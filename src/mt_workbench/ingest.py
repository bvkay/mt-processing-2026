# -*- coding: utf-8 -*-
"""
Raw time series to one MTH5 archive per site, plus filtered variants

`ingest_site` writes one archive per site, `<workspace>/mth5/<site>.h5`
(`default_archive_path`), holding the raw recording with calibration only:
the coil response, `h_scale`, for a site declared `swap_e` the exchange
of ex and ey (`_swap_e`), the reversed-dipole flip, for a site declared
`swap_h` the exchange of hx and hy (`_swap_h`), for a site declared
`flip_h` the sign flip of the named coils (`_flip_h`) and then, for a
fluxgate site declared `rot_h`, the turn of hx and hy onto magnetic north
(`_rot_h`, read back by `archive_rot_h`). A
site that declares `clock_offset_s` has that many seconds added to every
run's time stamps, its samples untouched, and the shift recorded in the
run and channel comments and the station's ``provenance.comments``
(`_shift_clock`, read back by `archive_clock_offset`). A site whose
survey.yaml declares instrument registry DOIs (`logger_pid`, ...) gets them
in one piece of every run comment and of the station's
``provenance.comments``, "instrument_registry: logger <doi>, ..."
(`mt_workbench.survey.Survey.registry_note`); the run's `data_logger.id`
keeps the serial the reader gives. A LEMI-423 site
that recorded electrics only and declares `h_from: <neighbour>` gets the
neighbour's hx and hy, read from the neighbour's raw files with its
calibration, `swap_h`, `flip_h` and clock offset and taken at the local's
GPS time stamps (`_h_from_plan`, `_borrow_h`, read back by
`archive_h_from`); two EDL sites likewise (`_h_from_plan_edl`,
`_read_borrowed_edl`), and two Orange Box sites, whose runs lie on one
UTC 10 Hz grid, by grid alignment, the local's own hx and hy replaced and
its hz kept (`_h_from_plan_orangebox`, `_read_borrowed_orangebox`,
`_drop_own_h`). Entries of
`filters.yaml`, including `replace`, are applied in the variants described
below. LEMI-424 and Earth Data PR6-24 sites are read by their mt-io readers
(`mt_workbench.instruments.read_run`) with the reader's channel names and filter
chain. Phoenix MTU-5C and MTU-8A sites are read through mt-io's Phoenix
readers by `mt_workbench.phoenix`: one run per recording of continuous files,
split where a file does not start at the end of the one before, channels
renamed ex ey hx hy hz, a chain from the field to the recorded volts, and
the second by which file-version-2 stamps trail GPS added
(`_phoenix_units`). A Phoenix site's 24 kHz bursts are ingested as a site
of their own (`bursts_of:`), one run per burst (`_ingest_bursts`). Phoenix
MTU-5A sites are read by `mt_workbench.mtu5a`: the 150 Hz `.TS4` of each
recording in the site folder, one run per recording (more where its record
tags step by other than 1 s), stored as counts with the table's scalar
chain as filters, the tags' saturation and status written beside the
archive (`<site>.mtu5a_flags.csv`). Orange
Box sites are read through mt-io's Orange Box reader by
`mt_workbench.orangebox`: runs split at stamp gaps, each run's samples timed
from its stamps on the logger clock's `clock_timezone`, the field drift
`clock_drift_s` spread over the deployment, and resampled onto the UTC
10 Hz grid, the time base recorded in each run comment
(`_orangebox_units`, `_read_orangebox_run`, read back by
`archive_time_base`). The site's instrument is `Survey.instrument_of(site)`.

LEMI-423 files are read by `read_lemi423` of the mt-io fork. It parses the
four-digit altitude line of firmware 2.1 (``%Alt1060.0,m``) and, given a
`calibration_fn`, builds each magnetic channel's chain from physical to
recorded, [LEMI-120 coil table nT -> nT (normalized), linear nT -> counts],
with units mt_metadata accepts (docs/upstream_issues.md 1, 2 and 6).
`_apply_h_scale` appends one stage to that chain.

The site's declared declination (`SiteConfig.declination`, its model and
epoch, from scripts/declination.py) is copied into the station metadata
(``location.declination``) on every reader path, and the station's
``orientation.reference_frame`` is set from the site's `layout_north`
(geomagnetic for "magnetic", the default; geographic for "geographic"),
so a LEMI-424 site carries it in place of its reader's geographic
default (`mt_workbench.products.apply_site_frame`). The declination is
stored and not applied: ``translated_azimuth`` stays unset and the channels
keep their azimuths. An archive built before the key existed carries 0.0, and
process_rr.py sets the survey.yaml frame and value on the TF at write time.

`ingest_site` also measures the raw DC level of each electric and magnetic
channel of each run it writes (`mt_workbench.dclevel`: the median, MAD and rail
share of a subsample of the samples in memory), classifies the site's
channel runs together ("open input?", "saturated?" or "ok") and appends the
medians, rail shares and verdicts to each run's comment
(`mt_workbench.dclevel.level_note`), where `mt_workbench.dclevel.recorded_levels` reads
them. A Phoenix run's rail share is measured against each channel's input
rail, 0.9 x the input range of its file header (`_phoenix_rails`), recorded
beside the levels; LEMI and EDL runs keep the record's own rail.

A site's declared filters (`<survey>/filters.yaml`) are applied to the raw
archive on demand, producing a variant `<site>_f<hash>.h5` (`variant_path`,
with `hash` the `filters_hash` of the declared list). `build_variant` builds
it from the raw archive's runs, reading `replace` donors from their raw
archives, and leaves the raw archive unchanged. `processing_archive` returns
the archive processing should read: it builds the variant if it is missing
or stale and returns the raw path for a site with no declared filters. A
variant is stale when `filters.yaml` is edited (the hash changes), and when
the raw archive or a donor's has been rebuilt or the coil tables changed
since it was built: each variant run comment records the raw archive's
identity (`archive_identity`: stem, size, modification time and the sha256
of its first MiB), the coil-table hash the raw archive records and each
donor's identity (`_variant_record`), and `variant_ready` compares them
with the files as they are; a variant built before the record is judged
by file times (`_file_time_stale`). `ingest_site` records the sha256 of the coil
tables it read in each raw run comment (``calibration_sha256: <hex>``); a
raw archive whose recorded tables no longer hash as the declared ones do
is refused by `build_variant` and `processing_archive` until it is
re-ingested. An old-layout archive, whose run
comments record filters applied inside `<site>.h5`, is rejected by
`processing_archive` (`archive_filter_kinds`) and must be rebuilt raw.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
import mt_io.lemi.lemi423 as _lemi423
from mt_io.lemi.lemi423 import read_lemi423
from mth5.mth5 import MTH5

from . import mtu5a
from .dclevel import OK, RAIL_LEVEL, THRESHOLD_COUNTS, channel_stats, channel_type, classify, flag_line, level_note
from .instruments import (  # noqa: F401
    INSTRUMENTS, b423_files, channel_electric_gains, edl_electric_gain, edl_record_start, edl_sample_rate,
    edl_sensor, file_start, read_run, record_files, recorder_ini_high_gain,
)
from .noise import apply_filters_arrays
from .products import H_TILT_PREFIX, ROT_H_PARTS_PREFIX, ROT_H_PREFIX, apply_site_frame, parse_h_tilt, parse_rot_h_part
from .survey import SiteConfig, Survey, distance_km
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
# the pieces of a `build_variant` run comment between the hash and `_FILTERS_PREFIX`
# (`_variant_record`), and the coil-table piece of an `ingest_site` run comment
# (`_calibration_note`). Each is one "key: value" piece with a dot-free key, no ";"
# and no second ":", because mt_metadata's EMTF XML writer splits a run comment on
# ";" and sets every "key: value" piece as an attribute (docs/upstream_issues.md 48)
_SOURCE_PREFIX = "source: "
_CALIBRATION_PREFIX = "calibration_sha256: "
_DONOR_PREFIX = "donor: "
_RECORD_PREFIXES = (_SOURCE_PREFIX, _CALIBRATION_PREFIX, _DONOR_PREFIX)
# the calibration a variant records when its raw archive records none (built before the record)
_UNKNOWN = "unknown"
# bytes at the start of an archive hashed into its identity (`archive_identity`)
_HEAD_BYTES = 1 << 20


class ArchiveHeldOpen(PermissionError):
    """A finished build could not replace an archive that another program holds open.

    Raised by `build_variant` when Windows refuses `os.replace` onto a
    variant that the GUI, or any other process, has open. The new build has
    been deleted and the file on disk is the one that was there before.
    """


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
    the `_VARIANT_HASH_PREFIX` part and the freshness record that follows it
    (`_variant_record`). The electric-gain note that
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
        while comment.startswith(_RECORD_PREFIXES):
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


def archive_identity(path: Path) -> str:
    """Return the identity of an archive file as it is on disk now.

    The identity is ``<stem> size <bytes> mtime <time> sha256_head <hex>``:
    the file's stem, its size, its modification time in UTC (ISO 8601 basic
    format to the nanosecond, ``20261005T044812.520872600Z``, with no colon)
    and the sha256 of its first MiB followed by its size in decimal. A
    rewrite of the file changes the time, and the hash also catches a
    rewrite given an older time. `build_variant` records the raw archive's
    identity in the variant, and scripts/decimate_site.py the source
    archive's in a derived archive, as a ``source: `` piece (`source_note`).

    An archive opened for writing (mode "a", mth5's default) is rewritten
    on close even when no data change, and so is a copy that does not
    keep the modification time (shutil.copy; robocopy and Explorer keep
    it): either gets a new identity, which costs a rebuild of what was made
    from it, never a stale product. The readers of this package open
    archives read-only, as does aurora unless it saves Fourier coefficients.

    Args:
        path (Path): The archive.

    Returns:
        str: The identity.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read(_HEAD_BYTES))
    digest.update(str(stat.st_size).encode("ascii"))
    seconds, nanos = divmod(stat.st_mtime_ns, 1_000_000_000)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(seconds)) + f".{nanos:09d}Z"
    return f"{path.stem} size {stat.st_size} mtime {stamp} sha256_head {digest.hexdigest()}"


def source_note(path: Path) -> str:
    """Return the run comment piece ``source: <identity>`` of an archive (`archive_identity`)."""
    return f"{_SOURCE_PREFIX}{archive_identity(path)}"


def _comment_values(comment: str, prefix: str, stop: str | None = None) -> list[str]:
    """Return the values of the "; "-separated pieces of a comment that start with `prefix`.

    Args:
        comment (str): Run comment.
        prefix (str): The piece's key and ": ".
        stop (str, optional): A piece starting with this ends the search.

    Returns:
        list of str: The text after `prefix` of each such piece, in order.
    """
    out = []
    for piece in (comment or "").split("; "):
        if stop and piece.startswith(stop):
            break
        if piece.startswith(prefix):
            out.append(piece[len(prefix):].strip())
    return out


def recorded_source(comment: str, stop: str | None = None) -> str | None:
    """Return the archive identity a run comment records in its first ``source: `` piece.

    Args:
        comment (str): Run comment.
        stop (str, optional): A piece starting with this ends the search, so
            that the comment of a source run quoted after it (as
            scripts/decimate_site.py quotes one) is not read.

    Returns:
        str or None: The identity (`archive_identity`); None when the
        comment records none.
    """
    values = _comment_values(comment, _SOURCE_PREFIX, stop)
    return values[0] if values else None


def _donor_sites(filters: list[dict]) -> list[str]:
    """Return the donor sites of a filter list's `replace` entries, sorted."""
    return sorted({str(d) for spec in filters if "replace" in spec for d in (spec["replace"] or {}).values()})


def _declared_tables(survey: Survey, site_name: str) -> list[str]:
    """Return the coil tables a site declares: its `calibration_fn`, then its `h_from` neighbour's.

    A derived site (`Survey.parent_of`) declares its parent's. Whether the
    ingest reads a declared table depends on the recorder; `_calibration_stale`
    therefore compares only the tables an archive records it read.
    """
    parent = survey.parent_of(site_name)
    if parent:
        return _declared_tables(survey, parent)
    site = survey.site(site_name)
    names = [site.calibration_fn] if site.calibration_fn else []
    if site.h_from and survey.site(site.h_from).calibration_fn:
        names.append(survey.site(site.h_from).calibration_fn)
    return names


def _table_hashes(survey: Survey, names: list[str]) -> list[str] | None:
    """Return the sha256 hex digest of each named coil table, in order, without repeats.

    Returns:
        list of str or None: The digests; None when a table cannot be found
        (`_calibration_path`), for example on a drive that is not connected.
    """
    digests: list[str] = []
    for name in names:
        try:
            path = _calibration_path(survey, name)
        except FileNotFoundError:
            return None
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if digest not in digests:
            digests.append(digest)
    return digests


def _calibration_note(paths: list[Path]) -> str:
    """Return the run comment piece recording the coil tables an ingest read.

    The piece is ``calibration_sha256: <hex> [<hex>]``, the sha256 of each
    table read (the site's `calibration_fn`, then an `h_from` neighbour's,
    without repeats), or ``calibration_sha256: none`` when none was read.
    """
    digests: list[str] = []
    for path in paths:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if digest not in digests:
            digests.append(digest)
    return f"{_CALIBRATION_PREFIX}{' '.join(digests) or 'none'}"


def calibration_sha256(survey: Survey, site_name: str) -> str | None:
    """Return the sha256 of the coil tables a site declares now (`_declared_tables`).

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.

    Returns:
        str or None: The hex digests, space-separated, in the order of
        `_calibration_note`; "none" when the site declares no table; None
        when a declared table cannot be found.
    """
    digests = _table_hashes(survey, _declared_tables(survey, site_name))
    return None if digests is None else (" ".join(digests) or "none")


def _calibration_stale(survey: Survey, site_name: str, recorded: str | None) -> str | None:
    """Say why a recorded coil-table hash no longer matches the site's declared tables.

    `recorded` is the value of an archive's ``calibration_sha256`` piece:
    the tables its ingest read. It is stale when one of its digests is not
    the digest of a table the site declares now (the table was edited or
    replaced, or the declaration names another file). None is returned
    when the archive records no table read ("none"), records no piece or
    "unknown" (built before the record), or a declared table cannot be found.

    Returns:
        str or None: The reason; None when the tables match or cannot
        be judged.
    """
    if recorded in (None, "none", _UNKNOWN):
        return None
    now = _table_hashes(survey, _declared_tables(survey, site_name))
    if now is None:
        return None
    if all(digest in now for digest in recorded.split()):
        return None
    return (f"it records coil table sha256 {recorded}, and the table(s) {site_name} declares now hash to "
            f"{' '.join(now) or 'nothing (none declared)'}")


def _calibration_refusal(site_name: str, path: Path, why: str) -> str:
    """Return the message refusing an archive built with another coil table."""
    return (f"{site_name}: {path.name}: {why}; it was built with another coil table: re-ingest the raw "
            f"archive (`scripts/ingest_site.py <survey.yaml> <site> --raw --force`, for a derived site its "
            f"parent's, then `scripts/decimate_site.py`) before processing")


def _recorded_calibration(path: Path) -> str | None:
    """Return the ``calibration_sha256`` value of an archive's earliest real run comment, None without one."""
    values = _comment_values(_earliest_real_run_comment(path) or "", _CALIBRATION_PREFIX)
    return values[0] if values else None


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
    hash equal to `filters_hash` of the site's current declaration, and
    every run's freshness record (`_variant_record`) still holds
    (`_variant_stale`): the raw archive's identity (`archive_identity`) is
    the one recorded, so the raw archive has not been rebuilt since; each
    `replace` donor's raw archive is the one recorded; and the coil tables
    the raw archive records it was ingested with still hash as the site's
    declared tables do (`_calibration_stale`). A missing raw or donor
    archive is not judged, since processing stops on it. A variant without
    the record (built before it existed) is judged by file times: ready,
    with a warning, when it is newer than its raw archive and donors
    (`_file_time_stale`; a variant whose raw archive was rebuilt after it
    fails). A stale record is
    logged with the reason. Every run is checked, which detects a variant
    cut short by a process killed during `os.replace`, or a file copied in
    or edited by hand.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.

    Returns:
        bool: False also for a site with no declared filters.
    """
    site = survey.site(site_name)
    if not site.filters:
        return False
    path = variant_path(survey, site_name)
    comments = _all_real_run_comments(path)
    if not comments:
        return False
    want = filters_hash(site.filters)
    for comment in comments:
        if not comment.startswith(_VARIANT_HASH_PREFIX):
            return False
        if comment[len(_VARIANT_HASH_PREFIX):].split(";", 1)[0].strip() != want:
            return False
    why = _variant_stale(survey, site_name, comments, path)
    if why:
        logger.info(f"{site_name}: {path.name} is not current: {why}")
        return False
    return True


def _variant_record(survey: Survey, site_name: str, raw_path: Path, raw_calibration: str | None) -> list[str]:
    """Return the freshness record `build_variant` writes after the hash in every run comment.

    The pieces are ``source: <identity>`` of the raw archive
    (`source_note`), ``calibration_sha256: <hex>`` (the value the raw
    archive records, `_calibration_note`, or "unknown" when it records
    none), and ``donor: <identity>`` of each `replace` donor's raw archive,
    in donor order (`_donor_sites`).

    Raises:
        FileNotFoundError: If a donor has no raw archive.
    """
    record = [source_note(raw_path), f"{_CALIBRATION_PREFIX}{raw_calibration or _UNKNOWN}"]
    for donor in _donor_sites(survey.site(site_name).filters or []):
        path = default_archive_path(survey, donor)
        if not path.exists():
            raise FileNotFoundError(f"{site_name}: replace donor {donor} has no raw archive at {path}; "
                                    f"ingest it first")
        record.append(f"{_DONOR_PREFIX}{archive_identity(path)}")
    return record


def _file_time_stale(path: Path, sources: list[Path]) -> str | None:
    """Judge an archive without a freshness record by file times.

    The rule for an archive built before the record existed: it is
    current when its modification time is later than that of every
    source that exists, and stale otherwise. It catches a raw archive
    rebuilt after its variant, and it spares every older archive a
    rebuild on first use.

    Args:
        path (Path): The archive without a record.
        sources (list of Path): The files it was made from; missing ones
            are not judged.

    Returns:
        str or None: The reason it is stale; None when it is newer than
        every source.
    """
    mine = path.stat().st_mtime_ns
    for source in sources:
        if source.exists() and source.stat().st_mtime_ns >= mine:
            return (f"it records no source archive, and {source.name} ({_iso(source.stat().st_mtime_ns)}) is "
                    f"not older than it ({_iso(mine)})")
    return None


def _variant_stale(survey: Survey, site_name: str, comments: list[str], path: Path) -> str | None:
    """Say why a variant's freshness record (`_variant_record`) no longer holds.

    A raw archive or donor archive that is missing is not judged:
    `processing_archive` and `build_variant` stop on it before a variant is
    read, and a variant kept on disk still holds what it was built from. A
    variant none of whose runs carries the record (built before it existed)
    is judged by file times instead (`_file_time_stale`): current, with a
    warning, when it is newer than the raw archive and every donor's; it
    carries the record once rebuilt. A variant that records it in some runs
    and not in others is stale.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        comments (list of str): The variant's real run comments.
        path (Path): The variant.

    Returns:
        str or None: The reason; None when every run records the raw
        archive and the donors as they are now and a coil-table hash that
        is not stale (`_calibration_stale`), or the grandfather rule holds.
    """
    raw = default_archive_path(survey, site_name)
    wanted = _donor_sites(survey.site(site_name).filters or [])
    recorded_runs = [bool(_comment_values(c, _SOURCE_PREFIX, stop=_FILTERS_PREFIX)
                          and _comment_values(c, _CALIBRATION_PREFIX, stop=_FILTERS_PREFIX)) for c in comments]
    if not any(recorded_runs):
        why = _file_time_stale(path, [raw] + [default_archive_path(survey, d) for d in wanted])
        if why is None:
            logger.warning(f"{site_name}: {path.name} records no source archive (built before archives recorded "
                           f"their sources): judged current by file time, newer than {raw.name} and its donors; it "
                           f"will carry the record when next rebuilt")
        return why
    if not all(recorded_runs):
        return "some of its runs record no source archive"
    source = archive_identity(raw) if raw.exists() else None
    donors = {d: archive_identity(default_archive_path(survey, d)) for d in wanted
              if default_archive_path(survey, d).exists()}
    for comment in comments:
        recorded = _comment_values(comment, _SOURCE_PREFIX, stop=_FILTERS_PREFIX)
        calibration = _comment_values(comment, _CALIBRATION_PREFIX, stop=_FILTERS_PREFIX)
        if source is not None and recorded[0] != source:
            return f"it was built from {recorded[0]}, and the raw archive is now {source}"
        recorded_donors = _comment_values(comment, _DONOR_PREFIX, stop=_FILTERS_PREFIX)
        names = [identity.split(" ", 1)[0] for identity in recorded_donors]
        if names != wanted:
            return f"it records the donors {names}, and the filters name {wanted}"
        for name, identity in zip(names, recorded_donors):
            if name in donors and donors[name] != identity:
                return f"it was built with the donor {identity}, and {name}'s raw archive is now {donors[name]}"
        why = _calibration_stale(survey, site_name, calibration[0])
        if why:
            return why
    return None


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
            (the GPS timing assumption, as in `mt_workbench.virtual`), or the run
            is too short.
    """
    path = default_archive_path(survey, donor_site)
    if not path.exists():
        raise FileNotFoundError(f"{tag}: replace donor {donor_site} has no raw archive at {path}; ingest it first")
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
                f"target's grid; GPS timing assumption violated, investigate before building the variant"
            )
        data = np.asarray(ch.hdf5_dataset[i0:i0 + n])
        if data.shape[0] != n:
            raise ValueError(f"{tag}: replace donor {donor_site} {comp}'s run is short by {n - data.shape[0]} "
                             f"sample(s) for this window")
        return data
    finally:
        m.close_mth5()


