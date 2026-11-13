# -*- coding: utf-8 -*-
"""
Unit test for the Metadata tab: New survey, Save, Add sites, Check, the swap boxes, Rebuild archive (headless)

The tab is driven offscreen on a synthetic survey: three site folders S01,
S02 and S03 under a scratch data root, each holding one small synthetic
B423 file (`new_survey_unit.write_b423`) named by its epoch, and a
survey.yaml written by hand with LF line endings, a `defaults:` block,
entries for S01 and S02 only, a comment line inside the `sites:` block and
an inline comment on one of S02's keys. A second survey of 40 sites is wide
and long enough to scroll both ways, and a folder of synthetic Phoenix
recordings (`phoenix_files_unit.write_recording`) is the data of one New
survey job. Message boxes are replaced by recorders, a basemap fetch is
recorded instead of started, and an ingest_site.py job is recorded and
never run, so the test runs offline and builds no archive. The Add sites
job and the Phoenix New survey job run scripts/new_survey.py for real.

This test fails if:

- a Save of one edited cell (S02's dipole_length_ex, 48 to 45) changes a
  line of survey.yaml other than that key's line, drops or changes a
  comment, changes a line ending, leaves no survey.yaml.previous holding
  the bytes before the Save, does not give the new value through
  `Survey.site`, or does not name the earlier copy in the status line;
- "47 m" typed in that cell is saved, or the status line does not say to
  type the number alone;
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
  without an entry and the comments as they were;
- the New survey form, given a survey name of 31 characters, is accepted,
  or does not show the message of `mt_workbench.survey.check_survey_name`
  in one warning box; or a name of 30 characters is not accepted;
- New survey... on a survey.yaml that exists starts a job, changes the file,
  or does not say in one box that the file exists and to open it and press
  Add sites; or the command line built for a new survey holds `--force`;
- a survey.yaml that holds `generated_by: scripts/new_survey.py` (a file
  that script only adds to) shows the yellow line or asks before Save; or
  one that names another script, or a longer text that only mentions
  new_survey.py, shows no yellow line or is saved without the question;
- the New survey form does not open on "auto (from the files)" with the
  channels box empty and off, or its command line then holds `--instrument`
  or `--channels`; with the usual dipole length 45 and azimuths 0 and 90 it
  does not hold `--dipole-length 45.0`, or with 50, 0 and 90 it holds
  `--dipole-length` or `--azimuths`; azimuths 10 and 100 do not give
  `--azimuths 10.0 100.0`; with phoenix chosen the dipole box is on, or a
  length typed before is passed; the electric gain and the clock zone add
  their flags when empty, or not when filled; a gain that is not a number
  closes the form; or the command line of the form, run on a folder of
  Phoenix recordings under auto, exits other than 0;
- Add sites with an unsaved edit starts a job or asks, or does not say to
  save first; with S03 the only folder with no entry, it does not ask with
  S03 in the question, starts a job when the answer is No, or, answered
  Yes, starts a job whose command line holds `--force` or differs from the
  re-run (the data folder, `--name` and `--out` of the open survey); after
  the job the table does not hold S03 as a row with editable cells, a line
  of S01's or S02's entry or a comment changes, or the status line does
  not show the script's "added 1 site(s): S03" line; a second Add sites
  starts a job or does not say there is nothing to add; a folder S05 put
  under the data folder while the survey is open is not named by the next
  Add sites;
- Check does not list a folder named S.4 (site_name, STOP) before the
  folders S.4 and S03 with no entry (folder_without_entry) and S02's missing
  position (no_position, WARN), one row each, with the level, site, name and
  message that scripts/check_survey.py --all prints for them, or misses a
  folder S06 put there after the survey was opened; or its caption lacks
  the command's line on the usual dipoles and its count line; or a double
  click on a finding does not set `State.site` to its site and select its row;
- Save of a survey.yaml that is read-only, or that another program holds
  open, holds the window for more than five seconds, writes the file, or
  does not say in its box that the file is open in another program or
  read-only;
- the swap columns are not headed "Ex and Ey swapped" and "Hx and Hy
  swapped", or their tooltips do not say in two sentences that ingest
  exchanges the samples (for the electric lines, that the lengths and
  azimuths are declared for the lines after the exchange) and that the
  archive must be rebuilt; the S03 boxes can be ticked or are not greyed;
- a ticked box is saved as anything but the one line `swap_e: true` (or
  `swap_h: true`) at the end of that site's entry, or a Save of a tick
  changes any other line of the file, a line of another entry or a comment;
  unticking leaves the key in the file; the status line asks for a rebuild
  after a swap change at a site with no archive, or does not name the site
  and say to press Rebuild archive after one at a site with an archive;
- Rebuild archive is enabled with no site selected, for a site with no
  archive, for a folder with no entry (that has an archive), for an entry
  with an archive and no raw data folder, or while a job runs; it is not
  enabled for S02 (entry, raw data folder, archive); with a ticked box not
  yet saved it starts a job or asks, or does not say to press Save
  survey.yaml first; it starts a job when the answer is No; its question is not "Rebuild the archive of S02 from its
  raw data? The present archive is replaced." with the sentence on the
  filtered variant for a site with declared filters; or the command it
  queues is anything but `<python> scripts/ingest_site.py <survey.yaml> S02
  --force`; or the status line does not report the finished job;
- after the 40-site table is scrolled fully to the right, at the middle of
  its rows, after one row is made taller, and after a sort by latitude, the
  fixed site column is not at the left edge of the rows, on top, or shows
  at the height of a row a site other than that row's; a click on its
  header does not sort the table by site; the fixed column and the table
  disagree on the selected row, or a click in the fixed column does not
  select that row and set `State.site`; or, after the sort and the
  scrolling, the table holds an unsaved change, or an edit of one row is
  saved into another site's entry.

Mutations that must make it fail: Save put back on a rewrite of the whole
`sites:` block with `yaml.safe_dump`, as before the writer (the comments
are lost and no survey.yaml.previous is made); the status line given only
the summary lines that end in "check it" (a removal is not shown); the form
accepted without the check of the name; New survey... starting its job on a
survey.yaml that exists; the yellow line and the question for every
`generated_by`; neither of them for any text that contains new_survey.py;
the instrument passed under auto; `--dipole-length` passed when unchanged;
Add sites run with unsaved edits; Add sites given `--force`; Add sites
and Check on the folders listed when the survey was opened; the Check
double click not setting the site; Save with the writer's twenty tries;
every tick written as swap_e; an untick written as false; a tick written
into the first row's site; no rebuild asked after a swap change; Rebuild
archive enabled without an archive, for a folder with no entry, or while a
job runs; `--force` left out of the rebuild command; the fixed column
hidden; its vertical scrolling not in step; its row heights not in step;
its own copy of the site column in place of the table's model; its own
selection.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/gui_new_survey_flow_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import difflib
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import yaml

if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.gui import metadata_edit  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from mt_workbench.gui.tabs.metadata import COLUMNS, NO_ENTRY_TIP  # noqa: E402
from mt_workbench.gui.theme import DISABLED  # noqa: E402
from mt_workbench.survey import Survey, check_survey_name  # noqa: E402
from mt_workbench.survey_file import comment_texts  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from new_survey_unit import write_b423  # noqa: E402  (a synthetic LEMI-423 file with a header)
import phoenix_files_unit  # noqa: E402  (synthetic Phoenix recordings)

SCRATCH = scratch_dir("gui_new_survey_flow_unit")
EPOCH = 1624510579
BOXES: list[tuple[str, str, str]] = []  # modal boxes: (kind, title, text)
FETCHES: list[list[str]] = []
INGESTS: list[list[str]] = []  # ingest_site.py command lines, recorded and never run
ANSWERS: list[bool] = []  # the answers metadata_edit.ask_yes_no gives, in turn; empty: No
NOTCH = [{"notch": {"f0": 50, "harmonics": 1, "q": 30, "passes": 2}}]
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
    """Record a fetch_basemap.py or ingest_site.py job instead of starting it; run any other job as usual."""
    argv = [str(a) for a in argv]
    if any(Path(a).name == "fetch_basemap.py" for a in argv):
        FETCHES.append(argv)
        return -1
    if any(Path(a).name == "ingest_site.py" for a in argv):
        INGESTS.append(argv)
        return -1
    return _real_run_now(self, label, argv, **details)


def _ask(parent, title, text) -> bool:
    """Record a Yes/No question and give the next answer of ANSWERS (No when none is left)."""
    BOXES.append(("question", title, text))
    return ANSWERS.pop(0) if ANSWERS else False


def _box(kind: str):
    def record(parent, title, text, *args, **kwargs):
        BOXES.append((kind, title, text))
        return QMessageBox.Ok
    return staticmethod(record)


JobRunner.run_now = _recording_run_now
metadata_edit.ask_yes_no = _ask
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
    for k, site in enumerate(("S01", "S02", "S03")):
        write_b423(root / "raw" / site / f"{EPOCH}.B423", 36 + k, "2.1", -31.5 - k / 10, 138.5 + k / 10, 200.0,
                   EPOCH)
    (root / "work").mkdir()
    path = root / "survey.yaml"
    path.write_bytes(SURVEY_TEXT.format(raw=(root / "raw").as_posix(), work=(root / "work").as_posix())
                     .encode("utf-8"))
    return path


def make_wide() -> Path:
    """Write a survey of 40 sites W00 to W39, each with a folder and an entry; return its survey.yaml."""
    root = SCRATCH / "wide"
    shutil.rmtree(root, ignore_errors=True)
    lines = ["name: wide", "instrument: lemi423", "sample_rate: 1000", f"data_root: {(root / 'raw').as_posix()}",
             f"workspace: {(root / 'work').as_posix()}", "defaults:", "  dipole_length_ex: 50.0", "sites:"]
    for k in range(40):
        site = f"W{k:02d}"
        (root / "raw" / site).mkdir(parents=True)
        (root / "raw" / site / f"{EPOCH}.B423").write_bytes(b"")
        lines += [f"  {site}:", f"    latitude: {-30.0 - (k * 7 % 40) / 10:.1f}", "    longitude: 138.0",
                  "    notes: a note long enough to make the table wider than the window"]
    (root / "work").mkdir()
    path = root / "survey.yaml"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def wait_for(app: QApplication, done, seconds: float) -> bool:
    """Pump events until `done()` is true or the time is up; return `done()`."""
    end = time.time() + seconds
    while time.time() < end and not done():
        app.processEvents()
        time.sleep(0.02)
    return done()


def changes(before: bytes, after: bytes) -> list[tuple[list[str], list[str]]]:
    """Return each changed run of lines as (old lines, new lines), line endings included."""
    old = before.decode("utf-8").splitlines(keepends=True)
    new = after.decode("utf-8").splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    return [(old[i1:i2], new[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def find(table, site: str, column: str):
    """Return the cell of `site`'s row in `column` of the Metadata table."""
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == site)
    return table.item(row, COLUMNS.index(column))


