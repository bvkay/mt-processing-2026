# -*- coding: utf-8 -*-
"""
Cross-powers tab

A cross-power viewer and mask editor for the processed data of one site: the
remote-reference impedances of the site against a remote, chunk by chunk and
band by band, on a time panel and a polar plane, over all the windows of a
span at once, with the time masks declared from them. `CrossPowerTab`
computes a window's STFT windows once (`crust.crosspower.compute_windows`)
and regroups them (`crust.crosspower.bin_windows`) for every chunk length
and every window inside the computed one; the masks are saved per site in
`<survey>/masks.yaml` (`crust.masks.save_masks`) and act in processing and
in `crust.crosspower.stack_impedance`.

The module also holds the helpers the tab uses: `processing_source` (the
archive processing reads for a site), `ElidedLabel` (a one-line label that
elides to its width), `SelectBox` (a ViewBox whose left-drag selects) and
the text helpers `span_text` and `duration_text`.

How it works

The window combo lists the whole overlap of the site and the remote (the
default), the Process tab's processing window while one is set for the
site, and the site's 2 h QC windows, following the one loaded in the tree.
Compute runs `compute_windows` in a `ReadThread` under `State.archive_lock`
on the archives processing reads, and the tab keeps the store, keyed on the
pair, the window and the two archives. A new chunk length, or a window of
the shown pair inside a kept store, is regrouped from the store at once,
with no archive read; a window regrouped from a larger store is rounded out
to whole minutes, and the title and the status line give the span drawn. A
window no store covers is computed when it belongs to the stored pair and
otherwise waits for Compute. A compute that returns after another window
was picked is drawn over it when its store covers it, and dropped
otherwise; one of another pair than the one shown is kept aside and drawn
when that pair is shown again.

The band is drawn on its own level's grid (`band_view`): one estimate per
base chunk at the levels whose windows fit it, one per m base chunks at a
deeper level (`level_multiples`), none where one such chunk is longer than
the window. The time panel shows log10 |Z|, phase (each mode's angle),
coherence and log10 |H| and |E| against time, with a bar over each chunk of
several base chunks; the polar plane shows (log10 |Z|, phase) per mode,
the yx phase plus 180 deg, wrapped to (-180, 180]
(`crust.crosspower.mode_phase`, the convention of scripts/cluster_masks.py),
so the Earth's phases of both modes lie in 0-90 deg and a near-field
source's yx phases near 0 deg, clear of the +/-180 deg edges. A chunk is
filled when no mask applying to the band touches it, lighter when a mask
takes some of its kept windows and hollow when one takes them all
(`masked_chunks`).

A left-drag selects chunks on the level it was made on, by the spots
drawn inside the rubber band (on the yx polar panel, by the phase plus
180 deg drawn there). "Mask selected" adds one mask per run of selected
chunks: all bands from the time panel with "all bands" ticked (offered
at a band shown per base chunk), else the band's [pmin, pmax]. "Unmask
selected" cuts the chunks out of the masks
applying to the band, the all-band ones only at a level shown per base
chunk. Masks are declared per site, whatever the remote; Save masks writes
the site's block of masks.yaml and a change of site reloads it. A new mask
is written with scope local (`crust.masks`): it applies when the site is
the local of a pair, and the pairs that use the site as a remote keep its
windows; an entry set to scope both in masks.yaml keeps that scope. In
processing an all-band mask is a time cut and a band mask drops the
windows it overlaps in its bands (`MASK_ROUTE`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph import Point
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGraphicsRectItem, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from crust.bands import build_band_scheme
from crust.crosspower import (
    BIN_S, CHUNKS_S, band_table, band_view, bin_windows, compute_windows, level_multiples, masked_chunks,
    mode_phase,
)
from crust.masks import applies, iso, load_masks, normalise, save_masks, utc
from crust.survey import distance_km
from crust.gui import theme
from crust.gui.archive import load_grid
from crust.gui.plots import share_x_axis
from crust.gui.reader import ReadThread
from crust.gui.site_map import PairSummary
from crust.gui.window_bar import WindowBar, overlap
from crust.gui.windows import window_label, window_list

XY_COLOUR, YX_COLOUR = theme.B_COLOUR, theme.E_COLOUR  # as mtpy draws xy and yx on View EDIs
POLAR_PHASE = {"xy": "phase (deg)", "yx": "phase yx + 180 (deg)"}  # the polar panels' left labels (`mode_phase`)
WORKERS = 4
DEFAULT_PERIOD_S = 0.05
SIZE, SELECTED_SIZE = 8, 12
SMALL_SIZE, MANY = 5, 300  # the spot size past MANY spots
PARTLY_TINT = 0.55  # a partly masked chunk's fill: its colour taken this far towards white (opaque)
COLUMNS = ("start (UTC)", "end (UTC)", "bands (s)", "reason", "found by")
REASON = 3
OVERLAP, PROCESSING, QC = "overlap", "processing", "qc"  # the window choices, in the combo's order
# a store by the kind of window it was computed for, as the status line names it
STORE_NAMES = {OVERLAP: "the overlap store", PROCESSING: "the processing window's store", QC: "the QC window's store"}
MASK_ROUTE = "all-band masks: time cuts; band masks: their windows dropped in those bands (aurora patch)"
ALL_BANDS_TIP = ("ticked: a time-panel mask is a time cut, every band left out (bands: all); unticked: it "
                 "covers the shown band only, like a polar-panel mask")
MASKS_TIP = ("this site's masks (its block of <survey>/masks.yaml): declared per site, they apply whichever remote "
             "it is processed with; new masks are scope local, applied when this site is the local of a pair, and "
             "a mask set to scope both in masks.yaml applies when it is the remote too (Process tab, \"apply "
             "masks.yaml\", on by default)")


def span_text(start, end, seconds: bool = False) -> str:
    """Return a span as text, '<start> to <end> UTC (<hours> h)'.

    Args:
        start: The span's start (anything `crust.masks.utc` takes).
        end: The span's end.
        seconds (bool): Times to the second ('%Y-%m-%d %H:%M:%S') rather than
            the minute.

    Returns:
        str: The text.
    """
    hours = (utc(end) - utc(start)).total_seconds() / 3600.0
    fmt = "%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M"
    return f"{utc(start).strftime(fmt)} to {utc(end).strftime(fmt)} UTC ({hours:.1f} h)"


def lighter(colour) -> QColor:
    """Return `colour` taken `PARTLY_TINT` of the way towards white, opaque: a partly masked chunk's fill."""
    c = QColor(colour)
    tint = lambda v: round(v + PARTLY_TINT * (255 - v))  # noqa: E731
    return QColor(tint(c.red()), tint(c.green()), tint(c.blue()))


def duration_text(seconds: float) -> str:
    """Return a chunk's length as text: '<m> min' (3 significant digits) under 2 h, '<h> h' from there."""
    minutes = float(seconds) / 60.0
    return f"{minutes:.3g} min" if minutes < 120.0 else f"{minutes / 60.0:.1f} h"


def _windows_for(path, survey_name: str, station: str):
    """Return the QC windows of `station` in the archive at `path` (`window_list`)."""
    return window_list(load_grid(path, survey_name, station))


