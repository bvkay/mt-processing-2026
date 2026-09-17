"""The main window and the state every tab shares.

`State` holds the one survey the window is looking at (the `survey.yaml` path,
the `mtproc.survey.Survey` built from it, the selected site) plus the two things
the job runner needs: the repo root (working directory for every subprocess)
and the Python executable that runs the scripts. Everything a tab needs to
know about the survey it asks `State` for, so opening a different survey is
one signal and one `reload()` per tab.

`State` also owns the window's **one** `JobRunner`: every tab queues on
`state.runner`, so the GUI runs one job at a time (an MTH5 must never be open
in two processes); the Process tab's `queue_table.QueuePanel` shows every job.
Opening a survey with no basemap fetches one (`site_map.fetch_basemap_if_missing`).

`State` also carries what the Time Series tab and the QC tabs share: the
**selection** (`selection` = (station, start, end) UTC, the window clicked in
the Time Series tab's tree, or None; `selection_changed`), the **remote**
the QC is computed against (`remote`, the Coherence tab's choice, None by
default on every new station; `remote_changed`), the `SegmentStore`
that loads the selected window and computes its QC off the GUI thread
(`segment_store`, `mtproc_gui.segment_store`), the `ArchiveLock` that keeps
the store's worker and the tree's archive reads from having a file open at
the same time (`archive_lock`), and `goto_time`, which any tab emits to put
the Time Series view on a moment. `request_qc()` is the one place the store
is asked for the selection with the current remote and ladder.

`MainWindow` is a QTabWidget over the nine tabs in the MATLAB app's order (QC
first: Metadata, Time Series, Spectra, Spectrogram, Coherence; then Filter Data,
Process, Cross-powers, View EDIs), a status bar, a File menu and, under the tabs in a vertical
`QSplitter`, the `console.ConsoleStrip` (the runner's log, loguru, `qc_started`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
from loguru import logger
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QSplitter, QTabWidget

from mtproc.ingest import variant_path, variant_ready
from mtproc.survey import Survey
from mtproc_gui.console import ConsoleStrip, LoguruQtSink
from mtproc_gui.jobs import JobRunner
from mtproc_gui.reader import ArchiveLock
from mtproc_gui.segment_store import SegmentStore
from mtproc_gui.site_map import fetch_basemap_if_missing

# src/mtproc_gui/app.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
# a filtered variant's own file stem (`<site>_f<hash>.h5`, `mtproc.ingest.variant_path`):
# never a site or a stacked remote of its own, just another archive of the
# name before the `_f<hash>`
_VARIANT_SUFFIX = re.compile(r"_f[0-9a-f]{8}$")


class State(QObject):
    """The survey and site every tab reads; emits when either changes."""

    survey_changed = Signal()
    site_changed = Signal(str)
    selection_changed = Signal(object)  # (station, start, end) or None
    remote_changed = Signal(object)  # the remote's name, or None
    goto_time = Signal(object)  # a pd.Timestamp the Time Series tab should show
    archive_changed = Signal(str)  # a site's archive was built or deleted: the tree and chooser look again

    def __init__(self, repo_root: Path | str = REPO_ROOT, parent=None):
        super().__init__(parent)
        self.repo_root = Path(repo_root)
        self.python_exe = sys.executable
        # the one queue the whole window shares: one job at a time, ever
        self.runner = JobRunner(self.repo_root, self)
        self.survey_yaml: Path | None = None
        self.survey: Survey | None = None
        self.site: str | None = None
        self._raw_sites: dict[str, Path] | None = None
        # the selected window, its remote, and the one in-process worker that
        # reads and QCs it; the lock keeps that worker and the tree's reads apart
        self.selection: tuple[str, pd.Timestamp, pd.Timestamp] | None = None
        self.remote: str | None = None
        self.archive_lock = ArchiveLock(self)
        self.segment_store = SegmentStore(self, self)

    # ------------------------------------------------------------ survey

    def open_survey(self, path: str | Path) -> None:
        """Load a survey.yaml and tell every tab to reload."""
        self.survey_yaml = Path(path).resolve()
        self.survey = Survey.from_yaml(self.survey_yaml)
        self.site = None
        self._raw_sites = None
        self.segment_store.clear()
        self.selection, self.remote = None, None
        self.selection_changed.emit(None)
        self.survey_changed.emit()
        fetch_basemap_if_missing(self)  # no <workspace>/basemap.json: run fetch_basemap.py now

    def set_site(self, name: str | None) -> None:
        if name != self.site:
            self.site = name or None
            self.site_changed.emit(self.site or "")

    # --------------------------------------------------------- selection

    def set_selection(self, station: str, start, end) -> None:
        """A window was clicked in the tree: it becomes the selection and its QC is requested.

        On a change of station the remote goes back to the station's declared
        `remote:`; while the station stays, a remote picked by hand is kept.
        The station also becomes `site`, so the Process and Filter Data tabs
        follow the tree.
        """
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if self.selection is None or station != self.selection[0]:
            # the segment QC runs on the local pairs by default: the remote
            # pairs answer one narrower question (dead coil or quiet field?)
            # and are switched on from the Coherence tab when needed. The
            # Process tab still presets the station's declared remote.
            self.remote = None
        self.selection = (station, start, end)
        self.set_site(station)
        self.selection_changed.emit(self.selection)
        self.request_qc()

    def set_remote(self, remote: str | None) -> None:
        """The Coherence tab picked a remote: the selection's QC is requested against it."""
        remote = remote or None
        if remote != self.remote:
            self.remote = remote
            self.remote_changed.emit(remote)
            self.request_qc()

    def request_qc(self) -> bool:
        """Ask the store for the selection with the current remote and ladder; False if nothing to do."""
        if self.selection is None:
            return False
        station, start, end = self.selection
        store = self.segment_store
        return store.request(station, start, end, self.remote, store.win_s, store.step_s)

    # ------------------------------------------------------- survey facts

    def raw_sites(self) -> dict[str, Path]:
        """site -> raw data folder, from `Survey.site_dirs()` (cached per survey)."""
        if self.survey is None:
            return {}
        if self._raw_sites is None:
            try:
                self._raw_sites = self.survey.site_dirs()
            except OSError:
                # data_root on an external drive that is not plugged in
                self._raw_sites = {}
        return self._raw_sites

    def configured_sites(self) -> list[str]:
        """Sites named in the YAML `sites:` block."""
        if self.survey is None:
            return []
        return list((self.survey.config.get("sites") or {}).keys())

    def all_sites(self) -> list[str]:
        """Every site the survey knows: configured plus raw folders found."""
        return sorted(set(self.configured_sites()) | set(self.raw_sites()))

    def archive_dir(self) -> Path | None:
        return None if self.survey is None else self.survey.workspace / "mth5"

    def archive_path(self, site: str) -> Path | None:
        d = self.archive_dir()
        return None if d is None else d / f"{site}.h5"

    def has_archive(self, site: str) -> bool:
        p = self.archive_path(site)
        return bool(p and p.exists())

    def processing_archive(self, site: str, use_filters: bool = True) -> tuple[Path | None, bool]:
        """Read-only: (path, is_filtered_variant) for `site` in the open survey.

        The filtered variant (`mtproc.ingest.variant_path`) when `use_filters`
        and it is ready (`mtproc.ingest.variant_ready` -- already built, and
        current for what `filters.yaml` now declares), else the raw archive
        (`archive_path`), flagged False. **Never builds one**: a view that
        only wants to know what it would read (the Cross-powers tab's
        candidate list, this) must not pay a build's cost or side effects --
        only `mtproc.ingest.build_variant`, through `scripts/process_rr.py`
        or the stack builder, does that.
        """
        raw = self.archive_path(site)
        if use_filters and self.survey is not None and variant_ready(self.survey, site):
            return variant_path(self.survey, site), True
        return raw, False

    def archived_sites(self) -> list[str]:
        """Every `<workspace>/mth5/*.h5` stem, whether or not it is a raw site --
        a filtered variant's own stem (``<site>_f<hash>.h5``) is left out: it
        is not a site, just another archive of the one named before the
        `_f<hash>`."""
        d = self.archive_dir()
        if d is None or not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.h5") if not _VARIANT_SUFFIX.search(p.stem))

    def stacked_remotes(self) -> list[str]:
        """Archives with no raw folder: synthetic remotes from scripts/build_stack.py."""
        raw = self.raw_sites()
        return [s for s in self.archived_sites() if s not in raw]

    def remote_choices(self, site: str | None) -> list[tuple[str, str]]:
        """(display, name) remotes for `site`: raw sites plus stacked archives.

        The same list on every tab that takes a remote. There is no
        single-station option anywhere in this GUI.
        """
        out = [(n, n) for n in sorted(self.raw_sites()) if n != site]
        out += [(f"{n}  (stack)", n) for n in self.stacked_remotes() if n != site]
        return out

    def default_remote(self, site: str | None) -> str | None:
        """`survey.yaml`'s declared remote for `site`, if it is a usable one."""
        if self.survey is None or not site:
            return None
        remote = self.survey.site(site).remote
        if not remote:
            return None
        return remote if any(remote == n for _d, n in self.remote_choices(site)) else None

    def filters_yaml(self) -> Path | None:
        """`<survey>/filters.yaml`, whether or not it exists yet."""
        return None if self.survey_yaml is None else self.survey_yaml.parent / "filters.yaml"

    def reference_edis_yaml(self) -> Path | None:
        return None if self.survey_yaml is None else self.survey_yaml.parent / "reference_edis.yaml"

    def qc_dir(self) -> Path | None:
        return None if self.survey is None else self.survey.workspace / "qc"

    def tf_dir(self) -> Path | None:
        return None if self.survey is None else self.survey.workspace / "tf"

    def script(self, name: str) -> str:
        """Absolute path of a script in `scripts/`."""
        return str(self.repo_root / "scripts" / name)


