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
