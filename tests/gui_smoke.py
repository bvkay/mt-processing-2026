# -*- coding: utf-8 -*-
"""
Smoke test for the crust.gui desktop GUI (run headless)

Drives the main window over the survey in surveys/curnamona_cube and checks
every tab against values computed here. The flow under test: a tree of
sites on the Time Series tab, a window under a site, one
click loads it, and the Spectra, Spectrogram and Coherence tabs show that
window. The test then goes through the Process, Metadata, Filter Data, View
EDIs and Cross-powers tabs, the survey tools (New survey, Import site table,
Build MTH5, the basemap fetch) and a mixed LEMI-423 / LEMI-424 / EDL survey.

It opens three archives, D02.h5, E08.h5 and A07.h5, read-only (through the
GUI and, for the independent check, through h5py), and for (28)-(31) the
scratch survey's MBJ21.h5 and EGFLP02.h5. `JobRunner.run_now` is wrapped at
the class level before the window is built: a call naming fetch_basemap.py
or ingest_site.py is recorded (`DIVERTED`) instead of started, and every
other call (New survey's) runs as usual, so the test runs offline and writes
no archive. The filter, metadata and mask round trips write to a copy of
the survey folder in the scratch directory, the New survey check writes
under the scratch directory too, and the files written into
`surveys/curnamona_cube/work/qc/` are PNGs.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1)  the window cannot be built, or its tabs are not, in order, Metadata,
     Time Series, Spectra, Spectrogram, Coherence, Filter Data, Cross-powers,
     Process, View EDIs; or the Metadata table does not show 61 sites with a
     `remote` column reading E08 for D02, and a `channels` column reading
     "Ex Ey Bx By" (the survey default [ex, ey, hx, hy] as its preset's
     label) for D02 and for A07 (both archived, so both cells drawn in the
     disabled grey #7a7a7a with the tooltip "archive built with the old set -
     Delete archive then Build MTH5 to change it") and for A02 (no archive)
     with no tooltip and not in that grey; or its `dc level` column does not
     follow `archive`, or reads other than "-" for A02 (no tooltip) and, with
     the tooltip `metadata.NO_RECORD_TIP`, for D02 and A07 when their
     archives' run comments (read here with h5py) hold no "dc level (" record;
     or the tab's dc level cell of an archive written here with h5py, two
     runs whose comments record hx +4.300e+07, hy +3.900e+07 and ex
     +2.000e+07 ok in both and ey +1.600e+09 open input? in the first and
     -3.000e+07 ok in the second, does not read "hx ok 4.30e7, hy ok 3.90e7,
     ex ok 2.00e7, ey open input? 1.60e9 in 1 of 2 runs" in #ef5350
     (`theme.BAD_COLOUR`), sort first (key 0) and list the eight channel runs
     in its tooltip; or the dark theme is not on: the
     application palette's Window colour is not #2b2b2b (`theme.WINDOW`),
     its Base not #1f1f1f, or the style not Fusion (behind the theme's
     proxy); or an unticked, unlabelled QCheckBox has no pixel at least 64
     lightness levels above the window grey (Fusion alone draws its outline
     from the window grey, darkened, and the box disappears);
(2)  the Time Series tree does not have 61 site rows, bold and collapsed, of
     which exactly five (A07, D02, D02L, E08, E08L, the archived ones; D02L
     and E08L are the 1 Hz sites scripts/decimate_site.py derives from D02
     and E08) are expandable
     (an indicator and no rows yet) while every other row holds one disabled
     child reading "no MTH5 yet - select the site and press Build MTH5"; or
     a real mouse click on D02's row does not expand it;
(3)  expanding D02 does not, within 30 s, yield 21 window rows, the first
     labelled with D02's record start as the runs' `time_period.start` attrs
     give it ("2021-06-29 06:55 UTC (2.0 h)") and the last "(1.3 h)";
(4)  a mouse click on window index 3 (the fourth) does not, within 60 s, bring
     `segment_loaded` for D02 with n = 7,200,000 samples per channel starting
     at that record start + 6 h, four channel plots with finite data over the
     whole window and x limits [0, 7200] s, the hint naming D02; or one click
     starts more than one worker (`qc_started` once); or the four plots are
     not stacked as follows: channels hx, hy, ex, ey top to bottom, left
     labels starting "Bx (", "By (", "Ex (", "Ey (", curve pens #4fc3f7
     (`theme.B_COLOUR`) on the first two and #ff5252 (`theme.E_COLOUR`) on
     the last two, a background brush of #1f1f1f, bottom tick values hidden
     on the upper three and shown on the bottom one, the vertical grid on
     and the horizontal grid off on all four, and no gap between them (each
     plot's top edge at the one above's bottom edge);
(5)  the independent check fails: ex over the first 60 s of that window, as
     the Segment holds it (float32, offset removed) plus the Segment's
     offset, and as the ex plot (the third) shows it, is not `allclose`
     (atol 1e-6 of the spread) to the same 60,000 samples read here with
     h5py alone: D02.h5 opened read-only, the record start from the earliest
     run's `time_period.start` attr, the sample rate from the `ex` dataset's
     `sample_rate` attr, the run covering the window found from the runs'
     `time_period` attrs and its `ex` dataset sliced by sample offset from
     that run's start, divided by the Segment's gain. The attrs and h5py
     alone place these samples in time, independently of
     `crust.gui.segment` and `crust.gui.archive`. This catches an
     off-by-one, wrong-run or wrong-t0 bug (the window starts 16,200,999
     samples into the second run);
(6)  the archive lock does not serialise: A07 expanded right after the click,
     while the store holds the lock for its load phase, must wait (no tree
     thread, A07 queued), then get its window rows once the store's load
     releases the lock, while the QC is still computing (the maths holds no
     lock);
(7)  `qc_ready` does not follow within 120 s with a `SegmentQC` whose PSD
     stages (two, at 1000 and 100 Hz) carry hx and r_hx, finite, whose
     (hx, r_hx) band curve has a median above 0.5 in the 0.1-1 s band, and
     whose spectrogram grids for all four channels are finite with at least
     20 time columns; or the three QC tabs do not draw it in this layout:
     Spectra: two panels titled "By-Ex (Zxy)" over "Bx-Ey (Zyx)", each
     with six finite positive curves (two stages each of the magnetic
     channel in #4fc3f7, the electric in #ff5252 and the remote's coil in
     #bdbdbd), bottom tick values on the lower panel only; each panel's
     ViewBox limits equal to the data extent computed here from the curves'
     own data (log10 of the smallest and largest positive frequency, and of
     the smallest and largest positive PSD at 0.003-400 Hz, below the
     anti-alias roll-off) and the view starting exactly there; a setRange a
     decade or two beyond every side clamped back to that extent; on each
     panel five dashed "Schumann" lines at 7.83, 14.3, 20.8, 27.3, 33.8 Hz
     and ten dashed "mains" lines at 50, 100, ... 500 Hz (Nyquist), and on
     the tab exactly one "Schumann" and one "50 Hz + harmonics" text label;
     Spectrogram: four meshes each more than 80 per cent finite, labelled
     Bx, By, Ex, Ey top to bottom, bottom tick values on the lowest only,
     each x limited to [0, 120] min with a 120 min maximum span, and a
     setXRange(-10, 200) clamped to [0, 120] on all four;
     Coherence: the two aligned columns, "By-Ex (Zxy)", "Bx-Ey (Zyx)",
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
     [0, 120]; and a click on a right-column panel at 15 min (900 s)
     putting the cursor at 15 min on all eight;
     or any of the three is not labelled with D02, the window's start and
     end (12:55:49 to 14:55:49 UTC) and remote E08;
(8)  a mouse click on E08's second window does not replace the plots with
     E08 (the hint names E08, the Segment is E08's, x limits reset to
     [0, 7200]) and, on its `qc_ready`, relabel the three QC tabs to E08
     (no remote is declared for E08) and leave the Coherence tab's right
     column out (four panels, the local pairs only);
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
     lemimt reference ticked and drawn: one mtpy error-bar container per
     station on the xy resistivity axes, finite and positive, apparent
     resistivities at 1 s within a factor of 3;
(13) the Process tab is not laid out as stated below, or
     does not do all of this for D02. Layout, from the widgets' positions:
     station combo, remote combo and summary left to right on row 1; below
     them the window bar; below that the buttons "Add to queue", "Run
     queue", "Reset queue", "Build stack" left to right on one row, and no
     "Timing check", "Site QC figures" or "Fetch basemap" button anywhere on
     the tab (nor the attributes or queue methods behind them); below them
     the run options, their "Advanced (aurora estimator)" block
     collapsed; below those the queue table; the site map right of the
     table and below the bar, the stack builder under the map and the
     Products list under that; in the bar, the status line centred (3 px)
     between the two lamps and above the plot, the start field left of the
     plot and the end field right of it. Behaviour: the declared-filters
     line (`RunOptions.describe_filters`) must read "D02 declares: none |
     E08 (remote) declares: none" (neither declares anything) and, called
     directly for A07 (a saved `replace`, no `A07_f<hash>.h5` variant
     built) "A07 declares: replace (filtered archive will be built first,
     from the raw archive)"; preselect remote E08 from `survey.yaml`; draw a
     site map of 61 points with D02 green, E08 blue and a distance label
     within 2 km of the D02-E08 separation computed here from the YAML
     coordinates by the spherical law of cosines (a different formula from
     the haversine under test); show both recorded spans on the window bar
     and default the region to their overlap; with
     `<workspace>/basemap.json` and `basemap.png` present (fetched by
     `scripts/fetch_basemap.py`; without them this check is skipped with a
     printed reason) the map must hold one `pg.ImageItem` below the dots
     whose rect in view coordinates equals the JSON's lon_min..lon_max,
     lat_min..lat_max (1e-9), whose top data row is the PNG's first (north)
     row and bottom data row its last; the credit must be the map plot's
     tooltip, "Basemap: <provider> - <attribution>" from basemap.json (its
     "(C)" as the copyright sign), with no visible label under the map (the
     grey line is hidden, and no visible QLabel on the tab carries the
     attribution); the map's ViewBox limits must be the JSON's extent (x and
     y limits lon_min..lon_max, lat_min..lat_max, maximum ranges their
     widths, 1e-9) and a setRange a degree beyond every side must leave the
     view inside that extent (the aspect lock may crop one axis); every
     site name must sit on a translucent dark box (the SURFACE
     grey, alpha between 100 and 230) drawn above the basemap and below the
     dots; the summary must read "Distance to remote:" within 0.1 km of that
     law-of-cosines figure, "Overlap available:" within 0.05 h (and its days
     within 0.005) of the D02-E08 overlap computed here from the two
     archives' run `time_period` attrs with h5py, "Window length:" within
     0.05 h of the region, and "Recommended remote: E08" (D02's declared
     remote) with that same distance and overlap; both lamps, as drawn (the
     pixel at each one's centre), green (hue 90-150) under "remote covers
     the whole window"; a region set programmatically (start + 5 h to
     start + 9 h) must show in both fields, both local labels (ACST is
     UTC+9:30) and "Window length: 4.0 h"; with D08 as the remote (a site
     whose span, from its B423 file names read here, ends inside D02's) the
     summary's distance must follow to D02-D08 by the law of cosines, a
     region dragged 2 h either side of D08's end must turn both lamps amber
     (hue 25-50) at 45-55 % covered, and one wholly after it red (hue under
     15 or over 345) with "no overlap", while the recommendation still names
     E08; back on E08, with `state.runner.add` wrapped to record every argv
     while `run_queue` does nothing (the jobs are queued and left waiting):
     the two finished jobs of (12) must be rows showing their label under
     Station and "-" under Remote, Window and Options; "Add to queue" must
     record process_rr.py D02 E08 with that window and **no** band options
     while they are the survey's and add a row reading Station D02, Remote
     E08, Window "<start> to <end>", Options "defaults", Status "queued";
     then `--min-period 0.01 --no-filters`, in the argv and in the new
     row's Options, once the spinbox and the checkbox are moved, and none
     again when they are put back; with the advanced block untouched no
     estimator flag (--taper ... --tolerance), then, with it expanded and
     the taper set to hamming (hann is the in-use default, so it emits no
     flag) and r0 to 2.0, exactly `--taper hamming --r0 2.0` at the end of
     the argv and "--taper hamming --r0 2.0" in the row's Options, and none
     again once they are put back; the row-3 "Build stack" button must
     record a build_stack.py argv naming the survey, the default stack name
     STKD02, the window and both chosen members (A02, A03), which the map
     then paints orange; "Reset queue" must leave the table with no rows and
     the runner with no jobs; then, with the runner real again and D02/E08
     still the pair, queuing a trivial job through the tab's own `_queue()`
     (what every button, including Add to queue, calls) must leave it
     "queued" and the runner idle (`status_label` reading "1 job(s) queued -
     press Run queue") until "Run queue" is pressed, after which it runs to
     completion; a trivial job whose argv names fetch_basemap.py, run for
     real, must make the map load the basemap again (a new ImageItem) when
     it finishes (skipped with the basemap check); and for E08, which
     declares no remote, the recommendation must be the nearest
     (`distance_km`, computed here by the law of cosines) among the raw
     sites whose overlap with E08 is within 1 h of the longest (a further
     tie going to the first by name), the longest itself computed here from
     the archives' run `time_period` attrs (h5py) for the archived sites and
     the B423 file names for the rest;
(14) any of the Spectra, Spectrogram or Coherence tabs still carries a
     label containing "What to look for" (a PDF explains it instead);
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
     visible and read "survey.yaml is generated by
     scripts/site_table_to_yaml.py: regenerating will overwrite edits made
     here"; channels, electric_gain, serial, firmware, start and end must be
     the six columns right after remote; exactly the eleven columns
     latitude, longitude, elevation, dipole_length_ex, dipole_length_ey,
     azimuth_ex, azimuth_ey, remote, timing, channels and notes must be
     editable; electric_gain, the EDL electric chain's declared gain, must
     read "-", read-only, with the tooltip "PR6-24 (EDL) sites only" on
     every row of this LEMI-423 copy, and its save rule
     (`metadata_edit.electric_gain_edit`) on an EDL survey whose default is
     10.0 must leave "10.0" typed over "10" unchanged, write 1.0 for "1" and
     5.0 for "5" typed over "10", drop the site's key for "10" typed over
     "1", and refuse "abc"; D02's dipole_length_ex typed as 51.25 and Save
     pressed must ask the Yes/No question once, naming the script, and
     answered No leave the file unchanged; pressed again and answered Yes,
     every byte above the `sites:` line and every byte from the copy's
     trailing `workspace:` key on must be unchanged, the file must keep its
     line count and differ in exactly one line, inside D02's entry (the
     nearest two-space key above it is "D02:"), where
     "dipole_length_ex: <old>" becomes "dipole_length_ex: 51.25"; and the
     reopened survey and the table must both read 51.25;
(16) the View EDIs tab, rebuilt on mtpy-v2, does not do all of this with
     the curnamona EDIs: with D02_rr-E08.edi and "D02 (lemimt)" ticked, the
     embedded canvas's figure must carry at least two axes, one mtpy
     error-bar container per station on each of them, and both labels in
     the resistivity legends (which shows the overlay is two stations and
     not one drawn twice); the Phase group's default "0 to 90 deg" must
     leave the yx phase axes' y limits exactly (0, 90), locked whatever the
     data do, with every plotted yx value in 0-90 for both EDIs (mtpy's own
     `phase_yx + 180` fold); "-180 to 180 deg" must redraw with the yx axes'
     y limits exactly (-180, 180) and every yx value in -180 to -90, the
     physical quadrant, for both EDIs; and switching back to "0 to 90 deg"
     must restore the (0, 90) limits; the Apparent resistivity group's min
     and max fields, blank by default, must leave both resistivity axes (xy
     and yx) on mtpy's own automatic scale until a field's
     `editingFinished` fires; typed 10 and 1000 must, after the debounce,
     clamp both axes' y limits to exactly (10, 1000); clearing max alone
     must put the low limit back to 10 and the high back to whatever mtpy
     drew automatically (checked against a draw with both fields blank);
     and typed 1000 and 10 (min >= max) must leave both axes at that same
     automatic scale and put "rho limits ignored" on the status line, so
     fields that leave the resistivity axes unclamped, or a bad pair
     applied silently, fail this; making A07's EDI the tree's current row
     with quick view on must bring one more draw within 2 s whose figure
     title names A07's file and whose xy axes now holds three containers,
     while the two ticked rows stay ticked; "plus phase tensor" must add
     axes to that figure, at least one of them labelled with mtpy's
     phi_min; the "plus tipper" radio must be disabled with the tooltip "no
     hz sensor on this survey", since curnamona declares channels
     [ex, ey, hx, hy] and the aurora tipper comes from an open Bz input;
     quick view off with nothing ticked must leave the figure with no axes
     at all and a hint drawn on it; and the arrow-key path must work: a
     QTest.keyClick(tree, Qt.Key_Down) moves the current row on and brings
     one more draw within 2 s, and five key clicks in quick succession move
     five rows but are debounced into at most two draws;
(17) the screenshots cannot be grabbed to `work/qc/`: gui_timeseries.png
     (tree and window), gui_timeseries_3s.png (a 3 s zoom), gui_spectra.png,
     gui_spectrogram.png, gui_coherence.png, gui_metadata.png,
     gui_process.png, gui_filters.png (the preview of (26), notch + cp on
     D02's fifth window), gui_edis.png, gui_process_mantle.png (35) and
     gui_edis_mantle.png (36), eleven in all; or any exception is
     raised inside a Qt slot on the way (PySide6 prints those and carries
     on; `sys.excepthook` collects them here); or the real
     `surveys/curnamona_cube/survey.yaml` is not identical at the end;
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
     window clicked in (4)) and at least one line containing
     "crust.timefreq" (the ladder: `cascade` and `psd_ladder` both call
     `logger.info`), a line logged from the segment store's worker thread
     as well as the GUI thread's;
(20) "Add to queue", or any other button that queues a job, starts the job
     by itself: with the runner real again (the (13) interception undone)
     and D02/E08 already the pair, a job queued through the Process tab's
     own `_queue()` is not left "queued" with the runner idle and
     `status_label` reading "1 job(s) queued - press Run queue" until "Run
     queue" is pressed, after which it does not run to completion; or, with
     a job queued that way and waiting, `JobRunner.run_now` (what New
     survey, the basemap fetch and Build MTH5 call) does not start its own
     job at once while the waiting job stays "queued" before, during and
     after that run, the runner idle at the end; or a job started with
     `run_now` from inside a `job_finished` slot (what a finished New survey
     does when its survey has no basemap) does not run to "done" with the
     runner idle after it;
(21) "Import site table..." (its `import_site_table`) with a two-row CSV
     (A03: dipole_length_ey 48 and notes "moved 20 m east"; B02:
     dipole_length_ey 51.5 and an empty notes cell) does not change exactly
     those three cells of the copy's table (every other cell, 61 sites by 20
     columns, reading as before), read "2 of 2 sites matched", and on Save
     (answered Yes) change exactly those three keys of the copy's parsed
     `sites:` block and nothing else;
(22) the Metadata tab's "New survey..." button, its dialog filled with the
     synthetic data root that `tests/new_survey_unit.py` builds (S01 and S02,
     in a scratch folder) and accepted: the click does not return once the
     job is queued on state.runner and started (not blocked for the scan:
     the dialog is closed and the job's "$ ..." command line, naming
     new_survey.py, already in the console strip before the wait below), or,
     waited out (job_finished, 60 s, app.processEvents pumped throughout so
     the window stays responsive) does not run `scripts/new_survey.py`,
     write `<scratch>/<name>/survey.yaml` and open it (`state.survey_yaml`),
     with the table showing two rows whose serial and firmware cells read
     "36" and "2.1" for S01 and "112" and "2.3" for S02, the yellow line
     naming scripts/new_survey.py, and the console strip also carrying the
     script's "wrote ..." line; nor does the name default to the folder's,
     the dialog's workspace field to `<data folder>/work` (that path in the
     job's `--workspace` and in the written survey.yaml's `workspace:`), or
     the survey's opening (its workspace has no basemap.json) run
     `<python> scripts/fetch_basemap.py <the new survey.yaml>` through
     `run_now`; nor does the dialog's "channels recorded" combo offer
     exactly the LEMI-423 presets "Ex Ey Bx By", "Ex Ey Bx By Bz", "Bx By
     (magnetics only)", "Bx By Bz" in that order with "Ex Ey Bx By"
     preselected, and, set to "Ex Ey Bx By Bz", put
     `--channels "Ex Ey Bx By Bz"` in the job's argv,
     `defaults: channels: [ex, ey, hx, hy, hz]` in the written survey.yaml
     and "Ex Ey Bx By Bz" in S01's and S02's channels cells;
(23) the Process tab's site map, on screen in the 1400 x 900 window, is less
     than 340 px tall;
(24) the basemap is not fetched on survey open exactly when it is missing:
     building the window over the real survey, whose workspace holds
     basemap.json, must call `run_now` for no fetch_basemap.py job; opening a
     scratch copy of the survey folder whose workspace is an empty scratch
     folder must call it once, with `<python> scripts/fetch_basemap.py
     <the copy's survey.yaml>`, and the site map must show its "no basemap"
     line; reopening the real survey must call it for none;
(25) the Time Series tab's "Build MTH5" button (on the real survey again) is
     not enabled with A02 (a raw site with no archive) the tree's current row
     and disabled, with the tooltip "archive exists", with D02; is not
     disabled while a job runs (a 2 s sleep started with `run_now`) and
     enabled again after it; pressed on A02, does not call `run_now` with
     exactly `<python> scripts/ingest_site.py <survey.yaml> A02` (recorded,
     not run) and put "building A02.h5 ..." in the tab's hint; or a
     finished job whose argv names ingest_site.py for A02 (a `python -c`
     that only prints, run through the real runner) does not, with
     `state.has_archive` made to answer True for A02, turn A02's row
     expandable and open (no "no MTH5 yet" child, the grey dropped, a read of
     its windows started) and the hint "built A02.h5 ..."; nor, once
     has_archive answers truthfully again, does `refresh_site("A02")` put the
     "no MTH5 yet" row back; or surveys/curnamona_cube/work/mth5/A02.h5
     exists at the end; or a filtered variant's own file (D02_fdeadbeef.h5,
     dropped in and removed again here) shows up in `archived_sites`,
     `stacked_remotes` or `remote_choices` (it is another archive of D02,
     neither a site nor a stacked remote of its own);
(26) the Filter Data tab does not preview the filter list on the loaded
     window. On a scratch copy of the survey folder (its workspace the real
     one), with the tab in front: choosing D02 in the tab's own site combo
     and D02's fifth window in its window combo (the Time Series tab left
     alone) must within 60 s load that window through the segment store (a
     Segment for D02 whose t0 is D02's record start + 8 h, the attrs' start
     of (3); the selection the same) and run the preview on that very
     Segment: with no filters the raw-only view, four time-series panels,
     each with exactly one visible curve, in its channel colour, and the two
     PSD panels with solid curves only. Then:
     adding "50 Hz + harmonics" with the form's defaults (50 Hz, 9
     harmonics) must bring, after the debounce, a preview whose filtered
     arrays differ from the raw on every channel while the store's raw
     arrays keep their SHA-1; whose Ex `line_excess` at 50 Hz on the 1000 Hz
     stage (computed here with `crust.timefreq.line_excess` from the
     result's raw and filtered ladders) drops by more than 15 dB; whose
     time-series view has 4 panels each holding a visible light grey curve
     (`theme.RAW_COLOUR`) and a visible curve in its channel colour, both
     over the whole window (7.2 M samples); and whose PSD view has the panels
     "By-Ex (Zxy)" and "Bx-Ey (Zyx)" each with dashed grey and solid coloured
     curves;
     a high-pass at 0.05 Hz added and moved above the notch must re-run the
     preview with the provenance lines in the list's order (the high-pass,
     then the notch);
     "Before" must hide every coloured curve and leave the grey ones
     visible, "After" the reverse, and "Both" show both again;
     the notch's q set to 25 and at once to 20 must re-run the preview
     exactly once (`started` not yet emitted 0.3 s later, then once), with
     q=20 in its provenance;
     unticking Bx under "Show" must hide Bx's time-series panel and every Bx
     curve on the PSD panels, and ticking it bring them back;
     with the list "50 Hz + harmonics" then "cathodic protection stack"
     (12 s) the preview's elapsed time is printed (the timing) and
     gui_filters.png shot with it on screen; the archive note must be empty
     and Delete archive hidden (D02's list was left unsaved, so
     `filters.yaml` still declares nothing for it and there is no variant
     file); switching to A07 (whose real `filters.yaml` entry, a `replace`,
     is saved, but which has no `A07_f<hash>.h5` yet) must read "filtered
     archive for this list: not built yet (built when processing starts)"
     with Delete archive still hidden (no variant file to delete), and
     switching back must read empty again;
     "burst removal (short transients)" added after them (the form's
     defaults) must re-run the preview with a last provenance line starting
     "burst:";
     "mains" added after it likewise, its line "mains:", its row
     LABELS["mains"];
     and removing every filter must bring the raw-only view back (the
     result's `filtered` None, one visible curve per panel in its channel
     colour, no dashed PSD curve);
(27) the Metadata tab's channels column does not edit and save the set on
     the scratch copy of (15): double-clicking A02's cell (`editItem`) must
     open a combo offering exactly the four LEMI-423 presets then "custom...",
     "Ex Ey Bx By" current; choosing "Bx By (magnetics only)" must set the
     cell to it; Save (answered Yes) must change the copy's parsed `sites:`
     block in exactly one key, A02's `channels` = [hx, hy] (no other site
     gains one), keep every byte above the `sites:` line and from the
     trailing `workspace:` key on, and `Survey.site("A02").channels` must
     read [hx, hy] while A03's stays the default; choosing "Ex Ey Bx By"
     again and saving must remove A02's key and leave the file identical to
     what it was before the first save; and "custom..." with the prompt
     answering "hx, hy, ex, ey, tx" (`channels_column.ask_channels`
     replaced) must set the cell to "hx, hy, ex, ey, tx" and make the tab's
     pending edits exactly {A02: {channels: [hx, hy, ex, ey, tx]}}, while
     "ex ey hx hy hz" typed the same way must come back as the preset
     "Ex Ey Bx By Bz" (nothing saved in either case);
(28) the mixed survey of `tests/instrument_samples.py` (scripts/new_survey.py
     over a scratch data root holding a synthetic LEMI-423 site, S01, and
     one real hour each of a LEMI-424, MBJ21, and an Earth Data PR6-24,
     EGFLP02, whose archives `ingest_site` writes into the scratch workspace
     when they are missing, as tests/ingest_unit.py does), opened with
     `window.open_survey`, does not show on the Metadata tab an "instrument"
     column right after "site", read-only, reading lemi423 for S01, lemi424
     for MBJ21 and edl for EGFLP02 (three values); or the Time Series tree
     does not hold exactly those three sites, MBJ21 and EGFLP02 expandable
     and S01 with the "no MTH5 yet" row;
(29) expanding MBJ21 and EGFLP02 does not list, within 30 s, exactly one
     window each, "2024-10-25 00:00 UTC (1.0 h)" and "2019-01-10 00:00 UTC
     (1.0 h)" (a one-hour record under the 24 h window `window_hours` gives
     both 1 Hz and 10 Hz);
(30) a click on MBJ21's window does not, within 60 s, draw seven panels,
     bx by bz e1 e2 e3 e4 top to bottom, left labels starting "Bx (", "By (",
     "Bz (", "E1 (", "E2 (", "E3 (", "E4 (", pens #4fc3f7 on the three
     magnetics and #ff5252 on the four electrics, whose E1 curve equals
     (atol 1e-6 of its spread) the 12th column of the sample file read here
     with numpy (a LEMI-424 has no filter chain, so the archive holds the
     recorded values); or its `qc_ready` does not follow within 60 s with the
     Spectra panels titled "By-E1 (Zxy)" and "Bx-E2 (Zyx)", each holding
     finite positive curves in exactly one magnetic and one electric pen (no
     remote), the Coherence tab's local panels labelled "By-E1 (Zxy)",
     "Bx-E2 (Zyx)", "Bx-By (magnetic)" and "E1-E2 (electric)", and the
     Spectrogram tab one image per channel, bx .. e4, labelled by `label`;
(31) a click on EGFLP02's window does not draw five panels, hx hy hz ex ey,
     labelled "Bx (", "By (", "Bz (", "Ex (", "Ey (", pens blue, blue, blue,
     red, red, whose Ex curve equals the sample's EX file (recorded
     microvolts) read here with numpy and divided by -500 (the reader's
     -50 m dipole times the x10 terminal box, so mV/km; atol 1e-6 of the
     spread); or its `qc_ready` does not bring Spectra panels titled "By-Ex
     (Zxy)" and "Bx-Ey (Zyx)" with finite positive curves. Four screenshots
     of (30) and (31) go to the instrument scratch folder, not `work/qc/`.
(32) the Filter Data tab's window combo does not mark the loaded window's
     row (bold, the theme's accent colour, suffixed "(loaded)") as the one
     and only marked row; or the mark does not move when another window is
     chosen (the old row plain again); or a site shown with nothing of it
     loaded has a marked row. The opened popup is saved as
     `work/qc/gui_filter_window_popup.png` (not counted in (17)).
(33) "Copy to sites...": **this fails if the copy does not write the
     ticked sites' lists as the source's, or touches an unticked site, or
     Append replaces**. With D02's list non-empty (criterion 26 leaves it
     with notch, cp, burst; a notch is added here if it does not), opening
     the dialog programmatically, ticking E08 and A07, keeping Replace and
     accepting must make both sites' `filters.yaml` entries equal D02's list
     while every other site's entry (including D02's own) is unchanged;
     Append onto E08 with a one-filter list must grow E08's list by that one
     entry, its own entries first and in order; and accepting with nothing
     ticked must leave the file unchanged.
(34) the Cross-powers tab: **this fails if the tab does not compute over
     the whole local-remote overlap by default, or the chunk impedances do
     not sit within a factor 3 of the processed EDI's, or a band is not drawn
     on its own grid, or a new chunk length or a window inside the computed
     one reads the archives again, or masking does not write and reload**.
     On a fresh scratch copy of the survey (`make_survey_copy`, as (26)
     redirects its saves; a masks.yaml left there removed first), with D02's
     fourth window (record start + 6 h to + 8 h, the attrs' start of (3))
     loaded through `state.set_selection` and the tab in front: a
     400-character status line and a 200-character band label must leave the
     tab's minimum width exactly what it was (both elide; the status tooltip
     holds the whole text). The status line sits on a row of its own under
     the controls, and what (34) asserts of it is the visible text: the
     label's own elided text, which must equal the whole text elided here
     (`QFontMetrics.elidedText` at the label's width). Its site combo on D02
     must preset remote E08 (D02's declared remote) and its window combo
     list D02's 21 QC windows after a first, current entry (the tree's
     window leaves it current), the whole overlap, equal within a sample to
     the span computed here from the two archives' run attrs with h5py (the
     later first start, the earlier last sample plus one sample:
     2021-06-29 06:55:49 to 2021-07-01 00:11:53.754 UTC, 41.3 h). With the
     band nearest 0.1 s chosen, Compute on it must within 120 s start
     exactly one compute (`tab.computes`), say "computed in" on the status
     line and give the base chunk count computed here from that span (whole
     600 s chunks, plus the tail when it is 300 s or more: 248), the first
     base chunk starting at the span's start within a sample and the last
     ending not after the span's end nor 300 s or more before it; the band's
     `band_view` on the base grid (multiple 1, its starts and ends the base
     grid's) with zxy, zyx, coh_xy, coh_yx and n_windows of shape [248], at
     least 95 % of the chunks with an estimate and the medians of their
     |Zxy| and |Zyx| within a factor 3 of the EDI's (below); the |Z| plot
     holding one spot per chunk with a finite estimate, per mode, and no
     span bar; "all bands" enabled; the time panel's x range covering every
     chunk start on its UTC date axis and its title naming both dates.
     On that same result, a band of level 5 (131 s windows; at 1000 Hz and
     600 s chunks `level_multiples` gives m = 2) must read "(20 min chunks)"
     in the band combo and end its label " · 124 chunks of 20 min", and be
     drawn on its own grid: 124 chunks of two base chunks, at least 90 % with
     an estimate, exactly one spot per mode per chunk with a finite log10
     |Z| (the per-chunk arrays of `bin_windows` hold nothing at level 5, so a
     tab drawing them shows no spot); a band of level 9 (m = 448 > 248) must
     read "(no chunk)", end its label " · no chunk (needs 74.7 h)", draw no
     spot, say "no chunk" in the |Z| plot's title and "no chunk at this
     band" in the count label, without an exception. **The deep band**: the
     first band of level 7 (2097 s windows, hop 1048.576 s, m = 28: chunks
     of 4.7 h) must hold the chunk count computed here, 9: 8 whole groups of
     28 base chunks, plus the 24-chunk remainder because it holds at least 4
     windows of the level's grid by centre (13, counted here from k x hop off
     the epoch), the last ending at the last base chunk's end and chunk 1
     starting at base chunk 28's start; read "(4.7 h chunks)" in the combo,
     end its label " · level 7 · 9 chunks of 4.7 h", draw one spot per
     finite chunk and mode on the |Z| plot with one span bar per mode whose
     left + right reach equals each chunk's span, and have "all bands"
     disabled with a tooltip saying a time cut would cut "4.7 h from every
     band". A rubber band round chunk 4's spot must select {4} on level 7;
     stepping on with the next-band arrow must keep it over the other
     level-7 bands and clear it at the first level-8 band with "selection
     of 1 chunk(s) cleared" on the status line. "all bands" ticked at the
     0.1 s band must show unticked (and disabled) at the deep band; chunk 4
     selected again must give one mask from that grid's start of chunk 4 to
     its end, bands the band's [pmin, pmax], not all, the status line
     reading "1 mask over 4.7 h, band <period> s only"; `masked_chunks` must
     then read 2 for chunk 4 (every window centred in it overlaps it), 1 for
     chunks 3 and 5 (each holds a window centred within one hop of the
     mask's edge whose 2 x hop span reaches into it, and windows further off
     that do not) and 0 elsewhere, and the |Z| and both polar plots draw
     exactly that: hollow, a lighter fill (opaque, of a higher HSL lightness
     than the series colour and not it) and filled (the series colour
     itself); the count label "3 of 9 chunks of 4.7 h masked (2 partly)";
     the tab shot to work/qc/gui_crosspower_deep.png. Back at the 0.1 s band
     "all bands" must be enabled and ticked again (as set there); a rubber
     band round base chunk 4 x 28 + 3 = 115 masked there must be an
     all-band mask over exactly that base chunk, which leaves level-5 chunk
     57 (base chunks 114-115) partly masked and drawn with the lighter fill;
     "Unmask selected" on level-7 chunk 4 must then cut the band's own mask
     out entirely and leave the all-band one, named on the status line by
     its start with "Remove"; Remove on every row empties the list. The
     chunk combo set to 1 min must regroup the same window store
     (`result["store"]` the same object, within 5 s, no compute started, the
     visible status line starting "regrouped to 1 min chunks in" and showing
     "no archive read") into the base chunk count computed here from the
     span (whole minutes from the minute at or before its start, plus the
     tail when it is 30 s or more), and draw one spot per mode per finite
     chunk at the 0.1 s band (level 2, m = 1) and one per finite chunk at a
     level-3 band (m = 2 at 1 min); back at 10 min it must hold 248 base
     chunks again, still with no compute started.
     Then the fourth QC window picked in the combo, inside the stored
     overlap, must be regrouped at once from the same store (no compute
     started, "regrouped to a QC window (2.0 h)" and "no archive read" on
     the visible status line, 12 base chunks over the window rounded out to
     whole minutes: from the minute at or before its start to the minute at
     or after its end, 12:55:00 to 14:56:00 UTC, the result's ``start`` and
     ``end`` saying so, as the store's shallow levels come in 60 s bins);
     Compute on it must within 120 s start one compute and give 12 base
     chunks, the first starting at the window's start, the band's zxy, zyx,
     coh_xy and coh_yx of shape [12], every chunk finite with n_windows > 0
     at that band, the medians of the chunks' |Zxy| and |Zyx| there within a
     factor 3 of the values of surveys/curnamona_cube/work/tf/D02_rr-E08.edi
     (read here with mt_metadata, at its period nearest the band's), and the
     regrouped chunks 1-11 within a median `REGROUP_TOL` (1e-6) relative of
     the computed ones in both modes (chunk 0, from the minute before the
     window's start when regrouped and from the start itself when computed
     alone, is printed only); the |Z| plot must hold 12 spots per mode.
     **A window picked while a compute runs**: with the QC window's own store
     kept, the whole overlap picked (outside that store: one compute starts
     by itself) and the QC window picked again before it returns (regrouped
     from the QC store at once), the overlap's store must, on its return, be
     kept and drawn over the QC window the combo shows rather than over the
     whole overlap (result kind QC, range the window's start and end, 12
     base chunks from the minute at or before its start, the new store, the
     overlap's, in the result, "picked meanwhile" on the visible status
     line); then Compute on the QC window with the overlap picked before it
     returns (regrouped from the overlap store at once) must leave the
     overlap drawn from the overlap store, 248 base chunks, the QC store
     dropped ("dropped" and "drawn from the stored windows" on the visible
     status line), one compute more each time. The QC window picked again
     (regrouped from the overlap store) must name the span drawn, not the
     one asked for, on the visible status line (with "rounded out to whole
     minutes") and in the |Z| plot's title: "2021-06-29 12:55:00 to
     2021-06-29 14:56:00 UTC", the window's start and end rounded out to
     whole minutes here. **A change of remote**: A07 picked (archived, its
     span covering D02's) must clear the drawing (no result, no spot) and
     say "window picked for D02 rr A07: press Compute", keeping the store,
     the QC window and the compute count; the whole overlap picked then must
     still draw nothing and start no compute. Compute on the QC window, with
     E08 picked back before it returns, must redraw D02 rr E08 at once from
     the overlap's store ("regrouped to a QC window (2.0 h) of D02 rr E08
     from the stored windows" first on the status line); on its return the
     A07 store must be kept aside ("not drawn: the pair shown changed
     meanwhile" on the visible status line, one compute more) and leave the
     tab's store the overlap's; the chunk combo set to 5 min must then
     regroup D02 rr E08 from that store: the drawn pair E08, the result's
     store the overlap's, the base chunk count computed here over the
     rounded window (whole 5 min from 12:55:00 to 14:56:00, plus a tail of
     150 s or more: 24), "D02 rr E08" in the |Z| title; a tab regrouping
     whatever store it last received draws A07, or no chunk. Back at 10 min,
     A07 picked again must draw the kept A07 store at once (12 chunks,
     nothing computed) and E08 picked again the overlap's. Compute on the QC
     window then gives it its own store again. **A compute queued behind a
     covering one**: the whole overlap picked (outside that store: one
     compute starts) and QC window 5 picked before it returns (outside it
     too: its compute queued) must, on the overlap's return, leave exactly
     one compute more, nothing queued or running, and QC window 5 drawn from
     the overlap's store (result kind QC, range QC window 5's start and end,
     the first base chunk at the minute at or before its start), "kept: the
     overlap store covers it" on the visible status line; a tab that runs
     the queued compute counts two and replaces the overlap's store with QC
     window 5's. Compute on the fourth QC window then gives the rest of (34)
     its fresh 12 chunks. The label beside the band combo must then name the
     combo's current band: "band <its index + 1> of <the band count>", its
     period (`tab.band_periods`, 4 significant digits), "level <its level>"
     (band_table's, read here) and its grid (" · <n> chunks of
     <m x 10 min>", or " · no chunk (needs"), the next-band arrow must move
     the combo one band on and the previous-band arrow one back, the label
     following each time; at the first band the previous arrow must be
     disabled and the next enabled, at the last band the next arrow
     disabled; the band brought back must be drawn again with 12 spots per
     mode. A rubber band over chunks 3 and 4 on the |Z| plot (the ViewBox's
     `selected` signal with a rectangle computed here round their spots, at
     the chunks' centres, `crosspower_rect`) must select exactly {3, 4}; the
     "all bands" box must be unticked (a time-panel mask covers the shown
     band only unless asked); ticked, "Mask selected" must add one mask,
     chunk 3's start to chunk 4's end, bands all, found_by time; "Save masks"
     must write the copy's masks.yaml holding exactly that one D02 entry,
     scope local
     (read here with yaml); the tab moved to E08 and back to D02 must list
     it again from the file; Compute on the same window again must draw
     chunks 3 and 4 hollow (no brush) and the ten others filled, on the |Z|
     plot and on both polar plots, and the count label read "2 of 12 chunks
     masked" (both fully masked: a count summing `masked_chunks`' 0/1/2
     codes says 4); and the real survey folder's masks.yaml, if any, must be
     left unchanged. The compute times are printed and the tab shot to
     work/qc/gui_crosspower_overlap.png (the whole overlap),
     gui_crosspower_deep.png (the deep band) and gui_crosspower.png (the QC
     window), none counted in (17); the level-5 band and the two 1 min bands
     to the scratch copy's folder (gui_crosspower_level5.png,
     gui_crosspower_60s_level2.png and gui_crosspower_60s_level3.png).
(35) the Process tab's engine combo does not offer exactly "aurora" and
     "mantle" with aurora chosen and the aurora estimator block enabled; or
     "mantle" chosen does not disable that block and put "engine mantle: the
     aurora estimator options above do not reach it" on the status line
     (D02 and E08 declare no masks, so no "--no-masks is passed" phrase);
     or Add to queue with mantle chosen and r0 moved to 2.0 meanwhile does
     not queue (never run: the job must stay "queued" with the runner idle)
     an argv ending exactly "--engine mantle", without any estimator flag or
     --no-masks, labelled from "process_rr D02 rr-E08 [mantle]" with Options
     "--engine mantle" in the queue table; or "aurora" chosen back does not
     re-enable the block, take the note off the status line and, with r0 put
     back, pass no flag again; the tab shot to work/qc/gui_process_mantle.png
     with mantle chosen and its row queued;
(36) the View EDIs list does not label the phase 1 head-to-head products
     by their sidecar's engine: the h2h-mantle EDI "... [mantle]", the
     h2h-aurora EDI "... [aurora]" (a sidecar without `engine`), the MANTLE
     fine-grid EDI "... h2h-mantle [mantle fine grid]" (the product stem's
     label, its own stem ending _fine) and D02_rr-E08.edi (no sidecar) by
     its file name alone; or quick view on the mantle row, with the D02 pair
     of (12) still ticked, does not draw exactly one verdict strip axes
     (label `tf_plot.VERDICT_STRIP`) under each of the two resistivity axes
     -- sharing its log period axis, its top `STRIP_GAP` below that axes'
     bottom and its bottom above the phase axes -- with the row labels
     ["ok", "snr_limited"] top to bottom, one bar collection per row whose
     period extent equals the shortest and longest period of that word's
     `freq_hz` scopes pooled over the report's verdicts (read here from
     <stem>.mantle_report.json with json alone) within 1e-6 relative and
     whose face colour is #66bb6a for ok and #ffa726 for snr_limited, and a
     legend naming the two words, the first strip's legend titled "MANTLE
     verdicts: ..."; or the label under the tree does not read the
     sidecar's engine_config.verdict_words ("ok 1, snr_limited 8") and
     "snr gate ran: True"; or "MANTLE notes..." is not enabled and does not
     open a visible dialog whose text carries "site D02" and the report's
     first note verbatim; or quick view moved to the aurora row does not
     leave the figure without a strip, the label empty and the button
     disabled; the tab shot to work/qc/gui_edis_mantle.png on the mantle row.
"""

