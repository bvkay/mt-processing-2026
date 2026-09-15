"""Declared, per-site time-domain noise filters applied at ingest.

Nothing here is automatic. A student sees the problem in the QC views (the
50 Hz line in the spectrogram, the 12 s square wave on the Time Series tab,
the comb in the PSD), tries a filter list on one loaded window on the GUI's
Filter Data tab (`apply_filters_arrays` on that window, raw drawn behind the
filtered), and declares the list for that site in `<survey>/filters.yaml`;
`ingest_site` applies it in the declared order on the raw counts and records
it in the archive, so an archive built before the list changed must be
rebuilt.

Order matters: mains first, so the cathodic-protection
edges are timed on a cleaner series. Prototypes and numbers:
`docs/prototypes/cp_recipe_notch_first.py`, `surveys/burra/qc_notes.md`.
**Cascade advice** for the Butterworth kinds: a high-pass goes first, before
the notch and the cp stack (a drift leaks into the median cycle: on
`tests/noise_unit.py`'s synthetic, a 100-unit drift under a 5-unit 12 s
square wave left 14 % of it after cp alone, 0.5 % after hp then cp), and a
low-pass goes last. `replace` is always applied first, wherever it sits in
the list, because `ingest_site` swaps the donor's coil in before any filter
runs (the borrowed channel then gets the same treatment as the site's own).

Filter specs (one dict each, keyed by kind; `channels` defaults to all of
the run's channels wherever it is accepted):

    - notch: {f0: 50.0, harmonics: 9, q: 30.0, passes: 2, extra: [75, 125],
              channels: [ex, ey, hx, hy]}
        "50 Hz + harmonics": zero-phase IIR notch at f0 and its harmonics
        below Nyquist (plus any `extra` lines a site shows), applied `passes`
        times (two by default: the grid wanders +-0.1 Hz and one pass leaves
        ~7 dB).
    - mains: {f0: 50.0, harmonics: 9, block_s: 1.0, step_fraction: 0.3,
              channels: [ex, ey, hx, hy]}
        "mains subtraction (fitted, follows steps)": `mains_subtract` removes
        the mains at f0 and its harmonics below Nyquist by subtraction, not
        by filtering, so a step in the mains amplitude leaves no ringing (a
        second-order notch's decays as exp(-pi f0 t / q): about
        +-4.6 q / (pi f0) s per pass, +-0.6 s and 400 mV/km on Morocco
        C23's Ex at q 25). The phase is tracked from 1 s demodulations at f0
        (the block-to-block phase advance, a running median over 10 blocks
        then a mean over 5, clipped to +-0.5 Hz, integrated); a step is a
        change of the fundamental's 0.1 s amplitude by more than
        step_fraction of the larger level, and by more than 30 times the
        amplitude's own 0.1 s jitter (so a channel whose mains is near the
        noise has none), to a level that holds for the next 0.1 s from one
        that held before (a spike or sferic never splits), placed to the
        sample. Between steps, sum of a_k cos k theta + b_k sin k theta is
        fitted per block_s block, the coefficients joined by straight lines between block
        centres (flat beyond the end ones) and never across a step: the
        model jumps where the mains jumped. The band it takes is about
        +-1/block_s Hz around each harmonic (the natural signal there goes
        with the mains; a notch's is about f / q wide). On 2 h of C23 (1000
        Hz) it follows 71 steps on ex, 19 on ey, 8 on hy, none on hx (two
        loads switching, 125 <-> 240 and 160 <-> 440 mV/km on Ex), in 3.4-4.1
        s a channel on one thread; the 50 Hz line ends 3-5 dB above the
        floor (raw +58/+68 dB; the notch -54/-47), 250 and 350 Hz 7-14 dB
        above it (the notch -88 to -95: the harmonics wander inside a
        second; block_s 0.25 takes both 10-12 dB below the floor, with
        +-4 Hz around each). What is left at a step is the switching's own
        transient (on Ex at 549.5 s, 150 mV/km for a few samples; the notch
        rang to 406 over +-0.4 s). Between the lines it also removes the steps'
        sidebands, which the notch keeps: C23 Ex's 20-45 and 55-95 Hz come
        out 7.8 dB lower than raw (the notch's 0.3 dB), and Ey's first
        540 s, before any step, within 0.005 dB of raw from 1 to 145 Hz.
        On 2 h of Curnamona D02, whose 50 Hz stands 8 dB above the floor,
        the 30 % test alone found about 14 500 "steps" a channel (43 s to
        preview after a notch); with the jitter test 0 to 3 on the raw
        window (up to 19 after a notch: bursts in what is left).
    - hp: {cutoff_hz: 0.001, order: 4, channels: [ex, ey, hx, hy]}
        "high-pass": zero-phase Butterworth (`scipy.signal.butter` as
        second-order sections, run forward and back by `sosfiltfilt`), so
        the magnitude is squared -- -6 dB at the cutoff, 2 x order poles'
        roll-off -- and nothing is delayed. `cutoff_hz` has no default.
        For drift and electrode settling; it takes the MT signal below the
        cutoff with it, so keep 1 / cutoff_hz beyond the longest period you
        intend to process (curnamona processes to 5000 s: 0.0002 Hz).
    - lp: {cutoff_hz: 100.0, order: 4, channels: [ex, ey, hx, hy]}
        "low-pass": the same Butterworth, low-pass; for hash above the
        band of interest. The archive keeps its sample rate.
    - cp: {period_s: 12.0, window_minutes: 10, channels: [ex, ey, hx, hy],
           refine: false, reference: ey}
        "cathodic protection stack" (a strictly periodic interference): in
        every window, stack all cycles at the fixed period and subtract the
        median cycle from each channel. No edge detection, no cutting.
        `refine: true` measures the period from the reference channel's
        autocorrelation (needed only when the declared period is not known to
        ~0.1 ms).
    - burst: {threshold: 12.0, min_len_s: 0.05, pad_s: 0.1, taper_s: 0.05,
              reference: [ex, ey], channels: [ex, ey, hx, hy]}
        "burst removal (short transients)": `detect_bursts` on the reference
        channels (default the electrics), then `fill_spans` on `channels`.
        Per reference, the envelope is |x - its local level| averaged over
        min_len_s, the local level being the medians of 1 s blocks joined
        by straight lines (`LEVEL_S`; the window's median would leave the
        long-period signal and the electrode drift in the envelope), divided
        by the running MAD of the same series over 60 s (`SCALE_S`, medians
        of the 1 s blocks' MADs, a gap's all-zero blocks left out). A sample
        is in a burst when any reference's envelope exceeds `threshold`
        (white noise sits near 1.2); runs shorter than min_len_s (less the
        averaging's own widening, so a lone spike or sferic never counts)
        are dropped, the rest widened by pad_s each side and merged. In every
        span each listed channel is set to its own local level -- zero on an
        offset-removed, flat window (the preview), the electrode offset on
        ingest's counts -- with a cosine taper of taper_s inside both ends,
        so nothing outside the spans changes. **Put it after the notch**:
        on Morocco C23 the "bursts" are the zero-phase notch's two-sided
        ringing (+-0.5 s) at abrupt steps of the 50 Hz amplitude (Ex
        180 -> 430 mV/km within a cycle); before the notch the 50 Hz itself
        sets the MAD and nothing is found. Threshold 12 by default: on 2 h
        of C23 after its notch, 5, 8 and 12 all catch the four known bursts
        (549.5, 607.4, 1319.8, 1365.1 s) and the same 67 s of ringing, but
        8 also masks 6 sferic-like spikes and 42 s where the background
        rose after a load switched on (the 60 s MAD lags it), 12 none of
        the spikes and 9 s: 75 s in all (1.0 % of the window), 0.7 s to
        detect on two references of 7.2 M samples.
    - flip: {channels: [ey]}
        "flip polarity": each listed channel times -1 (a channel wired with
        reversed polarity; Morocco D12's yx phase is 180 degrees from
        lemimt's with the resistivity matching). `channels` has no default,
        and a name the run lacks is refused. It acts on the channel as it
        stands in the list, so a `replace`d coil is flipped too.
    - replace: {hx: A06}
        "replace magnetics from another site": at ingest
        `mtproc.ingest._replace_channels` reads the donor's raw files with the
        donor's own coil calibration. On arrays (the preview) the donor's
        channel comes from `donors[site][comp]` when the caller loaded it.

Why cp and not a detector: on 12 h of Burra35 the plain stack raised coil
coherence with the remote from 0.49 to 0.71 (0.3-2 s) and left 0.05-0.3 s
untouched, while any excision around the edges (+-0.2 to 0.5 s, straight-line
bridging twice a cycle) pushed it below raw. The interrupter is crystal-locked
(12.0000 s to a few hundredths of a ms), so a fixed period folds exactly.
"""

