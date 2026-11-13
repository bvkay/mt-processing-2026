# -*- coding: utf-8 -*-
"""
Unit test for the Metadata tab's Save, its rows without an entry and Import site table (run headless)

The tab is driven offscreen on a synthetic survey: three site folders S01,
S02 and S03 under a scratch data root, each holding one empty B423 file
named by its epoch, and a survey.yaml written by hand with LF line endings,
a `defaults:` block, entries for S01 and S02 only, a comment line inside
the `sites:` block and an inline comment on one of S02's keys. Message
boxes are replaced by recorders and a basemap fetch is recorded instead of
started, so the test runs offline.

This test fails if:

- a Save of one edited cell (S02's dipole_length_ex, 48 to 45) changes a
  line of survey.yaml other than that key's line, drops or changes a
  comment, changes a line ending, leaves no survey.yaml.previous holding
  the bytes before the Save, does not give the new value through
  `Survey.site`, or does not name the earlier copy in the status line;
- the same cell typed equal to the `defaults:` value (50) does not remove
  S02's own key on Save, with that one line the only change; or the status
  line, after it and after an emptied cell, does not say that the key was
  removed and that S02 takes 50.0 from `defaults:`;
- a cell of the S03 row (a folder with no entry) can be edited, is not
  greyed, or lacks the "no entry yet" tooltip; or the S01 and S02 rows lose
  their editable cells;
- Import site table replaces the latitude S01 shows with the table's
  different one or does not name that disagreement; does not fill the
  elevation S01 lacks; does not set S01's dipole_length_ey; changes a cell
  of the S03 row or does not name S03 as a site with no entry; does not
  count one matched site as in the file and one changed; or the Save after
  it does not write those two values into S01's entry alone, S03 still
  without an entry and the comments as they were.

Mutations that must make it fail: Save put back on a rewrite of the whole
`sites:` block with `yaml.safe_dump`, as before the writer (the comments
are lost and no survey.yaml.previous is made); the status line given only
the summary lines that end in "check it" (a removal is not shown).

Usage:
    QT_QPA_PLATFORM=offscreen python tests/gui_new_survey_flow_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import difflib
import os
import shutil
import sys
import time
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from mt_workbench.gui.tabs.metadata import COLUMNS, NO_ENTRY_TIP  # noqa: E402
from mt_workbench.gui.theme import DISABLED  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.survey_file import comment_texts  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("gui_new_survey_flow_unit")
EPOCH = 1624510579
BOXES: list[tuple[str, str, str]] = []  # modal boxes: (kind, title, text)
FETCHES: list[list[str]] = []
_real_run_now = JobRunner.run_now

SURVEY_TEXT = """\
name: flow
instrument: lemi423
sample_rate: 1000
data_root: {raw}
workspace: {work}
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
sites:
  # dipoles of S01 and S02 taped on the day
  S01:
    latitude: -31.5
    longitude: 138.5
  S02:
    latitude: -31.6  # from the handheld GPS
    longitude: 138.6
    elevation: 240.0
    dipole_length_ex: 48.0
