# -*- coding: utf-8 -*-
"""
Aurora transfer-function estimation wrappers

`process_station` estimates a single-site or remote-referenced transfer
function from MTH5 archives and optionally writes an EDI. It builds an aurora
KernelDataset (`kernel_dataset`, `clip_to_window`), cuts the all-band time
masks out of it, builds the processing config (`build_config`,
`apply_tweaks`) and runs `aurora.pipelines.process_mth5.process_mth5`.

Band-limited masks from `<survey>/masks.yaml` act inside aurora's
regression: through the ``DecimationLevel.window_masks`` field on the
aurora fork (`AURORA_WINDOW_MASKS`, `_set_window_masks`), and through a
scoped runtime patch on stock aurora (`_band_masks_applied`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from pathlib import Path

import aurora
import aurora.pipelines.transfer_function_helpers as _tf_helpers
import numpy as np
import pandas as pd
from aurora.config.config_creator import ConfigCreator
from aurora.pipelines.process_mth5 import process_mth5
from loguru import logger
from mt_metadata.processing.aurora.decimation_level import DecimationLevel as _AuroraDecimationLevel

from .masks import applies, apply_time_masks, split_by_bands, windows_in_mask

try:  # newer stacks host these in mth5
    from mth5.processing import KernelDataset, RunSummary
except ImportError:  # older aurora
    from aurora.pipelines.run_summary import RunSummary
    from aurora.transfer_function.kernel_dataset import KernelDataset


def clip_to_window(kd, start=None, end=None):
    """Restrict a KernelDataset to [start, end) UTC.

    The MTH5 archives are left unchanged and keep every run; the window
    selects the part used in an estimate, for example the hours before a
    channel failed. Runs entirely outside the window
    are dropped and runs straddling it are trimmed. With a remote, the local
    and remote intervals are intersected again.

    Args:
        kd (KernelDataset): Kernel dataset, modified in place.
        start: Window start, UTC; None for no lower bound.
        end: Window end, UTC; None for no upper bound.

    Returns:
        KernelDataset: `kd`.

    Raises:
        ValueError: If no data remain in the window.
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
    # runs. Single-station, its remote_df is empty and it raises "do not
    # overlap", so it is called in remote-reference mode only.
    if kd.remote_station_id:
        kd.df = kd.restrict_run_intervals_to_simultaneous(kd.df)
    logger.info(
        f"processing window [{start}, {end}) UTC -> {len(kd.df)} run interval(s), "
        f"{kd.df.duration.sum() / 3600:.1f} station-hours"
    )
    return kd


# Estimator values a run without tweaks uses on every decimation level. They are
# aurora 0.6.2's ConfigCreator values (overlap_pct 25 %, which `build_config`
# raises to 75 % on levels whose window lasts over 600 s), except the taper,
# which `build_config` sets to Hann (aurora's is boxcar, `AURORA_TAPER`). With
# boxcar leakage, a strong 50 Hz line at either site leaks into the bands around it
# (tens of Hz wide); Hann's sidelobes keep it in its own band, with no loss where
# there is no such line.
# tests/process_rr_cli_unit.py builds a real config and checks these values.
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
AURORA_TAPER = "boxcar"  # ConfigCreator's taper; a run uses ESTIMATOR_DEFAULTS["taper"] unless tweaked
# ConfigCreator's window, whose overlap it sets to 32 samples (25 %); it keeps
# those 32 samples when the band scheme asks for another window length
AURORA_WINDOW = 128
DPSS_NW = 3.0  # time-bandwidth product for scipy's dpss window; aurora sets none


