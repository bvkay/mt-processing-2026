# -*- coding: utf-8 -*-
"""
Remote-reference impedances of one site over time

Computes, per band and per stretch of time, the remote-reference impedance
of that stretch alone, Z = <E R*> <H R*>^-1, with the coherence of E with
the E that Z predicts, the number of STFT windows averaged and the
stretch's mean |H| and |E|. The bands, their decimation levels and windows
are those of the survey's band scheme, the dict
`crust.bands.build_band_scheme` returns. The GUI's Cross-powers tab draws
the estimates against time and in the (log10 |Z|, phase) plane, where a
stretch that sits apart from the others can be masked (`crust.masks`).

`compute_windows` reads the two archives once and keeps the band sums of
the STFT windows in a `WindowStore`; `bin_windows` groups them into chunks
and display groups from the store alone, so a new chunk length or a window
inside the stored one is regrouped at once. `chunk_impedances` runs the two
in one call, `band_view` reads one band of a result on its own level's
grid, `masked_chunks` marks the groups a list of masks touches,
`level_multiples` gives the display group size per level and
`stack_impedance` stacks, per band, every kept window the masks leave. The
module is checked by `tests/crosspower_unit.py` and by criterion (34) of
`tests/gui_smoke.py`.

How it works

Base samples are counted from the UTC epoch, and level L of the band scheme
runs at fs / factor**L. Its half-overlapping STFT windows form one global
grid: window w starts at base sample w * hop_L, hop_L being half a window
in base samples, whatever the read, chunk length or range. The grid
windows of a range are those lying inside it; one touching a gap (samples
no run of either station covers) counts on the grid and is dropped.

`compute_windows` reads the record in blocks of `CHUNK_S` with a margin
either side, aligned so that every block's decimated samples lie on the
global grid, and `workers` threads take blocks side by side. A block
removes its channel medians, zeroes its gaps and decimates through the
levels (`crust.timefreq.decimation_levels`); each channel's spectra are
divided by the response of its MTH5 filter chain, as aurora calibrates
them, so Z is in (mV/km)/nT, and a band holds the harmonics
f_lo <= f < f_hi. A level whose windows fit in `BIN_S` is a binned level:
its kept windows are summed into minute bins by window centre, as the band
sums of <E R*>, <H R*>, <E H*>, <H H*> and |E|^2 with the counts of kept
and grid windows. The deeper stream levels are decimated from one low-rate
stream stitched from the blocks' samples at the deepest binned level, its
two ends treated as gaps, and keep the same sums per window.

`bin_windows` groups the sums into chunks of a base length, from the minute
at or before the range's start, and per level into display groups of m_L
chunks, m_L the smallest count holding `MIN_DOF` degrees of freedom and
`MIN_WINDOWS` windows (`level_multiples`). Masks act per window on the
stream levels and per minute bin on the binned levels. `stack_impedance`
sums every kept window the masks leave into one estimate per band, the
same for any chunk length, with the error of a delete-one-group jackknife
over the display groups, each weighted by its kept window count (Busing,
Meijer & van der Leeden 1999). These are plain remote-reference estimates
with scipy's decimation filter, where aurora weights windows robustly, so
the chunks scatter about the processed EDI.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5

from .masks import applies, normalise, windows_in_mask
from .timefreq import MIN_WINDOWS, _real_runs, decimation_levels, density_scale, segment_ffts

CHUNK_S = 600.0  # the default chunk, and the read block
CHUNKS_S = (600.0, 300.0, 120.0, 60.0)  # the chunk lengths the tab offers
BIN_S = 60.0  # the length of the bins the shallow levels are summed into
MIN_DOF = 32  # degrees of freedom (windows x band harmonics) a full display group holds
MIN_GROUPS = 5  # the jackknife is reported from this many display groups on
MARGIN_S = 64.0  # read either side of a block (widened where a binned window plus the FIR transient exceed it)
GRID_TOL = 1e-3  # samples a run's start may sit off the origin's grid before it is logged
LOCAL_ROLES = ("ex", "ey", "hx", "hy")
REMOTE_ROLES = ("hx", "hy")
R = "r_"  # the remote's channels in a block's arrays
CHANNELS = LOCAL_ROLES + tuple(R + r for r in REMOTE_ROLES)
ORIGIN = pd.Timestamp(0, tz="UTC")  # base sample 0
SUMS = ("er", "hr", "eh", "hh", "ee")  # the band sums a store keeps, per window or per minute bin
_NS = 10**9


def _ns(t) -> int:
    """Return a time (text or Timestamp; naive is UTC) as integer ns since the epoch."""
    ts = pd.Timestamp(str(t)) if not isinstance(t, pd.Timestamp) else t
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)


def _roles(names, wanted) -> dict[str, str]:
    """Map the roles hx, hy, ex, ey to the archive's channel names.

    The first two magnetics in name order (names starting b or h, then x or
    y) play hx and hy, the first two electrics (names starting e) ex and ey:
    a LEMI-423's own names, or a LEMI-424's bx, by, e1, e2. The rule is the
    one of `crust.gui.channels.roles`.

    Args:
        names: The archive's channel names.
        wanted: The roles to return.

    Returns:
        dict: {role: channel name} for each role in `wanted`.

    Raises:
        ValueError: When no channel plays one of the wanted roles.
    """
    mags = sorted(n for n in names if n[:1].lower() in ("h", "b") and n[1:2].lower() in ("x", "y"))
    elecs = sorted(n for n in names if n[:1].lower() == "e")
    parts = dict(zip(("hx", "hy"), mags)) | dict(zip(("ex", "ey"), elecs))
    missing = [w for w in wanted if w not in parts]
    if missing:
        raise ValueError(f"no channel plays {missing} among {sorted(names)}")
    return {w: parts[w] for w in wanted}


@dataclass
class _Run:
    """One run of an archive: its id, its first sample's time (ns since the epoch) and its length in samples."""

    run_id: str
    start_ns: int
    n: int


@dataclass
class _Station:
    """One station's archive: its runs, which channel plays which role, and its calibration."""

    path: Path
    station: str
    group: str  # the station's HDF5 group path
    fs: float
    runs: list[_Run]
    names: dict[str, str]  # role -> the archive's channel name
    chains: dict[str, tuple] = field(default_factory=dict)  # role -> (channel_response, filters to remove)

    def response(self, role: str, freqs: np.ndarray) -> np.ndarray:
        """Return the complex response aurora divides the spectrum of channel `role` by, at `freqs` (Hz)."""
        response, filters = self.chains[role]
        if not filters:
            return np.ones(freqs.size, dtype=complex)
        return np.asarray(response.complex_response(freqs, filters_list=filters), dtype=complex)


