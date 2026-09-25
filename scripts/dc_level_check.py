# -*- coding: utf-8 -*-
"""
Check the raw DC level of every channel of a survey's archives

An electric input that is open, or of very high impedance, sits at a rail
or bias level of the logger's input stage: C05 ey and C13 ey of the Morocco
survey sit at about 1.60e9 counts, while the healthy electric channels of
line C sit at 0.6e7 to 9.9e7 counts in magnitude. This script reads each
site's raw archive (`crust.ingest.default_archive_path`,
``<workspace>/mth5/<site>.h5``) and reports, per run and channel, the median
level in counts, its spread and a verdict.

Each archive is opened read-only with h5py, without an HDF5 file lock, so
the jobs of a running campaign open it as before. Every electric and
magnetic channel (the dataset's ``type`` attribute, else the first letter of
its name: e electric, h or b magnetic) of every run at --rate (default: the
site's sample rate, `Survey.sample_rate_of`) is read as a subsample: every
k-th sample, k the smallest step that keeps the read within --sample-seconds
of samples (default 3600 s, 3.6e6 samples at 1000 Hz), by a stepped slice
of the dataset. Per channel and run:

    median   the subsample's median, counts
    MAD      the median absolute deviation from it, counts (unscaled)
    rail %   the share of samples at the rail: on each side of the median,
             the samples whose distance from the median is at least 90 % of
             the largest distance seen on that side, the larger side
             counted; a channel clipped at a rail piles its samples there,
             and a flat channel has 100 %
    ratio    |median| over the typical level of its channel type, the median
             |median| of every electric (or magnetic) channel and run in the
             report

and the verdict, in this order:

    open input?  |median| above --threshold-counts (default 1e9), or ratio
                 above --ratio (default 30)
    saturated?   rail % above 1 %
    ok           otherwise

Without site names every site of the survey's `sites:` block with an
archive is checked; derived sites (``derived_from:``) and observatory
entries (``instrument: intermagnet``) are skipped with a note. The table is
sorted by verdict (open input?, saturated?, ok), then site, run and channel,
and ends with a one-line summary of the flagged channels. --csv writes the
rows, with the subsampling step and the typical levels, to a CSV file.

Exit status: 0 with the report, whatever it finds; 2 when the survey file
is missing, a named site has no archive, or an archive cannot be opened or
holds no station group of its site.

Usage:
    python scripts/dc_level_check.py <survey.yaml> [SITE ...] [--rate 1000] [--threshold-counts N]
        [--ratio R] [--sample-seconds S] [--csv OUT.csv]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import h5py  # noqa: E402
import numpy as np  # noqa: E402

from crust.ingest import default_archive_path  # noqa: E402
from crust.survey import OBSERVATORY, Survey  # noqa: E402

OPEN, SATURATED, OK = "open input?", "saturated?", "ok"
VERDICT_ORDER = {OPEN: 0, SATURATED: 1, OK: 2}
RAIL_LEVEL = 0.9  # a sample at the rail: at least this share of the largest distance from the median
RAIL_LIMIT = 0.01  # saturated? above this share of samples at the rail
RUN_RE = re.compile(r"^sr(\d+(?:p\d+)?)_\d+$")  # run groups sr<rate>_<n>, e.g. sr1000_0002
CSV_COLUMNS = ("site", "run", "channel", "type", "sample_rate", "n_samples", "step", "n_read", "median_counts",
               "mad_counts", "rail_fraction", "typical_counts", "ratio", "verdict")


def channel_type(name: str, dataset: h5py.Dataset) -> str | None:
    """Return a channel's type, "electric" or "magnetic".

    Args:
        name (str): Channel name in the run group, e.g. "ey".
        dataset (h5py.Dataset): The channel's dataset.

    Returns:
        str | None: The dataset's ``type`` attribute when it is electric or
        magnetic, else the type the name's first letter gives (e electric,
        h or b magnetic); None for any other channel.
    """
    kind = dataset.attrs.get("type")
    if isinstance(kind, bytes):
        kind = kind.decode()
    if kind in ("electric", "magnetic"):
        return kind
    first = name[:1].lower()
    return "electric" if first == "e" else "magnetic" if first in ("h", "b") else None


def rail_fraction(x: np.ndarray, median: float) -> float:
    """Return the share of samples at the rail.

    On each side of the median, a sample is at the rail when its distance
    from the median is at least RAIL_LEVEL of the largest distance seen on
    that side; the larger of the two shares is returned.

    Args:
        x (np.ndarray): Samples.
        median (float): Their median.

    Returns:
        float: Share of samples at the rail, 0 to 1; 1 for a flat channel.
    """
    upper = float(x.max()) - median
    lower = median - float(x.min())
    return float(max(np.mean(x >= median + RAIL_LEVEL * upper), np.mean(x <= median - RAIL_LEVEL * lower)))


def subsample_step(n: int, fs: float, sample_seconds: float) -> int:
    """Return the smallest step k that keeps n samples at fs within sample_seconds of samples.

    Args:
        n (int): Samples in the channel.
        fs (float): Sample rate in Hz.
        sample_seconds (float): Seconds' worth of samples to read at most.

    Returns:
        int: The step, at least 1.
    """
    return max(1, math.ceil(n / max(1.0, sample_seconds * fs)))


def channel_stats(dataset: h5py.Dataset, fs: float, sample_seconds: float) -> dict:
    """Read a channel's subsample and measure its level.

    Args:
        dataset (h5py.Dataset): The channel's samples, raw counts.
        fs (float): Its sample rate in Hz.
        sample_seconds (float): Seconds' worth of samples to read at most.

    Returns:
        dict: ``n_samples``, ``step``, ``n_read``, ``median_counts``,
        ``mad_counts`` and ``rail_fraction``.
    """
    n = int(dataset.shape[0])
    step = subsample_step(n, fs, sample_seconds)
    x = np.asarray(dataset[::step], dtype="float64")
    median = float(np.median(x))
    return dict(n_samples=n, step=step, n_read=int(x.size), median_counts=median,
                mad_counts=float(np.median(np.abs(x - median))), rail_fraction=rail_fraction(x, median))


def run_rate(name: str, group: h5py.Group) -> float:
    """Return a run's sample rate in Hz: its ``sample_rate`` attribute, else the one its name gives."""
    if "sample_rate" in group.attrs:
        return float(group.attrs["sample_rate"])
    return float(RUN_RE.match(name).group(1).replace("p", "."))


