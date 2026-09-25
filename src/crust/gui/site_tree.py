# -*- coding: utf-8 -*-
"""
Site tree of the Time Series tab

`SiteTree` is a `QTreeWidget` with one bold, collapsed row per site in
`State.all_sites()`, whose child rows are the site's archive windows rather
than raw files. A site with an archive is expandable; its window rows
(`crust.gui.windows.window_list` over `crust.gui.archive.load_grid`,
labelled by their UTC start) are built the first time it is expanded. The
archive read runs in a `ReadThread` under `State.archive_lock`, one site at
a time, with sites expanded meanwhile queued and a "reading the archive..."
row shown until the read returns. A site without an archive is greyed, with
one disabled row pointing to the tab's Build MTH5 button; `refresh_site`
checks the archive again once a job has built it. Clicking a site row
expands or collapses it; clicking a window row emits
`window_clicked(station, start, end)` and the tab loads that window.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from crust.gui.archive import load_grid
from crust.gui.reader import ReadThread
from crust.gui.windows import window_label, window_list

SITE_ROLE = Qt.UserRole  # a site row's station name
WINDOW_ROLE = Qt.UserRole + 1  # a window row's (start, end)
NO_ARCHIVE = "no MTH5 yet - select the site and press Build MTH5"
READING = "reading the archive..."
GREY = QBrush(QColor("#909090"))


def _windows_for(path, survey_name: str, station: str):
    """Return the station's windows from its run grid; run in the read thread."""
    return window_list(load_grid(path, survey_name, station))


