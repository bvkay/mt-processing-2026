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
   Robustness case 5c. Fixed in ae6d4bc (`_b423_run_ends`; the case 5c copies
   now ingest as three runs, file 3 stamped +0.001 s; psd_qc.py's --before
   read and profile_run.py's B423 read benchmark pass the site's rate too);
   the mt-io warning is still to do.
2. **A 10 min window writes an EDI with Z errors of exactly 0** at 45.976 s
   (rho 1030 / 1480 against 3.3 / 1.4 over 44.9 h); a 1 h window gives dZ/Z
   0.44 against 0.085 with only aurora's "Window is longer than the time
   series" errors. `mt_workbench.process.process_station` / `products`: never
   write a zero or non-finite error, and drop bands whose level has fewer than
   a minimum number of STFT windows (policy: Ben). Cases 3a, 3b. Fixed in
   4a7cde0: `drop_short_bands` with `min_band_windows` (default 5, below the
   7 of the 6 h identity run's deepest level; survey.yaml `processing:` key
   and `--min-band-windows`), then `products.drop_bad_errors`. The 10 min
   window writes 34 periods to 11.5 s, none with a zero error; the 1 h
   window (case 3a) loses level 8 (3 windows), 57.9-183.9 s, and ends at
   46 s. The default 5 stands until Ben sets the policy.
   The guard works per row. As first written it removed a period from
   every row when any row was bad there, and after `merge_rows` (a masked
   pair run once per set of masks by row) a band one row's run did not
   keep is NaN in that row, so the whole period went: in a synthetic merge
   (ex from a run on 1, 2, 4, 8 s, ey and hz from one on 1, 2, 8, 16 s) it
   wrote 1, 2 and 8 s and lost the good ex estimate at 4 s and the ey and
   hz ones at 16 s. Now a row with a zero or non-finite error is written as
   not estimated (EMPTY, 1e32, in the EDI) at that period, the other rows
   keep their values, and a period goes only when no row is left; the
   merge keeps all five periods, as before the guard. No masked pair has
   been measured with the floor on. MANTLE applies no floor:
   `--engine mantle` refuses `--min-band-windows` and its sidecar records
   `min_band_windows` as null; its pooled EDI does not pass through the
   error guard.
3. **An unknown declination (absent in survey.yaml and in the archive) is
   written as `<Declination epoch="1995">0.000</Declination>` in the XML** and
   0.0 in the sidecar, while the EDI correctly says "no declination stored".
   `mt_workbench.products` `frame_record` and the XML writer: treat an archive
   declination of 0.0 without a model or epoch as unknown. Case 8c. Fixed in
   896dc92 (no Declination element, null sidecar keys, a run-time warning).
4. **A site not in survey.yaml passes `--dry-run`** ("no raw folder",
   "1000 Hz") and the real run ends in a bare KeyError. `scripts/process_rr.py`
   `resolve`: exit 2 with the site name. Case 9b. Fixed in 17f0a96
   (`check_pair`; a stacked remote STK_..., built or not, passes).

## Unclear failures (a traceback or a silent wait where a message belongs)

5. Variant build while the variant is held open: two tracebacks
   (PermissionError on `os.replace(.h5.part -> .h5)`) and a 5.3 GB `.part`
   left behind; the cleanup targets the good variant. `ingest.build_variant`,
   `ingest_site._remove_partial`. Case 1b. Fixed in 9c0ba47.
