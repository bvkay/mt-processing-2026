# bbmt_gui — the desktop GUI

A launcher and a viewer over the scripts in `scripts/` and the per-survey YAML.
It replaces the MATLAB App Designer app the students know, tab for tab, and
after the owner tried the first slices it was redirected to work the way that
app worked. His two decisions, verbatim:

> "I really don't think the png images work within the GUI."

> "I think we need to follow how I set up the matlab app designer app, as
> there was a tree on the left side of the time series tab, where the user can
> see all the sites from the metadata, then they could expand a site, which
> would then show a selection of times from that site, if it was 1000 Hz data,
> it would show two hour time windows, if it was 500 Hz data it would show 4
> hour time windows and so on, and when the user clicked on one of those time
> windows from a site, it would then load that data in full for the selected
> window and display the time series, display the spectra, display the
> spectrogram and coherence. And when the user clicked on a different site it
> would then load that time window and so on."

So: **no PNG is displayed anywhere in the GUI** (the scripts still write the
report figures from the Process tab; the log names them and they stay on
disk), and the QC tabs are live views of **one window** picked in a tree.

## Launch

From the repo root, with the `bbmt-2026` env active:

```bash
python -m bbmt_gui surveys/curnamona_cube/survey.yaml
```

The argument is optional — without it the window opens empty and you pick the
survey from **File > Open survey...** or the button on the Metadata tab.

Smoke test (no window appears, writes `work/qc/gui_*.png` you can look at) and
the Qt-free unit tests — the tree's window list, the segment QC engine on a
synthetic hour, and the library's PSD ladder:

```bash
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
python tests/windows_unit.py
python tests/segment_unit.py
python tests/psd_ladder_unit.py
python tests/survey_unit.py          # distance_km, Survey.timezone
python tests/ingest_unit.py          # ingest_site(ignore_filters=...)
python tests/process_rr_cli_unit.py  # process_rr.py --dry-run, the estimator tweaks
python tests/basemap_unit.py         # fetch_basemap.py's warp, network mocked
python tests/new_survey_unit.py      # new_survey.py on synthetic B423s, then the Curnamona headers
```

## The flow: tree -> window -> every view

1. **Time Series** has a tree on the left of every site in the survey's
   metadata (`State.all_sites()`), bold and collapsed. A site with an MTH5
   archive expands to its **windows**: a constant 7.2 million samples per
   channel, so 2 h at 1000 Hz, 4 h at 500 Hz (`windows.py`), from the record
   start, the last one shorter, any window with under 10 minutes of samples
   inside the runs left out. A site without an archive is greyed with one
   row saying to ingest it from the Process tab. A click on a site row
   toggles it; a click on a window row selects it.
2. Selecting a window makes it `State.selection` and asks the one
   `SegmentStore` for it. The store's worker reads the local station
   (`segment.load_segment`) and hands the `Segment` straight out
   (`segment_loaded`, about a second for 2 h of D02); the Time Series tab
   draws it in full on the right — Bx, By, Ex, Ey stacked on one x axis
   at the full rate, physical units, the offset the segment removed added
   back for display, gaps as holes. The worker goes on to read the remote and compute the QC
   (`compute_segment_qc`, `bbmt.timefreq` only), and `qc_ready` follows in
   about ten seconds.
3. **Spectra**, **Spectrogram** and **Coherence** each redraw on `qc_ready`
   and say "load a window from the tree on the Time Series tab" until one
   exists. Every view is labelled with the station, the window's start and
   end in UTC, and the remote if any.
4. A click on a window of a different site loads that one instead: one
   worker at a time, the latest request wins, a result that no longer matches
   the selection is discarded, and a `Segment` is only drawn when its station
   and window match the selection.

The **remote** the QC is computed against is the Coherence tab's combo
(`State.remote`), "(none)" on every new station: the local pairs answer
the usual questions, the remote pairs only whether a low coil coherence is
a dead coil or a quiet field, so they are switched on when that is the
question. A remote that does not cover the window is dropped with a note
in every view's title. Changing the combo asks the store again.
The **processing window** is the Time Series tab's *visible* range: zoom to
the stretch you want and "Use visible range as processing window" sends its
UTC start and end to the Process tab. `State.goto_time` (the Coherence tab's
"Show in Time Series", from the cursor on its band panels) puts the Time
Series view ±5 minutes around a moment, inside the loaded window.

## The one rule

**No processing code lives in the GUI.** If a number ends up in a product —
an EDI, a transfer function, a report figure — it is computed in `src/bbmt/`
and reached through a script in `scripts/`, which the GUI runs as a subprocess
with the repo root as its working directory. The GUI only:

1. reads `survey.yaml` (through `bbmt.survey.Survey`) to know what exists --
   and writes back only what a person typed into it: the Metadata tab's
   edited cells into the `sites:` block, the Filter Data tab's lists into
   `filters.yaml`,
2. reads MTH5 archives to *draw* them (`archive.py`, `segment.load_segment`,
   read-only),
3. builds a command line, runs it, shows its log.

