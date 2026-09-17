"""Aurora transfer-function estimation wrappers."""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from pathlib import Path

import aurora.pipelines.transfer_function_helpers as _tf_helpers
import numpy as np
import pandas as pd
from aurora.config.config_creator import ConfigCreator
from aurora.pipelines.process_mth5 import process_mth5
from loguru import logger

from mth5.mth5 import MTH5

from .masks import applies, apply_time_masks, split_by_bands, windows_in_mask

try:  # newer stacks host these in mth5
    from mth5.processing import KernelDataset, RunSummary
except ImportError:  # older aurora
    from aurora.pipelines.run_summary import RunSummary
    from aurora.transfer_function.kernel_dataset import KernelDataset


def clip_to_window(kd, start=None, end=None):
    """Restrict a KernelDataset to [start, end) UTC without touching the MTH5s.

    The archive keeps every run; which part of it goes into an estimate is a
    processing decision (e.g. Burra35's Ex died 16.5 h in). Runs entirely
    outside the window are dropped, runs straddling it are trimmed.
    """
    if start is None and end is None:
        return kd
    df = kd.df.copy()
    if start is not None:
        df["start"] = df["start"].clip(lower=pd.Timestamp(start, tz="UTC"))
    if end is not None:
        df["end"] = df["end"].clip(upper=pd.Timestamp(end, tz="UTC"))
    df = df[df["end"] > df["start"]]
    if df.empty:
        raise ValueError(f"no data in processing window [{start}, {end})")
    kd.df = df
    kd._update_duration_column()
    # restrict_run_intervals_to_simultaneous intersects local against remote
    # runs; with no remote (single-station) its remote_df is always empty, so
    # it raises "do not overlap" on every call. Only meaningful, and only
    # safe to call, in RR mode.
    if kd.remote_station_id:
        kd.df = kd.restrict_run_intervals_to_simultaneous(kd.df)
    logger.info(
        f"processing window [{start}, {end}) UTC -> {len(kd.df)} run interval(s), "
        f"{kd.df.duration.sum() / 3600:.1f} station-hours"
    )
    return kd


# What a run without tweaks uses on every decimation level: aurora 0.6.2's
# ConfigCreator values (overlap_pct: 25 %, then `build_config` boosts levels
# whose window lasts over 600 s to 75 %) except the taper, which `build_config`
# sets to Hann (aurora's own is boxcar, `AURORA_TAPER`): the boxcar's leakage
# put D13's 50 Hz line into every 12-46 Hz band at Morocco D03, Hann removed
# that and lost nothing on Curnamona D02.
# tests/process_rr_cli_unit.py builds a real config and fails if these stop
# being the in-use values.
ESTIMATOR_DEFAULTS = {
    "taper": "hann",
    "overlap_pct": 25.0,
    "prewhiten": True,
    "min_windows": 0,
    "max_iterations": 10,
    "redescending_iterations": 2,
    "r0": 1.5,
    "u0": 2.8,
    "tolerance": 0.005,
}
TAPERS = ("boxcar", "hamming", "hann", "dpss")
AURORA_TAPER = "boxcar"  # what ConfigCreator sets; a run gets ESTIMATOR_DEFAULTS["taper"] unless told otherwise
DPSS_NW = 3.0  # scipy's dpss window needs a time-bandwidth product; none is set by aurora


# mth5's RunSummary opens every archive read-write to read run metadata, and a
# read-write open fails while any other process holds the archive read-only
# (the GUI drawing a window). Processing never writes to an archive, so the
# summary is read read-only here; see docs/upstream_issues.md, 5.
import mth5.processing.run_summary as _run_summary

_mth5_initialize = _run_summary.initialize_mth5


def _read_only_run_summary(path, mode="a", **kwargs):
    return _mth5_initialize(path, mode="r", **kwargs)


if _run_summary.initialize_mth5 is not _read_only_run_summary:
    _run_summary.initialize_mth5 = _read_only_run_summary


@contextmanager
def _archives_read_only():
    """Every `MTH5.open_mth5` inside the block opens read-only.

    `KernelDataset.from_run_summary` opens the local archive with mth5's
    default mode ("a") just to read the survey metadata; read-write opens
    fail while any other process holds the archive read-only (the GUI drawing
    a window) and touch the file's timestamp. Scoped, so ingest in the same
    process still writes.
    """
    original = MTH5.open_mth5

    def read_only(self, filename=None, mode="r", **kwargs):
        return original(self, filename, mode="r", **kwargs)

    MTH5.open_mth5 = read_only
    try:
        yield
    finally:
        MTH5.open_mth5 = original


