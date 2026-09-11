# What to borrow from the MATLAB field app

The owner's framing, in his words: "while a lot of the things from the matlab
app we don't need as we'll use the mth5 files and mt-io as the backend, there
are still a lot of very good things we can re-use or borrow from it, especially
regarding the processing side of things". Two readers went through
`MT_Field_App_2026_Jan_16a.mlapp` (23,623 lines of App Designer source, about
405 functions) feature by feature, one on the processing side and one on the QC
and filter side, and cross-checked every claim against this repo. What follows
is the result: for each MATLAB feature, the rule or formula it actually
implemented, what the Python side has today, and whether it is worth borrowing.
Several MATLAB features turned out to be dead code, wired into the UI but never
read; those are marked, because knowing not to port them is worth as much as
knowing what to port.

Three whole areas are deliberately not carried over. **File bundling**: the
app's "load a bundle of B423 files into memory, one working directory per site"
step is replaced by one MTH5 per site holding the whole deployment, read
lazily. **lemimt invocation**: writing `Process_Job_NN.txt`, calling
`lemimt.exe -r [-f] [-c]`, one EDI per frequency and chunk, and the
harmonize-frequencies step that existed so an external tool could merge them,
are all replaced by aurora; lemimt EDIs survive only as the validation
reference (`reference_edis.yaml`, `bbmt.compare`). **Single-station options**:
five of the app's six processing modes, the single-site list box and the
local-E-plus-remote-H substitution are ruled out by decision, not by oversight
(`HANDOVER.md`, "Decisions made": every product is remote-referenced). Where a
MATLAB feature exists only to serve one of those three, its row below says
"drop" and nothing more.

## Processing

