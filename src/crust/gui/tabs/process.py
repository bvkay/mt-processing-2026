# -*- coding: utf-8 -*-
"""
Process tab

Selects a station, a remote and a window, and queues the scripts that make
the products. Processing runs in `scripts/process_rr.py` and
`scripts/build_stack.py`; this tab builds their command lines and queues
them. The tab is laid out in rows, top to bottom:

1. Station, remote and the pair summary (`site_map.PairSummary`).
2. The window bar, full width (`window_bar.WindowBar`), with the start field
   at its left end, the end field at its right and the sync status centred
   above between two lamps.
3. Add to queue, Run queue, Reset queue and Build stack.
4. The run options (`stack_builder.RunOptions`): the engine, the bands,
   filters, masks, tag and the aurora estimator block.
5. The queue table over the script log (`queue_table.QueuePanel`).

Beside rows 3-5 are the site map (`site_map.SiteMap`), the stack builder and
the Products list. The timing check and site QC figures are run from the
command line, and the basemap is fetched when a survey is opened.

Each button runs one command line from the README's table through
`crust.gui.jobs.JobRunner`, from the repo root::

    Add to queue     scripts/process_rr.py <survey.yaml> <station> <remote> [start] [end]
                                           [--min-period ...] [--no-filters] [--no-masks] [--tag ...]
    Build stack      scripts/build_stack.py <survey.yaml> <name> <start> <end> <members...>

A band option is passed only when it differs from the survey's
`processing:` block, so a default run has the default command line.
`process_rr.py` also performs the raw ingest (as the Time Series tab's Build
MTH5 does for one site) and builds each site's filtered variant from it
(`crust.ingest.processing_archive`) unless "use declared filters" is off,
which adds `--no-filters` and processes both sites from their raw archives.
"apply masks.yaml" is on by default; its label counts each site's
`masks.yaml` entries for the pair and is refreshed when the pair changes,
the survey is opened and the tab is shown, since masks are saved on the
Cross-powers tab. process_rr applies the station's and the remote site's
masks; switching it off adds `--no-masks`, which ignores both. A remote is
required, since every product is remote-referenced. The engine combo's
"mantle" adds `--engine mantle`: the run goes to MANTLE on the same
archives and window, the queue label carries "[mantle]", the aurora
estimator block is disabled, and `--no-masks` goes with it whenever the pair
declares masks, which the status line says (`_engine_note`).

Add to queue and Build stack add jobs with `JobRunner.add` (`_queue`)
without starting them; Run queue runs them, so adding a job and running the
queue are separate steps. While jobs wait and the queue
is idle, `status_label` reads "N job(s) queued - press Run queue"
(`_queue_status`, `_refresh_status`).

The queue belongs to `State`, so every tab's jobs share `state.runner` and
appear in the table, and Reset queue calls `JobRunner.reset`. When a run
finishes, the EDI and figure paths its output reports writing ("wrote
<path>") that exist are added to the Products list, and "Show in View EDIs"
shows the chosen EDI with its lemimt reference on the View EDIs tab.
Comparison figures are listed only.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from crust.gui.jobs import QUEUED
from crust.gui.queue_table import ProductList, QueuePanel
from crust.gui.site_map import PairSummary, SiteMap
from crust.gui.stack_builder import RunOptions, StackBuilder
from crust.gui.window_bar import WindowBar


class ProcessTab(QWidget):
    """Station, remote, window and options, queued as the scripts that make the products.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    show_edi_requested = Signal(object)  # a Path: put it on the View EDIs tab

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.runner = state.runner  # the window's queue, owned by State
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
        self.options.engine_changed.connect(lambda _engine: self._refresh_status())
        self.state.site_changed.connect(self.select_station)

    def _button(self, text: str, slot, tip: str) -> QPushButton:
        """Return a push button with a tooltip, connected to `slot`."""
        button = QPushButton(text, self, toolTip=tip)
        button.clicked.connect(slot)
        return button

    # --------------------------------------------------------- the layout

    def _build_layout(self) -> None:
        """Lay out the rows top to bottom, with the map column beside rows 3-5."""
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
        side.addWidget(self.site_map, 3)  # the map takes most of the height, at least 340 px
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
        area = QScrollArea(self, widgetResizable=True)  # scrolls on a short screen
        area.setWidget(inner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)

    # --------------------------------------------------------- the lists

    def reload(self) -> None:
        """Repopulate from the survey: sites, map, spans and band defaults."""
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
        """Fill the remote combo with raw sites and stacked archives.

        On a new station the declared `remote:` in survey.yaml is selected;
        while the station stays the same, the remote chosen by the user is kept.
        """
        station = self.station_combo.currentData()
        previous = self.remote_combo.currentData()
        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        for display, name in self.state.remote_choices(station):
            self.remote_combo.addItem(display, name)
        # on a new station the site's declared `remote:` is the default; while
        # the station stays the same, a remote picked by the user is kept
        declared = self.state.default_remote(station) if station != self._remote_station else None
        self._remote_station = station
        wanted = declared or previous
        if wanted is not None:
            index = self.remote_combo.findData(wanted)
            if index >= 0:
                self.remote_combo.setCurrentIndex(index)
        self.remote_combo.blockSignals(False)

    def _station_changed(self, _index: int) -> None:
        """Refill the remotes and the stack candidates and set `State.site`."""
        station = self.station_combo.currentData()
        self._fill_remotes()
        self.stack_builder.set_station(station)
        self._sites_changed()
        if station:
            self.state.set_site(station)

    def _remote_changed(self, _index: int) -> None:
        """Update the views for the new pair."""
        self._sites_changed()

    def _sites_changed(self) -> None:
        """Update the map, spans, summary, buttons, filter line and masks switch for the current pair."""
        station, remote = self.station_combo.currentData(), self.remote_combo.currentData()
        self._paint_map()
        self.window_bar.set_sites(station, remote)
        self.summary.refresh()
        self._update_enabled()
        self.options.describe_filters(station, remote)
        self.options.describe_masks(station, remote)

    def showEvent(self, event) -> None:
        """Recount the masks on show, since they are saved on the Cross-powers tab."""
        super().showEvent(event)
        self.options.describe_masks(self.station_combo.currentData(), self.remote_combo.currentData())

    def _paint_map(self) -> None:
        """Colour the station, remote and stack members on the map."""
        self.site_map.set_roles(self.station_combo.currentData(), self.remote_combo.currentData(),
                                self.stack_builder.members())

    def select_station(self, name: str) -> None:
        """Select `name` in the station combo if listed."""
        index = self.station_combo.findData(name)
        if index >= 0 and index != self.station_combo.currentIndex():
            self.station_combo.setCurrentIndex(index)

    def _update_enabled(self) -> None:
        """Enable Add to queue when a station and a remote are selected."""
        ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
        self.add_button.setEnabled(ready)
        self._refresh_status()

    def _queue_status(self) -> str | None:
        """Return 'N job(s) queued - press Run queue' while jobs wait and the queue is idle, else None."""
        queued = sum(1 for job in self.runner.jobs if job.status == QUEUED)
        if queued and not self.runner.running:
            return f"{queued} job(s) queued - press Run queue"
        return None

    def _engine_note(self) -> str:
        """Describe what the chosen engine leaves out: "" for aurora, the masks and estimator note for MANTLE."""
        if self.options.engine() == "aurora":
            return ""
        note = "engine mantle: the aurora estimator options above do not reach it"
        if self.options.masks_declared():
            masks = self.options.masks_check.text().split(self.options.MASKS_TEXT, 1)[1].strip()
            note += f"; masks.yaml is left out, --no-masks is passed {masks}"
        return note

    def _refresh_status(self) -> None:
        """Show the queued-jobs notice and the engine note, or else the station and remote reminder when either is missing."""
        parts = [text for text in (self._queue_status(), self._engine_note()) if text]
        ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
        if not parts and not ready:
            parts = ["A station and a remote are both required: every product here is "
                     "remote-referenced (adjacent site, dedicated remote, or a stack)."]
        self.status_label.setText(" | ".join(parts))

    @property
    def products(self) -> list[Path]:
        """The products the jobs wrote, as listed under the map."""
        return self.product_panel.products

    def set_window(self, start: str, end: str) -> None:
        """Set the processing window; used by the Time Series tab's "Use visible range as processing window"."""
        self.window_bar.set_window(start, end)

    @property
    def start_edit(self) -> QLineEdit:
        """The window bar's start field."""
        return self.window_bar.start_edit

    @property
    def end_edit(self) -> QLineEdit:
        """The window bar's end field."""
        return self.window_bar.end_edit

    # ------------------------------------------------------- queue a job

    def _pair(self):
        """Return (survey.yaml, station, remote), or None after a warning message box."""
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
        """Return the optional [start, end] arguments as the scripts take them, or None after a warning."""
        start, end = self.window_bar.window_text()
        if end and not start:
            QMessageBox.warning(self, "Window", "process_rr.py takes start before end.")
            return None
        return [text for text in (start, end) if text]

    def _queue(self, label: str, argv, **details) -> int:
        """Add a job to `state.runner`'s queue without starting it; Run queue starts it."""
        return self.runner.add(label, argv, **details)

    def queue_process(self) -> list[str] | None:
        """Queue scripts/process_rr.py: ingest both sites, remote-reference TF, EDI and figure.

        Returns:
            list[str] | None: The queued argv, or None when the pair or window is invalid.
        """
        pair = self._pair()
        if pair is None:
            return None
        window = self._window()
        if window is None:
            return None
        survey_yaml, station, remote = pair
        options = self.options.flags()
        engine = self.options.engine()
        argv = [self.state.python_exe, self.state.script("process_rr.py"),
                survey_yaml, station, remote, *window, *options]
        label = (f"process_rr {station} rr-{remote}" + (f" [{engine}]" if engine != "aurora" else "")
                 + (f" {' '.join(window)}" if window else ""))
        shown = " to ".join(window) if len(window) == 2 else f"from {window[0]}" if window else "full overlap"
        self._queue(label + (f" {' '.join(options)}" if options else ""), argv, station=station,
                    remote=remote, window=shown, options=" ".join(options) or "defaults")
        return argv

    def queue_stack(self, argv) -> None:
        """Queue scripts/build_stack.py from the StackBuilder; the stack becomes the remote when it finishes."""
        name = argv[3]
        index = self._queue(f"build_stack {name} <- {', '.join(argv[6:])}", argv)
        self._stack_jobs[index] = name

    def reset_queue(self) -> None:
        """Cancel the running job and clear the queue and the log (`JobRunner.reset`), confirming first if a job runs."""
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
        """Report a finished job; a successfully built stack becomes the selected remote."""
        job = self.runner.jobs[index]
        self.status_label.setText(self._queue_status() or f"{job.label}: {job.status}")
        name = self._stack_jobs.pop(index, None)
        if name and ok:
            # a stack is an archive with no raw folder, and `State.archived_sites`
            # globs the folder on every call, so the new stack is listed
            self._fill_remotes()
            position = self.remote_combo.findData(name)
            if position >= 0:
                self.remote_combo.setCurrentIndex(position)
            self._sites_changed()