Refined, in the owner's words: NO PRODUCT (archive, transfer function, EDI,
report figure) is computed in the GUI; the QC views may compute on data
already loaded for display, but ONLY by calling functions in
`src/bbmt/timefreq.py` — never with spectral maths written inside
`src/bbmt_gui`. `segment.py` calls `levels_plan`, `cascade`,
`band_from_levels`, `levels_to_grid`, `psd_ladder` and `power_db` on the
selected window and holds no maths of its own; what it produces is drawn
and thrown away. The only arithmetic in the tabs is a picture's: percentile
colour limits, the row median the Spectrogram's "relative to median" view
subtracts, the mean of a pair's band lines the Coherence tab draws as "All
frequencies", seconds shown as minutes, an axis's clip or extent.

Two consequences worth knowing. Jobs run **one at a time**, because an MTH5
must never be open in two processes (HDF5 locking) — so there is exactly one
`JobRunner` in the window, `state.runner`, and every tab queues on it; the
queue table and the script log live on the Process tab (`queue_table.py`),
where every job from every tab is a row.
And there is **no single-station option** anywhere: every product is
remote-referenced, so the Process tab always wants a remote — an adjacent
site, a dedicated remote, or a stacked synthetic remote from
`scripts/build_stack.py` (shown as "(stack)").

**Queuing a job never starts it** (Ben, 2026-09-23): the MATLAB app kept "add
to Queue" and "Process Queue" as two separate steps, and the students already
know that flow, so every button that queues a job here — Add to queue, Timing
check, Site QC figures, Build stack, Fetch basemap, on the Process tab, the
only tab that queues anything — only calls `JobRunner.add`; only **Run queue** calls
`JobRunner.run_queue`. A status label beside the buttons reads "N job(s)
queued - press Run queue" whenever jobs are waiting and the queue is idle.
The one exception is the Metadata tab's **New survey...**
(`metadata_edit.start_new_survey`): it is not a processing job, opens no
archive, and the point of moving it onto the queue was to stop it blocking
the window, not to make a student press Run queue for it — so it calls both
`add` and `run_queue` together, and refuses to queue at all (a message box,
rather than waiting its turn) if another job is already running.

## The console strip