# Band-limited masks reach aurora through a scoped patch (docs/upstream_issues.md
# 22: aurora 0.6.2 takes no per-band window weights or masks from outside).
# Both of its regression loops take a band's Fourier coefficients from the one
# function, looked up in `aurora.pipelines.transfer_function_helpers`' globals
# at call time:
#   line 249, process_transfer_functions:
#       X, Y, RR = get_band_for_tf_estimate(band, dec_level_config, local_stft_obj, remote_stft_obj)
#   line 339, process_transfer_functions_with_weights (per output channel):
#       X, Y, RR = get_band_for_tf_estimate(band, dec_level_config, local_stft_obj, remote_stft_obj)
# (`process_mth5.process_tf_decimation_level` tries the second, falls back to the
# first). `_band_masks_applied` wraps that name, so a band a mask covers gets
# X, Y, RR without the masked windows: dropped, not zero-weighted, so aurora's
# own weighting (edf weights, the robust regression) never sees them.
# `_check_band_patch` fails loudly if aurora moves any of it.
BAND_PATCH_NAME = "get_band_for_tf_estimate"
BAND_PATCH_PARAMETERS = ("band", "dec_level_config", "local_stft_obj", "remote_stft_obj")
BAND_PATCH_CALLERS = ("process_transfer_functions", "process_transfer_functions_with_weights")
STFT_TIME = "time"  # the STFT's window axis: naive UTC datetime64, each window's first sample
MIN_MASKED_WINDOWS = 4  # a band mask never leaves a band fewer windows (nor under the level's min_num_stft_windows)


def _check_band_patch() -> None:
    """RuntimeError unless aurora still routes both regression loops through the wrapped name."""
    target = getattr(_tf_helpers, BAND_PATCH_NAME, None)
    if target is None:
        raise RuntimeError(f"aurora.pipelines.transfer_function_helpers has no {BAND_PATCH_NAME}: "
                           "band-limited masks cannot be applied (see mtproc.process)")
    got = tuple(inspect.signature(target).parameters)
    if got != BAND_PATCH_PARAMETERS:
        raise RuntimeError(f"aurora's {BAND_PATCH_NAME} now takes {got}, the band-mask patch expects "
                           f"{BAND_PATCH_PARAMETERS}")
    for name in BAND_PATCH_CALLERS:
        fn = getattr(_tf_helpers, name, None)
        if fn is None or fn.__globals__ is not vars(_tf_helpers) or BAND_PATCH_NAME not in fn.__code__.co_names:
            raise RuntimeError(f"aurora's {name} no longer calls transfer_function_helpers.{BAND_PATCH_NAME}: "
                               "the band-mask patch would not act")


def _mask_label(mask: dict) -> str:
    return (f"{mask['start']} to {mask['end']} [{mask['bands'][0]:g}, {mask['bands'][1]:g}] s")


class _BandMaskLog:
    """What `_band_masks_applied` did: per decimation level, per band a mask covers,
    {"windows", "lost", "skipped"}; one log line per level, when the next level starts
    or the block ends. Aurora asks for a band once per output channel, so a band is
    recorded (and counted) once."""

    def __init__(self, masks):
        self.masks = masks
        self.levels: dict[int, dict[float, dict]] = {}
        self.errors: list[str] = []
        self.calls = 0
        self._matched: set[int] = set()
        self._current: int | None = None
        self._flushed: set[int] = set()

    def record(self, level: int, period: float, windows: int, lost: int, skipped: list, matched) -> None:
        if self._current is not None and level != self._current:
            self._flush(self._current)
        self._current = level
        self._matched.update(matched)
        self.levels.setdefault(level, {})[period] = {"windows": windows, "lost": lost, "skipped": skipped}

    def lost(self) -> dict[float, int]:
        """{band centre period: windows dropped}, every band a mask covered."""
        return {p: b["lost"] for bands in self.levels.values() for p, b in bands.items()}

    def _flush(self, level: int) -> None:
        if level in self._flushed:
            return
        self._flushed.add(level)
        parts = []
        for period, b in sorted(self.levels.get(level, {}).items()):
            parts.append(f"{period:.4g} s lost {b['lost']} of {b['windows']} windows")
            for m in b["skipped"]:
                parts.append(f"mask {_mask_label(m)} skipped at {period:.4g} s (it would leave fewer "
                             f"than the band's minimum)")
        logger.info(f"band masks, decimation level {level}: " + "; ".join(parts))

    def close(self) -> None:
        if self._current is not None:
            self._flush(self._current)
        for i, m in enumerate(self.masks):
            if i not in self._matched:
                logger.warning(f"band mask {_mask_label(m)} covers no band's centre period: not applied")


