# -*- coding: utf-8 -*-
"""
Unit test for the Stacks tab's availability chart (run headless)

Survey A holds 60 sites, S01-S60, at 1000 Hz with no archives, a
basemap.json (so no fetch starts) and a masks.yaml with one all-band mask
on S01. Survey B holds L, L2 and M1-M5 at 1000 Hz with empty placeholder
archives; their runs come from a stand-in for
`availability_model.read_runs`, which the chart's read threads call. From
2024-01-10 00:00 UTC: M1, M2 and M3 0-12 h, M4 0-24 h, M5 12-24 h, L 12-17 h
and 19-24 h (the second half of the candidates' span) and L2 30-34 h,
where no candidate records. A `State` opens each survey and an
`AvailabilityChart` is driven as the Stacks tab drives it, with a band
recipe (H, base, rule) and no window of its own. The masks.yaml parse of
survey A is held in its worker thread by a stand-in for
`masks_reader.read_document` that waits on an event, as
tests/crosspower_masks_wait_unit.py holds it. `AvailabilityChart._compute`,
`availability._read_masks` and os.stat are wrapped to count their calls.

The sequence runs once on the module as it is, then once per mutation
below, each monkeypatched before its run and restored after it; a mutation
passes this test when none of the clauses named beside it fails.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/availability_chart_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. while the parse is held, `AvailabilityChart._compute` runs;
2. while the parse is held, os.stat is called on any site's archive path;
3. while the parse is held, the status lacks "waiting for masks.yaml to be parsed" or `rows()` is not empty;
4. within 10 s of the release, the rows are not one per site in `availability_model.group_rows` order;
5. then S01's row does not hold its one mask, `_read_masks` ran other than once, or the parses are not 1;
6. then the status says waiting, or the pass stats fewer than 60 archive paths (the control of 2);
7. at 900 x 400 and at 900 x 900 a row gets under 14 px, or the rows shown are not min(60, floor(h / 14));
8. after a manual range change, a resize back to 900 x 400 moves the y range;
9. survey B opened and `reload()` called, before any pass, the no-archive set is not empty (60 just before);
10. with local L, the default window is not inside L's record, or the status says "records nothing";
11. with local L2, the window is not 00:00-12:00 (the fall back) or the status lacks "L2 records nothing";
12. with the window set to 02:00-08:00 and local L, the status lacks "L records nothing in the window";
13. setting the recipe and local L again then moves that window;
14. survey A opened again and drawn before its first pass, the curve or the status still shows survey B's;
15. a Qt slot raised;
16. the mutation ROW_PX = 8 fails no check of 7;
17. the mutation `_rows_in_view` returning MAX_ROWS fails no check of 7;
18. the mutation `resizeEvent` without the refit fails no check of 7;
19. the mutation `_flush` without the wait for the parse fails no check of 1, 2 or 3;
20. the mutation `_view_moved` doing nothing fails no check of 8;
21. the mutation `_default_window` moving a chosen window fails no check of 13.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import stacks  # noqa: E402
from mt_workbench.gui import availability, masks_reader  # noqa: E402
from mt_workbench.gui import availability_model as model  # noqa: E402
from mt_workbench.gui.app import State  # noqa: E402
from mt_workbench.masks import masks_path  # noqa: E402

SCRATCH = scratch_dir("availability_chart_unit")
WAITING = "waiting for masks.yaml to be parsed"
SITES_A = [f"S{i:02d}" for i in range(1, 61)]
T0 = pd.Timestamp("2024-01-10 00:00", tz="UTC")
PROCESSING = {"min_period": 0.005, "max_period": 5000.0, "periods_per_decade": 10.0,
              "notch_frequencies": [50.0, 150.0]}
MASKS_A = {"S01": [{"start": "2024-01-01T00:00:00Z", "end": "2024-01-01T01:00:00Z", "bands": "all",
                    "reason": "the one mask", "found_by": "time"}]}
RECIPE = {"field": "H", "use": "base", "method": "band_mean", "sample_rate": 1000, "members": "rule"}


def at(hours: float) -> int:
    """Return T0 plus `hours` as ns since the epoch."""
    return int(T0.value + round(hours * 3.6e12))


RUNS_B = {"M1": [(at(0), at(12))], "M2": [(at(0), at(12))], "M3": [(at(0), at(12))],
          "M4": [(at(0), at(24))], "M5": [(at(12), at(24))],
          "L": [(at(12), at(17)), (at(19), at(24))], "L2": [(at(30), at(34))]}

SLOT_ERRORS: list[str] = []
COMPUTES: list[float] = []
MASK_LOADS: list[float] = []
STATS: list[str] = []  # normalised paths of the os.stat calls ending in .h5, from any thread


def _record_slot_error(exc_type, exc, tb) -> None:
    """Record an exception raised inside a Qt slot (PySide6 prints it instead of raising)."""
    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.stderr.write(SLOT_ERRORS[-1])


def _norm(path) -> str:
    """Return a path as an absolute, case-folded string."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


