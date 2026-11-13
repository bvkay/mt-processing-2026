# -*- coding: utf-8 -*-
"""
Unit test for the "apply masks.yaml" switch and the band controls of the Process tab

Runs headless. A scratch copy of curnamona_cube's survey.yaml, filters.yaml
and reference_edis.yaml gets its own masks.yaml with MASKS[D02] and
MASKS[E08] entries. The copy's workspace points at the real work folder,
which the test only reads; the test also checks that the real survey folder
still holds no masks.yaml at the end. `MainWindow` is built on the copy, the
Process tab is selected and the switch is read back. The band layout and
floor controls (window samples, min bin, min band windows) are read on the
copy as it is (no `window`, `min_bin` or `min_band_windows` in its
`processing:` block) and again after the copy's block gains all three and
the survey is reopened; the block is then put back.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/process_tab_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** with station D02 and remote E08 the switch does not
read exactly "apply masks.yaml (D02: 3, E08: 2)" (the masks process_rr
applies from each site: D02's own, duplicates in the file collapsed as
`load_masks` does, and E08's two of scope both), ticked and enabled,
with a tooltip naming the Cross-powers tab and the remote; `RunOptions.flags`
holds --no-masks while it is ticked, or lacks it once unticked, or the
process_rr argv the tab queues lacks it then; with the engine combo on
"mantle" and the switch ticked the flags are not exactly `--no-masks
--engine mantle` (in that order, the queued argv ending the same way), the
switch and the aurora estimator block are not disabled, the status line
lacks "engine mantle" or "--no-masks is passed (D02: 3, E08: 2)", the queue
label does not start "process_rr D02 rr-E08 [mantle]", or back on "aurora"
the flags are not empty with the switch enabled and ticked and the status
line free of the engine note; a remote change to A07 (no
masks) does not make the label "(D02: 3, A07: 0)"; station A02 with remote
A03 (neither has masks) does not leave the switch disabled and ticked again
(it was unticked on the pair before) reading "apply masks.yaml (no masks
declared)" with no --no-masks in the flags even when unticked, and D02
against E08 afterwards does not come back ticked; reopening the survey
after E08 gains a mask does not make the label "(D02: 3, E08: 3)" for D02 against E08 and re-tick it; a mask saved
while the tab is hidden does not show when the tab is shown again; an
unreadable masks.yaml does not read exactly "apply masks.yaml (masks.yaml
unreadable)" with the parser's message in the tooltip only, or the tooltip
keeps it once the file is fixed; the stack STK_E08u as remote is not left
out of the label ("(D02: 4)"); with data_root pointed at a folder that does
not exist (the data drive unplugged) D02 against E08 does not still read
"(D02: 3, E08: 2)"; E08 gaining a mask of scope local changes that label;
E08 gaining a mask of scope remote does not make it "(D02: 3, E08: 3)", or
D02 gaining one, or E08 one of scope both naming ey alone (the remote
contributes H only), changes it; the Cross-powers tab's list of E08's masks
does not show the columns "channels" and "scope" with "ey" and "both" on
the ey entry, "all" and "remote" on the remote-scoped one; or any Qt slot
raised.

The band controls. **This test also fails if**, on the copy without the
keys, window samples, min bin and min band windows do not start at 128,
0 shown as "layout's own" and 2 (`MIN_BAND_WINDOWS`) with no flag; moving
each one alone does not add exactly its own flag (`--window-samples 256`,
`--min-bin 12`, `--min-band-windows 5`), or the queued argv and the queue
label lack them; under "mantle" the min band windows control is not
disabled, `--min-band-windows` is still passed, or window samples or min
bin is disabled or drops its flag; `reload` does not put all three back
with no flag; after the block gains `window: 256`, `min_bin: 10` and
`min_band_windows: 5` the controls do not start at 256, 10 and 5 with no
flag, or min bin set to 0 does not read "layout's own" and pass
`--min-bin 0`, or min band windows set to 2 does not pass
`--min-band-windows 2`. Mutations that trip it: the floor flag emitted
under MANTLE, a default read from `MIN_BAND_WINDOWS` alone (the survey's
5 then passes a flag), or "layout's own" taken as no flag over the
survey's min_bin.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402

SURVEY_DIR = REPO / "surveys" / "curnamona_cube"
WORK = SURVEY_DIR / "work"
SCRATCH = scratch_dir("process_tab_unit")


def _mask(start: str, end: str, bands="all", reason="test", scope: str | None = None) -> dict:
    """Build one masks.yaml entry found by "time"; `scope` is left out when None."""
    out = {"start": start, "end": end, "bands": bands, "reason": reason, "found_by": "time"}
    return out if scope is None else {**out, "scope": scope}


# D02: three masks, one of them written twice (load_masks keeps it once); E08: two of scope both, the
# masks it gives a pair as the remote
MASKS = {
    "D02": [_mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z"),
            _mask("2021-06-29T08:00:00Z", "2021-06-29T08:30:00Z", [0.01, 0.1]),
            _mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z"),
            _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z")],
    "E08": [_mask("2021-06-29T09:00:00Z", "2021-06-29T09:15:00Z", scope="both"),
            _mask("2021-06-29T12:00:00Z", "2021-06-29T12:05:00Z", [1.0, 10.0], scope="both")],
}
EXTRA_E08 = _mask("2021-06-30T03:00:00Z", "2021-06-30T03:30:00Z", scope="both")
LOCAL_E08 = _mask("2021-06-30T05:00:00Z", "2021-06-30T05:30:00Z", reason="E08 ey", scope="local")
REMOTE_E08 = _mask("2021-06-30T06:00:00Z", "2021-06-30T06:30:00Z", reason="E08 as a remote", scope="remote")
REMOTE_D02 = _mask("2021-06-30T07:00:00Z", "2021-06-30T07:30:00Z", reason="D02 as a remote", scope="remote")
EY_E08 = {**_mask("2021-06-30T08:00:00Z", "2021-06-30T08:30:00Z", reason="E08 ey only", scope="both"),
          "channels": ["ey"]}

# run_now records the argv of a job the window would start at once (a basemap fetch) instead of starting it
STARTED: list[list[str]] = []
JobRunner.run_now = lambda self, label, argv, **details: STARTED.append([str(a) for a in argv]) or -1

SLOT_ERRORS: list[str] = []


def _record_slot_error(exc_type, exc, tb) -> None:
    """Record an exception raised inside a Qt slot.

    PySide6 prints such an exception instead of raising it; `main` fails at
    the end when any were recorded.
    """
    import traceback

    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.stderr.write(SLOT_ERRORS[-1])


sys.excepthook = _record_slot_error


def make_survey_copy(masks: dict) -> Path:
    """Copy the survey files to the scratch folder and write their masks.yaml.

    Args:
        masks (dict): Masks by site, written as the copy's masks.yaml.

    Returns:
        Path: The copy's survey.yaml, its workspace set to the real work
        folder.
    """
    for name in ("survey.yaml", "filters.yaml", "reference_edis.yaml"):
        shutil.copy2(SURVEY_DIR / name, SCRATCH / name)
    copy_yaml = SCRATCH / "survey.yaml"
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    config["workspace"] = str(WORK)
    copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    write_masks(masks)
    return copy_yaml


def write_masks(masks: dict) -> None:
    """Write the scratch masks.yaml."""
    (SCRATCH / "masks.yaml").write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")


def pump(app: QApplication, seconds: float = 0.1) -> None:
    """Process Qt events for `seconds`."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def set_remote(tab, name: str) -> None:
    """Select a remote in the tab's remote combo box by its data."""
    index = tab.remote_combo.findData(name)
    assert index >= 0, f"{name} is not a remote choice"
    tab.remote_combo.setCurrentIndex(index)


