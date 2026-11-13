# -*- coding: utf-8 -*-
"""
Process tab

Selects a processing type, a station, a remote and a window, and queues the
scripts that make the products. Processing runs in `scripts/process_rr.py`,
`scripts/build_stack.py` and `scripts/process_intersite.py`; this tab builds
their command lines and queues them. The tab is laid out in rows, top to bottom:

1. Processing type, station, remote, the Base box of a tensor type and the
   pair summary (`site_map.PairSummary`).
2. The window bar, full width (`window_bar.WindowBar`), with the start field
   at its left end, the end field at its right and the sync status centred
   above between two lamps.
3. Add to queue, "Add every site on this base" (a tensor type only), Run
   queue, Reset queue and Build stack.
4. The run options (`stack_builder.RunOptions`): the engine, the bands,
   the band layout (window samples, min bin) and the min band windows
   floor, filters, masks, tag and the aurora estimator block.
5. The queue table over the script log (`queue_table.QueuePanel`).

The station combo lists `State.station_choices`: every raw folder under
`data_root`, and every declared site that has an archive in
`<workspace>/mth5` (a derived or burst site too, not an observatory). A
site whose raw folder is not found is labelled with its kind, as
"A01  (archive)", and is processed from its archive: process_rr.py
ingests a site only when its archive is missing
(`mt_workbench.ingest.ingest_site`). So a survey whose `data_root` is
stale, or on a drive not plugged in, still lists the sites it has
archives of.

Beside rows 3-5 are the site map (`site_map.SiteMap`), the stack recipe
picker (`stack_builder.StackBuilder`) and the Products list. The timing
check and site QC figures are run from the command line, and the basemap is
fetched when a survey is opened.

Each button runs one command line from the README's table through
`mt_workbench.gui.jobs.JobRunner`, from the repo root::

    Add to queue     scripts/process_rr.py <survey.yaml> <station> <remote> [start] [end]
                                           [--min-period ...] [--window-samples N] [--min-bin N]
                                           [--min-band-windows N] [--no-filters] [--no-masks] [--tag ...]
    Build stack      scripts/build_stack.py <survey.yaml> --recipe NAME --overwrite
    Queue intersite  scripts/process_intersite.py <survey.yaml> <station> <start> <end> --kind KIND
                                           --remote <remote> --stack NAME [--no-filters]
    Add to queue     scripts/process_intersite.py <survey.yaml> <station> <base> [start end] --kind KIND
    (a tensor type)                        --remote <remote> [--tag ...] [--no-filters]

The Processing type combo chooses what Add to queue runs: "MT impedance and
tipper" (the default, process_rr.py), "Telluric tensor, E to E" or "Magnetic
tensor, B to B" (process_intersite.py with `--kind telluric` or `magnetic`).
A tensor type shows the Base box, which lists the survey.yaml sites that
have an archive at the station's sample rate, then the `use: base` band
recipes of stacks.yaml for the tensor's field at that rate as "stack: NAME".
The tensor and psi = arg(det) / 2 are the station's field relative to the
base's, in each site's channels as recorded, in geomagnetic coordinates: no
rotation is applied, and a declination is a recorded number that is not
applied. Add to queue then queues the station on the base with the remote
as the reference, through `mt_workbench.stacks.pair_argv` for a base site
and `StackBuilder.base_argv` for a base stack. "Add every site on this base"
queues one such run for every other site with an archive at that rate, the
base and the remote left out; the sites the checks refuse are left out too,
and the status line names them under each reason. A refusal is one the
script gives the same command line (exit 2). For a base site the three
archives' run lists are read when the button is pressed, under
`State.archive_lock`. A tensor run takes the tag and the filters switch;
the other run options are disabled meanwhile (`RunOptions.set_tensor`).

A band option is passed only when it differs from the survey's
`processing:` block, so a default run has the default command line. Min
bin reads "layout's own" at 0, its default when the survey gives no
`min_bin:`; min band windows starts at the survey's `min_band_windows:`,
else `mt_workbench.process.MIN_BAND_WINDOWS`, and is disabled under
"mantle".
`process_rr.py` also performs the raw ingest (as the Time Series tab's Build
MTH5 does for one site) and builds each site's filtered variant from it
(`mt_workbench.ingest.processing_archive`) unless "use declared filters" is off,
which adds `--no-filters` and processes both sites from their raw archives.
"apply masks.yaml" is on by default; its label counts the `masks.yaml`
entries process_rr applies for the pair and is refreshed when the pair
changes, the survey is opened and the tab is shown, since masks are saved
on the Cross-powers tab; a changed masks.yaml is parsed off the GUI thread
first (`State.masks_reader`), the label reading "(reading masks.yaml...)"
meanwhile. process_rr applies the station's masks of scope
local or both and the remote site's masks of scope both or remote (those
naming hx, hy or every channel); switching it off adds `--no-masks`,
which ignores both. A remote is
required, since every product is remote-referenced. The engine combo's
"mantle" adds `--engine mantle`: the run goes to MANTLE on the same
archives and window, the queue label carries "[mantle]", the aurora
estimator block is disabled, and `--no-masks` goes with it whenever the pair
declares masks, which the status line says (`_engine_note`).

The picker lists the recipes of the survey's stacks.yaml, declared on the
Stacks tab. Build stack queues a time recipe's archive; when it finishes the
archive becomes the remote, unless the station is one of its members (it
would share the station's noise). Queue intersite runs a `use: base` band
recipe for the station with the remote as the reference; the run options
apply to process_rr.py only. `use_recipe` (the Stacks tab's Use in Process)
chooses a recipe and puts its window on the bar.

Add to queue, Build stack and Queue intersite add jobs with `JobRunner.add` (`_queue`)
without starting them; Run queue runs them, so adding a job and running the
queue are separate steps. While jobs wait and the queue
is idle, `status_label` reads "N job(s) queued - press Run queue"
(`_queue_status`, `_refresh_status`).

The queue belongs to `State`, so every tab's jobs share `state.runner` and
appear in the table, and Reset queue calls `JobRunner.reset`. When a run
finishes, the EDI and figure paths its output reports writing ("wrote
<path>") that exist are added to the Products list, and "Show in View EDIs"
shows the chosen EDI with its lemimt reference on the View EDIs tab.
Comparison figures are listed only. A finished tensor run adds its CSV, its
sidecar, its h5 file and its figure, read from the four lines the script
ends with; a tensor has no EDI, so "Show in View EDIs" is disabled on them.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import functools
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from mt_workbench import intersite, stacks
from mt_workbench.gui.jobs import QUEUED
from mt_workbench.gui.queue_table import ProductList, QueuePanel
from mt_workbench.gui.site_map import PairSummary, SiteMap
from mt_workbench.gui.stack_builder import RunOptions, StackBuilder
from mt_workbench.gui.window_bar import UTC_FMT, WindowBar

# the Processing type choices: the label, and the --kind of scripts/process_intersite.py (None: process_rr.py)
TYPES = (("MT impedance and tipper", None), ("Telluric tensor, E to E", "telluric"),
         ("Magnetic tensor, B to B", "magnetic"))
STACK = "stack: "  # how the Base box lists a base recipe of stacks.yaml
ADD_TIPS = {False: "process_rr.py: ingest both sites, remote-referenced TF, EDI",
            True: "process_intersite.py: the station on the base, the remote as the reference, over the window"}
BASE_TIP = ("The site, or the saved base stack (stack: NAME), the tensor is taken against. The tensor and "
            "psi = arg(det) / 2 are the station's field relative to the base's, in each site's channels as "
            "recorded, in geomagnetic coordinates: no rotation is applied, and a declination is a recorded "
            "number that is not applied. A site is listed when it has an archive at the station's sample rate.")
STAR_TIP = ("One run for every other site that has an archive at the station's sample rate, each on this base "
            "with the same remote, window, tag and filters switch (a star of pairs around the base). The base, "
            "the remote and the sites the checks refuse are left out; the status line names them. The base "
            "must be a site: a base stack takes one station at a time.")


def _archive_runs(site: str, path, channels) -> list | None:
    """Return a site's runs (`intersite.archive_runs`), or None for an archive that cannot be opened now."""
    try:
        return intersite.archive_runs(path, site, channels)
    except OSError:  # being written by a job: the run reads it again
        return None


