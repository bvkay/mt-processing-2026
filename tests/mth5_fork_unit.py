# -*- coding: utf-8 -*-
"""
Unit test for the mtproc forks of mth5 and mt-metadata

Tests the forks (branch `mtproc-fixes`) against stock mth5 0.6.9 and
mt_metadata 1.0.10. The forks are the clones at MTPROC_FORKS/mth5 (import
name `mth5`) and MTPROC_FORKS/mt-metadata (import name `mt_metadata`);
MTPROC_FORKS defaults to `_scratch.DEFAULT_FORKS`. Every check runs in a
fresh subprocess (`--worker`). The fork's run has PYTHONPATH=<mth5
clone>;<mt-metadata clone>[;<mt-io clone>/src], then this process's own
PYTHONPATH and src, ahead of site-packages. The mt-io clone is included
when there is one because check 2 ingests through `mtproc.ingest`, whose
LEMI-423 coil chain comes from the mt-io fork. The installed packages' run
(what this interpreter imports: site-packages, or a PYTHONPATH set before
the test) gets this process's own PYTHONPATH and src alone.

The installed packages run checks 1, 2 and 4 as well, reported for
information. Stock mth5 0.6.9 / mt_metadata 1.0.10 (with stock mt-io) fail
all three, which shows each check can fail, and the installed forks pass
all three, reported as fixed. Without both clones the fork checks are
reported as skipped and the test passes; when the installed packages pass
checks 1, 2 and 4 (the forks installed), the timing comparison is skipped.

Usage:
    python tests/mth5_fork_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. read-only (docs/upstream_issues.md 5): while another process holds each
   archive open read-only, `RunSummary.from_mth5s` and
   `KernelDataset.from_run_summary` over the small archives of
   `tests/crosspower_unit.py` (L: ex ey hx hy in two runs, R: hx hy in one,
   100 Hz) raise under the fork, give other stations than L and R, or change
   either file's modification time (ns) (stock opens read-write, which the
   held read-only open refuses);
2. run ids (issue 9): `mtproc.ingest.ingest_site` over three synthetic
   LEMI-423 files (`tests/new_survey_unit.py`'s S01, survey.yaml written by
   scripts/new_survey.py) logs any WARNING from `mth5.groups.run` under the
   fork, or a channel's run id in the archive is not its group's (stock logs
   a "Channel run.id" warning per channel);
3. non-integer rate and phantom channel (issues 10 and 17, which live in
   mt_timeseries), run twice: with the mt-timeseries clone at
   MTPROC_FORKS/mt-timeseries (its src/ also on PYTHONPATH) and with the
   installed mt_timeseries: hx and hy at 10.00064 Hz written with
   `RunGroup.from_runts` and read back with `to_runts` and `time_slice` step
   their index by neither 100,000,000 ns (the known rounding: reported as not
   fixed for the installed package, a failure for the clone) nor
   99,993,600 +- 1 ns; or the step is right but the run's or the channel's
   sample rate is not 10.00064, a RunTS of hx and hy at 1.5 Hz does not step
   by 666,666,666.7 +- 1 ns at 1.5 Hz (the rounding steps by 500,000,000 ns,
   2 Hz), or the station of the 10.00064 Hz RunTS lists other channels than
   hx and hy (the rounding comes with ["auxiliary_default"]): a partial fix.
   Without the clone only the installed package is run;
4. no-harmonic band (issue 20): `Band(frequency_min=0.1575,
   frequency_max=0.1984).set_indices_from_frequencies(np.fft.rfftfreq(128,
   0.1))` does not raise a ValueError naming "0.1575-0.1984 Hz" and the
   spacing "0.078125 Hz" under the fork (stock raises a bare IndexError);
5. cost, when the installed packages are not the forks: on a synthetic 1 h,
   1000 Hz, five-channel float64 archive
   (144 MB), the fork's best wall time of `RunGroup.to_runts()`,
   `to_runts` of 20 min or `ChannelDataset.time_slice` of 20 min exceeds the
   stock best by more than TIME_TOLERANCE (5 %: other jobs share the
   machine). Stock and fork alternate, ROUNDS processes each, REPS calls a
   process; each process's peak working-set increment and the raw h5py
   slice time are reported, not tested.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from _scratch import fork_clone, forks_dir  # noqa: E402

TIME_TOLERANCE = 0.05
ROUNDS, REPS = 2, 3
FS_ODD = 10.00064  # the Orange Box rate of issue 10
SYN_START = "2020-01-01T00:00:00"
SLICE_START, SLICE_N = "2020-01-01T00:10:00", 1_200_000  # 20 min at 1000 Hz
TIMED_OPS = ["to_runts", "to_runts_20min", "time_slice_20min"]


def branch(path: Path) -> str:
    """Return a clone's checked-out branch, or the first 10 characters of a detached HEAD."""
    head = path / ".git" / "HEAD"
    text = head.read_text(encoding="utf-8").strip() if head.exists() else ""
    return text.rsplit("/", 1)[-1] if text.startswith("ref:") else text[:10]


