# mt-processing-2026 - handover (2026-09-23)

Where the broadband MT workflow stands after three sessions: the Curnamona
build-and-validate day (2026-09-21), the first Burra (noisy) day (2026-09-22),
and the GUI phase (2026-09-22/23, this handover). Repo:
https://github.com/bvkay/mt-processing-2026

The student-facing command line is the table in `README.md`; every step is a
plain script (no notebooks, no LLM at run time). The desktop GUI
(`src/mtproc_gui`, authoritative doc `src/mtproc_gui/README.md`) is a launcher and
viewer over those scripts and each survey's YAML - it computes no product of
its own. Per-site findings live in each survey's `qc_notes.md`.

## 2026-09-23, second session: filters, archives, line C, other instruments

Everything below is uncommitted on top of 5878872 (the rename commit). All 20
`tests/*_unit.py` and `tests/gui_smoke.py` (34 criteria) pass on this tree.

### Landed

- **Archive layout: raw archive plus filtered variants.**
  `<workspace>/mth5/<site>.h5` is the recording, built once with no filters.
  Processing reads `<site>_f<hash>.h5`, built on demand from the raw archive
  with the site's declared list (`mtproc.ingest.build_variant`,
  `processing_archive`; hash = sha1[:8] of the list; one variant per site
  kept; written to `.part` then renamed). A filter object in the MTH5 was
  rejected: aurora applies responses on 7.8 Hz-wide bins at 1000 Hz, so a
  notch stored as a response leaves the 50 Hz line in the bins (the C18
  spike); mains/cp/burst are not linear filters at all. Archives with
  filters baked in (Burra, some Curnamona) are refused as "old layout" until
  rebuilt raw (`scripts/ingest_site.py <survey> <site> --raw`).
