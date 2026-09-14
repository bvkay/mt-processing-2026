"""Declared, per-site time-domain noise filters applied at ingest.

Nothing here is automatic. A student sees the problem in the QC figures
(`scripts/site_qc.py`: the 50 Hz line in the spectrogram, the 12 s square wave
in the overview, the comb in the PSD) and declares a filter list for that site
in `<survey>/filters.yaml`; `ingest_site` applies the list in the declared
order on the raw counts and records it in the archive.

Order matters (Ben, 2026-09-22): mains first, so the cathodic-protection
edges are timed on a cleaner series. Prototypes and numbers:
`docs/prototypes/cp_recipe_notch_first.py`, `surveys/burra/qc_notes.md`.

Filter specs (one dict each, keyed by kind):

    - notch: {f0: 50.0, harmonics: 9, q: 30.0, passes: 2, extra: [75, 125]}
        zero-phase IIR notch at f0 and its harmonics below Nyquist (plus any
        `extra` lines a site shows), all channels, applied `passes` times
        (two by default: the grid wanders +-0.1 Hz and one pass leaves ~7 dB).
    - cp: {period_s: 12.0, window_minutes: 10, channels: [ex, ey, hx, hy],
           refine: false, reference: ey}
        cathodic protection (a strictly periodic interference): in every
        window, stack all cycles at the fixed period and subtract the median
        cycle from each channel. No edge detection, no cutting. `refine: true`
        measures the period from the reference channel's autocorrelation
        (needed only when the declared period is not known to ~0.1 ms).

Why this and not a detector: on 12 h of Burra35 the plain stack raised coil
coherence with the remote from 0.49 to 0.71 (0.3-2 s) and left 0.05-0.3 s
untouched, while any excision around the edges (+-0.2 to 0.5 s, straight-line
bridging twice a cycle) pushed it below raw. The interrupter is crystal-locked
(12.0000 s to a few hundredths of a ms), so a fixed period folds exactly.
"""

from __future__ import annotations

import numpy as np
from loguru import logger
from scipy.signal import butter, decimate, iirnotch, sosfiltfilt, tf2sos

ELECTRIC = ("ex", "ey")


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
    """Ben's fold: in each window, stack every cycle at the fixed period and
    subtract the median cycle. Phase is free per window, so nothing needs
    detecting; the natural field averages down by sqrt(cycles per window)."""
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


def apply_filters(run, filters: list[dict], fs: float, tag: str = "") -> list[str]:
    """Apply the declared filter list, in order, to run.dataset in place.

    Returns one provenance line per filter for the archive's comments.
    """
    lines: list[str] = []
    comps = list(run.dataset.data_vars)
    # period refinement (when asked for) reads the reference as recorded,
    # before any filter has touched it
    snapshots = {}
    for spec in filters or []:
        if "cp" in spec and (spec["cp"] or {}).get("refine"):
            ref = str((spec["cp"] or {}).get("reference", "ey")).lower()
            if ref in comps and ref not in snapshots:
                snapshots[ref] = np.array(run.dataset[ref].data, dtype="float64", copy=True)
    for spec in filters or []:
        if len(spec) != 1:
            raise ValueError(f"{tag}: each filter must be a single-key dict, got {spec}")
        kind, opts = next(iter(spec.items()))
        opts = dict(opts or {})
        if kind == "notch":
            f0 = float(opts.get("f0", 50.0)); harmonics = int(opts.get("harmonics", 9)); q = float(opts.get("q", 30.0))
            passes = int(opts.get("passes", 2)); extra = list(opts.get("extra", []) or [])
            for comp in comps:
                run.dataset[comp].data = mains_notch(run.dataset[comp].data, fs, f0, harmonics, q, passes, extra)
            line = (
                f"notch f0={f0:g} Hz harmonics={harmonics} q={q:g} passes={passes}"
                + (f" extra={extra}" if extra else "") + f" zero-phase on {comps}"
            )
        elif kind == "cp":
            period = float(opts.get("period_s", 12.0)); wmin = float(opts.get("window_minutes", 10.0))
            chans = [c.lower() for c in opts.get("channels", comps)]
            if opts.get("refine"):
                ref = str(opts.get("reference", "ey")).lower()
                if ref not in comps:
                    raise ValueError(f"{tag}: cp reference channel {ref!r} not in {comps}")
                period = refine_period(snapshots.get(ref, run.dataset[ref].data), fs, period)
            for comp in chans:
                if comp in comps:
                    run.dataset[comp].data = cp_stack_subtract(run.dataset[comp].data, fs, period, wmin)
            line = (
                f"cp stack-subtract: period {period:.5f} s, {wmin:g} min windows, median cycle removed on {chans}"
            )
        else:
            raise ValueError(f"{tag}: unknown filter kind {kind!r} (know: notch, cp)")
        logger.info(f"{tag}: applied {line}")
        lines.append(line)
    return lines
