# Burra 2017–2020 — site QC notes

Findings from processing/QC, so nobody rediscovers them the hard way. Field
noise log per site/channel/file: `BurraTimingPhase2.xlsx`, sheet "File Quality
by Channel" (in the data root). Deployment stages and the remote covering each
are summarised in the handover.

## Timing flags ("Correct" / "Behind" / "No data")

The field timing sheets flag each June and Sep–Oct 2018 deployment. Tested
2026-09-22 whether "Behind" means a clock error in the data, by cross-correlating
each site's hx/hy against the remote Burra54rr3 (natural-field band, 1000 Hz
decimated to 10 Hz and to 1 Hz, lags to ±3000 s; a clock error would move the
correlation peak off zero lag):

- Burra35 (Correct): peak at 0.0 s, r ≈ 0.73/0.80 (hx/hy) at 10 Hz.
- Burra57 (Behind): peak at 0.0 s in both bands, r ≈ 0.40/0.31 at 10 Hz,
  0.34/0.20 at 1 Hz. **No clock offset in the data.**
- The per-sample GPS columns in the B423 records (`sync` = PPS deviation,
  `stage` = PLL accuracy) look the same at Correct and Behind sites: `stage`
  is 1 throughout, `sync` wanders within about ±9 at all four sites tested.
  They do not encode the field flag.

Tightened to 10 ms resolution (100 Hz, 3–40 Hz Schumann band): Burra35 and
Burra57 both peak at 0 ms against the remote (r up to 0.98; r ≈ 0 at ±1 s).
**No timing correction is applied.**

Ben's recollection (2026-09-22): "Behind" marked sites where processing was
troublesome years ago and a ~1 s timing difference was suspected but never
confirmed. The likely source is in the **remote**, not the flagged sites:
Burra54rr3's file `1529918021.B423` starts 1 s late (5401 s after its
predecessor) and is 5399 s long, so the following file is back on the
original grid. Its samples are correctly timed (peak at 0 ms against Burra57
for that file and both neighbours), i.e. only the file boundary slipped.
Concatenating files at a fixed 5400 s would shift everything after it by 1 s;
`bbmt.ingest` instead starts a new run at any spacing anomaly and keeps the
per-sample timestamps, so nothing needs fixing. Scan every site's file epochs
for this (Burra35/57/25 have none); `timing:` in `survey.yaml` is information
only.

## Channel problems

- **Burra35 Ex fails at 2018-06-22 21:45 UTC** (07:15 local on the 23rd),
  16.5 h into the deployment: raw std jumps from ~1e5 to 3.6e8 counts with
  spikes, then stays 20–50× noisier than before with spike bursts (files
  00:45 and 09:45 on the 23rd) to the end. Matches the field note "Ex cable
  pulled out". Effect on the first RR run (full overlap): yx matches lemimt
  0.005–1000 s, xy matches only below 0.3 s and is garbage beyond. Process
  Burra35 on 2018-06-22 05:15–21:40 UTC only (or mask Ex after 21:40 once
  per-channel time masks exist). Ey, hx, hy are fine throughout; one spiky
  magnetics file at 2018-06-23 05:15 UTC.
- **hz is dead at every Burra site checked** (Burra35, Burra57, Burra54rr3):
  raw Bz counts sit at exactly −2³¹ for the whole record (an open or
  unconnected input), so the tipper from these sites is meaningless. Found
  2026-09-22 by the whole-record overview (`scripts/site_qc.py`), confirmed
  on the raw files. Same at Curnamona E08 (constant) and D02 (saw-toothing
  between −2³¹ and ~−8.6e8). Check any site's hz in the overview before
  believing a tipper.
- **Burra25 hx is unusable** (2018-06-24/25): PSD floor flat to 500 Hz with a
  large 0.02–0.5 Hz hump, and no correlation with the remote's hx (|r| < 0.3
  in every file tested) while hy correlates at 0.93. Same failure class as
  Curnamona A07. hy also carries the low-frequency hump. Not a quiet control
  and not a stack member.
