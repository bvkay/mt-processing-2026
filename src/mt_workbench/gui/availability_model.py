# -*- coding: utf-8 -*-
"""
Rows of the Stacks tab's availability chart, without Qt

The Stacks tab draws one row per survey.yaml site: its runs as bars on a UTC
axis, grouped under the deployment references, with the recipe's members,
the sites left out and why. This module holds the data side of that chart:
the runs read from each archive (`read_runs`), the cache that keeps them per
archive state (`RunsCache`), the grouping (`group_rows`), the rows
(`build_rows`), the count of candidate members per UTC hour
(`members_per_hour`), the stretch of hours a default window takes
(`best_window`, inside the local's record when candidates count there), the
nights (`night_spans`) and the Time Series tree's window under a click
(`tree_window_at`).

It holds no membership rule. Who is a member and why a site is left out is
`mt_workbench.stacks.resolve_members` over `mt_workbench.intersite.select_stack`,
which the chart calls with `RunsCache.runs_of` in place of its h5py reads, so
the chart, the tab and the scripts give one answer in one wording.
`build_rows` only puts those two lists beside the cached runs, the masks and
the read errors.

Runs are `mt_workbench.intersite.archive_runs`: (start, end) ns since the
epoch, the end being the run's last sample (`time_period.end`), read from the
HDF5 attributes alone. All channels of a run share its time period, so a
field's runs are the runs holding both of its channels. The cache is keyed and
stamped as `mt_workbench.gui.window_bar.SpanCache` is: (survey name, site),
then (path, st_mtime_ns, st_size); a stat answers whether the kept runs are
current, and no file is opened to answer it.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from mt_workbench import intersite
from mt_workbench.dclevel import channel_summary, recorded_levels
from mt_workbench.gui.windows import MIN_COVERED_S, window_hours

# the roles of each kept run list, in the order `read_runs` reads them
FIELD_ROLES = {"all": (), "H": ("hx", "hy"), "E": ("ex", "ey")}
ROLE_KEYS = {roles: key for key, roles in FIELD_ROLES.items()}
NO_REFERENCE = ""  # the group of the sites under no reference
UNREADABLE = "archive unreadable: "  # a row's reason when its archive did not open
HOUR_NS = 3_600_000_000_000
_NIGHT_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass
class Row:
    """One survey.yaml site as the chart draws it.

    Attributes:
        site (str): Site name.
        group (str): The reference whose group the row sits in, or "".
        is_reference (bool): True for the row heading its group.
        rate (float): The site's sample rate, Hz.
        runs (dict | None): ``{"all", "H", "E"}`` lists of (start_ns, end_ns),
            the end the last sample; None while the archive is not read.
        dc (dict[str, str]): Channel to dc-level verdict, {} without a record.
        masks (list[dict] | None): The site's masks.yaml entries, None when
            not loaded or unreadable.
        masks_error (str | None): Why the site's masks did not load.
        unread (str | None): The error of the last read of the archive.
        member (bool): True when the recipe takes the site.
        overlap_h (float | None): A member's overlap with the window, hours.
        reason (str | None): Why the recipe leaves the site out.
    """

    site: str
    group: str = NO_REFERENCE
    is_reference: bool = False
    rate: float = 0.0
    runs: dict | None = None
    dc: dict[str, str] = dc_field(default_factory=dict)
    masks: list[dict] | None = None
    masks_error: str | None = None
    unread: str | None = None
    member: bool = False
    overlap_h: float | None = None
    reason: str | None = None


def read_runs(path, site: str, survey_name: str) -> dict:
    """Read a site's runs and dc-level verdicts from its archive.

    Four reads of HDF5 attributes: `intersite.archive_runs` for every run,
    the runs holding hx and hy, and the runs holding ex and ey, then
    `dclevel.recorded_levels` (opened without an HDF5 file lock). Runs in a
    read thread.

    Args:
        path: The site's raw archive.
        site (str): Station name in the archive.
        survey_name (str): The survey's name, for the dc-level record.

    Returns:
        dict: ``"all"``, ``"H"`` and ``"E"``: lists of (start_ns, end_ns),
        earliest first; ``"dc"``: {channel: verdict} from
        `dclevel.channel_summary`, {} when the archive holds no record or
        not the station.

    Raises:
        OSError: If the archive is missing, is not HDF5 or is locked by a
            writer. The chart shows the row unreadable and reads it again on
            its next refresh.
    """
    out: dict = {key: intersite.archive_runs(path, site, roles) for key, roles in FIELD_ROLES.items()}
    try:
        levels = recorded_levels(Path(path), survey_name, site)
    except KeyError:  # the archive holds no such station: no record
        levels = {}
    out["dc"] = {d["channel"]: d["verdict"] for d in channel_summary(levels)}
    return out


class RunsCache:
    """Runs of each site's archive, kept under the archive's path, modification time and size.

    `get` answers after a stat, with no file opened; `read` reads an
    archive not kept, or kept for another state of the file, and keeps it
    (it runs in the chart's read thread). A failed stat is never kept.
    """

    def __init__(self):
        self._runs: dict[tuple[str, str], tuple[tuple, dict]] = {}  # (survey, site) -> (stamp, runs)

    @staticmethod
    def stamp(path) -> tuple | None:
        """Return (path, st_mtime_ns, st_size) of an archive, or None when it cannot be stat'ed."""
        if path is None:
            return None
        try:
            status = Path(path).stat()
        except OSError:
            return None
        return str(path), status.st_mtime_ns, status.st_size

    def get(self, survey, site: str, path) -> dict | None:
        """Return the kept runs of `site`'s archive as it is now, or None.

        Args:
            survey: The open `mt_workbench.survey.Survey` (its name keys the cache).
            site (str): Site name.
            path: The site's archive.

        Returns:
            dict | None: `read_runs`' dict, or None when nothing current is kept.
        """
        return self.kept(survey, site, self.stamp(path))

    def kept(self, survey, site: str, stamp) -> dict | None:
        """Return the kept runs of `site` when they were read from the file as `stamp` gives it, else None.

        No stat: the caller took the stamp (`stamp`), once per archive for a
        whole pass of the chart.

        Args:
            survey: The open `mt_workbench.survey.Survey`.
            site (str): Site name.
            stamp (tuple | None): `stamp` of the site's archive now.

        Returns:
            dict | None: `read_runs`' dict, or None.
        """
        kept = self._runs.get((survey.name, site))
        return kept[1] if stamp is not None and kept is not None and kept[0] == stamp else None

    def read(self, survey, site: str, path) -> dict:
        """Return `read_runs` of the archive, from what is kept when it is unchanged.

        Args:
            survey: The open `mt_workbench.survey.Survey`.
            site (str): Site name.
            path: The site's archive.

        Returns:
            dict: `read_runs`' dict.

        Raises:
            OSError: From `read_runs`.
        """
        stamp = self.stamp(path)
        kept = self._runs.get((survey.name, site))
        if stamp is not None and kept is not None and kept[0] == stamp:
            return kept[1]
        runs = read_runs(path, site, survey.name)
        if stamp is not None:
            self._runs[(survey.name, site)] = (stamp, runs)
        return runs

    def runs_of(self, survey, stamps: dict | None = None) -> Callable[[str, Path, tuple], list | None]:
        """Return the callable `intersite.select_stack(runs_of=...)` takes, answering from the cache.

        The callable is ``(site, path, roles) -> runs or None``: the kept,
        current runs holding `roles` (() for every run, ("hx", "hy") or
        ("ex", "ey")), or None when the archive is not read as it is now,
        which `select_stack` reports as `intersite.NOT_READ`. It opens no
        file. With `stamps` it takes "as it is now" from them and stats
        nothing for a site they hold.

        Args:
            survey: The open `mt_workbench.survey.Survey`.
            stamps (dict | None): {site: `stamp` of its archive}, taken by
                the caller for this pass.

        Returns:
            Callable: The lookup.
        """
        def lookup(site: str, path, roles=()) -> list | None:
            key = ROLE_KEYS.get(tuple(roles))
            if key is None:
                raise ValueError(f"the runs cache keeps every run, hx/hy and ex/ey, not {tuple(roles)}")
            if stamps is not None and site in stamps:
                kept = self.kept(survey, site, stamps[site])
            else:
                kept = self.get(survey, site, path)
            return None if kept is None else list(kept[key])

        return lookup


def overlap_ns(a, b) -> int:
    """Return the ns two run lists share (runs within a list do not overlap each other)."""
    return sum(max(0, min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b)


def group_rows(sites, runs_of: Callable[[str], list | None], references) -> list[tuple[str, list[str]]]:
    """Group the sites under the references they were recorded with.

    Each site goes under the reference whose runs it overlaps most, the
    earlier reference of the list on a tie; a site that overlaps none, or
    whose runs are not read, goes in the group "" ("no reference").

    Args:
        sites (iterable of str): The sites, survey.yaml order.
        runs_of (callable): ``site -> list of (start_ns, end_ns) or None``,
            every run of the site.
        references (iterable of str): The deployment references, in the
            order their groups are drawn. Names not among `sites` are
            skipped.

    Returns:
        list[tuple[str, list[str]]]: (reference, sites) per group in the
        references' order, the reference first and the rest sorted by name,
        then ("", the rest sorted by name) when it holds a site. With no
        references, the one group "".
    """
    sites = list(dict.fromkeys(sites))
    refs = [r for r in dict.fromkeys(references or ()) if r in sites]
    if not refs:
        return [(NO_REFERENCE, sorted(sites))]
    ref_runs = {r: runs_of(r) or [] for r in refs}
    under: dict[str, list[str]] = {r: [] for r in refs}
    rest = []
    for site in sites:
        if site in under:
            continue
        runs = runs_of(site) or []
        best, best_ns = None, 0
        for ref in refs:  # strict >: a tie stays with the earlier reference
            shared = overlap_ns(runs, ref_runs[ref])
            if shared > best_ns:
                best, best_ns = ref, shared
        (under[best] if best is not None else rest).append(site)
    out = [(ref, [ref] + sorted(under[ref])) for ref in refs]
    if rest:
        out.append((NO_REFERENCE, sorted(rest)))
    return out


def build_rows(sites, rates, runs, members, left_out, unread, references, masks) -> list[Row]:
    """Put the rows together in drawing order: groups as `group_rows` gives them.

    Membership and reasons are taken as given (`stacks.resolve_members`);
    the one rewrite is a site left out as `intersite.NOT_READ` whose last
    read failed, which reads "archive unreadable: <error>".

    Args:
        sites (iterable of str): The survey.yaml sites.
        rates (dict[str, float]): Sample rate per site.
        runs (dict[str, dict | None]): `read_runs` dict per site, None when not read.
        members (list[dict]): ``site`` and ``overlap_h`` per member.
        left_out (list[dict]): ``site`` and ``reason`` per site left out.
        unread (dict[str, str]): The read error per site whose read failed.
        references (iterable of str): The deployment references.
        masks (dict[str, list | str]): Per site, its masks, or the text of
            the error its masks raised.

    Returns:
        list[Row]: One row per site, group by group.
    """
    member = {m["site"]: m for m in members}
    reason = {d["site"]: d["reason"] for d in left_out}
    not_read = intersite.NOT_READ
    rows = []
    for group, names in group_rows(sites, lambda s: (runs.get(s) or {}).get("all"), references):
        for site in names:
            kept = runs.get(site)
            why = reason.get(site)
            error = unread.get(site)
            if why == not_read and error:
                why = UNREADABLE + error
            site_masks = masks.get(site)
            rows.append(Row(
                site=site, group=group, is_reference=bool(group) and site == group,
                rate=float(rates.get(site, math.nan)), runs=kept, dc=dict((kept or {}).get("dc") or {}),
                masks=site_masks if isinstance(site_masks, list) else None,
                masks_error=site_masks if isinstance(site_masks, str) else None,
                unread=error, member=site in member,
                overlap_h=member[site]["overlap_h"] if site in member else None, reason=why))
    return rows


def members_per_hour(runs, candidates, field: str, lo_ns: int, hi_ns: int,
                     edge_s: float = intersite.MEMBER_EDGE_S, merge: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Count, per UTC hour, the candidates whose record covers the whole hour.

    A candidate counts in an hour when one span of its `field` runs starts
    no later than `edge_s` after the hour's start and ends no earlier than
    `edge_s` before its end. A run from 10:00 to 12:30 counts in hours 10
    and 11; one ending at 11:59:30 counts in 11. With `merge`, the spans are
    the runs joined across gaps of at most `edge_s` (as
    `intersite.member_changes` joins them): a band stack sums a member's
    overlap over its runs, and Nador's 1000 Hz records are 2-5 runs 1 ms
    apart. Without it each run stands alone, as a time recipe judges a
    member by its single best run (`stacks.best_run`).

    Args:
        runs (dict[str, dict | None]): `read_runs` dict per site.
        candidates (iterable of str): The sites to count, the members of
            `stacks.resolve_members(..., min_overlap_hours=0.0)`.
        field (str): "H", "E" or "all".
        lo_ns, hi_ns (int): The span to count over; widened to whole UTC hours.
        edge_s (float): The slack at each edge of an hour, seconds.
        merge (bool): Join each candidate's runs across gaps of at most
            `edge_s` first (band recipes); False for time recipes.

    Returns:
        tuple: (edges, counts): ``edges`` int64 ns of the hour boundaries
        (one more than the hours), ``counts`` int per hour. Both empty when
        hi_ns <= lo_ns.
    """
    if hi_ns <= lo_ns:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=int)
    first = (int(lo_ns) // HOUR_NS) * HOUR_NS
    last = -(-int(hi_ns) // HOUR_NS) * HOUR_NS
    edges = np.arange(first, last + 1, HOUR_NS, dtype=np.int64)
    starts, ends = edges[:-1], edges[1:]
    counts = np.zeros(len(starts), dtype=int)
    edge_ns = int(round(edge_s * 1e9))
    for site in dict.fromkeys(candidates):
        spans = (runs.get(site) or {}).get(field) or []
        spans = intersite._merge_runs(spans, edge_ns) if merge else spans
        covered = np.zeros(len(starts), dtype=bool)
        for s, e in spans:
            covered |= (s <= starts + edge_ns) & (e >= ends - edge_ns)
        counts += covered
    return edges, counts


def best_window(edges, counts, within=None, edge_s: float = intersite.MEMBER_EDGE_S) -> tuple[int, int] | None:
    """Return the longest run of consecutive hours at the largest count.

    With `within` (the local's record), the hours searched first are those
    inside it, each end of `within` given `edge_s` of slack (the slack
    `members_per_hour` gives a candidate's record), at the largest count
    among them; when none of those hours counts a candidate, every hour is
    searched, as without `within`.

    Args:
        edges (array): Hour boundaries, ns (`members_per_hour`).
        counts (array): Count per hour.
        within (tuple[int, int] | None): (start_ns, end_ns) searched first:
            the local's first run start and last run end.
        edge_s (float): The slack at each end of `within`, seconds.

    Returns:
        tuple[int, int] | None: (start_ns, end_ns) of the run, the earliest of
        equal length; None when no hour counts a candidate.
    """
    counts = np.asarray(counts)
    if within is not None and counts.size:
        hours = np.asarray(edges, dtype=np.int64)
        edge_ns = int(round(edge_s * 1e9))
        inside = (hours[:-1] >= int(within[0]) - edge_ns) & (hours[1:] <= int(within[1]) + edge_ns)
        found = _longest_top(hours, np.where(inside, counts, 0))
        if found is not None:
            return found
    return _longest_top(edges, counts)


def _longest_top(edges, counts) -> tuple[int, int] | None:
    """Return the longest run of consecutive hours at the largest count, the earliest of equal length, or None."""
    counts = np.asarray(counts)
    if counts.size == 0 or counts.max() <= 0:
        return None
    top = counts == counts.max()
    best, best_len, i = None, 0, 0
    while i < len(top):
        if not top[i]:
            i += 1
            continue
        j = i
        while j < len(top) and top[j]:
            j += 1
        if j - i > best_len:
            best, best_len = (int(edges[i]), int(edges[j])), j - i
        i = j
    return best


def parse_night(night: str) -> tuple[int, int, int, int]:
    """Return (start hour, start minute, end hour, end minute) of an "HH:MM-HH:MM" night.

    Raises:
        ValueError: If the text is not two times "HH:MM" joined by "-", a
            time is out of range, or the start equals the end.
    """
    match = _NIGHT_RE.match(str(night))
    if match is None:
        raise ValueError(f"a night is 'HH:MM-HH:MM' in local time, not {night!r}")
    ha, ma, hb, mb = (int(v) for v in match.groups())
    if not (0 <= ha < 24 and 0 <= hb < 24 and 0 <= ma < 60 and 0 <= mb < 60):
        raise ValueError(f"night {night!r}: hours run 00-23 and minutes 00-59")
    if (ha, ma) == (hb, mb):
        raise ValueError(f"night {night!r}: the start and the end are the same time")
    return ha, ma, hb, mb


def night_spans(lo_ns: int, hi_ns: int, night: str, timezone: str) -> list[tuple[int, int]]:
    """Return the nights that meet [lo_ns, hi_ns), clipped to it, in ns UTC.

    The rule of scripts/gate_masks.py's `night_windows`: `night` is local
    time in `timezone`, an end before the start runs past midnight, a
    start that does not exist (a clock change) moves forward and an
    ambiguous one takes standard time.

    Args:
        lo_ns, hi_ns (int): The span, ns since the epoch.
        night (str): "HH:MM-HH:MM", local time.
        timezone (str): IANA name of the local time.

    Returns:
        list[tuple[int, int]]: (start_ns, end_ns) per night, earliest first.

    Raises:
        ValueError: From `parse_night`.
    """
    ha, ma, hb, mb = parse_night(night)
    over = (hb, mb) <= (ha, ma)
    start, end = pd.Timestamp(int(lo_ns), tz="UTC"), pd.Timestamp(int(hi_ns), tz="UTC")
    first = start.tz_convert(timezone).normalize().tz_localize(None) - pd.Timedelta(days=1)
    last = end.tz_convert(timezone).normalize().tz_localize(None) + pd.Timedelta(days=1)
    out = []
    for day in pd.date_range(first, last, freq="D"):
        a = (day + pd.Timedelta(hours=ha, minutes=ma)).tz_localize(timezone, nonexistent="shift_forward",
                                                                   ambiguous=False)
        b = (day + pd.Timedelta(days=int(over), hours=hb, minutes=mb)).tz_localize(
            timezone, nonexistent="shift_forward", ambiguous=False)
        a_ns, b_ns = max(int(a.tz_convert("UTC").value), int(lo_ns)), min(int(b.tz_convert("UTC").value), int(hi_ns))
        if b_ns > a_ns:
            out.append((a_ns, b_ns))
    return out


def tree_window_at(runs_all, sample_rate: float, t_ns: int) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return the Time Series tree's window that holds an instant, or None.

    The arithmetic of `mt_workbench.gui.windows.window_list` over
    `mt_workbench.gui.archive.load_grid`, from the runs alone: the grid
    starts at the first run's start; run k starts at grid sample
    ``round((start_k - t0) * fs)`` and holds ``round((end_k - start_k) * fs) + 1``
    samples (its end is its last sample); windows are
    `windows.window_hours(fs)` long from the grid start, the last one
    ending one sample after the last run's last sample, and a window whose
    runs cover less than `windows.MIN_COVERED_S` is not in the tree.

    Args:
        runs_all (list): Every run of the site, (start_ns, end_ns).
        sample_rate (float): The site's sample rate, Hz.
        t_ns (int): The instant, ns since the epoch.

    Returns:
        tuple | None: (start, end) UTC Timestamps of the window, None when
        the instant is outside the record or its window is not in the tree.
    """
    if not runs_all:
        return None
    fs = float(sample_rate)
    runs = sorted(runs_all)
    t0_ns = int(runs[0][0])
    pieces = [(int(round((s - t0_ns) / 1e9 * fs)), int(round((e - s) / 1e9 * fs)) + 1) for s, e in runs]
    n_samples = pieces[-1][0] + pieces[-1][1]
    n_win = int(round(window_hours(fs) * 3600.0 * fs))
    t0 = pd.Timestamp(t0_ns, tz="UTC")

    def time_at(i: int) -> pd.Timestamp:  # Grid.time_at of i / fs / 3600 hours
        return t0 + pd.Timedelta(microseconds=round(float(i / fs / 3600.0) * 3.6e9))

    guess = int(math.floor((int(t_ns) - t0_ns) / 1e9 * fs / n_win))
    for k in (guess - 1, guess, guess + 1):  # the microsecond rounding of time_at can move an edge
        i0 = k * n_win
        if k < 0 or i0 >= n_samples:
            continue
        n = min(n_win, n_samples - i0)
        start, end = time_at(i0), time_at(i0 + n)
        if not start.value <= int(t_ns) < end.value:
            continue
        covered = sum(max(0, min(i0 + n, a + m) - max(i0, a)) for a, m in pieces)
        return (start, end) if covered >= MIN_COVERED_S * fs else None
    return None
