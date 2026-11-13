# -*- coding: utf-8 -*-
"""
Unit test for the Processing type choice of the Process tab (run headless)

The test writes a scratch survey at 100 Hz from the synthetic fields of
tests/intersite_unit.py, whose telluric tensor of L on B is known. L, B, R,
S1 and S2 record one hour from 2024-03-01 00:00; X records ten minutes from
01:10, after the others have ended; HO holds hx and hy alone, over the
first ten minutes; D1 is an archive whose entry declares 10 Hz; N0 is a raw
folder with no archive; LB and BB are burst sites (24000 Hz); STK_T.h5 is
an archive with no survey.yaml entry. Its stacks.yaml holds the base
recipes STK_EB (E), STK_HB (H) and STK_E10 (E at 10 Hz) and the reference
recipe STK_ER.

`JobRunner.run_now` is replaced before the window is built (the basemap
fetch is recorded, not run), the QMessageBox statics are replaced by
recorders, `runner.add` is wrapped to record each queued command line, and
a `sys.excepthook` collects exceptions raised in Qt slots. Queued jobs
wait, except in criterion 8, where one telluric job runs through the job
runner into the scratch workspace. Command lines are also given to the
script with --dry-run, which writes nothing. tests/gui_smoke.py keeps
process_intersite.py in its never-run list; this test is where the window
runs it.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/process_type_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (MT as before) the Processing type box does not hold, in order, "MT
   impedance and tipper", "Telluric tensor, E to E" and "Magnetic tensor, B
   to B" with the first chosen; or, with MT, the Base label, the Base box
   or "Add every site on this base" is visible; or Add to queue for L with
   remote R queues other than `[python, process_rr.py, survey.yaml, L, R,
   start, end]`, or with the tag t1 and the filters switch off other than
   that line plus `--no-filters --tag=t1`;
2. (the function and the script) `stacks.pair_argv` for L on B with remote
   R does not return exactly `[python, process_intersite.py, survey.yaml,
   L, B, start, end, --kind, telluric, --remote, R]`, or with a tag and
   without filters that line plus `--tag t1 --no-filters`, or without a
   window the line without start and end; or it refuses a window that the
   three sites cover in part (00:30 to 01:15), or a magnetic pair on HO;
   or the script's dry run of any of these exits other than 0; or, for
   each of these, it returns a command line, or a message that does not
   name the fault and say after a colon what to do: the local equal to the
   base, the remote equal to the local or to the base, a base with no
   survey.yaml entry, the stack archive STK_T as the remote, a base or a
   local with no archive, a base or a remote at another sample rate, a
   burst site as the base of a continuous pair, a telluric base holding
   no ex or ey, a base or a local that records nothing in the window, a
   window that ends before it starts, and no window for sites that share
   no time; or the script, given the same sites and window by
   `stacks.intersite_argv`, dry runs any of them with an exit code other
   than 2;
3. (the Base box and the run options) with "Telluric tensor, E to E" and
   station L the Base label, the Base box or the star button stays hidden,
   or the Base box lists other than B, R, S1, S2, X, HO and "stack:
   STK_EB": L itself, N0 (no archive), D1 (10 Hz), a burst site, STK_T,
   or a recipe of the other field, of another rate or of use reference;
   or a base is chosen before the user chooses one, or Add to queue or
   the star button is enabled without one; or "Magnetic tensor, B to B"
   lists a stack other than "stack: STK_HB"; or station LB lists other
   than BB; or, with a tensor type, the tag or the filters switch is
   disabled, or any other run option is enabled or shows a tooltip other
   than `RunOptions.TENSOR_TIP`; or back at MT any run option is left
   disabled or without the tooltip it had;
4. (one pair) with telluric, L, base B, remote R and the window 00:00 to
   00:40, Add to queue queues other than the line of criterion 2, or with
   the tag t1 and the filters switch off other than that line plus `--tag
   t1 --no-filters`; or the job is not a queued "processing" job whose row
   reads station L, remote R, the window and options naming the tensor
   and the base; or the same press with "Magnetic tensor, B to B" queues
   a line without `--kind magnetic`;
5. (refusals shown) Add to queue queues a job, or opens no warning box
   whose text names the fault, for: base R with remote R; the remote
   STK_T; the remote D1; the base X; the station N0; the station LB on
   base BB with remote R; a window typed with its end before its start;
   or the script's dry run of the same sites and window exits other than
   2 for any of them; or, while another reader holds `State.archive_lock`,
   Add to queue queues a job or opens no box saying an archive is being
   read, or with the lock free again it does not queue;
6. (the star) with base B, remote R and the window 00:00 to 00:40, "Add
   every site on this base" queues other than L, S1 and S2 for the
   telluric type (the base B, the remote R, X outside the window, HO
   without ex and ey, or a site with no archive or at another rate), or
   other than L, S1, S2 and HO for the magnetic type; or a queued line is
   not that site's line of criterion 2; or the status line is not the
   count of the runs queued, then X and HO (telluric) or X alone
   (magnetic) each under its reason, then the queued-jobs notice and
   nothing else (the base or the remote named as left out, for one); or
   the script's dry run exits other than 0 for a queued line or other
   than 2 for X's and HO's;
7. (a base stack) with the base "stack: STK_EB", Add to queue queues
   other than `[python, process_intersite.py, survey.yaml, L, start, end,
   --kind, telluric, --remote, R, --stack, STK_EB, --tag, t1]`, or that
   line's dry run exits other than 0; or with the filters switch off it
   queues a job, opens no box naming use_filters, or the script accepts
   the line with --no-filters (exit other than 2); or the star button is
   enabled with a base stack;
8. (a real run) the queued telluric job of L on B, started through the
   job runner, does not finish "done" with exit code 0; or its products
   are not L_te-B_rr-R.csv, .json, .h5 and .png in the scratch workspace's
   tf folder; or the tensor read from the CSV the job wrote, whatever its
   name, fails `intersite_unit.recovery` against the model tensor (more
   than 5 % of element-bands beyond 3 sigma, any beyond 5 sigma, or the
   timing check off +2 ms or -1.5 deg); or the sidecar does not record
   kind telluric, local L, base_site B and remote R; or the Products list
   does not hold the four files, the CSV and the figure among them; or
   "Show in View EDIs" is enabled on one of them;
9. a Qt slot raised, or a message box other than the warnings of
   criteria 5 and 7 was opened.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import intersite_unit as iu  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite, stacks  # noqa: E402
from mt_workbench.gui import theme  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from mt_workbench.gui.stack_builder import RunOptions  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

SCRATCH = scratch_dir("process_type_unit")
FS = iu.FS2
T0 = iu.T_START
MINUTES = 60
START, END = "2024-03-01 00:00", "2024-03-01 00:40"
TYPES = ["MT impedance and tipper", "Telluric tensor, E to E", "Magnetic tensor, B to B"]
STACKS_YAML = """STK_EB:
  field: E
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]

