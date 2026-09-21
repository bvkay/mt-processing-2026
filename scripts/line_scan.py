"""Per-hour narrow-line scan: a table and figure for declaring a notch's `extra` lines by hand.

Besides 50 Hz and its harmonics, a broadband survey can carry narrow
interharmonic lines from a grid-wide source -- at Morocco Atlas Mountains,
50 +- 12.55 Hz and 50 +- 15.7 Hz (34.3, 37.4, 62.55, 65.7 Hz), sometimes also
40.55, 59.45, 98.05, 99.0 Hz, and at D10 a 10 Hz comb that switches on at
dusk. They are stable in frequency (+-0.05 Hz) but intermittent in time and
appear at different sites at different hours -- hovering over a PSD site by
site is not a practical way to find them. This scans every site's archive an
hour at a time (`mtproc.timefreq.narrow_lines`, resolution fine enough to
separate lines a few Hz apart) and writes a table and a figure so a student
can read off which lines are worth declaring as a notch's `extra:` frequencies
and which hours they are worth masking.

Reads each archive directly with h5py, read-only, one hour of one channel at
a time (never a whole channel): mth5's on-disk layout is
`Experiment/Surveys/<survey>/Stations/<site>/<run>/<channel>`, with the real
data-bearing runs the groups named `sr<rate>_<NNNN>` (mth5/aurora's own
auxiliary station-level groups -- Features, Fourier_Coefficients,
Transfer_Functions -- do not start with "sr" and are skipped); a run's start
is its `time_period.start` attribute and its rate its `sample_rate`
attribute, both written by `mth5` at ingest. Excess-over-floor dB is scale
invariant to a frequency-independent gain (the line and its local floor both
scale by the same factor), so this reads raw counts straight off the archive
-- no calibration, no `mtproc.ingest`/`mtproc.timefreq.load_station` needed,
which is also why it can afford to read a whole record a hyperslab at a time
instead of loading a channel whole.

Usage:
    python scripts/line_scan.py <survey.yaml> [SITE ...] [--hours-step 1.0]
                                [--fmin 5] [--fmax 500] [--min-db 6]
                                [--channels hx hy ex ey]

SITE defaults to every site with an archive under `<workspace>/mth5`. A site
whose archive is missing or cannot be opened (archives may still be building
while this runs) is reported and skipped, never a crash.

Writes, per site, under `<workspace>/qc/`:

    lines_<site>.csv    one row per detected line: site, run, channel,
                        hour_start_utc, f_hz, excess_db, mains_harmonic
    lines_<site>.png    one panel per channel present: hour (UTC) on x,
                        frequency on a log y axis, marker size ~ excess dB,
                        mains harmonics hollow, everything else filled
    lines_summary.txt   appended, one block per site: every line seen in at
                        least 2 hours (grouped to 0.15 Hz -- narrower than
                        the 0.5 Hz line-to-line separation `narrow_lines`
                        itself enforces, so this only merges repeat sightings
                        of the *same* physical line across hours, never two
                        distinct nearby lines), its frequency, the channels
                        it appeared on, "hours present / hours scanned", and
                        its max excess dB -- mains harmonics listed last

The same per-site block is printed to the console as it is written.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc.survey import Survey
from mtproc.timefreq import narrow_lines

DPI = 150
DEFAULT_CHANNELS = ("hx", "hy", "ex", "ey")
MIN_TRAILING_S = 600.0  # a trailing partial hour under this is dropped, not scanned
GROUP_TOL_HZ = 0.15  # frequency tolerance for "the same line" across hours (grouping the summary)
MIN_HOURS_FOR_SUMMARY = 2  # a line seen in only 1 hour is not worth a summary row
CSV_COLUMNS = ("site", "run", "channel", "hour_start_utc", "f_hz", "excess_db", "mains_harmonic")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument(
        "sites", nargs="*",
        help="site name(s); default: every site with an archive under <workspace>/mth5",
    )
    p.add_argument(
        "--hours-step", type=float, default=1.0,
        help="hour-block length to scan, in hours (default 1.0)",
    )
    p.add_argument("--fmin", type=float, default=5.0, help="low edge of the scan band, Hz (default 5)")
    p.add_argument("--fmax", type=float, default=500.0, help="high edge of the scan band, Hz (default 500)")
    p.add_argument(
        "--min-db", type=float, default=6.0,
        help="minimum excess over the local floor to report a line, dB (default 6)",
    )
    p.add_argument(
        "--channels", nargs="+", default=list(DEFAULT_CHANNELS),
        help=f"channels to scan (default {' '.join(DEFAULT_CHANNELS)})",
    )
    return p.parse_args(argv)


def default_sites(survey: Survey) -> list[str]:
    """Every site with an archive under `<workspace>/mth5`, alphabetical."""
    mth5_dir = survey.workspace / "mth5"
    if not mth5_dir.is_dir():
        return []
    return sorted(p.stem for p in mth5_dir.glob("*.h5"))


# ---------------------------------------------------------------- scanning


def _run_ids(station: h5py.Group) -> list[str]:
    """Data-bearing run group names ("sr<rate>_<NNNN>"), earliest `time_period.start` first.

    mth5/aurora also write auxiliary station-level groups (Features,
    Fourier_Coefficients, Transfer_Functions); none of those start with "sr".
    """
    ids = [k for k in station.keys() if k.startswith("sr") and isinstance(station[k], h5py.Group)]
    ids.sort(key=lambda k: str(station[k].attrs["time_period.start"]))
    return ids


def scan_archive(
    h5_path: Path,
    survey_name: str,
    site: str,
    channels_wanted: list[str],
    hours_step: float,
    fmin: float,
    fmax: float,
    min_db: float,
) -> tuple[list[dict], int, list[str]]:
    """Scan one site's archive hour by hour; returns (rows, hours scanned, channels present).

    Opens `h5_path` read-only and never reads more than one hour of one
    channel at a time (`run[channel][i0:i1]` is an HDF5 hyperslab read, not a
    load of the whole dataset). `hours_scanned` counts hour-blocks, not
    channel-hours -- one per block regardless of how many channels it holds
    -- since every run here carries the same channel set start to end.
    """
    rows: list[dict] = []
    hours_scanned = 0
    channels_present: list[str] = []
    with h5py.File(h5_path, "r") as f:
        station_path = f"Experiment/Surveys/{survey_name}/Stations/{site}"
        if station_path not in f:
            raise KeyError(f"no {station_path!r} group in {h5_path}")
        station = f[station_path]
        run_ids = _run_ids(station)
        if not run_ids:
            raise ValueError(f"no run (sr*) groups with data in {h5_path}")

        for run_id in run_ids:
            run = station[run_id]
            fs = float(run.attrs["sample_rate"])
            t0 = pd.Timestamp(str(run.attrs["time_period.start"]))
            chans = [
                c for c in channels_wanted
                if c in run and isinstance(run[c], h5py.Dataset)
            ]
            for c in chans:
                if c not in channels_present:
                    channels_present.append(c)
            if not chans:
                logger.warning(f"{site} {run_id}: none of {channels_wanted} present -- skipped")
                continue

            n = run[chans[0]].shape[0]
            block_n = max(1, int(round(hours_step * 3600.0 * fs)))
            min_block_n = int(round(MIN_TRAILING_S * fs))
            for i0 in range(0, n, block_n):
                i1 = min(i0 + block_n, n)
                is_trailing_partial = (i1 - i0) < block_n
                if is_trailing_partial and (i1 - i0) < min_block_n:
                    break  # under 10 min left in this run -- dropped, not scanned
                hour_start = t0 + pd.Timedelta(seconds=i0 / fs)
                hours_scanned += 1
                for c in chans:
                    x = run[c][i0:i1].astype("float64")
                    for f_hz, excess_db, mains in narrow_lines(x, fs, fmin, fmax, min_db=min_db):
                        rows.append(dict(
                            site=site, run=run_id, channel=c,
                            hour_start_utc=hour_start.isoformat(),
                            f_hz=round(float(f_hz), 3),
                            excess_db=round(float(excess_db), 2),
                            mains_harmonic=bool(mains),
                        ))
    return rows, hours_scanned, channels_present


# ---------------------------------------------------------------- figure


def line_figure(site: str, channels: list[str], df: pd.DataFrame, min_db: float, out: Path, dpi: int = DPI) -> None:
    """One panel per channel: hour (UTC) on x, frequency on a log y axis.

    Marker size grows with excess dB above `min_db`; a mains harmonic is
    drawn hollow (open circle), everything else filled.
    """
    fig, axes = plt.subplots(
        len(channels), 1, figsize=(11.0, 2.6 * len(channels)), sharex=True, layout="constrained",
    )
    axes = np.atleast_1d(axes)
    for ax, c in zip(axes, channels):
        sub = df[df["channel"] == c]
        ax.set_yscale("log")
        ax.grid(alpha=0.25, which="both")
        ax.set_ylabel(f"{c}\nfrequency (Hz)", fontsize=9)
        if sub.empty:
            ax.text(0.5, 0.5, "no lines", transform=ax.transAxes, ha="center", va="center", color="0.5")
            continue
        # run boundaries do not always land on a whole second, so hour_start_utc
        # mixes "...+00:00" and "...123456+00:00" ISO strings within one column --
        # pandas' fast fixed-format path infers a format from the first rows and
        # then chokes on a later one with microseconds; format="ISO8601" parses
        # each string on its own terms instead
        t = pd.to_datetime(sub["hour_start_utc"], format="ISO8601")
        size = 10.0 + 4.0 * np.clip(sub["excess_db"] - min_db, 0.0, None)
        mains = sub["mains_harmonic"].astype(bool)
        ax.scatter(
            t[~mains], sub.loc[~mains, "f_hz"], s=size[~mains],
            c="C0", edgecolors="k", linewidths=0.4, zorder=3, label="line",
        )
        ax.scatter(
            t[mains], sub.loc[mains, "f_hz"], s=size[mains],
            facecolors="none", edgecolors="C3", linewidths=0.9, zorder=3, label="mains harmonic",
        )
    axes[0].legend(fontsize=8, loc="upper right", framealpha=0.8)
    axes[-1].set_xlabel("hour start (UTC)")
    fig.autofmt_xdate()
    fig.suptitle(f"{site}: narrow lines >= {min_db:g} dB")
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


# ---------------------------------------------------------------- summary


def group_lines(df: pd.DataFrame, tol_hz: float = GROUP_TOL_HZ) -> list[dict]:
    """Chain-cluster every row by frequency (consecutive gap <= tol_hz merges), across hour and channel.

    Returns one dict per group: f_hz (mean), channels (sorted set), hours_present
    (distinct (run, hour_start_utc) pairs the group was seen in, on any channel),
    max_db, mains (True if any member was flagged a mains harmonic).
    """
    if df.empty:
        return []
    rows = df.sort_values("f_hz").to_dict("records")
    groups: list[dict] = []
    cur: dict | None = None
    for r in rows:
        if cur is not None and r["f_hz"] - cur["_last_f"] <= tol_hz:
            cur["items"].append(r)
            cur["_last_f"] = r["f_hz"]
        else:
            cur = {"items": [r], "_last_f": r["f_hz"]}
            groups.append(cur)
    out = []
    for g in groups:
        items = g["items"]
        out.append(dict(
            f_hz=float(np.mean([it["f_hz"] for it in items])),
            channels=sorted({it["channel"] for it in items}),
            hours_present=len({(it["run"], it["hour_start_utc"]) for it in items}),
            max_db=max(it["excess_db"] for it in items),
            mains=any(bool(it["mains_harmonic"]) for it in items),
        ))
    return out


def summary_block(site: str, channels_present: list[str], hours_scanned: int, df: pd.DataFrame) -> str:
    """The per-site text block: printed to the console and appended to lines_summary.txt."""
    out = [
        f"=== {site} ===",
        f"scanned: {' '.join(channels_present) or '(no requested channel present)'}, "
        f"{hours_scanned} hour(s)",
    ]
    if hours_scanned == 0:
        out.append("  nothing scanned")
        return "\n".join(out)
    groups = [g for g in group_lines(df) if g["hours_present"] >= MIN_HOURS_FOR_SUMMARY]
    if not groups:
        out.append(f"  no line seen in >= {MIN_HOURS_FOR_SUMMARY} hour(s)")
        return "\n".join(out)
    non_mains = sorted((g for g in groups if not g["mains"]), key=lambda g: g["f_hz"])
    mains = sorted((g for g in groups if g["mains"]), key=lambda g: g["f_hz"])
    for g in non_mains + mains:
        tag = "  [mains]" if g["mains"] else ""
        out.append(
            f"  {g['f_hz']:7.2f} Hz  channels: {' '.join(g['channels']):<11}  "
            f"{g['hours_present']:3d}/{hours_scanned:<3d} h  max {g['max_db']:+.1f} dB{tag}"
        )
    return "\n".join(out)


# ---------------------------------------------------------------- driver


def main(argv=None) -> None:
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    qc_dir = survey.workspace / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)
    summary_path = qc_dir / "lines_summary.txt"

    sites = args.sites or default_sites(survey)
    if not sites:
        logger.warning("no sites named, and none found with an archive under <workspace>/mth5")
        return

    for site in sites:
        t_start = time.time()
        h5_path = survey.workspace / "mth5" / f"{site}.h5"
        if not h5_path.exists():
            logger.warning(f"{site}: no archive at {h5_path} -- skipped")
            continue
        try:
            rows, hours_scanned, channels_present = scan_archive(
                h5_path, survey.name, site, list(args.channels),
                args.hours_step, args.fmin, args.fmax, args.min_db,
            )
        except Exception as exc:
            logger.warning(f"{site}: could not scan ({exc!r}) -- skipped")
            continue

        df = pd.DataFrame(rows, columns=list(CSV_COLUMNS))
        csv_path = qc_dir / f"lines_{site}.csv"
        df.to_csv(csv_path, index=False)
        logger.info(f"{site}: {len(df)} line detection(s) over {hours_scanned} hour(s) -> {csv_path}")

        png_path = qc_dir / f"lines_{site}.png"
        if channels_present:
            line_figure(site, channels_present, df, args.min_db, png_path)
            logger.info(f"{site}: figure -> {png_path}")
        else:
            logger.warning(f"{site}: none of {args.channels} present in any run -- no figure")

        block = summary_block(site, channels_present, hours_scanned, df)
        print(block)
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(block + "\n")

        logger.info(f"{site}: {time.time() - t_start:.1f} s")


if __name__ == "__main__":
    main()
