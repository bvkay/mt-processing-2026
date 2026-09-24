"""Profile one processing step: time, memory, CPU and disk, split into phases.

Usage:
    python scripts/profile_run.py <survey.yaml> <local> <remote>
        [--stage rr|ingest|variant|stack|read|cprofile|tracemalloc|trace|all] [--out DIR]
        [--site SITE] [--members A B C] [--stack-start UTC --stack-end UTC]
        [--rw-archive H5] [--read-archives DIR --read-sites S [S ...]]
        [--interval 0.5] [--need-gb GB] [--no-markers]
    python scripts/profile_run.py <survey.yaml> <local> <remote> --stage trace --window START END
        --read-archives DIR [--variants fork stock] [--passes ...] [--stock-aurora DIR]
        [--viz-min-us 10] [--tm-nframe 10] [--tm-pause "L0 read TS"] [--reanalyse RUN_ID]
    python scripts/profile_run.py --parse-log LOG [LOG ...] [--out DIR]
    python scripts/profile_run.py --ledger <campaign dir> [--out DIR]

Each stage runs as a CHILD process -- the real code: `rr` is scripts/process_rr.py
<local> <remote>, `ingest` scripts/ingest_site.py <site> --raw (the raw archive
from the B423 files; --force when one is already there), `variant`
`mtproc.ingest.build_variant(<site>)` (as the campaign runs it), `stack`
scripts/build_stack.py over --members, `read` the MTH5 read benchmarks below
-- while this process samples the child every --interval s with psutil: its
working set (RSS, what the campaign ledger records) and private bytes, its
CPU percent (100 = one core), its thread count and its own read/write bytes,
plus the machine's CPU, memory in use and disk read/write bytes (the campaign
runs beside it: the machine curves show that contention).

Phases come from the child's log. The child is started through this script
(`--child`), which wraps a fixed list of library functions (`TARGETS`: mtproc's,
mth5's, mt-io's, aurora's) so each call writes `PROFMARK <epoch> B|E P|D <name>`
lines to stderr: P marks are the timeline's phases (sequential; a gap is
"(untracked)"), D marks are details summed per name into `<stem>_details.csv`
(count, total and self seconds). `--no-markers` runs the script bare, and a
bare process_rr log -- a campaign log too, `--parse-log` -- is split by the
lines aurora itself logs: "DECIMATION LEVEL n", "Dataset Dataframe Updated",
"Skip saving FCs" (one per run's STFT), "Features could not be accessed"
(the regression starts), "type(tf_cls)", then process_rr's "wrote" lines.

Outputs in --out (default: the scratch folder of the run): `<stem>.log`,
`<stem>_samples.csv`, `<stem>_phases.csv` (phase, start/end/seconds, peak RSS,
mean CPU, machine disk MB read/written, the child's own MB read/written),
`<stem>_details.csv`, `<stem>_timeline.png` (RSS, CPU and I/O against time,
phases shaded and labelled). `cprofile`: process_rr's `process_station` call
(same arguments, `process_rr.resolve`) under cProfile in a child: the top 40
by cumulative and by internal time in `<stem>_cprofile.txt` (+ `.prof`).
`tracemalloc`: the same call, traced from the level-0 STFTs to the end of the
level-0 merge (where the peak is; tracing the whole run slowed its start
tenfold), a snapshot each time the RSS passes its previous high by 2 GiB; the
top 20 allocation sites of the last one (the peak, to within 2 GiB) in
`<stem>_tracemalloc.txt`. `read`: MTH5
opens (r; a only on --rw-archive, a dedicated file: never a hard link), the
channel summary, h5py slicing vs mth5 `time_slice` vs `to_runts` for 2 h and
a whole run, `RunSummary` + `KernelDataset` for the pair, and B423 files
through numpy vs mt-io (`<stem>_bench.csv`). `ingest`/`variant` also write
`<stem>_h5layout.csv` (dtype, chunks, compression, sizes). `all` runs ingest,
variant, stack, read, rr and cprofile in that order.

--read-archives DIR --read-sites S ... points `mtproc.ingest.default_archive_path`
and `variant_path` of those sites at DIR inside the child (both archives read
there, read-only: everything written -- EDIs, a rebuilt variant, a stack --
still goes to the survey's own workspace). That is how a scratch copy of a
survey.yaml processes the real archives without copying or linking them;
`ingest` and `variant` refuse a site in --read-sites.

--need-gb waits before a child starts until the available memory, less what
other running process_rr.py children younger than 4 min may still grow by
(to --other-peak-gb), is at least that much: the campaign's own jobs peak
near 53 GiB each on 43 h pairs.

`trace` (dev tools viztracer and py-spy in the environment) runs one windowed
estimate -- `mtproc.process.process_station` on the sites' filtered variants in
--read-archives (never built, opened read-only), the survey's lemimt bands, ex ey
out, no tweaks, no masks -- as four sampled children per aurora (the installed
fork; stock 0.6.2 from a worktree of the fork's clone at its base commit, first on
PYTHONPATH), so that no instrument distorts another: `pyspy-idle` and `pyspy-gil`
(clean runs, py-spy attached from outside: a speedscope file of every sample, a
flamegraph SVG of the GIL-holding ones; exact call counts and seconds per phase of
`COUNT_TARGETS` in `_calls.csv`, every h5py dataset read in `_h5reads.csv`, psutil
at each phase boundary in `_boundaries.csv`), `viztracer` (every call of at least
--viz-min-us us, C calls and GC included, in `<stem>_viztracer.json` + `.json.gz`
for ui.perfetto.dev or `vizviewer`; our phase / detail / per-band spans on the
"mtproc phases + counters" track, RSS, disk read, CPU and thread counters every
0.25 s) and `tracemalloc` (a snapshot at every phase boundary diffed with the one
before: `_tm_sites.csv`; per-span traced peaks `_tm_spans.csv`; retained memory by
owner `_tm_owners.csv`; the time series aurora's kernel dataset holds at each
boundary; the composition near the peak `_tm_peak.csv`; tracing stops over
--tm-pause, where pandas allocates a Python int per sample). The report per
variant: `trace_<variant>_<run>_trace_timeline.png` (phases, RSS, disk read, CPU,
the top 5 functions by self time per phase), `_trace_phases.csv`, `_viz_hot.csv`,
`_viz_callers.csv`, `_calls_by_level.csv`, `_h5reads_summary.csv`,
`_pyspy_top.csv`, `_tm_top_sites.csv`, `_tm_peak_sites.csv`, `_tm_retained.png`;
and `trace_compare_<run>.csv/.png`, `trace_compare_functions_<run>.csv`.

`--ledger` summarises a campaign: per kind, seconds and peak RSS
(`ledger_stats.csv`), and from runs.log the jobs running over time and the
share of each stage block with a slot idle (`ledger_slots.csv`,
`ledger.png`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psutil  # noqa: E402

GIB = 1024.0 ** 3
MB = 1e6
MARK = "PROFMARK"
RESULT = "PROFRESULT"

# (consumer module, qualname, label, P|D). A name imported with `from x import f`
# is patched where it is looked up (its consumer's namespace), a method on its
# class. "{L}" in a label is the current aurora decimation level.
COMMON = [("mtproc.survey", "Survey.from_yaml", "survey load", "P"),
          ("mth5.mth5", "MTH5.open_mth5", "mth5 open_mth5", "D"),
          ("mth5.mth5", "MTH5.close_mth5", "mth5 close_mth5", "D")]
# how a run gets from the archive into memory (mth5 -> mt_timeseries), where it is read
READ_DETAILS = [("mth5.groups.channel_dataset", "ChannelDataset.time_slice", "mth5: ChannelDataset.time_slice", "D"),
                ("mth5.groups.channel_dataset", "ChannelDataset.to_channel_ts", "mth5: ChannelDataset.to_channel_ts", "D"),
                ("mt_timeseries", "ChannelTS.__init__", "mt_timeseries: ChannelTS()", "D"),
                ("mt_timeseries", "RunTS.__init__", "mt_timeseries: RunTS()", "D")]
TARGETS = {
    "rr": [
        ("mtproc.ingest", "ingest_site", "raw archive check (ingest_site)", "P"),
        ("mtproc.ingest", "processing_archive", "variant check (processing_archive)", "P"),
        ("mtproc.masks", "load_masks", "masks.yaml", "P"),
        ("mtproc.process", "kernel_dataset", "run summary + kernel dataset", "P"),
        ("mth5.processing", "RunSummary.from_mth5s", "RunSummary.from_mth5s", "D"),
        ("mth5.processing", "KernelDataset.from_run_summary", "KernelDataset.from_run_summary", "D"),
        ("mtproc.process", "build_config", "aurora config", "P"),
        ("mtproc.process", "process_mth5", "aurora (other)", "P"),
        ("aurora.pipelines.transfer_function_kernel", "TransferFunctionKernel.update_processing_summary",
         "aurora setup", "P"),
        ("aurora.pipelines.transfer_function_kernel", "TransferFunctionKernel.validate", "aurora setup", "P"),
        ("aurora.pipelines.transfer_function_kernel", "TransferFunctionKernel.initialize_mth5s",
         "aurora setup", "P"),
        ("aurora.pipelines.transfer_function_kernel", "TransferFunctionKernel.update_dataset_df",
         "L{L} read/decimate TS", "P"),
        ("mth5.processing", "KernelDataset.initialize_dataframe_for_processing",
         "KernelDataset.initialize_dataframe_for_processing (read runs)", "D"),
        ("mth5.groups", "RunGroup.to_runts", "RunGroup.to_runts", "D"),
        ("aurora.pipelines.transfer_function_kernel", "prototype_decimate", "prototype_decimate", "D"),
        ("aurora.pipelines.process_mth5", "get_spectrograms", "L{L} STFT", "P"),
        ("aurora.time_series.spectrogram_helpers", "nan_to_mean", "stft: nan_to_mean", "D"),
        ("aurora.time_series.spectrogram_helpers", "apply_prewhitening", "stft: prewhitening", "D"),
        ("aurora.time_series.spectrogram_helpers", "truncate_to_clock_zero", "stft: truncate", "D"),
        ("aurora.time_series.windowing_scheme", "WindowingScheme.apply_sliding_window",
         "stft: sliding window", "D"),
        ("aurora.time_series.windowed_time_series", "WindowedTimeSeries.detrend", "stft: detrend", "D"),
        ("aurora.time_series.windowed_time_series", "WindowedTimeSeries.apply_taper", "stft: taper", "D"),
        ("aurora.time_series.windowed_time_series", "fft_xr_ds", "stft: fft_xr_ds (detrend + np.fft.fft)", "D"),
        ("aurora.time_series.spectrogram_helpers", "apply_recoloring", "stft: recoloring", "D"),
        ("aurora.time_series.spectrogram_helpers", "calibrate_stft_obj", "stft: calibrate", "D"),
        ("aurora.pipelines.process_mth5", "merge_stfts", "L{L} merge STFTs", "P"),
        ("aurora.pipelines.process_mth5", "extract_features", "L{L} features/weights", "P"),
        ("aurora.pipelines.process_mth5", "calculate_weights", "L{L} features/weights", "P"),
        ("aurora.pipelines.process_mth5", "process_tf_decimation_level", "L{L} regression", "P"),
        ("aurora.pipelines.transfer_function_helpers", "get_band_for_tf_estimate",
         "regression: get_band_for_tf_estimate", "D"),
        ("aurora.pipelines.transfer_function_helpers", "stack_fcs", "regression: stack_fcs", "D"),
        ("aurora.pipelines.transfer_function_helpers", "drop_nans", "regression: drop_nans", "D"),
        ("aurora.pipelines.transfer_function_helpers", "effective_degrees_of_freedom_weights",
         "regression: edf weights", "D"),
        ("aurora.pipelines.transfer_function_helpers", "apply_weights", "regression: apply_weights", "D"),
        ("aurora.pipelines.transfer_function_helpers", "handle_nan", "regression: handle_nan", "D"),
        ("aurora.transfer_function.regression.RME_RR", "RME_RR.estimate", "regression: RME_RR.estimate", "D"),
        ("aurora.pipelines.transfer_function_kernel", "TransferFunctionKernel.export_tf_collection",
         "aurora TF export", "P"),
        ("mt_metadata.transfer_functions.core", "TF.write", "EDI write", "P"),
        ("mtproc.compare", "phase_quadrants", "phase quadrants", "P"),
        ("mtproc.compare", "plot_comparison", "comparison figure", "P"),
    ],
    "ingest": [
        ("mtproc.ingest", "select_files", "select B423 files", "P"),
        ("mtproc.ingest", "_group_contiguous", "group contiguous files (ours)", "P"),
        ("mtproc.ingest", "read_lemi423", "mt-io B423 read -> RunTS", "P"),
        ("mt_io.lemi.lemi423", "LEMI423Reader._read_one", "mt-io: one file (header + read_dataframe)", "D"),
        ("mt_io.lemi.lemi423", "Read_Lemi_Data.read_dataframe",
         "mt-io: read_dataframe (fromfile, DataFrame, time index, sort)", "D"),
        ("mt_io.lemi.lemi423", "LEMI423Reader._build_station_metadata", "mt-io: metadata", "D"),
        ("mt_io.lemi.lemi423", "LEMI423Reader._build_run_metadata", "mt-io: metadata", "D"),
        ("mt_io.lemi.lemi423", "LEMI423Reader._get_channel_metadata", "mt-io: metadata", "D"),
        ("mt_io.lemi.lemi423", "read_lemi_coil_response", "mt-io: metadata", "D"),
        ("mt_timeseries", "ChannelTS.__init__", "mt_timeseries: ChannelTS()", "D"),
        ("mt_timeseries", "RunTS.__init__", "mt_timeseries: RunTS()", "D"),
        ("mtproc.ingest", "_keep_channels", "channels / E sign / h_scale (ours)", "P"),
        ("mtproc.ingest", "_standardise_e_orientation", "channels / E sign / h_scale (ours)", "P"),
        ("mtproc.ingest", "_apply_h_scale", "channels / E sign / h_scale (ours)", "P"),
        ("mth5.groups", "RunGroup.from_runts", "mth5 write run (from_runts)", "P"),
        ("mth5.groups", "RunGroup.add_channel", "mth5: add_channel", "D"),
    ],
    "variant": [
        ("mtproc.ingest", "archive_filter_kinds", "raw archive check", "P"),
        ("mth5.groups", "RunGroup.to_runts", "mth5 read run (to_runts)", "P"),
        ("mtproc.ingest", "apply_filters_arrays", "filters (apply_filters_arrays, ours)", "P"),
        ("mth5.groups", "RunGroup.from_runts", "mth5 write run (from_runts)", "P"),
        ("mth5.groups", "RunGroup.add_channel", "mth5: add_channel", "D"),
    ],
    "stack": [
        ("mtproc.virtual", "_open_members", "open members (processing_archive)", "P"),
        ("mtproc.virtual", "processing_archive", "processing_archive", "D"),
        ("mtproc.virtual", "_mean_stack", "stack: mean (h5py chunk reads)", "P"),
        ("mtproc.virtual", "_coherence_stack", "stack: coherence-weighted", "P"),
        ("mth5.groups", "RunGroup.add_channel", "mth5 write coil", "P"),
    ],
    "read": [],
}
TARGETS["rr"] += READ_DETAILS
TARGETS["variant"] += READ_DETAILS
TARGETS["read"] += READ_DETAILS
TARGETS["cprofile"] = TARGETS["tracemalloc"] = []

# ----------------------------------------------------------------- child side

_LEVEL = [0]
_BAND = [None]  # centre period (s) of the band aurora's regression is on (the trace stage's band spans)
_SINKS: list = []  # in-process consumers of every main-thread mark: sink(flag, kind, name, epoch) (trace stage)
_MAIN_TID = threading.get_ident()


def _mark(flag: str, kind: str, name: str) -> None:
    t = time.time()
    sys.__stderr__.write(f"{MARK} {t:.6f} {flag} {kind} {name}\n")
    sys.__stderr__.flush()
    if _SINKS and threading.get_ident() == _MAIN_TID:
        for sink in _SINKS:
            sink(flag, kind, name, t)


class phase:
    """`with phase("name"):` -- a P mark pair around a block (the read benchmarks)."""

    def __init__(self, name: str, kind: str = "P"):
        self.name, self.kind = name, kind

    def __enter__(self):
        self.t0 = time.perf_counter()
        _mark("B", self.kind, self.name)
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0
        _mark("E", self.kind, self.name)
        return False


def _result(name: str, seconds: float, nbytes: float = 0.0, **extra) -> None:
    """One `PROFRESULT {json}` line: a read benchmark's number, collected into <stem>_bench.csv."""
    row = {"name": name, "seconds": round(seconds, 4), "MB": round(nbytes / MB, 1),
           "MB_per_s": round(nbytes / MB / seconds, 1) if seconds > 0 and nbytes else None,
           "rss_gib": round(psutil.Process().memory_info().rss / GIB, 2), **extra}
    sys.__stderr__.write(f"{RESULT} {json.dumps(row, default=str)}\n")
    sys.__stderr__.flush()


def _wrap(fn, label: str, kind: str):
    try:
        params = list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        params = []
    i_level = params.index("i_dec_level") if "i_dec_level" in params else None
    i_band = params.index("band") if "band" in params else None

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if i_level is not None:
            level = kwargs.get("i_dec_level", args[i_level] if len(args) > i_level else None)
            if level is not None:
                _LEVEL[0] = int(level)
        if i_band is not None:
            band = kwargs.get("band", args[i_band] if len(args) > i_band else None)
            if hasattr(band, "center_period"):
                _BAND[0] = float(band.center_period)
        name = label(_LEVEL[0]) if callable(label) else label.replace("{L}", str(_LEVEL[0]))
        _mark("B", kind, name)
        try:
            return fn(*args, **kwargs)
        finally:
            _mark("E", kind, name)

    return wrapper


def install_markers(stage: str) -> list[str]:
    """Wrap every target of `stage` (plus COMMON) in place; returns what could not be found."""
    import importlib

    missing = []
    for module, qualname, label, kind in COMMON + TARGETS.get(stage, []):
        try:
            owner = importlib.import_module(module)
            parts = qualname.split(".")
            for part in parts[:-1]:
                owner = getattr(owner, part)
            attr = parts[-1]
            if isinstance(owner, type):
                raw = next((k.__dict__[attr] for k in owner.__mro__ if attr in k.__dict__), None)
                if raw is None:
                    raise AttributeError(attr)
                if isinstance(raw, staticmethod):
                    setattr(owner, attr, staticmethod(_wrap(raw.__func__, label, kind)))
                elif isinstance(raw, classmethod):
                    setattr(owner, attr, classmethod(_wrap(raw.__func__, label, kind)))
                else:
                    setattr(owner, attr, _wrap(raw, label, kind))
            else:
                setattr(owner, attr, _wrap(getattr(owner, attr), label, kind))
        except Exception as exc:  # a target renamed upstream: profile without it, say so
            missing.append(f"{module}:{qualname} ({type(exc).__name__}: {exc})")
    for m in missing:
        sys.__stderr__.write(f"PROFINFO marker not installed: {m}\n")
    return missing


