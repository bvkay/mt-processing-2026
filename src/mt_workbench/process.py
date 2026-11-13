# -*- coding: utf-8 -*-
"""
Aurora transfer-function estimation wrappers

`process_station` estimates a single-site or remote-referenced transfer
function from MTH5 archives and optionally writes the row's products (EDI,
EMTF XML and a standalone TF h5, `mt_workbench.products.write_products`).
It builds an aurora KernelDataset (`kernel_dataset`, `clip_to_window`),
cuts the all-band time
masks out of it, builds the processing config (`build_config`,
`apply_tweaks`) and runs `aurora.pipelines.process_mth5.process_mth5`.

Band-limited masks from `<survey>/masks.yaml` act inside aurora's
regression: through the ``DecimationLevel.window_masks`` field on the
aurora fork (`AURORA_WINDOW_MASKS`, `_set_window_masks`), and through a
scoped runtime patch on stock aurora (`_band_masks_applied`).

A site with one electric line, the diagonal of a shared-centre layout
(scripts/diagonal_site.py, outputs ex and hz), is estimated through a
second scoped patch (`_one_electric_line`), since aurora 0.6.2 handles a
missing hz but not a missing ex or ey.

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
import xarray as xr
from aurora.transfer_function import TTFZ as _ttfz
from aurora.transfer_function import transfer_function_collection as _tf_collection
from aurora.config.config_creator import ConfigCreator
from aurora.pipelines.process_mth5 import process_mth5
from loguru import logger
from mt_metadata.processing.aurora.decimation_level import DecimationLevel as _AuroraDecimationLevel

from .masks import applies, apply_time_masks, split_by_bands, windows_in_mask
from .products import apply_site_frame, drop_bad_errors, keep_periods, write_products

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
# a decimation level whose window lasts longer than this is a "long" level: `build_config`
# gives it 75 % overlap, and the tweak `overlap_pct_long` reaches these levels only
LONG_WINDOW_SECONDS = 600.0
# every tweak `apply_tweaks` accepts: the defaults above plus the long-level overlap, which has
# no default of its own (absent, the long levels keep `build_config`'s 75 %)
KNOWN_TWEAKS = tuple(ESTIMATOR_DEFAULTS) + ("overlap_pct_long",)
# the fewest STFT windows a band may rest on for its period to be written
# (`drop_short_bands`). A band of one window gives an estimate whose errors
# mean nothing (a 10 min window left the deepest level one window and wrote
# Z errors of exactly 0). A floor of 2 removes those bands alone; a floor of
# 5 also removed the bands of 2 to 4 windows at the longest periods of
# full-record products. survey.yaml `processing: min_band_windows` and
# process_rr.py --min-band-windows set another floor; 0 turns it off.
MIN_BAND_WINDOWS = 2
# the attribute `drop_short_bands` sets on the TF: the periods it removed, in s
DROPPED_ATTR = "dropped_short_bands"
# issue 181: the per-level STFT window and overlap of the aurora config a run used (`overlap_table`), set on the TF
# `process_station` returns as this attribute, for the sidecar
OVERLAP_ATTR = "stft_overlaps"
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
# of `mt_workbench.masks.normalise` as `mt_workbench.masks.utc` does, so they are passed
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
                           "band-limited masks cannot be applied (see mt_workbench.process)")
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

    A mask covers the band when `mt_workbench.masks.applies` is True at the band's
    centre period; a window is dropped when any of its samples lies in the
    mask's [start, end) (`mt_workbench.masks.windows_in_mask`). Masks are taken
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
        covers, or where no window is dropped, returns the same objects.

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
        masks (list of dict): A site's masks (`mt_workbench.masks.load_masks`).
            The band-limited ones are used; ``bands: all`` masks are handled
            by `apply_time_masks`.
        min_windows (int): Fewest windows a mask may leave in a band.

    Yields:
        _BandMaskLog or None: The record of dropped windows, or None when
        there is no band-limited mask, in which case aurora is left unpatched.

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


# Aurora 0.6.2 estimates the rows it is given (`output_channels`), but two of
# its steps after the regression need both electric outputs
# (docs/upstream_issues.md 338):
#   TTFZ.apparent_resistivity, called on every decimation level's estimate
#   (process_mth5.process_mth5_legacy), reads tf.loc[ex, hy] and tf.loc[ey, hx]
#   for its rho and phase, which only aurora's development plots use;
#   TransferFunctionCollection.check_all_channels_present, called by
#   get_merged_dict before the TF is exported to mt_metadata, fills a missing
#   hz output with NaN (and its residual covariance with zeros) and raises
#   "No handling for missing ex/ey channel" otherwise.
# `_one_electric_line` patches both for one process_mth5 call: the first sets
# rho and phase NaN when an electric output is missing, the second adds the
# missing electric output as aurora adds a missing hz (a NaN row, zeros in
# the residual covariance) before aurora's own check. mt_metadata's TF then
# holds that row NaN, `drop_bad_errors` leaves a row NaN at every period
# alone, and the EDI writes it as EMPTY. mt_metadata's TF then also gives the
# first run of its station metadata an empty channel of the missing line (its
# default channel set, ex ey hx hy hz), so a station of several runs reaches
# the EMTF XML writer with runs that disagree on their channels and the
# writer stops (AttributeError: 'NoneType' object has no attribute
# 'component'; docs/upstream_issues.md 339): `_drop_unrecorded_lines` removes
# it from every run.
ONE_LINE_PATCHES = ((_ttfz.TTFZ, "apparent_resistivity"),
                    (_tf_collection.TransferFunctionCollection, "check_all_channels_present"))


def _add_missing_output(collection, name: str) -> None:
    """Add an output channel to a merged aurora TF collection: a NaN row and zeros in the residual covariance.

    The form of aurora's own fill of a missing hz
    (`TransferFunctionCollection.check_all_channels_present`).

    Args:
        collection: The aurora TransferFunctionCollection after
            `_merge_decimation_levels`.
        name (str): The output channel to add.
    """
    tf = collection.merged_tf
    row = tf.isel(output_channel=[0]).copy(deep=True).assign_coords(output_channel=[name])
    row.data = np.full(row.shape, np.nan, dtype=row.dtype)
    collection.merged_tf = xr.concat([tf, row], dim="output_channel")
    outputs = collection.merged_tf.output_channel.data.tolist()
    cov = collection.merged_cov_nn
    shape = [len(outputs) if d.startswith("output_channel") else cov.sizes[d] for d in cov.dims]
    coords = {d: (outputs if d.startswith("output_channel") else cov[d].data) for d in cov.dims}
    filled = xr.DataArray(np.zeros(shape, dtype=cov.dtype), dims=cov.dims, coords=coords)
    for a in cov.output_channel_1.data.tolist():
        for b in cov.output_channel_2.data.tolist():
            filled.loc[{"output_channel_1": a, "output_channel_2": b}] = \
                cov.loc[{"output_channel_1": a, "output_channel_2": b}]
    collection.merged_cov_nn = filled


def _drop_unrecorded_lines(tf, names) -> list[str]:
    """Remove the named electric channels from every run of a TF's station metadata.

    Args:
        tf: The mt_metadata TF of a one-electric estimate.
        names (list of str): The electric channels the site did not record
            (`_one_electric_line`'s added rows).

    Returns:
        list of str: "<run> <channel>" for each channel removed.
    """
    removed = []
    for run in tf.station_metadata.runs:
        for name in names:
            if name in run.channels_recorded_all:
                run.remove_channel(name)
                removed.append(f"{run.id} {name}")
    return removed


@contextmanager
def _one_electric_line(output_channels):
    """Let aurora estimate a TF whose outputs hold one electric channel, for the duration of the block.

    Intended to wrap one `process_mth5` call (the comment above
    `ONE_LINE_PATCHES`). The patches apply when the outputs hold one of ex
    and ey. The originals are restored on exit.

    Args:
        output_channels (list of str): The config's output channels.

    Yields:
        list of str: The electric channels added as NaN rows ([] when
        no patch applies).

    Raises:
        RuntimeError: Before the block, if aurora lacks a patched method.
    """
    outputs = [str(c) for c in output_channels or []]
    missing = [c for c in ("ex", "ey") if c not in outputs]
    if len(missing) != 1:
        yield []
        return
    for owner, attr in ONE_LINE_PATCHES:
        if not callable(getattr(owner, attr, None)):
            raise RuntimeError(f"aurora's {owner.__name__} has no {attr}: a site with one electric line cannot be "
                               f"estimated (see mt_workbench.process.ONE_LINE_PATCHES)")
    resistivity = _ttfz.TTFZ.apparent_resistivity
    check = _tf_collection.TransferFunctionCollection.check_all_channels_present

    def one_line_resistivity(self, channel_nomenclature, units="SI"):
        ex, ey = channel_nomenclature.unpack()[:2]
        present = self.tf.coords["output_channel"].data.tolist()
        if ex in present and ey in present:
            return resistivity(self, channel_nomenclature, units=units)
        for key in ("rho", "rho_se", "phi", "phi_se"):
            setattr(self, key, np.full((self.num_bands, 2), np.nan))
        return None

    def one_line_check(self, channel_nomenclature):
        ex, ey = channel_nomenclature.unpack()[:2]
        for name in (ex, ey):
            if name not in self.merged_tf.output_channel.data.tolist():
                _add_missing_output(self, name)
        return check(self, channel_nomenclature)

    _ttfz.TTFZ.apparent_resistivity = one_line_resistivity
    _tf_collection.TransferFunctionCollection.check_all_channels_present = one_line_check
    try:
        yield missing
    finally:
        _ttfz.TTFZ.apparent_resistivity = resistivity
        _tf_collection.TransferFunctionCollection.check_all_channels_present = check


@contextmanager
def slim_station_metadata(wanted=None):
    """Give each channel time series a station metadata holding its own run only, for one processing call.

    mth5 builds the station metadata of a channel from the station group's
    attributes, whose run_list names every run of the station, so a station
    of thousands of burst runs materialises them all for every channel read
    and the channel's constructor copies them again (about 30 s per burst
    run on a 3000-run station); the run group's own station_metadata keeps
    the one run. Inside this context the channel path keeps the one run as
    well (upstream issue 396), and the run metadata, the station's own
    attributes and the survey's reach aurora unchanged. aurora's per-run
    question whether Fourier coefficients are stored for a run opens the
    station each time; here a station with no stored coefficients answers
    from the file. The station's own metadata getter fills every run of the
    station from its group (tens of seconds for thousands of runs); with
    `wanted`, a set of run ids, it fills those and drops the rest, which the
    run list only names.

    Args:
        wanted (set, optional): Run ids whose metadata the station getter
            fills; None fills every run, as mth5 does.
    """
    from mt_metadata import timeseries as ts_metadata
    from mth5.groups.channel_dataset import ChannelDataset
    from mth5.helpers import read_attrs_to_dict

    original = ChannelDataset._station_metadata_with

    def one_run(self, run_metadata):
        attrs = dict(self.hdf5_dataset.parent.parent.attrs)
        attrs["run_list"] = [run_metadata.id]
        station = ts_metadata.Station()
        station.from_dict({"station": read_attrs_to_dict(attrs, station)})
        station.add_run(run_metadata)
        return station

    import aurora.pipelines.transfer_function_kernel as tfk
    import h5py

    has_fcs = tfk.mth5_has_fcs

    def has_fcs_quick(m, survey_id, station_id, run_id, remote, processing_config, **kwargs):
        # aurora asks per run whether stored Fourier coefficients exist, opening the station each time (the whole
        # run list again); a station whose Fourier_Coefficients group is empty answers from the file in a few ms
        try:
            with h5py.File(m, "r") as fh:
                group = fh.get(f"Experiment/Surveys/{survey_id}/Stations/{station_id}/Fourier_Coefficients")
                if group is None or len(group) == 0:
                    return False
        except (OSError, TypeError, KeyError):
            pass
        return has_fcs(m, survey_id, station_id, run_id, remote, processing_config, **kwargs)

    from mth5.groups.station import StationGroup
    from mth5.utils.exceptions import MTH5Error

    station_prop = StationGroup.metadata

    def wanted_runs(self):
        if wanted is None:
            return station_prop.fget(self)
        if not self._has_read_metadata or len(self._metadata.runs) > len(wanted):
            # the station from its own attributes with a run list of the wanted runs only, so no later pass
            # walks the placeholders the full run list would create
            attrs = dict(self.hdf5_group.attrs)
            attrs["run_list"] = [key for key in self.groups_list if key in wanted]
            station = ts_metadata.Station()
            station.from_dict({"station": read_attrs_to_dict(attrs, station)})
            self._metadata = station
            self._has_read_metadata = True
        for key in self.groups_list:
            if key not in wanted:
                continue
            try:
                group = self.get_run(key)
                if group.metadata.mth5_type.lower() in ["run"]:
                    self._metadata.add_run(group.metadata)
            except MTH5Error:
                self.logger.warning(f"Could not find run {key}")
        return self._metadata

    ChannelDataset._station_metadata_with = one_run
    tfk.mth5_has_fcs = has_fcs_quick
    StationGroup.metadata = property(wanted_runs, station_prop.fset, station_prop.fdel)
    try:
        yield
    finally:
        ChannelDataset._station_metadata_with = original
        tfk.mth5_has_fcs = has_fcs
        StationGroup.metadata = station_prop


def _drop_runs_outside(rs, start=None, end=None) -> None:
    """Drop the run summary's runs that end before `start` or begin at or after `end`, in place.

    The kernel dataset builds metadata for every run the summary holds, so a
    station of thousands of burst runs pays for all of them before
    `clip_to_window` keeps the window's few; dropping the others first costs
    nothing when the window holds every run. Runs straddling the window stay
    and are trimmed later. When the window holds no run the summary is left
    whole, so `clip_to_window` raises its own message.

    Args:
        rs (RunSummary): The run summary, modified in place.
        start: Window start, UTC; None for no lower bound.
        end: Window end, UTC; None for no upper bound.
    """
    if (start is None and end is None) or rs.df is None or rs.df.empty:
        return
    keep = pd.Series(True, index=rs.df.index)
    if start is not None:
        keep &= rs.df["end"] > pd.Timestamp(start, tz="UTC")
    if end is not None:
        keep &= rs.df["start"] < pd.Timestamp(end, tz="UTC")
    if keep.any() and not keep.all():
        logger.info(f"run summary: {int(keep.sum())} of {len(keep)} runs reach the window [{start}, {end})")
        rs.df = rs.df[keep].reset_index(drop=True)


def _restore_survey_ids(rs) -> int:
    """Put each archive's own survey id back into the run summary's rows where mth5 cut it, in place.

    mth5 0.6.9 holds the survey id of its channel summary, from which the
    run summary is made, in a field of 30 characters
    (``mth5.CHANNEL_DTYPE``), so a longer id reaches the run summary cut
    and the kernel dataset's run lookup fails (docs/upstream_issues.md
    550). A row's id is replaced when it fills the field and exactly one
    survey id of its archive (column ``mth5_path``) starts with it, a
    longer one. Only an archive holding such a row is opened, read-only,
    for its survey group names.

    Args:
        rs (RunSummary): The run summary, modified in place.

    Returns:
        int: The number of rows whose id was replaced.

    Raises:
        ValueError: If two survey ids of one archive start with a row's
            id of the field's width (the id itself counted).
    """
    from mth5 import CHANNEL_DTYPE
    from mth5.mth5 import MTH5

    if rs.df is None or rs.df.empty:
        return 0
    width = CHANNEL_DTYPE["survey"].itemsize
    df = rs.df
    cut = df["survey"].astype(str).str.len() == width
    restored = 0
    for path in df.loc[cut, "mth5_path"].unique():
        m = MTH5()
        m.open_mth5(path, mode="r")
        try:
            surveys = list(m.surveys_group.groups_list) if m.file_version == "0.2.0" else []
        finally:
            m.close_mth5()
        rows = cut & (df["mth5_path"] == path)
        for short in df.loc[rows, "survey"].astype(str).unique():
            # the id itself counts: an archive holding both it and a longer id that starts with it is ambiguous too
            full = [s for s in surveys if s.startswith(short)]
            if len(full) > 1:
                raise ValueError(f"{path}: survey ids {full} share the {width}-character id {short!r} that mth5's "
                                 f"run summary keeps (docs/upstream_issues.md 550): the run's survey is ambiguous")
            if full and full[0] != short:
                same = rows & (df["survey"].astype(str) == short)
                df.loc[same, "survey"] = full[0]
                restored += int(same.sum())
    return restored


def _keep_processed_runs(tf) -> int:
    """Keep, in the transfer function's station metadata, only the runs the estimate used.

    aurora copies the station's whole run list into the product, so a burst
    station of thousands of runs writes every one into the EDI and the XML
    and the XML writer spends minutes on them; the estimate's own runs are
    ``transfer_function.runs_processed``.

    Args:
        tf: The mt_metadata transfer function, modified in place.

    Returns:
        int: The number of runs dropped.
    """
    sm = tf.station_metadata
    used = set(sm.transfer_function.runs_processed or [])
    if not used or len(sm.runs) <= len(used):
        return 0
    unused = [run.id for run in sm.runs if run.id not in used]
    for run_id in unused:
        sm.remove_run(run_id)
    return len(unused)


def kernel_dataset(local_h5, station, remote_h5=None, remote_station=None,

                   start=None, end=None, min_run_seconds: float = 0.0):
    """Build the aurora KernelDataset of a station, clipped to [start, end).

    Opens the archives read-only: the mth5 fork reads the run summary and
    the kernel dataset's metadata in read-only mode
    (docs/upstream_issues.md 5), so a config builds while another process,
    such as the GUI, holds an archive open read-only, and the archive
    modification times stay unchanged. A survey id that mth5's run summary
    cut to 30 characters is put back whole (`_restore_survey_ids`).

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
    with slim_station_metadata():
        rs.from_mth5s(paths)
    restored = _restore_survey_ids(rs)
    if restored:
        logger.info(f"run summary: the survey id put back whole on {restored} rows (cut to 30 characters by mth5, "
                    f"docs/upstream_issues.md 550)")
    _drop_runs_outside(rs, start, end)
    with slim_station_metadata(set(rs.df["run"]) if rs.df is not None else None):
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
        tweaks (dict or None): Any subset of taper, overlap_pct,
            overlap_pct_long, prewhiten, min_windows, max_iterations,
            redescending_iterations, r0, u0 and tolerance (see
            `process_station`).

    Returns:
        The config.

    Raises:
        ValueError: If a key is unknown, the taper is not one of `TAPERS`,
            or overlap_pct or overlap_pct_long is outside [0, 100).
    """
    tweaks = dict(tweaks or {})
    unknown = set(tweaks) - set(KNOWN_TWEAKS)
    if unknown:
        raise ValueError(f"unknown tweak(s) {sorted(unknown)}; known: {list(KNOWN_TWEAKS)}")
    if "taper" in tweaks and tweaks["taper"] not in TAPERS:
        raise ValueError(f"taper {tweaks['taper']!r} is not one of {TAPERS}")
    for key in ("overlap_pct", "overlap_pct_long"):
        if key in tweaks and not 0.0 <= float(tweaks[key]) < 100.0:
            raise ValueError(f"{key} {tweaks[key]} is outside [0, 100)")
    for dec in config.decimations:
        stft, window, reg = dec.stft, dec.stft.window, dec.regression
        if "taper" in tweaks:
            window.type = tweaks["taper"]
            window.additional_args = {"NW": DPSS_NW} if tweaks["taper"] == "dpss" else {}
        if "overlap_pct" in tweaks:
            window.overlap = int(round(window.num_samples * float(tweaks["overlap_pct"]) / 100.0))
        if "overlap_pct_long" in tweaks:
            # the long levels only (window over LONG_WINDOW_SECONDS); set after
            # overlap_pct so it wins there when both are given
            if window.num_samples / float(dec.decimation.sample_rate) > LONG_WINDOW_SECONDS:
                window.overlap = int(round(window.num_samples * float(tweaks["overlap_pct_long"]) / 100.0))
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


def overlap_table(config) -> list[dict]:
    """Return the STFT window and overlap of every decimation level of an aurora config (issue 181).

    Each entry: ``level``, ``sample_rate`` (Hz), ``window_samples``,
    ``window_s``, ``overlap_samples``, ``overlap_pct`` (of the window, to
    0.01) and ``long`` (window over `LONG_WINDOW_SECONDS`, the levels the
    75 % boost and ``overlap_pct_long`` reach).
    """
    out = []
    for k, dec in enumerate(config.decimations):
        w = dec.stft.window
        fs = float(dec.decimation.sample_rate)
        n, ov = int(w.num_samples), int(w.overlap)
        out.append(dict(level=int(getattr(dec.decimation, "level", k)), sample_rate=fs, window_samples=n,
                        window_s=n / fs, overlap_samples=ov, overlap_pct=round(100.0 * ov / n, 2),
                        long=bool(n / fs > LONG_WINDOW_SECONDS)))
    return out


def build_config(kd, band_scheme: dict | None = None, tweaks: dict | None = None, **config_kwargs):
    """Build the aurora processing config for a kernel dataset.

    The config comes from ConfigCreator; levels whose window lasts over
    600 s get 75 % overlap, the others 25 % of their own window (the 32
    samples ConfigCreator sets for its 128-sample window, 64 for a
    256-sample one); then `tweaks` are applied, with the taper defaulting
    to Hann.

    Args:
        kd (KernelDataset): Kernel dataset.
        band_scheme (dict, optional): Band scheme from `mt_workbench.bands`; its
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
        if window_seconds > LONG_WINDOW_SECONDS:
            w.overlap = int(w.num_samples * 0.75)
        elif w.num_samples != AURORA_WINDOW:
            w.overlap = round(w.num_samples * ESTIMATOR_DEFAULTS["overlap_pct"] / 100.0)
    tweaks = dict(tweaks or {})
    tweaks.setdefault("taper", ESTIMATOR_DEFAULTS["taper"])  # Hann unless a taper is given
    apply_tweaks(config, tweaks)
    logger.info("estimator tweaks: " + ", ".join(f"{k}={v}" for k, v in tweaks.items()))
    return config


