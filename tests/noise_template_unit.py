# -*- coding: utf-8 -*-
"""
Unit test for the `template` kind of mt_workbench.noise

The synthetic is 8 h at 10 Hz. A glitch shaped as a trapezoid (flat 0.5 s,
0.1 s ramps, 0.7 s at its foot, the Orange Box's once-a-minute step) repeats
every 59.9967 s, so its phase moves through the UTC minute by 0.2 s per
hour as the Kalgoorlie 2006 boxes' does, the first at 23.4 s; it is +0.30
on hx and -0.15 on hy, and absent from hz. Every channel carries a 40 s sine
(amplitude 2, phases 30, 70 and 110 deg), a 3,600 s sine (amplitude 20) and
white noise (0.05 rms). The glitch is evaluated in continuous time at each
sample, so its samples differ from cycle to cycle as the phase moves.

The measures are taken with numpy alone: the glitch's amplitude by least
squares on the known glitch waveform jointly with the two sines and a
constant; the glitch's fold as the mean, over every true glitch, of the
series less the clean synthetic at the sample nearest each glitch centre
and its neighbours (the largest of the 13 mean values); the 40 s sine's
amplitude and phase by the same least squares on the output and on the
clean synthetic (no glitch, the same noise).

Usage:
    python tests/noise_template_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test
fails if**

- the glitch's least-squares amplitude or its fold on hx or hy is not
  reduced by 95 % or more;
- the 40 s sine's amplitude on hx, hy or hz differs from the clean
  synthetic's by more than 0.1 %, or its phase by more than 0.1 deg;
- an output channel's length differs from its input's, or the run path
  (`apply_filters` on a run-like object holding an xarray Dataset) changes
  the time axis or gives other samples than `apply_filters_arrays`;
- the fitted period differs from 59.9967 s by more than 0.0005 s, or the
  first glitch centre from 23.4 s by more than 0.05 s (half a sample);
- controls: hz, which carries no glitch, is not identical to its input
  (left by the significance gate, marked "(left)"); a record with no
  glitch on any channel is not returned unchanged with "nothing
  subtracted"; a record of 2.5 h (fewer than 30 cycles once 1 h is left out
  at each end) is not returned unchanged with "nothing subtracted"; an
  input array changes (SHA-1 of its bytes); an unknown `estimate` or a
  width at or above the period is not refused.
"""

import hashlib
import sys
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mt_workbench.noise import apply_filters, apply_filters_arrays  # noqa: E402

FS = 10.0
HOURS = 8.0
PERIOD = 59.9967
FIRST = 23.4
AMP = {"hx": 0.30, "hy": -0.15, "hz": 0.0}
PHASE40 = {"hx": 30.0, "hy": 70.0, "hz": 110.0}
FAILS = []


def check(ok: bool, text: str) -> None:
    """Print a PASS or FAIL line and keep the failures."""
    print(("PASS " if ok else "FAIL ") + text)
    if not ok:
        FAILS.append(text)


def trapezoid(t: np.ndarray) -> np.ndarray:
    """The glitch shape: 1 for |t| <= 0.25 s, 0 beyond 0.35 s, straight between."""
    return np.clip((0.35 - np.abs(t)) / 0.1, 0.0, 1.0)


def glitch_times(n: int) -> np.ndarray:
    """Centres in s of every glitch of an n-sample record."""
    return FIRST + PERIOD * np.arange(int(n / FS / PERIOD) + 1)


def waveform(n: int) -> np.ndarray:
    """The unit glitch train evaluated at every sample (continuous-time centres)."""
    t = np.arange(n) / FS
    g = np.zeros(n)
    for tc in glitch_times(n):
        i0, i1 = max(0, int((tc - 1.0) * FS)), min(n, int((tc + 1.0) * FS) + 1)
        g[i0:i1] += trapezoid(t[i0:i1] - tc)
    return g


def synthetic(hours: float, glitch: bool = True, seed: int = 7):
    """Return (with_glitch, clean, unit_waveform) dicts/arrays of `hours` at FS."""
    n = int(hours * 3600 * FS)
    t = np.arange(n) / FS
    rng = np.random.default_rng(seed)
    g = waveform(n)
    clean, dirty = {}, {}
    for c in ("hx", "hy", "hz"):
        base = (2.0 * np.cos(2 * np.pi * t / 40.0 + np.radians(PHASE40[c]))
                + 20.0 * np.sin(2 * np.pi * t / 3600.0) + rng.normal(0.0, 0.05, n))
        clean[c] = base
        dirty[c] = base + (AMP[c] * g if glitch else 0.0)
    return dirty, clean, g


def lsq(y: np.ndarray, g: np.ndarray):
    """Least squares of y on [g, cos40, sin40, cos3600, sin3600, 1]; return (glitch amp, sine amp, sine phase deg)."""
    t = np.arange(y.size) / FS
    w40, w36 = 2 * np.pi / 40.0, 2 * np.pi / 3600.0
    A = np.column_stack([g, np.cos(w40 * t), -np.sin(w40 * t), np.cos(w36 * t), np.sin(w36 * t), np.ones_like(t)])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef[0], float(np.hypot(coef[1], coef[2])), float(np.degrees(np.arctan2(coef[2], coef[1])))