| MATLAB feature | Rule or formula | Python status | Recommendation |
|---|---|---|---|
| Station / remote / mag-replace dropdowns (`StationtoProcessDropDownValueChanged`, `ProcessSiteList`) | Picking a station removes it from the other two lists; each change refills `SingleSiteList` / `RemoteSiteList` / `MagChannelReplaceList` | have: `bbmt_gui/tabs/process.py` (`station_combo`, `remote_combo`, preselected from `remote:` in `survey.yaml`) | Drop the self-exclusion machinery: one remote slot, not three interacting lists |
| Best-remote recommendation (`findBestRemoteSite`) | Skip `dist < 0.1 km` or `overlap < 1 h`, then `score = 0.7*dist_km + 0.3*ovlp_hr`, **max** wins (unnormalised, so distance dominates and it prefers the farther site) | missing: no distance or overlap is computed anywhere in `bbmt` | Adapt, do not copy the formula. Show distance and overlap hours as two columns on the Metadata tab so a declared `remote:` can be checked; the scoring rule itself is unsound |
| Processing window: slider, UTC and local fields (`SlideBar`, `updateProcessingWindowFields`, `SelectData_Slide`) | ROI line on a hidden axes; the window selects whole files by epoch overlap **plus one neighbour file either side**; no minimum-length check | have, tighter: `ProcessTab.start_edit` / `end_edit` into `bbmt.process.clip_to_window`, which trims aurora's run intervals exactly and raises if nothing is left | Borrow the gesture only, already done: the Time Series tab's "Use visible range as processing window". Do not borrow whole-file selection or neighbour padding |
| Local-time display on the window fields | Site timezone from lat / lon, label such as "(ACST)" | missing: UTC everywhere | Adapt, low cost: show the local equivalent as a read-only suffix beside the Process tab window fields. Students read field sheets in local time |
| Batch queue (`addtoQueueButton`, `ProcessQueue`, `resetQueueButton`) | `BatchQueue` struct array, about 25 UI fields captured per entry; loop with try / catch that logs and continues; no persistence, no dedupe | have: `bbmt_gui/jobs.py` (`JobRunner`, FIFO of `Job(label, argv, ...)`, same log-and-continue behaviour) | Borrow as is, already done. A queue entry being the literal command line beats a 25-field struct |
| Parallel workers (`ParallelProcessingCheckBox`, workers spinner) | Local `parpool`, one `parfeval` per frequency or chunk within a run | missing by design: one job at a time across the whole app | Drop. An MTH5 must never be open in two processes (`HANDOVER.md` fact 8), a tighter constraint than MATLAB's |
| Processing mode selector, six modes (`getProcessingConfig`) | Table of MT / E-Field / B-Field crossed with single-site / with-remote; the E and B modes force `ReplaceMag=1, Bx=1, By=1` | missing: only remote-reference MT exists | Drop. Validated as wrong: D02 with E08's H came out 28 to 32 % off lemimt |
| Replace B-field channel (donor dropdown, Bx / By checkboxes) | The donor's files are read over the run span and substituted in `ProcessDataTT` step 9, with channel-order remapping | have, reshaped: `bbmt.ingest._replace_channels` plus the `replace:` kind in `<survey>/filters.yaml`, applied at ingest with the donor's own coil calibration | Borrow as is, already done and better. Proven on A07 (dead hx from A06, 32 km) |
| Swap Bx / By on the same site (`SwapMagChannelsCheckBox`) | Exchange the two magnetic channels of one site | missing | Adapt: add a `swap` kind to `bbmt.noise` and `filters.yaml` alongside `replace`. Same ingest-time operation, and it covers a miswired coil pair |
| Flip Bx / Flip By (`FlipBxCheckBox`, `FlipByCheckBox`) | Negate a channel's polarity scale in the lemimt config | missing for H; the `flip_reversed_dipoles` rule is E-dipole layout polarity, a different thing | Adapt: the same new `filters.yaml` entry as the swap, one flag per axis. Cheap insurance against a reversed coil |
| Rotate long-period magnetics (`Rotate_LP_MagCheckBox`) | `theta = atan2(mean(By), mean(Bx))`, then rotate every Bx / By pair to that angle | missing | Drop for now. A mean-field alignment trick with no validation behind it; revisit only if a long-period site needs it |
| Coherence pre-sorting (`CoherencePresortingCheckBox`) | Passed to lemimt as `-c` | missing as a switch; the related work is `bbmt.qc.band_coherence` and `scripts/coherence_qc.py` | Drop the switch (aurora has no matching flag). The real version of this idea is coherence-weighted stacking, already on the roadmap |
| Correct sensor response (`SensorResponseCheckBox`) | lemimt `-f`; without it lemimt works in raw counts | have, always on: `.rsp` to `FrequencyResponseTableFilter` plus the `h_scale` coefficient filter, applied at ingest | Drop the toggle. The useful half is the warning a site with no `calibration_fn` already gets |
| Sample-window-length spinner | `rowsPerChunk = SampleWinM * 1e6 * factor`, sizing the chunk handed to `lemimt.exe` | not applicable: aurora manages its own STFT windows per decimation level (`bbmt.bands`, `num_samples_window`, `band_edges`) | Drop. Different concept, and exposing it would invite students to break the band scheme |
| EDI naming (`makeSiteName`) | One EDI per frequency and chunk; the name encodes every switch, e.g. `MT-<SS>_RR-<RR>_<f>Hz_<ts>_Job<NN>[-CP][-MR]` | have, simpler: `<local>_rr-<remote>` plus a compact window suffix, one EDI per run | Adapt one idea: record which filters were applied in the tag or the EDI INFO block. MATLAB tried and failed, since its `isfield(cfg,'filters')` test checks a field that never exists |

## Time sync

