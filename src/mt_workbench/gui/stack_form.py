# -*- coding: utf-8 -*-
"""
Recipe form of the Stacks tab

`RecipeForm` edits one stack recipe of stacks.yaml
(`mt_workbench.stacks.Recipe`): its name, method, field, use, sample rate,
members, window, the method's parameters, whether the members' declared
filters apply, and notes. The method dropdown is grouped by engine: "Band
stack, formed in each run" (band mean, band median: scripts/process_intersite.py
forms them per band inside each run, as the base or the reference) and
"Archive for process_rr.py" (time mean, time coherence-weighted:
scripts/build_stack.py writes an archive). Only the keys
`stacks.applicable_keys` gives for the method and use are shown, and the
rule radio is disabled for the time methods, which take an explicit list so
that the archive leaves out the station it is later the remote of.

The member list holds every survey.yaml site at the recipe's rate, one row
each: the site, its overlap with the window, its declared filters, its coil
declarations (swap_h, flip_h, rot_h), its dc-level verdicts, the member check's
flags and the reason the recipe leaves it out, the last four from the
Stacks chart's rows (`set_rows`) and the check (`set_flags`). Under the rule
an unticked site is excluded; under a list a ticked site is a member. Names
the recipe holds that the list does not show (a site at another rate, a name
with no survey.yaml entry) are carried over unchanged.

The window is the chart's (`set_window`); "write it into the recipe" makes
it part of a band recipe, and a time recipe always holds it. `recipe()`
returns `stacks.Recipe.from_mapping` of the fields, so the form validates
exactly as stacks.yaml is read, and raises its `StacksError`, which names
the key. The form writes nothing; the tab's Save recipe does.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QWidget,
)

from mt_workbench import intersite, stacks
from mt_workbench.dclevel import OK as DC_OK
from mt_workbench.gui.theme import BAD_COLOUR, IDLE_COLOUR, OK_COLOUR, WARN_COLOUR

# the method dropdown: a header per engine, then its methods
GROUPS = (("Band stack, formed in each run", ("band_mean", "band_median")),
          ("Archive for process_rr.py", ("time_mean", "time_coherence")))
COLUMNS = ("site", "overlap h", "reason", "check", "dc level", "filters", "swap_h / flip_h / rot_h")
REASON_WIDTH = 230  # px: a long reason is cut, and its tooltip holds it whole
RENAME_HINT = ("Saving under a new name adds a recipe; the old one stays in stacks.yaml until you remove it "
               "there.")
ROLES_TEXT = {"H": "hx, hy", "E": "ex, ey"}
USE_TEXT = {"base": "base: the stack is the tensor's input field",
            "reference": "reference: the stack is the remote reference",
            "remote": "remote: an archive for process_rr.py"}
NO_WINDOW = "none yet: the chart has not read the archives"
LOCAL_REASON = "the local"  # intersite.select_stack's reason for the local


def _rate_text(rate: float) -> str:
    """Return a sample rate as the dropdown shows it."""
    return f"{rate:g} Hz"


def new_name(field: str, taken) -> str:
    """Return the first free name ``STK_<field><k>``, k = 1, 2, ...

    Args:
        field (str): "H" or "E".
        taken (iterable of str): Names in use (recipes and sites).

    Returns:
        str: The name.
    """
    taken = set(taken)
    k = 1
    while f"STK_{field}{k}" in taken:
        k += 1
    return f"STK_{field}{k}"


class RecipeForm(QWidget):
    """The fields of one stack recipe, in and out of a `stacks.Recipe`.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    changed = Signal()  # an edit by the user; set_recipe, set_rows, set_flags and a silent set_window emit nothing

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._loading = False
        self._rows: dict = {}  # site -> availability_model.Row, from the chart
        self._flags: dict[str, str] = {}  # site -> the member check's flags, as text
        self._checked: dict[str, bool] = {}  # site -> ticked in the member list
        self._extra: tuple[str, ...] = ()  # names in the recipe's list or exclude the member list does not show
        self._window: tuple[pd.Timestamp, pd.Timestamp] | None = None

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("STK_...")
        self.name_edit.setToolTip("STK_ then letters and digits in parts joined by single underscores, at most "
                                  f"{stacks.NAME_MAX} characters")
        self.rename_hint = QLabel(RENAME_HINT, self, wordWrap=True)
        self.rename_hint.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.method_combo = QComboBox(self)
        for header, keys in GROUPS:
            self.method_combo.addItem(header, None)
            self.method_combo.model().item(self.method_combo.count() - 1).setEnabled(False)
            for key in keys:
                self.method_combo.addItem(f"    {stacks.METHODS[key].label}", key)
        self.field_h = QRadioButton("H", self)
        self.field_e = QRadioButton("E", self)
        self.field_group = QButtonGroup(self)
        for button in (self.field_h, self.field_e):
            self.field_group.addButton(button)
        self.roles_label = QLabel("", self)
        self.roles_label.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.use_combo = QComboBox(self)
        self.rate_combo = QComboBox(self)
        self.rule_radio = QRadioButton("rule: every site at the rate covering the window", self)
        self.list_radio = QRadioButton("list: the sites ticked", self)
        self.members_group = QButtonGroup(self)
        for button in (self.rule_radio, self.list_radio):
            self.members_group.addButton(button)
        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setMinimumHeight(170)
        self.table.setToolTip("Under the rule an unticked site is excluded; under a list a ticked site is a member")

        self.overlap_spin = QDoubleSpinBox(self, decimals=2, minimum=0.01, maximum=10000.0, suffix=" h")
        self.overlap_spin.setToolTip("A member must cover this much of the window, or all of a shorter window")
        self.reject_spin = QDoubleSpinBox(self, decimals=1, minimum=1.1, maximum=1.0e6)
        self.reject_spin.setToolTip("A member's window over this many times the members' level is left out")
        self.min_members_spin = QSpinBox(self, minimum=1, maximum=999)
        self.min_members_spin.setToolTip("A window keeping fewer members than this is left out of the band")
        self.polarity_combo = QComboBox(self)
        self.polarity_combo.addItems(list(stacks.POLARITY))
        self.polarity_combo.setToolTip("flag: record a reversed member; drop: leave it out of the stack")
        self.change_combo = QComboBox(self)
        self.change_combo.addItems(list(stacks.MEMBER_CHANGE))
        self.change_combo.setToolTip("constant: refuse a window whose membership changes; allow: take it")
        self.window_label = QLabel(NO_WINDOW, self)
        self.window_check = QCheckBox("write it into the recipe", self)
        self.window_check.setToolTip("A band recipe without a window takes the run's; a time recipe needs one")
        self.filters_check = QCheckBox("use the members' declared filters", self)
        self.notes_edit = QLineEdit(self)
        self.notes_edit.setPlaceholderText("remarks kept in the recipe, outside its hash")
        self.rule_label = QLabel("", self, wordWrap=True)
        self.rule_label.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.error_label = QLabel("", self, wordWrap=True)
        self.error_label.setStyleSheet(f"color: {BAD_COLOUR}")
        self._build_layout()

        self.name_edit.textEdited.connect(self._edited)
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self.field_group.buttonClicked.connect(self._field_changed)
        self.use_combo.currentIndexChanged.connect(self._edited)
        self.rate_combo.currentIndexChanged.connect(self._rate_changed)
        self.members_group.buttonClicked.connect(self._members_mode_changed)
        self.table.itemChanged.connect(self._item_changed)
        for spin in (self.overlap_spin, self.reject_spin, self.min_members_spin):
            spin.valueChanged.connect(self._edited)
        for combo in (self.polarity_combo, self.change_combo):
            combo.currentIndexChanged.connect(self._edited)
        for check in (self.window_check, self.filters_check):
            check.toggled.connect(self._edited)
        self.notes_edit.textEdited.connect(self._edited)

    def _build_layout(self) -> None:
        """Lay the fields out as one form, the member list across both columns."""
        field_row = QHBoxLayout()
        for widget in (self.field_h, self.field_e, self.roles_label):
            field_row.addWidget(widget)
        field_row.addStretch(1)
        members_row = QHBoxLayout()
        members_row.addWidget(self.rule_radio)
        members_row.addWidget(self.list_radio)
        members_row.addStretch(1)
        window_row = QHBoxLayout()
        window_row.addWidget(self.window_label, 1)
        window_row.addWidget(self.window_check)
        self.layout_ = QFormLayout(self)
        self.layout_.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.layout_.addRow("Name", self.name_edit)
        self.layout_.addRow("", self.rename_hint)
        self.layout_.addRow("Method", self.method_combo)
        self.layout_.addRow("Field", field_row)
        self.layout_.addRow("Use", self.use_combo)
        self.layout_.addRow("Sample rate", self.rate_combo)
        self.layout_.addRow("Members", members_row)
        self.layout_.addRow(self.table)
        self.layout_.addRow("Min overlap", self.overlap_spin)
        self.layout_.addRow("Reject factor", self.reject_spin)
        self.layout_.addRow("Min members", self.min_members_spin)
        self.layout_.addRow("Polarity screen", self.polarity_combo)
        self.layout_.addRow("Member change", self.change_combo)
        self.layout_.addRow("Window", window_row)
        self.layout_.addRow("Filters", self.filters_check)
        self.layout_.addRow("Notes", self.notes_edit)
        self.layout_.addRow("Rule", self.rule_label)
        self.layout_.addRow(self.error_label)
        self._parameter_widgets = {"min_overlap_hours": self.overlap_spin, "reject_factor": self.reject_spin,
                                   "min_members": self.min_members_spin, "screen_polarity": self.polarity_combo,
                                   "member_change": self.change_combo}

    # ------------------------------------------------------------ public

    def reload(self) -> None:
        """Take the new survey's sample rates; forget the rows, flags and window of the last one."""
        self._rows, self._flags, self._window = {}, {}, None
        self._loading = True
        try:
            self.rate_combo.clear()
            for rate in self.rates():
                self.rate_combo.addItem(_rate_text(rate), rate)
        finally:
            self._loading = False
        self.set_recipe(None)

    def rates(self) -> list[float]:
        """Return the survey's sample rates, highest first."""
        survey = self.state.survey
        if survey is None:
            return []
        out = set()
        for site in survey.site_names():
            try:
                out.add(float(survey.sample_rate_of(site)))
            except (KeyError, ValueError, TypeError):
                continue
        return sorted(out, reverse=True)

    def set_recipe(self, recipe, default_rate: float | None = None, taken=()) -> None:
        """Show a recipe, or a new one; emits nothing.

        Args:
            recipe (stacks.Recipe | None): The recipe; None for a new one:
                band mean, field H, use base, members by rule, no window,
                named ``STK_H<k>`` with the first k not in `taken`.
            default_rate (float | None): A new recipe's sample rate (the
                tab's local's); None for the survey's.
            taken (iterable of str): Names a new recipe may not take.
        """
        self._loading = True
        try:
            if recipe is None:
                survey = self.state.survey
                rate = default_rate if default_rate is not None else (survey.sample_rate if survey else None)
                self.name_edit.setText(new_name("H", taken))
                self._set_method(stacks.DEFAULT_METHOD)
                self.field_h.setChecked(True)
                self._fill_uses("base")
                self._set_rate(rate)
                self.rule_radio.setChecked(True)
                self._checked, self._extra = {}, ()
                self.overlap_spin.setValue(intersite.MIN_OVERLAP_HOURS)
                self.reject_spin.setValue(intersite.STACK_REJECT_FACTOR)
                self.min_members_spin.setValue(intersite.STACK_MIN_MEMBERS)
                self.polarity_combo.setCurrentText(stacks.POLARITY[0])
                self.change_combo.setCurrentText(stacks.MEMBER_CHANGE[0])
                self.window_check.setChecked(False)
                self.filters_check.setChecked(True)
                self.notes_edit.setText("")
            else:
                self.name_edit.setText(recipe.name)
                self._set_method(recipe.method)
                (self.field_h if recipe.field == "H" else self.field_e).setChecked(True)
                self._fill_uses(recipe.use)
                self._set_rate(recipe.sample_rate)
                shown = set(self._sites())
                if recipe.members is None:
                    self.rule_radio.setChecked(True)
                    self._checked = {s: s not in recipe.exclude for s in shown}
                    self._extra = tuple(s for s in recipe.exclude if s not in shown)
                else:
                    self.list_radio.setChecked(True)
                    self._checked = {s: s in recipe.members for s in shown}
                    self._extra = tuple(s for s in recipe.members if s not in shown)
                for key, widget in self._parameter_widgets.items():
                    value = getattr(recipe, key)
                    if value is None:
                        continue
                    if isinstance(widget, QComboBox):
                        widget.setCurrentText(value)
                    else:
                        widget.setValue(value)
                self.window_check.setChecked(recipe.start is not None)
                if recipe.start is not None:
                    self._window = (recipe.start, recipe.end)
                self.filters_check.setChecked(recipe.use_filters)
                self.notes_edit.setText(recipe.notes)
        finally:
            self._loading = False
        self._refresh()

    def recipe(self) -> stacks.Recipe:
        """Return the recipe the fields declare.

        Returns:
            stacks.Recipe: Made by `stacks.Recipe.from_mapping`.

        Raises:
            stacks.StacksError: Naming the key, as stacks.yaml would.
        """
        name = self.name_edit.text().strip()
        method = self.method_combo.currentData()
        use = self.use_combo.currentData()
        mapping = {"field": "H" if self.field_h.isChecked() else "E", "use": use, "method": method}
        rate = self.rate_combo.currentData()
        if rate is not None:
            mapping["sample_rate"] = float(rate)
        keys = stacks.applicable_keys(method, use)
        shown = self._sites()
        if self.rule_radio.isChecked() and stacks.METHODS[method].engine == "band":
            mapping["members"] = stacks.MEMBER_RULE
            excluded = sorted({s for s in shown if not self._checked.get(s, True)} | set(self._extra))
            if excluded:
                mapping["exclude"] = excluded
        else:
            mapping["members"] = sorted({s for s in shown if self._checked.get(s, False)} | set(self._extra))
        for key, widget in self._parameter_widgets.items():
            if key in keys:
                mapping[key] = widget.currentText() if isinstance(widget, QComboBox) else widget.value()
        if (self.window_check.isChecked() or stacks.METHODS[method].engine == "time") and self._window:
            mapping["start"], mapping["end"] = self._window
        mapping["use_filters"] = self.filters_check.isChecked()
        notes = self.notes_edit.text().strip()
        if notes:
            mapping["notes"] = notes
        return stacks.Recipe.from_mapping(name, mapping)

    def rate(self) -> float | None:
        """Return the sample rate chosen, Hz."""
        rate = self.rate_combo.currentData()
        return None if rate is None else float(rate)

    def method(self) -> str:
        """Return the method chosen (a key of `stacks.METHODS`)."""
        return self.method_combo.currentData()

    def set_window(self, start, end, emit: bool = True) -> None:
        """Take the chart's window.

        Args:
            start, end (pd.Timestamp | None): UTC; None for no window.
            emit (bool): Emit `changed` (an edit by the user on the chart); the
                tab passes False when it only follows the chart's default.
        """
        window = None if start is None or end is None else (pd.Timestamp(start), pd.Timestamp(end))
        if window == self._window:
            return
        self._window = window
        self._show_window()
        if emit:
            self._edited()
        else:
            self._show_rule()

    def window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the chart's window as the form holds it."""
        return self._window

    def set_rows(self, rows) -> None:
        """Take the chart's rows for the member list's overlap, dc level and reason columns; emits nothing."""
        self._rows = {row.site: row for row in rows}
        self._fill_table()

    def set_flags(self, flags: dict) -> None:
        """Show the member check's flags, {site: text}; emits nothing."""
        self._flags = dict(flags)
        self._fill_table()

    def set_error(self, text: str) -> None:
        """Show why the fields do not make a recipe ("" clears it)."""
        self.error_label.setText(text)

    # ------------------------------------------------------- the fields

    def _sites(self) -> list[str]:
        """Return the survey.yaml sites at the chosen rate, sorted."""
        survey, rate = self.state.survey, self.rate()
        if survey is None or rate is None:
            return []
        out = []
        for site in survey.site_names():
            try:
                if math.isclose(float(survey.sample_rate_of(site)), rate, rel_tol=1e-9):
                    out.append(site)
            except (KeyError, ValueError, TypeError):
                continue
        return sorted(out)

    def _set_method(self, method: str) -> None:
        """Select a method in the dropdown."""
        index = self.method_combo.findData(method)
        self.method_combo.setCurrentIndex(index if index >= 0 else self.method_combo.findData(stacks.DEFAULT_METHOD))

    def _fill_uses(self, wanted: str | None = None) -> None:
        """Offer the uses of the chosen method, keeping `wanted` (or the current use) when it is one."""
        wanted = wanted or self.use_combo.currentData()
        uses = stacks.METHODS[self.method()].uses
        self.use_combo.blockSignals(True)
        try:
            self.use_combo.clear()
            for use in uses:
                self.use_combo.addItem(USE_TEXT[use], use)
            index = self.use_combo.findData(wanted)
            self.use_combo.setCurrentIndex(max(0, index))
        finally:
            self.use_combo.blockSignals(False)

    def _set_rate(self, rate) -> None:
        """Select a rate, adding it to the dropdown when no site of the survey has it."""
        if rate is None:
            return
        index = self.rate_combo.findData(float(rate))
        if index < 0:
            self.rate_combo.addItem(_rate_text(float(rate)), float(rate))
            index = self.rate_combo.count() - 1
        self.rate_combo.setCurrentIndex(index)

    def _edited(self, *_args) -> None:
        """Refresh what depends on the fields and tell the tab, unless the form is being filled."""
        if self._loading:
            return
        self._refresh()
        self.changed.emit()

    def _method_changed(self, _index: int) -> None:
        """Offer the method's uses; a time method takes a list."""
        if self.method() is None:  # a group header: back to the method above it
            self.method_combo.setCurrentIndex(self.method_combo.currentIndex() + 1)
            return
        self._fill_uses()
        if stacks.METHODS[self.method()].engine == "time" and self.rule_radio.isChecked():
            self.list_radio.setChecked(True)
            self._start_list()
        self._edited()

    def _field_changed(self, _button) -> None:
        """Take H or E."""
        self._edited()

    def _rate_changed(self, _index: int) -> None:
        """Show the sites at the new rate; a site not met before starts ticked under the rule only."""
        self._fill_table()
        self._edited()

    def _members_mode_changed(self, _button) -> None:
        """Rule: every site ticked (none excluded). List: the rule's members over the window ticked."""
        if self.list_radio.isChecked():
            self._start_list()
        else:
            self._checked = {s: True for s in self._sites()}
            self._extra = ()
        self._fill_table()
        self._edited()

    def _start_list(self) -> None:
        """Tick the chart's present members, so a list starts from what the rule gives."""
        self._checked = {s: bool(self._rows.get(s) is not None and self._rows[s].member) for s in self._sites()}
        self._extra = ()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        """Take a tick or untick in the member list."""
        if self._loading or item.column() != 0:
            return
        self._checked[item.text()] = item.checkState() == Qt.Checked
        self._edited()

    # ---------------------------------------------------------- display

    def _refresh(self) -> None:
        """Show the keys the method and use take, the roles, the window, the member list and the rule."""
        method = self.method()
        time_method = method is not None and stacks.METHODS[method].engine == "time"
        try:
            keys = stacks.applicable_keys(method, self.use_combo.currentData())
        except stacks.StacksError:
            keys = ()
        for key, widget in self._parameter_widgets.items():
            self.layout_.setRowVisible(widget, key in keys)
        self.rule_radio.setEnabled(not time_method)
        self.rule_radio.setToolTip("A time recipe takes a list: its archive must leave out the station it is "
                                   "later the remote of" if time_method else "")
        self.window_check.setEnabled(not time_method)
        if time_method and not self.window_check.isChecked():
            self._loading, was = True, self._loading
            self.window_check.setChecked(True)
            self._loading = was
        self.roles_label.setText(ROLES_TEXT["H" if self.field_h.isChecked() else "E"])
        self._show_window()
        self._fill_table()
        self._show_rule()

    def _show_window(self) -> None:
        """Write the chart's window beside the window switch."""
        if self._window is None:
            self.window_label.setText(NO_WINDOW)
            return
        start, end = self._window
        tail = "%H:%M" if start.date() == end.date() else "%Y-%m-%d %H:%M"
        self.window_label.setText(f"{start:%Y-%m-%d %H:%M} to {end.strftime(tail)} UTC (the chart's)")

    def _show_rule(self) -> None:
        """Show the rule the recipe records, and why the fields do not make a recipe."""
        try:
            recipe = self.recipe()
        except stacks.StacksError as exc:
            method = self.method()
            self.rule_label.setText(stacks.METHODS[method].rule if method else "")
            self.error_label.setText(str(exc))
            return
        self.rule_label.setText(stacks.rule_text(recipe))
        self.error_label.setText("")

    def _fill_table(self) -> None:
        """Fill the member list: one row per site at the rate, ticked as `_checked` says."""
        survey = self.state.survey
        sites = self._sites()
        rule = self.rule_radio.isChecked() and self.rule_radio.isEnabled()
        was = self._loading
        self._loading = True
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(sites))
            for r, site in enumerate(sites):
                row = self._rows.get(site)
                ticked = self._checked.setdefault(site, rule)
                config = survey.site(site) if survey is not None else None
                filters = ", ".join(next(iter(f)) if isinstance(f, dict) and f else str(f)
                                    for f in (config.filters or [])) if config is not None else ""
                coils = []
                if config is not None and config.swap_h:
                    coils.append("swap_h")
                if config is not None and config.flip_h:
                    coils.append("flip_h " + ", ".join(config.flip_h))
                if config is not None and config.rot_h:
                    coils.append(f"rot_h {config.rot_h:g}")
                dc = ""
                if row is not None and row.dc:
                    bad = [f"{c} {v}" for c, v in row.dc.items() if v != DC_OK]
                    dc = ", ".join(bad) if bad else DC_OK
                overlap = "" if row is None or row.overlap_h is None else f"{row.overlap_h:.2f}"
                reason = "" if row is None else ("member" if row.member else (row.reason or ""))
                cells = [site, overlap, reason, self._flags.get(site, ""), dc, filters, ", ".join(coils)]
                for c, text in enumerate(cells):
                    item = self.table.item(r, c)
                    if item is None:
                        item = QTableWidgetItem()
                        self.table.setItem(r, c, item)
                    item.setText(text)
                    item.setToolTip(text if c in (2, 4) else "")
                    colour = None
                    if c == 0 and row is not None:
                        colour = OK_COLOUR if row.reason == LOCAL_REASON else WARN_COLOUR if row.member else None
                    elif c == 3 and text:
                        colour = BAD_COLOUR
                    elif c == 2 and row is not None and not row.member:
                        colour = IDLE_COLOUR
                    item.setForeground(QBrush(QColor(colour)) if colour else QBrush())
                    if c == 0:
                        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Checked if ticked else Qt.Unchecked)
            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(2, min(self.table.columnWidth(2), REASON_WIDTH))
        finally:
            self.table.setUpdatesEnabled(True)
            self._loading = was
