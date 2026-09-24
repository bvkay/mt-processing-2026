"""Unit test for band-limited masks inside aurora: `mtproc.process._band_masks_applied` on
stock aurora, `mtproc.process._set_window_masks` (aurora's own `DecimationLevel.window_masks`)
on aurora 0.6.2+mtproc (`mtproc.process.AURORA_WINDOW_MASKS`). Both live in this one file and
branch on `mtproc.process.AURORA_WINDOW_MASKS`, so the same criteria are checked whichever
aurora is installed; running it once under each aurora is how both get exercised (below).

    python tests/band_masks_unit.py            # FALSIFY=1 disables the window drop

**Running it under both aurora.** This environment runs aurora 0.6.2+mtproc (the bvkay/aurora
fork, branch mtproc-fixes), so a plain run exercises `_set_window_masks`. Stock aurora 0.6.2 is a git
worktree of the same clone (`git -C <the clone> worktree add <scratch> 3395804c`); running
this file again as a subprocess with that worktree first on PYTHONPATH exercises
`_band_masks_applied` instead -- the old, stock-only expectations (below) hold there unchanged.

The synthetic archives of `tests/crosspower_unit.py` (L: ex ey hx hy in two
runs, [T0, T0 + 1500 s) and [T0 + 1600 s, T0 + 3100 s); R: hx hy over the
whole span; 100 Hz; Zxy = 2 exp(-2 pi i f / 100), Zyx = -1.5; its white Ex
burst, 10 times Ex's rms, over [1800, 2400) s), with one thing added: over
chunk 1, [600, 1200) s, L's Ex follows a Zxy 20 % low (the same field, seed
5). A robust regression cannot see that chunk -- its residuals look like
signal -- so only a mask removes it; the white burst it rejects on its own
once its Huber stage runs (measured with the stage run for every band:
masking the burst moves no level-0/1 band by more than 0.1 % of |Z|). The
burst is kept because it makes regressions exhaust their 10 iterations,
which exposes aurora 0.6.2's shared iteration counter (below).

Processed by `process_station` against R, lemimt scheme at 100 Hz out to
10 s (four decimation levels, 24 bands): no masks; a band-limited mask over
chunk 1 in the TEST BAND only (level 1's fourth band from the low end,
0.2851 s, [1/f_hi, 1/f_lo] of its edges); both again with aurora's Huber
stage made to start from a fresh iteration count for every regression
("leak-free", a test-local patch, see 1); an all-band mask over chunk 1; a
band mask over the whole record in the test band plus one whose period
range holds no band's centre.

**Aurora 0.6.2 is order-dependent, and not at the 1e-12 level.** One
`IterControl` serves every band of a decimation level
(`transfer_function_helpers.set_up_iter_control`, once per level), and
`MEstimator.apply_huber_regression` evaluates ``converged =
iter_control.max_iterations_reached`` BEFORE it resets the counter: a
regression that follows one which used all 10 iterations runs no Huber
iteration at all. A band mask changes its band's iteration count, so the
bands the loop reaches after it on the same level (ex bands, then ey
bands) can flip between Huber and no Huber. In the unmasked run here 10 of
48 regressions skip the stage.

**This test fails if** (stock aurora; under the fork, 1 and 3 and half of 5 change -- see
"under the fork" after each)

1. isolation: (a) leak-free, the band-masked run changes any band but the
   test band -- every other band's Z (the 2x2) and its error must be
   bit-identical to the unmasked run's; (b) stock aurora, on the test
   band's pair and on a CASCADE pair (a band mask over the white burst in
   level 1's second band, 0.4525 s, whose ex regression exhausts its
   iterations unmasked): any band on another decimation level is not
   bit-identical, the masked band's own Z does not change or its Huber-skip
   state differs between the runs (it depends only on the bands before it,
   which the mask does not touch), or any other band's row (Zx. from the ex regression, Zy. from
   ey) changed although that regression's Huber-skip state did not flip
   (recorded HERE by wrapping `MEstimator.apply_huber_regression`); or the
   cascade pair moves no other row at all -- the leak exists in aurora
   0.6.2, and when aurora fixes it this fails so the docs saying so change.
   **Under the fork** (aurora 0.6.2+mtproc resets the Huber iteration count
   before its convergence check, per regression -- the fork's
   second commit -- so there is no shared state left to leak through): 1b
   becomes "no other band moves at all", own band still must change, and
   the leak-free pair must be bit-identical to the stock pair (the
   test-local reset is now redundant with aurora's own -- asserted, not
   assumed);
2. in the test band, in both the stock and the leak-free pair, the masked
   Zxy is not closer to the known Zxy (the band mean of 2 exp(-2 pi i f /
   100) over the harmonics aurora used, recorded HERE) than half the
   unmasked run's error (measured 6.25 % -> 0.91 %), or the shift |Zxy_masked
   - Zxy_unmasked| is not larger than the unmasked run's own reported Zxy
   error (aurora's impedance_error): the move must be more than the noise;
3. the log does not carry exactly one "band masks, decimation level 1" line
   saying the test band lost N of 780 windows, N being the level-1 windows
   (128 points at 25 Hz, 96-sample hop from each run's start: 5.12 s long,
   3.84 s apart) that overlap [600, 1200) s, counted HERE from that grid
   (158); or any other level gets a line. **Under the fork**: mtproc's own
   "window masks, decimation level 1: 1 mask(s) passed to aurora" line is
   missing, or aurora's own "window masks: band ...s drops N of M STFT
   windows" line (its logger, not mtproc's) does not carry that same (158,
   780);
4. the all-band mask over chunk 1 does not change every band;
5. a band mask over the whole record is not skipped in the test band (it
   would leave 0 windows), a mask covering no band's centre is not warned
   about (by mtproc: aurora does not check that itself, fork or stock), or
   that run is not bit-identical to the unmasked one in every band.
   **Under stock**: the skip is not a log line from mtproc naming the mask.
   **Under the fork**: the skip is not a warning from aurora's own logger
   naming the band and the floor;
6. `mtproc.process._band_masks_applied` (the patch, always importable and
   directly tested here regardless of which aurora is installed) does not
   restore aurora's `get_band_for_tf_estimate` (the same object) after a
   run through it and after an exception inside the block.

The guard: **this test also fails if**, under stock aurora,
`aurora.pipelines.transfer_function_helpers.get_band_for_tf_estimate`'s
parameters are not (band, dec_level_config, local_stft_obj, remote_stft_obj);
either regression loop (process_transfer_functions,
process_transfer_functions_with_weights) stops calling that module-level
name; or `mtproc.process._check_band_patch` accepts a function with other
parameter names; under the fork, `mtproc.process.AURORA_WINDOW_MASKS` is not
True, `DecimationLevel` does not round-trip a `window_masks` assignment, or
`transfer_function_helpers` lost `window_mask_for_band`. Either aurora: the
STFT a band is cut from, recorded HERE during the unmasked run, does not
have dims (time, frequency) with `time` a naive datetime64 whose first
window at levels 0 and 1 is T0 exactly and whose first window after L's gap
is T0 + 1600 s (each window's first sample, UTC -- what both paths assume).
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import crosspower_unit as cu  # noqa: E402  (the synthetic archive)
from loguru import logger  # noqa: E402

import aurora  # noqa: E402
import aurora.pipelines.transfer_function_helpers as tfh  # noqa: E402
import mtproc.process as mp  # noqa: E402
from aurora.transfer_function.regression.m_estimator import MEstimator  # noqa: E402
from mtproc.bands import lemimt_band_scheme  # noqa: E402

logger.remove()  # after aurora's and mth5's imports, which add their own sinks
logger.add(sys.stderr, level="WARNING", filter=lambda r: not r["name"].startswith(("aurora", "mth5", "mt_")))

SCHEME = lemimt_band_scheme(cu.FS, max_period=10.0)
BIAS = -0.2  # chunk 1's Zxy is (1 + BIAS) times the true one
BIASED = (600.0, 1200.0)  # s after T0
WHITE = (1800.0, 2400.0)  # crosspower_unit's white Ex burst
TEST_LEVEL, TEST_INDEX = 1, 3  # level 1's fourth band from the low-frequency end: 0.2851 s
CASCADE_INDEX = 1  # level 1's second band, 0.4525 s: its ex regression exhausts its iterations unmasked
EXPECTED_PARAMETERS = ("band", "dec_level_config", "local_stft_obj", "remote_stft_obj")
CALLERS = ("process_transfer_functions", "process_transfer_functions_with_weights")


def at(seconds: float) -> pd.Timestamp:
    return cu.T0 + pd.Timedelta(seconds=seconds)


def samples() -> dict:
    """crosspower_unit's channels, L's Ex following Zxy (1 + BIAS) over chunk 1."""
    data = cu.field_and_channels()
    rng = np.random.default_rng(5)  # the same seed: the first two draws are the field's Hx, Hy
    n = int(cu.SPAN_S * cu.FS)
    _hx, hy = 1000.0 * rng.standard_normal(n), 1000.0 * rng.standard_normal(n)
    sl = slice(cu.index(BIASED[0]), cu.index(BIASED[1]))
    data["ex"][sl] += np.rint(BIAS * cu.Z_TRUE["xy"] * np.roll(hy, cu.DELAY)[sl])
    return data


def the_test_band() -> tuple[float, float, float]:
    """(centre period, pmin, pmax) of the test band, from the scheme's own edges."""
    lo, hi = np.asarray(SCHEME["band_edges"][TEST_LEVEL])[TEST_INDEX]
    return 1.0 / np.sqrt(lo * hi), 1.0 / hi, 1.0 / lo