def openblas_threads() -> dict:
    """OpenBLAS thread-pool sizes of numpy's and scipy's own copies (ctypes; no threadpoolctl here)."""
    import ctypes
    import glob

    import scipy

    out = {}
    for pkg in (np, scipy):
        for dll in glob.glob(str(Path(pkg.__file__).parent) + ".libs/*openblas*.dll"):
            lib = ctypes.CDLL(dll)
            for fn in ("scipy_openblas_get_num_threads64_", "scipy_openblas_get_num_threads",
                       "openblas_get_num_threads64_", "openblas_get_num_threads"):
                if hasattr(lib, fn):
                    out[f"{pkg.__name__}:{Path(dll).name[:24]}"] = int(getattr(lib, fn)())
                    break
    return out


def redirect_archives(directory: str, sites) -> None:
    """`sites`' raw archive and variant are looked up in `directory` (read there, never written)."""
    import mtproc.ingest as ing

    directory, sites = Path(directory), set(sites)
    raw_path, var_path = ing.default_archive_path, ing.variant_path

    def default_archive_path(survey, site_name, ignore_filters=False):
        path = raw_path(survey, site_name, ignore_filters)
        return directory / path.name if site_name in sites else path

    def variant_path(survey, site_name):
        path = var_path(survey, site_name)
        return directory / path.name if site_name in sites else path

    ing.default_archive_path, ing.variant_path = default_archive_path, variant_path
    sys.__stderr__.write(f"PROFINFO archives of {sorted(sites)} read from {directory}\n")


def child_env(first=()) -> dict:
    """A child's environment: PYTHONPATH = `first` (e.g. a stock aurora checkout), this repo's src,
    then the caller's own PYTHONPATH entries -- a fork clone put there reaches the child -- and
    unbuffered output."""
    caller = [e for e in os.environ.get("PYTHONPATH", "").split(os.pathsep) if e]
    path = list(dict.fromkeys([*map(str, first), str(REPO / "src"), *caller]))
    return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": os.pathsep.join(path)}


def package_origins(names=("aurora", "mth5", "mt_timeseries", "mt_metadata", "mt_io")) -> dict:
    """Where each MT package would be imported from, found without importing it."""
    import importlib.util

    out = {}
    for name in names:
        try:
            found = importlib.util.find_spec(name)
            out[name] = str(Path(found.origin).parent) if found and found.origin else None
        except Exception as exc:
            out[name] = f"{type(exc).__name__}: {exc}"
    return out


def child_main(stage: str, spec_path: str) -> int:
    # first lines of every stage log: which packages this child runs
    sys.__stderr__.write(f"PROFINFO PYTHONPATH={os.environ.get('PYTHONPATH', '')}\n")
    sys.__stderr__.write(f"PROFINFO packages {package_origins()}\n")
    sys.__stderr__.flush()
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    sys.path.insert(0, str(SCRIPTS))
    if spec.get("read_archives"):
        redirect_archives(spec["read_archives"], spec.get("read_sites") or [])
    env = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}
    try:
        blas = openblas_threads()
    except Exception as exc:
        blas = {"error": str(exc)}
    sys.__stderr__.write(f"PROFINFO pid {os.getpid()} stage {stage} env {env} openblas {blas}\n")
    if spec.get("markers", True) and stage != "trace":  # trace_child installs its own after its imports
        install_markers(stage)
    if stage in ("rr", "ingest", "stack"):
        script = {"rr": "process_rr.py", "ingest": "ingest_site.py", "stack": "build_stack.py"}[stage]
        import runpy

        sys.argv = [str(SCRIPTS / script), *spec["argv"]]
        runpy.run_path(str(SCRIPTS / script), run_name="__main__")
        return 0
    if stage == "variant":
        from mtproc.ingest import build_variant
        from mtproc.survey import Survey

        out = build_variant(Survey.from_yaml(spec["survey"]), spec["site"])
        print(f"variant: {out}", flush=True)
        return 0
    if stage == "read":
        bench_read(spec)
        return 0
    if stage in ("cprofile", "tracemalloc"):
        inprocess_rr(spec, stage)
        return 0
    if stage == "trace":
        trace_child(spec)
        return 0
    raise SystemExit(f"unknown child stage {stage}")


# ------------------------------------------------------ in-process rr (cProfile / tracemalloc)

def _rr_call(spec: dict):
    """process_rr.main's own resolution, then the arguments it hands `process_station`."""
    import process_rr as pr

    from mtproc.bands import lemimt_band_scheme
    from mtproc.ingest import processing_archive
    from mtproc.masks import load_masks

    args = pr.build_parser().parse_args(spec["argv"])
    started = dt.datetime.now().astimezone()
    res = pr.resolve(args, started)
    survey = res["survey"]
    local_h5 = processing_archive(survey, args.local)
    remote_h5 = res["remote_archive"] if res["virtual_remote"] else processing_archive(survey, args.remote)
    scheme = lemimt_band_scheme(survey.sample_rate, **res["scheme_kwargs"])
    masks = load_masks(survey, args.local)
    kwargs = dict(out_dir=survey.workspace / "tf", band_scheme=scheme, start=args.start, end=args.end,
                  tag=res["stem"], tweaks=res["tweaks"] or None, time_masks=masks or None)
    if res["output_channels"]:
        kwargs["output_channels"] = res["output_channels"]
    return (local_h5, args.local, remote_h5, args.remote), kwargs


class PeakSnapper(threading.Thread):
    """A tracemalloc snapshot each time this process's RSS passes its last snapshot's by `step`."""

    def __init__(self, step_gib: float = 2.0, interval: float = 0.5, top: int = 20, path: Path | None = None):
        super().__init__(daemon=True)
        self.step, self.interval, self.top, self.path = step_gib * GIB, interval, top, path
        self.stop = threading.Event()
        self.best_rss, self.report, self.n_snaps, self.snap_seconds = 0.0, "", 0, 0.0

    def run(self):
        import tracemalloc

        proc = psutil.Process()
        while not self.stop.is_set():
            rss = proc.memory_info().rss
            if rss > self.best_rss + self.step:
                t0 = time.perf_counter()
                snap = tracemalloc.take_snapshot()
                traced, traced_peak = tracemalloc.get_traced_memory()
                self.report = format_snapshot(snap, rss, traced, traced_peak, self.top)
                del snap
                if self.path is not None:  # the latest one survives a killed run
                    self.path.write_text(self.report + "\n", encoding="utf-8")
                self.best_rss = rss
                self.n_snaps += 1
                self.snap_seconds += time.perf_counter() - t0
                _mark("B", "D", "tracemalloc snapshot")
                _mark("E", "D", "tracemalloc snapshot")
            self.stop.wait(self.interval)


def _short(filename: str) -> str:
    f = filename.replace("\\", "/")
    for key in ("site-packages/", "/src/", "/scripts/", "/tests/"):
        if key in f:
            return f.split(key, 1)[1]
    for pkg in ("aurora", "mth5", "mt_timeseries", "mt_metadata", "mt_io"):  # a checkout on PYTHONPATH
        if f"/{pkg}/" in f:
            return pkg + "/" + f.split(f"/{pkg}/", 1)[1]
    return f


def format_snapshot(snap, rss: float, traced: float, traced_peak: float, top: int) -> str:
    stats = snap.statistics("traceback")
    lines = [f"snapshot at {dt.datetime.now():%H:%M:%S}: RSS {rss / GIB:.2f} GiB, traced now "
             f"{traced / GIB:.2f} GiB (traced peak so far {traced_peak / GIB:.2f} GiB)",
             f"top {top} allocation sites alive (by traceback; innermost frame first):"]
    for i, st in enumerate(stats[:top], 1):
        # the allocating line, then the first frames in the MT packages (who asked for it)
        chain = [f"{_short(fr.filename)}:{fr.lineno}" for fr in reversed(st.traceback)]
        ours = [f for f in chain[1:] if f.startswith(("aurora", "mth5", "mt_timeseries", "mt_metadata", "mtproc"))]
        frames = chain[:1] + (ours[:4] or chain[1:5])
        lines.append(f"{i:3d}. {st.size / GIB:7.3f} GiB in {st.count:7d} block(s)  " + "  <-  ".join(frames))
    by_line = snap.statistics("lineno")
    lines.append(f"\ntop {top} by innermost line:")
    for i, st in enumerate(by_line[:top], 1):
        fr = st.traceback[0]
        lines.append(f"{i:3d}. {st.size / GIB:7.3f} GiB in {st.count:7d} block(s)  {_short(fr.filename)}:{fr.lineno}")
    return "\n".join(lines)


def inprocess_rr(spec: dict, mode: str) -> None:
    from mtproc.process import process_station

    call_args, kwargs = _rr_call(spec)
    stem = Path(spec["out_stem"])
    t_wall = time.perf_counter()
    if mode == "cprofile":
        import cProfile
        import io
        import pstats

        prof = cProfile.Profile()
        with phase("process_station under cProfile"):
            prof.enable()
            try:
                process_station(*call_args, **kwargs)
            finally:
                prof.disable()
        wall = time.perf_counter() - t_wall
        prof.dump_stats(str(stem) + "_cprofile.prof")
        buf = io.StringIO()
        buf.write(f"cProfile of mtproc.process.process_station{call_args} -- {wall:.1f} s wall "
                  f"({dt.datetime.now():%Y-%m-%d %H:%M})\n")
        for key in ("cumulative", "tottime"):
            buf.write(f"\n===== top 40 by {key} =====\n")
            pstats.Stats(prof, stream=buf).strip_dirs().sort_stats(key).print_stats(40)
        Path(str(stem) + "_cprofile.txt").write_text(buf.getvalue(), encoding="utf-8")
        print(f"cprofile: {stem}_cprofile.txt ({wall:.1f} s)", flush=True)
        return
    # Traced from the level-0 STFTs to the end of the level-0 merge only, where the peak is:
    # tracing the whole run made the metadata-heavy start (kernel dataset, to_runts) crawl
    # (0.5 GiB after 3 min). What was allocated before -- the level-0 time series
    # the kernel dataset holds -- is untraced: the header gives the RSS at the start of tracing.
    import tracemalloc

    import aurora.pipelines.process_mth5 as apm

    nframe = int(spec.get("nframe", 12))
    snapper = PeakSnapper(step_gib=float(spec.get("snap_step_gib", 2.0)),
                          path=Path(str(stem) + "_tracemalloc.txt"))
    state = {"on": False, "rss0": 0.0, "t0": 0.0, "t1": 0.0}
    get_spectrograms, merge_stfts = apm.get_spectrograms, apm.merge_stfts

    def traced_spectrograms(tfk, i_dec_level, *args, **kw):
        if i_dec_level == 0 and not state["on"] and not state["t1"]:
            state.update(on=True, rss0=psutil.Process().memory_info().rss, t0=time.perf_counter())
            snapper.best_rss = state["rss0"]
            tracemalloc.start(nframe)
            snapper.start()
        return get_spectrograms(tfk, i_dec_level, *args, **kw)

    def traced_merge(*args, **kw):
        try:
            return merge_stfts(*args, **kw)
        finally:
            if state["on"]:
                snapper.stop.set()
                snapper.join()
                tracemalloc.stop()
                state.update(on=False, t1=time.perf_counter())

    apm.get_spectrograms, apm.merge_stfts = traced_spectrograms, traced_merge
    with phase("process_station, level-0 STFT + merge under tracemalloc"):
        process_station(*call_args, **kwargs)
    wall = time.perf_counter() - t_wall
    peak_wset = getattr(psutil.Process().memory_info(), "peak_wset", 0)
    head = (f"tracemalloc (nframe {nframe}) of process_station{call_args}: {wall:.1f} s wall; traced from the "
            f"first level-0 get_spectrograms to the end of the level-0 merge_stfts ({state['t1'] - state['t0']:.1f} s), "
            f"RSS {state['rss0'] / GIB:.2f} GiB when tracing started (untraced: the level-0 time series and what "
            f"else was allocated before); {snapper.n_snaps} snapshot(s) taking {snapper.snap_seconds:.1f} s; process "
            f"peak working set {peak_wset / GIB:.2f} GiB. The report is the last snapshot, taken when the RSS last "
            f"passed its previous high by {spec.get('snap_step_gib', 2.0)} GiB\n\n")
    Path(str(stem) + "_tracemalloc.txt").write_text(head + snapper.report + "\n", encoding="utf-8")
    print(f"tracemalloc: {stem}_tracemalloc.txt ({wall:.1f} s)", flush=True)


# ------------------------------------------------------------- read benchmarks (child)

def bench_read(spec: dict) -> None:
    """MTH5 opens, the channel summary, h5py vs mth5 slices, to_runts, RunSummary + KernelDataset,
    B423 files through numpy vs mt-io -- every step a phase and a PROFRESULT line."""
    import gc

    import h5py
    from mth5.mth5 import MTH5

    from mtproc.ingest import _group_contiguous, processing_archive, select_files
    from mtproc.survey import Survey
    from mtproc.timefreq import _real_runs

    survey = Survey.from_yaml(spec["survey"])
    local, remote = spec["local"], spec["remote"]
    path = Path(processing_archive(survey, local))
    size = path.stat().st_size
    hours = float(spec.get("window_hours", 2.0))

    with phase("mth5 open (r)") as p:
        m = MTH5()
        m.open_mth5(path, mode="r")
    _result("mth5 open (r)", p.seconds, archive=path.name, archive_GB=round(size / 1e9, 2))
    with phase("mth5 channel_summary.to_dataframe (r)") as p:
        cs = m.channel_summary.to_dataframe()
    _result("channel_summary.to_dataframe (r)", p.seconds, rows=len(cs))
    survey_name = m.surveys_group.groups_list[0]
    with phase("mth5 get_station + run list") as p:
        station = m.get_station(local, survey=survey_name)
        runs = _real_runs(station)
    _result("get_station + _real_runs", p.seconds, runs=len(runs))
    run_id, r_start, r_end = max(runs, key=lambda r: (r[2] - r[1]))
    with phase("mth5 get_run + get_channel hx") as p:
        run = station.get_run(run_id)
        ch = run.get_channel("hx")
    _result("get_run + get_channel (metadata objects)", p.seconds)
    ds = ch.hdf5_dataset
    fs = float(ch.metadata.sample_rate)
    n = int(ds.shape[0])
    n_win = int(hours * 3600 * fs)
    i0 = n // 2
    w0 = pd.Timestamp(str(ch.metadata.time_period.start)) + pd.Timedelta(seconds=i0 / fs)
    w1 = w0 + pd.Timedelta(seconds=(n_win - 1) / fs)
    group = ds.name.rsplit("/", 1)[0]
    m.close_mth5()

    # (a) h5py alone, as mtproc.virtual and the GUI's segment loader read
    with phase("h5py open + slice hx 2 h") as p:
        with h5py.File(path, "r") as f:
            a = f[group]["hx"][i0:i0 + n_win]
    _result(f"h5py slice hx {hours:g} h", p.seconds, a.nbytes, dtype=str(a.dtype), chunks=str(f"{group}"))
    del a
    with phase("h5py open + read hx whole run") as p:
        with h5py.File(path, "r") as f:
            a = f[group]["hx"][:]
    _result(f"h5py read hx whole run ({n / fs / 3600:.1f} h)", p.seconds, a.nbytes, dtype=str(a.dtype))
    del a
    gc.collect()

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(local, survey=survey_name).get_run(run_id)
        ch = run.get_channel("hx")
        # (b) mth5 ChannelDataset.time_slice -> ChannelTS (xarray with a time index)
        with phase("mth5 time_slice hx 2 h") as p:
            cts = ch.time_slice(start=str(w0), end=str(w1))
        _result(f"mth5 time_slice hx {hours:g} h", p.seconds, cts.ts.nbytes,
                samples=int(cts.ts.size), index_MB=round(cts.data_array.time.nbytes / MB, 1))
        del cts
        rss0 = psutil.Process().memory_info().rss
        with phase("mth5 time_slice hx whole run") as p:
            cts = ch.time_slice(start=str(r_start), end=str(r_end))
        held = psutil.Process().memory_info().rss - rss0
        _result("mth5 time_slice hx whole run", p.seconds, cts.ts.nbytes, samples=int(cts.ts.size),
                index_MB=round(cts.data_array.time.nbytes / MB, 1), rss_held_GiB=round(held / GIB, 2))
        del cts
        gc.collect()
        # (c) RunGroup.to_runts, the way aurora reads a run: every channel, one xarray Dataset
        with phase("mth5 to_runts 2 h") as p:
            rts = run.to_runts(start=str(w0), end=str(w1))
        _result(f"mth5 to_runts {hours:g} h ({len(rts.dataset.data_vars)} ch)", p.seconds,
                sum(v.nbytes for v in rts.dataset.data_vars.values()))
        del rts
        gc.collect()
        rss0 = psutil.Process().memory_info().rss
        with phase("mth5 to_runts whole run") as p:
            rts = run.to_runts()
        held = psutil.Process().memory_info().rss - rss0
        data_b = sum(v.nbytes for v in rts.dataset.data_vars.values())
        _result(f"mth5 to_runts whole run ({len(rts.dataset.data_vars)} ch)", p.seconds, data_b,
                dtypes=sorted({str(v.dtype) for v in rts.dataset.data_vars.values()}),
                index_MB=round(rts.dataset.time.nbytes / MB, 1), rss_held_GiB=round(held / GIB, 2))
        with phase("RunTS.dataset.to_array('channel') (as mth5 KernelDataset)") as p:
            arr = rts.dataset.to_array("channel")
        _result("RunTS.dataset.to_array('channel')", p.seconds, arr.nbytes)
        del arr, rts
        gc.collect()
    finally:
        m.close_mth5()

    # (d) RunSummary + KernelDataset for the pair, exactly as mtproc.process builds them
    from mtproc.process import kernel_dataset

    remote_h5 = processing_archive(survey, remote)
    opens = []
    original = MTH5.open_mth5

    def counting(self, filename=None, mode="a", **kw):
        opens.append((Path(str(filename)).name, mode))
        return original(self, filename, mode, **kw)

    MTH5.open_mth5 = counting
    try:
        with phase("RunSummary + KernelDataset (pair)") as p:
            kd = kernel_dataset(path, local, remote_h5, remote)
    finally:
        MTH5.open_mth5 = original
    _result("RunSummary.from_mth5s + KernelDataset.from_run_summary (pair)", p.seconds,
            opens=len(opens), open_list="; ".join(f"{n}:{md}" for n, md in opens), rows=len(kd.df))
    del kd

    # (3) a read-write open, only on a dedicated archive (never a hard link shared with another)
    rw = spec.get("rw_archive")
    if rw and Path(rw).exists():
        rw = Path(rw)
        if os.stat(rw).st_nlink != 1:
            print(f"read-write open skipped: {rw} has {os.stat(rw).st_nlink} links", flush=True)
        else:
            for mode in ("r", "a"):
                with phase(f"mth5 open ({mode}) own archive") as p:
                    m = MTH5()
                    m.open_mth5(rw, mode=mode)
                _result(f"mth5 open ({mode}) {rw.name}", p.seconds, archive_GB=round(rw.stat().st_size / 1e9, 2))
                if mode == "a":
                    with phase("mth5 channel_summary.summarize (a)") as p:
                        m.channel_summary.summarize()
                    _result("channel_summary.summarize() (a)", p.seconds)
                with phase(f"mth5 close ({mode}) own archive") as p:
                    m.close_mth5()
                _result(f"mth5 close ({mode})", p.seconds)

    # B423: numpy alone vs mt-io's per-file reader, on the same (by now cached) files
    site = spec.get("b423_site")
    if site and site in survey.site_dirs():
        from mt_io.lemi.lemi423 import Read_Lemi_Data

        files = select_files(survey.site_dirs()[site])
        biggest = max(_group_contiguous(files, 34), key=len)
        nbytes = sum(f.stat().st_size for f in biggest)
        with phase("B423 read into cache (numpy, 1st pass)") as p:
            for f in biggest:
                np.fromfile(f, dtype=Read_Lemi_Data.binary_format, offset=1024)
        _result(f"B423 numpy fromfile, 1st pass ({len(biggest)} files)", p.seconds, nbytes)
        with phase("B423 numpy fromfile (records)") as p:
            for f in biggest:
                np.fromfile(f, dtype=Read_Lemi_Data.binary_format, offset=1024)
        _result(f"B423 numpy fromfile, cached ({len(biggest)} files)", p.seconds, nbytes)
        with phase("B423 mt-io read_dataframe per file") as p:
            for f in biggest:
                Read_Lemi_Data(f, {}).read_dataframe()
        _result(f"B423 mt-io read_dataframe, cached ({len(biggest)} files)", p.seconds, nbytes)


