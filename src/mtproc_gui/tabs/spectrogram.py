"""Spectrogram tab: the loaded window's power against period and time, per channel.

The live view of the window picked on the Time Series tab: on `qc_ready` the
`SegmentQC.spectrograms` -- `mtproc.timefreq.cascade`'s power levels stitched
onto the base time grid by `levels_to_grid` and turned to dB by `power_db`,
the same functions `scripts/site_qc.py` draws figure 04 with -- are drawn as
four period-against-time images, Bx, By, Ex, Ey top to bottom, stacked
with no gap on one x axis in minutes since the window's start (tick labels
on the bottom one only), the view locked to the window and the period range
(`qc_plots.lock_view`). The MATLAB app's controls are
here: the colour scale (robust 2-98 %, the figure's default; wide; tight;
full) and "relative to median", which shows each period's dB above or below
its median over the window, so a noisy stretch stands out as a bright band.
The base window and step of the ladder (120 s stepped by 30 s to start) are
the spinboxes; Recompute asks the store again with the new values.

Nothing is computed here beyond the picture's colour limits and, for the
relative view, the row median that is subtracted for display. What to read
off the images is not written on the tab: that goes in the students' PDF.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from mtproc_gui import theme
from mtproc_gui.plots import clear_layout, share_x_axis
from mtproc_gui.qc_plots import (
    PLACEHOLDER, SCALES, LadderControls, PeriodImage, percentile_levels, time_label, window_title,
)

PANELS = ("hx", "hy", "ex", "ey")  # until a window is loaded; then its own channels, magnetics first


class SpectrogramTab(QWidget):
    """One x-linked dB image per channel of the loaded window (four on a LEMI-423), redrawn on `qc_ready`."""

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
        """One image per channel in `comps`, stacked on one x axis (kept when the channels are the same)."""
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
        self.clear()

    def clear(self) -> None:
        self.qc = None
        for image in self.images.values():
            image.clear()
        self.title_label.setText(PLACEHOLDER)

    def _selection_changed(self, selection) -> None:
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        # keep what is in view until the new result replaces it (a remote
        # change must not blank the tab)
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    def draw(self, qc) -> None:
        self.qc = qc
        self.redraw()

    def redraw(self) -> None:
        """The four images at the chosen colour scale, absolute or relative to the row median."""
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
            # x in minutes (a picture's unit), the view locked to the whole window
            image.set(t_s / 60.0, periods, db, percentile_levels(db, scale), qc.duration_s / 60.0)
        list(self.images.values())[-1].plot.setLabel("bottom", time_label(qc.t0))
        mode = "dB relative to each period's median" if relative else "power density, dB"
        self.title_label.setText(f"{window_title(qc)}  -  {mode}, colour scale {scale}")
