# -*- coding: utf-8 -*-
"""
Unit test for the mtproc aurora fork against stock aurora 0.6.2

Tests the fork (branch `mtproc-fixes`, version `0.6.2+mtproc`). The
estimate is `crust.process.process_station` on the synthetic pair of
`tests/crosspower_unit.py` stretched to 2 h: its field, generator and
archive writer (100 Hz, known Z) with the field running for `SPAN_S` = 7300
s, L (ex ey hx hy) in two runs [T0, T0 + 3500 s) and [T0 + 3600 s, T0 +
7100 s), and R recording ex ey (the field's electrics) as well as its own hx
hy over the whole span, as a full MT remote does. crosspower_unit's white Ex
burst (10 times Ex's rms over [1800, 2400) s after T0) is continued with the
same amplitude to 3200 s (seed 11), so that it keeps its share of the record
(1400 of 7000 s; 600 of 3000 s there) and some regressions still exhaust
their 10 Huber iterations under stock aurora. L rr R, the lemimt scheme at 100 Hz
out to 10 s (four decimation levels, 24 bands, the scheme of
`tests/band_masks_unit.py`), output channels ex and ey, no tweaks, no masks.
R's ex and ey stay out of the regression: under stock aurora the estimate
is identical with and without them, and the fork skips their transform.
Every estimate runs in a fresh subprocess (`--worker`) with BLAS pinned to
one thread (OPENBLAS/OMP/MKL_NUM_THREADS=1), so its peak memory is its own
and PYTHONPATH chooses the aurora it imports (the clone, when it is the one
tested, ahead of this process's own PYTHONPATH and src).

The fixtures (`tests/fixtures/aurora_stock/`, written by `--make-fixtures`
under stock aurora 0.6.2):

- `stock_default.edi`: the stock estimate's EDI;
- `stock_default.npz`: `periods`, `z`, `z_err` (impedance and
  impedance_error) of the stock estimate; `z_huber_reset`,
  `z_err_huber_reset` of the same estimate with the Huber stage starting
  from a fresh iteration count for every regression (the test-local patch of
  `tests/band_masks_unit.py`, which is what the fork's first fix does);
  `huber_affected`, the indices of the bands where the two differ;
- `stock_default.json`: versions, threads, per-run seconds and memory (peak
  working set of the worker process; RSS just before `process_station`), the
  best of `REPS` runs, and the affected bands.

The aurora tested is the installed one (what this interpreter imports) when
its `aurora.__version__` carries `+mtproc`; otherwise the clone of the fork
at `CRUST_FORKS/aurora` (CRUST_FORKS defaults to `_scratch.DEFAULT_FORKS`)
when its `aurora/__init__.py` carries `+mtproc`, run with
PYTHONPATH=<clone> ahead of site-packages. With neither, check 0 alone runs
and the fork checks are reported as skipped. When the installed aurora is
the fork and a clone of it exists too, one estimate is also made with the
clone and compared with the installed fork's, for information (a clone
ahead of what is installed may differ).

Usage:
    python tests/aurora_fork_unit.py                  # the checks below
    python tests/aurora_fork_unit.py --make-fixtures  # stock aurora 0.6.2 only: rewrites tests/fixtures/aurora_stock/

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

0. a fixture is missing; the npz does not hold 24 periods and 24 x 2 x 2
   finite Z and Z error arrays for both stock runs; the EDI's Z, read back
   with mt_metadata, differs from the npz's by more than 1e-5 of the band's
   largest |Z| (the EDI's print precision); the json does not name aurora
   0.6.2 or does not hold `REPS` runs with seconds and a peak;
1. identity: in any band outside `huber_affected`, the fork's Z or Z error
   differs from the stock fixture's by more than `RTOL` of the band's largest
   |Z| (|Z error|); or, in a band of `huber_affected`, from the Huber-reset
   stock run's; or the fork's `REPS` runs are not identical to each other;
2. the per-band window masks on the config: `DecimationLevel.window_masks` =
   [[T0 + 1800 s, T0 + 3200 s, pmin, pmax]] (the burst) on every level,
   [pmin, pmax] the edges of level 1's second band (0.4525 s, the cascade
   band of band_masks_unit; check 0 fails unless it is one of the bands the
   Huber reset changes) does not change that band's Z, changes any other band's Z or Z error by a single
   bit against the fork's unmasked run, or differs by a single bit in any
   band from CRUST's runtime patch (`process_station(time_masks=[the same
   mask])`) run on the fork;
3. cost: the fork's best peak increment over `REPS` runs (peak working set
   minus RSS just before `process_station`) is not below the stock best
   recorded in the json; or its best-of-`REPS` wall time of
   `process_station` is not below stock's: with the clone (stock aurora
   installed), stock's best of `REPS` runs made now, alternating with the
   fork's (each stock run must also be identical to the fixture);
   with the fork installed, the stock best recorded in the json. Wall time
   on this machine moves by 15 % within an hour while the processing
   campaign runs (stock's best: 15.7 s when the fixtures were made, 18.2 s
   in the bisect an hour later), so a recorded time is compared only when
   stock cannot be run. Memory is steady to 1 %.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from _scratch import fork_clone, forks_dir  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "aurora_stock"
STEM = "stock_default"
STOCK_VERSION = "0.6.2"
FORK_TAG = "+mtproc"
THREADS = "1"
REPS = 3
RTOL = 1e-12  # relative to the band's largest |Z| (|Z error|)
MASK_LEVEL, MASK_INDEX = 1, 1  # level 1's second band from the low-frequency end: 0.4525 s
BURST_S = (1800.0, 3200.0)  # the white Ex burst, s after T0: crosspower_unit's [1800, 2400) continued
SPAN_S = 7300.0  # the field runs from T0 - 100 s: 2 h of L plus margins
L_RUNS_S = [(0.0, 3500.0), (3600.0, 7100.0)]  # s after T0, a 100 s gap as in crosspower_unit
OUTPUTS = ["ex", "ey"]


def clone_is_fork(path: Path) -> bool:
    """Check whether a clone's aurora/__init__.py carries the fork tag."""
    init = path / "aurora" / "__init__.py"
    return init.exists() and FORK_TAG in init.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- worker (one estimate per process)

