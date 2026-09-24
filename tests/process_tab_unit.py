"""Unit test for the Process tab's "apply masks.yaml" switch (headless).

    QT_QPA_PLATFORM=offscreen python tests/process_tab_unit.py

A scratch copy of curnamona_cube's survey.yaml, filters.yaml and
reference_edis.yaml (workspace pointed at the real one: nothing is written
there) gets its own masks.yaml, with MASKS[D02] and MASKS[E08] entries; the
real survey folder holds no masks.yaml and is never written. `MainWindow` is
built on the copy, the Process tab picked, and the switch read back.

**This test fails if** with station D02 and remote E08 the switch does not
read exactly "apply masks.yaml (D02: 3, E08: 2)" (each site's own count,
duplicates in the file collapsed as `load_masks` does), ticked and enabled,
with a tooltip naming the Cross-powers tab and the remote; `RunOptions.flags`
holds --no-masks while it is ticked, or lacks it once unticked, or the
process_rr argv the tab queues lacks it then; a remote change to A07 (no
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
"(D02: 3, E08: 2)"; or any Qt slot raised.
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
from mtproc_gui.app import MainWindow  # noqa: E402
from mtproc_gui.jobs import JobRunner  # noqa: E402

SURVEY_DIR = REPO / "surveys" / "curnamona_cube"
WORK = SURVEY_DIR / "work"
SCRATCH = scratch_dir("process_tab_unit")


def _mask(start: str, end: str, bands="all", reason="test") -> dict:
    return {"start": start, "end": end, "bands": bands, "reason": reason, "found_by": "time"}


# D02: three masks, one of them written twice (load_masks keeps it once); E08: two
MASKS = {
    "D02": [_mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z"),
            _mask("2021-06-29T08:00:00Z", "2021-06-29T08:30:00Z", [0.01, 0.1]),
            _mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z"),
            _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z")],
    "E08": [_mask("2021-06-29T09:00:00Z", "2021-06-29T09:15:00Z"),
            _mask("2021-06-29T12:00:00Z", "2021-06-29T12:05:00Z", [1.0, 10.0])],
}
EXTRA_E08 = _mask("2021-06-30T03:00:00Z", "2021-06-30T03:30:00Z")

# nothing is started: a job the window would run at once (a basemap fetch) is only recorded
STARTED: list[list[str]] = []
JobRunner.run_now = lambda self, label, argv, **details: STARTED.append([str(a) for a in argv]) or -1

SLOT_ERRORS: list[str] = []


def _record_slot_error(exc_type, exc, tb) -> None:
    """An exception inside a Qt slot is printed by PySide6, not raised: keep it, fail at the end."""
    import traceback

    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.stderr.write(SLOT_ERRORS[-1])


sys.excepthook = _record_slot_error


def make_survey_copy(masks: dict) -> Path:
    """The copy's survey.yaml (workspace -> the real work folder) with `masks` as its masks.yaml."""
    for name in ("survey.yaml", "filters.yaml", "reference_edis.yaml"):
        shutil.copy2(SURVEY_DIR / name, SCRATCH / name)
    copy_yaml = SCRATCH / "survey.yaml"
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    config["workspace"] = str(WORK)
    copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    write_masks(masks)
    return copy_yaml


def write_masks(masks: dict) -> None:
    (SCRATCH / "masks.yaml").write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")


def pump(app: QApplication, seconds: float = 0.1) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def set_remote(tab, name: str) -> None:
    index = tab.remote_combo.findData(name)
    assert index >= 0, f"{name} is not a remote choice"
    tab.remote_combo.setCurrentIndex(index)


def main() -> int:
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
    # the station list is the raw sites, empty now: the label rule is called directly
    options.describe_masks("D02", "E08")
    assert box.text() == "apply masks.yaml (D02: 3, E08: 2)", box.text()
    print(f"  data_root unmounted, D02 rr E08: {box.text()!r}")

    assert not SLOT_ERRORS, f"{len(SLOT_ERRORS)} Qt slot error(s)"
    assert not (SURVEY_DIR / "masks.yaml").exists(), "a masks.yaml was written to the real survey folder"
    window.state.runner.reset()
    window.close()
    pump(app)
    print("\nPASS  process_tab_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
