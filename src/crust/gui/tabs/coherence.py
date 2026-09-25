# -*- coding: utf-8 -*-
"""
Coherence tab

Shows whether the loaded window has signal and whether the remote sees the
same field. On `qc_ready` the tab draws `SegmentQC.band_curves`
(`crust.timefreq.band_from_levels` over `BANDS_S`, the lines of figure 02 of
`scripts/site_qc.py`) for the window chosen on the Time Series tab, as one
small plot per pair on a grid of two aligned columns (`ROWS`), named by
channel pair and impedance element::

    By-Ex (Zxy)         rBy-Ex (Zxy, remote)   the two impedance pairs,
    Bx-Ey (Zyx)         rBx-Ey (Zyx, remote)   local beside remote
    Bx-By (magnetic)    Bx-rBx                 then the two coil checks
    Ex-Ey (electric)    By-rBy

Names follow the roles channels play (`crust.gui.channels.roles`), so on a
LEMI-424 the rows read "By-E1 (Zxy)", "Bx-E2 (Zyx)", ..., "E1-E2 (electric)";
the panels stay keyed by the LEMI-423 pairs of `ROWS`.

Each row places a local pair beside the matching remote pair, so a low
coherence on the left can be read against the coil check on the right.
Without a remote the right column is hidden and the four local pairs fill
the tab. Each column is one stack on one time axis, with no gap between rows
and tick labels on the bottom row only. All plots share one x range
(`qc_plots.link_x_ranges`) in minutes since the window's start, locked to the
window and to coherence 0-1 (`qc_plots.lock_view`). Over each pair's band
lines a thick white "All frequencies" curve shows their mean. The tab has no
coherogram, since the band curves already show coherence against time over
the same 1-3 h window.

Controls:

* Remote: the remote the QC is computed against (`State.remote`, none on a
  new station); changing it requests the QC again.
* The ladder's base window and step, with Recompute.
* Cursor: a vertical line on every panel, placed by clicking any panel and
  dragged on any panel. The label gives its UTC time, and "Show in Time
  Series" centres the Time Series view on it, +-5 minutes
  (`State.goto_time`).

Whole-record figures 02 and 03 come from `scripts/site_qc.py`.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from crust.timefreq import BANDS_S
from crust.gui import channels, theme
from crust.gui.plots import share_x_axis
from crust.gui.qc_plots import (
    PLACEHOLDER, LadderControls, band_legend, band_plot, draw_bands, link_x_ranges,
    lock_view, time_label, window_title,
)

# (local pair, its label, remote pair, its label): one row of the grid, in the
# LEMI-423 role names (`channels.title` names them for the loaded record). An r
# marks the remote's coil, so "rBx-Ey (Zyx, remote)" is this site's Ey against
# the remote's Bx.
ROWS = (
    (("hy", "ex"), "{hy}-{ex} (Zxy)", ("ex", "r_hy"), "{r_hy}-{ex} (Zxy, remote)"),
    (("hx", "ey"), "{hx}-{ey} (Zyx)", ("ey", "r_hx"), "{r_hx}-{ey} (Zyx, remote)"),
    (("hx", "hy"), "{hx}-{hy} (magnetic)", ("hx", "r_hx"), "{hx}-{r_hx}"),
    (("ex", "ey"), "{ex}-{ey} (electric)", ("hy", "r_hy"), "{hy}-{r_hy}"),
)
LEMI423 = {name: name for name in channels.ROLE_NAMES}  # the parts played by their own names
LOCAL_COLUMN = [row[0] for row in ROWS]
REMOTE_COLUMN = [row[2] for row in ROWS]
CURSOR_PEN = pg.mkPen(theme.CURSOR_COLOUR, width=1.5)
S_PER_UNIT = 60.0  # the x axis is in minutes


class CoherenceTab(QWidget):
    """Band-coherence lines for eight pairs on two aligned columns, with one shared cursor.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.qc = None
        self._filling = False
        self._moving = False

        self.title_label = QLabel(PLACEHOLDER, self)
        self.title_label.setStyleSheet("font-weight: bold")
        self.remote_combo = QComboBox(self, minimumWidth=160)
        self.remote_combo.setToolTip(
            "The remote the window's QC is computed against: its coils are read "
            "over the same window (it must already be archived). The site's "
            "declared remote: is preselected."
        )
        self.remote_combo.currentIndexChanged.connect(self._remote_picked)
        self.ladder = LadderControls(state, self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Remote", self))
        controls.addWidget(self.remote_combo)
        controls.addStretch(1)
        controls.addWidget(self.ladder)

        # the grid: local pairs down the left, the matching remote pair beside
        # each one. Every panel carries the same cursor.
        self.band_plots: dict[tuple[str, str], pg.PlotWidget] = {}
        self.labels: dict[tuple[str, str], str] = {}
        self.templates: dict[tuple[str, str], str] = {}
        self.cursors: dict[tuple[str, str], pg.InfiniteLine] = {}
        panels = QWidget(self)
        self.grid = QGridLayout(panels)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setVerticalSpacing(0)  # each column is one stack on one time axis
        self.grid.setHorizontalSpacing(8)
        self.grid.addWidget(QLabel(band_legend([label for _lo, _hi, label in BANDS_S]), panels), 0, 0, 1, 2)
        for row, (local, local_label, remote, remote_label) in enumerate(ROWS, start=1):
            for column, (pair, template) in enumerate(((local, local_label), (remote, remote_label))):
                label = channels.title(template, LEMI423, {"hx": "r_hx", "hy": "r_hy"})
                plot = band_plot(panels, label)
                self.band_plots[pair] = plot
                self.labels[pair] = label
                self.templates[pair] = template
                self._add_cursor(pair, plot)
                self.grid.addWidget(plot, row, column)
            self.grid.setRowStretch(row, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        for column in (LOCAL_COLUMN, REMOTE_COLUMN):
            share_x_axis([self.band_plots[pair] for pair in column])
        link_x_ranges(list(self.band_plots.values()))  # one x range, copied, not pixel-linked

        self.time_label = QLabel("cursor: click any panel", self)
        self.show_button = QPushButton("Show in Time Series", self, enabled=False)
        self.show_button.clicked.connect(self.show_in_timeseries)
        cursor_row = QHBoxLayout()
        cursor_row.addWidget(self.time_label, 1)
        cursor_row.addWidget(self.show_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(controls)
        layout.addWidget(panels, 1)
        layout.addLayout(cursor_row)

        self.show_remote_column(False)
        store = self.state.segment_store
        store.qc_started.connect(self._started)
        store.qc_ready.connect(self.draw)
        store.qc_failed.connect(lambda m: self.title_label.setText(f"QC failed: {m}"))
        self.state.selection_changed.connect(self._selection_changed)
        # the remote can also be set elsewhere (State.set_remote); the combo
        # shows what the QC in view was computed against
        self.state.remote_changed.connect(lambda _r: self._fill_remotes())

    # ------------------------------------------------------------ controls

    def reload(self) -> None:
        """Clear the plots and refill the remotes after a survey change."""
        self.clear()
        self._fill_remotes()

    def _fill_remotes(self) -> None:
        """Fill the remote combo for the selected station, with `State.remote` selected."""
        station = self.state.selection[0] if self.state.selection else None
        self._filling = True
        try:
            self.remote_combo.clear()
            self.remote_combo.addItem("(none)", None)
            for display, name in self.state.remote_choices(station):
                self.remote_combo.addItem(display, name)
            index = self.remote_combo.findData(self.state.remote) if self.state.remote else 0
            self.remote_combo.setCurrentIndex(max(index, 0))
        finally:
            self._filling = False

    def _remote_picked(self, _index: int) -> None:
        """Pass a remote chosen in the combo to `State.set_remote`."""
        if not self._filling:
            self.state.set_remote(self.remote_combo.currentData())

    def _selection_changed(self, selection) -> None:
        """Refill the remotes, clearing the plots when nothing is selected."""
        self._fill_remotes()
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        """Show that a QC is running; the panels keep the previous result until it is replaced."""
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    # ------------------------------------------------------------- drawing

    def show_remote_column(self, on: bool) -> None:
        """Show or hide the remote column."""
        for pair in REMOTE_COLUMN:
            self.band_plots[pair].setVisible(on)

    def visible_pairs(self) -> list[tuple[str, str]]:
        """Return the pairs on the grid in row order: four without a remote, eight with.

        Uses `isHidden` rather than `isVisible`, since a tab that is not
        current is hidden with all its children; the result reflects the
        layout whichever tab is in front.
        """
        return [p for p in self.band_plots if not self.band_plots[p].isHidden()]

    def clear(self) -> None:
        """Clear every plot, hide the remote column and reset the labels."""
        self.qc = None
        for plot in self.band_plots.values():
            plot.clear()
        self._restore_cursors()
        self.show_remote_column(False)
        self.title_label.setText(PLACEHOLDER)
        self.time_label.setText("cursor: click any panel")
        self.show_button.setEnabled(False)

    def draw(self, qc) -> None:
        """Draw every pair's band lines, showing the remote column when the QC has a remote."""
        self.qc = qc
        self.show_remote_column(bool(qc.remote))
        span = qc.duration_s / S_PER_UNIT
        for pair, plot in self.band_plots.items():
            self.labels[pair] = channels.title(self.templates[pair], qc.roles, qc.remote_roles)
            plot.setLabel("left", self.labels[pair])
            actual = channels.resolve_pairs([pair], qc.roles, qc.remote_roles)
            if actual and actual[0] in qc.band_curves:
                curves = {label: (t / S_PER_UNIT, values)
                          for label, (t, values) in qc.band_curves[actual[0]].items()}
                draw_bands(plot, curves)
            else:
                plot.clear()
            lock_view(plot, x=(0.0, span), y=(0.0, 1.0))  # locked to the window
        for pair in (LOCAL_COLUMN[-1], REMOTE_COLUMN[-1]):  # the bottom row carries the time axis
            self.band_plots[pair].setLabel("bottom", time_label(qc.t0))
        self._restore_cursors()  # draw_bands clears the plot, cursor and all
        for cursor in self.cursors.values():
            cursor.setBounds([0.0, span])
        self.title_label.setText(f"{window_title(qc)}  -  band coherence")
        self._cursor_moved()

    # -------------------------------------------------------------- cursor

    def _add_cursor(self, pair, plot) -> None:
        """Add a draggable vertical cursor to a panel, linked to every other panel's."""
        cursor = pg.InfiniteLine(angle=90, movable=True, pen=CURSOR_PEN)
        cursor.setZValue(10)
        plot.addItem(cursor)
        cursor.sigPositionChanged.connect(lambda _c, p=pair: self._dragged(p))
        plot.scene().sigMouseClicked.connect(lambda event, w=plot: self._clicked(event, w))
        self.cursors[pair] = cursor

    def _restore_cursors(self) -> None:
        """Re-add the cursor lines after `PlotWidget.clear()` removed them."""
        for pair, plot in self.band_plots.items():
            if self.cursors[pair] not in plot.getPlotItem().items:
                plot.addItem(self.cursors[pair])

    def cursor_value(self) -> float:
        """Return the cursor position in minutes since the window's start."""
        return float(next(iter(self.cursors.values())).value())

    def cursor_time(self) -> pd.Timestamp | None:
        """Return the cursor's UTC time, or None with no QC drawn."""
        if self.qc is None:
            return None
        return self.qc.t0 + pd.Timedelta(microseconds=round(self.cursor_value() * S_PER_UNIT * 1e6))

    def set_cursor(self, minutes: float) -> None:
        """Move every panel's cursor to `minutes` since the window's start."""
        self._moving = True
        try:
            for cursor in self.cursors.values():
                cursor.setValue(float(minutes))
        finally:
            self._moving = False
        self._cursor_moved()

    def _dragged(self, pair) -> None:
        """Move every cursor to the one dragged."""
        if not self._moving:
            self.set_cursor(self.cursors[pair].value())

    def _clicked(self, event, plot) -> None:
        """Place the cursor at a left click on a panel."""
        if self.qc is None or event.button() != Qt.LeftButton:
            return
        self.set_cursor(plot.getViewBox().mapSceneToView(event.scenePos()).x())

    def _cursor_moved(self) -> None:
        """Update the cursor label and enable "Show in Time Series"."""
        when = self.cursor_time()
        if when is None:
            return
        self.time_label.setText(f"cursor: {when:%Y-%m-%d %H:%M:%S} UTC ({self.cursor_value():.1f} min)")
        self.show_button.setEnabled(True)

    def show_in_timeseries(self) -> None:
        """Emit `State.goto_time` with the cursor's time."""
        when = self.cursor_time()
        if when is not None:
            self.state.goto_time.emit(when)
