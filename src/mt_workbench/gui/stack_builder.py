# -*- coding: utf-8 -*-
"""
Stack builder and run options of the Process tab

* `StackBuilder`: the recipe picker. It lists the recipes of the survey's
  stacks.yaml (declared on the Stacks tab) and builds their command lines:
  `scripts/build_stack.py <survey.yaml> --recipe NAME --overwrite` for a
  time recipe, which the Process tab's "Build stack" button queues, and
  `scripts/process_intersite.py` with `--stack NAME` for a `use: base` band
  recipe over the station, the remote and the window, which its "Queue
  intersite" button queues. "edit in Stacks tab..." opens the recipe there.
  `base_argv` builds that command line for a named base recipe and a named
  station, with a tag and the filters switch. The Process tab's Base box
  lists the recipes of `base_recipes` as "stack: NAME" and queues through it.
* `RunOptions`: the group box of settings a run can vary (the four band
  kwargs, the band layout's window samples and min bin, the min band windows
  floor, the ingest-filters switch, the masks.yaml switch and the output tag
  suffix). It returns `scripts/process_rr.py` flags for the settings changed
  from the survey's `processing:` block only. Below it, collapsed by default,
  `EstimatorOptions` ("Advanced (aurora estimator)") covers process_rr.py's
  --taper ... --tolerance by the same rule, against the values a run uses
  (`mt_workbench.process.ESTIMATOR_DEFAULTS`). While a tensor type is chosen
  on the Process tab, `RunOptions.set_tensor` disables every setting but the
  tag and the filters switch, the two a tensor run takes.

Queue intersite is enabled only for a command line process_intersite takes:
the station and the remote at the recipe's rate, neither a burst site, and,
judged from `State.runs_cache` over the window (stats only), the remote not
among the base stack's members, at least the recipe's `min_members` members
and, for a recipe of `member_change: constant`, no member's record starting
or ending inside the window (`mt_workbench.intersite.member_changes` over the
same cached runs, the test the run applies). While the remote's runs are not
read yet, the recipe's declaration decides whether it would be a member.

`StackBuilder.intersite_argv` and `RunOptions.flags` assemble command lines from a
`WindowBar`, the survey's `processing:` block (`band_defaults`) and the
estimator defaults. The masks switch shows, for the pair, the count of the
station's masks of scope local or both (`mt_workbench.masks.masks_for_role`) and
of the remote's masks of scope both or remote that name hx, hy or every
channel (`mt_workbench.masks.remote_masks`), the ones process_rr.py applies.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import inspect
import math

import pandas as pd
import yaml

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

from mt_workbench import intersite, stacks
from mt_workbench.bands import build_band_scheme
from mt_workbench.ingest import variant_ready
from mt_workbench.masks import is_stack, load_masks, masks_for_role, remote_masks
from mt_workbench.process import ESTIMATOR_DEFAULTS, MIN_BAND_WINDOWS, TAPERS
from mt_workbench.gui.window_bar import UTC_FMT, WindowBar

# the band kwargs a run can override, in `scripts/process_rr.py`'s order: the
# four of the period grid, then the band layout's FFT window and lowest band edge
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies", "window", "min_bin")


def band_defaults(survey) -> dict:
    """Return the survey's band settings: its `processing:` block over `build_band_scheme`'s defaults.

    `scripts/process_rr.py` applies the same rule, so a value changed from
    these defaults is one that needs a command-line flag. `min_bin` is None
    (the layout's own) when the survey gives none. `min_band_windows` is
    the survey's `processing: min_band_windows`, else
    `mt_workbench.process.MIN_BAND_WINDOWS`.

    Args:
        survey: The open `mt_workbench.survey.Survey`, or None.

    Returns:
        dict: The values of `BAND_KEYS` and ``min_band_windows``.
    """
    signature = inspect.signature(build_band_scheme).parameters
    out = {key: signature[key].default for key in BAND_KEYS}
    out.update({k: v for k, v in (survey.processing if survey else {}).items() if k in out})
    floor = survey.min_band_windows if survey else None
    out["min_band_windows"] = MIN_BAND_WINDOWS if floor is None else int(floor)
    return out


def notch_text(values) -> str:
    """Format notch frequencies as comma-separated Hz."""
    return ", ".join(f"{float(v):g}" for v in values or ())


# ------------------------------------------------------------ the recipe picker


def describe(recipe: stacks.Recipe) -> str:
    """Return a recipe's picker label tail: "time mean, 2023-09-19 19:02 to 09-21 07:02" or "band median, base"."""
    label = stacks.METHODS[recipe.method].label
    if recipe.engine == "time":
        return f"{label}, {recipe.start:%Y-%m-%d %H:%M} to {recipe.end:%m-%d %H:%M}"
    return f"{label}, {recipe.use}"


class StackBuilder(QGroupBox):
    """The Process tab's recipe picker: a stack recipe of stacks.yaml and its command lines.

    A time recipe gives ``scripts/build_stack.py <survey.yaml> --recipe NAME
    --overwrite`` (`argv`, queued by the row-3 Build stack button); a
    ``use: base`` band recipe gives ``scripts/process_intersite.py`` for the
    station, the remote and the window bar's window with ``--stack NAME``
    (`intersite_argv`, queued by Queue intersite). A ``use: reference`` band
    recipe needs a base site the Process tab does not hold, so it runs from
    the command line the Stacks tab shows. Recipes are declared and saved on
    the Stacks tab; "edit in Stacks tab..." opens the chosen one there.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        window_bar (WindowBar): Supplies the processing window.
        parent (QWidget | None): Qt parent.
    """

    build_requested = Signal(list)  # a build_stack.py argv, for the tab to queue
    members_changed = Signal(list)  # a time recipe's members, for the map to paint them orange
    edit_requested = Signal(str)  # the recipe to open on the Stacks tab, "" for a new one
    intersite_requested = Signal(list)  # a process_intersite.py argv, for the tab to queue

    EDIT = "edit in Stacks tab..."
    NO_RECIPES = "(no recipe in stacks.yaml)"
    RUN_OPTIONS_NOTE = "The run options (engine, bands, masks, estimator) apply to process_rr.py only."

    def __init__(self, state, window_bar: WindowBar, parent=None):
        super().__init__("Stack recipe (stacks.yaml)", parent)
        self.state = state
        self.window_bar = window_bar
        self.station: str | None = None
        self.remote: str | None = None
        self._recipes: dict[str, stacks.Recipe] = {}
        self._errors: dict[str, str] = {}
        self._file_error: str | None = None
        self._name: str | None = None  # the recipe chosen, kept across reloads
        self._painted: list[str] = []

        self.recipe_combo = QComboBox(self)
        self.recipe_combo.setToolTip("The recipes of the survey's stacks.yaml, declared on the Stacks tab")
        self.members_line = QLineEdit(self, readOnly=True)
        self.intersite_button = QPushButton("Queue intersite", self)
        self.intersite_button.setToolTip("process_intersite.py: the station on the base stack of the recipe, "
                                         "the remote as the reference, over the processing window")
        # four hint lines reserved: the Process tab's splitter ignores a wrapped label's
        # height-for-width, and a minimum equal to the drawn height keeps the box off the map
        self.hint = QLabel("", self, wordWrap=True)
        self.hint.setMinimumHeight(4 * self.hint.fontMetrics().lineSpacing())

        layout = QGridLayout(self)
        layout.addWidget(QLabel("Recipe", self), 0, 0)
        layout.addWidget(self.recipe_combo, 0, 1)
        layout.addWidget(QLabel("Members", self), 1, 0)
        layout.addWidget(self.members_line, 1, 1)
        layout.addWidget(self.intersite_button, 2, 1, Qt.AlignLeft)
        layout.addWidget(self.hint, 3, 0, 1, 2)
        layout.setColumnStretch(1, 1)
        self.recipe_combo.currentIndexChanged.connect(self._chosen)
        self.intersite_button.clicked.connect(self.queue_intersite)
        self.window_bar.window_changed.connect(lambda *_args: self._refresh())

    # ------------------------------------------------------------ the list

    def reload(self) -> None:
        """Read stacks.yaml again (it is parsed once per change) and refill the list, keeping the recipe chosen."""
        self._recipes, self._errors, self._file_error = {}, {}, None
        if self.state.survey is not None:
            try:
                self._recipes, self._errors = stacks.load_recipes(self.state.survey)
            except (stacks.StacksError, OSError) as exc:
                self._file_error = str(exc)
        self.recipe_combo.blockSignals(True)
        try:
            self.recipe_combo.clear()
            if not self._recipes:
                self.recipe_combo.addItem(self.NO_RECIPES, None)
            for name, recipe in self._recipes.items():
                self.recipe_combo.addItem(f"{name}  ({describe(recipe)})", name)
            self.recipe_combo.addItem(self.EDIT, self.EDIT)
            index = self.recipe_combo.findData(self._name) if self._name in self._recipes else -1
            self.recipe_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.recipe_combo.blockSignals(False)
        self._name = self.recipe_combo.currentData()
        self._refresh()

    def names(self) -> list[str]:
        """Return the recipe names listed, in file order."""
        return list(self._recipes)

    def recipe(self) -> stacks.Recipe | None:
        """Return the recipe chosen, or None."""
        return self._recipes.get(self._name)

    def recipe_named(self, name: str) -> stacks.Recipe | None:
        """Return a listed recipe by name, or None."""
        return self._recipes.get(name)

    def select_recipe(self, name: str) -> bool:
        """Choose a recipe; False when stacks.yaml holds no valid recipe of that name."""
        index = self.recipe_combo.findData(name) if name in self._recipes else -1
        if index < 0:
            return False
        self.recipe_combo.setCurrentIndex(index)
        self._name = name
        self._refresh()
        return True

    def set_pair(self, station: str | None, remote: str | None) -> None:
        """Take the Process tab's station and remote, which the recipe's command lines and hint are judged for."""
        self.station, self.remote = station, remote
        self._refresh()

    def members(self) -> list[str]:
        """Return a time recipe's members (painted orange on the map); [] for a band recipe or none."""
        recipe = self.recipe()
        return [] if recipe is None or recipe.members is None or recipe.engine != "time" else list(recipe.members)

    def holds(self, name: str | None, station: str | None) -> bool:
        """True when `name` is a listed time recipe holding `station`: its archive is not that station's remote."""
        recipe = self._recipes.get(name) if name else None
        return bool(station) and recipe is not None and recipe.engine == "time" and station in (recipe.members or ())

    def refresh(self) -> None:
        """Judge the command lines again, for example once the Stacks chart has read more archives."""
        self._refresh()

    def _chosen(self, index: int) -> None:
        """Take the recipe chosen; the edit entry opens the chosen recipe on the Stacks tab and stays off."""
        data = self.recipe_combo.itemData(index)
        if data == self.EDIT:
            back = self.recipe_combo.findData(self._name)
            self.recipe_combo.blockSignals(True)
            self.recipe_combo.setCurrentIndex(max(0, back))
            self.recipe_combo.blockSignals(False)
            self.edit_requested.emit(self._name or "")
            return
        self._name = data
        self._refresh()

    # ---------------------------------------------------- the command lines

    def _build(self) -> tuple[list[str] | None, str]:
        """Return (build_stack.py argv, "") for a time recipe, else (None, the reason)."""
        if self.state.survey_yaml is None:
            return None, "open a survey first"
        if self._file_error:
            return None, f"stacks.yaml cannot be used: {self._file_error}"
        recipe = self.recipe()
        if recipe is None:
            return None, "no stacks.yaml recipe: declare one on the Stacks tab"
        if recipe.engine != "time":
            return None, "a band recipe is formed inside scripts/process_intersite.py: Queue intersite"
        return stacks.build_argv(self.state.python_exe, self.state.script("build_stack.py"),
                                 str(self.state.survey_yaml), recipe.name), ""

    def base_recipes(self, field: str, rate: float) -> list[str]:
        """Return the listed ``use: base`` band recipes of a field (E or H) at `rate` Hz, in file order."""
        return [name for name, recipe in self._recipes.items()
                if recipe.engine == "band" and recipe.use == "base" and recipe.field == field
                and math.isclose(recipe.sample_rate, float(rate), rel_tol=1e-9)]

    def base_argv(self, name: str, station: str, tag: str | None = None,
                  no_filters: bool | None = None) -> tuple[list[str] | None, str]:
        """Return (process_intersite.py argv, "") for a station on the base recipe `name`, else (None, the reason).

        The Process tab's Base box calls this for a "stack: NAME" entry.
        The checks are Queue intersite's (`_intersite`), made for `station`
        in place of the tab's station, with the run's tag and its filters
        switch.

        Args:
            name (str): A ``use: base`` band recipe of stacks.yaml.
            station (str): The local site.
            tag (str | None): ``--tag``.
            no_filters (bool | None): The filters switch as the run has it,
                refused when the recipe's `use_filters` says otherwise, as
                the script refuses it; None takes the recipe's.

        Returns:
            tuple: (the command line, "") or (None, the reason).
        """
        recipe = self._recipes.get(name)
        if recipe is None:
            return None, f"{name}: no valid recipe of that name in stacks.yaml: declare it on the Stacks tab"
        return self._intersite(recipe, station, tag, no_filters)

    def _intersite(self, recipe=None, station=None, tag=None, no_filters=None) -> tuple[list[str] | None, str]:
        """Return (process_intersite.py argv, "") for a base band recipe and the pair, else (None, the reason).

        Queue intersite judges the recipe chosen in the picker for the
        tab's station; `base_argv` gives the recipe, the station, the tag
        and the filters switch.
        """
        survey = self.state.survey
        recipe = self.recipe() if recipe is None else recipe
        if survey is None or self.state.survey_yaml is None:
            return None, "open a survey first"
        if recipe is None:
            return None, "no stacks.yaml recipe: declare one on the Stacks tab"
        if recipe.engine != "band":
            return None, (f"{recipe.name} is an archive for process_rr.py: Build stack, then pick it as the "
                          f"remote")
        if recipe.use != "base":
            return None, f"{recipe.name} is a reference recipe: it needs a base site: the Stacks tab's command line"
        station, remote = station or self.station, self.remote
        if not station:
            return None, "pick a station"
        names = survey.site_names()
        rate = survey.sample_rate_of(station) if station in names else None
        if rate is None or not math.isclose(float(rate), recipe.sample_rate, rel_tol=1e-9):
            at = "no survey.yaml entry" if rate is None else f"{float(rate):g} Hz"
            return None, f"{station} is at {at}, {recipe.name} at {recipe.sample_rate:g} Hz"
        if not remote:
            return None, "pick a remote"
        if remote not in names:
            return None, (f"{remote}: process_intersite takes a survey.yaml site as --remote; a stack archive "
                          f"is process_rr.py's")
        remote_rate = float(survey.sample_rate_of(remote))
        if not math.isclose(remote_rate, recipe.sample_rate, rel_tol=1e-9):
            return None, (f"{remote} is at {remote_rate:g} Hz and {station} at {recipe.sample_rate:g} Hz: "
                          f"process_intersite takes a remote at the local's rate")
        bursts = [s for s in (station, remote) if survey.bursts_parent(s)]
        if bursts:
            return None, (f"{', '.join(bursts)}: burst sites are read on a compact grid of their bursts, and "
                          f"process_intersite takes no stack with them")
        if no_filters is not None and no_filters == recipe.use_filters:
            return None, (f"{recipe.name} declares use_filters: {str(recipe.use_filters).lower()}: "
                          f"{'tick' if recipe.use_filters else 'untick'} \"use declared filters\", or change the "
                          f"recipe on the Stacks tab")
        window = self.window_bar.window()
        if window is None:
            return None, "the processing window must have a start and an end"
        refused = self._members_refusal(recipe, survey, station, remote, window)
        if refused:
            return None, refused
        return stacks.intersite_argv(
            self.state.python_exe, self.state.script("process_intersite.py"), str(self.state.survey_yaml),
            station, stacks.KIND_OF_BASE[recipe.field], [recipe.name], remote=remote,
            start=window[0].strftime(UTC_FMT), end=window[1].strftime(UTC_FMT), tag=tag,
            no_filters=not recipe.use_filters), ""

    def _members_refusal(self, recipe, survey, station: str, remote: str, window) -> str:
        """Return why process_intersite would refuse the base stack over the window, or "".

        The members are `stacks.resolve_members` over `State.runs_cache`
        (stats only). The remote among them would be both a base member and
        the reference, which process_intersite refuses without
        --allow-shared-members; while the remote's runs are not read, the
        declaration decides (a list holding it, or a rule recipe that does
        not exclude it). Fewer members than the recipe's min_members are
        refused too, once no candidate is waiting for its read. For a recipe
        of ``member_change: constant``, a member's record starting or ending
        inside the window (`intersite.member_changes` over the same cached
        runs) is refused as the run refuses it; a change among the members
        read so far is enough, whatever candidate is still waiting.

        Args:
            recipe (stacks.Recipe): A ``use: base`` band recipe.
            survey: The open `mt_workbench.survey.Survey`.
            station (str): The local site.
            remote (str): The remote site.
            window (tuple): The processing window, two UTC timestamps.

        Returns:
            str: The refusal, for the hint's first line, or "".
        """
        runs_of = self.state.runs_cache.runs_of(survey)
        try:
            members, left_out = stacks.resolve_members(recipe, survey, window=window, local=station,
                                                       runs_of=runs_of)
        except stacks.StacksError as exc:
            return str(exc)
        names = [m["site"] for m in members]
        unread = {d["site"] for d in left_out if d["reason"] == intersite.NOT_READ}
        declared = remote in recipe.members if recipe.members is not None else remote not in recipe.exclude
        if remote in names or (remote in unread and declared):
            return (f"{remote} would sit in {recipe.name}'s base stack and be the reference: exclude it in "
                    f"{recipe.name} on the Stacks tab, or run from the command line with --allow-shared-members")
        if not unread and len(names) < recipe.min_members:
            return (f"{recipe.name} has {len(names)} member(s) over the window, fewer than its min_members "
                    f"{recipe.min_members}: move the window or change the recipe")
        if recipe.member_change == "constant":
            changes = intersite.member_changes(survey, members, recipe.roles, int(window[0].value),
                                               int(window[1].value), runs_of=runs_of)
            if changes:
                first = changes[0]
                more = f" (and {len(changes) - 1} more)" if len(changes) > 1 else ""
                when = pd.Timestamp(first["time_ns"], tz="UTC").strftime(UTC_FMT)
                return (f"{recipe.name}'s membership changes inside the window: {first['site']} "
                        f"{first['change']} at {when}{more}: move the window inside one constant-membership "
                        f"epoch, or set member_change: allow in {recipe.name} on the Stacks tab")
        return ""

    def argv(self) -> list[str] | None:
        """Return the build_stack.py command line of a time recipe, or None with the reason in the hint.

        Returns:
            list[str] | None: ``[python, build_stack.py, survey.yaml,
            --recipe, NAME, --overwrite]``.
        """
        argv, why = self._build()
        if argv is None:
            self.hint.setText(f"{why}\n{self.RUN_OPTIONS_NOTE}")
        return argv

    def intersite_argv(self) -> list[str] | None:
        """Return the process_intersite.py command line of a base band recipe, or None with the reason in the hint.

        Returns:
            list[str] | None: ``[python, process_intersite.py, survey.yaml,
            station, start, end, --kind, KIND, --remote, REMOTE, --stack,
            NAME (, --no-filters)]``.
        """
        argv, why = self._intersite()
        if argv is None:
            self.hint.setText(f"{why}\n{self.RUN_OPTIONS_NOTE}")
        return argv

    def build(self) -> list[str] | None:
        """Emit `build_requested` with the build_stack.py argv, or leave the reason in the hint."""
        argv = self.argv()
        if argv is not None:
            self.build_requested.emit(argv)
        return argv

    def queue_intersite(self) -> list[str] | None:
        """Emit `intersite_requested` with the process_intersite.py argv, or leave the reason in the hint."""
        argv = self.intersite_argv()
        if argv is not None:
            self.intersite_requested.emit(argv)
        return argv

    def _refresh(self) -> None:
        """Show the members, enable Queue intersite, write the hint and repaint the members on the map."""
        recipe = self.recipe()
        if recipe is None:
            self.members_line.setText("")
        elif recipe.members is None:
            self.members_line.setText("members by rule, resolved in each run"
                                      + (f"; excluded {', '.join(recipe.exclude)}" if recipe.exclude else ""))
        else:
            self.members_line.setText(", ".join(recipe.members))
        argv, why = self._intersite()
        self.intersite_button.setEnabled(argv is not None)
        lines = []
        if self._errors:
            lines.append(f"unreadable in stacks.yaml: {', '.join(self._errors)} (see the Stacks tab)")
        if recipe is not None and recipe.engine == "time":
            if self.station and self.station in recipe.members:
                lines.append(f"{recipe.name} holds {self.station}: not its remote")
            else:
                lines.append(f"Build stack queues build_stack.py --recipe {recipe.name}; once built it is the "
                             f"remote")
        elif argv is not None:
            lines.append(f"Queue intersite: {self.station} on {recipe.name}, --remote {self.remote}, over the "
                         f"window")
            window = self.window_bar.window()
            if recipe.window_ns is not None and window is not None and \
                    (int(window[0].value), int(window[1].value)) != tuple(recipe.window_ns):
                # process_intersite takes the command line's window and only logs the recipe's
                lines.append(f"the bar's window replaces {recipe.name}'s declared window "
                             f"({recipe.start:%Y-%m-%d %H:%M} to {recipe.end:%Y-%m-%d %H:%M})")
        else:
            lines.append(why if recipe is not None or self._file_error is None else self._build()[1])
        lines.append(self.RUN_OPTIONS_NOTE)
        self.hint.setText("\n".join(lines))
        members = self.members()
        if members != self._painted:
            self._painted = members
            self.members_changed.emit(members)


# ------------------------------------------------------------- the run options


class RunOptions(QGroupBox):
    """Settings a single run may change: the engine, the band kwargs, the ingest filters, the masks and the tag.

    The band controls start at the survey's `processing:` block
    (`band_defaults`) and only a control moved off it becomes a flag. The
    third row holds the band layout and the floor: window samples
    (`--window-samples`, the FFT window of every decimation level), min bin
    (`--min-bin`, the lowest band edge of every decimated level in FFT
    harmonics; its lowest value, 0, reads "layout's own": the default when
    the survey gives no `min_bin:`, and `--min-bin 0` over one it gives)
    and min band windows (`--min-band-windows`, the fewest STFT windows a
    band needs for its period to be written; 0 keeps every period).

    The engine combo picks aurora (the default, no flag) or MANTLE
    (`--engine mantle`). MANTLE runs on its own estimator, so with it the
    aurora estimator block and the min band windows control are disabled
    and pass nothing, and masks.yaml is left out of the run: `--no-masks`
    is passed whenever the pair declares masks, whatever the masks switch
    says (`engine_changed` lets the tab say so on its status line). Window
    samples and min bin stay enabled: MANTLE pools its estimate onto the
    same band scheme, whose longest-period band edges they move.

    A tensor run (scripts/process_intersite.py, the Process tab's
    Processing type) takes the tag and the filters switch of this box and
    none of its other settings. `set_tensor` disables those while a tensor
    type is chosen, each with `TENSOR_TIP` as its tooltip, and puts them
    back with their own tooltips afterwards.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    ENGINES = ("aurora", "mantle")
    engine_changed = Signal(str)
    TENSOR_TIP = ("Not passed to a tensor run: scripts/process_intersite.py estimates on the survey's band layout "
                  "with its own estimator and always applies masks.yaml. The tag and the filters switch are passed.")
    MASKS_TEXT = "apply masks.yaml"
    MASKS_TIP = (
        "On (default): the run leaves out the intervals in masks.yaml. Masks are declared "
        "per site on the Cross-powers tab and apply with any remote; the remote site's masks "
        "of scope both or remote apply too (scope local, the default, applies only when the site is "
        "the local, scope remote only when it is the remote; a remote's mask naming only ex, ey or hz "
        "is left out; a stacked remote, STK_..., has none). Off adds --no-masks: masks.yaml is "
        "ignored for both sites."
    )

    def __init__(self, state, parent=None):
        super().__init__("Run options (survey defaults; only what you change is passed)", parent)
        self.state = state
        self.defaults: dict = {}
        self._tensor = False  # True while a tensor type is chosen on the Process tab (`set_tensor`)
        self._tips: dict = {}  # the tooltips `TENSOR_TIP` stands in for meanwhile

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
        self.window_spin = QSpinBox(self, minimum=16, maximum=65536, singleStep=128, suffix=" samples")
        self.window_spin.setToolTip(
            "FFT window of every decimation level (--window-samples); starts at the survey's window:, else "
            "128. Every band keeps its period and spans window/128 times the harmonics.")
        self.min_bin_spin = QDoubleSpinBox(self, decimals=2, minimum=0.0, maximum=100.0, singleStep=1.0)
        self.min_bin_spin.setSpecialValueText("layout's own")
        self.min_bin_spin.setToolTip(
            "Lowest band edge of every decimated level, in FFT harmonics (--min-bin): the first edge of the "
            "layout at or above it. Starts at the survey's min_bin:, else at 0, which reads \"layout's own\" "
            "(6.4 at 1000 Hz) and passes no flag; set to 0 over a survey's min_bin: it passes --min-bin 0, "
            "the layout's own.")
        self.floor_spin = QSpinBox(self, minimum=0, maximum=100000)
        self.floor_spin.setToolTip(
            "aurora: a period whose band rests on fewer STFT windows is not written (--min-band-windows); "
            f"starts at the survey's min_band_windows:, else {MIN_BAND_WINDOWS}; 0 keeps every period. "
            "MANTLE applies no such floor, so the control is disabled with it.")
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
            (2, 0, QLabel("Window samples", self)), (2, 1, self.window_spin),
            (2, 2, QLabel("Min bin", self)), (2, 3, self.min_bin_spin),
            (2, 4, QLabel("Min band windows", self)), (2, 5, self.floor_spin),
        ):
            grid.addWidget(widget, row, column)
        grid.addWidget(self.filters_check, 3, 0, 1, 2)
        grid.addWidget(self.filters_label, 3, 2, 1, 4)
        grid.addWidget(self.masks_check, 4, 0, 1, 6)
        self.advanced = EstimatorOptions(self)
        grid.addWidget(self.advanced, 5, 0, 1, 6)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)

    def reload(self) -> None:
        """Reset to the survey's band block with aurora, filters and masks on and no tag."""
        self.defaults = band_defaults(self.state.survey)
        for spin, key in ((self.min_spin, "min_period"), (self.max_spin, "max_period"),
                          (self.decade_spin, "periods_per_decade")):
            spin.setValue(float(self.defaults[key]))
        self.notch_edit.setText(notch_text(self.defaults["notch_frequencies"]))
        self.window_spin.setValue(int(self.defaults["window"]))
        self.min_bin_spin.setValue(self._min_bin_default())
        self.floor_spin.setValue(int(self.defaults["min_band_windows"]))
        self.filters_check.setChecked(True)
        self.masks_check.setChecked(True)
        self.tag_edit.clear()
        self.engine_combo.setCurrentText(self.ENGINES[0])
        self.advanced.reset()

    def _min_bin_default(self) -> float:
        """Return the min bin control's default: the survey's `min_bin:`, else 0, the layout's own."""
        value = self.defaults.get("min_bin")
        return 0.0 if value is None else float(value)

    def engine(self) -> str:
        """Return the engine chosen, "aurora" or "mantle"."""
        return self.engine_combo.currentText()

    def _engine_changed(self, engine: str) -> None:
        """Disable the aurora estimator block, the min band windows control and the masks switch for MANTLE."""
        aurora = engine == self.ENGINES[0] and not self._tensor  # a tensor type keeps all three disabled
        self.advanced.setEnabled(aurora)
        self.floor_spin.setEnabled(aurora)
        self.masks_check.setEnabled(aurora and self._masks_declared)
        self.engine_changed.emit(engine)

    def set_tensor(self, on: bool) -> None:
        """Disable the options a tensor run does not take, each with a tooltip saying why; False puts them back.

        The engine, the band controls, the masks switch and the aurora
        estimator block are process_rr.py's. The tag and the filters switch
        stay enabled: scripts/process_intersite.py takes both.

        Args:
            on (bool): True while a tensor type is chosen on the Process tab.
        """
        if on == self._tensor:
            return
        widgets = (self.engine_combo, self.min_spin, self.max_spin, self.decade_spin, self.notch_edit,
                   self.window_spin, self.min_bin_spin, self.floor_spin, self.masks_check, self.advanced)
        if on:
            self._tips = {widget: widget.toolTip() for widget in widgets}
        self._tensor = on
        for widget in widgets:
            widget.setEnabled(not on)
            widget.setToolTip(self.TENSOR_TIP if on else self._tips[widget])
        if not on:
            self._engine_changed(self.engine())  # the engine's rule for its three controls again

    def _set_masks(self, enabled: bool, tip: str) -> None:
        """Enable the masks switch and set its tooltip; a tensor type keeps it disabled and the tooltip for later."""
        if self._tensor:
            self._tips[self.masks_check] = tip
            return
        self.masks_check.setEnabled(enabled)
        self.masks_check.setToolTip(tip)

    def masks_declared(self) -> bool:
        """Return whether the pair shown declares masks.yaml entries (`describe_masks`)."""
        return self._masks_declared

    def describe_filters(self, station, remote=None) -> None:
        """Show the filters the station and the remote declare in `filters.yaml`.

        Each list is applied on demand into a filtered variant of the site's
        raw archive (`mt_workbench.ingest.processing_archive`) when a run uses
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

    def masks_reading(self) -> None:
        """Label the masks switch '(reading masks.yaml...)' while the tab's parse runs; its state is left as it was."""
        self.masks_check.setText(f"{self.MASKS_TEXT} (reading masks.yaml...)")

    def describe_masks(self, station, remote=None) -> None:
        """Label the masks switch with the mask count of each site of the pair.

        The label reads 'apply masks.yaml (<station>: n, <remote>: m)', the
        masks process_rr applies from each site: n from `masks_for_role` (the
        station's masks of scope local or both), m from `remote_masks` (the
        remote's masks of scope both or remote naming hx, hy or every
        channel). A stacked remote
        (`is_stack`, the name rule process_rr uses, independent of
        `data_root` being mounted) has no masks and is left out. When
        neither site has masks to apply the switch
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
                counts.append((station, len(masks_for_role(load_masks(survey, station), "local"))))
                if remote and remote != station and not is_stack(remote):
                    counts.append((remote, len(remote_masks(survey, remote))))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._masks_declared = True  # the run reports the file's error; the switch stays enabled
            self.masks_check.setText(f"{self.MASKS_TEXT} (masks.yaml unreadable)")
            self._set_masks(True, f"{self.MASKS_TIP}\n\nmasks.yaml could not be read: {exc}")
            return
        self._masks_declared = any(n for _site, n in counts)
        self._set_masks(self._masks_declared and self.engine() == self.ENGINES[0], self.MASKS_TIP)
        if not self._masks_declared:
            self.masks_check.setChecked(True)
        detail = (", ".join(f"{site}: {n}" for site, n in counts) if self._masks_declared
                  else "no masks declared")
        self.masks_check.setText(f"{self.MASKS_TEXT} ({detail})")

    def flags(self) -> list[str]:
        """Return process_rr.py flags for the settings changed from the defaults.

        Covers --min-period, --max-period, --per-decade, --notch,
        --window-samples, --min-bin, --no-filters, --no-masks (when the pair
        has masks), --tag, --min-band-windows and the estimator flags; with
        MANTLE chosen, `--engine mantle`, `--no-masks` whenever the pair has
        masks, and neither --min-band-windows nor an estimator flag.

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
        if self.defaults and self.window_spin.value() != int(self.defaults["window"]):
            out += ["--window-samples", str(self.window_spin.value())]
        if self.defaults and abs(self.min_bin_spin.value() - self._min_bin_default()) > 1e-9:
            out += ["--min-bin", f"{self.min_bin_spin.value():g}"]
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
        if self.defaults and self.floor_spin.value() != int(self.defaults["min_band_windows"]):
            out += ["--min-band-windows", str(self.floor_spin.value())]
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
            "STFT overlap (--overlap). Left at 25 % no flag is passed and levels whose window "
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
