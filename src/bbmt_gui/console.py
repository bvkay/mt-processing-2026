"""ConsoleStrip: a small always-visible echo of what the backend is doing.

The owner's request, verbatim: "a small two-three line area at the bottom of
our GUI, where it echoes the command line terminal, that way the students can
see the python commands and outputs that are part of the backend that are
running when they click on something." `ConsoleStrip` is a read-only,
monospace `QPlainTextEdit`, three lines tall by default (in the dark theme,
`theme.apply` already having set the application palette every widget draws
with, so nothing here sets a colour of its own), holding at most `MAX_BLOCKS`
lines, always scrolled to the newest one. `MainWindow` puts it under the tab
widget in a vertical `QSplitter`, so a student can drag it taller to read a
full log -- the tabs keep the stretch, the strip only a minimum.

Three sources feed it, all through the `append(line)` slot:

1. `state.runner.log_line` -- every line of the subprocess queue's merged
   log, exactly as a terminal shows it: the "$ ..." command line the runner
   already prefixes, then its stdout/stderr, unfiltered.
2. the in-process backend's own `loguru` logger, through `LoguruQtSink`
   below: a small `QObject` loguru calls as a plain sink, which re-emits
   each formatted line as a `Signal(str)` so a line logged from a worker
   thread (`bbmt.timefreq`'s `cascade` and `psd_ladder`, called off the GUI
   thread by `SegmentStore`'s worker) reaches the strip on the GUI thread
   through a queued connection, not a direct call across threads. Only
   loguru records reach it, so pyqtgraph's and Qt's own console noise --
   neither writes with loguru -- never does.
3. `state.segment_store.qc_started`, prefixed "[segment] " so a window load
   reads as one line, e.g. "[segment] D02 12:55 to 14:55 UTC".

`append` never raises once the strip has been told the window is closing
(`begin_shutdown()`, called from `MainWindow.closeEvent` before the loguru
sink is removed): a line arriving mid-teardown, from a worker thread's
queued connection landing after the widget starts coming down, is dropped
rather than crashing the shutdown.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit

MAX_BLOCKS = 5000
VISIBLE_LINES = 3


class ConsoleStrip(QPlainTextEdit):
    """Read-only, monospace, three lines tall by default, always at the newest line."""

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
        metrics = self.fontMetrics()
        frame = 2 * self.frameWidth()
        height = metrics.lineSpacing() * VISIBLE_LINES + frame + 6
        return QSize(super().sizeHint().width(), height)

    @Slot(str)
    def append(self, line: str) -> None:
        """Add one line and keep the view on the newest one; a no-op once closing."""
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
        """Stop accepting lines: call from `MainWindow.closeEvent` before the sink is removed."""
        self._closing = True


class LoguruQtSink(QObject):
    """A plain loguru sink that re-emits each formatted record as a Qt signal.

    loguru calls a callable sink synchronously, from whatever thread logged
    the record -- here, the segment store's worker `QThread` as often as the
    GUI thread. `write` only emits; the connection to `ConsoleStrip.append`
    is made with `Qt.QueuedConnection` so the text actually lands on the GUI
    thread.
    """

    line_written = Signal(str)

    def write(self, message) -> None:
        # loguru passes a `Message` (a str subclass) already through `format`;
        # only the trailing newline the format string leaves needs trimming
        self.line_written.emit(str(message).rstrip("\n"))
