# -*- coding: utf-8 -*-
"""
Build a synthetic (stacked) remote reference from concurrent sites

The stack is built from the members' hx/hy counts as their MTH5 archives hold
them, which is how processing sees each member: declared filters from
<survey>/filters.yaml were applied at ingest and are not applied again. Each
member needs an archive (scripts/ingest_site.py, or "Build MTH5" on the Time
Series tab of the GUI); a missing one stops the build. Each member
contributes the run that overlaps [start, end) most. The stack spans those
runs' intersection with [start, end) and is read in 10-minute chunks, with
only the two output coils held whole (ten members over 36 h peak at about
2.7 GB). --min-piece-h H builds it per piece instead (positional form only):
every run of every member is taken, and each stretch of [start, end) in
which every member is inside one of its runs becomes one run of the stack
archive when it lasts at least H hours (`mt_workbench.virtual.stack_pieces`),
so a member with a gap or a restart costs the stack that gap only; the
pieces kept and left out are printed. scripts/campaign.py builds its stage
2 stacks with --min-piece-h 6. The stack's hx and hy carry the members'
common filter chain and units (the first member's; a member whose response
differs from it by a constant is scaled onto it, a member whose response
differs in shape refuses the build: Calibration in the `mt_workbench.virtual`
docstring), so a transfer function estimated against the stack carries
errors in physical units, as against a single calibrated remote; members
with no chain give an uncalibrated stack and a warning (upstream issues 111
and 116: the remote-reference estimate is invariant to the remote's
calibration, its errors are not). A member with no chain beside members
with one, whose samples are in the units the others' chain calibrates to (an
INTERMAGNET observatory in nanoTesla beside EDL sites), is taken as an
identity chain and scaled onto the reference's chain when that chain is a
real constant, and the printout and run comment say "member CNB: no filter
chain, samples in nanoTesla taken as calibrated"; in other units, or beside
a chain that varies with frequency, it refuses the build. The chain each coil carries and every
member's scale are printed and written to the run comment. The script
writes <workspace>/mth5/<name>.h5; process it as the remote with
scripts/process_rr.py <survey.yaml> <local> <name>.

--weighting none (the default) is the plain mean of the members. One dead
channel spoils a mean, so check the members first: --check prints, per
member and coil, the squared coherence with the plain mean of the other
members (per 10-minute chunk, 0.1-1 s, 1-10 s and 0.1-10 s) and writes
nothing. Leave out a coil that sits near zero.

--weighting coherence weights each member, per 10-minute chunk and coil, by
that coherence over 0.1-10 s, normalised per chunk, and drops a member under
0.05 in a chunk. The rule is described in the mt_workbench.virtual module
docstring; the archive's run and channel comments record it and the weights.
The script prints the per-member table of mean weights per coil.

Recipes. --recipe NAME builds a time recipe of the survey's stacks.yaml
(`mt_workbench.stacks`, which the GUI's Stacks tab writes: method time_mean
or time_coherence, use remote, an explicit member list and a window) in
place of the positional name, window and members, which are then refused,
as is --weighting (the recipe's method sets it). The members are the
listed sites whose single run overlapping the window most covers it less
60 s (`mt_workbench.stacks.resolve_members`, as `mt_workbench.virtual`
builds from one run per member); a listed site that does not is named with
its reason, and fewer than two members stop the build. A band recipe is
refused: scripts/process_intersite.py --stack NAME forms it inside each run.

A recipe build records its recipe (name, hash, canonical text), its
members and each member's processing-archive identity
(`mt_workbench.ingest.archive_identity`) in the archive (Provenance in the
`mt_workbench.virtual` docstring). An existing <workspace>/mth5/NAME.h5 is
reused only when it records the recipe's hash, the same members and the
same identities, so a member archive rebuilt since (a re-ingest with swap_h,
flip_h or h_from, or a changed filters.yaml that rebuilds a variant) makes
the archive stale; a stale archive exits 2 naming the first difference,
and --overwrite rebuilds it (an archive that answers its recipe is still
reused). An existing NAME.h5 that records no recipe (a positional build,
or campaign.py's STK_<site>u and STK_<site>w, from which process_rr
products may have been made) is never replaced: it exits 2 even with
--overwrite, asking for another recipe name or for the archive to be
moved aside. The build is written into <workspace>/mth5/.build_<pid>/, its run
is checked to start no later than the window's start plus 60 s and to end
no earlier than its end less 60 s, and only then is it moved onto NAME.h5,
so a build that fails leaves the previous NAME.h5 unchanged. The folder
is removed whatever happens; a folder left by a killed build is named in
the next summary, to be removed by hand. --check with a recipe prints the
member check of the resolved members over the recipe's window and writes
nothing.

Each member is read from its processing archive
(`mt_workbench.ingest.processing_archive`): its filtered variant when it
declares filters, built first when missing or stale, else its raw archive.

Usage:
    python scripts/build_stack.py <survey.yaml> <name> <start> <end> <member> [<member> ...]
        [--weighting {none,coherence}] [--min-piece-h H] [--check]
    python scripts/build_stack.py <survey.yaml> --recipe NAME [--overwrite] [--check]
    (each <member> is read from its processing archive under <workspace>/mth5)

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench import intersite, stacks
from mt_workbench.ingest import archive_identity, processing_archive
from mt_workbench.masks import REPLACE_TRIES
from mt_workbench.survey import Survey
from mt_workbench.virtual import (CHECK_BANDS_S, COILS, WEIGHTINGS, build_synthetic_remote, check_members,
                                  recorded_provenance)
from mth5.utils.exceptions import MTH5Error

# what reading a member's archive can raise besides a refusal: a missing file, a bad value, or mth5's own error
# (for example an archive whose survey group is not survey.yaml's name)
READ_ERRORS = (FileNotFoundError, ValueError, OSError, KeyError, MTH5Error)

BUILD_PREFIX = ".build_"  # <workspace>/mth5/.build_<pid>/: a recipe build before it replaces NAME.h5
REPLACE_WAIT_S = 0.1  # between tries of the final os.replace, which Windows refuses while the target is open


class Refused(ValueError):
    """A recipe build that cannot go ahead as asked (exit 2)."""


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of build_stack.py."""
    p = argparse.ArgumentParser(
        prog="build_stack.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("name", nargs="?", default=None,
                   help="stack name; the archive is <workspace>/mth5/<name>.h5 (not with --recipe)")
    p.add_argument("start", nargs="?", default=None, help='UTC, e.g. "2023-09-19 19:02" (not with --recipe)')
    p.add_argument("end", nargs="?", default=None, help="UTC (not with --recipe)")
    p.add_argument("members", nargs="*", default=[],
                   help="member sites (at least two), each read from its processing archive (not with --recipe)")
    p.add_argument("--weighting", choices=WEIGHTINGS, default=None,
                   help="none: plain mean (default); coherence: chunk-wise coherence weights (not with --recipe, "
                        "whose method sets it)")
    p.add_argument("--recipe", default=None, metavar="NAME",
                   help="build the time recipe NAME of the survey's stacks.yaml: its members, window and method")
    p.add_argument("--overwrite", action="store_true",
                   help="with --recipe: rebuild NAME.h5 when it does not answer the recipe and its member "
                        "archives (without it such an archive exits 2)")
    p.add_argument("--check", action="store_true",
                   help="print each member's coherence with the mean of the others and exit")
    p.add_argument("--min-piece-h", type=float, default=None, metavar="H",
                   help="build per piece: every stretch of the window in which every member is inside one of its "
                        "runs and that lasts H hours or more becomes one run of the stack (positional form only; "
                        "not with --check)")
    return p


