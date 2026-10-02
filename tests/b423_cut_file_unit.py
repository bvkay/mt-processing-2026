# -*- coding: utf-8 -*-
"""
Unit test for a B423 file cut mid-record inside a run (mt_workbench.ingest)

Four synthetic B423 files of 4 s at 1000 Hz, named 4 s apart (back to back),
are written into a scratch site folder; the second is then cut to 2000
whole records and 17 bytes, as `corrupt_b423.py truncate` cut a copy of a
real file in the robustness pass of 3 Oct 2026 (case 5c). Each file's Ex is
a constant of its own (1e6, 2e6, 3e6, 4e6 counts), so every file's stretch
can be found in the archive by its value. `ingest_site` writes the archive
and h5py reads it back: each stretch's time stamp (its run's start plus its
index over the sample rate) is compared with the start the file's name
gives. A control folder of the same four files uncut must give one run with
every stamp right.

Usage:
    python tests/b423_cut_file_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** any file's first sample in the archive is stamped
more than 2 ms from the start its file name gives (the old grouping joined
the cut file to the files after it in one run and stamped files 3 and 4
2 s early); if the cut set is not ingested as two runs, files 1-2 and
files 3-4; if no WARNING names the cut file with its 2000 samples missing;
or if the uncut control is not one run of 16000 samples with every stamp
right and no such warning.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import h5py  # noqa: E402
import numpy as np  # noqa: E402
from loguru import logger  # noqa: E402

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRATCH = scratch_dir("b423_cut_file_unit")
EPOCH = 1695390686  # C18's second file name, as in the robustness copies
RATE = 1000
N = 4000  # records per file: 4 s at 1000 Hz
LEVELS = (1.0e6, 2.0e6, 3.0e6, 4.0e6)  # each file's Ex, counts


def build(name: str, cut: bool) -> Survey:
    """Write four back-to-back B423 files under <scratch>/<name>, the second cut when `cut`."""
    root = SCRATCH / name
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "S01"
    for k, level in enumerate(LEVELS):
        epoch = EPOCH + k * N // RATE
        _write_b423(site / f"{epoch}.B423", epoch=epoch, n=N, rate=RATE, levels={"Ex": (level, 0.0)})
    if cut:
        # 2000 whole records and 17 bytes of the next, as corrupt_b423.py truncate cut case 5c's copy
        os.truncate(site / f"{EPOCH + N // RATE}.B423", 1024 + 30 * 2000 + 17)
    return Survey({"name": "t", "instrument": "lemi423", "sample_rate": RATE, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"channels": ["ex", "ey", "hx", "hy"], "dipole_length_ex": 50.0,
                                "dipole_length_ey": 50.0},
                   "sites": {"S01": {}}}, root)


def _epoch(text: str) -> float:
    """Seconds since 1970 of an ISO time stamp, UTC when it carries no offset."""
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def stamps(path: Path) -> tuple[dict, dict]:
    """Read each run's samples and, per file level, the time stamp of its first sample (h5py only)."""
    found, runs = {}, {}
    with h5py.File(path, "r") as f:
        station = f["Experiment/Surveys/t/Stations/S01"]
        for rid in sorted(r for r in station if r.startswith("sr")):
            ds = station[rid]["ex"]
            ex = ds[()].astype("float64")
            start = _epoch(ds.attrs["time_period.start"])
            runs[rid] = ex.size
            for k, level in enumerate(LEVELS):
                at = np.flatnonzero(ex == level)
                if at.size:
                    found[k] = (rid, int(at[0]), start + at[0] / RATE)
    return found, runs


def check(name: str, cut: bool) -> tuple[list[str], dict, dict]:
    """Ingest one folder and check its stamps; return the warnings logged, the runs and the stamps."""
    survey = build(name, cut)
    warnings: list[str] = []
    sink = logger.add(lambda m: warnings.append(str(m)), level="WARNING", format="{message}")
    try:
        path = ingest_site(survey, "S01", overwrite=True)
    finally:
        logger.remove(sink)
    found, runs = stamps(path)
    assert sorted(found) == [0, 1, 2, 3], (name, found)
    for k, (rid, index, stamp) in sorted(found.items()):
        truth = EPOCH + k * N // RATE
        shift = stamp - truth
        print(f"  {name}: file {k + 1} ({truth}.B423) first sample in {rid} index {index}, "
              f"stamped {stamp:.3f}, shift {shift:+.3f} s")
        assert abs(shift) <= 0.002, f"{name}: file {k + 1} stamped {shift:+.3f} s from its file name"
    return warnings, runs, found


def test_cut_file_ends_its_run() -> None:
    """Check a file cut mid-record ends its run, with a warning, and every later stamp is right."""
    warnings, runs, found = check("cut", cut=True)
    assert len(runs) == 2, f"the cut set was ingested as {len(runs)} run(s) {runs}, not 2"
    assert [found[k][0] for k in range(4)] == ["sr1000_0001", "sr1000_0001", "sr1000_0002", "sr1000_0002"], found
    assert list(runs.values()) == [N + 2000, 2 * N], runs
    cut_name = f"{EPOCH + N // RATE}.B423"
    named = [w for w in warnings if cut_name in w and "2000 samples missing" in w]
    assert named, f"no warning names {cut_name} with its 2000 samples missing: {warnings}"
    print(f"  cut: runs {runs}; warning: {named[0].strip()}")


def test_uncut_control_is_one_run() -> None:
    """Check the same four files uncut make one run with every stamp right and no warning."""
    warnings, runs, _ = check("uncut", cut=False)
    assert list(runs.values()) == [4 * N], f"the uncut control gave runs {runs}, not one of {4 * N} samples"
    assert not [w for w in warnings if "records" in w], warnings
    print(f"  uncut: runs {runs}, no record-count warning")


if __name__ == "__main__":
    SCRATCH.mkdir(parents=True, exist_ok=True)
    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="WARNING", filter=lambda r: r["function"] != "_record_levels")  # the constant levels read as saturated
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  b423_cut_file_unit ({len(tests) - failed} of {len(tests)} tests passed)")
    sys.exit(1 if failed else 0)
