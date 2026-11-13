# -*- coding: utf-8 -*-
"""
Unit test for the declared logger clock offset of mt_workbench.ingest (`clock_offset_s`)

A LEMI-423 site is written as four synthetic B423 files of 4 s at 1000 Hz,
the first three back to back and the fourth 18 s after the third, so the
ingest makes two runs (12 s from three files, then 4 s), each channel a
distinct noisy series. It is ingested with a synthetic coil table and
`h_scale: -1000` four times: with no `clock_offset_s` key, with 0.0, with
-1.0 (a logger that stamps its samples 1 s late) and with 0.0125. The
archives are read back with h5py and mth5 and compared with the archive
without the key. A filtered variant is built from the -1.0 archive, and
the refusals are checked on `Survey.site` and `ingest_site`.

Usage:
    python tests/ingest_clock_offset_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - at -1.0 or 0.0125, for either run and any channel, the time axis mth5
    reads back is not the unshifted archive's plus exactly the offset (in
    nanoseconds) at every sample, the run's, each channel's or the
    station's start or end is not moved by exactly the offset, the channel
    summary's start and end are not, or any other dataset (samples,
    filters, standards) differs from the unshifted archive's;
  - a run comment, a channel comment or the station's
    ``provenance.comments`` of a shifted archive does not carry the line
    "clock_offset_s <offset>: ...", `archive_clock_offset` does not read the
    offset back, or the ingest log does not say each run's stamps were
    shifted;
  - the 0.0 archive differs from the archive without the key in any
    dataset's bytes (a summary table's object references, which point
    into their own file, left out) or any attribute other than the file's
    access time, or the archive without the key records an offset;
  - the variant built from the -1.0 archive does not keep its time axis,
    its channel comments and its station record;
  - `Survey.site` accepts a NaN, an infinite, a 60.5 s or a -61 s offset,
    a string, a boolean, a non-zero offset in `defaults:`, or one on a
    derived or an observatory site, or refuses 60 s, -60 s or an integer
    -1; or `ingest_site` with a NaN offset writes a file.

The mutations: with the offset's sign reversed, and with the shift
skipped while the record is still written, the time-axis checks must fail,
which shows they can; the archive comparison must tell the -1.0 archive
from the unshifted one, which shows the no-op check can fail.
"""

from __future__ import annotations

import dataclasses
import math
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import archive_clock_offset, build_variant, ingest_site  # noqa: E402
from mt_workbench.survey import MAX_CLOCK_OFFSET_S, Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_swap_h_unit import all_datasets, lemi_survey, same  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRATCH = scratch_dir("ingest_clock_offset_unit")
EPOCH = 1624510579
STARTS = (EPOCH, EPOCH + 4, EPOCH + 8, EPOCH + 30)  # three files back to back, then a gap: two runs
RUNS = ("sr1000_0001", "sr1000_0002")
COMPS = ("ex", "ey", "hx", "hy")
NOTCH = [{"notch": {"f0": 50.0, "harmonics": 3, "q": 30.0, "passes": 1}}]
# attributes that carry the wall-clock time of the write, the only ones two builds may differ in
WRITE_TIME_ATTRS = {"file.access.time"}


def write_site(root: Path) -> None:
    """Write the four B423 files of site S01 under `root`/raw."""
    shutil.rmtree(root, ignore_errors=True)
    for k, start in enumerate(STARTS):
        _write_b423(root / "raw" / "S01" / f"{start}.B423", epoch=start, n=4000, seed=11 + k,
                    levels={"Ex": (2.0e7, 2.0e6), "Ey": (-1.5e7, 1.0e6), "Bx": (4.3e7, 2.0e6),
                            "By": (-3.1e7, 1.0e6)})


