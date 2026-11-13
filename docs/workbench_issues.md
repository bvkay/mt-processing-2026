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
   Robustness case 5c. Fixed in a35b625 (`_b423_run_ends`; the case 5c copies
   now ingest as three runs, file 3 stamped +0.001 s; psd_qc.py's --before
   read and profile_run.py's B423 read benchmark pass the site's rate too);
   the mt-io warning is still to do.
2. **A 10 min window writes an EDI with Z errors of exactly 0** at 45.976 s
   (rho 1030 / 1480 against 3.3 / 1.4 over 44.9 h); a 1 h window gives dZ/Z
   0.44 against 0.085 with only aurora's "Window is longer than the time
   series" errors. `mt_workbench.process.process_station` / `products`: never
   write a zero or non-finite error, and drop bands whose level has fewer than
   a minimum number of STFT windows (policy: open). Cases 3a, 3b. Fixed in
   2928aab: `drop_short_bands` with `min_band_windows` (default 5, below the
   7 of the 6 h identity run's deepest level; survey.yaml `processing:` key
   and `--min-band-windows`), then `products.drop_bad_errors`. The 10 min
   window writes 34 periods to 11.5 s, none with a zero error; the 1 h
   window (case 3a) loses level 8 (3 windows), 57.9-183.9 s, and ends at
   46 s. The default 5 stands until the policy is set.
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
   b93acca (no Declination element, null sidecar keys, a run-time warning).
4. **A site not in survey.yaml passes `--dry-run`** ("no raw folder",
   "1000 Hz") and the real run ends in a bare KeyError. `scripts/process_rr.py`
   `resolve`: exit 2 with the site name. Case 9b. Fixed in 05fc5cd
   (`check_pair`; a stacked remote STK_..., built or not, passes).