def test_form(app, window, check) -> None:
    """The New survey form: auto, the usual dipoles, the two optional fields, a Phoenix folder under auto."""
    state = window.state
    dialog = metadata_edit.NewSurveyDialog(SCRATCH / "forms", window)
    dialog.folder_edit.setText(str(SCRATCH / "flow" / "raw"))
    out = SCRATCH / "forms" / "x" / "survey.yaml"

    def argv() -> list[str]:
        return metadata_edit.new_survey_argv(state, dialog.values(), out)

    def flag(args: list[str], name: str, n: int = 1):
        return args[args.index(name) + 1:args.index(name) + 1 + n] if name in args else None

    first = dialog.instrument_combo.currentText()
    args = argv()
    check("the form opens on auto, the channels box empty and off, and passes neither --instrument nor --channels",
          first == metadata_edit.AUTO and dialog.channels_combo.count() == 0
          and not dialog.channels_combo.isEnabled() and "--instrument" not in args and "--channels" not in args,
          f"instrument {first!r}, channels {dialog.channels_combo.count()} item(s), argv {args[3:]}")
    check("with 50, 0 and 90 the command line holds no --dipole-length or --azimuths",
          "--dipole-length" not in args and "--azimuths" not in args, str(args[3:]))
    dialog.dipole_spin.setValue(45.0)
    args = argv()
    check("a usual dipole length of 45 gives --dipole-length 45.0 and no --azimuths",
          flag(args, "--dipole-length") == ["45.0"] and "--azimuths" not in args, str(args[3:]))
    dialog.azimuth_ex_spin.setValue(10.0)
    dialog.azimuth_ey_spin.setValue(100.0)
    args = argv()
    check("azimuths 10 and 100 give --azimuths 10.0 100.0", flag(args, "--azimuths", 2) == ["10.0", "100.0"],
          str(args[3:]))
    check("the empty gain and clock zone give no flag", "--electric-gain" not in args
          and "--clock-timezone" not in args, str(args[3:]))
    dialog.gain_edit.setText("10")
    dialog.clock_edit.setText("Australia/Perth")
    args = argv()
    check("a filled gain and clock zone give --electric-gain 10 and --clock-timezone Australia/Perth",
          flag(args, "--electric-gain") == ["10"] and flag(args, "--clock-timezone") == ["Australia/Perth"],
          str(args[3:]))
    dialog.instrument_combo.setCurrentText("phoenix")
    args = argv()
    check("with phoenix the dipole box is off, says why, and the length typed before is not passed",
          not dialog.dipole_spin.isEnabled() and "record their dipole lengths" in dialog.dipole_spin.toolTip()
          and "--dipole-length" not in args and flag(args, "--instrument") == ["phoenix"], str(args[3:]))
    dialog.instrument_combo.setCurrentText("lemi423")
    args = argv()
    check("with lemi423 the instrument and its default channels are passed, and the dipole box is on",
          flag(args, "--instrument") == ["lemi423"] and flag(args, "--channels") is not None
          and dialog.dipole_spin.isEnabled(), str(args[3:]))
    BOXES.clear()
    dialog.gain_edit.setText("ten")
    dialog.name_edit.setText("forms_gain")
    dialog._accept()
    check("a gain that is not a number keeps the form open with one warning box",
          dialog.result() != QDialog.Accepted and len(BOXES) == 1 and BOXES[0][0] == "warning"
          and "Electric gain (EDL)" in BOXES[0][2], f"result {dialog.result()}, boxes {BOXES}")
    BOXES.clear()
    dialog.deleteLater()

    # the form's command line on a folder of Phoenix recordings, under auto, runs to the end
    phx = SCRATCH / "phx"
    shutil.rmtree(phx, ignore_errors=True)
    for site, (receiver, model, mapping) in phoenix_files_unit.RECEIVERS.items():
        phoenix_files_unit.write_recording(phx / site, receiver, model, mapping)
    shutil.rmtree(SCRATCH / "forms", ignore_errors=True)
    dialog = metadata_edit.NewSurveyDialog(SCRATCH / "forms", window)
    dialog.folder_edit.setText(str(phx))
    args = metadata_edit.new_survey_argv(state, dialog.values(), dialog.out_path())
    done = subprocess.run(args, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=600)
    instrument = (Survey.from_yaml(dialog.out_path()).instrument if dialog.out_path().is_file() else None)
    check("the form's command line on Phoenix recordings under auto exits 0 and makes a Phoenix survey",
          done.returncode == 0 and instrument == "phoenix" and "--dipole-length" not in args,
          f"exit {done.returncode}, instrument {instrument}, {(done.stdout + done.stderr).strip()[-300:]}")
    dialog.deleteLater()


