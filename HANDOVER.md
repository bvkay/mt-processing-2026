# BBMT-processing-2026 — handover (2026-09-22)

Where the broadband MT workflow stands after two sessions: the Curnamona
build-and-validate day (2026-09-21) and the first Burra (noisy) day
(2026-09-22). Repo: https://github.com/bvkay/BBMT-processing-2026

The student-facing command line is the table in `README.md`; every step is a
plain script (no notebooks, no LLM at run time). Per-site findings live in
each survey's `qc_notes.md`.

## What works (validated)

**raw B423 → MTH5 (mt-io readers) → aurora (RR) → EDI → comparison figure**

- **Curnamona D02 RR E08** (`examples/01_validate_d02_e08.py`): matches the
  merged lemimt EDI from 0.005 s to ~3000 s in rho and phase, both modes
  ([figure](docs/figures/D02_rr-E08_vs_lemimt.png)). Synthetic stacked remote
  and band-averaged coherence QC as before (`examples/02`, `03`).
- **Burra35 RR Burra54rr3** on its good-Ex window (first 16.5 h) **with the
  declared filters** (mains notch, then the 12 s stack-and-subtract): both
  modes match lemimt from 0.005 s to 1000 s including the cathodic-protection
  band ([figure](docs/figures/Burra35_rr-Burra54rr3_filtered_vs_lemimt.png);
  [unfiltered](docs/figures/Burra35_rr-Burra54rr3_window_vs_lemimt.png) for
  contrast: 1–15 s lost).
- **Burra57 RR Burra54rr3 with the declared filters** (19 h window): both
  modes match lemimt 0.005–~1000 s, through the cathodic-protection band
  ([figure](docs/figures/Burra57_rr-Burra54rr3_filtered_vs_lemimt.png);
  [unfiltered](docs/figures/Burra57_rr-Burra54rr3_vs_lemimt.png): 0.3–15 s lost).
- **Per-site QC set** (`scripts/site_qc.py`, ~75 s per site, plus
  `scripts/psd_qc.py`): whole-record overview, band coherence vs time,
  coherogram, spectrogram, and the calibrated whole-record PSD per channel
  with the remote overlaid — the figures Ben wants students to look at first
  ([D02 coherence vs time](docs/figures/D02_02_band_coherence_vs_time.png),
  [Burra57 coherogram](docs/figures/Burra57_03_coherogram.png),
  [Burra35 overview](docs/figures/Burra35_01_overview.png)).
- **Timing QC before ingest** (`scripts/timing_qc.py`): file-boundary slips,
  clock offset vs the remote by cross-correlation (10 ms resolution), GPS
  status per file.

Environment: `conda env create -f environment.yml` → `bbmt-2026` (mth5 0.6.9,
mt-io 0.0.5, mt-metadata 1.0.10, aurora 0.6.2). 128 GB Windows box; a
full-deployment RR run peaks ~45 GB and takes ~13 min; ingest of a 2-day
site takes ~30 s.

## The cathodic-protection band at Burra (solved for Burra35 and Burra57)

At Burra35 and Burra57 a high-pressure gas main's cathodic protection puts a
comb of lines (harmonics of a ~12 s cycle) from ~0.08 to ~5 Hz on **both**
local E and local H. Unfiltered, this made 0.3–15 s unusable in both modes;
with the declared filter list below, both sites match lemimt across the
whole band. Left in the archives: a residual electric comb (cycle-to-cycle
amplitude variation, costs variance not bias) and a real broadband coil
hump at 2–20 s that is in the raw data. Next refinements if a site needs
them: a per-cycle amplitude fit for the electrics; 60 Hz in the band-scheme
notches (the remote carries a faint 60 Hz line that shows as one off band at
0.017 s). Local Ex–Hy coherence is 1.0 across 0.3–6 s while
local-vs-remote magnetics coherence is 0 over 0.2–15 s, so the RR
denominator ⟨H R*⟩ collapses and **0.3–15 s is unusable in both modes**
([coherence](docs/figures/Burra57_rr-Burra54rr3_band_coherence.png)).
Below 0.1 s Burra57 also drifts off lemimt (a broad modulation skirt around
50 Hz on ex/ey that a ±8 % notch does not remove; 100 Hz is not notched).