6. Dead remote (no time overlap): a 12-line mth5 traceback after a
   resolution block that says "window: full overlap". `process_rr.resolve`:
   compare the spans in the dry run. Case 4. Fixed in 17f0a96: exit 2 with
   both spans (survey.yaml start/end, else the archive's runs), dry run too.
7. Memory gate above the machine's RAM waits for ever with one log line every
   300 s. `campaign.py` `Runner.gate`: refuse at start (exit 2) when
   `min_available_gb` exceeds the machine. Case 7. Fixed in ba4944a.
8. `campaign.py --stage 0 --dry-run` lists a current variant as "to build"
   when the ledger has no done row for it. Case 2c. Fixed in 93cc600, which
   also names a missing raw archive and lists an unreadable variant file.
9. `process_rr --dry-run` words a missing raw archive the same as a present
   one ("raw: <path>, variant: to build"). Case 9a. Fixed in 17f0a96
   ("raw: <path> (missing: ingested from <raw folder> first)").
10. A missing workspace folder opens the survey in the GUI with "0 with an
    MTH5 archive" and no workspace error (GUI bench control). Fixed in
    71901d6: a non-modal warning when the workspace and its parent folder
    are both missing; a workspace not made yet opens and fetches as before.

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
    Fixed: 557b4fe (`masks.read_document`: one libyaml parse per change of
    (path, mtime, size), 2.8-3.0 s, a file read within 2 s of a write read
    again; `State.masks_reader` parses off the GUI thread; all 75 Atlas sites
    load equal to the pure-Python parse; the Cross-powers mask buttons
    inert until the list is filled, `tests/crosspower_masks_wait_unit.py`)
    and 7df4a33 (no read loop on an unreadable file). Masks per site
    still open.
12. **View EDIs `reload()` json-loads every sidecar** (4,398 files, 588 MB)
    to read the `engine` key; its `lru_cache(256)` is smaller than the file
    count. 5.1-6.2 s at survey open, on Refresh and after every landed job;
    0.014 s with 100 products. `mantle_products.describe`, `gui/tabs/edis.py`:
    a `tf/index.json` written with each product, an unbounded mtime-keyed
    cache, a lazy tree.
    Fixed: dcfb686 (`mt_workbench.tf_index`: the index written by
    `write_products`, per-stem entries kept in-process without bound, one
    `os.scandir` per reload). The lazy tree is not done (see
    `qc/survey/workbench_fixes_20261003/gui/README.md` for the reload left).
13. **Every WindowBar reads the span of every archive** with `load_grid`
    (96-104 calls, 13.2-15.0 s, pydantic metadata construction) under the
    archive lock; 1.4 s with 10 archives. `window_bar.site_span`,
    `archive.load_grid`: spans from h5py attributes, one persisted cache shared
    by the Process and Cross-powers bars.
    Fixed: 5d428a4 (`archive.read_span`: the 103 live archives in 0.53 s
    against 14.59 s, every span equal to `load_grid`'s; `State.spans` keyed
    on path, mtime and size, shared by both bars and kept across survey
    reloads in the process, not written to disk).
14. **Variant filtering is 52 % of the end-to-end pipeline** (1,635 of
    3,500 s over 13 builds) on 3.4-3.8 of 20 cores: `noise.mains_subtract`
    (one-second block fit) and `noise.mains_notch` (one `sosfiltfilt` per line
    and pass) through `build_variant`'s four-worker, one-channel-per-thread
    pool; B10 alone 506 s at 37 GiB. Fix: time chunks over a pool sized to the
    cores (bounds memory too); a stacked SOS is 6.5x faster per channel but
    not identical within 60 s of run ends (Ben's call, with a variant-hash
    salt). Fixed in 31f7402 for the mains fit only (the stacked SOS left for
    Ben): its own chunks run over a pool of the cores, bit for bit (the
    synthetic against a stored a937bc4 result; 2 h of B10's four channels
    on 1, 8 and 20 threads). On those 2 h it went 5.41 -> 3.84-3.94 s on 8
    threads (3.6 -> 6.2 cores, peak 0.67-0.71 -> 0.72 GiB) and 4.25-4.33 s
    on 20 (1.07 GiB): its basis arithmetic is memory-bound, so 8 threads
    beat 20. The notch keeps its single pass. In 600 s chunks with settling
    margins it equalled the single pass only to rounding: up to 2.2e-12 of
    the std on C19's declared q 60 x2 (3.3e-14 of the largest sample), and
    with the mean removed C19 ex still differed by 5.2e-8 counts in 37,746
    samples. That patch (B10's notch 2.31 -> 1.62 s, 1.07 -> 0.67 GiB) is
    Ben's call: the Morocco workspace's
    qc/survey/workbench_fixes_20261003/pipeline/followup. Not measured on a
    whole variant build.
15. Masks naming only output channels split a pair into two aurora runs
    (`process_rr.row_runs`): A20 rr A21 440 s = 135 + 279 s. One read and STFT
    with the extra masks applied at the regression; needs an identity check.
16. Cross-powers `WORKERS` 4 -> 8: whole-overlap compute 24.5 -> 17.1 s
    (identity checked on a 6 h window only).
    Fixed: 1eb7941 (identity re-checked on 1 h of the bench C18 rr C19:
    the 92 store arrays with data equal; levels 8-10 hold no window in
    1 h, so the deepest levels rest on the 6 h check).
    The 24.5 -> 17.1 s is an idle-machine figure; under 34-65 % machine
    load the whole overlap took 24.3 -> 19.8 s (two runs of each, 3 Oct).
17. Imports per child process 2.6 s (`mt_metadata.transfer_functions` 1.5 s
    through `mt_workbench.compare`): about 70 s per bench-sized batch; reuse
    worker processes in the campaign runner. cc6203a makes compare import
    mt_metadata and matplotlib only when used (`import mt_workbench.compare`
    2.36 -> 0.075 s), and process_rr.py selects Agg itself before mth5 and
    mt_io import pyplot, as compare did. process_rr.py's import is no
    faster: 2.80 s before, 2.92 s with the lazy imports alone, 2.83 s with
    Agg selected early (medians of five fresh processes, interleaved;
    2.69-3.15 s over all fifteen). `mt_workbench.ingest` imports mth5 and
    mt_io, which import mt_metadata.transfer_functions and
    matplotlib.pyplot themselves: the 1.5 s was where `-X importtime`
    charged a cost every child pays anyway. Worker reuse remains the lever.
18. Campaign `--parallel` below what the memory gate allows: four jobs fit at
    the fork median peak of 22.4 GiB, three at the p90 34.6 GiB; lines A and D
    ran two at a time. Fixed in 8cd6e21: the default is `runner.parallel`,
    else as many jobs as the gate admits at start, logged with the rr peak
    used (line C2's dry run: 4 at its p90 of 25.0 GB with 101.2 GB free).
19. Sidecars record no fork SHAs for mth5, mt_timeseries, mt_io and
    mt_metadata (the version strings are the upstream numbers), so a ledger
    cannot attribute a gain to a fork. `products` / `process_rr`: record the
    installed `direct_url` commit or a local tag per package. Fixed in
    955bc16: `versions.installed` per package (direct_url, editable, the
    commit when pip recorded one, the RECORD and `__init__.py` hashes). The
    forks were installed from their clone folders, so pip recorded no
    commit; a reinstall from a `git+file://` URL would record one.
