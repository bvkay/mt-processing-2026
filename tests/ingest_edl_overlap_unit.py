# -*- coding: utf-8 -*-
"""
Unit test for EDL restart files that overlap the file before them (`mt_workbench.ingest._edl_runs_by_samples`)

A PR6-24 restarted during a recording writes a new file whose stamp falls
before the end of the samples of the file it interrupted: TAS105's
`Tas105_160124050800` holds 620 samples at 10 Hz (to 05:09:01.9) and
`Tas105_160124050845` starts at 05:08:45, 17 s inside it (Tasmania AusLAMP
2016, upstream issue 318). Read as two runs, the two share 17 s and the
grid loaders write both onto the same samples. An EDL site is written with
the same shape at 10 Hz: a 620-sample file at 00:00:00, a restart file of
3,000 samples stamped 00:00:45 (17 s inside it) and a file of 3,000 samples
stamped where the restart file ends; then a file wholly inside the one
before it; and a stamp whose five files are empty (TAS112's
`TAS112_160218220000`, whose reading stopped its ingest).

Usage:
    python tests/ingest_edl_overlap_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - O1: the archive's runs overlap (a run starts before the run before it
    ends), the kept sample count differs from the union of the files'
    spans, or the run after the restart does not start exactly where the
    620-sample file ends (00:01:02.0);
  - O2: any kept sample differs from the file sample of the same instant,
    the earlier file's (its 170 overlapping samples are kept and the
    restart file's first 170 left out), or the restart file's later
    samples and the next file's are not contiguous in one run;
  - O3: the restart run's comment does not say "overlap: the first 170
    samples (17.0 s) of" the restart file "left out", naming the earlier
    file, whose samples are kept;
  - O4: a file wholly inside the file before it is not left out with a
    warning (its samples are the earlier file's instants), or a stamp
    whose files hold no sample stops the ingest instead of being left out;
  - O5 (a set-up at another rate, TAS151's 100 s/s of 24 Oct 2016 03:04:30
    to 03:31:47 as its recorder.msg logs it): a second site whose
    recorder.msg puts its data channels at 100 s/s over a stretch of five
    files of ten times the samples their stamps allow is ingested with any
    of those five files, or without its 10 Hz files before and after the
    stretch, or with a run that overlaps another; or a third site whose
    recorder.msg ends on a 50 s/s set-up while its files are 10 Hz
    throughout (TAS131's log) loses any file.

Mutations: with the trim left out (each restart run read whole), O1 must
find the runs overlapping; with the recorder.msg guard left out, O5 must
find the 100 Hz files kept. Each shows its check can fail.
"""

from __future__ import annotations

import shutil
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
from mt_workbench.instruments import record_files  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("ingest_edl_overlap_unit")
SITE = "OVL"
FS = 10.0
T0 = pd.Timestamp("2016-01-24T00:00:00", tz="UTC")
# (stamp offset s, samples): the 620-sample file, the restart 17 s inside it, the next file where the restart
# ends; a gap; a file, one wholly inside it, the next where the first ends; an empty stamp after a gap
FILES = ((0, 620), (45, 3000), (345, 3000), (1000, 3000), (1100, 500), (1300, 3000), (2000, 0))
EMPTY = 2000


def stamp(offset: float) -> str:
    """Return the file stamp yymmddhhmmss of `T0` + offset s."""
    return (T0 + pd.Timedelta(seconds=offset)).strftime("%y%m%d%H%M%S")


def write_site(root: Path) -> dict[str, dict[int, float]]:
    """Write the site under `root`/raw; return each channel's samples by instant (ns): the earliest file's win."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    truth: dict[str, dict[int, float]] = {}
    for k, (offset, n) in enumerate(FILES):
        for c, suffix in enumerate(("BX", "BY", "BZ", "EX", "EY")):
            values = (c + 1) * 1_000_000 + k * 10_000 + np.arange(n)
            path = site / f"{SITE}_{stamp(offset)}.{suffix}"
            if n:
                np.savetxt(path, values, fmt="%d")
            else:
                path.write_bytes(b"")
            t = (T0 + pd.Timedelta(seconds=offset)).value + np.round(np.arange(n) * 1e9 / FS).astype("int64")
            for ti, v in zip(t, values):
                truth.setdefault(suffix, {}).setdefault(int(ti), float(v))  # the earlier file's sample wins
    return truth


def survey(root: Path) -> Survey:
    """Build the one-site EDL survey."""
    return Survey({"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0,
                                "channels": ["ex", "ey", "hx", "hy", "hz"]},
                   "sites": {SITE: {}}}, root)


def read_runs(path: Path) -> list[dict]:
    """Return each run's start (ns), samples per channel and comment, in time order."""
    runs = []
    with h5py.File(path, "r") as f:
        station = f[f"Experiment/Surveys/t/Stations/{SITE}"]
        for name, g in station.items():
            if g.attrs.get("mth5_type") != "Run":
                continue
            comment = g.attrs.get("comments")
            runs.append(dict(id=name, start=pd.Timestamp(g.attrs["time_period.start"]).value,
                             comment=comment.decode() if isinstance(comment, bytes) else str(comment or ""),
                             **{c: g[c][()] for c in ("hx", "ex")}))
    return sorted(runs, key=lambda r: r["start"])


