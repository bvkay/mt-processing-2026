"""Filter Data tab: declare the selected site's entry in `<survey>/filters.yaml`.

This tab edits one file and runs nothing. `filters.yaml` maps a site to an
ordered list of single-key dicts; `bbmt.ingest.ingest_site` applies that list
**at ingest**, on the raw counts, in the order declared, and writes what it did
into the archive's run comments. The kinds are documented in `bbmt.noise`
(notch, cp) and `bbmt.ingest._replace_channels` (replace).

    A07:
      - replace: {hx: A06}      # borrow A06's hx, with A06's own calibration
      - notch: {f0: 50.0, harmonics: 9, q: 30.0, passes: 2}
      - cp: {period_s: 12.0, window_minutes: 10}

Saving rewrites the whole file with `yaml.safe_dump(sort_keys=False)`, leaving
every other site's entry exactly as it was and dropping this site's key when
its list is empty, then reopens the survey so the Metadata tab's "filters"
column and every other tab see the change. Because the archive is built at
ingest, an existing `<workspace>/mth5/<site>.h5` predates any edit made here --
hence the note and the "Delete archive" button under the form.
"""

from __future__ import annotations

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bbmt_gui.filter_forms import CpForm, NotchForm, ReplaceForm, summarise

RULE = (
    "Nothing here is automatic. A student sees the problem in the QC figures "
    "(scripts/site_qc.py: the 50 Hz line in the spectrogram, the 12 s square "
    "wave in the overview, the comb in the PSD) and declares a filter list for "
    "that site in <survey>/filters.yaml; ingest_site applies the list in the "
    "declared order on the raw counts and records it in the archive.\n"
    "Order matters (Ben, 2026-09-22): mains first, so the cathodic-protection "
    "edges are timed on a cleaner series.\n"
    "    -- bbmt.noise, module docstring"
)
ARCHIVE_NOTE = (
    "The archive was built before this change; filters are applied at ingest, "
    "so delete it and the next Process run re-ingests"
)


