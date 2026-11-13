# -*- coding: utf-8 -*-
"""
Unit test for the float32-aware tolerance of scripts/site_qc.py's check (a), "calibration and run placement"

`mt_workbench.timefreq.load_station` keeps each channel as float32 less one offset, the median of the first
run, so a record whose later runs lie far from that offset is stored to about |x - offset| x 2^-24, coarser than
the check's old fixed 1e-5 sigma (Tasmania AusLAMP 2016, TAS138 and TAS151 after the rot_h rebuild: 2.6e-5 and
1.7e-5 sigma against float32 bounds of 2.9e-5 and 2.6e-5; there the first run is a few seconds at the set-up,
so it moves the offset and not the standard deviation). `site_qc.calibration_tolerances` makes each channel's
tolerance max(1e-5, 3 x its bound). An EDL site of two runs (120 s, then 600 s after a gap) at a DC of 3e6 counts
with white noise of 2,000 counts is written, ingested and loaded as site_qc loads it; the same record is then
stored again in float32 against an offset 5,000 sigma away, the condition of TAS138, since a synthetic first run
short enough to move the offset and not the deviation would need days of files.

Usage:
    python tests/site_qc_calibration_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - Q1: the archive as loaded, or the record stored against the far offset, does not pass check (a) with
    `calibration_tolerances`, or a channel's tolerance is below 1e-5 sigma or is not max(1e-5, 3 x max
    |x - offset| x 2^-24 / sigma); (the far-offset record failing the old fixed 1e-5 is printed, as the
    reason for the change, and not asserted);
  - Q2: the record with its second run moved by one sample (the samples of that run's span rolled by one,
    as a loader that misplaced it would hold them) still passes, as loaded or under the far offset's widened
    tolerance;
  - Q3: a channel whose float32 bound is under 1e-5 / 3 does not get 1e-5 exactly.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.timefreq import load_station, spot_check_calibration  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

spec = importlib.util.spec_from_file_location("site_qc", REPO / "scripts" / "site_qc.py")
site_qc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_qc)

SCRATCH = scratch_dir("site_qc_calibration_unit")
SITE = "SQC"
T0 = pd.Timestamp("2016-10-19T00:00:00", tz="UTC")


def write_site(root: Path) -> None:
    """Write the two-run EDL site: 120 s near 0, then (after a gap) 600 s at 6e6 counts."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(7)
    for offset, n, dc in ((0, 1200, 3_000_000), (300, 3000, 3_000_000), (600, 3000, 3_000_000)):
        when = T0 + pd.Timedelta(seconds=offset)
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            values = dc + np.round(rng.normal(0.0, 2000.0, n)).astype("int64")
            np.savetxt(site / f"{SITE}_{when:%y%m%d%H%M%S}.{suffix}", values, fmt="%d")


def test_tolerance() -> None:
    """Q1-Q3."""
    root = SCRATCH / "site"
    write_site(root)
    survey = Survey({"name": "t", "instrument": "edl", "sample_rate": 10, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0}, "sites": {SITE: {}}}, root)
    path = ingest_site(survey, SITE, overwrite=True)
    record = load_station(path, "t", SITE, comps=("hx", "hy", "hz", "ex", "ey"))
    worst = spot_check_calibration(path, "t", SITE, record)
    tol = site_qc.calibration_tolerances(record, worst)
    for key, value in tol.items():
        a = record.arrays[key]
        bound = float(np.nanmax(np.abs(a))) * 2.0 ** -24 / float(np.nanstd(a))
        assert value >= 1e-5 and abs(value - max(1e-5, 3 * bound)) <= 1e-12 * value, (key, value, bound)
    assert all(worst[k] <= tol[k] for k in worst), (worst, tol)
    print("  Q1 as loaded: " + ", ".join(f"{k} {worst[k]:.1e} <= tol {tol[k]:.1e}" for k in worst))
    # the same values stored in float32 against an offset 5,000 sigma away (TAS138's condition)
    far_arrays, far_offsets = {}, {}
    for k, a in record.arrays.items():
        value = a.astype("float64") + record.offsets[k]
        off = record.offsets[k] - 5000.0 * float(np.nanstd(a))
        far_arrays[k], far_offsets[k] = (value - off).astype("float32"), off
    far = type(record)(**{**record.__dict__, "arrays": far_arrays, "offsets": far_offsets})
    worst_far = spot_check_calibration(path, "t", SITE, far)
    tol_far = site_qc.calibration_tolerances(far, worst_far)
    assert all(worst_far[k] <= tol_far[k] for k in worst_far), (worst_far, tol_far)
    print("  Q1 the offset 5,000 sigma away: " + ", ".join(f"{k} {worst_far[k]:.1e} <= tol {tol_far[k]:.1e}"
                                                         for k in worst_far)
          + f"; the old fixed 1e-5 {'fails' if max(worst_far.values()) > 1e-5 else 'passes'}")

    # Q2: the second run (from 300 s) moved by one sample in the record
    i0 = int(round((T0 + pd.Timedelta(seconds=300) - record.t0).total_seconds() * record.sample_rate))
    moved = {k: v.copy() for k, v in record.arrays.items()}
    for k in moved:
        moved[k][i0:] = np.roll(moved[k][i0:], 1)
    shifted = type(record)(**{**record.__dict__, "arrays": moved})
    worst2 = spot_check_calibration(path, "t", SITE, shifted)
    tol2 = site_qc.calibration_tolerances(shifted, worst2)
    caught = [k for k in worst2 if worst2[k] > tol2[k]]
    assert caught, (worst2, tol2)
    print(f"  Q2 the second run one sample off: caught on {caught} (e.g. {caught[0]} {worst2[caught[0]]:.2f} sigma "
          f"against tol {tol2[caught[0]]:.1e})")
    # and under the widened tolerance of the far-offset record
    moved_far = {k: v.copy() for k, v in far.arrays.items()}
    for k in moved_far:
        moved_far[k][i0:] = np.roll(moved_far[k][i0:], 1)
    far_shifted = type(record)(**{**far.__dict__, "arrays": moved_far})
    worst3 = spot_check_calibration(path, "t", SITE, far_shifted)
    tol3 = site_qc.calibration_tolerances(far_shifted, worst3)
    caught3 = [k for k in worst3 if worst3[k] > tol3[k]]
    assert caught3, (worst3, tol3)
    print(f"  Q2 the same under the far offset's widened tolerance: caught on {caught3} (e.g. {caught3[0]} "
          f"{worst3[caught3[0]]:.2f} sigma against tol {tol3[caught3[0]]:.1e})")

    # Q3: a quiet channel near its offset gets the floor 1e-5
    quiet = type(record)(**{**record.__dict__, "arrays": {"hx": np.random.default_rng(1).normal(0, 1, 1000)
                                                                    .astype("float32")}})
    q = site_qc.calibration_tolerances(quiet, ["hx"])["hx"]
    assert q == 1e-5, q
    print(f"  Q3 a channel within a few sigma of its offset: tolerance {q:g}")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1])
    test_tolerance()
    print("  ok  test_tolerance")
    print("\nPASS  site_qc_calibration_unit (1 test)")
