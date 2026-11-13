# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.intersite and scripts/process_intersite.py

The synthetic fields are made in the frequency domain, so a known tensor
and a known delay hold exactly at every harmonic. Two source fields Bx, By
have red amplitude spectra (f^-1); the base's electric field is a
half-space-like response of them, Ebx = 2 z By and Eby = -1.5 z Bx with
z = sqrt(f) exp(i pi / 4); the local's is

    E_local(f) = A exp(i phi0) exp(-2 pi i f tau) E_base(f),
    A = [[1.10, 0.10], [-0.05, 0.90]], phi0 = -1.5 deg, tau = 2 ms,

so T carries a constant phase like an IP response and the local lags the
base by 2 ms, which under numpy's FFT is -360 f tau degrees on every
element and on arg(det T) / 2. Every site's H is B plus its own noise
(0.3 of B's spectrum), and every E has its own noise (0.2 of E's), with
random phases and the shape of the signal, so the noise is red as the
fields are. A band's expected T is the mean of the tensor over the band's
harmonics weighted by the base E's power (f^-1).

Part 1 (the array interface): 4 h at 200 Hz, the band scheme of
build_band_scheme(200, min_period=0.02, max_period=200), local and base
E and H, a third site C's H and a remote R's H; and 30 min at 1000 Hz
with tau = 10 ms, the band scheme of build_band_scheme(1000,
max_period=60), for the timing check at a delay whose turn between
neighbouring short-period bands exceeds half a cycle. Part 2 (the archives and
the script): 3 h at 100 Hz written as MTH5 archives of a scratch survey
(sites L, B, R, S1, S2 full length, X 20 min only), each channel stored as
int32 counts of its calibrated signal times its filter chain's response.
B's ex chain holds a 10 Hz one-pole low-pass (45 deg at 10 Hz) and its hx
chain a 5 Hz one, so a calibration that is not applied, or applied with
another site's chain, shows as a phase of T or M.

