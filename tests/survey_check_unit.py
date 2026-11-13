# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.survey_check and scripts/check_survey.py

Builds five synthetic surveys in the test's scratch folder and reads the
findings of `check_survey` and the lines and exit code of the command. A
site folder is one synthetic LEMI-423 file of `new_survey_unit.write_b423`;
a complete entry has a position, a span and a declination, and each planted
site lacks only what it plants.

The main survey: an unknown key on S01; a folder S09 with no entry; S10
with no folder and no archive, S11 with no folder and an archive; S02 with
no position; S03 with no declination; S04 with a 20-year span, S12 with no
start, end or declination; OB1, an Orange Box entry with no full scales;
PX1, a Phoenix entry whose `calibration_dir: sensors` does not exist; S05
with the old dipoles sentence in its notes, and its burst site S05H; S13
with azimuths 0 and 0; S06 with `remote: NOPE`; S07 with a stack of
stacks.yaml as remote and S08 with the folder S09 as remote; a derived
S01L and an observatory CNB, neither with a folder. The names survey holds
the names `A.1`, one of 28 characters with its `SL` site, one of 29, and a
folder `B.2` with no entry. The edges survey has a data root that does not
exist, seven sites with no position, spans and azimuths at the limits,
derived sites and an observatory with a span or an azimuth a recorded site
would be listed for, and entries a hand edit can leave: a name written as
a number, an entry that is one value, a bare header, a value of the wrong
kind. The clean survey has three complete sites. The last survey sits in a
folder with a blank in its name, is laid out to geographic north and has a
stacks.yaml that does not parse.

Usage:
    python tests/survey_check_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

- a planted site of the main survey does not get exactly its finding, by
  name and level: S01 site_refused (stop), S02 no_position, S03
  no_declination, S04 span_suspect, S05 dipoles_not_set, S06 remote_unknown,
  S09 folder_without_entry, S10 entry_without_folder, S13
  dipoles_not_perpendicular (warn), OB1 orangebox_full_scales and PX1
  phoenix_calibration (stop);
- S07, S08, S11, S12, the derived S01L, the burst site S05H or the
  observatory CNB gets a finding;
- the check changes a byte of survey.yaml, or leaves a new file beside it or
  in the data folder;
- a folder map given by the caller is not the one used;
- the command does not exit 1 on the main survey, or does not print one line
  per finding name, the stops first, the line on the usual dipoles (12
  sites with no dipole key of their own taking 50/50 m, 0/90 deg from
  magnetic north, 2 with their own) and the count (3 STOP and 8 WARN, naming
  11 of 18 sites);
- `usual_dipoles` counts a derived site, a burst site or an observatory, or
  the line does not give the built-in 0/0 m, 0/90 deg for a `defaults:`
  block with no dipole key;
- the message of no_declination does not say the value is recorded with
  the products and never applied to the data, or the command it names does
  not give S03 a declination, or changes the declination of another site;
- the command the message of orangebox_full_scales names does not clear
  OB1, removing the unknown key through `survey_file.edit` does not clear
  S01, PX1 is cleared by the calibration file of another receiver, or not by
  its own; or, with the three stops fixed, the command does not exit 0 with
  the eight warnings left;
- the command the message of remote_unknown names does not clear S06;
- `A.1`, the name of 29 characters or `B.2` does not give site_name (stop),
  `B.2` not folder_without_entry as well, or the name of 28 characters or
  its `SL` site gives any;
- the message of site_name for `A.1`, `B.2` or the name of 29 characters is
  not the refusal of `mt_workbench.survey.check_site_name`, which
  scripts/new_survey.py prints for a site folder, so the check and the
  command could disagree on a name;
