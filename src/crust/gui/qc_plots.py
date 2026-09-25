# -*- coding: utf-8 -*-
"""
Plot helpers for the QC tabs

pyqtgraph helpers for the Spectra, Spectrogram and Coherence tabs, and the
ladder controls shared by the last two. The values drawn come from a
`crust.gui.segment.SegmentQC`, computed by `crust.timefreq` in the segment
store's worker; colours come from `crust.gui.theme`.

* `draw_psd`: PSD ladders on one log-log plot, each stage over the decade
  its resolution suits, as `scripts/psd_qc.py` draws figure 05 (2-500 Hz from
  the 1000 Hz stage, 0.2-2 Hz from the 100 Hz stage, and so on;
  `stage_bands`). A remote coil is drawn grey underneath and an optional
  "before" ladder dashed light grey beneath everything. The view is locked
  to what was drawn, with the y extent taken below the anti-alias roll-off
  (`Y_EXTENT_HZ`), and faint dashed lines mark the Schumann resonances and
  50 Hz and its harmonics (`mark_frequencies`).
* `PeriodImage`: one plot holding a period-against-time image (a spectrogram
  in dB) as a `PColorMeshItem` whose rows sit at the true log-period bin
  edges, since the ladder's bins are not evenly spaced in log period. The
  colour bar can be dragged to change the levels.
* `draw_bands`: the band lines of one pair against time, coherence 0-1, plus
  the "All frequencies" curve, their mean.
* `lock_view`: sets the view to an extent with no padding and prevents
  panning or zooming out past it, as on the Time Series tab.
* `LadderControls`: the base window and step (`SegmentStore.win_s`,
  `step_s`) as two spin boxes and a Recompute button. The Spectrogram and
  Coherence tabs each show one; they stay in step through
  `ladder_changed`.

Time on the Spectrogram and Coherence tabs is in minutes since the window's
start (a QC window is 1-3 h); the Time Series tab uses seconds.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import warnings

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QWidget

from crust.gui import theme
from crust.gui.plots import AXIS_WIDTH

PLACEHOLDER = "load a window from the tree on the Time Series tab"
STAGE_LO = 0.002  # a stage is drawn from fs * STAGE_LO up to the stage above's low edge
# the PSD's y extent is taken inside this band, as psd_qc.py's YLIM_PCTL_HZ; the
# anti-alias roll-off above 400 Hz would drag the axis ~10 decades below the data
Y_EXTENT_HZ = (0.003, 400.0)
BAND_COLOURS = theme.BAND_COLOURS
# colour-scale choices for the spectrogram: (low, high) percentile clips
SCALES = {
    "robust (2-98 %)": (2.0, 98.0),
    "wide (1-99 %)": (1.0, 99.0),
    "tight (10-90 %)": (10.0, 90.0),
    "full": (0.0, 100.0),
}


def window_title(qc) -> str:
    """Return a QC window's title, e.g. 'S01  2021-06-29 12:55:49 to 14:55:49 UTC (2.00 h)  remote S02'."""
    end = qc.t0 + pd_timedelta(qc.duration_s)
    text = f"{qc.station}  {qc.t0:%Y-%m-%d %H:%M:%S} to {end:%H:%M:%S} UTC ({qc.duration_s / 3600:.2f} h)"
    text += f"  remote {qc.remote}" if qc.remote else "  no remote"
    return text + (f"  ({qc.note})" if getattr(qc, "note", "") else "")


def pd_timedelta(seconds: float):
    """Return `seconds` as a pandas Timedelta rounded to the microsecond."""
    import pandas as pd

    return pd.Timedelta(microseconds=round(seconds * 1e6))


def time_label(t0) -> str:
    """Return the x-axis label "minutes since <t0> UTC"."""
    return f"minutes since {t0:%Y-%m-%d %H:%M:%S} UTC"


def lock_view(plot: pg.PlotWidget, x=None, y=None) -> None:
    """Show exactly (lo, hi) on each given axis and prevent panning or zooming out past it.

    Ranges are in view coordinates; on a log axis that is log10 of the value,
    as pyqtgraph's ViewBox holds a log range.

    Args:
        plot (pg.PlotWidget): The plot.
        x (tuple[float, float] | None): x range, or None to leave x free.
        y (tuple[float, float] | None): y range, or None to leave y free.
    """
    limits = {}
    if x is not None:
        limits.update(xMin=x[0], xMax=x[1], maxXRange=x[1] - x[0])
    if y is not None:
        limits.update(yMin=y[0], yMax=y[1], maxYRange=y[1] - y[0])
    box = plot.getViewBox()
    box.setLimits(**limits)
    box.setRange(xRange=x, yRange=y, padding=0)


