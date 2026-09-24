# Upstream issues found while building this workflow

Running log of bugs/quirks to report or fix in the community packages
(mt-io, mth5, mt-metadata, aurora). Add an entry whenever we work around
something here; remove it when the upstream fix lands and the workaround is
deleted.

## mt-io

### 1. `lemi423.read_lemi_coil_response` unit names fail mt_metadata validation
- **Found:** 2026-09-21, mt-io 0.0.5 with mt_metadata 1.0.10
- **Symptom:** passing `calibration_fn` to `read_lemi423` raises
  `KeyError: "Unit 'millivolts' not found in the UNITS_DF DataFrame"` at
  `lemi423.py:313` — so the coil-response path can never have run on this
  stack combination.
- **Fix:** `fap.units_in = "nanoTesla"`, `fap.units_out = "milliVolt"`
  (registry accepts camelCase singular; lowercase "nanotesla" passes only by
  case-insensitive lookup, "millivolts" fails on the plural).
- **Workaround here:** `mtproc.ingest._read_coil_response` monkeypatches the
  function; delete once fixed upstream.
- **Retired (2026-09-24):** fixed on the mt-io fork (branch `mtproc-fixes`,
  "Make the LEMI-423 coil response chain valid"); `mtproc.ingest` no longer
  patches mt-io.

### 2. `lemi423` magnetic filter-chain units are dimensionally doubled
- **Found:** 2026-09-21, mt-io 0.0.5
- **Detail:** the linear calibration filter is labelled `nanoTesla -> count`
  (i.e. the K coefficient already yields nT), but the coil response filter is
  labelled `nanoTesla -> milliVolt` on top of it. The .rsp amplitudes are
  normalized (~1 in passband), so numerically it acts as a deconvolution, but
  the declared units chain is inconsistent — mt_metadata's
  `ChannelResponse._check_consistency_of_units` rejects it ("input units for
  lemi_120_*_response should be digital counts not nanoTesla"). Proper fix:
  order the chain physical->archived as [coil nT->mV (or nT->nT if
  normalized), linear mV->count] with matching labels. Our shim instead labels
  the coil filter `digital counts -> digital counts` (dimensionless shape
  correction) to fit the reader's existing order. Retired 2026-09-24: the
  mt-io fork labels the table nT -> nT and puts it ahead of the linear stage,
  which is the fix above; the shim's labels conflicted with that order.
- **Resolved empirically (2026-09-21, D02 RR E08 vs merged lemimt EDI):** the
  reader's "nT" magnetics are actually **pT with inverted polarity** relative
  to the lemimt convention — rho came out a constant 1.0e6 low (|Z| factor
  986 ~ 1000) with both phase modes exactly 180 deg off. Fix in mt-io: make
  the linear magnetic calibration filter gain a factor -1000 different (or
  correct the labelled units to picoTesla and document the polarity). Until
  then `mtproc.ingest._apply_h_scale` appends an explicit CoefficientFilter
  (gain -1000, `h_scale` in survey.yaml) to each magnetic channel.

### 3. Electric channels with no dipole length only warn
- **Found:** 2026-09-21, mt-io 0.0.5
- **Detail:** without `dipole_length_ex/ey` kwargs the E channels calibrate to
  electrode voltage, with only a log warning. Fine as a default, but consider
  making the resulting units metadata reflect that (channel still claims MT
  field units downstream). Low priority.

### 4. `lemi423` reader discards the per-sample GPS status columns
- **Found:** 2026-09-22, mt-io 0.0.5
- **Detail:** each 30-byte B423 record carries `sync` (int8, deviation from
  PPS) and `stage` (uint8, PLL accuracy). `Read_Lemi_Data` names them in the
  dtype but drops them before returning. They are the only in-band record of
  GPS lock quality, so timing QC (e.g. for the Burra "Behind" flags) has to
  re-read the raw file. Suggest exposing them (e.g. an optional `gps_summary`
  or as run metadata: fraction of samples with `sync != 0`, distinct `stage`
  values). Low priority; not a correctness bug.

### 5. mth5: `KernelDataset.from_run_summary` opens the local archive read-write

Found 2026-09-23 while building an aurora config for a test. `RunSummary.from_mth5s` opens every archive through `initialize_mth5(path, mode="a")`, and `KernelDataset.from_run_summary` opens the local station again through `MTH5().open_mth5(path)`, whose default mode is also read-write. Two consequences: (1) a config cannot be built while another process (the GUI, a test) holds the archive open read-only, because HDF5 file locking refuses the read-write open (`OSError: unable to lock file`); (2) every processing run touches the archive's modification time even though it only reads metadata. The content is unchanged (checked with an independent h5py read of samples). Workaround, now in production (2026-09-23, after a run failed with `unable to lock file` while the GUI held the remote's archive): `mtproc.process` forces `run_summary.initialize_mth5` to read-only and wraps the kernel-dataset build in a scoped `MTH5.open_mth5(mode="r")`; aurora's own opens are already read-only when no Fourier coefficients are saved (`get_mth5_file_open_mode`). The tests use the same monkeypatches. Worth an upstream request for a read-only mode on both.
**Retired (2026-09-24):** the mth5 fork (branch `mtproc-fixes`, "Open archives read-only for run summaries and kernel datasets") opens both read-only; `mtproc.process` patches nothing, and `tests/process_rr_cli_unit.py` builds a config while holding both archives open read-only.

