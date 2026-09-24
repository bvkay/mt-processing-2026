# -*- coding: utf-8 -*-
"""
Quality numbers for one transfer function and agreement between two

The numbers rank and flag the many processing runs of one site made by
scripts/campaign.py (every remote, stacks, estimator options); the plots
remain the basis for judging a result. All values are read through
`mtproc.compare.rho_phi` (apparent resistivity, phase and their 1-sigma
errors from the EDI impedance and variances), so a TF object and an EDI path
are handled alike.

`tf_quality(edi, pmin, pmax)`, per mode (xy = Zxy, yx = Zyx) over the periods in
[pmin, pmax] (all of them when not given):

- ``quadrant_frac``: the fraction of the periods whose phase lies in the
  mode's physical quadrant (`mtproc.compare.QUADRANTS`: xy in (0, 90) deg,
  yx in (-180, -90) deg). A period with no finite, positive rho or no finite
  phase counts as *out*, so missing periods lower it too.
- ``median_rel_err``: median of rho_err / rho over the periods whose error
  bar is finite and positive (NaN when the EDI carries no variances).
- ``roughness``: median |dlog10 rho| between adjacent valid periods.
- ``smoothness``: the mean over those adjacent steps s_k of exp(-(s_k / 0.25)**2).
- ``blowups``: the number of periods with rho > 1e5 or < 1e-2 ohm m.
- ``score`` in [0, 1], higher is better::

      score = Q * S * exp(-5 * B / N)

  with Q the quadrant fraction, S the smoothness, B the blow-ups and N the
  periods in the window. The score is 0 when S is undefined, that is with
  fewer than two valid periods. Each factor is a per-period (per-step)
  average, so a noisy band costs score in proportion to its width. The
  roughness enters through S rather than through its median, because the
  median ignores noise confined to fewer than half of the steps, and a dead
  band a decade or two wide, which is what separates one remote from
  another, is noise of that kind. In tests/quality_unit.py (5), 13 noisy
  periods of 61 cost 0.06 of score through the median and 0.15 through S.
  The per-step term is flat near zero: a smooth curve steps 0.03-0.06 dex
  between adjacent bands at 8-12 bands per decade, which costs under 0.06
  of S, so band density alone barely moves it; a step of 0.3 dex keeps 0.24
  of its share and one of 0.5 dex keeps 0.02. One blow-up in 60 periods
  costs 8 %. The error bars are reported but not scored, since their size
  depends on the estimator settings being compared (more overlap gives more
  correlated windows and smaller bars) as well as on the data.

``overall``: Q is the mean of the two modes', the relative error and the
roughness are medians over both modes' values pooled, the blow-ups a sum, and
the score the mean of the two modes' scores.

`agreement(a, b)`: over the periods the two TFs share (equal to 2 %), per
mode the median |dlog10 rho| and the median |dphase| (deg, wrapped to
[0, 180]), and pooled over both modes in ``overall``.

`pairwise_spread(tfs)`: per period of the first TF, per mode, the median over
every pair of TFs of |dlog10 rho| and |dphase|, showing where several remotes
agree and where they differ.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import numpy as np

from .compare import QUADRANTS, rho_phi

MODES = {"xy": (0, 1), "yx": (1, 0)}
RHO_HIGH = 1e5  # ohm m: above this a period is a blow-up
RHO_LOW = 1e-2  # ohm m: below this too
ROUGHNESS_SCALE = 0.25  # dex: the adjacent step whose smoothness term is exp(-1)
BLOWUP_WEIGHT = 5.0  # score *= exp(-BLOWUP_WEIGHT * blow-up fraction)
PERIOD_RTOL = 0.02  # two periods are "the same" within 2 %


@lru_cache(maxsize=512)
def _curves_cached(path: str, mtime_ns: int):
    """Return `rho_phi` of an EDI path, cached on path and modification time."""
    return rho_phi(path)


def curves(tf_or_path):
    """Return `rho_phi` of an EDI path or a TF object.

    Results for a path are cached per path and modification time; a TF
    object is converted on every call.
    """
    if isinstance(tf_or_path, (str, Path)):
        p = Path(tf_or_path)
        return _curves_cached(str(p), p.stat().st_mtime_ns)
    return rho_phi(tf_or_path)


def _window(period: np.ndarray, pmin=None, pmax=None) -> np.ndarray:
    """Boolean selection of the periods in [pmin, pmax], either bound optional."""
    sel = np.ones(period.size, dtype=bool)
    if pmin is not None:
        sel &= period >= float(pmin) * (1.0 - 1e-9)
    if pmax is not None:
        sel &= period <= float(pmax) * (1.0 + 1e-9)
    return sel


def in_quadrant(phase_deg: np.ndarray, mode: str) -> np.ndarray:
    """Flag phases strictly inside the physical quadrant of a mode.

    Args:
        phase_deg (np.ndarray): Phases in degrees, as np.angle returns them.
        mode (str): ``"xy"`` or ``"yx"``.

    Returns:
        np.ndarray: Boolean array, False for non-finite phases.
    """
    lo, hi = QUADRANTS[mode]
    phase_deg = np.asarray(phase_deg, dtype=float)
    return np.isfinite(phase_deg) & (phase_deg > lo) & (phase_deg < hi)


def smoothness(steps) -> float:
    """Return the mean of exp(-(step / 0.25)**2) over adjacent |dlog10 rho| steps.

    Non-finite steps are ignored. Returns NaN when there are no steps.
    """
    steps = np.asarray(steps, dtype=float)
    steps = steps[np.isfinite(steps)]
    return float(np.mean(np.exp(-((steps / ROUGHNESS_SCALE) ** 2)))) if steps.size else float("nan")


def combined_score(quadrant_frac: float, smooth: float, blowups: int, n_periods: int) -> float:
    """Combine quality factors into a score in [0, 1].

    Args:
        quadrant_frac (float): Q, the fraction of periods in quadrant.
        smooth (float): S, the smoothness.
        blowups (int): B, the number of blow-up periods.
        n_periods (int): N, the number of periods in the window.

    Returns:
        float: Q * S * exp(-5 * B / N), clipped to [0, 1]; 0 when Q or S is
        undefined or N is 0.
    """
    if n_periods <= 0 or not np.isfinite(smooth) or not np.isfinite(quadrant_frac):
        return 0.0
    s = float(quadrant_frac) * float(smooth) * np.exp(-BLOWUP_WEIGHT * float(blowups) / float(n_periods))
    return float(min(1.0, max(0.0, s)))


def _median(values) -> float:
    """Median of the finite values; NaN when there are none."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(np.median(values)) if values.size else float("nan")