_real_stat = os.stat


def _counting_stat(path, *args, **kwargs):
    """os.stat that records each path ending in .h5 it is called with."""
    if isinstance(path, (str, os.PathLike)) and os.fspath(path).endswith(".h5"):
        STATS.append(_norm(path))
    return _real_stat(path, *args, **kwargs)


_real_compute = availability.AvailabilityChart._compute
_real_read_masks = availability._read_masks
_real_read_runs = model.read_runs


def _counted_compute(self):
    """`AvailabilityChart._compute`, counted."""
    COMPUTES.append(time.time())
    return _real_compute(self)


def _counted_read_masks(*args):
    """`availability._read_masks`, counted."""
    MASK_LOADS.append(time.time())
    return _real_read_masks(*args)


def _fake_read_runs(path, site: str, survey_name: str) -> dict:
    """Stand-in for `availability_model.read_runs`: survey B's runs, every channel in every run."""
    runs = list(RUNS_B[site])
    return {"all": runs, "H": list(runs), "E": list(runs), "dc": {}}


# ------------------------------------------------------------------ mutations


def _flush_without_wait(self) -> None:
    """Mutant of `_flush`: the pass runs while masks.yaml is parsed."""
    if not self._dirty or self._closing:
        return
    self._dirty = False
    self._flush_timer.stop()
    self._compute()


def _resize_without_refit(self, event) -> None:
    """Mutant of `resizeEvent`: no refit of the rows to the new height."""
    QWidget.resizeEvent(self, event)


def _default_window_moving_choice(self, window_ns) -> None:
    """Mutant of `_default_window`: a chosen window is moved like a default one."""
    window_ns = window_ns or self._extent
    if window_ns is not None and tuple(window_ns) != self._window_ns():
        self._set_region(window_ns[0] / 1e9, window_ns[1] / 1e9)


# (name, clauses that must fail, [(object, attribute, value)])
MUTATIONS = [
    ("ROW_PX = 8", {7}, [(availability, "ROW_PX", 8)]),
    ("_rows_in_view returning MAX_ROWS", {7},
     [(availability.AvailabilityChart, "_rows_in_view", lambda self: availability.MAX_ROWS)]),
    ("resizeEvent without the refit", {7}, [(availability.AvailabilityChart, "resizeEvent", _resize_without_refit)]),
    ("_flush without the wait for the parse", {1, 2, 3},
     [(availability.AvailabilityChart, "_flush", _flush_without_wait)]),
    ("_view_moved doing nothing", {8}, [(availability.AvailabilityChart, "_view_moved", lambda self, *a: None)]),
    ("_default_window moving a chosen window", {13},
     [(availability.AvailabilityChart, "_default_window", _default_window_moving_choice)]),
]


# ------------------------------------------------------------------ fixture


def write_survey(folder: Path, name: str, sites, archives: bool, masks: dict | None) -> Path:
    """Write a survey.yaml at 1000 Hz with its workspace and basemap.json; return its path.

    Args:
        folder (Path): The survey's folder, emptied first.
        name (str): Survey name.
        sites (iterable of str): Its sites.
        archives (bool): Write an empty placeholder archive per site.
        masks (dict | None): The masks.yaml document, None for no file.

    Returns:
        Path: survey.yaml.
    """
    if folder.exists():
        shutil.rmtree(folder)
    mth5 = folder / "work" / "mth5"
    mth5.mkdir(parents=True)
    (folder / "work" / "basemap.json").write_text("{}", encoding="utf-8")
    if archives:
        for site in sites:
            (mth5 / f"{site}.h5").write_bytes(b"")
    survey = {"name": name, "instrument": "lemi423", "sample_rate": 1000, "timezone": "UTC",
              "data_root": str(folder / "no_drive"), "workspace": str(folder / "work"),
              "processing": PROCESSING, "sites": {s: {} for s in sites}}
    survey_yaml = folder / "survey.yaml"
    survey_yaml.write_text(yaml.safe_dump(survey, sort_keys=False), encoding="utf-8")
    if masks is not None:
        masks_path(survey_yaml).write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")
    return survey_yaml


def pump(app: QApplication, until, seconds: float = 10.0) -> bool:
    """Process Qt events until `until()` is true or `seconds` pass; return `until()`."""
    end = time.time() + seconds
    while not until() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return until()


