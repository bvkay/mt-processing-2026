# -*- coding: utf-8 -*-
"""
Spectrogram tab

Shows the loaded window's power against period and time for each channel.
On `qc_ready` the tab draws `SegmentQC.spectrograms` (the power levels of
`mtproc.timefreq.cascade`, placed on the base time grid by `levels_to_grid`
and converted to dB by `power_db`, the functions `scripts/site_qc.py` uses
for figure 04) for the window chosen on the Time Series tab. There is one
period-against-time image per local channel, Bx, By, Ex, Ey top to bottom
on a LEMI-423, stacked with no gap on one x axis in minutes since the
window's start (tick labels on the bottom image only), with the view locked
to the window and the period range (`qc_plots.lock_view`).

The controls are the colour scale (robust 2-98 %, the
figure's default; wide; tight; full) and "relative to median", which shows
each period's dB relative to its median over the window, so a noisy stretch
stands out as a bright band. The spin boxes set the ladder's base window and
step (120 s and 30 s initially); Recompute requests the QC with the new
values. The tab computes only the colour limits and, for the relative view,
the row median subtracted for display.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from mtproc_gui import theme
from mtproc_gui.plots import clear_layout, share_x_axis
from mtproc_gui.qc_plots import (
    PLACEHOLDER, SCALES, LadderControls, PeriodImage, percentile_levels, time_label, window_title,
)

PANELS = ("hx", "hy", "ex", "ey")  # before a window is loaded; then its own channels, magnetics first


class SpectrogramTab(QWidget):
    """One x-linked dB image per channel of the loaded window (four on a LEMI-423), redrawn on `qc_ready`.

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.qc = None

        self.title_label = QLabel(PLACEHOLDER, self)
        self.title_label.setStyleSheet("font-weight: bold")
        self.scale_combo = QComboBox(self)
        for name in SCALES:
            self.scale_combo.addItem(name, name)
        self.scale_combo.currentIndexChanged.connect(lambda _i: self.redraw())
        self.relative_check = QCheckBox("relative to median (dB above each period's median)", self)
        self.relative_check.toggled.connect(lambda _on: self.redraw())
        self.ladder = LadderControls(state, self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Colour scale", self))
        controls.addWidget(self.scale_combo)
        controls.addWidget(self.relative_check)
        controls.addStretch(1)
        controls.addWidget(self.ladder)

        self.images: dict[str, PeriodImage] = {}
        panels = self.panels = QVBoxLayout()
        panels.setContentsMargins(0, 0, 0, 0)
        panels.setSpacing(0)
        self._build(PANELS)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(controls)
        layout.addLayout(panels, 1)

        store = self.state.segment_store
        store.qc_started.connect(self._started)
        store.qc_ready.connect(self.draw)
        store.qc_failed.connect(lambda m: self.title_label.setText(f"QC failed: {m}"))
        self.state.selection_changed.connect(self._selection_changed)

    def _build(self, comps) -> None:
        """Build one image per channel in `comps` on one x axis; unchanged if the channels are the same."""
        if list(self.images) == list(comps):
            return
        clear_layout(self.panels)
        self.images = {}
        for comp in comps:
            image = PeriodImage(self, theme.label(comp), "dB", rounding=0.1)
            if self.images:
                image.plot.setXLink(next(iter(self.images.values())).plot)
            self.images[comp] = image
            self.panels.addWidget(image.plot)
        share_x_axis([image.plot for image in self.images.values()])

    def reload(self) -> None:
        """Clear the images after a survey change."""
        self.clear()

    def clear(self) -> None:
        """Clear the images and the title."""
        self.qc = None
        for image in self.images.values():
            image.clear()
        self.title_label.setText(PLACEHOLDER)

    def _selection_changed(self, selection) -> None:
        """Clear the images when nothing is selected."""
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        """Show that a QC is running; the images keep the previous result until it is replaced."""
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    def draw(self, qc) -> None:
        """Keep a new QC result and redraw."""
        self.qc = qc
        self.redraw()

    def redraw(self) -> None:
        """Draw the images at the chosen colour scale, absolute or relative to each period's median."""
        qc = self.qc
        if qc is None:
            return
        scale = self.scale_combo.currentData()
        relative = self.relative_check.isChecked()
        self._build(theme.channel_order(qc.spectrograms) or PANELS)  # the local channels; r_ ones are not drawn
        for comp, image in self.images.items():
            if comp not in qc.spectrograms:
                image.clear()
                continue
            t_s, periods, db = qc.spectrograms[comp]
            if relative:
                with np.errstate(all="ignore"):
                    db = db - np.nanmedian(db, axis=0, keepdims=True)
            # x in minutes, the view locked to the whole window
            image.set(t_s / 60.0, periods, db, percentile_levels(db, scale), qc.duration_s / 60.0)
        list(self.images.values())[-1].plot.setLabel("bottom", time_label(qc.t0))
        mode = "dB relative to each period's median" if relative else "power density, dB"
        self.title_label.setText(f"{window_title(qc)}  -  {mode}, colour scale {scale}")
