# -*- coding: utf-8 -*-
"""
Stacked channel plots

pyqtgraph helpers for a stack of x-linked channel plots, used by the Time
Series tab and the filter preview. One plot per channel is stacked top to
bottom with no gap, the x axes are linked so panning one pans all, and only
the bottom plot shows the x tick values and label (`share_x_axis`). This
stack takes its colours and grid from `mtproc_gui.theme`:
magnetics blue, electrics red, vertical grid only. Curves use pyqtgraph's
automatic peak (per-pixel min/max) decimation and clipping to the view, so a
2 h window at 1000 Hz (7.2 M points per channel) pans and zooms smoothly.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QWidget

from mtproc_gui import theme

AXIS_WIDTH = 72  # px, every left axis in a stack: see `stack_plots`


def clear_layout(layout) -> None:
    """Remove and delete every widget in a layout."""
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def follow_visible_y(plot: pg.PlotWidget) -> None:
    """Make the y range follow the visible data, recomputed on every pan and zoom."""
    plot.setAutoVisible(y=True)
    plot.enableAutoRange(axis="y")


def share_x_axis(plots) -> None:
    """Show x tick values on the bottom plot of a stack only.

    The upper plots keep their bottom axis, which draws the vertical grid and
    the inward ticks; without values it takes no height, so the plots meet
    with no gap.

    Args:
        plots: The plots of the stack, top to bottom.
    """
    for k, plot in enumerate(plots):
        plot.getAxis("bottom").setStyle(showValues=(k == len(plots) - 1))


def stack_plots(box: QWidget, comps, x, series, unit_of, x_label: str) -> list[pg.PlotWidget]:
    """Build one x-linked PlotWidget per channel in `box`, top to bottom, with no gaps.

    Every left axis is `AXIS_WIDTH` wide rather than sized to its own tick
    text. pyqtgraph aligns linked views by screen pixel, so axes of different
    widths give the panels different x ranges (1.3 s between E and H at a
    10-minute view). 72 px holds the widest tick text seen (30 px) plus the
    tick offsets and the rotated label. Peak decimation and clipping to the
    view are on; the grid is vertical only.

    Args:
        box (QWidget): Widget whose layout receives the plots; cleared first.
        comps: Channel names, top to bottom.
        x: Shared x values.
        series (dict): Channel name to y values.
        unit_of: Callable giving a channel's unit; the axis reads "Bx (nT, ...)".
        x_label (str): Label of the bottom plot's x axis.

    Returns:
        list[pg.PlotWidget]: The plots, top to bottom.
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
        plot.setDownsampling(auto=True, mode="peak")  # per-pixel min/max: the same noise envelope as drawing every sample
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
