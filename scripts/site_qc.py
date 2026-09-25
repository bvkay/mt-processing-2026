# -*- coding: utf-8 -*-
"""
Per-site time-resolved QC: four figures per site, one command

The AusLAMP per-site QC pages, ported to broadband. One run per site gives
what is needed to decide whether a site is worth processing and which
stretches of it to mask:

  <site>_01_overview.png        the whole record as laid, one panel per
                                channel, 1-second means over the 1-second
                                range, dotted median, median/std/range
  <site>_02_band_coherence.png  squared coherence per window against time,
                                one line per band group, running median,
                                one panel per pair (+4 remote pairs)
  <site>_03_coherogram.png      the same coherence as an image, period (log)
                                against time, one panel per pair
  <site>_04_spectrogram.png     power density in dB per channel, period (log)
                                against time

All four read the site's MTH5 in <workspace>/mth5/<site>.h5, with every run
concatenated onto one sample grid (NaN in the gaps) so the whole deployment
appears. A remote is placed on the local sample grid, so all four figures
share one time axis and the coherogram lines up with the overview. Magnetics
carry the scalar part of the MTH5 filter chain only (LEMI linear coefficient
x `lemi423_b_scale`); the coil response is a shape, which a near-DC overview
does not need. Electrics are fully calibrated: their chain is two
coefficient filters, dipole length included.

Checks run at the end of every invocation and are printed as CHECK lines.
**They fail if**

(a) *calibration and placement*: for any channel, a sample read back
    independently from the MTH5 (its own fresh open, its index mapped to a run
    from the run metadata alone, its gain recomputed from the filter chain)
    differs from the value figure 01 draws at that same absolute sample by
    more than 1e-5 of the channel's standard deviation. This is what catches a
    wrong gain, a dropped filter stage, a sign error, a lost DC offset or a
    misplaced run.
(b) *the 1-second reduction*: the mean of the 1-second means differs from the
    mean of the channel's full-rate samples by more than 1e-6 of the
    channel's standard deviation (0.05 sigma on a record with gaps, where a
    partly-empty block still counts once).
(c) *the dead band*: the median Bx-Ey and By-Ex coherence over 2-10 s is not
    at least 0.15 below the median over both 0.1-1 s and 30-300 s, i.e. the
    figures do not reproduce a dead band known to be there.
    Reported for every site and asserted with --assert-dead-band, since a
    clean site has none.

Two quantities are reported rather than asserted:

- The median of the 1-second means differs from the median of the samples, by
  a few % of a standard deviation. The two means agree to rounding error, so
  the reduction is exact; the medians differ because block averaging changes
  the distribution's shape. The median of the means tracks the mean, while the
  sample median tracks the raw distribution, which the high-frequency content
  skews. The difference is printed in units of the channel's standard
  deviation and flagged above 0.1 sigma.
- The 50 Hz mains line is invisible in figure 04. A line a few dB above the
  broadband floor in a 1 Hz resolution bandwidth is diluted to a fraction of a
  dB by a log-period bin at 8 per decade, about 15 Hz wide at 50 Hz, whatever
  the colour limits. The excess is measured on the level-0 spectra instead and
  printed per channel.

Usage:
    python scripts/site_qc.py <survey.yaml> <site> [--remote NAME] [--win MIN]
                              [--step MIN] [--smooth HOURS] [--out-dir DIR]
                              [--assert-dead-band]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.survey import Survey
from crust.timefreq import (
    BANDS_S,
    CHANNELS,
    COLOUR,
    DAY,
    GUIDE_S,
    LOCAL_PAIRS,
    REMOTE_PAIRS,
    UNIT,
    Record,
    band_from_levels,
    block_stats,
    cascade,
    day_axis,
    iso,
    levels_plan,
    levels_to_grid,
    line_excess,
    load_station,
    merge,
    pair_label,
    running_median,
    spot_check_calibration,
)

DPI = 150
DEAD_BAND = (2.0, 10.0)
REFERENCE_BANDS = ((0.1, 1.0), (30.0, 300.0))
DEAD_BAND_DROP = 0.15
# sigma, for the independent MTH5 re-read. float32 storage of an
# offset-removed channel is good to ~1e-7 sigma, so this leaves two orders of
# margin and still catches any error that matters (a gain, a sign, a stage).
CAL_TOL = 1e-5
MEAN_TOL = 1e-6     # sigma, for the 1-second block reduction on a gapless record
MEAN_TOL_GAPS = 0.05  # with gaps the blocks are weighted equally, not by sample
MEDIAN_NOTE = 0.1   # sigma, above which the two medians are worth a look


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line of site_qc.py."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("site", help="site name (MTH5 in <workspace>/mth5/<site>.h5)")
    p.add_argument("--remote", metavar="NAME", help="remote site: adds four local-remote pairs")
    p.add_argument("--win", type=float, default=20.0, metavar="MIN", help="base window (default 20)")
    p.add_argument("--step", type=float, default=10.0, metavar="MIN", help="base step (default 10)")
    p.add_argument(
        "--smooth",
        type=float,
        metavar="HOURS",
        help="running median for figure 02 (default: min(3 h, record/12))",
    )
    p.add_argument("--out-dir", metavar="DIR", help="output folder (default <workspace>/qc)")
    p.add_argument(
        "--assert-dead-band",
        action="store_true",
        help="treat a missing 2-10 s dead band in Bx-Ey/By-Ex as a failure (for a survey known to have one)",
    )
    return p.parse_args(argv)


def station_h5(survey: Survey, station: str) -> Path:
    """Return <workspace>/mth5/<station>.h5.

    Raises:
        FileNotFoundError: When the station has no MTH5.
    """
    h5 = survey.workspace / "mth5" / f"{station}.h5"
    if not h5.exists():
        raise FileNotFoundError(f"no MTH5 for station {station!r}: {h5}")
    return h5


# ---------------------------------------------------------------- figure 01


def overview(record: Record, out: Path, survey_name: str, figsize=(15, 11), dpi=DPI):
    """Draw figure 01: the whole record as laid, one panel per channel.

    Each panel is the 1-second mean drawn over the 1-second range, with y
    limits at the 1st to 99th percentile of the 1-second means plus a 5 per
    cent pad, and the median as a dotted line printed with the channel's
    spread. The figure shows a dead channel, a rail, a step, a reversed axis
    and the moment an electrode fails.

    Args:
        record (Record): The site's record.
        out (Path): Output figure.
        survey_name (str): Survey name for the title.
        figsize (tuple): Figure size in inches.
        dpi (int): Figure resolution.

    Returns:
        dict: Per channel: median, mean, std, min, max, second_median and
        second_mean.
    """
    m = int(round(record.sample_rate))
    ticks, labels = day_axis(record.t0, record.duration_s)
    chans = [c for c in CHANNELS if c in record.arrays]
    fig, axes = plt.subplots(len(chans), 1, figsize=figsize, sharex=True, layout="constrained")
    stats = {}
    for ax, comp in zip(np.atleast_1d(axes), chans):
        x = record.arrays[comp]
        off = record.offsets[comp]
        mid, lo, hi = block_stats(x, m)
        mid, lo, hi = mid + off, lo + off, hi + off
        t = (np.arange(mid.size) * m + m / 2) / (record.sample_rate * DAY)
        col = COLOUR.get(comp, "0.3")
        ax.fill_between(t, lo, hi, lw=0, alpha=0.2, color=col, rasterized=True)
        ax.plot(t, mid, lw=0.7, color=col)

        pct = np.nanpercentile(x, (1, 50, 99)) if np.isnan(x).any() else np.percentile(x, (1, 50, 99))
        _, med, _ = pct + off
        sd = float(np.nanstd(x))
        rmin, rmax = float(np.nanmin(x)) + off, float(np.nanmax(x)) + off
        # the AusLAMP panel took its limits from the 1st-99th percentile of the
        # full-rate channel. At 1000 Hz the per-second mean has 1/sqrt(1000) of
        # the raw scatter, so those limits would flatten the mean curve: the
        # limits here are the 1st-99th percentile of the 1-second means, and
        # the 1-second range clips against them.
        p_lo, p_hi = np.nanpercentile(mid, (1, 99))
        if p_hi <= p_lo:
            # a railed or dead channel is flat (a coil sitting on the int32 rail
            # for the whole record); give it a readable axis rather than
            # matplotlib's 1e-14 offset notation
            span = max(abs(med) * 0.02, 1e-9)
            p_lo, p_hi = med - span / 2, med + span / 2
        pad = 0.05 * (p_hi - p_lo)
        ax.set_ylim(p_lo - pad, p_hi + pad)
        ax.axhline(med, color="k", lw=0.6, ls=":")
        unit = UNIT[comp]
        flat = "   <- FLAT: railed or dead" if sd == 0.0 else ""
        ax.text(
            0.004,
            0.94,
            f"median {med:.4g} {unit}, std {sd:.4g}, range {rmin:.4g} .. {rmax:.4g}{flat}",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="0.2",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75),
        )
        tag = ", scalar gain" if comp in record.scalar_only else ""
        ax.set_ylabel(f"{comp}\n({unit}{tag})", fontsize=9)
        ax.grid(alpha=0.25)
        n_whole = x.size // m * m
        stats[comp] = dict(
            median=float(med),
            mean=float(np.nanmean(x[:n_whole], dtype="float64")) + off,
            std=sd,
            min=rmin,
            max=rmax,
            second_median=float(np.nanmedian(mid)),
            second_mean=float(np.nanmean(mid)),
        )

    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels)
    axes[-1].set_xlim(0, record.duration_s / DAY)
    axes[-1].set_xlabel(f"days from {iso(record.t0)} UTC")
    note = (
        "magnetics: scalar gain only (LEMI linear coefficient x lemi423_b_scale); "
        "the coil response is a shape and is not deconvolved"
    )
    fig.suptitle(
        f"{survey_name} {record.station}: the whole record as laid, 1-second means "
        f"over the 1-second range\n{note}",
        fontsize=11,
    )
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return stats


# ---------------------------------------------------------------- figure 02


def band_coherence_figure(
    record: Record, coh_levels, out: Path, survey_name: str, smooth_h: float, step_s: float, dpi=DPI
):
    """Draw figure 02: squared coherence per window against time, one line per band group.

    Args:
        record (Record): The site's record.
        coh_levels (dict): Coherence levels per pair from `cascade`.
        out (Path): Output figure.
        survey_name (str): Survey name for the title.
        smooth_h (float): Running-median length in hours.
        step_s (float): Window step in seconds.
        dpi (int): Figure resolution.

    Returns:
        dict: Median coherence per band label, keyed by pair label.
    """
    pairs = list(coh_levels)
    fig, axes = plt.subplots(
        len(pairs), 1, figsize=(14, 2.1 * len(pairs) + 1.2), sharex=True, layout="constrained"
    )
    axes = np.atleast_1d(axes)
    ticks, labels = day_axis(record.t0, record.duration_s)
    w = max(1, int(round(smooth_h * 3600.0 / step_s)))
    table = {}
    for ax, pair in zip(axes, pairs):
        t = coh_levels[pair][0][0]
        row = {}
        for lo, hi, lab in BANDS_S:
            v = band_from_levels(coh_levels[pair], lo, hi, t)
            row[lab] = float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan
            ax.plot(t / DAY, running_median(v, w), lw=1.0, alpha=0.85, label=lab)
        table[pair_label(pair)] = row
        ax.axhline(0.5, color="0.5", ls="--", lw=0.6)
        ax.set_ylim(0, 1)
        ax.set_ylabel("coh " + pair_label(pair), fontsize=9)
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=7.5, loc="lower right", ncol=len(BANDS_S), framealpha=0.85)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels)
    axes[-1].set_xlim(0, record.duration_s / DAY)
    axes[-1].set_xlabel(f"days from {iso(record.t0)} UTC")
    fig.suptitle(
        f"{survey_name} {record.station}: the band coherence, "
        f"{smooth_h:g} h running median",
        fontsize=11,
    )
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return table


# ---------------------------------------------------------------- figure 03


def coherogram_figure(
    record: Record, coh_levels, out: Path, survey_name: str, smooth_h: float, step_s: float, dpi=DPI
):
    """Draw figure 03: squared coherence as an image, period (log) against time, one panel per pair."""
    pairs = list(coh_levels)
    fig = plt.figure(figsize=(14, 2.3 * len(pairs) + 1.2), layout="constrained")
    gs = fig.add_gridspec(len(pairs), 2, width_ratios=[70, 1])
    axes = [fig.add_subplot(gs[i, 0]) for i in range(len(pairs))]
    cax = fig.add_subplot(gs[:, 1])
    for a in axes[:-1]:
        a.sharex(axes[-1])
        a.tick_params(labelbottom=False)
    ticks, labels = day_axis(record.t0, record.duration_s)
    w = max(1, int(round(smooth_h * 3600.0 / step_s)))
    pc = None
    for ax, pair in zip(axes, pairs):
        t = coh_levels[pair][0][0]
        per, img = levels_to_grid(coh_levels[pair], t)
        img = running_median(img, w)
        pc = ax.pcolormesh(t / DAY, per, img.T, vmin=0, vmax=1, cmap="viridis", shading="gouraud")
        ax.set_yscale("log")
        ax.set_ylim(per.min(), per.max())
        ax.set_ylabel(f"{pair_label(pair)}\nperiod (s)", fontsize=9)
        for p in GUIDE_S:
            if per.min() <= p <= per.max():
                ax.axhline(p, color="w", lw=0.5, ls=":", alpha=0.7)
    fig.colorbar(pc, cax=cax, label="squared coherence")
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels)
    axes[-1].set_xlim(0, record.duration_s / DAY)
    axes[-1].set_xlabel(f"days from {iso(record.t0)} UTC")
    fig.suptitle(
        f"{survey_name} {record.station}: the coherogram, every level on the base "
        f"time grid, {smooth_h:g} h running median",
        fontsize=11,
    )
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------- figure 04


def spectrogram_figure(
    record: Record, pow_levels, out: Path, survey_name: str, smooth_h: float, step_s: float, dpi=DPI
):
    """Draw figure 04: power density in dB per channel, colour limits at the 2nd/98th percentile."""
    chans = [c for c in CHANNELS if c in pow_levels]
    fig, axes = plt.subplots(
        len(chans), 1, figsize=(14, 2.3 * len(chans) + 1.2), sharex=True, layout="constrained"
    )
    axes = np.atleast_1d(axes)
    ticks, labels = day_axis(record.t0, record.duration_s)
    w = max(1, int(round(smooth_h * 3600.0 / step_s)))
    for ax, comp in zip(axes, chans):
        t = pow_levels[comp][0][0]
        per, img = levels_to_grid(pow_levels[comp], t)
        with np.errstate(divide="ignore", invalid="ignore"):
            db = 10.0 * np.log10(img)
        db = running_median(db, w)
        vmin, vmax = np.nanpercentile(db, [2, 98]) if np.isfinite(db).any() else (-1.0, 1.0)
        pc = ax.pcolormesh(t / DAY, per, db.T, vmin=vmin, vmax=vmax, cmap="viridis",
                           shading="gouraud")
        ax.set_yscale("log")
        ax.set_ylim(per.min(), per.max())
        ax.set_ylabel(f"{comp}\nperiod (s)", fontsize=9)
        for p in GUIDE_S:
            if per.min() <= p <= per.max():
                ax.axhline(p, color="w", lw=0.5, ls=":", alpha=0.7)
        tag = " (scalar gain)" if comp in record.scalar_only else ""
        fig.colorbar(pc, ax=ax, label=f"dB ({UNIT[comp]})$^2$/Hz{tag}", fraction=0.02, pad=0.01)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels)
    axes[-1].set_xlim(0, record.duration_s / DAY)
    axes[-1].set_xlabel(f"days from {iso(record.t0)} UTC")
    fig.suptitle(
        f"{survey_name} {record.station}: the spectrograms, colour limits at each "
        f"channel's 2nd and 98th percentile, {smooth_h:g} h running median",
        fontsize=11,
    )
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------- checks


def check_calibration(record: Record, survey: Survey, site: str, remote: str | None) -> bool:
    """Run check (a): re-read samples independently from the MTH5 and compare with figure 01.

    Returns:
        bool: True when every channel is within CAL_TOL sigma.
    """
    worst = spot_check_calibration(station_h5(survey, site), survey.name, site, record)
    if remote:
        worst.update(
            spot_check_calibration(
                station_h5(survey, remote), survey.name, remote, record, ("hx", "hy"), "r_"
            )
        )
    ok = all(v <= CAL_TOL for v in worst.values())
    detail = ", ".join(f"{k} {v:.1e}" for k, v in worst.items())
    print(
        f"CHECK {'PASS' if ok else 'FAIL'}  calibration and run placement: worst re-read "
        f"difference {max(worst.values()):.1e} sigma (tol {CAL_TOL:g}) -- {detail}"
    )
    return ok


def check_second_means(record: Record, stats: dict) -> bool:
    """Run check (b): the 1-second reduction is exact; also report how far the medians differ.

    Returns:
        bool: True when every channel's mean of means is within tolerance.
    """
    ok = True
    # a block falling partly in a gap still counts once, so the mean of the
    # block means is only the record's mean where there are no gaps
    tol = MEAN_TOL if not record.gaps else MEAN_TOL_GAPS
    for comp, s in stats.items():
        sd = s["std"] or 1.0
        mean_err = abs(s["second_mean"] - s["mean"]) / sd
        med_err = abs(s["second_median"] - s["median"]) / sd
        good = mean_err <= tol
        ok &= good
        flag = "" if med_err <= MEDIAN_NOTE else "   <- worth a look"
        print(
            f"CHECK {'PASS' if good else 'FAIL'}  {comp}: 1-s mean of means vs channel mean "
            f"{mean_err:.1e} sigma (tol {tol:g}); medians differ {med_err:.3f} sigma "
            f"({s['second_median']:.6g} vs {s['median']:.6g} {UNIT[comp]}){flag}"
        )
    return ok


def check_lines(base_psd: dict, lines=(50.0, 100.0, 150.0)) -> None:
    """Print how far each mains line stands above its local floor, per channel.

    Printed rather than drawn: an 8-per-decade log-period bin at 50 Hz is
    about 15 Hz wide and dilutes a narrow line out of figure 04.
    """
    for comp in CHANNELS:
        if comp not in base_psd:
            continue
        freqs, psd = base_psd[comp]
        parts = " ".join(f"{f0:g} Hz {line_excess(freqs, psd, f0):+.1f} dB" for f0 in lines)
        print(f"CHECK       {comp}: narrow-line excess over the local floor -- {parts}")


def check_dead_band(coh_levels, assert_it: bool) -> bool:
    """Run check (c): median coherence over the 2-10 s dead band against two reference bands.

    Args:
        coh_levels (dict): Coherence levels per pair from `cascade`.
        assert_it (bool): Whether the Bx-Ey and By-Ex drops are asserted.

    Returns:
        bool: False when an asserted pair drops by less than DEAD_BAND_DROP.
    """
    ok = True
    for pair, levels in coh_levels.items():
        t = levels[0][0]
        dead = float(np.nanmedian(band_from_levels(levels, *DEAD_BAND, t)))
        refs = [float(np.nanmedian(band_from_levels(levels, lo, hi, t))) for lo, hi in REFERENCE_BANDS]
        drop = min(r - dead for r in refs)
        tested = assert_it and pair in (("hx", "ey"), ("hy", "ex"))
        good = drop >= DEAD_BAND_DROP
        if tested:
            ok &= good
        tag = ("PASS" if good else "FAIL") if tested else "    "
        print(
            f"CHECK {tag}  {pair_label(pair)}: gamma2 {DEAD_BAND[0]:g}-{DEAD_BAND[1]:g} s "
            f"{dead:.3f} vs {REFERENCE_BANDS[0][0]:g}-{REFERENCE_BANDS[0][1]:g} s {refs[0]:.3f} "
            f"and {REFERENCE_BANDS[1][0]:g}-{REFERENCE_BANDS[1][1]:g} s {refs[1]:.3f} "
            f"(drop {drop:+.3f})"
        )
    return ok


# ---------------------------------------------------------------- driver


def main(argv=None) -> None:
    """Load the record, draw the four figures and run the checks.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.
    """
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    out_dir = Path(args.out_dir) if args.out_dir else survey.workspace / "qc"
    out_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    record = load_station(station_h5(survey, args.site), survey.name, args.site, CHANNELS)
    channels = [c for c in CHANNELS if c in record.arrays]
    pairs = list(LOCAL_PAIRS)
    if args.remote:
        remote = load_station(
            station_h5(survey, args.remote),
            survey.name,
            args.remote,
            ("hx", "hy"),
            grid=(record.t0, record.n, record.sample_rate),
            prefix="r_",
        )
        record = merge(record, remote)
        channels += ["r_hx", "r_hy"]
        pairs += list(REMOTE_PAIRS)
    t_load = time.time() - t_start
    logger.info(f"load: {t_load:.1f} s ({record.n} samples, {record.duration_s / 3600:.2f} h)")

    smooth_h = args.smooth if args.smooth else min(3.0, record.duration_s / 3600.0 / 12.0)
    step_s = args.step * 60.0
    title_site = args.site if not args.remote else f"{args.site} (remote {args.remote})"

    t0 = time.time()
    fig01 = out_dir / f"{args.site}_01_overview.png"
    stats = overview(record, fig01, survey.name)
    t_fig1 = time.time() - t0
    logger.info(f"figure 01: {t_fig1:.1f} s -> {fig01}")

    # before the cascade: it replaces record.arrays with each level's decimated
    # copy, so the full-rate samples are available for the re-read only now
    print()
    ok = check_calibration(record, survey, args.site, args.remote)
    ok &= check_second_means(record, stats)

    t0 = time.time()
    plan = levels_plan(
        record.sample_rate, record.duration_s, win_s=args.win * 60.0, step_s=step_s
    )
    print("\nlevel ladder:")
    print(plan.to_string(index=False))
    coh_levels, pow_levels, base_psd = cascade(
        record.arrays, record.gaps, record.sample_rate, plan, tuple(channels), tuple(pairs)
    )
    t_cascade = time.time() - t0
    logger.info(f"cascade ({len(plan)} levels, {len(channels)} channels, {len(pairs)} pairs): "
                f"{t_cascade:.1f} s")

    t0 = time.time()
    fig02 = out_dir / f"{args.site}_02_band_coherence.png"
    table = band_coherence_figure(record, coh_levels, fig02, survey.name, smooth_h, step_s)
    t_fig2 = time.time() - t0

    t0 = time.time()
    fig03 = out_dir / f"{args.site}_03_coherogram.png"
    coherogram_figure(record, coh_levels, fig03, survey.name, smooth_h / 3.0, step_s)
    t_fig3 = time.time() - t0

    t0 = time.time()
    fig04 = out_dir / f"{args.site}_04_spectrogram.png"
    spectrogram_figure(
        record, {c: pow_levels[c] for c in channels}, fig04, survey.name, smooth_h / 3.0, step_s
    )
    t_fig4 = time.time() - t0

    print(f"\n{survey.name} {title_site}: median band coherence over the record")
    header = f"{'pair':<10}" + "".join(f"{lab:>14}" for _, _, lab in BANDS_S)
    print(header)
    for name, row in table.items():
        print(f"{name:<10}" + "".join(f"{row[lab]:>14.3f}" for _, _, lab in BANDS_S))

    print()
    check_lines(base_psd)
    ok &= check_dead_band(coh_levels, args.assert_dead_band)
    print(f"CHECK {'PASS' if ok else 'FAIL'}  overall")

    print(
        f"\ntimings: load {t_load:.1f} s, figure 01 {t_fig1:.1f} s, cascade "
        f"{t_cascade:.1f} s, figure 02 {t_fig2:.1f} s, figure 03 {t_fig3:.1f} s, "
        f"figure 04 {t_fig4:.1f} s, total {time.time() - t_start:.1f} s"
    )
    for p in (fig01, fig02, fig03, fig04):
        print(p)


if __name__ == "__main__":
    main()