def _peak_bytes() -> int:
    """Return this process's peak working set (Windows) or maximum RSS (POSIX) in bytes."""
    import psutil

    info = psutil.Process().memory_info()
    if hasattr(info, "peak_wset"):  # Windows: the process's peak working set
        return int(info.peak_wset)
    import resource  # POSIX: ru_maxrss, KiB on Linux

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _mask_edges(scheme) -> tuple[float, float]:
    """Return the (pmin, pmax) period edges in s of the masked band."""
    lo, hi = np.asarray(scheme["band_edges"][MASK_LEVEL])[MASK_INDEX]
    return 1.0 / hi, 1.0 / lo


def worker(out: Path, local: Path, remote: Path, mode: str, edi_dir: Path | None) -> None:
    """Make one estimate in this process and write periods, Z, Z error and a meta json to `out` (npz).

    Args:
        out (Path): The npz to write.
        local (Path): L's archive.
        remote (Path): R's archive.
        mode (str): "default", "huber_reset", "config_mask" or
            "runtime_mask".
        edi_dir (Path | None): Folder for the EDI, if one is written.

    Raises:
        ValueError: On an unknown mode.
    """
    sys.path.insert(0, str(REPO / "tests"))
    import psutil
    import pandas as pd

    import crosspower_unit as cu  # the synthetic pair's constants (T0, FS)
    from loguru import logger

    import aurora
    import crust.process as mp
    from aurora.pipelines.process_mth5 import process_mth5
    from aurora.transfer_function.regression.m_estimator import MEstimator
    from crust.bands import build_band_scheme

    logger.remove()  # after aurora's and mth5's imports, which add their own sinks
    logger.add(sys.stderr, level="WARNING", filter=lambda r: r["name"].startswith("crust"))
    scheme = build_band_scheme(cu.FS, max_period=10.0)
    pmin, pmax = _mask_edges(scheme)
    start, end = (cu.T0 + pd.Timedelta(seconds=s) for s in BURST_S)
    kwargs = dict(band_scheme=scheme, output_channels=OUTPUTS)

    if mode == "huber_reset":  # what the fork's first commit does, as a test-local patch of stock aurora
        original = MEstimator.apply_huber_regression

        def apply_huber_regression(estimator):
            """Reset the iteration count, then run stock's Huber regression."""
            estimator.iter_control.reset_number_of_iterations()
            return original(estimator)

        MEstimator.apply_huber_regression = apply_huber_regression

    rss_before = psutil.Process().memory_info().rss
    t0, cpu0 = time.perf_counter(), time.process_time()
    if mode in ("default", "huber_reset"):
        tf = mp.process_station(local, "L", remote, "R", out_dir=edi_dir, tag=STEM if edi_dir else None, **kwargs)
    elif mode == "config_mask":  # process_station's own steps, with the mask on the config
        kd = mp.kernel_dataset(local, "L", remote, "R")
        config = mp.build_config(kd, scheme, None, output_channels=OUTPUTS)
        for dec in config.decimations:
            dec.window_masks = [[start.isoformat(), end.isoformat(), pmin, pmax]]
        tf = process_mth5(config, kd)
    elif mode == "runtime_mask":
        tf = mp.process_station(local, "L", remote, "R", time_masks=[{"start": start, "end": end,
                                                                        "bands": [pmin, pmax]}], **kwargs)
    else:
        raise ValueError(mode)
    seconds, cpu = time.perf_counter() - t0, time.process_time() - cpu0
    meta = {"mode": mode, "aurora": aurora.__version__, "aurora_file": aurora.__file__,
            "seconds": seconds, "cpu_seconds": cpu, "rss_before": rss_before, "peak": _peak_bytes(),
            "threads": os.environ.get("OPENBLAS_NUM_THREADS"), "mask": [start.isoformat(), end.isoformat(), pmin, pmax]}
    np.savez(out, periods=np.asarray(tf.period), z=np.asarray(tf.impedance.data),
             z_err=np.asarray(tf.impedance_error.data), meta=json.dumps(meta))