The CP cycle is **exactly 12.000 s** (0.0833 Hz and harmonics; the field
note's "6 s" is the rectifier half-cycle), the same on Burra57's electrics
and Burra35's coils.

What was tried and what is next:
1. **"Replace magnetics"** (local E + remote H, single-station) was tried
   and **rejected**: on clean Curnamona data, D02 with E08's H (149 km)
   comes out 28–32 % off lemimt in rho and 4–6° in phase where D02 RR E08
   is within 3 % / 0.5° — the local impedance needs the local anomalous H.
   Together with Ben's rule (no single-station processing at all) the code
   was removed from the repo; the finding stays in `surveys/burra/qc_notes.md`.
2. **Implemented: the student-declared filter list at ingest** (`bbmt.noise`,
   `bbmt.ingest`, `<survey>/filters.yaml`; prototypes and numbers in
   `docs/prototypes/`), applied in the listed order: (a) `replace` — borrow a
   magnetic channel (one or both) from another site over the run's span,
   with that site's own coil calibration, for a dead or swamped coil; (b)
   `notch` — **50 Hz + harmonics first**, zero-phase, it recovers the
   electrics' coherence with the remote; (c) `cp` — **Ben's KISS stack**: in
   every 10-min window stack all cycles at the declared period (12.0000 s at
   Burra; the interrupter is crystal-locked) and subtract the median cycle
   from every channel. Nothing detected, nothing cut: on 12 h of Burra35 the
   plain stack raised coil coherence with the remote 0.49 → 0.71 in 0.3–2 s
   with 0.05–0.3 s untouched, while every edge-excision variant pushed it
   below raw (`docs/prototypes/kiss_variants.py`). Never automatic: the
   student sees the square wave / comb in the QC figures and declares the
   list for that site; ingest applies it and writes the provenance into the
   run comments; then RR as usual. Declared: Burra35, Burra57
   (`surveys/burra/filters.yaml`); A07 hx ← A06 (`surveys/curnamona_cube/filters.yaml`).
   Outcomes in `surveys/burra/qc_notes.md` and `surveys/curnamona_cube/qc_notes.md`.
   `replace` is proven on A07 (dead hx ← A06, 32 km): xy unchanged and matching
   lemimt, yx smooth and physical over 0.005–1000 s
   ([figure](docs/figures/A07_hx-from-A06_rr-E08_vs_lemimt.png)); a borrowed
   coil's mode carries the uniform-field assumption, so label it as borrowed.
3. Notch 100 Hz and widen the 50 Hz guard (short-period fix only).
4. **Stacked remote, tried on Burra57** (`scripts/build_stack.py`, per-coil
   member lists from the member QC in `surveys/burra/qc_notes.md`): an
   unweighted mean of the clean remote plus four to five noisier concurrent
   sites ties the dedicated remote outside the CP band and loses inside it
   (misfit roughly doubles). Coherence *weighting* per member and band is the
   next step; it should converge to the dedicated remote where one exists
   and matter where none does (stages without a Burra54 deployment). Open
   item: aurora reports zero impedance errors whenever the remote is a
   virtual (uncalibrated) station — SYN01 yesterday, STK57 today.

## Decisions made

- Thin library, headless first, GUI later; decisions are data (per-survey
  YAML); visual comparisons over numbers; site = folder name.
- **No single-station processing at all** (Ben, 2026-09-22): every product
  is remote-referenced — an adjacent site, a dedicated remote, or a stacked
  synthetic remote. (`process_station` still accepts no remote only so the
  Curnamona example can show why single-station is wrong.)
- **Noise removal order: mains first, then cathodic protection**, both as a
  per-site declared filter list, never auto-detected (CP is a minority case).
- **No hz on any broadband deployment** (Ben): no sensor was attached, the
  B423 Bz column is an open input (constant −2³¹). Survey `channels:
  [ex, ey, hx, hy]` drops it at ingest; no tipper is produced. Archives
  ingested before this (D02, E08, Burra35, Burra57, Burra54rr3) still carry
  the dead hz — re-ingest them (30 s each) before any single-station run,
  because a constant output channel makes aurora's single-station regression
  fail with "array must not contain infs or NaNs" (RR runs tolerate it).
- **Burra field-sheet azimuths are layout direction, not polarity**
  (`flip_reversed_dipoles: false`); at Curnamona a 180° azimuth did mean a
  reversed pair. `scripts/process_rr.py` checks impedance phase quadrants
  after every run and logs an error if a mode is 180° out.
- **Processing window ≠ archive window.** One MTH5 per site holds the whole
  deployment; `start`/`end` on the processing scripts trim aurora's kernel
  dataset (`bbmt.process.clip_to_window`).
- Agent usage (for the humans): Fable designs and verifies; sub-agents get a
  frozen spec, reference code where it exists, a falsifiable test, and files
  nobody else is editing. Sonnet is fine for mechanical ports; Opus was worth
  it for the field-sheet reconciliation and the AusLAMP figure port.

## Hard-won facts (do not rediscover these)

1. **LEMI-423 magnetics come out of mt-io in pT with inverted polarity**
   relative to the lemimt convention: CoefficientFilter gain −1000
   (`h_scale`). Coil response `sensors/l120n.rsp` (a copy sits with each
   survey config).
2. **Contiguous B423 files must be merged into long runs at ingest**; a new
   run starts at any epoch-spacing anomaly. That is also the whole timing
   story at Burra: the "Behind" flags on the field sheets are **not** clock
   errors (Burra35 and Burra57 align with the remote to 0 ms); the one real
   1 s event is a file-boundary slip in the remote Burra54rr3 (one file
   starts 1 s late and runs 5399 s, samples inside correctly timed). Naive
   5400 s concatenation shifts everything after it by 1 s — almost certainly
   the "1 second difference" remembered from the lemimt days.
3. **Band scheme**: 10 periods/decade, factor-4 levels, window 128, 75 %
   overlap on long windows; mains notched at 50/150 Hz.
4. **The RR estimator is calibration-invariant**: synthetic remotes stack
   raw counts; GPS ms grids align exactly (asserted).
5. **One dead channel poisons a mean stack** (Curnamona A07 hx; Burra25 hx
   is likewise unusable).
6. **Ex failures show up in the overview figure and kill one mode**: Burra35
   Ex died 16.5 h in (cable pulled); process on the good window. Per-channel
   time masks are the general fix (not built yet).
7. **Dead bands**: Curnamona 2–10 s (natural, time-varying — the coherogram
   shows it recover during the 06-30 disturbance); Burra 0.2–20 s on the
   local coils because of the CP comb, yet RR still recovers the modes
   outside 0.3–15 s.
8. **Code gotchas**: RunTS channel accessors return copies (edit
   `run.dataset` / `run.filters` in place); aurora needs `num_samples_window`
   as a per-level list with `band_edges`; `MTime` needs `str()` before
   `pd.Timestamp`; **never open an MTH5 another process has open** (HDF5
   locking — sequence runs, and keep sub-agents off archives in use);
   `KernelDataset.restrict_run_intervals_to_simultaneous` must not be called
   in single-station mode; mt-io discards the per-sample GPS `sync`/`stage`
   columns (`docs/upstream_issues.md` #4).

## Burra survey facts

- Raw: `E:\MT_Timeseries_DATA\MT_Burra_2017-2020`, 94 zips (332 GB), each
  unzips in place to `Burra##/` — that folder is the survey `data_root`.
  Extracted so far: Burra35, Burra57, Burra25, Burra54rr3 (Jun 22–27 2018
  stage) and Burra33 + Burra54rr (Jun 4–13, the clean long pair, not yet
  processed).
- Five stages, each with its own Burra54 remote deployment (Burra54 for
  Oct 2017; Burra54rr, rr2, rr3, rr4 for the four 2018 stages). Which sites
  are concurrent with which remote: memory note / `qc_notes.md`.
- Config: `surveys/burra/survey.yaml` (93 sites, generated by
  `scripts/burra_notes_to_yaml.py` from the field sheets with time-based row
  matching — the Burra18/Burra18repeat zips are labelled opposite to the
  field sheet), `reference_edis.yaml` (92/93 mapped; Burra17 has no EDI).
- Field-noise log per site/channel/file: `BurraTimingPhase2.xlsx`, sheet
  "File Quality by Channel". CP sites: 57, 50, 35.

## Next steps

1. Coherence *weighting* for the stacked remote (per member, per band
   group; `bbmt.virtual.build_synthetic_remote` already takes per-coil
   member lists) and fix aurora's zero error bars for virtual remotes.
2. Add 60 Hz to the Burra band-scheme notches (the remote's faint 60 Hz line
   shows as one off band at 0.017 s at Burra57) and re-check.
3. Re-ingest the remaining old archives without hz (D02, E08: delete the
   `.h5`, rerun `scripts/process_rr.py`; 30 s each). Burra35, Burra57,
   Burra54rr3 and A07 are already current.
3. Burra33 RR Burra54rr (clean long pair, already extracted): the Burra
   clean-pair check against `Burra33.edi`.
4. Per-channel time masks driven by the coherence-vs-time figure (Burra35 Ex
   after 21:45 UTC is the first use case), then coherence-weighted stacking
   across the 22 sites of the Jun 22–27 stage.
5. 50/100 Hz band-placement experiment on Burra57's short periods.
6. Earth Data logger ingest, batch CLI, then the Panel GUI.

## Figures

| | |
|---|---|
| ![Burra35 windowed RR](docs/figures/Burra35_rr-Burra54rr3_window_vs_lemimt.png) | ![Burra57 RR](docs/figures/Burra57_rr-Burra54rr3_vs_lemimt.png) |
| ![Burra57 coherogram](docs/figures/Burra57_03_coherogram.png) | ![Burra35 overview](docs/figures/Burra35_01_overview.png) |
| ![D02 coherence vs time](docs/figures/D02_02_band_coherence_vs_time.png) | ![D02 RR validation](docs/figures/D02_rr-E08_vs_lemimt.png) |