class SiteTree(QTreeWidget):
    """Sites as bold collapsed rows; archived sites expand to their windows.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    window_clicked = Signal(str, object, object)  # (station, start, end)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._items: dict[str, QTreeWidgetItem] = {}
        self._archived: dict[str, bool] = {}  # what each site row shows
        self._filled: set[str] = set()
        self._queue: list[str] = []  # sites expanded while a read was running
        self._thread: ReadThread | None = None
        self.setHeaderLabels(["Sites"])
        self.setExpandsOnDoubleClick(False)  # a single click on the row toggles it
        self.setMinimumWidth(220)
        self.itemExpanded.connect(self._expanded)
        self.itemClicked.connect(self._clicked)
        self.state.archive_lock.changed.connect(self._kick)  # a read may have been waiting

    # ------------------------------------------------------------ rows

    def reload(self) -> None:
        """Rebuild the rows from the survey; a read in flight is discarded on return."""
        self._queue.clear()
        self._filled.clear()
        self._items.clear()
        self._archived.clear()
        self.clear()
        bold = self.font()
        bold.setBold(True)
        for site in self.state.all_sites():
            item = QTreeWidgetItem(self, [site])
            item.setData(0, SITE_ROLE, site)
            item.setFont(0, bold)
            item.setExpanded(False)
            self._items[site] = item
            self._show_archive(site)

    def _show_archive(self, site: str) -> None:
        """Show whether `site` has an archive: expandable, or grey with the Build MTH5 hint."""
        item, has = self._items[site], self.state.has_archive(site)
        self._archived[site] = has
        item.takeChildren()
        if has:
            item.setToolTip(0, str(self.state.archive_path(site)))
            item.setData(0, Qt.ForegroundRole, None)  # the default text colour again
            # expandable before it has children: they are read on demand
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        else:
            item.setToolTip(0, "")
            item.setForeground(0, GREY)
            child = QTreeWidgetItem(item, [NO_ARCHIVE])
            child.setFlags(Qt.NoItemFlags)

    def refresh_site(self, site: str, expand: bool = False) -> None:
        """Check `site`'s archive again, e.g. after a job built it.

        A row whose archive state changed is rebuilt, so a new archive
        replaces the placeholder and becomes expandable.

        Args:
            site (str): Site name.
            expand (bool): Expand the row and read its windows.
        """
        if site not in self._items:
            return
        if self.state.has_archive(site) != self._archived.get(site):
            self._filled.discard(site)
            self._show_archive(site)
        if expand and self._archived[site]:
            self._items[site].setExpanded(False)  # an open row would not signal again
            self._items[site].setExpanded(True)  # `_expanded` reads its windows

    def site_items(self) -> list[QTreeWidgetItem]:
        """Return the site rows."""
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def window_items(self, site: str) -> list[QTreeWidgetItem]:
        """Return the window rows under `site`; empty until it has been expanded and read."""
        item = self._items.get(site)
        if item is None:
            return []
        rows = [item.child(i) for i in range(item.childCount())]
        return [r for r in rows if r.data(0, WINDOW_ROLE) is not None]

    def select_site(self, site: str) -> None:
        """Highlight `site`'s row after a choice on another tab, without loading anything."""
        item, current = self._items.get(site), self.currentItem()
        if item is None or current is item or (current is not None and current.parent() is item):
            return  # already on that site, or on one of its windows: leave the highlight there
        self.setCurrentItem(item)
        self.scrollToItem(item)

    # ----------------------------------------------------------- clicks

    def _clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Emit `window_clicked` for a window row; toggle a site row."""
        window = item.data(0, WINDOW_ROLE)
        if window is not None:
            self.window_clicked.emit(item.parent().data(0, SITE_ROLE), *window)
        elif item.data(0, SITE_ROLE) is not None:
            item.setExpanded(not item.isExpanded())

    def _expanded(self, item: QTreeWidgetItem) -> None:
        """On the first expansion of an archived site, show a placeholder and queue its read."""
        site = item.data(0, SITE_ROLE)
        if site is None or site in self._filled or not self.state.has_archive(site):
            return
        if item.childCount() == 0:
            placeholder = QTreeWidgetItem(item, [READING])
            placeholder.setFlags(Qt.NoItemFlags)
        if site not in self._queue:
            self._queue.append(site)
        self._kick()

    # ------------------------------------------------------------ reads

    def _kick(self) -> None:
        """Start the next queued read if none runs and the archive lock is free."""
        lock = self.state.archive_lock
        if self._thread is not None or not self._queue or self.state.survey is None:
            return
        if lock.busy and lock.holder is not self:
            return  # the segment worker is loading: `changed` calls this again
        site = self._queue.pop(0)
        path = self.state.archive_path(site)
        thread = ReadThread(_windows_for, (site, path), path, self.state.survey.name, site, parent=self)
        thread.result.connect(self._on_windows)
        thread.failed.connect(self._on_failed)
        thread.finished.connect(self._read_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread  # set before acquire, since its `changed` re-enters _kick
        lock.acquire(self)
        thread.start()

    def _read_done(self) -> None:
        """Release the archive lock after a read."""
        self._thread = None
        self.state.archive_lock.release(self)  # its `changed` runs _kick for the next site

    def wait_for_read(self) -> None:
        """Block until the read in flight returns, dropping queued reads; used on window close."""
        self._queue.clear()
        if self._thread is not None:
            self._thread.wait()

    def _current(self, tag) -> QTreeWidgetItem | None:
        """Return the site row a read was for, or None if the survey has changed since."""
        site, path = tag
        item = self._items.get(site)
        return item if item is not None and path == self.state.archive_path(site) else None

    def _on_windows(self, tag, windows) -> None:
        """Replace the placeholder with the site's window rows."""
        item = self._current(tag)
        if item is None:
            return
        item.takeChildren()
        for start, end in windows:
            row = QTreeWidgetItem(item, [window_label(start, end)])
            row.setData(0, WINDOW_ROLE, (start, end))
            row.setToolTip(0, f"{start:%Y-%m-%d %H:%M:%S} to {end:%Y-%m-%d %H:%M:%S} UTC")
        self._filled.add(tag[0])

    def _on_failed(self, tag, message: str) -> None:
        """Replace the placeholder with the read error."""
        item = self._current(tag)
        if item is None:
            return
        item.takeChildren()
        row = QTreeWidgetItem(item, [f"could not read the archive: {message}"])
        row.setFlags(Qt.NoItemFlags)  # collapse and expand again to retry
