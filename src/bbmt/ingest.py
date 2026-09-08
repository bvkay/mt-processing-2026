"""Raw LEMI-423 time series -> one MTH5 archive per site."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
import mt_io.lemi.lemi423 as _lemi423
from mt_io.lemi.lemi423 import read_lemi423
from mth5.mth5 import MTH5

from .survey import SiteConfig, Survey


def _read_coil_response(calibration_fn, coil_number=None):
    """Copy of mt_io's read_lemi_coil_response with unit names that pass
    mt_metadata 1.0.10 validation ("millivolts" is rejected, "milliVolt" is
    accepted). TODO remove once fixed upstream in mt-io."""
    calibration_fn = Path(calibration_fn)
    cal_data = np.loadtxt(calibration_fn, skiprows=2)
    fap = _lemi423.FrequencyResponseTableFilter()
    fap.frequencies = cal_data[:, 0]
    fap.amplitudes = cal_data[:, 1]
    fap.phases = np.deg2rad(cal_data[:, 2])
    # The .rsp amplitudes are normalized (~1 in passband): a shape-only
    # deconvolution. Labelling it dimensionless in the count domain keeps
    # mt_metadata's chain-consistency check happy with the reader's filter
    # order [linear nT->count, coil]; see docs/upstream_issues.md #2.
    fap.units_in = "digital counts"
    fap.units_out = "digital counts"
    fap.name = (
        f"lemi_120_{coil_number}_response" if coil_number else "lemi_120_response"
    )
    fap.calibration_date = "1970-01-01T00:00:00+00:00"
    fap.comments = f"LEMI-120 coil response from {calibration_fn.name}"
    return fap


_lemi423.read_lemi_coil_response = _read_coil_response


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
        # the reader already writes the standard azimuth into the channel
        # attrs, so flipping the data is the whole correction. NB mutate
        # run.dataset directly: run.<comp> accessors return fresh copies.
        run.dataset[comp].data = -run.dataset[comp].data
        logger.info(f"{site.name} {comp}: azimuth {az} -> sign-flipped to {standard}")


def _apply_h_scale(run, site: SiteConfig) -> None:
    """Fold `h_scale` into each magnetic channel's filter chain.

    Appended as an explicit CoefficientFilter so the correction is visible in
    the MTH5 provenance. Calibration divides by the chain response, so a gain
    of -1000 turns the reader's pT-with-inverted-polarity output into nT in
    the lemimt convention. Applied to hz too, which leaves the tipper
    unchanged (numerator and denominator flip together).
    """
    if site.h_scale == 1.0:
        return
    coef = _lemi423.CoefficientFilter()
    coef.name = "lemi423_b_scale"
    coef.gain = site.h_scale
    # labelled dimensionless in the count domain to satisfy the chain
    # consistency check (see docs/upstream_issues.md #2)
    coef.units_in = "digital counts"
    coef.units_out = "digital counts"
    coef.comments = (
        f"empirical magnetic scale/polarity vs lemimt convention: "
        f"gain {site.h_scale} (pT -> nT with sign flip)"
    )
    # RunTS keeps filters in run.filters and the per-channel applied list in
    # dataset attrs; run.<comp> accessors return fresh copies, so mutating
    # those would be lost.
    run.filters[coef.name] = coef
    for comp in ("hx", "hy", "hz"):
        if comp not in run.dataset:
            continue
        flist = list(run.dataset[comp].attrs.get("filters") or [])
        flist.append(
            {
                "applied_filter": {
                    "applied": True,
                    "name": coef.name,
                    "stage": len(flist) + 1,
                }
            }
        )
        run.dataset[comp].attrs["filters"] = flist


def _group_contiguous(files: list[Path], max_run_files: int | None = None) -> list[list[Path]]:
    """Group B423 files into contiguous runs using their epoch filenames.

    Files are nominally back-to-back (epoch spacing == file length, typically
    5400 s); any other spacing means a real gap (e.g. the short first file
    after deployment) and starts a new run. Long runs matter: aurora STFTs
    each run independently, so the longest estimable period is set by run
    length, not total recording.
    """
    epochs = [int(f.stem) for f in files]
    diffs = np.diff(epochs)
    nominal = int(np.median(diffs)) if diffs.size else 0

    groups: list[list[Path]] = [[files[0]]]
    for fn, diff in zip(files[1:], diffs):
        full = max_run_files is not None and len(groups[-1]) >= max_run_files
        if diff == nominal and not full:
            groups[-1].append(fn)
        else:
            groups.append([fn])
    return groups


def ingest_site(
    survey: Survey,
    site_name: str,
    start=None,
    end=None,
    out_path: Path | None = None,
    overwrite: bool = False,
    max_run_files: int | None = None,
) -> Path:
    """Read a site's B423 files and write an MTH5.

    Contiguous files (exact epoch spacing) are merged into long runs so aurora
    can use long STFT windows; any spacing anomaly starts a new run, so gaps
    never corrupt sample timing.
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

    groups = _group_contiguous(files, max_run_files)
    logger.info(
        f"{site_name}: ingesting {len(files)} files as {len(groups)} run(s) -> {out_path}"
    )
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = None
        for i, group in enumerate(groups, 1):
            run = read_lemi423(group if len(group) > 1 else group[0], **read_kwargs)
            _standardise_e_orientation(run, site)
            _apply_h_scale(run, site)
            run_id = f"sr{int(run.sample_rate)}_{i:04d}"
            run.run_metadata.id = run_id
            if station_group is None:
                station_group = m.add_station(site_name, survey=survey.name)
                station_group.metadata.update(run.station_metadata)
                station_group.write_metadata()
            run_group = station_group.add_run(run_id)
            run_group.from_runts(run)
            logger.info(
                f"{site_name}: run {run_id} <- {len(group)} file(s) "
                f"({group[0].name} .. {group[-1].name})"
            )
    finally:
        m.close_mth5()
    return out_path
