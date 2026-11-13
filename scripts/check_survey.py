# -*- coding: utf-8 -*-
"""
Check a survey.yaml before ingest: what stops it and what is doubtful

Prints the findings of `mt_workbench.survey_check.check_survey`, one line per
finding name: its level, STOP (the ingest of those sites fails or gives
wrong products) or WARN (a gap to look at), how many sites it names, the
first five of them, and the message with what to do. The stops come first.
When the sites of one line have different messages (a span, an azimuth
pair) the line carries the first site's and says so. `--all` prints one
line per site. Below the findings come the line on the usual dipoles and
azimuths and a count.

The check lists the data folder and tests whether each site's archive
exists; it writes no file.

Usage (exit status 0 with no STOP, 1 with at least one STOP, 2 when the
file cannot be read as a survey):
    python scripts/check_survey.py <survey.yaml> [--all]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.survey_check import (  # noqa: E402
    LEVELS, ORDER, STOP, Finding, check_survey, count_line, usual_dipoles_text,
)

# how many site names one line of a finding lists without --all
NAMES_SHOWN = 5


def finding_lines(findings: list[Finding], every: bool = False) -> list[str]:
    """Return the printed lines of the findings, the stops first.

    Args:
        findings (list[Finding]): The findings of `check_survey`.
        every (bool): One line per site, in place of one per finding name.

    Returns:
        list[str]: ``STOP name: N site(s): A, B ...: message`` per finding
        name, or ``STOP name: A: message`` per site with `every`.
    """
    lines = []
    for name in ORDER:
        group = [f for f in findings if f.name == name]
        if not group:
            continue
        head = f"{LEVELS[name].upper()} {name}"
        if every or group[0].site is None:
            lines += [f"{head}: {f.site + ': ' if f.site else ''}{f.message}" for f in group]
            continue
        sites = [f.site for f in group]
        shown = ", ".join(sites[:NAMES_SHOWN]) + (" ..." if len(sites) > NAMES_SHOWN else "")
        differ = any(f.message != group[0].message for f in group)
        tail = f" (the message of {sites[0]}; --all prints every site's)" if differ else ""
        lines.append(f"{head}: {len(sites)} site(s): {shown}: {group[0].message}{tail}")
    return lines


def main(argv=None) -> int:
    """Print the findings of the check for one survey.yaml.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 with no STOP, 1 with at least one, 2 when the file cannot be
        read as a survey.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml", help="the survey.yaml")
    parser.add_argument("--all", action="store_true", dest="every",
                        help="one line per site, in place of one line per finding name")
    args = parser.parse_args(argv)

    path = Path(args.survey_yaml)
    if not path.is_file():
        print(f"ERROR {path} not found", file=sys.stderr)
        return 2
    try:
        survey = Survey.from_yaml(path)
    except yaml.YAMLError as exc:
        print(f"ERROR {path.name} does not parse: {' '.join(str(exc).split())}; fix it by hand first",
              file=sys.stderr)
        return 2
    except (KeyError, TypeError):
        print(f"ERROR {path} is not a survey file: it needs name: and data_root: at the top level "
              f"(python scripts/new_survey.py <data folder> --name NAME writes one)", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        print(f"ERROR {path} cannot be read as a survey: {exc}", file=sys.stderr)
        return 2

    findings = check_survey(survey)
    folders = {f.site for f in findings if f.name == "folder_without_entry"}
    for line in finding_lines(findings, args.every):
        print(line)
    print(usual_dipoles_text(survey))
    print(count_line(findings, len(survey.site_names()) + len(folders)))
    return 1 if any(f.level == STOP for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