# ------------------------------------------------------------------ PSD ladder


def stage_bands(stages) -> list[tuple[float, float]]:
    """Return the (low, high) Hz band drawn from each stage.

    Each stage covers `fs * STAGE_LO` up to the low edge of the stage above;
    the first stage reaches its Nyquist frequency.
    """
    bands, hi = [], None
    for fs, _freqs, _psd in stages:
        top = fs / 2.0 if hi is None else hi
        lo = fs * STAGE_LO
        bands.append((lo, top))
        hi = lo
    return bands


def psd_plot(parent, title: str) -> pg.PlotWidget:
    """Return an empty log-log PSD plot titled `title`, with a legend bottom left."""
    plot = pg.PlotWidget(parent=parent)
    plot.setLogMode(x=True, y=True)
    plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA * 0.7)
    plot.setTitle(title, color=theme.TEXT)
    plot.setLabel("left", "PSD (units²/Hz)")
    plot.setLabel("bottom", "frequency (Hz)")
    plot.getAxis("left").setWidth(AXIS_WIDTH)  # the two panels are x-linked by pixel
    for side in ("left", "bottom"):  # no SI prefix such as "(x1e-06)" on a log axis
        plot.getAxis(side).enableAutoSIPrefix(False)
    # bottom left: an MT PSD falls with frequency, so that corner is the emptiest
    plot.addLegend(offset=(10, -10), brush=pg.mkBrush(31, 31, 31, 210), labelTextColor=theme.TEXT)
    plot.setMinimumHeight(160)
    return plot


def draw_psd(plot: pg.PlotWidget, stages, curves, labelled: bool = False, before=None) -> list:
    """Draw PSD ladders on `plot`, stage by stage.

    Each channel is drawn in its theme colour (a remote coil grey and
    underneath) and named once in the legend. `before`, a second ladder of
    the same channels such as the Filter Data tab's raw window, is drawn
    beneath everything, dashed light grey and left out of the legend. The
    view is locked to the extent of the positive finite values drawn, with
    the y extent taken inside `Y_EXTENT_HZ`, and the frequency marks are
    added.

    Args:
        plot (pg.PlotWidget): The plot; cleared first.
        stages: PSD ladder as (fs, freqs, {channel: PSD}) per stage.
        curves: (channel, legend name) pairs to draw.
        labelled (bool): Label the frequency marks.
        before: Optional second ladder drawn underneath.

    Returns:
        list: (channel, curve item) for every curve drawn.
    """
    plot.clear()
    f_lo, f_hi, p_lo, p_hi = np.inf, -np.inf, np.inf, -np.inf
    drawn = []
    for ladder, raw in ([(before, True)] if before else []) + [(stages, False)]:
        for comp, name in curves:
            named = False
            for (_fs, freqs, psd), (lo, hi) in zip(ladder, stage_bands(ladder)):
                m = (freqs >= lo) & (freqs <= hi)
                if comp not in psd or not m.any():
                    continue
                f, p = freqs[m], psd[comp][m]
                pen = theme.raw_pen(1.0, dashed=True) if raw else theme.pen(comp, 1.2)
                item = plot.plot(f, p, pen=pen, name=None if named or raw else name)
                item.setZValue(-2 if raw else -1 if comp.startswith("r_") else 0)
                named = True
                drawn.append((comp, item))
                ok = np.isfinite(p) & (p > 0)
                if ok.any():
                    f_lo, f_hi = min(f_lo, f[ok].min()), max(f_hi, f[ok].max())
                ok &= (f >= Y_EXTENT_HZ[0]) & (f <= Y_EXTENT_HZ[1])
                if ok.any():
                    p_lo, p_hi = min(p_lo, p[ok].min()), max(p_hi, p[ok].max())
    if drawn and np.isfinite([f_lo, f_hi, p_lo, p_hi]).all():
        lock_view(plot, x=(float(np.log10(f_lo)), float(np.log10(f_hi))),
                  y=(float(np.log10(p_lo)), float(np.log10(p_hi))))
        mark_frequencies(plot, stages[0][0] / 2.0, labelled)
    return drawn