def tf_quality(edi_path, pmin=None, pmax=None) -> dict:
    """Compute the per-mode and overall quality of one TF.

    The rules are given in the module docstring.

    Args:
        edi_path (str or Path or TF): EDI path or TF object.
        pmin (float, optional): Shortest period in s; all periods when None.
        pmax (float, optional): Longest period in s; all periods when None.

    Returns:
        dict: ``{"xy": {...}, "yx": {...}, "overall": {...}, "n_periods",
        "pmin", "pmax", "period_min", "period_max"}``. Each mode dict holds
        ``quadrant_frac``, ``median_rel_err``, ``roughness``,
        ``smoothness``, ``blowups``, ``n_valid`` and ``score``.
    """
    period, rho, phi, rho_err, _ = curves(edi_path)
    sel = _window(period, pmin, pmax)
    n = int(sel.sum())
    out = {
        "n_periods": n,
        "pmin": None if pmin is None else float(pmin),
        "pmax": None if pmax is None else float(pmax),
        "period_min": float(period[sel].min()) if n else float("nan"),
        "period_max": float(period[sel].max()) if n else float("nan"),
    }
    pooled_rel, pooled_steps, scores, quads, blows = [], [], [], [], 0
    for mode, (i, j) in MODES.items():
        r = rho[sel, i, j]
        ph = phi[sel, i, j]
        e = rho_err[sel, i, j]
        valid = np.isfinite(r) & (r > 0) & np.isfinite(ph)
        q = float((valid & in_quadrant(ph, mode)).sum() / n) if n else float("nan")
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = e[valid] / r[valid]
        rel = rel[np.isfinite(rel) & (rel > 0)]
        steps = np.abs(np.diff(np.log10(r[valid]))) if valid.sum() >= 2 else np.array([])
        rough = _median(steps)
        smooth = smoothness(steps)
        b = int((valid & ((r > RHO_HIGH) | (r < RHO_LOW))).sum())
        score = combined_score(q, smooth, b, n)
        out[mode] = {
            "quadrant_frac": q,
            "median_rel_err": _median(rel),
            "roughness": rough,
            "smoothness": smooth,
            "blowups": b,
            "n_valid": int(valid.sum()),
            "score": score,
        }
        pooled_rel.append(rel)
        pooled_steps.append(steps)
        scores.append(score)
        quads.append(q)
        blows += b
    out["overall"] = {
        "quadrant_frac": float(np.mean(quads)) if n else float("nan"),
        "median_rel_err": _median(np.concatenate(pooled_rel)),
        "roughness": _median(np.concatenate(pooled_steps)),
        "smoothness": smoothness(np.concatenate(pooled_steps)),
        "blowups": blows,
        "n_valid": out["xy"]["n_valid"] + out["yx"]["n_valid"],
        "score": float(np.mean(scores)),
    }
    return out


