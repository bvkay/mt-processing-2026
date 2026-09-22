"""Profile one processing step: time, memory, CPU and disk, split into phases.

Usage:
    python scripts/profile_run.py <survey.yaml> <local> <remote>
        [--stage rr|ingest|variant|stack|read|cprofile|tracemalloc|all] [--out DIR]
        [--site SITE] [--members A B C] [--stack-start UTC --stack-end UTC]
        [--rw-archive H5] [--read-archives DIR --read-sites S [S ...]]
        [--interval 0.5] [--need-gb GB] [--no-markers]
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


def _mark(flag: str, kind: str, name: str) -> None:
    sys.__stderr__.write(f"{MARK} {time.time():.6f} {flag} {kind} {name}\n")
    sys.__stderr__.flush()


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

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if i_level is not None:
            level = kwargs.get("i_dec_level", args[i_level] if len(args) > i_level else None)
            if level is not None:
                _LEVEL[0] = int(level)
        name = label.replace("{L}", str(_LEVEL[0]))
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


def child_main(stage: str, spec_path: str) -> int:
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
    if spec.get("markers", True):
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
    for key in ("site-packages/", "/src/", "/scripts/"):
        if key in f:
            return f.split(key, 1)[1]
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

def run_sampled(cmd: list[str], log_path: Path, interval: float = 0.5, env=None):
    """Run `cmd` with stdout+stderr to `log_path`, sampling it every `interval` s; (samples, t_spawn, t_end, rc)."""
    rows = []
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        t_spawn = time.time()
        child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO), env=env)
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
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(REPO / "src")}
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="profile_run.py", description=__doc__.split("\n\nUsage:")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("survey_yaml", nargs="?")
    p.add_argument("local", nargs="?")
    p.add_argument("remote", nargs="?")
    p.add_argument("--stage", default="rr",
                   choices=["rr", "ingest", "variant", "stack", "read", "cprofile", "tracemalloc", "all"])
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
    p.add_argument("--parse-log", nargs="+", default=None, help="only parse these bare process_rr logs")
    p.add_argument("--ledger", default=None, help="only summarise this campaign folder (ledger.csv, runs.log)")
    return p


NEED_GB = {"rr": 58.0, "cprofile": 58.0, "tracemalloc": 60.0, "ingest": 25.0, "variant": 28.0,
           "stack": 10.0, "read": 20.0}


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
