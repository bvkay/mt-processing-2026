# -*- coding: utf-8 -*-
"""
Unit test for the Stacks tab and the Process tab's recipe picker (run headless)

The test writes a scratch survey of eight 100 Hz sites with ex, ey, hx and
hy over 70 minutes (L, the local; M1-M4; P, whose hx is reversed; Q, which
records the first 35 minutes only; R, L's declared remote), a 1 Hz entry S1
with no archive, an archive STK_T.h5 standing for a built time recipe, raw
folders holding one empty B423 file per archived site (so the Process tab
lists stations; every site has an archive, so no raw file is read), and a
stacks.yaml written by hand with comments and LF newlines: STK_H (band mean,
H, base, rule, R excluded), STK_EREF (band median, E, reference, a list),
STK_EBASE (band mean, E, base, rule, R excluded), STK_EB2 (the same without
the exclude, so R, L's remote, is a member), STK_T (time mean, M1-M3, one
hour), STK_EQ (STK_EBASE with min_overlap_hours 0.5, so Q is a member and
its end at 00:35 changes the membership), STK_EQA (STK_EQ with
member_change: allow) and STK_EBW (STK_EBASE declaring the window
00:00-01:00); and a masks.yaml with one all-band mask on M2, 01:01-01:04,
outside the default window. `JobRunner.run_now` is replaced before the window is
built (the basemap fetch is recorded, not run); `runner.add` and `run_queue`
are wrapped so queued jobs are recorded and never start; the QMessageBox
statics are replaced by recorders; and a `sys.excepthook` collects
exceptions raised in Qt slots. Command lines the GUI would queue are run
here with --dry-run, which writes nothing.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/stacks_tab_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1.  the tab titles are not, in order, Metadata, Time Series, Spectra,
    Spectrogram, Coherence, Filter Data, Cross-powers, Stacks, Process, View
    EDIs, View tensors, or `window.tabs.widget(7)` is not `window.stacks_tab`;
2.  once the chart's reads finish (STK_H, local L), the chart does not hold
    one row per survey.yaml site, or any row's member flag or reason differs
    from `stacks.resolve_members` with its default h5py reads for the same
    recipe, window and local; or the outcome is not, literally: the window
    00:00-01:00, the members exactly M1, M2, M3, M4 and P, R "excluded on
    request", L "the local", Q left out on its 0.58 h of cover, S1 "1 Hz,
    the pair is at 100 Hz";
3.  Save recipe of STK_H with its reject factor moved to 30 does not
    round-trip (the saved block loads equal to the form's recipe and reads
    "reject_factor: 30.0"), changes a byte outside STK_H's key line and
    indented lines (found here by a splitter of this test's own), or puts a
    carriage return in the file; or saving a new recipe STK_NEW changes any
    byte of the file before the appended block;
4.  after `recipe_saved`, the Process picker does not list exactly the valid
    recipes of stacks.yaml in file order, then "edit in Stacks tab..."; or,
    STK_T chosen in the picker, the Process site map does not paint M1, M2
    and M3 `SiteMap.MEMBER`, or the Process tab's row-3 Build stack does not
    record `[python_exe, <scripts>/build_stack.py, <survey.yaml>, --recipe,
    STK_T, --overwrite]`;
5.  Build archive for the saved STK_T does not record `[python_exe,
    <scripts>/build_stack.py, <survey.yaml>, --recipe, STK_T, --overwrite]`
    through `ProcessTab.queue_stack` with `_stack_jobs` holding STK_T; or
    Build archive is enabled for STK_H (a band recipe) or for STK_T with an
    unsaved edit; or Use in Process is enabled for STK_EREF (a reference
    recipe); or choosing STK_H while STK_T holds that edit does not put
    "unsaved edits to STK_T dropped" on the status line;
6.  Use in Process with STK_T does not choose STK_T in the picker and put
    its window on the Process window bar, or makes STK_T the remote while
    the Process station is M1 (one of its members), or does not make it the
    remote of L; with STK_EBASE, the picker's Queue intersite does not record
    `[python_exe, <scripts>/process_intersite.py, <survey.yaml>, L, <start>,
    <end>, --kind, telluric, --remote, R, --stack, STK_EBASE]` as a
    "processing" job, or that command line with --dry-run exits other than
    0; or Queue intersite is enabled for STK_EREF or for the remote STK_T
    (an archive, not a survey.yaml site); or, for STK_EB2 with the remote R,
    Queue intersite is enabled or the hint does not say "R would sit in
    STK_EB2's base stack and be the reference", while the same command line
    built by `stacks.intersite_argv` dry runs with exit other than 2 naming
    --allow-shared-members (so the picker refuses what the script refuses);
    or, for STK_EQ with the bar at 00:00-01:10, Queue intersite is enabled or
    the hint's first line does not start "STK_EQ's membership changes inside
    the window" and name "Q ends at 2024-03-01 00:34", while the same command
    line dry runs with exit other than 2 naming "Q ends"; or Queue intersite
    is disabled for STK_EQA (member_change: allow); or, for STK_EBW with the
    bar at 00:10-00:50, no hint line is exactly "the bar's window replaces
    STK_EBW's declared window (2024-03-01 00:00 to 2024-03-01 01:00)", the
    command line's start and end are not the bar's, or its dry run exits
    other than 0 or does not print the bar's window and the declared one as
    recipe_window; or a hint line holds "replaces" for STK_EBW with the bar
    at 00:00-01:00 or for STK_EBASE (no declared window) at 00:10-00:50;
    or, given the remote S1 (1 Hz), Queue intersite is enabled or the hint
    does not name 1 Hz; or, with STK_T the remote of L, selecting the
    station M1 keeps STK_T as the remote or leaves the status line without
    "STK_T holds M1", or Add to queue with M1 and STK_T chosen by hand
    queues a job or opens no warning;
7.  after `state.set_selection` of L's tree window and its segment loads,
    the member check does not flag P reversed (on hx) or leaves
    `state.archive_lock` busy; or, with the recipe's rate set to 1 Hz while
    the 100 Hz segment is loaded, a member read starts
    (`segment.load_segment` wrapped to count) or the status line does not
    name both rates; or, with the read budget
    `tabs.stacks.AUTO_CHECK_SAMPLES` set to 1, a member read starts before
    Check is clicked, the check's line does not ask for Check, or Check
    does not then read the five members;
8.  emitting `chart.bar_clicked(M1, t)` leaves `state.site` other than M1,
    changes `tab.local()`, or moves the reason "the local" off L in the
    rows;
9.  hiding the tab, with a check's arrays held, leaves `check.kept_sites()`
    not empty;
10. the chart's grab holds fewer than 100 pixels within 8 levels per
    channel of `theme.B_COLOUR` (the opaque H bars of an H recipe), or any
    QLabel in the tab shows a non-null pixmap (no PNG is displayed); or,
    with STK_EBASE (an electric recipe), the plot's pixels in the middle of
    M2's mask on its E strip lie within 40 levels of `theme.E_COLOUR`, while
    the same strip outside the mask lies more than 8 levels from it (the
    control: the sampling hits the strip); the grabs go to the scratch
    folder as gui_stacks.png and gui_stacks_check.png;
11. `window.close()` takes over 30 s, a modal message box other than the
    warning of (6) was opened, a Qt slot raised, a read thread of the chart
    starts after `tab.wait()` returned with reads pending (one archive per
    batch, every archive made stale), or the stacks.yaml of the Nador or
    Vulcan survey folder, in this tree or the main tree, differs in its
    bytes (or appears) between before the window was built and after it
    closed;
12. with a masks.yaml of 30,000 masks over eight sites, once loaded, the
    median of five form edits (a reject-factor step) takes 50 ms or more on
    the GUI thread, or hiding and showing the tab loads the masks again
    (`availability._read_masks` counted); the old chart parsed every mask's
    time on every redraw (87 ms of 110 ms per edit on the Atlas survey's
    30,802 masks [measured by the review]).
"""

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

