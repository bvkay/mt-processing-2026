"""Chunk-by-chunk remote-reference impedances of one site: what the Cross-powers tab draws.

A cross-power editor/viewer for the processed data of one site at a time, so
that a burst shows up on the cross powers and specific time windows and
polar coordinates can be masked out. `chunk_impedances` cuts [start, end)
into chunks of `chunk_s` and gives, per chunk and per band of the survey's
lemimt band scheme (`mtproc.bands.lemimt_band_scheme`, the same decimation
levels, windows and band edges processing uses), the remote-reference
impedance of that chunk alone,

    Z = <E R*> <H R*>^-1,

with its coherence between E and the E that Z predicts, the number of STFT
windows it averaged and the chunk's mean |H| and |E|. A chunk that sits apart
from the others in time or in the (log10 |Z|, phase) plane is what the
student masks (`mtproc.masks`); nothing here decides anything.

How each chunk is computed -- no spectral maths of its own:

- **Read.** Each station's run layout comes from its MTH5 metadata (opened
  read-only once, closed again); the samples are then sliced with h5py alone,
  chunk by chunk, by integer index arithmetic from each run's start (as
  `mtproc.virtual` streams its members): a chunk plus `MARGIN_S` either side
  is all that is ever held, so a 51 h record is never loaded whole. The
  margin is read wherever the record has it (outside [start, end) too) so the
  decimation filters settle before the chunk proper; where there is no data
  it is a gap, as any sample no run covers.
- **Decimate and transform.** `mtproc.timefreq.decimation_levels` (the QC
  cascade's own decimation: scipy FIR, zero phase, gaps zeroed and dilated
  per level) walks the band scheme's factor-4 levels, and at each level
  `mtproc.timefreq.window_spectra` averages the auto- and cross-spectra of
  every Hann-tapered STFT window of the level's `num_samples_window` points,
  50 % overlap, lying inside the chunk proper (never thinned; a window
  touching a gap is dropped, and a chunk keeping fewer than four windows or
  half its windows at a level is NaN there).
- **Calibrate.** Every channel's spectra are divided by the complex response
  of its MTH5 filter chain -- the filters aurora removes
  (`aurora.time_series.spectrogram_helpers.calibrate_stft_obj`: not
  decimation, not delay, marked applied) -- evaluated at the level's FFT
  harmonics, so E is in mV/km, H in nT and Z in (mV/km)/nT, as the EDIs are.
- **Band-average.** A band holds the harmonics f_lo <= f < f_hi (mt_metadata's
  `Band`, closed on the left), the cross-powers are summed over them, and Z,
  the coherences and the amplitudes follow from those sums.

What differs from processing, on purpose: no robust weighting (a chunk's Z
is the plain RR estimate -- the outliers are what the student looks for), no
prewhitening (a no-op on a per-harmonic average), 50 % overlap where aurora
uses 25 %, and scipy's decimation filter where aurora uses its own; so a
chunk scatters about the processed EDI rather than sitting on it.

**The classical editor's estimate.** Each chunk also keeps its band sums
<E R*> and <H R*> (summed over its STFT windows, ``er``, ``hr``), so
`stack_impedance(result, masks)` re-forms, per band, the stacked
remote-reference impedance from the chunks the masks keep,

    Z = (sum_k <E R*>_k) (sum_k <H R*>_k)^-1,

with a delete-one-chunk jackknife error -- what WinGLink's or Phoenix's
cross-power editor does with the segments processing produced. It is how a
band-limited mask acts (aurora 0.6.2 takes none: see `mtproc.masks`); an
all-band mask acts both there and in aurora (a time cut). A library
function only: no GUI calls it and nothing writes it as an EDI yet.

Time scales linearly with the record: every chunk reads only itself plus
`MARGIN_S` either side, so a 60 s chunk reads 188 s. With 4 worker threads,
a full local-remote overlap of tens of hours at 1000 Hz processes in tens
of seconds for 600 s chunks and roughly double that for 60 s chunks; a 2 h
window with 600 s chunks takes a few seconds. Checked in
`tests/crosspower_unit.py` (synthetic archives, a known Z) and against the
processed EDI in `tests/gui_smoke.py` (34); see the Cross-powers note in
src/mtproc_gui/README.md.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5

from .masks import applies, normalise, utc
from .timefreq import _real_runs, decimation_levels, window_spectra

CHUNK_S = 600.0
MARGIN_S = 64.0  # read either side of a chunk: >= GAP_DILATE output samples down to level 5 at 1000 Hz
MIN_WINDOWS = 4  # `window_spectra`'s own floor: fewer STFT windows in a chunk and the level is NaN
GRID_TOL = 1e-3  # samples a run's start may sit off the local grid before it is logged
LOCAL_ROLES = ("ex", "ey", "hx", "hy")
REMOTE_ROLES = ("hx", "hy")
R = "r_"  # the remote's channels in the chunk's arrays
# the cross-powers a chunk needs: <E R*>, <H R*>, <E H*>, <Hx Hy*> (window_spectra's
# csd[(a, b)] is mean(conj(a) b) = <b a*>, so the conjugated channel comes first)
PAIRS = tuple(
    [(R + r, e) for e in ("ex", "ey") for r in REMOTE_ROLES]
    + [(R + r, h) for h in ("hx", "hy") for r in REMOTE_ROLES]
    + [(h, e) for e in ("ex", "ey") for h in ("hx", "hy")]
    + [("hx", "hy")]
)
CHANNELS = LOCAL_ROLES + tuple(R + r for r in REMOTE_ROLES)


def _ns(t) -> int:
    """A time (text, Timestamp; naive = UTC) as integer ns since the epoch, UTC."""
    ts = pd.Timestamp(str(t)) if not isinstance(t, pd.Timestamp) else t
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)


def _roles(names, wanted) -> dict[str, str]:
    """{hx|hy|ex|ey: the archive's channel playing it}: the first two magnetics (b..., h...)
    in name order are hx, hy, the first two electrics (e...) ex, ey -- a LEMI-423's own names,
    a LEMI-424's bx by e1 e2 (`mtproc_gui.channels.roles`, the same rule)."""
    mags = sorted(n for n in names if n[:1].lower() in ("h", "b") and n[1:2].lower() in ("x", "y"))
    elecs = sorted(n for n in names if n[:1].lower() == "e")
    parts = dict(zip(("hx", "hy"), mags)) | dict(zip(("ex", "ey"), elecs))
    missing = [w for w in wanted if w not in parts]
    if missing:
        raise ValueError(f"no channel plays {missing} among {sorted(names)}")
    return {w: parts[w] for w in wanted}


@dataclass
class _Run:
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
        """The complex response aurora divides this channel's spectrum by, at `freqs` (Hz)."""
        response, filters = self.chains[role]
        if not filters:
            return np.ones(freqs.size, dtype=complex)
        return np.asarray(response.complex_response(freqs, filters_list=filters), dtype=complex)


def _layout(h5_path, station: str, roles) -> _Station:
    """Read `station`'s run layout and filter chains from its MTH5, read-only, closed on return."""
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
    """`st`'s channel `role` over n samples from t0_ns on the local grid: (int counts or None, covered spans).

    Integer arithmetic from each run's start: the run's sample 0 lands at
    index round((run start - t0) * fs) of the chunk, the nearest sample if a
    run sits off the grid (logged once per run past `GRID_TOL`).
    """
    group = handle[st.group]
    raw, covered = None, []
    for run in st.runs:
        pos = (run.start_ns - t0_ns) * st.fs / 1e9
        i0 = int(round(pos))
        if abs(pos - i0) > GRID_TOL and (st.station, run.run_id) not in warned:
            warned.add((st.station, run.run_id))
            logger.warning(f"{st.station} {run.run_id}: run start {pos - i0:+.3f} samples off the local grid "
                           f"-- placed at the nearest sample")
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
    out, cursor = [], 0
    for a, b in sorted(covered):
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < n:
        out.append((cursor, n))
    return out


def _merge(spans) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


@dataclass
class _Plan:
    """What every chunk shares: the bands, the levels, the responses at each level's harmonics."""

    fs: float
    factor: int
    windows: list[int]  # STFT points per level
    levels: int  # levels a chunk can use (>= MIN_WINDOWS windows)
    band_level: np.ndarray
    band_lo: np.ndarray
    band_hi: np.ndarray
    # [level] -> {channel key: response at that level's rfft frequencies}
    responses: list[dict[str, np.ndarray]]
    n_chunk: int
    margin: int


def _cross(psd, csd, a: str, b: str) -> np.ndarray:
    """<a b*> per frequency from `window_spectra`'s outputs (csd[(p, q)] = <q p*>)."""
    if a == b:
        return psd[a][0].astype(complex)
    if (b, a) in csd:
        return csd[(b, a)][0]
    return np.conj(csd[(a, b)][0])


def _chunk(k: int, t0_ns: int, local: _Station, remote: _Station, handles, plan: _Plan, warned: set):
    """One chunk: {"z", "er", "hr" [band, 2, 2], "coh" [band, 2], "n", "h", "e" [band]}."""
    n_band = plan.band_level.size
    out = {"z": np.full((n_band, 2, 2), np.nan, dtype=complex), "coh": np.full((n_band, 2), np.nan),
           "n": np.zeros(n_band, dtype=int), "h": np.full(n_band, np.nan), "e": np.full(n_band, np.nan),
           "er": np.full((n_band, 2, 2), np.nan, dtype=complex),
           "hr": np.full((n_band, 2, 2), np.nan, dtype=complex)}
    m, n = plan.margin, plan.n_chunk + 2 * plan.margin
    start = t0_ns - int(round(m * 1e9 / plan.fs))
    arrays, gaps = {}, []
    for st, handle, roles, prefix in ((local, handles[0], LOCAL_ROLES, ""),
                                      (remote, handles[1], REMOTE_ROLES, R)):
        for role in roles:
            raw, covered = _read(st, handle, role, start, n, warned)
            if raw is None:
                return k, out  # a station has no sample in this chunk
            gaps += _uncovered(covered, n)
            inside = np.concatenate([raw[a:b] for a, b in covered])
            arrays[prefix + role] = (raw - np.median(inside)).astype("float32")
            del raw
    gaps = _merge(gaps)
    for level, fs, level_gaps in decimation_levels(arrays, gaps, plan.fs, plan.levels, CHANNELS, plan.factor):
        scale = plan.factor ** level
        i0, i1 = -(-m // scale), (m + plan.n_chunk) // scale
        sub = {c: arrays[c][i0:i1] for c in CHANNELS}
        sub_gaps = [(max(0, a - i0), min(i1 - i0, b - i0)) for a, b in level_gaps if b > i0 and a < i1]
        win = plan.windows[level]
        _t, freqs, psd, csd, used = window_spectra(
            sub, sub_gaps, fs, (i1 - i0) / fs, (i1 - i0) / fs, win, CHANNELS, PAIRS,
            max_segments=10**9, counts=True)
        in_level = np.flatnonzero(plan.band_level == level)
        if used[0] == 0 or in_level.size == 0:
            continue
        resp = plan.responses[level]

        def S(a, b):  # calibrated <a b*> per frequency (the DC bin, in no band, may divide by 0)
            with np.errstate(divide="ignore", invalid="ignore"):
                return _cross(psd, csd, a, b) / (resp[a] * np.conj(resp[b]))

        e_names, h_names, r_names = ("ex", "ey"), ("hx", "hy"), (R + "hx", R + "hy")
        er = np.array([[S(e, r) for r in r_names] for e in e_names])  # [2, 2, freq]
        hr = np.array([[S(h, r) for r in r_names] for h in h_names])
        eh = np.array([[S(e, h) for h in h_names] for e in e_names])
        hh = np.array([[S(a, b) for b in h_names] for a in h_names])
        ee = np.array([S(e, e).real for e in e_names])
        for j in in_level:
            sel = (freqs >= plan.band_lo[j]) & (freqs < plan.band_hi[j])
            if not sel.any():
                continue
            ER, HR, EH, HH = (x[..., sel].sum(axis=-1) for x in (er, hr, eh, hh))
            EE = ee[:, sel].sum(axis=-1)
            try:
                z = ER @ np.linalg.inv(HR)
            except np.linalg.LinAlgError:
                continue
            for row in range(2):
                zr = z[row]
                cross = np.sum(np.conj(zr) * EH[row])  # <E Ep*>
                pred = np.real(zr @ HH @ np.conj(zr))  # <Ep Ep*>
                with np.errstate(divide="ignore", invalid="ignore"):
                    out["coh"][j, row] = np.abs(cross) ** 2 / (EE[row] * pred)
            out["z"][j] = z
            out["n"][j] = int(used[0])
            # window_spectra averages over the STFT windows: times their count is their sum,
            # which is what chunks stack by (`stack_impedance`)
            out["er"][j], out["hr"][j] = ER * int(used[0]), HR * int(used[0])
            n_sel = int(sel.sum())
            out["h"][j] = math.sqrt(max(np.real(HH[0, 0] + HH[1, 1]) / n_sel, 0.0))
            out["e"][j] = math.sqrt(max(float(EE.sum()) / n_sel, 0.0))
    return k, out


def band_table(band_scheme: dict):
    """(level, f_lo, f_hi) arrays over every band of `band_scheme`, shortest period first.

    A band's period is 1 / sqrt(f_lo f_hi), its geometric centre, as aurora
    labels it in the EDI.
    """
    rows = [(int(level), float(lo), float(hi))
            for level, bands in band_scheme["band_edges"].items() for lo, hi in np.asarray(bands)]
    rows.sort(key=lambda r: -math.sqrt(r[1] * r[2]))
    return (np.array([r[0] for r in rows], dtype=int), np.array([r[1] for r in rows]),
            np.array([r[2] for r in rows]))


def levels_in_chunk(band_scheme: dict, n_samples: int) -> int:
    """How many of the scheme's levels hold `MIN_WINDOWS` half-overlapping STFT windows in
    `n_samples` samples at the base rate: bands on deeper levels get no estimate from a chunk."""
    windows = [int(w) for w in band_scheme["num_samples_window"]]
    factors = list(band_scheme["decimation_factors"])
    factor = factors[1] if len(factors) > 1 else 4
    count = 0
    while count < len(windows) and 0.5 * (MIN_WINDOWS + 1) * windows[count] * factor ** count <= n_samples:
        count += 1
    return count


def chunk_impedances(local_h5, station: str, remote_h5, remote_station: str, start=None, end=None,
                     band_scheme: dict | None = None, chunk_s: float = CHUNK_S, workers: int = 1,
                     progress=None) -> dict:
    """Per chunk of `chunk_s` and per band of `band_scheme`, `station`'s RR impedance against `remote_station`.

    `start`/`end` (UTC; naive is UTC; None: the stations' common span) bound
    the chunks, which start at `start` on the local sample grid; a last chunk
    under half of `chunk_s` is dropped. `band_scheme` is
    `mtproc.bands.lemimt_band_scheme`'s dict (band_edges, decimation_factors,
    num_samples_window), exactly what processing is given. `workers` threads
    compute chunks side by side; `progress(percent, message)`, if given, is
    called from the calling thread as chunks finish.

    Returns a dict of numpy arrays, [chunk, band] unless said otherwise:

    - ``periods`` [band] s, shortest first; ``band_lo_hz``, ``band_hi_hz``,
      ``band_level`` [band];
    - ``chunk_starts``, ``chunk_ends`` (pd.DatetimeIndex, UTC) [chunk];
    - ``zxy``, ``zyx`` complex, (mV/km)/nT; ``z`` [chunk, band, 2, 2] the whole tensor;
    - ``coh_xy``, ``coh_yx``: squared coherence of Ex (Ey) with the Ex (Ey)
      the chunk's Z predicts from Hx, Hy;
    - ``n_windows`` int: STFT windows the chunk averaged at the band's level
      (0: none -- the band's window does not fit the chunk MIN_WINDOWS
      times, or gaps took them);
    - ``h_amp`` nT/sqrt(Hz), ``e_amp`` (mV/km)/sqrt(Hz): sqrt of the band's
      mean |Hx|^2 + |Hy|^2 (|Ex|^2 + |Ey|^2) power density;
    - ``er``, ``hr`` complex [chunk, band, 2, 2]: <E R*> and <H R*> (rows
      Ex, Ey or Hx, Hy; columns the remote's Hx, Hy), summed over the band's
      harmonics and the chunk's STFT windows -- ``z`` is er @ inv(hr), and
      `stack_impedance` sums them over chunks;

    plus ``station``, ``remote``, ``sample_rate``, ``chunk_s``, ``levels``
    (the levels a chunk reaches) and ``elapsed_s``.
    """
    t_begin = time.time()
    if band_scheme is None:
        raise ValueError("band_scheme is required: mtproc.bands.lemimt_band_scheme(sample_rate, **processing)")
    local = _layout(local_h5, station, LOCAL_ROLES)
    remote = _layout(remote_h5, remote_station, REMOTE_ROLES)
    fs = local.fs
    if abs(remote.fs - fs) > 1e-9 * fs:
        raise ValueError(f"{remote_station} is {remote.fs:g} Hz, {station} {fs:g} Hz")
    factors = list(band_scheme["decimation_factors"])
    factor = factors[1] if len(factors) > 1 else 4
    if factors[0] != 1 or any(f != factor for f in factors[1:]):
        raise ValueError(f"decimation factors {factors}: a first 1 then one repeated factor is expected")
    windows = [int(w) for w in band_scheme["num_samples_window"]]

    span = lambda st: (st.runs[0].start_ns, max(r.start_ns + int(round(r.n * 1e9 / st.fs)) for r in st.runs))
    lo = max(span(local)[0], span(remote)[0]) if start is None else _ns(start)
    hi = min(span(local)[1], span(remote)[1]) if end is None else _ns(end)
    # the first chunk starts on the local grid, at or after `lo`
    g0 = local.runs[0].start_ns
    first = g0 + int(math.ceil((lo - g0) * fs / 1e9 - 1e-9)) * 1e9 / fs
    n_chunk = int(round(chunk_s * fs))
    total = (hi - first) * fs / 1e9
    n_chunks = int(total // n_chunk) + (1 if total % n_chunk >= 0.5 * n_chunk else 0)
    if n_chunks <= 0:
        raise ValueError(f"[{start}, {end}) holds no chunk of {chunk_s:g} s")
    starts_ns = [int(round(first + k * n_chunk * 1e9 / fs)) for k in range(n_chunks)]
    chunk_lengths = [n_chunk] * n_chunks
    tail = int(round(total - (n_chunks - 1) * n_chunk))
    if tail < n_chunk:
        chunk_lengths[-1] = tail

    level_of, band_lo, band_hi = band_table(band_scheme)
    levels = levels_in_chunk(band_scheme, n_chunk)
    responses = []
    for level in range(levels):
        freqs = np.fft.rfftfreq(windows[level], factor ** level / fs)
        resp = {role: local.response(role, freqs) for role in LOCAL_ROLES}
        resp.update({R + role: remote.response(role, freqs) for role in REMOTE_ROLES})
        responses.append(resp)
    margin = int(round(MARGIN_S * fs))

    n_band = level_of.size
    z = np.full((n_chunks, n_band, 2, 2), np.nan, dtype=complex)
    coh = np.full((n_chunks, n_band, 2), np.nan)
    n_win = np.zeros((n_chunks, n_band), dtype=int)
    h_amp, e_amp = np.full((n_chunks, n_band), np.nan), np.full((n_chunks, n_band), np.nan)
    er = np.full((n_chunks, n_band, 2, 2), np.nan, dtype=complex)
    hr = np.full((n_chunks, n_band, 2, 2), np.nan, dtype=complex)
    logger.info(f"cross-powers {station} rr {remote_station}: {n_chunks} chunk(s) of {chunk_s:g} s, "
                f"{levels} of {len(windows)} levels fit a chunk, {workers} worker(s)")
    warned: set = set()
    same = Path(remote.path) == Path(local.path)
    with h5py.File(local.path, "r") as fl, (h5py.File(remote.path, "r") if not same else _Same(fl)) as fr:
        plans = [_Plan(fs, factor, windows, levels_in_chunk(band_scheme, length), level_of, band_lo, band_hi, responses, length,
                       margin) for length in chunk_lengths]
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            jobs = [pool.submit(_chunk, k, starts_ns[k], local, remote, (fl, fr), plans[k], warned)
                    for k in range(n_chunks)]
            for done, job in enumerate(as_completed(jobs), 1):
                k, out = job.result()
                z[k], coh[k], n_win[k], h_amp[k], e_amp[k] = out["z"], out["coh"], out["n"], out["h"], out["e"]
                er[k], hr[k] = out["er"], out["hr"]
                if progress is not None:
                    progress(int(100 * done / n_chunks), f"chunk {done}/{n_chunks}")
    starts = pd.DatetimeIndex(pd.to_datetime(starts_ns, unit="ns", utc=True))
    ends = starts + pd.to_timedelta(np.array(chunk_lengths) / fs, unit="s")
    elapsed = time.time() - t_begin
    logger.info(f"cross-powers {station} rr {remote_station}: {n_chunks} chunk(s) in {elapsed:.1f} s")
    return {
        "station": station, "remote": remote_station, "sample_rate": fs, "chunk_s": float(chunk_s),
        "levels": levels, "elapsed_s": elapsed,
        "periods": 1.0 / np.sqrt(band_lo * band_hi), "band_lo_hz": band_lo, "band_hi_hz": band_hi,
        "band_level": level_of,
        "chunk_starts": starts, "chunk_ends": ends,
        "z": z, "zxy": z[:, :, 0, 1], "zyx": z[:, :, 1, 0],
        "coh_xy": coh[:, :, 0], "coh_yx": coh[:, :, 1],
        "n_windows": n_win, "h_amp": h_amp, "e_amp": e_amp, "er": er, "hr": hr,
    }


def masked_chunks(result: dict, masks, j: int) -> np.ndarray:
    """Per chunk of `result` (`chunk_impedances`): True when a mask covering band j
    (`mtproc.masks.applies`, at the band's centre period) overlaps the chunk in time."""
    starts, ends = result["chunk_starts"], result["chunk_ends"]
    period = float(result["periods"][j])
    out = np.zeros(len(starts), dtype=bool)
    for m in (normalise(m) for m in masks or []):
        if applies(m, period):
            out |= np.asarray((starts < utc(m["end"])) & (ends > utc(m["start"])))
    return out


def stack_impedance(result: dict, masks=()) -> dict:
    """The stacked remote-reference impedance per band from the chunks `masks` keep.

    For band j the kept chunks are those with an estimate there
    (``n_windows`` > 0, finite cross-powers) that no mask covering the band
    overlaps (`masked_chunks`: all-band masks and band masks alike). Then

        Z_j = (sum_k er[k, j]) (sum_k hr[k, j])^-1

    -- one RR estimate over every STFT window of the kept chunks, not a mean
    of chunk impedances -- and its error is the delete-one-chunk jackknife:
    with Z_(k) the estimate without chunk k and m kept chunks,
    err = sqrt((m - 1) / m * sum_k |Z_(k) - mean Z_(.)|^2), per element
    (NaN with fewer than two chunks). No robust weighting: a chunk is in or
    out, as in the classical cross-power editors.

    Returns numpy arrays per band (shortest period first, as `result`):
    ``periods``, ``band_lo_hz``, ``band_hi_hz``, ``band_level``; ``z``
    complex [band, 2, 2] (mV/km)/nT, ``z_err`` [band, 2, 2] real;
    ``zxy``, ``zyx``, ``zxy_err``, ``zyx_err``; ``n_chunks`` (kept),
    ``n_masked`` (chunks with an estimate that masks took out),
    ``n_windows`` (STFT windows in the kept chunks); plus ``station``,
    ``remote`` and ``masks`` (the normalised list applied).
    """
    masks = [normalise(m) for m in masks or []]
    er, hr, n_win = result["er"], result["hr"], result["n_windows"]
    n_band = er.shape[1]
    z = np.full((n_band, 2, 2), np.nan, dtype=complex)
    z_err = np.full((n_band, 2, 2), np.nan)
    kept_n, masked_n, windows = (np.zeros(n_band, dtype=int) for _ in range(3))
    for j in range(n_band):
        has = (n_win[:, j] > 0) & np.isfinite(er[:, j]).all(axis=(1, 2)) & np.isfinite(hr[:, j]).all(axis=(1, 2))
        drop = masked_chunks(result, masks, j) & has
        keep = np.flatnonzero(has & ~drop)
        kept_n[j], masked_n[j], windows[j] = keep.size, int(drop.sum()), int(n_win[keep, j].sum())
        if keep.size == 0:
            continue
        s_er, s_hr = er[keep, j].sum(axis=0), hr[keep, j].sum(axis=0)
        try:
            z[j] = s_er @ np.linalg.inv(s_hr)
        except np.linalg.LinAlgError:
            continue
        if keep.size < 2:
            continue
        leave = []
        for k in keep:
            try:
                leave.append((s_er - er[k, j]) @ np.linalg.inv(s_hr - hr[k, j]))
            except np.linalg.LinAlgError:
                leave.append(np.full((2, 2), np.nan, dtype=complex))
        leave = np.array(leave)
        m = keep.size
        z_err[j] = np.sqrt((m - 1) / m * np.sum(np.abs(leave - leave.mean(axis=0)) ** 2, axis=0))
    return {
        "station": result.get("station"), "remote": result.get("remote"), "masks": masks,
        "periods": result["periods"], "band_lo_hz": result["band_lo_hz"], "band_hi_hz": result["band_hi_hz"],
        "band_level": result["band_level"],
        "z": z, "z_err": z_err, "zxy": z[:, 0, 1], "zyx": z[:, 1, 0],
        "zxy_err": z_err[:, 0, 1], "zyx_err": z_err[:, 1, 0],
        "n_chunks": kept_n, "n_masked": masked_n, "n_windows": windows,
    }


class _Same:
    """The local handle again, as a context manager that does not close it (remote in the same file)."""

    def __init__(self, handle):
        self.handle = handle

    def __enter__(self):
        return self.handle

    def __exit__(self, *exc):
        return False
