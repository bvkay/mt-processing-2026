"""Band-averaged coherence QC for a local/remote pair, on the processing bands.

The general form of examples/03_coherence_d02.py. Plots, on the TF plots'
period axis:

- local E-H coherence (ex-hy, ey-hx): signal quality at the local site
- local-vs-remote magnetics coherence (hx, hy): what the remote reference sees
- local-vs-stack magnetics coherence (hx, hy), when --stack is given

If a stack is doing its job its curves sit above the single remote's wherever
sensor noise matters; the dead band should dip in everything.

Reads the MTH5s already in <workspace>/mth5 (ingest first). Local and remote
each use whichever of their runs overlaps the other the most (`best_overlap_runs`);
a station split into several runs (e.g. by a file-timing anomaly) is not
reduced to its single longest run before checking overlap. When --stack is
given, the stack's run is chosen to best overlap the local run already chosen
against the remote, not re-optimised against the stack independently.

Usage:
    python scripts/coherence_qc.py <survey.yaml> <local> <remote> [--stack NAME] [--out PNG]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc.bands import lemimt_band_scheme
from mtproc.qc import align, band_coherence, best_overlap_runs, load_channel, run_periods
from mtproc.survey import Survey


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("local", help="local station name (MTH5 in <workspace>/mth5)")
    p.add_argument("remote", help="remote-reference station name")
    p.add_argument("--stack", metavar="NAME", help="also compare against this stacked remote")
    p.add_argument("--out", metavar="PNG", help="output figure path (default: <workspace>/qc/...)")
    return p.parse_args(argv)


def station_h5(survey: Survey, station: str) -> Path:
    h5 = survey.workspace / "mth5" / f"{station}.h5"
    if not h5.exists():
        raise FileNotFoundError(f"no MTH5 for station {station!r}: {h5}")
    return h5


def station_channels(survey: Survey, station: str, comps: list[str], run: str) -> dict:
    """Load the named components from one specific run of a station."""
    h5 = station_h5(survey, station)
    return {(station, comp): load_channel(h5, survey.name, station, run, comp) for comp in comps}


def best_run_against(period: tuple, mth5_path: Path, survey_name: str, station: str) -> tuple[str, float]:
    """Run id of `station` whose time period overlaps a fixed (start, end) the most."""
    best_run, best_overlap = None, -1.0
    for run_id, (s, e) in run_periods(mth5_path, survey_name, station).items():
        overlap = (min(e, period[1]) - max(s, period[0])).total_seconds()
        if overlap > best_overlap:
            best_run, best_overlap = run_id, overlap
    return best_run, best_overlap


def main(argv=None) -> None:
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)

    local_h5 = station_h5(survey, args.local)
    remote_h5 = station_h5(survey, args.remote)
    local_run, remote_run, overlap_lr = best_overlap_runs(
        local_h5, survey.name, args.local, remote_h5, args.remote
    )
    logger.info(
        f"{args.local}[{local_run}] vs {args.remote}[{remote_run}]: "
        f"overlap {overlap_lr / 3600:.2f} h"
    )

    chans = {}
    chans.update(station_channels(survey, args.local, ["ex", "ey", "hx", "hy"], local_run))
    chans.update(station_channels(survey, args.remote, ["hx", "hy"], remote_run))

    if args.stack:
        stack_h5 = station_h5(survey, args.stack)
        local_period = run_periods(local_h5, survey.name, args.local)[local_run]
        stack_run, overlap_ls = best_run_against(local_period, stack_h5, survey.name, args.stack)
        logger.info(
            f"{args.stack}[{stack_run}]: overlap with {args.local}[{local_run}] "
            f"{overlap_ls / 3600:.2f} h"
        )
        chans.update(station_channels(survey, args.stack, ["hx", "hy"], stack_run))

    keys = list(chans.keys())
    data = dict(zip(keys, align([chans[k] for k in keys])))
    sr = survey.sample_rate

    pairs = [
        ((args.local, "ex"), (args.local, "hy"), f"{args.local} ex-hy (local)", "0.15", "-"),
        ((args.local, "ey"), (args.local, "hx"), f"{args.local} ey-hx (local)", "0.15", "--"),
        ((args.local, "hx"), (args.remote, "hx"), f"hx: {args.local}-{args.remote}", "C2", "-"),
        ((args.local, "hy"), (args.remote, "hy"), f"hy: {args.local}-{args.remote}", "C2", "--"),
    ]
    if args.stack:
        pairs += [
            ((args.local, "hx"), (args.stack, "hx"), f"hx: {args.local}-stack", "C1", "-"),
            ((args.local, "hy"), (args.stack, "hy"), f"hy: {args.local}-stack", "C1", "--"),
        ]

    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    for a, b, label, colour, ls in pairs:
        p, g2 = band_coherence(data[a].copy(), data[b].copy(), sr, scheme)
        ax.semilogx(p, g2, color=colour, ls=ls, lw=1.3, label=label)
        print(f"{label}: min gamma2 {g2.min():.2f} at {p[g2.argmin()]:.3g} s")

    ax.set_xlabel("period (s)")
    ax.set_ylabel(r"band-averaged $\gamma^2$")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=9, ncol=2, loc="lower left")
    ax.set_title(f"{args.local}: coherence across processing bands")

    out = Path(args.out) if args.out else (
        survey.workspace / "qc" / f"{args.local}_rr-{args.remote}_band_coherence.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"coherence figure: {out}")


if __name__ == "__main__":
    main()
