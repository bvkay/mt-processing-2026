# -*- coding: utf-8 -*-
"""
Unit test for the delay scan of the inter-site timing check (intersite.timing_check)

`timing_check` places each band's phase on its branch by a scan of delays
and fits phase = a - 360 f tau. When every band frequency is a multiple of
one spacing df, a delay tau and tau + cycle / (360 df) give the same phase
at every band (1024 s for arg(det) / 2 at df = 1/2048 Hz), and when the
band phases are noise the scan still finds some line (upstream 100 and
336). The scan is bounded by the alias period of the bands and by a clock
tolerance, takes the smallest |tau| among near-equal maxima, and reports a
delay as not determined (None, with a reason) when the line runs to the
bound or when its resultant is under `TIMING_MIN_RESULTANT`.

The estimates are built in the test: a diagonal tensor whose two elements
carry phi0 - 360 f tau plus Gaussian phase noise, at given band
frequencies, with the band errors stated. The long-period grid holds bands
at k/2048 Hz, k = 2-10 (one harmonic of 2048 s windows each); the short
grid ten bands per decade from 250 Hz down (1000 Hz sampling).

Usage:
    python tests/intersite_delay_scan_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (recovery) on the long grid with 0.2 deg noise, a delay of +0.5 s at
   the default clock tolerance, or of -3.0 s with a clock tolerance of
   3000 s, is not determined, or comes back more than 4 sigma from the
   truth, or more than one of the 30 fits (arg(det) / 2 and the two
   diagonal elements in 10 seeds) comes back more than 3 sigma from it
   (with honest errors 30 fits put one beyond 3 sigma about 8 % of the
   time, and two under 0.4 %);
2. (alias period) with the 3000 s tolerance the alias period reported is
   not 1024 s for arg(det) / 2 and 2048 s for an element (to within two
   steps of the scan), or the scan's half-width exceeds half of it;
3. (beyond the bound) on the long grid, a delay of -3.0 s or +30 s at the
   default tolerance (1 s) is reported with a tau or its error other
   than None by arg(det) / 2 or by either element, is not marked not
   determined with a reason that names the bound and scripts/timing_qc.py
   (for an offset of whole seconds), the check does not
   write as strict JSON (a NaN in it does not), or `timing_text` does
   not print "not determined" for arg(det) / 2 and for each element;
4. (zero) a delay of 0 fails criterion 1's rule about 0, at the default
   tolerance or at 3000 s;
5. (noise) uniform random band phases give a finite tau (from arg(det)
   / 2) in any of 100 seeds: with stated errors of 60 deg on the long grid
   and on the short grid (the errors alone forbid a line), and with stated
   errors of 2 deg on the short grid (errors far under the scatter, so
   only the observed resultant can refuse the line; over 1000 other seeds
   the largest resultant taken was under `TIMING_MIN_RESULTANT`, while 7
   reached 0.95);
6. (control) a clean line of 2 ms on the short grid with 0.5 deg noise
   and 0.5 deg errors fails criterion 1's rule about 2 ms.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench import intersite  # noqa: E402

LONG = np.arange(2, 11) / 2048.0  # Hz, one harmonic of 2048 s windows per band
SHORT = 250.0 * 10.0 ** (-np.arange(10) / 10.0)  # Hz, ten bands per decade from 250 Hz
PHI0_DEG = -1.5

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    """Print one criterion's result and keep the failures."""
    print(("PASS " if ok else "FAIL ") + message)
    if not ok:
        failures.append(message)


