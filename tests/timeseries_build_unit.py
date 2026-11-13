# -*- coding: utf-8 -*-
"""
Unit test for the Time Series tab's Build MTH5 gate on a burst site (run headless)

**This test fails if** the Time Series tab's Build MTH5 button, on a scratch
Phoenix survey with no archive, is not enabled on the burst site G5H
(`bursts_of: G5`, `sample_rate: 24000`), whose recorded site G5 has a raw
folder and G5H none of its own (upstream issue 72: `scripts/ingest_site.py`
looks a burst site up by its recorded site's folder, `Survey.raw_site`);
if pressing it on G5H does not ask the job runner for
`scripts/ingest_site.py <survey.yaml> G5H`; if it is enabled on the burst
site G9H, whose recorded site G9 is declared but has no folder, or its
tooltip there does not name G9; or, as the control, if it is not enabled on
G5 itself.

The survey is written into a scratch folder: G5 is a Phoenix channel
folder holding one synthetic `.td_150` name (a 128-byte zero header), as
tests/survey_unit.py makes it. `JobRunner.run_now` is replaced at the class
level before the window is built by a recorder that starts nothing, so no
ingest or basemap fetch runs.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/timeseries_build_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import yaml

if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("timeseries_build_unit")
JOBS: list[list[str]] = []


def _recording_run_now(self, label, argv, **details):
    """Record a job instead of starting it."""
    JOBS.append([str(a) for a in argv])
    return -1


JobRunner.run_now = _recording_run_now


def pump(app: QApplication, seconds: float = 0.3) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def make_survey() -> Path:
    """Write the survey of the module docstring; return its survey.yaml."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    folder = SCRATCH / "data" / "G5" / "3"
    folder.mkdir(parents=True)
    (folder / "10133_5FA4809A_3_00000001.td_150").write_bytes(bytes(128))
    (SCRATCH / "work").mkdir()
    config = {"name": "BURST_GATE", "instrument": "phoenix", "sample_rate": 150, "data_root": str(SCRATCH / "data"),
              "workspace": str(SCRATCH / "work"),
              "sites": {"G5": {"serial": "10133"}, "G5H": {"bursts_of": "G5", "sample_rate": 24000},
                        "G9": {"serial": "10139"}, "G9H": {"bursts_of": "G9", "sample_rate": 24000}}}
    (SCRATCH / "survey.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return SCRATCH / "survey.yaml"


def gate(app: QApplication, window: MainWindow) -> dict:
    """Return Build MTH5's (enabled, tooltip) on each site row of the tab's tree."""
    ts = window.timeseries_tab
    rows = {r.text(0): r for r in ts.tree.site_items()}
    out = {}
    for site in ("G5", "G5H", "G9H"):
        ts.tree.setCurrentItem(rows[site])
        pump(app)
        out[site] = (ts.build_button.isEnabled(), ts.build_button.toolTip())
    return out


def main() -> int:
    print(__doc__.split("**This test fails if**")[1].split("The survey is written")[0].strip())
    print()
    app = QApplication.instance() or QApplication(sys.argv)
    survey_yaml = make_survey()
    window = MainWindow()
    window.open_survey(survey_yaml)
    pump(app, 0.5)
    window.tabs.setCurrentWidget(window.timeseries_tab)
    pump(app)
    got = gate(app, window)
    for site, (enabled, tip) in got.items():
        print(f"  {site}: {'enabled' if enabled else 'disabled'}, tooltip {tip!r}")
    bad = []
    if not got["G5"][0]:
        bad.append(f"control: G5 disabled ({got['G5'][1]!r})")
    if not got["G5H"][0]:
        bad.append(f"G5H disabled ({got['G5H'][1]!r}), its recorded site G5 has a raw folder")
    if got["G9H"][0] or "G9" not in got["G9H"][1].replace("G9H", ""):
        bad.append(f"G9H {'enabled' if got['G9H'][0] else 'disabled'} with tooltip {got['G9H'][1]!r}: G9 has no "
                   f"folder, the tooltip must name G9")
    if got["G5H"][0]:
        ts = window.timeseries_tab
        rows = {r.text(0): r for r in ts.tree.site_items()}
        ts.tree.setCurrentItem(rows["G5H"])
        pump(app)
        before = len(JOBS)
        ts.build_button.click()
        pump(app)
        wanted = [str(survey_yaml), "G5H"]
        asked = JOBS[before:]
        if len(asked) != 1 or Path(asked[0][1]).name != "ingest_site.py" or asked[0][2:] != wanted:
            bad.append(f"pressed on G5H, the runner was asked for {asked}")
        else:
            print(f"  pressed on G5H: run_now({' '.join(Path(a).name for a in asked[0][1:])}) recorded, not run")
    window.close()
    if bad:
        print("\nFAIL  timeseries_build_unit")
        for line in bad:
            print(f"  {line}")
        return 1
    print("\nPASS  timeseries_build_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
