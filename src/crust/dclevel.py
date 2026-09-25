# -*- coding: utf-8 -*-
"""
Raw DC level of a channel: median, spread, share at a rail and a verdict

An electric input that is open, or of very high impedance, sits at a rail
or bias level of the logger's input stage: C05 ey and C13 ey of the Morocco
survey sit at about 1.60e9 counts, while the healthy electric channels of
line C sit at 0.6e7 to 9.9e7 counts in magnitude. `channel_stats` measures
a channel's stored samples, an h5py dataset or an array, through a
subsample: every k-th sample, k the smallest step that keeps the read
within `sample_seconds` of samples (`subsample_step`; SAMPLE_SECONDS,
3600 s, is 3.6e6 samples at 1000 Hz). Per channel and run it gives

    median   the subsample's median, counts
    MAD      the median absolute deviation from it, counts (unscaled)
    rail     the share of samples at the rail (`rail_fraction`)

and `classify` gives each channel run of a set measured together its ratio
to the typical level of its channel type (the median |median| of the set's
electric, or magnetic, channel runs) and its verdict, in this order:

    open input?  |median| above THRESHOLD_COUNTS (1e9), or ratio above
                 RATIO_LIMIT (30)
    saturated?   rail share above RAIL_LIMIT (1 %)
    ok           otherwise

`crust.ingest.ingest_site` measures each run of a site as it writes it,
classifies the site's channel runs together and records each run's levels
in the run's comment (`level_note`). `recorded_levels` reads them back from
an archive, for the flagged lines of scripts/ingest_site.py (`flag_line`)
and the dc level column of the GUI's Metadata tab (`channel_summary`).
scripts/dc_level_check.py measures a survey's archives with
`channel_stats` and classifies them together.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import h5py
import numpy as np

OPEN, SATURATED, OK = "open input?", "saturated?", "ok"
VERDICT_ORDER = {OPEN: 0, SATURATED: 1, OK: 2}
RAIL_LEVEL = 0.9  # a sample at the rail: at least this share of the largest distance from the median
RAIL_LIMIT = 0.01  # saturated? above this share of samples at the rail
THRESHOLD_COUNTS = 1e9  # open input? above this |median|
RATIO_LIMIT = 30.0  # open input? above this ratio to the typical level of the channel type
SAMPLE_SECONDS = 3600.0  # seconds' worth of samples read per channel and run at most
RUN_RE = re.compile(r"^sr(\d+(?:p\d+)?)_\d+$")  # run groups sr<rate>_<n>, e.g. sr1000_0002
# the run comment's record: the prefix, then "<channel> <median> <rail %> <verdict>" per channel, joined by ", "
NOTE_PREFIX = "dc level (median counts, rail %): "
NOTE_ITEM = re.compile(r"^(?P<channel>\S+) (?P<median>\S+) (?P<rail>\S+) (?P<verdict>.+)$")


def channel_type(name: str, channel) -> str | None:
    """Return a channel's type, "electric" or "magnetic".

    Args:
        name (str): Channel name, e.g. "ey".
        channel: The channel's h5py dataset or xarray DataArray, whose
            ``attrs`` may carry its ``type``.

    Returns:
        str | None: The ``type`` attribute when it is electric or magnetic,
        else the type the name's first letter gives (e electric, h or b
        magnetic); None for any other channel.
    """
    kind = channel.attrs.get("type")
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


def channel_stats(samples, fs: float, sample_seconds: float = SAMPLE_SECONDS) -> dict:
    """Measure a channel's level on its subsample.

    Args:
        samples: The channel's samples, raw counts: an h5py dataset (read
            as a stepped slice) or an array.
        fs (float): Its sample rate in Hz.
        sample_seconds (float): Seconds' worth of samples to read at most.

    Returns:
        dict: ``n_samples``, ``step``, ``n_read``, ``median_counts``,
        ``mad_counts`` and ``rail_fraction``.
    """
    n = int(samples.shape[0])
    step = subsample_step(n, fs, sample_seconds)
    x = np.asarray(samples[::step], dtype="float64")
    median = float(np.median(x))
    return dict(n_samples=n, step=step, n_read=int(x.size), median_counts=median,
                mad_counts=float(np.median(np.abs(x - median))), rail_fraction=rail_fraction(x, median))


def classify(rows: list[dict], threshold_counts: float = THRESHOLD_COUNTS,
             ratio_limit: float = RATIO_LIMIT) -> dict[str, float]:
    """Give each channel run its typical level, ratio and verdict.

    Args:
        rows (list[dict]): Channel runs with ``type``, ``median_counts`` and
            ``rail_fraction``, completed in place with ``typical_counts``,
            ``ratio`` and ``verdict``.
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
    return typical


def counts_text(value: float) -> str:
    """Return a level in counts to three significant digits, e.g. "1.60e9" or "-3.00e7"."""
    if not math.isfinite(value):
        return str(value)
    mantissa, exponent = f"{value:.2e}".split("e")
    return f"{mantissa}e{int(exponent)}"


