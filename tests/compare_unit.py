"""Unit test for mtproc.compare.phase_quadrants (no Qt).

    python tests/compare_unit.py

The synthetic TF: 44 periods, 0.005-100 s at 10 per decade, rho 100 ohm m;
xy phases 35-55 deg and yx -145 to -125 deg (the physical quadrants), except
that every period shorter than 0.1 s is replaced by noise -- a random
amplitude and a uniformly random phase per period and mode, seeded -- which
is what Morocco D05 RR D13 looks like at 0.01-0.1 s.

**This test fails if**

(1) the physical TF with the noisy short band is not judged physical in both
    modes by the default window (0.1-10 s), or either mode is judged on
    fewer than five periods;

(2) negating Zxy (one mode 180 deg out) does not make xy_ok False while
    yx_ok stays True -- and the same with Zyx negated and xy -- in the
    default window;

(3) over 200 seeds of the noisy short band, the default window raises any
    alarm (a mode not ok), or the old window (pmin=0.01, pmax=0.1) raises one
    on fewer than half of them. The second half is what makes this test able
    to fail: it proves the synthetic reproduces the D05 failure mode (the
    median of random phases is arbitrary), so (1) passing means the window
    moved off it and not that the synthetic was easy;

(4) a mode with only four finite periods in 0.1-10 s (the rest NaN, or an
    exact zero, which np.angle would read as a finite 0 deg) is judged at
    all -- it must come back not ok, with its count 4 and a `reason` naming
    it -- or the other mode's judgement changes;

(5) phases straddling np.angle's +-180 cut are misjudged: a physical yx that
    alternates -172 and -184 deg (read as +176) must be ok with its median
    within 1 deg of -178, and a flipped xy that alternates -174 and -182 deg
    (read as +178) must NOT be ok. Both cases are checked to fool a plain
    np.median of the raw angles (+2 deg in each: yx judged out, flipped xy
    judged physical), so the wrap handling is what passes them;

(6) on the real Morocco D05_rr-D13.edi (skipped, and said so, when the
    workspace is not mounted): the default window raises an alarm, the old
    window does NOT reproduce the false alarm on xy, or negating Zxy / Zyx in
    memory does not raise it on that mode alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mtproc.compare import phase_quadrants, rho_phi  # noqa: E402

D05_EDI = Path(r"D:/MT_DATA/MT_Morocco_Atlas_Mountains_Workspace/tf/D05_rr-D13.edi")
PERIOD = np.logspace(np.log10(0.005), 2.0, 44)
WINDOW = (PERIOD >= 0.1) & (PERIOD <= 10.0)
OLD = dict(pmin=0.01, pmax=0.1)


def synthetic_z(seed: int = 0, noisy_below: float = 0.1) -> np.ndarray:
    """(nf, 2, 2) impedance in mV/km/nT: physical quadrants, random-phase noise below `noisy_below` s."""
    z = np.zeros((PERIOD.size, 2, 2), dtype=complex)
    amp = np.sqrt(100.0 / (0.2 * PERIOD))  # rho = 0.2 T |Z|^2 = 100 ohm m
    x = np.log10(PERIOD)
    z[:, 0, 1] = amp * np.exp(1j * np.radians(45.0 + 10.0 * np.sin(2.0 * x)))
    z[:, 1, 0] = amp * np.exp(1j * np.radians(-135.0 + 10.0 * np.cos(2.0 * x)))
    rng = np.random.default_rng(seed)
    noisy = PERIOD < noisy_below
    k = int(noisy.sum())
    for i, j in ((0, 1), (1, 0)):
        z[noisy, i, j] = amp[noisy] * rng.uniform(0.1, 10.0, k) * np.exp(1j * rng.uniform(-np.pi, np.pi, k))
    return z


def make_tf(z: np.ndarray) -> TF:
    tf = TF()
    tf.station = "SYN"
    tf.period = PERIOD
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    return tf


def with_phases(z: np.ndarray, mode: tuple, phases_deg: np.ndarray) -> np.ndarray:
    """`z` with `mode`'s phases in the 0.1-10 s window replaced (amplitudes kept)."""
    z = z.copy()
    i, j = mode
    z[WINDOW, i, j] = np.abs(z[WINDOW, i, j]) * np.exp(1j * np.radians(phases_deg))
    return z


def test_physical_with_noisy_short_band() -> None:
    q = phase_quadrants(make_tf(synthetic_z()))
    assert q["xy_ok"] and q["yx_ok"], q
    assert q["xy_n"] >= 5 and q["yx_n"] >= 5, q
    assert (q["pmin"], q["pmax"]) == (0.1, 10.0), q
    print(f"  default 0.1-10 s: xy {q['xy']:+.1f} deg (n {q['xy_n']}), yx {q['yx']:+.1f} deg (n {q['yx_n']}): physical")


