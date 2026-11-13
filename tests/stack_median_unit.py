# -*- coding: utf-8 -*-
"""
Unit test for the band median stack and the engine hooks of the Stacks tab

Covers the library half of the Stacks tab's median stack:

- `intersite.stack_band(method="median")` and `band_stack(method=...)`: the
  marginal median of the kept members' scaled spectra, per window and
  harmonic, on random spectra with absent members, rejected windows and
  windows under `min_members`;
- `intersite.select_stack(rate=, runs_of=)` on a scratch survey whose
  archives are real MTH5 files written with mth5: three sites at 100 Hz,
  four at 1 Hz (one with no archive, one covering half the window);
- `virtual.stack_arrays(weighting=)`, `build_synthetic_remote(provenance=)`
  and `recorded_provenance` on members written by
  tests/virtual_unit.py's `write_archive` (1000 Hz, 1900 s).

Every expected value is computed here, not read from the code under test:
the median by a per-window loop over `np.median` of the real and imaginary
parts, the provenance as the dict given, the comments as literal strings.

Usage:
    python tests/stack_median_unit.py [--quick]

``--quick`` skips criterion 10 (the four existing stack suites, about six
minutes).

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. `stack_band(method="median")` on random spectra (6 members; absent
   windows, one member partly absent in one harmonic, a few windows
   rejected, windows with fewer than `min_members` kept) differs in any
   window from the hand computation (each member over the square root of
   the median of its band power, rejection over 25 times the window's
   median normalised power, then `np.median` of the kept members' real and
   imaginary parts separately, cast to complex64) by more than 1e-6 of the
   largest value (the hand computation squares in float64, the code in
   float32); or, given the code's own scales and kept members, differs in
   any bit from that per-window `np.median`; or keeps other members than
   the hand computation; or holds a finite value in a window with fewer
   than `min_members` kept; or its count, scale,
   power, level, present or rejected arrays differ in any bit from the
   mean's; or the data hold no rejected window, no window under
   `min_members`, or no even or no odd kept count (the test would not
   reach those branches);
2. with exactly two members kept the median differs from the mean in any
   bit (in the windows of the six-member spectra that keep two, and on a
   two-member array), or, as the control that the comparison can fail,
   the median equals the mean in every window keeping three or more;
3. the values [1+10j, 2+0j, 3+5j] (equal scales, 1.0) do not stack to
   2+5j exactly, or numpy's own median of them is 2+5j (the control: it
   must be 2+0j, the lexicographic order);
4. any of the calls of 1-3, and a stack with a window where every member is
   absent, raises under `warnings.simplefilter("error")`;
5. one member multiplied by 1000 in 10 % of the windows, with
   `reject_factor=1e9` (no rejection), leaves the median's mean squared
   error against the common signal not at least ten times smaller than the
   mean's; or a window is rejected at 1e9; or, as the control, the default
   25 rejects none of the outlier windows;
6. `method="mode"` does not raise ValueError in `stack_band` or in
   `band_stack`; `band_stack(method="median")` yields a stack channel that
   differs in any bit from `stack_band(method="median")` at the kept
   windows, or equals the mean's; or `band_stack(method="mean")` differs in
   any bit from the default `band_stack()`;
7. `virtual.stack_arrays` with `weighting="none"` or `"coherence"` gives an
   array (and, for coherence, weights) different in any bit from
   `_mean_stack` or `_coherence_stack` on the same members, ``"none"``
   gives info other than {}, the two weightings give the same array (the
   control), or `weighting="median"` does not raise ValueError;
8. `build_synthetic_remote(provenance=...)` writes hx or hy that differs in
   any bit from the build without it (unweighted and coherence-weighted);
   `recorded_provenance` does not return the dict given (holding a "|", a
   newline and the text "provenance: " in its recipe text); the station
   comment is not today's string plus "; recipe=<name>
   recipe_hash=<hash>"; the coherence build's run comment is not its
   comment without provenance, a newline and the provenance line; a build
   without provenance has a run comment that is not empty, a station
   comment other than virtual_unit check 1's string, or a provenance that
   is not None; `recorded_provenance` gives other than None for a missing
   file or station; or a provenance without a recipe hash does not raise
   ValueError, or changes a byte of an existing archive with
   ``overwrite=True``;
9. `select_stack(rate=1.0, local=None)` misses a 1 Hz site that covers the
   window, keeps a 100 Hz site, or words a reason other than "100 Hz, the
   stack is at 1 Hz", "its runs with hx/hy cover 0.50 h of the window,
   under 1 h" and "no archive at <path>"; with a 1 Hz local, the 100 Hz
   reason is not "100 Hz, the pair is at 1 Hz"; a 100 Hz local with
   rate=1.0, or neither local nor rate, does not raise ValueError; the
   default call (local at 100 Hz, no rate) changes its lists or wording;
   a `runs_of` that returns `archive_runs`' own runs gives lists that
   differ from the default's, or is called with other arguments than
   (site, the raw archive's path, ("hx", "hy")), or for a site with no
   archive or at another rate; a `runs_of` returning None for one site
   does not leave that site out with `NOT_READ` and only it; a call with
   `runs_of` opens a file (h5py.File or open), or, as the control, the
   default call opens none;
10. tests/virtual_unit.py, tests/intersite_stack_unit.py,
    tests/intersite_basestack_unit.py or tests/intersite_basestack_h_unit.py
    exits other than 0 (not run with ``--quick``).
"""

