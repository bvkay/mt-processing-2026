# -*- coding: utf-8 -*-
"""
Unit test for the batch mode of scripts/ingest_site.py

**This test fails if**

- (a) `--all --parallel 2` does not exit 0, build S02.h5 and S03.h5, keep S01.h5 (mtime unchanged), log S02, S03 in <workspace>/logs;
- (b) its summary does not list exactly S01 kept, S02 built with its variant, S03 built, or the run does not name S09 as skipped;
- (c) the named S01 S02, built in this process, do not exit 0 with S01 kept (mtime unchanged), S02 built, a summary of those two;
- (d) with S04 holding one unreadable file, `--all --parallel 2` or `S04 S03` in this process do not exit 1 and build the rest;
- (e) S04's row is not failed with its ValueError's first line, the same in both batches, or an S04.h5 is left behind;
- (f) a single-site call prints other script lines than the single-site script printed before the batch mode, on the same calls;
- (mutations) (a) and (b) pass a batch given --force, which rebuilds S01, or (d) and (e) pass a script that lets S04's error end the batch.

The survey is written into a scratch folder: three LEMI-423 sites S01, S02
and S03 of one synthetic B423 file each (4 s at 1000 Hz, written by
`mtio_fork_unit._write_b423`), S09 declared in survey.yaml with no raw
folder, and a 50 Hz notch declared for S02 in filters.yaml, so S02 also has
a variant. S01's raw archive is built first by a single-site call. Every
check runs the script in a process of its own with the interpreter
MTPROC_PYTHON names (this one by default), which needs the processing
environment (aurora, mth5, mt-io).

The lines of (f) are those the single-site script printed on the same calls
before the batch mode: "ingesting <site> (lemi423) from <raw folder>
(LEMI-423 runs of at most <MAX_RUN_FILES> files) -> <archive>", "archive:
<archive>", then "variant: none (no declared filters)", or "building
<site>'s variant (1 declared filter(s)) -> <variant>" and "variant:
<variant>" for S02. A second call on S01 exits 2 with "ERROR <archive>
exists: pass --force to rebuild it" on stderr and prints no script line, and
`--variant` on S02's current variant prints "variant: <variant> (already
current)". The time-stamped log lines are left out of the comparison.

The mutation of (d) and (e) replaces `except (Exception, SystemExit) as
exc:` in `run_here` with `except SystemExit as exc:` in a copy of the
script, so the first failing site ends the batch.

Usage:
    python tests/ingest_site_cli_unit.py
    MTPROC_PYTHON=<processing env python> python -m pytest tests/ingest_site_cli_unit.py -q

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRIPT = REPO / "scripts" / "ingest_site.py"
PY = os.environ.get("MTPROC_PYTHON", sys.executable)
SCRATCH = scratch_dir("ingest_site_cli_unit")
SITES = {"S01": 1624510579, "S02": 1624596979, "S03": 1624683379}  # site -> the epoch of its one B423 file
UNREADABLE = ("S04", 1624769779)
NOTCH = [{"notch": {"f0": 50, "harmonics": 1, "q": 30, "passes": 2}}]
MAX_RUN_FILES = int(re.search(r"^MAX_RUN_FILES = (\d+)",
                              (REPO / "scripts" / "process_rr.py").read_text(encoding="utf-8"), re.M).group(1))
# the lines the script prints itself, in one-site and batch form
SCRIPT_LINE = re.compile(r"^(?:ingesting |archive: |building |variant: |removed the partial |batch of |summary |"
                         r"skipping |\[\d+/\d+\] |\S+: (?:kept|started|built|failed) )")
ROW = re.compile(r"^(?P<site>\S+)\s{2,}(?P<archive>.+?)\s{2,}(?P<variant>.+?)\s{2,}(?P<seconds>\d+\.\d)\s{2,}"
                 r"(?P<status>built|kept|failed)(?:: (?P<error>.*))?$")
S04_ERROR = "ValueError: S04: none of the 1 B423 files can be read"
VARIANT = r"S02_f[0-9a-f]{8}\.h5"
EXPECTED_ALL = {"S01": (r"S01\.h5 kept", "none", "kept"),
                "S02": (r"S02\.h5 built", VARIANT + " built", "built"),
                "S03": (r"S03\.h5 built", "none", "built")}
EXPECTED_NAMED = {"S01": EXPECTED_ALL["S01"], "S02": EXPECTED_ALL["S02"]}
MUTATION = ("        except (Exception, SystemExit) as exc:\n", "        except SystemExit as exc:\n")


def make_survey(name: str, unreadable: bool = False) -> Path:
    """Write the synthetic survey of the module docstring into a fresh scratch folder.

    Args:
        name (str): Name of the folder under the test's scratch directory.
        unreadable (bool): Add S04, whose raw folder holds one 100-byte B423 file.

    Returns:
        Path: The survey.yaml.
    """
    root = SCRATCH / name
    shutil.rmtree(root, ignore_errors=True)
    for site, epoch in SITES.items():
        (root / "raw" / site).mkdir(parents=True)
        _write_b423(root / "raw" / site / f"{epoch}.B423", epoch=epoch, n=4000)
    sites = {site: {} for site in (*SITES, "S09")}
    if unreadable:
        site, epoch = UNREADABLE
        (root / "raw" / site).mkdir()
        (root / "raw" / site / f"{epoch}.B423").write_bytes(bytes(100))
        sites[site] = {}
    config = {"name": "synthetic", "instrument": "lemi423", "sample_rate": 1000,
              "data_root": str(root / "raw"), "workspace": str(root / "work"),
              "defaults": {"channels": ["ex", "ey", "hx", "hy"], "dipole_length_ex": 50.0,
                           "dipole_length_ey": 50.0, "azimuth_ex": 0.0, "azimuth_ey": 90.0},
              "sites": sites}
    (root / "survey.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (root / "filters.yaml").write_text(yaml.safe_dump({"S02": NOTCH}), encoding="utf-8")
    return root / "survey.yaml"


def archive(survey_yaml: Path, site: str) -> Path:
    """Return a site's raw archive path in the scratch survey."""
    return survey_yaml.parent / "work" / "mth5" / f"{site}.h5"


