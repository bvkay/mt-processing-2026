# Command line

This page lists the scripts of `scripts/` in the order of a survey, each
with its usage and what it reads and writes. Run one from the repository
folder as `python scripts/<name>.py ...` in the `bbmt-2026` environment.
The inter-site scripts are on [tensors.md](tensors.md) and the campaign
runner on [campaigns.md](campaigns.md).

## The scripts at a glance

| step | script | what it does |
|---|---|---|
| Make a survey | `new_survey.py` | write `survey.yaml` from a folder of site folders |
|  | `site_table_to_yaml.py`, `burra_notes_to_yaml.py` | a field sheet into the `sites:` block |
|  | `site_table_from_notes.py` | a field-notes CSV into the site table `new_survey.py` reads |
|  | `match_reference_edis.py` | legacy EDIs into `reference_edis.yaml` |
|  | `declination.py` | each site's magnetic declination from the IGRF |
|  | `fetch_basemap.py` | the map background of the window's site map |
|  | `pidinst_lookup.py` | propose the instrument registry DOIs: see [instruments.md](instruments.md) |
| Check before ingest | `timing_qc.py` | file-boundary slips, clock offset against a remote, GPS status |
|  | `noise_psd.py` | a quick look at the raw noise |
| Ingest | `ingest_site.py` | the raw files of a site into its MTH5 archive, and its filtered variant |
|  | `phoenix_cal_convert.py` | Phoenix binary calibrations into JSON |
|  | `dc_level_check.py` | the raw DC level of every channel |
|  | `decimate_site.py` | a broadband site at 1 Hz |
|  | `fetch_observatory.py` | an INTERMAGNET observatory as a 1 Hz remote |
| Look at the noise and try filters | `site_qc.py` | the QC figures of a site's whole record |
|  | `psd_qc.py` | the whole-record PSD of each channel |
|  | `line_scan.py` | narrow spectral lines per hour |
|  | `filter_trial.py` | candidate filter chains on one window |
|  | `coherence_qc.py` | band-averaged coherence of a pair |
| Process | `process_rr.py` | the impedance and tipper of a site against a remote |
|  | `build_stack.py` | a stacked synthetic remote |
|  | `compare_unmerged.py` | an aurora EDI against lemimt's unmerged EDIs |
|  | `process_intersite.py` | the telluric or magnetic tensor between two sites: see [tensors.md](tensors.md) |
|  | `merge_tensor_bands.py` | one tensor over a Phoenix receiver's whole band: see [tensors.md](tensors.md) |
|  | `solve_datum.py` | one potential per site from the pair products: see [tensors.md](tensors.md) |
|  | `campaign.py` | a processing campaign over a line of sites: see [campaigns.md](campaigns.md) |
| Masks | `cluster_masks.py` | band masks of a coherent near-field source |
|  | `gate_masks.py` | masks by time of night and by bursts of the electric field |
|  | `retire_masks.py` | mask entries into the history file, and back |
| Merge and deliver | `merge_modes.py` | one EDI from two products of one pair |
|  | `deliver_as_laid.py` | the delivered EDI, each reversed electric line as laid |
| The notebook and the QC folder | `harvest_notes.py` | index and check a survey's processing notebook |
|  | `organise_qc.py` | sort the workspace's `qc/` folder by line and site |

The scripts folder also holds `bench_pipeline.py`, `diagonal_site.py`, `edl_unpack.py`, `h_azimuth.py`, `health_table.py`, `health_windows.py`, `line_noise_profile.py`, `merge_best.py`, `merge_windows.py`, `observatory_from_parquet.py`, `observatory_rot_h.py`, `profile_run.py`, `shared_centre_test.py`, `stretch_masks.py`. They have no entry on this
page; the docstring at the top of each one says what it does.

## Make a survey

### `new_survey.py`

```text
scripts/new_survey.py <data_root> --name NAME [--instrument auto|lemi423|lemi424|edl|phoenix] [--channels SET] [--timezone TZ] [--site-table CSV] [--out PATH] [--workspace DIR]
```

