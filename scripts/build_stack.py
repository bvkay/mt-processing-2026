"""Build a synthetic (stacked) remote reference from concurrent sites.

Usage:
    python scripts/build_stack.py <survey.yaml> <name> <start> <end> <member> [<member> ...]
        [--weighting {none,coherence}] [--check]
    (each <member> is read from its archive <workspace>/mth5/<member>.h5)

The stack is built from the members' hx/hy counts as their MTH5 archives hold
them (scripts/ingest_site.py, or "Build MTH5" on the GUI's Time Series tab:
a member without one stops the build), i.e. exactly as processing sees each
member -- its declared filters from <survey>/filters.yaml were applied at
ingest and are not applied again. Each member contributes the run that
overlaps [start, end) most; the stack spans those runs' intersection with
[start, end), read in 10-minute chunks: only the two output coils are held
whole (ten members over 36 h peak at about 2.7 GB). No calibration is
needed because the remote-reference estimator is invariant to any linear
transform of the remote. Writes <workspace>/mth5/<name>.h5; process it as the remote with
scripts/process_rr.py <survey.yaml> <local> <name>.

--weighting none (the default) is the plain mean of the members. One dead
channel poisons a mean, so check the members first: --check prints, per
member and coil, the squared coherence with the plain mean of the other
members (per 10-minute chunk, 0.1-1 s, 1-10 s and 0.1-10 s) and writes
nothing; leave out a coil that sits near zero.

--weighting coherence weights each member, per 10-minute chunk and coil, by
that coherence over 0.1-10 s, normalised per chunk, dropping a member under
0.05 in a chunk (mtproc.virtual's module docstring has the rule; the archive's
run and channel comments record it and the weights), and prints the
per-member table of mean weights per coil.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc.survey import Survey
from mtproc.virtual import CHECK_BANDS_S, WEIGHTINGS, build_synthetic_remote, check_members


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_stack.py",
        description=__doc__.split("\n\nUsage:")[0],
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
    return f"{b[0]:g}-{b[1]:g} s"


def print_check(result: dict) -> None:
    """Per member and coil: median (and 10th percentile) gamma2 over chunks, each band."""
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
    """Per member: mean weight, chunks dropped and median gamma2 (0.1-10 s), per coil."""
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
