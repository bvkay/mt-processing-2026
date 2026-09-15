"""StackBuilder and RunOptions: the Process tab's stack builder and run options.

`docs/matlab_app_borrowing.md` says what each is and is not:

- `StackBuilder` the members, name and span of a synthetic remote; it returns
                 the `scripts/build_stack.py` command line and never runs it
                 (the Process tab's "Build stack" button calls `build`).
- `RunOptions`   the one group box of things a run can vary -- the four band
                 kwargs, the ingest-filters switch and the output tag suffix --
                 which hands back the `scripts/process_rr.py` flags for
                 whatever was *changed* from the survey's `processing:` block,
                 and nothing for what was not. Under them, collapsed by
                 default, `EstimatorOptions`: "Advanced (aurora estimator)",
                 process_rr.py's --taper ... --tolerance, by the same rule
                 against the in-use values (`mtproc.process.ESTIMATOR_DEFAULTS`).

Nothing here computes a product: `StackBuilder.argv` and `RunOptions.flags`
only assemble command lines from a `WindowBar`, the survey's own
`processing:` block (`band_defaults`, below) and the estimator defaults.
"""

from __future__ import annotations

import inspect

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QLineEdit, QListWidget, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from mtproc.bands import lemimt_band_scheme
from mtproc.ingest import variant_ready
from mtproc.process import ESTIMATOR_DEFAULTS, TAPERS
from mtproc_gui.window_bar import UTC_FMT, WindowBar

# the four band kwargs a run can override, in `scripts/process_rr.py`'s order
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies")


def band_defaults(survey) -> dict:
    """The survey's band settings: its `processing:` block over `lemimt_band_scheme`'s own defaults.

    The same rule `scripts/process_rr.py` applies, so "changed from the
    default" means exactly "worth putting on the command line".
    """
    signature = inspect.signature(lemimt_band_scheme).parameters
    out = {key: signature[key].default for key in BAND_KEYS}
    out.update({k: v for k, v in (survey.processing if survey else {}).items() if k in out})
    return out


def notch_text(values) -> str:
    return ", ".join(f"{float(v):g}" for v in values or ())


# ------------------------------------------------------------ the stack builder


class StackBuilder(QGroupBox):
    """Name, members and span of a synthetic remote; returns the build_stack.py argv."""

    build_requested = Signal(list)  # the argv, for the tab to queue
    members_changed = Signal(list)  # for the map to paint them orange

    def __init__(self, state, window_bar: WindowBar, parent=None):
        super().__init__("Stacked remote (scripts/build_stack.py)", parent)
        self.state = state
        self.window_bar = window_bar
        self.station: str | None = None

        self.name_edit = QLineEdit(self)
        self.name_edit.setToolTip("the stack's archive name: <workspace>/mth5/<name>.h5")
        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # fixed list, two hint lines reserved: the Process tab's splitter drops the wrapped hint's
        # height-for-width, so the builder's minimum must be the height it is drawn at or it
        # overlaps the map above it (340 px minimum)
        self.list.setFixedHeight(110)
        self.list.itemSelectionChanged.connect(lambda: self.members_changed.emit(self.members()))
        self.hint = QLabel("two or more members, over the processing window; then Build stack", self)
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(2 * self.hint.fontMetrics().lineSpacing())

        layout = QGridLayout(self)
        layout.addWidget(QLabel("Name", self), 0, 0)
        layout.addWidget(self.name_edit, 0, 1)
        layout.addWidget(QLabel("Members", self), 1, 0, Qt.AlignTop)
        layout.addWidget(self.list, 1, 1)
        layout.addWidget(self.hint, 2, 0, 1, 2)
        layout.setColumnStretch(1, 1)

    def reload(self) -> None:
        self.set_station(self.station)

    def set_station(self, station: str | None) -> None:
        """Refill the candidates (every raw site but this one) and the default name."""
        self.station = station
        chosen = set(self.members())
        self.list.clear()
        for name in sorted(self.state.raw_sites()):
            if name != station:
                self.list.addItem(name)
        for i in range(self.list.count()):
            if self.list.item(i).text() in chosen:
                self.list.item(i).setSelected(True)
        if station:
            self.name_edit.setText(f"STK{station}")
        self.members_changed.emit(self.members())

    def members(self) -> list[str]:
        return [item.text() for item in self.list.selectedItems()]

    def argv(self) -> list[str] | None:
        """`build_stack.py <survey.yaml> <name> <start> <end> <members...>`, or None with a reason."""
        members = self.members()
        name = self.name_edit.text().strip()
        window = self.window_bar.window()
        if self.state.survey_yaml is None:
            self.hint.setText("open a survey first")
            return None
        if len(members) < 2:
            self.hint.setText("pick at least two members (a mean of one site is that site)")
            return None
        if not name:
            self.hint.setText("give the stack a name")
            return None
        if window is None:
            self.hint.setText("the processing window must have a start and an end")
            return None
        self.hint.setText(f"{name} <- {', '.join(members)} over the processing window")
        return [self.state.python_exe, self.state.script("build_stack.py"),
                str(self.state.survey_yaml), name,
                window[0].strftime(UTC_FMT), window[1].strftime(UTC_FMT), *members]

    def build(self) -> list[str] | None:
        """Emit `build_requested` with the argv, or leave the reason in the hint."""
        argv = self.argv()
        if argv is not None:
            self.build_requested.emit(argv)
        return argv


