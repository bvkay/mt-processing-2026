# -*- coding: utf-8 -*-
"""
Raw time series to one MTH5 archive per site, plus filtered variants

`ingest_site` writes one archive per site, `<workspace>/mth5/<site>.h5`
(`default_archive_path`), holding the raw recording with calibration only:
the coil response, `h_scale` and the reversed-dipole flip. Entries of
`filters.yaml`, including `replace`, are applied in the variants described
below. LEMI-424 and Earth Data PR6-24 sites are read by their mt-io readers
(`mtproc.instruments.read_run`) with the reader's channel names and filter
chain. The site's instrument is `Survey.instrument_of(site)`.

LEMI-423 files are read by `read_lemi423` of the mt-io fork. It parses the
four-digit altitude line of firmware 2.1 (``%Alt1060.0,m``) and, given a
`calibration_fn`, builds each magnetic channel's chain from physical to
recorded, [LEMI-120 coil table nT -> nT (normalized), linear nT -> counts],
with units mt_metadata accepts (docs/upstream_issues.md 1, 2 and 6).
`_apply_h_scale` appends one stage to that chain.

A site's declared filters (`<survey>/filters.yaml`) are applied to the raw
archive on demand, producing a variant `<site>_f<hash>.h5` (`variant_path`,
with `hash` the `filters_hash` of the declared list). `build_variant` builds
it from the raw archive's runs, reading `replace` donors from their raw
archives, and leaves the raw archive unchanged. `processing_archive` returns
the archive processing should read: it builds the variant if it is missing
or stale (an edit of `filters.yaml` changes the hash) and returns the raw
path for a site with no declared filters. An old-layout archive, whose run
comments record filters applied inside `<site>.h5`, is rejected by
`processing_archive` (`archive_filter_kinds`) and must be rebuilt raw.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
import mt_io.lemi.lemi423 as _lemi423
from mt_io.lemi.lemi423 import read_lemi423
from mth5.mth5 import MTH5

from .instruments import (  # noqa: F401
    INSTRUMENTS, b423_files, edl_electric_gain, edl_sample_rate, edl_sensor, file_start, read_run,
    record_files, recorder_ini_high_gain,
)
from .noise import apply_filters_arrays
from .survey import SiteConfig, Survey
from .timefreq import _real_runs


def default_archive_path(survey: Survey, site_name: str, ignore_filters: bool = False) -> Path:
    """Return the path of a site's raw archive, ``<workspace>/mth5/<site>.h5``.

    For the archive with the site's declared filters applied, use
    `processing_archive`.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        ignore_filters (bool): Accepted for compatibility with older callers
            and ignored; the raw archive is the unfiltered archive.

    Returns:
        Path: The archive path.
    """
    return survey.workspace / "mth5" / f"{site_name}.h5"


# prefix of the filter provenance in a run comment, written by an old-layout
# `ingest_site` build (`_filter_lines`, `archive_filter_kinds`) or by
# `build_variant` (after `_VARIANT_HASH_PREFIX`, below); the text after it is
# one provenance line per filter, joined by "; then "
_FILTERS_PREFIX = "ingest filters (in order): "
# prefix of a `build_variant` run comment: the hash, then `_FILTERS_PREFIX` and
# the same provenance lines an old-layout archive carries
_VARIANT_HASH_PREFIX = "filters hash "


def _run_comment(run_group) -> str:
    """Return a run group's comment text, "" when there is none."""
    comment = run_group.metadata.comments
    return "" if comment is None else str(getattr(comment, "value", comment) or "")


def _all_real_run_comments(path: Path) -> list[str] | None:
    """Return the comment of every real run in an archive's station, earliest first.

    Real runs come from `_real_runs`, which skips the auxiliary station-level
    groups of mth5 and aurora. The archive is opened read-only.

    Args:
        path (Path): MTH5 file with one station.

    Returns:
        list of str or None: The comments; an empty list for an archive with
        no real run; None when the file does not exist or is a ``.part``
        temporary file of `build_variant`, which is moved onto the final
        name with `os.replace` once every run is written and both files are
        closed.
    """
    path = Path(path)
    if path.suffix == ".part" or not path.exists():
        return None
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        stations = m.station_list
        if not stations:
            return []
        survey_name = m.surveys_group.groups_list[0]
        station = m.get_station(stations[0], survey=survey_name)
        return [_run_comment(station.get_run(run_id)) for run_id, _start, _end in _real_runs(station)]
    finally:
        m.close_mth5()


def _earliest_real_run_comment(path: Path) -> str | None:
    """Return the earliest real run's comment (`_all_real_run_comments`).

    Used by `archive_filter_kinds`: one `ingest_site` or `build_variant`
    call applies the same filters to every run of a site, so the earliest
    run represents the archive. `variant_ready` checks every run.

    Returns:
        str or None: The comment; "" for an archive with no real run; None
        for a missing file or a ``.part`` temporary file.
    """
    comments = _all_real_run_comments(path)
    return None if comments is None else (comments[0] if comments else "")


