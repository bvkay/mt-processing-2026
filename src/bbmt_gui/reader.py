"""One `bbmt_gui.archive` read in its own thread, for tabs that draw an MTH5.

A read of a 41 h 1000 Hz site takes a few seconds and a full-rate detail read
about a second; either would freeze the window if run on the GUI thread. A
`ReadThread` runs one `archive` function and brings its result back with the
`tag` it was started with, so the tab can tell which request has returned.

`ArchiveLock` is how the window keeps to **one archive open at a time across
threads**: the Time Series tab's reads and the segment QC worker
(`bbmt_gui.segment_store`) each `acquire` it before opening an archive and
`release` it when the file is closed, and whoever could not get it retries
on `changed`. It is a flag, not a mutex: everything that touches it runs on
the GUI thread (the workers signal back rather than releasing themselves).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class ReadThread(QThread):
    """Run `fn(*args)` off the GUI thread; `tag` comes back with the result."""

    progress = Signal(int, str)  # (percent, message), if `report_progress`
    result = Signal(object, object)  # (tag, what the read returned)
    failed = Signal(object, str)  # (tag, message)

    def __init__(self, fn, tag, *args, report_progress: bool = False, parent=None):
        super().__init__(parent)
        self.fn, self.tag, self.args = fn, tag, args
        self.report_progress = report_progress

    def run(self) -> None:
        kwargs = {"progress": self.progress.emit} if self.report_progress else {}
        try:
            out = self.fn(*self.args, **kwargs)
        except Exception as exc:  # the archive may be missing, busy or short
            self.failed.emit(self.tag, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(self.tag, out)


class ArchiveLock(QObject):
    """Who may have an archive open right now: one holder, or nobody."""

    changed = Signal()  # after every acquire and release

    def __init__(self, parent=None):
        super().__init__(parent)
        self.holder = None

    @property
    def busy(self) -> bool:
        return self.holder is not None

    def acquire(self, holder) -> bool:
        """Take the lock for `holder` (a no-op if it already holds it); False if someone else does."""
        if self.holder is not None and self.holder is not holder:
            return False
        if self.holder is None:
            self.holder = holder
            self.changed.emit()
        return True

    def release(self, holder) -> None:
        """Give the lock back; nothing happens if `holder` does not hold it."""
        if self.holder is holder:
            self.holder = None
            self.changed.emit()