def overlap_problems(runs: list[dict], truth: dict) -> list[str]:
    """Return what is wrong with the archive's runs against the files; empty when right."""
    problems = []
    step = int(1e9 / FS)
    for a, b in zip(runs, runs[1:]):
        end = a["start"] + a["hx"].size * step
        if b["start"] < end:
            problems.append(f"run {b['id']} starts {(end - b['start']) / 1e9:.1f} s before {a['id']} ends")
    union = len(truth["BX"])
    kept = sum(r["hx"].size for r in runs)
    if kept != union:
        problems.append(f"{kept} samples kept, the union of the files is {union}")
    for r in runs:
        t = r["start"] + np.arange(r["hx"].size) * step
        for comp, suffix in (("hx", "BX"), ("ex", "EX")):
            want = np.array([truth[suffix].get(int(x), np.nan) for x in t])
            if not np.array_equal(r[comp], want):
                problems.append(f"{r['id']} {comp} differs from the files' samples of the same instants")
    return problems


def test_overlap() -> None:
    """O1-O4 on the synthetic site, and the mutation."""
    root = SCRATCH / "site"
    truth = write_site(root)
    files = record_files(root / "raw" / SITE, "edl")
    groups = _group_contiguous(files, None, "edl", rate=FS)
    got = [(sorted({p.stem.split("_")[1] for p in g}), getattr(g, "trim", 0)) for g in groups]
    want = [([stamp(0)], 0), ([stamp(45), stamp(345)], 170), ([stamp(1000), stamp(1300)], 0)]
    assert got == want, got
    path = ingest_site(survey(root), SITE, out_path=root / "work" / "ovl.h5", overwrite=True)
    runs = read_runs(path)
    problems = overlap_problems(runs, truth)
    assert not problems, problems
    second = runs[1]
    end_first = T0 + pd.Timedelta(seconds=62.0)
    assert second["start"] == end_first.value, pd.Timestamp(second["start"], tz="UTC")
    note = f"overlap: the first 170 samples (17.0 s) of {SITE}_{stamp(45)} left out"
    assert note in second["comment"] and f"{SITE}_{stamp(0)}" in second["comment"], second["comment"]
    print(f"  O1-O3 runs {[r['id'] for r in runs]}: no overlap, {sum(r['hx'].size for r in runs)} samples == the "
          f"union; run 2 starts {pd.Timestamp(second['start'], tz='UTC'):%H:%M:%S.%f} where the 620-sample file "
          f"ends; every sample the earlier file's; comment {note!r}...")
    print(f"  O4 the file wholly inside ({stamp(1100)}) and the empty stamp ({stamp(EMPTY)}) left out; groups {got}")

    real = ingest._trim_run_start
    ingest._trim_run_start = lambda run, trim, note: run
    try:
        mutant = ingest_site(survey(root), SITE, out_path=root / "work" / "mutant.h5", overwrite=True)
    finally:
        ingest._trim_run_start = real
    caught = overlap_problems(read_runs(mutant), truth)
    assert any("starts" in p for p in caught), caught
    print(f"  mutation (no trim): {caught[0]!r}")


MSG_LINE = "{when} Channel {ch:02d} changing to low  gain {rate}s/s"


def msg_block(when: pd.Timestamp, rates: dict[int, int]) -> list[str]:
    """Return the recorder.msg lines of one digitiser reconfigure at `when`."""
    stamp = when.strftime("%d/%m/%y %H:%M:%S")
    return [MSG_LINE.format(when=stamp, ch=ch, rate=r) for ch, r in rates.items()]


