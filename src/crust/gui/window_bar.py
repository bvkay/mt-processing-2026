# -*- coding: utf-8 -*-
"""
Processing window bar of the Process tab

`WindowBar` is the processing-window slider. It shows the station's and
the remote's recorded spans as two bars on one UTC time axis with a draggable
region for the processing window, bounded to the union of the two spans and
defaulting to their overlap. The same window appears as two UTC fields, the
start left of the bar and the end right of it, each with the local time
(`Survey.timezone`) below. Above the bar the sync status is shown in the
words of `status_state`, between two round lamps of the status colour.

The window arithmetic is an interval intersection. Spans come from
`site_span`: `crust.gui.archive.load_grid` for an archived site, or
`crust.instruments.span` for a site with raw files only. The Process tab's
summary (`crust.gui.site_map.PairSummary`) reads its hours through `span`,
`known` and `read_spans`.

Spans are read off the GUI thread (`load_grid` opens the site's archive; a
raw site needs only a file listing), in the same way the tree reads its windows:
one `ReadThread` at a time under `State.archive_lock`, the current pair ahead
of other sites, cached per survey. Each read starts one event-loop turn
later, so a window clicked in the tree takes the lock first.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from crust.instruments import span as file_span
from crust.gui.archive import load_grid
from crust.gui.reader import ReadThread
from crust.gui.theme import (
    BAD_COLOUR, HIGHLIGHT, IDLE_COLOUR, MARKER_EDGE, OK_COLOUR, PAIR_REMOTE_COLOUR, REGION_ALPHA,
    WARN_COLOUR,
)

UTC_FMT = "%Y-%m-%d %H:%M"  # what the fields hold and the scripts take


def site_span(survey, site: str, archive, site_dir):
    """Return a site's recorded span from its archive or its raw files.

    Uses the archive when there is one (`load_grid`, the grid the Time Series
    tab lists windows from, so the bar and the tree agree to the sample),
    otherwise the raw file names (`crust.instruments.span` for the site's
    instrument). For B423 files the span runs from the first epoch to the
    last epoch plus the median spacing, as in `scripts/timing_qc.py`.
    Runs in a `ReadThread`.

    Args:
        survey: The open `crust.survey.Survey`.
        site (str): Site name.
        archive: The site's archive path, or None.
        site_dir: The site's raw folder, or None.

    Returns:
        tuple: (first sample, one past the last sample), UTC.

    Raises:
        FileNotFoundError: If the site has neither an archive nor a raw folder.
    """
    if archive is not None and Path(archive).exists():
        grid = load_grid(archive, survey.name, site)
        return grid.t0, grid.t0 + pd.Timedelta(seconds=grid.n_samples / grid.sample_rate)
    if site_dir is not None:
        start, end, _n = file_span(Path(site_dir), survey.instrument_of(site))
        return start, end
    raise FileNotFoundError(f"{site}: no archive and no raw folder")


def to_utc(value) -> pd.Timestamp:
    """Return a UTC-aware Timestamp from anything pandas parses; naive values are taken as UTC."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def overlap(a, b):
    """Return the intersection of two (start, end) spans, or None."""
    if a is None or b is None:
        return None
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if hi > lo else None