def _some(names: list[str], most: int = 6) -> str:
    """Return a comma list of the first `most` names and a count of the rest."""
    shown = ", ".join(names[:most])
    return shown if len(names) <= most else f"{shown} and {len(names) - most} more"


class ProcessTab(QWidget):
    """Station, remote, window and options, queued as the scripts that make the products.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    show_edi_requested = Signal(object)  # a Path: put it on the View EDIs tab

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.runner = state.runner  # the window's queue, owned by State
        self._remote_station = None
        self._remote_note = ""  # why a kept remote was dropped on a station change
        self._star_note = ""  # what "Add every site on this base" queued and left out, until the pair changes
        self._stack_jobs: dict[int, str] = {}

        self.type_combo = QComboBox(self)
        for text, kind in TYPES:
            self.type_combo.addItem(text, kind)
        self.type_combo.setToolTip("What Add to queue runs: the impedance and tipper of the station (process_rr.py), "
                                   "or the telluric or magnetic tensor of the station on a base (process_intersite.py)")
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.station_combo = QComboBox(self, minimumWidth=140)
        self.station_combo.currentIndexChanged.connect(self._station_changed)
        self.remote_combo = QComboBox(self, minimumWidth=140)
        self.remote_combo.currentIndexChanged.connect(self._remote_changed)
        self.base_label = QLabel("Base", self, visible=False)
        self.base_combo = QComboBox(self, minimumWidth=140, visible=False, toolTip=BASE_TIP)
        self.base_combo.setPlaceholderText("choose a base")
        self.base_combo.currentIndexChanged.connect(lambda _index: self._sites_changed())
        self.site_map = SiteMap(state, self)
        self.site_map.setMinimumHeight(340)
        self.window_bar = WindowBar(state, self)
        self.summary = PairSummary(state, self.site_map, self.window_bar, self)
        self.options = RunOptions(state, self)
        self.stack_builder = StackBuilder(state, self.window_bar, self)
        self.stack_builder.members_changed.connect(lambda _m: self._paint_map())
        self.stack_builder.build_requested.connect(self.queue_stack)
        self.stack_builder.intersite_requested.connect(self.queue_intersite)

        self.add_button = self._button("Add to queue", self.queue_process, ADD_TIPS[False])
        self.star_button = self._button("Add every site on this base", self.queue_star, STAR_TIP)
        self.star_button.setVisible(False)
        self.run_button = self._button("Run queue", self.runner.run_queue, "start the next queued job")
        self.reset_button = self._button("Reset queue", self.reset_queue,
                                         "cancel the running job, clear the queue and the log")
        self.build_button = self._button("Build stack", self.stack_builder.build,
                                         "build_stack.py --recipe: the time recipe chosen on the right")
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
        self.state.masks_reader.ready.connect(self._describe_masks)

    def _button(self, text: str, slot, tip: str) -> QPushButton:
        """Return a push button with a tooltip, connected to `slot`."""
        button = QPushButton(text, self, toolTip=tip)
        button.clicked.connect(slot)
        return button

    # --------------------------------------------------------- the layout

    def _build_layout(self) -> None:
        """Lay out the rows top to bottom, with the map column beside rows 3-5."""
        pair = QGridLayout()
        for column, (label, combo) in enumerate(((QLabel("Processing type", self), self.type_combo),
                                                 (QLabel("Station to process", self), self.station_combo),
                                                 (QLabel("Remote reference", self), self.remote_combo),
                                                 (self.base_label, self.base_combo))):  # hidden for MT
            pair.addWidget(label, 0, column)
            pair.addWidget(combo, 1, column)
        pair.addWidget(self.summary, 0, 4, 3, 1)
        pair.setRowStretch(2, 1)
        pair.setColumnStretch(4, 1)
        pair.setHorizontalSpacing(24)

        buttons = QHBoxLayout()
        separator = QFrame(self, frameShape=QFrame.VLine, frameShadow=QFrame.Sunken)
        for widget in (self.add_button, self.star_button, self.run_button, self.reset_button, separator,
                       self.build_button):
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
        for display, name in self.state.station_choices():
            self.station_combo.addItem(display, name)
        self.station_combo.blockSignals(False)
        self.site_map.reload()
        self.window_bar.reload()
        self._remote_station = None
        self.stack_builder.reload()  # before the remotes: a recipe archive holding the station is not kept
        if self.state.site:
            self.select_station(self.state.site)
        self._fill_remotes()
        self._fill_bases()
        self._sites_changed()

    def _archived_at(self, rate: float) -> list[str]:
        """Return the survey.yaml sites at `rate` Hz that have an archive, in the file's order."""
        survey = self.state.survey
        return [site for site in survey.site_names()
                if survey.sample_rate_of(site) == rate and self.state.has_archive(site)]

    def _fill_bases(self) -> None:
        """Fill the Base box for the tensor type and the station, keeping the base chosen while it is still listed.

        The sites with an archive at the station's sample rate, the station
        left out, then the base recipes of stacks.yaml for the tensor's
        field at that rate as "stack: NAME". Empty for MT, and with no
        station.
        """
        kind, station, survey = self.type_combo.currentData(), self.station_combo.currentData(), self.state.survey
        previous = self.base_combo.currentData()
        self.base_combo.blockSignals(True)
        self.base_combo.clear()
        if kind and station and survey is not None:
            rate = survey.sample_rate_of(station)
            for site in self._archived_at(rate):
                if site != station:
                    self.base_combo.addItem(site, site)
            for name in self.stack_builder.base_recipes(intersite.BASE_FIELDS[kind], rate):
                self.base_combo.addItem(STACK + name, STACK + name)
        self.base_combo.setCurrentIndex(self.base_combo.findData(previous) if previous else -1)
        self.base_combo.blockSignals(False)

    def _base(self) -> tuple[str | None, bool]:
        """Return the Base box's choice as (the site or recipe name, or None; whether it is a base stack)."""
        data = self.base_combo.currentData() or ""
        if data.startswith(STACK):
            return data[len(STACK):], True
        return data or None, False

    def _type_changed(self, _index: int) -> None:
        """Show the Base box and the star button for a tensor type, and set the run options for its script."""
        tensor = bool(self.type_combo.currentData())
        for widget in (self.base_label, self.base_combo, self.star_button):
            widget.setVisible(tensor)
        self.add_button.setToolTip(ADD_TIPS[tensor])
        self.options.set_tensor(tensor)
        self._fill_bases()
        self._sites_changed()

    def _fill_remotes(self) -> None:
        """Fill the remote combo with raw sites and stacked archives.

        On a new station the declared `remote:` in survey.yaml is selected;
        while the station stays the same, the remote chosen by the user is kept.
        A kept remote that is a time recipe's archive holding the new station
        is dropped for the declared remote (or none), and the status line
        says why: it would share the station's noise (design 8.1 item 8).
        """
        station = self.station_combo.currentData()
        previous = self.remote_combo.currentData()
        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        for display, name in self.state.remote_choices(station):
            self.remote_combo.addItem(display, name)
        # on a new station the site's declared `remote:` is the default; while
        # the station stays the same, a remote picked by the user is kept
        new_station = station != self._remote_station
        default = self.state.default_remote(station) if new_station else None
        self._remote_station = station
        wanted = default or previous
        if new_station:
            self._remote_note = ""
        if wanted is not None and self.stack_builder.holds(wanted, station):
            declared = self.state.default_remote(station)
            self._remote_note = (f"{wanted} holds {station}, so it is not {station}'s remote: "
                                 + (f"{declared}, the declared remote, is chosen" if declared else "choose a remote"))
            wanted = None if declared is None or self.stack_builder.holds(declared, station) else declared
        index = self.remote_combo.findData(wanted) if wanted is not None else -1
        if index >= 0:
            self.remote_combo.setCurrentIndex(index)
        elif wanted is None and self._remote_note:
            self.remote_combo.setCurrentIndex(-1)
        self.remote_combo.blockSignals(False)

    def _station_changed(self, _index: int) -> None:
        """Refill the remotes and set `State.site`."""
        station = self.station_combo.currentData()
        self._fill_remotes()
        self._fill_bases()
        self._sites_changed()
        if station:
            self.state.set_site(station)

    def _remote_changed(self, _index: int) -> None:
        """Update the views for the new pair."""
        self._remote_note = ""
        self._sites_changed()

    def _sites_changed(self) -> None:
        """Update the map, spans, summary, buttons, filter line and masks switch for the current pair."""
        station, remote = self.station_combo.currentData(), self.remote_combo.currentData()
        self._star_note = ""
        self.stack_builder.set_pair(station, remote)
        self._paint_map()
        self.window_bar.set_sites(station, remote)
        self.summary.refresh()
        self._update_enabled()
        self.options.describe_filters(station, remote)
        self._describe_masks()

    def showEvent(self, event) -> None:
        """Recount the masks and re-read the stack recipes on show: both are saved on other tabs."""
        super().showEvent(event)
        self._describe_masks()
        self.stack_builder.reload()
        if self.type_combo.currentData():  # a base recipe saved or an archive built on another tab
            self._fill_bases()
            self._update_enabled()

    def _describe_masks(self) -> None:
        """Count the pair's masks on the switch, at once when masks.yaml is parsed as it is now.

        A changed file is parsed off the GUI thread (`State.masks_reader`);
        the switch reads "(reading masks.yaml...)" until its `ready` calls
        this again.
        """
        if self.state.masks_reader.request():
            self.options.describe_masks(self.station_combo.currentData(), self.remote_combo.currentData())
        else:
            self.options.masks_reading()

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
        """Enable Add to queue when a station and a remote are selected, and for a tensor type a base as well.

        The star button needs a base site: a base stack takes one station
        at a time.
        """
        ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
        tensor, (base, stacked) = bool(self.type_combo.currentData()), self._base()
        self.add_button.setEnabled(ready and (bool(base) or not tensor))
        self.star_button.setEnabled(ready and tensor and bool(base) and not stacked)
        self._refresh_status()

    def _queue_status(self) -> str | None:
        """Return 'N job(s) queued - press Run queue' while jobs wait and the queue is idle, else None."""
        queued = sum(1 for job in self.runner.jobs if job.status == QUEUED)
        if queued and not self.runner.running:
            return f"{queued} job(s) queued - press Run queue"
        return None

    def _engine_note(self) -> str:
        """Describe what the chosen engine leaves out: "" for aurora, the masks and estimator note for MANTLE.

        "" for a tensor type too: scripts/process_intersite.py takes no engine.
        """
        if self.options.engine() == "aurora" or self.type_combo.currentData():
            return ""
        note = "engine mantle: the aurora estimator options above do not reach it"
        if self.options.masks_declared():
            masks = self.options.masks_check.text().split(self.options.MASKS_TEXT, 1)[1].strip()
            note += f"; masks.yaml is left out, --no-masks is passed {masks}"
        return note

    def _refresh_status(self) -> None:
        """Show the queued-jobs notice and the engine note, or else the station and remote reminder when either is missing.

        The summary of "Add every site on this base" stays until the pair
        changes, and a tensor type with a station, a remote and no base
        asks for the base.
        """
        parts = [text for text in (self._remote_note, self._star_note, self._queue_status(), self._engine_note())
                 if text]
        ready = bool(self.station_combo.currentData()) and bool(self.remote_combo.currentData())
        kind = self.type_combo.currentData()
        if not parts and not ready:
            parts = ["A station and a remote are both required: every product here is "
                     "remote-referenced (adjacent site, dedicated remote, or a stack)."]
        if kind and ready and self.base_combo.currentIndex() < 0:
            parts.append(f"Choose a base: the {kind} tensor and psi = arg(det) / 2 are the station's field "
                         f"relative to the base's.")
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

        With a tensor type chosen, Add to queue queues the station's tensor
        run instead (`queue_tensor`).

        Returns:
            list[str] | None: The queued argv, or None when the pair or window is invalid.
        """
        if self.type_combo.currentData():
            return self.queue_tensor()
        pair = self._pair()
        if pair is None:
            return None
        window = self._window()
        if window is None:
            return None
        survey_yaml, station, remote = pair
        if self.stack_builder.holds(remote, station):
            QMessageBox.warning(self, "Remote", f"{remote} is a stack of {station} among others: as {station}'s "
                                                f"remote it would share {station}'s noise. Pick another remote.")
            return None
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

    def tensor_argvs(self, stations) -> tuple[dict[str, tuple[list[str] | None, str]], str]:
        """Return each station's tensor command line on the base, remote, window, tag and filters switch shown.

        A base site goes through `mt_workbench.stacks.pair_argv`, which
        reads the run list of each archive once, here under
        `State.archive_lock`. A "stack: NAME" base goes through the recipe
        picker (`StackBuilder.base_argv`), which opens no file.

        Args:
            stations (list[str]): The local sites.

        Returns:
            tuple: ({station: (command line, "") or (None, the refusal)},
            ""), or ({}, why no station could be judged): no survey, base
            or remote, window fields that are not a window, or an archive
            read in flight.
        """
        kind, remote = self.type_combo.currentData(), self.remote_combo.currentData()
        base, stacked = self._base()
        if self.state.survey_yaml is None or not kind or not base or not remote:
            return {}, "Open a survey, and choose a tensor type, a base and a remote."
        tag = self.options.tag_edit.text().strip() or None
        no_filters = not self.options.filters_check.isChecked()
        if stacked:
            return {s: self.stack_builder.base_argv(base, s, tag, no_filters) for s in stations}, ""
        start, end = (text or None for text in self.window_bar.window_text())
        if (start or end) and self.window_bar.window() is None:
            return {}, ("The window needs a start and an end in UTC, the end after the start: fill both fields, "
                        "or clear both to take the time the three sites share.")
        lock = self.state.archive_lock
        if not lock.acquire(self):
            return {}, "An archive is being read: press the button again in a moment."
        runs_of = functools.lru_cache(maxsize=None)(_archive_runs)  # each run list read once for this press
        try:
            return {s: stacks.pair_argv(self.state.python_exe, self.state.script("process_intersite.py"),
                                        str(self.state.survey_yaml), s, base, kind, remote, start, end, tag,
                                        no_filters, survey=self.state.survey, runs_of=runs_of)
                    for s in stations}, ""
        finally:
            lock.release(self)

    def _queue_tensor(self, argv) -> int:
        """Add a tensor job: a base recipe's as Queue intersite adds it, a plain pair's with its base under Options."""
        if "--stack" in argv:
            return self.queue_intersite(argv)
        local, base, kind_at, remote_at = argv[3], argv[4], argv.index("--kind"), argv.index("--remote")
        kind = argv[kind_at + 1]
        return self._queue(f"process_intersite {local} on {base} ({kind})", argv, station=local,
                           remote=argv[remote_at + 1], window=" to ".join(argv[5:kind_at]) or "the shared record",
                           options=" ".join([f"{kind} tensor on base {base}", *argv[remote_at + 2:]]))

    def queue_tensor(self) -> list[str] | None:
        """Queue the station's tensor run on the base shown: Add to queue with a tensor type chosen.

        Returns:
            list[str] | None: The queued argv, or None after a warning box
            that gives the refusal and what to do.
        """
        station = self.station_combo.currentData()
        answers, why = self.tensor_argvs([station] if station else [])
        argv, why = answers.get(station, (None, why or "Pick a station."))
        if argv is None:
            QMessageBox.warning(self, self.type_combo.currentText(), why)
            return None
        self._queue_tensor(argv)
        return argv

    def queue_star(self) -> list[list[str]]:
        """Queue every other site on the base shown, with the same remote, window, tag and filters switch.

        The sites are those of survey.yaml that have an archive at the
        station's sample rate (the rate of every base the box lists), less
        the base and the remote. A site the checks refuse is left out. The
        status line then counts the runs queued and, under each refusal,
        the sites left out. The base is a site: a base stack takes one
        station at a time through Add to queue.

        Returns:
            list[list[str]]: The queued argvs; [] after a warning box when
            no site could be judged.
        """
        station, remote = self.station_combo.currentData(), self.remote_combo.currentData()
        base, stacked = self._base()
        sites = [] if not station or self.state.survey is None else [
            site for site in self._archived_at(self.state.survey.sample_rate_of(station)) if site not in (base, remote)]
        answers, why = ({}, "A base stack takes one station at a time: choose the station and press Add to "
                            "queue.") if stacked else self.tensor_argvs(sites)
        if why:
            QMessageBox.warning(self, self.star_button.text(), why)
            return []
        queued, left_out = [], {}
        for site, (argv, refusal) in answers.items():
            if argv is None:
                left_out.setdefault(refusal, []).append(site)
            else:
                self._queue_tensor(argv)
                queued.append(argv)
        note = [f"{len(queued)} {self.type_combo.currentData()} tensor run(s) queued on base {base}"]
        note += [f"{len(names)} left out ({_some(names)}): {refusal}" for refusal, names in left_out.items()]
        self._star_note = " | ".join(note)
        self._refresh_status()
        return queued

    def queue_stack(self, argv) -> int:
        """Queue a time recipe's scripts/build_stack.py; the archive becomes the remote when it finishes.

        Called by the picker's Build stack and the Stacks tab's Build
        archive. When the job finishes, `_job_finished` selects the archive
        as the remote unless the station is one of the recipe's members.

        Args:
            argv (list[str]): ``[python, build_stack.py, survey.yaml,
                --recipe, NAME, --overwrite]`` (`stacks.build_argv`).

        Returns:
            int: The job's index in the queue.
        """
        name = argv[argv.index("--recipe") + 1]
        self.stack_builder.reload()  # a recipe saved on the Stacks tab since the last look
        recipe = self.stack_builder.recipe_named(name)
        window = (f"{recipe.start:%Y-%m-%d %H:%M} to {recipe.end:%Y-%m-%d %H:%M}"
                  if recipe is not None and recipe.start is not None else "-")
        index = self._queue(f"build_stack {name} (recipe)", argv, station=name, window=window,
                            options=" ".join(argv[argv.index("--recipe") + 2:]) or "-")
        self._stack_jobs[index] = name
        return index

    def queue_intersite(self, argv) -> int:
        """Queue a base band recipe's scripts/process_intersite.py run from the picker's Queue intersite.

        Args:
            argv (list[str]): ``[python, process_intersite.py, survey.yaml,
                station, start, end, --kind, KIND, --remote, REMOTE, --stack,
                NAME, ...]`` (`stacks.intersite_argv`).

        Returns:
            int: The job's index in the queue; Run queue starts it.
        """
        local, kind_at = argv[3], argv.index("--kind")
        name = argv[argv.index("--stack") + 1]
        remote = argv[argv.index("--remote") + 1] if "--remote" in argv else None
        positionals = argv[4:kind_at]
        window = " to ".join(positionals) if len(positionals) == 2 else "the recipe's"
        return self._queue(f"process_intersite {local} --stack {name}", argv, station=local, remote=remote,
                           window=window, options=f"--stack {name}")

    def use_recipe(self, name: str) -> str:
        """Choose a recipe in the picker and put its window on the bar (the Stacks tab's Use in Process).

        A time recipe's archive is also selected as the remote when it is
        built and the station is not one of its members; for a base band
        recipe Queue intersite is then one click.

        Args:
            name (str): The recipe.

        Returns:
            str: What was done, as the status line says it.
        """
        builder = self.stack_builder
        builder.reload()
        if not builder.select_recipe(name):
            note = f"{name}: no valid recipe of that name in stacks.yaml"
            self.status_label.setText(note)
            return note
        recipe = builder.recipe()
        if recipe.start is not None:
            self.window_bar.set_window(recipe.start.strftime(UTC_FMT), recipe.end.strftime(UTC_FMT))
        station = self.station_combo.currentData()
        if recipe.engine == "time":
            if station in recipe.members:
                note = f"{name} holds {station}: not its remote"
            elif not self.state.has_archive(name):
                note = f"{name}: no archive yet: Build stack, then Run queue"
            else:
                self._fill_remotes()
                position = self.remote_combo.findData(name)
                if position >= 0:
                    self.remote_combo.setCurrentIndex(position)
                note = f"{name} is the remote of {station}"
        else:
            note = (f"{name}: Queue intersite runs {station} on it" if builder.intersite_button.isEnabled()
                    else f"{name}: {builder.hint.text().splitlines()[0]}")
        self._sites_changed()
        self.status_label.setText(note)
        return note

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
        """Report a finished job; a built stack becomes the selected remote unless the station is a member."""
        job = self.runner.jobs[index]
        self.status_label.setText(self._queue_status() or f"{job.label}: {job.status}")
        name = self._stack_jobs.pop(index, None)
        if name and ok:
            # a stack is an archive with no raw folder, and `State.archived_sites`
            # globs the folder on every call, so the new stack is listed
            self._fill_remotes()
            recipe = self.stack_builder.recipe_named(name)
            station = self.station_combo.currentData()
            if recipe is not None and recipe.members and station in recipe.members:
                # it would share the station's noise
                self.status_label.setText(f"{name} built; it holds {station}, so it is not made its remote")
            else:
                position = self.remote_combo.findData(name)
                if position >= 0:
                    self.remote_combo.setCurrentIndex(position)
            self._sites_changed()
