"""Time-resolved spectra and coherence for per-site QC, on a decimation cascade.

The AusLAMP long-period QC figures (whole-record overview, band coherence vs
time, coherogram, spectrogram) computed each level of their period ladder by
growing the FFT length at the native 1 Hz rate. At 1000 Hz that is hopeless:
a 2000 s period would need a 2-million-point FFT on a 160 M-sample channel.
Here the ladder is a **factor-4 decimation cascade** instead, the same shape
`bbmt.bands.lemimt_band_scheme` lays out for processing: the FFT length is
fixed at every level and the sample rate drops by 4, so each level's segment
covers 4x the period range of the one below it. Numerically the two are the
same Welch estimate over the same segment durations; the cascade just gets
there for 1/4 of the work per level and never holds more than one level's
copy of the data (`cascade` replaces its input dict in place).

The pieces, in the order the figures use them:

- `load_station`    every run of a station concatenated onto one sample grid,
                    NaN in the gaps, calibrated to physical units by the
                    scalar (frequency-independent) part of the MTH5 filter
                    chain. A `grid=` argument places a remote station on the
                    local station's grid, which is what `bbmt.qc.align` does
                    for a single run pair, generalised to many runs and to
                    partial overlap (the non-overlapping part is a gap).
- `levels_plan`     one row per level: sample rate, segment, window, step and
                    the period slice it covers. The window grows with the
                    level so every level keeps >= `min_segments` Welch
                    segments at its longest period.
- `cascade`         one pass down the ladder: per-window Welch auto- and
                    cross-spectra for every channel and pair at once (the
                    segment FFTs are computed once per channel per window and
                    shared by every pair), averaged into log-period bins.
- `levels_to_grid`, `band_from_levels`   stitch the levels onto the base
                    level's time grid, as one image or as one band line.

Scaling matches `scipy.signal.welch(..., scaling="density")` and the
per-frequency coherence matches `scipy.signal.coherence`, both verified
against scipy; band lines and images are then bin-averages of those, exactly
as the AusLAMP figures do it.

Windows: the mean is removed per segment; a segment touching a gap is
dropped and a window keeping fewer than half its segments is left NaN. The
DC bin is dropped; a log-period bin holding no FFT harmonic is dropped
rather than drawn as a hole.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from scipy.signal import decimate, get_window

DAY = 86400.0

CHANNELS = ("hx", "hy", "hz", "ex", "ey")
UNIT = {"hx": "nT", "hy": "nT", "hz": "nT", "ex": "mV/km", "ey": "mV/km"}
MAGNETIC = ("hx", "hy", "hz")
COLOUR = {"hx": "C0", "hy": "C1", "hz": "C2", "ex": "C3", "ey": "C4"}

# component -> the label Ben's figures use (B for the measured field)
BLABEL = {"hx": "Bx", "hy": "By", "hz": "Bz", "ex": "Ex", "ey": "Ey"}

LOCAL_PAIRS = (("hx", "ey"), ("hy", "ex"), ("hx", "hy"), ("ex", "ey"))
REMOTE_PAIRS = (("hx", "r_hx"), ("hy", "r_hy"), ("ex", "r_hy"), ("ey", "r_hx"))

# band groups for broadband, the AusLAMP figure-02 lines rebased on 0.01-1000 s
BANDS_S = (
    (0.01, 0.1, "0.01-0.1 s"),
    (0.1, 1.0, "0.1-1 s"),
    (1.0, 10.0, "1-10 s"),
    (10.0, 100.0, "10-100 s"),
    (100.0, 1000.0, "100-1000 s"),
)
GUIDE_S = (0.02, 1.0, 10.0, 100.0)  # mains at 0.02 s, then the decade lines

PER_DECADE = 8
MIN_SEGMENTS = 8
LEVEL_FACTOR = 4
NPERSEG = 1024
MAX_SEGMENTS = 512
PMIN_S = 0.005
PMAX_S = 2000.0
# a decimation FIR smears a gap this many output samples either side
GAP_DILATE = 32


def pair_label(pair: tuple[str, str]) -> str:
    """'Bx-Ey', 'Ex-rBy', ... for a (component, component) pair."""
    return "-".join(
        ("r" + BLABEL[c[2:]]) if c.startswith("r_") else BLABEL[c] for c in pair
    )


# ---------------------------------------------------------------- loading


@dataclass
class Record:
    """One station's whole deployment on a single sample grid, in physical units.

    `arrays[comp]` is float32 with the channel's DC offset **removed** (kept in
    `offsets[comp]`, same units): at 1000 Hz a LEMI count sits around 1e7-1e9,
    where a float32 ulp is tens of counts and would bury the instrument's own
    LSB under quantisation noise. Everything spectral removes the mean anyway;
    only the overview adds the offset back.
    """

    station: str
    survey: str
    t0: pd.Timestamp
    sample_rate: float
    n: int
    arrays: dict[str, np.ndarray]
    offsets: dict[str, float]
    gains: dict[str, float]
    gaps: list[tuple[int, int]] = field(default_factory=list)
    scalar_only: set[str] = field(default_factory=set)

    @property
    def duration_s(self) -> float:
        return self.n / self.sample_rate

    def value(self, comp: str) -> np.ndarray:
        """The channel with its DC offset added back, float64 (for the overview)."""
        return self.arrays[comp].astype("float64") + self.offsets[comp]


def _scalar_gain(channel) -> tuple[float, bool]:
    """(product of the frequency-independent filter gains, whether any shape filter was skipped).

    The MTH5 chain for a LEMI-423 magnetic channel is
    [linear nT->count coefficient, coil response table, `lemi423_b_scale`
    coefficient]; for an electric channel [dipole-length coefficient, linear
    coefficient] -- so the electrics come out fully calibrated and the
    magnetics carry the coil's shape, which a DC-ish overview does not need.
    Calibration divides by the chain, so counts / gain is the physical value.
    """
    gain, skipped = 1.0, False
    for f in channel.channel_response.filters_list:
        if type(f).__name__ == "CoefficientFilter":
            gain *= float(f.gain)
        else:
            skipped = True
            logger.debug(f"{channel.metadata.component}: shape filter {f.name!r} not applied")
    return gain, skipped


def _real_runs(station_group) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """(run id, start, end) for every run group holding data, earliest first.

    Aurora/mth5 write auxiliary station-level groups (Features,
    Fourier_Coefficients, Transfer_Functions) whose time period is the null
    1980-01-01; they are dropped here, as `bbmt.qc.longest_run` drops them.
    """
    runs = []
    for run_id in station_group.groups_list:
        t = station_group.get_run(run_id).metadata.time_period
        start, end = pd.Timestamp(str(t.start)), pd.Timestamp(str(t.end))
        if start.year < 1990 or end <= start:
            continue
        runs.append((run_id, start, end))
    return sorted(runs, key=lambda r: r[1])


def load_station(
    mth5_path: Path,
    survey_name: str,
    station: str,
    comps=CHANNELS,
    grid: tuple[pd.Timestamp, int, float] | None = None,
    prefix: str = "",
    chunk: int = 1 << 24,
) -> Record:
    """Every run of `station` concatenated onto one sample grid, calibrated.

    `grid` is (t0, n, sample_rate) -- pass another station's grid to place a
    remote on the local sample grid (samples it does not cover become gaps).
    Without it the grid spans the station's own first to last sample.
    `prefix` is prepended to the component keys ("r_" for a remote).
    The MTH5 is opened read-only and closed before returning.
    """
    mth5_path = Path(mth5_path)
    m = MTH5()
    m.open_mth5(mth5_path, mode="r")
    try:
        st = m.get_station(station, survey=survey_name)
        first_run = _real_runs(st)
        if not first_run:
            raise ValueError(f"{station}: no runs with data in {mth5_path}")
        # only the channels the archive holds (broadband surveys drop hz at
        # ingest: no sensor was attached)
        available = set(st.get_run(first_run[0][0]).groups_list)
        missing = [c for c in comps if c not in available]
        if missing:
            logger.info(f"{station}: channels {missing} not in the archive -- skipped")
            comps = [c for c in comps if c in available]
        if not comps:
            raise ValueError(f"{station}: none of the requested channels in {mth5_path}")
        sr = float(m.get_channel(station, first_run[0][0], comps[0], survey_name).metadata.sample_rate)
        runs = _real_runs(st)
        if grid is None:
            t0 = runs[0][1]
            last = runs[-1]
            n_last = m.get_channel(station, last[0], comps[0], survey_name).hdf5_dataset.shape[0]
            n = int(round((last[1] - t0).total_seconds() * sr)) + n_last
        else:
            t0, n, grid_sr = grid
            if abs(grid_sr - sr) > 1e-9:
                raise ValueError(f"{station}: sample rate {sr} != grid rate {grid_sr}")
        logger.info(
            f"{station}: {len(runs)} run(s), {n} samples at {sr:g} Hz "
            f"({n / sr / 3600:.2f} h) from {t0}"
        )

        arrays, offsets, gains, scalar_only = {}, {}, {}, set()
        covered: list[tuple[int, int]] = []
        for comp in comps:
            key = prefix + comp
            out = np.full(n, np.nan, dtype="float32")
            gain = offset_counts = None
            spans = []
            for run_id, start, _ in runs:
                ch = m.get_channel(station, run_id, comp, survey_name)
                ds = ch.hdf5_dataset
                n_run = ds.shape[0]
                i0 = int(round((start - t0).total_seconds() * sr))
                drift = (start - t0).total_seconds() * sr - i0
                if abs(drift) > 1e-3:
                    logger.warning(
                        f"{station} {run_id} {comp}: run start is {drift:.3f} samples "
                        f"off the grid -- placed at the nearest sample"
                    )
                if gain is None:
                    gain, skipped = _scalar_gain(ch)
                    if skipped:
                        scalar_only.add(key)
                    step = max(1, n_run // 200_000)
                    offset_counts = float(np.median(ds[::step].astype("float64")))
                # clip the run to the grid, then fill it in chunks so the int32
                # -> float64 -> float32 conversion never copies the whole run
                a, b = max(i0, 0), min(i0 + n_run, n)
                if b <= a:
                    logger.warning(f"{station} {run_id} {comp}: outside the grid, skipped")
                    continue
                for c0 in range(a, b, chunk):
                    c1 = min(c0 + chunk, b)
                    raw = ds[c0 - i0 : c1 - i0].astype("float64")
                    out[c0:c1] = ((raw - offset_counts) / gain).astype("float32")
                spans.append((a, b))
            arrays[key] = out
            offsets[key] = offset_counts / gain
            gains[key] = gain
            if not covered:
                covered = spans
        gaps = _complement(covered, n)
        if gaps:
            missing = sum(b - a for a, b in gaps) / sr
            logger.info(f"{station}: {len(gaps)} gap(s), {missing:.1f} s not covered")
    finally:
        m.close_mth5()

    return Record(
        station=station,
        survey=survey_name,
        t0=t0,
        sample_rate=sr,
        n=n,
        arrays=arrays,
        offsets=offsets,
        gains=gains,
        gaps=gaps,
        scalar_only=scalar_only,
    )


def _complement(spans: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
    """The [0, n) index ranges no span covers, merged and sorted."""
    out, cursor = [], 0
    for a, b in sorted(spans):
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < n:
        out.append((cursor, n))
    return out


def merge(local: Record, remote: Record) -> Record:
    """Fold a remote Record (already loaded on the local grid) into the local one."""
    if remote.n != local.n or remote.t0 != local.t0:
        raise ValueError("remote was not loaded on the local grid")
    local.arrays.update(remote.arrays)
    local.offsets.update(remote.offsets)
    local.gains.update(remote.gains)
    local.scalar_only |= remote.scalar_only
    local.gaps = _merge_intervals(local.gaps + remote.gaps)
    return local


def spot_check_calibration(
    mth5_path: Path,
    survey_name: str,
    station: str,
    record: Record,
    comps=CHANNELS,
    prefix: str = "",
    n_probe: int = 7,
) -> dict[str, float]:
    """Re-read scattered single samples straight from the MTH5 and compare.

    An independent path to the same number: each probe index is mapped back to
    its run and local offset from the run metadata alone, the raw count is read
    one sample at a time, and the calibration gain is recomputed from the
    channel's filter chain. Comparing that with `record.arrays[comp][i] +
    record.offsets[comp]` tests the gain, the sign, the stored DC offset and
    the run-placement arithmetic all at once -- a misplaced run, a dropped
    filter stage or an off-by-N index cannot survive it. Returns
    {component: largest absolute difference in units of the channel's std}.
    """
    # only channels that were actually loaded (broadband archives carry no hz)
    comps = [c for c in comps if (prefix + c) in record.arrays]
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    worst = {}
    try:
        runs = _real_runs(m.get_station(station, survey=survey_name))
        for comp in comps:
            key = prefix + comp
            sd = float(np.nanstd(record.arrays[key])) or 1.0
            worst[key] = 0.0
            for run_id, start, _ in runs:
                ch = m.get_channel(station, run_id, comp, survey_name)
                gain, _ = _scalar_gain(ch)
                n_run = ch.hdf5_dataset.shape[0]
                base = int(round((start - record.t0).total_seconds() * record.sample_rate))
                for local in np.linspace(0, n_run - 1, n_probe).round().astype(int):
                    i = base + int(local)
                    if not 0 <= i < record.n:
                        continue
                    expect = float(ch.hdf5_dataset[int(local)]) / gain
                    got = float(record.arrays[key][i]) + record.offsets[key]
                    worst[key] = max(worst[key], abs(got - expect) / sd)
    finally:
        m.close_mth5()
    return worst


def _merge_intervals(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# ---------------------------------------------------------------- the level ladder


def levels_plan(
    sample_rate: float,
    record_s: float,
    win_s: float = 1200.0,
    step_s: float = 600.0,
    pmin: float = PMIN_S,
    pmax: float = PMAX_S,
    nperseg: int = NPERSEG,
    factor: int = LEVEL_FACTOR,
    min_segments: int = MIN_SEGMENTS,
    min_windows: int = 3,
) -> pd.DataFrame:
    """The decimation ladder, one row per level, without reading any data.

    Level L runs at `sample_rate / factor**L`, so its `nperseg`-point segment
    is `factor**L` times longer and it covers the period slice from the level
    below it up to its own segment length. The base level uses the caller's
    window and step; a deeper level whose segment no longer leaves
    `min_segments` Welch segments in that window gets a window long enough
    that it does (and a step of half a segment, as the AusLAMP ladder does),
    so the long periods are still estimated from a sane number of segments.
    The ladder stops at the level reaching `pmax`, or earlier if its window
    no longer fits `min_windows` times into the record.
    """
    rows = []
    lo = float(pmin)
    for level in range(32):
        fs = sample_rate / factor**level
        segment_s = nperseg / fs
        hi = min(segment_s, pmax)
        if lo >= hi:
            break
        # Welch with 50% overlap puts 2*W/S - 1 segments in a window of W s
        need_s = 0.5 * (min_segments + 1) * segment_s
        if need_s <= win_s:
            w, st = float(win_s), float(step_s)
        else:
            w, st = need_s, max(float(step_s), 0.5 * segment_s)
        n_windows = int((record_s - w) // st) + 1 if record_s >= w else 0
        if n_windows < min_windows:
            logger.warning(
                f"level {level} (periods {lo:.4g}-{hi:.4g} s) needs a {w / 3600:.2f} h "
                f"window and the record is {record_s / 3600:.2f} h -- ladder stops below it"
            )
            break
        rows.append(
            dict(
                level=level,
                sample_rate=fs,
                nperseg=int(nperseg),
                segment_s=segment_s,
                window_s=w,
                step_s=st,
                n_segments=int(2 * w / segment_s) - 1,
                n_windows=n_windows,
                period_floor_s=lo,
                period_ceiling_s=hi,
            )
        )
        if hi >= pmax:
            break
        lo = hi
    if not rows:
        raise ValueError("no usable level: the record is shorter than one base window")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- per-window spectra


def _log_bins(nperseg: int, fs: float, pmin: float, pmax: float, per_decade: int):
    """(bin index per FFT harmonic, in-range mask, harmonics per bin, bin centre periods).

    The DC bin is dropped; bins holding no harmonic are dropped by the caller.
    """
    periods = 1.0 / np.fft.rfftfreq(nperseg, 1.0 / fs)[1:]
    n_bins = max(1, int(round(np.log10(pmax / pmin) * per_decade)))
    edges = np.geomspace(pmin, pmax, n_bins + 1)
    centres = np.sqrt(edges[:-1] * edges[1:])
    idx = np.digitize(periods, edges) - 1
    ok = (idx >= 0) & (idx < n_bins)
    counts = np.bincount(idx[ok], minlength=n_bins).astype(float)
    return idx, ok, counts, centres


def _segment_starts(window_n: int, nperseg: int, max_segments: int) -> np.ndarray:
    """Offsets of the Welch segments inside a window, thinned evenly to `max_segments`.

    At 1000 Hz a 20-minute window holds ~2300 segments of 1024 samples; a few
    hundred already give a coherence estimate far tighter than the QC needs,
    so above `max_segments` the segments are spread evenly over the window
    instead of taken back to back. Time coverage is unchanged.
    """
    hop = nperseg // 2
    starts = np.arange(0, window_n - nperseg + 1, hop, dtype=int)
    if starts.size > max_segments:
        pick = np.linspace(0, starts.size - 1, max_segments).round().astype(int)
        starts = starts[pick]
    return starts


def window_spectra(
    arrays: dict[str, np.ndarray],
    gaps: list[tuple[int, int]],
    fs: float,
    win_s: float,
    step_s: float,
    nperseg: int,
    channels: tuple[str, ...],
    pairs: tuple[tuple[str, str], ...],
    max_segments: int = MAX_SEGMENTS,
):
    """Welch auto- and cross-spectra per window, every channel and pair in one pass.

    Returns (window centres in seconds from sample 0, one-sided frequencies,
    {channel: Sxx[window, freq]}, {pair: Sxy[window, freq] complex}). The
    segment FFTs are taken once per channel per window and shared by every
    pair, which is the whole point of doing this here rather than calling
    `scipy.signal.coherence` per pair. Scaling matches
    `scipy.signal.welch(..., scaling="density")`; the DC bin is kept here and
    dropped by the binning.
    """
    n = min(a.size for a in arrays.values())
    w = int(round(win_s * fs))
    st = max(1, int(round(step_s * fs)))
    starts = np.arange(0, max(1, n - w + 1), st, dtype=int)
    seg0 = _segment_starts(w, nperseg, max_segments)
    win = get_window("hann", nperseg).astype("float32")
    scale = 1.0 / (fs * float(np.sum(win.astype("float64") ** 2)))
    n_freq = nperseg // 2 + 1
    freqs = np.fft.rfftfreq(nperseg, 1.0 / fs)
    # one-sided: every bin but DC and (for even nperseg) Nyquist carries twice
    dbl = np.full(n_freq, 2.0)
    dbl[0] = 1.0
    if nperseg % 2 == 0:
        dbl[-1] = 1.0

    psd = {c: np.full((starts.size, n_freq), np.nan) for c in channels}
    csd = {p: np.full((starts.size, n_freq), np.nan, dtype="complex128") for p in pairs}
    n_bad = 0
    for k, s in enumerate(starts):
        good = np.ones(seg0.size, dtype=bool)
        for g0, g1 in gaps:
            if g1 <= s or g0 >= s + w:
                continue
            good &= (s + seg0 + nperseg <= g0) | (s + seg0 >= g1)
        if good.sum() < max(4, 0.5 * seg0.size):
            n_bad += 1
            continue
        offs = seg0[good]
        ffts = {}
        for c in channels:
            view = np.lib.stride_tricks.sliding_window_view(arrays[c][s : s + w], nperseg)[offs]
            segs = (view - view.mean(axis=1, keepdims=True)) * win
            ffts[c] = np.fft.rfft(segs, axis=1)
        for c in channels:
            psd[c][k] = dbl * scale * np.mean(np.abs(ffts[c]) ** 2, axis=0)
        for a, b in pairs:
            # conj on the first channel, as scipy.signal.csd(x, y) has it
            csd[(a, b)][k] = dbl * scale * np.mean(np.conj(ffts[a]) * ffts[b], axis=0)
    if n_bad:
        logger.info(f"  {n_bad}/{starts.size} window(s) dropped (gaps)")
    return (starts + w / 2.0) / fs, freqs, psd, csd


def _bin_average(values: np.ndarray, idx, ok, counts) -> np.ndarray:
    """Average a [window, freq] block (DC already dropped) into the log-period bins."""
    n_bins = counts.size
    out = np.full((values.shape[0], n_bins), np.nan)
    for k in range(values.shape[0]):
        row = values[k]
        if not np.isfinite(row).all():
            continue
        acc = np.bincount(idx[ok], weights=row[ok], minlength=n_bins)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[k] = np.where(counts > 0, acc / np.maximum(counts, 1), np.nan)
    return out


def cascade(
    arrays: dict[str, np.ndarray],
    gaps: list[tuple[int, int]],
    sample_rate: float,
    plan: pd.DataFrame,
    channels: tuple[str, ...],
    pairs: tuple[tuple[str, str], ...],
    per_decade: int = PER_DECADE,
    max_segments: int = MAX_SEGMENTS,
    factor: int = LEVEL_FACTOR,
):
    """Walk the ladder once, returning coherence and power maps per level.

    Returns ({pair: [(t_s, periods, coh), ...]}, {channel: [(t_s, periods, psd), ...]},
    {channel: (freqs, median level-0 PSD)}). The first two hold one entry per
    level, which `levels_to_grid` and `band_from_levels` stitch; the third is
    the base level at full frequency resolution, for `line_excess`.

    **`arrays` is consumed**: each level's entries are replaced by the
    decimated copy, so the full-rate arrays are released once level 0 is done
    and the peak footprint is one level plus a quarter. Gap samples are zeroed
    first (the arrays are offset-removed, so zero is the channel mean) because
    a FIR decimation would otherwise smear one NaN across the whole record;
    the gap list is carried down the cascade and dilated by `GAP_DILATE`
    output samples per level to cover the filter's smear.
    """
    for a, b in gaps:
        for c in channels:
            arrays[c][a:b] = 0.0
    for c in channels:
        n_nan = int(np.isnan(arrays[c]).sum())
        if n_nan:
            logger.warning(f"{c}: {n_nan} NaN outside the run gaps -- zeroed")
            np.nan_to_num(arrays[c], copy=False)

    coh_levels = {p: [] for p in pairs}
    pow_levels = {c: [] for c in channels}
    base_psd: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    fs = float(sample_rate)
    level_gaps = list(gaps)
    for row in plan.itertuples():
        if row.level > 0:
            for c in channels:
                arrays[c] = decimate(arrays[c], factor, ftype="fir", zero_phase=True).astype(
                    "float32"
                )
            fs /= factor
            n_level = arrays[channels[0]].size
            level_gaps = _merge_intervals(
                [
                    (max(0, a // factor - GAP_DILATE), min(n_level, b // factor + 1 + GAP_DILATE))
                    for a, b in level_gaps
                ]
            )
        logger.info(
            f"level {row.level}: {fs:g} Hz, segment {row.segment_s:.4g} s, window "
            f"{row.window_s / 60:.1f} min, step {row.step_s / 60:.1f} min, "
            f"periods {row.period_floor_s:.4g}-{row.period_ceiling_s:.4g} s"
        )
        t, freqs, psd, csd = window_spectra(
            arrays,
            level_gaps,
            fs,
            row.window_s,
            row.step_s,
            row.nperseg,
            channels,
            pairs,
            max_segments=max_segments,
        )
        if row.level == 0:
            # the level-0 spectra at full frequency resolution, kept for the
            # narrow-line report: a log-period bin at 8 per decade is 15 Hz
            # wide at 50 Hz and cannot show a mains line, so the number has to
            # come from here (see `line_excess`)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                base_psd = {c: (freqs, np.nanmedian(psd[c], axis=0)) for c in channels}
        idx, ok, counts, centres = _log_bins(
            row.nperseg, fs, row.period_floor_s, row.period_ceiling_s, per_decade
        )
        keep = counts > 0
        for c in channels:
            binned = _bin_average(psd[c][:, 1:], idx, ok, counts)
            pow_levels[c].append((t, centres[keep], binned[:, keep]))
        for pair in pairs:
            a, b = pair
            with np.errstate(invalid="ignore", divide="ignore"):
                gamma2 = np.abs(csd[pair][:, 1:]) ** 2 / (psd[a][:, 1:] * psd[b][:, 1:])
            binned = _bin_average(np.clip(gamma2.real, 0.0, 1.0), idx, ok, counts)
            coh_levels[pair].append((t, centres[keep], binned[:, keep]))
    return coh_levels, pow_levels, base_psd


def line_excess(freqs: np.ndarray, psd: np.ndarray, f0: float, half_width: float = 10.0,
                guard: float = 2.0) -> float:
    """dB by which the spectrum at `f0` stands above the floor either side of it.

    The floor is the median density over [f0 - half_width, f0 + half_width]
    excluding a +-`guard` Hz window around the line itself. Reported per
    channel because a narrow line cannot survive log-period binning: at 8 bins
    per decade the bin holding 50 Hz is ~15 Hz wide, so a line standing 2 dB
    above the floor in a 1 Hz resolution bandwidth is diluted to ~0.2 dB and
    is invisible in the spectrogram however the colours are scaled.
    """
    near = (freqs >= f0 - half_width) & (freqs <= f0 + half_width)
    floor_m = near & (np.abs(freqs - f0) > guard)
    if not floor_m.any() or not near.any():
        return float("nan")
    k = int(np.argmin(np.abs(freqs - f0)))
    with np.errstate(divide="ignore", invalid="ignore"):
        return float(10.0 * np.log10(psd[k] / np.nanmedian(psd[floor_m])))


# ---------------------------------------------------------------- stitching levels


def levels_to_grid(levels, t_base):
    """Every level interpolated (nearest window) onto the base time grid, as one image."""
    per_all, cols = [], []
    for t, per, img in levels:
        if per.size == 0:
            continue
        i = np.clip(np.searchsorted(t, t_base), 0, len(t) - 1)
        per_all.append(per)
        cols.append(img[i])
    per = np.concatenate(per_all)
    out = np.concatenate(cols, axis=1)
    order = np.argsort(per)
    return per[order], out[:, order]


def band_from_levels(levels, lo_s, hi_s, t_base) -> np.ndarray:
    """One band line on the base time grid, averaged over every level reaching the band."""
    out = []
    for t, per, img in levels:
        m = (per >= lo_s) & (per <= hi_s)
        if not m.any():
            continue
        v = np.nanmean(img[:, m], axis=1)
        if np.isfinite(v).any():
            i = np.clip(np.searchsorted(t, t_base), 0, len(t) - 1)
            out.append(v[i])
    if not out:
        return np.full(len(t_base), np.nan)
    with np.errstate(all="ignore"):
        return np.nanmean(np.vstack(out), axis=0)


def running_median(a: np.ndarray, n_windows: int) -> np.ndarray:
    """Centred running median along time (axis 0), NaN-tolerant."""
    if n_windows <= 1:
        return a
    return (
        pd.DataFrame(a).rolling(int(n_windows), center=True, min_periods=1).median().to_numpy()
    )


# ---------------------------------------------------------------- time axis


def iso(t: pd.Timestamp) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")


def day_axis(t0: pd.Timestamp, duration_s: float):
    """(tick positions in days from t0, tick labels) snapped to round UTC times.

    The AusLAMP version ticked whole days, which is right for a record of
    weeks; a broadband deployment is ~2 days, so the step is chosen from
    quarter-hours up to 20 days for about 8 ticks and the label carries the
    time of day whenever the step is under a day.
    """
    days = duration_s / DAY
    steps = [1 / 96, 1 / 48, 1 / 24, 2 / 24, 3 / 24, 6 / 24, 12 / 24, 1, 2, 5, 10, 20]
    step = next((s for s in steps if days / s <= 9), steps[-1])
    t0 = pd.Timestamp(t0)
    origin = t0.timestamp()
    first = np.ceil(origin / (step * DAY)) * step * DAY
    abs_ticks = np.arange(first, origin + duration_s + 1e-6, step * DAY)
    ticks = (abs_ticks - origin) / DAY
    fmt = "%m-%d" if step >= 1 else "%m-%d %H:%M"
    labels = [(t0 + pd.Timedelta(days=float(d))).strftime(fmt) for d in ticks]
    return ticks, labels


def block_stats(x: np.ndarray, m: int):
    """(mean, min, max) of each block of m samples; the trailing partial block is dropped."""
    n = x.size // m * m
    a = x[:n].reshape(-1, m)
    if np.isnan(a).any():
        # a block falling wholly inside a gap is all-NaN and comes back NaN,
        # which is what the figure should draw: a hole, not a joined line
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(a, axis=1), np.nanmin(a, axis=1), np.nanmax(a, axis=1)
    return a.mean(axis=1, dtype="float64"), a.min(axis=1), a.max(axis=1)
