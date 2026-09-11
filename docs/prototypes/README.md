# Prototypes (reference code, not part of the package)

Working scratch scripts that established a result and are kept as the
reference implementation for the corresponding `bbmt` feature. They read raw
B423 files directly (see `timing_probe.py` for the record layout) and run
from this folder with the `bbmt-2026` env.

- `timing_probe.py` — B423 memmap helpers; cross-correlation clock check.
  Productised as `scripts/timing_qc.py`.
- `cp_remove_proto2.py` — cathodic-protection removal by edge-locked 12 s
  template (10-min running median, per-cycle alignment for coils). Result:
  comb lines −31 dB but coil coherence with the remote unchanged.
- `cp_lines_vs_broadband.py` — shows the coil contamination is broadband
  (between-line coherence 0.27) and that excising ±0.5 s around each
  switching edge restores it to ~0.6.
- `cp_recipe.py` — the combined recipe (E: template subtraction; all
  channels: ±0.5 s edge excision with linear interpolation) with the
  coherence table in `surveys/burra/qc_notes.md`. Basis for the
  student-declared CP step in ingest (not automatic: the student sees the
  square wave / comb in `scripts/site_qc.py` output and declares the period
  and reference channel for that site in `survey.yaml`).
- `cp_recipe_notch_first.py` — Ben's order: zero-phase 50 Hz + harmonics
  notch first, then the CP step on the cleaner series. Edge timing scatter
  7 → 5 ms; electrics' coherence with the remote recovers (ey–hx 0.06 → 0.19
  in 0.3–2 s, 0.40 → 0.64 in 0.05–0.3 s); coils unchanged within scatter.
  This is the order the ingest filter list applies.
- `kiss_fold.py`, `kiss_variants.py` — Ben's KISS version, which won: one
  period (12.0000 s; autocorrelation at a 50-cycle lag), fixed-grid stacking
  per 10-min window, median cycle subtracted from every channel, nothing
  detected, nothing cut. On 12 h of Burra35 (notch first): coil coherence
  with the remote 0.49 → 0.71 in 0.3–2 s with 0.05–0.3 s untouched; any
  excision around the edges (±0.2–0.5 s) pushed coherence below raw. This is
  what `bbmt.noise.cp_stack_subtract` implements; the edge-detector variants
  above are kept only as the record of what was tried.
