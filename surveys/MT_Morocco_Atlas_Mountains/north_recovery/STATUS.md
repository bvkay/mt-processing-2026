# North recovery: status

Last updated 2026-09-25, about 17:00 local (UTC+8). The work is finished and stopped at the wall described below.

- **Record.** `LOG.md` holds every experiment's question, method, command, numbers and verdict.
- **Per experiment.** Each folder `E<nn>_*/` holds the script, figures, `metrics.json` and `run.log`.
- **Shared helpers.** `nr_common.py` has the loaders, calibration, STFT bands, plain RR, coherence and scorecard.
- **How to run.** Every script runs as `python <folder>\<script>.py` from `qc\north_recovery` with the bbmt-2026 environment. It imports `mtproc` from the worktree `D:\BEN\BBMT_Processing_2026\.claude\worktrees\agent-ae84cc9fb8c936a00\src`, which still has the pre-rename package name.

## Bottom line

The natural MT impedance above about 1 s is not recoverable at B01, B04 and B10 with these data.

1. **The source's E is the limit, not its H.**
   - The source E exceeds the natural E by 27-55 dB in power over the whole record, at every period from 4 to 4096 s. That assumes a natural rho of 100 ohm m; subtract 10 dB for 1000 ohm m. The worst case is B01 ey (51-55 dB), the mildest B10 ey (27-32 dB).
   - The local E has no coherence with Ebro above the null at any period.
   - The local H is partly natural: coherence with Ebro reaches 0.3-0.75 above 300 s.
2. **Every lever gains 10-40 dB at most.** The levers were:
   - projection onto Ebro, which is identical to RR;
   - quiet-time selection;
   - polarisation filtering;
   - inverse-noise weighting;
   - an array model with natural-free references;
   - their combinations;
   - burst gating at 1 Hz and at 1000 Hz.

   The best linear prediction of the source's E from the local H plus eight neighbour channels still leaves it 10-300 times above the natural E over the whole record (E06). With weighting, it leaves 1-10 times (E07).
3. **At 1000 Hz on the one quiet night with a clean remote,** an automatic, local-only burst gate reproduces Ben's hand masks at B04. The yx is physical-looking to 1.15 s. Above that the phase falls to 0 while rho climbs: the source takes over again. A physical-looking B10 yx to 2 s on one night did not repeat on the two other nights (E10b). With 6 h of July night-time data, even the clean control B18 does not resolve 1.5-10 s.
4. **What H does allow.** The natural H is recoverable at long periods (E05, E09, E11). B10's horizontal magnetic transfer function to B14 is M = I within 15-25 % at 40-3000 s.

## Experiment table

cohH is the mean multiple coherence of the local hx and hy with Ebro. Each cell gives before -> after, with the after row's null in brackets. Periods are 30-300 s and 300-1000 s at 1 Hz. "yx strict" is the fraction of 10-1000 s bands (E01: 4-1000 s) with yx phase in (10, 80) deg and within 15 deg of its neighbours. Before rows use the same layout and span as the after rows.