def build_variant(survey: Survey, site_name: str, workers: int = 4, chunk_workers: int | None = None) -> Path:
    """Build or replace a site's filtered variant from its raw archive.

    The raw archive (`default_archive_path`) is read run by run
    (`_real_runs`). The site's declared `filters.yaml` list is applied to
    each run's channel arrays (`mt_workbench.noise.apply_filters_arrays`, with
    `workers` threads per filter, and the `mains` kind cut into time chunks
    over `chunk_workers` threads); `replace` entries read the donor's raw
    archive over the run's span (`_donor_channel`), so a donor may be any
    instrument. The result is written to `variant_path` with the same runs,
    the raw station's metadata, and each run's provenance lines behind a
    leading ``filters hash <hash>; `` and the freshness record
    (`_variant_record`: the raw archive's identity, taken before it is
    read, the coil-table hash the raw archive records, and each donor's
    identity), which `variant_ready` reads back. One
    run's channel arrays are held in memory at a time. The file is written
    under a ``.part`` name and moved into place when complete; when the
    variant it replaces is open in another program (Windows refuses the
    move), the ``.part`` file is deleted and `ArchiveHeldOpen` is raised.
    After a successful write every other ``<site>_f*.h5`` is deleted,
    leaving one variant per site.

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        workers (int): Threads per filter.
        chunk_workers (int, optional): Threads for the time chunks of
            `mains`; the machine's cores (`os.cpu_count`) when None.

    Returns:
        Path: The variant path.

    Raises:
        ValueError: If the site declares no filters (the raw archive is then
            the processing archive), the raw archive is an old-layout
            archive with filters applied (rebuild it with
            ``scripts/ingest_site.py <survey.yaml> <site> --raw``), or it
            has no real run, or it records coil tables that no longer hash
            as the site's declared tables do (`_calibration_stale`: re-ingest
            it with ``--raw --force``).
        FileNotFoundError: If the raw archive or a donor's is missing.
        ArchiveHeldOpen: If the existing variant of the same hash is open
            in another program; the new build is deleted.
    """
    site = survey.site(site_name)
    filters = site.filters or []
    if not filters:
        raise ValueError(f"{site_name}: no declared filters; there is no variant to build")
    raw_path = default_archive_path(survey, site_name)
    if not raw_path.exists():
        raise FileNotFoundError(f"{site_name}: no raw archive at {raw_path}; ingest it first")
    baked = archive_filter_kinds(raw_path)
    if baked:
        raise ValueError(
            f"{site_name}: {raw_path.name} was built with filters baked in (old layout: {baked}); rebuild it "
            f"raw first: `scripts/ingest_site.py <survey.yaml> {site_name} --raw`"
        )
    raw_calibration = _recorded_calibration(raw_path)
    why = _calibration_stale(survey, site_name, raw_calibration)
    if why:
        raise ValueError(_calibration_refusal(site_name, raw_path, why))
    if raw_calibration is None:
        logger.info(f"{site_name}: {raw_path.name} records no coil-table hash (ingested before the record): "
                    f"the variant records it as {_UNKNOWN}")
    # taken before the raw archive is read: a rewrite during the build leaves a stale record
    record = "; ".join(_variant_record(survey, site_name, raw_path, raw_calibration))
    h = filters_hash(filters)
    out_path = survey.workspace / "mth5" / f"{site_name}_f{h}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # written under a .part name and moved onto out_path once every run is
    # written and both files are closed (os.replace, below); after a crash
    # midway only the .part file exists, which variant_ready does not accept
    tmp_path = out_path.with_name(out_path.name + ".part")
    if tmp_path.exists():
        tmp_path.unlink()

    if chunk_workers is None:
        chunk_workers = os.cpu_count() or 1
    started = time.perf_counter()
    m_in = MTH5()
    m_in.open_mth5(raw_path, mode="r")
    try:
        survey_name_in = m_in.surveys_group.groups_list[0]
        station_in = m_in.get_station(site_name, survey=survey_name_in)
        runs = _real_runs(station_in)
        if not runs:
            raise ValueError(f"{site_name}: {raw_path.name} has no real run to filter")
        donor_sites = _donor_sites(filters)

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
                                                  donors=donors, workers=workers, chunk_workers=chunk_workers)
                for comp in comps:
                    if not np.may_share_memory(out[comp], arrays[comp]):
                        run.dataset[comp].data = out[comp]
                run.run_metadata.comments.value = (
                    f"{_VARIANT_HASH_PREFIX}{h}; {record}; {_FILTERS_PREFIX}" + "; then ".join(lines)
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
    # existing out_path of the same hash. Windows refuses it while another
    # process holds out_path open: the .part is then deleted, so no full-size
    # copy is left behind, and out_path keeps the previous build
    try:
        os.replace(tmp_path, out_path)
    except PermissionError as exc:
        tmp_path.unlink(missing_ok=True)
        if not out_path.exists():
            raise
        raise ArchiveHeldOpen(
            f"{site_name}: {out_path} is open in another program (the GUI?): close it and re-run; "
            f"the new build was deleted and the existing {out_path.name} is unchanged"
        ) from exc
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
    missing or not current (`variant_ready`: its recorded hash differs from
    the current declaration, or the raw archive, a donor or the coil
    tables changed since it was built). The raw archive must already
    exist; ingest runs in `ingest_site`. A raw archive returned as it is
    must not record coil tables that no longer hash as the site's declared
    tables do (`_calibration_stale`), as `build_variant` requires of the
    raw archive it reads.

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
            ``scripts/ingest_site.py <survey.yaml> <site> --raw``. Also when
            it was ingested with coil tables that have changed since.
    """
    site = survey.site(site_name)
    raw = default_archive_path(survey, site_name)
    if not raw.exists():
        raise FileNotFoundError(
            f"{site_name}: no archive at {raw}; ingest it first (scripts/ingest_site.py, or the "
            f"Time Series tab's Build MTH5)"
        )
    baked = archive_filter_kinds(raw)
    if baked:
        raise ValueError(
            f"{site_name}: {raw.name} was built with filters baked in (old layout: {baked}); rebuild it "
            f"raw first: `scripts/ingest_site.py <survey.yaml> {site_name} --raw`"
        )
    if not use_filters or not site.filters:
        why = _calibration_stale(survey, site_name, _recorded_calibration(raw))
        if why:
            raise ValueError(_calibration_refusal(site_name, raw, why))
        return raw
    if not variant_ready(survey, site_name):
        return build_variant(survey, site_name)
    return variant_path(survey, site_name)


def select_files(site_dir: Path, start=None, end=None, instrument: str = "lemi423") -> list[Path]:
    """Return the site's data files overlapping [start, end).

    File names carry each file's start in UTC (the unix epoch for B423,
    `mt_workbench.instruments.file_start` for the others). A file's span runs to
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
    At a site whose pair `_rot_e` turns (`_rot_e_wanted`), a line off the
    cardinal axes follows the same reversed-pair rule mt-io's dipole filter
    applies on an EDL (`_e_direction`): negated when more than 90 deg off
    its nominal azimuth (ey at 315 measures along 135), left alone within
    90 deg (ex at 45); `_rot_e` then turns the pair.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Raises:
        ValueError: If an azimuth is neither standard nor reversed by 180
            deg, at a site `_rot_e` does not turn.
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
            if not _rot_e_wanted(site) or not site.flip_reversed_dipoles:
                raise ValueError(
                    f"{site.name} {comp}: azimuth {az} needs a real rotation; "
                    f"only reversed (180 deg) dipoles are handled at ingest"
                )
            # a line off the cardinal axes, turned later by `_rot_e`: the reversed-pair rule mt-io's
            # dipole filter applies on an EDL (`_e_direction`), so the channel measures along
            # `_e_direction(comp, az)`; a line within 90 deg of its nominal azimuth is left as it is
            if _e_direction(comp, az) == float(az) % 360.0:
                continue
            run.dataset[comp].data = -run.dataset[comp].data
            logger.info(f"{site.name} {comp}: azimuth {az} more than 90 deg off {standard} -> sign-flipped, "
                        f"measures along {_e_direction(comp, az):g} (turned by rot_e)")
            continue
        if not site.flip_reversed_dipoles:
            logger.info(
                f"{site.name} {comp}: azimuth {az} taken as layout direction only "
                f"(flip_reversed_dipoles=False), no sign flip"
            )
            continue
        # the reader writes the standard azimuth into the channel attrs, so
        # flipping the data completes the correction. run.dataset is modified
        # directly because run.<comp> accessors return copies.
        run.dataset[comp].data = -run.dataset[comp].data
        logger.info(f"{site.name} {comp}: azimuth {az} -> sign-flipped to {standard}")


# the LEMI-424 electric sign convention (`SiteConfig.e_sign`): the default sign, and the stage recorded in each
# electric channel's chain (`_apply_e_sign`)
LEMI424_E_SIGN = -1.0
LEMI424_E_SIGN_FILTER = "lemi424_e_sign"


def _apply_e_sign(run, site: SiteConfig, sign: float) -> str | None:
    """Record a LEMI-424 run's electric sign convention `e_sign` in each electric channel's chain.

    The LEMI-424 records E1 and E2 with the opposite sign to the x-north,
    y-east frame, so a LEMI-424 site's sign is -1.0 unless survey.yaml says
    otherwise (`_e_sign`). The samples stay as the logger wrote them; a
    CoefficientFilter `LEMI424_E_SIGN_FILTER` of that gain, mV/km in and
    out, is appended to the chain of every electric channel the run keeps
    (after `_keep_channels`), recorded as applied, as `_apply_h_scale`
    records `h_scale`. Calibration divides by the applied stages (aurora,
    `mt_workbench.crosspower`, `mt_workbench.timefreq`, scripts/psd_qc.py),
    so every consumer reads -E1 and -E2. `_standardise_e_orientation` runs
    after it and negates the samples of a line a crew laid reversed, so a
    declared reversal sits in the samples and the convention in the chain.
    A sign of 1.0 writes nothing.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.
        sign (float): 1.0 or -1.0.

    Returns:
        str or None: The run comment line, or None when nothing was recorded.
    """
    if sign == 1.0:
        return None
    done = [c for c in run.dataset.data_vars if run.dataset[c].attrs.get("type") == "electric"]
    if not done:
        return None
    coef = _lemi423.CoefficientFilter()
    coef.name = LEMI424_E_SIGN_FILTER
    coef.gain = float(sign)
    coef.units_in = "milliVolt per kilometer"
    coef.units_out = "milliVolt per kilometer"
    coef.comments = (f"LEMI-424 electric sign convention e_sign {sign:g}: the samples are the logger's columns, "
                     f"calibration divides by this stage")
    run.filters[coef.name] = coef
    for comp in done:
        # run.<comp> accessors return copies, so the attrs are modified directly
        chain = list(run.dataset[comp].attrs.get("filters") or [])
        chain.append({"applied_filter": {"applied": True, "name": coef.name, "stage": len(chain) + 1}})
        run.dataset[comp].attrs["filters"] = chain
    logger.info(f"{site.name}: e_sign {sign:g} recorded in the chain of {done} (LEMI-424 convention)")
    # one "key value" piece with no ";" and no ":" (the EMTF XML writer splits run comments on ";")
    return (f"LEMI-424 E sign convention e_sign {sign:g} recorded in the chain of {', '.join(done)} (E1, E2 are "
            f"recorded with the opposite sign to the x-north, y-east frame), the samples are the logger's columns")


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


def _is_dipole_stage(name: str) -> bool:
    """Whether a filter is a dipole stage (mt-io's ``uoa_dipole_<c>_<L>m``, ``lemi423_dipole_<c>_<L>m``)."""
    return "_dipole_" in str(name)


def _swap_e(run, site: SiteConfig) -> str | None:
    """Exchange the ex and ey channels of a site declared `swap_e`.

    A site whose two electric lines were connected to each other's inputs
    records the line declared as ey on the ex input and the line declared
    as ex on the ey input. The samples of the two channels are exchanged.
    Each channel keeps its own dipole stage (the reader built it from the
    channel's declared length and azimuth, which describe the line its
    samples now hold), and every other stage of its chain, the logger
    input's own (the EDL terminal box and electric gain, the LEMI-423
    linear coefficient), is taken from the input the samples were recorded
    on, in the same place in the chain. The channel's name, azimuth,
    dipole length and every other attr stay. Each channel's metadata
    comment names the input it holds. Called before the reversed-dipole
    rule, which then reads the channels as they are after the exchange.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: The line for the run comment, or None when the site
        does not declare `swap_e`.

    Raises:
        ValueError: If the run does not hold both ex and ey, or their
            chains do not have one dipole stage each in the same place.
    """
    if not site.swap_e:
        return None
    if not all(comp in run.dataset for comp in ("ex", "ey")):
        raise ValueError(f"{site.name}: swap_e exchanges ex and ey, and the run holds "
                         f"{list(run.dataset.data_vars)}")
    chains = {c: list(run.dataset[c].attrs.get("filters") or []) for c in ("ex", "ey")}
    where = {c: [k for k, f in enumerate(chains[c]) if _is_dipole_stage(f["applied_filter"]["name"])]
             for c in chains}
    if len(chains["ex"]) != len(chains["ey"]) or where["ex"] != where["ey"] or len(where["ex"]) > 1:
        names = {c: [f["applied_filter"]["name"] for f in chains[c]] for c in chains}
        raise ValueError(f"{site.name}: swap_e moves each input's stages with its samples and keeps each "
                         f"channel's dipole stage, and the chains do not match stage for stage (ex {names['ex']}, "
                         f"ey {names['ey']})")
    # run.<comp> accessors return copies, so run.dataset is modified directly
    ex, ey = run.dataset["ex"].data, run.dataset["ey"].data
    run.dataset["ex"].data, run.dataset["ey"].data = ey, ex
    dipole = set(where["ex"])
    new = {c: [chains[c][k] if k in dipole else chains["ey" if c == "ex" else "ex"][k]
               for k in range(len(chains[c]))] for c in chains}
    for comp, source in (("ex", "ey"), ("ey", "ex")):
        run.dataset[comp].attrs["filters"] = new[comp]
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), f"swap_e: the samples and input stages of the "
                                                                  f"{source} input, with this channel's dipole stage")
    logger.info(f"{site.name}: swap_e -> ex and ey exchanged (ex holds the ey input, ey the ex input)")
    return ("swap_e: ex and ey exchanged, each with the input stages of the input it was recorded on and its own "
            "dipole stage, before the reversed-dipole rule")


# the run comment line of a Phoenix site declared `swap_e` (`_phoenix_swap_e`, `_ingest_bursts`); one
# "key: value" piece with no semicolon and no second colon (the EMTF XML writer splits run comments on ";")
PHOENIX_SWAP_E_NOTE = ("swap_e: the E2 input stored as ex and the E1 input as ey, each with its samples, receiver "
                       "curve, contact readings, rail, folder and the dipole length of its metadata file, at the "
                       "dipole lengths and azimuths survey.yaml declares for ex and ey")


def _phoenix_swap_e(run, site: SiteConfig) -> str | None:
    """Return the run comment line of a Phoenix site declared `swap_e`, whose run is read exchanged.

    A Phoenix input is stored under a name when it is read
    (`mt_workbench.phoenix.component_of`): at a site declared `swap_e` the
    E2 input's samples are stored as ex and the E1 input's as ey, and
    everything the reader takes from an input goes with its samples, the
    receiver curve, the contact readings, the folder number, the comment
    naming the folder and tag and the metadata file's dipole length; the
    dipole stage and azimuth are the stored channel's declared ones
    (`mt_workbench.phoenix._channel_chain`), and the input's rail goes with
    it (`_phoenix_rails`). The samples are not exchanged again: `_swap_e`, which
    exchanges the samples of a run read under the tags' names, would undo
    it.

    Args:
        run (RunTS): The run as read.
        site (SiteConfig): Site settings.

    Returns:
        str or None: `PHOENIX_SWAP_E_NOTE`, or None when the site does not
        declare `swap_e`.

    Raises:
        ValueError: If the run does not hold both ex and ey.
    """
    if not site.swap_e:
        return None
    if not all(comp in run.dataset for comp in ("ex", "ey")):
        raise ValueError(f"{site.name}: swap_e exchanges ex and ey, and the run holds "
                         f"{list(run.dataset.data_vars)}")
    logger.info(f"{site.name}: swap_e -> the E2 input stored as ex, the E1 input as ey (Phoenix, at the read)")
    return PHOENIX_SWAP_E_NOTE


# the azimuths, modulo 360 deg, the ingest reads an electric channel at: its nominal one or the reversed pair
E_AZIMUTHS = {"ex": (0.0, 180.0), "ey": (90.0, 270.0)}


def _check_e_azimuths(site: SiteConfig, instrument: str) -> None:
    """Refuse an electric layout the ingest cannot store on the geomagnetic axes, before anything is written.

    Ingest reads ex along 0 deg and ey along 90 deg, a line laid at 180 or
    270 deg as the reversed pair (`flip_reversed_dipoles`), and turns a
    pair laid off those axes onto magnetic north and east (`_rot_e`;
    docs/workbench_issues.md 172). This
    guard refuses, for every recorder:

    - a line along the other channel's axis (ex at 90 or 270, ey at 0 or
      180): on the EDL path mt-io's dipole filter takes the azimuth for a
      sign alone, so a sheet layout such as TAS125's (Ex 270, Ey 0) would be
      ingested without a warning; a site whose lines were connected to each other's
      inputs declares `swap_e` with the lengths and azimuths of the lines
      as they are after the exchange, which then pass; a 90/180 sheet
      entry (SA013, SA107_2) is the typo class and is refused, not turned;
    - a pair off the cardinal axes that `_rot_e` cannot turn: a site that
      keeps one electric line; a recorder other than `ROT_E_INSTRUMENTS`
      (Orange Box, Phoenix and LEMI-423, whose sign conventions are not
      established); `flip_reversed_dipoles: false`; `layout_north` other
      than magnetic; or two lines whose angle, as lines, is more than
      `ROT_E_PERPENDICULAR_TOLERANCE` from 90 deg (SA033 180/27, SA214
      180/290; SA175 2/90 at 88 deg passes).

    Each message names the site, both azimuths and the angle between the
    lines.

    Args:
        site (SiteConfig): Site settings (after any `swap_e`, the azimuths
            of the exchanged channels).
        instrument (str): The site's instrument (named in the message).

    Raises:
        ValueError: Naming the site, the two azimuths, the angle between
            the lines and the reason (`swap_e` for a line along the other
            channel's axis).
    """
    kept = [c.lower() for c in site.channels] if site.channels else ["ex", "ey"]
    ax, ay = float(site.azimuth_ex), float(site.azimuth_ey)
    pair = f"ex {ax:g} deg, ey {ay:g} deg, angle {_line_angle(ax, ay):g} deg between the lines"
    for comp, az in (("ex", ax), ("ey", ay)):
        if comp not in kept or az % 360.0 in E_AZIMUTHS[comp]:
            continue
        nominal = E_AZIMUTHS[comp][0]
        if (az - nominal) % 360.0 in (90.0, 270.0):
            raise ValueError(f"{site.name} {comp}: azimuth {az:g} is neither {nominal:g} nor {nominal + 180:g} "
                             f"(survey.yaml, {instrument}; {pair}): the line lies along the other channel's axis "
                             f"(a site whose lines were connected to each other's inputs declares swap_e: true with "
                             f"the lengths and azimuths of the lines as they are after the exchange; a typo is "
                             f"corrected in survey.yaml)")
    if not _rot_e_wanted(site):
        return
    # a line off the cardinal axes: the pair is turned onto magnetic north and east (`_rot_e`), when it can be
    why = None
    if not all(comp in kept for comp in ("ex", "ey")):
        why = f"the turn needs both lines and the site keeps {kept}"
    elif instrument not in ROT_E_INSTRUMENTS:
        why = (f"the turn is built for {' and '.join(ROT_E_INSTRUMENTS)} sites, whose electric sign convention is "
               f"shown; {instrument} is refused until someone shows its convention")
    elif not site.flip_reversed_dipoles:
        why = ("flip_reversed_dipoles is false (an azimuth then records the layout direction only, so it cannot "
               "say which way the line measures)")
    elif str(site.layout_north).lower() != "magnetic":
        why = (f"layout_north is {site.layout_north!r}, and the turn reads the azimuths clockwise from magnetic "
               f"north, onto the geomagnetic axes H is held on")
    elif abs(_line_angle(ax, ay) - 90.0) > ROT_E_PERPENDICULAR_TOLERANCE:
        why = (f"the lines are not a perpendicular pair to within {ROT_E_PERPENDICULAR_TOLERANCE:g} deg (a typo "
               f"class: check the field sheet)")
    if why:
        raise ValueError(f"{site.name}: {pair} (survey.yaml, {instrument}) is off the cardinal axes and is not "
                         f"turned at ingest: {why}")


# the recorders whose electric sign convention `_rot_e` is built for: on both, the two lines share the logger's
# convention, the EDL's in the dipole stage's sign (mt-io), the LEMI-424's in `LEMI424_E_SIGN_FILTER` and the
# reversed-pair rule of `_standardise_e_orientation`
ROT_E_INSTRUMENTS = ("edl", "lemi424")
# the largest departure from 90 deg, as lines, of a pair `_rot_e` turns (beyond it, the typo class)
ROT_E_PERPENDICULAR_TOLERANCE = 15.0
# start of the line `_rot_e` writes into the ex and ey comments and the station provenance (`archive_rot_e`)
ROT_E_PREFIX = "rot_e: "


def _line_angle(ax: float, ay: float) -> float:
    """Return the angle between two lines laid at azimuths `ax` and `ay`, as lines (0 .. 90 deg)."""
    d = abs(float(ax) - float(ay)) % 180.0
    return round(min(d, 180.0 - d), 6) + 0.0


def _e_direction(comp: str, azimuth: float) -> float:
    """Return the direction, deg clockwise from north, along which a calibrated electric channel measures.

    The reversed-pair rule the ingest already applies (mt-io's dipole filter
    on an EDL, `_standardise_e_orientation` on a LEMI-424): a line within
    90 deg of its channel's nominal azimuth (0 for ex, 90 for ey) is read
    the standard way, so the calibrated channel is the field along the
    azimuth as laid; a line more than 90 deg off is read as the reversed
    pair, the calibrated channel the field along the azimuth plus 180. At
    the cardinal azimuths this is 0 for ex at 0 or 180 and 90 for ey at 90
    or 270, the frame the ingest has always stored. A line exactly 90 deg
    off is refused before (`_check_e_azimuths`).
    """
    nominal = E_AZIMUTHS[comp][0]
    off = ((float(azimuth) - nominal) + 180.0) % 360.0 - 180.0
    return float(azimuth) % 360.0 if abs(off) <= 90.0 else (float(azimuth) + 180.0) % 360.0


def _rot_e_wanted(site: SiteConfig) -> bool:
    """Whether a site's electric pair is off the cardinal axes, so that `_rot_e` turns it."""
    return (_e_direction("ex", site.azimuth_ex), _e_direction("ey", site.azimuth_ey)) != (0.0, 90.0)


# channel attrs that describe the samples of the logger input a channel was
# recorded on, and so move with the samples when `_swap_h` exchanges hx and hy:
# the filter chain, whose linear stage on a LEMI-423 holds the input's own ADC
# coefficient, and the reader's comment, which on an MTU-5A names the table
# column and coil the samples were read from (every "sensor." attr moves too)
_INPUT_ATTRS = ("filters", "comments")


def _swap_h(run, site: SiteConfig) -> str | None:
    """Exchange the hx and hy channels of a site declared `swap_h`.

    A site whose two horizontal coils were plugged into each other's inputs
    records the field along hy on the hx input and the field along hx on the
    hy input. The samples of the two channels are exchanged, each with the
    attrs that describe them (`_INPUT_ATTRS` and every "sensor." attr): the
    filter chain of the input it was recorded on, the reader's comment (on
    an MTU-5A the table column and coil the samples were read from) and the
    sensor (the coil that produced them). So the archive's hx holds the
    samples of the hy input with that input's chain, comment and sensor,
    and hy those of the hx input. The component, channel number, azimuth,
    tilt, units, sample rate, time period and every other attr stay with
    the channel name, and the polarity is unchanged. Each channel's moved
    comment then gets the piece "swap_h: the samples, filter chain, sensor
    and comment of the <hy|hx> input, held as <hx|hy>", appended, so a
    later piece (`_flip_h`) follows it.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: The line for the run comment, or None when the site
        does not declare `swap_h`.

    Raises:
        ValueError: If the run does not hold both hx and hy.
    """
    if not site.swap_h:
        return None
    if not all(comp in run.dataset for comp in ("hx", "hy")):
        raise ValueError(f"{site.name}: swap_h exchanges hx and hy, and the run holds "
                         f"{list(run.dataset.data_vars)}")
    # run.<comp> accessors return copies, so run.dataset is modified directly
    hx, hy = run.dataset["hx"].data, run.dataset["hy"].data
    run.dataset["hx"].data, run.dataset["hy"].data = hy, hx
    for key in _INPUT_ATTRS:
        hx_attr, hy_attr = run.dataset["hx"].attrs.get(key), run.dataset["hy"].attrs.get(key)
        run.dataset["hx"].attrs[key], run.dataset["hy"].attrs[key] = hy_attr, hx_attr
    a, b = run.dataset["hx"].attrs, run.dataset["hy"].attrs
    missing = object()
    for key in sorted({k for k in (*a, *b) if str(k).startswith("sensor.")}):
        hx_attr, hy_attr = a.get(key, missing), b.get(key, missing)
        for attrs, value in ((a, hy_attr), (b, hx_attr)):
            if value is missing:  # a sensor attr one channel has and the other does not moves alone
                attrs.pop(key, None)
            else:
                attrs[key] = value
    for comp, source in (("hx", "hy"), ("hy", "hx")):
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), f"swap_h: the samples, filter chain, sensor and "
                                                                   f"comment of the {source} input, held as {comp}")
    logger.info(f"{site.name}: swap_h -> hx and hy exchanged (hx holds the hy input, hy the hx input)")
    return "swap_h: hx and hy exchanged, each with the filter chain of the input it was recorded on"


def _flip_notes(site: SiteConfig) -> tuple[str, str]:
    """Return the run comment line and the channel comment line recording a declared `flip_h`."""
    # each one dot-free "key: value" piece with no ";" and no second ":": the EMTF XML writer
    # (mt_metadata) splits run comments on ";" and sets each "key: value" as an attribute
    # (docs/upstream_issues.md 48)
    after = ", after swap_h" if site.swap_h else ""
    return (f"flip_h: {' '.join(site.flip_h)} samples negated at ingest{after} (declared reversed coil)",
            f"flip_h: the samples negated at ingest{after} (declared reversed coil)")


def _flip_h(run, site: SiteConfig) -> str | None:
    """Negate the samples of the coil channels a site declares `flip_h`.

    Called after `_swap_h`, so the names are the channels as they are after
    the exchange: a site with `swap_h: true` and `flip_h: [hy]` stores the
    hx input's samples, negated, as hy. Only the samples change; the filter
    chain, azimuth and every other attr stay, so the calibrated series is
    the negative of the unflipped one (but for the DC term mt_timeseries'
    time-domain calibration sets, docs/upstream_issues.md 68). Each
    flipped channel's metadata comment gets the line "flip_h: the samples
    negated at ingest ...".

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: The line for the run comment ("flip_h: hy samples
        negated at ingest ..."), or None when the site declares no
        `flip_h`.

    Raises:
        ValueError: If a named channel is not in the run.
    """
    if not site.flip_h:
        return None
    missing = [comp for comp in site.flip_h if comp not in run.dataset]
    if missing:
        raise ValueError(f"{site.name}: flip_h names {missing}, and the run holds {list(run.dataset.data_vars)}")
    note, channel_note = _flip_notes(site)
    for comp in site.flip_h:
        # run.<comp> accessors return copies, so run.dataset is modified directly
        run.dataset[comp].data = -run.dataset[comp].data
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), channel_note)
    logger.info(f"{site.name}: flip_h -> {' '.join(site.flip_h)} sign-flipped"
                f"{' after swap_h' if site.swap_h else ''}")
    return note


# the frequencies, in Hz, at which `_rot_h` compares the hx and hy chains, and the largest relative
# difference of their responses it accepts: the turn mixes the two inputs' samples, which is exact only
# when one chain calibrates both
_ROT_H_FREQS = np.logspace(-5.0, 4.0, 19)
_ROT_H_CHAIN_TOLERANCE = 1e-9


def _chain_response(run, comp: str, freqs: np.ndarray) -> np.ndarray:
    """Return the complex response of a run channel's filter chain at `freqs` (1 for an empty chain)."""
    response = np.ones(freqs.size, dtype=complex)
    for entry in run.dataset[comp].attrs.get("filters") or []:
        response = response * run.filters[entry["applied_filter"]["name"]].complex_response(freqs)
    return response


def _rot_h_note(value: float) -> str:
    """Return the channel and station comment line recording a declared `rot_h` (`_rot_h`)."""
    # one dot-free "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48)
    return f"{ROT_H_PREFIX}{value!r} deg applied at ingest, hx and hy turned from the sensor axes onto magnetic north"