# aurora 0.6.2+mtproc (the bvkay/aurora fork, branch mtproc-fixes, "Add per-band
# STFT window masks on the decimation level") has a field for band masks:
# `DecimationLevel.window_masks`, a list of [start, end, pmin_s, pmax_s] rows,
# read with getattr inside both regression loops (window_mask_for_band and
# apply_window_mask in aurora.pipelines.transfer_function_helpers). Overlapping
# STFT windows are removed before the regression, per band and per level, as
# the patch below does. The fork's floor is max(1, stft.min_num_stft_windows);
# a mask that would leave fewer windows is skipped with a warning from aurora.
# A mask that covers no band centre on any level is reported by
# `_set_window_masks`. `start` and `end` go through aurora's `_utc_naive`
# (`pandas.Timestamp(value)`, naive taken as UTC), which parses the ISO strings
# of `crust.masks.normalise` as `crust.masks.utc` does, so they are passed
# unchanged. mt_metadata's DecimationLevel has no typed window_masks field, so
# the field does not serialise with the processing config, and a stock
# DecimationLevel accepts the assignment without error. `AURORA_WINDOW_MASKS`
# therefore checks aurora's version string for +mtproc and also probes that an
# assignment on `DecimationLevel` round-trips.
AURORA_WINDOW_MASKS = "+mtproc" in aurora.__version__


def _decimation_level_accepts_window_masks() -> bool:
    """Return True when `DecimationLevel` stores and returns a `window_masks` assignment.

    Complements the version check of `AURORA_WINDOW_MASKS`, which cannot
    detect a +mtproc build without the field, since the field is untyped and
    a stock `DecimationLevel` accepts the same assignment (see the comment
    above).
    """
    probe = object()
    dec = _AuroraDecimationLevel()
    try:
        dec.window_masks = probe
    except Exception:
        return False
    return getattr(dec, "window_masks", None) is probe


AURORA_WINDOW_MASKS = AURORA_WINDOW_MASKS and _decimation_level_accepts_window_masks()


def _set_window_masks(config, band_limited: list[dict]) -> None:
    """Set aurora's `window_masks` on every decimation level of a config.

    One row is written per band-limited mask. The number passed is logged
    per level, and a warning is logged for any mask whose [pmin_s, pmax_s]
    covers no band centre period on any level (see the comment above
    `AURORA_WINDOW_MASKS`).

    Args:
        config: Aurora processing config, modified in place.
        band_limited (list of dict): Normalised band-limited masks.
    """
    rows = [[m["start"], m["end"], m["bands"][0], m["bands"][1]] for m in band_limited]
    matched: set[int] = set()
    for dec in config.decimations:
        dec.window_masks = list(rows)
        logger.info(f"window masks, decimation level {int(dec.decimation.level)}: "
                    f"{len(rows)} mask(s) passed to aurora")
        for i, m in enumerate(band_limited):
            if any(applies(m, float(band.center_period)) for band in dec.bands):
                matched.add(i)
    for i, m in enumerate(band_limited):
        if i not in matched:
            logger.warning(f"band mask {_mask_label(m)} covers no band's centre period: not applied")


# On stock aurora (no `window_masks`), band-limited masks reach aurora through a
# scoped patch (docs/upstream_issues.md 22: aurora 0.6.2 takes no per-band
# window weights or masks as input). Both of its regression loops take a band's
# Fourier coefficients from one function, looked up in the globals of
# `aurora.pipelines.transfer_function_helpers` at call time:
#   line 249, process_transfer_functions:
#       X, Y, RR = get_band_for_tf_estimate(band, dec_level_config, local_stft_obj, remote_stft_obj)
#   line 339, process_transfer_functions_with_weights (per output channel):
#       X, Y, RR = get_band_for_tf_estimate(band, dec_level_config, local_stft_obj, remote_stft_obj)
# (`process_mth5.process_tf_decimation_level` tries the second and falls back to
# the first). `_band_masks_applied` wraps that name, so a band a mask covers gets
# X, Y, RR with the masked windows removed rather than zero-weighted, and
# aurora's weighting (edf weights, the robust regression) operates on the
# remaining windows. `_check_band_patch` raises if aurora changes any of this.
BAND_PATCH_NAME = "get_band_for_tf_estimate"
BAND_PATCH_PARAMETERS = ("band", "dec_level_config", "local_stft_obj", "remote_stft_obj")
BAND_PATCH_CALLERS = ("process_transfer_functions", "process_transfer_functions_with_weights")
STFT_TIME = "time"  # STFT window axis: naive UTC datetime64 of each window's first sample
MIN_MASKED_WINDOWS = 4  # fewest windows a band mask may leave (also at least the level's min_num_stft_windows)


