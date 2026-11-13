# -*- coding: utf-8 -*-
"""
Figures of the Stacks tab's member check: the preview panels and the weights plot

A figure script, not a unit suite. It opens the GUI offscreen, runs the member
check and saves what the check pane shows below its first screen: the two
preview panels (By-Ex over Bx-Ey, the stack's band power over the members')
and, for a coherence-weighted time recipe, the weights plot. The default run
uses the synthetic survey of tests/stacks_tab_unit.py (STK_H checked on the
local L, then an in-memory time_coherence recipe over the five members);
``--survey nador`` opens the Nador survey read-only (every queue, build and
save call diverted, every file under the survey folder and the workspace
compared before and after) with an in-memory band_median H base recipe and
a time_coherence recipe over the first five members of that check.

The images are grabbed from the check widget itself, so they hold the panels
whatever the scroll position. They go to ``--out`` (default: the test scratch
folder).

This script fails if (exit 1, the failed criteria printed):
- the check does not finish within its timeout or its status line is not the
  expected member count, span and method
- either preview panel holds other than members + 1 curves, or the preview
  grab is not the two panels' united height or not taller than the scroll
  viewport
- on the synthetic survey, the stack's band power over the members' lies
  outside 0.30-0.42 on hx (one member's hx reversed) or 0.8-1.25 on hy
- the time_coherence check gives no weights, weights not of one row per
  member and one column per chunk, a chunk whose weights do not sum to 1,
  or a weights plot hidden or holding other than two curves per member
- a message box opens, a Qt slot raises, a job other than the synthetic
  survey's basemap fetch is run, a job is queued, a recipe is saved, or
  (Nador) any watched file changes

Usage:
    QT_QPA_PLATFORM=offscreen python tests/stacks_tab_shots.py [--survey nador] [--out DIR]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stacks_tab_unit as stu  # noqa: E402  (its import diverts run_now and the message boxes)
from _scratch import scratch_dir  # noqa: E402

from mt_workbench import stacks  # noqa: E402
from mt_workbench.gui import availability_model, theme  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
NADOR_YAML = REPO / "surveys" / "MT_Morocco_Nador_Geothermal" / "survey.yaml"
NADOR_WORKSPACE = Path("D:/MT_DATA/MT_Morocco_Nador_Geothermal_Workspace")
FAILED: list[str] = []
DIVERTED: list[list[str]] = []
BOXES: list = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILED.append(what)


def guard_writes() -> None:
    """Divert every call that would run, queue, save or ask."""

    def divert(self, label, argv, **details):
        DIVERTED.append([str(a) for a in argv])
        return -1

    def no_box(*args, **kwargs):
        BOXES.append(args[1:3])
        return QMessageBox.Ok

    def refuse(name):
        def _refuse(*a, **k):
            raise RuntimeError(f"{name} called")
        return _refuse

    JobRunner.run_now = divert
    JobRunner.add = refuse("JobRunner.add")
    JobRunner.run_queue = refuse("JobRunner.run_queue")
    for kind in ("warning", "critical", "information", "question"):
        setattr(QMessageBox, kind, staticmethod(no_box))
    for name in ("save_recipe", "save_chart"):
        setattr(stacks, name, refuse(f"stacks.{name}"))


def snapshot(roots) -> dict:
    out = {}
    for root in roots:
        for p in Path(root).rglob("*"):
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def preview_grab(check_widget):
    rect = check_widget.panels[0].geometry().united(check_widget.panels[1].geometry())
    return check_widget.grab(rect), rect


def judge_preview(tab, members: int, status: str, label: str) -> None:
    widget = tab.check
    check(widget.status.text() == status, f"{label} status {widget.status.text()!r} == {status!r}")
    for i, panel in enumerate(widget.panels):
        n = len(panel.getPlotItem().listDataItems())
        check(n == members + 1, f"{label} panel {i} holds {n} curves (members + 1 = {members + 1})")
    img, rect = preview_grab(widget)
    viewport = widget.parentWidget().parentWidget()
    check(img.height() == rect.height() and img.height() > viewport.height(),
          f"{label} preview grab {img.width()}x{img.height()} is the panels' {rect.height()} px, "
          f"taller than the viewport's {viewport.height()}")


def judge_weights(tab, members: int, chunks: int, label: str) -> None:
    widget = tab.check
    res = widget.result()
    weights = res.weights if res is not None else None
    check(bool(weights), f"{label} the time_coherence check gives weights")
    if weights:
        for role, w in weights.items():
            check(w.shape == (members, chunks), f"{label} {role} weights shape {w.shape} == ({members}, {chunks})")
            sums = np.nansum(w, axis=0)
            check(bool(np.all(np.abs(sums - 1.0) < 1e-9)), f"{label} {role} chunk sums {np.round(sums, 6).tolist()}")
    curves = len(widget.weights.getPlotItem().listDataItems())
    check(widget.weights.isVisible() and curves == 2 * members,
          f"{label} weights plot shown with {curves} curves (2 x {members})")


def wait_check(app, tab, results, timeout: float, what: str) -> None:
    results.clear()
    stu.wait_until(app, lambda: bool(results), timeout, what)
    stu.pump(app, 0.5)


def synthetic(app, out: Path) -> None:
    stu.SCRATCH = scratch_dir("stacks_tab_shots")  # build_survey empties its folder: never the unit test's
    yaml_path = stu.build_survey()
    window = MainWindow(survey_yaml=yaml_path)
    window.resize(1500, 1000)
    window.show()
    stu.pump(app, 0.3)
    state, tab = window.state, window.stacks_tab
    window.tabs.setCurrentWidget(tab)
    state.set_site("L")
    stu.pump(app, 0.2)
    stu.wait_until(app, lambda: tab.chart.reads_pending() == 0
                   and all(r.runs is not None for r in tab.chart.rows() if r.site != "S1"), 60, "chart reads")
    row = next(r for r in tab.chart.rows() if r.site == "L")
    tree = availability_model.tree_window_at(row.runs["all"], row.rate, row.runs["all"][0][0])
    results = []
    tab.check.ready.connect(results.append)
    state.set_selection("L", *tree)
    wait_check(app, tab, results, 240, "band check")
    judge_preview(tab, 5, "5 member(s), 2024-03-01 00:00 to 01:10 UTC, band mean", "synthetic")
    res = tab.check.result()
    if res is not None:
        for role, lo, hi in (("hx", 0.30, 0.42), ("hy", 0.8, 1.25)):
            prev = res.preview[role]
            ratio = prev["stack"] / np.median(prev["members"], axis=0)
            med = float(np.median(ratio[np.isfinite(ratio)]))
            check(lo <= med <= hi, f"synthetic {role} stack power over the members' {med:.3f} within {lo}-{hi}")
    preview_grab(tab.check)[0].save(str(out / "gui_stacks_preview.png"))
    recipe = stacks.Recipe.from_mapping("STK_TC", {
        "field": "H", "use": "remote", "method": "time_coherence", "sample_rate": 100.0,
        "members": ["M1", "M2", "M3", "M4", "P"], "start": "2024-03-01 00:00", "end": "2024-03-01 01:00"})
    tab.form.set_recipe(recipe)
    tab._update()
    wait_check(app, tab, results, 240, "time check")
    judge_weights(tab, 5, 7, "synthetic")
    tab.check.weights.grab().save(str(out / "gui_stacks_weights.png"))
    window.close()
    stu.pump(app, 0.3)


def nador(app, out: Path) -> None:
    check(NADOR_YAML.exists() and NADOR_WORKSPACE.exists(), f"Nador survey and workspace present: {NADOR_YAML}")
    if FAILED:
        return
    before = snapshot((NADOR_YAML.parent, NADOR_WORKSPACE))
    print(f"files watched: {len(before)}")
    window = MainWindow(survey_yaml=NADOR_YAML)
    window.resize(1700, 1050)
    window.show()
    state, tab = window.state, window.stacks_tab
    window.tabs.setCurrentWidget(tab)
    stu.pump(app, 0.5)
    recipe = stacks.Recipe.from_mapping("STK_NADOR_H", {
        "field": "H", "use": "base", "method": "band_median", "sample_rate": 1000.0, "members": "rule",
        "screen_polarity": "drop", "start": "2023-12-21 12:00", "end": "2023-12-22 08:00"})
    tab.chart.set_references(["RR1", "RR2", "RR3"])
    tab.chart.set_night("01:00-07:00")
    tab.form.set_recipe(recipe)
    tab._fill_locals()
    tab.local_combo.setCurrentIndex(max(0, tab.local_combo.findData("P5S1")))
    tab._update()
    stu.wait_until(app, lambda: not tab.chart.reads_pending() and not any(
        r.runs is None and r.unread is None and state.has_archive(r.site) for r in tab.chart.rows()), 240, "chart")
    stu.pump(app, 1.0)
    row = next(r for r in tab.chart.rows() if r.site == "P5S1")
    t = pd.Timestamp("2023-12-22 01:00", tz="UTC")
    tree = availability_model.tree_window_at(row.runs["all"], row.rate, int(t.value))
    results = []
    tab.check.ready.connect(results.append)
    tab.check.failed.connect(lambda m: check(False, f"nador check failed: {m}"))
    state.set_selection("P5S1", *tree)
    stu.pump(app, 1.0)
    stu.wait_until(app, lambda: state.segment_store.segment is not None, 300, "segment")
    stu.pump(app, 2.0)
    tab.check_button.click()  # eleven members over an hour at 1000 Hz exceed the automatic budget
    wait_check(app, tab, results, 900, "band check")
    res = tab.check.result()
    members = len(res.members) if res is not None else 0
    check(members >= 2, f"nador band check has {members} members")
    judge_preview(tab, members, f"{members} member(s), 2023-12-22 00:35 to 01:35 UTC, band median", "nador")
    preview_grab(tab.check)[0].save(str(out / "gui_stacks_nador_preview.png"))
    top5 = list(res.members[:5]) if res is not None else []
    win = tab.chart.window()
    trec = stacks.Recipe.from_mapping("STK_NADOR_TC", {
        "field": "H", "use": "remote", "method": "time_coherence", "sample_rate": 1000.0, "members": top5,
        "start": f"{win[0]:%Y-%m-%d %H:%M}", "end": f"{win[1]:%Y-%m-%d %H:%M}"})
    tab.form.set_recipe(trec)
    tab._update()
    wait_check(app, tab, results, 900, "time check")
    judge_weights(tab, 5, 6, "nador")
    tab.check.weights.grab().save(str(out / "gui_stacks_nador_weights.png"))
    window.close()
    stu.pump(app, 0.3)
    after = snapshot((NADOR_YAML.parent, NADOR_WORKSPACE))
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    check(not changed, f"nador survey folder and workspace unchanged ({len(changed)} changed: {changed[:5]})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--survey", choices=["synthetic", "nador"], default="synthetic")
    parser.add_argument("--out", type=Path, default=None, help="folder for the PNGs (default: the test scratch)")
    args = parser.parse_args()
    out = args.out or scratch_dir("stacks_tab_shots") / "shots"
    out.mkdir(parents=True, exist_ok=True)
    guard_writes()
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    started = time.time()
    if args.survey == "nador":
        nador(app, out)
    else:
        synthetic(app, out)
    ran = [a for a in DIVERTED if not any(Path(x).name == "fetch_basemap.py" for x in a)]  # the fixture has no basemap
    check(not BOXES and not stu.SLOT_ERRORS and not ran,
          f"no message box ({BOXES}), slot error ({stu.SLOT_ERRORS}) or run beyond the basemap fetch ({ran})")
    print(f"{'FAIL' if FAILED else 'PASS'}  stacks_tab_shots --survey {args.survey} ({time.time() - started:.0f} s), "
          f"figures in {out}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