New survey: a folder of site folders -> `survey.yaml` (each site's instrument detected from its files, the most common written as `instrument:` unless `--instrument` names one, a site on another recorder given its own `instrument:` and that recorder's default `channels:`; each LEMI-423 site's first B423 header via mt-io: position, serial, firmware, sample rate; a LEMI-424's `.inf` and first line, an EDL's `recorder.ini`; span from the file names; dipoles left to `defaults:`; `--site-table` merges a CSV/XLSX; `workspace:` is `<data_root>/work` unless `--workspace` says otherwise; `--channels` names the columns that had a sensor, a preset from `mt_workbench.survey.CHANNEL_PRESETS`, "Ex Ey Bx By" by default, "Ex Ey Bx By Bz", "Bx By (magnetics only)", "Bx By Bz", or a list such as `hx,hy`, written as `defaults: channels:`, and the summary prints each site's file columns beside it; also the GUI's Metadata tab "New survey...", whose channels column sets a site that differs).

### `site_table_to_yaml.py` and `burra_notes_to_yaml.py`

```text
scripts/site_table_to_yaml.py
scripts/burra_notes_to_yaml.py
```

Field sheet -> `sites:` block.

### `site_table_from_notes.py`

```text
scripts/site_table_from_notes.py <notes.csv> <site_table.csv> [--timezone TZ] [--data-root DIR]
```

UoA field-notes CSV (Stuart Shelf 2009 layout: header rows, then `Station`, `Latitude_dd`, `X_dip_length` = Ex, `Y_dip_length` = Ey, orientations, local deploy/recover times ...) -> the site table `new_survey.py --site-table` reads (position, dipoles, azimuths, `timezone`, and notes carrying serials, sensor, rate, gain, the times in local and UTC and the field remarks; a typed UTC that disagrees with the local time, and a blank dipole length, are named).

- `--data-root` lists stations with no folder and folders with no station

### `match_reference_edis.py`

```text
scripts/match_reference_edis.py <edi_dir> <survey.yaml>
```

Legacy EDIs -> `reference_edis.yaml`.

### `declination.py`

```text
scripts/declination.py <survey.yaml> [SITE ...] [--dry-run|--write|--check SITE=DEG ...] [--tol DEG]
scripts/declination.py --self-test
```

Each site's magnetic declination in survey.yaml from the IGRF (ppigrf, its newest coefficients, IGRF-14): at the site's latitude, longitude and elevation and the midpoint of its `start`/`end`, as `declination` (degrees east of geographic north, 2 decimals), `declination_model` and `declination_epoch` (decimal year).

- a dry run prints the table
- `--write` edits survey.yaml by lines (existing keys replaced in place, missing ones added after the entry's last line, every other line unchanged, refused when the parsed result differs in anything else)
- `--check SITE=DEG ...` compares with values given (exit 1 beyond `--tol`, 0.05 deg)
- `--self-test` checks the NOAA calculator's values at 31.87 N 7.93 W (-1.07) and 33.0 N 3.4 W (+0.20), with a sign-flipped control that must fail

### `fetch_basemap.py`

```text
scripts/fetch_basemap.py <survey.yaml> [--provider NAME] [--margin F] [--zoom N|auto]
```

Map background for the GUI's site map, fetched once while online (Esri.WorldImagery by default: imagery, no place names; contextily's zoom + 3, longer side at most 8000 px; warped to lon/lat; `<workspace>/basemap.png` + `.json`).

- the GUI runs it itself when a survey is opened without `basemap.json`

## Check before ingest

### `timing_qc.py`

```text
scripts/timing_qc.py <survey.yaml> <local> <remote>
```

Before ingest: file-boundary slips, clock offset vs remote, GPS status.

### `noise_psd.py`

```text
scripts/noise_psd.py <survey.yaml> <site>
```

Quick look at raw noise (Welch PSD, mains zoom).

## Ingest

### `ingest_site.py`

```text
scripts/ingest_site.py <survey.yaml> <site> [<site> ...] [--raw | --variant] [--max-run-files N] [--force] [--parallel N]
scripts/ingest_site.py <survey.yaml> --all [...]
```

Ingest a site's raw archive into `<workspace>/mth5/<site>.h5` (its run length as `process_rr.py`'s), then build its filtered variant too if it declares any (`--raw` for the archive alone, `--variant` for the variant alone).

