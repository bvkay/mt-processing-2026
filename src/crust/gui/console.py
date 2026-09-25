# -*- coding: utf-8 -*-
"""
Console strip showing backend commands and log output

An always-visible area at the bottom of the window that echoes the
command-line terminal, showing the Python commands the GUI runs and their
output. `ConsoleStrip` is a read-only monospace `QPlainTextEdit`, three lines
tall by default, holding at most `MAX_BLOCKS` lines and scrolled to the
newest one. Its colours come from the application palette set by
`theme.apply`. `MainWindow` places it under the tab widget in a vertical
`QSplitter`, so it can be dragged taller to read a full log; the tabs take
the stretch.

Three sources feed it through the `append(line)` slot:

1. `state.runner.log_line`: every line of the subprocess queue's merged log
   as a terminal shows it, the "$ ..." command line the runner prefixes and
   then stdout and stderr, unfiltered.
2. The in-process `loguru` logger, through `LoguruQtSink`. loguru calls the
   sink as a plain function and the sink re-emits each formatted line as a
   `Signal(str)`. A line logged from a worker thread (`crust.timefreq`'s
   `cascade` and `psd_ladder`, called by `SegmentStore`'s worker) therefore
   reaches the strip on the GUI thread through a queued connection. Output
   from pyqtgraph and Qt does not go through loguru and does not appear.
3. `state.segment_store.qc_started`, prefixed "[segment] ", so a window load
   reads as one line, e.g. "[segment] S01 12:55 to 14:55 UTC".

After `begin_shutdown()`, called from `MainWindow.closeEvent` before the
loguru sink is removed, `append` drops incoming lines, so a queued line
arriving during teardown does not raise.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit

MAX_BLOCKS = 5000
VISIBLE_LINES = 3


class ConsoleStrip(QPlainTextEdit):
    """Read-only monospace log view, three lines tall by default, kept at the newest line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setMaximumBlockCount(MAX_BLOCKS)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)  # the declared property; on a headless test rig the platform's
        self.setFont(font)        # own substitution can still hand back a variable-pitch family
        self.setToolTip("what the backend is running: subprocess commands and output, and the "
                        "in-process log -- drag the splitter above to read more of it")
        self._closing = False

    def sizeHint(self) -> QSize:
        """Height of `VISIBLE_LINES` lines plus the frame."""
        metrics = self.fontMetrics()
        frame = 2 * self.frameWidth()
        height = metrics.lineSpacing() * VISIBLE_LINES + frame + 6
        return QSize(super().sizeHint().width(), height)

    @Slot(str)
    def append(self, line: str) -> None:
        """Add one line and scroll to it; ignored after `begin_shutdown`."""
        if self._closing:
            return
        try:
            self.appendPlainText(line)
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())
        except RuntimeError:
            # the underlying C++ widget can already be gone if a queued signal
            # (a worker thread's loguru line) lands after teardown started
            pass

    def begin_shutdown(self) -> None:
        """Stop accepting lines; called from `MainWindow.closeEvent` before the sink is removed."""
        self._closing = True


class LoguruQtSink(QObject):
    """A loguru sink that re-emits each formatted record as a Qt signal.

    loguru calls a callable sink synchronously on the thread that logged the
    record, which is often the segment store's worker `QThread`. `write`
    emits `line_written`; `MainWindow` connects it to `ConsoleStrip.append`
    with `Qt.QueuedConnection`, so the text lands on the GUI thread.
    """

    line_written = Signal(str)

    def write(self, message) -> None:
        """Emit a formatted loguru message without its trailing newline."""
        # loguru passes a `Message` (a str subclass) already formatted;
        # the trailing newline the format leaves is trimmed
        self.line_written.emit(str(message).rstrip("\n"))