def processing_source(survey, site: str, raw: Path) -> tuple[Path, str]:
    """Return the archive processing reads for `site`, and a note.

    The raw `<site>.h5` when the site declares no filters (or is a stack);
    its filtered variant `<site>_f<hash>.h5` when `crust.ingest.variant_ready`
    says it is built for the current declaration; otherwise the raw archive,
    noted "raw archive (filtered variant not built)". A missing variant stays
    missing (`crust.ingest.processing_archive` is the call that builds one).
    Opens archives read-only, so it runs in the compute's thread, under the
    archive lock.

    Args:
        survey: The open `crust.survey.Survey`.
        site (str): The site.
        raw (Path): The site's raw archive.

    Returns:
        tuple: (archive path, note); the note is empty when there is nothing
        to say.
    """
    try:
        from crust.ingest import archive_filter_kinds, variant_path, variant_ready
    except ImportError:  # a library from before the raw / variant split
        return raw, ""
    if site not in survey.site_names() or not survey.site(site).filters:
        baked = archive_filter_kinds(raw)
        return raw, f"old-layout archive, filters baked in: {baked}" if baked else ""
    if variant_ready(survey, site):
        return variant_path(survey, site), ""
    return raw, "raw archive (filtered variant not built)"


def _compute(survey, site, raw_local, remote, raw_remote, start, end, scheme, progress=None):
    """Run `compute_windows` on the archives processing reads (`processing_source`).

    Runs in the compute's `ReadThread`, with `WORKERS` threads.

    Returns:
        tuple: (store, (local archive name, remote archive name), notes).
    """
    (local, local_note), (far, far_note) = (processing_source(survey, site, raw_local),
                                            processing_source(survey, remote, raw_remote))
    store = compute_windows(local, site, far, remote, start, end, scheme, workers=WORKERS, progress=progress)
    notes = "; ".join(f"{n}: {t}" for n, t in ((site, local_note), (remote, far_note)) if t)
    return store, (Path(local).name, Path(far).name), notes


