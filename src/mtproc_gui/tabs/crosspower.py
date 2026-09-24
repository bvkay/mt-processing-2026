"""Cross-powers tab: one site's chunk-by-chunk RR impedances, and the masks declared from them.

A cross-power editor and viewer for the processed data, one site at a time,
where certain time windows and polar coordinates can be masked, working on
all the windows at once rather than stepping through each one. Top row: the
site (archived sites), the remote (archived sites whose recorded span
overlaps the site's; preset to the site's declared `remote:`, else the
Process tab's recommendation rule, `site_map.PairSummary.recommendation`,
over the archived raw sites), the window, the band (every band of the
survey's lemimt scheme, by period; the arrows either side of it, or PgUp /
PgDn anywhere in the tab, step one band back or on, and the label after
them names the band shown: "band 23 of 60 · 1.14 s · level 3", its place in
the list, its centre period and its decimation level), the chunk length
and **Compute**.

The window is, first and by default, the **whole overlap** of the site and
the remote: `window_bar.overlap` of their recorded spans, read exactly as
the Process tab's window bar reads them (a `WindowBar` of its own, never
shown). Then the Process tab's **processing window**, listed while one is
set there for this site (dragged, typed or pushed from the Time Series tab;
the bar's own default is the overlap again, so it is not listed). Then each
of the site's 2 h **QC windows** (`mtproc_gui.windows.window_list`; while a
QC window is the choice, the window loaded in the tree is followed).
Compute runs `mtproc.crosspower.chunk_impedances` in a `ReadThread` under
`State.archive_lock` on the archives processing reads (`processing_source`)
-- a view computation, nothing written -- with the chunk count on the
status line as it goes; the result stays until the next Compute (a new site
clears it). A 44 h overlap takes 31-37 s in 10 min chunks, 45-56 s in 1 min
chunks, on 4 workers (`mtproc.crosspower`).

Views (pyqtgraph): left, the time panel -- log10 |Z|, phase, the coherence
of E with the E that Z predicts, and the chunk's log10 |H| and |E| against
chunk start on a UTC date axis (hours, or days for a record of days), xy
blue and yx red as the View EDIs tab (mtpy) draws them; right, the polar
plane of the band -- (log10 |Z|, phase) for xy over yx. A masked chunk is
drawn hollow. A left-drag on any panel draws a rubber band and selects the
chunks inside it (on either mode); "Mask selected" adds one mask per run of
consecutive selected chunks -- `bands: all` from the time panel with "all
bands" ticked, the band's [pmin, pmax] from the polar panel -- and "Unmask
selected" takes the selected chunks out of the masks that apply to the band
(`mtproc.masks.applies`). The site's masks are listed (the reason cell is
editable), Remove drops the rows picked, and **Save masks** writes
`<survey>/masks.yaml` (`mtproc.masks.save_masks`: only this site's block). A
change of site reloads the list from the file; unsaved edits are dropped
with a line in the status label.

What the masks do downstream, said on the status line (`MASK_ROUTE`): an
all-band mask is a time cut in processing (scripts/process_rr.py ->
`mtproc.masks.apply_time_masks`); a band mask is recorded, and acts only in
`mtproc.crosspower.stack_impedance` -- aurora 0.6.2 takes no per-band window
weights (see `mtproc.masks`). The tab estimates nothing itself: it is a view
and a mask editor.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from pyqtgraph import Point
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGraphicsRectItem, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from mtproc.bands import lemimt_band_scheme
from mtproc.crosspower import band_table, chunk_impedances, levels_in_chunk, masked_chunks
from mtproc.masks import applies, load_masks, normalise, save_masks, utc
from mtproc.survey import distance_km
from mtproc_gui import theme
from mtproc_gui.archive import load_grid
from mtproc_gui.plots import share_x_axis
from mtproc_gui.reader import ReadThread
from mtproc_gui.site_map import PairSummary
from mtproc_gui.window_bar import WindowBar, overlap
from mtproc_gui.windows import window_label, window_list

XY_COLOUR, YX_COLOUR = theme.B_COLOUR, theme.E_COLOUR  # as mtpy draws xy and yx on View EDIs
CHUNKS_S = (600.0, 300.0, 120.0, 60.0)
WORKERS = 4
DEFAULT_PERIOD_S = 0.05
SIZE, SELECTED_SIZE = 8, 12
SMALL_SIZE, MANY = 5, 300  # spot size past MANY chunks (a 44 h record is 263 of 10 min, 2629 of 1 min)
COLUMNS = ("start (UTC)", "end (UTC)", "bands (s)", "reason", "found by")
REASON = 3
OVERLAP, PROCESSING, QC = "overlap", "processing", "qc"  # the window choices, in the combo's order
MASK_ROUTE = "all-band masks: time cuts; band masks: their windows dropped in those bands (aurora patch)"


def span_text(start, end) -> str:
    """'2023-09-22 13:57 to 2023-09-24 09:46 UTC (43.8 h)'."""
    hours = (utc(end) - utc(start)).total_seconds() / 3600.0
    return f"{utc(start):%Y-%m-%d %H:%M} to {utc(end):%Y-%m-%d %H:%M} UTC ({hours:.1f} h)"


def _windows_for(path, survey_name: str, station: str):
    return window_list(load_grid(path, survey_name, station))


def processing_source(survey, site: str, raw: Path) -> tuple[Path, str]:
    """(the archive processing reads for `site`, a note), never building anything.

    The raw `<site>.h5` when the site declares no filters (or is a stack);
    its filtered variant `<site>_f<hash>.h5` when `mtproc.ingest.variant_ready`
    says it is built for the current declaration; otherwise the raw archive,
    noted "raw archive (filtered variant not built)". Not
    `mtproc.ingest.processing_archive`, which builds a missing variant: a view
    never writes a product. Opens archives (read-only), so it runs in the
    compute's thread, under the archive lock.
    """
    try:
        from mtproc.ingest import archive_filter_kinds, variant_path, variant_ready
    except ImportError:  # a library from before the raw / variant split
        return raw, ""
    if site not in survey.site_names() or not survey.site(site).filters:
        baked = archive_filter_kinds(raw)
        return raw, f"old-layout archive, filters baked in: {baked}" if baked else ""
    if variant_ready(survey, site):
        return variant_path(survey, site), ""
    return raw, "raw archive (filtered variant not built)"


def _compute(survey, site, raw_local, remote, raw_remote, start, end, scheme, chunk_s, progress=None):
    """`chunk_impedances` on the archives processing reads (`processing_source`), notes attached."""
    (local, local_note), (far, far_note) = (processing_source(survey, site, raw_local),
                                            processing_source(survey, remote, raw_remote))
    result = chunk_impedances(local, site, far, remote, start, end, scheme, chunk_s=chunk_s, workers=WORKERS,
                              progress=progress)
    result["archives"] = (Path(local).name, Path(far).name)
    result["notes"] = "; ".join(f"{n}: {t}" for n, t in ((site, local_note), (remote, far_note)) if t)
    return result


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
    """Chunk impedances of one site on a time panel and a polar plane; masks.yaml from what is picked."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.scheme: dict | None = None
        self.result: dict | None = None
        self.masks: list[dict] = []
        self.dirty = False
        self.selected: set[int] = set()
        self.selected_on = "time"  # or "polar xy" / "polar yx"
        self._windows: dict[str, list] = {}
        self._wanted: str | None = None  # a site whose windows are to be read
        self._pending = None  # a compute asked for, waiting for the archive
        self._thread: ReadThread | None = None
        self._hand_remote: str | None = None  # the site whose remote was picked by hand
        # plot -> [(item, x, y (view coordinates), chunk index per spot, colour)]
        self.items: dict[pg.PlotWidget, list] = {}
        self.spans = WindowBar(state, self)  # never shown: the recorded spans, read as the Process tab reads them
        self.spans.hide()
        self.spans.spans_changed.connect(self._fill_remotes)

        self.site_combo = QComboBox(self, minimumWidth=90)
        self.remote_combo = QComboBox(self, minimumWidth=110, toolTip="archived sites overlapping the site")
        self.window_combo = QComboBox(self, minimumWidth=330, toolTip=(
            "whole overlap of site and remote (default), the Process tab's processing window "
            "when one is set for this site, or one 2 h QC window"))
        self.band_combo = QComboBox(self, minimumWidth=150)
        self.prev_band = QToolButton(self, arrowType=Qt.LeftArrow, toolTip="previous band (PgUp)")
        self.next_band = QToolButton(self, arrowType=Qt.RightArrow, toolTip="next band (PgDn)")
        self.band_label = QLabel("", self)  # the list is long: which band is shown
        self.chunk_combo = QComboBox(self, toolTip="chunk length: one impedance per chunk and band")
        for seconds in CHUNKS_S:
            self.chunk_combo.addItem(f"{seconds / 60:g} min", seconds)
        self.compute_button = QPushButton("Compute", self, toolTip="chunk_impedances over the window, 4 threads")
        self.status = QLabel("", self)
        self.site_combo.currentIndexChanged.connect(lambda _i: self._site_changed())
        self.remote_combo.activated.connect(lambda _i: setattr(self, "_hand_remote", self.site()))
        self.remote_combo.currentIndexChanged.connect(lambda _i: self._fill_windows())  # a new overlap
        self.band_combo.currentIndexChanged.connect(lambda _i: self._band_shown())
        self.band_combo.currentIndexChanged.connect(lambda _i: self.draw())
        self.prev_band.clicked.connect(lambda: self.step_band(-1))
        self.next_band.clicked.connect(lambda: self.step_band(1))
        # PgUp / PgDn while the focus is anywhere in this tab; not bare Left / Right, the combo's and the plots'
        for key, step in ((Qt.Key_PageUp, -1), (Qt.Key_PageDown, 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(partial(self.step_band, step))
        self.chunk_combo.currentIndexChanged.connect(lambda _i: self._fill_bands())
        self.compute_button.clicked.connect(self.compute)
        top = QHBoxLayout()
        for text, widgets in (("Site", [self.site_combo]), ("Remote", [self.remote_combo]),
                              ("Window", [self.window_combo]),
                              ("Band", [self.prev_band, self.band_combo, self.next_band, self.band_label]),
                              ("Chunk", [self.chunk_combo])):
            top.addWidget(QLabel(text, self))
            for widget in widgets:
                top.addWidget(widget)
        top.addWidget(self.compute_button)
        top.addWidget(self.status, 1)

        # log10 on linear axes, as the polar plane's x: a log axis spanning under a decade
        # (a chunk's |Z| scatter) stacks its minor tick labels on top of each other
        self.time_plots = [self._plot(label, date_axis=True) for label in (
            "log10 |Z| ((mV/km)/nT)", "phase (deg)", "coherence", "log10 |H| nT, |E| mV/km /sqrt Hz")]
        for plot in self.time_plots[1:]:
            plot.setXLink(self.time_plots[0])
        share_x_axis(self.time_plots)
        self.time_plots[-1].setLabel("bottom", "chunk start (UTC)")
        self.polar_plots = {mode: self._plot("phase (deg)", panel=f"polar {mode}") for mode in ("xy", "yx")}
        for mode, plot in self.polar_plots.items():
            plot.setLabel("bottom", f"log10 |Z{mode}|")
        left, right = self._column(self.time_plots), self._column(list(self.polar_plots.values()))
        split = QSplitter(Qt.Horizontal, self)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.all_bands = QCheckBox("all bands", self, checked=False,
                                   toolTip="ticked: a time-panel mask is a time cut, every band left out "
                                           "(bands: all); unticked: it covers the shown band only, like a "
                                           "polar-panel mask")
        self.mask_button = QPushButton("Mask selected", self, clicked=self.mask_selected)
        self.unmask_button = QPushButton("Unmask selected", self, clicked=self.unmask_selected)
        self.remove_button = QPushButton("Remove", self, clicked=self.remove_rows)
        self.save_button = QPushButton("Save masks", self, clicked=self.save, toolTip="write <survey>/masks.yaml")
        self.count_label = QLabel("", self)
        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(REASON, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMaximumHeight(150)
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
        box = SelectBox()
        axes = {"bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0)} if date_axis else {}
        plot = pg.PlotWidget(parent=self, viewBox=box, axisItems=axes)
        box.selected.connect(partial(self.select_rect, panel, plot))
        plot.setMinimumHeight(90)
        plot.showGrid(x=True, y=True, alpha=theme.GRID_ALPHA)
        box.setDefaultPadding(0.12)  # a spot on the edge of a stacked panel stays inside it
        plot.setLabel("left", left)
        plot.getAxis("left").setWidth(64)
        for side in ("left", "bottom"):  # coherence reads 0-1, not "(x0.001)" 0-1000
            plot.getAxis(side).enableAutoSIPrefix(False)
        plot.panel = panel
        return plot

    def _column(self, plots) -> QWidget:
        box = QWidget(self)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        for plot in plots:
            column.addWidget(plot, 1)
        return box

    # -------------------------------------------------------------- survey

    def reload(self) -> None:
        """A survey was opened: its archived sites, its band scheme, no result, no read in flight."""
        self._windows.clear()
        self.spans.reload()
        self.result, self._pending = None, None
        survey = self.state.survey
        self.scheme = None
        if survey is not None:
            try:
                self.scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)
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

    def _fill_bands(self) -> None:
        """Every band by period; a band whose level fits no chunk of this length says so."""
        keep = self.band_combo.currentData()
        self.band_combo.blockSignals(True)
        self.band_combo.clear()
        if self.scheme is not None and self.state.survey is not None:
            level, lo, hi = band_table(self.scheme)
            fits = levels_in_chunk(self.scheme, int(self.chunk_s() * self.state.survey.sample_rate))
            periods = 1.0 / np.sqrt(lo * hi)
            for j, period in enumerate(periods):
                text = f"{period:.4g} s" + ("" if level[j] < fits else "  (longer than a chunk)")
                self.band_combo.addItem(text, j)
            if keep is None or keep >= periods.size:  # a new survey: the band nearest DEFAULT_PERIOD_S
                keep = int(np.argmin(np.abs(np.log(periods / DEFAULT_PERIOD_S))))
            self.band_combo.setCurrentIndex(keep)
        self.band_combo.blockSignals(False)
        self._band_shown()
        self.draw()

    def step_band(self, step: int) -> None:
        """The band combo one band back (-1) or on (+1); nothing past either end."""
        index = self.band_combo.currentIndex() + step
        if 0 <= index < self.band_combo.count():
            self.band_combo.setCurrentIndex(index)

    def _band_shown(self) -> None:
        """'band 23 of 60 · 1.14 s · level 3' for the combo's current band (its place in the list,
        its centre period, its decimation level), empty without one; each arrow on while it has a band to go to."""
        index, count, j = self.band_combo.currentIndex(), self.band_combo.count(), self.band()
        self.prev_band.setEnabled(index > 0)
        self.next_band.setEnabled(0 <= index < count - 1)
        if j is None or self.scheme is None:
            self.band_label.setText("")
            return
        level = band_table(self.scheme)[0][j]
        self.band_label.setText(f"band {index + 1} of {count} · {self.band_periods(j)[0]:.4g} s · level {level}")

    def site(self) -> str | None:
        return self.site_combo.currentText() or None

    def chunk_s(self) -> float:
        return float(self.chunk_combo.currentData() or CHUNKS_S[0])

    def select_site(self, site: str | None) -> None:
        index = self.site_combo.findText(site or "")
        if index >= 0 and index != self.site_combo.currentIndex():
            self.site_combo.setCurrentIndex(index)

    def _site_changed(self) -> None:
        """New site: its masks from the file, its windows and remotes; the old result is cleared."""
        site = self.site()
        dropped = len(self.masks) if self.dirty else 0
        self.result, self.selected, self.dirty = None, set(), False
        note = f"unsaved mask edits dropped ({dropped} mask(s) in the list)" if dropped else ""
        try:
            self.masks = load_masks(self.state.survey_yaml, site) if site and self.state.survey_yaml else []
        except ValueError as exc:  # a hand-edited masks.yaml that is not masks
            self.masks, note = [], f"masks.yaml: {exc}"
        self._fill_table()
        self.draw()
        self.status.setText(note or MASK_ROUTE)
        self.window_combo.clear()  # the new site starts on its whole overlap
        self._read_spans()
        self._fill_remotes()

    def _read_spans(self) -> None:
        """On screen only: the site's span, then every archived site's (the remote list and its preset)."""
        site = self.site()
        if site and self.isVisible():
            if self.spans.station != site:
                self.spans.set_sites(site, None)
            self.spans.read_spans([s for s in self.state.archived_sites() if s != site])

    # -------------------------------------------------- remotes and windows

    def _recommended(self, site: str) -> str | None:
        """The declared remote, else PairSummary's rule over the archived raw sites (None while spans are read)."""
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
        """Archived sites (and stacks) not known to miss the site's span; the recommendation preset."""
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
            self.remote_combo.addItem(name if name in raw else f"{name}  (stack)", name)
        wanted = current if self._hand_remote == site else (self._recommended(site) if site else None)
        index = self.remote_combo.findData(wanted if wanted is not None else current)
        self.remote_combo.setCurrentIndex(max(index, 0) if keep else -1)
        self.remote_combo.blockSignals(False)
        self._fill_windows()

    def whole_overlap(self):
        """(start, end) UTC shared by the site's and the remote's recorded spans, as the Process
        tab's window bar computes it (`window_bar.overlap`); None while a span is unread."""
        site, remote = self.site(), self.remote_combo.currentData()
        return overlap(self.spans.span(site), self.spans.span(remote)) if site and remote else None

    def _processing_window(self, site: str):
        """The Process tab's window while the student has set one there for `site`, else None.

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
        """The window choices: whole overlap, the Process tab's window (when set), the QC windows."""
        site = self.site()
        keep = self.window_combo.currentData()
        combo = self.window_combo
        combo.blockSignals(True)
        combo.clear()
        if site is not None:
            common = self.whole_overlap()
            if common is not None:
                combo.addItem(f"whole overlap  {span_text(*common)}", (OVERLAP, *common))
            else:  # computed from the archives' own runs, the same intersection (chunk_impedances)
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
        """While a QC window is the choice, a window of this site loaded anywhere (the tree, the
        Filter Data chooser) becomes it; the whole overlap and the processing window stay put."""
        selection, current = self.state.selection, self.window_combo.currentData()
        if selection is None or selection[0] != self.site() or not current or current[0] != QC:
            return
        for k in range(self.window_combo.count()):
            data = self.window_combo.itemData(k)
            if data and data[0] == QC and (selection[0], *data[1:]) == selection:
                self.window_combo.setCurrentIndex(k)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._read_spans()
        self._fill_windows()  # the Process tab's window may have been set meanwhile
        self._kick()

    # ------------------------------------------------------------- threads

    def compute(self) -> None:
        """Compute the chunk impedances over the chosen window (after any archive read in flight)."""
        site, remote, window = self.site(), self.remote_combo.currentData(), self.window_combo.currentData()
        if not site or not remote or not window or self.scheme is None:
            self.status.setText("pick a site, a remote and a window")
            return
        kind, start, end = window
        self._pending = (site, remote, start, end, self.chunk_s(), kind)
        self._kick()

    @staticmethod
    def describe(kind: str, start, end) -> str:
        """'the whole overlap (43.8 h)', 'the processing window (6.0 h)', 'a QC window (2.0 h)'."""
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
            site, remote, start, end, chunk_s, kind = tag
            thread = ReadThread(_compute, tag, survey, site, self.state.archive_path(site), remote,
                                self.state.archive_path(remote), start, end, self.scheme, chunk_s,
                                report_progress=True, parent=self)
            head = f"computing {site} rr {remote} over {self.describe(kind, start, end)}, {chunk_s:g} s chunks"
            thread.progress.connect(lambda percent, message, head=head: self.status.setText(
                f"{head}: {message} ({percent} %)"))
            thread.result.connect(self._computed)
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
        self._thread = thread  # before acquire: its `changed` re-enters here and must see it
        lock.acquire(self)
        thread.start()

    def _thread_done(self) -> None:
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for anything waiting

    def _windows_read(self, tag, windows) -> None:
        site, path = tag
        if path == self.state.archive_path(site):
            self._windows[site] = list(windows)
            if self.site() == site:
                self._fill_windows()

    def _computed(self, tag, result) -> None:
        if tag[0] != self.site():
            return  # the site changed while it ran
        self.result, self.selected = result, set()
        starts, ends = result["chunk_starts"], result["chunk_ends"]
        hours = (ends[-1] - starts[0]).total_seconds() / 3600.0
        self.status.setText(f"{tag[0]} rr {tag[1]} ({' / '.join(result['archives'])}): {len(starts)} chunks of "
                            f"{tag[4]:g} s over {hours:.1f} h in {result['elapsed_s']:.1f} s -- {MASK_ROUTE}"
                            + (f"  -- {result['notes']}" if result["notes"] else ""))
        self.draw()

    def wait(self) -> None:
        """The window is closing: let a read or compute in flight finish, start no other."""
        self._pending = self._wanted = None
        self.spans.wait_for_read()
        if self._thread is not None:
            self._thread.wait()

    # ------------------------------------------------------------- drawing

    def band(self) -> int | None:
        j = self.band_combo.currentData()
        return None if j is None else int(j)

    def band_periods(self, j: int) -> tuple[float, float, float]:
        """(period, pmin, pmax) of band j, seconds."""
        _level, lo, hi = band_table(self.scheme)
        return 1.0 / np.sqrt(lo[j] * hi[j]), 1.0 / hi[j], 1.0 / lo[j]

    def applies(self, mask: dict, j: int) -> bool:
        return applies(mask, self.band_periods(j)[0])

    def masked_chunks(self, j: int) -> np.ndarray:
        """Per chunk: True when a mask applying to band j overlaps it (`mtproc.crosspower.masked_chunks`,
        the rule `stack_impedance` keeps chunks by)."""
        return masked_chunks(self.result, self.masks, j)

    def draw(self) -> None:
        """The chosen band of the result on every panel (or empty panels without one)."""
        self.items = {}
        for plot in (*self.time_plots, *self.polar_plots.values()):
            plot.clear()
        r, j = self.result, self.band()
        if r is None or j is None:
            self._count()
            return
        t = np.asarray(r["chunk_starts"].asi8, dtype=float) / 1e9
        ok = r["n_windows"][:, j] > 0
        zxy, zyx = r["zxy"][:, j], r["zyx"][:, j]
        with np.errstate(divide="ignore", invalid="ignore"):
            lxy, lyx, lh, le = (np.log10(np.abs(v)) for v in (zxy, zyx, r["h_amp"][:, j], r["e_amp"][:, j]))
        rows = [
            (self.time_plots[0], [(t, lxy, XY_COLOUR, "xy"), (t, lyx, YX_COLOUR, "yx")]),
            (self.time_plots[1], [(t, np.degrees(np.angle(zxy)), XY_COLOUR, None),
                                  (t, np.degrees(np.angle(zyx)), YX_COLOUR, None)]),
            (self.time_plots[2], [(t, r["coh_xy"][:, j], XY_COLOUR, None), (t, r["coh_yx"][:, j], YX_COLOUR, None)]),
            (self.time_plots[3], [(t, lh, theme.B_COLOUR, "|H|"), (t, le, theme.E_COLOUR, "|E|")]),
            (self.polar_plots["xy"], [(lxy, np.degrees(np.angle(zxy)), XY_COLOUR, None)]),
            (self.polar_plots["yx"], [(lyx, np.degrees(np.angle(zyx)), YX_COLOUR, None)]),
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
                item = pg.PlotDataItem(x[good], y[good], pen=None, symbol="o")
                plot.addItem(item)
                self.items.setdefault(plot, []).append((item, x[good], y[good], np.flatnonzero(good), colour))
        period = self.band_periods(j)[0]
        self.time_plots[0].setTitle(f"{r['station']} rr {r['remote']}  "
                                    f"{span_text(r['chunk_starts'][0], r['chunk_ends'][-1])}, "
                                    f"{t.size} chunks  band {period:.4g} s")
        self.restyle()

    def restyle(self) -> None:
        """Filled, hollow (masked) or ringed (selected) spots, from the masks and the selection."""
        j = self.band()
        if self.result is None or j is None:
            self._count()
            return
        masked = self.masked_chunks(j)
        many = len(self.result["chunk_starts"]) > MANY
        size, bigger = (SMALL_SIZE, SMALL_SIZE + 4) if many else (SIZE, SELECTED_SIZE)
        hollow, ring = pg.mkBrush(None), pg.mkPen(theme.CURSOR_COLOUR, width=2.5)  # one object per look
        for entries in self.items.values():
            for item, x, y, idx, colour in entries:
                fill, edge = pg.mkBrush(colour), pg.mkPen(colour, width=1.0 if many else 1.5)
                picked = [int(k) in self.selected for k in idx]
                brushes = [hollow if masked[k] else fill for k in idx]
                pens = [ring if p else edge for p in picked]
                sizes = [bigger if p else size for p in picked]
                item.setData(x, y, pen=None, symbol="o", symbolBrush=brushes, symbolPen=pens, symbolSize=sizes)
        self._count()

    # ------------------------------------------------------------ selecting

    def select_rect(self, panel: str, plot: pg.PlotWidget, rect: QRectF) -> None:
        """The chunks with a spot inside `rect` (`plot`'s view coordinates) become the selection."""
        picked = set()
        for _item, x, y, idx, _colour in self.items.get(plot, []):
            inside = (x >= rect.left()) & (x <= rect.right()) & (y >= rect.top()) & (y <= rect.bottom())
            picked |= {int(k) for k in idx[inside]}
        self.selected, self.selected_on = picked, panel
        self.restyle()

    def mask_selected(self) -> None:
        """One mask per run of consecutive selected chunks."""
        r, j = self.result, self.band()
        if r is None or j is None or not self.selected:
            return
        period, pmin, pmax = self.band_periods(j)
        whole = self.selected_on == "time" and self.all_bands.isChecked()
        runs, run = [], []
        for k in sorted(self.selected):
            if run and k != run[-1] + 1:
                runs.append(run)
                run = []
            run.append(k)
        runs.append(run)
        for run in runs:
            self.masks.append(normalise({
                "start": r["chunk_starts"][run[0]], "end": r["chunk_ends"][run[-1]],
                "bands": "all" if whole else [pmin, pmax],
                "reason": f"{self.selected_on} panel, {period:.4g} s band",
                "found_by": "time" if self.selected_on == "time" else "polar"}))
        self._edited()

    def unmask_selected(self) -> None:
        """Take the selected chunks out of every mask that applies to the band (a mask may split)."""
        r, j = self.result, self.band()
        if r is None or j is None or not self.selected:
            return
        cuts = [(r["chunk_starts"][k], r["chunk_ends"][k]) for k in sorted(self.selected)]
        out = []
        for m in self.masks:
            if not self.applies(m, j):
                out.append(m)
                continue
            pieces = [(utc(m["start"]), utc(m["end"]))]
            for a, b in cuts:
                pieces = [p for s, e in pieces for p in ((s, min(e, a)), (max(s, b), e)) if p[1] > p[0]]
            out += [normalise({**m, "start": s, "end": e}) for s, e in pieces]
        self.masks = out
        self._edited()

    # ---------------------------------------------------------- the list

    def _edited(self) -> None:
        self.masks.sort(key=lambda m: m["start"])
        self.dirty, self.selected = True, set()
        self._fill_table()
        self.restyle()

    def _fill_table(self) -> None:
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
        if item.column() == REASON and item.row() < len(self.masks):
            self.masks[item.row()]["reason"] = item.text()
            self.dirty = True
            self._count()

    def remove_rows(self) -> None:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        if rows:
            self.masks = [m for k, m in enumerate(self.masks) if k not in rows]
            self._edited()

    def save(self) -> None:
        site = self.site()
        if not site or self.state.survey_yaml is None:
            return
        path = save_masks(self.state.survey_yaml, site, self.masks)
        self.dirty = False
        self.status.setText(f"{len(self.masks)} mask(s) of {site} saved to {path.name} -- {MASK_ROUTE}")
        self._count()

    def _count(self) -> None:
        """'2 of 12 chunks masked; 1 mask(s), 0.33 h' (the hours: the union of every mask of the site)."""
        hours, cursor = 0.0, None
        for a, b in sorted((utc(m["start"]), utc(m["end"])) for m in self.masks):
            a = a if cursor is None else max(a, cursor)
            if b > a:
                hours += (b - a).total_seconds() / 3600.0
                cursor = b
        text = f"{len(self.masks)} mask(s), {hours:.2f} h"
        if self.result is not None and self.band() is not None:
            masked = int(self.masked_chunks(self.band()).sum())
            text = f"{masked} of {len(self.result['chunk_starts'])} chunks masked; {text}"
        self.count_label.setText(text + ("  (not saved)" if self.dirty else ""))