def test_flipped_mode_fires() -> None:
    for mode, (i, j), other in (("xy", (0, 1), "yx"), ("yx", (1, 0), "xy")):
        z = synthetic_z()
        z[:, i, j] *= -1.0
        q = phase_quadrants(make_tf(z))
        assert not q[f"{mode}_ok"], (mode, q)
        assert q[f"{other}_ok"], (mode, q)
        print(f"  {mode} negated: {mode} {q[mode]:+.1f} deg -> alarm; {other} {q[other]:+.1f} deg -> ok")


def test_old_window_arbitrary_new_window_clean() -> None:
    n_seeds = 200
    old_alarms = new_alarms = 0
    for seed in range(n_seeds):
        tf = make_tf(synthetic_z(seed))
        q_new = phase_quadrants(tf)
        q_old = phase_quadrants(tf, **OLD)
        new_alarms += not (q_new["xy_ok"] and q_new["yx_ok"])
        old_alarms += not (q_old["xy_ok"] and q_old["yx_ok"])
    assert new_alarms == 0, f"default window raised {new_alarms}/{n_seeds} false alarms"
    assert old_alarms >= n_seeds // 2, (
        f"old window raised only {old_alarms}/{n_seeds}: the synthetic no longer reproduces the D05 failure"
    )
    print(f"  {n_seeds} noisy seeds: old 0.01-0.1 s window false alarms {old_alarms}/{n_seeds}, "
          f"default 0.1-10 s {new_alarms}/{n_seeds}")


def test_too_few_periods() -> None:
    m = np.flatnonzero(WINDOW)
    for fill, label in ((np.nan, "NaN"), (0.0, "zero")):
        z = synthetic_z()
        z[m[4:], 0, 1] = fill  # four finite xy periods left in the window
        q = phase_quadrants(make_tf(z))
        assert q["xy_n"] == 4 and not q["xy_ok"] and np.isnan(q["xy"]), (label, q)
        assert "xy" in q["reason"] and "fewer than 5" in q["reason"], (label, q)
        assert q["yx_ok"] and q["yx_n"] == m.size, (label, q)
        print(f"  xy with 4 finite periods ({label} elsewhere): not judged, reason {q['reason']!r}; yx still ok")


def test_wrap_at_180() -> None:
    n = int(WINDOW.sum())
    alternate = np.arange(n) % 2 == 0

    z = with_phases(synthetic_z(), (1, 0), np.where(alternate, -172.0, -184.0))
    q = phase_quadrants(make_tf(z))
    _, _, phi, _, _ = rho_phi(make_tf(z))
    naive = float(np.median(phi[WINDOW, 1, 0]))
    assert not (-180.0 < naive < -90.0), f"naive median {naive} already passes: the case has no teeth"
    assert q["yx_ok"] and abs(q["yx"] - (-178.0)) < 1.0, q
    print(f"  physical yx at -172/-184 deg: median {q['yx']:+.1f} deg -> ok "
          f"(plain median of the raw angles: {naive:+.1f}, would alarm)")

    z = with_phases(synthetic_z(), (0, 1), np.where(alternate, -174.0, -182.0))
    q = phase_quadrants(make_tf(z))
    _, _, phi, _, _ = rho_phi(make_tf(z))
    naive = float(np.median(phi[WINDOW, 0, 1]))
    assert 0.0 < naive < 90.0, f"naive median {naive} already fails: the case has no teeth"
    assert not q["xy_ok"], q
    print(f"  flipped xy at -174/-182 deg: median {q['xy']:+.1f} deg -> alarm "
          f"(plain median of the raw angles: {naive:+.1f}, would pass)")


def test_real_d05() -> None:
    if not D05_EDI.exists():
        print(f"  SKIP: {D05_EDI} not found")
        return
    tf = TF(fn=str(D05_EDI))
    tf.read()
    q = phase_quadrants(tf)
    assert q["xy_ok"] and q["yx_ok"], q
    q_old = phase_quadrants(tf, **OLD)
    assert not q_old["xy_ok"], f"old window no longer reproduces the D05 false alarm: {q_old}"
    print(f"  D05 default: xy {q['xy']:+.1f} (n {q['xy_n']}), yx {q['yx']:+.1f} (n {q['yx_n']}): no alarm; "
          f"old window: xy {q_old['xy']:+.1f} -> the false alarm")
    z0 = np.asarray(tf.impedance.data).copy()
    for mode, (i, j), other in (("xy", (0, 1), "yx"), ("yx", (1, 0), "xy")):
        z = z0.copy()
        z[:, i, j] *= -1.0
        tf.impedance = z
        q = phase_quadrants(tf)
        assert not q[f"{mode}_ok"] and q[f"{other}_ok"], (mode, q)
        print(f"  D05 with {mode} negated in memory: {mode} {q[mode]:+.1f} deg -> alarm, {other} ok")
    tf.impedance = z0


def main() -> int:
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [
        test_physical_with_noisy_short_band,
        test_flipped_mode_fires,
        test_old_window_arbitrary_new_window_clean,
        test_too_few_periods,
        test_wrap_at_180,
        test_real_d05,
    ]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  compare_unit ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
