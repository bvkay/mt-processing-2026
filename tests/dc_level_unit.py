# -*- coding: utf-8 -*-
"""
Unit test for scripts/dc_level_check.py

Two sites are written with mth5 as MTH5 0.2.0 archives of int32 counts at
1000 Hz, the layout of the raw archives. S01 holds ex ey hx hy at the
levels of line C's healthy channels (+5e7, -3e7, +4.3e7, +3.9e7 counts)
with Gaussian noise of 2e6 counts and a 50 Hz sine of 1e6, in a 120 s run
sr1000_0001, and a 10 s run sr100_0002 at 100 Hz. S02 holds two 120 s runs:
ex (+2e7) and hy (+3.7e7) as healthy as S01's, ey at 1.6e9 counts with
Gaussian noise of 1e3 (MAD about 670 counts), the level of C05 ey and C13
ey, and hx (+4.1e7, noise 5e6) clipped at its own 95th percentile, so 5 %
of its samples sit at the rail. survey.yaml also declares S03 (no archive),
S01L (derived_from S01, with a 1 Hz archive whose ey sits at 1.6e9) and OBS
(instrument intermagnet). The script's main runs in-process on that
survey.

Usage:
    python tests/dc_level_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if a channel at 1.6e9 counts is not flagged as an open
input or a healthy channel is. In detail, it fails if: S02 ey of either run
is not "open input?", with a median within 1e4 counts of 1.6e9 and a MAD
below 2e3; any channel of S01, S02 ex or S02 hy is not "ok"; S02 hx is not
"saturated?" with 5 % to 8 % of its samples at the rail; S02 ey is not
flagged by the threshold alone (--ratio 1e6) or by the ratio alone
(--threshold-counts 1e12), with a ratio within 1 % of 40 (1.6e9 over the
median of the written electric levels |+5e7|, |-3e7|, |+2e7| twice and
1.6e9 twice, 4e7), or is flagged with both off; a subsample holds more than
--sample-seconds of samples or its step is not ceil(n / (S fs)); the table
is not ordered open input?, saturated?, ok and then by site; the summary
line does not name S02 ey as an open input in both runs and S02 hx as
saturated; S01L and OBS are checked instead of skipped with a note, S03 is
not listed as having no archive, or sr100_0002 is checked at 1000 Hz; the
exit status is not 0 for the report, 2 for S03 named and 2 for a missing
survey file; or the CSV does not hold the table's rows.

The mutation: with the rail share (`crust.dclevel.rail_fraction`, which
the script's measure calls) taken as the literal share of samples whose
|counts| are at least 90 % of the largest |counts|, the healthy
channels, whose DC level is many times their noise, come back "saturated?";
the test checks that it does, so the healthy criterion is shown able to
fail.
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from crust import dclevel  # noqa: E402

SCRIPT = REPO / "scripts" / "dc_level_check.py"
SCRATCH = scratch_dir("dc_level_unit")
SURVEY = "dc_level_unit"
FS = 1000.0
RUN_S = 120
SAMPLE_S = 20.0
T0 = pd.Timestamp("2023-09-25T15:00:00+00:00")
OPEN_LEVEL = 1.6e9
# {site: {run: (rate, {channel: (DC level, Gaussian noise sigma, 50 Hz amplitude, clip share)})}}
HEALTHY_E = {"ex": (5.0e7, 2.0e6, 1.0e6, 0.0), "ey": (-3.0e7, 2.0e6, 1.0e6, 0.0)}
HEALTHY_H = {"hx": (4.3e7, 2.0e6, 1.0e6, 0.0), "hy": (3.9e7, 2.0e6, 1.0e6, 0.0)}
S02_CHANNELS = {"ex": (2.0e7, 2.0e6, 1.0e6, 0.0), "ey": (OPEN_LEVEL, 1.0e3, 0.0, 0.0),
                "hx": (4.1e7, 5.0e6, 0.0, 0.05), "hy": (3.7e7, 2.0e6, 1.0e6, 0.0)}
ARCHIVES = {
    "S01": {"sr1000_0001": (FS, RUN_S, {**HEALTHY_E, **HEALTHY_H}),
            "sr100_0002": (100.0, 10, {**HEALTHY_E, **HEALTHY_H})},
    "S02": {"sr1000_0001": (FS, RUN_S, S02_CHANNELS), "sr1000_0002": (FS, RUN_S, S02_CHANNELS)},
    "S01L": {"sr1_0001": (1.0, 600, {"ex": (5.0e7, 2.0e6, 0.0, 0.0), "ey": (OPEN_LEVEL, 1.0e3, 0.0, 0.0)})},
}
HEALTHY = [("S01", "ex"), ("S01", "ey"), ("S01", "hx"), ("S01", "hy"), ("S02", "ex"), ("S02", "hy")]
EXPECTED_RATIO = OPEN_LEVEL / float(np.median([5e7, 3e7, 2e7, 2e7, OPEN_LEVEL, OPEN_LEVEL]))  # 40

SURVEY_YAML = """name: {name}
instrument: lemi423
sample_rate: 1000
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  S01:
    latitude: 31.6
    longitude: -5.6
  S02:
    latitude: 31.7
    longitude: -5.6
  S03:
    latitude: 31.8
    longitude: -5.6
  S01L:
    derived_from: S01
    sample_rate: 1.0
  OBS:
    instrument: intermagnet
    channels: [hx, hy, hz]