from __future__ import annotations

import hashlib
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
    QApplication, QCheckBox, QComboBox, QDialogButtonBox, QLabel, QPushButton, QTreeWidgetItem,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.survey import Survey  # noqa: E402
from crust.timefreq import BANDS_S, line_excess  # noqa: E402
from crust.gui import channels_column, metadata_edit, tf_plot, theme  # noqa: E402
from crust.gui.tabs import metadata as metadata_module  # noqa: E402
from crust.gui.app import MainWindow  # noqa: E402
from crust.gui.jobs import JobRunner  # noqa: E402

sys.path.insert(0, str(REPO / "tests"))
import instrument_samples  # noqa: E402  (the mixed survey of (28)-(31))
from _scratch import scratch_dir  # noqa: E402

SURVEY_DIR = REPO / "surveys" / "curnamona_cube"
SURVEY_YAML = SURVEY_DIR / "survey.yaml"
SITE = "D02"
REMOTE = "E08"
OTHER = "E08"  # the site whose second window is clicked in (8)
ARCHIVED = ["A07", "D02", "D02L", "E08", "E08L"]  # D02L, E08L: the 1 Hz derived sites
EXPECTED_SITES = 61
EXPECTED_CHANNELS = ("hx", "hy", "ex", "ey")  # top to bottom: magnetics first
# the expected look, stated here rather than taken from the theme's helpers
WINDOW_GREY, SURFACE_GREY = "#2b2b2b", "#1f1f1f"
PANEL_LOOK = [("Bx", theme.B_COLOUR), ("By", theme.B_COLOUR), ("Ex", theme.E_COLOUR), ("Ey", theme.E_COLOUR)]
SPECTRA_PANELS = ["By-Ex (Zxy)", "Bx-Ey (Zyx)"]
SCHUMANN = [7.83, 14.3, 20.8, 27.3, 33.8]
MAINS = [50.0 * k for k in range(1, 11)]  # to Nyquist at 1000 Hz
Y_EXTENT_HZ = (0.003, 400.0)  # below the anti-alias roll-off, psd_qc.py's rule
WINDOW_MIN = 120.0  # the QC window in minutes, the Spectrogram and Coherence x unit
EXPECTED_TABS = ["Metadata", "Time Series", "Spectra", "Spectrogram", "Coherence",
                 "Filter Data", "Cross-powers", "Process", "View EDIs"]
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
ROW3_BUTTONS = ["Add to queue", "Run queue", "Reset queue", "Build stack"]
REMOVED_BUTTONS = {"Timing check", "Site QC figures", "Fetch basemap"}
REMOVED_NAMES = ("timing_button", "qc_button", "basemap_button",
                 "queue_timing_check", "queue_site_qc", "queue_basemap")