The owner's request, verbatim: "a small two-three line area at the bottom of
our GUI, where it echoes the command line terminal, that way the students can
see the python commands and outputs that are part of the backend that are
running when they click on something." `console.ConsoleStrip` sits under the
tab widget in a vertical `QSplitter` (`app.py`'s `console_splitter`), three
lines tall by default and read-only, so a student can drag it taller to read
a full log while the tabs keep the stretch. Three sources feed it, all
through its `append(line)` slot:

1. `state.runner.log_line` — every line of the subprocess queue's merged log,
   exactly as a terminal shows it: the "$ ..." command line the runner
   already prefixes, then its stdout/stderr, unfiltered.
2. the in-process backend's own **loguru** logger, through `console.LoguruQtSink`
   — a small `QObject` loguru calls as a plain sink (`logger.add(sink,
   level="INFO", format="{time:HH:mm:ss} | {name} | {message}")`), which
   re-emits each formatted line as a `Signal(str)` on a queued connection, so
   a line logged off the GUI thread (`bbmt.timefreq`'s `cascade` and
   `psd_ladder`, called by `SegmentStore`'s worker `QThread`) still lands on
   the strip safely. Only loguru records reach it, so pyqtgraph's and Qt's
   own console noise — neither writes with loguru — never does.
3. `state.segment_store.qc_started`, prefixed "[segment] " so a window load
   reads as one line, e.g. "[segment] D02 12:55 to 14:55 UTC".

`MainWindow.closeEvent` tells the strip it is shutting down and removes the
loguru sink before anything else, so a line arriving mid-teardown from a
worker thread's queued connection is dropped rather than raised, and the sink
never outlives the widget it writes to.

## Layout — one file per tab, one class per tab

```
src/bbmt_gui/
    __main__.py        python -m bbmt_gui [survey.yaml]; theme.apply before the window
    theme.py           the look: apply(app) (dark Fusion palette, pyqtgraph and
                       matplotlib greys) and every colour -- B_COLOUR, E_COLOUR,
                       REMOTE_COLOUR, the Schumann and mains marks, the bands
    app.py             State (survey, site, selection, remote, the one JobRunner,
                       the SegmentStore, the ArchiveLock, goto_time) + MainWindow
                       (the tabs over the console strip in a QSplitter; installs
                       and removes the loguru sink)
    console.py         ConsoleStrip (a 3-line, read-only, monospace QPlainTextEdit
                       under the tabs, fed the runner's log, "[segment] " QC
                       starts and the in-process loguru log) + LoguruQtSink (a
                       QObject sink so a worker thread's log line reaches it
                       through a queued connection)
    jobs.py            JobRunner (QProcess queue; a Job can carry the station,
                       remote, window and options the queue table shows); the
                       queue table (`queue_table.py`) is the only view of it now
    archive.py         read-only MTH5 reading for the views, nothing else;
                       Grid + load_grid + run_slices are the one copy of the run arithmetic
    windows.py         window_hours / window_list / window_label (no Qt): the
                       windows the tree offers, 7.2 M samples per channel each
    reader.py          ReadThread: one archive read off the GUI thread;
                       ArchiveLock: one archive open at a time across threads
    site_tree.py       SiteTree: the sites, their windows read on first expansion
    segment.py         Segment / load_segment / SegmentQC / compute_segment_qc
                       (no Qt): the segment QC engine, bbmt.timefreq only
    segment_store.py   SegmentStore on State: one worker loads the selected window
                       (+ remote) and computes its QC; segment_loaded, then qc_ready
    plots.py           pyqtgraph helper: a stack of x-linked channel plots with
                       no gaps; share_x_axis (tick values on the bottom plot only)
    qc_plots.py        pyqtgraph helpers for the QC tabs: PSD ladder + frequency
                       marks, period-time images (PColorMeshItem + colour bar),
                       band lines + "All frequencies", lock_view; LadderControls
    tf_plot.py         the one mtpy-v2 caller: load_mt (an MT per file, cached) and
                       draw(figure, [(label, path)], choice) onto the View EDIs canvas
    site_map.py        SiteMap: the Process tab's map, real longitude and
                       latitude with the ViewBox aspect locked to cos(mean
                       latitude), over <workspace>/basemap.png if fetched,
                       + distance label; basemap_argv (the Fetch basemap
                       argv); PairSummary: row 1's distance, overlap, window
                       length, recommended remote
    window_bar.py      WindowBar (both spans, the window region, the start field
                       at its left end and the end field at its right with the
                       local time under each, the status between two lamps) and
                       site_span, the reader behind it
    stack_builder.py   StackBuilder (a build_stack.py argv; the tab's Build stack
                       button calls it) and RunOptions (the band kwargs, the
                       ingest-filters switch and the tag suffix, and under
                       them EstimatorOptions, the collapsed "Advanced (aurora
                       estimator)" block)
    queue_table.py     QueueTable (#, Station, Remote, Window, Options, Status
                       over state.runner), QueuePanel (the table over the
                       script log) and ProductList (the EDIs the jobs wrote)
    filter_forms.py    one small form per filter kind, for the Filter Data tab
    metadata_edit.py   the Metadata tab's editing: NewSurveyDialog + start_new_survey
                       (scripts/new_survey.py on state.runner, started at
                       once) and handle_new_survey_finished (opens what it
                       wrote), rewrite_sites_block (only the sites: block),
                       format_cell / parse_cell, ask_yes_no
    tabs/                             (in tab order -- the MATLAB app's:
        metadata.py    MetadataTab     QC first, then filters, processing, EDIs)
        timeseries.py  TimeSeriesTab  the tree + the loaded window at the full rate
        spectra.py     SpectraTab     the window's PSDs: a Zxy and a Zyx panel
        spectrogram.py SpectrogramTab the window's dB images per channel
        coherence.py   CoherenceTab   band lines per pair, two aligned columns
        filters.py     FiltersTab     drives <survey>/filters.yaml
        process.py     ProcessTab     the MATLAB Process Data tab's rows; drives
                                      timing_qc / process_rr / site_qc / psd_qc /
                                      build_stack / fetch_basemap
        edis.py        EdiTab         mtpy-v2 draws <workspace>/tf/*.edi +
                                      reference_edis.yaml on one live canvas
```

`State` is shared by every tab and emits `survey_changed`, `site_changed`,
`selection_changed`, `remote_changed` and `goto_time`; `MainWindow.reload_tabs()`
calls each tab's `reload()` when a survey is opened, so a tab never has to
know about any other tab. `State.request_qc()` is the one place the store is
asked for the selection with the current remote and ladder.

## The look — `theme.py`

The owner compared this GUI with his MATLAB App Designer app (2026-09-23) and
asked for its look: "the time series plots can share an axis, lets have the
magnetics as the first two subplots, coloured blue, while the electrics are
the last two subplots coloured red", "keep the vertical grid", the spectra
"locked in so they can not zoom out further", "faint dashed vertical lines
highlighting the Schuman bands", "make the axis tight so we have no gaps",
"how well everything blends into each other", and names like "Zxy (By-Ex)".
`theme.apply(app)` runs once, on the `QApplication`, before the window is
built (`__main__`; the smoke test does the same), so it reaches every tab,
including the ones that never import it:

- **One grey surface.** The Fusion style with a dark palette: window and
  buttons #2b2b2b, text boxes, tables, lists and every plot area #1f1f1f,
  text #e6e6e6, disabled text #7a7a7a, a muted blue selection, dark
  tooltips; the theme sets no stylesheet. pyqtgraph's `background` and
  `foreground` config options and matplotlib's rcParams (figure and axes
  face, text, ticks, spines, grid, legend) are set to the same greys, so
  the View EDIs canvas blends too (mtpy 2.1.4 sets none of those;
  checked). One
  exception to "Fusion as it comes": Fusion draws a check box's outline
  from the window grey, darkened, which left an unticked box invisible on
  this surface (the View EDIs tree, the Filter Data forms, the Process
  tab's switch), so a small `QProxyStyle` draws only the check box and
  radio indicators with a light grey outline.
- **One set of colours**, all in `theme.py`: magnetics `B_COLOUR`
  (#4fc3f7, cyan-blue) and electrics `E_COLOUR` (#ff5252, red) on every
  tab, the remote's coils `REMOTE_COLOUR` (light grey), `colour(comp)` to
  pick one, `label(comp)` for the MATLAB names (Bx, By, Ex, Ey, rBx, rBy,
  from `bbmt.timefreq.BLABEL`); the Spectra marks (Schumann green, mains
  orange, both faint and dashed); the Coherence band colours, the white
  "All frequencies" curve and the amber cursor; the Process tab's traffic
  light and site roles (`OK_COLOUR` green, `WARN_COLOUR` amber, `BAD_COLOUR`
  red, `IDLE_COLOUR` grey, `PAIR_REMOTE_COLOUR` blue) and its cyan-blue
  summary text (`SUMMARY_COLOUR`). A tab never writes a hex colour of its
  own.
- **Stacks share one x axis.** Magnetics first (`CHANNEL_ORDER` = hx, hy,
  ex, ey). Panels of a stack sit with no gap between them, and only the
  bottom one shows x tick values and the x label (`plots.share_x_axis`:
  the upper ones keep their bottom axis for the grid and the inward ticks,
  without values it takes no height). The pixel-linked stacks keep one
  fixed left-axis width.
- **Locked zoom.** A view starts at its data's extent with no padding and
  can never be panned or zoomed out past it (`qc_plots.lock_view`:
  `setLimits` with min, max and maximum range, then `setRange(padding=0)`).
  On a log axis the limits are in log10, which is how pyqtgraph's ViewBox
  holds a log range. The Time Series tab keeps its own rule (x limits at
  the window's ends, y following what is visible).
- **Names** are the MATLAB app's: "By-Ex (Zxy)", "Bx-Ey (Zyx)",
  "Bx-By (magnetic)", "Ex-Ey (electric)", "rBy-Ex (Zxy, remote)", ...

## Adding a tab

1. Write `src/bbmt_gui/tabs/<name>.py` with one `QWidget` subclass that takes
   `state` as its first constructor argument and has a `reload()` rebuilding
   itself from `state.survey`. Say in the class docstring which script, YAML
   file or store signal the tab drives or draws.
2. In `app.py`, import it inside `MainWindow.__init__`, construct it and
   `self.tabs.addTab(...)`. Add it to the loop in `reload_tabs`.
3. If it runs anything long, queue it on `state.runner` (never make a second
   `JobRunner`) — do not import `bbmt` and compute in the GUI. If it draws the
   selected window, connect to `state.segment_store.qc_ready` (or
   `segment_loaded`) and take the numbers from the `SegmentQC`.
4. Add it to `tests/gui_smoke.py`'s criteria and screenshot loop.

Hand-written layouts only (`QGridLayout`, `QVBoxLayout`, `QSplitter`) — no
`.ui` files, no Designer. Plain signals and slots. Keep each file under about
350 lines; if a tab outgrows that, the extra probably belongs in a script.
(The tests are exempt: `tests/gui_smoke.py` is one linear script on purpose,
so its criteria can be read top to bottom.)

## Notes for the tabs

- **Metadata** — the table's numbers are what the YAML declares (a site with
  no value of its own shows the survey's `defaults:`); serial, firmware, start
  and end, right after remote, are the recorder facts `scripts/new_survey.py`
  read from the B423 headers and file names, read-only; "raw folder" and
  "archive" say what is actually on disk right now; "filters" is whether the
  site has a declared noise filter list in `<survey>/filters.yaml`. Click a
  header to sort. Selecting a row sets `State.site`, which the tree highlights.
  - **A new survey** (the owner's decision, 2026-09-23: a student with a new
    survey has only a folder of site folders and paper field notes, no
    survey.yaml). **New survey...** opens a dialog -- data folder (Browse...),
    survey name (the folder's name until typed over), instrument (lemi423),
    time zone (Australia/Adelaide), an optional site table -- which shows
    where it writes (`surveys/<name>/survey.yaml`) and, on OK, closes and
    queues `scripts/new_survey.py` on `state.runner`, starting it at once
    (`metadata_edit.start_new_survey`): the one job in this GUI exempt from
    "queuing a job never starts it" above, since it is not a processing job
    and never opens an archive. The window stays responsive while it runs;
    its command line and output reach the console strip the way any job's
    do. `handle_new_survey_finished`, wired to `state.runner.job_finished`
    once in `MetadataTab.__init__`, opens the survey.yaml on success
    (`State.open_survey`) or shows the last lines of output on failure. If a
    job is already running, New survey... says so and does not queue behind
    it. An existing survey.yaml is overwritten (`--force`) only after a Yes.
    The script reads each site's first B423 header through mt-io (serial,
    firmware, GPS position and elevation) and, for the sample rate, a bounded
    read of the first file's first 4096 records (`fast_sample_rate` in
    `scripts/new_survey.py`, snapped to the nearest of the LEMI-423's
    documented rates) rather than mt-io's own whole-file scan -- milliseconds
    a site instead of about 0.7 s, so 59 Curnamona sites take a few seconds
    rather than ~45 s -- plus the file-name epochs for the span; it writes
    the dipole lengths and azimuths **only** in `defaults:`, so every site
    says "dipole lengths and azimuths from defaults - set them from the
    field sheet" until they are set here. It also copies the LEMI-120
    response into `sensors/`. When legacy EDIs exist, run
    `scripts/match_reference_edis.py` afterwards.
  - **Editing.** latitude, longitude, elevation, dipole_length_ex/ey,
    azimuth_ex/ey, remote, timing and notes are editable (double-click or
    F2); a line beside the buttons counts the unsaved changes. **Save
    survey.yaml** writes only the cells whose value changed
    (`metadata_edit.rewrite_sites_block`): everything above `sites:` is kept
    byte for byte (as `scripts/burra_notes_to_yaml.py`'s `write_sites_block`
    does), so is any top-level key after the block and the file's line
    endings, and every per-site key the table does not show is kept; a
    blank or a dash drops the site's own key, so the default applies again;
    a number that does not parse is refused on the status line. Then the
    survey is reopened, so every tab sees the edit. Comments *inside* the
    sites block are lost, as when the generator scripts rewrite it.
  - **Import site table...** merges a CSV or XLSX (a `site` column plus any
    of the editable columns, headers matched case-insensitively; template
    `docs/site_table_template.csv`) into the table: only the columns the file
    has, only the sites that match, and an empty cell changes nothing. The
    status line reads "N of M sites matched" and names any site not in the
    survey and any column it ignored. Nothing is written until Save. The
    same reader (`bbmt.survey.read_site_table`) serves
    `new_survey.py --site-table`.
  - **`generated_by:`** -- a top-level key naming the script that writes the
    sites block (`scripts/burra_notes_to_yaml.py` for Burra,
    `scripts/site_table_to_yaml.py` for Curnamona, `scripts/new_survey.py`
    for a new survey; `Survey.generated_by`, None when absent). When it is
    set, a yellow line (`theme.NOTICE_COLOUR`) reads "survey.yaml is
    generated by <script>: regenerating will overwrite edits made here", and
    Save asks Yes/No first. Both generators keep the key: `write_sites_block`
    keeps everything above `sites:` byte for byte, and
    `site_table_to_yaml.py` rewrites the parsed config with the key in it.
- **Time Series** — the tree's windows are read the first time a site is
  expanded (`load_grid`, one MTH5 open, no samples) in a `ReadThread` under
  `State.archive_lock`, one read at a time; a site expanded while the store's
  worker is loading waits for the lock and fills in when the files are
  closed. The plots: Bx, By, Ex, Ey top to bottom, magnetics blue and
  electrics red, stacked with no gap on one x axis whose tick values are on
  the bottom plot only, vertical grid only; x in seconds since the window's
  start (the UTC start in the axis label), wheel-zoom and drag along x only, hard limits at the
  window's ends, no narrower than 20 samples; y starts at each channel's
  1st–99th percentile (what figure 01 does) and follows whatever is visible
  once zoomed in, back to the clip at the whole window. pyqtgraph's peak
  decimation and clip-to-view keep 7.2 M points a channel smooth; at the
  whole window the picture is the envelope, as MATLAB's `plot` of the same
  samples was — zoom in for the waveform. Units as `scripts/site_qc.py`'s
  figure 01: mV/km, and nT from the scalar part of the filter chain only —
  the magnetic axes say "scalar gain" because the coil's shape response is
  not applied. The four left axes share one fixed width so the four
  ViewBoxes are pixel-identical: pyqtgraph links views by screen pixel.
- **Spectra** — `psd_ladder` on the window: 65536-point Welch at 1000 Hz and
  again at 100 Hz (a 1–3 h window supports those two stages), each drawn over
  the decade its resolution suits (2–500 Hz, 0.2–2 Hz) as `psd_qc.py` draws
  figure 05. The MATLAB Welch tab's layout: two log-log panels on one
  frequency axis, "By-Ex (Zxy)" over "Bx-Ey (Zyx)", By or Bx blue and Ex
  or Ey red, the remote's coil of the same component grey underneath; y is
  "PSD (units²/Hz)" and the legend (bottom left) gives each curve's unit,
  "(nT)²/Hz, scalar gain" or "(mV/km)²/Hz". Faint dashed lines: green at
  the Schumann resonances (7.83, 14.3, 20.8, 27.3, 33.8 Hz), orange at 50 Hz
  and its harmonics up to Nyquist, labelled "Schumann" and "50 Hz +
  harmonics" once, on the top panel. The view is locked to the data: x to
  the drawn frequencies, y to the smallest and largest PSD **at 0.003–400
  Hz** — the band `psd_qc.py` takes its y range from — because the
  anti-alias roll-off above 400 Hz reaches 10⁻¹⁸ and would squash the rest
  into a quarter of the panel; the roll-off runs off the bottom instead.
- **Spectrogram** — `cascade` power levels on the base time grid
  (`levels_to_grid`, `power_db`), four images with a colour bar each, Bx,
  By, Ex, Ey stacked with no gap on one x axis in minutes since the window's
  start, locked to the window (0 to its length) and to the period range; the image is a `PColorMeshItem` because the log-period bins are not
  evenly spaced. Colour scale robust (2–98 %, figure 04's rule), wide, tight
  or full; "relative to median" subtracts each period's median over the
  window. The base window and step (120 s stepped by 30 s: ~240 columns on a
  2 h window) are the spinboxes; Recompute asks the store again.
- **Coherence** — `band_from_levels` over `BANDS_S`, drawn on a grid of two
  aligned columns (the lines of figure 02). Left, the four local pairs in
  this order: "By-Ex (Zxy)", "Bx-Ey (Zyx)", "Bx-By (magnetic)", "Ex-Ey
  (electric)". Right, on the same rows, the remote question that goes with
  each: "rBy-Ex (Zxy, remote)" (`ex`, `r_hy`), "rBx-Ey (Zyx, remote)" (`ey`,
  `r_hx`), then the two coil checks "Bx-rBx" and "By-rBy". Over each pair's
  five band lines a thick white "All frequencies" curve, their mean at each
  time, drawn and thrown away. Each column is one stack (no gaps, tick
  values on the bottom row), x in minutes from 0 to the window's length and
  y from 0 to 1, both locked. With no remote in, the right column is hidden
  and the four local panels fill the tab. **There is no coherogram here any more** (Ben, 2026-09-22):
  the band curves already show coherence against time over the same window,
  so the image only repeated them. Everything is kept on one x range in
  minutes since the window start (`link_x_ranges`, by copy). The cursor is a
  vertical line on *every* panel: click or drag any of them to place it, its
  UTC time is in the label, and "Show in Time Series" goes there.
- **Filter Data** — one of the two tabs that write a config file (the other
  is Metadata, above). It edits the
  selected site's ordered list in `<survey>/filters.yaml` (kinds: `replace`
  from `bbmt.ingest._replace_channels`, `notch` and `cp` from `bbmt.noise`),
  previews the YAML live, and on Save rewrites the file with
  `yaml.safe_dump(sort_keys=False)` — every other site's entry is preserved and
  the site's key is dropped when its list is empty — then reopens the survey so
  the Metadata tab's "filters" column updates. Two things to know: the file's
  *leading* comment block is kept but comments further down are lost to
  `safe_dump`, and because filters are applied **at ingest**, an archive that
  already exists predates the edit — hence the note and the "Delete archive"
  button (disabled while any job is running).
- **Process** — laid out as the MATLAB app's Process Data tab, whose
  arrangement the owner said "makes it feel much more intuitive in how it's
  all set up" (2026-09-23). Every control does what it did before; only the
  order changed (`docs/matlab_app_borrowing.md`, the Processing and Time sync
  tables, says what was borrowed). Top to bottom:
  1. **Station to process** and **Remote reference** (the declared `remote:`
     preselected, stacked archives shown as "(stack)"), and to their right
     the **summary** (`site_map.PairSummary`) in the MATLAB app's colours:
     "Distance to remote: 148.6 km", "Overlap available: 41.3 h (1.72 days)"
     and "Window length: 4.0 h" in cyan-blue, then in green "Recommended
     remote: E08 (148.6 km, 41.3 h)". The kilometres are the map's
     (`bbmt.survey.distance_km`), the hours the window bar's spans (days are
     added from one day up). The recommendation is the station's declared
     `remote:`; a station without one gets the raw site whose recorded span
     overlaps its own longest. **Tie-break rule** (Ben, 2026-09-23): with no
     declared remote, more than one raw site can tie on overlap hours -- for
     E08, nine sites cover its whole archive -- so every candidate within 1 h
     of the longest overlap is treated as tied, and among the tied candidates
     the **nearest** one (`SiteMap.distance_km`) wins; a candidate with no
     declared position sorts last, and a further tie goes to the first by
     name (`site_map.PairSummary.recommendation`, `TIE_HOURS`). That needs
     every raw site's span, read through the window bar's one queue behind
     the pair (a B423 file listing ~1 ms, an archive's `load_grid` ~0.6 s:
     all 59 curnamona sites in about 2 s), and only while the tab is on
     screen, so a hidden Process tab never keeps the tree or the segment
     store waiting for the archive lock. Picking another remote, a stack
     included, does not change the recommendation.
  2. The **window bar**, full width, the app's slide bar: both recorded spans
     on one UTC axis (station green, remote blue), a draggable region for the
     processing window (bounded to the union of the spans, defaulting to
     their overlap), "Window start (UTC)" with the local time under it
     (`Survey.timezone`, e.g. "21:26 ACST") at the bar's left end and "Window
     end (UTC)" at its right end, and centred above the bar the sync status
     between two round lamps of its colour -- green "remote covers the whole
     window (overlap 41.3 h)", amber "remote covers 50 % of the window -
     adjust it", red "no overlap between station and remote", grey with no
     remote or while a span is being read. The region and the fields follow
     each other both ways, and the Time Series tab's "Use visible range as
     processing window" lands in the fields.
  3. **Add to queue**, **Run queue**, **Reset queue** | **Timing check**,
     **Site QC figures**, **Build stack**, **Fetch basemap**. Add to queue
     only queues `process_rr.py` -- it does **not** start the queue ("Queuing
     a job never starts it", under "The one rule" above); Run queue starts
     whatever is waiting, whether the queue was idle or it is starting the
     next job after a Cancel; Reset queue is `JobRunner.reset` (cancel the
     running job, clear the queue and the log), asked first when a job is
     running. `status_label`, beside the buttons, reads "N job(s) queued -
     press Run queue" while jobs wait and the queue is idle. Build stack
     queues `build_stack.py` from the stack builder on the right (its own
     button is gone: one button, not two) and selects the new stack as the
     remote when it finishes. "Site QC figures" runs `site_qc.py` and
     `psd_qc.py --before`, whose PNGs go to `<workspace>/qc` and are named in
     the log, nothing more. **Fetch basemap** queues `scripts/fetch_basemap.py
     <survey.yaml>` (the argv is `site_map.basemap_argv`), the one script here
     that needs internet; see the site map below.
  4. **Aurora options** in three columns: min period, max period and periods
     per decade (from the survey's `processing:` block); notch Hz and the tag
     suffix; the "use declared filters at ingest" switch with a read-only
     line saying what the station declares. Only an option *changed* from
     the survey's default reaches the command line, so a default run reads
     exactly as it always did; the switch off adds `--no-filters` and both
     sites are ingested into `<site>_unfiltered.h5`. Under them, **collapsed
     by default**, "Advanced (aurora estimator)" (`EstimatorOptions`, a
     toggle button over the block): the STFT taper (boxcar, hamming, hann,
     dpss), the overlap %, "pre-whitening (first difference)" on, the min
     windows, and a regression row -- max iterations, redescending
     iterations, r0, u0, tolerance. Every control starts at the value a run
     uses without its flag (`bbmt.process.ESTIMATOR_DEFAULTS`: boxcar, 25 %,
     pre-whitened, 0, 10, 2, 1.5, 2.8, 0.005; tests/process_rr_cli_unit.py
     builds a real aurora config and fails if those stop being the in-use
     values), and by the same rule as the band options only a control moved
     off it becomes a `process_rr.py` flag (`--taper`, `--overlap`,
     `--no-prewhiten`, `--min-windows`, `--max-iterations`,
     `--redescending-iterations`, `--r0`, `--u0`, `--tolerance`), which the
     queue table's Options column shows, e.g. "--taper hann --r0 2.0". Each
     is applied to **every** decimation level after aurora builds the
     config (`process_station(tweaks=...)`); an overlap other than 25 %
     replaces the 75 % the library gives levels whose window lasts over
     600 s.
  5. The **queue table** (`queue_table.py`): #, Station, Remote, Window (UTC
     start to end), Options (the non-default flags, or "defaults") and
     Status, over `state.runner`, so every job from every tab is a row; a job
     that is not a `process_rr` run shows its label under Station and "-"
     elsewhere. Under it **Script output**, the merged log, with Cancel (kill
     the running script, the rest stay queued) and Clear log.

  Beside rows 3-5, top to bottom: the **site map** (never under 340 px tall,
  and stretch 3 against the stack builder's 2), a plain lon/lat scatter
  of every positioned site with the ViewBox aspect locked to cos(mean
  latitude) so a degree of longitude draws that much shorter than a degree of
  latitude -- station green, remote blue, stack members orange, the rest
  grey, each dot with a black outline so it reads on imagery, the names in
  the plot foreground grey -- with one line under it, "remote E08 at 148.6
  km" (haversine). Under the dots, the **basemap** (the owner asked for a
  map background): the GUI stays offline, so `scripts/fetch_basemap.py`
  fetches the tiles once, while online (contextily; OpenTopoMap by default,
  `--provider Esri.WorldImagery` and the like), warps them from Web Mercator
  onto this plain lon/lat grid with numpy, and writes
  `<workspace>/basemap.png` and `basemap.json` (the extent: the sites'
  padded by 15 % of the span, at least 0.1 degree; provider, attribution,
  zoom, fetch time, size). The map draws the PNG as a `pg.ImageItem`
  (row-major, rows flipped so north is up) under the dots, `setRect` over the
  JSON's extent in degrees, with the provider's attribution small in its
  bottom-right corner, and reloads it when a fetch_basemap job finishes;
  without the two files a small grey line reads "no basemap - Fetch basemap
  on the Process tab (needs internet)". Then
  the **stack builder** (name and members; its window is row 2's); and the
  **Products** list: when a run finishes, the `.edi` paths in its output that
  exist are listed, and "Show in View EDIs" ticks that EDI and the station's
  lemimt reference on the View EDIs tab and fronts it. The `comparison
  figure:` line is log text. The tab sits in a scroll area, so a short laptop
  screen scrolls rather than squashing the rows.
  The two recorded spans are read off the GUI thread: `load_grid` measured
  0.66 s for D02 and 0.56 s for E08 on this machine, about 1.2 s for a pair,
  so the reads go through one `ReadThread` at a time under
  `State.archive_lock` exactly as the tree's do, cached per survey, and
  scheduled one event-loop turn late so a window clicked in the tree always
  takes the lock first. A site with no archive gets its span from the B423
  file names instead (`bbmt.ingest.select_files`, ~1 ms).
- **View EDIs** — rebuilt on **mtpy-v2** (Ben, 2026-09-22: "I think we almost
  need to use mtpy-v2 for the edi viewer here so we get decent transfer
  functions plotted properly, though I do like being able to stack various TFs
  over the top of each other"). The tree is unchanged — tick any combination of
  `<workspace>/tf/*.edi` and the lemimt references in
  `<survey>/reference_edis.yaml` — but the picture is now a live matplotlib
  canvas (`FigureCanvasQTAgg` + `NavigationToolbar2QT`, which work with
  PySide6) that mtpy draws: `PlotMTResponse` for one station,
  `PlotMultipleResponses(plot_style="compare")` for an overlay, xy and yx
  (`plot_num=1`) with mtpy's own error bars, xy left and yx right, rho above
  phase. All of the mtpy glue is in `tf_plot.py`, including the one trick that
  makes it embeddable: mtpy builds its figure through `plt.figure(...)` inside
  `plot()`, so for the length of the call `plt.figure` (and `fignum_exists`,
  `close`, `clf`) hand back the tab's own Figure. Nothing is left in pyplot's
  registry; mtpy does write a few `plt.rcParams` as it plots, which is
  harmless while nothing else in the GUI draws with matplotlib. The dark
  faces are `theme.apply`'s rcParams, read when the tab's Figure is made.
  **Quick view** (on, by default) is the rest of the same sentence — "it would
  be really cool to be able to use the keyboard down arrow for a sort of quick
  view to go through them quick": the row under the cursor is drawn on its own
  *plus* whatever is ticked, so a student steps down a survey against a fixed
  reference. A click puts the focus back on the tree, and redraws go through a
  single-shot 150 ms `QTimer`, so holding the arrow down costs one draw and not
  one per row. Switch quick view off and only the ticked rows are drawn.
  The **Plot** radio group is "rho and phase", "plus phase tensor" (mtpy's row
  of ellipses, one per station — the owner's reason for the move: "this would
  enable phase tensors to be plotted as well, and later induction arrows for
  long period data etc") and "plus tipper", which is **disabled** with the
  tooltip "no hz sensor on this survey" while no site of the survey declares an
  hz channel: the aurora EDIs of such a survey still carry a tipper, estimated
  from an open Bz input, and it is nonsense, so it is never drawn by default.
  A two-EDI overlay draws in about 0.2 s on this machine, so the whole thing
  runs in the GUI thread behind a "drawing..." label; `mtpy.MT` objects are
  cached per file (an `mt_metadata` parse is ~0.1 s) and only forgotten when a
  `process_rr` job rewrites `<workspace>/tf`. The references on `E:` are only
  ever read.

## The engine behind the views

- `load_segment` reads the window through the same `Grid`/`run_slices`
  arithmetic the tree used to list it, one channel at a time, into
  `bbmt.timefreq.Record`'s float32 offset-removed convention (7.2 M samples a
  channel, 29 MB each; the display copies are float64 with the offset back,
  58 MB each). `compute_segment_qc` then calls only `bbmt.timefreq`: the
  factor-4 level ladder (`levels_plan` + `cascade`), `band_from_levels` over
  `BANDS_S`, `levels_to_grid` for the images, and `psd_ladder`, the same
  whole-record ladder `scripts/psd_qc.py` imports from the library. The
  `Segment` is never modified: the cascade and the ladder consume copies. For
  2 h of D02 with E08 as remote, offscreen: `segment_loaded` at 2.6 s,
  `qc_ready` at 8.3 s.
- **One worker, one archive at a time.** `SegmentStore.request(...)` does
  nothing when its result already matches, otherwise runs the loads and the
  QC in one `QThread`, keeping only the latest request pending while one is
  in flight and discarding a result that no longer matches. The archive is
  opened only in the worker's load phase, under `State.archive_lock`, which
  the tree's reads also take: a site expanded while the worker is loading
  waits and reads the moment the files are closed, while the maths carries
  on without the lock. Signals: `qc_started(str)`, `segment_loaded(Segment)`,
  `qc_progress(int, str)`, `qc_ready(SegmentQC)`, `qc_failed(str)`,
  `ladder_changed(float, float)`.
