"""Quick apparent-resistivity / phase overlays for TF comparison."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mt_metadata.transfer_functions.core import TF


def rho_phi(tf_or_path):
    """Return (period, rho[nf,2,2], phase_deg[nf,2,2]) from a TF or EDI path."""
    tf = tf_or_path
    if not isinstance(tf, TF):
        tf = TF(fn=str(tf_or_path))
        tf.read()
    period = np.asarray(tf.period, dtype=float)
    z = np.asarray(tf.impedance.data)  # mV/km/nT
    rho = 0.2 * period[:, None, None] * np.abs(z) ** 2
    phi = np.degrees(np.angle(z))
    return period, rho, phi


def plot_comparison(main, references=(), title="", out_png=None, main_label="aurora", ref_label="lemimt"):
    """Overlay xy/yx apparent resistivity and phase; `main` bold, refs grey."""
    fig, (ax_r, ax_p) = plt.subplots(
        2, 1, figsize=(8, 9), sharex=True, height_ratios=[2, 1], layout="constrained"
    )
    for i, ref in enumerate(references):
        p, rho, phi = rho_phi(ref)
        kw = dict(color="0.65", lw=0.8, alpha=0.8)
        ax_r.loglog(p, rho[:, 0, 1], label=f"xy ({ref_label})" if i == 0 else None, **kw)
        ax_r.loglog(p, rho[:, 1, 0], ls="--", label=f"yx ({ref_label})" if i == 0 else None, **kw)
        ax_p.semilogx(p, phi[:, 0, 1], **kw)
        ax_p.semilogx(p, phi[:, 1, 0] + 180.0, ls="--", **kw)

    p, rho, phi = rho_phi(main)
    ax_r.loglog(p, rho[:, 0, 1], "o-", color="C0", ms=3.5, lw=1.2, label=f"xy ({main_label})")
    ax_r.loglog(p, rho[:, 1, 0], "s-", color="C3", ms=3.5, lw=1.2, label=f"yx ({main_label})")
    ax_p.semilogx(p, phi[:, 0, 1], "o-", color="C0", ms=3.5, lw=1.2)
    ax_p.semilogx(p, phi[:, 1, 0] + 180.0, "s-", color="C3", ms=3.5, lw=1.2)

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