def _drop_masked_windows(band, dec_level_config, X, Y, RR, masks, min_windows: int, log: _BandMaskLog):
    """X, Y, RR without the STFT windows a band-limited mask covering `band` overlaps.

    A mask covers the band when `mtproc.masks.applies` says so at the band's
    centre period; a window is dropped when any of its samples lies in the
    mask's [start, end) (`mtproc.masks.windows_in_mask`). Masks are taken
    earliest first; one that would leave the band fewer than
    max(`min_windows`, stft.min_num_stft_windows) windows is skipped for this
    band (logged, named). A band no mask covers is returned untouched (the
    same objects).
    """
    period = float(band.center_period)
    covering = [(i, m) for i, m in enumerate(masks) if applies(m, period)]
    if not covering:
        return X, Y, RR
    if STFT_TIME not in X.dims:
        raise KeyError(f"the STFT has no {STFT_TIME!r} axis (dims {tuple(X.dims)}): cannot place windows in time")
    level = int(dec_level_config.decimation.level)
    times = X[STFT_TIME].values
    n = int(times.size)
    window_s = dec_level_config.stft.window.num_samples / float(dec_level_config.decimation.sample_rate)
    floor = max(int(dec_level_config.stft.min_num_stft_windows or 0), int(min_windows))
    drop = np.zeros(n, dtype=bool)
    skipped = []
    for _i, m in covering:
        hit = windows_in_mask(times, window_s, m)
        if not hit.any():
            continue
        trial = drop | hit
        if n - int(trial.sum()) < floor:
            skipped.append(m)
            continue
        drop = trial
    log.record(level, period, n, int(drop.sum()), skipped, [i for i, _m in covering])
    if not drop.any():
        return X, Y, RR
    if any(getattr(c, "weights", None) is not None for c in dec_level_config.channel_weight_specs):
        # aurora's weighted path would then apply one weight per window of the whole level
        raise RuntimeError("band masks cannot be combined with feature weights (channel_weight_specs)")
    keep = ~drop
    X, Y = X.isel({STFT_TIME: keep}), Y.isel({STFT_TIME: keep})
    if RR is not None:
        RR = RR.isel({STFT_TIME: keep})
    return X, Y, RR


@contextmanager
def _band_masks_applied(masks, min_windows: int = MIN_MASKED_WINDOWS):
    """For the duration of one `process_mth5` call, band-limited masks act in aurora's regression.

    `masks` is a site's list (`mtproc.masks.load_masks`); only the band-limited
    ones are used here (`bands: all` masks are time cuts, `apply_time_masks`).
    Wraps `aurora.pipelines.transfer_function_helpers.get_band_for_tf_estimate`
    (the comment above `BAND_PATCH_NAME` quotes the two call sites) so that,
    for a band whose centre period a mask covers, the STFT windows overlapping
    the mask are dropped from the local and remote Fourier coefficients
    before the regression (`_drop_masked_windows`). Logs once per decimation
    level how many windows each covered band lost, and warns about a mask
    that covers no band. The original function is restored on exit, as
    `_archives_read_only` restores `MTH5.open_mth5`. Yields a `_BandMaskLog`
    (None with no band-limited mask, and then nothing is patched).

    Raises RuntimeError before the block when aurora no longer has the
    expected entry point or signature (`_check_band_patch`), and after it
    when the wrapper failed inside aurora (which would otherwise drop a whole
    decimation level with only a log line) or was never called.
    """
    _all_band, band_masks = split_by_bands(masks)
    if not band_masks:
        yield None
        return
    _check_band_patch()
    original = getattr(_tf_helpers, BAND_PATCH_NAME)
    log = _BandMaskLog(band_masks)

    def masked(band, dec_level_config, local_stft_obj, remote_stft_obj):
        X, Y, RR = original(band, dec_level_config, local_stft_obj, remote_stft_obj)
        log.calls += 1
        try:
            return _drop_masked_windows(band, dec_level_config, X, Y, RR, band_masks, min_windows, log)
        except Exception as exc:
            log.errors.append(f"{type(exc).__name__}: {exc}")
            raise

    setattr(_tf_helpers, BAND_PATCH_NAME, masked)
    try:
        yield log
    finally:
        setattr(_tf_helpers, BAND_PATCH_NAME, original)
        log.close()
    if log.errors:
        raise RuntimeError(f"band masks failed inside aurora ({len(log.errors)} time(s)): {log.errors[0]}")
    if not log.calls:
        raise RuntimeError(f"aurora never called {BAND_PATCH_NAME}: the band masks were not applied")