def view(chart) -> tuple[float, int, tuple[float, float]]:
    """Return the plot's view box height in px, the rows its y range shows, and the y range."""
    box = chart.plot.getViewBox()
    lo, hi = box.viewRange()[1]
    return box.sceneBoundingRect().height(), int(round(hi - lo)), (float(lo), float(hi))


def text(window) -> str:
    """Return a window of two UTC Timestamps as text."""
    return "None" if window is None else " to ".join(f"{w:%Y-%m-%d %H:%M}" for w in window)


# ------------------------------------------------------------------ the sequence


def run(app: QApplication, label: str, verbose: bool) -> dict[int, list[str]]:
    """Run clauses 1-15 on fresh surveys under <scratch>/<label>.

    Args:
        app (QApplication): The application.
        label (str): Folder name of this run's surveys.
        verbose (bool): Print a PASS or FAIL line per check.

    Returns:
        dict[int, list[str]]: The messages of the failed checks, per clause.
    """
    failed: dict[int, list[str]] = {}

    def check(clause: int, ok: bool, msg: str) -> None:
        if verbose:
            print(("PASS " if ok else "FAIL ") + f"{clause}. {msg}")
        if not ok:
            failed.setdefault(clause, []).append(msg)

    yaml_a = write_survey(SCRATCH / label / "a", "chart_unit_a", SITES_A, False, MASKS_A)
    yaml_b = write_survey(SCRATCH / label / "b", "chart_unit_b", list(RUNS_B), True, None)
    COMPUTES.clear()
    MASK_LOADS.clear()
    errors_before = len(SLOT_ERRORS)
    release, started = threading.Event(), threading.Event()
    parse = masks_reader.read_document

    def held(target):
        started.set()
        release.wait(30.0)
        return parse(target)

    masks_reader.read_document = held
    state = State(REPO)
    chart = availability.AvailabilityChart(state)
    try:
        # (1-6) the pass waits for the masks.yaml parse
        state.open_survey(yaml_a, fetch_basemap=False)
        archives = {_norm(state.archive_path(s)) for s in SITES_A}
        first_stat = len(STATS)
        chart.reload()
        held_ok = started.wait(10.0)
        pump(app, lambda: False, 0.5)  # the flush timer has had its turns
        rows = chart.rows()
        status = chart.status.text()
        n_compute = len(COMPUTES)
        n_stat = sum(p in archives for p in STATS[first_stat:])
        check(1, held_ok and n_compute == 0, f"parse held ({held_ok}): {n_compute} passes (want 0)")
        check(2, n_stat == 0, f"parse held: {n_stat} stats of archive paths (want 0)")
        check(3, WAITING in status and rows == [], f"parse held: status {status!r}, {len(rows)} rows (want 0)")
        mark = len(STATS)
        release.set()
        order = [s for _, names in model.group_rows(state.survey.site_names(), lambda s: None, []) for s in names]

        def s01_masks():
            row = next((r for r in chart.rows() if r.site == "S01"), None)
            return None if row is None else row.masks

        landed = pump(app, lambda: bool(s01_masks()) and not chart._waiting_masks, 10.0)
        rows = chart.rows()
        status = chart.status.text()
        n_stat = sum(p in archives for p in STATS[mark:])
        check(4, [r.site for r in rows] == order and len(order) == 60,
              f"released (landed within 10 s: {landed}): {len(rows)} rows in group_rows order: "
              f"{[r.site for r in rows] == order}")
        check(5, len(s01_masks() or []) == 1 and len(MASK_LOADS) == 1 and state.masks_reader.parses == 1,
              f"S01 holds {len(s01_masks() or [])} mask (want 1), masks loaded {len(MASK_LOADS)} times (want 1), "
              f"{state.masks_reader.parses} parses (want 1)")
        check(6, WAITING not in status and n_stat >= 60,
              f"status {status!r}; the pass after the release stats {n_stat} archive paths (want >= 60)")

        # (7-8) the default view's rows are at least ROW_PX high
        for height in (400, 900):
            chart.resize(900, height)
            chart.show()
            pump(app, lambda: False, 0.5)
            h, shown, _ = view(chart)
            want = min(60, math.floor(h / 14))
            check(7, shown > 0 and h / shown >= 14 and shown == want,
                  f"at 900 x {height}: view box {h:.0f} px, {shown} rows shown, "
                  f"{h / shown if shown else math.nan:.1f} px per row (want {want} rows, >= 14 px)")
        box = chart.plot.getViewBox()
        box.setYRange(5.5, 20.5, padding=0)
        box.sigRangeChangedManually.emit(box.state["mouseEnabled"])
        _, _, before = view(chart)
        chart.resize(900, 400)
        pump(app, lambda: False, 0.5)
        _, _, after = view(chart)
        check(8, all(abs(a - b) < 1e-6 for a, b in zip(before, after)),
              f"after a manual range change and a resize: y range {after} (was {before})")

        # (9) a survey change forgets the last survey's sites with no archive
        stale = len(chart._no_archive)
        state.open_survey(yaml_b, fetch_basemap=False)
        chart.reload()
        check(9, stale == 60 and chart._no_archive == set(),
              f"survey B, before its first pass: no-archive set of {len(chart._no_archive)} (want 0; "
              f"{stale} just before)")

        # (10-13) the default window and the local
        recipe = stacks.Recipe.from_mapping("STK_B", RECIPE)
        chart.set_recipe(recipe, local="L")
        settled = pump(app, lambda: chart.reads_pending() == 0 and all(r.runs is not None for r in chart.rows()))
        window = chart.window()
        status = chart.status.text()
        lo, hi = RUNS_B["L"][0][0], RUNS_B["L"][-1][1]
        inside = window is not None and lo <= window[0].value < window[1].value <= hi
        check(10, settled and inside and "records nothing" not in status,
              f"local L (record 12:00-24:00): default window {text(window)}, status {status!r}")
        chart.set_recipe(recipe, local="L2")
        window = chart.window()
        status = chart.status.text()
        busiest = (T0, T0 + pd.Timedelta(hours=12))
        check(11, window == busiest and "L2 records nothing in the window" in status,
              f"local L2 (record 30:00-34:00): window {text(window)} (want {text(busiest)}), status {status!r}")
        chart.set_recipe(recipe, local="L")
        chosen = (T0 + pd.Timedelta(hours=2), T0 + pd.Timedelta(hours=8))
        chart.set_window(*chosen)
        window = chart.window()
        status = chart.status.text()
        check(12, window == chosen and "L records nothing in the window" in status,
              f"window set to {text(chosen)}: window {text(window)}, status {status!r}")
        chart.set_recipe(recipe, local="L")
        window = chart.window()
        check(13, window == chosen, f"the recipe and local L set again: window {text(window)} "
                                    f"(want {text(chosen)})")

        # (14) a draw before the first pass of the next survey
        x_b, y_b = chart.curve.getData()
        points_b = 0 if y_b is None else len(y_b)
        status_b = chart.status.text()
        state.open_survey(yaml_a, fetch_basemap=False)
        chart.reload()
        chart.set_night("22:00-04:00")  # draws now, before any pass
        x_a, y_a = chart.curve.getData()
        points = 0 if y_a is None else len(y_a)
        status = chart.status.text()
        check(14, points_b > 0 and "members" in status_b and points == 0 and "members" not in status,
              f"survey A drawn before its first pass: curve {points} points (survey B's {points_b}), "
              f"status {status!r} (survey B's {status_b!r})")
    finally:
        release.set()
        masks_reader.read_document = parse
        state.masks_reader.wait()
        chart.wait()
        chart.close()
        app.processEvents()
    check(15, len(SLOT_ERRORS) == errors_before, f"{len(SLOT_ERRORS) - errors_before} Qt slot errors")
    return failed


