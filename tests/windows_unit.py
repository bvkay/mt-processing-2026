"""Unit test for `mtproc_gui.windows` -- the tree's window list, no Qt, no archive.

    python tests/windows_unit.py

**This test fails if** a record of 41.268 h at 1000 Hz (D02's length) in one
run does not give exactly 21 windows -- twenty of 2.0 h from the record
start and a last one of 1.268 h ending at the record end -- with the first
labelled '2021-06-29 06:55 UTC (2.0 h)'; 500 Hz data is not offered in 4 h
windows (a 10 h record: 4 h, 4 h, 2 h); `window_hours` is not 2.0 at 1000 Hz,
4.0 at 500 Hz, capped at 24 h for 10 Hz (an EDL) and 1 Hz (a LEMI-424) and
0.5 h for 1 MHz; a window that
falls entirely in a gap between two runs is offered, or one that catches
under 10 minutes of a run is, or one that catches 12 minutes is not; or a
window is placed by anything other than `run_slices` over the grid (a run
starting 2.001 s after the previous one ends must still cover its window).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtproc_gui.archive import Grid  # noqa: E402
from mtproc_gui.windows import window_hours, window_label, window_list  # noqa: E402

T0 = pd.Timestamp("2021-06-29 06:55:49+00:00")
D02_SAMPLES = 148_564_754  # 41.268 h at 1000 Hz


class _Dataset:
    """Stands in for an h5py dataset: `run_slices` only reads `.shape`."""

    def __init__(self, n: int):
        self.shape = (n,)


def fake_grid(fs: float, runs: list[tuple[float, int]]):
    """A `Grid` plus a fake station group from (start hours, n samples) per run."""
    run_list, station = [], {}
    for k, (start_h, n) in enumerate(runs):
        start = T0 + pd.Timedelta(microseconds=round(start_h * 3.6e9))
        end = start + pd.Timedelta(microseconds=round((n - 1) / fs * 1e6))
        run_list.append((f"r{k}", start, end))
        station[f"r{k}"] = {"ex": _Dataset(n)}
    last_h, last_n = runs[-1]
    n_total = int(round(last_h * 3600 * fs)) + last_n
    grid = Grid(
        path=Path("fake.h5"), station="X", survey="s", t0=T0, sample_rate=fs,
        n_samples=n_total, group="/g", runs=run_list, gains={"ex": 1.0}, scalar_only=set(),
    )
    return grid, station


def test_window_hours() -> None:
    assert window_hours(1000.0) == 2.0
    assert window_hours(500.0) == 4.0
    assert window_hours(10.0) == 24.0  # 200 h capped: a 10 Hz EDL site
    assert window_hours(1.0) == 24.0  # 2000 h capped: a 1 Hz LEMI-424 site
    assert window_hours(1e6) == 0.5  # 7.2 s raised to the floor
    print("  1000 Hz -> 2 h, 500 Hz -> 4 h, 10 Hz -> 24 h cap, 1 MHz -> 0.5 h floor")


def test_d02_length_gives_21_windows() -> None:
    grid, station = fake_grid(1000.0, [(0.0, D02_SAMPLES)])
    windows = window_list(grid, station)
    assert len(windows) == 21, f"{len(windows)} windows, expected 21"
    hours = [(e - s).total_seconds() / 3600 for s, e in windows]
    assert all(abs(h - 2.0) < 1e-9 for h in hours[:-1]), hours
    assert abs(hours[-1] - 1.268) < 1e-3, hours[-1]
    assert windows[0][0] == T0 and windows[-1][1] == grid.time_at(grid.duration_h)
    for (_s, e), (s, _e) in zip(windows, windows[1:]):
        assert e == s, "windows do not abut"
    assert window_label(*windows[0]) == "2021-06-29 06:55 UTC (2.0 h)", window_label(*windows[0])
    assert window_label(*windows[-1]) == "2021-06-30 22:55 UTC (1.3 h)", window_label(*windows[-1])
    print(f"  41.268 h at 1000 Hz: {len(windows)} windows, last {hours[-1]:.3f} h, "
          f"first {window_label(*windows[0])!r}")


def test_500hz_gives_4h_windows() -> None:
    grid, station = fake_grid(500.0, [(0.0, int(10 * 3600 * 500))])
    hours = [(e - s).total_seconds() / 3600 for s, e in window_list(grid, station)]
    assert hours == [4.0, 4.0, 2.0], hours
    print(f"  10 h at 500 Hz: {hours} h")


def test_gap_windows_dropped() -> None:
    fs = 1000.0
    # run 1: 0-2 h; run 2 from 6 h for 2 h: windows [2,4) and [4,6) lie in the gap
    grid, station = fake_grid(fs, [(0.0, 7_200_000), (6.0, 7_200_000)])
    starts = [(s - T0).total_seconds() / 3600 for s, _e in window_list(grid, station)]
    assert starts == [0.0, 6.0], starts
    # run 2 from 5.9 h: [4,6) catches 6 minutes of it -> still dropped ...
    grid, station = fake_grid(fs, [(0.0, 7_200_000), (5.9, 7_200_000)])
    starts = [(s - T0).total_seconds() / 3600 for s, _e in window_list(grid, station)]
    assert starts == [0.0, 6.0], starts
    # ... from 5.8 h: 12 minutes -> offered
    grid, station = fake_grid(fs, [(0.0, 7_200_000), (5.8, 7_200_000)])
    starts = [(s - T0).total_seconds() / 3600 for s, _e in window_list(grid, station)]
    assert starts == [0.0, 4.0, 6.0], starts
    print("  a window inside a gap is dropped; 6 min of a run is not enough, 12 min is")


def test_run_offset_not_a_whole_second() -> None:
    fs = 1000.0
    # run 2 starts 2.001 s after run 1 ends (as D02's does, to the millisecond)
    n1 = int(1.5 * 3600 * fs)
    grid, station = fake_grid(fs, [(0.0, n1), ((n1 + 2001) / fs / 3600, int(3 * 3600 * fs))])
    windows = window_list(grid, station)
    hours = [(e - s).total_seconds() / 3600 for s, e in windows]
    assert len(windows) == 3 and abs(hours[0] - 2.0) < 1e-9, hours
    print(f"  a 2.001 s inter-run offset: {len(windows)} windows, {[f'{h:.3f}' for h in hours]} h")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  windows_unit ({len(tests)} tests)")