def station_group(archive: h5py.File, survey_name: str, site: str) -> h5py.Group:
    """Return a site's station group, Experiment/Surveys/<survey>/Stations/<site>.

    Args:
        archive (h5py.File): The open archive.
        survey_name (str): The survey's name, looked in first.
        site (str): Station id.

    Returns:
        h5py.Group: The station group.

    Raises:
        KeyError: If no survey group of the archive holds the station.
    """
    surveys = archive.get("Experiment/Surveys")
    names = [] if surveys is None else sorted(surveys, key=lambda s: s != survey_name)
    for name in names:
        path = f"Experiment/Surveys/{name}/Stations/{site}"
        if path in archive:
            return archive[path]
    raise KeyError(f"no station group {site} under Experiment/Surveys ({', '.join(names) or 'no survey'})")


def check_archive(path: Path, survey_name: str, site: str, rate: float, sample_seconds: float) -> tuple[list, list]:
    """Measure the level of every electric and magnetic channel of a site's runs at one rate.

    Args:
        path (Path): The site's raw archive.
        survey_name (str): The survey's name.
        site (str): Station id.
        rate (float): Sample rate of the runs checked, Hz.
        sample_seconds (float): Seconds' worth of samples read per channel and run at most.

    Returns:
        tuple: (rows, notes). Each row is a dict with ``site``, ``run``,
        ``channel``, ``type``, ``sample_rate`` and the `channel_stats`
        values; the notes name runs at other rates and empty channels.

    Raises:
        OSError: If the archive does not open.
        KeyError: From `station_group`.
    """
    rows, notes = [], []
    with h5py.File(path, "r", locking=False) as archive:
        station = station_group(archive, survey_name, site)
        for run in sorted(name for name in station if RUN_RE.match(name)):
            group = station[run]
            fs = run_rate(run, group)
            if abs(fs - rate) > 1e-6 * rate:
                notes.append(f"{run} at {fs:g} Hz")
                continue
            for comp in sorted(group):
                dataset = group[comp]
                if not isinstance(dataset, h5py.Dataset):
                    continue
                kind = channel_type(comp, dataset)
                if kind is None:
                    continue
                if dataset.shape[0] == 0:
                    notes.append(f"{run} {comp} empty")
                    continue
                stats = channel_stats(dataset, fs, sample_seconds)
                rows.append(dict(site=site, run=run, channel=comp, type=kind, sample_rate=fs, **stats))
    return rows, notes


