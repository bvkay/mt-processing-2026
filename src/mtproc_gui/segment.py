# -*- coding: utf-8 -*-
"""
Segment QC engine

Loads a 1-3 h stretch of a station and computes its QC: Welch spectra, a
spectrogram and band coherence, on a window chosen on the Time Series tab and
optionally merged with a remote. The results are displayed on the QC tabs
and held in memory only. `compute_segment_qc` takes every number from
`mtproc.timefreq` (`levels_plan`, `cascade`, `band_from_levels`,
`levels_to_grid`, `psd_ladder`, `power_db`), the functions
`scripts/site_qc.py` and `scripts/psd_qc.py` call on a whole record, so a
segment's coherogram is a slice of figure 03 computed the same way.

* `Segment`: one stretch in `mtproc.timefreq.Record`'s convention, float32
  with the DC offset removed (a 1000 Hz LEMI count sits near 1e9, where a
  float32 ulp is tens of counts), zero in the gaps, and the gaps listed.
  `to_record()` returns a `Record`, so `mtproc.timefreq.merge` folds a remote
  in unchanged.
* `load_segment`: reads a segment read-only through the run grid of
  `mtproc_gui.archive` (`load_grid`, `run_slices`), one channel at a time.
  Each channel's counts are converted to offset-removed float32 before the
  next is read, so a 3 h segment (10.8 M samples per channel, 43 MB as
  float32) peaks at the four channels plus one channel's raw counts and a
  float64 chunk, under 400 MB. The 1-3 h limits are set by the GUI.
* `SegmentQC`: the output of one `compute_segment_qc` call.

Channels keep the archive's own names (bx .. e4 on a LEMI-424). The pairs are
`mtproc.timefreq.LOCAL_PAIRS` and `REMOTE_PAIRS`, with each LEMI-423 name
resolved to the channel playing that role (`mtproc_gui.channels.roles`: the
first two magnetics are Bx, By, the first two electrics Ex, Ey). A LEMI-423
or EDL segment therefore gets the standard pairs and a LEMI-424 segment
(by, e1) for Zxy. For a window too short for the default segment lengths,
such as one hour at 1 Hz, the lengths are halved until the ladder fits
(`_plan`, `_psd_nperseg`); a 1000 Hz window keeps the defaults.

The module has no Qt dependency. `mtproc_gui.segment_store` runs it off the
GUI thread and `tests/segment_unit.py` runs it on a synthetic hour.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger

from mtproc.timefreq import (
    BANDS_S,
    LOCAL_PAIRS,
    NPERSEG,
    PSD_MIN_SEGMENTS,
    PSD_NPERSEG,
    REMOTE_PAIRS,
    Record,
    _complement,
    band_from_levels,
    cascade,
    levels_plan,
    levels_to_grid,
    merge,
    power_db,
    psd_ladder,
)
from mtproc_gui.archive import load_grid, run_slices
from mtproc_gui.channels import REMOTE_COMPS, order, resolve_pairs, roles  # noqa: F401  (REMOTE_COMPS: the store's)

MIN_NPERSEG = 64  # the shortest segment `_plan` and `_psd_nperseg` go down to
# base window and step for a 1-3 h segment, seconds: see `compute_segment_qc`
WIN_S = 120.0
STEP_S = 30.0
CHUNK = 1 << 22  # samples per counts -> float32 conversion (32 MB as float64)


@dataclass
class Segment:
    """One stretch of a station, in `mtproc.timefreq.Record`'s convention.

    Attributes:
        station (str): Station name.
        survey (str): Survey name inside the MTH5.
        t0 (pd.Timestamp): Time of the first sample, UTC.
        sample_rate (float): Sample rate in Hz.
        n (int): Number of samples.
        arrays (dict[str, np.ndarray]): float32 samples per channel with the
            DC offset removed. At 1000 Hz a LEMI count sits around 1e7-1e9,
            where a float32 ulp is tens of counts.
        offsets (dict[str, float]): The removed offset per channel, in the
            channel's units.
        gains (dict[str, float]): Scalar gain per channel.
        scalar_only (set[str]): Channels calibrated by the scalar gain only.
        gaps (list[tuple[int, int]]): Sample spans no run covers, as
            `Record.gaps`. Those samples are zero (the channel mean), as
            `cascade` and `psd_ladder` would set them.
    """

    station: str
    survey: str
    t0: pd.Timestamp
    sample_rate: float
    n: int
    arrays: dict[str, np.ndarray]
    offsets: dict[str, float]
    gains: dict[str, float]
    scalar_only: set[str] = field(default_factory=set)
    gaps: list[tuple[int, int]] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        """Length in seconds."""
        return self.n / self.sample_rate

    @property
    def end(self) -> pd.Timestamp:
        """End time, UTC, to the microsecond."""
        return self.t0 + pd.Timedelta(microseconds=round(self.duration_s * 1e6))

    def to_record(self, prefix: str = "") -> Record:
        """Return a `Record` over this segment's grid.

        The arrays are shared rather than copied; the dicts, the set and the
        gap list are new objects, so `merge` leaves this segment unchanged.

        Args:
            prefix (str): Prefix for the channel names, "r_" for a remote.

        Returns:
            Record: The record.
        """
        return Record(
            station=self.station,
            survey=self.survey,
            t0=self.t0,
            sample_rate=self.sample_rate,
            n=self.n,
            arrays={prefix + c: a for c, a in self.arrays.items()},
            offsets={prefix + c: v for c, v in self.offsets.items()},
            gains={prefix + c: v for c, v in self.gains.items()},
            gaps=list(self.gaps),
            scalar_only={prefix + c for c in self.scalar_only},
        )


def load_segment(
    mth5_path: str | Path,
    survey_name: str,
    station: str,
    start,
    end,
    comps=None,
) -> Segment:
    """Load a station's samples from `start` to `end`, calibrated and offset-removed.

    The segment sits on the station's own grid (`mtproc_gui.archive.load_grid`):
    the first sample is the grid sample nearest `start` and `t0` is that
    sample's time. Every run overlapping the window is filled in through
    `run_slices`. A remote loaded for the same `start` and `end` therefore has
    the same `n` and a `t0` within half a sample, which `compute_segment_qc`
    checks before `merge`. The MTH5 is opened read-only for the run metadata
    and closed, then the datasets are sliced with h5py.

    Args:
        mth5_path (str | Path): The MTH5 file.
        survey_name (str): Survey name inside the MTH5.
        station (str): Station name.
        start: Window start, UTC; a naive time is taken as UTC.
        end: Window end, UTC.
        comps (list[str] | None): Channels to read; those present are read,
            or every electric and magnetic channel when none is or when None
            (`archive.load_grid`).

    Returns:
        Segment: The loaded segment.

    Raises:
        ValueError: If the window is empty, lies outside the record, or no
            run covers it.
    """
    grid = load_grid(mth5_path, survey_name, station, comps)
    fs = grid.sample_rate
    i_win = grid.index_of(start)
    n_win = grid.index_of(end) - i_win
    if n_win <= 0:
        raise ValueError(f"{station}: window end {end} is not after its start {start}")
    if i_win < 0 or i_win + n_win > grid.n_samples:
        raise ValueError(f"{station}: {start} to {end} is outside the record")
    step = max(1, n_win // 200_000)

    arrays, offsets, gaps = {}, {}, None
    with h5py.File(grid.path, "r") as handle:
        station_group = handle[grid.group]
        for comp in grid.comps:
            raw, covered = None, []
            for dataset, dst, src in run_slices(grid, station_group, comp, i_win, n_win):
                if raw is None:
                    raw = np.zeros(n_win, dtype=dataset.dtype)
                raw[dst] = dataset[src]
                covered.append((dst.start, dst.stop))
            if raw is None:
                raise ValueError(f"{station}: no run covers {start} to {end}")
            gain = grid.gains[comp]
            thinned = np.concatenate([raw[a:b:step] for a, b in covered]).astype("float64")
            offset_counts = float(np.median(thinned))
            # counts -> offset-removed float32 in chunks, so a whole channel
            # is not held as float64 alongside its counts
            out = np.empty(n_win, dtype="float32")
            for c0 in range(0, n_win, CHUNK):
                c1 = min(c0 + CHUNK, n_win)
                out[c0:c1] = ((raw[c0:c1].astype("float64") - offset_counts) / gain).astype("float32")
            del raw
            comp_gaps = _complement(covered, n_win)
            for a, b in comp_gaps:
                out[a:b] = 0.0
            if gaps is None:
                gaps = comp_gaps
            arrays[comp] = out
            offsets[comp] = offset_counts / gain
    if gaps:
        logger.info(f"{station}: {len(gaps)} gap(s), {sum(b - a for a, b in gaps) / fs:.1f} s zeroed")
    return Segment(
        station=station,
        survey=survey_name,
        t0=grid.time_at(i_win / fs / 3600.0),
        sample_rate=fs,
        n=n_win,
        arrays=arrays,
        offsets=offsets,
        gains=dict(grid.gains),
        scalar_only=set(grid.scalar_only),
        gaps=gaps or [],
    )


@dataclass
class SegmentQC:
    """Output of one `compute_segment_qc` call for a segment and optional remote.

    Times `t_s` are seconds from the segment's `t0`.

    Attributes:
        station (str): Local station.
        remote (str | None): Remote station, or None.
        t0 (pd.Timestamp): Segment start, UTC.
        duration_s (float): Segment length in seconds.
        sample_rate (float): Sample rate in Hz.
        win_s (float): Base window of the ladder in seconds.
        step_s (float): Base step of the ladder in seconds.
        channels (list[str]): Channels computed, remote coils prefixed "r_".
        pairs (list[tuple[str, str]]): Coherence pairs computed.
        psd_stages (list): `psd_ladder` output, [(fs, freqs, {channel: psd}), ...],
            over the local channels plus the remote's coils when given.
        plan (pd.DataFrame): `levels_plan` output.
        coh_levels (dict): `cascade` coherence levels per pair.
        pow_levels (dict): `cascade` power levels per channel.
        base_psd (dict): `cascade` base-level PSD.
        band_curves (dict): `band_curves[pair][label]` is `(t_s, values)`
            from `band_from_levels` over `BANDS_S`.
        coherograms (dict): `coherograms[pair]` is `(t_s, periods, image)`
            from `levels_to_grid`.
        spectrograms (dict): `spectrograms[comp]` is `(t_s, periods, image)`,
            the image in dB.
        note (str): Why the QC differs from the request, e.g. a remote that
            does not cover the window; set by the worker and shown in every
            view's title.
        scalar_only (set): Channels (r_ for the remote's) calibrated by the
            scalar gain only, for the labels.
        roles (dict): Channels playing Bx, By, Ex, Ey (`channels.roles`,
            keyed hx hy ex ey).
        remote_roles (dict): The remote's coils (r_...).
    """

    station: str
    remote: str | None
    t0: pd.Timestamp
    duration_s: float
    sample_rate: float
    win_s: float
    step_s: float
    channels: list[str]
    pairs: list[tuple[str, str]]
    psd_stages: list
    plan: pd.DataFrame
    coh_levels: dict
    pow_levels: dict
    base_psd: dict
    band_curves: dict
    coherograms: dict
    spectrograms: dict

    # why the QC differs from the request, e.g. a remote that does not
    # cover this window (set by the worker, shown in every view's title)
    note: str = ""
    # channels (r_ for the remote's) in nT from the scalar gain only, for the labels
    scalar_only: set = field(default_factory=set)
    # who plays Bx, By, Ex, Ey (`channels.roles`, keyed hx hy ex ey), and the remote's coils (r_...)
    roles: dict = field(default_factory=dict)
    remote_roles: dict = field(default_factory=dict)

def _report(progress, percent: int, message: str) -> None:
    """Call `progress(percent, message)` if a callback was given."""
    if progress is not None:
        progress(int(percent), message)


def _plan(sample_rate: float, duration_s: float, win_s: float, step_s: float):
    """Run `levels_plan` at the default segment length (NPERSEG), halving it while no level fits.

    Raises:
        ValueError: If no level fits even at `MIN_NPERSEG`.
    """
    nperseg = NPERSEG
    while True:
        try:
            return levels_plan(sample_rate, duration_s, win_s=win_s, step_s=step_s, nperseg=nperseg)
        except ValueError:
            if nperseg // 2 < MIN_NPERSEG:
                raise
            nperseg //= 2


def _psd_nperseg(n: int) -> int:
    """Return PSD_NPERSEG, halved while `n` samples hold fewer than PSD_MIN_SEGMENTS segments."""
    nperseg = PSD_NPERSEG
    while nperseg > MIN_NPERSEG and n < PSD_MIN_SEGMENTS * nperseg:
        nperseg //= 2
    return nperseg


def compute_segment_qc(
    segment: Segment,
    remote: Segment | None = None,
    win_s: float = WIN_S,
    step_s: float = STEP_S,
    progress=None,
) -> SegmentQC:
    """Compute a segment's coherence and power ladders, band lines and PSDs.

    Every number comes from `mtproc.timefreq`; this function chooses the
    window and copies the arrays. `win_s` and `step_s` default to 120 s and
    30 s, where `scripts/site_qc.py` uses 20 and 10 min: on a record of a day
    or two a 20 min window gives a few hundred columns, on a 1 h segment it
    would give four. 120 s stepped by 30 s puts 117 columns on a 1 h segment's
    base level (20 is the fewest worth drawing), and `levels_plan`'s
    `min_windows` drops any deeper level whose window no longer fits three
    times, so a 1 h segment reaches periods of about 260 s and a 3 h one about
    1000 s. The PSD ladder runs one channel at a time, since `psd_ladder`
    casts its input to float64 (86 MB for one channel of a 3 h segment, 520 MB
    for six).

    `cascade` and `psd_ladder` consume their input, so they receive copies
    and `segment` and `remote` are left unchanged: one float32 copy of every
    channel for the cascade, released level by level as it decimates, and
    one channel at a time for the PSD ladder.

    Args:
        segment (Segment): The local segment.
        remote (Segment | None): A remote segment on the same grid.
        win_s (float): Base window in seconds.
        step_s (float): Base step in seconds.
        progress: Optional callable `progress(percent, message)`, called
            between stages.

    Returns:
        SegmentQC: The QC of the segment.

    Raises:
        ValueError: If the remote is not on the local segment's grid (a
            different length or sample rate, or a start more than half a
            sample off), or the ladder does not fit the segment.
    """
    record = segment.to_record()
    local_roles, remote_roles = roles(record.arrays), {}
    channels = order(record.arrays)
    pairs = resolve_pairs(LOCAL_PAIRS, local_roles)
    remote_name = None
    if remote is not None:
        if remote.n != segment.n or remote.sample_rate != segment.sample_rate:
            raise ValueError("the remote segment is not on the local segment's grid")
        shift = (remote.t0 - segment.t0).total_seconds() * segment.sample_rate
        if abs(shift) > 0.5:
            raise ValueError(f"the remote segment starts {shift:.2f} samples off the local one")
        r = remote.to_record("r_")
        r.t0 = segment.t0  # within half a sample: the same grid
        record = merge(record, r)
        remote_name = remote.station
        remote_roles = roles(remote.arrays, prefix="r_")
        channels += [remote_roles[k] for k in ("hx", "hy") if k in remote_roles]
        pairs += resolve_pairs(REMOTE_PAIRS, local_roles, remote_roles)

    _report(progress, 2, "planning the level ladder")
    plan = _plan(record.sample_rate, record.duration_s, win_s, step_s)

    _report(progress, 5, f"cascade: {len(plan)} levels, {len(channels)} channels, {len(pairs)} pairs")
    copies = {c: record.arrays[c].copy() for c in channels}
    coh_levels, pow_levels, base_psd = cascade(
        copies, record.gaps, record.sample_rate, plan, tuple(channels), tuple(pairs)
    )
    del copies

    _report(progress, 60, "band curves and grids")
    band_curves, coherograms = {}, {}
    for pair in pairs:
        t = coh_levels[pair][0][0]
        band_curves[pair] = {
            label: (t, band_from_levels(coh_levels[pair], lo, hi, t)) for lo, hi, label in BANDS_S
        }
        periods, image = levels_to_grid(coh_levels[pair], t)
        coherograms[pair] = (t, periods, image)
    spectrograms = {}
    for comp in channels:
        t = pow_levels[comp][0][0]
        periods, image = levels_to_grid(pow_levels[comp], t)
        spectrograms[comp] = (t, periods, power_db(image))

    psd_stages: list = []
    nperseg = _psd_nperseg(record.n)
    for k, comp in enumerate(channels):
        _report(progress, 65 + 35 * k // len(channels), f"PSD ladder: {comp}")
        stages = psd_ladder({comp: record.arrays[comp].copy()}, record.gaps, record.sample_rate, [comp],
                            nperseg=nperseg)
        for level, (fs, freqs, row) in enumerate(stages):
            if level == len(psd_stages):
                psd_stages.append((fs, freqs, {}))
            psd_stages[level][2].update(row)
    _report(progress, 100, "done")

    return SegmentQC(
        station=segment.station,
        remote=remote_name,
        t0=segment.t0,
        duration_s=segment.duration_s,
        sample_rate=segment.sample_rate,
        win_s=float(win_s),
        step_s=float(step_s),
        channels=channels,
        pairs=pairs,
        psd_stages=psd_stages,
        plan=plan,
        coh_levels=coh_levels,
        pow_levels=pow_levels,
        base_psd=base_psd,
        band_curves=band_curves,
        coherograms=coherograms,
        spectrograms=spectrograms,
        scalar_only=set(record.scalar_only),
        roles=local_roles,
        remote_roles=remote_roles,
    )