def read_times(path: Path) -> dict:
    """Read an archive's station period and, per run, its period, comment and each channel's axis."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station("S01", survey="t")
        md = station.metadata
        out = {"station": (str(md.time_period.start), str(md.time_period.end)),
               "provenance": str(md.provenance.comments.value or ""), "runs": {}}
        for run_id in RUNS:
            run = station.get_run(run_id)
            row = {"period": (str(run.metadata.time_period.start), str(run.metadata.time_period.end)),
                   "comment": str(run.metadata.comments.value or "")}
            for comp in COMPS:
                ch = run.get_channel(comp)
                comment = getattr(ch.metadata.comments, "value", ch.metadata.comments)
                row[comp] = dict(
                    time=ch.to_channel_ts().data_array.coords["time"].values.astype("datetime64[ns]"),
                    period=(str(ch.metadata.time_period.start), str(ch.metadata.time_period.end)),
                    comment=str(comment or ""))
            out["runs"][run_id] = row
    finally:
        m.close_mth5()
    return out


def ns(text: str) -> np.datetime64:
    """Return an ISO time as numpy nanoseconds (UTC)."""
    import pandas as pd

    return np.datetime64(pd.Timestamp(text).tz_convert("UTC").tz_localize(None), "ns")


def time_problems(plain: Path, shifted: Path, offset: float) -> list[str]:
    """Return how `shifted`'s time axes and periods differ from `plain`'s plus `offset`; empty when right."""
    step = np.timedelta64(int(round(offset * 1e9)), "ns")
    a, b = read_times(plain), read_times(shifted)
    problems = []
    for edge, x, y in zip(("start", "end"), a["station"], b["station"]):
        if ns(y) - ns(x) != step:
            problems.append(f"station {edge} {x} -> {y}")
    for run_id in RUNS:
        ra, rb = a["runs"][run_id], b["runs"][run_id]
        for edge, x, y in zip(("start", "end"), ra["period"], rb["period"]):
            if ns(y) - ns(x) != step:
                problems.append(f"{run_id} {edge} {x} -> {y}")
        for comp in COMPS:
            ta, tb = ra[comp]["time"], rb[comp]["time"]
            if ta.size != tb.size or not np.all(tb - ta == step):
                problems.append(f"{run_id} {comp} time axis: {ta[0]} -> {tb[0]} ({ta.size} vs {tb.size} samples)")
            for edge, x, y in zip(("start", "end"), ra[comp]["period"], rb[comp]["period"]):
                if ns(y) - ns(x) != step:
                    problems.append(f"{run_id} {comp} {edge} {x} -> {y}")
    return problems


def summary_problems(plain: Path, shifted: Path, offset: float) -> list[str]:
    """Return how the datasets differ beyond the channel summary's start and end moving by `offset`."""
    step = np.timedelta64(int(round(offset * 1e9)), "ns")
    a, b = all_datasets(plain), all_datasets(shifted)
    problems = [f"datasets only in one: {sorted(set(a) ^ set(b))}"] if sorted(a) != sorted(b) else []
    for name in sorted(set(a) & set(b)):
        if name != "Experiment/channel_summary":
            if not same(a[name], b[name]):
                problems.append(f"{name} differs")
            continue
        for field in a[name]:
            x, y = a[name][field], b[name][field]
            if field in ("start", "end"):
                moved = [ns(v.decode() if isinstance(v, bytes) else str(v)) for v in y]
                were = [ns(v.decode() if isinstance(v, bytes) else str(v)) for v in x]
                if any(q - p != step for p, q in zip(were, moved)):
                    problems.append(f"channel_summary {field} not moved by {offset}")
            elif not np.array_equal(x, y):
                problems.append(f"channel_summary {field} differs")
    return problems


def file_differences(a_path: Path, b_path: Path) -> list[str]:
    """Return every dataset whose bytes differ and every attribute that differs, write times left out."""
    out = []
    with h5py.File(a_path, "r") as a, h5py.File(b_path, "r") as b:
        names_a, names_b = [], []
        a.visit(names_a.append)
        b.visit(names_b.append)
        if sorted(names_a) != sorted(names_b):
            out.append(f"objects only in one: {sorted(set(names_a) ^ set(names_b))}")
        for name in [""] + sorted(set(names_a) & set(names_b)):
            obj_a, obj_b = (a[name], b[name]) if name else (a, b)
            if isinstance(obj_a, h5py.Dataset):
                x, y = obj_a[()], obj_b[()]
                # a summary table's object references point into their own file
                fields = [f for f in (x.dtype.names or ()) if not f.endswith("reference")]
                if obj_a.dtype != obj_b.dtype:
                    out.append(f"{name}: dtype {obj_a.dtype} vs {obj_b.dtype}")
                elif fields:
                    out += [f"{name} {f}: bytes differ" for f in fields if x[f].tobytes() != y[f].tobytes()]
                elif x.tobytes() != y.tobytes():
                    out.append(f"{name}: bytes differ")
            keys = (set(obj_a.attrs) | set(obj_b.attrs)) - WRITE_TIME_ATTRS
            for key in sorted(keys):
                x, y = obj_a.attrs.get(key), obj_b.attrs.get(key)
                if isinstance(x, h5py.Reference) or isinstance(y, h5py.Reference):
                    continue  # an object reference points into its own file
                if not np.array_equal(np.asarray(x), np.asarray(y)):
                    out.append(f"{name or '/'} attr {key}: {x!r} vs {y!r}")
    return out


