# Curnamona Cube — site QC notes

Findings from processing/QC, so nobody rediscovers them the hard way.

- **A07 hx is dead** for at least 2021-06-29 06:00 → 2021-07-01 00:00 UTC:
  band-averaged coherence vs E08 hx = 0.00 at all periods (0.005–5000 s),
  while A07 hy is excellent (0.93–1.00). Found when a 5-site
  synthetic remote stack went noisy at 3–100 s. Do not use A07 hx as a
  remote; check whether the whole deployment is affected before processing
  A07 itself.
- **B06 hz railed** at negative full scale in the first file of its
  deployment (2021-06-28 05:08, instrument settling). Check mid-deployment
  before trusting hz.
- **D02 Ex reversed in the field** (37 m dipole at 180°); handled at ingest
  via the field-sheet azimuth (sign flip). Same applies to A06 ex (180°) and
  B02 ey (270°).
- **Dead band 2–10 s is total** at these sites: all coherences (local E–H
  and inter-station H–H) drop to ~0–0.15. Error bars balloon there; that is
  data, not processing.
- **hz is unusable at D02 and E08** (found with `scripts/site_qc.py`,
  confirmed on raw counts): E08's Bz is a constant −2³¹ counts for the whole
  deployment (open input), D02's saws between −2³¹ and ~−8.6e8. The tipper
  from either is meaningless; the D02 RR E08 validation covers impedance only.
  Look at the overview figure's hz panel before trusting any tipper.
- **A07 with hx replaced by A06's** (`surveys/curnamona_cube/filters.yaml`:
  `replace: {hx: A06}`; figure
  `docs/figures/A07_hx-from-A06_rr-E08_vs_lemimt.png`): RR on E08 over the
  validation window gives xy matching lemimt 0.005–5000 s (A07's own Hy) and
  a smooth, physical yx from the borrowed coil over 0.005–1000 s (phases +41
  / −139 deg at short periods). Lemimt's A07 yx was made from the dead hx
  and stops at 3 s, so it is not a reference; the borrowed-coil yx assumes
  the horizontal field is the same 32 km away (the D02-with-E08's-H test at
  149 km showed a 28–32 % / 4–6 deg bias from that assumption). Use it as
  the best available yx for A07, labelled as borrowed. Implementation
  lessons: the donor channel must carry only its linear + coil filters (the
  site's h_scale is appended once for every coil afterwards; a duplicate
  stage name makes mt_metadata drop the whole chain and aurora then skips
  the calibration), and its channel attributes must be rewritten to this run.