def kernel_dataset(local_h5, station, remote_h5=None, remote_station=None,
                   start=None, end=None, min_run_seconds: float = 0.0):
    """The aurora KernelDataset for `station` (RR against `remote_station`), clipped to [start, end)."""
    rs = RunSummary()
    paths = [Path(local_h5)]
    if remote_h5 is not None and Path(remote_h5) != Path(local_h5):
        paths.append(Path(remote_h5))
    with _archives_read_only():
        rs.from_mth5s(paths)
        kd = KernelDataset()
        kd.from_run_summary(rs, station, remote_station)
    clip_to_window(kd, start, end)
    if min_run_seconds:
        kd.drop_runs_shorter_than(min_run_seconds)
    return kd


def apply_tweaks(config, tweaks: dict | None):
    """Set the estimator tweaks on every decimation level of an aurora config (in place).

    Keys (any subset; see `process_station`): taper, overlap_pct, prewhiten,
    min_windows, max_iterations, redescending_iterations, r0, u0, tolerance.
    An unknown key raises, so a typo never silently runs the defaults.
    """
    tweaks = dict(tweaks or {})
    unknown = set(tweaks) - set(ESTIMATOR_DEFAULTS)
    if unknown:
        raise ValueError(f"unknown tweak(s) {sorted(unknown)}; known: {list(ESTIMATOR_DEFAULTS)}")
    if "taper" in tweaks and tweaks["taper"] not in TAPERS:
        raise ValueError(f"taper {tweaks['taper']!r} is not one of {TAPERS}")
    if "overlap_pct" in tweaks and not 0.0 <= float(tweaks["overlap_pct"]) < 100.0:
        raise ValueError(f"overlap_pct {tweaks['overlap_pct']} is outside [0, 100)")
    for dec in config.decimations:
        stft, window, reg = dec.stft, dec.stft.window, dec.regression
        if "taper" in tweaks:
            window.type = tweaks["taper"]
            window.additional_args = {"NW": DPSS_NW} if tweaks["taper"] == "dpss" else {}
        if "overlap_pct" in tweaks:
            window.overlap = int(round(window.num_samples * float(tweaks["overlap_pct"]) / 100.0))
        if "prewhiten" in tweaks and not tweaks["prewhiten"]:
            # mt_metadata 1.0.10's validator only accepts "first difference" or
            # "other", but mth5's apply_prewhitening/apply_recoloring read an
            # empty type as "none": write it past the validator
            stft.__dict__["prewhitening_type"] = ""
            stft.recoloring = False
        if "min_windows" in tweaks:
            stft.min_num_stft_windows = int(tweaks["min_windows"])
        if "max_iterations" in tweaks:
            reg.max_iterations = int(tweaks["max_iterations"])
        if "redescending_iterations" in tweaks:
            reg.max_redescending_iterations = int(tweaks["redescending_iterations"])
        for key in ("r0", "u0", "tolerance"):
            if key in tweaks:
                setattr(reg, key, float(tweaks[key]))
    return config