from mt_workbench import stacks  # noqa: E402
from mt_workbench.gui import availability, availability_model, segment, theme  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from mt_workbench.gui.site_map import SiteMap  # noqa: E402
from mt_workbench.gui.stack_builder import StackBuilder  # noqa: E402
from mt_workbench.gui.tabs import stacks as stacks_tab_module  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

SCRATCH = scratch_dir("stacks_tab_unit")
SURVEY = "stacks_tab_unit"
FS = 100.0
N = int(4200 * FS)  # 70 min: a window of whole hours then ends inside every record (workbench issue 27)
T0 = pd.Timestamp("2024-03-01T00:00:00", tz="UTC")
SITES = ("L", "M1", "M2", "M3", "M4", "P", "Q", "R")
EXPECTED_TABS = ["Metadata", "Time Series", "Spectra", "Spectrogram", "Coherence", "Filter Data", "Cross-powers",
                 "Stacks", "Process", "View EDIs", "View tensors"]
# this tree and the main tree (the folder holding .git as a folder, not a worktree's .git file)
TREES = [REPO] + [p for p in REPO.parents if (p / ".git").is_dir()][:1]
REAL_SURVEYS = [tree / "surveys" / name for tree in TREES
                for name in ("MT_Morocco_Nador_Geothermal", "MT_Vulcan_2022")]
MASKS_YAML = """# one all-band mask on M2, outside the default window 00:00-01:00
M2:
- start: '2024-03-01T01:01:00Z'
  end: '2024-03-01T01:04:00Z'
  bands: all
  reason: test
  found_by: time
  scope: local
"""
STACKS_YAML = """# Stack recipes for stacks_tab_unit, written by hand.
# A second header line.

chart:
  references: [R]
  night: "01:00-05:00"

# the H base: every 100 Hz site but R
STK_H:
  field: H
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]
  reject_factor: 25.0
  notes: the H base

# a reference stack of three sites
STK_EREF:
  field: E
  use: reference
  method: band_median
  sample_rate: 100.0
  members: [M1, M2, M3]

STK_EBASE:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]

# the same base without the exclude: R, L's declared remote, is a member
STK_EB2:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule

# STK_OLD:
#   field: H

# an archive for process_rr.py
STK_T:
  field: H
  use: remote
  method: time_mean
  sample_rate: 100.0
  members: [M1, M2, M3]
  start: 2024-03-01 00:00
  end: 2024-03-01 01:00

# Q a member at half an hour of cover: its end at 00:35 changes the membership inside 00:00-01:10
STK_EQ:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]
  min_overlap_hours: 0.5

STK_EQA:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]
  min_overlap_hours: 0.5
  member_change: allow

# a base recipe declaring its window: the Process bar's window replaces it
STK_EBW:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]
  start: 2024-03-01 00:00
  end: 2024-03-01 01:00
"""

failures: list[str] = []
SLOT_ERRORS: list[str] = []
BOXES: list[tuple[str, str]] = []
FETCHES: list[list[str]] = []
_real_run_now = JobRunner.run_now


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def _recording_run_now(self, label, argv, **details):
    """Record a fetch_basemap.py job instead of starting it."""
    argv = [str(a) for a in argv]
    if any(Path(a).name == "fetch_basemap.py" for a in argv):
        FETCHES.append(argv)
        return -1
    return _real_run_now(self, label, argv, **details)