# ------------------------------------------------------------------ HDF5 layout

def h5_layout(path: Path, raw_bytes: float | None = None) -> pd.DataFrame:
    """One row per data array of `path`: dtype, chunk shape/bytes, compression, stored vs in-memory float64."""
    import h5py

    rows = []
    with h5py.File(path, "r") as f:
        def visit(name, obj):
            if isinstance(obj, h5py.Dataset) and obj.ndim == 1 and obj.size > 100000:
                rows.append({
                    "archive": Path(path).name, "dataset": name.split("Stations/")[-1], "samples": obj.size,
                    "dtype": str(obj.dtype), "chunk_samples": obj.chunks[0] if obj.chunks else None,
                    "chunk_kB": round(obj.chunks[0] * obj.dtype.itemsize / 1e3, 1) if obj.chunks else None,
                    "compression": obj.compression, "shuffle": obj.shuffle,
                    "stored_MB": round(obj.id.get_storage_size() / MB, 1),
                    "float64_MB": round(obj.size * 8 / MB, 1)})
        f.visititems(visit)
    df = pd.DataFrame(rows)
    df.attrs["file_MB"] = Path(path).stat().st_size / MB
    if raw_bytes:
        df.attrs["raw_MB"] = raw_bytes / MB
    return df


# ---------------------------------------------------------------- sampler (parent)

def run_sampled(cmd: list[str], log_path: Path, interval: float = 0.5, env=None, on_spawn=None):
    """Run `cmd` with stdout+stderr to `log_path`, sampling it every `interval` s; (samples, t_spawn, t_end, rc).

    `on_spawn(pid)`, if given, runs in a thread beside the sampling and returns the
    processes it started (py-spy attached to the child), waited for once the child exits.
    """
    rows = []
    helpers: list = []
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        t_spawn = time.time()
        child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO), env=env)
        hook = None
        if on_spawn is not None:
            hook = threading.Thread(target=lambda: helpers.extend(on_spawn(child.pid) or []), daemon=True)
            hook.start()
        try:
            proc = psutil.Process(child.pid)
            proc.cpu_percent(None)
        except psutil.Error:
            proc = None
        psutil.cpu_percent(None)
        nxt = time.time()
        while True:
            rc = child.poll()
            row = {"t": time.time()}
            if proc is not None:
                try:
                    with proc.oneshot():
                        mi = proc.memory_info()
                        row.update(rss=mi.rss, private=getattr(mi, "private", mi.vms),
                                   peak_wset=getattr(mi, "peak_wset", 0), cpu=proc.cpu_percent(None),
                                   threads=proc.num_threads())
                        io = proc.io_counters()
                        row.update(p_read=io.read_bytes, p_write=io.write_bytes)
                    for kid in proc.children(recursive=True):
                        try:
                            row["rss"] += kid.memory_info().rss
                        except psutil.Error:
                            pass
                except psutil.Error:
                    pass
            d = psutil.disk_io_counters()
            vm = psutil.virtual_memory()
            row.update(d_read=d.read_bytes, d_write=d.write_bytes, m_used=vm.total - vm.available,
                       m_total=vm.total, m_cpu=psutil.cpu_percent(None))
            rows.append(row)
            if rc is not None:
                break
            nxt += interval
            time.sleep(max(0.0, nxt - time.time()))
        t_end = time.time()
    if hook is not None:
        hook.join(timeout=60)
    for h in helpers:
        try:
            h.wait(timeout=300)
        except subprocess.TimeoutExpired:
            h.kill()
    return pd.DataFrame(rows), t_spawn, t_end, rc


def wait_for_memory(need_gib: float, other_peak_gib: float = 62.0, young_min: float = 4.0,
                    poll_s: float = 15.0, log=functools.partial(print, flush=True)) -> None:
    """Block until available memory less the growth still ahead of young process_rr.py children >= need_gib."""
    if need_gib <= 0:
        return
    last = 0.0
    while True:
        avail = psutil.virtual_memory().available / GIB
        reserve, young = 0.0, 0
        for p in psutil.process_iter(["pid", "cmdline", "create_time", "memory_info"]):
            try:
                cmd = " ".join(p.info["cmdline"] or [])
                if "process_rr.py" in cmd and "profile_run.py" not in cmd and p.info["pid"] != os.getpid():
                    if (time.time() - p.info["create_time"]) / 60.0 < young_min:
                        young += 1
                        reserve += max(0.0, other_peak_gib - p.info["memory_info"].rss / GIB)
            except (psutil.Error, TypeError):
                pass
        if avail - reserve >= need_gib:
            log(f"memory gate: {avail:.1f} GiB available, {reserve:.1f} GiB held back for {young} young "
                f"process_rr.py job(s): need {need_gib:.0f} GiB -- starting")
            return
        if time.time() - last > 120:
            log(f"memory gate: {avail:.1f} GiB available, {reserve:.1f} GiB held back for {young} young "
                f"process_rr.py job(s): need {need_gib:.0f} GiB -- waiting")
            last = time.time()
        time.sleep(poll_s)


# ------------------------------------------------------------------- log parsing

ANSI = re.compile(r"\x1b\[[0-9;]*m")
LOGURU = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?) \| (\w+)\s*\| "
                    r"([\w.<>]+) \| (\w+|<module>) \| line: \d+ \| (.*)$")
MARK_RE = re.compile(rf"^{MARK} (\d+\.\d+) ([BE]) ([PD]) (.+)$")
HEADER = re.compile(r"^=== (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}) ")
STARTED = re.compile(r"^started: (\d{4}-\d{2}-\d{2}T\S+)$")


def _epoch(text: str) -> float:
    return dt.datetime.fromisoformat(text.replace(" ", "T", 1)).timestamp()


def parse_log(text: str) -> list[dict]:
    """Every timed line of a child log: {"type": mark|log|started|header|result, "t", ...}, in file order."""
    events = []
    for raw in text.splitlines():
        line = ANSI.sub("", raw).rstrip()
        m = MARK_RE.match(line)
        if m:
            events.append({"type": "mark", "t": float(m[1]), "flag": m[2], "kind": m[3], "name": m[4]})
            continue
        m = LOGURU.match(line)
        if m:
            events.append({"type": "log", "t": _epoch(m[1]), "level": m[2], "module": m[3],
                           "function": m[4], "msg": m[5]})
            continue
        if line.startswith(RESULT + " "):
            events.append({"type": "result", "t": None, "row": json.loads(line[len(RESULT) + 1:])})
            continue
        m = STARTED.match(line)
        if m:
            events.append({"type": "started", "t": _epoch(m[1])})
            continue
        m = HEADER.match(line)
        if m:
            events.append({"type": "header", "t": _epoch(m[1])})
    return events


def mark_intervals(events: list[dict]) -> list[dict]:
    """B/E mark pairs -> [{"name", "kind", "t0", "t1", "depth"}]; an E closes the latest open B of its name."""
    stack, out = [], []
    for e in events:
        if e["type"] != "mark":
            continue
        if e["flag"] == "B":
            stack.append({"name": e["name"], "kind": e["kind"], "t0": e["t"], "depth": len(stack)})
        else:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i]["name"] == e["name"]:
                    iv = stack.pop(i)
                    iv["t1"] = e["t"]
                    out.append(iv)
                    break
    return sorted(out, key=lambda iv: iv["t0"])


def phases_from_marks(intervals: list[dict], t_start: float, t_end: float, min_s: float = 0.05) -> list[dict]:
    """Partition [t_start, t_end] by the P intervals: each instant goes to the innermost P interval
    covering it; uncovered time is "python start + imports" (before the first), "exit" (after the
    last) or "(untracked)"; pieces shorter than `min_s` fold into the piece before them."""
    ps = [iv for iv in intervals if iv["kind"] == "P"]
    cuts = sorted({t_start, t_end, *[iv["t0"] for iv in ps], *[iv["t1"] for iv in ps]})
    cuts = [c for c in cuts if t_start <= c <= t_end]
    first = min((iv["t0"] for iv in ps), default=t_end)
    last = max((iv["t1"] for iv in ps), default=t_start)
    pieces = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b <= a:
            continue
        mid = 0.5 * (a + b)
        cover = [iv for iv in ps if iv["t0"] <= mid < iv["t1"]]
        if cover:
            name = max(cover, key=lambda iv: (iv["depth"], iv["t0"]))["name"]
        else:
            name = "python start + imports" if mid < first else ("exit" if mid > last else "(untracked)")
        if pieces and pieces[-1]["name"] == name:
            pieces[-1]["t1"] = b
        else:
            pieces.append({"name": name, "t0": a, "t1": b})
    merged = []
    for pc in pieces:
        if merged and (pc["t1"] - pc["t0"] < min_s or merged[-1]["name"] == pc["name"]):
            merged[-1]["t1"] = pc["t1"]
        else:
            merged.append(dict(pc))
    return merged


def phases_from_rr_log(events: list[dict], t_start: float | None, t_end: float | None) -> list[dict]:
    """A bare process_rr log (no marks) split at the lines aurora and process_rr themselves log."""
    logs = [e for e in events if e["type"] == "log"]
    if not logs:
        return []
    started = next((e["t"] for e in events if e["type"] == "started"), None)
    t_start = t_start if t_start is not None else next(
        (e["t"] for e in events if e["type"] == "header"), logs[0]["t"])
    t_end = max(t_end or 0.0, logs[-1]["t"])
    cps = [(t_start, "python start + imports")]
    if started:
        cps.append((started, "survey load + archive status"))
    level, stft_last = 0, None

    def add(t, name):
        if t >= cps[-1][0]:
            cps.append((t, name))

    for e in logs:
        msg, mod, fn = e["msg"], e["module"], e["function"]
        if mod == "__main__" and "Ex " in msg and "@" in msg and cps[-1][1].startswith(("python", "survey")):
            add(e["t"], "archives + run summary + kernel dataset + config")
        elif mod == "mtproc.process" and msg.startswith("aurora: "):
            add(e["t"], "aurora setup")
        elif fn == "valid_decimations":
            add(e["t"], "L0 read TS")
        elif "DECIMATION LEVEL" in msg:
            if stft_last is not None:
                stft_last = None
            level = int(msg.rsplit(" ", 1)[1])
            add(e["t"], f"L{level} decimate")
        elif "Dataset Dataframe Updated for decimation level" in msg:
            level = int(re.search(r"level (\d+)", msg)[1])
            add(e["t"], f"L{level} STFT")
        elif fn == "save_fourier_coefficients":
            stft_last = e["t"]
        elif fn == "extract_features":
            if stft_last is not None:
                add(stft_last, f"L{level} merge STFTs")
                stft_last = None
            add(e["t"], f"L{level} regression")
        elif "type(tf_cls)" in msg:
            add(e["t"], "close archives + EDI write")
        elif mod == "mtproc.process" and msg.startswith("wrote "):
            add(e["t"], "quadrants + comparison figure")
        elif mod == "__main__" and msg.startswith("wrote ") and msg.endswith(".png"):
            add(e["t"], "sidecar")
        elif mod == "__main__" and msg.startswith("wrote ") and msg.endswith(".json"):
            add(e["t"], "EDI INFO rewrite + exit")
    cps.append((t_end, None))
    return [{"name": n, "t0": a, "t1": b} for (a, n), (b, _) in zip(cps[:-1], cps[1:]) if b > a]


def details_table(intervals: list[dict]) -> pd.DataFrame:
    """Per D (and P) mark name: count, total seconds, self seconds (less directly nested marks)."""
    rows = {}
    for iv in intervals:
        kids = [k for k in intervals if k is not iv and k["depth"] == iv["depth"] + 1
                and k["t0"] >= iv["t0"] and k["t1"] <= iv["t1"]]
        dur = iv["t1"] - iv["t0"]
        r = rows.setdefault(iv["name"], {"name": iv["name"], "kind": iv["kind"], "count": 0,
                                         "total_s": 0.0, "self_s": 0.0})
        r["count"] += 1
        r["total_s"] += dur
        r["self_s"] += dur - sum(k["t1"] - k["t0"] for k in kids)
    df = pd.DataFrame(list(rows.values()))
    if not df.empty:
        df = df.sort_values("total_s", ascending=False)
        df[["total_s", "self_s"]] = df[["total_s", "self_s"]].round(3)
    return df


def _interp(samples: pd.DataFrame, col: str, t: float) -> float:
    s = samples.dropna(subset=[col])
    if s.empty:
        return float("nan")
    return float(np.interp(t, s["t"].to_numpy(), s[col].to_numpy(dtype=float)))


def phase_table(phases: list[dict], samples: pd.DataFrame | None, t0: float) -> pd.DataFrame:
    rows = []
    for ph in phases:
        row = {"phase": ph["name"], "start_s": round(ph["t0"] - t0, 2), "end_s": round(ph["t1"] - t0, 2),
               "seconds": round(ph["t1"] - ph["t0"], 2)}
        if samples is not None and not samples.empty and "rss" in samples:
            win = samples[(samples["t"] >= ph["t0"]) & (samples["t"] <= ph["t1"])]
            if win.empty:
                win = samples.iloc[[int(np.argmin(np.abs(samples["t"].to_numpy() - 0.5 * (ph["t0"] + ph["t1"]))))]]
            row.update(
                peak_rss_gib=round(win["rss"].max() / GIB, 2),
                mean_cpu_pct=round(win["cpu"].iloc[1:].mean() if len(win) > 1 else win["cpu"].mean(), 1),
                machine_cpu_pct=round(win["m_cpu"].mean(), 1),
                disk_read_mb=round((_interp(samples, "d_read", ph["t1"]) - _interp(samples, "d_read", ph["t0"])) / MB, 1),
                disk_write_mb=round((_interp(samples, "d_write", ph["t1"]) - _interp(samples, "d_write", ph["t0"])) / MB, 1),
                proc_read_mb=round((_interp(samples, "p_read", ph["t1"]) - _interp(samples, "p_read", ph["t0"])) / MB, 1),
                proc_write_mb=round((_interp(samples, "p_write", ph["t1"]) - _interp(samples, "p_write", ph["t0"])) / MB, 1),
            )
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ the figure

CATEGORIES = [  # (name, colour, test on the phase name), first match wins
    ("startup / untracked", "#bbbbbb", lambda n: n.startswith(("python start", "exit", "(untracked)"))),
    ("STFT", "#ff7f0e", lambda n: "STFT" in n and "merge" not in n),
    ("regression", "#d62728", lambda n: "regression" in n),
    ("read time series / files", "#2ca02c", lambda n: any(k in n for k in ("read", "B423", "to_runts", "slice",
                                                                          "time_slice", "open"))),
    ("decimate", "#bcbd22", lambda n: "decimate" in n),
    ("write archive / EDI", "#8c564b", lambda n: any(k in n for k in ("write", "close", "EDI"))),
    ("aurora other", "#9467bd", lambda n: any(k in n for k in ("aurora", "merge", "features", "stack:",
                                                                "summarize", "channel_summary"))),
    ("ours", "#1f77b4", lambda n: True),
]


def category(name: str) -> tuple[str, str]:
    for cat, colour, test in CATEGORIES:
        if test(name):
            return cat, colour
    return "ours", "#1f77b4"