def test_add_sites(app, window, check) -> None:
    """Add sites: refused with unsaved edits, asks with the folders, runs the re-run, reopens the survey."""
    path = make_survey()
    window.open_survey(path)
    pump(app)
    tab, runner = window.metadata_tab, window.state.runner
    jobs = len(runner.jobs)
    find(tab.table, "S02", "dipole_length_ex").setText("44")
    BOXES.clear()
    started = tab.add_sites()
    status = tab.status_label.text()
    check("Add sites with an unsaved edit starts no job, asks nothing and says to save first",
          started is False and len(runner.jobs) == jobs and BOXES == [] and "unsaved change(s)" in status
          and "Save survey.yaml" in status, f"started {started}, boxes {BOXES}, status {status!r}")
    find(tab.table, "S02", "dipole_length_ex").setText("48")
    before = path.read_bytes()
    ANSWERS[:] = [False]
    started = tab.add_sites()
    check("Add sites asks with S03 in the question and starts no job on No",
          started is False and len(runner.jobs) == jobs and len(BOXES) == 1
          and BOXES[0][:2] == ("question", "Add sites")
          and "S03" in BOXES[0][2] and "S01" not in BOXES[0][2], f"boxes {BOXES}")
    BOXES.clear()
    ANSWERS[:] = [True]
    started = tab.add_sites()
    job = runner.jobs[-1] if len(runner.jobs) > jobs else None
    want = metadata_edit.add_sites_argv(window.state)
    check("answered Yes, Add sites starts the re-run of new_survey.py, with no --force",
          started is True and job is not None and job.argv == want and "--force" not in job.argv
          and Path(job.argv[1]).name == "new_survey.py"
          and job.argv[2:] == [str(window.state.survey.data_root), "--name", "flow", "--out", str(path.resolve())],
          f"started {started}, argv {job.argv[2:] if job else None}")
    finished = wait_for(app, lambda: job is not None and job.status in ("done", "failed"), 180)
    pump(app)
    check("the Add sites job ends done", finished and job.status == "done",
          f"status {job.status if job else None}: " + " | ".join(job.output[-6:] if job else []))
    after = path.read_bytes()
    diff = changes(before, after)
    inserted = diff[0][1] if len(diff) == 1 and not diff[0][0] else []
    check("Add sites inserts S03's entry and changes no other line, comments kept",
          len(diff) == 1 and not diff[0][0] and inserted[:1] == ["  S03:\n"]
          and comment_texts(after.decode("utf-8")) == comment_texts(before.decode("utf-8")),
          f"changes {[(o, n[:2]) for o, n in diff]}")
    cell = find(tab.table, "S03", "dipole_length_ex")
    check("after the job the S03 row has editable cells", bool(cell.flags() & Qt.ItemIsEditable),
          f"flags {cell.flags()}")
    status = tab.status_label.text()
    check("the status line shows the script's added line", status.startswith("added 1 site(s): S03"), repr(status))
    jobs = len(runner.jobs)
    BOXES.clear()
    started = tab.add_sites()
    check("a second Add sites starts no job and says there is nothing to add",
          started is False and len(runner.jobs) == jobs and BOXES == []
          and tab.status_label.text() == "nothing to add: every site folder has an entry",
          f"started {started}, boxes {BOXES}, status {tab.status_label.text()!r}")
    write_b423(path.parent / "raw" / "S05" / f"{EPOCH}.B423", 41, "2.1", -31.9, 138.9, 200.0, EPOCH)
    BOXES.clear()
    ANSWERS[:] = [False]
    tab.add_sites()
    check("a folder S05 put there while the survey is open is named by the next Add sites",
          len(BOXES) == 1 and "S05" in BOXES[0][2], f"boxes {BOXES}, status {tab.status_label.text()!r}")