def _layout(h5_path, station: str, roles) -> _Station:
    """Read a station's run layout and filter chains from its MTH5 archive.

    Opens the archive read-only and closes it before returning. Each role's
    filter chain is the first run's, with the filters aurora removes
    (`calibrate_stft_obj`): the applied filters other than decimation and
    delay.

    Args:
        h5_path: The MTH5 archive.
        station (str): The station.
        roles: The roles to map (`_roles`).

    Returns:
        _Station: Its runs, channel names per role, sample rate and filter chains.

    Raises:
        ValueError: When the station is not in the archive or has no run with
            data, or when its runs differ in sample rate.
    """
    h5_path = Path(h5_path)
    with h5py.File(h5_path, "r") as f:
        surveys = list(f["Experiment/Surveys"]) if "Experiment/Surveys" in f else []
        survey = next((s for s in surveys if station in f[f"Experiment/Surveys/{s}/Stations"]), None)
    if survey is None:
        raise ValueError(f"{station}: not in {h5_path}")
    m = MTH5()
    m.open_mth5(h5_path, mode="r")
    try:
        st = m.get_station(station, survey=survey)
        run_list = _real_runs(st)
        if not run_list:
            raise ValueError(f"{station}: no runs with data in {h5_path}")
        names = _roles(st.get_run(run_list[0][0]).groups_list, roles)
        first = names[roles[0]]
        runs, chains, fs = [], {}, None
        for run_id, _start, _end in run_list:
            ch = m.get_channel(station, run_id, first, survey)
            rate = float(ch.metadata.sample_rate)
            if fs is None:
                fs = rate
            elif abs(rate - fs) > 1e-9 * fs:
                raise ValueError(f"{station} {run_id}: {rate:g} Hz, the first run is {fs:g} Hz")
            runs.append(_Run(run_id, _ns(ch.metadata.time_period.start), int(ch.hdf5_dataset.shape[0])))
        for role, name in names.items():
            # the first run's chain, removed the way aurora removes it (calibrate_stft_obj)
            ch = m.get_channel(station, run_list[0][0], name, survey)
            response = ch.channel_response
            idx = response.get_indices_of_filters_to_remove(include_decimation=False, include_delay=False)
            idx = [i for i in idx if ch.metadata.filters[i].applied]
            chains[role] = (response, [response.filters_list[i] for i in idx])
        group = st.hdf5_group.name
    finally:
        m.close_mth5()
    return _Station(h5_path, station, group, fs, runs, names, chains)


def _read(st: _Station, handle, role: str, t0_ns: int, n: int, warned: set):
    """Read one channel over n samples from t0_ns on the origin's grid.

    Places each run by integer arithmetic from its start: the run's sample 0
    lands at index round((run start - t0) * fs) of the chunk, the nearest
    sample when a run sits off the grid (logged once per run past
    `GRID_TOL`).

    Args:
        st (_Station): The station.
        handle: The open h5py file of its archive.
        role (str): The channel's role.
        t0_ns (int): The first sample's time, ns since the epoch.
        n (int): Samples to read.
        warned (set): (station, run) pairs already logged as off the grid; updated.

    Returns:
        tuple: (float64 counts, zero where no run covers them, or None when no
        run meets the span; the [a, b) spans the runs cover).
    """
    group = handle[st.group]
    raw, covered = None, []
    for run in st.runs:
        pos = (run.start_ns - t0_ns) * st.fs / 1e9
        i0 = int(round(pos))
        if abs(pos - i0) > GRID_TOL and (st.station, run.run_id) not in warned:
            warned.add((st.station, run.run_id))
            logger.warning(f"{st.station} {run.run_id}: run start {pos - i0:+.3f} samples off the sample grid, "
                           f"placed at the nearest sample")
        a, b = max(0, i0), min(n, i0 + run.n)
        if b <= a:
            continue
        dataset = group[run.run_id][st.names[role]]
        if raw is None:
            raw = np.zeros(n, dtype="float64")
        raw[a:b] = dataset[a - i0 : b - i0]
        covered.append((a, b))
    return raw, covered


def _uncovered(covered, n: int) -> list[tuple[int, int]]:
    """Return the [a, b) spans of [0, n) that the `covered` spans leave out."""
    out, cursor = [], 0
    for a, b in sorted(covered):
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < n:
        out.append((cursor, n))
    return out


def _merge(spans) -> list[tuple[int, int]]:
    """Return `spans` sorted, with the spans that overlap or touch merged."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def band_table(band_scheme: dict):
    """Return the level and edges of every band of a band scheme, shortest period first.

    A band's period is 1 / sqrt(f_lo f_hi), its geometric centre, as aurora
    labels it in the EDI.

    Args:
        band_scheme (dict): The survey's band scheme (see crust.bands).

    Returns:
        tuple: (level, f_lo, f_hi) numpy arrays, one entry per band.
    """
    rows = [(int(level), float(lo), float(hi))
            for level, bands in band_scheme["band_edges"].items() for lo, hi in np.asarray(bands)]
    rows.sort(key=lambda r: -math.sqrt(r[1] * r[2]))
    return (np.array([r[0] for r in rows], dtype=int), np.array([r[1] for r in rows]),
            np.array([r[2] for r in rows]))


def levels_in_chunk(band_scheme: dict, n_samples: int) -> int:
    """Return how many of the scheme's levels hold `MIN_WINDOWS` half-overlapping STFT windows.

    `level_multiples` gives the display groups `bin_windows` uses.

    Args:
        band_scheme (dict): The survey's band scheme (see crust.bands).
        n_samples (int): The span, in samples at the base rate.

    Returns:
        int: The number of levels, counted from level 0.
    """
    windows = [int(w) for w in band_scheme["num_samples_window"]]
    factors = list(band_scheme["decimation_factors"])
    factor = factors[1] if len(factors) > 1 else 4
    count = 0
    while count < len(windows) and 0.5 * (MIN_WINDOWS + 1) * windows[count] * factor ** count <= n_samples:
        count += 1
    return count



class _Clock:
    """Convert between base-sample indices on the origin's grid and UTC ns.

    Sample n lies n / fs s after 1970-01-01 UTC; the rate is held as an exact
    fraction.
    """

    def __init__(self, fs: float):
        self.fs = float(fs)
        self._rate = Fraction(self.fs).limit_denominator(10**6)

    def ceil(self, ns: int) -> int:
        """The first sample at or after `ns` (exact)."""
        return math.ceil(Fraction(int(ns)) * self._rate / _NS)

    def ns(self, n: int) -> int:
        """Sample n's time, ns since the epoch (exact)."""
        return round(Fraction(int(n)) * _NS / self._rate)

    def ns_array(self, n, ref: int) -> np.ndarray:
        """int64 ns of the samples `n`, exact at `ref` and to the ns within a record of it."""
        steps = (np.asarray(n, dtype=np.int64) - int(ref)).astype(np.float64)
        return self.ns(ref) + np.round(steps * (_NS / self.fs)).astype(np.int64)

    def times(self, n, ref: int) -> pd.DatetimeIndex:
        """Return the samples `n` as a UTC DatetimeIndex (`ns_array`)."""
        return pd.DatetimeIndex(pd.to_datetime(self.ns_array(n, ref), unit="ns", utc=True))


