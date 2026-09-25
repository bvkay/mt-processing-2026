# North recovery: running log

Question: what, if anything, can be recovered of the natural MT signal at periods above ~0.7 s at the northern line B sites (R01-B10), which a coherent near-field source dominates?

Started 2026-09-25 16:05 (local, UTC+8). Workspace `D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace\qc\north_recovery\`. Code: the worktree `D:\BEN\BBMT_Processing_2026\.claude\worktrees\agent-ae84cc9fb8c936a00` (PYTHONPATH `<worktree>\src`), Python `C:\Users\joint\anaconda3\envs\bbmt-2026\python.exe`. Every experiment script sits in its folder and imports `nr_common.py` from this folder. Run each as `python <folder>\<script>.py` from this folder. No repository file was edited. Archives were opened read-only. The only writes outside this folder are the derived 1 Hz archives made with `scripts/decimate_site.py` (they also add `<site>L` entries to survey.yaml, as that script does) and the aurora products in `tf/` tagged `nr-E<nn>`.

## Conventions (fixed before any experiment)

- **Bands and estimator (`nr_common.py`).** 1 Hz data, calibrated by dividing the FFT of the whole series by the MTH5 filter-chain response and high-passing below 1/20000 Hz. Three STFT levels: 1, 1/8 and 1/64 Hz, with FIR zero-phase decimation. Hann windows of 256 samples at half overlap. 8 bands per decade from 4 to 4096 s. Each band sits on the first level where its lowest harmonic index is at least 6 (4 on the last level). The impedance is the plain (unweighted) remote reference Z = <E R^H><H R^H>^-1 summed over the kept windows and harmonics. Its error is a delete-one-group jackknife over 20 contiguous groups.
- **Scorecard 1: coherence with Ebro.** The multiple coherence of a local channel y with Ebro (hx, hy) is gamma^2 = S_yR S_RR^-1 S_Ry / S_yy, from spectra summed over the kept windows and harmonics. "cohH" is the mean of hx and hy. It is averaged over the bands whose centres fall in 30-300, 300-1000 and 1000-3000 s. **The null** is the same quantity against Ebro shifted by 7 days: +7 d for February and March, -7 d for July, so the shift stays inside Ebro's record. It is the floor that includes any selection bias. A coherence counts only as far as it clears the null. "cohE" is the same for ex and ey.
- **Scorecard 2: the transfer function.** The fraction of bands whose yx phase (+180) lies in (0, 90) deg and within 15 deg of every neighbouring band. On a 1 Hz product this runs over 4-1000 s; on a 1000 Hz product over 0.1-1000 s, 0.1-4 s and 0.7-10 s. **Strict** means the same test with the quadrant narrowed to (10, 80) deg. It was added because the loose test counts the source's own smooth phase of +2-6 deg as physical: B01 rr R01 scores 0.33 loose and 0.00 strict (E01). "q" is the `mtproc.quality.tf_quality` overall score of the same impedance, computed through an mt_metadata TF object.
- **Scorecard 3: the B28 control.** The same method applied to B28L. It passes when B28's estimate stays within the combined 2 sigma of the 1000 Hz product B28 rr B29 in the bands where the unmodified baseline already does.

## V00: tool check (the estimator before any experiment)

- **Question.** Does `nr_common` reproduce aurora on a clean site?
- **Failure criterion.** It fails if B28L rr EBR differs from aurora's `tf/B28L_rr-EBR_20260925-1544_obs-EBR.edi` by more than 0.05 dex in rho or 3 deg in phase (median over 10-1000 s).
- **Script.** `V00_tool_check/v00_tool_check.py`
- **Result.** Median |dlog10 rho| is 0.013 (xy) and 0.013 (yx). Median |dphase| is 1.2 deg (xy) and 1.0 deg (yx), over 14 bands. **Pass.**
- **Limitation.** At 4-15 s the plain estimate at B28 is noise (yx 4-1000 s fraction 0.68, against 0.92 for aurora). Aurora's robust weighting copes there; the plain sum does not. B28's ex is noisy at 4-10 s (E00), and Ebro's natural coherence is low at those periods. From 20 to 3000 s the two agree band for band (figure `V00_tool_check/v00_B28L_nrcommon_vs_aurora.png`). The scorecard therefore also carries a 20-1000 s fraction ("20-1000"), on which B28 scores 1.00.

## E00: characterisation of the source (1 Hz, whole records)

- **Question.** What are the source's spectrum, polarisation, own impedance, timing and spatial coherence, and how much of each local channel does Ebro see?
- **Data.** B01L (Feb, 91.7 h), B04L (Jul, 93.2 h), B10L (Jul, 121.7 h), B28L (Mar, 45 h, control), each against EBR hx and hy at 1 Hz. The null is Ebro shifted by +/-7 d. The array pairs are B01-B02, B01-R01, B04-B03, B04-B14, B10-B09 and B10-B14 (1 Hz derived archives made today: B02L, R01L, B03L, B09L, B10L, B14L, and later B05L-B08L, B11L, B13L, B15L; log `decimation.log`).
- **Script.** `E00_characterise/e00_characterise.py`
- **Figures.** `e00_fig1_spectra_coherence_polarisation.png`, `e00_fig2_time_behaviour.png`, `e00_fig3_array_coherence.png`
- **Failure criteria.** The brief's picture is contradicted if B01 hx/hy coherence with Ebro exceeds the null by more than 0.05 at 30-300 s, or if B28's coherence falls below 0.5 at 300-1000 s. Neither happened: B01 is 0.047 against a null of 0.002, and B28 is 0.92.

**Multiple coherence with Ebro, per channel.** Values are for 30-300 / 300-1000 / 1000-3000 s; the null is in brackets.

| site | ex | ey | hx | hy |
|---|---|---|---|---|
| B01 | 0.002/0.023/0.033 (0.003/0.037/0.031) | 0.003/0.017/0.039 (0.002/0.017/0.021) | 0.014/0.197/0.633 (0.002/0.019/0.020) | 0.079/0.422/0.753 (0.002/0.025/0.038) |
| B04 | 0.003/0.013/0.031 (0.002/0.018/0.019) | 0.003/0.009/0.036 (0.002/0.016/0.016) | 0.003/0.028/0.080 (0.003/0.016/0.061) | 0.002/0.040/0.250 (0.001/0.008/0.036) |
| B10 | 0.001/0.010/0.049 (0.001/0.004/0.016) | 0.002/0.011/0.054 (0.001/0.005/0.024) | 0.113/0.703/0.905 (0.001/0.015/0.033) | 0.010/0.211/0.374 (0.001/0.003/0.010) |
| B28 | 0.509/0.922/0.939 | 0.503/0.917/0.949 | 0.515/0.918/0.954 | 0.522/0.915/0.900 |

**Local H amplitude over Ebro's (whole-record ASD ratio).**

| site | 4-10 s | 10-100 s | 100-1000 s | 1000-4096 s |
|---|---|---|---|---|
| B01 | 14.6 | 10.4 | 3.0 | 1.5 |
| B04 | 35.6 | 25.0 | 14.7 | 4.9 |
| B10 | 8.9 | 6.1 | 2.5 | 1.3 |
| B28 | 1.1 | 0.56 | 0.87 | 1.2 |

**Paragraph.**

1. **Both fields carry the source; E is fully dominated.** At B01, B04 and B10 the electric channels have no coherence with Ebro above the null anywhere from 4 to 4096 s. The one hint is B10 at 1000-3000 s: 0.05 against a null of 0.02. The magnetic channels become partly natural as the period grows: B01 hy reaches 0.42 at 300-1000 s and 0.75 above 1000 s, and B10 hx 0.70 and 0.90. The natural H at line B is about 0.56 of Ebro's amplitude at 10-100 s (B28). On that scale the source's share of the local H power is roughly 99 % at 10-100 s at B01 and 99.8 % at B04. The obstacle for an impedance is E, not H.
2. **Polarisation and the source's own impedance.** The source E is linearly polarised and fixed in direction. At B01 it points at -81 to -85 deg (E-W, ey), with a polarised fraction of 0.96-0.99 and ellipticity under 2.5 deg in every band. At B10 it points at -12 to -16 deg (N-S, ex), fraction 0.96-0.98. At B04 it points at 60-77 deg, fraction 0.56-0.87. The source H is less regular. At B01 the major axis lies at 20-25 deg below 100 s, the polarised fraction is 0.56-0.8, and the per-window azimuth spreads by 23-77 deg. At B10 the axis lies at 70-78 deg (hy). At B04 the H is barely polarised (0.08-0.5 below 500 s). The source pair is therefore Ey/Hx at B01 (rho_yx single-station 5e4 ohm m at 4 s, rising as T to 7e6 at 1000 s, phase about 0) but Ex/Hy at B10 (rho_xy 6e3 to 1.5e6, phase about 0). At B10 it is the xy mode that the source takes over: the 1000 Hz B10 rr B14 keeps a physical yx phase of 35-42 deg to 1.2 s (E01 figure).
3. **Timing.** Local over Ebro H power at 10-40 s follows a clear daily cycle (fig2). Medians by local hour (UTC+1):
   - B01: 20-70 from 10 to 19 h, falling to 0.8 at 04 h.
   - B04: 50-100 by day, 0.5 at 04 h.
   - B10: 10-30 by day, 0.9 at 04 h.

   The quietest 5 % of windows reach 0.22 (B01), 0.23 (B04) and 0.42 (B10), against B28's natural median of 0.13. On some nights the E power falls by three to four decades:
   - B01: the nights of 15/16, 16/17 and 17/18 Feb.
   - B04: 19/20 and 22/23 Jul.
   - B10: 22/23 and 23/24 Jul.

   The source is a daytime-dominated, schedule-like source with quiet stretches around 01-05 h local, consistent with rail traffic. The earlier hour masks by step statistics did not pick these nights out.
4. **Spatial coherence.** The source E is coherent over 6 km but not enough to cancel. B01-B02 ey has coherence 0.76-0.85 and ex 0.22-0.67. B10-B09 ex has 0.74-0.91. B04-B03 E has 0.1-0.7, and its hx is 0.01. B01-R01 is incoherent except for the natural field at long periods. A coherence of 0.85 leaves 15 % of the power, while the natural E is well under 1 % of it.

- **Verdict.** The source dominates the local E by far more than the local H, at every period to 4096 s, and it is strongly diurnal.
- **Next.** Plain RR against Ebro should fail on E's signal-to-noise alone (E01). Projection onto Ebro cannot help E (E02). The one lever the data offer is time: the quiet nights (E03).

## E01: the "before" scorecard

- **Question.** What do the existing products and the plain estimator score before any method?
- **Script.** `E01_baseline/e01_baseline.py`. It writes the per-band arrays to `e01_<site>_plainrr.npz` and the figures to `e01_<site>_baseline.png`. The aurora B10L rr EBR was made for this: `python scripts\process_rr.py <survey> B10L EBR --tag nr-E01`, giving `tf/B10L_rr-EBR_20260925-1618_nr-E01.edi`. Aurora's own quadrant check flags that product's median phases as out of quadrant (xy -47, yx -167 deg): noise.

**nr_common plain RR against Ebro, whole record, 1 Hz.** cohH is the mean of hx and hy; yx fractions are over 4-1000 s.

| site | cohH 30-300 | cohH 300-1000 | cohH 1000-3000 | null (same) | cohE 300-1000 | yx phys | yx strict | xy phys | q | yx 20-1000 |
|---|---|---|---|---|---|---|---|---|---|---|
| B01 | 0.047 | 0.310 | 0.693 | 0.002/0.022/0.029 | 0.020 | 0.00 | 0.00 | 0.00 | 0.033 | 0.00 |
| B04 | 0.003 | 0.034 | 0.165 | 0.002/0.012/0.049 | 0.011 | 0.00 | 0.00 | 0.00 | 0.029 | 0.00 |
| B10 | 0.062 | 0.457 | 0.640 | 0.001/0.009/0.021 | 0.011 | 0.05 | 0.05 | 0.11 | 0.106 | 0.08 |
| B28 | 0.518 | 0.917 | 0.927 | 0.006/0.024/0.067 | 0.920 | 0.68 | 0.68 | 0.74 | 0.562 | 1.00 |

**Aurora products.**

| product | range | yx phys | yx strict | q |
|---|---|---|---|---|
| B01L rr EBR (1 Hz) | 4-1000 | 0.00 | 0.00 | 0.021 |
| B04L rr EBR, no masks (1 Hz) | 4-1000 | 0.04 | 0.04 | 0.029 |
| B04L rr EBR, Ben's masks2 (1 Hz) | 4-1000 | 0.04 | 0.00 | 0.027 |
| B10L rr EBR (1 Hz, nr-E01) | 4-1000 | 0.08 | 0.04 | 0.028 |
| B28L rr EBR (1 Hz) | 4-1000 | 0.92 | 0.92 | 0.958 |
| B01 rr R01 (1000 Hz) | 0.1-1000 / 0.1-4 / 0.7-10 | 0.33 / 0.50 / 0.75 | 0.00 / 0.00 / 0.00 | 0.337 |
| B01 rr B02 (1000 Hz) | same | 0.42 / 0.88 / 0.67 | 0.00 / 0.00 / 0.00 | 0.201 |
| B04 rr B14 (1000 Hz) | same | 0.30 / 0.75 / 0.33 | 0.30 / 0.75 / 0.33 | 0.045 |
| B04 rr B14, masks2 (1000 Hz) | same | 0.30 / 0.81 / 0.33 | 0.30 / 0.75 / 0.33 | 0.041 |
| B10 rr B13 (1000 Hz) | same | 0.28 / 0.69 / 0.33 | 0.25 / 0.62 / 0.17 | 0.141 |
| B10 rr B14 (1000 Hz) | same | 0.25 / 0.62 / 0.17 | 0.25 / 0.62 / 0.17 | 0.175 |
| B28 rr B29 (1000 Hz) | same | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.969 |

- **Verdict.** The baseline is noise at every northern site above 4 s at 1 Hz. The 1000 Hz products' loose fractions at B01 (0.33-0.88) are the source's smooth near-zero phase, which the strict test removes (0.00).
- **Next.** Every later experiment is scored against these rows with the same estimator.

## E02: projection onto Ebro (natural-field estimate)

- **Question.** Does regressing the local channels on Ebro and keeping the predicted part give anything RR does not?
- **Method.** Per band: T_H = S_HR S_RR^-1 and T_E = S_ER S_RR^-1; then H^ = T_H R and E^ = T_E R, and Z from (E^, H^). The identity Z_proj = T_E T_H^-1 = S_ER S_HR^-1 = Z_RR holds algebraically, so the check is numeric. Out of sample: T is fitted on odd UTC days and applied to even days, and back. Reported is the explained variance EV = 1 - sum|y - y^|^2 / sum|y|^2.
- **Data.** The four sites, whole records, 1 Hz.
- **Script.** `E02_projection/e02_projection.py`. Figure `e02_explained_variance.png`.
- **Failure criterion (identity check).** A relative difference above 1e-6 fails it.

**Result.** max |Z_proj - Z_RR| / |Z_RR| = 1.7e-12 (B01), 5e-14 (B04, B10) and 1e-14 (B28): the identity holds. Scorecard 1 on H^ is 1 by construction and is not a result; EV replaces it.

**Out-of-sample EV from Ebro.** Values are for 30-300 / 300-1000 / 1000-3000 s. The shifted-Ebro null is -0.01 to -0.24 everywhere.

| site | ex | ey | hx | hy |
|---|---|---|---|---|
| B01 | -0.01/-0.03/-0.11 | -0.01/-0.03/-0.07 | 0.00/0.17/0.58 | 0.07/0.38/0.71 |
| B04 | 0.00/-0.05/-0.06 | 0.00/-0.04/-0.02 | 0.00/0.01/0.03 | 0.00/0.02/0.14 |
| B10 | 0.00/-0.03/-0.10 | 0.00/-0.03/-0.08 | 0.11/0.69/0.89 | 0.01/0.18/0.27 |
| B28 | 0.41/0.85/0.86 | 0.33/0.73/0.81 | 0.31/0.74/0.85 | 0.42/0.86/0.85 |

The odd-day and even-day RR estimates differ in yx phase by a median of 69 deg (B01), 66 deg (B04), 98 deg (B10) and 1.0 deg (B28) at 20-1000 s.

- **Verdict.** Projection onto Ebro is remote reference under another name. It predicts a natural H at long periods (B01 hy 71 %, B10 hx 89 % of the variance above 1000 s) but none of the E at any period, so it cannot give an impedance.
- **Next.** The E must be cleaned first. Time selection of the quiet nights is the only lever that acts on E (E03).

## Housekeeping note (16:30)

- **What collided.** While my second decimation batch was running (`run_decimations.sh B05 B06 B07 B08 B11 B13 B15`), filters.yaml gained new declarations (hash f81e4c0e6: B07, B10, B11, B13, B15; file written 16:14). A re-ingest of B01, B02, B07, B10, B13, B14, B15, B19-B21, B24-B29 also started (`scripts\ingest_site.py ... --force`, pids 42712, 24432 and 38168, not mine). As a result:
  - **B11.** `decimate_site.py B11` built the new variant `mth5/B11_f81e4c0e6.h5` (10.9 GB, 16:15-16:29) through `processing_archive`, which is the script's documented behaviour. B11 is not in the re-ingest list, so the variant matches the current raw archive and filters.
  - **B13.** `decimate_site.py B13` collided with the other process building `B13_f81e4c0e6.h5.part`. It failed at the unlink, with a PermissionError because the file was open, so it wrote nothing into that file.
  - **B15.** I stopped `decimate_site.py B15` (pid 35552) at 16:30 because it was building a B15 variant from a raw archive queued for re-ingest. It leaves `mth5/B15_f81e4c0e6.h5.part` (173 MB, partial). `build_variant` unlinks an existing .part before writing, so the next build replaces it. I did not delete it, to avoid racing the running re-ingest.
- **Consequences.** No more decimations. The 1 Hz derived archives B02L, B07L, B10L and B14L (and B01L and B28L from earlier today) were cut from the raw archives before the dipole re-ingest. They carry the old dipole lengths: B01, B02, B10 and B14 50 m instead of 53-54.9 m, and B28 ey 53.5 m instead of 33.5 m. That scales E and rho but not coherence or phase, which are all the scorecard reads. They should be rebuilt with `--force` before any product is taken from them. The 1000 Hz work (it became E10) waits for the re-ingest of its sites.

## E03: quiet-time selection

- **Question.** Does keeping only the times when the source is quiet expose the natural E and H, and give a physical TF?
- **Method.** A time mask that never looks at Ebro, so the estimate stays unbiased. Rules, one at a time:
  - **clock.** Windows lying wholly within 00-04 UTC (01-05 h local).
  - **Equiet p.** The quietness of each 256 s window is the local E power (ex^2 + ey^2) at 4-10 s. Windows at or below its p-quantile are kept, for p = 0.20, 0.10 and 0.05. A deeper window is kept when at least 90 % of the 256 s windows inside it are quiet. The 4-10 s bands that define the rule are not scored (scoring starts at 10 s).
- **Layout.** Windows of 256, 256 and 64 samples (the deepest is 4096 s, short enough to fit a night); bands 4-2048 s. The "all" row uses the same layout.
- **Data.** B01L, B04L, B10L and B28L, whole records, against EBR; null is EBR +/-7 d on the same kept windows.
- **Script.** `E03_quiet_time/e03_quiet_time.py`. Figures `e03_<site>.png`: TF, coherence and the kept windows on the quietness trace.
- **Failure criterion.** The method recovers nothing unless cohH or cohE clears both the all-window value and the null by more than the null's own size, AND the yx strict fraction over 10-1000 s rises by at least 0.2.

**Results.** Coherence cells give the value with the null in brackets. Fractions are over 10-1000 s. The control is the share of B28's 20-1000 s bands within the combined 2 sigma of B28 rr B29 (1000 Hz).

| site | rule | hours | cohH 30-300 | cohH 300-1000 | cohE 30-300 | cohE 300-1000 | yx phys | yx strict | xy strict | q | control |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B01 | all | 91.5 | 0.047 (0.002) | 0.295 (0.015) | 0.003 (0.003) | 0.015 (0.019) | 0.00 | 0.00 | 0.00 | 0.025 | |
| B01 | clock | 15.9 | 0.051 (0.028) | 0.510 (0.122) | 0.020 (0.031) | 0.097 (0.201) | 0.06 | 0.00 | 0.00 | 0.019 | |
| B01 | Equiet0.20 | 18.3 | 0.480 (0.085) | 0.665 (0.775) | 0.090 (0.081) | 0.204 (0.290) | 0.00 | 0.00 | 0.00 | 0.048 | |
| B01 | Equiet0.10 | 9.2 | 0.554 (0.147) | 0.701 (0.585) | 0.191 (0.209) | 0.257 (0.540) | 0.00 | 0.00 | 0.00 | 0.101 | |
| B01 | Equiet0.05 | 4.6 | 0.164 (0.008) | - | 0.009 (0.015) | - | 0.00 | 0.00 | 0.00 | 0.003 | |
| B04 | all | 93.0 | 0.003 (0.002) | 0.017 (0.003) | 0.003 (0.002) | 0.005 (0.011) | 0.00 | 0.00 | 0.00 | 0.022 | |
| B04 | clock | 15.9 | 0.127 (0.011) | 0.576 (0.182) | 0.005 (0.012) | 0.064 (0.062) | 0.00 | 0.00 | 0.00 | 0.003 | |
| B04 | Equiet0.20 | 18.6 | 0.545 (0.076) | 0.873 (0.481) | 0.147 (0.048) | 0.546 (0.353) | 0.06 | 0.06 | 0.00 | 0.054 | |
| B04 | Equiet0.10 | 9.3 | 0.643 (0.119) | 0.794 (0.541) | 0.161 (0.132) | 0.462 (0.183) | 0.00 | 0.00 | 0.00 | 0.064 | |
| B04 | Equiet0.05 | 4.7 | 0.629 (0.132) | 0.783 (0.528) | 0.169 (0.167) | 0.587 (0.264) | 0.00 | 0.00 | 0.00 | 0.062 | |
| B10 | all | 121.5 | 0.062 (0.001) | 0.461 (0.007) | 0.002 (0.001) | 0.010 (0.006) | 0.12 | 0.12 | 0.00 | 0.071 | |
| B10 | clock | 19.9 | 0.158 (0.011) | 0.711 (0.049) | 0.009 (0.010) | 0.058 (0.062) | 0.06 | 0.00 | 0.00 | 0.089 | |
| B10 | Equiet0.20 | 24.3 | 0.586 (0.071) | 0.828 (0.245) | 0.187 (0.077) | 0.311 (0.283) | 0.00 | 0.00 | 0.00 | 0.136 | |
| B10 | Equiet0.10 | 12.2 | 0.594 (0.071) | 0.828 (0.245) | 0.189 (0.077) | 0.311 (0.283) | 0.00 | 0.00 | 0.00 | 0.102 | |
| B10 | Equiet0.05 | 6.1 | 0.167 (0.011) | - | 0.028 (0.022) | - | 0.00 | 0.00 | 0.00 | 0.010 | |
| B28 | all | 44.9 | 0.518 (0.006) | 0.895 (0.023) | 0.506 (0.006) | 0.895 (0.019) | 0.81 | 0.81 | 0.88 | 0.829 | 0.77 of 13 |
| B28 | clock | 8.0 | 0.465 (0.024) | 0.930 (0.252) | 0.496 (0.025) | 0.950 (0.228) | 0.69 | 0.69 | 0.56 | 0.785 | 0.92 of 13 |
| B28 | Equiet0.20 | 9.0 | 0.261 (0.019) | - | 0.263 (0.018) | - | 0.12 | 0.12 | 0.12 | 0.393 | 1.00 of 2 |
| B28 | Equiet0.10 | 4.5 | 0.234 (0.024) | - | 0.201 (0.022) | - | 0.06 | 0.06 | 0.06 | 0.345 | 1.00 of 2 |

("-": no window of that length passed the rule.)

**Reading.**

- **H becomes natural.** In the quiet windows the local H does: at 30-300 s cohH is 0.48-0.64, against nulls of 0.07-0.15 and all-window values of 0.003-0.06.
- **E stays source.** The E does not follow. B01's cohE is at its null in every rule. B04 and B10 show cohE of 0.15-0.19 at 30-300 s in the Equiet0.20 windows, against nulls of 0.05-0.08, but it does not clear the null by its own size at 300-1000 s (few deep windows: the nulls there are 0.2-0.8, a small-sample floor).
- **The TF stays noise.** Strict yx fractions are 0.00-0.06.
- **Control.** The clock rule passes (0.92 of 13 bands, against 0.77 with all windows). The E-quiet rules cannot be judged at B28: its quiet windows are scattered, not contiguous nights, and only 2 bands of 20-1000 s remain. At a clean site the E-quiet windows are the magnetically quiet ones, and its coherence drops to 0.23-0.26.
- **The quiet nights are not clean.** At B01 the night of 15/16 Feb carries a steady E of about 1e6 (a night-time source). At B01 the quietest E reaches about 1e4 per 256 s window at 4-10 s, three to four decades under the daytime level, but that is still far above the natural E expected there (E06).

- **Verdict.** Quiet-time selection makes the local H natural but leaves E source-dominated; no physical TF at 10-1000 s at any of the three sites.
- **Next.** Hard selection throws away most of the information. Weighting every window by its source level is the continuous form (E05). The fixed polarisation of the source E is a separate lever (E04).

## E04: polarisation filtering of E (and H)

- **Question.** The source E is linearly polarised in a fixed direction. Is the perpendicular component natural?
- **Method.** Per band, over the whole record, theta_E is the Stokes major-axis azimuth of the local E spectral matrix and theta_H that of H. E_perp and E_par are the components across and along theta_E, and likewise for H. The adaptive variant E_perp_w uses a per-window theta_E. The TF is the clean row z_perp = S_{Eperp R} S_{HR}^-1 against Ebro. Only the mode whose E lies across the source can come out: xy at B01 (theta_E -82 deg) and B04 (66 deg), yx at B10 (-14 deg).
- **Script.** `E04_polarisation/e04_polarisation.py`. Figure `e04_polarisation.png`.
- **Failure criterion.** E_perp's coherence must clear its null by more than the null's own size, and the recovered mode's strict fraction over 10-1000 s must rise by at least 0.2.

**Multiple coherence with Ebro.** Values are for 30-300 / 300-1000 / 1000-3000 s; the null is in brackets.

| site | E_perp | E_par | E_perp_w | H_perp | H_par | mode | strict 10-1000, before -> after |
|---|---|---|---|---|---|---|---|
| B01 | 0.003/0.020/0.033 (0.002/0.029/0.028) | 0.003/0.017/0.039 (0.002/0.018/0.021) | 0.002/0.019/0.029 (0.002/0.019/0.028) | 0.113/0.440/0.474 (0.002/0.031/0.032) | 0.011/0.201/0.709 | xy | 0.00 -> 0.00 |
| B04 | 0.002/0.012/0.040 (0.002/0.017/0.030) | 0.003/0.009/0.035 | 0.002/0.016/0.047 (0.001/0.015/0.037) | 0.003/0.040/0.223 (0.003/0.008/0.036) | 0.003/0.027/0.083 | xy | 0.00 -> 0.00 |
| B10 | 0.002/0.018/0.037 (0.001/0.010/0.018) | 0.001/0.010/0.050 | 0.002/0.017/0.023 (0.001/0.011/0.025) | 0.163/0.473/0.240 (0.002/0.010/0.014) | 0.007/0.405/0.920 | yx | 0.06 -> 0.00 |
| B28 | 0.397/0.778/0.769 | 0.508/0.922/0.950 | 0.210/0.642/0.686 | 0.427/0.846/0.840 | 0.574/0.932/0.958 | xy | 0.88 -> 0.88 |

- **Verdict.** Negative. The component across the source's E direction is as source-dominated as the one along it: coherence at the null at all three sites and in the adaptive variant too. The source E is not rank one to the precision needed. Its minor axis carries about 1 % of the power, still orders above the natural E. Projecting H across its source axis helps H (B01 30-300 s: 0.113 against 0.047 for hx/hy), not E.
- **Control.** B28 passes, unchanged at 0.88. The adaptive projection costs B28 half its E coherence, as expected: it removes natural E too.
- **Next.** Weighting (E05).

## E05: inverse-noise weighting of the windows

- **Question.** Is weighting every window by 1/(its source level) better than hard selection?
- **Method.** Weighted least squares on the RR sums: Z = (sum w E R^H)(sum w H R^H)^-1, with w = 1/sigma^2. The noise level sigma^2 is measured two ways, one at a time:
  - **A (w_broadband).** The window's local E power at 4-10 s, averaged over the 256 s windows inside a deeper window; bands from 10 s scored.
  - **B (w_neighbours).** The same window's local E power in the other bands of its level, excluding the band itself and two neighbours each side, so that the band's own natural E does not set its weight.
- **Layout.** As E03.
- **Script.** `E05_noise_weighting/e05_noise_weighting.py`. Figures `e05_<site>.png`.
- **Failure criterion.** As E03.

**Results.** Coherence cells give the value with the null in brackets; fractions are over 10-1000 s.

| site | weights | cohH 30-300 | cohH 300-1000 | cohE 30-300 | cohE 300-1000 | yx phys | yx strict | xy strict | q | control |
|---|---|---|---|---|---|---|---|---|---|---|
| B01 | none | 0.047 (0.002) | 0.295 (0.015) | 0.003 (0.003) | 0.015 (0.019) | 0.00 | 0.00 | 0.00 | 0.025 | |
| B01 | broadband | 0.250 (0.011) | 0.613 (0.062) | 0.007 (0.012) | 0.022 (0.014) | 0.12 | 0.12 | 0.00 | 0.110 | |
| B01 | neighbours | 0.233 (0.010) | 0.768 (0.139) | 0.006 (0.008) | 0.025 (0.033) | 0.19 | 0.19 | 0.00 | 0.132 | |
| B04 | none | 0.003 (0.002) | 0.017 (0.003) | 0.003 (0.002) | 0.005 (0.011) | 0.00 | 0.00 | 0.00 | 0.022 | |
| B04 | broadband | 0.060 (0.004) | 0.100 (0.008) | 0.005 (0.005) | 0.005 (0.004) | 0.00 | 0.00 | 0.00 | 0.098 | |
| B04 | neighbours | 0.111 (0.003) | 0.341 (0.042) | 0.004 (0.008) | 0.023 (0.020) | 0.06 | 0.06 | 0.00 | 0.151 | |
| B10 | none | 0.062 (0.001) | 0.461 (0.007) | 0.002 (0.001) | 0.010 (0.006) | 0.12 | 0.12 | 0.00 | 0.071 | |
| B10 | broadband | 0.209 (0.013) | 0.613 (0.025) | 0.004 (0.003) | 0.017 (0.011) | 0.00 | 0.00 | 0.00 | 0.064 | |
| B10 | neighbours | 0.290 (0.034) | 0.805 (0.049) | 0.009 (0.002) | 0.045 (0.029) | 0.06 | 0.06 | 0.00 | 0.189 | |
| B28 | none | 0.518 (0.006) | 0.895 (0.023) | 0.506 (0.006) | 0.895 (0.019) | 0.81 | 0.81 | 0.88 | 0.829 | 0.77 of 13 |
| B28 | broadband | 0.424 (0.005) | 0.867 (0.019) | 0.415 (0.005) | 0.864 (0.021) | 0.88 | 0.88 | 0.88 | 0.844 | 0.85 of 13 |
| B28 | neighbours | 0.318 (0.007) | 0.714 (0.048) | 0.309 (0.009) | 0.740 (0.053) | 0.88 | 0.88 | 0.88 | 0.859 | 0.92 of 13 |

- **Verdict.** Weighting is the most effective step so far for H: cohH at 30-300 s goes from 0.047 to 0.23-0.25 at B01 and from 0.06 to 0.21-0.29 at B10, nulls 0.01-0.03, over the whole record rather than a few hours. The weighted rho at B01 no longer follows the source's T^1 line (1e3-1e4 ohm m instead of 1e5-1e7). But cohE stays at its null, and the TF stays noise: B01 yx strict 0.19, which is scattered phases, not a curve (figure). The control passes (0.85 and 0.92 of 13).
- **Next.** Measure how far any linear model of the source can go in E (E06).

## E06: array two-source model: upper bound and natural-free references

- **Question.** Can the source in E be predicted from local and neighbour channels well enough to expose the natural E?
- **Method, part (i): upper bound.** 1 - gamma^2(E | refs) is the fraction of local E power left by the best linear prediction. Reference sets:
  - a: local hx, hy
  - b: neighbour 1, 4 channels
  - c: neighbours 1 and 2, 8 channels
  - d: local H plus 8 channels, 10 channels

  This is compared with the natural share of the local E, f_nat = |Z_n|^2 P_Hn / P_E. Here P_Hn is the Ebro-coherent part of the local H scaled by B28's natural coherence, and rho_n is 100 ohm m (bounds 10-1000).
- **Method, part (ii): cleaning.** The natural-free references are c = H_loc - H_nb, 4 channels from two neighbours. Local E and H are regressed on c per band, the prediction is subtracted, and the plain RR against Ebro is taken of the cleaned data.
- **Caveat stated before running.** A natural H gradient in c enters the cleaned E multiplied by the source's E/H (20-50 times the natural impedance). It biases Z, and B28 cannot show it.
- **Arrays (common spans).** B01 + B02 + R01, 70.5 h. B04 + B03 + B06, 92.7 h. B10 + B09 + B08, 90.3 h.
- **Script.** `E06_array_source_model/e06_array_source_model.py`. Figure `e06_array_source_model.png`.

**Part (i): the E power left by the best prediction and the natural share.** Values are for 10-100 / 100-1000 / 1000-4096 s.

| site | channel | a local H | b nb1 | c nb1+nb2 | d local H + nb | natural share, rho 100 | natural share, rho 1000 |
|---|---|---|---|---|---|---|---|
| B01 | ex | 0.096/0.148/0.347 | 0.145/0.179/0.038 | 0.124/0.118/0.016 | 0.078/0.054/0.012 | 2e-4/2e-4/3e-4 | 2e-3/2e-3/3e-3 |
| B01 | ey | 0.0067/0.082/0.37 | 0.043/0.070/0.014 | 0.028/0.016/0.0057 | 0.0012/0.0008/0.0009 | 7e-6/3e-6/6e-6 | 7e-5/3e-5/6e-5 |
| B04 | ex | 0.74/0.85/0.45 | 0.10/0.17/0.018 | 0.042/0.076/0.0046 | 0.042/0.075/0.0045 | 2e-4/4e-5/2e-4 | 2e-3/4e-4/2e-3 |
| B04 | ey | 0.91/0.94/0.83 | 0.26/0.23/0.016 | 0.16/0.12/0.0048 | 0.16/0.12/0.0047 | 8e-5/1e-5/6e-5 | 8e-4/1e-4/6e-4 |
| B10 | ex | 0.016/0.084/0.42 | 0.16/0.14/0.030 | 0.075/0.057/0.0086 | 0.012/0.024/0.0076 | 5e-5/7e-5/1e-4 | 5e-4/7e-4/1e-3 |
| B10 | ey | 0.066/0.23/0.50 | 0.20/0.18/0.10 | 0.18/0.13/0.028 | 0.036/0.018/0.018 | 6e-4/9e-4/2e-3 | 6e-3/9e-3/1.7e-2 |

**Part (ii): scorecard, same common span.** Fractions are over 10-1000 s.

| site | | cohH 30-300 / 300-1000 / 1000-3000 | null | cohE 30-300 / 300-1000 / 1000-3000 | null | yx strict | xy strict | q |
|---|---|---|---|---|---|---|---|---|
| B01 | before | 0.041/0.339/0.710 | 0.004/0.031/0.054 | 0.003/0.033/0.049 | 0.005/0.034/0.057 | 0.00 | 0.00 | 0.040 |
| B01 | after | 0.290/0.795/0.719 | 0.003/0.029/0.073 | 0.006/0.079/0.248 | 0.003/0.020/0.037 | 0.00 | 0.00 | 0.159 |
| B04 | before | 0.003/0.032/0.157 | 0.002/0.015/0.050 | 0.003/0.017/0.046 | 0.002/0.016/0.021 | 0.00 | 0.00 | 0.020 |
| B04 | after | 0.043/0.457/0.770 | 0.002/0.021/0.089 | 0.003/0.015/0.021 | 0.002/0.010/0.023 | 0.00 | 0.00 | 0.008 |
| B10 | before | 0.071/0.509/0.670 | 0.002/0.019/0.045 | 0.002/0.014/0.070 | 0.002/0.015/0.060 | 0.06 | 0.00 | 0.056 |
| B10 | after | 0.185/0.633/0.852 | 0.002/0.024/0.049 | 0.006/0.061/0.351 | 0.001/0.019/0.041 | 0.00 | 0.00 | 0.125 |

**Reading.**

- **The upper bound.** Even the best 10-channel prediction leaves the source 10-300 times above the natural E in B01 ey (8e-4 to 1.2e-3 left, against 3e-6 to 7e-5 natural). It leaves 2-4 orders of magnitude at B04, where the source is not coherent across sites. At B10 it leaves 1-2 orders, except in ey above 1000 s, where 0.018 left meets 0.017 natural for rho 1000. Linear prediction of the source from any combination of these channels cannot expose the natural E over the whole record.
- **The cleaning.** It raises cohH sharply: B01 0.29 at 30-300 s, B04 0.77 above 1000 s. It raises cohE only above 1000 s, at B01 (0.25, null 0.04) and B10 (0.35, null 0.04). That is exactly where the caveat's leak (natural H gradient x source E/H) would put a spurious Ebro-coherent E. The TF does not improve (strict 0.00 at all three).

- **Verdict.** Negative for the TF. The array model cleans H but not E. The upper bound shows the wall: whole-record E would need 30-50 dB more source rejection than any linear model of these channels gives.
- **Next.** The two partial levers, time weighting (E05) and array prediction (E06), are multiplicative in principle. E07 combines them. The leak-bias estimate from a clean pair was dropped because B29 is being re-ingested; it only matters if E07 succeeds.

## E07: weighting (E05 B) plus array cleaning (E06 part ii)

- **Question.** Do time and space multiply?
- **Method.** The E06 arrays and spans, with window weights w = 1/(local E power in the other bands of the level, guard 2):
  1. the weighted upper bound 1 - gamma_w^2(E | 10 references), against the weighted natural share (rho_n 100);
  2. the weighted RR without cleaning;
  3. the weighted RR with the natural-free references c = H_loc - H_nb regressed out (weighted fit).
- **Script.** `E07_weighting_plus_array/e07_weighting_plus_array.py`. Figure `e07_weighting_plus_array.png`.
- **Failure criterion.** As E03.

**Weighted upper bound.** Values are for 10-100 / 100-1000 / 1000-4096 s.

| site | ey left | ey natural share | ex left | ex natural share |
|---|---|---|---|---|
| B01 | 0.028/0.013/0.0013 | 2e-4/6e-5/2e-5 | 0.74/0.45/0.016 | 7e-4/4e-4/5e-4 |
| B04 | 0.21/0.17/0.0054 | 0.034/0.0074/6e-5 | 0.26/0.24/0.0050 | 0.055/0.017/2e-4 |
| B10 | 0.095/0.044/0.023 | 0.077/0.0048/0.0054 | 0.14/0.057/0.014 | 0.017/0.001/5e-4 |

Weighting lifts the natural share of E by one to two orders of magnitude (B04 ey 10-100 s from 8e-5 to 0.034, B10 ey from 6e-4 to 0.077). But it also degrades the array prediction, because the quiet windows hold a larger share of source that is not coherent across sites. The gap closes only at B10 ey 10-100 s (0.095 left against 0.077 natural) and within a factor of 5-6 at B04 10-100 s.

**Scorecard.** Coherence values are for 30-300 / 300-1000 / 1000-3000 s; fractions are over 10-1000 s.

| site | row | cohH | null | cohE | null | yx strict | xy strict | q |
|---|---|---|---|---|---|---|---|---|
| B01 | weighted | 0.188/0.531/0.807 | 0.013/0.086/0.248 | 0.010/0.040/0.122 | 0.009/0.062/0.090 | 0.00 | 0.00 | 0.093 |
| B01 | weighted + cleaned | 0.333/0.828/0.648 | 0.017/0.074/0.119 | 0.024/0.160/0.216 | 0.014/0.049/0.113 | 0.00 | 0.00 | 0.068 |
| B04 | weighted | 0.111/0.084/0.224 | 0.003/0.011/0.073 | 0.004/0.018/0.072 | 0.008/0.014/0.036 | 0.06 | 0.00 | 0.104 |
| B04 | weighted + cleaned | 0.407/0.594/0.799 | 0.015/0.046/0.162 | 0.009/0.021/0.034 | 0.012/0.010/0.028 | 0.00 | 0.00 | 0.035 |
| B10 | weighted | 0.330/0.735/0.828 | 0.043/0.118/0.111 | 0.012/0.030/0.102 | 0.002/0.024/0.059 | 0.25 | 0.00 | 0.155 |
| B10 | weighted + cleaned | 0.442/0.741/0.796 | 0.048/0.119/0.100 | 0.051/0.188/0.544 | 0.012/0.058/0.069 | 0.12 | 0.00 | 0.210 |

**Reading.**

- **E coherence at B10 and B01.** At B10 the combination is the first row where cohE clears its null by more than the null's own size in all three ranges: 0.051 (0.012), 0.188 (0.058), 0.544 (0.069). B01 does so at 300-1000 s: 0.160 (0.049).
- **But the TF does not follow.** yx strict is 0.12 at B10 and 0.00 at B01. The cleaned yx phase at B10 drops towards 0-10 deg above 300 s (figure). Both effects are what the stated leak would produce: a natural H gradient, multiplied by the source's E/H, appears in the cleaned E as an Ebro-coherent signal with the source's near-zero phase. The E coherence gained here cannot be taken as natural E.
- **Instability.** The weighted-only yx at B10 (strict 0.25 on this 90 h span) was 0.06 on the full 121 h record in E05/E08: not stable.

- **Verdict.** Negative for the TF. The only E-coherence gain is where the array's known leak predicts one.
- **Next.** The component across the source axis with weighting (E08), then the source's time structure (E00b, E09).

## E08: weighting (E05 B) plus the E component across the source axis (E04)

- **Question.** With weighting lowering the source share, is E_perp now natural?
- **Method.** Weighted sums per band, theta_E from the weighted E matrix, E_perp, and the clean row z_perp against Ebro (as E04, weighted). The recovered mode is xy at B01 and B04, yx at B10. Layout: 256-sample windows at every level, 4-4096 s.
- **Script.** `E08_weighting_plus_polarisation/e08_weighting_plus_polarisation.py`. Figure `e08_weighting_plus_polarisation.png`.

**Results.** Coherence cells give the value with the null in brackets. The recovered-mode columns give the strict fraction over 10-1000 s.

| site | theta_E | E_perp 30-300 | E_perp 300-1000 | E_perp 1000-3000 | mode | E08 | weighted full tensor | E04 unweighted |
|---|---|---|---|---|---|---|---|---|
| B01 | -81 | 0.009 (0.016) | 0.024 (0.027) | 0.044 (0.051) | xy | 0.00 | 0.00 | 0.00 |
| B04 | 59 | 0.005 (0.014) | 0.014 (0.013) | 0.071 (0.038) | xy | 0.00 | 0.00 | 0.00 |
| B10 | -18 | 0.005 (0.002) | 0.026 (0.025) | 0.088 (0.070) | yx | 0.00 | 0.06 | 0.00 |
| B28 (control) | 72 | 0.168 (0.005) | 0.444 (0.023) | 0.442 (0.076) | xy | 0.69 | 0.88 | 0.88 |

Weighted coherence of the plain channels with Ebro at 30-300 s:
- **hx.** B01 0.307, B04 0.219, B10 0.381; nulls 0.005-0.05.
- **ex and ey.** 0.003-0.010 against nulls of 0.001-0.015.

- **Verdict.** Negative. E_perp stays at the null even with weighting. The control fails: the weighted projection costs B28 0.19 of its xy strict fraction, because at a clean site the weighted "major axis" is natural E.
- **Next.** Look at the source's waveform before trying anything else (E00b).

## E00b (addendum to E00): the source's waveform

- **Script.** `E00_characterise/e00b_waveforms.py`. Figure `e00b_waveforms.png`, with two-hour stretches by day and by night at B01, B04 and B10.
- **What the traces show.** The source arrives as bursts of rectangular, chopper-like pulses lasting 5-15 min, repeated every 10-30 min by day and more sparsely at night. The pulses appear in E and H at the same instants, with opposite or equal sign depending on the channel: B01 ey pulses up while hx dips. That is a train drawing traction current near the site. Between bursts the local E at the plotted scale is flat at B01 and B04, but at B10 (ex) and at B01 at night (ex) a continuous, noisy lower-level signal remains. That signal is uncorrelated with Ebro's smooth natural field.
- **Step statistic.** A thresholded running-median step count was computed for each trace (`metrics_e00b.json`). It does not separate source from natural (step share 0.67-0.99 for every trace, including night-time H), so it was not used.
- **Consequence.** The source is intermittent on the scale of minutes, not only day and night. Gating at that scale is E09.

## E09: burst gating at fine time resolution

- **Question.** Does cutting out the train bursts, with windows short enough to fit the gaps, expose the natural E at 10-128 s?
- **Method.** A local burst detector: the first difference of each E channel, normalised by its median; a sample is "burst" when the 30 s running mean of the larger normalised difference exceeds K times its record median. Bursts are dilated by M s either side. Windows are 128 samples at 1 Hz (bands 4-32 s) and 64 samples at 1/8 Hz (512 s, bands 32-128 s), kept only if wholly clean. One variable per row: K = 3 or 10, M = 60 or 180 s. Scored at 10-128 s.
- **Script.** `E09_burst_gating/e09_burst_gating.py`. Figures `e09_<site>.png`.
- **Failure criterion.** As E03.

**Results.** Coherence is over the 30-128 s bands, with the null in brackets; fractions are over 10-128 s; the control is against B28 rr B29.

| site | rule | clean share | cohH 30-128 | cohE 30-128 | yx phys | yx strict | xy strict | q | control |
|---|---|---|---|---|---|---|---|---|---|
| B01 | all | 1.00 | 0.011 (0.001) | 0.001 (0.001) | 0.00 | 0.00 | 0.00 | 0.086 | |
| B01 | K3 M60 | 0.65 | 0.136 (0.002) | 0.003 (0.002) | 0.00 | 0.00 | 0.00 | 0.252 | |
| B01 | K10 M60 | 0.80 | 0.089 (0.003) | 0.001 (0.003) | 0.00 | 0.00 | 0.11 | 0.146 | |
| B01 | K3 M180 | 0.56 | 0.135 (0.002) | 0.002 (0.002) | 0.11 | 0.00 | 0.00 | 0.192 | |
| B04 | all | 1.00 | 0.001 (0.001) | 0.001 (0.001) | 0.00 | 0.00 | 0.00 | 0.152 | |
| B04 | K3 M60 | 0.53 | 0.009 (0.004) | 0.006 (0.007) | 0.00 | 0.00 | 0.00 | 0.110 | |
| B04 | K10 M60 | 0.86 | 0.002 (0.001) | 0.001 (0.002) | 0.00 | 0.00 | 0.00 | 0.012 | |
| B04 | K3 M180 | 0.37 | 0.020 (0.002) | 0.008 (0.007) | 0.22 | 0.11 | 0.00 | 0.016 | |
| B10 | all | 1.00 | 0.021 (0.001) | 0.000 (0.001) | 0.00 | 0.00 | 0.00 | 0.130 | |
| B10 | K3 M60 | 0.66 | 0.097 (0.002) | 0.003 (0.002) | 0.56 | 0.56 | 0.00 | 0.158 | |
| B10 | K10 M60 | 0.96 | 0.026 (0.001) | 0.001 (0.001) | 0.00 | 0.00 | 0.11 | 0.048 | |
| B10 | K3 M180 | 0.49 | 0.107 (0.002) | 0.005 (0.002) | 0.33 | 0.33 | 0.00 | 0.106 | |
| B28 | all | 1.00 | 0.404 (0.003) | 0.359 (0.003) | 0.33 | 0.33 | 0.78 | 0.543 | 1.00 of 9 |
| B28 | K3 M60 | 0.95 | 0.280 (0.003) | 0.277 (0.004) | 0.78 | 0.78 | 0.78 | 0.735 | 1.00 of 9 |
| B28 | K10 M60 | 1.00 | 0.406 (0.003) | 0.419 (0.003) | 0.78 | 0.78 | 0.78 | 0.794 | 0.78 of 9 |
| B28 | K3 M180 | 0.90 | 0.282 (0.003) | 0.277 (0.003) | 0.78 | 0.78 | 0.78 | 0.893 | 1.00 of 9 |

**Reading.**

- **H is cleaned.** Gating lifts cohH ten-fold at B01 and five-fold at B10 over 30-128 s, on 50-65 % of the record.
- **E is not.** cohE stays at its null at all three sites. The continuous lower-level source between bursts (E00b) still owns E.
- **B10's yx fraction.** B10 K3 M60 reaches yx strict 0.56 (5 of 9 bands, 30-60 deg at 30-100 s, figure). But the error bars span the whole quadrant and cohE is at the null. By the criterion fixed beforehand (both conditions), this is not a recovery. K3 M180 gives 0.33 and K10 M60 gives 0.00, which fits a chance alignment of noisy phases rather than a stable result.
- **Control.** The B28 control passes for K3 (1.00 of 9 bands). K10 M60 keeps all of B28 and scores 0.78, the same as its all-window row on those bands.

- **Verdict.** Negative for E. Gating the bursts is the best H cleaner at 10-128 s, but the E between bursts is still source.
- **Next.** The 1 Hz evidence is consistent across eight methods. What is left is the 0.7-10 s band at 1000 Hz, where gaps between bursts hold many windows (E10).

## E11: what H allows: the horizontal magnetic transfer function to a clean site

- **Question.** Every method lifted the local H's natural share (E03, E05, E06, E09). Is the natural H of a northern site recoverable as a response in its own right? That response is the inter-station horizontal magnetic TF M (H_site = M H_ref), not an impedance.
- **Method.** Per band, nr_common layout, 4-4096 s. H_ref is the clean southern site B14 (1 Hz, B14L). Three estimates:
  - **plain.** Direct regression, M = S_{Hs Hr} S_{Hr Hr}^-1.
  - **weighted.** The same with E05-B weights from the site's own E.
  - **ebr_rr_weighted.** The weighted form with Ebro as remote reference, M = S_{Hs R} S_{Hr R}^-1.

  Pairs: B10-B14 (68 h), B04-B14 (20 h, all the overlap there is) and the control B18-B14 (41 h, both clean). B01 has no clean simultaneous magnetometer closer than Ebro.
- **Script.** `E11_magnetic_tf/e11_magnetic_tf.py`. Figure `e11_magnetic_tf.png`.
- **Failure criterion (stated beforehand).** The diagonal of M must agree within 2 sigma between the weighted estimate and both the plain and the Ebro-RR estimates over 30-1000 s, with median relative error under 10 %.

**Results.** Diagonal of M over 40-3000 s (15 bands).

| pair | estimate | median abs(Mxx) | median phase (deg) | median rel. err | abs(Myy) | phase | rel. err |
|---|---|---|---|---|---|---|---|
| B18-B14 (control) | ebr_rr_weighted | 1.08 | 0.3 | 0.05 | 1.04 | 1.8 | 0.05 |
| B18-B14 (control) | plain | 0.73 | 1.3 | 0.09 | 0.77 | 0.8 | 0.06 |
| B18-B14 (control) | weighted | 0.92 | 0.7 | 0.07 | 0.84 | 0.9 | 0.06 |
| B10-B14 | ebr_rr_weighted | 0.90 | -0.4 | 0.14 | 1.00 | 3.0 | 0.26 |
| B10-B14 | plain | 0.66 | 0.8 | 0.21 | 1.23 | -141 | 0.21 |
| B10-B14 | weighted | 0.93 | 1.1 | 0.10 | 0.64 | -4.7 | 0.41 |
| B04-B14 | ebr_rr_weighted | 0.85 | 1.9 | 0.59 | 3.39 | 60 | 1.26 |

**Reading.**

- **The control exposes a flaw in the criterion.** The direct regressions (plain, weighted) are biased low even between two clean sites: 0.73-0.92 against 1.04-1.08 for the Ebro-RR form. B14's H carries noise and local field that B18's lacks, and the direct regression attenuates by it. Comparing with them was therefore not a valid part of the criterion. Only the Ebro-RR form is unbiased.
- **B10.** With Ebro as reference and weighting, B10's Mxx is 0.90, phase -0.4 deg, relative error 0.14, over 40-3000 s. Myy is 1.00 at relative error 0.26. That is consistent with a laterally uniform natural H (M = I), to about 15-25 %.
- **B04.** Not recoverable (relative error 0.6-1.3; 20 h of overlap and the strongest source on the line).

- **Verdict.** Partial, not a pass by the criterion as written. The criterion's comparison with the direct estimates was invalid, and B10's error is 14-26 % rather than under 10 %. The natural horizontal H at B10 is measurable at 40-3000 s with weighting and Ebro as reference. Nothing comparable holds for E.
- **Next.** No further H-only work planned. It gives no impedance. At most it gives a magnetic perturbation constraint of about 20 % at B10.

## E10: 1000 Hz, 0.1-20 s: night against day, and automatic burst gating

- **Question.** At 0.7-10 s the gaps between train bursts hold many windows. Does an automatic, local-only gate (E09's detector, K = 3, M = 60 s, on the local E decimated to 1 Hz) on a quiet night carry the yx beyond the 0.7 s that Ben's hand masks reach?
- **Data.** 6 h windows at 1000 Hz, read read-only:
  - B04 (B04_fa5afd228.h5) rr B14 (B14.h5, raw, re-ingested at 16:36 and stable), on the night 22/23 Jul 22-04 UTC (the only night the two overlap) and the day 22 Jul 14-20 UTC.
  - B10 (B10_f81e4c0e6.h5) rr B14 on the night 23/24 Jul.
  - B01 (B01_fa5afd228.h5) rr R01 on the night 16/17 Feb. R01 carries its own source; there is no clean February remote.
  - The control B18 rr B14 on the night 23/24 Jul.

  The null is the remote 24 h later (48 h earlier for 24/25 Jul in E10b). The memory rule held: the script waits for more than 40 GB available before every 1000 Hz read. It waited once, during the re-ingest.
- **Chain.** FIR decimation to 100, 10 and 1 Hz; Hann windows of 512/512/128 samples; spectra divided by the filter-chain response; 8 bands per decade, 0.1-20 s; plain RR with a 20-group jackknife.
- **Script.** `E10_1000hz_gating/e10_1000hz_gating.py` (v2). Figure `e10_1000hz_gating.png`.
- **v1 (superseded by v2, kept as `_v1` files).** v1 ran only B04 night/day and B18. Its control compared the 6 h estimates with aurora's whole-record product within 2 sigma, and failed at the clean B18 in 16 of 16 bands, gated and ungated alike: a 6 h window against three days differs by more than the formal errors. That control could not pass, so v2 replaced it with the same-window control (B18 gated against B18 all). v2 also added a test the phase fraction cannot make: the rho slope to each neighbouring band must satisfy |d log rho / d log T| <= 1, the 1-D bound ("strict+slope").
- **Failure criterion (fixed before v1).** yx strict over 0.7-10 s rises by 0.2 over masks2's 0.33 (for B10, over its default product), cohE over 0.7-10 s clears its null by the null's own size, and (v2) strict+slope rises too.

**Results.** cohH and cohE are the coherence of the local H and E with the remote's H, over 0.7-10 s, with the null in brackets.

| case | gate | clean | cohH 0.7-10 | cohE 0.7-10 | yx strict 0.1-10 | yx strict 0.7-10 | yx strict+slope 0.7-10 | xy strict 0.7-10 |
|---|---|---|---|---|---|---|---|---|
| B04 night | all | 0.60 | 0.206 (0.001) | 0.161 (0.001) | 0.31 | 0.11 | 0.00 | 0.78 |
| B04 night | gated | 0.60 | 0.445 (0.004) | 0.324 (0.004) | 0.75 | 0.56 | 0.00 | 1.00 |
| B04 day | all | 0.62 | 0.003 (0.001) | 0.034 (0.001) | 0.19 | 0.00 | 0.00 | 0.33 |
| B04 day | gated | 0.62 | 0.122 (0.001) | 0.163 (0.002) | 0.06 | 0.00 | 0.00 | 0.78 |
| B10 night | all | 0.44 | 0.404 (0.001) | 0.552 (0.001) | 0.56 | 0.44 | 0.11 | 0.00 |
| B10 night | gated | 0.44 | 0.209 (0.004) | 0.141 (0.006) | 0.69 | 0.44 | 0.22 | 0.00 |
| B01 night (rr R01) | all | 0.61 | 0.331 (0.001) | 0.239 (0.001) | 0.06 | 0.11 | 0.00 | 1.00 |
| B01 night (rr R01) | gated | 0.61 | 0.415 (0.003) | 0.300 (0.002) | 0.31 | 0.56 | 0.11 | 0.56 |
| B18 night (control) | all | 0.78 | 0.780 (0.001) | 0.718 (0.001) | 0.75 | 0.56 | 0.00 | 0.22 |
| B18 night (control) | gated | 0.78 | 0.752 (0.001) | 0.636 (0.001) | 0.69 | 0.44 | 0.00 | 0.22 |
| aurora B04 rr B14 default | | | | | 0.60 | 0.33 | 0.00 | 0.67 |
| aurora B04 rr B14 masks2 | | | | | 0.60 | 0.33 | 0.08 | 0.42 |
| aurora B10 rr B14 default | | | | | 0.50 | 0.17 | 0.17 | 0.00 |
| aurora B01 rr R01 default | | | | | 0.00 | 0.00 | 0.00 | 1.00 |
| aurora B18 rr B14 default | | | | | 0.55 | 0.25 | 0.17 | 0.25 |

**B04 yx per band (phase deg / rho ohm m).**

| T (s) | 0.49 | 0.65 | 0.87 | 1.15 | 1.54 | 2.05 | 2.74 | 3.65 |
|---|---|---|---|---|---|---|---|---|
| night, gated | 45/247 | 46/226 | 36/304 | 34/650 | 28/1628 | 21/4868 | 13/6250 | 9/13673 |
| night, all | 36/353 | 40/377 | 43/1226 | 26/4836 | 13/9623 | 4/18723 | 2/31470 | -1/44026 |
| day, gated | -49/264 | -9/284 | 13/1697 | -32/2062 | -18/8223 | -17/20331 | -22/22809 | -23/32973 |
| masks2 (Ben, aurora, whole record) | 41/236 (0.45 s) | 41/243 (0.57) | 37/247 (0.72) | 37/264 (0.91) | 35/404 (1.14) | 11/10611 (1.44) | 34/1973 (1.81) | 24/3706 (2.28) |

**Control (same window).** B18 gated against all agrees within the combined 2 sigma at every band from 0.12 to 0.87 s (both modes) and at 4.9 and 15.4 s. It does not agree at 1.15-3.65 s or at 6.5-11.6 s: 9 of 16 bands in all. Aurora's whole-record B18 is itself out of quadrant at 3-10 s (xy phase to -60, yx above 90). With 6 h of July night-time data, even a clean site does not resolve 1.5-10 s, the dead band.

**The slope test.** It fails at B18 in 0.7-10 s too (0.00), so it is not a clean discriminator on this line. It is reported, not relied on.

**E10b: repeatability of B10.** Script `E10_1000hz_gating/e10b_b10_repeat_nights.py`, figure `e10b_b10_repeat_nights.png`, `metrics_e10b.json`. Same chain and gate on the nights of 22/23 and 24/25 Jul, with B18 as control on 24/25. The failure criterion (fixed beforehand): the 23/24 gated B10 yx at 1.15-2.05 s must repeat within 15 deg and a factor 2 in rho on both other nights.

| night | B10 gated yx at 0.87 / 1.15 / 1.54 / 2.05 s (phase/rho) |
|---|---|
| 22/23 Jul | 34/69, 22/73, 30/34, -62/635 |
| 23/24 Jul (E10) | 40/120, 44/144, 46/147, 49/145 |
| 24/25 Jul | 64/94, 55/72, 14/9, -42/65687 |

B18 (clean) on 24/25 Jul gives 27/12, 24/15, 37/23, 55/50 (gated), against 41/15, 49/29, 55/74, 58/186 (all) on 23/24 Jul. Not repeatable: 0 of 3 bands on each night.

**Reading.**

1. **B04.** The automatic gate on the quiet night does, locally and automatically, what Ben's hand masks do. It gives a physical-looking yx (34-46 deg, rho 230-650) to 1.15 s, where masks2 reaches 1.14 s. It does not go further: from 1.15 s the rho climbs steeply (650, 1628, 4868 ohm m) as the phase falls to 0, the source taking over again. Without the gate the same night gives way at 0.87-1.15 s (rho 1226-4836). The day gives nothing (yx phase -9 to -49 deg from 0.5 s). cohE at 0.7-10 s rises from 0.03 (day) through 0.16 (night) to 0.32 (night, gated), all nulls under 0.005, so the gate does expose some natural E at night. But the gain in scorecard phase fractions sits in the bands where masks2 already works, plus 1.15-2 s, where the curve is the transition into the source.
2. **B10.** The yx is the mode the source does not hold at B10. On the night 23/24 Jul it looked physical to 2 s (phase 40-49, rho 120-150). It does not repeat on 22/23 or 24/25 Jul (E10b). Night to night, B10's and even B18's yx at 1.15-2 s vary by 15-40 deg: that is the July night-time noise floor near the dead band, not a recovery.
3. **B01** (rr R01, whose own source enters the remote) gives nothing new. The xy passes the phase and slope tests in both the default product and E10 (phase 15-20 deg). That is also what a mixture of source (phase 0) and Earth would look like, and E00 shows xy source-dominated at 4 s and beyond.
4. **B04 xy.** At 1.5-10 s it looks physical in every estimate (rho about 2.5e3 flat, phase 35-42), including the day-gated one. It is not tested against a neighbour. It is listed as an open question.

- **Verdict.** Automatic burst gating on a quiet night is a local, reproducible replacement for the hand cross-power masks to about 1-1.15 s. Nothing beyond that is recovered in yx at B04 or B10, and 1.5-10 s cannot be tested with one July night even at a clean site. By the criterion fixed beforehand, the B04 night-gated row passes the phase and coherence conditions but fails the slope condition. The slope condition turned out to fail at the clean control too, so the decisive evidence is the B04 curve's shape (phase falling to 0 while rho climbs) and the E10b non-repeatability.
- **Next.** Stop. Every route tried ends at the same wall: the E field of the source, 27-55 dB over the natural E at 1 Hz and taking over again at about 1 s at 1000 Hz even on the quietest night.

## Closing summary (17:00)

- **Budget.** The characterisation plus nine distinct methods or combinations (E02-E10) and one H-only product (E11) were scored. The log shows the same wall throughout, so work stopped.
- **The wall.** The local E at B01, B04 and B10 carries the source 27-55 dB (power) above the natural E at 4-4096 s. No lever or combination of levers here closes that gap: time selection or weighting, burst gating, polarisation, array prediction, and projection onto Ebro. The H is partly recoverable; the impedance is not.
- **At 1000 Hz.** Automatic night-time burst gating matches the hand masks to about 1.1 s and no further.
- **Where the full picture is.** The experiment table, what worked, what did not, what was not tried and why, and the open questions are in `STATUS.md`.
