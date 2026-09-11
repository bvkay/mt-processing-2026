"""Aurora transfer-function estimation wrappers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from aurora.config.config_creator import ConfigCreator
from aurora.pipelines.process_mth5 import process_mth5
from loguru import logger

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


# What aurora 0.6.2's ConfigCreator gives every decimation level, i.e. what a
# run without tweaks uses (overlap_pct: 25 %, then `build_config` boosts levels
# whose window lasts over 600 s to 75 %). tests/process_rr_cli_unit.py builds a
# real config and fails if these stop being the in-use values.
ESTIMATOR_DEFAULTS = {
    "taper": "boxcar",
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
DPSS_NW = 3.0  # scipy's dpss window needs a time-bandwidth product; none is set by aurora


def kernel_dataset(local_h5, station, remote_h5=None, remote_station=None,
                   start=None, end=None, min_run_seconds: float = 0.0):
    """The aurora KernelDataset for `station` (RR against `remote_station`), clipped to [start, end)."""
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
    """ConfigCreator's config for `kd`, the long-window overlap boost, then `tweaks`."""
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
    if tweaks:
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
    **config_kwargs,
):
    """Estimate a transfer function for `station`, optionally remote-referenced.

    `band_scheme` is the dict from bbmt.bands (band_edges, decimation_factors,
    num_samples_window); `start`/`end` (UTC) restrict the estimate to a
    processing window (see `clip_to_window`); `tag` overrides the output file
    stem (default ``<station>_rr-<remote>`` or ``<station>_ss``). Any further
    `config_kwargs` go to aurora's ``ConfigCreator.create_from_kernel_dataset``.

    `tweaks` changes the aurora estimator on **every** decimation level, after
    the config is built and after the long-window overlap boost; only the keys
    given are touched (the in-use value when a key is absent in brackets,
    `ESTIMATOR_DEFAULTS`):

    - ``taper``: STFT window, one of boxcar, hamming, hann, dpss [boxcar]
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
    kd = kernel_dataset(local_h5, station, remote_h5, remote_station, start, end, min_run_seconds)
    config = build_config(kd, band_scheme, tweaks, **config_kwargs)

    logger.info(
        f"aurora: {station}" + (f" RR {remote_station}" if remote_station else " single-station")
    )
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
