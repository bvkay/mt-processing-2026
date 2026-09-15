"""Read an MTH5 archive for *display only* -- no processing lives here.

One read, read-only, closing the file before it returns:

- `load_grid`   the station's `Grid`: its sample grid, its runs, its channel
                gains and the HDF5 group path, from the run metadata alone
                (one MTH5 open, no samples read). This is what the Time
                Series tab's tree needs to list a station's windows
                (`mtproc_gui.windows`), and what `mtproc_gui.segment.load_segment`
                slices the datasets with, through h5py alone: rebuilding
                mth5's channel metadata on every read (`get_channel`, the
                filter chain) took 0.8 s of a 0.9 s read, and even
                `MTH5.get_station` built mt_metadata objects that were never
                freed (350 kB and 20 ms a read -- half a gigabyte over a long
                QC session).

Every run of the station goes on one sample grid running from the first
run's start to the last run's end -- the same concatenation
`mtproc.timefreq.load_station` does for the QC figures, so a window the GUI
draws and `scripts/site_qc.py`'s figure 01 place a sample at the same time.
Calibration is the same too: the scalar (frequency-independent) part of the
channel's MTH5 filter chain, `mtproc.timefreq._scalar_gain`, which leaves the
electrics fully calibrated in mV/km and the magnetics in nT without the
coil's shape response (a time series does not need it; the channel is flagged
in `scalar_only` so the plot can say so). An EDL chain is all coefficients
(fully calibrated); a LEMI-424 has none (gain 1, the reader's units).

Channels are the archive's own names, whatever the reader called them
(`mtproc_gui.channels`): `load_grid` takes every electric and magnetic
channel by default, in the stack order, or the names asked for that exist.

The run arithmetic -- which sample of which run lands where on the grid --
lives in one place, `run_slices` over a `Grid`. `mtproc_gui.windows.window_list`
walks it to decide which windows a station has; `load_segment` fills a
window through it.
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
    """A station's sample grid, runs and scalar gains -- what every read needs.

    The grid runs from the first run's start `t0` for `n_samples` at
    `sample_rate`; sample i sits at `t0 + i / sample_rate`. `runs` are the
    run groups holding data (id, start, end), earliest first, and `group` is
    the station's HDF5 group path (e.g. /Experiment/Surveys/X/Stations/D02),
    so a read can slice the datasets with h5py alone.
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
        return list(self.gains)

    @property
    def duration_h(self) -> float:
        return self.n_samples / self.sample_rate / 3600.0

    def unit(self, comp: str) -> str:
        tag = ", scalar gain" if comp in self.scalar_only else ""
        return channels.unit(comp) + tag

    def time_at(self, hours: float) -> pd.Timestamp:
        """The UTC timestamp `hours` into the record, to the nearest microsecond."""
        # whole microseconds: Timedelta(seconds=<float>) truncates to the
        # nanosecond, and 50 min comes out 1 ns short, so 07:45:48 not 07:45:49
        return self.t0 + pd.Timedelta(microseconds=round(float(hours) * 3.6e9))

    def index_of(self, when) -> int:
        """The grid index nearest to a UTC timestamp (naive is taken as UTC)."""
        when = pd.Timestamp(when)
        if when.tzinfo is None:
            when = when.tz_localize("UTC")
        return int(round((when - self.t0).total_seconds() * self.sample_rate))


def _open(mth5_path: Path) -> MTH5:
    handle = MTH5()
    handle.open_mth5(Path(mth5_path), mode="r")
    return handle


def _grid(handle: MTH5, station: str, survey: str, comps):
    """(runs, available comps, sample rate, t0, n samples, HDF5 group path)."""
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
    """The station's `Grid` from its run metadata: one MTH5 open, no samples read.

    `comps` None: every electric and magnetic channel of the first run, in
    `channels.order`; otherwise those of `comps` the run holds, in that
    order -- and all of them again when it holds none (`channels.display`).

    The scalar gain of each channel comes from the first run's filter chain
    (`mtproc.timefreq._scalar_gain`).
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
    """(dataset, slice into the window, slice into the run) per run overlapping the window.

    The window is grid samples [i_win, i_win + n_win); `station_group` is the
    station's open h5py group. Every read of a stretch goes through here so
    the placement of a run on the grid -- sample `round((start - t0) * fs)`
    onwards, clipped to the window -- is written once.
    """
    fs = grid.sample_rate
    for run_id, run_start, _ in grid.runs:
        dataset = station_group[run_id][comp]
        i0 = int(round((run_start - grid.t0).total_seconds() * fs))
        a = max(i_win, i0)
        b = min(i_win + n_win, i0 + dataset.shape[0])
        if b > a:
            yield dataset, slice(a - i_win, b - i_win), slice(a - i0, b - i0)