def _filter_lines(comment: str) -> list[tuple[str, str]]:
    """Parse the filter provenance lines out of a run comment.

    The comment must start with `_FILTERS_PREFIX`, optionally preceded by
    the `_VARIANT_HASH_PREFIX` part. The electric-gain note that
    `ingest_site` may append follows the last filter's line after "; "
    (rather than "; then ") and is stripped from that line.

    Args:
        comment (str): Run comment.

    Returns:
        list of tuple: ``(kind, provenance_line)`` pairs; empty when the
        comment records no filters.
    """
    if comment.startswith(_VARIANT_HASH_PREFIX):
        comment = comment.split("; ", 1)[1] if "; " in comment else ""
    if not comment.startswith(_FILTERS_PREFIX):
        return []
    body = comment[len(_FILTERS_PREFIX):]
    out = []
    for segment in body.split("; then "):
        segment = segment.split("; electric gain", 1)[0]
        token = segment.split(None, 1)[0].rstrip(":") if segment else ""
        out.append((token, segment))
    return out


def archive_filter_kinds(path: Path) -> list[str] | None:
    """Return the filter kinds recorded in an archive's run comments, in order.

    A non-empty result on `default_archive_path` marks an old-layout
    archive with filters applied inside the raw archive; `processing_archive`
    and `build_variant` reject such an archive. See `_filter_lines` for how
    the comment is parsed.

    Args:
        path (Path): MTH5 file.

    Returns:
        list of str or None: The kinds; an empty list for a raw archive, as
        `ingest_site` writes, or one with no real run; None when the archive
        does not exist.
    """
    comment = _earliest_real_run_comment(path)
    return None if comment is None else [kind for kind, _line in _filter_lines(comment)]