# --------------------------------------------------------------------------- the parent side

def write_pair(tmp: Path) -> tuple[Path, Path]:
    """Write crosspower_unit's L and R archives over 2 h (SPAN_S, L_RUNS_S), R with ex ey hx hy.

    Returns:
        tuple[Path, Path]: The L and R archives.
    """
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO / "tests"))
    import crosspower_unit as cu
    import pandas as pd

    saved = cu.SPAN_S
    cu.SPAN_S = SPAN_S  # field_and_channels reads the module's span
    try:
        data = cu.field_and_channels()
    finally:
        cu.SPAN_S = saved
    a, b = cu.index(cu.BURST * cu.CHUNK_S), cu.index((cu.BURST + 1) * cu.CHUNK_S)  # crosspower_unit's burst
    rms = np.delete(data["ex"], np.s_[a:b]).std()
    c = cu.index(BURST_S[1])
    data["ex"][b:c] += np.rint(10.0 * rms * np.random.default_rng(11).standard_normal(c - b))
    local, remote = tmp / "L.h5", tmp / "R.h5"
    cu.write_archive(local, "L", [(cu.T0 + pd.Timedelta(seconds=a),
                                   {c: data[c][cu.index(a): cu.index(b)] for c in ("ex", "ey", "hx", "hy")})
                                  for a, b in L_RUNS_S])
    cu.write_archive(remote, "R", [(cu.T0 - pd.Timedelta(seconds=cu.LEAD_S),
                                    {"ex": data["ex"], "ey": data["ey"], "hx": data["r_hx"], "hy": data["r_hy"]})])
    return local, remote