def _cdiv(x, h):
    """Ceiling division, integers or int64 arrays."""
    return -(-x // h)


@dataclass
class _Level:
    """One decimation level of the band scheme: its STFT grid, its bands and their calibration."""

    level: int
    binned: bool  # window <= BIN_S: stored as minute sums
    win: int  # STFT points
    scale: int  # base samples per level sample (factor ** level)
    bands: np.ndarray  # the level's bands, as indices into band_table's order
    n_harm: np.ndarray  # rfft harmonics in each of those bands
    cols: np.ndarray  # the rfft bins lying in some band of the level
    weights: np.ndarray  # [cols, bands]: band membership times the density scaling
    inv_resp: dict = field(default_factory=dict)  # channel -> 1 / its response at `cols`

    @property
    def win_b(self) -> int:
        """The window length in base samples."""
        return self.win * self.scale

    @property
    def hop_b(self) -> int:
        """The hop, half a window, in base samples."""
        return self.win // 2 * self.scale


def _factor(band_scheme: dict) -> int:
    """Return the decimation factor of a scheme whose factors are 1 followed by one repeated factor.

    Raises:
        ValueError: For any other list of factors.
    """
    factors = list(band_scheme["decimation_factors"])
    factor = factors[1] if len(factors) > 1 else 4
    if factors[0] != 1 or any(f != factor for f in factors[1:]):
        raise ValueError(f"decimation factors {factors}: a first 1 then one repeated factor is expected")
    return int(factor)


def _plan_levels(band_scheme: dict, fs: float, local: _Station | None = None,
                 remote: _Station | None = None) -> tuple[int, list[_Level]]:
    """Plan every decimation level of a band scheme.

    Args:
        band_scheme (dict): The survey's band scheme (see crust.bands).
        fs (float): The base sample rate, Hz.
        local (_Station | None): The local station; given with `remote`, each
            level holds the inverse channel responses at its harmonics.
        remote (_Station | None): The remote station.

    Returns:
        tuple: (factor, one `_Level` per level).

    Raises:
        ValueError: For an odd window, or a binned level deeper than a
            stream level.
    """
    factor = _factor(band_scheme)
    level_of, lo, hi = band_table(band_scheme)
    out = []
    for level, win in enumerate(int(w) for w in band_scheme["num_samples_window"]):
        if win % 2:
            raise ValueError(f"level {level}: an odd window ({win}) has no half-overlap grid")
        scale = factor**level
        freqs = np.fft.rfftfreq(win, scale / fs)
        bands = np.flatnonzero(level_of == level)
        member = np.array([(freqs >= lo[j]) & (freqs < hi[j]) for j in bands], dtype=bool).reshape(bands.size, -1)
        cols = np.flatnonzero(member.any(axis=0))
        density, dbl = density_scale(fs / scale, win)
        weights = member[:, cols].T * (dbl[cols] * density)[:, None]
        lv = _Level(level, win * scale <= BIN_S * fs * (1 + 1e-12), win, scale, bands,
                    member.sum(axis=1), cols, weights)
        if local is not None:
            f = freqs[cols]
            lv.inv_resp = {role: 1.0 / local.response(role, f) for role in LOCAL_ROLES}
            lv.inv_resp.update({R + role: 1.0 / remote.response(role, f) for role in REMOTE_ROLES})
        out.append(lv)
    binned = [lv.binned for lv in out]
    if any(binned[k + 1] and not binned[k] for k in range(len(binned) - 1)):
        raise ValueError("binned levels must be the shallowest levels (windows growing with the level)")
    return factor, out


def _multiple(n_harm: np.ndarray, hop_b: int, chunk_s: float, fs: float) -> int:
    """Return m_L, the base chunks per display group of one level.

    m_L is the smallest count for which a full group holds `MIN_WINDOWS` grid
    windows and `MIN_DOF` degrees of freedom (windows times the level's
    smallest band harmonic count).

    Args:
        n_harm (np.ndarray): Harmonics per band of the level.
        hop_b (int): The level's hop in base samples.
        chunk_s (float): The base chunk, s.
        fs (float): The base sample rate, Hz.

    Returns:
        int: m_L, at least 1.
    """
    per_chunk = chunk_s * fs / hop_b  # grid windows a base chunk holds
    harm = max(1, int(np.min(n_harm))) if np.size(n_harm) else 1
    return max(1, math.ceil(MIN_DOF / harm / per_chunk - 1e-9), math.ceil(MIN_WINDOWS / per_chunk - 1e-9))


def level_multiples(band_scheme: dict, sample_rate: float, chunk_s: float = CHUNK_S) -> list[int]:
    """Return m_L, the base chunks per display group, for every level of a band scheme.

    m_L is the smallest integer for which a full group of level L holds, on
    the grid, at least `MIN_WINDOWS` windows and at least `MIN_DOF` degrees of
    freedom (windows times the level's smallest band harmonic count) in every
    band. `bin_windows` shows level L on groups of m_L base chunks.

    Args:
        band_scheme (dict): The survey's band scheme (see crust.bands).
        sample_rate (float): The base sample rate, Hz.
        chunk_s (float): The base chunk, s.

    Returns:
        list of int: m_L per level.
    """
    _factor_, levels = _plan_levels(band_scheme, float(sample_rate))
    return [_multiple(lv.n_harm, lv.hop_b, chunk_s, float(sample_rate)) for lv in levels]


def _settle_n(factor: int, level: int) -> int:
    """Return the base samples from an array end that the decimation cascade's FIR transient reaches.

    `decimation_levels` uses scipy.signal.decimate(ftype="fir",
    zero_phase=True): 20 * factor + 1 taps, applied centred, so each level
    smears 10 * factor of its input samples in from an end. Summed over
    levels 1 to `level` in base samples, this is
    10 * factor * (factor**level - 1) / (factor - 1).

    Args:
        factor (int): The decimation factor.
        level (int): The deepest level.

    Returns:
        int: Base samples.
    """
    return sum(10 * factor * factor ** (step - 1) for step in range(1, level + 1))


def _margin_n(fs: float, levels: list, factor: int, q: int) -> int:
    """Return the base samples read either side of a block: `MARGIN_S`, widened where needed.

    A block owns the binned-level windows starting in its chunk proper, so
    its last one runs up to one window (win_b of the deepest binned level K)
    into the right margin, and the first starts at the left margin's end.
    Both lie on samples the cascade has settled when the margin is at least
    win_b + `_settle_n`(K); the margin is widened to that where `MARGIN_S` is
    shorter, at rates whose deepest binned window is close to `BIN_S`.

    Args:
        fs (float): The base sample rate, Hz.
        levels (list of _Level): The planned levels.
        factor (int): The decimation factor.
        q (int): The block alignment in base samples; the margin is a multiple of it.

    Returns:
        int: The margin in base samples.
    """
    need = int(round(MARGIN_S * fs))
    binned = [lv for lv in levels if lv.binned]
    if binned:
        need = max(need, binned[-1].win_b + _settle_n(factor, binned[-1].level))
    return _cdiv(need, q) * q


def _touches(idx: np.ndarray, win: int, gaps) -> np.ndarray:
    """Return, per window starting at `idx` (win samples long), True when a gap overlaps it."""
    bad = np.zeros(idx.size, dtype=bool)
    for a, b in gaps:
        bad |= (idx < b) & (idx + win > a)
    return bad


def _window_sums(arrays: dict, offsets: np.ndarray, lv: _Level, slab: int = 2048) -> list[np.ndarray]:
    """Return the band sums of the calibrated cross-powers of STFT windows at one level.

    The cross-powers are density-scaled as by `scipy.signal.csd` and summed
    over each band's harmonics. The windows are worked `slab` at a time, which
    bounds the memory the per-harmonic products take.

    Args:
        arrays (dict): The level's samples per channel.
        offsets (np.ndarray): The windows' first samples, in level samples.
        lv (_Level): The level.
        slab (int): Windows per step.

    Returns:
        list: [er, hr, eh, hh], each [n, bands, 2, 2] complex, and ee [n, bands, 2].
    """
    parts = []
    for i in range(0, offsets.size, slab):
        off = offsets[i: i + slab]
        spec = {c: segment_ffts(arrays[c], off, lv.win)[:, lv.cols].astype(np.complex128) * lv.inv_resp[c]
                for c in CHANNELS}
        e = np.stack([spec["ex"], spec["ey"]], axis=1)  # [n, 2, f]
        h = np.stack([spec["hx"], spec["hy"]], axis=1)
        r_conj = np.conj(np.stack([spec[R + "hx"], spec[R + "hy"]], axis=1))
        h_conj = np.conj(h)

        def band(a, b_conj):  # <a b*> per band: [n, 2, 2, f] @ [f, bands] -> [n, bands, 2, 2]
            return np.moveaxis((a[:, :, None, :] * b_conj[:, None, :, :]) @ lv.weights, 3, 1)

        ee = np.moveaxis((e.real**2 + e.imag**2) @ lv.weights, 2, 1)
        parts.append([band(e, r_conj), band(h, r_conj), band(e, h_conj), band(h, h_conj), ee])
    if len(parts) == 1:
        return parts[0]
    return [np.concatenate(p, axis=0) for p in zip(*parts)]


@dataclass
class _Job:
    """The inputs every block of one `compute_windows` call shares."""

    local: _Station
    remote: _Station
    handles: tuple
    clock: _Clock
    levels: list[_Level]
    factor: int
    binned_level: int  # K
    stream_level: int  # S = max(K, 0)
    lo_n: int
    hi_n: int
    b0: int  # the first block's chunk proper starts here (a multiple of factor**S)
    block_n: int
    margin_n: int
    n_blocks: int
    bin_n: int
    warned: set = field(default_factory=set)


def _block(job: _Job, k: int) -> dict:
    """Compute block k: its binned levels' window sums per minute bin, and its level-S stream piece and gaps.

    Args:
        job (_Job): The shared inputs.
        k (int): The block index.

    Returns:
        dict: ``k``; ``bins`` {level: (bin indices, the sums per bin, kept
        windows per bin)}; ``stream`` {channel: level-S samples with the
        block's median added back}, or None when a station has no sample in
        the block; ``stream_gaps`` (level-S [a, b) spans); ``n`` (level-S
        samples handed over).
    """
    q = job.factor**job.stream_level
    c0 = job.b0 + k * job.block_n
    c1 = c0 + job.block_n
    r0, n = c0 - job.margin_n, job.block_n + 2 * job.margin_n
    # the stream piece this block hands over, read-local base samples
    h0 = 0 if k == 0 else job.margin_n
    h1 = n if k == job.n_blocks - 1 else job.margin_n + job.block_n
    out = {"k": k, "bins": {}, "stream": None, "stream_gaps": [(0, (h1 - h0) // q)], "n": (h1 - h0) // q}
    t0_ns = job.clock.ns(r0)
    arrays, gaps, medians = {}, [], {}
    for st, handle, roles, prefix in ((job.local, job.handles[0], LOCAL_ROLES, ""),
                                      (job.remote, job.handles[1], REMOTE_ROLES, R)):
        for role in roles:
            raw, covered = _read(st, handle, role, t0_ns, n, job.warned)
            if raw is None:
                return out  # a station has no sample in this block: all of it is a gap
            gaps += _uncovered(covered, n)
            inside = np.concatenate([raw[a:b] for a, b in covered])
            medians[prefix + role] = float(np.median(inside))
            arrays[prefix + role] = (raw - medians[prefix + role]).astype("float32")
            del raw
    gaps = _merge(gaps)
    for level, _fs, level_gaps in decimation_levels(arrays, gaps, job.clock.fs, job.stream_level + 1, CHANNELS,
                                                    job.factor):
        if level <= job.binned_level:
            lv = job.levels[level]
            first, last = max(c0, job.lo_n), min(c1, job.hi_n - lv.win_b + 1)  # window starts, [first, last)
            if last > first:
                starts = np.arange(_cdiv(first, lv.hop_b), _cdiv(last, lv.hop_b), dtype=np.int64) * lv.hop_b
                assert ((starts - r0) % lv.scale == 0).all(), "a window off the level's sample grid"
                idx = (starts - r0) // lv.scale
                assert idx.size == 0 or idx[-1] + lv.win <= arrays[CHANNELS[0]].size, "a window past the margin"
                keep = ~_touches(idx, lv.win, level_gaps)
                if keep.any():
                    sums = _window_sums(arrays, idx[keep], lv)
                    bin_idx = (starts[keep] + lv.win_b // 2) // job.bin_n
                    uniq, first_i, counts = np.unique(bin_idx, return_index=True, return_counts=True)
                    out["bins"][level] = (uniq, [np.add.reduceat(s, first_i, axis=0) for s in sums], counts)
        if level == job.stream_level:
            a, b = h0 // q, h1 // q
            out["stream"] = {c: arrays[c][a:b].astype(np.float64) + medians[c] for c in CHANNELS}
            out["stream_gaps"] = [(max(g0, a) - a, min(g1, b) - a) for g0, g1 in level_gaps if g1 > a and g0 < b]
    return out


@dataclass
class WindowStore:
    """Every STFT window of one site-remote pair over [start, end), as `compute_windows` leaves it.

    ``levels[L]`` is a dict per level of the band scheme: ``level``,
    ``binned`` (a binned level), ``win`` (STFT points), ``win_b``/``hop_b``
    (window and hop in base samples), ``bands`` (indices into band_table's
    order), ``n_harm`` [bands], ``starts`` [items] (base sample of each
    item's start: a minute bin's, or a window's), ``span_n`` (an item's
    length: the bin or the window), ``n_used`` and ``n_possible`` [items]
    (windows kept and windows on the grid; 0/1 and 1 for a stream level's
    windows) and the band sums over each item's kept windows, ``er``,
    ``hr``, ``eh``, ``hh`` [items, bands, 2, 2] complex (<E R*>, <H R*>,
    <E H*>, <H H*>: rows Ex Ey or Hx Hy, columns the remote's Hx Hy or H's)
    and ``ee`` [items, bands, 2] (|Ex|^2 and |Ey|^2). ``stream`` is the
    stitched level-S stream (float32, median removed, gaps zeroed), sample 0
    at base sample ``stream_start``, with its ``stream_gaps``.
    """

    station: str
    remote: str
    sample_rate: float
    factor: int
    lo_n: int  # first base sample of [start, end)
    hi_n: int  # one past its last
    bin_n: int  # base samples per minute bin
    binned_level: int  # K, the deepest binned level (-1: none)
    band_level: np.ndarray
    band_lo_hz: np.ndarray
    band_hi_hz: np.ndarray
    levels: list
    stream: dict
    stream_start: int
    stream_gaps: list
    block_n: int
    n_blocks: int
    elapsed_s: float

    @property
    def clock(self) -> _Clock:
        """The sample clock at the store's rate."""
        return _Clock(self.sample_rate)

    @property
    def start(self) -> pd.Timestamp:
        """The UTC time of base sample ``lo_n``."""
        return pd.Timestamp(self.clock.ns(self.lo_n), unit="ns", tz="UTC")

    @property
    def end(self) -> pd.Timestamp:
        """The UTC time of base sample ``hi_n``."""
        return pd.Timestamp(self.clock.ns(self.hi_n), unit="ns", tz="UTC")

    @property
    def nbytes(self) -> int:
        """Bytes held: the minute and per-window sums and the stream."""
        total = sum(v.nbytes for lv in self.levels for v in lv.values() if isinstance(v, np.ndarray))
        return total + sum(v.nbytes for v in self.stream.values())


def compute_windows(local_h5, station: str, remote_h5, remote_station: str, start=None, end=None,
                    band_scheme: dict | None = None, workers: int = 1, progress=None) -> WindowStore:
    """Compute every STFT window of `station` against `remote_station` over [start, end), once.

    Opens both archives read-only and reads each block once, `workers`
    threads side by side; the store is the same for any worker count. It
    holds the minute sums of the binned levels, the sums per window of the
    stream levels and the stitched stream (see How it works in the module
    docstring).

    Args:
        local_h5: The local station's MTH5 archive.
        station (str): The local station.
        remote_h5: The remote station's MTH5 archive (it may be the local one).
        remote_station (str): The remote station.
        start: UTC start (naive is UTC); None for the start of the stations' common span.
        end: UTC end, likewise; None for the end of the common span.
        band_scheme (dict): The survey's band scheme (see crust.bands).
        workers (int): Threads reading blocks.
        progress: Optional callable progress(percent, message), called from the calling thread.

    Returns:
        WindowStore: The band sums, the window grid and the stitched stream.

    Raises:
        ValueError: Without `band_scheme`; when the sample rates differ, a
            `BIN_S` bin is not a whole number of samples or [start, end)
            holds no sample.
    """
    t_begin = time.time()
    if band_scheme is None:
        raise ValueError("band_scheme is required: crust.bands.build_band_scheme(sample_rate, **processing)")
    local = _layout(local_h5, station, LOCAL_ROLES)
    remote = _layout(remote_h5, remote_station, REMOTE_ROLES)
    fs = local.fs
    if abs(remote.fs - fs) > 1e-9 * fs:
        raise ValueError(f"{remote_station} is {remote.fs:g} Hz, {station} {fs:g} Hz")
    clock = _Clock(fs)
    factor, levels = _plan_levels(band_scheme, fs, local, remote)
    binned_level = max((lv.level for lv in levels if lv.binned), default=-1)
    stream_level = max(binned_level, 0)
    q = factor**stream_level
    bin_n = int(round(BIN_S * fs))
    if abs(bin_n - BIN_S * fs) > 1e-6:
        raise ValueError(f"{fs:g} Hz: a {BIN_S:g} s bin is not a whole number of samples")

    span = lambda st: (st.runs[0].start_ns, max(r.start_ns + int(round(r.n * 1e9 / st.fs)) for r in st.runs))
    lo_ns = max(span(local)[0], span(remote)[0]) if start is None else _ns(start)
    hi_ns = min(span(local)[1], span(remote)[1]) if end is None else _ns(end)
    lo_n, hi_n = clock.ceil(lo_ns), clock.ceil(hi_ns)
    if hi_n <= lo_n:
        raise ValueError(f"[{start}, {end}) holds no sample")
    block_n = max(q, int(round(CHUNK_S * fs)) // q * q)
    margin_n = _margin_n(fs, levels, factor, q)
    if margin_n > _cdiv(int(round(MARGIN_S * fs)), q) * q:
        logger.info(f"{fs:g} Hz: read margin widened to {margin_n / fs:g} s (the deepest binned window plus the "
                    f"decimation transient exceed {MARGIN_S:g} s)")
    b0 = lo_n // q * q
    n_blocks = _cdiv(hi_n - b0, block_n)
    logger.info(f"cross-powers {station} rr {remote_station}: {n_blocks} block(s) of {block_n / fs:g} s, "
                f"levels 0-{binned_level} per {BIN_S:g} s bin, {binned_level + 1}-{len(levels) - 1} per window "
                f"from the stitched level-{stream_level} stream, {workers} worker(s)")

    # binned levels: per minute bin, the sums of the blocks' kept windows. A bin meets at most two blocks,
    # and 0 + a + b equals 0 + b + a exactly, so merging blocks as they finish gives the same store
    # for any worker count.
    a0, a1 = lo_n // bin_n, (hi_n - 1) // bin_n + 1
    bins = np.arange(a0, a1, dtype=np.int64)
    stored = []
    for lv in levels:
        entry = {"level": lv.level, "binned": lv.binned, "win": lv.win, "win_b": lv.win_b, "hop_b": lv.hop_b,
                 "bands": lv.bands, "n_harm": lv.n_harm}
        if lv.binned:
            nb = lv.bands.size
            entry.update(starts=bins * bin_n, span_n=bin_n, n_used=np.zeros(bins.size, dtype=np.int64))
            for name in SUMS[:4]:
                entry[name] = np.zeros((bins.size, nb, 2, 2), dtype=np.complex128)
            entry["ee"] = np.zeros((bins.size, nb, 2))
            # grid windows (span inside [lo, hi)) whose centre lies in each bin, counted from the grid alone
            s_lo = np.maximum(bins * bin_n - lv.win_b // 2, lo_n)
            s_hi = np.minimum((bins + 1) * bin_n - lv.win_b // 2, hi_n - lv.win_b + 1)
            entry["n_possible"] = np.maximum(0, _cdiv(s_hi, lv.hop_b) - _cdiv(s_lo, lv.hop_b))
        stored.append(entry)
    # the stitched stream: level-S samples of every block's chunk proper (the first block's left
    # margin and the last block's right margin too), each block's medians added back; padded at
    # the start so that sample 0 lies on a multiple of factor**(last level) base samples
    first = b0 - margin_n
    align = factor ** (len(levels) - 1)
    stream_start = first // align * align
    pad = (first - stream_start) // q
    total = pad + (n_blocks * block_n + 2 * margin_n) // q
    stream = {c: np.zeros(total) for c in CHANNELS}
    gaps = [(0, pad)] if pad else []

    def merge(out):
        for level, (uniq, sums, counts) in out["bins"].items():
            entry, i = stored[level], uniq - a0
            for name, part in zip(SUMS, sums):
                entry[name][i] += part
            entry["n_used"][i] += counts
        k = out["k"]
        off = pad + (0 if k == 0 else (margin_n + k * block_n) // q)
        if out["stream"] is not None:
            for c in CHANNELS:
                stream[c][off: off + out["n"]] = out["stream"][c]
        gaps.extend((off + a, off + b) for a, b in out["stream_gaps"])

    same = Path(remote.path) == Path(local.path)
    with h5py.File(local.path, "r") as fl, (h5py.File(remote.path, "r") if not same else _Same(fl)) as fr:
        job = _Job(local, remote, (fl, fr), clock, levels, factor, binned_level, stream_level, lo_n, hi_n, b0,
                   block_n, margin_n, n_blocks, bin_n)
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            jobs = [pool.submit(_block, job, k) for k in range(n_blocks)]
            for done, fut in enumerate(as_completed(jobs), 1):
                merge(fut.result())
                if progress is not None:
                    progress(int(95 * done / n_blocks), f"block {done}/{n_blocks}")

    gaps = _merge(gaps + [(0, 0), (total, total)])  # the stream's ends filter like gaps
    covered = np.ones(total, dtype=bool)
    for a, b in gaps:
        covered[a:b] = False
    for c in CHANNELS:
        median = float(np.median(stream[c][covered])) if covered.any() else 0.0
        stream[c] = (stream[c] - median).astype("float32")

    # stream levels: decimated from the stream, windowed on the global grid
    arrays, kept_stream = dict(stream), {}
    for step, _fs, level_gaps in decimation_levels(arrays, list(gaps), fs / q, len(levels) - stream_level, CHANNELS,
                                                   factor):
        if step == 0:
            kept_stream = {c: arrays[c] for c in CHANNELS}  # gap samples zeroed: what the cascade decimates
        lv = levels[stream_level + step]
        if lv.binned:
            continue
        entry, nb = stored[lv.level], lv.bands.size
        w0, w1 = _cdiv(lo_n, lv.hop_b), (hi_n - lv.win_b) // lv.hop_b + 1
        starts = np.arange(w0, max(w0, w1), dtype=np.int64) * lv.hop_b
        assert ((starts - stream_start) % lv.scale == 0).all(), "a deep window off the level's sample grid"
        idx = (starts - stream_start) // lv.scale
        assert idx.size == 0 or idx[-1] + lv.win <= arrays[CHANNELS[0]].size, "a deep window past the stream"
        keep = ~_touches(idx, lv.win, level_gaps)
        entry.update(starts=starts, span_n=lv.win_b, n_used=keep.astype(np.int64),
                     n_possible=np.ones(starts.size, dtype=np.int64))
        for name in SUMS[:4]:
            entry[name] = np.zeros((starts.size, nb, 2, 2), dtype=np.complex128)
        entry["ee"] = np.zeros((starts.size, nb, 2))
        if keep.any():
            for name, s in zip(SUMS, _window_sums(arrays, idx[keep], lv)):
                entry[name][keep] = s
    if progress is not None:
        progress(100, "deep levels")
    level_of, band_lo, band_hi = band_table(band_scheme)
    store = WindowStore(station, remote_station, fs, factor, lo_n, hi_n, bin_n, binned_level, level_of, band_lo,
                        band_hi, stored, kept_stream, stream_start, gaps, block_n, n_blocks, time.time() - t_begin)
    logger.info(f"cross-powers {station} rr {remote_station}: {n_blocks} block(s) in {store.elapsed_s:.1f} s, "
                f"store {store.nbytes / 1e6:.1f} MB")
    return store


def _inv2(m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (inverse, determinant) of [..., 2, 2] matrices, NaN where singular."""
    det = m[..., 0, 0] * m[..., 1, 1] - m[..., 0, 1] * m[..., 1, 0]
    adj = np.stack([np.stack([m[..., 1, 1], -m[..., 0, 1]], -1), np.stack([-m[..., 1, 0], m[..., 0, 0]], -1)], -2)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = adj / np.where(det == 0, np.nan, det)[..., None, None]
    return inv, det


def _estimate(sums: dict, n_used: np.ndarray, n_possible: np.ndarray, n_harm: np.ndarray) -> dict:
    """Return the estimates per group and band from the band sums.

    A group has an estimate when it kept at least `MIN_WINDOWS` windows and
    at least half its grid windows, the rule
    `crust.timefreq.window_spectra` applies.

    Args:
        sums (dict): The group sums {er, hr, eh, hh, ee}.
        n_used (np.ndarray): Windows kept per group.
        n_possible (np.ndarray): Grid windows per group.
        n_harm (np.ndarray): Harmonics per band.

    Returns:
        dict: z, coh, n_windows, h_amp, e_amp, er, hr; NaN (n_windows 0) where
        a group has no estimate.
    """
    er, hr, eh, hh, ee = (sums[name] for name in SUMS)
    inv, _det = _inv2(hr)
    z = er @ inv
    valid = ((n_used >= MIN_WINDOWS) & (n_used >= 0.5 * n_possible))[:, None] & np.isfinite(z).all(axis=(-2, -1))
    coh = np.full(z.shape[:2] + (2,), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        for row in range(2):
            zr = z[..., row, :]
            cross = np.sum(np.conj(zr) * eh[..., row, :], axis=-1)  # <E Ep*>
            pred = np.real(np.einsum("...a,...ab,...b->...", zr, hh, np.conj(zr)))  # <Ep Ep*>
            coh[..., row] = np.abs(cross) ** 2 / (ee[..., row] * pred)
        count = n_used[:, None] * np.maximum(n_harm, 1)[None, :]
        h_amp = np.sqrt(np.maximum(np.real(hh[..., 0, 0] + hh[..., 1, 1]) / count, 0.0))
        e_amp = np.sqrt(np.maximum(ee.sum(axis=-1) / count, 0.0))
    bad = ~valid
    z[bad], coh[bad], h_amp[bad], e_amp[bad] = np.nan, np.nan, np.nan, np.nan
    er, hr = er.copy(), hr.copy()
    er[bad], hr[bad] = np.nan, np.nan
    n_windows = np.where(valid, n_used[:, None], 0)
    return {"z": z, "coh": coh, "n_windows": n_windows, "h_amp": h_amp, "e_amp": e_amp, "er": er, "hr": hr}


def bin_windows(store: WindowStore, chunk_s: float = CHUNK_S, start=None, end=None) -> dict:
    """Group a store's windows into chunks of `chunk_s` over [start, end), and into display groups per level.

    Reads the store alone. The range (default: the store's span) is rounded
    out to whole minutes and clipped to the store, and the result reports the
    range it covers; a tail under half a chunk joins the last chunk. Level L
    is shown on display groups of m_L chunks (`level_multiples`); a group's
    estimate needs `MIN_WINDOWS` kept windows and half its grid windows.

    Args:
        store (WindowStore): From `compute_windows`.
        chunk_s (float): The base chunk, a whole number of minutes (the GUI offers `CHUNKS_S`).
        start: UTC start of the range (naive is UTC); None for the store's.
        end: UTC end of the range; None for the store's.

    Returns:
        dict: ``start``, ``end`` (the range covered); ``station``, ``remote``,
        ``sample_rate``, ``chunk_s``, ``bin_s``, ``elapsed_s``; per band
        ``periods``, ``band_level``, ``band_lo_hz``, ``band_hi_hz``;
        ``base_starts``, ``base_ends``; ``grids`` and ``levels``, the display
        groups and their estimates per level (`band_view` reads one band); the
        estimates per base chunk (``z``, ``zxy``, ``coh_xy``, ...) of the
        ``levels_fit`` levels with m_L = 1; ``store`` and ``items``.

    Raises:
        ValueError: When `chunk_s` is not whole minutes or the range holds no chunk.
    """
    t_begin = time.time()
    fs, clock, bin_n = store.sample_rate, store.clock, store.bin_n
    ratio = float(chunk_s) / BIN_S
    if ratio < 1 - 1e-9 or abs(ratio - round(ratio)) > 1e-9:
        raise ValueError(f"chunk_s {chunk_s:g} s is not a whole number of {BIN_S:g} s bins")
    chunk_n = int(round(ratio)) * bin_n
    # the range asked for, rounded out to whole minutes (a binned level's sums come in whole minutes) and
    # clipped to the store: [start_n, end_n) is what the result covers, and says it covers
    start_n = store.lo_n if start is None else min(max(store.lo_n, clock.ceil(_ns(start))), store.hi_n)
    end_n = store.hi_n if end is None else max(min(store.hi_n, clock.ceil(_ns(end))), start_n)
    s0 = start_n // bin_n * bin_n
    start_n = max(s0, store.lo_n)
    end_n = min(_cdiv(end_n, bin_n) * bin_n, store.hi_n)
    n_full, tail = divmod(end_n - s0, chunk_n)
    if n_full == 0 and 2 * tail < chunk_n:
        raise ValueError(f"[{start}, {end}) holds no chunk of {chunk_s:g} s")
    edges = [s0 + chunk_n * k for k in range(n_full + 1)]
    if tail:
        if n_full == 0 or 2 * tail >= chunk_n:
            edges.append(end_n)
        else:
            edges[-1] = end_n
    edges = np.array(edges, dtype=np.int64)
    n_base = edges.size - 1
    shown = edges.copy()
    shown[0] = start_n
    base_starts, base_ends = clock.times(shown[:-1], store.lo_n), clock.times(shown[1:], store.lo_n)

    level_of, band_lo, band_hi = store.band_level, store.band_lo_hz, store.band_hi_hz
    n_band = level_of.size
    z = np.full((n_base, n_band, 2, 2), np.nan, dtype=complex)
    coh = np.full((n_base, n_band, 2), np.nan)
    n_win = np.zeros((n_base, n_band), dtype=int)
    h_amp, e_amp = np.full((n_base, n_band), np.nan), np.full((n_base, n_band), np.nan)
    er, hr = np.full((n_base, n_band, 2, 2), np.nan, dtype=complex), np.full((n_base, n_band, 2, 2), np.nan, dtype=complex)
    grids, per_level, items, fit = [], [], [], 0
    for lv in store.levels:
        m = _multiple(lv["n_harm"], lv["hop_b"], chunk_s, fs)
        starts, span_n = lv["starts"], lv["span_n"]
        if lv["binned"]:  # bins starting inside the grid; the grid's edges are whole minutes
            inside = (starts >= s0) & (starts < end_n)
        else:  # windows lying inside [start, end)
            inside = (starts >= start_n) & (starts + span_n <= end_n)
        idx = np.flatnonzero(inside)
        chunk = np.clip(np.searchsorted(edges, starts[idx] + span_n // 2, side="right") - 1, 0, n_base - 1)
        n_full_groups = n_base // m
        group_of_chunk = np.minimum(np.arange(n_base) // m, n_full_groups)  # a partial last group: n_full_groups
        n_groups = n_full_groups + (1 if n_base % m else 0)
        if n_full_groups == 0:
            n_groups, group_of_chunk = 0, np.full(n_base, -1)
        elif n_base % m and lv["n_possible"][idx][group_of_chunk[chunk] == n_full_groups].sum() < MIN_WINDOWS:
            group_of_chunk[group_of_chunk == n_full_groups] = n_full_groups - 1
            n_groups = n_full_groups
        group = group_of_chunk[chunk]  # -1: no display group (the level's smallest group exceeds the range)
        grouped = group >= 0
        first = np.arange(n_groups) * m
        last = np.r_[first[1:] - 1, n_base - 1] if n_groups else first
        grids.append({"starts": base_starts[first], "ends": base_ends[last], "multiple": m})
        sums, g_idx, g_group = {}, idx[grouped], group[grouped]
        for name in SUMS:
            sums[name] = np.zeros((n_groups,) + lv[name].shape[1:], dtype=lv[name].dtype)
            np.add.at(sums[name], g_group, lv[name][g_idx])
        n_used = np.bincount(g_group, weights=lv["n_used"][g_idx], minlength=n_groups).astype(np.int64)
        n_possible = np.bincount(g_group, weights=lv["n_possible"][g_idx], minlength=n_groups).astype(np.int64)
        est = _estimate(sums, n_used, n_possible, lv["n_harm"])
        per_level.append({"bands": lv["bands"], **est, "n_used": n_used, "n_possible": n_possible, "sums": sums})
        items.append({"idx": idx, "group": group})  # every item in range: the stack's, grouped or not
        if m == 1:
            fit += 1
            b = lv["bands"]
            z[:, b], coh[:, b], n_win[:, b] = est["z"], est["coh"], est["n_windows"]
            h_amp[:, b], e_amp[:, b], er[:, b], hr[:, b] = est["h_amp"], est["e_amp"], est["er"], est["hr"]
    elapsed = store.elapsed_s + time.time() - t_begin
    return {
        "station": store.station, "remote": store.remote, "sample_rate": fs, "chunk_s": float(chunk_s),
        "origin": ORIGIN, "bin_s": BIN_S, "elapsed_s": elapsed,
        "start": base_starts[0], "end": base_ends[-1],
        "periods": 1.0 / np.sqrt(band_lo * band_hi), "band_lo_hz": band_lo, "band_hi_hz": band_hi,
        "band_level": level_of,
        "base_starts": base_starts, "base_ends": base_ends, "grids": grids, "levels": per_level,
        "levels_fit": fit,
        "chunk_starts": base_starts, "chunk_ends": base_ends,
        "z": z, "zxy": z[:, :, 0, 1], "zyx": z[:, :, 1, 0], "coh_xy": coh[:, :, 0], "coh_yx": coh[:, :, 1],
        "n_windows": n_win, "h_amp": h_amp, "e_amp": e_amp, "er": er, "hr": hr,
        "store": store, "items": items,
    }


def band_view(result: dict, j: int) -> dict:
    """Return band j of a `bin_windows` result on its own level's grid.

    Args:
        result (dict): From `bin_windows`.
        j (int): The band, an index in band_table's order.

    Returns:
        dict: ``starts``, ``ends`` [group]; ``z`` [group, 2, 2]; ``zxy``,
        ``zyx``, ``coh_xy``, ``coh_yx``, ``n_windows``, ``h_amp``, ``e_amp``,
        ``er``, ``hr`` [group, ...]; ``level``, ``multiple``, ``period``. The
        arrays are empty for a level with no group.
    """
    level = int(result["band_level"][j])
    pl, grid = result["levels"][level], result["grids"][level]
    b = int(np.flatnonzero(pl["bands"] == j)[0])
    z = pl["z"][:, b]
    return {"starts": grid["starts"], "ends": grid["ends"], "z": z, "zxy": z[:, 0, 1], "zyx": z[:, 1, 0],
            "coh_xy": pl["coh"][:, b, 0], "coh_yx": pl["coh"][:, b, 1], "n_windows": pl["n_windows"][:, b],
            "h_amp": pl["h_amp"][:, b], "e_amp": pl["e_amp"][:, b], "er": pl["er"][:, b], "hr": pl["hr"][:, b],
            "level": level, "multiple": grid["multiple"], "period": float(result["periods"][j])}


def _item_masks(result: dict, masks, j: int):
    """Return, for band j: (store level, item indices, their groups, kept, hit by a mask covering the band)."""
    store = result["store"]
    level = int(result["band_level"][j])
    lv, it = store.levels[level], result["items"][level]
    idx, group = it["idx"], it["group"]
    kept = lv["n_used"][idx] > 0
    hit = np.zeros(idx.size, dtype=bool)
    period = float(result["periods"][j])
    wanted = [m for m in (normalise(m) for m in masks or []) if applies(m, period)]
    if wanted and idx.size:
        times = store.clock.ns_array(lv["starts"][idx], store.lo_n).astype("datetime64[ns]")
        for m in wanted:  # an item a mask overlaps is out: a window's span, or a bin's
            hit |= windows_in_mask(times, lv["span_n"] / store.sample_rate, m)
    return lv, idx, group, kept, hit


def masked_chunks(result: dict, masks, j: int) -> np.ndarray:
    """Return, per group of band j on its level's grid, 0 clear, 1 partly masked or 2 fully masked.

    Judged per item: a window (stream levels) or a minute bin (binned
    levels) is masked when a mask covering band j (`crust.masks.applies`,
    at the band's centre period) overlaps its span; a group is fully masked
    when every kept item in it is, partly when some are. For a level with
    m_L = 1 the groups are the base chunks.

    Args:
        result (dict): From `bin_windows`.
        masks: Mask dicts (`crust.masks`).
        j (int): The band.

    Returns:
        np.ndarray: The int8 code per group (`band_view`'s groups).
    """
    n_groups = len(result["grids"][int(result["band_level"][j])]["starts"])
    _lv, _idx, group, kept, hit = _item_masks(result, masks, j)
    kept = kept & (group >= 0)  # a level with no display group: nothing to mark
    n_kept = np.bincount(group[kept], minlength=n_groups)
    n_hit = np.bincount(group[kept & hit], minlength=n_groups)
    return np.where((n_kept > 0) & (n_hit == n_kept), 2, np.where(n_hit > 0, 1, 0)).astype(np.int8)


def stack_impedance(result_or_store, masks=(), chunk_s: float | None = None) -> dict:
    """Return the stacked remote-reference impedance per band from every kept window the masks leave.

    For band j, Z_j = (sum er) (sum hr)^-1 over every kept window inside the
    result's range that no mask covering the band overlaps, a mask taking
    whole minute bins on the binned levels; the estimate is the same for any
    chunk length. Its error is a delete-one-group jackknife over the band's
    display groups, each weighted by its kept window count; it needs
    `MIN_GROUPS` groups, and a band with fewer gets NaN and a note.

    Args:
        result_or_store: A `bin_windows` result or a `WindowStore`.
        masks: Mask dicts (`crust.masks`); normalised here.
        chunk_s (float | None): The base chunk to bin at; None keeps the
            result's, or `CHUNK_S` for a store.

    Returns:
        dict: per band, shortest period first, ``periods``, ``band_lo_hz``,
        ``band_hi_hz``, ``band_level``; ``z`` [band, 2, 2] in (mV/km)/nT and
        ``z_err``; ``zxy``, ``zyx``, ``zxy_err``, ``zyx_err``; ``n_chunks``
        (display groups contributing), ``n_masked`` (groups the masks took
        whole), ``n_windows`` (windows stacked), ``n_windows_masked``,
        ``notes``; and ``station``, ``remote``, ``chunk_s`` and ``masks``
        (the normalised list applied).
    """
    if isinstance(result_or_store, WindowStore):
        result = bin_windows(result_or_store, CHUNK_S if chunk_s is None else chunk_s)
    else:
        result = result_or_store
        if chunk_s is not None and float(chunk_s) != result["chunk_s"]:
            result = bin_windows(result["store"], chunk_s, result["start"], result["end"])
    masks = [normalise(m) for m in masks or []]
    n_band = result["periods"].size
    z = np.full((n_band, 2, 2), np.nan, dtype=complex)
    z_err = np.full((n_band, 2, 2), np.nan)
    kept_n, masked_n, windows, windows_masked = (np.zeros(n_band, dtype=int) for _ in range(4))
    notes = [""] * n_band
    for j in range(n_band):
        lv, idx, group, kept, hit = _item_masks(result, masks, j)
        b = int(np.flatnonzero(lv["bands"] == j)[0])
        n_groups = len(result["grids"][lv["level"]]["starts"])
        use = kept & ~hit  # the stack's items: every kept, unmasked one, with or without a display group
        grouped = use & (group >= 0)  # the jackknife's: those in a display group
        weight = lv["n_used"][idx]
        windows[j], windows_masked[j] = int(weight[use].sum()), int(weight[kept & hit].sum())
        in_group = np.bincount(group[grouped], weights=weight[grouped], minlength=n_groups)
        had = np.bincount(group[kept & (group >= 0)], minlength=n_groups) > 0
        kept_n[j], masked_n[j] = int((in_group > 0).sum()), int((had & (in_group == 0)).sum())
        if not use.any():
            notes[j] = "no window kept"
            continue
        er_i, hr_i = lv["er"][idx[use], b], lv["hr"][idx[use], b]
        s_er, s_hr = er_i.sum(axis=0), hr_i.sum(axis=0)
        z[j] = s_er @ _inv2(s_hr)[0]
        n_g = kept_n[j]
        if n_groups == 0:
            m = result["grids"][lv["level"]]["multiple"]
            notes[j] = (f"no jackknife: level {lv['level']} has no display group (a group of {m} x "
                        f"{result['chunk_s']:g} s is longer than the range)")
            continue
        if n_g < MIN_GROUPS:
            notes[j] = f"no jackknife: {n_g} display group(s), {MIN_GROUPS} needed"
            continue
        g_er = np.zeros((n_groups, 2, 2), dtype=complex)
        g_hr = np.zeros((n_groups, 2, 2), dtype=complex)
        np.add.at(g_er, group[grouped], lv["er"][idx[grouped], b])
        np.add.at(g_hr, group[grouped], lv["hr"][idx[grouped], b])
        present = in_group > 0
        leave = (s_er - g_er[present]) @ _inv2(s_hr - g_hr[present])[0]  # Z without group g
        size = in_group[present]
        total = size.sum()
        h = total / size
        theta = n_g * z[j] - np.sum((1.0 - size / total)[:, None, None] * leave, axis=0)
        pseudo = h[:, None, None] * z[j] - (h - 1.0)[:, None, None] * leave
        z_err[j] = np.sqrt(np.sum(np.abs(pseudo - theta) ** 2 / (h - 1.0)[:, None, None], axis=0) / n_g)
    return {
        "station": result.get("station"), "remote": result.get("remote"), "masks": masks,
        "chunk_s": result["chunk_s"],
        "periods": result["periods"], "band_lo_hz": result["band_lo_hz"], "band_hi_hz": result["band_hi_hz"],
        "band_level": result["band_level"],
        "z": z, "z_err": z_err, "zxy": z[:, 0, 1], "zyx": z[:, 1, 0],
        "zxy_err": z_err[:, 0, 1], "zyx_err": z_err[:, 1, 0],
        "n_chunks": kept_n, "n_masked": masked_n, "n_windows": windows, "n_windows_masked": windows_masked,
        "notes": notes,
    }


def chunk_impedances(local_h5, station: str, remote_h5, remote_station: str, start=None, end=None,
                     band_scheme: dict | None = None, chunk_s: float = CHUNK_S, workers: int = 1,
                     progress=None) -> dict:
    """Return `bin_windows(compute_windows(...), chunk_s)`: per chunk and band, the RR impedance.

    `compute_windows` describes the arguments and `bin_windows` the result's
    keys.

    Raises:
        ValueError: When `chunk_s` is not a whole number of minutes, checked
            before any archive is read.
    """
    ratio = float(chunk_s) / BIN_S
    if ratio < 1 - 1e-9 or abs(ratio - round(ratio)) > 1e-9:
        raise ValueError(f"chunk_s {chunk_s:g} s is not a whole number of {BIN_S:g} s bins")
    store = compute_windows(local_h5, station, remote_h5, remote_station, start, end, band_scheme, workers, progress)
    return bin_windows(store, chunk_s)


class _Same:
    """The local h5py handle as a context manager that leaves it open, for a remote in the same file."""

    def __init__(self, handle):
        self.handle = handle

    def __enter__(self):
        return self.handle

    def __exit__(self, *exc):
        return False
