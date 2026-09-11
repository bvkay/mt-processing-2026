"""View EDIs tab: mtpy-v2 transfer function plots over a checkable tree.

Two groups in one tree. The first is every `*.edi` in `<workspace>/tf` -- what
`scripts/process_rr.py` wrote -- and the second is the lemimt references
declared in `<survey>/reference_edis.yaml` (site -> {edi, distance_km}), which
live on the field drive and are only ever read. Ticked rows are overlaid on
one live matplotlib canvas (`FigureCanvasQTAgg` + `NavigationToolbar2QT`), and
everything mtpy-specific is in `bbmt_gui.tf_plot`: `PlotMTResponse` for a
single station, `PlotMultipleResponses(plot_style="compare")` for an overlay,
xy and yx (`plot_num=1`), mtpy's own error bars. The owner's reason for
handing the picture to mtpy (2026-09-22): "I think we almost need to use
mtpy-v2 for the edi viewer here so we get decent transfer functions plotted
properly, though I do like being able to stack various TFs over the top of
each other."

**Quick view** (on by default) is the other half of that sentence: "it would
be really cool to be able to use the keyboard down arrow for a sort of quick
view to go through them quick". The row under the cursor -- moved with the
arrow keys or clicked -- is drawn on its own *plus* whatever is ticked, so a
student steps through a survey one EDI at a time against a fixed reference.
Redraws are debounced by a single-shot 150 ms timer, so holding the key down
queues one draw, not one per row. With quick view off only the ticked rows
are drawn.

The **Plot** group picks what mtpy draws: apparent resistivity and phase, the
same plus a row of phase tensor ellipses per station, or the same plus the
tipper. The tipper button is disabled on a survey whose sites declare no hz
channel -- the aurora EDIs still carry a tipper, estimated from an open Bz
input, and it is nonsense. Induction arrows for long-period data are the
reason to keep the button there at all.

Nothing is produced here: to make a new EDI, use the Process tab.
"""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bbmt_gui import tf_plot

# holding the down arrow must not queue one mtpy draw per row
DEBOUNCE_MS = 150
NO_HZ_TIP = "no hz sensor on this survey"
EMPTY_HINT = ("tick a transfer function on the left, or switch Quick view on\n"
              "and step through the list with the arrow keys")