def run_worker(out: Path, local: Path, remote: Path, mode: str, aurora_path: Path | None = None,
               edi_dir: Path | None = None) -> dict:
    """Run `worker` in a fresh process and load its npz.

    PYTHONPATH is `aurora_path` (if any), this process's own PYTHONPATH,
    then this repo's src; BLAS is pinned to THREADS.

    Returns:
        dict: The npz arrays, with "meta" parsed from JSON.

    Raises:
        RuntimeError: When the worker fails.
    """
    env = dict(os.environ)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env[key] = THREADS
    inherited = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(([str(aurora_path)] if aurora_path else []) + inherited + [str(REPO / "src")])
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", str(out), "--local", str(local),
           "--remote", str(remote), "--mode", mode]
    if edi_dir is not None:
        cmd += ["--edi-dir", str(edi_dir)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"worker {mode} failed ({proc.returncode}):\n{proc.stderr[-6000:]}")
    with np.load(out, allow_pickle=False) as npz:
        res = {k: npz[k] for k in npz.files}
    res["meta"] = json.loads(str(res["meta"]))
    return res


def versions() -> dict:
    """Return the Python and package versions recorded with the fixtures."""
    import importlib.metadata as md

    out = {"python": platform.python_version()}
    for name in ("aurora", "mth5", "mt_metadata", "mt_timeseries", "numpy", "scipy", "xarray", "pandas"):
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "not installed"
    return out


def increment(meta: dict) -> int:
    """Return a run's peak increment: peak working set minus RSS before process_station."""
    return int(meta["peak"]) - int(meta["rss_before"])


def gib(n: float) -> str:
    """Format bytes as GiB."""
    return f"{n / 2**30:.3f} GiB"


