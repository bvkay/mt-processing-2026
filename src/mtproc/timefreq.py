# -*- coding: utf-8 -*-
"""
Time-resolved spectra and coherence for per-site QC on a decimation cascade

The AusLAMP long-period QC figures (whole-record overview, band coherence
against time, coherogram, spectrogram) compute each level of their period
ladder by growing the FFT length at the native 1 Hz rate. At 1000 Hz a
2000 s period would need a 2-million-point FFT on a 160 M-sample channel, so
here the ladder is a factor-4 decimation cascade, the same shape
`mtproc.bands.build_band_scheme` lays out for processing: the FFT length is
fixed at every level and the sample rate drops by 4, so each level's segment
covers 4 times the period range of the one below it. Both give the same
Welch estimate over the same segment durations; the cascade costs a quarter
of the work per level and holds one level's copy of the data at a time
(`cascade` replaces its input dict in place).

The pieces, in the order the figures use them:

- `load_station`    every run of a station concatenated onto one sample grid,
                    NaN in the gaps, calibrated to physical units by the
                    scalar (frequency-independent) part of the MTH5 filter
                    chain. A `grid=` argument places a remote station on the
                    local station's grid, which is what `mtproc.qc.align` does
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
against scipy; band lines and images are bin averages of those, as in the
AusLAMP figures.

Windows: the mean is removed per segment; a segment touching a gap is
dropped and a window keeping fewer than half its segments is left NaN. The
DC bin is dropped, and a log-period bin holding no FFT harmonic is dropped
rather than drawn as a hole.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from scipy.signal import decimate, get_window, welch

DAY = 86400.0

CHANNELS = ("hx", "hy", "hz", "ex", "ey")
UNIT = {"hx": "nT", "hy": "nT", "hz": "nT", "ex": "mV/km", "ey": "mV/km"}
MAGNETIC = ("hx", "hy", "hz")
COLOUR = {"hx": "C0", "hy": "C1", "hz": "C2", "ex": "C3", "ey": "C4"}

# component -> the plotting label (B for the measured field)
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
# fewest Welch segments (STFT windows) an estimate is formed from: `window_spectra`
# leaves a window with fewer NaN, and `mtproc.crosspower` uses it as its compute floor
MIN_WINDOWS = 4


def pair_label(pair: tuple[str, str]) -> str:
    """Return the plot label of a component pair, such as 'Bx-Ey' or 'Ex-rBy'."""
    return "-".join(
        ("r" + BLABEL[c[2:]]) if c.startswith("r_") else BLABEL[c] for c in pair
    )


# ---------------------------------------------------------------- loading


@dataclass
class Record:
    """One station's whole deployment on a single sample grid, in physical units.

    ``arrays[comp]`` is float32 with the channel's DC offset removed and kept
    in ``offsets[comp]``, in the same units. At 1000 Hz a LEMI count sits
    around 1e7-1e9, where a float32 ulp is tens of counts and would bury the
    instrument's LSB under quantisation noise. The spectral estimates remove
    the mean in any case; the overview adds the offset back (`value`).

    Attributes:
        station (str): Station id.
        survey (str): Survey id.
        t0 (pd.Timestamp): Time of sample 0.
        sample_rate (float): Sample rate in Hz.
        n (int): Number of samples.
        arrays (dict): Component to float32 samples, offset removed.
        offsets (dict): Component to DC offset in physical units.
        gains (dict): Component to scalar calibration gain.
        gaps (list of tuple): [start, stop) sample ranges with no data.
        scalar_only (set): Components whose chain has a shape filter that
            was not applied.
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
        """Record length in s."""
        return self.n / self.sample_rate

    def value(self, comp: str) -> np.ndarray:
        """Return the channel with its DC offset added back, as float64."""
        return self.arrays[comp].astype("float64") + self.offsets[comp]


