# -*- coding: utf-8 -*-
"""
Site and window chooser of the Filter Data tab

`WindowChooser` lets the Filter Data tab change windows directly. The site
combo lists every site with an MTH5 archive; the window combo lists that
site's windows as the Time Series tree does (`mtproc_gui.windows.window_list`
over `mtproc_gui.archive.load_grid`, labelled by `window_label`). Windows are
read in a `ReadThread` under `State.archive_lock`, one read at a time as in
`site_tree.py`, with "reading the archive..." shown meanwhile, and only while
the chooser is visible.

Choosing a window loads it through `State.set_selection(station, start,
end)`, the same call a click in the tree makes, so the segment store loads
it and the Time Series and QC tabs follow. The combos follow
`selection_changed` and `site_changed`, so they show the loaded window, or,
for a site chosen elsewhere, its windows with none loaded until one is
picked.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from mtproc_gui import theme
from mtproc_gui.archive import load_grid
from mtproc_gui.reader import ReadThread
from mtproc_gui.windows import window_label, window_list

READING = "reading the archive..."
PICK = "pick a window to load it"
LOADED_SUFFIX = "   (loaded)"


def _windows_for(path, survey_name: str, station: str):
    """Return the station's windows from its run grid; run in the read thread."""
    return window_list(load_grid(path, survey_name, station))


class WindowChooser(QWidget):
    """Site combo of archived sites and window combo of that site's windows; choosing a window loads it.

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._windows: dict[str, list] = {}  # site -> [(start, end)], per survey
        self._wanted: str | None = None  # the site whose windows are to be read next
        self._shown: str | None = None  # the site whose windows the window combo lists
        self._thread: ReadThread | None = None
        self.site_combo = QComboBox(self, minimumWidth=90)
        self.window_combo = QComboBox(self, minimumWidth=230, placeholderText=PICK)
        self._auto_first = False
        self.site_combo.currentIndexChanged.connect(self._site_picked)
        self.window_combo.currentIndexChanged.connect(self._window_chosen)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Site", self))
        layout.addWidget(self.site_combo)
        layout.addWidget(QLabel("Window", self))
        layout.addWidget(self.window_combo)
        state.selection_changed.connect(self.follow)
        state.site_changed.connect(lambda site: self._select_site(site) if site else None)
        state.archive_changed.connect(lambda _site: self.reload())
        state.archive_lock.changed.connect(self._kick)

    def site(self) -> str | None:
        """Return the site in the site combo, or None."""
        return self.site_combo.currentText() or None

    def reload(self) -> None:
        """List the archived sites again after a survey or archive change."""
        self._windows.clear()
        self._shown = None
        keep = self.state.selection[0] if self.state.selection else self.state.site
        self.site_combo.blockSignals(True)
        self.site_combo.clear()
        self.site_combo.addItems([s for s in self.state.all_sites() if self.state.has_archive(s)])
        self.site_combo.setCurrentIndex(-1)
        self.site_combo.blockSignals(False)
        self._select_site(keep)

    def follow(self, selection) -> None:
        """Show the loaded window after a selection change from any source."""
        if selection is not None:
            self._select_site(selection[0])

    def _site_picked(self, _index: int) -> None:
        """Show a site chosen here and load its first window."""
        self._auto_first = True
        self._show_windows(self.site())

    def _select_site(self, site: str | None) -> None:
        """Select a site chosen elsewhere without loading a window."""
        self._auto_first = False  # following a selection made elsewhere: nothing to load
        index = self.site_combo.findText(site or "")
        self.site_combo.blockSignals(True)
        self.site_combo.setCurrentIndex(index)
        self.site_combo.blockSignals(False)
        self._show_windows(self.site())

    def _show_windows(self, site: str | None) -> None:
        """Fill the window combo with `site`'s windows, the loaded one current, reading them first if needed.

        When the combo already lists `site`'s windows only the current row
        moves, since this runs inside the combo's own signal when a choice
        here loads a window.

        The loaded row is marked (bold, accent colour, "(loaded)") on every
        call, so the mark follows a window change from this combo, the Time
        Series tree or a different site's list. Only the row's text and its
        FontRole and ForegroundRole change; its data (`itemData(k)`, the
        (start, end) tuple `_window_chosen` reads) is left as is.
        """
        combo, windows = self.window_combo, self._windows.get(site)
        combo.blockSignals(True)
        if windows is None or site != self._shown:
            combo.clear()
            self._shown = site if windows is not None else None
            combo.setPlaceholderText(PICK if windows is not None or site is None else READING)
            for start, end in windows or []:
                combo.addItem(window_label(start, end), (start, end))
        selection = self.state.selection
        index = -1
        if windows and selection is not None and selection[0] == site:
            index = next((k for k, w in enumerate(windows) if (site, *w) == selection), -1)
        combo.setCurrentIndex(index)
        bold = QFont(combo.font())
        bold.setBold(True)
        accent = QBrush(QColor(theme.HIGHLIGHT))
        for k, (start, end) in enumerate(windows or []):
            loaded = k == index
            combo.setItemText(k, window_label(start, end) + (LOADED_SUFFIX if loaded else ""))
            combo.setItemData(k, bold if loaded else None, Qt.FontRole)
            combo.setItemData(k, accent if loaded else None, Qt.ForegroundRole)
        combo.blockSignals(False)
        if windows and self._auto_first:
            self._auto_first = False
            if combo.currentIndex() < 0:
                combo.setCurrentIndex(0)  # signals on: `_window_chosen` loads the first window
        if site is not None and windows is None:
            self._wanted = site
            self._kick()

    def _window_chosen(self, index: int) -> None:
        """Load the chosen window through `State.set_selection` unless it is already loaded."""
        site, window = self.site(), self.window_combo.itemData(index)
        if site and window is not None and self.state.selection != (site, *window):
            self.state.set_selection(site, *window)

    # ------------------------------------------------------------ reads

    def showEvent(self, event) -> None:
        """Start a read wanted while the tab was hidden."""
        super().showEvent(event)
        self._kick()  # a site chosen elsewhere while the tab was hidden

    def _kick(self) -> None:
        """Read the wanted site's windows when visible, idle and the archive lock is free.

        Reads wait until the chooser is visible because a window clicked in
        the Time Series tree also sets the site, and the segment store takes
        the lock first.
        """
        site, lock = self._wanted, self.state.archive_lock
        if self._thread is not None or site is None or self.state.survey is None or not self.isVisible():
            return
        if lock.busy and lock.holder is not self:
            return  # `changed` calls this again
        self._wanted = None
        path = self.state.archive_path(site)
        thread = ReadThread(_windows_for, (site, path), path, self.state.survey.name, site, parent=self)
        thread.result.connect(self._on_windows)
        thread.failed.connect(lambda _tag, message: self.window_combo.setPlaceholderText(
            f"could not read the archive: {message}"))
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # set before acquire, since its `changed` re-enters _kick
        lock.acquire(self)
        thread.start()

    def _read_done(self) -> None:
        """Release the archive lock after a read."""
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for a site wanted meanwhile

    def _on_windows(self, tag, windows) -> None:
        """Cache a site's windows and show them if the site is still selected."""
        site, path = tag
        if path != self.state.archive_path(site):
            return  # the survey changed under the read
        self._windows[site] = list(windows)
        if self.site() == site:
            self._show_windows(site)

    def wait_for_read(self) -> None:
        """Block until the read in flight returns, dropping the wanted read; used on window close."""
        self._wanted = None
        if self._thread is not None:
            self._thread.wait()