def test_check(app, window, check) -> None:
    """Check: one row per finding, the stops first, the command's text; a double click selects the site."""
    path = make_survey()
    write_b423(path.parent / "raw" / "S.4" / f"{EPOCH}.B423", 40, "2.1", -31.9, 138.9, 200.0, EPOCH)
    text = path.read_bytes().decode("utf-8")
    text = text.replace("    latitude: -31.6  # from the handheld GPS\n    longitude: 138.6\n",
                        "    latitude: -31.6  # from the handheld GPS\n", 1)
    path.write_bytes(text.encode("utf-8"))
    window.open_survey(path)
    pump(app)
    write_b423(path.parent / "raw" / "S06" / f"{EPOCH}.B423", 42, "2.1", -31.9, 138.9, 200.0, EPOCH)
    tab = window.metadata_tab
    found = tab.run_check()
    table = tab.check_table
    rows = [tuple(table.item(r, c).text() for c in range(4)) for r in range(table.rowCount())]
    names = [(level, site, name) for level, site, name, _message in rows]
    check("Check lists the folder S.4's site_name (STOP) first, then the folders S.4, S03 and S06 (put there "
          "after the survey was opened) with no entry and S02 with no position (WARN), one row each",
          names == [("STOP", "S.4", "site_name"), ("WARN", "S.4", "folder_without_entry"),
                    ("WARN", "S03", "folder_without_entry"), ("WARN", "S06", "folder_without_entry"),
                    ("WARN", "S02", "no_position")], str(names))
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "check_survey.py"), str(path), "--all"], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    lines = done.stdout.strip().splitlines()
    want = [f"{level} {name}: {site}: {message}" for level, site, name, message in rows]
    check("each row reads as the line check_survey.py --all prints for it",
          lines[:len(want)] == want and len(found) == len(want), "\n".join(lines[:len(want)])[:400])
    caption = tab.check_label.text().splitlines()
    check("the caption holds the command's line on the usual dipoles and its count line",
          caption == lines[len(want):], f"caption {caption}, command {lines[len(want):]}")
    window.state.set_site(None)
    table.cellDoubleClicked.emit(next((r for r, row in enumerate(rows) if row[1] == "S03"), 0), 3)
    pump(app)
    selected = [tab.table.item(i.row(), 0).text() for i in tab.table.selectionModel().selectedRows()]
    check("a double click on S03's finding sets State.site and selects S03's row",
          window.state.site == "S03" and selected == ["S03"], f"site {window.state.site}, selected {selected}")


