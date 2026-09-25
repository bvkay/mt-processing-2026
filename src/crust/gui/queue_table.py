# -*- coding: utf-8 -*-
"""
Job queue views of the Process tab

`QueueTable`, `QueuePanel` and `ProductList` display the window's
`JobRunner` (`state.runner`); the runner itself starts and stops the jobs.

`QueueTable` shows the queue as a table (#, Station, Remote, Window (UTC),
Options, Status) over `state.runner`. A
`process_rr` run queued by the Process tab fills Station, Remote, Window and
Options from the optional `Job` fields; any other job shows its label under
Station and "-" elsewhere. The table lists processing jobs (process_rr,
build_stack); utility jobs (Build MTH5, the basemap fetch, New survey) report
in the console strip. `QueuePanel` places the processing log, "Processing
output", under the table, with Cancel (kill the running script; queued jobs
wait for Run queue) and Clear log. The table is redrawn from `runner.jobs`
on `queue_changed` and the log appends `log_line`.

`ProductList` is the list under the site map. When a job finishes, every
path its output reports writing in a "wrote <path>" line that exists and
ends in `.edi` or `.png` is listed once. `process_rr.py` logs such a line for
the EDI, the comparison figure and the sidecar JSON, and
`crust.process.process_station` for the EDI. "Show in View EDIs" emits the
chosen path, which the Process tab forwards to the View EDIs tab. Paths are
read from the output because a run's EDI and figure share a stem built from
the local start time (`scripts/process_rr.run_stem`), which the argv alone
does not determine.

@author: ben kay (ben@auscope.org.au)

:license: MIT
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

from crust.gui.jobs import DONE, FAILED, RUNNING, JobRunner
from crust.gui.theme import BAD_COLOUR, OK_COLOUR, WARN_COLOUR

COLUMNS = ("#", "Station", "Remote", "Window (UTC)", "Options", "Status")
STATUS_COLOURS = {RUNNING: WARN_COLOUR, DONE: OK_COLOUR, FAILED: BAD_COLOUR}
# a script's "wrote <path>" line for an EDI or a figure; process_rr.py also logs
# one for the sidecar JSON, which is not matched since View EDIs does not plot it
WROTE_RE = re.compile(r"wrote\s+(\S.*\.(?:edi|png))\s*$", re.IGNORECASE)


class QueueTable(QTableWidget):
    """One row per processing job on the runner, in queue order, redrawn when the queue changes.

    Args:
        runner (JobRunner): The window's job runner.
        parent (QWidget | None): Qt parent.
    """

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
        """Redraw the rows from the runner's processing jobs."""
        # ingest, basemap and new-survey jobs are utility jobs shown in the console strip
        shown = [job for job in self.runner.jobs if job.kind == "processing"]
        self.setRowCount(len(shown))
        for row, job in enumerate(shown):
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
    """The queue table over the processing log, with Cancel and Clear log.

    Args:
        runner (JobRunner): The window's job runner.
        parent (QWidget | None): Qt parent.
    """

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
        header.addWidget(QLabel("Processing output (ingest, basemap and new-survey jobs report in the console strip)", self))
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

        runner.log_line.connect(self._append_processing_line)

    def _append_processing_line(self, line: str) -> None:
        """Append a line of a processing job's output; the console strip shows every job."""
        job = self.runner.current_job()
        if job is not None and job.kind == "processing":
            self.log_view.appendPlainText(line)

    def clear_log(self) -> None:
        """Clear the processing log view."""
        self.log_view.clear()


class ProductList(QWidget):
    """List of the EDIs and figures the jobs wrote, read from their output.

    "Show in View EDIs" or a double-click emits `show_requested` with the
    chosen path.

    Args:
        runner (JobRunner): The window's job runner.
        repo_root: Root that relative paths in the output are resolved against.
        parent (QWidget | None): Qt parent.
    """

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
        layout.addWidget(QLabel("Products (EDIs and figures written by these jobs)", self))
        layout.addWidget(self.list, 1)
        layout.addWidget(self.show_button)
        runner.job_finished.connect(self._job_finished)

    def _job_finished(self, index: int, _ok: bool) -> None:
        """Add every EDI or PNG a finished job reports writing."""
        for line in self.runner.jobs[index].output:
            match = WROTE_RE.search(line)
            if not match:
                continue
            path = Path(match.group(1).strip().strip("'\""))
            self.add(path if path.is_absolute() else self.repo_root / path)

    def add(self, path: Path) -> None:
        """List a product path once, if the file exists, and select it."""
        if not path.exists() or path in self.products:
            return
        self.products.append(path)
        self.list.addItem(str(path))
        self.list.setCurrentRow(len(self.products) - 1)

    def show_product(self) -> None:
        """Emit `show_requested` for the selected product."""
        row = self.list.currentRow()
        if 0 <= row < len(self.products):
            self.show_requested.emit(self.products[row])
