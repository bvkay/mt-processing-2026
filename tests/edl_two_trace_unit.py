# -*- coding: utf-8 -*-
"""
Unit test for an EDL first file holding the deployment test run before the record (workbench issue 76)

At deployment a PR6-24 is sometimes run for a little while, stopped and run
again, so the first file of a deployment can hold two traces: the test run
under the logger's previous station and location codes, then the record
under the new ones (AusLAMP Victoria's `VIC078b_140822050000`: `.vic01.Ol.bx`
1,800 samples from 05:00:00, then `.vic07.Le.bx` 34,200 from 05:03:00). The
record starts at the last trace and the test run is left out (upstream
525). Before the fix mt-io read the trace that
sorts first by id and counted both, and `_edl_plan` placed the hour from its
stamp, so every later file of the run sat 57 min early.

A site is written with that shape at 10 Hz: the first stamp's five channel
files are two-trace miniSEED (obspy), the next two stamps normal ASCII hours.
Each channel's record counts up through the three files, so the archive's
run must hold exactly the record, in order, from 05:03:00.

Usage:
    python tests/edl_two_trace_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - T1: `ingest_site` does not build one run starting 05:03:00.0 whose
    every channel equals the record as written (34,200 + 2 x 36,000
    samples) and whose last sample is the last file's (07:59:59.9); the
    grouping does not keep the three stamps in one run; `span` does not
    give 05:03:00 to 08:00:00 over 3 stamps; or the run comment's
    "deployment_test_run:" line does not name the test trace left out
    (its id and its 1,800 samples) and the record's id;
  - T2 (the guard, `_check_edl_read`): a read returning 600 samples fewer
    than planned (at the end, or at the start, the start then 60 s late) is
    written instead of refused with a ValueError naming the site, the run's
    first file, the planned 106200 and the read count;
  - T3: with mt-io's pre-525 behaviour (`read_edl_miniseed` keeping the
    trace that sorts first, `count_samples` summing both, no
    `count_samples_and_start`) the ingest writes a run instead of refusing
    it with the guard's ValueError (planned 108000, read 73800).

Mutation (T4, run when MT_WORKBENCH_PRISTINE_PYTHONPATH names the src
folders of an mt-io and an mt-workbench from before this change): the same
site ingested by that pair in a fresh process must give the run starting
05:00:00 with the 06:00 file's samples at sample 1,800 (05:03:00, 57 min
early) and the run ending 07:02:59.9, so the checks of T1 can fail.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import _group_contiguous, ingest_site  # noqa: E402
from mt_workbench.instruments import record_files, span  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("edl_two_trace_unit")
SITE = "TWO"
FS = 10.0
CHANNELS = ("BX", "BY", "BZ", "EX", "EY")
COMPS = ("hx", "hy", "hz", "ex", "ey")
T0 = pd.Timestamp("2014-08-22T05:00:00", tz="UTC")
TEST_N, RECORD_N, HOUR_N = 1800, 34200, 36000
TOTAL = RECORD_N + 2 * HOUR_N  # the record: the two-trace file's last trace and two ASCII hours


def record_values(c: int) -> np.ndarray:
    """Return channel c's record, counting up through its three files."""
    return (c + 1) * 1_000_000 + np.arange(TOTAL, dtype=float)


def write_site(root: Path) -> Path:
    """Write the site under `root`/raw: the two-trace miniSEED stamp at 05:00, then ASCII hours at 06:00 and 07:00."""
    from obspy import Stream, Trace, UTCDateTime

    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "234").mkdir(parents=True)
    (site / "config").mkdir()
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    for c, channel in enumerate(CHANNELS):
        def trace(station, location, start, values):
            t = Trace(values.astype(np.int32))
            t.stats.network, t.stats.station, t.stats.location, t.stats.channel = "", station, location, channel.lower()
            t.stats.starttime, t.stats.sampling_rate = UTCDateTime(start.isoformat()), FS
            return t

        test = -(c + 1) * 100_000 - np.arange(TEST_N)
        record = record_values(c)
        Stream([trace("vic01", "Ol", T0, test),
                trace("vic07", "Le", T0 + pd.Timedelta(seconds=TEST_N / FS), record[:RECORD_N])]).write(
            str(site / "234" / f"{SITE}_{T0:%y%m%d%H%M%S}.{channel}"), format="MSEED", encoding="STEIM2", reclen=512)
        for k in (1, 2):
            when = T0 + pd.Timedelta(hours=k)
            part = record[RECORD_N + (k - 1) * HOUR_N:RECORD_N + k * HOUR_N]
            np.savetxt(site / "234" / f"{SITE}_{when:%y%m%d%H%M%S}.{channel}", part, fmt="%d")
    return site


