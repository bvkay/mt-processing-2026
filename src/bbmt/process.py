"""Aurora transfer-function estimation wrappers."""

from __future__ import annotations

from pathlib import Path

from aurora.config.config_creator import ConfigCreator
from aurora.pipelines.process_mth5 import process_mth5
from loguru import logger

try:  # newer stacks host these in mth5
    from mth5.processing import KernelDataset, RunSummary
except ImportError:  # older aurora
    from aurora.pipelines.run_summary import RunSummary
    from aurora.transfer_function.kernel_dataset import KernelDataset


def process_station(
    local_h5: Path,
    station: str,
    remote_h5: Path | None = None,
    remote_station: str | None = None,
    out_dir: Path | None = None,
    min_run_seconds: float = 0.0,
    band_scheme: dict | None = None,
    **config_kwargs,
):
    """Estimate a transfer function for `station`, optionally remote-referenced.

    `band_scheme` is the dict from bbmt.bands (band_edges, decimation_factors,
    num_samples_window); any further `config_kwargs` go to aurora's
    ``ConfigCreator.create_from_kernel_dataset``.
    Returns the mt_metadata TF object; writes an EDI when `out_dir` is given.
    """
    rs = RunSummary()
    paths = [Path(local_h5)]
    if remote_h5 is not None and Path(remote_h5) != Path(local_h5):
        paths.append(Path(remote_h5))
    rs.from_mth5s(paths)

    kd = KernelDataset()
    kd.from_run_summary(rs, station, remote_station)
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
        tag = f"{station}_rr-{remote_station}" if remote_station else f"{station}_ss"
        edi_path = out_dir / f"{tag}.edi"
        tf.write(fn=edi_path, file_type="edi")
        logger.info(f"wrote {edi_path}")
    return tf