def mark_frequencies(plot: pg.PlotWidget, nyquist: float, labelled: bool) -> None:
    """Add faint dashed lines at the Schumann resonances and at 50 Hz and its harmonics up to `nyquist`.

    The lines are named "Schumann" and "mains". When `labelled`, the first
    line of each kind carries a text label.
    """
    mains = [theme.MAINS_HZ * k for k in range(1, int(nyquist // theme.MAINS_HZ) + 1)]
    groups = (("Schumann", theme.SCHUMANN_COLOUR, "Schumann", theme.SCHUMANN_HZ),
              ("mains", theme.MAINS_COLOUR, "50 Hz + harmonics", mains))
    for name, colour, text, freqs in groups:
        for k, f in enumerate(freqs):
            opts = {}
            if labelled and k == 0:
                opts = {"label": text,
                        "labelOpts": {"position": 0.02, "color": colour, "anchors": [(0, 1), (0, 1)]}}
            line = pg.InfiniteLine(float(np.log10(f)), angle=90, pen=theme.mark_pen(colour),
                                   movable=False, name=name, **opts)
            plot.addItem(line, ignoreBounds=True)


# ------------------------------------------------------- period-time images


def percentile_levels(image: np.ndarray, scale: str) -> tuple[float, float]:
    """Return colour levels at the `SCALES[scale]` percentiles of the finite image values."""
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo, hi = np.percentile(finite, SCALES[scale])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def _edges(centres: np.ndarray) -> np.ndarray:
    """Return the n + 1 cell edges around `centres`, given in the axis's own coordinates."""
    c = np.asarray(centres, dtype=float)
    if c.size == 1:
        step = 1.0
        return np.array([c[0] - step / 2, c[0] + step / 2])
    mid = (c[1:] + c[:-1]) / 2.0
    return np.concatenate([[2 * c[0] - mid[0]], mid, [2 * c[-1] - mid[-1]]])


class PeriodImage:
    """A plot with one period-against-time image and its colour bar.

    Args:
        parent (QWidget): Parent of the plot.
        title (str): Prefix of the y-axis label "<title> period (s)".
        bar_label (str): Colour bar label.
        cmap (str): pyqtgraph colour map name.
        limits: Colour bar limits, or None.
        rounding (float): Colour bar level rounding.
    """

    def __init__(self, parent, title: str, bar_label: str, cmap: str = "viridis",
                 limits=None, rounding: float = 0.1):
        self.plot = pg.PlotWidget(parent=parent)
        self.plot.setMinimumHeight(150)
        self.plot.setLabel("left", f"{title} period (s)")
        self.plot.getAxis("left").setLogMode(True)  # ticks read 10^k; the mesh sits at log10(period)
        self.plot.getAxis("left").setWidth(64)
        self.mesh = pg.PColorMeshItem(colorMap=pg.colormap.get(cmap), enableAutoLevels=False)
        self.plot.addItem(self.mesh)
        self.bar = pg.ColorBarItem(
            values=(0.0, 1.0), colorMap=pg.colormap.get(cmap), label=bar_label,
            limits=limits, rounding=rounding, interactive=True,
        )
        self.bar.setImageItem(self.mesh, insert_in=self.plot.getPlotItem())
        self.drawn = False

    def set(self, t, periods, image, levels, span: float) -> None:
        """Draw an image with cells at the true bin edges.

        The view is locked to [0, span] in x and to the period range in y.

        Args:
            t: Cell centres in the plot's x unit.
            periods: Period of each row in seconds.
            image: Values shaped (time, period).
            levels (tuple[float, float]): Colour range.
            span (float): Window length in the x unit.
        """
        x_edges = _edges(t)
        y_edges = _edges(np.log10(periods))
        xm, ym = np.meshgrid(x_edges, y_edges, indexing="ij")
        self.mesh.setData(xm, ym, np.asarray(image, dtype=float))
        self.mesh.setVisible(True)
        self.bar.setLevels(levels)
        lock_view(self.plot, x=(0.0, float(span)), y=(float(y_edges.min()), float(y_edges.max())))
        self.drawn = True

    def clear(self) -> None:
        """Hide the image; a PColorMeshItem cannot be set to no data."""
        self.mesh.setVisible(False)
        self.drawn = False


# ------------------------------------------------------------ band curves


def band_plot(parent, title: str) -> pg.PlotWidget:
    """Return an empty band plot with y locked to 0-1."""
    plot = pg.PlotWidget(parent=parent)
    plot.setMinimumHeight(110)
    plot.setLabel("left", title)
    lock_view(plot, y=(0.0, 1.0))
    plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
    plot.getAxis("left").setWidth(64)
    return plot


def draw_bands(plot: pg.PlotWidget, curves: dict) -> int:
    """Draw one line per band, then the "All frequencies" mean over them.

    The mean is the band lines' mean at each time, drawn thick and white;
    the bands of one pair share the time grid of `compute_segment_qc`.

    Args:
        plot (pg.PlotWidget): The plot; cleared first.
        curves (dict): Band label to (t, values), drawn in `BAND_COLOURS` order.

    Returns:
        int: The number of band lines drawn.
    """
    plot.clear()
    drawn, rows, t = 0, [], None
    for k, (label, (t, values)) in enumerate(curves.items()):
        pen = pg.mkPen(BAND_COLOURS[k % len(BAND_COLOURS)], width=1.2)
        plot.plot(t, values, pen=pen, connect="finite", name=label)
        rows.append(np.asarray(values, dtype=float))
        drawn += 1
    if rows:
        with warnings.catch_warnings():  # a time where every band is NaN stays NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(np.vstack(rows), axis=0)
        plot.plot(t, mean, pen=pg.mkPen(theme.ALL_FREQ_COLOUR, width=theme.ALL_FREQ_WIDTH),
                  connect="finite", name=theme.ALL_FREQ_LABEL)
    return drawn


def band_legend(labels) -> str:
    """Return rich text naming each band in its line colour, then "All frequencies"."""
    parts = [f'<span style="color:{BAND_COLOURS[k % len(BAND_COLOURS)]}"><b>&#9644;</b> {label}</span>'
             for k, label in enumerate(labels)]
    parts.append(f'<span style="color:{theme.ALL_FREQ_COLOUR}"><b>&#9644;&#9644;</b> '
                 f'{theme.ALL_FREQ_LABEL}</span>')
    return "bands: " + "&nbsp;&nbsp; ".join(parts)


def link_x_ranges(plots) -> None:
    """Keep every plot in `plots` on one x range by copying range changes.

    pyqtgraph's `setXLink` aligns linked views by screen pixel, which suits a
    stack of equal-width plots but shifts and stretches the range of plots of
    different widths, such as small plots beside one wide image. Here a
    range change on any plot is copied to the others, guarded against
    re-entry.
    """
    busy = [False]

    def follow(source):
        def _slot(_box, rng):
            if busy[0]:
                return
            busy[0] = True
            try:
                for plot in plots:
                    if plot is not source:
                        plot.setXRange(*rng, padding=0)
            finally:
                busy[0] = False
        return _slot

    for plot in plots:
        plot.getViewBox().sigXRangeChanged.connect(follow(plot))


# ------------------------------------------------------ the ladder controls


class LadderControls(QWidget):
    """Base window and step spin boxes plus Recompute, bound to the segment store's ladder.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        store = state.segment_store
        self.win_spin = QDoubleSpinBox(self, minimum=10.0, maximum=1800.0, singleStep=10.0,
                                       decimals=0, suffix=" s", value=store.win_s)
        self.win_spin.setToolTip("base window of the coherence and power ladder (seconds)")
        self.step_spin = QDoubleSpinBox(self, minimum=5.0, maximum=900.0, singleStep=5.0,
                                        decimals=0, suffix=" s", value=store.step_s)
        self.step_spin.setToolTip("step between windows at the base level (seconds)")
        self.button = QPushButton("Recompute", self)
        self.button.clicked.connect(self.recompute)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Window", self))
        layout.addWidget(self.win_spin)
        layout.addWidget(QLabel("Step", self))
        layout.addWidget(self.step_spin)
        layout.addWidget(self.button)
        store.ladder_changed.connect(self._follow)

    def recompute(self) -> None:
        """Set the store's ladder from the spin boxes and request the QC again."""
        self.state.segment_store.set_ladder(self.win_spin.value(), self.step_spin.value())
        self.state.request_qc()

    def _follow(self, win_s: float, step_s: float) -> None:
        """Show the store's ladder after a change from another tab."""
        self.win_spin.setValue(win_s)
        self.step_spin.setValue(step_s)