- Field-sheet channel replacements to remember when stacking: Burra89
  magnetics replaced with Burra88's for the whole run; Burra10repeat
  magnetics replaced with Burra08 after 30 min; Burra81 Ex electrode binned;
  Burra91 Ex cable cut; Burra35 Ex cable pulled out on retrieval; Burra18
  electrode out 3 h in.

## Noise character (raw PSDs, one mid-deployment file each)

- **Burra54rr3 (remote, Jun 22–27 2018)**: clean. 50 Hz only, faint 60 Hz
  line, Schumann resonances (8, 14, 20, 26 Hz) visible on all channels.
- **Burra35** and **Burra57**: cathodic-protection comb — harmonics of a
  ~12 s rectifier cycle — from ~0.08 Hz to ~5 Hz on hx, hy and ey (Burra35 ex
  is spared; Burra57 has it on all four), plus 50 Hz and harmonics to 400 Hz.
  Burra57 also shows a broad modulation skirt around 50 Hz on ex/ey. Burra50
  is the third CP site per the field log.
- **Burra35** dipoles are short (28.5 m Ex, 31 m Ey, Ey at 270°) — the rho
  level of anything processed from it depends on those lengths.

## First RR results (2026-09-22, lemimt band scheme, notches 50/150 Hz)

- **Burra35 RR Burra54rr3, full overlap**: yx matches lemimt 0.005–1000 s;
  xy only below 0.3 s (Ex failure above).
- **Burra35 RR Burra54rr3, window 2018-06-22 05:15–21:40 UTC, polarity
  fixed, unfiltered** (`..._vs_lemimt_unfiltered.png`): both modes match
  lemimt from 0.005 s to ~1 s and from ~15 s to 1000 s; 1–15 s unusable in
  both modes (the CP band).
- **Same, with the declared filters** (`surveys/burra/filters.yaml`: 50 Hz +
  harmonics zero-phase notch, then Ben's stack-and-subtract of the 12.0000 s
  cycle in 10-min windows on all four channels; archive
  `Burra35_rr-Burra54rr3_w20180622T0515-20180622T2140.edi`, figure in
  `docs/figures/Burra35_rr-Burra54rr3_filtered_vs_lemimt.png`): **both modes
  match lemimt in rho and phase from 0.005 s to 1000 s**, including the CP
  band — yx continuously with tight error bars (phase dip to 12° at 4 s
  reproduced), xy with wider error bars in 5–15 s (weak channel in the dead
  band) but on the curve. Beyond 1000 s only 16.5 h feed the estimate. Two
  detector-based variants tried on the way (`_cpv1`, `_cpv2` products) were
  worse: edge excision damages the record; see `docs/prototypes/`. **This is
  the reference Burra35 result.** What the stack leaves in the archive (comb
  line-to-floor ratio, hourly): coils ~0 dB in every hour (raw 16–19 dB);
  electrics 8–27 dB (raw 44 dB on Ey) — the cycle-to-cycle amplitude
  variation of the square wave, which a median template cannot follow. It
  costs RR variance, not bias. A per-cycle amplitude fit is the obvious next
  refinement if a site needs it.
- **Burra57 RR Burra54rr3 with the declared filters, 2018-06-24 03:05–22:15
  UTC (19 h)** (`Burra57_rr-Burra54rr3_w20180624T0305-20180624T2215.edi`,
  `docs/figures/Burra57_rr-Burra54rr3_filtered_vs_lemimt.png`; phases xy
  +37 / yx −139 deg vs lemimt +38 / −138): **both modes match lemimt from
  0.005 s to ~1000 s in rho and phase, through the CP band and at the
  short-period end**, with error bars comparable to lemimt's. Blemishes: one
  band at 0.017 s (59 Hz — the remote's faint 60 Hz line; add 60 to the
  band-scheme notches), yx noisy beyond ~300 s (19 h only). **Reference
  Burra57 result.** The unfiltered run below is kept for contrast.