def classify(rows: list[dict], threshold_counts: float, ratio_limit: float) -> dict[str, float]:
    """Give each row its typical level, ratio and verdict.

    Args:
        rows (list[dict]): Rows of `check_archive`, completed in place with
            ``typical_counts``, ``ratio`` and ``verdict``.
        threshold_counts (float): |median| above which a channel is an open input.
        ratio_limit (float): Ratio to the typical level above which a channel is an open input.

    Returns:
        dict[str, float]: The typical level of each channel type, the median
        |median| over its rows, in counts.
    """
    typical = {}
    for kind in sorted({row["type"] for row in rows}):
        typical[kind] = float(np.median([abs(r["median_counts"]) for r in rows if r["type"] == kind]))
    for row in rows:
        level, ref = abs(row["median_counts"]), typical[row["type"]]
        row["typical_counts"] = ref
        row["ratio"] = level / ref if ref > 0 else math.nan
        if level > threshold_counts or (ref > 0 and row["ratio"] > ratio_limit):
            row["verdict"] = OPEN
        elif row["rail_fraction"] > RAIL_LIMIT:
            row["verdict"] = SATURATED
        else:
            row["verdict"] = OK
    rows.sort(key=lambda r: (VERDICT_ORDER[r["verdict"]], r["site"], r["run"], r["channel"]))
    return typical


def table_lines(rows: list[dict]) -> list[str]:
    """Format the rows as a fixed-width table: site, run, channel, median, MAD, ratio, rail %, verdict."""
    site_w = max([4] + [len(r["site"]) for r in rows])
    run_w = max([3] + [len(r["run"]) for r in rows])
    head = (f"{'site':<{site_w}}  {'run':<{run_w}}  {'channel':<7}  {'median':>11}  {'MAD':>9}  {'ratio':>7}  "
            f"{'rail %':>6}  verdict")
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r['site']:<{site_w}}  {r['run']:<{run_w}}  {r['channel']:<7}  {r['median_counts']:>+11.3e}  "
                     f"{r['mad_counts']:>9.2e}  {r['ratio']:>7.2f}  {100 * r['rail_fraction']:>6.2f}  {r['verdict']}")
    return lines


def summary_line(rows: list[dict]) -> str:
    """Summarise the flagged channels in one line, per verdict: site, channel and the runs flagged."""
    parts = []
    for verdict in (OPEN, SATURATED):
        flagged: dict[tuple[str, str], list[str]] = {}
        for r in rows:
            if r["verdict"] == verdict:
                flagged.setdefault((r["site"], r["channel"]), []).append(r["run"])
        items = [f"{site} {comp} ({', '.join(runs)})" for (site, comp), runs in sorted(flagged.items())]
        parts.append(f"{verdict} {'; '.join(items) if items else 'none'}")
    n_flagged = sum(r["verdict"] != OK for r in rows)
    return f"summary: {n_flagged} of {len(rows)} channel runs flagged -- " + " | ".join(parts)


