# -*- coding: utf-8 -*-
"""
Fetch INTERMAGNET observatory data and archive it as a survey site

An observatory gives a remote reference that reaches the long periods, or a
window longer than any site's. The script fetches an INTERMAGNET
observatory's one-second X, Y, Z from the BGS GIN (`mtproc.observatory`,
ported from the AusLAMP processing), one request per UTC day, at the best
available publication state.

start and end (UTC; dates or ISO times, whole days are fetched) default to the
survey's earliest site `start:` and latest site `end:` in survey.yaml. Three
steps, in order:

  1. Every day of the span missing from the cache is fetched into
     <cache>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz (--cache, default
     <workspace>/observatory), each fetch logged with its size and seconds.
     Cached days are reused, so a re-run fetches only the missing days.
  2. The cached days are written to <workspace>/mth5/<CODE>.h5
     (`mtproc.ingest.default_archive_path`): station <CODE> at the IAGA-2002
     header's position, channels hx = X (north), hy = Y (east), hz = Z (down)
     in nT at 1 Hz with no filters, gaps up to --max-gap seconds (default 600)
     filled by a straight line and one run per stretch between longer gaps.
     The archive is rebuilt from the cache on every run.
  3. survey.yaml gains, or has refreshed, the site entry
     <CODE>: {instrument: intermagnet, channels: [hx, hy, hz], latitude,
     longitude, elevation, start, end, notes: "INTERMAGNET observatory, 1 s,
     fetched <UTC>"}, through the rewrite used by the GUI Metadata tab
     (`mtproc_gui.metadata_edit.rewrite_sites_block`). The `sites:` block
     alone is rewritten; every other site's text and everything outside the
     block stay as they were, and any other key of an existing
     <CODE> entry (a remote:, say) is kept. An existing site of that name
     that is not an observatory is left as it is and the script exits 2.

--dry-run prints the days it would fetch and the days already cached, and
the archive and the entry it would write, without writing anything. With
the GIN out of reach the script exits 1 with one line saying so; the cache
keeps whole days only.

`mtproc.survey.Survey.instrument_of` accepts the raw-data recorders of
`mtproc.instruments.INSTRUMENTS` and raises for `intermagnet`, so the GUI's
Metadata tab, which asks it about every site, fails on a survey holding an
observatory site. The script prints a warning after writing the entry.

Usage:
    python scripts/fetch_observatory.py <survey.yaml> <IAGA code> [start] [end]
        [--cache DIR] [--max-gap S] [--dry-run]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc import observatory  # noqa: E402
from mtproc.ingest import default_archive_path  # noqa: E402
from mtproc.survey import Survey  # noqa: E402


def survey_span(sites: dict, code: str) -> tuple[str, str] | None:
    """Return the dated span of the survey's recording sites.

    Observatory sites (named `code` or with instrument intermagnet) are
    skipped.

    Args:
        sites (dict): The `sites:` mapping of survey.yaml.
        code (str): IAGA code of the observatory.

    Returns:
        tuple[str, str] | None: (earliest start, latest end), or None when no
        site has both a start and an end.
    """
    starts, ends = [], []
    for name, entry in sites.items():
        entry = entry or {}
        if name == code or entry.get("instrument") == "intermagnet":
            continue
        if entry.get("start"):
            starts.append(str(entry["start"]))
        if entry.get("end"):
            ends.append(str(entry["end"]))
    return (min(starts), max(ends)) if starts and ends else None


def day_ranges(days) -> str:
    """Format dates as runs of consecutive days.

    Args:
        days (list[datetime.date]): Days, in any order.

    Returns:
        str: E.g. "2023-09-18 .. 2023-09-20 (3), 2023-09-25", or "none" when
        empty.
    """
    days = sorted(days)
    if not days:
        return "none"
    out, a, b = [], days[0], days[0]
    for d in days[1:] + [None]:
        if d is not None and (d - b).days == 1:
            b = d
            continue
        out.append(str(a) if a == b else f"{a} .. {b} ({(b - a).days + 1})")
        if d is not None:
            a = b = d
    return ", ".join(out)


def main(argv=None) -> int:
    """Fetch, archive and register one observatory.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 1 when the GIN fails, 2 when survey.yaml already
        has a site of that name that is not an observatory.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("survey_yaml")
    parser.add_argument("code", help="the observatory's IAGA code, e.g. SFS")
    parser.add_argument("start", nargs="?", help="UTC date or time (default: the survey's earliest site start)")
    parser.add_argument("end", nargs="?", help="UTC date or time, its whole day included (default: the latest site end)")
    parser.add_argument("--cache", help="day cache (default <workspace>/observatory)")
    parser.add_argument("--max-gap", type=float, default=observatory.MAX_GAP_S,
                        help="longest gap in seconds filled by a straight line (default %(default)g)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be fetched and written; touch nothing")
    args = parser.parse_args(argv)

    code = args.code.upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        parser.error(f"{args.code!r} is not an IAGA code (three letters)")
    yaml_path = Path(args.survey_yaml).resolve()
    survey = Survey.from_yaml(yaml_path)
    sites = survey.config.get("sites") or {}
    held = sites.get(code) or {}
    if code in sites and held.get("instrument") != "intermagnet":
        print(f"ERROR {yaml_path.name} already has a site {code} that is not an observatory "
              f"(instrument {held.get('instrument', survey.instrument)}): not touching it", file=sys.stderr)
        return 2
    start, end = args.start, args.end
    if start is None or end is None:
        span = survey_span(sites, code)
        if span is None:
            parser.error("no site in survey.yaml has a start: and an end: -- give start and end")
        start, end = start or span[0], end or span[1]
    cache = Path(args.cache).resolve() if args.cache else survey.workspace / "observatory"
    archive = default_archive_path(survey, code)

    cov = observatory.coverage(code, start, end, cache)
    todo = list(cov.day[~cov.cached])
    print(f"{code} {cov.day.iloc[0]} .. {cov.day.iloc[-1]}: {len(cov)} day(s), {int(cov.cached.sum())} cached, "
          f"{len(todo)} to fetch (cache {cache / code})")
    print(f"  to fetch:  {day_ranges(todo)}")
    print(f"  cached:    {day_ranges(list(cov.day[cov.cached]))}")
    if args.dry_run:
        print(f"  would write {archive} (hx hy hz, 1 Hz, nT; gaps up to {args.max_gap:g} s filled)")
        print(f"  would add or refresh {code} in {yaml_path}")
        if todo:
            print(f"  first request: {observatory.gin_url(code, todo[0])}")
        print("dry run: nothing fetched, nothing written")
        return 0

    before = set(cov.path[cov.cached])
    try:
        observatory.fetch_days(code, start, end, cache)
    except observatory.GINError as exc:
        new = sum(1 for p in observatory.coverage(code, start, end, cache).path if p.exists() and p not in before)
        kept = "the cache is as it was" if not new else f"the {new} day(s) fetched before it are kept, whole"
        print(f"ERROR {exc} -- {kept}", file=sys.stderr)
        return 1
    missing = [r.day for r in observatory.coverage(code, start, end, cache).itertuples() if not r.cached]
    if missing:
        print(f"  WARNING the GIN served no data for {len(missing)} day(s): {day_ranges(missing)}")

    summary = observatory.to_mth5(code, start, end, cache, archive, max_gap_s=args.max_gap, survey=survey.name)
    meta = summary["meta"]
    print(f"archive: {summary['path']}")
    print(f"  {code} {meta['station_name']}: {meta['latitude']} N, {meta['longitude']} E, {meta['elevation']} m "
          f"(IAGA-2002 header); data types {meta['data_types']}")
    print(f"  gaps: {meta['gaps']}")
    for run in summary["runs"]:
        print(f"  run {run['id']}: {run['start']} .. {run['end']} ({run['n']} s)")

    from mtproc_gui.metadata_edit import rewrite_sites_block  # the sites-block rewrite of the Metadata tab

    entry = observatory.survey_entry(meta, summary["runs"])
    rewrite_sites_block(yaml_path, {code: entry})
    print(f"{'refreshed' if held else 'added'} {code} in {yaml_path}: {entry}")
    try:
        Survey.from_yaml(yaml_path).instrument_of(code)
    except ValueError as exc:
        print(f"  WARNING mtproc.survey does not know this site's instrument yet ({exc}); the GUI's "
              f"Metadata tab will fail on this survey until it does")
    return 0


if __name__ == "__main__":
    sys.exit(main())
