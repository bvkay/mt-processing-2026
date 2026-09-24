# mtproc_gui — the desktop GUI

A launcher and a viewer over the scripts in `scripts/` and the per-survey YAML.
It replaces the MATLAB App Designer app the students know, tab for tab, and
follows that app's own layout: a tree on the left of the Time Series tab
lists every site from the metadata; expanding a site shows a selection of
times from it -- two hour windows for 1000 Hz data, four hour windows for
500 Hz data, and so on; clicking one of those time windows loads that data
in full for the selected window and displays the time series, the spectra,
the spectrogram and the coherence; clicking a different site loads that
site's time window instead.

**No PNG is displayed anywhere in the GUI** (the scripts still write
their report figures -- `site_qc.py`, `psd_qc.py`, `timing_qc.py` from the
command line, `process_rr.py`'s comparison figure from the Process tab; the
log names them and they stay on disk), and the QC tabs are live views of
**one window** picked in a tree.

## Launch

From the repo root, with the `mt-2026` env active (an environment created
earlier as `bbmt-2026` keeps working):

```bash
python -m mtproc_gui surveys/curnamona_cube/survey.yaml
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
python tests/survey_unit.py          # distance_km, Survey.timezone, the channel presets, instrument detection
python tests/ingest_unit.py          # the raw/variant split (filters_hash, build_variant, old-layout), the LEMI-423 path, one real hour of LEMI-424 and EDL
python tests/noise_unit.py           # the filter kinds on synthetic arrays; ingest path == arrays path
python tests/virtual_unit.py         # synthetic remote: the plain stack byte-identical to before; coherence weights (dead coil -> 0, burst chunk down-weighted)
python tests/process_rr_cli_unit.py  # process_rr.py --dry-run, the estimator tweaks, run_stem, the sidecar, the quadrant window
python tests/basemap_unit.py         # fetch_basemap.py: warp, provider, zoom rule; network mocked
python tests/new_survey_unit.py      # new_survey.py on synthetic B423s, a mixed LEMI-423/424/EDL root, Curnamona
python tests/crosspower_unit.py      # chunk impedances on synthetic archives: known Z, scipy.csd, gaps, a burst, streaming; stack_impedance
python tests/masks_unit.py           # masks.yaml round trip (other sites byte-identical); cutting masks out of a KernelDataset
```

## The flow: tree -> window -> every view

1. **Time Series** has a tree on the left of every site in the survey's
   metadata (`State.all_sites()`), bold and collapsed. A site with an MTH5
   archive expands to its **windows**: a constant 7.2 million samples per
   channel, so 2 h at 1000 Hz, 4 h at 500 Hz (`windows.py`), from the record
   start, the last one shorter, any window with under 10 minutes of samples
   inside the runs left out. A site without an archive is greyed with one
   row, "no MTH5 yet - select the site and press Build MTH5": the **Build
   MTH5** button under the tree runs `scripts/ingest_site.py` for it at once
   and the row then lists its windows (see "Time Series" below). A click on
   a site row toggles it; a click on a window row selects it.
2. Selecting a window makes it `State.selection` and asks the one
   `SegmentStore` for it. The store's worker reads the local station
   (`segment.load_segment`) and hands the `Segment` straight out
   (`segment_loaded`, about a second for 2 h of D02); the Time Series tab
   draws it in full on the right — Bx, By, Ex, Ey stacked on one x axis
   at the full rate, physical units, the offset the segment removed added
   back for display, gaps as holes. The worker goes on to read the remote and compute the QC
   (`compute_segment_qc`, `mtproc.timefreq` only), and `qc_ready` follows in
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
an EDI, a transfer function, a report figure — it is computed in `src/mtproc/`
and reached through a script in `scripts/`, which the GUI runs as a subprocess
with the repo root as its working directory. The GUI only:

1. reads `survey.yaml` (through `mtproc.survey.Survey`) to know what exists --
   and writes back only what a person typed into it: the Metadata tab's
   edited cells into the `sites:` block, the Filter Data tab's lists into
   `filters.yaml`,
2. reads MTH5 archives to *draw* them (`archive.py`, `segment.load_segment`,
   read-only),
3. builds a command line, runs it, shows its log.

Stated precisely: NO PRODUCT (archive, transfer function, EDI,
report figure) is computed in the GUI; the QC views may compute on data
already loaded for display, but ONLY by calling functions in
`src/mtproc/timefreq.py` — never with spectral maths written inside
`src/mtproc_gui`. `segment.py` calls `levels_plan`, `cascade`,
`band_from_levels`, `levels_to_grid`, `psd_ladder` and `power_db` on the
selected window and holds no maths of its own; what it produces is drawn
and thrown away. The Filter Data tab's preview is the one other caller:
`filter_preview.py` runs the declared list through
`mtproc.noise.apply_filters_arrays` -- the function ingest itself delegates
to -- and `psd_ladder` on the raw and filtered copies of the loaded window,
draws them, and writes nothing. The only arithmetic in the tabs is a picture's: percentile
colour limits, the row median the Spectrogram's "relative to median" view
subtracts, the mean of a pair's band lines the Coherence tab draws as "All
frequencies", seconds shown as minutes, an axis's clip or extent.

Two consequences worth knowing. Jobs run **one at a time**, because an MTH5
must never be open in two processes (HDF5 locking) — so there is exactly one
`JobRunner` in the window, `state.runner`, and every tab queues on it; the
queue table and the processing log live on the Process tab (`queue_table.py`;
they show processing jobs only, while Build MTH5, the basemap fetch and New
survey are utility jobs that report in the console strip),
where every job from every tab is a row.
And there is **no single-station option** anywhere: every product is
remote-referenced, so the Process tab always wants a remote — an adjacent
site, a dedicated remote, or a stacked synthetic remote from
`scripts/build_stack.py` (shown as "(stack)").

**Queuing a job never starts it**: the MATLAB app kept "add
to Queue" and "Process Queue" as two separate steps, and the students already
know that flow, so every button that queues a processing job — Add to queue
and Build stack, on the Process tab — only calls `JobRunner.add`; only **Run
queue** calls `JobRunner.run_queue`, which then runs every queued job in
turn. A status label beside the buttons reads "N job(s) queued - press Run
queue" whenever jobs are waiting and the queue is idle. (Timing check, Site
QC figures and Fetch basemap were dropped from that row: `timing_qc.py`,
`site_qc.py` and `psd_qc.py` stay in README.md's command table.)

Three jobs are exceptions, each started at once through `JobRunner.run_now`,
which starts **that** job alone: jobs already queued keep waiting for Run
queue, and the queue does not go on to them when it finishes.

1. The Metadata tab's **New survey...** (`metadata_edit.start_new_survey`):
   not a processing job, opens no archive, and the point of moving it onto
   the queue was to stop it blocking the window, not to make a student press
   Run queue for it. It refuses to queue at all (a message box, rather than
   waiting its turn) if another job is already running.
