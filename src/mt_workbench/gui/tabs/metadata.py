# -*- coding: utf-8 -*-
"""
Metadata tab

Creates or opens a survey and shows and edits what `surveys/<name>/survey.yaml`
declares, through `mt_workbench.survey.Survey`. The table has one row per site
with:

* the field-sheet numbers as declared;
* the site's magnetic declination in degrees east of geographic north, its
  model and its epoch (decimal year), "-" when unset
  (scripts/declination.py fills them from the IGRF); stored with every
  product, never applied;
* the recorder, read-only (`Survey.instrument_of`: the site's own
  `instrument:` or what its folder holds), with the parent and rate of a
  derived site ("lemi423 (B01 at 1 Hz)") and an observatory's rate
  ("intermagnet (1 Hz)");
* two tick boxes, "Ex and Ey swapped" (`swap_e:`) and "Hx and Hy swapped"
  (`swap_h:`), for a site whose two electric lines or two horizontal coils
  were connected to each other's inputs; ingest exchanges the samples of the
  two channels, so a change reaches the data only when the archive is built
  again ("Rebuild archive"); greyed on a derived, burst or observatory row,
  which takes no swap of its own (`_swap_elsewhere`);
* the site's usual remote-reference partner (`remote:`), which the Process,
  Spectra and Coherence tabs preselect;
* its channels (`channels_column`);
* on a PR6-24 (EDL) row, the declared electric chain gain
  (`metadata_edit.electric_gain_cell`), "-" for other recorders;
* the recorder facts `scripts/new_survey.py` read from the B423 headers
  (serial, firmware, start, end), read-only;
* whether the raw folder and the MTH5 archive exist;
* the raw DC level the ingest recorded in the archive's run comments
  (`mt_workbench.dclevel.recorded_levels`), per channel its verdict ("ok",
  "open input?", "saturated?") and median in counts
  (`mt_workbench.dclevel.channel_summary`: the most severe verdict of its runs,
  followed by "in k of n runs" when only some of its runs have it, and the
  median of those runs' medians), e.g. "hx ok 4.30e7, hy ok 3.89e7, ex ok
  2.00e7, ey open input? 1.60e9"; the cell is red with an open input,
  yellow with a saturated channel, and its tooltip lists every run and
  channel; "-" for a site without an archive or an archive without the
  record (built before the ingest recorded it: scripts/dc_level_check.py
  reads its samples);
* whether the site has a declared noise filter list (`<survey>/filters.yaml`,
  merged into `Survey.site()` and edited on the Filter Data tab).

The `metadata_edit.EDITABLE` columns are edited in place, by double-click or
with "Import site table..." from a CSV or XLSX (`mt_workbench.survey.merge_table_row`:
a position the site holds is kept). A row of a site folder with no entry in
survey.yaml is read-only until "Add sites" adds it: that button runs
scripts/new_survey.py again on the survey (`metadata_edit.start_add_sites`),
after a question that lists the folders, and is refused while the table holds
unsaved edits. "Rebuild archive" builds the selected site's archive again
from its raw data (scripts/ingest_site.py <survey.yaml> <site> --force, on
`state.runner`), after a question, for a site with an entry, a raw data
folder and an archive, while no job runs and the table holds no unsaved edit;
a changed swap box or electric gain reaches the data that way. "Check" lists what stops an ingest and what is doubtful
(`mt_workbench.survey_check`, the findings and lines scripts/check_survey.py
prints) in a table below the sites, one row per finding, the stops first; a
double click on a row selects its site. "Save survey.yaml" writes the
changed cells into the edited entries through `mt_workbench.survey_file.edit`,
which leaves every other line as it was and keeps the file as it was in
survey.yaml.previous, and reopens the survey, asking first when the file is
written again whole by a script (`generated_by:`, shown as a yellow line;
not for scripts/new_survey.py, which only adds sites to a file that
exists, `rewriting_script`). "New survey..." queues
`scripts/new_survey.py` on `state.runner` and opens the survey it wrote when
the job finishes (`metadata_edit.start_new_survey`,
`handle_new_survey_finished`).

Selecting a row sets `State.site`, which the other tabs preselect. The site
column stays at the left edge when the table is scrolled sideways
(`FrozenSiteColumn`), so every row can be read against its site.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from mt_workbench import survey_check, survey_file
from mt_workbench.dclevel import OK, OPEN, VERDICT_ORDER, channel_summary, counts_text, recorded_levels
from mt_workbench.survey import OBSERVATORY, merge_table_row, read_site_table
from mt_workbench.gui import channels_column, metadata_edit
from mt_workbench.gui.metadata_edit import EDITABLE, format_cell, parse_cell
from mt_workbench.gui.theme import BAD_COLOUR, DISABLED, NOTICE_COLOUR

DC_LEVEL = "dc level"
NO_RECORD = len(VERDICT_ORDER)  # the dc level cell's sort key without a record: after ok
NO_RECORD_TIP = ("no dc level recorded: the archive was built before the ingest recorded it; "
                 "scripts/dc_level_check.py reads its samples, and a rebuild records it")
COLUMNS = ["site", "instrument", "latitude", "longitude", "elevation", "declination", "declination_model",
           "declination_epoch", "dipole_length_ex", "dipole_length_ey",
           "azimuth_ex", "azimuth_ey", "swap_e", "swap_h", "timing", "remote", "channels",
           metadata_edit.ELECTRIC_GAIN, "serial", "firmware", "start", "end", "raw folder", "archive", DC_LEVEL,
           "filters", "notes"]
# the tick box columns: the site key, its header and the header's tooltip
SWAPS = {
    "swap_e": ("Ex and Ey swapped",
               "Ticked for a site whose two electric lines were connected to each other's inputs: ingest exchanges "
               "the samples of ex and ey, and the dipole lengths and azimuths are declared for the lines as they "
               "are after the exchange. The change reaches the data only when the archive is built again: select "
               "the site and press Rebuild archive."),
    "swap_h": ("Hx and Hy swapped",
               "Ticked for a site whose two horizontal coils were plugged into each other's inputs: ingest "
               "exchanges the samples of hx and hy. The change reaches the data only when the archive is built "
               "again: select the site and press Rebuild archive."),
}
NUMBERS = {"latitude", "longitude", "elevation", "declination", "declination_epoch", "dipole_length_ex",
           "dipole_length_ey", "azimuth_ex", "azimuth_ey"}
NO_ENTRY_TIP = "no entry yet: press Add sites"
ADD_SHOWN = 20  # the folders the question of Add sites names before "and N more"
CHECK_COLUMNS = ["level", "site", "finding", "message"]
INGEST_SCRIPT = "ingest_site.py"
REBUILD = "rebuild MTH5"  # the label of a Rebuild archive job, before the site
# Save tries the replace of a survey.yaml held open this many times, this far apart: the window waits about 2 s
SAVE_TRIES = 3
SAVE_WAIT_S = 1.0
ADDS_ONLY = "scripts/new_survey.py"  # run again on a survey.yaml, this script only adds site folders


def rewriting_script(survey) -> str | None:
    """Return the script that writes the survey.yaml again whole (`generated_by:`), None when none does.

    A file made by scripts/new_survey.py is not warned about: run again,
    that script adds the site folders with no entry and leaves every other
    line. The comparison is exact, so a `generated_by:` text that only
    mentions that script still counts as another script's.
    """
    by = survey.generated_by
    return None if by == ADDS_ONLY else by


class SortableItem(QTableWidgetItem):
    """A table cell that sorts on `key`, or its text, and displays `text` as given; a tick box sorts on its state.

    Qt's numeric sorting needs the number in the display role, which rounds a
    latitude to six digits on screen; a separate key keeps the YAML value
    shown as written. A number cell sorts on the number its text parses to.

    Args:
        text (str): Display text.
        key: Sort key; None sorts on the text.
        editable (bool): Make the cell editable.
        number (bool): Sort on the text parsed as a float.
    """

    def __init__(self, text: str, key=None, editable: bool = False, number: bool = False):
        super().__init__(text)
        self.key, self.number = key, number
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        self.setFlags(flags | Qt.ItemIsEditable if editable else flags)

    def sort_key(self):
        """Return the value the cell sorts on."""
        if self.data(Qt.CheckStateRole) is not None:  # a tick box sorts on its state, ticked last
            return 1 if self.checkState() == Qt.Checked else 0
        if self.number:
            try:
                return float(self.text())
            except ValueError:
                return float("-inf")  # a dash (no value) sorts first
        return self.text() if self.key is None else self.key

    def __lt__(self, other: "SortableItem") -> bool:
        """Compare sort keys, falling back to their text for mixed types."""
        try:
            return self.sort_key() < other.sort_key()
        except TypeError:
            return str(self.sort_key()) < str(other.sort_key())


def _yes_no(flag: bool) -> SortableItem:
    """Return a "yes"/"no" cell that sorts yes after no."""
    return SortableItem("yes" if flag else "no", 1 if flag else 0)


def _instrument_text(survey, name: str) -> str:
    """Return the instrument cell: the recorder, with the parent and rate of a derived site or an observatory's rate."""
    instrument = survey.instrument_of(name)
    parent = survey.parent_of(name)
    if parent:
        return f"{instrument} ({parent} at {survey.sample_rate_of(name):g} Hz)"
    if instrument == OBSERVATORY:
        return f"{instrument} ({survey.sample_rate_of(name):g} Hz)"
    return instrument


