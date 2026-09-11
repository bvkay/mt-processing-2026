"""One small form per declared filter kind, for the Filter Data tab.

Three widgets, one per kind in `bbmt.noise` (+ `replace`, which
`bbmt.ingest._replace_channels` handles): each shows the options of one entry
in `<survey>/filters.yaml`, and `spec()` gives that entry back as the
single-key dict the YAML wants. They live here rather than in
`tabs/filters.py` so the tab file stays one class and under the size rule.

The defaults are the defaults the code uses, not invented ones: notch f0 50 Hz,
9 harmonics, q 30, 2 passes (`bbmt.noise.mains_notch`); cp period 12 s, 10 min
windows, all four channels, no refinement, ey as reference
(`bbmt.noise.apply_filters`).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

CHANNELS = ("ex", "ey", "hx", "hy")
MAGNETIC = ("hx", "hy")


def _spin(value: float, lo: float, hi: float, decimals: int, step: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setValue(value)
    box.setMaximumWidth(140)  # a number box as wide as the pane reads badly
    return box


class ReplaceForm(QWidget):
    """`- replace: {hx: A06}` -- borrow a magnetic channel from another site.

    The MATLAB app's "replace mag channel: Bx/By + donor". The donor's raw
    files covering this run are read with the donor's own coil calibration and
    the run is trimmed to the span the donor covers.
    """

    kind = "replace"
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes: dict[str, QCheckBox] = {}
        self.donors: dict[str, QComboBox] = {}
        grid = QGridLayout(self)
        grid.addWidget(QLabel("channel"), 0, 0)
        grid.addWidget(QLabel("donor site (its own coil calibration)"), 0, 1)
        for row, comp in enumerate(MAGNETIC, start=1):
            check = QCheckBox(comp, self)
            combo = QComboBox(self)
            combo.setMinimumWidth(140)
            check.toggled.connect(lambda on, c=combo: (c.setEnabled(on), self.changed.emit()))
            combo.currentIndexChanged.connect(lambda _i: self.changed.emit())
            combo.setEnabled(False)
            grid.addWidget(check, row, 0)
            grid.addWidget(combo, row, 1)
            self.boxes[comp], self.donors[comp] = check, combo
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)

    def set_donors(self, names) -> None:
        """Every other site with a raw folder can donate a coil."""
        for comp, combo in self.donors.items():
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


class NotchForm(QWidget):
    """`- notch: {...}` -- zero-phase IIR comb at f0 and its harmonics."""

    kind = "notch"
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f0 = _spin(50.0, 0.01, 10000.0, 3, 1.0)
        self.harmonics = QSpinBox(self)
        self.harmonics.setRange(1, 99)
        self.harmonics.setValue(9)
        self.harmonics.setMaximumWidth(140)
        self.q = _spin(30.0, 1.0, 1000.0, 1, 1.0)
        self.passes = QSpinBox(self)
        self.passes.setRange(1, 20)
        self.passes.setValue(2)
        self.passes.setMaximumWidth(140)
        self.extra = QLineEdit(self)
        self.extra.setMaximumWidth(360)
        self.extra.setPlaceholderText("extra lines, comma-separated Hz (e.g. 75, 125)")

        grid = QGridLayout(self)
        for row, (text, widget) in enumerate(
            [
                ("f0 (Hz)", self.f0),
                ("harmonics", self.harmonics),
                ("q", self.q),
                ("passes", self.passes),
                ("extra lines (Hz)", self.extra),
            ]
        ):
            grid.addWidget(QLabel(text, self), row, 0)
            grid.addWidget(widget, row, 1)
        grid.addWidget(
            QLabel("Two passes by default: the grid wanders +-0.1 Hz and one\n"
                   "pass leaves the line ~7 dB above the floor.", self), 5, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(6, 1)

        for widget in (self.f0, self.q):
            widget.valueChanged.connect(lambda _v: self.changed.emit())
        for widget in (self.harmonics, self.passes):
            widget.valueChanged.connect(lambda _v: self.changed.emit())
        self.extra.textChanged.connect(lambda _t: self.changed.emit())

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

    def spec(self) -> dict:
        out = {
            "f0": float(self.f0.value()),
            "harmonics": int(self.harmonics.value()),
            "q": float(self.q.value()),
            "passes": int(self.passes.value()),
        }
        extra = []
        for token in self.extra.text().replace(";", ",").split(","):
            token = token.strip()
            if token:
                try:
                    extra.append(float(token))
                except ValueError:
                    continue
        if extra:
            out["extra"] = extra
        return {"notch": out}


class CpForm(QWidget):
    """`- cp: {...}` -- stack the cycles of a periodic interferer and subtract."""

    kind = "cp"
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.period_s = _spin(12.0, 0.001, 3600.0, 5, 0.1)
        self.window_minutes = _spin(10.0, 0.5, 600.0, 1, 1.0)
        self.channels = {c: QCheckBox(c, self) for c in CHANNELS}
        for box in self.channels.values():
            box.setChecked(True)
            box.toggled.connect(lambda _on: self.changed.emit())
        self.refine = QCheckBox("refine the period from the reference's autocorrelation", self)
        self.refine.toggled.connect(lambda _on: self.changed.emit())
        self.reference = QComboBox(self)
        self.reference.addItems(list(CHANNELS))
        self.reference.setCurrentText("ey")
        self.reference.setMaximumWidth(140)
        self.reference.currentIndexChanged.connect(lambda _i: self.changed.emit())
        for widget in (self.period_s, self.window_minutes):
            widget.valueChanged.connect(lambda _v: self.changed.emit())

        channels = QHBoxLayout()
        for comp in CHANNELS:
            channels.addWidget(self.channels[comp])
        channels.addStretch(1)

        grid = QGridLayout(self)
        grid.addWidget(QLabel("period_s", self), 0, 0)
        grid.addWidget(self.period_s, 0, 1)
        grid.addWidget(QLabel("window_minutes", self), 1, 0)
        grid.addWidget(self.window_minutes, 1, 1)
        grid.addWidget(QLabel("channels", self), 2, 0)
        grid.addLayout(channels, 2, 1)
        grid.addWidget(self.refine, 3, 0, 1, 2)
        grid.addWidget(QLabel("reference", self), 4, 0)
        grid.addWidget(self.reference, 4, 1)
        grid.addWidget(
            QLabel("Refinement is only needed when the declared period is not\n"
                   "known to ~0.1 ms (Burra's interrupter: 12.0000 s).", self), 5, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(6, 1)

    def load(self, opts: dict) -> None:
        opts = dict(opts or {})
        for widget, key, default in (
            (self.period_s, "period_s", 12.0),
            (self.window_minutes, "window_minutes", 10.0),
        ):
            widget.blockSignals(True)
            widget.setValue(float(opts.get(key, default)))
            widget.blockSignals(False)
        wanted = [str(c).lower() for c in (opts.get("channels") or CHANNELS)]
        for comp, box in self.channels.items():
            box.blockSignals(True)
            box.setChecked(comp in wanted)
            box.blockSignals(False)
        self.refine.blockSignals(True)
        self.refine.setChecked(bool(opts.get("refine", False)))
        self.refine.blockSignals(False)
        self.reference.blockSignals(True)
        self.reference.setCurrentText(str(opts.get("reference", "ey")).lower())
        self.reference.blockSignals(False)

    def spec(self) -> dict:
        return {
            "cp": {
                "period_s": float(self.period_s.value()),
                "window_minutes": float(self.window_minutes.value()),
                "channels": [c for c in CHANNELS if self.channels[c].isChecked()],
                "refine": bool(self.refine.isChecked()),
                "reference": self.reference.currentText(),
            }
        }


def summarise(entry: dict) -> str:
    """One line for the list widget, e.g. `notch 50 Hz x9 (+75, 125)`."""
    kind, opts = next(iter(entry.items()))
    opts = opts or {}
    if kind == "replace":
        return "replace " + ", ".join(f"{c}<-{s}" for c, s in opts.items()) if opts else "replace (nothing)"
    if kind == "notch":
        extra = opts.get("extra") or []
        return (
            f"notch {float(opts.get('f0', 50)):g} Hz x{int(opts.get('harmonics', 9))}"
            f", q {float(opts.get('q', 30)):g}, {int(opts.get('passes', 2))} passes"
            + (" (+" + ", ".join(f"{float(v):g}" for v in extra) + " Hz)" if extra else "")
        )
    if kind == "cp":
        chans = opts.get("channels") or list(CHANNELS)
        return (
            f"cp {float(opts.get('period_s', 12)):g} s, "
            f"{float(opts.get('window_minutes', 10)):g} min windows, {' '.join(chans)}"
            + (" (refined)" if opts.get("refine") else "")
        )
    return str(kind)
