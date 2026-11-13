# -*- coding: utf-8 -*-
"""
Unit test for an all-null EDL stamp (`mt_workbench.ingest._edl_samples`, `_edl_plan`, `mt_workbench.instruments.span`)

A PR6-24 file can hold bytes but no samples: AusLAMP Victoria's
`VIC076_140628150000.BY` is 53,248 bytes of zeros where its BX, BZ, EX and
EY are readable miniSEED of 36,000 samples. mt-io's `count_samples` raises
``ValueError("... holds bytes but no samples")`` on such a file by design,
and `_edl_plan` counted every file unguarded, so one hour refused the whole
site (workbench issue 75). Each case writes a synthetic EDL site in a fresh
scratch folder: seven hourly stamps from 2014-06-28 12:00 UTC of five ASCII
channel files (``EDLN_YYMMDDhhmmss.BX`` ... ``.EY``, 36,000 integer samples
each at 10 Hz, every value distinct) in a day folder ``179/``, and a
``config/recorder.ini`` giving the rate. Some files are then replaced: by
53,248 zero bytes (an all-null block), by 0 bytes, or by a folder. The
plan is read through `_group_contiguous` (the grouping `ingest_site`
calls), the span through `span`, and the archive of (a) and (b) is built
by `ingest_site` and read back with h5py.

Usage:
    python tests/edl_null_stamp_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(a) stamp 3 (15:00) has its five files replaced by 53,248 zero bytes each:
    `_edl_samples` does not give None for such a file (and 36,000 for a
    readable one); the runs are not stamps [0, 1, 2] and [4, 5, 6]; the
    grouping's warnings are not exactly the one line "1 EDL file stamp(s)
    whose files hold bytes but no samples (all-null blocks): 2014-06-28
    15:00:00 53248 bytes (EDLN_140628150000.BX EDLN_140628150000.BY
    EDLN_140628150000.BZ EDLN_140628150000.EX EDLN_140628150000.EY); left
    out, the run split there" (the stamp, the byte size, the files);
    `ingest_site` does not build exactly two runs, starting at 12:00 and
    16:00, whose hx, hy, ex and ey equal the values written to the files of
    their stamps (108,000 samples each); or `span` is not 12:00 to 19:00
    over 7 stamps;
(b) only stamp 3's BY is the all-null block (the other four files
    readable, VIC076's pattern): the stamp is not left out the same way
    (the one warning ending "53248 bytes (EDLN_140628150000.BY); left out,
    the run split there", nothing reported as "differ in length"), or
    `ingest_site` does not build the same two runs with the written values;
(c) the last stamp (18:00) is all-null: the runs are not [0, ..., 5] with
    the one warning naming 18:00:00, or `span` does not end at 18:00:00
    (that stamp's start) over 7 stamps with exactly the warning
    "EDLN_140628180000.BX holds bytes but no samples (an all-null block):
    counted as 0 samples, the span ends at its stamp";
(d) stamp 3's five files are 0 bytes (TAS112's case): `_edl_samples` does
    not give 0, the runs are not [0, 1, 2] and [4, 5, 6], or the warnings are
    not exactly the existing "1 EDL file stamp(s) whose files hold no
    sample: 2014-06-28 15:00:00; left out" (no all-null line);
(e) any other error from `count_samples` is swallowed: a folder in the
    place of stamp 3's BY (an unreadable path: PermissionError on Windows,
    IsADirectoryError elsewhere) must raise that OSError from
    `_edl_samples` and from `_edl_plan`, and a folder as the last stamp's BX
    from `span`; a ValueError of another text ("bad record header", from
    `count_samples` replaced for those files) must raise from
    `_edl_samples`, `_edl_plan` and `span`.

The mutation: with the plan and the span as they stood before issue 75
restored (`_old_plan` and `_old_span`, the bodies unchanged), cases (a), (b)
and (c) must fail by mt-io's ValueError "holds bytes but no samples", and
(d) and (e) must pass under both.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import mt_workbench.ingest as ingest  # noqa: E402
import mt_workbench.instruments as instruments  # noqa: E402
from mt_workbench.instruments import INSTRUMENTS, edl_sample_rate, file_start, record_files  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

FS = 10  # Hz
PER_FILE = 36_000  # one hour at 10 Hz
NULL_BYTES = 53_248  # VIC076_140628150000.BY
CHANNELS = ("BX", "BY", "BZ", "EX", "EY")
COMPS = (("hx", "BX"), ("hy", "BY"), ("ex", "EX"), ("ey", "EY"))  # the survey's channels and their files
T0 = datetime(2014, 6, 28, 12, tzinfo=timezone.utc)
N_STAMPS = 7
SITE = "EDLN"
INI = "[recorder]\n" + "".join(f"channel_{n}_samplerate={FS}\n" for n in range(5))
NULL_LINE = ("1 EDL file stamp(s) whose files hold bytes but no samples (all-null blocks): {when} 53248 bytes ({files})"
             "; left out, the run split there")
EMPTY_LINE = "1 EDL file stamp(s) whose files hold no sample: 2014-06-28 15:00:00; left out"
SPAN_LINE = ("EDLN_140628180000.BX holds bytes but no samples (an all-null block): counted as 0 samples, the span "
             "ends at its stamp")
STALE = "holds bytes but no samples"  # mt-io's refusal: the old plan and span raise it on (a), (b) and (c)
OLD_FAILS = {"a", "b", "c"}  # the cases the old plan and span must fail (the mutation)


def _old_plan(files: list[Path], stamps: list[int], drop: set[int], rate: float, suspect: set[int] | None = None
              ) -> tuple[list[set[int]], dict[int, tuple[int, int]]]:
    """Return `_edl_plan` as it stood before issue 75 (the mutation): every file counted unguarded."""
    from loguru import logger
    from mt_io.uoa.pr624 import count_samples

    lengths: dict[int, set[int]] = {}
    for f, s in zip(files, stamps):
        lengths.setdefault(s, set()).add(count_samples(f))
    uneven = {s for s, n in lengths.items() if len(n) > 1 and s not in drop}
    if uneven:
        logger.warning(f"{len(uneven)} EDL file stamp(s) whose channel files differ in length: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} {sorted(lengths[s])}"
                                   for s in sorted(uneven)) + "; left out, the run split there")
    ordered = sorted(lengths)
    nxt = dict(zip(ordered, ordered[1:]))
    other = sorted(s for s in (suspect or set()) if s in nxt and s not in drop
                   and max(lengths[s]) > (nxt[s] - s) * rate + 2)
    if other:
        logger.warning(f"{len(other)} EDL file stamp(s) recorded while recorder.msg had a data channel at another "
                       f"rate than {rate:g} Hz, their files overrunning the next stamp "
                       f"({pd.Timestamp(other[0], unit='s'):%Y-%m-%d %H:%M:%S} .. "
                       f"{pd.Timestamp(other[-1], unit='s'):%Y-%m-%d %H:%M:%S}): left out, the run split there")
        drop = set(drop) | set(other)
    empty = sorted(s for s, n in lengths.items() if n == {0} and s not in drop)
    if empty:
        logger.warning(f"{len(empty)} EDL file stamp(s) whose files hold no sample: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S}" for s in empty) + "; left out")
    runs: list[set[int]] = []
    trims: dict[int, tuple[int, int]] = {}
    inside: list[int] = []
    ids: set[int] = set()
    end, cut = None, []
    kept_end, kept_stamp = None, None  # the end of the samples kept so far, and the stamp they end with
    for s in sorted(lengths):
        if s in drop or s in uneven:
            if ids:
                runs.append(ids)
            ids, end = set(), None
            continue
        n = next(iter(lengths[s]))
        if n == 0:
            continue
        if kept_end is not None and s < kept_end - 2.0 / rate:
            overlap = int(round((kept_end - s) * rate))
            if overlap >= n:
                inside.append(s)
                continue
            if ids:
                runs.append(ids)
            ids = {s}
            trims[s] = (overlap, kept_stamp)
            end = kept_end = s + n / rate
            kept_stamp = s
            continue
        if ids and abs(s - end) > 2.0 / rate:
            runs.append(ids)
            ids = set()
            if s > end:
                cut.append(s)
        ids.add(s)
        end = s + n / rate
        if kept_end is None or end >= kept_end:
            kept_end, kept_stamp = end, s
    if ids:
        runs.append(ids)
    if cut:
        logger.info(f"{len(cut)} EDL run split(s) where a file ends before the next stamp")
    for s, (overlap, earlier) in sorted(trims.items()):
        logger.warning(f"EDL file stamp {pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} starts {overlap / rate:g} s "
                       f"before the samples of {pd.Timestamp(earlier, unit='s'):%Y-%m-%d %H:%M:%S} end: its first "
                       f"{overlap} samples are left out, the earlier file's kept")
    if inside:
        logger.warning(f"{len(inside)} EDL file stamp(s) wholly inside the samples of the file before them: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S}" for s in inside) + "; left out")
    return runs, trims


def _old_span(site_dir: Path, instrument: str, files=None) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return `span` as it stood before issue 75 (the mutation): the last file counted unguarded."""
    files = files if files is not None else record_files(Path(site_dir), instrument)
    if not files:
        raise FileNotFoundError(f"no {INSTRUMENTS[instrument]['label']} files under {site_dir}")
    if instrument == "phoenix":
        return instruments._phoenix_span(files)
    starts = sorted({file_start(f, instrument) for f in files})
    if instrument == "lemi423":
        spacing = int(np.median(np.diff(starts))) if len(starts) > 1 else INSTRUMENTS[instrument]["file_seconds"]
        end = starts[-1] + spacing
    elif instrument == "lemi424":
        end = instruments._lemi424_last_second(files[-1]) + 1
    else:
        from mt_io.uoa.pr624 import count_samples

        rate = edl_sample_rate(site_dir, files)
        last = next(f for f in files if file_start(f, instrument) == starts[-1])
        end = starts[-1] + (count_samples(last) / rate if rate else INSTRUMENTS[instrument]["file_seconds"])
    to_ts = lambda s: pd.Timestamp(s, unit="s", tz="UTC")  # noqa: E731
    return to_ts(starts[0]), to_ts(end), len(starts)