"""


def channel_samples(rng: np.random.Generator, n: int, fs: float, spec: tuple) -> np.ndarray:
    """Return a channel's int32 counts: DC level, Gaussian noise, a 50 Hz sine, clipped at a rail when asked."""
    level, sigma, amp50, clip = spec
    t = np.arange(n) / fs
    x = level + sigma * rng.standard_normal(n) + amp50 * np.sin(2 * np.pi * 50.0 * t)
    if clip:
        x = np.minimum(x, np.quantile(x, 1.0 - clip))
    return np.round(x).astype("int32")


def write_archive(path: Path, site: str, runs: dict, rng: np.random.Generator) -> None:
    """Write one site's MTH5 0.2.0 archive of int32 counts, runs back to back from T0."""
    from mth5.mth5 import MTH5

    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        station.write_metadata()
        start = T0
        for run_id, (fs, seconds, channels) in runs.items():
            n = int(seconds * fs)
            end = start + pd.Timedelta(seconds=(n - 1) / fs)
            run = station.add_run(run_id)
            for comp, spec in channels.items():
                kind = "electric" if comp.startswith("e") else "magnetic"
                ch = run.add_channel(comp, kind, channel_samples(rng, n, fs, spec))
                ch.metadata.component = comp
                ch.metadata.sample_rate = fs
                ch.metadata.time_period.start = str(start)
                ch.metadata.time_period.end = str(end)
                ch.metadata.units = "digital counts"
                ch.write_metadata()
            run.metadata.sample_rate = fs
            run.metadata.time_period.start = str(start)
            run.metadata.time_period.end = str(end)
            run.write_metadata()
            start = end + pd.Timedelta(seconds=60)
    finally:
        m.close_mth5()


def build() -> Path:
    """Write the archives and survey.yaml; return the survey.yaml path."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    root, work = SCRATCH / "raw", SCRATCH / "work"
    root.mkdir(parents=True)
    rng = np.random.default_rng(20260925)
    for site, runs in ARCHIVES.items():
        write_archive(work / "mth5" / f"{site}.h5", site, runs, rng)
    yaml_path = SCRATCH / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(name=SURVEY, root=root.as_posix(), work=work.as_posix()),
                         encoding="utf-8")
    return yaml_path


def load_script():
    """Import scripts/dc_level_check.py as a module."""
    spec = importlib.util.spec_from_file_location("dc_level_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, *argv: str) -> tuple[int, str, str]:
    """Run the script's main in-process; return (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = module.main([str(a) for a in argv])
    return status, out.getvalue(), err.getvalue()


def read_csv(path: Path) -> dict[tuple[str, str, str], dict]:
    """Read the script's CSV: {(site, run, channel): row}."""
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["site"], r["run"], r["channel"]): r for r in csv.DictReader(f)}


def table_rows(stdout: str) -> list[list[str]]:
    """Return the table's rows from the report, split on whitespace (the verdict kept whole)."""
    lines = stdout.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("site "))
    rows = []
    for ln in lines[first + 2:]:
        if not ln.strip():
            break
        head, verdict = ln.rsplit("  ", 1)
        rows.append(head.split() + [verdict.strip()])
    return rows


