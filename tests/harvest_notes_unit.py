# -*- coding: utf-8 -*-
"""
Unit test for scripts/harvest_notes.py

A synthetic survey is written under the scratch directory: a survey.yaml
whose workspace is a scratch folder, a ``notes/`` folder with one note, and a
reports folder with two JSON reports, A and B. The note cites A by its file
name, an existing figure ``qc/fig_ok.png``, a missing figure
``qc/fig_missing.png``, a glob ``qc/fig_*.png`` and a template
``qc/<site>_x.png``; it does not cite B. The script's ``main`` is run on it,
then on repaired notes, then on a note citing a report that does not exist.
The survey declares two sites, S04 and S05. A synthetic workflow journal (a
report ``dive:S05`` whose text names S05 and S04, and its verdict
``verify:S05``, with the workflow's script beside it) is then copied into the
reports folder with ``--journals``, twice. Last, the notebook gets a line
subfolder (``notes/lineS/S04.md``, the only note citing B, with a relative
``../site.md``) and the reports are moved to ``qc/survey/reports/``, the
organised qc layout.

Usage:
    python tests/harvest_notes_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the first run does not return 1, or its output does
not name B as cited by no note and ``qc/fig_missing.png`` as a missing path,
or names A, ``qc/fig_ok.png``, the glob or the template among the problems;
``notes/index.md`` does not list A as cited by the note and B as cited by
none, or ``manifest.csv`` does not hold one row per report with the columns
file, workflow, label, phase, date, sites, has_verdict, kind, run_id and
agent_id; the repaired notebook (B cited, the missing figure gone) does not
return 0 and print PASS; a note citing ``r: C.json`` does not return 1 naming
C as a cited report missing; a glob that matches no file is not reported
missing; the journal copy does not write exactly two files named
``<date>_harvest-demo_dive-S05.json`` and
``<date>_harvest-demo_verify-S05.json``, with the date from the journal's
modification time (2023-09-27), the report's kind "report", has_verdict true
and verdict_by ``["verify:S05"]``, the verdict's kind "verdict", the sites
``["S04", "S05"]`` (the survey's site names, not S0 or S055) and the result
copied unchanged; or a second copy writes any file; or, with the line
subfolder and the reports in ``qc/survey/reports/``, the run without
--reports does not find both reports, does not count B as cited by
``lineS/S04.md`` (as named in index.md), fails on ``../site.md`` (which
exists beside the note's folder), or does not report ``../nothere.md`` as
``lineS/S04.md: cited path missing``.

The mutations: with ``path_exists`` replaced by a stub that finds every path,
the missing-figure criterion trips; with ``citations`` replaced by a stub that
marks every report cited, the uncited-report criterion trips. The test runs
both and checks that each of those criteria is shown able to fail.
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402

SCRIPT = REPO / "scripts" / "harvest_notes.py"
SCRATCH = scratch_dir("harvest_notes_unit")
COLUMNS = ["file", "workflow", "label", "phase", "date", "sites", "has_verdict",
           "kind", "run_id", "agent_id"]
A, B = "2026-09-25_demo-flow_site-A.json", "2026-09-25_demo-flow_site-B.json"


def load_script():
    """Import scripts/harvest_notes.py as a module."""
    spec = importlib.util.spec_from_file_location("harvest_notes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(module, *args: str) -> tuple[int, str]:
    """Run the script's main with args; return its exit status and printed output."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = module.main(list(args))
    return status, out.getvalue()


