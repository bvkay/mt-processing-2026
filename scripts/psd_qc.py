# -*- coding: utf-8 -*-
"""
Whole-record power spectral density per channel, in physical units, full band

The fifth per-site QC figure, after the four of `scripts/site_qc.py`. The
spectrogram of `site_qc.py` walks the factor-4 decimation ladder of
`crust.timefreq.cascade` and bins into log period and time, a time-resolved
view. This figure is a single whole-record spectrum at a frequency
resolution fine enough to show a 50 Hz line next to its neighbours;
log-period binning dilutes a narrow line to invisibility, as `check_lines()`
in `site_qc.py` explains. It uses plain `scipy.signal.welch` at a fixed
`nperseg = 2**16` on a ladder of four decimation-by-10 stages (native, /10,
/100, /1000). Each stage is assigned the decade its resolution suits and in
which its record length still gives several Welch segments:

    stage  fs        assigned band   df          segment length
    0      1000 Hz   2-500 Hz        0.0153 Hz   65.5 s
    1      100 Hz    0.2-2 Hz        0.00153 Hz  655 s
    2      10 Hz     0.02-0.2 Hz     1.53e-4 Hz  1.82 h
    3      1 Hz      0.002-0.02 Hz   1.53e-5 Hz  18.2 h

Each stage's Welch runs over its whole available spectrum (down to its own
df, up to its own Nyquist). The assigned band alone is drawn, and the extra
reach lets `check_boundary_continuity` compare two independently decimated
stages at the frequency where they hand off. This is the available test
without a reference spectrum, since no lemimt EDI covers these frequencies.

Gaps: `load_station` returns NaN outside the runs it found, with each
channel's DC offset already removed (`Record.arrays`), so zero is the
channel mean. Gap samples are zeroed in place rather than dropped, as
`crust.timefreq.cascade` does before its own decimation. One contiguous
array per channel keeps the FIR decimation simple, and a zeroed window
lowers that window's average power slightly, where a NaN or a straight
interpolation would add spurious spectral content.

Units: hx/hy are (nT)^2/Hz, ex/ey are (mV/km)^2/Hz. The magnetics carry the
scalar (frequency-independent) part of the MTH5 filter chain only, the LEMI
linear coefficient times `lemi423_b_scale`, without the coil's shape. The
electrics are fully calibrated (dipole length folded in). This is the
convention of `scripts/site_qc.py`.

`--before` overlays each local channel's PSD before any declared ingest
filter, in grey dashed, labelled "before filters (raw file)". The raw trace
is read from the site's B423 files: `crust.ingest.select_files` over the
archive's own time span, `crust.ingest.read_lemi423` with the read kwargs
of `ingest_site` (dipole lengths and `calibration_fn` from
`survey.site(site)`), then `crust.ingest._keep_channels`. It is calibrated
to the physical units of the archived trace by the scalar-gain rule of
`load_station` (`_raw_scalar_gain` below: the rule of `_scalar_gain` on a raw
channel's filter chain of LEMI linear coefficient, dipole length and
`lemi423_b_scale`, after `crust.ingest._apply_h_scale`, since the archived
channels carry it). The declared filters of `filters.yaml`
(`crust.noise.apply_filters`) are not applied. A site with no declared
filters is the correctness test: the two traces are the same samples
through the same gain and coincide, and the CHECK lines quantify how well.

A 45 h record is about 160M samples per channel, so `load_before` reads
every file in the archive's span in one `read_lemi423` call (matching
`load_station`, which concatenates every run) up to MAX_BEFORE_SAMPLES.
Beyond that it falls back to the longest contiguous group of B423 files
(`crust.ingest._group_contiguous`, the grouping ingest splits runs by) and
logs the drop. The fallback is a last resort: two disjoint spans of the same
natural field disagree by several dB from Welch sampling scatter alone, so
dropping even a short run this way can put the before/archived agreement
several dB out, while reading the whole span of a site with no declared
filters matches to 0.000 dB.

Usage:
    python scripts/psd_qc.py <survey.yaml> <site> [--remote NAME] [--before] [--out PNG]

@author: ben kay (ben@auscope.org.au)

:license: MIT

Check, printed as CHECK lines at the end of every invocation.
**It fails if** a channel's Welch PSD at a stage boundary (2, 0.2, 0.02 Hz),
read from the stage above (fewer decimations, finer df) and the stage below
(one more decimation, coarser df), disagree by more than that boundary's
entry in BOUNDARY_TOL_DB. Both stages estimate the same physical quantity,
the power at that frequency from the same underlying samples, by two
different pipelines (a different `scipy.signal.decimate` depth and a
different-width Welch segment). A gain error in the decimation, an aliasing
leak, wrong Welch scaling or a stage assigned the wrong band would show up as
a systematic offset on every channel at that boundary at once.

The tolerance is set per boundary because the number of Welch segments the
deeper stage averages drops tenfold per stage down the ladder, to a few dozen
at the 0.02 Hz boundary on a record of a day or two. A Welch estimate's
sampling scatter (chi-squared, about 2x the segment count degrees of freedom)
grows the same way, so two independent estimates of a non-stationary natural
field can disagree by a few dB by chance once one side is down to a few dozen
segments: typically under 1 dB at the 2 Hz boundary and several dB at 0.02 Hz,
one channel at a time and of mixed sign. A decimation or scaling bug would
move every channel together. BOUNDARY_TOL_DB is set from that spread with
headroom; a fixed offset across every channel at a boundary still fails it.
"""

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.ingest import _apply_h_scale, _group_contiguous, _keep_channels, read_lemi423, select_files
from crust.survey import Survey
from crust.timefreq import CHANNELS, COLOUR, UNIT, load_station, line_excess, merge, psd_ladder

