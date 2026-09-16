"""The Metadata tab's "channels" column: the cell, its combo-box editor, the save rule.

Which of the recorder's columns had a sensor attached is a per-survey
logistics decision (`mtproc.survey.CHANNEL_PRESETS`): the survey declares it
once in `defaults: channels:` and a site that differs -- a dedicated remote
with magnetics only, a deployment that carried a Bz coil -- has its own
`channels:`. The cell shows the site's effective set as its preset's label
(`mtproc.survey.preset_label`, e.g. "Ex Ey Bx By"), or the list itself when
it is no preset. Double-click or F2 opens a combo of the site's instrument's
presets (`Survey.instrument_of`) plus "custom...", which asks for a list (`ask_channels`). Save
writes the site's `channels:` only when the set differs from the survey
default, and drops the key when it is the default's again (`edit`); the tab's
rule that only changed cells are written holds as for every other column.
Ingest applies the set, so on a site whose archive exists the cell is greyed
with `ARCHIVE_TIP` as its tooltip: the archive keeps the set it was built
with until it is deleted and built again. Nothing here computes anything.
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
    """The site's cell: `item_class(label, editable=True)`, greyed with ARCHIVE_TIP when `archived`."""
    item = item_class(preset_label(channels, instrument), editable=True)
    if archived:
        item.setForeground(QColor(DISABLED))
        item.setToolTip(ARCHIVE_TIP)
    return item


def _same(a: list[str] | None, b: list[str] | None) -> bool:
    """The same set of channels (order and case ignored; None, "every column", only equals None)."""
    if a is None or b is None:
        return a is b
    return sorted(str(c).lower() for c in a) == sorted(str(c).lower() for c in b)


def edit(survey, item, shown: str | None, site: str | None = None):
    """A channels cell -> the site's `channels:` to write: a list, None to drop the key, or UNCHANGED.

    UNCHANGED when the cell's set is the one loaded (`shown`); None when the
    new set is the survey default's, so the site's own key goes and the
    default applies again; otherwise the list.
    """
    if item is None or shown is None or item.text() == shown:
        return UNCHANGED
    instrument = survey.instrument_of(site) if site else survey.instrument
    new = channels_from_label(item.text(), instrument)
    if _same(new, channels_from_label(shown, instrument)):
        return UNCHANGED
    return None if _same(new, survey.defaults.get("channels")) else new


def ask_channels(parent, current: str) -> str | None:
    """The "custom..." prompt: the typed list, or None when cancelled or blank."""
    text, ok = QInputDialog.getText(
        parent, "Channels recorded",
        "Channels with a sensor, comma separated, as the reader names them (e.g. ex, ey, hx, hy, hz):",
        text=current)
    return text.strip() if ok and text.strip() else None


class ChannelsDelegate(QStyledItemDelegate):
    """The channels column's editor: the row's instrument's presets plus "custom...".

    A choice commits at once. "custom..." asks for a list; a list that is a
    preset's set comes back as that preset's label, any other as "a, b, c".
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state

    def _instrument(self, index) -> str:
        """The instrument of the row's site (column 0), else the survey's."""
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
            # the prompt is the combo's child, so the editor keeps its focus while it is open
            typed = ask_channels(combo, ", ".join(channels or []))
            names = channels_from_label(typed, instrument) if typed else None
            label = preset_label(names, instrument) if names else loaded  # cancelled or no name: as loaded
            if combo.findText(label) < 0:
                combo.insertItem(combo.count() - 1, label)
            combo.setCurrentIndex(combo.findText(label))
        self.commitData.emit(combo)
        self.closeEditor.emit(combo)
