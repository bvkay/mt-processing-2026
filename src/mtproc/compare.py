"""Quick apparent-resistivity / phase overlays for TF comparison."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mt_metadata.transfer_functions.core import TF


def rho_phi(tf_or_path):
    """Return (period, rho, phase_deg, rho_err, phase_err) from a TF or EDI path.

    All arrays are (nf, 2, 2); errors are 1-sigma, propagated from the
    impedance errors (zeros when the file carries no variances).
    """
    tf = tf_or_path
    if not isinstance(tf, TF):
        tf = TF(fn=str(tf_or_path))
        tf.read()
    period = np.asarray(tf.period, dtype=float)
    z = np.asarray(tf.impedance.data)  # mV/km/nT
    az = np.abs(z)
    rho = 0.2 * period[:, None, None] * az**2
    phi = np.degrees(np.angle(z))
    ze = np.zeros_like(az)
    if tf.impedance_error is not None:
        ze = np.nan_to_num(np.asarray(tf.impedance_error.data, dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(az > 0, ze / az, 0.0)
    rho_err = 2.0 * rho * rel
    phi_err = np.degrees(rel)
    return period, rho, phi, rho_err, phi_err


# Where each mode's physical phases sit (deg): xy in (0, 90), yx in (-180, -90).
QUADRANTS = {"xy": (0.0, 90.0), "yx": (-180.0, -90.0)}


def _median_phase(phi_deg: np.ndarray, lo: float, hi: float) -> float:
    """Median of `phi_deg` taken on a branch cut 90 deg above the quadrant's
    centre (the interval [c - 270, c + 90)), returned in (-180, 180].

    The cut sits halfway between the physical quadrant (centre c) and its
    180-deg flip (centre c - 180), 90 deg from each: a physical mode with
    phases near a +-180 wrap (yx near -180 whose noise reads +178) and a
    flipped one are each kept on one side of it, so neither is split into
    two clusters whose median lands between them. np.angle's own cut at
    +-180 runs straight through the yx quadrant's edge.
    """
    c = 0.5 * (lo + hi)
    wrapped = np.mod(phi_deg - (c - 270.0), 360.0) + (c - 270.0)
    m = float(np.mod(np.median(wrapped) + 180.0, 360.0) - 180.0)
    return 180.0 if m == -180.0 else m


def phase_quadrants(tf_or_path, pmin: float = 0.1, pmax: float = 10.0, min_periods: int = 5) -> dict:
    """Median impedance phases over [pmin, pmax] s and whether they sit in the
    physical quadrants: xy in (0, 90) deg, yx in (-180, -90) deg.

    One mode 180 deg out means an E or H channel has the wrong sign -- almost
    always a dipole-polarity convention (see SiteConfig.flip_reversed_dipoles).

    The default window is 0.1-10 s, the band that carried signal at every
    Line D and Curnamona site so far. At a noisy broadband site the
    0.01-0.1 s band can be pure noise with random phases, whose median is
    arbitrary and can trigger a false "180 deg out": Morocco D05 RR D13
    read xy -90 deg there while its 0.1-10 s phases were a clean 25-49 deg.
    Pass ``pmin=0.01, pmax=0.1`` for that band instead.

    A mode is judged only on at least `min_periods` periods in the window
    with a finite, non-zero impedance; with fewer, its ``*_ok`` is False and
    ``reason`` says why (a TF with almost nothing in 0.1-10 s needs a look
    either way). No fallback to other periods: judging a band the caller did
    not ask for is how the false alarm above happened.

    Returns ``{"xy", "yx"}`` (median phase, deg, in (-180, 180]; NaN when not
    judged), ``{"xy_ok", "yx_ok"}``, ``{"xy_n", "yx_n"}`` (periods used),
    ``pmin``, ``pmax`` and ``reason`` ("" when both modes were judged).
    """
    period, rho, phi, _, _ = rho_phi(tf_or_path)
    out = {"pmin": float(pmin), "pmax": float(pmax)}
    reasons = []
    in_window = (period >= pmin) & (period <= pmax)
    for mode, (i, j) in (("xy", (0, 1)), ("yx", (1, 0))):
        vals = phi[:, i, j]
        # np.angle gives a finite 0 deg for a zero impedance: rho 0 marks it
        good = in_window & np.isfinite(vals) & np.isfinite(rho[:, i, j]) & (rho[:, i, j] > 0)
        n = int(good.sum())
        out[f"{mode}_n"] = n
        lo, hi = QUADRANTS[mode]
        if n < min_periods:
            out[mode] = float("nan")
            out[f"{mode}_ok"] = False
            reasons.append(f"{mode}: {n} finite period(s) in {pmin:g}-{pmax:g} s, fewer than {min_periods}")
            continue
        med = _median_phase(vals[good], lo, hi)
        out[mode] = med
        out[f"{mode}_ok"] = bool(lo < med < hi)
    out["reason"] = "; ".join(reasons)
    return out


def plot_comparison(
    main,
    references=(),
    baseline=None,
    others=(),
    title="",
    out_png=None,
    main_label="aurora",
    ref_label="lemimt chunks",
    baseline_label="lemimt merged",
):
    """Overlay xy/yx apparent resistivity and phase.

    `main` bold and coloured, `baseline` (e.g. the final merged legacy EDI)
    black dashed, `references` (e.g. per-chunk EDIs) thin grey, `others` a
    list of (tf_or_path, label, colour) plotted thin (xy solid, yx dashed).
    """
    fig, (ax_r, ax_p) = plt.subplots(
        2, 1, figsize=(8, 9), sharex=True, height_ratios=[2, 1], layout="constrained"
    )
    for i, ref in enumerate(references):
        p, rho, phi, _, _ = rho_phi(ref)
        kw = dict(color="0.65", lw=0.8, alpha=0.8)
        ax_r.loglog(p, rho[:, 0, 1], label=f"xy ({ref_label})" if i == 0 else None, **kw)
        ax_r.loglog(p, rho[:, 1, 0], ls="--", label=f"yx ({ref_label})" if i == 0 else None, **kw)
        ax_p.semilogx(p, phi[:, 0, 1], **kw)
        ax_p.semilogx(p, phi[:, 1, 0] + 180.0, ls="--", **kw)

    ax_r.set_xscale("log")
    ax_r.set_yscale("log")
    ax_p.set_xscale("log")

    if baseline is not None:
        p, rho, phi, rerr, perr = rho_phi(baseline)
        kw = dict(color="k", lw=1.2, elinewidth=0.7, capsize=1.5, alpha=0.85)
        ax_r.errorbar(p, rho[:, 0, 1], yerr=rerr[:, 0, 1], label=f"xy ({baseline_label})", **kw)
        ax_r.errorbar(p, rho[:, 1, 0], yerr=rerr[:, 1, 0], ls="--", label=f"yx ({baseline_label})", **kw)
        ax_p.errorbar(p, phi[:, 0, 1], yerr=perr[:, 0, 1], **kw)
        ax_p.errorbar(p, phi[:, 1, 0] + 180.0, yerr=perr[:, 1, 0], ls="--", **kw)

    for other, label, colour in others:
        p, rho, phi, rerr, perr = rho_phi(other)
        kw = dict(color=colour, lw=1.0, ms=2.0, elinewidth=0.5, capsize=1.0, alpha=0.9)
        ax_r.errorbar(p, rho[:, 0, 1], yerr=rerr[:, 0, 1], fmt="o-", label=f"xy ({label})", **kw)
        ax_r.errorbar(p, rho[:, 1, 0], yerr=rerr[:, 1, 0], fmt="s--", label=f"yx ({label})", **kw)
        ax_p.errorbar(p, phi[:, 0, 1], yerr=perr[:, 0, 1], fmt="o-", **kw)
        ax_p.errorbar(p, phi[:, 1, 0] + 180.0, yerr=perr[:, 1, 0], fmt="s--", **kw)

    p, rho, phi, rerr, perr = rho_phi(main)
    kw = dict(ms=3.5, lw=1.2, elinewidth=0.8, capsize=2.0)
    ax_r.errorbar(p, rho[:, 0, 1], yerr=rerr[:, 0, 1], fmt="o-", color="C0", label=f"xy ({main_label})", **kw)
    ax_r.errorbar(p, rho[:, 1, 0], yerr=rerr[:, 1, 0], fmt="s-", color="C3", label=f"yx ({main_label})", **kw)
    ax_p.errorbar(p, phi[:, 0, 1], yerr=perr[:, 0, 1], fmt="o-", color="C0", **kw)
    ax_p.errorbar(p, phi[:, 1, 0] + 180.0, yerr=perr[:, 1, 0], fmt="s-", color="C3", **kw)

    ax_r.set_ylabel(r"$\rho_a$ ($\Omega$m)")
    ax_p.set_ylabel("phase (deg)")
    ax_p.set_xlabel("period (s)")
    ax_p.set_ylim(0, 90)
    ax_r.grid(True, which="both", alpha=0.3)
    ax_p.grid(True, which="both", alpha=0.3)
    ax_r.legend(fontsize=9)
    ax_r.set_title(title)

    if out_png:
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
    return fig
