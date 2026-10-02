# The IAGA Div VI fork branches: what is where, and what to do next

Working record of Ben's `mtproc-fixes` branches of the IAGA-DVI-DataStandards
repositories (and the simpeg aurora fork), kept so that later work on them
starts from what is known. Symptoms are numbered in `upstream_issues.md`;
the review evidence of 2 Oct 2026 is under
`<workspace>/qc/survey/fork_pr_readiness_20261002/` (index `README.md`, PR
drafts listed in `PR_INDEX.md`, one `review/` and one `sceptic/` folder per
repository, `benchmarks/`, `profile/`); the end-to-end bench of 2-3 Oct is
under `<workspace>/qc/survey/pipeline_bench_20261002/`.

## Branches (2 Oct 2026)

| repo | clone | base (upstream) | tip | pushed | PR target | commits |
|---|---|---|---|---|---|---|
| mt-timeseries | D:\BEN\mt-timeseries | main f25956e (v0.0.3) | 1e69f05 | yes | main | 5 |
| mth5 | D:\BEN\mth5 | master 6c62aeb9 (v0.6.9) | 0ea85692 | yes | patches | 6 |
| mt-metadata | D:\BEN\mt-metadata | main 22350c51 (v1.0.11) | 405e7ff1 | **no** (origin at 0a84443f) | patches | 2 |
| mt-io | D:\BEN\mt-io | main 90f3365 (v0.0.5; develop has the same tree) | cdceeb3 | yes | develop | 16 |
| aurora | D:\BEN\aurora | simpeg main 3395804c | d7acd16c | yes | (not in the PR plan) | 14 |

All five are installed in `bbmt-2026` non-editable from the clones
(`pip install --no-deps <clone>`), so a change to a clone is not live until
reinstalled. `remote -v` in each clone: `origin` = github.com/bvkay/<repo>,
`upstream` = the IAGA-DVI or simpeg repository. Rules: Ben is the only
author, no attribution lines, one concern per commit, nothing pushed and no
issue or PR opened by an agent.

## Commit to issue map

- mt-timeseries: 5729127 non-integer rates kept (issue 10; changes
  `test_dataframe_with_index` 4096 -> 4095 Hz; needs pandas >= 2.0, not
  declared); 25229b8 phantom `auxiliary_default` dropped (17); e92978c
  whole-ns int64 index (24, speed); 60a3ba7 one index shared between channels
  (24, memory; a module-level `WeakValueDictionary`); 1e69f05 step counting
  instead of sorting (speed; slower than main on jittered indexes).
- mth5: 01d145fe read-only opens for run summaries and kernel datasets (5);
  2c0cf2ed one run-id warning per run (9); 069b6237 channel metadata built
  once in `to_channel_ts`/`time_slice` (speed); f13ad860 tests accept
  mt_metadata's ValueError (needed by mt-metadata 0a84443f); fc478555 black on
  two tests (squash into the two before it); 0ea85692 LEMI-120 coil response
  expected in nanotesla (needs mt-io 736a736).
- mt-metadata: 0a84443f named ValueError for a band with no FFT harmonic
  (20); 405e7ff1 EDI AZM from measurement_azimuth, DECLINATION round trip,
  TROT warning (31).
- mt-io: 816bd44 four-digit altitudes (6; stock cannot read 46 of the 103
  Atlas sites); 68df1de every rate listed (7); 7681acf no-rate warning (8);
  736a736 coil response chain valid (1, 2); f9fcef2 integer-ms time index
  (speed); 6232b27 GPS status on request (4); 2ef167a refuse non-contiguous
  EDL sets (18); 8e91515 400 mV/nT note (19b); 1272113 fluxgate-chain warning
  and bad coil file error (19a, c); 3a5f1c7 per-channel gain on PR6-24;
  58a3a0a refuse non-joining Orange files (11); 830f191 Orange full scales
  (13, 14); 4ce30d9 Orange defaults named (15); f6d0079 Orange temperature on
  request; 653913e black plus a dead variable (dissolve into the PRs it
  touches); cdceeb3 clear error on a blank B423 header (30).
- aurora: see `../NOTES.md` in the clone and `upstream_issues.md` 22-29
  (window masks, Huber reset, EDF count_nonzero, closed-form detrend, isel
  bands, rfft, freed intermediates, remote channels dropped, round 2).

## State of the suites (2 Oct 2026, production python 3.11.16)

Fork tip / upstream tip, same command, same partners: mt-timeseries 264 / 190
passed; mth5 2173 / 2081 (the same 91 `mth5_test_data` and 4
`pytest-benchmark` errors on both; 2302 passed with the test data); mt-metadata
7481 / 7468; mt-io 1575 / 1533 (74 `mth5_test_data` errors on both). No
fork-induced failure with the same partners. With every partner at its
release, as upstream CI installs them, one mth5 test fails
(`test_lemi::test_get_coil_response_filter`, 0ea85692 expects mt-io 736a736).
black passes on every touched file; isort fails on upstream's own files
(mt-timeseries `tests/test_scipy_filters.py`; mt-metadata 165 files on both
trees; mth5 upstream fails black on 105 files). The exact commands are in
each `review/README.md`; pytest, black and isort are not in `bbmt-2026` and
were run from a `--target` install on PYTHONPATH.

## Blockers before the PRs (who acts: Ben)