def stamp_of(k: int) -> str:
    """Return the YYMMDDhhmmss of hourly stamp k."""
    return f"{T0 + timedelta(hours=k):%y%m%d%H%M%S}"


def names_of(k: int, channels=CHANNELS) -> str:
    """Return the file names of stamp k's channels, as the all-null warning lists them."""
    return " ".join(f"{SITE}_{stamp_of(k)}.{c}" for c in channels)


def build_site(root: Path, null: dict | None = None, zero: dict | None = None) -> tuple[Path, dict]:
    """Write the synthetic site under root/raw/EDLN; return (the folder, {(stamp, suffix): the values written}).

    Args:
        root (Path): The case's folder.
        null (dict, optional): {stamp index: the channels written as NULL_BYTES zero bytes}.
        zero (dict, optional): {stamp index: the channels written as 0-byte files}.
    """
    site = root / "raw" / SITE
    day = site / "179"
    day.mkdir(parents=True)
    (site / "config").mkdir()
    (site / "config" / "recorder.ini").write_text(INI, encoding="utf-8")
    truth = {}
    for k in range(N_STAMPS):
        for c, suffix in enumerate(CHANNELS):
            path = day / f"{SITE}_{stamp_of(k)}.{suffix}"
            if suffix in (null or {}).get(k, ()):
                path.write_bytes(bytes(NULL_BYTES))
            elif suffix in (zero or {}).get(k, ()):
                path.write_bytes(b"")
            else:
                values = (c + 1) * 10_000_000 + k * 100_000 + np.arange(PER_FILE)
                path.write_bytes("".join(f"{v}\n" for v in values).encode("ascii"))
                truth[(stamp_of(k), suffix)] = values.astype(float)
    return site, truth