def flat_quality(q: dict) -> dict:
    """Flatten a `tf_quality` result into one row.

    Args:
        q (dict): Result of `tf_quality`.

    Returns:
        dict: ``score`` and ``n_periods``, then ``<mode>_<key>`` for
        overall, xy and yx.
    """
    row = {"score": q["overall"]["score"], "n_periods": q["n_periods"]}
    for mode in ("overall", "xy", "yx"):
        for key, value in q[mode].items():
            row[f"{mode}_{key}"] = value
    return row


def match_periods(pa: np.ndarray, pb: np.ndarray, rtol: float = PERIOD_RTOL) -> tuple[np.ndarray, np.ndarray]:
    """Match two period arrays within a relative tolerance.

    Each period of `pa` is paired with the nearest period of `pb` in log
    space, and the pair is kept when the two agree to within `rtol`.

    Args:
        pa (np.ndarray): First periods.
        pb (np.ndarray): Second periods.
        rtol (float): Relative tolerance (default 2 %).

    Returns:
        tuple: ``(ia, ib)`` index arrays into `pa` and `pb`.
    """
    pa = np.asarray(pa, dtype=float)
    pb = np.asarray(pb, dtype=float)
    if pa.size == 0 or pb.size == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    la, lb = np.log(pa), np.log(pb)
    ib = np.abs(la[:, None] - lb[None, :]).argmin(axis=1)
    ok = np.abs(la - lb[ib]) <= np.log1p(rtol)
    return np.flatnonzero(ok), ib[ok]


def _wrap_deg(d: np.ndarray) -> np.ndarray:
    """|d| wrapped onto [0, 180] deg."""
    return np.abs((np.asarray(d, dtype=float) + 180.0) % 360.0 - 180.0)