STK_HB:
  field: H
  use: base
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [R]

STK_E10:
  field: E
  use: base
  method: band_mean
  sample_rate: 10.0
  members: rule

STK_ER:
  field: E
  use: reference
  method: band_mean
  sample_rate: 100.0
  members: rule
"""

failures: list[str] = []
SLOT_ERRORS: list[str] = []
BOXES: list[tuple[str, str, str]] = []
FETCHES: list[list[str]] = []
_real_run_now = JobRunner.run_now


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def _recording_run_now(self, label, argv, **details):
    """Record a fetch_basemap.py job instead of starting it."""
    argv = [str(a) for a in argv]
    if any(Path(a).name == "fetch_basemap.py" for a in argv):
        FETCHES.append(argv)
        return -1
    return _real_run_now(self, label, argv, **details)


def _box(kind: str):
    def record(parent, title, text, *args, **kwargs):
        BOXES.append((kind, str(title), str(text)))
        return QMessageBox.Ok
    return staticmethod(record)


def _slot_error(kind, value, tb) -> None:
    """Record an exception raised in a Qt slot, and print it: an error in main() lands here too."""
    SLOT_ERRORS.append(f"{kind.__name__}: {value}")
    traceback.print_exception(kind, value, tb)


JobRunner.run_now = _recording_run_now
for _kind in ("warning", "critical", "information", "question"):
    setattr(QMessageBox, _kind, _box(_kind))
sys.excepthook = _slot_error


# ------------------------------------------------------------------ fixture


def write_h_only(work: Path, site: str, spec: dict, n: int) -> None:
    """Write an archive holding hx and hy alone, n samples from the start, as counts with no filter chain."""
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    chans = [ChannelTS(channel_type="magnetic",
                       data=np.rint(np.fft.irfft(spec[f"s1_{c}"] * spec["scale"], spec["n"])[:n]).astype("int32"),
                       channel_metadata={"magnetic": {"component": c, "sample_rate": FS,
                                                      "time_period.start": T0.isoformat()}})
             for c in ("hx", "hy")]
    m = MTH5(file_version="0.2.0")
    m.open_mth5(work / "mth5" / f"{site}.h5", mode="w")
    try:
        m.add_survey("SYNTH")
        station = m.add_station(site, survey="SYNTH")
        run = RunTS(chans, run_metadata={"id": "sr100_0001", "sample_rate": FS}, station_metadata={"id": site})
        station.add_run("sr100_0001").from_runts(run)
    finally:
        m.close_mth5()


def build_survey() -> Path:
    """Write the scratch survey of the module docstring; return its survey.yaml."""
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    raw, work = root / "raw", root / "work"
    raw.mkdir(parents=True)
    spec = iu.fields(FS, MINUTES / 60.0, seed=7, h_sites=("l", "b", "r", "s1", "s2", "x"))
    # one factor on every channel (the tensor is unchanged) so the int32 counts are large
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    short = int(600 * FS)
    for site in ("L", "B", "R", "S1", "S2"):
        iu.write_site(work, site, spec, T0, spec["n"])
    iu.write_site(work, "X", spec, T0 + pd.Timedelta(minutes=70), short)
    for site in ("D1", "LB", "BB"):  # never read as samples: any ten minutes will do
        alias = dict(spec, **{f"{site.lower()}_{c}": spec[f"s1_{c}"] for c in ("ex", "ey", "hx", "hy")})
        iu.write_site(work, site, alias, T0, short)
    for site in ("HO", "STK_T"):
        write_h_only(work, site, spec, short)
    (raw / "N0").mkdir()
    (raw / "N0" / f"{int(T0.timestamp())}.B423").write_bytes(b"")
    lines = ["name: SYNTH", "instrument: lemi423", "sample_rate: 100", f"data_root: {raw.as_posix()}",
             f"workspace: {work.as_posix()}", "defaults:", "  channels: [ex, ey, hx, hy]", "sites:",
             "  L: {latitude: -31.0, longitude: 137.0, remote: R}"]
    for k, site in enumerate(("B", "R", "S1", "S2", "X", "N0", "HO")):
        lines.append(f"  {site}: {{latitude: -31.{k + 1}, longitude: 137.{k + 1}}}")
    lines += ["  D1: {latitude: -31.8, longitude: 137.8, sample_rate: 10}",
              "  LB: {bursts_of: L, sample_rate: 24000}", "  BB: {bursts_of: B, sample_rate: 24000}",
              "processing:", "  min_period: 0.04", "  max_period: 200.0", "  periods_per_decade: 10.0"]
    (root / "survey.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "stacks.yaml").write_bytes(STACKS_YAML.encode("utf-8"))
    return root / "survey.yaml"


# ------------------------------------------------------------------ helpers


def dry_run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a command line with --dry-run (the script writes no file)."""
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    return subprocess.run(list(argv) + ["--dry-run"], capture_output=True, text=True, cwd=REPO, env=env)