def flag_line(row: dict) -> str:
    """Return a flagged channel run as one line.

    Args:
        row (dict): A channel run with ``site``, ``run``, ``channel``,
            ``median_counts``, ``rail_fraction`` and ``verdict``.

    Returns:
        str: "<site> <run> <channel>: median 1.60e9 counts, open input?",
        with the rail share before the verdict of a saturated channel.
    """
    rail = f", {100 * row['rail_fraction']:.2f} % at the rail" if row["verdict"] == SATURATED else ""
    return (f"{row['site']} {row['run']} {row['channel']}: median {counts_text(row['median_counts'])} counts"
            f"{rail}, {row['verdict']}")


def level_note(rows: list[dict]) -> str:
    """Return the run comment's record of a run's classified channels.

    Args:
        rows (list[dict]): The run's channel runs, classified.

    Returns:
        str: NOTE_PREFIX, then "<channel> <median> <rail %> <verdict>" per
        channel joined by ", ", e.g. "dc level (median counts, rail %): ex
        +2.000e+07 0.00 ok, ey +1.600e+09 0.00 open input?".
    """
    return NOTE_PREFIX + ", ".join(
        f"{r['channel']} {r['median_counts']:+.3e} {100 * r['rail_fraction']:.2f} {r['verdict']}" for r in rows)


def parse_level_note(comment: str) -> list[dict]:
    """Read the channel levels a run comment records (`level_note`).

    The record runs from NOTE_PREFIX to the next "; " of the comment or its
    end, so it reads the same with other notes before or after it.

    Args:
        comment (str): Run comment.

    Returns:
        list[dict]: ``channel``, ``median_counts``, ``rail_fraction`` (0 to 1)
        and ``verdict`` per channel, in the record's order; empty for a
        comment without the record.
    """
    if NOTE_PREFIX not in comment:
        return []
    body = comment.split(NOTE_PREFIX, 1)[1].split("; ", 1)[0]
    rows = []
    for item in body.split(", "):
        match = NOTE_ITEM.match(item.strip())
        if match is None or match["verdict"] not in VERDICT_ORDER:
            continue
        try:
            median, rail = float(match["median"]), float(match["rail"]) / 100.0
        except ValueError:
            continue
        rows.append(dict(channel=match["channel"], median_counts=median, rail_fraction=rail,
                         verdict=match["verdict"]))
    return rows


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


def _text(value) -> str:
    """Return an HDF5 attribute as text, "" for None."""
    if value is None:
        return ""
    return value.decode() if isinstance(value, bytes) else str(value)


def recorded_levels(path: Path, survey_name: str, site: str) -> dict[str, list[dict]]:
    """Read the channel levels recorded in the run comments of a site's archive.

    The archive is opened read-only with h5py, without an HDF5 file lock.
    A derived site's run comment carries its source run's comment, and with
    it the source run's levels, which decimation keeps.

    Args:
        path (Path): The archive.
        survey_name (str): The survey's name.
        site (str): Station id.

    Returns:
        dict[str, list[dict]]: {run: rows} for the runs whose comment holds
        the record, in run order; each row is a `parse_level_note` row with
        ``site`` and ``run``.

    Raises:
        OSError: If the archive does not open.
        KeyError: From `station_group`.
    """
    out = {}
    with h5py.File(path, "r", locking=False) as archive:
        station = station_group(archive, survey_name, site)
        for run in sorted(name for name in station if RUN_RE.match(name)):
            rows = parse_level_note(_text(station[run].attrs.get("comments")))
            if rows:
                out[run] = [dict(site=site, run=run, **row) for row in rows]
    return out


def channel_summary(levels: dict[str, list[dict]]) -> list[dict]:
    """Summarise a site's recorded levels per channel.

    Args:
        levels (dict[str, list[dict]]): `recorded_levels` of the site.

    Returns:
        list[dict]: One dict per channel, in the order the channels are
        first recorded: ``channel``; ``verdict``, the most severe verdict of
        its runs (open input?, then saturated?, then ok); ``median_counts``,
        the median of the run medians over the runs with that verdict;
        ``n_verdict``, the number of those runs; and ``n_runs``, the runs
        recorded for the channel.
    """
    by_channel: dict[str, list[dict]] = {}
    for rows in levels.values():
        for row in rows:
            by_channel.setdefault(row["channel"], []).append(row)
    out = []
    for channel, rows in by_channel.items():
        verdict = min((r["verdict"] for r in rows), key=VERDICT_ORDER.__getitem__)
        worst = [r["median_counts"] for r in rows if r["verdict"] == verdict]
        out.append(dict(channel=channel, verdict=verdict, median_counts=float(np.median(worst)),
                        n_verdict=len(worst), n_runs=len(rows)))
    return out
