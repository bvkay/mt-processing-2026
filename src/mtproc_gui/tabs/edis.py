# -*- coding: utf-8 -*-
"""
View EDIs tab

mtpy-v2 transfer function plots over a checkable tree with two groups. The
first lists every `*.edi` in `<workspace>/tf` written by
`scripts/process_rr.py`, ordered by stem so the newest run of a pair is last.
A stem in `run_stem`'s format is labelled by `_run_label`
("S01 rr S02, 23 Sep 21:15, hann"); any other EDI keeps its file name. A
row with a sidecar ends with its engine in brackets, "[aurora]" or
"[mantle]" (`mantle_products.describe`; a MANTLE run's fine-grid EDI reads
"[mantle fine grid]"). The
second group lists the lemimt reference EDIs declared in
`<survey>/reference_edis.yaml` (site -> {edi, distance_km}), which are read
from the field drive. Ticked rows are overlaid on one matplotlib canvas
(`FigureCanvasQTAgg` with `NavigationToolbar2QT`). The mtpy calls live in
`mtproc_gui.tf_plot`: `PlotMTResponse` for a single station and
`PlotMultipleResponses(plot_style="compare")` for an overlay, xy and yx
(`plot_num=1`), with mtpy's error bars. New EDIs are made on the Process tab.

Quick view (on by default) draws the current row, moved with the arrow keys
or by a click, together with every ticked row, so a survey can be stepped
through one EDI at a time against a fixed reference. Redraws are debounced
by a single-shot 150 ms timer, so holding an arrow key queues one draw. With
quick view off only the ticked rows are drawn.

The Plot group selects what mtpy draws: apparent resistivity and phase, the
same plus a row of phase tensor ellipses per station, or the same plus the
tipper. The tipper button is disabled on a survey whose sites declare no hz
channel, since the aurora EDIs then carry a tipper estimated from an open Bz
input. It is kept for induction arrows on long-period data.

The Phase group selects how the yx phase is shown. mtpy folds it into the xy
curve's 0-90 quadrant (+180 on every yx phase value; "0 to 90 deg", the
default of `tf_plot._apply_phase_range`). "-180 to 180 deg" undoes the fold,
so a physical yx (usually near -135) and a mode 180 deg out of quadrant show
where they sit. The choice applies to every EDI drawn, overlays and quick
view alike, and persists across Plot changes and redraws.

The Apparent resistivity fields (`rho_min_edit`, `rho_max_edit`; "auto"
placeholder, blank for mtpy's own scale) set the resistivity axes' y limits
in Ohm m, so an outlier cannot flatten the rest of the curve. A field
commits on `editingFinished` through the same debounce. A min at or above
the max, or either at or below zero, is not applied and is reported on the
status line. Like Phase, the values apply to every EDI drawn and persist
until changed.

A MANTLE product among the rows drawn (the quick-view row first, then the
ticked rows) adds its verdict strip under the resistivity panels
(`tf_plot.draw(verdicts=...)`, from `<stem>.mantle_report.json` through
`mantle_products.word_ranges`), its verdict word counts from the sidecar
on `mantle_label` under the tree, and the "MANTLE notes..." button, which
opens the report's summary and notes as plain text (`show_notes`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

import yaml
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtproc_gui import mantle_products, tf_plot

# redraw delay, so holding an arrow key queues one mtpy draw
DEBOUNCE_MS = 150
NO_HZ_TIP = "no hz sensor on this survey"
MAX_RHO = 1e12  # the Apparent resistivity fields' validator ceiling, Ohm m
EMPTY_HINT = ("tick a transfer function on the left, or switch Quick view on\n"
              "and step through the list with the arrow keys")
# scripts/process_rr.run_stem's own format: <local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>]
_STEM_RE = re.compile(r"^(?P<local>.+)_rr-(?P<remote>.+?)_(?P<stamp>\d{8}-\d{4})(?:_(?P<tag>.+))?$")


def _run_label(stem: str) -> str | None:
    """Build a tree label from a `run_stem` file stem.

    Args:
        stem (str): EDI file stem.

    Returns:
        str | None: "<local> rr <remote>, <DD Mon HH:MM>[, <tag>]", e.g.
        "S01 rr S02, 23 Sep 21:15, hann"; None when `stem` does not match
        the `run_stem` format.
    """
    match = _STEM_RE.match(stem)
    if not match:
        return None
    try:
        stamp = dt.datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M")
    except ValueError:
        return None
    label = f"{match.group('local')} rr {match.group('remote')}, {stamp.strftime('%d %b %H:%M')}"
    tag = match.group("tag")
    return f"{label}, {tag}" if tag else label


class EdiTab(QWidget):
    """A checkable tree of EDIs beside one mtpy canvas.

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._checked: set[str] = set()
        self.last_seconds: float | None = None
        self.draws = 0  # number of mtpy draws, used to test the debounce

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["transfer function"])
        self.tree.setMinimumWidth(280)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemClicked.connect(self._item_clicked)

        self.quick_check = QCheckBox("Quick view (arrow keys step through the list)", self)
        self.quick_check.setChecked(True)
        self.quick_check.setToolTip(
            "Draw the row under the cursor on its own, with any ticked rows under it"
        )
        self.quick_check.toggled.connect(lambda _on: self.schedule())

        self.rho_radio = QRadioButton("rho and phase", self)
        self.pt_radio = QRadioButton("plus phase tensor", self)
        self.tipper_radio = QRadioButton("plus tipper", self)
        self.rho_radio.setChecked(True)
        plot_box = QGroupBox("Plot", self)
        plot_layout = QVBoxLayout(plot_box)
        for radio in (self.rho_radio, self.pt_radio, self.tipper_radio):
            plot_layout.addWidget(radio)
            radio.toggled.connect(self._choice_toggled)

        self.phase_fold_radio = QRadioButton("0 to 90 deg", self)
        self.phase_unfold_radio = QRadioButton("-180 to 180 deg", self)
        self.phase_fold_radio.setChecked(True)
        self.phase_fold_radio.setToolTip("mtpy's own fold: yx phase + 180, same quadrant as xy")
        self.phase_unfold_radio.setToolTip(
            "yx phase as mtpy computes it, unfolded -- a physical yx sits near -135"
        )
        phase_box = QGroupBox("Phase", self)
        phase_layout = QVBoxLayout(phase_box)
        for radio in (self.phase_fold_radio, self.phase_unfold_radio):
            phase_layout.addWidget(radio)
            radio.toggled.connect(self._choice_toggled)

        self.rho_min_edit = QLineEdit(self)
        self.rho_max_edit = QLineEdit(self)
        rho_validator = QDoubleValidator(0.0, MAX_RHO, 6, self)
        rho_validator.setNotation(QDoubleValidator.StandardNotation)
        for edit in (self.rho_min_edit, self.rho_max_edit):
            edit.setValidator(rho_validator)
            edit.setPlaceholderText("auto")
            edit.setMaximumWidth(90)
            edit.editingFinished.connect(self.schedule)
        rho_box = QGroupBox("Apparent resistivity", self)
        rho_layout = QHBoxLayout(rho_box)
        rho_layout.addWidget(QLabel("min", self))
        rho_layout.addWidget(self.rho_min_edit)
        rho_layout.addWidget(QLabel("max", self))
        rho_layout.addWidget(self.rho_max_edit)
        rho_layout.addWidget(QLabel("Ohm m", self))
        rho_layout.addStretch(1)

        self.refresh_button = QPushButton("Refresh list", self)
        self.refresh_button.clicked.connect(self.reload)
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.mantle_label = QLabel("", self)
        self.mantle_label.setWordWrap(True)
        self.notes_button = QPushButton("MANTLE notes...", self, enabled=False)
        self.notes_button.setToolTip("the summary and plain-language notes of the MANTLE report drawn")
        self.notes_button.clicked.connect(self.show_notes)
        self._mantle_row: tuple[str, Path] | None = None
        self._notes_dialog: QDialog | None = None

        self.figure = Figure(figsize=(9.0, 7.0), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.redraw)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.tree, 1)
        left_layout.addWidget(self.quick_check)
        left_layout.addWidget(plot_box)
        left_layout.addWidget(phase_box)
        left_layout.addWidget(rho_box)
        left_layout.addWidget(self.mantle_label)
        left_layout.addWidget(self.notes_button)
        left_layout.addWidget(self.refresh_button)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        header = QHBoxLayout()
        header.addWidget(QLabel("Tick to overlay; the cursor row draws on its own", self))
        header.addWidget(self.status_label, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self.state.runner.job_finished.connect(self._job_finished)
        self._update_tipper_button()
        self.redraw()

    # ------------------------------------------------------------ the lists

    def reload(self) -> None:
        """Re-list both groups, keeping the ticked rows."""
        self.tree.blockSignals(True)
        self.tree.clear()
        tf_dir = self.state.tf_dir()
        processed = QTreeWidgetItem(self.tree, [f"processed ({tf_dir})" if tf_dir else "processed"])
        processed.setFlags(Qt.ItemIsEnabled)
        if tf_dir is not None and tf_dir.exists():
            # ordered by stem, not path: a run_stem stamp sorts chronologically as a
            # string (zero-padded YYYYMMDD-HHMM), so the newest run of a pair is last
            for path in sorted(tf_dir.glob("*.edi"), key=lambda p: p.stem):
                label = _run_label(mantle_products.product_stem(path)) or path.name
                suffix = mantle_products.describe(path)
                self._add_leaf(processed, f"{label} {suffix}" if suffix else label, path)
        lemimt = QTreeWidgetItem(self.tree, ["lemimt reference"])
        lemimt.setFlags(Qt.ItemIsEnabled)
        for site, entry in self._references().items():
            path = Path(str(entry.get("edi", "")))
            distance = entry.get("distance_km")
            label = f"{site} (lemimt)" + (f"  {float(distance):g} km" if distance is not None else "")
            self._add_leaf(lemimt, label, path)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._update_tipper_button()
        self.schedule()

    def _references(self) -> dict:
        """Return the reference_edis.yaml mapping, or {} when absent."""
        path = self.state.reference_edis_yaml()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _add_leaf(self, parent: QTreeWidgetItem, label: str, path: Path) -> None:
        """Add a checkable EDI row, greyed when the file is missing."""
        item = QTreeWidgetItem(parent, [label])
        item.setData(0, Qt.UserRole, str(path))
        # selectable as well as checkable: the arrow keys move the current
        # row, which quick view draws
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        item.setCheckState(0, Qt.Checked if str(path) in self._checked else Qt.Unchecked)
        if not path.exists():
            item.setForeground(0, QBrush(QColor("#909090")))
            item.setToolTip(0, f"{path} is not there (external drive not mounted?)")

    def check(self, needle: str, on: bool = True) -> bool:
        """Tick the first leaf whose label or path contains `needle`."""
        for item in self._leaves():
            if needle in item.text(0) or needle in str(item.data(0, Qt.UserRole)):
                item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                return True
        return False

    def _leaves(self):
        """Yield every EDI row of both groups."""
        for top in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(top)
            for row in range(parent.childCount()):
                yield parent.child(row)

    def checked_files(self) -> list[tuple[str, Path]]:
        """Return (label, path) of every ticked row."""
        return [
            (item.text(0), Path(str(item.data(0, Qt.UserRole))))
            for item in self._leaves()
            if item.checkState(0) == Qt.Checked
        ]

    def quick_row(self) -> tuple[str, Path] | None:
        """Return (label, path) of the current row when quick view is on, else None."""
        if not self.quick_check.isChecked():
            return None
        item = self.tree.currentItem()
        path = None if item is None else item.data(0, Qt.UserRole)
        if not path:  # a group header, or nothing current
            return None
        return item.text(0), Path(str(path))

    # --------------------------------------------------------------- slots

    def _item_changed(self, _item, _column) -> None:
        """Record the ticked rows and schedule a redraw."""
        self._checked = {str(p) for _label, p in self.checked_files()}
        self.schedule()

    def _current_changed(self, _current, _previous) -> None:
        """Schedule a redraw when the current row moves in quick view."""
        if self.quick_check.isChecked():
            self.schedule()

    def _item_clicked(self, _item, _column) -> None:
        """Keep keyboard focus on the tree after a click, so the arrow keys step through it."""
        self.tree.setFocus()

    def _choice_toggled(self, on: bool) -> None:
        """Schedule a redraw when a radio button is switched on."""
        if on:  # a radio group fires twice, off then on
            self.schedule()

    def _job_finished(self, index: int, ok: bool) -> None:
        """Clear the EDI cache and re-list after a successful process_rr job rewrote `<workspace>/tf`."""
        job = self.state.runner.jobs[index]
        if ok and "process_rr" in job.label:
            tf_plot.clear_cache()
            self.reload()

    # ------------------------------------------------------------- the plot

    def choice(self) -> str:
        """Return the `tf_plot.CHOICES` entry selected by the Plot radio buttons."""
        if self.pt_radio.isChecked():
            return "pt"
        if self.tipper_radio.isChecked():
            return "tipper"
        return "rho"

    def phase_range(self) -> str:
        """Return the `tf_plot.PHASE_CHOICES` entry selected by the Phase radio buttons."""
        if self.phase_unfold_radio.isChecked():
            return tf_plot.PHASE_UNFOLDED
        return tf_plot.PHASE_FOLDED

    def rho_limits(self) -> tuple[float | None, float | None]:
        """Return (min, max) in Ohm m from the Apparent resistivity fields.

        A blank or unparsable field gives None, which `tf_plot` treats as
        mtpy's automatic value.
        """

        def value(edit: QLineEdit) -> float | None:
            text = edit.text().strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None

        return value(self.rho_min_edit), value(self.rho_max_edit)

    def _survey_has_hz(self) -> bool:
        """True if any site of the survey declares a vertical magnetic channel (hz; bz on a LEMI-424).

        A site with no `channels:` declaration counts as having one. A survey
        declares `channels: [ex, ey, hx, hy]` when its loggers carried no hz
        sensor; the B423 Bz column is then an open input and any tipper in
        the EDIs is estimated from a dead channel.
        """
        survey = self.state.survey
        if survey is None:
            return False
        for name in self.state.configured_sites():
            channels = survey.site(name).channels
            if channels is None or any(str(c).lower() in ("hz", "bz") for c in channels):  # LEMI-424: bz
                return True
        return False

    def _update_tipper_button(self) -> None:
        """Enable the tipper button only on a survey with an hz channel."""
        has_hz = self._survey_has_hz()
        self.tipper_radio.setEnabled(has_hz)
        self.tipper_radio.setToolTip("" if has_hz else NO_HZ_TIP)
        if not has_hz and self.tipper_radio.isChecked():
            self.rho_radio.setChecked(True)

    def rows_to_draw(self) -> tuple[list[tuple[str, Path]], tuple[str, Path] | None]:
        """Return (rows, quick row): the current row first in quick view, then every ticked row."""
        quick = self.quick_row()
        rows = list(self.checked_files())
        if quick is not None:
            rows = [quick] + [row for row in rows if str(row[1]) != str(quick[1])]
        return rows, quick

    def schedule(self) -> None:
        """Request a redraw in `DEBOUNCE_MS`, replacing any pending one."""
        self._timer.start()

    def mantle_row(self, rows) -> tuple[str, Path] | None:
        """Return the first row that is a MANTLE product with a report, or None."""
        for label, path in rows:
            if mantle_products.engine_of(path) == "mantle" and mantle_products.report_of(path):
                return label, path
        return None

    def _describe_mantle(self, row: tuple[str, Path] | None) -> None:
        """Show the verdict word counts of the MANTLE product drawn and enable its notes button."""
        self._mantle_row = row
        if row is None:
            self.mantle_label.setText("")
            self.notes_button.setEnabled(False)
            return
        label, path = row
        sidecar = mantle_products.sidecar_of(path) or {}
        counts = mantle_products.word_counts(sidecar)
        tally = ", ".join(f"{word} {n}" for word, n in counts.items()) or "none recorded"
        gate = (sidecar.get("engine_config") or {}).get("snr_gate_ran")
        self.mantle_label.setText(f"MANTLE verdicts of {label}: {tally}"
                                  + ("" if gate is None else f"; snr gate ran: {gate}"))
        self.notes_button.setEnabled(True)

    def show_notes(self) -> QDialog | None:
        """Open the MANTLE report's summary and notes as plain text; returns the dialog."""
        if self._mantle_row is None:
            return None
        label, path = self._mantle_row
        text = mantle_products.notes_text(mantle_products.report_of(path), title=f"MANTLE report of {label}")
        if self._notes_dialog is None:
            self._notes_dialog = QDialog(self)
            self._notes_dialog.setWindowTitle("MANTLE notes")
            self._notes_dialog.resize(720, 480)
            layout = QVBoxLayout(self._notes_dialog)
            self._notes_view = QPlainTextEdit(self._notes_dialog, readOnly=True)
            layout.addWidget(self._notes_view)
        self._notes_view.setPlainText(text)
        self._notes_dialog.show()
        self._notes_dialog.raise_()
        return self._notes_dialog

    def redraw(self) -> None:
        """Draw the current rows with mtpy, on the GUI thread."""
        self._timer.stop()
        rows, quick = self.rows_to_draw()
        if rows:
            self.status_label.setText("drawing...")
            self.status_label.repaint()
        title = " + ".join(label for label, _p in rows)
        if quick is not None:
            title = f"{title}   [quick view: {quick[1].name}]"
        mantle = self.mantle_row(rows)
        verdicts = None
        if mantle is not None:
            verdicts = (mantle[0], mantle_products.word_ranges(mantle_products.report_of(mantle[1])))
        self._describe_mantle(mantle)
        started = time.perf_counter()
        drawn, problems = tf_plot.draw(
            self.figure, rows, self.choice(), title=title, hint=EMPTY_HINT,
            phase_range=self.phase_range(), rho_limits=self.rho_limits(), verdicts=verdicts,
        )
        self.canvas.draw_idle()
        self.last_seconds = time.perf_counter() - started
        self.draws += 1
        if drawn:
            summary = (f"{len(drawn)} EDI{'s' if len(drawn) != 1 else ''}: "
                       f"{', '.join(drawn)}  ({self.last_seconds:.2f} s)")
        else:
            summary = "nothing to draw - tick a row, or switch Quick view on"
        self.status_label.setText(summary + ("; " + "; ".join(problems) if problems else ""))
