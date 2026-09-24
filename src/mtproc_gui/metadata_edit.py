# -*- coding: utf-8 -*-
"""
Editing support for the Metadata tab

Holds the New survey dialog, the rewrite of the `sites:` block of
survey.yaml, and the conversion between YAML values and table cell text.

`start_new_survey` queues `scripts/new_survey.py` on `state.runner` and
starts it immediately with `JobRunner.run_now`, so the window stays
responsive while it runs. `handle_new_survey_finished`, connected to
`state.runner.job_finished` by `MetadataTab`, opens the survey.yaml the job
wrote or reports its failure. Progress shows in the console strip through
the runner's `log_line`.

`rewrite_sites_block` writes the table's edits into survey.yaml in the same
way as `write_sites_block` in `scripts/burra_notes_to_yaml.py`: only the
`sites:` block is rewritten (`yaml.safe_dump`, two-space indent). The text
above the block and any top-level keys after it are kept unchanged, as
are the file's line endings and every per-site key the table does not show.
Comments inside the `sites:` block are lost, as with the generator scripts.

@author: ben kay (ben@auscope.org.au)

:license: MIT
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
    """Ask a Yes/No question with No as the default; True for Yes.

    The GUI smoke test replaces this function.
    """
    answer = QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return answer == QMessageBox.Yes


def format_cell(column: str, value) -> str:
    """Format a YAML value for the table: numbers to 10 significant digits, "-" for None."""
    if value is None:
        return "-"
    if SITE_TABLE_COLUMNS.get(column) is float:
        return f"{float(value):.10g}"
    return str(value).replace("\n", " ")


# The EDL electric chain's declared gain column (`SiteConfig.electric_gain`): the site's effective
# number as text, editable on an EDL row only; Save writes the site's own key only when the number
# differs from the survey default, as for channels. The gain is hardwired at the field terminal
# junction box and, for a survey whose PR6-24 configs were not kept, is known from the field notes;
# it is separate from the PR6-24 pre-amplifier setting.
ELECTRIC_GAIN = "electric_gain"
ELECTRIC_GAIN_TIP = "extra gain of the electric chain beyond the reader's own (the x10 terminal box), declared from the field notes"
ELECTRIC_GAIN_ARCHIVE_TIP = "archive built with the old gain - Delete archive then Build MTH5 to change it"
ELECTRIC_GAIN_NOT_EDL = "PR6-24 (EDL) sites only"


def electric_gain_cell(item_class, gain, instrument: str, archived: bool):
    """Build a site's electric_gain cell.

    On an EDL row the cell is editable and shows the site's effective gain
    (default 1.0, no filter) to 10 significant digits; on any other row it
    is a read-only "-". When an archive exists the cell is greyed with
    `ELECTRIC_GAIN_ARCHIVE_TIP`, since the archive keeps the gain it was
    built with until rebuilt.

    Args:
        item_class: Table item class.
        gain (float | None): The site's effective gain.
        instrument (str): The site's instrument key.
        archived (bool): Whether the site's archive exists.

    Returns:
        The table item.
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
    """Work out the site's electric_gain value to write from an edited cell.

    Args:
        survey: The open `mtproc.survey.Survey`.
        site (str): Site name, used in the error message.
        text (str | None): The cell text now.
        shown (str | None): The cell text as loaded; None for a read-only cell.

    Returns:
        `UNCHANGED` when the cell reads the number it was loaded with or is
        not editable; None when it reads the survey default, so the site's
        key is dropped; otherwise the number.

    Raises:
        ValueError: If the text is not a number.
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
    except ValueError:  # loaded text is not a number: any valid number is a change
        pass
    default = survey.defaults.get(ELECTRIC_GAIN)
    default = 1.0 if default is None else float(default)
    return None if new == default else new


def parse_cell(column: str, text: str):
    """Parse a cell's text into its YAML value.

    Args:
        column (str): Column name from `SITE_TABLE_COLUMNS`.
        text (str): The cell text.

    Returns:
        The value; None for a blank or "-" cell, which drops the site's key.

    Raises:
        ValueError: If a number column does not read as a number.
    """
    text = text.strip()
    if text in ("", "-"):
        return None
    return float(text) if SITE_TABLE_COLUMNS[column] is float else text


def rewrite_sites_block(yaml_path: str | Path, edits: dict[str, dict]) -> None:
    """Apply per-site edits to the `sites:` block of a survey.yaml.

    The block runs from the top-level `sites:` line to the next top-level
    key; comments or blank lines directly above that key stay with it. The
    text before and after the block is written back unchanged with the
    file's own line endings. A file with no `sites:` key gets one at the end.

    Args:
        yaml_path (str | Path): The survey.yaml.
        edits (dict[str, dict]): {site: {key: value}}; a value of None drops
            the key.

    Raises:
        ValueError: If the file has more than one top-level `sites:` key.
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
    """Dialog for the arguments of scripts/new_survey.py.

    Collects the data folder, workspace, survey name, instrument, channels
    recorded, time zone and optional site table. The workspace (archives,
    TFs, figures) defaults to `<data folder>/work` beside the raw data, since
    a 100-site survey's archives run to hundreds of GB, and follows the data
    folder until it is typed over or browsed to. "channels recorded" offers
    the instrument's presets (`mtproc.survey.CHANNEL_PRESETS`, its default
    preselected) and becomes `--channels`, the survey's
    `defaults: channels:`.

    Args:
        surveys_dir (Path): Folder the survey's own folder is created in.
        parent (QWidget | None): Qt parent.
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

        instrument_row = QHBoxLayout()  # instrument and channels share a row: the presets depend on the instrument
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
        """Fill the channels combo with the instrument's presets, its default selected."""
        self.channels_combo.clear()
        self.channels_combo.addItems(list(CHANNEL_PRESETS.get(instrument, {})))
        if instrument in CHANNEL_PRESETS:
            self.channels_combo.setCurrentText(default_preset(instrument))

    def _pick_folder(self) -> None:
        """Browse for the data folder."""
        path = QFileDialog.getExistingDirectory(self, "Folder of site folders", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def _pick_workspace(self) -> None:
        """Browse for the workspace folder, which then stops following the data folder."""
        path = QFileDialog.getExistingDirectory(self, "Workspace folder", self.workspace_edit.text())
        if path:
            self.workspace_edit.setText(path)
            self.workspace_edit.setModified(True)  # chosen: it no longer follows the data folder

    def _pick_table(self) -> None:
        """Browse for the site table."""
        path, _ = QFileDialog.getOpenFileName(self, "Site table", self.folder_edit.text(), TABLE_FILTER)
        if path:
            self.table_edit.setText(path)

    def _folder_changed(self, text: str) -> None:
        """Update the name to the folder's and the workspace to <folder>/work, unless typed over."""
        if not self.name_edit.isModified():
            self.name_edit.setText(Path(text.strip()).name if text.strip() else "")
        if not self.workspace_edit.isModified():
            self.workspace_edit.setText(str(Path(text.strip()) / "work") if text.strip() else "")

    def out_path(self) -> Path:
        """`<surveys_dir>/<name>/survey.yaml`."""
        return self.surveys_dir / self.name_edit.text().strip() / "survey.yaml"

    def _show_out(self) -> None:
        """Show the path the survey.yaml will be written to."""
        name = self.name_edit.text().strip()
        self.out_label.setText(f"writes {self.out_path()}" if name else "")

    def _accept(self) -> None:
        """Accept when the data folder exists and a name is given; otherwise warn."""
        if not Path(self.folder_edit.text().strip()).is_dir():
            QMessageBox.warning(self, "New survey", "Pick the folder that holds the site folders.")
        elif not self.name_edit.text().strip():
            QMessageBox.warning(self, "New survey", "Give the survey a name.")
        else:
            self.accept()

    def values(self) -> dict:
        """Return the dialog's values; empty optional fields are None."""
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
    """Build the scripts/new_survey.py command line.

    Args:
        state: The shared `mtproc_gui.app.State`.
        values (dict): `NewSurveyDialog.values()`.
        out (Path): The survey.yaml to write.
        force (bool): Add `--force` to overwrite an existing file.

    Returns:
        list[str]: The command line.
    """
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
    """True for a job whose argv runs scripts/new_survey.py."""
    return len(job.argv) > 1 and Path(job.argv[1]).name == "new_survey.py"


def start_new_survey(parent, state, values: dict, out: Path) -> bool:
    """Queue scripts/new_survey.py on `state.runner` and start it immediately.

    The job opens no MTH5 archive, so it is added and started in one call
    with `JobRunner.run_now`, which leaves any queued job waiting for Run
    queue. `MetadataTab.new_survey` calls this after the dialog closes. The
    job's output reaches the console strip through the runner's `log_line`,
    and `handle_new_survey_finished` opens the survey.yaml it wrote. An
    existing survey.yaml is overwritten (`--force`) only after the user
    answers Yes. While another job is running the request is refused with a
    message, so one new-survey job runs at a time.

    Args:
        parent (QWidget): Parent of the message boxes.
        state: The shared `mtproc_gui.app.State`.
        values (dict): `NewSurveyDialog.values()`.
        out (Path): The survey.yaml to write.

    Returns:
        bool: True if the job was started.
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
    """Open the survey.yaml a finished new-survey job wrote, or report its failure.

    Connected to `state.runner.job_finished`, which fires for every job;
    jobs other than new_survey.py (`is_new_survey_job`) are ignored.

    Args:
        parent (QWidget): Parent of the message boxes.
        state: The shared `mtproc_gui.app.State`.
        index (int): The finished job's index.
        ok (bool): Whether the job succeeded.
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
