# -*- coding: utf-8 -*-
"""
Availability chart of the Stacks tab

`AvailabilityChart` draws every survey.yaml site as one row on a UTC time
axis: each run of its archive as two half-height strips, the runs holding hx
and hy above (magnetics blue) and the runs holding ex and ey below
(electrics red). The recipe's field is drawn opaque and the other field
faint; a site the recipe leaves out is drawn grey, with the reason in its
tooltip. The local's name is green and the members' amber. Rows are grouped
under the deployment references (`availability_model.group_rows`), each
reference's runs a faint band behind its group, the reference's name in
bold. Over the rows sit the masks of masks.yaml (an entry over all bands as
a dark segment with a thin red outline, a period band as a dashed light
outline; both read over the blue and the red strips, which a red fill over
the electrics would not) and the nights (local time in the survey's
`timezone:`) as full-height grey bands; the processing window is a
draggable region. With no window chosen and none in the recipe, the window
is the longest stretch of hours at the most candidates, searched first
inside the local's record (its first run's start to its last run's end) and
over every hour when no hour there counts a candidate; the status line says
when the local records nothing in the window, whoever set it. The default
view shows as many rows as fit at 14 px each. Under the rows, x-linked, the
count of candidate members per UTC hour is a step curve with a dashed line at the
recipe's `min_members`; below it the window's UTC fields with local time,
and the settings row: the references, the night, and **Save view**, which
asks the tab to write them to stacks.yaml (`view_save_requested`).

Membership is `mt_workbench.stacks.resolve_members`, called on the GUI thread
with `RunsCache.runs_of`, so it stats the archives and opens none; the
candidates the curve counts are the members of the same call with
``min_overlap_hours=0.0``. The rows are worked out lazily: a change (the
recipe, the window, the references, a read landing) marks them stale, and
they are rebuilt once, when `rows()` or `window()` is next read or on the
next turn of the event loop, so a survey reload that sets the references,
the night, the window and the recipe costs one pass. A pass stats each
archive once and answers `runs_of` from those stats. The runs are read off
the GUI thread: batches of up to 16 stale archives in one `ReadThread`
holding `State.archive_lock`, four h5py attribute reads per archive
(`availability_model.read_runs`), kept in `State.runs_cache`, which the
Process tab's recipe picker reads too. Rows not read yet read
`intersite.NOT_READ` until their batch lands; an archive that does not open
reads "archive unreadable: ..." and is read again on the next `refresh` once
its file changed. Raw folders are never read. Each site's masks, and their
times as seconds for drawing, are loaded in a `ReadThread` once per change
of masks.yaml (after `State.masks_reader` has parsed it), not on every show
or redraw: the Atlas survey's 30,802 masks took 0.46 s per load and 87 ms
per redraw on the GUI thread before [measured by the review]. After `wait()`
(window close) the chart starts no thread.

The chart computes nothing from samples and changes nothing: a click on a
bar emits `bar_clicked(site, time)` and the tab decides what to load.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolTip, QVBoxLayout, QWidget,
)

from mt_workbench import stacks
from mt_workbench.gui import availability_model as model
from mt_workbench.gui.reader import ReadThread
from mt_workbench.gui.theme import (
    B_COLOUR, BAD_COLOUR, E_COLOUR, FOREGROUND, GRID_ALPHA, HIGHLIGHT, IDLE_COLOUR, OK_COLOUR, REGION_ALPHA,
    REMOTE_COLOUR, SURFACE, WARN_COLOUR,
)
from mt_workbench.gui.window_bar import UTC_FMT, to_utc
from mt_workbench.masks import load_masks
from mt_workbench.survey import OBSERVATORY

BATCH = 16  # archives per read thread: about 0.13 s of the archive lock at Nador [inference]
MAX_ROWS = 40  # rows the default view shows before the plot has a height
ROW_PX = 14  # the default view gives each row at least this many pixels, so the names do not overlap
AXIS_W = 92  # px of the left axes, so the two plots line up
FAINT_ALPHA = 90  # of 255: the field the recipe does not take
STRIP_H, STRIP_GAP = 0.40, 0.02  # row units: each field's strip, and the gap between the two
MASK_H = 0.9
NO_REFERENCES = ("No deployment references: name the reference sites (for example RR1, RR2, RR3) and "
                 "Save view")


def _read_batch(cache: model.RunsCache, survey, items) -> dict[str, str]:
    """Read a batch of archives into the cache; return the error text per site whose read failed.

    Runs in the read thread.
    """
    errors = {}
    for site, path in items:
        try:
            cache.read(survey, site, path)
        except Exception as exc:  # a locked, partly written or foreign file: the row says so
            errors[site] = f"{type(exc).__name__}: {exc}"
    return errors


def _mask_times(masks: list) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Return a site's masks as float s since the epoch: {"all": (starts, ends), "band": (starts, ends)}."""
    out = {}
    epoch, second = pd.Timestamp(0, tz="UTC"), pd.Timedelta(seconds=1)
    for key, chosen in (("all", [m for m in masks if m["bands"] == "all"]),
                        ("band", [m for m in masks if m["bands"] != "all"])):
        # ISO8601: masks.normalise writes whole seconds without a fraction, so one list mixes two layouts;
        # divided by a Timedelta, whatever unit pandas 3 parsed the text to (us, not ns)
        times = [(pd.to_datetime([m[end] for m in chosen], utc=True, format="ISO8601") - epoch) / second
                 for end in ("start", "end")]
        out[key] = tuple(np.asarray(t, dtype=float) if len(chosen) else np.zeros(0) for t in times)
    return out