def dry_runs(lines: dict) -> dict:
    """Dry run several command lines at once; return {label: (exit code, the last line of stderr)}."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        done = dict(zip(lines, pool.map(dry_run, lines.values())))
    return {label: (res.returncode, (res.stderr.strip().splitlines() or [""])[-1][:140])
            for label, res in done.items()}


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


def choose(combo, data) -> None:
    """Choose a combo entry by its data."""
    index = combo.findData(data)
    if index < 0:
        raise AssertionError(f"{data!r} is not listed among {[combo.itemData(i) for i in range(combo.count())]}")
    combo.setCurrentIndex(index)


def settle(app, window) -> None:
    """Pump until no background read holds the archive lock, so a press is judged at once."""
    pump(app, 0.2)
    wait_until(app, lambda: not window.state.archive_lock.busy, 30, "the archive lock to be free")
    pump(app, 0.05)


def says(why: str, *words: str) -> bool:
    """True when a refusal names every word before its colon and says what to do after it."""
    fault, _colon, advice = why.partition(": ")
    return all(word in fault for word in words) and len(advice) > 10


# ------------------------------------------------------------------ the test


def function_and_script(py: str, script: str, yaml_path: str) -> None:
    """Criterion 2: `stacks.pair_argv` against literal command lines and against the script's dry run."""
    head = [py, script, yaml_path]
    line = head + ["L", "B", START, END, "--kind", "telluric", "--remote", "R"]
    got = stacks.pair_argv(py, script, yaml_path, "L", "B", "telluric", "R", START, END)
    check(got == (line, ""), f"(2) pair_argv L on B, remote R: {got[0][3:] if got[0] else got}")
    got = stacks.pair_argv(py, script, yaml_path, "L", "B", "telluric", "R", START, END, tag="t1", no_filters=True)
    check(got == (line + ["--tag", "t1", "--no-filters"], ""), f"(2) with a tag and without filters: {got[0][-3:]}")
    got = stacks.pair_argv(py, script, yaml_path, "L", "B", "telluric", "R")
    check(got == (head + ["L", "B", "--kind", "telluric", "--remote", "R"], ""), f"(2) without a window: {got[0][3:]}")
    part = ("2024-03-01 00:30", "2024-03-01 01:15")
    # label: (local, base, kind, remote, start, end, words of the fault; None for a line the script takes)
    cases = {
        "valid": ("L", "B", "telluric", "R", START, END, None),
        "valid, no window": ("L", "B", "telluric", "R", None, None, None),
        "valid, a window covered in part": ("L", "B", "telluric", "R", *part, None),
        "valid, magnetic on HO": ("L", "HO", "magnetic", "R", "2024-03-01 00:00", "2024-03-01 00:05", None),
        "local = base": ("L", "L", "telluric", "R", START, END, ("station", "base", "both L")),
        "remote = local": ("L", "B", "telluric", "L", START, END, ("remote L", "is the station")),
        "remote = base": ("L", "B", "telluric", "B", START, END, ("remote B", "is the base")),
        "base with no entry": ("L", "ZZ", "telluric", "R", START, END, ("base ZZ", "no entry")),
        "remote a stack archive": ("L", "B", "telluric", "STK_T", START, END, ("remote STK_T", "no survey.yaml")),
        "base with no archive": ("L", "N0", "telluric", "R", START, END, ("base N0", "no archive")),
        "local with no archive": ("N0", "B", "telluric", "R", START, END, ("station", "no archive")),
        "base at 10 Hz": ("L", "D1", "telluric", "R", START, END, ("100 Hz", "base D1", "10 Hz")),
        "remote at 10 Hz": ("L", "B", "telluric", "D1", START, END, ("100 Hz", "remote D1", "10 Hz")),
        "a burst base": ("L", "BB", "telluric", "R", START, END, ("burst", "base BB")),
        "telluric base without ex, ey": ("L", "HO", "telluric", "R", START, END, ("base HO", "ex, ey")),
        "base outside the window": ("L", "X", "telluric", "R", START, END, ("base X", "records nothing")),
        "local outside the window": ("L", "B", "telluric", "R", "2024-03-01 02:00", "2024-03-01 03:00",
                                     ("station", "records nothing")),
        "window reversed": ("L", "B", "telluric", "R", END, START, ("window", "ends")),
        "no shared time": ("L", "X", "telluric", "R", None, None, ("base X", "share no recording time")),
    }
    lines = {label: stacks.intersite_argv(py, script, yaml_path, c[0], c[2], [], base=c[1], remote=c[3], start=c[4],
                                          end=c[5]) for label, c in cases.items()}
    exits = dry_runs(lines)
    for label, (local, base, kind, remote, start, end, words) in cases.items():
        argv, why = stacks.pair_argv(py, script, yaml_path, local, base, kind, remote, start, end)
        code, last = exits[label]
        if words is None:
            check(argv == lines[label] and why == "" and code == 0,
                  f"(2) {label}: pair_argv builds the line ({why!r}) and its dry run exits {code} {last!r}")
        else:
            check(argv is None and says(why, *words), f"(2) {label}: pair_argv refuses, saying what to do: {why!r}")
            check(code == 2, f"(2) {label}: the script refuses the same line: exit {code} {last!r}")


