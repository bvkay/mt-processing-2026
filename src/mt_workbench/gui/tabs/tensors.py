# -*- coding: utf-8 -*-
"""
View tensors tab

Lists and draws the inter-site products of `<workspace>/tf`: the telluric
tensor (E at a local site on E at a base) and the magnetic tensor (H on H)
that `scripts/process_intersite.py` writes as a CSV, a JSON sidecar, an h5
and a figure under one stem. A stem is listed when it has a `.csv` and a
`.json` whose sidecar says ``kind`` telluric or magnetic (`find_products`);
the file name is not parsed, and an EDI product is never listed. A sidecar
that cannot be read is listed in its own group with the reason.

The tree has one row per product under its local site: local, base (a
site, or the stack's name), reference, tensor, tag and window. The current
row is drawn with `mt_workbench.intersite.draw_estimate`, the function that
draws the script's own figure: magnitudes and phases of the four elements,
and arg(det) / 2 with its error bars, the timing line and the flags. The
CSV is read with `mt_workbench.intersite.read_csv` when the row is chosen.
Under the tree, `facts_text` gives the facts of the run from the sidecar:
the sites, the window, the periods estimated and flagged, the masks, each
site's frame as recorded, and whether the timing delay was determined.

Reload rereads the folder, and so does a finished job of
process_intersite.py. A sidecar is read once per modification time and
size, and only the facts the tab shows are kept (`run_facts`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mt_workbench import intersite
from mt_workbench.gui import theme

SCRIPT = "process_intersite.py"  # a finished job of this script has written a product
COLUMNS = ("local", "base", "reference", "tensor", "tag", "window (UTC)")
UNREADABLE = "cannot be read"  # the group of the products whose sidecar does not read
NOT_RECORDED = "not recorded"
HINT = "select a tensor product on the left to draw it"


def _window(facts: dict) -> str:
    """Return a run's window as "2024-03-01 00:00:00 to 2024-03-01 00:20:00", "" when the sidecar has none."""
    if not (facts["start"] and facts["end"]):
        return ""
    return " to ".join(str(facts[key])[:19].replace("T", " ") for key in ("start", "end"))


def run_facts(sidecar) -> dict | None:
    """Return the facts of a run the tab shows, from its sidecar; None when the sidecar is not a tensor's.

    A key the sidecar lacks gives None (an empty dict for ``flags`` and
    ``frames``), so a product written by another script, such as a merge
    of two products, is still listed.

    Args:
        sidecar: The parsed `.json` of a product.

    Returns:
        dict | None: ``kind``, ``letter``, ``local``, ``base`` (the site,
        or the stack's name), ``base_members`` (None for a site),
        ``reference``, ``reference_channels``, ``reference_members`` (None
        for a site), ``start``, ``end``, ``hours``, ``tag``, ``bands``,
        ``flags`` ({flag: rows}), ``masks`` ([(site, role, entries applied,
        band windows masked)], the sidecar's own words when it holds a
        text, None without the block), ``frames`` ({site: its frame}),
        ``timing`` (the timing check) and ``units``.
    """
    if not isinstance(sidecar, dict) or sidecar.get("kind") not in intersite.TENSORS:
        return None
    window, reference = sidecar.get("window") or {}, sidecar.get("reference") or {}
    stack, masks = sidecar.get("base_stack"), sidecar.get("masks")
    if isinstance(masks, dict):
        masks = [(site, entry.get("role"), len(entry.get("applied") or []), entry.get("windows_masked"))
                 for site, entry in (masks.get("sites") or {}).items()]
    # a base stack has no site: the inputs carry its name, "stackE ex" or "<recipe> ex"
    inputs = sidecar.get("inputs") or [""]
    return {
        "kind": sidecar["kind"], "letter": intersite.TENSORS[sidecar["kind"]], "local": sidecar.get("local"),
        "base": sidecar.get("base_site") or str(inputs[0]).rsplit(" ", 1)[0] or None,
        "base_members": None if not stack else [m["site"] for m in stack.get("members") or []
                                                if not m.get("dropped")],
        "reference": sidecar.get("remote") or reference.get("site"),
        "reference_channels": reference.get("channels"),
        "reference_members": (None if reference.get("type") != "stack" else
                              [m["site"] for m in reference.get("members") or []]),
        "start": window.get("start"), "end": window.get("end"), "hours": window.get("hours"),
        "tag": sidecar.get("tag"), "bands": (sidecar.get("counts") or {}).get("bands"),
        "flags": {name: block.get("rows") for name, block in (sidecar.get("flags") or {}).items()},
        "masks": masks, "frames": dict((sidecar.get("frames") or {}).get("sites") or {}),
        "timing": sidecar.get("timing_check"), "units": sidecar.get("units"),
    }


