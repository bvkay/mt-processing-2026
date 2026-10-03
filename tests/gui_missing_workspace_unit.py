# -*- coding: utf-8 -*-
"""
Unit test for opening a survey whose workspace folder does not exist (run headless)

**This test fails if** `MainWindow.open_survey`, on a survey whose
`workspace:` folder and its parent folder do not exist, opens a modal
message box of any kind, does not show one non-modal box
(`MainWindow.workspace_notice`, visible, window modality NonModal) naming
that folder and the `workspace:` key, does not say in the status bar that
the folder does not exist, starts fetch_basemap.py, or leaves the folder
created. As controls, it fails if any of these shows a box or a notice, puts
anything but the usual "<n> sites, data_root ..., workspace ..." line in the
status bar, or does not start fetch_basemap.py exactly once: the same survey
with its workspace folder made (empty); the clean-clone case, a survey.yaml
without a `workspace:` key whose default `<survey dir>/work` is not made (a
synthetic one, and a copy of the tracked curnamona_cube survey.yaml,
filters.yaml and reference_edis.yaml, unchanged, without `work/`); and
new_survey.py's `<data_root>/work`, named by the key and not made, on first
open. It fails too if a finished New survey job
(`metadata_edit.handle_new_survey_finished`) on a survey.yaml whose
workspace and its parent do not exist yet does not make that folder and
start fetch_basemap.py (the new survey's basemap, as before) without a box;
or if a finished New survey job whose workspace folder cannot be made
(its parent path is a file, or the folder's own path is a file) does not
open the survey, opens a modal box, does not show the non-modal notice
naming the folder as not made, does not say so in the status bar, or
starts fetch_basemap.py.

The surveys are written into a scratch folder: one LEMI-423 site, S01, with
a position and a raw folder holding one empty B423 file named by its epoch.
`JobRunner.run_now` is wrapped at the class level before the window is
built: a call naming fetch_basemap.py is recorded instead of started, as
tests/gui_smoke.py does, so the test runs offline. `QMessageBox.warning`,
`critical`, `information` and `question` and `QMessageBox.exec` are replaced
by recorders that return at once, so a modal box is counted instead of
holding the test.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/gui_missing_workspace_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import yaml

if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.gui import metadata_edit  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("gui_missing_workspace_unit")
CURNAMONA = REPO / "surveys" / "curnamona_cube"
EPOCH = 1624510579
FETCHES: list[list[str]] = []
BOXES: list[tuple[str, str, str]] = []  # modal boxes: (kind, title, text)
_real_run_now = JobRunner.run_now


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


def _exec(self):
    """Record a modal `QMessageBox.exec` instead of waiting on it."""
    BOXES.append(("exec", self.windowTitle(), self.text()))
    return QMessageBox.Ok


JobRunner.run_now = _recording_run_now
for _kind in ("warning", "critical", "information", "question"):
    setattr(QMessageBox, _kind, _box(_kind))
QMessageBox.exec = _exec


def pump(app: QApplication, seconds: float = 0.3) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def make_survey(name: str, workspace: str | None = "not_made/work") -> tuple[Path, Path]:
    """Write the survey of the module docstring; return (survey.yaml, its workspace, not made).

    Args:
        name (str): The survey's name and its scratch folder.
        workspace (str | None): The `workspace:` key relative to the survey
            folder, or None for no key (the default `<survey dir>/work`).
    """
    root = SCRATCH / name
    shutil.rmtree(root, ignore_errors=True)
    (root / "raw" / "S01").mkdir(parents=True)
    (root / "raw" / "S01" / f"{EPOCH}.B423").write_bytes(b"")
    config = {"name": name, "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
              "sites": {"S01": {"latitude": -31.5, "longitude": 138.5}}}
    if workspace is not None:
        config["workspace"] = str(root / workspace)
    (root / "survey.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root / "survey.yaml", root / (workspace or "work")


def copy_curnamona() -> tuple[Path, Path]:
    """Copy the tracked curnamona_cube survey files, unchanged, without `work/`; return (survey.yaml, work)."""
    root = SCRATCH / "curnamona_clean"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for name in ("survey.yaml", "filters.yaml", "reference_edis.yaml"):
        shutil.copy2(CURNAMONA / name, root / name)
    return root / "survey.yaml", root / "work"


def main() -> int:
    print(__doc__.split("**This test fails if**")[1].split("The surveys are written")[0].strip())
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

    def notice_up() -> bool:
        notice = getattr(window, "workspace_notice", None)
        return notice is not None and notice.isVisible()

    def opens_as_before(label: str, survey_yaml: Path, workspace: Path) -> None:
        """Open a survey whose workspace is reachable: no box, no notice, the usual status line, one fetch."""
        n_boxes, n_fetches = len(BOXES), len(FETCHES)
        window.open_survey(survey_yaml)
        pump(app)
        status = window.statusBar().currentMessage()
        want = [[sys.executable, str(REPO / "scripts" / "fetch_basemap.py"), str(survey_yaml.resolve())]]
        check(f"{label}: no box and no notice", len(BOXES) == n_boxes and not notice_up(),
              f"modal boxes {BOXES[n_boxes:]}, notice up {notice_up()}")
        check(f"{label}: the usual status line",
              " sites, data_root " in status and status.endswith(f"workspace {workspace}"), repr(status))
        check(f"{label}: one fetch", FETCHES[n_fetches:] == want, f"fetches {FETCHES[n_fetches:]}, expected {want}")

    # the workspace and its parent missing: one non-modal notice naming the folder, no fetch, nothing made
    survey_yaml, workspace = make_survey("missing")
    window.open_survey(survey_yaml)
    pump(app)
    notice = getattr(window, "workspace_notice", None)
    text = notice.text() if notice is not None else ""
    status = window.statusBar().currentMessage()
    check("no modal box", BOXES == [], f"modal boxes {BOXES}")
    check("one non-modal notice naming the folder and the key",
          notice is not None and notice.isVisible() and not notice.isModal()
          and notice.windowModality() == Qt.NonModal and str(workspace) in text and "`workspace:`" in text,
          "no notice" if notice is None else
          f"visible {notice.isVisible()}, modal {notice.isModal()}, modality {notice.windowModality()}, text {text!r}")
    check("the status bar names the folder", str(workspace) in status and "does not exist" in status, repr(status))
    check("no basemap fetch", FETCHES == [], f"fetches {FETCHES}")
    check("the folder is not made", not workspace.parent.exists(), f"{workspace.parent} exists: "
          f"{workspace.parent.exists()}")

    # control: the same survey with its workspace made, empty
    workspace.mkdir(parents=True)
    opens_as_before("control, empty workspace", survey_yaml, workspace)

    # clean-clone controls: workspaces not made yet, whose parent folder exists
    no_key_yaml, no_key_work = make_survey("no_key", workspace=None)
    opens_as_before("clean clone, no workspace key", no_key_yaml, no_key_work)
    check("clean clone, no workspace key: work/ not made by the window", not no_key_work.exists(),
          f"{no_key_work} exists: {no_key_work.exists()}")
    cur_yaml, cur_work = copy_curnamona()
    opens_as_before("clean clone, tracked curnamona_cube", cur_yaml, cur_work)
    first_yaml, first_work = make_survey("first_open", workspace="raw/work")
    opens_as_before("new_survey.py's <data_root>/work on first open", first_yaml, first_work)

    # control: a finished New survey job whose workspace and its parent do not exist yet
    new_yaml, new_workspace = make_survey("new")
    n_boxes, n_fetches = len(BOXES), len(FETCHES)
    index = window.state.runner.add("new survey new", [sys.executable, str(REPO / "scripts" / "new_survey.py"),
                                                       str(new_yaml.parent / "raw"), "--out", str(new_yaml)])
    metadata_edit.handle_new_survey_finished(window.metadata_tab, window.state, index, True)
    pump(app)
    want = [[sys.executable, str(REPO / "scripts" / "fetch_basemap.py"), str(new_yaml.resolve())]]
    check("control, New survey: the workspace made", new_workspace.is_dir(), str(new_workspace))
    check("control, New survey: opened with one fetch and no box",
          window.state.survey_yaml == new_yaml.resolve() and FETCHES[n_fetches:] == want and len(BOXES) == n_boxes,
          f"opened {window.state.survey_yaml}, fetches {FETCHES[n_fetches:]}, boxes {BOXES[n_boxes:]}")

    # a finished New survey job whose workspace folder cannot be made: opened, reported, nothing fetched
    for label, name, key in (("New survey, the workspace's parent a file", "new_parent_file", "blocker/work"),
                             ("New survey, the workspace a file", "new_workspace_file", "work_file")):
        unmade_yaml, unmade = make_survey(name, workspace=key)
        (unmade_yaml.parent / key.split("/")[0]).write_text("a file, not a folder", encoding="utf-8")
        n_boxes, n_fetches = len(BOXES), len(FETCHES)
        index = window.state.runner.add(f"new survey {name}", [
            sys.executable, str(REPO / "scripts" / "new_survey.py"), str(unmade_yaml.parent / "raw"),
            "--out", str(unmade_yaml)])
        metadata_edit.handle_new_survey_finished(window.metadata_tab, window.state, index, True)
        pump(app)
        notice = getattr(window, "workspace_notice", None)
        text = notice.text() if notice is not None else ""
        status = window.statusBar().currentMessage()
        check(f"{label}: the survey opened", window.state.survey_yaml == unmade_yaml.resolve(),
              f"opened {window.state.survey_yaml}")
        check(f"{label}: no modal box", len(BOXES) == n_boxes, f"modal boxes {BOXES[n_boxes:]}")
        check(f"{label}: one non-modal notice naming the folder as not made",
              notice is not None and notice.isVisible() and not notice.isModal()
              and notice.windowModality() == Qt.NonModal and str(unmade) in text and "could not be made" in text,
              "no notice" if notice is None else
              f"visible {notice.isVisible()}, modality {notice.windowModality()}, text {text!r}")
        check(f"{label}: the status bar names the folder", str(unmade) in status and "could not be made" in status,
              repr(status))
        check(f"{label}: no basemap fetch", FETCHES[n_fetches:] == [], f"fetches {FETCHES[n_fetches:]}")

    window.close()
    pump(app, 0.2)
    print(f"\n{'FAIL' if failed else 'PASS'}  gui_missing_workspace_unit ({len(failed)} of {n_checks} checks failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