def make_estimate(f: np.ndarray, tau_s: float, noise_deg: float, err_deg: float, seed: int,
                  random_phase: bool = False) -> intersite.TensorEstimate:
    """Build a diagonal tensor estimate whose elements carry phi0 - 360 f tau plus noise, with stated errors.

    Args:
        f (np.ndarray): Band frequencies, Hz (used as f_mean and f_weighted).
        tau_s (float): The delay, s.
        noise_deg (float): Standard deviation of each element's phase noise, deg.
        err_deg (float): The stated error of each element's phase, deg.
        seed (int): Seed of the noise.
        random_phase (bool): Each element's phase uniform over a cycle instead.

    Returns:
        intersite.TensorEstimate: The estimate.
    """
    rng = np.random.default_rng(seed)
    n = f.size
    if random_phase:
        ph = rng.uniform(-180.0, 180.0, (n, 2))
    else:
        ph = (PHI0_DEG - 360.0 * f * tau_s)[:, None] + rng.normal(0.0, noise_deg, (n, 2))
    tensor = np.zeros((n, 2, 2), complex)
    tensor[:, 0, 0] = np.exp(1j * np.radians(ph[:, 0]))
    tensor[:, 1, 1] = np.exp(1j * np.radians(ph[:, 1]))
    sigma = np.full((n, 2, 2), math.radians(err_deg))
    det = tensor[:, 0, 0] * tensor[:, 1, 1]
    nan2 = np.full((n, 2), np.nan)
    return intersite.TensorEstimate(
        period=1.0 / f, f_lo=0.95 * f, f_hi=1.05 * f, f_mean=f.copy(), f_weighted=f.copy(),
        level=np.zeros(n, int), n_windows=np.full(n, 100), n_harm=np.ones(n, int), n_groups=np.full(n, 20),
        tensor=tensor, sigma=sigma, det=det, abs_det_err=np.full(n, 0.01),
        half_arg_deg=np.degrees(np.angle(det)) / 2.0, half_arg_err_deg=np.full(n, err_deg / math.sqrt(2.0)),
        coh_out=nan2.copy(), coh_in=nan2.copy())


def run_check(est, **kwargs):
    """Return `timing_check` of the estimate, or the exception's text when it raises."""
    try:
        return intersite.timing_check(est, **kwargs)
    except Exception as exc:  # the unfixed code takes no clock tolerance
        return f"{type(exc).__name__}: {exc}"


def fits(tc: dict) -> dict:
    """Return the fits of a check by name: arg(det) / 2 as 'det', and the elements."""
    out = {"det": tc}
    out.update({name: el for name, el in (tc.get("elements") or {}).items()})
    return out


def deviation(fit, tau_s: float) -> tuple[float, str]:
    """Return |tau - tau_s| in sigma (inf when the fit is missing or not determined) and a printable tau."""
    if fit is None or fit.get("tau_ms") is None:
        return float("inf"), "no fit"
    tau, err = fit["tau_ms"], fit["tau_err_ms"]
    if not (np.isfinite(tau) and np.isfinite(err) and err > 0):
        return float("inf"), f"not determined ({fit.get('not_determined')})"
    return abs(tau - tau_s * 1e3) / err, f"{tau:+.2f} +/- {err:.2f} ms"


def recovery_cases(f, tau_s, tol, label, seeds=10, noise=0.2, err=0.2) -> None:
    """Criteria 1, 4 and 6: every fit within 4 sigma of tau_s, and at most one beyond 3 sigma."""
    kwargs = {} if tol is None else {"clock_tolerance_s": tol}
    devs, beyond, shown = [], [], ""
    for seed in range(seeds):
        tc = run_check(make_estimate(f, tau_s, noise, err, seed), **kwargs)
        if isinstance(tc, str):
            devs.append(float("inf"))
            beyond.append(f"seed {seed}: {tc}")
            continue
        for name, fit in fits(tc).items():
            d, text = deviation(fit, tau_s)
            devs.append(d)
            if seed == 0:
                shown += f" {name} {text};"
            if d > 3.0:
                beyond.append(f"seed {seed} {name} {text} ({d:.2f} sigma)")
    devs = np.array(devs)
    ok = bool(np.all(devs <= 4.0) and np.sum(devs > 3.0) <= 1)
    check(ok, f"{label}: tau {tau_s:+g} s, {np.sum(devs > 3.0)} of {devs.size} fits beyond 3 sigma, worst "
              f"{devs.max():.2f} sigma (seed 0:{shown}) {'; '.join(beyond[:4])}")