def make_fixtures() -> int:
    """Write the fixtures under stock aurora: the default estimate REPS times (identical), its EDI, and the Huber-reset run."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        local, remote = write_pair(tmp)
        runs = []
        for k in range(REPS):
            res = run_worker(tmp / f"default{k}.npz", local, remote, "default", edi_dir=tmp if k == 0 else None)
            assert res["meta"]["aurora"] == STOCK_VERSION, f"fixtures need stock aurora {STOCK_VERSION}: {res['meta']}"
            runs.append(res)
            print(f"  stock run {k + 1}: {res['meta']['seconds']:.2f} s, peak {gib(res['meta']['peak'])}, "
                  f"increment {gib(increment(res['meta']))}")
        for res in runs[1:]:
            assert np.array_equal(res["z"], runs[0]["z"]) and np.array_equal(res["z_err"], runs[0]["z_err"]), \
                "the stock estimate is not deterministic: no bit-identity test can stand on it"
        reset = run_worker(tmp / "huber_reset.npz", local, remote, "huber_reset")
        shutil.copyfile(tmp / f"{STEM}.edi", FIXTURES / f"{STEM}.edi")
    ref = runs[0]
    moved = [k for k in range(ref["periods"].size)
             if not (np.array_equal(ref["z"][k], reset["z"][k]) and np.array_equal(ref["z_err"][k], reset["z_err"][k]))]
    np.savez(FIXTURES / f"{STEM}.npz", periods=ref["periods"], z=ref["z"], z_err=ref["z_err"],
             z_huber_reset=reset["z"], z_err_huber_reset=reset["z_err"], huber_affected=np.asarray(moved, dtype=int))
    best = min(runs, key=lambda r: r["meta"]["seconds"])["meta"]
    info = {
        "made": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "machine": platform.node(), "versions": versions(), "threads": THREADS,
        "estimate": ("process_station(L, rr R), crosspower_unit's pair stretched to 2 h (R with ex ey hx hy), "
                     "lemimt 100 Hz to 10 s, ex ey, no tweaks, no masks"),
        "runs": [{k: r["meta"][k] for k in ("seconds", "cpu_seconds", "rss_before", "peak")} for r in runs],
        "best_seconds": min(r["meta"]["seconds"] for r in runs),
        "best_peak_increment": min(increment(r["meta"]) for r in runs),
        "best_run": best,
        "huber_affected": moved, "huber_affected_periods": [float(ref["periods"][k]) for k in moved],
        "mask": ref["meta"]["mask"],
    }
    (FIXTURES / f"{STEM}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"  Huber reset moves {len(moved)} of {ref['periods'].size} bands: "
          f"{[round(float(ref['periods'][k]), 4) for k in moved]}")
    print(f"  wrote {FIXTURES / STEM}.edi / .npz / .json")
    return 0


def check_fixtures() -> tuple[dict, dict]:
    """Run check 0: the fixtures exist and hold what they should.

    Returns:
        tuple[dict, dict]: The npz arrays and the json info.
    """
    paths = [FIXTURES / f"{STEM}{ext}" for ext in (".edi", ".npz", ".json")]
    missing = [str(p) for p in paths if not p.exists()]
    assert not missing, f"0. missing fixtures {missing}: run python tests/aurora_fork_unit.py --make-fixtures under stock aurora"
    with np.load(paths[1], allow_pickle=False) as npz:
        fx = {k: npz[k] for k in npz.files}
    info = json.loads(paths[2].read_text(encoding="utf-8"))
    assert fx["periods"].shape == (24,), fx["periods"].shape
    for key in ("z", "z_err", "z_huber_reset", "z_err_huber_reset"):
        assert fx[key].shape == (24, 2, 2) and np.isfinite(fx[key]).all(), (key, fx[key].shape)
    assert info["versions"]["aurora"] == STOCK_VERSION, info["versions"]
    k_mask = int(np.argmin(np.abs(fx["periods"] - 1.0 / np.sqrt(np.prod(_scheme_edges())))))
    assert k_mask in fx["huber_affected"].tolist(), \
        f"0. the mask band {fx['periods'][k_mask]:.4f} s is not one the Huber reset changes: check 2 would not test it"
    assert len(info["runs"]) == REPS and all(r["seconds"] > 0 and r["peak"] > 0 for r in info["runs"]), info["runs"]
    from mt_metadata.transfer_functions.core import TF

    tf = TF()
    tf.read(paths[0])
    z_edi = np.asarray(tf.impedance.data)
    order = [int(np.argmin(np.abs(np.asarray(tf.period) - p))) for p in fx["periods"]]
    scale = np.abs(fx["z"]).max(axis=(1, 2))
    worst = float((np.abs(z_edi[order] - fx["z"]).max(axis=(1, 2)) / scale).max())
    assert worst < 1e-5, f"0. the EDI's Z is not the npz's: {worst:.2e} of |Z|"
    print(f"  0. fixtures: {STEM}.edi/.npz/.json, stock aurora {info['versions']['aurora']}, 24 bands; "
          f"EDI Z = npz Z within {worst:.1e} of |Z|; Huber reset moves bands {fx['huber_affected'].tolist()}")
    return fx, info


def worst_rel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return per band the max |a - b| over the 2x2, relative to the band's largest |b|."""
    return np.abs(a - b).max(axis=(1, 2)) / np.abs(b).max(axis=(1, 2))