def survey(root: Path) -> Survey:
    """Build the one-site EDL survey."""
    return Survey({"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0,
                                "channels": ["ex", "ey", "hx", "hy", "hz"]},
                   "sites": {SITE: {}}}, root)


def read_runs(path: Path) -> list[dict]:
    """Return each run's start, end, channels and comment, in time order."""
    runs = []
    with h5py.File(path, "r") as f:
        station = f[f"Experiment/Surveys/t/Stations/{SITE}"]
        for name, g in station.items():
            if g.attrs.get("mth5_type") != "Run":
                continue
            comment = g.attrs.get("comments")
            runs.append(dict(id=name, start=pd.Timestamp(g.attrs["time_period.start"]),
                             end=pd.Timestamp(g.attrs["time_period.end"]),
                             comment=comment.decode() if isinstance(comment, bytes) else str(comment or ""),
                             **{c: g[c][()] for c in COMPS}))
    return sorted(runs, key=lambda r: r["start"])


def test_one_run_from_the_record() -> None:
    """T1."""
    root = SCRATCH / "t1"
    site = write_site(root)
    files = record_files(site, "edl")
    groups = _group_contiguous(files, None, "edl", rate=FS)
    got = [sorted({p.stem.split("_")[1] for p in g}) for g in groups]
    assert got == [["140822050000", "140822060000", "140822070000"]], got
    start, end, n = span(site, "edl", files)
    assert (start, end, n) == (T0 + pd.Timedelta(minutes=3), T0 + pd.Timedelta(hours=3), 3), (start, end, n)
    path = ingest_site(survey(root), SITE, out_path=root / "work" / "two.h5", overwrite=True)
    runs = read_runs(path)
    assert len(runs) == 1, [(r["id"], r["start"]) for r in runs]
    run = runs[0]
    assert run["start"] == T0 + pd.Timedelta(minutes=3), run["start"]
    assert run["end"] == T0 + pd.Timedelta(hours=3) - pd.Timedelta(seconds=1 / FS), run["end"]
    for c, comp in enumerate(COMPS):
        assert np.array_equal(run[comp], record_values(c)), (comp, run[comp].size, run[comp][:3])
    note = [p.strip() for p in run["comment"].split(";") if p.strip().startswith("deployment_test_run:")]
    assert len(note) == 1, run["comment"]
    for text in (f"{SITE}_140822050000.BX", ".vic01.Ol.bx 1800 samples 2014-08-22T050000.0 to 2014-08-22T050259.9",
                 "record .vic07.Le.bx 2014-08-22T050300.0"):
        assert text in note[0], (text, note[0])
    assert note[0].count(":") == 1 and ";" not in note[0], note[0]  # upstream 48: one key, no second colon
    print(f"  T1 one run {run['id']} {run['start']:%H:%M:%S.%f} .. {run['end']:%H:%M:%S.%f}, {run['hx'].size} samples "
          f"per channel == the record as written (5 channels); span {start:%H:%M:%S} .. {end:%H:%M:%S} over {n} "
          f"stamps; comment {note[0][:110]}...")


def _cut_tail(run, k: int):
    """Return a run without its last k samples (a reader returning fewer samples than planned)."""
    from mth5.timeseries import RunTS

    dataset = run.dataset.isel(time=slice(0, -k)).copy()
    piece = RunTS()
    piece.station_metadata = run.station_metadata.copy()
    piece.run_metadata = run.run_metadata.copy()
    piece.filters = dict(run.filters)
    piece.dataset = dataset
    return piece


def test_guard() -> None:
    """T2: a read returning fewer samples than planned is refused."""
    root = SCRATCH / "t2"
    write_site(root)
    real = ingest.read_run
    for what, short in (("the last 600 samples missing", lambda run: _cut_tail(run, 600)),
                        ("the first 600 samples missing", lambda run: ingest._trim_run_start(run, 600, "test"))):
        ingest.read_run = lambda *a, short=short, **k: short(real(*a, **k))
        try:
            ingest_site(survey(root), SITE, out_path=root / "work" / "guard.h5", overwrite=True)
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError(f"T2 ({what}): the run was written")
        finally:
            ingest.read_run = real
        for text in (f"{SITE}:", f"{SITE}_140822050000.", f"planned as {TOTAL} samples from 2014-08-22T05:03:00",
                     f"hx {TOTAL - 600}", "refused"):
            assert text in message, (what, text, message)
        print(f"  T2 ({what}) refused: {message[:200]}...")


def _pre525(module):
    """Return mt-io's pre-525 read_edl_miniseed and count_samples (the trace that sorts first; the sum)."""
    from datetime import timezone

    def read_edl_miniseed(fn):
        from obspy import read as obspy_read
        stream = obspy_read(Path(fn).as_posix(), format="MSEED")
        stream.merge(method=0)
        trace = stream[0]
        return (trace.data.astype(float), trace.stats.starttime.datetime.replace(tzinfo=timezone.utc),
                float(trace.stats.sampling_rate))

    real_count = module.count_samples

    def count_samples(fn):
        if module.is_miniseed(fn):
            from obspy import read as obspy_read
            return int(sum(t.stats.npts for t in obspy_read(Path(fn).as_posix(), headonly=True)))
        return real_count(fn)

    return read_edl_miniseed, count_samples