def _read_masks(survey, sites) -> tuple[dict, dict]:
    """Load each site's masks and their times; an entry that does not load is said per site.

    Runs in a read thread, once per change of masks.yaml.

    Returns:
        tuple: ({site: masks or the error text}, {site: `_mask_times`}).
    """
    masks, times = {}, {}
    for site in sites:
        try:
            masks[site] = load_masks(survey, site)
            if masks[site]:
                times[site] = _mask_times(masks[site])
        except Exception as exc:  # a bad entry (Nador P3S6's found_by: dive) or a file that does not parse
            masks[site] = f"masks.yaml entry unreadable: {exc}"
    return masks, times


def _alpha(colour: str, alpha: int) -> QColor:
    """Return a colour with an alpha of 0-255."""
    out = QColor(colour)
    out.setAlpha(alpha)
    return out


class _RowAxis(pg.AxisItem):
    """Left axis that draws each site's name in its own colour, and the references in bold."""

    def __init__(self):
        super().__init__(orientation="left")
        self.styles: dict[str, tuple[str | None, bool]] = {}  # label -> (colour, bold)

    def drawPicture(self, p, axisSpec, tickSpecs, textSpecs) -> None:
        """Draw the axis line and ticks as pyqtgraph does, then each label in its style."""
        super().drawPicture(p, axisSpec, tickSpecs, [])
        font = QFont(self.style["tickFont"]) if self.style["tickFont"] is not None else QFont(p.font())
        bold = QFont(font)
        bold.setBold(True)
        p.setClipRect(self.boundingRect().toAlignedRect())
        for rect, flags, text in textSpecs:
            colour, strong = self.styles.get(text, (None, False))
            p.setFont(bold if strong else font)
            p.setPen(pg.mkPen(colour) if colour else self.textPen())
            # right-aligned: widen to the left so a bold name is not clipped
            p.drawText(QRectF(rect).adjusted(-24, 0, 0, 0), int(flags), text)


