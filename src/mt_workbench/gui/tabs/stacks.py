# -*- coding: utf-8 -*-
"""
Stacks tab

Declares the stack recipes of the survey's stacks.yaml (`mt_workbench.stacks`)
and shows what a recipe takes: which sites are live over which window, which
the recipe keeps and why it leaves the others out, and how its members agree
on the loaded window. From the top:

1. The recipe combo (the recipes of stacks.yaml, an unreadable one as "NAME
   (unreadable: ...)", and "(new recipe)"), a time recipe's archive status,
   and the local: the site a band stack is formed for, at the recipe's
   rate. The local follows the site selected on any tab, except the
   selection the tab's own bar click makes, and is passed on only at the
   recipe's rate; a time recipe takes none (its archive is the same for
   every local).
2. On the left, the recipe form (`stack_form.RecipeForm`); on the right the
   availability chart (`availability.AvailabilityChart`): every site's runs
   on one UTC axis, the recipe's members and the reasons it leaves the
   others out, the window, the nights, the masks and the members per hour.
3. Under the chart, the member check and preview
   (`stack_check.MemberCheck`): on the loaded window, bounded by
   `stackcheck.check_span`, each member's coherence with the others, its
   polarity, and the stack's band power over the members'.
   It runs 500 ms after the members, the method or its parameters change
   while the tab is shown, and at Check; only when the loaded station's
   rate is the recipe's. It reads members on its own only while the reads
   stay under `AUTO_CHECK_SAMPLES` (members times samples per channel:
   about five members over an hour at 1000 Hz); a larger set is read at
   Check, and a method or parameter edit then recomputes from the arrays
   held. Hiding the tab drops the members' arrays.
4. Save recipe, Build archive, Use in Process, the status line, and the
   recipe's command line to copy. Choosing another recipe while
   the form holds edits not saved says so on the status line ("unsaved
   edits to STK_X dropped"); stacks.yaml is left unchanged.

Save recipe writes the recipe's block of stacks.yaml (`stacks.save_recipe`),
every other byte unchanged; the chart's Save view writes the chart block
(`stacks.save_chart`). These are the tab's only writes. Build archive queues
scripts/build_stack.py for a saved time recipe on the Process tab's queue
(`ProcessTab.queue_stack`; it waits for Run queue there), and Use in Process
hands a saved time recipe or base band recipe to the Process tab's recipe
picker. A reference band recipe needs a base site the Process tab does not
hold and runs from the command line shown. The tab computes no product: the
chart reads run lists, and the check reads at most
`stackcheck.MAX_CHECK_SAMPLES` samples per member channel and computes in
`mt_workbench.stackcheck`.

A click on a site's bar selects the Time Series tree window that holds the
instant (`availability_model.tree_window_at`) and shows it there.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from mt_workbench import stackcheck, stacks
from mt_workbench.gui import availability_model
from mt_workbench.gui.availability import AvailabilityChart
from mt_workbench.gui.stack_check import MemberCheck
from mt_workbench.gui.stack_form import RecipeForm
from mt_workbench.gui.theme import IDLE_COLOUR, WARN_COLOUR

NEW = "(new recipe)"
NO_LOCAL = "(none)"
DEBOUNCE_MS = 500  # the check waits this long after the last change of what it reads
# members x samples per channel the check reads without a Check click: 16 members of an hour at 1000 Hz took
# 24.6 s and held 461 MB plus 501 MB while computing [measured by the check builder, synthetic]
AUTO_CHECK_SAMPLES = 20_000_000
NO_WINDOW = "load a window on the Time Series tab to check the members"
BUILD_TIP = "build_stack.py --recipe {name} --overwrite, queued on the Process tab: Run queue there starts it"
REFERENCE_TIP = "a reference recipe needs a base site: run it from the command line below"
SAVE_FIRST = "save first: the scripts read the recipe from stacks.yaml"


def _quote(arg: str) -> str:
    """Quote a command-line argument holding a space, for copying."""
    return f'"{arg}"' if " " in arg else arg


class StacksTab(QWidget):
    """Stack recipes: the form, the availability chart, the member check, and the hand-off to Process.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    build_requested = Signal(list)  # a build_stack.py argv, for ProcessTab.queue_stack
    use_in_process_requested = Signal(str)  # a saved recipe's name, for ProcessTab.use_recipe
    recipe_saved = Signal(str)  # the name just written to stacks.yaml

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._recipes: dict[str, stacks.Recipe] = {}
        self._errors: dict[str, str] = {}
        self._file_error: str | None = None
        self._last_valid: stacks.Recipe | None = None  # the chart shows it while the form does not make one
        self._locals_rate: float | None = None
        self._own_click = False  # the site change that the tab's own bar click causes
        self._updating = False
        self._check_key: tuple | None = None
        self._notes = {"action": "", "local": "", "check": ""}
        self._baseline: object = None  # the form's recipe (or its error) as last shown or saved

        self.recipe_combo = QComboBox(self, minimumWidth=260)
        self.recipe_combo.setToolTip("The recipes of the survey's stacks.yaml")
        self.archive_label = QLabel("", self)
        self.archive_label.setStyleSheet(f"color: {IDLE_COLOUR}")
        self.local_combo = QComboBox(self, minimumWidth=120)
        self.local_combo.setToolTip("The site a band stack is formed for: it is never its own member. A time "
                                    "recipe takes none")
        self.form = RecipeForm(state, self)
        self.chart = AvailabilityChart(state, self)
        self.check = MemberCheck(state, self)
        self.check_button = QPushButton("Check", self)
        self.check_button.setToolTip("Check the members on the loaded window now")
        self.save_button = QPushButton("Save recipe", self)
        self.save_button.setToolTip("Write this recipe's block of stacks.yaml; every other line stays as it is")
        self.build_button = QPushButton("Build archive", self)
        self.use_button = QPushButton("Use in Process", self)
        self.status_label = QLabel("", self, wordWrap=True)
        self.command_edit = QLineEdit(self, readOnly=True)
        self.command_edit.setToolTip("The recipe's command line, to copy; <...> marks a site the tab does not "
                                     "hold")
        self._timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._build_layout()

        self._timer.timeout.connect(self._run_check)
        self.recipe_combo.currentIndexChanged.connect(self._recipe_chosen)
        self.local_combo.currentIndexChanged.connect(lambda _i: self._update())
        self.form.changed.connect(self._update)
        self.chart.window_changed.connect(self._chart_window)
        self.chart.rows_changed.connect(self._update)
        self.chart.view_save_requested.connect(self._save_view)
        self.chart.bar_clicked.connect(self._bar_clicked)
        self.check.ready.connect(self._check_ready)
        self.check_button.clicked.connect(lambda: self._run_check(force=True))
        self.save_button.clicked.connect(self.save_recipe)
        self.build_button.clicked.connect(self.build_archive)
        self.use_button.clicked.connect(self.use_in_process)
        state.site_changed.connect(self._site_changed)
        state.selection_changed.connect(self._selection_changed)
        state.segment_store.segment_loaded.connect(lambda _segment: self._schedule_check())

    def _build_layout(self) -> None:
        """The recipe row; the form beside the chart over the check; the buttons, status and command line."""
        top = QHBoxLayout()
        top.addWidget(QLabel("Recipe", self))
        top.addWidget(self.recipe_combo)
        top.addWidget(self.archive_label, 1)
        top.addWidget(QLabel("Local", self))
        top.addWidget(self.local_combo)
        form_area = QScrollArea(self, widgetResizable=True)  # the form is taller than a short screen
        form_area.setWidget(self.form)
        form_area.setMinimumWidth(440)
        lower = QWidget(self)
        check_column = QVBoxLayout(lower)
        check_column.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Member check and preview on the loaded window", self))
        heading.addStretch(1)
        heading.addWidget(self.check_button)
        check_column.addLayout(heading)
        check_column.addWidget(self.check, 1)
        lower.setMinimumHeight(710)  # the check's table, bars, two panels and the weights, scrolled when smaller
        check_area = QScrollArea(self, widgetResizable=True)
        check_area.setWidget(lower)
        right = QSplitter(Qt.Vertical, self)
        right.addWidget(self.chart)
        right.addWidget(check_area)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setSizes([660, 240])  # the chart first: Nador has 154 rows; drag down for a check
        columns = QSplitter(Qt.Horizontal, self)
        columns.addWidget(form_area)
        columns.addWidget(right)
        columns.setStretchFactor(0, 2)
        columns.setStretchFactor(1, 5)
        buttons = QHBoxLayout()
        for button in (self.save_button, self.build_button, self.use_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        command = QHBoxLayout()
        command.addWidget(QLabel("Command line", self))
        command.addWidget(self.command_edit, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(columns, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        layout.addLayout(command)

    # ------------------------------------------------------------ public

    def reload(self) -> None:
        """Take a newly opened survey: its recipes, chart settings and sites; drop the check's arrays.

        The chart's rows are worked out once, after the references, the
        night, the window and the recipe are all set.
        """
        dropped = self._unsaved()
        self._timer.stop()
        self.check.clear()
        self.form.set_flags({})
        self._check_key, self._last_valid, self._locals_rate = None, None, None
        self._notes = {"action": "", "local": "", "check": ""}
        self._updating = True  # the chart and the form are refilled before the rows are worked out
        try:
            self.local_combo.blockSignals(True)
            self.local_combo.clear()  # the local is seeded from the selected site, not the last survey's
            self.local_combo.blockSignals(False)
            self.chart.reload()
            self.form.reload()
            self._load_recipes()
            survey = self.state.survey
            if survey is not None:
                try:
                    settings = stacks.load_chart(survey)
                except (stacks.StacksError, OSError) as exc:
                    settings = {"references": [], "night": stacks.DEFAULT_NIGHT}
                    self._notes["action"] = f"chart settings not read: {exc}"
                self.chart.set_references(settings["references"])
                try:
                    self.chart.set_night(settings["night"])
                except ValueError as exc:
                    self._notes["action"] = str(exc)
            self.recipe_combo.blockSignals(True)
            self.recipe_combo.setCurrentIndex(self.recipe_combo.findData(next(iter(self._recipes), "")))
            self.recipe_combo.blockSignals(False)
        finally:
            self._updating = False
        self._baseline = None
        self._recipe_chosen(self.recipe_combo.currentIndex())
        if dropped:
            self._act(f"unsaved edits to {dropped} dropped (survey reloaded)")

    def select_recipe(self, name: str) -> None:
        """Show a recipe of stacks.yaml in the form and the chart; "" or an unknown name gives a new recipe."""
        self._load_recipes()
        index = self.recipe_combo.findData(name or "")
        self.recipe_combo.setCurrentIndex(index if index >= 0 else self.recipe_combo.findData(""))

    def local(self) -> str | None:
        """Return the local site, or None."""
        return self.local_combo.currentData() or None

    def save_recipe(self):
        """Write the form's recipe to stacks.yaml; every other byte of the file stays.

        Returns:
            Path | None: stacks.yaml, or None with the reason in the status line.
        """
        survey = self.state.survey
        if survey is None:
            return self._act("open a survey first")
        try:
            recipe = self.form.recipe()
        except stacks.StacksError as exc:
            return self._act(f"not saved: {exc}")
        if recipe.name in self.state.raw_sites():
            return self._act(f"not saved: {recipe.name} is a raw data folder of the survey; choose another name")
        try:
            path = stacks.save_recipe(survey, recipe)
        except (stacks.StacksError, OSError) as exc:
            return self._act(f"not saved: {exc}")
        self._load_recipes()
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.setCurrentIndex(self.recipe_combo.findData(recipe.name))
        self.recipe_combo.blockSignals(False)
        self._act(f"saved {recipe.name} to {path} (recipe hash {stacks.recipe_hash(recipe)})")
        self.recipe_saved.emit(recipe.name)
        self._update()
        self._baseline = self._form_state()
        return path

    def build_archive(self) -> list | None:
        """Queue scripts/build_stack.py for the saved time recipe on the Process tab's queue.

        Returns:
            list | None: The argv, or None with the reason in the status line.
        """
        recipe = self._saved_recipe()
        if recipe is None or recipe.engine != "time":
            return self._act("Build archive takes a saved time recipe")
        argv = stacks.build_argv(self.state.python_exe, self.state.script("build_stack.py"),
                                 str(self.state.survey_yaml), recipe.name)
        self.build_requested.emit(argv)
        self._act(f"build_stack.py --recipe {recipe.name} is queued on the Process tab: it waits for Run queue "
                  f"there")
        return argv

    def use_in_process(self) -> str | None:
        """Hand the saved recipe (time, or band with use: base) to the Process tab's picker.

        Returns:
            str | None: The recipe's name, or None with the reason in the status line.
        """
        recipe = self._saved_recipe()
        if recipe is None or (recipe.engine == "band" and recipe.use != "base"):
            return self._act("Use in Process takes a saved time recipe or a saved base band recipe")
        self.use_in_process_requested.emit(recipe.name)
        return recipe.name

    def wait(self) -> None:
        """Block until the chart's and the check's threads return; used on window close."""
        self._timer.stop()
        self.chart.wait()
        self.check.wait()

    # ------------------------------------------------------------ recipes

    def _load_recipes(self) -> None:
        """Read stacks.yaml (parsed once per change) into the recipe combo, keeping the choice."""
        self._recipes, self._errors, self._file_error = {}, {}, None
        if self.state.survey is not None:
            try:
                self._recipes, self._errors = stacks.load_recipes(self.state.survey)
            except (stacks.StacksError, OSError) as exc:
                self._file_error = str(exc)
        current = self.recipe_combo.currentData()
        self.recipe_combo.blockSignals(True)
        try:
            self.recipe_combo.clear()
            for name in self._recipes:
                self.recipe_combo.addItem(name, name)
            for name, error in self._errors.items():
                self.recipe_combo.addItem(f"{name} (unreadable: {error.removeprefix(name + ', ')})", name)
            self.recipe_combo.addItem(NEW, "")
            index = self.recipe_combo.findData(current) if current is not None else -1
            self.recipe_combo.setCurrentIndex(index if index >= 0 else self.recipe_combo.count() - 1)
        finally:
            self.recipe_combo.blockSignals(False)

    def _form_state(self):
        """Return the form's recipe, or ("invalid", the error) when it does not make one."""
        try:
            return self.form.recipe()
        except stacks.StacksError as exc:
            return ("invalid", str(exc))

    def _unsaved(self) -> str | None:
        """Return the name in the form when it holds edits since it was shown or saved, else None."""
        if self._baseline is None or self.state.survey is None:
            return None
        if self._form_state() == self._baseline:
            return None
        return self.form.name_edit.text().strip() or "the new recipe"

    def _recipe_chosen(self, index: int) -> None:
        """Show the chosen recipe in the form; put the chart on its window or the one chosen elsewhere.

        Edits not saved are dropped (stacks.yaml is left unchanged), and the status
        line says so.
        """
        dropped = self._unsaved()
        name = self.recipe_combo.itemData(index) or ""
        recipe = self._recipes.get(name)
        survey = self.state.survey
        taken = set(self._recipes) | set(self._errors)
        if survey is not None:
            taken |= set(survey.site_names()) | set(self.state.raw_sites())
        self._notes["action"] = ""
        self.form.set_recipe(recipe, default_rate=self._rate_of(self.local() or self.state.site), taken=taken)
        if recipe is None and name in self._errors:
            self.form.name_edit.setText(name)  # a save writes over the unreadable block
            self._notes["action"] = f"{name} is unreadable: {self._errors[name]}"
        if self._file_error:
            self._notes["action"] = f"stacks.yaml cannot be used: {self._file_error}"
        self._last_valid = None
        self._fill_locals()
        self._initial_window(recipe)
        self._update()
        self._baseline = self._form_state()
        if dropped:
            self._act(f"unsaved edits to {dropped} dropped" + (f"; {self._notes['action']}"
                                                                 if self._notes["action"] else ""))

    def _saved_recipe(self) -> stacks.Recipe | None:
        """Return the form's recipe when stacks.yaml holds it unchanged, else None."""
        try:
            recipe = self.form.recipe()
        except stacks.StacksError:
            return None
        return recipe if self._recipes.get(recipe.name) == recipe else None

    def _initial_window(self, recipe) -> None:
        """Put the chart on the recipe's window, else the Process bar's chosen one, else the loaded window."""
        if recipe is not None and recipe.start is not None:
            self.chart.set_window(recipe.start, recipe.end)
            return
        process = getattr(self.window(), "process_tab", None)
        bar = getattr(process, "window_bar", None)
        if bar is not None and getattr(bar, "_chosen", False) and bar.window() is not None:
            self.chart.set_window(*bar.window())
            return
        if self.state.selection is not None:
            self.chart.set_window(self.state.selection[1], self.state.selection[2])
        # else the chart keeps its own: the longest stretch at the most candidates

    # -------------------------------------------------------------- local

    def _rate_of(self, site: str | None) -> float | None:
        """Return a survey.yaml site's sample rate, or None."""
        survey = self.state.survey
        if survey is None or not site or site not in survey.site_names():
            return None
        return float(survey.sample_rate_of(site))

    def _fill_locals(self) -> None:
        """List the sites at the form's rate as locals, keeping the local or taking the selected site."""
        survey, rate = self.state.survey, self.form.rate()
        sites = []
        if survey is not None and rate is not None:
            sites = [s for s in survey.site_names() if math.isclose(self._rate_of(s), rate, rel_tol=1e-9)]
        current = self.local() or self.state.site
        self.local_combo.blockSignals(True)
        try:
            self.local_combo.clear()
            self.local_combo.addItem(NO_LOCAL, "")
            for site in sorted(sites):
                self.local_combo.addItem(site, site)
            index = self.local_combo.findData(current) if current in sites else 0
            self.local_combo.setCurrentIndex(max(0, index))
        finally:
            self.local_combo.blockSignals(False)
        self._locals_rate = rate

    def _chart_local(self, recipe) -> str | None:
        """Return the local the chart and the command line get: a band recipe's, at its rate only."""
        local = self.local()
        if recipe is None or recipe.engine != "band" or local is None:
            return None
        rate = self._rate_of(local)
        return local if rate is not None and math.isclose(rate, recipe.sample_rate, rel_tol=1e-9) else None

    def _site_changed(self, site: str) -> None:
        """Follow the site selected on any tab, unless the tab's own bar click selected it."""
        if self._own_click or not site:
            return
        index = self.local_combo.findData(site)
        if index >= 0:
            self._notes["local"] = ""
            self.local_combo.setCurrentIndex(index)
            return
        rate = self._rate_of(site)
        if rate is not None and self.form.rate() is not None:
            self._notes["local"] = (f"{site} is at {rate:g} Hz, the recipe at {self.form.rate():g} Hz: the "
                                    f"local stays {self.local() or 'unset'}")
            self._show_status()

    # ------------------------------------------------------------ updates

    def _form_recipe(self) -> tuple[stacks.Recipe | None, str]:
        """Return (the form's recipe, "") or (None, why it is not one)."""
        try:
            return self.form.recipe(), ""
        except stacks.StacksError as exc:
            return None, str(exc)

    def _update(self) -> None:
        """Recompute the chart's rows for the form's recipe and local, and refresh what depends on them."""
        if self._updating or self.state.survey is None:
            return
        self._updating = True
        try:
            if self.form.rate() != self._locals_rate:
                self._fill_locals()
            recipe, error = self._form_recipe()
            if recipe is not None:
                self._last_valid = recipe
            shown = recipe or self._last_valid
            if shown is not None and self.form.rate() is not None and not math.isclose(
                    shown.sample_rate, self.form.rate(), rel_tol=1e-9):
                shown = None
            self.chart.set_recipe(shown, self._chart_local(shown))
            # a default window (the recipe's, the best stretch, the record) emits nothing: follow it here;
            # none yet (the chart's pass waits for masks.yaml, or no archive is read) leaves the form's
            window = self.chart.window()
            if window is not None and window != self.form.window():
                self.form.set_window(*window, emit=False)
                recipe, error = self._form_recipe()
                if recipe is not None and recipe != shown:
                    self._last_valid = shown = recipe
                    self.chart.set_recipe(shown, self._chart_local(shown))
            self.form.set_rows(self.chart.rows())
            self.form.set_error(error)
            self._show_recipe(recipe, error)
            self._schedule_check()
        finally:
            self._updating = False

    def _chart_window(self, start, end) -> None:
        """A window chosen on the chart (a drag or the fields) goes into the form."""
        self.form.set_window(start, end)

    def _show_recipe(self, recipe, error: str) -> None:
        """Enable the buttons, write the archive status, the command line and the status line."""
        saved = recipe is not None and self._recipes.get(recipe.name) == recipe
        time_recipe = recipe is not None and recipe.engine == "time"
        self.save_button.setEnabled(recipe is not None and self.state.survey is not None and not self._file_error)
        self.save_button.setToolTip(error or "Write this recipe's block of stacks.yaml; every other line stays")
        self.build_button.setEnabled(time_recipe and saved)
        if recipe is None:
            tip = error
        elif not time_recipe:
            tip = "a band recipe is formed inside each process_intersite run: there is no archive to build"
        else:
            tip = BUILD_TIP.format(name=recipe.name) if saved else SAVE_FIRST
        self.build_button.setToolTip(tip)
        usable = recipe is not None and (time_recipe or recipe.use == "base")
        self.use_button.setEnabled(usable and saved)
        if recipe is not None and not usable:
            tip = REFERENCE_TIP
        elif recipe is not None and not saved:
            tip = SAVE_FIRST
        else:
            tip = error or "Choose this recipe in the Process tab's picker and put its window on the bar"
        self.use_button.setToolTip(tip)
        self.archive_label.setText(self._archive_text(recipe, saved))
        self.command_edit.setText(self._command(recipe))
        local = self.local()
        self._notes["local"] = ""
        if time_recipe and local is not None and local in recipe.members:
            self._notes["local"] = (f"{recipe.name} holds {local}: as {local}'s remote it would share "
                                    f"{local}'s noise")
        self._show_status()

    def _archive_text(self, recipe, saved: bool) -> str:
        """Say whether a time recipe's archive exists (a stat); a band recipe has none."""
        if recipe is None:
            return ""
        tail = "" if saved else "  (not saved)"
        if recipe.engine == "band":
            return f"band stack: formed inside each process_intersite run, nothing saved{tail}"
        path = self.state.archive_path(recipe.name)
        try:
            size = path.stat().st_size
        except (OSError, AttributeError):
            return f"no archive {recipe.name}.h5 yet: Build archive{tail}"
        return f"archive {path.name} present ({size / 1e6:.1f} MB){tail}"

    def _command(self, recipe) -> str:
        """Return the recipe's command line; <...> marks a site the tab does not hold."""
        if recipe is None or self.state.survey_yaml is None:
            return ""
        survey_yaml = str(self.state.survey_yaml)
        if recipe.engine == "time":
            argv = stacks.build_argv("python", "scripts/build_stack.py", survey_yaml, recipe.name)
        else:
            base = recipe.use == "base"
            argv = stacks.intersite_argv(
                "python", "scripts/process_intersite.py", survey_yaml, self._chart_local(recipe) or "<LOCAL>",
                stacks.KIND_OF_BASE[recipe.field] if base else "<telluric|magnetic>", [recipe.name],
                base=None if base else "<BASE>", remote="<REMOTE>" if base else None,
                no_filters=not recipe.use_filters)
        return " ".join(_quote(a) for a in argv)

    def _act(self, text: str) -> None:
        """Say what a button did, or why it did not; returns None for the button's return value."""
        self._notes["action"] = text
        self._show_status()
        return None

    def _show_status(self) -> None:
        """Write the last action, the local's warning and the check's rate note, warnings in amber."""
        parts = [text for text in (self._notes["action"], self._notes["local"], self._notes["check"]) if text]
        self.status_label.setText(" | ".join(parts))
        warn = bool(self._notes["local"] or self._notes["check"])
        self.status_label.setStyleSheet(f"color: {WARN_COLOUR}" if warn else "")

    def _save_view(self, references: list, night: str) -> None:
        """Write the chart's references and night to the chart block of stacks.yaml."""
        if self.state.survey is None:
            return
        try:
            path = stacks.save_chart(self.state.survey, references, night)
        except (stacks.StacksError, OSError) as exc:
            self._act(f"view not saved: {exc}")
            return
        self._act(f"saved the chart's references and night to {path}")

    # -------------------------------------------------------------- click

    def _bar_clicked(self, site: str, when) -> None:
        """Select the tree window of `site` holding `when` and show it on the Time Series tab."""
        row = next((r for r in self.chart.rows() if r.site == site), None)
        window = None
        if row is not None and row.runs:
            window = availability_model.tree_window_at(row.runs["all"], row.rate, int(when.value))
        if window is None:
            self._act(f"no Time Series window of {site} holds {when:%Y-%m-%d %H:%M} UTC")
            return
        self._own_click = True
        try:
            self.state.set_selection(site, *window)
            self.state.goto_time.emit(when)
        finally:
            self._own_click = False

    # -------------------------------------------------------------- check

    def _check_request(self) -> tuple[tuple | None, str]:
        """Return (MemberCheck.request's arguments, "") for the recipe on the loaded window, or (None, why not)."""
        recipe = self._last_valid
        segment = self.state.segment_store.segment
        if recipe is None:
            return None, "no recipe to check"
        if segment is None:
            return None, NO_WINDOW
        if not math.isclose(float(segment.sample_rate), recipe.sample_rate, rel_tol=1e-9):
            return None, (f"the loaded station is at {float(segment.sample_rate):g} Hz, the recipe at "
                          f"{recipe.sample_rate:g} Hz: no check")
        rows = sorted((r for r in self.chart.rows() if r.member), key=lambda r: -(r.overlap_h or 0.0))
        if not rows:
            return None, "the recipe has no members over the window"
        span = stackcheck.check_span(segment.t0, segment.end, recipe.sample_rate)
        method = stacks.METHODS[recipe.method]
        return (tuple(r.site for r in rows), recipe.roles, span, method.engine, method.stack, method.weighting,
                recipe.reject_factor, recipe.min_members, recipe.use_filters), ""

    def _schedule_check(self) -> None:
        """Check again 500 ms after what the check reads or computes has changed, while the tab is shown."""
        if not self.isVisible():
            return
        args, why = self._check_request()
        if args is None:
            self._timer.stop()
            self._show_no_check(why)
            return
        if args != self._check_key:
            self._timer.start()

    def _show_no_check(self, why: str) -> None:
        """Say why there is no check; drop the arrays of a check that no longer applies."""
        if self._check_key is not None or self.check.kept_sites():
            self.check.clear()
            self.form.set_flags({})
        self._check_key = None
        self.check.status.setText(why)
        self._notes["check"] = why if " Hz: no check" in why else ""
        self._show_status()

    def _run_check(self, force: bool = False) -> None:
        """Request the member check, unless it is the request already made (Check repeats it).

        Without a Check click (`force`), members are read only while the
        set stays under `AUTO_CHECK_SAMPLES`; arrays already held are always
        recomputed from.
        """
        if not self.isVisible():
            return
        args, why = self._check_request()
        if args is None:
            self._show_no_check(why)
            return
        if args == self._check_key and not force:
            return
        members, roles, span = args[0], args[1], args[2]
        if not force and self.check.missing(members, roles, span, args[-1]):
            n = min(len(members), stackcheck.MAX_CHECK_MEMBERS)
            samples = n * (span[1] - span[0]).total_seconds() * self._last_valid.sample_rate
            if samples > AUTO_CHECK_SAMPLES:
                self.check.status.setText(
                    f"{n} members over {(span[1] - span[0]).total_seconds() / 60:.0f} min at "
                    f"{self._last_valid.sample_rate:g} Hz: {samples / 1e6:.0f} M samples per channel to read, "
                    f"more than the {AUTO_CHECK_SAMPLES / 1e6:.0f} M read without asking: press Check")
                return
        self._check_key = args
        self._notes["check"] = ""
        self._show_status()
        members, *rest = args
        self.check.request(list(members), *rest)

    def _check_ready(self, result) -> None:
        """Put the check's flags in the member list."""
        flags: dict[str, list[str]] = {}
        for (site, role), marks in result.flags.items():
            for mark in marks:
                flags.setdefault(site, []).append(f"{role} {mark}")
        self.form.set_flags({site: ", ".join(marks) for site, marks in flags.items()})

    def _selection_changed(self, selection) -> None:
        """A cleared selection drops the check; a new one is checked once its window loads."""
        if selection is None:
            self._timer.stop()
            self._show_no_check(NO_WINDOW)

    def showEvent(self, event) -> None:
        """Check the members of the loaded window once shown."""
        super().showEvent(event)
        self._schedule_check()

    def hideEvent(self, event) -> None:
        """Drop the members' arrays: memory limits the batches that run beside the GUI."""
        super().hideEvent(event)
        self._timer.stop()
        self.check.clear()
        self.form.set_flags({})
        self._check_key = None