def _swap_elsewhere(survey, name: str) -> str | None:
    """Return why a site's swap boxes are greyed, naming the site that holds the setting; None when they are not.

    A swap acts at ingest, on the raw samples of a recorded site. A derived
    site's archive is decimated from its parent's, a burst site's is
    ingested with its recorded site's settings, and an observatory's is
    fetched from INTERMAGNET, so none of them takes a swap of its own.
    """
    parent = survey.parent_of(name) or survey.bursts_parent(name)
    if parent:
        kind = "derived from" if survey.parent_of(name) else "a burst site of"
        return (f"{name} is {kind} {parent}: its archive is made from {parent}'s, so the swap is set on "
                f"{parent}'s row")
    if survey.instrument_of(name) == OBSERVATORY:
        return f"{name} is an observatory: its archive is fetched from INTERMAGNET, so it takes no swap"
    return None


def derived_rebuilds(survey, site: str, has_archive) -> str:
    """Return the sentence naming the derived sites a rebuild of `site` leaves with the old samples, "" when none.

    A derived site's archive is made from its parent's, so a rebuilt parent
    leaves it as it was. Each derived site that has an archive is named with
    the command that builds it again: ``<site>L`` by scripts/decimate_site.py
    at its own rate, ``<site>D`` by scripts/diagonal_site.py; any other is
    named alone.

    Args:
        survey: The open `Survey`.
        site (str): The recorded site whose archive is rebuilt.
        has_archive: Callable, site name -> whether it has an archive.

    Returns:
        str: The sentence, or "".
    """
    parts = []
    for name in survey.site_names():
        if survey.parent_of(name) != site or not has_archive(name):
            continue
        if name == f"{site}L":
            parts.append(f"{name} (python scripts/decimate_site.py survey.yaml {site} --rate "
                         f"{survey.sample_rate_of(name):g})")
        elif name == f"{site}D":
            parts.append(f"{name} (python scripts/diagonal_site.py survey.yaml {site}, with the --sign it was "
                         f"built with if one was given)")
        else:
            parts.append(name)
    if not parts:
        return ""
    return (f"the derived sites of {site} keep the old samples until they are built again, after the rebuild: "
            f"{', '.join(parts)}")