DPI = 150
NPERSEG = 2**16
STAGE_FACTOR = 10
N_STAGES = 4
# the ladder itself is `crust.timefreq.psd_ladder`, which stops a stage short of
# `min_segments` whole Welch segments. 1 here, where the library default is 4:
# every stage runs on a whole record, and under the default any record
# shorter than 72.8 h (4 x 65536 samples at 1 Hz) would lose stage 3
# (0.002-0.02 Hz). welch needs one whole segment to run at the stated nperseg.
MIN_SEGMENTS = 1
# stage index -> (low Hz, high Hz) plotted; must run high-to-low and join
# seamlessly (each entry's low edge is the next entry's high edge)
BANDS_HZ = ((2.0, 500.0), (0.2, 2.0), (0.02, 0.2), (0.002, 0.02))
XLIM_HZ = (0.002, 500.0)
LINES_HZ = (50.0, 100.0, 150.0)
MAINS_HARMONICS = 9  # 50, 100, ... 450 Hz
CP_HARMONICS = 30
# per boundary (2, 0.2, 0.02 Hz): looser deeper down the ladder, where the
# stage below has far fewer Welch segments and more sampling scatter; the
# module docstring gives the measured spread this is sized from.
BOUNDARY_TOL_DB = (3.0, 5.0, 7.0)
PANELS = ("hx", "hy", "ex", "ey")
REMOTE_OF = {"hx": "r_hx", "hy": "r_hy"}
MAINS_COLOR = "0.35"
CP_COLOR = "firebrick"
REMOTE_COLOR = "0.6"
BEFORE_COLOR = "0.75"
BEFORE_LABEL = "before filters (raw file)"
# the y-range is set from data in this sub-band rather than the full XLIM,
# which excludes the anti-alias roll-off near 500 Hz and the sub-mHz edge;
# either can sit many decades below the natural-field floor
YLIM_PCTL_HZ = (0.003, 400.0)
YLIM_PCTL = (1.0, 99.0)
YLIM_PAD_DECADES = 1.0
# three bands whose archived/before-filter power ratio is printed with
# --before: mains, then the two a cathodic-protection stack acts on (see
# crust.noise's module docstring)
RATIO_BANDS_HZ = (
    (45.0, 55.0, "45-55 Hz (mains)"),
    (0.07, 0.2, "0.07-0.2 Hz"),
    (0.2, 2.0, "0.2-2 Hz (cp band)"),
)
# above this many estimated raw samples/channel, load_before falls back to
# the longest contiguous file group rather than the whole requested span;
# the module docstring explains why the whole span is read by default
MAX_BEFORE_SAMPLES = 220_000_000