def band_windows(tf) -> dict[float, int]:
    """Return the number of STFT windows behind each band of an aurora TF, by period.

    aurora records, per band, its decimation level, its first and last
    harmonic and ``npts``, the observations its regression used
    (``TF.decimation_dict``, keyed by the period as text,
    `TransferFunctionKernel.export_tf_collection`). Each window gives one
    observation per harmonic. aurora 0.6.2 pairs each level's npts with its
    bands in reverse order (a 10 min C18 rr C19 window: npts 10 on the
    8-harmonic band and 40 on the 2-harmonic one, 5 windows each), so the
    windows of a level are its npts summed over its harmonics summed, which
    the pairing does not change, and every band of the level gets that
    count. A band-limited mask can leave one band fewer windows than the
    level's mean; an unestimated level has 0.

    Args:
        tf (TF): The transfer function aurora returned.

    Returns:
        dict: Period in s to its level's window count; empty for a TF
        without the record (one read back from a file).
    """
    levels: dict[int, list] = {}
    for key, band in (getattr(tf, "decimation_dict", None) or {}).items():
        first, last = (int(i) for i in band["bands"])
        levels.setdefault(int(band["level"]), []).append((float(key), int(band["npts"]), last - first + 1))
    out = {}
    for bands in levels.values():
        windows = sum(n for _, n, _ in bands) // sum(h for _, _, h in bands)
        out.update({period: windows for period, _, _ in bands})
    return out


