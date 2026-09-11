"""Smoke test for the bbmt_gui desktop GUI (run headless).

    QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py

The flow under test is the MATLAB app's: a tree of sites on the Time Series
tab, a window under a site, one click loads it, and the Spectra, Spectrogram
and Coherence tabs show that window. **This test fails if**

(1)  the window cannot be built, or its tabs are not, in order, Metadata,
     Time Series, Spectra, Spectrogram, Coherence, Filter Data, Process,
     View EDIs; or the Metadata table does not show 59 sites with a `remote`
     column reading E08 for D02; or the dark theme is not on: the
     application palette's Window colour is not #2b2b2b (`theme.WINDOW`),
     its Base not #1f1f1f, or the style not Fusion (behind the theme's
     proxy); or an unticked, unlabelled QCheckBox has no pixel at least 64
     lightness levels above the window grey -- Fusion alone draws its
     outline from the window grey, darkened, and the box disappears;
(2)  the Time Series tree does not have 59 site rows, bold and collapsed, of
     which exactly three -- A07, D02, E08, the archived ones -- are
     expandable (an indicator and no rows yet) while every other row holds
     one disabled child reading "no archive - ..."; or a real mouse click on
     D02's row does not expand it;
(3)  expanding D02 does not, within 30 s, yield 21 window rows, the first
     labelled with D02's record start as the runs' `time_period.start` attrs
     give it ("2021-06-29 06:55 UTC (2.0 h)") and the last "(1.3 h)";
(4)  a mouse click on window index 3 (the fourth) does not, within 60 s, bring
     `segment_loaded` for D02 with n = 7,200,000 samples per channel starting
     at that record start + 6 h, four channel plots with finite data over the
     whole window and x limits [0, 7200] s, the hint naming D02; or one click
     starts more than one worker (`qc_started` once); or the four plots are
     not the MATLAB app's stack: channels hx, hy, ex, ey top to bottom, left
     labels starting "Bx (", "By (", "Ex (", "Ey (", curve pens #4fc3f7
     (`theme.B_COLOUR`) on the first two and #ff5252 (`theme.E_COLOUR`) on
     the last two, a background brush of #1f1f1f, bottom tick values hidden
     on the upper three and shown on the bottom one, the vertical grid on
     and the horizontal grid off on all four, and no gap between them (each
     plot's top edge at the one above's bottom edge);
(5)  the INDEPENDENT check fails: ex over the first 60 s of that window, as
     the Segment holds it (float32, offset removed) plus the Segment's offset,
     and as the ex plot (the third) shows it, is not `allclose` (atol 1e-6
     of the spread) to the same 60,000 samples read here with h5py alone --
     D02.h5 opened read-only, the record start from the earliest run's
     `time_period.start` attr, the sample rate from the `ex` dataset's
     `sample_rate` attr, the run covering the window found from the runs'
     `time_period` attrs and its `ex` dataset sliced by sample offset from
     that run's start, divided by the Segment's gain; nothing from
     `bbmt_gui.segment` or `bbmt_gui.archive` places these samples in time. This catches an off-by-one, wrong-run or
     wrong-t0 bug (the window starts 16,200,999 samples into the second run);
(6)  the archive lock does not serialise: A07 expanded right after the click,
     while the store holds the lock for its load phase, must wait (no tree
     thread, A07 queued), then get its window rows once the store's load
     releases the lock, while the QC is still computing (the maths holds no
     lock);
(7)  `qc_ready` does not follow within 120 s with a `SegmentQC` whose PSD
     stages (two, at 1000 and 100 Hz) carry hx and r_hx, finite, whose
     (hx, r_hx) band curve has a median above 0.5 in the 0.1-1 s band, and
     whose spectrogram grids for all four channels are finite with at least
     20 time columns; or the three QC tabs do not draw it, in the MATLAB
     app's layout:
     Spectra -- two panels titled "By-Ex (Zxy)" over "Bx-Ey (Zyx)", each
     with six finite positive curves (two stages each of the magnetic
     channel in #4fc3f7, the electric in #ff5252 and the remote's coil in
     #bdbdbd), bottom tick values on the lower panel only; each panel's
     ViewBox limits equal to the data extent computed HERE from the curves'
     own data (log10 of the smallest and largest positive frequency, and of
     the smallest and largest positive PSD at 0.003-400 Hz, below the
     anti-alias roll-off) and the view starting exactly there; a setRange a
     decade or two beyond every side clamped back to that extent; on each
     panel five dashed "Schumann" lines at 7.83, 14.3, 20.8, 27.3, 33.8 Hz
     and ten dashed "mains" lines at 50, 100, ... 500 Hz (Nyquist), and on
     the tab exactly one "Schumann" and one "50 Hz + harmonics" text label;
     Spectrogram -- four meshes each more than 80 per cent finite, labelled
     Bx, By, Ex, Ey top to bottom, bottom tick values on the lowest only,
     each x limited to [0, 120] min with a 120 min maximum span, and a
     setXRange(-10, 200) clamped to [0, 120] on all four;
     Coherence -- the two aligned columns: "By-Ex (Zxy)", "Bx-Ey (Zyx)",
     "Bx-By (magnetic)", "Ex-Ey (electric)" in rows 1-4 of column 0 and
     "rBy-Ex (Zxy, remote)", "rBx-Ey (Zyx, remote)", "Bx-rBx", "By-rBy" in
     rows 1-4 of column 1, as the panels' left axis labels; no coherogram
     and no pair combo anywhere; every one of the eight panels holding the
     five band lines plus a white "All frequencies" curve at least 2 px wide
     equal (NaN where they are) to the mean of the five lines it is drawn
     over; each column stacked with no gap and bottom tick values on row 4
     only; once the tab is shown every panel's x view exactly [0, 120] min
     (1e-9, no padding) with x limits [0, 120] and y view and limits
     [0, 1], and a setXRange(-10, 200) on one panel leaving every panel on
     [0, 120]; and a click on a RIGHT-column panel at 15 min (900 s)
     putting the cursor at 15 min on all eight;
     or any of the three is not labelled with D02, the window's start and
     end (12:55:49 to 14:55:49 UTC) and remote E08;
(8)  a mouse click on E08's second window does not replace the plots with
     E08 (the hint names E08, the Segment is E08's, x limits reset to
     [0, 7200]) and, on its `qc_ready`, relabel the three QC tabs to E08
     (no remote is declared for E08) and leave the Coherence tab's right
     column out -- four panels, the local pairs only;
(9)  the visible range set to 600-1800 s and the "Use visible range as
     processing window" button do not fill the Process tab's window fields
     with E08's window start + 10 min and + 30 min (to the minute);
(10) `state.goto_time.emit(window start + 3000 s)` does not set the view to
     [2700, 3300] s and bring the Time Series tab to the front;
(11) a click on a left-column band panel at 1234 s (20.57 min) does not put
     the cursor there on every visible panel, with the time label reading
     the window start + 1234 s in UTC;
(12) a trivial job does not run through the shared JobRunner to completion
     with its output in the shared log; a job whose output names an
     existing .edi path does not put it in the Products list; or "Show in
     View EDIs" does not front the View EDIs tab with that EDI and the D02
     lemimt reference ticked and drawn -- one mtpy error-bar container per
     station on the xy resistivity axes, finite and positive, apparent
     resistivities at 1 s within a factor of 3;
(13) the Process tab is not laid out as the MATLAB Process Data tab, or
     does not do all of this for D02. Layout, from the widgets' positions:
     station combo, remote combo and summary left to right on row 1; below
     them the window bar; below that the buttons "Add to queue", "Run
     queue", "Reset queue", "Timing check", "Site QC figures", "Build stack",
     "Fetch basemap" left to right on one row; below them the Aurora options,
     their "Advanced (aurora estimator)" block collapsed; below those
     the queue table; the site map right of the table and below the bar,
     the stack builder under the map and the Products list under that; in
     the bar, the status line centred (3 px) between the two lamps and above
     the plot, the start field left of the plot and the end field right of
     it. Behaviour: preselect remote E08 from `survey.yaml`; draw a site map
     of 59 points with D02 green, E08 blue and a distance label within 2 km
     of the D02-E08 separation computed here from the YAML coordinates by
     the spherical law of cosines (a different formula from the haversine
     under test); show both recorded spans on the window bar and default the
     region to their overlap; with `<workspace>/basemap.json` and
     `basemap.png` present (fetched by `scripts/fetch_basemap.py`; without
     them this check is skipped with a printed reason) the map must hold one
     `pg.ImageItem` below the dots whose rect in view coordinates equals the
     JSON's lon_min..lon_max, lat_min..lat_max (1e-9), whose top data row is
     the PNG's first (north) row and bottom data row its last, with the
     attribution naming the provider and no "no basemap" line showing;
     the summary must read "Distance to remote:"
     within 0.1 km of that law-of-cosines figure, "Overlap available:" within
     0.05 h (and its days within 0.005) of the D02-E08 overlap computed HERE
     from the two archives' run `time_period` attrs with h5py, "Window
     length:" within 0.05 h of the region, and "Recommended remote: E08"
     (D02's declared remote) with that same distance and overlap; both lamps,
     as drawn (the pixel at each one's centre), green (hue 90-150) under
     "remote covers the whole window"; a region set programmatically (start
     + 5 h to start + 9 h) must show in both fields, both local labels (ACST
     is UTC+9:30) and "Window length: 4.0 h"; with D08 as the remote (a site
     whose span, from its B423 file names read HERE, ends inside D02's) the
     summary's distance must follow to D02-D08 by the law of cosines, a
     region dragged 2 h either side of D08's end must turn both lamps amber
     (hue 25-50) at 45-55 % covered, and one wholly after it red (hue under
     15 or over 345) with "no overlap", while the recommendation still names
     E08; back on E08, with `state.runner.add` wrapped to record every argv
     while `run_queue` does nothing (the jobs are queued, never run): the
     two finished jobs of (12) must be rows showing their label under
     Station and "-" under Remote, Window and Options; "Add to queue" must
     record process_rr.py D02 E08 with that window and **no** band options
     while they are the survey's and add a row reading Station D02, Remote
     E08, Window "<start> to <end>", Options "defaults", Status "queued";
     then `--min-period 0.01 --no-filters`, in the argv and in the new row's
     Options, once the spinbox and the checkbox are moved, and none again
     when they are put back; with the advanced block untouched no estimator
     flag (--taper ... --tolerance), then, with it expanded and the taper
     set to hann and r0 to 2.0, exactly `--taper hann --r0 2.0` at the end
     of the argv and "--taper hann --r0 2.0" in the row's Options, and none
     again once they are put back; "Fetch basemap" must record exactly
     `<python> scripts/fetch_basemap.py <survey.yaml>` and add a row showing
     its label; the row-3 "Build stack" button must record a
     build_stack.py argv naming the survey, the default stack name STKD02,
     the window and both chosen members (A02, A03), which the map then
     paints orange; "Reset queue" must leave the table with no rows and the
     runner with no jobs; then, with the runner real again and D02/E08 still
     the pair, queuing a trivial job through the tab's own `_queue()` (what
     every button, including Add to queue, calls) must leave it "queued" and
     the runner idle -- `status_label` reading "1 job(s) queued - press Run
     queue" -- until "Run queue" is pressed, after which it runs to
     completion; a trivial job whose argv names fetch_basemap.py, run for
     real, must make the map load the basemap again (a new ImageItem) when
     it finishes (skipped with the basemap check); and for E08, which
     declares no remote, the recommendation
     must be the NEAREST (`distance_km`, computed HERE by the law of cosines)
     among the raw sites whose overlap with E08 is within 1 h of the longest
     (a further tie going to the first by name), the longest itself computed
     HERE from the archives' run `time_period` attrs (h5py) for the archived
     sites and the B423 file names for the rest;
(14) any of the Spectra, Spectrogram or Coherence tabs still carries a
     label containing "What to look for" (the owner writes a PDF instead);
     the Filter Data tab's rule box is not touched;
(15) the Filter Data tab does not round-trip through `filters.yaml`: pointed
     at a *copy* of the survey folder, adding a notch (defaults plus extra
     lines 75 and 125 Hz) and a cp (12 s, 10 min windows) and saving must
     make `Survey.site("D02").filters` equal that list exactly while A07's
     declared `replace` entry (which must load into the replace form, hx
     from A06) stays untouched, and emptying the list and saving again must
     delete D02's key and leave A07's; and the Metadata tab, on that same
     copy (whose `generated_by: scripts/site_table_to_yaml.py` came over with
     it), does not edit and save its `survey.yaml`: the yellow line must be
     visible and read "survey.yaml is generated by scripts/site_table_to_yaml.py:
     regenerating will overwrite edits made here"; serial, firmware, start and
     end must be the four columns right after remote; exactly the ten columns
     latitude, longitude, elevation, dipole_length_ex, dipole_length_ey,
     azimuth_ex, azimuth_ey, remote, timing and notes must be editable; D02's
     dipole_length_ex typed as 51.25 and Save pressed must ask the Yes/No
     question once, naming the script, and answered No leave the file
     byte-identical; pressed again and answered Yes, every byte above the
     `sites:` line and every byte from the copy's trailing `workspace:` key on
     must be unchanged, the file must keep its line count and differ in
     exactly one line -- inside D02's entry (the nearest two-space key above
     it is "D02:"), "dipole_length_ex: <old>" become "dipole_length_ex:
     51.25" -- and the reopened survey and the table must both read 51.25;
(16) the View EDIs tab, rebuilt on mtpy-v2, does not do all of this with
     the curnamona EDIs: with D02_rr-E08.edi and "D02 (lemimt)" ticked, the
     embedded canvas's figure must carry at least two axes, one mtpy
     error-bar container per station on each of them, and BOTH labels in the
     resistivity legends (that is what says the overlay is two stations and
     not one drawn twice); making A07's EDI the tree's current row with
     quick view on must bring one more draw within 2 s whose figure title
     names A07's file and whose xy axes now holds three containers, while
     the two ticked rows stay ticked; "plus phase tensor" must add axes to
     that figure, at least one of them labelled with mtpy's phi_min; the
     "plus tipper" radio must be disabled with the tooltip "no hz sensor on
     this survey", since curnamona declares channels [ex, ey, hx, hy] and
     the aurora tipper comes from an open Bz input; quick view off with
     nothing ticked must leave the figure with no axes at all and a hint
     drawn on it; and the arrow-key path must work -- a
     QTest.keyClick(tree, Qt.Key_Down) moves the current row on and brings
     one more draw within 2 s, and five key clicks in quick succession move
     five rows but are debounced into at most two draws, not five;
(17) the screenshots cannot be grabbed to `work/qc/`: gui_timeseries.png
     (tree and window), gui_timeseries_3s.png (a 3 s zoom), gui_spectra.png,
     gui_spectrogram.png, gui_coherence.png, gui_metadata.png,
     gui_process.png, gui_filters.png, gui_edis.png -- nine in all; or any
     exception is raised inside a Qt slot on the way (PySide6 prints those
     and carries on; `sys.excepthook` collects them here); or the real
     `surveys/curnamona_cube/survey.yaml` is not byte-identical at the end;
(18) the console strip (`window.console`) does not sit in a `QSplitter` below
     `window.tabs` (its top at or below the tab widget's bottom), is not
     read-only, or is not a monospace font; or, freshly built with nothing
     appended, its size hint is not close to three lines
     (`fontMetrics().lineSpacing() * 3`, +/- one line for the frame); or once
     the trivial job of (12) has run, the strip's last lines do not carry
     both the "$ ..." command line the runner prefixes and "hello from job",
     its stdout;
(19) once the segment QC of (7) is ready, the console strip does not also
     carry a line starting "[segment] " (the store's `qc_started`, for the
     window clicked in (4)) and at least one line containing "bbmt.timefreq"
     (the ladder -- `cascade` and `psd_ladder` both call `logger.info`) --
     the sink must reach a line logged from the segment store's worker
     thread, not only the GUI thread's;
(20) "Add to queue" -- and every other button that queues a job -- starts
     the job by itself: with the runner real again (not the (13) interception)
     and D02/E08 already the pair, a job queued through the Process tab's own
     `_queue()` is not left "queued" with the runner idle and
     `status_label` reading "1 job(s) queued - press Run queue" until "Run
     queue" is pressed, after which it does not run to completion;
(21) "Import site table..." (its `import_site_table`) with a two-row CSV --
     A03: dipole_length_ey 48 and notes "moved 20 m east"; B02:
     dipole_length_ey 51.5 and an EMPTY notes cell -- does not change exactly
     those three cells of the copy's table (every other cell, 59 sites by 18
     columns, reading as before), read "2 of 2 sites matched", and on Save
     (answered Yes) change exactly those three keys of the copy's parsed
     `sites:` block and nothing else;
(22) the Metadata tab's "New survey..." button, its dialog filled with the
     synthetic data root that `tests/new_survey_unit.py` builds (S01 and S02,
     in a scratch folder) and accepted: the click does not return once the
     job is queued on state.runner and started (not blocked for the scan --
     the dialog is closed and the job's "$ ..." command line, naming
     new_survey.py, already in the console strip before the wait below), or,
     waited out (job_finished, 60 s, app.processEvents pumped throughout so
     the window stays responsive) does not run `scripts/new_survey.py`,
     write `<scratch>/<name>/survey.yaml` and open it (`state.survey_yaml`),
     with the table showing two rows whose serial and firmware cells read
     "36" and "2.1" for S01 and "112" and "2.3" for S02, the yellow line
     naming scripts/new_survey.py, and the console strip also carrying the
     script's "wrote ..." line; nor does the name default to the folder's;
(23) the Process tab's site map, on screen in the 1400 x 900 window, is less
     than 340 px tall.

It opens three archives, D02.h5, E08.h5 and A07.h5, read-only (through the
GUI and, for the independent check, through h5py), runs no script that
writes an archive, never writes the real `surveys/curnamona_cube/filters.yaml`
or `survey.yaml` (the round trips use a copy in the scratch directory; the
New survey check writes only under the scratch directory too), and writes
only PNGs into `surveys/curnamona_cube/work/qc/`.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import yaml

# the offscreen platform plugin finds no fonts on Windows and draws every
# label as empty boxes; point it at the system font folder so the screenshots
# are readable. Must happen before QApplication is created.
if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pyqtgraph as pg  # noqa: E402
from PySide6.QtCore import QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QDialogButtonBox, QLabel, QTreeWidgetItem,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from bbmt.survey import Survey  # noqa: E402
from bbmt.timefreq import BANDS_S  # noqa: E402
from bbmt_gui import metadata_edit, theme  # noqa: E402
from bbmt_gui.app import MainWindow  # noqa: E402

SURVEY_DIR = REPO / "surveys" / "curnamona_cube"
SURVEY_YAML = SURVEY_DIR / "survey.yaml"
SITE = "D02"
REMOTE = "E08"
OTHER = "E08"  # the site whose second window is clicked in (8)
ARCHIVED = ["A07", "D02", "E08"]
EXPECTED_SITES = 59
EXPECTED_CHANNELS = ("hx", "hy", "ex", "ey")  # top to bottom: magnetics first
# the MATLAB app's look, stated here rather than taken from the theme's helpers
WINDOW_GREY, SURFACE_GREY = "#2b2b2b", "#1f1f1f"
PANEL_LOOK = [("Bx", theme.B_COLOUR), ("By", theme.B_COLOUR), ("Ex", theme.E_COLOUR), ("Ey", theme.E_COLOUR)]
SPECTRA_PANELS = ["By-Ex (Zxy)", "Bx-Ey (Zyx)"]
SCHUMANN = [7.83, 14.3, 20.8, 27.3, 33.8]
MAINS = [50.0 * k for k in range(1, 11)]  # to Nyquist at 1000 Hz
Y_EXTENT_HZ = (0.003, 400.0)  # below the anti-alias roll-off, psd_qc.py's rule
WINDOW_MIN = 120.0  # the QC window in minutes, the Spectrogram and Coherence x unit
EXPECTED_TABS = ["Metadata", "Time Series", "Spectra", "Spectrogram", "Coherence",
                 "Filter Data", "Process", "View EDIs"]
WINDOW_SAMPLES = 7_200_000
WINDOW_INDEX = 3  # the fourth window of D02
N_WINDOWS_D02 = 21
CHECK_S = 60.0  # the independent h5py check covers this much of the window
WINDOW_FMT = "%Y-%m-%d %H:%M"  # what the Time Series tab sends the Process tab
# the Coherence tab's grid, row by row: (local pair, label) then (remote pair, label)
LOCAL_ORDER = [(("hy", "ex"), "By-Ex (Zxy)"), (("hx", "ey"), "Bx-Ey (Zyx)"),
               (("hx", "hy"), "Bx-By (magnetic)"), (("ex", "ey"), "Ex-Ey (electric)")]
REMOTE_ORDER = [(("ex", "r_hy"), "rBy-Ex (Zxy, remote)"), (("ey", "r_hx"), "rBx-Ey (Zyx, remote)"),
                (("hx", "r_hx"), "Bx-rBx"), (("hy", "r_hy"), "By-rBy")]
STACK_MEMBERS = ["A02", "A03"]
RECOMMENDED = "E08"  # the Process tab's recommendation for D02: its declared `remote:`
PARTIAL = "D08"  # a raw site whose recorded span ends inside D02's: the amber and red lamps
ROW3_BUTTONS = ["Add to queue", "Run queue", "Reset queue", "Timing check", "Site QC figures",
                "Build stack", "Fetch basemap"]
ESTIMATOR_FLAGS = {"--taper", "--overlap", "--no-prewhiten", "--min-windows", "--max-iterations",
                   "--redescending-iterations", "--r0", "--u0", "--tolerance"}
ACST_OFFSET_H = 9.5  # what `timezone: Australia/Adelaide` means in June
HINT_TEXT = "What to look for"
NO_HZ_TOOLTIP = "no hz sensor on this survey"  # what the View EDIs tipper radio must say
WORK = SURVEY_DIR / "work"
SHOT_DIR = WORK / "qc"

SCRATCH = Path(
    r"C:\Users\joint\AppData\Local\Temp\claude\D--BEN-BBMT-Processing-2026"
    r"\7432a3ce-c47b-448e-8958-b1c946ec7c08\scratchpad\gui_survey"
)

# what the Filter Data tab must write for D02, entry for entry
EXPECTED_FILTERS = [
    {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2, "extra": [75.0, 125.0]}},
    {"cp": {"period_s": 12.0, "window_minutes": 10.0,
            "channels": ["ex", "ey", "hx", "hy"], "refine": False, "reference": "ey"}},
]
A07_FILTERS = [{"replace": {"hx": "A06"}}]

# the Metadata tab, stated here rather than taken from the tab's own lists
EDITABLE_COLUMNS = {"latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey",
                    "azimuth_ex", "azimuth_ey", "remote", "timing", "notes"}
HEADER_COLUMNS = ["serial", "firmware", "start", "end"]  # read-only, right after "remote"
NEW_DIPOLE = "51.25"  # D02's dipole_length_ex, typed into the copy's table
GENERATED_WARNING = ("survey.yaml is generated by scripts/site_table_to_yaml.py: "
                     "regenerating will overwrite edits made here")
IMPORT_CSV = "site,dipole_length_ey,notes\nA03,48,moved 20 m east\nB02,51.5,\n"
IMPORT_CELLS = {("A03", "dipole_length_ey"): "48", ("A03", "notes"): "moved 20 m east",
                ("B02", "dipole_length_ey"): "51.5"}
IMPORT_KEYS = {("A03", "dipole_length_ey"): 48.0, ("A03", "notes"): "moved 20 m east",
               ("B02", "dipole_length_ey"): 51.5}
NEW_SURVEY_DIR = SCRATCH.parent / "gui_new_survey"  # (22): the synthetic raw data and its survey
SYNTHETIC = {"S01": ("36", "2.1"), "S02": ("112", "2.3")}  # serial, firmware in the headers


SLOT_ERRORS: list[str] = []
REAL_YAML = b""  # surveys/curnamona_cube/survey.yaml as the test found it


def _record_slot_error(exc_type, exc, tb) -> None:
    """An exception inside a Qt slot is printed by PySide6, not raised: keep it, fail at the end."""
    import traceback

    text = "".join(traceback.format_exception(exc_type, exc, tb))
    SLOT_ERRORS.append(text)
    sys.stderr.write(text)


sys.excepthook = _record_slot_error


def pump(app: QApplication, seconds: float = 0.05) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def wait_until(app: QApplication, predicate, timeout: float, what: str) -> None:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out after {timeout:.0f} s waiting for {what}")


def curve_data(plot, index: int = 0):
    """(x, y) given to a curve on a pyqtgraph PlotWidget -- the data behind the
    downsampled picture, not the few hundred points drawn (`getOriginalDataset`)."""
    items = plot.getPlotItem().listDataItems()
    assert len(items) > index, f"a plot has {len(items)} curves, wanted index {index}"
    x, y = items[index].getOriginalDataset()
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def edi_curves(axes):
    """[(period, value)] of the data line inside each of a matplotlib axes'
    error-bar containers -- one container per station, in the order mtpy drew
    them, so an overlay of two EDIs gives two curves."""
    out = []
    for container in axes.containers:
        line = container.lines[0]
        out.append((np.asarray(line.get_xdata(), dtype=float),
                    np.asarray(line.get_ydata(), dtype=float)))
    return out


def legend_labels(axes) -> list[str]:
    legend = axes.get_legend()
    return [] if legend is None else [t.get_text() for t in legend.get_texts()]


def wait_for_draw(app, tab, before: int, timeout: float = 2.0) -> float:
    """Seconds until the View EDIs tab has drawn again (its debounce is ~150 ms)."""
    start = time.time()
    wait_until(app, lambda: tab.draws > before, timeout, "a View EDIs redraw")
    return time.time() - start


def record_start_and_rate(site: str):
    """(t0, fs) of `site` from the archive's attrs alone: the earliest run's
    `time_period.start` and the `ex` dataset's `sample_rate`."""
    with h5py.File(WORK / "mth5" / f"{site}.h5", "r") as f:
        surveys = f["Experiment/Surveys"]
        station = next(surveys[s]["Stations"][site] for s in surveys if site in surveys[s]["Stations"])
        runs = [g for g in station.values() if g.attrs.get("mth5_type") == "Run"]
        t0 = min(pd.Timestamp(g.attrs["time_period.start"]) for g in runs)
        fs = float(runs[0]["ex"].attrs["sample_rate"])
    return t0, fs


