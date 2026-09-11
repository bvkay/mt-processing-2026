# BBMT-processing-2026

Broadband magnetotelluric (BBMT) processing for Adelaide Uni surveys recorded on
LEMI-423 (and later Earth Data) loggers, built on the IAGA-DVI stack
([mt-io](https://github.com/kujaku11/mt-io), [mth5](https://github.com/IAGA-DVI-DataStandards/mth5),
[mt-metadata](https://github.com/IAGA-DVI-DataStandards/mt-metadata)) with
[aurora](https://github.com/simpeg/aurora) as the transfer-function engine.

Design rules, in order:

1. **Thin.** `bbmt` wraps the community packages; it does not re-implement them.
2. **Headless first.** Everything runs from a script or the command line; the GUI
   (coming later) calls the same functions.
3. **Decisions are data.** Noise masks, band choices and remote-reference pairs
   live in per-survey YAML/JSON files, never buried in code or notebooks.

## Install

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

## Layout

```
src/bbmt/          the package: survey.py, ingest.py, process.py, compare.py,
                   bands.py, qc.py, timefreq.py, virtual.py
surveys/<name>/    one folder per survey: survey.yaml (config), reference_edis.yaml,
                   qc_notes.md (what was learned about each site) + work/ (outputs, gitignored)
scripts/           the student-facing command line, one job each (see below)
examples/          runnable end-to-end examples for students
```

## Command line (no notebooks, no LLM: plain scripts a student runs)

| step | script |
|---|---|
| field sheet -> `sites:` block | `scripts/site_table_to_yaml.py`, `scripts/burra_notes_to_yaml.py` |
| legacy EDIs -> `reference_edis.yaml` | `scripts/match_reference_edis.py <edi_dir> <survey.yaml>` |
| before ingest: file-boundary slips, clock offset vs remote, GPS status | `scripts/timing_qc.py <survey.yaml> <local> <remote>` |
| quick look at raw noise (Welch PSD, mains zoom) | `scripts/noise_psd.py <survey.yaml> <site>` |
| ingest both sites, remote-reference TF, overlay on lemimt | `scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end]` |
| per-site QC set: overview, band coherence vs time, coherogram, spectrogram | `scripts/site_qc.py <survey.yaml> <site> [--remote R]` |
| whole-record PSD per channel from the archive, remote overlaid, lines marked, before/after filters | `scripts/psd_qc.py <survey.yaml> <site> [--remote R] [--before]` |
| stacked synthetic remote from concurrent sites (members' declared filters applied) | `scripts/build_stack.py <survey.yaml> <name> <start> <end> <member>...` |
| band-averaged coherence on the processing bands | `scripts/coherence_qc.py <survey.yaml> <local> <remote> [--stack S]` |

Every product is remote-referenced: an adjacent site, a dedicated remote, or a
stacked synthetic remote (`bbmt.virtual`). There is no single-station product.

`start`/`end` on the processing scripts are a *processing window* (UTC): the
MTH5 archive always holds the whole deployment, the window only trims what
aurora estimates from (e.g. Burra35 after its Ex cable failed).

Per-site noise decisions live in `<survey>/filters.yaml` (see
`surveys/burra/filters.yaml`), separate from the field-sheet-generated
`survey.yaml`; a site with an entry there is filtered at ingest, in order.
Change the list, delete the site's `.h5`, re-run.

## Quickstart: a survey in four lines

A survey is a YAML file pointing at the folder that holds the raw site
directories. **Site name = folder name** — nothing else to configure per site
unless a site needs overrides (dipole lengths/azimuths come from the field
spreadsheet via `scripts/site_table_to_yaml.py`).

```python
from bbmt.survey import Survey
from bbmt.ingest import ingest_site
from bbmt.process import process_station

survey = Survey.from_yaml("surveys/curnamona_cube/survey.yaml")
local  = ingest_site(survey, "D02", start="2021-06-29 12:00", end="2021-06-29 18:00")
remote = ingest_site(survey, "E08", start="2021-06-29 12:00", end="2021-06-29 18:00")
tf = process_station(local, "D02", remote, "E08", out_dir=survey.workspace / "tf")
```

See `examples/01_validate_d02_e08.py` for the full validation run against the
legacy lemimt EDIs.

## Status

- [x] LEMI-423 ingest -> MTH5 (contiguous B423 files merged into long runs, a
      new run at any file-spacing anomaly; per-survey `channels` list drops the
      unconnected hz; per-survey `flip_reversed_dipoles` says whether a 180/270
      field-sheet azimuth means a reversed pair — true at Curnamona, false at Burra)
- [x] Aurora single-station / remote-reference wrapper -> EDI, with a
      processing window and an automatic impedance-phase-quadrant check
- [x] Comparison plots against legacy lemimt EDIs
- [x] Validation vs lemimt on a clean Curnamona Cube pair: D02 RR E08 matches
      the merged lemimt EDI over 0.005-~3000 s (rho and phase, both modes)
      with the lemimt-style 60-band scheme
- [x] Burra (noisy) first results: Burra35 RR Burra54rr3 matches lemimt
      0.005-1 s and 15-1000 s on its good-Ex window; Burra57 matches 15-1000 s;
      the 0.3-15 s cathodic-protection band is the open problem
      (`surveys/burra/qc_notes.md`)
- [x] Timing QC before ingest (`scripts/timing_qc.py`): no clock errors found
      at the Burra "Behind" sites; the one 1 s event is a remote file-boundary slip
- [x] Noise toolbox, first steps (`bbmt.noise`, `bbmt.ingest`; declared per
      site in `<survey>/filters.yaml`, applied at ingest in the listed order,
      provenance written into the archive): `replace` (borrow a magnetic
      channel from another site, with that site's coil calibration — the field
      crews' "replace magnetics" for a dead coil), `notch` (50 Hz + harmonics,
      zero-phase) and `cp` (cathodic protection: stack every cycle at the
      declared period in 10-min windows and subtract the median cycle from
      every channel — no detection, no cutting). Never auto-detected —
      declared after looking at the QC figures.
- [ ] Noise toolbox, next: per-channel time masks, band schemes
- [ ] Band-placement experiment around mains: 50 Hz at band edge vs notched
      vs band centre (anchor option in bands.py), same data three ways
- [x] Stacked/synthetic remote references from multiple array sites — mean
      stack implemented and tested on D02 (found A07's dead hx in the process)
- [ ] Coherence-weighted stacking: per-member weights per time chunk and
      band group (0.1–1, 1–10, 10–100, 100–1000 s), then full per-band
      weighting at the Fourier-coefficient level; median stack as the
      robust baseline
- [x] Time-resolved coherence QC (`scripts/site_qc.py`, ported from the AusLAMP
      figures): whole-record overview, band coherence vs time, coherogram and
      spectrogram for Bx–Ey, By–Ex, Bx–By, Ex–Ey and the local-E vs remote-B
      pairs — the input for stack weights and time masks (next)
- [ ] Earth Data logger ingest
- [ ] Batch CLI, then GUI
