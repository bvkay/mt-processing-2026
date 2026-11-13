# Instruments

This page covers the recorders mt-workbench reads, how a site's recorder is
found, and the keys of `survey.yaml` that act when a site is ingested. The
ingest script, `scripts/ingest_site.py`, is on [commands.md](commands.md).

## The recorders

| `instrument:` | recorder | files of a site folder | rate | archive channels, units |
|---|---|---|---|---|
| `lemi423` | LEMI-423 broadband | `<unix epoch>.B423`, 90 min each | the survey's `sample_rate` (1000 Hz unless set) | hx hy hz ex ey, counts |
| `lemi424` | LEMI-424 long period | `YYYYMMDDhhmm.txt`, one text line a second | 1 Hz | hx hy hz ex ey e3 e4, nT and mV/km |
| `edl` | Earth Data PR6-24 | `{station}YYMMDDhhmmss.{BX,BY,BZ,EX,EY}` in day folders, `config/recorder.ini` | from `recorder.ini` | hx hy hz ex ey, microvolts |
| `phoenix` | Phoenix MTU-5C, MTU-8A | recording folders: `empower_recmeta.json` or `recmeta.json` beside channel folders of `.td_150`, `.td_30`, `.td_24k` files | 150 or 30 Hz, bursts 24 kHz | ex ey hx hy hz, volts |
| `mtu5a` | Phoenix MTU-5A | `<serial><month><day><letter>.TS4` with its `.TBL` | 150 Hz | ex ey hx hy hz, counts |
| `orangebox` | Orange Box (Flinders HFM) | hourly `HFM<n>-NNN.BIN` or `LP<n>-NNN.BIN` | 10 Hz | hx hy hz ex ey, counts |

The steps from field units to the archive's units are stored with each
channel as a filter chain, and processing divides by it. `channels:` and
`filters.yaml` use the archive's channel names.

A folder under `data_root` is a site when it holds files of one of these
recorders. A site's recorder is its own `instrument:` if its entry has one,
else what its folder holds, else the survey's `instrument:`.

### LEMI-423

- `new_survey.py` writes `calibration_fn` (the LEMI-120 coil response, or
  its `--calibration FILE`) and `h_scale: -1000.0` into `defaults:`: check
  both (keys below). Without the coil response only a warning is logged,
  and the transfer functions are wrong.
- A gap between files starts a new run. A file that cannot be read, and
  B423 files in a subfolder beside the recording, are left out with a
  warning.
- `timing_qc.py`, `noise_psd.py` and `psd_qc.py --before` read B423 files
  only.

### LEMI-424

- The columns Bx By Bz E1 E2 E3 E4 are stored as hx hy hz ex ey e3 e4, the
  electrics in mV/km as the logger writes them: no dipole length is applied.
- E1 and E2 are recorded with the opposite sign to x north, y east. The
  samples stay as written, and the sign is a stage of each electric chain
  (`e_sign`).

### Earth Data PR6-24 (`edl`)

- The rate comes from `recorder.ini`, else from the file stamps and sample
  counts.
- The PR6-24's own gain per channel is not modelled: the high-gain flags of
  `recorder.ini` are reported and not used (upstream 21). See
  `electric_gain` below.
- Files of another station left in the folder are left out with a warning
  (workbench 73).

### Phoenix MTU-5C and MTU-8A (`phoenix`)

- A site folder holds one recording folder, or several that share the
  receiver, coils and dipoles; `recording:` names one of them.
  `sample_rate: 150` reads `.td_150` files and 30 reads `.td_30` (untested).
- `calibration_dir` is required: the folder of `<receiver>_*.rxcal.json`
  and `<serial>_*.scal.json` files, which `phoenix_cal_convert.py`
  ([commands.md](commands.md)) makes from the binary ones. `new_survey.py`
  writes `calibration_dir: sensors`.
- `coil_hx`, `coil_hy` and `coil_hz` replace the coil serials of the
  recording's metadata file. A declared `serial:` must be the receiver's.
- A gap starts a new run. A sequence missing from one channel folder is
  left out of every channel (`phoenix_gap` in the run comment).
- Stamps of file version below 3 are 1 s behind GPS: 1.0 s is added and
  recorded as `phoenix_stamp_correction_s` (upstream 47).
- Not corrected: the delay of the receiver's decimation filter on the
  continuous stream. Declare it as `clock_offset_s` (-0.1148 s at
  Kalkaroo).
- Not applied: `polInv` of the metadata file, recorded only (upstream 54).
  Not read: `.td_2400` and `.td_96k` files.
- A warning that names `phoenix_h_polarity` means the archive was built
  before that stage and its impedance is 180 deg off: re-ingest it with
  `--force` (upstream 81).