def main() -> int:
    """Run the criteria and return the number of failures."""
    print(f"long grid {LONG.size} bands {1 / LONG.max():.1f}-{1 / LONG.min():.1f} s; "
          f"short grid {SHORT.size} bands {SHORT.min():.2f}-{SHORT.max():.0f} Hz")

    # 1. recovery
    recovery_cases(LONG, 0.5, None, "1 long grid, default tolerance")
    recovery_cases(LONG, -3.0, 3000.0, "1 long grid, tolerance 3000 s")

    # 2. alias period
    tc = run_check(make_estimate(LONG, -3.0, 0.2, 0.2, 0), clock_tolerance_s=3000.0)
    if isinstance(tc, str):
        check(False, f"2 alias period reported: {tc}")
    else:
        for name, fit, alias in (("det", tc, 1024.0), ("xx", tc["elements"]["xx"], 2048.0),
                                 ("yy", tc["elements"]["yy"], 2048.0)):
            got, half = fit.get("alias_period_s"), fit.get("scan_half_width_s")
            step = 1.0 / (360.0 * LONG.max())
            ok = got is not None and abs(got - alias) <= 2 * step and half is not None and half <= got / 2 + step
            check(ok, f"2 {name}: alias period {got} s (expected {alias:g}), scan half-width {half} s")

    # 3. beyond the bound
    for tau_s in (-3.0, 30.0):
        tc = run_check(make_estimate(LONG, tau_s, 0.2, 0.2, 1))
        if isinstance(tc, str):
            check(False, f"3 tau {tau_s:+g} s at the default tolerance: {tc}")
            continue
        for name, fit in fits(tc).items():
            reason = str(fit.get("not_determined") or "")
            ok = ("tau_ms" in fit and fit["tau_ms"] is None and fit.get("tau_err_ms") is None
                  and fit.get("determined") is False and "bound" in reason
                  and "scripts/timing_qc.py" in reason)
            check(ok, f"3 tau {tau_s:+g} s, {name}: tau {fit.get('tau_ms')} +/- {fit.get('tau_err_ms')} ms, "
                      f"determined {fit.get('determined')}, reason '{reason}'")
        try:
            json.dumps(tc, allow_nan=False)
            strict = "written"
        except ValueError as exc:
            strict = f"refused: {exc}"
        check(strict == "written", f"3 tau {tau_s:+g} s: the check as strict JSON {strict}")
        lines = intersite.timing_text(tc)
        text = " ".join(lines)
        check("delay not determined over" in text and "fewer than three" not in text,
              f"3 tau {tau_s:+g} s: timing_text prints arg(det) / 2 not determined {lines[3:]}")
        for name in ("xx", "yy"):
            check(f"arg {name}: delay not determined" in text,
                  f"3 tau {tau_s:+g} s: timing_text prints arg {name} not determined")

    # 4. zero
    recovery_cases(LONG, 0.0, None, "4 zero, default tolerance")
    recovery_cases(LONG, 0.0, 3000.0, "4 zero, tolerance 3000 s")

    # 5. noise
    for grid_name, f, err, need in (("long", LONG, 60.0, 100), ("short", SHORT, 60.0, 100),
                                    ("short", SHORT, 2.0, 100)):
        finite, examples = 0, []
        for seed in range(100):
            tc = run_check(make_estimate(f, 0.0, 0.0, err, seed, random_phase=True))
            if isinstance(tc, str):
                finite += 1
                examples.append(tc)
                continue
            if tc.get("tau_ms") is not None and np.isfinite(tc["tau_ms"]):
                finite += 1
                if len(examples) < 3:
                    examples.append(f"{tc['tau_ms']:+.1f} +/- {tc['tau_err_ms']:.1f} ms")
        check(100 - finite >= need, f"5 noise, {grid_name} grid, errors {err:g} deg: not determined in "
                                    f"{100 - finite} of 100 (at least {need}) {examples}")

    # 6. control
    recovery_cases(SHORT, 2e-3, None, "6 control, short grid", noise=0.5, err=0.5)

    print(f"{len(failures)} FAILED" if failures else "ALL PASSED")
    return len(failures)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