from __future__ import annotations

import builtins
import json
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import virtual_unit as vu  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite, virtual  # noqa: E402
from mt_workbench.ingest import archive_identity, default_archive_path  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRATCH = scratch_dir("stack_median_unit")
SUITES = ("virtual_unit.py", "intersite_stack_unit.py", "intersite_basestack_unit.py",
          "intersite_basestack_h_unit.py")

failures: list[str] = []


def check(ok, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def raises_value_error(fn) -> str:
    """Return the ValueError message `fn()` raises, or "" when it raises none."""
    try:
        fn()
    except ValueError as exc:
        return str(exc) or "ValueError"
    return ""


def same_bits(a: np.ndarray, b: np.ndarray) -> bool:
    """Return whether two arrays have the same shape, dtype and bytes."""
    a, b = np.asarray(a), np.asarray(b)
    return a.shape == b.shape and a.dtype == b.dtype and a.tobytes() == b.tobytes()


# ----------------------------------------------------------------- the band stack


def random_spectra(rng, n_members=6, n_windows=400, n_harm=5) -> np.ndarray:
    """Return complex64 spectra with absent members, a partial absence and loud windows.

    Windows 0-19 hold members 0 and 1 only; 20-29 hold members 0-2 only;
    30-39 hold no member; elsewhere each member is absent in about 12 % of
    the windows; member 3 lacks one harmonic in windows 100-104 (absent
    there); member 1 is 300 times louder in 4 % of the windows (rejected).
    """
    X = (rng.standard_normal((n_members, n_windows, n_harm))
         + 1j * rng.standard_normal((n_members, n_windows, n_harm))).astype(np.complex64)
    X *= (1.0 + 0.5 * np.arange(n_members))[:, None, None].astype(np.float32)  # members on different scales
    absent = rng.random((n_members, n_windows)) < 0.12
    absent[:, :40] = False
    absent[2:, :20] = True
    absent[3:, 20:30] = True
    absent[:, 30:40] = True
    X[absent] = np.nan
    X[3, 100:105, 2] = np.nan
    loud = rng.choice(np.arange(40, n_windows), size=n_windows // 25, replace=False)
    X[1, loud] *= 300.0
    return X


def hand_median(X: np.ndarray, reject_factor: float, min_members: int) -> tuple[np.ndarray, np.ndarray]:
    """Return the median stack computed window by window here, and the kept mask."""
    n_members, n_windows, n_harm = X.shape
    present = np.all(np.isfinite(X), axis=2)
    band_power = np.mean(np.abs(X.astype(np.complex128)) ** 2, axis=2)
    scale = np.full(n_members, np.nan)
    for m in range(n_members):
        if present[m].any():
            scale[m] = np.sqrt(np.median(band_power[m, present[m]]))
    kept = np.zeros((n_members, n_windows), dtype=bool)
    out = np.full((n_windows, n_harm), np.nan + 1j * np.nan, dtype=np.complex64)
    for w in range(n_windows):
        here = [m for m in range(n_members) if present[m, w]]
        if not here:
            continue
        power = {m: band_power[m, w] / scale[m] ** 2 for m in here}
        level = np.median([power[m] for m in here])
        for m in here:
            kept[m, w] = not power[m] > reject_factor * level
        rows = [m for m in here if kept[m, w]]
        if len(rows) < min_members:
            continue
        values = np.array([X[m, w] / scale[m] for m in rows])
        out[w] = (np.median(values.real, axis=0) + 1j * np.median(values.imag, axis=0)).astype(np.complex64)
    return out, kept


def check_band_median() -> None:
    """Criteria 1-6."""
    rng = np.random.default_rng(5)
    X = random_spectra(rng)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            med = intersite.stack_band(X, min_members=3, method="median")
            mean = intersite.stack_band(X, min_members=3, method="mean")
            med2 = intersite.stack_band(X, min_members=2, method="median")
            mean2 = intersite.stack_band(X, min_members=2)
            ok_warn = True
        except Exception as exc:  # a warning raised as an error
            ok_warn = False
            print(f"   raised under warnings-as-errors: {type(exc).__name__}: {exc}")
    check(ok_warn, "4. stack_band (mean and median, min_members 2 and 3, a window with no member) raises no "
                   "warning")
    if not ok_warn:
        return

    # 1. the hand computation
    hand, kept = hand_median(X, intersite.STACK_REJECT_FACTOR, 3)
    count = kept.sum(axis=0)
    print(f"   windows: {X.shape[1]}, rejected member-windows {int(med['rejected'].sum())}, under 3 kept "
          f"{int((count < 3).sum())}, even counts >= 3 {int(((count >= 3) & (count % 2 == 0)).sum())}, odd "
          f"counts >= 3 {int(((count >= 3) & (count % 2 == 1)).sum())}")
    check(med["rejected"].sum() > 0 and (count < 3).sum() > 0 and ((count >= 3) & (count % 2 == 0)).any()
          and ((count >= 3) & (count % 2 == 1)).any(),
          "1. the data reach rejection, windows under min_members, and even and odd kept counts")
    check(np.array_equal(kept, med["present"] & ~med["rejected"]), "1. the kept members are those computed here")
    finite = np.isfinite(hand).all(axis=1)
    diff = float(np.abs(med["stack"][finite] - hand[finite]).max())
    top = float(np.abs(hand[finite]).max())
    check(np.array_equal(np.isfinite(med["stack"]).all(axis=1), finite) and diff <= 1e-6 * top,
          f"1. the median equals the hand computation in every window (max |diff| {diff:.3g}, "
          f"{diff / top:.2g} of the largest value)")
    own = np.full_like(hand, np.nan + 1j * np.nan)
    for w in np.flatnonzero(med["count"] >= 3):
        rows = np.flatnonzero(med["present"][:, w] & ~med["rejected"][:, w])
        values = np.array([X[m, w] / med["scale"][m] for m in rows])
        own[w] = (np.median(values.real, axis=0) + 1j * np.median(values.imag, axis=0)).astype(np.complex64)
    check(same_bits(med["stack"], own), "1. given the code's scales and kept members, the median is the "
                                        "per-window np.median of each part, exactly")
    check(not np.isfinite(med["stack"][count < 3]).any(), "1. no value in a window with fewer than 3 kept")
    keys = ("count", "scale", "power", "level", "present", "rejected")
    check(all(same_bits(med[k], mean[k]) for k in keys),
          "1. count, scale, power, level, present and rejected are the mean's, exactly")

    # 2. two kept members
    two = med2["count"] == 2
    many = med2["count"] >= 3
    check(two.sum() >= 20 and same_bits(med2["stack"][two], mean2["stack"][two]),
          f"2. the median is exactly the mean in the {int(two.sum())} windows keeping two members")
    pair = intersite.stack_band(X[:2], method="median")
    pair_mean = intersite.stack_band(X[:2], method="mean")
    check(same_bits(pair["stack"], pair_mean["stack"]), "2. on a two-member array the median is exactly the "
                                                        "mean (NaN windows included)")
    n_differ = int(np.any(med2["stack"][many] != mean2["stack"][many], axis=1).sum())
    check(n_differ > 0.9 * many.sum(), f"2. control: the median differs from the mean in {n_differ} of "
                                       f"{int(many.sum())} windows keeping three or more")

    # 3. the marginal median, not numpy's complex order
    values = np.array([1 + 10j, 2 + 0j, 3 + 5j])
    Y = np.ones((3, 5, 1), dtype=np.complex64)
    Y[:, 0, 0] = values
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        res = intersite.stack_band(Y, method="median")
    check(np.all(res["scale"] == 1.0) and res["stack"][0, 0] == 2 + 5j,
          f"3. [1+10j, 2+0j, 3+5j] stacks to {complex(res['stack'][0, 0])} (2+5j), scales {res['scale'].tolist()}")
    check(np.median(values) == 2 + 0j, f"3. control: numpy's complex median is {np.median(values)} (2+0j)")

    # 5. one member far out in 10 % of the windows, nothing rejected
    n_windows, n_harm = 2000, 4
    common = rng.standard_normal((n_windows, n_harm)) + 1j * rng.standard_normal((n_windows, n_harm))
    Z = np.stack([common + 0.1 * (rng.standard_normal((n_windows, n_harm))
                                  + 1j * rng.standard_normal((n_windows, n_harm))) for _ in range(6)])
    out = rng.choice(n_windows, size=n_windows // 10, replace=False)
    Z[0, out] *= 1000.0
    Z = Z.astype(np.complex64)
    a = intersite.stack_band(Z, reject_factor=1e9, method="mean")
    b = intersite.stack_band(Z, reject_factor=1e9, method="median")
    truth = common / np.nanmean(b["scale"])
    err_mean = float(np.mean(np.abs(a["stack"] - truth) ** 2))
    err_median = float(np.mean(np.abs(b["stack"] - truth) ** 2))
    check(a["rejected"].sum() == 0 and b["rejected"].sum() == 0, "5. reject_factor 1e9 rejects no window")
    check(err_median * 10 <= err_mean, f"5. outlier member: median error {err_median:.3g}, mean error "
                                       f"{err_mean:.3g} (ratio {err_mean / err_median:.3g}, at least 10)")
    default = intersite.stack_band(Z, method="median")
    check(default["rejected"][0, out].all(), "5. control: the default 25x rejection leaves out every outlier "
                                             "window")

    # 6. the method's checks and band_stack's plumbing
    check(bool(raises_value_error(lambda: intersite.stack_band(X, method="mode"))),
          "6. stack_band(method='mode') raises ValueError")
    nw = X.shape[1]
    band = intersite.BandSpectra(0, 1.0, 2.0, np.linspace(1.0, 1.9, X.shape[2]), np.arange(nw, dtype=float), 1e3,
                                 {f"s{m}_ex": X[m] for m in range(X.shape[0])})
    members = [(f"M{m}", {"ex": f"s{m}_ex"}) for m in range(X.shape[0])]
    out_keys = {"ex": "r_ex"}
    check(bool(raises_value_error(lambda: list(intersite.band_stack([band], members, out_keys, min_members=3,
                                                                    method="mode")))),
          "6. band_stack(method='mode') raises ValueError")
    got = {}
    for method in (None, "mean", "median"):
        kwargs = {} if method is None else {"method": method}
        bands = list(intersite.band_stack([band], members, out_keys, min_members=3, **kwargs))
        got[method] = bands[0].spectra["r_ex"] if bands else None
    keep = med["count"] >= 3
    check(got["median"] is not None and same_bits(got["median"], med["stack"][keep]),
          "6. band_stack(method='median') yields stack_band's median at the kept windows, exactly")
    check(got["mean"] is not None and not np.array_equal(got["median"], got["mean"]),
          "6. band_stack's median differs from its mean")
    check(got[None] is not None and same_bits(got["mean"], got[None]),
          "6. band_stack(method='mean') is the default band_stack, exactly")


# ----------------------------------------------------------------- the time-domain stack


def member_arrays(rng, fs: float, n: int, n_members: int = 4) -> dict:
    """Return float64 members: a common field plus own noise, each with its offset and gain; one noisy member."""
    field = 1000.0 * rng.standard_normal(n)
    out = {}
    for k in range(n_members):
        noise = (200.0 if k else 2000.0) * rng.standard_normal(n)
        out[f"A{k}"] = 1e7 * (k + 1) + (0.9 + 0.05 * k) * field + noise
    return out


def check_stack_arrays() -> None:
    """Criterion 7."""
    fs = 100.0
    n = 3 * int(virtual.WEIGHT_CHUNK_S * fs) + 1234
    arrays = member_arrays(np.random.default_rng(7), fs, n)
    none, info_none = virtual.stack_arrays(arrays, fs, "none")
    default, info_default = virtual.stack_arrays(arrays, fs)
    coh, info = virtual.stack_arrays(arrays, fs, "coherence")
    ref_coh, ref_info = virtual._coherence_stack(arrays, fs)
    check(same_bits(none, virtual._mean_stack(arrays, fs)) and info_none == {},
          "7. stack_arrays('none') is exactly _mean_stack, info {}")
    check(same_bits(default, none) and info_default == {}, "7. stack_arrays default weighting is 'none'")
    check(same_bits(coh, ref_coh) and same_bits(info["weights"], ref_info["weights"])
          and info["members"] == ref_info["members"],
          "7. stack_arrays('coherence') is exactly _coherence_stack, weights included")
    check(not np.array_equal(none, coh), "7. control: the two weightings differ")
    check(bool(raises_value_error(lambda: virtual.stack_arrays(arrays, fs, "median"))),
          "7. weighting='median' raises ValueError")


def build_members(workspace: Path, rng, seconds: float) -> list[str]:
    """Write three 1000 Hz members as virtual_unit lays them out; return their names."""
    n = int(seconds * vu.FS)
    field = {c: 1000.0 * rng.standard_normal(n) for c in virtual.COILS}
    names = ["M1", "M2", "M3"]
    for k, m in enumerate(names):
        coils = {c: np.rint(1e7 * (k + 1) + field[c] + 200.0 * rng.standard_normal(n)).astype("int32")
                 for c in virtual.COILS}
        vu.write_archive(workspace, m, [(vu.T0, coils)])
    return names


def check_provenance() -> None:
    """Criterion 8."""
    root = SCRATCH / "provenance"
    shutil.rmtree(root, ignore_errors=True)
    ws, out = root / "ws", root / "out"
    out.mkdir(parents=True)
    names = build_members(ws, np.random.default_rng(3), 1900.0)  # member_coherence needs three whole chunks
    survey = vu.fake_survey(ws)
    sources = {m: archive_identity(default_archive_path(survey, m)) for m in names}
    given = {"recipe": "STK_T1", "recipe_hash": "c3d32023d8f7",
             "recipe_text": "STK_T1:\n  field: H\n  method: time_mean\n  notes: a | b, provenance: x\n",
             "rule": "the plain mean of the members' counts", "members": names, "sources": sources}

    def build(name, **kwargs):
        return virtual.build_synthetic_remote(survey, names, "2023-09-19", "2023-09-20", name=name,
                                              out_path=out / f"{name}.h5", **kwargs)

    plain = build("STK_P0")
    with_p = build("STK_P1", provenance=json.loads(json.dumps(given)))
    coh = build("STK_C0", weighting="coherence")
    coh_p = build("STK_C1", weighting="coherence", provenance=json.loads(json.dumps(given)))
    rb = {name: vu.read_back(path, name) for name, path in
          (("STK_P0", plain), ("STK_P1", with_p), ("STK_C0", coh), ("STK_C1", coh_p))}
    today = (f"synthetic remote: mean of raw hx/hy counts from {', '.join(sorted(names))}; "
             f"uncalibrated: the members carry no filter chain (the remote-reference estimate is invariant to "
             f"the remote's calibration, its errors are not: upstream issue 111)")
    for c in virtual.COILS:
        check(same_bits(rb["STK_P1"][c], rb["STK_P0"][c]), f"8. {c}: provenance changes no sample (mean)")
        check(same_bits(rb["STK_C1"][c], rb["STK_C0"][c]), f"8. {c}: provenance changes no sample (coherence)")
    got = virtual.recorded_provenance(with_p, "SYNTH", "STK_P1")
    check(got == given, "8. recorded_provenance returns the dict given (members, sources, hash, a '|', a newline)")
    check(virtual.recorded_provenance(coh_p, "SYNTH", "STK_C1") == given,
          "8. recorded_provenance reads the coherence build's provenance after its weights text")
    check(rb["STK_P1"]["station_comment"] == today + "; recipe=STK_T1 recipe_hash=c3d32023d8f7",
          "8. the station comment ends in '; recipe=STK_T1 recipe_hash=c3d32023d8f7'")
    line = rb["STK_C1"]["run_comment"].split("\n")
    check(len(line) == 2 and line[0] == rb["STK_C0"]["run_comment"] and line[1].startswith("provenance: {"),
          "8. coherence run comment: the weights text, a newline, the provenance line")
    check(rb["STK_P0"]["run_comment"] in ("", "None") and rb["STK_P0"]["station_comment"] == today,
          "8. without provenance: no run comment, today's station comment")
    check(virtual.recorded_provenance(plain, "SYNTH", "STK_P0") is None
          and virtual.recorded_provenance(coh, "SYNTH", "STK_C0") is None,
          "8. without provenance recorded_provenance gives None (also after a weights comment)")
    check(virtual.recorded_provenance(out / "none.h5", "SYNTH", "STK_P1") is None
          and virtual.recorded_provenance(with_p, "SYNTH", "STK_X") is None
          and virtual.recorded_provenance(with_p, "OTHER", "STK_P1") is None,
          "8. None for a missing file, station or survey")
    before = with_p.read_bytes()
    bad = {"recipe": "STK_T1", "members": names}
    msg = raises_value_error(lambda: build("STK_P1", provenance=bad, overwrite=True))
    check(bool(msg) and with_p.read_bytes() == before,
          f"8. a provenance without recipe_hash raises ({msg[:60]}...) and leaves the old archive unchanged")


# ----------------------------------------------------------------- select_stack


SURVEY_YAML = """name: stack_median_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
sites:
  A: {{latitude: -31.0, longitude: 137.0}}
  B: {{latitude: -31.1, longitude: 137.0}}
  C: {{latitude: -31.2, longitude: 137.0}}
  S1: {{latitude: -31.3, longitude: 137.0, sample_rate: 1}}
  S2: {{latitude: -31.4, longitude: 137.0, sample_rate: 1}}
  S3: {{latitude: -31.5, longitude: 137.0, sample_rate: 1}}
  S4: {{latitude: -31.6, longitude: 137.0, sample_rate: 1}}
"""
T0 = pd.Timestamp("2024-03-01T00:00:00")


def write_runs(workspace: Path, site: str, fs: float, runs: list[tuple[pd.Timestamp, int]]) -> Path:
    """Write a site's MTH5 archive with random int32 hx, hy runs at `fs`: (start, samples) per run."""
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(len(site))
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("stack_median_unit")
        station = m.add_station(site, survey="stack_median_unit")
        for i, (start, n) in enumerate(runs, 1):
            run_id = f"sr{fs:g}_{i:04d}"
            chans = [ChannelTS(channel_type="magnetic", data=rng.integers(-1000, 1000, n).astype("int32"),
                               channel_metadata={"magnetic": {"component": c, "sample_rate": fs,
                                                              "time_period.start": start.isoformat()}})
                     for c in ("hx", "hy")]
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": fs}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()
    return path


def build_survey() -> Survey:
    """Write the scratch survey of criterion 9 and its archives (S3 has none)."""
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    (root / "raw").mkdir(parents=True)
    work = root / "work"
    yaml_path = root / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=(root / "raw").as_posix(), work=work.as_posix()), encoding="utf-8")
    hour = 3600
    # a run's recorded end is its last sample, so a covering run goes on past the window
    for site in ("A", "B", "C"):
        write_runs(work, site, 100.0, [(T0, 100 * (hour + 60))])
    write_runs(work, "S1", 1.0, [(T0, hour + 60)])
    write_runs(work, "S2", 1.0, [(T0, hour // 2)])
    write_runs(work, "S4", 1.0, [(T0 - pd.Timedelta(minutes=10), hour + 1200)])
    return Survey.from_yaml(yaml_path)


class FileOpens:
    """Count h5py.File and builtins.open calls while active."""

    def __init__(self):
        self.count = 0
        self._h5, self._open = h5py.File, builtins.open

    def __enter__(self):
        h5_file, py_open = self._h5, self._open

        def counted_h5(*args, **kwargs):
            self.count += 1
            return h5_file(*args, **kwargs)

        def counted_open(*args, **kwargs):
            self.count += 1
            return py_open(*args, **kwargs)

        h5py.File, builtins.open = counted_h5, counted_open
        return self

    def __exit__(self, *exc):
        h5py.File, builtins.open = self._h5, self._open
        return False


def check_select_stack() -> None:
    """Criterion 9."""
    survey = build_survey()
    lo = int(T0.value)
    hi = lo + 3600 * 10**9
    hxhy = ("hx", "hy")
    s3_path = default_archive_path(survey, "S3")

    members, left = intersite.select_stack(survey, None, None, lo, hi, hxhy, rate=1.0)
    reasons = {d["site"]: d["reason"] for d in left}
    print(f"   rate 1, no local: members {[d['site'] for d in members]}, left out {reasons}")
    check([d["site"] for d in members] == ["S1", "S4"], "9. rate=1.0, no local: members S1 and S4 (1 Hz, covering)")
    check(all(reasons.get(s) == "100 Hz, the stack is at 1 Hz" for s in ("A", "B", "C")),
          "9. the 100 Hz sites are left out: '100 Hz, the stack is at 1 Hz'")
    check(reasons.get("S2") == "its runs with hx/hy cover 0.50 h of the window, under 1 h",
          "9. S2 (half the window) left out on its overlap")
    check(reasons.get("S3") == f"no archive at {s3_path}", "9. S3 (no archive) left out with its path")

    members_l, left_l = intersite.select_stack(survey, "S1", None, lo, hi, hxhy, rate=1.0)
    reasons_l = {d["site"]: d["reason"] for d in left_l}
    check([d["site"] for d in members_l] == ["S4"] and reasons_l.get("S1") == "the local"
          and reasons_l.get("A") == "100 Hz, the pair is at 1 Hz",
          "9. rate=1.0 with a 1 Hz local: the local left out, '100 Hz, the pair is at 1 Hz'")
    check(bool(raises_value_error(lambda: intersite.select_stack(survey, "A", None, lo, hi, hxhy, rate=1.0))),
          "9. a 100 Hz local with rate=1.0 raises ValueError")
    check(bool(raises_value_error(lambda: intersite.select_stack(survey, None, None, lo, hi, hxhy))),
          "9. neither a local nor a rate raises ValueError")

    with FileOpens() as default_opens:
        dm, dl = intersite.select_stack(survey, "A", None, lo, hi, hxhy)
    want_left = [{"site": "A", "reason": "the local"}] + [
        {"site": s, "reason": "1 Hz, the pair is at 100 Hz"} for s in ("S1", "S2", "S3", "S4")]
    check([d["site"] for d in dm] == ["B", "C"] and dl == want_left,
          "9. the default call (local A, no rate) keeps today's lists and wording")
    check(default_opens.count > 0, f"9. control: the default call opens files ({default_opens.count})")

    calls = []

    def from_archive(site, path, roles):
        calls.append((site, path, roles))
        return intersite.archive_runs(path, site, roles)

    for local, rate in ((None, 1.0), ("A", None)):
        base = intersite.select_stack(survey, local, None, lo, hi, hxhy, rate=rate)
        calls.clear()
        got = intersite.select_stack(survey, local, None, lo, hi, hxhy, rate=rate, runs_of=from_archive)
        expect_calls = ([(s, default_archive_path(survey, s), hxhy) for s in ("S1", "S2", "S4")] if local is None
                        else [(s, default_archive_path(survey, s), hxhy) for s in ("B", "C")])
        check(got == base and calls == expect_calls,
              f"9. runs_of with archive_runs' runs (local {local}, rate {rate}): same lists; called for "
              f"{[c[0] for c in calls]} with (site, raw path, ('hx', 'hy'))")

    cache = {s: intersite.archive_runs(default_archive_path(survey, s), s, hxhy) for s in ("S1", "S2")}

    def cached(site, path, roles):
        return cache.get(site)  # S4 not read yet

    with FileOpens() as opens:
        cm, cl = intersite.select_stack(survey, None, None, lo, hi, hxhy, rate=1.0, runs_of=cached)
    creasons = {d["site"]: d["reason"] for d in cl}
    check([d["site"] for d in cm] == ["S1"] and creasons.get("S4") == intersite.NOT_READ
          and sum(r == intersite.NOT_READ for r in creasons.values()) == 1
          and {k: v for k, v in creasons.items() if k != "S4"} == {k: v for k, v in reasons.items() if k != "S4"},
          f"9. runs_of None for S4: S4 left out as {intersite.NOT_READ!r}, the rest unchanged")
    check(opens.count == 0, f"9. select_stack with runs_of opens no file ({opens.count} opens)")


# ----------------------------------------------------------------- the existing suites


def run_suites() -> None:
    """Criterion 10."""
    for name in SUITES:
        t = time.perf_counter()
        proc = subprocess.run([sys.executable, str(REPO / "tests" / name)], capture_output=True, text=True,
                              cwd=REPO)
        tail = [line for line in proc.stdout.splitlines() if line.strip()][-1:] or ["(no output)"]
        check(proc.returncode == 0, f"10. {name} exits {proc.returncode} in {time.perf_counter() - t:.0f} s: "
                                    f"{tail[0][:100]}")
        if proc.returncode:
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])


def main() -> None:
    """Run the checks and exit 1 when any failed."""
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print(__doc__.split("**This test fails if**")[1].strip() + "\n")
    t = time.perf_counter()
    check_band_median()
    check_stack_arrays()
    check_provenance()
    check_select_stack()
    if "--quick" not in sys.argv[1:]:
        run_suites()
    else:
        print("SKIPPED 10. the four existing suites (--quick)")
    print(f"\n{len(failures)} failure(s) in {time.perf_counter() - t:.0f} s")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