| MATLAB feature | Rule or formula | Python status | Recommendation |
|---|---|---|---|
| Sync lamps (`recomputeSyncStatus`, `overlapStatus`, `colorFor`) | Window `[t0,t1]` against remote file bounds `[r0,r1]`: 2 = inside, 1 = partial, 0 = none, mapped to green / amber / red / grey | missing as a view; the same intersection happens silently in `clip_to_window` and aurora's `restrict_run_intervals_to_simultaneous` | Adapt: one status line on the Process tab ("remote covers 100 % of the window", or the hours it does not). A traffic light before a 13-minute run is cheap |
| "Time window in sync" labels (`setSyncText`) | Wording such as "partially in sync, adjust window" | missing | Borrow as the wording for the status line above |
| Site bounds from file names (`getSiteBounds`, `filenamesToEpochSeconds`) | Parse 10 / 11 / 12 / 14-digit epochs out of the B423 file names, all UTC | have: `bbmt.ingest.select_files` and check (a) of `scripts/timing_qc.py` | Borrow as is, already done and stricter: it flags the 5401 / 5399 s file-boundary slip |
| Any real clock check | **None.** Zero cross-correlation anywhere in the source; every "GPS" hit is lat / lon parsing. "Time sync" in this app means file coverage only | have, more than MATLAB ever did: `scripts/timing_qc.py` check (b) cross-correlates hx / hy, 3 to 40 Hz, plus or minus 5 s lag, 10 ms resolution, and **fails above 50 ms**; check (c) reads the B423 `sync` / `stage` GPS bytes | Nothing to borrow. Keep the check on the Process tab button, and say in the GUI hint that the MATLAB lamps never did this |
| Impedance phase-quadrant check | Not present; the polarity table is trusted silently | have: `bbmt.compare.phase_quadrants`, called by `scripts/process_rr.py` (xy in 0 to 90 degrees, yx in -180 to -90) | Nothing to borrow. This is the automatic sign-error catch MATLAB lacked |

## QC views