def drop_short_bands(tf, min_windows: int, label: str) -> list[float]:
    """Remove the periods whose band rests on fewer than `min_windows` STFT windows.

    A short processing window leaves the deep decimation levels a window or
    two, whose estimate and errors mean nothing (`MIN_BAND_WINDOWS`). The
    periods removed are logged with their window counts, and kept on the TF
    as the attribute `DROPPED_ATTR` (``tf.dropped_short_bands``, sorted, an
    empty list when none), which scripts/process_rr.py records in the
    sidecar.

    Args:
        tf (TF): The transfer function aurora returned, modified in place.
        min_windows (int): The floor; 0 keeps every period.
        label (str): Start of the log line, e.g. "C18 (2023-09-23 00:00 to 00:10)".

    Returns:
        list of float: The periods removed, in s, sorted.
    """
    setattr(tf, DROPPED_ATTR, [])
    windows = band_windows(tf)
    if not min_windows or not windows:
        return []
    keys = np.array(sorted(windows))
    periods = np.asarray(tf.period, dtype=float)
    counts = np.full(periods.size, -1)
    for i, p in enumerate(periods):
        k = keys[np.argmin(np.abs(keys - p))]
        if np.isclose(k, p, rtol=1e-6):
            counts[i] = windows[k]
    short = (counts >= 0) & (counts < int(min_windows))
    if not short.any():
        return []
    dropped = sorted(float(p) for p in periods[short])
    keep_periods(tf, ~short)
    setattr(tf, DROPPED_ATTR, list(dropped))
    logger.warning(f"{label}: {len(dropped)} period(s) not written, {min(dropped):.4g} to {max(dropped):.4g} s: "
                   f"their bands rest on {sorted({int(c) for c in counts[short]})} STFT window(s), fewer than "
                   f"{int(min_windows)} (min_band_windows)")
    return dropped


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
    site=None,
    min_band_windows: int = MIN_BAND_WINDOWS,
    **config_kwargs,
):
    """Estimate a transfer function for a station, optionally remote-referenced.

    A period whose band rests on fewer than `min_band_windows` STFT windows
    (`drop_short_bands`) is removed from the TF returned, with a warning;
    the periods removed are on the TF as ``tf.dropped_short_bands``.
    Then a Z or T row with a zero or non-finite error at a period is set to
    NaN there (not estimated), and a period left with no row is removed
    (`mt_workbench.products.drop_bad_errors`), with a warning.

    When aurora cannot finish (None) or cannot export its estimate to an
    mt_metadata TF, it logs the exception and returns that in place of a
    TF (aurora 0.6.2 `process_mth5_legacy` returns its own
    TransferFunctionCollection), for example when an output channel is not
    in the local's archive (a KeyError on hz at every decimation level for
    a site with no hz whose survey.yaml entry did not say so, such as
    Tasmania's TAS132L; upstream 340). That is refused
    here with a RuntimeError naming the outputs asked for, rather than
    failing later on a missing attribute (workbench 42).

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
    - ``overlap_pct_long``: the same, applied to the long levels only (window
      over `LONG_WINDOW_SECONDS`, 600 s), the others untouched; given with
      ``overlap_pct`` it wins on those levels [absent: the 75 % boost];
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
        out_dir (Path, optional): Folder for the products; None
            writes no files. The row's EDI, EMTF XML and standalone TF h5
            are written under one stem (`mt_workbench.products.write_products`).
        min_run_seconds (float): Runs shorter than this are dropped.
        band_scheme (dict, optional): Dict from `mt_workbench.bands` (band_edges,
            decimation_factors, num_samples_window).
        start: Processing window start, UTC (see `clip_to_window`).
        end: Processing window end, UTC.
        tag (str, optional): Output file stem; default
            ``<station>_rr-<remote>`` or ``<station>_ss``.
        tweaks (dict, optional): Estimator tweaks, listed above.
        time_masks (list of dict, optional): The masks applied from the
            local and remote sites (`mt_workbench.masks.masks_for_role`,
            `mt_workbench.masks.union_masks`).
        site (SiteConfig, optional): The local site's survey.yaml settings:
            its `layout_north` sets the TF's reference frame, and when its
            `declination` is set the declination (value, model, epoch) is
            set on the TF's station metadata, both over the archive's
            (`mt_workbench.products.apply_site_frame`). The TF is not
            rotated.
        min_band_windows (int): Fewest STFT windows a band needs for its
            period to be kept [`MIN_BAND_WINDOWS`, 2]; 0 keeps every period.
        **config_kwargs: Passed to aurora's
            ``ConfigCreator.create_from_kernel_dataset``.

    Returns:
        TF: The mt_metadata transfer function.

    Raises:
        RuntimeError: When aurora returns no mt_metadata TF (its export
            failed).
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
    outputs = list(config.decimations[0].output_channels) if config.decimations else []
    with _one_electric_line(outputs) as added, slim_station_metadata(set(kd.df["run"])):
        if added:
            logger.info(f"aurora: {station} has one electric output ({', '.join(outputs)}): {', '.join(added)} "
                        f"is written as not estimated (mt_workbench.process._one_electric_line)")
        if AURORA_WINDOW_MASKS:
            if band_limited:
                _set_window_masks(config, band_limited)
            tf = process_mth5(config, kd)
        else:
            with _band_masks_applied(band_limited):
                tf = process_mth5(config, kd)
    if not hasattr(tf, "station_metadata"):
        got = "nothing" if tf is None else f"a {type(tf).__name__}"
        raise RuntimeError(
            f"aurora returned {got} for {station}, not a transfer function: its estimate or its export to "
            f"mt_metadata failed (its log above says why). Outputs asked for: {', '.join(outputs) or 'none'}, "
            f"inputs hx, hy; an output the archive does not hold (hz at a site without a vertical coil) does "
            f"this: declare the site's channels in survey.yaml")
    setattr(tf, OVERLAP_ATTR, overlap_table(config))  # issue 181: what each level used, for the sidecar
    if added:
        removed = _drop_unrecorded_lines(tf, added)
        if removed:
            logger.info(f"aurora: {station}: the empty {', '.join(added)} channel mt_metadata gave the TF's metadata "
                        f"removed ({', '.join(removed)})")

    label = station + (f" ({start or 'start'} to {end or 'end'})" if start or end else "")
    drop_short_bands(tf, min_band_windows, label)
    dropped = _keep_processed_runs(tf)
    if dropped:
        logger.info(f"{label}: {dropped} run(s) the estimate did not use left out of the product's station metadata")
    drop_bad_errors(tf, label)
    apply_site_frame(tf.station_metadata, site)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if tag is None:
            tag = f"{station}_rr-{remote_station}" if remote_station else f"{station}_ss"
        write_products(tf, out_dir / f"{tag}.edi")
    return tf