- the edges survey does not give data_root_missing (stop), or lists a site
  for having no folder; a span that ends before it starts, ends when it
  starts, runs 401 days or has an end that is not a time is not listed, or
  one of 400 days is; azimuths 0 and 65, or one that is not a number, are
  not listed, or 45 and 135, 180 and 90 or 0 and 75 are; an Orange Box site
  with one full scale, or a Phoenix site with no `calibration_dir`, is not
  listed, or a Phoenix site with no serial and a calibration file in its
  folder is; a derived site or an observatory is listed for its span, its
  azimuths, its position, its full scales or its calibration, or a derived
  site with no declination is not listed;
- a site name written as a number does not give site_name, an entry that is
  one value, an unknown `instrument:` or a value of the wrong kind does not
  give site_refused, a bare header does not give no_position, or any of
  them stops the check;
- the command prints more than five site names on the line of a finding
  without `--all`, does not give the count of sites there, does not print
  one line per site with `--all`, or does not say whose message a line of
  several different messages carries;
- the clean survey, one of its sites a Phoenix site whose calibration
  folder is under the data root, prints a finding or does not exit 0, or,
  with its data root gone, does not give exactly data_root_missing and exit
  1;
- in a folder with a blank in its name the command a message names does
  not run as written; a survey laid out to geographic north is told its
  azimuths are from magnetic north; or a stacks.yaml that does not parse
  stops the check, or hides a remote that names no site;
- a file that does not parse, a file that is not there or a file with no
  `name:` does not exit 2 with a message.

The mutations this test catches, each made in a copy of the code: a rule
removed, for each of the eleven planted findings (the Orange Box rule: OB1
is not listed, while the exit code stays 1 through the other stops);
`entry_without_folder` not leaving out derived sites (S01L listed) or sites
with an archive (S11 listed); `span_suspect` on a missing start (S12
listed); a burst site checked as a recorded one (S05H listed); an
observatory taken as recorded (CNB listed); the stack names not read (S07
listed); a remote that is a folder with no entry refused (S08 listed); the
folder map of the caller not used; the name rule on derived sites, without
the pattern, with 27 as the limit, or not on a folder with no entry; the
check given a name rule of its own again; the
span and azimuth limits moved; the position, span, azimuth, full-scale
and calibration rules on derived sites, and the declination rule not on
them; the full scales asked for with `and`; the calibration file of any
receiver accepted, a serial required, or the data root not searched; the
level of a finding changed; each of the checks
for a hand-edited entry removed; the exit code 1 for a warning, or 0 with a
stop; the names on a line not cut at five; the note on a line of different
messages dropped; the folder findings made with no data root; the site
left out of the declination command;
`usual_dipoles` over every entry; the usual values taken from the built-in
ones, or from `defaults:` alone; the path in a command not quoted; the
north always magnetic; a stacks.yaml that does not parse not caught; and
each message with its command or its sentence on the declination changed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench import survey_check, survey_file  # noqa: E402
from mt_workbench.survey import Survey, check_site_name  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
import new_survey_unit as nsu  # noqa: E402  (the synthetic B423 writer)

SCRIPT = REPO / "scripts" / "check_survey.py"
SCRATCH = scratch_dir("survey_check_unit")
START, END = "2021-06-29T06:00:00Z", "2021-07-02T06:00:00Z"
# what a complete entry holds: a position, a span and a declination
FULL = {"latitude": -31.0, "longitude": 138.0, "start": START, "end": END, "declination": 7.9,
        "declination_model": "IGRF-14", "declination_epoch": 2021.5}
DECLINATION = ("declination", "declination_model", "declination_epoch")
OLD_NOTE = "dipole lengths and azimuths from defaults - set them from the field sheet"
RXCAL = "{serial}_5F0D1E2A.rxcal.json"
HEAD = """\
# survey for the survey_check test
name: {name}
instrument: lemi423
sample_rate: 1000
data_root: {root}
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  channels: [ex, ey, hx, hy]
{more}sites:
"""
STACKS = """\
STK_night:
  field: H
  use: remote
  members: [S02, S03]
"""
N28 = "LONGNAME_0123456789_ABCDEFGH"
N29 = N28 + "I"

