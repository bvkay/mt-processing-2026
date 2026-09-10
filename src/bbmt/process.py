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
    **config_kwargs,
):
    """Estimate a transfer function for `station`, optionally remote-referenced.

    `band_scheme` is the dict from bbmt.bands (band_edges, decimation_factors,
    num_samples_window); `start`/`end` (UTC) restrict the estimate to a
    processing window (see `clip_to_window`); `tag` overrides the output file
    stem (default ``<station>_rr-<remote>`` or ``<station>_ss``). Any further
    `config_kwargs` go to aurora's ``ConfigCreator.create_from_kernel_dataset``.
    Returns the mt_metadata TF object; writes an EDI when `out_dir` is given.
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
