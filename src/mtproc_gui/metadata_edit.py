"""The Metadata tab's editing: the New survey dialog, the sites-block rewrite, cell text.

Kept out of `tabs/metadata.py` so the tab stays a table. Nothing here reads a
B423 file or computes anything: `start_new_survey` queues `scripts/new_survey.py`
on `state.runner` and starts it immediately (`JobRunner.run_now`), rather than
blocking the window on a `subprocess.run` -- one of the jobs exempt from the
"Add to queue"/"Run queue" split, since it is not a processing job (see its
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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton,
)

from mtproc.survey import CHANNEL_PRESETS, INSTRUMENTS as SURVEY_INSTRUMENTS, SITE_TABLE_COLUMNS, default_preset
from mtproc_gui.channels_column import UNCHANGED
from mtproc_gui.theme import DISABLED

EDITABLE = tuple(SITE_TABLE_COLUMNS)  # the table's editable columns, the site table's too
INSTRUMENTS = list(SURVEY_INSTRUMENTS)  # the survey's default; each site's is detected from its files
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


# The EDL electric chain's declared gain column (`SiteConfig.electric_gain`): the site's effective
# number as text, typed over on an EDL row only; Save writes the site's own key only when the number
# differs from the survey default's, as for channels. Hardwired at the field terminal junction box;
# for a survey whose PR6-24 configs were not kept, known only from the field notes -- not a PR6-24
# pre-amplifier setting.
ELECTRIC_GAIN = "electric_gain"
ELECTRIC_GAIN_TIP = "extra gain of the electric chain beyond the reader's own (the x10 terminal box), declared from the field notes"
ELECTRIC_GAIN_ARCHIVE_TIP = "archive built with the old gain - Delete archive then Build MTH5 to change it"
ELECTRIC_GAIN_NOT_EDL = "PR6-24 (EDL) sites only"


def electric_gain_cell(item_class, gain, instrument: str, archived: bool):
    """A site's electric_gain cell: `item_class(text, editable=True)` on an EDL row, else a read-only "-".

    The text is the site's effective gain (default 1.0, no filter), to 10
    significant digits. Greyed with `ELECTRIC_GAIN_ARCHIVE_TIP` when an
    archive exists: it keeps the gain it was built with until rebuilt.
    """
    if instrument != "edl":
        item = item_class("-")
        item.setToolTip(ELECTRIC_GAIN_NOT_EDL)
        return item
    text = f"{float(1.0 if gain is None else gain):.10g}"
    item = item_class(text, editable=True, number=True)
    item.setToolTip(ELECTRIC_GAIN_ARCHIVE_TIP if archived else ELECTRIC_GAIN_TIP)
    if archived:
        item.setForeground(QColor(DISABLED))
    return item


def electric_gain_edit(survey, site: str, text: str | None, shown: str | None):
    """An electric_gain cell's text -> the site's key to write: a number, None to drop it, or UNCHANGED.

    UNCHANGED when the cell reads the same number it was loaded with
    (`shown`) or is not editable (no `shown`); None when it reads the survey
    default's number, so the default applies again; else the number. Raises
    ValueError naming the site for text that is not a number.
    """
    if text is None or shown is None or text == shown:
        return UNCHANGED
    try:
        new = float(text)
    except ValueError:
        raise ValueError(f"{site}: electric_gain {text!r} is not a number") from None
    try:
        if new == float(shown):
            return UNCHANGED
    except ValueError:  # loaded with something unparsable: any valid number is a change
        pass
    default = survey.defaults.get(ELECTRIC_GAIN)
    default = 1.0 if default is None else float(default)
    return None if new == default else new


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
    """scripts/new_survey.py's arguments: folders, name, instrument, channels, time zone, site table.

    The workspace (archives, TFs, figures) defaults to `<data folder>/work`,
    beside the raw data -- a 100-site survey's archives run to hundreds of GB
    -- and follows the data folder until it is typed over or browsed to.
    "channels recorded", beside the instrument, offers that instrument's
    presets (`mtproc.survey.CHANNEL_PRESETS`, its default preselected) and
    becomes `--channels`, the survey's `defaults: channels:`.
    """

    def __init__(self, surveys_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New survey")
        self.surveys_dir = Path(surveys_dir)
        self.folder_edit = QLineEdit(self)
        self.folder_edit.setPlaceholderText("the folder holding one subfolder of B423 files per site")
        self.workspace_edit = QLineEdit(self)
        self.workspace_edit.setPlaceholderText("archives, TFs and figures: <data folder>/work by default")
        self.name_edit = QLineEdit(self)
        self.instrument_combo = QComboBox(self)
        self.instrument_combo.addItems(INSTRUMENTS)
        self.channels_combo = QComboBox(self)
        self.channels_combo.setToolTip("the columns that had a sensor attached: the survey's defaults, "
                                       "applied at ingest; a site that differs is set on the Metadata table")
        self.timezone_edit = QLineEdit(DEFAULT_TIMEZONE, self)
        self.table_edit = QLineEdit(self)
        self.table_edit.setPlaceholderText("optional: CSV or XLSX, a site column + any editable column")
        self.out_label = QLabel(self)
        folder_button = QPushButton("Browse...", self)
        folder_button.clicked.connect(self._pick_folder)
        workspace_button = QPushButton("Browse...", self)
        workspace_button.clicked.connect(self._pick_workspace)
        table_button = QPushButton("Browse...", self)
        table_button.clicked.connect(self._pick_table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        instrument_row = QHBoxLayout()  # one row: the channels a survey records depend on the instrument
        instrument_row.addWidget(self.instrument_combo)
        instrument_row.addWidget(QLabel("channels recorded", self))
        instrument_row.addWidget(self.channels_combo, 1)
        grid = QGridLayout(self)
        for row, (text, widget) in enumerate([
            ("Data folder", self.folder_edit), ("Workspace folder", self.workspace_edit),
            ("Survey name", self.name_edit), ("Instrument", instrument_row),
            ("Time zone (IANA)", self.timezone_edit), ("Site table", self.table_edit),
        ]):
            grid.addWidget(QLabel(text, self), row, 0)
            if isinstance(widget, QHBoxLayout):
                grid.addLayout(widget, row, 1)
            else:
                grid.addWidget(widget, row, 1)
        grid.addWidget(folder_button, 0, 2)
        grid.addWidget(workspace_button, 1, 2)
        grid.addWidget(table_button, 5, 2)
        grid.addWidget(self.out_label, 6, 0, 1, 3)
        grid.addWidget(buttons, 7, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        self.resize(640, self.sizeHint().height())

        self.folder_edit.textChanged.connect(self._folder_changed)
        self.name_edit.textChanged.connect(self._show_out)
        self.instrument_combo.currentTextChanged.connect(self._fill_channels)
        self._fill_channels(self.instrument_combo.currentText())
        self._show_out()

    def _fill_channels(self, instrument: str) -> None:
        """The instrument's channel presets, its default selected."""
        self.channels_combo.clear()
        self.channels_combo.addItems(list(CHANNEL_PRESETS.get(instrument, {})))
        if instrument in CHANNEL_PRESETS:
            self.channels_combo.setCurrentText(default_preset(instrument))

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder of site folders", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def _pick_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Workspace folder", self.workspace_edit.text())
        if path:
            self.workspace_edit.setText(path)
            self.workspace_edit.setModified(True)  # chosen: it no longer follows the data folder

    def _pick_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Site table", self.folder_edit.text(), TABLE_FILTER)
        if path:
            self.table_edit.setText(path)

    def _folder_changed(self, text: str) -> None:
        """The name follows the folder's, and the workspace is <folder>/work, until typed over."""
        if not self.name_edit.isModified():
            self.name_edit.setText(Path(text.strip()).name if text.strip() else "")
        if not self.workspace_edit.isModified():
            self.workspace_edit.setText(str(Path(text.strip()) / "work") if text.strip() else "")

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
            "workspace": self.workspace_edit.text().strip() or None,
            "name": self.name_edit.text().strip(),
            "instrument": self.instrument_combo.currentText(),
            "channels": self.channels_combo.currentText() or None,
            "timezone": self.timezone_edit.text().strip() or DEFAULT_TIMEZONE,
            "site_table": self.table_edit.text().strip() or None,
        }