def test_save_held(app, window, check) -> None:
    """Save of a survey.yaml that is read-only or held open: quick, nothing written, a message that says why."""
    path = make_survey()
    window.open_survey(path)
    pump(app)
    tab = window.metadata_tab
    for label in ("read-only", "held open by another program"):
        before = path.read_bytes()
        find(tab.table, "S02", "dipole_length_ex").setText("41")
        handle = None
        if label == "read-only":
            os.chmod(path, stat.S_IREAD)
        else:
            handle = open(path, "rb")
        BOXES.clear()
        started = time.time()
        try:
            saved = tab.save()
        finally:
            took = time.time() - started
            if handle is not None:
                handle.close()
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        said = BOXES[-1][2] if BOXES else ""
        check(f"Save of a survey.yaml {label}: under five seconds, nothing written, the box says why and what to do",
              saved is False and took < 5.0 and path.read_bytes() == before
              and "open in another program or read-only" in said and "save again" in said,
              f"save() {saved}, {took:.1f} s, box {said[-160:]!r}")
        find(tab.table, "S02", "dipole_length_ex").setText("48")


def test_swaps(app, window, check) -> None:
    """The two tick boxes: headers, tooltips, the S03 row, Save of a tick and an untick, the rebuild hint."""
    path = make_survey()
    (path.parent / "work" / "mth5").mkdir(parents=True)
    (path.parent / "work" / "mth5" / "S02.h5").write_bytes(b"")
    window.open_survey(path)
    pump(app)
    tab, table = window.metadata_tab, window.metadata_tab.table
    heads = {key: table.horizontalHeaderItem(COLUMNS.index(key)) for key in ("swap_e", "swap_h")}
    labels = {key: item.text() for key, item in heads.items()}
    check("the swap columns are headed Ex and Ey swapped and Hx and Hy swapped",
          labels == {"swap_e": "Ex and Ey swapped", "swap_h": "Hx and Hy swapped"}, str(labels))
    tips = {key: item.toolTip() for key, item in heads.items()}
    ok = all(tip.count(". ") == 1 and tip.endswith(".") and "Rebuild archive" in tip and "built again" in tip
             for tip in tips.values())
    ok = ok and "exchanges the samples of ex and ey" in tips["swap_e"] and "after the exchange" in tips["swap_e"]
    ok = ok and "exchanges the samples of hx and hy" in tips["swap_h"]
    check("each tooltip says in two sentences what ingest exchanges and that the archive must be rebuilt", ok,
          str(tips))
    s03 = [find(table, "S03", key) for key in ("swap_e", "swap_h")]
    check("the S03 boxes cannot be ticked and are greyed",
          all(not c.flags() & Qt.ItemIsUserCheckable and not c.flags() & Qt.ItemIsEnabled
              and c.foreground().color().name() == DISABLED for c in s03), str([c.flags() for c in s03]))

    def save_ticks(ticks: dict) -> tuple:
        before = path.read_bytes()
        for (site, key), state in ticks.items():
            find(table, site, key).setCheckState(Qt.Checked if state else Qt.Unchecked)
        saved = tab.save()
        pump(app)
        return saved, before, path.read_bytes(), tab.status_label.text()

    saved, before, after, status = save_ticks({("S01", "swap_e"): True})
    diff = changes(before, after)
    lines = before.decode("utf-8").splitlines(keepends=True)
    at = lines.index("  S02:\n")  # the line after S01's last key
    new_lines = after.decode("utf-8").splitlines(keepends=True)
    check("a tick on S01 is saved as the one line swap_e: true at the end of S01's entry, nothing else",
          saved is True and diff == [([], ["    swap_e: true\n"])] and new_lines[at] == "    swap_e: true\n"
          and new_lines[:at] == lines[:at] and new_lines[at + 1:] == lines[at:], f"save() {saved}, changes {diff}")
    sites = yaml.safe_load(after.decode("utf-8"))["sites"]
    check("S01 reads swap_e true and S02 is as it was",
          Survey.from_yaml(path).site("S01").swap_e is True and "swap_e" not in sites["S02"]
          and "swap_h" not in sites["S01"], str(sites))
    check("no rebuild is asked for S01, which has no archive", "Rebuild archive" not in status, repr(status))
    saved, before, after, status = save_ticks({("S02", "swap_h"): True})
    diff = changes(before, after)
    check("a tick on S02's Hx and Hy box adds the one line swap_h: true, comments kept",
          saved is True and diff == [([], ["    swap_h: true\n"])]
          and comment_texts(after.decode("utf-8")) == comment_texts(before.decode("utf-8"))
          and yaml.safe_load(after.decode("utf-8"))["sites"]["S02"].get("swap_h") is True,
          f"save() {saved}, changes {diff}")
    check("after a swap change at S02, which has an archive, the status line names S02 and asks for Rebuild archive",
          "the archive of S02 was built before the swap changed" in status and "press Rebuild archive" in status,
          repr(status))
    saved, before, after, status = save_ticks({("S01", "swap_e"): False})
    diff = changes(before, after)
    check("unticking S01's box removes its swap_e line and nothing else",
          saved is True and diff == [(["    swap_e: true\n"], [])]
          and "swap_e" not in yaml.safe_load(after.decode("utf-8"))["sites"]["S01"], f"save() {saved}, changes {diff}")


