# -*- coding: utf-8 -*-
"""
Filter preview views of the Filter Data tab

Draws a `crust.gui.filter_preview.PreviewResult`; the computation is done in
`crust.gui.filter_preview`.

* `SeriesPreview`: Bx, By, Ex, Ey stacked on one x axis
  (`plots.stack_plots`, gaps as holes, peak decimation), the raw trace light
  grey behind the filtered one in the channel colour. Zoom is locked to the
  window as on the Time Series tab: x only, clamped to the window's ends, y
  following the visible data. With no filters the raw trace is drawn alone
  in the channel colour. The series are offset-removed, the segment's
  convention, so raw and filtered traces line up after a high-pass.
* `PsdPreview`: the Spectra tab's two pair panels, "By-Ex (Zxy)" and "Bx-Ey
  (Zyx)", named for the window's recorder by `spectra.panel`. The raw PSD is
  dashed light grey under the filtered one (`qc_plots.draw_psd`'s `before`),
  with the Schumann and mains lines, and the view locked to the data.
* `PreviewPane`: a "Time series: Before / After / Both / Removed" choice, a
  "Show: Bx By Ex Ey" row for the loaded window's channels (applied to both
  views), the status line, and the two views in a vertical splitter.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QRadioButton, QSplitter, QVBoxLayout, QWidget,
)

from crust.gui import channels, theme
from crust.gui.plots import clear_layout, follow_visible_y, share_x_axis, stack_plots
from crust.gui.qc_plots import draw_psd, psd_plot
from crust.gui.tabs.spectra import PANELS, legend_name, panel

MIN_SPAN_SAMPLES = 20  # the narrowest x range, as on the Time Series tab
MODES = ("Before", "After", "Both", "Removed")  # Removed = raw minus filtered: what the filters took out


def _faint(pen):
    """Return the raw pen at 45 per cent opacity, for the raw trace behind a filtered one."""
    colour = pen.color()
    colour.setAlpha(115)
    pen.setColor(colour)
    return pen


def _with_gaps(a: np.ndarray, gaps) -> np.ndarray:
    """Return the array, or a float32 copy with NaN over the gaps so they draw as holes."""
    if not gaps:
        return a
    a = np.array(a, dtype="float32")
    for g0, g1 in gaps:
        a[g0:g1] = np.nan
    return a


class SeriesPreview(QWidget):
    """Bx, By, Ex, Ey stacked on one locked x axis, raw light grey behind filtered in colour.

    `mode` is "Before", "After", "Both" or "Removed"; `hidden` holds the
    channels switched off under "Show".
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.mode = "Both"  # "Before", "After", "Both" or "Removed"
        self.hidden: set[str] = set()
        self.clear()

    def clear(self) -> None:
        """Remove the plots and forget the segment."""
        clear_layout(self.layout())
        self.segment, self.filtered, self._x = None, False, None
        self.plots, self.raw_items, self.filtered_items, self.removed_items = {}, {}, {}, {}

    def show_result(self, result: PreviewResult) -> None:
        """Draw a preview, rebuilding the plots when the window changed."""
        if result.segment is not self.segment:
            self._build(result.segment)
        for comp, item in self.filtered_items.items():
            if result.filtered is None:
                item.clear()
                self.removed_items[comp].clear()
            else:
                item.setData(self._x, _with_gaps(result.filtered[comp], self.segment.gaps))
                # what the filters took out, in the channel colour: the mains sinusoid a
                # notch removes, the 12 s square wave a cp stack removes
                taken = self.segment.arrays[comp].astype("float64") - result.filtered[comp]
                self.removed_items[comp].setData(self._x, _with_gaps(taken, self.segment.gaps))
        self.filtered = result.filtered is not None
        self.restyle()

    def _build(self, seg) -> None:
        """Build one plot per channel of the window, with raw, filtered and removed curves."""
        self.clear()
        self.segment = seg
        comps = theme.channel_order(seg.arrays)
        self._x = np.arange(seg.n) / seg.sample_rate
        series = {c: _with_gaps(seg.arrays[c], seg.gaps) for c in comps}
        x_label = f"seconds since {seg.t0:%Y-%m-%d %H:%M:%S} UTC  (offset removed; nT from the scalar gain)"
        plots = stack_plots(self, comps, self._x, series, channels.unit, x_label)
        duration = seg.n / seg.sample_rate
        for comp, plot in zip(comps, plots):
            self.raw_items[comp] = plot.getPlotItem().listDataItems()[0]
            self.filtered_items[comp] = plot.plot(pen=theme.pen(comp), connect="finite")
            self.removed_items[comp] = plot.plot(pen=theme.pen(comp), connect="finite")
            box = plot.getViewBox()
            box.setMouseEnabled(x=True, y=False)
            box.setLimits(xMin=0.0, xMax=duration, maxXRange=duration,
                          minXRange=MIN_SPAN_SAMPLES / seg.sample_rate)
            follow_visible_y(plot)
            plot.setLabel("bottom", x_label)
            plot.setMinimumHeight(55)  # the splitter shares the height with the spectra
        plots[0].setXRange(0.0, duration, padding=0)
        self.plots = dict(zip(comps, plots))

    def restyle(self) -> None:
        """Set pens and visibility from the filters, the mode and the hidden channels."""
        for comp, plot in self.plots.items():
            raw, filtered, removed = self.raw_items[comp], self.filtered_items[comp], self.removed_items[comp]
            raw.setPen(_faint(theme.raw_pen()) if self.filtered else theme.pen(comp))
            raw.setZValue(-1)
            raw.setVisible(not self.filtered or self.mode in ("Before", "Both"))
            filtered.setVisible(self.filtered and self.mode in ("After", "Both"))
            removed.setVisible(self.filtered and self.mode == "Removed")
            # the y range follows the trace on show: the filtered one in After and
            # Both (so a large removed component such as mains runs off the panel
            # instead of setting the scale), the raw in Before, the removed in Removed
            box = plot.getViewBox()
            for item, follow in ((raw, not self.filtered or self.mode == "Before"),
                                 (filtered, self.mode in ("After", "Both")),
                                 (removed, self.mode == "Removed")):
                # pyqtgraph's auto-range reads `addedItems`; an item left out of
                # that list still draws but no longer sets the range
                listed = item in box.addedItems
                if follow and not listed:
                    box.addedItems.append(item)
                elif not follow and listed:
                    box.addedItems.remove(item)
            box.updateAutoRange()
            plot.setVisible(comp not in self.hidden)
        shown = [p for c, p in self.plots.items() if c not in self.hidden]
        share_x_axis(shown)
        for plot in self.plots.values():
            bottom = bool(shown) and plot is shown[-1]
            plot.getAxis("bottom").showLabel(bottom)
            plot.setMinimumHeight(85 if bottom else 55)  # the bottom one's x axis takes ~30 px of it