from __future__ import annotations

import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from loguru import logger
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import butter, decimate, iirnotch, sosfiltfilt, tf2sos

ELECTRIC = ("ex", "ey")
KINDS = ("replace", "notch", "mains", "hp", "lp", "cp", "burst", "flip")
LEVEL_S = 1.0  # burst: the local level is the medians of blocks this long, joined by straight lines
SCALE_S = 60.0  # burst: the running MAD's window
MAINS_TRACK_S = 1.0  # mains: the phase is tracked from demodulations over blocks this long
MAINS_TRACK_MEDIAN = 10  # mains: a running median of the per-block frequency offset, in blocks, ...
MAINS_TRACK_MEAN = 5  # ... then a running mean (the median alone passes a drifting grid's block-to-block jitter)
MAINS_MAX_OFFSET = 0.5  # mains: the tracked offset is clipped to this (Hz)
MAINS_SUB_S = 0.1  # mains: steps in the amplitude are sought between sub-blocks this long
MAINS_STEP_SIGMA = 30.0  # mains: ... and must exceed this many times the sub-block amplitude's jitter
MAINS_SPREAD_S = 60.0  # mains: that jitter is 1.4826 x the median change between sub-blocks over blocks this long
MAINS_RUN_MAX = 3  # mains: a step's changes span at most this many sub-block boundaries (a switching transient)
MAINS_MIN_TAIL_S = 0.1  # mains: a segment's last partial block shorter than this joins the one before it
MAINS_CHUNK = 1 << 17  # mains: samples per vectorised pass (a basis of 18 rows x 131072 float64 is 19 MB)


def mains_notch(
    x: np.ndarray, fs: float, f0: float = 50.0, harmonics: int = 9, q: float = 30.0,
    passes: int = 2, extra=(),
) -> np.ndarray:
    """Zero-phase comb of second-order IIR notches at f0, 2 f0, ... below
    Nyquist, plus any `extra` lines (Hz), applied `passes` times.

    Two passes by default: the grid frequency wanders ±0.1 Hz within a
    10-min block (Burra35: 49.91-50.09 Hz), and a single Q=30 notch at
    50.000 left the line 7 dB above the floor over 90 min; the second pass
    takes it 20 dB below. Tracking the block's mean frequency does not help.
    """
    y = np.asarray(x, dtype="float64")
    lines = [k * f0 for k in range(1, int(harmonics) + 1) if k * f0 < 0.5 * fs]
    lines += [float(f) for f in extra if 0 < float(f) < 0.5 * fs]
    for _ in range(int(passes)):
        for fk in lines:
            b, a = iirnotch(fk, q, fs=fs)
            y = sosfiltfilt(tf2sos(b, a), y)
    return y