def _env(fork: tuple[Path, ...] | None) -> dict:
    """Build a worker's environment.

    PYTHONPATH is the fork's clones (None: none, for the installed
    packages), this process's own PYTHONPATH, then src.
    """
    env = dict(os.environ)
    env.pop("HDF5_USE_FILE_LOCKING", None)  # the lock is what check 1 needs
    parts = [str(p) for p in fork] if fork else []
    inherited = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts + inherited + [str(REPO / "src")])
    return env


def run_worker(fork: tuple[Path, ...] | None, *args: str) -> dict:
    """Run `--worker args` in a fresh process and return its JSON line.

    Args:
        fork (tuple[Path, ...] | None): Clones to put on PYTHONPATH; None
            for the installed packages.
        *args (str): Worker name and its arguments.

    Raises:
        RuntimeError: When the worker fails or prints no JSON line.
    """
    done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", *args],
                          env=_env(fork), capture_output=True, text=True, cwd=REPO)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("{")]
    if done.returncode != 0 or not lines:
        raise RuntimeError(f"worker {args} exited {done.returncode}:\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}")
    return json.loads(lines[-1])


# --------------------------------------------------------------------------- workers (one per process)

def _quiet():
    """Remove every loguru sink and return the logger."""
    from loguru import logger

    logger.remove()  # after mth5's import, which adds its own sink
    return logger


def _where() -> dict:
    """Return the files mth5 and mt_metadata are imported from."""
    import mt_metadata
    import mth5

    return {"mth5": mth5.__file__, "mt_metadata": mt_metadata.__file__}


def w_write_small(tmp: str) -> dict:
    """Write crosspower_unit's L (two runs) and R (one run) archives into `tmp`."""
    sys.path.insert(0, str(REPO / "tests"))
    import crosspower_unit as cu
    import pandas as pd

    tmp = Path(tmp)
    data = cu.field_and_channels()
    cu.write_archive(tmp / "L.h5", "L", [(cu.T0 + pd.Timedelta(seconds=a),
                                          {c: data[c][cu.index(a): cu.index(b)] for c in ("ex", "ey", "hx", "hy")})
                                         for a, b in cu.L_RUNS_S])
    cu.write_archive(tmp / "R.h5", "R", [(cu.T0 - pd.Timedelta(seconds=cu.LEAD_S),
                                          {"hx": data["r_hx"], "hy": data["r_hy"]})])
    return _where()


def w_hold(tmp: str) -> None:
    """Hold L.h5 and R.h5 open read-only until stdin closes."""
    import h5py

    files = [h5py.File(Path(tmp) / name, "r") for name in ("L.h5", "R.h5")]
    print("held", flush=True)
    sys.stdin.read()
    for f in files:
        f.close()


def w_read_only(tmp: str) -> dict:
    """Build RunSummary and KernelDataset over L and R directly with mth5, without mtproc.process."""
    from mth5.processing.kernel_dataset import KernelDataset
    from mth5.processing.run_summary import RunSummary

    _quiet()
    paths = [Path(tmp) / "L.h5", Path(tmp) / "R.h5"]
    before = [os.stat(p).st_mtime_ns for p in paths]
    stations, error = [], None
    try:
        run_summary = RunSummary()
        run_summary.from_mth5s(paths)
        kernel_dataset = KernelDataset()
        kernel_dataset.from_run_summary(run_summary, "L", "R")
        stations = sorted(kernel_dataset.df.station.unique().tolist())
    except Exception as exc:  # the stock control raises here
        error = f"{type(exc).__name__}: {exc}"
    after = [os.stat(p).st_mtime_ns for p in paths]
    return {**_where(), "stations": stations, "error": error, "mtime_unchanged": before == after}


