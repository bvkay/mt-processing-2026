# -*- coding: utf-8 -*-
"""
Unit test for the Cross-powers tab's mask buttons while masks.yaml is parsed

Runs headless, with no archive read. A scratch survey with sites A01 and
A02 (empty placeholder archives, so both are listed; a basemap.json, so no
fetch starts) gets a masks.yaml with two masks of A01 and one of A02. A
`State` opens it and a `CrossPowerTab` lists A01, which starts the
masks.yaml parse in `State.masks_reader`; the parse is held in its worker
thread until the test releases it. While it is held the tab's list is
empty, and Mask selected (on a stand-in result: a dict and a band view of
one chunk, the tab's `view`, `restyle` and `masked_chunks` replaced on the
instance), Remove rows (every row selected) and Save masks are run. Then
the parse is released and the same Remove rows and Save masks are run on
the filled list (the control).

Usage:
    QT_QPA_PLATFORM=offscreen python tests/crosspower_masks_wait_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the tab does not wait for the parse (its list not
empty, `_masks_wait` False, while the parse is held); Mask selected, Remove
rows or Save masks run during the wait change masks.yaml by one byte, put a
mask in the list or mark it unsaved, or leave the status line without
"masks.yaml is being read"; once the parse ends the list does not hold
A01's two masks from the file; or, the control, Remove rows on its first
row followed by Save masks does not leave A01 with one mask and A02 with
its one (the test could not see a write). Removing `_masks_unread`'s check
from Save masks fails it (A01's masks erased), as does removing it from
Mask selected (a mask in the list). Remove rows has no row to act on during
the wait (the list is emptied as the wait starts), so its own check is not
what this test exercises.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.gui import masks_reader  # noqa: E402
from mt_workbench.gui.app import State  # noqa: E402
from mt_workbench.gui.tabs.crosspower import CrossPowerTab  # noqa: E402
from mt_workbench.masks import load_masks, masks_path  # noqa: E402

SCRATCH = scratch_dir("crosspower_masks_wait_unit")
MASKS = {
    "A01": [{"start": "2024-01-01T00:00:00Z", "end": "2024-01-01T01:00:00Z", "bands": "all",
             "reason": "keep me", "found_by": "time"},
            {"start": "2024-01-02T00:00:00Z", "end": "2024-01-02T00:30:00Z", "bands": [0.01, 0.1],
             "reason": "keep me too", "found_by": "polar"}],
    "A02": [{"start": "2024-01-03T00:00:00Z", "end": "2024-01-03T02:00:00Z", "bands": "all",
             "reason": "A02's", "found_by": "time"}],
}
SURVEY = {
    "name": "masks_wait_test",
    "instrument": "lemi423",
    "sample_rate": 1000,
    "data_root": str(SCRATCH / "no_drive"),
    "workspace": str(SCRATCH / "work"),
    "processing": {"min_period": 0.005, "max_period": 5000.0, "periods_per_decade": 10.0,
                   "notch_frequencies": [50.0, 150.0]},
    "sites": {"A01": {}, "A02": {}},
}
WAITING = "masks.yaml is being read"

SLOT_ERRORS: list[str] = []


def _record_slot_error(exc_type, exc, tb) -> None:
    """Record an exception raised inside a Qt slot (PySide6 prints it instead of raising)."""
    import traceback

    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.stderr.write(SLOT_ERRORS[-1])


sys.excepthook = _record_slot_error


def make_survey() -> Path:
    """Write the scratch survey, its placeholder archives, basemap.json and masks.yaml; return survey.yaml."""
    mth5 = SCRATCH / "work" / "mth5"
    mth5.mkdir(parents=True, exist_ok=True)
    for site in SURVEY["sites"]:
        (mth5 / f"{site}.h5").write_bytes(b"")
    (SCRATCH / "work" / "basemap.json").write_text("{}", encoding="utf-8")
    survey_yaml = SCRATCH / "survey.yaml"
    survey_yaml.write_text(yaml.safe_dump(SURVEY, sort_keys=False), encoding="utf-8")
    masks_path(survey_yaml).write_text(yaml.safe_dump(MASKS, sort_keys=False), encoding="utf-8")
    return survey_yaml


def pump(app: QApplication, until, seconds: float = 10.0) -> bool:
    """Process Qt events until `until()` is true or `seconds` pass; return `until()`."""
    end = time.time() + seconds
    while not until() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return until()


def main() -> int:
    """Run the wait and the control on the Cross-powers tab and return 0 on success."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    app = QApplication.instance() or QApplication(sys.argv)
    survey_yaml = make_survey()
    path = masks_path(survey_yaml)
    before = path.read_bytes()

    release, started = threading.Event(), threading.Event()
    parse = masks_reader.read_document

    def held(target):
        started.set()
        release.wait(30.0)
        return parse(target)

    masks_reader.read_document = held
    state = State(REPO)
    tab = CrossPowerTab(state)
    try:
        state.open_survey(survey_yaml)
        tab.reload()
        assert tab.site() == "A01", tab.site()
        assert started.wait(10.0), "the masks.yaml parse did not start"
        assert tab._masks_wait and tab.masks == [], (tab._masks_wait, tab.masks)
        print(f"  A01 listed, the parse held: list {tab.masks}, waiting {tab._masks_wait}, "
              f"status {tab.status.text()!r}")

        # Mask selected on a stand-in result of one chunk at band j
        j = tab.band()
        assert j is not None, "no band listed"
        t0 = pd.Timestamp("2024-01-05T00:00:00Z")
        tab.result = {"chunk_s": 600.0}
        tab.view = lambda _j: {"multiple": 1, "level": 0, "starts": [t0], "ends": [t0 + pd.Timedelta(minutes=10)]}
        tab.restyle = lambda: None
        tab.masked_chunks = lambda _j: np.zeros(1, dtype=int)
        tab.selected, tab.selected_on, tab.selected_level = {0}, "time", 0
        tab.status.setText("")
        tab.mask_selected()
        status_mask = tab.status.text()
        tab.table.selectAll()
        tab.status.setText("")
        tab.remove_rows()
        tab.status.setText("")
        tab.save()
        status_save = tab.status.text()
        after = path.read_bytes()
        assert after == before, f"masks.yaml changed during the wait: A01 now {load_masks(survey_yaml, 'A01')}"
        assert tab.masks == [] and not tab.dirty, (tab.masks, tab.dirty)
        assert WAITING in status_mask and WAITING in status_save, (status_mask, status_save)
        print(f"  during the wait: Mask selected, Remove rows, Save masks: masks.yaml unchanged "
              f"({len(after)} bytes), list {tab.masks}, unsaved {tab.dirty}, status {status_save!r}")
        tab.result, tab.selected = None, set()
        del tab.view, tab.restyle, tab.masked_chunks

        release.set()
        assert pump(app, lambda: not tab._masks_wait), "the list still waits 10 s after the parse was released"
        assert tab.masks == load_masks(survey_yaml, "A01") and len(tab.masks) == 2, tab.masks
        assert tab.table.rowCount() == 2, tab.table.rowCount()
        print(f"  parse released: the list holds A01's {len(tab.masks)} masks, status {tab.status.text()!r}")

        # the control: the same buttons on the filled list write the file
        tab.table.clearSelection()
        tab.table.selectRow(0)
        tab.remove_rows()
        tab.save()
        assert path.read_bytes() != before, "Save masks after the wait did not write masks.yaml"
        a01, a02 = load_masks(survey_yaml, "A01"), load_masks(survey_yaml, "A02")
        assert len(a01) == 1 and a01[0]["reason"] == "keep me too" and len(a02) == 1, (a01, a02)
        print(f"  control: Remove rows (row 0) and Save masks after the wait: A01 {len(a01)} mask, A02 {len(a02)}")
    finally:
        release.set()
        masks_reader.read_document = parse
        state.masks_reader.wait()
        tab.close()
        app.processEvents()
    assert not SLOT_ERRORS, f"{len(SLOT_ERRORS)} Qt slot error(s)"
    print("\nPASS  crosspower_masks_wait_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