def level1_windows_in(a_s: float, b_s: float) -> tuple[int, int]:
    """(level-1 windows overlapping [a_s, b_s), all level-1 windows), from the window grid alone."""
    fs1, n, hop = cu.FS / 4, 128, 96
    length, step = n / fs1, hop / fs1
    hit = total = 0
    for a, b in cu.L_RUNS_S:
        count = (int(round((b - a) * fs1)) - n) // hop + 1
        starts = a + step * np.arange(count)
        total += count
        hit += int(((starts < b_s) & (starts + length > a_s)).sum())
    return hit, total


class Recorder:
    """Wraps aurora's band function (the SAME parameter names) and its Huber stage; records what they see."""

    def __init__(self, leak_free: bool = False):
        self.original = tfh.get_band_for_tf_estimate
        self.original_huber = MEstimator.apply_huber_regression
        self.leak_free = leak_free
        self.freqs: dict[float, np.ndarray] = {}
        self.stft: dict[int, dict] = {}
        self.huber: list[tuple[int, float, bool]] = []  # (level, period, Huber skipped), in call order
        self.band = None

    def __call__(self, band, dec_level_config, local_stft_obj, remote_stft_obj):
        X, Y, RR = self.original(band, dec_level_config, local_stft_obj, remote_stft_obj)
        level, period = int(dec_level_config.decimation.level), float(band.center_period)
        self.band = (level, period)
        self.freqs[period] = np.asarray(X.frequency.values)
        if level not in self.stft:
            self.stft[level] = {"dims": tuple(local_stft_obj.dims), "x_dims": tuple(X.dims),
                                "time": np.asarray(local_stft_obj.time.values)}
        return X, Y, RR

    def install(self):
        recorder, original_huber = self, self.original_huber

        def apply_huber_regression(estimator):
            if recorder.leak_free:  # what aurora's own reset would do if it came before the check
                estimator.iter_control.reset_number_of_iterations()
            recorder.huber.append((*recorder.band, bool(estimator.iter_control.max_iterations_reached)))
            return original_huber(estimator)

        tfh.get_band_for_tf_estimate = self
        MEstimator.apply_huber_regression = apply_huber_regression

    def uninstall(self):
        tfh.get_band_for_tf_estimate = self.original
        MEstimator.apply_huber_regression = self.original_huber

    def skipped(self) -> dict[tuple[float, int], bool]:
        """{(period, k): Huber skipped} -- k = 0 the ex regression, 1 the ey one (aurora's per-channel loop)."""
        out, seen = {}, {}
        for _level, period, skip in self.huber:
            key = round(period, 6)
            k = seen.get(key, 0)
            seen[key] = k + 1
            out[(key, k)] = skip
        return out

    def level_of(self, period: float) -> int:
        return next(level for level, p, _s in self.huber if round(p, 6) == round(period, 6))