def fold_peak(resid: np.ndarray) -> float:
    """The largest |mean| over glitches of resid at the nearest sample to each centre, offsets -6..+6."""
    n = resid.size
    centres = np.round(glitch_times(n) * FS).astype(int)
    offs = np.arange(-6, 7)
    idx = centres[:, None] + offs[None, :]
    ok = np.all((idx >= 0) & (idx < n), axis=1)
    return float(np.max(np.abs(resid[idx[ok]].mean(axis=0))))


def sha(a: np.ndarray) -> str:
    """SHA-1 of an array's bytes."""
    return hashlib.sha1(np.ascontiguousarray(a).tobytes()).hexdigest()


class _Run:
    """A run-like object: `apply_filters` reads and writes `run.dataset`."""

    def __init__(self, arrays: dict):
        n = len(next(iter(arrays.values())))
        time = np.datetime64("2006-05-04T00:00:00") + (np.arange(n) * 100).astype("timedelta64[ms]")
        self.dataset = xr.Dataset({c: ("time", np.array(a)) for c, a in arrays.items()}, coords={"time": time})


def main() -> int:
    spec = [{"template": {"period_s": 60.0, "width_s": 2.0}}]
    dirty, clean, g = synthetic(HOURS)
    before = {c: sha(a) for c, a in dirty.items()}
    out, lines = apply_filters_arrays(dirty, FS, spec, tag="synthetic")
    print("provenance:", lines[0])

    # controls first
    check(sha(out["hz"]) == sha(dirty["hz"]) and "hz" in lines[0] and "(left)" in lines[0].split("hz", 1)[1][:40],
          "control: hz (no glitch) is identical to its input and marked (left)")
    quiet, _c, _g = synthetic(HOURS, glitch=False, seed=11)
    qout, qlines = apply_filters_arrays(quiet, FS, spec, tag="quiet")
    check(all(sha(qout[c]) == sha(quiet[c]) for c in quiet) and "nothing subtracted" in qlines[0],
          f"control: a record with no glitch is unchanged ({qlines[0][:90]})")
    short, _c, _g = synthetic(2.5, seed=13)
    sout, slines = apply_filters_arrays(short, FS, spec, tag="short")
    check(all(sha(sout[c]) == sha(short[c]) for c in short) and "nothing subtracted" in slines[0],
          f"control: a 2.5 h record is unchanged ({slines[0][:90]})")
    check(all(sha(dirty[c]) == before[c] for c in dirty), "control: no input array changed")
    for bad, why in (({"estimate": "mean"}, "estimate mean"), ({"width_s": 60.0}, "width at the period")):
        try:
            apply_filters_arrays(dirty, FS, [{"template": bad}], tag="bad")
            check(False, f"control: {why} refused")
        except ValueError as exc:
            check(True, f"control: {why} refused ({str(exc)[:70]})")

    # the timing
    import re
    m = re.search(r"period ([0-9.]+) s .* first glitch ([0-9.]+) s", lines[0])
    period, first = float(m.group(1)), float(m.group(2))
    check(abs(period - PERIOD) <= 0.0005, f"fitted period {period:.5f} s against {PERIOD} s (<= 0.0005 s)")
    check(abs(first - FIRST) <= 0.05, f"first glitch {first:.3f} s against {FIRST} s (<= 0.05 s)")

    # the glitch and the sine
    for c in ("hx", "hy", "hz"):
        check(len(out[c]) == len(dirty[c]), f"{c}: length {len(out[c])} unchanged")
        a_in, amp_clean, ph_clean = lsq(dirty[c], g)
        a_out, amp_out, ph_out = lsq(out[c], g)
        _a, amp_clean2, ph_clean2 = lsq(clean[c], g)
        if c != "hz":
            red = 1.0 - abs(a_out) / abs(a_in)
            check(red >= 0.95, f"{c}: glitch amplitude by least squares {a_in:+.4f} -> {a_out:+.5f} "
                  f"(reduced {100 * red:.2f} %, >= 95 %)")
            f_in, f_out = fold_peak(dirty[c] - clean[c]), fold_peak(out[c] - clean[c])
            red = 1.0 - f_out / f_in
            check(red >= 0.95, f"{c}: glitch fold peak {f_in:.4f} -> {f_out:.5f} (reduced {100 * red:.2f} %, >= 95 %)")
        rel = abs(amp_out / amp_clean2 - 1.0)
        dph = abs((ph_out - ph_clean2 + 180.0) % 360.0 - 180.0)
        check(rel <= 1e-3 and dph <= 0.1, f"{c}: 40 s sine amplitude {amp_clean2:.5f} -> {amp_out:.5f} "
              f"({100 * rel:.4f} %, <= 0.1 %), phase {ph_clean2:.4f} -> {ph_out:.4f} deg ({dph:.4f}, <= 0.1)")

    # the run path: the time axis and the samples
    run = _Run(dirty)
    t_before = run.dataset.time.values.copy()
    rlines = apply_filters(run, spec, FS, tag="run")
    same = all(np.array_equal(run.dataset[c].values, out[c]) for c in out)
    check(np.array_equal(run.dataset.time.values, t_before) and same and rlines == lines,
          "run path: the time axis unchanged and the samples and provenance equal apply_filters_arrays'")

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