class PsdPreview(QWidget):
    """The two pair PSD panels, raw dashed light grey under the filtered, locked to the data.

    A hover cursor on every panel reads out the frequency, period and the
    visible channels' values below the panels.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hidden: set[str] = set()
        self.plots: dict[str, pg.PlotWidget] = {}
        self.items: dict[str, list] = {}  # panel title -> [(comp, item)]
        self.comps: dict[str, list] = {}  # panel title -> the window's channels on it
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.cursors: dict[str, pg.InfiniteLine] = {}
        for title, _comps in PANELS:
            plot = psd_plot(self, title)
            plot.setMinimumHeight(80)
            if self.plots:
                plot.setXLink(next(iter(self.plots.values())))
            self.plots[title] = plot
            layout.addWidget(plot)
            # a hover cursor on every panel: the pointer's frequency read out below
            cursor = pg.InfiniteLine(angle=90, movable=False, pen=theme.cursor_pen() if hasattr(theme, "cursor_pen") else pg.mkPen("#ffb74d", width=1))
            cursor.setZValue(20)
            cursor.hide()
            plot.addItem(cursor, ignoreBounds=True)
            self.cursors[title] = cursor
            plot.scene().sigMouseMoved.connect(lambda pos, t=title: self._hover(t, pos))
        self.readout = QLabel("move the pointer over a PSD panel to read the frequency", self)
        self.readout.setStyleSheet("font-size: 8pt")
        layout.addWidget(self.readout)

    def clear(self) -> None:
        """Clear the panels, keeping the hover cursors."""
        for title, plot in self.plots.items():
            plot.clear()
            plot.addItem(self.cursors[title], ignoreBounds=True)  # clear() took the cursor off too
            self.cursors[title].hide()
        self.items = {}

    def _hover(self, title: str, pos) -> None:
        """Move the cursors to the pointer's frequency and show the values under them."""
        plot = self.plots[title]
        if not plot.sceneBoundingRect().contains(pos):
            return
        point = plot.getViewBox().mapSceneToView(pos)
        freq = 10.0 ** point.x()  # log axes: the view coordinate is log10(Hz)
        if not np.isfinite(freq) or freq <= 0:
            return
        for cursor in self.cursors.values():
            cursor.setPos(point.x())
            cursor.show()
        parts = [f"f = {freq:.4g} Hz  (T = {1.0 / freq:.4g} s)"]
        seen: set[str] = set()
        for panel_title, entries in self.items.items():
            for comp, item in entries:
                if comp in seen or comp in self.hidden or not item.isVisible():
                    continue
                x, y = item.getOriginalDataset()
                if x is None or len(x) == 0 or freq < x[0] or freq > x[-1]:
                    continue  # another ladder stage of the same channel covers f
                value = 10.0 ** np.interp(np.log10(freq), np.log10(x), np.log10(np.maximum(y, 1e-300)))
                parts.append(f"{theme.label(comp) if hasattr(theme, 'label') else comp} {value:.3g}")
                seen.add(comp)
        self.readout.setText("   ".join(parts))

    def show_result(self, result: PreviewResult) -> None:
        """Draw the raw and filtered ladders on the two pair panels."""
        names = SimpleNamespace(remote=None, scalar_only=result.segment.scalar_only)
        local = channels.roles(result.segment.arrays)
        for k, (title, _pair) in enumerate(PANELS):
            shown, comps = panel(title, local)
            self.plots[title].setTitle(shown, color=theme.TEXT)
            self.comps[title] = comps
            curves = [(c, legend_name(c, names)) for c in comps]
            if result.filtered_stages:
                self.items[title] = draw_psd(self.plots[title], result.filtered_stages, curves,
                                             labelled=(k == 0), before=result.raw_stages)
            else:
                self.items[title] = draw_psd(self.plots[title], result.raw_stages, curves, labelled=(k == 0))
        self.restyle()

    def restyle(self) -> None:
        """Hide the hidden channels and any panel left with none shown."""
        shown = [self.plots[t] for t, _p in PANELS if any(c not in self.hidden for c in self.comps.get(t, ()))]
        for title, _pair in PANELS:
            self.plots[title].setVisible(self.plots[title] in shown)
            for comp, item in self.items.get(title, []):
                item.setVisible(comp not in self.hidden)
        share_x_axis(shown)
        for plot in self.plots.values():
            plot.getAxis("bottom").showLabel(bool(shown) and plot is shown[-1])