NO_ARCHIVE_ROW = "no MTH5 yet - select the site and press Build MTH5"
UNARCHIVED = "A02"  # a raw site with no archive: Build MTH5's site in (25)
ESTIMATOR_FLAGS = {"--taper", "--overlap", "--no-prewhiten", "--min-windows", "--max-iterations",
                   "--redescending-iterations", "--r0", "--u0", "--tolerance"}
ACST_OFFSET_H = 9.5  # what `timezone: Australia/Adelaide` means in June
HINT_TEXT = "What to look for"
NO_HZ_TOOLTIP = "no hz sensor on this survey"  # what the View EDIs tipper radio must say
WORK = SURVEY_DIR / "work"
SHOT_DIR = WORK / "qc"

SCRATCH = scratch_dir("gui_survey")

# what the Filter Data tab must write for D02, entry for entry
EXPECTED_FILTERS = [
    {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2, "extra": [75.0, 125.0]}},
    {"cp": {"period_s": 12.0, "window_minutes": 10.0,
            "channels": ["ex", "ey", "hx", "hy"], "refine": False, "reference": "ey"}},
]
A07_FILTERS = [{"replace": {"hx": "A06"}}]

# the Metadata tab, stated here rather than taken from the tab's own lists
EDITABLE_COLUMNS = {"latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey",
                    "azimuth_ex", "azimuth_ey", "remote", "timing", "channels", "notes"}
HEADER_COLUMNS = ["channels", "electric_gain", "serial", "firmware", "start", "end"]  # right after "remote"
# the channels column (27): the LEMI-423 presets in the combo's order, the default first
LEMI423_PRESETS = ["Ex Ey Bx By", "Ex Ey Bx By Bz", "Bx By (magnetics only)", "Bx By Bz"]
DEFAULT_CHANNELS = "Ex Ey Bx By"
MAGNETICS_ONLY = "Bx By (magnetics only)"
ARCHIVE_TIP = "archive built with the old set - Delete archive then Build MTH5 to change it"
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
NEW_SURVEY_CHANNELS = "Ex Ey Bx By Bz"  # (22): the dialog's channels combo, moved off its default
# (35), (36): the engine combo's items and the phase 1 MANTLE head-to-head products in work/tf
ENGINES = ["aurora", "mantle"]
MANTLE_EDI = WORK / "tf" / "D02_rr-E08_20260925-0820_h2h-mantle.edi"
AURORA_EDI = WORK / "tf" / "D02_rr-E08_20260925-0819_h2h-aurora.edi"
STRIP_WORDS = ["ok", "snr_limited"]  # the words the h2h-mantle report carries, in the strip's order
STRIP_COLOURS = {"ok": "#66bb6a", "snr_limited": "#ffa726"}  # theme.OK_COLOUR, theme.WARN_COLOUR
MANTLE_NOTE = "engine mantle: the aurora estimator options above do not reach it"


SLOT_ERRORS: list[str] = []
REAL_YAML = b""  # surveys/curnamona_cube/survey.yaml as the test found it

# offline, with no archive written: these two scripts are recorded, not run
NEVER_RUN = {"fetch_basemap.py", "ingest_site.py"}
DIVERTED: list[list[str]] = []
_real_run_now = JobRunner.run_now


def _diverting_run_now(self, label, argv, **details):
    """Run `JobRunner.run_now`, or only record a job naming one of NEVER_RUN in `DIVERTED`."""
    argv = [str(a) for a in argv]
    if any(Path(a).name in NEVER_RUN for a in argv):
        DIVERTED.append(argv)
        return -1
    return _real_run_now(self, label, argv, **details)


JobRunner.run_now = _diverting_run_now


def fetches() -> list[list[str]]:
    """Return the recorded fetch_basemap.py argvs."""
    return [argv for argv in DIVERTED if Path(argv[1]).name == "fetch_basemap.py"]


def _record_slot_error(exc_type, exc, tb) -> None:
    """Keep an exception raised inside a Qt slot (PySide6 prints it and carries on) for the final check."""
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
    """Pump events until `predicate()` holds; raise AssertionError naming `what` after `timeout` s."""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out after {timeout:.0f} s waiting for {what}")


def curve_data(plot, index: int = 0):
    """Return the (x, y) given to a curve on a pyqtgraph PlotWidget.

    The data behind the downsampled picture (`getOriginalDataset`), rather
    than the few hundred points drawn.
    """
    items = plot.getPlotItem().listDataItems()
    assert len(items) > index, f"a plot has {len(items)} curves, wanted index {index}"
    x, y = items[index].getOriginalDataset()
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def edi_curves(axes):
    """Return [(period, value)] of the data line inside each error-bar container of a matplotlib axes.

    One container per station, in the order mtpy drew them, so an overlay of
    two EDIs gives two curves.
    """
    out = []
    for container in axes.containers:
        line = container.lines[0]
        out.append((np.asarray(line.get_xdata(), dtype=float),
                    np.asarray(line.get_ydata(), dtype=float)))
    return out


def legend_labels(axes) -> list[str]:
    """Return the texts of a matplotlib axes' legend, or [] without one."""
    legend = axes.get_legend()
    return [] if legend is None else [t.get_text() for t in legend.get_texts()]


def wait_for_draw(app, tab, before: int, timeout: float = 2.0) -> float:
    """Return the seconds until the View EDIs tab has drawn again (its debounce is ~150 ms)."""
    start = time.time()
    wait_until(app, lambda: tab.draws > before, timeout, "a View EDIs redraw")
    return time.time() - start


def record_start_and_rate(site: str):
    """Return (t0, fs) of `site` from the archive's attrs alone.

    t0 is the earliest run's `time_period.start` and fs the `ex` dataset's
    `sample_rate`.
    """
    with h5py.File(WORK / "mth5" / f"{site}.h5", "r") as f:
        surveys = f["Experiment/Surveys"]
        station = next(surveys[s]["Stations"][site] for s in surveys if site in surveys[s]["Stations"])
        runs = [g for g in station.values() if g.attrs.get("mth5_type") == "Run"]
        t0 = min(pd.Timestamp(g.attrs["time_period.start"]) for g in runs)
        fs = float(runs[0]["ex"].attrs["sample_rate"])
    return t0, fs


def independent_ex(site: str, start: pd.Timestamp, seconds: float) -> np.ndarray:
    """Return ex counts over [start, start + seconds) read straight from the archive with h5py.

    The run whose `time_period` attrs cover `start` is sliced by sample
    offset from that run's own start at the dataset's `sample_rate` attr.
    The read uses h5py and the attrs alone, independent of
    `crust.gui.segment` and `crust.gui.archive`, so a wrong grid there
    shows as a mismatch.

    Raises:
        AssertionError: When no run covers `start`.
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
    """Click the text of a tree row with a real left mouse click."""
    tree.scrollToItem(item)
    pump(app, 0.1)
    rect = tree.visualItemRect(item)
    assert rect.isValid() and rect.height() > 0, f"{item.text(0)!r} is not on screen"
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    pump(app, 0.1)


def qc_labels(window) -> list[str]:
    """Return the title labels of the Spectra, Spectrogram and Coherence tabs."""
    return [tab.title_label.text() for tab in (window.spectra_tab, window.spectrogram_tab, window.coherence_tab)]


def assert_labelled(window, *needles: str) -> None:
    """Check that the title label of each QC tab contains every one of `needles`."""
    for name, text in zip(("Spectra", "Spectrogram", "Coherence"), qc_labels(window)):
        for needle in needles:
            assert needle in text, f"{name} label {text!r} lacks {needle!r}"


def law_of_cosines_km(lat1, lon1, lat2, lon2) -> float:
    """Return the great-circle distance in km by the spherical law of cosines.

    A different formula from the haversine under test.
    """
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    return 6371.0088 * math.acos(
        min(1.0, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(d_lon))
    )


def archive_span(site: str):
    """Return (earliest run start, latest run end) of `site` from its runs' `time_period` attrs, with h5py."""
    with h5py.File(WORK / "mth5" / f"{site}.h5", "r") as f:
        surveys = f["Experiment/Surveys"]
        station = next(surveys[s]["Stations"][site] for s in surveys if site in surveys[s]["Stations"])
        runs = [g for g in station.values() if g.attrs.get("mth5_type") == "Run"]
        return (min(pd.Timestamp(g.attrs["time_period.start"]) for g in runs),
                max(pd.Timestamp(g.attrs["time_period.end"]) for g in runs))


def raw_span(site_dir: Path):
    """Return a site's raw record from its B423 file names: first epoch to last epoch + the median spacing."""
    epochs = np.sort([int(f.stem) for f in Path(site_dir).rglob("*.B423")])
    return (pd.Timestamp(int(epochs[0]), unit="s", tz="UTC"),
            pd.Timestamp(int(epochs[-1] + np.median(np.diff(epochs))), unit="s", tz="UTC"))


def lamp_hue(lamp) -> int:
    """Return the hue (0-359; -1 for a grey) of the pixel at a lamp's centre, as the lamp is drawn."""
    image = lamp.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).hsvHue()


def number(text: str, prefix: str, unit: str) -> float:
    """Return the number between `prefix` and the first `unit` after it in `text`, which starts with `prefix`."""
    assert text.startswith(prefix), (text, prefix)
    return float(text[len(prefix):].split(unit)[0])


def table_row(table, row: int) -> list[str]:
    """Return the texts of one table row."""
    return [table.item(row, column).text() for column in range(table.columnCount())]


def click_plot(app, plot, x: float) -> None:
    """Click a pyqtgraph plot at x (in the plot's own unit) through its scene's click signal."""
    box = plot.getViewBox()
    y_mid = float(np.mean(box.viewRange()[1]))
    scene_pos = box.mapViewToScene(QPointF(float(x), y_mid))
    event = SimpleNamespace(button=lambda: Qt.LeftButton, scenePos=lambda: scene_pos)
    plot.scene().sigMouseClicked.emit(event)
    pump(app)


def panel_position(tab, pair):
    """Return the (row, column) of a Coherence band panel in the tab's grid."""
    row, column, _rs, _cs = tab.grid.getItemPosition(tab.grid.indexOf(tab.band_plots[pair]))
    return row, column


def hint_labels(tab) -> list[str]:
    """Return every label on a tab whose text carries the "What to look for" paragraph."""
    return [w.text() for w in tab.findChildren(QLabel) if HINT_TEXT in w.text()]


SHOTS: list[Path] = []


def shoot(app, window, name: str, tab) -> Path:
    """Grab one tab, in front, to work/qc/gui_<name>.png, one of the screenshots of (17)."""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    window.tabs.setCurrentWidget(tab)
    pump(app, 0.4)
    path = SHOT_DIR / f"gui_{name}.png"
    assert tab.grab().save(str(path)), f"could not save {path}"
    SHOTS.append(path)
    return path


def metadata_cells(table) -> dict[tuple[str, str], str]:
    """Return every cell of the Metadata table as {(site, column): text}."""
    columns = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    return {(table.item(r, 0).text(), columns[c]): table.item(r, c).text()
            for r in range(table.rowCount()) for c in range(table.columnCount())}


def sites_changes(before: dict, after: dict) -> dict:
    """Return {(site, key): new value} for every per-site key that differs between two parsed sites blocks."""
    out = {}
    for site in set(before) | set(after):
        old, new = before.get(site) or {}, after.get(site) or {}
        out.update({(site, key): new.get(key) for key in set(old) | set(new) if old.get(key) != new.get(key)})
    return out


def answering(answer: bool, asked: list):
    """Return a stand-in for `metadata_edit.ask_yes_no` that records the question and answers it."""
    return lambda _parent, _title, text: asked.append(text) or answer


def make_survey_copy() -> Path:
    """Copy the survey folder's YAML files to the scratch directory, the workspace pointing at the real one.

    Returns:
        Path: The copy's survey.yaml.
    """
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


# (30)/(31): the panels a LEMI-424 and an EDL window must draw, stated here rather than taken from the GUI
MIXED_SITES = {"S01": "lemi423", "MBJ21": "lemi424", "EGFLP02": "edl"}
LEMI424_PANELS = [("bx", "Bx", theme.B_COLOUR), ("by", "By", theme.B_COLOUR), ("bz", "Bz", theme.B_COLOUR),
                  ("e1", "E1", theme.E_COLOUR), ("e2", "E2", theme.E_COLOUR), ("e3", "E3", theme.E_COLOUR),
                  ("e4", "E4", theme.E_COLOUR)]
EDL_PANELS = [("hx", "Bx", theme.B_COLOUR), ("hy", "By", theme.B_COLOUR), ("hz", "Bz", theme.B_COLOUR),
              ("ex", "Ex", theme.E_COLOUR), ("ey", "Ey", theme.E_COLOUR)]
EDL_EX_GAIN = -50.0 * 10.0  # the reader's dipole filter (-L, L = 50 m) times the x10 terminal box


def check_panels(app, ts, look, truth_comp, truth) -> None:
    """Check the Time Series stack against `look` [(comp, label, pen)] and one curve against `truth` (read here)."""
    pump(app, 0.2)
    assert ts.comps == [c for c, _l, _p in look], f"Time Series panels {ts.comps}"
    for (comp, name, want_pen), plot in zip(look, ts.plots):
        text = plot.getAxis("left").labelText
        assert text.startswith(f"{name} ("), f"{comp}: labelled {text!r}, expected {name} (..."
        pen = pg.mkPen(plot.getPlotItem().listDataItems()[0].opts["pen"]).color().name()
        assert pen == want_pen.lower(), f"{comp}: pen {pen}, expected {want_pen}"
    _x, shown = curve_data(ts.plots[ts.comps.index(truth_comp)])
    atol = 1e-6 * float(np.ptp(truth))
    assert shown.size == truth.size and np.allclose(shown, truth, rtol=0, atol=atol), (
        f"{truth_comp} as plotted differs from the file by up to {np.max(np.abs(shown - truth)):g}")


def check_spectra(spectra, titles) -> None:
    """Check both Spectra panels: titled `titles`, with finite positive curves in one magnetic and one electric pen."""
    for (key, plot), title in zip(spectra.plots.items(), titles):
        assert plot.getPlotItem().titleLabel.text == title, (key, plot.getPlotItem().titleLabel.text, title)
        items = plot.getPlotItem().listDataItems()
        pens = sorted({pg.mkPen(item.opts["pen"]).color().name() for item in items})
        assert pens == sorted([theme.B_COLOUR, theme.E_COLOUR]), f"{title}: pens {pens}"
        for n in range(len(items)):
            _f, p = curve_data(plot, n)
            assert p.size > 10 and np.isfinite(p).all() and (p > 0).all(), f"{title} curve {n}"


def mixed_instruments(app, window) -> None:
    """Check (28)-(31): a LEMI-424 and an EDL site through the tree, the Time Series tab and the QC tabs."""
    t = time.time()
    paths = instrument_samples.ensure_archives()
    print(f"(28) mixed survey {instrument_samples.MIXED_YAML}; archives {[p.name for p in paths.values()]} "
          f"({time.time() - t:.1f} s to make or find)")
    window.open_survey(instrument_samples.MIXED_YAML)
    pump(app, 0.3)
    table = window.metadata_tab.table
    columns = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert columns[:2] == ["site", "instrument"], columns[:3]
    got = {table.item(r, 0).text(): table.item(r, 1).text() for r in range(table.rowCount())}
    assert got == MIXED_SITES, got
    assert not any(table.item(r, 1).flags() & Qt.ItemIsEditable for r in range(table.rowCount()))
    ts, store, tree = window.timeseries_tab, window.state.segment_store, window.timeseries_tab.tree
    window.tabs.setCurrentWidget(ts)
    pump(app, 0.2)
    rows = {r.text(0): r for r in tree.site_items()}
    assert sorted(rows) == sorted(MIXED_SITES), sorted(rows)
    expandable = sorted(n for n, r in rows.items()
                        if r.childCount() == 0 and r.childIndicatorPolicy() == QTreeWidgetItem.ShowIndicator)
    assert expandable == ["EGFLP02", "MBJ21"], expandable
    assert rows["S01"].child(0).text(0) == NO_ARCHIVE_ROW, rows["S01"].child(0).text(0)
    print(f"  instrument column {got}; not editable; tree {sorted(rows)}, expandable {expandable}")

    wants = {"MBJ21": "2024-10-25 00:00 UTC (1.0 h)", "EGFLP02": "2019-01-10 00:00 UTC (1.0 h)"}
    for site in wants:
        rows[site].setExpanded(True)
        wait_until(app, lambda s=site: len(tree.window_items(s)) == 1, 30, f"{site}'s window row")
    labels = {site: [w.text(0) for w in tree.window_items(site)] for site in wants}
    assert labels == {site: [text] for site, text in wants.items()}, labels
    print(f"(29) windows {labels}")

    loaded, results = [], []
    store.segment_loaded.connect(loaded.append)
    store.qc_ready.connect(results.append)
    sample = instrument_samples.MIXED_ROOT
    cases = (
        ("MBJ21", LEMI424_PANELS, "e1",
         np.loadtxt(sample / "MBJ21" / instrument_samples.LEMI424_FILE, usecols=11),
         ["By-E1 (Zxy)", "Bx-E2 (Zyx)"],
         ["By-E1 (Zxy)", "Bx-E2 (Zyx)", "Bx-By (magnetic)", "E1-E2 (electric)"], "lemi424"),
        ("EGFLP02", EDL_PANELS, "ex",
         np.loadtxt(sample / "EGFLP02" / instrument_samples.EDL_DAY / f"{instrument_samples.EDL_STAMP}.EX")
         / EDL_EX_GAIN,
         ["By-Ex (Zxy)", "Bx-Ey (Zyx)"],
         ["By-Ex (Zxy)", "Bx-Ey (Zyx)", "Bx-By (magnetic)", "Ex-Ey (electric)"], "edl"),
    )
    for site, look, truth_comp, truth, spectra_titles, coherence_labels, tag in cases:
        t0 = time.time()
        click(app, tree, tree.window_items(site)[0])
        wait_until(app, lambda s=site: loaded and loaded[-1].station == s, 60, f"segment_loaded for {site}")
        load_s = time.time() - t0
        check_panels(app, ts, look, truth_comp, truth)
        shot = instrument_samples.SCRATCH / f"gui_{tag}_timeseries.png"
        ts.grab().save(str(shot))
        wait_until(app, lambda s=site: results and results[-1].station == s, 60, f"qc_ready for {site}")
        qc_s = time.time() - t0
        qc = results[-1]
        check_spectra(window.spectra_tab, spectra_titles)
        local = [window.coherence_tab.labels[pair] for pair in window.coherence_tab.band_plots
                 if pair[1][:2] != "r_"]
        assert local == coherence_labels, local
        images = window.spectrogram_tab.images
        assert list(images) == [c for c, _l, _p in look], list(images)
        assert [image.plot.getAxis("left").labelText for image in images.values()] ==             [f"{name} period (s)" for _c, name, _p in look], [i.plot.getAxis("left").labelText for i in images.values()]
        window.tabs.setCurrentWidget(window.spectra_tab)
        pump(app, 0.3)
        window.spectra_tab.grab().save(str(instrument_samples.SCRATCH / f"gui_{tag}_spectra.png"))
        window.tabs.setCurrentWidget(ts)
        pump(app, 0.1)
        print(f"({30 if site == 'MBJ21' else 31}) {site}: segment_loaded {load_s:.1f} s, qc_ready {qc_s:.1f} s; "
              f"panels {ts.comps} labelled {[p.getAxis('left').labelText for p in ts.plots]}; {truth_comp} == the "
              f"file read here; Spectra {spectra_titles} at {[fs for fs, _f, _p in qc.psd_stages]} Hz; "
              f"Coherence {local}; Spectrogram {list(images)}; screenshots {shot.name} + gui_{tag}_spectra.png")


