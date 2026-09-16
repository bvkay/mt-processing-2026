"""Filter Data tab: try a site's filter list on a loaded window, then declare it in `<survey>/filters.yaml`.

For some datasets this is where a student spends most of their time
cleaning it before processing. Top to bottom:

1. **The window** -- a site combo and a window combo (`window_chooser`):
   choosing a window loads it (`State.set_selection`, as a click in the
   Time Series tree does), and the label beside them names what is loaded.
2. **The list** of the site's filters, applied in this order, with Add (50
   Hz + harmonics, high-pass, low-pass, cathodic protection stack, replace
   magnetics from another site), Remove, Move up, Move down, "Copy to
   sites..." (enabled with a non-empty list; `mtproc_gui.copy_filters`, for a
   survey where many sites share one declaration) and the rule under them;
   the form of the selected entry (`filter_forms`); and a narrow pane with
   the site's entry as it will be written (collapsible), Save and the
   archive note.
3. **The preview** (`filter_preview`): whenever the list or a form value
   changes (debounced, `DEBOUNCE_MS`), the loaded window goes through
   `mtproc.noise.apply_filters_arrays` off the GUI thread and is drawn raw
   (light grey) behind filtered (the channel colour) -- Bx, By, Ex, Ey on one
   locked x axis (Before / After / Both), and the Spectra tab's two pair
   panels, raw dashed -- with a status line of what was applied and how long
   it took. A channel unticked under "Show" leaves both views.

Saving rewrites the whole file with `yaml.safe_dump(sort_keys=False)`, leaving
every other site's entry as it was and dropping this site's key when its list
is empty, then reopens the survey (and reloads the window that was loaded) so
every tab sees the change. Filters are applied to a **filtered variant** of
the site's raw archive, built on demand (`mtproc.ingest.processing_archive`,
`build_variant`), never to the raw recording itself: the note says whether
that variant is ready or still to be built for the list as saved, and
"Delete archive" (asked first, disabled while a job runs) removes the site's
variant file(s) only -- never `<site>.h5` -- and tells the Time Series tree
(`State.archive_changed`) to look again, though nothing there changes; the
next run that wants filters rebuilds the variant from the raw archive.
"""

from __future__ import annotations

import yaml
from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from mtproc_gui import theme
from mtproc.ingest import variant_ready
from mtproc.survey import INSTRUMENTS
from mtproc_gui.copy_filters import CopyFiltersDialog
from mtproc_gui.filter_forms import CHANNELS, LABELS, make_forms, summarise
from mtproc_gui.filter_preview import FilterPreview
from mtproc_gui.filter_views import PreviewPane
from mtproc_gui.window_chooser import WindowChooser

ARCHIVE_NOTE = "filtered archive for this list:"
NO_WINDOW = "load a window (above, or on the Time Series tab) to preview the filters"
DEBOUNCE_MS = 500
ADD_ORDER = ("notch", "mains", "hp", "lp", "cp", "burst", "flip", "replace")


def _write_filters(path, updates: dict) -> None:
    """Rewrite `filters.yaml`: each site in `updates` set to its list, or dropped when the list is empty.

    Used by `save()` (one site) and `_copy_to_sites()` (several, in one
    write); every other site's entry, and the file's leading comment block,
    are left as they were.
    """
    data, header = {}, ""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        # keep the file's leading comment block; comments further down are
        # lost, which is what safe_dump costs
        lines = text.splitlines()
        keep = 0
        while keep < len(lines) and (not lines[keep].strip() or lines[keep].lstrip().startswith("#")):
            keep += 1
        header = "\n".join(lines[:keep]) + ("\n" if keep else "")
    for site, entries in updates.items():
        if entries:
            data[site] = [dict(entry) for entry in entries]
        else:
            data.pop(site, None)
    path.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


