# -*- coding: utf-8 -*-
"""
All-band masks of a site by time of night and by bursts of its local electric field

Two selections of a site's record, each written as all-band masks (time
cuts) under its own origin in masks.yaml. `--night HH:MM-HH:MM` keeps one
window of local time each night (the survey's `timezone:`; 01:00-05:00 when
no window is given) and masks the rest of every day of the site's record,
found_by "night", so that a run with `process_rr.py --mask-origins night`
processes the nights alone. `--gate` masks the spans where the local
electric field carries bursts, found_by "gate". The record is the site's
`start` to `end` in survey.yaml.

The burst detector reads ex and ey of the site's derived 1 Hz archive (the
site whose `derived_from:` names it, written by scripts/decimate_site.py),
in raw counts, seconds no run covers counting as quiet. For each channel, d
is the absolute first difference divided by the median of its non-zero
values over the record; s is the 30 s running mean of the larger of the two
d. A second is a burst second when s exceeds `--k` times the median of s over
the record (3 by default), and every burst second is widened by `--m`
seconds either side (60 by default). The burst seconds are merged into
[start, end) intervals.

`--out` writes the masks to a YAML file laid out as masks.yaml; `--write`
saves them into the survey's masks.yaml (`crust.masks.save_masks`) in place
of the site's earlier masks of the same origin, every other entry kept.
`--figure` draws s against time with the threshold and both mask sets, as
`<workspace>/qc/cluster_masks/<site>_night_gate.png`.

Usage:
    python scripts/gate_masks.py <survey.yaml> <site> [--night [HH:MM-HH:MM]]
                                 [--gate] [--k K] [--m S] [--out FILE.yaml]
                                 [--write] [--figure]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from scipy.ndimage import maximum_filter1d, uniform_filter1d

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from cluster_masks import write_mask_file, write_site_masks  # noqa: E402
from crust.crosspower import _layout, _read  # noqa: E402
from crust.ingest import default_archive_path  # noqa: E402
from crust.masks import normalise, utc  # noqa: E402
from crust.survey import Survey  # noqa: E402

NIGHT = "01:00-05:00"
K = 3.0
M_S = 60
RUNNING_S = 30
NIGHT_ORIGIN, GATE_ORIGIN = "night", "gate"
DPI = 110


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("site")
    p.add_argument("--night", nargs="?", const=NIGHT, default=None, metavar="HH:MM-HH:MM",
                   help=f"keep this local window each night and mask the rest (default window {NIGHT})")
    p.add_argument("--gate", action="store_true", help="mask the bursts of the local E")
    p.add_argument("--k", type=float, default=K, help=f"burst threshold, times the record median (default {K:g})")
    p.add_argument("--m", type=int, default=M_S, metavar="S", help=f"seconds added either side of a burst "
                                                                  f"(default {M_S})")
    p.add_argument("--out", default=None, metavar="FILE.yaml", help="write the masks to this file")
    p.add_argument("--write", action="store_true", help="save the masks into the survey's masks.yaml")
    p.add_argument("--figure", action="store_true", help="draw the detector and the masks")
    return p.parse_args(argv)


def spans_to_masks(spans, reason: str, origin: str) -> list[dict]:
    """Return all-band masks over (start, end) spans."""
    return [normalise({"start": a, "end": b, "bands": "all", "reason": reason, "found_by": origin})
            for a, b in spans if b > a]


def night_windows(start, end, window: str, timezone: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the kept night windows, in UTC, of every local day that meets [start, end).

    Args:
        start: The record's start (UTC).
        end: The record's end (UTC).
        window (str): "HH:MM-HH:MM" in local time; an end before the start runs past midnight.
        timezone (str): IANA name of the local time.

    Returns:
        list: (start, end) UTC Timestamps, clipped to the record, earliest first.
    """
    start, end = utc(start), utc(end)
    a_text, b_text = (s.strip() for s in window.split("-"))
    ha, ma = (int(v) for v in a_text.split(":"))
    hb, mb = (int(v) for v in b_text.split(":"))
    over = (hb, mb) <= (ha, ma)
    first = start.tz_convert(timezone).normalize().tz_localize(None) - pd.Timedelta(days=1)
    last = end.tz_convert(timezone).normalize().tz_localize(None) + pd.Timedelta(days=1)
    out = []
    for day in pd.date_range(first, last, freq="D"):
        a = (day + pd.Timedelta(hours=ha, minutes=ma)).tz_localize(timezone, nonexistent="shift_forward",
                                                                   ambiguous=False)
        b = (day + pd.Timedelta(days=int(over), hours=hb, minutes=mb)).tz_localize(
            timezone, nonexistent="shift_forward", ambiguous=False)
        a, b = max(a.tz_convert("UTC"), start), min(b.tz_convert("UTC"), end)
        if b > a:
            out.append((a, b))
    return out