class EdiTab(QWidget):
    """A checkable tree of EDIs over one mtpy canvas."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._checked: set[str] = set()
        self.last_seconds: float | None = None
        self.draws = 0  # how many times mtpy has drawn: the debounce is testable

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["transfer function"])
        self.tree.setMinimumWidth(280)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemClicked.connect(self._item_clicked)

        self.quick_check = QCheckBox("Quick view (arrow keys step through the list)", self)
        self.quick_check.setChecked(True)
        self.quick_check.setToolTip(
            "Draw the row under the cursor on its own, with any ticked rows under it"
        )
        self.quick_check.toggled.connect(lambda _on: self.schedule())

        self.rho_radio = QRadioButton("rho and phase", self)
        self.pt_radio = QRadioButton("plus phase tensor", self)
        self.tipper_radio = QRadioButton("plus tipper", self)
        self.rho_radio.setChecked(True)
        plot_box = QGroupBox("Plot", self)
        plot_layout = QVBoxLayout(plot_box)
        for radio in (self.rho_radio, self.pt_radio, self.tipper_radio):
            plot_layout.addWidget(radio)
            radio.toggled.connect(self._choice_toggled)

        self.refresh_button = QPushButton("Refresh list", self)
        self.refresh_button.clicked.connect(self.reload)
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)

        self.figure = Figure(figsize=(9.0, 7.0), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.redraw)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.tree, 1)
        left_layout.addWidget(self.quick_check)
        left_layout.addWidget(plot_box)
        left_layout.addWidget(self.refresh_button)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas, 1)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        header = QHBoxLayout()
        header.addWidget(QLabel("Tick to overlay; the cursor row draws on its own", self))
        header.addWidget(self.status_label, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self.state.runner.job_finished.connect(self._job_finished)
        self._update_tipper_button()
        self.redraw()

    # ------------------------------------------------------------ the lists

    def reload(self) -> None:
        """Re-list both groups, keeping whatever is ticked."""
        self.tree.blockSignals(True)
        self.tree.clear()
        tf_dir = self.state.tf_dir()
        aurora = QTreeWidgetItem(self.tree, [f"aurora ({tf_dir})" if tf_dir else "aurora"])
        aurora.setFlags(Qt.ItemIsEnabled)
        if tf_dir is not None and tf_dir.exists():
            for path in sorted(tf_dir.glob("*.edi")):
                self._add_leaf(aurora, path.name, path)
        lemimt = QTreeWidgetItem(self.tree, ["lemimt reference"])
        lemimt.setFlags(Qt.ItemIsEnabled)
        for site, entry in self._references().items():
            path = Path(str(entry.get("edi", "")))
            distance = entry.get("distance_km")
            label = f"{site} (lemimt)" + (f"  {float(distance):g} km" if distance is not None else "")
            self._add_leaf(lemimt, label, path)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._update_tipper_button()
        self.schedule()

    def _references(self) -> dict:
        path = self.state.reference_edis_yaml()
        if path is None or not path.exists():
            return {}
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _add_leaf(self, parent: QTreeWidgetItem, label: str, path: Path) -> None:
        item = QTreeWidgetItem(parent, [label])
        item.setData(0, Qt.UserRole, str(path))
        # selectable as well as checkable: the arrow keys move the *current*
        # row, which is what quick view draws
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        item.setCheckState(0, Qt.Checked if str(path) in self._checked else Qt.Unchecked)
        if not path.exists():
            item.setForeground(0, QBrush(QColor("#909090")))
            item.setToolTip(0, f"{path} is not there (external drive not mounted?)")

    def check(self, needle: str, on: bool = True) -> bool:
        """Tick the first leaf whose label or path contains `needle`."""
        for item in self._leaves():
            if needle in item.text(0) or needle in str(item.data(0, Qt.UserRole)):
                item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                return True
        return False

    def _leaves(self):
        for top in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(top)
            for row in range(parent.childCount()):
                yield parent.child(row)

    def checked_files(self) -> list[tuple[str, Path]]:
        return [
            (item.text(0), Path(str(item.data(0, Qt.UserRole))))
            for item in self._leaves()
            if item.checkState(0) == Qt.Checked
        ]

    def quick_row(self) -> tuple[str, Path] | None:
        """(label, path) of the row under the cursor, when quick view is on."""
        if not self.quick_check.isChecked():
            return None
        item = self.tree.currentItem()
        path = None if item is None else item.data(0, Qt.UserRole)
        if not path:  # a group header, or nothing current
            return None
        return item.text(0), Path(str(path))

    # --------------------------------------------------------------- slots

    def _item_changed(self, _item, _column) -> None:
        self._checked = {str(p) for _label, p in self.checked_files()}
        self.schedule()

    def _current_changed(self, _current, _previous) -> None:
        if self.quick_check.isChecked():
            self.schedule()

    def _item_clicked(self, _item, _column) -> None:
        # a click must leave the arrow keys working on the tree
        self.tree.setFocus()

    def _choice_toggled(self, on: bool) -> None:
        if on:  # a radio group fires twice, off then on
            self.schedule()

    def _job_finished(self, index: int, ok: bool) -> None:
        """A finished process_rr rewrote `<workspace>/tf`: re-list and re-read."""
        job = self.state.runner.jobs[index]
        if ok and "process_rr" in job.label:
            tf_plot.clear_cache()
            self.reload()

    # ------------------------------------------------------------- the plot

    def choice(self) -> str:
        """Which of `tf_plot.CHOICES` the radio buttons are asking for."""
        if self.pt_radio.isChecked():
            return "pt"
        if self.tipper_radio.isChecked():
            return "tipper"
        return "rho"

    def _survey_has_hz(self) -> bool:
        """Does any site of this survey declare an hz channel?

        `channels: [ex, ey, hx, hy]` is how a survey says its loggers carried
        no hz sensor; the B423 Bz column is then an open input and any tipper
        in the EDIs is an estimate from a dead channel.
        """
        survey = self.state.survey
        if survey is None:
            return False
        for name in self.state.configured_sites():
            channels = survey.site(name).channels
            if channels is None or any(str(c).lower() == "hz" for c in channels):
                return True
        return False

    def _update_tipper_button(self) -> None:
        has_hz = self._survey_has_hz()
        self.tipper_radio.setEnabled(has_hz)
        self.tipper_radio.setToolTip("" if has_hz else NO_HZ_TIP)
        if not has_hz and self.tipper_radio.isChecked():
            self.rho_radio.setChecked(True)

    def rows_to_draw(self) -> tuple[list[tuple[str, Path]], tuple[str, Path] | None]:
        """(rows, quick row): the cursor row first, then everything ticked."""
        quick = self.quick_row()
        rows = list(self.checked_files())
        if quick is not None:
            rows = [quick] + [row for row in rows if str(row[1]) != str(quick[1])]
        return rows, quick

    def schedule(self) -> None:
        """Ask for a redraw in `DEBOUNCE_MS`, replacing any pending one."""
        self._timer.start()

    def redraw(self) -> None:
        """Draw the current rows with mtpy, on the GUI thread."""
        self._timer.stop()
        rows, quick = self.rows_to_draw()
        if rows:
            self.status_label.setText("drawing...")
            self.status_label.repaint()
        title = " + ".join(label for label, _p in rows)
        if quick is not None:
            title = f"{title}   [quick view: {quick[1].name}]"
        started = time.perf_counter()
        drawn, problems = tf_plot.draw(
            self.figure, rows, self.choice(), title=title, hint=EMPTY_HINT
        )
        self.canvas.draw_idle()
        self.last_seconds = time.perf_counter() - started
        self.draws += 1
        if drawn:
            summary = (f"{len(drawn)} EDI{'s' if len(drawn) != 1 else ''}: "
                       f"{', '.join(drawn)}  ({self.last_seconds:.2f} s)")
        else:
            summary = "nothing to draw - tick a row, or switch Quick view on"
        self.status_label.setText(summary + ("; " + "; ".join(problems) if problems else ""))
