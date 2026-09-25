# -*- coding: utf-8 -*-
"""
Main window and shared application state

`State` holds the survey the window is showing (the `survey.yaml` path, the
`crust.survey.Survey` built from it and the selected site), the repo root
used as the working directory of every subprocess, and the Python executable
that runs the scripts. Tabs ask `State` for everything they need about the
survey, so opening a different survey is one signal and one `reload()` per
tab.

`State` owns the window's single `JobRunner`. Every tab queues on
`state.runner`, so the GUI runs one job at a time and an MTH5 file is open in
one process at a time; the Process tab's `queue_table.QueuePanel` lists every
job. Opening a survey with no basemap fetches one through
`site_map.fetch_basemap_if_missing`.

`State` also carries what the Time Series tab and the QC tabs share:

* `selection`: the (station, start, end) UTC window clicked in the Time Series
  tree, or None; emitted on `selection_changed`.
* `remote`: the remote the QC is computed against, chosen on the Coherence
  tab and reset to None on every new station; emitted on `remote_changed`.
* `segment_store`: the `crust.gui.segment_store.SegmentStore` that loads the
  selected window and computes its QC off the GUI thread.
* `archive_lock`: the `ArchiveLock` that keeps the store's worker and the
  tree's archive reads from opening a file at the same time.
* `goto_time`: emitted by any tab to put the Time Series view on a moment.

`request_qc()` asks the store for the selection with the current remote and
window ladder.

`MainWindow` is a QTabWidget over nine tabs in this order (QC
first: Metadata, Time Series, Spectra, Spectrogram, Coherence; then Filter
Data, Cross-powers, Process, View EDIs), with a status bar, a File menu and,
below the tabs in a vertical `QSplitter`, the `console.ConsoleStrip` showing
the runner's log, loguru output and `qc_started` messages.

@author: ben kay (ben@auscope.org.au)

:license: MIT
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

from crust.ingest import variant_path, variant_ready
from crust.survey import OBSERVATORY, Survey
from crust.gui.console import ConsoleStrip, LoguruQtSink
from crust.gui.jobs import JobRunner
from crust.gui.reader import ArchiveLock
from crust.gui.segment_store import SegmentStore
from crust.gui.site_map import fetch_basemap_if_missing

# src/crust/gui/app.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
# stem of a filtered variant (`<site>_f<hash>.h5`, `crust.ingest.variant_path`);
# such a file is another archive of the site named before the `_f<hash>`
_VARIANT_SUFFIX = re.compile(r"_f[0-9a-f]{8}$")


class State(QObject):
    """Survey, site, selection and job queue shared by every tab.

    Emits `survey_changed` and `site_changed` when either changes, and
    `selection_changed`, `remote_changed`, `goto_time` and `archive_changed`
    for the QC tabs.

    Args:
        repo_root (Path | str): Repository root, the working directory of
            every script run. Defaults to the root above this package.
        parent (QObject | None): Qt parent.
    """

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
        # the queue the whole window shares: one job at a time
        self.runner = JobRunner(self.repo_root, self)
        self.survey_yaml: Path | None = None
        self.survey: Survey | None = None
        self.site: str | None = None
        self._raw_sites: dict[str, Path] | None = None
        # the selected window, its remote, and the in-process worker that reads
        # and QCs it; the lock keeps that worker and the tree's reads apart
        self.selection: tuple[str, pd.Timestamp, pd.Timestamp] | None = None
        self.remote: str | None = None
        self.archive_lock = ArchiveLock(self)
        self.segment_store = SegmentStore(self, self)

    # ------------------------------------------------------------ survey

    def open_survey(self, path: str | Path) -> None:
        """Load a survey.yaml and tell every tab to reload.

        Clears the site, the selection, the remote and the segment store, then
        fetches a basemap if the workspace has none.

        Args:
            path (str | Path): The survey YAML to open.
        """
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
        """Set the selected site and emit `site_changed` if it differs."""
        if name != self.site:
            self.site = name or None
            self.site_changed.emit(self.site or "")

    # --------------------------------------------------------- selection

    def set_selection(self, station: str, start, end) -> None:
        """Make a window clicked in the tree the selection and request its QC.

        On a change of station the remote is reset to None, so the segment QC
        runs on the local pairs; while the station stays the same, a remote
        picked on the Coherence tab is kept. The station also becomes `site`,
        so the Process and Filter Data tabs follow the tree.

        Args:
            station (str): Station name.
            start: Window start, anything `pd.Timestamp` accepts (UTC).
            end: Window end, anything `pd.Timestamp` accepts (UTC).
        """
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if self.selection is None or station != self.selection[0]:
            # the segment QC runs on the local pairs by default; the remote
            # pairs, which separate a dead coil from a quiet field, are
            # switched on from the Coherence tab. The Process tab presets the
            # station's declared remote.
            self.remote = None
        self.selection = (station, start, end)
        self.set_site(station)
        self.selection_changed.emit(self.selection)
        self.request_qc()

    def set_remote(self, remote: str | None) -> None:
        """Set the remote chosen on the Coherence tab and request the QC against it.

        Args:
            remote (str | None): Remote station name, or None for local pairs.
        """
        remote = remote or None
        if remote != self.remote:
            self.remote = remote
            self.remote_changed.emit(remote)
            self.request_qc()

    def request_qc(self) -> bool:
        """Request the selection's QC with the current remote and window ladder.

        Returns:
            bool: The store's answer to the request; False when there is no
            selection.
        """
        if self.selection is None:
            return False
        station, start, end = self.selection
        store = self.segment_store
        return store.request(station, start, end, self.remote, store.win_s, store.step_s)

    # ------------------------------------------------------- survey facts

    def raw_sites(self) -> dict[str, Path]:
        """Map each site to its raw data folder.

        Uses `Survey.site_dirs()` and caches the result per survey. An
        unreachable `data_root` (for example an unplugged external drive)
        gives an empty mapping.

        Returns:
            dict[str, Path]: Site name to raw data folder.
        """
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
        """`<workspace>/mth5`, or None with no survey open."""
        return None if self.survey is None else self.survey.workspace / "mth5"

    def archive_path(self, site: str) -> Path | None:
        """`<workspace>/mth5/<site>.h5`, or None with no survey open."""
        d = self.archive_dir()
        return None if d is None else d / f"{site}.h5"

    def has_archive(self, site: str) -> bool:
        """True if the site's raw archive exists."""
        p = self.archive_path(site)
        return bool(p and p.exists())

    def processing_archive(self, site: str, use_filters: bool = True) -> tuple[Path | None, bool]:
        """Return the archive processing would read for `site`.

        Returns the filtered variant (`crust.ingest.variant_path`) when
        `use_filters` is set and the variant is ready
        (`crust.ingest.variant_ready`: built and current for the filters
        `filters.yaml` declares), otherwise the raw archive (`archive_path`).
        The lookup has no side effects; variants are built by
        `crust.ingest.build_variant`, called from `scripts/process_rr.py` and
        the stack builder.

        Args:
            site (str): Site name.
            use_filters (bool): Prefer the filtered variant when it is ready.

        Returns:
            tuple[Path | None, bool]: The archive path and whether it is the
            filtered variant.
        """
        raw = self.archive_path(site)
        if use_filters and self.survey is not None and variant_ready(self.survey, site):
            return variant_path(self.survey, site), True
        return raw, False

    def archived_sites(self) -> list[str]:
        """List every `<workspace>/mth5/*.h5` stem, raw site or not.

        Filtered variants (``<site>_f<hash>.h5``) are left out, since each is
        another archive of the site named before the `_f<hash>`.

        Returns:
            list[str]: Sorted archive stems.
        """
        d = self.archive_dir()
        if d is None or not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.h5") if not _VARIANT_SUFFIX.search(p.stem))

    def stacked_remotes(self) -> list[str]:
        """Archives with no raw folder: stacks from scripts/build_stack.py, observatories and derived sites (`archive_kind`)."""
        raw = self.raw_sites()
        return [s for s in self.archived_sites() if s not in raw]

    def remote_choices(self, site: str | None) -> list[tuple[str, str]]:
        """List the remotes available to `site`: raw sites plus stacked archives.

        Every tab that takes a remote uses this list. It has no single-station
        entry; the GUI processes remote reference only.

        Args:
            site (str | None): The local site, left out of the list.

        Returns:
            list[tuple[str, str]]: (display label, remote name) pairs.
        """
        out = [(n, n) for n in sorted(self.raw_sites()) if n != site]
        out += [(f"{n}  ({self.archive_kind(n)})", n) for n in self.stacked_remotes() if n != site]
        return out

    def archive_kind(self, name: str) -> str:
        """Describe an archive with no raw folder, for the remote lists.

        Args:
            name (str): Archive stem.

        Returns:
            str: "derived from <parent>, <rate> Hz" for a derived site,
            "observatory, <rate> Hz" for an INTERMAGNET entry, else "stack".
        """
        if self.survey is None:
            return "stack"
        parent = self.survey.parent_of(name)
        rate = self.survey.sample_rate_of(name)
        if parent:
            return f"derived from {parent}, {rate:g} Hz"
        if ((self.survey.config.get("sites") or {}).get(name) or {}).get("instrument") == OBSERVATORY:
            return f"observatory, {rate:g} Hz"
        return "stack"

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
        """`<survey>/reference_edis.yaml`, whether or not it exists yet."""
        return None if self.survey_yaml is None else self.survey_yaml.parent / "reference_edis.yaml"

    def qc_dir(self) -> Path | None:
        """`<workspace>/qc`, or None with no survey open."""
        return None if self.survey is None else self.survey.workspace / "qc"

    def tf_dir(self) -> Path | None:
        """`<workspace>/tf`, or None with no survey open."""
        return None if self.survey is None else self.survey.workspace / "tf"

    def script(self, name: str) -> str:
        """Absolute path of a script in `scripts/`."""
        return str(self.repo_root / "scripts" / name)