def _hz_to_period(f):
    """Convert Hz to s (and s to Hz, being its own inverse) for the top secondary axis."""
    with np.errstate(divide="ignore"):
        return 1.0 / np.asarray(f, dtype="float64")


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line of psd_qc.py."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("site", help="site name (MTH5 in <workspace>/mth5/<site>.h5)")
    p.add_argument("--remote", metavar="NAME", help="remote site: overlays its hx/hy coils")
    p.add_argument(
        "--before", action="store_true",
        help="overlay each channel's PSD before any declared ingest filter (grey dashed)",
    )
    p.add_argument("--out", metavar="PNG", help="output PNG (default <workspace>/qc/<site>_05_psd.png)")
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


def cp_period_s(survey: Survey, site: str) -> float | None:
    """Return the declared cathodic-protection period of a site in seconds, or None.

    The period comes from the site's "cp" filter in `<survey>/filters.yaml`
    (default 12 s).
    """
    for spec in survey.site(site).filters or []:
        if "cp" in spec:
            return float((spec["cp"] or {}).get("period_s", 12.0))
    return None


# ---------------------------------------------------------------- checks


def check_boundary_continuity(stages, channels, bands_hz=BANDS_HZ, tol_db=BOUNDARY_TOL_DB) -> bool:
    """Compare adjacent stages at the frequency where their assigned bands meet.

    The module docstring describes the check and its tolerances.

    Args:
        stages (list): (fs, freqs, psd) per stage from `psd_ladder`.
        channels (list[str]): Channels to compare.
        bands_hz (tuple): Assigned band of each stage, high to low.
        tol_db (tuple | float): Tolerance in dB per boundary, or one value.

    Returns:
        bool: True when every channel is within tolerance at every boundary.
    """
    ok = True
    for i in range(len(stages) - 1):
        f_b = bands_hz[i][0]  # stage i's low edge == stage i+1's high edge
        tol = tol_db[i] if isinstance(tol_db, (tuple, list)) else tol_db
        fs_a, freqs_a, psd_a = stages[i]
        fs_b, freqs_b, psd_b = stages[i + 1]
        for c in channels:
            ka = int(np.argmin(np.abs(freqs_a - f_b)))
            kb = int(np.argmin(np.abs(freqs_b - f_b)))
            va, vb = psd_a[c][ka], psd_b[c][kb]
            with np.errstate(divide="ignore", invalid="ignore"):
                diff_db = float(10.0 * np.log10(va / vb))
            good = abs(diff_db) <= tol
            ok &= good
            print(
                f"CHECK {'PASS' if good else 'FAIL'}  {c} @ {f_b:g} Hz: {fs_a:g} Hz stage vs "
                f"{fs_b:g} Hz stage {diff_db:+.2f} dB (tol {tol:g})"
            )
    return ok


# ---------------------------------------------------------------- before-filters raw trace


def _raw_scalar_gain(filters_list, label: str) -> tuple[float, bool]:
    """Apply the rule of `crust.timefreq._scalar_gain` to a raw channel's filter chain.

    `read_lemi423` + `crust.ingest._apply_h_scale` builds the chain a
    channel gets at ingest ([dipole coefficient, linear coefficient] for an
    electric, [linear coefficient, coil response, `lemi423_b_scale`] for a
    magnetic) before it is written to an MTH5 channel group, so it has no
    `.metadata.component` for `_scalar_gain` to log with. This function takes
    the filter list and a label instead. The gain is the product of the
    CoefficientFilter gains, and the coil's shape filter is skipped.

    Args:
        filters_list (list): The channel's filters.
        label (str): Channel name for the debug log.

    Returns:
        tuple[float, bool]: The scalar gain and whether a shape filter was
        skipped.
    """
    gain, skipped = 1.0, False
    for f in filters_list:
        if type(f).__name__ == "CoefficientFilter":
            gain *= float(f.gain)
        else:
            skipped = True
            logger.debug(f"{label}: shape filter {f.name!r} not applied")
    return gain, skipped


