"""Coherence tab: is there signal in the loaded window, and does the remote see the same field?

The live view of the window picked on the Time Series tab: on `qc_ready`
the `SegmentQC.band_curves` -- `mtproc.timefreq.band_from_levels` over
`BANDS_S`, the lines of `scripts/site_qc.py`'s figure 02 -- are drawn as one
small plot per pair on a grid of **two aligned columns** (`ROWS`), named as
the MATLAB app names them:

    By-Ex (Zxy)         rBy-Ex (Zxy, remote)   the two impedance pairs,
    Bx-Ey (Zyx)         rBx-Ey (Zyx, remote)   local beside remote
    Bx-By (magnetic)    Bx-rBx                 then the two coil checks
    Ex-Ey (electric)    By-rBy

The names are the parts channels play (`mtproc_gui.channels.roles`), so on a
LEMI-424 the rows read "By-E1 (Zxy)", "Bx-E2 (Zyx)", ..., "E1-E2 (electric)";
the panels stay keyed by the LEMI-423 pairs of `ROWS`.

Each row puts a local pair beside the remote question that goes with it, so
a low coherence on the left is read against the coil check on the right. With
no remote in, the right column is hidden and the four local pairs fill the
tab. Each column is one stack on one time axis -- no gap between the rows,
tick labels on the bottom row only -- and every plot is kept on one x range
(`qc_plots.link_x_ranges`), in minutes since the window's start, locked to
the window and to coherence 0-1 (`qc_plots.lock_view`). Over each pair's
band lines is a thick white "All frequencies" curve, their mean, drawn only.

There is no coherogram here: the band curves are already coherence against
time over the same 1-3 h window, and the image only repeated them at a
resolution the eye could not use.

Controls: the **remote** the QC is computed against (`State.remote`, preset
to the station's declared `remote:`; changing it asks the store again), the
ladder's base window and step with Recompute, and a **cursor** -- a vertical
line on every panel at once: click any panel to place it, drag it on any
panel, the label gives its UTC time, and "Show in Time Series" puts the Time
Series view +-5 minutes around it (`State.goto_time`).

Nothing is computed here, and nothing is produced: the whole-record figures
02 and 03 still come from `site_qc.py`, run from the Process tab.
"""

from __future__ import annotations

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from mtproc.timefreq import BANDS_S
from mtproc_gui import channels, theme
from mtproc_gui.plots import share_x_axis
from mtproc_gui.qc_plots import (
    PLACEHOLDER, LadderControls, band_legend, band_plot, draw_bands, link_x_ranges,
    lock_view, time_label, window_title,
)

# (local pair, its label, remote pair, its label) -- one row of the grid, in
# the LEMI-423 names standing for each part (`channels.title` names them for
# the loaded record). An r names the remote's coil, so "rBx-Ey (Zyx, remote)"
# is this site's Ey against the REMOTE's Bx.
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
    """Band-coherence lines for eight pairs on two aligned columns, one shared cursor."""

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

        # the grid: local pairs down the left, the remote question that goes
        # with each one beside it. Every panel carries the same cursor.
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
        # the remote can also be set from elsewhere (State.set_remote); keep the
        # combo saying what the QC in view was actually computed against
        self.state.remote_changed.connect(lambda _r: self._fill_remotes())

    # ------------------------------------------------------------ controls

    def reload(self) -> None:
        self.clear()
        self._fill_remotes()

    def _fill_remotes(self) -> None:
        """The remotes for the selected station, `State.remote` preselected."""
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
        if not self._filling:
            self.state.set_remote(self.remote_combo.currentData())

    def _selection_changed(self, selection) -> None:
        self._fill_remotes()
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        # the panels in view stay until the new result replaces them: picking
        # a remote must not blank the coherence in view
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    # ------------------------------------------------------------- drawing

    def show_remote_column(self, on: bool) -> None:
        """The right column is there only when a remote is in."""
        for pair in REMOTE_COLUMN:
            self.band_plots[pair].setVisible(on)

    def visible_pairs(self) -> list[tuple[str, str]]:
        """The pairs on the grid, in row order (four without a remote, eight with).

        `isHidden`, not `isVisible`: a tab that is not the current one is
        hidden with everything on it, and the question here is what the layout
        holds, not which tab is in front.
        """
        return [p for p in self.band_plots if not self.band_plots[p].isHidden()]

    def clear(self) -> None:
        self.qc = None
        for plot in self.band_plots.values():
            plot.clear()
        self._restore_cursors()
        self.show_remote_column(False)
        self.title_label.setText(PLACEHOLDER)
        self.time_label.setText("cursor: click any panel")
        self.show_button.setEnabled(False)

    def draw(self, qc) -> None:
        """Every pair's band lines; the right column only when the QC has a remote."""
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
            lock_view(plot, x=(0.0, span), y=(0.0, 1.0))  # tight on the window, never zoomed out past it
        for pair in (LOCAL_COLUMN[-1], REMOTE_COLUMN[-1]):  # the bottom row carries the time axis
            self.band_plots[pair].setLabel("bottom", time_label(qc.t0))
        self._restore_cursors()  # draw_bands clears the plot, cursor and all
        for cursor in self.cursors.values():
            cursor.setBounds([0.0, span])
        self.title_label.setText(f"{window_title(qc)}  -  band coherence")
        self._cursor_moved()

    # -------------------------------------------------------------- cursor

    def _add_cursor(self, pair, plot) -> None:
        """One draggable vertical line on this panel, moving with every other."""
        cursor = pg.InfiniteLine(angle=90, movable=True, pen=CURSOR_PEN)
        cursor.setZValue(10)
        plot.addItem(cursor)
        cursor.sigPositionChanged.connect(lambda _c, p=pair: self._dragged(p))
        plot.scene().sigMouseClicked.connect(lambda event, w=plot: self._clicked(event, w))
        self.cursors[pair] = cursor

    def _restore_cursors(self) -> None:
        """Put the cursor lines back after a `PlotWidget.clear()` took them off."""
        for pair, plot in self.band_plots.items():
            if self.cursors[pair] not in plot.getPlotItem().items:
                plot.addItem(self.cursors[pair])

    def cursor_value(self) -> float:
        """Minutes since the window's start (every panel's cursor is on the same value)."""
        return float(next(iter(self.cursors.values())).value())

    def cursor_time(self) -> pd.Timestamp | None:
        if self.qc is None:
            return None
        return self.qc.t0 + pd.Timedelta(microseconds=round(self.cursor_value() * S_PER_UNIT * 1e6))

    def set_cursor(self, minutes: float) -> None:
        """Put every panel's cursor on `minutes` since the window's start."""
        self._moving = True
        try:
            for cursor in self.cursors.values():
                cursor.setValue(float(minutes))
        finally:
            self._moving = False
        self._cursor_moved()

    def _dragged(self, pair) -> None:
        if not self._moving:
            self.set_cursor(self.cursors[pair].value())

    def _clicked(self, event, plot) -> None:
        if self.qc is None or event.button() != Qt.LeftButton:
            return
        self.set_cursor(plot.getViewBox().mapSceneToView(event.scenePos()).x())

    def _cursor_moved(self) -> None:
        when = self.cursor_time()
        if when is None:
            return
        self.time_label.setText(f"cursor: {when:%Y-%m-%d %H:%M:%S} UTC ({self.cursor_value():.1f} min)")
        self.show_button.setEnabled(True)

    def show_in_timeseries(self) -> None:
        when = self.cursor_time()
        if when is not None:
            self.state.goto_time.emit(when)