def set_processing(copy_yaml: Path, extra: dict | None) -> None:
    """Add `extra` to the copy's `processing:` block, or take the three band-control keys out when None."""
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    block = {k: v for k, v in (config.get("processing") or {}).items()
             if k not in ("window", "min_bin", "min_band_windows")}
    config["processing"] = {**block, **(extra or {})}
    copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")


def check_band_controls(app, window, tab, copy_yaml: Path) -> None:
    """Check the window samples, min bin and min band windows controls; leave D02 rr E08 selected on the copy."""
    from mt_workbench.process import MIN_BAND_WINDOWS

    options = tab.options
    win, low, floor = options.window_spin, options.min_bin_spin, options.floor_spin
    assert (win.value(), low.value(), floor.value()) == (128, 0.0, MIN_BAND_WINDOWS) and MIN_BAND_WINDOWS == 2, \
        (win.value(), low.value(), floor.value())
    assert low.text() == "layout's own", low.text()
    assert options.flags() == [], options.flags()
    for spin, value, want in ((win, 256, ["--window-samples", "256"]), (low, 12.0, ["--min-bin", "12"]),
                              (floor, 5, ["--min-band-windows", "5"])):
        start = spin.value()
        spin.setValue(value)
        assert options.flags() == want, (want, options.flags())
        spin.setValue(start)
    win.setValue(256)
    low.setValue(12.0)
    floor.setValue(5)
    flags = options.flags()
    assert flags == ["--window-samples", "256", "--min-bin", "12", "--min-band-windows", "5"], flags
    argv = tab.queue_process()
    label = tab.runner.jobs[-1].label
    assert argv is not None and argv[-6:] == flags, argv
    assert label.endswith(" ".join(flags)), label
    print(f"  band controls: 128, layout's own, {MIN_BAND_WINDOWS} with no flag; each moved alone passes its own "
          f"flag; all three queued: label {label!r}")

    options.engine_combo.setCurrentText("mantle")
    pump(app)
    assert not floor.isEnabled() and win.isEnabled() and low.isEnabled(), \
        (floor.isEnabled(), win.isEnabled(), low.isEnabled())
    flags = options.flags()
    assert "--min-band-windows" not in flags, flags
    assert flags[:4] == ["--window-samples", "256", "--min-bin", "12"] and flags[-2:] == ["--engine", "mantle"], flags
    options.engine_combo.setCurrentText("aurora")
    pump(app)
    assert floor.isEnabled() and "--min-band-windows" in options.flags(), options.flags()
    print(f"  mantle: min band windows disabled and not passed, window samples and min bin kept ({flags})")

    options.reload()
    assert (win.value(), low.value(), floor.value()) == (128, 0.0, 2) and options.flags() == [], \
        (win.value(), low.value(), floor.value(), options.flags())
    print("  reload: 128, layout's own, 2, no flag")

    set_processing(copy_yaml, {"window": 256, "min_bin": 10, "min_band_windows": 5})
    window.open_survey(copy_yaml)
    pump(app)
    assert (win.value(), low.value(), floor.value()) == (256, 10.0, 5) and options.flags() == [], \
        (win.value(), low.value(), floor.value(), options.flags())
    low.setValue(0.0)
    assert low.text() == "layout's own" and options.flags() == ["--min-bin", "0"], (low.text(), options.flags())
    low.setValue(10.0)
    floor.setValue(2)
    assert options.flags() == ["--min-band-windows", "2"], options.flags()
    print("  survey window 256, min_bin 10, min_band_windows 5: taken with no flag; min bin 0 -> --min-bin 0 "
          "(layout's own); min band windows 2 -> --min-band-windows 2")

    set_processing(copy_yaml, None)
    window.open_survey(copy_yaml)
    pump(app)
    tab.select_station("D02")
    set_remote(tab, "E08")
    pump(app)
    assert options.flags() == [], options.flags()