def filters_hash(filters: list[dict] | None) -> str:
    """Hash a declared filter list.

    The hash is the first 8 hex characters of the sha1 of
    ``json.dumps(filters, sort_keys=True)``. It forms the ``_f<hash>``
    suffix of `variant_path` and is recorded in `build_variant` run
    comments. It depends on the order of the entries, since the order
    changes what is applied.

    Args:
        filters (list of dict or None): Declared filters.

    Returns:
        str: 8 hex characters.
    """
    text = json.dumps(list(filters or []), sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def variant_path(survey: Survey, site_name: str) -> Path:
    """Return the variant path ``<workspace>/mth5/<site>_f<hash>.h5``.

    The hash is `filters_hash` of the site's current declared filters. The
    path applies to sites that declare filters; `processing_archive` and
    `variant_ready` use the raw archive for a site without them.
    """
    h = filters_hash(survey.site(site_name).filters)
    return survey.workspace / "mth5" / f"{site_name}_f{h}.h5"


def variant_ready(survey: Survey, site_name: str) -> bool:
    """Return whether the site's variant is complete and current.

    The variant is ready when `variant_path` names a finished file (a
    ``.part`` file still being written gives None from
    `_all_real_run_comments`), every real run's comment carries a recorded
    hash, and every hash equals `filters_hash` of the site's current
    declaration. Every run is checked, which detects a variant cut short by
    a process killed during `os.replace`, or a file copied in or edited by
    hand.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.

    Returns:
        bool: False also for a site with no declared filters.
    """
    site = survey.site(site_name)
    if not site.filters:
        return False
    comments = _all_real_run_comments(variant_path(survey, site_name))
    if not comments:
        return False
    want = filters_hash(site.filters)
    for comment in comments:
        if not comment.startswith(_VARIANT_HASH_PREFIX):
            return False
        if comment[len(_VARIANT_HASH_PREFIX):].split(";", 1)[0].strip() != want:
            return False
    return True


def _donor_channel(survey: Survey, donor_site: str, comp: str, t0, n: int, fs: float, tag: str) -> np.ndarray:
    """Read a donor channel for a `replace` filter from the donor's raw archive.

    `build_variant` passes the result to `apply_filters_arrays` as
    ``donors[donor_site][comp]``. The archive is opened read-only.

    Args:
        survey (Survey): The survey.
        donor_site (str): Donor site name.
        comp (str): Channel component.
        t0 (pd.Timestamp): Time of the first sample.
        n (int): Number of samples.
        fs (float): Sample rate in Hz.
        tag (str): Label for error messages.

    Returns:
        np.ndarray: `n` raw counts.

    Raises:
        FileNotFoundError: If the donor has no raw archive.
        ValueError: If no donor run covers the span, the sample rate
            differs, the run does not start on the target's sample grid
            (the GPS timing assumption, as in `mtproc.virtual`), or the run
            is too short.
    """
    path = default_archive_path(survey, donor_site)
    if not path.exists():
        raise FileNotFoundError(f"{tag}: replace donor {donor_site} has no raw archive at {path} -- ingest it first")
    t1 = t0 + pd.Timedelta(seconds=(n - 1) / fs)
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        station = m.get_station(donor_site, survey=survey_name)
        best = next((r for r, start, end in _real_runs(station) if start <= t0 and end >= t1), None)
        if best is None:
            raise ValueError(f"{tag}: replace donor {donor_site} has no run covering {t0} .. {t1}")
        ch = station.get_run(best).get_channel(comp)
        ch_fs = float(ch.metadata.sample_rate)
        if abs(ch_fs - fs) > 1e-9 * fs:
            raise ValueError(f"{tag}: replace donor {donor_site} {comp} is {ch_fs:g} Hz, not {fs:g} Hz")
        ch_start = pd.Timestamp(str(ch.metadata.time_period.start))
        offset = (t0 - ch_start).total_seconds() * fs
        i0 = int(round(offset))
        if abs(offset - i0) > 1e-3:
            raise ValueError(
                f"{tag}: replace donor {donor_site} {comp}'s run starts {offset - i0:+.4f} samples off the "
                f"target's grid -- GPS timing assumption violated, investigate before building the variant"
            )
        data = np.asarray(ch.hdf5_dataset[i0:i0 + n])
        if data.shape[0] != n:
            raise ValueError(f"{tag}: replace donor {donor_site} {comp}'s run is short by {n - data.shape[0]} "
                             f"sample(s) for this window")
        return data
    finally:
        m.close_mth5()


def build_variant(survey: Survey, site_name: str, workers: int = 4) -> Path:
    """Build or replace a site's filtered variant from its raw archive.

    The raw archive (`default_archive_path`) is read run by run
    (`_real_runs`). The site's declared `filters.yaml` list is applied to
    each run's channel arrays (`mtproc.noise.apply_filters_arrays`, with
    `workers` threads per filter); `replace` entries read the donor's raw
    archive over the run's span (`_donor_channel`), so a donor may be any
    instrument. The result is written to `variant_path` with the same runs,
    the raw station's metadata, and each run's provenance lines behind a
    leading ``filters hash <hash>; `` that `variant_ready` reads back. One
    run's channel arrays are held in memory at a time. The file is written
    under a ``.part`` name and moved into place when complete. After a
    successful write every other ``<site>_f*.h5`` is deleted, leaving one
    variant per site.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        workers (int): Threads per filter.

    Returns:
        Path: The variant path.

    Raises:
        ValueError: If the site declares no filters (the raw archive is then
            the processing archive), the raw archive is an old-layout
            archive with filters applied (rebuild it with
            ``scripts/ingest_site.py <survey.yaml> <site> --raw``), or it
            has no real run.
        FileNotFoundError: If the raw archive is missing.
    """
    site = survey.site(site_name)
    filters = site.filters or []
    if not filters:
        raise ValueError(f"{site_name}: no declared filters -- there is no variant to build")
    raw_path = default_archive_path(survey, site_name)
    if not raw_path.exists():
        raise FileNotFoundError(f"{site_name}: no raw archive at {raw_path} -- ingest it first")
    baked = archive_filter_kinds(raw_path)
    if baked:
        raise ValueError(
            f"{site_name}: {raw_path.name} was built with filters baked in (old layout: {baked}) -- rebuild it "
            f"raw first: `scripts/ingest_site.py <survey.yaml> {site_name} --raw`"
        )
    h = filters_hash(filters)
    out_path = survey.workspace / "mth5" / f"{site_name}_f{h}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # written under a .part name and moved onto out_path once every run is
    # written and both files are closed (os.replace, below); after a crash
    # midway only the .part file exists, which variant_ready does not accept
    tmp_path = out_path.with_name(out_path.name + ".part")
    if tmp_path.exists():
        tmp_path.unlink()

    started = time.perf_counter()
    m_in = MTH5()
    m_in.open_mth5(raw_path, mode="r")
    try:
        survey_name_in = m_in.surveys_group.groups_list[0]
        station_in = m_in.get_station(site_name, survey=survey_name_in)
        runs = _real_runs(station_in)
        if not runs:
            raise ValueError(f"{site_name}: {raw_path.name} has no real run to filter")
        donor_sites = sorted({str(d) for spec in filters if "replace" in spec
                              for d in (spec["replace"] or {}).values()})

        m_out = MTH5(file_version="0.2.0")
        m_out.open_mth5(tmp_path, mode="w")
        try:
            m_out.add_survey(survey.name)
            station_out = m_out.add_station(site_name, survey=survey.name)
            station_out.metadata.update(station_in.metadata)
            station_out.write_metadata()
            for run_id, t0, _t1 in runs:
                run = station_in.get_run(run_id).to_runts()
                comps = list(run.dataset.data_vars)
                donors = {}
                for donor in donor_sites:
                    needed = [c for spec in filters if "replace" in spec
                             for c, d in (spec["replace"] or {}).items() if str(d) == donor]
                    if needed:
                        donors[donor] = {c: _donor_channel(survey, donor, c, t0, run.dataset.time.size,
                                                            run.sample_rate, site_name) for c in needed}
                arrays = {c: run.dataset[c].data for c in comps}
                out, lines = apply_filters_arrays(arrays, run.sample_rate, filters, tag=site_name,
                                                  donors=donors, workers=workers)
                for comp in comps:
                    if not np.may_share_memory(out[comp], arrays[comp]):
                        run.dataset[comp].data = out[comp]
                run.run_metadata.comments.value = (
                    f"{_VARIANT_HASH_PREFIX}{h}; {_FILTERS_PREFIX}" + "; then ".join(lines)
                )
                run_group = station_out.add_run(run_id)
                run_group.from_runts(run)
                logger.info(f"{site_name}: variant run {run_id} <- {len(lines)} filter(s)")
        finally:
            m_out.close_mth5()
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    finally:
        m_in.close_mth5()

    # every run is written and both files are closed; os.replace is an atomic
    # rename on the same filesystem (POSIX and Windows), overwriting any
    # existing out_path of the same hash
    os.replace(tmp_path, out_path)
    took = time.perf_counter() - started
    size_mb = out_path.stat().st_size / 1e6
    logger.info(f"{site_name}: built variant {out_path.name} ({len(runs)} run(s), {size_mb:.1f} MB) in {took:.1f} s")

    for other in (survey.workspace / "mth5").glob(f"{site_name}_f*.h5"):
        if other != out_path:
            other.unlink()
            logger.info(f"{site_name}: pruned the outdated variant {other.name}")
    return out_path


def processing_archive(survey: Survey, site_name: str, use_filters: bool = True) -> Path:
    """Return the archive a processing run reads for a site.

    This is the raw archive (`default_archive_path`) when `use_filters` is
    False or the site declares no filters, and otherwise the filtered
    variant (`variant_path`), built first with `build_variant` when it is
    missing or its recorded hash differs from the current declaration
    (`variant_ready`). The raw archive must already exist; ingest runs in
    `ingest_site`.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        use_filters (bool): Whether to apply the declared filters.

    Returns:
        Path: The archive path.

    Raises:
        FileNotFoundError: If the raw archive does not exist.
        ValueError: If the raw archive is an old-layout archive with filters
            applied (`archive_filter_kinds`); rebuild it with
            ``scripts/ingest_site.py <survey.yaml> <site> --raw``.
    """
    site = survey.site(site_name)
    raw = default_archive_path(survey, site_name)
    if not raw.exists():
        raise FileNotFoundError(
            f"{site_name}: no archive at {raw} -- ingest it first (scripts/ingest_site.py, or the "
            f"Time Series tab's Build MTH5)"
        )
    baked = archive_filter_kinds(raw)
    if baked:
        raise ValueError(
            f"{site_name}: {raw.name} was built with filters baked in (old layout: {baked}) -- rebuild it "
            f"raw first: `scripts/ingest_site.py <survey.yaml> {site_name} --raw`"
        )
    if not use_filters or not site.filters:
        return raw
    if not variant_ready(survey, site_name):
        return build_variant(survey, site_name)
    return variant_path(survey, site_name)


def select_files(site_dir: Path, start=None, end=None, instrument: str = "lemi423") -> list[Path]:
    """Return the site's data files overlapping [start, end).

    File names carry each file's start in UTC (the unix epoch for B423,
    `mtproc.instruments.file_start` for the others). A file's span runs to
    the next file's start, or the median spacing for the last file. An EDL
    stamp names five channel files, which are kept or dropped together.

    Args:
        site_dir (Path): Site folder.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.
        instrument (str): Key of `INSTRUMENTS`.

    Returns:
        list of Path: The selected files.

    Raises:
        FileNotFoundError: If the folder holds no files of the instrument.
        ValueError: If no file overlaps the window.
    """
    if instrument != "lemi423":
        return _select_stamped(site_dir, start, end, instrument)
    files = b423_files(site_dir)
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


def _select_stamped(site_dir: Path, start, end, instrument: str) -> list[Path]:
    """Apply the `select_files` rule to each distinct file start of a LEMI-424 or EDL site."""
    files = record_files(Path(site_dir), instrument)
    if not files:
        spec = INSTRUMENTS[instrument]
        raise FileNotFoundError(f"no {spec['label']} files ({spec['pattern']}) under {site_dir}")
    if start is None and end is None:
        return files
    stamps = np.array([file_start(f, instrument) for f in files], dtype="int64")
    starts = np.unique(stamps)
    spans = np.diff(starts)
    file_len = int(np.median(spans)) if spans.size else INSTRUMENTS[instrument]["file_seconds"]
    ends = np.append(starts[1:], starts[-1] + file_len)
    t0 = pd.Timestamp(start, tz="UTC").timestamp() if start else -np.inf
    t1 = pd.Timestamp(end, tz="UTC").timestamp() if end else np.inf
    keep = set(starts[(starts < t1) & (ends > t0)].tolist())
    selected = [f for f, s in zip(files, stamps) if int(s) in keep]
    if not selected:
        raise ValueError(f"no files in {site_dir} overlap [{start}, {end})")
    return selected


def _standardise_e_orientation(run, site: SiteConfig) -> None:
    """Sign-flip electric channels recorded with reversed dipoles.

    Dipoles laid at 180/270 deg record the negative of the standard 0/90
    frame; flipping at ingest keeps later processing in one convention. The
    flip is skipped with a log line when `flip_reversed_dipoles` is False.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Raises:
        ValueError: If an azimuth is neither standard nor reversed by 180 deg.
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
        if not site.flip_reversed_dipoles:
            logger.info(
                f"{site.name} {comp}: azimuth {az} taken as layout direction only "
                f"(flip_reversed_dipoles=False) — no sign flip"
            )
            continue
        # the reader writes the standard azimuth into the channel attrs, so
        # flipping the data completes the correction. run.dataset is modified
        # directly because run.<comp> accessors return copies.
        run.dataset[comp].data = -run.dataset[comp].data
        logger.info(f"{site.name} {comp}: azimuth {az} -> sign-flipped to {standard}")


def _apply_h_scale(run, site: SiteConfig) -> None:
    """Fold `h_scale` into each magnetic channel's filter chain.

    The scale is appended as a CoefficientFilter, so the correction is
    recorded in the MTH5 provenance. Calibration divides by the chain
    response, so a gain of -1000 turns the reader's pT output with inverted
    polarity into nT in the lemimt convention. It is applied to hz too,
    which leaves the tipper unchanged since numerator and denominator flip
    together. A scale of 1.0 adds nothing.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.
    """
    if site.h_scale == 1.0:
        return
    coef = _lemi423.CoefficientFilter()
    coef.name = "lemi423_b_scale"
    coef.gain = site.h_scale
    # appended after the linear stage (nT -> counts), so it maps counts to
    # counts: the chain's units stay consistent (docs/upstream_issues.md 2)
    coef.units_in = "digital counts"
    coef.units_out = "digital counts"
    coef.comments = (
        f"empirical magnetic scale/polarity vs lemimt convention: "
        f"gain {site.h_scale} (pT -> nT with sign flip)"
    )
    # RunTS keeps filters in run.filters and the per-channel applied list in
    # dataset attrs; run.<comp> accessors return copies, so the attrs are
    # modified directly.
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


def _electric_gain(survey: Survey, site: SiteConfig, instrument: str, site_dir: Path) -> float:
    """Return the electric gain `read_run` folds into the ex and ey chains.

    Checked once per site before anything is written. For EDL sites this is
    `SiteConfig.electric_gain` (`edl_electric_gain`, default 1.0 with no
    filter). The recorder.ini ``channel_n_high_gain`` flags
    (`recorder_ini_high_gain`) produce an informational warning when set;
    the declared value is the electric chain gain from the field notes,
    separate from the PR6-24 pre-amplifier setting. For other instruments a
    `defaults:` value is ignored and the gain is 1.0.

    Args:
        survey (Survey): The survey.
        site (SiteConfig): Site settings.
        instrument (str): The site's instrument.
        site_dir (Path): Site folder.

    Returns:
        float: The gain.

    Raises:
        ValueError: If a non-EDL site sets its own `electric_gain` other
            than 1.0.
    """
    if instrument != "edl":
        own = ((survey.config.get("sites") or {}).get(site.name) or {}).get("electric_gain")
        if own is not None and float(own) != 1.0:
            raise ValueError(f"{site.name}: electric_gain {own} is an Earth Data PR6-24 (EDL) electric-chain "
                             f"setting, and this site is {instrument}: remove the key from its survey.yaml entry")
        return 1.0
    gain = edl_electric_gain(site)
    from_ini = recorder_ini_high_gain(site_dir)
    if from_ini:
        logger.warning(f"{site.name}: recorder.ini says channel_n_high_gain=1 for {' '.join(from_ini)}; "
                       f"electric_gain declared as {gain:g} -- informational, the flag is not used")
    return gain


def _keep_channels(run, site: SiteConfig) -> None:
    """Drop channels not listed in `site.channels`, such as an unconnected hz.

    The reader returns every column of the file, and the survey declares
    which had a sensor attached. Dropping the others keeps the MTH5 to the
    recorded channels, so aurora estimates no tipper from an open input.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Raises:
        ValueError: If none of the declared channels is among the reader's.
    """
    if not site.channels:
        return
    keep = [c.lower() for c in site.channels]
    drop = [c for c in run.dataset.data_vars if c not in keep]
    if not drop:
        return
    if len(drop) == len(run.dataset.data_vars):
        raise ValueError(
            f"{site.name}: none of the declared channels {keep} is among the reader's "
            f"{list(run.dataset.data_vars)} -- declare this site's `channels:` in its instrument's names"
        )
    run.dataset = run.dataset.drop_vars(drop)
    for attr in ("channels_recorded_magnetic", "channels_recorded_electric", "channels_recorded_auxiliary"):
        current = getattr(run.run_metadata, attr, None)
        if current:
            setattr(run.run_metadata, attr, [c for c in current if c.lower() in keep])
    logger.info(f"{site.name}: dropped {drop} at ingest (survey channels {keep})")


def _incomplete_stamps(files: list[Path], stamps: list[int]) -> set[int]:
    """Find the EDL file stamps without exactly one file per channel.

    mt-io's reader (`mt_io.uoa.pr624.UoAReader.read`) joins each channel's
    files end to end and trims every channel to the shortest, so a stamp
    missing one channel's file shifts that channel's later samples early by
    the file's length, to the end of the run: read as a whole, a site with no
    EX file at one stamp has, in its ex, the next file's samples at every
    later time, while the other channels are correct. A stamp with two files
    for a channel (a test recording kept in a subfolder with the stamps of the
    real files) includes both and dates every later sample late. Such a stamp
    is left out for every channel, and the run ends there as at a gap.

    Args:
        files (list of Path): EDL files.
        stamps (list of int): Start stamp of each file, unix seconds.

    Returns:
        set of int: The stamps to leave out.
    """
    have: dict[int, list[str]] = {}
    for f, s in zip(files, stamps):
        have.setdefault(s, []).append(Path(f).suffix.upper())
    every = set().union(*have.values()) if have else set()
    bad = {}
    for s, suffixes in have.items():
        missing = sorted(every - set(suffixes))
        twice = sorted({x for x in suffixes if suffixes.count(x) > 1})
        if missing or twice:
            bad[s] = "; ".join(t for t in (f"no {' '.join(missing)}" if missing else "",
                                           f"two {' '.join(twice)}" if twice else "") if t)
    if bad:
        listed = ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} ({why})" for s, why in sorted(bad.items()))
        logger.warning(f"{len(bad)} EDL file stamp(s) without exactly one file per channel: {listed} -- "
                       f"left out, the run split there")
    return set(bad)


def _edl_runs_by_samples(files: list[Path], stamps: list[int], drop: set[int], rate: float) -> list[set[int]]:
    """Group EDL stamps into runs by sample count.

    Follows mt-io's contiguity rule (`UoACollection._run_boundaries`). Every
    file's samples are counted (`mt_io.uoa.pr624.count_samples`, a newline
    count taking a few seconds per site once the files are cached). A stamp
    joins the run when it starts where the previous stamp's files end, to
    within two samples, so a file shorter than the time to the next stamp
    ends its run. Stamp spacing alone does not detect this: short startup
    files (e.g. 15 s each, stamped 300 s apart), read as one stretch, date
    every later sample of the run early (mt-io's reader warns of the seconds
    missing between files). A stamp whose channel files differ in length is
    left out, as a stamp with a missing file is.

    Args:
        files (list of Path): EDL files.
        stamps (list of int): Start stamp of each file, unix seconds.
        drop (set of int): Stamps already left out (`_incomplete_stamps`).
        rate (float): Sample rate in Hz.

    Returns:
        list of set: The stamps of each run.
    """
    from mt_io.uoa.pr624 import count_samples

    lengths: dict[int, set[int]] = {}
    for f, s in zip(files, stamps):
        lengths.setdefault(s, set()).add(count_samples(f))
    uneven = {s for s, n in lengths.items() if len(n) > 1 and s not in drop}
    if uneven:
        logger.warning(f"{len(uneven)} EDL file stamp(s) whose channel files differ in length: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} {sorted(lengths[s])}"
                                   for s in sorted(uneven)) + " -- left out, the run split there")
    runs: list[set[int]] = []
    ids: set[int] = set()
    end, cut = None, []
    for s in sorted(lengths):
        if s in drop or s in uneven:
            if ids:
                runs.append(ids)
            ids, end = set(), None
            continue
        if ids and abs(s - end) > 2.0 / rate:
            runs.append(ids)
            ids = set()
            if s > end:
                cut.append(s)
        ids.add(s)
        end = s + next(iter(lengths[s])) / rate
    if ids:
        runs.append(ids)
    if cut:
        logger.info(f"{len(cut)} EDL run split(s) where a file ends before the next stamp")
    return runs


B423_HEADER_BYTES = 1024
B423_MIN_FILL = 0.01   # a site whose files hold under 1 % of their nominal length was written with no card space
B423_MIN_FILES_FOR_FILL = 10


def readable_b423(files: list[Path]) -> tuple[list[Path], list[str]]:
    """Split B423 files into the readable ones and reasons for the rest.

    A logger that loses its card mid-record writes a file of the right
    length whose 1024-byte header block is all zero, and one whose card is
    already full writes files of a few seconds. Neither can be used, and
    one such file must not abort the site: it is left out here, with a
    reason, and the run splits at the gap it leaves.

    Args:
        files (list[Path]): The site's B423 files in name order.

    Returns:
        tuple[list[Path], list[str]]: The files to read, and one line per
        file left out naming it and the reason.

    Raises:
        ValueError: If, over ten or more files, the median file holds under
            one percent of the interval between file names (at the nominal
            1000 records a second), which means the logger had no card
            space and there is no recording to ingest.
    """
    from mt_io.lemi.lemi423 import Read_Lemi_Data, Read_Lemi_Header

    record = int(Read_Lemi_Data.binary_format.itemsize)
    keep, skipped = [], []
    for f in files:
        size = f.stat().st_size
        if size < B423_HEADER_BYTES + record:
            skipped.append(f"{f.name}: {size} bytes, no data")
            continue
        try:
            Read_Lemi_Header(f).read()
        except (ValueError, IndexError) as exc:
            skipped.append(f"{f.name}: header unreadable ({str(exc).split(': ', 1)[-1]})")
            continue
        keep.append(f)
    if len(keep) >= B423_MIN_FILES_FOR_FILL:
        epochs = sorted(int(f.stem) for f in keep if f.stem.isdigit())
        spacing = sorted(b - a for a, b in zip(epochs, epochs[1:]))
        if spacing:
            nominal = spacing[len(spacing) // 2]
            seconds = sorted((f.stat().st_size - B423_HEADER_BYTES) / record / 1000.0 for f in keep)
            fill = seconds[len(seconds) // 2] / nominal if nominal > 0 else 1.0
            if fill < B423_MIN_FILL:
                raise ValueError(
                    f"the B423 files are nearly empty (a median of {seconds[len(seconds) // 2]:.0f} s of data "
                    f"per file, {nominal} s apart, over {len(keep)} files): the logger had no card space; "
                    f"there is no recording to ingest"
                )
    return keep, skipped


def _group_contiguous(files: list[Path], max_run_files: int | None = None,
                      instrument: str = "lemi423", rate: float | None = None) -> list[list[Path]]:
    """Group data files into contiguous runs using the starts their names carry.

    Files are nominally back to back (epoch spacing equal to the file
    length, typically 5400 s for a B423, a day for a LEMI-424, an hour for
    an EDL); any other spacing is a gap, for example the short first file
    after deployment, and starts a new run. Aurora computes STFTs per run,
    so the longest estimable period is set by run length rather than total
    recording. For LEMI-424 and EDL the B423 rule is applied to the distinct
    starts, and a group carries every file of its starts (an EDL stamp's
    channels). An EDL stamp without exactly one file per channel is left
    out, ending the run there (`_incomplete_stamps`). Given the EDL `rate`,
    runs follow the files' sample counts instead of the spacing
    (`_edl_runs_by_samples`).

    Args:
        files (list of Path): Data files in start order.
        max_run_files (int, optional): Most files per LEMI-423 run.
        instrument (str): Key of `INSTRUMENTS`.
        rate (float, optional): EDL sample rate in Hz.

    Returns:
        list of list of Path: The runs.
    """
    if instrument != "lemi423":
        stamps = [file_start(f, instrument) for f in files]
        drop = _incomplete_stamps(files, stamps) if instrument == "edl" else set()
        if instrument == "edl" and rate:
            runs = _edl_runs_by_samples(files, stamps, drop, float(rate))
            return [[f for f, s in zip(files, stamps) if s in ids] for ids in runs]
        runs: list[set[int]] = []
        # apply the spacing rule to the distinct stamps, then cut each run at
        # the stamps left out
        for run in _group_contiguous([Path(f"{s}.B423") for s in sorted(set(stamps))], max_run_files):
            ids: set[int] = set()
            for stamp in (int(p.stem) for p in run):
                if stamp not in drop:
                    ids.add(stamp)
                elif ids:
                    runs.append(ids)
                    ids = set()
            if ids:
                runs.append(ids)
        return [[f for f, s in zip(files, stamps) if s in ids] for ids in runs]
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
    ignore_filters: bool = False,
) -> Path:
    """Read a site's data files and write its raw MTH5 archive.

    Contiguous files (exact epoch spacing) are merged into long runs so
    aurora can use long STFT windows; a spacing anomaly starts a new run,
    which keeps sample timing correct across gaps.

    The instrument is `survey.instrument_of(site_name)`. LEMI-423 files are
    read with `read_lemi423`. LEMI-424 and EDL sites are read with their
    mt-io readers (`mtproc.instruments.read_run`), keeping the reader's
    channel names, with the declared `channels:` applied in the same way.
    `h_scale` and the reversed-dipole flip apply to LEMI-423 sites, as does
    `calibration_fn`, which is also used by an EDL site whose `sensor_type`
    is lemi120. `max_run_files` caps LEMI-423 runs only: 90 days of EDL at
    10 Hz (78 M samples per channel) is less than one 51 h LEMI-423 run. An
    EDL site's declared `electric_gain` becomes a filter on the ex and ey
    chains (`read_run`; the samples stay the stored words), and the run
    comment gets a line such as "electric gain 10 on ['ex', 'ey'] (declared
    from the field notes)". The key is checked before an existing archive is
    deleted (`_electric_gain`).

    The archive holds calibration only: the coil response, `h_scale`, the
    reversed-dipole flip and the declared electric gain. The declared list
    of `<survey>/filters.yaml`, `replace` included, is applied on demand by
    `build_variant`.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.
        out_path (Path, optional): Output file; default
            `default_archive_path`.
        overwrite (bool): Replace an existing file. When False, an existing
            file is returned as it is.
        max_run_files (int, optional): Most files per LEMI-423 run.
        ignore_filters (bool): Accepted for compatibility with older callers
            and ignored.

    Returns:
        Path: The archive path.

    Raises:
        FileNotFoundError: If the coil calibration file is missing or the
            site has no data files.
        ValueError: If a setting does not fit the instrument (see
            `_electric_gain`, `_keep_channels`, `_standardise_e_orientation`)
            or no file overlaps the window.
    """
    site = survey.site(site_name)
    site_dir = survey.site_dirs()[site_name]
    instrument = survey.instrument_of(site_name)
    electric_gain = _electric_gain(survey, site, instrument, site_dir)
    files = select_files(site_dir, start, end, instrument)
    skipped: list[str] = []
    if instrument == "lemi423":
        try:
            files, skipped = readable_b423(files)
        except ValueError as exc:
            raise ValueError(f"{site_name}: {exc}") from None
        for line in skipped:
            logger.warning(f"{site_name}: skipping {line}")
        if not files:
            raise ValueError(f"{site_name}: none of the {len(skipped)} B423 files can be read: "
                             + "; ".join(skipped))

    out_path = Path(out_path) if out_path else default_archive_path(survey, site_name)
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
    coil = None  # an EDL site's LEMI-120 response file, for read_run
    if instrument != "lemi423":
        max_run_files = None  # caps LEMI-423 runs only (see the docstring)
    needs_coil = instrument == "lemi423" or (instrument == "edl" and edl_sensor(site) == "lemi120")
    if needs_coil and site.calibration_fn:
        cal = Path(site.calibration_fn)
        if not cal.is_absolute():
            # relative paths resolve against the survey folder first (sensor
            # files kept with the config), then the raw-data root (sensor files
            # kept with the data)
            cal = next(
                (c for c in (survey.config_dir / cal, survey.data_root / cal) if c.exists()),
                survey.data_root / cal,
            )
        if not cal.exists():
            raise FileNotFoundError(f"coil calibration file not found: {cal}")
        if instrument == "lemi423":
            read_kwargs["calibration_fn"] = cal
        else:
            coil = cal
    elif instrument == "lemi423":
        logger.warning(
            f"{site_name}: no calibration_fn — magnetic channels will lack a "
            f"coil response and TFs will be wrong"
        )

    groups = _group_contiguous(files, max_run_files, instrument,
                               rate=edl_sample_rate(site_dir) if instrument == "edl" else None)
    logger.info(
        f"{site_name}: ingesting {len(files)} {INSTRUMENTS[instrument]['label']} files as "
        f"{len(groups)} run(s) -> {out_path}"
    )
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = None
        for i, group in enumerate(groups, 1):
            if instrument == "lemi423":
                run = read_lemi423(group if len(group) > 1 else group[0], **read_kwargs)
            else:
                run = read_run(instrument, group, site, site_dir, calibration=coil)
            _keep_channels(run, site)
            if skipped and i == 1:
                prior = run.run_metadata.comments.value
                note = "skipped unreadable file(s): " + "; ".join(skipped)
                run.run_metadata.comments.value = f"{prior}; {note}" if prior else note
            carried = [c for c in ("ex", "ey") if electric_gain != 1.0 and c in run.dataset]
            if carried:  # the filter is in their chains (read_run); the comment records it in text
                note = f"electric gain {electric_gain:g} on {carried} (declared from the field notes)"
                prior = run.run_metadata.comments.value
                run.run_metadata.comments.value = f"{prior}; {note}" if prior else note
            if instrument == "lemi423":
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