"""
IMPORT_CSV = ("site,latitude,elevation,dipole_length_ex,dipole_length_ey\n"
              "S01,-31.7,251,,47\n"
              "S02,-31.6,,50,\n"
              "S03,,,40,\n"
              "S99,,,40,\n")


def _recording_run_now(self, label, argv, **details):
    """Record a fetch_basemap.py job instead of starting it; run any other job as usual."""
    argv = [str(a) for a in argv]
    if any(Path(a).name == "fetch_basemap.py" for a in argv):
        FETCHES.append(argv)
        return -1
    return _real_run_now(self, label, argv, **details)


def _box(kind: str):
    def record(parent, title, text, *args, **kwargs):
        BOXES.append((kind, title, text))
        return QMessageBox.Ok
    return staticmethod(record)


JobRunner.run_now = _recording_run_now
for _kind in ("warning", "critical", "information", "question"):
    setattr(QMessageBox, _kind, _box(_kind))


def pump(app: QApplication, seconds: float = 0.2) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def make_survey() -> Path:
    """Write the survey of the module docstring into the scratch folder; return its survey.yaml."""
    root = SCRATCH / "flow"
    shutil.rmtree(root, ignore_errors=True)
    for site in ("S01", "S02", "S03"):
        (root / "raw" / site).mkdir(parents=True)
        (root / "raw" / site / f"{EPOCH}.B423").write_bytes(b"")
    (root / "work").mkdir()
    path = root / "survey.yaml"
    path.write_bytes(SURVEY_TEXT.format(raw=(root / "raw").as_posix(), work=(root / "work").as_posix())
                     .encode("utf-8"))
    return path


def changes(before: bytes, after: bytes) -> list[tuple[list[str], list[str]]]:
    """Return each changed run of lines as (old lines, new lines), line endings included."""
    old = before.decode("utf-8").splitlines(keepends=True)
    new = after.decode("utf-8").splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return [(old[i1:i2], new[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def main() -> int:
    print(__doc__.split("This test fails if:")[1].split("Mutations that")[0].strip())
    print()
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    failed, n_checks = [], 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal n_checks
        n_checks += 1
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failed.append(name)

    path = make_survey()
    previous = path.with_name("survey.yaml.previous")
    window.open_survey(path)
    pump(app)
    tab = window.metadata_tab
    table = tab.table

    def cell(site: str, column: str):
        row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == site)
        return table.item(row, COLUMNS.index(column))

    def row_cells(site: str) -> list:
        return [cell(site, column) for column in COLUMNS]

    # the row of a folder with no entry is read-only and greyed
    s03 = row_cells("S03")
    editable = [c.text() for c in s03 if c.flags() & Qt.ItemIsEditable]
    check("S03 has no editable cell", not editable, f"editable cells {editable}")
    colours = {c.foreground().color().name() for c in s03}
    check("S03 is greyed", colours == {DISABLED}, f"colours {colours}")
    tips = {c.toolTip() for c in s03}
    check("S03 cells carry the no entry tooltip", tips == {NO_ENTRY_TIP}, f"tooltips {tips}")
    for site in ("S01", "S02"):
        flags = cell(site, "dipole_length_ex").flags()
        check(f"{site} keeps its editable dipole cell", bool(flags & Qt.ItemIsEditable), f"flags {flags}")

    # Save of one cell: one line changes, the comments stay, the earlier file is kept
    before = path.read_bytes()
    cell("S02", "dipole_length_ex").setText("45")
    saved = tab.save()
    pump(app)
    after = path.read_bytes()
    diff = changes(before, after)
    check("Save of one cell returns True", saved is True, f"save() gave {saved}, boxes {BOXES}")
    check("Save changes that key's line only",
          diff == [(["    dipole_length_ex: 48.0\n"], ["    dipole_length_ex: 45.0\n"])], f"changes {diff}")
    check("Save keeps every comment", comment_texts(after.decode("utf-8")) == comment_texts(before.decode("utf-8")),
          f"comments {comment_texts(after.decode('utf-8'))}")
    n_cr = after.count(b"\r")
    check("Save keeps LF line endings", n_cr == 0, f"{n_cr} carriage returns")
    check("survey.yaml.previous holds the file before the Save",
          previous.is_file() and previous.read_bytes() == before,
          f"exists {previous.is_file()}, same bytes {previous.is_file() and previous.read_bytes() == before}")
    value = Survey.from_yaml(path).site("S02").dipole_length_ex
    check("Survey.site reads the new value", value == 45.0, f"S02 dipole_length_ex {value}")
    status = tab.status_label.text()
    check("the status line names the earlier copy",
          status.startswith("saved 1 value(s) for 1 site(s)") and "survey.yaml.previous" in status, repr(status))

    # a cell typed equal to the default removes the site's own key
    before = path.read_bytes()
    cell("S02", "dipole_length_ex").setText("50")
    saved = tab.save()
    pump(app)
    after = path.read_bytes()
    diff = changes(before, after)
    check("a value equal to the default removes the key's line only",
          saved is True and diff == [(["    dipole_length_ex: 45.0\n"], [])], f"save() {saved}, changes {diff}")
    value = Survey.from_yaml(path).site("S02").dipole_length_ex
    check("S02 then reads the default", value == 50.0, f"S02 dipole_length_ex {value}")
    status = tab.status_label.text()
    check("the status line says the key was removed and what the site now reads",
          "S02: dipole_length_ex removed (takes 50.0 from defaults:)" in status, repr(status))

    # an emptied cell removes the site's own key, and the status line says what the site now reads
    cell("S02", "dipole_length_ex").setText("44")
    tab.save()
    pump(app)
    cell("S02", "dipole_length_ex").setText("")
    saved = tab.save()
    pump(app)
    status = tab.status_label.text()
    value = Survey.from_yaml(path).site("S02").dipole_length_ex
    check("an emptied cell removes the key and the status line says the site takes 50.0",
          saved is True and value == 50.0 and "S02: dipole_length_ex removed (takes 50.0 from defaults:)" in status,
          f"save() {saved}, S02 dipole_length_ex {value}, status {status!r}")

    # Import site table through merge_table_row
    csv_path = SCRATCH / "flow" / "table.csv"
    csv_path.write_text(IMPORT_CSV, encoding="utf-8")
    s03_before = [c.text() for c in row_cells("S03")]
    counts = tab.import_site_table(csv_path)
    status = tab.status_label.text()
    check("Import counts two of four rows matched", counts == (2, 4), f"returned {counts}")
    check("Import counts one as in the file and one changed",
          status.startswith("2 of 4 sites matched: 1 as in the file, 1 changed"), repr(status))
    check("Import keeps the latitude S01 shows", cell("S01", "latitude").text() == "-31.5",
          f"S01 latitude cell {cell('S01', 'latitude').text()!r}")
    check("Import names the latitude disagreement", "S01 latitude -31.7 in the table, -31.5 kept" in status,
          repr(status))
    check("Import fills the elevation S01 lacks", cell("S01", "elevation").text() == "251",
          f"S01 elevation cell {cell('S01', 'elevation').text()!r}")
    check("Import sets S01's dipole_length_ey", cell("S01", "dipole_length_ey").text() == "47",
          f"S01 dipole_length_ey cell {cell('S01', 'dipole_length_ey').text()!r}")
    s03_after = [c.text() for c in row_cells("S03")]
    check("Import leaves the S03 row alone", s03_after == s03_before,
          f"changed {[(COLUMNS[i], a, b) for i, (a, b) in enumerate(zip(s03_before, s03_after)) if a != b]}")
    check("Import names S03 as a site with no entry",
          "not a site with an entry: S03 (press Add sites first)" in status and "not in this survey: S99" in status,
          repr(status))

    before = path.read_bytes()
    saved = tab.save()
    pump(app)
    after = path.read_bytes()
    diff = changes(before, after)
    want = [([], ["    elevation: 251.0\n", "    dipole_length_ey: 47.0\n"])]
    check("Save after Import adds the two values to S01 alone", saved is True and diff == want,
          f"save() {saved}, changes {diff}")
    sites = Survey.from_yaml(path).site_names()
    check("S03 still has no entry", "S03" not in sites, f"entries {sites}")
    check("the comments are as they were", comment_texts(after.decode("utf-8")) == comment_texts(SURVEY_TEXT),
          f"comments {comment_texts(after.decode('utf-8'))}")
    check("no box was shown", BOXES == [], f"boxes {BOXES}")

    window.close()
    print()
    if failed:
        print(f"FAIL  gui_new_survey_flow_unit ({len(failed)} of {n_checks} checks failed): {', '.join(failed)}")
        return 1
    print(f"PASS  gui_new_survey_flow_unit (0 of {n_checks} checks failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