def find_products(tf_dir, kept: dict | None = None) -> list[dict]:
    """List the tensor products of a tf folder: every stem with a `.csv` and a `.json` sidecar of a tensor.

    The sidecar decides, not the file name. A sidecar that reads and is
    not a tensor's is left out. One that cannot be read is listed with the
    reason: it has the two files of a tensor product, and leaving it out
    would hide a product from the student.

    Args:
        tf_dir (str or Path): The folder, `<workspace>/tf`.
        kept (dict, optional): What each sidecar gave at its modification
            time and size, filled here; a later call with the same dict
            reads only the sidecars that are new or rewritten.

    Returns:
        list[dict]: One per product, sorted by local, base, reference,
        window, tensor and tag, the unreadable ones last: ``stem``, ``csv``
        (Path), ``facts`` (`run_facts`; None when unreadable) and
        ``problem`` (the reason; None when read).
    """
    tf_dir = Path(tf_dir)
    kept = {} if kept is None else kept
    names = set(os.listdir(tf_dir)) if tf_dir.is_dir() else set()
    products = []
    for stem in (name[:-5] for name in names if name.endswith(".json") and f"{name[:-5]}.csv" in names):
        path = tf_dir / f"{stem}.json"
        try:
            status = path.stat()
            stamp = (status.st_mtime_ns, status.st_size)
            if kept.get(str(path), (None, None))[0] != stamp:
                with open(path, encoding="utf-8") as handle:
                    kept[str(path)] = (stamp, run_facts(json.load(handle)))
            facts, problem = kept[str(path)][1], None
            if facts is None:  # a sidecar of something else, such as an impedance
                continue
        except (OSError, ValueError, AttributeError, TypeError, KeyError) as exc:
            facts, problem = None, f"{path.name} cannot be read ({type(exc).__name__}: {exc})"
        products.append({"stem": stem, "csv": tf_dir / f"{stem}.csv", "facts": facts, "problem": problem})

    def order(product: dict) -> tuple:
        facts = product["facts"] or {}
        return (product["facts"] is None,
                *(str(facts.get(key) or "") for key in ("local", "base", "reference", "start", "kind", "tag")),
                product["stem"])

    return sorted(products, key=order)


def row_texts(facts: dict) -> list[str]:
    """Return the six cells of a product's row, in the order of `COLUMNS`."""
    return [str(facts[key] or "") for key in ("local", "base", "reference", "kind", "tag")] + [_window(facts)]


def title_of(facts: dict) -> str:
    """Return the figure title of a product: the tensor, the sites and the window."""
    window = _window(facts)
    return (f"{intersite.TENSOR_NAMES[facts['letter']]} of {facts['local']} on {facts['base']}, reference "
            f"{facts['reference']}" + (f", {window} UTC" if window else ""))