def _dc_level_item(survey_name: str, site: str, path) -> SortableItem:
    """Return the dc level cell of a site: each channel's recorded verdict and median in counts.

    Args:
        survey_name (str): The survey's name.
        site (str): Site name.
        path (Path | None): The site's archive; None without one.

    Returns:
        SortableItem: "<channel> <verdict> <median>" per channel
        (`mt_workbench.dclevel.channel_summary`), sorting open input? first, then
        saturated?, ok and "-"; red text with an open input, yellow with a
        saturated channel; the tooltip lists every run and channel.
    """
    if path is None:
        return SortableItem("-", NO_RECORD + 1)
    try:
        levels = recorded_levels(path, survey_name, site)
    except (OSError, KeyError) as exc:
        item = SortableItem("-", NO_RECORD)
        item.setToolTip(f"archive unreadable: {exc}")
        return item
    if not levels:
        item = SortableItem("-", NO_RECORD)
        item.setToolTip(NO_RECORD_TIP)
        return item
    parts = []
    for channel in channel_summary(levels):
        runs = (f" in {channel['n_verdict']} of {channel['n_runs']} runs"
                if channel["verdict"] != OK and channel["n_verdict"] < channel["n_runs"] else "")
        parts.append(f"{channel['channel']} {channel['verdict']} {counts_text(channel['median_counts'])}{runs}")
    worst = min(VERDICT_ORDER[row["verdict"]] for rows in levels.values() for row in rows)
    item = SortableItem(", ".join(parts), worst)
    if worst < VERDICT_ORDER[OK]:
        item.setForeground(QColor(BAD_COLOUR if worst == VERDICT_ORDER[OPEN] else NOTICE_COLOUR))
    lines = [f"{run} {row['channel']}: median {counts_text(row['median_counts'])} counts, "
             f"rail {100 * row['rail_fraction']:.2f} %, {row['verdict']}"
             for run, rows in levels.items() for row in rows]
    item.setToolTip("\n".join(["raw DC level recorded at ingest, per run and channel:", *lines]))
    return item