2. The **basemap fetch** on survey open (`site_map.fetch_basemap_if_missing`,
   the one call in `State.open_survey`): when `<workspace>/basemap.json` is
   not there, `scripts/fetch_basemap.py <survey.yaml>` runs at once; it never
   opens an archive. Offline, it fails inside its 30 s tile timeout and the
   console strip shows why; nothing else happens, and the next try is the
   next time a survey is opened (a Save on the Metadata or Filter Data tab
   reopens the survey, so it counts). A fetch for the same survey already
   waiting or running is not queued twice; with another job running, it
   only joins the queue.
3. The Time Series tab's **Build MTH5** (`TimeSeriesTab.build_mth5`): the
   student is waiting to look at that site's data, and it is one ingest, not
   the processing queue. The button is disabled while any job runs, so it
   always starts at once.

## The console strip

A small, always-visible area at the bottom of the GUI that echoes the
command-line terminal, so students can see the python commands and outputs
from the backend as they run when something is clicked. `console.ConsoleStrip` sits under the
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
   a line logged off the GUI thread (`mtproc.timefreq`'s `cascade` and
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
src/mtproc_gui/
    __main__.py        python -m mtproc_gui [survey.yaml]; theme.apply before the window
    theme.py           the look: apply(app) (dark Fusion palette, pyqtgraph and
                       matplotlib greys) and every colour -- B_COLOUR, E_COLOUR,
                       REMOTE_COLOUR, the Schumann and mains marks, the bands
    channels.py        channel names, any recorder's (no Qt): kind, label, order,
                       unit, display, and roles/resolve/title -- who plays Bx By
                       Ex Ey in the MATLAB app's pairs (see "Channel names")
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
                       remote, window and options the queue table shows): add,
                       run_queue, and run_now for the three jobs started at
                       once; the queue table (`queue_table.py`) is its only view
    archive.py         read-only MTH5 reading for the views, nothing else;
                       Grid + load_grid + run_slices are the one copy of the run arithmetic
    windows.py         window_hours / window_list / window_label (no Qt): the
                       windows the tree offers, 7.2 M samples per channel each
    reader.py          ReadThread: one archive read off the GUI thread;
                       ArchiveLock: one archive open at a time across threads
    site_tree.py       SiteTree: the sites, their windows read on first expansion;
                       refresh_site looks at a site's archive again after a build
    segment.py         Segment / load_segment / SegmentQC / compute_segment_qc
                       (no Qt): the segment QC engine, mtproc.timefreq only
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
                       the credit as its tooltip, the view locked to the
                       basemap, a distance line; fetch_basemap_if_missing
                       (State.open_survey's one call); PairSummary: row 1's
                       distance, overlap, window length, recommended remote
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
                       script log) and ProductList (the EDIs and figures the
                       jobs wrote, read off their own "wrote <path>" lines)
    filter_forms.py    one small form per filter kind (notch, hp, lp, cp, replace) and
                       the students' names for them, for the Filter Data tab
    filter_preview.py  the Filter Data tab's preview engine: compute_preview
                       (mtproc.noise.apply_filters_arrays + psd_ladder on the loaded
                       window), one PreviewWorker at a time, latest wins
    filter_views.py    the preview's views: SeriesPreview (raw grey behind
                       filtered), PsdPreview (raw dashed), PreviewPane (Before /
                       After / Both, Show, the status line)
    window_chooser.py  WindowChooser: the Filter Data tab's site and window combos
                       (the tree's windows; choosing one loads it); the loaded
                       window's row is shown bold, in the accent colour and
                       suffixed "(loaded)" in the list
    metadata_edit.py   the Metadata tab's editing: NewSurveyDialog (with the
                       workspace folder and "channels recorded") + start_new_survey
                       (scripts/new_survey.py on state.runner, started at
                       once) and handle_new_survey_finished (opens what it
                       wrote), rewrite_sites_block (only the sites: block),
                       format_cell / parse_cell, ask_yes_no
    channels_column.py the Metadata tab's channels column: cell (the preset's
                       label, greyed when an archive exists), ChannelsDelegate
                       (the presets + "custom..." combo), edit (the save rule)
    tabs/                             (in tab order -- the MATLAB app's:
        metadata.py    MetadataTab     QC first, then filters, processing, EDIs)
        timeseries.py  TimeSeriesTab  the tree + Build MTH5 (ingest_site.py) +
                                      the loaded window at the full rate
        spectra.py     SpectraTab     the window's PSDs: a Zxy and a Zyx panel
        spectrogram.py SpectrogramTab the window's dB images per channel
        coherence.py   CoherenceTab   band lines per pair, two aligned columns
        filters.py     FiltersTab     previews the site's filter list on a loaded
                                      window; drives <survey>/filters.yaml
        process.py     ProcessTab     the MATLAB Process Data tab's rows; drives
                                      process_rr / build_stack
        crosspower.py  CrossPowerTab  one site's chunk impedances (time panel,
                                      polar plane); drives <survey>/masks.yaml
        edis.py        EdiTab         mtpy-v2 draws <workspace>/tf/*.edi +
                                      reference_edis.yaml on one live canvas
```

`State` is shared by every tab and emits `survey_changed`, `site_changed`,
`selection_changed`, `remote_changed`, `goto_time` and `archive_changed` (a
site's archive built on the Time Series tab or deleted on the Filter Data
tab: the tree's row and the Filter Data chooser look again); `MainWindow.reload_tabs()`
calls each tab's `reload()` when a survey is opened, so a tab never has to
know about any other tab. `State.request_qc()` is the one place the store is
asked for the selection with the current remote and ladder.

## The look — `theme.py`

The look follows the MATLAB App Designer app: the time series plots share an
axis, magnetics as the first two subplots coloured blue, electrics as the
last two subplots coloured red, the vertical grid kept, the spectra locked
in so they cannot be zoomed out further, faint dashed vertical lines
highlighting the Schumann bands, the axis tight with no gaps, everything
blending into each other, and names like "Zxy (By-Ex)".
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
  pick one by the channel's kind, `label(comp)` for the MATLAB names (Bx,
  By, Ex, Ey, E1, rBx -- `channels.label`); the Spectra marks (Schumann green, mains
  orange, both faint and dashed); the Coherence band colours, the white
  "All frequencies" curve and the amber cursor; the Process tab's traffic
  light and site roles (`OK_COLOUR` green, `WARN_COLOUR` amber, `BAD_COLOUR`
  red, `IDLE_COLOUR` grey, `PAIR_REMOTE_COLOUR` blue) and its cyan-blue
  summary text (`SUMMARY_COLOUR`). A tab never writes a hex colour of its
  own.
- **Stacks share one x axis.** Magnetics first, then electrics, each in
  name order (`theme.channel_order`: hx hy ex ey; bx by bz e1 e2 e3 e4). Panels of a stack sit with no gap between them, and only the
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

## Channel names (any recorder) -- `channels.py`

An archive keeps its reader's names (README.md, "Instruments"): hx hy hz ex ey
for a LEMI-423 or an Earth Data PR6-24 (EDL), bx by bz e1 e2 e3 e4 for a
LEMI-424. The GUI never assumes a fixed set; every view goes through one rule:

- **Kind**: a name starting with e is electric (red), with b or h magnetic
  (blue); a remote's `r_` prefix is ignored (grey); anything else -- a
  LEMI-424 temperature -- is neither and is not drawn.
- **Label**: Bx By Bz Ex Ey for the LEMI-423/EDL names, Bx By Bz E1..E4 for
  the LEMI-424 ones, the reader's name otherwise; "r" in front for a remote.
- **Order**: magnetics first, then electrics, each in name order.
- **What is drawn**: the station's declared `channels:` (its own or the
  survey's) that the archive holds -- so D02's dead hz, still in its old
  archive, stays hidden -- or every electric and magnetic channel when the
  declaration names none of them (`channels.display`, the segment store).
  The remote's two horizontal coils are hx hy or bx by, whichever it has.
- **Pairs**: the first two magnetics in name order play Bx and By, the first
  two electrics Ex and Ey (`channels.roles`). The pair lists stay written in
  the LEMI-423 names (`mtproc.timefreq.LOCAL_PAIRS`, the Spectra `PANELS`,
  the Coherence `ROWS`) and are resolved per window, so a LEMI-423 or EDL
  window gets exactly the old panels and a LEMI-424 one "By-E1 (Zxy)",
  "Bx-E2 (Zyx)", "E1-E2 (electric)": E1 and E2 stand in for Ex and Ey until
  the electric-pair setting (aurora's LEMI12/LEMI34) exists. The panels stay
  keyed by the LEMI-423 names; their titles follow the window.
- **Windows** stay rate-based (`windows.window_hours`, 7.2 M samples clipped
  to 0.5-24 h): a 10 Hz EDL site and a 1 Hz LEMI-424 get 24 h windows
  (864,000 and 86,400 samples). A window too short for the QC's default
  segment lengths -- one hour at 1 Hz -- gets them halved until the ladder
  fits (`segment._plan`, `_psd_nperseg`); a 1000 Hz window never does.
- The **Metadata** tab shows the site's recorder in a read-only
  "instrument" column after "site" (`Survey.instrument_of`), and its
  channels column offers that recorder's presets. The **Filter Data** forms'
  channel boxes, the cp reference and the preview's "Show" boxes follow the
  site's channels; `replace` stays a LEMI-423 filter (ingest refuses it for
  another recorder).

## Adding a tab

1. Write `src/mtproc_gui/tabs/<name>.py` with one `QWidget` subclass that takes
   `state` as its first constructor argument and has a `reload()` rebuilding
   itself from `state.survey`. Say in the class docstring which script, YAML
   file or store signal the tab drives or draws.
2. In `app.py`, import it inside `MainWindow.__init__`, construct it and
   `self.tabs.addTab(...)`. Add it to the loop in `reload_tabs`.
3. If it runs anything long, queue it on `state.runner` (never make a second
   `JobRunner`) — do not import `mtproc` and compute in the GUI. If it draws the
   selected window, connect to `state.segment_store.qc_ready` (or
   `segment_loaded`) and take the numbers from the `SegmentQC`.
4. Add it to `tests/gui_smoke.py`'s criteria and screenshot loop.

Hand-written layouts only (`QGridLayout`, `QVBoxLayout`, `QSplitter`) — no
`.ui` files, no Designer. Plain signals and slots. Keep each file under about
350 lines; if a tab outgrows that, the extra probably belongs in a script.
(The tests are exempt: `tests/gui_smoke.py` is one linear script on purpose,
so its criteria can be read top to bottom.)

## Notes for the tabs

- **Metadata** — "instrument", right after "site", is the site's recorder,
  read-only (`Survey.instrument_of`: its own `instrument:`, else what its
  folder holds, else the survey's). The table's numbers are what the YAML
  declares (a site with no value of its own shows the survey's `defaults:`); serial, firmware, start
  and end, right after remote, are the recorder facts `scripts/new_survey.py`
  read from the B423 headers and file names, read-only; "raw folder" and
  "archive" say what is actually on disk right now; "filters" is whether the
  site has a declared noise filter list in `<survey>/filters.yaml`. Click a
  header to sort. Selecting a row sets `State.site`, which the tree highlights.
  - **channels** (right after remote, `channels_column.py`): which of the
    recorder's columns had a sensor attached -- a per-survey logistics
    decision (a LEMI-423 site normally has Ex Ey Bx By
    with the Bz column an open input, some deployments carry a Bz sensor, a
    dedicated remote may be magnetics only); the reader says what columns a
    file carries, the survey only which of them had a sensor. The cell shows
    the site's effective set (its own `channels:` or the `defaults:` one) as
    the preset's label from `mtproc.survey.CHANNEL_PRESETS` -- for the
    LEMI-423 "Ex Ey Bx By" (the default), "Ex Ey Bx By Bz", "Bx By
    (magnetics only)", "Bx By Bz" -- or the list itself ("hx, hy, tx") when
    it is no preset; the match ignores order and case. Double-click or F2
    opens a combo of the survey instrument's presets plus "custom...", which
    asks for a comma list in the reader's names (a list that is a preset's
    set comes back as its label). Save writes the site's `channels:` only
    when its set differs from the survey default and removes the key when it
    is the default's again, by the same only-changed-cells rule as every
    other column. Ingest applies the set (`mtproc.ingest._keep_channels`)
    and `process_rr.py` asks aurora only for the declared outputs, so on a
    site whose archive exists the cell is drawn in the disabled grey with the
    tooltip "archive built with the old set - Delete archive then Build MTH5
    to change it"; it stays editable, since the declaration can be corrected
    first and the archive rebuilt after (the Filter Data tab's archive note
    works the same way).
  - **electric_gain** (right after channels, `metadata_edit.electric_gain_cell`):
    an Earth Data PR6-24 site's declared extra gain of the electric chain
    between the dipoles and the recorded values, beyond what the reader
    already models (the x10 terminal box). Hardwired at the field terminal
    junction box; for a survey whose PR6-24 configs were not kept, known only
    from the field notes -- Stuart Shelf 2009 trip 2 declares 10.0 so, not a
    PR6-24 pre-amplifier setting. An EDL
    row shows the site's effective number (default 1.0, no filter) and is
    typed over; any other recorder's row reads "-", read-only. Save writes
    the site's `electric_gain:` only when the number differs from the survey
    default's and drops the key when it is the default's again, like channels
    (`metadata_edit.electric_gain_edit`); text that is not a number is
    refused on the status line. Ingest adds a `uoa_electric_gain` filter of
    that gain to ex and ey's chain (`mtproc.instruments.read_run`), so an
    archived site's cell is greyed with "archive built with the old gain -
    Delete archive then Build MTH5 to change it".
  - **A new survey** (a student with a new
    survey has only a folder of site folders and paper field notes, no
    survey.yaml). **New survey...** opens a dialog -- data folder (Browse...),
    workspace folder (Browse...; `<data folder>/work` until typed over or
    browsed to), survey name (the folder's name until typed over), instrument
    (lemi423) and, on the same row, "channels recorded" (the instrument's
    presets, "Ex Ey Bx By" preselected; passed as `--channels` and written as
    `defaults: channels:`), time zone (Australia/Adelaide), an optional site table --
    which shows where it writes (`surveys/<name>/survey.yaml`) and, on OK,
    closes and queues `scripts/new_survey.py` on `state.runner`, starting it
    at once (`metadata_edit.start_new_survey`, `JobRunner.run_now`): one of
    the three jobs exempt from "queuing a job never starts it" above, since
    it is not a processing job and never opens an archive. The **workspace**
    (archives, TFs, figures, the basemap) goes beside the raw data by default,
    not under `surveys/<name>/work` in the repo, because a 100-site survey's
    archives run to hundreds of GB; the script writes it as `workspace:`
    (`--workspace`, default `<data_root>/work`) and makes no folder itself.
    The two existing surveys keep their own. The window stays responsive while it runs;
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
    F2), and channels through its combo (above); a line beside the buttons
    counts the unsaved changes. **Save
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
    same reader (`mtproc.survey.read_site_table`) serves
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
  **Build MTH5**, under the tree, replaces the old "no archive - ingest from
  the Process tab" row, which was counter-intuitive: it shows when no
  archive is detected and greys out when one is. Enabled only while the
  tree's current row is
  a site (or a row under one) with a raw folder and no archive, and no job
  runs -- otherwise disabled with the reason as its tooltip ("archive
  exists", "a job is running - wait for it to finish", ...). Pressed, it runs
  `scripts/ingest_site.py <survey.yaml> <site>` at once (`JobRunner.run_now`,
  exception 3 under "The one rule"), the hint reads "building <site>.h5 ..."
  and the console strip carries the script's log. The script is the ingest
  `process_rr.py` does -- `mtproc.ingest.ingest_site` with process_rr.py's
  MAX_RUN_FILES and archive naming, the whole deployment -- so the archive
  is the one a later run reuses. When a job whose argv names ingest_site.py
  succeeds, `SiteTree.refresh_site` looks at that site's archive again: the
  placeholder goes, the row turns expandable and opens, and its windows are
  read as on any first expansion. A failed build says so in the hint; the
  script removes the partial archive it was writing.
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
  and the four local panels fill the tab. **There is no coherogram here**:
  the band curves already show coherence against time over the same window,
  so the image only repeated them. Everything is kept on one x range in
  minutes since the window start (`link_x_ranges`, by copy). The cursor is a
  vertical line on *every* panel: click or drag any of them to place it, its
  UTC time is in the label, and "Show in Time Series" goes there.
- **Filter Data** — where a student may spend most of their time on a noisy
  dataset: it shows the filter list's effect on a loaded window, the cleaned
  time series and the filtered PSD, before anything is declared. One
  of the two tabs that write a config file (the other is Metadata, above).
  Top to bottom:
  1. **The window.** A site combo (every site with an archive) and a window
     combo listing that site's windows exactly as the Time Series tree does
     (`window_chooser.py`: `window_list` over `load_grid`, read under
     `State.archive_lock` in a `ReadThread`, "reading the archive..." meanwhile,
     and only while the tab is on screen, so a click in the tree always gets
     the lock first). Choosing a window *is* loading it -- `State.set_selection`,
     the tree's own call -- so the Time Series and QC tabs follow, and the
     combos follow `selection_changed` so they always show what is loaded. The
     bold label beside them names the loaded window, or says "load a window
     (above, or on the Time Series tab) to preview the filters", or that the
     loaded window is another site's, or that the site has no archive yet.
  2. **The list** (left) of the site's filters, applied in this order: Add
     (a menu in the students' words: "50 Hz + harmonics", "high-pass",
     "low-pass", "cathodic protection stack", "replace magnetics from another
     site" -- `filter_forms.LABELS`), Remove, Move up, Move down, the rule box
     under them; the selected entry's **form** (middle; each titled in the
     same words, channels as Bx By Ex Ey check boxes on notch, hp, lp and cp,
     the high-pass form saying live which periods it removes); and (right) the
     site's entry as it will be written (collapsible), **Save filters.yaml**,
     and the archive note with **Delete archive**.
  3. **The preview**, in a vertical splitter under the controls: "Time series:
     Before / After / Both / Removed" (Removed = raw minus filtered, what the filters took out; the y axis follows the trace being read, so a large removed component runs off the panel rather than setting the scale), "Show: Bx By Ex Ey" (both views), a status line,
     then Bx, By, Ex, Ey stacked on one x axis -- the raw in light grey
     (`theme.RAW_COLOUR`) behind the filtered in the channel colour, peak
     decimation, zoom locked to the window as on the Time Series tab, values
     offset-removed -- and under them the Spectra tab's two pair panels
     ("By-Ex (Zxy)", "Bx-Ey (Zyx)"), raw dashed light grey under filtered, the
     Schumann and mains lines, locked zoom (`qc_plots.draw_psd(..., before=)`).
     With no filters the raw alone is drawn, in the channel colours.
  The preview runs whenever the list or a form value changes, debounced 500 ms
  (`DEBOUNCE_MS`), and when a window is loaded while the tab is on screen:
  `filter_preview.FilterPreview` gives one `PreviewWorker` (a QThread) a
  reference to the loaded `Segment` -- never modified -- and the list; the
  worker reads any `replace` donor's window over the same span
  (`load_segment`, under the archive lock; a donor with no archive, or one not
  covering the window, becomes a status line instead), runs
  `mtproc.noise.apply_filters_arrays` (four threads: scipy's filters release the
  GIL) and `psd_ladder` on the filtered channels (the raw ladder once per
  window, cached). One worker at a time, the latest request wins, a stale
  result is dropped. The status line reads "previewing... (notch, cp)", then
  the provenance lines the archive would carry and the seconds it took --
  about 2.9 s for notch + cp on a 2 h window of D02 at 1000 Hz, 1.2 s for the
  raw ladder once. Save rewrites the file with `yaml.safe_dump(sort_keys=False)`
  -- every other site's entry is preserved and the site's key is dropped when
  its list is empty -- then reopens the survey (the Metadata tab's "filters"
  column updates) and reloads the window that was loaded. The file's *leading*
  comment block is kept but comments further down are lost to `safe_dump`.
  `<workspace>/mth5/<site>.h5` is always the RAW recording -- filters are
  never baked into it, so this tab's edits never touch it and never make it
  stale. A site's
  declared list is applied to a **filtered variant**,
  `<site>_f<hash>.h5` (`mtproc.ingest.processing_archive`/`build_variant`,
  `hash` a sha1 of the declared list), built on demand the next time
  something processes with filters on and rebuilt whenever the saved list's
  hash changes. The note (`ARCHIVE_NOTE`) reads "filtered archive for this
  list: ready" or "... not built yet (built when processing starts)" for the
  site's *saved* declaration (`variant_ready`; an edit not yet saved does not
  move it) when it is non-empty, empty otherwise; Delete archive (shown only
  when a `<site>_f*.h5` file exists) deletes that variant alone -- never the
  raw archive -- asks first, is disabled while any job runs, and emits
  `State.archive_changed` (the tree and chooser look again, though the raw
  archive they show is untouched). The preview is the same filter on the
  same samples a variant build would apply, with two differences worth
  knowing: a variant filters a whole run (up to 51 h) where the preview
  filters 2 h, so edge transients differ near the window's ends, and a
  variant works on the raw archive's counts where the preview works on the
  calibrated, offset-removed window (the same thing for these linear filters
  and for the cp median, up to the scale; for burst too, whose detection is a
  ratio and whose fill is the channel's own local level, not zero -- zero
  would dig a hole the depth of the electrode offset into the raw counts,
  429 mV/km on C23's Ex -- though its 1 s blocks fall differently from a
  run's start than from a window's, so a burst right at the threshold can
  come and go).

  **burst and flip**. Both have forms (`BurstForm`,
  `FlipForm` in `filter_forms.make_forms`), list rows ("burst removal (short
  transients): 12 x MAD on Ex Ey, over 0.05 s, pad 0.1 s, fills Bx By Ex
  Ey", "flip polarity: Ey"), and load, preview and save through
  `filters.yaml` like the others, and the Add menu offers them (`ADD_ORDER`
  in `tabs/filters.py`: notch, hp, lp, cp, burst, flip, replace). `flip: {channels: [ey]}` multiplies each
  listed channel by -1 (a channel wired reversed; Morocco D12's yx phase is
  180 degrees from lemimt's with the resistivity matching); it has no
  default channel and the form starts with none ticked. `burst: {threshold:
  12, min_len_s: 0.05, pad_s: 0.1, taper_s: 0.05, reference: [ex, ey],
  channels: [ex, ey, hx, hy]}` (`mtproc.noise.detect_bursts` then
  `fill_spans`): on each reference, |x - its local level (1 s block
  medians joined by straight lines)| averaged over min_len_s, over the
  running 60 s MAD; where any reference exceeds the threshold for longer
  than min_len_s (a lone spike or sferic never does), widened by pad_s,
  every listed channel is set to its local level with a taper_s cosine
  taper inside both ends; nothing outside the spans changes by a bit.
  Worked example, **Morocco C23** (LEMI-423, 1000 Hz), 2 h from 2023-09-22
  11:02:36 UTC with C23's declared notch (50 Hz, 9 harmonics, q 25, 2
  passes). The flagged bursts at 549.5, 607.4, 1319.8 and 1365.1 s are not
  in the raw record: they are the zero-phase notch's two-sided ringing
  (about +-0.6 s, 200-400 mV/km on Ex, 0.2-0.4 nT on By) at abrupt steps of
  the 50 Hz amplitude -- raw Ex goes from 180 to 430 mV/km peak within a cycle
  at 549.5 s and back at 607.4 s, a load switched on for about 58 s every
  13 min or so (549/607, 1319/1377, 2096/2155, 2854/2913, 3626/3683,
  4408/4466, 5189 s), with smaller steps between (1365.1 s is one: its
  ringing peaks at 55 mV/km on Ex). So **burst goes after the notch**;
  before it the 50 Hz sets the MAD and it finds nothing (0 spans at 8).
  After it (spans classed here
  by length and by how much of their energy sits in 5 samples):

  | threshold | spans | masked | the four | notch ringing | spike-like (sferics) | noisier stretches (>= 2 s) |
  |---|---|---|---|---|---|---|
  | 5  | 158 | 146 s, 2.0 % | all | 130 spans, 92 s | 24, 8 s | 4, 46 s |
  | 8  |  94 | 111 s, 1.5 % | all |  84 spans, 67 s |  6, 2 s | 4, 42 s |
  | 12 |  99 |  75 s, 1.0 % | all |  96 spans, 67 s |  0      | 3, 9 s  |

  12 is the default: it catches the four and the same 67 s of ringing as
  8, and leaves the sferic-like spikes (probably sferics, which are
  signal: their Ex/By is about 180 (mV/km)/nT, a plane wave's) and most of the
  noisier stretches after a load switches on (the 60 s MAD takes up to
  30 s to catch up with a raised background) alone. Within 0.7 s outside
  the four spans the largest excursion left on Ex is 4-9 mV/km (ringing
  tails and spikes; the MAD there is 0.2-0.4 mV/km), 32 mV/km at 607.4 s
  (a separate spike a second later). Detection
  takes 0.7 s on two references of 7.2 M samples, the whole filter 0.8 s
  on the preview's four threads (0.9 s on one). The cause is a notch
  that cannot follow a stepping 50 Hz; a mains subtraction fitted block by
  block would remove it without masking, if 1 % of a window ever matters.

  **mains**, the second way to remove the mains, for
  sites like C23 whose 50 Hz amplitude steps (the Atlas Mountains data).
  It has a form (`MainsForm`), a list row ("mains subtraction (fitted,
  follows steps): 50 Hz x9, 1 s blocks, steps over 0.3 of the level") and
  loads, previews and saves like the others; the Add menu offers it right
  after the notch (`ADD_ORDER`: notch, mains, hp, lp, cp, burst, flip,
  replace). `mains: {f0: 50, harmonics: 9, block_s: 1.0, step_fraction:
  0.3, channels: [ex, ey, hx, hy]}` (`mtproc.noise.mains_subtract`)
  subtracts a model of the mains instead of filtering: the grid phase is
  tracked from 1 s demodulations at f0, the fundamental's 0.1 s amplitude
  is watched for steps (a change over step_fraction of the level and over
  30 times the amplitude's own 0.1 s jitter, to a level that holds from
  one that held), each step is placed to the sample, and between steps the
  harmonics are fitted per block_s block with their coefficients joined
  by straight lines -- never across a step, so the model jumps where the
  mains jumped and nothing rings. It takes about +-1/block_s Hz around
  each harmonic (the form says so and updates with the block). Its
  provenance line counts the steps in all and per channel, e.g. "mains: f0
  50 Hz x9 harmonics fitted per 1 s block, tracked offset mean +0.003 Hz,
  98 amplitude steps followed in all (hx 0, hy 8, ex 71, ey 19) on
  ['hx', 'hy', 'ex', 'ey']" on C23's 2 h window, previewed in 5.7 s on
  the four threads (the notch 2.9 s; 3.8 s a channel on one thread). On
  that window's Ex the notch (q 25, 2 passes) rang to 406 mV/km over
  +-0.4 s at 549.5 s; after the subtraction what is left is the
  switching's own transient in the raw record (150 mV/km for a few
  samples, a 0.1 s wiggle of about 20), and 8 mV/km beyond 0.2 s of the
  step. The trade: the notch takes 50 Hz 54 dB and 250-450 Hz about 90 dB
  below the floor; the subtraction leaves 50 Hz 3 dB and 250-350 Hz 7-12
  dB above it (the harmonics wander within a second; `block_s: 0.25`
  takes those 10-12 dB below, and takes +-4 Hz). Between the lines the
  subtraction also removes the steps' sidebands, which the notch keeps:
  Ex's 20-45 and 55-95 Hz come out 7.8 dB below raw, where the notch
  leaves them 0.3 dB below (on Ey's first 540 s, before any step, the
  subtraction is within 0.005 dB of raw from 1 to 145 Hz). Without the
  jitter test a channel whose mains is near the noise is all "steps":
  Curnamona D02 (50 Hz 8 dB above the floor) gave about 14 500 a channel
  in 2 h and the preview after a notch took 43 s; with it, 0 to 3 on the
  raw window (1 to 19 after the notch, bursts in the noise). The
  notch form now says how long it rings: "rings about +-0.73 s per pass at a step in
  the mains amplitude" at q 25 (4.6 q / (pi f0): 1 % of the impulse
  response).

  **Copy to sites...**, for a survey where many sites
  share one declaration -- Morocco Atlas's 103 sites,
  most wanting the same notch plus the same interharmonic extra lines --
  rather than retyping it per site and inviting typos. The button
  (`copy_filters.CopyFiltersDialog`), in the list's button row, is enabled
  only when the current site's list is non-empty; its dialog shows a title
  line naming the site, its filter count and their short (kind-only)
  labels, a checkable list of every other site in the survey (not only the
  archived ones), each row a check box beside that site's own current
  declaration in grey ("none", or its own short labels), Select all/Clear,
  a Replace (default)/Append radio pair, and OK/Cancel -- the student still
  ticks every site copied to, nothing is applied automatically, and OK with
  nothing ticked does nothing. It writes through the same path as Save
  (`tabs/filters._write_filters`, factored to take several sites in one
  rewrite), Replace setting each ticked site's list to the source's, Append
  adding it after that site's own; the current site's own list and preview
  are left exactly as they were (the reopen a write triggers re-reads every
  site from the file, so this site's still-unsaved edits are kept aside and
  put straight back rather than lost), and one loguru line, "copied
  <site>'s filters to N sites: A, B, C", shows in the console strip. The
  archive note only asks whether the tab's *current* site has an archive,
  never when its `filters.yaml` entry last changed, so a copied site gets
  the same note the next time it is shown on this tab -- nothing extra was
  needed there.
- **Process** — laid out as the MATLAB app's Process Data tab. Every
  control does what it did before; only the
  order changed (`docs/matlab_app_borrowing.md`, the Processing and Time sync
  tables, says what was borrowed). Top to bottom:
  1. **Station to process** and **Remote reference** (the declared `remote:`
     preselected, stacked archives shown as "(stack)"), and to their right
     the **summary** (`site_map.PairSummary`) in the MATLAB app's colours:
     "Distance to remote: 148.6 km", "Overlap available: 41.3 h (1.72 days)"
     and "Window length: 4.0 h" in cyan-blue, then in green "Recommended
     remote: E08 (148.6 km, 41.3 h)". The kilometres are the map's
     (`mtproc.survey.distance_km`), the hours the window bar's spans (days are
     added from one day up). The recommendation is the station's declared
     `remote:`; a station without one gets the raw site whose recorded span
     overlaps its own longest. **Recommendation rule**: with no declared remote, the
     **nearest** raw site (`SiteMap.distance_km`; no position sorts last, then
     by name) among those whose overlap covers at least half of the station's
     own record is recommended; only when no site reaches that does the longest
     overlap decide, nearest among those within 1 h of it. Distance comes first
     because a remote must share coherent natural signal at the periods being
     processed: on Morocco line D the dedicated remote 450 km away gave a poor
     broadband result while the adjacent site reproduced lemimt's
     (`site_map.PairSummary.recommendation`, `ENOUGH_FRACTION`, `TIE_HOURS`). That needs
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
  3. **Add to queue**, **Run queue**, **Reset queue** | **Build stack**.
     Add to queue only queues `process_rr.py` -- it does **not** start the queue ("Queuing
     a job never starts it", under "The one rule" above); Run queue starts
     whatever is waiting, whether the queue was idle or it is starting the
     next job after a Cancel; Reset queue is `JobRunner.reset` (cancel the
     running job, clear the queue and the log), asked first when a job is
     running. `status_label`, beside the buttons, reads "N job(s) queued -
     press Run queue" while jobs wait and the queue is idle. Build stack
     queues `build_stack.py` from the stack builder on the right (its own
     button is gone: one button, not two) and selects the new stack as the
     remote when it finishes. Timing check, Site QC figures and Fetch basemap
     are gone: the first two are command-line
     scripts, and the basemap is fetched when a survey is opened.
  4. **Aurora options** in three columns: min period, max period and periods
     per decade (from the survey's `processing:` block); notch Hz and the tag
     suffix; the "use declared filters" switch with a read-only line
     (`RunOptions.describe_filters`) saying what the station and the remote
     declare, and, for a site that declares some, whether its filtered
     variant is ready or "will be built first, from the raw archive"
     (`mtproc.ingest.variant_ready`). Only an option *changed* from the
     survey's default reaches the command line, so a default run reads
     exactly as it always did; the switch off adds `--no-filters` and both
     sites are processed from their raw `<site>.h5` outright. Under them, **collapsed
     by default**, "Advanced (aurora estimator)" (`EstimatorOptions`, a
     toggle button over the block): the STFT taper (boxcar, hamming, hann,
     dpss), the overlap %, "pre-whitening (first difference)" on, the min
     windows, and a regression row -- max iterations, redescending
     iterations, r0, u0, tolerance. Every control starts at the value a run
     uses without its flag (`mtproc.process.ESTIMATOR_DEFAULTS`: hann, 25 %,
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
  the plot foreground grey on a translucent dark box (`theme.SURFACE` at
  `SITE_LABEL_ALPHA`, drawn under the dots so a name never hides a site) --
  with one line under it, "remote E08 at 148.6 km" (haversine). Under the
  dots, the **basemap**, fetched automatically with no town names shown:
  the GUI itself stays offline, so `scripts/fetch_basemap.py` fetches the
  tiles once, while online -- run automatically when a survey is opened
  with no `<workspace>/basemap.json` (exception 2 under "The one rule") --
  from Esri.WorldImagery by default (satellite imagery with no place names:
  Esri serves the labels as a separate layer, which is not fetched;
  `--provider Esri.WorldShadedRelief`, `CartoDB.PositronNoLabels`,
  `OpenTopoMap` and the like on the command line), at contextily's zoom
  plus three, coarsened until the image's longer side is at most 8000 px
  (Curnamona: zoom 9, 945 x 1806 px; Morocco: zoom 8, 1588 x 689 px, where
  zoom 9 would be 3176 px wide). It warps them from Web Mercator onto this
  plain lon/lat grid with numpy, and writes `<workspace>/basemap.png` and
  `basemap.json` (the extent: the sites' padded by 15 % of the span, at
  least 0.1 degree; provider, attribution, zoom, fetch time, size). The map
  draws the PNG as a `pg.ImageItem` (row-major, rows flipped so north is up)
  under the dots, `setRect` over the JSON's extent in degrees, and reloads
  it when a fetch_basemap job finishes. The credit the tile providers' terms
  require is the map's **tooltip**, "Basemap: <provider> - <attribution>"
  from basemap.json, not a visible line under the map -- the small grey line
  under the plot
  shows only without the two files: "no basemap: fetched on survey open when
  online (see the console strip)". The view is **locked** to the basemap
  (`SiteMap.lock_extent`): the ViewBox's limits are the
  JSON's lon/lat extent with maximum ranges its width and height, so a
  student can zoom in freely but never zoom or pan out past the imagery; the
  aspect lock stays, so when the plot's shape differs from the basemap's the
  view shows the largest part of it that fits (the whole basemap in one
  direction). Without a basemap the limits are the sites' extent padded as
  `fetch_basemap.py` pads it (15 % a side, at least 0.1 degree). To
  refetch (another provider, say), delete `basemap.json` and reopen the
  survey, or run the script by hand. Then
  the **stack builder** (name and members; its window is row 2's); and the
  **Products** list: when a run finishes, the EDI and figure paths its
  output reports writing (a "wrote &lt;path&gt;" line -- `process_rr.py`
  logs one each for the EDI, the comparison figure and the sidecar JSON in
  turn, read back by `queue_table.WROTE_RE`, `.json` deliberately excluded)
  that exist are listed, and "Show in View EDIs" ticks the chosen EDI and
  the station's lemimt reference on the View EDIs tab and fronts it. Reading
  the actual output line rather than predicting a name from the argv is what
  lets this stay agnostic to `run_stem`'s naming (below): the EDI and figure
  share a stem built from the local time the run started, not from the argv
  alone. The `comparison figure:` line is log text, same as before. The tab
  sits in a scroll area, so a short laptop screen scrolls rather than
  squashing the rows.
  The two recorded spans are read off the GUI thread: `load_grid` measured
  0.66 s for D02 and 0.56 s for E08 on this machine, about 1.2 s for a pair,
  so the reads go through one `ReadThread` at a time under
  `State.archive_lock` exactly as the tree's do, cached per survey, and
  scheduled one event-loop turn late so a window clicked in the tree always
  takes the lock first. A site with no archive gets its span from the B423
  file names instead (`mtproc.ingest.select_files`, ~1 ms).
- **Cross-powers**, a cross-power editor and viewer for the processed data,
  one site at a time, masking certain time windows and polar coordinates,
  working on all the windows at once. Top row: Site
  (archived sites), Remote (archived sites whose recorded span meets the
  site's, read by a `WindowBar` that is never shown, exactly as the Process
  tab reads them; preset to the declared `remote:`, else `PairSummary`'s rule
  over the archived raw sites -- the rule ignores the window, so for Morocco
  C10 it presets C09, which starts a day after C10's first windows), Window
  (**whole overlap** by default -- `window_bar.overlap` of the two recorded
  spans, the Process tab's own default window; then the Process tab's
  processing window while one is set there for this site; then the site's
  2 h QC windows, the tree's loaded one followed while a QC window is the
  choice), Band
  (every band of the survey's lemimt scheme by period, "longer than a chunk"
  on the levels whose 128-point window does not fit a chunk four times),
  Chunk (1, 2, 5 or 10 min, 10 by default) and Compute: `mtproc.crosspower.
  chunk_impedances` in a `ReadThread` under `State.archive_lock`, 4 threads,
  on the archives processing reads -- the filtered variant when
  `mtproc.ingest.variant_ready` says it is built, else the raw archive with
  "raw archive (filtered variant not built)" on the status line
  (`processing_source`; never `State.processing_archive`, which builds a
  missing variant: a view writes no product). Per chunk and band: Z = <E R*>
  <H R*>^-1 from Hann STFTs of the band's level (50 % overlap, every window
  in the chunk, calibrated by the filter chain aurora removes), the
  coherence of E with the E that Z predicts, the STFT window count and the
  chunk's |H| and |E|; the archive is streamed chunk by chunk (a chunk plus
  64 s either side is all that is held). Views: the time panel -- log10 |Z|,
  phase, coherence, log10 |H| and |E| against chunk start, xy blue and yx
  red as mtpy draws them -- and the polar plane (log10 |Z|, phase) for xy over
  yx; the time axis is UTC dates (hours, or days over a record of days);
  past 300 chunks the spots shrink; a masked chunk is drawn hollow, a
  selected one ringed in amber. A
  left-drag on any panel draws a rubber band (`SelectBox`) and selects the
  chunks inside it; "Mask selected" adds one mask per run of consecutive
  chunks (`bands: all` from the time panel with "all bands" ticked, the
  band's [pmin, pmax] from the polar plane), "Unmask selected" cuts the
  selected chunks out of the masks that apply to the band, the list's reason
  cell is editable, Remove drops rows and Save masks writes
  `<survey>/masks.yaml` (`mtproc.masks.save_masks`: only this site's block
  changes). **What processing does with it** (the status line says it:
  "all-band masks: time cuts; band masks: their windows dropped in those bands (aurora patch)"): `scripts/process_rr.py` loads the site's masks and
  `mtproc.process.process_station` cuts the `bands: all` ones out of the
  kernel dataset's run intervals (`apply_time_masks`, pieces under 10 min
  dropped). A band-limited mask also reaches aurora: on aurora 0.6.2+mtproc
  (`mtproc.process.AURORA_WINDOW_MASKS`) it is set directly on
  `DecimationLevel.window_masks`, the fork's own field
  (`mtproc.process._set_window_masks`); on stock aurora, which takes no
  per-band window weights (docs/upstream_issues.md 22), a scoped runtime
  patch instead (`mtproc.process._band_masks_applied`) drops the STFT
  windows it overlaps from each band whose centre period it covers, before
  the regression (Morocco C18 rr C19, 2023-09-23 01:00-03:00 UTC: 8 masks
  over [0.02, 0.1] s moved those 7 bands by 0.02-9 % and left the other 41
  bit-identical, 43.0 s against 41.3 s unmasked; tests/band_masks_unit.py
  also shows aurora's shared Huber iteration count letting a mask shift
  later bands of the same decimation level, on stock aurora only -- the
  fork resets it per regression). It also acts in
  `mtproc.crosspower.stack_impedance(result, masks)`, the classical
  cross-power editor's estimate: per band, the kept chunks' <E R*> summed
  times the inverse of their <H R*> summed, with a delete-one-chunk
  jackknife error -- a library function, not in the GUI and not yet written
  as an EDI (tests/crosspower_unit.py 7: within 2 % of the known Z on the
  synthetic archive at levels 0-1 once the burst chunk is masked, 5.5 %
  median off with it in). Timings on this machine, 4 threads, with the
  remote: the whole overlap of Morocco C18 rr C19 (filtered variants,
  43.8 h, two aurora jobs running alongside) 31-37 s in 263 chunks of
  10 min (peak process RSS 0.52-0.65 GB) and 45-56 s in 2629 chunks of 1 min
  (0.33-0.50 GB); Curnamona D02 rr E08's 41.3 h in 31.5 s (smoke (34)); 2 h windows
  at 1000 Hz: Curnamona D02 rr E08 2.0-3.0 s (4.5 s on one thread), Morocco
  C23 rr C22 2.1 s in 10 min chunks, 2.9 s in 1 min chunks. Checked against
  the processed EDI: on D02's fourth window the
  chunk medians sit on D02_rr-E08.edi within 1 % in |Z| and 0.3 deg in phase
  from 0.0056 to 0.18 s (0.999 of it at 0.0898 s, smoke criterion 34), within
  4 % in |Z| from 0.2 to 1.4 s (phases up to 12 deg off where the Ey coherence
  is under 0.5); past about 2 s a 10 min chunk averages 35 windows or fewer
  and D02-E08's coherence is low, so the chunks scatter off the robust EDI. **Morocco
  C23** rr C22, 2023-09-22 19:02:36-21:02:36 UTC, raw archives: in 1 min
  chunks, 18-20 of 120 chunks in the 0.028-0.071 s bands carry an |E| 4-5
  times the rest, in pairs of adjacent minutes every 11-13 min -- the load
  switching on for about 58 s every 13 min (see **mains** above) -- with the
  Ey coherence down from 0.9 to 0.1-0.2 and |H| up only 1.1-1.2 times; 15-16
  of the 18-19 polar-plane outliers (5 MAD) at 0.028 and 0.045 s are those
  chunks. In 10 min chunks 9 of the 12 hold a switch, and the three that do
  not stand out instead (Ey coherence 0.88-0.93 against 0.2-0.4, |E| half).
  Morocco C10 rr C11, 2023-09-24 18:21-20:21: |E| 3-7 times higher from
  18:30 to 18:50, then a raised E floor with coherence 0.3-0.4 for the rest.
- **View EDIs** — built on **mtpy-v2**, which draws decent transfer
  functions, with several stacked over each other for comparison. The tree
  lets you tick any combination of
  `<workspace>/tf/*.edi` and the lemimt references in
  `<survey>/reference_edis.yaml`, ordered by stem so the newest run of a pair
  is last, and labelled from the stem when it is one of `scripts/process_rr
  .run_stem`'s own ("D02 rr E08, 23 Sep 21:15, hann") or left as its plain
  file name otherwise (an EDI from before the naming change, or a
  hand-named one -- e.g. the Curnamona `D02_rr-E08.edi` fixture and the
  Morocco batch EDIs, which keep their names) -- and the picture is a live matplotlib
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
  **Quick view** (on, by default) lets the keyboard down arrow step quickly
  through the list: the row under the cursor is drawn on its own
  *plus* whatever is ticked, so a student steps down a survey against a fixed
  reference. A click puts the focus back on the tree, and redraws go through a
  single-shot 150 ms `QTimer`, so holding the arrow down costs one draw and not
  one per row. Switch quick view off and only the ticked rows are drawn.
  The **Plot** radio group is "rho and phase", "plus phase tensor" (mtpy's row
  of ellipses, one per station -- phase tensors and, for long-period data,
  induction arrows) and "plus tipper", which is **disabled** with the
  tooltip "no hz sensor on this survey" while no site of the survey declares an
  hz channel: the aurora EDIs of such a survey still carry a tipper, estimated
  from an open Bz input, and it is nonsense, so it is never drawn by default.
  The **Phase** radio group is "0 to 90 deg" (default) and "-180 to 180 deg":
  mtpy always folds the yx phase into the xy curve's own quadrant --
  `phase_yx + 180` (`mtpy.imaging.mtplot_tools.plotters.plot_phase`, checked on
  2.1.4's source: neither `PlotMTResponse` nor `PlotMultipleResponses` offers
  an unfolded mode, so this is post-processing, not an mtpy option) -- with the
  axis clamped to 0-90 (`set_phase_limits(mode="od")`). "-180 to 180 deg" undoes
  that fold after mtpy has drawn: `tf_plot._apply_phase_range` shifts every yx
  curve's line, cap markers and error-bar segments back by -180 (`axp2` when
  the draw is an overlay -- `PlotMultipleResponses(plot_style="compare")` gives
  xy and yx separate axes -- or the second of `axp`'s two containers when it is
  one EDI on its own, `PlotMTResponse` drawing xy then yx on one axes) and sets
  the axis to (-180, 180) with ticks every 45°, so a physical yx (usually near
  -135) and a mode 180° out of quadrant both show where they are instead of
  hiding inside 0-90; the phase axes' ylabel names the range so the picture
  says which one is on screen. The choice reaches every EDI on the canvas --
  ticked rows, the quick-view row, any `Plot` choice -- and stays put until
  changed again, across a redraw, a quick-view step or a different `Plot`
  radio. Below Phase, an **Apparent resistivity** group's two fields (min,
  max, Ohm m; blank -- the default -- is "auto") clamp an outlier off the
  viewing scale: `tf_plot._apply_rho_limits` reads each resistivity axes'
  own y limits after mtpy has already drawn (`plotter.axr` always, `axr2`
  too on the compare overlay, where it holds the yx curves) and replaces
  only the side that was typed, so a blank side keeps mtpy's own automatic
  value -- this is why the limits go on after the fact rather than through
  mtpy's own `res_limits` kwarg, which would need both sides given together.
  A field commits on `editingFinished`, through the same debounce as
  everything else; a min at or above the max, or either at or below zero, is
  left unapplied and shown on the status line instead of being drawn wrong.
  A two-EDI overlay draws in about 0.2 s on this machine, so the whole
  thing runs in the GUI thread behind a "drawing..." label; `mtpy.MT` objects
  are cached per file (an `mt_metadata` parse is ~0.1 s) and only forgotten
  when a `process_rr` job rewrites `<workspace>/tf`. The references on the
  field drive are only ever read.

## The engine behind the views

- `load_segment` reads the window through the same `Grid`/`run_slices`
  arithmetic the tree used to list it, one channel at a time, into
  `mtproc.timefreq.Record`'s float32 offset-removed convention (7.2 M samples a
  channel, 29 MB each; the display copies are float64 with the offset back,
  58 MB each). `compute_segment_qc` then calls only `mtproc.timefreq`: the
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