def new_survey_argv(state, values: dict, out: Path, force: bool) -> list[str]:
    """The scripts/new_survey.py command line for the dialog's values."""
    argv = [state.python_exe, state.script("new_survey.py"), values["data_root"],
            "--name", values["name"], "--instrument", values["instrument"],
            "--timezone", values["timezone"], "--out", str(out)]
    if values.get("channels"):
        argv += ["--channels", values["channels"]]
    if values.get("workspace"):
        argv += ["--workspace", values["workspace"]]
    if values.get("site_table"):
        argv += ["--site-table", values["site_table"]]
    return argv + (["--force"] if force else [])


def is_new_survey_job(job) -> bool:
    """True for a job whose argv names scripts/new_survey.py (not some other job on the queue)."""
    return len(job.argv) > 1 and Path(job.argv[1]).name == "new_survey.py"


def start_new_survey(parent, state, values: dict, out: Path) -> bool:
    """Queue scripts/new_survey.py on state.runner and start it immediately.

    Not a processing job -- it never opens an MTH5 archive -- so it skips the
    "Add to queue"/"Run queue" split the processing jobs follow: it is added
    and started here in one call (`JobRunner.run_now`, which leaves any job
    already queued waiting for Run queue), right after `MetadataTab.new_survey`
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
    state.runner.run_now(f"new survey {values['name']}", argv)
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