def load_before(survey: Survey, site_name: str, channels: list[str], t0, t1):
    """Read the site's raw B423 files over [t0, t1) for the --before trace.

    The samples are calibrated like the archive, without the declared filters
    of `filters.yaml`; the module docstring describes the --before trace.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        channels (list[str]): Channels to return.
        t0: Start of the span (naive or tz-aware).
        t1: End of the span (naive or tz-aware).

    Returns:
        tuple: (sample rate, {channel: physical-unit array}, set of channels
        whose shape filter was skipped, a note on the files used).
    """
    site = survey.site(site_name)
    site_dir = survey.site_dirs()[site_name]
    # select_files localises a naive start/end to UTC itself and rejects a
    # tz-aware Timestamp; record.t0 is tz-aware (from run metadata), so the
    # zone is stripped here.
    t0 = pd.Timestamp(t0)
    t0 = t0.tz_convert("UTC").tz_localize(None) if t0.tzinfo is not None else t0
    t1 = pd.Timestamp(t1)
    t1 = t1.tz_convert("UTC").tz_localize(None) if t1.tzinfo is not None else t1
    files = select_files(site_dir, start=t0, end=t1)

    # `_group_contiguous` groups by epoch spacing for MTH5 run boundaries
    # (aurora needs long, gapless runs), which differs from whether data are
    # missing: an archive can hold two runs split by an epoch-label anomaly of
    # a few seconds while `load_station` finds no sample gap (reading every
    # file gives the sample count of the two-run archive and matches it to
    # 0.000 dB). Restricting to the longest group there would drop a real
    # run and, by comparing a shorter span's Welch estimate with
    # the archive's full-span one, add several dB of sampling scatter that
    # resembles a gain bug. The whole requested span is therefore read in one
    # `read_lemi423` call by default, comparable to `load_station`, which
    # concatenates every run. The longest contiguous group is read when the
    # estimated raw sample count is too large to hold as a second
    # full-resolution copy in memory.
    epochs = np.array([int(f.stem) for f in files], dtype="int64")
    file_len_s = int(np.median(np.diff(epochs))) if epochs.size > 1 else 5400
    n_est = len(files) * file_len_s * survey.sample_rate
    groups = _group_contiguous(files)
    if n_est > MAX_BEFORE_SAMPLES and len(groups) > 1:
        group = max(groups, key=len)
        read_files = group if len(group) > 1 else group[0]
        note = (
            f"{len(group)}/{len(files)} raw file(s) (longest of {len(groups)} contiguous "
            f"group(s); ~{n_est / 1e6:.0f}M samples/channel over the full span exceeds the "
            f"{MAX_BEFORE_SAMPLES / 1e6:.0f}M cap)"
        )
    else:
        read_files = files
        note = f"{len(files)} raw file(s), the whole archive span (~{n_est / 1e6:.0f}M samples/channel)"
        if len(groups) > 1:
            note += f" across {len(groups)} contiguous group(s)"
    logger.info(f"{site_name}: before-filters trace uses {note}")

    read_kwargs = dict(
        station_id=site_name,
        dipole_length_ex=site.dipole_length_ex,
        dipole_length_ey=site.dipole_length_ey,
    )
    if site.calibration_fn:
        cal = Path(site.calibration_fn)
        if not cal.is_absolute():
            cal = next(
                (c for c in (survey.config_dir / cal, survey.data_root / cal) if c.exists()),
                survey.data_root / cal,
            )
        read_kwargs["calibration_fn"] = cal

    t_read = time.time()
    run = read_lemi423(read_files, **read_kwargs)
    _keep_channels(run, site)
    _apply_h_scale(run, site)
    logger.info(f"{site_name}: before-filters read: {time.time() - t_read:.1f} s")

    fs = float(run.sample_rate)
    arrays, scalar_only = {}, set()
    for comp in channels:
        if comp not in run.dataset:
            continue
        gain, skipped = _raw_scalar_gain(getattr(run, comp).channel_response.filters_list, comp)
        if skipped:
            scalar_only.add(comp)
        arrays[comp] = run.dataset[comp].data.astype("float64") / gain
    return fs, arrays, scalar_only, note


