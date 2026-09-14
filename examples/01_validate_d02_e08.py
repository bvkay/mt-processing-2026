"""Vertical-slice validation: D02 remote-referenced on E08 vs legacy lemimt EDIs.

This test fails if the aurora curves do not overlay the lemimt curves within
error bars on this clean site (a constant rho offset with matching phase would
point at a dipole-length mismatch, not a processing error).

Run from the repo root:  python examples/01_validate_d02_e08.py
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

SURVEY_YAML = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
REFERENCE_EDIS = SURVEY_YAML.parent / "reference_edis.yaml"  # merged lemimt EDIs
LOCAL, REMOTE = "D02", "E08"
# full D02 deployment (the shorter of the pair) so the longest bands resolve
START, END = "2021-06-29 06:00", "2021-07-01 00:00"


def main() -> None:
    survey = Survey.from_yaml(SURVEY_YAML)
    local_h5 = ingest_site(survey, LOCAL, start=START, end=END)
    remote_h5 = ingest_site(survey, REMOTE, start=START, end=END)

    scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)
    tf = process_station(
        local_h5, LOCAL, remote_h5, REMOTE,
        out_dir=survey.workspace / "tf", band_scheme=scheme,
    )

    baseline = None
    if REFERENCE_EDIS.exists():
        mapping = yaml.safe_load(REFERENCE_EDIS.read_text(encoding="utf-8")) or {}
        if LOCAL in mapping:
            baseline = mapping[LOCAL]["edi"]
    out_png = survey.workspace / "tf" / f"{LOCAL}_rr-{REMOTE}_vs_lemimt.png"
    plot_comparison(
        tf, baseline=baseline,
        title=f"{LOCAL} RR {REMOTE} — aurora vs lemimt ({START} to {END} UTC)",
        out_png=out_png,
    )
    print(f"comparison figure: {out_png}")


if __name__ == "__main__":
    main()