# ------------------------------------------------------------- the run options


class RunOptions(QGroupBox):
    """What a single run may change: the band kwargs, the ingest filters and the tag."""

    def __init__(self, state, parent=None):
        super().__init__("Aurora options (survey defaults; only what you change is passed)", parent)
        self.state = state
        self.defaults: dict = {}

        self.min_spin = QDoubleSpinBox(self, decimals=4, minimum=0.0001, maximum=100.0,
                                       singleStep=0.001, suffix=" s")
        self.max_spin = QDoubleSpinBox(self, decimals=1, minimum=1.0, maximum=100000.0,
                                       singleStep=100.0, suffix=" s")
        self.decade_spin = QDoubleSpinBox(self, decimals=1, minimum=1.0, maximum=40.0, singleStep=1.0)
        self.notch_edit = QLineEdit(self)
        self.notch_edit.setToolTip("comma-separated Hz kept out of every band (mains and harmonics)")
        self.filters_check = QCheckBox("use declared filters", self, checked=True)
        self.filters_check.setToolTip(
            "On (default): each site is processed from its filtered variant (<site>_f<hash>.h5), "
            "built on demand from its raw archive. Off adds --no-filters: both sites are processed "
            "from their raw <site>.h5 outright, so a run can be compared with and without their "
            "declared filters."
        )
        self.filters_label = QLabel("", self)
        self.filters_label.setWordWrap(True)
        self.tag_edit = QLineEdit(self)
        self.tag_edit.setPlaceholderText("tag suffix (optional), e.g. nofilt or try2")

        # three columns of label + control, like the MATLAB app's options block
        grid = QGridLayout(self)
        for row, column, widget in (
            (0, 0, QLabel("Min period", self)), (0, 1, self.min_spin),
            (0, 2, QLabel("Max period", self)), (0, 3, self.max_spin),
            (0, 4, QLabel("Periods per decade", self)), (0, 5, self.decade_spin),
            (1, 0, QLabel("Notch (Hz)", self)), (1, 1, self.notch_edit),
            (1, 2, QLabel("Output tag suffix", self)),
        ):
            grid.addWidget(widget, row, column)
        grid.addWidget(self.tag_edit, 1, 3, 1, 3)
        grid.addWidget(self.filters_check, 2, 0, 1, 2)
        grid.addWidget(self.filters_label, 2, 2, 1, 4)
        self.advanced = EstimatorOptions(self)
        grid.addWidget(self.advanced, 3, 0, 1, 6)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)

    def reload(self) -> None:
        """Back to the survey's own band block, filters on, no tag."""
        self.defaults = band_defaults(self.state.survey)
        for spin, key in ((self.min_spin, "min_period"), (self.max_spin, "max_period"),
                          (self.decade_spin, "periods_per_decade")):
            spin.setValue(float(self.defaults[key]))
        self.notch_edit.setText(notch_text(self.defaults["notch_frequencies"]))
        self.filters_check.setChecked(True)
        self.tag_edit.clear()
        self.advanced.reset()

    def describe_filters(self, station, remote=None) -> None:
        """One read-only line naming what the station and the remote declare in
        `filters.yaml`; each list is applied on demand, into a filtered
        variant of the site's raw archive (`mtproc.ingest.processing_archive`),
        when a run wants it (`RunOptions.filters_check`, on by default)."""
        survey = self.state.survey
        if not station or survey is None:
            self.filters_label.setText("")
            return

        def kinds(site):
            declared = survey.site(site).filters or []
            names = ", ".join(sorted({k for entry in declared for k in entry})) or "none"
            if not declared:
                return names
            state = "filtered archive ready" if variant_ready(survey, site) else \
                "filtered archive will be built first, from the raw archive"
            return f"{names} ({state})"

        text = f"{station} declares: {kinds(station)}"
        if remote and remote != station and remote in (survey.site_names() + list(self.state.raw_sites())):
            text += f" | {remote} (remote) declares: {kinds(remote)}"
        self.filters_label.setText(text + " (edit on the Filter Data tab)")

    def flags(self) -> list[str]:
        """Only what differs from the defaults: --min-period ... --notch, --no-filters, --tag, advanced."""
        out: list[str] = []
        for flag, spin, key in (("--min-period", self.min_spin, "min_period"),
                                ("--max-period", self.max_spin, "max_period"),
                                ("--per-decade", self.decade_spin, "periods_per_decade")):
            if abs(spin.value() - float(self.defaults.get(key, spin.value()))) > 1e-9:
                out += [flag, f"{spin.value():g}"]
        wanted = self.notch_edit.text().strip()
        if wanted != notch_text(self.defaults.get("notch_frequencies")):
            out += ["--notch", wanted]
        if not self.filters_check.isChecked():
            out.append("--no-filters")
        if self.tag_edit.text().strip():
            out += ["--tag", self.tag_edit.text().strip()]
        return out + self.advanced.flags()


