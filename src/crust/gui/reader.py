# -*- coding: utf-8 -*-
"""
Threaded archive reads and the archive lock

A whole-record read of a broadband site, and a full-rate detail read, take
long enough to stall the window, so reads run off the GUI thread. A
`ReadThread` runs one `crust.gui.archive` function and returns its result
with the `tag` it was started with, so the tab can tell which request has
returned.

`ArchiveLock` keeps one archive open at a time across threads. The Time
Series tab's reads and the segment QC worker (`crust.gui.segment_store`)
each `acquire` it before opening an archive and `release` it once the file is
closed; a caller that could not acquire it retries on `changed`. It is a flag
rather than a mutex: it is used on the GUI thread only, and workers signal
back to the GUI thread to release it.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class ReadThread(QThread):
    """Run `fn(*args)` off the GUI thread and emit the result with `tag`.

    Args:
        fn: The read function.
        tag: Any value identifying the request; emitted with the result.
        *args: Arguments of `fn`.
        report_progress (bool): Pass `progress=self.progress.emit` to `fn`.
        parent (QObject | None): Qt parent.
    """

    progress = Signal(int, str)  # (percent, message), if `report_progress`
    result = Signal(object, object)  # (tag, what the read returned)
    failed = Signal(object, str)  # (tag, message)

    def __init__(self, fn, tag, *args, report_progress: bool = False, parent=None):
        super().__init__(parent)
        self.fn, self.tag, self.args = fn, tag, args
        self.report_progress = report_progress

    def run(self) -> None:
        """Call the read function and emit `result` or `failed`."""
        kwargs = {"progress": self.progress.emit} if self.report_progress else {}
        try:
            out = self.fn(*self.args, **kwargs)
        except Exception as exc:  # the archive may be missing, busy or short
            self.failed.emit(self.tag, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(self.tag, out)


class ArchiveLock(QObject):
    """Records which object may have an archive open: one holder, or none."""

    changed = Signal()  # after every acquire and release

    def __init__(self, parent=None):
        super().__init__(parent)
        self.holder = None

    @property
    def busy(self) -> bool:
        """True while someone holds the lock."""
        return self.holder is not None

    def acquire(self, holder) -> bool:
        """Take the lock for `holder`.

        Args:
            holder: The object taking the lock.

        Returns:
            bool: True if `holder` now holds the lock (including when it
            already did); False if another object holds it.
        """
        if self.holder is not None and self.holder is not holder:
            return False
        if self.holder is None:
            self.holder = holder
            self.changed.emit()
        return True

    def release(self, holder) -> None:
        """Release the lock if `holder` holds it."""
        if self.holder is holder:
            self.holder = None
            self.changed.emit()
