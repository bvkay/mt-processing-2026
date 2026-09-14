"""Synthetic stacked remote reference test on D02.

Stacks raw hx/hy from five concurrent sites spread across the array
(deliberately excluding E08, the baseline remote) into a virtual station,
then compares: D02 RR-synthetic vs RR-E08 vs single-station vs the merged
lemimt EDI. The remote's calibration cancels in the RR estimator, so the
stack uses raw counts.

Run from the repo root after 01_validate_d02_e08.py (reuses its MTH5s and
RR-E08 EDI):  python examples/02_synthetic_remote_d02.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml

from mtproc.bands import lemimt_band_scheme
from mtproc.compare import plot_comparison
from mtproc.ingest import ingest_site
from mtproc.process import process_station
from mtproc.survey import Survey
from mtproc.virtual import build_synthetic_remote

SURVEY_YAML = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
REFERENCE_EDIS = SURVEY_YAML.parent / "reference_edis.yaml"
LOCAL = "D02"
# concurrent, well spread, no E08. A07 excluded: its hx is dead for this
# window (gamma2 = 0 vs E08 at all periods; see surveys/curnamona_cube/qc_notes.md)
MEMBERS = ["A05", "B06", "F08", "F09"]
START, END = "2021-06-29 06:00", "2021-07-01 00:00"


def main() -> None:
    survey = Survey.from_yaml(SURVEY_YAML)
    scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)
    tf_dir = survey.workspace / "tf"

    local_h5 = ingest_site(survey, LOCAL, start=START, end=END)
    syn_h5 = build_synthetic_remote(survey, MEMBERS, START, END, name="SYN01")

    tf_syn = process_station(
        local_h5, LOCAL, syn_h5, "SYN01", out_dir=tf_dir, band_scheme=scheme
    )
    if not (tf_dir / f"{LOCAL}_ss.edi").exists():
        process_station(local_h5, LOCAL, out_dir=tf_dir, band_scheme=scheme)

    baseline = None
    if REFERENCE_EDIS.exists():
        mapping = yaml.safe_load(REFERENCE_EDIS.read_text(encoding="utf-8")) or {}
        if LOCAL in mapping:
            baseline = mapping[LOCAL]["edi"]

    others = [(tf_dir / f"{LOCAL}_ss.edi", "single station", "0.5")]
    rr_e08 = tf_dir / f"{LOCAL}_rr-E08.edi"
    if rr_e08.exists():
        others.insert(0, (rr_e08, "RR E08", "C2"))

    out_png = tf_dir / f"{LOCAL}_synthetic_rr_comparison.png"
    plot_comparison(
        tf_syn,
        baseline=baseline,
        others=others,
        main_label=f"RR stack[{len(MEMBERS)}]",
        title=f"{LOCAL}: synthetic stacked remote ({'+'.join(MEMBERS)}) vs E08 vs SS",
        out_png=out_png,
    )
    print(f"comparison figure: {out_png}")


if __name__ == "__main__":
    main()