class EstimatorOptions(QWidget):
    """"Advanced (aurora estimator)": a toggle over process_rr.py's --taper ... --tolerance.

    Collapsed by default. Every control starts at the value a run uses when
    the flag is absent (`ESTIMATOR_DEFAULTS`, which tests/process_rr_cli_unit.py
    checks against a real aurora config), and only a control moved off it
    becomes a flag.
    """

    TITLE = "Advanced (aurora estimator)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.toggle = QToolButton(self, text=self.TITLE, checkable=True, autoRaise=True,
                                  toolButtonStyle=Qt.ToolButtonTextBesideIcon)
        self.toggle.setToolTip("aurora's STFT and robust regression on every decimation level; "
                               "each control starts at the value a run uses without it")
        self.toggle.toggled.connect(self.set_expanded)
        self.block = QWidget(self)
        self.taper_combo = QComboBox(self.block, toolTip="STFT window (--taper)")
        self.taper_combo.addItems(TAPERS)
        self.overlap_spin = QSpinBox(self.block, minimum=0, maximum=95, suffix=" %", toolTip=(
            "STFT overlap (--overlap). Left at 25 % nothing is passed and levels whose window "
            "lasts over 600 s keep their 75 %; any other value applies to every level."))
        self.prewhiten_check = QCheckBox("pre-whitening (first difference)", self.block,
                                         toolTip="off adds --no-prewhiten (and no recolouring)")
        self.min_windows_spin = QSpinBox(self.block, minimum=0, maximum=100000,
                                         toolTip="fewest STFT windows a level needs (--min-windows)")
        self.iterations_spin = QSpinBox(self.block, minimum=1, maximum=1000,
                                        toolTip="robust regression iterations (--max-iterations)")
        self.redescending_spin = QSpinBox(self.block, minimum=0, maximum=1000,
                                          toolTip="redescending iterations (--redescending-iterations)")
        self.r0_spin = QDoubleSpinBox(self.block, decimals=2, minimum=0.1, maximum=20.0, singleStep=0.1,
                                      toolTip="Huber threshold, residual standard deviations (--r0)")
        self.u0_spin = QDoubleSpinBox(self.block, decimals=2, minimum=0.1, maximum=20.0, singleStep=0.1,
                                      toolTip="redescending threshold (--u0)")
        self.tolerance_spin = QDoubleSpinBox(self.block, decimals=4, minimum=0.0001, maximum=0.5,
                                             singleStep=0.001, toolTip="convergence tolerance (--tolerance)")

        grid = QGridLayout(self.block)
        grid.setContentsMargins(0, 0, 0, 0)
        for row, pairs in enumerate((
            (("Taper", self.taper_combo), ("Overlap", self.overlap_spin),
             ("Min windows", self.min_windows_spin)),
            (("Max iterations", self.iterations_spin), ("Redescending", self.redescending_spin),
             ("r0", self.r0_spin), ("u0", self.u0_spin), ("Tolerance", self.tolerance_spin)),
        )):
            for i, (text, widget) in enumerate(pairs):
                grid.addWidget(QLabel(text, self.block), row, 2 * i)
                grid.addWidget(widget, row, 2 * i + 1)
        grid.addWidget(self.prewhiten_check, 0, 6, 1, 4)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.block)
        self.set_expanded(False)
        self.reset()

    def set_expanded(self, expanded: bool) -> None:
        """Show or hide the block; the arrow says which."""
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.block.setVisible(expanded)

    def _numbers(self):
        """(flag, spin box, ESTIMATOR_DEFAULTS key), in process_rr.py's order."""
        return (("--overlap", self.overlap_spin, "overlap_pct"),
                ("--min-windows", self.min_windows_spin, "min_windows"),
                ("--max-iterations", self.iterations_spin, "max_iterations"),
                ("--redescending-iterations", self.redescending_spin, "redescending_iterations"),
                ("--r0", self.r0_spin, "r0"), ("--u0", self.u0_spin, "u0"),
                ("--tolerance", self.tolerance_spin, "tolerance"))

    def reset(self) -> None:
        """Every control back to the value a run uses without its flag."""
        self.taper_combo.setCurrentText(ESTIMATOR_DEFAULTS["taper"])
        self.prewhiten_check.setChecked(bool(ESTIMATOR_DEFAULTS["prewhiten"]))
        for _flag, spin, key in self._numbers():
            value = ESTIMATOR_DEFAULTS[key]
            spin.setValue(int(value) if isinstance(spin, QSpinBox) else float(value))

    def flags(self) -> list[str]:
        """--taper, --no-prewhiten, --overlap ... --tolerance: only the controls moved off their default."""
        out: list[str] = []
        if self.taper_combo.currentText() != ESTIMATOR_DEFAULTS["taper"]:
            out += ["--taper", self.taper_combo.currentText()]
        if self.prewhiten_check.isChecked() != bool(ESTIMATOR_DEFAULTS["prewhiten"]):
            out.append("--no-prewhiten")
        for flag, spin, key in self._numbers():
            if abs(spin.value() - ESTIMATOR_DEFAULTS[key]) > 1e-9:
                # "50" from a whole-number box, "2.0" (not "2") from a decimal one
                whole = isinstance(spin, QSpinBox)
                out += [flag, str(spin.value()) if whole else repr(round(spin.value(), spin.decimals()))]
        return out
