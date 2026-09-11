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
- **Workaround here:** `bbmt.ingest._read_coil_response` monkeypatches the
  function; delete once fixed upstream.

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
  correction) to fit the reader's existing order.
- **Resolved empirically (2026-09-21, D02 RR E08 vs merged lemimt EDI):** the
  reader's "nT" magnetics are actually **pT with inverted polarity** relative
  to the lemimt convention — rho came out a constant 1.0e6 low (|Z| factor
  986 ~ 1000) with both phase modes exactly 180 deg off. Fix in mt-io: make
  the linear magnetic calibration filter gain a factor -1000 different (or
  correct the labelled units to picoTesla and document the polarity). Until
  then `bbmt.ingest._apply_h_scale` appends an explicit CoefficientFilter
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

Found 2026-09-23 while building an aurora config for a test. `RunSummary.from_mth5s` opens every archive through `initialize_mth5(path, mode="a")`, and `KernelDataset.from_run_summary` opens the local station again through `MTH5().open_mth5(path)`, whose default mode is also read-write. Two consequences: (1) a config cannot be built while another process (the GUI, a test) holds the archive open read-only, because HDF5 file locking refuses the read-write open (`OSError: unable to lock file`); (2) every processing run touches the archive's modification time even though it only reads metadata. The content is unchanged (checked with an independent h5py read of samples). Workaround in tests: monkeypatch `mth5.processing.run_summary.initialize_mth5` and `mth5.mth5.MTH5.open_mth5` to force `mode="r"` (see `tests/process_rr_cli_unit.py`). Worth an upstream request for a read-only mode on both.

### 6. `lemi423` header parser fails on four-digit altitudes (`%Alt1060.0,m`)

Found 2026-09-23 building the Morocco Atlas survey. LEMI-423 firmware 2.1 writes
the altitude line with a fixed field width, so once the value has four digits
there is no space after the tag: `%Alt1060.0,m 12 1` (three-digit values read
`%Alt 125.2,m 12 1`, two-digit `%Alt  27.1,m 12 2`). `Read_Lemi_Header._extract_coordinates`
takes `header[11].split(",")[0].split()[-1]`, which is `'%Alt1060.0'`, and
`float()` raises `ValueError: could not convert string to float: '%Alt1060.0'`.
`read_lemi423` therefore refuses every file of every site above 1000 m: 47 of
the 103 Morocco sites. Reproduction: the header lines above with any B423 body.
Workaround: `bbmt.ingest` installs a tolerant `_extract_coordinates` that
retries with a space inserted after `%Alt` (unit test
`tests/ingest_unit.py::test_glued_altitude_header_line`). Suggested fix
upstream: strip the `%Alt` tag before splitting, e.g.
`header[11].split(",")[0].replace("%Alt", "").strip()`.

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
with its rate. Not used by this repo (bbmt.ingest lists files itself), logged
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