def facts_text(facts: dict) -> str:
    """Return the facts of a run as the text shown beside its figure.

    The sites, the window, the periods estimated and the rows of each flag,
    the masks applied, each site's frame with the words "as recorded, not
    rotated", and the timing check in `mt_workbench.intersite.timing_text`'s
    words. A fact the sidecar does not hold reads "not recorded".

    Args:
        facts (dict): `run_facts` of the product's sidecar.

    Returns:
        str: One fact per line.
    """
    local, base, field = facts["local"], facts["base"], intersite.BASE_FIELDS[facts["kind"]]
    members, flags = facts["base_members"], facts["flags"]
    lines = [f"{intersite.TENSOR_NAMES[facts['letter']]} of {local} on {base}",
             f"{field} at the local site on {field} at the base: one 2 x 2 tensor per period", "",
             f"local: {local or NOT_RECORDED}",
             f"base: {base or NOT_RECORDED}" + ("" if members is None else
                                               f", a stack of {len(members)} sites ({', '.join(members)})")]
    reference = str(facts["reference"] or NOT_RECORDED)
    if facts["reference_members"] is not None:
        reference += f", a stack of {len(facts['reference_members'])} sites ({', '.join(facts['reference_members'])})"
    elif facts["reference_channels"]:
        reference += f" ({', '.join(facts['reference_channels'])})"
    lines.append(f"reference: {reference}")
    window = _window(facts)
    lines.append(f"window: {window + ' UTC' if window else NOT_RECORDED}"
                 + ("" if facts["hours"] is None else f", {facts['hours']:.1f} h"))
    lines += [f"tag: {facts['tag'] or 'none'}", ""]

    bands, missing = facts["bands"], flags.get("flag_not_estimated")
    if bands is None or missing is None:
        lines.append(f"periods: {NOT_RECORDED}")
    else:
        lines.append(f"periods: {bands - missing} estimated of the {bands} in the layout; {missing} not estimated, "
                     f"which have no value to draw")
    lines.append("flags (a flag marks a period and never removes it):")
    for flag, (words, _marker, _colour) in intersite.FLAG_MARKS.items():
        rows = flags.get(flag)
        lines.append(f"    {words}: {NOT_RECORDED if rows is None else rows}")
    lines.append("")

    masks = facts["masks"]
    if masks is None or isinstance(masks, str):
        lines.append(f"masks: {masks or NOT_RECORDED}")
    elif not any(count for _site, _role, count, _windows in masks):
        lines.append("masks: no masks.yaml entry applied")
    else:
        lines.append("masks applied:")
        lines += [f"    {site} ({role}): {count} masks.yaml entr{'y' if count == 1 else 'ies'}, {windows} band "
                  f"windows left out" for site, role, count, windows in masks if count]
    lines.append("frames: as recorded, not rotated" + ("" if facts["frames"] else f" ({NOT_RECORDED})"))
    for site, frame in facts["frames"].items():
        declination = frame.get("declination")
        lines.append(f"    {site} ({frame.get('role')}): ex at {frame.get('azimuth_ex')} deg, ey at "
                     f"{frame.get('azimuth_ey')} deg from {frame.get('layout_north')} north; declination "
                     + ("not recorded" if declination is None else f"{declination} deg, recorded and not applied"))
    timing = facts["timing"]
    if not timing:
        lines.append(f"timing delay: {NOT_RECORDED}")
    else:
        word = {True: "determined", False: "not determined"}.get(timing.get("determined"), "no fit was made")
        lines.append(f"timing delay: {word}")
        shortest = len(timing.get("three_shortest") or [])
        lines += ["    " + line.removeprefix("timing: ") for line in intersite.timing_text(timing)[shortest:]]
    lines += ["", f"arg(det) / 2 in the bottom panel is relative to the base: the phase of {local} less that of "
                  f"{base}."]
    if facts["units"]:
        lines.append(f"units: {facts['units']}")
    return "\n".join(lines)


