# -*- coding: utf-8 -*-
"""
Apparent resistivity and phase overlays for transfer-function comparison

`rho_phi` converts a TF object or EDI file to apparent resistivity and phase
with 1-sigma errors. `phase_quadrants` checks that the median xy and yx
phases sit in their physical quadrants, which flags a reversed dipole or
coil. `plot_comparison` overlays one main TF on reference, baseline and
other curves and optionally saves a PNG.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mt_metadata.transfer_functions.core import TF


def rho_phi(tf_or_path):
    """Compute apparent resistivity and phase from a TF or EDI path.

    Args:
        tf_or_path (TF or str or Path): An mt_metadata TF object, or a path
            to a file TF can read.

    Returns:
        tuple: ``(period, rho, phase_deg, rho_err, phase_err)``. `period` is
        (nf,) in s; the other arrays are (nf, 2, 2), rho in ohm-m and phase
        in degrees. Errors are 1-sigma, propagated from the impedance
        errors, and are zero when the file carries no variances.
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
    """Median phase taken on a branch cut 90 deg above the quadrant centre.

    The phases are wrapped into [c - 270, c + 90), where c is the centre of
    the quadrant (lo, hi). The cut sits halfway between the physical
    quadrant and its 180 deg flip, 90 deg from each, so a physical mode with
    phases near the +/-180 wrap (yx near -180 with noise reading +178) and a
    flipped mode each stay on one side of it and are not split into two
    clusters with a median between them. The cut of np.angle at +/-180 runs
    through the edge of the yx quadrant.

    Args:
        phi_deg (np.ndarray): Phases in degrees.
        lo (float): Lower edge of the physical quadrant in degrees.
        hi (float): Upper edge of the physical quadrant in degrees.

    Returns:
        float: Median phase in degrees, in (-180, 180].
    """
    c = 0.5 * (lo + hi)
    wrapped = np.mod(phi_deg - (c - 270.0), 360.0) + (c - 270.0)
    m = float(np.mod(np.median(wrapped) + 180.0, 360.0) - 180.0)
    return 180.0 if m == -180.0 else m


def phase_quadrants(tf_or_path, pmin: float = 0.1, pmax: float = 10.0, min_periods: int = 5) -> dict:
    """Check that the median impedance phases sit in the physical quadrants.

    The physical quadrants are xy in (0, 90) deg and yx in (-180, -90) deg.
    One mode 180 deg out means an E or H channel has the wrong sign, most
    often a dipole-polarity convention (see SiteConfig.flip_reversed_dipoles).

    The default window of 0.1-10 s is a band where broadband sites normally
    carry signal. At a noisy broadband site the 0.01-0.1 s band can be pure
    noise with random phases, whose median is arbitrary and can report a false
    180 deg flip while the 0.1-10 s phases sit well inside their quadrant.
    Pass ``pmin=0.01, pmax=0.1`` to check that band.

    A mode is judged on at least `min_periods` periods in the window with a
    finite, non-zero impedance. With fewer, its ``*_ok`` is False and
    ``reason`` says why. Only periods inside [pmin, pmax] are used.

    Args:
        tf_or_path (TF or str or Path): TF object or path to an EDI file.
        pmin (float): Shortest period of the window in s.
        pmax (float): Longest period of the window in s.
        min_periods (int): Minimum number of usable periods per mode.

    Returns:
        dict: ``"xy"`` and ``"yx"`` (median phase in deg, in (-180, 180],
        NaN when not judged), ``"xy_ok"`` and ``"yx_ok"`` (bool),
        ``"xy_n"`` and ``"yx_n"`` (periods used), ``"pmin"``, ``"pmax"``
        and ``"reason"`` (empty when both modes were judged).
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
    """Overlay xy and yx apparent resistivity and phase.

    Args:
        main (TF or str or Path): TF drawn bold in colour, with error bars.
        references (iterable): TFs or paths drawn thin grey, for example
            per-chunk EDIs.
        baseline (TF or str or Path, optional): TF drawn black dashed, for
            example the final merged legacy EDI.
        others (iterable): ``(tf_or_path, label, colour)`` tuples drawn thin,
            xy solid and yx dashed.
        title (str): Axes title.
        out_png (str or Path, optional): If given, the figure is saved here
            at 150 dpi and closed.
        main_label (str): Legend label of `main`.
        ref_label (str): Legend label of `references`.
        baseline_label (str): Legend label of `baseline`.

    Returns:
        matplotlib.figure.Figure: The figure. The yx phase is plotted plus
        180 deg so both modes share the 0-90 deg axis.
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