def build() -> tuple[Path, Path, Path, Path]:
    """Write the synthetic survey; return survey.yaml, the notes, the reports and the workspace."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    survey = SCRATCH / "survey"
    ws = SCRATCH / "workspace"
    notes, reports = survey / "notes", ws / "qc" / "reports"
    for folder in (notes, reports, ws / "qc"):
        folder.mkdir(parents=True, exist_ok=True)
    (survey / "survey.yaml").write_text(
        f"name: demo\nworkspace: {ws.as_posix()}\nsites:\n  S04: {{}}\n  S05: {{}}\n", encoding="utf-8")
    (ws / "qc" / "fig_ok.png").write_bytes(b"png")
    for name, site in ((A, "S01"), (B, "S02")):
        record = {"workflow": "demo-flow", "run_id": "wf_demo", "label": f"site:{site}",
                  "phase": "Test", "agent_id": f"a{site}", "date": "2026-09-25",
                  "kind": "report", "has_verdict": False, "verdict_by": [], "sites": [site],
                  "result": {"summary": f"{site} noise"}}
        (reports / name).write_text(json.dumps(record), encoding="utf-8")
    write_note(notes, cite_b=False, missing_fig=True)
    return survey / "survey.yaml", notes, reports, ws


def write_note(notes: Path, cite_b: bool, missing_fig: bool, extra: str = "") -> None:
    """Write notes/site.md with the citations the case needs."""
    lines = [
        "# Site",
        f"- A was tried [r: {A}; `qc/fig_ok.png`].",
        "- Glob `qc/fig_*.png` and template `qc/<site>_x.png`.",
    ]
    if cite_b:
        lines.append(f"- B too [r: {B}].")
    if missing_fig:
        lines.append("- A figure that is not there `qc/fig_missing.png`.")
    if extra:
        lines.append(extra)
    (notes / "site.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def problems_of(output: str) -> list[str]:
    """Return the problem lines of a run's output."""
    return [line for line in output.splitlines()
            if "cited by no note" in line or "missing" in line]


def criteria(status: int, output: str) -> dict[str, bool]:
    """Return which first-run criteria hold for a run's status and output."""
    probs = problems_of(output)
    return {
        "exit 1": status == 1,
        "B uncited": any(B in p and "cited by no note" in p for p in probs),
        "missing figure": any("qc/fig_missing.png" in p for p in probs),
        "no false alarm": not any(A in p or "fig_ok" in p or "fig_*" in p or "<site>" in p
                                  for p in probs),
    }


