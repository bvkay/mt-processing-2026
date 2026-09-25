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
2.7 GB). No calibration is needed because the remote-reference estimator is
invariant to any linear transform of the remote. The script writes
<workspace>/mth5/<name>.h5; process it as the remote with
scripts/process_rr.py <survey.yaml> <local> <name>.

--weighting none (the default) is the plain mean of the members. One dead
channel spoils a mean, so check the members first: --check prints, per
member and coil, the squared coherence with the plain mean of the other
members (per 10-minute chunk, 0.1-1 s, 1-10 s and 0.1-10 s) and writes
nothing. Leave out a coil that sits near zero.

--weighting coherence weights each member, per 10-minute chunk and coil, by
that coherence over 0.1-10 s, normalised per chunk, and drops a member under
0.05 in a chunk. The rule is described in the crust.virtual module
docstring; the archive's run and channel comments record it and the weights.
The script prints the per-member table of mean weights per coil.

Usage:
    python scripts/build_stack.py <survey.yaml> <name> <start> <end> <member> [<member> ...]
        [--weighting {none,coherence}] [--check]
    (each <member> is read from its archive <workspace>/mth5/<member>.h5)

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.survey import Survey
from crust.virtual import CHECK_BANDS_S, WEIGHTINGS, build_synthetic_remote, check_members


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of build_stack.py."""
    p = argparse.ArgumentParser(
        prog="build_stack.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("name", help="stack name; the archive is <workspace>/mth5/<name>.h5")
    p.add_argument("start", help='UTC, e.g. "2023-09-19 19:02"')
    p.add_argument("end", help="UTC")
    p.add_argument("members", nargs="+",
                   help="member sites (at least two), each read from <workspace>/mth5/<site>.h5")
    p.add_argument("--weighting", choices=WEIGHTINGS, default="none",
                   help="none: plain mean (default); coherence: chunk-wise coherence weights")
    p.add_argument("--check", action="store_true",
                   help="print each member's coherence with the mean of the others and exit")
    return p


def _band(b) -> str:
    """Format a (short, long) period band in seconds as "a-b s"."""
    return f"{b[0]:g}-{b[1]:g} s"


def print_check(result: dict) -> None:
    """Print the member check as one table per coil.

    Each cell is the median (and 10th percentile) over chunks of a member's
    squared coherence with the mean of the other members, per check band.

    Args:
        result (dict): Output of `crust.virtual.check_members`, keyed by
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
            `crust.virtual.build_synthetic_remote`, keyed by coil.
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


def main(argv=None) -> None:
    """Check the members or build the stack.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.
    """
    args = build_parser().parse_args(argv)
    if len(args.members) < 2:
        sys.exit("give at least two members")
    survey = Survey.from_yaml(args.survey_yaml)
    t0 = time.time()
    if args.check:
        print_check(check_members(survey, list(args.members), args.start, args.end, name=args.name))
        print(f"\ncheck of {', '.join(args.members)}: {time.time() - t0:.0f} s")
        return
    weights: dict = {}
    out = build_synthetic_remote(survey, list(args.members), args.start, args.end, name=args.name,
                                 weighting=args.weighting, weights_out=weights)
    if weights:
        print_weights(weights)
    print(f"stack {args.name} ({args.weighting}) <- {', '.join(args.members)}: {out} "
          f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
