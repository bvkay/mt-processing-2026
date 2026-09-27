# -*- coding: utf-8 -*-
"""
The window a MANTLE run takes when asked to clip it

MANTLE holds the whole processing window in memory and its reader refuses a
window that any run of either archive leaves uncovered. `choose_window`
picks, inside the window requested (the start and end given, else the two
archives' overlap), the longest span that both archives' runs cover without
a gap, and keeps its first `max_hours` hours when it is longer. The runs are
plain intervals of epoch seconds, so the choice is made and tested without
an archive or the engine; `crust.engine_mantle.archive_runs` reads them from
an archive with MANTLE's own reader, the one that checks the coverage.

`covered_spans` joins a site's runs into the spans they cover: two runs
whose gap is at most half a sample are one span, since a run of the next
file starts on the sample after the last of the previous one. A span is
half open, [first sample, last sample + 1 / fs), which is the interval of
samples the reader fills.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_HOURS = 1.0  # the shortest common covered span a pair may be processed over
REASONS = ("cap", "gap", "cap and gap")
_TOL_S = 1e-3  # a span shorter than the request by less than this is the request


@dataclass(frozen=True)
class WindowChoice:
    """The window chosen for a MANTLE run.

    Attributes:
        start (float): First second of the window, epoch UTC.
        end (float): End of the window (exclusive), epoch UTC.
        requested_start (float): Start of the window requested.
        requested_end (float): End of the window requested.
        clipped (dict | None): None when the window is the one requested,
            else {"requested_hours", "used_hours", "reason"} with reason
            "cap", "gap" or "cap and gap".
    """

    start: float
    end: float
    requested_start: float
    requested_end: float
    clipped: dict | None

    @property
    def hours(self) -> float:
        """Length of the window in hours."""
        return (self.end - self.start) / 3600.0

    @property
    def requested_hours(self) -> float:
        """Length of the window requested in hours."""
        return (self.requested_end - self.requested_start) / 3600.0


def covered_spans(runs, fs: float) -> list[tuple[float, float]]:
    """Join a site's runs into the spans they cover without a gap.

    Args:
        runs (iterable of tuple): ``(start, n_samples)`` of each run, start
            in epoch seconds of its first sample.
        fs (float): Sample rate in Hz.

    Returns:
        list of tuple: ``(start, end)`` epoch seconds, half open, in time
        order; runs whose gap is at most half a sample are one span.

    Raises:
        ValueError: If `fs` is not positive.
    """
    if not fs > 0.0:
        raise ValueError(f"sample rate {fs!r} is not positive")
    spans: list[list[float]] = []
    for start, n in sorted((float(s), int(n)) for s, n in runs):
        if n <= 0:
            continue
        end = start + n / fs
        if spans and start - spans[-1][1] <= 0.5 / fs:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return [(a, b) for a, b in spans]


def _intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return the intersection of two sorted lists of disjoint half-open spans."""
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _utc(t: float) -> str:
    """Format epoch seconds as "YYYY-MM-DD HH:MM:SS UTC" for a message."""
    import datetime as dt

    return dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def choose_window(local, remote, max_hours: float, start: float | None = None, end: float | None = None,
                  min_hours: float = MIN_HOURS) -> WindowChoice:
    """Choose the window a clipped MANTLE run takes.

    The window requested is [start, end) when given, else the overlap of the
    two sites' records (the later first sample to the earlier last). Inside
    it the spans both sites cover are intersected and the longest taken, the
    earliest of equal ones; when it is longer than `max_hours` its first
    `max_hours` hours are kept. The reason is "cap" when the cap cut the
    span, "gap" when the window is not the one the request would give
    without a gap (its first `max_hours` hours, or all of it), since a gap
    inside it, or a start or end outside a record, moved or shortened it,
    and "cap and gap" for both. A gap that lies beyond the first `max_hours`
    hours of the request changes nothing and is not a reason.

    Args:
        local (list of tuple): The local's covered spans (`covered_spans`).
        remote (list of tuple): The remote's covered spans.
        max_hours (float): The longest window, in hours.
        start (float | None): Start requested, epoch UTC.
        end (float | None): End requested, epoch UTC.
        min_hours (float): The shortest span accepted, in hours.

    Returns:
        WindowChoice: The window and what was clipped.

    Raises:
        ValueError: If `max_hours` is not positive, the request leaves no
            overlap, or no common covered span of `min_hours` lies inside it.
    """
    if not float(max_hours) > 0.0:
        raise ValueError(f"max_hours {max_hours!r} is not a positive number of hours")
    local, remote = sorted(local), sorted(remote)
    if not local or not remote:
        raise ValueError("a site has no run with data")
    a = float(start) if start is not None else max(local[0][0], remote[0][0])
    b = float(end) if end is not None else min(local[-1][1], remote[-1][1])
    if b <= a:
        raise ValueError(f"the window [{_utc(a)}, {_utc(b)}) leaves no overlap of the two records")
    common = _intersect(_intersect(local, remote), [(a, b)])
    if not common:
        raise ValueError(f"the two sites' runs share no covered span in [{_utc(a)}, {_utc(b)})")
    lo, hi = max(common, key=lambda s: (s[1] - s[0], -s[0]))
    if (hi - lo) / 3600.0 < min_hours:
        raise ValueError(f"the longest span both sites' runs cover in [{_utc(a)}, {_utc(b)}) is "
                         f"{(hi - lo) / 3600.0:.2f} h, from {_utc(lo)}; MANTLE needs at least {min_hours:g} h")
    cap_s = float(max_hours) * 3600.0
    cap = (hi - lo) > cap_s
    if cap:
        hi = lo + cap_s
        while hi - lo > cap_s:  # the float sum may land a hair above the cap, which check_window would refuse
            hi = math.nextafter(hi, -math.inf)
    # without a gap the window would be the request's first max_hours hours; a gap
    # (or a record start or end inside the request) counts when it moved the window
    gap = abs(lo - a) > _TOL_S or abs(hi - (a + min(b - a, cap_s))) > _TOL_S
    clipped = None
    if cap or gap:
        clipped = {"requested_hours": round((b - a) / 3600.0, 6), "used_hours": round((hi - lo) / 3600.0, 6),
                   "reason": "cap and gap" if cap and gap else "cap" if cap else "gap"}
    return WindowChoice(start=lo, end=hi, requested_start=a, requested_end=b, clipped=clipped)


def clip_text(clipped: dict | None) -> str:
    """Describe a `WindowChoice.clipped` for a log line or a ledger note.

    Returns:
        str: "not clipped", or e.g. "clipped (cap): 67.6 h requested, 48.0 h used".
    """
    if not clipped:
        return "not clipped"
    return (f"clipped ({clipped['reason']}): {float(clipped['requested_hours']):.1f} h requested, "
            f"{float(clipped['used_hours']):.1f} h used")