def independent_ex(site: str, start: pd.Timestamp, seconds: float) -> np.ndarray:
    """ex counts over [start, start + seconds) read straight from the archive with h5py.

    The run whose `time_period` attrs cover `start` is sliced by sample
    offset from that run's own start at the dataset's `sample_rate` attr.
    Nothing from `bbmt_gui.segment` or `bbmt_gui.archive` is used, so a wrong
    grid there cannot move this read along with it.
    """
    with h5py.File(WORK / "mth5" / f"{site}.h5", "r") as f:
        surveys = f["Experiment/Surveys"]
        station = next(surveys[s]["Stations"][site] for s in surveys if site in surveys[s]["Stations"])
        for name, group in station.items():
            if group.attrs.get("mth5_type") != "Run":
                continue
            run_start = pd.Timestamp(group.attrs["time_period.start"])
            run_end = pd.Timestamp(group.attrs["time_period.end"])
            if run_start <= start < run_end:
                fs = float(group["ex"].attrs["sample_rate"])
                offset = int(round((start - run_start).total_seconds() * fs))
                n = int(round(seconds * fs))
                raw = group["ex"][offset:offset + n].astype("float64")
                print(f"  independent h5py read: run {name} (starts {run_start}), "
                      f"ex[{offset}:{offset + n}] of {group['ex'].shape[0]}")
                return raw
    raise AssertionError(f"no run in {site}.h5 covers {start}")