def test_rebuild(app, window, check) -> None:
    """Rebuild archive: when it is enabled, its question and the command it queues."""
    path = make_survey()
    path.write_bytes(path.read_bytes() + b"  S04:\n    latitude: -31.8\n    longitude: 138.8\n")
    mth5 = path.parent / "work" / "mth5"
    mth5.mkdir(parents=True)
    for site in ("S02", "S03", "S04"):
        (mth5 / f"{site}.h5").write_bytes(b"")
    (path.parent / "filters.yaml").write_text(yaml.safe_dump({"S02": NOTCH}), encoding="utf-8")
    window.open_survey(path)
    pump(app)
    tab, state = window.metadata_tab, window.state
    button = tab.rebuild_button
    state.set_site(None)
    enabled = {None: button.isEnabled()}
    for site in ("S01", "S02", "S03", "S04"):
        state.set_site(site)
        enabled[site] = button.isEnabled()
    check("Rebuild archive is enabled for S02 alone: not with no site, S01 (no archive), S03 (no entry), "
          "S04 (no raw data folder)",
          enabled == {None: False, "S01": False, "S02": True, "S03": False, "S04": False}, str(enabled))
    state.set_site("S02")
    state.runner._process = object()  # a job running, as the runner sees it
    state.runner.queue_changed.emit()
    while_running = button.isEnabled()
    INGESTS.clear()
    ANSWERS[:] = [True]
    index = tab.rebuild_archive()
    ANSWERS.clear()
    state.runner._process = None
    state.runner.queue_changed.emit()
    check("Rebuild archive is off while a job runs and starts nothing",
          not while_running and index is None and INGESTS == [], f"enabled {while_running}, queued {INGESTS}")
    find(tab.table, "S02", "swap_h").setCheckState(Qt.Checked)  # a tick not saved
    BOXES.clear()
    ANSWERS[:] = [True]
    index = tab.rebuild_archive()
    ANSWERS.clear()
    status = tab.status_label.text()
    check("Rebuild archive with a ticked box not saved starts nothing, asks nothing and says to save first",
          index is None and INGESTS == [] and BOXES == []
          and status == "1 unsaved change(s): press Save survey.yaml first, then Rebuild archive",
          f"index {index}, queued {INGESTS}, boxes {BOXES}, status {status!r}")
    find(tab.table, "S02", "swap_h").setCheckState(Qt.Unchecked)
    INGESTS.clear()
    BOXES.clear()
    ANSWERS[:] = [False]
    index = tab.rebuild_archive()
    check("answered No, Rebuild archive queues nothing", index is None and INGESTS == [], str(INGESTS))
    question = BOXES[-1] if BOXES else None
    check("the question names S02, says the archive is replaced and that the filtered variant is built again",
          question == ("question", "Rebuild archive", "Rebuild the archive of S02 from its raw data? The present "
                       "archive is replaced. Its filtered variant is built again from the new archive too."),
          str(question))
    ANSWERS[:] = [True]
    tab.rebuild_archive()
    want = [state.python_exe, str(REPO / "scripts" / "ingest_site.py"), str(state.survey_yaml), "S02", "--force"]
    check("answered Yes, the one command queued is ingest_site.py <survey.yaml> S02 --force",
          len(INGESTS) == 1 and INGESTS[0][0] == want[0] and Path(INGESTS[0][1]).resolve() == Path(want[1]).resolve()
          and INGESTS[0][2:] == want[2:], str(INGESTS))
    state.runner.jobs.append(metadata_edit_job("rebuild MTH5 S02", INGESTS[0] if INGESTS else []))
    tab._job_finished(len(state.runner.jobs) - 1, True)
    check("the status line reports the finished rebuild", tab.status_label.text() == "rebuilt S02.h5 from its raw data",
          repr(tab.status_label.text()))
    (path.parent / "filters.yaml").unlink()
    window.open_survey(path)
    pump(app)
    state.set_site("S02")
    BOXES.clear()
    tab.rebuild_archive()
    check("with no declared filters the question has no sentence on a variant",
          BOXES[-1][2] == "Rebuild the archive of S02 from its raw data? The present archive is replaced."
          if BOXES else False, str(BOXES))


