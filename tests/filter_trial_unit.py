# -*- coding: utf-8 -*-
"""
Unit test for the metrics and outputs of scripts/filter_trial.py

**This test fails if**

- (a) ex's 50 Hz line excess drops by less than 20 dB after `[{notch: {f0: 50, harmonics: 1, q: 30, passes: 2}}]`;
- (b) any ey-hx coherence band mean changes by 0.05 or more after that notch, or is NaN;
- (c) ex's 99.15 Hz excess moves over 1 dB after that notch, or drops under 15 dB with `extra: [99.15]` added;
- (d) any local or remote input array differs from its copy after the filters and `trial_metrics` have run;
- (e) `write_trial` leaves out a PNG or the JSON in a temporary folder, or the JSON's chain differs from the one given;
- (premise) the raw excess of ex's 50 Hz or 99.15 Hz line is more than 2 dB from its 40 or 20 dB target;
- (mutations) any check passes the mutation built to trip it: (a) on the empty chain (raw against raw), (b) on a
  chain whose `replace` puts an independent series in hx, (c) on the 50 Hz notch for the removal half, (d) on a
  copy with one sample changed, (e) on the temporary folder before `write_trial` has run.

The synthetic window is 10 minutes at 1000 Hz, float32 like a loaded window.
A common random signal, white noise through a 4th-order 300 Hz Butterworth
low-pass, is in ey and in hx, each with independent white noise at half its
level added (squared coherence 0.64 below 300 Hz); a second one is in ex
and hy the same way. ex also carries a 50 Hz line and a 99.15 Hz line, both
whole cycles per 20 s Welch segment. At the line metrics' resolution (N =
20000 points, Hann) a line of amplitude A has a peak density of A^2 N / (3
fs) over a floor of 2 (1 + 0.5^2) / fs, so A = sqrt(R 7.5 / N) puts it R
over the floor: 1.936 for 40 dB and 0.1936 for 20 dB. The coherence uses
the band scheme `scripts/filter_trial.py` builds from a `processing:`
block of min_period 0.005 s, max_period 5000 s, 10 periods per decade and
notches at 50 and 150 Hz.

Usage:
    python -m pytest tests/filter_trial_unit.py -q
    python tests/filter_trial_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import filter_trial as ft  # noqa: E402
from crust.noise import apply_filters_arrays  # noqa: E402

FS = 1000.0
MINUTES = 10.0
N = int(round(MINUTES * 60.0 * FS))
SEED = 20260925
NOISE = 0.5  # independent noise, relative to the common signal
LP_HZ = 300.0
NPERSEG = int(round(FS / ft.WELCH_DF))
TARGET_50_DB, TARGET_99_DB = 40.0, 20.0
F_99 = 99.15
AMP_50 = float(np.sqrt(10 ** (TARGET_50_DB / 10) * 6.0 * (1.0 + NOISE**2) / NPERSEG))
AMP_99 = float(np.sqrt(10 ** (TARGET_99_DB / 10) * 6.0 * (1.0 + NOISE**2) / NPERSEG))
LINES = (F_99,)
PROCESSING = {"min_period": 0.005, "max_period": 5000.0, "periods_per_decade": 10.0,
              "notch_frequencies": [50.0, 150.0]}
NOTCH_50 = [{"notch": {"f0": 50, "harmonics": 1, "q": 30, "passes": 2}}]
NOTCH_50_EXTRA = [{"notch": {"f0": 50, "harmonics": 1, "q": 30, "passes": 2, "extra": [F_99]}}]
REPLACE_HX = [{"replace": {"hx": "NOISE"}}]


def _synthetic(seed: int = SEED) -> dict[str, np.ndarray]:
    """Build the synthetic window of the module docstring, float32 per channel."""
    rng = np.random.default_rng(seed)
    sos = signal.butter(4, LP_HZ, fs=FS, output="sos")
    s1 = signal.sosfilt(sos, rng.standard_normal(N))
    s2 = signal.sosfilt(sos, rng.standard_normal(N))
    t = np.arange(N) / FS
    lines = AMP_50 * np.cos(2 * np.pi * 50.0 * t + 0.3) + AMP_99 * np.cos(2 * np.pi * F_99 * t + 1.1)
    out = {
        "hx": s1 + NOISE * rng.standard_normal(N),
        "hy": s2 + NOISE * rng.standard_normal(N),
        "ex": s2 + NOISE * rng.standard_normal(N) + lines,
        "ey": s1 + NOISE * rng.standard_normal(N),
    }
    return {c: a.astype("float32") for c, a in out.items()}


@lru_cache(maxsize=None)
def window() -> dict[str, np.ndarray]:
    """The synthetic window, built once."""
    return _synthetic()


@lru_cache(maxsize=None)
def scheme() -> dict:
    """The band scheme of the script for PROCESSING at FS."""
    return ft.band_scheme(FS, PROCESSING)


def _donors() -> dict:
    """A donor whose hx is white noise independent of the window."""
    return {"NOISE": {"hx": np.random.default_rng(SEED + 1).standard_normal(N).astype("float32")}}


CHAINS = {"empty": [], "notch50": NOTCH_50, "notch50_extra": NOTCH_50_EXTRA, "replace_hx": REPLACE_HX}


@lru_cache(maxsize=None)
def filtered(name: str) -> dict[str, np.ndarray]:
    """The window through one of CHAINS."""
    out, _ = apply_filters_arrays(window(), FS, CHAINS[name], tag="synthetic", donors=_donors(), workers=4)
    return out


@lru_cache(maxsize=None)
def metrics(name: str) -> dict:
    """`trial_metrics` of the raw window ("raw") or of a chain of CHAINS."""
    arrays = window() if name == "raw" else filtered(name)
    return ft.trial_metrics(arrays, FS, scheme(), LINES)


def excess(m: dict, comp: str, f0: float) -> float:
    """The line excess of `comp` at `f0` in a `trial_metrics` result."""
    i = [k for k, f in enumerate(m["lines_hz"]) if abs(f - f0) < 1e-6]
    assert i, f"{f0:g} Hz is not among the evaluated lines {m['lines_hz']}"
    return float(m["line_excess_db"][comp][i[0]])


# ---------------------------------------------------------------- checks, each returning (ok, detail)


def check_a(raw: dict, filt: dict) -> tuple[bool, str]:
    """ex's 50 Hz excess drops by at least 20 dB."""
    drop = excess(raw, "ex", 50.0) - excess(filt, "ex", 50.0)
    return drop >= 20.0, f"50 Hz on ex: {excess(raw, 'ex', 50.0):+.1f} -> {excess(filt, 'ex', 50.0):+.1f} dB"