failed: list[str] = []
n_checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global n_checks
    n_checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    if not ok:
        failed.append(name)


def site(*drop: str, **own) -> dict:
    """Return a complete entry without the keys of `drop`, with the keys of `own` added or replaced."""
    return {**{k: v for k, v in FULL.items() if k not in drop}, **own}


MAIN_SITES = {
    "S01": site(dipole_lenght_ex=48.0),
    "S02": site("latitude", "longitude"),
    "S03": site(*DECLINATION),
    "S04": site(start="2001-06-29T06:00:00Z"),
    "S05": site(notes=OLD_NOTE),
    "S05H": {"bursts_of": "S05", "sample_rate": 24000},
    "S06": site(remote="NOPE"),
    "S07": site(remote="STK_night"),
    "S08": site(remote="S09", dipole_length_ex=48.0),
    "S10": site(),
    "S11": site(),
    "S12": site("start", "end", *DECLINATION),
    "S13": site(azimuth_ey=0.0),
    "OB1": site(instrument="orangebox"),
    "PX1": site(instrument="phoenix", calibration_dir="sensors", serial="10443"),
    "S01L": site(derived_from="S01", sample_rate=1.0),
    "CNB": site(instrument="intermagnet", channels=["hx", "hy", "hz"]),
}
MAIN_FOLDERS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S12", "S13", "OB1", "PX1")
MAIN_EXPECTED = {
    "S01": [("site_refused", "stop")], "S02": [("no_position", "warn")], "S03": [("no_declination", "warn")],
    "S04": [("span_suspect", "warn")], "S05": [("dipoles_not_set", "warn")], "S06": [("remote_unknown", "warn")],
    "S09": [("folder_without_entry", "warn")], "S10": [("entry_without_folder", "warn")],
    "S13": [("dipoles_not_perpendicular", "warn")], "OB1": [("orangebox_full_scales", "stop")],
    "PX1": [("phoenix_calibration", "stop")],
}
MAIN_CLEAN = ("S07", "S08", "S11", "S12", "S01L", "S05H", "CNB")
STOPS = ("S01", "OB1", "PX1")

NAME_SITES = {"A.1": site(), N28: site(), N29: site(), N28 + "SL": site(derived_from=N28, sample_rate=1.0)}
NAME_FOLDERS = ("A.1", N28, N29, "B.2")
NAME_EXPECTED = {"A.1": [("site_name", "stop")], N29: [("site_name", "stop")],
                 "B.2": [("site_name", "stop"), ("folder_without_entry", "warn")]}

