"""The segment QC engine: one 1-3 h stretch of a station, and the QC computed on it.

What the MATLAB App Designer app did on one 90-minute B423 file -- Welch
spectra, a spectrogram, band coherence -- done here on a window the student
picks on the Time Series tab, with a remote folded in. No product comes out
of this (no archive, no transfer function, no EDI, no report figure): the
numbers are drawn on the QC tabs and thrown away. And nothing spectral is
written here. `compute_segment_qc` calls `bbmt.timefreq` for every number --
`levels_plan`, `cascade`, `band_from_levels`, `levels_to_grid`, `psd_ladder`,
`power_db` -- the same functions `scripts/site_qc.py` and `scripts/psd_qc.py`
call on a whole record, so a segment's coherogram is a slice of what figure
03 would show, not another estimate of it.

- `Segment`       one stretch in `bbmt.timefreq.Record`'s convention: float32
                  with the DC offset removed (a 1000 Hz LEMI count sits near
                  1e9, where a float32 ulp is tens of counts), zero in the
                  gaps, the gaps listed. `to_record()` gives a `Record`, so
                  `bbmt.timefreq.merge` folds a remote in unchanged.
- `load_segment`  reads it through `bbmt_gui.archive`'s run grid (`load_grid`,
                  `run_slices`), read-only, one channel at a time -- each
                  channel's counts are converted to offset-removed float32
                  before the next is read, so a 3 h segment (10.8 M samples
                  per channel, 43 MB as float32) peaks at the four channels
                  plus one channel's raw counts and a float64 chunk, well
                  under 400 MB. The 1-3 h limits are the GUI's rule, not this
                  function's.
- `SegmentQC`     everything one `compute_segment_qc` call produces.

No Qt in here; `bbmt_gui.segment_store` runs it off the GUI thread, and
`tests/segment_unit.py` runs it on a synthetic hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger

from bbmt.timefreq import (
    BANDS_S,
    CHANNELS as TF_CHANNELS,
    LOCAL_PAIRS,
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
from bbmt_gui.archive import CHANNELS, load_grid, run_slices

REMOTE_COMPS = ("hx", "hy")
# base window and step for a 1-3 h segment, seconds: see `compute_segment_qc`
WIN_S = 120.0
STEP_S = 30.0
CHUNK = 1 << 22  # samples per counts -> float32 conversion (32 MB as float64)


@dataclass
class Segment:
    """One stretch of a station, in `bbmt.timefreq.Record`'s convention.

    `arrays[comp]` is float32 with the channel's DC offset removed (kept in
    `offsets[comp]`, same units) for the reason `Record` gives: at 1000 Hz a
    LEMI count sits around 1e7-1e9, where a float32 ulp is tens of counts.
    `gaps` are the sample spans no run covers, as `Record.gaps`, and those
    samples are already zero (the channel mean), which is what `cascade` and
    `psd_ladder` do to them first anyway.
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
        return self.n / self.sample_rate

    @property
    def end(self) -> pd.Timestamp:
        return self.t0 + pd.Timedelta(microseconds=round(self.duration_s * 1e6))

    def to_record(self, prefix: str = "") -> Record:
        """A `Record` over this segment's grid; `prefix` ("r_") names a remote.

        The arrays are shared, not copied; the dicts, the set and the gap
        list are new objects, so `merge` never writes into this segment.
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
    comps=CHANNELS,
) -> Segment:
    """`station`'s samples from `start` to `end` (UTC), calibrated, offset removed.

    Placed on the station's own grid (`bbmt_gui.archive.load_grid`, so the
    first sample is the grid sample nearest `start` and `t0` is that sample's
    time), every run overlapping the window filled through `run_slices`. A
    remote loaded for the same `start`/`end` therefore has the same `n`, and
    a `t0` within half a sample, which `compute_segment_qc` checks before
    `merge`. The MTH5 is opened read-only for the run metadata and closed,
    then the datasets are sliced with h5py alone.
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
            # counts -> offset-removed float32 in chunks: never a whole
            # channel as float64 alongside its counts
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
    """What one `compute_segment_qc` call produces for a segment (and its remote).

    `psd_stages` is `psd_ladder`'s output, [(fs, freqs, {channel: psd}), ...],
    over the local channels plus r_hx/r_hy when a remote was given; `plan`,
    `coh_levels`, `pow_levels` and `base_psd` are `levels_plan`'s and
    `cascade`'s; `band_curves[pair][label]` is `(t_s, values)` from
    `band_from_levels` over `BANDS_S`; `coherograms[pair]` and
    `spectrograms[comp]` are `(t_s, periods, image)` from `levels_to_grid`,
    the spectrogram in dB. `t_s` is seconds from the segment's `t0`.
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

    # why the QC differs from what was asked for, e.g. a remote that does not
    # cover this window (set by the worker, shown in every view's title)
    note: str = ""
    # channels (r_ for the remote's) in nT from the scalar gain only, for the labels
    scalar_only: set = field(default_factory=set)

def _report(progress, percent: int, message: str) -> None:
    if progress is not None:
        progress(int(percent), message)


def compute_segment_qc(
    segment: Segment,
    remote: Segment | None = None,
    win_s: float = WIN_S,
    step_s: float = STEP_S,
    progress=None,
) -> SegmentQC:
    """The segment's ladder of coherence and power maps, band lines and PSDs.

    Every number comes from `bbmt.timefreq`; this function only chooses the
    window and copies the arrays. `win_s` / `step_s` default to 120 / 30 s
    where `scripts/site_qc.py` uses 20 / 10 min: on a 41 h record a 20 min
    window gives ~250 columns, on a 1 h segment it would give four. 120 s
    stepped by 30 s puts 117 columns on a 1 h segment's base level (20 is the
    least worth drawing) and `levels_plan`'s `min_windows` still drops any
    deeper level whose window no longer fits three times -- a 1 h segment
    keeps periods to ~260 s, a 3 h one to ~1000 s. The PSD ladder runs one
    channel at a time (`psd_ladder` casts what it is given to float64; one
    channel of a 3 h segment is 86 MB, six would be 520 MB).

    `segment` and `remote` are not modified: `cascade` and `psd_ladder`
    consume what they are given, so they get copies -- one float32 copy of
    every channel for the cascade (the segment's own size again, released
    level by level as the cascade decimates) and one channel at a time for
    the ladder. `progress(percent, message)` is called between stages.
    """
    record = segment.to_record()
    channels = [c for c in TF_CHANNELS if c in record.arrays]
    pairs = [p for p in LOCAL_PAIRS if p[0] in record.arrays and p[1] in record.arrays]
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
        channels += [c for c in ("r_hx", "r_hy") if c in record.arrays]
        pairs += [p for p in REMOTE_PAIRS if p[0] in record.arrays and p[1] in record.arrays]

    _report(progress, 2, "planning the level ladder")
    plan = levels_plan(record.sample_rate, record.duration_s, win_s=win_s, step_s=step_s)

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
    for k, comp in enumerate(channels):
        _report(progress, 65 + 35 * k // len(channels), f"PSD ladder: {comp}")
        stages = psd_ladder({comp: record.arrays[comp].copy()}, record.gaps, record.sample_rate, [comp])
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
    )