def warnings_of(call) -> tuple[object, list[str]]:
    """Return `call()`'s result and the warning lines loguru logged during it."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING", format="{message}")
    try:
        return call(), lines
    finally:
        logger.remove(sink)


def plan_of(site: Path) -> tuple[list[list[int]], list[str]]:
    """Return the stamps (as indices) of each run `_group_contiguous` makes of the site, and its warnings."""
    files = record_files(site, "edl")
    groups, lines = warnings_of(lambda: ingest._group_contiguous(files, None, "edl", rate=FS))
    index = {stamp_of(k): k for k in range(N_STAMPS)}
    return [sorted({index[p.stem.split("_")[1]] for p in g}) for g in groups], lines


def span_of(site: Path) -> tuple[tuple[str, str, int], list[str]]:
    """Return (start, end, stamps) of `instruments.span` on the site as text, and its warnings."""
    (start, end, n), lines = warnings_of(lambda: instruments.span(site, "edl"))
    return (f"{start:%H:%M:%S}", f"{end:%H:%M:%S}", n), lines


def archive_check(root: Path, truth: dict, want_runs: list[list[int]]) -> list[str]:
    """Ingest the site with `ingest_site` and check its runs against the values written. Returns the failures."""
    import h5py

    survey = Survey({"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0,
                                  "channels": ["ex", "ey", "hx", "hy"]},
                     "sites": {SITE: {}}}, root)
    path = ingest.ingest_site(survey, SITE, overwrite=True)
    bad = []
    with h5py.File(path, "r") as h5:
        station = h5[f"Experiment/Surveys/t/Stations/{SITE}"]
        runs = sorted(n for n, g in station.items() if g.attrs.get("mth5_type") == "Run")
        if runs != [f"sr10_000{i + 1}" for i in range(len(want_runs))]:
            return [f"archive runs {runs}, expected {len(want_runs)}"]
        for name, ks in zip(runs, want_runs):
            run = station[name]
            t0 = pd.Timestamp(run.attrs["time_period.start"])
            t0 = t0.tz_convert(None) if t0.tzinfo else t0
            if t0 != pd.Timestamp(T0.replace(tzinfo=None) + timedelta(hours=ks[0])):
                bad.append(f"{name} starts {t0}, expected stamp {ks[0]}")
            for comp, suffix in COMPS:
                want = np.concatenate([truth[(stamp_of(k), suffix)] for k in ks])
                got = run[comp][()]
                if not np.array_equal(got, want):
                    bad.append(f"{name} {comp}: {got.size} samples, not the {want.size} written")
    return bad


def check_plan(case: str, site: Path, want_runs: list[list[int]], want_lines: list[str]) -> list[str]:
    """Check the grouping's runs and warnings. Returns the failures."""
    runs, lines = plan_of(site)
    bad = []
    if runs != want_runs:
        bad.append(f"({case}) runs {runs}, expected {want_runs}")
    if lines != want_lines:
        bad.append(f"({case}) warnings {lines}, expected {want_lines}")
    return bad