| MATLAB feature | Rule or formula | Python status | Recommendation |
|---|---|---|---|
| Field statistics after load (`collectFieldStatistics`, `calculateFieldStatisticsSimple`) | Per-channel mean and std of the finite detrended samples, printed as "mean Bx: m +- s nT". No thresholds, no flags | partial: stats are computed for display in `bbmt.qc` and `bbmt_gui/segment.py`, but there is no one-shot printed summary | Adapt: a small stats table under the Time Series overview. It is the fastest units-and-scaling sanity check there is |
| Derived field quantities (`calculateFieldStatistics`, dead in this build) | `Btotal = sqrt(Bx^2+By^2+Bz^2)`, `Bh = sqrt(Bx^2+By^2)`, `inclination = atan2d(Bz,Bh)`, `declination = atan2d(By,Bx)`; fluxgate check `if abs(mean By) > 1 nT: correction = -atan2d(byMean, 50000)` | missing | Adapt the declination part only. With no hz on any broadband deployment, `Btotal` and inclination are unavailable, but `atan2d(By,Bx)` against the IGRF value is a real coil-orientation check |
| Multi-taper PSD tab (`computePSDAndCoh_TT`) | `pmtm` with `NW=4` (K = 2NW-1); decimate by `floor(fs / max(2.5*fmax, 200))`, `nwin = max(256, 4 s * fsEff)`, `nfft = 2^nextpow2(...)` capped at 16384; up to 64 windows spaced across the record, each detrended | missing: all spectral QC is Welch only (`bbmt.timefreq`, `scripts/psd_qc.py`) | Adapt if a student needs it, as an alternative estimator in `bbmt.timefreq` behind the existing ladder. Lower priority than it looks: aurora does the estimation that reaches a product |
| Welch tab (`welchPackTT`) | `winSec = min(round(N/8)/fs, 60)`, overlap 0.75, `nfft = 2^nextpow2(nwin)`, **symmetric** Hamming (the periodic one leaked), scale `fs * sum(w^2) * nSeg`, one-sided doubling; coherence from 7-bin boxcar-smoothed cross spectra | have: `bbmt.timefreq` (`window_spectra`, `cascade`, `psd_ladder`), `scripts/psd_qc.py` (fixed `nperseg = 2**16` on a four-stage decimate-by-10 ladder), `bbmt_gui/tabs/spectra.py` | Borrow one detail, the symmetric-window note. Keep the ladder: it is built for archive-length records, which MATLAB's single adaptive window is not |
| Spectrogram compute (`plotSpectrogramTT`) | `winSec = 2`, overlap 0.8, `nfft = 2^nextpow2(max(nwin, fs/0.5))` capped at 2^18, NaNs linearly filled, `Zabs = 10*log10(P + eps)`; the complex STFT is cached so a mode switch never recomputes | have: `site_qc.py` figure 04 and `bbmt_gui/tabs/spectrogram.py`, log-period binned | Borrow the caching idea for the segment QC window, not the parameters |
| Spectrogram relative modes (`SpecViewButtonGroup`, `SpecBaselineButton`) | Absolute: `Z = Zabs`. Relative: `Z = Zabs - median(Zabs, 2)`, the per-frequency median over the whole record. Delta: `Z = Zabs - baseline`, the per-frequency median over **only the currently zoomed x-window**, stored per channel. Workflow: zoom to a quiet interval, press Baseline, switch to Delta | missing: a fixed 2 to 98 percentile absolute dB view only | **Borrow, the highest value on this page.** Subtracting the per-frequency median kills the 1/f slope that hides intermittent noise. Lives in `bbmt.timefreq` (the subtraction) plus a three-way radio group on the Spectrogram tab |
| Colour-scale percentiles (`SpecColourScaleDropDown`) | Full 0 to 100, Wide 5 to 95, Robust 10 to 90, Tight 15 to 85 percentile of the finite Z; symmetric about zero in the centred modes, otherwise a 5 % pad each side | partial: one hard-coded 2 to 98 | Borrow as is: a four-item dropdown on the Spectrogram tab. It teaches that "the plot looks noisy" is often just clipping |
| Log-frequency axis toggle | Pre-resampled onto an 80-points-per-decade log grid with `makima`, no recompute | have by default: log period everywhere | Drop |
| Coherence tab (`plotCoherenceTT`) | `Coh(f,t) = abs(movmean(S1 conj(S2)))^2 / (movmean(abs(S1)^2) * movmean(abs(S2)^2))`, time smoothing `max(5, nWindows/100)`, six log-decade bands, with a mean-over-frequency curve on top | have, wider: `site_qc.py` steps 02 and 03, `bbmt.qc.band_coherence`, `scripts/coherence_qc.py`, which also cover the local-vs-remote and local-vs-stack pairs | Borrow one thing: the thick "all frequencies" mean curve drawn over the per-band lines. Otherwise keep the Python version |
| Least-squares quick-look (`plotLS_Impedance_MTvsWelch`) | `Zxy = mu0 K S_ExBy / S_ByBy`, `rho = abs(Z)^2 / (mu0 w)`; gate on `coherence >= 0.50`; then a 3-MAD trim on `log10(rho)`: `madv = max(1.4826 * median(abs(lr - med)), 0.05)`, keep `abs(lr - med) <= 3 madv`; phase wrapped to plus or minus 180 | missing: nothing stands in front of aurora | **Borrow, second highest value.** A single-site QC plot is not a product, so it does not breach the no-single-station rule. Lives in a new `scripts/ls_quicklook.py` calling `bbmt.timefreq`, shown on the Spectra tab |
| View EDIs tab (`EDI_Viewer`) | Rho and phase log-log with error bars; phase-tensor ellipses coloured by beta, phimin or phimax; tipper `abs(T)`; X and Y limit fields. **Single selection, no overlay** | have and better for the core view: `bbmt_gui/tabs/edis.py` overlays any number of EDIs plus the lemimt references. partial: no phase-tensor ellipses | Adapt later: the ellipses are worth having, the tipper is not (no hz on any broadband deployment, so no tipper is produced) |

## Filters