def check_b(raw: dict, filt: dict) -> tuple[bool, str]:
    """Every ey-hx coherence band mean changes by less than 0.05."""
    r = raw["coherence"]["ey-hx"]["band_means"]
    f = filt["coherence"]["ey-hx"]["band_means"]
    diffs = [abs(f[g] - r[g]) for g in r]
    ok = all(np.isfinite(d) and d < 0.05 for d in diffs)
    return ok, ", ".join(f"{g} {r[g]:.3f}->{f[g]:.3f}" for g in r)


def check_c_kept(raw: dict, filt: dict) -> tuple[bool, str]:
    """ex's 99.15 Hz excess moves by at most 1 dB."""
    d = excess(filt, "ex", F_99) - excess(raw, "ex", F_99)
    return abs(d) <= 1.0, f"99.15 Hz on ex moved {d:+.2f} dB"


def check_c_removed(raw: dict, filt: dict) -> tuple[bool, str]:
    """ex's 99.15 Hz excess drops by at least 15 dB."""
    drop = excess(raw, "ex", F_99) - excess(filt, "ex", F_99)
    return drop >= 15.0, f"99.15 Hz on ex dropped {drop:+.1f} dB"


def check_d(before: dict, after: dict) -> tuple[bool, str]:
    """Every array equals its copy."""
    changed = [c for c in before if not np.array_equal(before[c], after[c])]
    return not changed, f"changed: {changed or 'none'}"