def main() -> None:
    """Criteria 1-9, in the order the tab is driven."""
    print(__doc__.split("**This test fails if**")[1].rstrip())
    begun = time.time()
    yaml_path = build_survey()
    print(f"     scratch survey written in {time.time() - begun:.1f} s: {yaml_path}")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow(survey_yaml=yaml_path)
    window.resize(1500, 1000)
    window.show()
    state, tab = window.state, window.process_tab
    window.tabs.setCurrentWidget(tab)
    pump(app, 0.3)
    runner, options, bar = state.runner, tab.options, tab.window_bar
    py, script, survey_yaml = state.python_exe, state.script("process_intersite.py"), str(state.survey_yaml)
    head = [py, script, survey_yaml]
    recorded: list[list[str]] = []
    real_add, real_run = runner.add, runner.run_queue

    def record(label, argv, **details):
        recorded.append([str(a) for a in argv])
        return real_add(label, argv, **details)

    runner.add, runner.run_queue = record, (lambda: None)

    def press(button) -> tuple[list[list[str]], list[tuple[str, str, str]]]:
        """Click a button once no read holds the lock; return the lines it queued and the boxes it opened."""
        settle(app, window)
        jobs, boxes = len(recorded), len(BOXES)
        button.click()
        pump(app, 0.05)
        opened = BOXES[boxes:]
        del BOXES[boxes:]
        return recorded[jobs:], opened

    def set_type(kind: str | None) -> None:
        """Choose the processing type by its place in the box (criterion 1 checks the order)."""
        tab.type_combo.setCurrentIndex([None, "telluric", "magnetic"].index(kind))

    def pair(station: str, base: str | None, remote: str, kind: str | None = "telluric", window=(START, END)):
        """Choose the type, the station, the remote, the base and the window on the tab."""
        set_type(kind)
        tab.select_station(station)
        pump(app, 0.05)
        choose(tab.remote_combo, remote)
        if base is not None:
            choose(tab.base_combo, base)
        bar.set_window(*window)
        pump(app, 0.05)

    function_and_script(py, script, survey_yaml)

    # ---------------------------------------------------------------- (1)
    texts = [tab.type_combo.itemText(i) for i in range(tab.type_combo.count())]
    check(texts == TYPES and tab.type_combo.currentIndex() == 0, f"(1) the types {texts}, the first chosen")
    tab.select_station("L")
    pump(app, 0.2)
    check(tab.remote_combo.currentData() == "R", f"(1) L's declared remote R is chosen: "
                                                 f"{tab.remote_combo.currentData()}")
    bar.set_window(START, END)
    pump(app, 0.05)
    hidden = [w.isVisible() for w in (tab.base_label, tab.base_combo, tab.star_button)]
    check(not any(hidden), f"(1) with MT the Base label, the Base box and the star button are hidden: {hidden}")
    rr_only = {"engine": options.engine_combo, "min period": options.min_spin, "max period": options.max_spin,
               "per decade": options.decade_spin, "notch": options.notch_edit, "window samples": options.window_spin,
               "min bin": options.min_bin_spin, "min band windows": options.floor_spin, "masks": options.masks_check,
               "estimator": options.advanced}
    both = {"tag": options.tag_edit, "filters": options.filters_check}
    at_mt = {name: (w.isEnabled(), w.toolTip()) for name, w in {**rr_only, **both}.items()}
    rr_line = [py, state.script("process_rr.py"), survey_yaml, "L", "R", START, END]
    queued, boxes = press(tab.add_button)
    check(queued == [rr_line] and not boxes, f"(1) MT queues process_rr as before: {[q[1:] for q in queued]}")
    options.tag_edit.setText("t1")
    options.filters_check.setChecked(False)
    queued, boxes = press(tab.add_button)
    check(queued == [rr_line + ["--no-filters", "--tag=t1"]] and not boxes,
          f"(1) MT with the tag and without filters: {[q[7:] for q in queued]}")
    options.tag_edit.clear()
    options.filters_check.setChecked(True)

    # ---------------------------------------------------------------- (3)
    set_type("telluric")
    pump(app, 0.1)
    shown = [w.isVisible() for w in (tab.base_label, tab.base_combo, tab.star_button)]
    check(all(shown), f"(3) a tensor type shows the Base label, the Base box and the star button: {shown}")
    listed = [tab.base_combo.itemText(i) for i in range(tab.base_combo.count())]
    check(listed == ["B", "R", "S1", "S2", "X", "HO", "stack: STK_EB"], f"(3) telluric, station L: the Base box "
                                                                         f"lists {listed}")
    check(tab.base_combo.currentIndex() == -1 and not tab.add_button.isEnabled()
          and not tab.star_button.isEnabled() and "Choose a base" in tab.status_label.text(),
          f"(3) no base is chosen for the user and neither button is enabled: index "
          f"{tab.base_combo.currentIndex()}, status {tab.status_label.text()!r}")
    off = {name: (w.isEnabled(), w.toolTip() == RunOptions.TENSOR_TIP) for name, w in rr_only.items()}
    on = {name: w.isEnabled() for name, w in both.items()}
    check(all(v == (False, True) for v in off.values()) and all(on.values()),
          f"(3) a tensor type disables the other run options with the tooltip saying why, and keeps the tag and "
          f"the filters switch: wrong {[n for n, v in off.items() if v != (False, True)]}, {on}")
    set_type("magnetic")
    pump(app, 0.1)
    listed = [tab.base_combo.itemText(i) for i in range(tab.base_combo.count())]
    check(listed == ["B", "R", "S1", "S2", "X", "HO", "stack: STK_HB"], f"(3) magnetic, station L: {listed}")
    tab.select_station("LB")
    pump(app, 0.1)
    listed = [tab.base_combo.itemText(i) for i in range(tab.base_combo.count())]
    check(listed == ["BB"], f"(3) station LB (a burst site at 24000 Hz): the Base box lists {listed}")
    tab.select_station("L")
    set_type(None)
    pump(app, 0.2)
    back = {name: (w.isEnabled(), w.toolTip()) for name, w in {**rr_only, **both}.items()}
    check(back == at_mt, f"(3) back at MT every run option is as it was: differing "
                         f"{[n for n in at_mt if back[n] != at_mt[n]]}")

    # ---------------------------------------------------------------- (4)
    line = head + ["L", "B", START, END, "--kind", "telluric", "--remote", "R"]
    pair("L", "B", "R")
    queued, boxes = press(tab.add_button)
    check(queued == [line] and not boxes, f"(4) telluric L on B, remote R: queued {[q[3:] for q in queued]}")
    job = runner.jobs[-1]
    check(job.kind == "processing" and job.status == "queued" and (job.station, job.remote) == ("L", "R")
          and job.window == f"{START} to {END}" and "telluric tensor" in job.options and "base B" in job.options,
          f"(4) the queue row: {job.station}, {job.remote}, {job.window!r}, {job.options!r}, {job.status}")
    options.tag_edit.setText("t1")
    options.filters_check.setChecked(False)
    queued, boxes = press(tab.add_button)
    check(queued == [line + ["--tag", "t1", "--no-filters"]] and not boxes,
          f"(4) with the tag and without filters: {[q[-3:] for q in queued]}")
    options.tag_edit.clear()
    options.filters_check.setChecked(True)
    pair("L", "B", "R", kind="magnetic")
    queued, boxes = press(tab.add_button)
    check(queued == [head + ["L", "B", START, END, "--kind", "magnetic", "--remote", "R"]] and not boxes,
          f"(4) the magnetic type queues a magnetic run: {[q[3:] for q in queued]}")

    # ---------------------------------------------------------------- (5)
    # label: (station, base, remote, window, words of the warning)
    refusals = {
        "base R with remote R": ("L", "R", "R", (START, END), ("remote R", "is the base")),
        "the remote STK_T": ("L", "B", "STK_T", (START, END), ("remote STK_T", "no survey.yaml")),
        "the remote D1": ("L", "B", "D1", (START, END), ("remote D1", "10 Hz")),
        "the base X": ("L", "X", "R", (START, END), ("base X", "records nothing")),
        "the station N0": ("N0", "B", "R", (START, END), ("station", "no archive")),
        "the station LB on BB": ("LB", "BB", "R", (START, END), ("burst",)),
        "a window ending before its start": ("L", "B", "R", (END, START), ("window", "end after the start")),
    }
    lines = {label: stacks.intersite_argv(py, script, survey_yaml, c[0], "telluric", [], base=c[1], remote=c[2],
                                          start=c[3][0], end=c[3][1]) for label, c in refusals.items()}
    exits = dry_runs(lines)
    for label, (station, base, remote, win, words) in refusals.items():
        pair(station, base, remote, window=win)
        queued, boxes = press(tab.add_button)
        text = boxes[0][2] if boxes else ""
        check(not queued and len(boxes) == 1 and boxes[0][0] == "warning" and all(w in text for w in words)
              and ": " in text, f"(5) {label}: nothing queued and one warning says why: {text!r}")
        check(exits[label][0] == 2, f"(5) {label}: the script refuses the same line: exit {exits[label][0]} "
                                    f"{exits[label][1]!r}")
    pair("L", "B", "R")
    settle(app, window)
    holder = object()
    state.archive_lock.acquire(holder)
    jobs, opened = len(recorded), len(BOXES)
    tab.add_button.click()
    pump(app, 0.05)
    text = BOXES[opened][2] if len(BOXES) > opened else ""
    del BOXES[opened:]
    check(len(recorded) == jobs and "being read" in text, f"(5) while a reader holds the archive lock nothing "
                                                          f"is queued and the box says so: {text!r}")
    state.archive_lock.release(holder)
    queued, boxes = press(tab.add_button)
    check(queued == [line] and not boxes, f"(5) with the lock free again the pair is queued: {len(queued)} line(s)")

    # ---------------------------------------------------------------- (6)
    def site_line(site: str, kind: str) -> list[str]:
        return head + [site, "B", START, END, "--kind", kind, "--remote", "R"]

    out_x = (f"1 left out (X): the station records nothing in the window {START} to {END}: move the window, or "
             f"choose another site")
    out_ho = "1 left out (HO): the station holds no run with ex, ey: choose another site"
    for kind, want, note in (
            ("telluric", ["L", "S1", "S2"], f"3 telluric tensor run(s) queued on base B | {out_x} | {out_ho}"),
            ("magnetic", ["L", "S1", "S2", "HO"], f"4 magnetic tensor run(s) queued on base B | {out_x}")):
        pair("S1", "B", "R", kind=kind)
        queued, boxes = press(tab.star_button)
        check(queued == [site_line(s, kind) for s in want] and not boxes,
              f"(6) {kind}: the star on base B queues {[q[3] for q in queued]} (expected {want})")
        status = tab.status_label.text()
        rest = status[len(note):]
        check(status.startswith(note) and rest.startswith(" | ") and rest.endswith("job(s) queued - press Run queue")
              and rest.count(" | ") == 1,
              f"(6) {kind}: the status line holds the count, each site left out under its reason, then the "
              f"queued-jobs notice: {status!r}")
    exits = dry_runs({site: site_line(site, "telluric") for site in ("L", "S1", "S2", "X", "HO")})
    check([exits[s][0] for s in ("L", "S1", "S2")] == [0, 0, 0] and [exits[s][0] for s in ("X", "HO")] == [2, 2],
          f"(6) the script takes the three queued lines and refuses X's and HO's: "
          f"{ {s: v[0] for s, v in exits.items()} }")

    # ---------------------------------------------------------------- (7)
    pair("L", "stack: STK_EB", "R")
    options.tag_edit.setText("t1")
    stack_line = head + ["L", START, END, "--kind", "telluric", "--remote", "R", "--stack", "STK_EB", "--tag", "t1"]
    queued, boxes = press(tab.add_button)
    check(queued == [stack_line] and not boxes, f"(7) L on stack: STK_EB: queued {[q[3:] for q in queued]}")
    check(not tab.star_button.isEnabled(), "(7) the star button is disabled with a base stack")
    options.filters_check.setChecked(False)
    queued, boxes = press(tab.add_button)
    text = boxes[0][2] if boxes else ""
    check(not queued and len(boxes) == 1 and "use_filters" in text and "tick" in text,
          f"(7) the filters switch off against STK_EB's use_filters: nothing queued, the box says {text!r}")
    options.filters_check.setChecked(True)
    options.tag_edit.clear()
    exits = dry_runs({"stack": stack_line, "no filters": stack_line + ["--no-filters"]})
    check(exits["stack"][0] == 0 and exits["no filters"][0] == 2,
          f"(7) the script takes the stack line and refuses it with --no-filters: {exits}")

    # ---------------------------------------------------------------- (8)
    runner.reset()
    recorded.clear()
    pair("L", "B", "R")
    queued, boxes = press(tab.add_button)
    check(queued == [line] and len(runner.jobs) == 1, f"(8) one telluric job queued: {len(runner.jobs)}")
    tf = Path(state.survey.workspace) / "tf"
    shutil.rmtree(tf, ignore_errors=True)
    started = time.time()
    real_run()
    wait_until(app, lambda: runner.jobs[0].status in ("done", "failed"), 300, "the telluric job")
    pump(app, 0.3)
    job = runner.jobs[0]
    if not check(job.status == "done" and job.exit_code == 0,
                 f"(8) the job ran through the job runner: {job.status}, exit {job.exit_code}, "
                 f"{time.time() - started:.0f} s"):
        print("\n".join(job.output[-25:]))
    stem = "L_te-B_rr-R"
    files = sorted(p.name for p in tf.glob("*")) if tf.exists() else []
    check(files == sorted(f"{stem}{s}" for s in (".csv", ".h5", ".json", ".png")), f"(8) products in tf: {files}")
    for csv in sorted(tf.glob("*.csv"))[:1]:  # judged whatever its name: a run of the wrong sites gives another tensor
        fmap, _scheme = iu.model_bands(yaml_path)
        est, letter = intersite.read_csv(csv)
        got = iu.recovery(est, fmap, iu.A, iu.PHI0_DEG, iu.TAU_S, "8 the tensor of the queued job", report=False)
        check(letter == "T" and got["elements_ok"] and got["timing_ok"],
              f"(8) the model tensor is recovered: {got['beyond3']} of {got['n']} element-bands beyond 3 sigma, "
              f"{got['beyond5']} beyond 5, worst {got['worst']:.2f}; tau {got['tau']} ms (model "
              f"{iu.TAU_S * 1e3:+.1f}), intercept {got['intercept']} deg (model {iu.PHI0_DEG:+.1f})")
        side = json.loads(csv.with_suffix(".json").read_text(encoding="utf-8"))
        facts = {k: side.get(k) for k in ("kind", "local", "base_site", "remote")}
        check(facts == {"kind": "telluric", "local": "L", "base_site": "B", "remote": "R"}, f"(8) sidecar: {facts}")
    want = [tf / f"{stem}{s}" for s in (".csv", ".json", ".h5", ".png")]
    check(tab.products == want, f"(8) the Products list holds the four files: {[p.name for p in tab.products]}")
    rows = []
    for row in range(tab.product_panel.list.count()):
        tab.product_panel.list.setCurrentRow(row)
        rows.append(tab.show_button.isEnabled())
    check(rows == [False] * 4, f"(8) Show in View EDIs is disabled on each tensor file: {rows}")

    # ---------------------------------------------------------------- (9)
    runner.add, runner.run_queue = real_add, real_run
    runner.reset()
    window.close()
    pump(app, 0.2)
    check(not BOXES, f"(9) no message box but the warnings of (5) and (7): {BOXES}")
    check(not SLOT_ERRORS, f"(9) no Qt slot raised: {SLOT_ERRORS}")
    print(f"     fetches recorded, not run: {len(FETCHES)}")
    if failures:
        print(f"\nFAIL  process_type_unit ({len(failures)} failure(s))")
        sys.exit(1)
    print(f"\nPASS  process_type_unit ({time.time() - begun:.0f} s)")


if __name__ == "__main__":
    main()
