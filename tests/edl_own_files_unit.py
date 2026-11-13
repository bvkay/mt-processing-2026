# -*- coding: utf-8 -*-
"""
Unit test for the EDL station rule of mt_workbench.instruments (`_edl_own_files`)

Builds synthetic PR6-24 site folders of empty files in a fresh scratch
folder: channel files with real PR6-24 names (``<STATION>YYMMDDhhmmss.BX``
as GA's AusLAMP Victoria folders write them, ``<STATION>_YYMMDDhhmmss.EX``
as Tasmania's do; one file a stamp, the five channels in turn) in ``DDD/``
day folders, a day log that is not a record, and a ``config/recorder.ini``
naming a station (none in cases c and i). Each case lists its folder with
`record_files(site, "edl")`, which reads recorder.ini through mt-io and
passes the files to `_edl_own_files`, and checks the kept files and the
warnings. Workbench issue 73: GA's VIC041 holds an ini naming VIC66 beside
2,975 VIC41 files, and the rule kept the one VIC66 file.

Usage:
    python tests/edl_own_files_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(a) folder VIC041, ini VIC66, 1 VIC66 stamp and 10 VIC41 stamps: the kept
    files are not the 10 VIC41 files, or the warnings are not one naming
    'VIC66' (1 file(s)) and 'VIC41' (10 file(s)) and one naming the VIC66
    file left out;
(b) folder VIC100, ini VIC100, 10 VIC100 stamps and 1 VIC1003 stamp: the
    kept files are not the 10 VIC100 files (VIC1003 merged into VIC100 by
    the normalisation), or the warnings are not the one naming VIC1003
    left out;
(c) no recorder.ini, folder site_3 named for neither of two stations (AAA1
    4 stamps, BBB2 6): a file is left out or a warning is logged;
(d) folder site_7, ini OLD5_, 3 OLD5 stamps and 10 NEW7 stamps: the kept
    files are not the 10 NEW7 files (the plurality), or the warnings are
    not one naming 'OLD5' (3 file(s)) and 'NEW7' (10 file(s)) and one
    naming the OLD5 files left out;
(e) folder site_7, ini OLD5_, 10 OLD5 and 3 NEW7: the kept files are not
    the 10 OLD5 files (recorder.ini's station is the plurality), or the
    warnings are not the one naming NEW7 left out;
(f) folder site_8, ini OLD5_, 5 OLD5 and 5 NEW8 (a tie): the kept files are
    not the 5 OLD5 files, or the warnings are not the one naming NEW8 left
    out;
(g) `_edl_station_key` does not make VIC041 ~ VIC41, vic41 ~ VIC41,
    VIC074a ~ VIC74A and TAS100 ~ TAS100, or makes VIC1003 ~ VIC100 or
    TAS201LP ~ TAS201;
(h) folder EDLZ, ini RENAMED_ naming no file's station, 10 EDLZ and 3 PLB03
    stamps: the kept files are not the 10 EDLZ files (the folder's name
    comes before the every-file-kept fallback; the old rule kept all 13),
    or the warnings are not one naming 'RENAMED' (0 file(s)) and 'EDLZ'
    (10 file(s)) and one naming the PLB03 files left out;
(i) no recorder.ini, folder TST01, 10 TST01 and 3 OTH9 stamps: the kept
    files are not the 10 TST01 files, or the warnings are not the one
    naming OTH9 left out (no ini, so no warning naming one);
(j) folder site_9, ini OLD5_, 2 OLD5 and 5 each of BBB9 and AAA9 (two
    other stations tie for the most): the kept files are not AAA9's (the
    first by name), or the warnings are not one naming 'OLD5' (2 file(s))
    and 'AAA9' (5 file(s)) and one naming BBB9 and OLD5 left out;
(k) folder site_5 named for no station, ini RENAMED_ naming no file's
    station, AAA1 4 and BBB2 6 stamps: a file is left out (the unchanged
    fallback), or the warnings are not the one saying no file carries
    'renamed' and every file is kept.

The mutation: with the old rule restored (`_old_rule`, the function as it
stood before issue 73's fix: recorder.ini's station whenever a file carries
it, else every file), cases (a) and (d) must fail, and so must (h), (i) and
(j), whose outcome the fix changes too; (b), (c), (e), (f) and (k) must pass
under both rules.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.instruments as instruments  # noqa: E402
from mt_workbench.instruments import _edl_station_key, file_start, record_files  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

INI = "[recorder]\nstation_long_identifier = {}\nchannel_0_samplerate = 10\nchannel_1_samplerate = 10\n"
CHANNELS = ("BX", "BY", "BZ", "EX", "EY")
T0 = datetime(2013, 11, 25, 7)

# case: (site folder, recorder.ini's station or None, [(station, separator, stamps, first stamp)],
#        the station whose files are kept (None: every file), [the fragments of each expected warning, in order])
CASES = {
    "a": ("VIC041", "VIC66", [("VIC41", "", 10, T0), ("VIC66", "", 1, datetime(2013, 12, 28, 22, 3, 11))], "VIC41",
          [["VIC041: recorder.ini names station 'VIC66' (1 file(s))", "'VIC41' (10 file(s))", "site folder"],
           ["VIC041: 1 EDL file(s)", "than the kept 'VIC41'", "VIC66 (1 from 2013-12-28 22:03)"]]),
    "b": ("VIC100", "VIC100", [("VIC100", "", 10, T0), ("VIC1003", "", 1, T0 + timedelta(hours=3))], "VIC100",
          [["VIC100: 1 EDL file(s)", "than recorder.ini's 'vic100'", "VIC1003 (1 from 2013-11-25 10:00)"]]),
    "c": ("site_3", None, [("AAA1", "_", 4, T0), ("BBB2", "_", 6, T0 + timedelta(days=40))], None, []),
    "d": ("site_7", "OLD5_", [("OLD5", "_", 3, T0 - timedelta(days=300)), ("NEW7", "_", 10, T0)], "NEW7",
          [["site_7: recorder.ini names station 'OLD5' (3 file(s))", "'NEW7' (10 file(s))", "most files"],
           ["site_7: 3 EDL file(s)", "than the kept 'NEW7'", "OLD5 (3 from 2013-01-29 07:00)"]]),
    "e": ("site_7", "OLD5_", [("OLD5", "_", 10, T0), ("NEW7", "_", 3, T0 + timedelta(days=300))], "OLD5",
          [["site_7: 3 EDL file(s)", "than recorder.ini's 'old5'", "NEW7 (3 from 2014-09-21 07:00)"]]),
    "f": ("site_8", "OLD5_", [("OLD5", "_", 5, T0), ("NEW8", "_", 5, T0 + timedelta(days=30))], "OLD5",
          [["site_8: 5 EDL file(s)", "than recorder.ini's 'old5'", "NEW8 (5 from 2013-12-25 07:00)"]]),
    "h": ("EDLZ", "RENAMED_", [("EDLZ", "_", 10, T0), ("PLB03", "_", 3, T0 - timedelta(days=30))], "EDLZ",
          [["EDLZ: recorder.ini names station 'RENAMED' (0 file(s))", "'EDLZ' (10 file(s))", "site folder"],
           ["EDLZ: 3 EDL file(s)", "than the kept 'EDLZ'", "PLB03 (3 from 2013-10-26 07:00)"]]),
    "i": ("TST01", None, [("TST01", "_", 10, T0), ("OTH9", "_", 3, T0 + timedelta(days=5))], "TST01",
          [["TST01: 3 EDL file(s)", "than the kept 'TST01'", "OTH9 (3 from 2013-11-30 07:00)"]]),
    "j": ("site_9", "OLD5_", [("OLD5", "_", 2, T0), ("BBB9", "_", 5, T0 + timedelta(days=1)),
                              ("AAA9", "_", 5, T0 + timedelta(days=2))], "AAA9",
          [["site_9: recorder.ini names station 'OLD5' (2 file(s))", "'AAA9' (5 file(s))", "most files"],
           ["site_9: 7 EDL file(s)", "than the kept 'AAA9'", "BBB9 (5 from 2013-11-26 07:00)",
            "OLD5 (2 from 2013-11-25 07:00)"]]),
    "k": ("site_5", "RENAMED_", [("AAA1", "_", 4, T0), ("BBB2", "_", 6, T0 + timedelta(days=40))], None,
          [["site_5: no EDL file carries recorder.ini's station 'renamed': every file kept"]]),
}
OLD_RULE_FAILS = {"a", "d", "h", "i", "j"}  # the cases the old rule must fail (the mutation)
KEY_PAIRS = [("VIC041", "VIC41", True), ("vic41", "VIC41", True), ("VIC074a", "VIC74A", True),
             ("VIC1003", "VIC100", False), ("TAS100", "TAS100", True), ("TAS201LP", "TAS201", False)]


def _old_rule(site_dir: Path, found: list[Path]) -> list[Path]:
    """Return the files `_edl_own_files` kept before issue 73's fix (the mutation): recorder.ini's station first."""
    import pandas as pd
    from loguru import logger
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import parse_edl_station

    own = str(UoACollection(site_dir).read_recorder_ini().get("station") or "").strip().rstrip("_-").lower()
    if not own:
        return found
    keep, other = [], {}
    for f in found:
        name = (parse_edl_station(f) or "").rstrip("_-")
        if name.lower() == own:
            keep.append(f)
        else:
            other.setdefault(name or "?", []).append(f)
    if not keep:
        logger.warning(f"{site_dir.name}: no EDL file carries recorder.ini's station {own!r}: every file kept")
        return found
    if other:
        logger.warning(f"{site_dir.name}: {sum(len(v) for v in other.values())} EDL file(s) named for another "
                       f"station than recorder.ini's {own!r} left out: "
                       + ", ".join(f"{k} ({len(v)} from "
                                   f"{pd.Timestamp(min(file_start(p, 'edl') for p in v), unit='s'):%Y-%m-%d %H:%M})"
                                   for k, v in sorted(other.items())))
    return keep


def build_site(root: Path, folder: str, ini: str | None, stations: list) -> dict[str, set[str]]:
    """Write one synthetic site folder under root; return each station's channel file names."""
    site = root / folder
    names: dict[str, set[str]] = {}
    for station, sep, n, first in stations:
        for k in range(n):
            when = first + timedelta(hours=k)
            day = site / f"{when.timetuple().tm_yday:03d}"
            day.mkdir(parents=True, exist_ok=True)
            name = f"{station}{sep}{when:%y%m%d%H%M%S}.{CHANNELS[k % len(CHANNELS)]}"
            (day / name).write_bytes(b"")
            names.setdefault(station, set()).add(name)
        # the day log, not a record
        (site / f"{first.timetuple().tm_yday:03d}" / f"{station}{sep}{first:%y%m%d}000000.gps").write_bytes(b"")
    if ini is not None:
        (site / "config").mkdir(parents=True, exist_ok=True)
        (site / "config" / "recorder.ini").write_text(INI.format(ini), encoding="utf-8")
    return names