EDGE_SITES = {
    **{f"N{i}": site("latitude", "longitude") for i in range(1, 8)},
    "T1": site(end="2021-06-28T06:00:00Z"),
    "T2": site(end="2022-08-04T06:00:00Z"),
    "T3": site(end="2022-08-03T06:00:00Z"),
    "T4": site(end=START),
    "T5": site(end="unknown"),
    "Z1": site(azimuth_ex=45.0, azimuth_ey=135.0),
    "Z2": site(azimuth_ex=180.0, azimuth_ey=90.0),
    "Z3": site(azimuth_ey=75.0),
    "Z4": site(azimuth_ey=65.0),
    "Z5": site(azimuth_ey="east"),
    "OB2": site(instrument="orangebox", electric_full_scale_uv=25000.0),
    "PX2": site(instrument="phoenix", serial="10444"),
    "PX3": site(instrument="phoenix", calibration_dir="cal"),
    "T1L": site(derived_from="T1", sample_rate=1.0, end="2021-06-28T06:00:00Z"),
    "Z4D": site(derived_from="Z4", sample_rate=1000.0, azimuth_ex=45.0, channels=["ex", "hx", "hy"]),
    "T3L": site(*DECLINATION, derived_from="T3", sample_rate=1.0),
    "N1L": site("latitude", "longitude", derived_from="N1", sample_rate=1.0),
    "OB2L": site(derived_from="OB2", sample_rate=1.0),
    "PX2L": site(derived_from="PX2", sample_rate=1.0),
    "CTA": site(instrument="intermagnet", channels=["hx", "hy", "hz"], start="2013-09-01T00:00:00Z",
                end="2018-08-01T00:00:00Z"),
    101: site(),
    "X1": 50.0,
    "X2": site(instrument="lemi"),
    "X3": None,
    "X4": site(channels=5),
}
EDGE_EXPECTED = {
    None: [("data_root_missing", "stop")],
    **{f"N{i}": [("no_position", "warn")] for i in range(1, 8)},
    "T1": [("span_suspect", "warn")], "T2": [("span_suspect", "warn")], "T4": [("span_suspect", "warn")],
    "T5": [("span_suspect", "warn")], "Z4": [("dipoles_not_perpendicular", "warn")],
    "Z5": [("dipoles_not_perpendicular", "warn")], "OB2": [("orangebox_full_scales", "stop")],
    "PX2": [("phoenix_calibration", "stop")], "T3L": [("no_declination", "warn")],
    "101": [("site_name", "stop")], "X1": [("site_refused", "stop")], "X2": [("site_refused", "stop")],
    "X3": [("no_position", "warn")], "X4": [("site_refused", "stop")],
}
EDGE_CLEAN = ("T3", "Z1", "Z2", "Z3", "PX3", "T1L", "Z4D", "N1L", "OB2L", "PX2L", "CTA")