def w_run_ids(tmp: str) -> dict:
    """Ingest three synthetic LEMI-423 files with mtproc and collect the mth5.groups.run warnings logged."""
    sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]
    import new_survey_unit as nsu

    tmp = Path(tmp)
    folder, _sub, serial, fw, lat, lon, alt, epoch, spacing, n = nsu.SITES[0]
    for k in range(n):
        nsu.write_b423(tmp / "raw" / folder / f"{epoch + k * spacing}.B423", serial, fw, lat, lon, alt,
                       epoch + k * spacing)
    yaml_path = tmp / "survey" / "survey.yaml"
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "new_survey.py"), str(tmp / "raw"),
                           "--name", "fork_proof", "--out", str(yaml_path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    from mth5.mth5 import MTH5
    from mtproc.ingest import ingest_site
    from mtproc.survey import Survey

    logger = _quiet()
    warnings: list[str] = []
    logger.add(lambda m: warnings.append(m.record["message"]), level="WARNING",
               filter=lambda r: r["name"] == "mth5.groups.run")
    path = ingest_site(Survey.from_yaml(yaml_path), folder, out_path=tmp / f"{folder}.h5", overwrite=True)
    ids = []
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station(folder, survey="fork_proof")
        for run_id in station.groups_list:
            run = station.get_run(run_id)
            for comp in run.groups_list:
                ids.append([run_id, run.metadata.id, comp, run.get_channel(comp).run_metadata.id])
    finally:
        m.close_mth5()
    return {**_where(), "warnings": warnings, "ids": ids}


def w_rate(tmp: str) -> dict:
    """Write hx, hy at 10.00064 Hz with from_runts, read them back with to_runts and time_slice, and build a 1.5 Hz RunTS."""
    import mt_timeseries
    import numpy as np
    from mt_metadata.timeseries import Magnetic, Run, Station
    from mt_timeseries import ChannelTS, RunTS
    from mth5.mth5 import MTH5

    _quiet()
    start = "2009-06-16T02:01:04+00:00"

    def pair(fs: float) -> list:
        """Build hx and hy ChannelTS of 3600 samples at `fs`."""
        chans = []
        for comp in ("hx", "hy"):
            meta = Magnetic(component=comp, sample_rate=fs)
            meta.time_period.start = start
            chans.append(ChannelTS("magnetic", data=np.arange(3600, dtype=float), channel_metadata=meta))
        return chans

    run_ts = RunTS(pair(FS_ODD), run_metadata=Run(id="sr10_0001"), station_metadata=Station(id="OB1"))
    run_15 = RunTS(pair(1.5), run_metadata=Run(id="sr1_0001"), station_metadata=Station(id="OB1"))
    path = Path(tmp) / "odd_rate.h5"
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("odd")
        station = m.add_station("OB1", survey="odd")
        station.add_run("sr10_0001").from_runts(run_ts)
    finally:
        m.close_mth5()

    def step_ns(t) -> float:
        """Return the first time step of an index in ns."""
        return float((t[1] - t[0]) / np.timedelta64(1, "ns"))

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_run("OB1", "sr10_0001", "odd")
        back = run.to_runts()
        sliced = run.get_channel("hx").time_slice(start, n_samples=100)
        out = {"to_runts_step_ns": step_ns(back.dataset.time.values),
               "time_slice_step_ns": step_ns(sliced.data_array.time.values),
               "run_rate": float(back.run_metadata.sample_rate),
               "channel_rate": float(run.get_channel("hx").metadata.sample_rate)}
    finally:
        m.close_mth5()
    out.update({"step_15_ns": step_ns(run_15.dataset.time.values), "rate_15": float(run_15.sample_rate),
                "channels_recorded": list(run_ts.station_metadata.channels_recorded),
                "mt_timeseries": mt_timeseries.__file__})
    return {**_where(), **out}


def w_band() -> dict:
    """Set the indices of a band holding no harmonic and report the error raised."""
    import numpy as np
    from mt_metadata.common.band import Band

    band = Band(frequency_min=0.1575, frequency_max=0.1984)
    try:
        band.set_indices_from_frequencies(np.fft.rfftfreq(128, 0.1))
        error = None
    except Exception as exc:
        error = [type(exc).__name__, str(exc)]
    return {**_where(), "error": error}


def w_make_synth(path: str) -> dict:
    """Write 1 h at 1000 Hz of ex ey hx hy hz float64, laid out as mtproc lays a site (one run, sr1000_0001)."""
    import numpy as np
    from mt_metadata.timeseries import Electric, Magnetic, Run, Station
    from mt_timeseries import ChannelTS, RunTS
    from mth5.mth5 import MTH5

    _quiet()
    fs, n = 1000.0, 3_600_000
    rng = np.random.default_rng(0)
    chans = []
    for comp in ("ex", "ey", "hx", "hy", "hz"):
        cls, kind = (Electric, "electric") if comp.startswith("e") else (Magnetic, "magnetic")
        meta = cls(component=comp, sample_rate=fs)
        meta.time_period.start = SYN_START + "+00:00"
        chans.append(ChannelTS(kind, data=rng.standard_normal(n), channel_metadata=meta))
    run_ts = RunTS(chans, run_metadata=Run(id="sr1000_0001"), station_metadata=Station(id="SYN"))
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("synthetic")
        station = m.add_station("SYN", survey="synthetic")
        station.add_run("sr1000_0001").from_runts(run_ts)
    finally:
        m.close_mth5()
    return _where()


def w_time(path: str, op: str) -> dict:
    """Time one operation: the best of REPS calls and this process's peak working-set increment."""
    import psutil
    from mth5.mth5 import MTH5

    _quiet()
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_run("SYN", "sr1000_0001", "synthetic")
        ch = run.get_channel("ex")
        ch.time_slice(SLICE_START, n_samples=1000)  # warm: metadata, filters, file cache
        i0 = ch.get_index_from_time(SLICE_START)
        h5 = []
        for _ in range(REPS):
            t0 = time.perf_counter()
            ch.hdf5_dataset[i0:i0 + SLICE_N]
            h5.append(time.perf_counter() - t0)
        info = psutil.Process().memory_info()
        rss0 = info.rss
        secs = []
        for _ in range(REPS):
            t0 = time.perf_counter()
            if op == "to_runts":
                out = run.to_runts()
            elif op == "to_runts_20min":
                out = run.to_runts(start=SLICE_START, n_samples=SLICE_N)
            elif op == "time_slice_20min":
                out = ch.time_slice(SLICE_START, n_samples=SLICE_N)
            else:
                raise ValueError(op)
            secs.append(time.perf_counter() - t0)
            del out
        peak = psutil.Process().memory_info().peak_wset
    finally:
        m.close_mth5()
    return {**_where(), "op": op, "best": min(secs), "h5py_best": min(h5), "peak_increment": peak - rss0}


WORKERS = {"write_small": w_write_small, "hold": w_hold, "read_only": w_read_only, "run_ids": w_run_ids,
           "rate": w_rate, "band": w_band, "make_synth": w_make_synth, "time": w_time}


# --------------------------------------------------------------------------- the parent side

def check_read_only(fork, tmp: Path) -> bool:
    """Run check 1: assert it on the fork and return whether the installed packages pass too."""
    run_worker(None, "write_small", str(tmp))

    def held(which) -> dict:
        """Run the read_only worker while another process holds both archives open read-only."""
        holder = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", "hold", str(tmp)],
                                  env=_env(None), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == "held", "the holder process did not open the archives"
            return run_worker(which, "read_only", str(tmp))
        finally:
            holder.communicate("", timeout=60)

    got = held(fork)
    assert got["error"] is None, f"1. fork: {got['error']}"
    assert got["stations"] == ["L", "R"], f"1. fork: kernel dataset stations {got['stations']}"
    assert got["mtime_unchanged"], "1. fork: an archive's modification time changed"
    line = "run summary + kernel dataset of L (2 runs) and R while another process holds both read-only: " \
           "stations L, R, mtimes unchanged"
    control = held(None)
    fixed = control["error"] is None and control["stations"] == ["L", "R"] and control["mtime_unchanged"]
    line += ("; installed: fixed too" if fixed else
             f"; installed: not fixed ({(control['error'] or 'an mtime changed').splitlines()[0][:110]})")
    print(f"  1. {line}")
    return fixed


def check_run_ids(fork, tmp: Path) -> bool:
    """Run check 2: assert it on the fork and return whether the installed packages pass too."""
    got = run_worker(fork, "run_ids", str(tmp / "fork"))
    assert not got["warnings"], f"2. fork: mth5.groups.run warned {got['warnings']}"
    wrong = [row for row in got["ids"] if not (row[0] == row[1] == row[3])]
    assert got["ids"] and not wrong, f"2. fork: run ids (group, group metadata, channel, channel run id) {wrong}"
    runs = sorted({row[0] for row in got["ids"]})
    line = f"ingest_site: {len(got['ids'])} channels in runs {runs}, no mth5.groups.run warning, run ids consistent"
    try:
        control = run_worker(None, "run_ids", str(tmp / "stock"))
    except RuntimeError as exc:  # stock mt-io cannot read the LEMI-423 coil file mtproc passes it
        tail = [ln for ln in str(exc).splitlines() if ln.strip()]
        print(f"  2. {line}; installed: the ingest fails ({tail[-1][:110] if tail else exc})")
        return False
    hits = [w for w in control["warnings"] if w.startswith("Channel run.id")]
    fixed = not control["warnings"] and bool(control["ids"]) and all(r[0] == r[1] == r[3] for r in control["ids"])
    line += ("; installed: fixed too" if fixed else
             f"; installed: not fixed ({len(hits)} x '{(hits or control['warnings'] or [''])[0][:60]}...')")
    print(f"  2. {line}")
    return fixed


def check_rate(fork, tmp: Path) -> None:
    """Run check 3 with the mt-timeseries clone, if any, and with the installed mt_timeseries."""
    mtts_clone = fork_clone("mt-timeseries")
    stacks = [("installed mt_timeseries", fork)]
    if mtts_clone is not None and (mtts_clone / "src" / "mt_timeseries" / "__init__.py").exists():
        stacks.insert(0, (f"mt-timeseries clone ({branch(mtts_clone)})", (*fork, mtts_clone / "src")))
    else:
        print(f"  3. no mt-timeseries clone at {forks_dir('mt-timeseries')}: the installed mt_timeseries only")
    want = 1e9 / FS_ODD
    for k, (label, paths) in enumerate(stacks):
        sub = tmp / f"stack{k}"
        sub.mkdir()
        got = run_worker(paths, "rate", str(sub))
        is_clone = paths is not fork
        if is_clone:
            assert Path(got["mt_timeseries"]).is_relative_to(mtts_clone), f"3. imported {got['mt_timeseries']}"
        steps = (got["to_runts_step_ns"], got["time_slice_step_ns"])
        seen = (f"index steps {steps[0]:,.0f} ns (to_runts) / {steps[1]:,.0f} ns (time_slice), run rate "
                f"{got['run_rate']:.7g}; 1.5 Hz: {got['step_15_ns']:,.0f} ns, rate {got['rate_15']:.7g}; station "
                f"channels {got['channels_recorded']}")
        if all(s == 1e8 for s in steps) and not is_clone:
            print(f"  3. {label}: {seen}: not fixed ({got['mt_timeseries']})")
            continue
        assert all(abs(s - want) <= 1.0 for s in steps), f"3. {label}: {seen}; want {want:,.1f} ns"
        assert got["run_rate"] == FS_ODD and got["channel_rate"] == FS_ODD, f"3. {label}: partial fix: {got}"
        assert abs(got["step_15_ns"] - 1e9 / 1.5) <= 1.0 and got["rate_15"] == 1.5, f"3. {label}: {seen}"
        assert got["channels_recorded"] == ["hx", "hy"], f"3. {label}: {seen}"
        print(f"  3. {label}: {seen}")


def check_band(fork) -> bool:
    """Run check 4: assert it on the fork and return whether the installed packages pass too."""
    got = run_worker(fork, "band")
    assert got["error"] and got["error"][0] == "ValueError", f"4. fork: {got['error']}"
    assert "0.1575-0.1984 Hz" in got["error"][1] and "0.078125 Hz" in got["error"][1], f"4. fork: {got['error']}"
    line = f"Band 0.1575-0.1984 Hz on a 128-point 10 Hz window: ValueError '{got['error'][1]}'"
    control = run_worker(None, "band")
    fixed = control["error"] == got["error"]
    line += "; installed: fixed too" if fixed else f"; installed: not fixed ({control['error']})"
    print(f"  4. {line}")
    return fixed


def check_cost(fork, tmp: Path) -> None:
    """Run check 5: time the fork against the installed packages, alternating ROUNDS times."""
    path = tmp / "synthetic_1h_1000hz.h5"
    run_worker(None, "make_synth", str(path))
    rows = {op: {"stock": [], "fork": []} for op in TIMED_OPS}
    for _ in range(ROUNDS):  # alternate, so both see the same machine load
        for op in TIMED_OPS:
            rows[op]["stock"].append(run_worker(None, "time", str(path), op))
            rows[op]["fork"].append(run_worker(fork, "time", str(path), op))
    slower = []
    print(f"  5. cost on {path.name} ({path.stat().st_size / 1e6:.0f} MB), best of {ROUNDS} x {REPS}:")
    for op in TIMED_OPS:
        best = {k: min(r["best"] for r in v) for k, v in rows[op].items()}
        peak = {k: min(r["peak_increment"] for r in v) / 2**20 for k, v in rows[op].items()}
        h5 = min(r["h5py_best"] for v in rows[op].values() for r in v)
        ratio = best["fork"] / best["stock"]
        print(f"     {op:17s} stock {best['stock']:6.3f} s  fork {best['fork']:6.3f} s  ({ratio:.2f}x)   "
              f"peak increment stock {peak['stock']:5.0f} MiB  fork {peak['fork']:5.0f} MiB"
              + (f"   (raw h5py slice of 20 min: {h5:.3f} s)" if op == "time_slice_20min" else ""))
        if ratio > 1.0 + TIME_TOLERANCE:
            slower.append((op, round(ratio, 3)))
    assert not slower, f"5. the fork is slower than stock by more than {TIME_TOLERANCE:.0%}: {slower}"


def main() -> int:
    """Run the checks on the fork clones; return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    mth5_clone, mtm_clone = fork_clone("mth5"), fork_clone("mt-metadata")
    have = (mth5_clone is not None and mtm_clone is not None
            and (mth5_clone / "mth5" / "__init__.py").exists()
            and (mtm_clone / "mt_metadata" / "__init__.py").exists())
    if not have:
        print(f"SKIPPED  mth5_fork_unit: no clones at {forks_dir('mth5')} and {forks_dir('mt-metadata')}; "
              f"stock mth5/mt_metadata only, the fork checks are skipped")
        return 0
    mtio_clone = fork_clone("mt-io")
    mtio_src = mtio_clone / "src" if mtio_clone is not None and (mtio_clone / "src" / "mt_io").is_dir() else None
    fork = (mth5_clone, mtm_clone) + ((mtio_src,) if mtio_src else ())
    where = run_worker(fork, "band")
    assert Path(where["mth5"]).is_relative_to(mth5_clone), f"the fork worker imported mth5 from {where['mth5']}"
    assert Path(where["mt_metadata"]).is_relative_to(mtm_clone), f"... mt_metadata from {where['mt_metadata']}"
    installed = run_worker(None, "band")
    print(f"  fork: mth5 {mth5_clone} ({branch(mth5_clone)}), mt_metadata {mtm_clone} ({branch(mtm_clone)})"
          + (f", mt-io {mtio_src} ({branch(mtio_clone)})" if mtio_src else ", the installed mt-io"))
    print(f"  installed: mth5 {installed['mth5']}, mt_metadata {installed['mt_metadata']}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for sub in ("small", "fork", "stock", "rate", "cost"):
            (tmp / sub).mkdir()
        fixed = {1: check_read_only(fork, tmp / "small"), 2: check_run_ids(fork, tmp)}
        check_rate(fork, tmp / "rate")
        fixed[4] = check_band(fork)
        if all(fixed.values()):
            print("  5. cost: skipped (the installed packages pass checks 1, 2 and 4: the forks, nothing to compare)")
        else:
            check_cost(fork, tmp / "cost")
    not_fixed = [k for k, v in fixed.items() if not v]
    print(f"\n  fork: checks 1-4 fixed; installed: "
          + ("checks 1, 2 and 4 fixed too" if not not_fixed else f"not fixed on check(s) {not_fixed} (stock)"))
    print("\nPASS  mth5_fork_unit")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        result = WORKERS[sys.argv[2]](*sys.argv[3:])
        if result is not None:
            print(json.dumps(result))
        sys.exit(0)
    sys.exit(main())