def metadata_edit_job(label: str, argv: list[str]):
    """Return a finished job record as the runner keeps it."""
    from mt_workbench.gui.jobs import Job
    job = Job(label=label, argv=argv)
    job.status = "done"
    return job


def test_site_column(app, window, check) -> None:
    """The site column stays at the left edge, in step with the rows, the sort and the selection."""
    path = make_wide()
    window.resize(1400, 900)
    window.show()
    window.open_survey(path)
    window.tabs.setCurrentWidget(window.metadata_tab)
    pump(app, 0.5)
    tab, state = window.metadata_tab, window.state
    table = tab.table
    fixed = getattr(tab, "site_column", None)

    def in_line(label: str) -> None:
        bad, n = [], 0
        for y in range(2, table.viewport().height(), 6):
            row = table.rowAt(y)
            if row < 0:
                continue
            n += 1
            on_top = table.childAt(table.viewport().mapTo(table, QPoint(3, y)))
            index = (fixed.indexAt(fixed.viewport().mapFromGlobal(table.viewport().mapToGlobal(QPoint(3, y))))
                     if fixed is not None else None)
            shown = index.data() if index is not None and index.isValid() else None
            if fixed is None or on_top is not fixed.viewport() or shown != table.item(row, 0).text():
                bad.append((y, table.item(row, 0).text(), shown))
        check(f"{label}: the site of each row is read at the left edge, at the height of its row",
              n > 10 and not bad, f"{n} points, first wrong {bad[:3]}")

    bar = table.horizontalScrollBar()
    bar.setValue(bar.maximum())
    pump(app)
    check("the table scrolls sideways and is scrolled fully to the right", bar.maximum() > 0
          and bar.value() == bar.maximum(), f"value {bar.value()} of {bar.maximum()}")
    in_line("scrolled fully to the right")
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum() // 2)
    pump(app)
    check("the table scrolls down", table.verticalScrollBar().value() > 0, str(table.verticalScrollBar().value()))
    in_line("scrolled to the middle of its rows")
    table.setRowHeight(table.rowAt(10), 70)
    pump(app)
    in_line("with one row made taller")
    table.sortByColumn(COLUMNS.index("latitude"), Qt.DescendingOrder)
    pump(app)
    in_line("sorted by latitude")
    header = fixed.horizontalHeader() if fixed is not None else None
    if header is not None:
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(header.sectionViewportPosition(0) + 5,
                                                                      header.height() // 2))
        pump(app)
    order = [table.item(r, 0).text() for r in range(table.rowCount())]
    check("a click on the fixed column's header sorts the table by site", order == sorted(order), str(order[:5]))
    in_line("sorted by site")
    row = table.rowAt(table.viewport().height() // 2)
    table.selectRow(row)
    pump(app)
    check("the fixed column shows the row the table selects",
          fixed is not None and fixed.selectionModel().isRowSelected(row, fixed.rootIndex())
          and state.site == table.item(row, 0).text(), f"row {row}, site {state.site}")
    other = table.rowAt(40)
    if fixed is not None:
        QTest.mouseClick(fixed.viewport(), Qt.LeftButton, pos=fixed.visualRect(fixed.model().index(other, 0)).center())
        pump(app)
    selected = [i.row() for i in table.selectionModel().selectedRows()]
    check("a click in the fixed column selects that row of the table and sets State.site",
          selected == [other] and state.site == table.item(other, 0).text(),
          f"selected {selected}, wanted {other}, site {state.site}")
    edits = tab.pending()
    check("after the scrolling, the sorts and the selection the table holds no unsaved change", edits == {},
          str(edits))
    site = table.item(other, 0).text()
    before = path.read_bytes()
    find(table, site, "dipole_length_ey").setText("47")
    saved = tab.save()
    pump(app)
    diff = changes(before, path.read_bytes())
    lines = before.decode("utf-8").splitlines(keepends=True)
    head = lines.index(f"  {site}:\n")
    check("an edit of that row after the sort is saved into its own site's entry",
          saved is True and diff == [([], ["    dipole_length_ey: 47.0\n"])]
          and Survey.from_yaml(path).site(site).dipole_length_ey == 47.0
          and yaml.safe_load(path.read_bytes().decode("utf-8"))["sites"][site].get("dipole_length_ey") == 47.0,
          f"save() {saved}, {site} at line {head}, changes {diff}")
    window.hide()


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

    # a unit typed in a number cell is not saved, and the status line says to type the number alone
    before = path.read_bytes()
    cell("S02", "dipole_length_ex").setText("47 m")
    saved = tab.save()
    pump(app)
    status = tab.status_label.text()
    check("a number cell holding a unit is not saved and the status line says what to type",
          saved is False and path.read_bytes() == before and "type the number alone, with no unit" in status,
          f"save() {saved}, status {status!r}")
    cell("S02", "dipole_length_ex").setText("45")

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

    # the New survey form refuses a name a new survey cannot take, and stays open
    try:
        check_survey_name("n" * 31)
        refusal = None
    except ValueError as exc:
        refusal = str(exc)
    dialog = metadata_edit.NewSurveyDialog(SCRATCH / "flow" / "surveys", window)
    dialog.folder_edit.setText(str(SCRATCH / "flow" / "raw"))
    dialog.name_edit.setText("n" * 31)
    dialog._accept()
    check("the New survey form with a 31-character name stays open and shows the library's message",
          dialog.result() != QDialog.Accepted and refusal is not None and "31 characters: 30 at most" in refusal
          and BOXES == [("warning", "New survey", refusal)], f"result {dialog.result()}, boxes {BOXES}")
    dialog.name_edit.setText("n" * 30)
    dialog._accept()
    check("the New survey form with a 30-character name is accepted with no further box",
          dialog.result() == QDialog.Accepted and len(BOXES) == 1, f"result {dialog.result()}, boxes {BOXES}")
    BOXES.clear()

    # New survey... on a survey.yaml that exists starts no job
    values = dialog.values()
    before, n_jobs = path.read_bytes(), len(window.state.runner.jobs)
    started = metadata_edit.start_new_survey(tab, window.state, values, path)
    pump(app)
    check("New survey... on a survey.yaml that exists starts no job and says to open it and press Add sites",
          started is False and len(window.state.runner.jobs) == n_jobs and path.read_bytes() == before
          and BOXES == [("information", "New survey", f"{path} exists: open it and press Add sites")],
          f"started {started}, jobs {len(window.state.runner.jobs) - n_jobs}, boxes {BOXES}")
    argv = metadata_edit.new_survey_argv(window.state, values, SCRATCH / "flow" / "surveys" / "n" / "survey.yaml")
    check("the command line built for a new survey has no --force",
          "--force" not in argv and Path(argv[1]).name == "new_survey.py" and "--name" in argv, str(argv))
    BOXES.clear()

    # the yellow line and the question before Save are for files another script writes again whole
    for label, generated_by, warned in (
            ("scripts/new_survey.py", "scripts/new_survey.py", False),
            ("another script", "scripts/burra_notes_to_yaml.py", True),
            ("a text that only mentions new_survey.py", "the field sheet script, not new_survey.py", True)):
        path = make_survey()
        text = path.read_bytes().decode("utf-8")
        path.write_bytes(text.replace("defaults:\n", f"generated_by: {generated_by}\ndefaults:\n", 1).encode("utf-8"))
        window.open_survey(path)
        pump(app)
        shown = not tab.warning_label.isHidden()
        before = path.read_bytes()
        cell("S02", "dipole_length_ex").setText("46")
        saved = tab.save()
        pump(app)
        asked = [box for box in BOXES if box[:2] == ("question", "Save survey.yaml")]
        check(f"generated_by {label}: the yellow line {'shown' if warned else 'hidden'}, Save "
              f"{'asks first' if warned else 'asks nothing'}",
              shown is warned and (len(asked) == 1) is warned and saved is (not warned)
              and (path.read_bytes() == before) is warned,
              f"line shown {shown} ({tab.warning_label.text()!r}), questions {len(asked)}, saved {saved}")
        BOXES.clear()

    for part in (test_form, test_add_sites, test_check, test_save_held, test_swaps, test_rebuild, test_site_column):
        print(f"{part.__name__}:")
        BOXES.clear()
        ANSWERS.clear()
        try:
            part(app, window, check)
        except Exception as exc:  # a crash of the code is a failure of the criterion under test
            check(f"{part.__name__} ran", False, f"{type(exc).__name__}: {exc}")

    window.close()
    print()
    if failed:
        print(f"FAIL  gui_new_survey_flow_unit ({len(failed)} of {n_checks} checks failed): {', '.join(failed)}")
        return 1
    print(f"PASS  gui_new_survey_flow_unit (0 of {n_checks} checks failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