def test_old_mtio_refused() -> None:
    """T3: the new workbench over mt-io's pre-525 functions refuses the run."""
    import mt_io.uoa.pr624 as pr624

    root = SCRATCH / "t3"
    write_site(root)
    saved = {name: getattr(pr624, name) for name in ("read_edl_miniseed", "count_samples", "count_samples_and_start")
             if hasattr(pr624, name)}
    pr624.read_edl_miniseed, pr624.count_samples = _pre525(pr624)
    if hasattr(pr624, "count_samples_and_start"):
        del pr624.count_samples_and_start
    try:
        ingest_site(survey(root), SITE, out_path=root / "work" / "old.h5", overwrite=True)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("T3: the run was written with mt-io's pre-525 functions")
    finally:
        for name, value in saved.items():
            setattr(pr624, name, value)
    want = 3 * HOUR_N
    read = TEST_N + 2 * HOUR_N
    for text in (f"{SITE}_140822050000.", f"planned as {want} samples from 2014-08-22T05:00:00", f"hx {read}"):
        assert text in message, (text, message)
    print(f"  T3 mt-io's pre-525 functions: refused, {message[:160]}...")


MUTANT = r"""
import json, sys
from pathlib import Path
import h5py, pandas as pd
import mt_io.uoa.pr624 as pr624, mt_workbench.ingest as ingest
from mt_workbench.ingest import ingest_site
from mt_workbench.survey import Survey
root = Path(sys.argv[1])
s = Survey({"name": "t", "instrument": "edl", "sample_rate": 10.0, "data_root": str(root / "raw"),
            "workspace": str(root / "work"), "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0,
            "channels": ["ex", "ey", "hx", "hy", "hz"]}, "sites": {"TWO": {}}}, root)
path = ingest_site(s, "TWO", out_path=root / "work" / "pristine.h5", overwrite=True)
with h5py.File(path, "r") as f:
    st = f["Experiment/Surveys/t/Stations/TWO"]
    runs = [(n, g.attrs["time_period.start"], g.attrs["time_period.end"], g["hx"][()].tolist())
            for n, g in st.items() if g.attrs.get("mth5_type") == "Run"]
print(json.dumps({"pr624": pr624.__file__, "ingest": ingest.__file__, "runs": runs}))
"""


def test_mutation_pristine_pair() -> None:
    """T4: the pre-fix pair writes the run from 05:00:00 with the 06:00 file at sample 1,800."""
    pristine = os.environ.get("MT_WORKBENCH_PRISTINE_PYTHONPATH")
    if not pristine:
        print("  T4 SKIPPED: MT_WORKBENCH_PRISTINE_PYTHONPATH not set (the pre-fix mt-io and mt-workbench src)")
        return
    root = SCRATCH / "t4"
    write_site(root)
    env = dict(os.environ, PYTHONPATH=pristine)
    out = subprocess.run([sys.executable, "-c", MUTANT, str(root)], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    for key in ("pr624", "ingest"):
        assert not Path(got[key]).resolve().is_relative_to(REPO.resolve()), got[key]
    assert len(got["runs"]) == 1, [r[:3] for r in got["runs"]]
    _name, start, end, hx = got["runs"][0]
    hx = np.asarray(hx)
    six = record_values(0)[RECORD_N:RECORD_N + HOUR_N]  # the 06:00 file's hx
    assert pd.Timestamp(start) == T0, start
    assert np.array_equal(hx[TEST_N:TEST_N + HOUR_N], six), "the 06:00 file is not at sample 1,800"
    assert pd.Timestamp(end) == T0 + pd.Timedelta(seconds=(TEST_N + 2 * HOUR_N - 1) / FS), end
    print(f"  T4 mutation (pre-fix pair, {got['pr624']}, {got['ingest']}): one run from {pd.Timestamp(start):%H:%M:%S} "
          f"to {pd.Timestamp(end):%H:%M:%S.%f}, {hx.size} samples; the 06:00 file's hx at sample {TEST_N} "
          f"(05:03:00, 57 min early); T1's start, length and values all fail on it")


if __name__ == "__main__":
    from loguru import logger

    import mt_io.uoa  # noqa: F401  (mt-io drops loguru's handlers on its first import)

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    tests = [test_one_run_from_the_record, test_guard, test_old_mtio_refused, test_mutation_pristine_pair]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  edl_two_trace_unit ({len(tests)} tests)")