# ---------------------------------------------------------------- (34) the Cross-powers tab
CROSSPOWER_EDI = WORK / "tf" / "D02_rr-E08.edi"
CROSSPOWER_PERIOD_S = 0.1  # the band nearest this is computed
CROSSPOWER_MASKED = (3, 4)  # the chunks the rubber band goes round
REGROUP_TOL = 1e-6  # median relative |Z| difference, a QC window regrouped from the overlap's store vs
# computed alone, chunks 1-11: the same windows, only the blocks' medians and FIR margins differ


def crosspower_rect(centres_s: np.ndarray, chunks) -> "QRectF":
    """Return a rubber band round the spots of `chunks` on the time panel's |Z| plot.

    In view coordinates (x in epoch seconds, y in log10), from 60 s before
    the first chunk's centre, where its spot is drawn, to 60 s after the
    last's.
    """
    from PySide6.QtCore import QRectF

    lo, hi = centres_s[min(chunks)] - 60.0, centres_s[max(chunks)] + 60.0
    return QRectF(lo, -10.0, hi - lo, 20.0)


def crosspower_check(app, window) -> None:
    """Check criterion (34) on a copy of the survey.

    The whole overlap by default; compute and compare with the EDI; the band
    grids; the deep band's chunks, selection and masks; regrouping without
    reading; computes returning after another window or pair was picked; the
    band label and arrows; select, mask, save, reload, hollow.
    """
    import re

    import pyqtgraph as pg
    from mt_metadata.transfer_functions.core import TF
    from crust.crosspower import band_table, band_view, level_multiples, masked_chunks
    from crust.masks import iso
    from PySide6.QtGui import QColor, QFontMetrics
    from crust.gui.tabs.crosspower import OVERLAP, QC

    print("(34) the Cross-powers tab, on a copy of the survey folder:")
    real_masks = SURVEY_DIR / "masks.yaml"
    real_masks_before = real_masks.read_bytes() if real_masks.exists() else None
    (SCRATCH / "masks.yaml").unlink(missing_ok=True)
    window.open_survey(make_survey_copy())
    pump(app, 0.3)
    state, tab = window.state, window.crosspower_tab
    combo = tab.window_combo
    t_rec, fs = record_start_and_rate(SITE)
    sample = pd.Timedelta(seconds=1.0 / fs)
    start, end = t_rec + pd.Timedelta(hours=6), t_rec + pd.Timedelta(hours=8)
    state.set_selection(SITE, start, end)  # what a click on the tree's fourth D02 window does
    window.tabs.setCurrentWidget(tab)
    tab.select_site(SITE)

    # the status line and the band label elide: the tab's minimum width is the same with long texts in both
    tab.layout().activate()
    narrow = tab.minimumSizeHint().width()
    saved = tab.status.text(), tab.band_label.text()
    tab.status.setText("x" * 400)
    tab.band_label.setText("y" * 200)
    tab.layout().activate()
    widened = tab.minimumSizeHint().width()
    assert widened == narrow and tab.status.toolTip() == "x" * 400, (narrow, widened)
    tab.status.setText(saved[0])
    tab.band_label.setText(saved[1])

    def visible_status() -> str:
        """The status line as the label paints it (its own elided text), which must equal the whole text
        elided here with the label's font at the label's width."""
        painted = QLabel.text(tab.status)
        here = QFontMetrics(tab.status.font()).elidedText(tab.status.text(), Qt.ElideRight, tab.status.width())
        assert painted == here, (painted, here, tab.status.width())
        return painted

    def entries():
        return [combo.itemData(k) or (None, None, None) for k in range(combo.count())]

    def qc_index():
        return next(k for k, data in enumerate(entries())
                    if data[0] == QC and (pd.Timestamp(data[1]), pd.Timestamp(data[2])) == (start, end))

    wait_until(app, lambda: tab.site() == SITE and [e[0] for e in entries()].count(QC) == N_WINDOWS_D02, 60,
               "the Cross-powers tab's D02 QC windows")
    wait_until(app, lambda: tab.remote_combo.currentData() == REMOTE, 60, "the Cross-powers remote preset")
    wait_until(app, lambda: (combo.currentData() or (None, None))[1] is not None, 60,
               "the whole overlap from the two spans")
    (d0, d1), (e0, e1) = archive_span(SITE), archive_span(REMOTE)
    here = (max(d0, e0), min(d1, e1) + sample)  # time_period.end is the last sample
    current = combo.currentData()
    assert combo.currentIndex() == 0 and current[0] == OVERLAP, (combo.currentIndex(), current)
    assert abs(current[1] - here[0]) <= sample and abs(current[2] - here[1]) <= sample, (current, here)
    level, lo, hi = band_table(tab.scheme)
    periods = 1.0 / np.sqrt(lo * hi)
    j = int(np.argmin(np.abs(np.log(periods / CROSSPOWER_PERIOD_S))))
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j))
    edi = TF()
    edi.read(CROSSPOWER_EDI)
    k = int(np.argmin(np.abs(np.log(np.asarray(edi.period) / periods[j]))))
    z_edi = np.asarray(edi.impedance.data)[k]

    def compute(what):
        tab.result = None
        began = time.time()
        tab.compute_button.click()
        wait_until(app, lambda: tab.result is not None, 120, what)
        pump(app, 0.2)
        return time.time() - began

    computes = tab.computes
    took_all = compute("the chunk impedances over the whole overlap")
    assert tab.computes == computes + 1 and "computed in" in tab.status.text(), (tab.computes, tab.status.text())
    r = tab.result
    total_s = (here[1] - here[0]).total_seconds()
    want_n = int(total_s // 600.0) + (1 if total_s % 600.0 >= 300.0 else 0)
    n_all = len(r["base_starts"])
    first, last = r["base_starts"][0], r["base_ends"][-1]
    assert n_all == want_n, (n_all, want_n, total_s)
    assert abs(first - here[0]) <= sample, (first, here[0])
    assert last <= here[1] + sample and (here[1] - last).total_seconds() < 300.0, (last, here[1])
    v = band_view(r, j)  # level 2: one chunk per base chunk
    assert v["multiple"] == 1 and (v["starts"] == r["base_starts"]).all() and (v["ends"] == r["base_ends"]).all()
    for key in ("zxy", "zyx", "coh_xy", "coh_yx", "n_windows"):
        assert v[key].shape == (n_all,), (key, v[key].shape)
    has = (v["n_windows"] > 0) & np.isfinite(v["zxy"]) & np.isfinite(v["zyx"])
    assert has.sum() >= 0.95 * n_all, (int(has.sum()), n_all)
    ratios_all = {mode: float(np.median(np.abs(v[f"z{mode}"][has])) / abs(z_edi[a, b]))
                  for mode, (a, b) in (("xy", (0, 1)), ("yx", (1, 0)))}
    for mode, ratio in ratios_all.items():
        assert 1 / 3 < ratio < 3, ("whole overlap", mode, ratio, periods[j], edi.period[k])
    z_plot = tab.time_plots[0]

    def spots_per_mode():
        return [len(item.scatter.points()) for item in z_plot.getPlotItem().listDataItems()]

    def finite_groups(jj):
        view = band_view(tab.result, jj)
        with np.errstate(divide="ignore", invalid="ignore"):
            return view, [int(((view["n_windows"] > 0) & np.isfinite(np.log10(np.abs(view[f"z{mode}"])))).sum())
                          for mode in ("xy", "yx")]

    spots = spots_per_mode()
    assert spots == finite_groups(j)[1], (spots, finite_groups(j)[1])
    x0, x1 = z_plot.getViewBox().viewRange()[0]
    assert x0 <= first.timestamp() and x1 >= r["base_starts"][-1].timestamp(), (x0, x1, first, last)
    axis = tab.time_plots[-1].getAxis("bottom")
    assert isinstance(axis, pg.DateAxisItem), type(axis)
    title = z_plot.getPlotItem().titleLabel.text
    assert first.date() != last.date() and f"{first:%Y-%m-%d}" in title and f"{last:%Y-%m-%d}" in title, title
    ticks = [s for spacing, values in axis.tickValues(x0, x1, axis.width())
             for s in axis.tickStrings(values, 1.0, spacing)]
    assert tab.all_bands.isEnabled(), "all bands off at a band shown per base chunk"
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    shot_all = SHOT_DIR / "gui_crosspower_overlap.png"
    assert tab.grab().save(str(shot_all)), f"could not save {shot_all}"
    print(f"    whole overlap by default (the tree's window loaded): {here[0]} to {here[1]} "
          f"({total_s / 3600:.1f} h) as the attrs give it; {n_all} base chunks of 600 s, {first} to {last}, "
          f"computed in {took_all:.1f} s; {int(has.sum())} with an estimate at {periods[j]:.4g} s, median |Z| / "
          f"EDI's xy {ratios_all['xy']:.3f}, yx {ratios_all['yx']:.3f}; {spots} spots; axis ticks {ticks}; "
          f"tab minimum width {narrow} px with a 400-character status and a 200-character band label; "
          f"{shot_all.name} saved")

    def bars(plot):
        return [item for item in plot.getPlotItem().items if isinstance(item, pg.ErrorBarItem)]

    multiples = level_multiples(tab.scheme, fs, 600.0)
    assert multiples[5] == 2 and multiples[7] == 28 and multiples[9] == 448, multiples
    assert not bars(z_plot), "a bar drawn at a band shown per base chunk"
    j5 = int(np.flatnonzero(level == 5)[0])
    j9 = int(np.flatnonzero(level == 9)[0])
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j5))
    pump(app, 0.1)
    view5, want5 = finite_groups(j5)
    assert view5["multiple"] == 2 and len(view5["starts"]) == n_all // 2 == 124, (view5["multiple"],
                                                                                  len(view5["starts"]))
    assert min(want5) >= 0.9 * len(view5["starts"]) and spots_per_mode() == want5, (spots_per_mode(), want5)
    assert tab.band_combo.currentText().endswith("(20 min chunks)"), tab.band_combo.currentText()
    assert tab.band_label.text().endswith(" · 124 chunks of 20 min"), tab.band_label.text()
    tab.grab().save(str(SCRATCH / "gui_crosspower_level5.png"))  # the scratch folder: not counted, not the survey's
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j9))
    pump(app, 0.1)
    assert tab.band_combo.currentText().endswith("(no chunk)"), tab.band_combo.currentText()
    assert tab.band_label.text().endswith(" · no chunk (needs 74.7 h)"), tab.band_label.text()
    assert len(band_view(tab.result, j9)["starts"]) == 0 and sum(spots_per_mode()) == 0, spots_per_mode()
    assert "no chunk" in z_plot.getPlotItem().titleLabel.text and tab.count_label.text().startswith(
        "no chunk at this band"), (z_plot.getPlotItem().titleLabel.text, tab.count_label.text())

    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j))
    pump(app, 0.05)
    tab.all_bands.setChecked(True)  # the user's choice at a base-chunk band: shown off (unticked) at the deep band
    # the deep band: level 7 (2097 s windows, hop 1048.576 s) on chunks of 28 base chunks (4.7 h). Its chunk
    # count here: the whole groups of 28, plus the remainder when it holds MIN_WINDOWS (4) windows of the
    # level's grid (windows k * hop from the epoch lying inside the overlap, by centre)
    jd = int(np.flatnonzero(level == 7)[0])
    hop = 64 * 4**7 / fs
    n_whole, rest = divmod(n_all, 28)
    lo_s, hi_s = r["base_starts"][0].timestamp(), r["base_ends"][-1].timestamp()
    k0, k1 = int(np.ceil(lo_s / hop)), int(np.floor((hi_s - 2 * hop) / hop))
    centres = (np.arange(k0, k1 + 1) + 1.0) * hop
    in_rest = int(((centres >= r["base_starts"][28 * n_whole].timestamp()) & (centres < hi_s)).sum()) if rest else 0
    want_deep = n_whole + (1 if in_rest >= 4 else 0)
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(jd))
    pump(app, 0.1)
    view_d, want_d = finite_groups(jd)
    assert view_d["multiple"] == 28 and len(view_d["starts"]) == want_deep, (view_d["multiple"],
                                                                             len(view_d["starts"]), want_deep)
    assert view_d["ends"][-1] == r["base_ends"][-1] and view_d["starts"][1] == r["base_starts"][28], view_d["starts"]
    assert tab.band_combo.currentText().endswith("(4.7 h chunks)"), tab.band_combo.currentText()
    assert tab.band_label.text().endswith(f" · level 7 · {want_deep} chunks of 4.7 h"), tab.band_label.text()
    assert spots_per_mode() == want_d and min(want_d) >= want_deep - 1, (spots_per_mode(), want_d)
    spans_s = (np.asarray(view_d["ends"].asi8) - np.asarray(view_d["starts"].asi8)) / 1e9
    for bar, (item, _x, _y, idx, _c) in zip(bars(z_plot), tab.items[z_plot]):  # a bar over each chunk's span
        assert np.allclose(bar.opts["left"] + bar.opts["right"], spans_s[idx]), (bar.opts["left"], spans_s)
    assert len(bars(z_plot)) == 2, bars(z_plot)
    assert not tab.all_bands.isEnabled() and "4.7 h from every band" in tab.all_bands.toolTip(), (
        tab.all_bands.toolTip())
    assert not tab.all_bands.isChecked() and tab.all_bands_wanted, "all bands shown ticked while off at a deep band"
    g = 4
    centres_d = (np.asarray(view_d["starts"].asi8, dtype=float) + np.asarray(view_d["ends"].asi8, dtype=float)) / 2e9
    z_plot.getViewBox().selected.emit(crosspower_rect(centres_d, (g,)))
    pump(app, 0.1)
    assert tab.selected == {g} and tab.selected_level == 7, (tab.selected, tab.selected_level)
    stepped = []
    while level[tab.band()] == 7:  # the next band on, while it is on level 7 the selection stays
        assert tab.selected == {g}, (tab.band(), tab.selected)
        tab.next_band.click()
        pump(app, 0.05)
        stepped.append(int(level[tab.band()]))
    assert stepped[-1] == 8 and tab.selected == set() and "selection of 1 chunk(s) cleared" in tab.status.text(), (
        stepped, tab.selected, tab.status.text())
    cleared_line = tab.status.text()
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(jd))
    pump(app, 0.1)
    z_plot.getViewBox().selected.emit(crosspower_rect(centres_d, (g,)))
    tab.mask_button.click()  # "all bands" was ticked at the 0.1 s band: here the mask covers the band only
    pump(app, 0.1)
    _p, pmin_d, pmax_d = tab.band_periods(jd)
    mask_line = tab.status.text()
    assert mask_line.startswith(f"1 mask over 4.7 h, band {_p:.4g} s only"), mask_line
    assert len(tab.masks) == 1, tab.masks
    deep_mask = tab.masks[0]
    assert (pd.Timestamp(deep_mask["start"]), pd.Timestamp(deep_mask["end"])) == (
        view_d["starts"][g], view_d["ends"][g]), (deep_mask, view_d["starts"][g], view_d["ends"][g])
    assert deep_mask["bands"] != "all" and np.allclose(deep_mask["bands"], [pmin_d, pmax_d]), deep_mask
    codes = masked_chunks(tab.result, tab.masks, jd)
    # chunk g fully masked (every window centred in it overlaps it); g - 1 and g + 1 partly: each holds a
    # window centred within one hop of the mask's edge, whose 2 x hop span reaches into the mask, and others
    # centred further off that do not
    assert codes[g] == 2 and codes[g - 1] == 1 and codes[g + 1] == 1, codes
    assert (np.delete(codes, [g - 1, g, g + 1]) == 0).all(), codes

    def looks(plot):
        """Return, per chunk index drawn on `plot`, its looks.

        'hollow' (no brush), 'filled' (the series colour), 'lighter' (opaque,
        another colour of a higher HSL lightness than the series colour) or
        'other'.
        """
        out = {}
        for item, _x, _y, idx, colour in tab.items[plot]:
            series = QColor(colour)
            for spot, i in zip(item.scatter.points(), idx):
                brush, got = spot.brush(), spot.brush().color()
                look = ("hollow" if brush.style() == Qt.NoBrush else
                        "filled" if got == series else
                        "lighter" if got.alpha() == 255 and got.lightness() > series.lightness() else "other")
                out.setdefault(int(i), set()).add(look)
        return out

    for plot in (z_plot, *tab.polar_plots.values()):
        drawn = looks(plot)
        want_looks = {i: {("filled", "lighter", "hollow")[int(codes[i])]} for i in drawn}
        assert drawn == want_looks, (plot.panel, drawn, want_looks)
    assert tab.count_label.text().startswith(f"3 of {want_deep} chunks of 4.7 h masked (2 partly);"), (
        tab.count_label.text())
    shot_deep = SHOT_DIR / "gui_crosspower_deep.png"
    assert tab.grab().save(str(shot_deep)), f"could not save {shot_deep}"

    # an all-band mask over one base chunk inside deep chunk g, made at the 0.1 s band (all bands on again)
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j))
    pump(app, 0.1)
    assert tab.all_bands.isEnabled() and tab.all_bands.isChecked(), "all bands not back ticked at a base-chunk band"
    c = 28 * g + 3
    centres_b = (np.asarray(r["base_starts"].asi8, dtype=float) + np.asarray(r["base_ends"].asi8, dtype=float)) / 2e9
    z_plot.getViewBox().selected.emit(crosspower_rect(centres_b, (c,)))
    pump(app, 0.1)
    assert tab.selected == {c}, tab.selected
    tab.mask_button.click()
    cut = next(m for m in tab.masks if m["bands"] == "all")
    assert (pd.Timestamp(cut["start"]), pd.Timestamp(cut["end"])) == (r["base_starts"][c], r["base_ends"][c]), cut
    # partly masked at level 5 (20 min chunks): chunk c // 2 holds base chunk c and one more
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j5))
    pump(app, 0.1)
    codes5 = masked_chunks(tab.result, tab.masks, j5)
    assert codes5[c // 2] == 1 and looks(z_plot)[c // 2] == {"lighter"}, (codes5[c // 2], looks(z_plot)[c // 2])
    # Unmask on the deep band: the band's own mask is cut out, the all-band one left and named
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(jd))
    pump(app, 0.1)
    z_plot.getViewBox().selected.emit(crosspower_rect(centres_d, (g,)))
    tab.unmask_button.click()
    pump(app, 0.1)
    assert tab.masks == [cut], tab.masks
    assert iso(cut["start"]) in tab.status.text() and "Remove" in tab.status.text(), tab.status.text()
    unmask_line = tab.status.text()
    tab.table.selectAll()
    tab.remove_button.click()
    assert tab.masks == [], tab.masks
    print(f"    level 5 at {periods[j5]:.4g} s: {len(view5['starts'])} chunks of 20 min, {want5} spots (xy, yx) "
          f"== finite chunks, \"{tab.band_combo.itemText(tab.band_combo.findData(j5))}\"; level 9 at "
          f"{periods[j9]:.4g} s: \"{tab.band_combo.itemText(tab.band_combo.findData(j9))}\", no spot")
    print(f"    deep band {periods[jd]:.4g} s (level 7): \"{tab.band_label.text()}\" ({n_whole} whole chunks of 28, "
          f"the remainder's {in_rest} windows {'kept' if in_rest >= 4 else 'joined'}), {want_d} spots, a bar over "
          f"each chunk's span; all bands off (\"{tab.all_bands.toolTip()[:60]}...\"); selection kept over "
          f"{len(stepped) - 1} band(s) of level 7, then \"{cleared_line}\"; chunk {g} masked "
          f"{deep_mask['start']} to {deep_mask['end']}, bands {deep_mask['bands']} (box shown unticked, status "
          f"\"{mask_line[:48]}\"): codes "
          f"{codes[g - 1:g + 2].tolist()} drawn lighter / hollow / lighter; {shot_deep.name} saved; an all-band "
          f"mask over base chunk {c} leaves level-5 chunk {c // 2} partly masked (lighter); Unmask at level 7: "
          f"\"{unmask_line}\"")
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j))
    pump(app, 0.05)
    tab.all_bands.setChecked(False)  # unticked at a band where it is on (the box a user can click)

    store = tab.result["store"]
    computes = tab.computes
    began = time.time()
    tab.chunk_combo.setCurrentIndex(tab.chunk_combo.findData(60.0))
    pump(app, 0.1)
    rebin_s = time.time() - began
    s0 = pd.Timestamp(here[0]).floor("60s")
    whole, tail = divmod((here[1] - s0).total_seconds(), 60.0)
    want60 = int(whole) + (1 if tail >= 30.0 else 0)
    assert tab.result["store"] is store and tab.result["chunk_s"] == 60.0 and rebin_s < 5.0, rebin_s
    regroup_line = visible_status()  # what happened first: the elision takes the pair and archives
    assert tab.computes == computes and regroup_line.startswith("regrouped to 1 min chunks in ") and (
        "no archive read" in regroup_line), (tab.computes, regroup_line, tab.status.text())
    status_px, status_chars = tab.status.width(), len(regroup_line.rstrip("\N{HORIZONTAL ELLIPSIS}"))
    assert len(tab.result["base_starts"]) == want60, (len(tab.result["base_starts"]), want60)
    j3 = int(np.flatnonzero(level == 3)[0])
    drawn60 = {}
    for jj, m_want in ((j, 1), (j3, 2)):
        tab.band_combo.setCurrentIndex(tab.band_combo.findData(jj))
        pump(app, 0.1)
        view, want = finite_groups(jj)
        assert view["multiple"] == m_want and spots_per_mode() == want and min(want) > 0, (
            jj, view["multiple"], spots_per_mode(), want)
        drawn60[jj] = (len(view["starts"]), want)
        tab.grab().save(str(SCRATCH / f"gui_crosspower_60s_level{level[jj]}.png"))
    tab.chunk_combo.setCurrentIndex(tab.chunk_combo.findData(600.0))
    tab.band_combo.setCurrentIndex(tab.band_combo.findData(j))
    pump(app, 0.1)
    assert len(tab.result["base_starts"]) == n_all and tab.result["store"] is store, len(tab.result["base_starts"])
    assert tab.computes == computes, tab.computes
    print(f"    1 min chunks regrouped in {rebin_s:.2f} s (same store, no compute started): {want60} chunks, band "
          f"{periods[j]:.4g} s {drawn60[j][1]} spots of {drawn60[j][0]}, level 3 at {periods[j3]:.4g} s "
          f"{drawn60[j3][1]} of {drawn60[j3][0]} chunks of 2 min; the status line, {status_px} px wide, shows "
          f"{status_chars} of its {len(tab.status.text())} characters: \"{regroup_line}\"")

    combo.setCurrentIndex(qc_index())  # inside the stored overlap: regrouped, nothing read
    pump(app, 0.1)
    regrouped = tab.result
    assert regrouped is not None and regrouped["store"] is store and tab.computes == computes, tab.computes
    seen = visible_status()
    assert "regrouped to a QC window (2.0 h)" in seen and "no archive read" in seen, seen
    # the window rounded out to whole minutes (the store's minute bins): 12:55:49-14:55:49 drawn as 12:55:00-14:56:00
    edge0, edge1 = start.floor("60s"), end.ceil("60s")
    assert len(regrouped["base_starts"]) == 12 and regrouped["base_starts"][0] == edge0, regrouped["base_starts"]
    assert (regrouped["start"], regrouped["end"], regrouped["base_ends"][-1]) == (edge0, edge1, edge1), (
        regrouped["start"], regrouped["end"])
    took = compute("the chunk impedances")
    assert tab.computes == computes + 1, tab.computes
    r = tab.result
    n_chunks = len(r["base_starts"])
    assert n_chunks == 12 and r["base_starts"][0] == start, (n_chunks, r["base_starts"][0], start)
    v = band_view(r, j)
    for key in ("zxy", "zyx", "coh_xy", "coh_yx"):
        assert v[key].shape == (12,), (key, v[key].shape)
    assert (v["n_windows"] > 0).all(), v["n_windows"]
    for key in ("zxy", "zyx", "coh_xy", "coh_yx", "h_amp", "e_amp"):
        assert np.isfinite(v[key]).all(), (key, v[key])
    ratios = {mode: float(np.median(np.abs(v[f"z{mode}"]))) / abs(z_edi[a, b])
              for mode, (a, b) in (("xy", (0, 1)), ("yx", (1, 0)))}
    for mode, ratio in ratios.items():
        assert 1 / 3 < ratio < 3, (mode, ratio, periods[j], edi.period[k])
    vr = band_view(regrouped, j)
    step = {mode: float(np.median(np.abs(vr[f"z{mode}"][1:] / v[f"z{mode}"][1:] - 1.0))) for mode in ("xy", "yx")}
    assert max(step.values()) < REGROUP_TOL, step
    # chunk 0: computed alone it starts at the window's start (record start + 6 h, 49 s into a minute),
    # regrouped from the overlap's store at the minute before it (the whole first minute bin); printed, not asserted
    step0 = float(np.abs(vr["zxy"][0] / v["zxy"][0] - 1.0))
    spots = spots_per_mode()
    assert spots == [12, 12], spots
    print(f"    D02 rr E08, {n_chunks} chunks of 600 s at {periods[j]:.4g} s (level {level[j]}): regrouped from the "
          f"overlap's store, then computed in {took:.1f} s; the two differ by a median {step['xy']:.1e} (xy), "
          f"{step['yx']:.1e} (yx) over chunks 1-11 (chunk 0, regrouped from the minute before the start: {step0:.1e} in xy); "
          f"median |Z| / EDI's at {edi.period[k]:.4g} s: "
          f"xy {ratios['xy']:.3f}, yx {ratios['yx']:.3f}")

    # a window picked while a compute runs: the compute that returns is drawn over the combo's window or dropped.
    # Nothing is pumped between the picks, so the compute's result (a queued signal) arrives after both
    qc_store, computes = tab.store, tab.computes
    combo.setCurrentIndex(0)  # the whole overlap, outside the QC store: computed by itself
    combo.setCurrentIndex(qc_index())  # picked while it runs: regrouped from the QC store at once
    assert tab.result["kind"] == QC and tab.result["store"] is qc_store, tab.result["kind"]
    began = time.time()
    wait_until(app, lambda: tab.store is not qc_store, 120, "the overlap's store, computed by itself")
    pump(app, 0.2)
    race_s = time.time() - began
    rr, overlap_store = tab.result, tab.store
    assert tab.computes == computes + 1 and tab.store_key[2] == OVERLAP, (tab.computes, tab.store_key)
    assert rr["kind"] == QC and rr["store"] is overlap_store, (rr["kind"], rr["store"] is overlap_store)
    assert (pd.Timestamp(rr["range"][0]), pd.Timestamp(rr["range"][1])) == (start, end), rr["range"]
    assert len(rr["base_starts"]) == 12 and rr["base_starts"][0] == edge0, rr["base_starts"]  # whole minutes
    race_line = visible_status()
    assert "picked meanwhile" in race_line, (race_line, tab.status.text())
    tab.compute_button.click()  # the QC window read again, and the overlap picked before it returns
    combo.setCurrentIndex(0)
    assert tab.result["kind"] == OVERLAP and tab.result["store"] is overlap_store, tab.result["kind"]
    wait_until(app, lambda: tab._thread is None and "dropped" in tab.status.text(), 120, "the QC compute dropped")
    pump(app, 0.2)
    assert tab.computes == computes + 2 and tab.store is overlap_store, (tab.computes, tab.store is overlap_store)
    assert tab.result["kind"] == OVERLAP and len(tab.result["base_starts"]) == n_all, (
        tab.result["kind"], len(tab.result["base_starts"]))
    dropped_line = visible_status()
    assert "dropped" in dropped_line and "drawn from the stored windows" in dropped_line, (
        dropped_line, tab.status.text())
    combo.setCurrentIndex(qc_index())  # regrouped from the overlap store: the span drawn is named
    pump(app, 0.1)
    drawn_at = f"{edge0:%Y-%m-%d %H:%M:%S} to {edge1:%Y-%m-%d %H:%M:%S} UTC"
    lead_line = visible_status()
    assert edge0 < start and drawn_at in lead_line and "rounded out to whole minutes" in lead_line, (
        drawn_at, lead_line, tab.status.text())
    assert drawn_at in z_plot.getPlotItem().titleLabel.text, z_plot.getPlotItem().titleLabel.text

    # a change of remote, and another pair's compute returning over the drawing of the pair shown
    far = "A07"  # archived, its span covering D02's
    overlap_store, computes = tab.store, tab.computes

    def set_remote(name):
        tab.remote_combo.setCurrentIndex(tab.remote_combo.findData(name))
        assert tab.remote_combo.currentData() == name, (name, tab.remote_combo.currentData())

    set_remote(far)
    pump(app, 0.1)
    ask = f"window picked for {SITE} rr {far}: press Compute"
    assert tab.result is None and sum(spots_per_mode()) == 0 and tab.status.text() == ask, (
        tab.result is None, spots_per_mode(), tab.status.text())
    assert tab.store is overlap_store and combo.currentIndex() == qc_index() and tab.computes == computes
    combo.setCurrentIndex(0)  # a window of a pair with no store: nothing drawn, nothing computed
    pump(app, 0.1)
    assert tab.result is None and tab.status.text() == ask and tab.computes == computes, tab.status.text()
    combo.setCurrentIndex(qc_index())
    tab.compute_button.click()  # D02 rr A07 over the QC window, and E08 back before it returns
    set_remote(REMOTE)
    assert tab.result["remote"] == REMOTE and tab.result["store"] is overlap_store, tab.result["remote"]
    assert tab.status.text().startswith("regrouped to a QC window (2.0 h) of D02 rr E08 from the stored windows"), (
        tab.status.text())
    wait_until(app, lambda: tab._thread is None and tab.computes == computes + 1
               and "not drawn: the pair shown changed meanwhile" in tab.status.text(), 120, "D02 rr A07's compute")
    pump(app, 0.2)
    assert tab.result is not None and tab.result["remote"] == REMOTE, "the drawing of D02 rr E08 left"
    far_line = visible_status()
    assert "not drawn: the pair shown changed meanwhile" in far_line, (far_line, tab.status.text())
    tab.chunk_combo.setCurrentIndex(tab.chunk_combo.findData(300.0))  # regroups the drawing's own store
    pump(app, 0.1)
    whole5, tail5 = divmod((edge1 - edge0).total_seconds(), 300.0)
    want5 = int(whole5) + (1 if tail5 >= 150.0 else 0)
    r5 = tab.result
    assert r5 is not None and (r5["station"], r5["remote"]) == (SITE, REMOTE) and r5["store"] is overlap_store, (
        None if r5 is None else (r5["remote"], r5["store"] is overlap_store))
    assert len(r5["base_starts"]) == want5 and r5["base_starts"][0] == edge0, (len(r5["base_starts"]), want5)
    assert f"{SITE} rr {REMOTE}" in z_plot.getPlotItem().titleLabel.text and tab.computes == computes + 1
    assert tab.store is overlap_store and tab.spare is not None and tab.spare[1][1] == far, "A07's store not kept aside"
    far_store = tab.spare[0]
    tab.chunk_combo.setCurrentIndex(tab.chunk_combo.findData(600.0))
    set_remote(far)  # its store, kept aside, covers the QC window: drawn at once, nothing read
    pump(app, 0.1)
    assert tab.result["remote"] == far and tab.result["store"] is far_store and tab.computes == computes + 1, (
        tab.result["remote"], tab.computes)
    assert len(tab.result["base_starts"]) == 12 and tab.spare[0] is overlap_store, len(tab.result["base_starts"])
    set_remote(REMOTE)
    pump(app, 0.1)
    assert tab.result["remote"] == REMOTE and tab.result["store"] is overlap_store and tab.store is overlap_store
    assert tab.computes == computes + 1, tab.computes
    print(f"    remote {far} picked: drawing cleared, \"{ask}\"; its compute returning after {REMOTE} was picked "
          f"back: \"...{far_line[far_line.find('kept'):]}\", D02 rr E08 still drawn, 5 min chunks from its own "
          f"store: {want5} chunks; {far} again drawn from its kept store, {REMOTE} again from the overlap's")

    compute("the chunk impedances, again")  # the QC window's own store again
    assert tab.computes == computes + 2 and tab.result["kind"] == QC and len(tab.result["base_starts"]) == 12, (
        tab.computes, tab.result["kind"])
    print(f"    the overlap picked, then the QC window again while it computed ({race_s:.1f} s): drawn over the QC "
          f"window, 12 chunks from the overlap's store (\"{race_line}\"); Compute on the QC window with the overlap "
          f"picked meanwhile: \"{dropped_line}\"; the QC window regrouped: \"{lead_line}\"")

    # a compute queued for a window that a returning store covers is dropped: the overlap picked (outside the
    # QC window's store: one compute starts), then QC window 5 before it returns (outside that store too: its
    # compute queued behind the first); the overlap's store, on its return, is kept and drawn over QC window 5
    qc_store, computes = tab.store, tab.computes
    k5 = qc_index() + 1
    _kind5, start5, end5 = entries()[k5]
    combo.setCurrentIndex(0)
    combo.setCurrentIndex(k5)
    assert tab._pending is not None and tuple(tab._pending[2:5]) == (QC, start5, end5), tab._pending
    began = time.time()
    wait_until(app, lambda: tab.store is not qc_store, 120, "the overlap's store, QC window 5's compute queued")
    pump(app, 0.5)  # a queued compute starts as the first one's thread finishes
    queue_s = time.time() - began
    kept_line = visible_status()
    r_k5 = tab.result
    assert tab.computes == computes + 1 and tab._pending is None and tab._thread is None, (
        tab.computes - computes, tab._pending, tab._thread)
    assert tab.store_key[2] == OVERLAP and r_k5["store"] is tab.store and r_k5["kind"] == QC, (
        tab.store_key[2], r_k5["kind"])
    assert (pd.Timestamp(r_k5["range"][0]), pd.Timestamp(r_k5["range"][1])) == (start5, end5), r_k5["range"]
    assert r_k5["base_starts"][0] == start5.floor("60s"), r_k5["base_starts"][0]
    assert "kept: the overlap store covers it" in kept_line, (kept_line, tab.status.text())
    combo.setCurrentIndex(qc_index())  # the fourth QC window again: regrouped from the overlap's store
    compute("the chunk impedances, once more")  # the rest of (34) reads the window's own compute
    assert tab.computes == computes + 2 and tab.result["kind"] == QC and len(tab.result["base_starts"]) == 12, (
        tab.computes, tab.result["kind"])
    print(f"    the overlap picked, then QC window 5 while it computed ({queue_s:.1f} s): one compute, QC window 5 "
          f"drawn from the overlap's store, \"{kept_line}\"")

    band_combo = tab.band_combo

    def band_named() -> int:
        """Check that the label names the combo's current band and return the band's index.

        The label gives its place (1-based), its period, its level and its grid.
        """
        index, jj, label = band_combo.currentIndex(), band_combo.currentData(), tab.band_label.text()
        m_jj, n_jj = multiples[level[jj]], len(band_view(tab.result, jj)["starts"])
        grid = (f"{n_jj} chunks of {600 * m_jj / 60:.3g} min" if 600 * m_jj < 7200 else
                f"{n_jj} chunks of {600 * m_jj / 3600:.1f} h") if n_jj else "no chunk (needs "
        for want in (rf"\bband {index + 1} of {band_combo.count()}\b",
                     rf"(^|\s){re.escape(f'{tab.band_periods(jj)[0]:.4g}')} s\b", rf"\blevel {level[jj]}\b",
                     re.escape(f" · {grid}")):
            assert re.search(want, label), (label, want, index, jj)
        return index

    at = band_named()
    assert at == band_combo.findData(j) and tab.prev_band.isEnabled() and tab.next_band.isEnabled(), (at, j)
    label_at = tab.band_label.text()
    tab.next_band.click()
    pump(app, 0.1)
    assert band_combo.currentIndex() == at + 1 == band_named(), (band_combo.currentIndex(), at)
    tab.prev_band.click()
    pump(app, 0.1)
    assert band_combo.currentIndex() == at == band_named() and tab.band_label.text() == label_at, (
        band_combo.currentIndex(), at, tab.band_label.text())
    band_combo.setCurrentIndex(0)
    pump(app, 0.1)
    assert band_named() == 0 and not tab.prev_band.isEnabled() and tab.next_band.isEnabled(), "at the first band"
    band_combo.setCurrentIndex(band_combo.count() - 1)
    pump(app, 0.1)
    assert band_named() == band_combo.count() - 1 and tab.prev_band.isEnabled() and not tab.next_band.isEnabled(), (
        "at the last band")
    band_combo.setCurrentIndex(at)
    pump(app, 0.1)
    assert tab.band() == j and tab.band_label.text() == label_at, (tab.band(), tab.band_label.text(), label_at)
    spots = spots_per_mode()
    assert spots == [12, 12], spots  # the band the rubber band goes round, drawn again
    print(f"    band label \"{label_at}\"; the next arrow one band on and the previous arrow back, the label "
          f"following; the previous arrow off at band 1, the next arrow off at band {band_combo.count()}")

    view = band_view(r, j)
    centres_s = (np.asarray(view["starts"].asi8, dtype=float) + np.asarray(view["ends"].asi8, dtype=float)) / 2e9
    z_plot.getViewBox().selected.emit(crosspower_rect(centres_s, CROSSPOWER_MASKED))
    pump(app, 0.1)
    assert tab.selected == set(CROSSPOWER_MASKED) and tab.selected_on == "time", (tab.selected, tab.selected_on)
    assert not tab.all_bands.isChecked(), "'all bands' ticked before it was asked for"
    tab.all_bands.setChecked(True)  # asked: this one is a time cut
    tab.mask_button.click()
    first, last = min(CROSSPOWER_MASKED), max(CROSSPOWER_MASKED)
    want = {"start": view["starts"][first], "end": view["ends"][last]}
    assert len(tab.masks) == 1, tab.masks
    mask = tab.masks[0]
    assert (pd.Timestamp(mask["start"]), pd.Timestamp(mask["end"])) == (want["start"], want["end"]), mask
    assert mask["bands"] == "all" and mask["found_by"] == "time", mask
    tab.save_button.click()
    written = yaml.safe_load((SCRATCH / "masks.yaml").read_text(encoding="utf-8"))
    assert list(written) == [SITE] and len(written[SITE]) == 1, written
    entry = written[SITE][0]
    assert (pd.Timestamp(entry["start"]), pd.Timestamp(entry["end"])) == (want["start"], want["end"]), entry
    assert entry["bands"] == "all" and entry["found_by"] == "time" and entry["scope"] == "local", entry
    print(f"    chunks {list(CROSSPOWER_MASKED)} masked and saved: "
          f"{entry['start']} to {entry['end']}, bands {entry['bands']}")

    tab.select_site(OTHER)
    pump(app, 0.2)
    assert tab.masks == [], tab.masks
    tab.select_site(SITE)
    wait_until(app, lambda: [e[0] for e in entries()].count(QC) == N_WINDOWS_D02, 30, "D02's windows again")
    assert len(tab.masks) == 1 and tab.masks[0]["start"] == entry["start"], tab.masks
    assert combo.currentData()[0] == OVERLAP, combo.currentData()  # a new site starts on its whole overlap
    combo.setCurrentIndex(qc_index())
    compute("the chunk impedances again")
    for plot in (z_plot, *tab.polar_plots.values()):
        for item, _x, _y, idx, _colour in tab.items[plot]:
            hollow = [spot.brush().style() == Qt.NoBrush for spot in item.scatter.points()]
            want_hollow = [int(i) in CROSSPOWER_MASKED for i in idx]
            assert hollow == want_hollow, (plot.panel, hollow)
    assert tab.count_label.text().startswith("2 of 12 chunks masked;"), tab.count_label.text()
    real_masks_after = real_masks.read_bytes() if real_masks.exists() else None
    assert real_masks_after == real_masks_before, "the real survey folder's masks.yaml was written"
    shot = SHOT_DIR / "gui_crosspower.png"
    assert tab.grab().save(str(shot)), f"could not save {shot}"
    print(f"    reloaded from the file: chunks {list(CROSSPOWER_MASKED)} hollow on the |Z| and both polar "
          f"plots, the other ten filled, \"{tab.count_label.text()}\"; the real survey folder's masks.yaml "
          f"untouched; {shot.name} and {shot_deep.name} saved")