### 6. `lemi423` header parser fails on four-digit altitudes (`%Alt1060.0,m`)

Found 2026-09-23 building the Morocco Atlas survey. LEMI-423 firmware 2.1 writes
the altitude line with a fixed field width, so once the value has four digits
there is no space after the tag: `%Alt1060.0,m 12 1` (three-digit values read
`%Alt 125.2,m 12 1`, two-digit `%Alt  27.1,m 12 2`). `Read_Lemi_Header._extract_coordinates`
takes `header[11].split(",")[0].split()[-1]`, which is `'%Alt1060.0'`, and
`float()` raises `ValueError: could not convert string to float: '%Alt1060.0'`.
`read_lemi423` therefore refuses every file of every site above 1000 m: 47 of
the 103 Morocco sites. Reproduction: the header lines above with any B423 body.
Workaround: `mtproc.ingest` installs a tolerant `_extract_coordinates` that
retries with a space inserted after `%Alt` (unit test
`tests/ingest_unit.py::test_glued_altitude_header_line`). Suggested fix
upstream: strip the `%Alt` tag before splitting, e.g.
`header[11].split(",")[0].replace("%Alt", "").strip()`.
Retired 2026-09-24: the mt-io fork makes that fix ("Parse LEMI-423 altitudes
of four digits"); `mtproc.ingest` no longer patches the parser, and the same
unit test now checks mt-io's own.

### 7. `LEMICollection.to_dataframe` drops every LEMI-423 file by default

Found 2026-09-23. `LEMICollection(folder, file_ext=["B423"]).to_dataframe()`
returns an empty frame and logs only "No entries found for LEMI collection",
after reading every file's header and summary (22 s for one Morocco site).
Cause: `to_dataframe(sample_rates=None)` sets `sample_rates = [1]` (the
LEMI-424 rate) and then `if sample_rate not in sample_rates: continue`
silently skips each 1000 Hz file. Passing `sample_rates=[1000]` returns the
files. The docstring's own LEMI-423 example passes `[1000]`, so the default is
the trap: a LEMI-423 folder listed with the documented `file_ext=['B423']`
yields nothing and no per-file message. Suggested fix: default to the
instrument's rates when `file_ext` names B423 files, or warn per skipped file
with its rate. Not used by this repo (mtproc.ingest lists files itself), logged
for students who try mt-io's collection directly.

### 8. `lemi423` sample-rate detection returns None silently for a faulty file

Found 2026-09-23 on Morocco site R05 (the remote's fifth deployment, 393 h
over 16 days), whose files hold one record per second with the millisecond
tick always 0 (5400 records in a 5400 s file). The LEMI-423 has no 1 Hz mode
(owner), so this is an instrument fault, and mt-io's reaction is reasonable:
`Read_Lemi_Data` derives the rate as `tick_max + 1`, gets `tick_max == 0`,
and returns `sample_rate = None`; `read_summary()` the same; `LEMICollection`
then skips the file. What is missing is a message: nothing says why the file
was dropped, and a student sees only an empty collection. Suggested fix
upstream: warn with the record count per second when `tick_max == 0`. Also
worth checking upstream: the tick-plus-one formula assumes the tick is a
millisecond counter that coincides with the sample index, which only holds
at 1000 Hz (500 and 250 Hz files were not available here to test).
Workaround: `scripts/new_survey.py` counts records per second itself and
reports a non-LEMI rate as measured with an instrument-fault warning.

### 9. mth5: "Channel run.id a != group run.id sr1000_0004" warning on every channel

Seen 2026-09-23 on every ingest (four warnings per run, one per channel):
`mth5.groups.run | from_runts | Channel run.id a != group run.id sr1000_0004.
Setting to ch.run_metadata.id to sr1000_0004`. The RunTS the mt-io reader
builds carries the reader's default run id (`a`), and `RunGroup.from_runts`
corrects each channel's run id to the group's. Harmless, but it fills a
student's log with 120 identical lines for a 30-run site. Suggested fix
upstream: correct the id once per run (or only warn when the channel id is
not the default), or let `from_runts` take the run id it should stamp.
Workaround: none needed; the lines are cosmetic.

### 10. mth5 / mt_timeseries: `ChannelTS` builds the time index with the rate rounded to an integer

Found 2026-09-23 reading Stuart Shelf 2009 Orange Box files (mt_timeseries 0.0.2, mt-io
0.0.5, mth5 0.6.9, mt_metadata 1.0.10). When data are first given to a `ChannelTS`, the
`ts` setter builds the index with `make_dt_coordinates(self.start, self.sample_rate, n)`,
and `ChannelTS.sample_rate` returns `np.round(sr, 0)` for any `sr >= 1` while the channel
has no data yet (channel_ts.py, the `sample_rate` property, the `has_data()` False branch).
`make_dt_coordinates` itself is right (10.00064 Hz gives a 99,993,600 ns step). So the
channel metadata keeps the true rate but the index steps at the rounded one:

```python
import numpy as np
from mt_timeseries import ChannelTS
from mt_metadata.timeseries import Magnetic
for sr in (10.00064, 1.5, 2.5, 1000.4):
    m = Magnetic(component="hx", sample_rate=sr); m.time_period.start = "2009-06-16T02:01:04+00:00"
    ch = ChannelTS("magnetic", data=np.zeros(36000), channel_metadata=m)
    t = ch.data_array.time.values
    print(sr, ch.channel_metadata.sample_rate, (t[1] - t[0]) / np.timedelta64(1, "ns"))
# 10.00064 -> step 100,000,000 ns (10 Hz); 1.5 -> 500,000,000 ns (2 Hz); 2.5 -> 2 Hz; 1000.4 -> 1 kHz
```

Consequence: `mt_io.uoa.read_orange` computes 10.000640 Hz from the filter point, and the
RunTS it returns (and every archive built from it) steps at exactly 0.1 s; `run.sample_rate`
then reads 10.0 from the index, and `RunTS.validate_metadata` logs at CRITICAL "sample rate
of dataset 10.0 does not match metadata sample rate 10.000640040962622 updating metatdata
value to 10.0" and adopts the rounded rate. Over a 69 h Orange Box deployment that is 16 s of timeline
against the reader's own rate, and against the Alice Springs observatory the archived axis
drifts +6 to +15 s at four sites
(D:/MT_DATA/MT_Stuart_Shelf_2009_Workspace/qc/orange_timing_summary.png, curve A). A 1.5 Hz
record would be indexed at 2 Hz. Suggested fix: build the index from the unrounded rate
(round only for display), or refuse a data assignment whose metadata rate and index rate
disagree. Regression guard: tests/orangebox_unit.py, which since 2026-09-24 asserts the
fixed behaviour of the mt-timeseries fork (branch `mtproc-fixes`, "Keep non-integer sample
rates in the time index and metadata"): the Orange Box rate kept, the index stepping by
99,993,600 ns.

### 11. mt-io `uoa.orange.read_orange` joins files without checking that they are contiguous

Found 2026-09-23 (mt-io 0.0.5). `OrangeReader.read` concatenates every file's samples
behind the first file's start stamp. Each Orange Box file carries its own start (header
line 2) and end (a 26 byte trailer, `" Tue Jun 16 03:01:04 2009\n"`, after the last
record, which the reader never reads); neither the later starts nor any trailer is
compared. Two files two hours apart become one run whose end is 2 h early, with no
message; a missing hourly file would shift every later sample by an hour. Reproduction:
write two synthetic files 2 h apart in the documented layout (tests/orangebox_unit.py,
`write_orange_bin`) and read them together. At Stuart Shelf the 16 trip-3 sites happen to
be back to back (start of file n+1 == start of file n + 36000 samples at 10 per RTC second
within the 1-2 s the truncated whole-second stamps allow, 1,089 files, qc/orange_stamp_scan.csv), but the logger report of ST61 (HFM1-RPT.TXT) lists a 70th file,
HFM1-069.BIN (35 min), that is not in the folder: had a middle file been the one lost, the
reader would not have said so. Suggested fix: read the trailer, split into runs where a
start differs from the previous end by more than a sample, and warn.
Fixed on the mt-io fork (branch `mtproc-fixes`, "Refuse Orange Box files that do not
join"): `read_orange` reads the end stamp and raises where a file does not start within
2 s of the previous one's end; tests/orangebox_unit.py asserts the refusal.

### 12. mt-io `uoa.orange`: the time axis ignores the logger's own stamps and the field GPS drift

Found 2026-09-23 (mt-io 0.0.5). The reader times a whole deployment from the first file's
start and the nominal rate 1e7/(512*filter_point) = 10.00064 Hz (which issue 10 then rounds
to 10.0). The Orange Box has two clocks: the ADC's, whose true rate varies by box (the file
stamps give 10.00000 to 10.00058 Hz: HFM1 10.00000-10.00004, HFM4 10.00030-10.00033, HFM5
10.00040-10.00041, HFM3 10.00048-10.00050, HFM2 10.00056-10.00058, consistent per box over
three deployments), and the RTC that stamps the files, which drifts against GPS (the field
sheet's `Drift_GPS-Inst` at recovery and `param.mt` line 10, "time difference (GPS actual -
instrument)": -8 s for HFM1 at ST61, -9 s HFM4, 0 HFM2, +1 HFM5 and HFM3). Independent check
against the GPS-timed Alice Springs observatory (1 s X against the site's hx, lag of the
correlation peak in 4 h windows, 30-600 s band; the test fails if the fitted lag changes by
more than 2 s over the deployment): the RunTS axis drifts +7.5, +6.3, +14.9, +13.2 s at ST61,
ST62, ST63, ST64; the reader's intended 10.00064 Hz axis -6.8, -7.9, +1.0, -0.7 s; the file
stamps alone +6.5, -2.8, +7.1, +1.0 s; the stamps plus the field drift spread linearly -0.7,
-1.9, -0.8, +1.0 s, the only axis that passes at all four
(D:/MT_DATA/MT_Stuart_Shelf_2009_Workspace/scripts/orange_timing_vs_asp.py,
qc/orange_timing_summary.png). The legacy mt_convert.exe used the stamps (10 samples to the
second) plus the param.mt drift. For a single-site or remote-reference impedance a slowly
varying offset largely cancels; for inter-station transfer functions, array work and any
overlay of two sites on one time grid it does not. Suggested fix: fit the time axis to the
per-file start stamps and the last trailer stamp, and take an optional `clock_drift_s`
(GPS - instrument at recovery, as param.mt holds) applied linearly.

### 13. mt-io `uoa.orange`: the electric full scale cannot be chosen through `read_orange`

Found 2026-09-23 (mt-io 0.0.5). `create_orange_electric_filter(component, dipole_length,
full_scale_uv=100000)` supports the +/-2.5 V boxes (25,000 uV), and the module docstring
says boxes before the rewiring recorded +/-2.5 V, but `OrangeReader.read` never passes
`full_scale_uv` and takes no keyword for it, so every file is calibrated at 100,000 uV. The
legacy Fortran (mt_transform.for, Goran Boren's note of 1 July 2010: "New Batch of Orange MT
Boxes have electrics set to +-10V (instead of 2.5V)") and the 2009 logger's own report
(HFM1-RPT.TXT prints ex/ey as volts on a 2.5 V full scale) put every pre-July-2010 file at
25,000 uV; the 2003 mt_convert.exe output for Stuart Shelf 2009 is exactly mt-io's E / 4 at
all four sites checked (tests/orangebox_unit.py; qc/ST61..ST64_hour_channels.png). That is a
factor 16 in apparent resistivity. An independent check (legacy birrp EDIs of the 16 Orange
Box sites against their two nearest PR6-24 sites, magnetic scale corrected, median det-rho
ratio 30-3000 s: 0.24 with 25,000 uV, i.e. 3.8 with 100,000 uV; qc/orange_e_scale_vs_edl.png)
sits between the two and does not settle it (static shift, 15-20 m against 40-45 m dipoles,
the PR6-24 chain's own assumptions), so the reader must let the user say which. Suggested
fix: an `electric_full_scale_uv` keyword (or a date rule with an override).

### 14. mt-io `uoa.orange`: the magnetic full scale is hard-coded to 70,000 nT

Found 2026-09-23 (mt-io 0.0.5). `create_orange_magnetic_filter` has no full-scale argument
and `BARTINGTON_FULL_SCALE_NT = 70000.0` applies to every file. The full scale is a property
of the Bartington sensor, not the box (the owner's fluxgate register,
D:/BEN/AusMT_2026/fluxgate_register, and the legacy Fortran's note that there was "1 off
100uT Bartington sensor"). Test at Stuart Shelf 2009 (|F| of the first hour against IGRF-13,
rotation invariant; fails outside 0.95-1.05): 13 of 16 Orange Box sites read 0.99-1.03; the
three that used sensor 1378 (ST61 HFM1, ST75 and ST92 HFM3) read 0.702-0.708 = 1/1.4286, so
1378 is the 100,000 nT unit (qc/fluxgate_total_field.png, .csv). With 70,000 nT their B is
0.7 of the truth and rho 2.04x too high. Historical note for the same survey: the 2003
mt_convert.exe applied 100,000 nT to boxes HFM2 and HFM5 (a box rule), so the legacy ASCII
and EDIs of the 7 HFM2/HFM5 sites (ST62, ST64, ST73, ST77, ST82, ST85, ST91) carry B x1.4286
(legacy/mt-io slope 1.42857 on all three components at ST62 and ST64) and rho /2.04, while
ST61/ST75/ST92 carry rho x2.04. Suggested fix: a `magnetic_full_scale_nt` keyword per site.

### 15. mt-io `uoa.orange`: silent defaults and dropped channels

Found 2026-09-23 (mt-io 0.0.5). `read_orange` documents `station_id` as required but uses
"OrangeBox" when it is missing, and uses 100 m dipoles, latitude/longitude 0 and elevation 0
without a message; the Stuart Shelf Orange Box dipoles are 12-20 m, so a forgotten length
makes E 5-8x too small with no warning (compare issue 3 for the PR6-24 reader). Channels 3,
4 (16 bit) and 5 (8 bit) are decoded and discarded; the logger's report prints channel 5 as
the temperature (19.75 falling to 4.71 over the ST61 deployment, HFM1-RPT.TXT), useful as an
auxiliary channel. Each file is also logged twice at INFO ("Read 36000 samples from ...", by
`read_samples` and by `read`), 138 lines for one 69-file site.

### 16. mt-io `uoa.pr624`: the Bz divider ratio 0.4 does not fit the Stuart Shelf 2009 PR6-24 kit

Found 2026-09-23 (mt-io 0.0.5); an observation that needs a hardware check before any code
change. Through pr624's chain (142.857 uV/nT, Bz behind a 15k/10k divider = 0.4) the first
hour of 18 trip-3 PR6-24 sites (six Bartington sensors, six interface boxes) reads horizontal
|H| 1.02x IGRF (median) but Z 1.109x IGRF (median; 1.08-1.15), and |F| 1.09x. The Orange Box
sites beside them read Z 1.0x. A 15k/12k divider (ratio 0.444) would give exactly 1.11. Trip
1 and 2 hours (ST01, ST19) show the same (Z/IGRF 1.12, 1.16). If the ratio is really 0.444 for
this kit, every PR6-24 tipper from it is 11% too large. Evidence:
D:/MT_DATA/MT_Stuart_Shelf_2009_Workspace/qc/fluxgate_H_Z_ratios.csv and
fluxgate_total_field.png. One site (ST80, ANT4, sensor 1184) reads Bz positive (+20,300 nT),
a wiring or orientation fault for the field sheet, not the reader.


**Owner's verdict (2026-09-23):** the 0.4 Bz divider as set up in mt-io is correct; the 2009 Stuart Shelf conversion's 0.4545 is not to be copied. No change to mt-io or mtproc.

### 17. mt_timeseries `RunTS` gives its station a phantom `auxiliary_default` channel

Found 2026-09-23 (mt-timeseries 0.0.2, mth5 0.6.9) while writing observatory archives
(`mtproc.observatory.to_mth5`). `RunTS(array_list=[hx, hy, hz], station_metadata=Station(id=...),
run_metadata=...)` returns `run_ts.station_metadata.channels_recorded == ["auxiliary_default"]`
although the run holds three magnetic channels and no auxiliary one; copied into the station
group (`station_group.metadata.update(...)`) it is written to the archive, and
`StationGroup.update_metadata()` then unions it with the runs' components
(`["auxiliary_default", "hx", "hy", "hz"]`). A reader-built RunTS does not show it (its station
lists its channels). Workaround in `to_mth5`: set `run_ts.station_metadata.channels_recorded`
to the channel list before the station metadata is copied. The channel summary aurora reads is
unaffected. Retired 2026-09-24: the mt-timeseries fork (branch `mtproc-fixes`, "Drop the
placeholder channel from a RunTS station's channel list") fixes it; `to_mth5` no longer
overrides the list, and tests/observatory_unit.py asserts the station lists exactly hx, hy, hz.

### 18. mt-io `uoa.pr624.UoAReader.read` writes a mis-dated run from a file list that is not contiguous

Found 2026-09-23 on Hillside phase 1 (PR6-24 at 1000 Hz, ASCII, 5-minute files; mt-io 0.0.5).
Given a list of files (one run's, the way a caller hands them over), `read()` joins each
channel's files end to end, trims every channel to the shortest and dates the whole from the
first stamp. When the list is not contiguous it only warns ("BX: 1140.0 s missing between files;
samples after a gap will be dated early. Use UoACollection to split the deployment into runs.")
and returns the RunTS anyway, so an archive is written with wrong times. Reproductions, archive
against the raw file stamped at the same time with h5py and numpy
(D:/MT_DATA/MT_Hillside_2012_Workspace/qc/step2_hs058_alignment.png, scripts/check_alignment.py):
(1) a channel file missing mid-run -- hs058 has no EX at 2012-03-27 15:35: the archived ex at
15:40:00 and at 20:00:00 equals the files stamped 15:45 and 20:05 (8 h of ex 300 s early; hx,
hy, ey right); the warning then says "300.0 s missing" for all five channels, since it is
computed after the trim, and does not name the channel that lacks a file; (2) 15 s files
stamped 300 s apart at startup (hs058 02:00-02:20, and at 10 other phase 1 sites): the 02:05,
02:10, 02:15, 02:20 files sit at 02:00:15, :30, :45 and 02:01:00; (3) two files with one stamp
for a channel (hs061: a test recording under old/ carrying the real files' stamps) are both read
in. `UoACollection._run_boundaries` gets all three right (per-channel sample counts; duplicates
warned) -- the reader's own list path does not. Suggested fix: with a file list, refuse or split
at any per-channel discontinuity (the collection's rule), and name the channel in the warning.
Workaround here: `mtproc.ingest` groups EDL files itself (`_incomplete_stamps`: exactly one
file per channel per stamp; `_edl_runs_by_samples`: a stamp joins the run only where the
previous files end, by sample count) and `mtproc.instruments._edl_own_files` keeps only the
files named for recorder.ini's station (HSSL09's folder holds 115 stamps of another survey's
PLB03 from 2012-04-29); tests/ingest_unit.py. Not handled, for the record: hs061's old/ folder
also holds HS061-named files at 11:20:46 and 11:21:00 that overlap its real 11:20 file in time;
they become short runs overlapping the real one.

### 19. mt-io `uoa.pr624`: broadband (LEMI-120) chain -- a silent fluxgate default and a stale 200 mV/nT note

Found 2026-09-23 on Hillside phase 1 (LEMI-120 coils on the PR6-24, 1000 Hz; mt-io 0.0.5).
(a) `UoAReader(sensor_type="bartington")` is the default at any rate, with no message, so a
1000 Hz coil record read without `sensor_type="lemi120"` is calibrated with the Mag-03's
142.857 uV/nT: B 2800x too large and no coil response. hs005 RR hs058 through aurora came out
with rho 1.9e-7 of Stephan Thiel's BIRRP result at 0.006-1 s, falling off as 1/f^2 beyond, and
phases up to 70 deg off (qc/step4_hs005_asis_bartington_vs_birrp.png, qc/step4_hs005_ratio.png).
The UoA field notes set coils at 500/1000 Hz and fluxgates at 10 Hz; a warning when a rate of
100 Hz or more is read with the fluxgate chain would have caught it. (b) With
`sensor_type="lemi120"` and the normalized l120n.rsp, the result matches BIRRP: median rho ratio
1.04 (xy) and 1.08 (yx), phase +1.6 and +0.7 deg over 0.006-22 s (qc/step4_hs005_ratio.png), so
`LEMI120_SENSITIVITY_MV_PER_NT = 400.0` (400,000 uV/nT) is right for these coils -- but
`create_lemi120_dc_gain_filter` says "# 200,000 uV/nT (forward)" in its code and writes
"LEMI-120 flat-band sensitivity: 200 mV/nT" into the filter's `comments`, which every archive
carries as provenance. Suggested fix: correct the note to 400 mV/nT. (c) A coil file that fails
to read (`_create_magnetic_filters`) is logged and the channel gets no response at all, which is
worse than failing. Workaround here: the survey's `sensor_type:` (EDL sites), passed to the
reader by `mtproc.instruments.read_run`, which also refuses a chain without the asked sensor's
filter; `scripts/new_survey.py` writes `sensor_type: lemi120` for an EDL survey at 100 Hz or more.

### 20. mt_metadata `Band.set_indices_from_frequencies`: a band with no FFT harmonic is a bare IndexError

Found 2026-09-23 (mt_metadata 1.0.10, aurora via `ConfigCreator.create_from_kernel_dataset`)
processing Stuart Shelf ST63 at 10 Hz with a band layout whose second band on every level
(e.g. 0.1575-0.1984 Hz at 10 Hz with a 128-point window, df = 0.078 Hz) falls between two
harmonics. `Processing.assign_bands` calls `band.set_indices_from_frequencies(frequencies)`,
which does `indices = np.where(...)[0]; self.index_min = indices[0]` and stops with
`IndexError: index 0 is out of bounds for axis 0 with size 0`, naming neither the band, the
decimation level nor the window. Reproduction: `Band(frequency_min=0.1575, frequency_max=0.1984)`
then `set_indices_from_frequencies(np.fft.rfftfreq(128, 0.1))`. Suggested fix: raise a
ValueError that names the band edges, the level and the harmonic spacing (or drop the band
with a warning). The layout itself was mtproc's (`lemimt_band_scheme` accepts a top band
1.6 harmonics up; reported to the coordinator, not upstream).

### 21. mt-io `uoa.pr624`: the PR6-24's per-channel gain is not modelled -- a high-gain channel reads 10x too large

Found 2026-09-23 on Stuart Shelf trip 2 (PR6-24 at 10 Hz, Bartington fluxgates, ASCII files, no
recorder.ini; mt-io 0.0.5), against the PR6-24 manual EDM 021 Issue 6 (Apr 2004,
the Earth Data logger manual, Instruction Manual EDM021 V6). What the manual says: each channel has two
pre-amplifier gains, full scale 8.388 V and 838.8 mV (p7, 1.2); low gain is 1 uV per bit and
high gain 100 nV per bit (p57, header bytes 58-59, a per-channel bit mask); recorder.ini selects
it per channel, `channel_xx_high_gain=0|1`, default low (p36, 4.2.8); a unit is delivered with
"Pre-amp gain of unity" (p23). The stored 24-bit word "represents the seismometer output in
microvolts (0.000001 volts) per bit" (p51, 7.1.1) and an ASCII value is "one sample in the range
-8000000 to 8000000 whose resolution is in microvolts" (p52, 7.1.4), i.e. the word, while 4.2.9
(p36) says of `ascii` "The magnitude of each value is in microvolts": the two agree only at low
gain; at high gain a word is 0.1 uV. What pr624 has right: 24 bits, 8.388 V / 838.8 mV
(`ADC_LOW_GAIN_FULL_SCALE_V`, `ADC_HIGH_GAIN_FULL_SCALE_V`), 1 uV per word at low gain; the
Bartington 142.857 uV/nT, the x10 terminal box (`E_TERMINAL_BOX_GAIN`, settable as
`efield_gain`) and the Bz divider are UoA interface hardware the manual does not cover. What it
does not model: the gain. The two full-scale constants are never used; the module comment
"ASCII is written already scaled to microVolt (EDM 021 4.2.9), so gain selection changes
resolution, not units" reads 4.2.9 alone; `UoACollection.read_recorder_ini` folds
`channel_n_high_gain` (n = 0-5) into one boolean `high_gain` that nothing reads; `UoAReader` has
no per-channel gain argument, so a site without recorder.ini (every trip-2 folder) cannot declare
one. Evidence: the 2009 processing's merged 1 s files (process/merged/stNN.*) of ST19, ST20 and
ST21 are the raw words decimated 10:1 and scaled, B horizontal 1.0000 x pr624's (rotated, a
per-site angle), Bz 0.880 x, E 0.1000 x pr624's (rotated by the declination, sign reversed) at
all three (D:/MT_DATA/MT_Stuart_Shelf_2009_Workspace/qc/trip2_E_H_scale_vs_2009.png, .csv): E =
word x 0.1 uV / (10 L), high gain on the electric channels and low on the fluxgates (a 3.4 V
fluxgate output does not fit 838.8 mV). Through pr624 as it is, aurora's ST19 rr ST21 has 86x
(xy) and 159x (yx) the 2009 birrp apparent resistivity with the phases within 1.5 and 5.5 deg;
with E / 10 and the 2009 rotations 1.03x and 1.01x, phases within 0.7 deg
(qc/ST19_rr-ST21_vs_2009_frame.png); ST21 rr ST19 0.98x and 1.02x. pr624's reading cannot hold
with high gain in any case: E words reach 2,235,552 (ST22), above the 838,800 uV a high-gain
channel spans in microvolts. Hillside's broadband PR6-24 (issue 19 b) matched BIRRP with the
low-gain reading, so the gain varies between deployments and has to be declared or read. Not
settled from these files: the field sheet's "Gain" column (Low on 78 of 79 Stuart Shelf rows,
"V. Low" once) is not the PR6-24's low/high (trip-1 notes call a -6 V fluxgate reading "off
scale ... should have been v.low", which low gain would hold). Suggested fix: apply the gain
per channel as a filter in the chain ("pr624_high_gain", 10 words per uV), from recorder.ini's
`channel_n_high_gain` through the channel map when present, else from a `high_gain_channels`
(or `channel_gain`) argument; correct the module comment; log the gain used. Related to issue
16: the same merged files put Bz at 0.880 x pr624's (a 0.4545 divider), reading Z 1.01-1.02x
IGRF at ST19-ST21 where pr624's 0.4 reads 1.15-1.16x. Workaround here (2026-09-24, corrected by the
owner from an earlier version that named this the PR6-24's own high-gain setting): mtproc declares
the electric chain's own extra gain instead -- survey.yaml's `electric_gain:` (a `defaults:` key
with per-site override, written by `scripts/new_survey.py --electric-gain`, declared from the field
notes since the PR6-24's own configs were not kept for this survey) puts a CoefficientFilter
`uoa_electric_gain` at the end of ex and ey's chains at ingest (`mtproc.instruments.read_run`), the
samples staying the stored words.

## 22. aurora 0.6.2 / mth5 0.6.9: no per-band, per-window weights or masks can be supplied to the regression (2026-09-24)

**What we wanted:** apply a student's band-limited mask (a time interval that is bad only in some bands, e.g. a mains switching minute at 0.02-0.1 s) as zero weights for the STFT windows in that interval, in those bands only, so a cross-power editor's polar-plane selection reaches aurora's robust regression.

**What the code does (aurora 0.6.2, mth5 0.6.9):**
- `aurora/pipelines/process_mth5.py` lines ~197-198: `feature_weights.calculate_weights` sets `chws.weights` per `channel_weight_specs` entry just before the regression; it is `None` without `feature_weight_specs`.
- `aurora/transfer_function/transfer_function_helpers.py` lines ~351-352: `# band_weights = chws.get_weights_for_band(band)` is commented out and replaced by `band_weights = weights.mean(axis=1)`: one weight per STFT window, identical for every band of the decimation level.
- If the weighted path raises, `process_tf_decimation_level` logs a warning and silently reruns without weights.
- No callback exists between the transform and the regression (`process_mth5_legacy` passes `local_merged_stft_obj` straight to `process_tf_decimation_level`).
- `mth5/timeseries/spectre/multiple_station.py` has the stub `def apply_masks_and_weights(): pass` under `# TODO: add this method to tf-estimation right before robust regression.`

**Consequence for mtproc:** all-band masks are applied as time cuts on the kernel dataset's run intervals (`mtproc.masks.apply_time_masks`); band-limited masks are recorded in `masks.yaml` only. Alternatives: (a) a scoped patch of `aurora.pipelines.transfer_function_helpers.get_band_for_tf_estimate` that blanks the masked windows per band (relies on internals, as the read-only `MTH5.open_mth5` patch of issue 5 did); (b) a classical stacked remote-reference estimator on the retained chunk cross-powers (`mtproc.crosspower.stack_impedance`, built, library only).

**Ask upstream:** honour `chws.get_weights_for_band(band)` (the commented-out line) or expose a per-band window mask/weight input on the config, and fill the mth5 stub.

**Workaround in mtproc (2026-09-24, alternative (a)):** `mtproc.process._band_masks_applied` wraps `aurora.pipelines.transfer_function_helpers.get_band_for_tf_estimate` (the file is under `pipelines/`, not `transfer_function/`; lines 249 and 339 are the two regression loops' calls) for the duration of one `process_mth5` call, whenever `process_station` is given band-limited masks. In each band whose centre period a mask covers, it drops the STFT windows overlapping the mask from X, Y and RR. They are dropped, not zero-weighted. It logs the windows lost per level, skips a mask that would leave a band fewer than 4 windows, and fails loudly if aurora's signature or callers change (`tests/band_masks_unit.py`). Caveat, a second aurora 0.6.2 bug: one `IterControl` serves every band of a level, and `MEstimator.apply_huber_regression` evaluates `max_iterations_reached` before resetting the count. A band after one that used all 10 iterations therefore gets no Huber iterations, and a band mask can flip that for the bands after it on the same level. On the synthetic archive that moved 5 rows by up to 3.5 %; in the real C18 rr C19 check nothing moved, because no regression there reached 10 iterations. The proper fixes are prepared as pull requests in `docs/upstream_patches/` (per-band window masks on the config, and the iteration reset), not installed.

## 23. aurora 0.6.2: the robust (Huber) iteration counter is shared by every band of a decimation level and checked before it is reset (2026-09-24)

**Where:** `aurora/transfer_function/regression/m_estimator.py`, `MEstimator.apply_huber_regression` (about lines 218-220): the "max iterations reached" test runs before the counter is reset for the new band, and the estimator object is reused across the bands of a level.

**Effect:** a band that follows one which used all `max_iterations` (10) gets NO Huber iterations: its estimate is the initial least squares. On mtproc's synthetic test archive 10 of 48 regressions skipped the robust stage; their Zxy errors were 2.1-10 % against 0.45-2.9 % with the counter reset per regression. Any EDI is exposed whenever a regression hits the limit (noisy bands do); which bands are affected depends on the order and on what happened in the previous band, so a change in one band (a mask, a different window count) can flip the robust treatment of the bands after it on the same level. On a 2 h C18 window no regression reached 10 iterations; the frequency on full-length runs is not measured yet.

**Fix (prepared, not applied):** a five-line patch, now the second commit of the aurora fork branch: reset the counter at the start of every regression. mtproc does not apply it at runtime yet (it changes every estimate; applying it mid-campaign would make line C inconsistent) - the owner's decision.

## 24. mt_timeseries 0.0.2 / mth5 0.6.9: the time index is built twice per channel, sample by sample (2026-09-24)

**Where:** `mt_timeseries/ts_helpers.py:123` (`make_dt_coordinates`) runs once from mth5's `ChannelDataset.time_slice` and again from the `ChannelTS` time setter (`channel_ts.py:967`); pandas `TimelikeOps._round` then rounds the index by creating one Python int per sample.

**Effect:** on a 6 h C18 rr C19 window (1000 Hz, 8 channels) the index work is 13.5 s of the 24 s level-0 read; the HDF5 reads themselves take 0.8 s at over 1 GB/s. Under tracemalloc the rounding runs 36-133x slower still. Measured with `scripts/profile_run.py --stage trace`.

**Ask upstream:** build the index once from integer nanoseconds (start + i * 1e9 / fs; at 1000 Hz the step is exactly 1,000,000 ns) and pass it from `time_slice` into `ChannelTS` instead of rebuilding it. The mt-timeseries fork branch (int64 whole-ns index, one index shared between channels) covers the rounding; the double build remains.

## 25. mt_metadata 1.0.10: the datum validator re-parses the datum through pyproj on every Location (2026-09-24)

**Where:** `mt_metadata/common/location.py:127` (`BasicLocation.validate_datum`) calls `pyproj.CRS(datum)` each time a Location is built; one call is 2.8 ms and 487 page reads of 4 kB from `proj.db`.

**Effect:** 1,788 `CRS()` calls per estimate (65 in the kernel dataset, 754 at level 0, 114 per later level, 50 in the EDI write): 6.7 s of an 81 s run, 25-62 % of the deep-level STFT and EDI-write phases, and about 1.5 GB of `proj.db` reads per run -- most of the process's read traffic, ahead of the archives.

**Ask upstream:** cache the datum string to name lookup (the mt-metadata fork branch does; 200 Location() 0.55 -> 0.004 s), or accept the EPSG number, which costs nothing.

## 26. aurora 0.6.2: a failed `import cftime` inside every band regression (2026-09-24)

**Where:** `aurora.transfer_function_helpers.stack_fcs` builds a pandas MultiIndex per band; xarray then tries `import cftime` to type the index and, with cftime not installed, re-scans `sys.path` every time.

**Effect:** 14,472 failed imports per estimate, 3.5 s, 27-49 % of each deep-level regression phase.

**Ask upstream:** stack the band arrays with a numpy reshape instead of a MultiIndex. Workaround: install `cftime` (an xarray optional dependency); results are unchanged, only the failed import goes.

## 27. aurora 0.6.2 / mth5 0.6.9: channel responses and channel objects rebuilt at every decimation level (2026-09-24)

**Where:** `aurora.time_series.spectrogram_helpers.calibrate_stft_obj` re-creates the channel objects per level; each one makes mth5 build a new pydantic model class (`mth5/helpers.py:863` -> `pydantic.create_model`, 944 calls per estimate).

**Effect:** 5.4 s over 18 calls per estimate, plus 62 `RunGroup.get_channel` calls (3.4 s).

**Ask upstream:** compute the responses once per run in aurora, or cache the generated classes in mth5.

## 28. aurora 0.6.2 / mth5 0.6.9: the STFT merge and the recolouring copy every run's spectrogram (2026-09-24)

**Where:** `aurora.time_series.spectrogram_helpers.merge_stfts` (lines ~226-230) concatenates with xarray even when a station has one run (a pure copy alive beside the original, 879 + 440 MiB at 6 h); `mth5/processing/spectre/prewhitening.py:82` (`apply_recoloring`) allocates the recoloured STFT through xarray `where` (1,318 MiB held in the `stfts` dict until the merge).

**Effect:** at the peak of a 6 h run on the fork, 2.6 GiB of the 4.2 GiB RSS are these copies plus the 1.3 GiB of time series the kernel dataset holds; on 44 h the same pattern is the 29 GiB peak.

**Ask upstream:** skip the concatenate for a single run (or free each run as it is copied) and recolour in place. Expected peak 4.1 -> about 2.8 GiB at 6 h.

## 29. aurora 0.6.2: each band is extracted twice, once per output channel, and the EDF weights copy the kept rows per iteration (2026-09-24)

**Where:** `process_transfer_functions_with_weights` extracts the band for ex and again for ey (xarray `align` 1,936 calls, `Dataset.copy` 3,323 calls per estimate); `edf_weights.py:75` selects the kept rows on every iteration.

**Effect:** about 2 s of align/copy and 7.3 s in `compute_weights` (34 % of the level-0 regression) per 6 h estimate on the fork.

**Ask upstream:** extract each band once and reuse it for both outputs; compute the weights with a single einsum over a boolean mask.