LOG_NAMES = (("mtproc.process", "aurora.pipelines.transfer_function_helpers")
            if mp.AURORA_WINDOW_MASKS else ("mtproc.process",))


def run(local, remote, masks, leak_free=False, falsify=False):
    """process_station L rr R; returns (tf, the log lines (mtproc.process, plus aurora's own
    transfer_function_helpers logger under the fork), the Recorder)."""
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO",
                      filter=lambda r: r["name"] in LOG_NAMES)
    saved_patch = mp.windows_in_mask
    saved_fork = getattr(tfh, "window_mask_for_band", None)
    if falsify:  # the drop disabled: no window is ever found inside a mask, on whichever path runs
        mp.windows_in_mask = lambda times, window_s, mask: np.zeros(np.asarray(times).size, dtype=bool)
        if saved_fork is not None:
            tfh.window_mask_for_band = lambda dec_level_config, band, times: None
    rec = Recorder(leak_free)
    rec.install()
    try:
        tf = mp.process_station(local, "L", remote, "R", band_scheme=SCHEME, output_channels=["ex", "ey"],
                                time_masks=masks)
        restored = tfh.get_band_for_tf_estimate is rec
    finally:
        rec.uninstall()
        mp.windows_in_mask = saved_patch
        if saved_fork is not None:
            tfh.window_mask_for_band = saved_fork
        logger.remove(sink)
    assert restored, "6. get_band_for_tf_estimate was not restored after the run"
    return tf, lines, rec