class FiltersTab(QWidget):
    """The selected site's ordered filter list, edited and saved to YAML."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.entries: list[dict] = []

        self.site_label = QLabel("no site selected", self)
        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._row_changed)

        self.add_button = QPushButton("Add", self)
        menu = QMenu(self.add_button)
        for kind in ("replace", "notch", "cp"):
            menu.addAction(kind, lambda k=kind: self.add_filter(k))
        self.add_button.setMenu(menu)
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self.remove_filter)
        self.up_button = QPushButton("Move up", self)
        self.up_button.clicked.connect(lambda: self.move_filter(-1))
        self.down_button = QPushButton("Move down", self)
        self.down_button.clicked.connect(lambda: self.move_filter(+1))

        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Filters, applied in this order", self))
        left_layout.addWidget(self.list, 1)
        left_layout.addLayout(buttons)

        self.forms = {f.kind: f for f in (ReplaceForm(self), NotchForm(self), CpForm(self))}
        self.stack = QStackedWidget(self)
        for form in self.forms.values():
            form.changed.connect(self._form_changed)
            self.stack.addWidget(form)
        self.empty = QLabel("Add a filter, or pick one from the list to edit it.", self)
        self.stack.addWidget(self.empty)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(160)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)

        self.save_button = QPushButton("Save filters.yaml", self)
        self.save_button.clicked.connect(self.save)
        self.archive_label = QLabel("", self)
        self.archive_label.setWordWrap(True)
        self.delete_button = QPushButton("Delete archive", self)
        self.delete_button.clicked.connect(self._delete_archive)

        archive_row = QHBoxLayout()
        archive_row.addWidget(self.archive_label, 1)
        archive_row.addWidget(self.delete_button)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.stack, 1)
        right_layout.addLayout(archive_row)
        right_layout.addWidget(QLabel("This site's entry as it will be written", self))
        right_layout.addWidget(self.preview)
        right_layout.addWidget(self.save_button)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        rule = QLabel(RULE, self)
        rule.setWordWrap(True)
        rule.setFrameShape(QFrame.StyledPanel)

        header = QHBoxLayout()
        header.addWidget(QLabel("Site", self))
        header.addWidget(self.site_label, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(rule)
        layout.addWidget(splitter, 1)

        self.state.site_changed.connect(lambda _n: self.reload())
        self.state.runner.queue_changed.connect(self._update_archive_note)

    # ----------------------------------------------------------- the site

    def reload(self) -> None:
        """Read the site's declared list out of `Survey.site()` and show it."""
        site = self.state.site
        self.site_label.setText(site or "no site selected (pick one on Metadata)")
        self.entries = []
        if site and self.state.survey is not None:
            declared = self.state.survey.site(site).filters or []
            self.entries = [dict(entry) for entry in declared]
        donors = [s for s in sorted(self.state.raw_sites()) if s != site]
        self.forms["replace"].set_donors(donors)
        self._refill_list(0 if self.entries else -1)
        self._update_archive_note()

    def _refill_list(self, row: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self.entries:
            self.list.addItem(summarise(entry))
        self.list.blockSignals(False)
        self.list.setCurrentRow(min(row, len(self.entries) - 1))
        self._row_changed(self.list.currentRow())

    # ------------------------------------------------------- list editing

    def _row_changed(self, row: int) -> None:
        if not (0 <= row < len(self.entries)):
            self.stack.setCurrentWidget(self.empty)
            self._update_preview()
            return
        kind, opts = next(iter(self.entries[row].items()))
        form = self.forms.get(kind)
        if form is None:
            self.stack.setCurrentWidget(self.empty)
        else:
            form.load(opts or {})
            self.stack.setCurrentWidget(form)
        self._update_preview()

    def add_filter(self, kind: str) -> None:
        if not self.state.site:
            QMessageBox.warning(self, "No site", "Pick a site on the Metadata tab first.")
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
        row = self.list.currentRow()
        new = row + step
        if 0 <= row < len(self.entries) and 0 <= new < len(self.entries):
            self.entries[row], self.entries[new] = self.entries[new], self.entries[row]
            self._refill_list(new)

    def _form_changed(self) -> None:
        row = self.list.currentRow()
        form = self.stack.currentWidget()
        if 0 <= row < len(self.entries) and form in self.forms.values():
            self.entries[row] = form.spec()
            self.list.blockSignals(True)
            self.list.item(row).setText(summarise(self.entries[row]))
            self.list.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        site = self.state.site or "<site>"
        if not self.entries:
            self.preview.setPlainText(f"# {site} has no declared filters (its key is removed)")
            return
        self.preview.setPlainText(
            yaml.safe_dump({site: self.entries}, sort_keys=False, allow_unicode=True)
        )

    # ----------------------------------------------------------- the file

    def save(self) -> bool:
        """Rewrite `filters.yaml`, then reopen the survey so every tab sees it."""
        path = self.state.filters_yaml()
        site = self.state.site
        if path is None or not site:
            QMessageBox.warning(self, "No site", "Open a survey and pick a site first.")
            return False
        data = {}
        header = ""
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
        if self.entries:
            data[site] = [dict(entry) for entry in self.entries]
        else:
            data.pop(site, None)
        path.write_text(
            header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.state.open_survey(self.state.survey_yaml)  # reload_tabs follows
        self.state.set_site(site)
        return True

    # -------------------------------------------------------- the archive

    def _update_archive_note(self) -> None:
        site = self.state.site
        has = bool(site) and self.state.has_archive(site)
        self.archive_label.setText(f"{ARCHIVE_NOTE}: {self.state.archive_path(site)}" if has else "")
        self.delete_button.setEnabled(has and not self.state.runner.running)
        self.delete_button.setToolTip(
            "a job is running - the archive may be open" if self.state.runner.running else ""
        )

    def _delete_archive(self) -> None:
        site = self.state.site
        path = self.state.archive_path(site) if site else None
        if path is None or not path.exists():
            return
        answer = QMessageBox.question(
            self, "Delete archive",
            f"Delete {path}?\n\nThe next Process run re-ingests {site} with the "
            f"filters as declared here. Nothing else is removed.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.critical(self, "Could not delete", f"{path}\n\n{exc}")
            return
        self.state.survey_changed.emit()  # archive columns and lists everywhere
