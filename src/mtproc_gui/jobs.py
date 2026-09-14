"""Run the repo's command-line scripts as subprocesses, one at a time.

Every long job in this GUI is one of the scripts in `scripts/` started with
`QProcess` from the repo root, exactly as a student would type it in a shell.
Nothing is imported from `bbmt` and run in-process, for two reasons: the GUI
must never be the place processing lives, and an MTH5 file must never be open
in two processes at once (HDF5 locking, HANDOVER.md fact 8) -- a queue that
runs a single job at a time is the simplest way to guarantee that.

`JobRunner` owns the queue; `queue_table.QueuePanel` is the widget that shows
it (the table of jobs with their status, plus the merged stdout/stderr log).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

# loguru colours its console output; the log widget is plain text
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Drop the colour escapes loguru writes, so the log reads as plain text."""
    return ANSI_RE.sub("", text)


@dataclass
class Job:
    """One script invocation: what to run, how it went, and everything it said."""

    label: str
    argv: list[str]
    status: str = QUEUED
    exit_code: int | None = None
    output: list[str] = field(default_factory=list)
    # what the Process tab's queue table shows for a process_rr run; None on any other job
    station: str | None = None
    remote: str | None = None
    window: str | None = None
    options: str | None = None

    @property
    def command(self) -> str:
        return " ".join(self.argv)


class JobRunner(QObject):
    """A FIFO queue of subprocesses, at most one running at any moment."""

    queue_changed = Signal()
    job_started = Signal(int)
    job_finished = Signal(int, bool)
    log_line = Signal(str)

    def __init__(self, cwd: str | Path, parent=None):
        super().__init__(parent)
        self.cwd = Path(cwd)
        self.jobs: list[Job] = []
        self.log: list[str] = []
        self._process: QProcess | None = None
        self._current = -1
        self._partial = ""
        self._cancelled = False

    # --------------------------------------------------------- the queue

    def add(self, label: str, argv, **details) -> int:
        """Append a job; returns its index. Does not start anything.

        `details` fill the optional `Job` fields (station, remote, window, options).
        """
        job = Job(label=label, argv=[str(a) for a in argv], **details)
        self.jobs.append(job)
        self.queue_changed.emit()
        return len(self.jobs) - 1

    def run_queue(self) -> None:
        """Start the first queued job, unless one is already running."""
        self._cancelled = False
        if self._process is None:
            self._start_next()

    def reset(self) -> None:
        """Drop every job (cancelling a running one) and clear the log."""
        self.cancel()
        self.jobs.clear()
        self.log.clear()
        self._current = -1
        self.queue_changed.emit()

    def cancel(self) -> None:
        """Kill the running job and stop the queue; queued jobs stay queued."""
        self._cancelled = True
        if self._process is not None:
            job = self.current_job()
            self._append("--- cancelled: " + (job.label if job else "job"))
            self._process.kill()
            self._process.waitForFinished(3000)

    @property
    def running(self) -> bool:
        return self._process is not None

    def current_job(self) -> Job | None:
        return self.jobs[self._current] if 0 <= self._current < len(self.jobs) else None

    # ------------------------------------------------------- the machine

    def _next_queued(self) -> int:
        for i, job in enumerate(self.jobs):
            if job.status == QUEUED:
                return i
        return -1

    def _start_next(self) -> None:
        index = self._next_queued()
        if index < 0 or self._cancelled:
            self._current = -1
            return
        job = self.jobs[index]
        self._current = index
        self._partial = ""

        process = QProcess(self)
        process.setWorkingDirectory(str(self.cwd))
        process.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")  # so the log fills while the job runs
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process

        job.status = RUNNING
        self.queue_changed.emit()
        self._append("$ " + job.command)
        self.job_started.emit(index)
        process.start(job.argv[0], job.argv[1:])

    def _read_output(self) -> None:
        if self._process is None:
            return
        raw = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        text = self._partial + strip_ansi(raw).replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        self._partial = lines.pop()
        for line in lines:
            self._append(line)

    def _append(self, line: str) -> None:
        self.log.append(line)
        job = self.current_job()
        if job is not None:
            job.output.append(line)
        self.log_line.emit(line)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        if self._partial:
            self._append(self._partial)
            self._partial = ""
        index = self._current
        job = self.current_job()
        self._process = None
        if job is not None:
            job.exit_code = exit_code
            job.status = DONE if (exit_code == 0 and not self._cancelled) else FAILED
            self._append(f"--- {job.label}: {job.status} (exit {exit_code})")
            self.queue_changed.emit()
            self.job_finished.emit(index, job.status == DONE)
        self._start_next()

    def _on_error(self, error) -> None:
        """A script that never started (bad path) never emits `finished`."""
        if error != QProcess.FailedToStart:
            return
        index = self._current
        job = self.current_job()
        self._process = None
        if job is not None:
            job.status = FAILED
            self._append(f"--- {job.label}: failed to start ({job.argv[0]})")
            self.queue_changed.emit()
            self.job_finished.emit(index, False)
        self._start_next()
