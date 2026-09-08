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

from bbmt.compare import plot_comparison
from bbmt.ingest import ingest_site
from bbmt.process import process_station
from bbmt.survey import Survey

SURVEY_YAML = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
LOCAL, REMOTE = "D02", "E08"
# 6 h of concurrent night-time (ACST) recording; extend once the slice works
START, END = "2021-06-29 12:00", "2021-06-29 18:00"


def main() -> None:
    survey = Survey.from_yaml(SURVEY_YAML)
    local_h5 = ingest_site(survey, LOCAL, start=START, end=END)
    remote_h5 = ingest_site(survey, REMOTE, start=START, end=END)

    tf = process_station(
        local_h5, LOCAL, remote_h5, REMOTE, out_dir=survey.workspace / "tf"
    )

    refs = sorted((survey.data_root / "EDIs").glob(f"P-{LOCAL}_RR-{REMOTE}_S-1000Hz_*.edi"))
    out_png = survey.workspace / "tf" / f"{LOCAL}_rr-{REMOTE}_vs_lemimt.png"
    plot_comparison(
        tf, refs, title=f"{LOCAL} RR {REMOTE} — aurora vs lemimt ({START} to {END} UTC)",
        out_png=out_png,
    )
    print(f"comparison figure: {out_png}")


if __name__ == "__main__":
    main()