def write_rate_site(root: Path, name: str, setup: bool) -> dict[str, list[int]]:
    """Write a site of 10 Hz files around a 100 s/s stretch (`setup`), or a 10 Hz site whose log ends at 50 s/s.

    Returns:
        dict: ``kept`` and ``left_out``: the stamps (unix s) of each kind.
    """
    site = root / "raw" / name
    shutil.rmtree(site, ignore_errors=True)
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    t0 = pd.Timestamp("2016-10-24T03:00:00", tz="UTC")
    data = {ch: 10 for ch in range(6)}
    lines = msg_block(t0 - pd.Timedelta(minutes=5), {**data, 13: 1})
    files = []
    if setup:
        # 10 Hz 60 s files, then five 100 Hz files stamped 300 s apart (30,000 samples each), then 10 Hz again
        lines += msg_block(t0 + pd.Timedelta(seconds=270), {ch: 100 for ch in range(6)})
        lines += msg_block(t0 + pd.Timedelta(seconds=1830), data)
        files += [(0, 600, True), (60, 600, True), (120, 600, True)]
        files += [(300 + 300 * k, 30000, False) for k in range(5)]
        files += [(1860, 600, True), (1920, 36000, True)]
    else:
        lines += msg_block(t0 + pd.Timedelta(seconds=100), {ch: 50 for ch in range(6)})
        files += [(0, 600, True), (60, 36000, True), (3660, 36000, True)]
    (site / "recorder.msg").write_text("\n".join(lines) + "\n", encoding="utf-8")
    kept, out = [], []
    for k, (offset, n, keep) in enumerate(files):
        when = t0 + pd.Timedelta(seconds=offset)
        for c, suffix in enumerate(("BX", "BY", "BZ", "EX", "EY")):
            np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}", (c + 1) * 1_000_000 + k * 100_000 + np.arange(n),
                       fmt="%d")
        (kept if keep else out).append(int(when.timestamp()))
    return {"kept": kept, "left_out": out}


def group_stamps(groups) -> list[int]:
    """Return the sorted unix stamps of the files of some groups."""
    return sorted({int(pd.to_datetime(Path(p).stem.split("_")[1], format="%y%m%d%H%M%S", utc=True)
                       .timestamp()) for g in groups for p in g})


def test_rate_guard() -> None:
    """O5: a set-up at 100 s/s is left out; a log that is not the deployment's own leaves nothing out."""
    root = SCRATCH / "rates"
    for name, setup in (("RTA", True), ("RTB", False)):
        want = write_rate_site(root, name, setup)
        files = record_files(root / "raw" / name, "edl")
        got = group_stamps(_group_contiguous(files, None, "edl", rate=FS))
        assert got == sorted(want["kept"]), (name, got, want)
        survey_ = Survey({"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
                          "workspace": str(root / "work"),
                          "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0},
                          "sites": {name: {}}}, root)
        path = ingest_site(survey_, name, out_path=root / "work" / f"{name}.h5", overwrite=True)
        with h5py.File(path, "r") as f:
            st = f[f"Experiment/Surveys/t/Stations/{name}"]
            runs = sorted((pd.Timestamp(g.attrs["time_period.start"]).value, g["hx"].shape[0])
                          for g in st.values() if isinstance(g, h5py.Group) and g.attrs.get("mth5_type") == "Run")
        step = int(1e9 / FS)
        assert all(b[0] >= a[0] + a[1] * step for a, b in zip(runs, runs[1:])), (name, runs)
        print(f"  O5 {name}: kept {len(want['kept'])} stamps, left out {len(want['left_out'])} "
              f"({'the 100 s/s stretch' if setup else 'none: the log ends at 50 s/s, the files are 10 Hz'}); "
              f"{len(runs)} runs, none overlapping")
        if setup:
            real = ingest._other_rate_stamps
            ingest._other_rate_stamps = lambda files, stamps, rate: set()
            try:
                mutant = group_stamps(_group_contiguous(files, None, "edl", rate=FS))
            finally:
                ingest._other_rate_stamps = real
            assert mutant != sorted(want["kept"]), mutant
            print(f"  O5 mutation (no recorder.msg guard): {len(set(mutant) & set(want['left_out']))} of the 100 Hz "
                  f"stamps kept")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    test_overlap()
    print("  ok  test_overlap")
    test_rate_guard()
    print("  ok  test_rate_guard")
    print("\nPASS  ingest_edl_overlap_unit (2 tests)")