def case_a(root: Path) -> tuple[str, list[str]]:
    """Stamp 3's five files all-null: two runs, the warning, the archive, the span."""
    site, truth = build_site(root, null={3: CHANNELS})
    null_file, good_file = site / "179" / f"{SITE}_{stamp_of(3)}.BY", site / "179" / f"{SITE}_{stamp_of(2)}.BY"
    bad = []
    counts = (ingest._edl_samples(null_file), ingest._edl_samples(good_file))
    if counts != (None, PER_FILE):
        bad.append(f"(a) _edl_samples gave {counts}, expected (None, {PER_FILE})")
    want = [[0, 1, 2], [4, 5, 6]]
    bad += check_plan("a", site, want, [NULL_LINE.format(when="2014-06-28 15:00:00", files=names_of(3))])
    got_span, _lines = span_of(site)
    if got_span != ("12:00:00", "19:00:00", 7):
        bad.append(f"(a) span {got_span}, expected 12:00:00 to 19:00:00 over 7 stamps")
    bad += [f"(a) {b}" for b in archive_check(root, truth, want)]
    return "runs [0,1,2] [4,5,6]; warning; archive 2 runs == written; span 12-19 h", bad


def case_b(root: Path) -> tuple[str, list[str]]:
    """Only stamp 3's BY all-null: the stamp left out the same way, not as uneven; two runs in the archive."""
    site, truth = build_site(root, null={3: ("BY",)})
    want = [[0, 1, 2], [4, 5, 6]]
    bad = check_plan("b", site, want, [NULL_LINE.format(when="2014-06-28 15:00:00", files=names_of(3, ("BY",)))])
    bad += [f"(b) {b}" for b in archive_check(root, truth, want)]
    return "runs [0,1,2] [4,5,6]; warning (the .BY), no 'differ in length'; archive == written", bad