def _rot_h(run, site: SiteConfig) -> str | None:
    """Turn the horizontal pair of a site declared `rot_h` onto magnetic north.

    `SiteConfig.rot_h` is the azimuth of magnetic north measured from the
    sensor's x axis toward its y axis, so the samples become hx' = cos(r) hx
    + sin(r) hy and hy' = -sin(r) hx + cos(r) hy with r = rot_h: a record
    whose mean field lies at r in the sensor frame has mean hy' = 0 and
    mean hx' > 0. Called after `_swap_h` and `_flip_h` (and, on a LEMI-423
    run, after `_apply_h_scale`), so it turns the channels as they then are;
    hz and the electrics are not touched. The turn mixes the samples of two
    inputs, which is exact only when one response calibrates both: the two
    chains' complex responses must agree to `_ROT_H_CHAIN_TOLERANCE` at
    `_ROT_H_FREQS` below the Nyquist (a fluxgate pair on one logger; a
    LEMI-423's per-input linear coefficients differ and are refused). The
    samples become float64; the chains, azimuths (0 and 90 deg, now true)
    and every other attr stay. Each of hx's and hy's metadata comments, and
    the station's ``provenance.comments``, gets the line "rot_h: <value>
    deg applied at ingest, ..." (`archive_rot_h` reads it back).

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: The line for the run comment, which adds the run's
        mean-field azimuth (atan2 of the median hy and hx through the
        chain) before and after the turn; None when `rot_h` is 0.0 and
        the run is left unchanged.

    Raises:
        ValueError: If the run does not hold hx and hy, or their chains
            differ.
    """
    value = site.rot_h
    if value == 0.0:
        return None
    before, after = _turn_h(run, site, value)
    note = _rot_h_note(value)
    for comp in ("hx", "hy"):
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), note)
    provenance = run.station_metadata.provenance
    if note not in str(provenance.comments.value or ""):
        provenance.comments.value = _append_comment(provenance.comments, note)
    logger.info(f"{site.name}: rot_h {value!r} -> hx and hy turned onto magnetic north (mean-field azimuth "
                f"{before:+.2f} deg before, {after:+.2f} after)")
    return f"{note} (mean-field azimuth of this run before the turn {before:+.2f} deg, after {after:+.2f})"


def _turn_h(run, site: SiteConfig, value: float) -> tuple[float, float]:
    """Turn a run's hx and hy by `value` degrees (`_rot_h`'s turn and its chain check); return the mean-field
    azimuths before and after, rounded to 0.01 deg. Used by `_rot_h` (the whole record) and `_rot_h_parts` (a part)."""
    if not all(comp in run.dataset for comp in ("hx", "hy")):
        raise ValueError(f"{site.name}: rot_h turns hx and hy, and the run holds {list(run.dataset.data_vars)}")
    freqs = _ROT_H_FREQS[_ROT_H_FREQS < 0.5 * float(run.sample_rate)]
    rx, ry = _chain_response(run, "hx", freqs), _chain_response(run, "hy", freqs)
    worst = float(np.max(np.abs(rx - ry) / np.maximum(np.abs(ry), 1e-300)))
    if worst > _ROT_H_CHAIN_TOLERANCE:
        names = {c: [f["applied_filter"]["name"] for f in run.dataset[c].attrs.get("filters") or []]
                 for c in ("hx", "hy")}
        raise ValueError(f"{site.name}: rot_h mixes the samples of hx and hy, and their filter chains differ "
                         f"(hx {names['hx']}, hy {names['hy']}: responses {worst:.2e} apart): the turn needs one "
                         f"response for both inputs")
    gain = float(np.real(rx[0])) if freqs.size else 1.0
    x = np.asarray(run.dataset["hx"].data, dtype="float64")
    y = np.asarray(run.dataset["hy"].data, dtype="float64")
    before = float(np.degrees(np.arctan2(np.median(y) / gain, np.median(x) / gain)))
    c, s = np.cos(np.radians(value)), np.sin(np.radians(value))
    # run.<comp> accessors return copies, so run.dataset is modified directly
    run.dataset["hx"].data, run.dataset["hy"].data = c * x + s * y, -s * x + c * y
    after = float(np.degrees(np.arctan2(np.median(run.dataset["hy"].data) / gain,
                                        np.median(run.dataset["hx"].data) / gain)))
    # to the 0.01 deg the comment gives, without a "-0.00"
    return round(before, 2) + 0.0, round(after, 2) + 0.0


def _h_tilt_matrix(vec) -> np.ndarray:
    """Return the rotation matrix of a rotation vector in degrees (Rodrigues): the right-hand turn by |vec| about
    vec/|vec|, so that B_level = R B_sensor (`SiteConfig.h_tilt`)."""
    r = np.radians(np.asarray(vec, dtype="float64"))
    theta = float(np.linalg.norm(r))
    if theta == 0.0:
        return np.eye(3)
    k = r / theta
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + np.sin(theta) * kx + (1.0 - np.cos(theta)) * (kx @ kx)


def _h_tilt_gains(run, site: SiteConfig) -> np.ndarray:
    """Return the counts-per-unit gains of hx, hy and hz's chains (`_h_tilt` turns in physical units).

    Each chain must be flat and real below the Nyquist (a fluxgate's coefficient stages): its complex response at
    `_ROT_H_FREQS` within `_ROT_H_CHAIN_TOLERANCE` of its value at the lowest frequency, which must be real, finite and
    non-zero; the gains may differ in size and sign (an EDL's hz divider, an Orange Box's hy, issue 156)."""
    freqs = _ROT_H_FREQS[_ROT_H_FREQS < 0.5 * float(run.sample_rate)]
    gains = []
    for comp in ("hx", "hy", "hz"):
        resp = _chain_response(run, comp, freqs) if freqs.size else np.ones(1, dtype=complex)
        g = resp[0]
        flat = float(np.max(np.abs(resp - g)) / max(abs(g), 1e-300))
        if not np.isfinite(g) or g == 0 or abs(g.imag) > _ROT_H_CHAIN_TOLERANCE * abs(g) or \
                flat > _ROT_H_CHAIN_TOLERANCE:
            names = [f["applied_filter"]["name"] for f in run.dataset[comp].attrs.get("filters") or []]
            raise ValueError(f"{site.name}: h_tilt turns hx, hy and hz in physical units, and {comp}'s chain {names} "
                             f"is not one flat real gain (response {g:.6g}, {flat:.2e} from flat): the turn needs a "
                             f"fluxgate's coefficient chain")
        gains.append(float(g.real))
    return np.array(gains)


def _h_tilt_note(vec) -> str:
    """Return the channel and station comment line recording a declared `h_tilt` (`archive_h_tilt` reads it)."""
    r = np.asarray(vec, dtype="float64")
    angle = float(np.linalg.norm(r))
    k = r / angle
    # one "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48)
    return (f"{H_TILT_PREFIX}{' '.join(repr(float(v)) for v in vec)} deg rotation vector applied at ingest "
            f"({angle:.2f} deg about the sensor axis {k[0]:.4f} {k[1]:.4f} {k[2]:.4f}), hx hy hz turned together in "
            f"physical units from the tilted sensor axes onto the level frame")


def _field_angles(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[float, float]:
    """Return the (inclination, azimuth) in degrees of the median field of three physical-unit series."""
    mx, my, mz = (float(np.median(v)) for v in (x, y, z))
    return float(np.degrees(np.arctan2(mz, np.hypot(mx, my)))), float(np.degrees(np.arctan2(my, mx)))


def _h_tilt(run, site: SiteConfig) -> str | None:
    """Level a tilted three-component fluxgate: turn hx, hy and hz of a site declared `h_tilt` by its rotation.

    `SiteConfig.h_tilt` is a rotation vector in degrees in the sensor axes; R = `_h_tilt_matrix` and B_level = R
    B_sensor. The turn is made in physical units: each channel's counts divided by its chain's gain
    (`_h_tilt_gains`, which refuses a chain that is not one flat real gain), turned, and multiplied back by the same
    channel's gain, so the stored counts keep their own chains and the calibrated series is R times the calibrated
    sensor series, whatever the gains' sizes and signs. Called after `_swap_h`, `_flip_h` (the channels as they then
    are) and before `_rot_h`; the electrics are not touched. The samples become float64. hx's, hy's and hz's channel
    comments and the station's ``provenance.comments`` get the line "h_tilt: <rx> <ry> <rz> deg rotation vector ..."
    (`archive_h_tilt` reads it back).

    Returns:
        str or None: The line for the run comment, with the run's mean-field inclination and azimuth before and after
        the turn; None when the site declares no `h_tilt`.

    Raises:
        ValueError: If the run does not hold hx, hy and hz, or a chain is not one flat real gain.
    """
    if not site.h_tilt:
        return None
    if not all(comp in run.dataset for comp in ("hx", "hy", "hz")):
        raise ValueError(f"{site.name}: h_tilt turns hx, hy and hz, and the run holds {list(run.dataset.data_vars)}")
    gains = _h_tilt_gains(run, site)
    matrix = _h_tilt_matrix(site.h_tilt)
    b = np.vstack([np.asarray(run.dataset[c].data, dtype="float64") for c in ("hx", "hy", "hz")]) / gains[:, None]
    inc0, az0 = _field_angles(*b)
    level = matrix @ b
    inc1, az1 = _field_angles(*level)
    out = level * gains[:, None]
    note = _h_tilt_note(site.h_tilt)
    for i, comp in enumerate(("hx", "hy", "hz")):
        # run.<comp> accessors return copies, so run.dataset is modified directly
        run.dataset[comp].data = out[i]
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), note)
    provenance = run.station_metadata.provenance
    if note not in str(provenance.comments.value or ""):
        provenance.comments.value = _append_comment(provenance.comments, note)
    logger.info(f"{site.name}: h_tilt {site.h_tilt} -> hx hy hz levelled (mean-field inclination {inc0:+.2f} -> "
                f"{inc1:+.2f} deg, azimuth {az0:+.2f} -> {az1:+.2f})")
    return (f"{note} (mean field of this run before the turn inclination {inc0:+.2f} deg azimuth {az0:+.2f}, after "
            f"inclination {inc1:+.2f} azimuth {az1:+.2f})")


def archive_h_tilt(path: Path, site_name: str) -> list | None:
    """Return the attitude correction an archive's ingest applied (`SiteConfig.h_tilt`, [rx, ry, rz] degrees), from the
    station's ``provenance.comments`` ("h_tilt: ..."); None for an archive that records none."""
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        vec = parse_h_tilt(line)
        if vec:
            return vec
    return None


def _compact_time(iso: str) -> str:
    """Return an ISO UTC time as YYYYmmddTHHMMSSZ (no colon: the comment lines keep one "key: value" colon)."""
    return pd.Timestamp(iso).tz_convert("UTC").strftime("%Y%m%dT%H%M%SZ") if pd.Timestamp(iso).tzinfo else \
        pd.Timestamp(iso).strftime("%Y%m%dT%H%M%SZ")


def _rot_h_part_note(value: float, start: str, end: str) -> str:
    """Return the channel, run and station comment line of one `rot_h_parts` part (`_rot_h_parts`)."""
    return (f"{ROT_H_PARTS_PREFIX}{value!r} deg over {_compact_time(start)} .. {_compact_time(end)} applied at ingest "
            f"(start <= t < end), hx and hy turned from the sensor axes onto magnetic north")


def _rot_h_parts(piece, site: SiteConfig) -> list:
    """Split a run at a site's declared `rot_h_parts` and turn each part's hx and hy by its own angle.

    Each part keeps the run's samples at instants start <= t < end (one contiguous stretch of a run, cut as
    `_record_window` cuts) and is turned by `_turn_h` with the part's angle; samples outside every part are left out,
    so the stretch of a turn is masked by leaving it out of both parts. hx's and hy's channel comments get the part's
    line (`_rot_h_part_note`); the station's provenance gets every part's line (`ingest_site`). Applied to each
    archive run as it is written, after `_record_window`.

    Returns:
        list of tuple: (RunTS, run comment line) per part the run reaches, in time order; empty when it reaches none.
    """
    from mth5.timeseries import RunTS

    times = pd.DatetimeIndex(piece.dataset.coords["time"].values)
    t = times.asi8
    out = []
    for start, end, angle in site.rot_h_parts:
        lo, hi = pd.Timestamp(start).value, pd.Timestamp(end).value
        keep = (t >= lo) & (t < hi)
        if not keep.any():
            continue
        idx = np.flatnonzero(keep)
        i0, i1 = int(idx[0]), int(idx[-1]) + 1
        dataset = piece.dataset.isel(time=slice(i0, i1)).copy()
        t0 = pd.Timestamp(int(t[i0]), unit="ns", tz="UTC").isoformat()
        t1 = pd.Timestamp(int(t[i1 - 1]), unit="ns", tz="UTC").isoformat()
        for comp in dataset.data_vars:
            dataset[comp].attrs = dict(dataset[comp].attrs, **{"time_period.start": t0, "time_period.end": t1})
        sub = RunTS()
        sub.station_metadata = piece.station_metadata.copy()
        sub.run_metadata = piece.run_metadata.copy()
        sub.run_metadata.time_period.start = t0
        sub.run_metadata.time_period.end = t1
        sub.filters = dict(piece.filters)
        sub.dataset = dataset
        before, after = _turn_h(sub, site, angle)
        note = _rot_h_part_note(angle, start, end)
        for comp in ("hx", "hy"):
            attrs = sub.dataset[comp].attrs
            attrs["comments"] = _append_comment(attrs.get("comments"), note)
        line = (f"{note} (mean-field azimuth of this part of the run before the turn {before:+.2f} deg, after "
                f"{after:+.2f}), kept {t0} .. {t1} ({i1 - i0} of {t.size} samples) of the run read {_iso(int(t[0]))} .. "
                f"{_iso(int(t[-1]))}")
        logger.info(f"{site.name}: rot_h_parts {angle!r} deg over {start} .. {end}: {i1 - i0} samples, mean-field "
                    f"azimuth {before:+.2f} -> {after:+.2f} deg")
        out.append((sub, line))
    return out


def archive_rot_h_parts(path: Path, site_name: str) -> list | None:
    """Return the per-part turns an archive's ingest applied (`SiteConfig.rot_h_parts`), from the station's
    ``provenance.comments`` (one "rot_h_part: ..." line per part, `_rot_h_part_note`).

    Returns:
        list or None: [[start ISO, end ISO, angle], ...] sorted by start; None for an archive that records none.
    """
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    parts = [p for p in (parse_rot_h_part(line) for line in comment.split("; ")) if p]
    return sorted(parts, key=lambda p: p[0]) or None


def archive_rot_h(path: Path, site_name: str) -> float | None:
    """Return the turn an archive's ingest applied to its horizontal pair (`SiteConfig.rot_h`).

    Read from the station's ``provenance.comments``, where `_rot_h` records
    it; a raw archive, its filtered variant and a site derived from it
    (scripts/decimate_site.py copies the station's metadata) carry it.

    Args:
        path (Path): The archive.
        site_name (str): The station in it.

    Returns:
        float or None: The angle in degrees; None for an archive that
        records none (built without the key, with 0.0, or before the key
        existed).
    """
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        if line.startswith(ROT_H_PREFIX):
            return float(line[len(ROT_H_PREFIX):].split(" ", 1)[0])
    return None


def _rot_e_matrix(bx: float, by: float) -> np.ndarray:
    """Return the matrix that takes the fields along `bx` and `by` (deg from north) to (E_N, E_E).

    A line measuring along direction b sees E_b = E_N cos b + E_E sin b, so
    [E_bx; E_by] = M [E_N; E_E] with M = [[cos bx, sin bx], [cos by, sin
    by]], and the inverse of M is returned (for a perpendicular pair, by =
    bx + 90, the rotation E_N = E_bx cos bx - E_by sin bx, E_E = E_bx sin bx
    + E_by cos bx).
    """
    bx, by = np.radians(bx), np.radians(by)
    return np.linalg.inv(np.array([[np.cos(bx), np.sin(bx)], [np.cos(by), np.sin(by)]]))


def _rot_e_note(site: SiteConfig) -> str:
    """Return the channel and station comment line recording `_rot_e`'s turn (`archive_rot_e` reads it)."""
    # one dot-free "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48)
    return (f"{ROT_E_PREFIX}ex {float(site.azimuth_ex)!r} deg, ey {float(site.azimuth_ey)!r} deg as laid, turned "
            f"onto magnetic north and east at ingest")


def _rot_e(run, site: SiteConfig, instrument: str) -> str | None:
    """Turn the electric pair of a site laid off the cardinal axes onto magnetic north and east.

    A line laid at azimuth a (deg clockwise from magnetic north,
    `layout_north: magnetic`) measures E_a = E_N cos a + E_E sin a. After
    the reversed-pair rule the ingest already applies (`_e_direction`: on
    an EDL mt-io's dipole filter, on a LEMI-424 `_standardise_e_orientation`)
    the calibrated ex measures along bx and ey along by, (bx, by) = (0, 90)
    at every cardinal layout, so the run is left unchanged there and None returned.
    Otherwise the pair is turned: [E_N; E_E] = inv(M) [E_bx; E_by]
    (`_rot_e_matrix`).

    The two channels' chains differ (each line's own length, and on an EDL
    its own sign), so the samples are mixed in calibrated terms and each
    output written back through its own chain: with Rx and Ry the chain
    responses, the turn needs Ry = k Rx for one real k at every frequency
    (checked to `_ROT_H_CHAIN_TOLERANCE` at `_ROT_H_FREQS` below the
    Nyquist; on an EDL k = (sign_y L_y) / (sign_x L_x) from the dipole
    stages, the terminal box and any electric gain being common); then
    ex' = i00 x + (i01 / k) y and ey' = k i10 x + i11 y in counts, where
    i = inv(M), so that ex' / Rx = i00 E_bx + i01 E_by = E_N and ey' / Ry =
    E_E exactly. Each channel keeps its chain, dipole length and every
    other attr; the samples become float64 and the stored
    ``measurement_azimuth`` is 0 for ex and 90 for ey (now true). On an EDL
    the sign of each dipole stage is checked against the rule first, so a
    chain built from other azimuths than survey.yaml's is refused. Each of
    ex's and ey's metadata comments, and the station's
    ``provenance.comments``, gets the line "rot_e: ex <a_x> deg, ey <a_y>
    deg as laid, turned onto magnetic north and east at ingest"
    (`archive_rot_e` reads it back); the as-laid azimuths stay in
    survey.yaml.

    Order in `ingest_site`: after `_swap_e` (survey.yaml declares the
    azimuths of the lines as they are after the exchange, so the turn reads
    the exchanged channels), after a LEMI-424's `_apply_e_sign` (one
    convention stage common to both chains, which leaves k unchanged) and
    `_standardise_e_orientation` (the reversed-pair rule on the samples,
    which `_e_direction` assumes), and before `_rot_h` (independent: it
    turns hx and hy only) and before anything that reads ex or ey (the dc
    level record, `_h_from_pieces`, the archive write). On an EDL nothing
    acts on ex or ey between the read and here but `_swap_e`.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.
        instrument (str): The site's instrument, one of `ROT_E_INSTRUMENTS`.

    Returns:
        str or None: The line for the run comment (the note, with the angle
        between the lines and the directions turned from), or None at a
        cardinal layout.

    Raises:
        ValueError: If the instrument is not one of `ROT_E_INSTRUMENTS`,
            the run does not hold ex and ey, their chains are not
            proportional by a real constant, or an EDL dipole stage's sign
            disagrees with the rule.
    """
    if not _rot_e_wanted(site):
        return None
    if instrument not in ROT_E_INSTRUMENTS:
        raise ValueError(f"{site.name}: rot_e is built for {ROT_E_INSTRUMENTS}, and this site is {instrument}")
    if not all(comp in run.dataset for comp in ("ex", "ey")):
        raise ValueError(f"{site.name}: rot_e turns ex and ey, and the run holds {list(run.dataset.data_vars)}")
    ax, ay = float(site.azimuth_ex), float(site.azimuth_ey)
    bx, by = _e_direction("ex", ax), _e_direction("ey", ay)
    freqs = _ROT_H_FREQS[_ROT_H_FREQS < 0.5 * float(run.sample_rate)]
    rx, ry = _chain_response(run, "ex", freqs), _chain_response(run, "ey", freqs)
    ratio = ry / rx if freqs.size else np.ones(1, dtype=complex)
    k = complex(ratio[0])
    spread = float(np.max(np.abs(ratio - k)) / abs(k))
    names = {c: [f["applied_filter"]["name"] for f in run.dataset[c].attrs.get("filters") or []]
             for c in ("ex", "ey")}
    if spread > _ROT_H_CHAIN_TOLERANCE or abs(k.imag) > _ROT_H_CHAIN_TOLERANCE * abs(k):
        raise ValueError(f"{site.name}: rot_e mixes the samples of ex and ey, and their chains are not one "
                         f"response times a real constant (ex {names['ex']}, ey {names['ey']}: ratio {k:.6g}, "
                         f"spread {spread:.2e})")
    if instrument == "edl":
        for comp, az, b in (("ex", ax, bx), ("ey", ay, by)):
            stages = [n for n in names[comp] if _is_dipole_stage(n)]
            want = -1.0 if b == az % 360.0 else 1.0  # the EDL hardware inverts E; a reversed line cancels it
            got = [float(np.sign(run.filters[n].gain)) for n in stages]
            if got != [want]:
                raise ValueError(f"{site.name} {comp}: rot_e reads the line at {az:g} deg as measuring along "
                                 f"{b:g}, which needs one dipole stage of sign {want:+g}, and the chain has "
                                 f"{stages} of sign {got} (read with other azimuths than survey.yaml's?)")
    k = k.real
    inv = _rot_e_matrix(bx, by)
    x = np.asarray(run.dataset["ex"].data, dtype="float64")
    y = np.asarray(run.dataset["ey"].data, dtype="float64")
    # run.<comp> accessors return copies, so run.dataset is modified directly
    run.dataset["ex"].data = inv[0, 0] * x + (inv[0, 1] / k) * y
    run.dataset["ey"].data = (k * inv[1, 0]) * x + inv[1, 1] * y
    note = _rot_e_note(site)
    for comp, azimuth in (("ex", 0.0), ("ey", 90.0)):
        attrs = run.dataset[comp].attrs
        attrs["measurement_azimuth"] = azimuth
        attrs["comments"] = _append_comment(attrs.get("comments"), note)
    provenance = run.station_metadata.provenance
    if note not in str(provenance.comments.value or ""):
        provenance.comments.value = _append_comment(provenance.comments, note)
    angle = _line_angle(ax, ay)
    logger.info(f"{site.name}: rot_e ex {ax:g} ey {ay:g} (measuring along {bx:g} and {by:g}, {angle:.2f} deg "
                f"apart) -> turned onto magnetic north and east")
    return (f"{note} (angle between the lines {angle:.2f} deg, ex measuring along {bx:g} and ey along {by:g} "
            f"after the reversed-pair rule, each channel through its own chain)")


def archive_rot_e(path: Path, site_name: str) -> tuple[float, float] | None:
    """Return the as-laid azimuths of the electric pair an archive's ingest turned (`_rot_e`), or None.

    Read from the station's ``provenance.comments``, where `_rot_e` records
    the line "rot_e: ex <a_x> deg, ey <a_y> deg as laid, ...".

    Args:
        path (Path): The archive.
        site_name (str): The station in it.

    Returns:
        tuple of float or None: (a_x, a_y) in degrees; None for an archive
        that records no turn (a cardinal layout, or built before rot_e).
    """
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        if line.startswith(ROT_E_PREFIX):
            words = line[len(ROT_E_PREFIX):].split(" ")
            return float(words[1]), float(words[4])
    return None


# start of the line `_shift_clock` writes into the run, channel and station
# provenance comments, followed by the offset's repr and ":"
_CLOCK_PREFIX = "clock_offset_s: "
# the earlier form of the note ("clock_offset_s -1.0: ..."); archives written with it are still read
_CLOCK_PREFIX_OLD = "clock_offset_s "
# mt_metadata's time of a period edge that was never set
_UNSET_TIME = "1980-01-01T00:00:00+00:00"


def _append_comment(prior, note: str) -> str:
    """Return `note` after a comment's text and "; ", or `note` alone when the comment is empty."""
    prior = "" if prior is None else str(getattr(prior, "value", prior) or "")
    return f"{prior}; {note}" if prior else note


def _clock_note(offset: float) -> str:
    """Return the comment line recording a declared `clock_offset_s` (`_shift_clock`)."""
    # one "key: value" piece with no dot in the key and no semicolon: the EMTF XML writer
    # (mt_metadata) splits run comments on ";" and sets each "key: value" as an attribute
    return (f"{_CLOCK_PREFIX}{offset!r} s added to every recorded time stamp at ingest "
            f"(declared logger clock error), the samples as recorded")


def _shift_clock(run, site: SiteConfig) -> str | None:
    """Add a site's declared `clock_offset_s` to every time stamp of a run.

    The run's time axis, its start and end, each channel's start and end
    and the station's time period move by the offset; the samples are not
    touched. The line returned for the run comment is also appended to each
    channel's metadata comment and to the station's ``provenance.comments``,
    so the record stays with a channel read on its own and with a filtered
    variant (`build_variant` replaces the run comment and keeps the
    others). A time stamp moves by the offset rounded to the nearest
    nanosecond, the resolution of the time axis.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: The line for the run comment, or None when the offset
        is 0.0 and the run is left unchanged.
    """
    offset = site.clock_offset_s
    if offset == 0.0:
        return None
    shift = pd.Timedelta(seconds=offset)
    recorded = pd.DatetimeIndex(run.dataset.coords["time"].values)
    shifted = recorded + shift
    note = _clock_note(offset)
    # the station's period only ever widens to cover its runs' periods
    # (Station.update_time_period, when the dataset is set), so it and its run
    # entries are moved first; then the run's own, which the new axis must match
    station = run.station_metadata
    for period in [station.time_period] + [entry.time_period for entry in station.runs]:
        for edge in ("start", "end"):
            value = getattr(period, edge)
            if value != _UNSET_TIME:
                setattr(period, edge, (pd.Timestamp(str(value)) + shift).isoformat())
    run.run_metadata.time_period.start = shifted[0].isoformat()
    run.run_metadata.time_period.end = shifted[-1].isoformat()
    dataset = run.dataset.assign_coords(time=shifted)
    for comp in dataset.data_vars:
        attrs = dataset[comp].attrs
        attrs["time_period.start"] = shifted[0].isoformat()
        attrs["time_period.end"] = shifted[-1].isoformat()
        attrs["comments"] = _append_comment(attrs.get("comments"), note)
    run.dataset = dataset
    provenance = station.provenance
    if note not in str(provenance.comments.value or ""):
        provenance.comments.value = _append_comment(provenance.comments, note)
    logger.info(f"{site.name}: clock_offset_s {offset!r} -> run time stamps shifted by {offset!r} s, "
                f"{recorded[0].isoformat()} -> {shifted[0].isoformat()} (samples as recorded)")
    return note