def _box(kind: str):
    def record(parent, title, text, *args, **kwargs):
        BOXES.append((kind, title))
        return QMessageBox.Ok
    return staticmethod(record)


JobRunner.run_now = _recording_run_now
for _kind in ("warning", "critical", "information", "question"):
    setattr(QMessageBox, _kind, _box(_kind))
def _slot_error(kind, value, tb) -> None:
    """Record an exception raised in a Qt slot, and print it: an error in main() lands here too."""
    SLOT_ERRORS.append(f"{kind.__name__}: {value}")
    traceback.print_exception(kind, value, tb)


sys.excepthook = _slot_error


# ------------------------------------------------------------------ fixture


def red(rng, n: int = N) -> np.ndarray:
    """Return red noise: white noise through a one-pole low-pass at 0.95."""
    return lfilter([1.0], [1.0, -0.95], rng.standard_normal(n))


def write_archive(workspace: Path, site: str, coils: dict) -> Path:
    """Write one site's archive as ingest_site lays it out: one run, int32 counts, no filters."""
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    chans = []
    for comp, data in coils.items():
        kind = "electric" if comp.startswith("e") else "magnetic"
        chans.append(ChannelTS(channel_type=kind, data=np.rint(data).astype("int32"),
                               channel_metadata={kind: {"component": comp, "sample_rate": FS,
                                                        "time_period.start": T0.tz_localize(None).isoformat()}}))
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        run = RunTS(chans, run_metadata={"id": "sr100_0001", "sample_rate": FS}, station_metadata={"id": site})
        station.add_run("sr100_0001").from_runts(run)
    finally:
        m.close_mth5()
    return path


