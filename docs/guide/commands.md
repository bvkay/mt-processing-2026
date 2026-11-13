# Command line

This page lists the scripts of `scripts/` by the step of a survey they
serve, with the usage of each, what it writes and what to watch for. Run
one from the repository folder as `python scripts/<name>.py ...` in the
`bbmt-2026` environment. A script with options lists them with `--help`.
Below, a value in an option's place is its default, and a word in capitals
stands for a value to give.

## Make a survey

- `new_survey.py <data_root> --name NAME [--instrument auto] [--channels SET] [--site-table FILE] [--timezone Australia/Adelaide] [--clock-timezone TZ] [--electric-gain G] [--calibration FILE] [--workspace <data_root>/work] [--out surveys/<name>/survey.yaml] [--force]`:
  writes survey.yaml from a folder of site folders. The recorder files hold
  no dipole lengths or azimuths: every site takes those of `defaults:`
  until `--site-table` (a CSV or XLSX with a `site` column) or the Metadata
  tab sets them. `--channels` names the columns that had a sensor, such as
  `hx,hy`. Keep `NAME` to 30 characters: mth5 cuts a longer survey id in
  its summaries (upstream 550). A new folder under `surveys/` is ignored
  by git.
- `site_table_from_notes.py <notes.csv> <site_table.csv> [--timezone TZ] [--data-root DIR]`:
  a field-notes CSV into that site table.
- `site_table_to_yaml.py <field_sheet.xlsx> <survey.yaml>`: a field-sheet
  spreadsheet into the `sites:` block. It writes the whole file again:
  comments, and sites not in the sheet, are lost.
- `burra_notes_to_yaml.py [survey.yaml]`: the same for the Burra survey's
  own sheets.
- `match_reference_edis.py <edi_dir> <survey.yaml>`: matches earlier EDIs to
  the sites, as `reference_edis.yaml`, for the comparison figures.
- `declination.py <survey.yaml> [SITE ...] [--dry-run | --write | --check SITE=DEG ... | --self-test] [--tol 0.05]`:
  prints each site's declination from the IGRF; `--write` sets it in
  survey.yaml. It is recorded with every product and never applied:
  [products.md](products.md).
- `fetch_basemap.py <survey.yaml> [--provider NAME] [--margin 0.15] [--zoom auto]`:
  the background of the window's site map. The window runs it when a
  survey has none.
- `pidinst_lookup.py <survey.yaml> [--site SITE ...] [--write] [--responses DIR]`:
  proposes the instrument registry DOIs: [instruments.md](instruments.md).

## Check before ingest

Both read LEMI-423 files.

- `timing_qc.py <survey.yaml> <local> <remote> [--files 6] [--out PNG]`:
  file-start spacing, the clock offset against the remote, and GPS lock.
  Exit 1 when the offset is over 50 ms: a clock error no later step
  repairs.
- `noise_psd.py <survey.yaml> <site> [out.png]`: the raw spectrum of one
  file, with a zoom on the mains lines.

## Ingest

- `ingest_site.py <survey.yaml> <site> [<site> ...] [--all] [--raw | --variant] [--force] [--parallel 1] [--max-run-files 34]`:
  writes `<workspace>/mth5/<site>.h5`, the raw archive of the whole
  deployment, then the filtered variant when `filters.yaml` declares filters
  for the site ([products.md](products.md)). "Build MTH5" on the Time Series
  tab runs it. Without `--force` an existing raw archive and a current
  variant are kept: the site's products were made from them. `--all` takes
  every site with a raw data folder; a batch goes on past a failed site,
  then exits 1. The keys of survey.yaml that change what it writes are on
  [instruments.md](instruments.md).
- `phoenix_cal_convert.py <source> <out_dir> [--curve-from DIR] [--dry-run]`:
  Phoenix binary calibrations (`.scal`, `.rxcal`) into the JSON the readers
  take. A receiver needs an EMpower `.rxcal.json` of its own in
  `--curve-from` (default `<out_dir>`). An existing output is never
  replaced.
- `dc_level_check.py <survey.yaml> [SITE ...] [--rate HZ] [--threshold-counts 1e9] [--ratio 30] [--sample-seconds 3600] [--csv OUT.csv]`:
  the raw DC level of every channel and run, with a verdict: `open input?`
  (the level of an electric input with no line on it), `saturated?` or
  `ok`. Ingest prints the same flags.
- `decimate_site.py <survey.yaml> <site> [--rate 1] [--force] [--min-free-gb G]`:
  a broadband site at 1 Hz, to pair with a 1 Hz remote: the derived site
  `<site>L`, whose bands start at 4 s.
