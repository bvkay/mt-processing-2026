"""Process tab: pick a pair, pick a window, queue the scripts that make the products.

Laid out as the MATLAB app's Process Data tab: (1) station, remote and
the summary (`site_map.PairSummary`); (2) the slide bar, full width
(`window_bar.WindowBar`: start field at its left end, end field at its right,
the sync status centred above between two lamps); (3) Add to queue, Run
queue, Reset queue | Build stack; (4) the Aurora options
(`stack_builder.RunOptions`); (5) the queue table over the script log
(`queue_table.QueuePanel`). Beside rows 3-5: the site map
(`site_map.SiteMap`), the stack builder and the Products list. Timing check,
Site QC figures and Fetch basemap are left off this tab: the scripts stay
on the command line, and the basemap is fetched on survey open.

Every button is one command line from README.md's table, queued through
`mtproc_gui.jobs.JobRunner` and run from the repo root:

    Add to queue     scripts/process_rr.py <survey.yaml> <station> <remote> [start] [end]
                                           [--min-period ...] [--no-filters] [--no-masks] [--tag ...]
    Build stack      scripts/build_stack.py <survey.yaml> <name> <start> <end> <members...>

A band option reaches the command line only when it differs from the survey's
`processing:` block, so a default run reads exactly as it always did.
`process_rr.py` also does the raw ingest (as the Time Series tab's Build MTH5
does for one site) and, unless told not to, builds each site's filtered
variant on top of it (`mtproc.ingest.processing_archive`), and this is where
"use declared filters" can be turned off (`--no-filters`: both sites are
processed from their raw archives outright). Likewise "apply masks.yaml"
(on by default; its label counts each site's `masks.yaml` entries for the
pair, refreshed when the pair changes, the survey is opened and the tab is
shown, since masks are saved on the Cross-powers tab): process_rr applies
the station's masks and the remote site's; off adds `--no-masks`, ignoring
both. A remote is always required:
there is no single-station product (HANDOVER.md, "Decisions made").

**Queuing a job never starts it**, as the legacy MATLAB field app kept "add
to Queue" and "Process Queue" separate: Add to queue and Build stack only
call `JobRunner.add` (`_queue`, below); only **Run queue** runs them.
`status_label` reads "N job(s) queued - press Run queue" while jobs wait and
the queue is idle (`_queue_status`, `_refresh_status`).

The queue belongs to `State`: every tab queues on the same `state.runner`, so
every job is a row of the table, and "Reset queue" is `JobRunner.reset`. When
a run finishes, the EDI and figure paths its output reports writing (a
"wrote <path>" line) that exist go in the **Products** list, and "Show in
View EDIs" puts the chosen EDI, with its lemimt reference, on the View EDIs
tab. The comparison figure is only ever listed, never displayed here: nothing
in this tab shows a PNG.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from mtproc_gui.jobs import QUEUED
from mtproc_gui.queue_table import ProductList, QueuePanel
from mtproc_gui.site_map import PairSummary, SiteMap
from mtproc_gui.stack_builder import RunOptions, StackBuilder
from mtproc_gui.window_bar import WindowBar


class ProcessTab(QWidget):
    """Station + remote + window + options -> the scripts that make the products."""

    show_edi_requested = Signal(object)  # a Path: put it on the View EDIs tab

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.runner = state.runner  # the window's one queue, owned by State
        self._remote_station = None
        self._stack_jobs: dict[int, str] = {}

        self.station_combo = QComboBox(self, minimumWidth=140)
        self.station_combo.currentIndexChanged.connect(self._station_changed)
        self.remote_combo = QComboBox(self, minimumWidth=140)
        self.remote_combo.currentIndexChanged.connect(self._remote_changed)
        self.site_map = SiteMap(state, self)
        self.site_map.setMinimumHeight(340)
        self.window_bar = WindowBar(state, self)
        self.summary = PairSummary(state, self.site_map, self.window_bar, self)
        self.options = RunOptions(state, self)
        self.stack_builder = StackBuilder(state, self.window_bar, self)
        self.stack_builder.members_changed.connect(lambda _m: self._paint_map())
        self.stack_builder.build_requested.connect(self.queue_stack)

        self.add_button = self._button("Add to queue", self.queue_process,
                                       "process_rr.py: ingest both sites, remote-referenced TF, EDI")
        self.run_button = self._button("Run queue", self.runner.run_queue, "start the next queued job")
        self.reset_button = self._button("Reset queue", self.reset_queue,
                                         "cancel the running job, clear the queue and the log")
        self.build_button = self._button("Build stack", self.stack_builder.build,
                                         "build_stack.py: the stacked remote set up on the right")
        self.status_label = QLabel("", self, wordWrap=True)

        self.job_panel = QueuePanel(self.runner, self)
        self.product_panel = ProductList(self.runner, state.repo_root, self)
        self.product_panel.show_requested.connect(self.show_edi_requested)
        self.show_button = self.product_panel.show_button

        self._build_layout()
        self.runner.job_finished.connect(self._job_finished)
        self.runner.queue_changed.connect(self._refresh_status)
        self.state.site_changed.connect(self.select_station)

    def _button(self, text: str, slot, tip: str) -> QPushButton:
        button = QPushButton(text, self, toolTip=tip)
        button.clicked.connect(slot)
        return button

    # --------------------------------------------------------- the layout

    def _build_layout(self) -> None:
        """The MATLAB Process Data tab's rows, top to bottom, the map column beside rows 3-5."""
        pair = QGridLayout()
        pair.addWidget(QLabel("Station to process", self), 0, 0)
        pair.addWidget(self.station_combo, 1, 0)
        pair.addWidget(QLabel("Remote reference", self), 0, 1)
        pair.addWidget(self.remote_combo, 1, 1)
        pair.addWidget(self.summary, 0, 2, 3, 1)
        pair.setRowStretch(2, 1)
        pair.setColumnStretch(2, 1)
        pair.setHorizontalSpacing(24)

        buttons = QHBoxLayout()
        separator = QFrame(self, frameShape=QFrame.VLine, frameShadow=QFrame.Sunken)
        for widget in (self.add_button, self.run_button, self.reset_button, separator, self.build_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        left = QWidget(self)
        rows = QVBoxLayout(left)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.addLayout(buttons)
        rows.addWidget(self.status_label)
        rows.addWidget(self.options)
        rows.addWidget(self.job_panel, 1)

        right = QWidget(self)
        side = QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.site_map, 3)  # the map wins the height, never under 340 px
        side.addWidget(self.stack_builder, 2)
        side.addWidget(self.product_panel, 1)

        lower = QSplitter(Qt.Horizontal, self)
        lower.addWidget(left)
        lower.addWidget(right)
        lower.setStretchFactor(0, 3)
        lower.setStretchFactor(1, 2)
        inner = QWidget(self)
        column = QVBoxLayout(inner)
        column.addLayout(pair)
        column.addWidget(self.window_bar)
        column.addWidget(lower, 1)
        area = QScrollArea(self, widgetResizable=True)  # a short laptop screen scrolls, not clips
        area.setWidget(inner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

    # --------------------------------------------------------- the lists

    def reload(self) -> None:
        """Repopulate everything from the survey: sites, map, spans, band defaults."""
        self.options.reload()
        self.station_combo.blockSignals(True)
        self.station_combo.clear()
        for name in sorted(self.state.raw_sites()):
            self.station_combo.addItem(name, name)
        self.station_combo.blockSignals(False)
        self.site_map.reload()
        self.window_bar.reload()
        self._remote_station = None
        if self.state.site:
            self.select_station(self.state.site)
        self._fill_remotes()
        self.stack_builder.set_station(self.station_combo.currentData())
        self._sites_changed()

    def _fill_remotes(self) -> None:
        """Raw sites plus stacked archives; `survey.yaml`'s `remote:` wins."""
        station = self.station_combo.currentData()
        previous = self.remote_combo.currentData()
        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        for display, name in self.state.remote_choices(station):
            self.remote_combo.addItem(display, name)
        # on a new station the site's declared `remote:` is the default; while
        # the station stays put, a remote the student picked by hand is kept
        declared = self.state.default_remote(station) if station != self._remote_station else None
        self._remote_station = station
        wanted = declared or previous
        if wanted is not None:
            index = self.remote_combo.findData(wanted)
            if index >= 0:
                self.remote_combo.setCurrentIndex(index)
        self.remote_combo.blockSignals(False)

    def _station_changed(self, _index: int) -> None:
        station = self.station_combo.currentData()
        self._fill_remotes()
        self.stack_builder.set_station(station)
        self._sites_changed()
        if station:
            self.state.set_site(station)

    def _remote_changed(self, _index: int) -> None:
        self._sites_changed()

    def _sites_changed(self) -> None:
        """The pair moved: repaint the map, ask for the spans, redo the summary, re-enable the buttons."""
        station, remote = self.station_combo.currentData(), self.remote_combo.currentData()
        self._paint_map()
        self.window_bar.set_sites(station, remote)
        self.summary.refresh()
        self._update_enabled()
        self.options.describe_filters(station, remote)
        self.options.describe_masks(station, remote)

    def showEvent(self, event) -> None:
        """Recount the masks: they are saved on the Cross-powers tab while this one is hidden."""
        super().showEvent(event)
        self.options.describe_masks(self.station_combo.currentData(), self.remote_combo.currentData())

    def _paint_map(self) -> None:
        self.site_map.set_roles(self.station_combo.currentData(), self.remote_combo.currentData(),
                                self.stack_builder.members())

    def select_station(self, name: str) -> None:
        index = self.station_combo.findData(name)
        if index >= 0 and index != self.station_combo.currentIndex():
            self.station_combo.setCurrentIndex(index)

    def _update_enabled(self) -> None:
        ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
        self.add_button.setEnabled(ready)
        self._refresh_status()

    def _queue_status(self) -> str | None:
        """'N job(s) queued - press Run queue' while jobs wait and the queue is idle; else None."""
        queued = sum(1 for job in self.runner.jobs if job.status == QUEUED)
        if queued and not self.runner.running:
            return f"{queued} job(s) queued - press Run queue"
        return None

    def _refresh_status(self) -> None:
        """The queued-jobs notice takes priority over the station/remote reminder."""
        text = self._queue_status()
        if text is None:
            ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
            text = "" if ready else (
                "A station and a remote are both required: every product here is "
                "remote-referenced (adjacent site, dedicated remote, or a stack)."
            )
        self.status_label.setText(text)

    @property
    def products(self) -> list[Path]:
        """The EDIs the jobs wrote, as listed under the map."""
        return self.product_panel.products

    # the Time Series tab's "Use visible range as processing window" lands here
    def set_window(self, start: str, end: str) -> None:
        self.window_bar.set_window(start, end)

    @property
    def start_edit(self) -> QLineEdit:
        return self.window_bar.start_edit

    @property
    def end_edit(self) -> QLineEdit:
        return self.window_bar.end_edit

    # ------------------------------------------------------- queue a job

    def _pair(self):
        """(survey.yaml, station, remote) or None with a message box."""
        if self.state.survey_yaml is None:
            QMessageBox.warning(self, "No survey", "Open a survey.yaml first.")
            return None
        station = self.station_combo.currentData()
        remote = self.remote_combo.currentData()
        if not station or not remote:
            QMessageBox.warning(self, "Station and remote", "Pick a station and a remote.")
            return None
        return str(self.state.survey_yaml), station, remote

    def _window(self) -> list[str] | None:
        """The optional [start, end] arguments as the scripts take them."""
        start, end = self.window_bar.window_text()
        if end and not start:
            QMessageBox.warning(self, "Window", "process_rr.py takes start before end.")
            return None
        return [text for text in (start, end) if text]

    def _queue(self, label: str, argv, **details) -> int:
        """Add the job to `state.runner`'s queue; it does not start (Run queue does)."""
        return self.runner.add(label, argv, **details)

    def queue_process(self) -> list[str] | None:
        """scripts/process_rr.py: ingest both sites, remote-reference TF, EDI, figure."""
        pair = self._pair()
        if pair is None:
            return None
        window = self._window()
        if window is None:
            return None
        survey_yaml, station, remote = pair
        options = self.options.flags()
        argv = [self.state.python_exe, self.state.script("process_rr.py"),
                survey_yaml, station, remote, *window, *options]
        label = f"process_rr {station} rr-{remote}" + (f" {' '.join(window)}" if window else "")
        shown = " to ".join(window) if len(window) == 2 else f"from {window[0]}" if window else "full overlap"
        self._queue(label + (f" {' '.join(options)}" if options else ""), argv, station=station,
                    remote=remote, window=shown, options=" ".join(options) or "defaults")
        return argv

    def queue_stack(self, argv) -> None:
        """scripts/build_stack.py, from the StackBuilder; its name is selected when it finishes."""
        name = argv[3]
        index = self._queue(f"build_stack {name} <- {', '.join(argv[6:])}", argv)
        self._stack_jobs[index] = name

    def reset_queue(self) -> None:
        """`JobRunner.reset`: cancel the running job, clear the queue and the log (asked first if one runs)."""
        job = self.runner.current_job()
        if self.runner.running and QMessageBox.question(
            self, "Reset queue",
            f"{job.label if job else 'A job'} is running.\n\nCancel it and clear the queue and the log?",
        ) != QMessageBox.Yes:
            return
        self.runner.reset()
        self.job_panel.clear_log()
        self._stack_jobs.clear()  # keyed by queue indices that no longer exist
        self.status_label.setText("queue reset")

    def _job_finished(self, index: int, ok: bool) -> None:
        """Say how it went; a stack that was built becomes the remote (its EDIs: `ProductList`)."""
        job = self.runner.jobs[index]
        self.status_label.setText(self._queue_status() or f"{job.label}: {job.status}")
        name = self._stack_jobs.pop(index, None)
        if name and ok:
            # a stack is an archive with no raw folder, and `State.archived_sites`
            # globs the folder on every call, so the new one is simply there
            self._fill_remotes()
            position = self.remote_combo.findData(name)
            if position >= 0:
                self.remote_combo.setCurrentIndex(position)
            self._sites_changed()
