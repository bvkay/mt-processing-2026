# -*- coding: utf-8 -*-
"""
Unit test for the window bars' span reads (mt_workbench.gui.window_bar, archive.read_span)

Reads the span of real archives, read-only: the Atlas bench archives C18
and C19 (`<workspace>/qc/survey/pipeline_bench_20261002/bench_ws/mth5`,
two runs each) and curnamona_cube's D02 and D02L (1 Hz, 6 MB) when they
are present, while
every MTH5 open and every h5py file open is counted. No Qt.

Usage:
    python tests/span_cache_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `site_span` of an archive differs from the span of
`load_grid`'s grid (``t0`` to ``t0 + n_samples / sample_rate``) by any
amount, or opens the archive through MTH5 (building mth5 and mt_metadata
objects) rather than once with h5py alone; `SpanCache.read` opens a file on
a second call for an unchanged archive, or `SpanCache.get` opens one at
all; a changed archive (a new modification time) is not read again;
`read_span` asked for a station under a survey name the archive does not
hold returns a span rather than raising KeyError, or `load_grid` does not
raise on the same call (the bar and the Time Series tree must agree); or no
archive is found to test (a skip, said so, exit 0).
"""

from __future__ import annotations

import os
import shutil
import sys
import types
from pathlib import Path

import h5py
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mth5.mth5 import MTH5  # noqa: E402

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.gui.archive import load_grid  # noqa: E402
from mt_workbench.gui.window_bar import site_span  # noqa: E402

BENCH = Path("D:/MT_DATA/MT_Morocco_Atlas_Mountains_Workspace/qc/survey/pipeline_bench_20261002/bench_ws/mth5")
ARCHIVES = [(BENCH / "C18.h5", "MT_Morocco_Atlas_Mountains", "C18"),
            (BENCH / "C19.h5", "MT_Morocco_Atlas_Mountains", "C19"),
            (REPO / "surveys" / "curnamona_cube" / "work" / "mth5" / "D02.h5", None, "D02"),
            (REPO / "surveys" / "curnamona_cube" / "work" / "mth5" / "D02L.h5", None, "D02L")]
OPENS: list[str] = []
MTH5_OPENS: list[str] = []
_h5_init = h5py.File.__init__
_open_mth5 = MTH5.open_mth5


def _counting_init(self, name, *args, **kwargs):
    if isinstance(name, (str, os.PathLike)):  # h5py also builds File objects from open ids
        OPENS.append(str(name))
    _h5_init(self, name, *args, **kwargs)


def _counting_open(self, filename, *args, **kwargs):
    MTH5_OPENS.append(str(filename))
    return _open_mth5(self, filename, *args, **kwargs)


h5py.File.__init__ = _counting_init
MTH5.open_mth5 = _counting_open


def present() -> list[tuple[Path, str, str]]:
    """Return the archives on this machine, the survey name read from the file where none is given."""
    out = []
    for path, survey, site in ARCHIVES:
        if path.exists():
            if survey is None:
                with h5py.File(path, "r") as f:
                    survey = next(s for s in f["Experiment/Surveys"] if site in f["Experiment/Surveys"][s]["Stations"])
            out.append((path, survey, site))
    return out


def test_a_span_equals_load_grid():
    for path, survey, site in present():
        OPENS.clear()
        MTH5_OPENS.clear()
        span = site_span(types.SimpleNamespace(name=survey), site, path, None)
        opens, mth5_opens = list(OPENS), list(MTH5_OPENS)
        grid = load_grid(path, survey, site)
        truth = (grid.t0, grid.t0 + pd.Timedelta(seconds=grid.n_samples / grid.sample_rate))
        assert span == truth, (site, span, truth)
        assert not mth5_opens and len(opens) == 1, (site, mth5_opens, opens)
        print(f"  {site}: {span[0]} to {span[1]} ({len(grid.runs)} runs), equal to load_grid's; "
              f"h5py opens {len(opens)}, MTH5 opens {len(mth5_opens)}")


def test_b_second_read_opens_nothing():
    from mt_workbench.gui.window_bar import SpanCache

    for path, survey, site in present():
        cache, survey_ns = SpanCache(), types.SimpleNamespace(name=survey)
        assert cache.get(survey_ns, site, path) is None
        first = cache.read(survey_ns, site, path, None)
        OPENS.clear()
        MTH5_OPENS.clear()
        assert cache.read(survey_ns, site, path, None) == first
        assert cache.get(survey_ns, site, path) == first
        assert OPENS == [] and MTH5_OPENS == [], (site, OPENS, MTH5_OPENS)
        print(f"  {site}: a second read and a get open no file")


def test_c_changed_archive_read_again():
    from mt_workbench.gui.window_bar import SpanCache

    found = present()
    path, survey, site = next(((p, s, n) for p, s, n in found if p.stat().st_size < 1e8), (None, None, None))
    if path is None:
        print("  no archive under 100 MB to copy: the changed-archive check is skipped")
        return
    copy = scratch_dir("span_cache_unit") / path.name
    shutil.copyfile(path, copy)
    cache, survey_ns = SpanCache(), types.SimpleNamespace(name=survey)
    cache.read(survey_ns, site, copy, None)
    status = copy.stat()
    os.utime(copy, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000_000))
    assert cache.get(survey_ns, site, copy) is None
    OPENS.clear()
    cache.read(survey_ns, site, copy, None)
    assert len(OPENS) == 1, OPENS
    print(f"  {site} (a copy): mtime +1 s, the kept span dropped and the archive read again")


def test_d_survey_name_mismatch():
    from mt_workbench.gui.archive import read_span

    path, survey, site = present()[0]
    wrong = f"{survey}_not_this"
    outcome = {}
    for name, call in (("read_span", read_span), ("load_grid", load_grid)):
        try:
            outcome[name] = ("returned", call(path, wrong, site))
        except Exception as exc:  # noqa: BLE001 - which error each raises is the point
            outcome[name] = ("raised", f"{type(exc).__name__}: {exc}")
    assert outcome["read_span"][0] == "raised" and outcome["read_span"][1].startswith("KeyError"), outcome
    assert outcome["load_grid"][0] == "raised", outcome
    print(f"  {site} under survey {wrong!r}: read_span {outcome['read_span'][1]}; "
          f"load_grid {outcome['load_grid'][1]}")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    if not present():
        print("SKIP  span_cache_unit: none of the archives is on this machine")
        sys.exit(0)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  span_cache_unit ({len(tests)} tests)")