def write_csv(rows: list[dict], path: Path) -> None:
    """Write the rows to a CSV file with the columns of CSV_COLUMNS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def select_sites(survey: Survey, names: list[str]) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Choose the sites to check.

    Args:
        survey (Survey): The survey.
        names (list[str]): Sites named on the command line; every declared
            site when empty.

    Returns:
        tuple: (sites to check, {reason: [sites skipped]}, [named sites
        with no archive]). The reasons are "derived", "observatory" and,
        for the declared sites, "no archive".
    """
    entries = survey.config.get("sites") or {}
    checked, skipped, missing = [], {"derived": [], "observatory": [], "no archive": []}, []
    for site in names or survey.site_names():
        if survey.parent_of(site):
            skipped["derived"].append(site)
        elif (entries.get(site) or {}).get("instrument") == OBSERVATORY:
            skipped["observatory"].append(site)
        elif not default_archive_path(survey, site).exists():
            (missing if names else skipped["no archive"]).append(site)
        else:
            checked.append(site)
    return checked, skipped, missing


def main(argv=None) -> int:
    """Check the raw DC level of a survey's channels and print the report.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 with the report; 2 when the survey file is missing, a named
        site has no archive, or an archive does not open or lacks its
        station group.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml")
    parser.add_argument("sites", nargs="*", metavar="SITE", help="sites to check (default: every site with an archive)")
    parser.add_argument("--rate", type=float, default=None,
                        help="sample rate of the runs checked, Hz (default: the site's sample rate)")
    parser.add_argument("--threshold-counts", type=float, default=1e9,
                        help="|median| above which a channel is an open input (default %(default)g)")
    parser.add_argument("--ratio", type=float, default=30.0,
                        help="ratio to the typical level of the channel type above which a channel is an open "
                             "input (default %(default)g)")
    parser.add_argument("--sample-seconds", type=float, default=3600.0,
                        help="seconds' worth of samples read per channel and run at most (default %(default)g)")
    parser.add_argument("--csv", type=Path, default=None, help="write the rows to this CSV file")
    args = parser.parse_args(argv)

    yaml_path = Path(args.survey_yaml)
    if not yaml_path.is_file():
        print(f"ERROR no survey file {yaml_path}", file=sys.stderr)
        return 2
    survey = Survey.from_yaml(yaml_path)
    sites, skipped, missing = select_sites(survey, args.sites)
    print(f"survey {survey.name}: archives in {survey.workspace / 'mth5'}")
    for reason, names in skipped.items():
        if names:
            print(f"skipped ({reason}): {', '.join(names)}")
    if missing:
        for site in missing:
            print(f"ERROR {site}: no archive {default_archive_path(survey, site)}", file=sys.stderr)
        return 2

    rows, errors = [], 0
    for site in sites:
        path = default_archive_path(survey, site)
        rate = args.rate if args.rate is not None else survey.sample_rate_of(site)
        started = time.perf_counter()
        try:
            got, notes = check_archive(path, survey.name, site, rate, args.sample_seconds)
        except (OSError, KeyError) as exc:
            print(f"ERROR {site}: {path}: {exc}", file=sys.stderr)
            errors += 1
            continue
        rows += got
        runs = sorted({r["run"] for r in got})
        extra = f"; left out: {', '.join(notes)}" if notes else ""
        print(f"  {site}: {len(runs)} run(s) at {rate:g} Hz, {len(got)} channel runs read in "
              f"{time.perf_counter() - started:.1f} s{extra}", flush=True)

    if rows:
        typical = classify(rows, args.threshold_counts, args.ratio)
        levels = ", ".join(f"{kind} {level:.3e} counts" for kind, level in typical.items())
        print(f"typical |median|: {levels}; open input? above {args.threshold_counts:g} counts or {args.ratio:g} x "
              f"typical, saturated? above {100 * RAIL_LIMIT:g} % at the rail")
        print()
        print("\n".join(table_lines(rows)))
        print()
    print(summary_line(rows))
    if args.csv is not None:
        write_csv(rows, args.csv)
        print(f"csv: {args.csv}")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