class FrozenSiteColumn(QTableView):
    """The first column of a table, kept at the left edge while the table scrolls sideways.

    Qt's frozen-column arrangement: a second view over the table's own model
    and selection model, showing the first column only, laid over the
    table's first column and kept in step with its vertical scrolling, row
    heights, column width and sort order. The rows, their order, the
    selection and the edits are the table's own, so the two views cannot
    disagree on them. A click on its header sorts the table by that column.

    Args:
        table (QTableWidget): The table; this view becomes its child.
    """

    def __init__(self, table: QTableWidget):
        super().__init__(table)
        self.table = table
        self.setModel(table.model())
        self.setSelectionModel(table.selectionModel())
        self.setSelectionBehavior(table.selectionBehavior())
        self.setSelectionMode(table.selectionMode())
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QFrame.NoFrame)
        self.setAlternatingRowColors(table.alternatingRowColors())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(table.verticalScrollMode())
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(table.verticalHeader().defaultSectionSize())
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setSortIndicatorShown(True)
        for column in range(1, table.columnCount()):
            self.setColumnHidden(column, True)
        table.viewport().stackUnder(self)

        table.horizontalHeader().sectionResized.connect(self._column_resized)
        table.verticalHeader().sectionResized.connect(lambda row, _old, new: self.setRowHeight(row, new))
        table.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.verticalScrollBar().valueChanged.connect(table.verticalScrollBar().setValue)
        table.horizontalHeader().sortIndicatorChanged.connect(self.horizontalHeader().setSortIndicator)
        self.horizontalHeader().sectionClicked.connect(self._sort)
        table.installEventFilter(self)
        table.viewport().installEventFilter(self)
        self.place()

    def place(self) -> None:
        """Lay the view over the table's first column, from the top of its header to the foot of its rows."""
        table = self.table
        header = table.horizontalHeader()
        self.setColumnWidth(0, table.columnWidth(0))
        self.horizontalHeader().setFixedHeight(header.height())
        self.setGeometry(table.viewport().x(), header.y(), table.columnWidth(0),
                         header.height() + table.viewport().height())

    def _column_resized(self, column: int, _old: int, _new: int) -> None:
        """Follow a new width of the table's first column."""
        if column == 0:
            self.place()

    def _sort(self, _column: int) -> None:
        """Sort the table by its first column, the other way round when it is sorted by it already."""
        header = self.table.horizontalHeader()
        again = header.sortIndicatorSection() == 0 and header.sortIndicatorOrder() == Qt.AscendingOrder
        self.table.sortByColumn(0, Qt.DescendingOrder if again else Qt.AscendingOrder)

    def eventFilter(self, watched, event) -> bool:
        """Lay the view again when the table or its viewport is resized or shown."""
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            self.place()
        return False