def case_c(root: Path) -> tuple[str, list[str]]:
    """The last stamp all-null: the plan drops it, the span ends at its start with the warning."""
    site, _truth = build_site(root, null={6: CHANNELS})
    bad = check_plan("c", site, [[0, 1, 2, 3, 4, 5]],
                     [NULL_LINE.format(when="2014-06-28 18:00:00", files=names_of(6))])
    got_span, lines = span_of(site)
    if got_span != ("12:00:00", "18:00:00", 7):
        bad.append(f"(c) span {got_span}, expected 12:00:00 to 18:00:00 over 7 stamps")
    if lines != [SPAN_LINE]:
        bad.append(f"(c) span warnings {lines}, expected [{SPAN_LINE!r}]")
    return "runs [0..5]; warning; span 12-18 h with its warning", bad


def case_d(root: Path) -> tuple[str, list[str]]:
    """Stamp 3's five files of 0 bytes: the existing `empty` path, its text unchanged."""
    site, _truth = build_site(root, zero={3: CHANNELS})
    bad = []
    n = ingest._edl_samples(site / "179" / f"{SITE}_{stamp_of(3)}.BX")
    if n != 0:
        bad.append(f"(d) _edl_samples of a 0-byte file gave {n}, expected 0")
    bad += check_plan("d", site, [[0, 1, 2], [4, 5, 6]], [EMPTY_LINE])
    return "runs [0,1,2] [4,5,6]; the existing 'hold no sample' line only", bad


def _raises(call, kind) -> str | None:
    """Return None when call() raises `kind`, else what happened."""
    try:
        call()
    except kind:
        return None
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}: {exc}"
    return "returned"


