"""pyqtgraph helpers for the three QC tabs, and the ladder controls two of them share.

Drawing only -- the numbers are a `bbmt_gui.segment.SegmentQC`, computed by
`bbmt.timefreq` in the store's worker; the colours are `bbmt_gui.theme`'s:

- `draw_psd`       PSD ladders on one log-log plot, each stage over the
                   decade its resolution suits, as `scripts/psd_qc.py` draws
                   figure 05 (2-500 Hz from the 1000 Hz stage, 0.2-2 Hz from
                   the 100 Hz stage, and so on: `stage_bands`), the remote's
                   coil in grey underneath, the view locked to what was drawn
                   (y: below the anti-alias roll-off, `Y_EXTENT_HZ`) and
                   faint dashed lines at the Schumann resonances and at
                   50 Hz and its harmonics (`mark_frequencies`).
- `PeriodImage`    one plot holding a period-against-time image (a
                   spectrogram in dB) as a `PColorMeshItem` whose rows sit at
                   the true log-period bin edges -- the levels' bins are not
                   evenly spaced in log period -- with a colour bar the
                   student can drag to change the levels.
- `draw_bands`     the band lines of one pair against time, coherence 0-1,
                   plus the "All frequencies" curve: their mean, for display.
- `lock_view`      the view starts at an extent with no padding and can never
                   be panned or zoomed out past it (the Time Series rule).
- `LadderControls` the base window and step (`SegmentStore.win_s`,
                   `step_s`) as two spinboxes and a Recompute button; the
                   Spectrogram and Coherence tabs each show one and they
                   follow each other through `ladder_changed`.

Time is minutes since the window's start on the Spectrogram and Coherence
tabs (a QC window is 1-3 h); the Time Series tab keeps seconds.
"""

from __future__ import annotations

import warnings

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QWidget

from bbmt_gui import theme
from bbmt_gui.plots import AXIS_WIDTH

PLACEHOLDER = "load a window from the tree on the Time Series tab"
STAGE_LO = 0.002  # a stage is drawn from fs * STAGE_LO up to the stage above's low edge
# the PSD's y extent is taken inside this band -- psd_qc.py's YLIM_PCTL_HZ: the
# anti-alias roll-off above 400 Hz would drag the axis ~10 decades below any real data
Y_EXTENT_HZ = (0.003, 400.0)
BAND_COLOURS = theme.BAND_COLOURS
# colour-scale choices for the spectrogram (the MATLAB app's wide / robust / tight / full)
SCALES = {
    "robust (2-98 %)": (2.0, 98.0),
    "wide (1-99 %)": (1.0, 99.0),
    "tight (10-90 %)": (10.0, 90.0),
    "full": (0.0, 100.0),
}


def window_title(qc) -> str:
    """'D02  2021-06-29 12:55:49 to 14:55:49 UTC (2.00 h)  remote E08'."""
    end = qc.t0 + pd_timedelta(qc.duration_s)
    text = f"{qc.station}  {qc.t0:%Y-%m-%d %H:%M:%S} to {end:%H:%M:%S} UTC ({qc.duration_s / 3600:.2f} h)"
    text += f"  remote {qc.remote}" if qc.remote else "  no remote"
    return text + (f"  ({qc.note})" if getattr(qc, "note", "") else "")


def pd_timedelta(seconds: float):
    import pandas as pd

    return pd.Timedelta(microseconds=round(seconds * 1e6))


def time_label(t0) -> str:
    return f"minutes since {t0:%Y-%m-%d %H:%M:%S} UTC"


def lock_view(plot: pg.PlotWidget, x=None, y=None) -> None:
    """Show exactly (lo, hi) on each axis given, and never let the view pan or zoom out past it.

    In view coordinates: on a log axis that is log10 of the value, which is
    how pyqtgraph's ViewBox holds a log range.
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
    """(low, high) Hz drawn from each stage: `fs * STAGE_LO` up to the stage above's low edge."""
    bands, hi = [], None
    for fs, _freqs, _psd in stages:
        top = fs / 2.0 if hi is None else hi
        lo = fs * STAGE_LO
        bands.append((lo, top))
        hi = lo
    return bands


def psd_plot(parent, title: str) -> pg.PlotWidget:
    """An empty log-log PSD plot titled `title`, with a legend bottom left."""
    plot = pg.PlotWidget(parent=parent)
    plot.setLogMode(x=True, y=True)
    plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA * 0.7)
    plot.setTitle(title, color=theme.TEXT)
    plot.setLabel("left", "PSD (units²/Hz)")
    plot.setLabel("bottom", "frequency (Hz)")
    plot.getAxis("left").setWidth(AXIS_WIDTH)  # the two panels are x-linked by pixel
    for side in ("left", "bottom"):  # a log axis must not read "(x1e-06)"
        plot.getAxis(side).enableAutoSIPrefix(False)
    # bottom left: an MT PSD falls with frequency, so that corner is the emptiest
    plot.addLegend(offset=(10, -10), brush=pg.mkBrush(31, 31, 31, 210), labelTextColor=theme.TEXT)
    plot.setMinimumHeight(160)
    return plot


