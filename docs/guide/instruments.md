# Instruments

This page covers the recorders mt-workbench reads: the files of each, how a
site's recorder is detected, what the reader of each does, the `survey.yaml`
keys that act at ingest, and the instrument registry DOIs.

## The recorders

`mt_workbench.instruments` lists six recorders (the five below and the Orange Box,
`orangebox`), each read by its own mt-io reader and archived under that reader's
channel names (Phoenix renamed to ex ey hx hy hz, the MTU-5A's table channels
stored as ex ey hx hy hz):

| `instrument:` | recorder | files a site folder holds | reader, archive channels |
|---|---|---|---|
| `lemi423` | LEMI-423 broadband | `<unix epoch>.B423` (90 min each) | `mt_io.lemi.lemi423`: hx hy hz ex ey (counts; LEMI-120 coil response and `h_scale` added at ingest) |
| `lemi424` | LEMI-424 long period, 1 Hz | `YYYYMMDDhhmm.txt` (daily) + a `.inf` | `mt_io.lemi.lemi424`: bx by bz e1 e2 e3 e4 (nT; the electrics as recorded, mV, though mt-io labels them mV/km, no dipole length applied) |
| `edl` | Earth Data PR6-24 (UoA interface) | `{station}YYMMDDhhmmss.{BX,BY,BZ,EX,EY}` in day folders + `config/recorder.ini` | `mt_io.uoa.pr624`: hx hy hz ex ey (microvolts; the reader's Bartington, Bz-divider, signed-dipole and x10 terminal-box chain; rate from recorder.ini) |
| `phoenix` | Phoenix MTU-5C / MTU-8A | a recording folder: `empower_recmeta.json`/`recmeta.json` + channel folders of `<rx>_<rec id>_<ch>_<seq>.td_150` (`.td_30`, `.td_24k` bursts) | `mt_io.phoenix` through `mt_workbench.phoenix`: ex ey hx hy hz (volts; chain field to volts: dipole or coil table by serial, on H the polarity stage of gain -1, mV to V, receiver curve) |
| `mtu5a` | Phoenix MTU-5A | per recording `<serial><month><day><letter>.TS4` (150 Hz, continuous) with its `.TBL` table; the `.TS2` and `.TS3` bursts are not read | `mt_io.phoenix.readers.MTUTSN` for the counts, the record tags and the table decoded in `mt_workbench.mtu5a`: ex ey hx hy hz (counts; the table's scalar chain as filters) |

## Detection

A folder under `data_root` is a site when it holds any of
those files anywhere below it (`detect_instrument`, one walk): B423 files ->
lemi423; a 12-digit `.txt` whose first line has the LEMI-424's 24 (or 16)
fields -> lemi424; `recorder.ini` or EDL channel files -> edl; `.td_150`,
`.td_30` or `.td_24k` files with a Phoenix name -> phoenix; `.TS4` files ->
mtu5a. The survey's
own instrument is preferred, so an existing LEMI-423 survey finds exactly the
sites it always did. **The per-site key:** `Survey.instrument_of(site)` is
the site's own `instrument:` if it has one, else what its folder holds, else
the survey's top-level `instrument:`. `scripts/new_survey.py` writes a site's
`instrument:` (and its recorder's default `channels:` preset, since the
survey default's names are not its reader's) only when it differs from the
survey's. `channels:` and `filters.yaml` lists use the reader's names
(`channels: [e1, e2, e3, e4, bx, by, bz]` on a LEMI-424).

## Phoenix MTU-5C and MTU-8A (`instrument: phoenix`)

A site folder holds one
recording folder (or several; `recording:` names one) with
`empower_recmeta.json` and/or `recmeta.json` beside numbered channel folders
of `<receiver>_<recording id hex>_<channel>_<sequence hex>.td_150` (360 s
each), `.td_30` and `.td_24k` (24 kHz bursts). mt-io's Phoenix readers read
the files (the installed fork, `mtproc-fixes` cdceeb3, whose Phoenix code is
upstream v0.0.5 with PR #8): the metadata file is empower_recmeta.json
first, and it gives the channel map per recording (MTU-8A 0 E1 / 2 H2 / 3 H1 /
7 E2, MTU-5C 0 H2 / 1 E1 / 2 H1 / 4 E2), the coil serials and the dipole
lengths. `mt_workbench.phoenix` adds:
- one run per recording, the files read one by one with
  `open_phoenix(fn).read()` and joined only where a file starts at the end of
  the one before (a short or missing file starts a new run; mt-io's
  `read_sequence` would join them and date every later sample early);
- the names ex ey hx hy hz (from E1 E2 H1 H2 H3), so aurora and intersite need
  no channel nomenclature;
- each channel's chain from the field to the recorded volts: the dipole
  (`dipole_<L>m`, mV/km to mV) or the coil table named by the coil serial
  (`phoenix_coil_<serial>`, from `<serial>_*.scal.json`, nT to mV; mt-io
  attaches no coil), on hx hy hz `phoenix_h_polarity` (mV to mV, gain -1:
  the Phoenix records H with the sign of the LEMI-423's recorded H;
  mt-workbench's convention, lemimt's and the LEMI-423 chain's -1000,
  negates H, and this stage puts the Phoenix H into it; upstream issue
  81. The samples stay as recorded, so an archive built by an earlier version
  lacks it, its Phoenix Z sits 180 deg off until re-ingested, and
  process_rr.py and process_intersite.py name it in a warning),
  `phoenix_mv_to_v` (mV to V, in place of mt-io's
  `v_to_mv` of gain 1000, which makes calibrated E and H 10^6 too small;
  replaced only when that is the stage found), and the receiver curve from
  `<receiver>_*.rxcal.json`. Both folders' files come from `calibration_dir:`
  (required). Of several files of one coil or receiver, the latest dated
  (the hex epoch in its name) at or before the recording's start is taken,
  else the earliest after it with a warning, and the channel comment names the
  file and its date, for a converted receiver file also the file its curve
  below the records came from (`phoenix.calibration_for`, upstream issue 84).
  Binary `.scal`/`.rxcal` files (from a
  folder or a .zip) become that JSON with `scripts/phoenix_cal_convert.py
  <source> <calibration_dir>`, which never replaces a file and compares one
  that exists; an `.rxcal`'s curve below its measured points is not in the
  binary and is taken from an EMpower JSON of the same receiver (upstream
  issue 83);
- the coil serial and dipole length from the metadata file unless
  `coil_hx`/`coil_hy`/`coil_hz` or a non-zero `dipole_length_ex/ey` is
  declared; each channel comment names every source (the metadata file,
  recmeta.json, the coil's own report in backend.log) and flags a coil whose
  self-report differs. `polInv` is recorded, never applied (mt-io does not
  read it, upstream issue 54);
- the version-2 second: every stamp of a file of version below 3 is 1 s
  behind GPS (Phoenix DAA09, issue 47), so 1.0 s is added, after checking that
  mt-io's start is its own header arithmetic (a reader that already corrects
  it gets nothing added, any other start is refused). It is recorded as
  `phoenix_stamp_correction_s` in the run, channel and station comments
  (`mt_workbench.phoenix.archive_stamp_correction`), apart from
  `clock_offset_s`, which stays free for a logger's own fault;
- `serial:` checked against the receiver; the header rate checked against the
  site's (`sample_rate: 150` reads `.td_150`, 30 reads `.td_30`); dc levels
  in V with no absolute threshold; `.td_2400` files noted in the run comment
  (mt-io has no reader for them). `h_scale`, `sensor_type`, `electric_gain`,
  `calibration_fn` and `h_from` are refused on a Phoenix site, the Phoenix
  keys on any other. `td_30` is untested (no test recording holds it).
- `scripts/new_survey.py --instrument phoenix` (or a folder detected as
  Phoenix) writes each site's receiver as `serial`, its model, position and
  span from the metadata file and headers, and Phoenix defaults:
  `dipole_length_ex/ey: 0.0` (a non-zero default would override every
  recording's measured lengths), `calibration_dir: sensors` and the aligned
  `min_period` below.

### The bursts as a site of their own

`G5H: {bursts_of: G5, sample_rate: 24000}` (the entry may also hold `remote`, `notes` and `clock_offset_s`;
everything else is G5's, but `clock_offset_s`, which is 0.0 unless G5H
declares one: the bursts carry GPS time, while an offset on G5 corrects the
continuous stream's decimation-filter delay, -0.1148 s at Kalkaroo) is
ingested from G5's folder, one run per burst (`sr24000_00001`, five
digits), every burst of a `.td_24k` file read through mt-io's
`DecimatedSegmentCollection` on a fresh reader (the installed `read_phoenix`
returns the first burst only, issue 44), checked against a walk of the
sub-headers, the channel folders matched by stamp; a last file that ends
inside a burst gives up that burst with a warning (issue 73). The station's
metadata is read once and written once (issue 85): KD-RR_210428H's 7048
runs ingest in about 3 min.
`scripts/ingest_site.py <survey.yaml> G5H` builds it, and `--all` with
it. `start`/`end` take a
window (a station-day is about 2.3 GB). process_intersite reads burst sites
on a compact grid (`intersite.read_bursts`): the bursts the three sites share,
back to back with one NaN sample between them, so no window straddles two
bursts and the memory is the bursts' (about 6 GB a pair-day, not 91 GB).
Stacks are refused there. A site faster than the survey takes the shortest
period of the survey's layout at or above 4 / rate (1/6000 s at 24 kHz and
4**(14/6)/6000 = 0.004233 s at 1000 Hz with 4**(22/6)/6000;
`mt_workbench.bands.site_min_period`; process_intersite and process_rr take
`--min-period`), and a `min_period` below 4 / rate drops the bands above a
quarter of the rate whole, the rest keeping their edges
(`mt_workbench.bands.top_edge`), so one `min_period` serves every rate. With 2 s bursts and the 128-sample
window, the burst telluric tensor reaches 0.00019-0.038 s. Aurora (Z) handles burst
archives only for windows of a few hundred bursts (issue 46).

### One telluric tensor over the ultra-wide band

Two process_intersite runs stitched by
band: the bursts (`G5H G8H --remote G6H`) and the continuous record (`G5 G8
--remote G6`) with the survey's `min_period: 0.026878315731090622`
(4**(22/6)/6000; the full value, a rounded one moves the edges), so the 150 Hz
band edges fall on the 24 kHz ones and the two products share two bands
(0.0269-0.0427 s). `scripts/merge_tensor_bands.py <bursts .json>
<continuous .json>` takes the burst rows below the first shared band and the
continuous rows from it on, and fails (exit 2) when a shared band disagrees
by more than 2 combined sigma (`--accept-disagreement` writes it anyway and
records it), when the edges do not coincide (it prints the aligned
`min_period`), or when the six archives' stamp corrections differ.

A reinstall of mt-io from the fork's `testing` branch (caddfb1, with mth5
`testing` e73d827d) would make `read_phoenix(td_24k)` return every burst and
give a cheap burst index (`mt_workbench.phoenix._read_bursts` is the one call
to change); it also brings three LEMI-423 reader commits, so the LEMI ingest
tests would be rerun. It changes nothing above otherwise.

## Phoenix MTU-5A (`instrument: mtu5a`, `mt_workbench.mtu5a`)

A recording
is a set of files sharing one stem, `<serial><month><day><letter>`
(4573C07A: receiver 4573, 7 December, the day's first recording). The reader
takes each `.TS4` (150 Hz, continuous) under the site folder with the `.TBL`
beside it; a `.TS4` without its `.TBL` is refused. A site folder holds the
recordings of one receiver (of the declared `serial`, when set), any number
of them, and the site's rate is `sample_rate: 150`. The counts come from
mt-io's `MTUTSN.read()`; the record tags and the table are decoded in
`mt_workbench.mtu5a`, because mt-io 0.0.5 reads the position, the start
time, the run boundaries, some table values and the tag status bytes wrong
and labels the units after one scalar (upstream 551-562, 564 and 565).
- Runs: each recording becomes a run, `sr150_0001` and on, in time order,
  starting at its first record's tag. Where the tags step by other than
  1 s, the run ends and the next one starts at the tag after the step, its
  comment carrying an `mtu5a_gap` piece. Refused: overlapping recordings or
  runs, two receivers in one folder, a table whose FTIM is more than 1 s
  from the first tag, recordings whose chain values differ (FSCV, EGN, HGN,
  HATT, HNOM, the dipole lengths and the channel numbers; workbench 137),
  and any record layout other than five channels of 3-byte samples behind
  32-byte tags in whole 1 s records.
- The chain: the archive stores the int32 counts (units "digital counts")
  with the table's scalar chain as filters, physical to recorded: on ex
  and ey the dipole (`mtu5a_dipole_<c>_<L>m`, mV/km to mV, the declared
  `dipole_length_*` or else the table's EXLN/EYLN), EGN and the converter
  (`mtu5a_counts_<FSCV>v`, mV to counts, 2^23 / (1000 FSCV)); on hx, hy and
  hz HNOM (nT to mV, the table's nominal value), HATT, HGN and the
  converter. Each channel comment names the table column it was read from,
  and on H the coil serial (HXSN, HYSN, HZSN), which is not part of the
  chain check (workbench 139).
- The flags: the tags' saturation bits, status byte, clock status and
  clock error are written beside the archive as
  `<archive stem>.mtu5a_flags.csv`, one row per interval (run, recording,
  field, channel, input, value, start, end, records), named in the ingest
  log and counted in the run comment's `mtu5a_flags` piece. The samples are
  stored as recorded; the flags are not applied as masks (workbench 123).
- The dc level of each channel is measured from the samples against an
  absolute rail of 0.9 x 0.941 x 2^23 counts (0.941 of full scale is the
  receiver's clip) and recorded after "dc rail (counts, 90 % of the clip): "
  (workbench 124).
- A site's own entry may set neither the Phoenix keys (`recording`,
  `calibration_dir`, `coil_hx`, `coil_hy`, `coil_hz`), nor the LEMI and EDL
  keys (`h_scale`, `sensor_type`, `electric_gain`, `calibration_fn`,
  `h_from`), nor the Orange Box keys.

What the reader does not do, each a known gap:
- No coil response: the H chain is HNOM alone, frequency independent, so
  Z and the magnetic tensor from MTU-5A magnetics are wrong; the telluric
  tensor (E to E) is not affected
  (workbench 119).
- The `.TS2` (24 kHz) and `.TS3` (2400 Hz) bursts are not read; one log
  line per site names them (workbench 120).
- No H sign stage: no rule says yet whether the MTU-5A records H with the
  MTU-5C's sign (which `phoenix_h_polarity` corrects), so an MTU-5A Z could
  sit 180 deg off (workbench 121).
- No band delay: the tag is taken as the time of the record's first scan.
  The EMpower `.cts` calibration gives the 150 Hz band a common delay of
  0.196 s, if its phase is referenced to the tag time; none is applied. It
  cancels between two MTU-5A sites and not between an MTU-5A and another
  kind (workbench 122).

## Ingest

`ingest_site` reads LEMI-423 on its own path (`calibration_fn`, `h_scale`,
the reversed-dipole flip and `replace` are LEMI-423 keys) and the others through
`mt_workbench.instruments.read_run` (EDL: the site's dipole lengths and, with
`flip_reversed_dipoles`, its azimuths go to the reader, whose dipole filter
carries the sign). `max_run_files` caps LEMI-423 runs only. Each run's
comment records the raw DC level of its electric and magnetic channels
("dc level (median counts, rail %): ex +2.000e+07 0.00 ok, ey +1.600e+09
0.00 open input?", `mt_workbench.dclevel`), classified over the site's channel
runs.

### Coils exchanged or reversed: `swap_h` and `flip_h`

A site whose two horizontal coils were plugged into each other's
inputs sets `swap_h: true` in its survey.yaml entry (default false): ingest
exchanges hx and hy (LEMI-423 and EDL), so the archive's hx holds the
samples of the hy input with that input's filter chain (on a LEMI-423 its
own linear stage, 1/Kmy) and hy the samples of the hx input with its own,
both keeping the coil response and `h_scale`, with normal polarity. The
run comment records "swap_h: hx and hy exchanged, ..." and each channel's
comment the input it holds. A coil cabled with its polarity reversed is
declared with `flip_h` (default none), the list of coil channels whose
samples ingest negates, from hx, hy and hz:

```yaml
sites:
  P9S2:
    flip_h: [hy]        # hy reads minus the field along 90 deg
  P6S3:
    swap_h: true        # coils turned 90 deg: recorded hx = -Hy, recorded hy = +Hx
    flip_h: [hy]        # after the exchange hy holds -Hy
```

It is applied after `swap_h` (every instrument, and a Phoenix burst site
takes its recorded site's), so the names are the channels as they are
after the exchange: a coil pair turned through 90 deg is `swap_h: true`
plus `flip_h` naming the channel that reads minus after it (recorded hx =
+Hy and hy = -Hx is `flip_h: [hx]`). "Reads minus" is against the field
along the channel's own direction (hx 0 deg, hy 90 deg) in the sign the
site's other coils give after `h_scale`. Only the samples change, not the
filter chain; the run comment records "flip_h: hy samples negated at
ingest, after swap_h (declared reversed coil)", one dot-free key piece the
EMTF XML writer accepts (docs/upstream_issues.md 48), and each flipped
channel's comment "flip_h: the samples negated at ingest ...".
`Survey.site` refuses a channel other than hx, hy and hz, one named twice,
one the site's `channels:` does not keep, and hx or hy on a site with
`h_from`, whose borrowed coils carry the neighbour's own `flip_h`. The
filters hash and the variant's name depend on `filters.yaml` alone, so
after changing either key rebuild both with
`scripts/ingest_site.py <survey.yaml> <site> --force` (with `--raw` the
old variant would stay in use). A re-ingest changes the raw archive's
mtime, which is part of `campaign.py`'s resume key, so the campaign runs
again every job that reads the site, as local, remote or stack member.

### A known clock error: `clock_offset_s`

A logger whose GPS time stamps are off by a known amount declares it as
`clock_offset_s`, the seconds added to its recorded stamps at ingest
(default 0.0, which changes nothing):

```yaml
sites:
  RR2:
    clock_offset_s: -1.0   # stamps each sample 1.000 s late: archive time = recorded time - 1 s
```

Every run's start time moves by the offset and the samples are untouched;
the run comment, each channel's comment and the station's
`provenance.comments` record "clock_offset_s: -1.0 s added to every
recorded time stamp at ingest ...", the ingest log says so for each run,
and `mt_workbench.ingest.archive_clock_offset` reads the offset back from
a raw archive or its variant. The key belongs in a site's own entry: it is
refused in `defaults:`, on a derived site (its archive is decimated from
the parent's, which carries the parent's shifted stamps) and on an
observatory, and a value that is not finite or beyond +/-60 s is refused.
An archive built before the key was set keeps its recorded stamps until
it is rebuilt with `--force`; like `swap_h`, the key is not in
`campaign.py`'s resume key itself, and the re-ingest changes the raw
archive's mtime, which is.

### Coils borrowed from a neighbour: `h_from`

A LEMI-423 site that recorded electrics only (its Bx and By inputs open,
dropped by `channels: [ex, ey]`) names a nearby site of the same survey
whose coils it takes, `h_from` (default none):

```yaml
sites:
  E12:
    channels: [ex, ey]   # no coils at this site
    h_from: M07          # 2 km away, four channels, the same 1000 Hz GPS time base
```

The ingest reads the neighbour's raw B423 files, grouped into runs as its
own ingest groups them, with its calibration file and header coefficients,
its `h_scale`, its `swap_h`, its `flip_h` and its `clock_offset_s` (its stamps moved by
its own offset before alignment; the local's offset moves the local's ex
and ey), and takes its hx and hy samples at the local's GPS time stamps one
for one, so the archive's hx and hy are exactly what the neighbour's own
archive holds at those instants, with its chains, azimuths and sensor ids
(the station location stays the local's). A local run the neighbour covers
in part is cut to the covered part, one it covers across a gap or a
boundary of its runs is split there, and one it does not cover is left
out. The run comment records the span and any cut, each borrowed channel's
comment "h_from: hx of M07, 2010 m away, coil 41, logger 41; aligned by
GPS time; the neighbour's clock_offset_s 0.0 applied", the station's
`provenance.comments` the neighbour and every run left out (so a filtered
variant keeps the record), the ingest log one line per run with its span,
and `mt_workbench.ingest.archive_h_from` reads the neighbour's name back.
`Survey.site` refuses the key in `defaults:`, on a site that declares hx or
hy (or no `channels:`), `swap_h`, a `flip_h` naming hx or hy or
`derived_from`, and with a neighbour
that is derived, an observatory, `h_from` itself, declares channels
without hx and hy, or has another sample rate; the ingest refuses, before
touching an existing archive, a neighbour on another sample grid or one
that covers under half of the local's samples. `process_rr.py` needs no
change: the archive then holds ex, ey, hx and hy, and its TF outputs are
the declared ex and ey. Adding or changing the key needs a re-ingest of
the local with `--force`, which changes its raw archive's mtime, part of
`campaign.py`'s inputs signature, so every campaign job that reads the
site runs again; a re-ingest of the neighbour does not reach the local's
archive, so re-ingest both after changing the neighbour's calibration,
`swap_h`, `flip_h` or clock offset.

### Speed, and what is not wired

One hour ingests
in about 1.4 s (LEMI-424) and 1.1 s (EDL). **Processing** a LEMI-424 site
needs aurora's electric-channel nomenclature (LEMI12/LEMI34) in
`mt_workbench.process`, not added yet; `timing_qc.py`, `psd_qc.py --before` and
`noise_psd.py` still read B423 files only. `build_stack.py` reads each
member's MTH5 archive (its `hx`/`hy`, so LEMI-423 and EDL archives, not a
LEMI-424's `bx`/`by`); a member without an archive has to be built first.

## Instrument registry DOIs

The keys are `logger_pid`, `sensor_pid_hx`, `sensor_pid_hy`,
`sensor_pid_hz`, `electrode_pid` and `platform_pid`. The AuScope instrument
registry (https://pidinst.data.auscope.org.au/) gives each logger, coil and
survey deployment (a "platform") a PIDINST record with a DOI under 10.82388.
A survey says which instrument recorded where by these keys, in a site entry
or `defaults:`, and `platform_pid` also at the top level of survey.yaml (a
site's own winning, for a survey that spans two deployment records). A value
is a bare DOI, `10.<prefix>/<suffix>` (`logger_pid: '10.82388/25jrcc6q'`;
a URL or a `doi:` prefix is refused), or the word `none` for an instrument
the registry does not hold, with the reason in the site's `notes:`. A
fluxgate inside a logger's record (the Orange Box) has no sensor key; no
electrode is registered yet. Ingest and processing fetch no record:
the keys are what the survey declares, and `Survey.instrument_pids(site)`
resolves them (a derived site takes its parent's, a burst site its recorded
site's, and a site with `h_from` adds `logger_hx_hy`, the neighbour's
logger, with the neighbour's hx and hy sensor DOIs). Where they go, each
only when a key is declared:
- the archive: every run comment and the station's provenance comment get
  one piece `instrument_registry: logger <doi>, sensor_hx <doi>, ..., platform
  <doi>` (re-ingest to add it to an existing archive; the products below do
  not need it);
- `process_rr.py`: the sidecar's `instrument_pids` (`local` and `remote`, each
  `{site, pids}`; a stacked remote `{site, members: {site: pids}}` from the
  stack's recorded provenance), the dry run's `instrument_pid.local:` and
  `instrument_pid.remote:` lines, the EDI's INFO block one line per
  instrument (`mt_workbench.instrument_pid_local_logger=10.82388/25jrcc6q`,
  `..._remote_member_<site>_logger=...` for a stack's members; underscores,
  since mt_metadata's EDI reader keeps only the last part of a dotted key,
  upstream 115), and a sentence in the XML's Notes naming each DOI as an
  https://doi.org/ link (`mt_workbench.products.pid_sentence`, read from those
  INFO lines, so any product carrying them gets it);
- `merge_best.py`: the merged EDI keeps its base's (the first xy source's)
  lines and adds, as `mt_workbench.instrument_pid_src<k>_<role>=<doi>`, each
  DOI of another source (k its place in the sidecar's `sources`) from which
  a period was taken and which the base does not carry; the sidecar's
  `instrument_pids` records both.
`scripts/pidinst_lookup.py <survey.yaml> [--write]` proposes the keys from the
serials survey.yaml holds (`serial`, `coil_hx/hy/hz`): it searches the
registry by serial, keeps the records whose SerialNumber is the serial and
whose model is the site's instrument (a serial is not unique across makers:
10307 is an Orange Box and a Phoenix MTU-5C), prints their service dates
against the site's span, and with `--write` writes a key only where exactly
one record is left, the standing way (dated copy, one inserted line per key,
parsed diff and comment count checked). The registry is read only.