def plot_timeline(samples: pd.DataFrame, phases: list[dict], t0: float, title: str, out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True, gridspec_kw={"height_ratios": [3, 2, 2]})
    x = samples["t"].to_numpy() - t0
    ax = axes[0]
    ax.plot(x, samples["m_used"] / GIB, color="0.55", lw=0.8, label="machine: memory in use")
    ax.plot(x, samples["rss"] / GIB, color="k", lw=1.6, label="this run: working set (RSS)")
    ax.plot(x, samples["private"] / GIB, color="k", lw=0.8, ls=":", label="this run: private bytes")
    ax.axhline(samples["m_total"].iloc[0] / GIB, color="0.3", lw=0.6, ls="--")
    ax.set_ylabel("memory (GiB)")
    ax.set_ylim(0, samples["m_total"].iloc[0] / GIB * 1.02)
    ax = axes[1]
    ax.plot(x, samples["m_cpu"] / 100.0 * psutil.cpu_count(), color="0.55", lw=0.8, label="machine")
    ax.plot(x, samples["cpu"] / 100.0, color="k", lw=1.2, label="this run")
    ax.set_ylabel(f"CPU (cores of {psutil.cpu_count()})")
    ax.set_ylim(0, psutil.cpu_count())
    ax2 = ax.twinx()
    ax2.plot(x, samples["threads"], color="tab:blue", lw=0.8, ls=":")
    ax2.set_ylabel("threads (dotted)", color="tab:blue")
    ax = axes[2]
    dtm = np.diff(samples["t"].to_numpy(), prepend=np.nan)
    for col, lab, sty in (("d_read", "machine disk read", dict(color="0.55", lw=0.8)),
                          ("d_write", "machine disk write", dict(color="0.55", lw=0.8, ls="--")),
                          ("p_read", "this run: read", dict(color="tab:green", lw=1.2)),
                          ("p_write", "this run: write", dict(color="tab:brown", lw=1.2))):
        rate = np.diff(samples[col].to_numpy(dtype=float), prepend=np.nan) / dtm / MB
        ax.plot(x, rate, label=lab, **sty)
    ax.set_ylabel("I/O (MB/s)")
    ax.set_yscale("symlog", linthresh=10)
    ax.set_xlabel("seconds since the child started")
    total = max(x[-1], 1e-9)
    seen = {}
    for ph in phases:
        cat, colour = category(ph["name"])
        seen[cat] = colour
        a, b = ph["t0"] - t0, ph["t1"] - t0
        for axx in axes:
            axx.axvspan(a, b, color=colour, alpha=0.16, lw=0)
            axx.axvline(a, color=colour, lw=0.4, alpha=0.6)
        if (b - a) / total >= 0.012:
            axes[0].text(0.5 * (a + b), axes[0].get_ylim()[1] * 0.985, f"{ph['name']}  {b - a:.0f} s",
                         rotation=90, va="top", ha="center", fontsize=7)
    handles = [Patch(color=c, alpha=0.35, label=k) for k, c in seen.items()]
    axes[0].legend(handles=axes[0].get_legend_handles_labels()[0] + handles, loc="center left",
                   bbox_to_anchor=(1.07, 0.5), fontsize=8)
    axes[1].legend(loc="center left", bbox_to_anchor=(1.07, 0.5), fontsize=8)
    axes[2].legend(loc="center left", bbox_to_anchor=(1.07, 0.5), fontsize=8)
    axes[0].set_title(title, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


# ------------------------------------------------------------------ orchestration

def _stem(stage: str, who: str) -> str:
    return f"{stage}_{who}_{dt.datetime.now():%Y%m%d-%H%M%S}"


def analyse(log_path: Path, samples: pd.DataFrame | None, t_spawn: float | None, t_end: float | None,
            out: Path, stem: str, stage: str, note: str = "") -> pd.DataFrame:
    """Log (+ samples) -> <stem>_phases.csv, _details.csv, _bench.csv and the timeline figure."""
    events = parse_log(log_path.read_text(encoding="utf-8", errors="replace"))
    intervals = mark_intervals(events)
    timed = [e["t"] for e in events if e["t"] is not None]
    t_start = t_spawn if t_spawn is not None else (min(timed) if timed else 0.0)
    t_stop = t_end if t_end is not None else (max(timed) if timed else t_start)
    if intervals:
        phases = phases_from_marks(intervals, t_start, t_stop)
    elif stage == "rr":
        phases = phases_from_rr_log(events, t_spawn, t_end)
    else:
        phases = [{"name": "(whole run)", "t0": t_start, "t1": t_stop}]
    table = phase_table(phases, samples, t_start)
    table.to_csv(out / f"{stem}_phases.csv", index=False)
    if intervals:
        details_table(intervals).to_csv(out / f"{stem}_details.csv", index=False)
    results = [e["row"] for e in events if e["type"] == "result"]
    if results:
        pd.DataFrame(results).to_csv(out / f"{stem}_bench.csv", index=False)
    if samples is not None and not samples.empty and "rss" in samples:
        samples.to_csv(out / f"{stem}_samples.csv", index=False)
        load = samples["m_used"].sub(samples["rss"]).mean() / GIB
        title = (f"{stem}: {t_stop - t_start:.0f} s, peak RSS {samples['rss'].max() / GIB:.1f} GiB "
                 f"(peak working set {samples['peak_wset'].max() / GIB:.1f} GiB), mean CPU "
                 f"{samples['cpu'].iloc[1:].mean() / 100:.2f} cores; rest of the machine: "
                 f"{load:.0f} GiB in use, {samples['m_cpu'].mean() / 100 * psutil.cpu_count():.1f} cores "
                 f"(all processes){note}")
        plot_timeline(samples, phases, t_start, title, out / f"{stem}_timeline.png")
    return table


def child_cmd(stage: str, spec: dict, spec_path: Path, markers: bool) -> list[str]:
    spec_path.write_text(json.dumps({**spec, "markers": markers}, default=str), encoding="utf-8")
    return [sys.executable, str(Path(__file__).resolve()), "--child", stage, str(spec_path)]


def run_stage(stage: str, spec: dict, out: Path, who: str, interval: float, markers: bool,
              need_gb: float, other_peak_gb: float, extra_note: str = "") -> dict:
    stem = _stem(stage, who)
    spec = {**spec, "out_stem": str(out / stem)}
    wait_for_memory(need_gb, other_peak_gb)
    others = [p for p in psutil.process_iter(["cmdline"])
              if "process_rr.py" in " ".join(p.info["cmdline"] or []) and "profile_run" not in
              " ".join(p.info["cmdline"] or [])]
    env = child_env()
    cmd = child_cmd(stage, spec, out / f"{stem}_spec.json", markers)
    print(f"[{dt.datetime.now():%H:%M:%S}] {stage}: {' '.join(cmd[-3:])} -> {out / stem}.log "
          f"({len(others)} other process_rr.py running)", flush=True)
    samples, t_spawn, t_end, rc = run_sampled(cmd, out / f"{stem}.log", interval, env)
    note = f"; {len(others)} campaign process_rr.py running at the start{extra_note}"
    table = analyse(out / f"{stem}.log", samples, t_spawn, t_end, out, stem, stage, note)
    print(f"[{dt.datetime.now():%H:%M:%S}] {stage}: exit {rc}, {t_end - t_spawn:.0f} s, peak RSS "
          f"{samples['rss'].max() / GIB:.1f} GiB -> {out / stem}_timeline.png", flush=True)
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(table.to_string(index=False), flush=True)
    return {"stem": stem, "rc": rc, "seconds": t_end - t_spawn, "table": table}


def parse_logs(paths: list[Path], out: Path) -> pd.DataFrame:
    """--parse-log: bare process_rr logs (campaign ones too) -> one row per phase per log."""
    frames = []
    for p in paths:
        events = parse_log(Path(p).read_text(encoding="utf-8", errors="replace"))
        phases = phases_from_rr_log(events, None, None)
        if not phases:
            continue
        t = phase_table(phases, None, phases[0]["t0"])
        t.insert(0, "log", Path(p).stem)
        frames.append(t)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df.to_csv(out / "parsed_phases.csv", index=False)
    print(f"parsed {len(frames)} log(s) -> {out / 'parsed_phases.csv'}")
    return df


def ledger_stats(campaign: Path, out: Path) -> None:
    """Per kind: seconds and peak RSS; from runs.log: slots in use over each stage block."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    led = pd.read_csv(campaign / "ledger.csv")
    led = led[pd.to_numeric(led["seconds"], errors="coerce").notna()].copy()
    led["seconds"] = led["seconds"].astype(float)
    led["peak_gib"] = pd.to_numeric(led["peak_rss_mb"], errors="coerce") / 1024.0
    q = lambda s, p: float(np.nanpercentile(s, p)) if len(s) else float("nan")  # noqa: E731
    rows = []
    for kind, g in led.groupby("kind"):
        rows.append({"kind": kind, "n": len(g), "status": dict(g["status"].value_counts()),
                     "seconds_min": g["seconds"].min(), "seconds_median": g["seconds"].median(),
                     "seconds_p90": q(g["seconds"], 90), "seconds_max": g["seconds"].max(),
                     "hours_total": round(g["seconds"].sum() / 3600, 2),
                     "peak_gib_min": round(g["peak_gib"].min(), 1), "peak_gib_median": round(g["peak_gib"].median(), 1),
                     "peak_gib_p90": round(q(g["peak_gib"], 90), 1), "peak_gib_max": round(g["peak_gib"].max(), 1)})
    stats = pd.DataFrame(rows)
    stats.to_csv(out / "ledger_stats.csv", index=False)

    lines = (campaign / "runs.log").read_text(encoding="utf-8", errors="replace").splitlines()
    ts = lambda s: pd.Timestamp(s[:19])  # noqa: E731
    blocks, runs, waits = [], {}, []
    for ln in lines:
        m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$", ln)
        if not m:
            continue
        t, msg = ts(m[1]), m[2]
        if msg.startswith("=== "):
            par = re.search(r"\((\d+) at a time\)", msg)
            blocks.append({"label": msg[4:].split(":")[0], "t0": t, "t1": t,
                           "parallel": int(par[1]) if par else 2, "jobs": 0})
        elif msg.startswith("START "):
            rid = msg.split()[1].rstrip(":")
            runs[rid] = {"run": rid, "start": t, "end": None}
            if blocks:
                blocks[-1]["jobs"] += 1
        elif msg.startswith(("DONE ", "FAILED ", "KILLED ", "INTERRUPTED ")):
            rid = msg.split()[1].rstrip(":")
            if rid in runs:
                runs[rid]["end"] = t
            if blocks:
                blocks[-1]["t1"] = t
        elif msg.startswith("slot waiting for memory"):
            waits.append(t)
    iv = pd.DataFrame([r for r in runs.values() if r["end"] is not None])
    slot_rows = []
    for b in blocks:
        if b["jobs"] == 0 or b["t1"] <= b["t0"]:
            continue
        grid = pd.date_range(b["t0"], b["t1"], freq="5s")
        busy = np.zeros(len(grid))
        for r in iv.itertuples():
            busy += (grid >= r.start) & (grid < r.end)
        dur = (b["t1"] - b["t0"]).total_seconds()
        slot_rows.append({"block": b["label"], "start": b["t0"], "end": b["t1"], "hours": round(dur / 3600, 2),
                          "jobs": b["jobs"], "parallel": b["parallel"],
                          "share_two_running": round(float(np.mean(busy >= 2)), 3),
                          "share_one_running": round(float(np.mean(busy == 1)), 3),
                          "share_none_running": round(float(np.mean(busy == 0)), 3),
                          "memory_wait_lines": sum(b["t0"] <= w <= b["t1"] for w in waits)})
    slots = pd.DataFrame(slot_rows)
    slots.to_csv(out / "ledger_slots.csv", index=False)

    fig, axes = plt.subplots(3, 1, figsize=(15, 10))
    kinds = sorted(led["kind"].unique())
    for ax, col, lab in ((axes[0], "seconds", "minutes per job"), (axes[1], "peak_gib", "peak RSS per job (GiB)")):
        data = [led.loc[led["kind"] == k, col].dropna() / (60.0 if col == "seconds" else 1.0) for k in kinds]
        ax.boxplot(data, orientation="horizontal", tick_labels=[f"{k} (n={len(d)})" for k, d in zip(kinds, data)], showfliers=False)
        for i, d in enumerate(data, 1):
            ax.plot(d, np.full(len(d), i) + np.random.default_rng(0).uniform(-0.15, 0.15, len(d)), ".", alpha=0.6)
        ax.set_xlabel(lab)
        ax.grid(alpha=0.3)
    axes[1].axvline(psutil.virtual_memory().total / GIB / 2, color="r", lw=0.8, ls="--",
                    label="half the machine's RAM")
    axes[1].legend(fontsize=8)
    ax = axes[2]
    if not iv.empty:
        grid = pd.date_range(iv["start"].min(), iv["end"].max(), freq="10s")
        busy = np.zeros(len(grid))
        for r in iv.itertuples():
            busy += (grid >= r.start) & (grid < r.end)
        ax.step(grid, busy, where="post", color="k", lw=0.8)
        for b in blocks:
            ax.axvspan(b["t0"], b["t1"], color="tab:blue", alpha=0.08)
        for w in waits:
            ax.axvline(w, color="r", lw=0.5, alpha=0.5)
    ax.set_ylabel("jobs running")
    ax.set_title("campaign slots over wall time (blue: stage blocks; red: 'slot waiting for memory')", fontsize=9)
    fig.suptitle(f"campaign ledger {campaign}", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "ledger.png", dpi=110)
    plt.close(fig)
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(stats.to_string(index=False))
        print(slots.to_string(index=False))


# ====================================================================== trace stage
#
# One estimate (process_station on a window, the survey's lemimt bands, ex ey out,
# no tweaks, no masks) run as four child passes of the same call, so no instrument
# distorts another's numbers:
#   pyspy-idle   clean run; py-spy --idle attached from outside (speedscope); exact
#                call counters + an h5py read log; psutil at every phase boundary
#   pyspy-gil    the same clean run again; py-spy --gil (flamegraph SVG): only the
#                samples of a thread holding the GIL
#   viztracer    in-process trace of every call lasting --viz-min-us or more (C
#                functions and GC included); our phase / detail / per-band spans on a
#                track of their own; RSS, disk read, CPU and thread counters every 0.25 s
#   tracemalloc  traced from the first line: a snapshot at every phase boundary, each
#                diffed with the one before; every span's traced peak; a snapshot each
#                time the RSS passes its last high by 0.25 GiB (the peak's composition)
# on the fork (the environment's aurora) and on stock aurora 0.6.2 (a worktree of the
# fork's clone at its base commit, first on PYTHONPATH).

TRACE_PASSES = ("pyspy-idle", "pyspy-gil", "viztracer", "tracemalloc")
SPAN_TRACK = "mtproc phases + counters"
MT_PACKAGES = ("aurora", "mth5", "mt_timeseries", "mt_metadata", "mtproc", "mt_io")
MIB = 2.0 ** 20
STOCK_AURORA_BASE = "3395804c"


def _read_or_decimate(level: int) -> str:
    return "L0 read TS" if level == 0 else f"L{level} decimate TS"


_TFK = "aurora.pipelines.transfer_function_kernel"
_SH = "aurora.time_series.spectrogram_helpers"
_WTS = "aurora.time_series.windowed_time_series"
_TFH = "aurora.pipelines.transfer_function_helpers"
_PM = "aurora.pipelines.process_mth5"
TARGETS["trace"] = [
    ("mtproc.process", "kernel_dataset", "kernel dataset", "P"),
    ("mth5.processing", "RunSummary.from_mth5s", "kd: RunSummary.from_mth5s", "D"),
    ("mth5.processing", "KernelDataset.from_run_summary", "kd: KernelDataset.from_run_summary", "D"),
    ("mtproc.process", "build_config", "aurora config", "P"),
    ("mtproc.process", "process_mth5", "aurora (other)", "P"),
    (_TFK, "TransferFunctionKernel.update_processing_summary", "aurora setup", "P"),
    (_TFK, "TransferFunctionKernel.validate", "aurora setup", "P"),
    (_TFK, "TransferFunctionKernel.initialize_mth5s", "aurora setup", "P"),
    (_TFK, "TransferFunctionKernel.update_dataset_df", _read_or_decimate, "P"),
    ("mth5.processing", "KernelDataset.initialize_dataframe_for_processing",
     "read: initialize_dataframe_for_processing", "D"),
    ("mth5.groups", "RunGroup.to_runts", "read: RunGroup.to_runts", "D"),
    (_TFK, "TransferFunctionKernel.drop_unused_remote_channels", "read: drop unused remote channels", "D"),
    (_TFK, "prototype_decimate", "decimate: prototype_decimate", "D"),
    (_PM, "get_spectrograms", "L{L} STFT", "P"),
    ("mth5.mth5", "MTH5.from_reference", "stft: MTH5.from_reference (run group)", "D"),
    (_SH, "make_stft_objects", "stft: one run (make_stft_objects)", "D"),
    (_SH, "run_ts_to_stft", "stft: run_ts_to_stft", "D"),
    (_SH, "nan_to_mean", "stft: nan_to_mean", "D"),
    (_SH, "apply_prewhitening", "stft: prewhiten", "D"),
    (_SH, "truncate_to_clock_zero", "stft: truncate to clock zero", "D"),
    ("aurora.time_series.windowing_scheme", "WindowingScheme.apply_sliding_window", "stft: sliding window", "D"),
    (_WTS, "WindowedTimeSeries.detrend", "stft: detrend", "D"),
    (_WTS, "WindowedTimeSeries.apply_taper", "stft: taper", "D"),
    (_WTS, "WindowedTimeSeries.apply_fft", "stft: FFT (apply_fft)", "D"),
    (_SH, "apply_recoloring", "stft: recolour", "D"),
    (_SH, "calibrate_stft_obj", "stft: calibrate", "D"),
    (_PM, "merge_stfts", "L{L} merge STFTs", "P"),
    (_PM, "extract_features", "L{L} features/weights", "P"),
    (_PM, "calculate_weights", "L{L} features/weights", "P"),
    (_PM, "process_tf_decimation_level", "L{L} regression", "P"),
    (_TFH, "get_band_for_tf_estimate", "band: extraction", "D"),
    (_TFH, "window_mask_for_band", "band: window mask", "D"),
    (_TFH, "stack_fcs", "band: stack_fcs", "D"),
    (_TFH, "drop_nans", "band: drop_nans", "D"),
    (_TFH, "effective_degrees_of_freedom_weights", "band: edf weights", "D"),
    (_TFH, "apply_weights", "band: apply_weights", "D"),
    (_TFH, "handle_nan", "band: handle_nan", "D"),
    ("aurora.transfer_function.regression.RME_RR", "RME_RR.estimate", "band: RME_RR.estimate", "D"),
    ("aurora.transfer_function.TTFZ", "TTFZ.set_tf", "band: set_tf", "D"),
    (_TFK, "TransferFunctionKernel.export_tf_collection", "TF assembly (export_tf_collection)", "P"),
    ("mth5.processing", "KernelDataset.close_mth5s", "close archives", "P"),
    ("mt_metadata.transfer_functions.core", "TF.write", "EDI write", "P"),
] + READ_DETAILS

# (module[|fallback], qualname, label): exact calls and seconds per phase in the clean passes.
# A module-level function is replaced wherever it is referenced (`from x import f` too);
# a method on its class. Only the outermost call of a recursion is timed.
COUNT_TARGETS = [
    ("pandas", "date_range", "pandas: pd.date_range"),
    ("pandas.core.arrays.datetimes", "DatetimeArray._generate_range", "pandas: DatetimeArray._generate_range"),
    ("mth5.mth5", "MTH5.from_reference", "mth5: MTH5.from_reference"),
    ("mth5.groups", "StationGroup.get_run", "mth5: StationGroup.get_run"),
    ("mth5.groups", "RunGroup.get_channel", "mth5: RunGroup.get_channel"),
    ("mth5.groups", "RunGroup.to_runts", "mth5: RunGroup.to_runts"),
    ("mth5.groups.channel_dataset", "ChannelDataset.__init__", "mth5: ChannelDataset()"),
    ("mth5.groups.channel_dataset", "ChannelDataset.time_slice", "mth5: ChannelDataset.time_slice"),
    ("mth5.groups.channel_dataset", "ChannelDataset.to_channel_ts", "mth5: ChannelDataset.to_channel_ts"),
    ("mth5.helpers", "read_attrs_to_dict", "mth5: read_attrs_to_dict"),
    ("mt_timeseries", "ChannelTS.__init__", "mt_timeseries: ChannelTS()"),
    ("mt_timeseries", "RunTS.__init__", "mt_timeseries: RunTS()"),
    ("mt_metadata.base.metadata", "MetadataBase.from_dict", "mt_metadata: MetadataBase.from_dict"),
    ("mt_metadata.base.metadata", "DotNotationBaseModel.__init__", "mt_metadata: metadata object ()"),
    ("pyproj.crs.crs", "CRS.__init__", "pyproj: CRS()"),
    ("xarray.structure.alignment|xarray.core.alignment", "align", "xarray: align"),
    ("xarray.core.dataset", "Dataset.copy", "xarray: Dataset.copy"),
    ("xarray.core.variable", "Variable._copy", "xarray: Variable._copy"),
    ("numpy", "copy", "numpy: np.copy"),
    ("copy", "deepcopy", "stdlib: copy.deepcopy"),
    ("numpy.fft", "fft", "numpy: fft.fft"),
    ("numpy.fft", "rfft", "numpy: fft.rfft"),
    ("scipy.signal", "detrend", "scipy: signal.detrend"),
    ("scipy.linalg", "lstsq", "scipy: linalg.lstsq"),
    ("h5py._hl.files", "File.__init__", "h5py: File()"),
    ("h5py._hl.group", "Group.__getitem__", "h5py: Group[...]"),
    ("h5py._hl.attrs", "AttributeManager.__getitem__", "h5py: attrs[...]"),
    ("h5py._hl.dataset", "Dataset.__getitem__", "h5py: Dataset[...] (read)"),
]


# ------------------------------------------------------------ trace stage: child side

class PhaseTracker:
    """The innermost open P mark: the phase piece an instant belongs to (as `phases_from_marks` names it)."""

    def __init__(self):
        self.open: list[str] = []
        self.seen = False

    def __call__(self, flag, kind, name, t):
        if kind != "P":
            return
        if flag == "B":
            self.open.append(name)
            self.seen = True
            return
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i] == name:
                del self.open[i]
                break

    def current(self) -> str:
        return self.open[-1] if self.open else ("(untracked)" if self.seen else "python start + imports")


class SpanSink:
    """B/E marks -> closed spans {name, kind, t0, t1, level, band}, handed to `emit` at their E.

    `clock` stamps them (viztracer's own `getts` in the viztracer pass, so the spans sit on
    the calls' timeline). A band's regression steps ("band: ...") also make one span per
    band and output channel, "L<n> band <T> s <ch>", from its extraction to its set_tf
    (aurora loops channels outside bands: the channel is the n-th time a band is seen).
    """

    def __init__(self, emit, clock=time.perf_counter, output_channels=("ex", "ey")):
        self.emit, self.clock, self.channels = emit, clock, list(output_channels)
        self.stack: list[dict] = []
        self.band_open: dict | None = None
        self.band_seen: dict = {}

    def __call__(self, flag, kind, name, t_epoch):
        t = self.clock()
        if flag == "B":
            if name == "band: extraction":
                self._close_band(t)
                key = (_LEVEL[0], _BAND[0])
                n = self.band_seen.get(key, 0)
                self.band_seen[key] = n + 1
                ch = self.channels[n] if n < len(self.channels) else f"#{n}"
                period = _BAND[0] if _BAND[0] is not None else float("nan")
                self.band_open = {"name": f"L{_LEVEL[0]} band {period:.4g} s {ch}", "kind": "band", "t0": t,
                                  "level": _LEVEL[0], "band": period}
            self.stack.append({"name": name, "kind": kind, "t0": t, "level": _LEVEL[0],
                               "band": _BAND[0] if name.startswith("band:") else None})
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["name"] == name:
                span = self.stack.pop(i)
                span["t1"] = t
                self.emit(span)
                break
        if name == "band: set_tf" or (kind == "P" and name.endswith("regression")):
            self._close_band(t)

    def _close_band(self, t):
        if self.band_open is not None:
            span, self.band_open = self.band_open, None
            span["t1"] = t
            self.emit(span)


class BoundaryLog:
    """psutil at every P boundary: RSS, I/O counters (bytes and operations), threads, CPU times, GC collections."""

    def __init__(self, tracker: PhaseTracker):
        import gc

        self.gc, self.tracker, self.proc, self.rows = gc, tracker, psutil.Process(), []

    def row(self, t: float, piece: str, flag: str = "", name: str = "") -> None:
        p = self.proc
        with p.oneshot():
            mi, io, ct = p.memory_info(), p.io_counters(), p.cpu_times()
            threads = p.num_threads()
        d = psutil.disk_io_counters()
        self.rows.append({
            "t": t, "ended": piece, "mark": f"{flag} {name}".strip(), "rss_mib": mi.rss / MIB,
            "private_mib": getattr(mi, "private", mi.vms) / MIB, "read_bytes": io.read_bytes, "read_count": io.read_count,
            "write_bytes": io.write_bytes, "write_count": io.write_count,
            "other_bytes": getattr(io, "other_bytes", 0), "other_count": getattr(io, "other_count", 0),
            "user_s": ct.user, "system_s": ct.system, "threads": threads,
            "machine_read_bytes": d.read_bytes, "machine_read_count": d.read_count,
            "gc_collections": sum(s["collections"] for s in self.gc.get_stats())})

    def __call__(self, flag, kind, name, t):
        if kind == "P":
            self.row(t, self.tracker.current(), flag, name)


def _h5_name(obj) -> tuple[str, str]:
    """(file name, object path) through h5py's low-level ids: no File object made, no counter hit."""
    import h5py

    try:
        fname = Path(os.fsdecode(h5py.h5f.get_name(obj.id))).name
    except Exception:
        fname = "?"
    try:
        name = os.fsdecode(h5py.h5i.get_name(obj.id))
    except Exception:
        name = "?"
    return fname, name


def _describe_selection(sel) -> tuple[str, int | None, int | None]:
    if isinstance(sel, tuple) and len(sel) == 1:
        sel = sel[0]
    if isinstance(sel, slice):
        return f"[{sel.start}:{sel.stop}{'' if sel.step in (None, 1) else ':' + str(sel.step)}]", sel.start, sel.stop
    if sel == () or sel is Ellipsis:
        return "[()] (all)", None, None
    try:
        import h5py

        if isinstance(sel, h5py.h5r.RegionReference):
            return "region reference", None, None
    except Exception:
        pass
    return type(sel).__name__, None, None


class CallCounter:
    """Exact calls and seconds of COUNT_TARGETS per phase piece (`tracker.current()` at the call).

    Per (phase, label): calls, outermost calls, seconds of the outermost calls, and for
    h5py dataset reads the bytes returned; every dataset read is also logged (time,
    phase, file, dataset, selection, bytes, seconds) to tell sequential from repeated reads.
    """

    def __init__(self, tracker: PhaseTracker):
        self.tracker = tracker
        self.rows: dict = {}
        self.depth: dict = {}
        self.reads: list = []

    def wrap(self, fn, label: str):
        rows, depth, tracker, reads = self.rows, self.depth, self.tracker, self.reads
        depth[label] = 0
        log_read = label.startswith("h5py: Dataset[")

        @functools.wraps(fn)
        def counted(*args, **kwargs):
            d = depth[label]
            depth[label] = d + 1
            t0 = time.perf_counter()
            try:
                out = fn(*args, **kwargs)
            finally:
                depth[label] = d
                sec = time.perf_counter() - t0
                key = (tracker.current(), label)
                r = rows.get(key)
                if r is None:
                    r = rows[key] = [0, 0, 0.0, 0]
                r[0] += 1
                if d == 0:
                    r[1] += 1
                    r[2] += sec
            if log_read:
                nbytes = int(getattr(out, "nbytes", 0) or 0)
                r[3] += nbytes
                fname, dname = _h5_name(args[0])
                desc, lo, hi = _describe_selection(args[1] if len(args) > 1 else ())
                try:
                    n = int(args[0].id.shape[0]) if args[0].id.shape else 0
                except Exception:
                    n = 0
                reads.append({"t": time.time(), "phase": key[0], "file": fname, "dataset": dname, "selection": desc,
                              "start": lo, "stop": hi, "dataset_len": n, "bytes": nbytes, "seconds": sec})
            return out

        return counted

    def table(self) -> pd.DataFrame:
        return pd.DataFrame([{"phase": ph, "target": lab, "calls": r[0], "outer_calls": r[1], "seconds": r[2],
                              "MB": r[3] / MB} for (ph, lab), r in self.rows.items()])


def _resolve_attr(module: str, qualname: str):
    import importlib

    last = None
    for name in module.split("|"):
        try:
            owner = importlib.import_module(name)
        except ImportError as exc:
            last = exc
            continue
        parts = qualname.split(".")
        for part in parts[:-1]:
            owner = getattr(owner, part)
        return owner, parts[-1]
    raise last or ImportError(module)


def _replace_everywhere(orig, new) -> int:
    """Every module attribute that *is* `orig` becomes `new`; returns how many."""
    n = 0
    for mod in list(sys.modules.values()):
        try:
            d = vars(mod)
        except TypeError:
            continue
        for k, v in list(d.items()):
            if v is orig:
                d[k] = new
                n += 1
    return n


def install_counters(counter: CallCounter, targets=None) -> list[str]:
    missing = []
    for module, qualname, label in COUNT_TARGETS if targets is None else targets:
        try:
            owner, attr = _resolve_attr(module, qualname)
            if isinstance(owner, type):
                raw = next((k.__dict__[attr] for k in owner.__mro__ if attr in k.__dict__), None)
                if raw is None:
                    raise AttributeError(attr)
                if isinstance(raw, classmethod):
                    setattr(owner, attr, classmethod(counter.wrap(raw.__func__, label)))
                elif isinstance(raw, staticmethod):
                    setattr(owner, attr, staticmethod(counter.wrap(raw.__func__, label)))
                else:
                    setattr(owner, attr, counter.wrap(raw, label))
            else:
                orig = getattr(owner, attr)
                if not _replace_everywhere(orig, counter.wrap(orig, label)):
                    raise AttributeError(f"{attr}: no reference found")
        except Exception as exc:
            missing.append(f"{module}:{qualname} ({type(exc).__name__}: {exc})")
    return missing


def _force_read_only() -> None:
    """Every MTH5 open in this process read-only: the trace stage reads the campaign's own archives."""
    from mth5.mth5 import MTH5

    original = MTH5.open_mth5

    @functools.wraps(original)
    def open_mth5(self, filename=None, mode="r", **kw):
        if mode != "r":
            sys.__stderr__.write(f"PROFINFO open_mth5 mode {mode!r} forced to 'r': {filename}\n")
        return original(self, filename, mode="r", **kw)

    MTH5.open_mth5 = open_mth5


# --- tracemalloc: snapshot diffs, owners, per-span peaks

@functools.lru_cache(maxsize=None)
def _func_spans(filename: str) -> tuple:
    import ast

    try:
        tree = ast.parse(Path(filename).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ()
    spans = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    spans.append((child.lineno, child.end_lineno or child.lineno, qual))
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return tuple(spans)


def _func_at(filename: str, lineno: int) -> str:
    """The innermost function (qualname) whose source lines hold `lineno`; "<module>" if none."""
    best, width = "", float("inf")
    for a, b, qual in _func_spans(filename):
        if a <= lineno <= b and b - a < width:
            best, width = qual, b - a
    return best or "<module>"


@functools.lru_cache(maxsize=None)
def _package_of(filename: str) -> str:
    f = filename.replace("\\", "/")
    for pkg in MT_PACKAGES:
        if f"/{pkg}/" in f:
            return pkg
    if "site-packages/" in f:
        return f.split("site-packages/", 1)[1].split("/", 1)[0]
    return "python"


def _frame_text(filename: str, lineno: int) -> str:
    return f"{_short(filename)}:{lineno} ({_func_at(filename, lineno)})"


def _raw_chain(frames, n: int = 4) -> str:
    """The first `n` of `frames` (raw (file, line), innermost first) in the MT packages -- else the first
    `n` -- as 'file:line|file:line' (resolved to function names later, outside the traced process)."""
    ours = [fr for fr in frames if _package_of(fr[0]) in MT_PACKAGES]
    return "|".join(f"{f}:{ln}" for f, ln in (ours[:n] or list(frames)[:n]))


def _resolve_chain(chain: str) -> str:
    if not isinstance(chain, str) or not chain:
        return ""
    return "  <-  ".join(_frame_text(*_split_frame(fr)) for fr in chain.split("|"))


def _split_frame(text: str) -> tuple[str, int]:
    f, ln = text.rsplit(":", 1)
    return f, int(ln)


def _tm_group_own(snapshot) -> tuple[dict, int]:
    """({raw traceback (innermost frame first): [bytes, blocks]}, bytes held by tracemalloc and this module)."""
    import tracemalloc

    skip = {tracemalloc.__file__, __file__}
    out, own = {}, 0
    for _domain, size, frames, _n in snapshot.traces._traces:
        if frames and frames[0][0] in skip:
            own += size
            continue
        r = out.get(frames)
        if r is None:
            out[frames] = [size, 1]
        else:
            r[0] += size
            r[1] += 1
    return out, own


def tm_group(snapshot) -> dict:
    """A snapshot's traces grouped by their whole traceback: {raw frames, innermost first: [bytes, blocks]}.
    Raw tuples rather than `Snapshot.statistics` objects: this runs at every phase boundary of a traced run."""
    return _tm_group_own(snapshot)[0]


def tm_diff_table(new, old, phase: str, top: int = 15, resolve: bool = True) -> pd.DataFrame:
    """The `top` allocation sites that grew most from `old` to `new` (snapshots or `tm_group` dicts).

    One row per site (a site = a whole traceback): phase, plus_mib (growth), blocks
    (growth in blocks), alive_mib (held at `new`), site_file / site_line (the allocating
    frame) and chain_frames (the next frames in the MT packages, innermost first, raw);
    with `resolve`, also site ('pkg/file.py:line'), function (the def holding that line)
    and chain ('file:line (function)  <-  ...': who asked for it).
    """
    if not isinstance(new, dict):
        new = tm_group(new)
    if not isinstance(old, dict):
        old = tm_group(old)
    grown = []
    for frames, (size, count) in new.items():
        s0, c0 = old.get(frames, (0, 0))
        if size > s0:
            grown.append((size - s0, count - c0, size, frames))
    grown.sort(key=lambda r: r[0], reverse=True)
    rows = [{"phase": phase, "plus_mib": d_size / MIB, "blocks": d_count, "alive_mib": size / MIB,
             "site_file": frames[0][0] if frames else "?", "site_line": frames[0][1] if frames else 0,
             "chain_frames": _raw_chain(frames[1:])} for d_size, d_count, size, frames in grown[:top]]
    df = pd.DataFrame(rows, columns=["phase", "plus_mib", "blocks", "alive_mib", "site_file", "site_line",
                                     "chain_frames"])
    return tm_resolve(df) if resolve else df


def tm_resolve(df: pd.DataFrame) -> pd.DataFrame:
    """Adds site, function and chain (function names from the source files) to a raw site table."""
    df = df.copy()
    df["site"] = [f"{_short(f)}:{ln}" for f, ln in zip(df["site_file"], df["site_line"])]
    df["function"] = [_func_at(f, int(ln)) for f, ln in zip(df["site_file"], df["site_line"])]
    df["chain"] = [_resolve_chain(c) for c in df["chain_frames"]]
    return df


def tm_owner_bytes(grouped: dict) -> dict:
    """Traced bytes per owner: the innermost frame in an MT package, else the allocating frame's package."""
    out: dict = {}
    for frames, (size, _count) in grouped.items():
        owner = next((p for p in (_package_of(f) for f, _ in frames) if p in MT_PACKAGES), None)
        owner = owner or (_package_of(frames[0][0]) if frames else "?")
        out[owner] = out.get(owner, 0) + size
    return out


_TFK_REF: list = [None]  # weakref to aurora's TransferFunctionKernel (tracemalloc pass: the census)


def ts_census() -> dict:
    """Bytes of the time series aurora's kernel dataset holds right now (data + coordinates), local and remote."""
    out = {"local": 0, "remote": 0}
    tfk = _TFK_REF[0]() if _TFK_REF[0] is not None else None
    df = getattr(tfk, "dataset_df", None) if tfk is not None else None
    if df is None or "run_dataarray" not in getattr(df, "columns", ()):
        return out
    for row in df.itertuples():
        arr = getattr(row, "run_dataarray", None)
        if arr is None or not hasattr(arr, "nbytes"):
            continue
        n = int(arr.nbytes) + sum(int(c.nbytes) for c in arr.coords.values())
        out["remote" if bool(getattr(row, "remote", False)) else "local"] += n
    return out


class TmSink:
    """tracemalloc on the mark stream: every span's traced peak (all marks); at each P boundary
    a snapshot, diffed with the previous one (the piece that just ended), and grouped by owner.

    Tracing stops over the `pause` phases and restarts after them (mth5's time_slice ->
    mt_timeseries' make_dt_coordinates -> pandas DatetimeIndex.round allocates a Python int
    per sample: traced, level 0's read of a 6 h window would take over an hour). A paused
    piece has no traced numbers; memory allocated in it is invisible to tracemalloc from
    then on, which is what the census (`ts_census`, the kernel dataset's time series, at
    every boundary) accounts for.
    """

    def __init__(self, tracker: PhaseTracker, top: int = 15, nframe: int = 10, pause=("L0 read TS",)):
        import tracemalloc

        self.tm, self.tracker, self.top, self.nframe, self.pause = tracemalloc, tracker, top, nframe, set(pause)
        self.prev: dict | None = None
        self.pk = [0]
        self.open: list = []
        self.pieces, self.sites, self.owners, self.spans = [], [], [], []
        self.piece_peak = 0
        self.t_piece0 = time.time()
        self.traced_piece0 = 0
        self.snap_seconds = 0.0
        self.paused: str | None = None
        self.epoch = 0

    def start(self) -> None:
        self.t_piece0 = time.time()
        self.traced_piece0 = self.tm.get_traced_memory()[0]
        self.piece_peak = self.traced_piece0
        self.boundary(self.t_piece0, self.traced_piece0, first=True)

    def __call__(self, flag, kind, name, t):
        tracing = self.tm.is_tracing()
        cur, peak = self.tm.get_traced_memory() if tracing else (0, 0)
        self.piece_peak = max(self.piece_peak, peak)
        if flag == "B":
            self.pk[-1] = max(self.pk[-1], peak)
            self.pk.append(cur)
            self.open.append((name, kind, t, cur, self.epoch))
        else:
            idx = next((i for i in range(len(self.open) - 1, -1, -1) if self.open[i][0] == name), None)
            if idx is not None:
                nm, kd, t0, c0, epoch = self.open.pop(idx)
                inner = max(self.pk.pop(idx + 1), peak)
                self.pk[idx] = max(self.pk[idx], inner)
                ok = tracing and epoch == self.epoch  # never across a pause
                nan = float("nan")
                self.spans.append({"name": nm, "kind": kd, "t0": t0, "t1": t,
                                   "traced_start_mib": c0 / MIB if ok else nan,
                                   "traced_end_mib": cur / MIB if ok else nan,
                                   "peak_mib": inner / MIB if ok else nan,
                                   "peak_over_start_mib": (inner - c0) / MIB if ok else nan})
        if tracing:
            self.tm.reset_peak()
        if kind != "P":
            return
        if flag == "B" and name in self.pause and tracing:
            self.boundary(t, cur)  # the piece before it ends, traced
            self.tm.stop()
            self.paused, self.epoch = name, self.epoch + 1
            self.t_piece0 = t
        elif flag == "E" and name == self.paused:
            census = ts_census()
            self.pieces.append({"piece": len(self.pieces), "phase": name, "t0": self.t_piece0, "t1": t,
                                "traced": False, "rss_end_mib": psutil.Process().memory_info().rss / MIB,
                                "census_local_mib": census["local"] / MIB, "census_remote_mib": census["remote"] / MIB})
            self.tm.start(self.nframe)
            self.paused, self.prev = None, {}
            self.t_piece0, self.traced_piece0, self.piece_peak = t, 0, 0
            self.pk = [0] * len(self.pk)
        elif tracing:
            self.boundary(t, cur)

    def boundary(self, t: float, cur: int, first: bool = False) -> None:
        piece = "start" if first else self.tracker.current()
        t0 = time.perf_counter()
        grouped, own = _tm_group_own(self.tm.take_snapshot())
        i = len(self.pieces)
        if self.prev is not None:
            df = tm_diff_table(grouped, self.prev, piece, self.top, resolve=False)
            df.insert(0, "piece", i)
            self.sites.append(df)
        for owner, size in tm_owner_bytes(grouped).items():
            self.owners.append({"piece": i, "phase": piece, "owner": owner, "MiB": size / MIB})
        self.prev = grouped
        dt_snap = time.perf_counter() - t0
        self.snap_seconds += dt_snap
        census = ts_census()
        rss = psutil.Process().memory_info().rss
        self.pieces.append({"piece": i, "phase": piece, "t0": self.t_piece0, "t1": t, "traced": True,
                            "traced_start_mib": self.traced_piece0 / MIB, "traced_end_mib": cur / MIB,
                            "net_mib": (cur - self.traced_piece0) / MIB, "peak_mib": self.piece_peak / MIB,
                            "peak_over_start_mib": (self.piece_peak - self.traced_piece0) / MIB,
                            "profiler_own_mib": own / MIB, "rss_end_mib": rss / MIB,
                            "census_local_mib": census["local"] / MIB, "census_remote_mib": census["remote"] / MIB,
                            "snapshot_s": dt_snap})
        self.t_piece0, self.traced_piece0 = t, cur
        self.piece_peak = cur
        self.tm.reset_peak()

    def write(self, stem: Path) -> None:
        pd.DataFrame(self.pieces).to_csv(str(stem) + "_tm_pieces.csv", index=False)
        sites = pd.concat(self.sites, ignore_index=True) if self.sites else pd.DataFrame()
        sites.to_csv(str(stem) + "_tm_sites.csv", index=False)
        pd.DataFrame(self.owners).to_csv(str(stem) + "_tm_owners.csv", index=False)
        pd.DataFrame(self.spans).to_csv(str(stem) + "_tm_spans.csv", index=False)


class TmPeak(threading.Thread):
    """A snapshot each time the RSS passes its last high by `step_gib`: the latest one's top sites
    (raw, resolved later) are the composition near the run's peak."""

    def __init__(self, step_gib: float = 0.25, interval: float = 0.25, top: int = 25):
        super().__init__(daemon=True)
        import tracemalloc

        self.tm, self.step, self.interval, self.top = tracemalloc, step_gib * GIB, interval, top
        self.halt = threading.Event()
        self.best = psutil.Process().memory_info().rss
        self.table = pd.DataFrame()
        self.n, self.seconds = 0, 0.0

    def run(self):
        proc = psutil.Process()
        while not self.halt.is_set():
            rss = proc.memory_info().rss
            if rss > self.best + self.step and self.tm.is_tracing():
                t0 = time.perf_counter()
                try:
                    grouped, _own = _tm_group_own(self.tm.take_snapshot())
                except RuntimeError:  # tracing stopped (a paused phase) under us
                    self.halt.wait(self.interval)
                    continue
                traced, _ = self.tm.get_traced_memory()
                census = ts_census()
                df = tm_diff_table(grouped, {}, "peak", self.top, resolve=False)
                df["rss_gib"], df["traced_gib"], df["t"] = rss / GIB, traced / GIB, time.time()
                df["census_local_gib"], df["census_remote_gib"] = census["local"] / GIB, census["remote"] / GIB
                self.table, self.best = df, rss
                self.n += 1
                self.seconds += time.perf_counter() - t0
            self.halt.wait(self.interval)


# --- viztracer: our spans and counters on the calls' timeline

class VizPump(threading.Thread):
    """Beside the traced main thread (started before the tracer, so itself untraced): our spans onto
    their own track (add_raw from this thread), and VizCounters every `interval` s."""

    def __init__(self, tracer, interval: float = 0.25):
        super().__init__(name=SPAN_TRACK, daemon=True)
        import queue

        from viztracer.vizcounter import VizCounter

        self.queue_mod = queue
        self.tracer, self.interval = tracer, interval
        self.q = queue.SimpleQueue()
        self.halt = threading.Event()
        self.mem = VizCounter(tracer, "memory (GiB)", trigger_on_change=False)
        self.disk = VizCounter(tracer, "disk read (MB/s)", trigger_on_change=False)
        self.cum = VizCounter(tracer, "disk read since start (GB)", trigger_on_change=False)
        self.cpu = VizCounter(tracer, "CPU (cores) and threads", trigger_on_change=False)

    def emit(self, span: dict) -> None:
        args = {k: span[k] for k in ("level", "band") if span.get(k) is not None}
        self.q.put({"ph": "X", "cat": span["kind"], "name": span["name"], "ts": span["t0"],
                    "dur": max(span["t1"] - span["t0"], 0.0), "args": args})

    def flush(self) -> None:
        while True:
            try:
                ev = self.q.get_nowait()
            except self.queue_mod.Empty:
                return
            self.tracer.add_raw(ev)

    def run(self):
        proc = psutil.Process()
        proc.cpu_percent(None)
        d0, p0 = psutil.disk_io_counters(), proc.io_counters()
        last = [time.perf_counter(), d0.read_bytes, p0.read_bytes]

        def sample():
            now, d, io, mi = time.perf_counter(), psutil.disk_io_counters(), proc.io_counters(), proc.memory_info()
            span = max(now - last[0], 1e-6)
            self.mem.rss = mi.rss / GIB
            self.mem.private = getattr(mi, "private", mi.vms) / GIB
            self.mem.log()
            self.disk.machine = (d.read_bytes - last[1]) / MB / span
            self.disk.process = (io.read_bytes - last[2]) / MB / span
            self.disk.log()
            self.cum.machine = (d.read_bytes - d0.read_bytes) / 1e9
            self.cum.process = (io.read_bytes - p0.read_bytes) / 1e9
            self.cum.log()
            self.cpu.cores = proc.cpu_percent(None) / 100.0
            self.cpu.threads = proc.num_threads()
            self.cpu.log()
            last[:] = [now, d.read_bytes, io.read_bytes]

        while True:
            self.flush()
            sample()
            if self.halt.wait(self.interval):  # a last sample once halted, while the tracer still records
                self.flush()
                sample()
                return


def trace_child(spec: dict) -> None:
    """One pass of the trace stage (spec["pass"]): the estimate under that pass's instrument."""
    mode = spec["pass"]
    stem = Path(spec["out_stem"])
    import aurora
    import aurora.pipelines.process_mth5  # noqa: F401 -- the targets' modules, imported before patching
    import aurora.transfer_function.regression.RME_RR  # noqa: F401
    import aurora.transfer_function.TTFZ  # noqa: F401
    import mt_metadata.transfer_functions.core  # noqa: F401
    import pyproj  # noqa: F401

    from mtproc.bands import lemimt_band_scheme
    from mtproc.process import process_station
    from mtproc.survey import Survey

    sys.__stderr__.write(f"PROFINFO aurora {aurora.__version__} from {Path(aurora.__file__).parent}\n")
    _force_read_only()
    install_markers("trace")
    tracker = PhaseTracker()
    bounds = BoundaryLog(tracker)
    # psutil at the boundaries costs ~10 ms each: not in the viztracer pass, whose counters cover it
    sinks: list = [bounds] if mode != "viztracer" else []
    counter = tms = pump = tracer = snapper = None
    if mode.startswith("pyspy"):
        counter = CallCounter(tracker)
        for m in install_counters(counter):
            sys.__stderr__.write(f"PROFINFO counter not installed: {m}\n")
    elif mode == "tracemalloc":
        import weakref

        from aurora.pipelines.transfer_function_kernel import TransferFunctionKernel

        tms = TmSink(tracker, top=int(spec.get("tm_top", 15)), nframe=int(spec.get("tm_nframe", 10)),
                     pause=spec.get("tm_pause") or ())
        sinks.append(tms)
        inner_update = TransferFunctionKernel.update_dataset_df

        @functools.wraps(inner_update)
        def update_dataset_df(self, *a, **k):  # remember the kernel (weakly) for the census
            _TFK_REF[0] = weakref.ref(self)
            return inner_update(self, *a, **k)

        TransferFunctionKernel.update_dataset_df = update_dataset_df
    elif mode == "viztracer":
        from viztracer import VizTracer

        tracer = VizTracer(tracer_entries=int(spec.get("viz_entries", 10_000_000)),
                           max_stack_depth=int(spec.get("viz_depth", -1)), ignore_c_function=False,
                           ignore_frozen=True, log_gc=True, min_duration=float(spec.get("viz_min_us", 5.0)),
                           dump_raw=True, verbose=0, output_file=str(stem) + ".json")
        pump = VizPump(tracer)
        spans = SpanSink(pump.emit, clock=tracer.getts, output_channels=spec.get("output_channels") or ("ex", "ey"))

        def level_instants(flag, kind, name, t):
            if flag == "B" and kind == "P" and name.endswith(" TS"):
                tracer.log_instant(f"{name}: level start", scope="p")

        sinks += [spans, level_instants]
    sinks.append(tracker)  # last: the others see the piece that just ended
    _SINKS[:] = sinks

    go = spec.get("go_file")
    if go:  # py-spy attaches first
        t_wait = time.time()
        while not Path(go).exists() and time.time() - t_wait < 120:
            time.sleep(0.05)
        sys.__stderr__.write(f"PROFINFO go after {time.time() - t_wait:.1f} s\n")
    if mode == "tracemalloc":
        import tracemalloc

        tracemalloc.start(int(spec.get("tm_nframe", 25)))
        snapper = TmPeak(step_gib=float(spec.get("snap_step_gib", 0.25)))
        tms.start()
        snapper.start()
    if mode == "viztracer":
        pump.start()
        offs = []
        for _ in range(5):
            a = tracer.getts()
            e = time.time() * 1e6
            offs.append(e - 0.5 * (a + tracer.getts()))
        viz_offset = float(np.median(offs))
        tracer.start()
    if mode != "viztracer":
        bounds.row(time.time(), "start", "B", "start")
    t_wall = time.perf_counter()
    try:
        survey = Survey.from_yaml(spec["survey"])
        scheme = lemimt_band_scheme(survey.sample_rate, **dict(survey.processing))
        process_station(Path(spec["local_h5"]), spec["local"], Path(spec["remote_h5"]), spec["remote"],
                        out_dir=Path(spec["edi_dir"]), band_scheme=scheme, start=spec["start"], end=spec["end"],
                        tag=stem.name, output_channels=list(spec.get("output_channels") or ["ex", "ey"]))
    finally:
        wall = time.perf_counter() - t_wall
        if mode != "viztracer":
            bounds.row(time.time(), tracker.current(), "E", "end")
        _SINKS[:] = []
        if mode == "viztracer":
            pump.halt.set()
            pump.join()
            tracer.stop()
            t0 = time.perf_counter()
            tracer.save()
            meta = {"offset_us": viz_offset, "min_duration_us": float(spec.get("viz_min_us", 5.0)),
                    "tracer_entries": int(spec.get("viz_entries", 10_000_000)),
                    "max_stack_depth": int(spec.get("viz_depth", -1)), "dump_seconds": time.perf_counter() - t0,
                    "wall_seconds": wall, "aurora": aurora.__version__}
            Path(str(stem) + "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        if mode == "tracemalloc":
            snapper.halt.set()
            snapper.join()
            tms.write(stem)
            snapper.table.to_csv(str(stem) + "_tm_peak.csv", index=False)
            import tracemalloc

            tracemalloc.stop()
            sys.__stderr__.write(f"PROFINFO tracemalloc: {len(tms.pieces)} boundary snapshots taking "
                                 f"{tms.snap_seconds:.1f} s; {snapper.n} peak snapshots taking {snapper.seconds:.1f} s\n")
        if counter is not None:
            counter.table().to_csv(str(stem) + "_calls.csv", index=False)
            pd.DataFrame(counter.reads).to_csv(str(stem) + "_h5reads.csv", index=False)
        pd.DataFrame(bounds.rows).to_csv(str(stem) + "_boundaries.csv", index=False)
    print(f"trace {mode}: process_station {wall:.1f} s", flush=True)


# ------------------------------------------------------------ trace stage: analysis (parent)

def _phase_pieces(log_path: Path, t_start: float, t_end: float) -> list[dict]:
    events = parse_log(log_path.read_text(encoding="utf-8", errors="replace"))
    return phases_from_marks(mark_intervals(events), t_start, t_end)


def agg_phases(table: pd.DataFrame) -> pd.DataFrame:
    """A pass's `phase_table` pieces summed per phase name, in order of first appearance."""
    rows = []
    for name, g in table.groupby("phase", sort=False):
        secs = g["seconds"].sum()
        rows.append({"phase": name, "pieces": len(g), "start_s": g["start_s"].min(), "seconds": secs,
                     "peak_rss_mib": g["peak_rss_gib"].max() * 1024.0,
                     "mean_cpu_cores": float(np.average(g["mean_cpu_pct"].fillna(0), weights=g["seconds"] + 1e-9)) / 100.0,
                     "machine_disk_read_mb": g["disk_read_mb"].sum(), "proc_read_mb": g["proc_read_mb"].sum()})
    return pd.DataFrame(rows)


def _short_func(name: str) -> str:
    """viztracer's 'func (C:\\...\\pkg\\mod.py:123)' -> 'func (pkg/mod.py:123)'."""
    m = re.match(r"^(.*) \((.+):(\d+)\)$", name)
    return f"{m[1]} ({_short(m[2])}:{m[3]})" if m else name


def viz_analyse(json_path: Path, meta: dict, pieces: list[dict], top: int = 15) -> dict:
    """Self time and calls per function per phase from a viztracer JSON (MainThread), GC time per phase."""
    import bisect
    from collections import defaultdict

    data = json.loads(Path(json_path).read_text(encoding="utf-8", errors="replace"))
    events = data["traceEvents"]
    names = {e["tid"]: e["args"]["name"] for e in events if e.get("ph") == "M" and e.get("name") == "thread_name"}
    main = next((tid for tid, n in names.items() if n == "MainThread"), None)
    off = meta["offset_us"]
    starts = [pc["t0"] * 1e6 - off for pc in pieces]
    ends = [pc["t1"] * 1e6 - off for pc in pieces]
    pnames = [pc["name"] for pc in pieces]
    self_t, calls = defaultdict(float), defaultdict(int)
    callers, caller_n = defaultdict(float), defaultdict(int)  # (function, its caller) -> inclusive us, calls

    def add_self(fn, a, b):
        i = max(bisect.bisect_right(starts, a) - 1, 0)
        while a < b and i < len(starts):
            seg = min(b, ends[i])
            if seg > a:
                self_t[(pnames[i], fn)] += seg - a
            a = max(a, seg)
            i += 1

    fee = sorted(((e["ts"], e["dur"], e["name"]) for e in events
                  if e.get("ph") == "X" and e.get("cat") == "fee" and e.get("tid") == main),
                 key=lambda r: (r[0], -r[1]))
    stack: list = []
    for ts, dur, fn in fee:
        end = ts + dur
        while stack and stack[-1][0] <= ts:
            top_ = stack.pop()
            add_self(top_[1], top_[2], top_[0])
        if stack:
            parent = stack[-1]
            if ts > parent[2]:
                add_self(parent[1], parent[2], ts)
            parent[2] = max(parent[2], min(end, parent[0]))
            callers[(fn, parent[1])] += dur
            caller_n[(fn, parent[1])] += 1
        i = max(bisect.bisect_right(starts, ts) - 1, 0)
        calls[(pnames[i], fn)] += 1
        stack.append([end, fn, ts])
    while stack:
        top_ = stack.pop()
        add_self(top_[1], top_[2], top_[0])
    gc_t: dict = defaultdict(float)
    gc_on = None
    for e in sorted((e for e in events if e.get("ph") == "C" and e.get("name") == "garbage collection"
                     and e.get("tid") == main), key=lambda e: e["ts"]):
        if e["args"].get("collecting"):
            gc_on = e["ts"]
        elif gc_on is not None:
            i = max(bisect.bisect_right(starts, gc_on) - 1, 0)
            gc_t[pnames[i]] += e["ts"] - gc_on
            gc_on = None
    phase_us = defaultdict(float)
    for a, b, n in zip(starts, ends, pnames):
        phase_us[n] += b - a
    rows = []
    for (ph, fn), us in self_t.items():
        rows.append({"phase": ph, "function": _short_func(fn), "self_s": us / 1e6, "calls": calls.get((ph, fn), 0),
                     "share": us / phase_us[ph] if phase_us[ph] else np.nan})
    hot = pd.DataFrame(rows)
    self_all = hot[hot["self_s"] >= 1e-3].copy() if not hot.empty else hot
    order = {n: i for i, n in enumerate(dict.fromkeys(pnames))}
    if not hot.empty:
        hot["order"] = hot["phase"].map(order)
        hot = hot.sort_values(["order", "self_s"], ascending=[True, False]).groupby("phase", sort=False).head(top)
        hot = hot.drop(columns="order")
    all_calls = pd.DataFrame([{"phase": ph, "function": _short_func(fn), "calls": c} for (ph, fn), c in calls.items()])
    n_fee = len(fee)
    total_self = defaultdict(float)
    for (ph, fn), us in self_t.items():
        total_self[fn] += us
    top_fns = sorted(total_self, key=total_self.get, reverse=True)[:60]
    crow = []
    for fn in top_fns:
        cs = sorted(((c, us) for (f, c), us in callers.items() if f == fn), key=lambda r: r[1], reverse=True)[:3]
        for rank, (c, us) in enumerate(cs, 1):
            crow.append({"function": _short_func(fn), "self_s_total": total_self[fn] / 1e6, "caller_rank": rank,
                         "caller": _short_func(c), "incl_s_from_caller": us / 1e6, "calls_from_caller": caller_n[(fn, c)]})
    return {"hot": hot, "self_all": self_all, "calls": all_calls, "callers": pd.DataFrame(crow), "gc": dict(gc_t), "events": len(events), "fee_events": n_fee,
            "overflow": n_fee >= meta.get("tracer_entries", 1 << 62) - 10, "phase_seconds": {k: v / 1e6 for k, v in phase_us.items()}}


def pyspy_speedscope(path: Path) -> tuple[pd.DataFrame, dict]:
    """Per function (name + file) self and inclusive samples over all threads of a py-spy speedscope file."""
    from collections import Counter

    d = json.loads(Path(path).read_text(encoding="utf-8"))
    frames = d["shared"]["frames"]
    key = [f"{fr['name']} ({_short(fr.get('file') or '?')})" for fr in frames]
    self_c, incl_c = Counter(), Counter()
    threads = {}
    for prof in d["profiles"]:
        threads[prof["name"]] = len(prof["samples"])
        for s in prof["samples"]:
            if not s:
                continue
            self_c[key[s[-1]]] += 1
            for k in {key[i] for i in s}:
                incl_c[k] += 1
    df = pd.DataFrame([{"function": k, "self_samples": self_c.get(k, 0), "incl_samples": v} for k, v in incl_c.items()])
    return df.sort_values("self_samples", ascending=False), threads


def pyspy_svg(path: Path) -> tuple[pd.DataFrame, int]:
    """Per function (name + file) inclusive samples from a py-spy flamegraph SVG's frame titles."""
    import html
    from collections import Counter

    text = Path(path).read_text(encoding="utf-8", errors="replace")
    incl, total = Counter(), 0
    for t in re.findall(r"<title>(.*?)</title>", text, flags=re.S):
        t = html.unescape(t)
        m = re.match(r"^(.*) \((\d[\d,]*) samples?, [\d.]+%\)$", t)
        if not m:
            continue
        label, n = m[1], int(m[2].replace(",", ""))
        if label == "all":
            total = n
            continue
        m2 = re.match(r"^(.*) \((.*?)(?::\d+)?\)$", label)
        name = f"{m2[1]} ({_short(m2[2])})" if m2 else label
        incl[name] += n
    return pd.DataFrame([{"function": k, "gil_incl_samples": v} for k, v in incl.items()]), total


def h5reads_summary(reads: pd.DataFrame) -> pd.DataFrame:
    """Per (file, dataset): reads, MB, distinct selections, repeated reads/MB, contiguous follow-ons, phases."""
    rows = []
    if reads.empty:
        return pd.DataFrame()
    reads = reads.sort_values("t")
    for (f, dname), g in reads.groupby(["file", "dataset"], sort=False):
        seen, rep_n, rep_b, contiguous = set(), 0, 0, 0
        prev_stop = None
        for r in g.itertuples():
            key = (r.selection,)
            if key in seen:
                rep_n += 1
                rep_b += r.bytes
            seen.add(key)
            if prev_stop is not None and pd.notna(r.start) and r.start == prev_stop:
                contiguous += 1
            prev_stop = r.stop if pd.notna(r.stop) else None
        rows.append({"file": f, "dataset": dname, "reads": len(g), "MB": g["bytes"].sum() / MB,
                     "seconds": g["seconds"].sum(), "MB_per_s": g["bytes"].sum() / MB / max(g["seconds"].sum(), 1e-9),
                     "distinct_selections": len(seen), "repeated_reads": rep_n, "repeated_MB": rep_b / MB,
                     "contiguous_follow_ons": contiguous, "dataset_len": int(g["dataset_len"].max()),
                     "phases": "; ".join(dict.fromkeys(g["phase"]))})
    return pd.DataFrame(rows).sort_values("MB", ascending=False)


def _level_group(phase: str) -> str:
    m = re.match(r"^L(\d+) ", phase)
    return f"L{m[1]}" if m else phase


def boundary_deltas(bounds: pd.DataFrame) -> pd.DataFrame:
    """Per phase name: process read MB and operations, write ops, other ops, CPU user/system s, max threads, GC runs."""
    b = bounds.sort_values("t").reset_index(drop=True)
    rows = []
    for i in range(1, len(b)):
        a, c = b.iloc[i - 1], b.iloc[i]
        rows.append({"phase": c["ended"], "proc_read_mb_b": (c["read_bytes"] - a["read_bytes"]) / MB,
                     "read_ops": c["read_count"] - a["read_count"], "write_ops": c["write_count"] - a["write_count"],
                     "other_ops": c["other_count"] - a["other_count"],
                     "machine_read_mb_b": (c["machine_read_bytes"] - a["machine_read_bytes"]) / MB,
                     "user_s": c["user_s"] - a["user_s"], "system_s": c["system_s"] - a["system_s"],
                     "threads_max": max(a["threads"], c["threads"]),
                     "gc_runs": c["gc_collections"] - a["gc_collections"]})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    agg = {k: "sum" for k in df.columns if k not in ("phase", "threads_max")}
    agg["threads_max"] = "max"
    return df.groupby("phase", sort=False).agg(agg).reset_index()


def tm_phase_table(pieces: pd.DataFrame) -> pd.DataFrame:
    """tracemalloc pieces per phase name: net retained MiB (sum), peak over the piece's start (max), traced
    peak (max) -- NaN for a phase tracing was paused over -- and the kernel dataset's time series at its end."""
    p = pieces[pieces["phase"] != "start"].copy()
    p["census_mib"] = p.get("census_local_mib", 0.0) + p.get("census_remote_mib", 0.0)
    return p.groupby("phase", sort=False).agg(tm_net_mib=("net_mib", "sum"),
                                              tm_alloc_peak_mib=("peak_over_start_mib", "max"),
                                              tm_traced_peak_mib=("peak_mib", "max"),
                                              ts_held_mib=("census_mib", "max")).reset_index()


# ------------------------------------------------------------ trace stage: figures

def plot_trace_timeline(samples: pd.DataFrame, pieces: list[dict], t0: float, hot: pd.DataFrame,
                        per_phase: pd.DataFrame, title: str, out_png: Path) -> None:
    """Phases as numbered spans over RSS, disk read and CPU of a clean pass; the top 5 functions of each
    phase by self time (viztracer pass) listed under it."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(dict.fromkeys(pc["name"] for pc in pieces))
    num = {n: i + 1 for i, n in enumerate(names)}
    lines = []
    for n in names:
        row = per_phase[per_phase["phase"] == n]
        secs = float(row["seconds"].iloc[0]) if len(row) else float("nan")
        peak = float(row["peak_rss_mib"].iloc[0]) / 1024 if len(row) and "peak_rss_mib" in row else float("nan")
        h = hot[hot["phase"] == n].head(5) if hot is not None and not hot.empty else pd.DataFrame()
        top5 = ";  ".join(f"{r.function.split(' (')[0]} {100 * r.share:.0f}%" for r in h.itertuples()) if len(h) else "-"
        lines.append(f"{num[n]:>2} {n[:38]:<38} {secs:7.1f} s {peak:5.1f} GiB | {top5}")
    n_lines = len(lines)
    fig = plt.figure(figsize=(20, 9.5 + 0.2 * n_lines))
    gs = fig.add_gridspec(4, 1, height_ratios=[3, 1.8, 1.6, 0.26 * n_lines + 1.2], hspace=0.12)
    axes = [fig.add_subplot(gs[0])]
    axes += [fig.add_subplot(gs[i], sharex=axes[0]) for i in (1, 2)]
    x = samples["t"].to_numpy() - t0
    ax = axes[0]
    ax.plot(x, samples["rss"] / GIB, color="k", lw=1.5, label="working set (RSS)")
    ax.plot(x, samples["private"] / GIB, color="k", lw=0.8, ls=":", label="private bytes")
    ax.set_ylabel("memory (GiB)")
    ax.set_ylim(0, max(samples["rss"].max(), samples["private"].max()) / GIB * 1.25)
    dtm = np.diff(samples["t"].to_numpy(), prepend=np.nan)
    ax = axes[1]
    for col, lab, sty in (("d_read", "machine disk read", dict(color="0.5", lw=0.8)),
                          ("p_read", "this run: read (incl. cache hits)", dict(color="tab:green", lw=1.3))):
        ax.plot(x, np.diff(samples[col].to_numpy(dtype=float), prepend=np.nan) / dtm / MB, label=lab, **sty)
    ax.set_yscale("symlog", linthresh=10)
    ax.set_ylabel("read (MB/s)")
    ax = axes[2]
    ax.plot(x, samples["cpu"] / 100.0, color="tab:red", lw=1.0, label="CPU (cores)")
    ax.set_ylabel("CPU (cores)")
    ax2 = ax.twinx()
    ax2.plot(x, samples["threads"], color="tab:blue", lw=0.8, ls=":")
    ax2.set_ylabel("threads (dotted)", color="tab:blue")
    ax.set_xlabel("seconds since the child started")
    cmap = plt.get_cmap("tab20")
    for pc in pieces:
        a, b = pc["t0"] - t0, pc["t1"] - t0
        colour = cmap((num[pc["name"]] - 1) % 20)
        for axx in axes[:3]:
            axx.axvspan(a, b, color=colour, alpha=0.18, lw=0)
            axx.axvline(a, color="0.4", lw=0.3)
        if b - a > 0.006 * (x[-1] if len(x) else 1):
            axes[0].text(0.5 * (a + b), axes[0].get_ylim()[1] * 0.98, str(num[pc["name"]]), ha="center", va="top",
                         fontsize=7)
    for axx in axes[:3]:
        axx.legend(loc="upper left", fontsize=8)
        axx.grid(alpha=0.25)
    axes[0].set_title(title, fontsize=10, loc="left")
    axt = fig.add_subplot(gs[3])
    axt.axis("off")
    axt.text(0.0, 0.93, "phase (clean pass: seconds, peak RSS) | top 5 functions by self time in the phase "
             "(viztracer pass; % of the phase's traced time)\n" + "\n".join(lines),
             family="monospace", fontsize=7.2, va="top", ha="left", transform=axt.transAxes)
    fig.savefig(out_png, dpi=100, bbox_inches="tight")
    plt.close(fig)


def plot_tm_retained(pieces: pd.DataFrame, owners: pd.DataFrame, title: str, out_png: Path) -> None:
    """Traced memory alive at the end of each phase piece, stacked by owner package; the piece's traced peak,
    the RSS at its end, and the kernel dataset's time series (census). The glue pieces between phases
    ("aurora (other)", "(untracked)") are left out; a piece tracing was paused over shows only RSS and census."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pieces = pieces[~pieces["phase"].isin(["aurora (other)", "(untracked)"])].reset_index(drop=True)
    traced = pieces["traced"].fillna(True).astype(bool) if "traced" in pieces else pd.Series(True, index=pieces.index)
    piv = owners.pivot_table(index="piece", columns="owner", values="MiB", aggfunc="sum").fillna(0.0)
    piv = piv.reindex(pieces["piece"]).fillna(0.0)
    piv = piv[piv.max().sort_values(ascending=False).index]
    keep = [c for c in piv.columns if piv[c].max() >= 5.0][:10]
    other = piv.drop(columns=keep).sum(axis=1)
    piv = piv[keep].assign(other=other)
    fig, ax = plt.subplots(figsize=(max(12, 0.36 * len(pieces)), 7.5))
    xs = np.arange(len(pieces))
    bottom = np.zeros(len(pieces))
    cmap = plt.get_cmap("tab20")
    for i, col in enumerate(piv.columns):
        ax.bar(xs, piv[col].to_numpy() / 1024, bottom=bottom / 1024, color=cmap(i % 20), label=col, width=0.85)
        bottom += piv[col].to_numpy()
    if "peak_mib" in pieces:
        ax.plot(xs, pieces["peak_mib"] / 1024, "v", color="k", ms=5, label="traced peak inside the piece")
    ax.plot(xs, pieces["rss_end_mib"] / 1024, "_", color="tab:red", ms=12, mew=2, label="RSS at the piece's end")
    if "census_local_mib" in pieces:
        census = (pieces["census_local_mib"].fillna(0) + pieces["census_remote_mib"].fillna(0)) / 1024
        ax.plot(xs, census, "o", mfc="none", color="tab:purple", ms=6,
                label="time series held by aurora's kernel dataset (census)")
    for x in xs[~traced.to_numpy()]:
        ax.axvspan(x - 0.45, x + 0.45, color="0.85", zorder=0)
        ax.text(x, ax.get_ylim()[1] * 0.5, "tracemalloc paused", rotation=90, ha="center", va="center", fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{r.piece} {r.phase}" for r in pieces.itertuples()], rotation=90, fontsize=7)
    ax.set_ylabel("GiB")
    ax.set_title(title, fontsize=10, loc="left")
    ax.legend(fontsize=8, loc="upper right", ncol=2)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=100)
    plt.close(fig)


def phase_kind(phase: str) -> str:
    """A phase's kind across levels: read, decimate, STFT, merge, features, regression, setup, end, other."""
    m = re.match(r"^L\d+ (.+)$", phase)
    if m:
        return {"read TS": "read", "decimate TS": "decimate", "STFT": "STFT", "merge STFTs": "merge",
                "features/weights": "features", "regression": "regression"}.get(m[1], "other")
    if phase in ("survey load", "kernel dataset", "aurora config", "aurora setup"):
        return "setup"
    if phase in ("TF assembly (export_tf_collection)", "close archives", "EDI write"):
        return "end"
    return "other"


def compare_functions(fork_csv: Path, stock_csv: Path, top: int = 40) -> pd.DataFrame | None:
    """Self seconds per (phase kind, function), fork vs stock, from the viztracer passes: the `top` largest differences."""
    if not (fork_csv.exists() and stock_csv.exists()):
        return None
    parts = []
    for tag, path in (("fork", fork_csv), ("stock", stock_csv)):
        d = pd.read_csv(path)
        d["kind"] = d["phase"].map(phase_kind)
        g = d.groupby(["kind", "function"])[["self_s", "calls"]].sum()
        g.columns = [f"{tag}_self_s", f"{tag}_calls"]
        parts.append(g)
    c = parts[0].join(parts[1], how="outer").fillna(0.0).reset_index()
    c["fork_minus_stock_s"] = c["fork_self_s"] - c["stock_self_s"]
    c = c.reindex(c["fork_minus_stock_s"].abs().sort_values(ascending=False).index).head(top)
    return c.reset_index(drop=True)


def plot_trace_compare(cmp: pd.DataFrame, title: str, out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    c = cmp[cmp["phase"] != "whole run"].copy()
    c = c[(c[["fork_s", "stock_s"]].max(axis=1) >= 0.5)]
    fig, axes = plt.subplots(1, 3, figsize=(20, 0.32 * len(c) + 2.5), sharey=True)
    ys = np.arange(len(c))[::-1]
    for ax, (col, lab) in zip(axes, (("s", "seconds (mean of the two clean passes)"),
                                     ("peak_mib", "peak RSS in the phase (MiB)"),
                                     ("alloc_mib", "traced allocation peak over the phase's start (MiB)"))):
        ax.barh(ys + 0.2, c[f"stock_{col}"], height=0.4, color="0.6", label="stock 0.6.2")
        ax.barh(ys - 0.2, c[f"fork_{col}"], height=0.4, color="tab:blue", label="fork 0.6.2+mtproc")
        ax.set_xlabel(lab)
        ax.grid(axis="x", alpha=0.3)
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels(c["phase"], fontsize=8)
    axes[0].legend(fontsize=8)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png, dpi=100)
    plt.close(fig)


# ------------------------------------------------------------ trace stage: orchestration (parent)

def _pyspy_exe() -> str | None:
    import shutil

    cand = Path(sys.executable).parent / "Scripts" / "py-spy.exe"
    return str(cand) if cand.exists() else shutil.which("py-spy")


def ensure_stock_aurora(path: Path) -> Path:
    """A worktree of the fork's clone at stock 0.6.2's commit (created once; the clone itself is never checked out)."""
    init = path / "aurora" / "__init__.py"
    if not init.exists():
        clone = Path(os.environ.get("MTPROC_FORKS", r"D:\BEN")) / "aurora"
        subprocess.run(["git", "-C", str(clone), "worktree", "add", "--detach", str(path), STOCK_AURORA_BASE],
                       check=True, capture_output=True, text=True)
    text = init.read_text(encoding="utf-8")
    if "+mtproc" in text or "0.6.2" not in text:
        raise SystemExit(f"{init} is not stock aurora 0.6.2")
    return path


def _pyspy_hook(log_path: Path, out_file: Path, fmt: str, flags: list[str], go_file: Path, spy_log: Path):
    """on_spawn for run_sampled: once the child's interpreter is up, attach py-spy, then let the child go."""

    def start(pid: int):
        t0 = time.time()
        while time.time() - t0 < 180:
            if log_path.exists() and "PROFINFO pid" in log_path.read_text(encoding="utf-8", errors="replace"):
                break
            time.sleep(0.2)
        spy = subprocess.Popen([_pyspy_exe(), "record", "--pid", str(pid), "--rate", "200", "--format", fmt,
                                "-o", str(out_file), *flags],
                               stdout=open(spy_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 30:
            if spy_log.exists() and "Sampling process" in spy_log.read_text(encoding="utf-8", errors="replace"):
                break
            time.sleep(0.1)
        go_file.touch()
        return [spy]

    return start


def trace_runs(args, survey, survey_yaml: str, out: Path, run_id: str, local_h5: Path, remote_h5: Path,
               stock_dir: Path | None) -> None:
    """Every pass of every variant as a sampled child (see the trace stage's header comment)."""
    for variant in args.variants:
        vstem = f"trace_{variant}_{run_id}"
        env = child_env([stock_dir] if variant == "stock" else [])
        for pas in args.passes:
            stem = f"{vstem}_{pas}"
            go = out / f"{stem}.go"
            go.unlink(missing_ok=True)
            spec = {"survey": survey_yaml, "local": args.local, "remote": args.remote, "local_h5": str(local_h5),
                    "remote_h5": str(remote_h5), "start": args.window[0], "end": args.window[1],
                    "output_channels": ["ex", "ey"], "pass": pas, "out_stem": str(out / stem),
                    "edi_dir": str(out / "edi"), "viz_min_us": args.viz_min_us, "viz_entries": args.viz_entries,
                    "viz_depth": args.viz_depth, "tm_nframe": args.tm_nframe, "tm_pause": args.tm_pause,
                    "snap_step_gib": 0.25,
                    "go_file": str(go) if pas.startswith("pyspy") else None}
            hook = None
            if pas.startswith("pyspy"):
                if _pyspy_exe() is None:
                    print(f"{stem}: py-spy not found, pass skipped", flush=True)
                    continue
                fmt, flags, ext = (("speedscope", ["--idle"], "speedscope.json") if pas == "pyspy-idle"
                                   else ("flamegraph", ["--gil"], "svg"))
                hook = _pyspy_hook(out / f"{stem}.log", out / f"{stem}.{ext}", fmt, flags, go, out / f"{stem}_pyspy.log")
            wait_for_memory(args.need_gb if args.need_gb is not None else NEED_GB["trace"], args.other_peak_gb)
            cmd = child_cmd("trace", spec, out / f"{stem}_spec.json", True)
            print(f"[{dt.datetime.now():%H:%M:%S}] trace {variant} {pas} -> {out / stem}.log", flush=True)
            samples, t_spawn, t_end, rc = run_sampled(cmd, out / f"{stem}.log", 0.25, env, on_spawn=hook)
            analyse(out / f"{stem}.log", samples, t_spawn, t_end, out, stem, "trace", f"; {variant} aurora, {pas}")
            go.unlink(missing_ok=True)
            print(f"[{dt.datetime.now():%H:%M:%S}] trace {variant} {pas}: exit {rc}, {t_end - t_spawn:.0f} s, "
                  f"peak RSS {samples['rss'].max() / GIB:.1f} GiB", flush=True)
            if rc != 0:
                raise SystemExit(f"{stem} failed (exit {rc}): see {out / stem}.log")


def _pass_files(out: Path, stem: str):
    log = out / f"{stem}.log"
    if not log.exists():
        return None
    samples = pd.read_csv(out / f"{stem}_samples.csv")
    t_start, t_end = float(samples["t"].iloc[0]), float(samples["t"].iloc[-1])
    pieces = _phase_pieces(log, t_start, t_end)
    table = phase_table(pieces, samples, t_start)
    text = log.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"PROFINFO aurora (\S+) from (.+)", text)
    return {"samples": samples, "t_start": t_start, "pieces": pieces, "table": table,
            "aurora": m[1] if m else "?", "aurora_path": m[2].strip() if m else "?", "log": text}


def trace_report(out: Path, run_id: str, variants: list[str]) -> None:
    """Per variant: <vstem>_trace_phases.csv, _trace_timeline.png, _viz_hot.csv, _calls_by_level.csv,
    _h5reads_summary.csv, _pyspy_top.csv, _tm_retained.png; then the fork-vs-stock comparison."""
    per_variant = {}
    for variant in variants:
        vstem = f"trace_{variant}_{run_id}"
        passes = {p: _pass_files(out, f"{vstem}_{p}") for p in TRACE_PASSES}
        clean = next((passes[p] for p in TRACE_PASSES if passes[p] is not None), None)  # a clean pass if any
        if clean is None:
            print(f"{vstem}: no clean pass to report", flush=True)
            continue
        expect_fork = variant == "fork"
        for p, info in passes.items():
            if info is not None and ("+mtproc" in info["aurora"]) != expect_fork:
                raise SystemExit(f"{vstem}_{p} ran aurora {info['aurora']} ({info['aurora_path']}): not the {variant}")
        phases = agg_phases(clean["table"])
        other = passes["pyspy-gil"] if clean is passes["pyspy-idle"] else None
        if other is not None:
            phases = phases.merge(agg_phases(other["table"])[["phase", "seconds"]].rename(
                columns={"seconds": "seconds_rerun"}), on="phase", how="left")
        bnd_path = out / f"{vstem}_pyspy-idle_boundaries.csv"
        if bnd_path.exists():
            phases = phases.merge(boundary_deltas(pd.read_csv(bnd_path)), on="phase", how="left")
        hot = pd.DataFrame()
        viz = passes["viztracer"]
        meta_path = out / f"{vstem}_viztracer_meta.json"
        if viz is not None and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            va = viz_analyse(out / f"{vstem}_viztracer.json", meta, viz["pieces"])
            hot = va["hot"]
            hot.to_csv(out / f"{vstem}_viz_hot.csv", index=False)
            va["calls"].to_csv(out / f"{vstem}_viz_calls.csv", index=False)
            va["callers"].to_csv(out / f"{vstem}_viz_callers.csv", index=False)
            va["self_all"].to_csv(out / f"{vstem}_viz_self.csv", index=False)
            vt = agg_phases(viz["table"])[["phase", "seconds"]].rename(columns={"seconds": "viz_seconds"})
            vt["viz_gc_s"] = vt["phase"].map(va["gc"]).fillna(0.0) / 1e6
            phases = phases.merge(vt, on="phase", how="left")
            vj = out / f"{vstem}_viztracer.json"
            gz = vj.with_suffix(".json.gz")
            if not gz.exists():  # for ui.perfetto.dev (it opens gzip); the .json for vizviewer
                import gzip
                import shutil

                with open(vj, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
                    shutil.copyfileobj(f, g, 1 << 24)
            print(f"{vstem}: viztracer {vj.stat().st_size / MB:.0f} MB ({gz.stat().st_size / MB:.0f} MB gzipped), "
                  f"{va['fee_events']} call events ({va['events']} in all)"
                  + (" -- BUFFER OVERFLOWED, the earliest calls are missing" if va["overflow"] else ""), flush=True)
        tm_p = out / f"{vstem}_tracemalloc_tm_pieces.csv"
        if tm_p.exists():
            pieces_tm = pd.read_csv(tm_p)
            phases = phases.merge(tm_phase_table(pieces_tm), on="phase", how="left")
            owners = pd.read_csv(out / f"{vstem}_tracemalloc_tm_owners.csv")
            sites_raw = out / f"{vstem}_tracemalloc_tm_sites.csv"
            if sites_raw.exists() and sites_raw.stat().st_size > 5:
                tm_resolve(pd.read_csv(sites_raw)).drop(columns=["site_file", "site_line", "chain_frames"]).to_csv(
                    out / f"{vstem}_tm_top_sites.csv", index=False)
            peak_raw = out / f"{vstem}_tracemalloc_tm_peak.csv"
            if peak_raw.exists() and peak_raw.stat().st_size > 5:
                tm_resolve(pd.read_csv(peak_raw)).drop(columns=["site_file", "site_line", "chain_frames"]).to_csv(
                    out / f"{vstem}_tm_peak_sites.csv", index=False)
            plot_tm_retained(pieces_tm, owners, f"{vstem}: traced memory alive at each phase piece's end, by owner "
                             f"(tracemalloc pass; the innermost MT-package frame, else the allocating package)",
                             out / f"{vstem}_tm_retained.png")
        if not hot.empty:
            top5 = hot.groupby("phase", sort=False).head(5).groupby("phase", sort=False).apply(
                lambda g: "; ".join(f"{f.split(' (')[0]} {100 * s:.0f}%" for f, s in zip(g["function"], g["share"])),
                include_groups=False)
            phases["top5_self_time"] = phases["phase"].map(top5)
        phases.to_csv(out / f"{vstem}_trace_phases.csv", index=False)
        calls_path = out / f"{vstem}_pyspy-idle_calls.csv"
        if calls_path.exists():
            calls = pd.read_csv(calls_path)
            calls["group"] = calls["phase"].map(_level_group)
            by = calls.groupby(["target", "group"], sort=False)[["calls", "outer_calls", "seconds", "MB"]].sum().reset_index()
            by.to_csv(out / f"{vstem}_calls_by_level.csv", index=False)
        reads_path = out / f"{vstem}_pyspy-idle_h5reads.csv"
        if reads_path.exists() and reads_path.stat().st_size > 5:
            h5reads_summary(pd.read_csv(reads_path)).to_csv(out / f"{vstem}_h5reads_summary.csv", index=False)
        ss = out / f"{vstem}_pyspy-idle.speedscope.json"
        svg = out / f"{vstem}_pyspy-gil.svg"
        if ss.exists():
            top, threads = pyspy_speedscope(ss)
            if svg.exists():
                gil, gil_total = pyspy_svg(svg)
                top = top.merge(gil, on="function", how="left")
                top["gil_incl_samples"] = top["gil_incl_samples"].fillna(0)
                print(f"{vstem}: py-spy --idle {sum(threads.values())} samples over {len(threads)} thread(s); "
                      f"--gil {gil_total} samples", flush=True)
            top.to_csv(out / f"{vstem}_pyspy_top.csv", index=False)
        s = clean["samples"]
        title = (f"{vstem}: aurora {clean['aurora']}; clean pass {s['t'].iloc[-1] - s['t'].iloc[0]:.0f} s, "
                 f"peak RSS {s['rss'].max() / GIB:.2f} GiB, mean CPU {s['cpu'].iloc[1:].mean() / 100:.2f} cores")
        plot_trace_timeline(s, clean["pieces"], clean["t_start"], hot, phases, title, out / f"{vstem}_trace_timeline.png")
        per_variant[variant] = phases
        with pd.option_context("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 60):
            print(phases.drop(columns=[c for c in ("top5_self_time",) if c in phases]).round(2).to_string(index=False))
    if {"fork", "stock"} <= set(per_variant):
        rows = []
        f, s = per_variant["fork"].set_index("phase"), per_variant["stock"].set_index("phase")
        for ph in list(dict.fromkeys(list(s.index) + list(f.index))):
            r = {"phase": ph}
            for tag, t in (("fork", f), ("stock", s)):
                have = ph in t.index
                secs = t.loc[ph, ["seconds", "seconds_rerun"]].mean() if have and "seconds_rerun" in t else (
                    t.loc[ph, "seconds"] if have else np.nan)
                r[f"{tag}_s"] = secs
                r[f"{tag}_peak_mib"] = t.loc[ph, "peak_rss_mib"] if have else np.nan
                r[f"{tag}_alloc_mib"] = t.loc[ph, "tm_alloc_peak_mib"] if have and "tm_alloc_peak_mib" in t else np.nan
                r[f"{tag}_net_mib"] = t.loc[ph, "tm_net_mib"] if have and "tm_net_mib" in t else np.nan
                r[f"{tag}_read_mb"] = t.loc[ph, "proc_read_mb"] if have else np.nan
            rows.append(r)
        cmp = pd.DataFrame(rows)
        tot = {"phase": "whole run"}
        for c in cmp.columns[1:]:
            tot[c] = cmp[c].max() if ("peak" in c or "alloc" in c) else cmp[c].sum()
        cmp = pd.concat([cmp, pd.DataFrame([tot])], ignore_index=True)
        cmp["fork_minus_stock_s"] = cmp["fork_s"] - cmp["stock_s"]
        cmp.to_csv(out / f"trace_compare_{run_id}.csv", index=False)
        fn_cmp = compare_functions(out / f"trace_fork_{run_id}_viz_self.csv", out / f"trace_stock_{run_id}_viz_self.csv")
        if fn_cmp is not None:
            fn_cmp.to_csv(out / f"trace_compare_functions_{run_id}.csv", index=False)
        plot_trace_compare(cmp, f"fork vs stock aurora per phase, {run_id}", out / f"trace_compare_{run_id}.png")
        with pd.option_context("display.width", 250, "display.max_columns", 30):
            print(cmp.round(1).to_string(index=False))


def run_trace(args, survey, survey_yaml: str, out: Path) -> int:
    if args.reanalyse:  # tables and figures only: no archive resolved, no aurora imported
        trace_report(out, args.reanalyse, args.variants)
        return 0
    from mtproc.ingest import variant_path

    if not args.read_archives:
        raise SystemExit("--stage trace reads the archives named by --read-archives DIR (the sites' filtered variants)")
    arch = Path(args.read_archives)
    local_h5 = arch / variant_path(survey, args.local).name
    remote_h5 = arch / variant_path(survey, args.remote).name
    for p in (local_h5, remote_h5):
        if not p.exists():
            raise SystemExit(f"{p} does not exist (the trace stage never builds a variant)")
    if not args.window:
        raise SystemExit("--stage trace needs --window START END")
    print(f"trace: {local_h5.name} rr {remote_h5.name}, window {args.window[0]} to {args.window[1]} UTC", flush=True)
    run_id = f"{args.local}_rr-{args.remote}_{dt.datetime.now():%Y%m%d-%H%M}"
    stock_dir = ensure_stock_aurora(Path(args.stock_aurora) if args.stock_aurora else out / "aurora-stock") \
        if "stock" in args.variants else None
    trace_runs(args, survey, survey_yaml, out, run_id, local_h5, remote_h5, stock_dir)
    trace_report(out, run_id, args.variants)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="profile_run.py", description=__doc__.split("\n\nUsage:")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("survey_yaml", nargs="?")
    p.add_argument("local", nargs="?")
    p.add_argument("remote", nargs="?")
    p.add_argument("--stage", default="rr",
                   choices=["rr", "ingest", "variant", "stack", "read", "cprofile", "tracemalloc", "trace", "all"])
    p.add_argument("--out", default=None, help="output folder (default: <workspace>/profile)")
    p.add_argument("--site", default=None, help="site for ingest/variant and the B423 benchmark (default: local)")
    p.add_argument("--members", nargs="+", default=None, help="stack members (default: local remote site)")
    p.add_argument("--stack-start", default=None, help="UTC; default the members' common span (survey.yaml)")
    p.add_argument("--stack-end", default=None)
    p.add_argument("--weighting", default="none", choices=["none", "coherence"])
    p.add_argument("--rw-archive", default=None, help="a dedicated archive for the read-write open timing")
    p.add_argument("--read-archives", default=None, help="folder the --read-sites archives are read from")
    p.add_argument("--read-sites", nargs="+", default=[], help="sites whose archives are read from --read-archives")
    p.add_argument("--tag", default="profile", help="process_rr --tag for the products")
    p.add_argument("--window", nargs=2, default=None, metavar=("START", "END"),
                   help="process_rr's processing window (UTC) for rr/cprofile/tracemalloc, e.g. a few hours")
    p.add_argument("--snap-step-gb", type=float, default=2.0,
                   help="tracemalloc: a snapshot each time the RSS passes its previous high by this much (GiB)")
    p.add_argument("--interval", type=float, default=0.5, help="sampling interval (s)")
    p.add_argument("--no-markers", action="store_true", help="run the step bare: phases from its own log lines")
    p.add_argument("--need-gb", type=float, default=None,
                   help="wait for this much memory first (default: rr/cprofile/tracemalloc 58, others 25; 0 = never)")
    p.add_argument("--other-peak-gb", type=float, default=62.0,
                   help="what a young process_rr.py job elsewhere may still grow to (GiB)")
    p.add_argument("--variants", nargs="+", default=["fork", "stock"], choices=["fork", "stock"],
                   help="trace: the environment's aurora (fork) and/or stock 0.6.2 (--stock-aurora first on PYTHONPATH)")
    p.add_argument("--stock-aurora", default=None,
                   help="trace: stock aurora checkout (default <out>/aurora-stock, a worktree of the fork's clone "
                        f"at {STOCK_AURORA_BASE}, made if missing)")
    p.add_argument("--passes", nargs="+", default=list(TRACE_PASSES), choices=list(TRACE_PASSES),
                   help="trace: which passes to run")
    p.add_argument("--viz-min-us", type=float, default=10.0,
                   help="trace: viztracer keeps calls lasting at least this long (microseconds)")
    p.add_argument("--viz-entries", type=int, default=10_000_000, help="trace: viztracer buffer (events)")
    p.add_argument("--viz-depth", type=int, default=-1, help="trace: viztracer max_stack_depth (-1: unlimited)")
    p.add_argument("--tm-nframe", type=int, default=10,
                   help="trace: tracemalloc frames kept per allocation (cost per allocation grows with it)")
    p.add_argument("--tm-pause", nargs="*", default=["L0 read TS"],
                   help="trace: phases tracemalloc stops over (per-sample Python objects make them crawl when traced)")
    p.add_argument("--reanalyse", default=None, metavar="RUN_ID",
                   help="trace: only redo the tables and figures of an earlier run, e.g. C18_rr-C19_20260924-1300")
    p.add_argument("--parse-log", nargs="+", default=None, help="only parse these bare process_rr logs")
    p.add_argument("--ledger", default=None, help="only summarise this campaign folder (ledger.csv, runs.log)")
    return p


NEED_GB = {"rr": 58.0, "cprofile": 58.0, "tracemalloc": 60.0, "ingest": 25.0, "variant": 28.0,
           "stack": 10.0, "read": 20.0, "trace": 15.0}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--child"]:
        return child_main(argv[1], argv[2])
    args = build_parser().parse_args(argv)
    if args.parse_log or args.ledger:
        out = Path(args.out or ".")
        out.mkdir(parents=True, exist_ok=True)
        if args.parse_log:
            parse_logs([Path(p) for p in args.parse_log], out)
        if args.ledger:
            ledger_stats(Path(args.ledger), out)
        return 0
    if not (args.survey_yaml and args.local and args.remote):
        build_parser().error("survey_yaml, local and remote are required")
    from mtproc.survey import Survey

    survey_yaml = str(Path(args.survey_yaml).resolve())
    survey = Survey.from_yaml(survey_yaml)
    out = Path(args.out) if args.out else survey.workspace / "profile"
    out.mkdir(parents=True, exist_ok=True)
    site = args.site or args.local
    if args.read_archives and site in args.read_sites and args.stage in ("ingest", "variant", "all"):
        raise SystemExit(f"{site} is in --read-sites: ingest/variant would write over a real archive's name")
    if args.stage == "trace":
        return run_trace(args, survey, survey_yaml, out)
    stages = ["ingest", "variant", "stack", "read", "rr", "cprofile"] if args.stage == "all" else [args.stage]
    results = {}
    for stage in stages:
        need = args.need_gb if args.need_gb is not None else NEED_GB[stage]
        common = {"survey": survey_yaml, "local": args.local, "remote": args.remote, "site": site,
                  "read_archives": args.read_archives, "read_sites": args.read_sites}
        if stage in ("rr", "cprofile", "tracemalloc"):
            tag = args.tag if stage == "rr" else f"{args.tag}-{stage}"
            spec = {**common, "argv": [survey_yaml, args.local, args.remote, *(args.window or []), "--tag", tag],
                    "snap_step_gib": args.snap_step_gb}
            who = f"{args.local}_rr-{args.remote}"
        elif stage == "ingest":
            from mtproc.ingest import default_archive_path

            force = ["--force"] if default_archive_path(survey, site).exists() else []
            if force and default_archive_path(survey, site).stat().st_nlink > 1:
                raise SystemExit(f"{default_archive_path(survey, site)} is a hard link to another archive: "
                                 f"ingest into a workspace where {site} has no archive")
            spec = {**common, "argv": [survey_yaml, site, "--raw", *force]}
            who = site
        elif stage == "variant":
            spec = common
            who = site
        elif stage == "stack":
            members = args.members or list(dict.fromkeys([args.local, args.remote, site]))
            start, end = args.stack_start, args.stack_end
            if not (start and end):
                spans = [(pd.Timestamp(survey.site(m).start), pd.Timestamp(survey.site(m).end)) for m in members]
                start = start or f"{max(s for s, _ in spans):%Y-%m-%d %H:%M:%S}"
                end = end or f"{min(e for _, e in spans):%Y-%m-%d %H:%M:%S}"
            name = f"PSTK{dt.datetime.now():%H%M%S}"
            spec = {**common, "argv": [survey_yaml, name, start, end, *members, "--weighting", args.weighting]}
            who = "-".join(members)
        else:  # read
            spec = {**common, "rw_archive": args.rw_archive, "b423_site": site}
            who = args.local
        res = run_stage(stage, spec, out, who, args.interval, not args.no_markers, need, args.other_peak_gb)
        results[stage] = res
        if stage in ("ingest", "variant") and res["rc"] == 0:
            from mtproc.ingest import default_archive_path, select_files, variant_path

            path = default_archive_path(survey, site) if stage == "ingest" else variant_path(survey, site)
            raw_bytes = sum(f.stat().st_size for f in select_files(survey.site_dirs()[site])) \
                if stage == "ingest" else None
            lay = h5_layout(path, raw_bytes)
            lay.to_csv(out / f"{res['stem']}_h5layout.csv", index=False)
            print(f"{path.name}: {lay.attrs['file_MB']:.0f} MB on disk"
                  + (f", raw B423 files {lay.attrs['raw_MB']:.0f} MB" if raw_bytes else "")
                  + f", float64 in memory {lay['float64_MB'].sum():.0f} MB", flush=True)
            print(lay.to_string(index=False), flush=True)
        if res["rc"] != 0:
            print(f"{stage} failed (exit {res['rc']}): see {out / res['stem']}.log", flush=True)
            if args.stage == "all":
                return res["rc"]
    return 0


if __name__ == "__main__":
    sys.exit(main())