def main() -> None:
    yaml_path = build()
    module = load_script()
    out_csv = SCRATCH / "dc_level.csv"

    status, stdout, stderr = run_main(module, yaml_path, "--sample-seconds", SAMPLE_S, "--csv", out_csv)
    assert status == 0, f"exit {status}\n{stdout}\n{stderr}"
    print("\n".join("  " + ln for ln in stdout.splitlines()))
    rows = read_csv(out_csv)

    # the verdicts
    for run in ("sr1000_0001", "sr1000_0002"):
        ey = rows[("S02", run, "ey")]
        assert ey["verdict"] == "open input?", ey
        assert abs(float(ey["median_counts"]) - OPEN_LEVEL) < 1e4 and float(ey["mad_counts"]) < 2e3, ey
        hx = rows[("S02", run, "hx")]
        assert hx["verdict"] == "saturated?" and 0.05 <= float(hx["rail_fraction"]) <= 0.08, hx
    healthy = [r for (site, _run, comp), r in rows.items() if (site, comp) in HEALTHY]
    assert len(healthy) == 8, sorted(rows)
    bad = [(r["site"], r["run"], r["channel"], r["verdict"]) for r in healthy if r["verdict"] != "ok"]
    assert not bad, f"healthy channels flagged: {bad}"
    rails = [100 * float(rows[("S02", run, "hx")]["rail_fraction"]) for run in ("sr1000_0001", "sr1000_0002")]
    print(f"  S02 ey open input? in both runs; S02 hx saturated? ({rails[0]:.2f} %, {rails[1]:.2f} % at the "
          f"rail); {len(healthy)} healthy channel runs ok")

    # the ratio against the written levels
    ratio = float(rows[("S02", "sr1000_0001", "ey")]["ratio"])
    assert abs(ratio / EXPECTED_RATIO - 1.0) < 0.01, (ratio, EXPECTED_RATIO)

    # the subsample
    for (site, run, comp), r in rows.items():
        n, step, n_read = int(r["n_samples"]), int(r["step"]), int(r["n_read"])
        assert step == math.ceil(n / (SAMPLE_S * FS)) and n_read == math.ceil(n / step), r
        assert n_read <= SAMPLE_S * FS, r
    print(f"  subsample: {n} samples read every {step} -> {n_read} ({SAMPLE_S:g} s at {FS:g} Hz); "
          f"ratio of S02 ey {ratio:.2f} (expected {EXPECTED_RATIO:.2f})")

    # the table's order and the summary line
    table = table_rows(stdout)
    assert sorted((r[0], r[1], r[2], r[-1]) for r in table) == \
        sorted((s, run, c, r["verdict"]) for (s, run, c), r in rows.items()), "the CSV and the table differ"
    order = {"open input?": 0, "saturated?": 1, "ok": 2}
    keys = [(order[r[-1]], r[0]) for r in table]
    assert keys == sorted(keys), keys
    summary = next(ln for ln in stdout.splitlines() if ln.startswith("summary:"))
    assert "open input? S02 ey (sr1000_0001, sr1000_0002)" in summary, summary
    assert "saturated? S02 hx (sr1000_0001, sr1000_0002)" in summary, summary
    assert summary.startswith("summary: 4 of 12 channel runs flagged"), summary

    # skipped sites and runs
    assert "skipped (derived): S01L" in stdout.splitlines(), stdout
    assert "skipped (observatory): OBS" in stdout.splitlines(), stdout
    assert "skipped (no archive): S03" in stdout.splitlines(), stdout
    assert not any(site in ("S01L", "OBS") for site, _r, _c in rows), sorted(rows)
    assert not any(run == "sr100_0002" for _s, run, _c in rows) and "left out: sr100_0002 at 100 Hz" in stdout
    print("  S01L and OBS skipped with a note, S03 listed without an archive, sr100_0002 left out at 1000 Hz")

    # each level criterion alone, and both off
    _s, only_threshold, _e = run_main(module, yaml_path, "S02", "--ratio", "1e6", "--sample-seconds", SAMPLE_S)
    _s, only_ratio, _e = run_main(module, yaml_path, "S01", "S02", "--threshold-counts", "1e12",
                                  "--sample-seconds", SAMPLE_S)
    _s, neither, _e = run_main(module, yaml_path, "S01", "S02", "--threshold-counts", "1e12", "--ratio", "1e6",
                               "--sample-seconds", SAMPLE_S)

    def verdicts(stdout_text: str, comp: str) -> set[str]:
        return {r[-1] for r in table_rows(stdout_text) if r[0] == "S02" and r[2] == comp}

    assert verdicts(only_threshold, "ey") == {"open input?"}, only_threshold
    assert verdicts(only_ratio, "ey") == {"open input?"}, only_ratio
    assert verdicts(neither, "ey") == {"ok"}, neither
    print("  S02 ey flagged by the 1e9 threshold alone and by the 30 x ratio alone; ok with both off")

    # exit status
    status, _o, err = run_main(module, yaml_path, "S01", "S03")
    assert status == 2 and "S03: no archive" in err, (status, err)
    status, _o, err = run_main(module, SCRATCH / "absent.yaml")
    assert status == 2 and "no survey file" in err, (status, err)
    print("  exit 2 for S03 named without an archive and for a missing survey file")

    # the mutation: the literal |counts| share at the rail
    literal = dclevel.rail_fraction
    dclevel.rail_fraction = lambda x, median: float(np.mean(np.abs(x) >= 0.9 * np.abs(x).max()))
    try:
        _s, mutant, _e = run_main(module, yaml_path, "S01", "S02", "--sample-seconds", SAMPLE_S)
    finally:
        dclevel.rail_fraction = literal
    tripped = [r for r in table_rows(mutant) if (r[0], r[2]) in HEALTHY and r[-1] != "ok"]
    assert tripped, mutant
    print(f"  mutation |counts| >= 90 % of max|counts|: {len(tripped)} of 8 healthy channel runs come back "
          f"{sorted({r[-1] for r in tripped})}, e.g. {tripped[0][0]} {tripped[0][1]} {tripped[0][2]} "
          f"at {tripped[0][-2]} % -- the healthy criterion trips")


if __name__ == "__main__":
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\n")[0])
    print()
    main()
    print("\nPASS  dc_level_unit")