class MainWindow(QMainWindow):
    """Tabbed launcher and viewer window over one survey and one job queue.

    Args:
        survey_yaml (str | Path | None): Survey to open on start.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, survey_yaml: str | Path | None = None, parent=None):
        super().__init__(parent)
        # imported here so `app.py` stays importable from a tab module
        from crust.gui.tabs.coherence import CoherenceTab
        from crust.gui.tabs.crosspower import CrossPowerTab
        from crust.gui.tabs.edis import EdiTab
        from crust.gui.tabs.filters import FiltersTab
        from crust.gui.tabs.metadata import MetadataTab
        from crust.gui.tabs.process import ProcessTab
        from crust.gui.tabs.spectra import SpectraTab
        from crust.gui.tabs.spectrogram import SpectrogramTab
        from crust.gui.tabs.timeseries import TimeSeriesTab

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
        # tab order: QC tabs, then filters, then processing, then EDIs
        self.tabs.addTab(self.metadata_tab, "Metadata")
        self.tabs.addTab(self.timeseries_tab, "Time Series")
        self.tabs.addTab(self.spectra_tab, "Spectra")
        self.tabs.addTab(self.spectrogram_tab, "Spectrogram")
        self.tabs.addTab(self.coherence_tab, "Coherence")
        self.tabs.addTab(self.filters_tab, "Filter Data")
        self.tabs.addTab(self.crosspower_tab, "Cross-powers")
        self.tabs.addTab(self.process_tab, "Process")
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
        """Ask for a survey.yaml with a file dialog and open it."""
        start_dir = str(self.state.survey_yaml.parent if self.state.survey_yaml
                        else self.state.repo_root / "surveys")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open survey.yaml", start_dir, "Survey config (*.yaml *.yml);;All files (*)"
        )
        if path:
            self.open_survey(path)

    def open_survey(self, path: str | Path) -> None:
        """Open a survey, reporting a load error in a message box and the status bar."""
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
        """Call `reload()` on every tab."""
        for tab in (self.metadata_tab, self.timeseries_tab, self.spectra_tab, self.spectrogram_tab,
                    self.coherence_tab, self.filters_tab, self.process_tab, self.crosspower_tab, self.edis_tab):
            tab.reload()

    def use_processing_window(self, start: str, end: str) -> None:
        """Set the window chosen on the Time Series tab on the Process tab and show it."""
        self.process_tab.set_window(start, end)
        self.tabs.setCurrentWidget(self.process_tab)
        self.statusBar().showMessage(f"processing window set: {start} to {end} UTC")

    def show_edi(self, path: Path) -> None:
        """Show an EDI written by a Process job on the View EDIs tab.

        Ticks the EDI and the station's lemimt reference, then brings the tab
        to the front.

        Args:
            path (Path): The EDI, named
                ``<station>_rr-<remote>_<started>[_<tag>].edi``.
        """
        path = Path(path)
        self.edis_tab.reload()
        self.edis_tab.check(path.name)
        station = path.stem.split("_rr-")[0]  # <station>_rr-<remote>_<started>[_<tag>].edi
        self.edis_tab.check(f"{station} (lemimt)")
        self.tabs.setCurrentWidget(self.edis_tab)
        self.statusBar().showMessage(f"showing {path.name} against {station}'s lemimt reference")

    def closeEvent(self, event) -> None:
        """Wait for archive reads in flight, then close.

        Qt aborts the process if a running QThread is destroyed with its
        parent window. A tree read takes under a second and a segment QC up
        to a minute. The console strip and the loguru sink are detached
        first, so a log line arriving during teardown is dropped.
        """
        self.console.begin_shutdown()
        logger.remove(self._log_sink_id)
        self.timeseries_tab.wait_for_read()
        self.process_tab.window_bar.wait_for_read()
        self.state.segment_store.wait()
        self.filters_tab.wait()  # the filter preview's worker and its chooser's read
        self.crosspower_tab.wait()  # a chunk-impedance compute or a window read
        super().closeEvent(event)