class WindowBar(QWidget):
    """Both sites' recorded spans, the processing window over them, and the sync lamps.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    window_changed = Signal(str, str)  # (start, end) UTC text, whenever either moves
    spans_changed = Signal()  # a span was read, or failed to be

    STATION_Y, REMOTE_Y, BAR_H = 1.0, 0.0, 0.6
    LAMP_PX = 14

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.station: str | None = None
        self.remote: str | None = None
        self.spans: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
        self.unreadable: set[str] = set()  # a failed read is not retried this survey
        self.bars: dict[str, pg.BarGraphItem] = {}
        self._queue: list[str] = []
        self._thread: ReadThread | None = None
        self._syncing = False
        self._chosen = False  # True once a window was set by hand or from the Time Series tab

        self.plot = pg.PlotWidget(parent=self, axisItems={"bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0)})
        self.plot.setMinimumHeight(110)
        self.plot.setMaximumHeight(160)
        self.plot.setLabel("bottom", "UTC")
        self.plot.getAxis("left").setWidth(70)
        self.plot.setYRange(-0.6, 1.7, padding=0)
        self.plot.setMouseEnabled(x=True, y=False)
        fill = QColor(HIGHLIGHT)
        fill.setAlpha(REGION_ALPHA)
        self.region = pg.LinearRegionItem(brush=pg.mkBrush(fill), movable=True)
        self.region.setZValue(10)
        self.plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self._region_moved)

        self.start_edit, self.end_edit = QLineEdit(self), QLineEdit(self)
        self.start_local, self.end_local = QLabel("", self), QLabel("", self)
        for edit in (self.start_edit, self.end_edit):
            edit.setPlaceholderText("YYYY-MM-DD HH:MM")
            edit.setFixedWidth(135)
            edit.editingFinished.connect(self._fields_edited)
        for label in (self.start_local, self.end_local):
            label.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.status = QLabel("", self, alignment=Qt.AlignCenter)
        self.lamps = (QLabel(self), QLabel(self))  # round, left and right of the status line
        for lamp in self.lamps:
            lamp.setFixedSize(self.LAMP_PX, self.LAMP_PX)

        status = QHBoxLayout()
        status.addStretch(1)
        for widget in (self.lamps[0], self.status, self.lamps[1]):
            status.addWidget(widget)
        status.addStretch(1)
        row = QHBoxLayout()
        for title, edit, local in (("Window start (UTC)", self.start_edit, self.start_local),
                                   ("Window end (UTC)", self.end_edit, self.end_local)):
            end = QVBoxLayout()
            for widget in (QLabel(title, self), edit, local):
                end.addWidget(widget)
            end.addStretch(1)
            row.addLayout(end)
        row.insertWidget(1, self.plot, 1)  # between the two ends
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(status)
        layout.addLayout(row, 1)

        self.state.archive_lock.changed.connect(self._kick)  # a read may have been waiting
        self._set_status()

    # ------------------------------------------------------------ the spans

    def reload(self) -> None:
        """Forget every span and window after a survey change."""
        self.spans.clear()
        self.unreadable.clear()
        self._queue.clear()
        self.station = self.remote = None
        self._chosen = False
        self.set_sites(None, None)

    def set_sites(self, station: str | None, remote: str | None) -> None:
        """Show two sites, reading their unknown spans in the background ahead of other sites."""
        if station != self.station:
            self._chosen = False  # a new station gets the default window again
        self.station, self.remote = station, remote
        # the read waits one event-loop turn (inside read_spans): a station
        # picked in the tree reaches this tab through `site_changed`, which
        # `State.set_selection` emits before `request_qc`, and the spans
        # give way to the window just clicked
        self.read_spans((station, remote), first=True)
        self.refresh()

    def read_spans(self, sites, first: bool = False) -> None:
        """Queue span reads of the unread `sites`, at the front if `first`.

        Also called by the pair summary for its candidate remotes.
        """
        wanted = [s for s in dict.fromkeys(sites) if s and not self.known(s)]
        if first:
            self._queue[:] = wanted + [s for s in self._queue if s not in wanted]
        else:
            self._queue += [s for s in wanted if s not in self._queue]
        if wanted:
            QTimer.singleShot(0, self._kick)

    def known(self, site) -> bool:
        """True once `site`'s span has been read or has failed."""
        return site in self.spans or site in self.unreadable

    def _kick(self) -> None:
        """Start the next span read if the archive lock is free and no read is running."""
        lock = self.state.archive_lock
        if self._thread is not None or not self._queue or self.state.survey is None:
            return
        if lock.busy and lock.holder is not self:
            return  # the segment worker or the tree has a file open; `changed` calls this again
        site = self._queue.pop(0)
        survey = self.state.survey
        archive = self.state.archive_path(site)
        site_dir = self.state.raw_sites().get(site)
        thread = ReadThread(site_span, site, survey, site, archive, site_dir, parent=self)
        thread.result.connect(self._span_read)
        thread.failed.connect(self._span_failed)
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # set before acquire, since its `changed` re-enters _kick
        lock.acquire(self)
        thread.start()

    def _span_read(self, site, span) -> None:
        """Store a span read and redraw if it belongs to the pair."""
        self.spans[str(site)] = (to_utc(span[0]), to_utc(span[1]))
        if site in (self.station, self.remote):  # another site's span changes no bar
            self.refresh()
        self.spans_changed.emit()

    def _span_failed(self, site, message: str) -> None:
        """Mark a site's span unreadable and report it if it belongs to the pair."""
        self.unreadable.add(str(site))
        if site in (self.station, self.remote):  # another site's failure only means "no span"
            self._paint_status(BAD_COLOUR, f"{site}: {message}")
        self.spans_changed.emit()

    def _read_done(self) -> None:
        """Release the archive lock after a read."""
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for the next site

    def wait_for_read(self) -> None:
        """Block until a span read in flight finishes, dropping queued reads; used on window close."""
        self._queue.clear()
        if self._thread is not None:
            self._thread.wait()

    def span(self, site) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return a site's recorded span, or None if not read."""
        return self.spans.get(site) if site else None

    def union(self):
        """Return the span covering the station and the remote, or None."""
        spans = [s for s in (self.span(self.station), self.span(self.remote)) if s]
        if not spans:
            return None
        return (min(s[0] for s in spans), max(s[1] for s in spans))

    # ------------------------------------------------------------- drawing

    def refresh(self) -> None:
        """Redraw the bars, re-bound the region and, unless a window was chosen, set it to the overlap."""
        for bar in self.bars.values():
            self.plot.removeItem(bar)
        self.bars.clear()
        ticks = []
        for site, y, colour in ((self.station, self.STATION_Y, OK_COLOUR),
                                (self.remote, self.REMOTE_Y, PAIR_REMOTE_COLOUR)):
            span = self.span(site)
            if site is None:
                continue
            ticks.append((y, site if span else f"{site} ..."))
            if span is None:
                continue
            x0, x1 = span[0].timestamp(), span[1].timestamp()
            bar = pg.BarGraphItem(x0=[x0], x1=[x1], y0=[y - self.BAR_H / 2], height=self.BAR_H,
                                  brush=pg.mkBrush(colour), pen=pg.mkPen(MARKER_EDGE))
            self.plot.addItem(bar)
            self.bars[site] = bar
        self.plot.getAxis("left").setTicks([ticks])
        whole = self.union()
        if whole is None:
            self._set_status()
            return
        lo, hi = whole[0].timestamp(), whole[1].timestamp()
        self._syncing = True  # setBounds clamps the region, which is not a user move
        try:
            self.region.setBounds([lo, hi])
        finally:
            self._syncing = False
        self.plot.setXRange(lo, hi, padding=0.02)
        if not self._chosen:
            default = overlap(self.span(self.station), self.span(self.remote)) or self.span(self.station) or whole
            self._set_region(default[0], default[1])
        self._set_status()

    def _set_region(self, start, end) -> None:
        """Move the region without marking the window as chosen, then fill the fields."""
        self._syncing = True
        try:
            self.region.setRegion((to_utc(start).timestamp(), to_utc(end).timestamp()))
        finally:
            self._syncing = False
        self._fill_fields()

    # ------------------------------------------------- the window, both ways

    def window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the processing window as two UTC timestamps, or None when the fields do not form one."""
        try:
            start, end = to_utc(self.start_edit.text().strip()), to_utc(self.end_edit.text().strip())
        except (ValueError, TypeError):
            return None
        return (start, end) if end > start else None

    def window_text(self) -> tuple[str, str]:
        """Return the start and end field texts."""
        return self.start_edit.text().strip(), self.end_edit.text().strip()

    def set_window(self, start: str, end: str) -> None:
        """Set the window, e.g. from the Time Series tab's visible range."""
        self.start_edit.setText(start)
        self.end_edit.setText(end)
        self._fields_edited()

    def _region_moved(self) -> None:
        """Mark the window as chosen when the user drags the region."""
        if self._syncing:
            return
        self._chosen = True
        self._fill_fields()

    def _fill_fields(self) -> None:
        """Fill the fields from the region, rounded to the minute, and emit `window_changed`."""
        lo, hi = self.region.getRegion()
        start = pd.Timestamp(float(lo), unit="s", tz="UTC").round("min")
        end = pd.Timestamp(float(hi), unit="s", tz="UTC").round("min")
        self.start_edit.setText(start.strftime(UTC_FMT))
        self.end_edit.setText(end.strftime(UTC_FMT))
        self._fill_local()
        self._set_status()
        self.window_changed.emit(*self.window_text())

    def _fields_edited(self) -> None:
        """Move the region to the typed window, or update the status if it is not a window."""
        window = self.window()
        self._chosen = True
        if window is not None and self.union() is not None:
            self._set_region(*window)
        else:
            self._fill_local()
            self._set_status()
            self.window_changed.emit(*self.window_text())

    def local_text(self, when) -> str:
        """Return a time in the survey's `timezone:` with its abbreviation for that date, e.g. '18:25 ACST'."""
        tz = self.state.survey.timezone if self.state.survey else "UTC"
        local = to_utc(when).tz_convert(tz)
        return f"{local:%H:%M} {local.tzname()}"

    def _fill_local(self) -> None:
        """Show the local times under the fields."""
        window = self.window()
        self.start_local.setText(self.local_text(window[0]) if window else "")
        self.end_local.setText(self.local_text(window[1]) if window else "")

    # ------------------------------------------------------- the sync lamps

    def status_state(self) -> tuple[str, str]:
        """Return the (colour, wording) of the sync lamps for the current window."""
        if not self.remote:
            return IDLE_COLOUR, "no remote selected - every product here is remote-referenced"
        remote_span, window = self.span(self.remote), self.window()
        if remote_span is None or window is None:
            return IDLE_COLOUR, f"waiting for {self.remote}'s recorded span"
        common = overlap(window, remote_span)
        if common is None:
            return BAD_COLOUR, "no overlap between station and remote"
        covered = (common[1] - common[0]).total_seconds()
        asked = (window[1] - window[0]).total_seconds()
        if covered >= asked - 1.0:
            return OK_COLOUR, f"remote covers the whole window (overlap {covered / 3600:.1f} h)"
        return WARN_COLOUR, f"remote covers {100.0 * covered / asked:.0f} % of the window - adjust it"

    def _set_status(self) -> None:
        """Paint the status for the current window."""
        self._paint_status(*self.status_state())

    def _paint_status(self, colour: str, text: str) -> None:
        """Set the status line and both lamps in one colour."""
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour}; font-weight: bold")
        for lamp in self.lamps:
            lamp.setStyleSheet(f"background-color: {colour}; border-radius: {self.LAMP_PX // 2}px")