def _check_band_patch() -> None:
    """Check that both aurora regression loops call the function the band patch wraps.

    Raises:
        RuntimeError: If the function is missing, its signature differs from
            `BAND_PATCH_PARAMETERS`, or a caller in `BAND_PATCH_CALLERS` does
            not look it up in the module globals.
    """
    target = getattr(_tf_helpers, BAND_PATCH_NAME, None)
    if target is None:
        raise RuntimeError(f"aurora.pipelines.transfer_function_helpers has no {BAND_PATCH_NAME}: "
                           "band-limited masks cannot be applied (see crust.process)")
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
    """Format a band-limited mask for log lines."""
    return (f"{mask['start']} to {mask['end']} [{mask['bands'][0]:g}, {mask['bands'][1]:g}] s")


class _BandMaskLog:
    """Record of the windows `_band_masks_applied` dropped.

    For each decimation level and each band a mask covers, the record holds
    ``{"windows", "lost", "skipped"}``. One log line is written per level,
    when the next level starts or the block ends. Aurora requests a band
    once per output channel; each band is recorded once.

    Args:
        masks (list of dict): The band-limited masks in use.
    """

    def __init__(self, masks):
        self.masks = masks
        self.levels: dict[int, dict[float, dict]] = {}
        self.errors: list[str] = []
        self.calls = 0
        self._matched: set[int] = set()
        self._current: int | None = None
        self._flushed: set[int] = set()

    def record(self, level: int, period: float, windows: int, lost: int, skipped: list, matched) -> None:
        """Store the result for one band, flushing the previous level's log line on a level change."""
        if self._current is not None and level != self._current:
            self._flush(self._current)
        self._current = level
        self._matched.update(matched)
        self.levels.setdefault(level, {})[period] = {"windows": windows, "lost": lost, "skipped": skipped}

    def lost(self) -> dict[float, int]:
        """Map each covered band's centre period to the number of windows dropped."""
        return {p: b["lost"] for bands in self.levels.values() for p, b in bands.items()}

    def _flush(self, level: int) -> None:
        """Log one level's summary line, once."""
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
        """Flush the last level and warn about masks that covered no band."""
        if self._current is not None:
            self._flush(self._current)
        for i, m in enumerate(self.masks):
            if i not in self._matched:
                logger.warning(f"band mask {_mask_label(m)} covers no band's centre period: not applied")