| MATLAB feature | Rule or formula | Python status | Recommendation |
|---|---|---|---|
| 50 Hz and harmonics (`PopulateNotch`, `generateHarmonics`) | `[50-w, 50+w]`, or 50, 100, ... 450 Hz each plus or minus `round(w,1)`; `WidthSlider` is the half-width in Hz, limits 0.1 to 5, default 1 | have, equivalent: `bbmt.noise.mains_notch` (zero-phase `iirnotch` comb) with `f0`, `harmonics` (default 9, the same), `q` (default 30, about plus or minus 0.83 Hz at 50 Hz), `passes` (default 2) and an `extra` line list MATLAB has no equivalent of | Borrow as is, already done. One improvement in `filter_forms.py`: print the half-width in Hz next to the q spinbox, so the knob means the same thing to a student |
| High-pass and low-pass (`buildButterSOS`, `applyFilterOneChannel`) | `butter(4, Wn, type)` into `tf2sos`, applied zero-phase, cascaded in the fixed order high-pass, notch, low-pass | missing: `filters.yaml` knows only `notch`, `cp` and `replace` | **Borrow.** Add `hp` and `lp` kinds to `bbmt.noise` and `filter_forms.py`, applied in the declared order like every other kind |
| Pre-whitening (`PrewhiteningCheckBox`, order 1 to 9) | 1 = first difference, 2 or more = AR filter. **Dead**: the worker command is literally `lemimt.exe -f -r <txt>`, so the flag was never passed | missing, and not needed: aurora pre-whitens internally | Drop |
| "Filter for" channel groups (`FilterforDropDown`) | 'All channels' / 'Bx Ey' / 'By Ex'. **Dead**: the value is never read | partial: `bbmt.noise.apply_filters` scopes `cp` by an optional `channels` list, but `notch` and `replace` always hit every channel | Adapt: extend the `channels` option to `notch` and to the new `hp` / `lp`. Python already implements for one kind what MATLAB only mocked up |
| Save and load filters (`SaveFiltersButton`, `LoadFiltersButton`) | `<WorkingDir>/<site>/Filter.json = {notchesHz, hpHz, lpHz, detrend}`, with legacy CSVs upgraded on load | have, cleaner: one `<survey>/filters.yaml` for the whole survey, edited on the Filter Data tab | Borrow as is, already done. Keep the single file |
| Run filters, raw versus filtered comparison (`RunFiltersButton`) | Builds the filtered matrix and redraws the time series and a Welch PSD from it, beside the raw | partial: `scripts/psd_qc.py --before` gives the same comparison, but only as a script run over the whole record after ingest | **Borrow the immediacy**, not the mechanism: apply the declared list to the loaded QC window (1 to 3 h) through `bbmt.timefreq` and draw before and after on the Filter Data tab. The segment QC engine already loads exactly that window |
| Preview versus applied split (`FilteredCheckBox`, `NotchFilterUserCheckBox`, `HzFilterCheckBox`) | The Filter tab's `FilteredTT` is **never** what gets processed. `ProcessDataTT` re-decides: "USER SELECTED" loads each site's own `Filter.json`, else "50 Hz Filter" applies a uniform 50 plus or minus 1 Hz comb to every site, else nothing | have, structurally safer: `filters.yaml` *is* the applied config; `ingest_site` reads it at ingest and writes the provenance into the run comments | Drop, and say so in the Filter Data tab hint. This was the worst trap in the app: a student could tune a filter and silently process without it |
| Ordering hazard | None in MATLAB, which filtered in memory per plot | have: the Filter Data tab warns that an existing `.h5` predates a filter edit, with a "Delete archive" button | Keep. It is the price of filtering at ingest, and it is the right trade |

## Metadata