| id | method | site | cohH 30-300 | cohH 300-1000 | yx strict | verdict |
|---|---|---|---|---|---|---|
| E00 | characterisation | B01/B04/B10 | 0.047 / 0.003 / 0.062 | 0.31 / 0.034 / 0.46 | - | E at the null everywhere; H partly natural above 300 s |
| E01 | before scorecard (plain RR, aurora) | B01/B04/B10 | 0.047 / 0.003 / 0.062 | 0.31 / 0.034 / 0.46 | 0.00 / 0.00 / 0.05 | noise above 4 s |
| E02 | projection onto Ebro | all | vacuous (1 by construction) | vacuous | = E01 | identical to RR (1e-12); Ebro predicts 0 % of the local E |
| E03 | quiet time, E-quiet 10 % | B01 | 0.047 -> 0.554 (0.147) | 0.295 -> 0.701 (0.585) | 0.00 -> 0.00 | H natural, E not; TF noise |
| E03 | same | B04 | 0.003 -> 0.643 (0.119) | 0.017 -> 0.794 (0.541) | 0.00 -> 0.00 | same |
| E03 | same | B10 | 0.062 -> 0.594 (0.071) | 0.461 -> 0.828 (0.245) | 0.12 -> 0.00 | same |
| E04 | polarisation (E across source axis) | B01/B04/B10 | E_perp 0.003 / 0.002 / 0.002 (null alike) | E_perp 0.020 / 0.012 / 0.018 | mode strict 0 -> 0 | negative |
| E05 | inverse-noise weighting | B01 | 0.047 -> 0.233 (0.010) | 0.295 -> 0.768 (0.139) | 0.00 -> 0.19 | best H cleaner; E null; TF scattered |
| E05 | same | B04 | 0.003 -> 0.111 (0.003) | 0.017 -> 0.341 (0.042) | 0.00 -> 0.06 | same |
| E05 | same | B10 | 0.062 -> 0.290 (0.034) | 0.461 -> 0.805 (0.049) | 0.12 -> 0.06 | same |
| E06 | array, H-gradient refs | B01 | 0.041 -> 0.290 (0.003) | 0.339 -> 0.795 (0.029) | 0.00 -> 0.00 | H cleaned; E only where the leak predicts |
| E06 | same | B04 | 0.003 -> 0.043 (0.002) | 0.032 -> 0.457 (0.021) | 0.00 -> 0.00 | same |
| E06 | same | B10 | 0.071 -> 0.185 (0.002) | 0.509 -> 0.633 (0.024) | 0.06 -> 0.00 | same |
| E07 | weighting + array | B01 | 0.041 -> 0.333 (0.017) | 0.339 -> 0.828 (0.074) | 0.00 -> 0.00 | cohE 0.16 (0.05) at 300-1000 s, with the source's phase |
| E07 | same | B04 | 0.003 -> 0.407 (0.015) | 0.032 -> 0.594 (0.046) | 0.00 -> 0.00 | negative |
| E07 | same | B10 | 0.071 -> 0.442 (0.048) | 0.509 -> 0.741 (0.119) | 0.06 -> 0.12 | cohE up to 0.54 (0.07) above 1000 s; phase drops to 0 (leak) |
| E08 | weighting + polarisation | B01/B04/B10 | E_perp 0.009 / 0.005 / 0.005 (0.016 / 0.014 / 0.002) | E_perp 0.024 / 0.014 / 0.026 | mode strict 0 -> 0 | negative; B28 control fails (0.88 -> 0.69) |
| E09 | burst gating, 1 Hz (K3 M60) | B01 | 0.011 -> 0.136 (0.002), 30-128 s | - | 0.00 -> 0.00 (10-128 s) | H cleaned; E at null |
| E09 | same | B04 | 0.001 -> 0.009 (0.004) | - | 0.00 -> 0.00 | negative |
| E09 | same | B10 | 0.021 -> 0.097 (0.002) | - | 0.00 -> 0.56 | E at null; K3 M180 0.33, K10 M60 0.00: not stable |
| E10 | 1000 Hz, night vs day, burst gate, rr B14 | B04 | cohE with B14, 0.7-10 s: 0.034 (day) -> 0.324 (night gated; null 0.004) | - | 0.7-10 s: 0.33 (masks2) -> 0.56 | = hand masks to 1.15 s, source above |
| E10/E10b | same | B10 | cohE 0.7-10 s: 0.552 (all), 0.141 (gated) | - | 0.7-10 s: 0.17 (default) -> 0.44 | 1.2-2 s gain not repeatable over 3 nights |
| E11 | horizontal magnetic TF to B14 (Ebro-RR, weighted) | B10 | - | - | - (Mxx 0.90, phase -0.4 deg, rel. err 0.14; Myy 1.00, 0.26) | H recoverable at 40-3000 s; not an impedance |

Controls: B28 at 1 Hz, and B18 at 1000 Hz, same window.
- **Pass.** Clock rule (E03), weighting (E05), E_perp (E04), burst gate K3 (E09), and the 1000 Hz gate at 0.1-0.9 s.
- **Fail.** E08.
- **Not judged.** E-quiet rules: B28's quiet windows are scattered, not whole nights.

## What worked (partially)