def guard() -> None:
    """Under the fork: `AURORA_WINDOW_MASKS` is active and its two support points still exist.
    Under stock: the patch's entry point and signature (unchanged from before the switch)."""
    if mp.AURORA_WINDOW_MASKS:
        assert mp._decimation_level_accepts_window_masks(), \
            "guard: DecimationLevel no longer round-trips a window_masks assignment"
        assert hasattr(tfh, "window_mask_for_band"), \
            "guard: aurora.pipelines.transfer_function_helpers lost window_mask_for_band"
        print(f"  guard: aurora {aurora.__version__}; AURORA_WINDOW_MASKS is True; DecimationLevel "
              f"round-trips window_masks; transfer_function_helpers still has window_mask_for_band")
        return
    fn = tfh.get_band_for_tf_estimate
    params = tuple(inspect.signature(fn).parameters)
    assert params == EXPECTED_PARAMETERS, f"guard: aurora's get_band_for_tf_estimate takes {params}"
    for name in CALLERS:
        caller = getattr(tfh, name)
        assert caller.__globals__ is vars(tfh), f"guard: {name} no longer lives in transfer_function_helpers"
        assert "get_band_for_tf_estimate" in caller.__code__.co_names, f"guard: {name} no longer calls it"

    def other(band, dec, local, remote):  # the same function under other parameter names
        return fn(band, dec, local, remote)

    tfh.get_band_for_tf_estimate = other
    try:
        mp._check_band_patch()
        raise AssertionError("guard: _check_band_patch accepted a function with other parameter names")
    except RuntimeError as exc:
        message = str(exc)
    finally:
        tfh.get_band_for_tf_estimate = fn
    print(f"  guard: parameters {params}; both regression loops call the module-level name; "
          f"_check_band_patch refuses another signature ({message[:58]}...)")


def rel_err(z, want) -> float:
    return float(abs(z - want) / abs(want))


def stock_isolation(label, periods, ref, got, skip_ref, skip_got, masked_period, rec_ref):
    """1b on one stock pair: ([(period, channel) of the other rows that moved], their largest |dZ| / |Z|)."""
    key = lambda p, c: (round(float(p), 6), c)  # noqa: E731
    assert all(skip_ref[key(masked_period, c)] == skip_got[key(masked_period, c)] for c in (0, 1)), \
        f"1b. {label}: the masked band's own Huber-skip state changed"
    k_masked = int(np.flatnonzero(periods == masked_period)[0])
    assert not np.array_equal(got[0][k_masked], ref[0][k_masked]), \
        f"1b. {label}: the mask did not change its own band ({masked_period:.4f} s): no window was dropped"
    moved, unexplained, worst = [], [], 0.0
    for k, p in enumerate(periods):
        if p == masked_period:
            continue
        same_level = rec_ref.level_of(p) == TEST_LEVEL
        for c in (0, 1):  # row 0 from the ex regression, row 1 from ey
            if np.array_equal(got[0][k, c], ref[0][k, c]) and np.array_equal(got[1][k, c], ref[1][k, c]):
                continue
            moved.append((round(float(p), 4), ("ex", "ey")[c]))
            worst = max(worst, float(np.max(np.abs(got[0][k, c] - ref[0][k, c]) / np.abs(ref[0][k, c]).max())))
            if not same_level or skip_ref[key(p, c)] == skip_got[key(p, c)]:
                unexplained.append((round(float(p), 4), c, "same level" if same_level else "other level"))
    assert not unexplained, f"1b. {label}: rows changed without a Huber-skip flip or off the test level: {unexplained}"
    return moved, worst


