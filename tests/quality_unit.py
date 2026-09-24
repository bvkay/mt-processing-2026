# -*- coding: utf-8 -*-
"""
Unit test for mtproc.quality

Checks `tf_quality`, `agreement` and `pairwise_spread` on synthetic TFs,
without Qt or a survey. Every TF is written to an EDI through mt_metadata and
read back from the file, as scripts/campaign.py reads aurora's products.

The smooth TF spans 0.005-5000 s at 10 per decade (61 periods), with
log10 rho = 2 + 0.6 tanh(log10 T) (40 to 400 ohm m), xy phase
45 - 12 tanh(log10 T) deg and yx the same minus 180 (the physical
quadrants), and 5 % impedance errors.

Usage:
    python tests/quality_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) the smooth TF scores under 0.9 overall, or either mode's quadrant
    fraction is not 1, its roughness is 0.06 dex or more, or it has a blow-up;

(2) the noisy TF (rho times 10**N(0, 0.3) per period and mode, and the phase
    of every third period replaced by a uniformly random one, seeded) scores
    0.4 or more, or less than 0.5 below the smooth one;

(3) negating Zxy (xy 180 deg out) does not take xy's quadrant fraction from
    1 to 0 with yx's staying at 1, xy's score to 0 and the overall score to
    yx's alone halved;

(4) three periods at 1e7 ohm m and one at 1e-4 in xy are not counted as four
    xy blow-ups (none in yx), or do not lower the score by at least
    exp(-5 * 4 / 61) of xy's own share;

(5) `pmin` does not restrict, or a noisy band narrower than half the record
    is not charged for: with the noise confined below 0.1 s (13 of 61
    periods, 21 %), the 0.1-5000 s score must be over 0.9 and the full-range
    score under it by more than 0.1 (half the noisy fraction). This first ran
    with 0.2 against a score that used the *median* roughness and failed
    (0.935 vs 0.997: the median ignores noise in under half of the steps);
    the score now takes the per-step mean `smoothness` instead, and 0.1 is
    what a charge proportional to the noisy band must beat while the old
    median-based score (0.06) still fails it;

(6) the smooth TF at 8 and at 12 bands per decade scores more than 0.05
    apart (the docstring's claim that band density alone barely moves the
    score);

(7) `agreement` of a TF with itself is not exactly 0 dex / 0 deg over all 61
    periods; with a copy whose |Z| is scaled by sqrt(10) not 1.0 dex and
    0 deg; with the 8-per-decade TF, counts periods that do not coincide:
    both grids start at 0.005 s, so they share every half decade (10/decade
    index 5j = 8/decade index 4j), 13 periods; the nearest pair that does not
    coincide is 5.9 % apart, outside the 2 % match (first written as "seven,
    the decade points" -- an arithmetic slip, corrected, not a behaviour);

(8) `pairwise_spread` of three TFs -- two identical, the third 0.5 dex higher
    over 1-10 s only -- is not 0.5 dex over 1-10 s and 0 elsewhere (the median
    of the pairs 0, 0.5, 0.5), or reports anything but 3 valid TFs per period.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mtproc.quality import agreement, pairwise_spread, tf_quality  # noqa: E402

OUT = Path(tempfile.mkdtemp(prefix="quality_unit_"))


def periods(per_decade: float = 10.0) -> np.ndarray:
    """Return log-spaced periods from 0.005 to 5000 s at `per_decade` per decade."""
    n = int(round(6.0 * per_decade)) + 1  # 0.005 .. 5000 s
    return np.logspace(np.log10(0.005), np.log10(5000.0), n)


def smooth_z(period: np.ndarray) -> np.ndarray:
    """Return the smooth (nf, 2, 2) impedance described in the module docstring."""
    x = np.log10(period)
    rho = 10.0 ** (2.0 + 0.6 * np.tanh(x))
    amp = np.sqrt(rho / (0.2 * period))
    phi_xy = 45.0 - 12.0 * np.tanh(x)
    z = np.zeros((period.size, 2, 2), dtype=complex)
    z[:, 0, 1] = amp * np.exp(1j * np.radians(phi_xy))
    z[:, 1, 0] = amp * np.exp(1j * np.radians(phi_xy - 180.0))
    return z


def write_edi(name: str, period: np.ndarray, z: np.ndarray) -> Path:
    """Write an impedance with 5 % errors to OUT/<name>.edi.

    Args:
        name (str): File stem.
        period (np.ndarray): Periods in seconds.
        z (np.ndarray): (nf, 2, 2) impedance.

    Returns:
        Path: The EDI written.
    """
    tf = TF()
    tf.station = "SYN"
    tf.period = period
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    path = OUT / f"{name}.edi"
    tf.write(fn=path, file_type="edi")
    return path


def noisy(z: np.ndarray, rows: np.ndarray, seed: int = 3) -> np.ndarray:
    """Add noise to an impedance on selected periods.

    On `rows`, rho is multiplied by 10**N(0, 0.3) and every third period's
    phase is replaced by a uniformly random one, per mode.

    Args:
        z (np.ndarray): (nf, 2, 2) impedance; a copy is modified.
        rows (np.ndarray): Boolean mask of the periods to perturb.
        seed (int): Seed of the random generator.

    Returns:
        np.ndarray: The noisy copy.
    """
    z = z.copy()
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(rows)
    for i, j in ((0, 1), (1, 0)):
        gain = 10.0 ** (0.5 * rng.normal(0.0, 0.3, idx.size))  # |Z| gain; rho goes as its square
        z[idx, i, j] *= gain
        third = idx[::3]
        z[third, i, j] = np.abs(z[third, i, j]) * np.exp(1j * rng.uniform(-np.pi, np.pi, third.size))
    return z


P = periods()
SMOOTH = write_edi("smooth", P, smooth_z(P))


def test_smooth_scores_high() -> None:
    q = tf_quality(SMOOTH)
    assert q["n_periods"] == 61, q["n_periods"]
    assert q["overall"]["score"] >= 0.9, q["overall"]
    for m in ("xy", "yx"):
        assert q[m]["quadrant_frac"] == 1.0 and q[m]["roughness"] < 0.06 and q[m]["blowups"] == 0, (m, q[m])
    print(f"  smooth: score {q['overall']['score']:.3f}, roughness xy {q['xy']['roughness']:.3f} "
          f"yx {q['yx']['roughness']:.3f} dex, rel err {q['overall']['median_rel_err']:.3f}")


def test_noisy_scores_low() -> None:
    s = tf_quality(SMOOTH)["overall"]["score"]
    path = write_edi("noisy", P, noisy(smooth_z(P), np.ones(P.size, dtype=bool)))
    q = tf_quality(path)
    assert q["overall"]["score"] < 0.4 and s - q["overall"]["score"] >= 0.5, (s, q["overall"])
    print(f"  noisy: score {q['overall']['score']:.3f} (smooth {s:.3f}); quadrant xy "
          f"{q['xy']['quadrant_frac']:.2f} yx {q['yx']['quadrant_frac']:.2f}, roughness "
          f"{q['overall']['roughness']:.3f} dex")


def test_flipped_mode() -> None:
    z = smooth_z(P)
    z[:, 0, 1] *= -1.0
    q = tf_quality(write_edi("flipped_xy", P, z))
    assert q["xy"]["quadrant_frac"] == 0.0 and q["yx"]["quadrant_frac"] == 1.0, (q["xy"], q["yx"])
    assert q["xy"]["score"] == 0.0 and abs(q["overall"]["score"] - q["yx"]["score"] / 2.0) < 1e-12, q["overall"]
    print(f"  Zxy negated: quadrant xy {q['xy']['quadrant_frac']:.2f} (was 1.00), yx "
          f"{q['yx']['quadrant_frac']:.2f}; score {q['overall']['score']:.3f}")


def test_blowups() -> None:
    z = smooth_z(P)
    amp = lambda rho: np.sqrt(rho / (0.2 * P))  # noqa: E731
    for k in (10, 30, 50):
        z[k, 0, 1] = amp(1e7)[k] * np.exp(1j * np.angle(z[k, 0, 1]))
    z[40, 0, 1] = amp(1e-4)[40] * np.exp(1j * np.angle(z[40, 0, 1]))
    q = tf_quality(write_edi("blowups", P, z))
    s = tf_quality(SMOOTH)
    assert q["xy"]["blowups"] == 4 and q["yx"]["blowups"] == 0 and q["overall"]["blowups"] == 4, q
    assert q["xy"]["score"] <= s["xy"]["score"] * np.exp(-5.0 * 4 / 61) + 1e-12, (q["xy"], s["xy"])
    print(f"  4 xy blow-ups: counted {q['xy']['blowups']}, xy score {q['xy']['score']:.3f} "
          f"(smooth {s['xy']['score']:.3f})")


def test_window() -> None:
    path = write_edi("noisy_short", P, noisy(smooth_z(P), P < 0.1))
    full = tf_quality(path)["overall"]["score"]
    long_ = tf_quality(path, pmin=0.1)["overall"]["score"]
    assert long_ > 0.9 and long_ - full > 0.1, (full, long_)
    print(f"  noise below 0.1 s: full range {full:.3f}, pmin 0.1 s {long_:.3f}")


def test_band_density() -> None:
    scores = {}
    for pd_ in (8.0, 12.0):
        p = periods(pd_)
        scores[pd_] = tf_quality(write_edi(f"smooth_pd{int(pd_)}", p, smooth_z(p)))["overall"]["score"]
    assert abs(scores[8.0] - scores[12.0]) <= 0.05, scores
    print(f"  smooth at 8 / 12 per decade: {scores[8.0]:.3f} / {scores[12.0]:.3f}")


def test_agreement() -> None:
    a = agreement(SMOOTH, SMOOTH)
    assert a["n_common"] == 61 and a["overall"]["dlog_rho"] == 0.0 and a["overall"]["dphase"] == 0.0, a
    scaled = write_edi("scaled", P, smooth_z(P) * np.sqrt(10.0))
    b = agreement(SMOOTH, scaled)
    for m in ("xy", "yx"):  # the EDI's text precision: ~5e-6 deg of phase
        assert abs(b[m]["dlog_rho"] - 1.0) < 1e-6 and b[m]["dphase"] < 1e-4, (m, b[m])
    p8 = periods(8.0)
    c = agreement(SMOOTH, write_edi("smooth_pd8b", p8, smooth_z(p8)))
    assert c["n_common"] == 13, c
    print(f"  self: {a['overall']['dlog_rho']} dex over {a['n_common']}; x sqrt(10): "
          f"{b['overall']['dlog_rho']:.6f} dex, {b['overall']['dphase']:.2g} deg; vs 8/decade: "
          f"{c['n_common']} common periods")


def test_pairwise_spread() -> None:
    z = smooth_z(P)
    band = (P >= 1.0) & (P <= 10.0)
    z3 = z.copy()
    z3[band] *= 10.0 ** 0.25  # rho up 0.5 dex
    paths = [SMOOTH, write_edi("copy", P, z), write_edi("offset", P, z3)]
    s = pairwise_spread(paths)
    for m in ("xy", "yx"):
        assert np.allclose(s["dlog_rho"][m][band], 0.5, atol=1e-6), s["dlog_rho"][m][band]
        assert np.allclose(s["dlog_rho"][m][~band], 0.0, atol=1e-6), s["dlog_rho"][m][~band]
        assert (s["n"][m] == 3).all(), s["n"][m]
    print(f"  spread: {s['dlog_rho']['xy'][band].round(3).tolist()} dex over 1-10 s, "
          f"max {np.nanmax(s['dlog_rho']['xy'][~band]):.1g} elsewhere")


def main() -> int:
    """Print the test contract and run every test.

    Returns:
        int: 0 when every test passes, 1 otherwise.
    """
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [test_smooth_scores_high, test_noisy_scores_low, test_flipped_mode, test_blowups,
             test_window, test_band_density, test_agreement, test_pairwise_spread]
    failed = 0
    for t in tests:
        print(t.__name__)
        try:
            t()
            print("  PASS")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