class _MainsPhase:
    """The tracked mains phase theta(t) = 2 pi (f0 t + the integrated frequency offset), and its harmonic basis.

    Each `MAINS_TRACK_S` block is demodulated at f0 (t from the record's
    start); the phase advance from one block to the next over 2 pi times the
    block is the offset from f0, smoothed (`_mains_smooth`) and clipped. That
    offset belongs to the boundary between the two blocks; joined by straight
    lines (flat beyond the first and last) and integrated, the phase is
    piecewise quadratic and follows a steadily drifting grid exactly.
    """

    def __init__(self, y: np.ndarray, fs: float, f0: float):
        self.fs, self.f0 = float(fs), float(f0)
        self.m = m = max(2, int(round(MAINS_TRACK_S * fs)))
        nb = len(y) // m
        self.offsets, self.integral = np.zeros(1), np.zeros(1)
        if nb < 2:
            return
        ref = 2.0 * np.pi * self.f0 * np.arange(m) / self.fs
        cos_r, sin_r, u = np.cos(ref), np.sin(ref), np.arange(m) - 0.5 * (m - 1)
        blocks = y[: nb * m].reshape(nb, m)  # a view
        # sum (x - its block's straight line) exp(-i 2 pi f0 tau), tau from the block's start: the
        # line (an electrode offset and drift, in counts at ingest) taken out through the sums
        level, slope = blocks.mean(axis=1), (blocks @ u) / (u @ u)
        c = (blocks @ cos_r - level * cos_r.sum() - slope * (u @ cos_r)) \
            - 1j * (blocks @ sin_r - level * sin_r.sum() - slope * (u @ sin_r))
        c *= np.exp(-2j * np.pi * np.mod(self.f0 * (np.arange(nb) * m) / self.fs, 1.0))  # ... t from the record's
        dt = m / self.fs
        self.offsets = d = _mains_smooth(np.angle(c[1:] * np.conj(c[:-1])) / (2.0 * np.pi * dt))
        self.integral = np.concatenate(([0.0], np.cumsum(0.5 * (d[:-1] + d[1:]) * dt)))  # cycles at the knots

    def cycles(self, i0: int, i1: int) -> np.ndarray:
        """theta / 2 pi at samples [i0, i1) (the f0 t part modulo 1)."""
        i = np.arange(i0, i1, dtype="float64")
        out = np.mod(i * self.f0 / self.fs, 1.0)
        d, nk, m = self.offsets, len(self.offsets), self.m
        if nk < 2:
            return out if not d[0] else out + d[0] * (i - (m - 0.5)) / self.fs
        # knot j (between tracking blocks j and j + 1) sits at sample (j + 1) m - 1/2
        j = np.clip(np.floor((i + 0.5) / m).astype(np.int64) - 1, 0, nk - 2)
        u = (i - ((j + 1) * m - 0.5)) / self.fs
        span = m / self.fs
        inside = np.clip(u, 0.0, span)  # the offset ramps between knots and is flat beyond the ends
        out += self.integral[j] + d[j] * u + 0.5 * (d[j + 1] - d[j]) / span * inside * (2.0 * u - inside)
        return out

    def basis(self, i0: int, i1: int, nh: int) -> np.ndarray:
        """(2 nh, i1 - i0): rows cos theta, sin theta, cos 2 theta, sin 2 theta, ... over samples [i0, i1)."""
        th = 2.0 * np.pi * self.cycles(i0, i1)
        out = np.empty((2 * nh, i1 - i0))
        np.cos(th, out=out[0])
        np.sin(th, out=out[1])
        tmp = th  # scratch from here on
        for k in range(1, nh):  # angle addition: cheaper than trig per harmonic, exact to a few eps
            c, s = out[2 * k - 2], out[2 * k - 1]
            np.multiply(c, out[0], out=out[2 * k]); np.multiply(s, out[1], out=tmp); out[2 * k] -= tmp
            np.multiply(s, out[0], out=out[2 * k + 1]); np.multiply(c, out[1], out=tmp); out[2 * k + 1] += tmp
        return out


def _mains_smooth(d: np.ndarray) -> np.ndarray:
    """The per-block offsets (Hz): running median (`MAINS_TRACK_MEDIAN`, drops the blocks a step or a spike
    upsets), running mean (`MAINS_TRACK_MEAN`), clipped to +-`MAINS_MAX_OFFSET`.

    The mean is there because a median passes a steadily drifting offset
    through unchanged, noise and all (the sequence is monotone): on
    `tests/noise_unit.py`'s synthetic (49.95 -> 50.05 Hz in 120 s) the
    median alone left the 250 Hz line 6.2 dB above the floor, 1.3 dB below
    it with the mean.
    """
    d = median_filter(d, size=MAINS_TRACK_MEDIAN, mode="nearest")
    return np.clip(uniform_filter1d(d, MAINS_TRACK_MEAN, mode="nearest"), -MAINS_MAX_OFFSET, MAINS_MAX_OFFSET)