def click(app, tree, item: QTreeWidgetItem) -> None:
    """A real left click on the text of a tree row."""
    tree.scrollToItem(item)
    pump(app, 0.1)
    rect = tree.visualItemRect(item)
    assert rect.isValid() and rect.height() > 0, f"{item.text(0)!r} is not on screen"
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    pump(app, 0.1)


def qc_labels(window) -> list[str]:
    return [tab.title_label.text() for tab in (window.spectra_tab, window.spectrogram_tab, window.coherence_tab)]


def assert_labelled(window, *needles: str) -> None:
    for name, text in zip(("Spectra", "Spectrogram", "Coherence"), qc_labels(window)):
        for needle in needles:
            assert needle in text, f"{name} label {text!r} lacks {needle!r}"


def law_of_cosines_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance by the spherical law of cosines -- NOT the haversine under test."""
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    return 6371.0088 * math.acos(
        min(1.0, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(d_lon))
    )


def archive_span(site: str):
    """(earliest run start, latest run end) of `site` from its runs' `time_period` attrs, h5py only."""
    with h5py.File(WORK / "mth5" / f"{site}.h5", "r") as f:
        surveys = f["Experiment/Surveys"]
        station = next(surveys[s]["Stations"][site] for s in surveys if site in surveys[s]["Stations"])
        runs = [g for g in station.values() if g.attrs.get("mth5_type") == "Run"]
        return (min(pd.Timestamp(g.attrs["time_period.start"]) for g in runs),
                max(pd.Timestamp(g.attrs["time_period.end"]) for g in runs))


def raw_span(site_dir: Path):
    """A site's raw record from its B423 file names: first epoch to last epoch + the median spacing."""
    epochs = np.sort([int(f.stem) for f in Path(site_dir).rglob("*.B423")])
    return (pd.Timestamp(int(epochs[0]), unit="s", tz="UTC"),
            pd.Timestamp(int(epochs[-1] + np.median(np.diff(epochs))), unit="s", tz="UTC"))


def lamp_hue(lamp) -> int:
    """Hue (0-359; -1 for a grey) of the pixel at a lamp's centre, as the lamp is drawn."""
    image = lamp.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).hsvHue()


def number(text: str, prefix: str, unit: str) -> float:
    """41.3 from ("Overlap available: 41.3 h (1.72 days)", "Overlap available: ", " h")."""
    assert text.startswith(prefix), (text, prefix)
    return float(text[len(prefix):].split(unit)[0])


def table_row(table, row: int) -> list[str]:
    return [table.item(row, column).text() for column in range(table.columnCount())]


def click_plot(app, plot, x: float) -> None:
    """A left click on a pyqtgraph plot at x (in the plot's own unit), through its scene."""
    box = plot.getViewBox()
    y_mid = float(np.mean(box.viewRange()[1]))
    scene_pos = box.mapViewToScene(QPointF(float(x), y_mid))
    event = SimpleNamespace(button=lambda: Qt.LeftButton, scenePos=lambda: scene_pos)
    plot.scene().sigMouseClicked.emit(event)
    pump(app)


def panel_position(tab, pair):
    """(row, column) of a Coherence band panel in the tab's grid."""
    row, column, _rs, _cs = tab.grid.getItemPosition(tab.grid.indexOf(tab.band_plots[pair]))
    return row, column


def hint_labels(tab) -> list[str]:
    """Every label on a tab whose text carries the old "What to look for" paragraph."""
    return [w.text() for w in tab.findChildren(QLabel) if HINT_TEXT in w.text()]


SHOTS: list[Path] = []


def shoot(app, window, name: str, tab) -> Path:
    """(14) grab one tab to work/qc/gui_<name>.png."""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    window.tabs.setCurrentWidget(tab)
    pump(app, 0.4)
    path = SHOT_DIR / f"gui_{name}.png"
    assert tab.grab().save(str(path)), f"could not save {path}"
    SHOTS.append(path)
    return path


def metadata_cells(table) -> dict[tuple[str, str], str]:
    """Every cell of the Metadata table as {(site, column): text}."""
    columns = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    return {(table.item(r, 0).text(), columns[c]): table.item(r, c).text()
            for r in range(table.rowCount()) for c in range(table.columnCount())}


def sites_changes(before: dict, after: dict) -> dict:
    """{(site, key): new value} for every per-site key that differs between two parsed sites blocks."""
    out = {}
    for site in set(before) | set(after):
        old, new = before.get(site) or {}, after.get(site) or {}
        out.update({(site, key): new.get(key) for key in set(old) | set(new) if old.get(key) != new.get(key)})
    return out


def answering(answer: bool, asked: list):
    """A stand-in for `metadata_edit.ask_yes_no` that records the question and answers it."""
    return lambda _parent, _title, text: asked.append(text) or answer