- refuses to rebuild an existing raw archive or an already-current variant without `--force`
- the raw step records the raw DC level of each channel and run in the run comments (`mt_workbench.dclevel`: the median in counts and the share of samples at a rail on a subsample of at most an hour, and a verdict over the site's channel runs, `open input?` above 1e9 counts or 30 times the typical level of the channel type, `saturated?` above 1 % at a rail, else `ok`) and prints one line per flagged channel run after `archive:`, e.g. `C05 sr1000_0001 ey: median 1.60e9 counts, open input?`
- several sites, or `--all` (every site of survey.yaml with a raw data folder, the others listed as skipped), make a batch that keeps existing archives and current variants, builds `--parallel N` sites at once, each in its own process logged to `<workspace>/logs/ingest_<site>.log` (default 1: one after another on the console), goes on past a failed site and ends with a table of each site's archive, variant, seconds and status (built, kept, failed with its error), exit 1 when a site failed
- a site whose survey.yaml entry sets `swap_h: true` has hx and hy exchanged in its raw archive, one that sets `flip_h: [hy]` has that coil's samples negated (after any exchange), and an electric-only site whose entry sets `h_from: <site>` takes that neighbour's hx and hy from its raw files (see "Ingest" in [instruments.md](instruments.md))
- also the GUI's Time Series tab "Build MTH5"

### `phoenix_cal_convert.py`

```text
scripts/phoenix_cal_convert.py <source> <out_dir> [--curve-from DIR] [--dry-run]
```

Phoenix binary calibrations (`<serial>_<epoch>.scal`, `<receiver>_<epoch>.rxcal`, from a folder, one file or a .zip read in place) -> EMpower's JSON form in a site's `calibration_dir` (`<name>.json`, with `converted_from`).

- an existing file is compared value by value and kept
- an `.rxcal`'s curve below its measured points comes from an EMpower `.rxcal.json` of the same receiver (`curve_below_records_from`; upstream issue 83)

### `dc_level_check.py`

```text
scripts/dc_level_check.py <survey.yaml> [SITE ...] [--rate HZ] [--threshold-counts N] [--ratio R] [--sample-seconds S] [--csv OUT.csv]
```

The raw DC level of every channel of a survey's archives, per run: subsampled median and MAD in counts, the share of samples at a rail, the ratio to the typical level of its channel type, and a verdict (`open input?` when the level exceeds `--threshold-counts`, 1e9, or `--ratio`, 30, times the typical; `saturated?` above 1 % at a rail; else `ok`).

- an electric input that is open or of very high impedance sits at the logger's bias level (C05 ey and C13 ey of the Morocco survey at 1.60e9 counts)
- derived and observatory sites are skipped
- archives opened read-only without a lock
- the measure and verdict are `mt_workbench.dclevel`'s, which the ingest also records per site in each archive's run comments (the GUI's Metadata tab shows that record), and the script classifies every site it checks together

### `decimate_site.py`

```text
scripts/decimate_site.py <survey.yaml> <site> [--rate 1] [--force] [--min-free-gb G]
```

A broadband site at 1 Hz for an observatory remote: the site's processing archive (its filtered variant when it declares filters) decimated run by run, one channel at a time, through zero-phase FIR stages of at most 10 (scipy.signal.decimate, the filter of `mt_workbench.timefreq`; 11.1 s dropped at each run end, samples on whole UTC seconds) into `<workspace>/mth5/<site>L.h5`, station `<site>L` with the source's runs, channel metadata and calibration chains, and a derived-site entry `<site>L: {derived_from: <site>, sample_rate: 1.0, ...}` in survey.yaml.

- an existing archive is kept without `--force`
- `process_rr.py <survey.yaml> <site>L <CODE>` then processes it at 1 Hz (bands from 4 s; a remote at another rate is refused)

### `fetch_observatory.py`

```text
scripts/fetch_observatory.py <survey.yaml> <IAGA code> [start] [end] [--cache DIR] [--max-gap S] [--dry-run]
```

INTERMAGNET observatory as a 1 Hz remote for long periods (`mt_workbench.observatory`, ported from the AusLAMP processing): one-second X Y Z from the BGS GIN, best available, one request per UTC day into a day cache (`<workspace>/observatory/<CODE>/<year>/<CODE>_<date>.sec.gz`, the served IAGA-2002 text; a re-run fetches nothing cached), then `<workspace>/mth5/<CODE>.h5` (hx = X north, hy = Y east, hz = Z down, nT, no filters; gaps up to `--max-gap` s filled, one run per longer gap) and a `<CODE>: {instrument: intermagnet, ...}` site entry in survey.yaml.

- start/end default to the survey's site span
- exit 1 when offline
- Aurora pairs it only with a 1 Hz local archive (no mixed sample rates)

## Look at the noise and try filters

### `site_qc.py`

```text
scripts/site_qc.py <survey.yaml> <site> [--remote R]
```

Per-site QC set: overview, band coherence vs time, coherogram, spectrogram.

### `psd_qc.py`

```text
scripts/psd_qc.py <survey.yaml> <site> [--remote R] [--before]
```

Whole-record PSD per channel from the archive, remote overlaid, lines marked, before/after filters.

### `line_scan.py`

```text
scripts/line_scan.py <survey.yaml> [SITE ...] [--hours-step 1] [--fmin 5] [--fmax 500] [--min-db 6] [--channels hx hy ex ey]
```

Narrow spectral lines per hour (grid-wide interharmonic combs, mains, drop-outs), for declaring a notch's `extra:` lines by hand: table + figure per site, summary across sites.

### `filter_trial.py`

```text
scripts/filter_trial.py <survey.yaml> <site> <start> <end> [--chain LABEL=FILE.yaml ...] [--declared] [--remote NAME] [--lines] [--out DIR]
```

Try candidate filter chains on one window of a site's raw archive before declaring them (the command-line form of the Filter Data tab's preview): each chain from a YAML file in `filters.yaml` syntax, `--declared` adds the site's current list.

- writes per chain, under `<workspace>/qc/filter_trials/<site>/`, a 5-500 Hz PSD per channel with the evaluated lines marked plus the full-band ladder, the time series with a 20 s zoom on the largest change, the band coherence of ey-hx and ex-hy (and of the remote pairs with `--remote`), and a metrics JSON: line excess before/after, the floor between lines, coherence band means, burst and step fractions
- `--lines` evaluates the site's line-scan lines too

### `coherence_qc.py`

```text
scripts/coherence_qc.py <survey.yaml> <local> <remote> [--stack S]
```

Band-averaged coherence on the processing bands.

## Process

### `process_rr.py`

```text
scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end] [--window-samples N] [--min-bin N] [--min-band-windows N] [--engine aurora|mantle] [--mantle-max-hours H] [--masks|--no-masks] [--mask-origins LIST] [--mask-scope role|union]
```

Ingest both sites, remote-reference TF, overlay on lemimt (advanced: `--taper`, `--overlap`, `--no-prewhiten`, `--r0` ... on every decimation level; the band layout: `--window-samples N` sets the FFT window of every level, `--min-bin N` moves the level boundaries so every decimated level starts at the first band edge at or above harmonic N (`--min-bin 0`: the layout's own, over the survey's `min_bin:`), both keeping every band's period, recorded as `window`, `min_bin` and `lowest_harmonic` in the sidecar; a period whose band rests on fewer than `--min-band-windows N` STFT windows (survey.yaml `processing: min_band_windows`, else 2: a band of one window) is not written, the periods removed recorded in the sidecar's `dropped_periods` (`n`, `periods_s`, `min_band_windows`), and a Z or tipper row with a zero or non-finite error is written as not estimated (EMPTY) at that period, the period going only when no row is left, each with a warning).

- writes `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>].edi` (the stamp is when the run started, local time, so re-running the same pair and window never overwrites an earlier EDI) plus the matching `.xml` (EMTF XML) and `.h5` (a standalone MTH5 file holding the TF), the `_vs_lemimt.png` and a `.json` sidecar of everything about the run (timing, archives, band scheme, tweaks, declared filters, argv, the phase-quadrant verdict, package versions)
- `--engine mantle` estimates with MANTLE (`mt_workbench.engine_mantle`: the same archives and window through MANTLE's MTH5 reader, its robust remote-reference cascade with jackknife error bars, the EDI pooled onto the same band scheme, plus MANTLE's fine-grid EDI and report JSON beside it; the sidecar gains `engine`, `engine_version`, `engine_config`, `mantle_report`, `mantle_fine_edi`; the aurora estimator flags, `--min-band-windows` and masks are refused with it, and its sidecar records `min_band_windows` and `dropped_periods` as null; MANTLE holds the window in memory and refuses one longer than `--mantle-max-hours` (24 h by default, recorded in `engine_config.options.max_hours`), and a limit above 24 h logs the window's expected peak, about 1.35 GB per hour at 1000 Hz; `--mantle-window clip` takes instead the longest span both archives' runs cover inside the window, its first `--mantle-max-hours` hours when longer, printed as `mantle.window_used` (a dry run too) and recorded in the sidecar's `window` and `window_clipped`: null, or `{requested_hours, used_hours, reason}` with reason `cap`, `gap` or `cap and gap`; aurora refuses the option)
- Masks are applied by role: the local's masks.yaml entries of `scope: local` or `both` (an entry without the key is `scope: local`) and the remote's of `scope: both` or `remote`, `--mask-scope union` applies every entry of both sites
- an entry's optional `channels` narrows it: of the remote, an entry naming neither hx nor hy is left out, and of the local, an entry naming only ex, ey or hz leaves out those TF rows alone, aurora running once per distinct set of entries by row and the rows merged into one TF before the EDI (the base run, with the fewest entries, gives the rest)
- the sidecar records the rule, the counts applied from each site and left out (`mask_scope`, `mask_counts`) and the runs (`channel_runs`)

### `build_stack.py`

```text
scripts/build_stack.py <survey.yaml> <name> <start> <end> <member>... [--weighting none|coherence] [--check]
scripts/build_stack.py <survey.yaml> --recipe NAME [--overwrite] [--check]
```

Stacked synthetic remote from concurrent sites (each member read via `processing_archive`, its filtered variant if it declares any, else its raw archive, exactly as `process_rr.py` would read it; streamed in 10-minute chunks).

- `--recipe NAME` builds a time recipe of the survey's `stacks.yaml` (the GUI's Stacks tab writes it; a band recipe is refused, `process_intersite.py --stack` forms it) and records the recipe's name, hash and text and each member's archive identity in the archive
- an archive that answers its recipe is reused, a stale one exits 2 unless `--overwrite`, which builds in `<workspace>/mth5/.build_<pid>/` and replaces `NAME.h5` only after the build is checked
- an existing `NAME.h5` built without a recipe exits 2 even with `--overwrite`

### `compare_unmerged.py`

```text
scripts/compare_unmerged.py <aurora.edi> <unmerged_dir> <site> [--remote NAME] [--out PNG] [--title TEXT]
```

aurora EDI vs every one of lemimt's unmerged per-rate/per-chunk EDIs for a site (e.g. Morocco Atlas Line D): rho/phase overlay by rate plus a per-rate median-difference table.

## Masks

### `cluster_masks.py`

```text
scripts/cluster_masks.py <survey.yaml> <local> <remote> [start] [end] [--component yx|xy|both] [--chunk-s S] [--min-separation DEG] [--min-earth-fraction F] [--min-coherence C] [--max-source-phase DEG] [--dilate N] [--out FILE.yaml] [--write] [--figures]
```

Band masks of a coherent near-field source from the Cross-powers tab's chunk impedances: per band, the groups of the pair's store (the overlap, or [start, end); `--chunk-s`, 600 s by default, 60 s recommended) with enough windows and a coherence of at least `--min-coherence` (0.5) are split by 2-means in the (log10 |Z|, phase) plane (yx plus 180 deg).

- a split is accepted when the cluster farther from 0 deg sits at a physical phase (the Earth's), the other lies within `--max-source-phase` (30 deg) of 0 deg, the median phases differ by at least `--min-separation` (20 deg) and by more than twice the pooled MAD, and the Earth holds at least `--min-earth-fraction` (0.2) of at least 30 groups
- the source cluster's groups, widened by `--dilate N` groups either side (2 recommended), get one band mask per run, found_by `cluster`, scope `local`
- prints the per-band table and the usable yx/xy range of the stacked impedance with no masks, the cluster masks and the site's other masks
- `--out` writes a masks.yaml-style file, `--write` replaces the site's earlier cluster masks in masks.yaml and keeps every other entry, `--figures` writes a scatter per band, a summary figure and a JSON under `<workspace>/qc/cluster_masks/<local>_rr-<remote>/`

### `gate_masks.py`

```text
scripts/gate_masks.py <survey.yaml> <site> [--night [HH:MM-HH:MM]] [--gate] [--k K] [--m S] [--out FILE.yaml] [--write] [--figure]
```

All-band masks by time of night and by bursts of the local E: `--night [HH:MM-HH:MM]` masks everything outside that local window (survey.yaml `timezone:`, 01:00-05:00 by default) on every day of the site's record, found_by `night`.

- `--gate` masks the bursts of the site's 1 Hz E (its derived `<site>L` archive: |first difference| of ex and ey over its record median, the 30 s running mean of the larger above `--k` (3) times its record median, widened by `--m` (60) s either side), found_by `gate`
- both scope `local`
- `--write` replaces only the site's entries of that origin
- `process_rr.py --mask-origins night` or `night,gate` then processes those selections

### `retire_masks.py`

```text
scripts/retire_masks.py <survey.yaml> <site> [--found-by LIST] [--scope LIST] [--bands all|limited] [--reason-contains TEXT] [--before ISO] [--after ISO] [--overlapping ISO..ISO] [--restore] --why TEXT [--dry-run]
```

Move a site's masks.yaml entries into `masks_history.yaml` beside it (each keeping its keys, with `retired: {on, why}`) or back with `--restore`, so no declaration is lost: the selectors are AND-ed (`--found-by`, `--scope`, `--bands all|limited`, `--reason-contains`, `--before`, `--after`, `--overlapping a..b`), each selected entry is printed on one line with the counts before and after, `--dry-run` moves nothing, exit 2 when nothing matches.

- both files are replaced atomically (`mt_workbench.masks.retire_masks`, `restore_masks`)

## Merge and deliver

### `merge_modes.py`

```text
scripts/merge_modes.py OUT.edi --xy A.edi --yx B.edi [--tag TAG] [--force]
```

One EDI from two products of the same pair when one electric channel is usable over the whole record and the other only over a window: the x row (Zxx, Zxy, errors) and the tipper from `--xy`, the y row (Zyx, Zyy, errors) from `--yx` interpolated in log period onto the `--xy` periods (NaN outside `--yx`'s range, stored as EMPTY and read back as 0), `--xy`'s station metadata and frame, `OUT.xml` and `OUT.h5` beside the EDI, and a sidecar naming both sources.

- exit 2 when the stations or the sidecars' remotes differ unless `--force`
- `merge_files` does the same from Python (campaign.py's `windows:` merges)

### `deliver_as_laid.py`

```text
scripts/deliver_as_laid.py <survey.yaml> <in.edi> <out.edi> [--site SITE] [--check]
```

A delivered EDI with each measured-reversed electric line written as laid: for each line the site's survey.yaml entry declares reversed (`azimuth_ex: 180` or `azimuth_ey: 270` under `flip_reversed_dipoles: true`; the site is the DATAID unless `--site`, a derived site read through its parent) the line's Z row is negated (Zxx, Zxy or Zyx, Zyy, real and imaginary parts; the errors, the other row, the tipper and the periods as read), its EMEAS line states AZM=180.00 or 270.00 (its electrode ends exchanged where it has any), and an INFO processing parameter `mt_workbench.as_laid_ex` or `_ey` says the row is the field as measured on the reversed dipole (a reader assuming north and east sees it 180 deg out, one applying AZM recovers the tensor) and quotes the measurement from the site's `notes:`.

- written as merge_best writes its EDI (`products.write_edi`, then `patch_edi_text`), the processing-parameter and measurement lines kept from the input's text, with `OUT.as_laid.json` beside it (the site, the input's and output's sha256, the lines and rows, AZM before and after, the INFO lines, every other header line the writer changed)
- applied once, at delivery, never to an intermediate product
- a site with no reversed line is re-written with nothing transformed
- refused (exit 2, nothing written): `swap_e`, an electric azimuth neither nominal nor reversed, a reversed azimuth under `flip_reversed_dipoles: false`, a site without its own entry, a file already written as laid
- `--check` applies the transform to the output again and compares the result with the input exactly (periods, Z, errors, tipper; PASS, or FAIL naming the first differing element, exit 1)

## The notebook and the QC folder

### `harvest_notes.py`

```text
scripts/harvest_notes.py <survey.yaml> [--notes DIR] [--reports DIR] [--journals DIR ...] [--no-index]
```

A survey's processing notebook (`surveys/<survey>/notes/`: what was tried per method and per site, the numbers, the verdict and why, each claim with its source) indexed and checked against the saved reports in `<workspace>/qc/reports/`: writes `notes/index.md` (every report with the notes that cite it) and `manifest.csv`.

- `--journals DIR ...` first copies new results from workflow journals (`journal.jsonl`) into the reports folder as `<date>_<workflow>_<label>.json`
- exit 1 when a report is cited by no note, a path cited in a note does not exist, or an `r: <file>` citation names no saved report

### `organise_qc.py`

```text
scripts/organise_qc.py <survey.yaml> [--qc DIR] [--notes DIR] [--apply]
```

A survey's `<workspace>/qc/` folder sorted by line and site: an item whose name starts with a survey.yaml site goes to `qc/<line>/<site>/` (a derived or renamed site such as `B01L` or `C21new` under its parent, `STK_<site>` stacks under the site they serve, the R remotes with line B), line-level items (`line<X>_*`, `line_noise_<X>*`, `lines_<site>` figures, `filters_line<X>*`) to `qc/<line>/line/`, the survey folders (merge_products, reports, cluster_masks, filter_trials, north_recovery, night_ss) to `qc/survey/<topic>/`, anything else to `qc/unsorted/`.

- `lineC_fx` is split by site, items inside an existing line folder are sorted the same way, and `lines_<site>.csv` and `lines_summary.txt` stay at the top (filter_trial.py --lines reads them there)
- a dry run by default (the plan, counts per destination folder, the unsorted items, the citations that would change)
- `--apply` moves (never overwriting), appends each move to `qc/_moves.csv` (old, new, date) and rewrites every recorded old path in `notes/**/*.md` and in the saved reports
- a second `--apply` moves nothing
- `tf/`, `mth5/` and `campaign/` are never touched

## From Python: a survey in four lines

A survey is a YAML file pointing at the folder that holds the raw site
directories. **Site name = folder name**; a site needs settings of its own only
for overrides (dipole lengths/azimuths come from the field
spreadsheet via `scripts/site_table_to_yaml.py`).

```python
from mt_workbench.survey import Survey
from mt_workbench.ingest import ingest_site
from mt_workbench.process import process_station

survey = Survey.from_yaml("surveys/curnamona_cube/survey.yaml")
local  = ingest_site(survey, "D02", start="2021-06-29 12:00", end="2021-06-29 18:00")
remote = ingest_site(survey, "E08", start="2021-06-29 12:00", end="2021-06-29 18:00")
tf = process_station(local, "D02", remote, "E08", out_dir=survey.workspace / "tf")
```
