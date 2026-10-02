# -*- coding: utf-8 -*-
"""
Subprocess job queue for the repo's command-line scripts

Every long job in the GUI is one of the scripts in `scripts/`, started with
`QProcess` from the repo root with the same command line a shell would use.
Processing therefore runs in the scripts, and the queue runs one job at a
time, so an MTH5 file is open in one process at a time as HDF5 file locking
requires.

`JobRunner` owns the queue; `queue_table.QueuePanel` shows it as a table of
jobs with their status plus the merged stdout/stderr log. `add` queues a job;
`run_queue` (the Process tab's Run queue button) runs every queued job in
turn; `run_now` starts one job immediately and alone, for the utility jobs
New survey, the basemap fetch and Build MTH5. Jobs queued before a `run_now`
job keep waiting for Run queue.

@author: ben kay (ben@auscope.org.au)

:license: MIT
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
    """Remove the ANSI colour escapes loguru writes, leaving plain text."""
    return ANSI_RE.sub("", text)


@dataclass
class Job:
    """One script invocation: its command, its status and its output.

    Attributes:
        label (str): Short name shown in the queue and the log.
        argv (list[str]): Command line; `argv[0]` is the executable.
        status (str): One of "queued", "running", "done", "failed".
        exit_code (int | None): The process exit code once finished.
        output (list[str]): Every output line of the job.
        station (str | None): Station of a process_rr run, for the queue table.
        remote (str | None): Remote of a process_rr run.
        window (str | None): Processing window of a process_rr run.
        options (str | None): Options summary of a process_rr run.
        kind (str): "processing" jobs (process_rr, build_stack) appear in the
            Process tab's queue table and script log; "utility" jobs (New
            survey, basemap, Build MTH5) appear in the console strip only.
    """

    label: str
    argv: list[str]
    status: str = QUEUED
    exit_code: int | None = None
    output: list[str] = field(default_factory=list)
    # shown in the Process tab's queue table for a process_rr run; None on any other job
    station: str | None = None
    remote: str | None = None
    window: str | None = None
    options: str | None = None
    # "processing" jobs appear in the Process tab's queue table and script log,
    # "utility" jobs in the console strip only
    kind: str = "processing"

    @property
    def command(self) -> str:
        """The command line as one string."""
        return " ".join(self.argv)


class JobRunner(QObject):
    """A FIFO queue of subprocesses with at most one running.

    Emits `queue_changed` on any change, `job_started(index)`,
    `job_finished(index, ok)` and `log_line(line)` for every output line.

    Args:
        cwd (str | Path): Working directory of every job, the repo root.
        parent (QObject | None): Qt parent.
    """

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
        self._draining = False  # set by Run queue: start the next queued job after each one

    # --------------------------------------------------------- the queue

    def add(self, label: str, argv, **details) -> int:
        """Append a job to the queue without starting it.

        Args:
            label (str): Short name of the job.
            argv: Command line; each item is converted to str.
            **details: Optional `Job` fields (station, remote, window,
                options, kind).

        Returns:
            int: The job's index.
        """
        job = Job(label=label, argv=[str(a) for a in argv], **details)
        self.jobs.append(job)
        self.queue_changed.emit()
        return len(self.jobs) - 1

    def run_queue(self) -> None:
        """Start the first queued job unless one is running; the rest follow in turn."""
        self._cancelled = False
        self._draining = True
        self._start_next()

    def run_now(self, label: str, argv, **details) -> int:
        """Add a job and, if none is running, start it immediately and alone.

        Jobs queued before it stay queued for Run queue, and the runner does
        not continue to them when it finishes. If a job is running, the new
        job joins the queue and runs in turn if Run queue is draining it.

        Args:
            label (str): Short name of the job.
            argv: Command line.
            **details: Optional `Job` fields; `kind` defaults to "utility".

        Returns:
            int: The job's index.
        """
        details.setdefault("kind", "utility")
        index = self.add(label, argv, **details)
        if self._process is None:
            self._cancelled = self._draining = False
            self._start(index)
        return index

    def reset(self) -> None:
        """Cancel a running job, drop every job and clear the log."""
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
        """True while a job's process is running."""
        return self._process is not None

    def current_job(self) -> Job | None:
        """The running or last started job, or None."""
        return self.jobs[self._current] if 0 <= self._current < len(self.jobs) else None

    # ------------------------------------------------------- the machine

    def _next_queued(self) -> int:
        """Index of the first queued job, or -1."""
        for i, job in enumerate(self.jobs):
            if job.status == QUEUED:
                return i
        return -1

    def _start_next(self) -> None:
        """Start the next queued job while Run queue is draining and nothing is running."""
        if self._process is not None:
            return  # a job_finished slot has started one already (run_now)
        index = self._next_queued()
        if index < 0 or self._cancelled or not self._draining:
            self._current = -1
            self._draining = False
            return
        self._start(index)

    def _start(self, index: int) -> None:
        """Start job `index` as a QProcess with merged output and unbuffered Python."""
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
        """Split new process output into lines, keeping a trailing partial line."""
        if self._process is None:
            return
        raw = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        text = self._partial + strip_ansi(raw).replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        self._partial = lines.pop()
        for line in lines:
            self._append(line)

    def _append(self, line: str) -> None:
        """Add a line to the log and the current job's output and emit `log_line`."""
        self.log.append(line)
        job = self.current_job()
        if job is not None:
            job.output.append(line)
        self.log_line.emit(line)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        """Record the job's exit status, emit `job_finished` and start the next job."""
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
        """Mark a job that failed to start as failed.

        A process that never starts (for example a bad path) emits no
        `finished`, so the job is closed here.
        """
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
