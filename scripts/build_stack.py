"""Build a synthetic (stacked) remote reference from concurrent sites.

Usage:
    python scripts/build_stack.py <survey.yaml> <name> <start> <end> <member> [<member> ...]

The stack is the mean of the members' raw hx/hy counts over the common span
(each member's declared filters from <survey>/filters.yaml applied first);
no calibration is needed because the remote-reference estimator is invariant
to any linear transform of the remote. Writes <workspace>/mth5/<name>.h5;
process it as the remote with scripts/process_rr.py <survey.yaml> <local> <name>.
Check the members first: scripts/coherence_qc.py against the dedicated remote
tells you which coils are worth stacking (one dead channel poisons a mean).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from bbmt.survey import Survey
from bbmt.virtual import build_synthetic_remote


def main(survey_yaml: str, name: str, start: str, end: str, *members: str) -> None:
    if len(members) < 2:
        sys.exit("give at least two members")
    survey = Survey.from_yaml(survey_yaml)
    out = build_synthetic_remote(survey, list(members), start, end, name=name)
    print(f"stack {name} <- {', '.join(members)}: {out}")


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit(__doc__)
    main(*sys.argv[1:])
