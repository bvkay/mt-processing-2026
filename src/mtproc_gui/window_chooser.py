"""WindowChooser: the Filter Data tab's site and window combos -- choosing a window loads it.

The Filter Data tab must not need a trip to the Time Series tab to change
windows. The site combo lists every site with an MTH5
archive; the window combo lists that site's windows exactly as the Time
Series tree does (`mtproc_gui.windows.window_list` over
`mtproc_gui.archive.load_grid`, labelled by `window_label`), read in a
`ReadThread` under `State.archive_lock` -- one read at a time, as
`site_tree.py` reads -- with "reading the archive..." meanwhile. Choosing a
window is loading it: `State.set_selection(station, start, end)`, the same
call a click in the tree makes, so the segment store loads it and the Time
Series and QC tabs follow. The combos follow `selection_changed` and
`site_changed` in turn, so they always show what is loaded (or, for a site
picked elsewhere, its windows, nothing loaded until one is chosen). Windows
are only read while the chooser is on screen.
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
    return window_list(load_grid(path, survey_name, station))


class WindowChooser(QWidget):
    """Site combo (archived sites) and window combo (that site's windows); choosing loads."""

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
        return self.site_combo.currentText() or None

    def reload(self) -> None:
        """The survey (or a site's archive) changed: list the archived sites again."""
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
        """The loaded window changed (here, in the tree, anywhere): show it."""
        if selection is not None:
            self._select_site(selection[0])

    def _site_picked(self, _index: int) -> None:
        """A site chosen here loads its first window on its own."""
        self._auto_first = True
        self._show_windows(self.site())

    def _select_site(self, site: str | None) -> None:
        self._auto_first = False  # following a selection made elsewhere: nothing to load
        index = self.site_combo.findText(site or "")
        self.site_combo.blockSignals(True)
        self.site_combo.setCurrentIndex(index)
        self.site_combo.blockSignals(False)
        self._show_windows(self.site())

    def _show_windows(self, site: str | None) -> None:
        """Fill the window combo with `site`'s windows, the loaded one current; read them first if needed.

        When the combo already lists `site`'s windows only the current row
        moves: this runs inside the combo's own signal when a choice here
        loads a window, and the combo is not emptied under its own handler.

        The loaded row (only) is marked every time this runs, so the mark
        follows a change of window from anywhere -- this combo, the Time
        Series tree, or a different site's windows replacing the list: which
        window is open is visible without a trip to the combo's popup. The
        row's data (`itemData(k)`, the (start, end) tuple
        `_window_chosen` reads) is never touched here, only its text and the
        FontRole/ForegroundRole the popup's delegate paints it with.
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
        site, window = self.site(), self.window_combo.itemData(index)
        if site and window is not None and self.state.selection != (site, *window):
            self.state.set_selection(site, *window)

    # ------------------------------------------------------------ reads

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._kick()  # a site chosen elsewhere while the tab was hidden

    def _kick(self) -> None:
        """Read the wanted site's windows if on screen, no read runs and the archive lock is free.

        Only on screen: a window clicked in the Time Series tree also sets the
        site, and the segment store must get the lock first, not this read.
        """
        site, lock = self._wanted, self.state.archive_lock
        if self._thread is not None or site is None or self.state.survey is None or not self.isVisible():
            return
        if lock.busy and lock.holder is not self:
            return  # `changed` brings us back here
        self._wanted = None
        path = self.state.archive_path(site)
        thread = ReadThread(_windows_for, (site, path), path, self.state.survey.name, site, parent=self)
        thread.result.connect(self._on_windows)
        thread.failed.connect(lambda _tag, message: self.window_combo.setPlaceholderText(
            f"could not read the archive: {message}"))
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # before acquire: its `changed` re-enters _kick, which must see it
        lock.acquire(self)
        thread.start()

    def _read_done(self) -> None:
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for a site wanted meanwhile

    def _on_windows(self, tag, windows) -> None:
        site, path = tag
        if path != self.state.archive_path(site):
            return  # the survey changed under the read
        self._windows[site] = list(windows)
        if self.site() == site:
            self._show_windows(site)

    def wait_for_read(self) -> None:
        """Block until the read in flight returns and start no other (the window is closing)."""
        self._wanted = None
        if self._thread is not None:
            self._thread.wait()