def check_dc_level_column(window, table, columns: list[str]) -> None:
    """Check the Metadata tab's dc level column and its cell of a recorded archive, criterion (1)."""
    dc_col = columns.index(metadata_module.DC_LEVEL)
    assert columns[dc_col - 1] == "archive", columns
    shown = {}
    for site in (SITE, "A07", UNARCHIVED):
        cell = table.item(next(r for r in range(table.rowCount()) if table.item(r, 0).text() == site), dc_col)
        shown[site] = cell.text()
        path = window.state.archive_path(site)
        recorded = False
        if path.exists():
            with h5py.File(path, "r", locking=False) as f:
                station = f[f"Experiment/Surveys/{next(iter(f['Experiment/Surveys']))}/Stations/{site}"]
                recorded = any("dc level (" in str(station[run].attrs.get("comments", ""))
                               for run in station if run.startswith("sr"))
        if recorded:
            assert cell.text() != "-", (site, cell.text())
        else:
            want = ("-", metadata_module.NO_RECORD_TIP if path.exists() else "")
            assert (cell.text(), cell.toolTip()) == want, (site, cell.text(), cell.toolTip())
    comments = {
        "sr1000_0001": ("skipped unreadable file(s): x.B423; dc level (median counts, rail %): hx +4.300e+07 0.10 ok, "
                        "hy +3.900e+07 0.10 ok, ex +2.000e+07 0.05 ok, ey +1.600e+09 0.05 open input?"),
        "sr1000_0002": ("dc level (median counts, rail %): hx +4.300e+07 0.10 ok, hy +3.900e+07 0.10 ok, "
                        "ex +2.000e+07 0.05 ok, ey -3.000e+07 0.08 ok"),
    }
    path = SCRATCH / "dc_level" / "S05.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        station = f.create_group("Experiment/Surveys/t/Stations/S05")
        station.create_group("Transfer_Functions")
        for run, text in comments.items():
            station.create_group(run).attrs["comments"] = text
    item = metadata_module._dc_level_item("t", "S05", path)
    want = "hx ok 4.30e7, hy ok 3.90e7, ex ok 2.00e7, ey open input? 1.60e9 in 1 of 2 runs"
    assert item.text() == want, item.text()
    assert item.foreground().color().name() == theme.BAD_COLOUR == "#ef5350", item.foreground().color().name()
    assert item.sort_key() == 0, item.sort_key()
    tip = item.toolTip().splitlines()
    assert len(tip) == 9 and "sr1000_0001 ey: median 1.60e9 counts, rail 0.05 %, open input?" in tip, tip
    print(f"  dc level column after archive: {shown}; a recorded archive's cell {item.text()!r} in "
          f"{theme.BAD_COLOUR}")


