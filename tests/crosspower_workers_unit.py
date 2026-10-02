# -*- coding: utf-8 -*-
"""
Unit test for the worker count of the Cross-powers tab's compute

The tab's `_compute` is run with `compute_windows` patched to record its
`workers` argument. Then one hour of the Atlas bench archives C18 rr C19
(`<workspace>/qc/survey/pipeline_bench_20261002/bench_ws/mth5`, raw,
read-only) is computed with 4 and with 8 workers on the survey's band
scheme, and the two stores are compared array by array. In one hour levels
8-10 hold no window, so 24 of the 116 arrays are empty and the comparison
has data in 92 (levels 0-7 and the stitched stream); the deepest levels
rest on the 6 h identity of 2 Oct (201 arrays).

Usage:
    python tests/crosspower_workers_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the tab's compute asks `compute_windows` for fewer
than 8 workers, or the 1 h C18 rr C19 store computed with 8 workers differs
from the one computed with 4 in any array of any level or in the stitched
stream (NaN equal to NaN), the two stores' windows do not cover the hour,
or any of levels 0-7 holds no window (its arrays all empty, compared
vacuously). Without the bench archives the identity half is skipped, said
so.
"""

from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mt_workbench import crosspower  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402
from mt_workbench.gui.tabs import crosspower as tab  # noqa: E402

BENCH = Path("D:/MT_DATA/MT_Morocco_Atlas_Mountains_Workspace/qc/survey/pipeline_bench_20261002/bench_ws/mth5")
SURVEY_YAML = REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "survey.yaml"
START, END = pd.Timestamp("2023-09-23T00:00:00Z"), pd.Timestamp("2023-09-23T01:00:00Z")


def test_a_tab_asks_for_eight():
    asked = []
    real, source = tab.compute_windows, tab.processing_source
    tab.compute_windows = lambda *args, **kwargs: asked.append(kwargs.get("workers")) or types.SimpleNamespace()
    tab.processing_source = lambda survey, site, raw: (raw, "")
    try:
        tab._compute(None, "L", Path("l.h5"), "R", Path("r.h5"), START, END, {})
    finally:
        tab.compute_windows, tab.processing_source = real, source
    assert asked == [8], f"the tab's compute asked for {asked} workers"
    print(f"  the tab's compute asks compute_windows for {asked[0]} workers")


def test_b_eight_workers_same_store():
    local, remote = BENCH / "C18.h5", BENCH / "C19.h5"
    if not (local.exists() and remote.exists()):
        print(f"  SKIP: {local} or {remote} is not on this machine")
        return
    processing = yaml.safe_load(SURVEY_YAML.read_text(encoding="utf-8"))["processing"]
    scheme = build_band_scheme(1000.0, **processing)
    stores, took = {}, {}
    for workers in (4, 8):
        t = time.perf_counter()
        stores[workers] = crosspower.compute_windows(local, "C18", remote, "C19", START, END, scheme, workers=workers)
        took[workers] = time.perf_counter() - t
    a, b = stores[4], stores[8]
    assert (a.lo_n, a.hi_n, a.n_blocks) == (b.lo_n, b.hi_n, b.n_blocks), ((a.lo_n, a.hi_n), (b.lo_n, b.hi_n))
    assert (a.hi_n - a.lo_n) == 3600 * 1000, a.hi_n - a.lo_n
    filled, empty, empty_levels = 0, 0, set()
    for a_lv, b_lv in zip(a.levels, b.levels, strict=True):
        for key, value in a_lv.items():
            if isinstance(value, np.ndarray):
                assert np.array_equal(value, b_lv[key], equal_nan=value.dtype.kind in "fc"), (a_lv["level"], key)
                if value.size:
                    filled += 1
                else:
                    empty += 1
                    empty_levels.add(int(a_lv["level"]))
    for c in a.stream:
        assert np.array_equal(a.stream[c], b.stream[c], equal_nan=True), c
        filled += 1
    assert not empty_levels & set(range(8)), f"levels {sorted(empty_levels)} hold no window"
    print(f"  C18 rr C19 {START:%Y-%m-%d %H:%M}-{END:%H:%M} UTC: {filled} arrays with data identical, "
          f"{empty} empty arrays equal (levels {sorted(empty_levels)} hold no window in 1 h; "
          f"{len(a.levels)} levels, {a.n_blocks} blocks); 4 workers {took[4]:.1f} s, 8 workers {took[8]:.1f} s")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  crosspower_workers_unit ({len(tests)} tests)")
