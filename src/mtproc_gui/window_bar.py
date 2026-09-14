"""WindowBar: the Process tab's slide bar, borrowed from the MATLAB app's `SlideBar`.

`docs/matlab_app_borrowing.md` says what it is and is not: the station's and
the remote's recorded spans as two bars on one UTC time axis, a draggable
region for the processing window (bounded to the union of the two spans,
defaulting to their overlap), the same window as two UTC fields with the
local time under each (`Survey.timezone`) -- the start at the bar's left end,
the end at its right end -- and above the bar the sync status in the lamps'
wording, centred between two round lamps of its colour.

Nothing here computes a product: the time arithmetic is a set intersection,
and the spans come from `bbmt_gui.archive.load_grid` (an archived site) or
`bbmt.ingest.select_files` (a site that has only its raw B423 files) --
`site_span`, below. The Process tab's summary (`bbmt_gui.site_map.PairSummary`)
reads its hours from `span`, `known` and `read_spans`.

The spans are read off the GUI thread (`load_grid` is 0.66 s for D02, 0.56 s
for E08; a B423 file listing ~1 ms), exactly as the tree reads its windows:
one `ReadThread` at a time under `State.archive_lock`, the pair ahead of any
other site, cached per survey, each read one event-loop turn late so a window
clicked in the tree takes the lock first.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from bbmt.ingest import select_files
from bbmt_gui.archive import load_grid
from bbmt_gui.reader import ReadThread
from bbmt_gui.theme import (
    BAD_COLOUR, HIGHLIGHT, IDLE_COLOUR, MARKER_EDGE, OK_COLOUR, PAIR_REMOTE_COLOUR, REGION_ALPHA,
    WARN_COLOUR,
)

UTC_FMT = "%Y-%m-%d %H:%M"  # what the fields hold and the scripts take
DEFAULT_FILE_SECONDS = 5400  # a B423 file's nominal span, for a site with one file


def site_span(survey, site: str, archive, site_dir):
    """(first sample, one past the last) UTC for a site, from whichever source exists.

    The archive when there is one (`load_grid`: the same grid the Time Series
    tab lists windows off, so the bar and the tree agree to the sample),
    otherwise the raw B423 file names -- first epoch to the last epoch plus
    the median spacing, which is what `scripts/timing_qc.py` and the MATLAB
    app's `getSiteBounds` both do. Runs in a `ReadThread`; raises if neither
    source is there.
    """
    if archive is not None and Path(archive).exists():
        grid = load_grid(archive, survey.name, site)
        return grid.t0, grid.t0 + pd.Timedelta(seconds=grid.n_samples / grid.sample_rate)
    if site_dir is not None:
        files = select_files(Path(site_dir))
        epochs = np.array([int(f.stem) for f in files], dtype="int64")
        spacing = int(np.median(np.diff(epochs))) if epochs.size > 1 else DEFAULT_FILE_SECONDS
        return (pd.Timestamp(int(epochs[0]), unit="s", tz="UTC"),
                pd.Timestamp(int(epochs[-1]) + spacing, unit="s", tz="UTC"))
    raise FileNotFoundError(f"{site}: no archive and no raw folder")


def to_utc(value) -> pd.Timestamp:
    """A UTC-aware Timestamp from anything pandas parses (naive text is UTC)."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def overlap(a, b):
    """The intersection of two (start, end) spans, or None."""
    if a is None or b is None:
        return None
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if hi > lo else None


