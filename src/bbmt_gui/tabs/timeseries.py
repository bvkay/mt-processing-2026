"""Time Series tab: pick a window of a site from the tree, see it in full.

The MATLAB App Designer app's Time Series tab, which the students know: a
tree on the left of every site in the metadata, and under an archived site
its windows (`bbmt_gui.site_tree`, 2 h at 1000 Hz, 4 h at 500 Hz -- see
`bbmt_gui.windows`). Clicking a window makes it `State.selection`, which asks
the `SegmentStore` for it; the store hands the local `Segment` over as soon
as it is read (`segment_loaded`, about a second for 2 h of D02) and this tab
draws it at the full sample rate on the right, one x-linked pyqtgraph plot
per channel in the physical units of `scripts/site_qc.py`'s figure 01 with
the offset the segment removed added back, gaps as holes, while the store
goes on to the remote and the QC that the Spectra, Spectrogram and Coherence
tabs draw. Clicking a window of another site loads that one instead.

The plots are the MATLAB app's stack: Bx, By, Ex, Ey top to bottom,
magnetics blue and electrics red (`bbmt_gui.theme`), no gap between them,
one shared x axis whose tick labels are on the bottom plot only, and the
vertical grid only.

The x axis is seconds since the window's start (the UTC start is in the
label). Wheel-zoom and drag along x only, never outside the window and never
narrower than 20 samples; each y axis follows whatever is visible, at the
whole window and at every zoom (the noise envelope at 2 h, single samples
when zoomed in). The **processing
window** is the visible range: zoom to the stretch you want and "Use
visible range as processing window" sends its UTC start and end to the
Process tab, and on to `scripts/process_rr.py` -- how the MATLAB app did it.
`State.goto_time` brings the view to +-5 minutes around a moment another
tab points at, inside the loaded window. Nothing is computed here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from bbmt.timefreq import UNIT
from bbmt_gui import theme
from bbmt_gui.plots import clear_layout, follow_visible_y, stack_plots
from bbmt_gui.site_tree import SiteTree

WINDOW_FMT = "%Y-%m-%d %H:%M"
MIN_SPAN_SAMPLES = 20  # the narrowest x range the student can zoom to
GOTO_HALF_SPAN_S = 5 * 60.0  # `goto_time` shows this much either side
PICK_HINT = "pick a site in the tree, then one of its windows"


class TimeSeriesTab(QWidget):
    """Tree of sites and windows on the left; the loaded window's channels on the right."""

    processing_window_selected = Signal(str, str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.segment = None  # the Segment on screen
        self.plots: list[pg.PlotWidget] = []
        self.comps: list[str] = []
        self._display: dict[str, np.ndarray] = {}  # what the curves show, per channel

        self.tree = SiteTree(state, self)
        self.tree.window_clicked.connect(self.state.set_selection)

        self.progress = QProgressBar(self, maximumWidth=260, visible=False)
        self.hint_label = QLabel(PICK_HINT, self, wordWrap=True)
        self.use_button = QPushButton("Use visible range as processing window", self, enabled=False)
        self.use_button.clicked.connect(self.use_as_processing_window)
        top = QHBoxLayout()
        top.addWidget(self.use_button)
        top.addWidget(self.progress)
        top.addWidget(self.hint_label, 1)

        self.plot_box = QWidget(self)
        QVBoxLayout(self.plot_box).setContentsMargins(0, 0, 0, 0)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(top)
        right_layout.addWidget(self.plot_box, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        store = self.state.segment_store
        store.qc_started.connect(self._on_started)
        store.qc_progress.connect(self._on_progress)
        store.segment_loaded.connect(self._on_segment)
        store.qc_ready.connect(lambda _qc: self.progress.setVisible(False))
        store.qc_failed.connect(self._on_failed)
        self.state.selection_changed.connect(self._selection_changed)
        self.state.site_changed.connect(self.tree.select_site)
        self.state.goto_time.connect(self.goto_time)

    # --------------------------------------------------------- the tree

    def reload(self) -> None:
        """A survey was opened: list its sites, show nothing."""
        self.tree.reload()
        self.clear_plots()
        self.hint_label.setText(PICK_HINT if self.state.survey is not None else "")

    def wait_for_read(self) -> None:
        self.tree.wait_for_read()

    # ------------------------------------------------------ the loading

    def _selection_changed(self, selection) -> None:
        if selection is None:
            self.clear_plots()
        elif self.segment is None or not self._matches(self.segment):
            self.clear_plots()  # the old window goes as soon as another is asked for
            station, start, end = selection
            self.hint_label.setText(f"loading {station} {start:%Y-%m-%d %H:%M} to {end:%H:%M} UTC...")

    def _matches(self, segment) -> bool:
        """Is `segment` the selected station over the selected window (to half a sample)?"""
        selection = self.state.selection
        if selection is None or segment.station != selection[0]:
            return False
        tol = 0.5 / segment.sample_rate
        return (abs((segment.t0 - selection[1]).total_seconds()) <= tol
                and abs((segment.end - selection[2]).total_seconds()) <= tol)

    def _on_started(self, what: str) -> None:
        self.progress.setRange(0, 0)  # busy: the load reports no percentage
        self.progress.setFormat(f"loading {what}")
        self.progress.setVisible(True)

    def _on_progress(self, percent: int, message: str) -> None:
        if percent > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.progress.setFormat(f"QC: {message} %p%")

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.hint_label.setText(f"could not load the window: {message}")

    def _on_segment(self, segment) -> None:
        """The store read the local segment: draw it if it is still the selection."""
        if not self._matches(segment):
            return
        self.draw(segment)

    # ------------------------------------------------------- the plots

    def clear_plots(self) -> None:
        self.segment = None
        self.plots, self.comps, self._display = [], [], {}
        clear_layout(self.plot_box.layout())
        self.use_button.setEnabled(False)

    def draw(self, segment) -> None:
        """The segment's channels at the full rate, offsets back, gaps as holes."""
        self.clear_plots()
        self.segment = segment
        self.comps = [c for c in theme.CHANNEL_ORDER if c in segment.arrays]
        fs, n = segment.sample_rate, segment.n
        x = np.arange(n) / fs  # seconds since the window start, shared by the four curves
        for comp in self.comps:
            y = segment.arrays[comp].astype("float64")
            y += segment.offsets[comp]
            for a, b in segment.gaps:
                y[a:b] = np.nan
            self._display[comp] = y
        self.plots = stack_plots(
            self.plot_box, self.comps, x, self._display,
            lambda comp: UNIT.get(comp, "") + (", scalar gain" if comp in segment.scalar_only else ""),
            f"seconds since {segment.t0:%Y-%m-%d %H:%M:%S} UTC",
        )
        duration = n / fs
        for comp, plot in zip(self.comps, self.plots):
            box = plot.getViewBox()
            box.setMouseEnabled(x=True, y=False)
            box.setLimits(xMin=0.0, xMax=duration, maxXRange=duration, minXRange=MIN_SPAN_SAMPLES / fs)
            follow_visible_y(plot)  # y fits what is on screen, at the whole window and at every zoom
        self.plots[0].setXRange(0.0, duration, padding=0)
        self.use_button.setEnabled(True)
        gaps = f", {len(segment.gaps)} gap(s)" if segment.gaps else ""
        self.hint_label.setText(
            f"{segment.station}: {segment.t0:%Y-%m-%d %H:%M:%S} to {segment.end:%H:%M:%S} UTC "
            f"({duration / 3600:.2f} h at {fs:g} Hz, {n:,} samples per channel{gaps})"
        )

    def visible_seconds(self) -> tuple[float, float]:
        """The x range on screen, seconds since the window start."""
        return tuple(float(v) for v in self.plots[0].getViewBox().viewRange()[0])

    # ---------------------------------------------------- the windows

    def goto_time(self, when) -> None:
        """Show +-5 minutes around a UTC time, clipped to the loaded window."""
        if self.segment is None or not self.plots:
            return
        when = pd.Timestamp(when)
        if when.tzinfo is None:
            when = when.tz_localize("UTC")
        centre = (when - self.segment.t0).total_seconds()
        lo = max(0.0, centre - GOTO_HALF_SPAN_S)
        hi = min(self.segment.duration_s, centre + GOTO_HALF_SPAN_S)
        if hi > lo:
            self.plots[0].setXRange(lo, hi, padding=0)

    def use_as_processing_window(self) -> None:
        """Push the visible x range to the Process tab as `start`/`end` for process_rr.py."""
        if self.segment is None or not self.plots:
            return
        lo, hi = self.visible_seconds()
        start = self.segment.t0 + pd.Timedelta(microseconds=round(lo * 1e6))
        end = self.segment.t0 + pd.Timedelta(microseconds=round(hi * 1e6))
        self.processing_window_selected.emit(start.strftime(WINDOW_FMT), end.strftime(WINDOW_FMT))
