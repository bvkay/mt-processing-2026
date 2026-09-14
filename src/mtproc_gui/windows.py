"""The time windows a station's archive is offered in -- no Qt in here.

The MATLAB App Designer app listed each station's raw files under the
station in a tree, and a student clicked one file to see its time series,
Welch spectrum, spectrogram and coherence. An MTH5 archive has no files to
list, so the tree lists **windows** of a constant 7.2 million samples per
channel instead: 2 h at 1000 Hz, 4 h at 500 Hz (`window_hours`, capped to
half an hour and a day), laid from the record's grid start, the last one
shorter. A window with less than `MIN_COVERED_S` (10 minutes) of samples
inside the runs -- one that falls in a gap between runs, or a sliver at the
end -- is not offered.

`window_list` walks the grid with `bbmt_gui.archive.run_slices`, the one
copy of the run arithmetic, so a window's coverage is decided exactly as
the segment load will fill it. It needs the station's h5py group for the
datasets' lengths and opens the archive read-only itself when none is given
(`tests/windows_unit.py` gives it a fake).
"""

from __future__ import annotations

import h5py
import pandas as pd

from bbmt_gui.archive import Grid, run_slices

WINDOW_SAMPLES = 7_200_000  # per channel: 2 h at 1000 Hz, 4 h at 500 Hz
MIN_HOURS = 0.5
MAX_HOURS = 24.0
MIN_COVERED_S = 600.0  # a window with fewer seconds of samples than this is not offered


def window_hours(sample_rate: float) -> float:
    """Hours per window at `sample_rate`: `WINDOW_SAMPLES` samples, capped to [0.5, 24] h."""
    hours = WINDOW_SAMPLES / float(sample_rate) / 3600.0
    return min(MAX_HOURS, max(MIN_HOURS, hours))


def window_list(grid: Grid, station_group=None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(start, end) UTC of every window of `grid`'s record worth offering.

    Windows of `window_hours(grid.sample_rate)` from the grid start, the last
    one shorter; a window whose runs cover less than `MIN_COVERED_S` of it is
    dropped. `station_group` is the station's h5py group (its run groups hold
    the datasets whose lengths `run_slices` needs); without it the archive
    is opened read-only for the walk and closed again.
    """
    if station_group is None:
        with h5py.File(grid.path, "r") as handle:
            return window_list(grid, handle[grid.group])
    fs = grid.sample_rate
    n_win = int(round(window_hours(fs) * 3600.0 * fs))
    comp = grid.comps[0]
    out = []
    for i0 in range(0, grid.n_samples, n_win):
        n = min(n_win, grid.n_samples - i0)
        covered = sum(dst.stop - dst.start for _ds, dst, _src in run_slices(grid, station_group, comp, i0, n))
        if covered >= MIN_COVERED_S * fs:
            out.append((grid.time_at(i0 / fs / 3600.0), grid.time_at((i0 + n) / fs / 3600.0)))
    return out


def window_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """The tree's row text: '2021-06-29 06:55 UTC (2.0 h)'."""
    hours = (end - start).total_seconds() / 3600.0
    return f"{start:%Y-%m-%d %H:%M} UTC ({hours:.1f} h)"
