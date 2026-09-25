# mt-processing-2026

Magnetotelluric (MT) processing for Adelaide Uni surveys recorded on
LEMI-423, LEMI-424 and Earth Data PR6-24 loggers (see "Instruments" below),
built on the IAGA-DVI stack
([mt-io](https://github.com/kujaku11/mt-io), [mth5](https://github.com/IAGA-DVI-DataStandards/mth5),
[mt-metadata](https://github.com/IAGA-DVI-DataStandards/mt-metadata)) with
[aurora](https://github.com/simpeg/aurora) as the transfer-function engine.

Design rules, in order:

1. **Thin.** `mtproc` wraps the community packages; it does not re-implement them.
2. **Headless first.** Everything runs from a script or the command line; the
   desktop GUI (`src/mtproc_gui`, see "The GUI" below) calls the same scripts
   and computes no product of its own.
3. **Decisions are data.** Noise masks, band choices and remote-reference pairs
   live in per-survey YAML/JSON files, never buried in code or notebooks.

## Install

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

`environment.yml` creates `bbmt-2026` (Python 3.11) and installs this package
editable; every dependency, the GUI's included, is listed once, in
`pyproject.toml`.

### The stack: the mtproc-fixes forks

mtproc runs on the `mtproc-fixes` branches of five forks, `github.com/bvkay/`
aurora, mth5, mt-io, mt-metadata and mt-timeseries, which carry the fixes
logged in `docs/upstream_issues.md`. `pyproject.toml` names them by git URL
(`mth5 @ git+https://github.com/bvkay/mth5@mtproc-fixes`, ...); all five branches are on
GitHub, so a plain install resolves them. A local clone (a sibling of this
repo) installs over the package from GitHub, leaving every other dependency
as it is:

```bash
pip install --no-deps ../mt-metadata ../mt-timeseries ../mt-io ../mth5 ../aurora
```

The `*_fork_unit.py` tests below check each fork (the clones, and whatever is
installed, reported side by side). mtproc no longer patches the stock
packages at runtime; the shims it used to install are retired, the forks fix
the same bugs at the source:

- mt-io (issues 1, 2, 6): the LEMI-120 coil chain of a LEMI-423 read with a
  `calibration_fn` (valid unit names, coil stage ahead of the linear stage)
  and four-digit LEMI-423 altitudes (`%Alt1060.0,m`), both once patched in
  `mtproc.ingest`;
- mth5 (issue 5): run summaries and kernel datasets open archives read-only,
  once forced in `mtproc.process`;
- mt-timeseries (issue 17): a RunTS station lists its channels, with no
  phantom `auxiliary_default`, once overridden in `mtproc.observatory`.

On stock packages these are bugs again: a LEMI-423 site with a
`calibration_fn` does not ingest (stock mt-io's coil response carries a unit
mt_metadata rejects), building a processing config fails while another
process (the GUI) holds an archive open and touches the archives'
modification times, a 10.00064 Hz Orange Box run is dated at 10 Hz, and an
observatory archive's station lists `auxiliary_default`.

## Layout

```
src/mtproc/        the package: survey.py, instruments.py, ingest.py, process.py,
                   compare.py, bands.py, qc.py, timefreq.py, virtual.py
src/mtproc_gui/    the desktop GUI: a launcher and viewer over scripts/ and
                   survey.yaml, no processing code of its own (see below and
                   src/mtproc_gui/README.md)
surveys/<name>/    one folder per survey: survey.yaml (config), reference_edis.yaml,
                   qc_notes.md (what was learned about each site) + work/ (outputs, gitignored)
scripts/           the student-facing command line, one job each (see below)
tests/             unit tests (no Qt) plus the GUI smoke test
```

## Command line (no notebooks, no LLM: plain scripts a student runs)

| step | script |
|---|---|
| new survey: a folder of site folders -> `survey.yaml` (each site's instrument detected from its files, the most common written as `instrument:` unless `--instrument` names one, a site on another recorder given its own `instrument:` and that recorder's default `channels:`; each LEMI-423 site's first B423 header via mt-io: position, serial, firmware, sample rate; a LEMI-424's `.inf` and first line, an EDL's `recorder.ini`; span from the file names; dipoles left to `defaults:`; `--site-table` merges a CSV/XLSX, template `docs/site_table_template.csv`; `workspace:` is `<data_root>/work` unless `--workspace` says otherwise; `--channels` names the columns that had a sensor, a preset from `mtproc.survey.CHANNEL_PRESETS`, "Ex Ey Bx By" by default, "Ex Ey Bx By Bz", "Bx By (magnetics only)", "Bx By Bz", or a list such as `hx,hy`, written as `defaults: channels:`, and the summary prints each site's file columns beside it; also the GUI's Metadata tab "New survey...", whose channels column sets a site that differs) | `scripts/new_survey.py <data_root> --name NAME [--instrument auto\|lemi423\|lemi424\|edl] [--channels SET] [--timezone TZ] [--site-table CSV] [--out PATH] [--workspace DIR]` |
| field sheet -> `sites:` block | `scripts/site_table_to_yaml.py`, `scripts/burra_notes_to_yaml.py` |
| UoA field-notes CSV (Stuart Shelf 2009 layout: header rows, then `Station`, `Latitude_dd`, `X_dip_length` = Ex, `Y_dip_length` = Ey, orientations, local deploy/recover times ...) -> the site table `new_survey.py --site-table` reads (position, dipoles, azimuths, `timezone`, and notes carrying serials, sensor, rate, gain, the times in local and UTC and the field remarks; a typed UTC that disagrees with the local time, and a blank dipole length, are named); `--data-root` lists stations with no folder and folders with no station | `scripts/site_table_from_notes.py <notes.csv> <site_table.csv> [--timezone TZ] [--data-root DIR]` |
| legacy EDIs -> `reference_edis.yaml` | `scripts/match_reference_edis.py <edi_dir> <survey.yaml>` |
| before ingest: file-boundary slips, clock offset vs remote, GPS status | `scripts/timing_qc.py <survey.yaml> <local> <remote>` |
| quick look at raw noise (Welch PSD, mains zoom) | `scripts/noise_psd.py <survey.yaml> <site>` |
| ingest a site's RAW archive into `<workspace>/mth5/<site>.h5` (its run length as `process_rr.py`'s), then build its filtered variant too if it declares any (`--raw` for the archive alone, `--variant` for the variant alone); refuses to rebuild an existing raw archive or an already-current variant without `--force`; several sites, or `--all` (every site of survey.yaml with a raw data folder, the others listed as skipped), make a batch that keeps existing archives and current variants, builds `--parallel N` sites at once, each in its own process logged to `<workspace>/logs/ingest_<site>.log` (default 1: one after another on the console), goes on past a failed site and ends with a table of each site's archive, variant, seconds and status (built, kept, failed with its error), exit 1 when a site failed; also the GUI's Time Series tab "Build MTH5" | `scripts/ingest_site.py <survey.yaml> <site> [<site> ...] [--raw \| --variant] [--max-run-files N] [--force] [--parallel N]`, `scripts/ingest_site.py <survey.yaml> --all [...]` |
| ingest both sites, remote-reference TF, overlay on lemimt (advanced: `--taper`, `--overlap`, `--no-prewhiten`, `--r0` ... on every decimation level); writes `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>].edi` (the stamp is when the run started, local time, so re-running the same pair and window never overwrites an earlier EDI) plus the matching `_vs_lemimt.png` and a `.json` sidecar of everything about the run (timing, archives, band scheme, tweaks, declared filters, argv, the phase-quadrant verdict, package versions); `--engine mantle` estimates with MANTLE (`mtproc.engine_mantle`: the same archives and window through MANTLE's MTH5 reader, its robust remote-reference cascade with jackknife error bars, the EDI pooled onto the same band scheme, plus MANTLE's fine-grid EDI and report JSON beside it; the sidecar gains `engine`, `engine_version`, `engine_config`, `mantle_report`, `mantle_fine_edi`; the aurora estimator flags and masks are refused with it) | `scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end] [--engine aurora\|mantle]` |
| aurora EDI vs every one of lemimt's unmerged per-rate/per-chunk EDIs for a site (e.g. Morocco Atlas Line D): rho/phase overlay by rate plus a per-rate median-difference table | `scripts/compare_unmerged.py <aurora.edi> <unmerged_dir> <site> [--remote NAME] [--out PNG] [--title TEXT]` |
| per-site QC set: overview, band coherence vs time, coherogram, spectrogram | `scripts/site_qc.py <survey.yaml> <site> [--remote R]` |
| whole-record PSD per channel from the archive, remote overlaid, lines marked, before/after filters | `scripts/psd_qc.py <survey.yaml> <site> [--remote R] [--before]` |
| narrow spectral lines per hour (grid-wide interharmonic combs, mains, drop-outs), for declaring a notch's `extra:` lines by hand: table + figure per site, summary across sites | `scripts/line_scan.py <survey.yaml> [SITE ...] [--hours-step 1] [--fmin 5] [--fmax 500] [--min-db 6] [--channels hx hy ex ey]` |
| try candidate filter chains on one window of a site's raw archive before declaring them (the command-line form of the Filter Data tab's preview): each chain from a YAML file in `filters.yaml` syntax, `--declared` adds the site's current list; writes per chain, under `<workspace>/qc/filter_trials/<site>/`, a 5-500 Hz PSD per channel with the evaluated lines marked plus the full-band ladder, the time series with a 20 s zoom on the largest change, the band coherence of ey-hx and ex-hy (and of the remote pairs with `--remote`), and a metrics JSON: line excess before/after, the floor between lines, coherence band means, burst and step fractions; `--lines` evaluates the site's line-scan lines too | `scripts/filter_trial.py <survey.yaml> <site> <start> <end> [--chain LABEL=FILE.yaml ...] [--declared] [--remote NAME] [--lines] [--out DIR]` |
| stacked synthetic remote from concurrent sites (each member read via `processing_archive`, its filtered variant if it declares any, else its raw archive, exactly as `process_rr.py` would read it; streamed in 10-minute chunks) | `scripts/build_stack.py <survey.yaml> <name> <start> <end> <member>... [--weighting none|coherence] [--check]` |
| band-averaged coherence on the processing bands | `scripts/coherence_qc.py <survey.yaml> <local> <remote> [--stack S]` |
| processing campaign over a line (plan YAML, e.g. `surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml`): stage 0 filtered variants, 1 every site rr every concurrent remote, 2 leave-one-out stacks (plain and coherence-weighted), 3 estimator/band options on each site's best remote; resumable (`ledger.csv`), `--parallel` jobs behind a memory gate, products scored by `mtproc.quality` and plotted per site and line-wide into `<workspace>/campaign/<name>/`, `summary.md`; `--report` redraws from the ledger | `scripts/campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...] [--parallel N] [--max-runs N] [--dry-run] [--report]` |
| map background for the GUI's site map, fetched once while online (Esri.WorldImagery by default: imagery, no place names; contextily's zoom + 3, longer side at most 8000 px; warped to lon/lat; `<workspace>/basemap.png` + `.json`); the GUI runs it itself when a survey is opened without `basemap.json` | `scripts/fetch_basemap.py <survey.yaml> [--provider NAME] [--margin F] [--zoom N\|auto]` |
| INTERMAGNET observatory as a 1 Hz remote for long periods (`mtproc.observatory`, ported from the AusLAMP processing): one-second X Y Z from the BGS GIN, best available, one request per UTC day into a day cache (`<workspace>/observatory/<CODE>/<year>/<CODE>_<date>.sec.gz`, the served IAGA-2002 text; a re-run fetches nothing cached), then `<workspace>/mth5/<CODE>.h5` (hx = X north, hy = Y east, hz = Z down, nT, no filters; gaps up to `--max-gap` s filled, one run per longer gap) and a `<CODE>: {instrument: intermagnet, ...}` site entry in survey.yaml; start/end default to the survey's site span; exit 1 when offline. Aurora pairs it only with a 1 Hz local archive (no mixed sample rates) | `scripts/fetch_observatory.py <survey.yaml> <IAGA code> [start] [end] [--cache DIR] [--max-gap S] [--dry-run]` |
| a broadband site at 1 Hz for an observatory remote: the site's processing archive (its filtered variant when it declares filters) decimated run by run, one channel at a time, through zero-phase FIR stages of at most 10 (scipy.signal.decimate, the filter of `mtproc.timefreq`; 11.1 s dropped at each run end, samples on whole UTC seconds) into `<workspace>/mth5/<site>L.h5`, station `<site>L` with the source's runs, channel metadata and calibration chains, and a derived-site entry `<site>L: {derived_from: <site>, sample_rate: 1.0, ...}` in survey.yaml; an existing archive is kept without `--force`. `process_rr.py <survey.yaml> <site>L <CODE>` then processes it at 1 Hz (bands from 4 s; a remote at another rate is refused) | `scripts/decimate_site.py <survey.yaml> <site> [--rate 1] [--force] [--min-free-gb G]` |

Every product is remote-referenced: an adjacent site, a dedicated remote, or a
stacked synthetic remote (`mtproc.virtual`). There is no single-station product.

`start`/`end` on the processing scripts are a *processing window* (UTC): the
MTH5 archive always holds the whole deployment, the window only trims what
aurora estimates from (e.g. Burra35 after its Ex cable failed).

A survey's **workspace** (`workspace:` in `survey.yaml`) holds the archives,
transfer functions, figures and the basemap. `scripts/new_survey.py` puts it
beside the raw data, `<data_root>/work`, since a 100-site survey's archives
run to hundreds of GB; a survey.yaml without the key (the existing ones) keeps
the old default, `surveys/<name>/work/` (gitignored).

`scripts/process_rr.py`'s EDI, comparison figure and `.json` sidecar in
`<workspace>/tf` share one stem, `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>]`
(the run's own start in local time, not the processing window, which is in
the sidecar). Older EDIs keep their old
`<local>_rr-<remote>[_w<start>-<end>][_<tag>]` names and have no sidecar --
e.g. `surveys/curnamona_cube/work/tf/D02_rr-E08.edi` and the Morocco batch
EDIs, both left as they are.

Per-site noise decisions live in `<survey>/filters.yaml` (see
`surveys/burra/filters.yaml`), separate from the field-sheet-generated
`survey.yaml`. Every archive `ingest_site` writes, `<site>.h5`, is the RAW
recording — filters are never baked into it. A site with a declared list is
processed from a filtered **variant** instead, `<site>_f<hash>.h5`
(`mtproc.ingest.processing_archive`/`build_variant`), built on demand from
the raw archive and rebuilt whenever the hash of the declared list changes (a
`filters.yaml` edit); one variant is kept per site at a time. `process_rr.py`
and `build_stack.py` (through `mtproc.virtual`) always read
`processing_archive`'s result; `--no-filters` reads the raw archive outright.
Try the list on a loaded window on the GUI's Filter Data tab first. The
kinds, documented in `src/mtproc/noise.py`'s module docstring: `notch` (50 Hz
+ harmonics), `hp` / `lp` (zero-phase Butterworth high- / low-pass,
`cutoff_hz` required, order 4; a high-pass goes first and removes every
period longer than 1 / cutoff_hz, a low-pass goes last), `cp` (cathodic
protection stack) and `replace` (magnetics from another site's raw archive,
applied first); `notch`, `hp`, `lp` and `cp` take an optional `channels` list
(default all).

## Quickstart: a survey in four lines

A survey is a YAML file pointing at the folder that holds the raw site
directories. **Site name = folder name** — nothing else to configure per site
unless a site needs overrides (dipole lengths/azimuths come from the field
spreadsheet via `scripts/site_table_to_yaml.py`).

```python
from mtproc.survey import Survey
from mtproc.ingest import ingest_site
from mtproc.process import process_station

survey = Survey.from_yaml("surveys/curnamona_cube/survey.yaml")
local  = ingest_site(survey, "D02", start="2021-06-29 12:00", end="2021-06-29 18:00")
remote = ingest_site(survey, "E08", start="2021-06-29 12:00", end="2021-06-29 18:00")
tf = process_station(local, "D02", remote, "E08", out_dir=survey.workspace / "tf")
```


## Instruments

`mtproc.instruments` knows three recorders, each read by its own mt-io reader
and archived under that reader's channel names:

| `instrument:` | recorder | files a site folder holds | reader, archive channels |
|---|---|---|---|
| `lemi423` | LEMI-423 broadband | `<unix epoch>.B423` (90 min each) | `mt_io.lemi.lemi423`: hx hy hz ex ey (counts; LEMI-120 coil response and `h_scale` added at ingest) |
| `lemi424` | LEMI-424 long period, 1 Hz | `YYYYMMDDhhmm.txt` (daily) + a `.inf` | `mt_io.lemi.lemi424`: bx by bz e1 e2 e3 e4 (nT; the electrics as recorded, mV, though mt-io labels them mV/km, no dipole length applied) |
| `edl` | Earth Data PR6-24 (UoA interface) | `{station}YYMMDDhhmmss.{BX,BY,BZ,EX,EY}` in day folders + `config/recorder.ini` | `mt_io.uoa.pr624`: hx hy hz ex ey (microvolts; the reader's Bartington, Bz-divider, signed-dipole and x10 terminal-box chain; rate from recorder.ini) |

**Detection.** A folder under `data_root` is a site when it holds any of
those files anywhere below it (`detect_instrument`, one walk): B423 files ->
lemi423; a 12-digit `.txt` whose first line has the LEMI-424's 24 (or 16)
fields -> lemi424; `recorder.ini` or EDL channel files -> edl. The survey's
own instrument is preferred, so an existing LEMI-423 survey finds exactly the
sites it always did. **The per-site key:** `Survey.instrument_of(site)` is
the site's own `instrument:` if it has one, else what its folder holds, else
the survey's top-level `instrument:`. `scripts/new_survey.py` writes a site's
`instrument:` (and its recorder's default `channels:` preset, since the
survey default's names are not its reader's) only when it differs from the
survey's. `channels:` and `filters.yaml` lists use the reader's names
(`channels: [e1, e2, e3, e4, bx, by, bz]` on a LEMI-424).

**Ingest.** `ingest_site` reads LEMI-423 exactly as before (archives
byte-identical; `calibration_fn`, `h_scale`, the reversed-dipole flip and
`replace` are LEMI-423 keys) and the others through
`mtproc.instruments.read_run` (EDL: the site's dipole lengths and, with
`flip_reversed_dipoles`, its azimuths go to the reader, whose dipole filter
carries the sign). `max_run_files` caps LEMI-423 runs only. One hour ingests
in about 1.4 s (LEMI-424) and 1.1 s (EDL). **Processing** a LEMI-424 site
needs aurora's electric-channel nomenclature (LEMI12/LEMI34) in
`mtproc.process`, not added yet; `timing_qc.py`, `psd_qc.py --before` and
`noise_psd.py` still read B423 files only. `build_stack.py` reads each
member's MTH5 archive (its `hx`/`hy`, so LEMI-423 and EDL archives, not a
LEMI-424's `bx`/`by`); a member without an archive has to be built first.

## The GUI

A desktop launcher and viewer over the scripts above and each survey's YAML,
with a site/window tree on the Time Series tab (2 h windows at 1000 Hz,
4 h at 500 Hz), live Spectra,
Spectrogram and Coherence views that compute only through `mtproc.timefreq` on
the loaded window, a Filter Data tab that previews the site's filter list on
a loaded window (raw behind filtered, time series and PSD) and drives
`<survey>/filters.yaml`, a
Process tab (rows of station and remote, window bar, queue buttons, options
and queue) that queues the scripts
above as subprocesses (Add to queue, then Run queue as a separate step;
its Engine combo, aurora or mantle, becomes `--engine mantle`, the queue
label carries "[mantle]" and, when the pair declares masks, `--no-masks`
goes with it and the status line says so),
a Build MTH5 button on the Time Series tab for a site with no archive yet,
a satellite basemap under the Process tab's site map, fetched when a survey
is opened, and a View EDIs tab drawn with mtpy-v2, which labels each product
by its sidecar's engine ("[aurora]", "[mantle]", "[mantle fine grid]") and,
for a MANTLE product, draws its verdict strip under the resistivity panels
from `<stem>.mantle_report.json` (one row per verdict word over the periods
it covers), shows the sidecar's verdict word counts and opens the report's
notes as plain text (`src/mtproc_gui/mantle_products.py`). **No product** (archive, transfer
function, EDI, report figure) is computed in the GUI, and no PNG is ever
displayed in it. Full detail: `src/mtproc_gui/README.md`.

```bash
python -m mtproc_gui surveys/<survey>/survey.yaml
```

Tests, each run on its own (no pytest runner wired up yet); the smoke test
needs an offscreen Qt platform and writes its screenshots to
`surveys/curnamona_cube/work/qc/gui_*.png` (gitignored — regenerate them by
running it):

```bash
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
QT_QPA_PLATFORM=offscreen python tests/process_tab_unit.py  # the Process tab's masks switch and the engine combo (mantle: --no-masks with --engine mantle, the status line)
python tests/campaign_unit.py        # campaign.py: plan, overlap rule, stacks, resume, dry-run counts, runner, filter check, masks signature, a MANTLE stage 3 config
python tests/windows_unit.py
python tests/segment_unit.py
python tests/psd_ladder_unit.py
python tests/survey_unit.py          # distance_km, Survey.timezone, the channel presets, instrument detection, derived and observatory sites
python tests/ingest_unit.py          # the raw/variant split (filters_hash, build_variant, old-layout), the LEMI-423 path, one real hour of LEMI-424 and EDL
python tests/noise_unit.py           # the filter kinds on synthetic arrays; ingest path == arrays path
python tests/filter_trial_unit.py    # scripts/filter_trial.py: line excess, floor, coherence and burst/step metrics on a synthetic window with a coherent pair and two lines; a notch removes its line and leaves the coherence; inputs unchanged; the figures and JSON written
python tests/virtual_unit.py         # synthetic remote from real tiny member archives: the plain stack byte-identical to before; coherence weights (dead coil -> 0, burst chunk down-weighted); streamed == single shot; missing archive, off-grid run, partial run
python tests/process_rr_cli_unit.py  # process_rr.py --dry-run, the estimator tweaks, run_stem, the sidecar, the quadrant window
python tests/engine_mantle_unit.py   # the MANTLE engine: options -> ProcessingConfig, levels_for, band pooling with the jackknife variance, to_tf round trip, the sidecar keys, --engine on the command line (skips when MANTLE is not installed)
python tests/decimate_unit.py        # decimate_site.py on a synthetic two-run LEMI-423 site: 100 s and 20 s sines within 0.5 % and 0.5 deg at 1 Hz, a 0.7 Hz sine gone, the calibration chain copied, starts on whole seconds, --force, the survey entry; process_rr.py at 1 Hz
python tests/basemap_unit.py         # fetch_basemap.py: warp, provider, zoom rule; network mocked
python tests/new_survey_unit.py      # new_survey.py on synthetic B423s, a mixed LEMI-423/424/EDL root, Curnamona
python tests/profile_unit.py         # scripts/profile_run.py: phases from a real process_rr log excerpt, nested marks, the psutil sampler on a sleep child; the trace stage's marker spans on a stub (and through viztracer when installed) and its tracemalloc diff table (`--stage trace`: viztracer + py-spy + tracemalloc passes of one windowed estimate, fork and stock aurora; dev tools viztracer, py-spy)
python tests/mth5_fork_unit.py       # the mth5 / mt-metadata forks (../mth5, ../mt-metadata, with ../mt-io, branch mtproc-fixes) on PYTHONPATH, the installed packages reported beside them: read-only opens, run id warning, no-harmonic band, to_runts/time_slice time against stock (while stock is installed); with ../mt-timeseries (src/) too, and against the installed mt_timeseries: the 10.00064 Hz and 1.5 Hz index, the RunTS station's channels (no auxiliary_default); skipped without the clones
python tests/aurora_fork_unit.py     # aurora fork 0.6.2+mtproc (installed, or the clone at ../aurora) against stock-0.6.2 fixtures: Z identity, config window masks, time and memory; with the fork installed, the clone's estimate compared with it; fixtures only without the fork
python tests/mtio_fork_unit.py       # mt-io fork (the clone at ../mt-io, or installed) on synthetic files: issues 6, 7, 8, 18, 19, 21; the installed mt-io reported check by check (stock 0.0.5 fails all six); skipped without the fork
python tests/orangebox_unit.py       # mt-io's Orange Box reader: the synthetic layout, the 10.00064 Hz rate kept, files that do not join refused; one real Stuart Shelf hour against the legacy converter (skipped without E:)
# (tests/instrument_samples.py cuts the one-hour LEMI-424 and EDL samples from the raw-data drives, read only)
```

New dependencies (`pyproject.toml`): `PySide6` and
`pyqtgraph` for the GUI itself, and `mtpy-v2` (2.1.4) for the View EDIs tab's
rho/phase and phase-tensor plots (induction arrows later) — which also drags
in `contextily` + `xyzservices` (reused by `scripts/fetch_basemap.py`'s tile
fetch), `geopandas`, `rasterio`, `pyproj`, `simpeg`, `bokeh` and `panel`.

## Status

- [x] LEMI-423 ingest -> MTH5 (contiguous B423 files merged into long runs, a
      new run at any file-spacing anomaly; per-survey `channels` list drops the
      unconnected hz; per-survey `flip_reversed_dipoles` says whether a 180/270
      field-sheet azimuth means a reversed pair — true at Curnamona, false at Burra)
- [x] Aurora single-station / remote-reference wrapper -> EDI, with a
      processing window and an automatic impedance-phase-quadrant check
- [x] Comparison plots against legacy lemimt EDIs
- [x] Validation vs lemimt on a clean Curnamona Cube pair: D02 RR E08 matches
      the merged lemimt EDI over 0.005-~3000 s (rho and phase, both modes)
      with the lemimt-style 60-band scheme
- [x] Burra (noisy) first results: Burra35 RR Burra54rr3 matches lemimt
      0.005-1 s and 15-1000 s on its good-Ex window; Burra57 matches 15-1000 s;
      the 0.3-15 s cathodic-protection band is the open problem
      (`surveys/burra/qc_notes.md`)
- [x] Timing QC before ingest (`scripts/timing_qc.py`): no clock errors found
      at the Burra "Behind" sites; the one 1 s event is a remote file-boundary slip
- [x] Noise toolbox, first steps (`mtproc.noise`, `mtproc.ingest`; declared per
      site in `<survey>/filters.yaml`, applied at ingest in the listed order,
      provenance written into the archive): `replace` (borrow a magnetic
      channel from another site, with that site's coil calibration — the field
      crews' "replace magnetics" for a dead coil), `notch` (50 Hz + harmonics,
      zero-phase) and `cp` (cathodic protection: stack every cycle at the
      declared period in 10-min windows and subtract the median cycle from
      every channel — no detection, no cutting). Never auto-detected —
      declared after looking at the QC figures.
- [x] Noise toolbox: `hp` and `lp` (zero-phase Butterworth), a
      `channels` list on `notch`, `mtproc.noise.apply_filters_arrays` (the one
      implementation; ingest delegates to it) and the Filter Data tab's
      live preview of the list on a loaded window.
- [ ] Noise toolbox, next: per-channel time masks, band schemes
- [ ] Band-placement experiment around mains: 50 Hz at band edge vs notched
      vs band centre (anchor option in bands.py), same data three ways
- [x] Stacked/synthetic remote references from multiple array sites — mean
      stack implemented and tested on D02 (found A07's dead hx in the process)
- [ ] Coherence-weighted stacking: per-member weights per time chunk and
      band group (0.1–1, 1–10, 10–100, 100–1000 s), then full per-band
      weighting at the Fourier-coefficient level; median stack as the
      robust baseline
- [x] Time-resolved coherence QC (`scripts/site_qc.py`, ported from the AusLAMP
      figures): whole-record overview, band coherence vs time, coherogram and
      spectrogram for Bx–Ey, By–Ex, Bx–By, Ex–Ey and the local-E vs remote-B
      pairs — the input for stack weights and time masks (next)
- [x] New-survey bootstrap from a raw folder (`scripts/new_survey.py`): B423
      headers -> `survey.yaml` via mt-io, `--site-table` merge, also reachable
      from the GUI's Metadata tab ("New survey...")
- [x] Channels recorded, per survey and per site: the presets in
      `mtproc.survey.CHANNEL_PRESETS` (LEMI-423: Ex Ey Bx By, + Bz,
      magnetics only, Bx By Bz; LEMI-424: E1-E4 Bx By Bz, E1 E2 Bx By Bz,
      Bx By Bz), `new_survey.py --channels` for the survey default, the
      Metadata tab's channels column for a site that differs
- [x] LEMI-424 and Earth Data PR6-24 (EDL) ingest and GUI (see
      "Instruments" above): the instrument detected per site folder,
      `instrument:` per site, the readers' own channel names in the archive
      and in every GUI view
- [x] Electric chain gain, EDL sites only (`electric_gain`):
      extra gain of the electric chain between the dipoles and the recorded
      values, beyond what the reader already models (the x10 terminal box) --
      hardwired at the field terminal junction box, declared from the field
      notes when the PR6-24's own configs were not kept (Stuart Shelf 2009:
      10.0), `new_survey.py --electric-gain` for the survey default, the
      Metadata tab's `electric_gain` column for a site that differs
- [ ] An `electric_pair` setting saying which two of a LEMI-424's e1-e4 are
      Ex and Ey (aurora's LEMI12/LEMI34 nomenclature in `mtproc.process`); the
      GUI meanwhile pairs the first two electrics, E1 and E2
- [x] Desktop GUI (`src/mtproc_gui`): PySide6 + pyqtgraph
      launcher-and-viewer over the scripts and per-survey YAML, with QC,
      filter, processing and EDI tabs — see "The GUI" above
- [ ] Cross-power editor: the GUI's Cross-powers tab. Every STFT window's
      cross-powers are computed once (`mtproc.crosspower.compute_windows`), then per base
      chunk (10, 5, 2 or 1 min) and per decimation level on groups of base
      chunks long enough for 4 windows and 32 degrees of freedom, regrouped
      instantly without reading the archives, a window inside a larger store
      rounded out to whole minutes; |Z|, phase, coherence, |H| and |E|
      against time and the polar plane; masks per window and band saved per
      site as UTC intervals in `<survey>/masks.yaml`, `process_rr.py`
      applying the station's and the remote's (Process tab "apply
      masks.yaml"). Still open: the stacked editor estimate
      (`stack_impedance`, a window-count-weighted jackknife from 5 groups)
      written as an EDI
- [ ] Burra in the GUI (93 sites, remotes filled per stage, `filters.yaml` for
      Burra35/57, timezone set — the config side is ready, untested in the GUI)
- [ ] EDL broadband (LEMI-120 coils on the PR6-24, `sensor_type="lemi120"`):
      only the Bartington long-period chain is wired
- [ ] Batch CLI