def build_survey() -> Path:
    """Write the scratch survey of the module docstring; return its survey.yaml."""
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    raw, work = root / "raw", root / "work"
    raw.mkdir(parents=True)
    rng = np.random.default_rng(7)
    field = {c: 1000.0 * red(rng) for c in ("ex", "ey", "hx", "hy")}
    for k, site in enumerate(SITES):
        coils = {c: field[c] + 100.0 * red(rng) for c in field}
        if site == "P":
            coils["hx"] = -coils["hx"]
        if site == "Q":
            coils = {c: v[: N // 2] for c, v in coils.items()}
        write_archive(work, site, coils)
        (raw / site).mkdir()
        (raw / site / f"{int(T0.timestamp())}.B423").write_bytes(b"")
    write_archive(work, "STK_T", {c: field[c] for c in ("hx", "hy")})
    lines = [f"name: {SURVEY}", "instrument: lemi423", "sample_rate: 100", "timezone: Australia/Adelaide",
             f"data_root: {raw.as_posix()}", f"workspace: {work.as_posix()}", "defaults:",
             "  channels: [ex, ey, hx, hy]", "sites:"]
    for k, site in enumerate(SITES):
        extra = ", remote: R" if site == "L" else ""
        lines.append(f"  {site}: {{latitude: -31.{k + 1}, longitude: 137.{k + 1}{extra}}}")
    lines.append("  S1: {latitude: -31.9, longitude: 137.9, sample_rate: 1}")
    (root / "survey.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "stacks.yaml").write_bytes(STACKS_YAML.encode("utf-8"))
    (root / "masks.yaml").write_bytes(MASKS_YAML.encode("utf-8"))
    return root / "survey.yaml"


def real_state() -> dict:
    """Return each real survey folder's stacks.yaml bytes, or None when it has none."""
    return {str(p): ((p / "stacks.yaml").read_bytes() if (p / "stacks.yaml").exists() else None)
            for p in REAL_SURVEYS}


def dry_run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a command line the GUI would queue, with --dry-run (the script writes no file)."""
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    return subprocess.run(list(argv) + ["--dry-run"], capture_output=True, text=True, cwd=REPO, env=env)


def pixel_near(plot, x: float, y: float) -> tuple[int, int, int]:
    """Return the median colour of the 5 x 3 pixels of a plot's grab around view point (x, y)."""
    point = plot.mapFromScene(plot.getViewBox().mapViewToScene(QPointF(x, y)))
    image = plot.grab().toImage()
    pixels = [QColor(image.pixel(point.x() + dx, point.y() + dy)).getRgb()[:3]
              for dx in (-2, -1, 0, 1, 2) for dy in (-1, 0, 1)]
    return tuple(int(statistics.median(p[k] for p in pixels)) for k in range(3))


def levels_from(rgb, colour: str) -> int:
    """Return the largest per-channel difference between an (r, g, b) and a "#rrggbb" colour."""
    return max(abs(a - int(colour[i: i + 2], 16)) for a, i in zip(rgb, (1, 3, 5)))


# ------------------------------------------------------------------ helpers


def pump(app, seconds: float = 0.05) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while True:
        app.processEvents()
        if time.time() >= end:
            return
        time.sleep(0.005)


def wait_until(app, predicate, timeout: float, what: str) -> bool:
    """Pump until `predicate()` holds; record a failure after `timeout` seconds."""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    check(False, f"timed out after {timeout:g} s waiting for {what}")
    return False


def block_of(text: str, name: str) -> tuple[int, int]:
    """Return the (first, last + 1) line indices of a recipe's key line and indented lines, by this test's rule."""
    lines = text.split("\n")
    first = lines.index(f"{name}:")
    last = first + 1
    while last < len(lines) and lines[last][:1] in (" ", "\t"):
        last += 1
    return first, last


def outside(text: str, name: str) -> str:
    """Return the text without a recipe's block."""
    lines = text.split("\n")
    first, last = block_of(text, name)
    return "\n".join(lines[:first] + lines[last:])


def b_pixels(widget) -> int:
    """Count the pixels of a widget's grab within 8 levels per channel of theme.B_COLOUR."""
    image = widget.grab().toImage().convertToFormat(widget.grab().toImage().Format.Format_RGB32)
    width, height = image.width(), image.height()
    data = np.frombuffer(image.constBits(), np.uint8).reshape(height, image.bytesPerLine())
    bgra = data[:, : width * 4].reshape(height, width, 4).astype(int)
    hex_ = theme.B_COLOUR.lstrip("#")
    r, g, b = (int(hex_[i: i + 2], 16) for i in (0, 2, 4))
    near = (abs(bgra[..., 2] - r) <= 8) & (abs(bgra[..., 1] - g) <= 8) & (abs(bgra[..., 0] - b) <= 8)
    return int(near.sum())


# ------------------------------------------------------------------ the test


def main() -> None:
    """Criteria 1-12, in the order the tab is driven."""
    print(__doc__.split("**This test fails if**")[1].rstrip())
    begun = started = time.time()
    real_before = real_state()
    yaml_path = build_survey()
    stacks_path = yaml_path.parent / "stacks.yaml"
    print(f"     scratch survey written in {time.time() - started:.1f} s: {yaml_path}")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow(survey_yaml=yaml_path)
    window.resize(1500, 1000)
    window.show()
    pump(app, 0.3)
    state, tab, process = window.state, window.stacks_tab, window.process_tab
    runner = state.runner
    recorded: list[list[str]] = []
    real_add = runner.add

    def record(label, argv, **details):
        recorded.append([str(a) for a in argv])
        return real_add(label, argv, **details)

    runner.add, runner.run_queue = record, (lambda: None)
    survey = Survey.from_yaml(yaml_path)

    # ---------------------------------------------------------------- (1)
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    check(titles == EXPECTED_TABS, f"(1) tab titles {titles}")
    check(window.tabs.widget(7) is tab, "(1) widget(7) is window.stacks_tab")

    # ---------------------------------------------------------------- (2)
    window.tabs.setCurrentWidget(tab)
    state.set_site("L")
    pump(app, 0.2)
    wait_until(app, lambda: tab.chart.reads_pending() == 0
               and all(r.runs is not None for r in tab.chart.rows() if r.site != "S1"), 60, "the chart's reads")
    pump(app, 0.2)
    check(tab.recipe_combo.currentData() == "STK_H" and tab.local() == "L",
          f"(2) the tab opens on STK_H with local L: {tab.recipe_combo.currentData()}, {tab.local()}")
    rows = tab.chart.rows()
    check(sorted(r.site for r in rows) == sorted(survey.site_names()) and len(rows) == len(survey.site_names()),
          f"(2) one row per survey.yaml site: {[r.site for r in rows]}")
    recipe = stacks.load_recipe(survey, "STK_H")
    chart_window = tab.chart.window()
    members, left_out = stacks.resolve_members(recipe, survey, window=chart_window, local="L")
    expected = {m["site"]: (True, None) for m in members}
    expected.update({x["site"]: (False, x["reason"]) for x in left_out})
    got = {r.site: (r.member, r.reason) for r in rows}
    check(got == expected, f"(2) rows equal resolve_members over {chart_window[0]:%H:%M}-{chart_window[1]:%H:%M}: "
                           f"members {sorted(s for s, v in got.items() if v[0])}; "
                           f"{ {s: v[1] for s, v in got.items() if not v[0]} }")
    literal = (chart_window == (T0, T0 + pd.Timedelta(hours=1))
               and sorted(s for s, v in got.items() if v[0]) == ["M1", "M2", "M3", "M4", "P"]
               and got.get("R") == (False, "excluded on request") and got.get("L") == (False, "the local")
               and got.get("Q", (None, ""))[1] == "its runs with hx/hy cover 0.58 h of the window, under 1 h"
               and got.get("S1") == (False, "1 Hz, the pair is at 100 Hz"))
    check(literal, "(2) the outcome is the literal one: 00:00-01:00, members M1 M2 M3 M4 P, R excluded, L the "
                   "local, Q on its 0.58 h, S1 at 1 Hz")

    # ---------------------------------------------------------------- (10)
    shots = SCRATCH / "shots"
    shots.mkdir(exist_ok=True)
    tab.grab().save(str(shots / "gui_stacks.png"))
    count = b_pixels(tab.chart)
    check(count >= 100, f"(10) the chart's grab holds {count} pixels of B_COLOUR (at least 100)")
    shown = [label.text() or "(no text)" for label in tab.findChildren(QLabel) if not label.pixmap().isNull()]
    check(not shown, f"(10) no QLabel of the tab shows a pixmap: {shown}")
    tab.select_recipe("STK_EBASE")  # an electric recipe: M2's E strip opaque red under its mask
    wait_until(app, lambda: bool(tab.chart._masks.get("M2")), 60, "M2's mask to load")
    pump(app, 0.3)
    rows = tab.chart.rows()
    i_m2 = [r.site for r in rows].index("M2")
    y = i_m2 + availability.STRIP_GAP / 2 + availability.STRIP_H / 2  # the middle of M2's E strip
    masked_px = pixel_near(tab.chart.plot, (T0 + pd.Timedelta(seconds=3750)).value / 1e9, y)  # 01:02:30
    clear_px = pixel_near(tab.chart.plot, (T0 + pd.Timedelta(seconds=4020)).value / 1e9, y)  # 01:07
    check(next(r for r in rows if r.site == "M2").member and levels_from(clear_px, theme.E_COLOUR) <= 8,
          f"(10) control: M2 is an E member and its strip outside the mask is E_COLOUR: {clear_px}")
    check(levels_from(masked_px, theme.E_COLOUR) > 40,
          f"(10) M2's mask over its E strip reads {masked_px}, {levels_from(masked_px, theme.E_COLOUR)} levels from "
          f"E_COLOUR (more than 40)")
    tab.select_recipe("STK_H")
    pump(app, 0.2)

    # ---------------------------------------------------------------- (3)
    before = stacks_path.read_bytes().decode("utf-8")
    tab.form.reject_spin.setValue(30.0)
    pump(app, 0.1)
    path = tab.save_recipe()
    pump(app, 0.1)
    after_bytes = stacks_path.read_bytes()
    after = after_bytes.decode("utf-8")
    saved = stacks.load_recipe(survey, "STK_H")
    check(path is not None and saved == tab.form.recipe() and saved.reject_factor == 30.0,
          f"(3) STK_H saved and loads equal to the form (reject_factor {saved.reject_factor})")
    lines = after.split("\n")
    first, last = block_of(after, "STK_H")
    check("  reject_factor: 30.0" in lines[first:last], f"(3) the block reads reject_factor: 30.0: {lines[first:last]}")
    check(outside(before, "STK_H") == outside(after, "STK_H"), "(3) no byte outside STK_H's block changed")
    check(b"\r" not in after_bytes, "(3) no carriage return in stacks.yaml")
    tab.select_recipe("")
    pump(app, 0.1)
    tab.form.name_edit.setText("STK_NEW")
    tab.form.name_edit.textEdited.emit("STK_NEW")
    pump(app, 0.1)
    path = tab.save_recipe()
    pump(app, 0.2)
    appended = stacks_path.read_bytes().decode("utf-8")
    check(path is not None and appended.startswith(after) and "STK_NEW:" in appended[len(after):],
          f"(3) a new recipe is appended, the file before it unchanged ({len(after)} -> {len(appended)} bytes)")

    # ---------------------------------------------------------------- (4)
    builder = process.stack_builder
    valid, _errors = stacks.load_recipes(survey)
    listed = [builder.recipe_combo.itemData(i) for i in range(builder.recipe_combo.count())]
    check(listed == list(valid) + [StackBuilder.EDIT] and "STK_NEW" in listed,
          f"(4) the picker lists {listed}")
    builder.select_recipe("STK_T")
    pump(app, 0.1)
    painted = {s: process.site_map.colours.get(s) for s in ("M1", "M2", "M3", "M4")}
    check(all(painted[s] == SiteMap.MEMBER for s in ("M1", "M2", "M3")) and painted["M4"] != SiteMap.MEMBER,
          f"(4) STK_T's members M1-M3, and not M4, painted MEMBER on the Process map: {painted}")
    process.build_button.click()
    pump(app, 0.1)
    want = [state.python_exe, state.script("build_stack.py"), str(state.survey_yaml), "--recipe", "STK_T",
            "--overwrite"]
    check(bool(recorded) and recorded[-1] == want,
          f"(4) the Process tab's Build stack recorded {recorded[-1] if recorded else None}")

    # ---------------------------------------------------------------- (5)
    tab.select_recipe("STK_H")
    pump(app, 0.1)
    check(not tab.build_button.isEnabled(), "(5) Build archive is disabled for STK_H, a band recipe")
    tab.select_recipe("STK_EREF")
    pump(app, 0.1)
    check(not tab.use_button.isEnabled(), f"(5) Use in Process is disabled for STK_EREF: {tab.use_button.toolTip()!r}")
    tab.select_recipe("STK_T")
    pump(app, 0.2)
    check(tab.build_button.isEnabled(), "(5) Build archive is enabled for the saved STK_T")
    tab.build_button.click()
    pump(app, 0.1)
    want = [state.python_exe, state.script("build_stack.py"), str(state.survey_yaml), "--recipe", "STK_T",
            "--overwrite"]
    check(bool(recorded) and recorded[-1] == want, f"(5) Build archive recorded {recorded[-1] if recorded else None}")
    check("STK_T" in process._stack_jobs.values(), f"(5) ProcessTab._stack_jobs holds STK_T: {process._stack_jobs}")
    QTest.keyClicks(tab.form.notes_edit, "edited")
    pump(app, 0.1)
    check(not tab.build_button.isEnabled(), "(5) Build archive is disabled for STK_T with an unsaved edit")
    tab.select_recipe("STK_H")
    pump(app, 0.1)
    check("unsaved edits to STK_T dropped" in tab.status_label.text(),
          f"(5) choosing STK_H says the edit to STK_T is dropped: {tab.status_label.text()!r}")
    tab.select_recipe("STK_T")  # back to the saved recipe
    pump(app, 0.1)

    # ---------------------------------------------------------------- (6)
    t_recipe = stacks.load_recipe(survey, "STK_T")
    process.select_station("M1")
    pump(app, 0.2)
    window.tabs.setCurrentWidget(tab)
    tab.use_button.click()
    pump(app, 0.3)
    window_text = (t_recipe.start.strftime("%Y-%m-%d %H:%M"), t_recipe.end.strftime("%Y-%m-%d %H:%M"))
    check(builder.recipe() is not None and builder.recipe().name == "STK_T"
          and process.window_bar.window_text() == window_text,
          f"(6) Use in Process chose {builder.recipe().name if builder.recipe() else None} with window "
          f"{process.window_bar.window_text()}")
    check(process.remote_combo.currentData() != "STK_T",
          f"(6) STK_T is not made the remote of M1, its member: remote {process.remote_combo.currentData()}, "
          f"status {process.status_label.text()!r}")
    check(window.tabs.currentWidget() is process, "(6) Use in Process brings the Process tab forward")
    process.select_station("L")
    pump(app, 0.2)
    window.tabs.setCurrentWidget(tab)
    tab.select_recipe("STK_T")
    pump(app, 0.1)
    tab.use_button.click()
    pump(app, 0.3)
    check(process.remote_combo.currentData() == "STK_T", f"(6) STK_T is made the remote of L: "
                                                         f"{process.remote_combo.currentData()}")
    process.select_station("M1")  # a station change keeps the remote unless it holds the new station
    pump(app, 0.2)
    check(process.remote_combo.currentData() != "STK_T" and "STK_T holds M1" in process.status_label.text(),
          f"(6) selecting the station M1 drops STK_T as the remote: remote {process.remote_combo.currentData()}, "
          f"status {process.status_label.text()!r}")
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("STK_T"))  # chosen by hand
    pump(app, 0.1)
    jobs_before, boxes_before = len(runner.jobs), len(BOXES)
    queued = process.queue_process()
    warned = BOXES[boxes_before:]
    check(queued is None and len(runner.jobs) == jobs_before and warned == [("warning", "Remote")],
          f"(6) Add to queue with M1 and STK_T refuses: argv {queued}, jobs {jobs_before} -> {len(runner.jobs)}, "
          f"boxes {warned}")
    del BOXES[boxes_before:]  # the one warning (11) expects
    process.select_station("L")
    pump(app, 0.2)
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("R"))
    pump(app, 0.2)
    window.tabs.setCurrentWidget(tab)
    tab.select_recipe("STK_EBASE")
    pump(app, 0.1)
    tab.use_button.click()
    pump(app, 0.3)
    start, end = process.window_bar.window_text()
    check(builder.intersite_button.isEnabled(),
          f"(6) Queue intersite is enabled for STK_EBASE: {builder.hint.text()!r}")
    builder.intersite_button.click()
    pump(app, 0.1)
    want = [state.python_exe, state.script("process_intersite.py"), str(state.survey_yaml), "L", start, end,
            "--kind", "telluric", "--remote", "R", "--stack", "STK_EBASE"]
    check(bool(recorded) and recorded[-1] == want, f"(6) Queue intersite recorded {recorded[-1] if recorded else None}")
    check(runner.jobs[-1].kind == "processing" and runner.jobs[-1].status == "queued",
          f"(6) the job is queued as processing: {runner.jobs[-1].kind}, {runner.jobs[-1].status}")
    res = dry_run(recorded[-1])
    check(res.returncode == 0 and "base_stack_recipe: STK_EBASE" in res.stdout,
          f"(6) the recorded command line dry runs: exit {res.returncode} "
          f"{(res.stderr.strip().splitlines() or [''])[-1][:160]!r}")
    builder.select_recipe("STK_EB2")
    pump(app, 0.1)
    hint = builder.hint.text().splitlines()[0]
    check(not builder.intersite_button.isEnabled() and hint.startswith(
        "R would sit in STK_EB2's base stack and be the reference"),
          f"(6) Queue intersite is disabled for STK_EB2 with R as the remote: {hint!r}")
    same = stacks.intersite_argv(state.python_exe, state.script("process_intersite.py"), str(state.survey_yaml),
                                 "L", "telluric", ["STK_EB2"], remote="R", start=start, end=end)
    res = dry_run(same)
    check(res.returncode == 2 and "--allow-shared-members" in res.stderr,
          f"(6) control: process_intersite refuses that command line: exit {res.returncode} "
          f"{(res.stderr.strip().splitlines() or [''])[-1][:160]!r}")
    builder.select_recipe("STK_EQ")  # Q a member at 0.5 h; its record ends at 00:35, inside the bar's window
    pump(app, 0.1)
    eq_hint = builder.hint.text().splitlines()[0]
    check(not builder.intersite_button.isEnabled()
          and eq_hint.startswith("STK_EQ's membership changes inside the window")
          and "Q ends at 2024-03-01 00:34" in eq_hint,
          f"(6) Queue intersite is disabled for STK_EQ, naming Q's end: {eq_hint!r}")
    same = stacks.intersite_argv(state.python_exe, state.script("process_intersite.py"), str(state.survey_yaml),
                                 "L", "telluric", ["STK_EQ"], remote="R", start=start, end=end)
    res = dry_run(same)
    check(res.returncode == 2 and "membership changes inside the window" in res.stderr and "Q ends" in res.stderr,
          f"(6) control: process_intersite refuses STK_EQ's command line: exit {res.returncode} "
          f"{(res.stderr.strip().splitlines() or [''])[-1][:200]!r}")
    builder.select_recipe("STK_EQA")
    pump(app, 0.1)
    check(builder.intersite_button.isEnabled(),
          f"(6) Queue intersite is enabled for STK_EQA (member_change: allow): {builder.hint.text()!r}")
    ebw_bar = process.window_bar.window_text()  # put back below, for what follows
    builder.select_recipe("STK_EBW")  # declares 00:00-01:00
    process.window_bar.set_window("2024-03-01 00:10", "2024-03-01 00:50")
    pump(app, 0.1)
    replaces = "the bar's window replaces STK_EBW's declared window (2024-03-01 00:00 to 2024-03-01 01:00)"
    ebw_lines = builder.hint.text().splitlines()
    ebw_argv = builder.intersite_argv()
    check(replaces in ebw_lines and ebw_argv is not None
          and ebw_argv[4:6] == ["2024-03-01 00:10", "2024-03-01 00:50"],
          f"(6) STK_EBW at the bar's 00:10-00:50: the hint says the bar's window replaces the declared one and "
          f"the command line takes the bar's: {ebw_lines}, {ebw_argv[4:6] if ebw_argv else None}")
    ebw_res = dry_run(ebw_argv) if ebw_argv else None
    ebw_out = ebw_res.stdout if ebw_res is not None else ""
    check(ebw_res is not None and ebw_res.returncode == 0
          and "window: 2024-03-01T00:10:00Z to 2024-03-01T00:50:00Z" in ebw_out
          and "recipe_window: 2024-03-01T00:00:00Z to 2024-03-01T01:00:00Z (the command line's is used)" in ebw_out,
          f"(6) STK_EBW's command line dry runs on the bar's window and logs the declared one: exit "
          f"{ebw_res.returncode if ebw_res is not None else None} "
          f"{[x for x in ebw_out.splitlines() if x.startswith(('window:', 'recipe_window:'))]}")
    process.window_bar.set_window("2024-03-01 00:00", "2024-03-01 01:00")
    pump(app, 0.1)
    ebw_lines = builder.hint.text().splitlines()
    check(builder.intersite_button.isEnabled() and not any("replaces" in x for x in ebw_lines),
          f"(6) STK_EBW at its declared 00:00-01:00: no hint line says replaces: {ebw_lines}")
    builder.select_recipe("STK_EBASE")
    process.window_bar.set_window("2024-03-01 00:10", "2024-03-01 00:50")
    pump(app, 0.1)
    ebw_lines = builder.hint.text().splitlines()
    check(builder.intersite_button.isEnabled() and not any("replaces" in x for x in ebw_lines),
          f"(6) STK_EBASE (no declared window) at 00:10-00:50: no hint line says replaces: {ebw_lines}")
    process.window_bar.set_window(*ebw_bar)
    pump(app, 0.1)
    check(process.window_bar.window_text() == ebw_bar,
          f"(6) the bar's window is put back: {process.window_bar.window_text()}")
    builder.select_recipe("STK_EBASE")
    builder.set_pair("L", "S1")  # a survey.yaml site at 1 Hz (not in the remote list: it has no raw folder)
    check(not builder.intersite_button.isEnabled() and "1 Hz" in builder.hint.text().splitlines()[0],
          f"(6) Queue intersite is disabled for the remote S1 at 1 Hz: {builder.hint.text().splitlines()[0]!r}")
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("M4"))
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("R"))  # the pair again, through the tab
    pump(app, 0.1)
    builder.select_recipe("STK_EREF")
    pump(app, 0.1)
    check(not builder.intersite_button.isEnabled(), f"(6) Queue intersite is disabled for STK_EREF: "
                                                    f"{builder.hint.text().splitlines()[0]!r}")
    builder.select_recipe("STK_EBASE")
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("STK_T"))
    pump(app, 0.2)
    check(not builder.intersite_button.isEnabled(), f"(6) Queue intersite is disabled with the remote STK_T: "
                                                    f"{builder.hint.text().splitlines()[0]!r}")
    process.remote_combo.setCurrentIndex(process.remote_combo.findData("R"))
    pump(app, 0.1)

    # ---------------------------------------------------------------- (7), (9)
    window.tabs.setCurrentWidget(tab)
    tab.select_recipe("STK_H")
    state.set_site("L")
    pump(app, 0.3)
    row_l = next(r for r in tab.chart.rows() if r.site == "L")
    tree = availability_model.tree_window_at(row_l.runs["all"], row_l.rate, row_l.runs["all"][0][0])
    results: list = []
    tab.check.ready.connect(results.append)
    state.set_selection("L", *tree)
    wait_until(app, lambda: bool(results), 240, "the member check's result")
    pump(app, 0.3)
    res = tab.check.result()
    if res is not None:
        flagged = {key for key, marks in res.flags.items() if "reversed" in marks}
        check(("P", "hx") in flagged, f"(7) the check flags P reversed on hx: flagged {sorted(flagged)}; "
                                      f"members {res.members}")
        tab.grab().save(str(shots / "gui_stacks_check.png"))
    check(not state.archive_lock.busy,
          f"(7) the archive lock is free after the check: holder {state.archive_lock.holder}")
    kept = tab.check.kept_sites()
    window.tabs.setCurrentWidget(process)
    pump(app, 0.2)
    check(bool(kept) and tab.check.kept_sites() == [],
          f"(9) hiding the tab drops the arrays: {len(kept)} sites held before, {tab.check.kept_sites()} after")
    reads: list[str] = []
    real_load = segment.load_segment

    def counting_load(path, survey_name, station, *args, **kwargs):
        reads.append(station)
        return real_load(path, survey_name, station, *args, **kwargs)

    segment.load_segment = counting_load
    budget = stacks_tab_module.AUTO_CHECK_SAMPLES
    stacks_tab_module.AUTO_CHECK_SAMPLES = 1  # every member set is over the budget: reads wait for Check
    try:
        window.tabs.setCurrentWidget(tab)
        pump(app, 1.5)
        check(not reads and "press Check" in tab.check.status.text(),
              f"(7) over the read budget no member read starts without Check: reads {reads}, "
              f"{tab.check.status.text()!r}")
        results.clear()
        tab.check_button.click()
        wait_until(app, lambda: bool(results), 240, "the check after the Check click")
        check(sorted(reads) == ["M1", "M2", "M3", "M4", "P"], f"(7) Check reads the five members: {sorted(reads)}")
    finally:
        stacks_tab_module.AUTO_CHECK_SAMPLES = budget
    reads.clear()
    try:
        tab.form.rate_combo.setCurrentIndex(tab.form.rate_combo.findData(1.0))
        pump(app, 1.5)
        status = tab.status_label.text()
        check(not reads, f"(7) with a 1 Hz recipe and the 100 Hz segment no member read starts: {reads}")
        check("100 Hz" in status and "1 Hz" in status, f"(7) the status line names both rates: {status!r}")
    finally:
        segment.load_segment = real_load
    tab.form.rate_combo.setCurrentIndex(tab.form.rate_combo.findData(100.0))
    tab.select_recipe("STK_T")
    tab.select_recipe("STK_H")  # back to the saved STK_H, its local L
    pump(app, 0.3)

    # ---------------------------------------------------------------- (8)
    row_m = next(r for r in tab.chart.rows() if r.site == "M1")
    when = pd.Timestamp(row_m.runs["all"][0][0] + 600 * 10**9, tz="UTC")
    local_before = tab.local()
    tab.chart.bar_clicked.emit("M1", when)
    pump(app, 0.3)
    rows = {r.site: r for r in tab.chart.rows()}
    check(state.site == "M1", f"(8) the bar click selects M1: state.site {state.site}")
    check(tab.local() == local_before == "L", f"(8) the local stays L: {local_before} -> {tab.local()}")
    check(rows["L"].reason == "the local" and rows["M1"].reason != "the local",
          f"(8) 'the local' stays on L: L {rows['L'].reason!r}, M1 {rows['M1'].reason!r}")
    check(window.tabs.currentWidget() is window.timeseries_tab, "(8) the Time Series tab is brought forward")

    # ---------------------------------------------------------------- (12)
    window.tabs.setCurrentWidget(tab)
    tab.select_recipe("STK_H")
    pump(app, 0.3)
    lines = ["# 30,000 masks for the cost check of stacks_tab_unit (12)"]
    sites = ("L", "M1", "M2", "M3", "M4", "P", "Q", "R")
    for site in sites:
        lines.append(f"{site}:")
        for k in range(3750):  # 0.5 s masks every 1.12 s over the 70 min
            a = T0 + pd.Timedelta(seconds=1.12 * k)
            lines += [f"- start: '{a:%Y-%m-%dT%H:%M:%S.%f}Z'",
                      f"  end: '{a + pd.Timedelta(seconds=0.5):%Y-%m-%dT%H:%M:%S.%f}Z'",
                      "  bands: all" if k % 2 else "  bands: [0.1, 10.0]", "  found_by: time"]
    (yaml_path.parent / "masks.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    loads: list[int] = []
    real_read_masks = availability._read_masks

    def counting_read_masks(*args, **kwargs):
        loads.append(1)
        return real_read_masks(*args, **kwargs)

    availability._read_masks = counting_read_masks
    try:
        tab.chart.refresh()
        wait_until(app, lambda: all(len(tab.chart._masks.get(s) or ()) == 3750 for s in sites), 240,
                   "the 30,000 masks to load")
        pump(app, 0.3)
        costs = []
        for k in range(5):
            tic = time.perf_counter()
            tab.form.reject_spin.setValue(26.0 + k)
            costs.append(time.perf_counter() - tic)
        median = statistics.median(costs) * 1e3
        check(median < 50.0, f"(12) a form edit with 30,000 masks takes {median:.1f} ms (median of five; under "
                             f"50 ms): {[round(c * 1e3, 1) for c in costs]}")
        loaded = len(loads)
        window.tabs.setCurrentWidget(process)
        pump(app, 0.2)
        window.tabs.setCurrentWidget(tab)
        pump(app, 0.5)
        check(len(loads) == loaded, f"(12) hiding and showing the tab loads no masks again ({loaded} -> {len(loads)})")
    finally:
        availability._read_masks = real_read_masks

    # ---------------------------------------------------------------- (11)
    runner.reset()
    starts: list[float] = []
    real_thread = availability.ReadThread

    class CountingThread(real_thread):
        """A ReadThread that notes when it starts."""

        def start(self, *args):
            starts.append(time.time())
            return super().start(*args)

    availability.ReadThread, batch = CountingThread, availability.BATCH
    availability.BATCH = 1  # one archive per batch, so batches are pending at wait()
    try:
        for path in (Path(state.survey.workspace) / "mth5").glob("*.h5"):
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))  # every archive stale
        tab.chart.refresh()
        tab.chart.rows()
        wait_until(app, lambda: tab.chart._thread is not None, 10, "a chart read in flight")
        pending = tab.chart.reads_pending()
        tab.wait()
        waited = time.time()
        pump(app, 1.0)
        after = [t for t in starts if t > waited]
        check(pending > 1 and not after, f"(11) after tab.wait() with {pending} reads pending, {len(after)} read "
                                         f"thread(s) started")
    finally:
        availability.ReadThread, availability.BATCH = real_thread, batch
    started = time.time()
    window.close()
    took = time.time() - started
    pump(app, 0.2)
    check(took <= 30.0, f"(11) window.close() returned in {took:.1f} s")
    check(not BOXES, f"(11) no modal message box but the warning of (6): {BOXES}")
    check(not SLOT_ERRORS, f"(11) no Qt slot raised: {SLOT_ERRORS}")
    real_after = real_state()
    changed = [p for p in real_after if real_after[p] != real_before[p]]
    check(not changed, f"(11) no stacks.yaml appeared or changed in {len(REAL_SURVEYS)} real survey folders: "
                       f"{changed}")
    print(f"     fetches recorded, not run: {len(FETCHES)}; shots in {shots}")
    if failures:
        print(f"\nFAIL  stacks_tab_unit ({len(failures)} failure(s))")
        sys.exit(1)
    print(f"\nPASS  stacks_tab_unit ({time.time() - begun:.0f} s)")


if __name__ == "__main__":
    main()
