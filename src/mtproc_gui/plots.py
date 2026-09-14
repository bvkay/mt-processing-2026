"""pyqtgraph helpers for the Time Series tab: a stack of x-linked channel plots.

One plot per channel, stacked top to bottom with no gap between them, x
axes linked so panning one pans all of them, and only the bottom plot showing
the x tick values and label (`share_x_axis`) -- the MATLAB app's look, with
its colours from `mtproc_gui.theme`: magnetics blue, electrics red, vertical
grid only. The curves get pyqtgraph's automatic peak (per-pixel min/max)
decimation and clipping to the view, so a 2 h window at 1000 Hz (7.2 M
points a channel) still pans and zooms smoothly.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QWidget

from mtproc_gui import theme

AXIS_WIDTH = 72  # px, every left axis in a stack: see `stack_plots`


def clear_layout(layout) -> None:
    """Remove and delete every widget in a layout (redrawing a stack)."""
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def follow_visible_y(plot: pg.PlotWidget) -> None:
    """Let the y range follow whatever is visible (recomputed on every pan and zoom)."""
    plot.setAutoVisible(y=True)
    plot.enableAutoRange(axis="y")


def share_x_axis(plots) -> None:
    """A stack reads as one x axis: tick values on the bottom plot only.

    The upper plots keep their bottom axis -- it draws the vertical grid and
    the inward ticks -- but without values it takes no height, so the plots
    meet with no gap.
    """
    for k, plot in enumerate(plots):
        plot.getAxis("bottom").setStyle(showValues=(k == len(plots) - 1))


def stack_plots(box: QWidget, comps, x, series, unit_of, x_label: str) -> list[pg.PlotWidget]:
    """One x-linked PlotWidget per channel in `box`, top to bottom, no gaps.

    `unit_of(comp)` supplies the axis unit; the axis reads "Bx (nT, ...)".
    Every left axis is `AXIS_WIDTH` wide instead of sized to its own tick
    text: pyqtgraph lines linked views up by screen pixel, so axes of
    different widths gave the panels different x ranges (a pixel was 1.3 s
    apart between E and H at a 10-minute view). 72 px holds the widest tick
    text seen (30 px) plus the tick offsets and the rotated label. Peak
    decimation and clipping to the view are on; the grid is vertical only.
    """
    layout = box.layout()
    clear_layout(layout)
    layout.setSpacing(0)
    plots: list[pg.PlotWidget] = []
    for comp in comps:
        plot = pg.PlotWidget(parent=box)
        plot.setMinimumHeight(110)
        plot.showGrid(x=True, y=False, alpha=theme.GRID_ALPHA)
        plot.setLabel("left", f"{theme.label(comp)} ({unit_of(comp)})")
        plot.getAxis("left").setWidth(AXIS_WIDTH)
        for side in ("left", "bottom"):  # ticks stay in the stated unit, no "(x0.001)"
            plot.getAxis(side).enableAutoSIPrefix(False)
        plot.setDownsampling(auto=True, mode="peak")  # per-pixel min/max: the noise envelope, as MATLAB plot() showed it
        plot.setClipToView(True)
        plot.plot(x, series[comp], pen=theme.pen(comp), connect="finite")
        if plots:
            plot.setXLink(plots[0])
        plots.append(plot)
        layout.addWidget(plot)
    if plots:
        share_x_axis(plots)
        plots[-1].setLabel("bottom", x_label)
    return plots
