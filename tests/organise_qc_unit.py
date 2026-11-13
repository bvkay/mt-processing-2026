# -*- coding: utf-8 -*-
"""
Unit test for scripts/organise_qc.py

A synthetic survey is written under the scratch directory: a survey.yaml
with sites A01, A01L (derived from A01), B02, C21, C21new and R01, and a
workspace whose ``qc/`` folder holds one site file (``A01L_psd.png``, a
derived site's figure, so it belongs under A01), one line file
(``lineA_profile.png``), one survey folder (``night_ss/table.md``), one
unknown (``mystery.png``), a C21new figure, a kept line-scan table
(``lines_A01.csv``), and a line folder made earlier (``lineA/`` holding
``A01_old.png`` and an organised ``A01/`` folder). ``tf/A01_x.edi`` sits
beside qc. A note in a line subfolder (``notes/lineA/A01.md``) cites the
site file, the survey table, the unknown and ``lineA/A01_old.png`` by their
old relative paths; a saved report (``qc/night_ss`` is not the reports
folder, ``qc/reports/r.json``) cites the site file by an absolute Windows
path. The script's ``main`` is run as a dry run, then with --apply, then
with --apply again.

Usage:
    python tests/organise_qc_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the synthetic qc tree with one site file, one line
file, one survey file and one unknown does not land in the four expected
places (``qc/lineA/A01/A01L_psd.png``, ``qc/lineA/line/lineA_profile.png``,
``qc/survey/night_ss/table.md``, ``qc/unsorted/mystery.png``), or C21new's
figure is not under ``qc/lineC/C21/``, or ``lineA/A01_old.png`` is not under
``qc/lineA/A01/``, or the kept table or ``tf/`` is moved, or the dry run
moves anything, or ``qc/_moves.csv`` does not hold one row per move, or a
second --apply moves anything or adds a row, or a citation in the synthetic
note (relative, forward slashes) or in the report (absolute, backslashes) is
not rewritten to the new path, or a citation of a path that did not move is
changed.

The mutations: with ``rewrite_citations`` replaced by a stub that rewrites
nothing, the citation criterion trips; with ``Rules.place_top`` sending every
item to ``unsorted``, the placement criterion trips; with
``Rules.place_in_line`` never leaving an item in place, the second --apply
moves something. The test runs all three and checks that each of those
criteria is shown able to fail.
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402

SCRIPT = REPO / "scripts" / "organise_qc.py"
SCRATCH = scratch_dir("organise_qc_unit")
WS_NAME = "Demo_Workspace"
EXPECTED = {
    "site": "qc/lineA/A01/A01L_psd.png",
    "line": "qc/lineA/line/lineA_profile.png",
    "survey": "qc/survey/night_ss/table.md",
    "unknown": "qc/unsorted/mystery.png",
    "child site": "qc/lineC/C21/C21new_fit.png",
    "old line folder": "qc/lineA/A01/A01_old.png",
}
KEPT = ("qc/lines_A01.csv", "tf/A01_x.edi", "qc/lineA/A01/kept.png")


def load_script():
    """Import scripts/organise_qc.py as a module."""
    spec = importlib.util.spec_from_file_location("organise_qc", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(module, *args: str) -> tuple[int, str]:
    """Run the script's main with args; return its exit status and printed output."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = module.main(list(args))
    return status, out.getvalue()