def draw_psd(plot: pg.PlotWidget, stages, curves, labelled: bool = False) -> int:
    """`curves` = [(comp, legend name), ...] on `plot`, stage by stage; returns the curves drawn.

    Each comp in its theme colour (a remote coil grey and underneath), named
    once in the legend. The view is then locked to the extent of what was
    drawn -- positive finite values only; in y only inside `Y_EXTENT_HZ` --
    and the frequency marks go on, their text labels only where `labelled`.
    """
    plot.clear()
    f_lo, f_hi, p_lo, p_hi = np.inf, -np.inf, np.inf, -np.inf
    drawn = 0
    for comp, name in curves:
        named = False
        for (_fs, freqs, psd), (lo, hi) in zip(stages, stage_bands(stages)):
            m = (freqs >= lo) & (freqs <= hi)
            if comp not in psd or not m.any():
                continue
            f, p = freqs[m], psd[comp][m]
            item = plot.plot(f, p, pen=theme.pen(comp, 1.2), name=None if named else name)
            item.setZValue(-1 if comp.startswith("r_") else 0)
            named, drawn = True, drawn + 1
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
    """Faint dashed lines at the Schumann resonances and at 50 Hz and its harmonics up to `nyquist`.

    The lines are named "Schumann" and "mains"; the first of each kind
    carries the text label when `labelled` (one label per tab, not per line).
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
    """Colour levels at `SCALES[scale]`'s percentiles of the finite image values."""
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo, hi = np.percentile(finite, SCALES[scale])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def _edges(centres: np.ndarray) -> np.ndarray:
    """Cell edges around `centres` (already in the axis's own coordinates), n + 1 of them."""
    c = np.asarray(centres, dtype=float)
    if c.size == 1:
        step = 1.0
        return np.array([c[0] - step / 2, c[0] + step / 2])
    mid = (c[1:] + c[:-1]) / 2.0
    return np.concatenate([[2 * c[0] - mid[0]], mid, [2 * c[-1] - mid[-1]]])


class PeriodImage:
    """A plot with one period-against-time image and its colour bar."""

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
        """Draw `image` (t x period) with cells at the true bin edges and `levels` as the colour range.

        `t` is in the plot's x unit and `span` is the window's length in it:
        the view is locked to [0, span] in x and to the period range in y.
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
        """Hide the image (a PColorMeshItem cannot be given no data)."""
        self.mesh.setVisible(False)
        self.drawn = False


# ------------------------------------------------------------ band curves


def band_plot(parent, title: str) -> pg.PlotWidget:
    plot = pg.PlotWidget(parent=parent)
    plot.setMinimumHeight(110)
    plot.setLabel("left", title)
    lock_view(plot, y=(0.0, 1.0))
    plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
    plot.getAxis("left").setWidth(64)
    return plot


def draw_bands(plot: pg.PlotWidget, curves: dict) -> int:
    """`curves[label] = (t, values)`, one line per band in `BAND_COLOURS` order; returns the lines drawn.

    Over them, thick and white, the "All frequencies" curve: the mean of the
    band lines at each time, drawn and thrown away (the bands of one pair
    share one time grid, `compute_segment_qc`'s).
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
    """Rich text naming each band in its line colour, then "All frequencies", for a label above the plots."""
    parts = [f'<span style="color:{BAND_COLOURS[k % len(BAND_COLOURS)]}"><b>&#9644;</b> {label}</span>'
             for k, label in enumerate(labels)]
    parts.append(f'<span style="color:{theme.ALL_FREQ_COLOUR}"><b>&#9644;&#9644;</b> '
                 f'{theme.ALL_FREQ_LABEL}</span>')
    return "bands: " + "&nbsp;&nbsp; ".join(parts)


def link_x_ranges(plots) -> None:
    """Keep every plot in `plots` on one x range, by plain copy.

    pyqtgraph's `setXLink` lines linked views up by screen pixel, which is
    right for a stack of equal-width plots and wrong for a grid of small
    plots beside one wide image (each gets a range shifted and stretched
    by its own width). Here a range change on any plot is copied to the
    others, guarded against re-entry.
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
    """Base window and step spinboxes plus Recompute, bound to the store's ladder."""

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
        self.state.segment_store.set_ladder(self.win_spin.value(), self.step_spin.value())
        self.state.request_qc()

    def _follow(self, win_s: float, step_s: float) -> None:
        self.win_spin.setValue(win_s)
        self.step_spin.setValue(step_s)
