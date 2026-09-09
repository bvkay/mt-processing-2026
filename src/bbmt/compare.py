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


def plot_comparison(
    main,
    references=(),
    baseline=None,
    title="",
    out_png=None,
    main_label="aurora",
    ref_label="lemimt chunks",
    baseline_label="lemimt merged",
):
    """Overlay xy/yx apparent resistivity and phase.

    `main` bold and coloured, `baseline` (e.g. the final merged legacy EDI)
    black dashed, `references` (e.g. per-chunk EDIs) thin grey.
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