def build() -> tuple[Path, Path, Path]:
    """Write the synthetic survey; return survey.yaml, the workspace and the notes folder."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    survey, ws = SCRATCH / "survey", SCRATCH / WS_NAME
    qc, notes = ws / "qc", survey / "notes"
    for folder in (qc / "night_ss", qc / "lineA" / "A01", qc / "reports", ws / "tf", notes / "lineA"):
        folder.mkdir(parents=True, exist_ok=True)
    (survey / "survey.yaml").write_text(
        f"name: demo\nworkspace: {ws.as_posix()}\nsites:\n  A01: {{}}\n"
        "  A01L: {derived_from: A01, sample_rate: 1.0}\n  B02: {}\n  C21: {}\n  C21new: {}\n  R01: {}\n",
        encoding="utf-8")
    for rel in ("A01L_psd.png", "lineA_profile.png", "night_ss/table.md", "mystery.png",
                "C21new_fit.png", "lines_A01.csv", "lineA/A01_old.png", "lineA/A01/kept.png"):
        (qc / rel).write_bytes(b"x")
    (ws / "tf" / "A01_x.edi").write_bytes(b"x")
    (notes / "lineA" / "A01.md").write_text(
        "# A01\n\n- Spectra [`qc/A01L_psd.png`; `qc/night_ss/table.md`].\n"
        "- Unknown `qc/mystery.png`; earlier `qc/lineA/A01_old.png`.\n"
        "- Unmoved `qc/lineA/A01/kept.png` and `qc/lines_A01.csv`.\n",
        encoding="utf-8")
    report = {"workflow": "demo", "result": {"figures": [
        f"D:\\MT_DATA\\{WS_NAME}\\qc\\A01L_psd.png", "qc/night_ss/table.md"]}}
    (qc / "reports" / "r.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return survey / "survey.yaml", ws, notes


def moves_rows(ws: Path) -> list[dict]:
    """Return the rows of qc/_moves.csv, or [] when there is none."""
    path = ws / "qc" / "_moves.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def placement(ws: Path) -> dict[str, bool]:
    """Return, per expected placement and kept path, whether it holds."""
    held = {k: (ws / rel).is_file() for k, rel in EXPECTED.items()}
    held["kept"] = all((ws / rel).is_file() for rel in KEPT)
    return held


def citations(ws: Path, notes: Path) -> dict[str, bool]:
    """Return which citation criteria hold after an apply."""
    note = (notes / "lineA" / "A01.md").read_text(encoding="utf-8")
    report = json.loads((ws / "qc" / "survey" / "reports" / "r.json").read_text(encoding="utf-8"))
    figures = report["result"]["figures"]
    return {
        "note rewritten": all(f"`{EXPECTED[k]}`" in note for k in ("site", "survey", "unknown", "old line folder")),
        "note unmoved kept": "`qc/lineA/A01/kept.png`" in note and "`qc/lines_A01.csv`" in note,
        "report absolute": figures[0] == f"D:\\MT_DATA\\{WS_NAME}\\qc\\lineA\\A01\\A01L_psd.png",
        "report relative": figures[1] == "qc/survey/night_ss/table.md",
    }


def main() -> None:
    module = load_script()

    # dry run: nothing moves, the plan names the four places
    survey_yaml, ws, notes = build()
    status, out = run(module, str(survey_yaml))
    assert status == 0 and not (ws / "qc" / "_moves.csv").exists(), out
    assert (ws / "qc" / "A01L_psd.png").exists() and (ws / "qc" / "mystery.png").exists(), out
    for line in ("qc/A01L_psd.png -> qc/lineA/A01/A01L_psd.png",
                 "qc/lineA_profile.png -> qc/lineA/line/lineA_profile.png",
                 "qc/night_ss -> qc/survey/night_ss", "qc/mystery.png -> qc/unsorted/mystery.png"):
        assert line in out, (line, out)
    assert "unsorted (no rule): 1" in out and "  mystery.png" in out, out
    print("  dry run: nothing moved; the plan lists the four places and mystery.png as unsorted")

    # apply
    status, out = run(module, str(survey_yaml), "--apply")
    held = placement(ws)
    assert status == 0 and all(held.values()), (held, out)
    rows = moves_rows(ws)
    assert len(rows) == 7 and all(r["old"] and r["new"] and r["date"] for r in rows), rows
    assert not (ws / "qc" / "reports").exists() and (ws / "qc" / "survey" / "reports" / "r.json").exists()
    cited = citations(ws, notes)
    assert all(cited.values()), (cited, out)
    print(f"  apply: {len(rows)} moves recorded; placements {sorted(held)} hold; citations rewritten "
          "(relative in the note, absolute with backslashes in the report), unmoved ones kept")

    # apply again: nothing moves, no row added, no citation changed
    note_before = (notes / "lineA" / "A01.md").read_text(encoding="utf-8")
    status, out = run(module, str(survey_yaml), "--apply")
    assert status == 0 and "moved: 0;" in out and len(moves_rows(ws)) == 7, out
    assert "citations rewritten: 0" in out, out
    assert (notes / "lineA" / "A01.md").read_text(encoding="utf-8") == note_before
    print("  second apply: moved 0, _moves.csv unchanged, 0 citations rewritten")

    # the mutations: each criterion shown able to fail
    original_rewrite, original_top, original_in_line = (
        module.rewrite_citations, module.Rules.place_top, module.Rules.place_in_line)
    survey_yaml, ws, notes = build()
    module.rewrite_citations = lambda *a, **k: {}
    run(module, str(survey_yaml), "--apply")
    tripped_citation = not all(citations(ws, notes).values())
    module.rewrite_citations = original_rewrite

    survey_yaml, ws, notes = build()
    module.Rules.place_top = lambda self, name, is_dir: (
        ("organised", None) if name in ("unsorted", "_moves.csv") else ("unsorted", f"unsorted/{name}"))
    run(module, str(survey_yaml), "--apply")
    tripped_placement = not all(placement(ws).values())
    module.Rules.place_top = original_top

    survey_yaml, ws, notes = build()
    module.Rules.place_in_line = lambda self, line, name, is_dir: ("line", f"{line}/line/{name}")
    run(module, str(survey_yaml), "--apply")
    n_first = len(moves_rows(ws))
    run(module, str(survey_yaml), "--apply")
    tripped_idempotent = len(moves_rows(ws)) > n_first
    module.Rules.place_in_line = original_in_line
    assert tripped_citation and tripped_placement and tripped_idempotent, (
        tripped_citation, tripped_placement, tripped_idempotent)
    print("  mutations: no rewrite trips the citation criterion; everything to unsorted trips the "
          "placement criterion; a line folder never left in place trips the second-apply criterion")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutations:")[0].strip())
    print()
    main()
    print("\nPASS  organise_qc_unit")