class TensorTab(QWidget):
    """A tree of the workspace's tensor products beside the figure and the facts of the current one.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._kept: dict = {}  # sidecar path -> ((mtime, size), facts): see `find_products`

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setMinimumWidth(360)
        self.tree.currentItemChanged.connect(lambda _current, _previous: self.draw())
        self.facts = QPlainTextEdit(self, readOnly=True)
        self.reload_button = QPushButton("Reload", self)
        self.reload_button.setToolTip("Read the workspace's tf folder again")
        self.reload_button.clicked.connect(self.reload)
        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)

        self.figure = Figure(figsize=(9.0, 7.0), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        left = QSplitter(Qt.Vertical, self)
        left.addWidget(self.tree)
        left.addWidget(self.facts)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas, 1)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        header = QHBoxLayout()
        header.addWidget(self.reload_button)
        header.addWidget(self.status_label, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self.state.runner.job_finished.connect(self._job_finished)
        self.draw()

    # ------------------------------------------------------------- the list

    def reload(self) -> None:
        """Reread the tf folder and rebuild the tree, keeping the current product when it is still there."""
        current = self.current()
        keep = current["stem"] if current else None
        tf_dir = self.state.tf_dir()
        products = find_products(tf_dir, self._kept) if tf_dir is not None else []
        self.tree.blockSignals(True)
        self.tree.clear()
        group, chosen = None, None
        for product in products:
            facts = product["facts"]
            name = UNREADABLE if facts is None else str(facts["local"] or NOT_RECORDED)
            if group is None or group.text(0) != name:
                group = QTreeWidgetItem(self.tree, [name])
                group.setFlags(Qt.ItemIsEnabled)
                group.setFirstColumnSpanned(True)
            item = QTreeWidgetItem(group, [product["problem"]] if facts is None else row_texts(facts))
            item.setData(0, Qt.UserRole, product)
            item.setToolTip(0, str(product["csv"]))
            if facts is None:
                item.setFirstColumnSpanned(True)
            if product["stem"] == keep:
                chosen = item
        self.tree.expandAll()
        for column in range(len(COLUMNS)):
            self.tree.resizeColumnToContents(column)
        self.tree.setCurrentItem(chosen)
        self.tree.blockSignals(False)
        self.draw()

    def rows(self) -> list[QTreeWidgetItem]:
        """Return every product row of the tree, top to bottom."""
        groups = [self.tree.topLevelItem(k) for k in range(self.tree.topLevelItemCount())]
        return [group.child(k) for group in groups for k in range(group.childCount())]

    def current(self) -> dict | None:
        """Return the current row's product (`find_products`), None on a group row or with no row."""
        item = self.tree.currentItem()
        return None if item is None else item.data(0, Qt.UserRole)

    def _job_finished(self, index: int, ok: bool) -> None:
        """Reread the folder after a job of process_intersite.py that ended well."""
        job = self.state.runner.jobs[index]
        if ok and any(Path(part).name == SCRIPT for part in job.argv):
            self.reload()

    # ----------------------------------------------------------- the figure

    def draw(self) -> None:
        """Draw the current product and show its facts; say what to do when there is none or it does not read."""
        product = self.current()
        tf_dir = self.state.tf_dir()
        self.figure.clear()
        if product is None:
            count = len(self.rows())
            if tf_dir is None:
                message = "no survey is open: File > Open survey..."
            elif count == 0:
                message = (f"no tensor product in {tf_dir}\n\nqueue a telluric or a magnetic tensor on the Process "
                           f"tab,\nor run scripts/{SCRIPT}, then press Reload")
            else:
                message = HINT
            self._say(message, facts="")
            self.status_label.setText(f"{count} tensor product{'s' if count != 1 else ''}"
                                      + (f" in {tf_dir}" if tf_dir is not None else ""))
            return
        facts, problem = product["facts"], product["problem"]
        if problem is None:
            try:
                est, letter = intersite.read_csv(product["csv"])
                if est.period.size == 0:
                    raise ValueError("it holds no period")
            except Exception as exc:  # a CSV cut short, or one of another layout
                problem = f"{product['csv'].name} cannot be read ({type(exc).__name__}: {exc})"
        if problem is not None:
            message = (f"{problem}\n\nRun the pair again to write the product afresh, or take the files of "
                       f"{product['stem']} out of {tf_dir}.")
            self._say(message, facts=message)
            self.status_label.setText(problem)
            return
        intersite.draw_estimate(self.figure, est, letter, title=title_of(facts), timing=facts["timing"])
        self.canvas.draw_idle()
        self.facts.setPlainText(facts_text(facts))
        self.status_label.setText(f"{product['stem']}: {int((~est.flags()['flag_not_estimated']).sum())} of "
                                  f"{est.period.size} periods drawn; as recorded, not rotated")

    def _say(self, message: str, facts: str) -> None:
        """Leave the figure empty with a message across it, and set the facts box."""
        self.figure.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, color=theme.FOREGROUND, wrap=True)
        self.canvas.draw_idle()
        self.facts.setPlainText(facts)