def _scalar_gain(channel) -> tuple[float, bool]:
    """Return the scalar part of a channel's filter chain.

    The MTH5 chain for a LEMI-423 magnetic channel is [linear nT->count
    coefficient, coil response table, `lemi423_b_scale` coefficient]; for an
    electric channel it is [dipole-length coefficient, linear coefficient].
    The electrics therefore come out fully calibrated, and the magnetics
    lack the coil's shape, which a near-DC overview does not need.
    Calibration divides by the chain, so counts / gain is the physical value.

    Returns:
        tuple: ``(gain, skipped)``: the product of the coefficient-filter
        gains, and whether any shape filter was left out.
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
    """List every run group holding data, earliest first.

    Aurora and mth5 write auxiliary station-level groups (Features,
    Fourier_Coefficients, Transfer_Functions) whose time period is the null
    1980-01-01; they are skipped, as `mtproc.qc.longest_run` skips them.

    Returns:
        list of tuple: ``(run_id, start, end)``.
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
    """Load every run of a station onto one calibrated sample grid.

    Opens the MTH5 read-only and closes it before returning. Channels the
    archive lacks are skipped with a log line.

    Args:
        mth5_path (Path): MTH5 file.
        survey_name (str): Survey id.
        station (str): Station id.
        comps (iterable of str): Components to load.
        grid (tuple, optional): ``(t0, n, sample_rate)`` of another station,
            to place a remote on the local sample grid; samples it does not
            cover become gaps. Without it the grid spans the station's own
            first to last sample.
        prefix (str): Prepended to the component keys, "r_" for a remote.
        chunk (int): Samples converted per step.

    Returns:
        Record: The station's record.

    Raises:
        ValueError: If the station has no runs with data, none of the
            requested channels, or a sample rate different from `grid`.
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
        # ingest when no sensor was attached)
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
                # -> float64 -> float32 conversion does not copy the whole run
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
    """Return the [0, n) index ranges no span covers, merged and sorted."""
    out, cursor = [], 0
    for a, b in sorted(spans):
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < n:
        out.append((cursor, n))
    return out


def merge(local: Record, remote: Record) -> Record:
    """Fold a remote Record, loaded on the local grid, into the local one.

    Raises:
        ValueError: If the remote was not loaded on the local grid.
    """
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
    """Re-read scattered single samples from the MTH5 and compare them with a Record.

    Each probe index is mapped back to its run and local offset from the run
    metadata alone, the raw count is read one sample at a time, and the
    calibration gain is recomputed from the channel's filter chain.
    Comparing that with ``record.arrays[comp][i] + record.offsets[comp]``
    tests the gain, the sign, the stored DC offset and the run placement
    together, so a misplaced run, a dropped filter stage or an off-by-N
    index shows up. The archive is opened read-only.

    Args:
        mth5_path (Path): MTH5 file.
        survey_name (str): Survey id.
        station (str): Station id.
        record (Record): The loaded record.
        comps (iterable of str): Components to check; those not loaded are
            skipped.
        prefix (str): Key prefix used when loading.
        n_probe (int): Probes per run.

    Returns:
        dict: Component key to the largest absolute difference in units of
        the channel's standard deviation.
    """
    # only channels that were loaded (broadband archives carry no hz)
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
    """Merge overlapping or touching [start, stop) intervals, sorted by start."""
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
    """Plan the decimation ladder, one row per level, without reading data.

    Level L runs at ``sample_rate / factor**L``, so its `nperseg`-point
    segment is ``factor**L`` times longer and it covers the period slice
    from the level below it up to its own segment length. The base level
    uses the given window and step. A deeper level whose segment would leave
    fewer than `min_segments` Welch segments in that window gets a window
    long enough for them, and a step of at least half a segment, as in the
    AusLAMP ladder, so the long periods are estimated from enough segments.
    The ladder stops at the level reaching `pmax`, or earlier when a
    level's window no longer fits `min_windows` times into the record.

    Args:
        sample_rate (float): Base sample rate in Hz.
        record_s (float): Record length in s.
        win_s (float): Base window length in s.
        step_s (float): Base window step in s.
        pmin (float): Shortest period in s.
        pmax (float): Longest period in s.
        nperseg (int): Welch segment length in samples, the same on every
            level.
        factor (int): Decimation factor between levels.
        min_segments (int): Fewest Welch segments per window.
        min_windows (int): Fewest windows per level.

    Returns:
        pd.DataFrame: Columns level, sample_rate, nperseg, segment_s,
        window_s, step_s, n_segments, n_windows, period_floor_s and
        period_ceiling_s.

    Raises:
        ValueError: If no level is usable because the record is shorter
            than one base window.
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
    """Map FFT harmonics to log-period bins.

    The DC bin is excluded; bins holding no harmonic are dropped by the
    caller.

    Returns:
        tuple: ``(idx, ok, counts, centres)``: the bin index per harmonic,
        the in-range mask, the harmonics per bin and the bin centre periods.
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
    """Return the offsets of the Welch segments in a window, thinned evenly to `max_segments`.

    At 1000 Hz a 20 minute window holds about 2300 segments of 1024 samples,
    and a few hundred already give a coherence estimate well within the QC
    requirement. Above `max_segments` the segments are spread evenly over
    the window instead of taken back to back, keeping the time coverage.
    """
    hop = nperseg // 2
    starts = np.arange(0, window_n - nperseg + 1, hop, dtype=int)
    if starts.size > max_segments:
        pick = np.linspace(0, starts.size - 1, max_segments).round().astype(int)
        starts = starts[pick]
    return starts


@lru_cache(maxsize=16)
def _hann(nperseg: int) -> np.ndarray:
    """Return the periodic Hann taper (scipy's "hann") as a cached, read-only float32 array."""
    win = get_window("hann", nperseg).astype("float32")
    win.flags.writeable = False
    return win


def density_scale(fs: float, nperseg: int) -> tuple[float, np.ndarray]:
    """Return the factors that turn |FFT|^2 of a Hann-tapered segment into a power density.

    Matches ``scipy.signal.welch(..., scaling="density")``: every bin except
    DC and, for even `nperseg`, Nyquist is doubled for the one-sided
    spectrum.

    Args:
        fs (float): Sample rate in Hz.
        nperseg (int): Segment length in samples.

    Returns:
        tuple: ``(scale, doubling)``, a float and a per-rfft-bin array.
    """
    win = _hann(nperseg)
    scale = 1.0 / (fs * float(np.sum(win.astype("float64") ** 2)))
    dbl = np.full(nperseg // 2 + 1, 2.0)
    dbl[0] = 1.0
    if nperseg % 2 == 0:
        dbl[-1] = 1.0
    return scale, dbl


def segment_ffts(x: np.ndarray, offsets: np.ndarray, nperseg: int) -> np.ndarray:
    """Return the rfft of `nperseg`-point segments of `x`, demeaned and Hann-tapered.

    This is the segment transform shared by `window_spectra` and
    `mtproc.crosspower`.

    Args:
        x (np.ndarray): Samples.
        offsets (np.ndarray): Segment start offsets.
        nperseg (int): Segment length in samples.

    Returns:
        np.ndarray: Complex array indexed [segment, bin].
    """
    view = np.lib.stride_tricks.sliding_window_view(x, nperseg)[offsets]
    segs = (view - view.mean(axis=1, keepdims=True)) * _hann(nperseg)
    return np.fft.rfft(segs, axis=1)


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
    counts: bool = False,
):
    """Compute Welch auto- and cross-spectra per window for every channel and pair in one pass.

    The segment FFTs are taken once per channel per window and shared by
    every pair, which is faster than calling `scipy.signal.coherence` per
    pair. Scaling matches ``scipy.signal.welch(..., scaling="density")``.
    The DC bin is kept here and dropped by the binning. A window keeping
    fewer than max(`MIN_WINDOWS`, half) of its segments after gap removal
    is left NaN.

    Args:
        arrays (dict): Channel to samples.
        gaps (list of tuple): [start, stop) sample ranges with no data.
        fs (float): Sample rate in Hz.
        win_s (float): Window length in s.
        step_s (float): Window step in s.
        nperseg (int): Segment length in samples.
        channels (tuple of str): Channels for auto-spectra.
        pairs (tuple of tuple): Channel pairs for cross-spectra.
        max_segments (int): Most segments per window.
        counts (bool): Also return the segment count per window.

    Returns:
        tuple: ``(t, freqs, psd, csd)``: window centres in s from sample 0,
        one-sided frequencies, ``{channel: Sxx[window, freq]}`` and
        ``{pair: Sxy[window, freq]}`` (complex). With `counts`, a fifth item
        holds the number of segments each window averaged (0 for a window
        dropped for its gaps), which `mtproc.crosspower` reports as a
        chunk's STFT window count.
    """
    n = min(a.size for a in arrays.values())
    w = int(round(win_s * fs))
    st = max(1, int(round(step_s * fs)))
    starts = np.arange(0, max(1, n - w + 1), st, dtype=int)
    seg0 = _segment_starts(w, nperseg, max_segments)
    scale, dbl = density_scale(fs, nperseg)
    n_freq = nperseg // 2 + 1
    freqs = np.fft.rfftfreq(nperseg, 1.0 / fs)

    psd = {c: np.full((starts.size, n_freq), np.nan) for c in channels}
    csd = {p: np.full((starts.size, n_freq), np.nan, dtype="complex128") for p in pairs}
    n_used = np.zeros(starts.size, dtype=int)
    n_bad = 0
    for k, s in enumerate(starts):
        good = np.ones(seg0.size, dtype=bool)
        for g0, g1 in gaps:
            if g1 <= s or g0 >= s + w:
                continue
            good &= (s + seg0 + nperseg <= g0) | (s + seg0 >= g1)
        if good.sum() < max(MIN_WINDOWS, 0.5 * seg0.size):
            n_bad += 1
            continue
        offs = seg0[good]
        n_used[k] = offs.size
        ffts = {c: segment_ffts(arrays[c][s : s + w], offs, nperseg) for c in channels}
        for c in channels:
            psd[c][k] = dbl * scale * np.mean(np.abs(ffts[c]) ** 2, axis=0)
        for a, b in pairs:
            # conj on the first channel, as scipy.signal.csd(x, y) has it
            csd[(a, b)][k] = dbl * scale * np.mean(np.conj(ffts[a]) * ffts[b], axis=0)
    if n_bad:
        logger.info(f"  {n_bad}/{starts.size} window(s) dropped (gaps)")
    if counts:
        return (starts + w / 2.0) / fs, freqs, psd, csd, n_used
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


def decimation_levels(
    arrays: dict[str, np.ndarray],
    gaps: list[tuple[int, int]],
    sample_rate: float,
    n_levels: int,
    channels: tuple[str, ...],
    factor: int = LEVEL_FACTOR,
):
    """Walk `n_levels` decimation levels down, yielding each level in turn.

    This is the cascade's decimation, used by `cascade` for the QC ladder
    and by `mtproc.crosspower` for a chunk's impedances. While a level is
    yielded, ``arrays[c]`` holds that level's float32 copy of each channel
    (level 0 is the input itself). `arrays` is consumed: gap samples are
    zeroed first (the arrays are offset-removed, so zero is the channel
    mean, and a FIR would otherwise smear one NaN across the whole record),
    any NaN outside the gaps is zeroed with a warning, and each level
    replaces the one before it. The gaps are carried down and dilated by
    `GAP_DILATE` output samples per level to cover the filter's smear.
    Level L's sample j is the input's sample j * factor**L.

    Args:
        arrays (dict): Channel to samples, modified in place.
        gaps (list of tuple): [start, stop) sample ranges with no data.
        sample_rate (float): Input sample rate in Hz.
        n_levels (int): Number of levels.
        channels (tuple of str): Channels to decimate.
        factor (int): Decimation factor between levels.

    Yields:
        tuple: ``(level, fs, level_gaps)``.
    """
    for a, b in gaps:
        for c in channels:
            arrays[c][a:b] = 0.0
    for c in channels:
        n_nan = int(np.isnan(arrays[c]).sum())
        if n_nan:
            logger.warning(f"{c}: {n_nan} NaN outside the run gaps -- zeroed")
            np.nan_to_num(arrays[c], copy=False)
    fs = float(sample_rate)
    level_gaps = list(gaps)
    for level in range(int(n_levels)):
        if level > 0:
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
        yield level, fs, level_gaps


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
    """Walk the ladder once and return coherence and power maps per level.

    `arrays` is consumed: each level's entries are replaced by the
    decimated copy, so the full-rate arrays are released once level 0 is
    done and the peak footprint is one level plus a quarter. Gap handling
    follows `decimation_levels`.

    Args:
        arrays (dict): Channel to samples, modified in place.
        gaps (list of tuple): [start, stop) sample ranges with no data.
        sample_rate (float): Input sample rate in Hz.
        plan (pd.DataFrame): Ladder from `levels_plan`.
        channels (tuple of str): Channels for power maps.
        pairs (tuple of tuple): Channel pairs for coherence maps.
        per_decade (int): Log-period bins per decade.
        max_segments (int): Most Welch segments per window.
        factor (int): Decimation factor between levels.

    Returns:
        tuple: ``({pair: [(t_s, periods, coh), ...]}, {channel: [(t_s,
        periods, psd), ...]}, {channel: (freqs, median level-0 PSD)})``. The
        first two hold one entry per level, which `levels_to_grid` and
        `band_from_levels` stitch; the third is the base level at full
        frequency resolution, for `line_excess`.
    """
    coh_levels = {p: [] for p in pairs}
    pow_levels = {c: [] for c in channels}
    base_psd: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    levels = decimation_levels(arrays, gaps, sample_rate, len(plan), channels, factor)
    for row, (_level, fs, level_gaps) in zip(plan.itertuples(), levels):
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
            # wide at 50 Hz and cannot show a mains line (see `line_excess`)
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
    """Return the dB by which the spectrum at `f0` stands above the floor either side of it.

    The floor is the median density over [f0 - half_width, f0 + half_width]
    excluding +/-`guard` Hz around the line. It is reported per channel
    because log-period binning hides a narrow line: at 8 bins per decade the
    bin holding 50 Hz is about 15 Hz wide, so a line standing 2 dB above the
    floor in a 1 Hz resolution bandwidth is diluted to about 0.2 dB and does
    not show in the spectrogram at any colour scale.

    Args:
        freqs (np.ndarray): Frequencies in Hz.
        psd (np.ndarray): Power density at `freqs`.
        f0 (float): Line frequency in Hz.
        half_width (float): Half-width of the floor window in Hz.
        guard (float): Half-width excluded around the line in Hz.

    Returns:
        float: Excess in dB, NaN when the window holds no floor bins.
    """
    near = (freqs >= f0 - half_width) & (freqs <= f0 + half_width)
    floor_m = near & (np.abs(freqs - f0) > guard)
    if not floor_m.any() or not near.any():
        return float("nan")
    k = int(np.argmin(np.abs(freqs - f0)))
    with np.errstate(divide="ignore", invalid="ignore"):
        return float(10.0 * np.log10(psd[k] / np.nanmedian(psd[floor_m])))


# ---------------------------------------------------------------- the PSD ladder

PSD_NPERSEG = 2**16
PSD_FACTOR = 10
PSD_STAGES = 4
PSD_MIN_SEGMENTS = 4


def psd_ladder(
    arrays: dict[str, np.ndarray],
    gaps: list[tuple[int, int]],
    fs0: float,
    channels,
    nperseg: int = PSD_NPERSEG,
    factor: int = PSD_FACTOR,
    n_stages: int = PSD_STAGES,
    min_segments: int = PSD_MIN_SEGMENTS,
):
    """Compute the whole-spectrum decimation ladder of `scripts/psd_qc.py`.

    Also used by the GUI segment QC on a 1-3 h stretch. Stage 0 is at the
    native rate and each later stage at a further `/factor`, with plain
    `scipy.signal.welch` at the fixed `nperseg` over the whole spectrum
    available at that rate; the script draws each stage's assigned decade
    (see its module docstring for the table).

    A stage is computed while its array holds at least
    ``min_segments * nperseg`` samples, and the ladder stops otherwise, so a
    short segment gets the stages its length supports and scipy never
    shrinks `nperseg` for a stage. At 1000 Hz with the defaults
    (65536-point segments, four of them) the thresholds are

        stage  fs       needs      samples at that rate
        0      1000 Hz  262 s      4 x 65536
        1      100 Hz   43.7 min   4 x 65536
        2      10 Hz    7.28 h     4 x 65536
        3      1 Hz     72.8 h     4 x 65536

    so a 1 h segment (3.6 M samples) yields stages 0 and 1, and so does a
    3 h one (10.8 M), since stage 2 needs 7.3 h. Any record shorter than
    72.8 h is also short of the default at stage 3, so `scripts/psd_qc.py`
    passes ``min_segments=1`` (one whole segment, 18.2 h at 1 Hz) to keep
    all four stages.

    `arrays` is consumed: each channel is cast to float64 in place, the
    float32 it replaces being released channel by channel, then replaced by
    its decimated copy at every later stage, as in `cascade`, so the peak
    footprint is one stage's worth of channels. Gap samples are zeroed
    first (the arrays are offset-removed by `load_station`, so zero is the
    channel mean), and any NaN outside the declared gaps is zeroed with a
    warning.

    Args:
        arrays (dict): Channel to samples, modified in place.
        gaps (list of tuple): [start, stop) sample ranges with no data.
        fs0 (float): Native sample rate in Hz.
        channels (iterable of str): Channels to use.
        nperseg (int): Welch segment length in samples.
        factor (int): Decimation factor between stages.
        n_stages (int): Most stages.
        min_segments (int): Fewest segment lengths a stage needs.

    Returns:
        list of tuple: ``(fs, freqs, {channel: psd})`` per stage.
    """
    for a, b in gaps:
        for c in channels:
            arrays[c][a:b] = 0.0
    for c in channels:
        n_nan = int(np.isnan(arrays[c]).sum())
        if n_nan:
            logger.warning(f"{c}: {n_nan} NaN outside the run gaps -- zeroed")
            np.nan_to_num(arrays[c], copy=False)
        arrays[c] = arrays[c].astype("float64")

    fs = float(fs0)
    stages = []
    for level in range(n_stages):
        n_level = arrays[channels[0]].size
        if n_level < min_segments * nperseg:
            logger.info(
                f"stage {level}: {n_level} samples at {fs:g} Hz is under {min_segments} x "
                f"{nperseg} -- ladder stops below it"
            )
            break
        t0 = time.time()
        freqs, row = None, {}
        for c in channels:
            freqs, row[c] = welch(
                arrays[c], fs=fs, window="hann", nperseg=nperseg, detrend="constant", scaling="density"
            )
        stages.append((fs, freqs, row))
        logger.info(
            f"stage {level}: {fs:g} Hz, {arrays[channels[0]].size} samples, "
            f"welch {time.time() - t0:.1f} s"
        )
        if level < n_stages - 1:
            t0 = time.time()
            for c in channels:
                arrays[c] = decimate(arrays[c], factor, ftype="fir", zero_phase=True)
            fs /= factor
            logger.info(f"  decimate x{factor} -> {fs:g} Hz: {time.time() - t0:.1f} s")
    return stages


def power_db(power: np.ndarray) -> np.ndarray:
    """Return 10 log10 of a power density, NaN where it is zero or missing."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(power)


# ---------------------------------------------------------------- stitching levels


def levels_to_grid(levels, t_base):
    """Stitch every level onto the base time grid (nearest window) as one image.

    Returns:
        tuple: ``(periods, image)`` with periods sorted ascending.
    """
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
    """Return one band line on the base time grid, averaged over every level reaching the band.

    Args:
        levels (list of tuple): One ``(t_s, periods, image)`` per level, as
            `cascade` returns them: window times in s, bin periods in s,
            and the (windows, bins) map.
        lo_s (float): Shortest period of the band in s.
        hi_s (float): Longest period of the band in s.
        t_base (np.ndarray): Times of the base grid, in s; each level is
            read at its first window at or after each time (its last
            window beyond the end).

    Returns:
        np.ndarray: The band's mean over its bins on `t_base`, averaged
        over the levels with a finite value (NaN ignored); all NaN when no
        level reaches the band.
    """
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
    """Return the centred running median along time (axis 0), ignoring NaN."""
    if n_windows <= 1:
        return a
    return (
        pd.DataFrame(a).rolling(int(n_windows), center=True, min_periods=1).median().to_numpy()
    )


# ---------------------------------------------------------------- time axis


def iso(t: pd.Timestamp) -> str:
    """Format a time as 'YYYY-MM-DD HH:MM'."""
    return pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")


def day_axis(t0: pd.Timestamp, duration_s: float):
    """Return time-axis ticks snapped to round UTC times.

    The AusLAMP version ticks whole days, which suits a record of weeks. A
    broadband deployment lasts about 2 days, so the step is chosen from
    quarter-hours up to 20 days for about 8 ticks, and the label carries the
    time of day whenever the step is under a day.

    Returns:
        tuple: ``(ticks, labels)``: positions in days from t0 and label text.
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
    """Return the (mean, min, max) of each block of m samples, dropping the trailing partial block."""
    n = x.size // m * m
    a = x[:n].reshape(-1, m)
    if np.isnan(a).any():
        # a block falling wholly inside a gap is all-NaN and comes back NaN,
        # so the figure draws a hole rather than a joined line
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(a, axis=1), np.nanmin(a, axis=1), np.nanmax(a, axis=1)
    return a.mean(axis=1, dtype="float64"), a.min(axis=1), a.max(axis=1)


# ---------------------------------------------------------------- narrow spectral lines


def narrow_lines(
    x: np.ndarray,
    fs: float,
    fmin: float,
    fmax: float,
    resolution_hz: float = 0.05,
    guard_hz: float = 2.0,
    min_db: float = 6.0,
    mains_hz: float = 50.0,
) -> list[tuple[float, float, bool]]:
    """Find narrow spectral lines in `x` between `fmin` and `fmax` Hz.

    Used to declare notch-filter `extra` lines by hand
    (`scripts/line_scan.py`). The grid-wide interharmonic combs around a
    broadband survey's mains hum sit a couple of Hz either side of 50 Hz
    and its harmonics, so the resolution must separate, for example, 34.3
    and 37.4 Hz, which a log-period bin (`cascade`'s `_log_bins`) or the
    fixed 2**16-point segment of `psd_ladder` cannot at a useful record
    length.

    The PSD is a plain `scipy.signal.welch` (Hann window, 50 % overlap, mean
    removed per segment with ``detrend="constant"``) at
    ``nperseg = round(fs / resolution_hz)``, in dB. Each candidate bin's
    local floor is the median of the dB spectrum within +/-`guard_hz`,
    excluding the +/-0.25 Hz around the bin itself so the line's peak and
    the start of its skirt stay out of its floor. A line is a local maximum
    of (dB - floor) that clears `min_db`; of two candidates within 0.5 Hz
    only the higher-excess one is kept, so a Hz-scale feature is reported
    once. `is_mains_harmonic` is True when the line sits within 0.6 Hz of a
    multiple of `mains_hz`.

    The result describes `x` as given. For per-hour behaviour over a longer
    record, call it once per hour as `scripts/line_scan.py` does; the whole
    record averages an intermittent or drifting line toward the noise floor.
    Frequency resolution is ``fs / nperseg`` (about `resolution_hz`,
    rounded to the nearest bin). A line more than about twice that
    resolution wide, or one drifting across more than about a bin within
    `x`, spreads over several bins; the smear raises each bin's floor once
    it reaches past the +/-0.25 Hz exclusion, so `excess_db` understates
    the line, and a wandering line may be reported as several weak adjacent
    lines or not at all.

    Args:
        x (np.ndarray): Samples.
        fs (float): Sample rate in Hz.
        fmin (float): Lowest frequency searched in Hz.
        fmax (float): Highest frequency searched in Hz.
        resolution_hz (float): Target frequency resolution in Hz.
        guard_hz (float): Half-width of the floor window in Hz.
        min_db (float): Smallest excess reported in dB.
        mains_hz (float): Mains frequency in Hz.

    Returns:
        list of tuple: ``(frequency_hz, excess_db, is_mains_harmonic)``,
        sorted by frequency.
    """
    x = np.asarray(x, dtype="float64")
    nperseg = int(round(fs / resolution_hz))
    nperseg = max(8, min(nperseg, x.size))
    freqs, psd = welch(
        x, fs=fs, window="hann", nperseg=nperseg, noverlap=nperseg // 2,
        detrend="constant", scaling="density",
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        psd_db = 10.0 * np.log10(psd)

    df = float(freqs[1] - freqs[0]) if freqs.size > 1 else fs / nperseg
    guard_bins = max(1, int(round(guard_hz / df)))
    excl_bins = max(0, int(round(0.25 / df)))

    # candidate bins are [fmin, fmax], widened by one bin either side so the
    # local-maximum test at the band edges has a real neighbour to compare
    lo = max(1, int(np.searchsorted(freqs, fmin, side="left")) - 1)
    hi = min(freqs.size - 2, int(np.searchsorted(freqs, fmax, side="right")))
    if hi <= lo:
        return []
    ext = np.arange(lo, hi + 1)

    pad = np.pad(psd_db, guard_bins, mode="constant", constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(pad, 2 * guard_bins + 1)[ext]
    rel = np.arange(-guard_bins, guard_bins + 1)
    excl_mask = np.abs(rel) <= excl_bins
    masked = windows.copy()
    masked[:, excl_mask] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slice possible at the spectrum edge
        floor_ext = np.nanmedian(masked, axis=1)
    excess_ext = psd_db[ext] - floor_ext

    # local maxima of (dB - floor) among the interior bins (ext's first/last
    # bin are the extra neighbours added only for this comparison)
    is_max = (excess_ext[1:-1] > excess_ext[:-2]) & (excess_ext[1:-1] > excess_ext[2:])
    inner = ext[1:-1]
    excess_inner = excess_ext[1:-1]
    ok = is_max & (excess_inner >= min_db) & np.isfinite(excess_inner)
    cand_idx = inner[ok]
    if cand_idx.size == 0:
        return []
    cand_f = freqs[cand_idx]
    cand_excess = excess_inner[ok]
    order = np.argsort(cand_f)
    cand_f, cand_excess = cand_f[order], cand_excess[order]

    kept_f: list[float] = []
    kept_excess: list[float] = []
    for f, e in zip(cand_f.tolist(), cand_excess.tolist()):
        if kept_f and f - kept_f[-1] < 0.5:
            if e > kept_excess[-1]:
                kept_f[-1], kept_excess[-1] = f, e
            continue
        kept_f.append(f)
        kept_excess.append(e)

    lines = []
    for f, e in zip(kept_f, kept_excess):
        nearest = round(f / mains_hz) * mains_hz
        lines.append((f, e, bool(abs(f - nearest) <= 0.6)))
    return lines
