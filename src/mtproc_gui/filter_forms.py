"""One small form per declared filter kind, for the Filter Data tab.

One widget per kind in `mtproc.noise` (`replace` is `mtproc.ingest._replace_channels`
at ingest): `load(opts)` shows one entry of `<survey>/filters.yaml` and
`spec()` gives it back as the single-key dict the YAML wants. `LABELS` holds
the students' names for the kinds; channels show as Bx, By, Ex, Ey and are
written hx, hy, ex, ey -- or the site's own recorder's names (E1 .. Bz on a
LEMI-424), which the tab passes in (`set_channels`). `replace` is LEMI-423's. The defaults are the code's: notch 50 Hz, 9
harmonics, q 30, 2 passes (`mains_notch`); cp 12 s, 10 min windows, all four
channels, ey as the reference; hp and lp order 4. The library has no default
cutoff; the forms start at 0.001 Hz (1000 s) for a high-pass and 100 Hz for
a low-pass. A `channels` list is written for notch, mains, hp and lp only
when it leaves a channel out, so a list saved before the option existed reads
back unchanged. The notch form also says how long it rings at a step of the
mains amplitude (+-4.6 q / (pi f0) s per pass). mains starts at
`mains_subtract`'s defaults (50 Hz, 9 harmonics, 1 s blocks, steps over 0.3
of the level) and says the band it takes (+-1/block Hz). burst starts at
`mtproc.noise`'s defaults (12 x MAD, 0.05 s, pad 0.1 s, taper 0.05 s, the electrics as reference, every channel) and writes
its reference and channels always; flip starts with no channel ticked (it
has no default) and writes the ticked ones.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QWidget,
)

from mtproc_gui import theme
from mtproc_gui.channels import kind, roles

CHANNELS = ("ex", "ey", "hx", "hy")  # until a site says otherwise; a written list: electrics first
MAGNETIC = ("hx", "hy")
LABELS = {
    "notch": "50 Hz + harmonics",
    "mains": "mains subtraction (fitted, follows steps)",
    "hp": "high-pass",
    "lp": "low-pass",
    "cp": "cathodic protection stack",
    "burst": "burst removal (short transients)",
    "flip": "flip polarity",
    "replace": "replace magnetics from another site",
}


def _spin(value: float, lo: float, hi: float, decimals: int, step: float) -> QDoubleSpinBox:
    # a number box as wide as the pane reads badly
    return QDoubleSpinBox(decimals=decimals, minimum=lo, maximum=hi, singleStep=step, value=value,
                          maximumWidth=140)


def _int_spin(value: int, lo: int, hi: int) -> QSpinBox:
    return QSpinBox(minimum=lo, maximum=hi, value=value, maximumWidth=140)


def _names(chans) -> str:
    return " ".join(theme.label(c) for c in theme.channel_order(chans))


class ChannelBoxes(QWidget):
    """One check box per channel (Bx By Ex Ey on a LEMI-423), all ticked by default; `changed` on any toggle."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.names, self.boxes = (), {}
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.set_channels(CHANNELS)

    def set_channels(self, names) -> None:
        """The site's channels: boxes in the stack order, a written list electrics first (ex ey hx hy)."""
        names = tuple(sorted(n for n in names if kind(n) == "electric")) + tuple(
            sorted(n for n in names if kind(n) == "magnetic"))
        if names == self.names:
            return
        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.names, self.boxes = names, {c: QCheckBox(theme.label(c), self) for c in theme.channel_order(names)}
        for box in self.boxes.values():
            box.setChecked(True)
            box.toggled.connect(lambda _on: self.changed.emit())
            self.row.addWidget(box)
        self.row.addStretch(1)

    def set(self, chans) -> None:
        wanted = [str(c).lower() for c in (self.names if chans is None else chans)]
        for comp, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(comp in wanted)
            box.blockSignals(False)

    def get(self) -> list[str]:
        return [c for c in self.names if self.boxes[c].isChecked()]


class _Form(QWidget):
    """A title in the students' words, then a grid of (label or widget, widget) rows and a note."""

    kind = ""
    changed = Signal()

    def _grid(self, rows, note: str) -> QGridLayout:
        grid = QGridLayout(self)
        title = QLabel(f"<b>{LABELS[self.kind]}</b> ({self.kind})", self)
        grid.addWidget(title, 0, 0, 1, 2)
        for row, (text, widget) in enumerate(rows, start=1):
            grid.addWidget(text if isinstance(text, QWidget) else QLabel(text, self), row, 0)
            grid.addWidget(widget, row, 1)
        self.note = QLabel(note, self, wordWrap=True)
        grid.addWidget(self.note, len(rows) + 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(rows) + 2, 1)
        return grid

    def set_channels(self, names) -> None:
        """The site's channels, for a form that has channel boxes."""
        if hasattr(self, "channels"):
            self.channels.set_channels(names)


