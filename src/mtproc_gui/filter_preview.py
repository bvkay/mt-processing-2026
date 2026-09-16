"""The Filter Data tab's preview engine: the loaded window through the filter list, off the GUI thread.

The list being edited is applied to the window loaded on the Time Series
tab (or the tab's own chooser) and drawn over the raw, every time the list
or a form value changes, so the cleaned time series and the filtered PSD
are visible, not just the raw ones.

- `compute_preview` (no Qt) copies nothing it does not have to: the window's
  arrays go through `mtproc.noise.apply_filters_arrays` -- the function ingest
  delegates to, so the preview is the archive's filter, not a lookalike --
  on four threads, and `mtproc.timefreq.psd_ladder` runs on the raw and on the
  filtered arrays (a copy per channel, one thread each), as the Spectra tab's
  ladder does. The raw ladder is computed once per window and reused.
- `FilterPreview` (on the tab) runs it in one `PreviewWorker` at a time; the
  latest request wins and a result that is no longer the latest is dropped,
  as `segment_store` does. A `replace` donor with an archive has its window
  over the same span read first (`mtproc_gui.segment.load_segment`) under
  `State.archive_lock`; a donor without one is a provenance line.

The views that draw a `PreviewResult` are `mtproc_gui.filter_views`. What is
computed is drawn and thrown away; nothing here writes a file.
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
    """One preview: the raw window, what the list made of it, and both PSD ladders."""

    segment: object  # the loaded `Segment`, never modified
    filters: list
    filtered: dict | None  # float32 per channel; None with no filters
    raw_stages: list
    filtered_stages: list | None
    provenance: list[str]
    elapsed_s: float


def ladder(arrays: dict, segment) -> list:
    """`psd_ladder` of each channel on its own float32 copy, one thread each, merged stage by stage."""
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
    """The window through `filters` (`apply_filters_arrays`) and both ladders; `segment` is not modified."""
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
    """Read any replace donor's window (signal `loaded`), then `compute_preview`."""

    loaded = Signal()  # the donors' archives are closed again
    result = Signal(int, object)  # (serial, PreviewResult)
    failed = Signal(int, str)

    def __init__(self, serial, segment, filters, reads, raw_stages, survey_name, parent=None):
        super().__init__(parent)
        self.serial, self.segment, self.filters = serial, segment, filters
        self.reads, self.raw_stages, self.survey = reads, raw_stages, survey_name

    def run(self) -> None:
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
    """One preview worker at a time; the latest request wins."""

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
        return self._thread is not None or self._pending is not None

    def request(self, segment, filters) -> None:
        self._serial += 1
        self._pending = (self._serial, segment, copy.deepcopy(list(filters)))
        self._kick()

    def clear(self) -> None:
        """Forget the result; a worker in flight is dropped on return."""
        self._serial += 1
        self._pending = self.result = None

    def _kick(self) -> None:
        if self._thread is not None or self._pending is None or self.state.survey is None:
            return
        serial, segment, filters = self._pending
        donors = sorted({str(s) for f in filters if "replace" in f for s in (f["replace"] or {}).values()})
        reads = [(s, self.state.archive_path(s)) for s in donors if self.state.has_archive(s)]
        lock = self.state.archive_lock
        if reads and lock.busy and lock.holder is not self:
            return  # `changed` brings us back here
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
        """Block until the worker in flight returns and start no other (the window is closing)."""
        self._pending = None
        if self._thread is not None:
            self._thread.wait()