- **Burra57 RR Burra54rr3, full overlap, polarity fixed, unfiltered**
  (`Burra57_rr-Burra54rr3_unfiltered.edi`, phases xy +17 / yx −103 deg at
  short periods): both modes match lemimt from ~15 s to 1000 s in rho and
  phase (xy continues cleanly to 5000 s). **0.3–15 s is destroyed** —
  this is the cathodic-protection band. Band coherence shows why: local
  ex–hy coherence ≈ 1 across 0.3–6 s while local-vs-remote hx/hy coherence
  ≈ 0 there, i.e. the CP signal dominates both local E and local H, the
  remote sees none of it, and the RR denominator ⟨H R*⟩ collapses. Below
  0.1 s aurora also drifts off lemimt (xy up to 5× low, yx phase 70–80°
  instead of ~40°); Burra57's ex/ey PSDs carry a broad modulation skirt
  around 50 Hz (≈35–65 Hz) that a ±8 % notch does not remove, and 100 Hz is
  not notched at all.
  **The CP cycle is 12.000 s** (fundamental 0.0833 Hz, harmonics at
  n × 0.0833 Hz; the field note's "every 6 seconds" is the rectifier's
  on/off half-cycle) — identical on Burra57 Ex and Burra35 Bx, i.e. one
  source. In the time domain (`docs/prototypes/cp_waveform`): the electrics
  carry a 12 s **square wave** (~2.5 s off-state, exponential settling
  edges) 30× the natural signal; the coils see a short **impulse** at each
  switching edge (two per cycle) and are clean in between.
  **What removes it (prototyped 2026-09-22, `docs/prototypes/cp_recipe.py`,
  one 90-min Burra57 file, metric = squared coherence with the remote's
  coils; CP-free control Burra25 hy: 0.86 in 0.3–2 s, 0.45 in 2–10 s):**
  - edge-locked folded template (10-min running median) drops the comb
    lines by ~31 dB on Ey and hx but leaves coil coherence unchanged
    (0.21→0.25 in 0.3–2 s) — the coil damage is broadband, not the lines;
  - **excising ±0.5 s around every switching edge** (linear interpolation,
    17 % of the record; ±1.5 s gains nothing) lifts coil coherence to
    0.59/0.64 (hx/hy) in 0.3–2 s and 0.59/0.49 in 2–10 s;
  - for the electrics, template + excision still leaves ex/ey vs remote-H
    coherence at 0.06–0.14 (a few % residual of a 30× signal), and hurts
    0.05–0.3 s (0.38→0.19) — E needs a per-cycle fit (separate on/off
    levels) or must rely on RR variance averaging. Untested in aurora yet.
  **Order (Ben): 50 Hz + harmonics first**, then CP on the cleaner series
  (`docs/prototypes/cp_recipe_notch_first.py`): edge scatter 7 → 5 ms,
  ey–remote-hx coherence 0.06 → 0.19 in 0.3–2 s and 0.40 → 0.64 in
  0.05–0.3 s, coils unchanged within scatter.
  Not automatic (Ben): the student sees the square wave / comb in the QC
  figures and declares the filter list for that site
  (`filters: [{notch: 50, harmonics: 9}, {cp: {period_s: 12.0, reference: ey}}]`);
  ingest applies it in order and records it in the archive. No
  single-station processing of any kind (the remote-H hybrid code was
  removed after the Curnamona test above).
  **"Replace magnetics" (hybrid local E + remote H, single-station) was
  validated on Curnamona and is biased**: D02 with E08's H (149 km apart)
  gives smooth curves 28–32 % off lemimt in rho and 4–6° in phase over
  0.01–100 s, against 3 % / 0.5° for D02 RR E08. The local impedance needs
  the local anomalous H; a distant H substitutes the source field only. At
  Burra57 (63 km to Burra54rr3) the hybrid may show the shape through the
  CP band but is not a product (`scripts/process_hybrid.py` kept as a
  diagnostic). Other options after template subtraction: notch 100 Hz and
  widen the 50 Hz guard (short-period fix only); a coherence-weighted stack
  of the other Jun 22–27 sites as a second remote.
- Inter-station magnetics coherence at Burra35 is ≈ 0 from 0.2 s to 20 s —
  a far wider dead band than Curnamona's 2–10 s, because the CP comb sits
  on the local coils there. RR still recovers yx through it.

## Mains at Burra35 (from the before/after PSD, 2026-09-22)

