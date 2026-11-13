# Work log

What was done, how it was tested, where the evidence is, and what was decided.
One entry per piece of work, newest first. Evidence paths are under the
survey workspace `D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace` unless
given in full; `qc/reports/` holds the harvested workflow results and
`surveys/<survey>/notes/` the processing notebook. Times are Perth (WAST).

## 29 Oct 2026

**The stack feature: a deep dive** (06:1x-11:0x, 29 Oct; `docs/stack_deep_dive_20261029/`, local with the rest of docs/: PLAN.md, 01_code.md, 02_evidence.md, 03_literature.md, 04_theory.md, 05_benchmark/, 06_real_data/, 07_skeptic.md, README.md, DECISIONS.md). The author asked what the stack gives and costs, whether the mean is the best rule and whether a stronger reference can be built; the lead session planned and wrote the synthesis, agents did the reading, the theory check, the benchmark, the real-data passes and the skeptic. Done: the code read (28 limits, probes P1-P3), the evidence (26 trials), the literature (77 papers), the theory (the remote-reference variance (1/n)(1/SNR_E + 1/SNR_H) q with q = (1 + 1/SNR_R)/rho^2, so any reference gains at most sqrt(1/q_record) and the 0.8 rule needs q at least 1.5625; a reference carries no datum, a base does), a registered synthetic benchmark (criteria hashed before the run; 7 regimes, N 2-12, 14 candidates including the covariance rules k1-k3), D1 (17,602 band rows of existing products placed in the q regime), D2 (the processed curves of Vulcan Nov 2024 Z at three sites, Nador M on six nights at three sites and the Kalkaroo G5|G6 control under every reference kind, each product of record reproduced to 1e-12 first), D2k (k1-k3 on the real sites) and a skeptic that recomputed every verdict from the tables. Verdicts: among healthy members no rule beats the plain mean by more than the variance law allows (1-10 %), and nothing beats the band stack; the plain mean of calibrated H breaks with bursting or very noisy members (5x RR-H at Kalkaroo 1-10 s, in the halves too) and the band stack, the medians, k1 and the subspace repair it while coherence weighting does not and k2 (full inverse-covariance, a minimum-power stack) cancels field where the signal is strong; a stack reference pays only where q of the record's reference is above about 1.5 (Vulcan 1-10 s 0.51-0.75 of RR1's jackknife error, 0.45-0.97 realistic; Nador 3-10 s 0.08-0.76 of X), nothing where it is near 1; the stack base wins where a single base is noisy but shifts psi 1.2-3.6 deg (its datum); shared near-field noise biases every H reference whatever N (benchmark) and no real-data test for it works yet (the validity null is miscalibrated, 9.25 % exceedance). Skeptic: the arithmetic holds; the benchmark's one positive verdict and the "22x" Nador number fall; the real-data rankings rest on jackknife errors; D1's agreement is near a consistency check; the Vulcan-only findings cannot be rerun (the 2024-25 workspace is gone; D2's 113 GB rebuild was removed at 10:05 when D: fell to 296 GB, under the floor). Decisions open (DECISIONS.md): keep the band stack and add the spatial median; a q ceiling reading in front of every build; member validity screens for reference stacks (the first-order item); the time-domain Z stack's future (fix the builder or a band-stack Z path); keep the base role with its datum recorded; an exclude-near knob; not to build k2, the multi-channel reference, the subspace, trimmed means or optimal transport. Nothing declared in any survey; nothing changed under src/ or scripts/.

## 9 Oct 2026

**The Process tab's station list from archives: workbench issues 31 and 32** (06:07, 9 Oct). The author could not pick a station on the Atlas survey. Cause: the station combo was filled from `State.raw_sites()` alone, and the Atlas raw folders moved to E: on 7 Oct with survey.yaml's data_root left on D:, so it held 0 of 146 sites (the remote combo 103 archives, all labelled "stack"); not the stack work (the list has come from raw_sites since before the rename). Behind it `ingest_site` looked up the raw folder before keeping an archive, so process_rr.py on A01 rr A06 stopped with KeyError 'A01'. Fix, a fixer in a worktree at ff4f100, criteria first (05:54): `State.station_choices` (raw folders, declared recorded sites with an archive, declared derived and burst sites with an archive; observatories left out; "A01  (archive)" when no raw folder), `State.recorded_sites` for the remote recommendation, the Cross-powers recommendation and the replace donors, `archive_kind` saying "archive" and "bursts of" where it said "stack", and `ingest_site` keeping an archive whose raw folder is not found. Tests: tests/process_station_list_unit.py (scratch survey with and without data_root; the raw_sites-only list trips it; Atlas 99 stations); G1 on the Atlas survey 99 of 99 (main: 0); G2 Kalkaroo and curnamona_cube lose no station (Kalkaroo gains the burst site KD-RR_210428H); G3 A01 rr A06, 2023-07-12 00:00-06:00, from archives through a survey copy, exits 0 with EDI (DATAID=A01, 52 periods), XML and h5 (main: KeyError). Found (32): a remote with an archive and no raw folder was taken as virtual by process_rr.py and its declared filters were not applied (nor recorded, for either site). Revision, an agent in a worktree, criteria first (06:48): fixed in the same change, `process_rr.recorded_site_folders` (every declared site that is not derived, burst or observatory, at data_root/<site> when its folder is not found; process_intersite.py uses it too), so A06 rr A01 under the stale root reads A01_f81e4c0e6.h5 and records A01's mains and notch, every decision equal to the run with data_root on E:; stack, observatory and derived remotes resolve as before; the 6 h A06 rr A01 run exits 0 (its Z moves from the old resolution's by a median 0.9 % in zxy) and A01 rr A06 equals G3 exactly; the dry run prints `local_reads`, `remote_reads` and `filters_recorded`. Declared derived and burst sites with an archive are now stations on raw surveys too (README). Record: qc/reports/gui_station_list_20261009/ and its revision/. The author's survey.yaml data_root is still stale. Verifier (9 Oct 07:4x, yes with changes): the resolve mapping confined to declared recorded sites, stale and E: roots equal in every decision, stack, observatory and derived remotes unchanged, all four of its own mutants trip; records only: the 164 % figure given its denominator and period, the stale _print_archive_status docstring, and workbench 33 opened for a burst site as the remote (virtual, its recorded site's filters neither applied nor recorded). Installed and committed by the orchestrator; no Atlas product or archive was written between the move on 7 Oct and the fix.

## 8 Oct 2026

**Hyphenated station names in the TF products: upstream issue 86 fixed in mt-workbench** (08:11, 8 Oct). A fixer in a worktree at e56af1c (the diff rebased onto 3f31b5c), criteria first (07:58). Cause: mt_metadata 1.0.10 admits a hyphen in a Station id (^[a-zA-Z0-9_-]*$) and not in a Run id (^[a-zA-Z0-9_]*$), and builds a placeholder run "<station>a" in `EDI.station_metadata` (edi.py line 1070; writer and reader) and in the EMTF XML reader when its FieldNotes give no run (emtfxml.py line 1138), so process_rr.py on KD-Q5 exited 1 at the EDI writer after aurora (P1 rows d03, d04) and a KD-Q5 XML did not read back; the EDI header reader also maps DATAID KD-Q5 to KD_Q5 (`validate_station_name`), so a merge from a KD- EDI would have carried DATAID=KD_Q5. The hyphen is the only character a station id can hold that a run id refuses. Fix: `products.hyphenated_station_ids`, a context in which `Run` of those two modules maps the run id's refused characters to "_" ("KD_Q5a") and the EDI reader keeps DATAID's hyphens, restored on exit; `write_edi`, `write_xml` and the new `products.read_tf` use it, as do merge_modes.py `read_tf`, merge_best.py's EDI write and `compare.rho_phi`; the station id, DATAID and the XML Site Id stay as declared. Test: tests/hyphen_station_export_unit.py (KD-Q5, KD-RR_210507, A01; mt_metadata's own code raising or renaming as the control; the context a no-op trips). Real data: the d03 command (KD-Q5 on KD-RR_210507, 2021-05-07 06:50:02 to 22:26:32, --no-masks, tag hyphen-fix-Z) through a survey copy exits 0 with EDI, XML and h5, DATAID=KD-Q5 and Site Id KD-Q5, and its Z, variances, XML Z and h5 Z equal the P1 wrapper product's exactly at 48 periods; on e56af1c it exits 1 at the EDI writer; merge_modes.py and merge_best.py on those EDIs write DATAID=KD-Q5 (KD_Q5 on e56af1c). xml_comment_keys, ingest_flip_h, edi_index, merge_tensor_bands, unknown_declination, compare, compare_imports, merge_best, merge_modes, quality, short_window pass; process_rr_cli_unit 14 of 18 as on e56af1c (the four on the deleted Curnamona archives). Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\hyphen_station_fix_20261008\. Sceptic (8 Oct 08:2x, yes with changes): the fix stands and the code needs no change; the read-side scope (merges delivered DATAID=KD_Q5 before) is justified; records only: entry 86's field name, the number collision with held diff B (B becomes 87), two line wraps, a docstring clause on INFO-runlist run ids. Installed and committed by the orchestrator.

