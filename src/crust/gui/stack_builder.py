# -*- coding: utf-8 -*-
"""
Stack builder and run options of the Process tab

* `StackBuilder`: the members, name and span of a synthetic remote. It
  builds the `scripts/build_stack.py` command line and emits it; the Process
  tab's "Build stack" button calls `build` and queues the job.
* `RunOptions`: the group box of settings a run can vary (the four band
  kwargs, the ingest-filters switch, the masks.yaml switch and the output tag
  suffix). It returns `scripts/process_rr.py` flags for the settings changed
  from the survey's `processing:` block only. Below it, collapsed by default,
  `EstimatorOptions` ("Advanced (aurora estimator)") covers process_rr.py's
  --taper ... --tolerance by the same rule, against the values a run uses
  (`crust.process.ESTIMATOR_DEFAULTS`).

`StackBuilder.argv` and `RunOptions.flags` assemble command lines from a
`WindowBar`, the survey's `processing:` block (`band_defaults`) and the
estimator defaults. The masks switch shows the `crust.masks.load_masks`
count for the pair; the masks are applied by process_rr.py.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import inspect

import yaml

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel,
    QLineEdit, QListWidget, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from crust.bands import build_band_scheme
from crust.ingest import variant_ready
from crust.masks import is_stack, load_masks, remote_masks
from crust.process import ESTIMATOR_DEFAULTS, TAPERS
from crust.gui.window_bar import UTC_FMT, WindowBar

# the four band kwargs a run can override, in `scripts/process_rr.py`'s order
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies")


def band_defaults(survey) -> dict:
    """Return the survey's band settings: its `processing:` block over `build_band_scheme`'s defaults.

    `scripts/process_rr.py` applies the same rule, so a value changed from
    these defaults is one that needs a command-line flag.

    Args:
        survey: The open `crust.survey.Survey`, or None.

    Returns:
        dict: The values of `BAND_KEYS`.
    """
    signature = inspect.signature(build_band_scheme).parameters
    out = {key: signature[key].default for key in BAND_KEYS}
    out.update({k: v for k, v in (survey.processing if survey else {}).items() if k in out})
    return out


def notch_text(values) -> str:
    """Format notch frequencies as comma-separated Hz."""
    return ", ".join(f"{float(v):g}" for v in values or ())


# ------------------------------------------------------------ the stack builder


class StackBuilder(QGroupBox):
    """Name, members and span of a synthetic remote, and its build_stack.py command line.

    Args:
        state: The shared `crust.gui.app.State`.
        window_bar (WindowBar): Supplies the processing window.
        parent (QWidget | None): Qt parent.
    """

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
        # fixed list height and two hint lines reserved: the Process tab's splitter ignores the
        # wrapped hint's height-for-width; a minimum equal to the drawn height keeps the builder
        # from overlapping the map above it (340 px minimum)
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
        """Refill the candidates for the current station."""
        self.set_station(self.station)

    def set_station(self, station: str | None) -> None:
        """Refill the candidates (every raw site but `station`), keeping the selection, and set the default name."""
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
        """Return the selected members."""
        return [item.text() for item in self.list.selectedItems()]

    def argv(self) -> list[str] | None:
        """Build the command line `build_stack.py <survey.yaml> <name> <start> <end> <members...>`.

        Returns:
            list[str] | None: The argv, or None with the reason shown in the hint.
        """
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
    """Settings a single run may change: the engine, the band kwargs, the ingest filters, the masks and the tag.

    The engine combo picks aurora (the default, no flag) or MANTLE
    (`--engine mantle`). MANTLE runs on its own estimator, so with it the
    aurora estimator block is disabled and passes nothing, and masks.yaml is
    left out of the run: `--no-masks` is passed whenever the pair declares
    masks, whatever the masks switch says (`engine_changed` lets the tab
    say so on its status line).

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    ENGINES = ("aurora", "mantle")
    engine_changed = Signal(str)
    MASKS_TEXT = "apply masks.yaml"
    MASKS_TIP = (
        "On (default): the run leaves out the intervals in masks.yaml. Masks are declared "
        "per site on the Cross-powers tab and apply with any remote; the remote site's own "
        "masks apply too (a stacked remote, STK_..., has none). Off adds --no-masks: "
        "masks.yaml is ignored for both sites."
    )

    def __init__(self, state, parent=None):
        super().__init__("Run options (survey defaults; only what you change is passed)", parent)
        self.state = state
        self.defaults: dict = {}

        self.engine_combo = QComboBox(self)
        self.engine_combo.addItems(self.ENGINES)
        self.engine_combo.setToolTip(
            "aurora (default): the IAGA-DVI stack's estimator, with the options below. mantle: MANTLE's "
            "DPSS multitaper, robust remote-reference cascade with block-jackknife error bars, on the same "
            "archives and window (--engine mantle); its EDI is pooled onto the same band scheme, and MANTLE's "
            "fine-grid EDI and report JSON land beside it. The aurora estimator block and masks.yaml do "
            "not reach a MANTLE run."
        )
        self.engine_combo.currentTextChanged.connect(self._engine_changed)

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
        self.masks_check = QCheckBox(self.MASKS_TEXT, self, checked=True)
        self.masks_check.setToolTip(self.MASKS_TIP)
        self._masks_declared = False
        self.tag_edit = QLineEdit(self)
        self.tag_edit.setPlaceholderText("tag suffix (optional), e.g. nofilt or try2")

        # the options block: three columns of label + control
        grid = QGridLayout(self)
        for row, column, widget in (
            (0, 0, QLabel("Min period", self)), (0, 1, self.min_spin),
            (0, 2, QLabel("Max period", self)), (0, 3, self.max_spin),
            (0, 4, QLabel("Periods per decade", self)), (0, 5, self.decade_spin),
            (1, 0, QLabel("Notch (Hz)", self)), (1, 1, self.notch_edit),
            (1, 2, QLabel("Output tag suffix", self)), (1, 3, self.tag_edit),
            (1, 4, QLabel("Engine", self)), (1, 5, self.engine_combo),
        ):
            grid.addWidget(widget, row, column)
        grid.addWidget(self.filters_check, 2, 0, 1, 2)
        grid.addWidget(self.filters_label, 2, 2, 1, 4)
        grid.addWidget(self.masks_check, 3, 0, 1, 6)
        self.advanced = EstimatorOptions(self)
        grid.addWidget(self.advanced, 4, 0, 1, 6)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)

    def reload(self) -> None:
        """Reset to the survey's band block with aurora, filters and masks on and no tag."""
        self.defaults = band_defaults(self.state.survey)
        for spin, key in ((self.min_spin, "min_period"), (self.max_spin, "max_period"),
                          (self.decade_spin, "periods_per_decade")):
            spin.setValue(float(self.defaults[key]))
        self.notch_edit.setText(notch_text(self.defaults["notch_frequencies"]))
        self.filters_check.setChecked(True)
        self.masks_check.setChecked(True)
        self.tag_edit.clear()
        self.engine_combo.setCurrentText(self.ENGINES[0])
        self.advanced.reset()

    def engine(self) -> str:
        """Return the engine chosen, "aurora" or "mantle"."""
        return self.engine_combo.currentText()

    def _engine_changed(self, engine: str) -> None:
        """Disable the aurora estimator block and the masks switch for MANTLE, and tell the tab."""
        aurora = engine == self.ENGINES[0]
        self.advanced.setEnabled(aurora)
        self.masks_check.setEnabled(aurora and self._masks_declared)
        self.engine_changed.emit(engine)

    def masks_declared(self) -> bool:
        """Return whether the pair shown declares masks.yaml entries (`describe_masks`)."""
        return self._masks_declared

    def describe_filters(self, station, remote=None) -> None:
        """Show the filters the station and the remote declare in `filters.yaml`.

        Each list is applied on demand into a filtered variant of the site's
        raw archive (`crust.ingest.processing_archive`) when a run uses
        filters (`filters_check`, on by default). The line also says whether
        each variant is ready or will be built first.

        Args:
            station (str | None): Local station.
            remote (str | None): Remote station.
        """
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

    def describe_masks(self, station, remote=None) -> None:
        """Label the masks switch with the mask count of each site of the pair.

        The label reads 'apply masks.yaml (<station>: n, <remote>: m)' from
        `load_masks` and `remote_masks`. A stacked remote (`is_stack`, the
        name rule process_rr uses, independent of `data_root` being mounted)
        has no masks and is left out. When neither site has masks the switch
        is disabled and ticked, reading '(no masks declared)', so a greyed box
        is not mistaken for switched off. An unreadable file shows
        '(masks.yaml unreadable)' with the error in the tooltip.

        Args:
            station (str | None): Local station.
            remote (str | None): Remote station.
        """
        survey = self.state.survey
        counts = []
        try:
            if station and survey is not None:
                counts.append((station, len(load_masks(survey, station))))
                if remote and remote != station and not is_stack(remote):
                    counts.append((remote, len(remote_masks(survey, remote))))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._masks_declared = True  # the run reports the file's error; the switch stays enabled
            self.masks_check.setEnabled(True)
            self.masks_check.setText(f"{self.MASKS_TEXT} (masks.yaml unreadable)")
            self.masks_check.setToolTip(f"{self.MASKS_TIP}\n\nmasks.yaml could not be read: {exc}")
            return
        self.masks_check.setToolTip(self.MASKS_TIP)
        self._masks_declared = any(n for _site, n in counts)
        self.masks_check.setEnabled(self._masks_declared and self.engine() == self.ENGINES[0])
        if not self._masks_declared:
            self.masks_check.setChecked(True)
        detail = (", ".join(f"{site}: {n}" for site, n in counts) if self._masks_declared
                  else "no masks declared")
        self.masks_check.setText(f"{self.MASKS_TEXT} ({detail})")

    def flags(self) -> list[str]:
        """Return process_rr.py flags for the settings changed from the defaults.

        Covers --min-period, --max-period, --per-decade, --notch,
        --no-filters, --no-masks (when the pair has masks), --tag and the
        estimator flags; with MANTLE chosen, `--engine mantle`, `--no-masks`
        whenever the pair has masks, and no estimator flag.

        Returns:
            list[str]: The flags.
        """
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
        mantle = self.engine() != self.ENGINES[0]
        if self._masks_declared and (mantle or not self.masks_check.isChecked()):
            out.append("--no-masks")
        tag = self.tag_edit.text().strip()
        if tag:
            out.append(f"--tag={tag}")  # the '=' form survives a tag typed with a leading dash
        if mantle:
            return out + ["--engine", self.engine()]
        return out + self.advanced.flags()