def build_config(kd, band_scheme: dict | None = None, tweaks: dict | None = None, **config_kwargs):
    """ConfigCreator's config for `kd`, the long-window overlap boost, then `tweaks` (the taper defaults to Hann)."""
    if band_scheme:
        config_kwargs = {**band_scheme, **config_kwargs}
    cc = ConfigCreator()
    config = cc.create_from_kernel_dataset(kd, **config_kwargs)

    # deep decimation levels have windows lasting hours: boost their overlap
    # so the longest-period bands still see a usable number of windows
    for dec in config.decimations:
        w = dec.stft.window
        window_seconds = w.num_samples / dec.decimation.sample_rate
        if window_seconds > 600.0:
            w.overlap = int(w.num_samples * 0.75)
    tweaks = dict(tweaks or {})
    tweaks.setdefault("taper", ESTIMATOR_DEFAULTS["taper"])  # Hann unless --taper says otherwise
    apply_tweaks(config, tweaks)
    logger.info("estimator tweaks: " + ", ".join(f"{k}={v}" for k, v in tweaks.items()))
    return config


def process_station(
    local_h5: Path,
    station: str,
    remote_h5: Path | None = None,
    remote_station: str | None = None,
    out_dir: Path | None = None,
    min_run_seconds: float = 0.0,
    band_scheme: dict | None = None,
    start=None,
    end=None,
    tag: str | None = None,
    tweaks: dict | None = None,
    time_masks: list | None = None,
    **config_kwargs,
):
    """Estimate a transfer function for `station`, optionally remote-referenced.

    `time_masks` is the site's list from `<survey>/masks.yaml` (`mtproc.masks.load_masks`):
    the all-band intervals are cut out of the kernel dataset's run intervals
    before the config is built (`apply_time_masks`). The band-limited ones act
    inside aurora's regression through a scoped patch (`_band_masks_applied`,
    aurora 0.6.2 taking no per-band window weights from outside,
    docs/upstream_issues.md 22): in a band whose centre period a mask covers,
    the STFT windows overlapping the mask are dropped before the regression,
    every other band untouched; a mask that would leave a band fewer than
    `MIN_MASKED_WINDOWS` windows is skipped there, with a log line.

    `band_scheme` is the dict from mtproc.bands (band_edges, decimation_factors,
    num_samples_window); `start`/`end` (UTC) restrict the estimate to a
    processing window (see `clip_to_window`); `tag` overrides the output file
    stem (default ``<station>_rr-<remote>`` or ``<station>_ss``). Any further
    `config_kwargs` go to aurora's ``ConfigCreator.create_from_kernel_dataset``.

    `tweaks` changes the aurora estimator on **every** decimation level, after
    the config is built and after the long-window overlap boost; only the keys
    given are touched (the in-use value when a key is absent in brackets,
    `ESTIMATOR_DEFAULTS`):

    - ``taper``: STFT window, one of boxcar, hamming, hann, dpss [hann; aurora's own is boxcar]
      (dpss gets the time-bandwidth product NW = 3, which scipy requires);
    - ``overlap_pct``: STFT overlap in percent of the window, applied to every
      level as ``round(num_samples * pct / 100)`` and **replacing** the boost
      [25 %, and 75 % on levels whose window lasts over 600 s];
    - ``prewhiten``: False turns the first-difference pre-whitening off
      (prewhitening_type "" and recoloring False) [True: "first difference",
      recoloured];
    - ``min_windows``: stft.min_num_stft_windows, the fewest STFT windows a
      level needs to be used [0];
    - ``max_iterations``: regression.max_iterations of the robust (Huber) stage [10];
    - ``redescending_iterations``: regression.max_redescending_iterations [2];
    - ``r0``: the Huber weight's threshold, in residual standard deviations [1.5];
    - ``u0``: the redescending weight's threshold [2.8];
    - ``tolerance``: the regression's convergence tolerance [0.005].

    Returns the mt_metadata TF object; writes an EDI when `out_dir` is given.
    """
    all_band, band_limited = split_by_bands(time_masks)
    kd = kernel_dataset(local_h5, station, remote_h5, remote_station, start, end, min_run_seconds)
    if all_band:
        apply_time_masks(kd, all_band)
    config = build_config(kd, band_scheme, tweaks, **config_kwargs)

    logger.info(
        f"aurora: {station}" + (f" RR {remote_station}" if remote_station else " single-station")
        + (f", {len(band_limited)} band-limited mask(s) applied per band" if band_limited else "")
    )
    with _band_masks_applied(band_limited):
        tf = process_mth5(config, kd)

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if tag is None:
            tag = f"{station}_rr-{remote_station}" if remote_station else f"{station}_ss"
        edi_path = out_dir / f"{tag}.edi"
        tf.write(fn=edi_path, file_type="edi")
        logger.info(f"wrote {edi_path}")
    return tf
