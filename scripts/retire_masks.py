# -*- coding: utf-8 -*-
"""
Move masks.yaml entries of a site to masks_history.yaml, or back

A mask that is no longer wanted, replaced by a narrower one or found wrong,
is kept rather than deleted: this script moves the entries of one site that
match every selector given from the site's block of `<survey>/masks.yaml`
to the end of its block of `<survey>/masks_history.yaml`, each keeping its
keys and gaining ``retired: {on: <today>, why: <--why>}``
(`mt_workbench.masks.retire_masks`). With `--restore` it moves the matching
entries of the history back into masks.yaml without the `retired` record
(`mt_workbench.masks.restore_masks`). Both files are replaced atomically, so a
campaign runner reading masks.yaml at a job start sees the old file or the
new one.

The selectors are AND-ed; an entry must match every one given, and with
none given every entry of the site is selected:

- `--found-by LIST`: its found_by is one of a comma list (time, polar,
  cluster, night, gate);
- `--scope LIST`: its scope is one of a comma list (local, both, remote);
- `--bands all|limited`: its bands are all, or a [pmin, pmax] limit;
- `--reason-contains TEXT`: its reason holds TEXT, ignoring case;
- `--before ISO`: it ends at or before the time (UTC);
- `--after ISO`: it starts at or after the time (UTC);
- `--overlapping ISO..ISO`: it overlaps the interval [a, b).

Each selected entry is printed on one line (start, end, bands, found_by,
scope, channels, reason), then the counts of the site's entries in both
files before and after the move. `--dry-run` prints the same and moves
nothing. `--why` is required when retiring; with `--restore` it is
optional and only printed. Exit status: 0 moved (or would move), 2 when
nothing is selected or an argument is malformed.

Usage:
    python scripts/retire_masks.py <survey.yaml> <site> [--found-by LIST] [--scope LIST]
        [--bands all|limited] [--reason-contains TEXT] [--before ISO] [--after ISO]
        [--overlapping ISO..ISO] [--restore] --why TEXT [--dry-run]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from loguru import logger  # noqa: E402

from mt_workbench.masks import (  # noqa: E402
    FOUND_BY, SCOPES, history_path, load_history, load_masks, masks_path, restore_masks, retire_masks, utc,
)

BANDS = ("all", "limited")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of retire_masks.py."""
    p = argparse.ArgumentParser(
        prog="retire_masks.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("site")
    p.add_argument("--found-by", default=None, metavar="LIST",
                   help="a comma list of origins: " + ", ".join(FOUND_BY))
    p.add_argument("--scope", default=None, metavar="LIST", help="a comma list of scopes: " + ", ".join(SCOPES))
    p.add_argument("--bands", choices=BANDS, default=None, help="all: bands all; limited: a [pmin, pmax] limit")
    p.add_argument("--reason-contains", default=None, metavar="TEXT", help="the reason holds TEXT (any case)")
    p.add_argument("--before", default=None, metavar="ISO", help="the entry ends at or before this UTC time")
    p.add_argument("--after", default=None, metavar="ISO", help="the entry starts at or after this UTC time")
    p.add_argument("--overlapping", default=None, metavar="ISO..ISO", help="the entry overlaps [a, b), UTC")
    p.add_argument("--restore", action="store_true",
                   help="move the selected entries of masks_history.yaml back into masks.yaml")
    p.add_argument("--why", default=None, metavar="TEXT",
                   help="why the entries are retired (required unless --restore)")
    p.add_argument("--dry-run", action="store_true", help="print the selection and the counts; move nothing")
    return p


def _names(text: str | None, allowed, flag: str) -> set[str] | None:
    """Parse a comma list of names drawn from `allowed`; None when the flag is not given."""
    if text is None:
        return None
    names = {s.strip() for s in text.split(",") if s.strip()}
    unknown = sorted(names - set(allowed))
    if unknown or not names:
        raise ValueError(f"{flag} takes a comma list of {', '.join(allowed)}; given {text!r}")
    return names


def selector(args):
    """Return a function that is True for an entry matching every selector given.

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        callable: Takes a normalised mask, returns bool.

    Raises:
        ValueError: If a list names an unknown value, a time does not
            parse, or --overlapping is not ``a..b`` with b after a.
    """
    found_by = _names(args.found_by, FOUND_BY, "--found-by")
    scopes = _names(args.scope, SCOPES, "--scope")
    before = utc(args.before) if args.before else None
    after = utc(args.after) if args.after else None
    span = None
    if args.overlapping:
        parts = args.overlapping.split("..")
        if len(parts) != 2:
            raise ValueError(f"--overlapping takes ISO..ISO; given {args.overlapping!r}")
        span = (utc(parts[0]), utc(parts[1]))
        if span[1] <= span[0]:
            raise ValueError(f"--overlapping {args.overlapping}: the end is not after the start")
    text = args.reason_contains.lower() if args.reason_contains else None

    def pick(m: dict) -> bool:
        if found_by is not None and m["found_by"] not in found_by:
            return False
        if scopes is not None and m["scope"] not in scopes:
            return False
        if args.bands == "all" and m["bands"] != "all":
            return False
        if args.bands == "limited" and m["bands"] == "all":
            return False
        if text is not None and text not in m["reason"].lower():
            return False
        start, end = utc(m["start"]), utc(m["end"])
        if before is not None and end > before:
            return False
        if after is not None and start < after:
            return False
        if span is not None and not (start < span[1] and end > span[0]):
            return False
        return True

    return pick


def entry_line(m: dict) -> str:
    """Format one entry on one line: start, end, bands, found_by, scope, channels, reason."""
    bands = "all" if m["bands"] == "all" else f"[{m['bands'][0]:g}, {m['bands'][1]:g}]"
    channels = m.get("channels", "all")
    channels = channels if channels == "all" else "[" + ", ".join(channels) + "]"
    return (f"  {m['start']}  {m['end']}  bands {bands}  found_by {m['found_by']}  scope {m['scope']}  "
            f"channels {channels}  {m['reason']}")


def main(argv=None) -> int:
    """Select, print and move a site's entries.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 when entries were moved (or would be, with --dry-run); 2 when
        nothing was selected or an argument was malformed.
    """
    args = build_parser().parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    if not args.restore and not (args.why or "").strip():
        print("ERROR --why is required when retiring entries", file=sys.stderr)
        return 2
    try:
        pick = selector(args)
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    survey, site = args.survey_yaml, args.site
    masks, history = load_masks(survey, site), load_history(survey, site)
    source = history if args.restore else masks
    chosen = [m for m in source if pick(m)]
    where = (f"{history_path(survey).name} -> {masks_path(survey).name}" if args.restore
             else f"{masks_path(survey).name} -> {history_path(survey).name}")
    if not chosen:
        print(f"{site}: no entry of {history_path(survey).name if args.restore else masks_path(survey).name} "
              f"matches the selectors ({len(source)} entries there): nothing moved")
        return 2
    verb = {(True, True): "would be restored", (True, False): "restored",
            (False, True): "would be retired", (False, False): "retired"}[(args.restore, args.dry_run)]
    print(f"{site}: {len(chosen)} entr{'y' if len(chosen) == 1 else 'ies'} {verb} ({where})"
          + (f", why: {args.why}" if args.why else ""))
    for m in chosen:
        print(entry_line(m))
    before = (len(masks), len(history))
    if args.dry_run:
        after = ((before[0] + len(chosen), before[1] - len(chosen)) if args.restore
                 else (before[0] - len(chosen), before[1] + len(chosen)))
    else:
        if args.restore:
            restore_masks(survey, site, pick)
        else:
            retire_masks(survey, site, pick, args.why)
        after = (len(load_masks(survey, site)), len(load_history(survey, site)))
    print(f"{site}: {masks_path(survey).name} {before[0]} -> {after[0]}, "
          f"{history_path(survey).name} {before[1]} -> {after[1]}" + (" (dry run: nothing moved)" if args.dry_run
                                                                       else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