class AvailabilityChart(QWidget):
    """Every site's runs, the recipe's members and the window, on one UTC axis.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    window_changed = Signal(object, object)  # (start, end) UTC Timestamps, minute-rounded
    rows_changed = Signal()  # reads landed, or the recipe, the window or the references changed
    view_save_requested = Signal(list, str)  # (references, night) at the Save view click
    bar_clicked = Signal(str, object)  # (site, UTC Timestamp) of a click on one of the site's runs

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.cache = state.runs_cache  # shared with the Process tab's recipe picker
        self._rows: list[model.Row] = []
        self._recipe = None
        self._local: str | None = None
        self._base: str | None = None
        self._references: list[str] = []
        self._night = stacks.DEFAULT_NIGHT
        self._masks: dict[str, list | str] = {}
        self._mask_times: dict[str, dict] = {}  # site -> `_mask_times`, loaded with the masks
        self._masks_key: tuple | None = None  # (serial, masks.yaml stamp) of the masks loaded or loading
        self._masks_thread: ReadThread | None = None
        self._masks_again = False  # masks.yaml changed while a load ran
        self._closing = False  # set by wait(): no thread is started after it
        self._dirty = False  # the rows are stale; `_flush` rebuilds them
        self._waiting_masks = False  # a pass waits for the masks reader's parse
        self._flush_timer = QTimer(self, singleShot=True, interval=0)
        self._flush_timer.timeout.connect(self._flush)
        self._unread: dict[str, tuple] = {}  # site -> (stamp of the file that failed, error text)
        self._no_archive: set[str] = set()  # sites whose raw archive is not there
        self._queue: list[str] = []
        self._in_flight: list[str] = []
        self._thread: ReadThread | None = None
        self._serial = 0  # bumped on reload: a batch of an earlier survey is dropped
        self._chosen = False  # a window was set by the tab, a drag or the fields
        self._syncing = False
        self._extent: tuple[int, int] | None = None
        self._auto_view = True  # fit the view to the rows and the record until the view is panned or zoomed
        self._edges = np.zeros(0, dtype=np.int64)
        self._counts = np.zeros(0, dtype=int)
        self._items: list = []
        self._hover_row = -1
        self._status_text = ""

        self.axis = _RowAxis()
        self.axis.setWidth(AXIS_W)
        self.plot = pg.PlotWidget(parent=self, axisItems={
            "bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0), "left": self.axis})
        self.plot.setLabel("bottom", "UTC")
        self.plot.invertY(True)
        self.plot.showGrid(x=True, y=False, alpha=GRID_ALPHA)
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setMinimumHeight(260)
        fill = _alpha(HIGHLIGHT, REGION_ALPHA)
        self.region = pg.LinearRegionItem(brush=pg.mkBrush(fill), movable=True)
        self.region.setZValue(10)
        self.plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self._region_moving)
        self.region.sigRegionChangeFinished.connect(self._region_moved)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self.plot.scene().sigMouseMoved.connect(self._hover)

        self.curve_plot = pg.PlotWidget(parent=self, axisItems={
            "bottom": pg.DateAxisItem(orientation="bottom", utcOffset=0)})
        self.curve_plot.setXLink(self.plot)
        self.curve_plot.setMaximumHeight(120)
        self.curve_plot.setMinimumHeight(90)
        self.curve_plot.setLabel("left", "members")
        self.curve_plot.getAxis("left").setWidth(AXIS_W)
        self.curve_plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self.curve_plot.setMouseEnabled(x=True, y=False)
        self.curve = pg.PlotDataItem(pen=pg.mkPen(WARN_COLOUR, width=1.5))
        self.curve_plot.addItem(self.curve)
        self.floor_line = pg.InfiniteLine(angle=0, pos=2, pen=pg.mkPen(FOREGROUND, style=Qt.DashLine))
        self.curve_plot.addItem(self.floor_line)
        self.curve_region = pg.LinearRegionItem(brush=pg.mkBrush(fill), movable=False)
        self.curve_region.setZValue(-1)
        self.curve_plot.addItem(self.curve_region)

        self.start_edit, self.end_edit = QLineEdit(self), QLineEdit(self)
        self.start_local, self.end_local = QLabel("", self), QLabel("", self)
        for edit in (self.start_edit, self.end_edit):
            edit.setPlaceholderText("YYYY-MM-DD HH:MM")
            edit.setFixedWidth(135)
            edit.editingFinished.connect(self._fields_edited)
        for label in (self.start_local, self.end_local):
            label.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.refs_edit = QLineEdit(self)
        self.refs_edit.setPlaceholderText("RR1, RR2, RR3")
        self.refs_edit.setToolTip("Deployment references, comma separated: each heads a group of the sites "
                                  "recorded with it")
        self.refs_edit.editingFinished.connect(self._refs_edited)
        self.night_edit = QLineEdit(self)
        self.night_edit.setFixedWidth(110)
        self.night_edit.setToolTip("The night, HH:MM-HH:MM in the survey's local time")
        self.night_edit.editingFinished.connect(self._night_edited)
        self.save_view_button = QPushButton("Save view", self)
        self.save_view_button.setToolTip("Write the references and the night to the chart block of stacks.yaml")
        self.save_view_button.clicked.connect(self._save_view)
        self.hint = QLabel(NO_REFERENCES, self)
        self.hint.setStyleSheet(f"color: {WARN_COLOUR}")
        self.hint.setWordWrap(True)
        self.status = QLabel("", self)
        self.status.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.status.setWordWrap(True)

        fields = QHBoxLayout()
        for title, edit, local in (("Window start (UTC)", self.start_edit, self.start_local),
                                   ("Window end (UTC)", self.end_edit, self.end_local)):
            column = QVBoxLayout()
            for widget in (QLabel(title, self), edit, local):
                column.addWidget(widget)
            fields.addLayout(column)
            fields.addSpacing(12)
        fields.addStretch(1)
        settings = QHBoxLayout()
        settings.addWidget(QLabel("References", self))
        settings.addWidget(self.refs_edit, 1)
        settings.addWidget(QLabel("Night (local)", self))
        settings.addWidget(self.night_edit)
        settings.addWidget(self.save_view_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.hint)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.curve_plot)
        layout.addLayout(fields)
        layout.addLayout(settings)
        layout.addWidget(self.status)

        self.state.archive_lock.changed.connect(self._kick)  # a batch may have been waiting
        self.state.masks_reader.ready.connect(self._masks_ready)
        self.state.archive_changed.connect(self._archive_changed)
        self.plot.getViewBox().sigRangeChangedManually.connect(self._view_moved)
        self.night_edit.setText(self._night)
        self._update_hint()

    # ------------------------------------------------------------ public

    def reload(self) -> None:
        """Forget the recipe, the window, the view settings and the read errors after a survey change.

        What a pass works out (the rows, the record, the hour counts, the
        sites with no archive, the status text) is cleared too, so a draw
        before this survey's first pass shows none of the last survey's.
        """
        self._serial += 1
        self._queue.clear()
        self._unread.clear()
        self._masks, self._mask_times, self._masks_key = {}, {}, None
        self._rows = []  # the last survey's rows are not shown while this one's wait for a pass
        self._no_archive = set()
        self._edges, self._counts = np.zeros(0, dtype=np.int64), np.zeros(0, dtype=int)
        self._status_text = ""
        self._hover_row = -1
        self._recipe = self._local = self._base = None
        self._references = []
        self._night = stacks.DEFAULT_NIGHT
        self._chosen = False
        self._extent = None
        self._auto_view = True
        self.refs_edit.setText("")
        self.night_edit.setText(self._night)
        for edit in (self.start_edit, self.end_edit):
            edit.setText("")
        self._update_hint()
        self.refresh()

    def refresh(self) -> None:
        """Look at every archive again: read the stale ones, retry the unreadable ones, reload changed masks."""
        self._unread.clear()
        self._load_masks()
        self._recompute()

    def set_recipe(self, recipe, local: str | None = None, base: str | None = None) -> None:
        """Show a recipe's members over the chart's window.

        Args:
            recipe (stacks.Recipe | None): The recipe; None shows the runs alone.
            local (str | None): The local site, at the recipe's rate (band recipes).
            base (str | None): The base site (band reference recipes).
        """
        self._recipe, self._local, self._base = recipe, local, base
        floor = 2 if recipe is None or recipe.min_members is None else recipe.min_members
        self.floor_line.setPos(floor)
        self._recompute()

    def set_window(self, start, end) -> None:
        """Set the window without emitting `window_changed`; it then stays until moved.

        Args:
            start, end: UTC times (naive is UTC).
        """
        start, end = to_utc(start), to_utc(end)
        if end <= start:
            return
        self._chosen = True
        self._set_region(start.value / 1e9, end.value / 1e9)
        self._recompute()

    def window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the window as two UTC Timestamps (a default one once the rows are worked out), or None."""
        self._flush()
        return self._fields_window()

    def _fields_window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Return the window in the fields as two UTC Timestamps, or None when they do not form one."""
        try:
            start, end = to_utc(self.start_edit.text().strip()), to_utc(self.end_edit.text().strip())
        except (ValueError, TypeError):
            return None
        return (start, end) if end > start else None

    def rows(self) -> list[model.Row]:
        """Return the rows as drawn, group by group, worked out first when they are stale."""
        self._flush()
        return list(self._rows)

    def set_references(self, names) -> None:
        """Group the rows under these reference sites (not written until Save view)."""
        self._references = [str(n).strip() for n in dict.fromkeys(names or ()) if str(n).strip()]
        self.refs_edit.setText(", ".join(self._references))
        self._update_hint()
        self._recompute()

    def references(self) -> list[str]:
        """Return the reference sites, in group order."""
        return list(self._references)

    def set_night(self, night: str) -> None:
        """Show the nights as "HH:MM-HH:MM" local time (not written until Save view).

        Raises:
            ValueError: From `availability_model.parse_night`.
        """
        model.parse_night(night)
        self._night = str(night).strip()
        self.night_edit.setText(self._night)
        self._redraw()

    def night(self) -> str:
        """Return the night, "HH:MM-HH:MM" local time."""
        return self._night

    def reads_pending(self) -> int:
        """Return the number of archives queued or being read."""
        return len(self._queue) + len(self._in_flight)

    def wait(self) -> None:
        """Stop for good: drop the queued reads, block until the threads in flight end; used on window close.

        The batch's `finished` is still delivered afterwards; with the
        chart closing it starts nothing (no read, no masks load, no rows).
        """
        self._closing = True
        self._queue.clear()
        self._flush_timer.stop()
        for thread in (self._thread, self._masks_thread):
            if thread is not None:
                thread.wait()
        self.state.archive_lock.release(self)

    def showEvent(self, event) -> None:
        """Look at the archives and masks again when shown: a job may have built or changed one."""
        super().showEvent(event)
        if self.state.survey is not None:
            self._load_masks()  # a stat: the masks load again only when masks.yaml changed
            self._recompute()

    def resizeEvent(self, event) -> None:
        """Fit the default view's rows to the new height, unless the view has been panned or zoomed."""
        super().resizeEvent(event)
        if self._auto_view and self._rows:
            self._fit_view(len(self._rows))

    # ------------------------------------------------------------- reads

    def _paths(self, sites) -> dict:
        """Return each site's raw archive path."""
        return {s: self.state.archive_path(s) for s in sites}

    def _queue_reads(self, sites) -> None:
        """Queue reads of stale archives not already queued or in flight; none once closing."""
        if self._closing:
            return
        new = [s for s in sites if s not in self._queue and s not in self._in_flight]
        if new:
            self._queue += new
            QTimer.singleShot(0, self._kick)  # a tree click this turn takes the lock first

    def _kick(self) -> None:
        """Start the next batch if the archive lock is free and no batch is running."""
        lock = self.state.archive_lock
        if self._closing or self._thread is not None or not self._queue or self.state.survey is None:
            return
        if lock.busy and lock.holder is not self:
            return  # another reader has a file open; `changed` calls this again
        batch, self._queue = self._queue[:BATCH], self._queue[BATCH:]
        survey = self.state.survey
        items = list(self._paths(batch).items())
        thread = ReadThread(_read_batch, (self._serial, tuple(batch)), self.cache, survey, items, parent=self)
        thread.result.connect(self._batch_read)
        thread.failed.connect(self._batch_failed)
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # set before acquire, since its `changed` re-enters _kick
        self._in_flight = list(batch)
        lock.acquire(self)
        thread.start()

    def _batch_read(self, tag, errors) -> None:
        """Note which reads of a batch failed; `_read_done` then recomputes the rows."""
        serial, batch = tag
        if serial != self._serial:
            return  # a batch of the survey open before
        paths = self._paths(batch)
        for site in batch:
            if site in errors:
                self._unread[site] = (model.RunsCache.stamp(paths[site]), errors[site])
            else:
                self._unread.pop(site, None)

    def _batch_failed(self, tag, message: str) -> None:
        """Mark a whole batch unreadable when the batch function itself raised."""
        serial, batch = tag
        if serial != self._serial:
            return
        paths = self._paths(batch)
        for site in batch:
            self._unread[site] = (model.RunsCache.stamp(paths[site]), message)

    def _read_done(self) -> None:
        """Release the lock after a batch, mark the rows stale and start the next batch."""
        self._thread = None
        self._in_flight = []
        self._recompute()
        self.state.archive_lock.release(self)  # its `changed` runs _kick for the next batch

    # ------------------------------------------------------------- masks

    def _load_masks(self) -> None:
        """Load each site's masks in a read thread when masks.yaml changed since the last load.

        The masks reader parses the file first (`ready` calls back); the
        load is keyed on the survey and the file's (path, mtime, size), so
        a show or a refresh of an unchanged file costs two stats.
        """
        survey = self.state.survey
        if survey is None or self._closing or not self.state.masks_reader.request():
            return  # the parse runs in the masks reader; `ready` calls back
        key = (self._serial, model.RunsCache.stamp(self.state.masks_reader.path()))
        if key == self._masks_key:
            return
        if self._masks_thread is not None:
            self._masks_again = True  # load again once the one running ends
            return
        self._masks_key = key
        thread = ReadThread(_read_masks, key, survey, list(survey.site_names()), parent=self)
        thread.result.connect(self._masks_read)
        thread.failed.connect(self._masks_failed)
        thread.finished.connect(self._masks_done)
        thread.finished.connect(thread.deleteLater)
        self._masks_thread = thread
        thread.start()

    def _masks_read(self, key, value) -> None:
        """Take a load's masks and their times, unless the survey or the file changed since it started."""
        if key != self._masks_key:
            return
        self._masks, self._mask_times = value
        self._recompute()

    def _masks_failed(self, key, message: str) -> None:
        """Say on every row that the masks could not be loaded."""
        if key != self._masks_key or self.state.survey is None:
            return
        self._masks = {site: f"masks.yaml unreadable: {message}" for site in self.state.survey.site_names()}
        self._mask_times = {}
        self._recompute()

    def _masks_done(self) -> None:
        """Forget the finished load; start another when the file changed meanwhile."""
        self._masks_thread = None
        if self._masks_again:
            self._masks_again = False
            self._load_masks()

    def _masks_ready(self) -> None:
        """Load the masks once the masks reader has parsed the file, and run a pass that waited for it."""
        if self.state.survey is not None:
            self._load_masks()
            if self._dirty:
                self._flush_timer.start()

    # -------------------------------------------------------------- rows

    def _recompute(self) -> None:
        """Mark the rows stale; they are rebuilt once, when read or on the next turn of the event loop."""
        if self._closing:
            return
        self._dirty = True
        self._flush_timer.start()

    def _flush(self) -> None:
        """Rebuild the rows now if they are stale, unless masks.yaml is being parsed.

        While the masks reader parses (3 s for the Atlas survey's 8.1 MB),
        every stat of a pass waits for the parse thread to let go of the
        interpreter: a pass took 1.1 s on the GUI thread then against tens
        of ms after [measured on Atlas, fix round]. The pass waits for the
        reader's `ready` instead (`_masks_ready`).
        """
        if not self._dirty or self._closing:
            return
        if self.state.survey is not None and not self.state.masks_reader.request():
            self._waiting_masks = True
            self._update_status()
            return
        self._waiting_masks = False
        self._dirty = False
        self._flush_timer.stop()
        self._compute()

    def _compute(self) -> None:
        """Rebuild the rows from the cache, queue the stale archives, and redraw.

        Each archive is stat'ed once per pass; `runs_of` answers from those
        stamps, so resolve_members' two calls stat only the archives
        `select_stack` asks the existence of.
        """
        survey = self.state.survey
        self._status_text = ""
        if survey is None:
            self._rows, self._extent = [], None
            self._edges, self._counts = np.zeros(0, dtype=np.int64), np.zeros(0, dtype=int)
            self._redraw()
            return
        sites = survey.site_names()
        paths = self._paths(sites)
        stamps = {site: model.RunsCache.stamp(paths[site]) for site in sites}
        runs, stale = {}, []
        self._no_archive = set()
        for site in sites:
            kept = self.cache.kept(survey, site, stamps[site])
            runs[site] = kept
            if kept is None:
                failed = self._unread.get(site)
                if stamps[site] is None:
                    self._no_archive.add(site)
                elif failed is None or failed[0] != stamps[site]:
                    stale.append(site)
        self._queue_reads(stale)
        starts = [r[0][0] for r in (v["all"] for v in runs.values() if v) if r]
        ends = [r[-1][1] for r in (v["all"] for v in runs.values() if v) if r]
        self._extent = (min(starts), max(ends)) if starts else None

        members, left_out = [], []
        self._edges, self._counts = np.zeros(0, dtype=np.int64), np.zeros(0, dtype=int)
        recipe = self._recipe
        # the window: the one chosen (the tab, a drag, the fields); else the recipe's; else the longest
        # stretch of hours at the most candidates, inside the local's record when candidates count there;
        # else the whole record. A default is not a choice and emits nothing: the tab reads `window()` when
        # it wants it.
        default = None if recipe is None else recipe.window_ns
        local_runs = self._local_runs(runs)
        if recipe is not None:
            kw = dict(local=self._local, base=self._base, runs_of=self.cache.runs_of(survey, stamps))
            try:
                window = (self._window_ns() if self._chosen else default) or self._extent
                if window is None:
                    raise stacks.StacksError("no window yet: the archives are still being read")
                candidates, _ = stacks.resolve_members(recipe, survey, window=window, min_overlap_hours=0.0, **kw)
                names = [c["site"] for c in candidates]
                spans = [r for s in names for r in ((runs.get(s) or {}).get(recipe.field) or [])]
                if spans:
                    lo, hi = min(s for s, _ in spans), max(e for _, e in spans)
                    self._edges, self._counts = model.members_per_hour(runs, names, recipe.field, lo, hi,
                                                                       merge=recipe.engine == "band")
                record = (min(s for s, _ in local_runs), max(e for _, e in local_runs)) if local_runs else None
                default = default or model.best_window(self._edges, self._counts, within=record)
                self._default_window(default)
                window = self._window_ns() or window
                members, left_out = stacks.resolve_members(recipe, survey, window=window, **kw)
                self._status_text = (f"{len(members)} members of {len(candidates)} candidates at "
                                     f"{recipe.sample_rate:g} Hz over the window")
                if local_runs is not None and not model.overlap_ns(local_runs, [tuple(window)]):
                    self._status_text += f"; {self._local} records nothing in the window"
            except stacks.StacksError as exc:
                self._status_text = str(exc)
                members, left_out = [], []
        else:
            self._default_window(None)
        unread = {site: text for site, (_stamp, text) in self._unread.items()}
        rates = {s: survey.sample_rate_of(s) for s in sites}
        rows = model.build_rows(sites, rates, runs, members, left_out, unread, self._group_heads(survey),
                                self._masks)
        changed = rows != self._rows
        self._rows = rows
        self._redraw()
        if changed:  # only on a change, so a listener that sets the recipe again ends there
            self.rows_changed.emit()

    def _local_runs(self, runs) -> list | None:
        """Return every run of the local from a pass's runs, or None with no local or its archive not read.

        Args:
            runs (dict): `read_runs` dict per site, None when not read.

        Returns:
            list | None: (start_ns, end_ns) per run.
        """
        kept = runs.get(self._local) if self._local else None
        return None if kept is None else list(kept.get("all") or [])

    def _default_window(self, window_ns) -> None:
        """Put the region on a default window, or on the whole record, unless a window was chosen."""
        if self._chosen:
            return
        window_ns = window_ns or self._extent
        if window_ns is not None and tuple(window_ns) != self._window_ns():
            self._set_region(window_ns[0] / 1e9, window_ns[1] / 1e9)

    def _group_heads(self, survey) -> list[str]:
        """Return the references that head groups: none when they are only observatories."""
        return [] if self._observatories_only(survey) else list(self._references)

    def _observatories_only(self, survey) -> bool:
        """True when there are no references, or every one is an observatory entry of survey.yaml."""
        if not self._references:
            return True
        entries = (survey.config.get("sites") or {}) if survey is not None else {}
        return all((entries.get(name) or {}).get("instrument") == OBSERVATORY for name in self._references)

    def _update_hint(self) -> None:
        """Show the references hint when no deployment reference heads a group."""
        self.hint.setVisible(self._observatories_only(self.state.survey))

    # ----------------------------------------------------------- drawing

    def _redraw(self) -> None:
        """Draw the rows, the overlays, the curve and the status from the computed state."""
        for item in self._items:
            self.plot.removeItem(item)
        self._items = []
        rows = self._rows
        field = None if self._recipe is None else self._recipe.field
        strips = {key: ([], [], []) for key in ("H_on", "H_off", "E_on", "E_off", "idle")}
        masks = {"all": ([], [], []), "band": ([], [], [])}  # arrays per row: starts, ends, tops
        ticks = []
        styles: dict[str, tuple[str | None, bool]] = {}
        for i, row in enumerate(rows):
            label = row.site
            if row.unread:
                label, colour = f"{row.site} (unreadable)", BAD_COLOUR
            elif row.site in self._no_archive:
                colour = IDLE_COLOUR
            elif row.runs is None:
                label, colour = f"{row.site} ...", IDLE_COLOUR
            elif row.site == self._local:
                colour = OK_COLOUR
            elif row.member:
                colour = WARN_COLOUR
            else:
                colour = None
            ticks.append((i, label))
            styles[label] = (colour, row.is_reference)
            for key, top in (("H", True), ("E", False)):
                y0 = i - STRIP_H - STRIP_GAP / 2 if top else i + STRIP_GAP / 2
                cls = "idle" if row.reason is not None else (f"{key}_on" if field in (None, key) else f"{key}_off")
                for s, e in (row.runs or {}).get(key) or []:
                    x0, x1, y = strips[cls]
                    x0.append(s / 1e9)
                    x1.append(e / 1e9)
                    y.append(y0)
            times = self._mask_times.get(row.site) if row.masks else None
            for key, (starts, ends) in (times or {}).items():
                if len(starts):
                    masks[key][0].append(starts)
                    masks[key][1].append(ends)
                    masks[key][2].append(np.full(len(starts), i - MASK_H / 2))
        self.axis.styles = styles
        self.axis.setTicks([ticks])
        brushes = {"H_on": pg.mkBrush(B_COLOUR), "H_off": pg.mkBrush(_alpha(B_COLOUR, FAINT_ALPHA)),
                   "E_on": pg.mkBrush(E_COLOUR), "E_off": pg.mkBrush(_alpha(E_COLOUR, FAINT_ALPHA)),
                   "idle": pg.mkBrush(IDLE_COLOUR)}
        for cls, (x0, x1, y0) in strips.items():
            self._add_bars(x0, x1, y0, STRIP_H, brushes[cls], None, 1)
        # an all-band mask dark over either field, with a thin red edge; a band mask a dashed light outline
        joined = {key: [np.concatenate(parts) if parts else [] for parts in value] for key, value in masks.items()}
        self._add_bars(*joined["all"], MASK_H, pg.mkBrush(_alpha(SURFACE, 200)), pg.mkPen(BAD_COLOUR, width=1), 3)
        self._add_bars(*joined["band"], MASK_H, pg.mkBrush(None),
                       pg.mkPen(FOREGROUND, width=1.2, style=Qt.DashLine), 3)
        self._draw_references(rows)
        self._draw_nights(len(rows))
        self._draw_separators(rows)
        self._fit_view(len(rows))
        if len(self._counts):
            self.curve.setData(x=self._edges / 1e9, y=self._counts, stepMode="center")
        else:
            self.curve.setData([], [])
        if self._extent is not None:
            self._syncing = True  # setBounds clamps the region, which is not a user move
            try:
                self.region.setBounds([self._extent[0] / 1e9, self._extent[1] / 1e9])
            finally:
                self._syncing = False
        self.curve_region.setRegion(self.region.getRegion())
        self._update_status()

    def _add_bars(self, x0, x1, y0, height, brush, pen, z) -> None:
        """Add one BarGraphItem of many rectangles; nothing for none."""
        if not len(x0):
            return
        item = pg.BarGraphItem(x0=np.asarray(x0), x1=np.asarray(x1), y0=np.asarray(y0), height=height,
                               brush=brush, pen=pen if pen is not None else pg.mkPen(None))
        item.setZValue(z)
        self.plot.addItem(item)
        self._items.append(item)

    def _draw_references(self, rows) -> None:
        """Draw each reference's runs as one faint band behind the rows of its group."""
        x0, x1, y0, heights = [], [], [], []
        groups: dict[str, list[int]] = {}
        for i, row in enumerate(rows):
            if row.group:
                groups.setdefault(row.group, []).append(i)
        for ref, index in groups.items():
            head = next((rows[i] for i in index if rows[i].is_reference), None)
            for s, e in ((head.runs or {}).get("all") or []) if head is not None else []:
                x0.append(s / 1e9)
                x1.append(e / 1e9)
                y0.append(min(index) - 0.5)
                heights.append(len(index))
        if x0:
            item = pg.BarGraphItem(x0=np.asarray(x0), x1=np.asarray(x1), y0=np.asarray(y0),
                                   height=np.asarray(heights, dtype=float),
                                   brush=pg.mkBrush(_alpha(REMOTE_COLOUR, 26)), pen=pg.mkPen(None))
            item.setZValue(-5)
            self.plot.addItem(item)
            self._items.append(item)

    def _draw_nights(self, n_rows: int) -> None:
        """Draw the nights over the record as one item of full-height grey bands."""
        survey = self.state.survey
        if survey is None or self._extent is None or not n_rows:
            return
        try:
            spans = model.night_spans(self._extent[0], self._extent[1], self._night, survey.timezone)
        except ValueError as exc:
            self._status_text = str(exc)
            return
        if not spans:
            return
        item = pg.BarGraphItem(x0=np.array([a for a, _ in spans]) / 1e9, x1=np.array([b for _, b in spans]) / 1e9,
                               y0=-0.5, height=float(n_rows), brush=pg.mkBrush(_alpha(IDLE_COLOUR, 34)),
                               pen=pg.mkPen(None))
        item.setZValue(-10)
        self.plot.addItem(item)
        self._items.append(item)

    def _draw_separators(self, rows) -> None:
        """Draw a line between groups."""
        for i in range(1, len(rows)):
            if rows[i].group != rows[i - 1].group:
                line = pg.InfiniteLine(pos=i - 0.5, angle=0, pen=pg.mkPen(FOREGROUND, width=1, style=Qt.DotLine))
                self.plot.addItem(line)
                self._items.append(line)

    def _rows_in_view(self) -> int:
        """Return how many rows fit the plot at ROW_PX each; MAX_ROWS before the plot has a height."""
        height = self.plot.getViewBox().sceneBoundingRect().height()
        return max(1, int(height // ROW_PX)) if height >= ROW_PX else MAX_ROWS

    def _fit_view(self, n_rows: int) -> None:
        """Show the first rows that fit at ROW_PX each over the whole record, until the view is panned or zoomed."""
        if not self._auto_view:
            return
        self.plot.setYRange(-0.5, max(1, min(n_rows, self._rows_in_view())) - 0.5, padding=0)
        if self._extent is not None:
            self.plot.setXRange(self._extent[0] / 1e9, self._extent[1] / 1e9, padding=0.02)

    def _view_moved(self, *_args) -> None:
        """Keep a manual pan or zoom: stop fitting the view to the record."""
        self._auto_view = False

    def _archive_changed(self, _site: str) -> None:
        """Look at the archives again after a job built or removed one."""
        if self.state.survey is not None:
            self._recompute()

    def _update_status(self) -> None:
        """Say what is being read, what failed and how many members the recipe has."""
        parts = []
        if self._waiting_masks:
            parts.append("waiting for masks.yaml to be parsed")
        pending = self.reads_pending()
        if pending:
            parts.append(f"reading {pending} archives")
        if self._unread:
            parts.append(f"{len(self._unread)} unreadable ({', '.join(sorted(self._unread)[:5])}"
                         f"{', ...' if len(self._unread) > 5 else ''})")
        if self._status_text:
            parts.append(self._status_text)
        self.status.setText("; ".join(parts))

    # ------------------------------------------------- the window, both ways

    def _window_ns(self) -> tuple[int, int] | None:
        """Return the fields' window as ns, or None."""
        window = self._fields_window()
        return None if window is None else (int(window[0].value), int(window[1].value))

    def _set_region(self, lo: float, hi: float) -> None:
        """Move the region by code and fill the fields; no signal."""
        self._syncing = True
        try:
            self.region.setRegion((lo, hi))
        finally:
            self._syncing = False
        self._fill_fields()

    def _region_moving(self) -> None:
        """Follow a drag with the fields and the curve's copy of the region."""
        self.curve_region.setRegion(self.region.getRegion())
        if not self._syncing:
            self._fill_fields()

    def _region_moved(self) -> None:
        """A drag ended: the window is chosen; recompute the rows and tell the tab."""
        if self._syncing:
            return
        self._chosen = True
        self._fill_fields()
        self._recompute()
        window = self._fields_window()
        if window is not None:
            self.window_changed.emit(*window)

    def _fill_fields(self) -> None:
        """Fill the fields from the region, rounded to the minute, with the local times beneath."""
        lo, hi = self.region.getRegion()
        start = pd.Timestamp(float(lo), unit="s", tz="UTC").round("min")
        end = pd.Timestamp(float(hi), unit="s", tz="UTC").round("min")
        self.start_edit.setText(start.strftime(UTC_FMT))
        self.end_edit.setText(end.strftime(UTC_FMT))
        self._fill_local()

    def _fill_local(self) -> None:
        """Show the local times under the fields."""
        window = self._fields_window()
        tz = self.state.survey.timezone if self.state.survey else "UTC"
        for label, when in zip((self.start_local, self.end_local), window or (None, None)):
            local = None if when is None else when.tz_convert(tz)
            label.setText("" if local is None else f"{local:%Y-%m-%d %H:%M} {local.tzname()}")

    def _fields_edited(self) -> None:
        """Move the region to the typed window and tell the tab."""
        window = self._fields_window()
        if window is None:
            self._fill_local()
            return
        start, end = window[0].round("min"), window[1].round("min")
        self._chosen = True
        self._set_region(start.value / 1e9, end.value / 1e9)
        self._recompute()
        self.window_changed.emit(start, end)

    # ---------------------------------------------------- settings and mouse

    def _refs_edited(self) -> None:
        """Take the references typed in the field."""
        names = [n.strip() for n in self.refs_edit.text().replace(";", ",").split(",") if n.strip()]
        if names != self._references:
            self.set_references(names)

    def _night_edited(self) -> None:
        """Take the night typed in the field, or say why not."""
        text = self.night_edit.text().strip()
        if text == self._night:
            return
        try:
            self.set_night(text)
        except ValueError as exc:
            self.status.setText(str(exc))

    def _save_view(self) -> None:
        """Ask the tab to write the references and the night."""
        self._refs_edited()
        self._night_edited()
        self.view_save_requested.emit(self.references(), self.night())

    def _row_at(self, scene_pos) -> tuple[int, float] | None:
        """Return (row index, time in s) under a scene position inside the plot, or None."""
        box = self.plot.getViewBox()
        if not box.sceneBoundingRect().contains(scene_pos):
            return None
        point = box.mapSceneToView(QPointF(scene_pos))
        index = int(round(point.y()))
        return (index, float(point.x())) if 0 <= index < len(self._rows) else None

    def _clicked(self, event) -> None:
        """Emit `bar_clicked` for a left click on one of a row's runs."""
        if event.button() != Qt.LeftButton:
            return
        hit = self._row_at(event.scenePos())
        if hit is None:
            return
        row = self._rows[hit[0]]
        t_ns = int(round(hit[1] * 1e9))
        if any(s <= t_ns <= e for s, e in (row.runs or {}).get("all") or []):
            self.bar_clicked.emit(row.site, pd.Timestamp(t_ns, tz="UTC"))

    def _hover(self, scene_pos) -> None:
        """Show the row's facts in a tooltip when the mouse moves to another row."""
        hit = self._row_at(scene_pos)
        index = -1 if hit is None else hit[0]
        if index == self._hover_row:
            return
        self._hover_row = index
        if index < 0:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(), self._tooltip(self._rows[index]), self.plot)

    def _tooltip(self, row: model.Row) -> str:
        """Return a row's facts: rate, membership or reason, runs, dc level, masks, notes."""
        lines = [f"{row.site}  ({row.rate:g} Hz)" + ("  reference" if row.is_reference else "")]
        if row.member:
            lines.append(f"member: {row.overlap_h:.2f} h of the window")
        elif row.reason:
            lines.append(f"left out: {row.reason}")
        if row.unread:
            lines.append(f"archive unreadable: {row.unread}")
        elif row.site in self._no_archive:
            lines.append("no archive yet")
        elif row.runs is None:
            lines.append("archive not read yet")
        else:
            for key, name in (("H", "hx/hy"), ("E", "ex/ey")):
                spans = row.runs.get(key) or []
                hours = sum(e - s for s, e in spans) / 3.6e12
                lines.append(f"{name}: {len(spans)} runs, {hours:.1f} h")
        if row.dc:
            lines.append("dc level: " + ", ".join(f"{c} {v}" for c, v in row.dc.items()))
        if row.masks_error:
            lines.append(row.masks_error)
        elif row.masks:
            lines.append(f"masks: {len(row.masks)}")
        survey = self.state.survey
        if survey is not None and row.site in survey.site_names():
            try:
                notes = survey.site(row.site).notes
            except ValueError:
                notes = None
            if notes:
                lines.append(f"notes: {notes}")
        return "\n".join(lines)