def _stage_for_band(lo: float, hi: float, bands_hz=BANDS_HZ) -> int:
    """Return the stage whose assigned band (BANDS_HZ) contains [lo, hi].

    When no band contains it, the stage whose band centre is nearest in log
    frequency is returned.
    """
    for i, (blo, bhi) in enumerate(bands_hz):
        if lo >= blo and hi <= bhi:
            return i
    mid = (lo * hi) ** 0.5
    return min(range(len(bands_hz)), key=lambda i: abs((bands_hz[i][0] * bands_hz[i][1]) ** 0.5 - mid))


def print_before_diagnostics(stages, stages_before, channels, below_hz: float = 100.0) -> None:
    """Print two CHECK blocks per channel for --before.

    (1) The largest before-vs-archived |diff| below `below_hz`, over every
    plotted frequency. A site with no declared filters reads about 0 dB
    everywhere, the --before correctness test of the module docstring.
    (2) The archived/before-filter power ratio in RATIO_BANDS_HZ, which
    quantifies what a site's declared filters did. Both are diagnostics,
    like the `line_excess` CHECK lines; a non-zero ratio is expected wherever
    a filter is declared to act.

    Args:
        stages (list): Archived (fs, freqs, psd) per stage.
        stages_before (list): Before-filters (fs, freqs, psd) per stage.
        channels (list[str]): Local channels.
        below_hz (float): Upper frequency of the |diff| search.
    """
    print()
    for c in channels:
        worst_db, worst_f = 0.0, float("nan")
        for i, (lo, hi) in enumerate(BANDS_HZ):
            if lo >= below_hz:
                continue
            _, freqs_a, psd_a = stages[i]
            _, freqs_b, psd_b = stages_before[i]
            m = (freqs_a >= lo) & (freqs_a <= min(hi, below_hz))
            if not m.any():
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                diff = 10.0 * np.log10(psd_a[c][m] / psd_b[c][m])
            if not np.isfinite(diff).any():
                continue
            k = int(np.nanargmax(np.abs(diff)))
            if not np.isfinite(worst_f) or abs(diff[k]) >= abs(worst_db):
                worst_db, worst_f = float(diff[k]), float(freqs_a[m][k])
        print(
            f"CHECK       {c}: before vs archived, largest |diff| below {below_hz:g} Hz = "
            f"{worst_db:+.2f} dB @ {worst_f:g} Hz"
        )

    print()
    for c in channels:
        parts = []
        for lo, hi, label in RATIO_BANDS_HZ:
            i = _stage_for_band(lo, hi)
            _, freqs_a, psd_a = stages[i]
            _, freqs_b, psd_b = stages_before[i]
            ma = (freqs_a >= lo) & (freqs_a <= hi)
            mb = (freqs_b >= lo) & (freqs_b <= hi)
            pa = float(np.nanmean(psd_a[c][ma])) if ma.any() else float("nan")
            pb = float(np.nanmean(psd_b[c][mb])) if mb.any() else float("nan")
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio_db = 10.0 * np.log10(pa / pb)
            parts.append(f"{label} {ratio_db:+.2f} dB")
        print(f"CHECK       {c}: archived/before-filters power ratio -- " + ", ".join(parts))


# ---------------------------------------------------------------- figure