def build(root: Path, tag: str, own: dict, filters=None) -> Path:
    """Ingest S01 with its own entry `own` into <root>/work/<tag>.h5."""
    return ingest_site(lemi_survey(root, own, filters), "S01", out_path=root / "work" / f"{tag}.h5",
                       overwrite=True)


def test_shift_and_record() -> None:
    """Check the time axes, periods and other datasets of the shifted archives, and the record."""
    from loguru import logger

    root = SCRATCH / "lemi423"
    write_site(root)
    plain = build(root, "plain", {})
    assert archive_clock_offset(plain, "S01") == 0.0
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO", filter=lambda r: "clock_offset_s" in r["message"])
    try:
        shifted = {offset: build(root, f"shift{k}", {"clock_offset_s": offset})
                   for k, offset in enumerate((-1.0, 0.0125))}
    finally:
        logger.remove(sink)
    for offset, path in shifted.items():
        problems = time_problems(plain, path, offset)
        assert not problems, (offset, problems)
        problems = summary_problems(plain, path, offset)
        assert not problems, (offset, problems)
        got = read_times(path)
        want = f"clock_offset_s: {offset!r} s added"
        assert want in got["provenance"], got["provenance"]
        for run_id in RUNS:
            assert want in got["runs"][run_id]["comment"], got["runs"][run_id]["comment"]
            for comp in COMPS:
                assert want in got["runs"][run_id][comp]["comment"], (run_id, comp, got["runs"][run_id][comp])
        assert archive_clock_offset(path, "S01") == offset, archive_clock_offset(path, "S01")
        logged = [line for line in lines if f"clock_offset_s {offset!r} -> run time stamps shifted" in line]
        assert len(logged) == len(RUNS), lines
    late = read_times(shifted[-1.0])
    first = late["runs"][RUNS[0]]["hx"]["time"]
    print(f"  -1.0 and 0.0125: both runs ({first.size} and {late['runs'][RUNS[1]]['hx']['time'].size} "
          f"samples), every channel's axis, the run, channel and station periods and the channel summary "
          f"moved by exactly the offset, every other dataset identical; -1.0 starts at {first[0]}; run "
          f"comment {late['runs'][RUNS[0]]['comment'].split('; ')[0]!r}; one log line per run")

    # the mutations: the sign reversed, and the shift skipped with the record still written
    real = ingest._shift_clock

    def reversed_sign(run, site):
        return real(run, dataclasses.replace(site, clock_offset_s=-site.clock_offset_s))

    def record_only(run, site):
        return real(run, dataclasses.replace(site, clock_offset_s=0.0)) or "clock_offset_s (not applied)"

    for name, mutant in (("sign reversed", reversed_sign), ("shift skipped", record_only)):
        ingest._shift_clock = mutant
        try:
            path = build(root, "mutant", {"clock_offset_s": -1.0})
        finally:
            ingest._shift_clock = real
        caught = time_problems(plain, path, -1.0)
        checks = 2 + len(RUNS) * (2 + 3 * len(COMPS))  # every edge and axis time_problems looks at
        assert len(caught) == checks, (name, len(caught), checks, caught)
        print(f"  mutation ({name}): {len(caught)} problems, e.g. {caught[0]!r}")


def test_zero_is_a_no_op() -> None:
    """Check that clock_offset_s 0.0 writes the archive the missing key writes, and the check can tell."""
    root = SCRATCH / "lemi423"
    if not (root / "work" / "plain.h5").exists():
        write_site(root)
        build(root, "plain", {})
    plain, late = root / "work" / "plain.h5", root / "work" / "shift0.h5"
    zero = build(root, "zero", {"clock_offset_s": 0.0})
    differ = file_differences(plain, zero)
    assert not differ, differ
    assert archive_clock_offset(zero, "S01") == 0.0
    assert "clock_offset_s" not in read_times(zero)["runs"][RUNS[0]]["comment"]
    if not late.exists():
        build(root, "shift0", {"clock_offset_s": -1.0})
    caught = file_differences(plain, late)
    assert caught, "the comparison does not tell the -1.0 archive from the unshifted one"
    with h5py.File(plain, "r") as f:
        names: list[str] = []
        f.visit(names.append)
        n_objects = len(names) + 1
    print(f"  0.0: every dataset's bytes and every attribute of {n_objects} objects as without the key "
          f"(file.access.time and the summary tables' object references left out); the same comparison finds {len(caught)} differences at -1.0, "
          f"e.g. {caught[0][:90]!r}")