| MATLAB feature | Rule or formula | Python status | Recommendation |
|---|---|---|---|
| Survey table, one row per site (`populatePage`, `metaPV_ensureSchema`) | Identity, timing, geometry, sensor type, power and contact QC, free text; the single source of truth for every tab | partial: `bbmt_gui/tabs/metadata.py` shows `survey.yaml` (dipoles, azimuths, lat / lon / elevation, remote, raw folder and archive present, filters yes or no), read-only | Keep it read-only. `survey.yaml` is generated from the field sheet by `scripts/site_table_to_yaml.py` and `scripts/burra_notes_to_yaml.py`; a GUI editor would fight the generator |
| Electrode contact QC columns | `ResistanceNG / NS / EW` in kOhm, `VoltageNG / NS / EW` in mV, battery voltage at start and end | missing: not in `survey.yaml`, not in `SiteConfig` | Adapt: optional fields on `SiteConfig` (`src/bbmt/survey.py`), filled by the two generator scripts, shown as a column group on the Metadata tab. Contact resistance is the field QC step students skip and it explains half of all bad-Ex sites |
| Autofill from file headers (`metaPV_autofillFromSiteDir`) | Sample rate, serial, firmware, lat / lon / elevation, start and finish, deployment length and timezone read from the raw headers and shown read-only | partial: `scripts/burra_notes_to_yaml.py` already cross-checks positions against `lemi423_metadata_summary.csv` | Adapt in the generators, not the GUI: always write the header-derived values and flag any disagreement with the field sheet into the site's `notes` |
| Save validation (`metaPV_save`) | Site name non-empty and unique (auto-renamed on collision), `FinishTime >= StartTime`, `SampleRate > 0`. That is the whole validation: no azimuth or dipole range checks | missing: there is no editing form, so no save step exists | Adapt into the generators: validate azimuths in 0 to 360, dipole lengths in a plausible range, and finish after start, as warnings when the YAML is written |
| Instrument dropdown | LEMI-423 / EDL / LEMI-424 / MTU-5C / 5A / 8A / Orange-Box | have at survey level: `instrument:` in `survey.yaml` | Keep. A per-site instrument field only matters once Earth Data ingest lands |
| Map (`UpdateMap`) | `geoaxes` on a landcover basemap, `geoscatter` of every site, the selected station green, its remote blue, a donor site magenta, redrawn on every dropdown change | missing: no map anywhere in `bbmt_gui` | Adapt, later and offline: a plain lat / lon scatter on the Metadata tab (matplotlib, no basemap, no network). The value is the remote-pairing gut check, not the imagery. Since 2026-09-23 (the owner asked for a map background): the scatter is on the Process tab (pyqtgraph) over `<workspace>/basemap.png`, fetched once online by `scripts/fetch_basemap.py` (the Fetch basemap button) and drawn offline |

## The five most valuable things to borrow next

1. **Spectrogram relative-to-median and baseline-from-zoomed-window modes.**
   The raw dB spectrogram is dominated by the 1/f slope, which is exactly what
   hides the intermittent noise a student is looking for; subtracting the
   per-frequency median flattens it and the anomalies jump out. A small change
   (one subtraction in `bbmt.timefreq`, one radio group on the Spectrogram tab)
   for the biggest gain in what the existing figures actually show.
2. **The least-squares quick-look with its coherence gate and 3-MAD trim.**
   It puts a cheap single-site sanity plot in front of a 13-minute
   remote-reference run, and it teaches the two rules of thumb worth
   internalising: do not trust an impedance estimate below about 0.5 coherence,
   and an isolated spike is powerline, not signal.
3. **Declarative high-pass and low-pass filter kinds in `filters.yaml`.**
   This is the only standard time-domain filter the Python pipeline cannot
   declare; a site with a DC drift or a strong out-of-band interferer has no
   knob at all today, and the cascade-order lesson (high-pass first, low-pass
   last) comes free with it.
4. **Before-and-after filter comparison on the loaded QC window.** Students
   currently declare a filter, delete the archive, re-ingest, and only then
   find out whether it helped. The segment QC engine already holds the 1 to 3 h
   window in memory, so applying the declared list to it turns a slow feedback
   loop into a fast one.
5. **Remote-pairing distance and overlap, as two Metadata columns.** Every
   product is remote-referenced and the pairing comes from a `remote:` field
   that nothing validates; showing kilometres and overlap hours catches a stage
   mismatch or an absurd separation before a run, without adopting MATLAB's
   unsound max-distance scoring and without needing a map.

Deliberately not on that list: the multi-taper PSD. It is the cleanest
capability gap on paper, but aurora does the estimation that ends up in a
product, and the Welch ladder in `bbmt.timefreq` already answers the questions
the QC figures ask. Build it when a student has a specific spectrum they cannot
resolve, not before.