def run(*args, script: Path = SCRIPT) -> subprocess.CompletedProcess:
    """Run the script (or a copy of it) with `args`, output captured as text."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if script != SCRIPT:  # a copy outside the repo finds mtproc and process_rr.py on PYTHONPATH
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO / "src"), str(REPO / "scripts"),
                                                          env.get("PYTHONPATH"))))
    return subprocess.run([PY, str(script), *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=900)


@lru_cache(maxsize=None)
def premise() -> None:
    """Check that the interpreter runs the script at all."""
    done = run("--help")
    assert done.returncode == 0, (f"{PY} cannot run {SCRIPT.name}: set MTPROC_PYTHON to the processing "
                                  f"environment's python\n{done.stderr[-800:]}")


def prebuilt(name: str, unreadable: bool = False) -> tuple[Path, int]:
    """Write a scratch survey and build S01's raw archive with a single-site call.

    Returns:
        tuple[Path, int]: The survey.yaml and S01.h5's mtime in ns.
    """
    premise()
    survey_yaml = make_survey(name, unreadable)
    done = run(survey_yaml, "S01")
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    return survey_yaml, archive(survey_yaml, "S01").stat().st_mtime_ns


def script_lines(text: str) -> list[str]:
    """Return the lines of `text` the script printed itself."""
    return [line for line in text.splitlines() if SCRIPT_LINE.match(line)]


def summary(stdout: str) -> dict[str, dict]:
    """Parse the batch's summary table into {site: row}; {} when there is none."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^site\s+archive\s+variant\s+seconds\s+status$",
                                                                line)), None)
    rows = {}
    for line in lines[start + 1:] if start is not None else []:
        match = ROW.match(line)
        if match is None:
            break
        rows[match["site"]] = match.groupdict()
    return rows


def table(stdout: str) -> str:
    """Return the summary block of a batch's output, for printing."""
    lines = stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("summary (")), len(lines))
    end = next((i for i in range(start, len(lines)) if re.match(r"^\d+ site\(s\): ", lines[i])), len(lines) - 1)
    return "\n".join("    " + line for line in lines[start:end + 1])


def check_kept(path: Path, mtime_ns: int) -> tuple[bool, str]:
    """Check that an archive is still there with the modification time it had."""
    if not path.exists():
        return False, f"{path.name} is gone"
    now = path.stat().st_mtime_ns
    return now == mtime_ns, f"{path.name} mtime {mtime_ns} -> {now}"