def night_masks(start, end, window: str = NIGHT, timezone: str = "UTC") -> list[dict]:
    """Return all-band masks over everything in [start, end) outside the night windows (`night_windows`)."""
    start, end = utc(start), utc(end)
    spans, cursor = [], start
    for a, b in night_windows(start, end, window, timezone):
        spans.append((cursor, a))
        cursor = b
    spans.append((cursor, end))
    return spans_to_masks(spans, f"night mask: outside {window} {timezone} (gate_masks.py)", NIGHT_ORIGIN)


def burst_seconds(ex, ey, k: float = K, m: int = M_S, running: int = RUNNING_S) -> tuple[np.ndarray, np.ndarray]:
    """Mark the burst seconds of a 1 Hz local E (the detector of the module docstring).

    Args:
        ex: Ex, one sample a second (NaN where no run covers).
        ey: Ey, likewise.
        k (float): The threshold, times the record median of the running mean.
        m (int): Seconds added either side of every burst second.
        running (int): The running mean's length, s.

    Returns:
        tuple: (burst flags per second, the running mean s).
    """
    d = []
    for x in (np.asarray(ex, float), np.asarray(ey, float)):
        dx = np.abs(np.diff(x, prepend=x[:1]))
        dx = np.where(np.isfinite(dx), dx, 0.0)
        positive = dx[dx > 0]
        d.append(dx / max(float(np.median(positive)) if positive.size else 1.0, 1e-30))
    s = uniform_filter1d(np.maximum(d[0], d[1]), running)
    burst = s > k * np.median(s)
    if m > 0:
        burst = maximum_filter1d(burst.astype(np.uint8), 2 * int(m) + 1).astype(bool)
    return burst, s


def second_spans(flags, t0) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the runs of True seconds as [start, end) UTC spans, second 0 at `t0`."""
    flags = np.asarray(flags, bool)
    edges = np.flatnonzero(np.diff(np.r_[0, flags.astype(int), 0]))
    t0 = utc(t0)
    return [(t0 + pd.Timedelta(seconds=int(a)), t0 + pd.Timedelta(seconds=int(b)))
            for a, b in zip(edges[::2], edges[1::2])]


def one_hz_site(survey: Survey, site: str) -> str:
    """Return the derived 1 Hz site of `site`.

    Raises:
        ValueError: When no site of the survey is derived from `site` at 1 Hz.
    """
    for name in survey.site_names():
        if survey.parent_of(name) == site and float(survey.site(name).sample_rate or 0) == 1.0:
            return name
    raise ValueError(f"{site}: no derived 1 Hz site; write one with scripts/decimate_site.py first")


def read_e(survey: Survey, site: str, start, end) -> tuple[pd.Timestamp, np.ndarray, np.ndarray]:
    """Read ex and ey of the site's 1 Hz archive over [start, end) on whole UTC seconds, raw counts, NaN in gaps."""
    name = one_hz_site(survey, site)
    st = _layout(default_archive_path(survey, name), name, ("ex", "ey"))
    t0 = utc(start).ceil("s")
    n = int((utc(end) - t0).total_seconds())
    out, warned = [], set()
    with h5py.File(st.path, "r") as h:
        for role in ("ex", "ey"):
            raw, covered = _read(st, h, role, int(t0.value), n, warned)
            x = np.full(n, np.nan)
            for a, b in covered if raw is not None else []:
                x[a:b] = raw[a:b]
            out.append(x)
    logger.info(f"{site}: ex, ey from {st.path.name}, {n} s from {t0}, {np.isfinite(out[0]).mean():.0%} covered")
    return t0, out[0], out[1]