- **Filter kinds**: `burst` (transient masking), `flip` (sign), `mains`
  (block-wise fitted subtraction that follows amplitude steps; the notch's
  ringing at C23's stepping mains was the "burst"). For a stepping or
  cut-off mains declare `mains` then `notch`. NotchForm shows its ring time.
  "Copy to sites..." dialog on the Filter Data tab (Replace/Append).
- **Hann is the default taper** (`build_config`; `--taper boxcar` restores
  the old). Validated on Curnamona D02 rr E08 (no loss) and it repairs D03's
  50 Hz leakage on line D.
- **Products**: `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>].edi` plus a
  `<stem>.json` sidecar (window, archives, band scheme, tweaks, filters,
  masks, versions, quadrant verdict). Nothing is overwritten any more.
- **GUI**: phase axis locked to 0-90 or -180..180; rho min/max; loaded
  window marked in the Filter Data chooser; basemap zoom +3 (cap 8000 px);
  Metadata columns `sensor_type` (EDL: bartington | lemi120) and
  `electric_gain`; **Cross-powers tab** (per-chunk, per-band
  remote-reference impedance, coherence, polar plane, rectangle selection,
  `<survey>/masks.yaml`; `process_rr` cuts the all-band masks out of the
  kernel dataset; band-limited masks are provenance only).
- **Scripts**: `line_scan.py` (narrow lines per site/hour, table + figure),
  `fetch_observatory.py` (INTERMAGNET GIN one-second -> MTH5 hx/hy/hz at
  1 Hz + survey entry; unfetched: the session's shells lost DNS),
  `campaign.py` (resumable remotes/stacks/options campaign with
  `mtproc.quality` scores), `build_stack.py --weighting coherence --check`
  (members read from archives: 26 s and 2.7 GB instead of 308 s and 47 GB).
- **Instruments**: EDL broadband (Hillside 2012) matches the 2012 BIRRP
  processing after five ingest fixes (LEMI-120 coil chain, other stations' files,
  incomplete stamps, short files, preset word order); PR6-24 electric chain gain declared
  per survey/site from the field notes (Stuart Shelf 2009: `electric_gain: 10`
  beyond mt-io's x10 terminal box, trip 2 verified against the 2009 EDIs);
  `Survey.site_dirs` reads a site's `raw\` subfolder; `lemimt_band_scheme`
  refuses bands narrower than one FFT harmonic.

### Findings

- Line D batch (13 pairings, raw archives): most sites track lemimt to a
  few percent; D12's yx is 180 deg out (a reversed channel: declare
  `flip`); D10 xy is a factor 2.3 above lemimt because lemimt used 50 m for
  a 33 m dipole (aurora is right); the 1-10 s xy sawtooth at D01 is
  incoherent coils, not band layout; D03's short-period fault is D13's 50 Hz
  leaking through the boxcar window. Coherence-weighted stacks do not beat
  the nearest quiet single remote; D01 on the stacks' window was best.
- Interharmonic sidebands 50 +- 12.55 and +- 15.7 Hz across line D
  (stable to 0.05 Hz, intermittent): declare them as notch `extra` lines.
  B24: 50m +- 60n Hz intermodulation from a 60 Hz source -> a second notch
  `f0: 10, harmonics: 20`. B30 and B24: stepping mains -> `mains` first.
- Line C: C21's folder is a copy of C07 (excluded); no lemimt references;
  every archive was raw at the time of processing, hence the single-band
  spike at 0.017 s next to 50 Hz. Campaign running (see below).
- Stuart Shelf 2009: 81 of 97 deployments are PR6-24, 16 Orange Boxes;
  mt-io's Orange Box reader decodes the files but its time axis, E scale and
  one magnetic scale are wrong (issues 10-16); the 2009 Orange Box EDIs have
  xy/yx swapped; the GPS forensics (`qc/gps_summary.md` in that workspace)
  found no lost survey in trip 1, ST59's data under the prefix ST52_, ST34
  empty, ST36's first deployment missing.
- Hillside: mt-io's PR6-24 reader silently calibrates coils as Bartington
  fluxgates (rho 1e-7 x BIRRP on LEMI-120 data) -> `sensor_type`.

### Running

- Line C campaign, runner pid 34132, `<Morocco workspace>/campaign/lineC/`
  (ledger.csv, runs.log, campaign.out, figures/, tf/, summary.md):
  stage 0 (variants) done; stage 1 (266 remote runs), 2 (46 stacks), 3
  (207 option runs) follow, two at a time, ~5.5 min per run. Group A first.
  `python scripts/campaign.py <survey> <plan> --report` redraws everything.
  Kill and relaunch to resume.

### Open

- The GUI has no `intermagnet` instrument yet (Metadata rejects the entry;
  Build MTH5 has no branch); aurora needs equal sample rates, so a 1 Hz
  observatory references 1 Hz archives only.
- Long-period needs (Stuart Shelf lists in both `qc/*.md`): Orange Box
  instrument in mtproc, rate-appropriate processing block, Spectra/
  Coherence to 1e4 s, UTC-day windows, select the recommended remote.
- `tabs/crosspower.py` is 678 lines; the remote preset ignores the window.
- HANDOVER/README documentation pass.
- Old products keep their names; the campaign's products live outside the
  GUI's EDI list.

## What works (validated)

**raw B423 -> MTH5 (mt-io readers) -> aurora (RR) -> EDI -> comparison figure**

- **Curnamona D02 RR E08** (`examples/01_validate_d02_e08.py`): matches the
  merged lemimt EDI from 0.005 s to ~3000 s in rho and phase, both modes
  ([figure](docs/figures/D02_rr-E08_vs_lemimt.png)). Synthetic stacked remote
  and band-averaged coherence QC as before (`examples/02`, `03`).
- **Burra35 RR Burra54rr3** on its good-Ex window (first 16.5 h) **with the
  declared filters** (mains notch, then the 12 s stack-and-subtract): both
  modes match lemimt from 0.005 s to 1000 s including the cathodic-protection
  band ([figure](docs/figures/Burra35_rr-Burra54rr3_filtered_vs_lemimt.png);
  [unfiltered](docs/figures/Burra35_rr-Burra54rr3_window_vs_lemimt.png) for
  contrast: 1-15 s lost).
- **Burra57 RR Burra54rr3 with the declared filters** (19 h window): both
  modes match lemimt 0.005-~1000 s, through the cathodic-protection band
  ([figure](docs/figures/Burra57_rr-Burra54rr3_filtered_vs_lemimt.png);
  [unfiltered](docs/figures/Burra57_rr-Burra54rr3_vs_lemimt.png): 0.3-15 s lost).
- **Per-site QC set** (`scripts/site_qc.py`, plus `scripts/psd_qc.py`):
  whole-record overview, band coherence vs time, coherogram, spectrogram, and
  the calibrated whole-record PSD per channel with the remote overlaid
  ([D02 coherence vs time](docs/figures/D02_02_band_coherence_vs_time.png),
  [Burra57 coherogram](docs/figures/Burra57_03_coherogram.png),
  [Burra35 overview](docs/figures/Burra35_01_overview.png)).
- **Timing QC before ingest** (`scripts/timing_qc.py`): file-boundary slips,
  clock offset vs the remote by cross-correlation (10 ms resolution), GPS
  status per file.
- **The GUI** (`src/mtproc_gui`, new this phase): a PySide6 + pyqtgraph
  launcher-and-viewer, verified end to end by `tests/gui_smoke.py` against
  the real Curnamona survey (see "What was verified and how" below) - the
  tree-driven Time Series/Spectra/Spectrogram/Coherence tabs, the Filter Data
  and Process tabs (including the queue, the recommendation tie-break and the
  basemap), and the mtpy-v2 View EDIs tab all load and draw real archives.

Environment: `conda env create -f environment.yml` -> `mt-2026` (an environment
created earlier as `bbmt-2026` keeps working; mth5 0.6.9, mt-io 0.0.5,
mt-metadata 1.0.10, aurora 0.6.2, now also PySide6, pyqtgraph and
mtpy-v2 2.1.4 for the GUI - see README.md's "The GUI"). 128 GB Windows box; a
full-deployment RR run peaks ~45 GB and takes ~13 min; ingest of a 2-day site
takes ~30 s.

## The cathodic-protection band at Burra (solved for Burra35 and Burra57)

Unchanged since 2026-09-22, not touched by the GUI phase. At Burra35 and
Burra57 a high-pressure gas main's cathodic protection puts a comb of lines
(harmonics of a ~12 s cycle, **exactly 12.000 s**) from ~0.08 to ~5 Hz on
**both** local E and local H. Unfiltered this made 0.3-15 s unusable in both
modes; with the declared filter list (`<survey>/filters.yaml`: `notch` 50 Hz
+ harmonics first, then `cp` - stack every cycle in 10-min windows and
subtract the median cycle, nothing detected, nothing cut) both sites match
lemimt across the whole band. "Replace magnetics" (local E + remote H,
single-station) was tried and rejected: 28-32 % off lemimt in rho where RR is
within 3 %, and it conflicts with the no-single-station rule; the code was
removed. Full detail and the KISS-stack numbers: `surveys/burra/qc_notes.md`,
`docs/prototypes/kiss_variants.py`.

## Decisions made

**Library and processing (2026-09-21/22, unchanged):**
- Thin library, headless first, GUI later; decisions are data (per-survey
  YAML); visual comparisons over numbers; site = folder name.
- **No single-station processing at all**: every product is remote-referenced,
  using an adjacent site, a dedicated remote, or a stacked synthetic remote.
- **Noise removal order: mains first, then cathodic protection**, both a
  per-site declared filter list, never auto-detected.
- **No hz on any broadband deployment**: no sensor was attached, the B423 Bz
  column is an open input. `channels: [ex, ey, hx, hy]` drops it at ingest;
  no tipper should be produced (see "Findings" - two old archives still do).
- **Burra field-sheet azimuths are layout direction, not polarity**
  (`flip_reversed_dipoles: false`); Curnamona's are polarity (`true`).
- **Processing window != archive window**: one MTH5 per site holds the whole
  deployment; `start`/`end` on the processing scripts trim aurora's kernel
  dataset only.

**The GUI (2026-09-22/23, new):**
- **PySide6 + pyqtgraph**, a launcher-and-viewer over `scripts/` + YAML: no
  processing code and no PNG anywhere in `src/mtproc_gui`; no single-station
  option anywhere either.
- **Tree-driven Time Series tab**, mirroring the legacy MATLAB field app: a
  site tree on the left expands to fixed windows (2 h at 1000 Hz, 4 h at
  500 Hz, `windows.py`); a click loads that window's time series, spectra,
  spectrogram and coherence.
- **The segment-QC remote is off by default** (`State.remote`, "(none)" on
  every new station): local pairs answer the usual noise questions; remote
  pairs only settle dead-coil-vs-quiet-field (e.g. A07's hx), so they are
  switched on when that is the question.
- **QC tabs keep the previous result in view** until a new one arrives -
  no tab blanks itself while the next window's QC is computing.
- **"Add to queue" only adds, "Run queue" only runs** (the MATLAB flow,
  restated 2026-09-23): every queuing button calls `JobRunner.add` only;
  the one exception is Metadata's "New survey..." (not a processing job,
  opens no archive), which adds and runs together.
- **Look**: dark theme, magnetics blue / electrics red, shared x axis with no
  gap between stacked panels, locked zoom (no pan/zoom past the data
  extent), Zxy/Zyx-style labels - copied from the legacy MATLAB field app
  (`theme.py`).
- **The Process tab is arranged like the MATLAB Process Data tab** (2026-09-23);
  every control does what it did before, only the order changed
  (`docs/matlab_app_borrowing.md`).
- **mtpy-v2 2.1.4** installed for the View EDIs tab: phase tensors now,
  induction arrows later (tipper stays disabled - no hz sensor on this
  survey).
- **A console strip** echoes backend commands: the subprocess queue's log,
  the in-process loguru sink, and "[segment] ..." window-load lines, three
  lines tall by default, resizable.
- **New surveys are built from a folder** by `scripts/new_survey.py` (B423
  headers via mt-io, `--site-table` merge), reachable from the Metadata tab's
  "New survey..." dialog.
- **The Metadata table is editable everywhere**, with a warning when
  `generated_by` is set (regenerating the sites block from the field sheet
  would overwrite GUI edits) - Save asks Yes/No first in that case.

## What was verified and how

`tests/gui_smoke.py` (`QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py`)
drives the real GUI, offscreen, against the real Curnamona survey and its
three archived sites (D02, E08, A07, opened read-only) - the closest thing to
a manual click-through this repo has. It checks, among 23 numbered criteria:
the tab order and the dark palette's exact colours; the tree's 59 site rows
with exactly D02/E08/A07 expandable; that a clicked window's time series
matches an independent h5py/numpy read of the same samples; that `qc_ready`
follows with correct PSD line detection, coherence and spectrogram values;
that the remote combo, `goto_time` cursor sync and "use visible range as
processing window" all work; that queuing never auto-starts a job except New
survey; that the Process tab's layout, its recommended-remote tie-break, its
sync lamps and its site map/basemap all match independently-computed
distances and overlaps; that Filter Data round-trips `filters.yaml`; that
View EDIs draws real mtpy error bars; that Import site table and New survey
run end to end against synthetic data; and that all nine screenshots
(`gui_timeseries.png`, `gui_timeseries_3s.png`, `gui_spectra.png`,
`gui_spectrogram.png`, `gui_coherence.png`, `gui_metadata.png`,
`gui_process.png`, `gui_filters.png`, `gui_edis.png`) are written. It writes
nothing to the real `survey.yaml` or `filters.yaml` (round trips use a scratch
copy) and only PNGs under `surveys/curnamona_cube/work/qc/` - **gitignored**,
so a reader regenerates them by running the smoke test rather than pulling
them from git.

The Qt-free unit tests each check one library or GUI-support module in
isolation: `windows_unit.py` (the window-list math), `segment_unit.py` (the
segment QC engine on a synthetic hour - line detection, coherence values, no
input-array mutation), `psd_ladder_unit.py` (bit-identical to a direct
`scipy.signal.welch` call), `survey_unit.py` (`distance_km`, `Survey.timezone`
against both real survey YAMLs), `ingest_unit.py` (`ignore_filters`),
`process_rr_cli_unit.py` (`process_rr.py --dry-run`'s flag-to-tweak mapping
and the in-use estimator defaults), `basemap_unit.py` (the Mercator warp
against an independent pyproj computation, network mocked) and
`new_survey_unit.py` (B423 header parsing against synthetic files, then the
real Curnamona headers).

Timings measured on the development machine: a 2 h window at 1000 Hz draws 2.6 s
after the click; all QC views 5 s without a remote, 8 s with one; a two-EDI
mtpy overlay draws in 0.2-0.4 s; the new-survey scan of 59 Curnamona sites
takes 2.6 s; the OpenTopoMap basemap fetch for Curnamona took 18 s at zoom 8.

## Findings

- **`D02_rr-E08.edi` carries a nonsense tipper**: D02 and E08 were ingested
  before hz was dropped from `channels:`, so their archives still hold the
  dead Bz column and aurora estimates a tipper from it. Fix: delete the two
  archives on the Filter Data tab and re-run `process_rr.py` - it now only
  asks aurora for the declared output channels, so a fresh ingest will not
  reproduce this. The two old archives are the fix still outstanding (Next
  steps, below).
- **D02's By shows a comb between 0.3 and 2 Hz** on the D02-E08 pair spectra
  that Bx and the E08 coil do not show - unexplained; not cathodic
  protection (that is a Burra-only finding) and not yet chased down.
- **mth5 opens archives read-write when building a config**
  (`docs/upstream_issues.md` #5, found 2026-09-23):
  `KernelDataset.from_run_summary` opens the local station read-write even
  to build a config, so it cannot run while the GUI or a test holds the same
  archive open, and it touches the file's modification time on every
  processing run. Workaround in tests: monkeypatch both `initialize_mth5`
  and `MTH5.open_mth5` to force `mode="r"`. Worth an upstream request.
- **Other instruments (2026-09-23): LEMI-424 and Earth Data PR6-24 (EDL)**
  are read, archived and viewed (README.md, "Instruments";
  `mtproc/instruments.py`, `mtproc_gui/channels.py`). The instrument is
  detected per site folder with a survey default and an `instrument:` per
  site; archives keep the readers' names (a LEMI-424's bx by bz e1-e4), and
  the LEMI-423 path writes byte-identical archives (checked old vs new on
  3 h of D02 and A07). Checked on one real hour each: MBJ21 (LEMI-424,
  `<data_root>/MT_WA-MT/Phase_1`, daily 1 Hz files, not hourly) and EGFLP02
  (EDL 10 Hz, `<data_root>/MT_PROCESSING_2026/MT_EasternGoldfields`). What the readers
  hand over: **LEMI-424 electrics are the recorded mV, labelled mV/km by
  mt-io** (no dipole length; the `.inf` says L1-L4 = 50 m) and no filter
  chain; its run metadata lists only e1 e2 as recorded (mth5 corrects it on
  write). **EDL has no rate without `recorder.ini`** unless two files give
  it, no position (its `.gps` sidecars are not parsed), and only the
  Bartington long-period chain is wired (broadband LEMI-120 on the PR6-24
  is not). In the GUI a LEMI-424's first two electrics, E1 and E2, stand in
  for Ex and Ey ("By-E1 (Zxy)").

## Hard-won facts (do not rediscover these)

1. **LEMI-423 magnetics come out of mt-io in pT with inverted polarity**
   relative to lemimt: CoefficientFilter gain -1000 (`h_scale`). Coil response
   `sensors/l120n.rsp`.
2. **Contiguous B423 files must be merged into long runs at ingest**; a new
   run starts at any epoch-spacing anomaly. Burra's "Behind" field-sheet flags
   are **not** clock errors; the one real 1 s event is a file-boundary slip in
   Burra54rr3.
3. **Band scheme**: 10 periods/decade, factor-4 levels, window 128, 75 %
   overlap on long windows; mains notched at 50/150 Hz.
4. **The RR estimator is calibration-invariant**: synthetic remotes stack raw
   counts; GPS ms grids align exactly.
5. **One dead channel poisons a mean stack** (Curnamona A07 hx; Burra25 hx
   likewise).
6. **Ex failures show up in the overview figure and kill one mode**: Burra35
   Ex died 16.5 h in. Per-channel time masks are the general fix (next: the
   cross-power editor's masks, see Next steps).
7. **Dead bands**: Curnamona 2-10 s (natural, time-varying); Burra 0.2-20 s
   on the local coils from the CP comb, RR still recovers outside 0.3-15 s.
8. **Code gotchas**: RunTS channel accessors return copies; aurora needs
   `num_samples_window` as a per-level list; `MTime` needs `str()` before
   `pd.Timestamp`; **never open an MTH5 another process has open** (HDF5
   locking, and see the mth5 read-write finding above); mt-io discards the
   per-sample GPS `sync`/`stage` columns (`docs/upstream_issues.md` #4).

## Open items

- Coherence-weighted stacking: per-member weights per time chunk and band
  group, then full per-band weighting at the Fourier-coefficient level;
  median stack as the robust baseline. Aurora also reports zero impedance
  errors for a virtual (uncalibrated) remote - open since the earlier
  handover.
- The aurora feature-weights experiment (per-band, per-window weighting at
  the estimator level) remains open from the earlier handover.
- Add 60 Hz to the Burra band-scheme notches (the remote's faint 60 Hz line
  shows as one off band at 0.017 s at Burra57).
- Burra33 RR Burra54rr (clean long pair, already extracted): the check
  against `Burra33.edi`.
- 50/100 Hz band-placement experiment on Burra57's short periods.

## Next steps (agreed order)

1. **Commit the uncommitted work in two commits**: library/scripts/config
   first (`src/mtproc/*.py`, `scripts/*.py`, `environment.yml`, `pyproject.toml`,
   the two `survey.yaml`s, `docs/upstream_issues.md`), then GUI/tests
   (`src/mtproc_gui/`, `tests/`, this handover and the README).
2. **The cross-power editor**, one site at a time: per-band, per-window
   cross-powers, coherence and single-window rho/phase against time, from
   `mtproc.timefreq.window_spectra`. Masks saved as UTC intervals per site in
   `<survey>/masks.yaml`; `process_rr.py` excludes them - an extension of the
   existing processing-window clipping to several intervals instead of one.
   Aurora's Fourier-coefficient storage was considered and **rejected** for
   this: about 10 GB per site at the first decimation level alone.
3. **Burra in the GUI**: `surveys/burra` is ready on the config side (93
   sites, remotes filled per stage, `filters.yaml` for Burra35/Burra57,
   `timezone: Australia/Adelaide` set) but untested through the GUI itself.
4. **Borrowing-list items** (`docs/matlab_app_borrowing.md`'s top five, not
   yet built): high-pass/low-pass filter kinds in `filters.yaml`;
   before/after filter comparison on the loaded QC window; the spectrogram's
   relative-to-median and baseline-from-zoomed-window modes; swap/flip coil
   kinds; the least-squares quick-look with its coherence gate and 3-MAD trim
   (open whether its single-site nature is acceptable - it sits in front of a
   product, not in place of one, but needs an explicit decision).
5. **Re-ingest D02 and E08 without hz** (see Findings): delete the archives,
   rerun `process_rr.py` (a full-deployment ingest plus estimate is about 13 min per pair). Coherence-weighted stacking and the
   aurora feature-weights experiment remain open from the earlier handover
   (see "Open items").
6. **The electric-pair setting for LEMI-424** (which two of e1-e4 are Ex and
   Ey): a per-site key read by `mtproc.process`, which must also pass aurora
   its electric-channel nomenclature (LEMI12/LEMI34) -- `process.py` was not
   touched by the instruments work, so **a LEMI-424 site cannot be processed
   yet** (ingest and view only). With it: the dipole length for e1-e4 (the
   reader leaves them in mV), and the GUI's pair rule then follows the
   setting instead of "the first two electrics". EDL sites use the LEMI-423
   names and are processable as they stand, but no EDL transfer function has
   been checked against lemimt yet.

## Burra survey facts

- Raw: `E:\MT_Timeseries_DATA\MT_Burra_2017-2020`, 94 zips (332 GB), each
  unzips in place to `Burra##/`. Extracted so far: Burra35, Burra57, Burra25,
  Burra54rr3 (Jun 22-27 2018 stage) and Burra33 + Burra54rr (Jun 4-13, not yet
  processed).
- Five stages, each with its own Burra54 remote deployment (Burra54 for
  Oct 2017; Burra54rr, rr2, rr3, rr4 for the four 2018 stages).
- Config: `surveys/burra/survey.yaml`, 93 sites, `generated_by:
  scripts/burra_notes_to_yaml.py`, `timezone: Australia/Adelaide`, and (new
  this phase) a `remote:` on every site that overlaps a Burra54* deployment.
  `reference_edis.yaml` maps 92 of 93 (Burra17 has no EDI).
- Field-noise log per site/channel/file: `BurraTimingPhase2.xlsx`, sheet
  "File Quality by Channel". CP sites: 57, 50, 35.

## Figures

Headline validation figures (unchanged this phase):

| | |
|---|---|
| ![Burra35 windowed RR](docs/figures/Burra35_rr-Burra54rr3_window_vs_lemimt.png) | ![Burra57 RR](docs/figures/Burra57_rr-Burra54rr3_vs_lemimt.png) |
| ![Burra57 coherogram](docs/figures/Burra57_03_coherogram.png) | ![Burra35 overview](docs/figures/Burra35_01_overview.png) |
| ![D02 coherence vs time](docs/figures/D02_02_band_coherence_vs_time.png) | ![D02 RR validation](docs/figures/D02_rr-E08_vs_lemimt.png) |

GUI screenshots from `tests/gui_smoke.py` - `surveys/curnamona_cube/work/qc/
gui_timeseries.png`, `gui_timeseries_3s.png`, `gui_spectra.png`,
`gui_spectrogram.png`, `gui_coherence.png`, `gui_metadata.png`,
`gui_process.png`, `gui_filters.png`, `gui_edis.png` - are **gitignored**, not
committed. Regenerate them with:

```bash
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
```
