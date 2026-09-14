"""Band-averaged coherence QC for D02: local signal + both remotes.

Plots, on the TF plots' period axis:
- local E-H coherence (ex-hy, ey-hx): signal quality at D02
- inter-station magnetics coherence D02 vs E08 (single remote)
- inter-station magnetics coherence D02 vs SYN01 (stacked remote)

If the stack is doing its job, D02-SYN coherence sits above D02-E08 wherever
single-remote sensor noise matters; the dead band should dip in everything.

Run after examples/01 and /02 (uses their MTH5s).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mtproc.bands import lemimt_band_scheme
from mtproc.qc import align, band_coherence, load_channel, longest_run
from mtproc.survey import Survey

SURVEY_YAML = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
LOCAL, REMOTE, SYN = "D02", "E08", "SYN01"


def main() -> None:
    survey = Survey.from_yaml(SURVEY_YAML)
    scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)
    mth5_dir = survey.workspace / "mth5"

    chans = {}
    for station, comps in [(LOCAL, ["ex", "ey", "hx", "hy"]), (REMOTE, ["hx", "hy"]), (SYN, ["hx", "hy"])]:
        h5 = mth5_dir / f"{station}.h5"
        run = longest_run(h5, survey.name, station)
        for comp in comps:
            chans[(station, comp)] = load_channel(h5, survey.name, station, run, comp)

    keys = list(chans.keys())
    aligned = align([chans[k] for k in keys])
    data = dict(zip(keys, aligned))
    sr = survey.sample_rate

    pairs = [
        ((LOCAL, "ex"), (LOCAL, "hy"), f"{LOCAL} ex-hy (local)", "0.15", "-"),
        ((LOCAL, "ey"), (LOCAL, "hx"), f"{LOCAL} ey-hx (local)", "0.15", "--"),
        ((LOCAL, "hx"), (REMOTE, "hx"), f"hx: {LOCAL}-{REMOTE}", "C2", "-"),
        ((LOCAL, "hy"), (REMOTE, "hy"), f"hy: {LOCAL}-{REMOTE}", "C2", "--"),
        ((LOCAL, "hx"), (SYN, "hx"), f"hx: {LOCAL}-stack", "C1", "-"),
        ((LOCAL, "hy"), (SYN, "hy"), f"hy: {LOCAL}-stack", "C1", "--"),
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
    ax.set_title(f"{LOCAL}: coherence across processing bands")

    out = survey.workspace / "qc" / f"{LOCAL}_band_coherence.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"coherence figure: {out}")


if __name__ == "__main__":
    main()
