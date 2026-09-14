"""The Metadata tab's editing: the New survey dialog, the sites-block rewrite, cell text.

Kept out of `tabs/metadata.py` so the tab stays a table. Nothing here reads a
B423 file or computes anything: `start_new_survey` queues `scripts/new_survey.py`
on `state.runner` and starts it immediately, rather than blocking the window
on a `subprocess.run` -- it is the one job in this GUI exempt from the "Add
to queue"/"Run queue" split, since it is not a processing job (see its
docstring). `handle_new_survey_finished` -- wired to `state.runner.job_finished`
by `MetadataTab` once, in `__init__` -- opens the survey.yaml it wrote once it
is done, or reports its failure; progress meanwhile shows in the console
strip through the runner's own `log_line`, like any other job's.
`rewrite_sites_block` writes the table's edits into `survey.yaml` the way
`scripts/burra_notes_to_yaml.py`'s `write_sites_block` does -- only the
`sites:` block is rewritten (`yaml.safe_dump`, two-space indent), everything
above it is kept byte for byte -- and, beyond that function, any top-level
key after the block is kept byte for byte too, as are the file's line endings
and every per-site key the table does not show. Comments *inside* the sites
block are lost, as they are when the generator scripts rewrite it.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import indent

import yaml
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton,
)

from bbmt.survey import SITE_TABLE_COLUMNS

EDITABLE = tuple(SITE_TABLE_COLUMNS)  # the table's editable columns, the site table's too
INSTRUMENTS = ["lemi423"]
DEFAULT_TIMEZONE = "Australia/Adelaide"
TABLE_FILTER = "Site table (*.csv *.xlsx *.xls);;All files (*)"


def ask_yes_no(parent, title: str, text: str) -> bool:
    """A Yes/No question with No the default (the smoke test replaces this function)."""
    answer = QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return answer == QMessageBox.Yes


def format_cell(column: str, value) -> str:
    """A YAML value as the table shows it: numbers to 10 significant digits, a dash for none."""
    if value is None:
        return "-"
    if SITE_TABLE_COLUMNS.get(column) is float:
        return f"{float(value):.10g}"
    return str(value).replace("\n", " ")


def parse_cell(column: str, text: str):
    """A cell's text -> the YAML value; None (blank or a dash) drops the site's own key.

    Raises ValueError for a number column that does not read as a number.
    """
    text = text.strip()
    if text in ("", "-"):
        return None
    return float(text) if SITE_TABLE_COLUMNS[column] is float else text


def rewrite_sites_block(yaml_path: str | Path, edits: dict[str, dict]) -> None:
    """Apply {site: {key: value, or None to drop the key}} to survey.yaml's `sites:` block.

    The block runs from the top-level `sites:` line to the next top-level key
    (a comment or blank line right above that key stays with it); the text
    before and after it is written back unchanged, with the file's own line
    endings. A file with no `sites:` key gets one at the end.
    """
    path = Path(yaml_path)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.split(":", 1)[0] == "sites" and ":" in line]
    if len(starts) > 1:
        raise ValueError(f"more than one top-level 'sites:' key in {path}")
    start = end = starts[0] if starts else len(lines)
    if starts:
        end = next((k for k in range(start + 1, len(lines))
                    if lines[k].strip() and not lines[k].startswith((" ", "\t", "#"))), len(lines))
        while end > start + 1 and (lines[end - 1].startswith("#") or not lines[end - 1].strip()):
            end -= 1
    head, tail = "".join(lines[:start]), "".join(lines[end:])
    if head and not head.endswith("\n"):
        head += newline

    sites = (yaml.safe_load(text) or {}).get("sites") or {}
    for site, changes in edits.items():
        entry = dict(sites.get(site) or {})
        for key, value in changes.items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
        sites[site] = entry
    body = yaml.safe_dump(sites, sort_keys=False, allow_unicode=True, default_flow_style=False)
    block = ("sites:\n" + indent(body, "  ")).replace("\n", newline)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(head + block + tail)


class NewSurveyDialog(QDialog):
    """Folder, name, instrument, timezone and an optional site table for scripts/new_survey.py."""

    def __init__(self, surveys_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New survey")
        self.surveys_dir = Path(surveys_dir)
        self.folder_edit = QLineEdit(self)
        self.folder_edit.setPlaceholderText("the folder holding one subfolder of B423 files per site")
        self.name_edit = QLineEdit(self)
        self.instrument_combo = QComboBox(self)
        self.instrument_combo.addItems(INSTRUMENTS)
        self.timezone_edit = QLineEdit(DEFAULT_TIMEZONE, self)
        self.table_edit = QLineEdit(self)
        self.table_edit.setPlaceholderText("optional: CSV or XLSX, a site column + any editable column")
        self.out_label = QLabel(self)
        folder_button = QPushButton("Browse...", self)
        folder_button.clicked.connect(self._pick_folder)
        table_button = QPushButton("Browse...", self)
        table_button.clicked.connect(self._pick_table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        grid = QGridLayout(self)
        for row, (text, widget) in enumerate([
            ("Data folder", self.folder_edit), ("Survey name", self.name_edit),
            ("Instrument", self.instrument_combo), ("Time zone (IANA)", self.timezone_edit),
            ("Site table", self.table_edit),
        ]):
            grid.addWidget(QLabel(text, self), row, 0)
            grid.addWidget(widget, row, 1)
        grid.addWidget(folder_button, 0, 2)
        grid.addWidget(table_button, 4, 2)
        grid.addWidget(self.out_label, 5, 0, 1, 3)
        grid.addWidget(buttons, 6, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        self.resize(640, self.sizeHint().height())

        self.folder_edit.textChanged.connect(self._folder_changed)
        self.name_edit.textChanged.connect(self._show_out)
        self._show_out()

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of site folders", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def _pick_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Site table", self.folder_edit.text(), TABLE_FILTER)
        if path:
            self.table_edit.setText(path)

    def _folder_changed(self, text: str) -> None:
        """The name follows the folder's until it is typed over."""
        if not self.name_edit.isModified():
            self.name_edit.setText(Path(text.strip()).name if text.strip() else "")

    def out_path(self) -> Path:
        return self.surveys_dir / self.name_edit.text().strip() / "survey.yaml"

    def _show_out(self) -> None:
        name = self.name_edit.text().strip()
        self.out_label.setText(f"writes {self.out_path()}" if name else "")

    def _accept(self) -> None:
        if not Path(self.folder_edit.text().strip()).is_dir():
            QMessageBox.warning(self, "New survey", "Pick the folder that holds the site folders.")
        elif not self.name_edit.text().strip():
            QMessageBox.warning(self, "New survey", "Give the survey a name.")
        else:
            self.accept()

    def values(self) -> dict:
        return {
            "data_root": self.folder_edit.text().strip(),
            "name": self.name_edit.text().strip(),
            "instrument": self.instrument_combo.currentText(),
            "timezone": self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
            "site_table": self.table_edit.text().strip() or None,
        }


