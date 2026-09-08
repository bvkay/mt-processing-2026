"""Raw LEMI-423 time series -> one MTH5 archive per site."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mt_io.lemi.lemi423 import read_lemi423
from mth5.mth5 import MTH5

from .survey import SiteConfig, Survey


def select_files(site_dir: Path, start=None, end=None) -> list[Path]:
    """Return the site's B423 files overlapping [start, end).

    B423 filenames are unix epochs (UTC) of the file start; a file's span is
    taken as running to the next file's epoch (median spacing for the last).
    """
    files = sorted(site_dir.rglob("*.B423"), key=lambda p: int(p.stem))
    if not files:
        raise FileNotFoundError(f"no .B423 files under {site_dir}")
    if start is None and end is None:
        return files
    epochs = np.array([int(f.stem) for f in files], dtype="int64")
    spans = np.diff(epochs)
    file_len = int(np.median(spans)) if spans.size else 5400
    ends = np.append(epochs[1:], epochs[-1] + file_len)
    t0 = pd.Timestamp(start, tz="UTC").timestamp() if start else -np.inf
    t1 = pd.Timestamp(end, tz="UTC").timestamp() if end else np.inf
    keep = (epochs < t1) & (ends > t0)
    selected = [f for f, k in zip(files, keep) if k]
    if not selected:
        raise ValueError(f"no files in {site_dir} overlap [{start}, {end})")
    return selected


def _standardise_e_orientation(run, site: SiteConfig) -> None:
    """Sign-flip electric channels recorded with reversed dipoles.

    Field crews sometimes lay dipoles at 180/270 deg; the data are the negative
    of the standard 0/90 frame. Flipping at ingest keeps everything downstream
    in one convention. Arbitrary azimuths are not handled (none in our surveys).
    """
    for comp, az, standard in (
        ("ex", site.azimuth_ex, 0.0),
        ("ey", site.azimuth_ey, 90.0),
    ):
        if comp not in run.dataset:
            continue
        off = (az - standard) % 360.0
        if off == 0.0:
            continue
        if off != 180.0:
            raise ValueError(
                f"{site.name} {comp}: azimuth {az} needs a real rotation — "
                f"only reversed (180 deg) dipoles are handled at ingest"
            )
        run.dataset[comp].data = -run.dataset[comp].data
        ch = getattr(run, comp)
        ch.channel_metadata.measurement_azimuth = standard
        ch.channel_metadata.comments = (
            f"recorded at azimuth {az} deg, sign-flipped to {standard} deg at ingest"
        )
        logger.info(f"{site.name} {comp}: azimuth {az} -> sign-flipped to {standard}")


def ingest_site(
    survey: Survey,
    site_name: str,
    start=None,
    end=None,
    out_path: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Read a site's B423 files and write an MTH5 (one run per raw file).

    Runs stay one-per-file because consecutive B423 files can be separated by
    small gaps; concatenating across them would corrupt sample timing. Aurora
    merges spectra across runs, so many short runs cost almost nothing.
    """
    site = survey.site(site_name)
    site_dir = survey.site_dirs()[site_name]
    files = select_files(site_dir, start, end)

    out_path = Path(out_path) if out_path else survey.workspace / "mth5" / f"{site_name}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        if not overwrite:
            logger.info(f"{out_path} exists — reusing (overwrite=False)")
            return out_path
        out_path.unlink()

    read_kwargs = dict(
        station_id=site_name,
        dipole_length_ex=site.dipole_length_ex,
        dipole_length_ey=site.dipole_length_ey,
    )
    if site.calibration_fn:
        cal = Path(site.calibration_fn)
        if not cal.is_absolute():
            cal = survey.data_root / cal
        if not cal.exists():
            raise FileNotFoundError(f"coil calibration file not found: {cal}")
        read_kwargs["calibration_fn"] = cal
    else:
        logger.warning(
            f"{site_name}: no calibration_fn — magnetic channels will lack a "
            f"coil response and TFs will be wrong"
        )

    logger.info(f"{site_name}: ingesting {len(files)} files -> {out_path}")
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = None
        for i, fn in enumerate(files, 1):
            run = read_lemi423(fn, **read_kwargs)
            _standardise_e_orientation(run, site)
            run_id = f"sr{int(run.sample_rate)}_{i:04d}"
            run.run_metadata.id = run_id
            if station_group is None:
                station_group = m.add_station(site_name, survey=survey.name)
                station_group.metadata.update(run.station_metadata)
                station_group.write_metadata()
            run_group = station_group.add_run(run_id)
            run_group.from_runts(run)
            logger.info(f"{site_name}: run {run_id} <- {fn.name}")
    finally:
        m.close_mth5()
    return out_path