def main() -> int:
    """Run the sequence on the module as it is, then once per mutation; return 0 on success."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    sys.excepthook = _record_slot_error
    app = QApplication.instance() or QApplication(sys.argv)
    os.stat = _counting_stat
    availability.AvailabilityChart._compute = _counted_compute
    availability._read_masks = _counted_read_masks
    model.read_runs = _fake_read_runs
    problems = []
    try:
        failed = run(app, "module", verbose=True)
        problems += [f"{clause}. {msg}" for clause, msgs in sorted(failed.items()) for msg in msgs]
        print()
        for number, (name, clauses, patches) in enumerate(MUTATIONS, 16):
            saved = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
            for obj, attr, value in patches:
                setattr(obj, attr, value)
            try:
                tripped = run(app, f"mutation_{number}", verbose=False)
            finally:
                for obj, attr, value in saved:
                    setattr(obj, attr, value)
            hit = sorted(clauses & set(tripped))
            first = tripped[hit[0]][0] if hit else f"failed clauses {sorted(tripped)}"
            ok = bool(hit)
            print(("PASS " if ok else "FAIL ") + f"{number}. mutation {name} trips {hit or sorted(clauses)}: {first}")
            if not ok:
                problems.append(f"{number}. mutation {name} trips none of {sorted(clauses)}")
    finally:
        os.stat = _real_stat
        availability.AvailabilityChart._compute = _real_compute
        availability._read_masks = _real_read_masks
        model.read_runs = _real_read_runs
    print()
    if problems:
        print(f"{len(problems)} FAILED:")
        for line in problems:
            print("  " + line)
        return 1
    print("PASS  availability_chart_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