def case_e(root: Path) -> tuple[str, list[str]]:
    """Any other error from count_samples still raises: an unreadable path (a folder) and another ValueError."""
    import mt_io.uoa.pr624 as pr624

    site, _truth = build_site(root)
    day = site / "179"
    files = record_files(site, "edl")
    stamps = [file_start(f, "edl") for f in files]
    bad = []
    # an unreadable path: a folder in the place of stamp 3's BY (outside the site, so record_files never lists it)
    folder = root / "unreadable" / f"{SITE}_{stamp_of(3)}.BY"
    folder.mkdir(parents=True)
    swapped = [folder if f.name == folder.name else f for f in files]
    for what, call in (("_edl_samples(folder)", lambda: ingest._edl_samples(folder)),
                       ("_edl_plan with the folder", lambda: ingest._edl_plan(swapped, stamps, set(), float(FS)))):
        why = _raises(call, OSError)
        if why:
            bad.append(f"(e) {what} {why}, expected an OSError")
    last_bx = next(f for f in files if f.name == f"{SITE}_{stamp_of(6)}.BX")
    (root / "unreadable" / last_bx.name).mkdir()
    last_swapped = [root / "unreadable" / last_bx.name if f == last_bx else f for f in files]
    why = _raises(lambda: instruments.span(site, "edl", last_swapped), OSError)
    if why:
        bad.append(f"(e) span with a folder as the last BX {why}, expected an OSError")
    # another ValueError from count_samples, for the stamp-3 BY and the last BX only
    real = pr624.count_samples

    def other_error(fn):
        if Path(fn).name in (f"{SITE}_{stamp_of(3)}.BY", last_bx.name):
            raise ValueError(f"{Path(fn).name}: bad record header")
        return real(fn)

    pr624.count_samples = other_error
    try:
        for what, call in (("_edl_samples", lambda: ingest._edl_samples(day / f"{SITE}_{stamp_of(3)}.BY")),
                           ("_edl_plan", lambda: ingest._edl_plan(files, stamps, set(), float(FS))),
                           ("span", lambda: instruments.span(site, "edl", files))):
            try:
                call()
                bad.append(f"(e) {what} returned on another ValueError")
            except ValueError as exc:
                if "bad record header" not in str(exc):
                    bad.append(f"(e) {what} raised another ValueError than the one given: {exc}")
    finally:
        pr624.count_samples = real
    return "OSError (folder) and another ValueError raise from helper, plan, span", bad


CASES = {"a": case_a, "b": case_b, "c": case_c, "d": case_d, "e": case_e}


def run_cases(root: Path, label: str) -> dict[str, list[str]]:
    """Run every case in a fresh folder under root; print a row each; return the failures by case."""
    failures = {}
    for case, fn in CASES.items():
        base = root / label / case
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
        try:
            expected, bad = fn(base)
        except Exception as exc:  # noqa: BLE001  (the mutation's ValueError, or a defect)
            expected, bad = fn.__doc__.split(":")[0], [f"({case}) raised {type(exc).__name__}: {exc}"]
        failures[case] = bad
        print(f"  [{label}] ({case}) {expected:<80} {'FAIL' if bad else 'ok'}")
        for line in bad:
            print(f"        {line[:400]}")
    return failures


def main() -> None:
    import mt_io.uoa  # noqa: F401  (mt-io resets loguru's handlers when first imported: before any sink)
    import mt_io.uoa.pr624  # noqa: F401
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print(f"  mt_workbench.ingest: {ingest.__file__}")
    print(f"  mt_workbench.instruments: {instruments.__file__}")
    root = Path(tempfile.mkdtemp(dir=scratch_dir("edl_null_stamp_unit")))
    failures = run_cases(root, "fixed")
    assert not any(failures.values()), {k: v for k, v in failures.items() if v}

    # the mutation: the plan and the span before issue 75; (a), (b), (c) fail by mt-io's refusal, (d), (e) pass
    plan, span = ingest._edl_plan, instruments.span
    ingest._edl_plan, instruments.span = _old_plan, _old_span  # _group_contiguous looks the plan up when called
    try:
        tripped = run_cases(root, "old")
    finally:
        ingest._edl_plan, instruments.span = plan, span
    failed = {case for case, bad in tripped.items() if bad}
    assert failed == OLD_FAILS, f"the old plan and span failed {sorted(failed)}, expected {sorted(OLD_FAILS)}"
    refused = {case for case in failed if any(STALE in line and "ValueError" in line for line in tripped[case])}
    assert refused == OLD_FAILS, (f"the old plan and span failed {sorted(failed)}, by mt-io's refusal only "
                                  f"{sorted(refused)}")
    print(f"  mutation (old plan and span): {', '.join(sorted(failed))} fail by mt-io's \"{STALE}\" and "
          f"{', '.join(sorted(set(CASES) - failed))} pass, as required")
    shutil.rmtree(root)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    main()
    print("\nPASS  edl_null_stamp_unit")
