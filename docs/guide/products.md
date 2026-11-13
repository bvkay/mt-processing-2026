# Archives, products and frames

This page says what is kept on disk: the workspace, a site's raw archive
and its filtered variant, the files a processing run writes, and the frame
and declination every product carries.

## The workspace

Everything a run writes goes to the survey's workspace, `workspace:` in
`survey.yaml`: the archives in `mth5/`, the products in `tf/`, the figures
in `qc/`, and `campaign/`, `datum/` and `logs/`. `scripts/new_survey.py`
sets it to `<data_root>/work`, beside the raw data. Without the key it is
the folder `work` beside `survey.yaml`.

## The raw archive and its filtered variant

`mth5/<site>.h5` is the raw recording, with no filter applied. A site's
noise filters are a list under its name in `filters.yaml`, beside
`survey.yaml` (see `surveys/burra/filters.yaml`). Such a site is processed
from a filtered variant, `mth5/<site>_f<hash>.h5`, built from the raw
archive on first use and rebuilt when the list changes or the raw archive
(or that of a `replace` donor) has been rebuilt. One variant is kept per
site. `--no-filters` on a processing script reads the raw archive. A raw
archive ingested with a coil response file that has since changed is
refused until the site is re-ingested.

| kind | what it does |
|---|---|
| `notch` | zero-phase notch at `f0` (50 Hz) and its harmonics |
| `mains` | subtracts a fitted mains model that follows steps in the mains amplitude, so a step does not ring |
| `hp`, `lp` | zero-phase Butterworth high-pass or low-pass; `cutoff_hz` is required |
| `cp` | cathodic protection: subtracts the median cycle of the fixed period `period_s` |
| `burst` | sets short transients to the local level |
| `template` | subtracts a glitch that repeats once per `period_s` |
| `flip` | multiplies the listed `channels` by -1 |
| `replace` | takes a channel from another site's raw archive: `{hx: A06}` |

The list is applied in the declared order, `replace` first wherever it
sits. Put a high-pass first, `notch` or `mains` before `cp` and `burst`, and
a low-pass last. A high-pass also removes the signal at every period longer
than 1 / `cutoff_hz`. `channels` narrows a filter (default: every channel,
for `template` the magnetics). The docstring of `src/mt_workbench/noise.py`
gives every option and its default. Try a list on the Filter Data tab
([gui.md](gui.md)) first.

## Product names

Every product is remote-referenced, against an adjacent site, a dedicated
remote or a stacked remote. The archive always holds the whole deployment;
the processing window (`start`, `end`, in UTC) and the scope of masks are
under `process_rr.py` on [commands.md](commands.md).

A `process_rr.py` run writes into `<workspace>/tf`, under the stem
`<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<tag>]`:

- `.edi`: the impedance and tipper;
- `.xml`: EMTF XML with the residual and inverse signal covariances, which
  a rotation of the errors needs (the EDI's variances cannot be rotated
  exactly);
- `.h5`: a standalone MTH5 file holding the transfer function, not the
  site's raw archive;
- `.json`: the sidecar, the record of the run;
- `_vs_lemimt.png`: the comparison figure.

The stamp is the local time the run started, so a re-run never replaces an
earlier product. `merge_best.py` and `merge_modes.py` write the same
`.edi`, `.xml` and `.h5`, without covariance: the INFO line
`mt_workbench.covariance=none` says so. The tensor products are on
[tensors.md](tensors.md).

## Frame and declination

Every product stays in the sensor frame and is never rotated at processing:
x is the sensors' north as laid out. Which north that was is `layout_north`,
`magnetic` (the default) or `geographic`, in `defaults:` or a site's entry.
It sets the station's reference frame (geomagnetic or geographic) in the
archive and on each product, and with it the EDI's COORDINATE_SYSTEM.

The declination is stored with every product and never applied, so a
modeller rotates once, inside the inversion. It is three keys of a site
entry (or `defaults:`), unset until `scripts/declination.py <survey.yaml>
--write` fills them. Unset is not 0.0.

```yaml
sites:
  B03:
    declination: -1.07          # degrees east of geographic north
    declination_model: IGRF-14
    declination_epoch: 2023.55  # decimal year, the midpoint of the record
```

- `process_rr.py` sets the local site's `survey.yaml` frame and declination
  on the product, over the archive's, so an archive needs no rebuild after
  `declination.py`. A site with no declination gets a warning and no
  DECLINATION line.
- The EDI's HEAD carries DECLINATION, DECLINATION.MODEL and
  DECLINATION.EPOCH. In the XML, Site Orientation
  `angle_to_geographic_north` is the declination D and each horizontal
  channel's orientation is its layout azimuth plus D.
- A merge takes its frame from the first xy source's EDI.
- A fluxgate turned or levelled at ingest ([instruments.md](instruments.md))
  is named in the INFO lines `mt_workbench.rot_h`,
  `mt_workbench.rot_h_parts` or `mt_workbench.h_tilt`. That is a correction
  of the sensor's layout, not a rotation of the estimate.

## ZROT convention

For a geomagnetic product with a declination D (east positive), the EDI
carries ZROT = TROT = D at every period and the data are left as estimated.
ZROT states the azimuth of the data's x-axis, clockwise from geographic
north. It is not a rotation that was applied.

- Geotools writes the same convention: its own rotation by t writes ZROT t
  with Z' = R Z R^T, R = [[cos t, sin t], [-sin t, cos t]]. How Geotools
  treats a non-zero ZROT on import is not tested yet.
- Geotools drops COORDINATE_SYSTEM and zeroes AZM on export but keeps INFO,
  so the frame is also written there in words (`mt_workbench.frame`,
  `mt_workbench.rotation`, `mt_workbench.declination`).
- With `layout_north: geographic`, or with no declination, ZROT and TROT
  are 0.
- `products: {zrot: zero}` at the top level of `survey.yaml` writes ZROT =
  TROT = 0 for every product, the declination recorded only. The default
  is `zrot: declination`.
- aurora does not estimate the Ex-Ey term of the residual covariance. It is
  written as 0, so rotated errors assume no correlation between the two
  electric channels.