def make_survey_copy() -> Path:
    """A copy of the survey folder whose workspace points at the real one."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for name in ("survey.yaml", "filters.yaml", "reference_edis.yaml"):
        shutil.copy2(SURVEY_DIR / name, SCRATCH / name)
    copy_yaml = SCRATCH / "survey.yaml"
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    config["workspace"] = str(WORK)  # archives, TFs and figures are the real ones
    copy_yaml.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return copy_yaml


def main() -> int:
    print(__doc__.split("**This test fails if**")[1].split("It opens three")[0].strip())
    print()

    global REAL_YAML
    REAL_YAML = SURVEY_YAML.read_bytes()  # (17): must be the same bytes at the end
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)  # as __main__ does, before the window is built
    window = MainWindow(survey_yaml=SURVEY_YAML)
    window.resize(1400, 900)
    window.show()
    pump(app, 0.3)
    assert window.windowTitle() == "BBMT processing", window.windowTitle()
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert tabs == EXPECTED_TABS, f"tab order {tabs}, expected {EXPECTED_TABS}"
    print(f"(1) window built from {SURVEY_YAML}: {tabs}")

    table = window.metadata_tab.table
    assert table.rowCount() == EXPECTED_SITES, f"{table.rowCount()} rows, expected {EXPECTED_SITES}"
    columns = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == SITE)
    assert table.item(row, columns.index("remote")).text() == REMOTE
    print(f"  metadata: {table.rowCount()} sites, {SITE}'s remote column {REMOTE}")
    palette = app.palette()
    window_grey = palette.color(QPalette.Window).name()
    base_grey = palette.color(QPalette.Base).name()
    style = app.style()
    style = (style.baseStyle() if hasattr(style, "baseStyle") else style).name().lower()
    assert window_grey == WINDOW_GREY, f"palette Window {window_grey}, expected {WINDOW_GREY}"
    assert base_grey == SURFACE_GREY, f"palette Base {base_grey}, expected {SURFACE_GREY}"
    assert style == "fusion", style
    probe = QCheckBox("")
    probe.resize(24, 24)
    image = probe.grab().toImage()
    edge = max(image.pixelColor(x, y).lightness() for x in range(24) for y in range(24))
    lift = edge - QColor(WINDOW_GREY).lightness()
    assert lift >= 64, f"an unticked check box is {lift} lightness levels above the window grey"
    print(f"  theme: {style} style, palette Window {window_grey}, Base {base_grey}; "
          f"an unticked check box's outline {lift} levels above the window grey")

    # ------------------------------------------------- (18) the console strip
    console = window.console
    assert console.isReadOnly(), "the console strip is editable"
    # the widget's own declared font property, not QFontInfo's post-substitution match: the
    # offscreen test platform's font matching can hand back a variable-pitch family regardless
    assert console.font().fixedPitch(), "the console strip's font does not declare fixed pitch"
    tabs_bottom = window.tabs.mapTo(window, window.tabs.rect().bottomLeft()).y()
    console_top = console.mapTo(window, console.rect().topLeft()).y()
    assert console_top >= tabs_bottom, f"console top {console_top} is above the tabs' bottom {tabs_bottom}"
    metrics = console.fontMetrics()
    want_h = metrics.lineSpacing() * 3
    got_h = console.sizeHint().height()
    assert abs(got_h - want_h) <= metrics.lineSpacing() + 10, f"size hint {got_h} px, wanted ~{want_h} px"
    print(f"(18) console strip: read-only, monospace, below the tabs (top {console_top} >= {tabs_bottom}), "
          f"size hint {got_h} px ~ 3 lines ({want_h} px)")

    # ------------------------------------------------------ (2) the tree
    state, store, lock = window.state, window.state.segment_store, window.state.archive_lock
    ts = window.timeseries_tab
    tree = ts.tree
    window.tabs.setCurrentWidget(ts)
    pump(app, 0.2)
    rows = tree.site_items()
    assert len(rows) == EXPECTED_SITES, f"{len(rows)} site rows"
    assert all(r.font(0).bold() and not r.isExpanded() for r in rows), "site rows not bold and collapsed"
    expandable = [r.text(0) for r in rows
                  if r.childCount() == 0 and r.childIndicatorPolicy() == QTreeWidgetItem.ShowIndicator]
    assert expandable == ARCHIVED, f"expandable rows {expandable}, expected {ARCHIVED}"
    for r in rows:
        if r.text(0) not in ARCHIVED:
            assert r.childCount() == 1 and not (r.child(0).flags() & Qt.ItemIsEnabled), r.text(0)
            assert r.child(0).text(0).startswith("no archive"), r.child(0).text(0)
    d02 = next(r for r in rows if r.text(0) == SITE)
    click(app, tree, d02)
    assert d02.isExpanded(), "a click on D02's row did not expand it"
    print(f"(2) tree: {len(rows)} site rows, expandable {expandable}; a click expanded {SITE}")

    # ------------------------------------------------- (3) D02's windows
    t_rec, fs = record_start_and_rate(SITE)
    window_h = WINDOW_SAMPLES / fs / 3600.0
    wait_until(app, lambda: len(tree.window_items(SITE)) == N_WINDOWS_D02, 30, f"{SITE}'s window rows")
    windows = tree.window_items(SITE)
    labels = [w.text(0) for w in windows]
    assert labels[0] == f"{t_rec:%Y-%m-%d %H:%M} UTC ({window_h:.1f} h)", labels[0]
    assert labels[-1].endswith("(1.3 h)"), labels[-1]
    print(f"(3) {SITE}: {len(windows)} windows, first {labels[0]!r}, last {labels[-1]!r}")

    # ---------------------------------------- (4) click the fourth window
    loaded, results, started = [], [], []
    store.segment_loaded.connect(loaded.append)
    store.qc_ready.connect(results.append)
    store.qc_started.connect(started.append)
    t0 = time.time()
    click(app, tree, windows[WINDOW_INDEX])
    # the remote is off by default on a new station; ask for E08 now so this
    # run checks the remote pairs too (queued behind the load in flight)
    tree.state.set_remote(REMOTE)
    assert lock.holder is store and store.busy, "the store did not start loading under the lock"
    # (6) the tree must wait for the archive while the store loads
    a07 = next(r for r in rows if r.text(0) == "A07")
    a07.setExpanded(True)
    pump(app)
    assert tree._thread is None and "A07" in tree._queue, (tree._thread, tree._queue)
    print("(4) window clicked; (6) A07 expanded meanwhile is queued behind the store's load")
    wait_until(app, lambda: loaded and loaded[-1].station == SITE, 60, f"segment_loaded for {SITE}")
    load_s = time.time() - t0
    segment = loaded[-1]
    win_start = t_rec + pd.Timedelta(hours=WINDOW_INDEX * window_h)
    assert segment.n == WINDOW_SAMPLES, segment.n
    assert segment.t0 == win_start, (segment.t0, win_start)
    assert ts.segment is segment and len(ts.plots) == 4, len(ts.plots)
    assert SITE in ts.hint_label.text(), ts.hint_label.text()
    for comp, plot in zip(EXPECTED_CHANNELS, ts.plots):
        x, y = curve_data(plot)
        assert y.size == WINDOW_SAMPLES and np.isfinite(y).mean() > 0.99, f"{comp}: {np.isfinite(y).sum()} finite"
        limits = plot.getViewBox().state["limits"]["xLimits"]
        assert limits == [0.0, WINDOW_SAMPLES / fs], f"{comp}: x limits {limits}"
    lo, hi = ts.visible_seconds()
    assert abs(lo) < 1e-9 and abs(hi - 7200.0) < 1e-9, (lo, hi)
    # the click started one worker (no remote); asking for E08 queued a second
    # behind it, and the first result was discarded as superseded
    assert len(started) == 2, f"the click plus the remote request started {len(started)} workers"
    print(f"  segment_loaded after {load_s:.1f} s: {segment.station} {segment.t0} "
          f"n={segment.n:,} at {segment.sample_rate:g} Hz; four plots, x limits [0, 7200] s; "
          f"hint {ts.hint_label.text()!r}")
    # the MATLAB app's stack: order, names, colours, one shared x axis, no gaps
    assert ts.comps == list(EXPECTED_CHANNELS), f"Time Series panels {ts.comps}"
    pump(app, 0.2)  # the layout settles before the geometry is read
    for k, ((name, want_pen), plot) in enumerate(zip(PANEL_LOOK, ts.plots)):
        label = plot.getAxis("left").labelText
        assert label.startswith(f"{name} ("), f"panel {k} labelled {label!r}, expected {name} (..."
        pen = pg.mkPen(plot.getPlotItem().listDataItems()[0].opts["pen"]).color().name()
        assert pen == want_pen.lower(), f"{name}: pen {pen}, expected {want_pen}"
        brush = plot.backgroundBrush().color().name()
        assert brush == SURFACE_GREY, f"{name}: background {brush}"
        shows = plot.getAxis("bottom").style["showValues"]
        assert shows == (k == len(ts.plots) - 1), f"{name}: bottom tick values shown {shows}"
        assert plot.getAxis("left").grid is False, f"{name}: horizontal grid on"
        assert plot.getAxis("bottom").grid not in (False, 0), f"{name}: vertical grid off"
    gaps = [b.y() - (a.y() + a.height()) for a, b in zip(ts.plots, ts.plots[1:])]
    assert gaps == [0, 0, 0], f"gaps between the Time Series panels: {gaps} px"
    print(f"  stack: {[p.getAxis('left').labelText for p in ts.plots]}, pens "
          f"{[pg.mkPen(p.getPlotItem().listDataItems()[0].opts['pen']).color().name() for p in ts.plots]}, "
          f"gaps {gaps} px, x values on the bottom panel only, vertical grid only")

    # ----------------------------------------- (5) the independent check
    n_check = int(round(CHECK_S * fs))
    raw = independent_ex(SITE, win_start, CHECK_S)
    expected = raw / segment.gains["ex"]
    got = segment.arrays["ex"][:n_check].astype("float64") + segment.offsets["ex"]
    _x, shown = curve_data(ts.plots[ts.comps.index("ex")])
    spread = float(np.ptp(expected))
    atol = 1e-6 * spread
    diff = float(np.max(np.abs(got - expected)))
    assert np.allclose(got, expected, rtol=0, atol=atol), (
        f"ex from the Segment differs from h5py by up to {diff:g} mV/km (atol {atol:g})")
    diff_shown = float(np.max(np.abs(shown[:n_check] - expected)))
    assert np.allclose(shown[:n_check], expected, rtol=0, atol=atol), (
        f"ex as plotted differs from h5py by up to {diff_shown:g} mV/km")
    print(f"(5) ex over the first {CHECK_S:.0f} s: Segment + offset and the plot both allclose to the "
          f"h5py read (max |diff| {diff:.3g} / {diff_shown:.3g} mV/km, atol {atol:.3g}, "
          f"spread {spread:.4g} mV/km, offset {segment.offsets['ex']:.4g})")

    # --------------------------------------- (6) A07's rows arrive during the QC
    wait_until(app, lambda: len(tree.window_items("A07")) >= 40, 60, "A07's window rows")
    assert store.busy and lock.holder is not store, "A07 was read but the QC had already finished"
    print(f"(6) A07 has {len(tree.window_items('A07'))} window rows while the QC is still computing")
    a07.setExpanded(False)

    # ------------------------------------------------- (7) the QC arrives
    wait_until(app, lambda: results and results[-1].remote == REMOTE, 120, "qc_ready with the remote")
    qc_s = time.time() - t0
    result = results[-1]
    assert result.station == SITE and result.remote == REMOTE, (result.station, result.remote)
    rates = [stage[0] for stage in result.psd_stages]
    assert rates == [1000.0, 100.0], rates
    for _fs, freqs, psd in result.psd_stages:
        assert "hx" in psd and "r_hx" in psd and np.isfinite(psd["hx"]).all(), list(psd)
    t_s, coh = result.band_curves[("hx", "r_hx")]["0.1-1 s"]
    med = float(np.nanmedian(coh))
    assert med > 0.5, f"hx-r_hx 0.1-1 s median coherence {med:.3f}, expected > 0.5"
    for comp in EXPECTED_CHANNELS:
        t_s, periods, db = result.spectrograms[comp]
        assert np.isfinite(db).any() and t_s.size >= 20, f"{comp}: {t_s.size} columns"
        assert np.isfinite(db).mean() > 0.8, f"{comp}: spectrogram mostly NaN"
    print(f"(7) qc_ready after {qc_s:.1f} s: PSD stages at {rates} Hz with {list(result.psd_stages[0][2])}; "
          f"hx-r_hx 0.1-1 s median coherence {med:.3f} over {t_s.size} columns; "
          f"spectrograms {t_s.size} x {periods.size}")
    window_text = f"{segment.t0:%H:%M:%S} to {segment.end:%H:%M:%S} UTC"
    assert_labelled(window, SITE, window_text, f"remote {REMOTE}")
    # Spectra: the MATLAB Welch tab, two panels on one frequency axis
    spectra = window.spectra_tab
    assert list(spectra.plots) == SPECTRA_PANELS, list(spectra.plots)
    mark_labels = []
    for k, (title, plot) in enumerate(spectra.plots.items()):
        assert plot.getPlotItem().titleLabel.text == title, plot.getPlotItem().titleLabel.text
        items = plot.getPlotItem().listDataItems()
        pens = sorted(pg.mkPen(item.opts["pen"]).color().name() for item in items)
        want = sorted([theme.B_COLOUR, theme.B_COLOUR, theme.E_COLOUR, theme.E_COLOUR,
                       theme.REMOTE_COLOUR, theme.REMOTE_COLOUR])
        assert pens == want, f"Spectra {title}: pens {pens}, expected {want}"
        assert plot.getAxis("bottom").style["showValues"] == (k == len(spectra.plots) - 1), title
        freqs, psds = [], []
        for n in range(len(items)):
            f, p = curve_data(plot, n)
            assert p.size > 100 and np.isfinite(p).all() and (p > 0).all(), f"Spectra {title} curve {n}"
            freqs.append(f)
            psds.append(p)
        f, p = np.concatenate(freqs), np.concatenate(psds)
        ok = np.isfinite(f) & np.isfinite(p) & (f > 0) & (p > 0)
        in_y = ok & (f >= Y_EXTENT_HZ[0]) & (f <= Y_EXTENT_HZ[1])
        x_ext = [np.log10(f[ok].min()), np.log10(f[ok].max())]
        y_ext = [np.log10(p[in_y].min()), np.log10(p[in_y].max())]
        box = plot.getViewBox()
        limits = box.state["limits"]
        assert np.allclose(limits["xLimits"], x_ext, rtol=0, atol=1e-9), (title, limits["xLimits"], x_ext)
        assert np.allclose(limits["yLimits"], y_ext, rtol=0, atol=1e-9), (title, limits["yLimits"], y_ext)
        assert np.allclose(box.viewRange(), [x_ext, y_ext], rtol=0, atol=1e-9), (title, box.viewRange())
        box.setRange(xRange=(x_ext[0] - 1, x_ext[1] + 1), yRange=(y_ext[0] - 2, y_ext[1] + 2), padding=0)
        pump(app)
        assert np.allclose(box.viewRange(), [x_ext, y_ext], rtol=0, atol=1e-9), (
            f"Spectra {title}: zoomed out to {box.viewRange()}, past the data {x_ext}, {y_ext}")
        lines = [i for i in plot.getPlotItem().items if isinstance(i, pg.InfiniteLine)]
        schumann = sorted(10 ** line.value() for line in lines if line.name() == "Schumann")
        mains = sorted(10 ** line.value() for line in lines if line.name() == "mains")
        assert np.allclose(schumann, SCHUMANN, rtol=1e-9), schumann
        assert np.allclose(mains, MAINS, rtol=1e-9), mains
        for line in lines:
            assert line.pen.style() == Qt.DashLine and line.pen.color().alpha() < 255, line.name()
        mark_labels += [line.label.toPlainText() for line in lines
                        if getattr(line, "label", None) is not None]
        print(f"  Spectra {title!r}: pens {pens}; limits = view = data extent "
              f"x 10^[{x_ext[0]:.3f}, {x_ext[1]:.3f}] Hz, y 10^[{y_ext[0]:.2f}, {y_ext[1]:.2f}], "
              f"clamped there after a zoom out; {len(schumann)} Schumann + {len(mains)} mains lines")
    assert sorted(mark_labels) == ["50 Hz + harmonics", "Schumann"], mark_labels

    # Spectrogram: Bx, By, Ex, Ey on one locked minutes axis
    spectrogram = window.spectrogram_tab
    assert list(spectrogram.images) == list(EXPECTED_CHANNELS), list(spectrogram.images)
    for k, ((name, _pen), (comp, image)) in enumerate(zip(PANEL_LOOK, spectrogram.images.items())):
        assert image.drawn and np.isfinite(image.mesh.z).mean() > 0.8, f"Spectrogram {comp}"
        assert image.plot.getAxis("left").labelText.startswith(f"{name} "), image.plot.getAxis("left").labelText
        assert image.plot.getAxis("bottom").style["showValues"] == (k == 3), comp
        limits = image.plot.getViewBox().state["limits"]
        assert limits["xLimits"] == [0.0, WINDOW_MIN] and limits["xRange"][1] == WINDOW_MIN, (comp, limits)
    spectrogram.images["hx"].plot.setXRange(-10.0, 200.0, padding=0)
    pump(app)
    for comp, image in spectrogram.images.items():
        x_view = image.plot.getViewBox().viewRange()[0]
        assert np.allclose(x_view, [0.0, WINDOW_MIN], rtol=0, atol=1e-9), f"Spectrogram {comp}: {x_view}"
    print(f"  Spectrogram: {[i.plot.getAxis('left').labelText for i in spectrogram.images.values()]}, "
          f"x limits [0, {WINDOW_MIN:g}] min, a setXRange(-10, 200) stays on [0, {WINDOW_MIN:g}]")

    # Coherence: the MATLAB titles, the band lines and their mean, locked axes
    coherence = window.coherence_tab
    band_names = [label for _lo, _hi, label in BANDS_S]
    for pair, plot in coherence.band_plots.items():
        items = plot.getPlotItem().listDataItems()
        names = [item.name() for item in items]
        assert names == band_names + ["All frequencies"], f"Coherence {pair}: {names}"
        pen = pg.mkPen(items[-1].opts["pen"])
        assert pen.color().name() == "#ffffff" and pen.widthF() >= 2, (pair, pen.color().name(), pen.widthF())
        band_rows = np.vstack([curve_data(plot, n)[1] for n in range(len(band_names))])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(band_rows, axis=0)
        t_all, all_freq = curve_data(plot, len(band_names))
        assert np.allclose(all_freq, mean, equal_nan=True), f"Coherence {pair}: the white curve is not the mean"
        assert 0 <= t_all.min() and t_all.max() <= WINDOW_MIN, (pair, t_all.min(), t_all.max())
    # two aligned columns, in the stated order, and no coherogram left
    assert not hasattr(coherence, "image"), "the coherogram is still on the Coherence tab"
    assert not hasattr(coherence, "pair_combo"), "the coherogram's pair combo is still there"
    for column, order in ((0, LOCAL_ORDER), (1, REMOTE_ORDER)):
        for row, (pair, label) in enumerate(order, start=1):
            assert panel_position(coherence, pair) == (row, column), (
                f"{label} sits at {panel_position(coherence, pair)}, expected row {row} column {column}")
            assert coherence.labels[pair] == label, (coherence.labels[pair], label)
            shown_label = coherence.band_plots[pair].getAxis("left").labelText
            assert shown_label == label, (shown_label, label)
            assert coherence.band_plots[pair].getAxis("bottom").style["showValues"] == (row == 4), label
    wanted_pairs = [pair for pair, _l in LOCAL_ORDER] + [pair for pair, _l in REMOTE_ORDER]
    assert sorted(coherence.visible_pairs()) == sorted(wanted_pairs), coherence.visible_pairs()
    window.tabs.setCurrentWidget(coherence)
    pump(app, 0.4)
    for order in (LOCAL_ORDER, REMOTE_ORDER):
        column = [coherence.band_plots[pair] for pair, _l in order]
        gaps = [b.y() - (a.y() + a.height()) for a, b in zip(column, column[1:])]
        assert gaps == [0, 0, 0], f"gaps between the Coherence rows: {gaps} px"
    for pair, plot in coherence.band_plots.items():
        box = plot.getViewBox()
        x_view, y_view = box.viewRange()
        assert np.allclose(x_view, [0.0, WINDOW_MIN], rtol=0, atol=1e-9), f"Coherence {pair}: x {x_view}"
        assert np.allclose(y_view, [0.0, 1.0], rtol=0, atol=1e-9), f"Coherence {pair}: y {y_view}"
        limits = box.state["limits"]
        assert limits["xLimits"] == [0.0, WINDOW_MIN] and limits["yLimits"] == [0.0, 1.0], (pair, limits)
    coherence.band_plots[LOCAL_ORDER[0][0]].setXRange(-10.0, 200.0, padding=0)
    pump(app)
    for pair, plot in coherence.band_plots.items():
        x_view = plot.getViewBox().viewRange()[0]
        assert np.allclose(x_view, [0.0, WINDOW_MIN], rtol=0, atol=1e-9), f"Coherence {pair}: {x_view}"
    # the cursor is on every panel, and a click on the RIGHT column moves it
    click_plot(app, coherence.band_plots[REMOTE_ORDER[1][0]], 900.0 / 60.0)
    values = [float(c.value()) for c in coherence.cursors.values()]
    assert max(abs(v - 15.0) for v in values) < 1.0 / 60.0, values
    assert f"{segment.t0 + pd.Timedelta(seconds=900):%H:%M:%S} UTC" in coherence.time_label.text()
    print(f"  QC tabs drawn and labelled: {qc_labels(window)[0]!r}; eight pair plots in two "
          f"aligned columns, each with five bands and the white 'All frequencies' mean, x exactly "
          f"[0, {WINDOW_MIN:g}] min and locked there, y [0, 1]; a click on "
          f"{REMOTE_ORDER[1][1]!r} put all eight cursors at {np.mean(values):.2f} min")

    # -------------------------------- (19) the console strip: segment + ladder
    console_text = console.toPlainText()
    segment_lines = [line for line in console_text.splitlines() if line.startswith("[segment] ")]
    ladder_lines = [line for line in console_text.splitlines() if "bbmt.timefreq" in line]
    assert segment_lines, f"no '[segment] ' line in the console strip:\n{console_text}"
    assert ladder_lines, f"no 'bbmt.timefreq' line (the ladder, off the GUI thread) in the console:\n{console_text}"
    print(f"(19) console strip: {len(segment_lines)} '[segment] ' line(s), last {segment_lines[-1]!r}; "
          f"{len(ladder_lines)} 'bbmt.timefreq' line(s), e.g. {ladder_lines[0]!r}")

    shoot(app, window, "timeseries", ts)
    ts.plots[0].setXRange(3000.0, 3003.0, padding=0)
    pump(app, 0.3)
    lo, hi = ts.visible_seconds()
    assert abs(lo - 3000) < 1e-6 and abs(hi - 3003) < 1e-6, (lo, hi)
    shoot(app, window, "timeseries_3s", ts)
    shoot(app, window, "spectra", spectra)
    shoot(app, window, "spectrogram", spectrogram)
    shoot(app, window, "coherence", coherence)

    # ---------------------------------------- (8) another site's window
    window.tabs.setCurrentWidget(ts)
    e08 = next(r for r in rows if r.text(0) == OTHER)
    click(app, tree, e08)
    wait_until(app, lambda: len(tree.window_items(OTHER)) >= 2, 30, f"{OTHER}'s window rows")
    other_windows = tree.window_items(OTHER)
    t_other, _fs = record_start_and_rate(OTHER)
    n_loaded, n_started = len(loaded), len(started)
    t0 = time.time()
    click(app, tree, other_windows[1])
    wait_until(app, lambda: len(loaded) > n_loaded and loaded[-1].station == OTHER, 60,
               f"segment_loaded for {OTHER}")
    other = loaded[-1]
    assert other.n == WINDOW_SAMPLES and other.t0 == t_other + pd.Timedelta(hours=window_h), other.t0
    assert ts.segment is other and OTHER in ts.hint_label.text() and SITE not in ts.hint_label.text()
    lo, hi = ts.visible_seconds()
    assert abs(lo) < 1e-9 and abs(hi - 7200.0) < 1e-9, (lo, hi)
    assert len(started) == n_started + 1
    print(f"(8) {OTHER}'s second window loaded after {time.time() - t0:.1f} s: {other.t0}; "
          f"hint {ts.hint_label.text()!r}")
    wait_until(app, lambda: results and results[-1].station == OTHER, 120, f"qc_ready for {OTHER}")
    other_qc = results[-1]
    assert other_qc.remote is None, other_qc.remote
    assert_labelled(window, OTHER, f"{other.t0:%H:%M:%S} to {other.end:%H:%M:%S} UTC", "no remote")
    assert coherence.visible_pairs() == [pair for pair, _l in LOCAL_ORDER], coherence.visible_pairs()
    print(f"  QC tabs relabelled after {time.time() - t0:.1f} s: {qc_labels(window)[2]!r}; "
          f"with no remote the Coherence tab shows {len(coherence.visible_pairs())} panels, "
          f"the local pairs")

    # ------------------------------------ (9) the visible range -> Process
    ts.plots[0].setXRange(600.0, 1800.0, padding=0)
    pump(app)
    ts.use_button.click()
    pump(app)
    process = window.process_tab
    want = ((other.t0 + pd.Timedelta(minutes=10)).strftime(WINDOW_FMT),
            (other.t0 + pd.Timedelta(minutes=30)).strftime(WINDOW_FMT))
    got_fields = (process.start_edit.text(), process.end_edit.text())
    assert got_fields == want, f"Process tab window {got_fields}, expected {want}"
    assert window.tabs.currentWidget() is process
    print(f"(9) visible 600-1800 s -> Process tab window {got_fields[0]} to {got_fields[1]}")

    # ------------------------------------------------------ (10) goto_time
    state.goto_time.emit(other.t0 + pd.Timedelta(seconds=3000))
    pump(app)
    assert window.tabs.currentWidget() is ts, "goto_time did not bring the Time Series tab up"
    lo, hi = ts.visible_seconds()
    assert abs(lo - 2700) < 1e-6 and abs(hi - 3300) < 1e-6, (lo, hi)
    print(f"(10) goto_time(start + 3000 s): view [{lo:.0f}, {hi:.0f}] s")

    # ------------------------------------------ (11) the coherogram cursor
    window.tabs.setCurrentWidget(coherence)
    pump(app, 0.3)
    click_plot(app, coherence.band_plots[LOCAL_ORDER[2][0]], 1234.0 / 60.0)
    when = other.t0 + pd.Timedelta(seconds=1234)
    values = [float(c.value()) * 60.0 for c in coherence.cursors.values()]  # minutes -> s
    assert max(abs(v - 1234.0) for v in values) < 1.0, values
    assert f"{when:%Y-%m-%d %H:%M:%S} UTC" in coherence.time_label.text(), coherence.time_label.text()
    print(f"(11) a click on {LOCAL_ORDER[2][1]!r} at 1234 s: every cursor at "
          f"{np.mean(values):.1f} s, label {coherence.time_label.text()!r}")

    # -------------------------------------------------- (12) jobs, products
    runner = state.runner
    assert process.runner is runner, "the Process tab is not using State's runner"
    index = runner.add("trivial job", [sys.executable, "-c", "print('hello from job')"])
    runner.run_queue()
    wait_until(app, lambda: runner.jobs[index].status in ("done", "failed"), 60, "the trivial job")
    pump(app, 0.2)
    assert runner.jobs[index].status == "done", runner.jobs[index].status
    assert "hello from job" in "\n".join(runner.log), "job output missing from the shared log"
    assert "hello from job" in process.job_panel.log_view.toPlainText()
    # (18) continued: the console strip carries the same "$ ..." command and output
    trivial_command = runner.jobs[index].command
    console_tail = "\n".join(console.toPlainText().splitlines()[-6:])
    assert f"$ {trivial_command}" in console_tail, f"no '$ ...' command line in the console tail:\n{console_tail}"
    assert "hello from job" in console_tail, f"no job output in the console tail:\n{console_tail}"
    print("  console strip tail after the trivial job:\n    " + console_tail.replace("\n", "\n    "))
    edi = WORK / "tf" / f"{SITE}_rr-{REMOTE}.edi"
    assert edi.exists(), f"missing {edi}"
    index = runner.add("fake edi job", [sys.executable, "-c", f"print('wrote ' + {str(edi)!r})"])
    runner.run_queue()
    wait_until(app, lambda: runner.jobs[index].status == "done", 60, "the edi job")
    pump(app, 0.2)
    assert process.products == [edi], process.products
    assert process.show_button.isEnabled()
    process.show_button.click()
    pump(app, 0.3)
    edis = window.edis_tab
    assert window.tabs.currentWidget() is edis, "Show in View EDIs did not front the tab"
    wait_until(app, lambda: len(edis.checked_files()) == 2, 120, "both EDIs ticked")
    pump(app, 0.5)
    ticked = [name for name, _p in edis.checked_files()]
    assert ticked[0] == edi.name and ticked[1].startswith(f"{SITE} (lemimt)"), ticked
    fig = edis.figure
    assert len(fig.axes) >= 2, f"the mtpy figure has {len(fig.axes)} axes"
    curves = edi_curves(fig.axes[0])  # xy apparent resistivity, one curve per station
    assert len(curves) == len(ticked), f"{len(curves)} curves for {len(ticked)} ticked EDIs"
    rho_at_1s = []
    for name, (period, rho) in zip(ticked, curves):
        assert np.isfinite(rho).all() and (rho > 0).all() and period.size > 10, name
        rho_at_1s.append(float(rho[int(np.argmin(np.abs(period - 1.0)))]))
    ratio = max(rho_at_1s) / min(rho_at_1s)
    assert ratio < 3.0, f"rho at 1 s differs by {ratio:.2f}x: {rho_at_1s}"
    print(f"(12) trivial job done, log carries its output; Products picked {edi.name}; "
          f"View EDIs shows {ticked}, rho at 1 s {[f'{v:.1f}' for v in rho_at_1s]} Ohm m "
          f"(factor {ratio:.3f})")

    # --------------------------------------------- (13) the Process tab
    print("(13) the Process tab for D02, in the MATLAB Process Data tab's order:")
    window.tabs.setCurrentWidget(process)
    process.select_station(SITE)
    pump(app, 0.3)
    assert process.station_combo.currentData() == SITE, process.station_combo.currentData()
    assert process.remote_combo.currentData() == REMOTE, process.remote_combo.currentData()

    def at(widget):
        """(left, top, right, bottom) of a widget in the tab's coordinates."""
        top_left = widget.mapTo(process, widget.rect().topLeft())
        return top_left.x(), top_left.y(), top_left.x() + widget.width(), top_left.y() + widget.height()

    bar, summary, table = process.window_bar, process.summary, process.job_panel.table
    buttons = [process.add_button, process.run_button, process.reset_button,
               process.timing_button, process.qc_button, process.build_button,
               process.basemap_button]
    assert [b.text() for b in buttons] == ROW3_BUTTONS, [b.text() for b in buttons]
    lefts = [at(b)[0] for b in buttons]
    assert lefts == sorted(lefts) and len({at(b)[1] for b in buttons}) == 1, [at(b) for b in buttons]
    row1 = [at(w)[0] for w in (process.station_combo, process.remote_combo, summary)]
    assert row1 == sorted(row1) and at(summary)[0] > at(process.remote_combo)[2], row1
    column = [process.station_combo, bar, process.add_button, process.options, table]
    for upper, lower in zip(column, column[1:]):
        assert at(upper)[3] <= at(lower)[1], (upper, at(upper), lower, at(lower))
    assert at(process.site_map)[0] >= at(table)[2] and at(process.site_map)[1] >= at(bar)[3], \
        (at(process.site_map), at(table), at(bar))
    assert at(process.stack_builder)[1] >= at(process.site_map)[3], "the stack builder is not under the map"
    assert at(process.product_panel)[1] >= at(process.stack_builder)[3], "Products is not under the stack builder"
    lamp_l, status, lamp_r = (bar.lamps[0].mapTo(bar, bar.lamps[0].rect().center()),
                              bar.status.mapTo(bar, bar.status.rect().center()),
                              bar.lamps[1].mapTo(bar, bar.lamps[1].rect().center()))
    assert lamp_l.x() < status.x() < lamp_r.x() and abs(status.x() - bar.width() / 2) <= 3, \
        (lamp_l, status, lamp_r, bar.width())
    plot_box = at(bar.plot)
    assert at(bar.status)[3] <= plot_box[1], "the status line is not above the bar"
    assert at(bar.start_edit)[2] <= plot_box[0] and at(bar.end_edit)[0] >= plot_box[2], \
        (at(bar.start_edit), plot_box, at(bar.end_edit))
    print(f"  layout: row 1 station, remote, summary; then the bar (status centred between the "
          f"lamps, start field left, end field right); then {', '.join(ROW3_BUTTONS)}; the options; "
          f"the queue table; the map, stack builder and Products to the right of rows 3-5")

    site_map = process.site_map
    assert len(site_map.scatter.points()) == EXPECTED_SITES, len(site_map.scatter.points())
    assert site_map.colours[SITE] == site_map.STATION, site_map.colours[SITE]
    assert site_map.colours[REMOTE] == site_map.REMOTE, site_map.colours[REMOTE]
    greys = [n for n, c in site_map.colours.items() if c == site_map.GREY]
    assert len(greys) == EXPECTED_SITES - 2, len(greys)
    yaml_sites = yaml.safe_load(SURVEY_YAML.read_text(encoding="utf-8"))["sites"]

    def cosines_km(a: str, b: str) -> float:
        return law_of_cosines_km(yaml_sites[a]["latitude"], yaml_sites[a]["longitude"],
                                 yaml_sites[b]["latitude"], yaml_sites[b]["longitude"])

    expected_km = cosines_km(SITE, REMOTE)
    shown_km = float(site_map.distance_label.text().split(" at ")[1].split(" km")[0])
    assert abs(shown_km - expected_km) < 2.0, (shown_km, expected_km)
    assert site_map.distance_label.text().startswith(f"remote {REMOTE} at "), site_map.distance_label.text()
    print(f"  map: {len(site_map.scatter.points())} points, {SITE} green, {REMOTE} blue, "
          f"{len(greys)} grey; label {site_map.distance_label.text()!r} vs "
          f"{expected_km:.2f} km by the law of cosines")
    basemap_json, basemap_png = WORK / "basemap.json", WORK / "basemap.png"
    have_basemap = basemap_json.exists() and basemap_png.exists()
    if have_basemap:
        import json

        from PIL import Image

        meta = json.loads(basemap_json.read_text(encoding="utf-8"))
        with Image.open(basemap_png) as image:
            png = np.asarray(image.convert("RGB"))
        images = [item for item in site_map.plot.getPlotItem().items if isinstance(item, pg.ImageItem)]
        assert images == [site_map.basemap_item], (images, site_map.basemap_item)
        rect = images[0].mapRectToParent(images[0].boundingRect())
        want = (meta["lon_min"], meta["lat_min"], meta["lon_max"] - meta["lon_min"],
                meta["lat_max"] - meta["lat_min"])
        got = (rect.x(), rect.y(), rect.width(), rect.height())
        assert np.allclose(got, want, rtol=0, atol=1e-9), (got, want)
        data = images[0].image  # row-major: data row 0 at the rect's smallest y, the south edge
        assert data.shape == png.shape and np.array_equal(data[-1], png[0]) and np.array_equal(data[0], png[-1]), \
            "the basemap is not north up"
        assert images[0].zValue() < site_map.scatter.zValue(), "the basemap is not under the dots"
        assert meta["provider"] in site_map.attribution_item.toPlainText(), site_map.attribution_item.toPlainText()
        assert site_map.basemap_label.isHidden(), site_map.basemap_label.text()
        print(f"  basemap: {meta['provider']} zoom {meta['zoom']}, {png.shape[1]}x{png.shape[0]} px, an "
              f"ImageItem at lon {got[0]:.4f}..{got[0] + got[2]:.4f}, lat {got[1]:.4f}..{got[1] + got[3]:.4f} "
              f"= basemap.json, north row on top, under the dots")
    else:
        print(f"  basemap: SKIPPED -- no {basemap_json.name} / {basemap_png.name} in {WORK} "
              f"(run scripts/fetch_basemap.py once, online)")

    wait_until(app, lambda: {SITE, REMOTE} <= set(bar.spans), 60, "both recorded spans")
    pump(app, 0.3)
    assert set(bar.bars) == {SITE, REMOTE}, list(bar.bars)
    station_span, remote_span = bar.spans[SITE], bar.spans[REMOTE]
    want_lo = max(station_span[0], remote_span[0])
    want_hi = min(station_span[1], remote_span[1])
    lo, hi = bar.region.getRegion()
    assert abs(lo - want_lo.timestamp()) < 60 and abs(hi - want_hi.timestamp()) < 60, (lo, hi)

    lines = [label.text() for label in (summary.distance, summary.overlap, summary.length, summary.recommended)]
    km_line = number(lines[0], "Distance to remote: ", " km")
    assert abs(km_line - expected_km) < 0.1, (lines[0], expected_km)
    h5_station, h5_remote = archive_span(SITE), archive_span(REMOTE)
    h5_hours = (min(h5_station[1], h5_remote[1]) - max(h5_station[0], h5_remote[0])).total_seconds() / 3600
    overlap_line = number(lines[1], "Overlap available: ", " h")
    days_line = float(lines[1].split("(")[1].split(" days")[0])
    assert abs(overlap_line - h5_hours) < 0.051 and abs(days_line - h5_hours / 24) < 0.0051, (lines[1], h5_hours)
    assert abs(number(lines[2], "Window length: ", " h") - (hi - lo) / 3600) < 0.051, (lines[2], (hi - lo) / 3600)
    recommended = lines[3].split("Recommended remote: ")[1].split(" ")[0]
    assert recommended == RECOMMENDED, f"recommended {recommended!r}, expected {RECOMMENDED!r}: {lines[3]!r}"
    assert lines[3].endswith(f"({km_line:.1f} km, {overlap_line:.1f} h)"), lines[3]
    colour, wording = bar.status_state()
    hues = [lamp_hue(lamp) for lamp in bar.lamps]
    assert wording.startswith("remote covers the whole window"), wording
    assert all(90 <= h <= 150 for h in hues), f"lamps not green: hues {hues}"
    print(f"  spans {SITE} {station_span[0]} .. {station_span[1]}, {REMOTE} {remote_span[0]} .. "
          f"{remote_span[1]}; region defaults to their overlap")
    print(f"  summary {lines}; h5py overlap {h5_hours:.3f} h, law of cosines {expected_km:.2f} km")
    print(f"  status {wording!r}, lamp hues {hues} (green)")

    set_lo = station_span[0].ceil("min") + pd.Timedelta(hours=5)
    set_hi = set_lo + pd.Timedelta(hours=4)
    bar.region.setRegion((set_lo.timestamp(), set_hi.timestamp()))
    pump(app, 0.2)
    assert bar.window_text() == (set_lo.strftime(WINDOW_FMT), set_hi.strftime(WINDOW_FMT)), bar.window_text()
    for label, when in ((bar.start_local, set_lo), (bar.end_local, set_hi)):
        local = when + pd.Timedelta(hours=ACST_OFFSET_H)
        assert label.text() == f"{local:%H:%M} ACST", (label.text(), f"{local:%H:%M} ACST")
    assert summary.length.text() == "Window length: 4.0 h", summary.length.text()
    assert all(90 <= lamp_hue(lamp) <= 150 for lamp in bar.lamps), [lamp_hue(lamp) for lamp in bar.lamps]
    print(f"  region set to {bar.window_text()} UTC -> local {bar.start_local.text()} to "
          f"{bar.end_local.text()}; {summary.length.text()!r}")

    raw_dirs = Survey.from_yaml(SURVEY_YAML).site_dirs()
    partial_end = raw_span(raw_dirs[PARTIAL])[1]
    assert station_span[0] < partial_end < station_span[1], (PARTIAL, partial_end, station_span)
    process.remote_combo.setCurrentIndex(process.remote_combo.findData(PARTIAL))
    wait_until(app, lambda: PARTIAL in bar.spans, 30, f"{PARTIAL}'s recorded span")
    pump(app, 0.2)
    partial_km = number(summary.distance.text(), "Distance to remote: ", " km")
    assert abs(partial_km - cosines_km(SITE, PARTIAL)) < 0.1, (summary.distance.text(), cosines_km(SITE, PARTIAL))
    seen = {}
    for name, (lo_t, hi_t) in (("across", (partial_end - pd.Timedelta(hours=2), partial_end + pd.Timedelta(hours=2))),
                               ("after", (partial_end + pd.Timedelta(hours=1), partial_end + pd.Timedelta(hours=5)))):
        bar.region.setRegion((lo_t.timestamp(), hi_t.timestamp()))
        pump(app, 0.2)
        seen[name] = (bar.status_state()[1], [lamp_hue(lamp) for lamp in bar.lamps])
    wording, hues = seen["across"]
    covered = float(wording.split("remote covers ")[1].split(" %")[0]) if " % of" in wording else -1.0
    assert 45 <= covered <= 55 and all(25 <= h <= 50 for h in hues), f"across {PARTIAL}'s end: {seen['across']}"
    wording, hues = seen["after"]
    assert wording == "no overlap between station and remote" and all(h <= 15 or h >= 345 for h in hues), \
        f"after {PARTIAL}'s end: {seen['after']}"
    still = summary.recommended.text().split("Recommended remote: ")[1].split(" ")[0]
    assert still == RECOMMENDED, f"with remote {PARTIAL} the recommendation became {still!r}"
    print(f"  remote {PARTIAL} ({summary.distance.text()!r}, its files end {partial_end}): "
          f"2 h either side of its end {seen['across']} (amber); after it {seen['after']} (red); "
          f"still {summary.recommended.text()!r}")
    process.remote_combo.setCurrentIndex(process.remote_combo.findData(REMOTE))
    pump(app, 0.2)
    bar.region.setRegion((set_lo.timestamp(), set_hi.timestamp()))
    pump(app, 0.2)
    assert bar.window_text() == (set_lo.strftime(WINDOW_FMT), set_hi.strftime(WINDOW_FMT)), bar.window_text()

    recorded: list[list[str]] = []
    real_add, real_run = runner.add, runner.run_queue

    def record(label, argv, **details):
        recorded.append([str(a) for a in argv])
        return real_add(label, argv, **details)  # into the queue table; run_queue below runs nothing

    runner.add, runner.run_queue = record, (lambda: None)
    try:
        finished = [job.label for job in runner.jobs]
        assert [job.status for job in runner.jobs] == ["done", "done"], [job.status for job in runner.jobs]
        assert table.rowCount() == len(finished), (table.rowCount(), finished)
        for row, label in enumerate(finished):
            assert table_row(table, row) == [str(row + 1), label, "-", "-", "-", "done"], table_row(table, row)
        window_cell = f"{set_lo.strftime(WINDOW_FMT)} to {set_hi.strftime(WINDOW_FMT)}"

        def added_row(options: str) -> None:
            n = table.rowCount()
            assert table_row(table, n - 1) == [str(n), SITE, REMOTE, window_cell, options, "queued"], \
                table_row(table, n - 1)

        process.add_button.click()
        pump(app)
        argv = recorded[-1]
        assert argv[1].endswith("process_rr.py"), argv[1]
        assert argv[3:6] == [SITE, REMOTE, set_lo.strftime(WINDOW_FMT)], argv[3:6]
        assert argv[6] == set_hi.strftime(WINDOW_FMT), argv[6]
        assert not [a for a in argv if a.startswith("--")], f"survey defaults still put flags on: {argv}"
        assert table.rowCount() == len(finished) + 1, table.rowCount()
        added_row("defaults")
        process.options.min_spin.setValue(0.01)
        process.options.filters_check.setChecked(False)
        process.add_button.click()
        pump(app)
        changed = recorded[-1]
        assert changed[7:] == ["--min-period", "0.01", "--no-filters"], changed[7:]
        added_row("--min-period 0.01 --no-filters")
        process.options.min_spin.setValue(float(process.options.defaults["min_period"]))
        process.options.filters_check.setChecked(True)
        process.add_button.click()
        pump(app)
        assert not [a for a in recorded[-1] if a.startswith("--")], recorded[-1]
        added_row("defaults")
        print(f"  Add to queue: {' '.join(Path(a).name if a.endswith('.py') else a for a in argv[1:])}")
        print(f"    with the spinbox and the checkbox moved: ...{' '.join(changed[7:])}")
        print(f"    queue table row: {table_row(table, len(finished))}")

        advanced = process.options.advanced
        assert advanced.block.isHidden() and not advanced.toggle.isChecked(), "the advanced block is not collapsed"
        assert not ESTIMATOR_FLAGS & set(argv), f"untouched advanced block put flags on: {argv}"
        advanced.toggle.click()
        pump(app)
        assert advanced.block.isVisible(), "the advanced toggle did not expand the block"
        advanced.taper_combo.setCurrentText("hann")
        advanced.r0_spin.setValue(2.0)
        process.add_button.click()
        pump(app)
        tweaked = recorded[-1]
        assert tweaked[7:] == ["--taper", "hann", "--r0", "2.0"], tweaked[7:]
        added_row("--taper hann --r0 2.0")
        advanced.taper_combo.setCurrentText("boxcar")
        advanced.r0_spin.setValue(1.5)
        process.add_button.click()
        pump(app)
        assert not [a for a in recorded[-1] if a.startswith("--")], recorded[-1]
        added_row("defaults")
        advanced.toggle.click()
        pump(app)
        assert advanced.block.isHidden(), "the advanced toggle did not collapse the block"
        print(f"    advanced block collapsed and untouched: no estimator flag; taper hann, r0 2.0: "
              f"...{' '.join(tweaked[7:])}, Options {table_row(table, table.rowCount() - 2)[4]!r}; "
              f"put back: none")

        process.basemap_button.click()
        pump(app)
        fetch_argv = recorded[-1]
        assert fetch_argv[1:] == [str(REPO / "scripts" / "fetch_basemap.py"), str(state.survey_yaml)], fetch_argv
        assert table_row(table, table.rowCount() - 1)[1:5] == ["fetch_basemap (needs internet)", "-", "-", "-"], \
            table_row(table, table.rowCount() - 1)
        print(f"  Fetch basemap: {' '.join(Path(a).name if a.endswith('.py') else a for a in fetch_argv[1:])} "
              f"queued, not run")

        for name in STACK_MEMBERS:
            items = process.stack_builder.list.findItems(name, Qt.MatchExactly)
            assert items, f"{name} is not a stack candidate"
            items[0].setSelected(True)
        pump(app, 0.2)
        process.build_button.click()
        pump(app)
        stack_argv = recorded[-1]
        assert stack_argv[1].endswith("build_stack.py"), stack_argv[1]
        assert stack_argv[3] == f"STK{SITE}", stack_argv[3]
        assert stack_argv[-2:] == STACK_MEMBERS, stack_argv[-2:]
        assert stack_argv[4:6] == [set_lo.strftime(WINDOW_FMT), set_hi.strftime(WINDOW_FMT)], stack_argv[4:6]
        for name in STACK_MEMBERS:
            assert site_map.colours[name] == site_map.MEMBER, (name, site_map.colours[name])
        print(f"  Build stack: {' '.join(Path(a).name if a.endswith('.py') else a for a in stack_argv[1:])}; "
              f"{', '.join(STACK_MEMBERS)} painted orange on the map")
        print(f"  queue table: {table.rowCount()} rows, last {table_row(table, table.rowCount() - 1)}")
        shoot(app, window, "process", process)  # with the queued rows still in the table
        map_h, builder_h = process.site_map.height(), process.stack_builder.height()
        assert map_h >= 340, f"the Process tab's site map is {map_h} px tall, expected at least 340"
        print(f"(23) Process tab on screen: site map {map_h} px tall, stack builder {builder_h} px")

        process.reset_button.click()
        pump(app)
        assert table.rowCount() == 0 and runner.jobs == [], (table.rowCount(), runner.jobs)
        print("  Reset queue: the table has no rows and the runner no jobs")
    finally:
        runner.reset()  # anything still queued goes before run_queue is real again
        runner.add, runner.run_queue = real_add, real_run

    # -------------------------- (20) Add to queue no longer starts the queue
    # the interception above replaced `runner.add`; test the real path too --
    # `_queue()` is what every queuing button (Add to queue included) calls
    assert process.station_combo.currentData() == SITE and process.remote_combo.currentData() == REMOTE, (
        process.station_combo.currentData(), process.remote_combo.currentData())
    assert runner.jobs == [] and not runner.running, "the queue should be empty and idle here"
    real_index = process._queue(
        "trivial add-to-queue test", [sys.executable, "-c", "print('queued, not started')"]
    )
    pump(app, 0.2)
    assert runner.jobs[real_index].status == "queued", runner.jobs[real_index].status
    assert not runner.running, "queuing a job through the tab's own _queue() started the runner"
    assert process.status_label.text() == "1 job(s) queued - press Run queue", process.status_label.text()
    print(f"(20) _queue() left the job {runner.jobs[real_index].status!r}, runner idle, "
          f"status label {process.status_label.text()!r}")
    process.run_button.click()  # "Run queue": only now does it start
    pump(app)
    wait_until(app, lambda: runner.jobs[real_index].status in ("done", "failed"), 30,
              "the real Add-to-queue-path job, after Run queue")
    assert runner.jobs[real_index].status == "done", runner.jobs[real_index].status
    assert "queued, not started" in "\n".join(runner.log)
    print(f"  Run queue started it: status {runner.jobs[real_index].status!r}")
    runner.reset()  # leave the queue empty for what follows
    if have_basemap:
        before = process.site_map.basemap_item
        pretend = runner.add("pretend fetch_basemap", [sys.executable, "-c", "print('pretend fetch')",
                                                        str(REPO / "scripts" / "fetch_basemap.py")])
        runner.run_queue()
        wait_until(app, lambda: runner.jobs[pretend].status in ("done", "failed"), 30, "the pretend fetch job")
        assert runner.jobs[pretend].status == "done", runner.jobs[pretend].status
        after = process.site_map.basemap_item
        assert after is not None and after is not before, "a finished fetch_basemap job did not reload the map"
        print("  a finished job naming fetch_basemap.py reloaded the basemap (a new ImageItem)")
        runner.reset()

    process.select_station(OTHER)  # E08 declares no remote: nearest-among-longest-overlap decides
    wait_until(app, lambda: all(bar.known(name) for name in raw_dirs), 60, "every raw site's span")
    pump(app, 0.2)
    other_span = archive_span(OTHER)
    by_hours = {}
    for name, site_dir in raw_dirs.items():
        if name != OTHER:
            span = archive_span(name) if (WORK / "mth5" / f"{name}.h5").exists() else raw_span(site_dir)
            common = (min(span[1], other_span[1]) - max(span[0], other_span[0])).total_seconds() / 3600
            by_hours[name] = max(common, 0.0)
    top = max(by_hours.values())
    tie_hours = summary.TIE_HOURS  # the declared threshold, not the recommendation itself
    tied = sorted(name for name, hours in by_hours.items() if hours >= top - tie_hours)

    def _law_of_cosines_to_other(name: str) -> float:
        if name not in yaml_sites or OTHER not in yaml_sites:
            return float("inf")
        return cosines_km(OTHER, name)

    expected = min(tied, key=lambda n: (_law_of_cosines_to_other(n), n))
    text = summary.recommended.text()
    pick = text.split("Recommended remote: ")[1].split(" ")[0]
    assert pick == expected, (
        f"{OTHER}: recommended {pick!r}, expected {expected!r} (nearest among "
        f"{len(tied)} tied within {tie_hours:g} h of {top:.3f} h: {tied}): {text!r}")
    assert abs(float(text.rsplit(", ", 1)[1].split(" h")[0]) - by_hours[expected]) < 0.051, (text, by_hours[expected])
    print(f"  {OTHER} (no declared remote): {text!r}; computed here {expected} at "
          f"{by_hours[expected]:.3f} h ({_law_of_cosines_to_other(expected):.1f} km), "
          f"{len(tied)} site(s) tied within {tie_hours:g} h of {top:.3f} h: {tied}")


    # ------------------------------------------ (14) no "What to look for"
    for name, tab in (("Spectra", spectra), ("Spectrogram", spectrogram), ("Coherence", coherence)):
        found = hint_labels(tab)
        assert not found, f"the {name} tab still hints: {found}"
    from bbmt_gui.tabs.filters import RULE

    kept = [w for w in window.filters_tab.findChildren(QLabel) if w.text() == RULE]
    assert len(kept) == 1, f"the Filter Data tab's rule box is {len(kept)} labels, expected 1"
    print('(14) no "What to look for" label on Spectra, Spectrogram or Coherence; '
          'the Filter Data rule box is still there')

    # ------------------------------------------- (15) the filters round trip
    print("(15) Filter Data round trip on a copy of the survey folder:")
    copy_yaml = make_survey_copy()
    window.open_survey(copy_yaml)
    state.set_site(SITE)
    pump(app, 0.2)
    filters_tab = window.filters_tab
    copy_filters = SCRATCH / "filters.yaml"
    state.set_site("A07")
    pump(app, 0.2)
    rows_f = [filters_tab.list.item(i).text() for i in range(filters_tab.list.count())]
    assert rows_f == ["replace hx<-A06"], rows_f
    replace_form = filters_tab.forms["replace"]
    assert filters_tab.stack.currentWidget() is replace_form
    assert replace_form.boxes["hx"].isChecked() and not replace_form.boxes["hy"].isChecked()
    assert replace_form.donors["hx"].currentText() == "A06", replace_form.donors["hx"].currentText()
    print(f"  A07 loads into the replace form: {rows_f[0]!r}, donor {replace_form.donors['hx'].currentText()}")
    state.set_site(SITE)
    pump(app, 0.2)
    assert filters_tab.entries == [], filters_tab.entries
    filters_tab.add_filter("notch")
    filters_tab.forms["notch"].extra.setText("75, 125")
    pump(app)
    filters_tab.add_filter("cp")
    pump(app)
    assert len(filters_tab.entries) == 2, filters_tab.entries
    assert filters_tab.save(), "save() refused"
    pump(app, 0.2)
    survey = Survey.from_yaml(copy_yaml)
    got_filters = survey.site(SITE).filters
    assert got_filters == EXPECTED_FILTERS, f"\n got      {got_filters}\n expected {EXPECTED_FILTERS}"
    assert survey.site("A07").filters == A07_FILTERS, survey.site("A07").filters
    print(f"  saved {copy_filters}: {got_filters}")
    shoot(app, window, "filters", filters_tab)  # with the two filters still listed
    state.set_site(SITE)
    pump(app)
    while filters_tab.list.count():
        filters_tab.list.setCurrentRow(0)
        filters_tab.remove_filter()
    assert filters_tab.save(), "save() refused on the empty list"
    pump(app, 0.2)
    data = yaml.safe_load(copy_filters.read_text(encoding="utf-8")) or {}
    assert SITE not in data and data.get("A07") == A07_FILTERS, data
    assert (SURVEY_DIR / "filters.yaml").read_text(encoding="utf-8").count("A07") >= 1
    print(f"  emptied: filters.yaml keys now {list(data)}; the real filters.yaml was never written")

    # ------------------- (15) continued: the Metadata tab edits the same copy
    print("(15) Metadata edits on the same copy:")
    meta = window.metadata_tab
    window.tabs.setCurrentWidget(meta)
    pump(app, 0.3)
    assert meta.warning_label.isVisible(), "the generated_by line is hidden"
    assert meta.warning_label.text() == GENERATED_WARNING, meta.warning_label.text()
    mtable = meta.table
    mcols = [mtable.horizontalHeaderItem(c).text() for c in range(mtable.columnCount())]
    after_remote = mcols[mcols.index("remote") + 1:mcols.index("remote") + 5]
    assert after_remote == HEADER_COLUMNS, after_remote
    editable = {c for i, c in enumerate(mcols) if mtable.item(0, i).flags() & Qt.ItemIsEditable}
    assert editable == EDITABLE_COLUMNS, f"editable {sorted(editable)}"
    print(f"  yellow line: {meta.warning_label.text()!r}; {', '.join(HEADER_COLUMNS)} after remote; "
          f"{len(editable)} editable columns")
    row = next(r for r in range(mtable.rowCount()) if mtable.item(r, 0).text() == SITE)
    old_dipole = Survey.from_yaml(copy_yaml).site(SITE).dipole_length_ex
    before = copy_yaml.read_bytes()
    asked: list[str] = []
    real_ask = metadata_edit.ask_yes_no
    try:
        mtable.item(row, mcols.index("dipole_length_ex")).setText(NEW_DIPOLE)
        metadata_edit.ask_yes_no = answering(False, asked)
        meta.save_button.click()
        pump(app)
        assert len(asked) == 1 and "scripts/site_table_to_yaml.py" in asked[0], asked
        assert copy_yaml.read_bytes() == before, "answered No, the copy's survey.yaml changed"
        metadata_edit.ask_yes_no = answering(True, asked)
        meta.save_button.click()
        pump(app, 0.3)
    finally:
        metadata_edit.ask_yes_no = real_ask
    assert len(asked) == 2, asked
    after = copy_yaml.read_bytes()
    cut = before.index(b"\nsites:") + 1
    assert after[:cut] == before[:cut], "the bytes above sites: changed"
    assert before[before.index(b"\nworkspace:"):] == after[after.index(b"\nworkspace:"):], "the tail changed"
    old_lines, new_lines = before.decode("utf-8").splitlines(), after.decode("utf-8").splitlines()
    assert len(old_lines) == len(new_lines), (len(old_lines), len(new_lines))
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(changed) == 1, [(old_lines[i], new_lines[i]) for i in changed]
    i = changed[0]
    owner = next(old_lines[k] for k in range(i, -1, -1)
                 if old_lines[k].startswith("  ") and not old_lines[k].startswith("   "))
    assert owner.strip() == f"{SITE}:", f"the changed line is inside {owner.strip()!r}"
    assert old_lines[i].strip() == f"dipole_length_ex: {old_dipole}", old_lines[i]
    assert new_lines[i].strip() == f"dipole_length_ex: {NEW_DIPOLE}", new_lines[i]
    reread = Survey.from_yaml(copy_yaml).site(SITE).dipole_length_ex
    assert reread == float(NEW_DIPOLE) and state.survey.site(SITE).dipole_length_ex == float(NEW_DIPOLE), reread
    row = next(r for r in range(mtable.rowCount()) if mtable.item(r, 0).text() == SITE)
    assert mtable.item(row, mcols.index("dipole_length_ex")).text() == NEW_DIPOLE
    print(f"  Save asked once per press ({asked[0].splitlines()[0]!r}); No left the file alone; Yes "
          f"changed one line of {len(new_lines)}: {old_lines[i].strip()!r} -> {new_lines[i].strip()!r} "
          f"under {owner.strip()!r}, head ({cut} bytes) and trailing workspace: key unchanged")

    # ------------------------------------------ (21) Import site table...
    print("(21) Import site table on the same copy:")
    cells_before = metadata_cells(mtable)
    sites_before = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))["sites"]
    csv_path = SCRATCH / "two_rows.csv"
    csv_path.write_text(IMPORT_CSV, encoding="utf-8")
    assert meta.import_site_table(csv_path) == (2, 2)
    assert meta.status_label.text().startswith("2 of 2 sites matched"), meta.status_label.text()
    cells_after = metadata_cells(mtable)
    assert set(cells_after) == set(cells_before) and len(cells_after) == EXPECTED_SITES * len(mcols)
    moved = {k: v for k, v in cells_after.items() if v != cells_before[k]}
    assert moved == IMPORT_CELLS, moved
    try:
        metadata_edit.ask_yes_no = answering(True, asked)
        assert meta.save(), "save() refused the imported cells"
    finally:
        metadata_edit.ask_yes_no = real_ask
    pump(app, 0.3)
    sites_after = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))["sites"]
    assert sites_changes(sites_before, sites_after) == IMPORT_KEYS, sites_changes(sites_before, sites_after)
    print(f"  {meta.status_label.text() or 'saved'}; cells changed {sorted(moved)}; "
          f"sites block changed {sorted(IMPORT_KEYS)} and nothing else")
    state.set_site(SITE)
    shoot(app, window, "metadata", meta)  # the copy: yellow line, header columns, the edits

    # -------------------------------------------- (16) View EDIs on mtpy-v2
    print("(16) View EDIs on mtpy-v2:")
    window.tabs.setCurrentWidget(edis)
    edis.quick_check.setChecked(False)
    pump(app, 0.6)
    fig = edis.figure
    ticked = [name for name, _p in edis.checked_files()]
    assert len(ticked) == 2, f"expected the D02 pair still ticked, got {ticked}"
    edis.redraw()  # one timed overlay draw, nothing pending
    pump(app, 0.3)
    base_axes = len(fig.axes)
    assert base_axes >= 2, f"the mtpy figure has {base_axes} axes"
    for axes in fig.axes[:2]:
        assert len(edi_curves(axes)) == 2, f"{len(edi_curves(axes))} stations on one axes"
    labels = legend_labels(fig.axes[0])
    assert labels == ticked, f"legend {labels}, ticked {ticked}"
    print(f"  overlay of {ticked}: {base_axes} axes, one error-bar container per station, "
          f"legend {labels}, drawn in {edis.last_seconds:.2f} s")

    channels = state.survey.site(SITE).channels
    assert channels is not None and "hz" not in channels, channels
    assert not edis.tipper_radio.isEnabled(), "the tipper radio is enabled with no hz sensor"
    assert edis.tipper_radio.toolTip() == NO_HZ_TOOLTIP, edis.tipper_radio.toolTip()
    print(f"  {SITE} declares channels {channels}: 'plus tipper' disabled, "
          f"tooltip {edis.tipper_radio.toolTip()!r}")

    a07_rows = [i for i in edis._leaves() if i.text(0).startswith("A07")]
    assert a07_rows, "no A07 EDI in the aurora list"
    edis.quick_check.setChecked(True)
    pump(app, 0.6)
    before = edis.draws
    edis.tree.setCurrentItem(a07_rows[0])
    took = wait_for_draw(app, edis, before)
    pump(app, 0.3)
    title = fig.get_suptitle()
    assert a07_rows[0].text(0) in title, f"{a07_rows[0].text(0)} not in title {title!r}"
    assert len(edi_curves(fig.axes[0])) == 3, len(edi_curves(fig.axes[0]))
    assert [n for n, _p in edis.checked_files()] == ticked, "quick view changed the ticks"
    print(f"  quick view on {a07_rows[0].text(0)}: redrew in {took:.2f} s over the ticked pair, "
          f"title {title!r}")

    edis.tree.setFocus()
    before, row_before = edis.draws, edis.tree.currentItem().text(0)
    QTest.keyClick(edis.tree, Qt.Key_Down)
    row_after = edis.tree.currentItem().text(0)
    assert row_after != row_before, f"the down arrow left the row on {row_before!r}"
    took = wait_for_draw(app, edis, before)
    print(f"  down arrow: {row_before!r} -> {row_after!r}, redrew in {took:.2f} s")
    stepped = [row_after]
    before = edis.draws
    for _ in range(5):
        QTest.keyClick(edis.tree, Qt.Key_Down)
        stepped.append(edis.tree.currentItem().text(0))
    wait_for_draw(app, edis, before)
    pump(app, 0.5)
    draws = edis.draws - before
    assert len(set(stepped)) == 6, stepped
    assert draws <= 2, f"{draws} draws for five arrow keys: the {edis._timer.interval()} ms debounce is not working"
    print(f"  five arrow keys in a row stepped {len(set(stepped)) - 1} rows for {draws} draw(s)")

    edis.quick_check.setChecked(False)
    pump(app, 0.6)
    before, base_axes = edis.draws, len(fig.axes)
    edis.pt_radio.setChecked(True)
    wait_for_draw(app, edis, before)
    pump(app, 0.4)
    pt_labels = [ax.get_ylabel() for ax in fig.axes if ax.get_ylabel()]
    assert len(fig.axes) > base_axes, f"the phase tensor added no axes ({base_axes} -> {len(fig.axes)})"
    assert any("Phi_{min}" in text for text in pt_labels), pt_labels
    assert len(edi_curves(fig.axes[0])) == 2, "the phase tensor view lost a station"
    print(f"  plus phase tensor: {base_axes} -> {len(fig.axes)} axes, ylabels {pt_labels}")

    for name in ticked:
        edis.check(name, False)
    pump(app, 0.8)
    assert not edis.checked_files(), edis.checked_files()
    assert len(fig.axes) == 0, f"{len(fig.axes)} axes with nothing ticked and quick view off"
    hints = [t.get_text() for t in fig.texts]
    assert hints and "tick a transfer function" in hints[0], hints
    print(f"  quick view off, nothing ticked: no axes, hint {hints[0].splitlines()[0]!r}")

    for name in ticked:  # back to the picture the screenshot wants
        assert edis.check(name), name
    pump(app, 1.0)
    assert len(edi_curves(fig.axes[0])) == 2 and len(fig.axes) > 4, len(fig.axes)
    print(f"  back to the pair with the phase tensor row: {edis.status_label.text()}")

    # ------------------------------------------------------ (17) screenshots
    shoot(app, window, "edis", edis)

    # ------------------------------------------------- (22) New survey...
    print("(22) New survey... over a synthetic data root:")
    sys.path.insert(0, str(REPO / "tests"))
    from new_survey_unit import build_data_root  # the unit test's B423 writer, not the GUI's

    raw_root = NEW_SURVEY_DIR / "burra_2027"  # its folder name is the survey's default name
    build_data_root(raw_root)
    out_dir = NEW_SURVEY_DIR / "surveys"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    meta.surveys_dir = out_dir
    window.tabs.setCurrentWidget(meta)
    pump(app, 0.2)
    filled: dict = {}

    def fill_dialog() -> None:
        dialog = meta.findChild(metadata_edit.NewSurveyDialog)
        if dialog is None or not dialog.isVisible():
            QTimer.singleShot(100, fill_dialog)  # exec() has not shown it yet
            return
        dialog.folder_edit.setText(str(raw_root))
        filled["name"] = dialog.name_edit.text()
        filled["timezone"] = dialog.timezone_edit.text()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()

    QTimer.singleShot(100, fill_dialog)
    n_before = len(runner.jobs)
    started = time.time()
    meta.new_button.click()  # async now: returns once the dialog closed and the job is queued+started
    took_to_queue = time.time() - started
    assert filled.get("name") == raw_root.name, f"the name defaulted to {filled.get('name')!r}"
    assert len(runner.jobs) == n_before + 1, "New survey... did not queue a job"
    index = len(runner.jobs) - 1
    job = runner.jobs[index]
    assert "new_survey.py" in job.command, job.command
    # the window must not have blocked for the scan: click() itself returns
    # once the job is queued and started, well under the several seconds the
    # real script needs for 2 synthetic sites plus process start-up
    assert took_to_queue < 5.0, f"new_button.click() blocked for {took_to_queue:.1f} s -- not async"
    # the runner's own echo (JobRunner._append), not a loguru line: "$ ..."
    # with no "HH:MM:SS | name | " prefix -- see criterion 12/18's trivial job
    strip_now = console.toPlainText().splitlines()
    assert f"$ {job.command}" in strip_now, \
        "the job's command line had not reached the console strip while it ran"
    print(f"  dialog: name {filled['name']!r} (the folder's), timezone {filled['timezone']!r}; "
          f"queued and started in {took_to_queue:.2f} s (async), console already showing it")

    # app.processEvents() runs inside wait_until while the job (and the GUI)
    # keep going -- this is what "the window stayed responsive" means here
    wait_until(app, lambda: runner.jobs[index].status in ("done", "failed"), 60, "the new-survey job")
    assert runner.jobs[index].status == "done", "\n".join(runner.jobs[index].output[-8:])
    pump(app, 0.2)

    want_yaml = (out_dir / raw_root.name / "survey.yaml").resolve()
    assert want_yaml.exists(), f"{want_yaml} was not written"
    assert state.survey_yaml == want_yaml, f"opened {state.survey_yaml}, expected {want_yaml}"
    assert meta.table.rowCount() == len(SYNTHETIC), meta.table.rowCount()
    cells = metadata_cells(meta.table)
    for site, (serial, firmware) in SYNTHETIC.items():
        assert (cells[(site, "serial")], cells[(site, "firmware")]) == (serial, firmware), \
            (site, cells[(site, "serial")], cells[(site, "firmware")])
    assert meta.warning_label.isVisible() and "scripts/new_survey.py" in meta.warning_label.text()
    strip = console.toPlainText().splitlines()
    wrote = [line for line in strip if f"wrote {want_yaml}" in line]
    assert f"$ {job.command}" in strip and wrote, \
        "the console strip has no new_survey.py command or 'wrote' line"
    print("  finished: state.survey_yaml opened, window responsive throughout")
    print("  table: " + ", ".join(f"{s} serial {cells[(s, 'serial')]} firmware {cells[(s, 'firmware')]}"
                                  for s in SYNTHETIC) + f"; yellow line {meta.warning_label.text()!r}")
    print(f"  console: {job.command[:90]}...")

    assert len(SHOTS) == 9, f"{len(SHOTS)} screenshots, expected 9: {SHOTS}"
    assert SURVEY_YAML.read_bytes() == REAL_YAML, "the real surveys/curnamona_cube/survey.yaml changed"
    print("\nthe real survey.yaml is byte-identical; screenshots:")
    for path in SHOTS:
        print(f"  {path}")
    assert not SLOT_ERRORS, (
        f"{len(SLOT_ERRORS)} exception(s) were raised inside Qt slots:\n" + "".join(SLOT_ERRORS))
    print("  no exception escaped a Qt slot")
    print("\nPASS  gui_smoke")
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