20. `variant_ready` and the 1 Hz derived site judge freshness by the filters hash
    alone, so a rebuilt raw archive (Nador 5 Oct 2026: P4S7 with `swap_h`, P4S8 with
    `h_from`) left `--variant` reporting the old variant "already current" and
    `decimate_site.py` cutting the 1 Hz site from the stale variant; the
    products would have carried the dead or swapped magnetics silently. Worked
    around with `--variant --force` and `decimate_site.py --force`
    (runs/reingest_20261005/run_variants_force.py). Fix: record the raw archive's
    identity (size, mtime or a content hash, and the calibration table's hash,
    chip of 4 Oct) in the variant's run comment and refuse "current" when it
    differs; the same for a derived site against its source archive.
    Fixed in fa9530b: `build_variant` writes, after the hash, "source: <stem>
    size <bytes> mtime <UTC, ISO basic> sha256_head <sha256 of the first MiB
    and the size>" of the raw archive (`archive_identity`, taken before it is
    read), "calibration_sha256: <hex>" as the raw archive records it, and
    "donor: <identity>" per `replace` donor, each a dot-free "key: value"
    piece the EMTF XML writer accepts (upstream 48). `ingest_site` now
    records the sha256 of the coil tables it read in every raw run comment.
    `variant_ready` is False when the raw archive or a donor is not the
    recorded file or the recorded tables no longer hash as the declared ones
    (`_calibration_stale`), with a log line saying why. A variant built
    before the fix (no record) is judged by file times instead
    (`_file_time_stale`, grandfather rule): current, with a WARNING, while
    newer than its raw archive and donors, so existing variants are not all
    rebuilt; P4S7 and P4S8 (raw rebuilt 04:44-04:46 after variants of 23:12
    and 00:12) fail it. `build_variant`
    and `processing_archive` refuse a raw archive whose recorded tables have
    changed (re-ingest it; a variant rebuilt from it would repeat the old
    table). decimate_site.py records the source's identity in every derived
    run and rebuilds `<site>L.h5` without --force when the source variant is
    stale or the identity differs (`derived_stale`; the same file-time rule
    for a derived archive without the record), and its note's key is now
    "derived_by: decimate_site <version>" (the old "decimated from ...
    decimate_site.py:" key had dots, upstream 48). Not covered: a raw
    archive ingested before the fix records no table, so a table change is
    caught only after a re-ingest; process_rr.py still takes a derived
    archive as it is (run decimate_site.py first); and an archive opened in
    mode "a" (mth5's default) is rewritten on close and reads as rebuilt,
    which costs a rebuild, not a stale product (our readers and aurora's
    default path open read-only).

25. `masks.replace_text` writes through `Path.write_text`, which on Windows
    turns every `\n` into `\r\n`, and `masks._write_block` reads the file
    with `read_text`, so the first save of a masks.yaml whose lines end in
    LF (a file from another editor or machine) rewrites every line of it,
    not one block: a 40-byte LF file came back 45 bytes, all CRLF [measured,
    scratch file, 5 Oct]. The content parses the same; what is lost is the
    promise that the other blocks stay byte-identical, and a diff of the
    file shows every line changed. Low severity: the GUI's own masks.yaml
    files are CRLF from their first write. Wanted: read bytes, keep the
    file's own newline, write bytes. The Stacks tab's stacks.yaml writer
    does not use `replace_text` for this reason
    (docs/gui_stack_tab_design.md 9.3, critique 8.1 item 13). Found 5 Oct
    2026 while revising the Stacks tab spec.

28. `intersite.polarity_summary` flags a member by the sign of its median
    correlation alone, so a dead member, whose correlation with the others is
    noise around zero, is called reversed on whichever coil the noise came out
    negative [measured: the dead member of tests/stack_check_unit.py, coherence
    0.009, correlates +0.0073 on hx and -0.0072 on hy]. With
    `--screen-polarity flag` the record names a dead coil as a reversed one;
    with `drop` the member leaves the stack when either coil happens to be
    negative and stays, adding its own noise at the members' scale, when both
    are positive [inference: the band stack divides each member by its scale
    and the 25x rejection never fires on a member at the array level]. Wanted:
    flag "reversed" only below a correlation threshold (a reversed member sits
    near -1: -0.97 in the same test), and leave dead members to a coherence
    test. The Stacks tab's member check (`stackcheck.compute_check`) does not
    call a member reversed when it flags it dead. Found 5 Oct 2026 while
    testing the Stacks tab's member check (check batch).

30. Every Phoenix archive's H was left out of mt-workbench's polarity
    convention (lemimt's, the LEMI-423 chain's -1000, under which calibrated
    H is minus geographic), so every Phoenix Z sat 180 deg from the published
    impedances (xy -163 deg, yx +48 deg at Kalkaroo G5, 0.1-10 s) and M
    between a Phoenix and a LEMI-423 site carried -1, with no message
    [measured: calibrated H opposite at five Phoenix-LEMI pairs in every
    hour; the 11 S1 sites equal to AusMT's within 0.7 deg and 0.01 dex once
    180 deg is added; 7 of 8 S3 and 5 of 5 S2 Phoenix sites in the opposite
    quadrants on the single-site check, AusMT's standard at 9 of 9 and 5 of
    5; the stored volts and counts in phase]. mt-io's Phoenix H is
    geographic, as a reader's should be; `phoenix._channel_chain` had no
    stage putting it into the convention (upstream 81). Fixed in the working
    tree (the Phoenix H polarity fix, 8 Oct 2026, not yet committed):
    `phoenix_h_polarity`, gain -1, on every Phoenix hx hy hz chain; the
    samples stay as recorded. Archives built before it lack the stage (no
    `phoenix_h_polarity` in a channel's `filters`) and must be re-ingested,
    and every Phoenix Z and M in a tf folder made from them carries the old
    sign; process_rr.py and process_intersite.py name such an archive in a
    warning (`phoenix.warn_without_h_polarity`) until then. Found by the
    Kalkaroo S3/S4 QC (8 Oct 2026); record
    `2026_Natural_Source_IP\datasets\kalkaroo\results\phoenix_h_sign_fix_20261008\`.

32. With `data_root` stale or not mounted, process_rr.py takes every remote
    that has an archive as a virtual remote (`virtual = ... args.remote not
    in raw_sites and stacked.exists()`) and reads its raw archive as it is,
    so the remote's declared filters (`filters.yaml`) are not applied, with
    no message; the Process tab's filter line still says "(filtered archive
    ready)" for it. The local is not affected: it goes through `ingest_site`
    and `processing_archive` [measured 9 Oct 2026 on the Atlas survey copy:
    A06 rr A01 --dry-run gives remote_archive A01.h5 and virtual_remote
    True, while A01 declares filters and A01_f81e4c0e6.h5 exists; with the
    raw folders under `data_root` it would be the variant]. Masks were
    already moved to the remote's name for this reason (`remote_masks`). The
    sidecar's `filters` uses the same proxy (`_declared_filters`: None for a
    site not in `raw_sites`), so it records null for both sites even when
    the local was read from its filtered variant [measured: A01 rr A06, 9
    Oct, local_archive A01_f81e4c0e6.h5 with filters {"A01": null}; the 26
    Sep mainsnotch sidecar of the same pair lists A01's mains and notch].
    Found 9 Oct 2026 by the station-list fix (31). Fixed 9 Oct 2026:
    `process_rr.recorded_site_folders` maps every declared site that is not
    derived, a burst site or an observatory and has no raw folder to
    ``data_root/<site>``, so it is never virtual: it goes through
    `ingest_site` (which keeps its archive, 31), `processing_archive` (its
    filtered variant) and the filter records (`archive_status`,
    `_declared_filters`); process_intersite.py takes its raw sites from the
    same function, so its archive status and sidecar `filters` say what
    `processing_archive` reads. The dry run and the log print the archive
    each site is read from (`local_reads`, `remote_reads`) and the filter
    kinds the sidecar records (`filters_recorded`); a missing archive whose
    raw folder is not there either reads "missing, and no raw folder at
    <folder> to ingest from". Atlas A06 rr A01 under the stale root: not
    virtual, A01_f81e4c0e6.h5, A01's mains and notch recorded, every
    decision equal to the run with data_root on E:; the 6 h run exits 0 with
    them in the sidecar, and its Z differs from the run with the old
    resolution (zxy median 0.9 %; the largest change 164 % at 0.023 s
    relative to the new Z, or 110 % at 584 s relative to the old; nil at
    0.056-0.45 s, the change below 0.045 s and at long periods). A stack, an
    observatory and a derived remote resolve as before. Tests:
    tests/process_station_list_unit.py (S03 rr S01 and S01 rr S03 under raw
    folders present, stale and missing; `recorded_site_folders` reduced to
    the folders found trips it), tests/process_rr_cli_unit.py (data_root
    unmounted: E08 recorded, not virtual). The GUI's filter line
    (`stack_builder.RunOptions.describe_filters`) reads the declaration by
    name and needed no change; build_stack.py reads `site_dirs` only for its
    name check. Record
    `<workspace>/qc/reports/gui_station_list_20261009/revision/`.
33. A burst site as the remote is virtual whatever the `data_root`: its raw
    burst archive is read as it is, and neither the filters its recorded
    site declares (which `Survey.site(<site>H)` inherits and
    `processing_archive` applies when the burst site is the local) nor a
    filter record are written, with no message. Found 9 Oct 2026 by the
    verifier of the station-list revision (32): a mutant that maps burst
    sites like recorded sites names S03H_fb5727e15.h5 with S03's notch. Not
    fixed: whether a burst remote should take its recorded site's
    time-domain mains and notch filters (the bursts are 1-2 s windows) is a
    design question to settle before burst remotes are used.
34. An EDL electric line declared along the other channel's axis was
    ingested without a word as a standard dipole. TAS125 of Tasmania
    AusLAMP 2016 declares its sheet's Ex 270 / Ey 0 (the two lines on each
    other's inputs); the ingest of all sites of 22 Oct 2026 20:3x, expected
    to stop there, built `mth5/TAS125.h5` in 150.5 s with ex at
    measurement azimuth 0 (44.0 m) and ey at 90 (49.2 m): the west line,
    with the sign of a standard north line, as ex, and the north line as
    ey. The EDL path hands the azimuths to mt-io's dipole filter, which
    keeps a sign only and reads anything within 90 deg of nominal as
    standard; `_standardise_e_orientation`, which refuses an azimuth that
    is neither standard nor reversed, runs on LEMI-423 runs only. Fixed
    22 Oct 2026 (stage 1b, agent D, uncommitted):
    `ingest._check_e_azimuths` refuses, for every recorder and before
    anything is written, an ex azimuth other than 0 or 180 deg and an ey
    azimuth other than 90 or 270, and names the new key `swap_e` (the two
    inputs exchanged, each channel keeping its own dipole stage) for a line
    along the other axis (upstream 335). Test: tests/ingest_swap_e_unit.py E3. TAS125's
    archive of 22 Oct 20:2x is wrong (components swapped) until it is
    rebuilt with `swap_e: true` and the exchanged lengths and azimuths.
    The Burra survey.yaml declares ex 90 / ey 270 at Burra22, Burra60 and
    Burra62, which the LEMI-423 path refused per run before and the new
    check refuses up front.
36. EDL restart files whose stamps lie inside the file before them were
    ingested as runs that overlap in time, and set-up files recorded at
    another rate were ingested as if at the site's rate. Before the
    stage-1b rebuild the Tasmania AusLAMP 2016 archives held 134 such
    overlaps at 16 sites (`<workspace>/qc/h_azimuth/run_overlaps_before_rebuild.csv`;
    upstream issue 318 for TAS105's 17 s): restart files at power-limited
    sites (TAS103, TAS109, TAS110, TAS128, TAS135, TAS143, TAS150: an
    hourly file seamless with the files either side, and short files
    stamped inside it after the PC's power-up) and the set-up minutes of
    TAS138 and TAS146-TAS151, whose recorder.msg puts the data channels at
    100 s/s, so each 300 s stamp holds 30,000 samples, read as 50 min at
    10 Hz (and TAS106's first file, 60,000 samples in a 13 min spacing). Fixed 22 Oct 2026 (stage 1b, agent
    D, uncommitted): `ingest._edl_plan` trims a file stamped before the end
    of the samples kept so far (the earlier file's samples win, Tasmania
    ruling 10; a file wholly inside them is left out; the run comment's
    "overlap:" line names both files), and leaves out a stamp that
    recorder.msg puts at another rate when its files overrun the next stamp
    at the site's rate (`_other_rate_stamps`; the log alone is not trusted:
    TAS106, TAS131 and TAS221LP end on 1000 or 50 s/s set-ups while their
    files are 10 Hz). Test: tests/ingest_edl_overlap_unit.py O1-O5.
40. scripts/campaign.py's stage 2 stack is far shorter than the dry run
    says, or fails, when members have gaps or restarts: `stack_plan` takes
    every eligible member of the site's group, and the builder
    (`virtual._open_members`) takes ONE run per member, the run overlapping
    the local's record most, and spans the intersection of those runs, so
    one member with a gap, a restart or a short record cuts every stack of
    its group. The dry run's "common span" is the survey.yaml spans'
    intersection, not the runs'. Tasmania AusLAMP 2016 at 10 Hz (23 Oct
    2026, agent E; read with the builder's own reader,
    `<workspace>/logs/stage2/stage2_span_probe.log`, all sites in
    `qc/stage2/stage2_spans.csv`): TAS102 359 h against the dry run's
    525 h (TAS100's run gap of 10 Feb; with TAS114 in the group, every
    west stack was 67 h); TAS116 to TAS123 10.8 h against 203 h (TAS120's
    and TAS221LP's run choice); every phase-2 site and TAS146, TAS148
    "members do not overlap" (TAS110 29 runs, TAS143 22, TAS109 10);
    TAS147 34.5 h against 624 h. An `h_from` site is also a member of its
    donor's stack (TAS132 in TAS131's: the local's own magnetics in its
    reference). Wanted: members chosen by their runs (leave out the member
    whose best run cuts the span most, down to a floor of hours, as
    `<workspace>/qc/stage2/scripts/stack_windows.py` does), the dry run
    printing the span the builder will get, and an h_from site and its
    donor kept out of each other's stacks. Not fixed (the campaign was
    launched as briefed; the lead's ruling).
    Fixed 23 Oct 2026 02:2x (the lead's ruling 1 of 02:0x; agent E,
    uncommitted): `stack_plan` takes the local's eligible remotes (any
    group), less the plan's new `stages.stacks.exclude_members`, whose
    best run (`best_run`, as the builder picks it) covers at least 70 %
    of the local's record (`STACK_COVER`), the 8 nearest
    (`STACK_MAX_MEMBERS`); with fewer than 2, a 50 % floor
    (`STACK_COVER_MIN`) named in the row's note; the runs are read from
    the raw archives (`Campaign.site_runs`, h5py through
    `intersite.archive_runs`); the build's note, the dry run and
    summary.md give the span expected from the runs (`run_span`) beside
    the survey spans' one; a remote-only site joins the R stack only at
    the members' floor. Tasmania after the fix: every one of the 60 sites
    has a stack, 176-743 h from the runs (`<workspace>/qc/stage2/
    stage2_member_rule_tasmania10.csv`). Test: tests/campaign_unit.py
    item 20 (four mutations caught); item 3 now expects F (another group)
    among A's members. The donor of an h_from site is handled by the plan
    (Tasmania's exclude_members names TAS132).
41. scripts/campaign.py's `run_block` and dry run counted an rr row on a
    stack as done while its stack's build was about to run again: the rr
    row's inputs are the stack archive's mtime, which still matches the
    ledger until the build replaces the archive, so a stack rebuilt with
    other members (issue 40's fix, or a member's archive rebuilt) kept
    its rr product of the old stack. Found 23 Oct 2026 by the dry run of
    the stage 2 re-run (west: 10 rr rows "already done" beside 10 builds
    to run). Fixed the same day (agent E, uncommitted): `split_done`
    counts a job done only when none of its dependencies in the block is
    to run; run_block and the dry run use it. Test: tests/campaign_unit.py
    item 20 (a done rr row on STK_Au runs again when the build's inputs
    change; the mutation without the rule is caught).
44. scripts/campaign.py's stage 2 stacks were built from ONE run per
    member (`virtual._open_members` through scripts/build_stack.py), so
    after issue 40's fix chose the members by their best runs, a member's
    gap or restart still cost the stack every stretch beyond it. Tasmania
    AusLAMP 2016 (23 Oct 2026, agent I; `<ws>/qc/stage2_fixes/
    piece_gain_tasmania10.csv`, `piece_gain_tasmania1.csv`): west TAS102,
    TAS105, TAS107, TAS144 359.0 h where 500.9 h is shared by every member
    in two pieces; north TAS111 254.5 -> 368.7 h, TAS114 599.3 -> 666.0 h;
    phase 3 TAS146 422.0 -> 600.1 h, TAS148 421.7 -> 583.9 h; phase 2
    TAS137, TAS139, TAS145 571.8 -> 580.0 h; at 1 Hz the R stacks with CNB
    of the north wave 258.3 -> 350.4 h and 364.6 -> 382.6 h. Fixed the same
    day (uncommitted): `virtual.stack_pieces`, `_member_runs`, `_align`,
    `_open_pieces` and `build_synthetic_remote(min_piece_h=...)` build one
    run of the stack archive per piece (every stretch of the window in
    which every member is inside one of its runs, at least the minimum
    long; shorter ones left out and logged); build_stack.py
    `--min-piece-h H` (positional form only); campaign.py builds stage 2
    with `--min-piece-h 6` (`STACK_MIN_PIECE_H`), gives the pieces in the
    note, the dry run and summary.md (`run_pieces`), and adds ";pieces <n>
    (<h> h)" to the inputs of a build whose pieces are not the one-run span
    (`piece_marker`), so a re-run rebuilds only the stacks the rule
    changes. The stack's runs are named after the members' rate (sr10_0001;
    they were always "sr1000_0001"). The member rule (best run >= 70 % of
    the record) is unchanged. Tests: tests/stack_pieces_unit.py (new),
    tests/campaign_unit.py item 21; three mutations caught.
45. scripts/process_rr.py refused every rr on a stack of derived 1 Hz
    members (STK_<site>Lu, STK_<site>LRu) with "<site>L is at 1 Hz and
    STK_<site>Lu at 10 Hz": its rate check read `Survey.sample_rate_of`,
    which gives a name with no survey.yaml entry (a stack) the survey's
    rate, though the stack archive was at 1 Hz and each of its samples the
    mean of its 1 Hz members (STK_TAS100Lu: 0 of 1,889,800 samples off).
    Tasmania AusLAMP 2016's 1 Hz campaign, 23 Oct 2026: 94 of 94 stage 2
    rr rows failed. Fixed the same day (agent I, uncommitted):
    `process_rr.archive_rate` reads the rate the archive's runs record,
    used by `resolve` for a remote with no entry whose archive exists.
    Test: tests/derived_sites_rr_unit.py (a 1 Hz stack of two derived
    members is at 1 Hz and their mean, processes against a 1 Hz local; the
    rule before refuses it, the mutation; a true 10 Hz stack is still
    refused).
46. scripts/decimate_site.py wrote a derived entry without the parent's
    `channels:`, so the derived site took `defaults:`: TAS132L (TAS132
    declares [ex, ey] and borrows TAS131's hx, hy through `h_from`; no hz)
    read [ex, ey, hx, hy, hz], process_rr.py asked aurora for an hz row,
    aurora failed every decimation level on KeyError 'hz' and returned its
    legacy collection (upstream 340), and every TAS132L pair as the local
    stopped on "'TransferFunctionCollection' object has no attribute
    'impedance'" (22 rows, 23 Oct 2026). Fixed the same day (agent I,
    uncommitted): `decimate_site.held_channels` (the parent's channels,
    plus hx and hy with `h_from`) goes into the derived entry as
    `channels:` when it differs from `defaults:`; TAS132L's entry was
    given `channels: [ex, ey, hx, hy]` in place; and issue 42's check now
    names the outputs asked for. Test: tests/derived_sites_rr_unit.py (an
    h_from parent's derived site processes to a Z equal to the parent's at
    10 Hz; without the entry it stops on the named RuntimeError).
47. scripts/campaign.py's stage 1 overlap rule reads the survey.yaml
    spans (`is_eligible`, `overlap_hours`), not the runs, so a pair whose
    spans overlap while no run of one overlaps a run of the other is
    planned and fails in aurora ("Local: TAS128 and remote: TAS140 do not
    overlap, Remote reference processing not a valid option"): Tasmania
    TAS128/TAS140 and their `L` twins, 2 + 2 rows failed at every run of
    stage 1 (spans overlap 198.8 h). The stack member rule already reads
    the runs (issue 40). Wanted: eligibility by the runs' overlap
    (`Campaign.site_runs`), or such a pair listed as skipped with the
    reason. Open (23 Oct 2026, agent I).
48. A campaign row of a weighting (or config) that the plan no longer has
    stays in the ledger with its last status, and summary.md lists it
    under "Not done" beside the plan's own failures: Tasmania's tasmania10
    ledger keeps 22 failed `STK_<site>w` builds and 22 skipped rr rows
    from the first runner (04:55-05:10, the member rule before issue 40's
    fix), after `w` was dropped from the plan and every `STK_<site>u` of
    those sites was built and run. Read as current, they looked like 22
    stack failures of the member rule (agent I's brief, 23 Oct 2026
    06:2x). Wanted: summary.md (and the dry run) to separate rows outside
    the current plan ("not in the plan: 44 rows") from the plan's own.
    Open.
49. A plain-mean stack (`virtual._mean_stack`; campaign.py's stage 2
    `STK_<site>u`, `STK_<site>Lu`, `STK_<site>LRu`) adds its members'
    STORED values, so a member stored in other units than the rest
    carries another weight: Tasmania's CNB.h5 holds nT, the EDL `L`
    archives hold counts (142.857 per nT), so in each of the 34
    `STK_<site>LRu` ("the L stack with CNB") CNB enters at 1/142.857 of
    an L member's weight. Measured 23 Oct 2026 (agent H,
    `<ws>/qc/stage4_compare/scripts/h1k_stack_units.py`,
    `stack_units.csv`, `stack_cnb_share.csv`, `stack_units.png`): every
    stack's hx median equals the mean of g_m |H|_m (g 142.857 for EDL
    members, 1 for CNB) within 0.7 % (154 of 154); regressing each LRu
    stack on its Lu twin and CNB gives n/(n+1) and 1/(n+1) per nT
    (34 of 34), so CNB's share of the stack's variation field is
    0.01-0.3 % where 11-33 % was meant. The rr products against LRu equal
    those against Lu to 0.0002 dex and 0.01 deg (`kind_headtohead_
    summary.csv`): the plan's "stacks with and without CNB" test (PLAN.md
    stage 2 (b)) measured nothing. The same mechanism as upstream 105
    (sign), here for magnitude; the products' error scale is upstream 111.
    Wanted: stack members in one unit (each member's coefficient gain, or
    its filter chain at DC, applied before the mean; the stack written in
    nT), or refuse a member set whose stored units differ; correct the
    "uncalibrated by design (RR estimator is calibration-invariant)"
    station comment. The same stacks keep the members' DC offsets in
    float32 (upstream 112, `_mean_stack` unchanged): not measured here.
    Open.

50. scripts/campaign.py's stage 2 member rule (`stack_plan`) does not
    leave out the local's `h_from` donor: TAS132 takes TAS131's magnetics
    (h_from), and STK_TAS132u, STK_TAS132Lu and STK_TAS132LRu each hold
    TAS131 (TAS131L) among their eight members (the build rows' notes in
    both ledgers), so `TAS132 rr STK_TAS132u` has 1/8 of its own H in the
    reference: partly a single-site estimate, biased like one where the
    coils are noisy. `exclude_members` held TAS132 out of every stack, not
    TAS131 out of TAS132's. Tasmania stage 4 (agent G, 23 Oct 2026) left
    the three products out of the best-of candidates
    (`<ws>/qc/stage4/excluded.csv`). Wanted: a local's stack never takes
    its h_from donor, nor a site whose h_from is the local. Open.
51. scripts/process_rr.py's sidecar does not record the STFT window count
    behind each band: `process.band_windows` is computed for
    `drop_short_bands` (min_band_windows) and then discarded, and the
    EDI, XML and TF h5 hold none, so a delivery cannot flag the bands that
    rest on 2-3 windows (the long end of every full-record product).
    Tasmania Run 1 (agent G, 23 Oct 2026): the brief's `few_windows` flag
    (count under 4) could not be computed and is never set (README).
    Wanted: the sidecar's `band_windows` {period: count} beside
    `dropped_periods`. Open.
52. The campaign's product EDIs carry no channel geometry: every EMEAS and
    HMEAS line reads AZM=0.00 with zero electrode coordinates (ey and hy at
    0 deg, no dipole), though the archives hold ey and hy at 90 deg and
    the dipole lengths (TAS100.h5 run sr10_0001: ey measurement_azimuth
    90, dipole_length 46.5; `tf/TAS100_rr-TAS107_20261023-0129_tasmania10-
    default.edi` EMEAS ey AZM=0.00); the installed mt_metadata has the
    fork's azimuth fix (upstream 31), so the TF handed to the writer
    lacks the channels' azimuths. merge_best.py then warns "an EDI written
    before mt_metadata's frame fix of 2 Oct 2026", a wrong diagnosis for
    EDIs written on 23 Oct, and the merged EDIs repeat the lines. The frame
    is stated by ZROT/TROT and the INFO lines, so the values are right;
    a reader that rotates by the channel azimuths would not be. Found 23
    Oct 2026 (agent G, Tasmania stage 4; the Run 1 README lists it).
    Wanted: process_rr/products copy each channel's measurement_azimuth
    and electrode positions from the archive into the TF before writing;
    `frame_gaps` names the cause it finds. Partly fixed 23 Oct 2026 (agent
    G, Run 2 R3, uncommitted): `mt_workbench.products.archive_geometry`
    reads each channel's azimuth, tilt, dipole length and electrode
    positions from an archive, `set_channel_geometry` writes them into a
    TF's runs, and `edi_copy`, `write_edi` and `write_products` take a
    `geometry` argument (None: as before); test
    tests/products_geometry_unit.py (ex 48.5 m / ey 46.5 m written as
    X2=48.50 AZM=0 / Y2=46.50 AZM=90, hy AZM=90, hz DIP=90; its control
    without the geometry writes zeros). The Tasmania Run 2 EDIs were
    regenerated through it. Still open: process_rr.py and merge_best.py
    do not pass an archive's geometry yet, and `frame_gaps` keeps its
    wording.
53. scripts/merge_best.py cannot leave a mode EMPTY on purpose: a recipe
    without yx stops on "mode yx: no source listed" and a yx entry that
    gives no value stops on "a mode takes no period" (exit 2). Tasmania's
    TAS132 is delivered by xy only (the lead's ruling 7 of 23 Oct 2026), so
    agent G's g4_flags.py writes EMPTY over the merged EDI's six yx data
    blocks and adds the reason to INFO (the EDI before is kept). Wanted: a
    recipe key `empty: {yx: "<reason>"}` writing the mode EMPTY with the
    reason line. Open.
54. scripts/merge_best.py `--auto` ranks candidates by the relative errors
    their EDIs carry, so a stack product (errors about 1/143 of a site
    pair's, upstream 111) wins every band it is not dropped from:
    Tasmania TAS100 (23 Oct 2026, agent G, `<ws>/qc/stage4/proposals/
    probe_TAS100_auto10_with_stack.yaml`): STK_TAS100u took every band
    from 36 s to 14,712 s with "err 0.000" and a runner-up 60-130 times
    larger. Stage 4 ran the script without the stacks and the proposal of
    record through merge_best's own band_stats and choose with each
    stack's errors times its k (agent H's stack_units.csv). Wanted: an
    error scale per candidate (`--error-scale EDI=K`), or a refusal of a
    stack candidate with no declared scale, until the stacks are written
    in nT (49, upstream 111). Open.

55. A TF read back with `products.read_tf` and written again loses
    information through mt_metadata 1.0.10's EDI reader: each INFO
    processing parameter comes back without the first dotted part of its
    key ("mt_workbench.best_xy_1=..." as "best_xy_1=..."), so the rewrite
    drops every "mt_workbench." prefix and duplicates the frame lines
    (`edi_copy` no longer recognises them and adds its own), and FILEBY
    is read into provenance.software.name, which the writer then prints
    as the software's name. Found 23 Oct 2026 (agent G, Tasmania Run 2,
    regenerating the merged EDIs); worked around in
    `<ws>/qc/stage4_run2/scripts/g4r2_finalize.py` (`source_params` takes
    the lines from the EDI's text; software.name reset). Wanted:
    `read_tf` keeping the processing parameters as written (and the
    upstream issue reported). Open.

56. `mt_workbench.masks.FOUND_BY` is a closed list (time, polar, cluster,
    night, gate): `normalise` refuses any other origin and process_rr.py's
    `--mask-origins` refuses any other name, so an experiment cannot
    declare its own selections side by side in one masks.yaml and pick
    one per run (Tasmania stage 5's brief asked for origins stage5-coh,
    stage5-act, stage5-rnd, stage5-quiet). Worked around (agent L, 23 Oct
    2026): one scratch survey folder per selection,
    `surveys/tasmania_auslamp_2016/experiments/stage5/sel_<name>/`, each
    with its own masks.yaml (found_by gate, the origin in the reason).
    Wanted: found_by free text (or a `selection:` key) that
    `--mask-origins` matches, the GUI showing it as it shows the five.
    Open.
57. scripts/process_rr.py's sidecar does not record the band masks aurora
    did not apply: the fork's `window_mask_for_band` leaves a band
    unmasked when the masks would empty it (upstream 356), and the
    sidecar's `masks`/`mask_counts` list every declared entry as applied.
    Tasmania stage 5 (agent L, 23 Oct 2026): at 1 Hz the bands over
    16,384 s rest on 6-18 six-day STFT windows, so a day selection of
    60 % emptied 6 of the 8 verdict-window bands of every random draw at
    TAS100L and most sites; those bands were the whole record, and the
    product, its EDI and its sidecar say nothing of it (the log alone has
    "band left unmasked"). Wanted: the sidecar's `band_masks` {period:
    {windows, kept, skipped}} (the record `_BandMaskLog` already builds
    on the patch path), beside issue 51's window counts. Open.

58. scripts/decimate_site.py refuses a derived site as its source, so a diagonal
    site `<site>D` (scripts/diagonal_site.py) gets no 1 Hz copy through the
    script; agent M called `write_derived` and `survey_entry` directly on a
    scratch survey (TAS112DL, 27 Oct 2026). Wanted: a derived source whose
    parent is itself derived, the chain named in the run comment.

59. `mt_workbench.crosspower._roles` needs two electric lines, so a
    one-electric site (a diagonal `<site>D`, channels [ex, hx, hy, hz]) cannot
    be opened in the Cross-powers tab nor by the scripts that use
    `compute_windows` (27 Oct 2026). Wanted: roles that take one electric
    line with its azimuth.

60. scripts/merge_best.py `--auto` ranks the candidates of each
    quarter-decade band by the median relative rho error, and at the
    10 Hz short end that takes the campaign's stage-3 `noprewhiten`
    variant, which is biased low there: about 1 dex in rho at 1.8-5.7 s
    with phases near 20 deg (TAS130 xy rr TAS134: log10 rho 0.0-0.3
    against 1.5-1.8 for the default product, while its relative error is
    the smallest of the site's 22 candidates). Tasmania stage 6, agent A
    (31 Oct 2026, `<ws>/qc/stage6/a/`): the same ranking by E over every
    candidate took the noprewhiten variant at 62 of 120 site-modes and
    lost to P on a held-out consensus at 42 of 60 (xy) and 46 of 59 (yx)
    sites; Run 3's recipes take it at 36 W period-modes (TAS128 xy and yx,
    TAS146 xy, TAS148 xy and yx), and where Run 3 differs from P inside
    0.40-10.2 s (5 sites) it is worse than P at 7 of 10 site-modes
    (`wins_A3.csv`, `run3_owners.csv`). The same mechanism as upstream
    183 (an unwhitened estimate biased low at short periods with small
    error bars). Wanted: the variant never a candidate of the short end
    (or of any band below the variant's own reach), or a level-and-phase
    check against P in each band before a pick (`drop_reason` compares a
    candidate's band with that candidate's own neighbouring bands, so a
    smooth trough 1 dex low with phases in quadrant passes). Open.

61. `engine_mantle.process_pair` writes into MANTLE's fine-grid EDI the INFO
    line "channels read by io.mth5_reader: H = counts*K*0.001 nT, E =
    -counts*K/L mV/km (the archive's lemimt convention carries the sign on H
    instead; Z is the same)" whatever the archive's chain, so a product of a
    chain the reader takes by its units (upstream 470's proposal: the
    Tasmania EDL archives, recorded microvolts / product of the chain's
    gains, the chain's own signs, no default polarity) states a calibration
    and a sign convention it did not use (`<ws>/tf/TAS100_rr-TAS107_
    20261031-2335_stage6-m-diff_fine.edi` line 23; Tasmania stage 6, agent
    M, 31 Oct 2026). The seam also reaches neither MANTLE's native-level cap
    nor its detrend: `MantleOptions.native_max_samples` (2,000,000 samples
    whatever the rate) keeps the first 55.6 h of a 10 Hz window at the level
    that holds 0.5-5 s (upstream 162's 1 Hz case, here at 10 Hz); agent M set
    it through a wrapper (`<ws>/qc/stage6/scripts/m_process_rr.py`). Wanted:
    the INFO line taken from the reader's classification of each channel
    (LEMI-423 or by units), and process_rr flags for the native cap (or a cap
    that follows MANTLE's own rule: B423 at 500 Hz and above) and the
    detrend. Open.

62. scripts/process_intersite.py refuses any local, base or remote at a
    different sample rate from the others (`Refused(f"{local} is at
    {rate:g} Hz and {site} ({label}) at ...")`, line 649), and
    scripts/decimate_site.py takes whole factors of 2 or more only
    (`stage_factors`, line 145), so a 150 Hz Phoenix site and a 1000 Hz
    LEMI-423 site cannot meet in one T, M or Z above 50 Hz (150/3,
    1000/20). Reproduction (Kalkaroo dome scout, 31 Oct 2026, dry runs
    only): PL KD-C5 / KD-C4, LP KD-C4 / KD-C5, LL with the Phoenix remote
    KD-RR_210428, PP with the LEMI remote KD-RRa_210428, each exit 2;
    `datasets/kalkaroo/results/scout_dome_S3S4_20261031/logs/
    q5_dryrun_{c,d,e1,e2}.log`. For Kalkaroo S3 this closes all 542 mixed
    pairs. A missing capability, not wrong output. Wanted, if the mixed
    pairs are wanted: a common-rate path (a resampled derived site, or
    resampling inside process_intersite) with its own identity test. Open.

63. Nothing compares an archive's stored clock offset with survey.yaml's
    `clock_offset_s`: `ingest.archive_clock_offset` (ingest.py line 1458)
    has no caller in src\ or scripts\, only tests\
    ingest_clock_offset_unit.py. A declaration edited into survey.yaml
    without a re-ingest would therefore run every product on the old time
    base with no message (Kalkaroo's proposed LEMI-423 -0.0326 s; 0 of 46
    archives store an offset). Found by reading the code in the Kalkaroo
    dome scout (31 Oct 2026, reader 3); not executed. Wanted: process_rr
    and process_intersite read the stored offset of every member and
    refuse when it differs from the declaration. Open.

64. process_intersite `--dry-run` accepts a window that starts before the
    base archive's first sample and reports the samples as held: form b
    of the Kalkaroo dome scout on survey.yaml's start (2021-04-30 03:00:58,
    the LEMI-423 B423 file-name epoch, 5 s before KD-C4's first sample)
    reports 161,135,000 samples against 161,130,000 for the archive's
    window, exit 0 (`datasets/kalkaroo/results/scout_dome_S3S4_20261031/
    skeptic/tables/sk5_dryrun_b_yaml.log`, 1 Nov 2026). A dry-run
    observation; whether a real run clips, pads or fails is not known.
    Wanted: the dry run clips the window to the members' spans and says
    so. Open.
65. `mt_workbench.crosspower.bin_windows` gives a level's sums only per
    display group of m_L base chunks, and at a 600 s chunk level 2 of the
    10 Hz scheme (the 7.2 and 9.1 s bands) has m_L = 3, so a selection of
    10-min chunks at 6.4-10.2 s cannot read one value per chunk from the
    result; stage 5's `s1_select.sums_per_chunk` raises there. Tasmania
    stage 6, agent B (1 Nov 2026): `<ws>/qc/stage6/scripts/b_select.py`
    `chunk_sums` copies bin_windows' edge and item-to-chunk rule and sums
    every level per base chunk (equal to sums_per_chunk at 3600 s to
    8e-15, check B2). Such a chunk holds 5-6 level-2 windows (about 29
    degrees of freedom over the two bands), so its coherence has a floor
    near 0.03 against hourly medians of 0.006-0.05 there. Wanted:
    `bin_windows(..., per_chunk=True)` returning every level's sums and
    window counts per base chunk beside the display groups. Open.

66. A delivered EDI's EMEAS/HMEAS ACQCHAN follow whichever product
    merge_best lists first: `merge_best.build_tf` copies the station and
    channel metadata of the first xy source only, and
    `products.write_edi(tf, geometry=archive_geometry(...))` rewrites AZM and
    the dipoles from the archive but takes ACQCHAN from the TF's channel
    metadata. The Tasmania products of 23 Oct 2026 carry no channel numbers
    (their EDIs: ACQCHAN 1.0-5.0, ey and hy AZM 0, hz DIP 0), those of 1 Nov
    (stage6-c-hcoh20, the tree as it stands) the archive's (TAS342LP: ex 3,
    ey 4, hx 0, hy 1, hz 2; ey and hy AZM 90, hz DIP 90). Agent R4B's first
    Run 4 trial (`<ws>/qc/stage4_run4/r4b/trial/`, 1 Nov 2026), with the
    masked product as the first xy source, delivered ACQCHAN 3, 4, 0, 1, 2
    where Runs 1-3 deliver 1.0, 2.0, 30, 40, 50 (upstream 497) at 33 sites,
    and the check on the measurement lines failed; the Run 4 recipes keep a
    23 Oct product first by an entry with the empty range 10.2-10.2 s
    (`<ws>/qc/stage4_run4/scripts/r4_recipes.py`, ANCHOR). So the ACQCHAN of
    the delivered files are not the logger channels, and a recipe's order
    can change them. Wanted: `archive_geometry` to carry each channel's
    number and `write_edi` to write ACQCHAN from it, as it writes AZM and
    the dipoles, so a delivered EDI's measurement lines come from the
    archive alone. Open.

67. survey.yaml's `start` for every LEMI-423 site of Kalkaroo S3 and S4 is
    5.0 s before the archive's first sample: 46 of 46 sites (the dome
    scout's `tables/site_spans_q3.csv`, column dstart_s), for example
    KD-RRa_210428 2021-04-28T00:44:07Z (survey.yaml line 3129) against a
    first sample at 00:44:12. The start is the B423 file-name epoch
    [inference]. A window taken from the declaration therefore starts 5 s
    before the data: the LEMI timing survey's builder took KD-RRa_210428's
    window from survey.yaml and its 12-hour sample moved by 5 s against the
    archive's (the gate pair's lag by +0.0044 / +0.0016 ms, 0.34 and 0.06
    of its errors; `datasets/kalkaroo/results/lemi_timing_survey_20261101/
    README.md`, Provenance, 1 Nov 2026). Entry 64 is the dry-run side of the
    same offset. Wanted: the ingest or a survey check reports the declared
    start against the first sample, and the declaration states which of
    the two `start` holds for LEMI-423 sites. Open.

69. scripts/decimate_site.py labels every Phoenix-derived sample 1.4667 ms
    late. `run_grid` (line 274) takes the input sample nearest the run's
    first whole UTC second as that second (`k0 = int(round(exact))`) and
    stamps the derived run from it; a Kalkaroo Phoenix 150 Hz archive sits
    0.22 of a sample off whole seconds (the ingest's clock_offset_s
    -0.1148 s is 17.22 samples), so the derived stamps are late by 0.22 of
    a 150 Hz sample. The tool warns ("its samples sit +0.2200 samples off
    whole seconds -- the nearest sample is taken as the second", line 339)
    but corrects nothing, and the run comment does not record it.
    Reproduction (the Kalkaroo PL 50 Hz path probe, 2 Nov 2026, on a survey
    copy and archive copies; `datasets/kalkaroo/results/
    pl_probe_50hz_20261102/tables/timebase.csv`, README.md):
    `decimate_site.py <copy> KD-G1 --rate 50 --force`, and KD-H1,
    KD-RR_210428, KD-C5; the lag of each derived site's channel against its
    source over one hour (cross-spectrum phase slope 0.5-10 Hz, 56 segments
    of 64 s placed by their stamps) reads +1.4667 to +1.4669 ms; the four
    LEMI-423 sources (1000 Hz, on whole seconds) read within 0.0004 ms of 0
    [measured]. It cancels in a pair of two Phoenix-derived sites (the same
    0.22 sample at every Phoenix 150 Hz archive [inference: 4 of 4 here]);
    in a Phoenix-LEMI pair it is a phase of 360 f x 1.4667 ms, 0.53 deg at
    1 s and 5.3 deg at 0.1 s [inference]. The probe's mixed pair KD-C5L |
    KD-C4L reads the LEMI late by +30.62 +- 0.50 ms against study T's 32.6,
    +31.13 expected with this labelling [measured: the probe's
    provenance.json r1]. Silent wrong output for any source off whole
    seconds. Wanted, before any Phoenix-LEMI tie of record: the fraction
    kept (a fractional-delay resample, or the shift applied in the FIR), or
    the derived run stamped on the source's own grid; with a test that a
    Phoenix-derived site's lag against its source reads 0 within 0.001 ms.
    Open.

70. scripts/decimate_site.py copies the source station's metadata into the
    derived station (`station_out.metadata.update(station_in.metadata)`,
    line 323), its provenance comment included, so the ingest's clock note
    travels with it: `ingest.archive_clock_offset` (ingest.py line 1500)
    reads -0.1148 on KD-G1L, KD-H1L, KD-RR_210428L and KD-C5L, whose samples
    carry no shift of their own, while `Survey.site` refuses clock_offset_s
    on a derived entry (survey.py lines 934-939, "declare the offset on
    <parent> and re-ingest it"). Reproduction: the PL probe's check C6
    clause (r), `tables/timebase.csv` column derived_archive_offset_s (the
    4 Phoenix-derived -0.1148, the 4 LEMI-derived 0.0; the sources -0.1148
    and 0.0; the data lags of entry 69 show the shift inherited once)
    [measured]. Harmless today, since archive_clock_offset has no caller
    (entry 63); once 63's stored-against-declared check is built, a derived
    site read literally would be refused, stored -0.1148 against a declared
    0.0 [inference]. Wanted: 63's check compares a derived site's stored
    offset with its parent's declaration, and the derived station's
    provenance says the note is the source's. Open.

71. scripts/decimate_site.py's docstring says a derived run "starts at the
    first whole second at least that reach inside its source run" (lines
    29-30); `run_grid` (lines 254-279) starts it at the source run's first
    whole UTC second at or after its first sample, plus ceil(reach x rate)
    / rate. From KD-G1 sr150_0001 (first sample 02:30:15.885200) the
    derived run starts at 02:30:16.200, and from KD-C4 sr1000_0002
    (04:31:02.001) at 04:31:03.300 [measured: the PL probe's
    tables/timebase.csv, residual 0 s on 15 of 15 runs]; the docstring's
    rule would give 02:30:17 and 04:31:03 [inference]. The derived survey
    entry's `start` and `end` are written with ISO = "%Y-%m-%dT%H:%M:%SZ"
    (line 108), cut to whole seconds: KD-G1L's entry starts at
    2021-04-29T02:30:16Z, 0.2 s before its first sample (0.3 s for a 1000 Hz
    source), and `survey_entry` (line 507) adds one sample interval to an
    end already cut [measured: the probe's provenance.json
    survey_copy_entries_added against timebase.csv derived_run_start; code
    read]. The same family as entry 67 (a declared start before the first
    sample). Wanted: the docstring states the code's rule, and the entry's
    span is written to the sample. Open.

72. `mt_workbench.bands.site_min_period` gives a site slower than the
    survey max(survey min_period, 4 / rate) (line 85), which is off the
    survey's band lattice, while a faster site takes the lattice's shortest
    period at or above 4 / rate (lines 80-84). At 50 Hz on Kalkaroo (survey
    150 Hz, min_period 4**(22/6)/6000 s) that is 0.08 s: the dry run of
    KD-G1L | KD-H1L at the default lays 49 bands from 0.0898 s, none on a
    period of the 150 Hz product it was to be compared with (0 of 49), so a
    50 Hz product can neither be compared with nor merged
    (merge_tensor_bands.py) into the 150 Hz and 1000 Hz ones; with
    `--min-period 512/6000` (0.08533 s, lattice k = 27) its 48 bands are all
    on the lattice [measured: the PL probe's tables/rows.csv rows
    a_dry_default and a_dry, provenance.json a_band_layouts;
    logs/children/04_a_dry_default.log, 05_a_dry.log]. A 30 Hz site
    (Kalkaroo S5) falls off the lattice the same way [inference: the
    planner]. Silent: the row runs and writes products. Wanted: the slower
    branch snaps to the lattice as the faster one does. Open.


73. **`_edl_own_files` (mt_workbench.instruments) keeps a previous deployment's
    files when the folder's recorder.ini names that deployment.** The rule keeps
    only the files named for recorder.ini's `station_long_identifier`; a PR6-24
    keeps the last deployment's config on disk, so a GA-packaged site folder can
    carry an ini naming the station before it. AusLAMP Victoria standard copy
    (`E:\MT_Timeseries_DATA\MT_Victoria_AusLAMP_2013_2018`, GA eCat 150806
    `EDL_raw` layout kept): VIC041's ini says VIC66 and the rule keeps 1 file (a
    9 s BX of VIC66) and leaves out 2,975 VIC41 files; VIC057 (ini VIC84) keeps
    120 and leaves out 6,425; VIC086 (ini VIC124) keeps 120 and leaves out 3,910
    [measured, stage 0 of 2 Nov 2026, `surveys/victoria_auslamp_2013_2018/notes/
    stage0/span_check.csv`]. Effect: `span` and so `scripts/new_survey.py` write
    the wrong `start:`/`end:` (VIC057 1,269 h short), and an ingest would archive
    the other station's record under the site's name, with only a warning.
    Six more Victoria folders carry a foreign ini that no file matches (VIC038,
    039, 040, 042, 050, 073) and fall to the existing every-file-kept branch;
    VIC100's ini names VIC100 and its five stray VIC1003 files are rightly left
    out. Wanted: when the folder's own name (digits compared without leading
    zeros, case-insensitive: VIC041 = VIC41) matches a station among the files,
    keep that station; else keep the ini's station only when it is the
    plurality of the files, otherwise the plurality, each departure from the
    ini warned with both names and counts. Tasmania's standard copies never met
    this because `scripts/edl_unpack.py` moves an ini naming another station to
    the records folder. Found 2 Nov 2026 by agent A's A3d span check against
    the workbook trial's table.

    Corrected and fixed 2 Nov 2026 (agent D, `surveys/victoria_auslamp_2013_2018/
    notes/stage0/fix73_REPORT.md`): the ini is NOT a previous deployment's. Every
    file at the nine folders carries the ini's station in its own header, and the
    files named for it fill a day the site-named files lack (VIC057 2013-11-23,
    VIC086 2013-12-10; VIC041's is a 9 s fragment), with that day's .gps at the
    site's position: GA renamed the files to the published site names and missed
    one day folder. Fix: `_edl_own_files` keeps the station named like the site
    folder (digits compared as integers, `_edl_station_key`), else the ini's
    station when it is the plurality, else the plurality; each departure warned
    with both names and counts; `tests/edl_own_files_unit.py` (11 cases, the old
    rule restored as the mutation: a, d, h, i, j trip); `tests/ingest_unit.py`
    amended at its lines 1226 and 1275, which encoded the old rule. Real data:
    only VIC041, VIC057, VIC086 change among 141 Victoria and Tasmania folders.
    The missed days stay out of the archive until a decision whether the standard
    copy renames them (open.md 23). Fixed in the working tree, uncommitted.

74. **`scripts/h_azimuth.py --neighbours` reports a wrong attitude difference on
    archives already turned by `rot_h`.** `neighbour_columns` sets
    `azimuth_neighbour = azimuth_sensor(base) - phi`, with `azimuth_sensor` in
    the sensors' own frames but `phi` fitted from the archives as built, so on
    turned archives every difference is off by (rot_h_base - rot_h_local).
    AusLAMP Victoria stage 0 smoke test, VIC006, VIC008, VIC010 after the
    rebuild with their keys: differences -7.3, +7.7, +169.2 deg, flagging all
    three; the same pairs on the sensor-axes copies: -4.2, +4.3, -12.6 deg
    [measured, `surveys/victoria_auslamp_2013_2018/notes/stage0/SMOKE_README.md`
    S2c]. The docstring says both angles are "in the sensor frames". Wanted:
    turn phi back by the archives' recorded rot_h (`ingest.archive_rot_h`) before
    the subtraction, or refuse a turned archive with a message. Tasmania's
    stage 1b ran the check before its rebuild, so it never met this. Found
    2 Nov 2026 by agent C.

76. **An EDL run is written as contiguous across samples the reader did not
    return (SILENT WRONG OUTPUT; the library half is upstream 525).**
    `mt_workbench.ingest._edl_plan` plans an hour from `count_samples` (the sum
    of every trace's npts, 36,000) and the run writer concatenates whatever
    `mt_io.uoa.pr624.read_edl_miniseed` returns; that reader keeps `stream[0]`
    after `merge(method=0)`, so a first-hour file holding two trace ids (the
    logger's previous and new station/location codes) yields 1,800 samples for
    a planned 36,000, and every later file of the run is placed early by the
    difference, with no warning. AusLAMP Victoria stage 1: 11 folders hold such
    a first-hour file; 7 archives of record are written 28-57 min early
    (VIC054 -3,420 s over the whole 789 h record; VIC059 -2,280; VIC060 -1,680;
    VIC061 -2,340; VIC074 -3,060, each whole record; VIC063 -2,640 and VIC078b
    -3,420 on their first runs); VIC011, VIC052, VIC087 lose their first 2-15 min
    because the later trace is the one kept [measured, agent E,
    `surveys/victoria_auslamp_2013_2018/notes/stage1/defects_found.md` D-1,
    `<ws>/qc/stage1/E1_multitrace_effect.csv`; the lead reproduced VIC078b:
    1,800 of 36,000 kept, the archive's first run ending 57 min short]. Every
    remote reference, lag and variation-field number at those sites is invalid.
    Wanted: after each file's read, compare the samples returned with the
    planned count and the next stamp, and refuse the run (or split it there with
    a message naming the file) on any mismatch, so no run is ever written as
    contiguous across samples it did not get; a unit test with a two-trace
    miniSEED file written by obspy. Tasmania's EDL folders not yet scanned for
    the same first-file pattern (the TAS100 sample deficit of its stage 7 may be
    this). Found 2 Nov 2026 by agent E (E1 coverage at VIC078b 0.888).
    Fixed 2 Nov 2026 (agent G, `surveys/victoria_auslamp_2013_2018/notes/stage1/
    fix76_REPORT.md`, with the reader half upstream 525 applied to the fork):
    `instruments.edl_record_start` and `_edl_plan`/`_edl_run_spans` place a stamp
    at its record's start (the deployment trace's), and `ingest._check_edl_read`,
    called right after `read_run` and before the restart trim, refuses a run
    whose read count or start differs from the plan, naming the site, the file
    and both numbers; the run comment carries `deployment_test_run:`.
    `tests/edl_two_trace_unit.py` (4 cases; the pristine pair writing the D-1
    shift is the mutation). Scratch rebuilds read back from the archives:
    VIC078b's first run 05:03:00 to 16:45:59.9 (389,400 -> 421,800 samples),
    VIC054's record ending at its files' end, VIC011 unchanged; the next-file
    shift 0.0 s where it was -3,420. Tasmania's 60 folders are all ASCII, so
    this defect cannot occur there (the TAS100 deficit is something else).
    Applied to the working tree, uncommitted.

81. **A PR6-24 boot file at another rate is archived as a run at the site's rate
    (SILENT WRONG OUTPUT, small; handled on the data side).** EDL files carry no
    rate; `instruments.edl_sample_rate` gives one rate per site and `_edl_plan`
    reads every file at it. A PR6-24 boots at 10 Hz for its first minutes
    (recorder.msg: channels "changing to low gain 10s/s" one by one, then to
    1000s/s), so its 6-120 s boot files, read at 1000 Hz, become runs of 60 to
    1,200 samples labelled 1000 Hz with their time compressed a hundredfold; a
    run is not contiguous with its neighbours, so each becomes its own run and
    nothing refuses it. The overrun guard of `_other_rate_stamps` (TAS151,
    files FASTER than planned) cannot see a SLOWER file: it never overruns.
    Tasmania broadband 2016 pilot: Tas-W303's archive held runs sr1000_0001-0007
    of 60/120/600/610/160/600/1,200 samples (its log: `TAS303_160201233544 6
    seconds` = 60 lines), W301 5 such runs, W313 4, W315 2, the remote a
    300-sample block; aurora then logged 522 "Window is longer than the time
    series" errors over six products [measured, the lead, `surveys/
    tasmania_broadband_2016/notes/stage1/README.md` B6c]. Effect on the
    products negligible (a few dozen windows in 1.7 million). A planner rule
    was built and proven on a scratch copy (agent F: log duration -> file rate,
    unlogged <= 3 s within 30 min = boot, join guard; 21/21 tests, W303's long
    run bit-equal) but NOT APPLIED: decided 3 Nov 2026 "just remove the 10 Hz
    data, KISS", so the 88 boot stamps (520 files, 22 sites, all <= 3,000
    samples, all within 32 min of each record's start) left the raw tree for
    the sibling `..._excluded_10Hz\` folder, with a manifest and a recount
    (`notes/stage1/excluded_10hz_files.csv`, `exclude_10hz_files.py`,
    `verify_10hz_census.py`); the unapplied patch and its test are kept there
    as `*_NOT_APPLIED.*`. Any 1000 Hz EDL survey must do the same at its stage
    0 (the Northern transect: 79 such blocks). The census found no boot file
    at the 10 Hz surveys (Tasmania AusLAMP, Victoria, Stuart Shelf) that the
    rule would have removed; Hillside's 1000 Hz phases hold 50 Hz boot files
    of the same kind (HS021 300 samples in 6 s), already in its archives.
    Found 3 Nov 2026 (agent B, lead-verified on the raw files).

82. **The filtered-copy layout doubles every archive for a cache the owner does not
    want.** Since 745f8d0 (15 Sep 2026) `ingest_site` writes the raw recording
    only and `processing_archive` reads a filtered copy `<site>_f<hash>.h5`
    built by `build_variant`, refusing an archive with filters applied ("old
    layout", `archive_filter_kinds`). The copy is a cache for surveys whose
    filter lists change often and whose raw ingest is slow (Morocco's Phoenix
    lines); Tasmania broadband 2016 pays 200 GB of duplicate archives and a
    25 min copy of the 27 GB remote for a seven-minute re-ingest it will not
    need [measured, 3 Nov 2026]. Decided 3 Nov 2026: "the filters should be applied
    to the h5 file, not creating a new h5 file for the filtered data, which was
    the point of having filters.yaml so the actual filters are recorded."
    Wanted: a single-archive mode: `ingest_site.py --filtered` (or the default
    when the site declares filters) applies the declared list while writing
    `<site>.h5` and records it in the run comments as the variant does
    (`_FILTERS_PREFIX`, the hash); `processing_archive` accepts an archive
    whose recorded filters equal the current declaration, and when they differ
    (or `--no-filters` is asked of a filtered archive) says so and names the
    re-ingest command instead of building a copy; `variant_ready`'s freshness
    record moves into the archive. The refusal of a MISMATCHED filtered archive
    stays. Surveys with raw archives (Morocco, Victoria, Tasmania AusLAMP) are
    unaffected; the GUI's Build MTH5 and the campaign's stage 0 follow the same
    rule. To be done after the Tasmania broadband v1 run completes (decided:
    "Finish v1 first"); the survey's duplicate raw archives then go on his word.
    Found 3 Nov 2026 (decided).

83. **A synthetic-remote stack is written with no filter chain, so every
    transfer function processed against it carries impedance errors about
    1e-5 of their value (the stack's response in microVolt per nanoTesla).**
    `virtual.build_synthetic_remote` read each member's hx and hy as stored
    (microVolt at the logger input, under an applied chain of the coil's
    response table and a nanoTesla -> microVolt coefficient of 400000 at the
    Tasmania broadband members) and wrote the stack as float32 `digital
    counts` with `filters: []`, its station comment saying "uncalibrated by
    design (RR estimator is calibration-invariant)". The estimate is
    invariant; aurora's remote-reference error is not (upstream 111, 116):
    `TRME_RR.compute_inverse_signal_covariance` is `(Z'X)^-1 (X'X) (X'Z)^-1`,
    which a factor R(f) on the remote divides by |R|^2. Against `STK_W304w`
    the Tas-W304 product's ZXY.VAR at 180 Hz read 9.0e-16 where the
    single-partner product's read 1.0e-4 (sqrt ratio 3e-6; the chain's
    1/|R| there is 2.5e-6), and err(stack)/err(partner) ran 3e-6 to 1.1e-4
    over 1-30 s, following 1/|R(f)| (2.7e5 microVolt/nT at 1 s, 1.2e4 at
    30 s) [measured, surveys/tasmania_broadband_2016/notes/stage2/
    README_deadband.md, 4 Nov 2026]. Effect: a stack cannot ship as a
    remote, the dead-band trial's criterion (b) was invalid for its arm 3,
    and any error-weighted use of a stack product (inversion weights,
    best-of merges, error floors) is wrong by 1e4-1e6. Fixed 4 Nov 2026
    (uncommitted; notes/2026-11-04_calibrated_stack/): the stack's hx and
    hy carry the members' common filter chain and units
    (`virtual.calibration_plan`: the first member's chain, every other
    member's response compared with it on 241 frequencies from 1e-4 Hz to
    Nyquist; a constant ratio scales the member onto the reference before
    the median, the coherence and the sum, a ratio varying with frequency
    refuses the build, members with no chain give the uncalibrated stack of
    before with a warning and a station comment that says so);
    `build_stack.py` prints the chain and the scales. Test
    tests/stack_calibration_unit.py; the real check on `STK_W304wc` and
    `STK_W315wc` is in the note's README: samples byte for byte the 3 Nov
    stacks', the chain of the first member declared, err(stack)/err(partner)
    median 0.82-1.03 over 1-30 s and 0.01-100 s (was 1.2e-5 to 1.7e-5), and
    Z moved by 0.1-0.5 % in the dead band (under 1 sigma over 0.1-3000 s),
    read as the chain acting as a per-bin weight within a band rather than
    the constant the estimator cancels. Not touched: 116's part (the RR
    covariance's middle factor is the local's power, so the errors against
    a remote whose noise differs from the local's are still too small),
    which is aurora's; and the deconvolution of members of different coil
    models, which the refusal names. Found 17 Oct 2026 (upstream 111, Stuart
    Shelf), met again 3 Nov 2026 (Tasmania broadband dead-band trial).

84. **`decimate_site.py` leaves a stale `channels:` on a derived entry when the
    parent's channels change (SILENT WRONG OUTPUT: a tipper lost).**
    `decimate_site.survey_entry` leaves `channels` out when the held list equals
    `defaults:`, and `rewrite_sites_block` merges into the old entry, so the
    previous list stays: VIC081 gained hz (Ruling 2 (c)), its rebuilt VIC081L
    archive holds hz, and the entry kept `[ex, ey, hx, hy]`, so
    `process_rr.output_channels` gave no 1 Hz tipper. Workaround: the stale key
    deleted by hand under the survey.yaml protocol (Victoria AusLAMP, 4 Nov 2026,
    `notes/stage4/README_run2_prep.md`). Ask: `decimate_site` writes the
    `channels` key explicitly, or deletes a stale one (a None value in
    `rewrite_sites_block` drops the key). Found 4 Nov 2026 by the Run 2
    preparation at VIC081L.

## Unclear failures (a traceback or a silent wait where a message belongs)

5. Variant build while the variant is held open: two tracebacks
   (PermissionError on `os.replace(.h5.part -> .h5)`) and a 5.3 GB `.part`
   left behind; the cleanup targets the good variant. `ingest.build_variant`,
   `ingest_site._remove_partial`. Case 1b. Fixed in bc80846.
6. Dead remote (no time overlap): a 12-line mth5 traceback after a
   resolution block that says "window: full overlap". `process_rr.resolve`:
   compare the spans in the dry run. Case 4. Fixed in 05fc5cd: exit 2 with
   both spans (survey.yaml start/end, else the archive's runs), dry run too.
7. Memory gate above the machine's RAM waits for ever with one log line every
   300 s. `campaign.py` `Runner.gate`: refuse at start (exit 2) when
   `min_available_gb` exceeds the machine. Case 7. Fixed in efd4d30.
8. `campaign.py --stage 0 --dry-run` lists a current variant as "to build"
   when the ledger has no done row for it. Case 2c. Fixed in 98dd681, which
   also names a missing raw archive and lists an unreadable variant file.
9. `process_rr --dry-run` words a missing raw archive the same as a present
   one ("raw: <path>, variant: to build"). Case 9a. Fixed in 05fc5cd
   ("raw: <path> (missing: ingested from <raw folder> first)").
10. A missing workspace folder opens the survey in the GUI with "0 with an
    MTH5 archive" and no workspace error (GUI bench control). Fixed in
    b8f8477: a non-modal warning when the workspace and its parent folder
    are both missing; a workspace not made yet opens and fetches as before.
22. A masks.yaml entry whose `found_by` is not in `masks.FOUND_BY` makes
    every mask of its site unreadable, and the error names neither the site
    nor the entry. Nador's masks.yaml (the author's file) gives P3S6 `found_by:
    dive` (its line 10); `masks.load_masks(survey, "P3S6")` raises "mask
    found_by must be one of ('time', 'polar', 'cluster', 'night', 'gate'),
    not 'dive'" [measured 5 Oct], so the Process tab's masks switch reads
    "(masks.yaml unreadable)" for any pair with P3S6 and process_rr with
    masks would refuse it; `read_document` parses the file without
    complaint. Wanted: `dive` in `FOUND_BY` (dives now propose masks) or
    the entry changed, which is a decision, and an error naming the site
    and the entry. Found 5 Oct 2026 while mapping the data for the Stacks
    tab, whose availability chart catches the error per site. The same
    defect is upstream 71 (`upstream_issues.md`), found by the Nador Z-tie
    stage's dry-run check; P3S6's Z rows run with `--no-masks` meanwhile.
23. The Process tab's StackBuilder names a stack `STK<station>`
    (stack_builder.py line 138, e.g. STKD02, which tests/gui_smoke.py line
    2711 asserts), but `masks.is_stack` tests the prefix `STK_` (masks.py
    lines 638-648) that campaign.py's stacks carry. A GUI-built stack is
    therefore not a stack to `RunOptions.describe_masks` or to process_rr's
    mask rule: both look for a masks.yaml entry named STKD02, find none and
    apply nothing, the right result today by accident [inference from the
    code]. The Stacks tab batch replaces the name field with stacks.yaml
    recipes, whose names must start with `STK_`
    (docs/gui_stack_tab_design.md, 13.4). Found 5 Oct 2026.
    Resolved by 01ca477 (merged 7ef3d16): the Process tab's StackBuilder is
    a recipe picker with no name field, recipe names match `stacks.NAME_RE`
    (`STK_...`), and tests/gui_smoke.py no longer asserts STKD02.
24. `virtual.build_synthetic_remote(overwrite=True)` deletes the existing
    `<workspace>/mth5/<name>.h5` before it opens the members (virtual.py lines
    565-569), so a rebuild that then fails (a member with no archive, a grid
    off by more than `GRID_TOL`, members that do not overlap) leaves no
    archive at all where a good one stood [inference from the code]. Latent
    today: scripts/build_stack.py never passes `overwrite`, and campaign.py
    moves an existing output aside before its build (lines 1884-1891). The
    Stacks tab spec has the GUI pass `--overwrite` on every Build archive
    (docs/gui_stack_tab_design.md 12.2, critique 8.1 item 3), which would make
    it live. Wanted: build to a temporary file in the same folder (the
    `out_path` argument) and `os.replace` it onto `<name>.h5` only after the
    write succeeds. Found 5 Oct 2026 while criticising the Stacks tab spec.
    The Stacks tab did not make it live: `build_stack.py --recipe NAME
    --overwrite` builds into `<workspace>/mth5/.build_<pid>/` and replaces
    `NAME.h5` only after the build is checked (scripts/build_stack.py
    lines 372-410). Still open for any other caller of
    `build_synthetic_remote(overwrite=True)`.
26. A coherence-weighted stack or member check on fewer than three whole
    600 s chunks (under 1800 s of common span) fails with "no usable level:
    the record is shorter than one base window" from `timefreq.levels_plan`
    [measured: 610 s and 1300 s at 1000 Hz, three members, through
    `virtual.build_synthetic_remote(weighting="coherence")`; 1900 s works].
    `member_coherence` plans its ladder with `levels_plan`'s default
    `min_windows=3`, so it needs three chunks, while the message speaks of
    one window and `member_coherence`'s docstring of a chunk that "cannot
    carry the band ladder". Wanted: `member_coherence` checks
    `n // chunk >= 3` first and says so ("coherence weighting needs at least
    three 600 s chunks, the span holds 2"), or passes `min_windows=1`, which
    its one-window-per-level plan allows [inference]. The Stacks tab's member
    check (`stackcheck.compute_check`) meets it on a short loaded segment.
    Found 5 Oct 2026 while testing `virtual.stack_arrays` (Stacks tab, median
    batch).
27. `intersite.select_stack` leaves out a member that covers the whole window
    when the window is no longer than `min_overlap_hours` and ends one sample
    after the member's last sample: `archive_runs` gives a run's end as its
    last sample (`time_period.end`), so `overlap_hours` comes out one sample
    short of the window, and the reason contradicts itself ("its runs with
    hx/hy cover 3.00 h of the window, under 3 h") [measured 5 Oct: 1 Hz
    scratch archives of 3 h from one start, window [start, start + 3 h),
    min_overlap 12 h: no member kept; tests/stacks_unit.py prints the line].
    process_intersite's default window ends at the earliest last sample of
    the local and the base, so it is not hit; a window given to the minute on
    the command line or in a stacks.yaml recipe is, whenever it is 12 h or
    shorter and ends where a member's record ends, as a night window cut by
    the record's end does [inference]. Time recipes are not affected
    (`stacks.resolve_members` asks for the window less `MEMBER_EDGE_S`), and
    `stacks` does not compensate for band recipes, so the recipe path and the
    flag path stay equal. Wanted, in intersite: count a run to one sample past
    its last (`archive_runs` adding one sample period, read from the run's
    `sample_rate`), or let `select_stack` accept a shortfall of one sample.
    Found 5 Oct 2026 while testing `stacks.resolve_members` (Stacks tab,
    recipes batch).
    Fixed in 01ca477 (the Stacks tab's fix round, 5 Oct; merged into main
    as 7ef3d16): `select_stack` accepts a shortfall of one sample period
    (`1 / (rate * 3600)` h), so the three-hour case above keeps M1
    (tests/stacks_unit.py's INFO line) [measured]; the suites and the Nador
    dry runs it touches were rerun (docs/gui_stack_tab_build.md, Fix round).
29. `tests/campaign_unit.py` reads
    `surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml` (its first
    test, `test_plan_parser`, line 467), which is gitignored, so it exits 1
    with FileNotFoundError in a worktree or a clean checkout [measured 5 Oct
    by the Stacks tab's scripts and tab batches: exit 1 in 3-5 s; with the
    file copied in, 17 of 17 pass]. A suite that runs it
    (tests/stack_recipe_cli_unit.py criterion 6) then reports a failure
    that is not one. Wanted: campaign_unit to leave that test out, saying
    so and exiting 2 ("not run"), when the plan is absent, or a copy of the
    plan under tests/. tests/stack_recipe_cli_unit.py now reports
    campaign_unit NOT RUN and exits 2 when the plan is absent. Found 5 Oct
    2026 while building the Stacks tab (scripts and tab batches).
    In the main tree, where the plan is present, campaign_unit completes:
    17 of 17 in 91 s inside stack_recipe_cli_unit on 6 Oct 2026, and 17 of
    17 in 92 s run alone the same day [measured]. The exit-2 NOT COMPLETE
    form applies to a worktree without the plan.

31. The Process tab's station list was empty, with no message but "A
    station and a remote are both required", whenever `data_root` held no
    site folder: it was filled from `State.raw_sites()` (`Survey.site_dirs`)
    alone, while the remote list already offered every archive. The Atlas
    survey's raw folders moved from `D:\MT_DATA\MT_Morocco_Atlas_Mountains`
    to `E:\MT_Timeseries_DATA\MT_Morocco_Atlas_Mountains` on 7 Oct 2026 and
    survey.yaml's `data_root` was left on D:, so the list held 0 of 146
    declared sites and the remote list 103 archives, each labelled "stack".
    Behind it, process_rr.py could not have run either: `ingest_site`
    looked up the raw folder (`survey.site_dirs()[site]`, KeyError) before
    keeping an existing archive. Fixed 9 Oct 2026: `State.station_choices`
    (every raw folder, every declared recorded site with an archive, the
    declared derived and burst sites with an archive; an observatory is a
    remote and is left out; a site without a raw folder labelled
    "A01  (archive)" by `archive_kind`), `State.recorded_sites` for the
    remote recommendation (`PairSummary`, Cross-powers) and the replace
    donors, and `ingest_site` keeps an archive whose raw folder is not
    found. Atlas: 99 stations (the declared sites with an archive less EBR
    and SPT); A01 rr A06 from archives, 6 h, exits 0 with EDI, XML and h5.
    Test: tests/process_station_list_unit.py. The station list from
    `raw_sites()` alone, the code before, trips it. The remote's filters
    under a stale `data_root` were issue 32, fixed with it. Record
    `<workspace>/qc/reports/gui_station_list_20261009/`.
35. An EDL stamp whose five channel files are empty stopped the ingest of
    the whole site with mt-io's "ValueError: No channel data found in
    [...]" (Tasmania AusLAMP 2016, 22 Oct 2026: TAS112's last stamp
    `TAS112_160218220000.*` and TAS133's `TAS133160826180000.*`, all 0
    bytes; the batch's only two failures). `ingest._edl_runs_by_samples`
    made the 0-sample stamp a run of its own. Fixed 22 Oct 2026 (stage 1b,
    agent D, uncommitted): `_edl_plan` leaves out a stamp whose files hold
    no sample, with one warning, and the run goes on across it; TAS112 and
    TAS133 then built in 38 and 19 s (one run of 21,402,490 samples; two
    runs of 35,928,000 and 34,800). Test: tests/ingest_edl_overlap_unit.py
    O4 (an empty last stamp). Upstream 334: mt-io raises on an empty file
    set where a warning and an empty read would do.
37. `ingest.ingest_site` (the library) leaves the archive it was writing
    when a run raises after the file is opened (a refused `rot_h` on a
    LEMI-423 pair whose chains differ, `flip_h` naming a channel the run
    lacks, a reader error), while scripts/ingest_site.py removes it
    ("removed the partial ..."). process_rr.py calls `ingest_site` with
    overwrite=False and reuses any archive it finds, so a partial archive
    left by a failed library call would be processed as the site. Found
    22 Oct 2026 by tests/ingest_rot_h_unit.py R5 (its first run asked for
    no file after the LEMI-423 refusal). Not fixed: remove the partial file
    in `ingest_site` as `_ingest_bursts` does (`_remove_partial_archive`).
38. scripts/site_qc.py's check (a), "calibration and run placement", fails
    on records whose float32 figure array cannot hold 1e-5 sigma: its
    tolerance (CAL_TOL 1e-5) assumes float32 storage good to ~1e-7 sigma,
    but `timefreq.load_station` removes one offset per channel, and a
    record whose samples lie hundreds of sigma from it (a first run at
    the set-up, or a turned fluxgate whose first run is not on the main
    DC) stores them to 2^-24 of that distance. Tasmania AusLAMP 2016 after
    the rot_h rebuild (22 Oct 2026): TAS138 worst re-read difference
    2.6e-5 sigma (hx; float32 bound 2.9e-5: max |x - offset| 479 sigma)
    and TAS151 1.7e-5 (bound 2.6e-5, 430 sigma) FAIL; TAS105 6.7e-6 (bound
    3.3e-5) passes; a misplaced run, the check's target, gave 1.2e-2 at
    TAS105 before the overlap fix. Logs `<workspace>/logs/stage1b/
    site_qc_TAS1*.log`. Fixed 23 Oct 2026 (stage 1b, agent D, uncommitted;
    the lead's ruling of 00:0x): `site_qc.calibration_tolerances` gives each
    channel the tolerance max(1e-5, 3 x its float32 bound, max |x - offset|
    x 2^-24 / sigma). Test: tests/site_qc_calibration_unit.py (Q1 a record
    stored 5,000 sigma from its offset passes at 2.2-2.8e-4 against 8.9e-4,
    where the fixed 1e-5 fails; Q2 a run one sample off is caught at 2 sigma
    under either tolerance; Q3 the floor 1e-5).
39. The stack member check and the coherence weighting (`mt_workbench.
    virtual`: CHECK_BANDS_S 0.1-1, 1-10, 0.1-10 s; WEIGHT_BAND_S 0.1-10 s;
    10-min chunks) are fixed to the coil band of the 1000 Hz surveys. At
    1 Hz they raise ("a 600 s chunk cannot carry the 0.1-10 s ladder on
    this record", `member_coherence`), so `build_stack.py --check` and
    `--weighting coherence` (campaign stage 2 `w`) cannot run on derived
    1 Hz sites or an observatory (Tasmania TAS100L + CNB, 23 Oct 2026,
    `<workspace>/qc/stage2/scripts/probe_1hz_coherence.py`). At 10 Hz they
    run inside the Bartington fluxgates' noise: every member of the five
    Tasmania wave recipes reads 0.10-0.16 in every band (logs/stage2/
    check_STK_<wave>.log), the level of incoherent noise for the estimator,
    while the same leave-one-out check at 100-1,000 s reads 0.58-0.996
    (`qc/stage2/member_coherence_<wave>.csv`, TAS120 hy the outlier at
    0.58), so the check cannot tell a dead or turned member and the `w`
    weights are taken from noise; with 20 or more members the absolute
    WEIGHT_FLOOR 0.05 is above an average normalised weight, so members
    drop out chunk by chunk at random (the module docstring says so).
    Wanted: the check and weight bands from the recipe's rate or the
    survey's band (with the chunk scaled to carry them), or options for
    both; a message naming the rate when they cannot run. Workaround:
    `<workspace>/qc/stage2/scripts/member_check_long.py` (the same check at
    10-100 and 100-1,000 s in 6-h chunks through `_open_members` and
    `member_coherence`); the 1 Hz campaign plan has the plain mean only.
    The lead's ruling 2 of 23 Oct 2026 02:0x drops `w` from both Tasmania
    plans (weighted stacks dropped on 24 Sep); the bands are not
    changed here.
42. `process.process_station` hands whatever aurora's `process_mth5`
    returns to `drop_short_bands`, so a run aurora could not finish fails
    with "AttributeError: 'NoneType' object has no attribute
    'dropped_short_bands'" (process_mth5 returned None) or "'TransferFunctionCollection'
    object has no attribute 'impedance'" (its export failed), lines after
    aurora's own log line that says why. Met at Tasmania AusLAMP 2016 stage
    3 (23 Oct 2026, agent F) on the first one-electric derived site
    (upstream 338): the cause, "No handling for missing ey channel", was
    in an ERROR line 40 lines above the traceback. Wanted: a check after
    `process_mth5` that raises naming aurora's failure (the object it
    returned and "see aurora's log above"). The one-electric case itself
    now runs (`process._one_electric_line`, stage 3, uncommitted); the
    unclear failure for other aurora failures is not fixed.
    Fixed 23 Oct 2026 (agent I, uncommitted): `process_station` raises a
    RuntimeError when `process_mth5` returns None or anything without TF
    metadata, naming what it returned and the outputs asked for (met again
    at TAS132L, issue 46 and upstream 340); tested in
    tests/derived_sites_rr_unit.py (the control without TAS132L-style
    channels stops on it).
43. process_rr.py's comparison figure (`<stem>_vs_lemimt.png`) of a
    derived diagonal site (`<site>D`, scripts/diagonal_site.py) overlays
    the parent's reference EDI as it stands: its xy and yx are the
    parent's N and E rows, the diagonal's "xy" is Z_dy of a line along
    theta_d, so the two curves are not like for like (TAS112D against
    TAS112_window_rr_TAS108: up to 2.5 times apart in rho, 5 to 15 deg in
    phase, where the like-for-like projection agrees within 8 % and
    0.4 deg). Met at Tasmania AusLAMP 2016 stage 3 (23 Oct 2026, agent F).
    The quadrant check of the same run called TAS115D's row "xy 180 deg
    out of quadrant" (Z_dy +173 deg along 317 deg at a 3D site) and wrote
    "flipped" into the sidecar and INFO; fixed the same day (uncommitted):
    `process_rr.diagonal_azimuth` makes it "not judged" for a diagonal,
    tested in tests/diagonal_site_unit.py. The figure is not fixed:
    wanted, the reference projected onto theta_d (u(theta_d)^T Z_ref,
    with the reference's frame undone), as
    `<ws>\qc\stage3\scripts\diagonal_compare.py` does for Tasmania.

68. `tests/campaign_unit.py` `test_runner_and_resume` judges the runner's
    concurrency from three fake jobs of 2 s each (`_fake_job`, a
    `python -c` child writing "start" and "end" times to a trace file) and
    asserts that two ran at once (`_max_concurrency`, its line 655). On a
    machine whose CPU is saturated by other jobs a child can write its
    "start" more than 2 s after its sibling ends, so the test reports
    "FAIL: 1 at once" though the runner started two: the Tasmania Run 4b
    re-run of the suite (1 Nov 2026 13:01, CPU 100 % [measured] from
    another session's Kalkaroo pipelines, 79 GB available) gave 19/20 with
    that case failing; the re-run at 13:10 passed 20/20 and its own line
    reads "3 jobs of 2 s at --parallel 2: at most 2 at once, 43.1 s"
    [measured], i.e. 43 s of wall time for three 2 s jobs. The memory gate
    is not the cause (the test plan's need is 0.2 GB, peaks 0.05 GB).
    Wanted: the concurrency read from the runner's own start times (or the
    ledger's), or fake jobs long enough that start-up lag cannot separate
    them (the first log kept in the Tasmania workspace,
    qc/stage4_run4b/tests/first_run/campaign_unit.log). Open.

75. **One all-null EDL hour refuses the whole site at ingest.** `mt_workbench.ingest._edl_plan`
    counts every file's samples with mt-io's `count_samples`, which raises
    `ValueError("... holds bytes but no samples")` on a file of bytes with no
    samples (by design: returning zero would put a run of no length into a
    collection). The plan has no guard, so `ingest_site.py` fails the site with
    that traceback. AusLAMP Victoria VIC076, standard copy `VIC0769    VIC076_140628150000.BY`: ONE file of 53,248 zero bytes (2014-06-28 15:00
    UTC; the BX, BZ, EX, EY and TP of that hour hold 36,000 good samples each;
    the zero file's mtime is 2025-11-20 and GA's release holds the same bytes,
    so the zeros came with GA's packaging, not the logger: agents E and F,
    2 Nov 2026); stage 1's 81-site batch
    reports "VIC076 failed in 15.0 s: ValueError: VIC076_140628150000.BY holds
    bytes but no samples" and the site has no archive [measured, 2 Nov 2026,
    `D:\MT_DATA\MT_Victoria_AusLAMP_2013_2018_Workspace\logs\ingest_VIC076.log`].
    `instruments.span` would fail the same way on an all-null last file. The
    plan already leaves out a stamp of 0-byte files (`empty`, TAS112) and lets
    contiguity split the run there. Wanted: an all-null stamp (any channel file
    counted as bytes-without-samples) takes that same path with its own
    warning naming the stamp and the byte size; `span` counts such a last file
    as 0 samples with a warning. Found 2 Nov 2026 by agent E's stage-1 batch.
    Fixed 2 Nov 2026 (agent F, `surveys/victoria_auslamp_2013_2018/notes/stage1/
    fix75_REPORT.md`): `ingest._edl_samples` returns None on mt-io's refusal; a
    stamp with any such file takes the `empty` path with its own warning naming
    the file and its bytes; `instruments.span` counts an all-null last file as
    0; `tests/edl_null_stamp_unit.py` (5 cases, the pristine plan raising as the
    mutation); the census of 242,451 channel files finds this one file; VIC076
    then plans as 302 + 37 stamps around the hour (its archive still needs the
    issue-76 rebuild). Applied to the working tree, uncommitted.

77. **`scripts/h_azimuth.py --neighbours` stops the whole run on a pair whose
    timing check has no fit (tau None).** Stage 1 of AusLAMP Victoria: one pair
    (VIC037) returned `tau None` and the script raised instead of writing the
    row without a lag [agent E, `defects_found.md` D-3, worked around by its
    `e2_table_completion`]. Wanted: a None tau written as empty with the pair
    noted. Found 2 Nov 2026.

78. **`dclevel` reads the main field as `open input?` after the fluxgate turn**
    at VIC038, VIC039, VIC056 (AusLAMP Victoria stage 1): the turned hx carries
    the whole horizontal field at a site whose sensor sat near 90 deg, and the
    "30 times the typical level of the channel type" clause fires on it
    [agent E, `defects_found.md` D-4]. Wanted: the typical level taken per
    channel after the turn, or the clause limited to the electrics. Found
    2 Nov 2026.

79. **`campaign.best_remotes` / `choose_best` rank without an overlap term**: the
    score is coverage x smoothness x blow-ups over the periods holding a value;
    hours never enter, so a short quiet overlap wins. AusLAMP Victoria
    `victoria10`: 21 of 76 picks cover under 70 % of the local's span, eight
    under 10 % (VIC001 rr VIC048 49 h of 643, VIC014 rr VIC003 25 h of 676,
    VIC030 rr VIC010 46 h of 1,003, VIC049 rr VIC010 41 h, VIC056 rr VIC036 38 h,
    VIC063 rr VIC077 26 h, VIC024 rr VIC017 69 h, VIC006 rr VIC048 168 h of 783);
    VIC031's pick covers 70 of 315 h and the rest of its record reads 15 % lower
    in rho (agent N). Tasmania's Run 1 met it at TAS110/128/132 (a short-overlap
    remote at 1,460 s). Wanted: `scoring.min_overlap_frac` in the plan (0.7, else
    the longest) and the overlap hours in scores.csv. Found 2 Nov 2026 [the lead,
    Victoria `decisions.md` F-4; stage 4 applies the floor by hand].
80. **`build_stack.py --check` measures no member lag**, and its fixed 0.1-10 s
    bands sit in the fluxgate noise at 10 Hz (0.104-0.116 at every member;
    Tasmania 0.10-0.16) and cannot run at 1 Hz (issue 39): it cannot fail a
    member. Agent N measured lags with `intersite.timing_check` over 0.43-3.6 s
    (each member against the plain mean of the others, one more as the remote;
    an injected +40 ms recovered as +40.06). Wanted: that measurement as a lag
    column of `--check`, bands chosen from the rate. Found 2 Nov 2026 [agent N,
    Victoria `stage3/README_hfrom_refs.md` N1d-N1e'].

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
    Fixed: 91bd796 (`masks.read_document`: one libyaml parse per change of
    (path, mtime, size), 2.8-3.0 s, a file read within 2 s of a write read
    again; `State.masks_reader` parses off the GUI thread; all 75 Atlas sites
    load equal to the pure-Python parse; the Cross-powers mask buttons
    inert until the list is filled, `tests/crosspower_masks_wait_unit.py`)
    and 76b39c6 (no read loop on an unreadable file). Masks per site
    still open.
12. **View EDIs `reload()` json-loads every sidecar** (4,398 files, 588 MB)
    to read the `engine` key; its `lru_cache(256)` is smaller than the file
    count. 5.1-6.2 s at survey open, on Refresh and after every landed job;
    0.014 s with 100 products. `mantle_products.describe`, `gui/tabs/edis.py`:
    a `tf/index.json` written with each product, an unbounded mtime-keyed
    cache, a lazy tree.
    Fixed: 715c6ea (`mt_workbench.tf_index`: the index written by
    `write_products`, per-stem entries kept in-process without bound, one
    `os.scandir` per reload). The lazy tree is not done (see
    `qc/survey/workbench_fixes_20261003/gui/README.md` for the reload left).
13. **Every WindowBar reads the span of every archive** with `load_grid`
    (96-104 calls, 13.2-15.0 s, pydantic metadata construction) under the
    archive lock; 1.4 s with 10 archives. `window_bar.site_span`,
    `archive.load_grid`: spans from h5py attributes, one persisted cache shared
    by the Process and Cross-powers bars.
    Fixed: 4433103 (`archive.read_span`: the 103 live archives in 0.53 s
    against 14.59 s, every span equal to `load_grid`'s; `State.spans` keyed
    on path, mtime and size, shared by both bars and kept across survey
    reloads in the process, not written to disk).
14. **Variant filtering is 52 % of the end-to-end pipeline** (1,635 of
    3,500 s over 13 builds) on 3.4-3.8 of 20 cores: `noise.mains_subtract`
    (one-second block fit) and `noise.mains_notch` (one `sosfiltfilt` per line
    and pass) through `build_variant`'s four-worker, one-channel-per-thread
    pool; B10 alone 506 s at 37 GiB. Fix: time chunks over a pool sized to the
    cores (bounds memory too); a stacked SOS is 6.5x faster per channel but
    not identical within 60 s of run ends (a decision, with a variant-hash
    salt). Fixed in 31c0498 for the mains fit only (the stacked SOS left for
    a decision): its own chunks run over a pool of the cores, bit for bit (the
    synthetic against a stored a937bc4 result; 2 h of B10's four channels
    on 1, 8 and 20 threads). On those 2 h it went 5.41 -> 3.84-3.94 s on 8
    threads (3.6 -> 6.2 cores, peak 0.67-0.71 -> 0.72 GiB) and 4.25-4.33 s
    on 20 (1.07 GiB): its basis arithmetic is memory-bound, so 8 threads
    beat 20. The notch keeps its single pass. In 600 s chunks with settling
    margins it equalled the single pass only to rounding: up to 2.2e-12 of
    the std on C19's declared q 60 x2 (3.3e-14 of the largest sample), and
    with the mean removed C19 ex still differed by 5.2e-8 counts in 37,746
    samples. That patch (B10's notch 2.31 -> 1.62 s, 1.07 -> 0.67 GiB) is
    an open decision: the Morocco workspace's
    qc/survey/workbench_fixes_20261003/pipeline/followup. Not measured on a
    whole variant build.
15. Masks naming only output channels split a pair into two aurora runs
    (`process_rr.row_runs`): A20 rr A21 440 s = 135 + 279 s. One read and STFT
    with the extra masks applied at the regression; needs an identity check.
16. Cross-powers `WORKERS` 4 -> 8: whole-overlap compute 24.5 -> 17.1 s
    (identity checked on a 6 h window only).
    Fixed: 44688f4 (identity re-checked on 1 h of the bench C18 rr C19:
    the 92 store arrays with data equal; levels 8-10 hold no window in
    1 h, so the deepest levels rest on the 6 h check).
    The 24.5 -> 17.1 s is an idle-machine figure; under 34-65 % machine
    load the whole overlap took 24.3 -> 19.8 s (two runs of each, 3 Oct).
17. Imports per child process 2.6 s (`mt_metadata.transfer_functions` 1.5 s
    through `mt_workbench.compare`): about 70 s per bench-sized batch; reuse
    worker processes in the campaign runner. 303ce78 makes compare import
    mt_metadata and matplotlib only when used (`import mt_workbench.compare`
    2.36 -> 0.075 s), and process_rr.py selects Agg itself before mth5 and
    mt_io import pyplot, as compare did. process_rr.py's import is no
    faster: 2.80 s before, 2.92 s with the lazy imports alone, 2.83 s with
    Agg selected early (medians of five fresh processes, interleaved;
    2.69-3.15 s over all fifteen). Whether the lazy imports alone are
    slower is not settled: three interleaved measurements of them against
    before gave +0.15, +0.12 and -0.05 s, so there is no clear slowdown;
    Agg is selected early as compare did before. `mt_workbench.ingest`
    imports mth5 and mt_io, which import mt_metadata.transfer_functions
    and matplotlib.pyplot themselves: the 1.5 s was where `-X importtime`
    charged a cost every child pays anyway. Worker reuse remains the lever.
18. Campaign `--parallel` below what the memory gate allows: four jobs fit at
    the fork median peak of 22.4 GiB, three at the p90 34.6 GiB; lines A and D
    ran two at a time. Fixed in 7f016c6: the default is `runner.parallel`,
    else as many jobs as the gate admits at start, logged with the rr peak
    used (line C2's dry run: 4 at its p90 of 25.0 GB with 101.2 GB free).
19. Sidecars record no fork SHAs for mth5, mt_timeseries, mt_io and
    mt_metadata (the version strings are the upstream numbers), so a ledger
    cannot attribute a gain to a fork. `products` / `process_rr`: record the
    installed `direct_url` commit or a local tag per package. Fixed in
    28befe7: `versions.installed` per package (direct_url, editable, the
    commit when pip recorded one, the RECORD and `__init__.py` hashes). The
    forks were installed from their clone folders, so pip recorded no
    commit; a reinstall from a `git+file://` URL would record one.
21. A raw folder of many Phoenix files makes a window bar's span read run
    for more than 28 min, and closing the window waits for it. The
    curnamona_cube data_root holds `C_cube_Phoenix` (77,615 files
    [measured]), recordings of several Phoenix units in one folder, which
    `Survey.site_dirs` now lists as one Phoenix site (it and J08, a folder
    with no `sites:` entry, are why the Metadata table shows 63 sites
    against the 61 of tests/gui_smoke.py). `gui.window_bar.site_span`
    reads a raw-only site's span from its files on every call:
    `instruments.span` -> `record_files`, which opens every file's header
    with `phoenix_header` (instruments.py line 371). `MainWindow.closeEvent`
    then blocks in `WindowBar.wait_for_read` (window_bar.py line 329) until
    that read ends. tests/process_tab_unit.py passes its checks and then
    waits in `window.close()` (its line 428; faulthandler stack after 90 s
    [measured]); a run stopped at 900 s was still waiting [measured];
    `instruments.span` alone on the folder had not returned after 1700 s
    [measured]. Wanted: a raw span kept per folder (its mtime and file
    count) or read from the first and last recordings' headers only; a
    close that abandons a raw span read instead of waiting; and a folder
    holding several units' recordings not taken as one site. Found 5 Oct
    2026 while mapping the test harness for the Stacks tab.

## Added 4 Nov 2026 by the Marymia LP 2015 track (agent A; appended at the tail as briefed: 85 belongs under "Silent wrong output", 86-88 under "Unclear failures")

85. **`rot_h` is one value per site, so a fluxgate that turned during the record
    is put on magnetic north in one segment only (SILENT WRONG OUTPUT: a frame
    error of up to 18 deg that the products do not show).** MRYLP005 (Marymia
    LP 2015, a 27-day 10 Hz PR6-24 record) holds ten turns of its fluxgate:
    the DC field steps by 200-8,300 nT in hx, hy and hz within 1-10 min while F
    changes by under 0.22 % (rotations of a working sensor, test S1e-1), and the
    segment azimuths (atan2 of the medians) run 0.37 to 34.97 deg
    (`surveys/marymia_lp_2015/notes/stage1/README.md`; `<ws>/qc/stage1/
    s1_segments.csv`). The variation field against Gingin follows every step
    (slope 0.95 at 100-1,000 s, 0.92 at 1,000-5,000 s; residual rms 1.7 and
    2.6 deg about the band's common offset; S2a). `scripts/h_azimuth.py`
    flags the site "moved 34.6 deg" and still proposes one `rot_h` (18.45, the
    azimuth of the record's median vector; the hour-weighted segment mean is
    14.6), and `ingest._rot_h` applies one turn to every run, so the archive's
    H frame is off by -18.1 to +16.5 deg segment by segment [measured]. The
    Tasmania track met the same at TAS147 (a turn on 29 Sep 2016) and masked
    the segment before the turn; at MRYLP005 the longest segment is a third
    of the record. Workaround: `<ws>/qc/stage2/scripts/s2_turn_segments.py`
    writes derived archives (`MRYLP005S`, `MRYLP005SL`, `derived_from:
    MRYLP005`) with each segment turned by its own azimuth after the
    ingest's whole-record turn (the hx and hy chains checked equal first, as
    `_rot_h` does; read back: hz, ex, ey bit-equal, |H| to 1e-9, every
    segment's mean-field azimuth within 0.004 deg of 0); with it the
    variation-field azimuth spread over the long segments falls from 32.5 to
    7.0 deg (100-1,000 s). Ask: `rot_h` as a list of `{start, end, value}`
    (a piecewise turn, each run sample taking its interval's value, the
    transitions split at their midpoints), and `h_azimuth.py --propose`
    finding the steps itself (the two-minute vector change over 150 nT with
    F within 1 %) and proposing one value per segment. Found 4 Nov 2026.

86. **`process_rr.py` has no single-station mode, and the by-hand script that
    supplied one is outside the repository and imports the package's old
    name.** A long-period record with no concurrent 10 Hz neighbour (MRYLP005,
    whose only remote is a 1 Hz observatory) needs single-station processing
    at its own rate for its short end. `process_rr.py` takes a local and a
    remote only; `mt_workbench.process.process_station` takes
    `remote_station=None`. The Morocco track's
    `<Morocco ws>/qc/survey/R_stations_20260930/scripts/single_station.py`
    imports `crust` and fails on this checkout. Workaround: `<ws>/qc/stage2/
    scripts/single_station.py` of the Marymia workspace (process_rr.py's own
    `resolve` with the local given as its own remote, then `process_station`
    with no remote, the sidecar's remote entries null and `single_station`
    true; stem `<local>_ss_<time>`). Ask: `process_rr.py <survey> <local>
    --single-station` with the same resolution, masks and sidecar. Found
    4 Nov 2026.

87. **`scripts/observatory_from_parquet.py` names only Canberra: any other
    observatory is archived with a blank source and its code as its name.**
    `KNOWN` holds CNB alone, so Gingin (GNG) rendered with `--lat --lon
    --elev` gets `Station Name GNG` and an empty `Source of Data` in every
    IAGA-2002 header, and `observatory.to_mth5` then writes the station
    comment "INTERMAGNET observatory GNG ()" [measured, Marymia
    `mth5/GNG.h5`, 4 Nov 2026]; nothing in the archive says Gingin or
    Geoscience Australia, and the elevation must be guessed (0 written as a
    placeholder). Ask: KNOWN entries for the Australian observatories the
    parquet holdings cover (ASP, CNB, CTA, GNG, KDU, LRM) from INTERMAGNET's
    station list, and `--name`/`--source` options for the rest. Found 4 Nov
    2026.

88. **The EDL ingest archives a run recorded before the logger's GPS lock with
    no flag.** MRYLP005's first two stamps (04:19:11 and 04:20:11 UTC, 2015-04-23,
    840 samples, run `sr10_0001`) precede the PLL lock: the day's .pll reads
    -1 in its first column until 04:20:32 and the .gst reads "1 0" for both
    stamps, "0 0" from 04:20:33 on. `ingest_site` plans from file stamps and
    sample counts only (`_edl_plan`), never reads .gst or .pll, and archives
    the run beside the record with no word about its clock. Effect small here
    (84 s, a separate run), but a long pre-lock stretch would enter processing
    with an undisciplined clock. Ask: read the .pll lock state per stamp and
    leave out (or flag in the run comment) stamps recorded before the first
    lock of the deployment, naming them. Related: upstream 317 (timing_qc.py
    has no EDL path). Found 4 Nov 2026.

## Added 4 Nov 2026 by the Victoria AusLAMP Run 2 track (agent P; appended at the tail: 89 belongs under "Unclear failures", 90 under "Silent wrong output")

89. **A one-site campaign plan builds no stage 2 stack, and says the reason is
    too few eligible remotes.** `campaign.stack_plan` draws stack candidates
    from `plan.sites` only (`cands = [s for s in plan.sites ...]`); the
    `remote_only` sites join only the second (R) stack, and only beside members
    already chosen. A side plan with one local and its remotes as
    `remote_only` (the form every h_from site needs, so that the lender is
    never paired with its borrower: `campaign_victoria_vic031.yaml`,
    `_vic040`, `_vic081`, `_vic047`) therefore never gets a stack, and the run
    log and the dry run print "no stack possible (fewer than 2 eligible
    remotes whose best run covers 50 % of its record)" while 5 to 20 eligible
    remotes cover 70 % or more [measured, Victoria `logs/stage4/run2/P/
    dryrun_vic047.log` against `stackplan_vic047.log`, 4 Nov 2026: the same
    20 remotes as plan sites give an 8-member stack]. Workaround used: a
    scratch plan with the remotes as sites, `--dry-run --stage 2 --sites
    <local>` to read the campaign's member choice, then `build_stack.py`
    positional with `--min-piece-h 6` and `process_rr.py` by hand (Victoria
    STK_VIC040u2, STK_VIC081u2, STK_VIC047u2 and their L twins). Ask: a plan
    key letting `remote_only` sites be stack members (or `stack_from:
    remotes`), and a message that names the real reason. Related: Victoria
    `notes/stage3/README_campaign_1hz.md` finding 1. Found 4 Nov 2026.

90. **An h_from ingest that cuts the record to the lender's cover leaves the
    site's survey.yaml span unchanged.** VIC081's rebuilt archive starts
    2014-03-02 08:00, where its lender VIC049 starts ("cut to the part VIC049
    covers (26712000 of 29556000 samples)", `logs/stage4/run2/
    ingest_VIC081_20261104-115849.log`), but survey.yaml still reads `start:
    2014-02-27 01:00`; `decimate_site.py` did move VIC081L's start to 03-02
    08:00:10. Everything that plans from the survey span then works on 79 h
    the archive does not hold: `campaign.py` overlap hours and the stack
    cover fractions (VIC081 821 h record, 694-798 h overlaps), the stack
    builder's start, and a split test's window A (2014-02-27 01:00 to 03-27,
    Victoria `qc/stage4/run2/stationarity_run2_jobs.csv`). process_rr itself
    takes the archives' overlap, so no product is wrong; the planning numbers
    are. Ask: `ingest_site` writes the cut span back to the entry (under the
    survey.yaml edit rule, upstream 91), or warns that the entry's span is
    wider than the archive. Found 4 Nov 2026.

## Added 4 Nov 2026 by the Tasmania broadband 2016 track (agent G, stage 4 Run 1; belongs under "Silent wrong output")

91. **`deliver_as_laid.py` quotes a wrong measurement fragment when one notes
    clause declares both lines.** Tasmania broadband's survey.yaml notes say
    "ex+ey declared reversed 4 Nov 2026 (ruling 14)" (one clause for both
    lines). The script matches "Ey declared reversed" inside "ex+ey declared
    reversed" and quotes the text before it, so the ey as-laid INFO line reads
    "reversal measured (ex+), declared in survey.yaml", while the ex line,
    which finds no "Ex declared reversed", reads "reversal declared in
    survey.yaml" [measured, `<ws>/qc/stage4/as_laid_trial/Tas-W330.edi` and the
    Run 1 delivery `deliverables/tasmania_broadband_2016_west_Run1_EDIs/`: 9 of
    the 15 ey lines, the sites whose notes use the "ex+ey" form; `<ws>/qc/stage4/M5_as_laid.csv`]. The rows, AZM and the round trip are
    right; only the quoted text is wrong, and it ships in the delivered INFO
    block. Workaround: none applied (the script is not edited by agents); the
    delivery README says the fragment is a parsing artefact. Ask: match the
    line name as a whole word (not after "+"), and for "ex+ey declared
    reversed" quote the clause for both lines. Found 4 Nov 2026. **Fixed
    4 Nov 2026 (the lead, uncommitted):** `measurement` matches the name with
    `(?<![\w+])` and takes the joint forms `ex+ey` / `ey+ex` for both lines;
    the Tasmania joint clause has no census and nothing before it, so both
    lines read "reversal declared in survey.yaml" (the test's case g); the
    Run 1 delivery's as-laid step was rerun on the fix.

## Added 5 Nov 2026 by the Victoria AusLAMP stage 6.0 track (agent S, the LEMI-424 tier; 92 and 93 are blockers and belong under "Silent wrong output", 94 and 96 under "Silent wrong output", 95 under "Unclear failures")

92. **A LEMI-424 site cannot be processed: its archive holds bx by bz e1 e2
    and nothing maps them to hx hy hz ex ey.** Found: `ingest_site.py`
    built `VIC004R.h5`, `VIC009R.h5` and `VIC058R.h5` (Victoria LEMI-424
    survey `surveys/victoria_lemi424_2016_2018/`, channels "E1 E2 Bx By Bz")
    with the channels as mt-io names them. Then `process_rr.py ... VIC004R
    VIC009R --no-masks --min-band-windows 2 --tag stage6-smoke` stopped with
    "aurora returned nothing ... Outputs asked for: bz, e1, e2, inputs hx,
    hy" (KeyError 'ex' in aurora's TTFZ) [measured,
    `<ws>/logs/stage6/s6c_VIC004R_rr_VIC009R_try1.log`]. A `channels: [ex,
    ey, hx, hy, hz]` declaration is refused at ingest ("none of the declared
    channels ... is among the reader's ['bx', 'by', 'bz', 'e1', ...]",
    `<ws>/logs/stage6/s6a_channels_test.log`), and
    `CHANNEL_PRESETS["lemi424"]` only selects, it does not rename. Where:
    `mt_workbench.instruments.read_run` (lemi424 branch) and
    `INSTRUMENTS["lemi424"]["channels"]`. Effect: no LEMI-424 survey gets a
    transfer function; this blocks stage 6 (19 sites). Workaround (smoke
    test only, diagnostic): `notes/stage6/s6_w1_ingest.py` wraps
    `read_run` in the agent's own process to rename and fill the metadata
    (92-94), then calls `ingest_site` unchanged, into `<ws>/w1/`. Ask: the
    lemi424 branch of `read_run` renames bx by bz e1 e2 to hx hy hz ex ey (as
    `mt_workbench.phoenix` renames E1 E2 H1 H2 H3), with the presets and
    `INSTRUMENTS` changed to match, or a declared map from e1/e2 to ex/ey for
    a card wired otherwise. Two traps for the fix, found while building
    the workaround: (i) renaming in place is not enough, because a RunTS
    keeps the names in the run's channel list, its channels_recorded_*
    lists and the station's channels_recorded, and its dataset setter
    rebuilds e1/e2 from each variable's `component` attr. W1 rebuilds the
    run from fresh ChannelTS objects. (ii) `_keep_channels` drops the
    variables of undeclared channels (e3, e4, the temperatures) but leaves
    them in the run and station metadata, and aurora's TF export then stops
    on "Component 'e3' not found in channel_nomenclature_dict". Found 5 Nov
    2026.
    **Fixed 5 Nov 2026 (agent T, stage 6 fix, uncommitted):**
    `instruments.read_run` (lemi424) returns `lemi424_stored(run, site)`,
    the run rebuilt from new ChannelTS objects with bx by bz e1 e2 stored as
    hx hy hz ex ey (`LEMI424_RENAME`; e3, e4 and the temperatures keep their
    names until `channels:` drops them); `INSTRUMENTS["lemi424"]["channels"]`
    and `CHANNEL_PRESETS["lemi424"]` use the stored names under the
    recorder's labels; `_keep_channels` also removes a dropped channel from
    the run's channel list and the station's channels_recorded and run
    entries (trap ii); a LEMI-424 `channels:` still written in the reader's
    names is read in the stored names by `Survey.site`. Test
    `tests/lemi424_ingest_unit.py`. The three smoke sites rebuilt from the
    survey of record give archives sample-identical to W1's and 7 of 7
    products bit-identical (`notes/stage6/README_stage6_fix.md`).
    `tests/ingest_unit.py` and `tests/survey_unit.py` still assert the old
    names (entry 97).

93. **The reversed-dipole rule and `rot_h` cannot reach a LEMI-424 site.**
    `_standardise_e_orientation` runs only `if instrument == "lemi423"`
    (`ingest.py` near line 3658), so `azimuth_ex: 180` / `azimuth_ey: 270`
    with `flip_reversed_dipoles` flip nothing on a LEMI-424 run, and the log
    says nothing. `_rot_h` raises "rot_h turns hx and hy, and the run holds
    [bx, by, ...]" on the archive as built today. Effect: a polarity declared
    from the quadrant census (the standing rule of 4 Nov) and the fluxgate
    turn cannot be applied to the tier; a declared reversal would be
    silently ignored once 92 is fixed by a rename alone. Workaround: the
    smoke's W1 wrapper calls `_standardise_e_orientation` after the rename.
    Ask: extend the reversed-dipole call to lemi424 (the reader does not
    invert E, so the rule applies as for LEMI-423); `_rot_h` works once 92
    renames. Found 5 Nov 2026.
    **Fixed 5 Nov 2026 (agent T, stage 6 fix, uncommitted), as the
    instrument convention the lead's brief asked for:** `SiteConfig.e_sign`
    (1.0 or -1.0; unset means -1.0 on a LEMI-424 site, a `defaults:` value
    is ignored on other recorders and a site's own value other than 1.0 on
    another recorder stops ingest, `ingest._e_sign`); `ingest._apply_e_sign`
    multiplies every kept electric channel by it and records the
    CoefficientFilter `lemi424_e_sign` (gain -1, mV/km in and out, applied
    False, so calibration does not undo it) and the run comment
    "LEMI-424 E sign convention e_sign -1 applied at ingest to ex, ey ...";
    `_standardise_e_orientation` now runs for lemi424 after it, so a line
    laid reversed is declared on top as for LEMI-423. `scripts/new_survey.py`
    writes `e_sign: -1.0` with a comment for a LEMI-424 survey; the Victoria
    LEMI-424 survey.yaml has it in `defaults:`. `_rot_h` works on the
    renamed run (VIC009R 0.59, VIC058R 0.19; residual after the turn
    -0.0013 / -0.0034 / -0.0018 deg). A decision may set the default +1 with
    per-site declarations: one survey.yaml line.

94. **A LEMI-424 archive carries wrong channel metadata: e1 and e2
    `dipole_length` 0.0, and by and e2 `measurement_azimuth` 0.0.** Read back
    from `VIC004R.h5`, `VIC009R.h5`, `VIC058R.h5` with h5py
    (`<ws>/qc/stage6/smoke/G2_archives.csv`). survey.yaml declares 88/100 m
    and azimuths 0/90; GA's release MTH5 of the same records holds
    `dipole_length` 88/100 and azimuths 0/90 for ex/ey and bx/by. `read_run`
    says "No dipole length is applied", which is right for the data (the
    logger writes mV/km), but the metadata is not filled either, and mt-io
    leaves the azimuths at 0 (upstream 548). Effect: an EDI writer or a
    rotation that reads the channel azimuths reads by and e2 as north; a
    reader of `dipole_length` reads 0. Workaround: W1 sets them from
    survey.yaml. Ask: `read_run` (lemi424) sets each E channel's
    `dipole_length` and every channel's `measurement_azimuth` from the
    SiteConfig, with no change to the samples. Found 5 Nov 2026.
    **Fixed 5 Nov 2026 (agent T, stage 6 fix, uncommitted):**
    `instruments.lemi424_stored` sets what the EDL reader sets: ex and ey
    `dipole_length` from the site; `measurement_azimuth` / `measurement_tilt`
    hx 0/0, hy 90/0, hz 0/90 (`STORED_AZIMUTH_TILT`), ex and ey the stored
    frame (site azimuth modulo 180: 0 and 90) with tilt 0;
    `translated_azimuth` not set (as on the EDL path). Read back from the
    rebuilt VIC004R, VIC009R, VIC058R archives (88/100, 76/100, 100/100 m;
    0/90).

95. **Two LEMI-424 messages mislead.** (a) `ingest_site.py` line 471 prints
    "(LEMI-423 runs of at most 34 files)" for a LEMI-424 site. (b)
    `_record_levels` classifies a LEMI-424 channel in "counts" against a
    relative rail and flags `saturated?` on values that are nT and mV/km
    (VIC004R sr1_0001: all five channels "saturated?", e.g. bx "median
    2.10e4 counts, 5.19 % at the rail"; `<ws>/logs/stage6/s6a_ingest_VIC004R.log`).
    Effect: a reader takes a sound LEMI-424 card as clipped. Ask: name the
    instrument in (a); in (b) say the units and leave out the rail test for
    an instrument whose reader returns physical units. Found 5 Nov 2026.

96. **Corrupt single-second LEMI-424 rows go into the archive unflagged, and
    one such row in a remote ruins the estimate.** The dec2017 cards hold
    rows where every channel is garbage for one second (VIC009R
    `201712200000.TXT` line 38048, 2017-12-20 10:34:07: bx 4.402, by
    -56834.695, bz -92546.914, e3 106093.063, between rows at 21414 / -1 /
    -56301 nT). There are 73 such seconds at VIC004R and 28 at VIC009R by a
    1,000 nT test against a 61 s running median, and none at VIC058R
    [measured, `<ws>/qc/stage6/smoke/G9_glitches.csv`]. Each site is fine as
    the local against CNB. As each other's remote they wreck the xy row:
    VIC004R rr VIC009R gives xy +1.31 dex and -13 deg against rr CNB, rho to
    1e10 ohm m at some periods (`G9_VIC004R_cnb.png`). With the seconds
    masked +-2 s (a diagnostic masks.yaml) the pair agrees with rr CNB to
    0.006 dex and 0.03 deg [`G9_cnb.csv`]. Effect: any LEMI-424 pair or
    stack that takes one of these sites as a remote is silently wrong.
    Ask: a corrupt-row check at ingest for LEMI-424 (any channel's jump over
    a set multiple of its running MAD, or E3/E4 off their unwired level),
    written as time masks or a run comment and listed in the ingest log.
    Found 5 Nov 2026.

## Added 5 Nov 2026 by the Victoria AusLAMP stage 6 track (agent T, the fixes of 92-94; belongs under "Unclear failures")

97. **Three tests still expect a LEMI-424 archive in the reader's names
    after fix 92.** `tests/ingest_unit.py` `test_new_instruments_one_hour`
    (line 978: MBJ21's channels `["bx", "by", "bz", "e1", "e2", "e3", "e4"]`,
    `chains["e1"] == []` and e1 equal to the file's column 11) and
    `tests/survey_unit.py` `test_channel_presets` (line 230: the LEMI-424
    presets must be a subset of mt-io's `LEMI424().file_column_names`) fail
    after the fix [measured 5 Nov 2026: "AssertionError: ['e3', 'e4', 'ex',
    'ey', 'hx', 'hy', 'hz']" and "('lemi424', 'E1 E2 E3 E4 Bx By Bz', {'hx',
    'hy', 'ey', 'ex', 'hz'})"]; `tests/gui_smoke.py` (line 1152,
    `LEMI424_PANELS` bx .. e4, and the e1 column check) will too (not run:
    Qt). Agent T's brief allowed edits to other tests only. Ask: in
    ingest_unit, comps ex ey e3 e4 hx hy hz, check ex against minus column
    11 and the chain [lemi424_e_sign]; in survey_unit, map the reader's
    names through `instruments.LEMI424_RENAME` for lemi424; in gui_smoke,
    the panels hx .. e4 and ex = -E1 (the scratch MBJ21.h5 of the mixed
    survey is rebuilt by `ensure_archives` only when missing: delete it
    first). Found 5 Nov 2026.
    **Fixed in part 5 Nov 2026 (agent T, uncommitted):** `tests/ingest_unit.py`
    (MBJ21 channels ex ey e3 e4 hx hy hz, ex checked against minus column
    11, ex chain [lemi424_e_sign -1], the header's words) and
    `tests/survey_unit.py` (mt-io's column names through `LEMI424_RENAME`,
    "Bx By Bz" and "Bx By Bz E1 E2" on a LEMI-424 in the stored names, the
    header's words) pass (exit 0, 24 and 16 tests). `tests/gui_smoke.py` is
    NOT changed and not run: on a four-electric LEMI-424 archive (the mixed
    survey's MBJ21, ex ey e3 e4) the GUI's `gui/channels.py` `order` (line
    60: electrics in name order, so e3 e4 before ex ey) and `roles` (line
    88: the first two electrics play Ex and Ey) give Ex = e3 and Ey = e4,
    so the Spectra and Coherence panels would read "By-E3 (Zxy)"; the panel
    list hx hy hz e3 e4 ex ey and the E1 truth also need the test's edit.
    `gui/stack_check.py` line 60 (`ALTERNATIVE` hx->bx, ex->e1) and the
    module docs of `gui/channels.py`, `tabs/spectra.py`, `tabs/coherence.py`
    and gui/README.md still speak of bx .. e4. Ask: `roles`/`order` prefer
    ex and ey when present, then the test's LEMI424_PANELS and titles.
    `synthetic_survey.yaml` given `e_sign: 1.0` (its E has the physical
    sign).
    **GUI part fixed 5 Nov 2026 (agent T, uncommitted):** `gui/channels.py`
    `order` and `roles` put ex and ey first when present (`_electrics`,
    `NAMED_ELECTRICS`), so a four-electric LEMI-424 archive stacks hx hy hz
    ex ey e3 e4 and reads By-Ex (Zxy) / Bx-Ey (Zyx) / Ex-Ey (electric), e3
    and e4 the extra pair; an older archive (bx .. e4) reads as before.
    Wording of `gui/stack_check.py` ALTERNATIVE, of the channels, spectra
    and coherence module docs and gui/README.md follows.
    `tests/gui_smoke.py` (30) expects hx hy hz ex ey e3 e4, "By-Ex (Zxy)"
    etc. and ex = minus column 11. Run headless (QT_QPA_PLATFORM=offscreen)
    through `notes/stage6/t8_gui_mixed.py` (criteria 28-31 alone, since
    the whole smoke stops at (1), "63 rows, expected 61", before and after,
    not this track's): before, "Time Series panels ['hx', 'hy', 'hz', 'e3',
    'e4', 'ex', 'ey']"; after, the panels, labels and pens pass and the
    check stops at "ex as plotted differs from the file by up to 328.662":
    the GUI draws +E1, see 98. 97 stays open on 98.

98. **Scalar calibration ignores a filter's `applied` flag, so every QC view
    draws a LEMI-424's E with the logger's sign again.** `ingest._apply_e_sign`
    (workbench 93's fix) negates the samples and records `lemi424_e_sign`
    (gain -1) as not applied; aurora, `crosspower` and `intersite` honour the
    flag, so the products are right (7 of 7 bit-identical to W1). But
    `timefreq._scalar_gain` (lines 172-179, used by `gui/archive.load_grid`
    and the site QC figures) multiplies every CoefficientFilter's gain and
    divides by it, so the GUI shows ex = +E1 [measured 5 Nov 2026: MBJ21.h5
    holds ex = -E1 (154.411 for -154.411); gui_smoke (30) "ex as plotted
    differs from the file by up to 328.662"]. The same loop is in
    `scripts/psd_qc.py` `_raw_scalar_gain` (line 271) and
    `scripts/diagonal_site.py` reads the chains whole. Ask (one of): (a)
    `_scalar_gain` and `_raw_scalar_gain` skip a stage whose
    `channel.metadata.filters[i].applied` is False, as aurora does; or (b)
    record e_sign in the h_scale form (samples raw, stage applied True),
    which every consumer already divides out, the products unchanged and
    the archive's E equal to the logger's columns. Found 5 Nov 2026.
    **Fixed 5 Nov 2026 (agent V, stage 6, uncommitted), by (b):**
    `ingest._apply_e_sign` no longer touches the samples: ex and ey are
    the logger's E1 and E2 columns, and the CoefficientFilter
    `lemi424_e_sign` (gain `e_sign`, mV/km in and out) is appended to each
    electric chain recorded applied, as `_apply_h_scale` records `h_scale`;
    the run comment reads "LEMI-424 E sign convention e_sign -1 recorded in
    the chain of ex, ey (E1, E2 are recorded with the opposite sign to the
    x-north, y-east frame), the samples are the logger's columns" (a comma,
    not the brief's ";", which the EMTF XML writer splits on). A line
    declared reversed is still negated in the samples by
    `_standardise_e_orientation`. `timefreq.py`, `psd_qc.py` and the GUI are
    unchanged and now draw -E1 (gui_smoke criteria 28-31 pass through
    `notes/stage6/t8_gui_mixed.py`, which stopped at "ex as plotted differs
    from the file by up to 328.662"). The 16 archived sites rebuilt: ex, ey
    equal the raw E1, E2 at every sample, hx hy hz byte-equal to the kept
    archives, and all 16 `<site> rr CNB` products bit-identical to their
    stage6-polarity / stage6-fix twins, with an e_sign 1.0 control that
    differs in the E rows only (`notes/stage6/README_stage6_form.md`). Tests
    `tests/lemi424_ingest_unit.py`, `tests/ingest_unit.py`,
    `tests/gui_smoke.py` (30) moved to the form. The full gui_smoke still
    stops at (1), "63 rows, expected 61": not a fixture, the two raw
    folders `C_cube_Phoenix` and `J08` in the curnamona_cube data_root with
    no `sites:` entry, already named in "Slow paths" entry 21.

## Added 5 Nov 2026 by the Victoria AusLAMP stage 6.1 track (agent U, the LEMI-424 ingest of all 19; belongs under "Unclear failures")

99. **One GPS-damaged line stops a whole LEMI-424 site's ingest, and the
    error names neither the file nor the line.** `ingest_site.py
    surveys/victoria_lemi424_2016_2018/survey.yaml <16 sites> --raw
    --parallel 4` built 13 sites and failed VIC033R ("ValueError: could not
    convert string to float: 'E'"), VIC051R and VIC069R ("... 'S'")
    [measured 5 Nov 2026, `<ws>/logs/ingest_VIC033R.log`, `_VIC051R`,
    `_VIC069R`; `<ws>/logs/stage6/u2_ingest16.log`]. The cause is six raw
    lines (of 9.5 million at the three sites) whose GPS block lost a field,
    e.g. VIC051R `DATA0039/201712240000.TXT` line 41267 "... 13.00 138.2 S 4 E
    2 0 17 6" (24 fields, latitude missing, the rest shifted) and VIC033R
    `DATA0060/201801090000.TXT` line 78165 (22 fields, "324.1  S  E 0 0
    0"); VIC033R holds 3, VIC069R 2, VIC051R 1; the other 16 cards none
    (`notes/stage6/README_stage6_ingest_polarity.md` U2). The data columns
    of those lines are sound. Where: the reader (upstream 549) raises inside
    `instruments.read_run` (lemi424), and `ingest_site` reports the bare
    ValueError. Effect: three of the tier's 19 sites have no archive and no
    product; the log gives no file, line or reason a user could act on.
    Ask: for lemi424, catch the reader's position-parse error and name the
    file and line; better, read such a line's data columns and take the
    position from the other lines (the position is metadata, the samples
    are good), counted in the run comment, as upstream 549 asks of the
    reader. Found 5 Nov 2026.

## Added 5 Nov 2026 by the Victoria AusLAMP stage 5 VIC085 dive (agent M; belongs under "Missing paths")

100. **A diagonal site has no 1 Hz twin: neither script will derive from a
    derived site.** `diagonal_site.py <scratch survey.yaml> VIC085L` stops
    with "VIC085L is itself derived: run it on the recorded site", and
    `decimate_site.py <scratch survey.yaml> VIC085D` with "VIC085D is itself
    derived from VIC085: decimate VIC085" [measured 5 Nov 2026 on a scratch
    survey copy, `<ws>/qc/stage5/vic085_dive/logs/diagonal_VIC085LD.log`,
    `decimate_VIC085DL.log`]. Where: the derived-site guards of both
    scripts. Effect: a shared-centre site's clean diagonal row (VIC085D,
    VIC023D) can be estimated at 10 Hz only, so it cannot be referenced to
    CNB at 1 Hz for the periods beyond about 2,000 s where the 10 Hz
    concurrent remotes run out; the survey's 1 Hz clause has no diagonal
    candidate. Ask: let `decimate_site.py` take a `diagonal_site.py` product
    (a chain of derived_from, both recorded in the run comment), or let
    `diagonal_site.py` cut the diagonal of a recorded site's `L` twin.
    Found 5 Nov 2026.

## Added 5 Nov 2026 by the Victoria AusLAMP stage 5 VIC018 dive (agent K; belongs under "Silent wrong output")

101. **`shared_centre_test.py` calls a floating centre "fails", so a site
    whose two lines carry one voltage gets no diagonal.** At VIC018 the
    test reads residual coherence 0.966, |g| 0.37, arg g -180, s_obs -1
    and the verdict "fails" (`<ws>/qc/stage5_usable/shared_centre/
    centre_test.csv`), because its model is a noisy centre at gain +1. Yet
    every VIC018 product has its ey row a real, frequency-independent
    multiple of its ex row: r = -0.338 (16-84 % half range 0.03), |Im r|/|r|
    0.06, misfit 0.09 over 10-1,000 s, on four remotes and every window
    [measured 5 Nov 2026, `<ws>/qc/stage5/vic018_dive/tables/
    B6_row_ratio.csv`]: a centre that floats at V(C) = a V(N) + (1 - a) V(E)
    (a = 0.25) puts (1 - a) and -a of the diagonal V(N) - V(E) on the two
    inputs, a singular tensor. ex - ey (`diagonal_site.py --sign 1`, theta_d
    315 deg) recovers the line whole: split-half 0.065 dex / 4 deg against
    0.20 / 10 for the delivered rows, errors 5 % against 19-25 %. Where:
    the verdict rule of `shared_centre_test.py` (gain near +1 only). Effect:
    a site with a floating centre is read as two weak, fieldless lines
    and delivered as a 2 x 2 tensor whose yx is 0.11 of its xy by
    construction. Ask: add the row-ratio test (ey row = r ex row, r real
    and constant, det Z near 0) as a second route to "holds", with
    s = +1 for ex - ey whatever r is. Found 5 Nov 2026.

## Added 5 Nov 2026 by the Eastern Goldfields long-period track (owner session; decided: log and carry on; belongs under "Silent wrong output")

102. **A PR6-24 power-on fragment stamped by the boot clock or a stale PC
    clock is archived as a run at that date.** Before the GPS sets the
    digitiser the logger stamps its files from a boot clock (1999-01-01,
    2000-01-01, 2003-01-01) and then from the PC clock (one hour fast, or
    months stale). An ingest of the archive as laid keeps those minutes as
    runs of their own: EGFLP19 `sr10_0001` dated 2018-06-22 02:04, 7.3
    minutes, at a site deployed on 26 Nov 2018; EGFLP33 `sr10_0001` dated
    2003-01-01 00:01, 2.8 minutes [measured 5 Nov 2026,
    `surveys/eastern_goldfields_lp_2018_2019/notes/stage1/trial_as_laid/`].
    The survey holds 19 boot-clock and 36 PC-clock fragments in 50 folders
    (`notes/stage0/tables/unsynced_segments.csv`); fragments wholly inside
    a later file are already left out with a warning. Where: `ingest.py`
    `_edl_plan` and `ingest_site` (no test of a run against the site's
    declared `start` and `end`); `scripts/new_survey.py` and
    `instruments.span` read the same stamps, so a new survey's spans begin
    in 2000 or 2003 at 17 folders (EGFLP36: 170,283 h). Effect: junk runs
    with a wrong date in the archive; spans of 16 years from new_survey; a
    stale stamp inside the survey period (EGFLP38's February 2019 fragment
    of a May 2019 deployment) sits beside other sites' records. Products are
    not harmed where the run overlaps no remote [inferred, not tested].
    Workaround: spans declared in survey.yaml from the logger's own logs;
    later steps leave out the runs listed in
    `notes/stage1/tables/fragment_runs.csv`. Ask: at ingest, leave out, with
    a warning that names it, a run lying wholly outside the site's declared
    span; in new_survey and `span`, flag a span longer than a year and
    ignore stamps before the first GPS-set stamp. Found 5 Nov 2026.

103. **A PR6-24 stretch stamped in GPS time is kept, dated 18 s late, and
    the UTC record after it loses its first 18 s.** After lock and before
    the receiver learns the GPS to UTC offset the logger stamps in GPS time;
    then its clock steps back 18 s. `_edl_plan` keeps the earlier file where
    the next overlaps it ("EDL file stamp 2019-05-01 21:16:13 starts 18 s
    before the samples of 2019-05-01 21:14:00 end: its first 180 samples are
    left out, the earlier file's kept"), so the 1 to 9 minutes before the
    step stay in the archive dated 18 s late and the true record starts 18 s
    after its first sample (EGFLP33: 02:14:01 against 02:13:43, 21:16:31
    against 21:16:13; ten runs under 15 minutes, 0.80 h) [measured 5 Nov
    2026, same folder, `compare_runs.py`]. 49 such fragments, 4.0 h, in the
    survey. Where: `ingest.py` `_edl_plan`, the overlap rule. Effect: minutes
    mis-timed by 18 s at each power-on, silently: the warning reads as an
    ordinary overlap. Small against records of months, wrong for any
    remote-reference window that falls in it. Workaround: the windows are
    listed in `fragment_runs.csv` for a mask. Ask: at a backward step of the
    stamps, keep the later file whole and drop the earlier fragment back to
    the previous break (the earlier clock is the unsynchronised one), and
    say so in the warning; the same rule removes a PC-clock fragment that
    the GPS step corrects backwards. Found 5 Nov 2026.

## Added 5 Nov 2026 by the Eastern Goldfields long-period track, stage 1 agent E (ingest verification; 104 belongs under "Silent wrong output", 105 and 106 under the derived 1 Hz sites)

104. **An EDL stamp that lacks any one channel's file is left out whole.**
    At EGFLP31 on 10 May 2019 (three 20-minute wake-ups of a logger that
    had stopped on 24 April) some stamps lack a channel file; the ingest
    drops those stamps for every channel, so the archive's record is 0.676 h
    shorter than the logger's files (the one site of 50 that fails the
    record-hours check; every other site is within 0.05 h) [measured 5 Nov
    2026, `surveys/eastern_goldfields_lp_2018_2019/notes/stage1/
    HANDBACK_agentE.md`, check E2, `tables/archive_runs.csv`]. Where: the
    EDL plan of `ingest.py` (and mt-io's PR6-24 read of a stamp's channel
    set). Effect: hours of the channels that were recorded are lost with no
    line in the run comment. Workaround: none needed here (0.7 h). Ask: keep
    the channels present, or record the hours left out in the run comment
    and the ingest log. Found 5 Nov 2026.

105. **`decimate_site.py` dates a derived entry from its first run, so a
    power-on fragment dates the 1 Hz site 2000, 2003 or months early.** The
    `<site>L` entries written into survey.yaml took `start` from the first
    derived run; at 23 of 50 folders that run is a boot-clock or stale-clock
    fragment (issue 102), for example EGFLP10L `start: 2003-01-01` for a
    site deployed on 28 Nov 2018 [measured 5 Nov 2026, survey.yaml before
    the owner's edit, copy `survey.yaml.before_L_spans_20261105-172505`].
    Where: `scripts/decimate_site.py`, the span of the new entry. Effect: a
    declared span of 16 years on a derived site; any planner or dry run that
    reads the entry's span is misled. Workaround: the owner's
    `notes/stage1/scripts/owner_fix_L_spans.py` gives each derived entry its
    parent's declared `start` and `end` (in-place, parsed-diff and
    comment-count checks). Ask: take the derived entry's span from the
    parent's declared span. Found 5 Nov 2026.

106. **`decimate_site.py` decimates fragment runs like records and nothing
    marks them in the derived archive.** 79 of the survey's 83 fragment runs
    (issues 102, 103) are carried into the 1 Hz copies as runs of their own
    [measured 5 Nov 2026, HANDBACK_agentE.md, "What the 1 Hz copies do with
    the fragments"]. Where: `scripts/decimate_site.py`. Effect: the 1 Hz
    route (an observatory remote) meets the same mis-dated minutes as the
    10 Hz route, and a reader of the derived archive cannot tell them from
    record. Workaround: the windows of `notes/stage1/tables/
    fragment_runs.csv` are left out by masks at processing. Ask: once the
    ingest leaves fragments out (102, 103), nothing more is needed; until
    then, skip a parent run that lies outside the parent's declared span.
    Found 5 Nov 2026.

## Added 5 Nov 2026 by the Eastern Goldfields long-period track (owner session, from the question "do we need to rebuild the archives? can't we rotate within mt-workbench?"; a design item, not a wrong output)

107. **A declared `rot_h` costs a full re-ingest from the logger's files.**
    The turn of hx and hy onto magnetic north is applied only while the raw
    files are read (`ingest.py` `_rot_h`, called from `ingest_site`; the
    archive records it in the station's provenance comments, read back by
    `archive_rot_h`). Nothing turns an archive that already exists, a
    variant, a stack member or a product. So at Eastern Goldfields the
    declaration of 50 measured turns after the first ingest meant reading
    124.6 GB of ASCII a second time (about 50 minutes, four sites at once)
    and deriving the 50 1 Hz copies again [measured 5 Nov 2026,
    `surveys/eastern_goldfields_lp_2018_2019/notes/stage1/
    rebuild_after_rot_h.log`]. The order cannot be avoided on a new survey:
    the angle is measured from the archive, so the archive exists before the
    angle is known. Where: `ingest.py` (`_rot_h` reachable only from the
    file read), `scripts/ingest_site.py` (no option to turn an existing
    archive). Effect: an hour of machine time per round of declarations on
    a 50-site survey, and a "raw" archive whose samples depend on a
    declaration. Workaround: declare, then `ingest_site.py --all --raw
    --force` and `decimate_site.py --force`. Ask (one of): (a) a tool that
    applies `_rot_h` to an existing archive's runs in place, with the same
    provenance line and a refusal when the archive is already turned
    (minutes, no file read); (b) the turn applied where the processing
    archive is read (processing, stacks, the GUI), leaving the raw archive
    as recorded; for one local site the turn is also exact on the estimated
    tensor (Z' = Z R^T, T' = T R^T), which a stack member cannot use. Found
    5 Nov 2026.

## Added 5 Nov 2026 by the Eastern Goldfields long-period track (owner session; belongs under "Fails late with a message that does not name the cause")

108. **A survey `name:` longer than 30 characters passes every step until the
    first processing run, which then cannot find the survey in its own
    archive.** mth5 cuts the survey id to 30 characters in its channel and
    run summaries (upstream 550); `process.kernel_dataset` passes the cut id
    on to aurora (`rs.from_mth5s` then `kd.from_run_summary`), which looks
    for `/Experiment/Surveys/<30 characters>/...`. At Eastern Goldfields
    (`name: eastern_goldfields_lp_2018_2019`, 31 characters) the survey was
    scouted, ingested twice (50 sites, 125 GB of logger files each time),
    decimated and stacked before the first `process_rr.py` run failed, with
    "Could not find" [measured 5 Nov 2026,
    `surveys/eastern_goldfields_lp_2018_2019/notes/stage3/
    HANDBACK_agentH.md`, H3]. Where: `survey.py` (`Survey.from_yaml` has no
    check on the length of `name`), `scripts/new_survey.py` (`--name`),
    `process.py` `kernel_dataset`. Effect: hours of ingest before the fault
    shows; the message names a path, not the cause. Ask: until upstream 550
    is fixed, (a) `kernel_dataset` puts each archive's own survey id back
    into the run summary before the kernel dataset is built, and (b)
    `Survey.from_yaml` and `new_survey.py` warn at once when `name` is
    longer than the summaries can hold. Found 5 Nov 2026.
    REPAIRED 5 Nov 2026 by decision (decisions R7 of the survey's notes; agent I; uncommitted): (a)
    `process._restore_survey_ids` in `kernel_dataset`, (b) the warning in `Survey.from_yaml`
    (`new_survey.py` not changed), `tests/survey_id_cut_unit.py` 7 of 7; `tests/survey_unit.py` 16 of 16
    and 19 other existing tests pass after it; gui_smoke fails on a site count that this change does
    not touch (63 rows against 61: two more Curnamona folders); 13 tests were not run.

## Added 5 Nov 2026 by the Eastern Goldfields long-period track (owner session, from the pilot's finding F1 and the instruction to try for the Nyquist; a design item)

109. **The band layout stops at a quarter of the sample rate, with no way to
    ask for more.** `bands.build_band_scheme` keeps the top band edge at or
    below 0.25 of the rate (`f_cap = 0.25 * sample_rate`), whatever
    `min_period` says. At 10 Hz with `min_period: 0.2` (the Nyquist) the
    shortest period estimated is 0.449 s (2.2 Hz against a Nyquist of 5 Hz),
    for every remote kind [measured 5 Nov 2026,
    `surveys/eastern_goldfields_lp_2018_2019/notes/stage3/
    HANDBACK_agentH2.md`, finding F1]. The cap is a sound default (the
    logger's own anti-alias roll-off, the level's decimation filter), and
    the docstrings say so. But the instruction for this survey is to try
    to get close to the Nyquist (decisions.md R6), and the octave between a
    quarter and a half of the rate cannot be estimated at all, even as a
    trial with its errors shown. Where: `src/mt_workbench/bands.py`
    (`build_band_scheme`, the cap; `_top_period`). Effect: 0.2 to 0.449 s
    is never estimated at 10 Hz (2.2 to 5 Hz), 2 to 4.49 s never at 1 Hz;
    `min_period` in survey.yaml reads as if it were honoured. Workaround:
    none without a code change. Ask: an optional top fraction (default 0.25,
    a trial value up to about 0.45) as a survey.yaml processing key and a
    `process_rr.py` option, recorded in the product's sidecar, with the
    bands above the quarter rate flagged in the product; and a line in the
    dry run that states the shortest period that will be estimated when it
    is longer than `min_period`. Found 5 Nov 2026.

## Added 5 Nov 2026 by the Tasmania broadband track, stage 5 agent R (noise characterisation at Tas-W338/W331)

110. **`timefreq.load_station` with a `grid` whose t0 is a naive Timestamp
    fails late with a pandas TypeError.** Found: placing the remote Tas-W344
    on a 4-day grid, `grid=(pd.Timestamp("2016-01-27T00:00:00"), n, 1000.0)`
    reads the MTH5, then stops at `i0 = int(round((start - t0)...))` with
    "Cannot subtract tz-naive and tz-aware datetime-like objects", because
    the run starts from `_real_runs` are tz-aware. Where:
    `src/mt_workbench/timefreq.py`, `load_station` (the `grid` branch).
    Effect: the call fails after opening the file; elsewhere in the
    workbench (crosspower, masks, segment) a naive time is taken as UTC, so
    the caller has no reason to expect this. Workaround: pass
    `pd.Timestamp(..., tz="UTC")`. Ask: normalise `grid[0]` with
    `tz_localize("UTC")` when it is naive (as `masks.utc` does), or say in
    the docstring that t0 must be tz-aware. Found 5 Nov 2026.

111. **`ingest.build_variant` deletes every other filtered variant of the site,
    including the record survey's, when a trial copy declares a different
    filter list.** Found: the stage 5 trial `v5f` (survey copy
    `surveys/tasmania_broadband_2016/experiments/stage5/v5f_W338/`, its
    filters.yaml = the record's notch comb + `burst`) built
    `Tas-W338_f6c7592f8.h5` and then pruned `Tas-W338_fa5afd228.h5`, the
    variant of the record filters.yaml that Run 1, v4c and every stage 3-5
    copy read (log `<ws>/logs/stage5/rr_v5f_Tas-W338.log`, 21:48:01 WAST).
    Where: `src/mt_workbench/ingest.py`, `build_variant`, the loop
    `for other in (survey.workspace / "mth5").glob(f"{site_name}_f*.h5"):
    other.unlink()`. Effect: survey copies under `experiments/` share the
    workspace with the record survey, so any filter trial on a copy deletes
    the record variant (5.3 GB here); the next record run rebuilds it
    (about 5 min), and a job of another agent that has it open, or opens it
    while it is missing, fails or rebuilds it and prunes the trial's variant
    in turn. The deletion is silent apart from one INFO line, and it breaks
    the standing rule that a trial deletes nothing. Workaround: none from a
    copy; agent R stopped its queue before the second site (Tas-W331's
    variant is intact) and did not rebuild W338's. Ask: prune only variants
    no survey.yaml under the workspace's surveys still resolves to (or never
    prune automatically, and list stale variants in the dry run instead);
    at least warn in `process_rr.py --dry-run` that a build will delete a
    named variant. Found 5 Nov 2026.

## Added 5 Nov 2026 by the Tasmania broadband track, stage 5 agent E (diagonal derived sites)

112. **A derived diagonal site `<site>D` does not see its parent's masks.**
    Found: building `Tas-W311D` and ten other `<site>D` sites on the survey
    copy `surveys/tasmania_broadband_2016/experiments/stage5/diag/`.
    Where: `src/mt_workbench/masks.py` `load_masks(survey, site)` reads the
    entries filed under the site's own name only, and
    `scripts/process_rr.py` calls `load_masks(survey, args.local)`; nothing
    maps a derived site (`derived_from`) to its parent's entries, and
    `scripts/diagonal_site.py` writes no masks entry. Effect: a `<site>D`
    run silently uses none of the parent's record trims or selection masks,
    so it is not processed on the hours its parent was (here up to 106
    entries per site, the record trims plus the v4c selection in 1-30 s),
    and a comparison with the parent's product mixes two data selections.
    Workaround: duplicate the parent's entries under `<site>D` by hand in
    the copy's masks.yaml (`notes/stage5/s5e_masks.py`, read back equal
    with load_masks). Ask: have `load_masks` fall back to (or union with)
    the parent's entries for a site with `derived_from` (masks are times,
    so they hold for a derived archive cut from the same samples), or have
    diagonal_site.py and decimate_site.py copy them, and say which in the
    process_rr sidecar. Found 5 Nov 2026.

## Added 6 Nov 2026 by the Eastern Goldfields long-period track (owner session, from the roll-out agent's defects J1 and J2)

113. **The EDL ingest writes no log line when `flip_reversed_dipoles` is
    false at a site whose field sheet gives a 180 or 270 deg azimuth.** On
    the PR6-24 path `instruments.py` hands the reader nominal azimuths and
    says nothing; the line "taken as layout direction" is written only on
    `ingest.py`'s other path. Five sites of the Eastern Goldfields survey
    (EGFLP08, 10, 11, 11A, 20) had the flip dropped on 6 Nov 2026 after
    the quadrant test showed every flipped row reversed
    (`surveys/eastern_goldfields_lp_2018_2019/notes/stage4/
    README_agentJ.md`, section 1 and J1). Where: `src/mt_workbench/
    instruments.py` (the EDL branch), `src/mt_workbench/ingest.py`.
    Effect: the ingest log of a site whose flip was dropped holds no record
    of how its 180/270 azimuth was read; only the products' quadrant test
    shows it. Workaround: the quadrant test on the products. Ask: the same
    info line on every recorder's path, naming the channel, the sheet
    azimuth and what was done (negated, or taken as layout direction).
    Found 6 Nov 2026.

114. **A derived 1 Hz entry copies its parent's 180/270 azimuths but not
    its `flip_reversed_dipoles: false`.** `decimate_site.survey_entry`
    writes `<site>L` with the parent's `azimuth_ex: 180.0` and without the
    parent's site-level `flip_reversed_dipoles`, so `Survey.from_yaml`
    gives EGFLP08L, 10L, 11L, 11AL and 20L the default true while their
    parents say false [measured 6 Nov 2026, the same README, J2]. Where:
    `scripts/decimate_site.py` (`survey_entry`). Effect: none on the data
    (the copy is decimated from the parent's archive, which already has
    the sign the parent's declaration gave it; the 1 Hz products are in
    quadrant), but the derived entry contradicts its parent, and a tool
    that reads the flip from the derived entry (a re-ingest of the L site
    from raw, `deliver_as_laid.py`'s check that a derived site declares the
    same azimuths) would act on the wrong reading. Workaround: read the
    declaration through the parent (`derived_from`). Ask: copy the
    parent's `flip_reversed_dipoles` when it is set, or write nominal
    azimuths in a derived entry and leave the declaration to the parent.
    Found 6 Nov 2026.

## Added 6 Nov 2026 by the Eastern Goldfields long-period track (owner session, from the census agent's defect L1)

115. **`timefreq.load_station` without `grid` spans every run of the
    archive, so one mis-dated fragment run makes a 16-year grid.** The
    1 Hz copy EGFLP33L holds a boot-clock fragment run dated 2003-01-01
    (workbench 102, 106: fragment runs are archived at their wrong date and
    copied into the derived site). `load_station` called without `grid`
    builds its grid from the first run's start to the last run's end:
    518 M samples, about 10 GB for five channels, where the record is
    949 h [measured 6 Nov 2026, `surveys/eastern_goldfields_lp_2018_2019/
    notes/stage5/README_agentL.md`, L1]. Where: `src/mt_workbench/
    timefreq.py` (`load_station`, the default grid). Effect: memory and
    time on any tool that loads a station whole (the coherence and
    spectrogram tabs, a census script); the values are correct. Workaround:
    pass `grid` built from the site entry's `start` and `end`. Ask: let
    `load_station` take a span (default: the site entry's `start` to `end`
    when the survey gives them), or leave out runs that masks.yaml masks
    whole, and warn when the grid is more than a few times the summed run
    length. Found 6 Nov 2026.

## Added 6 Nov 2026 by the Eastern Goldfields long-period track (owner session, from the best-hours agent's defect M1)

116. **The `masks.py` module docstring describes a band-mask route and a
    log line that the installed setup no longer uses.** It says band masks
    reach aurora "through a scoped runtime patch"
    (`process._band_masks_applied`, log line "band masks, decimation
    level") and that aurora 0.6.2 has no input for them. With the
    installed aurora fork the masks are applied by aurora itself and the
    log reads "N band-limited mask(s) applied per band (aurora
    window_masks)" followed by aurora's "window masks: band P s drops D of
    N" [measured 6 Nov 2026, `surveys/eastern_goldfields_lp_2018_2019/
    notes/stage5/README_agentM.md`, M1]. Where: `src/mt_workbench/masks.py`
    (module docstring). Effect: a check that greps the documented line
    finds nothing and reads as "the masks did not act" (it happened in the
    best-hours pilot; the check's wording had to be amended). Workaround:
    grep aurora's line. Ask: bring the docstring up to date with the route
    and the two log lines in use. Found 6 Nov 2026.

## Added 6 Nov 2026 by the Oak Dam scout (filing agent; gaps met by a new receiver kind, the Phoenix MTU-5A; merged from reader I's gaps 1-4 and reader R's W1-W7 in `2026_Natural_Source_IP\datasets\oak_dam\results\scout_20261106\`; the proposals are the scout's, not decided work; belongs under "Missing paths")

117. **No MTU-5A receiver kind: `detect_instrument` returns None on an
    MTU-5A folder, and the `phoenix` kind cannot take one.** The Oak Dam
    MTU-5A recordings (a .TBL with .TS2, .TS3 and .TS4, several boxes per
    dated folder) have no path into `ingest_site.py`.
    - `INSTRUMENTS` (`instruments.py` 66-75) holds lemi423, lemi424, edl
      and phoenix ("MTU-5C/8A", `*.td_150`).
    - `detect_instrument` (244-280) returns None on
      `D:\MT_DATA\MT_Oak_Dam\01-RAW\01-RAW\191207` [measured by the
      scout].
    - `survey.py` refuses an unknown kind (700-701, 838-839).
    - The reader branch is at `ingest.py` 3722-3727.
    Filing the MTU-5A under `phoenix` would inherit the 5C table path and
    `ingest_site.py:478`'s "a Phoenix archive stores volts".
    Until upstream 551, 552, 553, 555 and 557 are fixed, an MTU-5A path
    must not trust `MTUTable.station_metadata` or `MTUTSN.to_runts`. It
    should take the position as DD + MM.mmm/60, the span from FTIM/LTIM
    or the tags, the start from the first tag, and one read per array.
    Upstream 556 stops `read_phoenix` outright on 11 of the 247
    recordings.
    Where: `src/mt_workbench/instruments.py`, `ingest.py`, `survey.py`
    and `scripts/ingest_site.py` (line numbers as the scout read them on
    6 Nov 2026).
    Effect: no Oak Dam site can be ingested.
    Proposal (the scout's, not decided): a new kind `mtu5a`.
    - `INSTRUMENTS["mtu5a"]`: `*.TS4` with a sibling `.TBL`; channels
      ex, ey, hx, hy, hz. Matching cases in `is_record`,
      `detect_instrument`, `file_start` (the first tag) and
      `span`/`header_facts`.
    - `read_mtu5a`: walks the tags, requires 1 s steps and splits runs at
      gaps. Counts come from `MTUTSN.read()` (bit-exact against the
      scout's own decoder on 191207, check R2) or from a 40-line decoder.
      Start is the first tag, the rate comes from the tags, units are
      counts, and the channel order comes from the TBL's CH* tags. The
      scalar counts-to-volts chain (FSCV/2^23, EGN, HGN x HATT) goes on
      as unapplied filters. No `to_runts`.
    - In `ingest.py`: an `elif instrument == "mtu5a"` branch at
      3722-3727, the kind in the key lists at 2437-2438, and the
      "counts" level label at 3795 and in `ingest_site.py` 478.
    - Size: about 170 lines, and about a day with tests [reader R's
      estimate]. The tests: a synthetic three-record TSn, and the real
      191207 TS4 (start against the tag, the steps, bit-exactness).
    - Order: after the decision on 119, 121 and 122.
    Found 6 Nov 2026 (`report_reader.md` section 5, W1 and W7;
    `report_inventory.md` gap 1).
    Note, 6 Nov 2026 19:4x (the Oak Dam notes pass): the `mtu5a` kind
    now exists in the worktree branch `mtu5a-ingest`
    (`worktrees\mtu5a-ingest`, from main f177bba), NOT merged:
    new `src/mt_workbench/mtu5a.py` (TS4 only; counts from
    `MTUTSN.read()`, the time base from its own tag walk, the table by
    type byte, the scalar chain as filters) and `tests/mtu5a_unit.py`;
    hooks in `instruments.py`, `ingest.py`, `survey.py`, `dclevel.py`.
    Every acceptance check passed and the 45 Oak Dam archives of
    record were made with it (`2026_Natural_Source_IP\datasets\oak_dam\results\mtu5a_ingest_build_20261106\README.md`,
    `...\ingest_dec2019_20261106\README.md`). Merging awaits a decision
    (open.md OD-14). Its minor gaps are 125-129.
    Note, 13 Nov 2026: landed. c26ad61 adds `src/mt_workbench/mtu5a.py`,
    `tests/mtu5a_unit.py` and `tests/ingest_swap_h_provenance_unit.py` and
    merges the hooks into `instruments.py`, `ingest.py`, `survey.py` and
    `dclevel.py` beside the Orange Box kind (19 conflict hunks resolved by
    hand; `_check_instrument_keys` rebuilt in main's form, an `mtu5a` site
    refusing the Phoenix, LEMI, EDL and Orange Box keys); 7a81aec rewords
    comments only; 0cabec7 adds the README section. `mtu5a_unit` passes,
    M7 on the Oak Dam file included. `Survey.from_yaml` on the Oak Dam and
    Roxby survey files, which failed without the reader with "unknown instrument
    'mtu5a'", resolves every site as `mtu5a`, and Oak Dam
    2-WO-AMT029 and 2-WO-AMT032 ingested again equal their archives of
    record in every dataset and attribute.

118. **Site discovery assumes one folder per site. Oak Dam is one folder
    per date with several boxes in each, and a site's identity cannot be
    read from the folder or from the SITE name alone.**
    - `survey.py` 784-800 maps a site to its own folder.
    - Oak Dam has 28 dated folders (deployment or retrieval dates),
      several receivers per folder, and boxes that change site between
      run letters.
    - The SITE names were added in the office: SITE is blank in every
      .TBO. Three tables have no name. "REMOTE" is used at two positions
      1.94 km apart. Different names sit within 50 m of each other 46
      times [inventory, measured].
    Where: `src/mt_workbench/survey.py` (`site_dirs`, SiteConfig
    537-578).
    Effect: no survey.yaml can name an Oak Dam site's files under the
    present keys.
    Proposal (the scout's, not decided): an explicit site map in the Oak
    Dam survey.yaml, assigning each name plus position cluster to a site
    and listing the recordings. Two ways to get there:
    - a staging tree with one folder per site, built from NTFS hard links
      on D: (no code, but it needs a decision to create);
    - a new `recordings:` site key in SiteConfig and `site_dirs` (more
      code).
    Found 6 Nov 2026 (`report_reader.md` W2 and section 5 item 3;
    `report_inventory.md` gap 2).

119. **No calibration path for an MTU-5A.** There is no reader for the
    .cts files (the only calibration present at Oak Dam) or for Phoenix
    CLB/CLC, and the coil serial has to come from the .TBL, not the
    .TBO.
    - `phoenix.py` reads the 5C JSON calibrations only.
    - Each Oak Dam recording carries a .cts: EMpower text with
      per-frequency complex responses for five channels by band, from
      1e-4 Hz to 10.4 kHz. Its units and normalisation are unknown.
      There is no CLB and no CLC.
    - The coil serials in 18 .TBL differ from their .TBO (corrected
      after recording) [inventory, measured].
    - Between the two December boxes (4759/4573), the band-4 .cts E
      responses agree to 0.33 % and 0.05 deg, so an MTU-5A to MTU-5A
      E-to-E ratio is insensitive to the box response [reader R,
      inference].
    Where: `src/mt_workbench/phoenix.py` (the calibration readers).
    Effect: an MTU-5A archive can carry the scalar chain only. H cannot
    be calibrated, and nothing can be compared against another receiver
    kind.
    Proposal (the scout's, not decided): take the coil serial from the
    .TBL and record where the .TBO differs. To rule on two options:
    - the .cts as the calibration of record, once its units are known;
    - asking Zonge for the CLB/CLC behind it (`C:\CAL` on their
      processing PC).
    Found 6 Nov 2026 (`report_reader.md` W3, section 4 and question 2;
    `report_inventory.md` gap 3).

120. **Burst sites are fixed at 24000 Hz, Phoenix 5C. The MTU-5A burst
    layouts differ, and only TS4 is continuous.**
    - The fixed rate: `survey.py` 91 (`BURST_RATE = 24000.0`) and
      1046-1049; `ingest.py` 3633-3635; `_ingest_bursts` 3139-3391.
    - MTU-5A, read from the tags of 191207 [reader R, measured]: TS4 is
      150 Hz, continuous. TS3 is 2400 Hz, in bursts of 2 x 1 s every
      30 s. TS2 is 24 kHz, in 0.1 s records 1 s apart, 4 per burst,
      every 30 s.
    Effect: the proposed kind (117) takes TS4 only. Remote reference
    and E-to-E work on these files sit in the 150 Hz band.
    Proposal (the scout's, not decided): TS4 first. TS3 would add about
    a day (`BURST_RATE` generalised, `_ingest_bursts` adapted). Defer
    TS2. To say whether the TS3 bursts are wanted at all.
    Found 6 Nov 2026 (`report_reader.md` W4 and question 5;
    `report_inventory.md` gap 4).

121. **No H-sign rule for an MTU-5A.** The 5C rule (`phoenix_h_polarity`
    -1, calibrated H being minus geographic; `phoenix.py` 133-136 and
    912-946; workbench 81) is not known to apply to the MTU-5A, and it
    cannot be tested from the Oak Dam files alone.
    Where: `src/mt_workbench/phoenix.py`.
    Effect: an MTU-5A Z could sit 180 deg off in its H inputs, as Phoenix
    Z did before workbench 81.
    Proposal (the scout's, not decided): the ruling. A co-located
    MTU-5C or LEMI recording would settle it.
    Found 6 Nov 2026 (`report_reader.md` W5 and question 1).

122. **No time-delay convention for a receiver whose calibration carries
    a band delay.**
    - The band-4 (0.21-27.5 Hz) .cts phase of both December boxes implies
      a common 0.196 s delay, if that phase is referenced to the tag time
      [reader R, inference].
    - The delay cancels between two MTU-5A boxes. Against any other
      receiver it is 70.7 deg of phase at 1 Hz.
    - The workbench has no rule for recording or correcting such a delay
      (compare upstream_issues.md 427, the 5C bursts' inter-receiver
      timing, with Filters/time_delay empty).
    Where: the ingest's filter chain (`src/mt_workbench/ingest.py`,
    `phoenix.py`).
    Effect: it decides every mixed-receiver E-to-E pair and none of the
    MTU-5A to MTU-5A pairs.
    Proposal (the scout's, not decided): To choose one of three:
    record the delay as a filter, correct the time base, or ignore it.
    Found 6 Nov 2026 (`report_reader.md` W6 and question 3).

## Added 6 Nov 2026 by the Oak Dam scout (notes pass; from reader H's reading of the continuous band, `2026_Natural_Source_IP\datasets\oak_dam\results\scout_20261106\logs\reader_h_reply.txt`; gaps of the proposed MTU-5A kind, 117; the proposals are the scout's, not decided work)

123. **An MTU-5A ingest needs a per-record saturation mask from the tag
    (byte 15, bit = channel number - 1). A full-scale rail test is blind
    on this receiver.**
    - The MTU-5A clips at about 0.941 of full scale: +-7,893,675 to
      7,893,687 counts, 576.36 mV at the input of a gain-4 electric
      channel against FSCV/EGN = 612.5 mV, dithering over three codes
      [reader H, measured]. A rail at 0.999 x 2^23 found one sample on
      the 275 Oak Dam recording-channels, while the December remote's ex
      sat at the clip for hours (4573C07A 6.1 %, 4573C09A 11.7 %,
      4573C10A 17.0 % of the recording). The dither also defeats a
      zero-variance test on ex (0 flat records).
    - Byte 15 marks those records: every TS4 record holding samples at
      the clip carries its channel's bit (4573C07A ex 4933, 4573C09A ex
      9847, 4573C10A ex 15378, 4573C09A ey 929), and the contractor's
      "Saturated" counts are these flags (check RH1, 14 of 14)
      [`tables/ts4_health.csv`, `p1_pdf_vs_tbl.csv`, measured]. A few
      flagged records hold no clip sample at 150 Hz (2070C10B 23
      records, 4573C08B 6, 4573C09A ey 42). mt-io drops the byte
      (upstream 564).
    - The workbench's run-level check (`dclevel`: RAIL_LEVEL 0.9 of the
      input range for Phoenix, or of the record's largest excursion for
      counts) would give one "saturated?" verdict per run [inference
      from the code, not run]; it cannot say which hours.
    - Where a mask would act, by code reading: `scripts/process_intersite.py`
      does not apply masks.yaml (its docstring, line 131; `start`/`end`
      set one window), and `masks.remote_channel_split` leaves an
      ex/ey-only mask out in the remote role. In E-to-E the base
      contributes its E, and at Oak Dam the December base (the remote)
      is the clipped site.
    Where: the proposed `read_mtu5a` (117); `src/mt_workbench/masks.py`;
    `scripts/process_intersite.py`.
    Effect: an MTU-5A archive would hold hours of clipped electric data
    unmarked, and an E-to-E product on the Oak Dam remote as base would
    include them unless its window is cut by hand.
    Proposal (the scout's, not decided): `read_mtu5a` walks the tags
    anyway (117). Keep byte 15 per record and channel, write the flagged
    spans out (masks.yaml entries with the channels from the bits, or a
    per-run note), and give the E-to-E path a way to apply a base's E
    masks. For the first Oak Dam test a start/end window per pair is
    enough: each ex clip runs to the end of its recording and the ey
    clip sits in one hour [inference from `ts4_health_hourly.csv`].
    Found 6 Nov 2026 (`logs/reader_h_reply.txt`; `logs/reader_h.log`
    13:52:05).
    Note, 6 Nov 2026 19:4x (the Oak Dam notes pass): in the worktree
    branch `mtu5a-ingest` (NOT merged) the mtu5a reader keeps byte 15
    (and the status byte 14, clock status 21, clock error 22-25) per
    record and writes them beside each archive as
    `<site>.mtu5a_flags.csv` (intervals per channel, under the
    archive's channel names after swap_e / swap_h), named in the ingest
    log and counted in each run's comment; flagged samples are stored
    unchanged. The run-level dc check now uses an absolute rail,
    0.9 x `MTU5A_CLIP` (0.941) x 2^23 = 7,104,312 counts, not the
    relative one. On the 45 archives of record the flags equal the tag
    walk on all 265 recording-channels: the saturation-bit counts of
    4573C09A are ex 9848 and ey 971 (the 9847 and 929 above count the
    records holding a clip sample; 42 flagged ey records hold none, as
    said above). Applying the flags as masks in the E-to-E path is not
    built; the first Oak Dam study cuts its windows at them
    (`...\pairs_dec2019_20261106\criteria_draft_v1.txt`).
    Fixed in part (13 Nov 2026): scripts/process_intersite.py applies masks.yaml, the base taking its entries of scope local or both, so a base's ex/ey entries leave out its windows (`tests/intersite_masks_unit.py`); writing the flags out as masks.yaml entries is still open.

124. **Electric levels read from the .TBL's EXDC/EYDC are capped at
    FSCV/EGN and are end-of-recording values.**
    - The .TBL's EXDC/EYDC (x 1000 = the PDF's "Ex/Ey DC") equal the
      median of the last 60 s of the TS4 (median differences 0.017 and
      0.007 mV over the 14 December rows the PDF covers), not a level of
      the recording [reader H, measured: `tables/p1_pdf_vs_tbl.csv`].
    - Where a recording ends clipped, the table holds 612.5 mV = FSCV/EGN
      (2.45 V / 4) while the series sits at 576.36 mV (4573C07A,
      4573C09A ex: 36.1 mV apart).
    Where: the proposed `read_mtu5a` (117) and the levels step of
    `ingest.py` (`_run_levels`, `_record_levels`).
    Effect: an electrode level or saturation verdict taken from the
    table would read a clipped channel as 612.5 mV at full scale, and a
    channel that drifts during the recording by its last minute only.
    Proposal (the scout's, not decided): measure levels from the samples
    (as `_run_levels` already does for the other kinds) and carry
    EXDC/EYDC, if at all, as a note named "end-of-recording level,
    capped at FSCV/EGN".
    Found 6 Nov 2026 (`logs/reader_h_reply.txt`, "DC check").
    Note, 6 Nov 2026 19:4x (the Oak Dam notes pass): in the worktree
    branch `mtu5a-ingest` (NOT merged) the mtu5a levels are measured
    from the samples by `_run_levels` / `_record_levels`, against the
    absolute counts rail of 123's note, and recorded after the levels as
    "dc rail (counts, 90 % of the clip)" (`dclevel.RAIL_PREFIX_COUNTS`,
    read back by `parse_level_note`); EXDC/EYDC are not used.
    Note, 13 Nov 2026: landed with 117 (c26ad61): the levels are measured from the
    samples and the rail recorded after "dc rail (counts, 90 % of the
    clip): ". `level_note` uses that label for every run whose unit is
    counts, so an Orange Box run's rail line now reads it too (148);
    `parse_level_note` reads both labels.

## Added 6 Nov 2026 by the Oak Dam notes pass (the mtu5a build's minor items, recorded not fixed under its amendment 2, A10: the review's F5 and the ingest's reading; `2026_Natural_Source_IP\datasets\oak_dam\results\mtu5a_ingest_build_20261106\review\review.md`; all but 125 are in the unmerged branch `mtu5a-ingest`)

125. **Cosmetic, all kinds: `ingest_site.py`'s "ingesting" line says
    "(LEMI-423 runs of at most 34 files)" for every receiver kind**
    (6 Nov 2026).
    Where: `scripts/ingest_site.py` line 471 (live tree and worktree
    alike): `f"(LEMI-423 runs of at most {args.max_run_files} files)
    -> ..."`, printed whatever the instrument.
    Effect: a wrong label on the first console line of every Phoenix,
    EDL and MTU-5A ingest; nothing else uses it.
    Evidence: `ingest_site.py D:\MT_DATA\MT_Oak_Dam_Workspace\survey.yaml REMOTE1`
    (worktree, PYTHONPATH its src) prints "ingesting REMOTE1 (mtu5a)
    from ... (LEMI-423 runs of at most 34 files) -> ...\REMOTE1.h5"
    (`2026_Natural_Source_IP\datasets\oak_dam\results\ingest_dec2019_20261106\logs\ingest_REMOTE1.txt`
    line 2).
    Proposal: print the run-file cap only when the kind is lemi423 (or
    name the kind's own grouping).

126. **Minor, mtu5a: `is_record(mtu5a)` accepts any `*.TS4` name, so a
    stray copy stops the site** (6 Nov 2026).
    Where: `src/mt_workbench/instruments.py` `is_record` (line 141 in
    the worktree: "the name is checked when the recording is opened").
    Effect: a file such as "x 4573C06A.TS4" or a renamed copy in a site
    folder is taken as a record, and `mtu5a.open_recording` then
    refuses the whole site with the file's name (a loud refusal, not a
    wrong output).
    Evidence: reasoned from the code by the review (its defect 4), not
    run.
    Proposal: match `mtu5a.NAME` (`<serial><month><day><letter>`) in
    `is_record` and skip any other `*.TS4` with a warning that names it.

127. **Minor, mtu5a, performance: `read_run` re-reads a recording once
    per run** (6 Nov 2026).
    Where: `src/mt_workbench/mtu5a.py` `read_run` (line 754; the read at
    784, `MTUTSN(rec.ts4).read()`).
    Effect: a recording with k gaps (k + 1 runs) is read k + 1 times as
    float64. None of the 53 Oak Dam December recordings has a gap, so no
    cost was met; a long recording with many gaps would pay it.
    Evidence: reasoned from the code by the review (its defect 5), not
    measured.
    Proposal: read once per recording and slice the runs from it.

128. **Minor: `detect_instrument` on a folder holding both `.td_150`
    and `.TS4` returns phoenix unless `prefer` is mtu5a, with no
    warning** (6 Nov 2026).
    Where: `src/mt_workbench/instruments.py` `detect_instrument` (line
    245 in the worktree).
    Effect: a mixed folder (an MTU-5C and an MTU-5A recording side by
    side) is taken as one kind silently; with prefer "mtu5a" it returns
    mtu5a at the first .TS4, otherwise the INSTRUMENTS order gives
    phoenix.
    Evidence: the review's R6 reading (`review\review.md` Readings;
    `review\tables\review_checks.csv` R6 REPORT).
    Proposal: warn (or refuse) when a folder holds the records of two
    kinds, naming both.

129. **Minor, mtu5a: `instruments.span(mtu5a)` takes the times from the
    tables' FTIM/LTIM, not the tags** (6 Nov 2026).
    Where: `src/mt_workbench/instruments.py` `span` (lines 583-622 in
    the worktree, through `mtu5a.span`).
    Effect: none on the Oak Dam files, where FTIM equals the first tag
    (the scout's I3, 247 of 247) and the reader refuses a table whose
    FTIM is more than 1 s from it; `span` is used for listing only. A
    table edited after recording would list a span the archive does not
    hold.
    Evidence: the review's reading (`review\review.md`, "instruments.span
    takes times from the tables, not the tags").
    Proposal: take the span from the first and last tags (the walk the
    reader already makes), or say "table times" in the listing.

## Added 7 Nov 2026 by the Roxby scout (notes pass; merged from the gaps of readers I, D, R and H in `2026_Natural_Source_IP\datasets\roxby\results\scout_20261107\` (report_inventory.md, report_documents.md, report_readers.md, report_health.md, each "(b) mt-workbench gaps"); gaps of the unmerged `mtu5a` kind (117, worktree `worktrees\mtu5a-ingest`) met on a second MTU-5A survey; the proposals are the scout's, not decided work)

130. **Recording identity must be (folder, stem), with explicit
    de-duplication** (7 Nov 2026).
    - At Roxby, 27 stems are filed in two data folders: Dec 2017
      recordings filed again in Jan 2018 folders, copies in
      `frozen2070` and `335 RAW`, and the 180209-10 against
      180209-10\team 1 sets. 4262310B sits in three places with the
      02-PROCESSED copy.
    - Their TS4 bytes are equal in all 27. Their .TBL bytes are equal
      in 11 and differ in 16, often with SITE named in one copy and
      blank in the other (4262209A '' against '188').
    - Evidence: `tables\recordings.csv` (same_stem_*, first_copy);
      report_inventory.md finding 1.
    Where: the staging step and the `mtu5a` kind's discovery (a stem is
    taken as unique).
    Effect: the scout's overlaps.csv holds 12 pairs of a recording with
    itself at 0 m, and its usable-pair totals carry 2,413 h from second
    copies (the sceptic's S6). An ingest by stem would archive one copy
    with whichever table it met first.
    Proposal: key recordings by (folder, stem); when a stem recurs,
    require the TS bytes to be equal, and state which copy's table is
    used, with the other listed.

131. **Site identity needs an explicit map, not the table's SITE**
    (7 Nov 2026).
    - SITE is blank in every .TBO and was added in the office in the
      .TBL (839 of 841 pairs differ on SITE). It is blank on 61 stage-2
      recordings.
    - Names are re-used at distant positions: 59 names, up to 58.5 km
      apart, 23 of them stage-1 numbers re-used in stage 2.
    - Names carry text: '99 stage 1 (5', '49R stage 1 (', '222 error',
      '53(RR)', trailing spaces.
    - The remote goes under many names: '53(RR)', 'RR', '193',
      '193-rr', '188', 'Remote', '96', '650', '95', '620', and blank
      recordings at those positions.
    - Evidence: `tables\sites.csv`, `tbl_vs_tbo.csv`, `epochs.csv`;
      report_inventory.md findings 2-3; report_documents.md finding 4.
    Where: the survey declaration and the staging step. The Oak Dam
    character rule (site ids without spaces) does not cover an empty
    SITE (R5 used `S_<stem>`).
    Effect: a site taken from SITE alone would merge distant stations,
    split the remote, and leave 61 recordings nameless.
    Proposal: a declared recording-to-site map (stem to site id) in the
    survey, made at staging from positions within a stated distance,
    with the EDI's DATAID as a fallback name. The scout's tables used
    this form (amendment A8).

132. **The channel map must be read per table from CHEX..CHHZ, and the
    kind's handling of a non-standard map is untested** (7 Nov 2026).
    - Ten Roxby tables map hx to channel 4 and hy to channel 3
      (CHHX=4, CHHY=3): 180116-17\2200116A, 180117-18\2781117A, and
      box 2781 recordings of 18-24 Feb 2018. All others are 1-5 in
      order.
    - In all ten the .TBO differs, so the office changed the map.
    - Evidence: `tables\tbl_metadata.csv`; report_inventory.md
      finding 4.
    Where: `src/mt_workbench/mtu5a.py` in the worktree (the channel
    order from the table's CH* tags). None of the three recordings of
    the scout's R5 trial had the swap.
    Effect: if the map were assumed, hx and hy would be exchanged on
    ten recordings. In an E-to-E product with that site as the H
    reference, the exchange cancels in T [inference]; as a Z or tipper
    input it would not.
    Proposal: a test on one of the ten tables: the archived channel
    named hx equals the decoder's channel 4.

133. **The MTU-5A's E saturation bits are not clip marks: the kind's E
    flags must not be cut marks** (7 Nov 2026).
    - At Oak Dam every record holding a sample at the clip carried its
      channel's tag bit (123), and the first E-to-E study cut on the
      bits.
    - At Roxby the H bits still match the clip (1,072 of 244,633 hx and
      691 of 352,779 hy flagged records hold no clipped sample). The E
      bits do not: 877,512 flagged E records hold no sample at the clip
      (|count| >= 0.94 x 2^23). 2200C11A has 163,650 of 163,692 records
      flagged on ex and ey, none clipped, with a largest |count| of
      5.6 % of full scale.
    - The clip constant itself is 0.94100 x 2^23 on every box seen.
    - Evidence: `tables\ts_saturation_tags.csv`, `clip_level.csv`;
      report_health.md H2 and finding 4.
    Where: the kind's `<site>.mtu5a_flags.csv` (tag byte 15 per record
    and channel) and its run comments ("saturated?"); R5's acceptance
    test compared the flags with the same bits, so it cannot see this.
    Effect: a mask or cut built from the E rows of the flags CSV would
    discard good data; on 2200C11A, all of it.
    Proposal: the kind's E flag rows are labelled as the receiver's
    bits, not clips; any cut on E comes from a sample clip reading at
    0.94 x 2^23 (per record and channel), with the bits kept as a
    reading. A test: a flagged-unclipped E record (2200C11A) yields no
    cut.

134. **No minimum run length: a 4 s recording becomes a run**
    (7 Nov 2026).
    - 180209-10\4572209C (4 TS4 records, 600 samples per channel;
      ex at the clip) became run sr150_0001 of a site in the scout's R5
      trial.
    - Roxby holds 16 recordings under 0.1 h (short tests).
    - Evidence: `tables\workbench_trial.csv`; report_readers.md G2;
      `tables\recordings.csv`.
    Where: `src/mt_workbench/mtu5a.py` (worktree) and the ingest's run
    building.
    Effect: a test of seconds sits in an archive as a run beside the
    real ones, and every later step has to skip it.
    Proposal: a stated minimum run length (refused, or listed and
    skipped, with the reason in the ingest log).

135. **Staging across volumes: hard links cannot cross from E: to D:**
    (7 Nov 2026).
    - The Oak Dam staging tree (118's per-site folders of NTFS hard
      links) needs the raw data and the workspace on one volume.
    - Roxby's raw data is on E: (an HDD), and a workspace belongs on D:.
      A copy of the whole TS4 is 79.6 GiB; stage 1 is 18.1 GiB.
    - Evidence: report_readers.md G7; `tables\ts_walk.csv`;
      `2026_Natural_Source_IP\datasets\roxby\notes\open.md`
      RX-3.
    Where: 118 (site discovery assumes one folder per site).
    Effect: staging Roxby needs copies, symbolic links (a privilege) or
    a recording map read in place.
    Proposal: either a staging copy with a sha256 manifest (no code), or
    118's `recordings:` site key, so data_root can stay on E:.

136. **The .cts band-4 response is a delay plus about 1 deg of filter
    phase at the band top, not a pure delay** (7 Nov 2026).
    - On boxes 2070 and 2200 the band-4 E phase is a delay of 0.19640 s
      (29.460 samples at 150 Hz), equal between the boxes to 0.0003
      samples and to Oak Dam's 0.19643 s.
    - The residual from a pure delay rises to +0.37 deg at 11-14 Hz and
      reaches -1.03 deg at 27.5 Hz, the band's last point.
    - Evidence: `tables\cts_delay.csv`; report_readers.md C2 (FAIL as
      written) and G6.
    Where: 122 (no time-delay convention for the 0.196 s delay; its
    proposal is a delay only).
    Effect: between two MTU-5A boxes it cancels insofar as they share
    it. Against another receiver kind, a delay-only correction would
    leave up to about 1 deg near the top of band 4 [inference].
    Proposal: if 122 is taken up, apply the .cts phase per frequency
    (or the delay plus the tabulated residual), not a delay alone.

137. **Gains vary by recording, and the kind refuses mixed chains at
    one site** (7 Nov 2026).
    - EGN = HGN = 4 on 41 early Roxby recordings (to 171201-02 and the
      parallel test) and 1 on 859. The kind takes each table's own
      gains (R5: 4/4 on 2070B26A, 1/1 on the others, to 1.5e-16).
    - DECL is 4.0 on 51 tables and 7.0 on 923.
    - Evidence: `tables\settings.csv`, `workbench_trial.csv`;
      report_inventory.md finding 5; report_readers.md G4.
    Where: the `mtu5a` kind's site assembly (it refuses a site whose
    recordings' chains differ, by the docstring; not tested on Roxby).
    Effect: a site re-occupied at a different gain cannot be one site;
    it would have to be declared as two.
    Proposal: allow differing chains across runs of one site (the chain
    is per run already), or state the refusal in the survey check with
    the recordings named.

## Added 7 Nov 2026 by the Roxby staging and ingest (notes pass; from `2026_Natural_Source_IP\datasets\roxby\results\stage_stage1_20261107\` and `results\ingest_stage1_20261107\`, and the first E-to-E study's `results\pairs_stage1_20261107\criteria_addendum_2.txt`; gaps and one change of the unmerged `mtu5a` kind, 117, worktree `worktrees\mtu5a-ingest`; 138 is a proposal not decided work; 139 records a change already made in the worktree)

138. **The mtu5a kind's dc-level and health tests do not see a
    near-flat E channel** (7 Nov 2026).
    - REMOTE-RR (receiver 4574) has ex and ey spans (max - min over
      the run) of 1,975-3,320 counts (ex) and 126-191 counts (ey) on
      eight of its nine runs, 4574C05A-C14A, 5-15 Dec 2017. The runs
      last 20-48 h. Against these, every rover E channel of the scope
      spans at least 12,218 counts, and the base's own first run
      (4574C04B) spans 16 million.
    - The electrics were in effect disconnected [inference]. All eight
      runs passed the ingest:
      - the rail test (I5: no sample near 0.9 x 0.941 x 2^23);
      - the clip and flat-record rule (D3, the scout's H3: no clipped
        sample and no exactly flat 1 s record);
      - the dc-level verdicts in the run comments.
    - The kind's "open input?" line fires on a high median: it fired
      on 1-5-2781 hx, median 6.24e6 counts, a channel that is not
      dead. It does not fire on a low spread, and it did not fire on
      REMOTE-RR.
    - It was found only by the study's row builder, which read the
      ingest's per-channel min and max: an unhealthy trial product on
      a base run.
    - Evidence: `results\ingest_stage1_20261107\tables\
      channel_health.csv` (min_counts, max_counts per recording-
      channel), `logs\ingest_REMOTE-RR.txt`, `logs\ingest_1-5-2781.txt`;
      `results\pairs_stage1_20261107\criteria_addendum_2.txt` B7 and
      A9 (a 10,000-count floor; the live E channels start at 12,218
      and the dead ones end at 3,320).
    Where: `src/mt_workbench/dclevel.py` (`level_note`, `classify`)
    and the ingest's `_record_levels` (worktree).
    Effect: a dead or disconnected channel enters an archive with a
    clean dc-level comment. Only an estimator's health test downstream
    can catch it, and only if the channel is on the local side of a
    pair it reads. A base with dead E would poison every pair of its
    epoch unread.
    Proposal: a third dc-level verdict, "flat?" or "dead?", from an
    amplitude floor per channel-run. For example, max - min (or the
    p99 - p01 spread, robust to a spike) under a stated count floor,
    with the floor in the comment and the span beside it. The floor
    would be per kind and gain: here 10,000 counts is about 29 mV/km
    at EGN 1 and 7.3 mV/km at EGN 4 over 100 m. The test: a synthetic
    run of white noise at +-100 counts gets the verdict, and the same
    run at +-1e5 does not. It is the gap the scout's dead-channel rule
    had too (lesson of 7 Nov in the NSIP folder's `notes\lessons.md`).

139. **The mtu5a chain check compared the coil serials (FIXED in the
    unmerged worktree, recorded here so the merge carries it)**
    (7 Nov 2026).
    - `plan_runs` refused both Roxby bases at the staging trial
      (16:02:50-16:03:05). REMOTE-RR: "its recordings differ in HXSN,
      HYSN, HZSN", three coil sets over nine daily tables. REMOTE-53RR:
      "differ in HZSN", two sets over five.
    - The cause: `CHAIN_KEYS` included `*COIL_KEYS.values()` beside
      the numeric chain keys. No coil response is applied (HNOM
      alone), and each run's coil text is built from its own
      recording's table (`channel_chain`).
    - The change (decided 16:2x: change the chain; the staging's
      `plan_amendment1.txt` A1, 64c17fbd...; a builder, edits
      16:26:51; nothing committed):
      - `src/mt_workbench/mtu5a.py`: `CHAIN_KEYS = ("FSCV", "EGN",
        "HGN", "HATT", "HNOM", *DIPOLE_KEYS.values(),
        *CHANNEL_KEYS.values())`, with the comment above it and the
        `plan_runs` docstring saying why. COIL_KEYS and
        `channel_chain` are unchanged.
      - `tests/mtu5a_unit.py`: test M10 (`check_coil_chain`). Two
        recordings differing only in HXSN plan as one site of two
        runs, each hx comment naming its own coil; two differing in
        EGN are still refused with "differ in EGN". Its mutation (the
        coil keys put back) fails with "differ in HXSN ... 15 values
        compared".
    - Hashes:
      - mtu5a.py 807d9136ec6fc6b59d887d18f8dbdd21c1097c8b0067252a98e73f5cbe26c30c
        -> acaf771df510aa2315b041f23e75f356407b2ab83f9a5ab18e05e58786be2803;
      - tests/mtu5a_unit.py a09546c5b72d727dd0342cb347bfdd353a06f0a3727f4642f439283cfc6662a3
        -> ce014325e24a79558b4b83fabcb7df4151fd4abde42a4725d01343ae5315655c;
      - the src tree (112 files) -> a563431365e72f593844725a92981c2195aafa037067773370f4474c60867189;
      - `git diff f177bba` 6256e33f... unchanged, because both files
        are untracked and the diff cannot see them.
    - Suites after the change: mtu5a_unit, survey_unit, ingest_unit,
      ingest_swap_e_unit, ingest_swap_h_unit and ingest_site_cli_unit
      PASS. ingest_phoenix_unit keeps its baseline failure on missing
      Kalkaroo test data.
    - Evidence: `results\stage_stage1_20261107\logs\
      chain_change_report.md` (the exact diffs and the test runs),
      `RUN_LOG.md` 16:32:12-16:34:18, `tables\checks.csv`;
      `results\ingest_stage1_20261107\tables\coils.csv` (REMOTE-RR's
      nine runs, three coil sets, each its own table's).
    Where: `src/mt_workbench/mtu5a.py` lines 137-142 and the
    `plan_runs` docstring; `tests/mtu5a_unit.py` (worktree, both
    untracked).
    Effect: none on the Oak Dam products (every Oak Dam site passed
    the stricter check; their archives were not re-made). The Roxby
    staging, ingest and study are made with the change.
    Proposal: carry it in the merge (Oak Dam OD-14). Record the
    two file hashes at the merge, because the diff hash never covered
    them.
    Note, 13 Nov 2026: carried in c26ad61. The hashes at c26ad61 equal the ones above:
    mtu5a.py acaf771d..., tests/mtu5a_unit.py ce014325.... After the
    wording-only 7a81aec (syntax trees without comments and docstrings
    unchanged): mtu5a.py 46080882..., tests/mtu5a_unit.py d677060a....

140. **process_rr.py labels every reference EDI "lemimt merged"**
    (7 Nov 2026).
    - The comparison figure of Kalgoorlie LP 2006's Kal01 RR Kal02 is
      `tf\Kal01_rr-Kal02_20261107-1944_vs_lemimt.png`, titled "aurora vs
      lemimt" with the legend "xy (lemimt merged)", although the
      reference (surveys/kalgoorlie_lp_2006/reference_edis.yaml) is the
      2006 rrrmt single-site EDI kal01.edi.
    - Evidence: `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\tf\`
      (both stage 1 products), logs\stage1\process_rr_*.log.
    Where: `scripts/process_rr.py`, the comparison figure's title,
    legend and file name.
    Effect: a reader of the figure takes a 2006 rrrmt product for a
    lemimt one.
    Proposal: label the reference by its reference_edis.yaml entry (the
    file name, or a `label:` key), and name the figure `_vs_ref.png`.

141. **select_files and file_start read an Orange Box stamp as UTC
    unless given the clock's zone** (7 Nov 2026).
    - `file_start(path, "orangebox")` and `span(..., "orangebox")` take
      `clock_timezone="UTC"` by default (added with the instrument);
      `select_files(site_dir, start, end, "orangebox")` (via
      `_select_stamped`) calls `file_start` without it, so a window in
      UTC picks files 8 h off at Kalgoorlie (WST clocks).
    - `ingest_site` does not use them for an Orange Box site
      (`_orangebox_units` applies the site's `clock_timezone`), and
      nothing else in the tree calls them for one today.
    Where: `src/mt_workbench/ingest.py` `select_files`,
    `_select_stamped`; `src/mt_workbench/instruments.py` `file_start`.
    Effect: none today; a later caller (the GUI, noise_psd.py) choosing
    Orange Box files by a UTC window would choose the wrong hours.
    Proposal: give `select_files` the site's `clock_timezone`, or refuse
    an Orange Box site there and point at `_orangebox_units`.

142. **new_survey.py writes the LEMI defaults into every survey**
    (7 Nov 2026).
    - The `HEAD` block writes `calibration_fn` (the LEMI-120 table),
      `h_scale: -1000.0`, `processing: min_period 0.005` and
      `notch_frequencies: [50.0, 150.0]` for every instrument; for an
      Orange Box survey (10 Hz fluxgates) none applies: the coil keys
      are left alone in `defaults:` by `_check_instrument_keys`, and the
      band and notches lie above the 5 Hz Nyquist.
    - Seen writing tests/orangebox_ingest_unit.py's synthetic survey
      (test_new_survey).
    Where: `scripts/new_survey.py` `HEAD`; `orangebox_defaults` and
    `phoenix_defaults` amend it.
    Effect: a misleading survey.yaml, harmless at ingest.
    Proposal: per-instrument defaults blocks (the LEMI keys for LEMI
    surveys only; 0.2 s for a 10 Hz survey's min_period).

## Added 7 Nov 2026 by the Roxby raw E check (filing agent; from `2026_Natural_Source_IP\datasets\roxby\results\raw_e_check_20261107\` (README.md, skeptic\skeptic_report.md, tables\e_screen.csv, skeptic\tables\k4_hcross.csv, k4_maps.csv, k2_screen.csv); data checks the Roxby release showed are needed at staging or ingest; none is a defect of the workbench's code, the `mtu5a` kind (117, worktree `worktrees\mtu5a-ingest`) did what it was built to do; proposals not decided work; numbered after 142, the check's README calls them 140-142, which the Kalgoorlie LP 2006 track took at 19:48)

143. **An H-orientation data check at staging or ingest: each
    recording's hx and hy against a simultaneous site's, by
    cross-coherence** (7 Nov 2026).
    - Receiver 2781 (REMOTE-96) has hx and hy physically exchanged
      from 16 Feb 2018. With the labels the table gives, its channel 3
      is coherent with a simultaneous rover's hy at 0.975-0.993 and
      with its hx at 0.037-0.377; channel 4 the reverse (hx
      0.973-0.993, hy 0.021-0.255). Pairs: 2781216A against 4392216A
      (16.4 h) and 4573216B (15.6 h), 2781216B against 4574216C
      (4.2 h), 2781217A against 2200217A (14.4 h).
    - 2781216A's live E settles which side is exchanged: its ex is
      coherent at 0.994 with the rover's hy and its ey at 0.994 with
      the rover's hx (against 4392216A), as a normal E is.
    - The office corrected the map in the .TBL of eight later tables
      (2781218B, 221B, 222A, 222B, 223A, 223B, 224A, 224B: CHHX 4,
      CHHY 3; their .TBO 3, 4), and the data agree (2781218B against
      2200218B, 3.4 h: channel 3 with the rover's hy 0.982, hx 0.007;
      channel 4 with hx 0.950, hy 0.024). The tables of 2781216A, 216B
      and 217A read 3, 4 in both files and are wrong. 217B, 218A,
      219A/B, 220A/B and 221A were not read [inference: uncorrected
      too].
    - Evidence: `skeptic\tables\k4_hcross.csv`, `k4_maps.csv`;
      skeptic_report.md K4 and K4b; README finding 3.
    Where: the staging step (no orientation test today) and the
    `mtu5a` kind, which honours each table's CHHX/CHHY (item 132):
    right for the eight corrected tables, wrong for the three
    uncorrected ones. The kind is not at fault: the map is wrong.
    `swap_h` exists as a declaration, but only someone who knows can
    make it.
    Effect: on 2781216A and 216B (REMOTE-96, in the second study's
    scope) the archive's hx is the field's hy. In an E-to-E T with the
    site as H reference it cancels [inference, as 132 says]; the
    labels, the health tables, a Z or tipper there, and any H-H timing
    check against the site are wrong.
    Proposal: at staging, for every recording with an hour or more
    against another (the base, or a rover), the band-median
    coherences (1-33 Hz) of its table's hx and hy with the other's hx
    and hy; flag the recording when coh(hx, other hy) exceeds
    coh(hx, other hx) and coh(hy, other hx) exceeds coh(hy, other
    hy), listing the .TBL and .TBO maps beside it. A flag, not a
    repair: the `swap_h` declaration stays the user's, and the kind
    keeps honouring the table. Test: 2781216A flagged, 2781218B (a
    corrected table) not, 4392216A not.

144. **A per-recording E-rank reading at ingest, beside the clip and
    flags tables** (7 Nov 2026).
    - 4262B30B (site 30, 30 Nov 2017): coh(ex, ey) 0.915 at 174.1 deg
      over 1-33 Hz (the sceptic 0.904 at 1024-sample segments, 0.917
      at 4096), against 0.192 on 4262C01A, the next day at the same
      site, and at most 0.343 on the 20 other live recordings of the
      set. The E-E spectral matrix's eigenvalue ratio is 0.023 against
      0.386; an exchange cannot change that ratio. Both channels
      respond to one E direction (azimuth about -41 deg): a shared or
      faulty electrode [inference], repaired by the 1 Dec restart.
    - Its table equals every other 4262 table (C1 PASS). Its spans
      (2.2e6 and 2.9e6 counts) pass a floor and its E-H coherences
      (0.63, 0.54) pass a coherence screen.
    - In the first E-to-E study both products on it had a negative
      det T at 30 of 30 product-periods; its sceptic read an E
      exchange. A `swap_e` declaration would have repaired nothing.
    - Evidence: `tables\e_screen.csv`, `tables\checks.csv` (C1, C2,
      C3 FAIL, C8); `skeptic\tables\k1_rank_one_nseg1024.csv`;
      skeptic_report.md K1.
    Where: the ingest's per-run outputs (`channel_health.csv`,
    `<site>.mtu5a_flags.csv`, the dc-level comments of 138): none
    reads E against E.
    Effect: a shorted E pair enters an archive clean and reaches a
    study as an apparent exchange or a bad pair.
    Proposal: per run, coh(ex, ey), arg S(ex, ey) and the E-E
    eigenvalue ratio l2/l1 as band medians, written beside the flags;
    a reading, marked "shared E?" under a stated ratio (the check's
    numbers: 0.023 against 0.386 and above; the coh(ex, ey) >= 0.9
    bar had only 0.004 of margin at the sceptic's segment length, so
    the ratio is the better statistic). Test: 4262B30B marked,
    4262C01A not.

145. **The "dead channel" rule needs coherence beside the amplitude
    floor** (7 Nov 2026).
    - 2070131A's ex spans 9,915 counts, under the 10,000-count floor
      (138's proposal; the first study's addendum 2), and is coherent
      with H at 0.960: live. The floor called it dead (the sceptic's
      K2).
    - The dead channels of the three remotes read E-H coherence
      2.8e-5 to 6.6e-4 (55 recordings: the 188 base's 30, the 96
      base's 17, REMOTE-RR's 8); every live channel of the set reads
      over 0.5.
    - EGN is 1 on every 2018 table read, bases and rovers alike, so
      the gain does not explain the low spans (K3).
    - Evidence: `tables\e_screen.csv` (ex_max_coh_h, ey_max_coh_h),
      `skeptic\tables\k2_screen.csv`, `k4_maps.csv`.
    Where: proposal 138 (a "flat?" or "dead?" verdict from an
    amplitude floor alone); `src/mt_workbench/dclevel.py` (worktree)
    has neither test.
    Effect: a floor alone marks a live, quiet channel dead (here 85
    counts under it), and at another gain or a quieter site, more.
    Proposal: amend 138: "dead?" when the span is under the floor AND
    the channel's band-median coherence with its own site's hx or hy
    is under 0.3 (the check's rule for its next screen), with the span
    and the coherence in the comment; if the site's own H is also
    dead, say so instead. Test: 2070131A's ex not dead, 2070131B's
    dead.

## Added 7 Nov 2026 by the Kalgoorlie LP 2006 track, stage 2 agent B (clocks, frames, levels; `surveys/kalgoorlie_lp_2006/notes/stage2/HANDBACK_agentB.md`, logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\logs\stage2\s2b_*.log`)

146. **h_azimuth.py left Orange Box sites out as "orangebox without a
    fluxgate"** (7 Nov 2026).
    - The Orange Box records a three-component fluxgate (hx, hy, hz),
      but `fluxgate_sites` accepted only EDL bartington and LEMI-424
      sites, so the 20 Kalgoorlie sites were all skipped.
    Where: `scripts/h_azimuth.py` `fluxgate_sites`.
    Change made (agent B, on the stage 2 brief): one condition,
    `instrument in ("lemi424", "orangebox")` in place of
    `instrument == "lemi424"`; nothing else, the EDL and LEMI-424 paths
    untouched. Not done: the module docstring still names EDL
    bartington and LEMI-424 sites only (the brief allowed the one
    condition alone); a test of the orangebox branch.
    Effect before the change: no DC frame for any Orange Box survey.
    Proposal: name the Orange Box in the docstring; a unit test that
    `fluxgate_sites` keeps an orangebox site.

147. **dc_level_check.py: the open-input threshold of 1e9 counts cannot
    be reached by a 24-bit recorder** (7 Nov 2026).
    - `THRESHOLD_COUNTS = 1e9` (`src/mt_workbench/dclevel.py`) suits the
      LEMI 32-bit counts; an Orange Box channel saturates at 2^23 =
      8,388,608 counts, so a channel sitting at the rail (Kal02 ey,
      median +8.389e6, 76.45 % at the rail) is "open input?" only by
      the ratio rule (7.19 x typical, under 30) and here not at all
      without `--threshold-counts 7549747`.
    Where: `src/mt_workbench/dclevel.py` (`THRESHOLD_COUNTS`),
    `scripts/dc_level_check.py` (default of `--threshold-counts`).
    Effect: a railed channel of a 24-bit recorder reads "saturated?" at
    best, never "open input?", unless the user knows to pass the
    threshold.
    Proposal: when the run comment records an input rail, take the
    open-input threshold as that rail (a median at or beyond it is an
    open input); keep 1e9 only where no rail is recorded.

148. **The dc-rail line of an Orange Box run comment says "V" while its
    values are counts** (7 Nov 2026).
    - Every Kalgoorlie run comment reads "dc rail (V, 90 % of the input
      range): hx 7.54975e+06, ...": 0.9 x 2^23 counts, not volts.
    Where: `src/mt_workbench/dclevel.py` `RAIL_PREFIX` (the unit is
    fixed to V, written for the Phoenix rails); the orangebox branch of
    `ingest_site` writes its count rail through it.
    Effect: a reader of the comment (or of dc_level_check's csv) takes
    the rail for 7.5 MV; the numbers are used correctly by
    `parse_level_note`.
    Proposal: the unit as a field of the line ("dc rail (counts, 90 %
    of the input range)"), parsed back by `parse_level_note`.

149. **The processing environment cannot read the INTERMAGNET one-minute
    holdings kept as parquet** (7 Nov 2026).
    - `E:\MT_Timeseries_DATA\Geomagnetic_Observatory_Data\INTERMAGNET_1min`
      holds 2006 as `ASP_1min_2006.parquet`, `LRM_`, `CTA_`, `CNB_`,
      `KDU_`, `GNA_` only (no per-day csv for 2006); bbmt-2026 has no
      parquet engine (`import pyarrow` fails), and the rule is that
      every script runs on bbmt-2026. Stage 0 extracted GNA once on
      mt_aurora_2026.
    Where: the bbmt-2026 environment; the holdings layout.
    Effect: stage 2 could not set Kalgoorlie against a second
    observatory (Alice Springs, Learmonth) to tell a Gnangara
    induction effect from a channel gain on hy (agent B, B2).
    Proposal: pyarrow in bbmt-2026, or a csv extract of the 2006-2007
    parquet years beside the others.

150. **The Orange Box time base has no key for a constant clock offset**
    (7 Nov 2026).
    - `clock_drift_s` (GPS minus logger at recovery) spreads a
      correction linearly from zero at the first header to the drift at
      recovery; a clock that was not on GPS at setup (a constant error)
      cannot be declared. Stage 2 (agent B, B1) measures site offsets
      of 1.2-2.4 s between simultaneous sites that a drift error does
      not fit (Kal016 against Kal024: +2.1 s already at Kal016's 26 %
      of deployment, +3.3 s at 94 %; Kal017 against Kal019: 3.5 s
      steady over 35 h).
    Where: `src/mt_workbench/survey.py` (`SiteConfig.clock_drift_s`),
    `src/mt_workbench/orangebox.py` (`time_base`).
    Effect: a measured setup offset cannot be put into the archive;
    harmless for a single-remote Z (a constant remote delay cancels),
    not for stacks and a common time axis.
    Proposal: an optional `clock_offset_s` (archive time = corrected
    RTC time + offset), recorded in the run comment beside the drift;
    only if the offsets are to be declared.
    - **Checked by the lead, 7 Nov 2026 21:2x:** the key exists for every instrument: `clock_offset_s`
      (`SiteConfig`, a constant shift within +/-60 s, `MAX_CLOCK_OFFSET_S`) is applied by `_shift_clock`
      after `_read_orangebox_run` returns (ingest.py, the call after `_flip_h` in `ingest_site`) and is
      not in `_NOT_ORANGEBOX_KEYS`, so a constant setup error can be declared on an Orange Box site
      today. What is missing is narrower than the title says: no test of the shift on an Orange Box run,
      and a shifted run leaves the whole-tenth UTC grid unless the offset is a multiple of 0.1 s (the
      time-base note does not record the shift; `archive_clock_offset` does). Not re-run on an archive.

## Added 7 Nov 2026 by the Kalgoorlie LP 2006 track, stage 2 agent C (QC cards, edges, noise survey; `surveys/kalgoorlie_lp_2006/notes/stage2/HANDBACK_agentC.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\stage2\scripts\s2c_*.py`, `logs\stage2\`; numbered after agent B's 150)

151. **psd_qc.py's ladder and boundary check are fixed for 1000 Hz**
    (7 Nov 2026).
    - On a 10 Hz record (Kalgoorlie Orange Box) the stages run at 10 and
      1 Hz but keep the 1000 Hz assignment (2-500 Hz, 0.2-2 Hz, ...), so
      the figure draws 0.2-0.5 Hz and 2-5 Hz only, nothing below 0.2 Hz,
      and the boundary check compares the 10 Hz and 1 Hz stages at 2 Hz,
      above the 1 Hz stage's Nyquist: "CHECK FAIL hx @ 2 Hz: +10.07 dB"
      on Kal01 (logs\stage2\psd_qc_Kal01.log), on every site.
    - site_qc.py on the same record prints the 50/100/150 Hz narrow-line
      check as "+nan dB" (above Nyquist), and both figures' subtitles say
      "LEMI linear coefficient x lemi423_b_scale" for an Orange Box
      fluxgate.
    Where: `scripts/psd_qc.py` (the stage table, `BOUNDARY_TOL_DB`,
    `check_boundary_continuity`), `mt_workbench.timefreq.psd_ladder`;
    `scripts/site_qc.py` `check_lines`, the subtitles.
    Effect: no whole-record PSD card for a 10 Hz survey; a FAIL that
    is not a defect of the data.
    Workaround: `s2c_psd_comb.py` (Welch at 2^14 and 2^17 on the 10 Hz
    record, the fifth figure as `<site>_05b_psd10hz.png`).
    Proposal: assign the stages' bands from the record's own rate (the
    top decade below Nyquist, then down by the decimation factor), run
    the boundary check only where both stages are below Nyquist, skip
    mains harmonics above Nyquist, and name the instrument's chain in
    the subtitle.

152. **masks.FOUND_BY is a closed list with no value for a QC-stage
    finding** (7 Nov 2026).
    - The stage 2 brief asked for found_by `stage2-edges` and
      `stage2-rail`; `masks.normalise` refuses anything outside
      ("time", "polar", "cluster", "night", "gate").
    Where: `src/mt_workbench/masks.py` `FOUND_BY`, `normalise`.
    Effect: a proposal file with the brief's tags would not load; the
    proposals use `time` with the tag opening the reason.
    Proposal: either a `qc` value (with the finding's tag in the
    reason, as now), or a free `tag:` key beside found_by that the GUI
    shows and filters on.

153. **The `cp` kind imprints its own comb on a weak periodic
    interference** (7 Nov 2026).
    - `cp_stack_subtract` subtracts the whole median cycle of each window
      from every cycle; on a line-free synthetic background (Gaussian
      noise with Kalgoorlie Kal024 hx's spectrum) cp at 60 s, 30 min
      windows creates all 30 k/60 Hz lines (test T4, tables\cp_trial.csv,
      logs\stage2\cp_trial.log): the median cycle of noise is the same in
      every cycle of a window, so its spectrum lands on the k/period
      lines.
    - On the real 60 s glitch (0.1-0.7 nT, 0.6 s wide) cp takes the fold
      significance on hx from 19-176 to 7-16 but leaves 26-30 lines with 5-14 dB
      mean excess, and adds lines on channels that had none (Kal014 hy:
      0 -> 30).
    Where: `src/mt_workbench/noise.py` `cp_stack_subtract`.
    Effect: on an interference near the noise (any fluxgate glitch, a
    weak cathodic-protection square wave) cp trades the interference's
    comb for one of its own.
    Proposal: subtract only the template bins that stand above the
    template's own noise (e.g. |bin| > 4 x MAD of the bins / sqrt(cycles),
    the rest zeroed), or smooth the template outside a detected pulse;
    a unit test on a line-free background (no new lines) beside the
    existing Burra case.

154. **The `burst` kind's 1 s level blocks hold a burst of comparable
    length at a low sample rate** (7 Nov 2026).
    - `local_level` takes medians of `LEVEL_S` = 1 s blocks (at least 8
      samples); at 10 Hz a 0.6 s glitch fills 6 of a block's 10 samples,
      so the block median is the glitch and `fill_spans` refills the span
      with it. Test T5 (tables\burst_trial.csv): a planted 0.3 nT, 0.6 s
      glitch every 60 s is detected (1.7 % of samples filled) but the fold
      significance only falls from 115 to 107; on the real records
      (threshold 8 and 12) at most about 30 % of the fold significance goes (Kal024 hx 145 -> 100).
    Where: `src/mt_workbench/noise.py` `LEVEL_S`, `local_level`,
    `fill_spans`.
    Effect: `burst` is no remedy for sub-second transients below about
    20 Hz.
    Proposal: take the level from the samples outside the detected spans
    (interpolate across each span from its neighbours), or a `level_s`
    option scaled to the span length.

155. **Filters run over the whole run, crew transients included, so an
    IIR notch rings the masked edges into the record** (7 Nov 2026).
    - A `notch` at k/60 Hz (f0 1/60 Hz, 30 harmonics, 2 passes) applied
      to Kal024 hx's whole run against the settled record alone differs
      by 3.2 nT rms in the first hour after the edge mask and 0.06 nT in
      hours 1-3 at q 100 (7.2 and 0.47 nT at q 300); at Kal012's end
      (a 27,600 nT recovery excursion) 122 nT rms in the last hour.
      (`s2c_notch_trial.py` and the ringing check in the hand-back.)
    Where: `mt_workbench.noise.apply_filters` / `ingest.build_variant`
    (filters see the raw run; masks act later, at processing).
    Effect: a narrow notch, or any long-memory filter, spreads the
    deployment and recovery excursions over hours of good record.
    Proposal: let a filter list skip (bridge or taper) the site's
    `found_by: time` edge masks before filtering, or a `span:` key on a
    filter entry limiting it to the settled record.

156. **`ingest._rot_h` refuses every Orange Box site: the hx and hy chains
    differ by the sign of hy's gain, and the turn demands one response**
    (7 Nov 2026).
    - Declaring `rot_h: 180.0` on Kalgoorlie Kal025 (its fluxgate turned 180
      deg, stage 2) and re-ingesting raised `ValueError: Kal025: rot_h mixes
      the samples of hx and hy, and their filter chains differ (hx
      ['orange_magnetic_hx'], hy ['orange_magnetic_hy']: responses 2.00e+00
      apart): the turn needs one response for both inputs`. The run had
      already been deleted by `--force`, so the site had no archive until the
      key was changed (<ws>/logs/stage2/reingest_Kal025.log).
    - mt-io's Orange Box chain carries hy's polarity in the response
      (`create_orange_magnetic_filter`: +2^23/FS for hx and hz, -2^23/FS for
      hy, docs/upstream_issues.md 13-14), so hx and hy counts have gains of
      opposite sign at every Orange Box site; the check in `_rot_h` compares
      the two responses and finds them 2 apart.
    Where: `src/mt_workbench/ingest.py`, `_rot_h` (line 1429 at the raise).
    Effect: no `rot_h` can be declared on an Orange Box site, so a measured
    fluxgate azimuth (stage 2 holds 19 of them pending the neighbour check)
    cannot be applied at ingest; a 180 deg turn can be written as
    `flip_h: [hx, hy]` instead (done for Kal025, decisions.md D7), any other
    angle cannot.
    Proposal: apply the turn in physical units (counts through each chain,
    the rotation, back through a common chain) or fold a sign-only difference
    of the two gains into the data before the turn and restore it after, with
    a test on a synthetic Orange Box site at 30 deg; and let `--force` keep
    the old archive until the new one is written.

## Added 7 Nov 2026 by the Kalgoorlie LP 2006 track, clock study agent E (`surveys/kalgoorlie_lp_2006/notes/paper/HANDBACK_agentE.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\clock_study\scripts\s2e_*.py`, `logs\clock_study\`; numbered after 156)

157. **The Orange Box time-base note records the first grid point to 0.1 s
    but not the UTC time of the run's first record** (7 Nov 2026).
    - `orangebox.time_base_note` writes `grid_first` (the first 10 Hz grid
      point, rounded to the tenth by `_iso`), the true rate and the RTC error
      and header latency at the run's start, but not `start_ns`, the instant
      the first record was taken. A first run starts at a whole-second header,
      so its grid_first is its start exactly; a later run (Kal017 run 2,
      Kal021 runs 2 and 3) starts at its header less the latency plus the RTC
      error, anywhere within a grid step of grid_first.
    - The clock study's check that the samples sit where each axis' time base
      says (`s2e_axis_check.py`, test 2) had to restrict itself to first runs
      for that reason (all six study sites have one run).
    Where: `src/mt_workbench/orangebox.py`, `time_base_note` and
    `parse_time_base_note`.
    Effect: the placement of a later Orange Box run on the grid cannot be
    recovered from the archive to better than 0.1 s, so a check or a
    re-placement (a changed drift, `clock_offset_s`) of a later run has to
    re-read the raw stamps.
    Proposal: add `first_record_utc=<ISO to the ns>` (from `start_ns`) to the
    note and read it back in `parse_time_base_note`; old archives keep
    working without it.

158. **`h_azimuth.py --neighbours` picks an `h_from` site as base or reference, whose hx and hy are the lender's**
    (7 Nov 2026).
    - Kalgoorlie LP 2006 after Kal05 took Kal03's H and Kal015 took Kal013's (`h_from`, stage 3 agent D):
      the neighbour check chose Kal03 against Kal02 referenced to Kal05 (Kal03's own H as the remote: k 11.3,
      phi spread 49 deg), Kal011 against Kal013 referenced to Kal015 (the base's own H), Kal013 against
      Kal015 (its own H: phi 0.00 exactly), and Kal05 and Kal015 against their lenders (phi 0.00 exactly,
      reported as agreement) (`<ws>/qc/stage3/tables/h_azimuth_neighbours.csv`,
      `<ws>/logs/stage3/h_azimuth_neighbours.log`).
    Where: `scripts/h_azimuth.py`, the choice of base and reference in the `--neighbours` path (nearest
    site overlapping half of the local's record, then the nearest other site overlapping both).
    Effect: five rows of twenty look like tests and are not; Kal05's and Kal015's "difference 0.00" reads
    as a supported frame although their H is the lender's and their own sensor is not measured at all.
    Workaround: `<ws>/qc/stage3/scripts/s3_neighbour_redo.py` reruns Kal03 against Kal02 referenced to
    Kal01 with the script's own `run_intersite` and `neighbour_columns`; Kal05 and Kal015 marked n/a.
    Proposal: read `archive_h_from` of every candidate and of the local; leave out of the base and
    reference choice any site whose H is the local's or the base's (lender or borrower), and write the
    row of an `h_from` site as "H borrowed from <lender>: no frame of its own" instead of a fit.

159. **A stacked remote takes no masks: its members' record-end (crew)
    masks are lost, so a remote-reference run against a stack carries the
    members' deployment and recovery transients** (7 Nov 2026, clock study
    agent E; numbered after 158).
    - `masks.remote_masks` returns an empty list for any `STK_` remote
      (`is_stack`), and build_stack.py builds the stack from the members'
      archives over the recipe window without reading masks.yaml. At
      Kalgoorlie the recipes STK_Kal014_stack and STK_Kal024_stack (agent D's,
      and the clock study's copies) open at Kal024's deployment (2006-05-05
      00:43) and close at Kal012's recovery (05-07 15:46), so the first and
      last hour of the stack hold Kal024's and Kal012's crew transients (up
      to about 900 nT, agent C's edges.csv), which masks.yaml masks at those
      sites with scope both.
    - Seen in the clock study: the squared coherence of Kal014's hx with the
      stack's hx over 2 h windows is 0.00-0.07 at every period with the
      stack's first and last hour kept, and 0.67-0.99 with them left out (the
      transients dominate the window powers); the rr products against the
      stack (`<ws>/experiments/clock_study/{F,C}/tf/*STK*`) show scatter at
      30-200 s that the single-partner products do not.
    Where: `src/mt_workbench/masks.py` `remote_masks`; `scripts/build_stack.py`
    (`mt_workbench.virtual.build_synthetic_remote`).
    Effect: every rr product against a time stack is estimated with the
    members' transients in the remote, unless the local's own masks happen
    to cover them; agent D's stage 3 stack products are affected the same way.
    Proposal: carry the union of the members' scope-both/remote masks that
    name hx or hy to the stack (as the stack's own masks, recorded in its
    provenance), or have build_stack.py write NaN (a gap) over them; a test
    with a synthetic member transient.

## Added 7 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent F (the short-end trial; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentF.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\short_end\scripts\s3f_*.py`, `logs\short_end\`; numbered after 159)

160. **A time stack recipe refuses `use_filters: false`, so a survey that
    declares filters cannot build the raw stack of the same members to
    compare a filter against** (7 Nov 2026, stage 3 agent F; numbered after
    159).
    - `mt_workbench.stacks.Recipe.from_mapping` raises "a time recipe reads
      the members' processing archives (their filtered variants); false is
      not taken" for any time method with `use_filters: false`, although the
      key is documented for every recipe and process_rr.py offers
      `--no-filters` for the local and a site remote. The filtered and the
      unfiltered product of one pair are thus comparable against a site
      remote but not against a stack.
    - Seen: building STK_Kal014_raw (the recipe of record STK_Kal014_stack
      with `use_filters: false`) in a scratch survey whose filters.yaml
      declares the new `template` kind on the members exits 2.
    Where: `src/mt_workbench/stacks.py` (`Recipe.from_mapping`, the
    `use_filters` check); `scripts/build_stack.py --recipe`.
    Effect: a filter trial against stacks needs a second survey folder
    without filters.yaml.
    Workaround: agent F built the raw stacks in
    `<ws>/experiments/short_end/surveys/base_nofilt/` (the same survey.yaml
    and recipes, no filters.yaml) into the same scratch workspace.
    Proposal: let a time recipe take `use_filters: false` and read each
    member's raw archive (`processing_archive(..., use_filters=False)`),
    recording the choice in the stack's provenance; or name the refusal in
    the stacks.yaml documentation.

161. **The new `template` filter kind has no form on the GUI's Filter Data
    tab** (7 Nov 2026, stage 3 agent F; numbered after 160).
    - Agent F added the kind `template` to `mt_workbench.noise` (the
      Orange Box once-a-minute glitch subtracted by its folded template, the
      glitch times fitted as a line; tests/noise_template_unit.py). The brief
      allowed that one change in `src/`, so `gui/filter_forms.py` has no
      form, no entry in `LABELS`, and its summary prints the bare kind
      name. A filters.yaml entry of the kind is applied by `build_variant`
      and `processing_archive` as any other, but it cannot be tried or edited
      on the Filter Data tab.
    Where: `src/mt_workbench/gui/filter_forms.py` (`LABELS`, the form per
    kind, `summary`).
    Effect: the kind is usable from filters.yaml and scripts only.
    Proposal: a form with period_s, width_s, skip_s, chunk_s,
    min_significance, reference and channels, and a summary line; the
    preview on a loaded window needs the window to hold 30 or more cycles
    once skip_s is left out at each end (else the kind leaves it unchanged
    and says so).

162. **Orange Box files named `LP<n>-NNN.BIN` were not Orange Box files to
    the workbench** (8 Nov 2026, SA AusLAMP track, the lead; numbered after 161).
    - 20 of the 28 South Australia AusLAMP Orange Box sites (EP02 EP03 EP04
      SA027E SA030E SA137 SA137_2 SA160 SA163 SA164 SA166 SA168 SA169 SA170
      SA171 SA171_2 SA172_2 SA173 SA174 SA175; boxes 6, 7, 10-15) were written
      by MagLog 4.1 on a Persistor CF2, which names the hourly files
      `LP<n>-NNN.BIN` and the report `LP<n>-RPT.TXT`; the other 8 (MagLog
      3.50, CF1) write `HFM<n>-`. The layout is the same (SA163 LP14-000.BIN
      and SA165 HFM4-000.BIN: 756,066 bytes, header " 00008CA0 ... 7A1",
      report line "High Frequency Magnetometer Number <n>"); mt-io's reader
      never reads the name. `Survey.site_dirs` and `scripts/new_survey.py`
      found 455 sites in the standard copy and skipped the 20.
    Where: `src/mt_workbench/orangebox.py` (`ORANGE_NAME`, `REPORT_NAME`),
    `src/mt_workbench/instruments.py` (`detect_instrument`'s prefix test,
    `INSTRUMENTS["orangebox"]["pattern"]`).
    Effect: a survey loses every LP-named site; a renamed raw file would have
    been the alternative, refused (the copy is byte-identical to the NCI zips).
    Fixed in the working tree (uncommitted): the two regexes take
    `(?:HFM|LP)`, group 1 still the box number; `detect_instrument` tests
    `startswith(("hfm", "lp"))`, then the regex as before; the pattern label
    reads "HFM*.BIN or LP*.BIN". The serial stays "hfm<n>" (the report's own
    words). Test `tests/orangebox_lp_name_unit.py` (names, detection with
    prefer "edl", `record_files`, `report_box`, `header_facts`, `site_dirs`
    of an EDL survey) fails before the change and passes after.

163. **`header_facts` read the Orange Box logger report in the site folder
    itself, so a site whose files sit in a subfolder got `serial: None`**
    (8 Nov 2026, SA AusLAMP track, the lead; found by the test of 162).
    - `report_box(site_dir, prefix)` lists `site_dir` without descending;
      Kalgoorlie keeps `HFM<n>-RPT.TXT` beside the data files in the site
      folder, the SA standard copy keeps both under `<site>/raw/`. Every SA
      Orange Box site would have lost its box number in survey.yaml, and the
      box number matters there (box 14 reads about 8 % low: SA163, SA164,
      SA175; census note).
    Where: `src/mt_workbench/instruments.py`, `header_facts`, the orangebox
    branch.
    Fixed in the working tree (uncommitted): `report_box` is given the data
    files' own folder (`Path(files[0]).parent`), which is the site folder in
    Kalgoorlie's layout and `raw/` in SA's. `report_box` itself is unchanged.
    Covered by `tests/orangebox_lp_name_unit.py` (`header_facts` on a
    `<site>/raw/` layout must return "hfm14").

164. **`new_survey.py` writes no `sample_rate:` for a site recorded on another
    instrument than the survey's, so `Survey.sample_rate_of` gives it the
    survey's rate** (8 Nov 2026, SA AusLAMP track, the lead; numbered after 163).
    - The SA survey is EDL at 10 Hz with six LEMI-424 sites at 1 Hz. The script
      gives such a site its own `instrument:` and `channels:` and reads its rate
      (the summary line says "1 Hz"), but writes no `sample_rate:`; the
      differing-rate note is written only for sites of the survey's own
      instrument. `Survey.sample_rate_of` takes an entry's own `sample_rate:`
      else the survey's, so decimate_site.py, process_rr.py and the window
      arithmetic would have taken the six for 10 Hz.
    Where: `scripts/new_survey.py` (the `own` loop that adds instrument and
    channels); `src/mt_workbench/survey.py` `sample_rate_of`.
    Effect: a mixed-instrument survey silently mis-states the rate of the
    minority sites.
    Workaround: the SA track's `notes/stage0/edit_survey_yaml.py` adds
    `sample_rate: 1.0` to the LEMI-424 entries.
    Proposal: write `sample_rate:` into the entry of every site whose
    instrument is not the survey's when its read rate differs from the
    survey's, and print it in the summary.

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent G (Run 1b on the template variants; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentG.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\run1b\scripts\s3g_*.py`, `logs\run1b\`; numbered after 164)

165. **The `template` filter kind fits every run on its own, so a short run of
    a logger keeps its glitch, and the reason line states a negative span**
    (8 Nov 2026, Kalgoorlie LP 2006 track, agent G; numbered after 164).
    - Kal021's archive holds three runs: 04-23 04:47 to 04-24 20:46 (38 h),
      then 1.00 h and 0.90 h (the converter's split around a file join). The
      variant `Kal021_f6de87167.h5` subtracts the glitch in the first run and
      nothing in the other two: their provenance lines read "template: nothing
      subtracted (estimate span -1.00 h holds fewer than 30 cycles) on ['hx',
      'hy', 'hz']" and "(estimate span -1.10 h ...)". `skip_s: 3600` is left
      out of the estimate at each end of every run, so any run under 2 h has a
      negative estimate span, and any run under about 2.5 h is left whole,
      although the glitch of the same logger was fitted to 0.08 samples rms
      over the 38 h just before (period 59.99753 s, the same box clock).
    Where: `src/mt_workbench/noise.py`, `template_subtract` (the span check
    that sets `info["reason"]`, near line 939) and the per-run loop of
    `apply_filters_arrays` that calls it (near line 1231).
    Effect: 1.9 h of Kal021's 41.9 h keep the once-a-minute glitch in Run 1b
    (every product with Kal021 as local or remote over the whole record; the
    stack STK_Kal021_stack uses the first run only and is not touched). Small
    here; on a survey with many short runs (a logger restarted often) most of
    the record would stay unfiltered with nothing but a provenance line to say
    so. The negative span reads as a bug to whoever meets it.
    Workaround: none needed for Run 1b (recorded per run in
    `qc/run1b/tables/template_runs.csv`).
    Proposal: for a run too short to fit, take the period and the glitch line
    of the longest run of the same site whose clock is continuous with it (the
    glitch times extend across a converter split, as Kal021's run starts show:
    run 2 begins 0.7 s after run 1 ends), or let `skip_s` shrink to what the
    run allows; and state the span as "x h after the 3600 s ends" rather than a
    negative number.

166. **Workbench 159 biases phases, not only errors: three Kalgoorlie group 6
    stack products are off their partners by 12-54 deg at 30-100 s with
    errors under 1 deg, and the best-of's tests keep them** (8 Nov 2026,
    Kalgoorlie LP 2006 track, agent G; numbered after 165).
    - `qc/run1b/scripts/s3g_stack_sanity.py`, `tables/stack_vs_partners_run1b.csv`:
      the median |stack - median of the partners| phase at 30-100 s is 29 deg
      (xy) at Kal014, 18 and 54 deg at Kal016, 12 and 15 deg at Kal024, with
      median stack phase errors of 0.3-0.9 deg, in Run 1 interim (raw
      members) and in Run 1b (template members) alike, so the filter is not
      the cause. Below 30 s the same three are wild (phases from -177 to +160
      deg, errors 0.05-2 deg). Kal012's stack (members Kal014, Kal016,
      Kal024) agrees with its partners within 2 deg. The three biased stacks
      are the three that hold Kal012, whose record ends inside their window
      (the recovery at 7 May 15:4x); agent F's stacks of the same members
      with an hour trimmed at each end (short-end trial) gave sane products.
      The cause is inferred, not shown: the recovery transient in a plain
      mean, which no mask removes (159).
    - Agent D's reading of 7 Nov ("the harm is in the errors, not the level";
      median 0.000 dex over 30-1,000 s) holds as a median over the whole band,
      not at 30-100 s in group 6. The phases stay in quadrant on the 30-3,000 s
      median, so process_rr's quadrant test passes them, and with errors this
      small a partner never replaces them by the 0.67 error rule.
    Where: `scripts/build_stack.py` and `mt_workbench.virtual` (159); the
    best-of rule in the track's `s3_bestof.py` / `s3g_bestof.py`
    (merge_best's `drop_reason` sees no jump or quadrant failure in a band).
    Effect: Run 1 interim and Run 1b interim take Kal014 xy at 17.8-31.6 s
    and 56.2-316 s, and parts of Kal016 and Kal024, from biased stacks.
    Workaround: none applied (the rule is unchanged by the brief); flagged
    to the lead in `notes/stage3/HANDBACK_agentG.md`.
    Proposal: rebuild the group 6 stacks without the record ends (open.md
    30, or the window less an hour each end as agent F did), and add a
    stack-against-partners phase check per band to the best-of before a
    stack can be the base.

## Added 8 Nov 2026 by the Roxby 188 track (ingest trial 1 of 7 Nov 23:15; fixed in the mtu5a-ingest worktree the same morning)

167. **`ingest._swap_h` replaced the channel comment and left the sensor
    attrs with the channel names, so a swap_h archive's hx named the hx
    coil while holding the hy input's samples (FIXED in the unmerged
    worktree, recorded here so the merge carries it)** (8 Nov 2026, Roxby
    188 track; RX-17 option (a), decided 08:0x: fix the kind; numbered
    after 166).
    - `_swap_h` exchanged hx's and hy's samples and filter chains
      (`_INPUT_ATTRS = ("filters",)`), then set each channel's comment to
      "swap_h: the samples and filter chain of the <hy|hx> input". That
      wiped the reader's comment, which on the `mtu5a` kind (117) names
      the table column and coil the samples were read from ("mtu5a: <stem>
      channel N (CHHx), coil <serial> (HxSN), ..."), and left
      `sensor.id`, `sensor.manufacturer` and `sensor.type` with the
      channel names.
    - Found by the Roxby 188 ingest trial (7 Nov 23:08-23:15, check I6):
      REMOTE-96 2781216A, declared `swap_h: true`, archived hx with
      sensor.id BMT53817 = the table's HXSN, while holding the HY input's
      samples; the CHHY/HYSN text was gone. 2-323-p2 is the other Roxby
      site declared swap_h. Evidence:
      `2026_Natural_Source_IP\datasets\roxby\results\ingest_188_20261107\logs\ingester_report_1.md`
      (MEASURED CAUSE) and that folder's `tables\checks.csv` (trial I6).
    - Reproduction: `tests/ingest_swap_h_provenance_unit.py` (worktree).
      Two synthetic MTU-5A sites (the writers of `tests/mtu5a_unit.py`;
      HXSN, HYSN, HZSN three distinct serials), one `swap_h: true`, read
      back with mth5. With the old `_swap_h` (kept in the test verbatim and
      monkeypatched in) the swapped hx carries sensor.id = HXSN and its
      comment lacks "channel 5 (CHHY)" and "coil <HYSN> (HYSN)"; hy the
      mirror.
    Fix: in `_swap_h`, the attrs that describe the samples move with
    them: "filters" and "comments" (`_INPUT_ATTRS = ("filters",
    "comments")`) and every attr whose key starts "sensor." (on the mtu5a
    kind sensor.id, sensor.manufacturer, sensor.type). Then the piece
    "swap_h: the samples, filter chain, sensor and comment of the <hy|hx>
    input, held as <hx|hy>" is appended to each moved comment with
    `_append_comment`, so it follows the reader's text and precedes a
    later flip_h piece. Component, channel number, azimuth, tilt, units,
    sample rate, time period and polarity stay with the channel name; the
    run comment line is unchanged.
    Where: `worktrees\mtu5a-ingest\src\mt_workbench\ingest.py`,
    `_INPUT_ATTRS` and `_swap_h` (unmerged, OD-14); ingest.py
    sha256 e54bfe47... before, 34f335fd... after; src tree hash (Kalkaroo
    A's method, 112 files) a5634313... before, b3dcba95... after;
    mtu5a.py unchanged (acaf771d...). The new test passes and its
    mutation trips P1 and P2; `ingest_swap_h_unit`,
    `ingest_clock_offset_unit`, `mtu5a_unit` (M7 on the Oak Dam file
    included), `ingest_h_from_unit` and `ingest_swap_e_unit` pass;
    `ingest_flip_h_unit` passes F1-F5 (F2: the swap_h piece before the
    flip_h piece) and then crashes in F6 with FileNotFoundError on
    `D:\MT_DATA\MT_Kalkaroo_Phoenix_TEST\G5` (that site folder is no
    longer in the test folder, whose existence alone F6 checks before
    copying; it fails before any ingest).
    Effect: any archive written before the fix from a site declared
    `swap_h`, on any kind, carries hx/hy sensor attrs of the channel names
    and the swap_h line in place of the reader's comment [inference: the
    code path is kind-independent; not surveyed]; the samples and chains
    are right. None of the Oak Dam or Roxby stage-1 archives declares
    swap_h.
    Note, `_swap_e` (not changed): it appends its piece ("swap_e: the
    samples and input stages of the <ey|ex> input, with this channel's
    dipole stage") and so keeps the reader's comment, but that comment
    stays with the channel name. Measured on a synthetic MTU-5A site with
    `swap_e: true`: the archived ex holds the table's CHEY column (1) and
    its comment reads "mtu5a: 4573C07A channel 2 (CHEX), dipole 100 m
    ...; swap_e: ... of the ey input ...". The appended piece says which
    input the samples came from, so the record is not lost as it was in
    `_swap_h`, but the "channel N (CHEx)" text names the column the
    samples were not read from (and an EXR/EYR contact-resistance piece
    would stay with the name too [inference: the synthetic table has no
    EXR]). The kind sets no sensor attrs on E channels (mtu5a.py sets
    sensor.* on magnetic channels only). No Roxby site declares swap_e.
    Proposal: decide whether the E piece should name the input's column
    ("held as ex: the samples of channel 1 (CHEY)") rather than move the
    comment, since the dipole text in it rightly stays with the line.
    Note, 13 Nov 2026: carried in c26ad61. The change holds for every kind that goes
    through `_swap_h`: a continuous LEMI-423, EDL, Phoenix, Orange Box or
    MTU-5A site declared `swap_h`, and an `h_from` neighbour exchanged
    there. The Phoenix burst ingest (`_ingest_bursts`) builds its channel
    comments itself and still ends them with the earlier piece, "swap_h:
    the samples and filter chain of the <hy|hx> input", so a burst site
    and its continuous site describe one exchange in two forms.
    `ingest_swap_h_provenance_unit` passes and its mutation fails P1 and
    P2; `ingest_swap_h_unit` passes with the new comment.

169. **`dclevel.classify` calls a channel pinned at the rail "open input?"
    before "saturated?", so a coil stuck at full scale reads as an open
    input (NOTE, not fixed)** (8 Nov 2026, Roxby 188 track; the ingest of
    record's check I5 and amendment 2 A1; numbered after 168).
    - `mt_workbench.dclevel.classify` gives each channel run its verdict
      in a fixed order: "open input?" when |median| is above
      THRESHOLD_COUNTS (1e9) or its ratio to the typical level of its
      channel type is above RATIO_LIMIT (30); then "saturated?" when the
      share of samples at or beyond the rail is above RAIL_LIMIT (1 %);
      else "ok". A channel pinned AT the rail, whose |median| is the rail
      itself, meets the ratio test whenever the site's other channels of
      its type sit near zero, and so is labelled "open input?". Its rail
      share (100 %) is never consulted.
    - Found by the Roxby 188 ingest of record (8 Nov 08:33, check I5:
      "saturated?" if and only if the raw rail share is over 1 %).
      Reproduction: site 2-67ER, recording 2781203C, run sr150_0001, hz, in
      `D:\MT_DATA\MT_Roxby_Workspace\stage2_188\mth5\2-67ER.h5`. Every one
      of its 7,858 records holds -7,893,679 counts on every sample, so its
      |median| is 7,893,679 counts and its raw share at the rail
      (0.9 x 0.941 x 2^23 = 7,104,312.1 counts) is 100.0000 %. The run
      comment reads "open input? 100.00 %". 7,893,679 is under 1e9, so the
      ratio test is the one that fired [inference from the code]. The
      other three flagged channel-runs of the release (2781215A hy 37.16 %,
      4573204C hy 20.10 %, 4574205A hx 95.04 %) read "saturated?". Evidence:
      `2026_Natural_Source_IP\datasets\roxby\results\ingest_188_20261107\tables\levels_check.csv`,
      `tables\checks.csv` (I5 FAIL; I5-A2 PASS, which counts either label as
      the kind's flag), `logs\ingester_report_3.md`.
    - Effect: the channel IS flagged, so nothing passes unflagged; only the
      label misleads. An open input (a floating or disconnected line) and a
      pinned converter call for different field actions, and a reader of the
      flag line would look for the wrong fault. The channel is in that
      release's pinned_channels.csv either way (clip and flat fraction 1.0).
    Proposal (not decided, the kind not changed): test the rail share
    before the level ratio. A run with its rail share above RAIL_LIMIT reads
    "saturated?" whatever its median; or, at least, a run whose |median| is
    within the rail is never "open input?" by the ratio test alone. A unit
    test would need a pinned channel beside near-zero channels of its type,
    and should fail on the current order.

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent H (the stack windows trimmed under D10; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentH.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\run1b\scripts\s3h_*.py`, `logs\run1b\trim\`; numbered after 167)

168. **Workbench 159 and 166 reach every deployment group, and the members'
    transients make a stack product's errors too small as well as its
    phases wrong: a 10 to 30 min deployment or recovery transient of one
    member inside the window is enough** (8 Nov 2026, agent H; numbered
    after 167).
    - Measured at Kalgoorlie by cutting the 17 recipe windows back to the
      members' `stage2-edges` and `stage2-disturbance` masks at each end
      (decisions.md D10; 8 to 91 min per end; nothing else changed, the
      unchanged STK_Kal020_stack's product repeats to 0.0): the 30-100 s
      median |stack product - partners' median| phase fell at 14 of 17
      stacked sites, from 28.9/24.3, 17.5/22.8, 50.4/17.9 deg (xy/yx) to
      0.21/0.09, 0.03/0.15, 0.06/0.08 at Kal014, Kal016, Kal024 (group 6,
      the 91 min of Kal012's recovery and disturbances), and from 134.4 to
      0.57 deg at Kal02 yx, 17.0 to 0.51 at Kal02 xy, 11.4 to 1.0 at Kal01
      yx, 9.6 to 0.51 at Kal05 xy, 7.3/10.6 to 0.46/1.76 at Kal025, 5.5 to
      1.6 at Kal019 yx (groups 5 and 2: a 10 min deployment transient of
      Kal03, a 31 min one of Kal017, a 42 min recovery of Kal01).
    - The errors: the stack products' median phase errors at 10-30 s grew
      by up to 8x after the trim (Kal08 xy 7.96, Kal02 yx 6.97, Kal021 yx
      6.38, Kal014 xy 2.31) while their values moved by 2-325 of the v1 errors towards
      the partners; at 30-100 s they fell at the group 6 sites (Kal024
      0.19-0.27 of v1) and grew at Kal014 xy (1.76). So the untrimmed
      stack products were biased with errors that did not say so, at
      every group, not only group 6 (166). [inference: a large transient
      in the remote alone raises the remote power of a few windows and
      shrinks the regression errors without adding coherent signal]
    Where: `scripts/build_stack.py` (a recipe window is used as written;
    the members' masks are not read); `mt_workbench.masks.remote_masks`
    (none for a stack, 159).
    Effect: any time stack whose window was set from the members' run
    spans carries their record ends; a best-of that picks by error
    (merge_best's bands, agent D's rule) prefers those products.
    Workaround: D10, the windows cut back by hand in stacks.yaml
    (`s3h_stack_windows.py`).
    Proposal: `build_stack.py --recipe --check` names every member mask of
    a record-end or magnetic kind that overlaps the window or lies within
    20 min of an end, with the window that clears them; or 159's proposal
    (the members' masks carried to the stack), which would also cover the
    transients inside the window.

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent I (Run 1c under min_bin 4; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentI.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\run1c\scripts\s3i_*.py`, `logs\run1c\`; numbered after 169)

170. **The phase and rho errors of every level whose window lasts over
    600 s are about 1.8 times smaller than at 25 % overlap, because the
    75 % overlap there quadruples the windows and the errors count them as
    independent; so the printed errors jump at the 600 s window boundary
    (between the 204.8 s and the 819.2 s levels at 10 Hz)** (8 Nov 2026,
    agent I; numbered after 169).
    - Measured at Kalgoorlie: the 83 Run 1 sources re-run under
      `min_bin: 4` move the bands of 25.6-51.2 s from harmonics 16-32 of
      the 819.2 s level (75 % overlap) to harmonics 4-8 of the 204.8 s
      level (25 % overlap); their median phase error grew 1.63 times over
      360 partner and stack product points, while the bands that moved
      between two 75 % levels (102-205 s, 410-819 s, 1,638-3,277 s) fell to
      0.89-0.95 (`qc/run1c/tables/moved_points.csv`). One run decides it:
      Kal024 rr Kal014 under min_bin 4 with `--overlap-long 25` (tag
      `rr_mb4ol25`, `logs/run1c/diag_Kal024_rr_Kal014_rr_mb4ol25.log`):
      phase errors x1.00 at 12.8-51.2 s (untouched levels), x1.77, 1.79,
      1.82 and 2.03 on the four long levels, about sqrt(3), the ratio of
      the window counts. The test was stated first (fails if the long-level
      errors rise less than 1.3 times).
    - Effect: the errors of `scripts/process_rr.py`'s default
      (`--overlap 25`, `--overlap-long 75`) are optimistic above the 600 s
      level by the share of the overlapped windows that is not independent
      (inferred, not measured: a Hann window at 75 % overlap carries roughly
      twice, not four times, the information of the non-overlapped count, so
      about 1.4 times optimistic). Every error-based rule reads it: the
      best-of's 0.67 replacement test across the boundary, the
      error_above_bound and few_windows flags, "good from" (Kalgoorlie:
      thirteen base-product modes later by one to three bands (to 36-46 s)
      under min_bin 4 because the honest errors there crossed the 3 deg
      bound), the stack-against-partner tests in units of error. The values
      are not affected.
    - Proposal: scale each level's covariance by the overlap's
      equivalent-degrees-of-freedom factor (Welch's for the taper and the
      overlap in use) in `mt_workbench.process` after aurora returns, or
      state the factor in the sidecar and the EDI INFO lines; the aurora
      notes of 1 Nov (deep-level errors optimistic) are probably this.
    - Correction (the lead, 8 Nov 2026 10:1x, after Run 1d at 25 % on every level,
      agent K): the "1.8 times too small" overstates it, and the 75 % overlap
      is not without value. At 25 % the VALUES are noisier, not only labelled
      so: the 200-1,000 s phase roughness of the base products 1.60 to 3.55
      deg at the median, worse at 18 of 20 sites, the spread between a site's
      partner products at 100-1,000 s 1.70 times larger, 28 products losing
      one-window periods. Welch's arithmetic for a Hann taper against
      non-overlapping windows: variance about 0.75/N at 25 % (1.33N windows,
      nearly uncorrelated), 0.53/N at 50 % (2N, adjacent correlated 0.17),
      0.48/N at 75 % (4N, correlated 0.66); so the printed errors are about
      right at 25 %, optimistic by 1.03 at 50 % and by about 1.4 at 75 %, and
      the true error is lowest at 75 %. Measured on three pairs at 50 %
      (`qc/stage3/scripts/`, the 50 % overlap test): printed long-level
      errors 1.44-1.46 times the 75 % ones, roughness 1.08-1.26 times. The
      choice is 50 % (honest by construction) or 75 % with the long levels'
      errors scaled by Welch's factor; the Kalgoorlie survey block now takes
      `overlap_long:` either way (Survey.overlap_pct_long).

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent J (the stack built six ways at six sites; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentJ.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\stack_trial\scripts\s3j_*.py`, `logs\stack_trial\`; numbered after 170)

171. **The time stack's weighting cannot be moved to the band a survey's
    sensors carry without editing the module, and moving it by setting the
    module constants half works: `member_coherence`'s `chunk_s` default is
    bound to `WEIGHT_CHUNK_S` at import, so the `"coherence"` path computes
    weights on 600 s chunks and applies them on chunks of the new length;
    no median or SNR kind exists to compare** (8 Nov 2026, agent J;
    numbered after 170). A proposal, measured by a monkeypatch; nothing in
    `src/` was edited.
    - Where: `mt_workbench.virtual`: `WEIGHT_BAND_S = (0.1, 10.0)`,
      `WEIGHT_CHUNK_S = 600.0`, `CHECK_BANDS_S` fixed for broadband coils
      (39 says so for 1 Hz); `member_coherence(..., chunk_s=WEIGHT_CHUNK_S)`
      evaluated at import; `_coherence_stack` calls it without `chunk_s`
      while its sum loop reads the module global, so after
      `virtual.WEIGHT_CHUNK_S = 3600` the weights of chunk k (600 s) are
      applied to the k-th 3,600 s chunk and the tail takes the last weight
      (`kk = min(k, last)` hides the mismatch). `build_synthetic_remote`
      writes "coherence-weighted stack" in the station comment for any
      weighting other than `"none"`, and `_weights_comments` states the
      coherence rule whatever the kind.
    - Effect: at 10 Hz the Kalgoorlie fluxgates carry no coherent signal
      at 0.1-10 s, so the module's weighting cannot be used at all (agent D
      chose `time_mean`); the trial (`s3j_build.py`) set
      `WEIGHT_CHUNK_S = 3600`, `CHECK_BANDS_S = ((10, 30), (30, 100),
      (10, 100), (30, 300))` (the 3,600 s chunk carries the 10-300 s ladder
      at 10 Hz: `levels_plan` gives one window per level, 69 and 16 Welch
      segments) and replaced `stack_arrays` with a wrapper that calls
      `member_coherence(..., chunk_s=virtual.WEIGHT_CHUNK_S)` explicitly.
      With two members leave-one-out gives both members the same gamma2,
      so every coherence-derived kind is the mean and a "select" is a tie
      break (the module docstring says so; the trial measured an rms
      difference of 1e-4 of the stack's std at Kal03 and Kal025).
    - Proposal: the weight band and chunk scale with the members' rate,
      as on the unmerged `stack-default` branch (29-30 Oct), or are given
      in the recipe (`weight_band_s`, `chunk_s`
      keys of stacks.yaml), with `member_coherence` taking the chunk from
      its caller (no import-bound default); two kinds beside `none` and
      `coherence` as candidates: `snr` (weights gamma2 / (1 - gamma2), the
      deep dive's refinement) and `median` (per sample median of the
      members, offsets removed, on the common chain scale; three members or
      more). The station and run comments name the kind actually used.
      The measured outcome at six sites is in the hand-back.
    - Measured (Kalgoorlie, 32 stacks and products, min_bin 4): at the
      four three-member sites no kind beats the plain mean by more than a
      few per cent; the medians over the eight site-modes of the stack
      product's phase error over the best single partner's run on the
      stack's own window are, at 10-30 s, mean 1.16, coh10/coh30/snr10
      1.16, median 1.09, select10 1.19, and at 30-100 s 1.06-1.07 for
      every kind (against the partners of record, whose overlaps are up to
      86 h against the stacks' 61-63 h: 1.20-1.27). The leave-one-out
      weights give the member whose single-partner products carry the
      smallest errors (Kal014) the smallest hx weight at every group 6
      stack (coh10 0.29-0.30 against 0.33-0.37; select10 takes its hx in
      2-3 % of the hours), so a weighting that measures agreement among
      members does not find the best reference for a local here; a
      residual of the 60 s glitch comb shared by the comb sites was tested
      as the cause and refuted (`tables/comb_line_coherence.csv`). Every
      kind that switches members in time (select10; less so the median)
      steps the members' different slow drifts into the stack at chunk
      edges or sample by sample: select10 moves the 100-1,000 s product by
      0.5-10 errors and lowers the stack's coherence with the local H by
      half; at two members it is 11-46 deg off the partners at 30-100 s
      with errors that look better than the partners' (the bias with small
      errors of 168). Above 100 s every kind but select10 equals the mean
      within 0.25 of an error (the median within 0.5). So the weighting kinds are worth keeping as
      code only if the weights measure each member's noise against the
      local's field, not against the other members; as built here they do
      not pay at Kalgoorlie.

## Added 8 Nov 2026 by the SA AusLAMP 2013-2018 track, stage 2 agent D (`rot_e`, ruling R8; `surveys/south_australia_auslamp_2013_2018/notes/stage2/README_rot_e.md`; numbered after 171)

172. **Ingest refused every electric pair laid off the cardinal axes ("azimuth
    45 is neither 0 nor 180 ... a line at another angle needs a rotation,
    which ingest does not do"), so about 16 SA EDL sites (NF41_2 45/315,
    NF46 210/300, SA002 10/100, SA009 225/135, SA011 60/150, SA023 10/280,
    SA037 140/230, SA070 40/310, SA072 40/130, SA202 30/300, SA274-2 185/95,
    ...) could not be archived** (8 Nov 2026, agent D). `_check_e_azimuths`
    read ex along 0/180 and ey along 90/270 only; the batch log
    `D:\MT_DATA\MT_SA_AusLAMP_2013_2018_Workspace\logs\ingest_NF41_2.log`.
    - Fix (ruling R8): `mt_workbench.ingest._rot_e` turns the calibrated pair
      onto magnetic north and east at ingest, the mirror of `_rot_h`. After
      the reversed-pair rule the ingest already applies (`_e_direction`: a
      line within 90 deg of its nominal azimuth measures along its azimuth,
      one further off along its azimuth + 180; mt-io's dipole-stage sign on
      an EDL, `_standardise_e_orientation` on a LEMI-424, which now applies
      the same rule to a non-cardinal line), [E_N; E_E] = inv(M) [E_bx;
      E_by] with M = [[cos bx, sin bx], [cos by, sin by]]. The chains differ
      by each line's length and sign, so the mix is done in calibrated terms
      and written back through each channel's own chain (Ry = k Rx with one
      real k checked at 19 frequencies; ex' = i00 x + i01/k y, ey' = k i10 x
      + i11 y), exact to rounding; stored azimuths 0 and 90; the line "rot_e:
      ex <a_x> deg, ey <a_y> deg as laid, turned onto magnetic north and east
      at ingest" in the ex/ey comments, the station provenance and the run
      comment (with the angle between the lines), read back by
      `archive_rot_e`. A cardinal layout is untouched (bit-identical to the
      code before, tests/rot_e_unit.py T2). `_check_e_azimuths` stays the
      guard: a line on the other channel's axis (SA013, SA107_2 90/180), a
      pair more than 15 deg from perpendicular as lines (SA033 180/27, SA214
      180/290), Orange Box / Phoenix / LEMI-423, `flip_reversed_dipoles:
      false`, `layout_north` not magnetic, or one line kept are refused,
      naming the site, both azimuths and the angle.
    - Test: `tests/rot_e_unit.py` (T1-T6, written and failed before the
      change; T6 mutation forces the identity turn and is caught).
    - Open: LEMI-424 path built but exercised by no test; products that undo
      a reversal for delivery (`scripts/deliver_as_laid.py`) know nothing of
      a turned pair; Orange Box and Phoenix sign conventions unshown.

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent K (Run 1d at 25 % overlap on every level; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentK.md`, scripts and logs `D:\MT_DATA\MT_Kalgoorlie_LP_2006_Workspace\qc\run1d\scripts\s3k_*.py`, `logs\run1d\`; numbered after 172)

173. **The sidecar records only the periods the window floor removed
    (`dropped_periods`, `min_band_windows`), not those `drop_bad_errors`
    removes for a zero error on every row, so a product can lose a period
    with "dropped_periods: n 0" in its sidecar and the loss shows only as a
    WARNING line in the run log** (8 Nov 2026, agent K; numbered after 172).
    - Met at Kalgoorlie: the 83 Run 1 sources re-run at 25 % overlap on
      every level (D12) lose 9,268 s at 17 products of the 40-45 h sites
      (Kal017, Kal019, Kal020, Kal021, Kal022, Kal025, the Kal02 ex window),
      the five level-7 periods 14,712-46,709 s at the nine products of the
      group 6 sites (Kal012, Kal014, Kal016), and 3,678-11,677 s (all of level 6) at Kal019 rr
      Kal020 and Kal020 rr Kal019; every one of those sidecars says
      `dropped_periods: {"n": 0}`. The run logs say why, e.g.
      `logs/run1d/run_Kal017_rr_Kal019.log`: "Kal017: 1 period(s) with no
      row left to write not written: 9268 s" (level 6, window 52,429 s, two
      STFT windows in the run at 25 % overlap, and the 9,268 s band holds one
      harmonic, so two Fourier coefficients for a two-input regression and a
      zero error; at 75 % overlap the same record gave about five windows).
      The window floor passes the band (two windows, `min_band_windows` 2)
      because it counts windows, not windows times harmonics.
    - Effect: a reader of the sidecars (the best-of scripts, the period
      tests of a comparison) cannot tell a period lost to a degenerate
      regression from one never in the layout; the product's period set
      depends on the overlap without a record of it.
    - Proposed fix: `process_rr.py` (and the single-station path) add the
      periods `drop_bad_errors` returned to the sidecar beside
      `dropped_periods`, e.g. `dropped_zero_error: {"n", "periods_s"}`; and
      consider a floor on Fourier coefficients per band (windows x
      harmonics, at least the inputs + 2) as well as on windows, so the
      drop is decided and recorded by one rule.
    - The same gap one step earlier: in a product merged from channel
      runs (`channel_runs`, the masks per row), a run whose pieces hold too
      few windows for a level has that level's bands marked invalid by
      aurora ("Decimation level 5 band 0 is invalid, not enough points",
      `aurora.pipelines.transfer_function_kernel.make_decimation_dict_for_tf`)
      and the row comes back NaN there with no warning from mt-workbench and
      nothing in the sidecar (`drop_bad_errors` skips rows already NaN).
      Met at Kal02 (ey at the rail 76 % of the record, the ey run cut into
      short pieces): at 25 % overlap every remote-referenced product of
      Kal02 loses its yx row at 920-2,919 s (level 5, window 13,107 s; a
      piece that held two windows at 75 % holds one at 25 %), so the Run 1d
      best-of takes Kal02 yx there from the single station, flagged
      `single_station_source` (`logs/run1d/run_Kal02_rr_Kal01.log` lines
      about 234-260; `logs/run1d/merge_run1d_Kal02.log`).
    - Workaround: read the run log's "no row left to write" lines;
      `qc/run1d/tables/periods_run1d.csv` lists every period lost against
      Run 1c.
    - Met again (8 Nov 2026 10:4x, agent L, Run 1e at 50 % overlap on the
      long levels, D12 as amended; `HANDBACK_agentL.md`): 22 products still
      lack a Run 1c period, every sidecar `dropped_periods: {"n": 0}`; of the
      74 periods Run 1d lost at 28 products only 16 return at 50 % (9,268 s
      at six products of Kal020, Kal021, Kal022; the five level-6 periods of
      Kal020 rr Kal019; the five level-7 periods of the Kal014 single
      station). The group 6 products keep losing 14,712-46,709 s, the
      Kal017/Kal019/Kal025 and Kal02 ex-window products 9,268 s, Kal019 rr
      Kal020 3,678-11,677 s. The same drop also hides losses in Run 1c
      itself (`logs/run1e/run_*.log` lines "no row left to write" at Kal01,
      Kal07 9,268 s and in Kal02 products at 2,317 s). Kal02 yx at
      920-2,919 s is back at five of the six periods in every
      remote-referenced product at 50 %; 2,317 s stays empty there, with
      nothing in the sidecar, and so in the Run 1e best-of (as in Run 1d's;
      Run 1c held all six).
      `qc/run1e/tables/periods_run1e.csv` lists them per product.

## Added 8 Nov 2026 by the Kalgoorlie LP 2006 track, stage 3 agent M (instrument registry DOIs; `surveys/kalgoorlie_lp_2006/notes/stage3/HANDBACK_agentM.md`; numbered after 173)

174. **Feature (8 Nov 2026 10:2x): record each instrument's AuScope
    instrument registry DOI (https://pidinst.data.auscope.org.au/), so that
    which instrument recorded where is in every survey and product. Built
    the same day** (agent M; numbered after 173).
    - survey.yaml keys (`mt_workbench.survey.SiteConfig`, in a site entry or
      `defaults:`): `logger_pid`, `sensor_pid_hx`, `sensor_pid_hy`,
      `sensor_pid_hz`, `electrode_pid`, `platform_pid` (also at the top
      level, `Survey.platform_pid`; a site's own wins). A value is a bare DOI
      `10.<prefix>/<suffix>` (`check_pid`: a URL, a `doi:` prefix, a number
      or an empty string refused, with the form in the message) or `none`
      for an instrument the registry does not hold. Nothing is fetched at
      ingest or processing. `Survey.instrument_pids` resolves a site's (a
      derived site its parent's, a burst site its recorded site's, an
      `h_from` site adds `logger_hx_hy` and the neighbour's hx, hy sensor
      DOIs); `Survey.registry_note` gives the comment piece.
    - Ingest (`mt_workbench.ingest`, the main path and the Phoenix burst
      path): every run comment and the station's provenance comment get
      `instrument_registry: logger <doi>, ..., platform <doi>` (commas, one
      `key: value` piece, as the EMTF XML writer needs, upstream 48);
      `data_logger.id` keeps the serial. An existing archive gains it only
      by a re-ingest; the products below do not need one.
    - `scripts/process_rr.py`: the sidecar's `instrument_pids` (`local`,
      `remote`: `{site, pids}`, a stack `{site, members}` from its recorded
      provenance, `instrument_pids_of`), the dry run's `instrument_pid.local`
      and `instrument_pid.remote` lines, one EDI INFO line per instrument
      (`mt_workbench.instrument_pid_local_logger=<doi>`;
      `mt_workbench.products.pid_info_lines`) and a sentence of
      https://doi.org/ links in the XML's Notes (`products.pid_sentence`,
      called by `frame_note` from the TF's INFO lines, so every product that
      carries the lines gets it). The keys use underscores and a stack
      member's site goes in the value, since mt_metadata's EDI reader keeps
      only the last dotted part of a key (upstream 115) and lower-cases it
      (upstream 570). Not one dotted line per role as first designed: that
      also ran past `products.INFO_MAX` with a logger and three coils.
    - `scripts/merge_best.py`: the merged EDI keeps the first xy source's
      lines and adds each other used source's differing DOIs as
      `mt_workbench.instrument_pid_src<k>_<path>` (`source_pids`); its
      sidecar records `instrument_pids` and its XML's Notes name them.
    - `scripts/pidinst_lookup.py <survey.yaml> [--write] [--responses DIR]`:
      searches the registry (CKAN `package_search?q=<serial>`) for each site
      with a `serial` or `coil_hx/hy/hz` and no DOI, keeps the records whose
      SerialNumber equals the serial and whose model names the site's
      instrument (`MODEL_TOKENS`; serial 10307 is both an Orange Box and a
      Phoenix MTU-5C), prints their service dates against the site's span,
      and with `--write` inserts a key only where exactly one record is
      left, the standing way (dated copy, one inserted line per key, parsed
      diff, comment count, line endings kept). Read only; a network failure
      prints one line and exits 1.
    - Tests: `tests/instrument_pid_unit.py` (7 tests, saved registry
      response `tests/fixtures/pidinst_search_10307.json`, never the live
      API). Docs: README, Instruments section.
    - Kalgoorlie: `logger_pid` written into its twenty entries from
      `instruments.csv` (`<ws>/qc/stage3/scripts/s3m_write_logger_pids.py`,
      copy `survey.yaml.before_logger_pid_20261108-105500`); the proof
      product `<ws>/tf/Kal024_rr-Kal014_20261108-1055_pidcheck.*` carries
      10.82388/25jrcc6q (Kal024) and 10.82388/a092l1jc (Kal014) in its
      sidecar, EDI INFO and XML Notes. No archive re-ingested.
    - Not done: the GUI shows the keys nowhere (the Metadata table lists
      the fields it knows); `scripts/new_survey.py` writes none (its
      KEY_ORDER; run the lookup after it); `scripts/process_intersite.py`
      writes neither the INFO lines nor the sidecar key, and
      `scripts/merge_modes.py` replaces its INFO block with its own lines,
      so its products drop them (`deliver_as_laid.py` keeps them); a stack built
      without a recipe records no members, so its product names none. The
      structured home for a DOI in mt_metadata is upstream 569.


## Added 8 Nov 2026 by the SA AusLAMP 2013-2018 track, stage 2 agent F (four fixes from the Flinders trial; `surveys/south_australia_auslamp_2013_2018/notes/stage2/README_workbench_fixes.md`, checks `D:\MT_DATA\MT_SA_AusLAMP_2013_2018_Workspace\qc\stage2_fr\workbench_fixes\`; numbered after 174)

175. **The choice score charged nothing for periods a product does not hold,
    so a 40 h cross-wave pair stopping at 3,649 s won the remote choice at
    FR09, FR11 and FR15 of the Flinders trial** (8 Nov 2026, agent F; SA
    open.md 30). Both score forms take N, Q and C over the periods the EDI
    holds inside the window; the truncated products (26 of 35 periods in
    10-30,000 s) had coverage 1.000.
    - Fix: `mt_workbench.quality.window_count` (the product's own log-period
      lattice extended over the window) and `window_coverage` C_w, reported
      always; `tf_quality(..., coverage=True)` multiplies the selected form by
      C_w (C_w replaces C in the coverage form), `score_form` "+window".
      scripts/campaign.py: `scoring.coverage`, `scoring.min_coverage` (never the
      stage-1 pick or the best product under it), both in scores.csv and
      summary.md; best_remote.json records the form and floor of each choice
      and re-makes one made under another.
    - Test: `tests/quality_window_coverage_unit.py` (failed first; 36 frozen
      scores of the old code reproduced with the key absent).
    - Flinders re-score of 592 products, no re-run: best remote changes at 6
      of 28 sites, best product at 13 (the R1 qld256 window holds 32 of 35
      periods at 13 sites, stopping at 14,596 s).
    - Open: MANTLE products are now charged for their missing tail under
      `coverage: true`.

176. **campaign.py could not pass window or overlap flags to stages 1 and 2,
    so the Flinders trial ran aurora's 128-sample / 25 % there against ruling
    R1's 256 / 75 %** (8 Nov 2026, agent F; SA open.md 19). Unknown keys under
    `stages.remotes` were silently ignored.
    - Fix: plan keys `stages.remotes.flags`, `stages.stacks.flags` (process_rr.py
      flags on every stage-1 rr run and every stage-2 rr run on a stack, after
      --min-band-windows, before --tag). Checked by process_rr.py's own parser,
      which refuses an unknown flag, a bad value, a positional item, --tag,
      --dry-run and --engine. They are in the row inputs (";flags ..."), the
      dry run, the ledger cmd and summary.md. A `windows:` run takes the flags
      of the full-record run its merge pairs with.
    - Test: `tests/campaign_stage_flags_unit.py`.
    - Real: the dry run of the copy campaign_flinders_1hz_qld.yaml (480/480
      s1, 56/56 s2 rr rows carry them). The smoke FR05L rr FR04L sidecar
      records window 256, overlap 75.

177. **build_stack refused an observatory archive (nanoTesla, no filter chain)
    beside EDL members (microVolt, coefficient chain), so all 28 Ru stacks of
    the Flinders trial failed** (8 Nov 2026, agent F; SA open.md 28).
    - Fix: `mt_workbench.virtual.calibration_plan` takes a chain-less member
      whose units are those the reference chain calibrates to (first applied
      filter's units_in, `_unit_key` spelling-blind) as an identity chain. Its
      ratio 1 / R_ref goes through the existing constant-ratio test, so it is
      scaled by R_ref (x142.857143 for the EDL H coefficient). The reference
      is the first member with a chain. The run comment, station comment,
      calibration_out ``identity`` and build_stack's printout say "member CNB:
      no filter chain, samples in nanoTesla taken as calibrated". Still
      refused: other units or none, a reference chain varying with frequency,
      two chains of different shape.
    - Test: `tests/stack_identity_member_unit.py` (float64 stack vs hand mean
      of calibrated samples 3.8e-16; archived float32 exact).
    - Real: STK_F1FR05LRu (8 L + ASP CNB CTA), FR05L rr it scores 0.945 and
      agrees with the u stack to 0.002 dex.
    - Open: the observatories carry no rot_h while the L sites are turned to
      magnetic north (about 7 deg).

178. **No per-mode processing window from the health table: a whole-record
    product carried the dead weeks of an E line (Flinders FR01 xy at 0.0014
    of the 2018 level, FR25 xy 0.005)** (8 Nov 2026, agent F; SA open.md 29).
    - Fix: `scripts/health_windows.py <survey.yaml> <health_weeks.csv>` writes
      health_windows.yaml. Per site and mode: the longest run of weeks with
      that E line and H sound, "whole" or null, a reason, and derived sites
      clipped with `from:`. campaign.py `windows: <file>` runs one stage-3
      default run per distinct window and merges per mode (a whole mode from
      the full-record run); a null mode is not produced.
      scripts/merge_modes.py writes `mt_workbench.merge_xy_window=` /
      `merge_yx_window=` INFO lines and `merge.windows` in the sidecar.
    - Test: `tests/health_windows_unit.py`.
    - Real (scratch campaign f4check): merged xy vs 2018 FR01 0.624 (whole
      record 0.0015), FR25 0.448 (0.0046), FR27 1.03 (0.088; two windows).
    - Open: a null mode is not blanked in the whole-record product; the
      table's partial last week often reads unsound and trims windows.

179. **A geomagnetic product with a declination always carried ZROT = TROT =
    the declination; SA AusLAMP ruling R7 ("ZROT 0 as QLD") needs ZROT 0 with
    the declination recorded only. Re-writing a read-back EDI also repeated its
    frame lines under the reader's bare keys (frame=, rotation=, rot_h=),
    which with a declination contradicted the new ones** (8 Nov 2026, agent F,
    coordinator's F5; SA notes/stage2/README_workbench_fixes.md F5).
    - Fix: survey.yaml `products: {zrot: declination | zero}` (default
      declination, products byte-identical). `mt_workbench.products`:
      `zrot_rule_of`, `set_zrot_rule`/`tf_zrot_rule` (INFO line
      mt_workbench.zrot_rule=zero), `edi_azimuth` (ZROT/TROT 0 under zero),
      frame lines, `frame_record` zrot_rule, `frame_note`. `_key_is`
      matches read-back bare keys, so stale frame lines are replaced.
      process_rr.py applies the survey's rule; merge_modes.py keeps the xy
      source's (it wrote ZROT = D before).
    - Instruments (R11): `instrument_info_lines` and `apply_instruments` from
      <survey folder>/instruments.csv: INFO mt_workbench.instrument_logger=,
      mt_workbench.instrument_magnetometer= (underscore keys, upstream 115;
      long cells cut to INFO_MAX), run data_logger id/model, magnetic
      channel sensor id/model; sidecar instrument_info.
    - Test: `tests/products_zrot_unit.py` (fixtures frozen with the code
      before).
    - Real: FR05L rr FR01L on a scratch survey copy: HEAD
      COORDINATE_SYSTEM=geomagnetic, DECLINATION 7.36 IGRF-14 2013.75,
      ZROT/TROT 0, INFO geomagnetic.
    - Open: the XML keeps angle_to_geographic_north = D; process_intersite,
      merge_best and deliver_as_laid do not set the rule from survey.yaml;
      the sidecar holds the cut lines.

## Added 8 Nov 2026 by the SA AusLAMP 2013-2018 track, stage 3 agent G (the R13 window merge; `surveys/south_australia_auslamp_2013_2018/notes/stage3/README_windows_merge.md`; numbered after 179)

180. **campaign.py's resume treats a stage 3 config whose flags were edited as already done: a row's inputs
    (`Campaign.inputs`) hold the sites' signatures, masks, window, the plan's min_band_windows and the stage
    flags, but not the config's own flags, so a ledger row done under the old flags passes `already_done`**
    (8 Nov 2026, agent G; NOT fixed).
    - Seen: flinders1G (plan copy `campaign_flinders_1hz_qld_merge_G.yaml`), config d128 first written
      `[--window-samples 128 --overlap 25]`; correcting it in place would have left its 42 runs "done". Worked
      around by renaming the config (def128), so new run ids ran; the d128 rows stay in the ledger.
    - Proposal: add ";config <flags>" (the config's own flags, as `config_flags` gives them, window runs
      `<config>-<modes>win` included) to `inputs` for rr jobs of stage 3, so an edited config re-runs; a plan
      that never edits a config is unaffected, but existing ledgers would re-run once unless the marker is
      added only when non-empty and the old rows are grandfathered (as the stage flags were, issue 176).
    - FIXED 8 Nov 2026 (agent J, SA notes/stage3/README_workbench_round2.md J4): an rr job whose config has
      flags (a stage 3 config and its window runs `<config>-<modes>win`) carries ";config <flags>" in its
      inputs (`CONFIG_MARKER`, placed before the window and floor markers, which campaign_unit expects last);
      a default run adds nothing. `legacy_config_row`: a row written before the marker stays done only when its
      inputs equal the new ones without the marker AND its ledger `cmd` carries the config's present flags, so
      an unedited config is not re-run and an edited one is. Test `tests/campaign_config_flags_resume_unit.py`;
      `tests/campaign_unit.py` test_inputs_masks_both_sites revised (the union config's inputs gain the marker
      by design; recorded in the test).

181. **process_rr.py's sidecar does not record the long-level overlap: its `tweaks` hold `overlap_pct` (25.0 by
    default) and omit `overlap_pct_long` unless `--overlap-long` (or the survey's `overlap_long:`) is given, while
    the default run uses 75 % on every level whose window lasts over 600 s (issue 170)** (8 Nov 2026, agent G;
    NOT fixed).
    - Seen: a default run (FR05L rr FR01L, tag G-D-whole) and a run with `--window-samples 128 --overlap 25`
      both read `band_scheme.window 128, tweaks.overlap_pct 25.0` and nothing else about overlap, yet their
      products differ at every period from 2,299 s on (Z 0.3-34 %, errors 40-160 %), because the second forced
      25 % on the long levels. "The default window, 128 samples at 25 %" (as several notes say) is therefore a
      misreading the sidecar invites: the default is 25 % short, 75 % long.
    - Proposal: always write the overlap in use per level (or `overlap_pct_long` with its source: flag, survey,
      or the built-in 75) in the sidecar and an EDI INFO line.
    - FIXED 8 Nov 2026 (agent J, README_workbench_round2.md J4), sidecar only (no INFO line): key `overlap`
      = {short_pct, long_pct, long_source ("--overlap-long", "--overlap (every level)", "survey processing:
      overlap_long:", "survey processing: overlap: (every level)", "built-in 75 % (mt_workbench.process.
      build_config)"), long_window_s 600, levels}; `levels` is `mt_workbench.process.overlap_table` of the aurora
      config the run used (set on the TF as `OVERLAP_ATTR`). Null for MANTLE. Test
      `tests/process_rr_overlap_sidecar_unit.py` (FR05L rr FR01L smoke: 8 levels, the 6 with windows of 2,048 s
      and longer at 75 %; --overlap-long 25: all 25 %).

## Added 8 Nov 2026 by the SA AusLAMP 2013-2018 track, stage 3 agent J (workbench round 2; `surveys/south_australia_auslamp_2013_2018/notes/stage3/README_workbench_round2.md`, checks `D:\MT_DATA\MT_SA_AusLAMP_2013_2018_Workspace\qc\stage3_J\`; numbered after 181)

182. **The health table had no pair-only H verdict: H_ok judges hx, hy, hz together, so a dead-Bz site with a
    sound pair read H-unsound for its impedance too; and H_ok was blind to a dead PAIR under a live hz at SA
    inclinations (F/F_igrf 0.93 passes F_IGRF_BAND); and a four-channel archive (no hz, lane H's lender sites)
    was refused ("channels ['hz'] not in the archive")** (8 Nov 2026, agent J; SA open.md 44; FIXED).
    - Fix: `mt_workbench.health` week fields H_pair, H_igrf_ratio, `Hpair_ok` (Hx-Hy rules + |H| within
      `H_IGRF_BAND` 0.8-1.2 of the IGRF H, no hz term); with `h_igrf` given H_ok also needs that band (H_ok
      implies Hpair_ok); hz None / all NaN: F and hz fields NaN, `hz_present` False, H_ok False, pair and E
      verdicts computed. health_table.py: IGRF H passed, columns Hpair_ok_weeks, igrf_H, hz_present, printed
      "pair n/N" and "no hz". health_windows.py: xy/yx on Hpair_ok (H_ok for an older table), "tipper: null"
      + "tipper: no hz" for a no-hz site.
    - Tests: tests/health_unit.py T12, T13; tests/health_windows_unit.py (6), (7); health_qld_crosscheck
      unchanged.
    - Real: the ten dead-Bz sites Hpair_ok every week (H/H_igrf 0.98-1.10), SA104C neither; SA222 (no hz)
      pair 3/3, E 3/3; on the v2 table the new H_ok band moves 17 weeks at 8 sites (SA003, SA027M 0.11, SA160
      1.26, SA163 1.38, SA164 1.36, SA170 1.40, SA174 1.24, WA61 1.22).

183. **At a rot_e site the health table judged the turned pair (E_N, E_E), not the recorded lines, so one bad
    recorded line read as both lines bad and as a centre fault (SA009, SA070)** (8 Nov 2026, agent J; SA
    open.md 42; FIXED).
    - Fix: health_table.py `recorded_e` (diagonal_site's `unturn_matrix(b_x, b_y, 1)` on calibrated samples,
      exact: the gains are already divided out) and `health_record(..., e_dirs=)` pairing each recorded line
      with the H perpendicular to its measuring direction; CSV column `e_frame`, printed "lines: recorded".
    - During the build the Ex-Ey coherence went through the e_dirs path as Hy-Ey (wrong exey_med and
      centre_flag at every site, 20:50-21:05 on 8 Nov); caught by the FR05 control, fixed, test (6) added.
    - Test: tests/health_rot_e_unit.py. Real: SA070 recorded ex dead weeks 1-3 (Ex-Ey 0.08, not a centre);
      SA009 Ex 4/4 Ey 0/4; FR05 unchanged; undo equals the words route to float32 rounding.

184. **The observatory archives held geographic X, Y while every site is on its own magnetic north (R7), so an
    R stack or a lender mixed frames by the declination** (8 Nov 2026, agent J; SA open.md 33; FIXED for the four
    SA archives).
    - Fix: `scripts/observatory_rot_h.py <survey.yaml> <CODE> [--apply]`: atan2(median hy, median hx) over the
      archive; --apply turns hx, hy in place in every run (`_rot_h` formula) after a byte-checked dated copy,
      writes "rot_h: <deg> applied to the observatory archive ..." (archive_rot_h reads it), refuses a second
      turn. fetch_observatory.py itself still writes the geographic frame: re-apply after a rebuild (open).
    - Test: tests/observatory_rot_h_unit.py. Real: ASP +4.6810, CNB +12.5573, GNG -1.6550, CTA +7.4008 deg
      (IGRF-14 declination within 0.11 deg); after 0 within 0.0011 deg; |dF| <= 1.5e-11 nT.

185. **products.zrot leftovers (issue 179's Open list): merge_best.py dropped the zero rule (its rebuilt INFO
    lost the rule line, so a merge of zero-rule products wrote ZROT = D) and did not read survey.yaml;
    deliver_as_laid.py kept the input's rule whatever the survey said; the sidecar held the INFO-cut instrument
    lines** (8 Nov 2026, agent J; SA open.md 34; FIXED).
    - Fix: merge_best.py keeps the first xy source's rule, or takes the survey's with the new `--survey`;
      deliver_as_laid.py sets `zrot_rule_of(survey)`; `instrument_info_lines(..., cut=False)` and process_rr's
      sidecar `instrument_info_full` (written when the INFO lines are cut).
    - Not changed, by reading: the EMTF XML's angle_to_geographic_north stays at the declination under zero
      (the schema's x-axis azimuth from geographic north; the XML has no coordinate-system field, so 0 would
      declare the data geographic; the Declination element and the Notes carry the EDI's convention).
      process_intersite.py writes no EDI or XML: nothing to set.
    - Test: tests/products_zrot_round2_unit.py. Real: FR05L rr FR01L under the survey of record and its
      merge_best/deliver_as_laid re-writes: ZROT/TROT 0, DECLINATION 7.36, XML 7.36/97.36.
    - Open: merge_best.py drops the R11 instrument INFO lines of its source (0 lines in the FR05L merge);
      merge_best/deliver_as_laid take the declination from their source EDI, so a source written before the
      site's declination keys gets no DECLINATION (FR05L flinders1 products).

186. **campaign.py stack staleness is blind to member archive changes: a stack row input signature is the stack archive mtime
    alone** (8 Nov 2026, the lead; SA open.md 52; OPEN). Turning the four observatory archives in place (issue 184) made every row with
    an observatory remote stale (their signature carries the remote archive mtime) but no stack build row, although two stacks on
    disk hold observatory members from before the turn (STK_F1FR05LRc, STK_F1FR05LRu: mixed frames). Fix: `signature()` of a STK_
    site folds the member archives (name@mtime, from the stack recipe or the archive comments) so a member change re-runs the build
    and everything downstream; test: a synthetic plan whose stack member archive is touched lists the build row as stale in the dry run.

187. **Stage-1 remote choice has no minimum-overlap gate and the score does not charge window coverage** (9 Nov 2026, the lead;
    SA open.md 55; FIXED-UNCOMMITTED 9 Nov 2026, agent L, lead-verified: the gate existed as min_fraction OR min_hours; now AND
    (R18, 0.5 of the local record), refused_remotes.csv + log line, drop_refused in best_remotes; tests/campaign_overlap_gate_unit.py;
    the coverage charge is the existing plan key scoring.coverage true, no code). flinders10 and flinders1 chose FR09 <- FR11, FR11 <- FR15, FR15 <- FR11 with 1.6-1.7 days of local-remote
    overlap (the changeover between the two Flinders waves) against 20-24 days for every within-wave pair: the product rests on
    1.6 days and its lattice ends at 5,839 s (28 of 35 scored periods; no dropped-period record because the long levels never
    form). scores.csv carries overall_window_coverage 0.80 for these runs but score == overall_score_coverage with
    overall_coverage 1.0 and min_coverage 0.0, so a short smooth product outranks a long one (FR09: 0.963 over FR19's 0.914 with
    34 periods). Fix: (a) campaign stage 1 takes a plan key `min_overlap` (fraction of the local record, proposed 0.5) and
    refuses a remote below it before any run, reporting the overlap days in scores.csv and best_remote.json's `why`; (b) the
    score charges the lattice (periods the run could not populate count against coverage). Test: a synthetic plan with one
    remote overlapping 10 % of the record lists it refused in the dry run and never chooses it; a mutation (gate off) chooses it.

188. **Band masks that leave a band no window fall back to the whole record, silently** (9 Nov 2026, the lead; SA open.md 56; OPEN).
    Two fallbacks: the fork's `aurora.pipelines.transfer_function_helpers.window_mask_for_band` returns None (band unmasked) when
    the masks would leave fewer than max(1, stft.min_num_stft_windows) windows, logging a WARNING 'band left unmasked'; the
    workbench's `_drop_masked_windows` (process.py, MIN_MASKED_WINDOWS 4) skips the mask that would breach its floor, earliest
    first. Both write that band's rows from unselected data as if the masks had applied (SA lane K: 34 rows at FR30 yx, up to 36
    per single-stretch product). Fix: a band the masks leave below the floor produces NO row (NaN impedance and error, the EDI
    row absent or flagged), the sidecar lists the bands and the reason, and the INFO line says how many; the fork (aurora,
    the author's) and process.py change together. Test, fail-first: a synthetic record with masks covering all but one window of a band
    yields no row at that band and the sidecar names it; a mutation (fallback restored) yields the row.

## Added 13 Nov 2026 by the inter-site tensor track (the estimator of `mt_workbench.intersite` and `scripts/process_intersite.py`; numbered after 188)

189. **The inter-site reader calibrated every run of a site with the first
    run's filter chain, so a site whose chain changes between runs (a gain
    change, a re-laid dipole, a coil swap) had its later runs divided by the
    wrong response, with no message** (13 Nov 2026; FIXED for continuous
    inter-site runs, OPEN for the Cross-powers store and the burst reader).
    `crosspower._layout` read each role's chain from the first run only and
    `intersite.read_channels` used it for every run; aurora calibrates each
    run with its own chain, so Z from the same archive was right and T was
    not. Not checked: whether any archive of record has runs with
    different chains.
    - Fix: b12899d. `_layout` reads each run's chain (`run_chains`; runs
      listing the same filters share one). `read_channels` gives a channel
      whose chain changes a `RunResponses` cut at the change: a window takes
      the response of the run holding its centre, and the first sample of
      the later run is a gap when the runs meet, so no window holds two
      chains. The sidecar's calibration lists each run's chain.
    - Test: `tests/intersite_runs_unit.py` (a local of two runs at gains x1
      then x2 against the same record with one chain: within 3 sigma; with
      the code before the fix, 449 sigma).
    - Open: the Z cross-power store of `crosspower.py` (the Cross-powers
      tab's path, `compute_windows` through `_plan_levels`) still divides
      every window by
      `_Station.response(role, f)` for run 0, the first run's chain.
    - Open: `intersite.read_bursts` takes the chain of the first burst slot
      for every burst and refuses a burst whose channel lists other filter
      names; it compares the names only, not the responses or their applied
      flags.

190. **The inter-site readers never remove a declared time_delay filter**
    (13 Nov 2026; OPEN). `crosspower._layout` and `intersite.read_bursts`
    choose the filters to divide out with
    `get_indices_of_filters_to_remove(include_decimation=False,
    include_delay=False)`.
    - Effect: a time_delay filter written into an archive (the per-receiver
      correction upstream 427 asks for) would not reach T or M; the
      estimate would keep the delay.
    - Proposal: take delay filters into the chain when the archive declares
      one, and record them in the sidecar's filters. Test: a synthetic
      archive whose base carries a declared delay of one sample gives the T
      of the undelayed record within 3 sigma; leaving the delay in is the
      mutation that must trip.

191. **The errors of the inter-site tensor were never tested for
    calibration: the recovery rule of `tests/intersite_unit.py` (at most
    5 % of element-bands beyond 3 sigma, none beyond 5) passes errors too
    large by any factor and too small by up to about 1.7** (13 Nov 2026;
    test added, a small bias OPEN).
    - Test: c4e7aeb, `tests/intersite_errors_unit.py`: over 50 seeds of
      clean and bursty fields the fraction of deviations within one stated
      sigma must lie within 3 binomial deviations of 0.623 (elements) and
      0.670 (psi), and errors x2 and x0.5 trip it. At the test's counts
      (900 bands, 3600 element-bands per kind of field) a fraction at its
      expected value, from F(2, 38) and t(19), leaves its interval when
      every error is multiplied by under 0.967 or over 1.034 (pooled
      elements) or under 0.905 or over 1.105 (psi). On the test's own
      seeds the fractions stay inside for factors 0.976-1.045 (elements)
      and 0.927-1.120 (psi) on the clean fields, 0.997-1.060 and
      0.931-1.123 on the bursty ones (the test's series, seeds and
      intervals).
    - Open: each delete-one solve of `intersite.estimate_band` reuses the
      full sample's final Huber weights (`w[keep]`) and is not reweighted.
      On the test's model over 300 seeds (0-299, the test's own functions),
      the stated errors are low: pooled elements by 1.4 % (clean) and 2.5 %
      (bursty), psi by 4.2 % and 6.9 %, the worst element by 5.2 % (bursty
      T_yy). At 300 seeds the test's intervals fail for clean psi and for
      the bursty pooled elements, T_yx, T_yy and psi; at 50 seeds they pass.
      Which part of the bias the reused weights cause is not measured.
      Proposal: run Huber in each delete-one solve; it costs time in
      proportion to the slices.

192. **`scripts/process_intersite.py` on burst sites has no end-to-end test**
    (13 Nov 2026; OPEN). `tests/intersite_bursts_unit.py` tests
    `read_bursts` and the estimate on its arrays, and of the scripts only
    their `--min-period` option and process_rr's resolve;
    `tests/intersite_masks_unit.py` part 3 reads bursts through
    `read_bursts` too.
    - Effect: the script's slot intersection, the compact grid's sample
      count and start, and the sidecar's `grid` block are not tested.
    - Proposal: three synthetic burst sites and their parents in a scratch
      survey; the script's T within 3 sigma of the known T, and the grid
      block equal to a hand count of the shared slots.

193. **`scripts/merge_tensor_bands.py` refuses the whole merged product when
    its overlap check fails, a statistical gate, where a gate should be a
    per-period flag** (13 Nov 2026; OPEN).
    - Effect: with the false-refusal rate of upstream 403 (19-21 % of
      perfectly agreeing merges), an agreeing pair loses its whole wide band
      about one time in five; `--accept-disagreement` writes it with no
      mark on the bands that disagreed.
    - Since d82420e the check pairs only the rows each product formed (a
      row of 0 windows is left out of the overlap).
    - Proposal: always write the merge, with a per-band flag on the shared
      bands under a check of stated false-refusal rate (upstream 403's
      ask).

194. **The inter-site sidecar recorded no azimuth, layout_north or
    declination for either site, so a T between sites laid at different
    azimuths carried their relative turn and the product could not say
    so** (13 Nov 2026; FIXED).
    - Fix: 653eca5. The sidecar's `frames` block and the h5's `frames`
      attribute give the local's and the base's azimuth_ex, azimuth_ey,
      layout_north and declination from survey.yaml (0, 90, magnetic and
      none for a site with no keys), with `applied` false: the tensor
      stays in each site's channels as recorded. The text of
      `flag_off_diagonal` names a turn of more than 45 deg between the
      layouts.
    - Test: `tests/intersite_frames_unit.py`. Criteria 2 and 3 fail
      without the fix: the sidecar and the h5 give each site's declared
      frame, or the defaults where survey.yaml declares none. Criterion 4
      (T, errors and arg(det)/2 identical with and without declared
      frames) checks that the frames are not applied and passes either
      way.

195. **A band the record could not form vanished from the inter-site
    product instead of appearing as a row (a level with under 4 windows, a
    stack band with under 4 kept windows), so products of one survey held
    different periods and every comparison had to join on period** (13 Nov
    2026; FIXED, one part OPEN).
    - Fix: d82420e. `intersite.estimate(..., layout=)`, given the band
      scheme by the script, writes every band of the layout; a band not
      formed has 0 windows, NaN in its tensor, errors and arg(det)/2, and
      `flag_not_estimated`. merge_tensor_bands.py's `shared_bands` pairs
      formed rows only. The pair of record went from 48 to 53 rows (five
      bands of 1977-4982 s with 0 windows), its 48 rows unchanged.
    - Test: `tests/intersite_flags_unit.py` (criteria 4, 5 and 7).
    - Open: a band with windows but fewer than `MIN_SAMPLES` (20) spectral
      samples, or a row whose system is singular, comes back from
      `estimate_band` as `nan + 0j`, so the CSV writes the imaginary parts
      of T as 0, not NaN; the real parts and the errors are NaN and
      `flag_not_estimated` is set.

196. **`MIN_GROUPS` = 3 gives a band an error from as few as 3 jackknife
    slices, itself very uncertain, and nothing flagged a low count** (13 Nov
    2026; FIXED by a flag).
    - Fix: d82420e. `flag_few_groups` marks a band with fewer than
      `FLAG_MIN_GROUPS` (5) slices; the sidecar's `flags` block gives the
      limit and the number of rows. The error is still written from 3
      slices or more: a flag, not a cut.
    - The flag first also marked the bands the record could not form (0
      groups), so the sidecar of the pair of record counted 5 rows where no
      estimated row carries it. `TensorEstimate.flags` now sets every flag
      but `flag_not_estimated` False on a row that is not estimated; T, its
      errors and arg(det)/2 are unchanged.
    - Test: `tests/intersite_flags_unit.py` (criterion 3: the flag equals
      n_groups < 5 on the estimated rows of a 20 min record that has such
      bands; criterion 8: a row not estimated carries no other flag in the
      CSV or the h5, and the sidecar's counts equal theirs).

197. **`flag_low_coherence` reads the weighted coherence of each output E on
    the reference H, which is low in bands where T is well determined**
    (13 Nov 2026; OPEN). `TensorEstimate.flags`, `FLAG_COHERENCE` 0.1, the
    coherence screen limit of upstream 110.
    - Seen: the pair of record (H4 on J3, reference RR_201105) flags 16 of
      its 48 formed rows; those at 0.38-1.5 s carry psi errors of 0.46-2.45
      deg, smaller than those of every unflagged row from 12 s on (4.3-92
      deg). The coherence of E on the reference H follows the source
      field's strength in the band, not how well E_local follows E_base
      [inference].
    - Proposal: judge T by its errors, or by a coherence of the local E on
      the base E through the reference; until then read the flag as a weak
      source, not a poor T.

198. **`scripts/process_intersite.py` has no option for the clock tolerance
    of the timing check, and none to leave masks.yaml out or to name
    another masks file** (13 Nov 2026; OPEN). The script calls
    `intersite.timing_check(est)` with its default
    `TIMING_CLOCK_TOLERANCE_S` (1 s) and reads the masks file of
    `masks.masks_path(survey)`.
    - Effect: a delay beyond 1 s is read as not determined, and is then
      read with `scripts/timing_qc.py` or a call of `timing_check` in
      Python; a pair run without its masks, or with a trial set, needs the
      survey's masks.yaml changed.
    - Proposal: `--clock-tolerance S` (recorded in the sidecar's
      `timing_check`), `--no-masks` and `--masks FILE` (recorded in the
      `masks` block).