def check_fork(fx: dict, info: dict, aurora_path: Path | None, clone_too: Path | None = None) -> None:
    """Run checks 1-3 on the fork.

    Args:
        fx (dict): The fixture arrays.
        info (dict): The fixture json.
        aurora_path (Path | None): The clone to test; None for the
            installed fork.
        clone_too (Path | None): A clone of the fork beside an installed
            fork; one estimate is compared with the installed fork's, for
            information.
    """
    clone_run = None
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        local, remote = write_pair(tmp)
        runs, stock_now = [], []
        for k in range(REPS):  # with the clone, stock and fork alternate, so both see the same machine load
            runs.append(run_worker(tmp / f"fork{k}.npz", local, remote, "default", aurora_path))
            if aurora_path is not None:
                stock_now.append(run_worker(tmp / f"stock{k}.npz", local, remote, "default"))
        config_mask = run_worker(tmp / "config_mask.npz", local, remote, "config_mask", aurora_path)
        runtime_mask = run_worker(tmp / "runtime_mask.npz", local, remote, "runtime_mask", aurora_path)
        if clone_too is not None:
            clone_run = run_worker(tmp / "clone.npz", local, remote, "default", clone_too)
    meta = runs[0]["meta"]
    assert FORK_TAG in meta["aurora"], f"the worker imported aurora {meta['aurora']} from {meta['aurora_file']}"
    print(f"  fork: aurora {meta['aurora']} from {meta['aurora_file']}")

    # 1. identity against stock (the Huber-reset stock run in the bands the reset moves)
    fork = runs[0]
    for res in stock_now:
        assert res["meta"]["aurora"] == STOCK_VERSION, res["meta"]
        assert np.array_equal(res["z"], fx["z"]) and np.array_equal(res["z_err"], fx["z_err"]), \
            "1. the stock estimate made now is not identical to the fixture: remake the fixtures"
    for res in runs[1:]:
        assert np.array_equal(res["z"], fork["z"]) and np.array_equal(res["z_err"], fork["z_err"]), \
            "1. the fork's runs are not identical to each other"
    affected = set(fx["huber_affected"].tolist())
    want_z = np.where(np.isin(np.arange(24), list(affected))[:, None, None], fx["z_huber_reset"], fx["z"])
    want_e = np.where(np.isin(np.arange(24), list(affected))[:, None, None], fx["z_err_huber_reset"], fx["z_err"])
    assert np.array_equal(fork["periods"], fx["periods"]), "1. the fork's band periods differ from stock"
    rz, re_ = worst_rel(fork["z"], want_z), worst_rel(fork["z_err"], want_e)
    identical = [k for k in range(24) if np.array_equal(fork["z"][k], want_z[k]) and np.array_equal(fork["z_err"][k], want_e[k])]
    bad = [(k, float(rz[k]), float(re_[k])) for k in range(24) if rz[k] > RTOL or re_[k] > RTOL]
    assert not bad, f"1. bands off stock by more than {RTOL:g} (band, dZ, dZerr): {bad}"
    print(f"  1. identity: {len(identical)} of 24 bands identical to stock (bands {sorted(affected)} to the "
          f"Huber-reset stock run); largest difference {rz.max():.2e} of |Z|, {re_.max():.2e} of |Z error| "
          f"(limit {RTOL:g})")

    # 2. the config's per-band window masks: only the masked band moves, and as the runtime patch moves it
    k_mask = int(np.argmin(np.abs(fx["periods"] - 1.0 / np.sqrt(np.prod(_scheme_edges())))))
    moved = [k for k in range(24) if not (np.array_equal(config_mask["z"][k], fork["z"][k])
                                          and np.array_equal(config_mask["z_err"][k], fork["z_err"][k]))]
    assert moved == [k_mask], f"2. the band mask on {fx['periods'][k_mask]:.4f} s moved bands {moved}"
    assert np.array_equal(config_mask["z"], runtime_mask["z"]) and np.array_equal(config_mask["z_err"], runtime_mask["z_err"]), \
        "2. the config's window_masks and CRUST's runtime patch differ"
    shift = float(worst_rel(config_mask["z"][k_mask:k_mask + 1], fork["z"][k_mask:k_mask + 1])[0])
    print(f"  2. window_masks over the burst in the {fx['periods'][k_mask]:.4f} s band: that band moves "
          f"({shift:.2%} of |Z|), the other 23 identical; identical to CRUST's runtime patch in all 24")

    # 3. cost: memory against the stock numbers recorded with the fixtures; time against stock
    #    run alternately now when stock aurora is installed (the clone case), else against the record
    secs = min(r["meta"]["seconds"] for r in runs)
    inc = min(increment(r["meta"]) for r in runs)
    stock_secs, where = info["best_seconds"], "recorded"
    if stock_now:
        stock_secs, where = min(r["meta"]["seconds"] for r in stock_now), "run alternately now"
        print(f"     stock now (best of {REPS}): {stock_secs:.2f} s, peak increment "
              f"{gib(min(increment(r['meta']) for r in stock_now))}; recorded {info['best_seconds']:.2f} s")
    print(f"  3. cost (best of {REPS}): {secs:.2f} s against stock {stock_secs:.2f} s ({where}, "
          f"{secs / stock_secs:.2f}x); peak increment {gib(inc)} against the recorded "
          f"{gib(info['best_peak_increment'])} ({inc / info['best_peak_increment']:.2f}x)")
    assert secs < stock_secs, "3. the fork is not faster than stock"
    assert inc < info["best_peak_increment"], "3. the fork's peak memory increment is not below stock's"

    if clone_run is not None:  # reported for information
        same = np.array_equal(clone_run["z"], fork["z"]) and np.array_equal(clone_run["z_err"], fork["z_err"])
        worst = float(max(worst_rel(clone_run["z"], want_z).max(), worst_rel(clone_run["z_err"], want_e).max()))
        print(f"  clone: aurora {clone_run['meta']['aurora']} from {clone_run['meta']['aurora_file']}: "
              + ("identical to the installed fork's estimate: fixed too" if same else
                 f"differs from the installed fork's estimate (largest difference from the stock/Huber-reset "
                 f"reference {worst:.2e} of |Z|): the clone is not what is installed"))


