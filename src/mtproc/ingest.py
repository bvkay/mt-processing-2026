"""Raw time series -> one MTH5 archive per site, plus filtered variants of it.

`ingest_site` writes exactly one archive per site, `<workspace>/mth5/<site>.h5`
(`default_archive_path`), and it is always the raw recording: no
`filters.yaml` entry is ever applied here, not even `replace` -- calibration
only (the coil response, `h_scale`, the reversed-dipole flip; LEMI-424 and
Earth Data PR6-24 sites go through their own mt-io readers,
`mtproc.instruments.read_run`, with the reader's channel names and filter
chain). The site's instrument is `Survey.instrument_of(site)`.

LEMI-423 files are read by the mt-io fork's `read_lemi423` as it stands: it
parses the four-digit altitude line of firmware 2.1 (``%Alt1060.0,m``) and,
given a `calibration_fn`, builds each magnetic channel's chain physical to
recorded, [LEMI-120 coil table nT -> nT (normalized), linear nT -> counts],
with units mt_metadata accepts (docs/upstream_issues.md 1, 2 and 6).
Nothing of mt-io is patched here; `_apply_h_scale` only appends one stage.

A site's declared filters (`<survey>/filters.yaml`) are applied on top of the
raw archive, on demand, into a **variant**: `<site>_f<hash>.h5`
(`variant_path`, `hash` = `filters_hash` of the declared list), built by
`build_variant` from the raw archive's own runs -- `replace` entries read the
donor's *raw* archive, never B423 files -- and never overwrites it. Whatever
wants the site "as processing should see it" asks `processing_archive`,
which builds the variant if it is missing or stale (a `filters.yaml` edit
changes the hash) and returns the raw path outright for a site with no
declared filters. An archive from before this split, whose run comments
record filters baked into `<site>.h5` itself, is the one thing
`processing_archive` refuses to touch (`archive_filter_kinds`) -- it must be
rebuilt raw first.
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
    """Where `ingest_site` writes a site's RAW archive: ``<workspace>/mth5/<site>.h5``.

    `ignore_filters` is accepted and ignored, kept only so old call sites
    keep working: there is no more separate ``<site>_unfiltered.h5`` -- raw
    IS the unfiltered archive now (the module docstring). A run that wants
    the site's declared filters applied asks `processing_archive`, not this.
    """
    return survey.workspace / "mth5" / f"{site_name}.h5"


# the prefix a run comment carries its filter provenance with -- an old-layout
# `ingest_site` build (`_filter_lines`/`archive_filter_kinds`) or a
# `build_variant` one (`_VARIANT_PREFIX`, below); everything after either is
# one provenance line per filter, joined "; then "
_FILTERS_PREFIX = "ingest filters (in order): "
# `build_variant`'s own prefix: the hash, then `_FILTERS_PREFIX` and the same
# provenance lines an old-layout archive would have carried
_VARIANT_HASH_PREFIX = "filters hash "


def _run_comment(run_group) -> str:
    comment = run_group.metadata.comments
    return "" if comment is None else str(getattr(comment, "value", comment) or "")


def _all_real_run_comments(path: Path) -> list[str] | None:
    """Every real run's comment in `path`'s one station (`_real_runs`, which
    drops mth5/aurora's auxiliary station-level groups), earliest first.

    None when `path` does not exist, or names a ``.part`` temp file
    (`build_variant` never leaves a finished archive under that name -- only
    `os.replace` moves one onto the final name, after every run is written
    and both files are closed). [] when the archive exists but has no real
    run.
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
    """The earliest real run's comment (`_all_real_run_comments`); "" for an
    archive with no real run, None for one that does not exist (or is a
    `.part` temp file). `archive_filter_kinds` uses this -- one `ingest_site`/
    `build_variant` call applies the same filters to every run of a site, so
    the earliest stands for the whole archive there. `variant_ready` checks
    every run instead of trusting that: see its own docstring for why.
    """
    comments = _all_real_run_comments(path)
    return None if comments is None else (comments[0] if comments else "")


def _filter_lines(comment: str) -> list[tuple[str, str]]:
    """[(kind, provenance line), ...] out of a run `comment` that starts with
    `_FILTERS_PREFIX` (after `_VARIANT_HASH_PREFIX` too, when there is one);
    [] when it does not. The declared electric-gain note, when `ingest_site`
    appended one, rides "; " (not "; then ") after the last filter's line and
    is stripped off that line before it is returned.
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
    """The filter kinds recorded in `path`'s run comments, in order.

    None when the archive does not exist. [] for a raw archive (nothing
    recorded -- every archive `ingest_site` writes now) or one with no real
    run. A non-empty result on `default_archive_path`'s own path is an
    "old-layout" archive, from before filters and raw recordings were split:
    `processing_archive` refuses to build a variant from, or process, one of
    those. See `_filter_lines` for exactly how the comment is read.
    """
    comment = _earliest_real_run_comment(path)
    return None if comment is None else [kind for kind, _line in _filter_lines(comment)]


def filters_hash(filters: list[dict] | None) -> str:
    """The first 8 hex characters of the sha1 of `filters` (`json.dumps(..., sort_keys=True)`):
    `variant_path`'s ``_f<hash>`` suffix and the hash `build_variant` records
    in its run comments. Order-sensitive (two lists of the same entries in a
    different order hash differently -- order changes what is applied).
    """
    text = json.dumps(list(filters or []), sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def variant_path(survey: Survey, site_name: str) -> Path:
    """``<workspace>/mth5/<site>_f<hash>.h5``, hash = `filters_hash` of the site's
    currently declared filters. Meaningful only when the site declares some
    (an empty list hashes to something too, but callers -- `processing_archive`,
    `variant_ready` -- treat "no declared filters" as "no variant, use the raw
    archive" before ever asking for this path)."""
    h = filters_hash(survey.site(site_name).filters)
    return survey.workspace / "mth5" / f"{site_name}_f{h}.h5"


def variant_ready(survey: Survey, site_name: str) -> bool:
    """True when `variant_path` names a finished file (never a ``.part`` one
    `build_variant` is still writing -- `_all_real_run_comments` returns None
    for that), *every* one of its real runs' comment carries a recorded
    hash, and every one of those hashes equals `filters_hash` of the site's
    current declaration.

    Checking every run rather than trusting the file's name (or just its
    earliest run) is the guard against a variant that stopped part-way
    through: `build_variant` now only `os.replace`s its ``.part`` file onto
    the variant's real name after the last run is written and both files are
    closed, so a crash should never leave a partial file under that name --
    but a hard kill mid-`os.replace`, or a file dropped in or edited by hand,
    is exactly what this catches instead of silently trusting.
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
    """`comp`'s raw counts for `n` samples at `fs` Hz from `donor_site`'s RAW
    archive, starting at `t0` (a pandas Timestamp) -- the array `build_variant`
    hands `apply_filters_arrays` as `donors[donor_site][comp]` for a `replace`
    entry. Raises when the donor has no raw archive, no run covering the span,
    a different sample rate, a run that does not start on the target's exact
    sample grid (GPS timing assumption, as `mtproc.virtual` asserts it), or a
    run too short for `n` samples from there.
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
    """Build (or replace) `site_name`'s filtered variant from its raw archive.

    Reads the raw archive (`default_archive_path`; raises if it is missing,
    or if `archive_filter_kinds` finds it is an old-layout archive with
    filters already baked in -- rebuild it raw first, `scripts/ingest_site.py
    <survey.yaml> <site> --raw`) run by run (`_real_runs`), applies the
    site's declared `filters.yaml` list to that run's channel arrays
    (`mtproc.noise.apply_filters_arrays`, `workers` threads per filter),
    `replace` entries reading the donor's own RAW archive over the run's span
    (`_donor_channel`) -- never B423 files, so a `replace` donor need not be
    LEMI-423 any more -- and writes the result to `variant_path`: the same
    runs, the raw station's own metadata, and each run's provenance lines
    (as an old-layout `ingest_site` build would have written them) behind a
    leading ``filters hash <hash>; `` (`variant_ready` reads it back). One
    run's channel arrays are held at a time, never the whole site.

    Raises `ValueError` when the site declares no filters (there is nothing
    to build -- the raw archive already is the processing archive). After a
    successful write, every *other* ``<site>_f*.h5`` is deleted, so exactly
    one variant exists per site at a time.
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
    # built under a .part name and moved onto out_path only once every run is
    # written and both files are closed (os.replace, below): a crash midway
    # leaves only the .part file, which variant_ready never mistakes for a
    # finished variant, instead of a truncated file under the real name
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

    # the one moment the variant's real name starts to exist: every run is
    # written and both files are closed, so a reader (variant_ready) never
    # sees a partial file under it -- os.replace is an atomic rename on the
    # same filesystem (POSIX and Windows both), overwriting out_path if a
    # stale one of the same hash is somehow already there
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
    """The archive a processing run should read for `site_name`.

    The raw archive (`default_archive_path`) when `use_filters` is False, or
    the site declares no filters; otherwise its filtered variant
    (`variant_path`), built first (`build_variant`) when it is missing or its
    recorded hash does not match the current declaration (`variant_ready`).

    Raises when the raw archive itself does not exist -- this never ingests,
    only builds a variant on top of an existing raw archive -- or when it is
    an old-layout archive with filters baked in (`archive_filter_kinds`):
    rebuild it raw first, `scripts/ingest_site.py <survey.yaml> <site> --raw`.
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

    File names carry each file's start in UTC (B423: the unix epoch;
    `mtproc.instruments.file_start` for the others); a file's span is taken as
    running to the next file's start (median spacing for the last). An EDL
    stamp names five channel files, all kept or dropped together.
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
    """`select_files` for a LEMI-424 or EDL site: the same rule on each distinct file start."""
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

    Field crews sometimes lay dipoles at 180/270 deg; the data are the negative
    of the standard 0/90 frame. Flipping at ingest keeps everything downstream
    in one convention. Arbitrary azimuths are not handled (none occur in the
    surveys processed here).
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
    # appended after the linear stage (nT -> counts), so it maps counts to
    # counts: the chain's units stay consistent (docs/upstream_issues.md 2)
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


def _electric_gain(survey: Survey, site: SiteConfig, instrument: str, site_dir: Path) -> float:
    """The gain `read_run` folds into ex and ey's chain, checked once per site before anything is written.

    EDL: `SiteConfig.electric_gain` (`edl_electric_gain`; default 1.0, no
    filter). recorder.ini's own `channel_n_high_gain` flags
    (`recorder_ini_high_gain`) are read only to warn, informationally, when it
    flags a channel and a gain is declared -- they never set the value: this
    is the electric chain's gain, declared from the field notes, not the
    PR6-24's own setting.
    Another instrument: an `electric_gain:` in the site's own entry raises --
    it is an EDL electric-chain setting -- and a `defaults:` value is not
    applied to it.
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
    """Drop channels not listed in `site.channels` (e.g. the unconnected hz).

    The reader always returns all five B423 columns; the survey says which
    ones had a sensor attached. Dropping here keeps the MTH5 honest and stops
    aurora from producing a tipper out of an open input.
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
    """The EDL file stamps without exactly one file for every channel the site's stamps have.

    mt-io's reader (`mt_io.uoa.pr624.UoAReader.read`) joins each channel's
    files end to end and trims every channel to the shortest, so a stamp
    missing one channel's file shifts that channel's later samples early by
    the file's length, to the end of the run: Hillside hs058 has no EX file
    at 2012-03-27 15:35, and its archived ex then held the file stamped five
    minutes later at every time to 23:30 (hx, hy, ey right). A stamp with two
    files for a channel (hs061: a test recording under old/ with the stamps
    of the real files) puts both in and dates every later sample late. Such
    a stamp is left out, every channel of it, and the run ends there as at a gap.
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
    """EDL runs by sample count, mt-io's own contiguity rule (`UoACollection._run_boundaries`).

    Every file's samples are counted (`mt_io.uoa.pr624.count_samples`: a
    newline count, a few seconds a site once the files are cached, and the
    reader reads them next anyway). A stamp joins the run when it starts where
    the previous stamp's files end, to two samples; so a file shorter than the
    time to the next stamp ends its run. The stamp spacing alone missed those:
    Hillside's startup files of 15 s each, stamped 300 s apart (hs058 02:00 to
    02:15, hs053, hs054, hs075, hs076, ...), were read as one stretch and every
    later sample of the run dated early (mt-io's reader warns "1140.0 s
    missing between files"). A stamp whose channel files differ in length is
    left out, as a missing one is.
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


def _group_contiguous(files: list[Path], max_run_files: int | None = None,
                      instrument: str = "lemi423", rate: float | None = None) -> list[list[Path]]:
    """Group data files into contiguous runs using the starts their names carry.

    Files are nominally back-to-back (epoch spacing == file length, typically
    5400 s for a B423, a day for a LEMI-424, an hour for an EDL); any other
    spacing means a real gap (e.g. the short first file after deployment) and
    starts a new run. Long runs matter: aurora STFTs each run independently,
    so the longest estimable period is set by run length, not total
    recording. For LEMI-424 and EDL the B423 rule runs on the distinct starts
    and a group carries every file of its starts (an EDL stamp's channels);
    an EDL stamp without exactly one file per channel is left out, which ends
    the run there (`_incomplete_stamps`). With the EDL `rate`, the runs follow
    the files' sample counts instead of the spacing (`_edl_runs_by_samples`).
    """
    if instrument != "lemi423":
        stamps = [file_start(f, instrument) for f in files]
        drop = _incomplete_stamps(files, stamps) if instrument == "edl" else set()
        if instrument == "edl" and rate:
            runs = _edl_runs_by_samples(files, stamps, drop, float(rate))
            return [[f for f, s in zip(files, stamps) if s in ids] for ids in runs]
        runs: list[set[int]] = []
        # the spacing rule on every stamp (the nominal spacing is theirs), then
        # each run cut at the stamps left out
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
    """Read a site's data files and write its RAW MTH5 (`default_archive_path`).

    Contiguous files (exact epoch spacing) are merged into long runs so aurora
    can use long STFT windows; any spacing anomaly starts a new run, so gaps
    never corrupt sample timing.

    The instrument is `survey.instrument_of(site_name)`. LEMI-423 is read with
    `read_lemi423` exactly as before. LEMI-424 and EDL sites are read with
    their mt-io readers (`mtproc.instruments.read_run`): the reader's channel
    names, the declared `channels:` applied the same way; `h_scale` and the
    reversed-dipole flip are LEMI-423 keys, `calibration_fn` too except on an
    EDL site whose `sensor_type` is lemi120 (its coils), and `max_run_files`
    caps LEMI-423 runs only -- 90 days of EDL at 10 Hz (78 M samples a
    channel) is less than one 51 h LEMI-423 run. An EDL site's declared
    `electric_gain` gets a filter on ex and ey's chain (`read_run`; the
    samples stay the stored words) and the run comment the line "electric
    gain 10 on ['ex', 'ey'] (declared from the field notes)"; the key is
    checked before an existing archive is deleted (`_electric_gain`).

    `<survey>/filters.yaml`'s declared list, `replace` included, is never
    applied here -- calibration only (the coil response, `h_scale`, the
    reversed-dipole flip, the declared electric gain). A site's filters are
    applied on top of this archive, on demand, by `build_variant`;
    `ignore_filters` is accepted and ignored, kept only so old call sites
    keep working.
    """
    site = survey.site(site_name)
    site_dir = survey.site_dirs()[site_name]
    instrument = survey.instrument_of(site_name)
    electric_gain = _electric_gain(survey, site, instrument, site_dir)
    files = select_files(site_dir, start, end, instrument)

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
        max_run_files = None  # see the docstring
    needs_coil = instrument == "lemi423" or (instrument == "edl" and edl_sensor(site) == "lemi120")
    if needs_coil and site.calibration_fn:
        cal = Path(site.calibration_fn)
        if not cal.is_absolute():
            # relative paths: the survey folder first (sensor files kept with
            # the config, as for Burra), then the raw-data root (Curnamona).
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
            carried = [c for c in ("ex", "ey") if electric_gain != 1.0 and c in run.dataset]
            if carried:  # the filter is in their chains (read_run); this is the line a person reads
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