class FiltersTab(QWidget):
    """The site's ordered filter list, previewed on the loaded window, saved to filters.yaml."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.entries: list[dict] = []
        self._stale = False  # the preview no longer shows the list: run it when the tab is seen

        self.chooser = WindowChooser(state, self)
        self.window_label = QLabel(NO_WINDOW, self, wordWrap=True)
        self.window_label.setStyleSheet("font-weight: bold")
        top = QHBoxLayout()
        top.addWidget(self.chooser)
        top.addWidget(self.window_label, 1)

        self.site_label = QLabel("no site selected", self)
        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._row_changed)
        self.add_button = QPushButton("Add", self)
        menu = QMenu(self.add_button)
        for kind in ADD_ORDER:
            menu.addAction(LABELS[kind], lambda k=kind: self.add_filter(k))
        self.add_button.setMenu(menu)
        self.remove_button = QPushButton("Remove", self, clicked=self.remove_filter)
        self.up_button = QPushButton("Move up", self, clicked=lambda: self.move_filter(-1))
        self.down_button = QPushButton("Move down", self, clicked=lambda: self.move_filter(+1))
        self.copy_button = QPushButton("Copy to sites...", self, clicked=self._copy_to_sites)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button, self.copy_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.site_label)
        left_layout.addWidget(self.list, 1)
        left_layout.addLayout(buttons)

        self.forms = make_forms(self)
        self.stack = QStackedWidget(self)
        for form in self.forms.values():
            form.changed.connect(self._form_changed)
            self.stack.addWidget(form)
        self.empty = QLabel("Add a filter, or pick one from the list to edit it.", self)
        self.stack.addWidget(self.empty)

        self.yaml_button = QToolButton(self, text="the site's entry as it will be written", checkable=True,
                                       checked=True)
        self.yaml_view = QPlainTextEdit(self, readOnly=True, lineWrapMode=QPlainTextEdit.NoWrap)
        self.yaml_button.toggled.connect(self.yaml_view.setVisible)
        self.save_button = QPushButton("Save filters.yaml", self, clicked=self.save)
        self.archive_label = QLabel("", self, wordWrap=True)
        self.archive_label.setStyleSheet(f"color: {theme.NOTICE_COLOUR}")
        self.delete_button = QPushButton("Delete archive", self, clicked=self._delete_archive)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.yaml_button)
        right_layout.addWidget(self.yaml_view, 1)
        for widget in (self.save_button, self.archive_label, self.delete_button):
            right_layout.addWidget(widget)

        controls = QSplitter(Qt.Horizontal, self)
        for widget, stretch in ((left, 2), (self.stack, 3), (right, 2)):
            controls.addWidget(widget)
            controls.setStretchFactor(controls.count() - 1, stretch)

        self.pane = PreviewPane(self)  # Before/After/Both, Show, the status line, the two views
        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(controls)
        splitter.addWidget(self.pane)
        splitter.setSizes([240, 600])
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

        self.preview = FilterPreview(state, self)
        self.preview.started.connect(self.pane.status_label.setText)
        self.preview.ready.connect(self._show)
        self.preview.failed.connect(lambda message: self.pane.status_label.setText(f"preview failed: {message}"))
        self.timer = QTimer(self, singleShot=True, interval=DEBOUNCE_MS, timeout=self.run_preview)
        self.state.site_changed.connect(lambda _n: self._load_site())
        self.state.selection_changed.connect(lambda _s: self._window_changed())
        self.state.segment_store.segment_loaded.connect(lambda _seg: self._window_changed())
        self.state.runner.queue_changed.connect(self._update_archive_note)

    # ----------------------------------------------------------- the site

    def reload(self) -> None:
        """A survey was opened: the chooser's sites, the site's list, no preview yet."""
        self.chooser.reload()
        self._load_site()

    def _load_site(self) -> None:
        """Read the site's declared list out of `Survey.site()` and show it."""
        site = self.state.site
        self.site_label.setText(f"Filters for {site}, applied in this order" if site
                                else "no site selected (pick one above or on Metadata)")
        self.entries, names = [], CHANNELS
        if site and self.state.survey is not None:
            cfg, survey = self.state.survey.site(site), self.state.survey
            self.entries = [dict(entry) for entry in cfg.filters or []]
            names = cfg.channels or INSTRUMENTS[survey.instrument_of(site)]["channels"]  # the forms' boxes
        for form in self.forms.values():
            form.set_channels(names)
        self.forms["replace"].set_donors([s for s in sorted(self.state.raw_sites()) if s != site])
        self._refill_list(0 if self.entries else -1)
        self._update_archive_note()
        self._window_changed()

    def _refill_list(self, row: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self.entries:
            self.list.addItem(summarise(entry))
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(row, len(self.entries) - 1))
        self._row_changed(self.list.currentRow())
        self._changed()

    # ------------------------------------------------------- list editing

    def _row_changed(self, row: int) -> None:
        kind, opts = next(iter(self.entries[row].items())) if 0 <= row < len(self.entries) else (None, None)
        form = self.forms.get(kind)
        if form is not None:
            form.load(opts or {})
        self.stack.setCurrentWidget(form or self.empty)

    def add_filter(self, kind: str) -> None:
        if not self.state.site:
            QMessageBox.warning(self, "No site", "Pick a site first (above, or on the Metadata tab).")
            return
        form = self.forms[kind]
        form.load({})
        self.entries.append(form.spec())
        self._refill_list(len(self.entries) - 1)

    def remove_filter(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.entries):
            self.entries.pop(row)
            self._refill_list(max(row - 1, 0))

    def move_filter(self, step: int) -> None:
        row, new = self.list.currentRow(), self.list.currentRow() + step
        if 0 <= row < len(self.entries) and 0 <= new < len(self.entries):
            self.entries[row], self.entries[new] = self.entries[new], self.entries[row]
            self._refill_list(new)

    def _form_changed(self) -> None:
        row, form = self.list.currentRow(), self.stack.currentWidget()
        if 0 <= row < len(self.entries) and form in self.forms.values():
            self.entries[row] = form.spec()
            self.list.item(row).setText(summarise(self.entries[row]))
        self._changed()

    def _changed(self) -> None:
        """The list changed: the YAML now, the preview after the debounce."""
        site = self.state.site or "<site>"
        self.yaml_view.setPlainText(
            yaml.safe_dump({site: self.entries}, sort_keys=False, allow_unicode=True) if self.entries
            else f"# {site} has no declared filters (its key is removed)")
        self.copy_button.setEnabled(bool(self.entries))
        self._stale = True
        if self.isVisible():
            self.timer.start()

    # ------------------------------------------------------------ preview

    def window(self):
        """The loaded `Segment` when it is the selection and the site's own, else None."""
        seg, selection = self.state.segment_store.segment, self.state.selection
        if seg is None or selection is None or seg.station != selection[0] or seg.station != self.state.site:
            return None
        return seg if abs((seg.t0 - selection[1]).total_seconds()) <= 0.5 / seg.sample_rate else None

    def _window_changed(self) -> None:
        seg, site, selection = self.window(), self.state.site, self.state.selection
        if seg is not None:
            self.window_label.setText(f"{seg.station}: {seg.t0:%Y-%m-%d %H:%M:%S} to {seg.end:%H:%M:%S} UTC "
                                      f"({seg.duration_s / 3600:.2f} h at {seg.sample_rate:g} Hz)")
        elif selection is not None and selection[0] == site:
            self.window_label.setText(f"loading {site} {selection[1]:%Y-%m-%d %H:%M} UTC ...")
        elif site and not self.state.has_archive(site):
            self.window_label.setText(f"{site} has no archive: Build MTH5 on the Time Series tab to preview")
        else:
            self.window_label.setText(NO_WINDOW if selection is None else
                                      f"the loaded window is {selection[0]}'s: choose one of {site}'s above")
        if seg is None or seg is not self.pane.series.segment:
            self.preview.clear()
            self.pane.clear()
        self._stale = True
        if seg is not None and self.isVisible():
            self.run_preview()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.run_preview()

    def run_preview(self) -> None:
        """The list on the loaded window, now (the debounce's end)."""
        self.timer.stop()
        seg = self.window()
        if seg is not None:
            self._stale = False
            self.preview.request(seg, self.entries)

    def _show(self, result) -> None:
        if result.segment is self.window():  # not a window loaded since the request
            self.pane.show_result(result)

    # ----------------------------------------------------------- the file

    def save(self) -> bool:
        """Rewrite `filters.yaml`, then reopen the survey so every tab sees it."""
        path, site, selection = self.state.filters_yaml(), self.state.site, self.state.selection
        if path is None or not site:
            QMessageBox.warning(self, "No site", "Open a survey and pick a site first.")
            return False
        _write_filters(path, {site: self.entries})
        self._reopen(site, selection)
        return True

    def _reopen(self, site: str, selection) -> None:
        """Reload the survey so every tab sees the file, back on `site` (and `selection`, if any)."""
        self.state.open_survey(self.state.survey_yaml)  # reload_tabs follows
        self.state.set_site(site)
        if selection is not None:
            self.state.set_selection(*selection)  # the window comes back; the preview follows

    def _copy_to_sites(self) -> None:
        """"Copy to sites...": put this site's filter list onto sites the student ticks.

        `_reopen()` re-reads every site from the file it just wrote,
        including this one -- fine when it was this site's own edit that was
        just saved (`save()`), wrong here: this site's list may not be saved
        at all. So its entries are kept and put straight back after the
        reopen, leaving this site's own list and preview exactly as they
        were.
        """
        site, survey = self.state.site, self.state.survey
        path, selection = self.state.filters_yaml(), self.state.selection
        if not site or survey is None or path is None or not self.entries:
            return
        others = {s: (survey.site(s).filters or []) for s in self.state.all_sites() if s != site}
        dialog = CopyFiltersDialog(site, self.entries, others, self)
        accepted = dialog.exec() == QDialog.Accepted
        dialog.deleteLater()  # a closed dialog must not linger as a child (the next one is found by type)
        if not accepted:
            return
        targets = dialog.selected_sites()
        if not targets:
            return  # OK with nothing ticked does nothing
        source = [dict(entry) for entry in self.entries]
        if dialog.append():
            updates = {t: others[t] + source for t in targets}
        else:
            updates = {t: source for t in targets}
        _write_filters(path, updates)
        row = self.list.currentRow()
        self._reopen(site, selection)
        self.entries = source
        self._refill_list(row)
        logger.info(f"copied {site}'s filters to {len(targets)} sites: {', '.join(targets)}")

    # -------------------------------------------------------- the archive

    def _variant_paths(self, site: str | None) -> list:
        """The site's filtered variant file(s) on disk (`<site>_f*.h5`, normally
        at most one -- `mtproc.ingest.build_variant` prunes the rest)."""
        survey = self.state.survey
        if not site or survey is None:
            return []
        return sorted((survey.workspace / "mth5").glob(f"{site}_f*.h5"))

    def _update_archive_note(self) -> None:
        site, survey = self.state.site, self.state.survey
        variants = self._variant_paths(site)
        if site and survey is not None and survey.site(site).filters:
            state = "ready" if variant_ready(survey, site) else "not built yet (built when processing starts)"
            self.archive_label.setText(f"{ARCHIVE_NOTE} {state}")
        else:
            self.archive_label.setText("")
        self.delete_button.setVisible(bool(variants))
        self.delete_button.setEnabled(bool(variants) and not self.state.runner.running)
        self.delete_button.setToolTip("a job is running - the archive may be open" if self.state.runner.running
                                      else "")

    def _delete_archive(self) -> None:
        site = self.state.site
        paths = self._variant_paths(site)
        if not paths or self.state.runner.running:
            return
        names = ", ".join(p.name for p in paths)
        answer = QMessageBox.question(
            self, "Delete filtered archive",
            f"Delete {names}?\n\nThe raw archive ({site}.h5) is never touched. The next run that wants "
            f"filters rebuilds this from it, with the list as saved in filters.yaml (save first).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            for path in paths:
                path.unlink()
        except OSError as exc:
            QMessageBox.critical(self, "Could not delete", f"{names}\n\n{exc}")
            return
        self._update_archive_note()
        self.state.archive_changed.emit(site)  # the tree's row and the chooser look again

    def wait(self) -> None:
        """Let the preview worker and the chooser's read finish (the window is closing)."""
        self.preview.wait()
        self.chooser.wait_for_read()