def warnings_of(call) -> tuple[object, list[str]]:
    """Return `call()`'s result and the warning lines loguru logged during it."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING", format="{message}")
    try:
        return call(), lines
    finally:
        logger.remove(sink)


def run_case(root: Path, case: str) -> tuple[str, str, list[str]]:
    """Build one case's folder and list it with `record_files`; return (expected, got, failures)."""
    folder, ini, stations, kept, want_warnings = CASES[case]
    base = root / case
    shutil.rmtree(base, ignore_errors=True)
    names = build_site(base, folder, ini, stations)
    want = set().union(*names.values()) if kept is None else names[kept]
    files, lines = warnings_of(lambda: record_files(base / folder, "edl"))
    got = {f.name for f in files}
    shown = ", ".join(f"{s} ({len(got & v)})" for s, v in sorted(names.items()) if got & v) or "nothing"
    expected = "every file" if kept is None else f"{kept} ({len(want)})"
    bad = []
    if got != want:
        bad.append(f"({case}) kept {shown}, expected {expected}")
    if len(lines) != len(want_warnings) or not all(
            all(frag in line for frag in frags) for line, frags in zip(lines, want_warnings)):
        bad.append(f"({case}) warnings {lines}, expected {len(want_warnings)} holding {want_warnings}")
    return expected, f"{shown}; {len(lines)} warning(s)", bad