class PreviewPane(QWidget):
    """The options row, the status line and the two views, top to bottom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = SeriesPreview(self)
        self.spectra = PsdPreview(self)
        self.status_label = QLabel("", self, wordWrap=True)
        self.mode_group = QButtonGroup(self)
        options = QHBoxLayout()
        options.addWidget(QLabel("Time series:", self))
        for name in MODES:
            button = QRadioButton(name, self, checked=(name == self.series.mode))
            self.mode_group.addButton(button)
            options.addWidget(button)
        self.mode_group.buttonToggled.connect(lambda button, on: on and self.set_mode(button.text()))
        options.addSpacing(24)
        options.addWidget(QLabel("Show:", self))
        self.box_row = QHBoxLayout()
        options.addLayout(self.box_row)
        self.channel_boxes = {}
        self.set_channels(("hx", "hy", "ex", "ey"))  # until a window is loaded
        options.addStretch(1)
        options.addWidget(QLabel(f'<span style="color:{theme.RAW_COLOUR}">raw: light grey (dashed on the '
                                 f'spectra)</span> &nbsp; filtered: the channel colour', self))
        top = QWidget(self)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addLayout(options)
        top_layout.addWidget(self.status_label)
        top_layout.addWidget(self.series, 1)
        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.addWidget(top)
        self.splitter.addWidget(self.spectra)
        self.splitter.setSizes([310, 230])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

    def set_channels(self, comps) -> None:
        """Build one "Show" box per channel of the loaded window, in stack order."""
        comps = theme.channel_order(comps)
        if list(self.channel_boxes) == comps:
            return
        clear_layout(self.box_row)
        self.channel_boxes = {}
        for comp in comps:
            box = QCheckBox(theme.label(comp), self, checked=comp not in self.series.hidden)
            box.toggled.connect(lambda on, c=comp: self.show_channel(c, on))
            self.channel_boxes[comp] = box
            self.box_row.addWidget(box)

    def show_result(self, result) -> None:
        """Draw a preview in both views and show its provenance and compute time."""
        self.set_channels(result.segment.arrays)
        self.series.show_result(result)
        self.spectra.show_result(result)
        done = "; ".join(result.provenance) if result.filters else "no filters: the window as recorded"
        self.status_label.setText(f"{done}  ({result.elapsed_s:.1f} s)")

    def clear(self) -> None:
        """Clear both views and the status line."""
        self.series.clear()
        self.spectra.clear()
        self.status_label.setText("")

    def set_mode(self, mode: str) -> None:
        """Set the time-series mode: Before (raw), After (filtered), Both, or Removed (raw minus filtered)."""
        self.series.mode = mode
        self.series.restyle()

    def show_channel(self, comp: str, on: bool) -> None:
        """Show or hide a channel in both views."""
        for view in (self.series, self.spectra):
            (view.hidden.discard if on else view.hidden.add)(comp)
            view.restyle()