def main() -> int:
    """Build the window over the real survey, check criteria (1)-(34) in the order they run and return 0."""
    print(__doc__.split("**This test fails if**")[1].split("It opens three")[0].strip())
    print()

    global REAL_YAML
    REAL_YAML = SURVEY_YAML.read_bytes()  # (17): the same bytes at the end
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)  # as __main__ does, before the window is built
    window = MainWindow(survey_yaml=SURVEY_YAML)
    window.resize(1400, 900)
    window.show()
    pump(app, 0.3)
    startup_fetches = fetches()  # (24): the real workspace has its basemap.json
    assert window.windowTitle() == "MT processing", window.windowTitle()
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert tabs == EXPECTED_TABS, f"tab order {tabs}, expected {EXPECTED_TABS}"
    print(f"(1) window built from {SURVEY_YAML}: {tabs}")

    table = window.metadata_tab.table
    assert table.rowCount() == EXPECTED_SITES, f"{table.rowCount()} rows, expected {EXPECTED_SITES}"
    columns = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == SITE)
    assert table.item(row, columns.index("remote")).text() == REMOTE
    for site, archived in ((SITE, True), ("A07", True), (UNARCHIVED, False)):
        cell = table.item(next(r for r in range(table.rowCount()) if table.item(r, 0).text() == site),
                          columns.index("channels"))
        grey = cell.foreground().color().name() == theme.DISABLED == "#7a7a7a"
        assert cell.text() == DEFAULT_CHANNELS, (site, cell.text())
        assert (grey, cell.toolTip()) == ((True, ARCHIVE_TIP) if archived else (False, "")), \
            (site, cell.foreground().color().name(), cell.toolTip())
    print(f"  metadata: {table.rowCount()} sites, {SITE}'s remote column {REMOTE}; channels "
          f"{DEFAULT_CHANNELS!r} for {SITE}, A07 (greyed, archive tooltip) and {UNARCHIVED} (plain)")
    check_dc_level_column(window, table, columns)
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
            assert r.child(0).text(0) == NO_ARCHIVE_ROW, r.child(0).text(0)
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
    # the stack: order, names, colours, one shared x axis, no gaps
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
    # Spectra: two panels on one frequency axis
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

    # Coherence: the pair titles, the band lines and their mean, locked axes
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
    # the cursor is on every panel, and a click on the right column moves it
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
    ladder_lines = [line for line in console_text.splitlines() if "crust.timefreq" in line]
    assert segment_lines, f"no '[segment] ' line in the console strip:\n{console_text}"
    assert ladder_lines, f"no 'crust.timefreq' line (the ladder, off the GUI thread) in the console:\n{console_text}"
    print(f"(19) console strip: {len(segment_lines)} '[segment] ' line(s), last {segment_lines[-1]!r}; "
          f"{len(ladder_lines)} 'crust.timefreq' line(s), e.g. {ladder_lines[0]!r}")

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
    print("(13) the Process tab for D02, row by row:")
    window.tabs.setCurrentWidget(process)
    process.select_station(SITE)
    pump(app, 0.3)
    assert process.station_combo.currentData() == SITE, process.station_combo.currentData()
    assert process.remote_combo.currentData() == REMOTE, process.remote_combo.currentData()
    assert process.options.filters_label.text() == (
        f"{SITE} declares: none | {REMOTE} (remote) declares: none (edit on the Filter Data tab)"), \
        process.options.filters_label.text()
    process.options.describe_filters("A07", None)  # a saved `replace`, no A07_f<hash>.h5 variant yet
    assert process.options.filters_label.text() == (
        "A07 declares: replace (filtered archive will be built first, from the raw archive) "
        "(edit on the Filter Data tab)"), process.options.filters_label.text()
    process.options.describe_filters(SITE, REMOTE)  # restore: station_combo/remote_combo still show D02/E08
    print(f"  filters line: {SITE}/{REMOTE} 'none declared'; A07 (a saved replace, no variant) "
          f"'filtered archive will be built first, from the raw archive'")

    def at(widget):
        """(left, top, right, bottom) of a widget in the tab's coordinates."""
        top_left = widget.mapTo(process, widget.rect().topLeft())
        return top_left.x(), top_left.y(), top_left.x() + widget.width(), top_left.y() + widget.height()

    bar, summary, table = process.window_bar, process.summary, process.job_panel.table
    buttons = [process.add_button, process.run_button, process.reset_button, process.build_button]
    assert [b.text() for b in buttons] == ROW3_BUTTONS, [b.text() for b in buttons]
    on_tab = {b.text() for b in process.findChildren(QPushButton)}
    assert not on_tab & REMOVED_BUTTONS, f"removed buttons still on the Process tab: {on_tab & REMOVED_BUTTONS}"
    left_over = [name for name in REMOVED_NAMES if hasattr(process, name)]
    assert not left_over, f"the Process tab still has {left_over}"
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
    print(f"  no {', '.join(sorted(REMOVED_BUTTONS))} button among the tab's {len(on_tab)} buttons, "
          f"and none of {', '.join(REMOVED_NAMES)}")

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
        want_tip = f"Basemap: {meta['provider']} - " + meta["attribution"].replace("(C)", "\N{COPYRIGHT SIGN}")
        assert site_map.plot.toolTip() == want_tip, (site_map.plot.toolTip(), want_tip)
        assert site_map.basemap_label.isHidden(), f"a label under the map shows {site_map.basemap_label.text()!r}"
        credit = meta["attribution"].split("(C)")[-1].strip()[:12]
        shown = [w.text() for w in process.findChildren(QLabel) if w.isVisible() and credit in w.text()]
        assert not shown, f"the attribution is still on a visible label: {shown}"
        map_box = site_map.plot.getViewBox()
        lim = map_box.state["limits"]
        west, east, south, north = meta["lon_min"], meta["lon_max"], meta["lat_min"], meta["lat_max"]
        assert np.allclose(lim["xLimits"], [west, east], rtol=0, atol=1e-9), lim["xLimits"]
        assert np.allclose(lim["yLimits"], [south, north], rtol=0, atol=1e-9), lim["yLimits"]
        assert np.allclose([lim["xRange"][1], lim["yRange"][1]], [east - west, north - south], rtol=0, atol=1e-9)
        map_box.setRange(xRange=(west - 1, east + 1), yRange=(south - 1, north + 1), padding=0)
        pump(app, 0.2)
        (vx0, vx1), (vy0, vy1) = map_box.viewRange()
        tol = 1e-9
        assert west - tol <= vx0 < vx1 <= east + tol and south - tol <= vy0 < vy1 <= north + tol, (
            f"the map zoomed out past the basemap: view {map_box.viewRange()}, extent {west, east, south, north}")
        for text in site_map.texts:
            fill = text.fill.color()
            assert fill.name() == SURFACE_GREY and 100 <= fill.alpha() <= 230, (text.toPlainText(), fill.name())
            assert images[0].zValue() < text.zValue() < site_map.scatter.zValue(), text.toPlainText()
        print(f"  basemap: {meta['provider']} zoom {meta['zoom']}, {png.shape[1]}x{png.shape[0]} px, an "
              f"ImageItem at lon {got[0]:.4f}..{got[0] + got[2]:.4f}, lat {got[1]:.4f}..{got[1] + got[3]:.4f} "
              f"= basemap.json, north row on top, under the dots")
        print(f"  credit as the map's tooltip {want_tip[:50]!r}..., no label under the map; a zoom out "
              f"to +-1 deg stays at lon {vx0:.4f}..{vx1:.4f}, lat {vy0:.4f}..{vy1:.4f}, inside the basemap")
    else:
        print(f"  basemap: SKIPPED, no {basemap_json.name} / {basemap_png.name} in {WORK} "
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
        advanced.taper_combo.setCurrentText("hamming")
        advanced.r0_spin.setValue(2.0)
        process.add_button.click()
        pump(app)
        tweaked = recorded[-1]
        assert tweaked[7:] == ["--taper", "hamming", "--r0", "2.0"], tweaked[7:]
        added_row("--taper hamming --r0 2.0")
        advanced.taper_combo.setCurrentText("hann")
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

        # ------------------------------------ (35) the engine combo: MANTLE
        engine = process.options.engine_combo
        assert [engine.itemText(i) for i in range(engine.count())] == ENGINES, [engine.itemText(i) for i in range(engine.count())]
        assert engine.currentText() == ENGINES[0] and advanced.isEnabled(), (engine.currentText(), advanced.isEnabled())
        advanced.toggle.click()
        pump(app)
        advanced.r0_spin.setValue(2.0)  # moved off its default: it must not reach a MANTLE run
        engine.setCurrentText("mantle")
        pump(app)
        assert not advanced.isEnabled(), "the aurora estimator block stayed enabled with mantle chosen"
        status = process.status_label.text()
        assert MANTLE_NOTE in status and "--no-masks" not in status, status
        process.add_button.click()
        pump(app)
        mantle_argv = recorded[-1]
        assert mantle_argv[7:] == ["--engine", "mantle"], mantle_argv[7:]
        assert not ESTIMATOR_FLAGS & set(mantle_argv) and "--no-masks" not in mantle_argv, mantle_argv
        mantle_job = runner.jobs[-1]
        assert mantle_job.label.startswith(f"process_rr {SITE} rr-{REMOTE} [mantle]"), mantle_job.label
        assert mantle_job.options == "--engine mantle", mantle_job.options
        assert mantle_job.status == "queued" and not runner.running, "the MANTLE job must only be queued"
        added_row("--engine mantle")
        shoot(app, window, "process_mantle", process)
        engine.setCurrentText("aurora")
        pump(app)
        assert advanced.isEnabled() and MANTLE_NOTE not in process.status_label.text(), process.status_label.text()
        advanced.r0_spin.setValue(1.5)
        advanced.toggle.click()
        pump(app)
        process.add_button.click()
        pump(app)
        assert not [a for a in recorded[-1] if a.startswith("--")], recorded[-1]
        added_row("defaults")
        print(f"(35) engine combo {ENGINES}: mantle -> ...{' '.join(mantle_argv[7:])} (r0 2.0 meanwhile passed "
              f"nothing), label {mantle_job.label!r}, Options {mantle_job.options!r}, status line {status!r}; "
              f"back to aurora: block enabled, no note, no flag")

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

    # -------------------------- (20) Add to queue leaves the job for Run queue
    # the interception above replaced `runner.add`; test the real path too:
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
    waiting = process._queue("waiting job", [sys.executable, "-c", "print('still waiting')"])
    now = runner.run_now("run-now job", [sys.executable, "-c", "print('run now')"])
    assert runner.running and runner.current_job() is runner.jobs[now], "run_now did not start its own job"
    assert runner.jobs[waiting].status == "queued", runner.jobs[waiting].status
    wait_until(app, lambda: runner.jobs[now].status in ("done", "failed"), 30, "the run_now job")
    pump(app, 0.3)
    assert runner.jobs[now].status == "done" and runner.jobs[waiting].status == "queued", \
        [job.status for job in runner.jobs]
    assert not runner.running, "the queue went on to the waiting job after run_now's"
    print(f"  run_now with a job waiting: its own job {runner.jobs[now].status!r}, the waiting one "
          f"still {runner.jobs[waiting].status!r}, runner idle")
    runner.reset()
    chained: list[int] = []

    def chain(_index: int, _ok: bool) -> None:
        if not chained:
            chained.append(runner.run_now("chained job", [sys.executable, "-c", "print('chained')"]))

    runner.job_finished.connect(chain)
    try:
        runner.run_now("first job", [sys.executable, "-c", "print('first')"])
        wait_until(app, lambda: bool(chained) and runner.jobs[chained[0]].status in ("done", "failed"), 30,
                   "a job started with run_now from a job_finished slot")
    finally:
        runner.job_finished.disconnect(chain)
    pump(app, 0.2)
    assert runner.jobs[chained[0]].status == "done" and not runner.running, [j.status for j in runner.jobs]
    print(f"  run_now from a job_finished slot: the chained job {runner.jobs[chained[0]].status!r}, runner idle")
    runner.reset()
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
    own_hours = (other_span[1] - other_span[0]).total_seconds() / 3600
    fraction = summary.ENOUGH_FRACTION  # the declared threshold, not the recommendation itself
    tie_hours = summary.TIE_HOURS
    # the rule: the nearest site among those whose overlap covers
    # at least the fraction of the station's own record; else the longest overlap
    enough = sorted(name for name, hours in by_hours.items() if hours >= fraction * own_hours)
    tied = sorted(name for name, hours in by_hours.items() if hours >= top - tie_hours)

    def _law_of_cosines_to_other(name: str) -> float:
        if name not in yaml_sites or OTHER not in yaml_sites:
            return float("inf")
        return cosines_km(OTHER, name)

    pool = enough or tied
    expected = min(pool, key=lambda n: (_law_of_cosines_to_other(n), n))
    text = summary.recommended.text()
    pick = text.split("Recommended remote: ")[1].split(" ")[0]
    assert pick == expected, (
        f"{OTHER}: recommended {pick!r}, expected {expected!r} (nearest among "
        f"{len(pool)} with overlap >= {fraction:.0%} of {own_hours:.1f} h: {pool}): {text!r}")
    assert abs(float(text.rsplit(", ", 1)[1].split(" h")[0]) - by_hours[expected]) < 0.051, (text, by_hours[expected])
    print(f"  {OTHER} (no declared remote): {text!r}; computed here {expected} at "
          f"{by_hours[expected]:.3f} h ({_law_of_cosines_to_other(expected):.1f} km), nearest of "
          f"{len(pool)} site(s) with overlap >= {fraction:.0%} of {own_hours:.1f} h: {pool}")


    # ------------------------------------------ (14) no "What to look for"
    for name, tab in (("Spectra", spectra), ("Spectrogram", spectrogram), ("Coherence", coherence)):
        found = hint_labels(tab)
        assert not found, f"the {name} tab still hints: {found}"
    # the Filter Data tab carries no explanatory text either (a PDF explains it)
    rule_labels = [w for w in window.filters_tab.findChildren(QLabel) if "Nothing here is automatic" in w.text()]
    assert not rule_labels, "the Filter Data tab still shows the rule box"
    print('(14) no "What to look for" label on Spectra, Spectrogram or Coherence; '
          'no rule box on Filter Data')

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
    assert rows_f == ["replace magnetics from another site: Bx <- A06"], rows_f
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
    print(f"  emptied: filters.yaml keys now {list(data)}; the round trip wrote the copy's filters.yaml")

    # ------------------- (15) continued: the Metadata tab edits the same copy
    print("(15) Metadata edits on the same copy:")
    meta = window.metadata_tab
    window.tabs.setCurrentWidget(meta)
    pump(app, 0.3)
    assert meta.warning_label.isVisible(), "the generated_by line is hidden"
    assert meta.warning_label.text() == GENERATED_WARNING, meta.warning_label.text()
    mtable = meta.table
    mcols = [mtable.horizontalHeaderItem(c).text() for c in range(mtable.columnCount())]
    after_remote = mcols[mcols.index("remote") + 1:mcols.index("remote") + 1 + len(HEADER_COLUMNS)]
    assert after_remote == HEADER_COLUMNS, after_remote
    editable = {c for i, c in enumerate(mcols) if mtable.item(0, i).flags() & Qt.ItemIsEditable}
    assert editable == EDITABLE_COLUMNS, f"editable {sorted(editable)}"
    gcol = mcols.index("electric_gain")
    gains = [mtable.item(r, gcol) for r in range(mtable.rowCount())]
    assert {g.text() for g in gains} == {"-"} and not any(g.flags() & Qt.ItemIsEditable for g in gains), \
        [(g.text(), int(g.flags())) for g in gains[:3]]
    assert {g.toolTip() for g in gains} == {"PR6-24 (EDL) sites only"}, {g.toolTip() for g in gains}
    edl = Survey({"name": "g", "instrument": "edl", "data_root": ".", "defaults": {"electric_gain": 10.0},
                  "sites": {"ST19": {}}}, Path("."))
    rule = lambda text, shown: metadata_edit.electric_gain_edit(edl, "ST19", text, shown)  # noqa: E731
    assert rule("10.0", "10") is channels_column.UNCHANGED, rule("10.0", "10")
    assert (rule("1", "10"), rule("5", "10"), rule("10", "1")) == (1.0, 5.0, None), \
        (rule("1", "10"), rule("5", "10"), rule("10", "1"))
    try:
        rule("abc", "10")
        raise AssertionError("'abc' accepted as an electric_gain number")
    except ValueError as exc:
        assert "abc" in str(exc), exc
    print(f"  yellow line: {meta.warning_label.text()!r}; {', '.join(HEADER_COLUMNS)} after remote; "
          f"{len(editable)} editable columns; electric_gain '-' read-only on all {len(gains)} LEMI-423 "
          f"rows; its rule on an EDL survey (default 10.0): '10.0' over '10' unchanged, '1' -> 1.0, "
          f"'5' -> 5.0, '10' over '1' -> key dropped, 'abc' refused")
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

    # ------------------------------------ (27) the channels column's round trip
    print("(27) channels column on the same copy:")
    ccol = mcols.index("channels")

    def channels_cell(site):
        return mtable.item(next(r for r in range(mtable.rowCount()) if mtable.item(r, 0).text() == site), ccol)

    def choose_channels(site, label, typed=None):
        """Open the site's editor as a double-click does and pick `label` (a custom prompt answers `typed`)."""
        cell = channels_cell(site)
        mtable.editItem(cell)
        pump(app)
        combo = mtable.indexWidget(mtable.model().index(mtable.row(cell), ccol))
        assert isinstance(combo, QComboBox), f"no combo editor on {site}'s channels cell: {combo}"
        offered = [combo.itemText(i) for i in range(combo.count())]
        real_prompt = channels_column.ask_channels
        channels_column.ask_channels = lambda _parent, _current: typed
        try:
            combo.setCurrentIndex(offered.index(label))
            combo.activated.emit(offered.index(label))  # what a click on the item emits
        finally:
            channels_column.ask_channels = real_prompt
        pump(app)
        return offered, channels_cell(site).text()

    before = copy_yaml.read_bytes()
    sites_before = yaml.safe_load(before.decode("utf-8"))["sites"]
    default_a03 = Survey.from_yaml(copy_yaml).site("A03").channels
    assert channels_cell(UNARCHIVED).text() == DEFAULT_CHANNELS, channels_cell(UNARCHIVED).text()
    offered, shown = choose_channels(UNARCHIVED, MAGNETICS_ONLY)
    assert offered == LEMI423_PRESETS + [channels_column.CUSTOM], offered
    assert shown == MAGNETICS_ONLY, shown
    try:
        metadata_edit.ask_yes_no = answering(True, asked)
        assert meta.save(), "save() refused the channels edit"
    finally:
        metadata_edit.ask_yes_no = real_ask
    pump(app, 0.3)
    after = copy_yaml.read_bytes()
    changes = sites_changes(sites_before, yaml.safe_load(after.decode("utf-8"))["sites"])
    assert changes == {(UNARCHIVED, "channels"): ["hx", "hy"]}, changes
    cut = before.index(b"\nsites:") + 1
    assert after[:cut] == before[:cut], "the bytes above sites: changed"
    assert before[before.index(b"\nworkspace:"):] == after[after.index(b"\nworkspace:"):], "the tail changed"
    reread = Survey.from_yaml(copy_yaml)
    assert reread.site(UNARCHIVED).channels == ["hx", "hy"], reread.site(UNARCHIVED).channels
    assert reread.site("A03").channels == default_a03 == ["ex", "ey", "hx", "hy"], reread.site("A03").channels
    assert channels_cell(UNARCHIVED).text() == MAGNETICS_ONLY, channels_cell(UNARCHIVED).text()
    print(f"  offered {offered}; {UNARCHIVED} -> {MAGNETICS_ONLY!r}: saved {changes}, head and tail unchanged")

    _, shown = choose_channels(UNARCHIVED, DEFAULT_CHANNELS)
    assert shown == DEFAULT_CHANNELS, shown
    try:
        metadata_edit.ask_yes_no = answering(True, asked)
        assert meta.save(), "save() refused the channels edit back to the default"
    finally:
        metadata_edit.ask_yes_no = real_ask
    pump(app, 0.3)
    assert "channels" not in yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))["sites"][UNARCHIVED]
    assert copy_yaml.read_bytes() == before, "back to the default, the file is not what it was"
    print(f"  back to {DEFAULT_CHANNELS!r}: {UNARCHIVED}'s channels key removed, the file identical to before again")

    _, shown = choose_channels(UNARCHIVED, channels_column.CUSTOM, typed="hx, hy, ex, ey, tx")
    assert shown == "hx, hy, ex, ey, tx", shown
    assert meta.pending() == {UNARCHIVED: {"channels": ["hx", "hy", "ex", "ey", "tx"]}}, meta.pending()
    _, shown = choose_channels(UNARCHIVED, channels_column.CUSTOM, typed="ex ey hx hy hz")
    assert shown == "Ex Ey Bx By Bz", shown
    channels_cell(UNARCHIVED).setText(DEFAULT_CHANNELS)
    assert meta.pending() == {}, meta.pending()
    assert copy_yaml.read_bytes() == before, "the custom checks wrote the file"
    print("  custom...: 'hx, hy, ex, ey, tx' kept as typed (pending [hx, hy, ex, ey, tx]); "
          "'ex ey hx hy hz' shown as the preset 'Ex Ey Bx By Bz'; nothing saved")

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

    # phase range: 0-90 (mtpy's own yx + 180 fold) is the default, -180 to 180
    # undoes it, and it applies to every EDI on the phase axes
    def phase_axes():
        """Return the (xy, yx) phase axes of the current draw, found by their ylabel.

        `tf_plot._apply_phase_range` labels both "Phase (deg)".
        """
        found = [ax for ax in fig.axes if "Phase" in ax.get_ylabel()]
        assert len(found) == 2, f"expected 2 phase axes (xy, yx), got {len(found)}"
        return found

    assert edis.phase_fold_radio.isChecked(), "Phase does not default to '0 to 90 deg'"
    _axp, axp2 = phase_axes()
    lo, hi = axp2.get_ylim()
    assert (lo, hi) == (0.0, 90.0), f"default phase axes y limits {(lo, hi)}, expected exactly (0, 90): the axis is locked to the chosen range"
    for name, (_period, phase) in zip(ticked, edi_curves(axp2)):
        assert phase.size and ((phase >= 0) & (phase <= 90)).all(), (
            f"{name}: default yx phase outside 0-90: {phase.min():.1f} to {phase.max():.1f}"
        )
    print(f"  Phase '0 to 90 deg' (default): yx axes y limits {(lo, hi)}, "
          f"yx within 0-90 for {ticked}")

    edis.phase_unfold_radio.setChecked(True)
    pump(app, 0.6)
    _axp, axp2 = phase_axes()
    lo, hi = axp2.get_ylim()
    assert (lo, hi) == (-180.0, 180.0), f"unfolded phase axes y limits {(lo, hi)}, expected (-180, 180)"
    for name, (_period, phase) in zip(ticked, edi_curves(axp2)):
        assert phase.size and ((phase >= -180) & (phase <= -90)).all(), (
            f"{name}: unfolded yx phase not in -180 to -90 (the physical quadrant): "
            f"{phase.min():.1f} to {phase.max():.1f}"
        )
    print(f"  Phase '-180 to 180 deg': yx axes y limits {(lo, hi)}, "
          f"yx within -180 to -90 (physical quadrant) for {ticked}")

    edis.phase_fold_radio.setChecked(True)
    pump(app, 0.6)
    _axp, axp2 = phase_axes()
    lo, hi = axp2.get_ylim()
    assert (lo, hi) == (0.0, 90.0), f"back to '0 to 90 deg': y limits {(lo, hi)}, expected exactly (0, 90)"
    print(f"  back to Phase '0 to 90 deg': yx axes y limits {(lo, hi)}")

    # rho limits: blank is mtpy's own automatic scale, a valid pair clamps
    # both resistivity axes exactly, and a bad pair (min >= max) is ignored
    # and reported rather than silently applied
    def rho_axes():
        """Return (axr, axr2) of the current draw, the two resistivity axes mtpy makes before the phase ones.

        They are fig.axes[:2] for this two-station overlay (each holding two
        error-bar containers, checked above).
        """
        axes = fig.axes[:2]
        assert len(axes) == 2, f"expected 2 resistivity axes (axr, axr2), got {len(axes)}"
        return axes

    def set_rho(edit, text: str) -> None:
        """Type `text` into a rho field and let its debounced redraw land."""
        before = edis.draws
        edit.setText(text)
        edit.editingFinished.emit()
        wait_for_draw(app, edis, before)
        pump(app, 0.3)

    assert edis.rho_limits() == (None, None), "the rho fields do not start blank"
    set_rho(edis.rho_min_edit, "")  # a redraw with both fields confirmed blank: the automatic baseline
    auto_lims = [ax.get_ylim() for ax in rho_axes()]
    print(f"  rho limits blank (automatic): resistivity axes y limits {auto_lims}")

    set_rho(edis.rho_min_edit, "10")
    set_rho(edis.rho_max_edit, "1000")
    assert edis.rho_limits() == (10.0, 1000.0), edis.rho_limits()
    for axes in rho_axes():
        assert axes.get_ylim() == (10.0, 1000.0), f"rho axes y limits {axes.get_ylim()}, expected (10, 1000)"
    print("  rho limits min 10 max 1000: both resistivity axes clamped to (10.0, 1000.0)")

    set_rho(edis.rho_max_edit, "")
    assert edis.rho_limits() == (10.0, None), edis.rho_limits()
    for axes, (auto_lo, auto_hi) in zip(rho_axes(), auto_lims):
        lo, hi = axes.get_ylim()
        assert lo == 10.0, f"rho axes low limit {lo}, expected 10.0 kept"
        assert hi == auto_hi, f"rho axes high limit {hi}, expected mtpy's automatic {auto_hi}"
    print("  rho limits min 10, max blank: low clamped to 10.0, high back to mtpy's automatic value")

    set_rho(edis.rho_min_edit, "1000")
    set_rho(edis.rho_max_edit, "10")
    assert edis.rho_limits() == (1000.0, 10.0), edis.rho_limits()
    for axes, auto in zip(rho_axes(), auto_lims):
        assert axes.get_ylim() == auto, f"a bad pair (min >= max) changed the axes: {axes.get_ylim()}, was {auto}"
    assert "rho limits ignored" in edis.status_label.text(), edis.status_label.text()
    print(f"  rho limits min 1000 max 10 (min >= max): ignored, axes stayed at {auto_lims}, "
          f"status {edis.status_label.text()!r}")

    set_rho(edis.rho_min_edit, "")
    set_rho(edis.rho_max_edit, "")
    assert edis.rho_limits() == (None, None), edis.rho_limits()
    print("  rho fields cleared back to blank (automatic)")

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

    # ------------------------------------- (36) the MANTLE product on View EDIs
    print("(36) View EDIs with the MANTLE product:")
    import json
    from matplotlib.colors import to_hex

    assert MANTLE_EDI.exists() and AURORA_EDI.exists(), (MANTLE_EDI, AURORA_EDI)
    edis.rho_radio.setChecked(True)
    pump(app, 0.6)
    leaves = {item.text(0): item for item in edis._leaves()}
    by_name = {Path(str(item.data(0, Qt.UserRole))).name: label for label, item in leaves.items()}
    mantle_label = by_name.get(MANTLE_EDI.name)
    aurora_label = by_name.get(AURORA_EDI.name)
    fine_label = by_name.get(MANTLE_EDI.stem + "_fine.edi")
    assert mantle_label and mantle_label.endswith(" [mantle]"), mantle_label
    assert aurora_label and aurora_label.endswith(" [aurora]"), aurora_label
    assert fine_label == mantle_label[: -len(" [mantle]")] + " [mantle fine grid]", (fine_label, mantle_label)
    assert by_name.get(f"{SITE}_rr-{REMOTE}.edi") == f"{SITE}_rr-{REMOTE}.edi", by_name.get(f"{SITE}_rr-{REMOTE}.edi")
    sidecar = json.loads(MANTLE_EDI.with_suffix(".json").read_text(encoding="utf-8"))
    report = json.loads(MANTLE_EDI.with_name(sidecar["mantle_report"]).read_text(encoding="utf-8"))
    scopes: dict[str, list[float]] = {}
    for verdict in report["verdicts"]:
        scopes.setdefault(verdict["word"], []).extend(1.0 / f for f in verdict["freq_hz"])
    want = {word: (min(p), max(p)) for word, p in scopes.items()}
    assert sorted(want) == sorted(STRIP_WORDS), sorted(want)
    counts = sidecar["engine_config"]["verdict_words"]
    print(f"  list: {mantle_label!r}, {aurora_label!r}, {fine_label!r}, {SITE}_rr-{REMOTE}.edi plain; "
          f"report scopes {({w: (f'{a:.3g}', f'{b:.3g}') for w, (a, b) in want.items()})} s, counts {counts}")

    edis.quick_check.setChecked(True)
    pump(app, 0.6)
    before = edis.draws
    edis.tree.setCurrentItem(leaves[mantle_label])
    wait_for_draw(app, edis, before)
    pump(app, 0.5)
    strips = [ax for ax in fig.axes if ax.get_label() == tf_plot.VERDICT_STRIP]
    phase_top = max(ax.get_position().y1 for ax in fig.axes if "Phase" in ax.get_ylabel())
    assert len(strips) == 2, f"{len(strips)} verdict strips for the two resistivity axes"
    for strip in strips:
        labels = [t.get_text() for t in strip.get_yticklabels()]
        assert labels == STRIP_WORDS and strip.get_xscale() == "log", (labels, strip.get_xscale())
        box = strip.get_position()
        above = [ax for ax in fig.axes if ax is not strip and abs(ax.get_position().y0 - (box.y1 + tf_plot.STRIP_GAP)) < 1e-6
                 and abs(ax.get_position().x0 - box.x0) < 1e-6]
        assert len(above) == 1 and above[0] in strip.get_shared_x_axes().get_siblings(strip), above
        assert box.y0 >= phase_top - 1e-9, (box.y0, phase_top)
        assert len(strip.collections) == len(STRIP_WORDS), len(strip.collections)
        for coll, word in zip(strip.collections, STRIP_WORDS):
            xs = np.concatenate([path.vertices[:, 0] for path in coll.get_paths()])
            got = (float(xs.min()), float(xs.max()))
            assert np.allclose(got, want[word], rtol=1e-6), (word, got, want[word])
            assert to_hex(coll.get_facecolor()[0]) == STRIP_COLOURS[word], (word, to_hex(coll.get_facecolor()[0]))
        legend = strip.get_legend()
        assert legend is not None and [t.get_text() for t in legend.get_texts()] == STRIP_WORDS, legend
    assert strips[0].get_legend().get_title().get_text().startswith("MANTLE verdicts: "), \
        strips[0].get_legend().get_title().get_text()
    text = edis.mantle_label.text()
    assert f"ok {counts['ok']}, snr_limited {counts['snr_limited']}" in text and "snr gate ran: True" in text, text
    assert edis.notes_button.isEnabled(), "MANTLE notes... is disabled on a mantle product"
    dialog = edis.show_notes()
    pump(app, 0.3)
    notes = edis._notes_view.toPlainText()
    assert dialog is not None and dialog.isVisible(), "the notes dialog is not visible"
    assert f"site {SITE}" in notes and report["notes"][0] in notes, notes[:300]
    dialog.close()
    pump(app, 0.2)
    shoot(app, window, "edis_mantle", edis)
    print(f"  quick view on {mantle_label!r}: 2 strips {STRIP_WORDS}, extents {want}, colours "
          f"{STRIP_COLOURS}; label {text!r}; notes dialog {len(notes.splitlines())} lines")

    before = edis.draws
    edis.tree.setCurrentItem(leaves[aurora_label])
    wait_for_draw(app, edis, before)
    pump(app, 0.5)
    assert not [ax for ax in fig.axes if ax.get_label() == tf_plot.VERDICT_STRIP], "a strip on an aurora row"
    assert edis.mantle_label.text() == "" and not edis.notes_button.isEnabled(), edis.mantle_label.text()
    print(f"  quick view on {aurora_label!r}: no strip, label empty, notes disabled")
    edis.quick_check.setChecked(False)
    pump(app, 0.6)

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
        filled["workspace"] = dialog.workspace_edit.text()
        combo = dialog.channels_combo
        filled["channels"] = ([combo.itemText(i) for i in range(combo.count())], combo.currentText())
        combo.setCurrentText(NEW_SURVEY_CHANNELS)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()

    QTimer.singleShot(100, fill_dialog)
    n_before = len(runner.jobs)
    started = time.time()
    meta.new_button.click()  # asynchronous: returns once the dialog closed and the job is queued and started
    took_to_queue = time.time() - started
    assert filled.get("name") == raw_root.name, f"the name defaulted to {filled.get('name')!r}"
    assert Path(filled.get("workspace", "")) == raw_root / "work", f"workspace {filled.get('workspace')!r}"
    n_fetches = len(fetches())
    assert len(runner.jobs) == n_before + 1, "New survey... did not queue a job"
    index = len(runner.jobs) - 1
    job = runner.jobs[index]
    assert "new_survey.py" in job.command, job.command
    assert Path(job.argv[job.argv.index("--workspace") + 1]) == raw_root / "work", job.argv
    assert filled["channels"] == (LEMI423_PRESETS, DEFAULT_CHANNELS), filled["channels"]
    assert job.argv[job.argv.index("--channels") + 1] == NEW_SURVEY_CHANNELS, job.argv
    # the window stays responsive during the scan: click() itself returns
    # once the job is queued and started, well under the several seconds the
    # real script needs for 2 synthetic sites plus process start-up
    assert took_to_queue < 5.0, f"new_button.click() blocked for {took_to_queue:.1f} s: not async"
    # the runner's own echo (JobRunner._append), "$ ..." without a loguru
    # "HH:MM:SS | name | " prefix, as for the trivial job of criteria 12 and 18
    strip_now = console.toPlainText().splitlines()
    assert f"$ {job.command}" in strip_now, \
        "the job's command line had not reached the console strip while it ran"
    print(f"  dialog: name {filled['name']!r} (the folder's), timezone {filled['timezone']!r}; "
          f"queued and started in {took_to_queue:.2f} s (async), console already showing it")

    # app.processEvents() runs inside wait_until while the job (and the GUI)
    # keep going: this is what "the window stayed responsive" means here
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
    written_config = yaml.safe_load(want_yaml.read_text(encoding="utf-8"))
    written = written_config["workspace"]
    assert Path(written) == (raw_root / "work").resolve(), written
    assert written_config["defaults"]["channels"] == ["ex", "ey", "hx", "hy", "hz"], written_config["defaults"]
    assert all(cells[(site, "channels")] == NEW_SURVEY_CHANNELS for site in SYNTHETIC), cells
    new_fetch = fetches()[n_fetches:]
    assert new_fetch == [[sys.executable, str(REPO / "scripts" / "fetch_basemap.py"), str(want_yaml)]], new_fetch
    strip = console.toPlainText().splitlines()
    wrote = [line for line in strip if f"wrote {want_yaml}" in line]
    assert f"$ {job.command}" in strip and wrote, \
        "the console strip has no new_survey.py command or 'wrote' line"
    print("  finished: state.survey_yaml opened, window responsive throughout")
    print("  table: " + ", ".join(f"{s} serial {cells[(s, 'serial')]} firmware {cells[(s, 'firmware')]}"
                                  for s in SYNTHETIC) + f"; yellow line {meta.warning_label.text()!r}")
    print(f"  console: {job.command[:90]}...")
    print(f"  channels combo {filled['channels'][0]}, {filled['channels'][1]!r} preselected; set to "
          f"{NEW_SURVEY_CHANNELS!r}: --channels in the argv, defaults channels "
          f"{written_config['defaults']['channels']}, the table's cells {NEW_SURVEY_CHANNELS!r}")
    print(f"  workspace field {filled['workspace']!r} (<data folder>/work), survey.yaml workspace: {written}; "
          f"opening it ran fetch_basemap.py (recorded, not run): its workspace has no basemap.json")

    # ------------------------------------ (24) the basemap, fetched when missing
    print("(24) the basemap is fetched on survey open exactly when basemap.json is missing:")
    assert (WORK / "basemap.json").exists(), f"{WORK / 'basemap.json'} is missing: run scripts/fetch_basemap.py"
    assert startup_fetches == [], f"the window fetched a basemap the real workspace has: {startup_fetches}"
    bare = SCRATCH.parent / "gui_basemap_survey"
    shutil.rmtree(bare, ignore_errors=True)
    bare.mkdir(parents=True)
    for name in ("survey.yaml", "filters.yaml", "reference_edis.yaml"):
        shutil.copy2(SURVEY_DIR / name, bare / name)
    config = yaml.safe_load((bare / "survey.yaml").read_text(encoding="utf-8"))
    config["workspace"] = str(bare / "work")  # empty: no basemap.png, no basemap.json
    (bare / "survey.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    n_fetches = len(fetches())
    window.open_survey(bare / "survey.yaml")
    pump(app, 0.3)
    got = fetches()[n_fetches:]
    want = [[sys.executable, str(REPO / "scripts" / "fetch_basemap.py"), str((bare / "survey.yaml").resolve())]]
    assert got == want, f"opening a survey with no basemap ran {got}, expected {want}"
    site_map = process.site_map
    assert site_map.basemap_item is None and site_map.basemap_label.text().startswith("no basemap"), \
        site_map.basemap_label.text()
    print(f"  {bare.name} (empty workspace): run_now({' '.join(Path(a).name for a in got[0][1:])}), "
          f"map says {site_map.basemap_label.text()!r}")
    window.open_survey(SURVEY_YAML)
    pump(app, 0.3)
    assert fetches()[n_fetches + 1:] == [], "reopening the real survey fetched a basemap it has"
    print(f"  the window over the real survey and its reopening: no fetch ({WORK / 'basemap.json'} exists)")

    # ------------------------------------------ (25) Build MTH5 on the tree
    print("(25) Build MTH5 on the Time Series tab:")
    window.tabs.setCurrentWidget(ts)
    pump(app, 0.3)
    build = ts.build_button
    assert not state.has_archive(UNARCHIVED) and UNARCHIVED in state.raw_sites(), UNARCHIVED
    rows = {r.text(0): r for r in tree.site_items()}
    a02_row = rows[UNARCHIVED]
    assert a02_row.childCount() == 1 and a02_row.child(0).text(0) == NO_ARCHIVE_ROW, a02_row.child(0).text(0)
    assert not (a02_row.child(0).flags() & Qt.ItemIsEnabled), "the no-MTH5 row is enabled"
    tree.setCurrentItem(rows[SITE])
    pump(app)
    assert not build.isEnabled() and build.toolTip() == "archive exists", (build.isEnabled(), build.toolTip())
    tree.setCurrentItem(a02_row)
    pump(app)
    assert build.isEnabled(), f"Build MTH5 disabled on {UNARCHIVED}: {build.toolTip()!r}"
    print(f"  {SITE}: disabled, tooltip {'archive exists'!r}; {UNARCHIVED}: enabled, tooltip {build.toolTip()!r}")
    sleeper = runner.run_now("sleep 2 s", [sys.executable, "-c", "import time; time.sleep(2)"])
    pump(app)
    assert runner.running and not build.isEnabled(), "Build MTH5 is enabled while a job runs"
    busy_tip = build.toolTip()
    wait_until(app, lambda: runner.jobs[sleeper].status in ("done", "failed"), 30, "the sleeping job")
    pump(app)
    assert build.isEnabled(), f"Build MTH5 stayed disabled after the job: {build.toolTip()!r}"
    print(f"  while a job ran: disabled ({busy_tip!r}); enabled again after it")
    runner.reset()
    n_diverted = len(DIVERTED)
    build.click()
    pump(app)
    ingest_argv = [sys.executable, str(REPO / "scripts" / "ingest_site.py"), str(state.survey_yaml), UNARCHIVED]
    assert DIVERTED[n_diverted:] == [ingest_argv], DIVERTED[n_diverted:]
    assert not runner.running and ts.hint_label.text().startswith(f"building {UNARCHIVED}.h5 ..."), \
        (runner.running, ts.hint_label.text())
    print(f"  pressed on {UNARCHIVED}: run_now({' '.join(Path(a).name for a in ingest_argv[1:])}) recorded, "
          f"not run; hint {ts.hint_label.text()!r}")
    real_has_archive = state.has_archive
    state.has_archive = lambda site: site == UNARCHIVED or real_has_archive(site)
    try:
        pretend = runner.add(f"pretend ingest {UNARCHIVED}", [
            sys.executable, "-c", "print('pretend ingest')", str(REPO / "scripts" / "ingest_site.py"),
            str(state.survey_yaml), UNARCHIVED])
        runner.run_queue()
        wait_until(app, lambda: runner.jobs[pretend].status in ("done", "failed"), 30, "the pretend ingest")
        assert runner.jobs[pretend].status == "done", runner.jobs[pretend].output
        children = [a02_row.child(i).text(0) for i in range(a02_row.childCount())]
        assert NO_ARCHIVE_ROW not in children, children
        assert a02_row.childIndicatorPolicy() == QTreeWidgetItem.ShowIndicator and a02_row.isExpanded(), \
            (a02_row.childIndicatorPolicy(), a02_row.isExpanded())
        assert a02_row.data(0, Qt.ForegroundRole) is None, "A02's row is still grey"
        assert children and ts.hint_label.text().startswith(f"built {UNARCHIVED}.h5"), (children, ts.hint_label.text())
        print(f"  a finished job naming ingest_site.py {UNARCHIVED} (has_archive made True): the row is "
              f"expandable and open, children {children}, hint {ts.hint_label.text()!r}")
        wait_until(app, lambda: tree._thread is None and not tree._queue, 30, "the tree's read of A02")
        pump(app, 0.2)
    finally:
        state.has_archive = real_has_archive
    tree.refresh_site(UNARCHIVED)
    children = [a02_row.child(i).text(0) for i in range(a02_row.childCount())]
    assert children == [NO_ARCHIVE_ROW], children
    print(f"  has_archive truthful again: refresh_site put back {children}")
    runner.reset()
    assert not (WORK / "mth5" / f"{UNARCHIVED}.h5").exists(), f"{UNARCHIVED}.h5 was written"

    # a filtered variant's own stem (`<site>_f<hash>.h5`, crust.ingest.variant_path) is
    # another archive of its site, listed neither as a site nor as a stacked remote
    fake_variant = WORK / "mth5" / f"{SITE}_fdeadbeef.h5"
    fake_variant.write_bytes(b"")
    try:
        assert fake_variant.stem not in state.archived_sites(), state.archived_sites()
        assert fake_variant.stem not in state.stacked_remotes(), state.stacked_remotes()
        assert fake_variant.stem not in [n for _d, n in state.remote_choices(None)],             state.remote_choices(None)
    finally:
        fake_variant.unlink()
    print(f"  a filtered variant's own stem ({fake_variant.stem}) is invisible to archived_sites/"
          f"stacked_remotes/remote_choices")

    # ------------------------------------ (26) the Filter Data tab's preview
    print("(26) the Filter Data tab's preview, on a copy of the survey folder:")
    window.open_survey(make_survey_copy())
    pump(app, 0.3)
    ft = window.filters_tab
    window.tabs.setCurrentWidget(ft)
    pump(app, 0.3)
    chooser, pane = ft.chooser, ft.pane
    series, psd = pane.series, pane.spectra
    previews, preview_starts = [], []
    ft.preview.ready.connect(previews.append)
    ft.preview.started.connect(preview_starts.append)

    def latest_preview(entries, timeout, what):
        """The preview for exactly `entries` on the loaded window, waited for."""
        wait_until(app, lambda: previews and previews[-1].filters == entries
                   and previews[-1].segment is store.segment and not ft.preview.busy, timeout, what)
        pump(app, 0.2)
        return previews[-1]

    def curves_of(plot):
        """[(pen colour, dashed, visible, n points)] of every data curve on a plot."""
        out = []
        for item in plot.getPlotItem().listDataItems():
            pen = pg.mkPen(item.opts["pen"])
            x, _y = item.getOriginalDataset()
            out.append((pen.color().name(), pen.style() == Qt.DashLine, item.isVisible(),
                        0 if x is None else len(x)))
        return out

    def assert_raw_only(where):
        for comp, plot in series.plots.items():
            shown = [c for c in curves_of(plot) if c[2]]
            assert len(shown) == 1 and shown[0][0] == theme.colour(comp).lower(), (where, comp, curves_of(plot))
        for title, plot in psd.plots.items():
            assert all(not dashed for _c, dashed, _v, _n in curves_of(plot)), (where, title, curves_of(plot))

    chooser.site_combo.setCurrentIndex(chooser.site_combo.findText(SITE))
    wait_until(app, lambda: chooser.window_combo.count() == N_WINDOWS_D02, 30, "the chooser's D02 windows")
    fifth_start = t_rec + pd.Timedelta(hours=4 * window_h)
    t0 = time.time()
    chooser.window_combo.setCurrentIndex(4)
    wait_until(app, lambda: store.segment is not None and store.segment.station == SITE
               and store.segment.t0 == fifth_start, 60, "the fifth window chosen on the Filter Data tab")
    assert state.selection == (SITE, fifth_start, chooser.window_combo.itemData(4)[1]), state.selection
    raw_view = latest_preview([], 60, "the raw-only preview")
    loaded_seg = store.segment
    assert raw_view.filtered is None and raw_view.segment is loaded_seg
    assert list(series.plots) == list(EXPECTED_CHANNELS) and list(psd.plots) == SPECTRA_PANELS
    assert_raw_only("no filters")
    raw_sha = {c: hashlib.sha1(a.tobytes()).hexdigest() for c, a in loaded_seg.arrays.items()}
    print(f"  chooser: {SITE}'s fifth window loaded in {time.time() - t0:.1f} s ({loaded_seg.t0}, the "
          f"record start + 8 h); raw-only preview ({raw_view.elapsed_s:.1f} s): one curve per panel in "
          f"its colour; label {ft.window_label.text()!r}")

    ft.add_filter("notch")
    notch_view = latest_preview(ft.entries, 60, "the notch preview")
    assert notch_view.filters == [{"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2}}]
    for comp in EXPECTED_CHANNELS:
        assert not np.array_equal(notch_view.filtered[comp], loaded_seg.arrays[comp]), f"{comp} unfiltered"
    assert {c: hashlib.sha1(a.tobytes()).hexdigest() for c, a in store.segment.arrays.items()} == raw_sha, \
        "the store's raw arrays changed"
    raw_stage = next(stage for stage in notch_view.raw_stages if stage[0] == 1000.0)
    filt_stage = next(stage for stage in notch_view.filtered_stages if stage[0] == 1000.0)
    ex_raw = line_excess(raw_stage[1], raw_stage[2]["ex"], 50.0)
    ex_filt = line_excess(filt_stage[1], filt_stage[2]["ex"], 50.0)
    assert ex_raw - ex_filt > 15.0, f"Ex 50 Hz excess {ex_raw:.1f} -> {ex_filt:.1f} dB, drop under 15 dB"
    for comp, plot in series.plots.items():
        got = sorted((colour, visible, n) for colour, _d, visible, n in curves_of(plot))
        # three curves per panel: the raw (grey, shown), the filtered (colour, shown)
        # and the removed = raw minus filtered (colour, hidden until Removed mode)
        want = sorted([(theme.RAW_COLOUR.lower(), True, WINDOW_SAMPLES),
                       (theme.colour(comp).lower(), True, WINDOW_SAMPLES),
                       (theme.colour(comp).lower(), False, WINDOW_SAMPLES)])
        assert got == want, (comp, got)
    for title, plot in psd.plots.items():
        styles = {(dashed, colour == theme.RAW_COLOUR.lower()) for colour, dashed, _v, _n in curves_of(plot)}
        assert styles == {(True, True), (False, False)}, (title, curves_of(plot))
    print(f"  notch: every channel filtered, the raw SHA-1s unchanged; Ex 50 Hz excess {ex_raw:.1f} -> "
          f"{ex_filt:.1f} dB (drop {ex_raw - ex_filt:.1f} > 15); 4 panels of grey + colour over "
          f"{WINDOW_SAMPLES:,} samples; PSD panels {list(psd.plots)} dashed grey + solid colour")

    ft.add_filter("hp")
    ft.forms["hp"].cutoff.setValue(0.05)
    ft.move_filter(-1)
    hp_view = latest_preview(ft.entries, 60, "the hp + notch preview")
    kinds = [next(iter(entry)) for entry in hp_view.filters]
    assert kinds == ["hp", "notch"], kinds
    assert hp_view.provenance[0].startswith("hp highpass 0.05 Hz") and hp_view.provenance[1].startswith("notch"), \
        hp_view.provenance
    print(f"  hp 0.05 Hz moved above the notch: provenance {[line[:22] for line in hp_view.provenance]}")

    for mode, grey_shown, colour_shown, removed_shown in (
        ("Before", True, False, False), ("After", False, True, False),
        ("Both", True, True, False), ("Removed", False, False, True),
    ):
        next(b for b in pane.mode_group.buttons() if b.text() == mode).setChecked(True)
        pump(app, 0.1)
        for comp in series.plots:
            got = (series.raw_items[comp].isVisible(), series.filtered_items[comp].isVisible(),
                   series.removed_items[comp].isVisible())
            assert got == (grey_shown, colour_shown, removed_shown), (mode, comp, got)
        if mode in ("Both", "Removed"):
            # the y range follows the trace being read rather than the raw one, whose
            # large removed component would hide the filtered channels at fine zoom;
            # pyqtgraph pads the auto range by about a tenth on each side
            shown = series.filtered_items["ex"] if mode == "Both" else series.removed_items["ex"]
            plot = series.plots["ex"]; vb = plot.getViewBox(); vb.autoRange(); pump(app, 0.1)
            lo, hi = vb.viewRange()[1]
            y = shown.yData; pad = 0.2 * (np.nanmax(y) - np.nanmin(y))
            assert np.nanmin(y) - pad <= lo and hi <= np.nanmax(y) + pad, (mode, "y range not set by the shown trace", lo, hi, np.nanmin(y), np.nanmax(y))
            if mode == "Removed":
                raw = series.raw_items["ex"].yData
                assert hi - lo < 0.75 * (np.nanmax(raw) - np.nanmin(raw)), ("Removed y range as wide as the raw", hi - lo)
    next(b for b in pane.mode_group.buttons() if b.text() == "Both").setChecked(True)
    pump(app, 0.1)
    print("  Before: grey only; After: colour only; Both: both, y set by the filtered trace; Removed: raw minus filtered only")

    ft.list.setCurrentRow(1)
    pump(app, 0.1)
    n_starts = len(preview_starts)
    ft.forms["notch"].q.setValue(25.0)
    ft.forms["notch"].q.setValue(20.0)
    pump(app, 0.3)
    assert len(preview_starts) == n_starts, "the preview ran before the debounce ended"
    q_view = latest_preview(ft.entries, 60, "the q 20 preview")
    pump(app, 1.0)
    assert len(preview_starts) == n_starts + 1, f"{len(preview_starts) - n_starts} runs for two q changes"
    assert "q=20" in q_view.provenance[1], q_view.provenance
    print(f"  q 30 -> 25 -> 20 in quick succession: one run after the debounce, {q_view.provenance[1][:40]!r}")

    pane.channel_boxes["hx"].setChecked(False)
    pump(app, 0.1)
    assert series.plots["hx"].isHidden() and not series.plots["hy"].isHidden()
    bx_items = [item for comp, item in psd.items["Bx-Ey (Zyx)"] if comp == "hx"]
    assert bx_items and not any(item.isVisible() for item in bx_items)
    pane.channel_boxes["hx"].setChecked(True)
    pump(app, 0.1)
    assert not series.plots["hx"].isHidden() and all(item.isVisible() for item in bx_items)
    print("  Show: Bx unticked hid its panel and its PSD curves; ticked, they came back")

    ft.list.setCurrentRow(0)
    ft.remove_filter()
    ft.add_filter("cp")
    cp_view = latest_preview(ft.entries, 60, "the notch + cp preview")
    assert [next(iter(entry)) for entry in cp_view.filters] == ["notch", "cp"], cp_view.filters
    print(f"  timing: notch + cp on the 2 h window ({WINDOW_SAMPLES:,} samples x 4 channels): "
          f"{cp_view.elapsed_s:.2f} s (filters + filtered PSD ladder; the raw ladder is cached per window, "
          f"{raw_view.elapsed_s:.2f} s once)")
    assert ft.archive_label.text() == "", ft.archive_label.text()
    assert not ft.delete_button.isVisible(), "Delete archive shown for D02's unsaved list"
    shoot(app, window, "filters", ft)
    print(f"  archive note {ft.archive_label.text()!r} (D02's edits are unsaved), Delete archive hidden")

    # A07's real (saved) `replace` entry, no variant built yet: a direct,
    # read-only check of `_update_archive_note` that leaves D02's loaded
    # window and its (unsaved) working list as they are; `state.site` is set
    # and restored without `set_site` (no site_changed signal, so
    # `ft.entries`, the preview and the selection stay)
    prev_site = state.site
    state.site = "A07"
    ft._update_archive_note()
    assert ft.archive_label.text() == (
        "filtered archive for this list: not built yet (built when processing starts)"), ft.archive_label.text()
    assert not ft.delete_button.isVisible(), "Delete archive shown for A07, which has no variant file yet"
    state.site = prev_site
    ft._update_archive_note()
    assert ft.archive_label.text() == "" and not ft.delete_button.isVisible()
    print("  A07 (a saved replace, no variant built): archive note 'not built yet'; D02 empty again on the way back")

    ft.add_filter("burst")
    burst_view = latest_preview(ft.entries, 60, "the notch + cp + burst preview")
    assert burst_view.provenance[-1].startswith("burst:"), burst_view.provenance
    print(f"  burst added: {burst_view.provenance[-1][:70]!r} ({burst_view.elapsed_s:.2f} s)")

    from crust.gui.filter_forms import LABELS  # (26) only: the list row's words for the kind
    ft.add_filter("mains")
    mains_view = latest_preview(ft.entries, 60, "the notch + cp + burst + mains preview")
    assert mains_view.provenance[-1].startswith("mains:"), mains_view.provenance
    mains_row = ft.list.item(len(ft.entries) - 1).text()
    assert mains_row.startswith(LABELS["mains"] + ": "), mains_row
    print(f"  mains added: {mains_view.provenance[-1][:90]!r} ({mains_view.elapsed_s:.2f} s); row {mains_row!r}")

    while ft.entries:
        ft.list.setCurrentRow(0)
        ft.remove_filter()
    empty_view = latest_preview([], 60, "the raw-only preview again")
    assert empty_view.filtered is None and empty_view.filtered_stages is None
    assert_raw_only("every filter removed")
    assert SITE not in (yaml.safe_load((SURVEY_DIR / "filters.yaml").read_text(encoding="utf-8")) or {})
    print("  every filter removed: the raw-only view again; the real filters.yaml has no D02 entry")
    ft.wait()

    # --------- the window chooser's "(loaded)" mark
    # This test fails if the loaded window is not the one and only marked
    # row, or the mark does not follow a change of window.
    print("  the window chooser's loaded-window mark:")
    LOADED = "   (loaded)"

    def marked_rows(combo):
        """Return the rows bold, accent-coloured and suffixed "(loaded)", checking every other row is plain."""
        rows = []
        for k in range(combo.count()):
            font = combo.itemData(k, Qt.FontRole)
            brush = combo.itemData(k, Qt.ForegroundRole)
            colour = brush.color() if hasattr(brush, "color") else brush
            text = combo.itemText(k)
            if font is not None and font.bold():
                rows.append(k)
                assert colour is not None and colour.name() == QColor(theme.HIGHLIGHT).name(), \
                    (k, text, "the loaded row's foreground is not theme.HIGHLIGHT")
                assert text.endswith(LOADED), (k, text, "the loaded row has no (loaded) suffix")
            else:
                assert colour is None, (k, text, "a plain row still carries a foreground brush")
                assert not text.endswith(LOADED), (k, text, "a plain row still carries the (loaded) suffix")
        return rows

    # D02's fifth window (row 4) was loaded above: the only marked row
    before = marked_rows(chooser.window_combo)
    assert before == [4], (before, "D02's fifth window (row 4, just loaded) should be the only mark")
    print(f"    D02's fifth window still the only mark: row 4, {chooser.window_combo.itemText(4)!r}")

    # a different window loaded through the chooser: the mark follows it
    other_start, other_end = chooser.window_combo.itemData(2)
    chooser.window_combo.setCurrentIndex(2)  # signals on: loads it, as the fifth window was loaded above
    wait_until(app, lambda: store.segment is not None and store.segment.station == SITE
               and store.segment.t0 == other_start, 60, "D02's third window chosen through the chooser")
    assert state.selection == (SITE, other_start, other_end), state.selection
    moved = marked_rows(chooser.window_combo)
    assert moved == [2], (moved, "the mark did not move to row 2, or row 4 is still marked")
    print("    switched to row 2: the mark moved there, row 4 back to plain")

    chooser.window_combo.showPopup()
    QApplication.processEvents()
    popup = chooser.window_combo.view().window()
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    popup_path = SHOT_DIR / "gui_filter_window_popup.png"
    assert popup.grab().save(str(popup_path)), f"could not save {popup_path}"
    chooser.window_combo.hidePopup()
    pump(app, 0.1)
    print(f"    popup screenshot saved to {popup_path}")

    # --------- "Copy to sites..." (33)
    # This test fails if the copy does not write the ticked sites' lists as
    # the source's, or touches an unticked site, or Append replaces.
    print('  "Copy to sites...":')
    from crust.gui.copy_filters import CopyFiltersDialog  # (33) only

    if not ft.entries:  # (26) may have emptied it: (33) needs a non-empty source list
        ft.add_filter("notch")
        pump(app, 0.2)
    assert ft.entries, "(33) could not give D02 a filter to copy"
    d02_filters = [dict(entry) for entry in ft.entries]
    filters_path = state.filters_yaml()
    before_replace = yaml.safe_load(filters_path.read_text(encoding="utf-8")) or {}

    def copy_dialog(tick, append, on_ready=None):
        """Click "Copy to sites..." and fill the dialog as the button's own handler drives it.

        Once the dialog is up: run `on_ready`, tick `tick`, set Replace or
        Append and press OK.
        """
        def fill():
            # the dialog now up, rather than a closed one still awaiting deletion
            dialog = next((d for d in ft.findChildren(CopyFiltersDialog) if d.isVisible()), None)
            if dialog is None:
                QTimer.singleShot(50, fill)
                return
            if on_ready is not None:
                on_ready(dialog)
            for name in tick:
                dialog.boxes[name].setChecked(True)
            (dialog.append_radio if append else dialog.replace_radio).setChecked(True)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
        QTimer.singleShot(50, fill)
        ft.copy_button.click()  # exec(): returns once fill() closes the dialog

    def check_offer(dialog):
        assert SITE not in dialog.boxes, "the source site offered itself"
        assert len(dialog.boxes) >= 50, f"only {len(dialog.boxes)} other sites offered"
        assert dialog.replace_radio.isChecked() and not dialog.append_radio.isChecked(), \
            "Replace is not the dialog's default"

    def settle(label):
        """Wait for the reload a copy causes, one reload in flight at a time.

        `_copy_to_sites` reopens the whole survey and reloads the window while
        it is loaded (the same as `save()`): wait for that load and its full QC
        to finish, and any stale preview run, before the next dialog opens.
        """
        wait_until(app, lambda: store.segment is not None and store.segment.station == SITE
                   and store.segment.t0 == other_start and not store.busy,
                   90, f"D02's window settled after {label}")
        wait_until(app, lambda: not ft.preview.busy, 60, f"the preview settled after {label}")
        pump(app, 0.3)

    copy_dialog(["E08", "A07"], append=False, on_ready=check_offer)
    settle("the Replace copy")
    after_replace = yaml.safe_load(filters_path.read_text(encoding="utf-8")) or {}
    assert after_replace.get("E08") == d02_filters, (after_replace.get("E08"), d02_filters)
    assert after_replace.get("A07") == d02_filters, (after_replace.get("A07"), d02_filters)
    rest_before = {s: v for s, v in before_replace.items() if s not in ("E08", "A07")}
    rest_after = {s: v for s, v in after_replace.items() if s not in ("E08", "A07")}
    assert rest_after == rest_before, "Replace touched a site other than the two ticked"
    assert ft.entries == d02_filters, "D02's own (unsaved) list changed by copying it elsewhere"
    print(f"    Replace: E08 and A07 now hold D02's {len(d02_filters)} filter(s); every other entry, "
          f"D02's own included, unchanged")

    while len(ft.entries) > 1:
        ft.list.setCurrentRow(len(ft.entries) - 1)
        ft.remove_filter()
    one_filter = [dict(entry) for entry in ft.entries]
    kind_name = next(iter(one_filter[0]))
    e08_before_append = after_replace["E08"]
    copy_dialog(["E08"], append=True)
    settle("the Append copy")
    after_append = yaml.safe_load(filters_path.read_text(encoding="utf-8")) or {}
    assert after_append["E08"] == e08_before_append + one_filter, \
        (after_append["E08"], e08_before_append, one_filter)
    assert len(after_append["E08"]) == len(e08_before_append) + 1, "E08's list did not grow by exactly one"
    assert after_append.get("A07") == d02_filters, "A07 changed by an E08-only Append"
    print(f"    Append: E08's list grew by D02's one remaining filter ({kind_name}), its own "
          f"{len(e08_before_append)} first")

    before_empty = filters_path.read_bytes()
    copy_dialog([], append=False)
    pump(app, 0.3)
    assert filters_path.read_bytes() == before_empty, "OK with nothing ticked wrote to filters.yaml"
    print("    nothing ticked: OK did nothing, filters.yaml unchanged")

    # a site picked elsewhere (as the tree does), nothing loaded for it yet: no row marked
    state.set_site("E08")
    wait_until(app, lambda: chooser.site() == "E08" and chooser.window_combo.count() > 0,
               60, "E08's windows listed for the chooser (state.set_site, no window picked)")
    pump(app, 0.2)
    assert state.selection == (SITE, other_start, other_end), "picking a site alone loaded a window"
    unmarked = marked_rows(chooser.window_combo)
    assert unmarked == [], (unmarked, "E08 has no loaded window: no row should be marked")
    print(f"    E08 shown with nothing loaded for it: no row marked, {chooser.window_combo.count()} windows listed")

    mixed_instruments(app, window)
    crosspower_check(app, window)  # (34)

    assert len(SHOTS) == 11, f"{len(SHOTS)} screenshots, expected 11: {SHOTS}"
    assert SURVEY_YAML.read_bytes() == REAL_YAML, "the real surveys/curnamona_cube/survey.yaml changed"
    print("\nthe real survey.yaml is unchanged; screenshots:")
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