def _lsq(g: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Batched least squares from normal equations g (nb, p, p) and r (nb, p); a whisper of ridge for safety."""
    p = g.shape[-1]
    g = g + (1e-12 * np.trace(g, axis1=1, axis2=2) / p)[:, None, None] * np.eye(p)
    return np.linalg.solve(g, r[:, :, None])[:, :, 0]


def _lsq_one(basis: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Least-squares coefficients of x on one block's basis rows."""
    return _lsq((basis @ basis.T)[None], (basis @ x)[None])[0]


def _with_line(basis: np.ndarray, i0: int, centre: float, scale: float) -> np.ndarray:
    """basis (rows over samples i0 ...) with a constant and a straight line appended: fitted, never subtracted,
    so an offset or a drift (ingest's counts carry the electrode's) cannot leak into the harmonics."""
    u = (np.arange(i0, i0 + basis.shape[1]) - centre) / scale
    return np.vstack((basis, np.ones_like(u), u))


def _mains_amplitudes(y: np.ndarray, ph: _MainsPhase, ms: int) -> np.ndarray:
    """The fundamental's amplitude over consecutive ms-sample sub-blocks, demodulated with the tracked phase
    after each sub-block's straight line is taken out (through the sums: no copy of y)."""
    nsb = len(y) // ms
    amp = np.empty(nsb)
    per = max(1, MAINS_CHUNK // ms)
    u = np.arange(ms) - 0.5 * (ms - 1)
    for q0 in range(0, nsb, per):
        q1 = min(nsb, q0 + per)
        b = ph.basis(q0 * ms, q1 * ms, 1)
        seg = y[q0 * ms: q1 * ms].reshape(-1, ms)
        level, slope = seg.mean(axis=1), (seg @ u) / max(u @ u, 1e-300)
        cos_b, sin_b = b[0].reshape(-1, ms), b[1].reshape(-1, ms)
        re = np.einsum("ij,ij->i", seg, cos_b) - level * cos_b.sum(axis=1) - slope * (cos_b @ u)
        im = np.einsum("ij,ij->i", seg, sin_b) - level * sin_b.sum(axis=1) - slope * (sin_b @ u)
        amp[q0:q1] = 2.0 / ms * np.hypot(re, im)
    return amp


def _mains_split(y: np.ndarray, s: int, cyc: int, width: int, ph: _MainsPhase, nh: int) -> int:
    """The sample within a cycle of s that best splits the old waveform from the new.

    The harmonics are fitted on `width` samples ending a cycle before s (the
    old level) and on `width` starting a cycle after it (the new); the split k
    in [s - cyc, s + cyc] minimises the old fit's squared residual before k
    plus the new fit's from k on. The one-cycle amplitude's crossing alone
    sits a few samples off (its 2 f0 image and the harmonics bias it), and a
    sample on the wrong side keeps the whole step's difference there.
    """
    n = len(y)
    lo, hi = max(0, s - cyc), min(n, s + cyc)
    before, after = (max(0, lo - width), lo), (hi, min(n, hi + width))
    if min(before[1] - before[0], after[1] - after[0]) < 2 * nh + 4 or hi - lo < 2:
        return s
    here = _with_line(ph.basis(lo, hi, nh), lo, s, width)
    err = [(y[lo:hi] - _lsq_one(_with_line(ph.basis(a, b, nh), a, s, width), y[a:b]) @ here) ** 2
           for a, b in (before, after)]
    cost = np.concatenate(([0.0], np.cumsum(err[0]))) + np.concatenate((np.cumsum(err[1][::-1])[::-1], [0.0]))
    return lo + int(np.argmin(cost))


def _mains_steps(y: np.ndarray, fs: float, ph: _MainsPhase, step_fraction: float, nh: int) -> np.ndarray:
    """Sorted sample indices where the mains amplitude steps (each the first sample at the new level)."""
    n = len(y)
    ms = max(1, int(round(MAINS_SUB_S * fs)))
    cyc = max(2, int(round(fs / ph.f0)))
    amp = _mains_amplitudes(y, ph, ms)
    if len(amp) < 3:
        return np.empty(0, dtype=np.int64)
    change = np.abs(np.diff(amp))
    # a step must also stand MAINS_STEP_SIGMA times above the amplitude's own jitter (1.4826 x the median
    # change over the MAINS_SPREAD_S block it falls in): where the mains is near the noise, 30 % changes
    # come every half second (D02 after its notch: 15500 "steps" a channel in 2 h, 43 s to preview)
    per = max(1, int(round(MAINS_SPREAD_S / MAINS_SUB_S)))
    nblk = -(-len(change) // per)
    padded = np.full(nblk * per, np.nan)
    padded[: len(change)] = change
    floor = np.repeat(MAINS_STEP_SIGMA * 1.4826 * np.nanmedian(padded.reshape(nblk, per), axis=1), per)[: len(change)]
    big = (change > step_fraction * np.maximum(amp[:-1], amp[1:])) & (change > floor)  # boundary m: sub-blocks m, m + 1
    todo = []
    # a run of big boundaries (up to MAINS_RUN_MAX: a mixed sub-block, a switching transient) is a step
    # when the level after it, which then holds, differs from the level before it by the same test: a
    # spike or a sferic comes back and never counts; C23 Ex at 607.4 s, 366 -> 110 -> 160 mV/km, does
    edges = np.diff(np.concatenate(([0], big.astype(np.int8), [0])))
    for r0, r1 in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1):
        if r1 - r0 >= MAINS_RUN_MAX or r1 + 1 >= len(big):
            continue
        old = amp[r0 - 1] if r0 >= 1 else amp[r0]
        new = amp[r1 + 2] if r1 + 2 < len(amp) else amp[r1 + 1]
        if abs(new - old) > max(step_fraction * max(old, new), floor[r0], floor[r1]):
            todo.append((old, new, r0 * ms, (r1 + 2) * ms, (r0 + r1 + 2) * ms // 2))
    # a step inside sub-block m + 1 can split into two changes each under the test (C23 Ex
    # 427 -> 343 -> 252 mV/km at 2914.3 s): taken over the pair when the middle one lies between
    two = np.abs(amp[2:] - amp[:-2])
    wide = (two > step_fraction * np.maximum(amp[:-2], amp[2:])) & (two > np.maximum(floor[:-1], floor[1:]))
    between = (amp[1:-1] - amp[:-2]) * (amp[2:] - amp[1:-1]) >= 0
    quiet = ~np.concatenate(([False], big[:-2])) & ~np.concatenate((big[2:], [True]))  # boundaries m - 1, m + 2
    straddle = wide & between & quiet & ~big[:-1] & ~big[1:]
    todo += [(amp[m], amp[m + 2], (m + 1) * ms - cyc, (m + 2) * ms + cyc, int((m + 1.5) * ms))
             for m in np.flatnonzero(straddle)]
    half = cyc // 2
    found = []
    for old, new, lo, hi, b in todo:
        # where the one-cycle sliding amplitude crosses the levels' midpoint (nearest b), then to the sample
        mid, sign = 0.5 * (old + new), np.sign(new - old)
        lo, hi = max(half, lo), min(n - (cyc - half), hi)
        if hi <= lo:
            continue
        w0, w1 = lo - half, hi - half + cyc  # the window for position i is [i - half, i - half + cyc)
        basis = ph.basis(w0, w1, 1)
        u = np.arange(w1 - w0) - 0.5 * (w1 - w0 - 1)
        near = y[w0:w1] - y[w0:w1].mean() - u * (y[w0:w1] @ u) / (u @ u)  # the window's straight line out
        re = np.concatenate(([0.0], np.cumsum(near * basis[0])))
        im = np.concatenate(([0.0], np.cumsum(near * basis[1])))
        a = 2.0 / cyc * np.hypot(re[cyc:] - re[:-cyc], im[cyc:] - im[:-cyc])
        above = sign * (a - mid) >= 0
        cross = np.flatnonzero(~above[:-1] & above[1:]) + 1
        s = b if not len(cross) else lo + int(cross[np.argmin(np.abs(lo + cross - b))])
        found.append(_mains_split(y, s, cyc, ms, ph, nh))
    keep, last = [], 0
    for s in np.unique(np.asarray(found, dtype=np.int64)):  # a segment under 2 cycles joins the one before
        if s - last >= 2 * cyc:
            keep.append(int(s))
            last = s
    while keep and n - keep[-1] < 2 * cyc:
        keep.pop()
    return np.asarray(keep, dtype=np.int64)


def _mains_segment(y: np.ndarray, a: int, b: int, fs: float, ph: _MainsPhase, nh: int, block_s: float) -> None:
    """Fit the harmonics per block within [a, b), join the coefficients by straight lines between the
    blocks' centres (flat beyond the end ones) and subtract the model from y[a:b] in place."""
    p = 2 * nh
    m = max(2 * p, int(round(block_s * fs)))
    nfull, rest = divmod(b - a, m)
    if nfull == 0:
        regular, last = 0, (a, b)
    elif rest == 0:
        regular, last = nfull, None
    elif rest < MAINS_MIN_TAIL_S * fs:
        regular, last = nfull - 1, (a + (nfull - 1) * m, b)
    else:
        regular, last = nfull, (a + nfull * m, b)
    nb = regular + (last is not None)
    coefs, centres = np.empty((nb, p)), np.empty(nb)
    per = max(1, MAINS_CHUNK // m)
    u = (np.arange(m) - 0.5 * (m - 1)) / m  # each block's straight line, fitted with the harmonics, never subtracted
    for q0 in range(0, regular, per):  # the regular blocks, stacked: one batched solve per chunk
        q1 = min(regular, q0 + per)
        s0, s1 = a + q0 * m, a + q1 * m
        bt = ph.basis(s0, s1, nh).reshape(p, q1 - q0, m).transpose(1, 0, 2)  # (blocks, p, m)
        yb = y[s0:s1].reshape(q1 - q0, m)
        g = np.zeros((q1 - q0, p + 2, p + 2))
        g[:, :p, :p] = np.matmul(bt, bt.transpose(0, 2, 1))
        g[:, :p, p] = g[:, p, :p] = bt.sum(axis=2)
        g[:, :p, p + 1] = g[:, p + 1, :p] = bt @ u
        g[:, p, p], g[:, p + 1, p + 1], g[:, p, p + 1], g[:, p + 1, p] = m, u @ u, u.sum(), u.sum()
        r = np.empty((q1 - q0, p + 2))
        r[:, :p] = np.matmul(bt, yb[:, :, None])[:, :, 0]
        r[:, p], r[:, p + 1] = yb.sum(axis=1), yb @ u
        coefs[q0:q1] = _lsq(g, r)[:, :p]
        centres[q0:q1] = s0 + np.arange(q1 - q0) * m + 0.5 * (m - 1)
    if last is not None:
        centres[-1] = 0.5 * (last[0] + last[1] - 1)
        line = _with_line(ph.basis(*last, nh), last[0], centres[-1], last[1] - last[0])
        coefs[-1] = _lsq_one(line, y[last[0]:last[1]])[:p]
    for c0 in range(a, b, MAINS_CHUNK):
        c1 = min(b, c0 + MAINS_CHUNK)
        i = np.arange(c0, c1, dtype="float64")
        joined = np.stack([np.interp(i, centres, coefs[:, k]) for k in range(p)])
        y[c0:c1] -= np.einsum("ps,ps->s", ph.basis(c0, c1, nh), joined)


def mains_subtract(
    x: np.ndarray, fs: float, f0: float = 50.0, harmonics: int = 9, block_s: float = 1.0,
    step_fraction: float = 0.3,
) -> tuple[np.ndarray, dict]:
    """(y, info): a float64 copy of x less a model of the mains, fitted block by block, that follows steps.

    Phase: `_MainsPhase` (1 s demodulations at f0, the offset tracked and
    integrated). Steps (`_mains_steps`): the fundamental's amplitude over
    0.1 s sub-blocks, demodulated with that phase. A boundary is "big" where
    it changes by more than step_fraction of the larger level and by more
    than `MAINS_STEP_SIGMA` times the amplitude's local jitter; a run of big
    boundaries (up to `MAINS_RUN_MAX`) is a step when the level after it
    (which holds for the next sub-block) differs from the one before it by
    the same test -- so a spike or a sferic, which comes back, never splits
    -- and so is a change split over two quiet boundaries by a sub-block in
    between. Each is placed where a one-cycle sliding amplitude crosses the
    midpoint of the levels, then to the sample by a least-squares split
    (`_mains_split`); segments under 2 cycles are merged.
    Fit (`_mains_segment`): within each segment, sum over k of a_k cos k theta
    + b_k sin k theta (the harmonics below Nyquist) per block_s block (a last
    partial block under 0.1 s joins the one before), the coefficients joined
    by straight lines between block centres inside the segment, never across a
    step. It takes about +-1/block_s Hz around each harmonic with the mains.

    `info`: {"harmonics": the number fitted, "offset_mean": the tracked
    offset's mean (Hz), "steps": the steps' sample indices}. Memory: x's
    float64 copy (the output) and about 75 MB of `MAINS_CHUNK`-sample
    temporaries whatever the length (6 h at 1000 Hz: 173 + 75 MB, 11 s).
    """
    y = np.array(x, dtype="float64")
    n = len(y)
    nh = sum(1 for k in range(1, int(harmonics) + 1) if k * f0 < 0.5 * fs)
    info = {"harmonics": nh, "offset_mean": 0.0, "steps": np.empty(0, dtype=np.int64)}
    if nh == 0 or n < 2 * max(2, int(round(fs / f0))):
        return y, info
    ph = _MainsPhase(y, fs, f0)
    steps = _mains_steps(y, fs, ph, float(step_fraction), nh)
    info["offset_mean"], info["steps"] = float(np.mean(ph.offsets)), steps
    bounds = np.concatenate(([0], steps, [n]))
    for a, b in zip(bounds[:-1], bounds[1:]):
        _mains_segment(y, int(a), int(b), fs, ph, nh, float(block_s))
    return y, info


def refine_period(ref: np.ndarray, fs: float, nominal_s: float, cycles: int = 50) -> float:
    """The cycle period to ~0.1 ms from the autocorrelation peak `cycles` periods out.

    A 10 ms resolution at 100 Hz divided by 50 cycles gives 0.2 ms; parabolic
    interpolation of the peak does better. Uses up to 3 h of the reference,
    band-passed 0.005-5 Hz. (Burra's interrupter came out at 12.0000 s.)
    """
    r = np.asarray(ref, dtype="float64")
    r = r - np.median(r)
    r = sosfiltfilt(butter(2, [1.0 / 200.0, 5.0], btype="band", fs=fs, output="sos"), r)
    q = 10
    d = decimate(r, q, ftype="fir", zero_phase=True)
    fsd = fs / q
    d = d[: int(min(len(d), 3 * 3600 * fsd))]
    lag0 = int(round(cycles * nominal_s * fsd))
    span = max(2, int(round(0.005 * fsd * cycles)))  # +-5 ms per cycle
    lags = np.arange(lag0 - span, lag0 + span + 1)
    ac = np.array([np.dot(d[:-lag], d[lag:]) for lag in lags])
    k = int(np.argmax(ac))
    lag = float(lags[k])
    if 0 < k < len(ac) - 1:
        y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]
        if (y0 - 2 * y1 + y2) != 0:
            lag += 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
    return lag / fsd / cycles


def cp_stack_subtract(x: np.ndarray, fs: float, period_s: float, window_minutes: float = 10.0) -> np.ndarray:
    """In each window, stack every cycle at the fixed period and subtract
    the median cycle. Phase is free per window, so nothing needs detecting;
    the natural field averages down by sqrt(cycles per window)."""
    y = np.asarray(x, dtype="float64").copy()
    n = len(y)
    L = int(round(period_s * fs))
    win = int(round(window_minutes * 60.0 * fs))
    for w0 in range(0, n, win):
        w1 = min(n, w0 + win)
        n_cyc = int((w1 - w0) // (period_s * fs))
        if n_cyc < 5:
            continue
        starts = w0 + np.round(np.arange(n_cyc) * period_s * fs).astype(int)
        starts = starts[starts + L <= n]
        tmpl = np.median(np.stack([y[s : s + L] for s in starts]), axis=0)
        tmpl -= np.median(tmpl)
        for s in starts:
            y[s : s + L] -= tmpl
    return y


def butterworth(x: np.ndarray, fs: float, cutoff_hz: float, order: int = 4, btype: str = "highpass") -> np.ndarray:
    """Zero-phase Butterworth high- or low-pass (`sosfiltfilt`: magnitude squared, no delay)."""
    if not 0.0 < float(cutoff_hz) < 0.5 * fs:
        raise ValueError(f"cutoff {cutoff_hz} Hz is not between 0 and Nyquist ({0.5 * fs:g} Hz)")
    sos = butter(int(order), float(cutoff_hz), btype=btype, fs=fs, output="sos")
    return sosfiltfilt(sos, np.asarray(x, dtype="float64"))


def _blocks(x: np.ndarray, fs: float):
    """(centres, medians) of x's `LEVEL_S` blocks (at least 8 samples; the last one partial), centres in samples."""
    n = len(x)
    m = max(8, int(round(LEVEL_S * fs)))
    nb, rest = divmod(n, m)
    medians = np.empty(nb + (1 if rest else 0))
    if nb:
        medians[:nb] = np.median(np.asarray(x[: nb * m]).reshape(nb, m), axis=1)
    if rest:
        medians[nb] = np.median(np.asarray(x[nb * m:]))
    starts = np.arange(len(medians)) * m
    return 0.5 * (starts + np.minimum(starts + m, n) - 1), medians


def local_level(x: np.ndarray, fs: float) -> np.ndarray:
    """x's local level: the `LEVEL_S` block medians joined by straight lines (flat beyond the end blocks' centres)."""
    centres, medians = _blocks(x, fs)
    return np.interp(np.arange(len(x)), centres, medians)


def burst_ratio(x: np.ndarray, fs: float, min_len_s: float = 0.05) -> np.ndarray:
    """|x - local level| averaged over min_len_s, over the running MAD (`SCALE_S`) of x - level; float32.

    The MAD is the median, over the `SCALE_S` window centred on each block,
    of the blocks' own median |x - level| (the window shortened at the ends);
    an all-zero block (a zeroed gap) does not count, and a window with no
    other block gives a ratio of 0.
    """
    n = len(x)
    d = np.array(x, dtype="float64")  # one float64 copy, then in place (a 51 h run at 1000 Hz is 1.5 GB)
    d -= local_level(x, fs)
    np.abs(d, out=d)
    env = uniform_filter1d(d, max(1, int(round(min_len_s * fs))), mode="nearest", output=np.float32)
    _centres, mad = _blocks(d, fs)
    del d
    mad[mad <= 0] = np.nan
    half = int(round(SCALE_S / LEVEL_S)) // 2
    padded = np.concatenate([np.full(half, np.nan), mad, np.full(half, np.nan)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # an all-gap window
        scale = np.nanmedian(sliding_window_view(padded, 2 * half + 1), axis=1)
    scale = np.where(np.isfinite(scale), scale, np.inf).astype("float32")
    m = max(8, int(round(LEVEL_S * fs)))
    nb = n // m
    env[: nb * m].reshape(nb, m)[:] /= scale[:nb, None]
    if n > nb * m:
        env[nb * m:] /= scale[nb]
    return env


def detect_bursts(
    refs: list[np.ndarray], fs: float, threshold: float = 12.0, min_len_s: float = 0.05, pad_s: float = 0.1,
) -> np.ndarray:
    """(k, 2) int64 sample spans [start, stop), sorted and merged: where any `burst_ratio` of `refs`
    exceeds `threshold` for at least min_len_s (the run less the averaging's own widening, so a
    spike or a sferic never counts), widened by pad_s each side (clipped to the series)."""
    n = len(refs[0])
    hot = np.zeros(n, dtype=bool)
    for ref in refs:
        hot |= burst_ratio(ref, fs, min_len_s) > float(threshold)
    edges = np.flatnonzero(np.diff(np.concatenate(([False], hot, [False])).astype(np.int8)))
    starts, stops = edges[0::2], edges[1::2]
    # the average over min_len_s widens any excursion by min_len_s less a sample: a
    # single-sample spike (a sferic, the natural signal) is over the threshold for
    # exactly min_len_s. The excursion's own length is the run less that widening.
    width = max(1, int(round(min_len_s * fs)))
    keep = (stops - starts) - (width - 1) >= width
    pad = int(round(pad_s * fs))
    starts, stops = np.maximum(starts[keep] - pad, 0), np.minimum(stops[keep] + pad, n)
    if not len(starts):
        return np.empty((0, 2), dtype=np.int64)
    new = np.concatenate(([True], starts[1:] > np.maximum.accumulate(stops)[:-1]))
    return np.stack([starts[new], np.maximum.reduceat(stops, np.flatnonzero(new))], axis=1).astype(np.int64)


def fill_spans(x: np.ndarray, spans, fs: float, taper_s: float = 0.05) -> np.ndarray:
    """A float64 copy of x with every span set to x's `local_level`, a cosine taper of taper_s inside each end."""
    y = np.array(x, dtype="float64")
    centres, medians = _blocks(x, fs)
    taper = int(round(taper_s * fs))
    for a, b in spans:
        a, b = int(a), int(b)
        level = np.interp(np.arange(a, b), centres, medians)
        k = min(taper, (b - a) // 2)
        keep = np.zeros(b - a)
        if k:
            ramp = 0.5 * (1.0 + np.cos(np.pi * np.arange(k) / k))  # 1 at the span's edge, falling towards 0
            keep[:k], keep[b - a - k:] = ramp, ramp[::-1]
        y[a:b] = level + keep * (y[a:b] - level)
    return y


def _channels(opts: dict, comps: list[str]) -> list[str]:
    """The spec's `channels` (lower case) when it has the key, else every channel of the run."""
    chans = opts.get("channels")
    return [str(c).lower() for c in (comps if chans is None else chans)]


def _replace_from_donors(out: dict, spec: dict, donors: dict | None) -> list[str]:
    """`replace` on arrays: the donor's channel from `donors[site][comp]`, or a line saying why not."""
    lines, notes = [], []
    for comp, site in ((str(c).lower(), str(s)) for c, s in (spec or {}).items()):
        donor = (donors or {}).get(site) or {}
        if comp not in donor:
            lines.append(f"replace {comp}<-{site}: donor not loaded, skipped in preview")
        elif comp in out and len(donor[comp]) != len(out[comp]):
            lines.append(f"replace {comp}<-{site}: donor has {len(donor[comp])} samples, "
                         f"not {len(out[comp])}, skipped in preview")
        else:
            out[comp] = _read_only(donor[comp])
            notes.append(f"{comp} <- {site}")
    if notes:
        lines.insert(0, "replace magnetics: " + ", ".join(notes))
    return lines


def _read_only(a: np.ndarray) -> np.ndarray:
    """A view of `a` that cannot be written through (so an output never aliases a writable input)."""
    view = np.asarray(a).view()
    view.flags.writeable = False
    return view


def apply_filters_arrays(
    arrays: dict[str, np.ndarray],
    fs: float,
    filters: list[dict],
    tag: str = "",
    donors: dict | None = None,
    workers: int = 1,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Apply the declared filter list, in order, to plain arrays; the inputs are never modified.

    Returns (filtered, provenance): `filtered` has every key of `arrays`; a
    channel a filter touched is a new float64 array, one no filter touched
    is a read-only view of its input (no copy of a channel nobody filtered).
    `provenance` is one line per filter, as the archive's comments carry it.
    `replace` entries are applied first, from `donors[site][comp]` (see the
    module docstring); a donor not given is a provenance line, not an error.
    `workers` > 1 runs each filter's channels on that many threads (scipy's
    filters release the GIL): the GUI's preview asks for 4, ingest keeps 1
    so a 51 h run holds one channel's float64 temporaries at a time.
    """
    out = {c: _read_only(a) for c, a in arrays.items()}
    comps = list(arrays)
    lines: list[str] = []
    for spec in filters or []:
        if len(spec) != 1:
            raise ValueError(f"{tag}: each filter must be a single-key dict, got {spec}")
        if "replace" in spec:
            lines += _replace_from_donors(out, spec["replace"], donors)
    # period refinement (when asked for) reads the reference as recorded,
    # before any filter has touched it -- the input itself, never modified
    snapshots = dict(out)
    pool = ThreadPoolExecutor(int(workers)) if int(workers) > 1 else None

    def run(fn, chans):
        chans = [c for c in chans if c in out]
        inputs = [out[c] for c in chans]
        out.update(zip(chans, list((pool.map if pool else map)(fn, inputs))))

    try:
        for spec in filters or []:
            kind, opts = next(iter(spec.items()))
            opts = dict(opts or {})
            if kind == "replace":
                continue
            if kind == "notch":
                f0 = float(opts.get("f0", 50.0)); harmonics = int(opts.get("harmonics", 9)); q = float(opts.get("q", 30.0))
                passes = int(opts.get("passes", 2)); extra = list(opts.get("extra", []) or [])
                chans = _channels(opts, comps)
                run(lambda x: mains_notch(x, fs, f0, harmonics, q, passes, extra), chans)
                line = (
                    f"notch f0={f0:g} Hz harmonics={harmonics} q={q:g} passes={passes}"
                    + (f" extra={extra}" if extra else "") + f" zero-phase on {chans}"
                )
            elif kind == "mains":
                f0 = float(opts.get("f0", 50.0)); harmonics = int(opts.get("harmonics", 9))
                block_s = float(opts.get("block_s", 1.0)); frac = float(opts.get("step_fraction", 0.3))
                if not 0.0 < f0 < 0.5 * fs:
                    raise ValueError(f"{tag}: mains f0 {f0:g} Hz is not between 0 and Nyquist ({0.5 * fs:g} Hz)")
                if block_s <= 0.0 or frac <= 0.0:
                    raise ValueError(f"{tag}: mains block_s and step_fraction must be positive ({block_s:g}, {frac:g})")
                chans = _channels(opts, comps)
                done = [c for c in chans if c in out]
                results = list((pool.map if pool else map)(
                    lambda x: mains_subtract(x, fs, f0, harmonics, block_s, frac), [out[c] for c in done]))
                out.update((c, y) for c, (y, _info) in zip(done, results))
                infos = [info for _y, info in results]
                nh = sum(1 for k in range(1, harmonics + 1) if k * f0 < 0.5 * fs)
                offset = float(np.mean([info["offset_mean"] for info in infos])) if infos else 0.0
                line = (
                    f"mains: f0 {f0:g} Hz x{nh} harmonics fitted per {block_s:g} s block, tracked offset mean "
                    f"{offset:+.3f} Hz, {sum(len(info['steps']) for info in infos)} amplitude steps followed in all ("
                    + ", ".join(f"{c} {len(info['steps'])}" for c, info in zip(done, infos)) + f") on {chans}"
                )
            elif kind in ("hp", "lp"):
                if "cutoff_hz" not in opts:
                    raise ValueError(f"{tag}: {kind} needs a cutoff_hz (there is no default)")
                cutoff, order = float(opts["cutoff_hz"]), int(opts.get("order", 4))
                chans = _channels(opts, comps)
                btype = "highpass" if kind == "hp" else "lowpass"
                if not 0.0 < cutoff < 0.5 * fs:
                    raise ValueError(f"{tag}: {kind} cutoff {cutoff:g} Hz is not between 0 and Nyquist ({0.5 * fs:g} Hz)")
                run(lambda x: butterworth(x, fs, cutoff, order, btype), chans)
                line = f"{kind} {btype} {cutoff:g} Hz Butterworth order {order}, zero-phase (sosfiltfilt) on {chans}"
            elif kind == "cp":
                period = float(opts.get("period_s", 12.0)); wmin = float(opts.get("window_minutes", 10.0))
                chans = _channels(opts, comps)
                if opts.get("refine"):
                    ref = str(opts.get("reference", "ey")).lower()
                    if ref not in comps:
                        raise ValueError(f"{tag}: cp reference channel {ref!r} not in {comps}")
                    period = refine_period(snapshots[ref], fs, period)
                run(lambda x: cp_stack_subtract(x, fs, period, wmin), chans)
                line = (
                    f"cp stack-subtract: period {period:.5f} s, {wmin:g} min windows, median cycle removed on {chans}"
                )
            elif kind == "burst":
                thr = float(opts.get("threshold", 12.0)); min_len = float(opts.get("min_len_s", 0.05))
                pad = float(opts.get("pad_s", 0.1)); taper = float(opts.get("taper_s", 0.05))
                refs = opts.get("reference")
                refs = [str(c).lower() for c in ([c for c in ELECTRIC if c in comps] if refs is None else refs)]
                if not refs or any(r not in comps for r in refs):
                    raise ValueError(f"{tag}: burst reference {refs} is empty or not among {comps}")
                chans = _channels(opts, comps)
                spans = detect_bursts([out[r] for r in refs], fs, thr, min_len, pad)
                if len(spans):
                    run(lambda x: fill_spans(x, spans, fs, taper), chans)
                n = len(out[refs[0]])
                total = float(np.sum(spans[:, 1] - spans[:, 0])) / fs
                line = (
                    f"burst: {len(spans)} spans, {total:.2f} s total ({100.0 * total * fs / max(n, 1):.3f} % of the "
                    f"window), threshold {thr:g} x MAD on {refs}; min {min_len:g} s, pad {pad:g} s, "
                    f"taper {taper:g} s, set to the local level on {chans}"
                )
            elif kind == "flip":
                if "channels" not in opts:
                    raise ValueError(f"{tag}: flip needs `channels` (the ones wired reversed); there is no default")
                chans = _channels(opts, comps)
                if any(c not in comps for c in chans):
                    raise ValueError(f"{tag}: flip channels {chans} are not all among {comps}")
                run(lambda x: -np.asarray(x, dtype="float64"), chans)
                line = f"flip: sign reversed on {chans}"
            else:
                raise ValueError(f"{tag}: unknown filter kind {kind!r} (know: {', '.join(KINDS)})")
            logger.info(f"{tag}: applied {line}")
            lines.append(line)
    finally:
        if pool is not None:
            pool.shutdown()
    return out, lines


def apply_filters(run, filters: list[dict], fs: float, tag: str = "") -> list[str]:
    """Apply the declared filter list, in order, to run.dataset in place (the ingest path).

    `apply_filters_arrays` on the run's channels, one thread, and every
    channel a filter touched written back. Returns one provenance line per
    filter for the archive's comments. A `replace` entry is refused here:
    `ingest_site` applies it with `mtproc.ingest._replace_channels` first.
    """
    if any("replace" in spec for spec in filters or []):
        raise ValueError(f"{tag}: replace is applied by mtproc.ingest._replace_channels, not apply_filters")
    comps = list(run.dataset.data_vars)
    arrays = {c: run.dataset[c].data for c in comps}
    out, lines = apply_filters_arrays(arrays, fs, filters, tag=tag)
    for comp in comps:
        if not np.may_share_memory(out[comp], arrays[comp]):
            run.dataset[comp].data = out[comp]
    return lines
