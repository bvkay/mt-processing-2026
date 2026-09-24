# -*- coding: utf-8 -*-
"""
Channels column of the Metadata tab

Holds the cell, its combo-box editor and the rule for saving it. The set of
recorder columns that carried a sensor is declared per survey
(`mtproc.survey.CHANNEL_PRESETS`) once in `defaults: channels:`; a site that
differs, such as a dedicated remote with magnetics only or a deployment with
a Bz coil, has its own `channels:` key.

The cell shows the site's effective set as its preset label
(`mtproc.survey.preset_label`, e.g. "Ex Ey Bx By"), or the list itself when it
matches no preset. Double-click or F2 opens a combo of the presets of the
site's instrument (`Survey.instrument_of`) plus "custom...", which asks for a
list (`ask_channels`). On save, `edit` writes the site's `channels:` when the
set differs from the survey default and drops the key when it matches the
default again; as for every other column, only changed cells are written.

Ingest applies the set, so on a site whose archive exists the cell is greyed
with `ARCHIVE_TIP` as its tooltip. The archive keeps the set it was built
with until it is deleted and built again.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QInputDialog, QStyledItemDelegate

from mtproc.survey import CHANNEL_PRESETS, channels_from_label, preset_label
from mtproc_gui.theme import DISABLED

CUSTOM = "custom..."
ARCHIVE_TIP = "archive built with the old set - Delete archive then Build MTH5 to change it"
UNCHANGED = object()  # `edit`'s answer for a cell whose set is the one loaded


def cell(item_class, channels: list[str] | None, instrument: str, archived: bool):
    """Build the site's channels cell.

    Args:
        item_class: Table item class, called as `item_class(label, editable=True)`.
        channels (list[str] | None): The site's effective channel set.
        instrument (str): The site's instrument key.
        archived (bool): Grey the cell and set `ARCHIVE_TIP` as its tooltip.

    Returns:
        The table item.
    """
    item = item_class(preset_label(channels, instrument), editable=True)
    if archived:
        item.setForeground(QColor(DISABLED))
        item.setToolTip(ARCHIVE_TIP)
    return item


def _same(a: list[str] | None, b: list[str] | None) -> bool:
    """True if two channel sets are equal, ignoring order and case; None ("every column") equals only None."""
    if a is None or b is None:
        return a is b
    return sorted(str(c).lower() for c in a) == sorted(str(c).lower() for c in b)


def edit(survey, item, shown: str | None, site: str | None = None):
    """Work out the site's `channels:` value to write from an edited cell.

    Args:
        survey: The open `mtproc.survey.Survey`.
        item: The channels cell, or None.
        shown (str | None): The cell text as loaded.
        site (str | None): Site name, used to look up its instrument.

    Returns:
        `UNCHANGED` when the cell's set is the one loaded; None when the new
        set equals the survey default, so the site's key is dropped;
        otherwise the list of channel names.
    """
    if item is None or shown is None or item.text() == shown:
        return UNCHANGED
    instrument = survey.instrument_of(site) if site else survey.instrument
    new = channels_from_label(item.text(), instrument)
    if _same(new, channels_from_label(shown, instrument)):
        return UNCHANGED
    return None if _same(new, survey.defaults.get("channels")) else new


def ask_channels(parent, current: str) -> str | None:
    """Prompt for a custom channel list; return the typed text, or None when cancelled or blank."""
    text, ok = QInputDialog.getText(
        parent, "Channels recorded",
        "Channels with a sensor, comma separated, as the reader names them (e.g. ex, ey, hx, hy, hz):",
        text=current)
    return text.strip() if ok and text.strip() else None


class ChannelsDelegate(QStyledItemDelegate):
    """Editor of the channels column: the presets of the row's instrument plus "custom...".

    A choice commits at once. "custom..." asks for a list; a list matching a
    preset comes back as that preset's label, any other as "a, b, c".

    Args:
        state: The shared `mtproc_gui.app.State`.
        parent (QObject | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state

    def _instrument(self, index) -> str:
        """Return the instrument of the row's site (column 0), else the survey's."""
        survey = self.state.survey
        if survey is None:
            return "lemi423"
        site = index.sibling(index.row(), 0).data(Qt.DisplayRole)
        return survey.instrument_of(site) if site else survey.instrument

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setProperty("instrument", self._instrument(index))
        combo.addItems([*CHANNEL_PRESETS.get(combo.property("instrument"), {}), CUSTOM])
        combo.activated.connect(lambda _i, c=combo: self._chosen(c))
        return combo

    def setEditorData(self, editor, index):
        text = index.data(Qt.DisplayRole) or ""
        if editor.findText(text) < 0:  # a custom set (or "all columns") is offered as it is
            editor.insertItem(editor.count() - 1, text)
        editor.setCurrentIndex(editor.findText(text))
        editor.setProperty("loaded", text)

    def setModelData(self, editor, model, index):
        if editor.currentText() != CUSTOM:
            model.setData(index, editor.currentText())

    def _chosen(self, combo: QComboBox) -> None:
        if combo.currentText() == CUSTOM:
            loaded, instrument = combo.property("loaded"), combo.property("instrument")
            channels = channels_from_label(loaded, instrument)
            # the prompt is the combo's child, so the editor keeps focus while it is open
            typed = ask_channels(combo, ", ".join(channels or []))
            names = channels_from_label(typed, instrument) if typed else None
            label = preset_label(names, instrument) if names else loaded  # cancelled or no name: as loaded
            if combo.findText(label) < 0:
                combo.insertItem(combo.count() - 1, label)
            combo.setCurrentIndex(combo.findText(label))
        self.commitData.emit(combo)
        self.closeEditor.emit(combo)
