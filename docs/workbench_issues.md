# mt-workbench: known defects and slow paths

Our own, as distinct from `upstream_issues.md`. Found by the robustness and
GUI passes of 2-3 Oct 2026 (`<workspace>/qc/survey/pipeline_bench_20261002/`:
`robustness/cases.md`, `gui/`, `README.md` section 4). Numbered so notes can
cite them; add the fix commit when one lands.

## Silent wrong output (fix first)

1. **A B423 file cut mid-record inside a run of back-to-back files is
   ingested without a message**, and every sample after it is stamped
   -2699.999 s early (control: +0.001 s). `mt_workbench.ingest._group_contiguous`
   (LEMI-423): end a run at any file whose sample count disagrees with its
   span, and say so; a partial-record warning belongs in mt-io's reader too.
   Robustness case 5c.
2. **A 10 min window writes an EDI with Z errors of exactly 0** at 45.976 s
   (rho 1030 / 1480 against 3.3 / 1.4 over 44.9 h); a 1 h window gives dZ/Z
   0.44 against 0.085 with only aurora's "Window is longer than the time
   series" errors. `mt_workbench.process.process_station` / `products`: never
   write a zero or non-finite error, and drop bands whose level has fewer than
   a minimum number of STFT windows (policy: Ben). Cases 3a, 3b.
3. **An unknown declination (absent in survey.yaml and in the archive) is
   written as `<Declination epoch="1995">0.000</Declination>` in the XML** and
   0.0 in the sidecar, while the EDI correctly says "no declination stored".
   `mt_workbench.products` `frame_record` and the XML writer: treat an archive
   declination of 0.0 without a model or epoch as unknown. Case 8c.
4. **A site not in survey.yaml passes `--dry-run`** ("no raw folder",
   "1000 Hz") and the real run ends in a bare KeyError. `scripts/process_rr.py`
   `resolve`: exit 2 with the site name. Case 9b.

## Unclear failures (a traceback or a silent wait where a message belongs)

5. Variant build while the variant is held open: two tracebacks
   (PermissionError on `os.replace(.h5.part -> .h5)`) and a 5.3 GB `.part`
   left behind; the cleanup targets the good variant. `ingest.build_variant`,
   `ingest_site._remove_partial`. Case 1b.
6. Dead remote (no time overlap): a 12-line mth5 traceback after a
   resolution block that says "window: full overlap". `process_rr.resolve`:
   compare the spans in the dry run. Case 4.
7. Memory gate above the machine's RAM waits for ever with one log line every
   300 s. `campaign.py` `Runner.gate`: refuse at start (exit 2) when
   `min_available_gb` exceeds the machine. Case 7.
8. `campaign.py --stage 0 --dry-run` lists a current variant as "to build"
   when the ledger has no done row for it. Case 2c.
9. `process_rr --dry-run` words a missing raw archive the same as a present
   one ("raw: <path>, variant: to build"). Case 9a.
10. A missing workspace folder opens the survey in the GUI with "0 with an
    MTH5 archive" and no workspace error (GUI bench control).

## Slow paths, measured

11. **masks.yaml (8.1 MB, 30,802 masks) is parsed whole with pure-Python
    `yaml.safe_load` on the GUI thread, 10.2 s per parse**, three times at
    survey open and up to eight times per Process-tab pick:
    `masks.load_masks` via `stack_builder.RunOptions.describe_masks`,
    `crosspower`, `remote_masks`. Survey open 35.9 s -> 7.8 s and a pair pick
    70.4 s -> 2.4 s measured with the file cut to two sites. Fix: a parse cache
    keyed on (path, mtime, size) with `yaml.CSafeLoader` (2.9 s), off the GUI
    thread; longer term, masks per site. The same parse costs 19.4 s per
    masked `process_rr` run (77.75 s over the six bench pairs).
12. **View EDIs `reload()` json-loads every sidecar** (4,398 files, 588 MB)
    to read the `engine` key; its `lru_cache(256)` is smaller than the file
    count. 5.1-6.2 s at survey open, on Refresh and after every landed job;
    0.014 s with 100 products. `mantle_products.describe`, `gui/tabs/edis.py`:
    a `tf/index.json` written with each product, an unbounded mtime-keyed
    cache, a lazy tree.
13. **Every WindowBar reads the span of every archive** with `load_grid`
    (96-104 calls, 13.2-15.0 s, pydantic metadata construction) under the
    archive lock; 1.4 s with 10 archives. `window_bar.site_span`,
    `archive.load_grid`: spans from h5py attributes, one persisted cache shared
    by the Process and Cross-powers bars.
14. **Variant filtering is 52 % of the end-to-end pipeline** (1,635 of
    3,500 s over 13 builds) on 3.4-3.8 of 20 cores: `noise.mains_subtract`
    (one-second block fit) and `noise.mains_notch` (one `sosfiltfilt` per line
    and pass) through `build_variant`'s four-worker, one-channel-per-thread
    pool; B10 alone 506 s at 37 GiB. Fix: time chunks over a pool sized to the
    cores (bounds memory too); a stacked SOS is 6.5x faster per channel but
    not identical within 60 s of run ends (Ben's call, with a variant-hash
    salt).
15. Masks naming only output channels split a pair into two aurora runs
    (`process_rr.row_runs`): A20 rr A21 440 s = 135 + 279 s. One read and STFT
    with the extra masks applied at the regression; needs an identity check.
16. Cross-powers `WORKERS` 4 -> 8: whole-overlap compute 24.5 -> 17.1 s
    (identity checked on a 6 h window only).
17. Imports per child process 2.6 s (`mt_metadata.transfer_functions` 1.5 s
    through `mt_workbench.compare`): about 70 s per bench-sized batch; reuse
    worker processes in the campaign runner.
18. Campaign `--parallel` below what the memory gate allows: four jobs fit at
    the fork median peak of 22.4 GiB, three at the p90 34.6 GiB; lines A and D
    ran two at a time.
19. Sidecars record no fork SHAs for mth5, mt_timeseries, mt_io and
    mt_metadata (the version strings are the upstream numbers), so a ledger
    cannot attribute a gain to a fork. `products` / `process_rr`: record the
    installed `direct_url` commit or a local tag per package.