def check_e(out_dir: Path, stem: str, chain: list) -> tuple[bool, str]:
    """The three PNGs and the JSON exist, the PNGs are PNGs and the JSON holds the chain."""
    pngs = [out_dir / f"{stem}_{p}.png" for p in ("psd", "timeseries", "coherence")]
    js = out_dir / f"{stem}.json"
    missing = [p.name for p in [*pngs, js] if not p.exists() or p.stat().st_size == 0]
    if missing:
        return False, f"missing: {missing}"
    bad = [p.name for p in pngs if p.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"]
    doc = json.loads(js.read_text(encoding="utf-8"))
    ok = not bad and doc.get("chain") == chain and "line_excess_db" in doc.get("filtered", {})
    return ok, f"non-PNG: {bad or 'none'}, chain {doc.get('chain')}"


# ---------------------------------------------------------------- tests


def test_premise_line_levels() -> None:
    raw = metrics("raw")
    e50, e99 = excess(raw, "ex", 50.0), excess(raw, "ex", F_99)
    assert abs(e50 - TARGET_50_DB) <= 2.0 and abs(e99 - TARGET_99_DB) <= 2.0, f"{e50:+.1f}, {e99:+.1f} dB"


def test_a_notch_removes_50_hz() -> None:
    ok, detail = check_a(metrics("raw"), metrics("notch50"))
    assert ok, detail


def test_a_trips_on_empty_chain() -> None:
    ok, detail = check_a(metrics("raw"), metrics("empty"))
    assert not ok, f"check (a) passed raw against raw: {detail}"


def test_b_notch_keeps_coherence() -> None:
    ok, detail = check_b(metrics("raw"), metrics("notch50"))
    assert ok, detail


def test_b_trips_on_replaced_hx() -> None:
    ok, detail = check_b(metrics("raw"), metrics("replace_hx"))
    assert not ok, f"check (b) passed an hx replaced by independent noise: {detail}"


def test_c_99_hz_kept_then_removed() -> None:
    ok, detail = check_c_kept(metrics("raw"), metrics("notch50"))
    assert ok, detail
    ok, detail = check_c_removed(metrics("raw"), metrics("notch50_extra"))
    assert ok, detail


def test_c_trips_on_50_hz_notch() -> None:
    ok, detail = check_c_removed(metrics("raw"), metrics("notch50"))
    assert not ok, f"check (c) counted 99.15 Hz as removed by the 50 Hz notch: {detail}"


def test_d_inputs_unchanged() -> None:
    arrays = _synthetic()
    other = _synthetic(SEED + 2)
    remote = {c: other[c] for c in ("hx", "hy")}
    before = {c: a.copy() for c, a in arrays.items()}
    remote_before = {c: a.copy() for c, a in remote.items()}
    ft.trial_metrics(arrays, FS, scheme(), LINES, remote)
    for chain in CHAINS.values():
        out, _ = apply_filters_arrays(arrays, FS, chain, tag="synthetic", donors=_donors(), workers=4)
        m = ft.trial_metrics(out, FS, scheme(), LINES, remote)
    assert "hx-r_hx" in m["coherence"], list(m["coherence"])
    ok, detail = check_d(before, arrays)
    assert ok, detail
    ok, detail = check_d(remote_before, remote)
    assert ok, detail


def test_d_trips_on_changed_copy() -> None:
    before = {c: a.copy() for c, a in window().items()}
    after = {c: a.copy() for c, a in window().items()}
    after["ey"][N // 2] += 1.0
    ok, detail = check_d(before, after)
    assert not ok, f"check (d) missed a changed sample: {detail}"


def test_e_writes_outputs() -> None:
    info = {"site": "SYN", "label": "notch50", "t0": "2026-01-01T00:00:00+00:00", "chain": NOTCH_50}
    with tempfile.TemporaryDirectory() as tmp:
        stem = "SYN_notch50_20260101T0000"
        paths = ft.write_trial(Path(tmp), stem, info, metrics("raw"), metrics("notch50"), window(),
                               filtered("notch50"))
        ok, detail = check_e(Path(tmp), stem, NOTCH_50)
        assert ok, detail
        assert [p.name for p in paths] == [f"{stem}_psd.png", f"{stem}_timeseries.png", f"{stem}_coherence.png",
                                           f"{stem}.json"]


def test_e_trips_before_writing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ok, detail = check_e(Path(tmp), "SYN_notch50_20260101T0000", NOTCH_50)
        assert not ok, f"check (e) passed an empty folder: {detail}"


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("The synthetic window")[0].strip())
    print()
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        else:
            print(f"  ok    {test.__name__}")
    print(f"\n{'FAIL' if failed else 'PASS'}  filter_trial_unit ({len(tests) - len(failed)} of {len(tests)} passed)")
    sys.exit(1 if failed else 0)
