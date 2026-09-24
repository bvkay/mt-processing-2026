# -*- coding: utf-8 -*-
"""
Loaded segment and its QC

`SegmentStore` sits on `State` and holds the local `Segment`, the optional
remote `Segment`, the `SegmentQC` computed from them and the parameters of
that computation. `request(...)` returns at once when the result already
matches. Otherwise a `SegmentWorker` (a QThread) runs `load_segment` for the
local station, `load_segment` for the remote over the same start and end
when a remote with an archive is named, then `compute_segment_qc`. One
worker runs at a time; while it runs, the latest request is kept as the
single pending one, and a result that no longer matches the latest request
is discarded, so the store holds the result of the last request. The local
`Segment` is emitted on `segment_loaded` as soon as it is read, before the
remote is read and the QC computed, so the Time Series tab draws it in about
a second while the QC tabs wait for `qc_ready`.

The local channels loaded are the station's declared `channels:` (its own or
the survey's) that the archive holds, or every electric and magnetic channel
when the declaration names none of them (`mtproc_gui.channels.display`). A
column declared absent, such as a dead hz coil still stored in an older
archive, is therefore left off the plots.

The worker opens archives in its load phase only, under
`State.archive_lock`, so the Time Series tab's tree reads and the worker
never have a file open at the same time. The worker emits `loaded` once the
files are closed and the store releases the lock from the GUI thread while
the computation continues. A request made while the lock is held starts when
it is released.

The store also holds the ladder window the QC tabs share (`win_s`, `step_s`,
`set_ladder`, `ladder_changed`): the base window and step passed to
`compute_segment_qc`. The Spectrogram and Coherence tabs show spin boxes for
it; a change on either updates the store and the other tab, and the next
request (from Recompute or a tab coming into view) uses the new values.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import QObject, QThread, Signal

from mtproc_gui.segment import REMOTE_COMPS, STEP_S, WIN_S, compute_segment_qc, load_segment


@dataclass(frozen=True)
class QCParams:
    """Parameters of one segment QC: station, window, remote and ladder."""

    station: str
    start: pd.Timestamp
    end: pd.Timestamp
    remote: str | None
    win_s: float
    step_s: float


class SegmentWorker(QThread):
    """Worker thread that loads a segment and its remote, then computes the QC.

    Emits `segment_loaded` with the local segment, `loaded` once the archives
    are closed, then `result` or `failed`.

    Args:
        params (QCParams): What to compute.
        local_path: The local station's archive.
        remote_path: The remote's archive, or None.
        survey_name (str): Survey name inside the MTH5.
        parent (QObject | None): Qt parent.
        comps (list[str] | None): The station's declared channels; None
            loads every channel in the archive.
    """

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
        """Load, emit, compute; a remote that does not cover the window leaves local pairs only."""
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
                    # the remote's deployment does not cover this window: local pairs only
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
    """Holds one segment, one remote and one QC result, recomputed when a different one is requested.

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QObject | None): Qt parent.
    """

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
        """True while a worker runs."""
        return self._thread is not None

    def clear(self) -> None:
        """Forget the result, e.g. when the survey changes; a worker in flight is discarded on return."""
        self.segment = self.remote = self.result = self.params = None
        self._running = self._pending = None

    def set_ladder(self, win_s: float, step_s: float) -> None:
        """Set the base window and step for the next request and emit `ladder_changed` if they differ."""
        win_s, step_s = float(win_s), float(step_s)
        if (win_s, step_s) != (self.win_s, self.step_s):
            self.win_s, self.step_s = win_s, step_s
            self.ladder_changed.emit(win_s, step_s)

    def request(self, station: str, start, end, remote: str | None, win_s: float, step_s: float) -> bool:
        """Request the QC of `station` over [start, end] with `remote`.

        Args:
            station (str): Local station.
            start: Window start, UTC.
            end: Window end, UTC.
            remote (str | None): Remote station, or None for local pairs.
            win_s (float): Base window in seconds.
            step_s (float): Base step in seconds.

        Returns:
            bool: False when the held result already matches; True when a
            worker was started, queued behind the one in flight, or is
            waiting for the archive lock.
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
        """Start the requested run when no worker runs and the archive lock is free."""
        params = self._running
        if params is None or self._thread is not None or self.state.survey is None:
            return
        lock = self.state.archive_lock
        if lock.busy and lock.holder is not self:
            return  # `changed` calls this again when it is released
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
        self._thread = thread  # set before acquire, since its `changed` re-enters here
        lock.acquire(self)
        thread.start()
        self.qc_started.emit(f"{params.station} {params.start:%Y-%m-%d %H:%M} to {params.end:%H:%M} UTC")

    def _on_segment(self, params, segment) -> None:
        """Emit the local segment as soon as it is read, unless a newer request supersedes it."""
        if params == self._running and self._pending is None:
            self.segment = segment
            self.segment_loaded.emit(segment)

    def _on_loaded(self, _params) -> None:
        """Release the archive lock once the worker has closed the files."""
        self.state.archive_lock.release(self)  # the files are closed; the maths needs no lock

    def _finish(self, params) -> bool:
        """Finish a run and start any pending request.

        Returns:
            bool: True if `params` is still the latest request.
        """
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
        """Keep a result that is still wanted and emit `qc_ready`."""
        if not self._finish(params):
            return  # superseded, or cleared: discarded
        self.segment, self.remote, self.result = payload
        self.params = params
        self.qc_ready.emit(self.result)

    def _on_failed(self, params, message: str) -> None:
        """Emit `qc_failed` for a failure of the latest request."""
        if self._finish(params):
            self.qc_failed.emit(message)

    def wait(self) -> None:
        """Block until the worker in flight returns, dropping pending requests; used on window close."""
        self._running = self._pending = None
        if self._thread is not None:
            self._thread.wait()