def _drop_masked_windows(band, dec_level_config, X, Y, RR, masks, min_windows: int, log: _BandMaskLog):
    """Remove the STFT windows overlapped by the band-limited masks covering a band.

    A mask covers the band when `crust.masks.applies` is True at the band's
    centre period; a window is dropped when any of its samples lies in the
    mask's [start, end) (`crust.masks.windows_in_mask`). Masks are taken
    earliest first, and one that would leave the band fewer than
    max(`min_windows`, stft.min_num_stft_windows) windows is skipped for
    this band and named in the log.

    Args:
        band: Aurora frequency band.
        dec_level_config: Aurora decimation-level config.
        X: Input-channel Fourier coefficients (xarray, with a time axis).
        Y: Output-channel Fourier coefficients.
        RR: Remote-reference Fourier coefficients, or None.
        masks (list of dict): Band-limited masks, earliest first.
        min_windows (int): Fewest windows a mask may leave.
        log (_BandMaskLog): Record to update.

    Returns:
        tuple: ``(X, Y, RR)`` without the dropped windows. A band no mask
        covers, or where nothing is dropped, returns the same objects.

    Raises:
        KeyError: If the STFT has no time axis.
        RuntimeError: If windows would be dropped while the level has
            feature weights (channel_weight_specs).
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
        # aurora's weighted path applies one weight per window of the whole level
        raise RuntimeError("band masks cannot be combined with feature weights (channel_weight_specs)")
    keep = ~drop
    X, Y = X.isel({STFT_TIME: keep}), Y.isel({STFT_TIME: keep})
    if RR is not None:
        RR = RR.isel({STFT_TIME: keep})
    return X, Y, RR


@contextmanager
def _band_masks_applied(masks, min_windows: int = MIN_MASKED_WINDOWS):
    """Apply band-limited masks in aurora's regression for the duration of the block.

    Intended to wrap one `process_mth5` call. Wraps
    `aurora.pipelines.transfer_function_helpers.get_band_for_tf_estimate`
    (the comment above `BAND_PATCH_NAME` quotes the two call sites) so that,
    for a band whose centre period a mask covers, the STFT windows
    overlapping the mask are dropped from the local and remote Fourier
    coefficients before the regression (`_drop_masked_windows`). Logs once
    per decimation level how many windows each covered band lost, and warns
    about a mask that covers no band. The original function is restored on
    exit.

    Args:
        masks (list of dict): A site's masks (`crust.masks.load_masks`).
            The band-limited ones are used; ``bands: all`` masks are handled
            by `apply_time_masks`.
        min_windows (int): Fewest windows a mask may leave in a band.

    Yields:
        _BandMaskLog or None: The record of dropped windows, or None when
        there is no band-limited mask, in which case nothing is patched.

    Raises:
        RuntimeError: Before the block, if aurora lacks the expected entry
            point or signature (`_check_band_patch`). After the block, if
            the wrapper raised inside aurora (where aurora would drop the
            whole decimation level with a log line) or was never called.
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
    """Build the aurora KernelDataset of a station, clipped to [start, end).

    Opens the archives read-only: the mth5 fork reads the run summary and
    the kernel dataset's metadata in read-only mode
    (docs/upstream_issues.md 5), so a config builds while another process,
    such as the GUI, holds an archive open read-only, and the archive
    modification times stay unchanged.

    Args:
        local_h5 (Path): MTH5 file of the local station.
        station (str): Local station id.
        remote_h5 (Path, optional): MTH5 file of the remote station; may be
            the same file as `local_h5`.
        remote_station (str, optional): Remote station id for remote
            reference.
        start: Processing window start, UTC.
        end: Processing window end, UTC.
        min_run_seconds (float): Runs shorter than this are dropped.

    Returns:
        KernelDataset: The kernel dataset.
    """
    rs = RunSummary()
    paths = [Path(local_h5)]
    if remote_h5 is not None and Path(remote_h5) != Path(local_h5):
        paths.append(Path(remote_h5))
    rs.from_mth5s(paths)
    kd = KernelDataset()
    kd.from_run_summary(rs, station, remote_station)
    clip_to_window(kd, start, end)
    if min_run_seconds:
        kd.drop_runs_shorter_than(min_run_seconds)
    return kd