Usage:
    python tests/intersite_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (recovery, part 1) of the element-bands of T (local E on base E, Huber,
   referenced to R's H) with a finite error, more than 5 % lie beyond 3
   sigma of the expected T or any beyond 5 sigma; or the timing check's
   tau differs from +2 ms by more than max(3 sigma, 0.05 ms), or its
   intercept from phi0 = -1.5 deg by more than max(3 sigma, 0.1 deg);
2. (mutation, must trip 1) T referenced to a copy of the base's own E
   (least squares on a noisy input) passes criterion 1's 3-sigma count:
   its input noise of 0.2 must pull |T| about 4 % low, beyond every error;
3. (mutation, must trip 1) the same fields with tau = -2 ms pass the
   timing criterion for +2 ms, i.e. the sign of the delay is not seen;
4. (identities, code checks) with method "ls", one reference (R's H) and
   one set of windows, T differs from Z_local M Z_base^-1 (Z from each
   site's E on its own H, M from local H on base H), T_LB T_BL from I, or
   M_LB M_BC from M_LC by more than 1e-9 (relative, worst band); or, as
   the control that the comparison can fail, the Huber estimates (whose
   weights differ from row to row and tensor to tensor) meet the same
   identity to 1e-9;
5. (refusals) `estimate_band` or `estimate` accepts a reference sharing a
   channel with the inputs (the base's own channels) or with the outputs,
   or outputs that are the inputs; or the script with `--remote B` (the
   base) or `--remote L` (the local) does not exit 2 naming the reason,
   or writes a file; or the dry run with `--remote VS`, a workspace
   archive with no survey.yaml entry that holds B's own channels (a stack
   whose members include the base), does not exit 2 naming the missing
   entry (mutation: accepting a workspace archive as the remote, as the
   script once did, runs it and trips this);
6. (round trip) `read_csv(write_csv(est))` or `read_h5(write_h5(est))`
   differs from `est` in any array (exactly; NaN equal to NaN);
7. (archives, part 2) the telluric run L rr R or the magnetic run L rr R
   of the script fails criterion 1 against its expected tensor (for M the
   identity with tau 0 and phi0 0), or writes other products than
   <stem>.csv, .json, .h5 and .png under the stem L_te-B_rr-R or
   L_hm-B_rr-R, or any .edi or .xml; the CSV differs from the .h5's
   arrays; the sidecar lacks kind, tensor, local, base_site, reference,
   window, band_scheme, estimator, calibration, timing_check, versions or
   argv, or its timing_check differs from `timing_check` of the CSV read
   back by more than 1e-9 in tau; its calibration does not name B's
   low-pass filters;
8. (mutation, must trip 7) the same archives estimated with every chain
   response left out pass criterion 1 for T or for M;
9. (stack) the dry run of `--remote-stack H --exclude S2
   --min-overlap-hours 1` does not print members R and S1 alone and
   left_out lines for L (the local), B (the base), S2 (excluded) and X (20
   min, under 1 h), or exits non-zero; the real stack run's (the band
   stack, the default) sidecar members are not exactly [R, S1], its stem
   is not L_te-B_rr-stackH, or its T fails criterion 1 (the stack's
   rejection and the plain form are tests/intersite_stack_unit.py's); or
   `select_stack` without the exclude list
   leaves S2 out (the control that the exclusion, not the overlap, removed
   it);
10. (timing at 10 ms, part 1) with tau = 10 ms at 1000 Hz the timing
    check's tau differs from +10 ms by more than max(3 sigma, 0.05 ms),
    or its intercept from phi0 by more than max(3 sigma, 0.1 deg), or
    `timing_text` prints "not a clock offset alone"; or, as the control
    that the timing criterion can fail (the mutation the check was fixed
    for), the earlier fit of the same estimate (np.unwrap of arg(det)
    between neighbouring bands, at each band's plain mean frequency)
    comes within 1 ms of +10 ms; or, as the control that the note can
    fire, the 2 ms estimate of criterion 1 with a bump of 2 deg added to
    arg(det) / 2 (a phase that is not a line in frequency) is not printed
    as "not a clock offset alone"; or the 10 ms estimate with one band in
    the middle of the fit given an error of 15 deg and 40 deg more phase
    (a band beside a notch) has a weighted residual RMS of 1 % of the
    line's turn or more, or, as the control that the weighting is what
    keeps it under, a plain RMS under 1 % of the turn.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
A = np.array([[1.10, 0.10], [-0.05, 0.90]])
PHI0_DEG = -1.5
TAU_S = 2e-3
E_NOISE, H_NOISE = 0.2, 0.3
SCRATCH = scratch_dir("intersite_unit")
T_START = pd.Timestamp("2024-03-01T00:00:00")

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


# --- the synthetic fields ------------------------------------------------------------------------------------


def fields(fs: float, hours: float, seed: int, tau: float = TAU_S, h_sites=("l", "b", "c", "r")) -> dict:
    """Return the synthetic spectra (rfft, complex) of every channel, and the frequencies.

    Args:
        fs (float): Sample rate, Hz.
        hours (float): Length.
        seed (int): Random seed.
        tau (float): Delay of the local's E behind the base's, s.
        h_sites (tuple): Sites whose hx, hy are made (each B plus its own noise).

    Returns:
        dict: ``f`` (Hz), ``n`` (samples), and spectra keyed "l_ex", "l_ey",
        "b_ex", "b_ey", "<site>_hx", "<site>_hy" (and "<site>_ex", "<site>_ey"
        for the sites other than l and b), and "src_ex", "src_ey", the base's
        electric field without its noise.
    """
    n = int(round(hours * 3600 * fs))
    rng = np.random.default_rng(seed)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    fpos = np.maximum(f, f[1])
    b_shape = fpos**-1.0
    z = np.sqrt(fpos) * np.exp(1j * np.pi / 4)
    e_shape = np.abs(z) * b_shape * 1.75

    def white():
        w = rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)
        w[0] = 0.0
        return w

    bx, by = white() * b_shape, white() * b_shape
    ebx, eby = 2.0 * z * by, -1.5 * z * bx
    t = A[None] * np.exp(1j * np.radians(PHI0_DEG)) * np.exp(-2j * np.pi * f * tau)[:, None, None]
    out = {"f": f, "n": n,
           "l_ex": t[:, 0, 0] * ebx + t[:, 0, 1] * eby + E_NOISE * white() * e_shape,
           "l_ey": t[:, 1, 0] * ebx + t[:, 1, 1] * eby + E_NOISE * white() * e_shape,
           "b_ex": ebx + E_NOISE * white() * e_shape, "b_ey": eby + E_NOISE * white() * e_shape,
           "src_ex": ebx, "src_ey": eby}
    for site in h_sites:
        out[f"{site}_hx"] = bx + H_NOISE * white() * b_shape
        out[f"{site}_hy"] = by + H_NOISE * white() * b_shape
        if site not in ("l", "b"):  # a site's own E: its half-space response of B, plus its noise
            out[f"{site}_ex"] = 0.8 * ebx + E_NOISE * white() * e_shape
            out[f"{site}_ey"] = 0.8 * eby + E_NOISE * white() * e_shape
    return out


def series(spec: dict, keys) -> dict:
    """Return float32 time series of the given spectra."""
    return {k: np.fft.irfft(spec[k], spec["n"]).astype(np.float32) for k in keys}


def expected(freqs: np.ndarray, tensor: np.ndarray, phi0_deg: float, tau: float) -> np.ndarray:
    """Return the band's expected tensor: the mean over its harmonics, weighted by the base E power (f^-1)."""
    w = freqs**-1.0
    delay = np.sum(w * np.exp(-2j * np.pi * freqs * tau)) / np.sum(w)
    return tensor * np.exp(1j * np.radians(phi0_deg)) * delay


def recovery(est, bands_freqs, tensor, phi0_deg, tau, label: str, report: bool = True) -> dict:
    """Judge criterion 1 for an estimate; return the counts and the verdicts (printed when `report`).

    Args:
        est (TensorEstimate): The estimate.
        bands_freqs (dict): period -> the band's harmonics.
        tensor (np.ndarray): The real 2 x 2 tensor of the model.
        phi0_deg (float): Its constant phase.
        tau (float): Its delay, s.
        label (str): For the printed lines.
        report (bool): Record PASS/FAIL lines.

    Returns:
        dict: n, beyond3, beyond5, worst (in sigma), elements_ok, timing_ok, tau, intercept.
    """
    dev = []
    for b, p in enumerate(est.period):
        exp = expected(bands_freqs[round(float(p), 9)], tensor, phi0_deg, tau)
        d = np.abs(est.tensor[b] - exp) / est.sigma[b]
        dev += [x for x in d.ravel() if np.isfinite(x)]
    dev = np.array(dev)
    n3, n5 = int((dev > 3).sum()), int((dev > 5).sum())
    elements_ok = dev.size > 0 and n3 <= 0.05 * dev.size and n5 == 0
    tc = intersite.timing_check(est)
    tau_ms, tau_err = tc["tau_ms"], tc["tau_err_ms"]
    a, a_err = tc["intercept_deg"], tc["intercept_err_deg"]
    timing_ok = (tau_ms is not None and abs(tau_ms - tau * 1e3) <= max(3 * tau_err, 0.05)
                 and abs(a - phi0_deg) <= max(3 * a_err, 0.1))
    out = {"n": int(dev.size), "beyond3": n3, "beyond5": n5, "worst": float(dev.max()) if dev.size else np.nan,
           "elements_ok": bool(elements_ok), "timing_ok": bool(timing_ok), "tau": tau_ms, "intercept": a}
    if report:
        check(elements_ok, f"{label}: {n3} of {dev.size} element-bands beyond 3 sigma (at most 5 %), {n5} beyond "
                           f"5 sigma, worst {out['worst']:.2f} sigma")
        check(timing_ok, f"{label}: timing tau {tau_ms:+.4f} +/- {tau_err:.4f} ms (expected {tau * 1e3:+.3f}), "
                         f"intercept {a:+.3f} +/- {a_err:.3f} deg (expected {phi0_deg:+.2f})")
    return out


def freqs_by_period(bands) -> dict:
    """Map each band's period (rounded) to its harmonics."""
    return {round(b.period, 9): b.freqs for b in bands}


# --- part 1: the array interface -----------------------------------------------------------------------------


def part1() -> None:
    """Criteria 1-6 and 10 on the array interface."""
    fs = 200.0
    scheme = build_band_scheme(fs, min_period=0.02, max_period=200.0)
    spec = fields(fs, 4.0, seed=3)
    keys = ["l_ex", "l_ey", "b_ex", "b_ey", "l_hx", "l_hy", "b_hx", "b_hy", "c_hx", "c_hy", "r_hx", "r_hy"]
    arrays = series(spec, keys)
    arrays["bcopy_ex"], arrays["bcopy_ey"] = arrays["b_ex"].copy(), arrays["b_ey"].copy()
    bands = list(intersite.band_spectra(arrays, fs, scheme))
    fmap = freqs_by_period(bands)
    print(f"part 1: {len(bands)} bands, {spec['n']} samples at {fs:g} Hz")
    E_l, E_b, H_l, H_b, H_c, R = (("l_ex", "l_ey"), ("b_ex", "b_ey"), ("l_hx", "l_hy"), ("b_hx", "b_hy"),
                                  ("c_hx", "c_hy"), ("r_hx", "r_hy"))

    # 1. recovery
    est = intersite.estimate(bands, E_l, E_b, R)
    recovery(est, fmap, A, PHI0_DEG, TAU_S, "1 T rr R")
    for line in intersite.timing_text(intersite.timing_check(est)):
        print("     " + line)

    # 10. control: a phase that is not a line in frequency must be printed as not a clock offset alone
    bent = copy.deepcopy(est)
    bent.half_arg_deg = bent.half_arg_deg + 2.0 * np.sin(4.0 * np.pi * np.log10(bent.period))
    text = " ".join(intersite.timing_text(intersite.timing_check(bent)))
    check("not a clock offset alone" in text,
          "10 control: arg(det)/2 of criterion 1 with a 2 deg bump is printed as not a clock offset alone")

    # 2. mutation: the base's own E as the reference (a copy under other keys passes the key check)
    est_bad = intersite.estimate(bands, E_l, E_b, ("bcopy_ex", "bcopy_ey"))
    bad = recovery(est_bad, fmap, A, PHI0_DEG, TAU_S, "2 base E as reference", report=False)
    check(not bad["elements_ok"] and bad["beyond3"] > 0.25 * bad["n"],
          f"2 mutation trips: the base's own E as reference puts {bad['beyond3']} of {bad['n']} element-bands "
          f"beyond 3 sigma (worst {bad['worst']:.1f}); |T| median ratio to A "
          f"{np.nanmedian(np.abs(est_bad.det) / np.abs(np.linalg.det(A))) ** 0.5:.4f}")

    # 3. mutation: the delay of the other sign must fail the timing criterion for +2 ms
    spec_neg = fields(fs, 4.0, seed=3, tau=-TAU_S)
    arr_neg = series(spec_neg, ["l_ex", "l_ey", "b_ex", "b_ey", "r_hx", "r_hy"])
    est_neg = intersite.estimate(intersite.band_spectra(arr_neg, fs, scheme), E_l, E_b, R)
    neg = recovery(est_neg, fmap, A, PHI0_DEG, TAU_S, "3 tau -2 ms", report=False)
    check(not neg["timing_ok"] and neg["tau"] < -1.9,
          f"3 mutation trips: tau -2 ms injected comes back {neg['tau']:+.4f} ms, failing the +2 ms criterion")
    del arr_neg, spec_neg

    # 4. identities with the linear estimator, one reference, one set of windows
    T = intersite.estimate(bands, E_l, E_b, R, method="ls").tensor
    T_bl = intersite.estimate(bands, E_b, E_l, R, method="ls").tensor
    Zl = intersite.estimate(bands, E_l, H_l, R, method="ls").tensor
    Zb = intersite.estimate(bands, E_b, H_b, R, method="ls").tensor
    M_lb = intersite.estimate(bands, H_l, H_b, R, method="ls").tensor
    M_bc = intersite.estimate(bands, H_b, H_c, R, method="ls").tensor
    M_lc = intersite.estimate(bands, H_l, H_c, R, method="ls").tensor

    def worst(x, y):
        return float(np.nanmax(np.abs(x - y) / np.nanmax(np.abs(y), axis=(1, 2))[:, None, None]))

    d1 = worst(Zl @ M_lb @ np.linalg.inv(Zb), T)
    d2 = worst(T @ T_bl, np.broadcast_to(np.eye(2), T.shape))
    d3 = worst(M_lb @ M_bc, M_lc)
    check(d1 <= 1e-9, f"4 T = Z_l M Z_b^-1 to {d1:.2e} (ls, worst band)")
    check(d2 <= 1e-9, f"4 T_LB T_BL = I to {d2:.2e}")
    check(d3 <= 1e-9, f"4 M_LB M_BC = M_LC to {d3:.2e}")
    hub = {name: intersite.estimate(bands, o, i, R).tensor
           for name, (o, i) in {"T": (E_l, E_b), "Zl": (E_l, H_l), "Zb": (E_b, H_b), "M": (H_l, H_b)}.items()}
    dh = worst(hub["Zl"] @ hub["M"] @ np.linalg.inv(hub["Zb"]), hub["T"])
    check(dh > 1e-9, f"4 control: the Huber estimates meet T = Z_l M Z_b^-1 only to {dh:.2e} (> 1e-9), so the "
                     f"comparison can fail")

    # 5. refusals of the array interface
    for label, args in (("reference = the inputs", (E_l, E_b, E_b)),
                        ("reference shares an input", (E_l, E_b, ("b_ex", "r_hy"))),
                        ("reference shares an output", (E_l, E_b, ("l_ey", "r_hy"))),
                        ("outputs = inputs", (E_b, E_b, R))):
        for fn in ("estimate_band", "estimate"):
            try:
                if fn == "estimate_band":
                    intersite.estimate_band(bands[0], *args)
                else:
                    intersite.estimate(bands[:1], *args)
                check(False, f"5 {fn} refuses {label}")
            except ValueError as exc:
                check(True, f"5 {fn} refuses {label}: {exc}")

    # 6. round trips
    csv_path = SCRATCH / "roundtrip.csv"
    intersite.write_csv(est, "T", csv_path)
    back, letter = intersite.read_csv(csv_path)
    h5_path = SCRATCH / "roundtrip.h5"
    intersite.write_h5(est, "T", h5_path, attrs={"local": "L"})
    back_h5, letter_h5, attrs = intersite.read_h5(h5_path)
    for label, other, let in (("csv", back, letter), ("h5", back_h5, letter_h5)):
        same = let == "T" and all(np.array_equal(getattr(est, k), getattr(other, k), equal_nan=True)
                                  for k in intersite.TensorEstimate.__dataclass_fields__)
        check(same, f"6 {label} round trip: every array equal, letter {let}")
    check(attrs.get("local") == "L" and attrs.get("tensor") == "T", f"6 h5 attributes kept: {attrs.get('local')}")


def timing_large() -> None:
    """Criterion 10 at 1000 Hz: a delay of 10 ms, whose turn between neighbouring short-period bands exceeds 180 deg."""
    fs, tau = 1000.0, 10e-3
    scheme = build_band_scheme(fs, max_period=60.0)
    spec = fields(fs, 0.5, seed=5, tau=tau, h_sites=("r",))
    arrays = series(spec, ["l_ex", "l_ey", "b_ex", "b_ey", "r_hx", "r_hy"])
    del spec
    est = intersite.estimate(intersite.band_spectra(arrays, fs, scheme), ("l_ex", "l_ey"), ("b_ex", "b_ey"),
                             ("r_hx", "r_hy"))
    del arrays
    tc = intersite.timing_check(est)
    text = intersite.timing_text(tc)
    for line in text:
        print("     " + line)
    tau_ms, a = tc["tau_ms"], tc["intercept_deg"]
    ok = (tau_ms is not None and abs(tau_ms - 10.0) <= max(3 * tc["tau_err_ms"], 0.05)
          and abs(a - PHI0_DEG) <= max(3 * tc["intercept_err_deg"], 0.1))
    check(ok, f"10 tau 10 ms at 1000 Hz: timing tau {tau_ms:+.4f} +/- {tc['tau_err_ms']:.4f} ms, intercept "
              f"{a:+.3f} +/- {tc['intercept_err_deg']:.3f} deg (expected +10, {PHI0_DEG:+.2f})")
    check(not any("not a clock offset alone" in line for line in text),
          f"10 tau 10 ms: not printed as 'not a clock offset alone' (chi2/dof {tc['chi2_red']:.1f}, residuals "
          f"{tc['residual_rms_deg']:.3f} deg weighted RMS of a {tc['turn_deg']:.0f} deg turn)")
    # control: the earlier fit, np.unwrap between neighbours at the plain mean frequency, must miss
    lo, hi = tc["period_range_s"]
    sel = np.flatnonzero((est.period >= lo * (1 - 1e-9)) & (est.period <= hi * (1 + 1e-9)))
    sel = sel[np.argsort(est.f_mean[sel])]
    half = np.degrees(np.unwrap(np.radians(2.0 * est.half_arg_deg[sel]))) / 2.0
    old = intersite._line_fit(est.f_mean[sel], half, est.half_arg_err_deg[sel])
    old_tau = -old["b"] / 360.0 * 1e3
    check(abs(old_tau - 10.0) > 1.0, f"10 control: the earlier fit gives {old_tau:+.3f} ms for the same estimate, "
                                     f"more than 1 ms from +10, so the criterion can fail")
    # a band beside a notch: a large error and a large residual must not set the RMS the turn rule reads
    noisy = copy.deepcopy(est)
    b = sel[sel.size // 2]
    noisy.half_arg_err_deg[b] = 15.0
    noisy.half_arg_deg[b] += 40.0
    tn = intersite.timing_check(noisy)
    limit = intersite.TIMING_TURN_FRACTION * tn["turn_deg"]
    check(tn["residual_rms_deg"] < limit, f"10 noisy band at {est.period[b]:.4g} s: weighted residual RMS "
                                          f"{tn['residual_rms_deg']:.3f} deg, under 1 % of the turn ({limit:.2f} deg)")
    check(tn["residual_rms_plain_deg"] >= limit, f"10 control: the plain RMS of the same fit is "
                                                 f"{tn['residual_rms_plain_deg']:.3f} deg, not under {limit:.2f} deg")


# --- part 2: archives and the script -------------------------------------------------------------------------

FS2 = 100.0
HOURS2 = 3.0


def _filters(site: str, comp: str) -> list:
    """Return a channel's filter chain: a gain from physical units to counts, and B's low-pass stages."""
    from mt_metadata.timeseries.filters import CoefficientFilter, PoleZeroFilter

    electric = comp.startswith("e")
    units = "mV/km" if electric else "nT"
    gains = {"L": {"ex": 50.0, "ey": 40.0, "hx": 10.0, "hy": 10.0},
             "B": {"ex": 30.0, "ey": 60.0, "hx": 20.0, "hy": 20.0}}
    gain = gains.get(site, {}).get(comp, 50.0 if electric else 10.0)
    chain = [CoefficientFilter(name=f"{site.lower()}_{comp}_gain", units_in=units, units_out="count", gain=gain)]
    corner = {("B", "ex"): 10.0, ("B", "hx"): 5.0}.get((site, comp))
    if corner:
        w = 2 * np.pi * corner
        chain.append(PoleZeroFilter(name=f"{site.lower()}_{comp}_lowpass", units_in="count", units_out="count",
                                    poles=[complex(-w, 0.0)], zeros=[], normalization_factor=w))
    return chain


def _response(chain, f: np.ndarray) -> np.ndarray:
    """Return a chain's complex response at f (the product of its stages)."""
    out = np.ones(f.size, dtype=complex)
    for stage in chain:
        out *= stage.complex_response(f)
    return out


def write_site(workspace: Path, site: str, spec: dict, start: pd.Timestamp, n: int, offset: int = 0) -> None:
    """Write a site's archive: its channels as int32 counts through their chains, n samples from `offset`.

    Each channel's counts are its spectrum times the global `scale`, times
    its chain's response, transformed back and rounded.
    """
    from mt_metadata.timeseries.filters import ChannelResponse
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = spec["f"]
    key = {"L": "l", "B": "b"}.get(site, site.lower())
    chans = []
    for comp in ("ex", "ey", "hx", "hy"):
        chain = _filters(site, comp)
        physical = spec[f"{key}_{comp}"] * spec["scale"]
        counts = np.fft.irfft(physical * _response(chain, f), spec["n"])[offset: offset + n]
        counts = np.rint(counts).astype("int32")
        typ = "electric" if comp.startswith("e") else "magnetic"
        ch = ChannelTS(channel_type=typ, data=counts,
                       channel_metadata={typ: {"component": comp, "sample_rate": FS2,
                                               "time_period.start": start.isoformat()}},
                       channel_response=ChannelResponse(filters_list=chain))
        for applied in ch.channel_metadata.filters:
            applied.applied = True
        chans.append(ch)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("SYNTH")
        station = m.add_station(site, survey="SYNTH")
        run_id = f"sr{int(FS2)}_0001"
        run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS2}, station_metadata={"id": site})
        station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()


SURVEY_YAML = """name: intersite_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0}}
  B: {{latitude: -31.01, longitude: 137.0}}
  R: {{latitude: -31.5, longitude: 137.2}}
  S1: {{latitude: -31.2, longitude: 137.1}}
  S2: {{latitude: -31.3, longitude: 137.1}}
  X: {{latitude: -31.4, longitude: 137.1}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""


def build_survey() -> tuple[Path, dict]:
    """Write the scratch survey and its six archives; return survey.yaml and the spectra."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    spec = fields(FS2, HOURS2, seed=7, h_sites=("l", "b", "r", "s1", "s2", "x"))
    # one factor on every channel (T and M unchanged) so the int32 counts are large: the base's E at 1e4 rms
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    n = spec["n"]
    for site in ("L", "B", "R", "S1", "S2"):
        write_site(work, site, spec, T_START, n)
    short = int(20 * 60 * FS2)
    write_site(work, "X", spec, T_START + pd.Timedelta(hours=1), short, offset=int(3600 * FS2))
    return yaml_path, spec


def run(yaml_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run process_intersite.py on the scratch survey."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), *args], capture_output=True, text=True,
                          cwd=REPO)


def model_bands(yaml_path: Path) -> dict:
    """Return the band harmonics of the scratch survey's scheme at 100 Hz: period -> freqs (one STFT pass)."""
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(yaml_path)
    scheme = build_band_scheme(FS2, **survey.processing)
    probe = {"a": np.random.default_rng(1).standard_normal(int(HOURS2 * 3600 * FS2)).astype(np.float32)}
    return freqs_by_period(intersite.band_spectra(probe, FS2, scheme)), scheme


def part2() -> None:
    """Criteria 5 and 7-9 on archives through the script."""
    yaml_path, spec = build_survey()
    fmap, scheme = model_bands(yaml_path)
    out = SCRATCH / "out"
    shutil.rmtree(out, ignore_errors=True)

    # 5. refusals of the script: the base or the local as the reference
    for site, word in (("B", "base"), ("L", "local")):
        res = run(yaml_path, "L", "B", "--kind", "telluric", "--remote", site, "--out-dir", str(out))
        check(res.returncode == 2 and f"is the {word}" in res.stderr and "errors in variables" in res.stderr
              and not out.exists(),
              f"5 --remote {site} refused with exit {res.returncode}: {res.stderr.strip().splitlines()[-1][:120]}")
    # a workspace archive with no survey.yaml entry, here holding B's own channels
    work = SCRATCH / "survey" / "work"
    write_site(work, "VS", dict(spec, **{f"vs_{c}": spec[f"b_{c}"] for c in ("ex", "ey", "hx", "hy")}),
               T_START, spec["n"])
    res = run(yaml_path, "L", "B", "--kind", "telluric", "--remote", "VS", "--dry-run", "--out-dir", str(out))
    check(res.returncode == 2 and "no survey.yaml entry" in res.stderr and "errors in variables" in res.stderr
          and not out.exists(),
          f"5 --remote VS (a workspace archive holding B) refused with exit {res.returncode}: "
          f"{(res.stderr.strip().splitlines() or [''])[-1][:120]}")
    (work / "mth5" / "VS.h5").unlink()

    # 9. the stack's dry run
    res = run(yaml_path, "L", "B", "--kind", "telluric", "--remote-stack", "H", "--exclude", "S2",
              "--min-overlap-hours", "1", "--dry-run", "--out-dir", str(out))
    members = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("member: ")]
    left = {ln.split()[1]: ln for ln in res.stdout.splitlines() if ln.startswith("left_out: ")}
    ok = (res.returncode == 0 and members == ["R", "S1"] and "the local" in left.get("L", "")
          and "the base" in left.get("B", "") and "excluded" in left.get("S2", "")
          and "under 1 h" in left.get("X", "") and not out.exists())
    check(ok, f"9 dry run: members {members}, left out {sorted(left)}, exit {res.returncode}")
    if res.returncode != 0:
        print(res.stderr[-2000:])

    # 7. the telluric and magnetic runs through the script
    expected_stem = {"telluric": "L_te-B_rr-R", "magnetic": "L_hm-B_rr-R"}
    for kind, letter, tensor, phi0, tau in (("telluric", "T", A, PHI0_DEG, TAU_S),
                                            ("magnetic", "M", np.eye(2), 0.0, 0.0)):
        res = run(yaml_path, "L", "B", "--kind", kind, "--remote", "R", "--out-dir", str(out))
        if not check(res.returncode == 0, f"7 {kind} run exits 0"):
            print(res.stdout[-3000:], res.stderr[-3000:])
            continue
        stem = expected_stem[kind]
        files = sorted(p.name for p in out.glob(f"{stem}*"))
        check(files == sorted(f"{stem}{s}" for s in (".csv", ".h5", ".json", ".png")),
              f"7 {kind} products: {files}")
        check(not list(out.glob("*.edi")) and not list(out.glob("*.xml")), f"7 {kind}: no EDI or XML written")
        est, let = intersite.read_csv(out / f"{stem}.csv")
        est_h5, let_h5, _attrs = intersite.read_h5(out / f"{stem}.h5")
        check(let == let_h5 == letter and all(np.array_equal(getattr(est, k), getattr(est_h5, k), equal_nan=True)
                                              for k in intersite.TensorEstimate.__dataclass_fields__),
              f"7 {kind}: the CSV equals the h5's arrays")
        recovery(est, fmap, tensor, phi0, tau, f"7 {kind} from the archives")
        side = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
        need = ("kind", "tensor", "local", "base_site", "reference", "window", "band_scheme", "estimator",
                "calibration", "timing_check", "versions", "argv")
        missing = [k for k in need if k not in side]
        check(not missing and side["kind"] == kind and side["tensor"] == letter and side["base_site"] == "B",
              f"7 {kind} sidecar keys (missing {missing})")
        tc = intersite.timing_check(est)
        check(abs(tc["tau_ms"] - side["timing_check"]["tau_ms"]) <= 1e-9,
              f"7 {kind}: the sidecar's timing_check equals the CSV's ({side['timing_check']['tau_ms']:+.5f} ms)")
        comp = "ex" if kind == "telluric" else "hx"
        named = side["calibration"]["base"][comp]["filters"]
        check(f"b_{comp}_lowpass" in named, f"7 {kind}: calibration names B's {comp} chain {named}")

    # 8. mutation: the same archives with every chain left out
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(yaml_path)
    n, t0 = spec["n"], int(T_START.tz_localize("UTC").value)
    for kind, letter, tensor, phi0, tau in (("telluric", "T", A, PHI0_DEG, TAU_S),
                                            ("magnetic", "M", np.eye(2), 0.0, 0.0)):
        roles = intersite.KINDS[kind]
        arrays = {}
        for prefix, site, rr in (("l_", "L", roles), ("b_", "B", roles), ("r_", "R", ("hx", "hy"))):
            got, _resp, _chains = intersite.read_channels(survey.workspace / "mth5" / f"{site}.h5", site, rr, t0, n,
                                                          FS2)
            arrays.update({prefix + r: v for r, v in got.items()})
        est = intersite.estimate(intersite.band_spectra(arrays, FS2, scheme), ("l_" + roles[0], "l_" + roles[1]),
                                 ("b_" + roles[0], "b_" + roles[1]), ("r_hx", "r_hy"))
        bad = recovery(est, fmap, tensor, phi0, tau, f"8 {kind} uncalibrated", report=False)
        check(not bad["elements_ok"], f"8 mutation trips: {kind} without the chains puts {bad['beyond3']} of "
                                      f"{bad['n']} element-bands beyond 3 sigma (worst {bad['worst']:.0f})")

    # 9. the stack run, and the exclusion's control
    res = run(yaml_path, "L", "B", "--kind", "telluric", "--remote-stack", "H", "--exclude", "S2",
              "--min-overlap-hours", "1", "--out-dir", str(out))
    stem = "L_te-B_rr-stackH"
    if check(res.returncode == 0 and (out / f"{stem}.json").exists(), f"9 stack run exits {res.returncode}"):
        side = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
        got = [m["site"] for m in side["reference"]["members"]]
        check(got == ["R", "S1"], f"9 stack members in the sidecar: {got}")
        est, _let = intersite.read_csv(out / f"{stem}.csv")
        recovery(est, fmap, A, PHI0_DEG, TAU_S, "9 T rr stackH")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])
    lo = int(T_START.tz_localize("UTC").value)
    hi = lo + int(HOURS2 * 3.6e12)
    members, _left = intersite.select_stack(survey, "L", "B", lo, hi, ("hx", "hy"), (), 1.0)
    check([m["site"] for m in members] == ["R", "S1", "S2"],
          f"9 control: without the exclude list the members are {[m['site'] for m in members]}")


def main() -> int:
    """Run both parts; return 1 on any failure."""
    part1()
    timing_large()
    part2()
    print(f"\n{len(failures)} failure(s)")
    for msg in failures:
        print("  " + msg)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