def psd_figure(
    record,
    stages,
    channels,
    remote_channels,
    cp_period,
    survey_name,
    remote_name,
    out: Path,
    stages_before=None,
    dpi=DPI,
    figsize=(13, 10),
):
    """Draw the PSD figure: one log-log panel per local channel (2x2: hx, hy, ex, ey), 0.002-500 Hz.

    The local channel is drawn in its `crust.timefreq.COLOUR`, the remote's
    matching coil (r_hx under hx, r_hy under hy) in grey and, with
    `stages_before`, the channel's PSD before any ingest filter in grey
    dashed under the archived line. Faint dotted lines mark 50 Hz and its
    harmonics; faint dashed lines mark the declared cathodic-protection comb,
    if any.

    Each panel's y-limits are the 1st-99th percentile of everything plotted
    in it (archived, remote and before-filters) within YLIM_PCTL_HZ, padded a
    decade either side. The full XLIM_HZ range is avoided because the
    anti-alias roll-off near 500 Hz would pull the bottom of the axis many
    decades below the data.

    Args:
        record (Record): The site's record (station name, scalar_only).
        stages (list): Archived (fs, freqs, psd) per stage.
        channels (list[str]): Local channels.
        remote_channels (list[str]): Remote channels present ("r_hx", "r_hy").
        cp_period (float | None): Declared cathodic-protection period in s.
        survey_name (str): Survey name for the title.
        remote_name (str | None): Remote site name for the title.
        out (Path): Output figure.
        stages_before (list | None): Before-filters stages, if requested.
        dpi (int): Figure resolution.
        figsize (tuple): Figure size in inches.
    """
    panels = [c for c in PANELS if c in channels]
    ncols = 2
    nrows = int(np.ceil(len(panels) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, layout="constrained")
    axes = np.atleast_2d(axes)

    for i, comp in enumerate(panels):
        ax = axes[i // ncols, i % ncols]
        rcomp = REMOTE_OF.get(comp)
        has_remote = rcomp is not None and rcomp in remote_channels
        has_before = stages_before is not None and comp in stages_before[0][2]
        y_vals = []
        for level, (fs, freqs, psd) in enumerate(stages):
            lo, hi = BANDS_HZ[level]
            m = (freqs >= lo) & (freqs <= hi)
            if not m.any():
                continue
            pm = m & (freqs >= YLIM_PCTL_HZ[0]) & (freqs <= YLIM_PCTL_HZ[1])
            if has_before:
                fs_b, freqs_b, psd_b = stages_before[level]
                mb = (freqs_b >= lo) & (freqs_b <= hi)
                if mb.any():
                    ax.plot(
                        freqs_b[mb], psd_b[comp][mb], color=BEFORE_COLOR, lw=0.8, ls="--",
                        zorder=1, label=BEFORE_LABEL if level == 0 else None,
                    )
                    pmb = mb & (freqs_b >= YLIM_PCTL_HZ[0]) & (freqs_b <= YLIM_PCTL_HZ[1])
                    if pmb.any():
                        y_vals.append(psd_b[comp][pmb])
            ax.plot(
                freqs[m], psd[comp][m], color=COLOUR.get(comp, "C0"), lw=1.1, zorder=3,
                label=comp if level == 0 else None,
            )
            if pm.any():
                y_vals.append(psd[comp][pm])
            if has_remote:
                ax.plot(
                    freqs[m], psd[rcomp][m], color=REMOTE_COLOR, lw=0.9, zorder=2,
                    label=f"remote {rcomp}" if level == 0 else None,
                )
                if pm.any():
                    y_vals.append(psd[rcomp][pm])
        for k in range(1, MAINS_HARMONICS + 1):
            ax.axvline(
                k * 50.0, color=MAINS_COLOR, ls=":", lw=0.6, alpha=0.6,
                label="50 Hz + harmonics" if k == 1 else None,
            )
        if cp_period:
            for k in range(1, CP_HARMONICS + 1):
                fk = k / cp_period
                if fk > XLIM_HZ[1]:
                    break
                ax.axvline(
                    fk, color=CP_COLOR, ls="--", lw=0.5, alpha=0.45,
                    label=f"cp comb (1/{cp_period:g} s)" if k == 1 else None,
                )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(*XLIM_HZ)
        if y_vals:
            finite = np.concatenate(y_vals)
            finite = finite[np.isfinite(finite) & (finite > 0)]
            if finite.size:
                p_lo, p_hi = np.percentile(finite, YLIM_PCTL)
                if p_lo > 0:
                    pad = 10.0**YLIM_PAD_DECADES
                    ax.set_ylim(p_lo / pad, p_hi * pad)
        unit = UNIT[comp]
        tag = ", scalar gain" if comp in record.scalar_only else ""
        ax.set_ylabel(f"{comp} PSD\n(({unit})$^2$/Hz{tag})", fontsize=9)
        ax.set_xlabel("frequency (Hz)")
        ax.grid(alpha=0.25, which="both")
        ax.legend(fontsize=7.5, loc="upper right", framealpha=0.8)
        sec = ax.secondary_xaxis("top", functions=(_hz_to_period, _hz_to_period))
        sec.set_xlabel("period (s)", fontsize=8)

    for j in range(len(panels), nrows * ncols):
        axes[j // ncols, j % ncols].set_visible(False)

    note = (
        "magnetics: scalar gain only (LEMI linear coefficient x lemi423_b_scale); "
        "the coil response is a shape and is not deconvolved"
        + (f"; dashed lines mark the declared cp comb (1/{cp_period:g} s)" if cp_period else "")
        + (f"; grey dashed: {BEFORE_LABEL}" if stages_before is not None else "")
    )
    remote_tag = f", remote {remote_name} hx/hy in grey" if remote_name else ""
    fig.suptitle(
        f"{survey_name} {record.station}: whole-record PSD per channel{remote_tag}\n{note}",
        fontsize=11,
    )
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------- driver


def main(argv=None) -> None:
    """Compute the PSD ladder, draw the figure and print the checks.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Raises:
        ValueError: When the before-filters sample rate differs from the
            archive's.
    """
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    out = Path(args.out) if args.out else survey.workspace / "qc" / f"{args.site}_05_psd.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    record = load_station(station_h5(survey, args.site), survey.name, args.site, CHANNELS)
    channels = [c for c in CHANNELS if c in record.arrays and c != "hz"]
    remote_channels: list[str] = []
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
        remote_channels = [c for c in ("r_hx", "r_hy") if c in record.arrays]
    all_channels = channels + remote_channels
    t_load = time.time() - t_start
    logger.info(f"load: {t_load:.1f} s ({record.n} samples, {record.duration_s / 3600:.2f} h)")

    t0 = time.time()
    stages = psd_ladder(
        record.arrays, record.gaps, record.sample_rate, all_channels,
        nperseg=NPERSEG, factor=STAGE_FACTOR, n_stages=N_STAGES, min_segments=MIN_SEGMENTS,
    )
    t_cascade = time.time() - t0
    logger.info(f"cascade ({len(stages)} stages, {len(all_channels)} channels): {t_cascade:.1f} s")

    stages_before = None
    t_before = 0.0
    if args.before:
        # record.arrays is already consumed down to its final (1 Hz) stage by
        # psd_ladder above, so the raw before-filters read below adds at
        # most one full-resolution channel set to the peak footprint, not two
        t0 = time.time()
        t1_before = record.t0 + pd.Timedelta(seconds=record.duration_s)
        fs_before, before_arrays, before_scalar_only, before_note = load_before(
            survey, args.site, channels, record.t0, t1_before
        )
        if abs(fs_before - record.sample_rate) > 1e-6:
            raise ValueError(f"before-filters sample rate {fs_before:g} != archive {record.sample_rate:g}")
        stages_before = psd_ladder(
            before_arrays, [], fs_before, list(before_arrays),
            nperseg=NPERSEG, factor=STAGE_FACTOR, n_stages=N_STAGES, min_segments=MIN_SEGMENTS,
        )
        t_before = time.time() - t0
        logger.info(f"before-filters ({before_note}): {t_before:.1f} s")

    cp_period = cp_period_s(survey, args.site)

    t0 = time.time()
    psd_figure(
        record, stages, channels, remote_channels, cp_period, survey.name, args.remote, out,
        stages_before=stages_before,
    )
    t_fig = time.time() - t0
    logger.info(f"figure: {t_fig:.1f} s -> {out}")

    print()
    fs0, freqs0, psd0 = stages[0]
    for c in all_channels:
        parts = " ".join(f"{f0:g} Hz {line_excess(freqs0, psd0[c], f0):+.1f} dB" for f0 in LINES_HZ)
        print(f"CHECK       {c}: narrow-line excess over the local floor -- {parts}")

    print()
    ok = check_boundary_continuity(stages, all_channels)
    print(f"CHECK {'PASS' if ok else 'FAIL'}  overall")

    if stages_before is not None:
        print_before_diagnostics(stages, stages_before, channels)

    print(
        f"\ntimings: load {t_load:.1f} s, cascade {t_cascade:.1f} s, "
        + (f"before-filters {t_before:.1f} s, " if args.before else "")
        + f"figure {t_fig:.1f} s, total {time.time() - t_start:.1f} s"
    )
    print(out)


if __name__ == "__main__":
    main()