class ElidedLabel(QLabel):
    """A one-line label that elides its text at the right to the width the layout gives it.

    `text()` is the whole text, which is also the tooltip. Its minimum width
    is `min_width` whatever the text, so the window keeps its width under a
    long line; its preferred width is the whole text's unless `stretchy`
    (then it takes what the layout leaves it and prefers nothing).

    Args:
        parent (QWidget | None): Qt parent.
        min_width (int): The minimum width, px.
        stretchy (bool): Take the room the layout leaves instead of the text's width.
    """

    def __init__(self, parent=None, min_width: int = 40, stretchy: bool = False):
        super().__init__(parent)
        self._full, self._min, self._stretchy = "", int(min_width), stretchy
        self.setSizePolicy(QSizePolicy.Ignored if stretchy else QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumWidth(self._min)

    def setText(self, text) -> None:  # noqa: N802 (Qt's name)
        """Set the whole text, which is also the tooltip, and show it elided."""
        self._full = "" if text is None else str(text)
        self.setToolTip(self._full)
        self._elide()
        self.updateGeometry()

    def text(self) -> str:
        """Return the whole text."""
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Return `min_width` by the label's own minimum height."""
        return QSize(self._min, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        """Return the whole text's width (`min_width` when stretchy) by the label's own height."""
        margins = self.contentsMargins()
        width = self._min if self._stretchy else (self.fontMetrics().horizontalAdvance(self._full)
                                                  + margins.left() + margins.right() + 4)
        return QSize(max(self._min, width), super().sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Elide the text again at the new width."""
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        """Show the whole text elided at the right to the label's contents width."""
        room = max(0, self.contentsRect().width())
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, Qt.ElideRight, room))


class SelectBox(pg.ViewBox):
    """A ViewBox whose left-drag draws a rubber band and emits it (view coordinates) on release."""

    selected = Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.band = QGraphicsRectItem()
        self.band.setPen(pg.mkPen(theme.CURSOR_COLOUR, width=1, style=Qt.DashLine))
        fill = QColor(theme.CURSOR_COLOUR)
        fill.setAlpha(40)
        self.band.setBrush(pg.mkBrush(fill))
        self.band.setZValue(1e9)
        self.band.hide()
        self.addItem(self.band, ignoreBounds=True)

    def mouseDragEvent(self, ev, axis=None):
        """Draw the rubber band while the left button drags and emit `selected` on release; pass other drags on."""
        if ev.button() != Qt.LeftButton or axis is not None:
            return super().mouseDragEvent(ev, axis)
        ev.accept()
        rect = self.childGroup.mapRectFromParent(
            QRectF(Point(ev.buttonDownPos(ev.button())), Point(ev.pos()))).normalized()
        if ev.isFinish():
            self.band.hide()
            self.selected.emit(rect)
        else:
            self.band.setRect(rect)
            self.band.show()


class CrossPowerTab(QWidget):
    """RR impedances of one site per chunk on a time panel and a polar plane, and the masks declared from them.

    The controls are the site (archived sites), the remote (archived sites
    whose recorded span overlaps the site's, preset to the site's declared
    `remote:`, else `site_map.PairSummary.recommendation`), the window, the
    band, the base chunk (10, 5, 2 or 1 min) and Compute. Under them, at the
    tab's full width, the status line: one line elided at the right, the
    whole text in its tooltip, what just happened first. The band combo lists
    every band of the survey's band scheme by period; its arrows, or PgUp /
    PgDn anywhere in the tab, step one band, and the label after them names
    the band, its period, its level and its grid. Below the plots are the
    mask buttons, the count of masked chunks on the shown band's grid and the
    site's masks (the reason cell editable). How it works, in the module
    docstring, describes the windows, the compute, the drawing and the masks.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.scheme: dict | None = None
        self.result: dict | None = None  # `bin_windows` of the store, plus tag, archives, notes, range, kind
        self.store = None  # the `compute_windows` store the drawing came from, else the last of the shown pair
        self.store_key: tuple | None = None  # (site, remote, kind, start, end, local archive, remote archive)
        self.store_info: dict = {}  # its archive names and notes
        self.spare: tuple | None = None  # (store, key, info) of a pair not shown when its compute returned
        self.computes = 0  # computes started (a regroup starts none)
        self.masks: list[dict] = []
        self.dirty = False
        self.selected: set[int] = set()  # chunk indices on the grid of level `selected_level`
        self.selected_on = "time"  # or "polar xy" / "polar yx"
        self.selected_level: int | None = None
        self.all_bands_wanted = False  # the "all bands" box as last set while it was on; shown unticked while off
        self._windows: dict[str, list] = {}
        self._wanted: str | None = None  # a site whose windows are to be read
        self._pending = None  # a compute asked for, waiting for the archive
        self._thread: ReadThread | None = None
        self._hand_remote: str | None = None  # the site whose remote was picked by hand
        # plot -> [(item, x, y (view coordinates), chunk index per spot, colour)]
        self.items: dict[pg.PlotWidget, list] = {}
        self.spans = WindowBar(state, self)  # hidden: the recorded spans, read as the Process tab reads them
        self.spans.hide()
        self.spans.spans_changed.connect(self._fill_remotes)

        self.site_combo = QComboBox(self, minimumWidth=90)
        self.remote_combo = QComboBox(self, minimumWidth=110, toolTip="archived sites overlapping the site")
        self.window_combo = QComboBox(self, minimumWidth=330, toolTip=(
            "whole overlap of site and remote (default), the Process tab's processing window "
            "when one is set for this site, or one 2 h QC window; a window inside the computed one "
            "is regrouped from the stored windows without reading, one outside it is computed"))
        self.band_combo = QComboBox(self, minimumWidth=150, toolTip=(
            "the band shown; '(20 min chunks)': its level is shown on chunks of several base chunks; "
            "'(no chunk)': one chunk of its level is longer than the window"))
        self.prev_band = QToolButton(self, arrowType=Qt.LeftArrow, toolTip="previous band (PgUp)")
        self.next_band = QToolButton(self, arrowType=Qt.RightArrow, toolTip="next band (PgDn)")
        self.band_label = ElidedLabel(self, min_width=0)  # the band shown and its grid, elided to the room left
        self.chunk_combo = QComboBox(self, toolTip=(
            "base chunk: one impedance per chunk and band at the levels whose windows fit it; a deeper level "
            "is shown on chunks of several base chunks (the band label says how many and how long); "
            "a change regroups the stored windows, no archive read"))
        for seconds in CHUNKS_S:
            self.chunk_combo.addItem(f"{seconds / 60:g} min", seconds)
        self.compute_button = QPushButton("Compute", self, toolTip=(
            "compute_windows over the window, 4 threads: reads the two archives once and keeps every STFT "
            "window's band sums; chunk lengths and windows inside it are then regrouped without reading"))
        self.status = ElidedLabel(self, min_width=0, stretchy=True)
        self.site_combo.currentIndexChanged.connect(lambda _i: self._site_changed())
        self.remote_combo.activated.connect(lambda _i: setattr(self, "_hand_remote", self.site()))
        self.remote_combo.currentIndexChanged.connect(lambda _i: self._remote_changed())
        self.window_combo.currentIndexChanged.connect(lambda _i: self._window_changed())
        self.band_combo.currentIndexChanged.connect(lambda _i: self._band_shown())
        self.band_combo.currentIndexChanged.connect(lambda _i: self.draw())
        self.prev_band.clicked.connect(lambda: self.step_band(-1))
        self.next_band.clicked.connect(lambda: self.step_band(1))
        # PgUp / PgDn while the focus is anywhere in this tab (Left / Right stay the combo's and the plots'
        for key, step in ((Qt.Key_PageUp, -1), (Qt.Key_PageDown, 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(partial(self.step_band, step))
        self.chunk_combo.currentIndexChanged.connect(lambda _i: self._chunk_changed())
        self.compute_button.clicked.connect(self.compute)
        controls = QHBoxLayout()
        for text, widgets in (("Site", [self.site_combo]), ("Remote", [self.remote_combo]),
                              ("Window", [self.window_combo]),
                              ("Band", [self.prev_band, self.band_combo, self.next_band, self.band_label]),
                              ("Chunk", [self.chunk_combo])):
            controls.addWidget(QLabel(text, self))
            for widget in widgets:
                controls.addWidget(widget)
        controls.addWidget(self.compute_button)
        controls.addStretch(1)
        top = QVBoxLayout()  # the controls, then the status line on a row of its own, the tab's full width
        top.addLayout(controls)
        top.addWidget(self.status)

        # log10 values on linear axes, as the polar plane's x
        self.time_plots = [self._plot(label, date_axis=True) for label in (
            "log10 |Z| ((mV/km)/nT)", "phase (deg)", "coherence", "log10 |H| nT, |E| mV/km /sqrt Hz")]
        for plot in self.time_plots[1:]:
            plot.setXLink(self.time_plots[0])
        share_x_axis(self.time_plots)
        self.time_plots[-1].setLabel("bottom", "UTC (a spot at its chunk's centre; a bar over a chunk of several)")
        self.polar_plots = {mode: self._plot(POLAR_PHASE[mode], panel=f"polar {mode}") for mode in ("xy", "yx")}
        for mode, plot in self.polar_plots.items():
            plot.setLabel("bottom", f"log10 |Z{mode}|")
        left, right = self._column(self.time_plots), self._column(list(self.polar_plots.values()))
        split = QSplitter(Qt.Horizontal, self)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.all_bands = QCheckBox("all bands", self, checked=False, toolTip=ALL_BANDS_TIP)
        self.all_bands.toggled.connect(
            lambda on: setattr(self, "all_bands_wanted", on) if self.all_bands.isEnabled() else None)
        self.mask_button = QPushButton("Mask selected", self, clicked=self.mask_selected, toolTip=(
            "one mask per run of consecutive selected chunks, over their span on the shown band's grid"))
        self.unmask_button = QPushButton("Unmask selected", self, clicked=self.unmask_selected, toolTip=(
            "take the selected chunks' spans out of the masks applying to the band; on a level shown on "
            "chunks of several base chunks, band-limited masks only (Remove takes out an all-band one)"))
        self.remove_button = QPushButton("Remove", self, clicked=self.remove_rows)
        self.save_button = QPushButton("Save masks", self, clicked=self.save, toolTip="write <survey>/masks.yaml")
        self.count_label = QLabel("", self)
        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(REASON, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMaximumHeight(150)
        self.table.setToolTip(MASKS_TIP)
        self.table.itemChanged.connect(self._reason_edited)
        buttons = QVBoxLayout()
        for widget in (self.all_bands, self.mask_button, self.unmask_button, self.remove_button,
                       self.save_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        listing = QVBoxLayout()
        listing.addWidget(self.count_label)
        listing.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        bottom.addLayout(buttons)
        bottom.addLayout(listing, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addLayout(bottom)
        state.site_changed.connect(lambda site: self.select_site(site) if site else None)
        state.selection_changed.connect(lambda _selection: self._follow_selection())
        state.archive_lock.changed.connect(self._kick)
        self._band_shown()  # no survey yet: no label, both arrows off

    # ------------------------------------------------------------- building

    def _plot(self, left: str, panel: str = "time", date_axis: bool = False) -> pg.PlotWidget:
        """Return a plot on a `SelectBox` whose rubber band selects on `panel`, labelled `left`."""
        box = SelectBox()
        axes = {"bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0)} if date_axis else {}
        plot = pg.PlotWidget(parent=self, viewBox=box, axisItems=axes)
        box.selected.connect(partial(self.select_rect, panel, plot))
        plot.setMinimumHeight(90)
        plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        box.setDefaultPadding(0.12)  # a spot on the edge of a stacked panel stays inside it
        plot.setLabel("left", left)
        plot.getAxis("left").setWidth(64)
        for side in ("left", "bottom"):  # no SI prefix: coherence reads 0-1
            plot.getAxis(side).enableAutoSIPrefix(False)
        plot.panel = panel
        return plot

    def _column(self, plots) -> QWidget:
        """Return a widget stacking `plots` in one column."""
        box = QWidget(self)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        for plot in plots:
            column.addWidget(plot, 1)
        return box

    # -------------------------------------------------------------- survey

    def reload(self) -> None:
        """Load the survey opened: its archived sites and band scheme, with no result, store or pending read."""
        self._windows.clear()
        self.spans.reload()
        self.result, self._pending = None, None
        self.store, self.store_key, self.store_info, self.spare = None, None, {}, None
        survey = self.state.survey
        self.scheme = None
        if survey is not None:
            try:
                self.scheme = build_band_scheme(survey.sample_rate, **survey.processing)
            except (TypeError, ValueError) as exc:
                self.status.setText(f"band scheme: {exc}")
        self._fill_bands()
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        self.site_combo.addItems([s for s in self.state.all_sites() if self.state.has_archive(s)])
        self.site_combo.setCurrentIndex(-1)
        self.site_combo.blockSignals(False)
        self.select_site(self.state.site)
        if self.site_combo.currentIndex() < 0 and self.site_combo.count():
            self.site_combo.setCurrentIndex(0)

    def grid_of(self, level: int) -> tuple[int, int | None]:
        """Return (m, n) of `level`: base chunks per chunk and the chunk count in the result.

        Before a compute, m comes from `level_multiples` at the chunk combo's
        length and n is None.
        """
        if self.result is not None:
            grid = self.result["grids"][level]
            return int(grid["multiple"]), len(grid["starts"])
        return int(level_multiples(self.scheme, self.state.survey.sample_rate, self.chunk_s())[level]), None

    def grid_text(self, level: int) -> str:
        """Return the level's grid as text: '<n> chunks of <length>' or 'no chunk (needs <length>)'.

        Before a compute: 'chunks of <length>'.
        """
        m, n = self.grid_of(level)
        length = duration_text(m * self.chunk_s())
        if n is None:
            return f"chunks of {length}"
        return f"no chunk (needs {length})" if n == 0 else f"{n} chunks of {length}"

    def _fill_bands(self) -> None:
        """Fill the band combo with every band by period, then draw.

        Each band is marked with its level's grid at this chunk length:
        nothing for one estimate per base chunk, "(<length> chunks)" for
        chunks of several base chunks, "(no chunk)" when the result holds none
        of the level (the result's grids; `level_multiples` before a compute).
        """
        keep = self.band_combo.currentData()
        self.band_combo.blockSignals(True)
        self.band_combo.clear()
        if self.scheme is not None and self.state.survey is not None:
            level, lo, hi = band_table(self.scheme)
            periods = 1.0 / np.sqrt(lo * hi)
            grids = {int(lv): self.grid_of(int(lv)) for lv in np.unique(level)}
            for j, period in enumerate(periods):
                m, n = grids[int(level[j])]
                note = "" if m == 1 else f"  ({duration_text(m * self.chunk_s())} chunks)"
                if n == 0:
                    note = "  (no chunk)"
                self.band_combo.addItem(f"{period:.4g} s{note}", j)
            if keep is None or keep >= periods.size:  # a new survey: the band nearest DEFAULT_PERIOD_S
                keep = int(np.argmin(np.abs(np.log(periods / DEFAULT_PERIOD_S))))
            self.band_combo.setCurrentIndex(keep)
        self.band_combo.blockSignals(False)
        self._band_shown()
        self.draw()

    def step_band(self, step: int) -> None:
        """Move the band combo one band back (-1) or on (+1), stopping at either end."""
        index = self.band_combo.currentIndex() + step
        if 0 <= index < self.band_combo.count():
            self.band_combo.setCurrentIndex(index)

    def _band_shown(self) -> None:
        """Label the combo's current band and set the arrows and the "all bands" box.

        The label reads 'band <i> of <n> · <period> s · level <L> · <grid>'
        (its place in the list, centre period, decimation level, grid), empty
        without a band. Each arrow is on while it has a band to go to, and
        "all bands" at a band shown per base chunk.
        """
        index, count, j = self.band_combo.currentIndex(), self.band_combo.count(), self.band()
        self.prev_band.setEnabled(index > 0)
        self.next_band.setEnabled(0 <= index < count - 1)
        if j is None or self.scheme is None or self.state.survey is None:
            self.band_label.setText("")
            self._set_all_bands(True, ALL_BANDS_TIP)
            return
        level = int(band_table(self.scheme)[0][j])
        self.band_label.setText(f"band {index + 1} of {count} · {self.band_periods(j)[0]:.4g} s · level {level}"
                                f" · {self.grid_text(level)}")
        m = self.grid_of(level)[0]
        whole = duration_text(m * self.chunk_s())
        self._set_all_bands(m == 1, ALL_BANDS_TIP if m == 1 else (
            f"off at this band: level {level} is shown on chunks of {m} x {duration_text(self.chunk_s())} = "
            f"{whole}, so a time cut made from one would cut {whole} from every band; a mask made here "
            f"covers this band only (a band shown per base chunk makes time cuts, and the box comes back "
            f"there as it was set)"))

    def _set_all_bands(self, on: bool, tip: str) -> None:
        """Turn the "all bands" box on (ticked as last set while on) or off (shown unticked).

        While it is off, a mask made is band-limited whatever was set.
        """
        self.all_bands.blockSignals(True)
        self.all_bands.setEnabled(on)
        self.all_bands.setChecked(self.all_bands_wanted if on else False)
        self.all_bands.blockSignals(False)
        self.all_bands.setToolTip(tip)

    def site(self) -> str | None:
        """Return the site shown, or None."""
        return self.site_combo.currentText() or None

    def chunk_s(self) -> float:
        """Return the base chunk, s."""
        return float(self.chunk_combo.currentData() or CHUNKS_S[0])

    def _chunk_changed(self) -> None:
        """Regroup the result at the new base chunk, over the same window, from the store it came from."""
        r = self.result
        if r is not None and r["chunk_s"] != self.chunk_s():
            self._regroup(r["kind"], *r["range"], how=f"regrouped to {duration_text(self.chunk_s())} chunks",
                          slot=(r["store"], r["store_key"], {"archives": r["archives"], "notes": r["notes"]}))
        else:
            self._fill_bands()

    def select_site(self, site: str | None) -> None:
        """Show `site` in the site combo when it is listed."""
        index = self.site_combo.findText(site or "")
        if index >= 0 and index != self.site_combo.currentIndex():
            self.site_combo.setCurrentIndex(index)

    def _site_changed(self) -> None:
        """Show a new site: its masks from the file, its windows and remotes.

        The result is cleared and the store kept, so a window of its pair
        picked again is regrouped from it.
        """
        site = self.site()
        dropped = len(self.masks) if self.dirty else 0
        self.result, self.selected, self.selected_level, self.dirty = None, set(), None, False
        note = f"unsaved mask edits dropped ({dropped} mask(s) in the list)" if dropped else ""
        try:
            self.masks = load_masks(self.state.survey_yaml, site) if site and self.state.survey_yaml else []
        except ValueError as exc:  # a hand-edited masks.yaml that is not masks
            self.masks, note = [], f"masks.yaml: {exc}"
        self._fill_table()
        self._fill_bands()  # no result: the band labels from the chunk length alone; draws
        self.status.setText(note or MASK_ROUTE)
        self.window_combo.clear()  # the new site starts on its whole overlap
        self._read_spans()
        self._fill_remotes()

    def _read_spans(self) -> None:
        """Read the site's span, then every archived site's (the remote list and its preset), while on screen."""
        site = self.site()
        if site and self.isVisible():
            if self.spans.station != site:
                self.spans.set_sites(site, None)
            self.spans.read_spans([s for s in self.state.archived_sites() if s != site])

    # -------------------------------------------------- remotes and windows

    def _recommended(self, site: str) -> str | None:
        """Return the declared remote, else PairSummary's rule over the archived raw sites.

        None while spans are being read.
        """
        declared = self.state.default_remote(site)
        if declared and self.state.has_archive(declared):
            return declared
        candidates = [s for s in self.state.raw_sites() if s != site and self.state.has_archive(s)]
        if any(not self.spans.known(s) for s in (site, *candidates)):
            return None
        own = self.spans.span(site)
        hours = {}
        for c in candidates:
            common = overlap(own, self.spans.span(c))
            hours[c] = 0.0 if common is None else (common[1] - common[0]).total_seconds() / 3600.0
        if not hours or max(hours.values()) <= 0 or own is None:
            return None
        configured = set(self.state.configured_sites())

        def distance(name):
            a, b = (self.state.survey.site(n) if n in configured else None for n in (site, name))
            if a is None or b is None or None in (a.latitude, a.longitude, b.latitude, b.longitude):
                return (float("inf"), name)
            return (distance_km(a.latitude, a.longitude, b.latitude, b.longitude), name)

        own_h = (own[1] - own[0]).total_seconds() / 3600.0
        enough = [c for c in candidates if hours[c] >= PairSummary.ENOUGH_FRACTION * own_h]
        if enough:
            return min(enough, key=distance)
        best = max(hours.values())
        return min((c for c in candidates if hours[c] >= best - PairSummary.TIE_HOURS), key=distance)

    def _fill_remotes(self) -> None:
        """List the archived sites (and stacks) not known to miss the site's span, the recommendation preset."""
        site = self.site()
        own = self.spans.span(site)
        raw = self.state.raw_sites()
        keep = []
        for name in self.state.archived_sites():
            span = self.spans.span(name)
            if name == site or name in self.spans.unreadable or (own and span and overlap(own, span) is None):
                continue
            keep.append(name)
        current = self.remote_combo.currentData()
        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        for name in keep:
            self.remote_combo.addItem(name if name in raw else f"{name}  ({self.state.archive_kind(name)})", name)
        wanted = current if self._hand_remote == site else (self._recommended(site) if site else None)
        index = self.remote_combo.findData(wanted if wanted is not None else current)
        self.remote_combo.setCurrentIndex(max(index, 0) if keep else -1)
        self.remote_combo.blockSignals(False)
        self._fill_windows()
        if self.result is not None and self._pair_of(self.result["store_key"]) != self._pair():
            self._pair_changed()  # the preset moved under a drawing (the spans read meanwhile)

    def _remote_changed(self) -> None:
        """Follow a new remote: its overlap in the window list, then the drawing follows the new pair."""
        self._fill_windows()
        self._pair_changed()

    def _pair_changed(self) -> None:
        """Clear the drawing for a new pair shown and keep the stores.

        Called on a change of remote (a change of site clears on its own). A
        store of the new pair covering the window shown is regrouped at once;
        otherwise the status line asks for Compute.
        """
        self.result, self.selected, self.selected_level = None, set(), None
        data, pair = self.window_combo.currentData(), self._pair()
        if data and pair and self._take_store() and self.covers(*data):
            kind, start, end = data
            self._regroup(kind, start, end, how=f"regrouped to {self.describe(kind, start, end)} of "
                                                f"{pair[0]} rr {pair[1]} from the stored windows")
            return
        self._fill_bands()  # no result: blank panels
        if pair:
            self.status.setText(f"window picked for {pair[0]} rr {pair[1]}: press Compute")

    def whole_overlap(self):
        """Return (start, end) UTC shared by the site's and the remote's recorded spans.

        As the Process tab's window bar computes it (`window_bar.overlap`);
        None while a span is unread.
        """
        site, remote = self.site(), self.remote_combo.currentData()
        return overlap(self.spans.span(site), self.spans.span(remote)) if site and remote else None

    def _processing_window(self, site: str):
        """Return the Process tab's window while the user has set one there for `site`, else None.

        The Process tab is reached through the main window (`MainWindow.process_tab`). Its
        bar's `_chosen` is True once a window was dragged, typed or pushed from the Time Series
        tab; until then the bar shows the pair's overlap, which is this tab's first choice anyway.
        """
        process = getattr(self.window(), "process_tab", None)
        if process is None or process.station_combo.currentData() != site:
            return None
        bar = process.window_bar
        return bar.window() if getattr(bar, "_chosen", False) else None

    def _fill_windows(self) -> None:
        """Fill the window combo: whole overlap, the Process tab's window (when set), the QC windows."""
        site = self.site()
        keep = self.window_combo.currentData()
        combo = self.window_combo
        combo.blockSignals(True)
        combo.clear()
        if site is not None:
            common = self.whole_overlap()
            if common is not None:
                combo.addItem(f"whole overlap  {span_text(*common)}", (OVERLAP, *common))
            else:  # computed from the archives' own runs, the same intersection (compute_windows)
                combo.addItem("whole overlap  (spans being read)", (OVERLAP, None, None))
            chosen = self._processing_window(site)
            if chosen is not None:
                combo.addItem(f"processing window  {span_text(*chosen)}", (PROCESSING, *chosen))
            windows = self._windows.get(site)
            if windows is None:
                combo.addItem("QC windows: reading the archive...", None)
                combo.model().item(combo.count() - 1).setEnabled(False)
                self._wanted = site
            else:
                for start, end in windows:
                    combo.addItem(f"QC window  {window_label(start, end)}", (QC, start, end))
            index = 0
            for k in range(combo.count()):
                data = combo.itemData(k)
                if keep and data and data[0] == keep[0] and (keep[0] != QC or data[1:] == keep[1:]):
                    index = k
                    break
            combo.setCurrentIndex(index)
        combo.blockSignals(False)
        if self._wanted is not None:
            self._kick()

    def _follow_selection(self) -> None:
        """Follow a window of this site loaded anywhere (the tree, the Filter Data chooser).

        It becomes the choice while a QC window is the choice; the whole
        overlap and the processing window stay put.
        """
        selection, current = self.state.selection, self.window_combo.currentData()
        if selection is None or selection[0] != self.site() or not current or current[0] != QC:
            return
        for k in range(self.window_combo.count()):
            data = self.window_combo.itemData(k)
            if data and data[0] == QC and (selection[0], *data[1:]) == selection:
                self.window_combo.setCurrentIndex(k)

    def _pair(self) -> tuple | None:
        """Return (site, remote, local archive, remote archive) shown; None without a site and a remote."""
        site, remote = self.site(), self.remote_combo.currentData()
        if not site or not remote:
            return None
        return site, remote, str(self.state.archive_path(site)), str(self.state.archive_path(remote))

    @staticmethod
    def _pair_of(key: tuple) -> tuple:
        """Return the pair of a store key: (site, remote, local archive, remote archive)."""
        return key[0], key[1], key[5], key[6]

    def _same_pair(self) -> bool:
        """Return whether the store is of the site and remote shown, from the archives they have now."""
        return self.store_key is not None and self.store is not None and self._pair_of(self.store_key) == self._pair()

    def _take_store(self) -> bool:
        """Make the store of the pair shown the tab's store, and return whether there is one.

        The tab's store is already it, or the spare slot's is swapped in (the
        other becomes the spare); False when neither is of that pair. The
        callers call it while no result of another pair is drawn, so the store
        of a drawing on screen stays.
        """
        if self._same_pair():
            return True
        if self.spare is not None and self._pair_of(self.spare[1]) == self._pair():
            held = (self.store, self.store_key, self.store_info) if self.store is not None else None
            (self.store, self.store_key, self.store_info), self.spare = self.spare, held
            return True
        return False

    def covers(self, kind: str, start, end, store=None, key=None) -> bool:
        """Return whether a store holds every window of [start, end), within a sample.

        The overlap before its spans are read (no start or end) is covered
        when the store is of the overlap too.

        Args:
            kind (str): OVERLAP, PROCESSING or QC.
            start: The window's start, or None.
            end: The window's end, or None.
            store: The store (default: the tab's).
            key (tuple): Its key (default: the tab's store key).
        """
        store, key = (self.store, self.store_key) if store is None else (store, key)
        if start is None or end is None:
            return kind == OVERLAP and key[2] == OVERLAP
        sample = pd.Timedelta(seconds=1.0 / store.sample_rate)
        return utc(start) >= store.start - sample and utc(end) <= store.end + sample

    def _window_changed(self) -> None:
        """Draw, compute or wait for a window picked (or followed).

        A window of a stored pair inside its store is regrouped from it; one
        of a stored pair outside it is computed; one of a pair with no store
        clears the drawing and is left for Compute.
        """
        data, pair = self.window_combo.currentData(), self._pair()
        if not data or not pair:
            return
        if self.result is not None and self._pair_of(self.result["store_key"]) != pair:
            self.result, self.selected, self.selected_level = None, set(), None  # another pair's drawing
        if not self._take_store():
            self.result, self.selected, self.selected_level = None, set(), None
            self._fill_bands()
            self.status.setText(f"window picked for {pair[0]} rr {pair[1]}: press Compute")
            return
        kind, start, end = data
        if self.covers(kind, start, end):
            self._regroup(kind, start, end, how=f"regrouped to {self.describe(kind, start, end)} from the "
                                                f"stored windows")
        else:
            self.compute()

    def showEvent(self, event) -> None:
        """Read the spans, list the windows again and start any read waiting, as the tab is shown."""
        super().showEvent(event)
        self._read_spans()
        self._fill_windows()  # the Process tab's window may have been set meanwhile
        self._kick()

    # ------------------------------------------------------------- threads

    def compute(self) -> None:
        """Ask for the store of the chosen window, computed from the archives once the archive lock is free."""
        site, remote, window = self.site(), self.remote_combo.currentData(), self.window_combo.currentData()
        if not site or not remote or not window or self.scheme is None:
            self.status.setText("pick a site, a remote and a window")
            return
        kind, start, end = window
        self._pending = (site, remote, kind, start, end, str(self.state.archive_path(site)),
                         str(self.state.archive_path(remote)))
        self._kick()

    @staticmethod
    def describe(kind: str, start, end) -> str:
        """Return a window's name and length: 'the whole overlap (<h> h)', 'the processing window (<h> h)' or
        'a QC window (<h> h)'."""
        name = {OVERLAP: "the whole overlap", PROCESSING: "the processing window", QC: "a QC window"}[kind]
        if start is None or end is None:
            return name
        return f"{name} ({(utc(end) - utc(start)).total_seconds() / 3600.0:.1f} h)"

    def _kick(self) -> None:
        """Start the compute asked for, else the window read wanted, when the archive lock is free."""
        lock = self.state.archive_lock
        if self._wanted in self._windows:
            self._wanted = None  # read meanwhile (_fill_windows asks on every span read)
        if self._thread is not None or self.state.survey is None:
            return
        if lock.busy and lock.holder is not self:
            if self._pending is not None:
                self.status.setText("waiting for the archive...")
            return
        survey = self.state.survey
        if self._pending is not None:
            tag, self._pending = self._pending, None
            site, remote, kind, start, end, local_path, remote_path = tag
            thread = ReadThread(_compute, tag, survey, site, Path(local_path), remote, Path(remote_path), start,
                                end, self.scheme, report_progress=True, parent=self)
            head = f"computing {site} rr {remote} over {self.describe(kind, start, end)}"
            thread.progress.connect(lambda percent, message, head=head: self.status.setText(
                f"{head}: {message} ({percent} %)"))
            thread.result.connect(self._computed)
            self.computes += 1
            self.status.setText(f"{head}: reading the archives...")
        elif self._wanted is not None and self.isVisible():
            site, self._wanted = self._wanted, None
            path = self.state.archive_path(site)
            thread = ReadThread(_windows_for, (site, path), path, survey.name, site, parent=self)
            thread.result.connect(self._windows_read)
        else:
            return
        thread.failed.connect(lambda _tag, message: self.status.setText(f"failed: {message}"))
        thread.finished.connect(self._thread_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # set before acquire: its `changed` re-enters here and finds it
        lock.acquire(self)
        thread.start()

    def _thread_done(self) -> None:
        """Release the archive lock for the next read or compute."""
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for anything waiting

    def _windows_read(self, tag, windows) -> None:
        """Keep the QC windows read for a site whose archive is still the one read, and list them when shown."""
        site, path = tag
        if path == self.state.archive_path(site):
            self._windows[site] = list(windows)
            if self.site() == site:
                self._fill_windows()

    def _computed(self, tag, out) -> None:
        """Keep a computed store and draw it over the window the combo shows now, picked while it ran or not.

        A store of another pair than the one shown is kept in the spare slot
        and not drawn; the tab's store (the drawing's) stays, and a window of
        its pair shown again regroups it. A store of the combo's window is
        kept and binned at the chunk combo's length over its whole span; one
        covering the combo's window (picked meanwhile) is kept and binned over
        that window. In both cases a compute of that window queued behind
        this one is dropped, the status line saying "kept: <store> covers
        it". A store not covering the combo's window is dropped; that window
        is drawn from the store it was regrouped from, or is being computed,
        or waits for Compute.

        Args:
            tag (tuple): The store's key (site, remote, kind, start, end,
                local archive, remote archive).
            out (tuple): `_compute`'s (store, archive names, notes).
        """
        store, archives, notes = out
        info = {"archives": archives, "notes": notes}
        current = self.window_combo.currentData()
        took = f"{store.elapsed_s:.1f} s"
        if self._pair_of(tag) != self._pair():  # kept aside: the store of the drawing on screen stays
            self.spare = (store, tag, info)
            self.status.setText(f"{tag[0]} rr {tag[1]} over {self.describe(*tag[2:5])} computed in {took} and kept; "
                                f"not drawn: the pair shown changed meanwhile")
            return
        same = bool(current) and tuple(current) == tuple(tag[2:5])
        if same or (current and self.covers(*current, store=store, key=tag)):
            queued, kept = self._pending, ""
            if (queued is not None and self._pair_of(queued) == self._pair_of(tag)
                    and tuple(queued[2:5]) == tuple(current)):
                self._pending = None  # a compute of the window this store covers, queued behind it
                kept = f" (kept: {STORE_NAMES[tag[2]]} covers it, its queued compute dropped)"
            self._keep(store, tag, info)
            if same:
                self._regroup(tag[2], None, None, how=f"computed in {took}{kept}")
            else:
                self._regroup(*current, how=f"computed over {self.describe(*tag[2:5])} in {took}, drawn over "
                                            f"{self.describe(*current)} picked meanwhile{kept}")
            return
        waits = ("being computed" if self._pending is not None else
                 "drawn from the stored windows" if self._same_pair() and self.covers(*current) else
                 "waiting for Compute") if current else "waiting for a window"
        self.status.setText(f"{tag[0]} rr {tag[1]} over {self.describe(*tag[2:5])} computed in {took} and dropped: "
                            f"{self.describe(*current) if current else 'no window'} was picked meanwhile and is "
                            f"{waits}")

    def _keep(self, store, key: tuple, info: dict) -> None:
        """Make `store` (of the pair shown) the tab's store.

        The one it replaces moves to the spare slot when it is of another
        pair; a store of the same pair is superseded.
        """
        if self.store is not None and self._pair_of(self.store_key) != self._pair_of(key):
            self.spare = (self.store, self.store_key, self.store_info)
        self.store, self.store_key, self.store_info = store, key, info

    def _regroup(self, kind: str, start, end, how: str, slot: tuple | None = None) -> None:
        """Bin a store into base chunks of the combo's length over [start, end) and draw the result.

        Numpy sums on the store alone; the status line says `how` and how long
        it took.

        Args:
            kind (str): The window's kind.
            start: The window's start (None: the store's own span).
            end: The window's end (None: the store's own span).
            how (str): What happened, first on the status line.
            slot (tuple | None): (store, key, info), by default the tab's
                store; the result keeps its own store's key.
        """
        store, key, info = (self.store, self.store_key, self.store_info) if slot is None else slot
        began = time.perf_counter()
        try:
            result = bin_windows(store, self.chunk_s(), start, end)
        except ValueError as exc:  # a window under half a base chunk
            self.result, self.selected, self.selected_level = None, set(), None
            self.status.setText(f"no chunk: {exc}")
            self._fill_bands()
            return
        took_ms = 1e3 * (time.perf_counter() - began)
        result.update(tag=(key[0], key[1], kind, start, end), range=(start, end), kind=kind, store_key=key, **info)
        self.result, self.selected, self.selected_level = result, set(), None
        how = how if how.startswith("computed") else f"{how} in {took_ms:.0f} ms, no archive read"
        self._describe(how)
        self._fill_bands()  # the bands' grids, and the draw

    def _describe(self, how: str) -> None:
        """Write the status line for the result, what changes first.

        `how` it was made, the span drawn (said to be rounded out to whole
        minutes, with the window asked for, when it is not that window) and
        the base chunks; then the pair, its archives and the masks' route,
        which the elision may take.
        """
        r = self.result
        drawn = span_text(r["start"], r["end"], seconds=True)
        asked, sample = r["range"], pd.Timedelta(seconds=1.0 / r["sample_rate"])
        if asked[0] is not None and (abs(utc(asked[0]) - r["start"]) > sample or abs(utc(asked[1]) - r["end"]) > sample):
            drawn += (f", rounded out to whole minutes from the window asked for, "
                      f"{span_text(asked[0], asked[1], seconds=True)} (the store sums its windows in {BIN_S:.0f} s bins)")
        self.status.setText(f"{how}; {len(r['base_starts'])} base chunks of {duration_text(r['chunk_s'])} over "
                            f"{drawn}; {r['station']} rr {r['remote']} ({' / '.join(r['archives'])}); "
                            f"{MASK_ROUTE}" + (f"; {r['notes']}" if r["notes"] else ""))

    def wait(self) -> None:
        """Let a read or compute in flight finish as the window closes, and drop anything waiting."""
        self._pending = self._wanted = None
        self.spans.wait_for_read()
        if self._thread is not None:
            self._thread.wait()

    # ------------------------------------------------------------- drawing

    def band(self) -> int | None:
        """Return the band shown (an index in band_table's order), or None."""
        j = self.band_combo.currentData()
        return None if j is None else int(j)

    def band_periods(self, j: int) -> tuple[float, float, float]:
        """Return (period, pmin, pmax) of band j, s."""
        _level, lo, hi = band_table(self.scheme)
        return 1.0 / np.sqrt(lo[j] * hi[j]), 1.0 / hi[j], 1.0 / lo[j]

    def applies(self, mask: dict, j: int) -> bool:
        """Return whether `mask` covers band j (`crust.masks.applies` at its centre period)."""
        return applies(mask, self.band_periods(j)[0])

    def masked_chunks(self, j: int) -> np.ndarray:
        """Return, per chunk of band j's grid, 0 clear, 1 partly or 2 fully masked by the masks applying to it.

        `crust.crosspower.masked_chunks`, judged on the windows or minute
        bins `stack_impedance` keeps.
        """
        return masked_chunks(self.result, self.masks, j)

    def view(self, j: int) -> dict:
        """Return band j of the result on its own grid (`crust.crosspower.band_view`)."""
        return band_view(self.result, j)

    def draw(self) -> None:
        """Draw the chosen band of the result on every panel, or empty panels with the reason without one."""
        self.items = {}
        for plot in (*self.time_plots, *self.polar_plots.values()):
            plot.clear()
            plot.setTitle(None)
        r, j = self.result, self.band()
        if r is None or j is None:
            self._count()
            return
        v = self.view(j)
        if self.selected and v["level"] != self.selected_level:  # its indices name other chunks here
            self.status.setText(f"selection of {len(self.selected)} chunk(s) cleared: made on level "
                                f"{self.selected_level}, the band shown is on level {v['level']}")
            self.selected, self.selected_level = set(), None
        period, m, n = self.band_periods(j)[0], v["multiple"], len(v["starts"])
        span = span_text(r["start"], r["end"], seconds=True)  # the span drawn (rounded out to minutes, if it was)
        if n == 0:
            why = (f"no chunk at band {period:.4g} s: a level-{v['level']} chunk is {m} x "
                   f"{duration_text(r['chunk_s'])} = {duration_text(m * r['chunk_s'])}, longer than the window")
            self.time_plots[0].setTitle(f"{r['station']} rr {r['remote']}  {span}: {why}")
            for plot in self.polar_plots.values():
                plot.setTitle("no chunk at this band")
            self._count()
            return
        lo_s = np.asarray(v["starts"].asi8, dtype=float) / 1e9
        hi_s = np.asarray(v["ends"].asi8, dtype=float) / 1e9
        t = 0.5 * (lo_s + hi_s)  # a chunk's spot at its centre
        ok = v["n_windows"] > 0
        zxy, zyx = v["zxy"], v["zyx"]
        with np.errstate(divide="ignore", invalid="ignore"):
            lxy, lyx, lh, le = (np.log10(np.abs(x)) for x in (zxy, zyx, v["h_amp"], v["e_amp"]))
        rows = [
            (self.time_plots[0], [(t, lxy, XY_COLOUR, "xy"), (t, lyx, YX_COLOUR, "yx")]),
            (self.time_plots[1], [(t, np.degrees(np.angle(zxy)), XY_COLOUR, None),
                                  (t, np.degrees(np.angle(zyx)), YX_COLOUR, None)]),
            (self.time_plots[2], [(t, v["coh_xy"], XY_COLOUR, None), (t, v["coh_yx"], YX_COLOUR, None)]),
            (self.time_plots[3], [(t, lh, theme.B_COLOUR, "|H|"), (t, le, theme.E_COLOUR, "|E|")]),
            (self.polar_plots["xy"], [(lxy, mode_phase(zxy, "xy"), XY_COLOUR, None)]),
            (self.polar_plots["yx"], [(lyx, mode_phase(zyx, "yx"), YX_COLOUR, None)]),
        ]
        for plot, series in rows:
            if any(name for *_rest, name in series):
                legend = plot.addLegend(offset=(5, 5))
                legend.clear()
                for *_xy, colour, name in series:  # a plain sample: the spots' own brushes vary
                    legend.addItem(pg.ScatterPlotItem(symbol="o", brush=pg.mkBrush(colour),
                                                      pen=pg.mkPen(colour)), name)
            for x, y, colour, _name in series:
                good = ok & np.isfinite(x) & np.isfinite(y)
                if m > 1 and plot.panel == "time" and good.any():  # the chunk's span
                    bars = pg.ErrorBarItem(x=x[good], y=y[good], left=(x - lo_s)[good], right=(hi_s - x)[good],
                                           beam=0, pen=pg.mkPen(colour, width=1))
                    plot.addItem(bars)  # not a data item: the spot counts and the selection ignore it
                item = pg.PlotDataItem(x[good], y[good], pen=None, symbol="o")
                plot.addItem(item)
                self.items.setdefault(plot, []).append((item, x[good], y[good], np.flatnonzero(good), colour))
        grid = f"{n} chunks of {duration_text(r['chunk_s'])}" if m == 1 else (
            f"{n} chunks of {duration_text(m * r['chunk_s'])} ({m} x {duration_text(r['chunk_s'])})")
        self.time_plots[0].setTitle(f"{r['station']} rr {r['remote']}  {span}, {grid}  band {period:.4g} s")
        self.restyle()

    def restyle(self) -> None:
        """Restyle the spots: filled (clear), lighter (partly masked), hollow (fully masked) or ringed (selected)."""
        j = self.band()
        if self.result is None or j is None:
            self._count()
            return
        masked = self.masked_chunks(j)
        many = masked.size > MANY
        size, bigger = (SMALL_SIZE, SMALL_SIZE + 4) if many else (SIZE, SELECTED_SIZE)
        hollow, ring = pg.mkBrush(None), pg.mkPen(theme.CURSOR_COLOUR, width=2.5)  # one object per look
        for entries in self.items.values():
            for item, x, y, idx, colour in entries:
                fill, edge = pg.mkBrush(colour), pg.mkPen(colour, width=1.0 if many else 1.5)
                looks = (fill, pg.mkBrush(lighter(colour)), hollow)  # by masked_chunks' code 0 / 1 / 2
                picked = [int(k) in self.selected for k in idx]
                brushes = [looks[int(masked[k])] for k in idx]
                pens = [ring if p else edge for p in picked]
                sizes = [bigger if p else size for p in picked]
                item.setData(x, y, pen=None, symbol="o", symbolBrush=brushes, symbolPen=pens, symbolSize=sizes)
        self._count()

    # ------------------------------------------------------------ selecting

    def select_rect(self, panel: str, plot: pg.PlotWidget, rect: QRectF) -> None:
        """Select the chunks (band grid) with a spot inside `rect`, remembered with the band's level.

        Args:
            panel (str): "time", "polar xy" or "polar yx".
            plot (pg.PlotWidget): The plot the rubber band was drawn on.
            rect (QRectF): The rubber band, in `plot`'s view coordinates.
        """
        picked = set()
        for _item, x, y, idx, _colour in self.items.get(plot, []):
            inside = (x >= rect.left()) & (x <= rect.right()) & (y >= rect.top()) & (y <= rect.bottom())
            picked |= {int(k) for k in idx[inside]}
        j = self.band()
        level = None if self.result is None or j is None else int(self.result["band_level"][j])
        self.selected, self.selected_on, self.selected_level = picked, panel, level
        self.restyle()

    def mask_selected(self) -> None:
        """Add one mask per run of consecutive selected chunks, over their span on the band's grid."""
        r, j = self.result, self.band()
        if r is None or j is None or not self.selected:
            return
        v = self.view(j)
        period, pmin, pmax = self.band_periods(j)
        whole = self.selected_on == "time" and self.all_bands.isChecked() and v["multiple"] == 1
        runs, run = [], []
        for k in sorted(self.selected):
            if run and k != run[-1] + 1:
                runs.append(run)
                run = []
            run.append(k)
        runs.append(run)
        grid = "" if v["multiple"] == 1 else (
            f", level {v['level']} chunks of {duration_text(v['multiple'] * r['chunk_s'])}")
        for run in runs:
            self.masks.append(normalise({
                "start": v["starts"][run[0]], "end": v["ends"][run[-1]],
                "bands": "all" if whole else [pmin, pmax],
                "reason": f"{self.selected_on} panel, {period:.4g} s band{grid}",
                "found_by": "time" if self.selected_on == "time" else "polar", "scope": "local"}))
        self._edited()
        span_s = sum((v["ends"][run[-1]] - v["starts"][run[0]]).total_seconds() for run in runs)
        self.status.setText(
            f"{len(runs)} mask{'s' if len(runs) > 1 else ''} over {duration_text(span_s)}, "
            + ("all bands (a time cut)" if whole else f"band {period:.4g} s only ({pmin:.4g}-{pmax:.4g} s)")
            + "; Save writes masks.yaml")

    def unmask_selected(self) -> None:
        """Take the selected chunks' spans out of every mask that applies to the band (a mask may split).

        On a level shown on chunks of several base chunks this takes them out
        of the band-limited masks and names the all-band ones on the status
        line.
        """
        r, j = self.result, self.band()
        if r is None or j is None or not self.selected:
            return
        v = self.view(j)
        grouped = v["multiple"] > 1
        cuts = [(v["starts"][k], v["ends"][k]) for k in sorted(self.selected)]
        out, left = [], []
        for m in self.masks:
            touched = any(utc(m["start"]) < b and utc(m["end"]) > a for a, b in cuts)
            if not self.applies(m, j) or not touched:
                out.append(m)
                continue
            if grouped and m["bands"] == "all":
                out.append(m)
                left.append(m)
                continue
            pieces = [(utc(m["start"]), utc(m["end"]))]
            for a, b in cuts:
                pieces = [p for s, e in pieces for p in ((s, min(e, a)), (max(s, b), e)) if p[1] > p[0]]
            out += [normalise({**m, "start": s, "end": e}) for s, e in pieces]
        self.masks = out
        self._edited()
        if left:
            names = ", ".join(f"{iso(m['start'])} to {iso(m['end'])}" for m in left)
            self.status.setText(
                f"{len(left)} all-band mask(s) left as they are ({names}): level {v['level']} chunks are "
                f"{duration_text(v['multiple'] * r['chunk_s'])} long, and unmasking one would reopen that span in "
                f"every band; take them out with Remove")

    # ---------------------------------------------------------- the list

    def _edited(self) -> None:
        """Sort the masks, mark them unsaved, clear the selection, and list and restyle again."""
        self.masks.sort(key=lambda m: m["start"])
        self.dirty, self.selected, self.selected_level = True, set(), None
        self._fill_table()
        self.restyle()

    def _fill_table(self) -> None:
        """List the masks in the table, the reason column editable."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.masks))
        for row, m in enumerate(self.masks):
            bands = "all" if m["bands"] == "all" else f"{m['bands'][0]:.4g}-{m['bands'][1]:.4g}"
            for col, text in enumerate((m["start"], m["end"], bands, m["reason"], m["found_by"])):
                item = QTableWidgetItem(str(text))
                if col != REASON:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self._count()

    def _reason_edited(self, item) -> None:
        """Keep a reason typed in the table."""
        if item.column() == REASON and item.row() < len(self.masks):
            self.masks[item.row()]["reason"] = item.text()
            self.dirty = True
            self._count()

    def remove_rows(self) -> None:
        """Drop the masks of the rows picked."""
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        if rows:
            self.masks = [m for k, m in enumerate(self.masks) if k not in rows]
            self._edited()

    def save(self) -> None:
        """Write this site's masks to `<survey>/masks.yaml`."""
        site = self.site()
        if not site or self.state.survey_yaml is None:
            return
        path = save_masks(self.state.survey_yaml, site, self.masks)
        self.dirty = False
        self.status.setText(f"{len(self.masks)} mask(s) of {site} saved to {path.name}; {MASK_ROUTE}")
        self._count()

    def _count(self) -> None:
        """Write the count above the list: '<k> of <n> chunks masked (<p> partly); <m> mask(s), <h> h'.

        It counts the chunks of the shown band's grid with any kept window
        masked (' (<p> partly)' when some are partly masked; 'chunks of
        <length>' on a level shown on chunks of several base chunks) and the
        hours of the union of every mask of the site.
        """
        hours, cursor = 0.0, None
        for a, b in sorted((utc(m["start"]), utc(m["end"])) for m in self.masks):
            a = a if cursor is None else max(a, cursor)
            if b > a:
                hours += (b - a).total_seconds() / 3600.0
                cursor = b
        text = f"{len(self.masks)} mask(s), {hours:.2f} h"
        j = self.band()
        if self.result is not None and j is not None:
            codes = self.masked_chunks(j)
            m = self.view(j)["multiple"]
            if codes.size == 0:
                text = f"no chunk at this band; {text}"
            else:
                unit = "chunks" if m == 1 else f"chunks of {duration_text(m * self.result['chunk_s'])}"
                partly = int((codes == 1).sum())
                text = (f"{int((codes > 0).sum())} of {codes.size} {unit} masked"
                        + (f" ({partly} partly)" if partly else "") + f"; {text}")
        self.count_label.setText(text + ("  (not saved)" if self.dirty else ""))