class ReplaceForm(_Form):
    """`- replace: {hx: A06}` -- borrow a magnetic channel from another site.

    The MATLAB app's "replace mag channel: Bx/By + donor". The donor's raw
    files covering this run are read with the donor's own coil calibration and
    the run is trimmed to the span the donor covers.
    """

    kind = "replace"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QCheckBox] = {}
        self.donors: dict[str, QComboBox] = {}
        rows = []
        for comp in MAGNETIC:
            check = QCheckBox(f"{theme.label(comp)} from", self)
            combo = QComboBox(self)
            combo.setMinimumWidth(140)
            check.toggled.connect(lambda on, c=combo: (c.setEnabled(on), self.changed.emit()))
            combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
            combo.setEnabled(False)
            self.boxes[comp], self.donors[comp] = check, combo
            rows.append((check, combo))
        self._grid(rows, "The donor's coil is read with the donor's own calibration. "
                         "Applied first at ingest, wherever it sits in the list.")

    def set_donors(self, names) -> None:
        """Every other site with a raw folder can donate a coil."""
        for combo in self.donors.values():
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(names))
            index = combo.findText(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def load(self, opts: dict) -> None:
        opts = {str(k).lower(): str(v) for k, v in (opts or {}).items()}
        for comp in MAGNETIC:
            combo, check = self.donors[comp], self.boxes[comp]
            check.blockSignals(True)
            combo.blockSignals(True)
            check.setChecked(comp in opts)
            combo.setEnabled(comp in opts)
            if comp in opts:
                if combo.findText(opts[comp]) < 0:
                    combo.addItem(opts[comp])
                combo.setCurrentIndex(combo.findText(opts[comp]))
            check.blockSignals(False)
            combo.blockSignals(False)

    def spec(self) -> dict:
        out = {
            comp: self.donors[comp].currentText()
            for comp in MAGNETIC
            if self.boxes[comp].isChecked() and self.donors[comp].currentText()
        }
        return {"replace": out}


class NotchForm(_Form):
    """`- notch: {...}` -- zero-phase IIR comb at f0 and its harmonics."""

    kind = "notch"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f0 = _spin(50.0, 0.01, 10000.0, 3, 1.0)
        self.harmonics = _int_spin(9, 1, 99)
        self.q = _spin(30.0, 1.0, 1000.0, 1, 1.0)
        self.passes = _int_spin(2, 1, 20)
        self.extra = QLineEdit(self)
        self.extra.setMaximumWidth(360)
        self.extra.setPlaceholderText("extra lines, comma-separated Hz (e.g. 75, 125)")
        self.channels = ChannelBoxes(self)
        self.ringing = QLabel(self, wordWrap=True)  # read-only: the notch's ringing at a step of the mains
        self._grid([("mains (Hz)", self.f0), ("harmonics", self.harmonics), ("q", self.q),
                    ("passes", self.passes), ("", self.ringing), ("extra lines (Hz)", self.extra),
                    ("channels", self.channels)],
                   "Two passes by default: the grid wanders +-0.1 Hz and one pass leaves the "
                   "line ~7 dB above the floor. A higher q is a narrower notch.")
        for widget in (self.f0, self.q, self.harmonics, self.passes):
            widget.valueChanged.connect(lambda _v: self.changed.emit())
        for widget in (self.f0, self.q, self.passes):
            widget.valueChanged.connect(lambda _v: self._ringing())
        self.extra.textChanged.connect(lambda _t: self.changed.emit())
        self.channels.changed.connect(self.changed)
        self._ringing()

    def _ringing(self) -> None:
        """A second-order notch's impulse response decays as exp(-pi f0 t / q); 4.6 time constants is 1 %."""
        seconds = 4.6 * self.q.value() / (math.pi * self.f0.value())
        self.ringing.setText(f"rings about +-{seconds:.2f} s per pass at a step in the mains amplitude")

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, key, default in (
            (self.f0, "f0", 50.0),
            (self.harmonics, "harmonics", 9),
            (self.q, "q", 30.0),
            (self.passes, "passes", 2),
        ):
            widget.blockSignals(True)
            widget.setValue(type(widget.value())(opts.get(key, default)))
            widget.blockSignals(False)
        self.extra.blockSignals(True)
        self.extra.setText(", ".join(f"{float(v):g}" for v in (opts.get("extra") or [])))
        self.extra.blockSignals(False)
        self.channels.set(opts.get("channels"))
        self._ringing()

    def spec(self) -> dict:
        out = {
            "f0": float(self.f0.value()),
            "harmonics": int(self.harmonics.value()),
            "q": float(self.q.value()),
            "passes": int(self.passes.value()),
        }
        extra = []
        for token in self.extra.text().replace(";", ",").split(","):
            try:
                extra.append(float(token.strip()))
            except ValueError:
                continue
        if extra:
            out["extra"] = extra
        chans = self.channels.get()
        if len(chans) < len(self.channels.names):
            out["channels"] = chans
        return {"notch": out}


class MainsForm(_Form):
    """`- mains: {...}` -- subtract a fitted model of the mains that steps where its amplitude steps."""

    kind = "mains"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f0 = _spin(50.0, 0.01, 10000.0, 3, 1.0)
        self.harmonics = _int_spin(9, 1, 99)
        self.block_s = _spin(1.0, 0.05, 60.0, 2, 0.25)
        self.step_fraction = _spin(0.3, 0.05, 1.0, 2, 0.05)
        self.channels = ChannelBoxes(self)
        self._grid([("mains (Hz)", self.f0), ("harmonics", self.harmonics), ("fit block (s)", self.block_s),
                    ("step (fraction of the level)", self.step_fraction), ("channels", self.channels)], "")
        for widget in (self.f0, self.harmonics, self.block_s, self.step_fraction):
            widget.valueChanged.connect(lambda _v: (self._explain(), self.changed.emit()))
        self.channels.changed.connect(self.changed)
        self._explain()

    def _explain(self) -> None:
        self.note.setText(
            "Subtracts the mains (f0 and its harmonics, fitted block by block on the tracked grid phase) "
            "instead of filtering it out. Where the mains amplitude steps by more than the step fraction "
            "(a load switching) the fit starts afresh, so nothing rings. It takes about "
            f"+-{1.0 / self.block_s.value():g} Hz around each harmonic; a shorter block follows a "
            "wandering waveform better and takes more.")

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, key, default in ((self.f0, "f0", 50.0), (self.harmonics, "harmonics", 9),
                                     (self.block_s, "block_s", 1.0), (self.step_fraction, "step_fraction", 0.3)):
            widget.blockSignals(True)
            widget.setValue(type(widget.value())(opts.get(key, default)))
            widget.blockSignals(False)
        self.channels.set(opts.get("channels"))
        self._explain()

    def spec(self) -> dict:
        out = {
            "f0": float(self.f0.value()),
            "harmonics": int(self.harmonics.value()),
            "block_s": float(self.block_s.value()),
            "step_fraction": float(self.step_fraction.value()),
        }
        chans = self.channels.get()
        if len(chans) < len(self.channels.names):
            out["channels"] = chans
        return {"mains": out}


class ButterForm(_Form):
    """`- hp: {...}` or `- lp: {...}` -- a zero-phase Butterworth high- or low-pass."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.default = 0.001 if kind == "hp" else 100.0
        self.cutoff = _spin(self.default, 0.0001, 499.0, 4, 0.001 if kind == "hp" else 10.0)
        self.order = _int_spin(4, 1, 10)
        self.channels = ChannelBoxes(self)
        self._grid([("cutoff (Hz)", self.cutoff), ("order", self.order), ("channels", self.channels)], "")
        for widget in (self.cutoff, self.order):
            widget.valueChanged.connect(lambda _v: (self._explain(), self.changed.emit()))
        self.channels.changed.connect(self.changed)
        self._explain()

    def _explain(self) -> None:
        period = 1.0 / self.cutoff.value()
        if self.kind == "hp":
            self.note.setText(f"Removes every period longer than about {period:g} s from the archive, the MT "
                              "signal with it: keep it beyond the longest period you will process. "
                              "Put it first in the list, before the notch and the cp stack.")
        else:
            self.note.setText(f"Removes everything faster than {self.cutoff.value():g} Hz "
                              f"(periods under {period:g} s). Put it last in the list.")

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, value in ((self.cutoff, float(opts.get("cutoff_hz", self.default))),
                              (self.order, int(opts.get("order", 4)))):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.channels.set(opts.get("channels"))
        self._explain()

    def spec(self) -> dict:
        out = {"cutoff_hz": float(self.cutoff.value()), "order": int(self.order.value())}
        chans = self.channels.get()
        if len(chans) < len(self.channels.names):
            out["channels"] = chans
        return {self.kind: out}


class CpForm(_Form):
    """`- cp: {...}` -- stack the cycles of a periodic interferer and subtract."""

    kind = "cp"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.period_s = _spin(12.0, 0.001, 3600.0, 5, 0.1)
        self.window_minutes = _spin(10.0, 0.5, 600.0, 1, 1.0)
        self.channels = ChannelBoxes(self)
        self.refine = QCheckBox("refine the period from the reference's autocorrelation", self)
        self.reference = QComboBox(self)
        self.reference.setMaximumWidth(140)
        self._fill_reference()
        self._grid([("period (s)", self.period_s), ("window (minutes)", self.window_minutes),
                    ("channels", self.channels), ("", self.refine), ("reference", self.reference)],
                   "Refinement is only needed when the declared period is not known to ~0.1 ms "
                   "(Burra's interrupter: 12.0000 s). A drift leaks into the median cycle: "
                   "high-pass first.")
        self.channels.changed.connect(self.changed)
        self.refine.toggled.connect(lambda _on: self.changed.emit())
        self.reference.currentIndexChanged.connect(lambda _i: self.changed.emit())
        for widget in (self.period_s, self.window_minutes):
            widget.valueChanged.connect(lambda _v: self.changed.emit())

    def _fill_reference(self) -> None:
        """The reference combo: the site's channels, the one playing Ey (`channels.roles`) by default."""
        self.reference.blockSignals(True)
        self.reference.clear()
        for comp in theme.channel_order(self.channels.names):
            self.reference.addItem(theme.label(comp), comp)
        self.reference.setCurrentIndex(max(0, self.reference.findData(roles(self.channels.names).get("ey"))))
        self.reference.blockSignals(False)

    def set_channels(self, names) -> None:
        before = self.channels.names
        super().set_channels(names)
        if self.channels.names != before:
            self._fill_reference()

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, key, default in (
            (self.period_s, "period_s", 12.0),
            (self.window_minutes, "window_minutes", 10.0),
        ):
            widget.blockSignals(True)
            widget.setValue(float(opts.get(key, default)))
            widget.blockSignals(False)
        self.channels.set(opts.get("channels") or self.channels.names)
        self.refine.blockSignals(True)
        self.refine.setChecked(bool(opts.get("refine", False)))
        self.refine.blockSignals(False)
        self.reference.blockSignals(True)
        ey = roles(self.channels.names).get("ey", "ey")
        self.reference.setCurrentIndex(self.reference.findData(str(opts.get("reference", ey)).lower()))
        self.reference.blockSignals(False)

    def spec(self) -> dict:
        return {
            "cp": {
                "period_s": float(self.period_s.value()),
                "window_minutes": float(self.window_minutes.value()),
                "channels": self.channels.get(),
                "refine": bool(self.refine.isChecked()),
                "reference": self.reference.currentData(),
            }
        }


class BurstForm(_Form):
    """`- burst: {...}` -- find short transients on the reference channels and set them to the local level."""

    kind = "burst"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.threshold = _spin(12.0, 2.0, 1000.0, 1, 1.0)
        self.min_len_s = _spin(0.05, 0.001, 10.0, 3, 0.01)
        self.pad_s = _spin(0.1, 0.0, 10.0, 3, 0.05)
        self.taper_s = _spin(0.05, 0.0, 5.0, 3, 0.01)
        self.reference = ChannelBoxes(self)
        self.channels = ChannelBoxes(self)
        self._electrics()
        self._grid([("threshold (x MAD)", self.threshold), ("shortest burst (s)", self.min_len_s),
                    ("pad each side (s)", self.pad_s), ("taper (s)", self.taper_s),
                    ("detect on", self.reference), ("set to the local level", self.channels)],
                   "A burst is where a 'detect on' channel's 50 ms mean of |x - its 1 s level| stands this "
                   "many times above its running 60 s MAD, for longer than the shortest burst (a lone "
                   "spike or sferic never counts). Put it after the 50 Hz notch: on C23 the bursts are the "
                   "notch ringing at steps of the mains amplitude.")
        for widget in (self.threshold, self.min_len_s, self.pad_s, self.taper_s):
            widget.valueChanged.connect(lambda _v: self.changed.emit())
        self.reference.changed.connect(self.changed)
        self.channels.changed.connect(self.changed)

    def _electrics(self) -> list[str]:
        """Tick the site's electric channels as the reference (the default); returns them."""
        electrics = [c for c in self.reference.names if kind(c) == "electric"]
        self.reference.set(electrics)
        return electrics

    def set_channels(self, names) -> None:
        before = self.reference.names
        super().set_channels(names)
        self.reference.set_channels(names)
        if self.reference.names != before:
            self._electrics()

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, key, default in ((self.threshold, "threshold", 12.0), (self.min_len_s, "min_len_s", 0.05),
                                     (self.pad_s, "pad_s", 0.1), (self.taper_s, "taper_s", 0.05)):
            widget.blockSignals(True)
            widget.setValue(float(opts.get(key, default)))
            widget.blockSignals(False)
        if opts.get("reference") is None:
            self._electrics()
        else:
            self.reference.set(opts["reference"])
        self.channels.set(opts.get("channels"))

    def spec(self) -> dict:
        return {
            "burst": {
                "threshold": float(self.threshold.value()),
                "min_len_s": float(self.min_len_s.value()),
                "pad_s": float(self.pad_s.value()),
                "taper_s": float(self.taper_s.value()),
                "reference": self.reference.get(),
                "channels": self.channels.get(),
            }
        }


class FlipForm(_Form):
    """`- flip: {channels: [ey]}` -- a channel wired with reversed polarity, times -1."""

    kind = "flip"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channels = ChannelBoxes(self)
        self.channels.set([])
        self._grid([("reverse", self.channels)],
                   "Each ticked channel is multiplied by -1 at ingest: for a channel wired the wrong way "
                   "round (a mode's phase 180 degrees out with its resistivity right). Nothing is ticked "
                   "until you tick it.")
        self.channels.changed.connect(self.changed)

    def set_channels(self, names) -> None:
        before = self.channels.names
        super().set_channels(names)
        if self.channels.names != before:
            self.channels.set([])

    def load(self, opts: dict) -> None:
        self.channels.set((opts or {}).get("channels") or [])

    def spec(self) -> dict:
        return {"flip": {"channels": self.channels.get()}}


def make_forms(parent) -> dict:
    """{kind: form} for every kind, in the Add menu's order."""
    forms = (NotchForm(parent), MainsForm(parent), ButterForm("hp", parent), ButterForm("lp", parent),
             CpForm(parent), BurstForm(parent), FlipForm(parent), ReplaceForm(parent))
    return {form.kind: form for form in forms}


def summarise(entry: dict) -> str:
    """One line for the list widget, in the students' words, e.g. `50 Hz + harmonics: 50 Hz x9, ...`."""
    kind, opts = next(iter(entry.items()))
    opts = opts or {}
    scoped = f" on {_names(opts['channels'])}" if opts.get("channels") and kind != "cp" else ""
    if kind == "replace":
        pairs = ", ".join(f"{theme.label(str(c).lower())} <- {s}" for c, s in opts.items())
        return f"{LABELS[kind]}: {pairs or 'nothing'}"
    if kind == "notch":
        extra = opts.get("extra") or []
        return (
            f"{LABELS[kind]}: {float(opts.get('f0', 50)):g} Hz x{int(opts.get('harmonics', 9))}"
            f", q {float(opts.get('q', 30)):g}, {int(opts.get('passes', 2))} passes"
            + (" (+" + ", ".join(f"{float(v):g}" for v in extra) + " Hz)" if extra else "") + scoped
        )
    if kind == "mains":
        return (
            f"{LABELS[kind]}: {float(opts.get('f0', 50)):g} Hz x{int(opts.get('harmonics', 9))}, "
            f"{float(opts.get('block_s', 1.0)):g} s blocks, steps over {float(opts.get('step_fraction', 0.3)):g}"
            f" of the level{scoped}"
        )
    if kind in ("hp", "lp"):
        return f"{LABELS[kind]}: {float(opts.get('cutoff_hz', 0)):g} Hz, order {int(opts.get('order', 4))}{scoped}"
    if kind == "cp":
        return (
            f"{LABELS[kind]}: {float(opts.get('period_s', 12)):g} s, "
            f"{float(opts.get('window_minutes', 10)):g} min windows, {_names(opts.get('channels') or CHANNELS)}"
            + (" (refined)" if opts.get("refine") else "")
        )
    if kind == "burst":
        refs = opts.get("reference")
        return (
            f"{LABELS[kind]}: {float(opts.get('threshold', 12)):g} x MAD on "
            f"{_names(('ex', 'ey') if refs is None else refs) or 'nothing'}, "
            f"over {float(opts.get('min_len_s', 0.05)):g} s, pad {float(opts.get('pad_s', 0.1)):g} s, "
            f"fills {_names(opts.get('channels') or CHANNELS)}"
        )
    if kind == "flip":
        return f"{LABELS[kind]}: {_names(opts.get('channels') or []) or 'nothing'}"
    return str(kind)