def archive_clock_offset(path: Path, site_name: str) -> float:
    """Return the clock offset an archive's ingest added to its time stamps.

    Read from the station's ``provenance.comments``, where `_shift_clock`
    records it; a raw archive and its filtered variant both carry it.

    Args:
        path (Path): The archive.
        site_name (str): The station in it.

    Returns:
        float: The offset in seconds; 0.0 for an archive that records none,
        such as one built before the key existed.
    """
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        if line.startswith(_CLOCK_PREFIX):
            return float(line[len(_CLOCK_PREFIX):].split(" ", 1)[0])
        if line.startswith(_CLOCK_PREFIX_OLD):
            return float(line[len(_CLOCK_PREFIX_OLD):].split(":", 1)[0])
    return 0.0


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
        entry = (survey.config.get("sites") or {}).get(site.name) or {}
        for key in ("electric_gain", "electric_gain_ex", "electric_gain_ey"):
            own = entry.get(key)
            if own is not None and float(own) != 1.0:
                raise ValueError(f"{site.name}: {key} {own} is an Earth Data PR6-24 (EDL) electric-chain "
                                 f"setting, and this site is {instrument}: remove the key from its survey.yaml entry")
        return 1.0
    gain = edl_electric_gain(site)
    from_ini = recorder_ini_high_gain(site_dir)
    if from_ini:
        logger.warning(f"{site.name}: recorder.ini says channel_n_high_gain=1 for {' '.join(from_ini)}; "
                       f"electric_gain declared as {gain:g}; informational, the flag is not used")
    return gain


def _e_sign(survey: Survey, site: SiteConfig, instrument: str) -> float:
    """Return the sign `_apply_e_sign` records in a site's electric chains.

    Checked once per site before anything is written. For a LEMI-424 site
    this is `SiteConfig.e_sign`, or -1.0 when the key is unset (the
    instrument's convention). For other instruments a `defaults:` value is
    ignored and the sign is 1.0.

    Args:
        survey (Survey): The survey.
        site (SiteConfig): Site settings.
        instrument (str): The site's instrument.

    Returns:
        float: 1.0 or -1.0.

    Raises:
        ValueError: If a site of another instrument sets its own `e_sign`
            other than 1.0.
    """
    if instrument != "lemi424":
        own = ((survey.config.get("sites") or {}).get(site.name) or {}).get("e_sign")
        if own is not None and float(own) != 1.0:
            raise ValueError(f"{site.name}: e_sign {own} is the LEMI-424 electric sign convention, and this site is "
                             f"{instrument}: remove the key from its survey.yaml entry (a line laid reversed is "
                             f"declared by its azimuth with flip_reversed_dipoles)")
        return 1.0
    return LEMI424_E_SIGN if site.e_sign is None else float(site.e_sign)


def _record_window(piece, site: SiteConfig):
    """Clip a run to a site's declared `record_window`; return (the run or None, the run comment line or None).

    Keeps the samples at instants t with start <= t < end (an open bound
    keeps everything on its side). A run wholly inside is returned
    untouched with no line; a run wholly outside gives (None, None) and
    `ingest_site` records it in the station's provenance; a run cut gets
    the line "record_window: kept <a> .. <b> of the run read <c> .. <d>
    (window <start> .. <end>, start <= t < end)", its time periods updated
    as `_trim_run_start` updates them. Applied to each archive run as it is
    written, after every other step (`_h_from_pieces` included), so the
    window is on the time axis of the declared `clock_offset_s`.

    Args:
        piece (RunTS): A run as it would be written.
        site (SiteConfig): Site settings.

    Returns:
        tuple: (RunTS or None, str or None).
    """
    if not site.record_window:
        return piece, None
    from mth5.timeseries import RunTS

    from .survey import window_bounds

    lo, hi = window_bounds(site)
    times = pd.DatetimeIndex(piece.dataset.coords["time"].values)
    t = times.asi8
    keep = np.ones(t.size, dtype=bool)
    if lo is not None:
        keep &= t >= lo.value
    if hi is not None:
        keep &= t < hi.value
    if keep.all():
        return piece, None
    if not keep.any():
        return None, None
    idx = np.flatnonzero(keep)
    i0, i1 = int(idx[0]), int(idx[-1]) + 1  # the kept instants are one contiguous stretch of a run
    dataset = piece.dataset.isel(time=slice(i0, i1)).copy()
    t0 = pd.Timestamp(int(t[i0]), unit="ns", tz="UTC").isoformat()
    t1 = pd.Timestamp(int(t[i1 - 1]), unit="ns", tz="UTC").isoformat()
    for comp in dataset.data_vars:
        dataset[comp].attrs = dict(dataset[comp].attrs, **{"time_period.start": t0, "time_period.end": t1})
    out = RunTS()
    out.station_metadata = piece.station_metadata.copy()
    out.run_metadata = piece.run_metadata.copy()
    out.run_metadata.time_period.start = t0
    out.run_metadata.time_period.end = t1
    out.filters = dict(piece.filters)
    out.dataset = dataset
    window = " .. ".join("open" if v is None else v for v in site.record_window)
    line = (f"record_window: kept {t0} .. {t1} ({i1 - i0} of {t.size} samples) of the run read "
            f"{_iso(int(t[0]))} .. {_iso(int(t[-1]))} (window {window}, start <= t < end)")
    return out, line


def _record_window_station_notes(site: SiteConfig, left_out: list[str]) -> list[str]:
    """Return the station provenance lines of a declared `record_window`: the window, then each run left out."""
    if not site.record_window:
        return []
    window = " .. ".join("open" if v is None else v for v in site.record_window)
    lines = [f"record_window: {window} declared (start <= t < end), samples outside it left out at ingest"]
    lines += [f"record_window: the run read {span} left out, wholly outside the window" for span in left_out]
    return lines


# the run comment line of a site declared `edl_banks_swapped` (`_edl_banks_swapped`); one "key: value"
# piece with no semicolon (the EMTF XML writer splits run comments on ";")
EDL_BANKS_NOTE = ("edl_banks_swapped: the magnetometer and electrode cables in each other's banks, hx and hy "
                  "the .EX and .EY words through the magnetometer chain, ex and ey the .BX and .BY words through "
                  "the electric chain of the declared lines, the .BZ words (the electric bank's spare input) "
                  "left out, no hz recorded")


def _check_banks_instrument(site: SiteConfig, instrument: str) -> None:
    """Refuse `edl_banks_swapped` on a site that is not an EDL, before anything is written."""
    if site.edl_banks_swapped and instrument != "edl":
        raise ValueError(f"{site.name}: edl_banks_swapped is an Earth Data PR6-24 (EDL) wiring, and this site is "
                         f"{INSTRUMENTS[instrument]['label']}: remove the key")


def _edl_banks_swapped(run, site: SiteConfig) -> str | None:
    """Store an EDL run whose two banks held each other's sensors on the channels of the sensors.

    A site declared `edl_banks_swapped` recorded the fluxgate's x and y on
    the electric bank (the .EX and .EY files) and the electrode lines on the
    magnetometer bank (.BX and .BY). The reader (mt_io.uoa.pr624) maps
    files by extension and builds each channel's chain for its name: the
    Bartington stage on hx and hy, the dipole of the declared length and
    azimuth sign and the terminal box on ex and ey (and `electric_gain`).
    Both banks store microVolt as recorded, so the samples are exchanged
    (hx <-> ex, hy <-> ey) and each channel keeps the chain of its name,
    which is the chain of the sensor whose signal it now holds. The .BZ
    words, the electric bank's spare input, are dropped with hz (the
    fluxgate's z was not recorded). Each channel's comment names the file
    it holds, and the station's ``provenance.comments`` gets
    `EDL_BANKS_NOTE`. Called right after the read, before `_keep_channels`,
    `_swap_e`, `_swap_h`, `_flip_h`, `_rot_e` and `_rot_h`, which all read
    the channels as they are after the exchange.

    Args:
        run (RunTS): Run, modified in place.
        site (SiteConfig): Site settings.

    Returns:
        str or None: `EDL_BANKS_NOTE`, or None when the site does not
        declare the key.

    Raises:
        ValueError: If the run does not hold hx, hy, ex and ey.
    """
    if not site.edl_banks_swapped:
        return None
    if not all(comp in run.dataset for comp in ("hx", "hy", "ex", "ey")):
        raise ValueError(f"{site.name}: edl_banks_swapped exchanges hx with ex and hy with ey, and the run holds "
                         f"{list(run.dataset.data_vars)}")
    # run.<comp> accessors return copies, so run.dataset is modified directly
    for h, e in (("hx", "ex"), ("hy", "ey")):
        hd, ed = run.dataset[h].data, run.dataset[e].data
        run.dataset[h].data, run.dataset[e].data = ed, hd
    files = {"hx": ".EX", "hy": ".EY", "ex": ".BX", "ey": ".BY"}
    for comp, suffix in files.items():
        chain = "magnetometer" if comp.startswith("h") else "electric"
        attrs = run.dataset[comp].attrs
        attrs["comments"] = _append_comment(attrs.get("comments"), f"edl_banks_swapped: the words of the {suffix} "
                                                                  f"file read through this channel's {chain} chain")
    if "hz" in run.dataset:
        _keep_channels(run, SiteConfig(name=site.name, channels=[c for c in run.dataset.data_vars if c != "hz"]))
    provenance = run.station_metadata.provenance
    if EDL_BANKS_NOTE not in str(provenance.comments.value or ""):
        provenance.comments.value = _append_comment(provenance.comments, EDL_BANKS_NOTE)
    logger.info(f"{site.name}: edl_banks_swapped -> hx hy from the .EX .EY files, ex ey from .BX .BY, hz left out")
    return EDL_BANKS_NOTE


