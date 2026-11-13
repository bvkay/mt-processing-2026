# mt-workbench

Magnetotelluric (MT) processing for Adelaide Uni surveys recorded on
LEMI-423, LEMI-424 and Earth Data PR6-24 loggers and Phoenix MTU-5C/8A and MTU-5A receivers (see "Instruments" below),
built on the IAGA-DVI stack
([mt-io](https://github.com/kujaku11/mt-io), [mth5](https://github.com/IAGA-DVI-DataStandards/mth5),
[mt-metadata](https://github.com/IAGA-DVI-DataStandards/mt-metadata)) with
[aurora](https://github.com/simpeg/aurora) as the transfer-function engine.

Design rules, in order:

1. **Thin.** mt-workbench wraps the community packages; it does not re-implement them.
2. **Headless first.** Everything runs from a script or the command line; the
   desktop GUI (`src/mt_workbench/gui`, see "The GUI" below) calls the same scripts
   and computes no product of its own.
3. **Decisions are data.** Noise masks, band choices and remote-reference pairs
   live in per-survey YAML/JSON files, never buried in code or notebooks.

## Install

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

`environment.yml` creates `bbmt-2026` (Python 3.11) and installs this package
(`mt-workbench`, import name `mt_workbench`) editable; every dependency, the GUI's
included, is listed once, in `pyproject.toml`.

### The stack: the mtproc-fixes forks

mt-workbench runs on the `mtproc-fixes` branches of five forks, `github.com/bvkay/`
aurora, mth5, mt-io, mt-metadata and mt-timeseries, which carry the fixes
logged in `docs/upstream_issues.md`. `pyproject.toml` names them by git URL
(`mth5 @ git+https://github.com/bvkay/mth5@mtproc-fixes`, ...); all five branches are on
GitHub, so a plain install resolves them. The forks keep the names they had
before the workflow was renamed from mtproc to CRUST and from
CRUST to mt-workbench: branch `mtproc-fixes`, aurora version
`0.6.2+mtproc`. A local clone (a sibling of this repo) installs over the
package from GitHub, leaving every other dependency as it is:

```bash
pip install --no-deps ../mt-metadata ../mt-timeseries ../mt-io ../mth5 ../aurora
```

The `*_fork_unit.py` tests below check each fork (the clones, and whatever is
installed, reported side by side). mt-workbench no longer patches the stock
packages at runtime; the shims it used to install are retired, the forks fix
the same bugs at the source:

- mt-io (issues 1, 2, 6): the LEMI-120 coil chain of a LEMI-423 read with a
  `calibration_fn` (valid unit names, coil stage ahead of the linear stage)
  and four-digit LEMI-423 altitudes (`%Alt1060.0,m`), both once patched in
  `mt_workbench.ingest`;
- mth5 (issue 5): run summaries and kernel datasets open archives read-only,
  once forced in `mt_workbench.process`;
- mt-timeseries (issue 17): a RunTS station lists its channels, with no
  phantom `auxiliary_default`, once overridden in `mt_workbench.observatory`.

On stock packages these are bugs again: a LEMI-423 site with a
`calibration_fn` does not ingest (stock mt-io's coil response carries a unit
mt_metadata rejects), building a processing config fails while another
process (the GUI) holds an archive open and touches the archives'
modification times, a 10.00064 Hz Orange Box run is dated at 10 Hz, and an
observatory archive's station lists `auxiliary_default`.

## Layout

```
src/mt_workbench/      the package: survey.py, instruments.py, ingest.py, process.py,
                       compare.py, bands.py, qc.py, timefreq.py, virtual.py
src/mt_workbench/gui/  the desktop GUI: a launcher and viewer over scripts/ and
                       survey.yaml, no processing code of its own (see below and
                       src/mt_workbench/gui/README.md)
surveys/<name>/        one folder per survey: survey.yaml (config), reference_edis.yaml,
                       work/ (outputs, gitignored)
scripts/               the student-facing command line, one job each (see below)
tests/                 unit tests (no Qt) plus the GUI smoke test
```

## Command line (plain scripts a student runs)

| step | script |
|---|---|
| new survey: a folder of site folders -> `survey.yaml` (each site's instrument detected from its files, the most common written as `instrument:` unless `--instrument` names one, a site on another recorder given its own `instrument:` and that recorder's default `channels:`; each LEMI-423 site's first B423 header via mt-io: position, serial, firmware, sample rate; a LEMI-424's `.inf` and first line, an EDL's `recorder.ini`; span from the file names; dipoles left to `defaults:`; `--site-table` merges a CSV/XLSX; `workspace:` is `<data_root>/work` unless `--workspace` says otherwise; `--channels` names the columns that had a sensor, a preset from `mt_workbench.survey.CHANNEL_PRESETS`, "Ex Ey Bx By" by default, "Ex Ey Bx By Bz", "Bx By (magnetics only)", "Bx By Bz", or a list such as `hx,hy`, written as `defaults: channels:`, and the summary prints each site's file columns beside it; also the GUI's Metadata tab "New survey...", whose channels column sets a site that differs) | `scripts/new_survey.py <data_root> --name NAME [--instrument auto\|lemi423\|lemi424\|edl\|phoenix] [--channels SET] [--timezone TZ] [--site-table CSV] [--out PATH] [--workspace DIR]` |
| field sheet -> `sites:` block | `scripts/site_table_to_yaml.py`, `scripts/burra_notes_to_yaml.py` |
| UoA field-notes CSV (Stuart Shelf 2009 layout: header rows, then `Station`, `Latitude_dd`, `X_dip_length` = Ex, `Y_dip_length` = Ey, orientations, local deploy/recover times ...) -> the site table `new_survey.py --site-table` reads (position, dipoles, azimuths, `timezone`, and notes carrying serials, sensor, rate, gain, the times in local and UTC and the field remarks; a typed UTC that disagrees with the local time, and a blank dipole length, are named); `--data-root` lists stations with no folder and folders with no station | `scripts/site_table_from_notes.py <notes.csv> <site_table.csv> [--timezone TZ] [--data-root DIR]` |
| legacy EDIs -> `reference_edis.yaml` | `scripts/match_reference_edis.py <edi_dir> <survey.yaml>` |
| before ingest: file-boundary slips, clock offset vs remote, GPS status | `scripts/timing_qc.py <survey.yaml> <local> <remote>` |
| quick look at raw noise (Welch PSD, mains zoom) | `scripts/noise_psd.py <survey.yaml> <site>` |
| ingest a site's RAW archive into `<workspace>/mth5/<site>.h5` (its run length as `process_rr.py`'s), then build its filtered variant too if it declares any (`--raw` for the archive alone, `--variant` for the variant alone); refuses to rebuild an existing raw archive or an already-current variant without `--force`; the raw step records the raw DC level of each channel and run in the run comments (`mt_workbench.dclevel`: the median in counts and the share of samples at a rail on a subsample of at most an hour, and a verdict over the site's channel runs, `open input?` above 1e9 counts or 30 times the typical level of the channel type, `saturated?` above 1 % at a rail, else `ok`) and prints one line per flagged channel run after `archive:`, e.g. `C05 sr1000_0001 ey: median 1.60e9 counts, open input?`; several sites, or `--all` (every site of survey.yaml with a raw data folder, the others listed as skipped), make a batch that keeps existing archives and current variants, builds `--parallel N` sites at once, each in its own process logged to `<workspace>/logs/ingest_<site>.log` (default 1: one after another on the console), goes on past a failed site and ends with a table of each site's archive, variant, seconds and status (built, kept, failed with its error), exit 1 when a site failed; a site whose survey.yaml entry sets `swap_h: true` has hx and hy exchanged in its raw archive, one that sets `flip_h: [hy]` has that coil's samples negated (after any exchange), and an electric-only site whose entry sets `h_from: <site>` takes that neighbour's hx and hy from its raw files (see "Ingest." under "Instruments"); also the GUI's Time Series tab "Build MTH5" | `scripts/ingest_site.py <survey.yaml> <site> [<site> ...] [--raw \| --variant] [--max-run-files N] [--force] [--parallel N]`, `scripts/ingest_site.py <survey.yaml> --all [...]` |
| Phoenix binary calibrations (`<serial>_<epoch>.scal`, `<receiver>_<epoch>.rxcal`, from a folder, one file or a .zip read in place) -> EMpower's JSON form in a site's `calibration_dir` (`<name>.json`, with `converted_from`); an existing file is compared value by value and kept; an `.rxcal`'s curve below its measured points comes from an EMpower `.rxcal.json` of the same receiver (`curve_below_records_from`; upstream issue 83) | `scripts/phoenix_cal_convert.py <source> <out_dir> [--curve-from DIR] [--dry-run]` |
| ingest both sites, remote-reference TF, overlay on lemimt (advanced: `--taper`, `--overlap`, `--no-prewhiten`, `--r0` ... on every decimation level; the band layout: `--window-samples N` sets the FFT window of every level, `--min-bin N` moves the level boundaries so every decimated level starts at the first band edge at or above harmonic N (`--min-bin 0`: the layout's own, over the survey's `min_bin:`), both keeping every band's period, recorded as `window`, `min_bin` and `lowest_harmonic` in the sidecar; a period whose band rests on fewer than `--min-band-windows N` STFT windows (survey.yaml `processing: min_band_windows`, else 2: a band of one window) is not written, the periods removed recorded in the sidecar's `dropped_periods` (`n`, `periods_s`, `min_band_windows`), and a Z or T row with a zero or non-finite error is written as not estimated (EMPTY) at that period, the period going only when no row is left, each with a warning); writes `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>].edi` (the stamp is when the run started, local time, so re-running the same pair and window never overwrites an earlier EDI) plus the matching `.xml` (EMTF XML) and `.h5` (a standalone MTH5 file holding the TF), the `_vs_lemimt.png` and a `.json` sidecar of everything about the run (timing, archives, band scheme, tweaks, declared filters, argv, the phase-quadrant verdict, package versions); `--engine mantle` estimates with MANTLE (`mt_workbench.engine_mantle`: the same archives and window through MANTLE's MTH5 reader, its robust remote-reference cascade with jackknife error bars, the EDI pooled onto the same band scheme, plus MANTLE's fine-grid EDI and report JSON beside it; the sidecar gains `engine`, `engine_version`, `engine_config`, `mantle_report`, `mantle_fine_edi`; the aurora estimator flags, `--min-band-windows` and masks are refused with it, and its sidecar records `min_band_windows` and `dropped_periods` as null; MANTLE holds the window in memory and refuses one longer than `--mantle-max-hours` (24 h by default, recorded in `engine_config.options.max_hours`), and a limit above 24 h logs the window's expected peak, about 1.35 GB per hour at 1000 Hz; `--mantle-window clip` takes instead the longest span both archives' runs cover inside the window, its first `--mantle-max-hours` hours when longer, printed as `mantle.window_used` (a dry run too) and recorded in the sidecar's `window` and `window_clipped`: null, or `{requested_hours, used_hours, reason}` with reason `cap`, `gap` or `cap and gap`; aurora refuses the option). Masks are applied by role: the local's masks.yaml entries of `scope: local` or `both` (an entry without the key is `scope: local`) and the remote's of `scope: both` or `remote`, `--mask-scope union` applies every entry of both sites; an entry's optional `channels` narrows it: of the remote, an entry naming neither hx nor hy is left out, and of the local, an entry naming only ex, ey or hz leaves out those TF rows alone, aurora running once per distinct set of entries by row and the rows merged into one TF before the EDI (the base run, with the fewest entries, gives the rest); the sidecar records the rule, the counts applied from each site and left out (`mask_scope`, `mask_counts`) and the runs (`channel_runs`) | `scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end] [--window-samples N] [--min-bin N] [--min-band-windows N] [--engine aurora\|mantle] [--mantle-max-hours H] [--masks\|--no-masks] [--mask-origins LIST] [--mask-scope role\|union]` |
| aurora EDI vs every one of lemimt's unmerged per-rate/per-chunk EDIs for a site (e.g. Morocco Atlas Line D): rho/phase overlay by rate plus a per-rate median-difference table | `scripts/compare_unmerged.py <aurora.edi> <unmerged_dir> <site> [--remote NAME] [--out PNG] [--title TEXT]` |
| per-site QC set: overview, band coherence vs time, coherogram, spectrogram | `scripts/site_qc.py <survey.yaml> <site> [--remote R]` |
| whole-record PSD per channel from the archive, remote overlaid, lines marked, before/after filters | `scripts/psd_qc.py <survey.yaml> <site> [--remote R] [--before]` |
| narrow spectral lines per hour (grid-wide interharmonic combs, mains, drop-outs), for declaring a notch's `extra:` lines by hand: table + figure per site, summary across sites | `scripts/line_scan.py <survey.yaml> [SITE ...] [--hours-step 1] [--fmin 5] [--fmax 500] [--min-db 6] [--channels hx hy ex ey]` |
| try candidate filter chains on one window of a site's raw archive before declaring them (the command-line form of the Filter Data tab's preview): each chain from a YAML file in `filters.yaml` syntax, `--declared` adds the site's current list; writes per chain, under `<workspace>/qc/filter_trials/<site>/`, a 5-500 Hz PSD per channel with the evaluated lines marked plus the full-band ladder, the time series with a 20 s zoom on the largest change, the band coherence of ey-hx and ex-hy (and of the remote pairs with `--remote`), and a metrics JSON: line excess before/after, the floor between lines, coherence band means, burst and step fractions; `--lines` evaluates the site's line-scan lines too | `scripts/filter_trial.py <survey.yaml> <site> <start> <end> [--chain LABEL=FILE.yaml ...] [--declared] [--remote NAME] [--lines] [--out DIR]` |
| stacked synthetic remote from concurrent sites (each member read via `processing_archive`, its filtered variant if it declares any, else its raw archive, exactly as `process_rr.py` would read it; streamed in 10-minute chunks); `--recipe NAME` builds a time recipe of the survey's `stacks.yaml` (the GUI's Stacks tab writes it; a band recipe is refused, `process_intersite.py --stack` forms it) and records the recipe's name, hash and text and each member's archive identity in the archive; an archive that answers its recipe is reused, a stale one exits 2 unless `--overwrite`, which builds in `<workspace>/mth5/.build_<pid>/` and replaces `NAME.h5` only after the build is checked; an existing `NAME.h5` built without a recipe exits 2 even with `--overwrite` | `scripts/build_stack.py <survey.yaml> <name> <start> <end> <member>... [--weighting none\|coherence] [--check]`, `scripts/build_stack.py <survey.yaml> --recipe NAME [--overwrite] [--check]` |
| band-averaged coherence on the processing bands | `scripts/coherence_qc.py <survey.yaml> <local> <remote> [--stack S]` |
| inter-site transfer function of a local on a base, the native interim estimator (`mt_workbench.intersite`; aurora through a virtual pair station is the production path to come): the telluric tensor T (`--kind telluric`, E_local = T E_base) or the magnetic tensor M (`--kind magnetic`, H_local = M H_base) per band of the survey's band scheme, each channel calibrated through its own filter chain, Huber reweighting referenced to a third site (`--remote SITE`, its hx, hy or `--remote-channels ex,ey`) or to the stack of every other site's E or H covering the window by `--min-overlap-hours` (12 h; the local, the base and `--exclude` left out), formed per band from the members' calibrated spectra: each member channel divided by the square root of its median band power, a member's window left out where its normalised power exceeds `--stack-reject-factor` (25) times the median over the members in that window (a natural event raises every member and is kept, one member's fault or burst is not; it needs three members or more to act), a window keeping fewer than `--stack-min-members` (2) left out of the band, and each member's scale and rejected fraction per band and the windows left out recorded in the sidecar and the `.h5`; `--stack-plain` keeps the earlier time-domain stack (each member divided by its RMS over the window, then the plain mean), whose products are identical to those of the script before the band stack; errors from a 20-slice jackknife over time; the local or the base as the reference is refused (exit 2), and so is a workspace archive with no survey.yaml entry such as a `build_stack.py` stack, whose members cannot be checked against the pair; writes `<local>_te-<base>_rr-<remote>` (`_hm-` for M) `.csv`, `.json` sidecar, `.h5` (plain HDF5 arrays) and `.png` under `<workspace>/tf` or `--out-dir`, no EDI or XML; prints and records the timing check (arg(det)/2 at the three shortest periods, the delay of a phase linear in frequency); `--dry-run` prints the resolution, the stack's form and members and the sites left out; `--base-stack E` makes the band stack of the live sites' ex, ey the inputs instead of a named base (E_local = T E_stack, the local always left out, the positionals after the local then start and end, stem `<local>_te-stackE_rr-<remote>`), and `--base-stack H` the band stack of their hx, hy with `--kind magnetic` (H_local = M H_stack, reference a third site's H or E or a stack of either, stem `<local>_hm-stackH_rr-<remote>`; E with magnetic and H with telluric are refused); with a reference stack as well, `--remote-exclude` takes the place of `--exclude` for the reference stack so that the two stacks are built from different sites; on the stack T and M are in each band's normalised units (\|T\|, \|M\| not field ratios; phases and arg(det)/2 unaffected; `stack_scale_rms` per band in the record): a window in which a member's record starts or ends is refused (`--window-members-constant`, the default; `--allow-member-change` runs it and records the changes), a member channel whose median correlation with the other members over the 1-100 s bands is negative is flagged (`--screen-polarity flag`) or left out (`drop`), a reference sharing a site with the base stack is refused unless `--allow-shared-members`, `--stack-plain` is refused, and the sidecar's `base_stack` block records the members with their per-band scale and rejected fraction, the windows and sites left out, the window, the changes, the polarity screen and the shared sites; `--stack-method median` takes the median of the kept members' real and imaginary parts per band in place of their mean (two members kept give the mean; stem `stackEmed` or `stackHmed`; every band stack block of the sidecar records its method); `--stack NAME` takes a band recipe of the survey's `stacks.yaml` (`use: base` is the base stack, `use: reference` the reference; given twice, one of each), whose members, window (start and end on the command line win), overlap, reject factor, min members, method and, for a base, polarity screen and membership rule are the run's; the options a recipe declares and `--base-stack`, `--remote-stack` and `--stack-plain` beside it are refused (exit 2), as are a time recipe, a `use_filters` that is not the run's and a local at another rate than the recipe's; the sidecar records the recipe's name, hash and text and the stem carries the recipe's name | `scripts/process_intersite.py <survey.yaml> <local> <base> --kind telluric\|magnetic (--remote SITE [--remote-channels hx,hy\|ex,ey] \| --remote-stack E\|H [--exclude S1,S2] [--min-overlap-hours H] [--stack-plain \| --stack-reject-factor F] [--stack-min-members N] [--stack-method mean\|median]) [start] [end] [--min-period S] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]`; `scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind telluric --base-stack E (--remote SITE \| --remote-stack H [--remote-exclude S3,S4]) [--exclude S1,S2] [--window-members-constant \| --allow-member-change] [--screen-polarity flag\|drop] [--allow-shared-members] ...`; `scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind magnetic --base-stack H (--remote SITE [--remote-channels hx,hy\|ex,ey] \| --remote-stack H\|E [--remote-exclude S3,S4]) [--exclude S1,S2] ...`; `scripts/process_intersite.py <survey.yaml> <local> [<base>] [start] [end] --kind telluric\|magnetic --stack NAME [--stack NAME] [--remote SITE [--remote-channels hx,hy\|ex,ey]] [--allow-shared-members] [--min-period S] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]` (a base recipe takes no `<base>`, a reference recipe no `--remote`) |
| one T (or M) over a Phoenix receiver's whole band: a burst product (`G5H G8H --remote G6H`, compact grid) and a continuous one (`G5 G8 --remote G6`, survey `min_period` 4**(22/6)/6000) stitched by band, the burst rows below the first shared band, the continuous from it on; exit 2 when a shared band differs by more than 2 combined sigma, the edges do not coincide (the aligned `min_period` printed) or the archives' stamp corrections differ (see "Instruments", Phoenix) | `scripts/merge_tensor_bands.py <bursts .json> <continuous .json> [--accept-disagreement] [--out-dir DIR]` |
| one potential per site at every period from inter-site pair products (the network datum, `mt_workbench.network`; see "The network datum" below): a weighted least-squares solve of psi(l, b) = phi_l - phi_b per period and connected component, the potentials relative to the component median with a Monte Carlo error, chi2/dof with its 99 % interval, the loop each pair closes and every pair row with its reason; refused (exit 2) for two band layouts, mixed tensors, a missing sidecar or CSV, a stack product without `base` and an out folder that exists | `scripts/solve_datum.py <survey.yaml> --pairs PAIRS_CSV [--out DIR] [--scale-by-closure] [--leave-out-flag NAME ...] [--band LO-HI ...]` |
| band masks of a coherent near-field source from the Cross-powers tab's chunk impedances: per band, the groups of the pair's store (the overlap, or [start, end); `--chunk-s`, 600 s by default, 60 s recommended) with enough windows and a coherence of at least `--min-coherence` (0.5) are split by 2-means in the (log10 \|Z\|, phase) plane (yx plus 180 deg); a split is accepted when the cluster farther from 0 deg sits at a physical phase (the Earth's), the other lies within `--max-source-phase` (30 deg) of 0 deg, the median phases differ by at least `--min-separation` (20 deg) and by more than twice the pooled MAD, and the Earth holds at least `--min-earth-fraction` (0.2) of at least 30 groups; the source cluster's groups, widened by `--dilate N` groups either side (2 recommended), get one band mask per run, found_by `cluster`, scope `local`; prints the per-band table and the usable yx/xy range of the stacked impedance with no masks, the cluster masks and the site's other masks; `--out` writes a masks.yaml-style file, `--write` replaces the site's earlier cluster masks in masks.yaml and keeps every other entry, `--figures` writes a scatter per band, a summary figure and a JSON under `<workspace>/qc/cluster_masks/<local>_rr-<remote>/` | `scripts/cluster_masks.py <survey.yaml> <local> <remote> [start] [end] [--component yx\|xy\|both] [--chunk-s S] [--min-separation DEG] [--min-earth-fraction F] [--min-coherence C] [--max-source-phase DEG] [--dilate N] [--out FILE.yaml] [--write] [--figures]` |
| move a site's masks.yaml entries into `masks_history.yaml` beside it (each keeping its keys, with `retired: {on, why}`) or back with `--restore`, so no declaration is lost: the selectors are AND-ed (`--found-by`, `--scope`, `--bands all\|limited`, `--reason-contains`, `--before`, `--after`, `--overlapping a..b`), each selected entry is printed on one line with the counts before and after, `--dry-run` moves nothing, exit 2 when nothing matches; both files are replaced atomically (`mt_workbench.masks.retire_masks`, `restore_masks`) | `scripts/retire_masks.py <survey.yaml> <site> [--found-by LIST] [--scope LIST] [--bands all\|limited] [--reason-contains TEXT] [--before ISO] [--after ISO] [--overlapping ISO..ISO] [--restore] --why TEXT [--dry-run]` |
| all-band masks by time of night and by bursts of the local E: `--night [HH:MM-HH:MM]` masks everything outside that local window (survey.yaml `timezone:`, 01:00-05:00 by default) on every day of the site's record, found_by `night`; `--gate` masks the bursts of the site's 1 Hz E (its derived `<site>L` archive: \|first difference\| of ex and ey over its record median, the 30 s running mean of the larger above `--k` (3) times its record median, widened by `--m` (60) s either side), found_by `gate`; both scope `local`; `--write` replaces only the site's entries of that origin; `process_rr.py --mask-origins night` or `night,gate` then processes those selections | `scripts/gate_masks.py <survey.yaml> <site> [--night [HH:MM-HH:MM]] [--gate] [--k K] [--m S] [--out FILE.yaml] [--write] [--figure]` |
| processing campaign over a line (plan YAML, e.g. `surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml`): stage 0 filtered variants, 1 every site rr every concurrent remote, 2 leave-one-out stacks (plain and coherence-weighted), 3 estimator/band options on each site's best remote, MANTLE among them (`mantle: [--engine, mantle, --mantle-max-hours, "72"]`, run with `--mantle-window clip`, its expected peak by window length; see [Campaigns](#campaigns)); per-site plan keys: `remotes: {SITE: REMOTE}` sets a site's stage 3 remote (reported as the best, ledger note "remote override"), `modes: {SITE: [xy]}` scores the site on those modes (summary "xy-only"), `windows: {SITE: {yx: [start, end], merge: true}}` adds a default run over the window (`<name>-default-yxwin`) and a merged product (`<name>-default-merged`, scripts/merge_modes.py's `merge_files`: xy from the full-record default, yx from the window) shown as the site's default in `summary.md`; resumable (`ledger.csv`, with each product's engine from its sidecar), `--parallel` jobs behind a memory gate, products scored by `mt_workbench.quality` over their own periods (scores.csv gives each product's engine and period range: a MANTLE product stops near 1000 s) and plotted per site and line-wide into `<workspace>/campaign/<name>/`, `summary.md`; `--report` redraws from the ledger | `scripts/campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...] [--configs NAME[,NAME]] [--parallel N] [--max-runs N] [--dry-run] [--report]` |
| map background for the GUI's site map, fetched once while online (Esri.WorldImagery by default: imagery, no place names; contextily's zoom + 3, longer side at most 8000 px; warped to lon/lat; `<workspace>/basemap.png` + `.json`); the GUI runs it itself when a survey is opened without `basemap.json` | `scripts/fetch_basemap.py <survey.yaml> [--provider NAME] [--margin F] [--zoom N\|auto]` |
| INTERMAGNET observatory as a 1 Hz remote for long periods (`mt_workbench.observatory`, ported from the AusLAMP processing): one-second X Y Z from the BGS GIN, best available, one request per UTC day into a day cache (`<workspace>/observatory/<CODE>/<year>/<CODE>_<date>.sec.gz`, the served IAGA-2002 text; a re-run fetches nothing cached), then `<workspace>/mth5/<CODE>.h5` (hx = X north, hy = Y east, hz = Z down, nT, no filters; gaps up to `--max-gap` s filled, one run per longer gap) and a `<CODE>: {instrument: intermagnet, ...}` site entry in survey.yaml; start/end default to the survey's site span; exit 1 when offline. Aurora pairs it only with a 1 Hz local archive (no mixed sample rates) | `scripts/fetch_observatory.py <survey.yaml> <IAGA code> [start] [end] [--cache DIR] [--max-gap S] [--dry-run]` |
| a broadband site at 1 Hz for an observatory remote: the site's processing archive (its filtered variant when it declares filters) decimated run by run, one channel at a time, through zero-phase FIR stages of at most 10 (scipy.signal.decimate, the filter of `mt_workbench.timefreq`; 11.1 s dropped at each run end, samples on whole UTC seconds) into `<workspace>/mth5/<site>L.h5`, station `<site>L` with the source's runs, channel metadata and calibration chains, and a derived-site entry `<site>L: {derived_from: <site>, sample_rate: 1.0, ...}` in survey.yaml; an existing archive is kept without `--force`. `process_rr.py <survey.yaml> <site>L <CODE>` then processes it at 1 Hz (bands from 4 s; a remote at another rate is refused) | `scripts/decimate_site.py <survey.yaml> <site> [--rate 1] [--force] [--min-free-gb G]` |
| the raw DC level of every channel of a survey's archives, per run: subsampled median and MAD in counts, the share of samples at a rail, the ratio to the typical level of its channel type, and a verdict (`open input?` when the level exceeds `--threshold-counts`, 1e9, or `--ratio`, 30, times the typical; `saturated?` above 1 % at a rail; else `ok`); an electric input that is open or of very high impedance sits at the logger's bias level (C05 ey and C13 ey of the Morocco survey at 1.60e9 counts); derived and observatory sites are skipped; archives opened read-only without a lock; the measure and verdict are `mt_workbench.dclevel`'s, which the ingest also records per site in each archive's run comments (the GUI's Metadata tab shows that record), and the script classifies every site it checks together | `scripts/dc_level_check.py <survey.yaml> [SITE ...] [--rate HZ] [--threshold-counts N] [--ratio R] [--sample-seconds S] [--csv OUT.csv]` |
| one EDI from two products of the same pair when one electric channel is usable over the whole record and the other only over a window: the x row (Zxx, Zxy, errors) and the tipper from `--xy`, the y row (Zyx, Zyy, errors) from `--yx` interpolated in log period onto the `--xy` periods (NaN outside `--yx`'s range, stored as EMPTY and read back as 0), `--xy`'s station metadata and frame, `OUT.xml` and `OUT.h5` beside the EDI, and a sidecar naming both sources; exit 2 when the stations or the sidecars' remotes differ unless `--force`; `merge_files` does the same from Python (campaign.py's `windows:` merges) | `scripts/merge_modes.py OUT.edi --xy A.edi --yx B.edi [--tag TAG] [--force]` |
| a delivered EDI with each measured-reversed electric line written as laid: for each line the site's survey.yaml entry declares reversed (`azimuth_ex: 180` or `azimuth_ey: 270` under `flip_reversed_dipoles: true`; the site is the DATAID unless `--site`, a derived site read through its parent) the line's Z row is negated (Zxx, Zxy or Zyx, Zyy, real and imaginary parts; the errors, the other row, the tipper and the periods as read), its EMEAS line states AZM=180.00 or 270.00 (its electrode ends exchanged where it has any), and an INFO processing parameter `mt_workbench.as_laid_ex` or `_ey` says the row is the field as measured on the reversed dipole (a reader assuming north and east sees it 180 deg out, one applying AZM recovers the tensor) and quotes the measurement from the site's `notes:`; written as merge_best writes its EDI (`products.write_edi`, then `patch_edi_text`), the processing-parameter and measurement lines kept from the input's text, with `OUT.as_laid.json` beside it (the site, the input's and output's sha256, the lines and rows, AZM before and after, the INFO lines, every other header line the writer changed); applied once, at delivery, never to an intermediate product; a site with no reversed line is re-written with nothing transformed; refused (exit 2, nothing written): `swap_e`, an electric azimuth neither nominal nor reversed, a reversed azimuth under `flip_reversed_dipoles: false`, a site without its own entry, a file already written as laid; `--check` applies the transform to the output again and compares the result with the input exactly (periods, Z, errors, tipper; PASS, or FAIL naming the first differing element, exit 1) | `scripts/deliver_as_laid.py <survey.yaml> <in.edi> <out.edi> [--site SITE] [--check]` |
| each site's magnetic declination in survey.yaml from the IGRF (ppigrf, its newest coefficients, IGRF-14): at the site's latitude, longitude and elevation and the midpoint of its `start`/`end`, as `declination` (degrees east of geographic north, 2 decimals), `declination_model` and `declination_epoch` (decimal year); a dry run prints the table; `--write` edits survey.yaml by lines (existing keys replaced in place, missing ones added after the entry's last line, every other line unchanged, refused when the parsed result differs in anything else); `--check SITE=DEG ...` compares with values given (exit 1 beyond `--tol`, 0.05 deg); `--self-test` checks the NOAA calculator's values at 31.87 N 7.93 W (-1.07) and 33.0 N 3.4 W (+0.20), with a sign-flipped control that must fail | `scripts/declination.py <survey.yaml> [SITE ...] [--dry-run\|--write\|--check SITE=DEG ...] [--tol DEG]`, `scripts/declination.py --self-test` |
| a survey's processing notebook (`surveys/<survey>/notes/`: what was tried per method and per site, the numbers, the verdict and why, each claim with its source) indexed and checked against the saved reports in `<workspace>/qc/reports/`: writes `notes/index.md` (every report with the notes that cite it) and `manifest.csv`; `--journals DIR ...` first copies new results from workflow journals (`journal.jsonl`) into the reports folder as `<date>_<workflow>_<label>.json`; exit 1 when a report is cited by no note, a path cited in a note does not exist, or an `r: <file>` citation names no saved report | `scripts/harvest_notes.py <survey.yaml> [--notes DIR] [--reports DIR] [--journals DIR ...] [--no-index]` |
| a survey's `<workspace>/qc/` folder sorted by line and site: an item whose name starts with a survey.yaml site goes to `qc/<line>/<site>/` (a derived or renamed site such as `B01L` or `C21new` under its parent, `STK_<site>` stacks under the site they serve, the R remotes with line B), line-level items (`line<X>_*`, `line_noise_<X>*`, `lines_<site>` figures, `filters_line<X>*`) to `qc/<line>/line/`, the survey folders (merge_products, reports, cluster_masks, filter_trials, north_recovery, night_ss) to `qc/survey/<topic>/`, anything else to `qc/unsorted/`; `lineC_fx` is split by site, items inside an existing line folder are sorted the same way, and `lines_<site>.csv` and `lines_summary.txt` stay at the top (filter_trial.py --lines reads them there); a dry run by default (the plan, counts per destination folder, the unsorted items, the citations that would change); `--apply` moves (never overwriting), appends each move to `qc/_moves.csv` (old, new, date) and rewrites every recorded old path in `notes/**/*.md` and in the saved reports; a second `--apply` moves nothing; `tf/`, `mth5/` and `campaign/` are never touched | `scripts/organise_qc.py <survey.yaml> [--qc DIR] [--notes DIR] [--apply]` |

Every product is remote-referenced: an adjacent site, a dedicated remote, or a
stacked synthetic remote (`mt_workbench.virtual`). There is no single-station product.

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
`<local>_rr-<remote>[_w<start>-<end>][_<tag>]` names and have no sidecar,
e.g. `surveys/curnamona_cube/work/tf/D02_rr-E08.edi` and the Morocco batch
EDIs, both left as they are.

**Inter-site transfer functions.** `scripts/process_intersite.py` estimates
the telluric tensor T (E_local = T E_base) or the horizontal magnetic tensor
M (H_local = M H_base) between two concurrent sites with the native
estimator of `mt_workbench.intersite`, an interim tool beside aurora. T and
M are dimensionless once each channel is divided by its own filter chain
(E in mV/km, H in nT), and they share the impedances' periods (the survey's
band scheme). Each run of a continuous site is calibrated with its own
chain, as aurora does it: where a channel's chain changes between runs (a
gain change, a new dipole), the windows on each side take their own run's
response and a window across the change is left out. A burst site takes the
chain of its first burst and refuses a burst listing other filters. The
products in `<workspace>/tf` share the stem
`<local>_te-<base>_rr-<remote>[_<tag>]` (`_hm-` for M; `<remote>` is the
reference site, `<site>-E` for its electrics, or `stackE`/`stackH`): a
`.csv` with one row per period (the four complex elements and their
jackknife errors, det, |det| and arg(det)/2 with errors, |T_eff|, the largest
element of the tensor minus the identity, the coherences, the windows, the
flags), a `.json` sidecar in process_rr's form (kind, tensor, local,
base_site, the reference and the stack's members, window, archives, the
filters each calibration removed, band scheme, estimator, `masks`, `frames`,
`flags`, `timing_check`, versions), a `.h5` holding the same arrays in plain
HDF5 (mt_metadata's TF object would label a 2 x 2 on ex, ey an impedance)
and a `.png`. No EDI or XML is written, so merge_best, Geotools and the
quality score never read a T or M as Z. The phases follow numpy's FFT: a
local lagging its base by tau shows -360 f tau degrees, and the timing check
fits that line over the shortest decade of periods, at each band's frequency
weighted by its harmonics' cross power and with each band's phase on the
branch of the best line of a scan over delays, so that a delay of tens of ms
is followed through its wraps, since a clock offset between loggers is the
first thing that mimics an IP phase (10 ms is 3.6 deg at 1 s). The scan
reaches 1 s, the loggers' clock tolerance
(`intersite.TIMING_CLOCK_TOLERANCE_S`), and half the bands' alias period. A
best line at that bound, or band phases that make no line (a weak fit: a
resultant under 0.97, observed or allowed by the band errors), is printed as
"not determined" with the reason, and the sidecar's fit values are then
null. An offset of whole seconds is read with `scripts/timing_qc.py`.

Every band of the survey's layout is a row of the CSV, so the products of
one survey hold the same periods: a band the record could not form (too
few windows on its level, or none of its harmonics) has 0 windows and NaN in its tensor, errors and
arg(det)/2. The coherences are of each output and each input on the
reference: `coh_out_unweighted_x/y` and `coh_in_unweighted_x/y` with every
sample weighted 1, `coh_out_weighted_x/y` under each row's final Huber
weights, and `frac_downweighted_x/y`, the fraction of samples the Huber
weights took below 1. On bursty electrics the weighted value describes the
data the estimate used; the plain one can read near zero where T is well
determined. Five flag columns mark a period and never remove it:
`flag_not_estimated` (an element is not finite), `flag_few_groups` (fewer
than 5 of the 20 jackknife slices hold a solution), `flag_low_coherence`
(the weighted output coherence of either row under 0.1),
`flag_off_diagonal` (|T_xy T_yx| > |T_xx T_yy|: one site's electric
channels exchanged, or a turn of more than 45 deg between the two sites'
layouts) and `flag_re_det_negative` (Re det < 0); the last four mark
estimated rows only. The sidecar's `flags`
block gives each flag's rule, its limit and the number of rows it marks; `frames`
gives the local's and the base's azimuth_ex, azimuth_ey, layout_north and
declination from survey.yaml, recorded and not applied (the tensor stays in
each site's channels as recorded); `masks` gives each site's entries applied
and left out and the band windows they cover.

masks.yaml is applied to the windows of an inter-site run: a window holding
a sample inside an entry is left out of the bands the entry covers. The local and the base take their entries of
scope `local` or `both` (the base's channels are inputs of the tensor, as a
local's are), and the reference takes those of scope `both` or `remote`. An
entry naming none of the channels read from its site is left out, and one
that applies cuts the whole window for every element. The members of a
stack take none of their entries.

The base need not be one site. With `--base-stack E` the inputs are the
band stack of the ex, ey of every site live through the window (the local
always left out, `--exclude` as for a reference stack), so that
E_local = T E_stack with RR's H as the reference, and every site of a
leap-frog survey can be tied to one continuous regional E. T is then the
local relative to the mean of that window's members, so a product must
hold one mix of members: a window in which a member's record starts or
ends is refused (one product per constant-membership epoch), a member
whose E correlates negatively with the others over 1-100 s (a reversed
dipole) is flagged or left out, and a reference sharing a site with the
stack is refused, since that site's noise would sit in both the inputs and
the reference. A start or end within 60 s of the window's edges, or a gap
of 60 s or less, is no change (`intersite.MEMBER_EDGE_S`), and the base
stack's members are chosen by the same rule: over a window shorter than
`--min-overlap-hours`, a site joins when its record, with such gaps
bridged, starts no later than 60 s after the window's start and ends no
earlier than 60 s before its end. A reference stack over such a window
needs the whole window less one sample. The stem reads
`<local>_te-stackE_rr-<remote>`, the sidecar's `base_site` is null, and its
`base_stack` block holds what ties the products of different epochs
together afterwards: the members, each one's scale and rejected fraction
per band, and the polarity screen.

Where the electrics are lost, `--base-stack H` with `--kind magnetic` does
the same for M: H_local = M H_stack on the band stack of the live sites'
hx, hy, with a third site's H or E (`--remote SITE [--remote-channels
ex,ey]`) or a stack of either as the reference, under the same rules (a
reversed coil shows as a negative correlation, as a reversed dipole does);
the stem reads `<local>_hm-stackH_rr-<remote>`. `--base-stack E` with
`--kind magnetic` and `--base-stack H` with `--kind telluric` are refused.
With a reference stack beside the base stack, `--exclude` leaves its sites
out of both unless `--remote-exclude` is given, which then is the reference
stack's own list, so that the two stacks can be built from different sites
and share none. On a stack the tensor is in each band's normalised units:
each member enters over its per-band scale, so |T| and |M| (and the ratio
of elements in different columns) are not field ratios, while the phases,
arg(det)/2, the delay and the ratio of two elements of one column are
unaffected. Each band of the `base_stack` record holds `stack_scale_rms`,
the root mean square of the members' scales per channel, and when the
members are calibrated alike the ratio to a member's field is, column by
column, `M_field[:, r] = M_stack[:, r] / stack_scale_rms[r]` (the same for
T).

**Frame and declination.** Every product stays in the sensor frame and is
never rotated at processing: x is the sensors' north as laid out. Which
north that was is the survey's `layout_north` key, `magnetic` (the
default) or `geographic`, in `defaults:` and overridable per site; it sets
the station's `orientation.reference_frame` (geomagnetic or geographic) at
ingest for every reader, so a LEMI-424 site is no longer labelled with its
reader's geographic default, and again on each TF at write time, and with
it the EDI's COORDINATE_SYSTEM. The declination is stored with every
product so a modeller rotates once, inside the inversion. A survey.yaml
site entry (or `defaults:`) carries it as three keys, unset (None, which
is not 0.0) until `scripts/declination.py` fills them:

```yaml
defaults:
  layout_north: magnetic        # the north the sensors were laid out to, or geographic
sites:
  B03:
    declination: -1.07          # degrees east of geographic north
    declination_model: IGRF-14
    declination_epoch: 2023.55  # decimal year, the midpoint of the record
```

Ingest copies them into the archive's station metadata
(`location.declination`), never `translated_azimuth`; `process_rr.py` sets
the local site's survey.yaml frame and value on the TF before writing,
over the archive's, so an archive ingested before the keys existed needs
no rebuild (the sidecar's `frame.declination_source` says which, and
`frame.zrot` records the angle below). Each row writes three products
under its stem (`mt_workbench.products.write_products`): the `.edi`, whose
HEAD carries DECLINATION, DECLINATION.MODEL and DECLINATION.EPOCH lines
and whose INFO `transfer_function.coordinate_system` now equals the HEAD's
COORDINATE_SYSTEM; the `.xml`, EMTF XML, which for an aurora row carries
the residual and inverse signal covariances (RESIDCOV, INVSIGCOV), the
full error covariance a rotation needs (the EDI's ZXX.VAR-style variances
cannot be rotated exactly), and whose Notes state the frame; and the
`.h5`, a standalone MTH5 file holding the survey, station and TF
(`MTH5.tf_summary`, `MTH5.get_transfer_function`), not the site's raw
archive. The sidecar names them (`edi`, `xml`, `h5`). A station id with a
hyphen (KD-Q5) keeps it in the EDI's DATAID and the XML's Site Id, written
and read back (`products.hyphenated_station_ids`, upstream issue 86).
`merge_best.py` and `merge_modes.py` take the frame (declination, frame,
channel azimuths) from the first xy source's EDI and write the same three
files; a merge carries no covariance, which its INFO line
`mt_workbench.covariance=none` and its XML Notes say. A source EDI written
before mt_metadata's azimuth and declination fixes (fork commit 405e7ff)
reads back with no declination and hy at AZM 0, and a merge from
it prints a WARNING and repeats that until the source row is re-run.

**ZROT convention.** For a geomagnetic product with a declination D (east
positive), the EDI carries ZROT = TROT = D at every period and the data
are left as estimated: ZROT states the azimuth of the data's x-axis,
clockwise from geographic north, not a rotation that was applied. This
matches the convention Geotools writes: its own rotation by t writes
ZROT t with Z' = R Z R^T, R = [[cos t, sin t], [-sin t, cos t]], and a
ZROT 0 file round-trips unchanged (export test); how Geotools
treats a non-zero ZROT on import is not yet tested.
Geotools drops COORDINATE_SYSTEM and zeroes AZM on export but keeps INFO
unchanged, so the frame is also written there in words
(`mt_workbench.frame=sensor frame, x-axis at azimuth -1.07 deg clockwise
from geographic north`, `mt_workbench.rotation=data not rotated; ...` and
`mt_workbench.declination`, `_model`, `_epoch`). The EMTF XML states the
same in its own fields: Site Orientation `angle_to_geographic_north` is D
and each horizontal channel's orientation is its layout azimuth plus D
(Hx D, Hy 90 + D, Ex D, Ey 90 + D), and its Notes say so. With
`layout_north: geographic`, or with no declination stored, ZROT, TROT and
the angle are 0 (the declination, when known, is still stored). aurora
regresses each output channel separately, so the residual covariance's
Ex-Ey cross term is not estimated: the XML writes it as 0 (not the 1e32
EMPTY fill of mt_metadata's writer) and the h5 as 0, and both say that
rotated errors then assume zero output-side correlation.

Per-site noise decisions live in `<survey>/filters.yaml` (see
`surveys/burra/filters.yaml`), separate from the field-sheet-generated
`survey.yaml`. Every archive `ingest_site` writes, `<site>.h5`, is the RAW
recording, with no filter applied. A site with a declared list is
processed from a filtered **variant** instead, `<site>_f<hash>.h5`
(`mt_workbench.ingest.processing_archive`/`build_variant`), built on demand from
the raw archive and rebuilt whenever the hash of the declared list changes (a
`filters.yaml` edit); one variant is kept per site at a time. `process_rr.py`
and `build_stack.py` (through `mt_workbench.virtual`) always read
`processing_archive`'s result, also for a declared site whose raw folder is
not found under `data_root` (a stale path or a drive not plugged in: such a
site is never a virtual remote); `--no-filters` reads the raw archive outright.
Try the list on a loaded window on the GUI's Filter Data tab first. The
kinds, documented in `src/mt_workbench/noise.py`'s module docstring: `notch` (50 Hz
+ harmonics), `hp` / `lp` (zero-phase Butterworth high- / low-pass,
`cutoff_hz` required, order 4; a high-pass goes first and removes every
period longer than 1 / cutoff_hz, a low-pass goes last), `cp` (cathodic
protection stack) and `replace` (magnetics from another site's raw archive,
applied first); `notch`, `hp`, `lp` and `cp` take an optional `channels` list
(default all).

## The network datum

`scripts/solve_datum.py` turns the inter-site pair products of a survey
into one potential per site at every period. Each product gives
psi(l, b) = arg(det T) / 2 with its error per period, and over the network
psi(l, b) = phi_l - phi_b modulo 180 deg; `mt_workbench.network` solves
these equations by weighted least squares, each connected component of
the period's pairs on its own gauge site. The product of record is each
site's potential relative to its component's median, `phi_rel_deg`, with
its error `phi_rel_err_deg`, and the closure (chi2/dof and the loop each
pair closes) shows whether the pair errors describe the misfit.

**The pairs table** is a CSV with one row per product:

| column | |
|---|---|
| `sidecar` | the product's JSON sidecar from process_intersite.py or merge_tensor_bands.py; a relative path is taken against `<workspace>/tf` |
| `use` | optional, true by default; false keeps the product listed but out of the solve, and its rows are counted |
| `note` | optional free text, copied to the run record |
| `base` | only for a product whose base is a stack (sidecar `base_site` null): the node name it takes in the datum |

Products of the same two sites (parts, nights, the reverse direction) are
separate equations. All products must be of one tensor (T or M) and one band
layout: periods closer than 10 % but more than relative 1e-9 apart are
refused (exit 2), naming the products of each layout.

```
python scripts/solve_datum.py <survey.yaml> --pairs pairs.csv [--out DIR]
    [--scale-by-closure] [--leave-out-flag NAME ...] [--band LO-HI ...]
```

The tables go into `<workspace>/datum/<pairs table stem>/` (or `--out`), a
folder that must not exist yet: a second run into it is refused, so a run
never overwrites another. The script prints one line per period: rows
entered of rows present, how many entered rows carry a flag, the component
sizes, chi2/dof and whether it lies inside its 99 % interval, the worst
loop, and any gauge tie or unconverged component.

**Reading the tables.**

- `datum_sites_period.csv`, one row per period and site. `phi_rel_deg` and
  `phi_rel_err_deg` are the product. `phi_deg` and `phi_err_deg` are
  relative to the component's gauge (the gauge 0 +- 0): its site with the
  most entered equations, then the most partners, over the whole run (the
  `gauge_rank` table of the run record). When the next site has the same
  two counts, `phi_deg` and `phi_err_deg` are NaN and `datum_periods.csv`
  names the tied sites in `gauge_tie`. `phi_rel_err_deg` comes from 4000 draws (seeded by
  the period); the middle site of a component with an odd number of
  well-separated sites is the median in every draw, so its error is 0.
  `solved` is false for a site with no entered equation at that period.
- `datum_periods.csv`, one row per period and component plus an `all` row
  per period. `chi2_dof` is near 1 when the pair errors describe the
  scatter; `chi2_dof_lo99` and `chi2_dof_hi99` bound the 99 % interval for
  its dof. Above it the misfit is larger than the errors; below it the
  errors are larger than the misfit, or equations with errors over 52 deg
  pull it down (`n_err_over_52`). `phi_err_deg` is the formal error given
  the pair errors, and outside the interval it is not a measured error.
  `n_not_estimated`, `n_no_error` and `n_left_out` count the rows that did
  not enter, `n_<flag>` the entered rows carrying each flag, and
  `n_far_from_centre` the sites more than 60 deg from the component's
  centre, where the median depends on where the circle is cut. dof 0 (a
  tree) means the closure is not tested.
- `datum_loops.csv`: every pair outside the start tree (the most precise
  spanning tree) closes one loop with the tree path between its ends.
  `closure_deg` is the signed sum of psi round the loop, `sigma_deg` the
  root sum of squares of its errors and `z` their ratio; `kind` is
  `repeat` for two products of one pair.
- `datum_pairs_period.csv`, every row of every product,
  with `entered` and `reason` (`not_estimated`, `no_error`, `use=false`,
  `flag:<name>`, or empty when it entered), the product's flags, `resid_deg`,
  `z` (residual over error) and `redundancy`, the share of the pair's
  error the rest of the network checks: 0 for a pair in no loop, near 1 for
  a pair the network fixes. To find a bad pair from a bad loop, take the
  loop's `pairs` at that period and look them up here: a bad pair has a
  large |z| at a redundancy well above 0, and it shows in every loop it
  closes.
- `datum_run.json`: the inputs with their SHA-256, each flag's rule from the
  sidecars, the options, the period lattice, the gauge ranking, the totals
  (rows by reason, and in `entered_rows_flagged` the entered rows carrying
  each flag, the sum of its `n_<flag>` over the periods), the gauge ties,
  the components not converged, what `phi_err_deg` means, the version and
  commit, and the start and end times.

**Options.** Rows leave the solve only when the caller asks:
`--leave-out-flag NAME` (repeatable) leaves out the rows that carry that
flag column of the products (such as `flag_off_diagonal`), and `use` false a
whole product;
both write the reason and are counted in `n_left_out`. Errors enter as the
products wrote them. `--scale-by-closure` multiplies `phi_err_deg` of a
component whose sqrt(chi2/dof) (`scale`, always written) is over 1 by it,
recomputes `phi_rel_err_deg` with the covariance times scale^2, and marks
those rows `errors_scaled`; chi2, `z` and the loops keep the errors as
entered. `--band LO-HI` (seconds, repeatable) writes `datum_bands.csv`, the
weighted circular mean of each site's `phi_rel_deg` over the band with two
errors (`err_independent_deg` if the periods are independent,
`err_correlated_deg` if their errors are fully correlated): a reading of
the per-period table, never an input to the solve.

## Campaigns

`scripts/campaign.py` runs a plan (a YAML beside the survey, e.g.
`surveys/<survey>/campaign_lineA.yaml`) into
`<workspace>/campaign/<name>/`: stage 0 builds the filtered variants, stage 1
runs every site against every concurrent remote, stage 2 the leave-one-out
stacks, stage 3 each plan config on the site's best stage 1 remote (kept in
`best_remote.json`). Every run is a row of `ledger.csv`; a row done with the
same inputs (each site's filters hash and raw archive mtime, the masks
applied) is not run again, a failed one is. `--dry-run` prints every row
with its state, hours and, for a MANTLE row, its window and expected peak,
and writes nothing.

A MANTLE config (`--engine mantle`) is run with `--no-masks` and
`--mantle-window clip` unless its flags name `--mantle-window`: a pair whose
overlap is longer than the config's `--mantle-max-hours` (24 h without the
flag) or holds a gap is processed over the longest span both records cover,
its first `--mantle-max-hours` hours, where it would be refused. The row's
note gives the clip expected from the survey spans, then the one its sidecar
records. A MANTLE job is held at the memory gate by hours x
`runner.mantle_gb_per_hour` (1.25 GB; the line A runs peaked at 1.22 GB per
hour plus 0.2 GB) or its class figure, whichever is larger, and a job
expected above the machine's memory less `runner.min_available_gb` is marked
skipped with what it needs and what the machine has.

| plan key | meaning |
|---|---|
| `name`, `description` | the campaign's folder and tag prefix (`<name>-<config>`), and its summary text |
| `sites`, `exclude: {SITE: reason}`, `groups: {G: [SITE ...]}` | the line in order, the sites left out with why, the deployment groups in processing order |
| `overlap: {min_fraction, min_hours}` | a remote overlaps the local by at least this share of its record or this many hours |
| `stages.stacks.weightings` | stack suffix to weighting (`u: none`, `w: coherence`) |
| `stages.options.configs: {NAME: [flags]}` | the stage 3 configs, process_rr.py flags each |
| `stages.options.tie_tolerance` | scores within this of the top count as a tie in the best-remote choice |
| `remotes`, `modes`, `windows` | per-site stage 3 remote, scored modes, and mode windows with an optional merge |
| `scoring: {pmin, pmax}` | the period window of the scores |
| `min_band_windows: N` | `--min-band-windows N` (a whole number, 0 or more) on every aurora rr job of stages 1, 2 and 3, the `windows:` runs too, after the runner's `--no-masks` and before a config's flags, so a config's own `--min-band-windows` wins; none on a MANTLE config; shown in the dry run (each job's options and the plan's line), the start log and summary.md; part of a job's inputs unless its config gives its own floor, so a change re-runs the rows; without the key, no flag and nothing in the inputs |
| `runner.minutes_per_job`, `runner.expected_peak_gb` | per kind or per config: the dry run's minutes and the memory gate's peak |
| `runner.min_available_gb`, `runner.peak_factor`, `runner.peak_percentile`, `runner.peak_recent` | the memory gate |
| `runner.parallel` | jobs at once when `--parallel` is not given; `gate` (the default) takes as many rr jobs as the memory gate admits with the memory available at start, at least 1; the runner logs that count and the rr peak it used (a dry run prints it) |
| `runner.mantle_gb_per_hour` | a MANTLE job's expected peak per hour of window (1.25) |
| `runner.deferred_configs: [NAME ...]` | stage 3 configs run only when `--configs` names them |
| `runner.move_products`, `runner.masks` | move products into the campaign's `tf/`; apply masks.yaml to every rr run |

MANTLE over a site's whole common span, once the machine is free: add

```yaml
stages:
  options:
    configs:
      mantle_full: [--engine, mantle, --mantle-max-hours, "100"]
runner:
  deferred_configs: [mantle_full]
```

to the plan. The config is left out of every run of the campaign, and when
the other campaigns have ended

    python scripts/campaign.py <survey.yaml> <plan.yaml> --stage 3 --configs mantle_full --parallel 1

runs each site's best-remote pair over its whole common span (clipped only by
gaps and by the 100 h cap), one at a time, each held at the gate until its
memory is free. It reads the best remotes from `best_remote.json` and the
done rows from the ledger, so on a finished campaign nothing else runs; run
it with `--dry-run` first to see each row's hours, expected peak and the rows
too large for the machine.

## Quickstart: a survey in four lines

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


## Instruments

`mt_workbench.instruments` lists six recorders (the five below and the Orange Box,
`orangebox`), each read by its own mt-io reader and archived under that reader's
channel names (Phoenix renamed to ex ey hx hy hz, the MTU-5A's table channels
stored as ex ey hx hy hz):

| `instrument:` | recorder | files a site folder holds | reader, archive channels |
|---|---|---|---|
| `lemi423` | LEMI-423 broadband | `<unix epoch>.B423` (90 min each) | `mt_io.lemi.lemi423`: hx hy hz ex ey (counts; LEMI-120 coil response and `h_scale` added at ingest) |
| `lemi424` | LEMI-424 long period, 1 Hz | `YYYYMMDDhhmm.txt` (daily) + a `.inf` | `mt_io.lemi.lemi424`: bx by bz e1 e2 e3 e4 (nT; the electrics as recorded, mV, though mt-io labels them mV/km, no dipole length applied) |
| `edl` | Earth Data PR6-24 (UoA interface) | `{station}YYMMDDhhmmss.{BX,BY,BZ,EX,EY}` in day folders + `config/recorder.ini` | `mt_io.uoa.pr624`: hx hy hz ex ey (microvolts; the reader's Bartington, Bz-divider, signed-dipole and x10 terminal-box chain; rate from recorder.ini) |
| `phoenix` | Phoenix MTU-5C / MTU-8A | a recording folder: `empower_recmeta.json`/`recmeta.json` + channel folders of `<rx>_<rec id>_<ch>_<seq>.td_150` (`.td_30`, `.td_24k` bursts) | `mt_io.phoenix` through `mt_workbench.phoenix`: ex ey hx hy hz (volts; chain field to volts: dipole or coil table by serial, on H the polarity stage of gain -1, mV to V, receiver curve) |
| `mtu5a` | Phoenix MTU-5A | per recording `<serial><month><day><letter>.TS4` (150 Hz, continuous) with its `.TBL` table; the `.TS2` and `.TS3` bursts are not read | `mt_io.phoenix.readers.MTUTSN` for the counts, the record tags and the table decoded in `mt_workbench.mtu5a`: ex ey hx hy hz (counts; the table's scalar chain as filters) |

**Detection.** A folder under `data_root` is a site when it holds any of
those files anywhere below it (`detect_instrument`, one walk): B423 files ->
lemi423; a 12-digit `.txt` whose first line has the LEMI-424's 24 (or 16)
fields -> lemi424; `recorder.ini` or EDL channel files -> edl; `.td_150`,
`.td_30` or `.td_24k` files with a Phoenix name -> phoenix; `.TS4` files ->
mtu5a. The survey's
own instrument is preferred, so an existing LEMI-423 survey finds exactly the
sites it always did. **The per-site key:** `Survey.instrument_of(site)` is
the site's own `instrument:` if it has one, else what its folder holds, else
the survey's top-level `instrument:`. `scripts/new_survey.py` writes a site's
`instrument:` (and its recorder's default `channels:` preset, since the
survey default's names are not its reader's) only when it differs from the
survey's. `channels:` and `filters.yaml` lists use the reader's names
(`channels: [e1, e2, e3, e4, bx, by, bz]` on a LEMI-424).

**Phoenix MTU-5C and MTU-8A (`instrument: phoenix`).** A site folder holds one
recording folder (or several; `recording:` names one) with
`empower_recmeta.json` and/or `recmeta.json` beside numbered channel folders
of `<receiver>_<recording id hex>_<channel>_<sequence hex>.td_150` (360 s
each), `.td_30` and `.td_24k` (24 kHz bursts). mt-io's Phoenix readers read
the files (the installed fork, `mtproc-fixes` cdceeb3, whose Phoenix code is
upstream v0.0.5 with PR #8): the metadata file is empower_recmeta.json
first, and it gives the channel map per recording (MTU-8A 0 E1 / 2 H2 / 3 H1 /
7 E2, MTU-5C 0 H2 / 1 E1 / 2 H1 / 4 E2), the coil serials and the dipole
lengths. `mt_workbench.phoenix` adds:
- one run per recording, the files read one by one with
  `open_phoenix(fn).read()` and joined only where a file starts at the end of
  the one before (a short or missing file starts a new run; mt-io's
  `read_sequence` would join them and date every later sample early);
- the names ex ey hx hy hz (from E1 E2 H1 H2 H3), so aurora and intersite need
  no channel nomenclature;
- each channel's chain from the field to the recorded volts: the dipole
  (`dipole_<L>m`, mV/km to mV) or the coil table named by the coil serial
  (`phoenix_coil_<serial>`, from `<serial>_*.scal.json`, nT to mV; mt-io
  attaches no coil), on hx hy hz `phoenix_h_polarity` (mV to mV, gain -1:
  the Phoenix records H with the sign of the LEMI-423's recorded H;
  mt-workbench's convention, lemimt's and the LEMI-423 chain's -1000,
  negates H, and this stage puts the Phoenix H into it; upstream issue
  81. The samples stay as recorded, so an archive built by an earlier version
  lacks it, its Phoenix Z sits 180 deg off until re-ingested, and
  process_rr.py and process_intersite.py name it in a warning),
  `phoenix_mv_to_v` (mV to V, in place of mt-io's
  `v_to_mv` of gain 1000, which makes calibrated E and H 10^6 too small;
  replaced only when that is the stage found), and the receiver curve from
  `<receiver>_*.rxcal.json`. Both folders' files come from `calibration_dir:`
  (required). Of several files of one coil or receiver, the latest dated
  (the hex epoch in its name) at or before the recording's start is taken,
  else the earliest after it with a warning, and the channel comment names the
  file and its date, for a converted receiver file also the file its curve
  below the records came from (`phoenix.calibration_for`, upstream issue 84).
  Binary `.scal`/`.rxcal` files (from a
  folder or a .zip) become that JSON with `scripts/phoenix_cal_convert.py
  <source> <calibration_dir>`, which never replaces a file and compares one
  that exists; an `.rxcal`'s curve below its measured points is not in the
  binary and is taken from an EMpower JSON of the same receiver (upstream
  issue 83);
- the coil serial and dipole length from the metadata file unless
  `coil_hx`/`coil_hy`/`coil_hz` or a non-zero `dipole_length_ex/ey` is
  declared; each channel comment names every source (the metadata file,
  recmeta.json, the coil's own report in backend.log) and flags a coil whose
  self-report differs. `polInv` is recorded, never applied (mt-io does not
  read it, upstream issue 54);
- the version-2 second: every stamp of a file of version below 3 is 1 s
  behind GPS (Phoenix DAA09, issue 47), so 1.0 s is added, after checking that
  mt-io's start is its own header arithmetic (a reader that already corrects
  it gets nothing added, any other start is refused). It is recorded as
  `phoenix_stamp_correction_s` in the run, channel and station comments
  (`mt_workbench.phoenix.archive_stamp_correction`), apart from
  `clock_offset_s`, which stays free for a logger's own fault;
- `serial:` checked against the receiver; the header rate checked against the
  site's (`sample_rate: 150` reads `.td_150`, 30 reads `.td_30`); dc levels
  in V with no absolute threshold; `.td_2400` files noted in the run comment
  (mt-io has no reader for them). `h_scale`, `sensor_type`, `electric_gain`,
  `calibration_fn` and `h_from` are refused on a Phoenix site, the Phoenix
  keys on any other. `td_30` is untested (no test recording holds it).
- `scripts/new_survey.py --instrument phoenix` (or a folder detected as
  Phoenix) writes each site's receiver as `serial`, its model, position and
  span from the metadata file and headers, and Phoenix defaults:
  `dipole_length_ex/ey: 0.0` (a non-zero default would override every
  recording's measured lengths), `calibration_dir: sensors` and the aligned
  `min_period` below.

**The bursts as a site of their own.** `G5H: {bursts_of: G5, sample_rate:
24000}` (the entry may also hold `remote`, `notes` and `clock_offset_s`;
everything else is G5's, but `clock_offset_s`, which is 0.0 unless G5H
declares one: the bursts carry GPS time, while an offset on G5 corrects the
continuous stream's decimation-filter delay, -0.1148 s at Kalkaroo) is
ingested from G5's folder, one run per burst (`sr24000_00001`, five
digits), every burst of a `.td_24k` file read through mt-io's
`DecimatedSegmentCollection` on a fresh reader (the installed `read_phoenix`
returns the first burst only, issue 44), checked against a walk of the
sub-headers, the channel folders matched by stamp; a last file that ends
inside a burst gives up that burst with a warning (issue 73). The station's
metadata is read once and written once (issue 85): KD-RR_210428H's 7048
runs ingest in about 3 min.
`scripts/ingest_site.py <survey.yaml> G5H` builds it, and `--all` with
it. `start`/`end` take a
window (a station-day is about 2.3 GB). process_intersite reads burst sites
on a compact grid (`intersite.read_bursts`): the bursts the three sites share,
back to back with one NaN sample between them, so no window straddles two
bursts and the memory is the bursts' (about 6 GB a pair-day, not 91 GB).
Stacks are refused there. A site faster than the survey takes the shortest
period of the survey's layout at or above 4 / rate (1/6000 s at 24 kHz and
4**(14/6)/6000 = 0.004233 s at 1000 Hz with 4**(22/6)/6000;
`mt_workbench.bands.site_min_period`; process_intersite and process_rr take
`--min-period`), and a `min_period` below 4 / rate drops the bands above a
quarter of the rate whole, the rest keeping their edges
(`mt_workbench.bands.top_edge`), so one `min_period` serves every rate. With 2 s bursts and the 128-sample
window, the burst T reaches 0.00019-0.038 s. Aurora (Z) handles burst
archives only for windows of a few hundred bursts (issue 46).

**One T over the ultra-wide band.** Two process_intersite runs stitched by
band: the bursts (`G5H G8H --remote G6H`) and the continuous record (`G5 G8
--remote G6`) with the survey's `min_period: 0.026878315731090622`
(4**(22/6)/6000; the full value, a rounded one moves the edges), so the 150 Hz
band edges fall on the 24 kHz ones and the two products share two bands
(0.0269-0.0427 s). `scripts/merge_tensor_bands.py <bursts .json>
<continuous .json>` takes the burst rows below the first shared band and the
continuous rows from it on, and fails (exit 2) when a shared band disagrees
by more than 2 combined sigma (`--accept-disagreement` writes it anyway and
records it), when the edges do not coincide (it prints the aligned
`min_period`), or when the six archives' stamp corrections differ.

A reinstall of mt-io from the fork's `testing` branch (caddfb1, with mth5
`testing` e73d827d) would make `read_phoenix(td_24k)` return every burst and
give a cheap burst index (`mt_workbench.phoenix._read_bursts` is the one call
to change); it also brings three LEMI-423 reader commits, so the LEMI ingest
tests would be rerun. It changes nothing above otherwise.

**Phoenix MTU-5A (`instrument: mtu5a`, `mt_workbench.mtu5a`).** A recording
is a set of files sharing one stem, `<serial><month><day><letter>`
(4573C07A: receiver 4573, 7 December, the day's first recording). The reader
takes each `.TS4` (150 Hz, continuous) under the site folder with the `.TBL`
beside it; a `.TS4` without its `.TBL` is refused. A site folder holds the
recordings of one receiver (of the declared `serial`, when set), any number
of them, and the site's rate is `sample_rate: 150`. The counts come from
mt-io's `MTUTSN.read()`; the record tags and the table are decoded in
`mt_workbench.mtu5a`, because mt-io 0.0.5 reads the position, the start
time, the run boundaries, some table values and the tag status bytes wrong
and labels the units after one scalar (upstream 551-562, 564 and 565).
- Runs: each recording becomes a run, `sr150_0001` and on, in time order,
  starting at its first record's tag. Where the tags step by other than
  1 s, the run ends and the next one starts at the tag after the step, its
  comment carrying an `mtu5a_gap` piece. Refused: overlapping recordings or
  runs, two receivers in one folder, a table whose FTIM is more than 1 s
  from the first tag, recordings whose chain values differ (FSCV, EGN, HGN,
  HATT, HNOM, the dipole lengths and the channel numbers; workbench 137),
  and any record layout other than five channels of 3-byte samples behind
  32-byte tags in whole 1 s records.
- The chain: the archive stores the int32 counts (units "digital counts")
  with the table's scalar chain as filters, physical to recorded: on ex
  and ey the dipole (`mtu5a_dipole_<c>_<L>m`, mV/km to mV, the declared
  `dipole_length_*` or else the table's EXLN/EYLN), EGN and the converter
  (`mtu5a_counts_<FSCV>v`, mV to counts, 2^23 / (1000 FSCV)); on hx, hy and
  hz HNOM (nT to mV, the table's nominal value), HATT, HGN and the
  converter. Each channel comment names the table column it was read from,
  and on H the coil serial (HXSN, HYSN, HZSN), which is not part of the
  chain check (workbench 139).
- The flags: the tags' saturation bits, status byte, clock status and
  clock error are written beside the archive as
  `<archive stem>.mtu5a_flags.csv`, one row per interval (run, recording,
  field, channel, input, value, start, end, records), named in the ingest
  log and counted in the run comment's `mtu5a_flags` piece. The samples are
  stored as recorded; the flags are not applied as masks (workbench 123).
- The dc level of each channel is measured from the samples against an
  absolute rail of 0.9 x 0.941 x 2^23 counts (0.941 of full scale is the
  receiver's clip) and recorded after "dc rail (counts, 90 % of the clip): "
  (workbench 124).
- A site's own entry may set neither the Phoenix keys (`recording`,
  `calibration_dir`, `coil_hx`, `coil_hy`, `coil_hz`), nor the LEMI and EDL
  keys (`h_scale`, `sensor_type`, `electric_gain`, `calibration_fn`,
  `h_from`), nor the Orange Box keys.

What the reader does not do, each a known gap:
- No coil response: the H chain is HNOM alone, frequency independent, so
  Z and M from MTU-5A magnetics are wrong; T (E to E) is not affected
  (workbench 119).
- The `.TS2` (24 kHz) and `.TS3` (2400 Hz) bursts are not read; one log
  line per site names them (workbench 120).
- No H sign stage: no rule says yet whether the MTU-5A records H with the
  MTU-5C's sign (which `phoenix_h_polarity` corrects), so an MTU-5A Z could
  sit 180 deg off (workbench 121).
- No band delay: the tag is taken as the time of the record's first scan.
  The EMpower `.cts` calibration gives the 150 Hz band a common delay of
  0.196 s, if its phase is referenced to the tag time; none is applied. It
  cancels between two MTU-5A sites and not between an MTU-5A and another
  kind (workbench 122).

**Ingest.** `ingest_site` reads LEMI-423 exactly as before (archives
identical; `calibration_fn`, `h_scale`, the reversed-dipole flip and
`replace` are LEMI-423 keys) and the others through
`mt_workbench.instruments.read_run` (EDL: the site's dipole lengths and, with
`flip_reversed_dipoles`, its azimuths go to the reader, whose dipole filter
carries the sign). `max_run_files` caps LEMI-423 runs only. Each run's
comment records the raw DC level of its electric and magnetic channels
("dc level (median counts, rail %): ex +2.000e+07 0.00 ok, ey +1.600e+09
0.00 open input?", `mt_workbench.dclevel`), classified over the site's channel
runs. A site whose two horizontal coils were plugged into each other's
inputs sets `swap_h: true` in its survey.yaml entry (default false): ingest
exchanges hx and hy (LEMI-423 and EDL), so the archive's hx holds the
samples of the hy input with that input's filter chain (on a LEMI-423 its
own linear stage, 1/Kmy) and hy the samples of the hx input with its own,
both keeping the coil response and `h_scale`, with normal polarity. The
run comment records "swap_h: hx and hy exchanged, ..." and each channel's
comment the input it holds. A coil cabled with its polarity reversed is
declared with `flip_h` (default none), the list of coil channels whose
samples ingest negates, from hx, hy and hz:

```yaml
sites:
  P9S2:
    flip_h: [hy]        # hy reads minus the field along 90 deg
  P6S3:
    swap_h: true        # coils turned 90 deg: recorded hx = -Hy, recorded hy = +Hx
    flip_h: [hy]        # after the exchange hy holds -Hy
```

It is applied after `swap_h` (every instrument, and a Phoenix burst site
takes its recorded site's), so the names are the channels as they are
after the exchange: a coil pair turned through 90 deg is `swap_h: true`
plus `flip_h` naming the channel that reads minus after it (recorded hx =
+Hy and hy = -Hx is `flip_h: [hx]`). "Reads minus" is against the field
along the channel's own direction (hx 0 deg, hy 90 deg) in the sign the
site's other coils give after `h_scale`. Only the samples change, not the
filter chain; the run comment records "flip_h: hy samples negated at
ingest, after swap_h (declared reversed coil)", one dot-free key piece the
EMTF XML writer accepts (docs/upstream_issues.md 48), and each flipped
channel's comment "flip_h: the samples negated at ingest ...".
`Survey.site` refuses a channel other than hx, hy and hz, one named twice,
one the site's `channels:` does not keep, and hx or hy on a site with
`h_from`, whose borrowed coils carry the neighbour's own `flip_h`. The
filters hash and the variant's name depend on `filters.yaml` alone, so
after changing either key rebuild both with
`scripts/ingest_site.py <survey.yaml> <site> --force` (with `--raw` the
old variant would stay in use). A re-ingest changes the raw archive's
mtime, which is part of `campaign.py`'s resume key, so the campaign runs
again every job that reads the site, as local, remote or stack member.
A logger whose GPS time stamps are off by a known amount declares it as
`clock_offset_s`, the seconds added to its recorded stamps at ingest
(default 0.0, which changes nothing):

```yaml
sites:
  RR2:
    clock_offset_s: -1.0   # stamps each sample 1.000 s late: archive time = recorded time - 1 s
```

Every run's start time moves by the offset and the samples are untouched;
the run comment, each channel's comment and the station's
`provenance.comments` record "clock_offset_s: -1.0 s added -1.0 s added to every
recorded time stamp at ingest ...", the ingest log says so for each run,
and `mt_workbench.ingest.archive_clock_offset` reads the offset back from
a raw archive or its variant. The key belongs in a site's own entry: it is
refused in `defaults:`, on a derived site (its archive is decimated from
the parent's, which carries the parent's shifted stamps) and on an
observatory, and a value that is not finite or beyond +/-60 s is refused.
An archive built before the key was set keeps its recorded stamps until
it is rebuilt with `--force`; like `swap_h`, the key is not in
`campaign.py`'s resume key itself, and the re-ingest changes the raw
archive's mtime, which is.
A LEMI-423 site that recorded electrics only (its Bx and By inputs open,
dropped by `channels: [ex, ey]`) names a nearby site of the same survey
whose coils it takes, `h_from` (default none):

```yaml
sites:
  E12:
    channels: [ex, ey]   # no coils at this site
    h_from: M07          # 2 km away, four channels, the same 1000 Hz GPS time base
```

The ingest reads the neighbour's raw B423 files, grouped into runs as its
own ingest groups them, with its calibration file and header coefficients,
its `h_scale`, its `swap_h`, its `flip_h` and its `clock_offset_s` (its stamps moved by
its own offset before alignment; the local's offset moves the local's ex
and ey), and takes its hx and hy samples at the local's GPS time stamps one
for one, so the archive's hx and hy are exactly what the neighbour's own
archive holds at those instants, with its chains, azimuths and sensor ids
(the station location stays the local's). A local run the neighbour covers
in part is cut to the covered part, one it covers across a gap or a
boundary of its runs is split there, and one it does not cover is left
out. The run comment records the span and any cut, each borrowed channel's
comment "h_from: hx of M07, 2010 m away, coil 41, logger 41; aligned by
GPS time; the neighbour's clock_offset_s 0.0 applied", the station's
`provenance.comments` the neighbour and every run left out (so a filtered
variant keeps the record), the ingest log one line per run with its span,
and `mt_workbench.ingest.archive_h_from` reads the neighbour's name back.
`Survey.site` refuses the key in `defaults:`, on a site that declares hx or
hy (or no `channels:`), `swap_h`, a `flip_h` naming hx or hy or
`derived_from`, and with a neighbour
that is derived, an observatory, `h_from` itself, declares channels
without hx and hy, or has another sample rate; the ingest refuses, before
touching an existing archive, a neighbour on another sample grid or one
that covers under half of the local's samples. `process_rr.py` needs no
change: the archive then holds ex, ey, hx and hy, and its TF outputs are
the declared ex and ey. Adding or changing the key needs a re-ingest of
the local with `--force`, which changes its raw archive's mtime, part of
`campaign.py`'s inputs signature, so every campaign job that reads the
site runs again; a re-ingest of the neighbour does not reach the local's
archive, so re-ingest both after changing the neighbour's calibration,
`swap_h`, `flip_h` or clock offset.
One hour ingests
in about 1.4 s (LEMI-424) and 1.1 s (EDL). **Processing** a LEMI-424 site
needs aurora's electric-channel nomenclature (LEMI12/LEMI34) in
`mt_workbench.process`, not added yet; `timing_qc.py`, `psd_qc.py --before` and
`noise_psd.py` still read B423 files only. `build_stack.py` reads each
member's MTH5 archive (its `hx`/`hy`, so LEMI-423 and EDL archives, not a
LEMI-424's `bx`/`by`); a member without an archive has to be built first.

**Instrument registry DOIs (`logger_pid`, `sensor_pid_hx`, `sensor_pid_hy`,
`sensor_pid_hz`, `electrode_pid`, `platform_pid`).** The AuScope instrument
registry (https://pidinst.data.auscope.org.au/) gives each logger, coil and
survey deployment (a "platform") a PIDINST record with a DOI under 10.82388.
A survey says which instrument recorded where by these keys, in a site entry
or `defaults:`, and `platform_pid` also at the top level of survey.yaml (a
site's own winning, for a survey that spans two deployment records). A value
is a bare DOI, `10.<prefix>/<suffix>` (`logger_pid: '10.82388/25jrcc6q'`;
a URL or a `doi:` prefix is refused), or the word `none` for an instrument
the registry does not hold, with the reason in the site's `notes:`. A
fluxgate inside a logger's record (the Orange Box) has no sensor key; no
electrode is registered yet. Ingest and processing fetch no record:
the keys are what the survey declares, and `Survey.instrument_pids(site)`
resolves them (a derived site takes its parent's, a burst site its recorded
site's, and a site with `h_from` adds `logger_hx_hy`, the neighbour's
logger, with the neighbour's hx and hy sensor DOIs). Where they go, each
only when a key is declared:
- the archive: every run comment and the station's provenance comment get
  one piece `instrument_registry: logger <doi>, sensor_hx <doi>, ..., platform
  <doi>` (re-ingest to add it to an existing archive; the products below do
  not need it);
- `process_rr.py`: the sidecar's `instrument_pids` (`local` and `remote`, each
  `{site, pids}`; a stacked remote `{site, members: {site: pids}}` from the
  stack's recorded provenance), the dry run's `instrument_pid.local:` and
  `instrument_pid.remote:` lines, the EDI's INFO block one line per
  instrument (`mt_workbench.instrument_pid_local_logger=10.82388/25jrcc6q`,
  `..._remote_member_<site>_logger=...` for a stack's members; underscores,
  since mt_metadata's EDI reader keeps only the last part of a dotted key,
  upstream 115), and a sentence in the XML's Notes naming each DOI as an
  https://doi.org/ link (`mt_workbench.products.pid_sentence`, read from those
  INFO lines, so any product carrying them gets it);
- `merge_best.py`: the merged EDI keeps its base's (the first xy source's)
  lines and adds, as `mt_workbench.instrument_pid_src<k>_<role>=<doi>`, each
  DOI of another source (k its place in the sidecar's `sources`) from which
  a period was taken and which the base does not carry; the sidecar's
  `instrument_pids` records both.
`scripts/pidinst_lookup.py <survey.yaml> [--write]` proposes the keys from the
serials survey.yaml holds (`serial`, `coil_hx/hy/hz`): it searches the
registry by serial, keeps the records whose SerialNumber is the serial and
whose model is the site's instrument (a serial is not unique across makers:
10307 is an Orange Box and a Phoenix MTU-5C), prints their service dates
against the site's span, and with `--write` writes a key only where exactly
one record is left, the standing way (dated copy, one inserted line per key,
parsed diff and comment count checked). The registry is read only.

## The GUI

A desktop launcher and viewer over the scripts above and each survey's YAML,
with a Metadata tab listing each site's survey.yaml entry, its archive and,
in its dc level column, the raw DC level the ingest recorded: per channel
the verdict and median in counts ("hx ok 4.30e7, ..., ey open input?
1.60e9"), the most severe verdict of its runs with the number of runs when
only some have it, red with an open input and yellow with a saturated
channel, every run in the tooltip, and "-" for an archive built before the
ingest recorded it (scripts/dc_level_check.py reads those),
a site/window tree on the Time Series tab (2 h windows at 1000 Hz,
4 h at 500 Hz), live Spectra,
Spectrogram and Coherence views that compute only through `mt_workbench.timefreq` on
the loaded window, a Filter Data tab that previews the site's filter list on
a loaded window (raw behind filtered, time series and PSD) and drives
`<survey>/filters.yaml`, a Stacks tab that declares stack recipes in
`<survey>/stacks.yaml` (sites, field, window, method; written only at Save
recipe) over a chart of every site's runs and checks the members on the
loaded window through `mt_workbench.stackcheck` (Build archive and Use in
Process hand the recipe to the Process tab's queue and recipe picker), a
Process tab (rows of station and remote, window bar, queue buttons, options
and queue) that queues the scripts
above as subprocesses (Add to queue, then Run queue as a separate step;
its Engine combo, aurora or mantle, becomes `--engine mantle`, the queue
label carries "[mantle]" and, when the pair declares masks, `--no-masks`
goes with it and the status line says so; beside min period, max period,
periods per decade and the notches, window samples, min bin and min band
windows start at the survey's `processing:` values (min bin at 0, read
"layout's own", when the survey gives no `min_bin:`; min band windows at
`MIN_BAND_WINDOWS`, 2, when it gives no `min_band_windows:`) and pass
`--window-samples`, `--min-bin` and `--min-band-windows` only when moved
off them, min bin 0 over a survey's `min_bin:` passing `--min-bin 0`;
min band windows is disabled under mantle) and lists as stations every raw
folder and every declared site that has an archive, a site without a raw
folder labelled by its kind: a recorded site whose raw folder is not found
under `data_root` reads "A01  (archive)" and is processed from its archive,
its declared filters applied as with the folder present; a declared derived
or burst site with an archive is a station too ("B01L  (derived from B01,
1 Hz)", "G5H  (bursts of G5, 24000 Hz)"), also on
a survey whose raw folders are present; an observatory is a
remote only),
a Build MTH5 button on the Time Series tab for a site with no archive yet,
a satellite basemap under the Process tab's site map, fetched when a survey
is opened, and a View EDIs tab drawn with mtpy-v2, which labels each product
by its sidecar's engine ("[aurora]", "[mantle]", "[mantle fine grid]") and,
for a MANTLE product, draws its verdict strip under the resistivity panels
from `<stem>.mantle_report.json` (one row per verdict word over the periods
it covers), shows the sidecar's verdict word counts and opens the report's
notes as plain text (`src/mt_workbench/gui/mantle_products.py`). **No product** (archive, transfer
function, EDI, report figure) is computed in the GUI, and no PNG is ever
displayed in it. Full detail: `src/mt_workbench/gui/README.md`.

```bash
python -m mt_workbench surveys/<survey>/survey.yaml
```

The installed console script `mt-workbench surveys/<survey>/survey.yaml` does the same.

Tests, each run on its own (no pytest runner wired up yet); the smoke test
needs an offscreen Qt platform and writes its screenshots to
`surveys/curnamona_cube/work/qc/gui_*.png` (gitignored; regenerate them by
running it):

```bash
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
QT_QPA_PLATFORM=offscreen python tests/timeseries_build_unit.py  # the Time Series tab's Build MTH5 on a scratch Phoenix survey: enabled on the burst site G5H (its recorded site G5 has the folder) and pressing it asks for ingest_site.py <survey.yaml> G5H; disabled on G9H, whose G9 has no folder, naming G9; G5 enabled (the control)
QT_QPA_PLATFORM=offscreen python tests/gui_missing_workspace_unit.py  # a survey whose workspace folder and its parent do not exist: no modal box, one non-modal notice naming the folder, the status bar saying so, no basemap fetch, nothing made; an empty workspace, a survey.yaml without a workspace key (the tracked curnamona_cube on a clean clone) and new_survey.py's <data_root>/work not made yet open as before and fetch once; a finished New survey job makes its workspace and fetches
QT_QPA_PLATFORM=offscreen python tests/process_tab_unit.py  # the Process tab's masks switch (scope remote, a remote's E-only entry left out) and the engine combo (mantle: --no-masks with --engine mantle, the status line), the window samples, min bin and min band windows controls (defaults from the survey with and without the keys, a flag only when moved, "layout's own" as --min-bin 0 over a survey's min_bin, min band windows disabled and not passed under mantle, reload, the queued argv and label), the Cross-powers list's channels and scope columns
QT_QPA_PLATFORM=offscreen python tests/process_station_list_unit.py  # the Process tab's station list on a scratch survey with raw folders, archives, both or neither, a derived site, two burst sites, an observatory, an undeclared folder and a stack, with data_root present, stale (an existing folder with no site folder) and missing (labels exact, a queued run from archives, ingest_site keeping an archive whose raw folder is not found); process_rr's resolve on recorded remotes with filters (never virtual, variant named, filters recorded, equal under the three roots) and on a stack, burst, derived and observatory remote (virtual); the Atlas survey when reachable (--atlas <survey.yaml> for a copy, e.g. data_root on another drive): raw folders plain, declared sites with an archive labelled by kind; the list from raw_sites() alone and process_rr's raw sites as the folders found each trip it
python tests/mantle_window_unit.py   # the window a --mantle-window clip run takes: runs joined into spans, the cap, a gap, both, runs differing between sites, no common hour; process_rr's refuse unchanged
python tests/campaign_unit.py        # campaign.py: plan, overlap rule, stacks, resume, dry-run counts, runner, filter check, masks signature and scope (channels and scope remote too), a MANTLE stage 3 config (its memory gate and dry-run hours, the ledger's engine, its shorter product scored over its own periods, through a stand-in process_rr.py), the per-site remotes, modes and windows (the override, xy-only scores, the window run and the merged product), a MANTLE row's --mantle-window clip, its expected peak by hours and the skip over the machine's memory, done MANTLE rows kept on resume, the deferred configs and --configs, the plan's min_band_windows (validation, the flag on every aurora job and on no MANTLE job, a config's own flag after it, the inputs changing with it and a done row going stale, the dry-run listing and the plan line, summary.md)
python tests/campaign_memory_refusal_unit.py # campaign.py on a 64 GB machine (psutil stubbed): runner.min_available_gb 200 or 64 GB refused at start, run and --dry-run, exit 2 with one line naming the plan, the setting and the machine; 40 GB runs; the gate's wait line keeps its amounts
python tests/campaign_variant_dry_run_unit.py # campaign.py --stage 0 --dry-run with an empty ledger: a variant built by build_variant and current listed "ready" with its name and left out of the counts; a stale file under the current name (another hash) and missing files "to build"; a current variant whose raw archive is gone listed "raw archive missing" and counted; a 0-byte and a text file under variant names listed "unreadable" with the error's first line, no traceback
python tests/campaign_gate_unit.py   # campaign.py's default --parallel: gate_slots against the bench figures (4 jobs at 22.4 GB, 3 at the p90 34.6 GB), gate_admits == the jobs Campaign.gate starts (plan figure and ledger p90), runner.parallel parsed and refused, the dry run's start line for the gate, --parallel and the key
python tests/cluster_masks_unit.py   # cluster_masks.py on synthetic bands: two clusters masked (source >= 90 %, Earth <= 5 %), one cluster, a source-only band, a second cluster far from 0 deg and clusters 10 deg apart left alone, the mask records, their merging and --dilate, --write keeping time/polar masks, the usable-band rule, two mutations that must trip
python tests/mask_scope_unit.py      # masks.yaml scope: the default local, both, remote, an unknown value refused, the role filter, process_rr's resolve under the role rule and --mask-scope union (sidecar counts, the resolution line), the writers' scope local
python tests/mask_channels_unit.py   # masks.yaml channels: normalise, the key left out when every channel and an unchanged block kept identical, the remote leaving out an E-only entry, process_rr's per-row runs and the TF row merge on synthetic TFs, stack_impedance per row, the history (retire_masks, restore_masks, atomic replacement, scripts/retire_masks.py), two mutations that must trip
python tests/masks_cache_unit.py     # masks.yaml parsed once per change: reads counted over repeated loads and remote_masks, a new mtime at the same size read again, a save seen, the loads equal to the pure-Python parse, a parse error kept, is_current; the GUI's MasksReader parsing once on a worker thread and, on a file it cannot read, trying once and not again as the tabs ask on ready (test_i)
QT_QPA_PLATFORM=offscreen python tests/crosspower_masks_wait_unit.py  # the Cross-powers mask buttons while masks.yaml is parsed: with the parse held, Mask selected, Remove rows and Save masks leave masks.yaml unchanged and the list empty; once it ends the list holds the file's masks and the same Remove rows and Save write (the control)
python tests/gate_masks_unit.py      # gate_masks.py: night masks against hand-computed UTC windows, the burst detector on synthetic pulse trains, --write replacing one origin only, a mutation that must trip
python tests/windows_unit.py
QT_QPA_PLATFORM=offscreen python tests/edi_index_unit.py  # the View EDIs list from tf/index.json: two reloads of 300 fake products (400 rows) open each sidecar at most once, the labels as describe() gives them, a rewritten sidecar alone read again, a fresh start opening none, tf_index.add (write_products) recording a landed product
python tests/crosspower_workers_unit.py  # the Cross-powers tab's compute asking compute_windows for 8 workers; 1 h of the bench C18 rr C19 with 8 workers identical to 4, array by array: the 92 arrays with data (levels 8-10 hold no window in 1 h; identity skipped without the archives)
python tests/span_cache_unit.py      # the window bars' archive spans from h5py attributes: equal to load_grid's on the bench C18 and C19 and curnamona D02 and D02L, one h5py open and no MTH5 open; SpanCache's second read and its get open no file; a new mtime read again; a survey name the archive does not hold raising in read_span as in load_grid (skipped without the archives)
python tests/segment_unit.py
python tests/psd_ladder_unit.py
python tests/survey_unit.py          # distance_km, Survey.timezone, the channel presets (Phoenix's included), instrument detection, derived and observatory sites, the declination keys (None default, table CSV, the GUI cells and save), layout_north (default, defaults and own value, the frame it sets, a bad value refused), an unknown site key refused with ValueError naming it, the Phoenix keys and the burst site (bursts_of: the recorded site's settings under its own name, six bad burst entries refused), the burst site's clock_offset_s (0.0 under a recorded site at -0.1148, its own 0.05 kept, 61 refused; copying the recorded site's is the mutation that must trip)
python tests/phoenix_files_unit.py   # the Phoenix entries of mt_workbench.instruments on synthetic headers of both models: names (the ._ twin, td_2400 and a bad name refused), detection beside LEMI and EDL folders, file starts (recording id - 18 s, + 1 s or + 360 s x (sequence - 1); bursts at their stamp), record_files order, span, header_facts from empower_recmeta.json; no leap seconds is the mutation that must trip; the run plan with a trailing 0-byte sequence (one run, the empty files named) and with sequence 2 missing, empty or 60 s short in one folder (runs 1 and 3-4 in every folder, the phoenix_gap note with 360 s), each folder's own files the mutation; the calibration-date rule on synthetic scal and rxcal files of three dates and two on one day (earliest before the first, latest at or before the start, one file always, none for no file, refused with no start), the rule reversed the mutation; a file dated after the start taken with one warning naming the coil, the file and the days (no warning the mutation); the rxcal comment of a converted file naming the file its curve below the records came from (the date alone the mutation)
python tests/ingest_phoenix_unit.py  # Phoenix ingest on cuts of the real G5 (MTU-8A) and J1 (MTU-5C) recordings copied into scratch: every channel equal to its folder's file bytes (both maps), mt-io's read, the first sample at the recording id - 18 + 1 + 1 s and the stamp line in every comment, the coil stage by the empower serial with the scal table's response, J1's coil self-report flagged and overridden, |chain|/|rx| = L x 1e-6 and |coil| x 1e-3 with units mV/km or nT to V and calibrate quiet, the dipole sources, a short file splitting the run, the key refusals and the td_2400 note, the rate check, and the burst site G5H (24 runs equal to a sub-header walk and to mt-io's to_channel_ts()), a last .td_24k file cut 24000 samples into its last burst (23 runs, the warning) and a failure forced inside the burst ingest leaving no archive, and U14: with G5 at clock_offset_s -0.1148 the G5H bursts at their stamps (+ the version-2 second only), G5H's own 0.05 applied and G5 keeping its offset, U15-U17: a 0-byte last file in every folder (one run, a warning per file) and sequence 2 missing or empty in the hx folder (runs 1 and 3-4, each channel its own folder's files, run 2 at sequence 3's time in every channel, the phoenix_gap line), the dc level rails 2.25 V (E) and 1.125 V (H) in the run comment, the 25 test-folder recordings planned as on 8a72107 (tests/fixtures/phoenix_plans), U18: phoenix_h_polarity (gain -1) once on hx and hy and on G5H, never on E, the 1 Hz chain phase 180 deg on H and 0 on E, stored hx anticorrelated with calibrated hx (-0.9 or below) and ex correlated, flip_h hy still flipping and swap_h keeping one stage a channel, and with no coil table the chain [phoenix_h_polarity, phoenix_mv_to_v, receiver curve] accepted by ChannelResponse (an nT-to-nT stage first refused); U17 also dot-free run-comment keys; U19: G5H of 12 and 24 bursts calls mth5's station metadata getter at most 4 times and never with a run present, and Station.update_all as often for both (upstream 85); a mutation per check that must trip (needs the Kalkaroo Phoenix test recordings)
python tests/mtu5a_unit.py           # the MTU-5A reader on synthetic .TS4 and .TBL files written with struct (table channel numbers out of the stored order): M1 the table decoded by each block's type byte and the position as degrees plus minutes / 60, M2 a three-record recording as one run sr150_0001 from its first tag with each channel equal to the counts written for its table column and the scalar chain, M3 the flags csv, M4 a missing record splitting the run with an mtu5a_gap piece, M5 nine refusals leaving no archive, M6 detection, file_start and span, M7 the real Oak Dam recording 191207/4759C07A copied into scratch (one run, every sample equal to a decode written in the test; the two-receiver folder refused; skipped without the folder), M8 the dc level rail at 0.9 x 0.941 x 2^23 counts, M9 the flag names under swap_e, M10 coil serials outside the chain check, M11 the fifteen keys of other recorders refused by name in an mtu5a entry (swap_h allowed); a mutation per M2, M5, M8, M9, M10 and M11 that must trip
python tests/phoenix_archive_unit.py # archive_stamp_correction read with h5py: values equal to the mth5 read on six synthetic archives and PT_10133.h5 when present, MTH5Error for a missing archive or station, 400 runs in under 1 s and a tenth of the mth5 read with no mth5 open; the mth5 read is the mutation that must trip
python tests/phoenix_h_polarity_check_unit.py # archive_h_polarity and its warning: run_h_polarity on filter lists (the stage on hx and hy, one lacking, electric only, a LEMI-423 chain), ten synthetic h5py archives (mth5 0.2.0 and 0.1.0 forms, 1629 burst runs in under 5 s), and when present the scratch G5.h5 (with the stage), KD-RR_210428.h5 and PT_10133H.h5 (without, one warning each) and KD-RRa_210428.h5 (LEMI-423, none); the stage renamed is the mutation that must trip
python tests/xml_comment_keys_unit.py # products.dot_free_comment_keys: a run comment with the 4beb3cd "dc rail (V, 0.9 x the input range)" key written by write_xml while mt_metadata's own writer raises (the control), the TF's comment left as it was, values kept, the new dot-free RAIL_PREFIX accepted by mt_metadata's own writer, both keys read back by parse_level_note, and the scratch G5.h5's run comment when present; no sanitiser is the mutation that must trip
python tests/hyphen_station_export_unit.py # products.hyphenated_station_ids: EDI and XML of KD-Q5, KD-RR_210507 and A01 written by write_edi / write_xml and read back by read_tf with DATAID and Site Id exact and Z unchanged; mt_metadata's own EDI writer raising on the run id 'KD-Q5a', its XML read raising and its EDI read giving KD_Q5 (the control); A01's files the same with the context a no-op; the names restored after the context; the P1 wrapper products of KD-Q5 read as KD-Q5; the context made a no-op must trip
python tests/intersite_bursts_unit.py # the compact burst grid on synthetic burst archives: windows within one per burst of the dense grid at every level, a known T with a 3-sample delay recovered (levels 1-3 within 3 sigma, level 0 within 2 %: the window misalignment bias of the delay), a run with another chain refused; site_min_period at 24 kHz (1/6000 s, every 150 Hz band in range shared); mutations: the base shifted one burst, the chain check removed, the old max() rule
python tests/merge_tensor_bands_unit.py # merge_tensor_bands.py on synthetic burst and continuous products: the rows by the rule, the overlap check passing, a band moved 5 sigma exit 2 (0 with --accept-disagreement), misaligned edges exit 2 with the aligned min_period, differing stamp corrections exit 2; the shared bands taken from the bursts is the mutation that must trip
python tests/network_unit.py        # mt_workbench.network on synthetic networks: potentials recovered within 3 sigma, chi2/dof in its 99 % interval, dof, redundancy and loops, a shifted pair found by its loop, the gauge change, two components, the wrap edge, dof 0, parts, the error calibration, band_reading, scales and gauge ties
python tests/solve_datum_unit.py    # solve_datum.py on synthetic pair products written by the package's writers: rows, reasons and flag counts, potentials within 3 sigma, --leave-out-flag, --scale-by-closure, two layouts refused, a half-layout and a burst-merged product accepted, the refusals, use = false and a stack base
python tests/declination_unit.py     # declination.py: the IGRF fill against the NOAA calculator with a sign control, the record midpoint, the line-preserving --write on copies of the Morocco survey.yaml (other lines unchanged, CRLF, in-place replace, the guard), --check
python tests/ingest_unit.py          # the raw/variant split (filters_hash, build_variant, old-layout), the LEMI-423 path, one real hour of LEMI-424 and EDL, the DC level record (an ey at 1.6e9 counts open input?, healthy channels ok, the recorded medians against the archive's samples), the declared declination stored in the station metadata (no translated_azimuth, nothing rotated), the frame from layout_north (geographic on request; LEMI-424 and EDL archives geomagnetic, the LEMI-424 reader's own geographic as the control)
python tests/ingest_flip_h_unit.py   # flip_h on a synthetic LEMI-423 site: hy negated sample for sample with hx, the electrics and the chain untouched, the run and channel comments, [] the same as no key; a coil pair turned 90 deg either way given back as the field by swap_h then flip_h; the run comments taken by the EMTF XML writer; refusals (h_from, not a list, not a coil, twice, not kept); a donor's flip_h carried to an h_from site; Phoenix bursts flipped after the exchange; four mutations that must trip (the dotted key written with products.dot_free_comment_keys left out)
python tests/ingest_swap_h_unit.py   # swap_h on a synthetic LEMI-423 site: hx and hy exchanged sample for sample, each linear stage (1/Kmx, 1/Kmy) and the calibrated series following their data, the run and channel comments, no change without the key or with false; the same exchange on an EDL site; a run without hy refused; the variant path unchanged and the variant keeping the swap; a mutation that must trip
python tests/ingest_swap_h_provenance_unit.py # swap_h on two synthetic MTU-5A sites, one declared swap_h: the archived hx carries the hy input's samples, chain, sensor attrs and reader comment followed by the swap_h piece, hy the mirror, hz and the unswapped site their own; channel numbers and azimuths stay with the names; the earlier _swap_h is the mutation that must fail P1 and P2
python tests/ingest_clock_offset_unit.py # clock_offset_s on a synthetic LEMI-423 site of two runs: at -1.0 and 0.0125 every channel's time axis, the run, channel and station periods and the channel summary moved by exactly the offset and every other dataset identical; the run, channel and station provenance comments and the log line; 0.0 the same bytes and attributes as no key; a variant keeping the shift; NaN, inf, beyond 60 s, strings, booleans, defaults:, derived and observatory sites refused; two mutations that must trip
python tests/ingest_h_from_unit.py    # h_from on two synthetic LEMI-423 sites (an electric-only site and a four-channel neighbour with another logger, other coefficients and h_scale, its record offset by seconds and ending inside the local's last run; then with clock_offset_s -1.0 and swap_h): the borrowed hx and hy equal the neighbour's own archive sample for sample at the same instants with its chains and metadata; the local's ex, ey and time axes unchanged; a run left out and a run cut, both recorded; the channel, run and provenance comments, archive_h_from, the log lines, the variant keeping the record; ten refusals; a one-sample misalignment that must trip
python tests/b423_cut_file_unit.py  # four synthetic back-to-back B423 files, the second cut mid-record: two runs, every file's first sample stamped at its file name's start (the old grouping stamped files 3 and 4 2 s early), the warning naming the cut file; the uncut control one run
python tests/b423_rate_callers_unit.py # psd_qc.py's --before read and profile_run.py's B423 read benchmark group the same cut set with the site's rate: files 1-2, not all four; the uncut control all four
python tests/ingest_site_cli_unit.py # ingest_site.py's batch mode (--all, --parallel, a failing site, the single-site lines) and its flagged DC level line for an ey at 1.6e9 counts; the burst site G5H on a cut of the real G5 (one site, --all, a flagged level in V, a burst site whose recorded site has no folder refused)
python tests/variant_held_open_unit.py # a variant rebuild while another process holds the variant open (h5py, mode r; a held copy that os.replace must fail on as the control): build_variant and ingest_site.py --variant --force end in one line naming the file (the script exit 1, no traceback), the .part deleted, the variant unchanged; a rebuild failing midway removes the .part, never the variant
python tests/noise_unit.py           # the filter kinds on synthetic arrays; ingest path == arrays path
python tests/noise_chunks_unit.py    # the mains filter in time chunks over a thread pool (build_variant's chunk_workers): the single pass identical to the stored a937bc4 result (tests/fixtures/noise_chunks, mains and mains then notch on four channels), 8 threads identical to the single pass, a short record, apply_filters_arrays 8 threads == 1
python tests/filter_trial_unit.py    # scripts/filter_trial.py: line excess, floor, coherence and burst/step metrics on a synthetic window with a coherent pair and two lines; a notch removes its line and leaves the coherence; inputs unchanged; the figures and JSON written
python tests/intersite_unit.py       # mt_workbench.intersite and process_intersite.py on synthetic red-noise fields: a known T with a 2 ms delay and a -1.5 deg phase recovered within 3 sigma and the delay returned by the timing check; a 10 ms delay at 1000 Hz followed through its wraps (the earlier unwrap kept as the control), and a band beside a notch that the weighted residual RMS does not follow (the plain RMS the control); T = Z_l M Z_b^-1, T_ab T_ba = I and M_ab M_bc = M_ac to 1e-15 with the linear estimator (the Huber control misses); the base's own channels refused as reference, and a workspace archive with no survey.yaml entry refused as the remote; CSV and h5 round trips; archives with a phase-carrying chain on the base calibrated through the script, the stack's members (local, base, exclude and a short site left out); mutations that must trip: the base's E as reference, the delay's sign, the chains left out
python tests/intersite_stack_unit.py # the band stack of process_intersite.py --remote-stack on synthetic archives: a member with a fault 1000 times its RMS over 5 % of the record rejected in its fault windows, the stack's coherence with the clean common field within 0.002 of the fault-free stack's where the plain stack loses 0.04-0.08; a member whose RMS swings 20x between the halves (a drift) kept at the array level by the per-band scale where the whole-window RMS puts it at 0.004-0.006; a threshold of 1e12 rejecting nothing and equal to the per-band-scaled mean; the members as optional channels of band_spectra (the pair's spectra identical, a member's gap NaN in its own windows only); --stack-plain identical to the earlier pipeline's CSV; the record in the sidecar and the .h5; the dry run's stack_form and the refusals; rejection disabled is the mutation that must trip
python tests/intersite_basestack_h_unit.py # process_intersite.py --base-stack H --kind magnetic on synthetic archives: a local whose H is a known M (-1.5 deg) of a common field recovered within 3 sigma on the H stack of five noisy members, referenced to a third site's E and to the H stack of three other sites built with --remote-exclude (the same --exclude alone refused as sharing the members); stack_scale_rms per band the RMS of the members' scales, the sidecar's units, and the diagonal over stack_scale_rms within 3 % of the member field ratio (the undivided M off by over 50 %, the control); a member with a reversed hx flagged and left out by --screen-polarity drop; E with magnetic, H with telluric and a stray --remote-exclude refused; the sidecar's base_stack block and the h5; the members' own H stack as the reference is the mutation that must trip
python tests/intersite_basestack_unit.py # process_intersite.py --base-stack E on synthetic archives: a local whose E is a known T (2 ms, -1.5 deg) of a common field recovered within 3 sigma on the stack of five noisy members (each column over the members' recorded per-band scales); a member whose record ends inside the window refused, naming it and the time, and recorded with --allow-member-change, the 60 s edge tolerance as the control; a member with a reversed ex flagged (correlation -0.85, the others +0.77 to +0.83) and left out by --screen-polarity drop, its sign restored flagging nothing; a reference sharing a site with the stack refused and allowed with --allow-shared-members; the sidecar's base_stack block and the h5; the command-line refusals; the members' own E stack as the reference is the mutation that must trip
python tests/intersite_runs_unit.py  # per-run chains: a local of two runs with gains x1 then x2 gives the T of one run with one chain within 3 sigma, read_channels records the two chains and gives ex a RunResponses; two runs of one chain identical to one run; the first run's chain on every window is the mutation that must trip
python tests/intersite_stack_edge_unit.py # select_stack with edge_s: members ending 1, 30 or 59 s short of a 6 h window (or starting late, or with a 30 s gap) kept, 61 s short left out, in agreement with member_changes; without edge_s only the whole-window member kept, with the old reason text; process_intersite.py's resolve gives the tolerance to the base stack and not to the reference stack, by flags and by stacks.yaml recipes
python tests/intersite_coherence_unit.py # the weighted coherence: with bursts in 1 % of the local E, coh_out_weighted at least 0.2 above the plain value in every band of 400 windows or more and frac_downweighted at least the burst fraction; equal to the plain value with every weight 1; a dead local ex under 0.05 (the control); the column names and CSV/h5 round trips, an earlier CSV read back with NaN weighted columns
python tests/intersite_flags_unit.py # the five flag columns: an exchanged local E raises flag_off_diagonal and flag_re_det_negative, a dead one flag_low_coherence, and the clean record neither; flag_few_groups equals n_groups < 5 on the estimated rows of a 20 min record, and a row not estimated carries flag_not_estimated alone in the CSV, the h5 and the sidecar's counts; every band of the layout a row (NaN and 0 windows where not formed, a flag never removing a row); the sidecar's flags block and the h5 arrays; merge_tensor_bands.py's shared_bands pairing formed rows only
python tests/intersite_frames_unit.py # the sidecar's frames block and the h5 attribute: each site's azimuths, layout_north and declination as survey.yaml gives them (the defaults for an undeclared survey), marked not applied; T, errors and arg(det)/2 identical with and without the declared frames
python tests/intersite_delay_scan_unit.py # the timing scan: +0.5 s at the 1 s tolerance and -3.0 s at 3000 s recovered within 4 sigma, the alias periods 1024 s and 2048 s; -3.0 s and +30 s at 1 s read as not determined, the reason naming the bound and scripts/timing_qc.py, the sidecar strict JSON (None, not NaN); random band phases never determined in 100 seeds; 0 and a clean 2 ms line recovered
python tests/intersite_masks_unit.py # masks.yaml in inter-site runs: T with a base's mask equal to T with the windows cut by hand to 1e-9, a mask limited to one band touching no other; mask_role and site_masks by scope and channel; the script with entries of each scope on the local, base and reference equal to the hand cut (every scope, or none, the controls), the sidecar's counts; no masks.yaml giving the unmasked T; the burst grid's spans
python tests/intersite_errors_unit.py # the jackknife errors over 50 seeds of clean and bursty fields: the fraction of element and psi deviations within one stated sigma inside 3 binomial deviations of 0.623 and 0.670 (errors x2 and x0.5 the mutations); Huber T and psi with 1 % of windows scaled x1000 at most 5 % beyond 3 sigma and none beyond 5, least squares the control that fails; Huber T = Z_l M Z_b^-1 within 3 combined sigma, local and base exchanged the control
python tests/virtual_unit.py         # synthetic remote from real tiny member archives: the plain stack identical to before; coherence weights (dead coil -> 0, burst chunk down-weighted); streamed == single shot; missing archive, off-grid run, partial run
python tests/stacks_unit.py          # stacks.yaml recipes: block writes with the file unchanged outside the saved block (LF and CRLF), hash test vector, validation, members over select_stack, argv builders (mt_workbench.stacks)
python tests/stack_median_unit.py [--quick] # band median, select_stack(rate, runs_of), stack_arrays, stack provenance (--quick leaves out criterion 10, the four existing stack suites)
python tests/availability_model_unit.py # the Stacks tab's availability rows (mt_workbench.gui.availability_model, no Qt) on a synthetic 1 Hz survey: runs, groups, members per hour, nights, tree windows, rows equal to stacks.resolve_members
QT_QPA_PLATFORM=offscreen python tests/stack_check_unit.py  # Stacks tab member check: coherence, polarity, gaps, preview, MemberCheck reads and lock
QT_QPA_PLATFORM=offscreen python tests/stacks_tab_unit.py  # Stacks tab and the Process recipe picker: rows, stacks.yaml save, Build archive / Queue intersite argv, member check, bar click, the picker's refusals, the masks cost (a form edit with 30,000 masks under 50 ms)
QT_QPA_PLATFORM=offscreen python tests/availability_chart_unit.py  # the Stacks tab's chart (AvailabilityChart) on a 60-site survey with the masks.yaml parse held: no rows pass and no archive stat while it is held, the status says waiting, one row per site and S01's mask within 10 s of the release with one parse; rows at 14 px from the plot's height at two sizes and untouched after a manual pan; a survey change clears the no-archive set; the default window inside the local's record, the fall back when the local records outside every candidate hour, "records nothing in the window" on the status line; four mutations that must trip
QT_QPA_PLATFORM=offscreen python tests/stacks_tab_shots.py [--survey nador] [--out DIR]  # figure script, not a suite: the member check's preview panels and weights plot grabbed from the check widget (below the pane's first screen) on the synthetic survey (STK_H on L, then a time_coherence recipe over its five members) or on Nador read-only (every queue, build and save diverted, every watched file compared before and after); `--out DIR` writes the four PNGs there; exit 1 when a status line, curve count, grab height, power ratio or weight sum is off
python tests/burst_station_metadata_unit.py # process.slim_station_metadata and _keep_processed_runs on a synthetic burst station of 240 one-burst runs: a channel read inside the context carries its one run (every run outside), the RunTS unchanged, the method restored after, 20 runs at least 4x faster, the station getter holding the wanted runs only, the product keeping the runs the estimate used; a mutation that must trip
python tests/stack_recipe_cli_unit.py [--quick] # process_intersite --stack and build_stack --recipe: recipe runs equal the flag runs, records, refusals, archive reuse and safe rebuild (--quick leaves out the five existing suites); exit 2 "NOT COMPLETE", never a pass, when campaign_lineC.yaml is absent (workbench issue 29)
python tests/process_rr_cli_unit.py  # process_rr.py --dry-run, the estimator tweaks, the band-layout flags (--window-samples, --min-bin; --min-bin 0 the layout's own over a survey's min_bin, a negative one refused) in the resolution, aurora's config and the sidecar, run_stem, the sidecar (edi, xml, h5, frame), the quadrant window, the three products of an aurora-shaped TF (DECLINATION lines, HEAD/INFO frame, XML covariance, the h5 read back; mt_metadata's own XML write of it as a control that fails), ZROT = TROT = the declination with Z and T read back equal to a ZROT 0 write at difference 0 and the INFO frame lines, the XML angle and channel orientations read back (D, 90 + D), the RESIDCOV cross term written as 0 (the unmodified writes and the pre-fix Morocco sample as controls that fail)
python tests/unknown_declination_unit.py # a TF with the archive's unset declination (0.0, no epoch): null declination keys in frame_record, no Declination element in the XML (read back by mt_metadata), no DECLINATION line in the EDI; the declared -0.36 kept in all three as the control
python tests/process_rr_pair_check_unit.py # process_rr.py --dry-run on a synthetic survey: a missing raw archive marked missing, both spans printed, a pair sharing no time (survey.yaml spans, and a span read from the archive) and a site without a survey.yaml entry exit 2 with the reason
python tests/short_window_unit.py    # the short-window guards: band_windows under aurora's reversed npts pairing, the min_band_windows floor (the default 2 keeping a 3-window level, the periods removed kept on the TF), the zero/non-finite error guard (a NaN output row left alone, a one-row zero error blanking that row alone, a merged-rows TF keeping each row's own periods, EMPTY in the EDI where a row's run lacks a band), the survey.yaml key kept out of the band scheme; on the bench archives (read-only) the 10 min C18 rr C19 window writes no zero error and no 1-window level and records level 7 as dropped, aurora's own output as the control
python tests/min_band_windows_engine_unit.py # min_band_windows in the resolution and the sidecar: 2, the flag and the survey.yaml key under aurora, the sidecar's dropped_periods (none, then two periods sorted with a repeat counted once); --engine mantle refuses the flag and records both as null
python tests/sidecar_versions_unit.py # process_rr's sidecar versions.installed: per stack package the install source (direct_url, editable, commit), the RECORD and __init__ hashes against the files read here, a stand-in fork and stock install of the same version told apart, one changed RECORD line seen
python tests/compare_imports_unit.py # mt_workbench.compare imports neither mt_metadata.transfer_functions nor matplotlib until rho_phi or plot_comparison needs them (quality too; a control that is seen), rho_phi against a TF read directly, the figure on Agg with no figure left open, pyplot imported first or not
python tests/bands_unit.py           # build_band_scheme: bands narrower than a harmonic refused, the survey layouts unchanged, min_bin and a 256-point window keeping every period while moving the harmonics (mt_metadata's Band indices); one min_period at 150 Hz, 1000 Hz and 24 kHz (4**(14/6)/6000 or 4**(22/6)/6000 s): every edge on 6000 / 4**(k/6) Hz, top edges 37.2047, 236.235 and 6000 Hz, aurora's assign_bands giving every band a harmonic, the 150 Hz layout unchanged, site_min_period's values and process_rr's resolve on a 150 Hz and a 1000 Hz pair; the old quarter-rate cap is the mutation that must trip
python tests/engine_mantle_unit.py   # the MANTLE engine: options -> ProcessingConfig, levels_for, band pooling with the jackknife variance, to_tf round trip, the sidecar keys, --engine and --mantle-max-hours on the command line, the window limit (check_window and process_pair on a stub reader) (skips when MANTLE is not installed)
python tests/decimate_unit.py        # decimate_site.py on a synthetic two-run LEMI-423 site: 100 s and 20 s sines within 0.5 % and 0.5 deg at 1 Hz, a 0.7 Hz sine gone, the calibration chain copied, starts on whole seconds, the run groups typed `Run` as ingest's are (MANTLE's reader needs it), --force, the survey entry; process_rr.py at 1 Hz
python tests/dc_level_unit.py        # dc_level_check.py (mt_workbench.dclevel's measure) on a synthetic archive: a channel at 1.6e9 counts flagged as an open input, healthy channels not, the rail rule, derived and observatory sites skipped, exit 2 for a missing archive; the Phoenix input rail on synthetic volts: a drifting E flagged at its own rail and not at 2.25 V, a railed E flagged at both, the flag line naming the rail, the note round trip (rail ignored is the mutation); dc_level_check.py on a 150 Hz run whose comment carries the dc rail line (the drifting E ok at 2.25 V, the railed E saturated?) and a control run without it (both saturated? at their own rail; the comment's rail not read is the mutation); the rail record's key dot-free (the dotted key is the mutation) and the 4beb3cd dotted key still read back, in the note and by dc_level_check.py on a third run
python tests/merge_modes_unit.py     # merge_modes.py on two synthetic EDIs: x row from A, y row from B copied and interpolated in log period, NaN outside B's range, the tipper kept, the sidecar keys (edi, xml, h5), exit 2 on a station or remote mismatch
python tests/harvest_notes_unit.py   # harvest_notes.py on a synthetic notebook: an uncited report and a missing figure fail (exit 1), a glob with no match and a citation of a missing report fail, the repaired notebook passes, index.md and manifest.csv, a synthetic journal copied once (names, date from the journal, verdict pairing), two mutations that must trip
python tests/organise_qc_unit.py     # organise_qc.py on a synthetic qc tree: a site, a line, a survey and an unknown item land in qc/lineA/A01, qc/lineA/line, qc/survey/night_ss and qc/unsorted (a derived site under its parent, C21new under C21, an old line folder sorted); the dry run moves nothing; a note's relative and a report's absolute citations rewritten; a second --apply moves nothing; tf/ and the kept line-scan table untouched; three mutations that must trip
python tests/basemap_unit.py         # fetch_basemap.py: warp, provider, zoom rule; network mocked
python tests/new_survey_unit.py      # new_survey.py on synthetic B423s, a mixed LEMI-423/424/EDL root, Curnamona
python tests/profile_unit.py         # scripts/profile_run.py: phases from a real process_rr log excerpt, nested marks, the psutil sampler on a sleep child; the trace stage's marker spans on a stub (and through viztracer when installed) and its tracemalloc diff table (`--stage trace`: viztracer + py-spy + tracemalloc passes of one windowed estimate, fork and stock aurora; dev tools viztracer, py-spy)
python tests/mth5_fork_unit.py       # the mth5 / mt-metadata forks (../mth5, ../mt-metadata, with ../mt-io, branch mtproc-fixes) on PYTHONPATH, the installed packages reported beside them: read-only opens, run id warning, no-harmonic band, to_runts/time_slice time against stock (while stock is installed); with ../mt-timeseries (src/) too, and against the installed mt_timeseries: the 10.00064 Hz and 1.5 Hz index, the RunTS station's channels (no auxiliary_default); skipped without the clones
python tests/aurora_fork_unit.py     # aurora fork 0.6.2+mtproc (installed, or the clone at ../aurora) against stock-0.6.2 fixtures: Z identity, config window masks, time and memory; with the fork installed, the clone's estimate compared with it; fixtures only without the fork
python tests/mtio_fork_unit.py       # mt-io fork (the clone at ../mt-io, or installed) on synthetic files: issues 6, 7, 8, 18, 19, 21; the installed mt-io reported check by check (stock 0.0.5 fails all six); skipped without the fork
python tests/orangebox_unit.py       # mt-io's Orange Box reader: the synthetic layout, the 10.00064 Hz rate kept, files that do not join refused; one real Stuart Shelf hour against the legacy converter (skipped without the raw-data drive)
# (tests/instrument_samples.py cuts the one-hour LEMI-424 and EDL samples from the raw-data drives, read only)
```

New dependencies (`pyproject.toml`): `PySide6` and
`pyqtgraph` for the GUI itself, and `mtpy-v2` (2.1.4) for the View EDIs tab's
rho/phase and phase-tensor plots (induction arrows later), which also drags
in `contextily` + `xyzservices` (reused by `scripts/fetch_basemap.py`'s tile
fetch), `geopandas`, `rasterio`, `pyproj`, `simpeg`, `bokeh` and `panel`.

## Status

- [x] LEMI-423 ingest -> MTH5 (contiguous B423 files merged into long runs, a
      new run at any file-spacing anomaly; per-survey `channels` list drops the
      unconnected hz; per-survey `flip_reversed_dipoles` says whether a 180/270
      field-sheet azimuth means a reversed pair: true at Curnamona, false at Burra)
- [x] Aurora single-station / remote-reference wrapper -> EDI, with a
      processing window and an automatic impedance-phase-quadrant check
- [x] Comparison plots against legacy lemimt EDIs
- [x] Validation vs lemimt on a clean Curnamona Cube pair: D02 RR E08 matches
      the merged lemimt EDI over 0.005-~3000 s (rho and phase, both modes)
      with the lemimt-style 60-band scheme
- [x] Burra (noisy) first results: Burra35 RR Burra54rr3 matches lemimt
      0.005-1 s and 15-1000 s on its good-Ex window; Burra57 matches 15-1000 s;
      the 0.3-15 s cathodic-protection band is the open
      problem
- [x] Timing QC before ingest (`scripts/timing_qc.py`): no clock errors found
      at the Burra "Behind" sites; the one 1 s event is a remote file-boundary slip
- [x] Noise toolbox, first steps (`mt_workbench.noise`, `mt_workbench.ingest`; declared per
      site in `<survey>/filters.yaml`, applied at ingest in the listed order,
      provenance written into the archive): `replace` (borrow a magnetic
      channel from another site, with that site's coil calibration: the field
      crews' "replace magnetics" for a dead coil), `notch` (50 Hz + harmonics,
      zero-phase) and `cp` (cathodic protection: stack every cycle at the
      declared period in 10-min windows and subtract the median cycle from
      every channel, with no detection or cutting), declared by hand
      after looking at the QC figures.
- [x] Noise toolbox: `hp` and `lp` (zero-phase Butterworth), a
      `channels` list on `notch`, `mt_workbench.noise.apply_filters_arrays` (the one
      implementation; ingest delegates to it) and the Filter Data tab's
      live preview of the list on a loaded window.
- [ ] Noise toolbox, next: per-channel time masks, band schemes
- [ ] Band-placement experiment around mains: 50 Hz at band edge vs notched
      vs band centre (anchor option in bands.py), same data three ways
- [x] Stacked/synthetic remote references from multiple array sites: mean
      stack implemented and tested on D02 (found A07's dead hx in the process)
- [ ] Coherence-weighted stacking: per-member weights per time chunk and
      band group (0.1–1, 1–10, 10–100, 100–1000 s), then full per-band
      weighting at the Fourier-coefficient level; median stack as the
      robust baseline. Built: chunk-wise coherence weights
      (`mt_workbench.virtual`) and the band median (`mt_workbench.intersite`).
      Still open: per-band weighting at the Fourier-coefficient level.
- [x] Time-resolved coherence QC (`scripts/site_qc.py`, ported from the AusLAMP
      figures): whole-record overview, band coherence vs time, coherogram and
      spectrogram for Bx–Ey, By–Ex, Bx–By, Ex–Ey and the local-E vs remote-B
      pairs, the input for stack weights and time masks (next)
- [x] New-survey bootstrap from a raw folder (`scripts/new_survey.py`): B423
      headers -> `survey.yaml` via mt-io, `--site-table` merge, also reachable
      from the GUI's Metadata tab ("New survey...")
- [x] Channels recorded, per survey and per site: the presets in
      `mt_workbench.survey.CHANNEL_PRESETS` (LEMI-423: Ex Ey Bx By, + Bz,
      magnetics only, Bx By Bz; LEMI-424: E1-E4 Bx By Bz, E1 E2 Bx By Bz,
      Bx By Bz), `new_survey.py --channels` for the survey default, the
      Metadata tab's channels column for a site that differs
- [x] LEMI-424 and Earth Data PR6-24 (EDL) ingest and GUI (see
      "Instruments" above): the instrument detected per site folder,
      `instrument:` per site, the readers' own channel names in the archive
      and in every GUI view
- [x] Electric chain gain, EDL sites only (`electric_gain`):
      extra gain of the electric chain between the dipoles and the recorded
      values, beyond what the reader already models (the x10 terminal box),
      hardwired at the field terminal junction box, declared from the field
      notes when the PR6-24's own configs were not kept (Stuart Shelf 2009:
      10.0), `new_survey.py --electric-gain` for the survey default, the
      Metadata tab's `electric_gain` column for a site that differs
- [ ] An `electric_pair` setting saying which two of a LEMI-424's e1-e4 are
      Ex and Ey (aurora's LEMI12/LEMI34 nomenclature in `mt_workbench.process`); the
      GUI meanwhile pairs the first two electrics, E1 and E2
- [x] Desktop GUI (`src/mt_workbench/gui`): PySide6 + pyqtgraph
      launcher-and-viewer over the scripts and per-survey YAML, with QC,
      filter, processing and EDI tabs; see "The GUI" above
- [ ] Cross-power editor: the GUI's Cross-powers tab. Every STFT window's
      cross-powers are computed once (`mt_workbench.crosspower.compute_windows`), then per base
      chunk (10, 5, 2 or 1 min) and per decimation level on groups of base
      chunks long enough for 4 windows and 32 degrees of freedom, regrouped
      instantly without reading the archives, a window inside a larger store
      rounded out to whole minutes; |Z|, phase, coherence, |H| and |E|
      against time and the polar plane (log10 |Z| against phase per mode,
      the yx phase plus 180 deg wrapped to (-180, 180] as `cluster_masks.py`
      draws it, `mt_workbench.crosspower.mode_phase`, so a near-field source's yx
      cluster sits near 0 deg rather than across the +/-180 deg edges);
      masks per window and band saved per
      site as UTC intervals in `<survey>/masks.yaml`, `process_rr.py`
      applying the station's and the remote's of scope both (Process tab
      "apply masks.yaml"). Each entry's `scope` is `local` (the default,
      and what the tab, `cluster_masks.py` and `gate_masks.py` write: the
      mask applies when its site is the local of a pair, and the pairs
      that use the site as their remote keep those windows), `both`
      (also when its site is the remote) or `remote` (only when its site
      is the remote). An optional `channels` list (ex, ey, hx, hy, hz;
      every channel without it) says where the noise is: an entry naming
      only ex, ey or hz leaves out those TF rows alone as the local and
      nothing as the remote, one naming hx or hy leaves out whole windows.
      Entries taken out of use move to `masks_history.yaml`
      (`scripts/retire_masks.py`). Still open: the stacked editor
      estimate (`stack_impedance`, a window-count-weighted jackknife from
      5 groups) written as an EDI
- [ ] Burra in the GUI (93 sites, remotes filled per stage, `filters.yaml` for
      Burra35/57, timezone set; the config side is ready, untested in the GUI)
- [ ] EDL broadband (LEMI-120 coils on the PR6-24, `sensor_type="lemi120"`):
      only the Bartington long-period chain is wired
- [ ] Batch CLI