def check_rows(rows: dict, expected: dict) -> tuple[bool, str]:
    """Check the summary rows against {site: (archive regex, variant regex, status)}."""
    if set(rows) != set(expected):
        return False, f"summary sites {sorted(rows)}, wanted {sorted(expected)}"
    for site, (archive_cell, variant_cell, status) in expected.items():
        row = rows[site]
        if not (re.fullmatch(archive_cell, row["archive"]) and re.fullmatch(variant_cell, row["variant"])
                and row["status"] == status):
            return False, (f"{site} row {row['archive']!r} {row['variant']!r} {row['status']!r}, wanted "
                           f"{archive_cell!r} {variant_cell!r} {status!r}")
    return True, "; ".join(f"{s} {r['status']}" for s, r in rows.items())


def check_failure(done: subprocess.CompletedProcess, survey_yaml: Path, built: list[str]) -> tuple[bool, str]:
    """Check a batch in which S04 fails: exit 1, S04 failed on its error, no S04.h5, `built` built."""
    rows = summary(done.stdout)
    if done.returncode != 1:
        return False, f"exit {done.returncode}"
    s04 = rows.get("S04")
    if s04 is None or s04["status"] != "failed" or not (s04["error"] or "").startswith(S04_ERROR):
        return False, f"S04 row {s04}"
    if archive(survey_yaml, "S04").exists():
        return False, "S04.h5 left behind"
    for site in built:
        if site not in rows or rows[site]["status"] != "built" or not archive(survey_yaml, site).exists():
            return False, f"{site} row {rows.get(site)}, archive exists {archive(survey_yaml, site).exists()}"
    return True, f"S04 failed: {s04['error']}; built {built}"


def test_a_b_all_parallel() -> None:
    survey_yaml, s01_mtime = prebuilt("all_parallel")
    done = run(survey_yaml, "--all", "--parallel", 2)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    ok, detail = check_kept(archive(survey_yaml, "S01"), s01_mtime)
    assert ok, f"(a) {detail}"
    assert archive(survey_yaml, "S02").exists() and archive(survey_yaml, "S03").exists(), "(a) S02.h5 or S03.h5 missing"
    logs = sorted(p.name for p in (survey_yaml.parent / "work" / "logs").glob("*.log"))
    assert logs == ["ingest_S02.log", "ingest_S03.log"], f"(a) logs {logs}"
    assert all(f"archive: {archive(survey_yaml, s)}" in (survey_yaml.parent / "work" / "logs" / f"ingest_{s}.log")
               .read_text(encoding="utf-8") for s in ("S02", "S03")), "(a) a log lacks its archive: line"
    ok, detail = check_rows(summary(done.stdout), EXPECTED_ALL)
    assert ok, f"(b) {detail}"
    assert "skipping S09: no raw data folder under" in done.stdout, "(b) S09 not named as skipped"
    print(f"  (a)(b) --all --parallel 2: exit 0, S01.h5 mtime unchanged, logs {logs}\n{table(done.stdout)}")


def test_c_named_in_process() -> None:
    survey_yaml, s01_mtime = prebuilt("named")
    done = run(survey_yaml, "S01", "S02")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    ok, detail = check_kept(archive(survey_yaml, "S01"), s01_mtime)
    assert ok, f"(c) {detail}"
    ok, detail = check_rows(summary(done.stdout), EXPECTED_NAMED)
    assert ok, f"(c) {detail}"
    assert f"archive: {archive(survey_yaml, 'S02')}" in script_lines(done.stdout), "(c) S02's archive: line missing"
    assert not (survey_yaml.parent / "work" / "logs").exists(), "(c) an in-process batch wrote logs"
    print(f"  (c) S01 S02 in this process: exit 0, {detail}")


