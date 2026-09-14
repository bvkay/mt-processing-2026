"""QueueTable, QueuePanel and ProductList: the Process tab's view of the one job queue.

The MATLAB app's Process Data tab shows its queue as a table (#, Mode, SS,
RR, MR, Freq, Window). This is that table over `state.runner`, the window's
one `JobRunner`, so every job from every tab is a row: a `process_rr` run
queued by the Process tab fills Station, Remote, Window and Options (the
optional `Job` fields it sets), and any other job shows its label under
Station and "-" in the rest. Under the table is the merged script log,
"Script output", with Cancel (kill the running script; the queued ones stay
queued until Run queue) and Clear log.

`ProductList` is the list under the site map: when a job finishes, the
`.edi` paths in its output that exist are listed, once each, and "Show in
View EDIs" asks for the chosen one to be drawn (the Process tab forwards the
request to the View EDIs tab).

Nothing here runs or computes anything: the table is redrawn from
`runner.jobs` on `queue_changed`, the log appends `log_line`, and the
products are read off a finished job's output.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QListWidget, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from bbmt_gui.jobs import DONE, FAILED, RUNNING, JobRunner
from bbmt_gui.theme import BAD_COLOUR, OK_COLOUR, WARN_COLOUR

COLUMNS = ("#", "Station", "Remote", "Window (UTC)", "Options", "Status")
STATUS_COLOURS = {RUNNING: WARN_COLOUR, DONE: OK_COLOUR, FAILED: BAD_COLOUR}
EDI_RE = re.compile(r"[^\s'\"]+\.edi\b", re.IGNORECASE)


class QueueTable(QTableWidget):
    """One row per job on the runner, in queue order, redrawn whenever the queue changes."""

    def __init__(self, runner: JobRunner, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.runner = runner
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)  # one line a row
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.horizontalHeader()
        for column in range(len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COLUMNS.index("Options"), QHeaderView.Stretch)
        runner.queue_changed.connect(self.refresh)

    def refresh(self) -> None:
        self.setRowCount(len(self.runner.jobs))
        for row, job in enumerate(self.runner.jobs):
            cells = (str(row + 1), job.station or job.label, job.remote or "-",
                     job.window or "-", job.options or "-", job.status)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(job.command)  # the whole command line, as the log prints it
                if column == len(COLUMNS) - 1 and job.status in STATUS_COLOURS:
                    item.setForeground(QColor(STATUS_COLOURS[job.status]))
                self.setItem(row, column, item)
        self.scrollToBottom()


class QueuePanel(QWidget):
    """The queue table over the merged script log, with Cancel and Clear log."""

    def __init__(self, runner: JobRunner, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.table = QueueTable(runner, self)
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setToolTip("kill the running script; the queued ones wait for Run queue")
        self.cancel_button.clicked.connect(runner.cancel)
        self.clear_button = QPushButton("Clear log", self)
        self.clear_button.clicked.connect(self.clear_log)

        header = QHBoxLayout()
        header.addWidget(QLabel("Script output", self))
        header.addStretch(1)
        header.addWidget(self.cancel_button)
        header.addWidget(self.clear_button)
        log = QWidget(self)
        log_layout = QVBoxLayout(log)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addLayout(header)
        log_layout.addWidget(self.log_view)
        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(self.table)
        splitter.addWidget(log)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        runner.log_line.connect(self.log_view.appendPlainText)

    def clear_log(self) -> None:
        self.log_view.clear()


class ProductList(QWidget):
    """The EDIs the jobs wrote, read off their output; "Show in View EDIs" asks for one."""

    show_requested = Signal(object)  # a Path

    def __init__(self, runner: JobRunner, repo_root, parent=None):
        super().__init__(parent)
        self.runner, self.repo_root = runner, Path(repo_root)
        self.products: list[Path] = []
        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(lambda _item: self.show_product())
        self.show_button = QPushButton("Show in View EDIs", self, enabled=False)
        self.show_button.clicked.connect(self.show_product)
        self.list.currentRowChanged.connect(
            lambda row: self.show_button.setEnabled(0 <= row < len(self.products)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Products (EDIs written by these jobs)", self))
        layout.addWidget(self.list, 1)
        layout.addWidget(self.show_button)
        runner.job_finished.connect(self._job_finished)

    def _job_finished(self, index: int, _ok: bool) -> None:
        for line in self.runner.jobs[index].output:
            for token in EDI_RE.findall(line):
                path = Path(token.strip().strip("'\""))
                self.add(path if path.is_absolute() else self.repo_root / path)

    def add(self, path: Path) -> None:
        """List an EDI a job wrote, once, if it is really there."""
        if not path.exists() or path in self.products:
            return
        self.products.append(path)
        self.list.addItem(str(path))
        self.list.setCurrentRow(len(self.products) - 1)

    def show_product(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.products):
            self.show_requested.emit(self.products[row])