class EstimatorOptions(QWidget):
    """Collapsible "Advanced (aurora estimator)" block for process_rr.py's --taper ... --tolerance.

    Collapsed by default. Every control starts at the value a run uses when
    the flag is absent (`ESTIMATOR_DEFAULTS`, checked against a real aurora
    config by tests/process_rr_cli_unit.py), and only a control moved off
    that value becomes a flag.

    Args:
        parent (QWidget | None): Qt parent.
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
        """Show or hide the block and set the toggle's arrow."""
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.block.setVisible(expanded)

    def _numbers(self):
        """Return (flag, spin box, ESTIMATOR_DEFAULTS key) for each number, in process_rr.py's order."""
        return (("--overlap", self.overlap_spin, "overlap_pct"),
                ("--min-windows", self.min_windows_spin, "min_windows"),
                ("--max-iterations", self.iterations_spin, "max_iterations"),
                ("--redescending-iterations", self.redescending_spin, "redescending_iterations"),
                ("--r0", self.r0_spin, "r0"), ("--u0", self.u0_spin, "u0"),
                ("--tolerance", self.tolerance_spin, "tolerance"))

    def reset(self) -> None:
        """Reset every control to the value a run uses without its flag."""
        self.taper_combo.setCurrentText(ESTIMATOR_DEFAULTS["taper"])
        self.prewhiten_check.setChecked(bool(ESTIMATOR_DEFAULTS["prewhiten"]))
        for _flag, spin, key in self._numbers():
            value = ESTIMATOR_DEFAULTS[key]
            spin.setValue(int(value) if isinstance(spin, QSpinBox) else float(value))

    def flags(self) -> list[str]:
        """Return --taper, --no-prewhiten and --overlap ... --tolerance for the controls moved off their default."""
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