def _band(b) -> str:
    """Format a (short, long) period band in seconds as "a-b s"."""
    return f"{b[0]:g}-{b[1]:g} s"


def print_check(result: dict) -> None:
    """Print the member check as one table per coil.

    Each cell is the median (and 10th percentile) over chunks of a member's
    squared coherence with the mean of the other members, per check band.

    Args:
        result (dict): Output of `mt_workbench.virtual.check_members`, keyed by
            coil.
    """
    for comp, info in result.items():
        n_chunks = len(info["chunk_starts"])
        print(f"\n{comp}: gamma2 with the mean of the other members, median [10th pct] "
              f"over {n_chunks} chunks")
        print(f"{'member':>8}  " + "  ".join(f"{_band(b):>16}" for b in CHECK_BANDS_S))
        for i, m in enumerate(info["members"]):
            cells = []
            for b in CHECK_BANDS_S:
                g = info["bands"][b][i]
                cells.append(f"{np.nanmedian(g):.3f} [{np.nanpercentile(g, 10):.3f}]")
            print(f"{m:>8}  " + "  ".join(f"{c:>16}" for c in cells))


def print_weights(weights: dict) -> None:
    """Print the stack weights of each member per coil.

    The columns per coil are the mean weight, the number of chunks dropped
    (weight 0) and the median squared coherence over chunks (0.1-10 s).

    Args:
        weights (dict): Weights filled in by
            `mt_workbench.virtual.build_synthetic_remote`, keyed by coil.
    """
    comps = list(weights)
    members = sorted({m for info in weights.values() for m in info["members"]})
    n_chunks = len(next(iter(weights.values()))["chunk_starts"])
    head = "  ".join(f"{c + ' mean w':>10}  {c + ' dropped':>10}  {c + ' gamma2':>10}" for c in comps)
    print(f"\nstack weights over {n_chunks} chunks (gamma2: median over chunks, 0.1-10 s)")
    print(f"{'member':>8}  {head}")
    for m in members:
        cells = []
        for c in comps:
            info = weights[c]
            if m not in info["members"]:
                cells.append(f"{'-':>10}  {'-':>10}  {'-':>10}")
                continue
            i = info["members"].index(m)
            w = info["weights"][i]
            cells.append(f"{w.mean():>10.3f}  {int((w == 0).sum()):>10d}  "
                         f"{np.nanmedian(info['gamma2'][i]):>10.3f}")
        print(f"{m:>8}  " + "  ".join(cells))