class WindowBar(QWidget):
    """Both sites' recorded spans, the processing window over them, and the sync lamps."""

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
        """A new survey: forget every span and every window."""
        self.spans.clear()
        self.unreadable.clear()
        self._queue.clear()
        self.station = self.remote = None
        self._chosen = False
        self.set_sites(None, None)

    def set_sites(self, station: str | None, remote: str | None) -> None:
        """Show these two sites; their unknown spans are read in the background, first."""
        if station != self.station:
            self._chosen = False  # a new station gets the default window again
        self.station, self.remote = station, remote
        # the read waits one event-loop turn (inside read_spans): a station
        # picked in the tree reaches this tab through `site_changed`, which
        # `State.set_selection` emits *before* `request_qc`, and the spans
        # always give way to the window the student just clicked
        self.read_spans((station, remote), first=True)
        self.refresh()

    def read_spans(self, sites, first: bool = False) -> None:
        """Queue reads of the unread `sites` (at the front if `first`); the summary asks for its candidates."""
        wanted = [s for s in dict.fromkeys(sites) if s and not self.known(s)]
        if first:
            self._queue[:] = wanted + [s for s in self._queue if s not in wanted]
        else:
            self._queue += [s for s in wanted if s not in self._queue]
        if wanted:
            QTimer.singleShot(0, self._kick)

    def known(self, site) -> bool:
        """True once `site`'s span has been read, or has failed to be."""
        return site in self.spans or site in self.unreadable

    def _kick(self) -> None:
        """Start the next span read, if the archive is free and nothing is running."""
        lock = self.state.archive_lock
        if self._thread is not None or not self._queue or self.state.survey is None:
            return
        if lock.busy and lock.holder is not self:
            return  # the segment worker or the tree has a file open; `changed` brings us back
        site = self._queue.pop(0)
        survey = self.state.survey
        archive = self.state.archive_path(site)
        site_dir = self.state.raw_sites().get(site)
        thread = ReadThread(site_span, site, survey, site, archive, site_dir, parent=self)
        thread.result.connect(self._span_read)
        thread.failed.connect(self._span_failed)
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # before acquire: its `changed` re-enters _kick, which must see it
        lock.acquire(self)
        thread.start()

    def _span_read(self, site, span) -> None:
        self.spans[str(site)] = (to_utc(span[0]), to_utc(span[1]))
        if site in (self.station, self.remote):  # another site's span changes no bar
            self.refresh()
        self.spans_changed.emit()

    def _span_failed(self, site, message: str) -> None:
        self.unreadable.add(str(site))
        if site in (self.station, self.remote):  # another site's failure only means "no span"
            self._paint_status(BAD_COLOUR, f"{site}: {message}")
        self.spans_changed.emit()

    def _read_done(self) -> None:
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for the next site

    def wait_for_read(self) -> None:
        """Let a span read in flight finish (the window is closing)."""
        self._queue.clear()
        if self._thread is not None:
            self._thread.wait()

    def span(self, site) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        return self.spans.get(site) if site else None

    def union(self):
        spans = [s for s in (self.span(self.station), self.span(self.remote)) if s]
        if not spans:
            return None
        return (min(s[0] for s in spans), max(s[1] for s in spans))

    # ------------------------------------------------------------- drawing

    def refresh(self) -> None:
        """Redraw the bars, re-bound the region, and default it to the overlap."""
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
        self._syncing = True  # setBounds clamps the region, which is not the student moving it
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
        self._syncing = True
        try:
            self.region.setRegion((to_utc(start).timestamp(), to_utc(end).timestamp()))
        finally:
            self._syncing = False
        self._fill_fields()

    # ------------------------------------------------- the window, both ways

    def window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """The processing window as two UTC timestamps, or None when the fields are not a window."""
        try:
            start, end = to_utc(self.start_edit.text().strip()), to_utc(self.end_edit.text().strip())
        except (ValueError, TypeError):
            return None
        return (start, end) if end > start else None

    def window_text(self) -> tuple[str, str]:
        return self.start_edit.text().strip(), self.end_edit.text().strip()

    def set_window(self, start: str, end: str) -> None:
        """The Time Series tab's visible range (or any other caller) sets the window."""
        self.start_edit.setText(start)
        self.end_edit.setText(end)
        self._fields_edited()

    def _region_moved(self) -> None:
        if self._syncing:
            return
        self._chosen = True
        self._fill_fields()

    def _fill_fields(self) -> None:
        lo, hi = self.region.getRegion()
        start = pd.Timestamp(float(lo), unit="s", tz="UTC").round("min")
        end = pd.Timestamp(float(hi), unit="s", tz="UTC").round("min")
        self.start_edit.setText(start.strftime(UTC_FMT))
        self.end_edit.setText(end.strftime(UTC_FMT))
        self._fill_local()
        self._set_status()
        self.window_changed.emit(*self.window_text())

    def _fields_edited(self) -> None:
        window = self.window()
        self._chosen = True
        if window is not None and self.union() is not None:
            self._set_region(*window)
        else:
            self._fill_local()
            self._set_status()
            self.window_changed.emit(*self.window_text())

    def local_text(self, when) -> str:
        """'18:25 ACST' -- the survey's `timezone:` and the abbreviation it gives that date."""
        tz = self.state.survey.timezone if self.state.survey else "UTC"
        local = to_utc(when).tz_convert(tz)
        return f"{local:%H:%M} {local.tzname()}"

    def _fill_local(self) -> None:
        window = self.window()
        self.start_local.setText(self.local_text(window[0]) if window else "")
        self.end_local.setText(self.local_text(window[1]) if window else "")

    # ------------------------------------------------------- the sync lamps

    def status_state(self) -> tuple[str, str]:
        """(colour, wording) of the MATLAB sync lamps for the window as it stands."""
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
        self._paint_status(*self.status_state())

    def _paint_status(self, colour: str, text: str) -> None:
        """The status line and both lamps, in one colour."""
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour}; font-weight: bold")
        for lamp in self.lamps:
            lamp.setStyleSheet(f"background-color: {colour}; border-radius: {self.LAMP_PX // 2}px")
