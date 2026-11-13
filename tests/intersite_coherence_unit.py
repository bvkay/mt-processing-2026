# -*- coding: utf-8 -*-
"""
Unit test for the coherence columns of mt_workbench.intersite

The fields are those of tests/intersite_unit.py (2 h at 100 Hz, bands of
build_band_scheme(100, min_period=0.04, max_period=20)): local E on base E,
referenced to a remote's H. In the bursty copy each local E channel has a
burst added in 1 % of the record, 14 segments of 5 s at random, of
independent red noise 100 times the E noise's amplitude spectrum, about
5,000 times the clean local E power in those samples.

Why the margin of criterion 1 is 0.2. Bursts that add independent power B
times the clean power P in a fraction q of the samples bring the plain
squared coherence c0 down to c0 / (1 + q B), here 0.89 / (1 + 0.01 x 5,000)
= 0.02. Under the Huber weights a burst sample of residual r keeps
w |y|^2 = r0 s |r|, with s = 1.4826 median |r|, which is about 0.4 sqrt(P)
for a clean coherence of 0.89, so its share is g = r0 0.4 sqrt(B) = 43
times q, and the weighted coherence is c0 / (1 + q g) = 0.6. The predicted
gap is about 0.6 for ex and 0.45 for ey (whose clean coherence is lower);
0.2 is a third of it and ten times the plain value. The rule is judged on
the bands of 400 windows or more (levels 0-2), where bursts touch under
5 % of the windows; on the longest levels a burst fills a large part of
every window and no reweighting recovers the clean value.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. on the bursty copy, in any band of 400 windows or more, the weighted
   coherence of either output is not above the unweighted one by 0.2;
2. with method "ls" (every weight 1) the weighted coherence differs from
   the unweighted one by more than 1e-12 (relative) in any band, or the
   down-weighted fraction is not 0;
3. on the bursty copy, in a band of 400 windows or more, the down-weighted
   fraction of either output is under the fraction of windows whose centre
   lies in a burst, or over 1;
4. (control) a dead local ex (red noise sharing nothing with the fields)
   has a weighted coherence of 0.05 or more in any band, so the weights
   would make a dead channel read as alive;
5. the CSV or h5 round trip changes any coherence or down-weighted array;
   the CSV lacks coh_out_unweighted_x/y, coh_in_unweighted_x/y,
   coh_out_weighted_x/y or frac_downweighted_x/y, or still holds the
   ambiguous coh_out_x; or a frame in the earlier form (coh_out_x ...
   and no weighted columns) does not read back with coh_out_x as the
   unweighted value and NaN in the weighted columns.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import fields, series  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

FS = 100.0
HOURS = 2.0
BURST_S = 5.0
BURST_FRACTION = 0.01
BURST_AMPLITUDE = 100.0
MIN_WINDOWS = 400
MARGIN = 0.2
DEAD_LIMIT = 0.05
SCRATCH = scratch_dir("intersite_coherence_unit")
E_L, E_B, R = ("l_ex", "l_ey"), ("b_ex", "b_ey"), ("r_hx", "r_hy")

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def red(spec: dict, rng, scale: float) -> np.ndarray:
    """Return a red noise series with the E noise's spectral shape times `scale`."""
    f = spec["f"]
    fpos = np.maximum(f, f[1])
    w = rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)
    w[0] = 0.0
    return np.fft.irfft(scale * w * np.sqrt(fpos) * fpos**-1.0 * 1.75, spec["n"])


def run(arrays: dict, scheme: dict, method: str = "huber"):
    """Return (estimate, bands) of local E on base E referenced to R's H."""
    bands = list(intersite.band_spectra({k: v.copy() for k, v in arrays.items()}, FS, scheme))
    return intersite.estimate(bands, E_L, E_B, R, method=method), bands


def arrays_of(est, name: str):
    """Return an estimate's array `name`, or None when it has none."""
    return getattr(est, name, None)


