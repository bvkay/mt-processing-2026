"""The one loaded segment and its QC, computed off the GUI thread on request.

`SegmentStore` sits on `State` and owns the local `Segment`, the optional
remote `Segment`, the `SegmentQC` they produced and the parameters it was
produced for. `request(...)` does nothing when the result already matches;
otherwise one `SegmentWorker` (a QThread) runs `load_segment` for the local
station, `load_segment` for the remote over the same start and end when one
is named and has an archive, then `compute_segment_qc` -- one worker at a
time, the latest request kept as the single pending one while a worker runs,
and a result that no longer matches the latest request discarded (running /
pending / discard; there is one result, the last one asked for). The local
`Segment` is handed out as soon as it is read, `segment_loaded`, before the
remote is read and the QC computed: the Time Series tab draws it in about a
second while the QC tabs wait for `qc_ready`.

The local channels loaded are the station's declared `channels:` (its own or
the survey's), those the archive holds -- so D02's dead hz column, still in
its old archive, stays off the plots -- and every electric and magnetic one
when the declaration names none of them (`mtproc_gui.channels.display`).

The archive is opened only in the worker's load phase, under
`State.archive_lock`, so the Time Series tab's tree reads and this worker
never have a file open at once: the worker signals `loaded` when the files
are closed and the store releases the lock from the GUI thread while the
maths (which touches no file) carries on. A request made while the lock is
held waits and starts when it is released.

The store also carries the **ladder window** the QC tabs share (`win_s`,
`step_s`, `set_ladder`, `ladder_changed`): the base window and step
`compute_segment_qc` is asked for. Two tabs show spinboxes for it; changing
either changes the store's values (and the other tab's spinboxes) and the
next request, from a Recompute button or a tab coming into view, uses them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QObject, QThread, Signal

from mtproc_gui.segment import REMOTE_COMPS, STEP_S, WIN_S, compute_segment_qc, load_segment


@dataclass(frozen=True)
class QCParams:
    """What one segment QC was, or is to be, computed for."""

    station: str
    start: pd.Timestamp
    end: pd.Timestamp
    remote: str | None
    win_s: float
    step_s: float


class SegmentWorker(QThread):
    """Load the segment (signal it), the remote, signal `loaded`, then compute the QC."""

    segment_loaded = Signal(object, object)  # (params, the local Segment), before the remote
    loaded = Signal(object)  # params: the archives are closed again
    progress = Signal(int, str)
    result = Signal(object, object)  # (params, (segment, remote segment or None, qc))
    failed = Signal(object, str)  # (params, message)

    def __init__(self, params: QCParams, local_path, remote_path, survey_name: str, parent=None,
                 comps=None):
        super().__init__(parent)
        self.params, self.local_path, self.remote_path, self.survey = (
            params, local_path, remote_path, survey_name,
        )
        self.comps = comps  # the station's declared channels; None: every one in the archive

    def run(self) -> None:
        p = self.params
        try:
            self.progress.emit(0, f"loading {p.station}")
            segment = load_segment(self.local_path, self.survey, p.station, p.start, p.end, self.comps)
            self.segment_loaded.emit(p, segment)
            remote, note = None, ""
            if self.remote_path is not None:
                self.progress.emit(0, f"loading remote {p.remote}")
                try:
                    remote = load_segment(
                        self.remote_path, self.survey, p.remote, p.start, p.end, REMOTE_COMPS
                    )
                except ValueError as exc:
                    # the remote's deployment does not cover this window (A07's
                    # first windows start before E08 was out): local pairs only
                    note = f"remote {p.remote} does not cover this window, local pairs only"
                    self.progress.emit(0, note + f" ({exc})")
            self.loaded.emit(p)
            qc = compute_segment_qc(
                segment, remote, win_s=p.win_s, step_s=p.step_s, progress=self.progress.emit
            )
            qc.note = note
        except Exception as exc:  # the window may be outside the record, the archive busy
            self.loaded.emit(p)
            self.failed.emit(p, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(p, (segment, remote, qc))


class SegmentStore(QObject):
    """One segment, one remote, one QC result; recomputed only when asked for something else."""

    qc_started = Signal(str)
    qc_progress = Signal(int, str)
    segment_loaded = Signal(object)  # the local Segment, as soon as it is read
    qc_ready = Signal(object)  # the SegmentQC
    qc_failed = Signal(str)
    ladder_changed = Signal(float, float)  # (win_s, step_s) the tabs' spinboxes follow

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.win_s, self.step_s = float(WIN_S), float(STEP_S)
        self.segment = None
        self.remote = None
        self.result = None
        self.params: QCParams | None = None
        self._running: QCParams | None = None  # wanted next, or in flight
        self._pending: QCParams | None = None  # asked for while one was in flight
        self._thread: SegmentWorker | None = None
        self.state.archive_lock.changed.connect(self._kick)

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def clear(self) -> None:
        """Forget the result (the survey changed); a worker in flight is discarded on return."""
        self.segment = self.remote = self.result = self.params = None
        self._running = self._pending = None

    def set_ladder(self, win_s: float, step_s: float) -> None:
        """The base window and step the next request is computed with."""
        win_s, step_s = float(win_s), float(step_s)
        if (win_s, step_s) != (self.win_s, self.step_s):
            self.win_s, self.step_s = win_s, step_s
            self.ladder_changed.emit(win_s, step_s)

    def request(self, station: str, start, end, remote: str | None, win_s: float, step_s: float) -> bool:
        """Ask for the QC of `station` over [start, end] with `remote`, unless it is already here.

        False when the result already matches (nothing to do), True when a
        worker was started, queued behind the one in flight, or is waiting
        for the archive lock.
        """
        params = QCParams(station, pd.Timestamp(start), pd.Timestamp(end), remote or None,
                          float(win_s), float(step_s))
        if self.result is not None and params == self.params:
            return False
        if self._thread is not None:
            self._pending = None if params == self._running else params  # the latest wins
            return True
        self._running = params
        self._kick()
        return True

    def _kick(self) -> None:
        """Start the run `_running` asks for, when no worker runs and the archive is free."""
        params = self._running
        if params is None or self._thread is not None or self.state.survey is None:
            return
        lock = self.state.archive_lock
        if lock.busy and lock.holder is not self:
            return  # `changed` brings us back here when it is released
        remote_path = None
        if params.remote and self.state.has_archive(params.remote):
            remote_path = self.state.archive_path(params.remote)
        survey = self.state.survey
        declared = (survey.site(params.station).channels if params.station in self.state.configured_sites()
                    else survey.defaults.get("channels"))
        thread = SegmentWorker(
            params, self.state.archive_path(params.station), remote_path, survey.name, self, declared
        )
        thread.segment_loaded.connect(self._on_segment)
        thread.loaded.connect(self._on_loaded)
        thread.progress.connect(self.qc_progress)
        thread.result.connect(self._on_result)
        thread.failed.connect(self._on_failed)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # before acquire: its `changed` re-enters here and must see it
        lock.acquire(self)
        thread.start()
        self.qc_started.emit(f"{params.station} {params.start:%Y-%m-%d %H:%M} to {params.end:%H:%M} UTC")

    def _on_segment(self, params, segment) -> None:
        """The local segment is read: hand it out now, unless a newer request has superseded it."""
        if params == self._running and self._pending is None:
            self.segment = segment
            self.segment_loaded.emit(segment)

    def _on_loaded(self, _params) -> None:
        self.state.archive_lock.release(self)  # the files are closed; the maths needs no lock

    def _finish(self, params) -> bool:
        """Common tail of a result or a failure: is `params` still what is wanted?"""
        self._thread = None
        self.state.archive_lock.release(self)
        if self._pending is not None:
            self._running, self._pending = self._pending, None
            self._kick()
            return False
        wanted = params == self._running
        self._running = None
        return wanted

    def _on_result(self, params, payload) -> None:
        if not self._finish(params):
            return  # superseded, or cleared: discarded
        self.segment, self.remote, self.result = payload
        self.params = params
        self.qc_ready.emit(self.result)

    def _on_failed(self, params, message: str) -> None:
        if self._finish(params):
            self.qc_failed.emit(message)

    def wait(self) -> None:
        """Block until the worker in flight returns and start no other (the window is closing)."""
        self._running = self._pending = None
        if self._thread is not None:
            self._thread.wait()
