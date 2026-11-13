# -*- coding: utf-8 -*-
"""
The Queensland health table's maths, ported as pure functions on arrays

Port of the health table of the Queensland inspection code, with its band
coherence, coherence map, fixed rotation and site loading. Per UTC week of
7 x 86400 s from the record's first sample and per channel group (H, Ex, Ey),
a week is sound or not by the Queensland thresholds (the constants block
below):

- H (hx, hy, hz together): |F| of the week's means of H as laid within
  `F_TOL` of the site's median weekly |F|; the fraction of hourly windows
  whose Hx-Hy coherence at 20-200 s exceeds `HXHY_HI_COH` below
  `HXHY_HI_MAX` (no common-mode noise); the week's median Hx-Hy coherence at
  most `HXHY_MED_MAX` (no leakage between the channels);
- Ex: the fraction of windows with Hy-Ex (Hx-Ex when swapped) coherence
  above `E_COH` at least `E_FRAC_MIN`; Ey likewise with Hx-Ey (Hy-Ey).

The coherences are taken on H rotated by the whole record's mean-field angle
(the fixed-rotation convention of the Queensland code) and E as laid; |F|
and the angle on H as laid.

Departures from the Queensland code, each forced by gaps the Queensland 1 Hz
cache never had (it refused a record with a gap over 600 s, so its windows
were all finite):

- a window holding any non-finite sample is NaN (as in the Queensland code) and
  is left out of every count and fraction: `n_windows`, the >= 24 rule and the
  fractions are over finite windows (Queensland counted every window slot and
  took ``nanmean(v > 0.5)``, which scores a NaN window as "not above"); the
  same for the ``swapped`` rule's whole-record fractions. On a gapless record
  the two are identical.
- `to_1hz` leaves a gap over `GAP_FILL_S` NaN (Queensland refused such a
  record) and marks NaN every 1 Hz sample whose decimation filter touches it.

A further departure:

- a per-component weekly check beside the Queensland rule, ``H_component_ok``:
  the week's medians of hx, hy, hz as laid (nT, DC level in) against the
  site's medians of the weekly medians, each deviation normalised by the
  field the component belongs to: ``hx_dev = |hx_week - hx_site| / |H|_site``,
  ``hy_dev = |hy_week - hy_site| / |H|_site``, ``hz_dev = |hz_week - hz_site|
  / |hz_site|``, with ``|H|_site = hypot(hx_site, hy_site)``; sound when all
  three are at most `COMPONENT_TOL`. The |F| rule was tuned at Queensland
  inclinations; at SA's -66 to -70 deg |F| is dominated by hz and an 8 % hx
  fault moves it by about 1 %. A ratio of each component to its own level
  would not serve: a sensor aligned with the
  field has hy of tens of nT, and a few nT of drift then reads as several %.
  ``H_ok`` is unchanged (the Queensland rule); the flag is its own field.

Kept as in the Queensland code:

- no head/tail trim: Queensland's 1 Hz cache started 6 h after the usable
  coverage and stopped 1 h before its end; this is a weekly table on the whole
  archived record, and the processing window handles the head;
- a window is used only when all five channels are finite (EDL channels gap
  together), so a gap in E alone also costs H that window;
- a short last week counts when it holds at least `MIN_WINDOWS` windows.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import numpy as np

# ------------------------------------------------------------------ the Queensland constants (one block)
WEEK_S = 7 * 86400          # a week, from the record's first sample (not calendar weeks)
WIN_S = 3600                # coherence window (qld_salvage.band_coh)
STEP_S = 1800               # its step
BAND_S = (20.0, 200.0)      # the coherence band, s
PER_DECADE = 8              # log bins per decade (coherence_map)
MIN_WINDOWS = 24            # a week counts with at least this many (finite) windows
F_TOL = 0.05                # |F| within 5 % of the site's median weekly |F|
HXHY_HI_COH = 0.9           # an Hx-Hy window "high" above this coherence
HXHY_HI_MAX = 0.3           # H sound only when the fraction of high windows is below this
HXHY_MED_MAX = 0.5          # H sound only when the week's median Hx-Hy coherence is at most this
E_COH = 0.5                 # an H-E window "coherent" above this
E_FRAC_MIN = 0.3            # E sound when at least this fraction of the week's windows is coherent
SWAP_MARGIN = 0.15          # the swapped rule's margin
GAP_FILL_S = 600.0          # to_1hz fills gaps up to this long by linear interpolation
F_IGRF_BAND = (0.9, 1.1)    # a dead fluxgate reads a steady near-zero F and passes the Queensland
                            # median-F test; with the site's IGRF F given, H_ok also needs F / F_igrf inside this band
CENTRE_EXEY_MIN = 0.7       # both E lines unsound in a week and their median Ex-Ey coherence at or above
                            # this = the centre-electrode class (NF41_2 reads 0.96; set from the census, provisional)
H_IGRF_BAND = (0.8, 1.2)    # the pair-only verdict Hpair_ok needs |H| (hypot of the week's hx and
                            # hy medians) inside this band of the IGRF H when it is given; no hz term
COMPONENT_TOL = 0.05        # departure: weekly hx, hy deviation <= 5 % of |H|_site, hz deviation <= 5 % of |hz_site|


def _auto_nperseg(win_n: int, min_segments: int = 4) -> int:
    """``qld_student.auto_nperseg``: the largest power of 2 giving `min_segments` segments."""
    return int(2 ** np.floor(np.log2(win_n / min_segments)))


def hourly_pair_coherence(x, y, fs: float = 1.0, lo: float = 20.0, hi: float = 200.0):
    """Return the band-mean coherence of two series per hourly window (``qld_salvage.band_coh``).

    ``coherence_map`` with win_s `WIN_S`, step_s `STEP_S`, nperseg auto
    (512 at 1 Hz), `PER_DECADE` log bins over [lo, hi] s, the mean over each
    bin's harmonics, empty bins dropped, then the mean over the bins. Each
    window's means are removed before ``scipy.signal.coherence`` (Welch,
    Hann, 50 % overlap). A window with any non-finite sample is NaN.

    Args:
        x, y (array): The two series, same rate.
        fs (float): Sample rate in Hz (the Queensland table ran at 1 Hz).
        lo, hi (float): Band edges in s.

    Returns:
        tuple: ``(centres_s, values)``: window centres in s from sample 0 and
        the band-mean coherence (NaN for a voided window).
    """
    from scipy.signal import coherence

    win = int(round(WIN_S * fs))
    step = int(round(STEP_S * fs))
    nperseg = _auto_nperseg(win)
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = min(len(x), len(y))
    starts = np.arange(0, n - win + 1, step)
    f = np.fft.rfftfreq(nperseg, 1 / fs)[1:]
    periods = 1 / f
    edges = np.geomspace(lo, hi, int(round(np.log10(hi / lo) * PER_DECADE)) + 1)
    nbin = len(edges) - 1
    idx = np.digitize(periods, edges) - 1
    ok = (idx >= 0) & (idx < nbin)
    cnt = np.bincount(idx[ok], minlength=nbin).astype(float)
    populated = cnt > 0
    out = np.full(len(starts), np.nan)
    for k, s in enumerate(starts):
        xs = x[s:s + win]
        ys = y[s:s + win]
        if not (np.isfinite(xs).all() and np.isfinite(ys).all()):
            continue
        _, c = coherence(xs - xs.mean(), ys - ys.mean(), fs=fs, nperseg=nperseg)
        c = c[1:]
        acc = np.bincount(idx[ok], weights=c[ok], minlength=nbin)
        out[k] = float(np.mean(acc[populated] / cnt[populated]))
    return (starts + win / 2.0) / fs, out


def mean_field_angle(hx, hy) -> float:
    """Return the mean horizontal field's angle, atan2(mean hy, mean hx) in degrees (``qld_campaign.rotate``).

    NaN samples are ignored (``nanmean``, as Queensland).
    """
    return float(np.degrees(np.arctan2(np.nanmean(hy), np.nanmean(hx))))


def rotate_h(hx, hy, angle_deg: float):
    """Rotate (hx, hy) by an angle, ``rotate_fixed``'s convention: Hx' = c hx + s hy, Hy' = -s hx + c hy.

    Rotating by `mean_field_angle` puts the mean horizontal field on Hx'.

    Returns:
        tuple: ``(hx_rotated, hy_rotated)``.
    """
    c, s = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    hx = np.asarray(hx, float)
    hy = np.asarray(hy, float)
    return c * hx + s * hy, -s * hx + c * hy


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return the [start, stop) runs of True in a boolean array."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate(([0], mask.view(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def to_1hz(x, fs: float, gaps=None, max_fill_s: float | None = None) -> np.ndarray:
    """Prepare one channel at 1 Hz the way the Queensland 1 Hz cache did.

    Every gap (non-finite samples, plus the [start, stop) sample ranges in
    `gaps`) is filled by linear interpolation (``np.interp``, as
    ``qld_campaign.read_native``); a gap longer than `max_fill_s`
    (`GAP_FILL_S`, 600 s, Queensland's ``MAX_GAP_S``) is marked to be NaN
    afterwards. A 1 Hz record is then returned as is. A higher integer rate
    is decimated by ``scipy.signal.decimate(x, q, ftype="fir",
    zero_phase=True)``, the cache's own call (``qld_campaign.cache_1hz``):
    a Hamming ``firwin(20 q + 1, 1 / q)`` applied by ``resample_poly``, zero
    phase, output sample k at input sample k q. A 1 Hz sample whose filter
    support (10 q input samples either side) touches a long gap is NaN.

    Args:
        x (array): One channel at `fs`, NaN in gaps.
        fs (float): Its sample rate; must be an integer number of Hz.
        gaps (list of tuple, optional): Extra [start, stop) sample ranges with no data.
        max_fill_s (float, optional): Longest gap filled, s (`GAP_FILL_S`).

    Returns:
        np.ndarray: float64 at 1 Hz, ceil(len(x) / q) samples.

    Raises:
        ValueError: If `fs` is not a positive integer.
    """
    from scipy.signal import decimate

    q = int(round(fs))
    if q < 1 or abs(fs - q) > 1e-9:
        raise ValueError(f"to_1hz: sample rate {fs} Hz is not an integer number of Hz")
    max_fill = GAP_FILL_S if max_fill_s is None else max_fill_s
    v = np.array(x, dtype="float64")
    for a, b in gaps or ():
        v[int(a):int(b)] = np.nan
    bad = ~np.isfinite(v)
    if bad.all():
        return np.full(-(-v.size // q), np.nan)
    long = np.zeros(v.size, bool)
    if bad.any():
        for a, b in _runs(bad):
            if (b - a) / fs > max_fill:
                long[a:b] = True
        idx = np.arange(v.size)
        v[bad] = np.interp(idx[bad], idx[~bad], v[~bad])
    if q == 1:
        v[long] = np.nan
        return v
    y = decimate(v, q, ftype="fir", zero_phase=True)
    if long.any():
        half = 10 * q                          # decimate's default FIR: n = 20 q taps + 1
        c = np.concatenate(([0], np.cumsum(long)))
        lo = np.clip(np.arange(v.size) - half, 0, v.size)
        hi = np.clip(np.arange(v.size) + half + 1, 0, v.size)
        touched = (c[hi] - c[lo]) > 0
        y[touched[::q][:y.size]] = np.nan
    return y


def _frac(v: np.ndarray, thr: float) -> float:
    """Fraction of the finite values above `thr` (NaN when none is finite)."""
    f = v[np.isfinite(v)]
    return float(np.mean(f > thr)) if f.size else float("nan")


def health_record(t0, fs: float, hx, hy, hz, ex, ey, f_igrf: float | None = None,
                  h_igrf: float | None = None, e_dirs: tuple[float, float] | None = None) -> dict:
    """Evaluate a record: the weeks and the record-level facts.

    Args:
        t0: Time of sample 0 (carried into ``t_start``/``t_end`` of each week
            as ``t0 + offset``; a pandas Timestamp gets a Timedelta).
        fs (float): Sample rate of the arrays (1 Hz after `to_1hz`).
        hx, hy, hz (array): H as laid, in nT (mean levels kept: |F| uses them). hz may be
            None or all NaN (an archive without hz): F and the hz fields are then NaN,
            ``hz_present`` False and ``H_ok`` False; ``Hpair_ok`` and the E verdicts stand.
        ex, ey (array): E as laid.
        f_igrf (float, optional): The IGRF F at the site and epoch, nT. When given,
            every week also carries ``F_igrf_ratio`` and ``F_igrf_ok`` (`F_IGRF_BAND`)
            and ``H_ok`` requires ``F_igrf_ok``: the Queensland rule alone cannot see a
            dead sensor. None keeps the Queensland verdict exactly.
        h_igrf (float, optional): The IGRF horizontal intensity H at the site and epoch, nT.
            Every week carries ``H_pair`` (hypot of the week's hx and hy
            medians), ``H_igrf_ratio`` and ``Hpair_ok``: the Hx-Hy rules (hxhy_hi, hxhy_med)
            and, when `h_igrf` is given, ``H_pair / h_igrf`` inside `H_IGRF_BAND`; no hz
            term, so a dead hz under a sound pair keeps its impedance verdict (the tipper
            keeps ``H_ok``). Without `h_igrf` Hpair_ok is the two Hx-Hy rules alone. With
            `h_igrf` given ``H_ok`` also requires the pair's ratio in the band (a dead pair
            under a live hz passes the F rules at SA inclinations, F/F_igrf ~0.93), so
            H_ok implies Hpair_ok; without it H_ok is the Queensland rule.
        e_dirs (tuple, optional): The directions (deg, in the archive's H frame) along which
            `ex` and `ey` measure, when they are not 0 and 90: the lines as recorded at a
            rot_e site (scripts/health_table.py `recorded_e`). Each line is then
            paired with H turned by the mean-field angle plus its own departure from its
            nominal azimuth (ex: b_x - 0, ey: b_y - 90), so the line's partner is the H
            component perpendicular to it (Hy' for ex, Hx' for ey) and its swapped-test
            partner the parallel one, as at a cardinal site. The H rules and the Ex-Ey
            coherence are unchanged. None or (0, 90) keeps the Queensland pairing exactly.

    Returns:
        dict: ``weeks`` (see `weekly_health`), ``e_swapped``, ``angle`` (the
        whole-record mean-field angle the coherences used), ``n`` (samples),
        ``windows_total`` (window slots in the record), ``windows_finite``,
        ``windows_used`` (finite windows in the weeks that count), ``fmed``.
    """
    hx = np.asarray(hx, float)
    hy = np.asarray(hy, float)
    # an archive without hz (a dead hz left out at ingest): hz None or all NaN;
    # F and the hz fields are NaN, H_ok False, the pair verdict and the E verdicts are computed as usual
    hz = np.full(len(hx), np.nan) if hz is None else np.asarray(hz, float)
    has_hz = bool(np.isfinite(hz).any())
    n = min(len(hx), len(hy), len(hz), len(ex), len(ey))
    ang = mean_field_angle(hx, hy)
    rx, ry = rotate_h(hx, hy, ang)
    loc = {"Hx": rx, "Hy": ry, "Ex": np.asarray(ex, float), "Ey": np.asarray(ey, float)}
    # the H each E line pairs with: the record's mean-field frame, turned further by the line's departure from its
    # nominal azimuth when the lines are judged as recorded; at a cardinal pair both are the Queensland H
    h_for = {"Ex": (rx, ry), "Ey": (rx, ry)}
    if e_dirs is not None:
        for comp, b, nominal in (("Ex", e_dirs[0], 0.0), ("Ey", e_dirs[1], 90.0)):
            off = ((float(b) - nominal) + 180.0) % 360.0 - 180.0
            if off != 0.0:
                h_for[comp] = rotate_h(hx, hy, ang + off)
    fr = {}
    tc = None
    for a, b in (("Hx", "Ey"), ("Hy", "Ex"), ("Hx", "Ex"), ("Hy", "Ey"), ("Ex", "Ey"), ("Hx", "Hy")):
        ha = h_for[b][0 if a == "Hx" else 1] if (b in h_for and a in ("Hx", "Hy")) else loc[a]
        tc, v = hourly_pair_coherence(ha[:n], loc[b][:n], fs, BAND_S[0], BAND_S[1])
        fr[a + b] = v
    swapped = bool((_frac(fr["HxEx"], E_COH) > _frac(fr["HxEy"], E_COH) + SWAP_MARGIN)
                   and (_frac(fr["HyEy"], E_COH) > _frac(fr["HyEx"], E_COH) + SWAP_MARGIN))
    finite = np.isfinite(fr["HxHy"])
    for v in fr.values():
        finite &= np.isfinite(v)
    week = int(round(WEEK_S * fs))
    weeks = []
    for w0 in range(0, n, week):
        w1 = min(n, w0 + week)
        m = (tc * fs >= w0) & (tc * fs < w1) & finite
        if m.sum() < MIN_WINDOWS:
            continue
        x, y = np.nanmean(hx[w0:w1]), np.nanmean(hy[w0:w1])
        z = np.nanmean(hz[w0:w1]) if has_hz and np.isfinite(hz[w0:w1]).any() else np.nan
        exv = (fr["HxEx"] if swapped else fr["HyEx"])[m]
        eyv = (fr["HyEy"] if swapped else fr["HxEy"])[m]
        hh = fr["HxHy"][m]
        s0, s1 = w0 / fs, w1 / fs
        weeks.append(dict(start=s0, end=s1, F=float(np.sqrt(x * x + y * y + z * z)),
                          angle=float(np.degrees(np.arctan2(y, x))),
                          hxhy_hi=float(np.mean(hh > HXHY_HI_COH)), hxhy_med=float(np.median(hh)),
                          exey_med=float(np.median(fr["ExEy"][m])),
                          ex=float(np.mean(exv > E_COH)), ey=float(np.mean(eyv > E_COH)),
                          n_windows=int(m.sum()), e_swapped=swapped,
                          hx_med=float(np.nanmedian(hx[w0:w1])), hy_med=float(np.nanmedian(hy[w0:w1])),
                          hz_med=float(np.nanmedian(hz[w0:w1])) if np.isfinite(z) else float("nan"),
                          hz_present=has_hz,
                          t_start=_add(t0, s0), t_end=_add(t0, s1)))
    fmed = float(np.median([w["F"] for w in weeks])) if weeks and has_hz else float("nan")
    cmed = {c: float(np.median([w[c + "_med"] for w in weeks])) if weeks and (has_hz or c != "hz") else float("nan")
            for c in ("hx", "hy", "hz")}
    h_site = float(np.hypot(cmed["hx"], cmed["hy"]))
    norm = {"hx": h_site, "hy": h_site, "hz": abs(cmed["hz"])}
    for w in weeks:
        for c in ("hx", "hy", "hz"):
            w[c + "_dev"] = abs(w[c + "_med"] - cmed[c]) / norm[c]
        w["H_component_ok"] = bool(all(w[c + "_dev"] <= COMPONENT_TOL for c in ("hx", "hy", "hz")))
        w["F_igrf_ratio"] = float(w["F"] / f_igrf) if f_igrf else float("nan")
        w["F_igrf_ok"] = bool(F_IGRF_BAND[0] <= w["F_igrf_ratio"] <= F_IGRF_BAND[1]) if f_igrf else True
        # the pair-only verdict (Hx-Hy rules, |H| against the IGRF H; no hz term)
        w["H_pair"] = float(np.hypot(w["hx_med"], w["hy_med"]))
        w["H_igrf_ratio"] = float(w["H_pair"] / h_igrf) if h_igrf else float("nan")
        h_pair_igrf_ok = bool(H_IGRF_BAND[0] <= w["H_igrf_ratio"] <= H_IGRF_BAND[1]) if h_igrf else True
        w["Hpair_ok"] = bool(w["hxhy_hi"] < HXHY_HI_MAX and w["hxhy_med"] <= HXHY_MED_MAX and h_pair_igrf_ok)
        # H_ok also needs the pair's |H| when the IGRF H is given: at SA inclinations (-66 to
        # -70 deg) hz carries ~93 % of F, so a dead pair under a live hz reads F/F_igrf ~0.93, inside F_IGRF_BAND
        w["H_ok"] = bool(has_hz and abs(w["F"] - fmed) <= F_TOL * fmed and w["hxhy_hi"] < HXHY_HI_MAX
                         and w["hxhy_med"] <= HXHY_MED_MAX and w["F_igrf_ok"] and h_pair_igrf_ok)
        w["Ex_ok"] = bool(w["ex"] >= E_FRAC_MIN)
        w["Ey_ok"] = bool(w["ey"] >= E_FRAC_MIN)
        # a noisy or open centre electrode puts one voltage on both lines: neither pairs with H, both
        # pair with each other; the week is a candidate for the diagonal line (scripts/diagonal_site.py)
        w["centre_flag"] = bool(not w["Ex_ok"] and not w["Ey_ok"] and w["exey_med"] >= CENTRE_EXEY_MIN)
    return dict(weeks=weeks, e_swapped=swapped, angle=ang, n=n, fmed=fmed,
                windows_total=int(len(tc)), windows_finite=int(finite.sum()),
                windows_used=int(sum(w["n_windows"] for w in weeks)))


def _add(t0, seconds: float):
    """t0 + seconds, a Timedelta for a pandas/np datetime, plain addition for a number."""
    if isinstance(t0, (int, float, np.integer, np.floating)):
        return t0 + seconds
    import pandas as pd
    return pd.Timestamp(t0) + pd.Timedelta(seconds=seconds)


def weekly_health(t0, fs: float, hx, hy, hz, ex, ey, f_igrf: float | None = None,
                  h_igrf: float | None = None, e_dirs: tuple[float, float] | None = None) -> list[dict]:
    """Return the record's weeks, each a dict of the Queensland fields.

    ``start``, ``end`` (s from sample 0), ``F`` (nT), ``angle`` (deg, the
    week's means of H as laid), ``hxhy_hi``, ``hxhy_med``, ``ex``, ``ey``,
    ``H_ok``, ``Ex_ok``, ``Ey_ok``; plus the departure's ``hx_med``,
    ``hy_med``, ``hz_med`` (nT), ``hx_dev``, ``hy_dev``, ``hz_dev`` and
    ``H_component_ok``; plus ``H_pair``, ``H_igrf_ratio`` and ``Hpair_ok``; plus ``n_windows`` (finite windows
    whose centre falls in the week), ``e_swapped`` (the record's) and
    ``t_start``/``t_end`` (t0 + start/end). See `health_record`.
    """
    return health_record(t0, fs, hx, hy, hz, ex, ey, f_igrf=f_igrf, h_igrf=h_igrf, e_dirs=e_dirs)["weeks"]