def check_index_and_manifest(notes: Path, reports: Path) -> None:
    """Check index.md and manifest.csv after the first run."""
    index = (notes / "index.md").read_text(encoding="utf-8")
    row_a = next(line for line in index.splitlines() if line.startswith(f"| {A} "))
    row_b = next(line for line in index.splitlines() if line.startswith(f"| {B} "))
    assert row_a.rstrip().endswith("| site.md |"), row_a
    assert row_b.rstrip().endswith("| - |"), row_b
    with open(reports / "manifest.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == COLUMNS, list(rows[0].keys())
    assert sorted(r["file"] for r in rows) == [A, B], rows
    print(f"  index.md: A cited by site.md, B by none; manifest.csv: {len(rows)} rows, columns {COLUMNS}")


def write_journal(root: Path) -> Path:
    """Write a synthetic log folder with one workflow journal; return the journal path."""
    session = root / "session"
    run_dir = session / "subagents" / "workflows" / "wf_demo2"
    run_dir.mkdir(parents=True, exist_ok=True)
    (session / "workflows" / "scripts").mkdir(parents=True, exist_ok=True)
    (session / "workflows" / "scripts" / "harvest-demo-wf_demo2.js").write_text("// demo\n", encoding="utf-8")
    report = {"site": "S05", "summary": "S05 ey is a channel fault; S04 is clean; S0 and S055 are not sites.",
              "caveats": []}
    verdict = {"checked": ["numbers"], "refuted": [], "confirmed": ["S05 fault"], "notes": "holds"}
    lines = [
        {"type": "launched"},
        {"type": "started", "agentId": "a111", "label": "dive:S05", "phase": "Deep dives"},
        {"type": "result", "agentId": "a111", "result": report},
        {"type": "started", "agentId": "a222", "label": "verify:S05", "phase": "Verify"},
        {"type": "result", "agentId": "a222", "result": verdict},
    ]
    journal = run_dir / "journal.jsonl"
    journal.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    stamp = dt.datetime(2023, 9, 27, 12, 0).timestamp()
    os.utime(journal, (stamp, stamp))
    return journal


def main() -> None:
    module = load_script()
    survey_yaml, notes, reports, ws = build()

    # first run: one uncited report, one missing figure
    status, out = run(module, str(survey_yaml))
    held = criteria(status, out)
    assert all(held.values()), (held, out)
    print(f"  first run: exit {status}; problems: {problems_of(out)}")
    check_index_and_manifest(notes, reports)

    # a glob with no match is reported
    write_note(notes, cite_b=True, missing_fig=False, extra="- `qc/nomatch_*.png`")
    status, out = run(module, str(survey_yaml))
    assert status == 1 and any("qc/nomatch_*.png" in p for p in problems_of(out)), out
    print("  a glob that matches nothing: exit 1, reported missing")

    # repaired notebook
    write_note(notes, cite_b=True, missing_fig=False)
    status, out = run(module, str(survey_yaml))
    assert status == 0 and out.strip().endswith("PASS"), out
    print("  repaired notebook: exit 0, PASS")

    # a citation of a report that does not exist
    write_note(notes, cite_b=True, missing_fig=False, extra="- C [r: C.json].")
    status, out = run(module, str(survey_yaml))
    assert status == 1 and any("cited report missing: C.json" in p for p in problems_of(out)), out
    print("  r: C.json with no such report: exit 1, 'cited report missing: C.json'")
    write_note(notes, cite_b=True, missing_fig=False)

    # journal copy
    journal = write_journal(SCRATCH / "journals")
    before = set(p.name for p in reports.glob("*.json"))
    status, out = run(module, str(survey_yaml), "--journals", str(SCRATCH / "journals"), "--no-index")
    new = sorted(set(p.name for p in reports.glob("*.json")) - before)
    expect = ["2023-09-27_harvest-demo_dive-S05.json", "2023-09-27_harvest-demo_verify-S05.json"]
    assert new == expect, (new, out)
    rep = json.loads((reports / expect[0]).read_text(encoding="utf-8"))
    ver = json.loads((reports / expect[1]).read_text(encoding="utf-8"))
    assert rep["kind"] == "report" and rep["has_verdict"] is True, rep
    assert rep["verdict_by"] == ["verify:S05"] and rep["sites"] == ["S04", "S05"], rep
    assert rep["result"] == json.loads(journal.read_text(encoding="utf-8").splitlines()[2])["result"], rep
    assert ver["kind"] == "verdict" and rep["workflow"] == "harvest-demo", ver
    print(f"  journals: wrote {new}; report has_verdict by {rep['verdict_by']}, sites {rep['sites']}")
    status, out = run(module, str(survey_yaml), "--journals", str(SCRATCH / "journals"), "--no-index")
    again = sorted(set(p.name for p in reports.glob("*.json")) - before)
    assert again == expect and "0 new report" in out, (again, out)
    print("  journals again: 0 new reports")

    # the mutations: each criterion shown able to fail
    for p in reports.glob("2023-09-27_*.json"):
        p.unlink()
    write_note(notes, cite_b=False, missing_fig=True)
    original_exists, original_citations = module.path_exists, module.citations
    module.path_exists = lambda span, roots: True
    status, out = run(module, str(survey_yaml), "--no-index")
    tripped_fig = not criteria(status, out)["missing figure"]
    module.path_exists = original_exists
    module.citations = lambda notes_dir, names: {n: ["site.md"] for n in names}
    status, out = run(module, str(survey_yaml), "--no-index")
    tripped_b = not criteria(status, out)["B uncited"]
    module.citations = original_citations
    assert tripped_fig and tripped_b, (tripped_fig, tripped_b)
    print("  mutations: path_exists always true trips the missing-figure criterion; "
          "citations marking everything cited trips the uncited-report criterion")

    # a line subfolder, and the reports in the organised qc layout
    survey_yaml, notes, reports, ws = build()
    write_note(notes, cite_b=False, missing_fig=False)
    line_dir = notes / "lineS"
    line_dir.mkdir()
    (line_dir / "S04.md").write_text(f"# S04\n\n- Keys in `../site.md` [r: {B}].\n", encoding="utf-8")
    organised = ws / "qc" / "survey" / "reports"
    organised.parent.mkdir(parents=True)
    shutil.move(str(reports), str(organised))
    status, out = run(module, str(survey_yaml))
    assert status == 0 and "reports: 2, cited: 2" in out, out
    index = (notes / "index.md").read_text(encoding="utf-8")
    row_b = next(line for line in index.splitlines() if line.startswith(f"| {B} "))
    assert row_b.rstrip().endswith("| lineS/S04.md |"), row_b
    (line_dir / "S04.md").write_text(f"# S04\n\n- `../nothere.md` [r: {B}].\n", encoding="utf-8")
    status, out = run(module, str(survey_yaml), "--no-index")
    assert status == 1 and "lineS/S04.md: cited path missing: ../nothere.md" in out, out
    print("  line subfolder: reports found in qc/survey/reports, B cited by lineS/S04.md, "
          "../site.md resolved from the note's folder, ../nothere.md reported missing")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutations:")[0].strip())
    print()
    main()
    print("\nPASS  harvest_notes_unit")