def test_variant_keeps_the_shift() -> None:
    """Check that a filtered variant built from a shifted archive keeps its axis and its record."""
    root = SCRATCH / "variant"
    write_site(root)
    survey = lemi_survey(root, {"clock_offset_s": -1.0}, NOTCH)
    raw = ingest_site(survey, "S01", overwrite=True)
    variant = build_variant(survey, "S01")
    a, b = read_times(raw), read_times(variant)
    for run_id in RUNS:
        for comp in COMPS:
            assert np.array_equal(a["runs"][run_id][comp]["time"], b["runs"][run_id][comp]["time"]), (run_id, comp)
            assert "clock_offset_s: -1.0 s added" in b["runs"][run_id][comp]["comment"], b["runs"][run_id][comp]["comment"]
    assert archive_clock_offset(variant, "S01") == -1.0
    print(f"  variant {variant.name}: the raw archive's shifted axes, the channel comments and the station "
          f"record kept; archive_clock_offset -1.0")


def test_refusals() -> None:
    """Check the values and sites `Survey.site` refuses, and that a refused ingest writes nothing."""
    root = SCRATCH / "lemi423"
    if not (root / "raw" / "S01").exists():
        write_site(root)

    def config(own=None, defaults=None, extra=None) -> Survey:
        survey = lemi_survey(root, own or {})
        survey._defaults.update(defaults or {})
        survey._sites.update(extra or {})
        return survey

    for value in (math.nan, math.inf, -math.inf, MAX_CLOCK_OFFSET_S + 0.5, -61, "-1.0 s", True, None):
        try:
            config({"clock_offset_s": value}).site("S01")
        except ValueError as exc:
            assert "clock_offset_s" in str(exc), exc
            continue
        raise AssertionError(f"clock_offset_s {value!r} accepted")
    for value, want in ((60.0, 60.0), (-60.0, -60.0), (-1, -1.0), (0, 0.0)):
        got = config({"clock_offset_s": value}).site("S01").clock_offset_s
        assert got == want and isinstance(got, float), (value, got)
    refused = {}
    cases = {
        "defaults": config(defaults={"clock_offset_s": -1.0}),
        "derived": config(extra={"S01L": {"derived_from": "S01", "sample_rate": 1.0, "clock_offset_s": -1.0}}),
        "observatory": config(extra={"OBS": {"instrument": "intermagnet", "clock_offset_s": -1.0}}),
    }
    for case, survey in cases.items():
        site = {"defaults": "S01", "derived": "S01L", "observatory": "OBS"}[case]
        try:
            survey.site(site)
        except ValueError as exc:
            refused[case] = str(exc)
            continue
        raise AssertionError(f"clock_offset_s accepted on the {case} case")
    assert "derived from S01" in refused["derived"] and "observatory" in refused["observatory"], refused
    assert config(extra={"S01L": {"derived_from": "S01", "sample_rate": 1.0}}).site("S01L").clock_offset_s == 0.0
    out = root / "work" / "refused.h5"
    out.unlink(missing_ok=True)
    try:
        ingest_site(config({"clock_offset_s": math.nan}), "S01", out_path=out, overwrite=True)
    except ValueError:
        assert not out.exists(), "a refused ingest wrote a file"
    else:
        raise AssertionError("ingest_site accepted clock_offset_s NaN")
    print(f"  refused: NaN, +/-inf, 60.5, -61, a string, a boolean, None; in defaults:, on a derived and an "
          f"observatory site (e.g. {refused['derived'][:80]!r}); accepted: 60, -60, -1 as -1.0; a NaN ingest "
          f"writes no file")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("**This test fails if**", 1)[1].split("\n\nThe mutations")[0])
    print()
    tests = [test_shift_and_record, test_zero_is_a_no_op, test_variant_keeps_the_shift, test_refusals]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  ingest_clock_offset_unit ({len(tests)} tests)")