def test_d_e_failure() -> None:
    premise()
    survey_yaml = make_survey("failure", unreadable=True)
    parallel = run(survey_yaml, "--all", "--parallel", 2)
    ok, detail = check_failure(parallel, survey_yaml, ["S01", "S02", "S03"])
    assert ok, f"(d)(e) --parallel 2: {detail}\n{parallel.stdout[-3000:]}{parallel.stderr[-3000:]}"
    print(f"  (d)(e) --all --parallel 2: exit 1, {detail}\n{table(parallel.stdout)}")
    archive(survey_yaml, "S03").unlink()
    here = run(survey_yaml, "S04", "S03")
    ok, detail = check_failure(here, survey_yaml, ["S03"])
    assert ok, f"(d)(e) in this process: {detail}\n{here.stdout[-3000:]}{here.stderr[-3000:]}"
    errors = {summary(parallel.stdout)["S04"]["error"], summary(here.stdout)["S04"]["error"]}
    assert len(errors) == 1, f"(e) S04's error differs between the two batches: {errors}"
    print(f"  (d)(e) S04 S03 in this process: exit 1, {detail}")


def test_f_single_site() -> None:
    premise()
    survey_yaml = make_survey("single")
    raw, s01, s02 = survey_yaml.parent / "raw", archive(survey_yaml, "S01"), archive(survey_yaml, "S02")

    def ingesting(site: str, out: Path) -> str:
        return (f"ingesting {site} (lemi423) from {raw / site} (LEMI-423 runs of at most {MAX_RUN_FILES} files) "
                f"-> {out}")

    first = run(survey_yaml, "S01")
    want = [ingesting("S01", s01), f"archive: {s01}", "variant: none (no declared filters)"]
    assert first.returncode == 0 and script_lines(first.stdout) == want, (first.returncode, script_lines(first.stdout))
    second = run(survey_yaml, "S02")
    variants = sorted(s02.parent.glob("S02_f*.h5"))
    assert len(variants) == 1 and re.fullmatch(VARIANT, variants[0].name), variants
    want = [ingesting("S02", s02), f"archive: {s02}",
            f"building S02's variant (1 declared filter(s)) -> {variants[0]}", f"variant: {variants[0]}"]
    assert second.returncode == 0 and script_lines(second.stdout) == want, (second.returncode,
                                                                            script_lines(second.stdout))
    again = run(survey_yaml, "S01")
    assert again.returncode == 2 and script_lines(again.stdout) == [], (again.returncode, script_lines(again.stdout))
    assert f"ERROR {s01} exists: pass --force to rebuild it" in again.stderr.splitlines(), again.stderr[-2000:]
    current = run(survey_yaml, "S02", "--variant")
    want = [f"variant: {variants[0]} (already current)"]
    assert current.returncode == 0 and script_lines(current.stdout) == want, script_lines(current.stdout)
    print(f"  (f) S01, S02, S01 again (exit 2), S02 --variant: the single-site lines, e.g. "
          f"{script_lines(second.stdout)[-1]!r}")


def test_mutation_force_trips_a_b() -> None:
    survey_yaml, s01_mtime = prebuilt("mutation_force")
    done = run(survey_yaml, "--all", "--parallel", 2, "--force")
    kept, kept_detail = check_kept(archive(survey_yaml, "S01"), s01_mtime)
    rows, rows_detail = check_rows(summary(done.stdout), EXPECTED_ALL)
    assert not kept, f"(a) passed a batch that rebuilt S01: {kept_detail}"
    assert not rows, f"(b) passed a batch that rebuilt S01: {rows_detail}"
    print(f"  (mutation) --force: (a) trips ({kept_detail}), (b) trips ({rows_detail})")


def test_mutation_escape_trips_d_e() -> None:
    premise()
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count(MUTATION[0]) == 1, "the mutation target is not in the script exactly once"
    mutant = SCRATCH / "mutant" / "ingest_site.py"
    mutant.parent.mkdir(parents=True, exist_ok=True)
    mutant.write_text(text.replace(*MUTATION), encoding="utf-8")
    survey_yaml = make_survey("mutation_escape", unreadable=True)
    done = run(survey_yaml, "S04", "S03", script=mutant)
    ok, detail = check_failure(done, survey_yaml, ["S03"])
    assert not ok, f"(d)(e) passed the mutant that lets S04's exception end the batch: {detail}"
    print(f"  (mutation) exception let through: (d)(e) trip ({detail}; S03.h5 exists "
          f"{archive(survey_yaml, 'S03').exists()})")


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("The survey is written")[0].strip())
    print()
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        else:
            print(f"  ok    {test.__name__}")
    print(f"\n{'FAIL' if failed else 'PASS'}  ingest_site_cli_unit ({len(tests) - len(failed)} of {len(tests)} passed)")
    sys.exit(1 if failed else 0)
