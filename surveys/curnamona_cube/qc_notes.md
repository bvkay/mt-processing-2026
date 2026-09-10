# Curnamona Cube — site QC notes

Findings from processing/QC, so nobody rediscovers them the hard way.

- **A07 hx is dead** for at least 2021-06-29 06:00 → 2021-07-01 00:00 UTC:
  band-averaged coherence vs E08 hx = 0.00 at all periods (0.005–5000 s),
  while A07 hy is excellent (0.93–1.00). Found 2026-09-21 when a 5-site
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