**Burst-ingest metadata cost: upstream issue 85 fixed in mt-workbench** (07:47, 8 Oct). A fixer in a worktree at e56af1c, criteria first (07:15). Cause: mth5's `StationGroup.metadata` getter adds every run of the station to it again on each read, and mt_metadata's `Station.add_run` recomputes the period over all runs on each add; `_ingest_bursts` read the getter five times with the runs present (the provenance check and update, the period's start and end, `write_metadata`): on a 400-run synthetic ingest 83.7 of 112.1 s profiled, update_all 2,002 calls. Change: the station's metadata read once before its first run, each run added with `update=False`, the provenance lines, one `update_all()` and the period set on that object, written once by `ingest._write_group_metadata` (mth5's attribute loop on the object held, no getter); the run comment's `recording_id` (a glob of the recording's files, 20 ms at KD-RR) taken once per recording; comments, chains, the +1 s correction and the continuous path unchanged. Test: ingest_phoenix_unit U19 (G5H of 12 and 24 bursts: 4 getter calls, none with a run present, update_all 3 for both; e56af1c fails it with 5 calls with the runs present and update_all 62 and 122; a station read per run and the write through mth5's write_metadata are the mutations that trip); ingest_phoenix_unit, intersite_bursts_unit, phoenix_archive_unit, ingest_site_cli_unit and timeseries_build_unit exit 0. Synthetic G5H (hx hy): 100/200/400/800/1600 runs in 2.7/5.1/10.2/19.9/37.6 s (e56af1c 11.9/24.8/58.0/143.7/389.4 s; t(800)/t(400) 1.95 against 2.47, t(1600)/t(800) 1.89 against 2.71), the unfixed and fixed 800-run archives equal in every attribute and sample. Real: KD-RR_210428H (7048 runs) through scripts/ingest_site.py into D:\MT_DATA\MT_Kalkaroo_Workspace\mth5\scratch_bursts_fix in 196 s against 93 min at 4beb3cd; against that archive 7048 runs of the same names, starts and channels, every sample of every run bit-identical, every station attribute equal; the differences are those of 336275d and e56af1c only (the phoenix_h_polarity stage in 14,096 channel filter lists and comments, the dated calibration comments, the dot-free dc rail key in 7,048 run comments). Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\burst_ingest_cost_fix_20261008\. Sceptic (8 Oct 07:59, yes with changes): the fix stands, scoped to _ingest_bursts, the archive unchanged; record corrections only (the dc-rail key difference stated as a deviation from criterion B3's letter, explained by upstream 82; the all-samples equality over all 7048 runs established by the sceptic's own pass, the fixer's covering 7047 plus the shifted control; both coil files named). Installed and committed by the orchestrator.

**Phoenix H polarity: upstream issues 81 and 82, workbench 30** (05:43, 8 Oct). The S3/S4 QC found calibrated Phoenix H opposite to LEMI-423 H at five pairs; without a stage the 11 S1 sites equal AusMT within 0.7 deg and 0.01 dex once 180 deg is added, and on mt-workbench's single-site check 7 of 8 S3 and 5 of 5 S2 Phoenix sites sit in the opposite quadrants where AusMT's are standard at 9 of 9 and 5 of 5 (KD-J2 fits neither). The locate step showed the stored Phoenix volts and LEMI-423 counts in phase (12 of 12 hours); with the 586 rxcal and scal tables within 8.6 deg at 1 Hz and entry 68's LEMI-423 H of the observatories' sign, mt-io's Phoenix H is geographic and the -1 is mt-workbench's own convention (lemimt's, the LEMI-423 chain's -1000), into which the Phoenix H had not been put. A fixer in a worktree at 4beb3cd added `phoenix._h_polarity_stage`: `phoenix_h_polarity`, a CoefficientFilter of gain -1, mV to mV, after the coil stage on every Phoenix hx hy hz (continuous and bursts, through `_channel_chain`), the comment piece "phoenix_h_polarity -1", E untouched, the samples as recorded. Test: ingest_phoenix_unit U18 (the stage once on H and G5H and never on E, 1 Hz phase 180 deg on H and 0 on E, stored hx anticorrelated with calibrated hx, flip_h and swap_h composed; fails on 4beb3cd; gain +1 and no stage trip), U1-U17 unchanged, phoenix_archive_unit, ingest_site_cli_unit and eight other Phoenix suites pass. Real data in D:\MT_DATA\MT_Kalkaroo_Workspace\mth5\scratch_sign_fix (calibration files of before 04:31 copied there: the workspace sensors folder now holds two files for 9 receivers and 19 coils, which ingest refuses): KD-RR_210428 against KD-RRa_210428 polarity +1 in 24 of 24 hours (before -1 in 24), delay +32.66/+32.71 ms and amplitude ratio 0.977/0.976 equal to the QC's; G5 on RR_201105 with the S1 first-product command: xy +16.6 and yx -132.3 deg (medians 0.1-10 s, before -163.4 and +47.7), rho unchanged and phases exactly 180 deg from the S1 product, and AusMT interpolated onto its periods within 0.07 deg and 0.007 dex. process_rr.py then exited 1 at the XML: the "dc rail (V, 0.9 x ...)" run-comment key of 4beb3cd (upstream 82). The sceptic (8 Oct 05:23, yes with changes) asked for the framing above (81 a statement of mt-workbench's convention, not an mt-io defect; the ask to Phoenix whether EMPower inverts H or E and whether H3 follows H1 and H2), the measured counts, the coil-missing chain in U18, a warning for archives built before the stage, the 82 fix and the proof. The revision: U18 also ingests G5 with no coil table ([phoenix_h_polarity, phoenix_mv_to_v, curve] accepted by ChannelResponse; an nT-to-nT stage first is refused); `phoenix.archive_h_polarity` and `warn_without_h_polarity` (one warning per site where process_rr.py, process_intersite.py and `intersite.stack_channels` open an archive without the stage; no change of behaviour; tests/phoenix_h_polarity_check_unit.py, the workspace KD-RR_210428.h5 and PT_10133H.h5 warned, the scratch G5.h5 not); upstream 82 fixed at both ends, the dot-free key "dc rail (V, 90 % of the input range)" with the dotted one still read back (dc_level_unit) and `products.dot_free_comment_keys` in `xml_copy` (tests/xml_comment_keys_unit.py, mt_metadata's own writer raising as the control), so the archives built at 4beb3cd (E10, J12, KD-G5, KD-RR_210428H, the scratch ones) export without a re-ingest; the S1 first-product command on the scratch archives exits 0 with the XML and the EDI equal to the fixer's (xy +16.63, yx -132.30 deg, log10 rho 1.8192 and 1.2644), the unrevised code exits 1 at the XML. Diff B of the ingest gaps fix (held) takes upstream 83 when it lands (ingest_gaps_fix_20261007/RENUMBER_NOTE.md). Every Phoenix archive and Phoenix Z or M in tf\ predates the stage and needs a re-ingest. Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\phoenix_h_sign_fix_20261008\fix\ and revision\.

**Phoenix binary calibrations, the calibration-date rule, the Kalkaroo sensors folder: upstream issues 83-85** (05:27, 8 Oct). A fixer in a worktree at 4beb3cd, criteria written first (04:18). The 2021 calibrations (`E:/MT_Timeseries_DATA/MT_Jupiter_2021/_calibration_1.zip`, 58 `.scal`, 21 `.rxcal`, read in place) are binary, and nothing in the environment reads them (83). The layout was derived from the 24 coils and 12 receivers in both forms: a `.scal` holds its whole JSON (68 records of frequency and complex response; 24/24 pairs, 1,632 values, 0 units of the 8th digit); an `.rxcal` holds four bands of measured records per channel, whose JSON values are |z| and arg z less a 1.4666667 ms delay (12/12, 3,276 records within 1.0e-7 and 1.0e-5 deg, float32 arithmetic), but not the JSON's curve below each band's lowest record, a model EMpower fits and does not write, which for lp 10000 is the whole curve below 1024 Hz. New scripts/phoenix_cal_convert.py writes the JSON form, takes that curve from an EMpower JSON of the same receiver (`curve_below_records_from`), never replaces a file and compares one that exists; through mt-io the converted filters equal EMpower's (coils 1.2e-16, receivers 1.8e-7); the one-byte shift and negated phases are the controls. `phoenix.calibration_for`: of several files the latest dated at or before the recording's start (`PhoenixRecording.start_s`), else the earliest after; the comment names the file and its date; 4beb3cd refused several files (84). Test: phoenix_files_unit (ten date cases; the reversed rule trips four; exit 1 on 4beb3cd). The Kalkaroo sensors folder gained 43 files (36 existing compared equal and kept, byte-equal to the repo's copies). Under the rule S1, S2 and S3's receivers keep their Nov 2020 files; 31 S3 sites gain coil tables (the 30 "coil table missing" archives and KD-G5); the four S5 sites move to the 26 May 2021 files. Coil tables change by at most 0.8 % and 0.7 deg between dates above 1 Hz and up to 5.2 % and 2.45 deg below 1 Hz (5.3 % over the full range to 5000 s, 54650 at 2.8e-4 Hz). Re-ingest plan (not run): install first (4beb3cd now refuses nine receivers' sites), then the 31 archives with --force. Suite: 77 of 81 exit 0; campaign_unit 17/17 with campaign_lineC.yaml copied in; declination_unit CRLF in the worktree, process_rr_cli_unit the deleted Curnamona archives, gui_smoke 63 against 61 rows, as on 7 Oct. The sceptic (8 Oct 06:25, yes with changes) decoded the 79 files on its own and agreed; three changes followed: the rxcal piece of a converted file names the file its curve below the records came from ("rxcal 10307_60ADCE5D.rxcal.json (records calibrated 2021-05-26; curve below 1024 Hz from 10307_5FA205AE.rxcal.json) 10000 Hz curve": below 75 Hz its response is that file's), a file dated after the recording's start is taken with one warning (KD-H2 and KD-E4 take 54647/54648_608F788F, 4.1 and 2.0 days after their starts), and the converter compares coils within 2 units of the 8th digit (the receiver tolerance it used let a coil pass at up to about 24); the drift corrections (2.45 deg for 54687 at the 0.42 Hz table point, the coil-against-another-coil control) are in the record. Re-based onto 336275d (8 Oct, from 06:39), which took 81 and 82 for the H polarity: the H chain is the coil table, phoenix_h_polarity, phoenix_mv_to_v, the receiver curve, and KD-J3 read in place builds it with the 28 Apr 2021 coil tables and the polarity stage together (336275d refuses KD-J3, KD-H2 and K9_repeat with the converted files in the sensors folder). (85, not fixed) A burst site's ingest rebuilds the station metadata over every run at each read, quadratic in the run count: KD-RR_210428H (7048 runs) took 93 min, about 85 in the rebuilds. Tests: phoenix_files_unit (the date cases, the after-start warning and the converted rxcal comment, each with a mutation that trips), ingest_phoenix_unit U1-U18 and eight more files exit 0. Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\phoenix_calibrations_20261008\ (the re-base in revision\).

**Kalkaroo ingest gaps and the Phoenix input rail: upstream issues 76-80** (03:37, 8 Oct). A fixer in a worktree at 8a72107, each change first a failing test on 8a72107 (logs/before.log: phoenix_files_unit, dc_level_unit and ingest_phoenix_unit exit 1). (76) `phoenix.recording_files` skips a file of no more than its 128-byte header with a warning naming it (J12's four 0-byte sequence-0x108 files; KD-G5's 0-byte 0x9D in folders 0 and 4, which folders 1 and 2 never held, found by the sceptic: one run now). (77) `phoenix.plan_runs` aligns the channel folders first (`_aligned_files`): a sequence one folder lacks, holds empty or holds with another sample count is left out of every channel, becomes a run boundary, and is logged and written into the next run's comment ("phoenix_gap: sequence 13 (not in folder 3) left out of every channel, 360 s from the end of sequence 12 to the start of sequence 14"); nothing is interpolated. E10's missing hx file is sequence 0x0D, not the 0x0E the old message named. (78) A Phoenix run's dc level counts samples at 0.9 x the channel's input range from its header (`phoenix.input_range_v`: 2.25 V E, 1.125 V H), recorded after the levels ("dc rail (V, 0.9 x the input range): ...") and named in the flag line; LEMI and EDL keep the relative rail. scripts/dc_level_check.py reads that rail back from the run comment (`comment_rails`) and keeps the record's own for a run without it: the sceptic's rebuilt C10 went from ex 9.49 % and ey 11.62 % "saturated?" to 0.00 % ok, as its comment records. The input range was taken over the saturated-frame counts because the headers hold 2,185 of the 5,641 storm frames of the stats files and mt-io decodes them wrongly (79, an mt-io entry). (80, not fixed) `instruments.record_files` still stops on a 0-byte Phoenix file (J12, KD-G5: new_survey.py, the window bar's raw span). Tests: phoenix_files_unit (gap cases on synthetic headers), ingest_phoenix_unit U15-U17 (G5 cuts: a trailing 0-byte file, a missing and an empty hx file; channels equal to their folders' files and aligned to the ns; the rails in the run comment) and U16 (the 25 test-folder recordings plan as the 8a72107 fixture tests/fixtures/phoenix_plans/ptest_plans.json), dc_level_unit (a drifting E flagged at its own rail and not at 2.25 V, a railed E flagged at both; dc_level_check.py on a run whose comment carries the rail and a control run without it); a mutation per check trips. Real data through scripts/ingest_site.py into D:\MT_DATA\MT_Kalkaroo_Workspace\mth5\scratch_gaps_fix: J12 one run of 263 files (14,201,850 samples a channel), E10 two runs (files 1-12 and 14-479, 647,850 and 25,119,000 samples, run 2 360 s and one sample after run 1 in every channel, the gap line), every channel equal to its folder's files, every dc level ok; the 141 other recordings under raw_sites plan exactly as on 8a72107; C10, E6 and K5 re-measured: 6 recorded flags, 0 at the input rail, the shares equal to the S1 QC's rail table. Suite on the change set before the split: 78 of 81 exit 0 (campaign_unit with campaign_lineC.yaml copied in); declination_unit CRLF in the worktree, process_rr_cli_unit the deleted Curnamona archives, gui_smoke 63 against 61 rows, as on 7 Oct. The sceptic (8 Oct 03:27, yes with changes) held the band floor of a recorded site slower than the survey out of this change: it moves the 1 Hz observatories EBR and SPT of Atlas and Nador from 4.0 to 4.06375 s as a local, so it is a separate diff for a decision (ingest_gaps_fix_B_bands_held.diff). Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\ingest_gaps_fix_20261007\ (the split: ingest_gaps_fix_A_install.diff, split/).

## 7 Oct 2026

**Kalkaroo survey code: the burst clock, one min_period at every rate, Build MTH5 for burst sites** (23:57, 7 Oct). Three changes the declared Kalkaroo survey (236 sites, 150 Hz Phoenix, 1000 Hz LEMI-423, 24 kHz bursts) needed, a fixer in a worktree at a035bc7, each first a failing test on a035bc7 (logs/*_before.log). (1) survey.py: a burst site's `clock_offset_s` is 0.0 unless its own entry declares one (`BURST_SITE_KEYS` gains it; `Survey._burst_site`): the bursts carry GPS time, while -0.1148 s on every Phoenix 150 Hz site corrects the continuous stream's decimation-filter delay, and copied it moved the bursts 0.1148 s early. Tests: survey_unit (G5H under G5 at -0.1148 resolves 0.0, its own 0.05 kept, 61 refused; copying the recorded site's is the mutation), ingest_phoenix_unit U14 on the real G5 cut (24 bursts at stamp - 18 + 1 s to the ns with no clock line, 0.05 applied with it, G5 itself still at -0.1148 s; a035bc7: the bursts -0.114800 s off). (2) bands.py: a `min_period` below 4 / rate re-anchored the whole layout at the quarter rate (no band dropped, no EMPTY row, no error; 150 Hz at 0.004233 s gave 37.5 Hz, 1000 Hz sites 250 Hz via site_min_period's 4 / rate: both off the bursts' lattice 6000 / 4**(k/6) Hz). Now `top_edge` drops the bands above the quarter rate whole (an edge on it to 1e-9 is the quarter rate, so 100 Hz at 0.005 s stays 25.0 Hz bit for bit: aurora_fork_unit caught that) and site_min_period gives a faster site the shortest period of the survey's layout at or above 4 / rate (1000 Hz 4**(14/6)/6000 = 0.004233 s, 24 kHz 1/6000 s); process_rr and process_intersite pass the block's periods_per_decade. Unchanged byte for byte: every 1000 Hz survey at 0.005 s, Kalkaroo's 150 Hz at the declared value, 1 Hz derived, 24 kHz; stuart_shelf_2009 (10 Hz at 0.005 s) moves 0.787 % (min_period 0.4 keeps it). Tests: bands_unit (every edge on the lattice at 150, 1000 and 24000 Hz, aurora's assign_bands, process_rr's resolve on a 150 Hz and a 1000 Hz pair; the old cap is the mutation). Recommended block: min_period 4**(14/6)/6000, max_period 4**(75/6)/6000 = 5592.4 s (the last level on the lattice at every rate). (3) gui/tabs/timeseries.py `_update_build` tests `survey.raw_site(site)` (issue 72 amended); new tests/timeseries_build_unit.py. Suite: 76 of 81 exit 0; campaign_unit (17/17) and stack_recipe_cli_unit (0 failures) pass with campaign_lineC.yaml copied in; declination_unit CRLF in the worktree; process_rr_cli_unit the deleted Curnamona archives; gui_smoke stops at (1) with "63 rows, expected 61" on a035bc7 as well (curnamona_cube's E: data_root now holds C_cube_Phoenix and J08). Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\survey_code_20261007\.

**Kalkaroo ingest defects fixed: upstream issues 72-74** (21:59, 7 Oct). The three defects the P-test ingest met on 5 Oct, fixed with the lead as the architect and a fixer in a worktree at ca0dc53. Each was first a failing test on ca0dc53 (before.log), then fixed: (72) scripts/ingest_site.py tests `survey.raw_site(site) in raw_sites` in main, plan_site and --all, so a burst site is ingested from its recorded site's folder (the "ingesting" line names it and ends "; the bursts of <site> (bursts_of)"), the refusal names Phoenix, and a Phoenix site's dc level lines are in V; (73) `ingest._ingest_bursts` drops mt-io's trailing burst when it is the cut one the sub-header walk leaves out (`phoenix.cut_burst_samples`), and removes the archive it was writing on any failure (`_remove_partial_archive`); (74) `phoenix.archive_stamp_correction` reads the station's `provenance.comments` with h5py, same values and MTH5Error as before. Tests: ingest_site_cli_unit (i)-(l) on a cut of the real G5, 12 of 12; ingest_phoenix_unit U13 (a .td_24k file cut 24000 samples into its last burst: 23 runs equal to the walk; a failure forced after five runs leaves no file; two mutations trip); new tests/phoenix_archive_unit.py (six fixtures and PT_10133.h5 equal to the mth5 read, 400 runs in about 1 ms against 3.7 s). Suite: 76 of 79 *_unit.py pass in the worktree; campaign_unit passes (17/17) with the gitignored campaign_lineC.yaml copied in, declination_unit passes from the live tree (the worktree checkout is CRLF), process_rr_cli_unit needs the curnamona_cube archives deleted on 3 Oct (as on 6 Oct). Real data, through the script into the scratch workspace D:\MT_DATA\MT_Kalkaroo_Workspace\mth5\scratch_defects_fix: PT_10133H 1629 runs in 553 s (ca0dc53 refused it in 4 s); PT_10306H 1625 runs in 565 s, its first 1620 equal to the P-test's workaround archive and the other 5 the last file's whole bursts, the cut burst in no run; a failure forced after 50 runs left nothing; the stamp read of PT_10133H 0.002 s against 106 s on ca0dc53, all 12 burst archives 1.0. Record: 2026_Natural_Source_IP\datasets\kalkaroo\results\ingest_defects_fix_20261007\. Left: the GUI's Build MTH5 button still enables only a site with its own folder (gui/tabs/timeseries.py `_update_build`).

## 6 Oct 2026

**The Stacks tab finished** (15:26, 6 Oct). Request: finish the stack feature with agents and the lead session as the architect. A baseline workflow of six agents ran the merged suites in main (every Stacks suite passes under bbmt-2026; the base anaconda python has no pyqtgraph and gives false failures) and read the open items with evidence: the picker gap's premise was wrong (the runs cache already holds what member_changes reads), the chart's wait on masks.yaml was finding 3's measured trade, two fix-round findings had no test, the preview and weights plot had no figure, and the build's README and gui README requests were unapplied. The build workflow's five worktrees started at origin/main, 120 commits behind main; the messages sent to fix that resumed a copy of each builder in the same worktree, and the workflow was stopped and the rest done by hand from the builders' partial work. Five commits: 26b3a7a (the picker refuses a membership change inside the window through intersite.member_changes(runs_of=); stacks_tab_unit adds STK_EQ/STK_EQA/STK_EBW and the run_now guard, 67 checks), bba2ba4 (the chart's default window searched inside the local's record with "records nothing in the window" on the status line, reload() clearing the last survey's state, tests/availability_chart_unit.py pinning the masks wait, the 14 px rows and the window cases, 23 checks, four mutations trip), ebe47d4 (a time_coherence recipe under 1800 s refused at Save and by build_stack.py --recipe; the leftover .build_ folder listing tested; stacks_unit 176, stack_recipe_cli_unit 83 with campaign_unit 17/17 in main, which answers workbench 29), 6d5b891 (the weights plot readable: plain axis, two-row translucent legend, 160 px; tests/stacks_tab_shots.py writes docs/figures/gui_stacks_preview.png, gui_stacks_weights.png and the Nador pair from a read-only open, 847 files unchanged), a29db47 (README rows and eight test lines, workbench 22/23/24/27/29, upstream 71; the gui README's one rule, layout, "Adding a tab" and a Stacks entry). The weights plot's SI-prefix axis, cut label and legend over the curves were a defect of the built layout found by the screenshot reader. Design 13.1's "at most 40 rows" is now the 14 px rule and 13.4 lists the new refusal. Main-tree runs after the commits: stack_check_unit 76, availability_model_unit 62, intersite_unit 54, stack_median_unit --quick 50, ruff clean; process_tab_unit still hangs at close (workbench 21). To decide: the Queue intersite button (design 17.1); the chart's default view, member-list order and other-rate rows; whether the design and build docs and docs/figures travel (git add -f); P5S8 dead on both coils yet a rule member of the Nador H recipe (workbench 28); the Nador bar plot's overlapping tick labels. Lesson recorded: never message a running workflow agent (a copy is resumed), and a worktree agent's brief starts with a fast-forward to main.

## 4 Oct 2026

**The Stacks tab** (18:26, 5 Oct). The request at 12:4x: a tab for building stacks (which sites, which field, which weighting or method, how to see it, where to save it, what is available in a window). Proposal in docs/gui_stack_tab_design.md sections 1-7 (accepted: "stack gui accepted, lets build it"), the build spec in sections 8-17 after a critique and revision, the build log in docs/gui_stack_tab_build.md (both under the gitignored docs/*). Built in worktree stack-tab by one workflow of 18 agents (readers, spec, critique, revision, four foundation builders, two integrators, three reviewers, a fixer, a final check), commit 01ca477, merged 7ef3d16 once the Nador stack batch had finished (the live-tree rule). A stack is now a declared recipe (src/mt_workbench/stacks.py; <survey>/stacks.yaml written only at a click, byte-stable block writes, a recipe hash) that both engines take (process_intersite.py --stack NAME, build_stack.py --recipe NAME; every product records the recipe's name, hash and canonical text). The Stacks tab (gui/tabs/stacks.py, index 7 before Process) holds the recipe form (gui/stack_form.py), the availability chart of runs per site and role with references, nights, masks, the window region and members per hour (gui/availability.py, availability_model.py), the member check and preview on the loaded window only (mt_workbench.stackcheck, gui/stack_check.py), and Save recipe, Build archive and Use in Process; the Process tab's StackBuilder is a recipe picker. intersite.stack_band and band_stack take method mean or median (the mean path unchanged; the complex marginal median, two members give the mean); virtual.stack_arrays is public. The time-domain median was cut by the critique on a synthetic check (its error power 0.87 of a member's against 0.19 for the mean under slow drifts). Logged: workbench issues 21-29, upstream 75 (mt_metadata splits a Comment on "|"). Tests from main after the merge: stacks_unit 168, availability_model_unit 52, stack_check_unit 76, stacks_tab_unit 59 and stack_median_unit --quick pass; the agents' full runs added stack_recipe_cli_unit 80 (campaign_unit NOT RUN in the worktree, its plan is gitignored, workbench 29) and the existing intersite, virtual, bursts and merge suites. gui_smoke lists the ten tabs with Stacks at 7, then stops at the pre-existing 63-against-61 site count (workbench 21; its archives were deleted on 3 Oct, chip raised); process_rr_cli_unit needs the same archives. Leftovers: other-rate sites clutter the Nador chart rows; the preview and weights plot have no screenshot; the chart waits while masks.yaml parses (3 s at Atlas). Screenshots docs/figures/gui_stacks_nador.png, gui_stacks_vulcan.png.

**Nador magnetic tensor stage** (09:40, 5 Oct). A pre-registered base test on eight sites chose the remote RR of each deployment over the cleaned H stack (the stack was more precise at five sites but lost at the three nearest the remote and had polarity flags from five members), then every usable site got full-band magnetic tensors against RR with a profile neighbour as reference and, at 100-1000 s, against the remote's 1 Hz copy with the SPT observatory as reference: 267 runs, none failed, 61 sites mapped. The screen found five more coil defects (two reversed hy, one swapped pair, one pair rotated 90 deg, one weak logger). The maps show H amplified by 40-60 % relative to the remote in two zones, inland west-centre and east, from 3 to 1000 s, and the coast in the sign of M_xy only.

**The 1-10 s band (item 5)** (04:57, 5 Oct). Three sub-studies with a skeptic: the apparent 7.24 s jump of the chained identity is not a step but a level in one link's impedance-phase term, and the parked coil table cancels exactly in every two-site quantity, so the telluric products are clean of it; 3-10 s ties through the 2022 stack with the present products while 1-3 s does not tie across days and the 2024-25 tie breaks at RR2's own product; the 1-2 s residual of the western block is carried by the FEMTIC model's misfit, not by the data, the near-surface or the processing, so 1-3.6 s is model-limited in Stage 0 and 4.6-9.1 s can be judged now. Proposals by cost, from band-rule declarations to an inversion constrained at 1-3 s.

**Five post-P2 analyses** (03:51, 5 Oct). After FEMTIC's P2 on v4, the chosen analyses ran in parallel with hashed criteria and a skeptic each: Stage 0 on the spectral shape finds no site whose residual survives as IP, only a long-period east-west residual the model lacks; the decomposition of psi into the magnetic term and the impedance phase difference holds on the data to 0.12 deg and shows the model fitting psi and the magnetic term at 10-30 s but not the impedance phases, with the north-east misfit in the sites' own Z phases; the injected-IP test recovers a Cole-Cole phase to 0.35 % and puts the detection threshold at a chargeability of 0.002-0.008 at the jackknife errors but 0.07-0.09 against the 0.4 deg repeat floor, so the datum sets the limit; the phase tensor of T showed Caldwell's invariants are not immune to base distortion (only psi and an eigenphase split are); and the SimPEG kernel gives M 5-17 % of T's IP phase for a 16 km block, so M stays inductive. Item 5 (the 1-10 s band) starts with the 7.24 s jump of the chained identity.

**Residual-tensor diagnostic** (03:21, 5 Oct). The author pasted a residual impedance-tensor screening method (NRT, phase-tensor residual, distortion index, spectral and spatial coherence, a ranking index and seven classes) and said it might be worth testing. It was built as a reusable tool with tests in the IP home and applied to the twelve Geotools runs, with the open choices in a config and a hashed criteria file. Vulcan4 shows no candidate IP-like response, only a run-wide phase misfit beyond 30 s; Kalkaroo's line B recurs as a candidate but with an amplitude misfit too. The ranking index does not agree with the telluric psi map. A numerical skeptic confirmed the arithmetic; a mutation skeptic showed the distortion class is a fixed quota of the model's own C matrices and the spatial gate barely acts, so the classes need new rules before the IP class means anything. The skeptic also found the Vulcan EDI frames about 6.5 deg off the declination.

**Nador logger-9 dive** (00:43, 5 Oct). The author asked for a detailed noise dive on two logger-9 sites before any exclusion. P3S8 and P4S8: the horizontal magnetics do not sense the field (coherence with the remote 0.001-0.03 against 0.4-0.99 for working coils, hy flat, hx an inverted copy at a sixth of the true size, DC levels fixed), the clock is good, nothing is shorted; the cause sits in the coils' supply chain from the hour logger 9 first met coils 117/118, and the field sheet's coil entry at P4S8 is contradicted by the instrument timing. P4S8's electrics work and can carry a borrowed H from P4S6; P3S8's cannot be shown to. The skeptic confirmed the H verdicts at both sites and refuted P3S8's ey pass. Proposals: exclude the logger-9 magnetics, keep P4S8 as E-only, test P6S13's E.

**Geotools runs inventoried** (23:25). By decision the Geotools (CGG RLM3DMT) 3-D inversion runs of Vulcan (6), Kalkaroo (6) and Jupiter (6) were copied into the IP home with md5 manifests, and the Vulcan and Kalkaroo runs were inventoried by a workflow of 18 agents: grids, periods, sites, iterations, RMS, EDI sets, C matrices, tears; a shared reader and figures of every final model with the orientation proven from the model array itself; two skeptics confirmed every key number. Vulcan4 (the "ADI run 4" of Stage 0) is a 98-site, 17-period, 40-iteration run at nRMS 0.96 whose model is byte-identical to the Stage 0 copy; the Vulcan1-4 EDIs are the Tear1 EDIs rotated 7 deg; the Kalkaroo tipper blocks are placeholders. The "M3" is not among them.

**Nador raw archives complete; the B423 listing rule** (22:20). The 76 raw archives of the Nador survey landed in 43 min (237 GB, every size within 0.5 % of the Vulcan four-channel rate). One site, P2S1, was refused because the B423 listing searched subfolders and swept in a stray card (the Atlas remote's R05 deployment at 1 Hz, left on logger 34): the listing now takes the site folder's own records and searches subfolders only when there are none, naming any stray it leaves out (1f4be8d, ingest_unit 20 tests). Seven upstream issues met today went into docs/upstream_issues.md on request (53dff93). FEMTIC's v4 half-space passes the psi gate everywhere (0.050 and 0.009 deg at 11.5 and 92 s).

**FEMTIC v4 built and production launched** (21:54; IP home modelling/femtic). The author's D1 ruling applied: the v4 mesh refines the stations at their logger positions (the v1-v3 table was mirrored north-south: Spearman of latitude against table north -0.9996 on v3, +0.9956 on v4). v3's P0 half-space measured the floor the mirror costs: max |psi| 0.40 deg at 11.5 s with 30 of 100 sites above the 0.10 deg gate. v4: 3.07 M elements, every grid station within 1.04 m of a refined zone centre, the Geotools model transferred with R1-R4 passing (R4 max 0.039), and P0, P1, P2 launched at 21:46 for about two hours. Figures of the mirror, the mesh in plan and section, the model on the sections and the psi floor went to the author, who confirmed that the model is a Geotools 3-D inversion and asked for the Geotools runs (Vulcan and Kalkaroo) copied into the IP home for reference.

**Nador raw ingest launched; D1 ruled; personal surveys ignored** (21:38). Decided: "we can start nador as well. though making sure we keep system memory for the modelling": the 76 LEMI-423 sites of the Nador survey ingest two at a time behind a 50 GB free-memory gate (runner, hashed criteria and README in the Nador home, runs/ingest_20261004), four channels everywhere so the washed-out E can be re-screened after the filters; RR1 and P1S1 first as a trial judged on size, runs and channels. On FEMTIC D1: "lets go with the logger positions for D1": the v4 mesh is built on the logger positions and production runs on it; v3 keeps only its P0 (the psi floor at the true positions, 8 min, 33.7 GB). Figures were asked for of the mesh and the FEMTIC work. Decided: the Vulcan 2022, Vulcan 2024-25, Nador and Kalkaroo survey folders are personal projects for now and are ignored by git (3786cf6).

**FEMTIC Stage 0 pipeline** (21:16; IP home modelling/femtic: recon/, DESIGN.md, scripts, runs, README; seven agents, two review
rounds, two small items fixed by hand after). Built: the ADI run 4 model resampled onto the author's tetra mesh (one FEMTIC cell per
ADI cell an element falls in, columns hung from ADI's ground, edge and bottom extension, checks R1-R4 with mutations), the
observation file with E at every site and one common H station (J2, so that T(s|b) = Q_s inv(Q_b) is exact for any base;
RR as an extra HTF station for Q and M referred to RR), two frequency lists (ADI's 9 periods; the 20 estimator periods),
forward-only control (ITERATION 0 0), the WSL launch, a parser to Z, Q, T and psi with the e^(-i omega t) convention
stated (conjugation flips psi). Verified on FEMTIC's example mesh: Q_s = Z_ss M_sb to 6e-7 and T from station outputs
against raw fields to 2.5e-5 (stations exactly on element edges first broke it: build T from station outputs only).
Coarse tests on v1 (7 min, 19.8 GB each): formats and impedance checks pass; the model transfer passes its gates; the
T = I half-space test at the true site positions FAILS at 0.18-0.53 deg at 10 s (0.02-0.07 at the mesh's own refined
stations): the mesh itself puts tenths of a degree into psi there. Found: the v1-v3 station table in FEMTIC_2026 is
mirrored north to south (v3 puts J2 north of A1; the loggers put J2 south of A01), so a v4 mesh on the logger positions is
the production mesh, pending the ruling (D1); the same mirror affects the author's own FEMTIC inversions. Production on v3 is
prepared, not launched: P0 (10 ohm-m half-space, the mesh's psi floor, 11-13 min, 33.6 GB) by default; P1/P2 (ADI's 9
periods, the 20 estimator periods, about 1.6-1.9 h) after D1. Also: ADI's predicted EDIs carry CMATRIX APPLIED=YES (det C
divided out in the checks); the model sampling choice moves the phase against ADI by 0.1-0.3 deg (subsample used).

**Vulcan 2024-25 impedances against lemimt** (21:11; IP home datasets/vulcan_2024_25/results/lemimt_replication_20261004,
criteria hashed 16:02 before any product; the comparison tool self-tested 5 of 5 and run by itself when the batch's
status table filled). The impedance batch (runs/impedance_20261004): 48 runs, 19 four-channel sites plus the five
electric-only sites with a neighbour's H, Nov in three 57 h parts, Mar whole; 47 ok on the first pass, Vul25_RR2
failed on the EMTF-XML writer (the clock-note bug, fixed; its four RR2 rows redone after the batch). Result: R1 PASS
at 14 of 14 sites with own H against RR1's (median phase difference within 2 deg per mode and apparent resistivity
within 0.1 in log10 over 1-100 s, against lemimt's per-segment median), R2 PASS at 5 of 5 B-replaced sites with the
same neighbour lemimt used, the shuffled-site mutation fails R1 as it must (0 of 14 at every shift); R3 (the three
legacy E-field sets) FAIL as expected (RR2's uncorrected 1 s clock in two sets, a collapsed column in the 017 set);
R4 (Vul24_019, magnetics dead from 23 Nov 23:00Z) undefined. Our Z and lemimt's agree at every site compared.

**The stack as the base for the magnetic tensor** (20:33; branch base-stack-h, 3 commits, fast-forwarded into main with the
reviewer's "commit"). For the Nador B-to-B work (as asked: "this is also where we want to do a stack"): --base-stack H makes the
band stack of the live sites' hx, hy the inputs of M (H_local = M H_stack; the local left out; the same constant-membership
rule, polarity screen and rejection as the E stack; E with telluric and H with magnetic, the other pairings refused), with
a third site's H or E or a reference stack as the reference, --remote-exclude for a reference stack built from different
sites, stems <local>_hm-stackH_rr-<ref>. Units recorded: a tensor on a per-band-normalised stack is in each band's units
(|M| is not a field ratio; phases, arg(det)/2 and same-column element ratios are unaffected); the sidecar now carries
stack_scale_rms per band and channel, and M_field[:, r] = M_stack[:, r] / stack_scale_rms[r] recovers the field ratio
when the members are calibrated alike (1.3 % median on the synthetic test). Test intersite_basestack_h_unit (M recovered;
the units check; a reversed coil flagged and dropped; the shared-stack mutation trips). Not in this branch: the cleaning
of the Nador magnetics before stacking (the PSD survey's filters) and the question whether cleaned data make the few
electric sites usable.

**Vulcan 2022 and 2024-25 combined** (19:30; IP home datasets/vulcan_2024_25/results/combined_2022_2024_25_20261004;
assumptions hashed 19:11 before any product). The 2024-25 sites put on the 2022 J2 datum through RR2 and A06 at
10-100 s: psi(site) on the campaign stack times (M-1)/M, minus psi(RR2) on the same stack (no leave-one-out factor:
RR2 is not a member; the factor would have moved every site by 0.3-0.4 deg, settled on the independent RR2-base
products), plus A06 on the J2 datum, plus the RR2-to-A06 ground difference. The datum offset is -3.33 +/- 0.35 (Nov)
and -2.47 +/- 0.35 (Mar) deg at 10-30 s, -2.08 +/- 0.19 and -1.30 +/- 0.18 at 30-100 s (realistic errors at 2.5x the
jackknife; A06's single 2022 product is 57-76 % of the variance; its I9 bridge product agrees to 0.05 deg). Found:
16 of the 20 new sites lie off the 2022 grid (north of row A, east of column 10) and continue the west-to-east fall
of psi; of the four within 2 km of a 2022 site, Nov 013 and Mar 004 fit, Mar 007 is 1.3 / 0.8 deg low (z -2.8 /
-3.6) and Mar 010 1.1 deg low at 10-30 s: local, since the three Mar sites share one datum; the campaign level fits
(Mar mean residual -0.6 +/- 0.4 and -0.3 +/- 0.2 deg); no change between 2022 and 2025 is resolved below 0.4-0.75
deg; the two campaigns agree where they nearly meet (0.05-0.46 deg); 1-10 s is not tied. Controls: the 2022 values
match the stack-base study to 5e-5 deg and the 2024-25 values the three-base closure to 5e-4; a 3.2x error factor
changes no verdict. To decide: tighten A06 by averaging its J5 and I9 products (a new hashed step); read 007 and 010
as ground north of row A or check their records; deliver the 10-100 s J2-datum values with realistic errors.

**Vulcan 2022 on the continuous E stack: the study** (18:31; IP home datasets/vulcan_2022/results/stackbase_products_20261004,
criteria hashed 15:32). Found: the stack gives one datum per night, not one datum. Each night's datum is the mean
psi of that night's stack members (+0.14 to -2.04 deg at 10-30 s on J2's E across the 12 nights), and the rrH map
predicts every night-pair offset to a median of 0.06 deg; within a night the datum is common to all sites (slope
1.04 raw against the M/(M-1) prediction 1.06, 0.98 corrected, r 0.97). No fixed-membership stack can span the
survey: no E channel is live on more than 3 of the 12 nights. After a network adjustment of the nights through
the shared sites (inverse-variance weights, gauge J2 = 0) the stack map reproduces the rrH J2-datum map
(Spearman 0.96 at 10 s, 0.99 at 10-30 and 30-100 s; chain error 0.13-0.16 deg at the last night), and the two
independent chains to J2 (the stack's nights, the rrH bridges) agree within 0.4 deg (at most 2.2 sigma),
parting from I9 onwards with opposite signs in the two bands (J5 -0.02, I9 -0.28, J10 -0.25, I10 -0.40 deg at
10-30 s); which chain is right is open. A site's psi scatters 0.08-0.11 deg night to night against jackknife
errors of 0.05-0.07, so one-night errors are lower bounds by 2-3x. As written, C2 (30 % within 2 sigma), C3
(68 %) and C4 (Spearman 0.48 on night means) FAIL because they assumed one datum; the adjusted results carry the
intent. Flags: H6 (three tests), E4, A10, and single flags at A05, J8, C6, A07, D7, E7, H7, J6, G4; night e105 is
quiet at 5-15 s. For the aim of one continuous datum: adjust the nights through the shared sites on band values,
carry the 0.3-0.4 deg chain disagreement from I9 on as a systematic until a joint adjustment explains it; the
2024-25 tie site A06 sits in J5, which closes to -0.02 +/- 0.14 deg.

**Vulcan 2022 on the continuous E stack: the batch** (18:04; IP home datasets/vulcan_2022/runs/stackbase_20261004). All 197
products made (99 sites over 12 constant-membership nights, RR's H as reference, G7 and the defect sites left out of
the stacks), 0 failures, no polarity flag, 45-186 s and 3-12 GB per run, three instances from 15:20 to 18:02.
The study against the criteria hashed 15:32 (health, night-to-night stability, within-night site differences
against the rrH products, the 10 s map against the rrH map) follows.

**Vulcan 2024-25: which E base** (18:00; IP home datasets/vulcan_2024_25/results/three_bases_20261004, criteria hashed
12:10 before any product; 153 products, 0 failures, batch 15:20-17:31 on three instances). Verdict: the campaign E stack
(every site's T on the band stack of the other numbered sites' E, RR1's H as reference) wins. Nov 2024: the stack's
median jackknife error of psi is 0.15 / 0.31 / 0.044 / 0.061 deg in the 1-3 / 3-10 / 10-30 / 30-100 s bands against
0.93 / 2.27 / 0.091 / 0.091 for RR2's E and 0.66 / 2.0 / 0.83 / 2.5 for RR1's E (clearly better, ratio under 0.7,
in all four bands); it also moves least between the first and last thirds of the record (0.04 / 0.015 deg at 10-30 /
30-100 s against 0.20 / 0.17 for RR2's E). Mar 2025: the stack wins three bands (ratios 0.34-0.97) and, scaled to
equal hours, all four; the 44 h four-channel stack is better still for those five sites (0.028 deg at 30-100 s).
RR1's E is last everywhere (4-60x the stack's errors) and its Mar products are biased below 9 s by its Ex defect.
RR2's E drifts about 0.1-0.2 deg within Nov (whole window against thirds fails at 57 %). The tie into 2022 passes
weakly through RR1 (its errors are 1.3-4 deg) and must go through RR2; the stack-to-RR2 step is +3.66 deg (Nov) and
+2.89 (Mar) at 10-30 s, closing to 0.06-0.09 deg once the leave-one-out term is removed: each site's stack leaves
that site out, which scales inter-site differences by M/(M-1) (about 1.11 with ten members; correct by (M-1)/M or
go through RR2 per site). The 26 Nov geomagnetic event sits in the middle third and carries all eight polarity
flags. Lesson on the criteria: the mutation "doubling one base's errors must change the winner" cannot flip a lead
larger than 2x, so it failed as worded while the comparison does change its winner at the right factor; future
templates state the mutation factor relative to the lead.

**Borrowed magnetics for electric-only sites** (16:19; branch h-from, 6 commits, merged into main as ef1954f with the
reviewer's "commit" after a one-character fix). Decided: "for the sites with E-field only, we can use the closest sites
magnetic field as its replacement, which is fine on these scales". Done: the per-site survey.yaml key h_from names
the neighbour whose hx, hy the ingest reads from its raw files and attaches to the local's runs sample for sample by
GPS time (the neighbour's calibration, h_scale, swap_h and clock offset applied; a partly covered run cut, an
uncovered run left out, both recorded; refusals for a local with its own H, a neighbour without H, a chained
h_from, a different rate, coverage under 50 %), recorded in the channel and run comments and the station
provenance, read back by ingest.archive_h_from; a test on two synthetic sites (sample-for-sample identity with
the neighbour's own archive, the cut and left-out runs, ten refusals, a one-sample mutation that trips); the
README. Declared for the Vulcan Mar 2025 electric-only sites with the neighbours lemimt used for its own B-replaced
impedances (004 and 005 from 007, 009 from 008, 012 and 018 from 011) and the five archives rebuilt. Caveats kept:
an h_from site and its neighbour must not be processed as a local-remote pair (the same magnetics twice); the
neighbour's re-ingest does not refresh the local's archive. Also from the lemimt inventory: Vul24_019's magnetics
are dead from 2024-11-23T23:00Z (confirmed in our archive; logged), so its impedance needs the same key.

**SimPEG forward study for natural-source IP** (14:55; `the projects folder6_Natural_Source_IP\modelling\simpeg\`, env mt_2026 via
conda run; criteria hashed 11:42 before any run; implementer, reviewer "fix" on three reporting points, fix,
reviewer "accept"). Found: (S1) SimPEG 0.24.0 with Pardiso reproduces the halfspace to 0.25 % and 0.013 deg
once the quadrants are read in SimPEG's east-north-up frame (the pre-registered MT-frame quadrants failed by
180 deg; amendment written after the fact and the original FAIL kept); (S2) the inter-site tensors from the
existing receivers are exact to 1e-16 (Q_s, Zorin's identity, T two ways, swap flips psi); a 10 ohm-m block
0.55 km thick at 0.54 km under the local gives the 1-D negative sign at 10-30 s only when wide (1-4 km sides
give +0.5 to +1.5 deg; 16 km gives -3.7 deg at 10 s against -10.5 deg for the same layer in 1-D) and the
uniform-H term is 0.7-1.9 deg, so psi and the local-minus-base impedance phase part company in 3-D; psi and K
move 10-15 % between meshes (caveat recorded); (S3) the scoping study's claim holds: a conductivity phase phi
on the block changes psi by K phi with K the real-sigma amplitude kernel, to 1.2 % for phi up to 0.05 rad,
residual second order, the phase-kernel mutation failing; complex sigma needs only a one-property subclass;
a polarisable body lowers psi in the author's convention; (S4) one forward over 9 periods on ADI's run 4 mesh does
not fit SimPEG's default path (about 173 GB and 51 min per frequency, extrapolated), fits with the matrix
declared symmetric (about 80 GB, 32 min, 5 h for 9 periods on an idle machine), while FEMTIC measured 34 GB
and 4-9 min per frequency; SuperLU is two orders slower than Pardiso; (S5) ADI's run 4 model reads into a
TensorMesh with the 98 matched sites placed to 0 m. Next: Stage 0 (residuals of the real-sigma prediction)
and the choice of forward engine for the full mesh (FEMTIC, or SimPEG with the symmetric path on an idle
machine).

**Vul25_RR1's Ex reversal declared, both product batches launched** (13:13). Decided: "lets do a visual comparison
for the Vul25_RR1s Ex, and if that passes then we can declare the azimuth at 180". Test 1 (six Mar windows
against RR2 and 007, the impedance quadrants; criteria hashed first) failed its thresholds on two noisy
windows and unresolved short periods while every window and every resolved band showed the reversal; test 2
(every 20-min window of the Mar record, 66 of 140 kept by a 3x amplitude screen fixed in advance) passed:
median r(ex) -0.75 and -0.72, no positive window, Nov 2024 control +0.77 and +0.74, the mutation failing as
required. Declared azimuth_ex 180.0 for Vul25_RR1 (the sign flip at ingest; the survey's filters.yaml flip
rule would not reach the raw-archive inter-site runs); the archive rebuilt in 76 s and verified (the six
windows exactly mirrored, nothing else changed). Also found: RR1's Mar Ex response is wrong below about 9 s
whatever the sign; and the ingest records a flip only in its log, not in the archive (chip raised). Then
the two runners were launched detached, in the order given: the 2024-25 three-base batch (153 products; the full
dry-run check 152 of 153, the one miss a 12 h minimum-overlap edge on an 11.9 h window, fixed by asking for
90 % of the window) and the 2022 stack-base batch (197 products; checked 197 of 197 from the identical
worktree code and 10 of 10 bracketing rows from main); both wait for the Z batch's DONE marker.

**The stack as the base** (12:08; branch base-stack, 4 commits, merged into main as 052df87 with the reviewer's
"commit"). Done: `process_intersite.py --base-stack E` takes the band-domain stack of the live sites' ex, ey
(the local always left out, the same --exclude, rejection and minimum-member options as the reference
stack) as the inputs, with a site or an H stack as the reference; a reference sharing a member with the
base stack is refused unless --allow-shared-members, and the overlap is recorded; the membership must be
constant inside the window (--window-members-constant, default; a start or end within 60 s of the edges
and sub-minute gaps do not count; --allow-member-change records a change instead); a polarity screen
correlates each member channel with the mean of the others over the 1-100 s bands, flags a negative
median and with --screen-polarity drop leaves the member out (G7's ex flagged at -0.98 on real data); the
sidecar's base block records members, per-band scales, rejected fractions, exclusions and the window; the
stem reads <local>_te-stackE_rr-<remote>[_<tag>]. Tests: intersite_basestack_unit (T recovered on a
synthetic stack; the member-change refusal; the polarity flag and drop; the shared-member refusal; a
mutation that trips), intersite_unit and intersite_stack_unit unchanged. Measured: A04 on 16 members over
a 16.6 h night in 106 s at 9.6 GB (about 0.036 GB per member-hour). Runners written, not yet launched:
the 2022 batch (197 products over 12 constant-membership nights, about 6 h) and the 2024-25 batch (153
products: three bases per site, Nov windows in thirds for memory), both in the natural-source IP home
under datasets/<name>/runs/, both waiting for the Z batch.

**Per-site clock offset at ingest** (11:37; branch clock-offset, 4 commits, fast-forwarded into main as
421467d). Done: the survey.yaml key clock_offset_s (seconds added to the recorded time stamps at ingest;
default 0.0; refused when non-finite, beyond 60 s, on a derived or observatory site or in defaults);
the shift applied to every run's time axis and the run, channel and station periods, the samples as
recorded; recorded in the run and channel comments, the station provenance and the ingest log, read
back by ingest.archive_clock_offset; a synthetic LEMI-423 test (4 tests, mutations trip); the README.
The campaign ledger is unchanged: its signature carries the raw archive's mtime, which the re-ingest
changes. Applied: clock_offset_s -1.0 declared for Vul24_RR2 and Vul25_RR2 in the Vulcan 2024-25 draft
survey (logger 10, firmware 2.0, stamps 1.000 s late), and the two raw archives rebuilt by a detached
batch (MT_Vulcan_2024_25_Workspace\qc\survey
eingest_rr2_20261004); the post-build check is the
cross-correlation lag against RR1, 017 and 007 within 20 samples. Follow-up noted by the reviewer: a
process_rr check that survey.yaml and the archive's recorded offset agree.

**The LEMI-120 coil table** (10:38; `2026_Natural_Source_IP\datasets\vulcan_2022\results\depth_20261004\coil_response\`).
Found: sensors/l120n.rsp, used by every survey and byte-identical to lemimt's l120new.rsp, has a +5.1 deg
phase point at 0.1325 Hz that raises every impedance phase by about 3 deg at 7.24 s and 1 deg at 9.12 s in
both modes (the largest jump between 1 and 30 s in the mt-workbench Vulcan, lemimt Vulcan and Morocco line B
sets alike, matching the table's prediction; an injected error is caught at z 26.5); its points below 2 Hz
scatter 0.7 deg about a physical response; its rows below 0.021 Hz are a template that may bias rho_a by
+20 % beyond 116 s (unconfirmed). T is unaffected; every Z-derived product is. Proposed: a new smoothed
table (candidate B) under a new name, re-ingest of every survey after the filtered variants are deleted,
reprocessing of the Z products and deliverables, and a coil-to-fluxgate test of the long-period rows. The author
decides. Chip: the variant freshness check must include the calibration table's hash.

**Band-domain inter-site stack merged** (10:35; branch stack-robust, 4 commits, merged into main as dda51c9 at
the decision: "accept the stack change as built and merge it"). Done: `--remote-stack` forms the reference per
band from the members' calibrated spectra (each member channel scaled by the square root of its median band
power; a member left out of a window above 25x the median over members; the kept members averaged; windows
with fewer than 2 members dropped), with `--stack-reject-factor`, `--stack-min-members` and the old time-domain
stack behind `--stack-plain` (byte-identical to the earlier products); the per-member per-band record in the
sidecar and h5; band_spectra gained an `optional=` argument. Tests: intersite_unit (criterion 9 on the band
stack) and intersite_stack_unit (7 criteria, mutations trip). Tested on the Vulcan J2 block at I2 and J3: the
whole-window effect is gone (error ratio to RR's H 1.26 -> 0.99 and 1.10 -> 0.99), I3's faulted-half cost is
gone, the plain control reproduces the study; two pre-registered criteria failed and were accepted by the author as
design, not defects: the constant per-band scale also rejects C2's weak ex (11 % of windows) and noise-floor
members in the quiet hours (5-8 %), and one long-period band shifts 1.016 sigma from the band form itself.
Open: the rejection-timing and rejection-off runs (run_robust_r2.py) once the machine is free; a dry-run
warning for two-member stacks; a stored fixture for the plain path; `--tag` to keep plain and band products apart.

**Vulcan drill holes as ground truth** (10:29; `2026_Natural_Source_IP\datasets\vulcan_2022\results\depth_20261004\drillholes\`).
Done: the author's May 2024 Excel work read (18 holes complete: stratigraphy tops, collars, surveys, desurveys) with
the 2026 notebook's partial port, the SARIG reports and ADI's Tasman trace files (VUD018/019 only there);
31 holes tabulated in GDA94 MGA 53. Found: the drilled basement lies 761-900 m below collar (median 844 m,
shallowest south); the data's Bostick 30 ohm-m depth at the nearest site sits on it (per-site r 0.64) while
ADI's 3-D model reaches 30 ohm-m about 100 m too deep and 50 ohm-m about 340 m too deep with no per-site
correlation; the 10 s telluric phase does not separate mineralised from barren holes (position and
mineralisation confounded; all mineralisation 810-1325 m under 760-900 m of conductive cover); core data
bearing on IP are sparse (magnetite only at VUD007, sulphur only at VUD001, no electrical logs). Errors in
The author's tables listed with their second source (magnetic azimuths, a 200 m northing, two dips, elevations,
CRS tags). Next, to decide: finish the port with the fixes, settle the azimuth frame, fetch SARIG envelope
11911's digital assays and petrophysics.

**Scoping a true 3-D natural-source IP model** (10:25; `2026_Natural_Source_IP\datasets\vulcan_2022\results\ip3d_scoping_20261004\README.md`).
Done: codes and feasibility (SimPEG 0.25.2 forms T from its Impedance receiver; pydiso is the gate; FEMTIC
built with measured costs; ModEM real sigma; complex sigma needs three changes per code; a first-order
Cauchy-Riemann shortcut makes the real-sigma amplitude kernel the IP sensitivity), the literature (36 papers;
no 3-D natural-source chargeability inversion exists; the controlled-source recipe carries over), a staged
plan with failure criteria. Finding: the obstacle is sigma0 leakage (a Z-fitted real-resistivity model can
absorb the IP phase; a 2 % Z floor equals the signal), tested by the Stage 0 extension and controls C2/C3.
The drill-hole tables show the collar IP does not separate mineralised from barren holes. Decisions open
listed on the board.

**Vulcan 2024-25 tie preconditions** (10:14; `2026_Natural_Source_IP\datasets\vulcan_2024_25\results\tie_preconditions_20261004\`).
Done: six pre-stated tests of the spatial tie RR1 = J1 (115 m) and RR2 = A06 (284 m): Z at the shared
ground, the RR repeats three months apart, the 2022 gradient, the RR1-RR2 telluric tensor against the
2022 chain, daily stability through Nov 2024, Vul25_RR2's last hours; 57 runs. Found: Vul24_RR2 and
Vul25_RR2 (logger 10, firmware 2.0) stamp their samples exactly 1.000 s late (invalidates every inter-site
product with RR2 until corrected; interim patched copies made); Vul25_RR1's Ex is reversed and noisy below
15 s, and RR1's Nov Ex is non-stationary; Vul25_RR2's H fails from 2 Mar 11:25Z. The tie is not the identity
at 1-10 s (RR2/A06 -5 to +1 deg per band with the same coils; both tie sites 30-50 m from the Borefield
Track) and usable at 10-100 s through RR2 as a per-band offset of about -0.1 deg with +/-0.1-0.4 deg error
(A06's shared Z error, a 0.1 deg Nov-Mar change, the J2-J5 link); RR1 not separable from a coil
calibration difference; |T| cannot be tied. Sceptic: numbers hold, framing corrected (T4 uninformative, the
error budget widened, T3's assumptions, the rain claim unsourced). Next: the decisions on the clock fix,
the RR1 flip, the RR2 trim and the tie rule; a daily series not on RR2.

**Vulcan depth constraint** (10:07; `2026_Natural_Source_IP\datasets\vulcan_2022\results\depth_20261004\`). Done: ADI's
RLM-3D resistivity model read (99 sites, 0.2 deg rotation, MGA 53; columns under all 100 sites); the
published 2022 impedances fetched from AusMT for all 100 sites (CC BY 4.0); Bostick and Schmucker depths
per site (z* 0.5 / 5 / 20 km and h_B 1.4 / 9 / 27 km at 1 / 10 / 100 s); the 2022 "3D IP model" decoded as
a period-layer display stack (per-site h_B/3 panels, uniform 530 sqrt(T) caption depths); depth slices of
arg(det T)/2; a 1-D Cole-Cole forward model (a resistive polarisable layer visible only above ~1 km, a
polarisable conductor to 6 km, a conductor alone giving -3 to -5 deg at 10-30 s); a Z batch for every site
against RR's H (running). Sceptic: in the J2 block the telluric phase equals the local-minus-base impedance
phase (Spearman 0.97-0.99 at 1-2 s, 0.32 deg median misfit) and ADI's non-polarisable model reproduces it to
0.31 deg: the IP evidence must be the residual a real-resistivity model cannot fit (<= 0.3-0.8 deg in J2).
Found: our Z products carry a +6 deg phase step at 5.9-7.4 s from a non-monotonic phase in the LEMI-120
response table l120n.rsp (T unaffected; 1-D depths from our Z not until fixed). Next: merge the write-up;
check the table across surveys; a 3-D forward with m = 0 twins.

**Vulcan 2022 full survey with RR's H, the base chain and the first files** (08:38;
`2026_Natural_Source_IP\datasets\vulcan_2022\results\survey_plan_20261004\` and `survey_rrH_20261004\`). Done:
all 102 archives ingested (253 GB); the leap-frog verified from the spans (both crews daily, two
alternating cohorts per half, 12-20 sites live, cohorts as diagonal bands so the five lemimt base
blocks are diagonal bands too); rrH (RR's H as reference) for the 68 remaining pairs and 35 bridge
second-base runs (103 runs, no failures); the four blocks compared with the origin EDIs (I9 0.20,
J10 0.15, I10 0.14 deg median like J2's 0.13; J5 0.42 with A04/B4/C3 2.6-3.6 deg below lemimt at
1.1-1.4 s; single-site OLS on both days never reproduces lemimt's values, so the difference sits in
lemimt's untraceable J5 inputs or hand-picks, not in the estimator); the bridge links
between adjacent bases (9/8/9/9 bridges) all fail the pre-stated chi2 test at 1-5 s and agree at
longer periods; block offsets on the J2 datum over 5-100 s without 14.48 s about -0.04, -0.65,
-0.51, -0.84 deg for J5, I9, J10, I10 (varying by over 1 deg with period; errors lower bounds), the
published I10 block about 0.5 deg below J10 by two estimators on the same records; a first-file
diagnostic over all sites (loud first files at J2 ex, E1 ey, E8 ey on three loggers; a weak
survey-wide settling; recommended rule: drop each site's first run). Dead channels: B5 ex at 0.2-10 s,
C2 on J5 at 0.5-11.5 s. Sceptic: arithmetic right, framing corrected (offsets per period, errors as
lower bounds, the J5 cause and the 14.48 s cause open). Next: the stack-base network as the
independent check of the chain; the decisions on the offsets, B5, 14.48 s and the first-run rule.

**Vulcan E-stack reference study and the 14.5 s edge test** (02:21;
`stack_tests_20261003\results.md`, `j2_replication_20261003\edge_test\README.md`). Done: an array E-field
coherence diagnostic (the J2 block's E is a two-source regional field; every member has the same
polarity; C2 ex weak and I3 ex failing on 13 Feb), then T at four adjacent pairs (I1, J1, I2, J3 on J2)
against eight references (E stacks of every concurrent site, the clean set, the quiet set, sites beyond
3 km, other lines, two halves; one far single E; RR's H; a far H), 88 runs + 4 reused, judged by rules
pre-registered before the first product. Result: the null outcome holds (no composition beats RR's H);
rrH and the far single E pass at all four pairs; the negative control did not fail the median rule, so
the study has no power on accuracy, although band by band the failing member doubles to quadruples the
error at 1.1-2.3 s on the faulted half; a whole-window effect at I2 and J3 (stack errors over the whole
window exceed both halves') points at the RMS-over-window member normalisation. Recommendation: RR's H
as the J2-block T of record, on cost; the stack code change (per-band scaling, array-relative fault
rejection) has a motive but no measured benefit yet. Edge test at A01 with three band layouts: the
+0.8 deg bump at 14.5 s stays put when the decimation-level edge moves, so it is not the level edge; the
same-data gap with lemimt stays open; 13-16 s at the north end unusable or floored at 0.8 deg. Two
sceptics (study, edge); write-up corrections applied.

**Vulcan J2 block replication complete** (01:11; `2026_Natural_Source_IP\datasets\vulcan_2022\results\j2_replication_20261003\`,
results.md and tables\block_summary.md). Done: 25 J2-paired sites processed with the native
inter-site estimator three ways (single-site least squares over the whole overlap, the 2022
lemimt mode; robust with an E stack of the other block sites; robust with RR's H) plus a
single-site pass on each pair's lemimt window parsed from Ying's LogFile.txt and a pass over
lemimt's picked sources; compared with the 2022 origin EDIs at 1-100 s under tolerances fixed
before the runs (median |d arg(det T)/2| < 0.5 deg, 90 % of bands < 1 deg, anomaly signs).
Result: the robust estimates match lemimt to 0.13-0.14 deg median over the block with ~0.09 deg
jackknife errors and 14/15 anomaly signs (C2 the miss); single-site least squares fails wherever
J2's loud first file (02:47-04:17Z, 12 Feb, >99.9 % of J2 ex's energy) enters the window, which
lemimt avoided by hand-picking; over lemimt's picked sources it matches at 23/25 (0.12 deg). Found:
I3's Ex fails from 20:20Z on 13 Feb; C2's origin rests on picks 2-5.7 deg off lemimt's own segment
median; lemimt's 2022 B1/D1 products carry a damaged 125 Hz run that lowers |T| but not
arg(det T)/2 (input noise leaves det T's phase unbiased); a +0.3 deg offset at 14.5 s (first band
of a decimation level) in every pair, probably processing (same-data OLS bends +0.24 deg more
than lemimt): a shifted-band-edge test is the precondition for the north-end 13-16 s values. Two
sceptics (first pair, block). Tested: every number recomputed independently; verdict logic 0
mismatches. Next: the E-stack reference study (runner started after the batch), the edge test,
The author's masks for J2 and I3.

## 3 Oct 2026

**Inter-site transfer functions, stage 0 landed** (21:47; branch intersite, 12 commits,
merged into main as 3264d56; evidence `D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace\qc\survey\intersite_validation_20261003\`).
Done: `mt_workbench/intersite.py` and `scripts/process_intersite.py` estimate the telluric
tensor T (E_local on E_base) and the horizontal magnetic tensor M (H_local on H_base) with a
third site or an in-memory E or H stack as remote reference: Huber IRLS (r0 1.5) with a
20-slice delete-one jackknife, each channel calibrated through its own MTH5 filter chain,
products CSV + JSON sidecar + HDF5 + PNG and no EDI or XML, a timing check that scans delays
and fits the phase at the cross-power-weighted band frequency (2 ms and 10 ms at 1000 Hz
recovered to 0.005 ms; a weighted-RMS turn rule says when the phase is not a clock offset
alone). tests/intersite_unit.py: 54 checks with mutations that trip. Tested: the port
reproduces the 28 Sep Morocco M of B18 on B17 (median 0.17 sigma); line D telluric D02 on
D16 with D14 as reference gives arg(det T)/2 errors of 0.3-0.8 deg at 23-90 s over 42 h;
line B gives 2-19 deg, and an H stack of seven line B sites disagrees with the single-site
reference in 38 % of bands (shared noise or optimistic errors; a data finding). Two review
rounds (README conflict, a build_stack archive accepted as remote, the timing check aliased
at 10 ms, its note fired on a pure delay; all fixed). Caveats: the chain is taken from each
site's first run; masks are not applied; stems carry no timestamp; a build_stack archive is
refused as remote. Interim tool by decision: aurora through a virtual pair station is
the production path. Housekeeping: about 30 GB of variant caches in the evidence folder's
verifier_r1\ws\mth5\*_f*.h5 can go.

**min_band_windows landed** (19:08; branch min-band-windows merged fast-forward to
main at 1d64c4e; evidence `qc/survey/min_band_windows_20261003/`). Done: the default
floor is 2 (process.py); the sidecar records `dropped_periods` (n, periods_s, the
floor; null for MANTLE); the Process tab's run options gained window samples, min bin
(0 reads "layout's own" and passes no flag; `--min-bin 0` now means that in
process_rr) and min band windows beside the four band controls, each a flag only
when moved off the survey's value, the floor disabled under MANTLE; campaign plans
take a top-level `min_band_windows:` applied to every aurora job and carried in the
ledger inputs, a config's own flag winning. Tests extended (min_band_windows_engine,
short_window, process_rr_cli, process_tab, campaign) with mutations that trip. Code
review: commit; the lineD plan's 242 job signatures and commands are unchanged
without the key. Verifier: B02 rr R01, C18 rr C19 (masked argv) and B10 rr B09
re-run; Z, Z.VAR and tipper exactly equal to the floor-5 products on every common
period and to the OLD references on every written period. **The expectation was
wrong in part:** floor 2 restores B10's 3663.6 and 4507.6 s (3 windows each) but not
B02's 231.7-583.9 s, which rest on ONE window and return only at floor 1 or 0 (a
floor-1 run equals OLD exactly); B02's 735.6 s never returns (drop_bad_errors: 1e32
variance). To decide: floor 2 or floor 1 as the default. Housekeeping: 54 GB of
rebuilt variants under the evidence folder's mth5/ can go; the EDI INFO block does
not name the floor (the sidecar does).

**TODO, superseded by the entry above:** `min_band_windows` default 5 -> 2 (option b), a Process-tab
control with the survey value as default, a campaign plan option, the dropped-period
count in the sidecar, and a re-run of the B02 rr R01, C18 rr C19 and B10 rr B09 reference
comparisons listing which periods still drop (the 1-window periods 3664 and 4508 s will).
Measured 3 Oct: the placeholder 5 drops 6 periods (232-736 s) at B02 and the two longest
at C18 and B10; delivered products are untouched until this is done.

**Timing round 2** (11:42-15:33; `qc/survey/timing_round2_20261003/README.md`; sceptic
stands with changes, corrections applied in each phase README). mt-workbench OLD a1781e3 ->
NEW 8eeac52, same session, quiet machine, steady GUI actions reproduced by the sceptic within
2 %: Process-tab pick 72.5 -> 0.23 s, ProcessTab.reload 57.0 -> 2.6 s, survey reopen 37.6 ->
0.98 s, View EDIs reload 5.8 -> 0.3-0.5 s, Cross-powers show 14.7 -> 0.27 s; the cold survey
open depends on the file cache (OLD 37.7-49.5 s, NEW 3.9-5.4 s with tf/index.json); masked
C18 rr C19 run 204 -> 182.5 s (masks parse 20.3 -> 2.4 s); variant B10 530 -> 450 s bit for
bit (8 cores instead of 3.5), C18 and C19 unchanged (notch-bound). Testing stack vs
mtproc-fixes, Z/VAR/tipper bit for bit on every period of every job: 6 h 31.5 -> 24.3 s,
B02 rr R01 1.2-1.3x, C18 rr C19 full 186.5 -> 141.0 s, B10 rr B09 376.5 -> 302.0 s with the
peak 51.9 -> 50.3 GiB (decimate bound at 2 threads, L1 phase 30 -> 33 GiB, 17 GiB under the
run peak); micro: jitter step 2.9-3.2x, prewhitening 1.9x, decimate 2.4x; Phoenix: the hour
of G5 builds in 19.8 s as 120 burst runs + 1 continuous, 480 burst channels exact; aurora on
the 120 runs 183 s (per-run cost unchanged, issue 46). Pipeline: the six bench pairs' rr stage
1061 s with TESTING + NEW against 1335 s on 2-3 Oct (1.26x; 1.18-1.65x per pair), peaks
within -2.6/+1.8 %, stack build unchanged; identity passes in full for A20, D02 and the stack
pair, and on every common period for C18, B02 and B10, where the placeholder floor
min_band_windows 5 drops the longest periods (the TODO above). Found: every product now
writes ZROT = site declination where the 28 Sep / 2 Oct references hold 0 (the 2 Oct
convention, not a defect; identity compares FREQ, Z, Z.VAR and tipper); the
bench_pipeline archive perturb control is a no-op for float32 stack archives (fix: a relative
perturbation); the headless GUI bench processes crash at teardown after os._exit(0). What is
left by size: the variant filter builds (1634 s on 2-3 Oct, notch-bound), aurora's regression
(41 % of rr) and STFT (35 %), and for Phoenix the per-run to_runts cost. Scratch to delete:
about 95 GB under the session scratchpad timing\ folder.

**Testing branches of the five forks, four rounds** (05:25-11:42;
`qc/survey/testing_branches_20261003/`; summary in `fork_branches.md`).
Done: branch `testing` from `mtproc-fixes` in every clone, 27 commits by the author
dated into the week of 28 Sep - 2 Oct, each fix with a test that fails on its
parent. Tested: each repo's full suite on the tip and on the parent export
(no new failure), the format gate as the repo's CI runs it, per-commit test
runs on git-archive exports, cross-partner suites with released partners
(the mth5 either-unit and the mt-metadata BandHarmonicError decouple the
repos), a 6 h C18 rr C19 identity after every aurora change, and paired
micro and run benchmarks (testing vs fork: 6 h 1.30x, full overlap 1.18-1.31x,
products bit-identical). Found on the way: the unbounded threaded decimate
raised the L1 peak by 8 GiB (bounded in round 2); prewhitening was not
bit-identical for single precision (np.float64 step); the every-burst
Phoenix reader broke mth5's PhoenixClient (fixed in mth5 round 3). One amend
was refused to an agent by the permission classifier and run by the
orchestrator from the worktree (501eee3b). Open: aurora fast path on inputs
without data variables; the author's review, push, install, PRs.

**mt-workbench fixes on main** (05:27-09:41; `qc/survey/workbench_fixes_20261003/`;
`workbench_issues.md`). Done: 28 commits (a1781e3 -> 8eeac52) from four
worktree branches rebased linearly, plus a polish pass and a notice fix.
Correctness: a B423 file cut mid-record ends the run with a WARNING instead
of shifting later samples by -2700 s; a short window writes no period
resting on too few STFT windows and no zero or non-finite error (floor
`min_band_windows`, placeholder 5; per-row blanking on merged rows); an
unknown declination is null in the XML and sidecar; the dry run refuses an
unknown site or a pair sharing no time. Clear failures: a held variant's
`.part` is deleted with one message; a memory gate above the machine
refuses at start; a current variant lists as ready; a workspace that cannot
be reached or made is reported without a modal box. GUI: masks.yaml parsed
once per change with libyaml off the GUI thread (survey open 52.5 -> 16.3 s,
Process pick 105.6 -> 0.45 s), spans from HDF5 attributes in one cache
(26.6 -> 1.15 s), View EDIs from tf/index.json (38.2 -> 0.51 s),
cross-powers 8 threads. Pipeline: the mains fit in time chunks (bit for
bit; the notch kept as it was), sidecar records each package's install
source and record hash, campaign default parallel from the gate, lazy
imports in compare, read_span name normalisation. Tested: 31 test files and
gui_smoke pass in the main checkout with the curnamona data (process_rr_cli
17/17, campaign 16/16); every new test shown failing on the parent tree;
clean-clone controls (a modal box that hung process_tab_unit on a clean tree
was found this way and removed); 6 h identity 0.0 after the correctness
changes; sceptics on every area and on the merge. Decisions open:
`min_band_windows` policy; merged-row blanking vs dropping; exit 2 for a
raw-folder site missing from survey.yaml; the stacked-SOS and chunked notch
patches (kept aside); tf/index.json in the live tf folder.

**Phoenix reconnaissance, Kalkaroo G5 and G8** (05:52-07:10;
`D:\MT_DATA\MT_Kalkaroo_Phoenix_TEST\qc_recon_20261003\`; memory note
`phoenix-burst-mode`). Found: MTU-8A, 150 Hz continuous in 360 s files plus
24 kHz bursts of 2 s every 30 s (12 per file, 2,880 a day; 2,705 slots shared
by the pair); mt-io returned the first burst of each file only, so a
PhoenixClient archive held 1/12 of the bursts (verified on a built hour);
`metadata_only=True` walked into the samples; the per-run metadata cost grows
with the runs in a station (0.375 s at 11 runs, 1.31 at 120, 3.88 at 360),
so a burst station-day is hours of overhead for 147 s of compute; the
site-folder EDIs are LEMIMT outputs of the MATLAB app, not EMPower; Phoenix's
format note says stamps are GPS time, continuous data start 1 s after the
recording start, and version-2 files carry stamps one second behind GPS
(Kalkaroo is version 2; uncorrected). Decisions: empower_recmeta.json
has priority over recmeta.json; monitoring needs every burst, so one run per
burst stays and the per-run cost must go (options C then B; D for the
Kalkaroo band question only). Issues 44-47 in `upstream_issues.md`.

**Records** (03:1x-03:2x): `fork_branches.md` and `workbench_issues.md`
created and allowlisted in .gitignore (a937bc4); upstream issues 37-43
(a937bc4), 44-46 (c98d3d3), 45 reworded (5dbc5e6), 47 (a1781e3);
`scripts/bench_pipeline.py` and the profile_run.py extensions committed
(26833a8); 13 workflow journals harvested into `qc/reports/`.

**GUI and pipeline bench on the Atlas workspace** (23:56 2 Oct - 03:07;
`qc/survey/pipeline_bench_20261002/`). Done: headless GUI profiling on the
full workspace and thinned copies (100 products; 10 archives; masks cut to
two sites) to attribute the slowness: masks.yaml (8.1 MB, 30,802 masks)
parsed whole on the GUI thread, 10.2 s a parse, 3-8 times per interaction;
then the EDI tab's 588 MB of sidecar JSON per reload; then span reads over
103 archives. Then the whole pipeline on five pairs and a stack from the raw
B423 files in an isolated bench workspace: 3,500 s (variant filters 52 %,
rr 38 %, ingest 8 %), peak 52 GiB at B10 rr B09 (aurora holding 19.5 GiB of
L0 series through the regression), every product identical to its live
reference and every raw archive sample-for-sample. Robustness: 18 cases,
four silent wrong outputs (now fixed on main). Tested by a sceptic per
report; `scripts/bench_pipeline.py` left as the fixture.

## 2 Oct 2026

**Fork PR readiness and performance** (19:50-23:44;
`qc/survey/fork_pr_readiness_20261002/`, `PR_INDEX.md` with 23 draft PR
bodies). Done: for each of the four IAGA forks a commit-by-commit review,
the full suite on the fork and the upstream tip (control), the format gate as
upstream CI runs it, stock-partner tests (two cross-repo couplings found),
PR grouping with draft bodies; paired stock-vs-fork benchmarks (309 timed
runs with controls: to_runts whole run 9.2 -> 2.3 s and 14.8 -> 3.9 GiB;
against released partners 2 h to_runts 3.0 -> 0.47 s mt-timeseries, 3.0 ->
1.65 s mth5; B423 read 0.45 -> 0.17 s; stock mt-io cannot read 46 of the 103
Atlas sites; stock mth5 modifies an archive on a run summary); a profile of
the 6 h and 44.9 h C18 rr C19 runs (90 % aurora; four trial patches
165 -> 125 s bit-identical; the ledger's 457 -> 181 s on the same 62 pairs
is the whole-stack change, not attributable to the four forks: sidecars
record no fork SHAs, since fixed). Blockers found: mt-metadata 405e7ff1
unpushed and not idempotent (fixed on testing); mth5/mt-io unit coupling;
mt-metadata/mth5 exception coupling; a test anchored on another commit.

**Declination and frames** (morning to 16:21; commits fe4afc4, 7b46e54;
`qc/survey/declination_xml_h5_20261002/`, `geotools_export_test_20261002/`;
memory note `declination-and-frames`). Done: survey.yaml gains declination,
declination_model, declination_epoch per site (IGRF-14 via ppigrf,
`scripts/declination.py`) and `layout_north`; every EDI carries
ZROT = TROT = +D with COORDINATE_SYSTEM geomagnetic, the DECLINATION header
and INFO frame lines; an EMTF XML and a TF h5 beside every EDI; the
mt-metadata fork fix 405e7ff1 (AZM, DECLINATION round trip, TROT warning).
Tested: four verifiers and a sceptic; the sample EDI equals its live twin in
Z and VAR at 0; the author's Geotools export test decoded the ZROT convention
(clockwise x-azimuth, R = [[c, s], [-s, c]]); import of a non-zero ZROT not
yet tested (to run). Upstream issues 31-36 (7b46e54).

**Line B best-of revision 2, galleries, the rename to mt-workbench, the
surveys folder** (07:25-14:00; commits ea27a49, 7624ba1, 84a24f8, 3759e75;
`deliverables/lineB_bestof_20261002/`; `qc/lineB/line/bestof_rev2_20261002/`).
See HANDOVER.md of that day and the notebook under `notes/lineB/`.
