# Archives, products and frames

This page says what is kept on disk: the workspace, the raw archive of a
site and its filtered variant, the files a processing run writes and their
names, and the frame and declination every product carries.

## The workspace

A survey's **workspace** (`workspace:` in `survey.yaml`) holds the archives,
transfer functions, figures and the basemap. `scripts/new_survey.py` puts it
beside the raw data, `<data_root>/work`, since a 100-site survey's archives
run to hundreds of GB; a survey.yaml without the key takes
the default, `surveys/<name>/work/` (gitignored).

## The raw archive and its filtered variant

Per-site noise decisions live in `<survey>/filters.yaml` (see
`surveys/burra/filters.yaml`), separate from the field-sheet-generated
`survey.yaml`. Every archive `ingest_site` writes, `<site>.h5`, is the raw
recording, with no filter applied. A site with a declared list is
processed from a filtered **variant** instead, `<site>_f<hash>.h5`
(`mt_workbench.ingest.processing_archive`/`build_variant`), built on demand from
the raw archive and rebuilt whenever the hash of the declared list changes (a
`filters.yaml` edit); one variant is kept per site at a time. `process_rr.py`
and `build_stack.py` (through `mt_workbench.virtual`) always read
`processing_archive`'s result, also for a declared site whose raw folder is
not found under `data_root` (a stale path or a drive not plugged in: such a
site is never a virtual remote); `--no-filters` reads the raw archive outright.
Try the list on a loaded window on the GUI's Filter Data tab first. The
kinds, documented in `src/mt_workbench/noise.py`'s module docstring: `notch` (50 Hz +
harmonics), `hp` / `lp` (zero-phase Butterworth high- / low-pass,
`cutoff_hz` required, order 4; a high-pass goes first and removes every
period longer than 1 / cutoff_hz, a low-pass goes last), `cp` (cathodic
protection stack) and `replace` (magnetics from another site's raw archive,
applied first); `notch`, `hp`, `lp` and `cp` take an optional `channels` list
(default all).

## Remote reference and the processing window

Every product is remote-referenced: an adjacent site, a dedicated remote, or a
stacked synthetic remote (`mt_workbench.virtual`). There is no single-station product.

`start`/`end` on the processing scripts are a *processing window* (UTC): the
MTH5 archive always holds the whole deployment, the window only trims what
aurora estimates from (e.g. Burra35 after its Ex cable failed).

## Product names

`scripts/process_rr.py`'s EDI, comparison figure and `.json` sidecar in
`<workspace>/tf` share one stem, `<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>]`
(the run's own start in local time, not the processing window, which is in
the sidecar). Older EDIs keep their old
`<local>_rr-<remote>[_w<start>-<end>][_<tag>]` names and have no sidecar,
e.g. `surveys/curnamona_cube/work/tf/D02_rr-E08.edi` and the Morocco batch
EDIs, both left as they are.

## Frame and declination

Every product stays in the sensor frame and is
never rotated at processing: x is the sensors' north as laid out. Which
north that was is the survey's `layout_north` key, `magnetic` (the
default) or `geographic`, in `defaults:` and overridable per site; it sets
the station's `orientation.reference_frame` (geomagnetic or geographic) at
ingest for every reader, so a LEMI-424 site is not labelled with its
reader's geographic default, and again on each TF at write time, and with
it the EDI's COORDINATE_SYSTEM. The declination is stored with every
product so a modeller rotates once, inside the inversion. A survey.yaml
site entry (or `defaults:`) carries it as three keys, unset (None, which
is not 0.0) until `scripts/declination.py` fills them:

```yaml
defaults:
  layout_north: magnetic        # the north the sensors were laid out to, or geographic
sites:
  B03:
    declination: -1.07          # degrees east of geographic north
    declination_model: IGRF-14
    declination_epoch: 2023.55  # decimal year, the midpoint of the record
```

Ingest copies them into the archive's station metadata
(`location.declination`), never `translated_azimuth`; `process_rr.py` sets
the local site's survey.yaml frame and value on the TF before writing,
over the archive's, so an archive ingested before the keys existed needs
no rebuild (the sidecar's `frame.declination_source` says which, and
`frame.zrot` records the angle below). Each row writes three products
under its stem (`mt_workbench.products.write_products`): the `.edi`, whose
HEAD carries DECLINATION, DECLINATION.MODEL and DECLINATION.EPOCH lines
and whose INFO `transfer_function.coordinate_system` equals the HEAD's
COORDINATE_SYSTEM; the `.xml`, EMTF XML, which for an aurora row carries
the residual and inverse signal covariances (RESIDCOV, INVSIGCOV), the
full error covariance a rotation needs (the EDI's ZXX.VAR-style variances
cannot be rotated exactly), and whose Notes state the frame; and the
`.h5`, a standalone MTH5 file holding the survey, station and TF
(`MTH5.tf_summary`, `MTH5.get_transfer_function`), not the site's raw
archive. The sidecar names them (`edi`, `xml`, `h5`). A station id with a
hyphen (KD-Q5) keeps it in the EDI's DATAID and the XML's Site Id, written
and read back (`products.hyphenated_station_ids`, upstream issue 86).
`merge_best.py` and `merge_modes.py` take the frame (declination, frame,
channel azimuths) from the first xy source's EDI and write the same three
files; a merge carries no covariance, which its INFO line
`mt_workbench.covariance=none` and its XML Notes say. A source EDI written
before mt_metadata's azimuth and declination fixes (fork commit 405e7ff)
reads back with no declination and hy at AZM 0, and a merge from
it prints a WARNING and repeats that until the source row is re-run.

## ZROT convention

For a geomagnetic product with a declination D (east
positive), the EDI carries ZROT = TROT = D at every period and the data
are left as estimated: ZROT states the azimuth of the data's x-axis,
clockwise from geographic north, not a rotation that was applied. This
matches the convention Geotools writes: its own rotation by t writes
ZROT t with Z' = R Z R^T, R = [[cos t, sin t], [-sin t, cos t]], and a
ZROT 0 file round-trips unchanged (export test); how Geotools
treats a non-zero ZROT on import is not yet tested.
Geotools drops COORDINATE_SYSTEM and zeroes AZM on export but keeps INFO
unchanged, so the frame is also written there in words
(`mt_workbench.frame=sensor frame, x-axis at azimuth -1.07 deg clockwise
from geographic north`, `mt_workbench.rotation=data not rotated; ...` and
`mt_workbench.declination`, `_model`, `_epoch`). The EMTF XML states the
same in its own fields: Site Orientation `angle_to_geographic_north` is D
and each horizontal channel's orientation is its layout azimuth plus D
(Hx D, Hy 90 + D, Ex D, Ey 90 + D), and its Notes say so. With
`layout_north: geographic`, or with no declination stored, ZROT, TROT and
the angle are 0 (the declination, when known, is still stored). aurora
regresses each output channel separately, so the residual covariance's
Ex-Ey cross term is not estimated: the XML writes it as 0 (not the 1e32
EMPTY fill of mt_metadata's writer) and the h5 as 0, and both say that
rotated errors then assume zero output-side correlation.
