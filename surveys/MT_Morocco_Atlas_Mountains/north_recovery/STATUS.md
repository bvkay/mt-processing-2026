# North recovery: status

Last updated 2026-09-25, about 17:40 local (UTC+8), after round two.

- **Record.** `LOG.md` holds every experiment's question, method, command, numbers and verdict. Round one is V00, E00-E11; round two is V01, E12-E15.
- **Per experiment.** Each folder `E<nn>_*/` holds the script, figures, `metrics.json` and `run.log`.
- **Shared code.** `nr_common.py` has the loaders, calibration, bands, plain RR, coherence, scorecard, and the in-memory decimation of round two. `nr_array.py` has the array methods of round two.
- **How to run.** Every script runs as `python <folder>\<script>.py` from `qc\north_recovery` with the bbmt-2026 environment. It imports `mtproc` from the worktree `D:\BEN\BBMT_Processing_2026\.claude\worktrees\agent-ae84cc9fb8c936a00\src`, which still has the pre-rename package name.

## Is the source removable in principle?

**Not from these data. That is now a property of the data, not only of the methods tried.**

1. **The cancellation methods work on a source they can represent.** In the positive control (E12), a railway-like synthetic was injected at 40 dB over the natural E into the clean March array. It used B01's real burst-plus-continuous waveform, near-zero-phase E/H, and a site-specific polarisation. With rank 1 or 2 and a fixed pattern, it is removed to the natural level by the round-one cancellation (E06/E07: array H differences as natural-free references). B28's TF comes back: yx strict 1.00, phase within 3 deg, rho within 0.04 dex.
2. **The real source is not such a source.** The rank measure of E13b gives the target's E left after removing k components of the whole array's E field, with the target inside the basis, so it is optimistic. On the synthetics (E13c) it reaches the natural share with 1 component (rank 1), 2 (rank 2) or 4 (moving pattern). On the real data it stays far above even with every E channel of the array:
   - B01: -27 dB after 5 of 6 components, against -57 dB natural.
   - B04: -24 dB after 6 of 12, against -45 dB.
   - B10: -12 dB after 6 of 12, against -42 dB.
   - The same holds per hour in train hours.

   The source has more independent components than the arrays have channels at the precision needed. Its dominant pattern is stable in train hours (hourly similarity 0.96 in February, 0.90 in July) but carries spatially incoherent parts of a few percent of the power between sites 5-10 km apart, and a different structure at night (E13).
3. **The methods also have limits of their own, which apply even to an ideal source.**
   - **Leak at 55 dB.** At B01's level, an ideal rank-1 source still leaves +9 to +17 dB of natural leak at 10-100 s: the natural H gradient and coil noise in the references, multiplied by the source's large E/H. That costs about 10 deg of phase (E12 V2).
   - **Moving patterns.** A moving pattern defeats whole-record coefficients (E12 V4).
   - **Time-local fits.** No time-local canceller fitted in 10-30 min blocks passes both the clean control and the synthetic (E14). With natural-carrying references it removes the natural field. With a source subspace it cannot identify the natural part along a fixed source pattern. With natural-free references the blocks are too short.
4. **Physics.** The first physical model (E15) is a straight line of six segment currents at 300 m depth, solved from the array's H. It explains 58-86 % of the source H at four of six July sites. It explains 87 % (-9 dB) of the E at B10, but the E at nearly no other site. So a line current describes part of the source, and an inversion with the real geometry is the only route with a physical basis.

**By which method, if any?**
- **Nothing gives a physical TF at the northern sites above ~1 s from the existing records.**
- **What does work:**
  - the natural H at long periods: weighting (E05) or gating (E09), and B10's magnetic transfer function (E11);
  - at 1000 Hz, automatic night-time burst gating to about 1.1 s (E10), matching the hand masks.
- **If processing is continued, the method with a demonstrated basis is the whole-record array cancellation with natural-free references plus inverse-noise weighting (E07).** It removes a fixed low-rank source at 40 dB (E12). But the real source's excess rank (E13b) means it cannot reach the natural level here.

## What a full effort would need

1. **Natural-free references with at least as many independent channels as the source has components.** E13b shows the existing arrays' E channels are too few and too far apart, and every array channel carries natural signal (E14's control). The cleanest reference is the source itself:
   - the traction currents: ONCF substation and feeder currents, logged at 1 s or faster with GPS time;
   - or magnetometers and short E dipoles at the track and feeders.

   A reference of that kind contains no natural field, so there is no leak (E12 V2) and no loss of natural signal (E14).
2. **Dense local sampling of the leakage field around each target.** Several E dipoles within 1-2 km are needed, because the source's site-local part decorrelates over 5-10 km (E13b).
3. **Long records (weeks), not days.** They are needed to beat the leak and the jackknife errors at 55 dB. E12's leak falls as the references' own non-source power is averaged down.
4. **A real source geometry for a physical inversion.** That means the track, feeders, substations, the Ben Guerir and OCP lines and their current records, with a 3-D conductivity model for the galvanic E (E15). The straight-line model already explains much of the H.
5. **Or avoid the problem.** Record during a traction outage, or site stations away from the corridor. How far the source's E decays with distance from the track is unknown and would itself need a short profile of E dipoles.

## Experiment table, round two

"removed/recovered" refers to the synthetic truth. cohE is the coherence of the target's cleaned E with Ebro, 30-300 / 300-1000 s, with the null in brackets. "yx strict" is over 10-1000 s.

