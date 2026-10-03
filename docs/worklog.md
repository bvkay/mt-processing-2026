# Work log

What was done, how it was tested, where the evidence is, and what was decided.
One entry per piece of work, newest first. Evidence paths are under the
survey workspace `D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace` unless
given in full; `qc/reports/` holds the harvested workflow results and
`surveys/<survey>/notes/` the processing notebook. Times are Perth (WAST).

## 3 Oct 2026

**Timing round 2** (from 11:42; `qc/survey/timing_round2_20261003/`). The
frozen testing tips and mt-workbench main 8eeac52 against the pre-fix main
a1781e3 and the installed mtproc-fixes stack: GUI bench, whole-site variant
builds, a masked full run, campaign gate numbers, 6 h identity; then the
testing stack on the 6 h run, C18 rr C19, B02 rr R01 and B10 rr B09 (the
decimate bound must keep the peak at or under 51.9 GiB) and the Phoenix hour;
then bench_pipeline on the five pairs and the stack against the 2-3 Oct
baseline. Results in that folder's README when it lands.

**Testing branches of the five forks, four rounds** (05:25-11:42;
`qc/survey/testing_branches_20261003/`; summary in `fork_branches.md`).
Done: branch `testing` from `mtproc-fixes` in every clone, 27 commits by Ben
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
without data variables; Ben's review, push, install, PRs.

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
changes; sceptics on every area and on the merge. Decisions for Ben:
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
(Kalkaroo is version 2; uncorrected). Decisions by Ben: empower_recmeta.json
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
Z and VAR at 0; Ben's Geotools export test decoded the ZROT convention
(clockwise x-azimuth, R = [[c, s], [-s, c]]); import of a non-zero ZROT not
yet tested (Ben to run). Upstream issues 31-36 (7b46e54).

**Line B best-of revision 2, galleries, the rename to mt-workbench, the
surveys folder** (07:25-14:00; commits ea27a49, 7624ba1, 84a24f8, 3759e75;
`deliverables/lineB_bestof_20261002/`; `qc/lineB/line/bestof_rev2_20261002/`).
See HANDOVER.md of that day and the notebook under `notes/lineB/`.