def check_keys() -> list[str]:
    """Case (g): the normalisation helper on its own. Returns the failures."""
    return [f"(g) {a!r} ~ {b!r} is {_edl_station_key(a) == _edl_station_key(b)}, expected {same}"
            for a, b, same in KEY_PAIRS if (_edl_station_key(a) == _edl_station_key(b)) != same]


def main() -> None:
    import mt_io.uoa  # noqa: F401  (mt-io resets loguru's handlers when first imported: before any sink)
    import mt_io.uoa.pr624  # noqa: F401

    print(f"  mt_workbench.instruments: {instruments.__file__}")
    root = Path(tempfile.mkdtemp(dir=scratch_dir("edl_own_files_unit")))
    print(f"  {'case':<6}{'expected':<16}{'got':<42}verdict")
    failures: dict[str, list[str]] = {}
    for case in CASES:
        expected, got, bad = run_case(root, case)
        failures[case] = bad
        print(f"  ({case})   {expected:<16}{got:<42}{'FAIL' if bad else 'ok'}")
        for line in bad:
            print(f"        {line}")
    failures["g"] = check_keys()
    print(f"  (g)   {len(KEY_PAIRS)} name pairs: "
          + ", ".join(f"{a} {'~' if same else '!~'} {b}" for a, b, same in KEY_PAIRS)
          + f"  {'FAIL' if failures['g'] else 'ok'}")
    for line in failures["g"]:
        print(f"        {line}")
    assert not any(failures.values()), {k: v for k, v in failures.items() if v}

    # the mutation: the old rule fails (a) and (d), and (h), (i), (j); (b), (c), (e), (f), (k) pass under both
    kept = instruments._edl_own_files
    instruments._edl_own_files = _old_rule  # record_files looks the function up when called
    try:
        tripped = {case: run_case(root, case)[2] for case in CASES}
    finally:
        instruments._edl_own_files = kept
    failed = {case for case, bad in tripped.items() if bad}
    for case in sorted(failed):
        print(f"  mutation (old rule) tripped {tripped[case][0]}")
    assert failed == OLD_RULE_FAILS, f"the old rule failed {sorted(failed)}, expected {sorted(OLD_RULE_FAILS)}"
    print(f"  mutation (old rule): {', '.join(sorted(failed))} fail and {', '.join(sorted(set(CASES) - failed))} "
          f"pass, as required")
    shutil.rmtree(root)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    main()
    print("\nPASS  edl_own_files_unit")
