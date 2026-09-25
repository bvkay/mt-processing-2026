# -*- coding: utf-8 -*-
"""
Copy-filters dialog of the Filter Data tab

Copies one site's filter list onto other sites. A survey can have more than
100 sites, most of which share the same notch declaration (50 Hz and
harmonics plus the same interharmonic lines); the user ticks the target
sites in the dialog.

`CopyFiltersDialog` shows a title line naming the source site's list above a
checkable list of every other site in the survey. Each row is a check box
with the site's name beside a grey label of what that site declares now
("none", or `short_labels()` of its list, e.g. "notch, cp"). Below are
"Select all" and "Clear" buttons, a Replace/Append radio pair and OK/Cancel.
`selected_sites()` and `append()` read the choice back; the Filter Data tab
writes the files (`crust.gui.tabs.filters._write_filters`) and logs the
change.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from crust.gui import theme


def short_labels(entries: list[dict] | None) -> str:
    """Return the kinds of a filter list in declared order, e.g. "notch, cp", or "none" if empty."""
    kinds = [next(iter(entry)) for entry in entries or []]
    return ", ".join(kinds) if kinds else "none"


class CopyFiltersDialog(QDialog):
    """Dialog for ticking the sites that receive `site`'s filter list.

    Args:
        site (str): The source site.
        entries (list[dict]): The source site's filter entries.
        others (dict[str, list[dict]]): Every other site and its current
            filter entries.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, site: str, entries: list[dict], others: dict[str, list[dict]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Copy filters to sites")
        self.resize(420, 480)

        title = QLabel(
            f"Copy {site}'s filter list ({len(entries)} filters: {short_labels(entries)}) to:", self,
            wordWrap=True)

        self.list = QListWidget(self)
        self.boxes: dict[str, QCheckBox] = {}
        for name in sorted(others):
            row = QWidget(self.list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            check = QCheckBox(name, row)
            declared = QLabel(short_labels(others[name]), row)
            declared.setStyleSheet(f"color: {theme.DISABLED}")
            row_layout.addWidget(check)
            row_layout.addWidget(declared, 1)
            item = QListWidgetItem(self.list)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self.boxes[name] = check

        select_all = QPushButton("Select all", self, clicked=self._select_all)
        clear = QPushButton("Clear", self, clicked=self._clear)
        select_row = QHBoxLayout()
        select_row.addWidget(select_all)
        select_row.addWidget(clear)
        select_row.addStretch(1)

        self.replace_radio = QRadioButton("Replace the site's list", self, checked=True)
        self.replace_radio.setToolTip("Each ticked site's list becomes a copy of this one.")
        self.append_radio = QRadioButton("Append to the site's list", self)
        self.append_radio.setToolTip("This list is added to the end of each ticked site's own.")
        radio_row = QHBoxLayout()
        radio_row.addWidget(self.replace_radio)
        radio_row.addWidget(self.append_radio)
        radio_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.list, 1)
        layout.addLayout(select_row)
        layout.addLayout(radio_row)
        layout.addWidget(buttons)

    def _select_all(self) -> None:
        """Tick every site."""
        for box in self.boxes.values():
            box.setChecked(True)

    def _clear(self) -> None:
        """Untick every site."""
        for box in self.boxes.values():
            box.setChecked(False)

    def selected_sites(self) -> list[str]:
        """Return the ticked sites in alphabetical order."""
        return [name for name, box in self.boxes.items() if box.isChecked()]

    def append(self) -> bool:
        """True if Append is chosen; False for Replace (the default)."""
        return self.append_radio.isChecked()