def main() -> int:
    scheme = build_band_scheme(FS, min_period=0.04, max_period=20.0)
    spec = fields(FS, HOURS, seed=11, h_sites=("r",))
    keys = ["l_ex", "l_ey", "b_ex", "b_ey", "r_hx", "r_hy"]
    clean = series(spec, keys)
    n = spec["n"]
    rng = np.random.default_rng(5)
    seg = int(BURST_S * FS)
    mask = np.zeros(n, dtype=bool)
    for s in rng.choice(n // seg, size=int(BURST_FRACTION * n / seg), replace=False):
        mask[s * seg:(s + 1) * seg] = True
    bursty = {k: v.copy() for k, v in clean.items()}
    for k in E_L:
        bursty[k] = (bursty[k] + red(spec, rng, BURST_AMPLITUDE) * mask).astype(np.float32)
    print(f"{n} samples at {FS:g} Hz; bursts in {mask.mean():.4f} of the record")

    est, bands = run(bursty, scheme)
    weighted, down = arrays_of(est, "coh_out_weighted"), arrays_of(est, "frac_downweighted")
    if weighted is None or down is None:
        check(False, "1 the estimate has coh_out_weighted and frac_downweighted")
        print(f"\n{len(failures)} FAILED")
        return 1
    big = est.n_windows >= MIN_WINDOWS
    gap = weighted - est.coh_out
    worst = float(np.nanmin(gap[big])) if big.any() else np.nan
    k = int(np.nanargmin(np.where(big[:, None], gap, np.inf))) // 2 if big.any() else 0
    check(big.sum() >= 12 and np.all(np.isfinite(gap[big])) and np.all(gap[big] > MARGIN),
          f"1 bursty: weighted minus unweighted coherence at least {MARGIN} in {int(big.sum())} bands of "
          f">= {MIN_WINDOWS} windows: smallest {worst:.3f} at {est.period[k]:.3g} s (unweighted "
          f"{est.coh_out[k, 0]:.4f}, {est.coh_out[k, 1]:.4f}; weighted {weighted[k, 0]:.4f}, {weighted[k, 1]:.4f})")

    ls, _ = run(bursty, scheme, method="ls")
    rel = np.abs(ls.coh_out_weighted - ls.coh_out) / np.abs(ls.coh_out)
    check(np.all(np.isfinite(rel)) and float(rel.max()) <= 1e-12 and np.all(ls.frac_downweighted == 0.0),
          f"2 ls: weighted equals unweighted to {float(np.nanmax(rel)):.1e} (at most 1e-12), down-weighted "
          f"fraction max {float(np.nanmax(ls.frac_downweighted)):.3g} (must be 0)")

    centred = {}
    for b in bands:
        idx = np.clip(np.round(b.t_mid * FS).astype(int), 0, n - 1)
        centred[round(b.period, 9)] = float(mask[idx].mean())
    floor = np.array([centred[round(float(p), 9)] for p in est.period])
    ok3 = np.all(down[big] >= floor[big, None]) and np.all(down[big] <= 1.0)
    check(bool(ok3), f"3 bursty: down-weighted fraction {float(np.nanmin(down[big])):.3f}-"
                     f"{float(np.nanmax(down[big])):.3f} against windows centred in a burst "
                     f"{float(floor[big].min()):.3f}-{float(floor[big].max()):.3f}")

    dead = {k: v.copy() for k, v in clean.items()}
    dead["l_ex"] = red(spec, np.random.default_rng(9), 1.0).astype(np.float32)
    est_dead, _ = run(dead, scheme)
    top = float(np.nanmax(est_dead.coh_out_weighted[:, 0]))
    check(top < DEAD_LIMIT, f"4 control: a dead local ex has a weighted coherence of at most {top:.4f} "
                            f"(under {DEAD_LIMIT})")

    csv = intersite.write_csv(est, "T", SCRATCH / "coh.csv")
    h5 = intersite.write_h5(est, "T", SCRATCH / "coh.h5")
    df = pd.read_csv(csv)
    names = ["coh_out_unweighted_x", "coh_out_unweighted_y", "coh_in_unweighted_x", "coh_in_unweighted_y",
             "coh_out_weighted_x", "coh_out_weighted_y", "frac_downweighted_x", "frac_downweighted_y"]
    absent = [c for c in names if c not in df.columns]
    stale = [c for c in ("coh_out_x", "coh_out_y", "coh_in_x", "coh_in_y") if c in df.columns]
    back_csv, _ = intersite.read_csv(csv)
    back_h5, _, _ = intersite.read_h5(h5)
    same = all(np.array_equal(getattr(est, a), getattr(b, a), equal_nan=True)
               for b in (back_csv, back_h5)
               for a in ("coh_out", "coh_in", "coh_out_weighted", "frac_downweighted"))
    old = est.frame("T").rename(columns={"coh_out_unweighted_x": "coh_out_x", "coh_out_unweighted_y": "coh_out_y",
                                         "coh_in_unweighted_x": "coh_in_x", "coh_in_unweighted_y": "coh_in_y"})
    old = old.drop(columns=["coh_out_weighted_x", "coh_out_weighted_y", "frac_downweighted_x", "frac_downweighted_y"])
    back_old, _ = intersite.TensorEstimate.from_frame(old)
    old_ok = (np.array_equal(back_old.coh_out, est.coh_out, equal_nan=True)
              and np.all(np.isnan(back_old.coh_out_weighted)) and np.all(np.isnan(back_old.frac_downweighted)))
    check(not absent and not stale and same and old_ok,
          f"5 columns present (missing {absent}), earlier names gone (left {stale}), CSV and h5 round trips "
          f"exact ({same}), an earlier-form frame reads back ({old_ok})")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