def print_calibration(calibration: dict) -> None:
    """Print the chain each coil of the built stack carries and the scale applied to each member.

    Args:
        calibration (dict): Filled in by
            `mt_workbench.virtual.build_synthetic_remote(calibration_out=...)`,
            keyed by coil; None for a coil written uncalibrated.
    """
    for comp in COILS:
        cal = calibration.get(comp)
        if cal is None:
            print(f"{comp}: uncalibrated (no member carries a filter chain; upstream issue 111)")
            continue
        scales = ", ".join(f"{m} x{s:.9g}" for m, s in cal["scales"].items())
        print(f"{comp}: chain of {cal['reference']} ({', '.join(cal['names'])}) in {cal['units']}; scales {scales}"
              + "".join(f"; member {m}: no filter chain, samples in {u} taken as calibrated"
                        for m, u in (cal.get("identity") or {}).items()))


def _text_ns(ns: int) -> str:
    """Format ns since the epoch as 2023-09-19T19:02:00Z."""
    return pd.Timestamp(int(ns), unit="ns", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def built_span_short(path, name: str, lo_ns: int, hi_ns: int) -> str | None:
    """Say why a built stack does not span its recipe's window, or return None when it does.

    The stack's run must start no later than the window's start plus
    `mt_workbench.intersite.MEMBER_EDGE_S` and end (its last sample) no
    earlier than the window's end less it: the slack the member rule gives
    each member's run (`mt_workbench.stacks.resolve_members`). A stack that
    falls short was built from processing archives whose runs differ from
    the raw archives' the members were judged on.

    Args:
        path: The built archive.
        name (str): Its station (the recipe's name).
        lo_ns, hi_ns (int): The recipe's window, ns since the epoch.

    Returns:
        str or None: The reason, naming the span and the shortfall; None
        when the span holds the window to within the edge.
    """
    runs = intersite.archive_runs(path, name, COILS)
    if not runs:
        return f"{name}: the built archive holds no run with {'/'.join(COILS)}"
    start, end = min(s for s, _e in runs), max(e for _s, e in runs)
    edge = int(round(intersite.MEMBER_EDGE_S * 1e9))
    short = []
    if start > lo_ns + edge:
        short.append(f"starts {(start - lo_ns) / 1e9:.3f} s after the window's start")
    if end < hi_ns - edge:
        short.append(f"ends {(hi_ns - end) / 1e9:.3f} s before the window's end")
    if not short:
        return None
    return (f"{name}: the built stack spans {_text_ns(start)} to {_text_ns(end)} and " + " and ".join(short)
            + f" (at most {intersite.MEMBER_EDGE_S:g} s each)")


def _member_runs(survey: Survey, members, lo_ns: int, hi_ns: int, use_filters: bool) -> str:
    """Name each member's run in its processing archive that overlaps the window most."""
    out = []
    for site in members:
        path = processing_archive(survey, site, use_filters)
        best = stacks.best_run(intersite.archive_runs(path, site, COILS), lo_ns, hi_ns)
        out.append(f"{site} ({path.name}) " + (f"{_text_ns(best[0][0])} to {_text_ns(best[0][1])}" if best
                                                else "no run overlapping the window"))
    return "; ".join(out)


def provenance_difference(recorded: dict | None, wanted: dict) -> str | None:
    """Return the first way an archive's recorded provenance differs from a build's, or None when it answers it.

    Args:
        recorded (dict or None): `mt_workbench.virtual.recorded_provenance`
            of the existing archive.
        wanted (dict): The provenance this build would record: the
            recipe's (`mt_workbench.stacks.provenance`) plus ``members`` and
            ``sources``.

    Returns:
        str or None: The recipe hash, then the member list, then each
        member's archive identity, in that order; None when all match.
    """
    if recorded is None:
        return "no provenance recorded (an archive not built from a recipe)"
    if recorded.get("recipe_hash") != wanted["recipe_hash"]:
        return f"recipe hash {recorded.get('recipe_hash')}, the recipe is now {wanted['recipe_hash']}"
    old, new = set(recorded.get("members") or ()), set(wanted["members"])
    if old != new:
        changes = [f"+{s}" for s in sorted(new - old)] + [f"-{s}" for s in sorted(old - new)]
        return "members differ: " + " ".join(changes)
    sources = recorded.get("sources") or {}
    for site in wanted["members"]:
        if sources.get(site) != wanted["sources"][site]:
            return (f"{site}'s archive changed since the build (recorded {sources.get(site)}; now "
                    f"{wanted['sources'][site]})")
    return None


def _replace(built: Path, target: Path) -> None:
    """Move the built archive onto the target, trying `REPLACE_TRIES` times while Windows holds the target open.

    Raises:
        Refused: When the target stays held open; it is unchanged.
    """
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(built, target)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise Refused(f"{target.name} is held open by another program; nothing replaced (the new build "
                              f"is discarded)") from None
            time.sleep(REPLACE_WAIT_S)


def recipe_build(args) -> Path | None:
    """Check or build the time recipe `args.recipe`.

    Args:
        args (argparse.Namespace): Parsed arguments, with ``recipe`` set.

    Returns:
        Path or None: The archive (built or reused); None with --check.

    Raises:
        Refused: For positionals or --weighting beside --recipe, a recipe
            stacks.yaml does not hold or that is invalid, a band recipe, a
            recipe named as a site, fewer than two members, a member whose
            processing archive cannot be had or read (an mth5 error
            included), an existing archive that records no recipe (with or
            without --overwrite), an existing archive that does not answer
            the recipe (without --overwrite), a build that fails or falls
            short of the window, and a target held open.
    """
    given = [v for v in (args.name, args.start, args.end) if v is not None] + list(args.members)
    if given:
        raise Refused(f"--recipe {args.recipe} takes the name, the window and the members from stacks.yaml; "
                      f"positionals given: {' '.join(given)}")
    if args.weighting is not None:
        raise Refused(f"--recipe {args.recipe}: the recipe's method sets the weighting; --weighting goes with the "
                      f"positional form")
    survey = Survey.from_yaml(args.survey_yaml)
    try:
        recipe = stacks.load_recipe(survey, args.recipe)
    except stacks.StacksError as exc:
        raise Refused(str(exc)) from None
    except OSError as exc:
        raise Refused(f"{args.recipe}: {stacks.stacks_path(survey)} cannot be read ({exc})") from None
    method = stacks.METHODS[recipe.method]
    if method.engine != "time":
        raise Refused(f"{recipe.name} is a band recipe ({recipe.method}, use {recipe.use}): it is formed inside each "
                      f"run of scripts/process_intersite.py --stack {recipe.name}, not built as an archive")
    try:
        raw_folders = survey.site_dirs()
    except OSError:  # data_root on a drive that is not plugged in
        raw_folders = {}
    if recipe.name in survey.site_names() or recipe.name in raw_folders:
        raise Refused(f"{recipe.name} is a site of the survey: its archive would be replaced; rename the recipe")
    lo, hi = recipe.window_ns
    try:
        members, left_out = stacks.resolve_members(recipe, survey)
    except stacks.StacksError as exc:
        raise Refused(str(exc)) from None
    names = sorted(m["site"] for m in members)
    listed_out = [x for x in left_out if x["reason"] != stacks.NOT_LISTED]
    print(f"recipe: {recipe.name} ({recipe.method}, recipe hash {stacks.recipe_hash(recipe)}), window "
          f"{_text_ns(lo)} to {_text_ns(hi)}")
    for m in members:
        print(f"member: {m['site']} {m['overlap_h']:.2f} h of the window in one run")
    for x in listed_out:
        print(f"left_out: {x['site']} ({x['reason']})")
    if len(names) < 2:
        raise Refused(f"{recipe.name}: {len(names)} listed site(s) cover the window, fewer than two: " + "; ".join(
            f"{x['site']} {x['reason']}" for x in listed_out))
    if args.check:
        t0 = time.time()
        try:
            table = check_members(survey, names, recipe.start, recipe.end, name=recipe.name)
        except READ_ERRORS as exc:
            raise Refused(f"{recipe.name}: the check of {', '.join(names)} failed ({type(exc).__name__}: "
                          f"{exc}); nothing written") from None
        print_check(table)
        print(f"\ncheck of {', '.join(names)}: {time.time() - t0:.0f} s")
        return None
    sources = {}
    for site in names:
        try:
            sources[site] = archive_identity(processing_archive(survey, site, recipe.use_filters))
        except READ_ERRORS as exc:
            raise Refused(f"{recipe.name}: member {site}: {type(exc).__name__}: {exc}") from None
    provenance = dict(stacks.provenance(recipe), members=names, sources=sources)
    mth5_dir = survey.workspace / "mth5"
    target = mth5_dir / f"{recipe.name}.h5"
    tmp_dir = mth5_dir / f"{BUILD_PREFIX}{os.getpid()}"
    leftovers = sorted(p.name for p in mth5_dir.glob(f"{BUILD_PREFIX}*") if p.is_dir() and p != tmp_dir)
    if target.exists():
        recorded = recorded_provenance(target, survey.name, recipe.name)
        if recorded is None:
            # products may have been made from it (process_rr with it as the remote): never replaced by a recipe
            raise Refused(f"{target.name} was not built from a recipe (a campaign or hand build); rename the recipe "
                          f"or move the archive aside: {target} is unchanged")
        difference = provenance_difference(recorded, provenance)
        if difference is None:
            print(f"{target.name} holds recipe hash {provenance['recipe_hash']} from the same member archives: "
                  f"reused")
            _print_leftovers(mth5_dir, leftovers)
            return target
        if not args.overwrite:
            raise Refused(f"{target} does not answer {recipe.name}: {difference}; --overwrite rebuilds it")
        print(f"rebuilding {target.name}: {difference}")
    t0 = time.time()
    weights: dict = {}
    calibration: dict = {}
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            built = build_synthetic_remote(survey, names, recipe.start, recipe.end, name=recipe.name,
                                           out_path=tmp_dir / target.name, overwrite=True,
                                           weighting=method.weighting, weights_out=weights, provenance=provenance,
                                           calibration_out=calibration)
        except READ_ERRORS as exc:
            raise Refused(f"{recipe.name}: the build from {', '.join(names)} failed and {target.name} is unchanged: "
                          f"{type(exc).__name__}: {exc}") from None
        short = built_span_short(built, recipe.name, lo, hi)
        if short:
            raise Refused(f"{short}; each member's run overlapping the window most: "
                          f"{_member_runs(survey, names, lo, hi, recipe.use_filters)}; {target.name} is unchanged")
        _replace(built, target)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_dir.exists():
            print(f"WARNING {tmp_dir} could not be removed: remove it by hand", file=sys.stderr)
    if weights:
        print_weights(weights)
    if calibration:
        print_calibration(calibration)
    print(f"stack {recipe.name} ({recipe.method}, recipe hash {provenance['recipe_hash']}) <- {', '.join(names)}: "
          f"{target} ({time.time() - t0:.0f} s)")
    _print_leftovers(mth5_dir, leftovers)
    return target


def _print_leftovers(mth5_dir: Path, leftovers: list) -> None:
    """Name the build folders a killed build left behind, for removal by hand."""
    if leftovers:
        print(f"leftover build folders in {mth5_dir} (from builds that were stopped; remove them by hand): "
              f"{', '.join(leftovers)}")


def main(argv=None) -> None:
    """Check the members or build the stack.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.
    """
    parser = build_parser()
    args = parser.parse_intermixed_args(argv)
    if args.recipe is not None:
        if args.min_piece_h is not None:
            parser.error("--min-piece-h goes with the positional form: a recipe's window lies inside one run of "
                         "each member")
        try:
            recipe_build(args)
        except Refused as exc:
            print(f"ERROR {exc}", file=sys.stderr)
            raise SystemExit(2) from None
        return
    if args.overwrite:
        parser.error("--overwrite goes with --recipe")
    if args.name is None or args.start is None or args.end is None or not args.members:
        parser.error("the following arguments are required: name, start, end, members (or --recipe NAME)")
    if len(args.members) < 2:
        sys.exit("give at least two members")
    weighting = args.weighting or "none"
    if args.min_piece_h is not None and not args.min_piece_h > 0:
        parser.error(f"--min-piece-h takes a positive number of hours; given {args.min_piece_h:g}")
    if args.min_piece_h is not None and args.check:
        parser.error("--check reads one run per member; give it without --min-piece-h")
    survey = Survey.from_yaml(args.survey_yaml)
    t0 = time.time()
    if args.check:
        print_check(check_members(survey, list(args.members), args.start, args.end, name=args.name))
        print(f"\ncheck of {', '.join(args.members)}: {time.time() - t0:.0f} s")
        return
    weights: dict = {}
    pieces: list = []
    calibration: dict = {}
    out = build_synthetic_remote(survey, list(args.members), args.start, args.end, name=args.name,
                                 weighting=weighting, weights_out=weights, min_piece_h=args.min_piece_h,
                                 pieces_out=pieces, calibration_out=calibration)
    for k, piece in enumerate(pieces, 1):
        what = "run " + ", ".join(f"{s} {r}" for s, r in sorted(piece["runs"].items())) if piece["kept"] else (
            f"left out: under {args.min_piece_h:g} h")
        print(f"piece {k}: {piece['start']} to {piece['end']} ({piece['hours']:.2f} h) {what}")
    if pieces:
        kept = [p for p in pieces if p["kept"]]
        print(f"pieces: {len(kept)} kept, {sum(p['hours'] for p in kept):.2f} h; {len(pieces) - len(kept)} left out, "
              f"{sum(p['hours'] for p in pieces if not p['kept']):.2f} h")
    if weights:
        print_weights(weights)
    if calibration:
        print_calibration(calibration)
    print(f"stack {args.name} ({weighting}) <- {', '.join(args.members)}: {out} "
          f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