def main() -> int:
    """Run the test sequence on the Process tab and return 0 on success."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    assert not (SURVEY_DIR / "masks.yaml").exists(), "the real survey folder holds a masks.yaml"
    copy_yaml = make_survey_copy(MASKS)
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(survey_yaml=copy_yaml)
    window.resize(1400, 900)
    window.show()
    tab = window.process_tab
    window.tabs.setCurrentWidget(tab)
    pump(app)
    box, options = tab.options.masks_check, tab.options

    tab.select_station("D02")
    set_remote(tab, "E08")
    pump(app)
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)", box.text()
    assert box.isChecked() and box.isEnabled(), (box.isChecked(), box.isEnabled())
    assert "Cross-powers" in box.toolTip() and "remote" in box.toolTip(), box.toolTip()
    assert "--no-masks" not in options.flags(), options.flags()
    print(f"  D02 rr E08: {box.text()!r}, ticked, flags {options.flags()}")

    box.setChecked(False)
    assert "--no-masks" in options.flags(), options.flags()
    argv = tab.queue_process()
    assert argv is not None and "--no-masks" in argv, argv
    print(f"  unticked: flags {options.flags()}, queued argv ends {argv[-3:]}")
    box.setChecked(True)

    # the MANTLE engine on a pair with masks: --no-masks goes with --engine
    # mantle whatever the switch says, the switch and the aurora block are
    # disabled, and the status line says so
    options.engine_combo.setCurrentText("mantle")
    pump(app)
    assert options.flags() == ["--no-masks", "--engine", "mantle"], options.flags()
    assert not box.isEnabled() and box.isChecked(), (box.isEnabled(), box.isChecked())
    assert not options.advanced.isEnabled(), "the aurora estimator block stayed enabled with mantle"
    status = tab.status_label.text()
    assert "engine mantle" in status and "--no-masks is passed (D02: 3, E08: 2)" in status, status
    argv = tab.queue_process()
    assert argv is not None and argv[-3:] == ["--no-masks", "--engine", "mantle"], argv
    label = tab.runner.jobs[-1].label
    assert label.startswith("process_rr D02 rr-E08 [mantle]"), label
    print(f"  engine mantle: flags {options.flags()}, switch disabled and ticked, status {status!r}, "
          f"queue label {label!r}")
    options.engine_combo.setCurrentText("aurora")
    pump(app)
    assert options.flags() == [] and box.isEnabled() and box.isChecked(), (options.flags(), box.isEnabled())
    assert options.advanced.isEnabled() and "engine mantle" not in tab.status_label.text(), tab.status_label.text()
    print(f"  back to aurora: flags {options.flags()}, switch enabled again")

    check_band_controls(app, window, tab, copy_yaml)
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)" and box.isChecked(), box.text()

    set_remote(tab, "A07")
    pump(app)
    assert box.text() == "apply masks.yaml (D02: 3, A07: 0)", box.text()
    print(f"  remote -> A07: {box.text()!r}")

    box.setChecked(False)  # unticked on a pair with masks, then a pair with none
    tab.select_station("A02")
    set_remote(tab, "A03")
    pump(app)
    assert box.text() == "apply masks.yaml (no masks declared)", box.text()
    assert not box.isEnabled(), "enabled with no masks declared"
    assert box.isChecked(), "a greyed switch left unticked reads as switched off"
    box.setChecked(False)  # programmatic only: a user cannot untick a disabled box
    assert "--no-masks" not in options.flags(), options.flags()
    print(f"  A02 rr A03: {box.text()!r}, disabled and ticked again, flags {options.flags()} even unticked")
    box.setChecked(True)
    tab.select_station("D02")
    set_remote(tab, "E08")
    pump(app)
    assert box.isChecked() and box.isEnabled() and "--no-masks" not in options.flags(), (
        box.isChecked(), box.isEnabled(), options.flags())
    print(f"  back to D02 rr E08: {box.text()!r}, ticked")

    write_masks({**MASKS, "E08": MASKS["E08"] + [EXTRA_E08]})
    window.open_survey(copy_yaml)
    pump(app)
    tab.select_station("D02")
    set_remote(tab, "E08")
    pump(app)
    assert box.text() == "apply masks.yaml (D02: 3, E08: 3)", box.text()
    assert box.isChecked(), "reopening the survey did not re-tick the switch"
    print(f"  survey reopened after E08 gained a mask: {box.text()!r}, ticked")

    window.tabs.setCurrentWidget(window.crosspower_tab)
    pump(app)
    write_masks({**MASKS, "E08": MASKS["E08"] + [EXTRA_E08], "D02": MASKS["D02"] + [EXTRA_E08]})
    window.tabs.setCurrentWidget(tab)
    pump(app)
    assert box.text() == "apply masks.yaml (D02: 4, E08: 3)", box.text()
    print(f"  a mask saved while the tab was hidden, tab shown again: {box.text()!r}")

    window.tabs.setCurrentWidget(window.crosspower_tab)
    pump(app)
    (SCRATCH / "masks.yaml").write_text("D02: [\n  - start: {\n", encoding="utf-8")
    window.tabs.setCurrentWidget(tab)
    pump(app)
    assert box.text() == "apply masks.yaml (masks.yaml unreadable)", box.text()
    assert "could not be read" in box.toolTip() and "Cross-powers" in box.toolTip(), box.toolTip()
    print(f"  broken masks.yaml: {box.text()!r}, the parser's message in the tooltip")
    window.tabs.setCurrentWidget(window.crosspower_tab)
    pump(app)
    write_masks({**MASKS, "E08": MASKS["E08"] + [EXTRA_E08], "D02": MASKS["D02"] + [EXTRA_E08]})
    window.tabs.setCurrentWidget(tab)
    pump(app)
    assert box.text() == "apply masks.yaml (D02: 4, E08: 3)", box.text()
    assert "could not be read" not in box.toolTip(), box.toolTip()

    options.describe_masks("D02", "STK_E08u")
    assert box.text() == "apply masks.yaml (D02: 4)", box.text()
    print(f"  remote STK_E08u (a stack): {box.text()!r}")

    # the data drive unplugged: data_root names a folder that does not exist
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    config["data_root"] = str(SCRATCH / "drive_not_mounted")
    copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    write_masks(MASKS)
    window.open_survey(copy_yaml)
    pump(app)
    assert window.state.raw_sites() == {}, "data_root is expected to be unreadable"
    # the label rule is called directly, whatever the station list holds (tests/process_station_list_unit.py)
    options.describe_masks("D02", "E08")
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)", box.text()
    print(f"  data_root unmounted, D02 rr E08: {box.text()!r}")

    # a mask of scope local at E08 applies to E08 as the local alone
    write_masks({**MASKS, "E08": MASKS["E08"] + [LOCAL_E08]})
    options.describe_masks("D02", "E08")
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)", box.text()
    print(f"  E08 gains a mask of scope local, D02 rr E08: {box.text()!r}")

    # scope remote: E08's applies to D02 rr E08; D02's does not apply to D02 as the local; an E-only
    # entry of E08 does not apply to E08 as the remote
    write_masks({**MASKS, "E08": MASKS["E08"] + [REMOTE_E08]})
    options.describe_masks("D02", "E08")
    assert box.text() == "apply masks.yaml (D02: 3, E08: 3)", box.text()
    write_masks({**MASKS, "D02": MASKS["D02"] + [REMOTE_D02], "E08": MASKS["E08"] + [EY_E08]})
    options.describe_masks("D02", "E08")
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)", box.text()
    print(f"  E08 gains a mask of scope remote: (D02: 3, E08: 3); D02 one of scope remote and E08 an [ey] one "
          f"of scope both: {box.text()!r}")

    # the Cross-powers tab lists a mask's channels and scope
    from mt_workbench.gui.tabs.crosspower import COLUMNS
    from mt_workbench.masks import load_masks

    write_masks({**MASKS, "E08": MASKS["E08"] + [REMOTE_E08, EY_E08]})
    cross = window.crosspower_tab
    cross.masks = load_masks(copy_yaml, "E08")
    cross._fill_table()
    table = cross.table
    heads = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert heads == list(COLUMNS) and heads[-2:] == ["channels", "scope"], heads
    shown = {table.item(r, 0).text(): (table.item(r, heads.index("channels")).text(),
                                       table.item(r, heads.index("scope")).text()) for r in range(table.rowCount())}
    assert shown[EY_E08["start"]] == ("ey", "both") and shown[REMOTE_E08["start"]] == ("all", "remote"), shown
    print(f"  Cross-powers list of E08: columns {heads[-2:]}, [ey] entry {shown[EY_E08['start']]}, "
          f"remote-scoped {shown[REMOTE_E08['start']]}")

    assert not SLOT_ERRORS, f"{len(SLOT_ERRORS)} Qt slot error(s)"
    assert not (SURVEY_DIR / "masks.yaml").exists(), "a masks.yaml was written to the real survey folder"
    window.state.runner.reset()
    window.close()
    pump(app)
    print("\nPASS  process_tab_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