- `fetch_observatory.py <survey.yaml> <IAGA code> [start] [end] [--cache DIR] [--max-gap 600] [--dry-run]`:
  an INTERMAGNET observatory as a 1 Hz remote for long periods, fetched
  from the BGS GIN and cached by day: the site `<CODE>`, with hx geographic
  north, hy geographic east and hz down, in nT.
- `observatory_from_parquet.py`: fills that cache from observatory data
  held as parquet.
- `observatory_rot_h.py`: with `--apply`, turns an observatory archive's hx
  and hy onto magnetic north in place, after a copy.
- `h_azimuth.py`: fluxgate sites: the sensor's azimuth from the recorded
  main field, and the `rot_h:` key that follows.
- `diagonal_site.py`: an EDL site with a noisy centre electrode: the dipole
  between its outer electrodes, as the derived site `<site>D`.
- `edl_unpack.py`: unpacks one PR6-24 site zip into a site folder.

`decimate_site.py` and `fetch_observatory.py` add their entry by writing
the `sites:` block of survey.yaml again: comments inside it are lost.

## Look at the noise

These read archives, so ingest first. Output goes to `<workspace>/qc/`.

- `site_qc.py <survey.yaml> <site> [--remote R] [--win 20] [--step 10] [--smooth HOURS] [--out-dir DIR] [--assert-dead-band]`:
  four figures of the whole record: overview, band coherence, coherogram
  and spectrogram. Read the CHECK lines it prints.
- `psd_qc.py <survey.yaml> <site> [--remote R] [--before] [--out PNG]`: the
  whole-record spectrum of each channel; `--before` overlays the spectrum
  before the declared filters.
- `line_scan.py <survey.yaml> [SITE ...] [--hours-step 1] [--fmin 5] [--fmax 500] [--min-db 6] [--channels hx hy ex ey]`:
  narrow spectral lines hour by hour, for a notch's `extra:` lines.
- `filter_trial.py <survey.yaml> <site> <start> <end> [--chain LABEL=FILE.yaml ...] [--declared] [--remote NAME] [--lines] [--out DIR]`:
  candidate filter chains (files in `filters.yaml` syntax) on one window of
  5 min to 3 h, before they are declared, as on the Filter Data tab.
- `coherence_qc.py <survey.yaml> <local> <remote> [--stack NAME] [--out PNG]`:
  coherence on the processing bands: local E with H, local with remote or
  stack magnetics.
- `line_noise_profile.py`: an hourly noise profile of a line, and whether
  its noise episodes are simultaneous between sites.
- `shared_centre_test.py`: EDL sites: whether a noisy centre electrode
  explains the two electric lines.
- `health_table.py`: per site and week, whether H, Ex and Ey are sound.
- `health_windows.py`: from that table, a processing window per site and
  mode, written beside survey.yaml for the `windows:` key of a campaign
  plan.

## Process