### Phoenix bursts

A receiver's 24 kHz bursts are a site of their own, `<site>H`:

```yaml
sites:
  G5H: {bursts_of: G5, sample_rate: 24000}
```

- The entry may also hold `remote`, `notes` and `clock_offset_s` (0.0 unless
  declared, since the bursts carry GPS time). Every other setting is G5's.
- `scripts/ingest_site.py <survey.yaml> G5H` builds it from G5's folder, one
  run per burst. A last file that ends inside a burst loses that burst
  (upstream 73).
- Process burst sites with `process_intersite.py` and join the result to
  the continuous record's with `merge_tensor_bands.py`:
  [tensors.md](tensors.md#one-tensor-over-a-phoenix-receivers-whole-band).
  `process_rr.py` is practical only over a few hundred bursts (upstream
  46).

### Phoenix MTU-5A (`mtu5a`)

- Each `.TS4` (150 Hz) is read with its `.TBL`, one run per recording; a
  new run starts where the record tags step by other than 1 s. Set
  `sample_rate: 150`.
- Refused: a `.TS4` without its `.TBL`, two receivers in one folder,
  overlapping recordings, and recordings whose gains or dipole lengths
  differ (workbench 137).
- The tags' saturation, status and clock flags are written to
  `<archive stem>.mtu5a_flags.csv` and are not applied as masks (workbench
  123).
- Not applied: a coil response (workbench 119), so an impedance or magnetic
  tensor from MTU-5A magnetics is wrong, while the telluric tensor is not
  affected; an H sign stage (workbench 121), so an impedance may sit 180 deg
  off; and the band delay its calibration implies, 0.196 s (workbench 122),
  which cancels only between two MTU-5A sites.
- Only the 150 Hz band is read: the `.TS2` and `.TS3` bursts are left out
  (workbench 120).

### Orange Box (`orangebox`)

- Needs `electric_full_scale_uv` (25000 for the +/-2.5 V boxes before July
  2010, 100000 for the +/-10 V ones after) and `magnetic_full_scale_nt`
  (70000 or 100000). A site without them is refused (upstream 13, 14).
- The file stamps are the logger's own clock, read as UTC unless
  `clock_timezone` names the zone. `clock_drift_s` (GPS minus logger at
  recovery, in seconds) is spread over the deployment. Without it no drift
  is corrected and the run comment says "drift unrecorded".
- Every run is resampled onto the UTC 10 Hz grid, and stamps that do not
  join within 2 s start a new run. The files carry no position.

## The ingest keys of `survey.yaml`

These keys of a site entry or of `defaults:` act when the raw archive is
built ("own entry": not in `defaults:`). A key left out does nothing unless
a default is given, and each correction is recorded in the archive's run
comments. After changing a key, rebuild the archive and its filtered
variant:

```bash
python scripts/ingest_site.py <survey.yaml> <site> --force
```

A campaign then runs again every job that reads the site
([campaigns.md](campaigns.md)). Rebuild a site with `h_from` too after a
change to its neighbour's keys or calibration.

| key | what ingest does | when to set it |
|---|---|---|
| `channels` | keeps these channels and drops the rest | the inputs that had a sensor (a LEMI-423's Bz is an open input without a coil); default: all |
| `record_window` | `[start, end]` in UTC: keeps the samples with start <= t < end | another occupation in the folder, or a dead sensor; the entry's `start` and `end` must lie inside it |
| `clock_offset_s` | adds these seconds to every recorded time stamp | a known clock error (-1.0 for stamps 1 s late); own entry, within +/-60 s |
| `dipole_length_ex`, `dipole_length_ey` | the line lengths in m, in the electric chain | from the field sheet. Not applied on a LEMI-424; 0.0 on a Phoenix or MTU-5A site takes the recording's own |
| `azimuth_ex`, `azimuth_ey` | the line directions, in degrees clockwise from the layout's north | from the field sheet; default 0 and 90 |
| `flip_reversed_dipoles` | `true`: a line at 180 (ex) or 270 (ey) is read as wired reversed, its sign flipped. `false`: the sign is kept | once per survey; default `true`. Not applied on Phoenix MTU-5C and MTU-8A sites. Check the phase-quadrant line of the first `process_rr.py` run ([commands.md](commands.md#process_rrpy)): a wrong choice puts one mode 180 deg out |
| the `rot_e` turn (no key of its own) | EDL and LEMI-424: turns an electric pair laid off 0/180 and 90/270 onto magnetic north and east | declare `azimuth_ex`, `azimuth_ey` as laid. Refused on other recorders, under `flip_reversed_dipoles: false` or `layout_north: geographic`, with one line kept, and for a pair over 15 deg from perpendicular |
| `swap_e` | exchanges ex and ey | lines connected to each other's inputs; declare lengths and azimuths as they are after the exchange. Without it a line along the other channel's axis is refused. The tick box "Ex and Ey swapped" on the Metadata tab sets it; then press "Rebuild archive" |
| `swap_h` | exchanges hx and hy, each with its input's filter chain | coils plugged into each other's inputs. The tick box "Hx and Hy swapped" on the Metadata tab sets it; then press "Rebuild archive" |
| `flip_h` | negates the listed channels (of hx, hy, hz), after `swap_h` | a coil cabled reversed: `flip_h: [hy]`. A coil pair turned through 90 deg is `swap_h: true` plus the channel that then reads minus |
| `rot_h` | turns hx and hy of a fluxgate from the sensor's axes onto magnetic north and east. The value is the azimuth of magnetic north from the sensor's x axis toward its y axis, in degrees | a fluxgate not set to magnetic north. `scripts/h_azimuth.py <survey.yaml> --propose` prints it and `--apply` writes it; own entry |
| `rot_h_parts` | `[[start, end, angle], ...]`: turns each part by its own angle and leaves out the samples outside every part | a fluxgate that turned during the record; not with `rot_h` |
| `h_tilt` | `[rx, ry, rz]`, a rotation vector in degrees: levels hx, hy and hz, before `rot_h` | an EDL or Orange Box fluxgate that was not level |
| `h_from` | takes hx and hy from a neighbour's raw files at the site's own time stamps, with the neighbour's calibration and keys; runs the neighbour does not cover are left out | a site that recorded electrics only (`channels: [ex, ey]`); both sites on one recorder (LEMI-423, EDL or Orange Box) and one rate; own entry; refused under half coverage |
| `calibration_fn` | the coil response file | LEMI-423, and EDL with `sensor_type: lemi120`; a relative path is looked for in the survey folder, then `data_root` |
| `h_scale` | a gain on the magnetic chain | LEMI-423: -1000.0 (pT to nT and the sign convention); default 1.0 |
| `e_sign` | the sign of the electric chain, 1.0 or -1.0 | LEMI-424; unset means -1.0 |
| `sensor_type` | the magnetic sensors: `bartington` (fluxgates) or `lemi120` (coils) | EDL; default `bartington`. A coil read as a fluxgate comes out 2800 times too large |
| `electric_gain` | one more gain on the ex and ey chains | EDL: a gain beyond the x10 terminal box, from the field notes. Left out, the apparent resistivity is the gain squared too large |
| `electric_gain_ex`, `electric_gain_ey` | the same on one line alone | EDL; not with `swap_e` |
| `edl_banks_swapped` | stores the `.EX`, `.EY` files as hx, hy and the `.BX`, `.BY` files as ex, ey; no hz | EDL with the magnetometer and electrode cables in each other's banks |
| `time_base` | `headers`, or `nominal`: the reader's own time axis, no drift | Orange Box; `nominal` is for comparison only |

The Phoenix, burst and Orange Box keys are in their sections above. An
unknown key is refused, and so is a Phoenix or Orange Box key in the own
entry of a site on another recorder.

The archive holds the channels on the layout's axes: x to its north, magnetic
north by default. `rot_h`, `rot_h_parts`, `h_tilt` and the `rot_e` turn put a
sensor that is declared off those axes onto them, once, at ingest, and the
archive records each. They are corrections of the layout. Processing applies
no rotation, and the declination (`layout_north` and the `declination` keys,
[products.md](products.md)) is recorded and never applied.

## Instrument registry DOIs

A survey may declare the AuScope instrument registry DOI
(https://pidinst.data.auscope.org.au/) of each site's logger (`logger_pid`),
coils (`sensor_pid_hx`, `sensor_pid_hy`, `sensor_pid_hz`), electrodes
(`electrode_pid`) and deployment (`platform_pid`, also a top-level key), in
a site entry or `defaults:`. A value is a bare DOI (`'10.82388/25jrcc6q'`;
a URL or a `doi:` prefix is refused) or the word `none` for an instrument
the registry does not hold. Ingest writes them into the archive's run and station comments, and `process_rr.py` and
`merge_best.py` into the sidecar's `instrument_pids`, the EDI's INFO block
and the XML's Notes.

`scripts/pidinst_lookup.py <survey.yaml> [--site SITE ...] [--write]
[--responses DIR]` searches the registry by the serials of `survey.yaml` and
prints the matching records. `--write` writes a key only where exactly one
record is left, after a dated copy of `survey.yaml`. `--responses` reads
saved search responses in place of the network.