def _scheme_edges() -> tuple[float, float]:
    """Return the (low, high) frequency edges of the masked band of the 100 Hz scheme."""
    sys.path.insert(0, str(REPO / "src"))
    from crust.bands import build_band_scheme

    lo, hi = np.asarray(build_band_scheme(100.0, max_period=10.0)["band_edges"][MASK_LEVEL])[MASK_INDEX]
    return float(lo), float(hi)


def main() -> int:
    """Check the fixtures, pick the fork to test and run checks 1-3; return 0."""
    fx, info = check_fixtures()
    import aurora

    installed = aurora.__version__
    clone = fork_clone("aurora")
    clone_too = None
    if FORK_TAG in installed:
        path, where = None, f"installed aurora {installed} ({aurora.__file__})"
        if clone is not None and clone_is_fork(clone) and not Path(aurora.__file__).resolve().is_relative_to(
                clone.resolve()):
            clone_too = clone
            where += f"; the clone at {clone} is the fork too, one estimate compared"
    elif clone is not None and clone_is_fork(clone):
        path, where = clone, f"the clone at {clone} (installed: aurora {installed})"
    else:
        print(f"  aurora {installed} installed and no fork clone at {forks_dir('aurora')}: fork checks 1-3 SKIPPED")
        print("\nPASS  aurora_fork_unit (fixtures only)")
        return 0
    print(f"  fork checks on {where}")
    check_fork(fx, info, path, clone_too)
    print("\n  " + (f"installed aurora {installed}: the fork, checks 1-3 fixed" if path is None else
                     f"the clone: checks 1-3 fixed; installed aurora {installed}: stock"))
    print("\nPASS  aurora_fork_unit")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--make-fixtures", action="store_true")
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--local", type=Path)
    parser.add_argument("--remote", type=Path)
    parser.add_argument("--mode", default="default")
    parser.add_argument("--edi-dir", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.local, args.remote, args.mode, args.edi_dir)
        raise SystemExit(0)
    if args.make_fixtures:
        raise SystemExit(make_fixtures())
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    raise SystemExit(main())