- **Cleaning the local H.** Inverse-noise weighting over the whole record (E05) and burst gating (E09) do it, with B28 unchanged. That gives the natural H at long periods, and the B10 magnetic transfer function (E11).
- **An automatic, local-only stand-in for the hand cross-power masks at 1000 Hz.** The burst detector on the local E at 1 Hz, run on a quiet night, reproduces B04's yx to 1.15 s (E10). It cannot extend it.

## What did not work

- **Any impedance at 10-1000 s at B01, B04 and B10,** by every method and combination above.
- **The yx above about 1.15 s at 1000 Hz.** The cause is the source at B04, and the July dead band at B10 and even at B18.

## The method worth pursuing, if any

**Night-time burst gating at 1000 Hz** (E10), as a replacement for hand masks at 0.2-1.1 s. It needs no cross-power clustering, uses only the local E, and did as well as the 6517 hand masks on B04's one clean-remote night. It will not carry any site past about 1 s. Nothing tried at 1 Hz is worth pursuing for impedances.

## Not tried, and why

- **ICA.** A linear unmixing that removes the source from E is a linear predictor of it, so it is bounded by E06/E07's 1 - gamma^2. That bound is one to three orders above the natural share of E.
- **Wavelet (CWT) masking.** pywt is not installed; scipy.signal.cwt is gone in scipy 1.17; nothing was installed. The STFT gating and weighting of E03, E05, E09 and E10 carry the same information on another tiling.
- **Template or Kalman step subtraction.** The source is chopper pulse trains of variable length plus a continuous lower level between bursts (E00b). The continuous part is what keeps E at the null after gating (E09). A template would have to be accurate to 40-60 dB.
- **Ebro hz as a third reference.** It improves only the prediction of H, which is not the limit.
- **Robust reweighting against Ebro.** Aurora is that, and its product is noise. Residual-based weights favour the source cluster wherever the source dominates.
- **More sites (B02, B03, B05-B09, R01 as locals).** The rule was to add sites only when a method worked; none did.
- **B01 at 1000 Hz with a clean remote.** No clean site overlaps February. The R01-referenced row (E10) is weak evidence.
- **More B04 nights at 1000 Hz.** B04 and B14 overlap on one night only (22/23 Jul).
- **A B28 control at 1000 Hz.** B28 and B29 were being re-ingested; B18 rr B14 served instead.

## Open questions

1. **The continuous inter-burst E source.** It is present at night and between trains. At B01 on 15/16 Feb it held a steady level for hours, in the bursts' polarisation. Traction substations, the OCP installations and pipeline cathodic protection are candidates. Identifying it matters more than any further processing.
2. **B04 xy at 1.5-10 s.** It looks physical in every 1000 Hz estimate, day and night: rho about 2.5e3 flat, phase 35-42 deg. Is it natural? Check it against B05/B06.
3. **Field options.** The data say the wall is the local E's signal-to-noise, so a better remote cannot help. Only data taken while the traction supply is off, or sites several km or more from the corridor, would change it. How far from the corridor is unknown; a line of E dipoles away from the track would measure the decay.

## Housekeeping (for Ben)

- **1 Hz derived archives made in this session** with `scripts/decimate_site.py`, each with its survey.yaml entry: B02L, B03L, B05L, B06L, B07L, B08L, B09L, B10L, B11L, B14L and R01L (`mth5/<site>L.h5`).
  - **Stale dipoles.** B02L, B07L, B10L and B14L predate the 16:16 dipole re-ingest, as do B01L and B28L from earlier, and carry the old dipole lengths. Rebuild them with `--force` before any rho product.
  - **B13L failed.** It collided with the re-ingest's own build of `B13_f81e4c0e6.h5.part` and wrote nothing.
  - **B15L I stopped.** The re-ingest has since replaced its partial `.part`.
  - **A variant my run built.** `decimate_site.py B11` built the current `B11_f81e4c0e6.h5` (10.9 GB) because filters.yaml changed at 16:14.
- **Aurora product made.** `tf/B10L_rr-EBR_20260925-1618_nr-E01.*`.
- **No repository file was edited** (src, scripts, tests, masks.yaml and filters.yaml untouched). **No archive was opened for writing.**