class MetadataTab(QWidget):
    """The survey's sites as a sortable, editable table; selecting a row sets `State.site`.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    open_requested = Signal()

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._syncing = False
        self._shown: dict[tuple[str, str], str] = {}  # (site, column) -> the text loaded
        # where "New survey..." writes <name>/survey.yaml; the smoke test points it at a scratch folder
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
        self.add_button = QPushButton("Add sites", self)
        self.add_button.setToolTip("add the site folders under data_root that have no entry yet; a second "
                                   "deployment goes in its own folder (SA106_2); nothing else changes")
        self.add_button.clicked.connect(self.add_sites)
        self.check_button = QPushButton("Check", self)
        self.check_button.setToolTip("list what stops an ingest (STOP) and what to look at (WARN), site by site, "
                                     "as scripts/check_survey.py prints it")
        self.check_button.clicked.connect(self.run_check)
        self.rebuild_button = QPushButton("Rebuild archive", self)
        self.rebuild_button.clicked.connect(self.rebuild_archive)

        self.name_label, self.data_root_label, self.workspace_label = (QLabel("-", self) for _ in range(3))
        self.count_label, self.status_label, self.warning_label = (QLabel("", self) for _ in range(3))
        self.status_label.setWordWrap(True)  # a long message wraps instead of widening the window
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
        edit_row.addWidget(self.add_button)
        edit_row.addWidget(self.check_button)
        edit_row.addWidget(self.rebuild_button)
        edit_row.addWidget(self.status_label, 1)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels([SWAPS[c][0] if c in SWAPS else c for c in COLUMNS])
        for key, (_label, tip) in SWAPS.items():
            self.table.horizontalHeaderItem(COLUMNS.index(key)).setToolTip(tip)
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
        self.site_column = FrozenSiteColumn(self.table)  # the site stays at the left edge when scrolled sideways

        self.check_label = QLabel("", self)
        self.check_label.setWordWrap(True)
        self.check_table = QTableWidget(0, len(CHECK_COLUMNS), self)
        self.check_table.setHorizontalHeaderLabels(CHECK_COLUMNS)
        self.check_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.check_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.check_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.check_table.verticalHeader().setVisible(False)
        self.check_table.horizontalHeader().setStretchLastSection(True)
        self.check_table.setMaximumHeight(180)
        self.check_table.cellDoubleClicked.connect(self._finding_selected)
        self._clear_check()

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.warning_label)
        layout.addLayout(edit_row)
        layout.addWidget(self.count_label)
        layout.addWidget(self.table)
        layout.addWidget(self.check_label)
        layout.addWidget(self.check_table)

        self.state.site_changed.connect(self.select_site)
        self.state.runner.job_finished.connect(self._job_finished)
        self.state.runner.queue_changed.connect(self._update_rebuild)  # a job started or ended
        self._set_enabled(False)

    # ------------------------------------------------------------ filling

    def reload(self) -> None:
        """Rebuild the table from `State.survey`, discarding unsaved edits."""
        survey = self.state.survey
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._shown.clear()
        self.status_label.clear()
        self._clear_check()
        self._set_enabled(survey is not None)
        if survey is None:
            self.count_label.setText("")
            return

        self.path_edit.setText(str(self.state.survey_yaml))
        self.name_label.setText(survey.name)
        self.data_root_label.setText(str(survey.data_root))
        self.workspace_label.setText(str(survey.workspace))
        script = rewriting_script(survey)
        self.warning_label.setText(
            f"survey.yaml is generated by {script}: regenerating will overwrite "
            "edits made here" if script else "")
        self.warning_label.setVisible(bool(script))

        raw_sites = self.state.raw_sites()
        sites = self.state.all_sites()
        entries = set(self.state.configured_sites())
        self.table.blockSignals(True)  # filling is not editing
        self.table.setRowCount(len(sites))
        for row, name in enumerate(sites):
            cfg = survey.site(name)
            for column, key in enumerate(COLUMNS):
                if key in ("site", "instrument"):
                    item = SortableItem(name if key == "site" else _instrument_text(survey, name))
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
                elif key in SWAPS:  # a tick box: the site's merged value, false when unset
                    flag = bool(getattr(cfg, key))
                    item = SortableItem("")
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if flag else Qt.Unchecked)
                    elsewhere = _swap_elsewhere(survey, name)
                    if elsewhere:  # shown greyed, as the site reads it; set on the recorded site
                        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsEnabled)
                        item.setForeground(QColor(DISABLED))
                        item.setToolTip(elsewhere)
                    else:
                        self._shown[(name, key)] = flag
                elif key == "raw folder":
                    item = _yes_no(name in raw_sites)
                elif key == "archive":
                    item = _yes_no(self.state.has_archive(name))
                elif key == DC_LEVEL:
                    item = _dc_level_item(survey.name, name, self.state.archive_path(name)
                                          if self.state.has_archive(name) else None)
                elif key == "filters":
                    item = _yes_no(bool(cfg.filters))
                else:  # serial, firmware, start, end: header facts, read-only
                    item = SortableItem(getattr(cfg, key) or "-")
                if name not in entries:  # a folder with no entry: Save has no entry to write into
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsUserCheckable
                                  & ~(Qt.ItemIsEnabled if key in SWAPS else Qt.NoItemFlags))
                    item.setForeground(QColor(DISABLED))
                    item.setToolTip(NO_ENTRY_TIP)
                    self._shown.pop((name, key), None)
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
        """Enable Import, Save and Add sites when a survey is loaded."""
        self.import_button.setEnabled(loaded)
        self.save_button.setEnabled(loaded)
        self.add_button.setEnabled(loaded)
        self.check_button.setEnabled(loaded)
        self._update_rebuild()

    def _update_rebuild(self) -> None:
        """Enable Rebuild archive for the selected site when it has an entry, raw data and an archive, and no job runs.

        A burst site's raw data is its recorded site's folder
        (`Survey.raw_site`), as scripts/ingest_site.py looks it up.
        """
        site, state = self.state.site, self.state
        survey = state.survey
        raw = None if site is None or survey is None else survey.raw_site(site)
        why = ("open a survey" if survey is None
               else "select a site in the table" if site is None
               else f"{site} has no entry yet: press Add sites" if site not in state.configured_sites()
               else f"no raw data folder for {raw}" if raw not in state.raw_sites()
               else f"{site} has no archive yet: Build MTH5 on the Time Series tab builds it"
               if not state.has_archive(site)
               else "a job is running - wait for it to finish" if state.runner.running
               else None)
        self.rebuild_button.setEnabled(why is None)
        self.rebuild_button.setToolTip(why or f"build the archive of {site} again from its raw data "
                                              f"(scripts/ingest_site.py --force), after a question")

    def _status(self, text: str, colour: str | None = None) -> None:
        """Show a status message, optionally coloured."""
        self.status_label.setStyleSheet(f"color: {colour}" if colour else "")
        self.status_label.setText(text)

    # ------------------------------------------------------------ editing

    def pending(self) -> dict[str, dict]:
        """Collect the edited cells.

        Returns:
            dict[str, dict]: {site: {column: value}} for every editable cell
            whose value differs from the loaded one. A value of None drops
            the site's key (a blank or "-" cell, or channels or electric gain
            equal to the survey default), so the default applies again. A
            ticked swap box gives True; an unticked one None, or False when
            `defaults:` holds True.

        Raises:
            ValueError: If a number cell, including electric gain, does not
                parse; the message names the site and column.
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
                    raise ValueError(f"{site} {key} {item.text()!r} is not a number: type the number alone, with "
                                     f"no unit") from None
                if value != parse_cell(key, shown):
                    edits.setdefault(site, {})[key] = value
            value = channels_column.edit(self.state.survey, self.table.item(row, COLUMNS.index("channels")),
                                         self._shown.get((site, "channels")), site)
            if value is not channels_column.UNCHANGED:  # a key is written only when it differs from the default
                edits.setdefault(site, {})["channels"] = value
            gain = self.table.item(row, COLUMNS.index(metadata_edit.ELECTRIC_GAIN))
            value = metadata_edit.electric_gain_edit(self.state.survey, site, gain.text() if gain else None,
                                                      self._shown.get((site, metadata_edit.ELECTRIC_GAIN)))
            if value is not channels_column.UNCHANGED:  # likewise for the electric gain
                edits.setdefault(site, {})[metadata_edit.ELECTRIC_GAIN] = value
            for key in SWAPS:  # a tick box: true is written, false removes the key (false is the default)
                item, shown = self.table.item(row, COLUMNS.index(key)), self._shown.get((site, key))
                ticked = item is not None and item.checkState() == Qt.Checked
                if shown is None or ticked == shown:
                    continue
                edits.setdefault(site, {})[key] = True if ticked else (False if self.state.survey.defaults.get(key)
                                                                       else None)
        return edits

    def _show_pending(self) -> None:
        """Show the number of unsaved changes, or the parse error."""
        try:
            n = sum(len(v) for v in self.pending().values())
        except ValueError as exc:
            self._status(str(exc), BAD_COLOUR)
            return
        self._status(f"{n} unsaved change(s) - press Save survey.yaml" if n else "")

    def _unsaved(self) -> int:
        """Return the number of unsaved changes; a cell that does not parse counts as one."""
        try:
            return sum(len(v) for v in self.pending().values())
        except ValueError:
            return 1

    def save(self) -> bool:
        """Write the changed cells into their sites' entries, then reopen the survey.

        One `survey_file.edit` call writes every edited site: only the lines
        of those entries change, a cell equal to the `defaults:` value
        removes the site's own key, and the file as it was is kept as
        survey.yaml.previous. A refused edit is shown in a box and the file
        is left as it was. A file another program holds open, or a
        read-only one, is tried `SAVE_TRIES` times, `SAVE_WAIT_S` apart,
        so the window waits about two seconds before the box says so.

        Returns:
            bool: True if the file was written.
        """
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
        script = rewriting_script(survey)
        if script and not metadata_edit.ask_yes_no(
            self, "Save survey.yaml",
            f"{path.name} is generated by {script}.\n\nRegenerating it will "
            "overwrite the edits made here. Save anyway?",
        ):
            return False
        try:
            result = survey_file.edit(path, sites=edits, tries=SAVE_TRIES, wait_s=SAVE_WAIT_S)
        except Exception as exc:  # a refused edit or a malformed file is reported and left unwritten
            QMessageBox.critical(self, "Could not save", f"{path}\n\n{exc}")
            return False
        site = self.state.site
        self.state.open_survey(path)
        self.state.set_site(site)
        if not result.written:
            self._status(f"nothing written: {path.name} already reads as the table")
            return False
        n = sum(len(v) for v in edits.values())
        # every summary line, so a removed key and the value the site now takes are seen
        notes = result.summary[:5] + ([f"and {len(result.summary) - 5} more"] if len(result.summary) > 5 else [])
        # a swap acts at ingest: an archive built before the change still holds the channels as they were
        stale = [s for s, values in edits.items() if set(values) & set(SWAPS) and self.state.has_archive(s)]
        rebuild = ([f"the archive of {', '.join(stale)} was built before the swap changed: select "
                    f"{'it' if len(stale) == 1 else 'each'} and press Rebuild archive"] if stale else [])
        rebuild += [text for text in (derived_rebuilds(self.state.survey, s, self.state.has_archive) for s in stale)
                    if text]
        self._status("; ".join([f"saved {n} value(s) for {len(edits)} site(s); the file as it was: "
                                f"{result.previous.name}", *rebuild, *notes]), NOTICE_COLOUR if stale else None)
        return True

    def _choose_site_table(self) -> None:
        """Ask for a site table file and import it."""
        start = str(self.state.survey_yaml.parent) if self.state.survey_yaml else ""
        path, _ = QFileDialog.getOpenFileName(self, "Import site table", start, metadata_edit.TABLE_FILTER)
        if path:
            self.import_site_table(path)

    def import_site_table(self, path) -> tuple[int, int]:
        """Merge a site table's columns into the table for the sites it matches.

        Each row goes through `merge_table_row` against the cells as shown:
        a latitude, longitude or elevation the site already shows is kept,
        and one that differs from the table's is named in the status line;
        every other column the file has is set. Rows of folders with no
        entry are left alone and named. The file is written by Save.

        Args:
            path: CSV or XLSX site table.

        Returns:
            tuple[int, int]: (sites matched, sites in the file).
        """
        try:
            rows, ignored = read_site_table(path)
        except (OSError, ValueError) as exc:
            self._status(f"not imported: {exc}", BAD_COLOUR)
            return 0, 0
        by_site = {self.table.item(r, 0).text(): r for r in range(self.table.rowCount())}
        entries = set(self.state.configured_sites())
        matched = [site for site in rows if site in by_site and site in entries]
        no_entry = [site for site in rows if site in by_site and site not in entries]
        missing = [site for site in rows if site not in by_site]
        n_changed, disagreements = 0, []
        self.table.setSortingEnabled(False)
        for site in matched:
            cells = {key: self.table.item(by_site[site], COLUMNS.index(key)) for key in rows[site]}
            shown = {}
            for key, item in cells.items():
                try:
                    shown[key] = parse_cell(key, item.text())
                except ValueError:  # a number cell typed wrong counts as no value
                    shown[key] = None
            values, disagree = merge_table_row(shown, rows[site])
            disagreements += [f"{site} {key} {rows[site][key]:g} in the table, {shown[key]:g} kept"
                              for key in disagree]
            n_changed += any(value != shown[key] for key, value in values.items())
            for key, value in values.items():
                cells[key].setText(format_cell(key, value))
        self.table.setSortingEnabled(True)
        text = (f"{len(matched)} of {len(rows)} sites matched: {len(matched) - n_changed} as in the file, "
                f"{n_changed} changed")
        text += f"; not a site with an entry: {', '.join(no_entry)} (press Add sites first)" if no_entry else ""
        text += f"; not in this survey: {', '.join(missing)}" if missing else ""
        text += f"; position kept where the table differs: {', '.join(disagreements)}" if disagreements else ""
        text += f"; ignored columns: {', '.join(ignored)}" if ignored else ""
        warn = missing or no_entry or disagreements or ignored
        self._status(text + " - Save survey.yaml writes them", BAD_COLOUR if warn else None)
        return len(matched), len(rows)

    def add_sites(self) -> bool:
        """Add the site folders that have no entry, after a question that lists them.

        Refused while the table holds unsaved edits, since the survey opens
        again when the job ends and the edits would be lost. The data folder
        is listed again, so a folder put there since the survey was opened
        counts. With no such folder, or with the data folder not found,
        nothing runs and the status line says why. Otherwise `metadata_edit.ask_yes_no` names the
        folders, and on Yes `metadata_edit.start_add_sites` runs
        scripts/new_survey.py again, as the command line re-run does.

        Returns:
            bool: True if the job was started.
        """
        if self.state.survey is None:
            return False
        n = self._unsaved()
        if n:
            self._status(f"{n} unsaved change(s): press Save survey.yaml first, or open the survey again to drop "
                         f"them, then Add sites", BAD_COLOUR)
            return False
        entries = set(self.state.configured_sites())
        try:  # read again: a folder put under data_root since the survey was opened counts
            found = self.state.survey.site_dirs()
        except OSError:  # data_root on a drive that is not connected
            self._status(f"data folder {self.state.survey.data_root} not found: connect the drive, or correct "
                         f"data_root in survey.yaml, then press Add sites", BAD_COLOUR)
            return False
        folders = sorted(site for site in found if site not in entries)
        if not folders:
            self._status("nothing to add: every site folder has an entry")
            return False
        shown = ", ".join(folders[:ADD_SHOWN]) + (f" and {len(folders) - ADD_SHOWN} more"
                                                   if len(folders) > ADD_SHOWN else "")
        if not metadata_edit.ask_yes_no(self, "Add sites", f"Add {len(folders)} site(s) that have a folder and no "
                                                           f"entry: {shown}? Nothing else in the file changes."):
            return False
        if not metadata_edit.start_add_sites(self, self.state):
            return False
        self._status(f"adding {len(folders)} site(s) ... (the log is in the console strip below)")
        return True

    def run_check(self) -> list:
        """List the findings of `mt_workbench.survey_check.check_survey` below the site table.

        The data folder is listed again, so a site folder put there since
        the survey was opened is found. One row per finding, in
        `survey_check.ORDER` (the stops first),
        with its level, site, name and message, the text
        scripts/check_survey.py --all prints; STOP rows red, WARN rows
        yellow. The line on the usual dipoles and the count line of the
        command stand above the list.

        Returns:
            list: The findings.
        """
        survey = self.state.survey
        if survey is None:
            return []
        findings = survey_check.check_survey(survey)  # lists the data folder itself, as the command does
        findings.sort(key=lambda f: survey_check.ORDER.index(f.name))  # stable: sites keep their order
        self.check_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            colour = QColor(BAD_COLOUR if finding.level == survey_check.STOP else NOTICE_COLOUR)
            texts = (finding.level.upper(), finding.site or "", finding.name, finding.message)
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setForeground(colour)
                item.setToolTip(finding.message)
                self.check_table.setItem(row, column, item)
        self.check_table.resizeColumnsToContents()
        folders = {f.site for f in findings if f.name == "folder_without_entry"}
        self.check_label.setText(survey_check.usual_dipoles_text(survey) + "\n"
                                 + survey_check.count_line(findings, len(survey.site_names()) + len(folders)))
        self.check_label.show()
        self.check_table.setVisible(bool(findings))
        self._status("check done: double-click a finding to select its site" if findings else "check done")
        return findings

    def _clear_check(self) -> None:
        """Empty and hide the Check list."""
        self.check_table.setRowCount(0)
        self.check_table.hide()
        self.check_label.clear()
        self.check_label.hide()

    def _finding_selected(self, row: int, _column: int) -> None:
        """Select the site of a double-clicked finding in the site table (`State.set_site`)."""
        item = self.check_table.item(row, CHECK_COLUMNS.index("site"))
        if item is not None and item.text():
            self.state.set_site(item.text())

    def rebuild_command(self, site: str) -> list[str]:
        """Return the command line that rebuilds a site's archive: scripts/ingest_site.py <survey.yaml> SITE --force."""
        return [self.state.python_exe, self.state.script(INGEST_SCRIPT), str(self.state.survey_yaml), site, "--force"]

    def rebuild_archive(self) -> int | None:
        """Build the selected site's archive again from its raw data, after a question.

        Refused while the table holds unsaved edits, since the job reads
        survey.yaml as saved. The question says that the present archive is
        replaced and, for a
        site with declared filters, that its filtered variant is built again
        too, as scripts/ingest_site.py --force does. On Yes the command of
        `rebuild_command` starts at once on `state.runner`
        (`JobRunner.run_now`), as Build MTH5 does on the Time Series tab, and
        the status line follows it.

        Returns:
            int | None: The job's index, or None when nothing was started.
        """
        self._update_rebuild()
        site = self.state.site
        if not self.rebuild_button.isEnabled() or not site:
            return None
        n = self._unsaved()
        if n:  # the job reads survey.yaml as saved
            self._status(f"{n} unsaved change(s): press Save survey.yaml first, then Rebuild archive", BAD_COLOUR)
            return None
        variant = (" Its filtered variant is built again from the new archive too."
                   if self.state.survey.site(site).filters else "")
        derived = derived_rebuilds(self.state.survey, site, self.state.has_archive)
        derived = f"\n\nThen {derived}." if derived else ""
        if not metadata_edit.ask_yes_no(self, "Rebuild archive", f"Rebuild the archive of {site} from its raw data? "
                                                                 f"The present archive is replaced.{variant}{derived}"):
            return None
        index = self.state.runner.run_now(f"{REBUILD} {site}", self.rebuild_command(site), station=site)
        self._status(f"rebuilding {site}.h5 ... (the log is in the console strip below)")
        self._update_rebuild()
        return index

    def _refresh_archive_cells(self, site: str) -> None:
        """Read the archive and dc level cells of one row again; the other cells, edited or not, stay as they are."""
        row = next((r for r in range(self.table.rowCount()) if self.table.item(r, 0).text() == site), None)
        if row is None or self.state.survey is None:
            return
        archived = self.state.has_archive(site)
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)  # the row stays where it is while its cells are replaced
        self.table.blockSignals(True)
        self.table.setItem(row, COLUMNS.index("archive"), _yes_no(archived))
        self.table.setItem(row, COLUMNS.index(DC_LEVEL), _dc_level_item(
            self.state.survey.name, site, self.state.archive_path(site) if archived else None))
        self.table.blockSignals(False)
        self.table.setSortingEnabled(sorting)
        self._update_rebuild()

    def _job_finished(self, index: int, ok: bool) -> None:
        """Open what a New survey or Add sites job wrote, and report an Add sites or Rebuild archive job.

        A Rebuild archive job refreshes the archive and dc level cells of its
        site's row alone, so unsaved edits of the table are kept.
        """
        metadata_edit.handle_new_survey_finished(self, self.state, index, ok)
        job = self.state.runner.jobs[index] if 0 <= index < len(self.state.runner.jobs) else None
        if job is not None and job.label.startswith(REBUILD):
            site = job.label[len(REBUILD):].strip()
            self._refresh_archive_cells(site)
            self._status(f"rebuilt {site}.h5 from its raw data" if ok else
                         f"could not rebuild {site}.h5: the console strip says why", None if ok else BAD_COLOUR)
            return
        if job is None or not ok or not metadata_edit.is_new_survey_job(job) \
                or not job.label.startswith(metadata_edit.ADD_SITES):
            return
        said = [line for line in job.output if line.startswith(("added ", "nothing to add"))]
        self._status(said[-1] if said else "Add sites finished")

    def new_survey(self) -> None:
        """Show the New survey dialog, then run scripts/new_survey.py through `metadata_edit.start_new_survey`."""
        dialog = metadata_edit.NewSurveyDialog(self.surveys_dir, self)
        accepted, values, out = dialog.exec(), dialog.values(), dialog.out_path()
        dialog.deleteLater()
        if accepted:
            metadata_edit.start_new_survey(self, self.state, values, out)

    # ------------------------------------------------------------- slots

    def _selection_changed(self) -> None:
        """Set `State.site` from the selected row."""
        if self._syncing:
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item is not None:
            self.state.set_site(item.text())

    def select_site(self, name: str) -> None:
        """Select `name`'s row after another tab changes the site."""
        self._update_rebuild()
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
