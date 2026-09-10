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
src/bbmt/          the package: survey.py, ingest.py, process.py, compare.py
surveys/<name>/    one folder per survey: survey.yaml (config) + work/ (outputs, gitignored)
scripts/           one-off tooling (e.g. field spreadsheet -> survey.yaml)
examples/          runnable end-to-end examples for students
```

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

- [x] LEMI-423 ingest -> MTH5 (one run per raw B423 file; reversed dipoles
      sign-corrected from field-sheet azimuths)
- [x] Aurora single-station / remote-reference wrapper -> EDI
- [x] Comparison plots against legacy lemimt EDIs
- [x] Validation vs lemimt on a clean Curnamona Cube pair: D02 RR E08 matches
      the merged lemimt EDI over 0.005-~3000 s (rho and phase, both modes)
      with the lemimt-style 60-band scheme
- [ ] Noise toolbox: time masks, band schemes (next)
- [ ] Band-placement experiment around mains: 50 Hz at band edge vs notched
      vs band centre (anchor option in bands.py), same data three ways
- [x] Stacked/synthetic remote references from multiple array sites — mean
      stack implemented and tested on D02 (found A07's dead hx in the process)
- [ ] Coherence-weighted stacking: per-member weights per time chunk and
      band group (0.1–1, 1–10, 10–100, 100–1000 s), then full per-band
      weighting at the Fourier-coefficient level; median stack as the
      robust baseline
- [ ] Time-resolved coherence QC (coherogram): Bx–Ey, By–Ex, Bx–By, Ex–Ey,
      and local-E vs remote-B pairs per band group across time — drives
      both stack weights and time masking for noisy sites
- [ ] Earth Data logger ingest
- [ ] Batch CLI, then GUI