def apply_tweaks(config, tweaks: dict | None):
    """Set estimator tweaks on every decimation level of an aurora config.

    Args:
        config: Aurora processing config, modified in place.
        tweaks (dict or None): Any subset of taper, overlap_pct, prewhiten,
            min_windows, max_iterations, redescending_iterations, r0, u0 and
            tolerance (see `process_station`).

    Returns:
        The config.

    Raises:
        ValueError: If a key is unknown, the taper is not one of `TAPERS`,
            or overlap_pct is outside [0, 100).
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
            # mt_metadata 1.0.10's validator accepts "first difference" or
            # "other", and mth5's apply_prewhitening/apply_recoloring read an
            # empty type as "none", so the empty type is written past the validator
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
    """Build the aurora processing config for a kernel dataset.

    The config comes from ConfigCreator; levels whose window lasts over
    600 s get 75 % overlap, the others 25 % of their own window (the 32
    samples ConfigCreator sets for its 128-sample window, 64 for a
    256-sample one); then `tweaks` are applied, with the taper defaulting
    to Hann.

    Args:
        kd (KernelDataset): Kernel dataset.
        band_scheme (dict, optional): Band scheme from `crust.bands`; its
            ``num_samples_window`` sets the window of every level.
        tweaks (dict, optional): Estimator tweaks (see `apply_tweaks`).
        **config_kwargs: Passed to ``ConfigCreator.create_from_kernel_dataset``,
            overriding `band_scheme` keys.

    Returns:
        The aurora processing config.
    """
    if band_scheme:
        config_kwargs = {**band_scheme, **config_kwargs}
    cc = ConfigCreator()
    config = cc.create_from_kernel_dataset(kd, **config_kwargs)

    # deep decimation levels have windows lasting hours: boost their overlap
    # so the longest-period bands still see a usable number of windows; the
    # others overlap by the in-use fraction of their own window
    for dec in config.decimations:
        w = dec.stft.window
        window_seconds = w.num_samples / dec.decimation.sample_rate
        if window_seconds > 600.0:
            w.overlap = int(w.num_samples * 0.75)
        elif w.num_samples != AURORA_WINDOW:
            w.overlap = round(w.num_samples * ESTIMATOR_DEFAULTS["overlap_pct"] / 100.0)
    tweaks = dict(tweaks or {})
    tweaks.setdefault("taper", ESTIMATOR_DEFAULTS["taper"])  # Hann unless a taper is given
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
    """Estimate a transfer function for a station, optionally remote-referenced.

    The all-band intervals of `time_masks` are cut out of the kernel
    dataset's run intervals before the config is built (`apply_time_masks`).
    The band-limited ones act inside aurora's regression: on aurora
    0.6.2+mtproc (`AURORA_WINDOW_MASKS`) through its
    `DecimationLevel.window_masks` field (`_set_window_masks`), and on stock
    aurora, which takes no per-band window weights as input
    (docs/upstream_issues.md 22), through a scoped patch
    (`_band_masks_applied`). In both cases, in a band whose centre period a
    mask covers, the STFT windows overlapping the mask are dropped before
    the regression and other bands are unchanged. A mask that would leave a
    band too few windows is skipped there with a log line (aurora's floor on
    the fork, `MIN_MASKED_WINDOWS` on the patch).

    `tweaks` change the aurora estimator on every decimation level, after
    the config is built and after the long-window overlap boost. Only the
    keys given are set; the value in use when a key is absent is shown in
    brackets (`ESTIMATOR_DEFAULTS`):

    - ``taper``: STFT window, one of boxcar, hamming, hann, dpss [hann; aurora's own is boxcar]
      (dpss gets the time-bandwidth product NW = 3, which scipy requires);
    - ``overlap_pct``: STFT overlap in percent of the window, applied to every
      level as ``round(num_samples * pct / 100)``, replacing the boost
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

    Args:
        local_h5 (Path): MTH5 file of the local station.
        station (str): Local station id.
        remote_h5 (Path, optional): MTH5 file of the remote station.
        remote_station (str, optional): Remote station id; single-station
            processing when None.
        out_dir (Path, optional): Folder for the EDI; nothing is written
            when None.
        min_run_seconds (float): Runs shorter than this are dropped.
        band_scheme (dict, optional): Dict from `crust.bands` (band_edges,
            decimation_factors, num_samples_window).
        start: Processing window start, UTC (see `clip_to_window`).
        end: Processing window end, UTC.
        tag (str, optional): Output file stem; default
            ``<station>_rr-<remote>`` or ``<station>_ss``.
        tweaks (dict, optional): Estimator tweaks, listed above.
        time_masks (list of dict, optional): The masks applied from the
            local and remote sites (`crust.masks.masks_for_role`,
            `crust.masks.union_masks`).
        **config_kwargs: Passed to aurora's
            ``ConfigCreator.create_from_kernel_dataset``.

    Returns:
        TF: The mt_metadata transfer function.
    """
    all_band, band_limited = split_by_bands(time_masks)
    kd = kernel_dataset(local_h5, station, remote_h5, remote_station, start, end, min_run_seconds)
    if all_band:
        apply_time_masks(kd, all_band)
    config = build_config(kd, band_scheme, tweaks, **config_kwargs)

    logger.info(
        f"aurora: {station}" + (f" RR {remote_station}" if remote_station else " single-station")
        + (f", {len(band_limited)} band-limited mask(s) applied per band"
           f" ({'aurora window_masks' if AURORA_WINDOW_MASKS else 'runtime patch'})" if band_limited else "")
    )
    if AURORA_WINDOW_MASKS:
        if band_limited:
            _set_window_masks(config, band_limited)
        tf = process_mth5(config, kd)
    else:
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