def _keep_channels(run, site: SiteConfig) -> None:
    """Drop channels not listed in `site.channels`, such as an unconnected hz.

    The reader returns every column of the file, and the survey declares
    which had a sensor attached. Dropping the others keeps the MTH5 to the
    recorded channels, so aurora estimates no tipper from an open input.
    A dropped channel is also taken out of the run's channel list and the
    station's channels_recorded and run entries.

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
            f"{list(run.dataset.data_vars)}; declare this site's `channels:` in its instrument's names"
        )
    run.dataset = run.dataset.drop_vars(drop)
    for attr in ("channels_recorded_magnetic", "channels_recorded_electric", "channels_recorded_auxiliary"):
        current = getattr(run.run_metadata, attr, None)
        if current:
            setattr(run.run_metadata, attr, [c for c in current if c.lower() in keep])
    # the run's channel list and the station's channels_recorded and runs keep the dropped names, and
    # aurora's TF export then stops on one (docs/workbench_issues.md 92)
    for comp in drop:
        if comp in run.run_metadata.channels.keys():
            run.run_metadata.channels.remove(comp)
    station = run.station_metadata
    station.channels_recorded = [c for c in station.channels_recorded if c not in drop]
    for listed in station.runs:
        for comp in drop:
            if comp in listed.channels.keys():
                listed.channels.remove(comp)
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
        logger.warning(f"{len(bad)} EDL file stamp(s) without exactly one file per channel: {listed}; "
                       f"left out, the run split there")
    return set(bad)


class EdlRun(list):
    """The files of one EDL run (a list of Path, as `_group_contiguous` returns), with its trim.

    Attributes:
        trim (int): Samples at the start of the run's first stamp that the
            file before it already holds (a restart file stamped before the
            end of the file it interrupted); the ingest leaves them out
            (`_trim_run_start`), so the earlier file's samples are kept.
        overlaps (str or None): The stem of that earlier file.
    """

    trim: int = 0
    overlaps: str | None = None


def _edl_samples(path: Path) -> int | None:
    """Count an EDL file's samples, or None for a file of bytes without samples (an all-null block).

    mt-io's `count_samples` raises ``ValueError("<name> holds bytes but no
    samples")`` on a file that is not empty but is neither miniSEED nor holds
    a newline, by design: counting it as zero would put a run of no length
    into a collection. Such a file is a block of zeros a logger or a copy
    left in place of the data: AusLAMP Victoria's
    `VIC076_140628150000.BY`, 53,248 bytes of zeros beside that stamp's
    readable BX, BZ, EX and EY (workbench issue 75). `_edl_plan` leaves its
    stamp out; `mt_workbench.instruments.span` repeats these lines for its
    last file (that module does not import this one).

    Args:
        path (Path): An EDL data file.

    Returns:
        int or None: mt-io's sample count, or None when mt-io finds bytes
        but no samples.

    Raises:
        ValueError: mt-io's, for any other reason than bytes without samples.
        OSError: A file that cannot be read.
    """
    from mt_io.uoa.pr624 import count_samples

    try:
        return count_samples(path)
    except ValueError as exc:
        if "holds bytes but no samples" in str(exc):
            return None
        raise


def _edl_plan(files: list[Path], stamps: list[int], drop: set[int], rate: float, suspect: set[int] | None = None
              ) -> tuple[list[set[int]], dict[int, tuple[int, int]]]:
    """Group EDL stamps into runs by sample count, trimming restart files that overlap the file before them.

    Follows mt-io's contiguity rule (`UoACollection._run_boundaries`). Every
    file's samples are counted (`mt_io.uoa.pr624.count_samples`, a newline
    count taking a few seconds per site once the files are cached). A stamp
    joins the run when it starts where the previous stamp's files end, to
    within two samples, so a file shorter than the time to the next stamp
    ends its run. Stamp spacing alone does not detect this: short startup
    files (e.g. 15 s each, stamped 300 s apart), read as one stretch, date
    every later sample of the run early (mt-io's reader warns of the seconds
    missing between files). A stamp whose channel files differ in length is
    left out, as a stamp with a missing file is, and so is a stamp whose
    files hold no sample (TAS112's `TAS112_160218220000`, five files of 0
    bytes, which mt-io's reader refuses), without ending the run. A stamp
    with any file of bytes but no samples (`_edl_samples` None: VIC076's
    `VIC076_140628150000.BY`, 53,248 bytes of zeros, on which mt-io's
    `count_samples` raises) takes the same path with its own warning, its
    other channels' files left out with it; the next stamp then does not
    start where the files before end, so contiguity splits the run there.

    A file holding the deployment test run before the record (a PR6-24 run
    for a little while at deployment, stopped and run again: two trace ids
    in the first file, AusLAMP Victoria's VIC078b_140822050000) is placed
    as mt-io reads it: the record alone (mt-io's count), from the record's
    start (`edl_record_start`), not from the file name's stamp. A stamp
    whose channel files' records start at different times is left out as
    an uneven one is (workbench issue 76).

    A stamp that starts before the end of the samples kept so far (a PR6-24
    restarted during a file writes the new file's stamp inside the old
    file's span: TAS105's `Tas105_160124050845` starts 17 s before
    `Tas105_160124050800` ends) starts a run whose first file loses its
    overlapping samples, so the earlier file's samples are kept and no two
    runs share an instant; a file that lies wholly inside the kept samples
    is left out. Both are logged. Before that, a `suspect` stamp
    (`_other_rate_stamps`: recorder.msg had a data channel at another rate)
    whose files hold more samples than the time to the next stamp allows
    at `rate` is left out and ends its run: its samples are at another
    rate, and trimming them would keep them stretched.

    Args:
        files (list of Path): EDL files.
        stamps (list of int): Start stamp of each file, unix seconds.
        drop (set of int): Stamps already left out (`_incomplete_stamps`).
        rate (float): Sample rate in Hz.
        suspect (set of int, optional): Stamps recorder.msg puts at
            another rate (`_other_rate_stamps`).

    Returns:
        tuple: (the stamps of each run, {first stamp of a trimmed run:
        (samples left out, the stamp of the earlier file)}).
    """
    lengths: dict[int, set[int]] = {}
    nulls: dict[int, list[Path]] = {}  # stamp: its files of bytes without samples (all-null blocks)
    leads: dict[int, set[float]] = {}  # stamp: s from it to its files' first sample (0, or after a test run)
    for f, s in zip(files, stamps):
        n = _edl_samples(f)
        if n is None:
            nulls.setdefault(s, []).append(Path(f))
        lengths.setdefault(s, set()).add(0 if n is None else n)
        record = edl_record_start(f) if n else None
        leads.setdefault(s, set()).add(0.0 if record is None else (record - s * 1_000_000_000) / 1e9)
    for s in nulls:
        lengths[s] = {0}  # the stamp holds no sample: left out below as `empty` is, never `uneven`
    uneven = {s for s, n in lengths.items() if len(n) > 1 and s not in drop}
    if uneven:
        logger.warning(f"{len(uneven)} EDL file stamp(s) whose channel files differ in length: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} {sorted(lengths[s])}"
                                   for s in sorted(uneven)) + "; left out, the run split there")
    askew = {s for s, v in leads.items() if len(v) > 1 and s not in drop and s not in uneven and s not in nulls}
    if askew:
        logger.warning(f"{len(askew)} EDL file stamp(s) whose channel files' records start at different times "
                       "after a deployment test run: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} +{sorted(leads[s])} s"
                                   for s in sorted(askew)) + "; left out, the run split there")
        uneven |= askew
    lead = {s: max(v) for s, v in leads.items()}
    tested = sorted(s for s in lengths if lead[s] and s not in drop and s not in uneven and s not in nulls)
    if tested:
        logger.warning(f"{len(tested)} EDL file stamp(s) holding the deployment test run before the record: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} (record from "
                                   + f"{pd.Timestamp(s + lead[s], unit='s'):%H:%M:%S.%f}"[:-5] + ")" for s in tested)
                       + "; the test run left out, the record placed at its own start")
    ordered = sorted(lengths)
    nxt = dict(zip(ordered, ordered[1:]))
    other = sorted(s for s in (suspect or set()) if s in nxt and s not in drop
                   and max(lengths[s]) > (nxt[s] - (s + lead[s])) * rate + 2)
    if other:
        logger.warning(f"{len(other)} EDL file stamp(s) recorded while recorder.msg had a data channel at another "
                       f"rate than {rate:g} Hz, their files overrunning the next stamp "
                       f"({pd.Timestamp(other[0], unit='s'):%Y-%m-%d %H:%M:%S} .. "
                       f"{pd.Timestamp(other[-1], unit='s'):%Y-%m-%d %H:%M:%S}): left out, the run split there")
        drop = set(drop) | set(other)
    empty = sorted(s for s, n in lengths.items() if n == {0} and s not in drop and s not in nulls)
    if empty:
        logger.warning(f"{len(empty)} EDL file stamp(s) whose files hold no sample: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S}" for s in empty) + "; left out")
    null = sorted(s for s in nulls if s not in drop)
    if null:
        logger.warning(f"{len(null)} EDL file stamp(s) whose files hold bytes but no samples (all-null blocks): "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} "
                                   f"{'/'.join(str(b) for b in sorted({f.stat().st_size for f in nulls[s]}))} bytes "
                                   f"({' '.join(sorted(f.name for f in nulls[s]))})"
                                   for s in null) + "; left out, the run split there")
    runs: list[set[int]] = []
    trims: dict[int, tuple[int, int]] = {}
    inside: list[int] = []
    ids: set[int] = set()
    end, cut = None, []
    kept_end, kept_stamp = None, None  # the end of the samples kept so far, and the stamp they end with
    for s in sorted(lengths):
        if s in drop or s in uneven:
            if ids:
                runs.append(ids)
            ids, end = set(), None
            continue
        n = next(iter(lengths[s]))
        if n == 0:
            continue
        t = s + lead[s]  # where the stamp's samples start: the stamp, or after a deployment test run the record
        if kept_end is not None and t < kept_end - 2.0 / rate:
            overlap = int(round((kept_end - t) * rate))
            if overlap >= n:
                inside.append(s)
                continue
            if ids:
                runs.append(ids)
            ids = {s}
            trims[s] = (overlap, kept_stamp)
            end = kept_end = t + n / rate
            kept_stamp = s
            continue
        if ids and abs(t - end) > 2.0 / rate:
            runs.append(ids)
            ids = set()
            if t > end:
                cut.append(s)
        ids.add(s)
        end = t + n / rate
        if kept_end is None or end >= kept_end:
            kept_end, kept_stamp = end, s
    if ids:
        runs.append(ids)
    if cut:
        logger.info(f"{len(cut)} EDL run split(s) where a file ends before the next stamp")
    for s, (overlap, earlier) in sorted(trims.items()):
        logger.warning(f"EDL file stamp {pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S} starts {overlap / rate:g} s "
                       f"before the samples of {pd.Timestamp(earlier, unit='s'):%Y-%m-%d %H:%M:%S} end: its first "
                       f"{overlap} samples are left out, the earlier file's kept")
    if inside:
        logger.warning(f"{len(inside)} EDL file stamp(s) wholly inside the samples of the file before them: "
                       + ", ".join(f"{pd.Timestamp(s, unit='s'):%Y-%m-%d %H:%M:%S}" for s in inside) + "; left out")
    return runs, trims


# a recorder.msg line of the PR6-24's digitiser set-up: "24/10/16 03:04:01 Channel 00 changing to low  gain 100s/s"
_MSG_RATE = re.compile(r"^(\d\d)/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d) Channel (\d\d) (?:changing to|already at)\s+"
                       r"\S+\s+gain\s+(\d+(?:\.\d+)?)s/s")


def _edl_rate_changes(site_dir: Path) -> list[tuple[int, dict[int, float]]]:
    """Read the digitiser's channel rates through time from a PR6-24's recorder.msg files.

    Each "Buffer/Digitiser reconfigure" of the recorder's log lists every
    channel "changing to" or "already at" its gain and rate, with the
    recorder's GPS-set time (dd/mm/yy hh:mm:ss, UTC). The state after each
    such line is returned in time order.

    Args:
        site_dir (Path): The site folder; every recorder.msg under it is read.

    Returns:
        list of tuple: (unix seconds, {channel number: rate in Hz}) after
        each line; empty when there is no recorder.msg or no such line.
    """
    lines = []
    for msg in sorted(Path(site_dir).rglob("recorder.msg")):
        for raw in msg.read_text(errors="replace").splitlines():
            m = _MSG_RATE.match(raw.strip())
            if m:
                dd, mm, yy, hh, mi, ss, ch, r = m.groups()
                when = int(pd.Timestamp(f"20{yy}-{mm}-{dd}T{hh}:{mi}:{ss}", tz="UTC").timestamp())
                lines.append((when, int(ch), float(r)))
    state: dict[int, float] = {}
    out = []
    for when, ch, r in sorted(lines, key=lambda x: x[0]):
        state[ch] = r
        out.append((when, dict(state)))
    return out


def _other_rate_stamps(files: list[Path], stamps: list[int], rate: float) -> set[int]:
    """Find the EDL stamps recorder.msg says were recorded with a data channel at another rate than the site's.

    A PR6-24 set up at another rate for a while (TAS151 of Tasmania
    AusLAMP 2016 ran channels 00-05 at 100 s/s from 03:04:30 to 03:31:47 UTC
    on 24 Oct 2016, then at the survey's 10 s/s) writes files whose samples
    read at the site's rate would be stretched in time: such a file holds
    ten times the samples its stamps' spacing allows, so it overruns the
    files after it. A stamp at or after a recorder.msg line that left a data
    channel (one at the site's rate in some state of the log; a 1 s/s
    temperature channel is not) at another rate is a suspect. The log is
    not always the deployment's own (TAS106, TAS131 and TAS221LP end on a
    1000 or 50 s/s set-up while their files are 10 Hz throughout), so
    `_edl_plan` leaves a suspect out only when its files overrun the next
    stamp at the site's rate.

    Args:
        files (list of Path): EDL files.
        stamps (list of int): Start stamp of each file, unix seconds.
        rate (float): The site's sample rate in Hz.

    Returns:
        set of int: The suspect stamps.
    """
    if not files:
        return set()
    folder = Path(os.path.commonpath([str(Path(f).parent) for f in files]))
    changes = _edl_rate_changes(folder)
    if not changes:
        return set()
    # the data channels: those at the site's rate in any state of the log
    data = {ch for _when, state in changes for ch, r in state.items() if abs(r - rate) <= 1e-9 * rate}
    times = [when for when, _state in changes]
    out = set()
    for s in set(stamps):
        k = int(np.searchsorted(times, s, side="right")) - 1
        if k < 0:
            continue
        state = changes[k][1]
        if any(abs(state.get(ch, rate) - rate) > 1e-9 * rate for ch in data):
            out.add(s)
    return out


def _edl_runs_by_samples(files: list[Path], stamps: list[int], drop: set[int], rate: float) -> list[set[int]]:
    """Group EDL stamps into runs by sample count (`_edl_plan` without its trims).

    Args:
        files (list of Path): EDL files.
        stamps (list of int): Start stamp of each file, unix seconds.
        drop (set of int): Stamps already left out (`_incomplete_stamps`).
        rate (float): Sample rate in Hz.

    Returns:
        list of set: The stamps of each run.
    """
    return _edl_plan(files, stamps, drop, rate)[0]


def _overlap_note(group, rate: float) -> str:
    """Return the run comment line of an `EdlRun` whose first file overlaps the file before it."""
    # one dot-free "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48): no clock times
    first = Path(group[0]).stem
    return (f"overlap: the first {group.trim} samples ({group.trim / float(rate):.1f} s) of {first} left out, the "
            f"file {group.overlaps} before it holds those instants and its samples are kept (restart file stamped "
            f"before the end of that file)")


def _check_edl_read(run, group, site_name: str, rate: float) -> None:
    """Refuse an EDL run whose samples are not the ones planned (workbench issue 76).

    `_edl_plan` places each file's samples by its stamp (or, after a
    deployment test run, the record's start) and sample count, and a run's
    planned samples and start are `_edl_run_spans`'s; mt-io's reader joins
    each channel's files end to end and dates them from the first. A file
    returning other samples than counted (one trace of a two-id file, before
    upstream 525) would put every later sample of the run early, so the read
    is compared with the plan here, each channel's samples and the run's
    start (to within half a sample), as read: before the trim of a restart
    file (`_trim_run_start`, the plan of the group's files without it).

    Args:
        run (RunTS): The run as read.
        group (list of Path): Its files (an `EdlRun`).
        site_name (str): Site name, for the message.
        rate (float): The site's sample rate in Hz.

    Raises:
        ValueError: If a channel's samples or the run's start differ from
            the plan, naming the site, the run's first file, and the planned
            and read counts and starts.
    """
    plan = _edl_run_spans([list(group)], 0.0, rate)[0]  # as read: a plain list carries no trim
    counts = {comp: int(run.dataset[comp].shape[0]) for comp in run.dataset.data_vars}
    start = int(pd.Timestamp(run.dataset.time.values[0]).value) if run.dataset.sizes.get("time") else None
    wrong = {comp: k for comp, k in counts.items() if k != plan["n"]}
    late = start is None or abs(start - plan["recorded_ns"]) > 0.5e9 / float(rate)
    if wrong or late:
        read = ", ".join(f"{comp} {k}" for comp, k in counts.items())
        raise ValueError(
            f"{site_name}: the EDL run from {Path(plan['files'][0]).name} was planned as {plan['n']} samples from "
            f"{_iso(plan['recorded_ns'])} but the reader returned {read} sample(s) from "
            f"{'nothing' if start is None else _iso(start)}: refused, as the run would be written as contiguous "
            f"across samples the reader did not return (workbench issue 76)")


def _test_run_note(group) -> str:
    """Return the run comment line naming the deployment test run left out at a run's first file, or ""."""
    first = min(group, key=lambda f: (file_start(f, "edl"), Path(f).suffix.upper()))
    if edl_record_start(first) is None:
        return ""
    from obspy import read

    traces = sorted(read(Path(first).as_posix(), headonly=True), key=lambda t: t.stats.starttime)
    when = lambda t: f"{pd.Timestamp(t.ns, unit='ns', tz='UTC'):%Y-%m-%dT%H%M%S.%f}"[:-5]  # noqa: E731
    left = ", ".join(f"{t.id} {t.stats.npts} samples {when(t.stats.starttime)} to {when(t.stats.endtime)}"
                     for t in traces[:-1])
    record = traces[-1]
    # one dot-free "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48): no clock times
    return (f"deployment_test_run: {len(traces) - 1} trace(s) of {Path(first).name} before the record left out as "
            f"the deployment test run ({left}), the run starts at the record {record.id} "
            f"{when(record.stats.starttime)} (workbench issue 76)")


def _trim_run_start(run, trim: int, note: str):
    """Return a run without its first `trim` samples, its time periods and comment updated.

    The run of an `EdlRun` whose first file overlaps the file before it
    (`_edl_plan`) starts with the samples that file already holds; they
    are left out here, so the earlier file's samples are kept.

    Args:
        run (RunTS): The run as read.
        trim (int): Samples to leave out.
        note (str): The line for the run comment (`_overlap_note`).

    Returns:
        RunTS: The run from sample `trim` on.
    """
    from mth5.timeseries import RunTS

    dataset = run.dataset.isel(time=slice(int(trim), None)).copy()
    times = pd.DatetimeIndex(dataset.coords["time"].values)
    t0 = pd.Timestamp(times[0], tz="UTC").isoformat()
    t1 = pd.Timestamp(times[-1], tz="UTC").isoformat()
    for comp in dataset.data_vars:
        dataset[comp].attrs = dict(dataset[comp].attrs, **{"time_period.start": t0, "time_period.end": t1})
    piece = RunTS()
    piece.station_metadata = run.station_metadata.copy()
    piece.run_metadata = run.run_metadata.copy()
    piece.run_metadata.time_period.start = t0
    piece.run_metadata.time_period.end = t1
    piece.filters = dict(run.filters)
    piece.dataset = dataset
    piece.run_metadata.comments.value = _append_comment(piece.run_metadata.comments, note)
    return piece


B423_HEADER_BYTES = 1024
B423_MIN_FILL = 0.01   # a site whose files hold under 1 % of their nominal length was written with no card space
B423_MIN_FILES_FOR_FILL = 10


def readable_b423(files: list[Path], sample_rate: float = 1000.0) -> tuple[list[Path], list[str]]:
    """Split B423 files into the readable ones and reasons for the rest.

    A logger that loses its card mid-record writes a file of the right
    length whose 1024-byte header block is all zero, and one whose card is
    already full writes files of a few seconds. Neither can be used, and
    one such file must not abort the site: it is left out here, with a
    reason, and the run splits at the gap it leaves.

    The fill test counts a file's records at the site's sample rate: a
    logger recording at 1 Hz (R05 on the Atlas survey, an instrument fault)
    writes 5400 records per 90-minute file, which at 1000 records a second
    would read as five seconds of data and be refused.

    Args:
        files (list[Path]): The site's B423 files in name order.
        sample_rate (float): The site's sample rate in Hz
            (`Survey.sample_rate_of`); 1000 for a LEMI-423 at its usual
            rate.

    Returns:
        tuple[list[Path], list[str]]: The files to read, and one line per
        file left out naming it and the reason.

    Raises:
        ValueError: If, over ten or more files, the median file holds under
            one percent of the interval between file names at the site's
            sample rate, which means the logger had no card space and there
            is no recording to ingest.
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
            detail = str(exc).split(": ", 1)[-1]
            skipped.append(f"{f.name}: {detail}" if "unreadable" in detail
                           else f"{f.name}: header unreadable ({detail})")
            continue
        keep.append(f)
    if len(keep) >= B423_MIN_FILES_FOR_FILL:
        epochs = sorted(int(f.stem) for f in keep if f.stem.isdigit())
        spacing = sorted(b - a for a, b in zip(epochs, epochs[1:]))
        if spacing:
            nominal = spacing[len(spacing) // 2]
            seconds = sorted((f.stat().st_size - B423_HEADER_BYTES) / record / float(sample_rate) for f in keep)
            fill = seconds[len(seconds) // 2] / nominal if nominal > 0 else 1.0
            if fill < B423_MIN_FILL:
                raise ValueError(
                    f"the B423 files are nearly empty (a median of {seconds[len(seconds) // 2]:.0f} s of data "
                    f"per file at {sample_rate:g} Hz, {nominal} s apart, over {len(keep)} files): the logger had "
                    f"no card space; there is no recording to ingest"
                )
    return keep, skipped


def _b423_run_ends(files: list[Path], diffs, nominal: int, rate: float) -> set[int]:
    """Find the B423 files after which a run must end, from their record counts.

    mt-io's reader joins a run's files end to end and stamps every sample
    from the first file's start, so a file holding fewer records than the
    span to the next file name (a copy cut short, a card fault) stamps every
    later sample of the run early by the samples it lacks; a partial record
    at the end of a file is dropped by the reader without a message. A file
    at the nominal spacing whose record count, (size - 1024) // 30, is not
    the span times `rate`, or whose data are not a whole number of records,
    ends its run, with a WARNING naming it and the samples missing. A
    partial record in a file that ends its run anyway (a gap follows, or it
    is the last file) is reported too.

    Args:
        files (list of Path): B423 files in start order.
        diffs (array of int): Spacing of the file names in s, one fewer
            than `files`.
        nominal (int): The nominal spacing in s (`_group_contiguous`).
        rate (float): The site's sample rate in Hz.

    Returns:
        set of int: Indices into `files` of the files that end a run.
    """
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    record = int(Read_Lemi_Data.binary_format.itemsize)
    ends: set[int] = set()
    for k, f in enumerate(files):
        n, partial = divmod(f.stat().st_size - B423_HEADER_BYTES, record)
        tail = f" and a partial record of {partial} bytes" if partial else ""
        if k < len(diffs) and int(diffs[k]) == nominal:
            span = int(round(int(diffs[k]) * float(rate)))
            if n != span or partial:
                ends.add(k)
                short = (f"{span - n} samples missing" if n < span else
                         f"{n - span} samples more than the span" if n > span else "no sample missing")
                logger.warning(f"{f.parent.name}/{f.name}: {n} records{tail} where the {int(diffs[k])} s to the "
                               f"next file at {float(rate):g} Hz need {span} ({short}): the run ends after it")
        elif partial:
            logger.warning(f"{f.parent.name}/{f.name}: {n} records{tail} (the partial record is dropped)")
    return ends


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
    (`_edl_plan`): an `EdlRun` each, whose `trim` is the samples its first
    file shares with the file before it (a restart file), left out at
    ingest; a stamp recorded while the site's recorder.msg had a data
    channel at another rate (a set-up at 100 s/s) is left out first
    (`_other_rate_stamps`). Given a LEMI-423 site's `rate`, a file whose
    record count disagrees with the span to the next file, or whose data
    are not a whole number of records, also ends its run
    (`_b423_run_ends`): read on as one stretch, a file cut short would
    stamp every later sample of the run early.

    Args:
        files (list of Path): Data files in start order.
        max_run_files (int, optional): Most files per LEMI-423 run.
        instrument (str): Key of `INSTRUMENTS`.
        rate (float, optional): Sample rate in Hz of an EDL or LEMI-423
            site; without it a LEMI-423 run follows the spacing alone.

    Returns:
        list of list of Path: The runs.
    """
    if instrument != "lemi423":
        stamps = [file_start(f, instrument) for f in files]
        drop = _incomplete_stamps(files, stamps) if instrument == "edl" else set()
        if instrument == "edl" and rate:
            runs, trims = _edl_plan(files, stamps, drop, float(rate),
                                    suspect=_other_rate_stamps(files, stamps, float(rate)))
            out = []
            for ids in runs:
                group = EdlRun(f for f, s in zip(files, stamps) if s in ids)
                first = min(ids)
                if first in trims:
                    group.trim = trims[first][0]
                    group.overlaps = next(f for f, s in zip(files, stamps) if s == trims[first][1]).stem
                out.append(group)
            return out
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
    ends = _b423_run_ends(files, diffs, nominal, rate) if rate else set()

    groups: list[list[Path]] = [[files[0]]]
    for k, (fn, diff) in enumerate(zip(files[1:], diffs)):
        full = max_run_files is not None and len(groups[-1]) >= max_run_files
        if diff == nominal and not full and k not in ends:
            groups[-1].append(fn)
        else:
            groups.append([fn])
    return groups


def _run_levels(run, site_name: str, run_id: str, rails: dict | None = None) -> list[dict]:
    """Measure the raw DC level of a run's electric and magnetic channels.

    Each channel's samples in memory are measured on a subsample of at most
    `mt_workbench.dclevel.SAMPLE_SECONDS` of samples (`mt_workbench.dclevel.channel_stats`),
    the samples the archive stores for the run.

    Args:
        run (RunTS): The run as it is written.
        site_name (str): Site name.
        run_id (str): The run's id in the archive.
        rails (dict, optional): {channel: absolute rail} for the channels
            measured against one (a Phoenix run, `_phoenix_rails`, in V; an
            MTU-5A run, `mt_workbench.mtu5a.rails`, in counts); the others
            take the record's own.

    Returns:
        list[dict]: One row per channel with samples: ``site``, ``run``,
        ``channel``, ``type``, ``sample_rate`` and the `channel_stats`
        values.
    """
    rows = []
    for comp in list(run.dataset):
        channel = run.dataset[comp]
        kind = channel_type(comp, channel)
        if kind is None or channel.shape[0] == 0:
            continue
        fs = float(run.sample_rate)
        rail = (rails or {}).get(comp)
        stats = channel_stats(np.asarray(channel.data), fs) if rail is None else \
            channel_stats(np.asarray(channel.data), fs, rail=rail)
        rows.append(dict(site=site_name, run=run_id, channel=comp, type=kind, sample_rate=fs, **stats))
    return rows


def _phoenix_rails(rec, files: dict, swapped: bool = False, swapped_e: bool = False) -> dict[str, float]:
    """Return each channel's absolute rail for a Phoenix run's dc level.

    The rail is `mt_workbench.dclevel.RAIL_LEVEL` x the channel's input range
    from the header of its first file (`mt_workbench.phoenix.input_range_v`),
    keyed by the stored channel name; with `swapped` (swap_h) hx and hy
    exchange theirs with their samples, and with `swapped_e` (swap_e) each
    input's rail is keyed by the name its samples are stored under
    (`mt_workbench.phoenix.component_of`: the E2 input's under ex).

    Args:
        rec (PhoenixRecording): The recording.
        files (dict): Channel folder index to its files (or bursts) of the
            run, the first one's header read.
        swapped (bool): Whether hx and hy were exchanged.
        swapped_e (bool): Whether the site declares `swap_e`.

    Returns:
        dict[str, float]: {channel: rail in V}.
    """
    from .phoenix import component_of, input_range_v

    rails = {}
    for folder, items in files.items():
        first = items[0] if isinstance(items, (list, tuple)) else items
        tag = rec.tags[folder]
        rails[component_of(tag, swapped_e)] = RAIL_LEVEL * input_range_v(first.path)
    if swapped and {"hx", "hy"} <= set(rails):
        rails["hx"], rails["hy"] = rails["hy"], rails["hx"]
    return rails


def _record_levels(run_groups: dict, rows: list[dict], site_name: str, unit: str = "counts") -> None:
    """Classify a site's channel levels together and record them in the run comments.

    Each run's classified channels (`mt_workbench.dclevel.level_note`) follow its
    comment after "; ", and the run's metadata is written again. The flagged
    channel runs go to the log.

    Args:
        run_groups (dict): {run id: the mth5 run group written}.
        rows (list[dict]): `_run_levels` of every run, classified in place.
        site_name (str): Site name.
        unit (str): The unit of the stored samples. For "counts" a channel
            above `mt_workbench.dclevel.THRESHOLD_COUNTS` is an open input; for
            "V" (a Phoenix archive) that threshold, which is in LEMI counts,
            does not apply and only the ratio to the channel type's typical
            level and the rail share act.
    """
    if not rows:
        return
    classify(rows, threshold_counts=THRESHOLD_COUNTS if unit == "counts" else float("inf"))
    for run_id, run_group in run_groups.items():
        mine = [r for r in rows if r["run"] == run_id]
        if not mine:
            continue
        prior = _run_comment(run_group)
        note = level_note(mine, unit=unit)
        run_group.metadata.comments.value = f"{prior}; {note}" if prior else note
        run_group.write_metadata()
    flagged = [r for r in rows if r["verdict"] != OK]
    for row in flagged:
        logger.warning(flag_line(row, unit=unit))
    logger.info(f"{site_name}: dc level of {len(rows)} channel run(s) recorded in the run comments, "
                f"{len(flagged)} flagged")


# start of the line `ingest_site` writes into the station's provenance.comments
# for a site declared `h_from`, followed by the neighbour's name and ","
_H_FROM_PREFIX = "h_from: hx and hy of "
# the least share of the local's recorded samples the neighbour must cover
H_FROM_MIN_COVER = 0.5
# the largest offset between the two sites' sample grids, in samples: both are
# GPS timed at the same rate, so their grids coincide
_GRID_TOLERANCE = 1e-3


# keys of a site's own survey.yaml entry that belong to one recorder: refused on a site of another
_PHOENIX_ONLY_KEYS = ("recording", "calibration_dir", "coil_hx", "coil_hy", "coil_hz")
_NOT_PHOENIX_KEYS = ("h_scale", "sensor_type", "electric_gain", "calibration_fn", "h_from")
# the Orange Box keys, and the keys of other recorders an Orange Box
# site may not set: its fluxgates need no coil response, and its chain comes from the two full scales
_ORANGEBOX_ONLY_KEYS = ("electric_full_scale_uv", "magnetic_full_scale_nt", "clock_timezone", "clock_drift_s",
                        "time_base")
# (`h_from` is allowed: an Orange Box neighbour's hx and hy replace the local's,
# `_h_from_plan_orangebox`)
_NOT_ORANGEBOX_KEYS = ("h_scale", "sensor_type", "electric_gain", "calibration_fn", *_PHOENIX_ONLY_KEYS)


def _check_instrument_keys(survey: Survey, site: SiteConfig, instrument: str) -> None:
    """Refuse a key in a site's own entry that its recorder does not use.

    A `defaults:` value is left alone, so a survey of several recorders
    may keep one recorder's defaults.

    Args:
        survey (Survey): The survey.
        site (SiteConfig): Site settings.
        instrument (str): The site's instrument.

    Raises:
        ValueError: Naming the key, for `_NOT_PHOENIX_KEYS` on a Phoenix
            site (`h_scale`, `sensor_type`, `electric_gain`,
            `calibration_fn`, `h_from`), both lists on an MTU-5A site
            (the mtu5a reader uses none of them), `_PHOENIX_ONLY_KEYS` on any
            other, `_ORANGEBOX_ONLY_KEYS` (the full scales, `clock_timezone`,
            `clock_drift_s`, `time_base`) on any but an Orange Box site, and
            `_NOT_ORANGEBOX_KEYS` on an Orange Box site.
    """
    own = (survey.config.get("sites") or {}).get(survey.raw_site(site.name)) or {}
    label = INSTRUMENTS[instrument]["label"]
    if instrument == "orangebox":
        found = [k for k in _NOT_ORANGEBOX_KEYS if k in own]
        if found:
            raise ValueError(f"{site.name}: {', '.join(found)} in its survey.yaml entry, and the site is {label}: "
                             f"a LEMI, EDL or Phoenix setting (its fluxgates need no coil response, its chain comes "
                             f"from electric_full_scale_uv and magnetic_full_scale_nt); remove the key")
        return
    refused = {"phoenix": _NOT_PHOENIX_KEYS, "mtu5a": _PHOENIX_ONLY_KEYS + _NOT_PHOENIX_KEYS}.get(
        instrument, _PHOENIX_ONLY_KEYS)
    found = [k for k in refused if k in own]
    if found:
        what = {"phoenix": "a LEMI or EDL setting", "mtu5a": "a setting the MTU-5A reader does not use"}.get(
            instrument, "a Phoenix setting")
        raise ValueError(f"{site.name}: {', '.join(found)} in its survey.yaml entry, and the site is {label}: "
                         f"{what}; remove the key")
    found = [k for k in _ORANGEBOX_ONLY_KEYS if k in own]
    if found:
        raise ValueError(f"{site.name}: {', '.join(found)} in its survey.yaml entry, and the site is {label}: "
                         f"an Orange Box setting; remove the key")


def _orangebox_scales(site: SiteConfig) -> None:
    """Refuse an Orange Box site without both full scales, before anything is written.

    mt-io's reader would take 100000 uV and 70000 nT without them, and the
    electric scale alone moves the apparent resistivity by a factor 16
    between the two known boxes (docs/upstream_issues.md 13 and 14).

    Args:
        site (SiteConfig): Site settings, `defaults:` merged.

    Raises:
        ValueError: Naming each missing key and its known values.
    """
    from .orangebox import ELECTRIC_FULL_SCALES_UV, MAGNETIC_FULL_SCALES_NT

    missing = []
    if site.electric_full_scale_uv is None:
        missing.append(f"electric_full_scale_uv (uV: {' or '.join(f'{v:.0f}' for v in ELECTRIC_FULL_SCALES_UV)}, "
                       f"the +/-2.5 V boxes before July 2010 or the +/-10 V ones after)")
    if site.magnetic_full_scale_nt is None:
        missing.append(f"magnetic_full_scale_nt (nT: {' or '.join(f'{v:.0f}' for v in MAGNETIC_FULL_SCALES_NT)}, "
                       f"the Bartington sensor's)")
    if missing:
        raise ValueError(f"{site.name}: an Orange Box site needs " + " and ".join(missing)
                         + " in its survey.yaml entry or defaults:")


def _orangebox_units(site: SiteConfig, site_dir: Path, start, end) -> list[tuple]:
    """Plan an Orange Box site's runs and their time base.

    The site's files (`record_files`, empty ones left out with a warning)
    are split into runs at stamp gaps (`mt_workbench.orangebox.plan_runs`),
    and the deployment's time base is worked out over all of them
    (`mt_workbench.orangebox.time_base`, with the site's `clock_timezone`,
    `clock_drift_s` and `time_base`) before the `start`/`end` window keeps the runs
    that overlap it, whole.

    Args:
        site (SiteConfig): Site settings.
        site_dir (Path): Site folder.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.

    Returns:
        list of tuple: (OrangeRun, its time base dict) per run kept.

    Raises:
        FileNotFoundError: If the folder holds no Orange Box file with a
            header.
        ValueError: If no run overlaps the window.
    """
    from .orangebox import orange_files, plan_runs, time_base

    listed, _skipped = orange_files(record_files(Path(site_dir), "orangebox"))
    if not listed:
        raise FileNotFoundError(f"no {INSTRUMENTS['orangebox']['label']} files with a header under {site_dir}")
    runs = plan_runs(listed)
    bases = time_base(runs, site.clock_timezone, site.clock_drift_s, site.time_base)
    t0 = pd.Timestamp(start, tz="UTC").value if start is not None else -np.inf
    t1 = pd.Timestamp(end, tz="UTC").value if end is not None else np.inf
    kept = [(run, base) for run, base in zip(runs, bases)
            if base["start_ns"] < t1 and base["start_ns"] + run.records / base["fs_true"] * 1e9 > t0]
    if not kept:
        raise ValueError(f"no Orange Box run in {site_dir} overlaps [{start}, {end})")
    return kept


def _read_orangebox_run(group: tuple, site: SiteConfig):
    """Read one Orange Box run (`_orangebox_units`) onto the UTC grid (`mt_workbench.orangebox.read_orangebox_run`)."""
    from .orangebox import read_orangebox_run

    run_plan, base = group
    return read_orangebox_run(run_plan, base, site, site.clock_timezone)


def archive_time_base(path: Path, site_name: str) -> dict[str, dict]:
    """Return the Orange Box time base an archive's ingest recorded, per run.

    The sibling of `archive_clock_offset`: each run comment's
    "orangebox_time_base:" line (`mt_workbench.orangebox.time_base_note`) read
    back by `mt_workbench.orangebox.parse_time_base_note`.

    Args:
        path (Path): The archive.
        site_name (str): The station in it.

    Returns:
        dict: Run id to its time base (clock_timezone, clock_drift_s,
        drift_recorded, t_rtc_s, n, fs_true_hz, grid_first, grid_last, ...);
        empty for an archive of another recorder.
    """
    from .orangebox import parse_time_base_note

    out = {}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        station = m.get_station(site_name, survey=survey_name)
        for run_id in station.groups_list:
            if run_id in ("Transfer_Functions", "Fourier_Coefficients", "Features"):
                continue
            found = parse_time_base_note(str(station.get_run(run_id).metadata.comments.value or ""))
            if found is not None:
                out[run_id] = found
    finally:
        m.close_mth5()
    return out


def _calibration_dir(survey: Survey, site: SiteConfig) -> Path:
    """Resolve a Phoenix site's `calibration_dir` like `calibration_fn` (`_calibration_path`).

    Raises:
        ValueError: If the site declares none.
        FileNotFoundError: If the folder does not exist.
    """
    if not site.calibration_dir:
        raise ValueError(f"{site.name}: a Phoenix site needs calibration_dir, the folder of the receivers' "
                         f"<receiver>_*.rxcal.json and the coils' <serial>_*.scal.json files")
    folder = Path(site.calibration_dir)
    if not folder.is_absolute():
        folder = next((c for c in (survey.config_dir / folder, survey.data_root / folder) if c.is_dir()),
                      survey.data_root / folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"{site.name}: calibration_dir {folder} not found")
    return folder


def _phoenix_units(survey: Survey, site: SiteConfig, site_dir: Path, rate: float, start, end) -> list[tuple]:
    """List a Phoenix site's runs: one or more per recording of continuous files.

    The continuous type is chosen by the site's rate (`.td_150` at 150 Hz,
    `.td_30` at 30 Hz); a recording with one continuous type takes that
    one, and `mt_workbench.phoenix.plan_runs` refuses a header rate other than
    the site's. An empty file is skipped and a sequence that one channel
    folder lacks becomes a run boundary for every channel (`plan_runs`,
    upstream issues 76 and 77). Several recordings in one site folder must
    have the same receiver, channel map, coils and dipoles, because
    processing takes the first run's chain for every run.

    Args:
        survey (Survey): The survey.
        site (SiteConfig): Site settings.
        site_dir (Path): The site folder.
        rate (float): `Survey.sample_rate_of` the site.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.

    Returns:
        list of tuple: ``(PhoenixRecording, RunPlan)`` per run, in time order.

    Raises:
        ValueError: If a recording is of another receiver than the site's
            `serial`, has no continuous files of a type the rate selects,
            the recordings differ in receiver, map, coils or dipoles, or
            `plan_runs` refuses.
    """
    from .phoenix import find_recordings, open_recording, plan_runs, recording_files

    units, layouts = [], {}
    for folder in find_recordings(site_dir, site.recording):
        rec = open_recording(folder)
        if site.serial and str(site.serial) != rec.receiver:
            raise ValueError(f"{site.name}: {folder} is receiver {rec.receiver}, and survey.yaml declares serial "
                             f"{site.serial}")
        by_rate = {150.0: ".td_150", 30.0: ".td_30"}
        present = [s for s in (".td_150", ".td_30") if any(any((folder / str(c)).glob(f"*{s}")) for c in rec.tags)]
        suffix = by_rate.get(float(rate)) if by_rate.get(float(rate)) in present else (
            present[0] if len(present) == 1 else None)
        if suffix is None:
            raise ValueError(f"{site.name}: no continuous Phoenix files for {rate:g} Hz in {folder} (types "
                             f"{present or 'none'})")
        layouts[folder] = (rec.receiver, tuple(sorted(rec.tags.items())),
                           tuple((rec.chan(t).get("serial"), rec.chan(t).get("length1"), rec.chan(t).get("length2"))
                                 for t in sorted(rec.tags.values())))
        try:
            plans = plan_runs(recording_files(rec, suffix), float(rate), start, end)
        except ValueError as exc:
            if "overlaps" in str(exc) and (start or end):
                continue
            raise ValueError(f"{site.name}: {exc}") from None
        units += [(rec, plan) for plan in plans]
    if len(set(layouts.values())) > 1:
        raise ValueError(f"{site.name}: its recordings differ in receiver, channel map, coils or dipoles "
                         f"({', '.join(f'{k.name}: {v}' for k, v in layouts.items())}): give each its own site "
                         f"entry with `recording:`")
    if not units:
        raise ValueError(f"{site.name}: no Phoenix file overlaps [{start}, {end})")
    return sorted(units, key=lambda u: u[1].start_s)


def _calibration_path(survey: Survey, calibration_fn: str) -> Path:
    """Resolve a site's `calibration_fn`.

    A relative path resolves against the survey folder first (sensor files
    kept with the config), then the raw-data root (sensor files kept with
    the data).

    Args:
        survey (Survey): The survey.
        calibration_fn (str): The declared path.

    Returns:
        Path: The coil response file.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    cal = Path(calibration_fn)
    if not cal.is_absolute():
        cal = next((c for c in (survey.config_dir / cal, survey.data_root / cal) if c.exists()),
                   survey.data_root / cal)
    if not cal.exists():
        raise FileNotFoundError(f"coil calibration file not found: {cal}")
    return cal


def _b423_records(path: Path) -> int:
    """Return the number of whole records in a B423 file, as the reader reads them."""
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    return max(0, (Path(path).stat().st_size - B423_HEADER_BYTES) // int(Read_Lemi_Data.binary_format.itemsize))


def _b423_first_ns(path: Path) -> int:
    """Return the recorded time of a B423 file's first record, in ns since the epoch (UTC)."""
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    first = np.fromfile(path, dtype=Read_Lemi_Data.binary_format, count=1, offset=B423_HEADER_BYTES)
    if first.size == 0:
        raise ValueError(f"{Path(path).name}: no record")
    return (int(first["time"][0]) * 1000 + int(first["tick"][0])) * 1_000_000


def _run_spans(groups: list[list[Path]], offset_s: float) -> list[dict]:
    """Describe the runs `ingest_site` builds from B423 file groups, without reading the samples.

    `read_lemi423` stamps a run's samples from its first record's time at
    the sample rate, so a run is its first record's time and its record
    count; `ingest_site` checks the reader agrees (`_h_from_pieces`).

    Args:
        groups (list of list of Path): `_group_contiguous` of a site.
        offset_s (float): The site's `clock_offset_s`.

    Returns:
        list of dict: Per run, ``files``, ``cum`` (the record index at which
        each file starts, then the total), ``n`` (records), ``recorded_ns``
        (the first record's recorded time) and ``start_ns`` (the archive's
        time of it, the offset added), in ns.
    """
    shift = int(round(offset_s * 1e9))
    spans = []
    for files in groups:
        cum = np.concatenate([[0], np.cumsum([_b423_records(f) for f in files])]).astype("int64")
        recorded = _b423_first_ns(files[0])
        spans.append({"files": files, "cum": cum, "n": int(cum[-1]), "recorded_ns": recorded,
                      "start_ns": recorded + shift})
    return spans


def _edl_run_spans(groups: list[list[Path]], offset_s: float, rate: float) -> list[dict]:
    """Describe the runs `ingest_site` builds from EDL file groups, without reading the samples.

    mt-io's EDL reader stamps a run's samples from its first file's stamp
    at the sample rate, and a run of an `EdlRun` whose first file overlaps
    the file before it loses its first `trim` samples (`_trim_run_start`),
    so a run is its first stamp plus the trim and its samples less the trim
    (`count_samples` of one channel's files, which `_edl_plan` has made
    equal across channels). A first file holding the deployment test run
    before the record starts its run at the record (`edl_record_start`).

    Args:
        groups (list of list of Path): `_group_contiguous` of an EDL site.
        offset_s (float): The site's `clock_offset_s`.
        rate (float): The site's sample rate in Hz.

    Returns:
        list of dict: Per run, ``files`` (one channel's, in stamp order),
        ``group`` (the run's files), ``trim``, ``n`` (samples),
        ``recorded_ns`` and ``start_ns`` (the archive's time of the first
        sample kept, the offset added), in ns.
    """
    from mt_io.uoa.pr624 import count_samples

    shift = int(round(offset_s * 1e9))
    spans = []
    for group in groups:
        first_suffix = Path(group[0]).suffix.upper()
        files = sorted((f for f in group if Path(f).suffix.upper() == first_suffix), key=lambda f: file_start(f, "edl"))
        trim = int(getattr(group, "trim", 0))
        n = sum(count_samples(f) for f in files) - trim
        record = edl_record_start(files[0])  # a first file holding the deployment test run: the record's start
        begin = int(file_start(files[0], "edl")) * 1_000_000_000 if record is None else record
        recorded = begin + int(round(trim * 1e9 / float(rate)))
        spans.append({"files": files, "group": group, "trim": trim, "n": int(n), "recorded_ns": recorded,
                      "start_ns": recorded + shift})
    return spans


def _iso(ns: int) -> str:
    """Return a time in ns since the epoch as an ISO string in UTC."""
    return pd.Timestamp(int(ns), unit="ns", tz="UTC").isoformat()


def _position(site: SiteConfig, first_file: Path) -> tuple[float, float]:
    """Return a site's latitude and longitude: its survey.yaml values, else its first B423 header's."""
    if site.latitude is not None and site.longitude is not None:
        return float(site.latitude), float(site.longitude)
    from mt_io.lemi.lemi423 import Read_Lemi_Header

    header = Read_Lemi_Header(first_file).read()
    return float(header["latitude"]), float(header["longitude"])


def _h_from_plan(survey: Survey, site: SiteConfig, groups: list[list[Path]], rate: float,
                 max_run_files: int | None) -> dict:
    """Match a site's runs to the neighbour it takes hx and hy from (`SiteConfig.h_from`).

    The neighbour's raw B423 files are selected, screened and grouped into
    runs as its own `ingest_site` does them (`readable_b423`,
    `_group_contiguous` with `max_run_files`), and every run of both sites
    is placed on the time axis its archive has (`_run_spans`: the first
    record's GPS stamp plus the site's own `clock_offset_s`, then one
    sample per 1/`rate`). Each local run is matched to the neighbour's runs
    it overlaps: the overlap is a piece, which becomes one run of the
    archive; a local run that overlaps none is left out, and one that
    overlaps a neighbour's run in part is cut to the overlap. Only the
    file headers and first records are read.

    Args:
        survey (Survey): The survey.
        site (SiteConfig): The local site's settings, `h_from` set.
        groups (list of list of Path): The local's `_group_contiguous`.
        rate (float): The sample rate in Hz of both sites.
        max_run_files (int or None): The ingest's cap on files per run.

    Returns:
        dict: ``neighbour`` (its SiteConfig), ``calibration`` (its coil
        response file or None), ``local`` and ``theirs`` (`_run_spans`),
        ``pieces`` (per local run, a list of ``(i0, i1, g, j0)``: local
        samples i0..i1-1 are the neighbour's run g from sample j0),
        ``cover`` (the share of local samples covered) and ``distance_m``.

    Raises:
        ValueError: If either site is not LEMI-423, the neighbour has no
            raw folder or no readable file, the two sample grids are offset
            by a fraction of a sample, or the neighbour covers under
            `H_FROM_MIN_COVER` of the local's samples.
    """
    other = site.h_from
    neighbour = survey.site(other)  # Survey.site has checked the pair's declarations
    kinds = {survey.instrument_of(name) for name in (site.name, other)}
    if len(kinds) != 1 or not kinds <= {"lemi423", "edl", "orangebox"}:
        raise ValueError(f"{site.name}: h_from {other}: {site.name} is {survey.instrument_of(site.name)} and "
                         f"{other} {survey.instrument_of(other)}; h_from reads two LEMI-423, two EDL or two "
                         f"Orange Box sites")
    dirs = survey.site_dirs()
    if other not in dirs:
        raise ValueError(f"{site.name}: h_from {other}: no folder of raw files for {other} under {survey.data_root}")
    if kinds == {"edl"}:
        return _h_from_plan_edl(survey, site, neighbour, dirs[other], groups, rate)
    if kinds == {"orangebox"}:
        return _h_from_plan_orangebox(survey, site, neighbour, dirs[other], groups, rate)
    try:
        nfiles, nskipped = readable_b423(select_files(dirs[other], None, None, "lemi423"),
                                         sample_rate=survey.sample_rate_of(other))
    except ValueError as exc:
        raise ValueError(f"{site.name}: h_from {other}: {exc}") from None
    for line in nskipped:
        logger.warning(f"{site.name}: h_from {other}: skipping {line}, as {other}'s own ingest does")
    if not nfiles:
        raise ValueError(f"{site.name}: h_from {other}: none of {other}'s B423 files can be read")
    ngroups = _group_contiguous(nfiles, max_run_files, "lemi423", rate=survey.sample_rate_of(other))
    local = _run_spans(groups, site.clock_offset_s)
    theirs = _run_spans(ngroups, neighbour.clock_offset_s)
    step = 1e9 / float(rate)
    pieces = []
    for mine in local:
        found = []
        for g, run in enumerate(theirs):
            lag = (run["start_ns"] - mine["start_ns"]) / step
            k = int(round(lag))
            lo, hi = max(0, k), min(mine["n"], k + run["n"])
            if hi <= lo:
                continue
            if abs(lag - k) > _GRID_TOLERANCE:
                raise ValueError(
                    f"{site.name}: h_from {other}: {other}'s run from {run['files'][0].name} sits {lag - k:+.4f} "
                    f"samples off {site.name}'s sample grid (run from {mine['files'][0].name}), after the "
                    f"clock offsets {site.clock_offset_s!r} and {neighbour.clock_offset_s!r} s: the two are not "
                    f"on one GPS time base; the samples cannot be taken one for one")
            found.append((lo, hi, g, lo - k))
        pieces.append(sorted(found))
    total = sum(mine["n"] for mine in local)
    covered = sum(hi - lo for found in pieces for lo, hi, _g, _j in found)
    if covered < H_FROM_MIN_COVER * total:
        raise ValueError(
            f"{site.name}: h_from {other}: {other} covers {covered} of {site.name}'s {total} samples "
            f"({covered / max(total, 1):.1%}), under the {H_FROM_MIN_COVER:.0%} h_from needs; name a neighbour "
            f"that recorded over the same hours")
    calibration = None
    if neighbour.calibration_fn:
        calibration = _calibration_path(survey, neighbour.calibration_fn)
    else:
        logger.warning(f"{site.name}: h_from {other}: {other} has no calibration_fn, so the borrowed hx and hy "
                       f"lack a coil response and TFs will be wrong")
    here, there = _position(site, groups[0][0]), _position(neighbour, nfiles[0])
    return {"neighbour": neighbour, "calibration": calibration, "local": local, "theirs": theirs,
            "pieces": pieces, "cover": covered / total, "distance_m": 1000.0 * distance_km(*here, *there)}


def _h_from_cover(site: SiteConfig, local: list[dict], theirs: list[dict], rate: float, clock: float) -> tuple:
    """Match each local run to the neighbour's runs it overlaps; return (pieces, share covered).

    Raises:
        ValueError: If a neighbour's run sits off the local's sample grid, or
            it covers under `H_FROM_MIN_COVER` of the local's samples.
    """
    other = site.h_from
    step = 1e9 / float(rate)
    pieces = []
    for mine in local:
        found = []
        for g, run in enumerate(theirs):
            lag = (run["start_ns"] - mine["start_ns"]) / step
            k = int(round(lag))
            lo, hi = max(0, k), min(mine["n"], k + run["n"])
            if hi <= lo:
                continue
            if abs(lag - k) > _GRID_TOLERANCE:
                raise ValueError(
                    f"{site.name}: h_from {other}: {other}'s run from {run['files'][0].name} sits {lag - k:+.4f} "
                    f"samples off {site.name}'s sample grid (run from {mine['files'][0].name}), after the "
                    f"clock offsets {site.clock_offset_s!r} and {clock!r} s: the two are not on one GPS time "
                    f"base; the samples cannot be taken one for one")
            found.append((lo, hi, g, lo - k))
        pieces.append(sorted(found))
    total = sum(mine["n"] for mine in local)
    covered = sum(hi - lo for found in pieces for lo, hi, _g, _j in found)
    if covered < H_FROM_MIN_COVER * total:
        raise ValueError(
            f"{site.name}: h_from {other}: {other} covers {covered} of {site.name}'s {total} samples "
            f"({covered / max(total, 1):.1%}), under the {H_FROM_MIN_COVER:.0%} h_from needs; name a neighbour "
            f"that recorded over the same hours")
    return pieces, covered / total


def _h_from_plan_edl(survey: Survey, site: SiteConfig, neighbour: SiteConfig, folder: Path,
                     groups: list[list[Path]], rate: float) -> dict:
    """`_h_from_plan` for two EDL sites: the neighbour's files grouped as its own ingest groups them.

    The neighbour's runs come from `_group_contiguous` at its own rate
    (`edl_sample_rate`), with its overlap trims, and both sites' runs are
    placed by `_edl_run_spans`; a neighbour at another rate is refused.
    The neighbour's coil table is used when its `sensor_type` is lemi120
    (`calibration_fn`); a fluxgate's chain is coefficients only.

    Returns:
        dict: As `_h_from_plan`, with ``instrument`` "edl", ``folder``
        (the neighbour's raw folder), ``sensor`` and an empty ``cache``
        that `_read_borrowed` fills with each neighbour run it reads.
    """
    other = site.h_from
    theirs_rate = edl_sample_rate(folder)
    if theirs_rate is None or abs(float(theirs_rate) - float(rate)) > 1e-9 * float(rate):
        raise ValueError(f"{site.name}: h_from {other}: {other} records at {theirs_rate} Hz and {site.name} at "
                         f"{rate:g} Hz; the samples are taken one for one")
    nfiles = select_files(folder, None, None, "edl")
    ngroups = _group_contiguous(nfiles, None, "edl", rate=float(rate))
    local = _edl_run_spans(groups, site.clock_offset_s, rate)
    theirs = _edl_run_spans(ngroups, neighbour.clock_offset_s, rate)
    pieces, cover = _h_from_cover(site, local, theirs, rate, neighbour.clock_offset_s)
    sensor = edl_sensor(neighbour)
    calibration = None
    if sensor == "lemi120" and neighbour.calibration_fn:
        calibration = _calibration_path(survey, neighbour.calibration_fn)
    here, there = _position(site, groups[0][0]), _position(neighbour, nfiles[0])
    return {"neighbour": neighbour, "calibration": calibration, "local": local, "theirs": theirs,
            "pieces": pieces, "cover": cover, "distance_m": 1000.0 * distance_km(*here, *there),
            "instrument": "edl", "folder": folder, "sensor": sensor, "cache": {}}


def _orangebox_run_spans(units: list[tuple], offset_s: float) -> list[dict]:
    """Describe the runs `ingest_site` builds from Orange Box units, without reading the samples.

    `mt_workbench.orangebox.read_orangebox_run` puts each run on the UTC
    10 Hz grid from its time base, so a run is its first grid sample and
    its number of grid samples (`mt_workbench.orangebox.grid_span`);
    `_h_from_pieces` checks the read run agrees.

    Args:
        units (list of tuple): `_orangebox_units` of a site.
        offset_s (float): The site's `clock_offset_s`.

    Returns:
        list of dict: Per run, ``files`` (its paths), ``unit`` (the
        `_orangebox_units` entry), ``n`` (grid samples), ``recorded_ns``
        (the first grid sample's time) and ``start_ns`` (the archive's time
        of it, the offset added), in ns.
    """
    from .orangebox import grid_span

    shift = int(round(offset_s * 1e9))
    spans = []
    for unit in units:
        run_plan, base = unit
        first, n = grid_span(run_plan, base)
        spans.append({"files": list(run_plan.paths), "unit": unit, "n": int(n), "recorded_ns": int(first),
                      "start_ns": int(first) + shift})
    return spans


def _h_from_plan_orangebox(survey: Survey, site: SiteConfig, neighbour: SiteConfig, folder: Path,
                           units: list[tuple], rate: float) -> dict:
    """`_h_from_plan` for two Orange Box sites: the neighbour's runs on the same UTC grid.

    Both sites' runs are placed where their ingest puts them
    (`_orangebox_units` over the neighbour's whole record with its own
    `clock_timezone` and `clock_drift_s`, then `_orangebox_run_spans`), so
    the borrow is a grid alignment: local grid sample i is the neighbour's
    grid sample at the same UTC time. Fluxgates need no coil response, so
    ``calibration`` is None and ``sensor`` "fluxgate". The local's own hx
    and hy are replaced by the neighbour's (`ingest_site` drops them before
    the borrow); its ex, ey and hz are kept.

    Returns:
        dict: As `_h_from_plan`, with ``instrument`` "orangebox" and an
        empty ``cache`` that `_read_borrowed_orangebox` fills with each
        neighbour run it reads.
    """
    _orangebox_scales(neighbour)
    theirs_units = _orangebox_units(neighbour, Path(folder), None, None)
    local = _orangebox_run_spans(units, site.clock_offset_s)
    theirs = _orangebox_run_spans(theirs_units, neighbour.clock_offset_s)
    pieces, cover = _h_from_cover(site, local, theirs, rate, neighbour.clock_offset_s)
    here = (float(site.latitude), float(site.longitude))
    there = (float(neighbour.latitude), float(neighbour.longitude))
    return {"neighbour": neighbour, "calibration": None, "local": local, "theirs": theirs,
            "pieces": pieces, "cover": cover, "distance_m": 1000.0 * distance_km(*here, *there),
            "instrument": "orangebox", "sensor": "fluxgate", "cache": {}}


def _read_borrowed_orangebox(plan: dict, g: int, j0: int, j1: int, rate: float, tag: str) -> tuple[dict, str]:
    """`_read_borrowed` for an Orange Box neighbour: its run g read whole once, its own steps applied, then sliced.

    The neighbour's run is read onto the grid as its own ingest reads it
    (`_read_orangebox_run`), with its `_keep_channels`, `_swap_h`,
    `_flip_h` and `_rot_h`, so hx and hy hold what its own archive holds;
    the result is kept in ``plan["cache"]`` for the other pieces of the
    same run.

    Raises:
        ValueError: If the read's rate, first grid time or length differ
            from the plan.
    """
    neighbour, run = plan["neighbour"], plan["theirs"][g]
    if g not in plan["cache"]:
        plan["cache"].clear()  # one neighbour run in memory at a time
        nrun = _read_orangebox_run(run["unit"], neighbour)
        if abs(float(nrun.sample_rate) - float(rate)) > 1e-9 * float(rate):
            raise ValueError(f"{tag}: h_from {neighbour.name}: {run['files'][0].name} reads at "
                             f"{nrun.sample_rate:g} Hz, not {rate:g} Hz")
        got = int(pd.DatetimeIndex(nrun.dataset.coords["time"].values[:1]).asi8[0])
        if got != run["recorded_ns"] or nrun.dataset.time.size != run["n"]:
            raise ValueError(f"{tag}: h_from {neighbour.name}: the run from {run['files'][0].name} reads "
                             f"{nrun.dataset.time.size} samples from {_iso(got)}, where its time base puts "
                             f"{run['n']} from {_iso(run['recorded_ns'])}")
        _keep_channels(nrun, neighbour)
        _swap_h(nrun, neighbour)
        _flip_h(nrun, neighbour)
        _rot_h(nrun, neighbour)
        kept = {}
        for comp in ("hx", "hy"):
            if comp not in nrun.dataset:
                raise ValueError(f"{tag}: h_from {neighbour.name}: {neighbour.name}'s run holds "
                                 f"{list(nrun.dataset.data_vars)}, without {comp}")
            channel = nrun.dataset[comp]
            attrs = dict(channel.attrs)
            filters = [nrun.filters[f["applied_filter"]["name"]] for f in attrs.get("filters") or []]
            kept[comp] = (np.asarray(channel.data), attrs, filters)
        plan["cache"][g] = (kept, str(nrun.run_metadata.data_logger.id or neighbour.serial or "unknown"))
        del nrun
    kept, logger_id = plan["cache"][g]
    out = {}
    for comp, (samples, attrs, filters) in kept.items():
        if not 0 <= j0 < j1 <= samples.shape[0]:
            raise ValueError(f"{tag}: h_from {neighbour.name}: samples {j0}..{j1 - 1} wanted of a run of "
                             f"{samples.shape[0]}")
        out[comp] = (np.array(samples[j0:j1]), attrs, filters)
    return out, logger_id


def _drop_own_h(run, site: SiteConfig) -> str:
    """Drop an Orange Box site's own hx and hy before `h_from` lends a neighbour's; return the run comment line.

    An Orange Box records all five channels, so a site declared `h_from`
    has its own hx and hy (a dead or disturbed channel among them); they
    are taken out of the run as `_keep_channels` takes out an undeclared
    channel, and hz stays.
    """
    keep = SiteConfig(name=site.name, channels=[c for c in run.dataset.data_vars if c not in ("hx", "hy")])
    _keep_channels(run, keep)
    return (f"h_from {site.h_from}: the recorded hx and hy of {site.name} left out and replaced by "
            f"{site.h_from}'s; ex, ey and hz are {site.name}'s own")


def _h_from_station_notes(site: SiteConfig, plan: dict, rate: float) -> list[str]:
    """Return the lines an `h_from` ingest adds to the station's ``provenance.comments``.

    The first names the neighbour (`archive_h_from` reads it); one more
    follows for each local run the neighbour does not cover, which is left
    out of the archive.
    """
    neighbour, step = plan["neighbour"], 1e9 / float(rate)
    lines = [f"{_H_FROM_PREFIX}{neighbour.name}, {plan['distance_m']:.0f} m away, read from its raw files with "
             f"its calibration, h_scale {neighbour.h_scale:g}, swap_h {neighbour.swap_h}, flip_h "
             f"{' '.join(neighbour.flip_h) if neighbour.flip_h else 'none'} and clock_offset_s "
             f"{neighbour.clock_offset_s!r}, rot_h {neighbour.rot_h!r}, and aligned by GPS time, "
             f"{plan['cover']:.1%} of the recorded samples covered"]
    for mine, found in zip(plan["local"], plan["pieces"]):
        if not found:
            end = mine["start_ns"] + int(round((mine["n"] - 1) * step))
            lines.append(f"h_from {neighbour.name}: the recorded run {_iso(mine['start_ns'])} .. {_iso(end)} "
                         f"({mine['files'][0].name} .. {mine['files'][-1].name}) left out, {neighbour.name} "
                         f"does not cover it")
    return lines


def _read_borrowed(plan: dict, g: int, j0: int, j1: int, rate: float, tag: str) -> tuple[dict, str]:
    """Read samples j0..j1-1 of the neighbour's run g of hx and hy, as its own archive holds them.

    Only the files of the run that hold those samples are read, from the
    run's first file when the header coefficients of the first needed
    file differ from it (the linear stage comes from a run's first
    header). The reader must stamp the first of them where the run's first
    record and the record counts put it. The neighbour's `_keep_channels`,
    `_swap_h`, `_flip_h`, `_apply_h_scale` and `_rot_h` are applied, so each channel
    carries the samples, filter chain and metadata of the neighbour's
    archive.

    Args:
        plan (dict): `_h_from_plan`.
        g (int): The neighbour's run.
        j0 (int): First sample, counted from the run's start.
        j1 (int): One past the last sample.
        rate (float): Sample rate in Hz.
        tag (str): Label for messages.

    Returns:
        tuple: ``({comp: (samples, attrs, filters)} for hx and hy, the
        neighbour's logger serial)``.

    Raises:
        ValueError: If the reader's rate or stamps disagree with the plan.
    """
    from mt_io.lemi.lemi423 import Read_Lemi_Header

    if plan.get("instrument") == "edl":
        return _read_borrowed_edl(plan, g, j0, j1, rate, tag)
    if plan.get("instrument") == "orangebox":
        return _read_borrowed_orangebox(plan, g, j0, j1, rate, tag)
    neighbour, run = plan["neighbour"], plan["theirs"][g]
    files, cum = run["files"], run["cum"]
    k0 = int(np.searchsorted(cum, j0, side="right")) - 1
    k1 = int(np.searchsorted(cum, j1 - 1, side="right"))
    if k0 and Read_Lemi_Header(files[k0]).read()["coefficients"] != Read_Lemi_Header(files[0]).read()["coefficients"]:
        k0 = 0
    kwargs = dict(station_id=neighbour.name, dipole_length_ex=neighbour.dipole_length_ex,
                  dipole_length_ey=neighbour.dipole_length_ey)
    if plan["calibration"] is not None:
        kwargs["calibration_fn"] = plan["calibration"]
    chunk = files[k0:k1]
    nrun = read_lemi423(chunk if len(chunk) > 1 else chunk[0], **kwargs)
    if abs(float(nrun.sample_rate) - float(rate)) > 1e-9 * float(rate):
        raise ValueError(f"{tag}: h_from {neighbour.name}: {chunk[0].name} reads at {nrun.sample_rate:g} Hz, not "
                         f"{rate:g} Hz")
    got = int(pd.DatetimeIndex(nrun.dataset.coords["time"].values[:1]).asi8[0])
    want = run["recorded_ns"] + int(round(int(cum[k0]) * 1e9 / float(rate)))
    if got != want:
        raise ValueError(f"{tag}: h_from {neighbour.name}: {chunk[0].name} starts at {_iso(got)}, where its run's "
                         f"first record and record counts put {_iso(want)}: the files are not back to back")
    _keep_channels(nrun, neighbour)
    _swap_h(nrun, neighbour)
    _flip_h(nrun, neighbour)
    _apply_h_scale(nrun, neighbour)
    _rot_h(nrun, neighbour)
    a, b = j0 - int(cum[k0]), j1 - int(cum[k0])
    out = {}
    for comp in ("hx", "hy"):
        if comp not in nrun.dataset:
            raise ValueError(f"{tag}: h_from {neighbour.name}: {neighbour.name}'s run holds "
                             f"{list(nrun.dataset.data_vars)}, without {comp}")
        channel = nrun.dataset[comp]
        if not 0 <= a < b <= channel.shape[0]:
            raise ValueError(f"{tag}: h_from {neighbour.name}: samples {a}..{b - 1} wanted of a read of "
                             f"{channel.shape[0]} from {chunk[0].name}")
        attrs = dict(channel.attrs)
        filters = [nrun.filters[f["applied_filter"]["name"]] for f in attrs.get("filters") or []]
        out[comp] = (np.array(channel.data[a:b]), attrs, filters)
    return out, str(nrun.run_metadata.data_logger.id or "unknown")


def _read_borrowed_edl(plan: dict, g: int, j0: int, j1: int, rate: float, tag: str) -> tuple[dict, str]:
    """`_read_borrowed` for an EDL neighbour: its run g read whole once, its own steps applied, then sliced.

    The neighbour's run is read with `read_run` and its own settings, its
    overlap trim, `_keep_channels`, `_swap_h`, `_flip_h` and `_rot_h`
    applied, so hx and hy hold what its own archive holds; the result is
    kept in ``plan["cache"]`` for the other pieces of the same run.

    Raises:
        ValueError: If the read's rate or first time differ from the plan.
    """
    neighbour, run = plan["neighbour"], plan["theirs"][g]
    if g not in plan["cache"]:
        plan["cache"].clear()  # one neighbour run in memory at a time
        nrun = read_run("edl", list(run["group"]), neighbour, plan["folder"], calibration=plan["calibration"])
        if abs(float(nrun.sample_rate) - float(rate)) > 1e-9 * float(rate):
            raise ValueError(f"{tag}: h_from {neighbour.name}: {run['files'][0].name} reads at "
                             f"{nrun.sample_rate:g} Hz, not {rate:g} Hz")
        if run["trim"]:
            nrun = _trim_run_start(nrun, run["trim"], _overlap_note(run["group"], rate))
        got = int(pd.DatetimeIndex(nrun.dataset.coords["time"].values[:1]).asi8[0])
        if got != run["recorded_ns"] or nrun.dataset.time.size != run["n"]:
            raise ValueError(f"{tag}: h_from {neighbour.name}: the run from {run['files'][0].name} reads "
                             f"{nrun.dataset.time.size} samples from {_iso(got)}, where its stamps and sample "
                             f"counts put {run['n']} from {_iso(run['recorded_ns'])}")
        _keep_channels(nrun, neighbour)
        _swap_h(nrun, neighbour)
        _flip_h(nrun, neighbour)
        _rot_h(nrun, neighbour)
        kept = {}
        for comp in ("hx", "hy"):
            if comp not in nrun.dataset:
                raise ValueError(f"{tag}: h_from {neighbour.name}: {neighbour.name}'s run holds "
                                 f"{list(nrun.dataset.data_vars)}, without {comp}")
            channel = nrun.dataset[comp]
            attrs = dict(channel.attrs)
            filters = [nrun.filters[f["applied_filter"]["name"]] for f in attrs.get("filters") or []]
            kept[comp] = (np.asarray(channel.data), attrs, filters)
        plan["cache"][g] = (kept, str(nrun.run_metadata.data_logger.id or "unknown"))
        del nrun
    kept, logger_id = plan["cache"][g]
    out = {}
    for comp, (samples, attrs, filters) in kept.items():
        if not 0 <= j0 < j1 <= samples.shape[0]:
            raise ValueError(f"{tag}: h_from {neighbour.name}: samples {j0}..{j1 - 1} wanted of a run of "
                             f"{samples.shape[0]}")
        out[comp] = (np.array(samples[j0:j1]), attrs, filters)
    return out, logger_id


def _borrow_h(run, lo: int, hi: int, borrowed: dict, notes: dict):
    """Return samples lo..hi-1 of a local run with the borrowed hx and hy added.

    The local channels keep their samples and time stamps; the borrowed
    channels take the local's time axis, the neighbour's samples, metadata
    (azimuths, sensor, location, chain) and filters, and each its line in
    `notes` after its comment. The run's and station's metadata are copies
    of the local run's.

    Args:
        run (RunTS): The local run.
        lo (int): First sample kept.
        hi (int): One past the last.
        borrowed (dict): `_read_borrowed`'s channels.
        notes (dict): {comp: comment line}.

    Returns:
        RunTS: The piece.

    Raises:
        ValueError: If a borrowed filter's name is a different filter in a
            local channel's chain.
    """
    import xarray as xr
    from mth5.timeseries import RunTS

    dataset = run.dataset.isel(time=slice(lo, hi)).copy()
    times = pd.DatetimeIndex(dataset.coords["time"].values)
    t0 = pd.Timestamp(times[0], tz="UTC").isoformat()
    t1 = pd.Timestamp(times[-1], tz="UTC").isoformat()
    local = list(dataset.data_vars)
    used = {f["applied_filter"]["name"] for c in local for f in dataset[c].attrs.get("filters") or []}
    for comp in local:
        dataset[comp].attrs = dict(dataset[comp].attrs, **{"time_period.start": t0, "time_period.end": t1})
    piece = RunTS()
    piece.station_metadata = run.station_metadata.copy()
    piece.run_metadata = run.run_metadata.copy()
    piece.run_metadata.time_period.start = t0
    piece.run_metadata.time_period.end = t1
    filters = dict(run.filters)
    for comp, (samples, attrs, chain) in borrowed.items():
        attrs = dict(attrs, **{"time_period.start": t0, "time_period.end": t1})
        if local:
            attrs["station.id"] = dataset[local[0]].attrs.get("station.id")
            attrs["run.id"] = dataset[local[0]].attrs.get("run.id")
        attrs["comments"] = _append_comment(attrs.get("comments"), notes[comp])
        dataset[comp] = xr.DataArray(samples, coords={"time": dataset.coords["time"]}, dims=("time",), attrs=attrs)
        for f in chain:
            if f.name in used and filters.get(f.name) != f:
                raise ValueError(f"h_from: the borrowed {comp}'s filter {f.name} is another filter in the local "
                                 f"channels' chains")
            filters[f.name] = f  # the neighbour's own stage, e.g. its lemi423_linear_hx
    piece.filters = filters
    piece.dataset = dataset
    return piece


def _h_from_pieces(run, index: int, plan: dict, site: SiteConfig, rate: float):
    """Yield the archive runs one local run makes under `h_from`, one per piece of `_h_from_plan`.

    The run must start and hold the samples `_run_spans` planned. Each
    piece's borrowed channels are read when it is yielded, so one piece's
    neighbour samples are in memory at a time. A piece shorter than the
    run gets a run comment line naming the part kept, and each piece is
    logged with its span.

    Args:
        run (RunTS): The local run, every local step applied.
        index (int): Its index in `plan["local"]`.
        plan (dict): `_h_from_plan`.
        site (SiteConfig): The local site's settings.
        rate (float): Sample rate in Hz.

    Yields:
        RunTS: The pieces, in time order.

    Raises:
        ValueError: If the local run's start or length differs from the plan.
    """
    mine, neighbour = plan["local"][index], plan["neighbour"]
    times = run.dataset.coords["time"].values
    got = int(pd.DatetimeIndex(times[:1]).asi8[0])
    if got != mine["start_ns"] or times.size != mine["n"]:
        raise ValueError(f"{site.name}: run from {mine['files'][0].name} reads {times.size} samples from "
                         f"{_iso(got)}, where its records put {mine['n']} from {_iso(mine['start_ns'])}")
    step = 1e9 / float(rate)
    for lo, hi, g, j0 in plan["pieces"][index]:
        borrowed, logger_id = _read_borrowed(plan, g, j0, j0 + (hi - lo), rate, site.name)
        # the coil table's name carries the coil id it was looked up by (read_lemi_coil_response)
        names = [f.name for f in borrowed["hx"][2] if f.name.startswith("lemi_120")]
        match = re.fullmatch(r"lemi_120_(.+)_response", names[0]) if names else None
        coil = match.group(1) if match else (names[0] if names else plan.get("sensor", "none"))
        notes = {comp: (f"h_from: {comp} of {neighbour.name}, {plan['distance_m']:.0f} m away, coil {coil}, logger "
                        f"{logger_id}; aligned by GPS time; the neighbour's clock_offset_s "
                        f"{neighbour.clock_offset_s!r} applied") for comp in ("hx", "hy")}
        piece = _borrow_h(run, lo, hi, borrowed, notes)
        del borrowed
        t0, t1 = mine["start_ns"] + int(round(lo * step)), mine["start_ns"] + int(round((hi - 1) * step))
        span = f"{_iso(t0)} .. {_iso(t1)}"
        line = f"h_from: hx and hy of {neighbour.name} ({plan['distance_m']:.0f} m away) over {span}, aligned by GPS time"
        cut = ""
        if hi - lo != mine["n"]:
            end = mine["start_ns"] + int(round((mine["n"] - 1) * step))
            cut = (f", cut to the part {neighbour.name} covers ({hi - lo} of {mine['n']} samples; recorded "
                   f"{_iso(mine['start_ns'])} .. {_iso(end)})")
        piece.run_metadata.comments.value = _append_comment(piece.run_metadata.comments, line + cut)
        logger.info(f"{site.name}: h_from {neighbour.name} -> hx, hy over {span} ({hi - lo} samples){cut}")
        yield piece


def archive_h_from(path: Path, site_name: str) -> str | None:
    """Return the neighbour whose hx and hy an archive's ingest took (`SiteConfig.h_from`).

    Read from the station's ``provenance.comments``, where `ingest_site`
    records it; a raw archive and its filtered variant both carry it.

    Args:
        path (Path): The archive.
        site_name (str): The station in it.

    Returns:
        str or None: The neighbour's name; None for an archive whose hx and
        hy are its own.
    """
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        if line.startswith(_H_FROM_PREFIX):
            return line[len(_H_FROM_PREFIX):].split(",", 1)[0]
    return None


def _read_phoenix_run(group: tuple, site: SiteConfig, calibration_dir: Path):
    """Read one Phoenix run (`_phoenix_units`) and give it its run comment.

    Returns:
        RunTS: The run, its comment the `mt_workbench.phoenix.read_continuous`
        lines and, where the recording holds file types mt-io cannot read,
        a line naming them.
    """
    from .phoenix import read_continuous, unread_types

    rec, plan = group
    run, notes, _correction = read_continuous(rec, plan, site, calibration_dir)
    unread = unread_types(rec)
    if unread:
        notes.append(f"phoenix_unread: {' '.join(unread)} files not read (no mt-io reader)")
    run.run_metadata.comments.value = "; ".join(notes)
    return run


def _ingest_bursts(survey: Survey, site: SiteConfig, site_dir: Path, start, end, out_path: Path) -> Path:
    """Write a Phoenix site's 24 kHz bursts as one run per burst (a burst site, `bursts_of:`).

    The bursts of every recording of the recorded site's folder within
    [start, end) are matched across the channel folders by stamp
    (`mt_workbench.phoenix.burst_slots`); a slot that some folder lacks is
    left out and counted in the next run's comment. Each file is read once
    per channel folder through mt-io (`mt_workbench.phoenix._read_bursts`),
    and its bursts must match the walk of its sub-headers in number, stamp
    and samples; a burst cut short at the end of the file, which the walk
    leaves out with a warning, is dropped from mt-io's read when its size
    is the samples the file holds of it (`phoenix.cut_burst_samples`), so
    that a recording stopped during a burst is ingested whole (upstream
    issue 73). Any failure after the archive is opened removes it
    (`_remove_partial_archive`). The channels get the names, chains and comments of the
    continuous runs (`mt_workbench.phoenix._channel_chain`, built once per
    recording), a start that is mt-io's for the burst plus the stamp
    correction checked per burst, the recorded site's `clock_offset_s`,
    `swap_h`, `flip_h` (after the exchange), `swap_e` (read exchanged, as
    the continuous runs: `_phoenix_swap_e`) and `channels:`. Runs are
    ``sr24000_00001`` on (five digits: 2,880 bursts a day) and are written
    with mth5's `add_channel`, a tenth of the time of `from_runts`. The
    station's period runs from the first run's start to the last run's
    end, both on the corrected time. The station's metadata is read once,
    before its first run; each run is added to it without an update, and
    the run list, period and provenance lines are set on that object and
    written once after the last run (`_write_group_metadata`): mth5's
    station getter, which `write_metadata` also reads, adds every run of
    the station again on each read, a cost in the square of the run count
    (upstream issue 85: 85 of the 93 min of a 7048-run ingest).

    Args:
        survey (Survey): The survey.
        site (SiteConfig): The burst site's settings (`Survey.site`).
        site_dir (Path): The recorded site's folder.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.
        out_path (Path): The archive, written anew.

    Returns:
        Path: The archive.

    Raises:
        ValueError: If a recording is of another receiver than `serial`,
            no burst lies in the window, a file's bursts read through
            mt-io differ from its sub-headers, a header rate is not the
            site's, or a stamp fails `mt_workbench.phoenix.stamp_correction`.
    """
    from mt_io.phoenix.read import open_phoenix
    from mth5.groups import FiltersGroup

    from .phoenix import (UNITS_NOTE, _channel_chain, _read_bursts, burst_index, burst_slots, component_of,
                          cut_burst_samples, find_recordings, input_range_v, open_recording, stamp_correction,
                          stamp_note, station_record)

    if site.rot_h != 0.0:
        raise ValueError(f"{site.name}: rot_h on {site.bursts_of}, and the burst ingest does not build it; "
                         f"ingest the bursts of a site without it")
    rate = float(site.sample_rate)
    calibration_dir = _calibration_dir(survey, site)
    plans = []
    for folder in find_recordings(site_dir, site.recording):
        rec = open_recording(folder)
        if site.serial and str(site.serial) != rec.receiver:
            raise ValueError(f"{site.name}: {folder} is receiver {rec.receiver}, and survey.yaml declares serial "
                             f"{site.serial}")
        try:
            slots, missing = burst_slots(rec, start, end)
        except ValueError:
            continue
        if slots:
            plans.append((rec, slots, missing))
    if not plans:
        raise ValueError(f"{site.name}: no Phoenix burst of {site.bursts_of} in [{start}, {end})")
    n_slots = sum(len(p[1]) for p in plans)
    logger.info(f"{site.name}: ingesting {n_slots} burst(s) of {site.bursts_of} from {len(plans)} recording(s) "
                f"-> {out_path}")
    if out_path.exists():
        out_path.unlink()
    keep = [c.lower() for c in site.channels] if site.channels else None
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    written = False
    try:
        m.add_survey(survey.name)
        station_group, station_meta, filters_written = None, None, set()
        levels: list[dict] = []
        run_groups = {}
        first_t = last_t = None  # the first run's start and the last run's end
        for rec, slots, missing in plans:
            setup, run_md, station_md = {}, None, None
            recording_id = rec.recording_id  # a glob of the recording's files: once per recording, not per burst
            for folder in sorted(rec.tags):
                reader = open_phoenix(slots[0].bursts[folder].path)
                try:
                    if abs(float(reader.sample_rate) - rate) > 1e-9 * rate:
                        raise ValueError(f"{site.name}: {reader.base_path.name} is at {reader.sample_rate:g} Hz; "
                                         f"the burst site is declared at {rate:g} Hz")
                    md = reader.channel_metadata.copy()
                    chain, pieces, replaced = _channel_chain(reader, rec, folder, site, calibration_dir, md)
                    if run_md is None:
                        run_md, station_md = reader.run_metadata.copy(), reader.station_metadata.copy()
                finally:
                    reader.close()
                comp = component_of(rec.tags[folder], site.swap_e)  # the E2 input as ex at a swap_e site
                if keep is not None and comp not in keep:
                    continue
                md.component, md.channel_number, md.sample_rate = comp, folder, rate
                md.filters = []
                for stage, f in enumerate(chain, 1):
                    md.add_filter(name=f.name, applied=True, stage=stage)
                setup[folder] = [comp, md, chain, [f"phoenix: folder {folder}, tag {rec.tags[folder].upper()}",
                                                   *pieces], replaced]
            # each folder's input rail, which follows its samples through swap_h (upstream issue 78)
            burst_rails = {folder: RAIL_LEVEL * input_range_v(slots[0].bursts[folder].path) for folder in setup}
            swapped_e = None
            if site.swap_e:  # read exchanged (`component_of`, as `_phoenix_swap_e` for the continuous runs)
                stored = sorted(s_[0] for s_ in setup.values())
                if not {"ex", "ey"} <= set(stored):
                    raise ValueError(f"{site.name}: swap_e exchanges ex and ey, and the bursts hold {stored}")
                swapped_e = PHOENIX_SWAP_E_NOTE
            swapped = None
            if site.swap_h:
                inputs = {s[0]: f for f, s in setup.items()}
                if not {"hx", "hy"} <= set(inputs):
                    raise ValueError(f"{site.name}: swap_h exchanges hx and hy, and the bursts hold {sorted(inputs)}")
                fx, fy = inputs["hx"], inputs["hy"]
                setup[fx][2], setup[fy][2] = setup[fy][2], setup[fx][2]
                setup[fx][1], setup[fy][1] = setup[fx][1].copy(), setup[fy][1].copy()
                for f_to, f_from in ((fx, fy), (fy, fx)):
                    setup[f_to][1].filters = []
                    for stage, f in enumerate(setup[f_to][2], 1):
                        setup[f_to][1].add_filter(name=f.name, applied=True, stage=stage)
                setup[fx][0], setup[fy][0] = "hy", "hx"  # the samples of the hx input are stored as hy
                swapped = "swap_h: hx and hy exchanged, each with the filter chain of the input it was recorded on"
            flipped = flip_channel = None
            flip_comps = set(site.flip_h or [])
            if flip_comps:
                stored = sorted(s_[0] for s_ in setup.values())  # the names after any exchange
                missing = sorted(flip_comps - set(stored))
                if missing:
                    raise ValueError(f"{site.name}: flip_h names {missing}, and the bursts hold {stored}")
                flipped, flip_channel = _flip_notes(site)
            if station_group is None:
                station_group = m.add_station(site.name, survey=survey.name)
                station_record(station_md, site.name)
                apply_site_frame(station_md, site)
                # the station's metadata read once, before its first run: mth5's getter re-adds every run of
                # the station on each read, at a cost in the square of the run count (upstream issue 85)
                station_meta = station_group.metadata
                station_meta.update(station_md)
            current: dict[int, tuple] = {}
            corrections, shifts, version = set(), set(), None
            missed = set(missing)
            pending = 0
            for slot in slots:
                pending += sum(1 for s in list(missed) if s < slot.stamp)
                missed = {s for s in missed if s >= slot.stamp}
                arrays, comps = {}, {}
                for folder, (comp, md, chain, pieces, replaced) in setup.items():
                    burst = slot.bursts[folder]
                    if current.get(folder, (None,))[0] != burst.path:
                        read = _read_bursts(burst.path)
                        walk = burst_index(burst.path)
                        cut = cut_burst_samples(burst.path, walk)
                        if len(read) == len(walk) + 1 and cut is not None and read[-1][1].size == cut:
                            read = read[:-1]  # mt-io's trailing burst, cut at the end of the file: the walk's left out
                        if [d.size for _t, d in read] != [b.n for b in walk]:
                            raise ValueError(f"{burst.path.name}: mt-io read {len(read)} bursts of "
                                             f"{[d.size for _t, d in read][:3]}... samples, the sub-headers give "
                                             f"{len(walk)} of {[b.n for b in walk][:3]}...")
                        current[folder] = (burst.path, read)
                        version = int(open_header_version(burst.path))
                    reader_s, data = current[folder][1][burst.index]
                    correction = stamp_correction(reader_s, burst.start_s, version, burst.path.name)
                    corrections.add(correction)
                    shifts.add(round(reader_s - burst.start_s, 6) + correction)
                    arrays[comp] = -data if comp in flip_comps else data  # not in place: `current` caches the read
                if len(corrections) != 1 or len(shifts) != 1:
                    raise ValueError(f"{site.name}: bursts need different stamp corrections {corrections} "
                                     f"(shifts from the sub-header stamps {shifts})")
                # mt-io's start plus the correction, as the shift from the sub-header stamp
                shift = next(iter(shifts)) + site.clock_offset_s
                t0 = pd.Timestamp(slot.start_s + shift, unit="s", tz="UTC")
                t1 = t0 + pd.Timedelta(seconds=(slot.n - 1) / rate)
                first_t, last_t = (t0 if first_t is None else first_t), t1
                run_id = f"sr{int(rate)}_{len(run_groups) + 1:05d}"
                run_group = station_group.add_run(run_id)
                if not filters_written >= {f.name for s_ in setup.values() for f in s_[2]}:
                    group = FiltersGroup(run_group.hdf5_group.parent.parent.parent["Filters"])
                    for s_ in setup.values():
                        for f in s_[2]:
                            if f.name not in filters_written:
                                group.add_filter(f)
                                filters_written.add(f.name)
                note = stamp_note(next(iter(corrections)), version)
                clock = _clock_note(site.clock_offset_s) if site.clock_offset_s else None
                for folder, (comp, md, chain, pieces, replaced) in setup.items():
                    channel_md = md.copy()
                    channel_md.time_period.start, channel_md.time_period.end = t0.isoformat(), t1.isoformat()
                    channel_md.comments = "; ".join([", ".join(pieces), note, *([clock] if clock else []),
                                                     *([f"swap_h: the samples and filter chain of the "
                                                        f"{'hy' if comp == 'hx' else 'hx'} input"]
                                                       if swapped and comp in ("hx", "hy") else []),
                                                     *([flip_channel] if comp in flip_comps else [])])
                    run_group.add_channel(comp, md.type, arrays[comp], channel_metadata=channel_md)
                    levels.append(dict(site=site.name, run=run_id, channel=comp,
                                       type="electric" if comp.startswith("e") else "magnetic", sample_rate=rate,
                                       **channel_stats(arrays[comp], rate, rail=burst_rails[folder])))
                first = next(iter(slot.bursts.values()))
                pieces_run = [f"phoenix: {rec.model} ({rec.receiver_model}) receiver {rec.receiver}, recording "
                              f"{recording_id}, burst {first.index + 1} of file {first.path.stem.split('_')[3]}, "
                              f"stamp {slot.stamp}, folders {' '.join(str(f) for f in setup)}, file version {version}, "
                              f"metadata {rec.meta_path.name}"
                              f"{' (recmeta.json also present)' if rec.recmeta is not None else ''}", note]
                if any(s_[4] for s_ in setup.values()):
                    pieces_run.append(UNITS_NOTE)
                if pending:
                    pieces_run.append(f"phoenix_missing_bursts: {pending} burst slot(s) before this one lack a "
                                      f"channel folder's burst and were left out")
                    pending = 0
                # the instruments' registry DOIs as survey.yaml declares them (none: nothing added)
                pieces_run += [x for x in (swapped_e, swapped, flipped, clock, survey.registry_note(site.name)) if x]
                meta = run_group.metadata
                meta.id = run_id
                meta.sample_rate = rate
                meta.time_period.start, meta.time_period.end = t0.isoformat(), t1.isoformat()
                meta.data_logger.id = rec.receiver
                meta.data_logger.model = rec.receiver_model
                meta.data_logger.manufacturer = "Phoenix Geophysics"
                meta.comments.value = "; ".join(pieces_run)
                meta.channels_recorded_electric = [c for c in arrays if c.startswith("e")]
                meta.channels_recorded_magnetic = [c for c in arrays if c.startswith("h")]
                run_group.write_metadata()
                run_groups[run_id] = run_group
                station_meta.add_run(meta, update=False)  # the run list and period are updated once, below;
                # until then has_run cannot see the run just added and a repeated id would replace it (ids are unique here)
            for line in (note, clock, survey.registry_note(site.name)):
                if line and line not in str(station_meta.provenance.comments.value or ""):
                    station_meta.provenance.comments.value = _append_comment(station_meta.provenance.comments, line)
        station_meta.update_all()
        station_meta.time_period.start = first_t.isoformat()
        station_meta.time_period.end = last_t.isoformat()
        _write_group_metadata(station_group, station_meta)
        _record_levels(run_groups, levels, site.name, unit="V")
        logger.info(f"{site.name}: {len(run_groups)} burst run(s) written")
        written = True
    finally:
        try:
            m.close_mth5()
        finally:
            if not written:
                _remove_partial_archive(out_path, site.name)
    return out_path


def _write_group_metadata(group, metadata) -> None:
    """Write a metadata object to an mth5 group's attributes, as mth5's `BaseGroup.write_metadata` writes them.

    mth5's own `write_metadata` reads the group's `metadata`, and for a
    station that getter adds every run of the station to it again, each add
    recomputing the station's period over all its runs (upstream issue 85):
    for a burst site of thousands of runs one such read takes minutes. Here
    the object the caller holds is written as it is: each key of
    ``metadata.to_dict(single=True)``, converted by mth5's `to_numpy_type`,
    modifies an attribute whose value differs or creates a missing one.

    Args:
        group: The mth5 group (`mth5.groups.BaseGroup`), in a file open for
            writing.
        metadata: Its metadata (`mt_metadata.base.MetadataBase`), with every
            update applied.
    """
    from mth5.groups.base import BaseGroup
    from mth5.helpers import to_numpy_type

    attrs = group.hdf5_group.attrs
    for key, value in metadata.to_dict(single=True).items():
        value = to_numpy_type(value)
        if key in attrs:
            if BaseGroup._values_equal(attrs[key], value):
                continue
            attrs.modify(key, value)
        else:
            attrs.create(key, value)


def _remove_partial_archive(path: Path, site_name: str) -> None:
    """Delete the archive a failed burst ingest was writing, leaving no partial archive under the site's name.

    Args:
        path (Path): The archive.
        site_name (str): The burst site, for the log.
    """
    try:
        if path.exists():
            path.unlink()
            logger.warning(f"{site_name}: removed the partial {path}")
    except OSError as exc:  # the ingest's own error is the one raised
        logger.error(f"{site_name}: could not remove the partial {path}: {exc}")


def open_header_version(path: Path) -> int:
    """Return a Phoenix file's format version from its header."""
    from .instruments import phoenix_header

    return int(phoenix_header(path)["file_version"])


def _describe_group(group) -> str:
    """Return a run's files for the log: the first and last name and the count."""
    if isinstance(group, tuple) and hasattr(group[0], "paths"):  # an Orange Box run (`_orangebox_units`)
        paths = group[0].paths
        return f"{len(paths)} file(s) ({paths[0].name} .. {paths[-1].name})"
    if isinstance(group, tuple):
        _rec, plan = group
        files = next(iter(plan.files.values()))
        return f"{len(files)} file(s) per channel ({files[0].path.name} .. {files[-1].path.name})"
    if isinstance(group, mtu5a.Mtu5aRun):
        return group.describe()
    return f"{len(group)} file(s) ({group[0].name} .. {group[-1].name})"


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
    mt-io readers (`mt_workbench.instruments.read_run`), a LEMI-424's
    channels stored as hx hy hz ex ey e3 e4
    (`mt_workbench.instruments.lemi424_stored`), with the declared
    `channels:` applied in the same way.
    `h_scale` and the reversed-dipole flip apply to LEMI-423 sites, as does
    `calibration_fn`, which is also used by an EDL site whose `sensor_type`
    is lemi120. A LEMI-424 site's electric samples stay the logger's
    columns and its `e_sign` (`_e_sign`: -1.0 unless survey.yaml says
    otherwise) is recorded as the applied stage `LEMI424_E_SIGN_FILTER` in
    each electric chain and in the run comment (`_apply_e_sign`); the
    reversed-dipole flip then negates the samples of a line declared laid
    reversed. A site declared `swap_h` has its hx and hy exchanged after
    the channel keep, each with the filter chain of its input (`_swap_h`),
    and each run comment gets the line "swap_h: hx and hy exchanged, each
    with the filter chain of the input it was recorded on". A site declared
    `swap_e` has its ex and ey exchanged before that, each with its own
    dipole stage and the other input's stages (`_swap_e`); a Phoenix run
    is read exchanged instead, the E2 input stored as ex and the E1 as ey,
    each with everything read from its input and its rail
    (`_phoenix_swap_e`, `mt_workbench.phoenix.component_of`). An EDL or
    LEMI-424 site whose electric lines are laid off the cardinal axes (ex
    not at 0 or 180 deg, ey not at 90 or 270) has its calibrated pair
    turned onto magnetic north and east after `swap_e`, the LEMI-424
    `e_sign` and the reversed-pair rule (`_rot_e`; the line
    "rot_e: ex <a_x> deg, ey <a_y> deg as laid, ..." in the run, ex and ey
    comments and the station's ``provenance.comments``, read back by
    `archive_rot_e`); a layout it cannot turn (a line on the other
    channel's axis, a pair more than 15 deg from perpendicular, another
    recorder, `flip_reversed_dipoles: false`, a geographic layout, one
    line kept) is refused before anything is written (`_check_e_azimuths`). A fluxgate site
    declared `rot_h` has hx and hy turned by it onto magnetic north once
    `swap_h`, `flip_h` and `h_scale` are applied (`_rot_h`; the line "rot_h:
    <angle> deg applied at ingest, ..." in the run, hx and hy comments and
    the station's ``provenance.comments``, read back by `archive_rot_h`).
    An EDL restart file stamped before the end of the file it interrupted
    starts a run without its overlapping samples (`_edl_plan`,
    `_trim_run_start`; the run comment's "overlap:" line names both files),
    and a stamp whose files hold no sample is left out. A first file
    holding the deployment test run before the record (two trace ids)
    starts its run at the record, the test run left out
    (`edl_record_start`; the run comment's "deployment_test_run:" line
    names the traces left out), and an EDL run whose read differs from its
    plan in any channel's samples or in its start is refused
    (`_check_edl_read`). A site that
    declares `clock_offset_s` has that many seconds added to every run's
    time stamps after the exchange (`_shift_clock`), and the run comment,
    each channel's comment and the station's ``provenance.comments`` get
    the line "clock_offset_s: -1.0 s added to every recorded time
    stamp at ingest ..."; the files of the `start`/`end` window are chosen
    by their recorded stamps. A LEMI-423 or EDL site that recorded electrics
    only and declares `h_from: <neighbour>` (a site of the same recorder)
    gets the neighbour's hx and hy
    (`_h_from_plan`, `_h_from_pieces`): the neighbour's raw files are
    grouped into runs as its own ingest groups them and read with its
    calibration file, header coefficients, `h_scale` and `swap_h`, its
    stamps moved by its own `clock_offset_s`, and its samples taken at the
    local's time stamps one for one, so the borrowed channels hold what the
    neighbour's own archive holds at those instants. A local run the
    neighbour covers in part is cut to the covered part, one it covers
    across a gap or a boundary of its runs is split there, and one it does
    not cover is left out; the run comment records the span and any cut,
    each borrowed channel's comment the neighbour, its distance, coil and
    logger, and the station's ``provenance.comments`` the neighbour
    (`archive_h_from`) and every run left out. The neighbour must cover
    `H_FROM_MIN_COVER` of the local's samples on the same sample grid.
    A burst site (`bursts_of:`) is written from its recorded site's
    folder by `_ingest_bursts`, one run per burst.
    An Orange Box site needs `electric_full_scale_uv` and
    `magnetic_full_scale_nt` (`_orangebox_scales`), may not set the LEMI,
    EDL or Phoenix keys, and a site of another recorder may not set the
    Orange Box keys (`_check_instrument_keys`). Its runs come from
    `_orangebox_units`: split at stamp gaps over 2 s, timed from the
    stamps on `clock_timezone` with `clock_drift_s` spread over the
    deployment, resampled onto the UTC 10 Hz grid; each run comment starts
    with the "orangebox_time_base:" line (`archive_time_base`), and the dc
    levels are in counts.
    A Phoenix site (`mt_workbench.phoenix`) needs `calibration_dir`;
    its own entry may not set `h_scale`, `sensor_type`, `electric_gain`,
    `calibration_fn` or `h_from`, and a site of another recorder may not
    set the Phoenix keys (`_check_instrument_keys`). Its runs come from
    `_phoenix_units`, each run comment starts with the receiver, the
    recording, the metadata file, the stamp correction and the units line,
    and a "phoenix_gap" line on a run after sequences left out of every
    channel (`mt_workbench.phoenix.plan_runs`), and the dc levels are in
    volts with no absolute open-input threshold, their rail share against
    each channel's input rail (`_phoenix_rails`).
    An MTU-5A site's runs come from `mt_workbench.mtu5a.plan_runs` (every
    `.TS4` of the folder with its `.TBL`, one receiver, no overlap; a run
    ends where the record tags step by other than 1 s) and are read by
    `mt_workbench.mtu5a.read_run` (counts, the table's scalar chain as
    filters); its own entry may set neither the Phoenix keys nor the LEMI
    and EDL ones, and the tags' saturation, status and clock flags go to
    `<archive stem>.mtu5a_flags.csv` beside the archive
    (`mt_workbench.mtu5a.write_flags`), named in the log. Its dc levels
    are in counts, their rail share against the receiver's clip
    (`mt_workbench.mtu5a.rails`, RAIL_LEVEL x 0.941 x 2^23 counts).
    `max_run_files`
    caps LEMI-423 runs only: 90 days of EDL at 10 Hz (78 M samples per
    channel) is less than one 51 h LEMI-423 run. An EDL site's declared
    `electric_gain` becomes a filter on the ex and ey chains (`read_run`;
    the samples stay the stored words), and the run comment gets a line
    such as "electric gain 10 on ['ex', 'ey'] (declared from the field
    notes)". The key is checked before an existing archive is deleted
    (`_electric_gain`). An EDL site's `electric_gain_ex` or
    `electric_gain_ey` adds one more stage to that line's chain alone
    (`mt_workbench.instruments.add_channel_electric_gains`), with the run
    comment line "electric gain 64 on ex alone (declared
    electric_gain_ex)". An EDL site declared `edl_banks_swapped` has its
    samples exchanged right after the read, the .EX and .EY words stored
    as hx and hy and the .BX and .BY words as ex and ey, each channel with
    the chain of its name, and no hz (`_edl_banks_swapped`; refused on
    another recorder by `_check_banks_instrument` before anything is
    written). A site declaring `record_window` keeps only the samples at
    instants start <= t < end, applied to each archive run after every
    other step (`_record_window`): a run is clipped (its comment says what
    was kept of what was read) or, wholly outside, left out, and the
    station's ``provenance.comments`` gets the window and each run left out.

    Each run comment records the coil tables read, the site's
    `calibration_fn` and an `h_from` neighbour's, as
    "calibration_sha256: <hex>" (the sha256 of each table, or "none" when
    none was read; `_calibration_note`), which `build_variant`,
    `variant_ready` and `processing_archive` compare with the tables the
    site declares later (`_calibration_stale`). A burst site's archive
    records none.

    The archive holds calibration only: the coil response, `h_scale`, the
    `swap_e` exchange, the reversed-dipole flip, the `rot_e` turn, the
    `swap_h` exchange, the `flip_h` sign flip (after the exchange), the
    `rot_h` turn and the
    declared electric gain, on the time axis of the declared
    `clock_offset_s`. The declared list of
    `<survey>/filters.yaml`, `replace` included, is applied on demand by
    `build_variant`.

    Each run's electric and magnetic channels are measured as the run is
    written (`_run_levels`: the median, MAD and rail share of the stored
    samples, on a subsample of at most an hour of samples). Once every run
    is written, the site's channel runs are classified together
    (`mt_workbench.dclevel.classify`: "open input?" above 1e9 counts or 30 times
    the typical level of the channel type, "saturated?" above 1 % at a rail,
    else "ok"), each run's comment gets a line such as "dc level (median
    counts, rail %): ex +2.000e+07 0.00 ok, ey +1.600e+09 0.00 open input?"
    (`_record_levels`), and each flagged channel run is logged as a warning
    (`mt_workbench.dclevel.flag_line`).

    Args:
        survey (Survey): The survey.
        site_name (str): Site name.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.
        out_path (Path, optional): Output file; default
            `default_archive_path`.
        overwrite (bool): Replace an existing file. When False, an existing
            file is returned as it is, also when the site's raw folder is
            not found under `data_root` (a stale path, or a drive not
            plugged in).
        max_run_files (int, optional): Most files per LEMI-423 run.
        ignore_filters (bool): Accepted for compatibility with older callers
            and ignored.

    Returns:
        Path: The archive path.

    Raises:
        FileNotFoundError: If the coil calibration file is missing, the
            site has no data files, or its raw folder is not found under
            `data_root` and there is no archive to keep (or `overwrite`
            asks for a new one).
        ValueError: If a setting does not fit the instrument (see
            `_electric_gain`, `_keep_channels`, `_swap_h`, `_flip_h`,
            `_standardise_e_orientation`, `_h_from_plan`; an existing
            archive is kept when `_h_from_plan` refuses),
            no file overlaps the window, or the site is a derived site
            (`Survey.parent_of`), whose archive scripts/decimate_site.py
            (or scripts/diagonal_site.py) writes.
    """
    parent = survey.parent_of(site_name)
    if parent:
        raise ValueError(f"{site_name} is derived from {parent} and has no raw folder: its archive "
                         f"{default_archive_path(survey, site_name)} is written by scripts/decimate_site.py "
                         f"(a diagonal <site>D: scripts/diagonal_site.py)")
    site = survey.site(site_name)
    try:
        site_dirs = survey.site_dirs()
    except OSError:  # data_root on a drive that is not plugged in
        site_dirs = {}
    raw_name = survey.raw_site(site_name)
    if raw_name not in site_dirs:
        # a stale or unmounted data_root: the archive, if there is one, is all there is to read
        kept = Path(out_path) if out_path else default_archive_path(survey, site_name)
        if kept.exists() and not overwrite:
            logger.info(f"{kept} exists, no raw folder {raw_name} under {survey.data_root}, reusing")
            return kept
        raise FileNotFoundError(f"{site_name}: no raw folder {raw_name} under {survey.data_root}"
                                + ("" if kept.exists() else f" and no archive at {kept}"))
    site_dir = site_dirs[raw_name]
    instrument = survey.instrument_of(site_name)
    _check_instrument_keys(survey, site, instrument)
    if site.bursts_of:
        if instrument != "phoenix":
            raise ValueError(f"{site_name}: bursts_of {site.bursts_of}, which is {INSTRUMENTS[instrument]['label']}: "
                             f"only a Phoenix site records bursts")
        out_path = Path(out_path) if out_path else default_archive_path(survey, site_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not overwrite:
            logger.info(f"{out_path} exists, reusing (overwrite=False)")
            return out_path
        return _ingest_bursts(survey, site, site_dir, start, end, out_path)
    electric_gain = _electric_gain(survey, site, instrument, site_dir)
    _check_banks_instrument(site, instrument)
    e_sign = _e_sign(survey, site, instrument)
    _check_e_azimuths(site, instrument)
    phoenix_dir = None
    if instrument == "phoenix":
        phoenix_dir = _calibration_dir(survey, site)
        units = _phoenix_units(survey, site, site_dir, survey.sample_rate_of(site_name), start, end)
        files = [f for _rec, plan in units for fs in plan.files.values() for f in fs]
    elif instrument == "orangebox":
        _orangebox_scales(site)
        units = _orangebox_units(site, site_dir, start, end)
        files = [p for run_plan, _base in units for p in run_plan.paths]
    elif instrument == "mtu5a":
        units = mtu5a.plan_runs(site_dir, site, survey.sample_rate_of(site_name), start, end)
        files = list(dict.fromkeys(unit.recording.ts4 for unit in units))
    else:
        files = select_files(site_dir, start, end, instrument)
    skipped: list[str] = []
    if instrument == "lemi423":
        try:
            files, skipped = readable_b423(files, sample_rate=survey.sample_rate_of(site_name))
        except ValueError as exc:
            raise ValueError(f"{site_name}: {exc}") from None
        for line in skipped:
            logger.warning(f"{site_name}: skipping {line}")
        if not files:
            raise ValueError(f"{site_name}: none of the {len(skipped)} B423 files can be read: "
                             + "; ".join(skipped))

    out_path = Path(out_path) if out_path else default_archive_path(survey, site_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not overwrite:
        logger.info(f"{out_path} exists, reusing (overwrite=False)")
        return out_path

    read_kwargs = dict(
        station_id=site_name,
        dipole_length_ex=site.dipole_length_ex,
        dipole_length_ey=site.dipole_length_ey,
    )
    coil = None  # an EDL site's LEMI-120 response file, for read_run
    if instrument != "lemi423":
        max_run_files = None  # caps LEMI-423 runs only (see the docstring)
    needs_coil = instrument == "lemi423" or (instrument == "edl" and edl_sensor(site) == "lemi120")
    tables: list[Path] = []  # the coil tables read, recorded in every run comment (_calibration_note)
    if needs_coil and site.calibration_fn:
        cal = _calibration_path(survey, site.calibration_fn)
        tables.append(cal)
        if instrument == "lemi423":
            read_kwargs["calibration_fn"] = cal
        else:
            coil = cal
    elif instrument == "lemi423" and not site.h_from:
        logger.warning(
            f"{site_name}: no calibration_fn: magnetic channels will lack a "
            f"coil response and TFs will be wrong"
        )

    rate = (edl_sample_rate(site_dir) if instrument == "edl" else
            survey.sample_rate_of(site_name) if instrument in ("lemi423", "phoenix", "orangebox") else None)
    groups = (units if instrument in ("phoenix", "orangebox", "mtu5a") else
              _group_contiguous(files, max_run_files, instrument, rate=rate))
    # checked before anything is deleted or written: a refused h_from leaves an existing archive in place
    plan = _h_from_plan(survey, site, groups, rate, max_run_files) if site.h_from else None
    station_notes = _h_from_station_notes(site, plan, rate) if plan else []
    if plan and plan["calibration"] is not None:
        tables.append(plan["calibration"])
    calibration = _calibration_note(tables)
    registry = survey.registry_note(site_name)  # None when survey.yaml declares no registry DOI for the site
    borrowing = (f"; hx and hy from {site.h_from} (h_from), {sum(map(bool, plan['pieces']))} of {len(groups)} "
                 f"run(s) covered, {plan['cover']:.1%} of the samples" if plan else "")
    logger.info(
        f"{site_name}: ingesting {len(files)} {INSTRUMENTS[instrument]['label']} files as "
        f"{len(groups)} run(s) -> {out_path}{borrowing}"
    )
    for line in station_notes[1:]:
        logger.warning(f"{site_name}: {line}")
    if out_path.exists():
        out_path.unlink()
    flags = mtu5a.flags_path(out_path) if instrument == "mtu5a" else None  # written after the last run
    if flags is not None:
        flags.unlink(missing_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = None
        levels: list[dict] = []  # every run's channel levels, classified once the site is written
        run_groups = {}
        left_out: list[str] = []  # the spans of runs wholly outside a declared record_window
        for index, group in enumerate(groups):
            if plan and not plan["pieces"][index]:
                continue  # the neighbour does not cover it: recorded in the station's provenance
            if instrument == "lemi423":
                run = read_lemi423(group if len(group) > 1 else group[0], **read_kwargs)
            elif instrument == "phoenix":
                run = _read_phoenix_run(group, site, phoenix_dir)
            elif instrument == "orangebox":
                run = _read_orangebox_run(group, site)
            elif instrument == "mtu5a":
                run = mtu5a.read_run(group, site)
            else:
                run = read_run(instrument, group, site, site_dir, calibration=coil)
                if instrument == "edl":  # the reader returned the samples planned, or the run is refused
                    _check_edl_read(run, group, site_name, float(rate or run.sample_rate))
                if getattr(group, "trim", 0):  # a restart file overlapping the file before it (`_edl_plan`)
                    run = _trim_run_start(run, group.trim, _overlap_note(group, run.sample_rate))
                tested = _test_run_note(group) if instrument == "edl" else ""
                if tested:  # the deployment test run left out at the run's first file
                    run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, tested)
                # the cables in each other's banks: the samples onto the channels of their sensors, before
                # anything reads a channel by name
                banks = _edl_banks_swapped(run, site)
                if banks:
                    run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, banks)
            _keep_channels(run, site)
            # the frame from the site's layout_north and the declared declination, stored and not
            # applied: the channel azimuths stay as recorded
            apply_site_frame(run.station_metadata, site)
            # before the reversed-dipole rule, which reads the exchanged channels; a Phoenix run is read exchanged
            swapped_e = _phoenix_swap_e(run, site) if instrument == "phoenix" else _swap_e(run, site)
            swapped = _swap_h(run, site)
            flipped = _flip_h(run, site)  # after the exchange: the names are the swapped channels
            clock = _shift_clock(run, site)
            if skipped and not run_groups:
                prior = run.run_metadata.comments.value
                note = "skipped unreadable file(s): " + "; ".join(skipped)
                run.run_metadata.comments.value = f"{prior}; {note}" if prior else note
            carried = [c for c in ("ex", "ey") if electric_gain != 1.0 and c in run.dataset]
            if carried:  # the filter is in their chains (read_run); the comment records it in text
                note = f"electric gain {electric_gain:g} on {carried} (declared from the field notes)"
                prior = run.run_metadata.comments.value
                run.run_metadata.comments.value = f"{prior}; {note}" if prior else note
            if instrument == "edl":  # a line's own gain (read_run, add_channel_electric_gains), recorded in text
                for comp, gain in channel_electric_gains(site).items():
                    if comp in run.dataset:
                        note = f"electric gain {gain:g} on {comp} alone (declared electric_gain_{comp})"
                        run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, note)
            if swapped_e:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, swapped_e)
            if swapped:
                prior = run.run_metadata.comments.value
                run.run_metadata.comments.value = f"{prior}; {swapped}" if prior else swapped
            if flipped:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, flipped)
            if clock:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, clock)
            run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, calibration)
            if instrument == "lemi423":
                _standardise_e_orientation(run, site)
                _apply_h_scale(run, site)
            if instrument == "lemi424":
                # the logger's sign convention, then a line a crew laid reversed on top of it
                signed = _apply_e_sign(run, site, e_sign)
                if signed:
                    run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, signed)
                _standardise_e_orientation(run, site)
            if instrument == "orangebox":  # stored in the 0/90 frame: a line laid at 180 or 270 deg is negated
                _standardise_e_orientation(run, site)
            # after swap_e, a LEMI-424's e_sign and the reversed-pair rule: a pair laid off the cardinal
            # axes turned onto magnetic north and east (None, nothing touched, at a cardinal layout)
            turned_e = _rot_e(run, site, instrument)
            if turned_e:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, turned_e)
            # after swap_h, flip_h and h_scale, before rot_h: a tilted sensor's hx, hy, hz levelled in physical units
            levelled = _h_tilt(run, site)
            if levelled:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, levelled)
            # after swap_h, flip_h and h_scale: the pair as the chain calibrates it, turned onto magnetic north
            turned = _rot_h(run, site)
            if turned:
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, turned)
            if registry:  # the instruments' registry DOIs as survey.yaml declares them; data_logger.id keeps the serial
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, registry)
            for note in station_notes + ([registry] if registry else []):
                provenance = run.station_metadata.provenance
                if note not in str(provenance.comments.value or ""):
                    provenance.comments.value = _append_comment(provenance.comments, note)
            # a Phoenix run's dc level against each channel's input rail, an MTU-5A run's against the
            # receiver's clip in counts (upstream issue 78)
            rails = (_phoenix_rails(group[0], group[1].files, bool(swapped), site.swap_e)
                     if instrument == "phoenix" else mtu5a.rails() if instrument == "mtu5a" else None)
            if instrument == "orangebox":  # the 24-bit ADC's rail, +/-2**23 counts, not the record's own extreme
                rails = {c: RAIL_LEVEL * 2.0 ** 23 for c in run.dataset.data_vars}
            if instrument == "orangebox" and plan:  # all five recorded: the neighbour's hx and hy replace the local's
                run.run_metadata.comments.value = _append_comment(run.run_metadata.comments, _drop_own_h(run, site))
            for piece in ([run] if plan is None else _h_from_pieces(run, index, plan, site, rate)):
                # the declared record_window, after every other step: a run clipped, one wholly outside left out
                read_span = (f"{_iso(int(pd.DatetimeIndex(piece.dataset.coords['time'].values[:1]).asi8[0]))} .. "
                             f"{_iso(int(pd.DatetimeIndex(piece.dataset.coords['time'].values[-1:]).asi8[0]))}"
                             if site.record_window else "")
                piece, windowed = _record_window(piece, site)
                if piece is None:
                    left_out.append(read_span)
                    logger.info(f"{site.name}: run {read_span} left out, wholly outside record_window "
                                f"{site.record_window}")
                    continue
                if windowed:
                    piece.run_metadata.comments.value = _append_comment(piece.run_metadata.comments, windowed)
                    logger.info(f"{site.name}: {windowed}")
                # the declared rot_h_parts, after the record_window: the run cut at the parts, each turned by its
                # own angle, the samples outside every part left out
                parts = [(piece, None)] if not site.rot_h_parts else _rot_h_parts(piece, site)
                if not parts:
                    logger.info(f"{site.name}: a run left out, wholly outside rot_h_parts {site.rot_h_parts}")
                for piece, parted in parts:
                    if parted:
                        piece.run_metadata.comments.value = _append_comment(piece.run_metadata.comments, parted)
                    run_id = f"sr{int(piece.sample_rate)}_{len(run_groups) + 1:04d}"
                    piece.run_metadata.id = run_id
                    if station_group is None:
                        station_group = m.add_station(site_name, survey=survey.name)
                        station_group.metadata.update(piece.station_metadata)
                        station_group.write_metadata()
                    levels += _run_levels(piece, site_name, run_id, rails)
                    run_group = station_group.add_run(run_id)
                    run_group.from_runts(piece)
                    run_groups[run_id] = run_group
                    logger.info(f"{site_name}: run {run_id} <- {_describe_group(group)}")
        if site.rot_h_parts:
            if station_group is None:
                raise ValueError(f"{site_name}: no sample of the record lies inside rot_h_parts {site.rot_h_parts}")
            provenance = station_group.metadata.provenance
            for start, end, angle in site.rot_h_parts:
                note = _rot_h_part_note(angle, start, end)
                if note not in str(provenance.comments.value or ""):
                    provenance.comments.value = _append_comment(provenance.comments, note)
            station_group.write_metadata()
        if site.record_window:
            if station_group is None:
                raise ValueError(f"{site_name}: no sample of the record lies inside record_window "
                                 f"{site.record_window}")
            provenance = station_group.metadata.provenance
            for note in _record_window_station_notes(site, left_out):
                if note not in str(provenance.comments.value or ""):
                    provenance.comments.value = _append_comment(provenance.comments, note)
            station_group.write_metadata()
        _record_levels(run_groups, levels, site_name, unit="V" if instrument == "phoenix" else "counts")
        if flags is not None:  # an MTU-5A run per group: no h_from, so the run ids follow the groups
            rows = mtu5a.write_flags(flags, zip(run_groups, groups, strict=True), site)
            logger.info(f"{site_name}: {len(rows)} interval(s) of the MTU-5A tags' saturation, status and clock "
                        f"flags -> {flags}")
    finally:
        m.close_mth5()
    return out_path