def agreement(edi_a, edi_b, pmin=None, pmax=None, rtol: float = PERIOD_RTOL) -> dict:
    """Compute the agreement of two TFs over their common periods.

    Periods are matched with `match_periods`, then restricted to
    [pmin, pmax] of the first TF.

    Args:
        edi_a (str or Path or TF): First TF.
        edi_b (str or Path or TF): Second TF.
        pmin (float, optional): Shortest period in s.
        pmax (float, optional): Longest period in s.
        rtol (float): Relative period tolerance for matching.

    Returns:
        dict: ``{"n_common", "xy": {"dlog_rho", "dphase", "n"}, "yx": {...},
        "overall": {...}}`` with median |dlog10 rho| and median |dphase| in
        degrees wrapped to [0, 180]. Medians are NaN where no period is
        valid in both.
    """
    pa, ra, fa, _, _ = curves(edi_a)
    pb, rb, fb, _, _ = curves(edi_b)
    ia, ib = match_periods(pa, pb, rtol)
    keep = _window(pa[ia], pmin, pmax)
    ia, ib = ia[keep], ib[keep]
    out = {"n_common": int(ia.size)}
    all_dl, all_dp = [], []
    for mode, (i, j) in MODES.items():
        r1, r2 = ra[ia, i, j], rb[ib, i, j]
        ok = np.isfinite(r1) & np.isfinite(r2) & (r1 > 0) & (r2 > 0) & np.isfinite(fa[ia, i, j]) & np.isfinite(fb[ib, i, j])
        dl = np.abs(np.log10(r1[ok]) - np.log10(r2[ok]))
        dp = _wrap_deg(fa[ia, i, j][ok] - fb[ib, i, j][ok])
        out[mode] = {"dlog_rho": _median(dl), "dphase": _median(dp), "n": int(ok.sum())}
        all_dl.append(dl)
        all_dp.append(dp)
    dl, dp = np.concatenate(all_dl), np.concatenate(all_dp)
    out["overall"] = {"dlog_rho": _median(dl), "dphase": _median(dp), "n": int(dl.size)}
    return out


def pairwise_spread(tfs, rtol: float = PERIOD_RTOL) -> dict:
    """Compute the spread among several TFs per period and mode.

    Each TF's periods are matched to the first TF's with `rtol`. A TF
    without a matching period, or with an invalid value there, is left out
    of that period's pairs.

    Args:
        tfs (iterable): EDI paths or TF objects, at least two.
        rtol (float): Relative period tolerance for matching.

    Returns:
        dict: ``{"period", "n", "dlog_rho", "dphase"}``. ``period`` holds the
        first TF's periods; ``n`` maps each mode to the number of valid TFs
        per period; ``dlog_rho`` and ``dphase`` map each mode to the median
        over all pairs of |dlog10 rho| and |dphase|, NaN where fewer than
        two TFs are valid.
    """
    tfs = list(tfs)
    p0 = curves(tfs[0])[0]
    nf = p0.size
    logr = {m: np.full((len(tfs), nf), np.nan) for m in MODES}
    phs = {m: np.full((len(tfs), nf), np.nan) for m in MODES}
    for k, tf in enumerate(tfs):
        p, rho, phi, _, _ = curves(tf)
        i0, ik = match_periods(p0, p, rtol)
        for mode, (i, j) in MODES.items():
            r = rho[ik, i, j]
            f = phi[ik, i, j]
            ok = np.isfinite(r) & (r > 0) & np.isfinite(f)
            logr[mode][k, i0[ok]] = np.log10(r[ok])
            phs[mode][k, i0[ok]] = f[ok]
    out = {"period": p0, "n": {}, "dlog_rho": {}, "dphase": {}}
    pairs = list(combinations(range(len(tfs)), 2))
    for mode in MODES:
        if pairs:
            a = np.array([p[0] for p in pairs])
            b = np.array([p[1] for p in pairs])
            dl = np.abs(logr[mode][a] - logr[mode][b])
            dp = _wrap_deg(phs[mode][a] - phs[mode][b])
            dp[~np.isfinite(dl)] = np.nan
            with warnings.catch_warnings():  # all-NaN columns give NaN, as documented
                warnings.simplefilter("ignore", RuntimeWarning)
                out["dlog_rho"][mode] = np.nanmedian(dl, axis=0)
                out["dphase"][mode] = np.nanmedian(dp, axis=0)
        else:
            out["dlog_rho"][mode] = np.full(nf, np.nan)
            out["dphase"][mode] = np.full(nf, np.nan)
        out["n"][mode] = np.isfinite(logr[mode]).sum(axis=0)
    return out