class MainWindow(QMainWindow):
    """Tabbed launcher-and-viewer window over one survey and one job queue."""

    def __init__(self, survey_yaml: str | Path | None = None, parent=None):
        super().__init__(parent)
        # imported here so `app.py` stays importable from a tab module
        from mtproc_gui.tabs.coherence import CoherenceTab
        from mtproc_gui.tabs.crosspower import CrossPowerTab
        from mtproc_gui.tabs.edis import EdiTab
        from mtproc_gui.tabs.filters import FiltersTab
        from mtproc_gui.tabs.metadata import MetadataTab
        from mtproc_gui.tabs.process import ProcessTab
        from mtproc_gui.tabs.spectra import SpectraTab
        from mtproc_gui.tabs.spectrogram import SpectrogramTab
        from mtproc_gui.tabs.timeseries import TimeSeriesTab

        self.setWindowTitle("MT processing")
        self.state = State()

        self.tabs = QTabWidget(self)
        self.metadata_tab = MetadataTab(self.state, self)
        self.timeseries_tab = TimeSeriesTab(self.state, self)
        self.process_tab = ProcessTab(self.state, self)
        self.spectra_tab = SpectraTab(self.state, self)
        self.spectrogram_tab = SpectrogramTab(self.state, self)
        self.coherence_tab = CoherenceTab(self.state, self)
        self.filters_tab = FiltersTab(self.state, self)
        self.edis_tab = EdiTab(self.state, self)
        self.crosspower_tab = CrossPowerTab(self.state, self)
        # the MATLAB app's order: QC tabs, then filters, then processing, then EDIs
        self.tabs.addTab(self.metadata_tab, "Metadata")
        self.tabs.addTab(self.timeseries_tab, "Time Series")
        self.tabs.addTab(self.spectra_tab, "Spectra")
        self.tabs.addTab(self.spectrogram_tab, "Spectrogram")
        self.tabs.addTab(self.coherence_tab, "Coherence")
        self.tabs.addTab(self.filters_tab, "Filter Data")
        self.tabs.addTab(self.process_tab, "Process")
        self.tabs.addTab(self.crosspower_tab, "Cross-powers")
        self.tabs.addTab(self.edis_tab, "View EDIs")

        self.metadata_tab.open_requested.connect(self.choose_survey)
        self.timeseries_tab.processing_window_selected.connect(self.use_processing_window)
        self.process_tab.show_edi_requested.connect(self.show_edi)
        self.state.survey_changed.connect(self.reload_tabs)
        self.state.goto_time.connect(lambda _t: self.tabs.setCurrentWidget(self.timeseries_tab))

        # the console strip: under the tabs in a splitter (console.py)
        self.console = ConsoleStrip(self)
        self._console_sink = LoguruQtSink()
        self._console_sink.line_written.connect(self.console.append, Qt.QueuedConnection)
        self._log_sink_id = logger.add(
            self._console_sink.write, level="INFO", format="{time:HH:mm:ss} | {name} | {message}"
        )
        self.state.runner.log_line.connect(self.console.append)
        self.state.segment_store.qc_started.connect(
            lambda message: self.console.append(f"[segment] {message}"))
        self.console_splitter = QSplitter(Qt.Vertical, self)
        self.console_splitter.addWidget(self.tabs)
        self.console_splitter.addWidget(self.console)
        self.console_splitter.setStretchFactor(0, 1)
        self.console_splitter.setStretchFactor(1, 0)
        self.console_splitter.setSizes([800, self.console.sizeHint().height()])
        self.setCentralWidget(self.console_splitter)

        self._build_menu()
        self.statusBar().showMessage("no survey loaded - File > Open survey...")
        self.resize(1280, 860)

        if survey_yaml:
            self.open_survey(survey_yaml)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open survey...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_survey)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # ------------------------------------------------------------- slots

    def choose_survey(self) -> None:
        start_dir = str(self.state.survey_yaml.parent if self.state.survey_yaml
                        else self.state.repo_root / "surveys")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open survey.yaml", start_dir, "Survey config (*.yaml *.yml);;All files (*)"
        )
        if path:
            self.open_survey(path)

    def open_survey(self, path: str | Path) -> None:
        try:
            self.state.open_survey(path)
        except Exception as exc:  # a bad YAML should not kill the window
            QMessageBox.critical(self, "Could not open survey", f"{path}\n\n{exc}")
            self.statusBar().showMessage(f"could not open {path}: {exc}")
            return
        survey = self.state.survey
        self.statusBar().showMessage(
            f"{survey.name}: {len(self.state.all_sites())} sites, "
            f"data_root {survey.data_root}, workspace {survey.workspace}"
        )

    def reload_tabs(self) -> None:
        for tab in (self.metadata_tab, self.timeseries_tab, self.spectra_tab, self.spectrogram_tab,
                    self.coherence_tab, self.filters_tab, self.process_tab, self.crosspower_tab, self.edis_tab):
            tab.reload()

    def use_processing_window(self, start: str, end: str) -> None:
        """Time Series -> Process: push the selected window onto the Process tab."""
        self.process_tab.set_window(start, end)
        self.tabs.setCurrentWidget(self.process_tab)
        self.statusBar().showMessage(f"processing window set: {start} to {end} UTC")

    def show_edi(self, path: Path) -> None:
        """Process -> View EDIs: tick the EDI a job wrote, and its lemimt reference, and front the tab."""
        path = Path(path)
        self.edis_tab.reload()
        self.edis_tab.check(path.name)
        station = path.stem.split("_rr-")[0]  # <station>_rr-<remote>_<started>[_<tag>].edi
        self.edis_tab.check(f"{station} (lemimt)")
        self.tabs.setCurrentWidget(self.edis_tab)
        self.statusBar().showMessage(f"showing {path.name} against {station}'s lemimt reference")

    def closeEvent(self, event) -> None:
        """Let an archive read in flight finish: Qt aborts the process if a
        running QThread is destroyed with its parent window (a tree read is
        under a second; a segment QC up to a minute). The console strip and
        the loguru sink come off first, so a line arriving mid-teardown is
        dropped, not raised, and the sink outlives neither."""
        self.console.begin_shutdown()
        logger.remove(self._log_sink_id)
        self.timeseries_tab.wait_for_read()
        self.process_tab.window_bar.wait_for_read()
        self.state.segment_store.wait()
        self.filters_tab.wait()  # the filter preview's worker and its chooser's read
        self.crosspower_tab.wait()  # a chunk-impedance compute or a window read
        super().closeEvent(event)