def figure(path: Path, site: str, t0, s, k: float, night, gate) -> None:
    """Draw the detector's running mean against time with the threshold and the masks."""
    t = pd.to_datetime(utc(t0).value + np.arange(s.size) * 10**9, utc=True)
    fig, ax = plt.subplots(figsize=(14, 4), layout="constrained")
    ax.semilogy(t, np.maximum(s, 1e-3), lw=0.4, color="0.3", label="30 s mean of the larger normalised |dE|")
    ax.axhline(k * np.median(s), color="C3", lw=1.0, label=f"{k:g} x record median")
    for i, m in enumerate(gate):
        ax.axvspan(pd.Timestamp(m["start"]), pd.Timestamp(m["end"]), color="C3", alpha=0.25, lw=0,
                   label="gate masks" if i == 0 else None)
    for i, m in enumerate(night):
        ax.axvspan(pd.Timestamp(m["start"]), pd.Timestamp(m["end"]), ymin=0.0, ymax=0.05, color="0.2", lw=0,
                   label="night masks (outside the kept window)" if i == 0 else None)
    ax.set_title(f"{site}: burst detector and masks", fontsize=10)
    ax.set_xlabel("UTC")
    ax.legend(fontsize=7, loc="upper right")
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def main(argv=None) -> int:
    """Build the masks the flags ask for and write them.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0.
    """
    args = parse_args(argv)
    if not args.night and not args.gate:
        raise SystemExit("give --night, --gate or both")
    survey = Survey.from_yaml(args.survey_yaml)
    cfg = survey.site(args.site)
    start, end = utc(cfg.start), utc(cfg.end)
    record_s = (end - start).total_seconds()
    written = {}
    night, gate, s, t0 = [], [], None, None
    if args.night:
        night = night_masks(start, end, args.night, survey.timezone)
        kept = record_s - sum((pd.Timestamp(m["end"]) - pd.Timestamp(m["start"])).total_seconds() for m in night)
        print(f"{args.site}: night {args.night} {survey.timezone}: {len(night)} mask(s), {kept / 3600:.1f} h of "
              f"{record_s / 3600:.1f} h kept")
        written[NIGHT_ORIGIN] = night
    if args.gate:
        t0, ex, ey = read_e(survey, args.site, start, end)
        burst, s = burst_seconds(ex, ey, args.k, args.m)
        gate = spans_to_masks(second_spans(burst, t0), f"gate mask: local E burst, K {args.k:g}, M {args.m} s "
                              f"(gate_masks.py)", GATE_ORIGIN)
        print(f"{args.site}: gate K {args.k:g} M {args.m} s: {len(gate)} mask(s), {burst.mean():.0%} of the record")
        written[GATE_ORIGIN] = gate
    if args.out:
        path = write_mask_file(args.out, args.site, [m for masks in written.values() for m in masks])
        logger.info(f"masks written to {path}")
    if args.write:
        for origin, masks in written.items():
            kept, removed, new = write_site_masks(args.survey_yaml, args.site, masks, origin)
            logger.info(f"{args.site}: {origin}: {removed} earlier mask(s) replaced by {new}, {kept} other(s) kept")
    if args.figure and s is not None:
        out = survey.workspace / "qc" / "cluster_masks" / f"{args.site}_night_gate.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        figure(out, args.site, t0, s, args.k, night, gate)
        logger.info(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
