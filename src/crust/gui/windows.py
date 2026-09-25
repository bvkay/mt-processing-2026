# -*- coding: utf-8 -*-
"""
Time windows of a station's archive

The Time Series tab lists each station in a tree, and clicking an entry
under it shows its time series, Welch spectrum, spectrogram and
coherence. An MTH5 archive has no files to list, so the tree lists windows
of a constant 7.2 million samples per channel: 2 h at 1000 Hz, 4 h at 500 Hz.
`window_hours` caps the length to between half an hour and a day, so a 10 Hz
EDL site (where 7.2 M samples would be 200 h) and a 1 Hz LEMI-424 get 24 h
windows of 864,000 and 86,400 samples. Windows are laid from the record's
grid start and the last one is shorter. A window with less than
`MIN_COVERED_S` (10 minutes) of samples inside the runs, such as one in a gap
between runs or a sliver at the end, is left out.

`window_list` walks the grid with `crust.gui.archive.run_slices`, the same
run arithmetic the segment load uses, so a window's coverage matches what the
load will fill. It needs the station's h5py group for the dataset lengths and
opens the archive read-only when none is given (`tests/windows_unit.py`
passes a fake). The module has no Qt dependency.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import h5py
import pandas as pd

from crust.gui.archive import Grid, run_slices

WINDOW_SAMPLES = 7_200_000  # per channel: 2 h at 1000 Hz, 4 h at 500 Hz
MIN_HOURS = 0.5
MAX_HOURS = 24.0
MIN_COVERED_S = 600.0  # a window with fewer seconds of samples than this is left out


def window_hours(sample_rate: float) -> float:
    """Return the window length in hours: `WINDOW_SAMPLES` samples, capped to [0.5, 24] h."""
    hours = WINDOW_SAMPLES / float(sample_rate) / 3600.0
    return min(MAX_HOURS, max(MIN_HOURS, hours))


def window_list(grid: Grid, station_group=None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """List the windows of a station's record.

    Windows are `window_hours(grid.sample_rate)` long from the grid start, the
    last one shorter. A window whose runs cover less than `MIN_COVERED_S` of
    it is dropped.

    Args:
        grid (Grid): The station's grid.
        station_group: The station's h5py group, whose run groups hold the
            datasets `run_slices` measures. When None, the archive is opened
            read-only for the walk and closed again.

    Returns:
        list[tuple[pd.Timestamp, pd.Timestamp]]: (start, end) UTC per window.
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
    """Return the tree's row text, e.g. '2021-06-29 06:55 UTC (2.0 h)'."""
    hours = (end - start).total_seconds() / 3600.0
    return f"{start:%Y-%m-%d %H:%M} UTC ({hours:.1f} h)"