def main() -> int:
    fork = mp.AURORA_WINDOW_MASKS
    print(f"path exercised: {'aurora window_masks (0.6.2+mtproc, DecimationLevel.window_masks)' if fork else 'runtime patch (stock aurora, _band_masks_applied)'}")
    guard()
    falsify = os.environ.get("FALSIFY") == "1"
    period, pmin, pmax = the_test_band()
    band_mask = {"start": at(BIASED[0]), "end": at(BIASED[1]), "bands": [pmin, pmax], "reason": "Zxy bias"}
    data = samples()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        local, remote = tmp / "L.h5", tmp / "R.h5"
        cu.write_archive(local, "L", [(at(a), {c: data[c][cu.index(a): cu.index(b)] for c in ("ex", "ey", "hx", "hy")})
                                      for a, b in cu.L_RUNS_S])
        cu.write_archive(remote, "R", [(at(-cu.LEAD_S), {"hx": data["r_hx"], "hy": data["r_hy"]})])
        none, _, rec_none = run(local, remote, None)
        banded, band_lines, rec_band = run(local, remote, [band_mask], falsify=falsify)
        free_none, _, _ = run(local, remote, None, leak_free=True)
        free_band, _, _ = run(local, remote, [band_mask], leak_free=True, falsify=falsify)
        cascade = rec_cascade = None
        if falsify:
            print("  FALSIFY=1: the window drop is disabled; own-band and known-Z criteria must now fail")
        else:
            if not fork:  # the shared-iteration-count cascade is a stock-only leak (aurora 0.6.2+mtproc resets per regression)
                lo, hi = np.asarray(SCHEME["band_edges"][TEST_LEVEL])[CASCADE_INDEX]
                cascade_mask = {"start": at(WHITE[0]), "end": at(WHITE[1]), "bands": [1.0 / hi, 1.0 / lo]}
                cascade, _, rec_cascade = run(local, remote, [cascade_mask])
            all_band, _, _ = run(local, remote, [{**band_mask, "bands": "all"}])
            whole = {"start": at(-3600), "end": at(7200), "bands": [pmin, pmax], "reason": "empties the band"}
            nowhere = {"start": at(1800), "end": at(2400), "bands": [0.2900, 0.2905], "reason": "no centre"}
            empty, empty_lines, _ = run(local, remote, [whole, nowhere])

    # the guard's STFT checks, on what the unmasked run's regression was given
    t0 = np.datetime64(cu.T0.tz_convert(None).to_datetime64())
    gap_end = np.datetime64(at(1600).tz_convert(None).to_datetime64())
    for level in (0, 1):
        s = rec_none.stft[level]
        assert s["dims"] == ("time", "frequency") and s["x_dims"] == ("time", "frequency"), s["dims"]
        assert s["time"].dtype.kind == "M", s["time"].dtype
        assert s["time"][0] == t0, (level, s["time"][0], t0)
        assert s["time"][s["time"] >= gap_end][0] == gap_end, (level, s["time"][s["time"] >= gap_end][0])
    print(f"  guard: the STFT's dims {rec_none.stft[0]['dims']}, time {rec_none.stft[0]['time'].dtype} naive UTC; "
          f"first windows at T0 and T0 + 1600 s on levels 0 and 1 (each window's first sample)")

    periods = np.asarray(none.period)
    assert periods.size == 24, periods.size
    j = int(np.argmin(np.abs(periods - period)))
    assert abs(periods[j] - period) < 1e-6 * period, (periods[j], period)
    others = [k for k in range(periods.size) if k != j]
    Z = {name: (tf.impedance.data, tf.impedance_error.data)
         for name, tf in (("none", none), ("band", banded), ("free_none", free_none), ("free_band", free_band))}

    # own band must change either way -- the falsification target: FALSIFY=1 disables the drop,
    # so this (and 2, below) must then fail
    assert not np.array_equal(Z["band"][0][j], Z["none"][0][j]), \
        f"1. the mask did not change its own band ({period:.4f} s): no window was dropped"

    if fork:
        # 1. the fork resets the Huber iteration count before its convergence check, per regression
        # (the fork's second commit): no shared state is left for a mask on one band to
        # leak through to another, so every other band -- on every level -- must be untouched
        for k in others:
            assert np.array_equal(Z["band"][0][k], Z["none"][0][k]) and \
                np.array_equal(Z["band"][1][k], Z["none"][1][k]), \
                f"1. fork: band {periods[k]:.4f} s changed under a mask on {period:.4f} s (no other band should move)"
        print(f"  1. fork: band mask [{pmin:.4f}, {pmax:.4f}] s changes only its own band ({period:.4f} s); "
              f"the other {len(others)} bands are bit-identical (Z and its error)")
        # the test-local Huber reset ("leak-free") is now redundant with aurora's own -- assert, don't assume
        for a, b in (("none", "free_none"), ("band", "free_band")):
            assert np.array_equal(Z[a][0], Z[b][0]) and np.array_equal(Z[a][1], Z[b][1]), \
                f"1. fork: {a} and {b} differ although aurora resets the Huber count itself"
        print("  1. fork: the leak-free run (test-local Huber reset) is bit-identical to the stock run: "
              "aurora's own per-regression reset already removes the cascade")
    else:
        # 1a. leak-free: only the test band moved
        for k in others:
            assert np.array_equal(Z["free_band"][0][k], Z["free_none"][0][k]) and \
                np.array_equal(Z["free_band"][1][k], Z["free_none"][1][k]), \
                f"1a. leak-free, band {periods[k]:.4f} s changed under a mask on {period:.4f} s"
        print(f"  1a. leak-free: band mask [{pmin:.4f}, {pmax:.4f}] s leaves the other {len(others)} bands "
              f"bit-identical (Z and its error)")

        # 1b. stock aurora: other levels bit-identical; same-level changes only where the Huber skip flipped
        skip_none = rec_none.skipped()
        print(f"  1b. stock aurora: {sum(skip_none.values())} of {len(skip_none)} regressions skip the Huber stage "
              f"unmasked")
        pairs = [("test-band pair", banded, rec_band, periods[j])]
        if not falsify:
            lo, hi = np.asarray(SCHEME["band_edges"][TEST_LEVEL])[CASCADE_INDEX]
            pairs.append(("cascade pair", cascade, rec_cascade, periods[int(np.argmin(np.abs(periods - 1 / np.sqrt(lo * hi))))]))
        for label, tf, rec, masked_period in pairs:
            moved, worst = stock_isolation(label, periods, Z["none"], (tf.impedance.data, tf.impedance_error.data),
                                           skip_none, rec.skipped(), masked_period, rec_none)
            if label == "cascade pair":
                assert moved, ("1b. masking the white burst in the cascade band moved no other band: aurora's shared "
                               "iteration counter no longer leaks -- update the docs that say it does")
            print(f"      {label}: mask on {masked_period:.4f} s moved {len(moved)} other row(s), all on level "
                  f"{TEST_LEVEL}, each with its Huber skip flipped{f' (at most {100 * worst:.1f} % of |Z|)' if moved else ''}: "
                  f"{moved}")

    # 2. the test band moved towards the known Z, by more than its own error
    f = rec_none.freqs[min(rec_none.freqs, key=lambda p: abs(p - period))]
    want = cu.Z_TRUE["xy"] * np.mean(np.exp(-2j * np.pi * f * cu.DELAY / cu.FS))
    for label, a, b in ((("aurora window_masks" if fork else "stock"), "none", "band"), ("leak-free", "free_none", "free_band")):
        z0, e0, zb = Z[a][0][j, 0, 1], Z[a][1][j, 0, 1], Z[b][0][j, 0, 1]
        err0, errb, shift = rel_err(z0, want), rel_err(zb, want), abs(zb - z0)
        print(f"  2. {label}: {period:.4f} s ({f.size} harmonics, {f[0]:.3f}-{f[-1]:.3f} Hz) Zxy error "
              f"{100 * err0:.2f} % unmasked -> {100 * errb:.2f} % masked; shift {shift:.4f} vs the unmasked "
              f"error {e0:.4f}")
        assert errb < 0.5 * err0, f"2. {label}: the masked band did not move towards the known Z"
        assert shift > e0, f"2. {label}: the shift {shift:.4f} is within the unmasked error {e0:.4f}"

    # 3. the log: level 1 (and only level 1) reports the lost windows, counted from the grid
    hit, total = level1_windows_in(*BIASED)
    if fork:
        # mtproc's own line: how many masks were passed to aurora, per level
        own_lines = [line for line in band_lines if line.startswith("window masks, decimation level")]
        level_line = [line for line in own_lines if line.startswith(f"window masks, decimation level {TEST_LEVEL}:")]
        assert len(level_line) == 1 and level_line[0].endswith("1 mask(s) passed to aurora"), own_lines
        # aurora's own line (its logger, not mtproc's): the actual windows dropped for the test band
        drop_lines = [line for line in band_lines if line.startswith("window masks: band ") and "drops" in line]
        assert drop_lines, band_lines
        m = re.search(r"window masks: band ([\d.]+)s drops (\d+) of (\d+) STFT windows", drop_lines[0])
        assert m and abs(float(m.group(1)) - periods[j]) < 1e-5 * periods[j] and \
            (int(m.group(2)), int(m.group(3))) == (hit, total), (drop_lines, hit, total)
        print(f"  3. fork: {level_line[0]!r}; aurora itself logged {drop_lines[0]!r} "
              f"({hit} of {total} counted here from the level-1 grid)")
    else:
        level_lines = [line for line in band_lines if line.startswith("band masks, decimation level")]
        assert len(level_lines) == 1 and level_lines[0].startswith(f"band masks, decimation level {TEST_LEVEL}:"), \
            level_lines
        m = re.search(rf"{period:.4g} s lost (\d+) of (\d+) windows", level_lines[0])
        assert m and (int(m.group(1)), int(m.group(2))) == (hit, total), (level_lines[0], hit, total)
        print(f"  3. log: {level_lines[0]!r} ({hit} of {total} counted here from the level-1 grid)")

    # 4. the all-band mask moves every band
    za, z0 = all_band.impedance.data, Z["none"][0]
    same = [periods[k] for k in range(periods.size) if np.array_equal(za[k], z0[k])]
    assert not same, f"4. bands unchanged by the all-band mask: {same}"
    print(f"  4. all-band mask: every one of the {periods.size} bands differs from the unmasked run "
          f"(median |dZxy| {np.median(np.abs(za[:, 0, 1] - z0[:, 0, 1])):.4f})")

    # 5. a mask emptying the band is skipped, a mask covering no band is warned about
    assert np.array_equal(empty.impedance.data, z0) and np.array_equal(empty.impedance_error.data, Z["none"][1]), \
        "5. the skipped masks changed the estimate"
    # mtproc warns about the mask covering no band's centre either way -- aurora does not check
    # that itself, fork or stock (see the comment above mtproc.process.AURORA_WINDOW_MASKS)
    assert any("covers no band's centre period" in line and "[0.29, 0.2905]" in line for line in empty_lines), \
        empty_lines
    if fork:
        # aurora's own floor (max(1, min_num_stft_windows)) leaves the whole-record mask's band
        # unmasked, and aurora logs that itself (not mtproc)
        aurora_skip = [line for line in empty_lines
                       if "STFT windows (minimum" in line and "band left unmasked" in line]
        assert aurora_skip, empty_lines
        print(f"  5. fork: a mask over the whole record left unmasked by aurora itself ({aurora_skip[0]!r}); "
              f"mtproc warned about the mask between band centres; every band bit-identical to the unmasked run")
    else:
        skip_line = [line for line in empty_lines if f"skipped at {period:.4g} s" in line]
        assert skip_line and "2023-09-21T23:00:00Z" in skip_line[0], empty_lines
        print(f"  5. a mask over the whole record skipped at {period:.4g} s (logged), a mask between band centres "
              f"warned about; every band bit-identical to the unmasked run")

    # 6. restored after an exception inside the block too
    original = tfh.get_band_for_tf_estimate
    try:
        with mp._band_masks_applied([band_mask]):
            assert tfh.get_band_for_tf_estimate is not original, "6. the patch was not installed"
            raise ValueError("inside the block")
    except ValueError:
        pass
    assert tfh.get_band_for_tf_estimate is original, "6. not restored after an exception"
    print("  6. aurora's function restored after every run and after an exception inside the block")
    print("\nPASS  band_masks_unit")
    return 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    raise SystemExit(main())