def load_script():
    spec = importlib.util.spec_from_file_location("check_survey", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(case: str, name: str, sites: dict, folders: tuple, root: bool = True, more: str = "") -> Path:
    """Write one survey: the data folder with a B423 file per site folder, and survey.yaml; return its path.

    An entry that is a mapping is written one key per line, None as a bare
    header, and any other value on the header line. `more` is added to the
    `defaults:` block.
    """
    base = SCRATCH / case
    shutil.rmtree(base, ignore_errors=True)
    raw = base / "raw"
    if root:
        raw.mkdir(parents=True)
    for folder in folders:
        nsu.write_b423(raw / folder / "1624949744.B423", 36, "2.1", -31.0, 138.0, 100.0, 1624949744, n=1)
    lines = [HEAD.format(name=name, root=raw.as_posix(), more=more)]
    for site_name, own in sites.items():
        if not isinstance(own, dict):
            lines.append(f"  {site_name}:{'' if own is None else f' {own}'}\n")
            continue
        lines.append(f"  {site_name}:\n")
        # the first line of the dump is the value on one line (a bare scalar is followed by a "..." line)
        lines += [f"    {key}: {yaml.safe_dump(value, default_flow_style=True, width=10 ** 9).splitlines()[0]}\n"
                  for key, value in own.items()]
    path = base / "survey" / "survey.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes("".join(lines).encode("utf-8"))
    return path


def by_site(path: Path) -> dict:
    """Return {site: [(finding name, level), ...]} of the survey, in the order found."""
    out: dict = {}
    for finding in survey_check.check_survey(Survey.from_yaml(path)):
        out.setdefault(finding.site, []).append((finding.name, finding.level))
    return out


def message(path: Path, site_name: str, finding: str) -> str:
    found = [f.message for f in survey_check.check_survey(Survey.from_yaml(path))
             if f.site == site_name and f.name == finding]
    return found[0] if found else ""


def compare(label: str, got: dict, expected: dict, clean: tuple) -> None:
    """Check each planted site's findings, each clean site's none, and that no other site is named."""
    for site_name, want in expected.items():
        check(f"{label}: {site_name or 'the survey'} gets exactly {', '.join(f'{n} ({v})' for n, v in want)}",
              got.get(site_name) == want, str(got.get(site_name)))
    for site_name in clean:
        check(f"{label}: {site_name} gets no finding", site_name not in got, str(got.get(site_name)))
    others = sorted(str(s) for s in set(got) - set(expected) - set(clean))
    check(f"{label}: no other site is named", not others, str({s: got.get(s) for s in others}))


def run(script, *args) -> tuple[int, str]:
    """Run the command's main in this process; return (exit code, stdout and stderr)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = script.main([str(a) for a in args])
        except SystemExit as exc:  # argparse leaves through SystemExit
            code = exc.code
    return code, out.getvalue()


def command(script_name: str, *args) -> subprocess.CompletedProcess:
    """Run a script of scripts/ as a command, with this repository's source first."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), os.environ.get("PYTHONPATH", "")])}
    return subprocess.run([sys.executable, str(REPO / "scripts" / script_name), *map(str, args)],
                          capture_output=True, text=True, env=env, cwd=REPO)


def named_command(text: str, script_name: str, last: str | None = None) -> list[str]:
    """Return the arguments of the `python scripts/<script_name>` command a message names, up to `last`."""
    words = shlex.split(text.split(f"python scripts/{script_name} ", 1)[1])
    return words[:words.index(last) + 1] if last else words


def files_under(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


# ------------------------------------------------------------------ the cases


def build_main() -> Path:
    path = build("main", "t_check", MAIN_SITES, MAIN_FOLDERS)
    (path.parent / "stacks.yaml").write_bytes(STACKS.encode("utf-8"))
    archive = path.parent / "work" / "mth5" / "S11.h5"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"")
    return path


def test_main_findings() -> None:
    path = build_main()
    before = (path.read_bytes(), files_under(path.parents[1]))
    compare("main", by_site(path), MAIN_EXPECTED, MAIN_CLEAN)
    after = (path.read_bytes(), files_under(path.parents[1]))
    check("the check changes no byte of survey.yaml and leaves no new file", before == after,
          str(sorted(set(after[1]) ^ set(before[1]))))
    survey = Survey.from_yaml(path)
    given = {name: folder for name, folder in survey.site_dirs().items() if name != "S07"}
    got = [f.name for f in survey_check.check_survey(survey, given) if f.site == "S07"]
    check("a folder map given by the caller is the one used: S07 left out of it has no folder",
          got == ["entry_without_folder"], str(got))
    counts = survey_check.usual_dipoles(survey)
    check("usual_dipoles: 12 recorded sites with no dipole key of their own, 2 with one", counts == (12, 2),
          str(counts))
    bare = Survey({"name": "t_bare", "data_root": str(SCRATCH / "none"), "sites": {"A1": {"latitude": 1.0}}},
                  SCRATCH / "none")
    text = survey_check.usual_dipoles_text(bare)
    check("with no dipole key in defaults: the line gives the built-in 0/0 m, 0/90 deg",
          "1 site(s) have no dipole key of their own and take 0/0 m, 0/90 deg from magnetic north; 0 have "
          "their own" in text, text)
    text = message(path, "S03", "no_declination")
    check("no_declination says the value is recorded with the products and never applied to the data",
          "recorded with the products and is never applied to the data" in text, text)


def test_main_command(script) -> None:
    path = build_main()
    code, out = run(script, path)
    lines = out.strip().splitlines()
    heads = [line.split(":")[0] for line in lines if line.startswith(("STOP ", "WARN "))]
    want = ["STOP site_refused", "STOP orangebox_full_scales", "STOP phoenix_calibration",
            "WARN folder_without_entry", "WARN entry_without_folder", "WARN no_position", "WARN no_declination",
            "WARN span_suspect", "WARN dipoles_not_set", "WARN dipoles_not_perpendicular", "WARN remote_unknown"]
    check("command on the main survey: exit 1", code == 1, f"exit {code}")
    check("command: one line per finding name, the stops first", heads == want, str(heads))
    check("command: a line gives the count of sites and their names",
          any(line.startswith("STOP orangebox_full_scales: 1 site(s): OB1: Orange Box full scales not set")
              for line in lines), out[:400])
    usual = [line for line in lines if line.startswith("dipoles and azimuths:")]
    check("command: the line on the usual dipoles gives 12 and 2, 50/50 m and 0/90 deg from magnetic north",
          len(usual) == 1 and "12 site(s) have no dipole key of their own and take 50/50 m, 0/90 deg from "
          "magnetic north; 2 have their own" in usual[0], str(usual))
    check("command: the last line counts 3 STOP and 8 WARN, naming 11 of 18 site(s)",
          lines[-1].startswith("3 STOP and 8 WARN, naming 11 of 18 site(s)"), lines[-1])
    done = command("check_survey.py", path)
    check("run as a command, the main survey exits 1", done.returncode == 1,
          f"exit {done.returncode}, {done.stderr.strip()[-200:]}")


def test_fixes() -> None:
    path = build_main()
    survey_file.edit(path, sites={"S01": {"dipole_lenght_ex": survey_file.REMOVE}})
    check("the unknown key removed through survey_file.edit clears S01", "S01" not in by_site(path),
          str(by_site(path).get("S01")))
    words = named_command(message(path, "OB1", "orangebox_full_scales"), "survey_set.py")
    done = command("survey_set.py", *words)
    check("the command the Orange Box message names clears OB1",
          done.returncode == 0 and Path(words[0]) == path and "OB1" not in by_site(path),
          f"exit {done.returncode}, {' '.join(words[1:])}, {done.stderr.strip()[-200:]}")
    sensors = path.parent / "sensors"
    sensors.mkdir()
    (sensors / RXCAL.format(serial="10555")).write_bytes(b"")
    text = message(path, "PX1", "phoenix_calibration")
    check("the calibration file of another receiver does not clear PX1, and the message names 10443 and the folder",
          "10443" in text and str(sensors) in text, text)
    (sensors / RXCAL.format(serial="10443")).write_bytes(b"")
    check("the calibration file of its own receiver clears PX1", "PX1" not in by_site(path),
          str(by_site(path).get("PX1")))
    warns = {s: v for s, v in MAIN_EXPECTED.items() if s not in STOPS}
    compare("the stops fixed", by_site(path), warns, MAIN_CLEAN + STOPS)
    done = command("check_survey.py", path)
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
    check("run as a command with the stops fixed: exit 0, 0 STOP and 8 WARN",
          done.returncode == 0 and last.startswith("0 STOP and 8 WARN"), f"exit {done.returncode}, {last}")

    words = named_command(message(path, "S03", "no_declination"), "declination.py", last="--write")
    done = command("declination.py", *words)
    sites = yaml.safe_load(path.read_bytes().decode("utf-8"))["sites"]
    got = sites["S03"].get("declination")
    check("the command the no_declination message names gives S03 a declination",
          done.returncode == 0 and isinstance(got, float) and "S03" not in by_site(path),
          f"exit {done.returncode}, {' '.join(words[1:])}, declination {got!r}, {done.stderr.strip()[-200:]}")
    others = {name: own.get("declination") for name, own in sites.items() if name != "S03" and "declination" in own}
    check("that command changes the declination of no other site",
          len(others) == 14 and set(others.values()) == {FULL["declination"]}, str(others))
    words = named_command(message(path, "S06", "remote_unknown"), "survey_set.py")
    done = command("survey_set.py", *words)
    check("the command the remote_unknown message names clears S06",
          done.returncode == 0 and "S06" not in by_site(path),
          f"exit {done.returncode}, {' '.join(words[1:])}, {done.stderr.strip()[-200:]}")


def test_names() -> None:
    path = build("names", "t_names", NAME_SITES, NAME_FOLDERS)
    compare("names", by_site(path), NAME_EXPECTED, (N28, N28 + "SL"))
    text = message(path, N29, "site_name")
    check("the message of a long name gives its length and the limit", "has 29 characters: 28 at most" in text, text)
    for name in ("A.1", "B.2", N29):
        try:
            check_site_name(name)
            refusal = None
        except ValueError as exc:
            refusal = str(exc)
        text = message(path, name, "site_name")
        check(f"the site_name message of {name} is the refusal of check_site_name, as new_survey.py prints it",
              refusal is not None and text == refusal, f"check {text!r}, library {refusal!r}")
    done = command("check_survey.py", path)
    check("run as a command, a refused site name exits 1", done.returncode == 1, f"exit {done.returncode}")


def test_edges(script) -> None:
    path = build("edges", "t_edges", EDGE_SITES, (), root=False)
    (path.parent / "cal").mkdir()
    (path.parent / "cal" / RXCAL.format(serial="10555")).write_bytes(b"")
    compare("edges", by_site(path), EDGE_EXPECTED, EDGE_CLEAN)
    for name, finding, words in (("T5", "span_suspect", "(not two times)"),
                                 ("Z5", "dipoles_not_perpendicular", "Ey azimuth east"),
                                 ("PX2", "phoenix_calibration", "calibration_dir is not set"),
                                 ("101", "site_name", "put it in quotes by hand ('101':)"),
                                 ("X1", "site_refused", "is the value 50.0, not a block of key: value lines"),
                                 ("X2", "site_refused", "unknown instrument 'lemi'"),
                                 ("X4", "site_refused", "a value in its entry has the wrong kind")):
        text = message(path, name, finding)
        check(f"edges: the message of {name} says {words!r}", words in text, text[:200])
    code, out = run(script, path)
    lines = out.strip().splitlines()
    line = next((x for x in lines if x.startswith("WARN no_position")), "")
    check("command: eight sites on one line, the count and the first five names only",
          line.startswith("WARN no_position: 8 site(s): N1, N2, N3, N4, N5 ...: has no position")
          and "N6" not in line and "N7" not in line and "X3" not in line, line[:120])
    line = next((x for x in lines if x.startswith("WARN span_suspect")), "")
    check("command: a line of different messages says whose it carries",
          line.startswith("WARN span_suspect: 4 site(s): T1, T2, T4, T5: span ")
          and line.endswith("(the message of T1; --all prints every site's)"), line[:80] + " ... " + line[-60:])
    check("command: the survey-wide finding has a line with no site",
          any(x.startswith("STOP data_root_missing: data folder ") for x in lines), lines[0][:120])
    check("command on the edges survey: exit 1 and the count", code == 1
          and lines[-1].startswith("7 STOP and 15 WARN, naming 21 of 32 site(s)"), f"exit {code}, {lines[-1]}")
    code, out = run(script, path, "--all")
    every = [x for x in out.splitlines() if x.startswith("WARN no_position: ")]
    spans = [x for x in out.splitlines() if x.startswith("WARN span_suspect: T")]
    check("command --all: one line per site, each with its own message",
          code == 1 and len(every) == 8 and len(spans) == 4
          and all(f"{t}: span " in x and f" {t} start=" in x for t, x in zip(("T1", "T2", "T4", "T5"), spans)),
          f"exit {code}, {len(every)} and {len(spans)} line(s)")


def test_clean(script) -> None:
    sites = {"C1": site(), "C2": site()}
    phoenix = {"C3": site(instrument="phoenix", calibration_dir="cal", serial="10443")}
    path = build("clean", "t_clean", {**sites, **phoenix}, ("C1", "C2", "C3"))
    cal = path.parents[1] / "raw" / "cal"
    cal.mkdir()
    (cal / RXCAL.format(serial="10443")).write_bytes(b"")
    code, out = run(script, path)
    lines = out.strip().splitlines()
    check("the clean survey: exit 0, no finding line, 0 STOP and 0 WARN in 3 sites",
          code == 0 and not [x for x in lines if x.startswith(("STOP", "WARN"))]
          and lines[-1].startswith("0 STOP and 0 WARN, naming 0 of 3 site(s)"), f"exit {code}, {out.strip()[:300]}")
    path = build("clean_no_root", "t_clean", sites, (), root=False)
    got = by_site(path)
    check("the clean survey with its data root gone: exactly data_root_missing (stop)",
          got == {None: [("data_root_missing", "stop")]}, str(got))
    done = command("check_survey.py", path)
    check("run as a command, a missing data root exits 1 and names the folder",
          done.returncode == 1 and f"data folder {path.parents[1] / 'raw'} not found" in done.stdout,
          f"exit {done.returncode}, {done.stdout.strip()[:200]}")


def test_blank_and_north() -> None:
    sites = {"G1": site(*DECLINATION), "G2": site(azimuth_ey=0.0), "G3": site(remote="STK_a")}
    path = build("two words", "t_blank", sites, ("G1", "G2", "G3"), more="  layout_north: geographic\n")
    (path.parent / "stacks.yaml").write_bytes(b"STK_a: [\n")
    got = by_site(path)
    compare("blank", got, {"G1": [("no_declination", "warn")], "G2": [("dipoles_not_perpendicular", "warn")],
                           "G3": [("remote_unknown", "warn")]}, ())
    text = message(path, "G2", "dipoles_not_perpendicular")
    check("a site laid out to geographic north: its azimuths are from geographic north",
          "Ex azimuth 0 and Ey azimuth 0 (deg from geographic north)" in text, text[:120])
    text = survey_check.usual_dipoles_text(Survey.from_yaml(path))
    check("a survey laid out to geographic north: the usual azimuths are from geographic north",
          "0/90 deg from geographic north" in text, text[:160])
    text = message(path, "G1", "no_declination")
    words = named_command(text, "declination.py", last="--write")
    done = command("declination.py", *words)
    check("a path with a blank is quoted, and the command named runs as written",
          f'"{path.as_posix()}"' in text and done.returncode == 0 and "G1" not in by_site(path),
          f"exit {done.returncode}, {words}, {done.stderr.strip()[-200:]}")


def test_unreadable(script) -> None:
    folder = SCRATCH / "unreadable"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    broken = folder / "survey.yaml"
    broken.write_bytes(b"name: t_bad\ndata_root: X\nsites:\n  S01:\n    notes: [open\n")
    code, out = run(script, broken)
    check("a file that does not parse: exit 2 and a message", code == 2 and "does not parse" in out,
          f"exit {code}, {out.strip()[:200]}")
    code, out = run(script, folder / "none.yaml")
    check("a file that is not there: exit 2 and a message", code == 2 and "not found" in out,
          f"exit {code}, {out.strip()[:200]}")
    nameless = folder / "nameless.yaml"
    nameless.write_bytes(b"data_root: X\nsites:\n  S01:\n    latitude: 1.0\n")
    code, out = run(script, nameless)
    check("a file with no name: exit 2 and a message", code == 2 and "is not a survey file" in out,
          f"exit {code}, {out.strip()[:200]}")
    done = command("check_survey.py", broken)
    check("run as a command, a file that does not parse exits 2", done.returncode == 2,
          f"exit {done.returncode}, {done.stderr.strip()[-200:]}")


def main() -> int:
    logger.remove()
    print(__doc__.split("**This test fails if**")[1].split("The mutations")[0].strip())
    print()
    script = load_script()
    tests = [(test_main_findings,), (test_main_command, script), (test_fixes,), (test_names,),
             (test_edges, script), (test_clean, script), (test_blank_and_north,), (test_unreadable, script)]
    for test, *args in tests:
        print(f"{test.__name__}:")
        try:
            test(*args)
        except Exception as exc:  # a crash of the code is a failure of the criterion under test
            check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  survey_check_unit ({len(failed)} of {n_checks} checks failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
