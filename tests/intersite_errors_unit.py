# -*- coding: utf-8 -*-
"""
Unit test for the errors, the robustness and the impedance identity of mt_workbench.intersite

The fields are made in the frequency domain, as in tests/intersite_unit.py,
from two source fields Bx, By with red amplitude spectra (f^-1). The base
H is B, the local H is M B, the base E is z Z_b B and the local E is
z Z_l M B, with z = sqrt(f) exp(i pi / 4) and

    Z_b = [[0, 2], [-1.5, 0]],
    Z_l = exp(i phi0) [[0.2, 2.2], [-1.6, -0.1]],   phi0 = -1.5 deg,
    M = [[1.05, 0.08], [-0.04, 0.95]],

so T = Z_l M Z_b^-1 is the same at every frequency, and arg(det T) / 2 =
phi0 (det Z_l M / det Z_b is exp(2 i phi0) times a positive number). Every
E has its own red noise of 0.2 of its spectrum, every H (local, base and a
remote R) 0.3 of B's. Each record is 1 h at 50 Hz with the bands of
build_band_scheme(50, min_period=0.08, max_period=50). In the bursty copy
1 % of the samples of each local E channel lie in 20 bursts of white noise
30 times the channel's standard deviation.

Why the calibration targets are 0.623 and 0.670, not 0.683. An element's
error is the jackknife standard error of the complex value (its modulus),
so a calibrated element lies within one sigma with probability
1 - exp(-1) = 0.632 when the error is known exactly, and psi = arg(det T)
/ 2, a real value, with probability 0.683. The jackknife of g = 20 slices
estimates the variance with about g - 1 degrees of freedom, so the
deviation over its error follows Student's t with 19 for psi (0.670), and
for an element the squared ratio follows F(2, 38) (1 - (20/19)^-19 =
0.623). Only bands with all 20 slices are counted. The element-bands of
these fields are close to independent (the spread of the fraction between
seeds is the binomial one), so each check's interval is p0 +- 3 sqrt(p0
(1 - p0) / N), N the number counted. With 50 seeds (900 bands) the pooled
interval resolves errors wrong by a factor of about 1.03 in the elements
and 1.10 in psi; a smaller miscalibration passes.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (calibration, clean and bursty fields, seeds 0-49 each) the fraction
   of element deviations |T - T_true| under one stated sigma, pooled or
   for any one element, or the fraction of psi deviations under one
   stated sigma, lies outside its interval about 0.623 (elements) or
   0.670 (psi);
2. (mutations, must trip 1) with every error multiplied by 2, or by 0.5,
   the pooled element fraction or the psi fraction stays inside its
   interval;
3. (robustness) with the local E's spectra of 1 % of each level's windows
   (at least one) multiplied by 1000, the Huber estimate has more than 5 %
   of its element-bands beyond 3 sigma of T_true or any beyond 5 sigma,
   or more than 5 % of its bands with psi beyond 3 sigma of phi0 or any
   beyond 5 sigma, judged once with its own errors and once with the
   errors of the Huber estimate of the same spectra before the scaling (an
   estimate whose errors grow with the outliers can pass the first and
   still have lost the clean run's precision);
4. (mutation, must trip 3) the least-squares estimate of the same
   spectra meets criterion 3;
5. (identity, bursty fields) any element-band of the Huber T differs from
   Z_l M Z_b^-1 (each estimated with Huber, referenced to R) by more than
   3 combined sigma, or the median difference exceeds sqrt(ln 2) = 0.83
   combined sigma; the combined sigma is sqrt(sigma_T^2 + sigma_P^2),
   sigma_P propagated to first order from the errors of Z_l, M and Z_b
   as if they were independent. Two independent estimates of one complex
   value would differ by over 3 combined sigma with probability exp(-9)
   and by a median of sqrt(ln 2); T and the product share their data, so
   they lie closer than that;
6. (mutation, must trip 5) Z_b M Z_l^-1, the identity with the local and
   the base exchanged, meets criterion 5.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

FS = 50.0
HOURS = 1.0
SEEDS = range(50)
PHI0_DEG = -1.5
Z_B = np.array([[0.0, 2.0], [-1.5, 0.0]], dtype=complex)
Z_L = np.exp(1j * np.radians(PHI0_DEG)) * np.array([[0.2, 2.2], [-1.6, -0.1]])
M = np.array([[1.05, 0.08], [-0.04, 0.95]], dtype=complex)
T_TRUE = Z_L @ M @ np.linalg.inv(Z_B)
PSI_TRUE = np.degrees(np.angle(np.linalg.det(T_TRUE))) / 2.0
E_NOISE, H_NOISE = 0.2, 0.3
BURST_FRACTION, BURST_COUNT, BURST_AMPLITUDE = 0.01, 20, 30.0
SCALED_FRACTION, SCALE = 0.01, 1000.0
SCHEME = build_band_scheme(FS, min_period=4.0 / FS, max_period=50.0)
E_L, E_B, H_L, H_B, R = (("l_ex", "l_ey"), ("b_ex", "b_ey"), ("l_hx", "l_hy"), ("b_hx", "b_hy"),
                         ("r_hx", "r_hy"))
G = intersite.JACKKNIFE_GROUPS
P_ELEMENT = 1.0 - (G / (G - 1.0)) ** -(G - 1.0)  # P(F(2, 2(g - 1)) < 1)
P_PSI = float(stats.t.cdf(1.0, G - 1) - stats.t.cdf(-1.0, G - 1))

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def series(seed: int, bursty: bool = False) -> dict:
    """Return float32 time series of the local and base E and H and the remote's H.

    Args:
        seed (int): Random seed.
        bursty (bool): Add bursts to 1 % of each local E channel's samples.

    Returns:
        dict: Channel key ("l_ex", "b_hy", "r_hx", ...) to its series.
    """
    n = int(round(HOURS * 3600 * FS))
    rng = np.random.default_rng(seed)
    f = np.fft.rfftfreq(n, 1.0 / FS)
    fpos = np.maximum(f, f[1])
    b_shape = fpos**-1.0
    z = np.sqrt(fpos) * np.exp(1j * np.pi / 4)
    e_shape = np.abs(z) * b_shape * 1.75

    def white():
        w = rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)
        w[0] = 0.0
        return w

    b = np.array([white() * b_shape, white() * b_shape])
    hl = M @ b
    eb = z * (Z_B @ b)
    el = z * (Z_L @ hl)
    spec = {}
    for i, c in enumerate("xy"):
        spec[f"l_e{c}"] = el[i] + E_NOISE * white() * e_shape
        spec[f"b_e{c}"] = eb[i] + E_NOISE * white() * e_shape
        spec[f"l_h{c}"] = hl[i] + H_NOISE * white() * b_shape
        spec[f"b_h{c}"] = b[i] + H_NOISE * white() * b_shape
        spec[f"r_h{c}"] = b[i] + H_NOISE * white() * b_shape
    out = {k: np.fft.irfft(v, n) for k, v in spec.items()}
    if bursty:
        length = int(BURST_FRACTION * n / BURST_COUNT)
        for k in E_L:
            sd = float(out[k].std())
            for start in rng.integers(0, n - length, BURST_COUNT):
                out[k][start:start + length] += BURST_AMPLITUDE * sd * rng.standard_normal(length)
    return {k: v.astype(np.float32) for k, v in out.items()}


def interval(p0: float, n: int) -> tuple[float, float]:
    """Return p0 +- 3 binomial standard deviations for n counts."""
    half = 3.0 * np.sqrt(p0 * (1.0 - p0) / n)
    return p0 - half, p0 + half


def calibration(label: str, bursty: bool) -> None:
    """Criteria 1 and 2 over the seeds, for one kind of field."""
    dev_el, dev_psi = [], []
    for seed in SEEDS:
        bands = list(intersite.band_spectra(series(seed, bursty), FS, SCHEME))
        est = intersite.estimate(bands, E_L, E_B, R)
        full = est.n_groups == G
        dev_el.append((np.abs(est.tensor[full] - T_TRUE[None]) / est.sigma[full]).reshape(-1, 4))
        dev_psi.append(np.abs(est.half_arg_deg[full] - PSI_TRUE) / est.half_arg_err_deg[full])
    d_el, d_psi = np.concatenate(dev_el), np.concatenate(dev_psi)
    n_bands = d_psi.size
    print(f"{label}: {len(SEEDS)} seeds, {n_bands} bands with all {G} slices, {d_el.size} element-bands")
    lo, hi = interval(P_ELEMENT, d_el.size)
    frac = float(np.mean(d_el < 1.0))
    scale = float(np.quantile(d_el, P_ELEMENT))
    check(lo <= frac <= hi, f"1 {label}: elements pooled {frac:.4f} within 1 sigma, interval [{lo:.4f}, {hi:.4f}]; "
                            f"the errors match at {scale:.3f} times their stated value")
    lo1, hi1 = interval(P_ELEMENT, n_bands)
    for k, el in enumerate(intersite.ELEMENTS):
        f_el = float(np.mean(d_el[:, k] < 1.0))
        check(lo1 <= f_el <= hi1, f"1 {label}: T_{el} {f_el:.4f} within 1 sigma, interval [{lo1:.4f}, {hi1:.4f}]; "
                                  f"scale {np.quantile(d_el[:, k], P_ELEMENT):.3f}")
    plo, phi = interval(P_PSI, n_bands)
    f_psi = float(np.mean(d_psi < 1.0))
    check(plo <= f_psi <= phi, f"1 {label}: psi {f_psi:.4f} within 1 sigma, interval [{plo:.4f}, {phi:.4f}]; "
                               f"scale {np.quantile(d_psi, P_PSI):.3f}")
    for factor in (2.0, 0.5):
        f_m, p_m = float(np.mean(d_el < factor)), float(np.mean(d_psi < factor))
        check(not lo <= f_m <= hi and not plo <= p_m <= phi,
              f"2 {label}: errors x{factor:g} trip: elements {f_m:.4f}, psi {p_m:.4f} within the stated sigma")


def beyond(est, sigma: np.ndarray, psi_sigma: np.ndarray, label: str) -> bool:
    """Judge criterion 3 for an estimate against the given errors; return whether it holds, and print the counts."""
    d_el = np.abs(est.tensor - T_TRUE[None]) / sigma
    d_el = d_el[np.isfinite(d_el)]
    d_psi = np.abs(est.half_arg_deg - PSI_TRUE) / psi_sigma
    d_psi = d_psi[np.isfinite(d_psi)]
    ok = (d_el.size > 0 and np.sum(d_el > 3) <= 0.05 * d_el.size and not np.any(d_el > 5)
          and d_psi.size > 0 and np.sum(d_psi > 3) <= 0.05 * d_psi.size and not np.any(d_psi > 5))
    print(f"     {label}: {int(np.sum(d_el > 3))} of {d_el.size} element-bands beyond 3 sigma, worst "
          f"{d_el.max():.2f}; {int(np.sum(d_psi > 3))} of {d_psi.size} psi beyond 3 sigma, worst {d_psi.max():.2f}")
    return bool(ok)


def robustness() -> None:
    """Criteria 3 and 4."""
    rng = np.random.default_rng(1000)
    bands = list(intersite.band_spectra(series(7), FS, SCHEME))
    clean = intersite.estimate(bands, E_L, E_B, R)
    chosen = {}
    for band in bands:
        if band.level not in chosen:
            n = band.n_windows
            chosen[band.level] = rng.choice(n, max(1, int(round(SCALED_FRACTION * n))), replace=False)
        for k in E_L:
            band.spectra[k] = band.spectra[k].copy()
            band.spectra[k][chosen[band.level]] *= SCALE
    print("3 windows scaled per level: " + ", ".join(f"{lv}: {idx.size}" for lv, idx in sorted(chosen.items())))
    for method in intersite.METHODS:
        est = intersite.estimate(bands, E_L, E_B, R, method=method)
        own = beyond(est, est.sigma, est.half_arg_err_deg, f"{method}, its own errors")
        held = beyond(est, clean.sigma, clean.half_arg_err_deg, f"{method}, the clean run's errors")
        ratio = float(np.nanmedian(est.sigma / clean.sigma))
        if method == "huber":
            check(own and held, f"3 Huber recovers T and psi within its errors and the clean run's with 1 % of "
                                f"windows x1000 (median error {ratio:.2f} times the clean run's)")
        else:
            check(not (own and held), f"4 least squares on the same spectra trips criterion 3 (median error "
                                      f"{ratio:.1f} times the clean run's)")


def product_sigma(zl, sl, m, sm, zb, sb) -> tuple[np.ndarray, np.ndarray]:
    """Return Z_l M Z_b^-1 per band and its first-order error from independent element errors."""
    w = np.linalg.inv(zb)
    p = zl @ m @ w
    mw = m @ w
    var = (np.einsum("bik,bkj->bij", sl**2, np.abs(mw) ** 2)
           + np.einsum("bik,bkl,blj->bij", np.abs(zl) ** 2, sm**2, np.abs(w) ** 2)
           + np.einsum("bik,bkl,blj->bij", np.abs(p) ** 2, sb**2, np.abs(w) ** 2))
    return p, np.sqrt(var)


def identity() -> None:
    """Criteria 5 and 6."""
    bands = list(intersite.band_spectra(series(11, bursty=True), FS, SCHEME))
    est = {name: intersite.estimate(bands, o, i, R)
           for name, (o, i) in {"T": (E_L, E_B), "Zl": (E_L, H_L), "Zb": (E_B, H_B), "M": (H_L, H_B)}.items()}
    t, st = est["T"].tensor, est["T"].sigma
    root = np.sqrt(np.log(2.0))

    def judge(p, sp):
        r = np.abs(t - p) / np.sqrt(st**2 + sp**2)
        r = r[np.isfinite(r)]
        return r.size > 0 and r.max() <= 3.0 and np.median(r) <= root, r

    p, sp = product_sigma(est["Zl"].tensor, est["Zl"].sigma, est["M"].tensor, est["M"].sigma,
                          est["Zb"].tensor, est["Zb"].sigma)
    ok, r = judge(p, sp)
    check(ok, f"5 Huber T = Z_l M Z_b^-1 over {r.size} element-bands: median {np.median(r):.3f}, worst "
              f"{r.max():.3f} combined sigma (at most {root:.2f} and 3)")
    q, sq = product_sigma(est["Zb"].tensor, est["Zb"].sigma, est["M"].tensor, est["M"].sigma,
                          est["Zl"].tensor, est["Zl"].sigma)
    bad, rs = judge(q, sq)
    check(not bad, f"6 local and base exchanged trips: median {np.median(rs):.2f}, worst {rs.max():.2f} combined sigma")


def main() -> int:
    """Run every criterion; return 0 when all pass."""
    start = time.time()
    print(f"mt_workbench from {intersite.__file__}")
    print(f"T_true {np.round(T_TRUE, 4).tolist()}, psi {PSI_TRUE:+.3f} deg; targets {P_ELEMENT:.4f} (elements), "
          f"{P_PSI:.4f} (psi)")
    calibration("clean", bursty=False)
    calibration("bursty", bursty=True)
    robustness()
    identity()
    print(f"\n{time.time() - start:.0f} s")
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