def new_survey_argv(state, values: dict, out: Path, force: bool) -> list[str]:
    """The scripts/new_survey.py command line for the dialog's values."""
    argv = [state.python_exe, state.script("new_survey.py"), values["data_root"],
            "--name", values["name"], "--instrument", values["instrument"],
            "--timezone", values["timezone"], "--out", str(out)]
    if values.get("site_table"):
        argv += ["--site-table", values["site_table"]]
    return argv + (["--force"] if force else [])


def is_new_survey_job(job) -> bool:
    """True for a job whose argv names scripts/new_survey.py (not some other job on the queue)."""
    return len(job.argv) > 1 and Path(job.argv[1]).name == "new_survey.py"


def start_new_survey(parent, state, values: dict, out: Path) -> bool:
    """Queue scripts/new_survey.py on state.runner and start it immediately.

    Not a processing job -- it never opens an MTH5 archive -- so it skips the
    "Add to queue"/"Run queue" split every other job in this GUI follows: it
    is added and started here in one call, right after `MetadataTab.new_survey`
    closes the dialog, rather than left queued for a press of "Run queue".
    Its progress reaches the console strip the way any job's does, through
    the runner's own `log_line`; `handle_new_survey_finished`, wired to
    `state.runner.job_finished` by `MetadataTab` once, in `__init__`, opens
    the survey.yaml it wrote once it is done. An existing survey.yaml is
    overwritten (--force) only after a Yes. A job already running is refused
    here -- tell the student to wait -- rather than queued behind it, so
    there is never more than one new-survey job in flight. Returns True if
    the job was queued.
    """
    if state.runner.running:
        QMessageBox.information(
            parent, "New survey",
            "A job is already running - wait for it to finish, then try New survey... again.")
        return False
    out = Path(out)
    force = out.exists()
    if force and not ask_yes_no(parent, "New survey",
                                f"{out} exists.\n\nOverwrite it? Every edit made in it is lost."):
        return False
    argv = new_survey_argv(state, values, out, force)
    state.runner.add(f"new survey {values['name']}", argv)
    state.runner.run_queue()
    return True


def handle_new_survey_finished(parent, state, index: int, ok: bool) -> None:
    """state.runner.job_finished slot: open the survey.yaml a new-survey job wrote, or report its failure.

    Every finished job fires this signal, including a processing run queued
    from the Process tab, so anything that is not new_survey.py
    (`is_new_survey_job`) is ignored here.
    """
    job = state.runner.jobs[index] if 0 <= index < len(state.runner.jobs) else None
    if job is None or not is_new_survey_job(job):
        return
    if not ok:
        QMessageBox.critical(parent, "New survey failed",
                             f"{job.label} exited {job.exit_code}:\n\n" + "\n".join(job.output[-8:]))
        return
    out = Path(job.argv[job.argv.index("--out") + 1])
    try:
        state.open_survey(out)
    except Exception as exc:  # a bad YAML should not kill the window
        QMessageBox.critical(parent, "Could not open survey", f"{out}\n\n{exc}")
