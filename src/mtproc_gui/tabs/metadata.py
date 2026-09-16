"""Metadata tab: start or pick a survey, read and edit what is declared in it.

Drives `surveys/<name>/survey.yaml` (via `mtproc.survey.Survey`) and nothing
else -- no processing. One row per site: the field-sheet numbers as declared,
its recorder (read-only "instrument": `Survey.instrument_of`, the site's own
`instrument:` or what its folder holds), the site's usual remote-reference partner (`remote:`, what the Process/Spectra/
Coherence tabs preselect), its channels (`channels_column`), on a PR6-24 (EDL)
row its declared electric chain gain (`metadata_edit.electric_gain_cell`,
"-" on any other recorder's), the recorder facts
`scripts/new_survey.py` read from the B423 headers (serial, firmware, start,
end -- read-only), whether the raw folder and the MTH5 archive are actually
there, and whether the site has a declared noise filter list
(`<survey>/filters.yaml`, folded into `Survey.site()`, edited on Filter Data).

The `metadata_edit.EDITABLE` columns are edited in place (double-click, or
"Import site table..." from a CSV/XLSX); "Save survey.yaml" writes only the
changed cells into the `sites:` block (`metadata_edit.rewrite_sites_block`)
and reopens the survey -- asking first when a script wrote the file
(`generated_by:`, shown as a yellow line). "New survey..." queues
`scripts/new_survey.py` on `state.runner` and opens what it wrote once the
job finishes (`metadata_edit.start_new_survey`, `handle_new_survey_finished`).

Selecting a row sets `State.site`, which is what the other tabs preselect.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from mtproc.survey import read_site_table
from mtproc_gui import channels_column, metadata_edit
from mtproc_gui.metadata_edit import EDITABLE, format_cell, parse_cell
from mtproc_gui.theme import BAD_COLOUR, NOTICE_COLOUR

COLUMNS = ["site", "instrument", "latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey",
           "azimuth_ex", "azimuth_ey", "timing", "remote", "channels", metadata_edit.ELECTRIC_GAIN, "serial",
           "firmware", "start", "end", "raw folder", "archive", "filters", "notes"]
NUMBERS = {"latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey",
           "azimuth_ex", "azimuth_ey"}


class SortableItem(QTableWidgetItem):
    """A cell that sorts on `key` (or on its text) and displays `text` verbatim.

    Qt's own numeric sorting would need the number in the display role, which
    rounds a latitude to six digits on screen; the key keeps the YAML value
    shown as written. A number cell sorts on the number its text reads as.
    """

    def __init__(self, text: str, key=None, editable: bool = False, number: bool = False):
        super().__init__(text)
        self.key, self.number = key, number
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        self.setFlags(flags | Qt.ItemIsEditable if editable else flags)

    def sort_key(self):
        if self.number:
            try:
                return float(self.text())
            except ValueError:
                return float("-inf")  # a dash (no value) sorts first
        return self.text() if self.key is None else self.key

    def __lt__(self, other: "SortableItem") -> bool:
        try:
            return self.sort_key() < other.sort_key()
        except TypeError:
            return str(self.sort_key()) < str(other.sort_key())


def _yes_no(flag: bool) -> SortableItem:
    return SortableItem("yes" if flag else "no", 1 if flag else 0)


class MetadataTab(QWidget):
    """The survey's sites as a sortable, editable table; row selection sets `State.site`."""

    open_requested = Signal()

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._syncing = False
        self._shown: dict[tuple[str, str], str] = {}  # (site, column) -> the text loaded
        # where "New survey..." writes <name>/survey.yaml (the smoke test points it at scratch)
        self.surveys_dir = state.repo_root / "surveys"

        self.path_edit = QLineEdit(self)
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("no survey.yaml loaded")
        self.open_button = QPushButton("Open survey.yaml...", self)
        self.open_button.clicked.connect(self.open_requested.emit)
        self.new_button = QPushButton("New survey...", self)
        self.new_button.setToolTip("scripts/new_survey.py: a survey.yaml from a folder of site folders")
        self.new_button.clicked.connect(self.new_survey)
        self.import_button = QPushButton("Import site table...", self)
        self.import_button.setToolTip("a CSV or XLSX with a site column plus any editable column")
        self.import_button.clicked.connect(self._choose_site_table)
        self.save_button = QPushButton("Save survey.yaml", self)
        self.save_button.setToolTip("write the edited cells into the sites: block, nothing else")
        self.save_button.clicked.connect(self.save)

        self.name_label, self.data_root_label, self.workspace_label = (QLabel("-", self) for _ in range(3))
        self.count_label, self.status_label, self.warning_label = (QLabel("", self) for _ in range(3))
        self.warning_label.setStyleSheet(f"color: {NOTICE_COLOUR}; font-weight: bold")
        self.warning_label.hide()

        header = QGridLayout()
        header.addWidget(QLabel("Survey file", self), 0, 0)
        header.addWidget(self.path_edit, 0, 1)
        header.addWidget(self.open_button, 0, 2)
        header.addWidget(self.new_button, 0, 3)
        for row, (text, label) in enumerate(
            [("Name", self.name_label), ("data_root", self.data_root_label),
             ("workspace", self.workspace_label)], start=1):
            header.addWidget(QLabel(text, self), row, 0)
            header.addWidget(label, row, 1, 1, 3)
        header.setColumnStretch(1, 1)
        edit_row = QHBoxLayout()
        edit_row.addWidget(self.import_button)
        edit_row.addWidget(self.save_button)
        edit_row.addWidget(self.status_label, 1)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(lambda _item: self._show_pending())
        self.table.setItemDelegateForColumn(COLUMNS.index("channels"),
                                            channels_column.ChannelsDelegate(state, self.table))

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.warning_label)
        layout.addLayout(edit_row)
        layout.addWidget(self.count_label)
        layout.addWidget(self.table)

        self.state.site_changed.connect(self.select_site)
        self.state.runner.job_finished.connect(  # opens what a New survey job wrote
            lambda index, ok: metadata_edit.handle_new_survey_finished(self, self.state, index, ok))
        self._set_enabled(False)

    # ------------------------------------------------------------ filling

    def reload(self) -> None:
        """Rebuild the table from `State.survey`; any unsaved edit is dropped."""
        survey = self.state.survey
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._shown.clear()
        self.status_label.clear()
        self._set_enabled(survey is not None)
        if survey is None:
            self.count_label.setText("")
            return

        self.path_edit.setText(str(self.state.survey_yaml))
        self.name_label.setText(survey.name)
        self.data_root_label.setText(str(survey.data_root))
        self.workspace_label.setText(str(survey.workspace))
        self.warning_label.setText(
            f"survey.yaml is generated by {survey.generated_by}: regenerating will overwrite "
            "edits made here" if survey.generated_by else "")
        self.warning_label.setVisible(bool(survey.generated_by))

        raw_sites = self.state.raw_sites()
        sites = self.state.all_sites()
        self.table.blockSignals(True)  # filling is not editing
        self.table.setRowCount(len(sites))
        for row, name in enumerate(sites):
            cfg = survey.site(name)
            for column, key in enumerate(COLUMNS):
                if key in ("site", "instrument"):
                    item = SortableItem(name if key == "site" else survey.instrument_of(name))
                elif key in EDITABLE:
                    text = format_cell(key, getattr(cfg, key))
                    self._shown[(name, key)] = text
                    item = SortableItem(text, editable=True, number=key in NUMBERS)
                elif key == "channels":  # greyed when an archive holds the set it was built with
                    item = channels_column.cell(SortableItem, cfg.channels, survey.instrument_of(name),
                                                self.state.has_archive(name))
                    self._shown[(name, key)] = item.text()
                elif key == metadata_edit.ELECTRIC_GAIN:  # the EDL electric chain's declared gain: EDL rows only
                    item = metadata_edit.electric_gain_cell(SortableItem, cfg.electric_gain,
                                                            survey.instrument_of(name), self.state.has_archive(name))
                    if item.flags() & Qt.ItemIsEditable:
                        self._shown[(name, key)] = item.text()
                elif key == "raw folder":
                    item = _yes_no(name in raw_sites)
                elif key == "archive":
                    item = _yes_no(self.state.has_archive(name))
                elif key == "filters":
                    item = _yes_no(bool(cfg.filters))
                else:  # serial, firmware, start, end: header facts, read-only
                    item = SortableItem(getattr(cfg, key) or "-")
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.AscendingOrder)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

        n_raw = sum(1 for s in sites if s in raw_sites)
        n_archive = sum(1 for s in sites if self.state.has_archive(s))
        self.count_label.setText(
            f"{len(sites)} sites - {n_raw} with a raw folder, {n_archive} with an MTH5 archive"
        )
        if self.state.site:
            self.select_site(self.state.site)

    def _set_enabled(self, loaded: bool) -> None:
        self.import_button.setEnabled(loaded)
        self.save_button.setEnabled(loaded)

    def _status(self, text: str, colour: str | None = None) -> None:
        self.status_label.setStyleSheet(f"color: {colour}" if colour else "")
        self.status_label.setText(text)

    # ------------------------------------------------------------ editing

    def pending(self) -> dict[str, dict]:
        """{site: {column: value}} for every editable cell that no longer reads as it was loaded.

        None means "drop the site's own key" (blank, a dash, the default's channels or electric-gain
        number), so the survey's default applies again. Raises ValueError naming a cell whose number
        does not parse, channels or electric-gain included.
        """
        edits: dict[str, dict] = {}
        for row in range(self.table.rowCount()):
            site = self.table.item(row, 0).text()
            for key in EDITABLE:
                item, shown = self.table.item(row, COLUMNS.index(key)), self._shown.get((site, key))
                if item is None or shown is None or item.text() == shown:
                    continue
                try:
                    value = parse_cell(key, item.text())
                except ValueError:
                    raise ValueError(f"{site} {key} {item.text()!r} is not a number") from None
                if value != parse_cell(key, shown):
                    edits.setdefault(site, {})[key] = value
            value = channels_column.edit(self.state.survey, self.table.item(row, COLUMNS.index("channels")),
                                         self._shown.get((site, "channels")), site)
            if value is not channels_column.UNCHANGED:  # its own rule: a key only off the default's set
                edits.setdefault(site, {})["channels"] = value
            gain = self.table.item(row, COLUMNS.index(metadata_edit.ELECTRIC_GAIN))
            value = metadata_edit.electric_gain_edit(self.state.survey, site, gain.text() if gain else None,
                                                      self._shown.get((site, metadata_edit.ELECTRIC_GAIN)))
            if value is not channels_column.UNCHANGED:  # the same rule: a key only off the default's number
                edits.setdefault(site, {})[metadata_edit.ELECTRIC_GAIN] = value
        return edits

    def _show_pending(self) -> None:
        try:
            n = sum(len(v) for v in self.pending().values())
        except ValueError as exc:
            self._status(str(exc), BAD_COLOUR)
            return
        self._status(f"{n} unsaved change(s) - press Save survey.yaml" if n else "")

    def save(self) -> bool:
        """Write the changed cells into the sites block, then reopen the survey; False if nothing was written."""
        survey, path = self.state.survey, self.state.survey_yaml
        if survey is None:
            return False
        try:
            edits = self.pending()
        except ValueError as exc:
            self._status(f"not saved: {exc}", BAD_COLOUR)
            return False
        if not edits:
            self._status("nothing to save")
            return False
        if survey.generated_by and not metadata_edit.ask_yes_no(
            self, "Save survey.yaml",
            f"{path.name} is generated by {survey.generated_by}.\n\nRegenerating it will "
            "overwrite the edits made here. Save anyway?",
        ):
            return False
        try:
            metadata_edit.rewrite_sites_block(path, edits)
        except Exception as exc:  # a malformed file is reported, never half-written
            QMessageBox.critical(self, "Could not save", f"{path}\n\n{exc}")
            return False
        site = self.state.site
        self.state.open_survey(path)
        self.state.set_site(site)
        n = sum(len(v) for v in edits.values())
        self._status(f"saved {n} value(s) for {len(edits)} site(s) to {path.name}")
        return True

    def _choose_site_table(self) -> None:
        start = str(self.state.survey_yaml.parent) if self.state.survey_yaml else ""
        path, _ = QFileDialog.getOpenFileName(self, "Import site table", start, metadata_edit.TABLE_FILTER)
        if path:
            self.import_site_table(path)

    def import_site_table(self, path) -> tuple[int, int]:
        """Merge a site table's columns into the table (only the columns it has, only matching sites).

        Nothing is written (Save does); returns (sites matched, sites in the file).
        """
        try:
            rows, ignored = read_site_table(path)
        except (OSError, ValueError) as exc:
            self._status(f"not imported: {exc}", BAD_COLOUR)
            return 0, 0
        by_site = {self.table.item(r, 0).text(): r for r in range(self.table.rowCount())}
        self.table.setSortingEnabled(False)
        for site, values in rows.items():
            for key, value in values.items():
                if site in by_site:
                    self.table.item(by_site[site], COLUMNS.index(key)).setText(format_cell(key, value))
        self.table.setSortingEnabled(True)
        matched = sum(1 for site in rows if site in by_site)
        text = f"{matched} of {len(rows)} sites matched"
        missing = [site for site in rows if site not in by_site]
        text += f"; not in this survey: {', '.join(missing)}" if missing else ""
        text += f"; ignored columns: {', '.join(ignored)}" if ignored else ""
        self._status(text + " - Save survey.yaml writes them", BAD_COLOUR if missing or ignored else None)
        return matched, len(rows)

    def new_survey(self) -> None:
        """The New survey dialog, then scripts/new_survey.py on state.runner (metadata_edit.start_new_survey)."""
        dialog = metadata_edit.NewSurveyDialog(self.surveys_dir, self)
        accepted, values, out = dialog.exec(), dialog.values(), dialog.out_path()
        dialog.deleteLater()
        if accepted:
            metadata_edit.start_new_survey(self, self.state, values, out)

    # ------------------------------------------------------------- slots

    def _selection_changed(self) -> None:
        if self._syncing:
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is not None:
            self.state.set_site(item.text())

    def select_site(self, name: str) -> None:
        """Highlight `name` (called when another tab changes the selection)."""
        if not name:
            return
        self._syncing = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and item.text() == name:
                    self.table.selectRow(row)
                    break
        finally:
            self._syncing = False
