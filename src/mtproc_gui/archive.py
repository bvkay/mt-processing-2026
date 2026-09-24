# -*- coding: utf-8 -*-
"""
MTH5 archive geometry for display

`load_grid` opens an archive read-only, reads the station's run metadata and
closes the file before it returns. It reads no samples. The resulting `Grid`
holds the sample grid, the runs, the scalar channel gains and the station's
HDF5 group path. The Time Series tab's tree uses it to list a station's
windows (`mtproc_gui.windows`), and `mtproc_gui.segment.load_segment` uses it
to slice the datasets directly with h5py. Reading through h5py avoids
rebuilding mth5 channel metadata and filter chains on every read, which
takes most of the time of a read through `MTH5.get_station`.

All runs of a station go on one sample grid from the first run's start to the
last run's end. This is the same concatenation `mtproc.timefreq.load_station`
applies for the QC figures, so a window drawn in the GUI and figure 01 of
`scripts/site_qc.py` place each sample at the same time. Calibration matches
as well: the scalar (frequency-independent) part of the channel's MTH5 filter
chain, `mtproc.timefreq._scalar_gain`. This leaves the electrics fully
calibrated in mV/km and the magnetics in nT without the coil's frequency
response; such channels are listed in `Grid.scalar_only` so plots can label
them. An EDL chain is all coefficients (fully calibrated); a LEMI-424 has no
filters (gain 1, the reader's units).

Channels keep the archive's own names (`mtproc_gui.channels`). `load_grid`
takes every electric and magnetic channel by default, in stack order, or the
requested names that exist.

`run_slices` maps each run's samples onto the grid.
`mtproc_gui.windows.window_list` walks it to find a station's windows and
`load_segment` fills a window through it.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from mth5.mth5 import MTH5

from mtproc.timefreq import _real_runs, _scalar_gain
from mtproc_gui import channels


@dataclass
class Grid:
    """A station's sample grid, runs and scalar gains.

    The grid starts at the first run's start `t0` and holds `n_samples` at
    `sample_rate`; sample i sits at `t0 + i / sample_rate`.

    Attributes:
        path (Path): The MTH5 file.
        station (str): Station name.
        survey (str): Survey name inside the MTH5.
        t0 (pd.Timestamp): Start of the grid, UTC.
        sample_rate (float): Sample rate in Hz.
        n_samples (int): Grid length in samples.
        group (str): The station's HDF5 group path, e.g.
            /Experiment/Surveys/X/Stations/S01, used to slice the datasets
            with h5py.
        runs (list[tuple[str, pd.Timestamp, pd.Timestamp]]): Run groups
            holding data as (id, start, end), earliest first.
        gains (dict[str, float]): Scalar gain per channel.
        scalar_only (set[str]): Channels whose filter chain has a
            frequency-dependent part that the scalar gain leaves out.
    """

    path: Path
    station: str
    survey: str
    t0: pd.Timestamp
    sample_rate: float
    n_samples: int
    group: str
    runs: list[tuple[str, pd.Timestamp, pd.Timestamp]]
    gains: dict[str, float]
    scalar_only: set[str]

    @property
    def comps(self) -> list[str]:
        """Channel names in stack order."""
        return list(self.gains)

    @property
    def duration_h(self) -> float:
        """Grid length in hours."""
        return self.n_samples / self.sample_rate / 3600.0

    def unit(self, comp: str) -> str:
        """Unit label of a channel, with ", scalar gain" for a `scalar_only` channel."""
        tag = ", scalar gain" if comp in self.scalar_only else ""
        return channels.unit(comp) + tag

    def time_at(self, hours: float) -> pd.Timestamp:
        """Return the UTC timestamp `hours` into the record, to the nearest microsecond."""
        # whole microseconds: Timedelta(seconds=<float>) truncates to the
        # nanosecond, and 50 min comes out 1 ns short, so 07:45:48 not 07:45:49
        return self.t0 + pd.Timedelta(microseconds=round(float(hours) * 3.6e9))

    def index_of(self, when) -> int:
        """Return the grid index nearest to a UTC timestamp; a naive timestamp is taken as UTC."""
        when = pd.Timestamp(when)
        if when.tzinfo is None:
            when = when.tz_localize("UTC")
        return int(round((when - self.t0).total_seconds() * self.sample_rate))


def _open(mth5_path: Path) -> MTH5:
    """Open an MTH5 file read-only."""
    handle = MTH5()
    handle.open_mth5(Path(mth5_path), mode="r")
    return handle


def _grid(handle: MTH5, station: str, survey: str, comps):
    """Read the grid geometry of a station from an open MTH5.

    Returns:
        tuple: (runs, channels to draw, sample rate, t0, number of samples,
        HDF5 group path).

    Raises:
        ValueError: If the station has no runs with data, or none of the
            requested channels are in the archive.
    """
    station_group = handle.get_station(station, survey=survey)
    runs = _real_runs(station_group)
    if not runs:
        raise ValueError(f"{station}: no runs with data")
    available = station_group.get_run(runs[0][0]).groups_list
    comps = channels.display(available, comps)
    if not comps:
        raise ValueError(f"{station}: none of the requested channels are in the archive")
    sample_rate = float(
        handle.get_channel(station, runs[0][0], comps[0], survey).metadata.sample_rate
    )
    t0 = runs[0][1]
    last_id, last_start, _ = runs[-1]
    n_last = handle.get_channel(station, last_id, comps[0], survey).hdf5_dataset.shape[0]
    n = int(round((last_start - t0).total_seconds() * sample_rate)) + n_last
    return runs, comps, sample_rate, t0, n, station_group.hdf5_group.name


def load_grid(mth5_path: str | Path, survey_name: str, station: str, comps=None) -> Grid:
    """Build the station's `Grid` from its run metadata.

    Opens the MTH5 once, read-only, and reads no samples. The scalar gain of
    each channel comes from the first run's filter chain
    (`mtproc.timefreq._scalar_gain`).

    Args:
        mth5_path (str | Path): The MTH5 file.
        survey_name (str): Survey name inside the MTH5.
        station (str): Station name.
        comps (list[str] | None): Channels to take. None takes every electric
            and magnetic channel of the first run in `channels.order`;
            otherwise the listed channels the run holds are taken, or all of
            them when it holds none (`channels.display`).

    Returns:
        Grid: The station's grid.

    Raises:
        ValueError: If the station has no runs with data.
    """
    handle = _open(mth5_path)
    try:
        runs, comps, sample_rate, t0, n, group = _grid(handle, station, survey_name, comps)
        gains, scalar_only = {}, set()
        for comp in comps:
            gain, skipped = _scalar_gain(handle.get_channel(station, runs[0][0], comp, survey_name))
            gains[comp] = gain
            if skipped:
                scalar_only.add(comp)
    finally:
        handle.close_mth5()
    return Grid(
        path=Path(mth5_path), station=station, survey=survey_name, t0=t0,
        sample_rate=sample_rate, n_samples=n, group=group, runs=runs, gains=gains,
        scalar_only=scalar_only,
    )


def run_slices(grid: Grid, station_group, comp: str, i_win: int, n_win: int):
    """Yield the part of each run that overlaps a window of the grid.

    A run starts at grid sample `round((start - t0) * fs)`; its overlap with
    the window is clipped to both.

    Args:
        grid (Grid): The station's grid.
        station_group: The station's open h5py group.
        comp (str): Channel name.
        i_win (int): First grid sample of the window.
        n_win (int): Window length in samples.

    Yields:
        tuple: (h5py dataset, slice into the window, slice into the run) for
        each run that overlaps the window.
    """
    fs = grid.sample_rate
    for run_id, run_start, _ in grid.runs:
        dataset = station_group[run_id][comp]
        i0 = int(round((run_start - grid.t0).total_seconds() * fs))
        a = max(i_win, i0)
        b = min(i_win + n_win, i0 + dataset.shape[0])
        if b > a:
            yield dataset, slice(a - i_win, b - i_win), slice(a - i0, b - i0)