1. mt-metadata 405e7ff1: not pushed; not idempotent (a second
   `TF.write(file_type="edi")` of the same TF gives ey AZM 0.00: the
   `from_metadata` zero-fill loop sets `translated_azimuth` None -> 0 and the
   new rule treats 0 as set; two-line fix and write-twice test drafted in
   `mt-metadata/review/azm_idempotence/`); drops every `DECLINATION.COMMENTS`
   line; mixes three concerns (split into AZM / declination / TROT). The
   commit message also claims a "comments time stamp line" is dropped, which
   the diff does not do.
2. mth5 0ea85692 <-> mt-io 736a736 break each other's CI: make the mth5
   assertion accept either unit and merge it first.
3. mt-metadata 0a84443f's ValueError fails two stock-mth5 tests: mth5
   f13ad860 released first, or raise `BandHarmonicError(ValueError,
   IndexError)` (verified not to break stock mth5).
4. mt-timeseries 25229b8 does not apply to main alone (test anchored on
   5729127's class): `mt-timeseries/review/patches/25229b8_rebased_on_upstream_main.patch`.
5. mt-io 653913e dissolved into PRs 2, 7, 8, 11; `tests/lemi/test_lemi423.py`
   import order fixed in PR 1.
6. Commit bodies citing fork hashes (mth5 f13ad860 -> 83c8b9c7, 0ea85692 ->
   736a736) replaced by partner PR numbers; `#...` placeholders filled after
   opening.
7. Field numbers in mt-io pr_08/09/11 with no log behind them: confirm or
   drop.
8. Behaviour changes a maintainer may question, listed in
   `fork_pr_readiness_20261002/README.md` section 5.5 (numeric rate change and
   4096 -> 4095; global cache; new exceptions where data was returned; widened
   defaults; coil label).

Granularity: the drafts give 23 PRs (mt-io 12). Three mt-io PRs (LEMI-423
fixes, LEMI speed, UoA) is the alternative; Ben decides when opening.

## Measured gains to quote (paired, fresh process per run, medians)

Against the released partners (what an upstream reviewer runs): 2 h
`RunGroup.to_runts` 3.01 -> 0.47 s with the mt-timeseries fork alone and
3.01 -> 1.65 s with the mth5 fork alone (both forks 0.295 s); whole 44.3 h
run `to_runts` 9.17 -> 2.29 s and peak 14.8 -> 3.9 GiB with both;
`time_slice` 2 h 0.69 -> 0.36 s (mth5); B423 `read_dataframe` 0.45 -> 0.17 s
(mt-io, independent of partners); EDI round trip unchanged (mt-metadata,
correctness only). Data and time stamps identical in every speed case.
Source: `fork_pr_readiness_20261002/benchmarks/timings.csv` and the sceptic's
partner-release reruns. The ledger's 457 -> 181 s on the same 62 pairs is the
whole-stack change (aurora rounds 1-2, the four forks, mt-workbench), not
attributable to the four forks: the sidecars record no fork SHAs (to add).

## Next upstream changes with evidence (not yet on any branch)

- aurora: NaN fast path in `drop_nans`/`handle_nan` and X/RR stack + EDF
  weights once per band (-2.4 s and -1.1 s on a 6 h run; 540 s of the 1335 s
  regression over the six bench pairs); threaded per-channel
  `prototype_decimate` (1.72 -> 0.72 s per call); release the L0 series
  before the L0 regression (19.45 of the 51.9 GiB B10 peak); complex64 STFTs
  (-9.7 GiB, numerics change, Ben's decision). Trial patches with identical
  TFs: `fork_pr_readiness_20261002/profile/`.
- mth5: `apply_prewhitening` by `np.gradient` with the scalar step (1.08 ->
  0.55 s per call); `ChannelTable.has_data` returning False for a 0-byte
  dataset (-1.0 s per TF h5 write); `RunGroup.to_runts(channels=...)` so the
  remote's unused electrics are not read; a test for the never-summarised
  archive (PR 1 raises KeyError there).
- mt-metadata: cache `get_unit_from_df` rows (0.28 -> 0.001 ms per call);
  metadata built once per run rather than per level.
- mt-timeseries: `make_dt_coordinates` rounds to ms at 20/25/50/100 kHz from a
  whole-second start (both trees); `compute_sample_rate` high-rate branch
  raises TypeError with scipy >= 1.11 (both trees); a scipy fallback for
  jittered indexes in 1e69f05.
- mt-io: a partial-record warning when a B423 file ends mid-record (see
  `workbench_issues.md` 1 for the mt-workbench side).

## How to re-run the checks

- Suites: export a tree with `git -C <clone> archive <ref> | tar -x -C <dir>`,
  put the package root (`src` for mt-io) first on PYTHONPATH, confirm with
  `python -c "import <pkg>; print(<pkg>.__file__)"`, then
  `python -m pytest -q -p no:cacheprovider -rfEs tests` with the production
  python. Never check out another branch in a clone: the installed copies are
  snapshots, but `aurora.__file__` once resolved to the clone.
- Format gate as upstream runs it: `format.yaml` / `format-check.yml` in each
  repo (black, isort, autoflake); versions unpinned in CI, pinned in
  `.pre-commit-config.yaml` where present.
- Benchmarks: `fork_pr_readiness_20261002/benchmarks/bench.py` (stock tree on
  PYTHONPATH vs installed fork, fresh child per run, tree check that must
  fail). End to end: `scripts/bench_pipeline.py` (reference pairs C18 rr C19,
  A20 rr A21, B02 rr R01, D02 rr D14, B10 rr B09 and the C18 stack), which
  checks every product against the live reference and exits 1 on a
  difference.