- The grid frequency wanders 49.91–50.09 Hz between 10-min blocks. One
  Q=30 notch at 50.000 leaves the line ~7 dB above the floor over 90 min
  (the spike inside the dip Ben spotted); two passes take it 20 dB below.
  `notch` now applies two passes by default; tracking the block's mean
  frequency does not help because the line moves within the block.
- Hx 75/125 Hz lines (odd multiples of 25 Hz, a separate source) are only
  0.4–0.7 dB above the floor in the file measured; declare them with
  `notch: {extra: [75, 125]}` if they matter for a site.
- The "noisy" 25–40 Hz on the coils is the higher Schumann modes (27, 34,
  39 Hz) at fine resolution; hx sits a uniform +2.2 dB above the remote
  across 20–45 Hz, no localized band.

## Stack members (coherence with Burra54rr3, notched; 0.3–2 s / 10–100 s)

Burra35's good-Ex window (Jun 22): only Burra10 (hx 0.54/0.65 usable, hy
0.08 dead) and Burra18repeat (both coils dead) were recording — too thin for
a stack. Burra57's window (Jun 24 12:00–20:00 UTC), per coil:

| member | hx | hy |
|---|---|---|
| Burra60 | 0.63 / 0.79 | 0.84 / 0.89 |
| Burra52 | 0.70 / 0.32 | 0.82 / 0.83 |
| Burra01 | 0.68 / 0.82 | dead |
| Burra07 | 0.36 / 0.70 | 0.80 / 0.80 |
| Burra34 | 0.36 / 0.62 | 0.67 / 0.63 |
| Burra25 | 0.35 / 0.16 | 0.76 / 0.57 |
| Burra37 | dead | 0.51 / 0.87 |
| Burra16 | dead | dead |
| Burra57 own coils | 0.29 / 0.27 | 0.34 / 0.51 |

STK57 (`scripts/build_stack.py`, per-coil member lists): hx = mean of
Burra54rr3 + 01 + 60 + 52; hy = mean of Burra54rr3 + 60 + 52 + 07 + 34, over
2018-06-24 03:05–22:15 UTC. Members carry their declared notch. **Result**
(`Burra57_rr-STK57_w...edi` vs `Burra57_rr-Burra54rr3_w...edi`, misfit to
lemimt as median |Δlog10 rho| / |Δphase|): outside the CP band the stack
ties the dedicated remote (xy 0.022 / 1.0° vs 0.023 / 0.8°); inside 0.3–15 s
it loses (xy 0.067 / 4.7° vs 0.029 / 2.2°; yx 0.052 / 3.7° vs 0.020 / 1.1°).
An unweighted mean gives the noisier members' coils the same weight as the
clean remote and adds noise where they are poor. Coherence *weighting* (per
member, per band) is the next step; expect it to converge to the dedicated
remote where one exists and to matter where none does (stages without a
Burra54 deployment) or at short periods where members are comparably good.
Open item: aurora reports zero impedance errors for the stacked remote
(same for the Curnamona SYN01 run) — a virtual-remote artefact to look at.

## Metadata caveats

- **Dipole azimuths are layout direction, not polarity.** With the Curnamona
  rule (sign-flip a 180/270 deg dipole) Burra35's yx phase came out at +19 deg
  and Burra57's xy at -163 deg over 0.01–0.1 s — each 180 deg out of the
  physical quadrant and 180 deg from the lemimt EDIs — while the unflipped
  modes were fine. The raw Burra channels are already in standard polarity
  (the crew wired by the logger's N/S/E/W terminals; the sheet has Ex/N,
  Ex/S, Ey/E, Ey/W electrode columns). `flip_reversed_dipoles: false` in
  `survey.yaml`; `scripts/process_rr.py` now checks the phase quadrants after
  every run and logs an error if a mode is 180 deg out.

- Folder names Burra18 / Burra18repeat hold the September and June 2018
  deployments respectively, the opposite of the field-sheet naming (b18 = June,
  b18r = September). `scripts/burra_notes_to_yaml.py` matches rows to folders
  by deployment time for this reason.
- `lemi423_metadata_summary.csv` `Start Time` is a constant +8 h from UTC; use
  the B423 filename epochs instead.
- Seven sites flagged "No data" on the timing sheet (17, 76, 78, 80, 81, 83,
  86) all have data files; Burra17 has no reference EDI.