| id | method | case | result | verdict |
|---|---|---|---|---|
| V01 | in-memory decimation vs decimate_site | B04 | rms diff <= 4e-4 | pass |
| E12 | E06/E07 on synthetic V1 (rank 1, fixed, 40 dB) | B28 array | residual -14 to -23 dB, leak -4 to +2 dB; TF 16/16 bands in 2 sigma; yx strict 1.00 | method sound |
| E12 | V2 (55 dB) | B28 array | leak +9 to +17 dB at 10-100 s; phase error ~10 deg; yx strict 0.31-0.38 | method limit at B01's level |
| E12 | V3 (rank 2) | B28 array | residual -8 to -19 dB, leak +3 to +7 dB; yx strict 0.69-1.00 | mostly recovered |
| E12 | V4 (moving) | B28 array | residual +2 to +10 dB; agreement 0.62-0.81; yx 0.44-0.75 | whole-record coefficients fail |
| E13 | array rank (coherence form) and hourly pattern | Feb, Jul, Mar | 2-3 structures in E above the noise edge; leading pattern fixed in train hours (0.96/0.90), different at night (0.12/0.47) | looks low rank at the noise level, but see E13b |
| E13b | target E left after k array components | B01, B04, B10 | -27 dB (B01, k=5), -24 (B04, k=6), -12 (B10, k=6), against -57/-45/-42 natural | not low rank at the needed precision |
| E13c | E13b on synthetics | B28 array | natural level at k=1 (V1, V2), k=2 (V3), k=4 (V4) | the measure works |
| E14a | time-local Wiener, refs other sites / source-dominated E, 10-30 min | control, V1, V4, B01, B04, B10 | control destroyed (cohE 0.5 -> 0.01); V1 not recovered (0.19-0.69); real cohE at null, yx 0 | fails the control |
| E14b | time-local source subspace + GLS | same | identity check passes (3.7e-13); tau 30 removes natural at the control; tau 300 keeps it but does not recover V1; real cohE at null, yx 0-0.12 | fails the synthetic |
| E14c | time-local natural-free (H-difference) refs | same | control coherence lost (0.5 -> 0.02-0.2); V4 residual +12 to +18 dB; real cohE at null | fails |
| E15 | straight-line railway currents (Biot-Savart), galvanic E | Jul array, 19.5 h | H explained 58-86 % at 4 of 6 sites; E explained 87 % at B10, <= 21 % elsewhere; B10 cohE 0.008/0.128 -> 0.074/0.355 (0.010/0.064), yx strict 0; B14 check unchanged | not a partial success by the criterion; B10 is the hint |

## Round one in one paragraph

At B01, B04 and B10 the local E has no coherence with Ebro above a shifted-Ebro null at any period from 4 to 4096 s. The source dominates E by 27-55 dB (power) and H by about 20-25 dB. Round one scored ten levers (E02-E11): projection onto Ebro, which is RR under another name; quiet time; polarisation; weighting; array cancellation; burst gating; and 1000 Hz night gating. They clean the H but never the E. At 1000 Hz, automatic night gating reproduces the hand masks to about 1.1 s. B10's magnetic transfer function to B14 is M = I within 15-25 % at 40-3000 s. Details in LOG.md, E00-E11.

## Not tried, and why

- **FastICA and scikit-learn in general.** Not installed, and nothing was installed. Any linear unmixing is bounded by E13b.
- **Wavelet masking.** pywt is not installed, and scipy 1.17 has no cwt. The STFT gating covers the same ground.
- **Template or Kalman subtraction of the bursts.** The continuous inter-burst source keeps E at the null after the bursts are gated out (E09).
- **A source inversion with the real track, feeder and substation geometry and 3-D conductivity.** It needs data this project does not have. It is the next step if Ben can get the geometry and the traction current logs.
- **Longer time-local blocks (hours).** They converge on E07, which is already bounded by E13b.
- **More July sites in the array.** B05 and B07 end on 20 Jul, and B11 and B13-B15 are south and clean. The six-site set is the largest simultaneous one.
- **B01 at 1000 Hz with a clean remote.** None exists in February.

## Open questions

1. **What the continuous night-time source is** (E13: a different pattern at night; E00b; E09). Candidates: substation standing leakage, OCP installations, cathodic protection.
2. **Whether ONCF or OCP current logs exist for Feb and Jul 2023.** With them, E12 says a cancellation with natural-free references would work for the part of the source they describe.
3. **Whether B04's xy at 1.5-10 s is natural** (round one, E10).
4. **Whether B10 can be extended with a better geometry** (E15: 87 % of its E from a straight line).

## Housekeeping (for Ben)

- **1 Hz derived archives from round one.** Made with `scripts/decimate_site.py`, each with its survey.yaml entry: B02L, B03L, B05L, B06L, B07L, B08L, B09L, B10L, B11L, B14L and R01L. B01L, B02L, B07L, B10L, B14L and B28L predate the dipole re-ingest; rebuild them with `--force` before any rho product. B13L and B15L were not made. `decimate_site.py B11` built `B11_f81e4c0e6.h5` (10.9 GB) because filters.yaml had changed.
- **Round two wrote no archive and no survey.yaml entry.** 1 Hz counts are cached in `qc/north_recovery/cache/` (about 170 MB, 21 files). They are safe to delete; they rebuild on demand.
- **Aurora product made.** `tf/B10L_rr-EBR_20260925-1618_nr-E01.*` (round one).
- **No repository file was edited. No archive was opened for writing.**
