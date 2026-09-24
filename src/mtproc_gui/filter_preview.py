# -*- coding: utf-8 -*-
"""
Filter preview engine of the Filter Data tab

Applies the filter list being edited to the window loaded on the Time Series
tab (or the Filter Data tab's own chooser) off the GUI thread, each time the
list or a form value changes. The result is drawn over the raw data so the
cleaned time series and the filtered PSD can be compared with the raw ones.

* `compute_preview` has no Qt dependency and copies only what it must. The
  window's arrays go through `mtproc.noise.apply_filters_arrays`, the same
  function ingest calls, on four threads. `mtproc.timefreq.psd_ladder` then
  runs on the raw and the filtered arrays, one float32 copy and one thread
  per channel, as on the Spectra tab. The raw ladder is computed once per
  window and reused.
* `FilterPreview` runs one `PreviewWorker` at a time. The latest request
  wins and a result that is no longer the latest is dropped, as in
  `segment_store`. For a `replace` filter whose donor has an archive, the
  donor's window over the same span is read first
  (`mtproc_gui.segment.load_segment`) under `State.archive_lock`; a donor
  without an archive is reported as a provenance line.

`mtproc_gui.filter_views` draws a `PreviewResult`. Results are held in memory
for display and not written to disk.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from mtproc.noise import apply_filters_arrays
from mtproc.timefreq import psd_ladder
from mtproc_gui import theme
from mtproc_gui.segment import REMOTE_COMPS, load_segment

WORKERS = 4  # threads for the filters (scipy releases the GIL) and the ladders


@dataclass
class PreviewResult:
    """One preview: the raw window, the filtered arrays and both PSD ladders.

    Attributes:
        segment: The loaded `Segment`, unmodified.
        filters (list): The filter entries applied.
        filtered (dict | None): float32 array per channel; None with no filters.
        raw_stages (list): PSD ladder of the raw window.
        filtered_stages (list | None): PSD ladder of the filtered window.
        provenance (list[str]): Provenance lines from the filters and donors.
        elapsed_s (float): Compute time in seconds.
    """

    segment: object  # the loaded `Segment`, left unmodified
    filters: list
    filtered: dict | None  # float32 per channel; None with no filters
    raw_stages: list
    filtered_stages: list | None
    provenance: list[str]
    elapsed_s: float


def ladder(arrays: dict, segment) -> list:
    """Compute the PSD ladder of every channel and merge it stage by stage.

    Each channel runs `psd_ladder` on its own float32 copy in its own thread.

    Args:
        arrays (dict): Channel name to samples.
        segment: The `Segment` giving the gaps and sample rate.

    Returns:
        list: (sample rate, frequencies, {channel: PSD}) per ladder stage.
    """
    comps = theme.channel_order(arrays)

    def one(comp):
        return psd_ladder({comp: np.array(arrays[comp], dtype="float32")}, segment.gaps,
                          segment.sample_rate, [comp])

    with ThreadPoolExecutor(WORKERS) as pool:
        per_comp = list(pool.map(one, comps))
    stages: list = []
    for rows in per_comp:
        for level, (fs, freqs, row) in enumerate(rows):
            if level == len(stages):
                stages.append((fs, freqs, {}))
            stages[level][2].update(row)
    return stages


def compute_preview(segment, filters, donors=None, raw_stages=None, notes=()) -> PreviewResult:
    """Filter a window and compute the raw and filtered PSD ladders.

    Args:
        segment: The loaded `Segment`; left unmodified.
        filters (list): filters.yaml entries, applied with `apply_filters_arrays`.
        donors (dict | None): Donor site to channel arrays for `replace`.
        raw_stages (list | None): Raw ladder from an earlier call on the same
            window; computed when None.
        notes: Extra provenance lines placed first.

    Returns:
        PreviewResult: The preview.
    """
    t0 = time.time()
    if raw_stages is None:
        raw_stages = ladder(segment.arrays, segment)
    filtered, filtered_stages, lines = None, None, list(notes)
    if filters:
        out, provenance = apply_filters_arrays(segment.arrays, segment.sample_rate, filters,
                                               tag=segment.station, donors=donors, workers=WORKERS)
        filtered = {c: np.asarray(a, dtype="float32") for c, a in out.items()}
        filtered_stages = ladder(filtered, segment)
        lines += provenance
    return PreviewResult(segment, list(filters), filtered, raw_stages, filtered_stages, lines, time.time() - t0)


class PreviewWorker(QThread):
    """Worker thread that reads replace donors' windows, then runs `compute_preview`.

    Emits `loaded` once the donor archives are closed, then `result` or
    `failed` with the request's serial number.
    """

    loaded = Signal()  # the donors' archives are closed again
    result = Signal(int, object)  # (serial, PreviewResult)
    failed = Signal(int, str)

    def __init__(self, serial, segment, filters, reads, raw_stages, survey_name, parent=None):
        super().__init__(parent)
        self.serial, self.segment, self.filters = serial, segment, filters
        self.reads, self.raw_stages, self.survey = reads, raw_stages, survey_name

    def run(self) -> None:
        """Read donors on the window's sample grid, then compute the preview."""
        seg = self.segment
        try:
            donors, notes = {}, []
            for site, path in self.reads:
                try:
                    donor = load_segment(path, self.survey, site, seg.t0, seg.end, REMOTE_COMPS)
                except ValueError as exc:
                    notes.append(f"donor {site} does not cover this window ({exc})")
                    continue
                if donor.n == seg.n and abs((donor.t0 - seg.t0).total_seconds() * seg.sample_rate) <= 0.5:
                    donors[site] = donor.arrays
                else:
                    notes.append(f"donor {site} is not on this window's sample grid")
            self.loaded.emit()
            out = compute_preview(seg, self.filters, donors, self.raw_stages, notes)
        except Exception as exc:  # a bad cutoff, a donor archive busy
            self.loaded.emit()
            self.failed.emit(self.serial, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(self.serial, out)


class FilterPreview(QObject):
    """Runs one preview worker at a time; the latest request wins.

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QObject | None): Qt parent.
    """

    started = Signal(str)  # "previewing... (notch, cp)"
    ready = Signal(object)  # PreviewResult
    failed = Signal(str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.result: PreviewResult | None = None
        self._serial = 0
        self._pending = None  # (serial, segment, filters) not started yet
        self._thread: PreviewWorker | None = None
        self._raw = None  # (segment, its raw ladder)
        state.archive_lock.changed.connect(self._kick)

    @property
    def busy(self) -> bool:
        """True while a worker runs or a request waits."""
        return self._thread is not None or self._pending is not None

    def request(self, segment, filters) -> None:
        """Queue a preview of `segment` through a copy of `filters`, replacing any pending request."""
        self._serial += 1
        self._pending = (self._serial, segment, copy.deepcopy(list(filters)))
        self._kick()

    def clear(self) -> None:
        """Forget the result; the result of a worker in flight is dropped on return."""
        self._serial += 1
        self._pending = self.result = None

    def _kick(self) -> None:
        """Start the pending request if no worker runs and the archive lock allows the donor reads."""
        if self._thread is not None or self._pending is None or self.state.survey is None:
            return
        serial, segment, filters = self._pending
        donors = sorted({str(s) for f in filters if "replace" in f for s in (f["replace"] or {}).values()})
        reads = [(s, self.state.archive_path(s)) for s in donors if self.state.has_archive(s)]
        lock = self.state.archive_lock
        if reads and lock.busy and lock.holder is not self:
            return  # `changed` calls this again
        self._pending = None
        raw = self._raw[1] if self._raw is not None and self._raw[0] is segment else None
        thread = PreviewWorker(serial, segment, filters, reads, raw, self.state.survey.name, self)
        thread.loaded.connect(lambda: self.state.archive_lock.release(self))
        thread.result.connect(self._on_result)
        thread.failed.connect(self._on_failed)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        if reads:
            lock.acquire(self)
        thread.start()
        self.started.emit(f"previewing... ({', '.join(next(iter(f)) for f in filters) or 'no filters'})")

    def _finish(self, serial: int) -> bool:
        """Release the worker and the lock, start any pending request; True if `serial` is the latest."""
        self._thread = None
        self.state.archive_lock.release(self)
        self._kick()
        return serial == self._serial

    def _on_result(self, serial: int, result: PreviewResult) -> None:
        self._raw = (result.segment, result.raw_stages)
        if self._finish(serial):
            self.result = result
            self.ready.emit(result)

    def _on_failed(self, serial: int, message: str) -> None:
        if self._finish(serial):
            self.failed.emit(message)

    def wait(self) -> None:
        """Block until the worker in flight returns, dropping any pending request; used on window close."""
        self._pending = None
        if self._thread is not None:
            self._thread.wait()