- [`process_rr.py`](#process_rrpy): the impedance and tipper of a site
  against a remote.
- [`build_stack.py`](#build_stackpy): a stacked remote.
- `compare_unmerged.py <aurora.edi> <unmerged_dir> <site> [--remote NAME] [--out PNG] [--title TEXT]`:
  an EDI against each of lemimt's unmerged EDIs of the site, as a figure.
- `process_intersite.py <survey.yaml> <local> <base> [start] [end] --kind telluric|magnetic --remote SITE [options]`:
  the telluric or magnetic tensor between two sites:
  [tensors.md](tensors.md).
- `merge_tensor_bands.py <bursts.json> <continuous.json> [--accept-disagreement] [--out-dir DIR]`:
  one tensor over a Phoenix receiver's whole band: [tensors.md](tensors.md).
- `solve_datum.py <survey.yaml> --pairs PAIRS.csv [--out DIR] [--scale-by-closure] [--leave-out-flag NAME ...] [--band LO-HI ...]`:
  one potential per site from the pair products: [tensors.md](tensors.md).
- `campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...] [--configs NAME[,NAME]] [--parallel N] [--max-runs N] [--allow-raw] [--dry-run] [--report]`:
  every remote, stack and option for a line of sites:
  [campaigns.md](campaigns.md).

### `process_rr.py`

```text
scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end] [--dry-run] [--tag TAG] [--no-filters]
    [--no-masks | --masks] [--mask-origins LIST] [--masks-file PATH] [--mask-scope role|union]
    [--min-period S] [--max-period S] [--per-decade N] [--notch HZ,HZ] [--window-samples N] [--min-bin N]
    [--taper hann] [--overlap PCT] [--overlap-long PCT] [--no-prewhiten] [--min-windows 0] [--min-band-windows N]
    [--max-iterations 10] [--redescending-iterations 2] [--r0 1.5] [--u0 2.8] [--tolerance 0.005]
    [--engine aurora|mantle] [--mantle-whiten none|diff] [--mantle-max-hours 24] [--mantle-window refuse|clip]
```

The remote is a site, a stack or an observatory. A missing archive is
ingested first, and a site that declares filters is read from its filtered
variant unless `--no-filters`. `--dry-run` prints what the run resolves to
and writes nothing.

**The processing window.** `start` and `end` (UTC, as `"2021-06-29 12:55"`)
limit what the estimate reads, to keep out a stretch where a channel had
failed. The archive always holds the whole deployment; without them the run
uses the whole overlap of the two sites.

**It writes** the EDI, XML, h5, sidecar and figure of
`<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>]` in `<workspace>/tf/`:
[products.md](products.md#product-names).

**Check after a run:**

- the log's phase-quadrant line. An ERROR that a mode is 180 deg out of
  quadrant means a channel has the wrong sign: declare a `flip` for the
  site on the Filter Data tab, or check `flip_reversed_dipoles`
  ([instruments.md](instruments.md)), rebuild the archive and run again;
- the periods not written: a band resting on fewer than
  `--min-band-windows` windows (default 2) is left out and listed in the
  sidecar's `dropped_periods`, and a row with a zero or non-finite error is
  written EMPTY;
- a warning that the site has no declination: run `declination.py --write`.

**Band and estimator options** stand in, for one run, for the survey's
`processing:` keys (`min_period`, `max_period`, `periods_per_decade`,
`notch_frequencies`, `window`, `min_bin`, `min_band_windows`, `overlap`,
`overlap_long`). Leave the band options alone for a product: every transfer
function is estimated over the full band. The overlap is 25 %, and 75 % on
levels whose window lasts over 600 s, where the errors come out about 1.8
times too small: `overlap_long: 25` gives honest ones.

**MANTLE.** `--engine mantle` estimates with MANTLE on the same archives
and window, held in memory (about 1.35 GB per hour at 1000 Hz). A window
over `--mantle-max-hours` or with a gap is refused unless `--mantle-window
clip`. The aurora estimator options, `--min-band-windows` and masks are
refused with it: run it with `--no-masks`.

**Masks.** A mask is an interval of a site that processing leaves out: an
entry of `<survey>/masks.yaml`, written on the Cross-powers tab or by the
scripts under [Masks](#masks), with `start`, `end` (UTC), `bands`, `reason`,
`found_by`, `scope` and, optionally, `channels`.

- `scope`: `local` (the default) applies when its site is the local of the
  pair, `remote` when it is the remote, `both` in either. So a mask of a
  site's electric noise leaves its windows in the pairs that use the site
  as a remote. `--mask-scope union` applies every entry of both sites.
- `channels`: an entry naming hx or hy, or none, removes its windows from
  every row; one naming only ex, ey or hz from those rows alone, and never
  when its site is the remote.
- `bands`: `all` cuts the time out; `[pmin_s, pmax_s]` removes the windows
  only from the bands centred in that range.
- `--mask-origins night,gate` applies only the entries with those
  `found_by` values, `--masks-file` reads the entries from another file,
  and `--no-masks` applies none.

**Refused** (exit 2, in a dry run too): a site with no entry in survey.yaml
(a stack excepted), a pair whose records share no time, and a remote at
another sample rate (decimate the local with `decimate_site.py` and process
`<site>L`).

### `build_stack.py`

```text
scripts/build_stack.py <survey.yaml> <name> <start> <end> <member> <member> ... [--weighting none|coherence] [--min-piece-h H] [--check]
scripts/build_stack.py <survey.yaml> --recipe NAME [--overwrite] [--check]
```

Averages hx and hy of concurrent sites into `<workspace>/mth5/<name>.h5`,
which `process_rr.py` takes as `<remote>`.

- `--check` prints each member's coherence with the mean of the others and
  writes nothing. Run it first: one dead coil spoils a plain mean, so leave
  out a member that sits near zero.
- `--weighting coherence` weights each member by that coherence.
- `--min-piece-h H` gives the stack one run per stretch of H hours or more
  in which every member records, so a member's gap costs that gap alone.
- `--recipe NAME` builds the time recipe NAME of `stacks.yaml`, which the
  Stacks tab writes. An archive that no longer answers its recipe is exit 2
  unless `--overwrite`; one built without a recipe is never replaced.

In the first form an existing `<name>.h5` is kept as it is: give a changed
stack a new name. Refused: a member with no archive, or whose coil response
differs in shape from the first member's. Members with no calibration give
a warning: the impedance is the same, its errors are not in physical units.

## Masks

What a mask is: [`process_rr.py`](#process_rrpy). In the first two scripts
`--out` writes the masks to a file laid out as masks.yaml, and `--write`
saves them into masks.yaml in place of the site's earlier entries of the
same origin.

- `cluster_masks.py <survey.yaml> <local> <remote> [start] [end] [--component yx|xy|both] [--chunk-s 60] [--min-coherence 0.5] [--max-source-phase 30] [--min-separation 20] [--min-earth-fraction 0.2] [--dilate 2] [--out FILE.yaml] [--write] [--figures]`:
  band masks of a coherent source near the site. In a band where the chunk
  impedances of the Cross-powers tab split into two clusters, the Earth's
  at a physical phase and the source's near 0 deg, the source's chunks are
  masked. It prints the usable period range with and without the masks.
- `gate_masks.py <survey.yaml> <site> [--night [01:00-05:00]] [--gate] [--k 3] [--m 60] [--out FILE.yaml] [--write] [--figure]`:
  all-band masks. `--night` keeps that window of local time (the survey's
  `timezone:`) each night and masks the rest. `--gate` masks the bursts of
  the electric field, read from the site's 1 Hz archive (`decimate_site.py`
  first). `process_rr.py --mask-origins night` then processes that
  selection alone.
- `retire_masks.py <survey.yaml> <site> [--found-by LIST] [--scope LIST] [--bands all|limited] [--reason-contains TEXT] [--before ISO] [--after ISO] [--overlapping ISO..ISO] [--restore] --why TEXT [--dry-run]`:
  a mask no longer wanted is kept, not deleted. The site's entries that
  match every selector given move from masks.yaml to `masks_history.yaml`
  beside it; `--restore` moves them back.
- `stretch_masks.py`: masks over the stretches where an electric line's
  hourly coherence with H is low, as a candidate file for `process_rr.py
  --masks-file`. Selecting hours by coherence can make a response out of
  noise: run its `--control` selections beside it.

## Merge and deliver

Each merge writes `OUT.xml`, `OUT.h5` and a sidecar `OUT.json` naming its
sources beside `OUT.edi`, keeps the frame of its first xy source and
applies no rotation. A period no source gives is written EMPTY, which
mt_metadata reads back as 0 with a zero error.

- `merge_modes.py OUT.edi --xy A.edi --yx B.edi [--tag TAG] [--force]`: for
  a site where one electric line is usable over the whole record and the
  other only over a window: the x row (Zxx, Zxy), the tipper and the
  periods from `--xy`, the y row (Zyx, Zyy) from `--yx`.
- `merge_best.py OUT.edi --recipe FILE --site SITE [--tag TAG] [--force] [--survey survey.yaml]`:
  the good period ranges of several products. The recipe lists, per site
  and part (`xy`, `yx`, optionally `tipper`), sources in order, each
  `{edi, pmin, pmax}`; a part takes the first source whose range covers
  the period. `--auto --candidates A.edi B.edi ... --propose FILE` proposes
  a recipe.
- `merge_windows.py`: two FFT window lengths of one site: the short-window
  product up to a crossover period, the long-window one above it.
- `deliver_as_laid.py <survey.yaml> <in.edi> <out.edi> [--site SITE] [--check] [--corrected]`:
  the delivered EDI of a site. A site with no reversed line is written
  unchanged, so run it for every site. Ingest negates
  a line that survey.yaml declares reversed (`azimuth_ex: 180` or
  `azimuth_ey: 270`), so every product has ex along 0 and ey along 90. Run
  this once, at delivery, never on a product that goes into a merge.
  - By default each reversed line is written as laid: its Z row negated and
    its EMEAS line stating AZM=180 or 270. Software that assumes north and
    east reads that row 180 deg out; software that applies AZM recovers the
    tensor. Deliver this form.
  - `--corrected` writes the other form: no row negated, AZM 0 and 90, and
    an INFO line naming each reversed line.
  - `--check` compares the output with the input: PASS, or FAIL and exit 1.
  - Refused (exit 2, nothing written), among others: a site with
    `swap_e: true`, an electric azimuth neither nominal nor reversed, an
    EDI already written as laid.

## The notebook and the QC folder

- `harvest_notes.py <survey.yaml> [--notes DIR] [--reports DIR] [--journals DIR ...] [--no-index]`:
  indexes a survey's processing notebook (`surveys/<survey>/notes/`)
  against the saved reports under `<workspace>/qc/`. Exit 1 when a report
  is cited by no note, or a note cites a path or report that does not
  exist.
- `organise_qc.py <survey.yaml> [--qc DIR] [--notes DIR] [--apply]`: sorts
  `<workspace>/qc/` into a folder per line and site. It prints the plan;
  `--apply` moves the items and updates the paths cited in the notes.
