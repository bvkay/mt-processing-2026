# -*- coding: utf-8 -*-
"""
Hourly noise profile of a line of sites and a test of whether its episodes are simultaneous

Some broadband noise comes in episodes of minutes: the coils carry broadband
bursts while both electrics swing far off their running level, as one-sided
steps of tens of seconds or as anticorrelated excursions. When the same
episodes turn up at several sites of a line, the question is whether they
come from one regional source (simultaneous at sites recording at the same
time) or from something local at each site. The script profiles every site
of a line an hour at a time and then correlates the profiles of every pair
of sites whose records overlap.

Each archive is read directly with h5py, read-only, one window at a time
(the layout and run attributes as in `scripts/line_scan.py`). For every
hour a window of `--minutes` is read with a margin of `PAD_S` on each side
where the run allows, the site's declared filters are applied in memory
(`crust.noise.apply_filters_arrays`) and, on the window itself, in raw
counts: `step_ex`, `step_ey` are the fractions of the 10 Hz samples (every
tenth of a second, taken without an anti-alias filter) farther than 6 MAD
(scaled by 1.4826, from the median absolute residual) from a 60 s running
median, and `shift_ex`, `shift_ey` the same fractions about a 600 s running
median. A running median follows a step that fills more than half of its
length, so the 60 s one sees steps shorter than about 30 s and only the
edges of longer ones, while the 600 s one counts steps of up to about 5 min
that fill less than half of any 10 min. `p2p_ex`, `p2p_ey` are the 1 to 99
percentile range of the 10 Hz samples; `burst_hx`, `burst_hy` the
fractions of samples beyond 6 scaled MAD after a 4th-order zero-phase 5 to
200 Hz Butterworth band-pass; and `coh_*` the mean magnitude-squared
coherence (8 s Hann segments, half overlap) of ex-hy and ey-hx over 0.5 to
5 Hz (`_lo`) and 5 to 40 Hz (`_hi`). Windows start on the UTC clock hour by
default (`--align clock`), so concurrent sites are measured over the same
minutes; `--align run` starts them at the run start plus whole hours
instead. A window must lie wholly inside one run; its start is kept in
whole nanoseconds and reported to the second.

The simultaneity test takes every pair of sites with at least MIN_OVERLAP_H
common hours and gives the Pearson correlation of their hourly `step_ey`,
`shift_ey` and `burst_hx`, and of their 5-minute step envelopes (the
fraction of ey samples flagged as a step in each whole 5-minute UTC cell
both windows cover). A pair whose raw ex samples are identical in every
common window (a CRC-32 of each window's raw counts) is marked `same_raw`:
the same recording archived under two names, whose correlation says
nothing about a common source even when the declared filters differ. Local
time is the survey's `timezone:` when it declares one, UTC otherwise; the
script prints which.

Usage:
    python scripts/line_noise_profile.py <survey.yaml> [SITE ...]
                                         [--hours-step 1] [--minutes 20]
                                         [--align clock|run]

    SITE may be a full name or a prefix (a prefix selects every site whose
    name starts with it); no SITE means every site with an archive.

    Writes, under `<workspace>/qc/`, where `<tag>` is the SITE given, the
    SITEs given joined by "_" when there are several, or "all" when none is:

        line_noise_<tag>.csv            one row per site and hour (CSV_COLUMNS)
        line_noise_<tag>_env5min.csv    site, cell_start_utc, env_ey
        line_noise_<tag>_pairs.csv      the simultaneity table
        line_noise_<tag>_heatmap.png    site x hour of record for step_ey,
                                        burst_hx, coh_eyhx_hi and shift_ey
        line_noise_<tag>_diurnal.png    the same four, median over sites by
                                        local hour
        line_noise_<tag>_concurrent.png hourly step_ey against UTC, one panel
                                        per group of overlapping sites

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "4")

import argparse
import itertools
import sys
import time
import zlib
from pathlib import Path
from zoneinfo import ZoneInfo

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from scipy import ndimage, signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.noise import apply_filters_arrays
from crust.survey import Survey

DPI = 150
WORKERS = 4  # threads per filter
CHANNELS = ("ex", "ey", "hx", "hy")
STEP_FS = 10.0  # rate of the electric step series, Hz
MEDIAN_S = 60.0  # running-median length for step_*, s
SHIFT_MEDIAN_S = 600.0  # running-median length for shift_*, s
K_MAD = 6.0  # outlier threshold in scaled MAD
MAD_SCALE = 1.4826  # MAD to standard deviation for Gaussian noise
BURST_BAND = (5.0, 200.0)  # band-pass for the coil bursts, Hz
BURST_ORDER = 4
COH_SEG_S = 8.0  # coherence segment length, s
COH_LO = (0.5, 5.0)
COH_HI = (5.0, 40.0)
PAD_S = SHIFT_MEDIAN_S / 2.0  # margin read on each side of a window for filter and median edges
ENV_S = 300.0  # envelope cell, s
MIN_OVERLAP_H = 6  # smallest overlap for a pair to be correlated
CSV_COLUMNS = (
    "site", "run", "hour_start_utc", "hour_local", "step_ex", "step_ey", "shift_ex", "shift_ey",
    "p2p_ex", "p2p_ey", "burst_hx", "burst_hy", "coh_exhy_lo", "coh_exhy_hi", "coh_eyhx_lo", "coh_eyhx_hi",
)
METRICS = CSV_COLUMNS[4:]
MAP_METRICS = ("step_ey", "burst_hx", "coh_eyhx_hi", "shift_ey")


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line of line_noise_profile.py."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("sites", nargs="*", help="site names or name prefixes; default: every site with an archive")
    p.add_argument("--hours-step", type=float, default=1.0, help="hours between windows (default 1)")
    p.add_argument("--minutes", type=float, default=20.0, help="window length in minutes (default 20)")
    p.add_argument(
        "--align", choices=("clock", "run"), default="clock",
        help="start windows on the UTC clock hour (default) or at the run start plus whole hours",
    )
    return p.parse_args(argv)


def select_sites(survey: Survey, names: list[str]) -> tuple[list[str], str]:
    """Resolve names and prefixes to the sites with an archive.

    The output tag keeps runs over different selections apart: a single
    name or prefix is the tag itself, and several are joined by "_", so an
    explicit list of sites never takes the tag of a whole line.

    Args:
        survey (Survey): The survey (only its `workspace` is read).
        names (list[str]): Site names or prefixes; empty for every site.

    Returns:
        tuple[list[str], str]: The sites in name order and the output tag
        ("all" when `names` is empty).
    """
    mth5_dir = survey.workspace / "mth5"
    available = sorted(p.stem for p in mth5_dir.glob("*.h5")) if mth5_dir.is_dir() else []
    if not names:
        return available, "all"
    chosen = sorted({s for s in available for n in names if s == n or s.startswith(n)})
    tag = "_".join(dict.fromkeys(names))
    return chosen, tag


# ---------------------------------------------------------------- metrics


def _frac_beyond(x: np.ndarray) -> float:
    """Fraction of `x` farther than K_MAD scaled MADs from zero, the MAD taken about zero."""
    mad = float(np.median(np.abs(x)))
    if not np.isfinite(mad) or mad == 0.0:
        return float("nan")
    return float(np.mean(np.abs(x) > K_MAD * MAD_SCALE * mad))


def _flags_about_running_median(y: np.ndarray, width: int, j0: int, j1: int) -> tuple[np.ndarray, float]:
    """Flag the samples `j0:j1` of `y` farther than K_MAD scaled MADs from a running median.

    The median runs over the whole of `y` (its ends padded with the end
    values), and the MAD is taken from the residuals of `j0:j1` alone.

    Args:
        y (np.ndarray): The series, with any margin.
        width (int): Running-median length in samples (odd).
        j0 (int): First sample of the window in `y`.
        j1 (int): One past the last sample of the window.

    Returns:
        tuple[np.ndarray, float]: The flags of `j0:j1` and their mean (NaN
        when the MAD is zero or not finite).
    """
    res = (y - ndimage.median_filter(y, size=width, mode="nearest"))[j0:j1]
    mad = float(np.median(np.abs(res)))
    if not np.isfinite(mad) or mad == 0.0:
        return np.zeros(res.size, bool), float("nan")
    flags = np.abs(res) > K_MAD * MAD_SCALE * mad
    return flags, float(np.mean(flags))


def window_metrics(
    arrays: dict[str, np.ndarray], fs: float, i0: int, i1: int, t_window: pd.Timestamp,
) -> tuple[dict, list[tuple[pd.Timestamp, float]]]:
    """Compute one window's metrics from filtered arrays that may carry a margin.

    The running medians and the filters see the margin; every metric is
    taken over samples `i0:i1` only. The times of the 10 Hz samples are
    offsets from `t_window` rounded to whole nanoseconds, so a sample on a
    cell boundary is never put in the cell before it.

    Args:
        arrays (dict): Filtered ex, ey, hx, hy in counts, with margins.
        fs (float): Sample rate in Hz.
        i0 (int): First sample of the window in `arrays`.
        i1 (int): One past the last sample of the window.
        t_window (pd.Timestamp): UTC start of the window, the time of
            sample `i0` to within half a sample.

    Returns:
        tuple: The metrics (METRICS keys) and the ey step envelope as
        (cell start, fraction flagged) for every whole ENV_S UTC cell in
        the window.
    """
    out: dict = {}
    dec = max(1, int(round(fs / STEP_FS)))
    width = int(round(MEDIAN_S * fs / dec)) | 1  # odd
    width_shift = int(round(SHIFT_MEDIAN_S * fs / dec)) | 1
    j0, j1 = -(-i0 // dec), -(-i1 // dec)  # decimated samples inside the window
    env: list[tuple[pd.Timestamp, float]] = []
    for c in ("ex", "ey"):
        y = arrays[c][::dec]
        flags, out[f"step_{c}"] = _flags_about_running_median(y, width, j0, j1)
        _, out[f"shift_{c}"] = _flags_about_running_median(y, width_shift, j0, j1)
        yw = y[j0:j1]
        out[f"p2p_{c}"] = float(np.percentile(yw, 99) - np.percentile(yw, 1))
        if c == "ey":
            off_ns = np.rint((np.arange(j0, j1) * dec - i0) / fs * 1e9).astype("int64")
            t_dec = pd.to_datetime(t_window.value + off_ns, unit="ns", utc=True)
            cells = t_dec.floor(f"{int(ENV_S)}s")
            per_cell = int(round(ENV_S * fs / dec))
            s = pd.Series(flags.astype(float), index=cells)
            g = s.groupby(level=0).agg(["mean", "size"])
            env = [(t, float(m)) for t, (m, n) in g.iterrows() if n >= per_cell]
    sos = signal.butter(BURST_ORDER, BURST_BAND, btype="band", fs=fs, output="sos")
    for c in ("hx", "hy"):
        out[f"burst_{c}"] = _frac_beyond(signal.sosfiltfilt(sos, arrays[c])[i0:i1])
    nseg = int(round(COH_SEG_S * fs))
    for e, h in (("ex", "hy"), ("ey", "hx")):
        f, coh = signal.coherence(arrays[e][i0:i1], arrays[h][i0:i1], fs=fs, nperseg=nseg)
        for tag, (lo, hi) in (("lo", COH_LO), ("hi", COH_HI)):
            out[f"coh_{e}{h}_{tag}"] = float(np.mean(coh[(f >= lo) & (f <= hi)]))
    return out, env


def _run_ids(station: h5py.Group) -> list[str]:
    """Return the data-bearing run groups (named sr*) of a station, earliest first."""
    ids = [k for k in station.keys() if k.startswith("sr") and isinstance(station[k], h5py.Group)]
    ids.sort(key=lambda k: str(station[k].attrs["time_period.start"]))
    return ids


def window_starts(t0: pd.Timestamp, t_end: pd.Timestamp, hours_step: float, minutes: float, align: str) -> list:
    """Window starts inside one run, in whole nanoseconds.

    Args:
        t0 (pd.Timestamp): Run start (UTC).
        t_end (pd.Timestamp): Run end (UTC), one sample past the last.
        hours_step (float): Hours between windows.
        minutes (float): Window length.
        align (str): "clock" for UTC clock hours, "run" for the run start
            plus whole steps.

    Returns:
        list[pd.Timestamp]: Starts of the windows that fit in the run.
    """
    first = t0.ceil("h") if align == "clock" else t0
    step = pd.Timedelta(hours=hours_step)
    length = pd.Timedelta(minutes=minutes)
    starts = []
    t = first
    while t + length <= t_end:
        starts.append(t)
        t += step
    return starts


def profile_site(
    h5_path: Path, survey_name: str, site: str, filters: list[dict] | None,
    hours_step: float, minutes: float, align: str, tz: ZoneInfo,
) -> tuple[list[dict], list[dict]]:
    """Profile one site's archive, one window at a time.

    A window begins at the sample nearest to its nominal start. The
    nominal start, in whole nanoseconds and never a float of seconds,
    dates the window and its envelope cells, and `hour_start_utc` is that
    start rounded to the second.

    Args:
        h5_path (Path): The site's MTH5, opened read-only.
        survey_name (str): Survey id in the MTH5.
        site (str): Station name.
        filters (list of dict or None): The site's declared filters.
        hours_step (float): Hours between windows.
        minutes (float): Window length.
        align (str): Window alignment ("clock" or "run").
        tz (ZoneInfo): Local time zone for `hour_local`.

    Returns:
        tuple[list[dict], list[dict]]: One row per window (CSV_COLUMNS and
        raw_crc, the CRC-32 of the window's raw ex counts) and one row per
        envelope cell (site, cell_start_utc, env_ey).

    Raises:
        KeyError: When the archive has no group for the station.
    """
    rows: list[dict] = []
    env_rows: list[dict] = []
    with h5py.File(h5_path, "r") as f:
        station_path = f"Experiment/Surveys/{survey_name}/Stations/{site}"
        if station_path not in f:
            raise KeyError(f"no {station_path!r} group in {h5_path}")
        station = f[station_path]
        for run_id in _run_ids(station):
            run = station[run_id]
            if not all(c in run and isinstance(run[c], h5py.Dataset) for c in CHANNELS):
                logger.warning(f"{site} {run_id}: not every channel of {CHANNELS} present, skipped")
                continue
            fs = float(run.attrs["sample_rate"])
            t0 = pd.Timestamp(str(run.attrs["time_period.start"]))
            n = min(run[c].shape[0] for c in CHANNELS)
            t_end = t0 + pd.Timedelta(int(round(n * 1e9 / fs)), unit="ns")
            pad = int(round(PAD_S * fs))
            for ts in window_starts(t0, t_end, hours_step, minutes, align):
                w0 = int(round((ts - t0).value * fs / 1e9))
                w1 = min(w0 + int(round(minutes * 60.0 * fs)), n)
                r0, r1 = max(0, w0 - pad), min(n, w1 + pad)
                raw = {c: run[c][r0:r1].astype("float64") for c in CHANNELS}
                crc = zlib.crc32(np.ascontiguousarray(raw["ex"][w0 - r0 : w1 - r0]).tobytes())
                filt, _ = apply_filters_arrays(raw, fs, filters or [], tag=f"{site} {run_id}", workers=WORKERS)
                metrics, env = window_metrics(filt, fs, w0 - r0, w1 - r0, ts)
                mid = ts + pd.Timedelta(minutes=minutes / 2.0)
                rows.append(dict(
                    site=site, run=run_id, hour_start_utc=ts.round("s").isoformat(),
                    hour_local=int(mid.tz_convert(tz).hour), **metrics, raw_crc=crc,
                ))
                env_rows += [dict(site=site, cell_start_utc=t.isoformat(), env_ey=v) for t, v in env]
    return rows, env_rows


# ---------------------------------------------------------------- simultaneity


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation of finite pairs; NaN with fewer than 3 or a constant series."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def pair_table(df: pd.DataFrame, env: pd.DataFrame, min_overlap_h: int = MIN_OVERLAP_H) -> pd.DataFrame:
    """Correlate every pair of sites over their common hours.

    Hours are matched on `hour_start_utc` rounded to the hour, which is
    exact for clock-aligned windows.

    Args:
        df (pd.DataFrame): The hourly profile (CSV_COLUMNS and raw_crc).
        env (pd.DataFrame): The 5-minute envelopes (site, cell_start_utc, env_ey).
        min_overlap_h (int): Fewest common hours for a pair to be listed.

    Returns:
        pd.DataFrame: site_a, site_b, overlap_h, r_step_ey, r_shift_ey,
        r_burst_hx, env_cells, r_env_ey, same_raw.
    """
    d = df.assign(hour=pd.to_datetime(df["hour_start_utc"], format="ISO8601").dt.round("h"))
    e = env.assign(cell=pd.to_datetime(env["cell_start_utc"], format="ISO8601"))
    rows = []
    for a, b in itertools.combinations(sorted(d["site"].unique()), 2):
        m = d[d["site"] == a].merge(d[d["site"] == b], on="hour", suffixes=("_a", "_b"))
        if len(m) < min_overlap_h:
            continue
        me = e[e["site"] == a].merge(e[e["site"] == b], on="cell", suffixes=("_a", "_b"))
        same = bool((m["raw_crc_a"] == m["raw_crc_b"]).all())
        rows.append(dict(
            site_a=a, site_b=b, overlap_h=len(m),
            r_step_ey=_pearson(m["step_ey_a"].to_numpy(), m["step_ey_b"].to_numpy()),
            r_shift_ey=_pearson(m["shift_ey_a"].to_numpy(), m["shift_ey_b"].to_numpy()),
            r_burst_hx=_pearson(m["burst_hx_a"].to_numpy(), m["burst_hx_b"].to_numpy()),
            env_cells=len(me),
            r_env_ey=_pearson(me["env_ey_a"].to_numpy(), me["env_ey_b"].to_numpy()),
            same_raw=same,
        ))
    return pd.DataFrame(rows, columns=[
        "site_a", "site_b", "overlap_h", "r_step_ey", "r_shift_ey", "r_burst_hx", "env_cells", "r_env_ey",
        "same_raw",
    ])


def overlap_groups(pairs: pd.DataFrame, sites: list[str]) -> list[list[str]]:
    """Group sites joined by a listed pair (connected components), each group in name order."""
    parent = {s: s for s in sites}

    def root(s):
        while parent[s] != s:
            s = parent[s]
        return s

    for a, b in zip(pairs["site_a"], pairs["site_b"]):
        parent[root(a)] = root(b)
    groups: dict[str, list[str]] = {}
    for s in sites:
        groups.setdefault(root(s), []).append(s)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


# ---------------------------------------------------------------- figures


def heatmap_figure(df: pd.DataFrame, sites: list[str], title: str, out: Path) -> None:
    """Plot site x hour of record for MAP_METRICS, sites in name order.

    Hour of record is the whole number of hours since the site's first
    window.

    Args:
        df (pd.DataFrame): The hourly profile.
        sites (list[str]): Sites in name order.
        title (str): Figure title.
        out (Path): Output figure.
    """
    t = pd.to_datetime(df["hour_start_utc"], format="ISO8601")
    hor = ((t - t.groupby(df["site"]).transform("min")).dt.total_seconds() // 3600).astype(int)
    n_h = int(hor.max()) + 1
    fig, axes = plt.subplots(len(MAP_METRICS), 1, figsize=(12.0, 1.2 + 0.28 * len(sites) * len(MAP_METRICS)),
                             sharex=True, layout="constrained")
    for ax, k in zip(np.atleast_1d(axes), MAP_METRICS):
        grid = np.full((len(sites), n_h), np.nan)
        for i, s in enumerate(sites):
            sel = df["site"] == s
            grid[i, hor[sel].to_numpy()] = df.loc[sel, k].to_numpy()
        vmax = np.nanpercentile(grid, 98) if np.isfinite(grid).any() else 1.0
        im = ax.pcolormesh(np.arange(n_h + 1), np.arange(len(sites) + 1), np.ma.masked_invalid(grid),
                           cmap="viridis", vmin=0.0, vmax=1.0 if k.startswith("coh") else vmax, shading="flat")
        ax.set_yticks(np.arange(len(sites)) + 0.5, sites, fontsize=8)
        ax.invert_yaxis()
        ax.set_ylabel(k)
        fig.colorbar(im, ax=ax, pad=0.01)
    np.atleast_1d(axes)[-1].set_xlabel("hour of record (from the site's first window)")
    fig.suptitle(title)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def diurnal_table(df: pd.DataFrame) -> pd.DataFrame:
    """Median over sites of each site's median per local hour, for MAP_METRICS.

    Args:
        df (pd.DataFrame): The hourly profile.

    Returns:
        pd.DataFrame: Indexed by hour_local, the medians and n_sites.
    """
    per_site = df.groupby(["site", "hour_local"])[list(MAP_METRICS)].median()
    tab = per_site.groupby(level="hour_local").median()
    tab["n_sites"] = per_site.groupby(level="hour_local").size()
    return tab.reindex(range(24))


def diurnal_figure(df: pd.DataFrame, tab: pd.DataFrame, tz_label: str, title: str, out: Path) -> None:
    """Plot each site's median per local hour (thin) and the median over sites (thick).

    Args:
        df (pd.DataFrame): The hourly profile.
        tab (pd.DataFrame): The diurnal table.
        tz_label (str): Name of the local time used.
        title (str): Figure title.
        out (Path): Output figure.
    """
    per_site = df.groupby(["site", "hour_local"])[list(MAP_METRICS)].median()
    fig, axes = plt.subplots(len(MAP_METRICS), 1, figsize=(9.0, 1.2 + 2.1 * len(MAP_METRICS)), sharex=True,
                             layout="constrained")
    for ax, k in zip(axes, MAP_METRICS):
        for s, g in per_site.groupby(level="site"):
            h = g.index.get_level_values("hour_local")
            ax.plot(h, g[k], color="0.75", lw=0.8)
        ax.plot(tab.index, tab[k], color="C3", lw=2.2, marker="o", ms=3, label="median over sites")
        ax.set_ylabel(k)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, loc="upper right")
    axes[-1].set_xlabel(f"local hour ({tz_label}), of the window midpoint")
    axes[-1].set_xticks(range(0, 24, 2))
    fig.suptitle(title)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def concurrent_figure(df: pd.DataFrame, groups: list[list[str]], title: str, out: Path) -> None:
    """Plot hourly step_ey against UTC, one panel per group of overlapping sites.

    Args:
        df (pd.DataFrame): The hourly profile.
        groups (list of list of str): Groups of sites that overlap.
        title (str): Figure title.
        out (Path): Output figure.
    """
    groups = [g for g in groups if len(g) > 1] or groups
    fig, axes = plt.subplots(len(groups), 1, figsize=(12.0, 2.8 * len(groups)), layout="constrained")
    for ax, g in zip(np.atleast_1d(axes), groups):
        for s in g:
            sel = df["site"] == s
            ax.plot(pd.to_datetime(df.loc[sel, "hour_start_utc"], format="ISO8601"), df.loc[sel, "step_ey"],
                    lw=1.0, marker=".", ms=3, label=s)
        ax.set_ylabel("step_ey")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, ncol=min(len(g), 8), loc="upper right")
    np.atleast_1d(axes)[-1].set_xlabel("window start (UTC)")
    fig.suptitle(title)
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


# ---------------------------------------------------------------- driver


def _p90(x: pd.Series) -> float:
    """90th percentile of a series, for the per-site summary."""
    return float(x.quantile(0.9))


def main(argv=None) -> None:
    """Profile the sites, write the tables and figures and print the summaries.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.
    """
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    declared_tz = survey.config.get("timezone")
    tz_label = str(declared_tz) if declared_tz else "UTC"
    tz = ZoneInfo(tz_label)
    qc_dir = survey.workspace / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    sites, tag = select_sites(survey, list(args.sites))
    if not sites:
        logger.warning("no site with an archive matches the names given")
        return
    logger.info(f"{len(sites)} site(s): {' '.join(sites)}; local time: {tz_label}"
                f"{' (survey timezone)' if declared_tz else ' (survey declares none)'}")

    rows: list[dict] = []
    env_rows: list[dict] = []
    for site in sites:
        t_start = time.time()
        h5_path = survey.workspace / "mth5" / f"{site}.h5"
        try:
            r, e = profile_site(h5_path, survey.name, site, survey.site(site).filters,
                                args.hours_step, args.minutes, args.align, tz)
        except Exception as exc:
            logger.warning(f"{site}: could not profile ({exc!r}), skipped")
            continue
        rows += r
        env_rows += e
        logger.info(f"{site}: {len(r)} window(s) in {time.time() - t_start:.0f} s")

    df = pd.DataFrame(rows, columns=[*CSV_COLUMNS, "raw_crc"])
    env = pd.DataFrame(env_rows, columns=["site", "cell_start_utc", "env_ey"])
    if df.empty:
        logger.warning("nothing profiled")
        return
    stem = qc_dir / f"line_noise_{tag}"
    df[list(CSV_COLUMNS)].to_csv(f"{stem}.csv", index=False)
    env.to_csv(f"{stem}_env5min.csv", index=False)
    done = sorted(df["site"].unique())

    pairs = pair_table(df, env)
    pairs.to_csv(f"{stem}_pairs.csv", index=False)
    groups = overlap_groups(pairs, done)

    what = f"{tag}: {args.minutes:g} min per {args.hours_step:g} h, {args.align}-aligned"
    heatmap_figure(df, done, f"line noise profile, {what}", Path(f"{stem}_heatmap.png"))
    tab = diurnal_table(df)
    diurnal_figure(df, tab, tz_label, f"diurnal noise, {what}", Path(f"{stem}_diurnal.png"))
    concurrent_figure(df, groups, f"step_ey at concurrently recording sites, {what}", Path(f"{stem}_concurrent.png"))

    pd.set_option("display.width", 200)
    per_site = df.groupby("site").agg(
        hours=("step_ey", "size"),
        step_ey_med=("step_ey", "median"), step_ey_p90=("step_ey", _p90),
        shift_ey_med=("shift_ey", "median"), shift_ey_p90=("shift_ey", _p90),
        shift_ex_med=("shift_ex", "median"), shift_ex_p90=("shift_ex", _p90),
        burst_hx_med=("burst_hx", "median"), coh_eyhx_hi_med=("coh_eyhx_hi", "median"),
        first_utc=("hour_start_utc", "min"),
    )
    print(f"\n=== per site ({len(done)} sites, {len(df)} windows) ===")
    print(per_site.to_string(float_format=lambda v: f"{v:.4f}"))
    print(f"\n=== diurnal, local hour = {tz_label} ===")
    print(tab.to_string(float_format=lambda v: f"{v:.4f}"))
    print(f"\n=== simultaneity, pairs overlapping >= {MIN_OVERLAP_H} h ===")
    print(pairs.to_string(index=False, float_format=lambda v: f"{v:+.3f}") if not pairs.empty else "  no pair")
    for p in ("", "_env5min", "_pairs"):
        logger.info(f"table -> {stem}{p}.csv")
    for p in ("_heatmap", "_diurnal", "_concurrent"):
        logger.info(f"figure -> {stem}{p}.png")


if __name__ == "__main__":
    main()
