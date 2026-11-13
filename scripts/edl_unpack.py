# -*- coding: utf-8 -*-
"""
Unpack one Earth Data PR6-24 site zip into a standard site folder

A PR6-24 writes hourly ASCII files ``{station}YYMMDDhhmmss.{BX,BY,BZ,EX,EY}``
with ``.TP`` and ``.ambientTemperature`` beside them in day folders ``DDD/``,
a ``.gps`` (Trimble TAIP), ``.gst``, ``.pll`` and ``.msg`` per day,
``config/recorder.ini`` and ``log/recorder.msg``. The logger keeps the files
of earlier deployments on its disk, so a site's zip can hold other stations'
files, files stamped before the GPS locked (dated 2003-01-01), a Windows
recycle bin, chkdsk fragments and processing copies beside the site's own
record.

Every member of the zip is copied once, to one of three places:

- the site folder ``OUT_ROOT/SITE/``, flat: the members named for the
  station ``--station`` whose stamp lies in ``[--start, --end]`` (the five
  channel files, ``.TP`` and ``.ambientTemperature``), the ``.gps``,
  ``.gst``, ``.pll`` and ``.msg`` of the UTC days that hold one of those
  files (with ``--day-logs window``, every one stamped in the window), and
  the deployment's ``config/recorder.ini`` and ``log/recorder.msg``
  when the ini's ``station_long_identifier`` names the station. The station
  of a file is the name before its twelve-digit stamp
  (`mt_io.uoa.pr624.parse_edl_station`, stamp by `parse_edl_timestamp`);
  names compare without case and without a trailing "_" or "-";
- the salvage tree ``--salvage-root``: ``<STATION>/`` for other stations'
  members, flat, shared by every zip unpacked into the same tree;
  ``_unsynced/SITE/`` for the station's own members outside the window;
  ``_recycle_bin/<zip folder>/<STATION>/`` for ``$RECYCLE.BIN`` members by
  station (a recorder.ini by the station it names, a recorder.msg beside
  the bin's only recorder.ini, the rest under ``_no_station/``);
  ``_found000/<zip folder>/`` for chkdsk ``FOUND.nnn`` fragments; and
  ``_other/<zip folder>/<member path>`` for system folders, the logger's
  ``temp/``, members matched by ``--exclude``, nested archives and any
  other member;
- the records folder ``--records``: ``field_sheets/SITE/`` for documents
  (docx, pdf, txt, images, spreadsheets) and for a recorder.ini or
  recorder.msg the site folder does not take, and ``manifests/`` for
  ``SITE_manifest.csv`` and ``SITE_summary.json``.

The deployment's config folder is the only ``config/`` folder outside the
recycle bin and system folders that holds a recorder.ini, or the one
``--config`` names when there are several; its recorder.msg is in the
sibling ``log/`` folder.

Two members bound for the same name in the site folder stop the script
before anything is copied: ``--exclude`` (fnmatch patterns on member paths,
repeatable) sets the unwanted ones aside in ``_other/``. In the salvage tree
and the records, a member whose destination already holds a file of the
same size and CRC-32 is not copied again and its manifest row names that
file; a different file of the same name gets ``__<zip folder>`` before its
extension (and a counter when that is taken too), listed in the summary. An
existing site folder that holds files is written into only with --force.
Before copying, the free space of every drive written to is checked: the
script stops when a drive would fall under --min-free-gb (default 300 GB).

The manifest has one row per zip member: member, bytes, action (kept: the
site folder; salvaged; recorded: the records; directory: a folder entry,
0 bytes, nothing to copy), reason, parsed_station, stamp_utc, destination,
samples (lines of a channel, TP or ambientTemperature file copied to the
site folder, counted as mt-io's `count_samples` counts them) and note. The
summary JSON holds the counts per action and reason, the first and last
kept stamp, the stamps and the whole UTC hours that have all five channel
files, the samples per channel, the recorder.ini found, the renamed salvage
files, and the free space of each drive before and after. --dry-run writes
``SITE_manifest.dryrun.csv`` and ``SITE_summary.dryrun.json`` and copies
nothing.

Usage:
    python scripts/edl_unpack.py ZIP SITE OUT_ROOT --station PREFIX
        --start UTC --end UTC --records DIR --salvage-root DIR
        [--config DIR_IN_ZIP] [--exclude GLOB ...] [--day-logs kept-days|window]
        [--min-free-gb 300]
        [--dry-run] [--force]

Example:
    python scripts/edl_unpack.py site_100.zip TAS100 survey_root --station TAS100
        --start 2016-01-22T01:52:00Z --end 2016-02-21T08:30:00Z
        --records ingest_records
        --salvage-root survey_salvage

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import configparser
import csv
import fnmatch
import json
import os
import re
import shutil
import sys
import time
import zipfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from mt_io.uoa.pr624 import EDL_TIMESTAMP, parse_edl_station, parse_edl_timestamp

CHANNELS = (".BX", ".BY", ".BZ", ".EX", ".EY")
AUXILIARY = (".TP", ".AMBIENTTEMPERATURE")
DAY_LOGS = (".GPS", ".GST", ".PLL", ".MSG")
DOCUMENTS = (".DOCX", ".DOC", ".PDF", ".TXT", ".PNG", ".JPG", ".JPEG", ".XLSX", ".XLS", ".CSV", ".RTF")
ARCHIVES = (".ZIP", ".7Z", ".RAR", ".GZ", ".TAR")
# a stamp before this year was written before the GPS locked (the PR6-24 starts at 2003-01-01)
GPS_LOCK_YEAR = 2010
MANIFEST_COLUMNS = ("member", "bytes", "action", "reason", "parsed_station", "stamp_utc", "destination",
                    "samples", "note")
CHUNK = 1 << 20
GB = 1e9


@dataclass
class Row:
    """One zip member's plan: where it goes and why."""

    info: zipfile.ZipInfo
    action: str = ""
    reason: str = ""
    station: str = ""
    stamp: datetime | None = None
    dest: Path | None = None
    samples: int | None = None
    note: str = ""
    write: bool = True
    kind: str = ""  # channel, auxiliary, day_log or "" for the site folder's bookkeeping
    extra: dict = field(default_factory=dict)


class UnpackError(Exception):
    """A condition that stops the unpacking before anything is copied."""


def norm(station) -> str:
    """Return a station name for comparison: no case, no trailing "_" or "-"."""
    return str(station or "").strip().rstrip("_-").lower()


def parse_utc(text: str) -> datetime:
    """Read an ISO-8601 time as UTC (a time without a zone is taken as UTC)."""
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)


def ini_station(data: bytes) -> str | None:
    """Return the ``station_long_identifier`` of a recorder.ini's text, as written."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string(data.decode("utf-8", "replace"))
    except configparser.Error:
        return None
    if not parser.has_section("recorder"):
        return None
    value = parser["recorder"].get("station_long_identifier")
    return value.strip() if value is not None else None


def file_crc(path: Path) -> int:
    """Return the CRC-32 of a file on disk, as a zip stores it."""
    crc = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def suffix_of(name: str) -> str:
    """Return a file name's extension in upper case ("" when it has none)."""
    return PurePosixPath(name).suffix.upper()


def find_config(infos, config: str | None, skip) -> str | None:
    """Return the member path of the deployment's recorder.ini.

    Args:
        infos (list of ZipInfo): The zip's members.
        config (str or None): The config folder named on the command line.
        skip (callable): True for a member under the recycle bin, a system
            folder or a chkdsk folder.

    Returns:
        str or None: The member path, or None when the zip has no recorder.ini
        outside those folders.

    Raises:
        UnpackError: If --config names no recorder.ini, or several config
            folders hold one and --config names none.
    """
    if config:
        want = config.strip("/").rstrip("/") + "/recorder.ini"
        hits = [i.filename for i in infos if i.filename.lower() == want.lower()]
        if not hits:
            raise UnpackError(f"--config {config}: the zip has no {want}")
        return hits[0]
    found = [i.filename for i in infos if PurePosixPath(i.filename).name.lower() == "recorder.ini"
             and PurePosixPath(i.filename).parent.name.lower() == "config" and not skip(i.filename)]
    if len(found) > 1:
        raise UnpackError(f"several deployment config folders: {', '.join(found)}; name one with --config")
    return found[0] if found else None


def plan(zf: zipfile.ZipFile, args) -> tuple[list[Row], dict]:
    """Decide the destination of every member of a zip.

    Args:
        zf (ZipFile): The site zip.
        args (Namespace): The parsed command line.

    Returns:
        tuple: ``(rows, facts)``: one Row per member in zip order, and the
        recorder.ini facts for the summary.

    Raises:
        UnpackError: If two members are bound for the same name in the site
            folder, or the config folder is ambiguous.
    """
    zip_folder = Path(args.zip).stem
    site_dir = Path(args.out_root) / args.site
    salvage = Path(args.salvage_root)
    records = Path(args.records)
    own = norm(args.station)
    start, end = parse_utc(args.start), parse_utc(args.end)
    infos = zf.infolist()

    def parts(name):
        return [p.lower() for p in PurePosixPath(name).parts]

    def in_recycle(name):
        return "$recycle.bin" in parts(name) or "recycler" in parts(name)

    def in_found(name):
        return any(re.fullmatch(r"found\.\d{3}", p) for p in parts(name)[:-1])

    def in_system(name):
        return "system volume information" in parts(name)[:-1]

    def in_temp(name):
        return "temp" in parts(name)[:-1]

    def skip(name):
        return in_recycle(name) or in_found(name) or in_system(name)

    ini_member = find_config(infos, args.config, skip)
    facts = {"member": ini_member, "station": None, "copied": False, "log_member": None}
    if ini_member:
        facts["station"] = ini_station(zf.read(ini_member))
        facts["copied"] = norm(facts["station"]) == own
        deployment = PurePosixPath(ini_member).parent.parent
        log = (deployment / "log" / "recorder.msg").as_posix().lstrip("./")
        facts["log_member"] = next((i.filename for i in infos if i.filename.lower() == log.lower()), None)
    # the recycle bin's own recorder.ini, which a recycled recorder.msg sits beside
    bin_inis = {}
    for i in infos:
        if in_recycle(i.filename) and PurePosixPath(i.filename).name.lower() == "recorder.ini":
            bin_inis[i.filename] = (ini_station(zf.read(i)) or "").strip().rstrip("_-") or "_no_station"

    rows = []
    for info in infos:
        name = info.filename
        base = PurePosixPath(name).name
        row = Row(info)
        rows.append(row)
        if name.endswith("/"):
            row.action, row.reason, row.write = "directory", "folder entry", False
            continue
        suffix = suffix_of(base)
        stem = PurePosixPath(base).stem if suffix else base
        stamped = EDL_TIMESTAMP.search(stem) is not None and suffix in CHANNELS + AUXILIARY + DAY_LOGS
        if stamped:
            row.station = parse_edl_station(base) or ""
            row.stamp = parse_edl_timestamp(base)
        rel_bin = None
        if in_recycle(name):
            low = parts(name)
            rel_bin = PurePosixPath(*PurePosixPath(name).parts[low.index("$recycle.bin" if "$recycle.bin" in low
                                                                              else "recycler") + 1:])
            if stamped and row.station:
                group = row.station
                target = salvage / "_recycle_bin" / zip_folder / group / base
            elif base.lower() == "recorder.ini":
                group = bin_inis.get(name, "_no_station")
                row.station = group
                target = salvage / "_recycle_bin" / zip_folder / group / base
            elif base.lower() == "recorder.msg" and len(set(bin_inis.values())) == 1:
                group = next(iter(bin_inis.values()))
                target = salvage / "_recycle_bin" / zip_folder / group / base
                row.note = f"beside the recycle bin's recorder.ini ({group})"
            else:
                target = salvage / "_recycle_bin" / zip_folder / "_no_station" / rel_bin
            row.action, row.reason, row.dest = "salvaged", "recycle bin", target
            continue
        if in_found(name):
            row.action, row.reason, row.dest = "salvaged", "chkdsk fragment", salvage / "_found000" / zip_folder / base
            continue
        if in_system(name):
            row.action, row.reason, row.dest = "salvaged", "system folder", salvage / "_other" / zip_folder / name
            continue
        if in_temp(name):
            row.action, row.reason, row.dest = "salvaged", "logger temp folder", salvage / "_other" / zip_folder / name
            continue
        if suffix in DOCUMENTS:
            row.action, row.reason = "recorded", "document"
            row.dest = records / "field_sheets" / args.site / base
            continue
        pattern = next((g for g in args.exclude if fnmatch.fnmatch(name, g)), None)
        if pattern:
            row.action, row.reason = "salvaged", f"excluded by --exclude {pattern}"
            row.dest = salvage / "_other" / zip_folder / name
            continue
        if base.lower() == "recorder.ini":
            station = ini_station(zf.read(info))
            row.station = station or ""
            if name == ini_member and facts["copied"]:
                row.action, row.reason, row.dest = "kept", "deployment recorder.ini", site_dir / base
            else:
                why = ("recorder.ini of another station" if name == ini_member
                       else "recorder.ini outside the deployment config folder")
                row.action, row.reason = "recorded", why
                row.dest = records / "field_sheets" / args.site / name
            continue
        if base.lower() == "recorder.msg":
            if name == facts["log_member"] and facts["copied"]:
                row.action, row.reason, row.dest = "kept", "deployment recorder.msg", site_dir / base
            else:
                row.action, row.reason = "recorded", "recorder.msg the site folder does not take"
                row.dest = records / "field_sheets" / args.site / name
            continue
        if stamped and row.station and row.stamp is None:
            row.action, row.reason = "salvaged", "stamp that is not a date"
            row.dest = salvage / "_other" / zip_folder / name
            continue
        if stamped and row.station and row.stamp is not None:
            row.kind = "channel" if suffix in CHANNELS else "auxiliary" if suffix in AUXILIARY else "day_log"
            if norm(row.station) != own:
                row.action, row.reason = "salvaged", "other station"
                row.dest = salvage / row.station / base
            elif row.kind != "day_log" and start <= row.stamp <= end:
                row.action, row.reason, row.dest = "kept", f"own {row.kind} file in the window", site_dir / base
            elif row.kind == "day_log":
                row.action = "pending"  # decided below, from the kept days
            else:
                row.action = "salvaged"
                row.reason = ("own station, stamp before GPS lock" if row.stamp.year < GPS_LOCK_YEAR
                              else "own station outside the window")
                row.dest = salvage / "_unsynced" / args.site / base
            continue
        row.action = "salvaged"
        row.reason = "nested archive" if suffix in ARCHIVES else "unrecognised member"
        row.dest = salvage / "_other" / zip_folder / name

    kept_days = {r.stamp.date() for r in rows if r.action == "kept" and r.kind in ("channel", "auxiliary")}
    for r in rows:
        if r.action != "pending":
            continue
        if r.stamp.date() in kept_days:
            r.action, r.reason, r.dest = "kept", "own day log of a kept day", site_dir / PurePosixPath(r.info.filename).name
        elif args.day_logs == "window" and start <= r.stamp <= end:
            r.action, r.reason, r.dest = "kept", "own day log in the window", site_dir / PurePosixPath(r.info.filename).name
        else:
            r.action = "salvaged"
            r.reason = ("own station, stamp before GPS lock" if r.stamp.year < GPS_LOCK_YEAR
                        else "own day log of a day without kept files")
            r.dest = salvage / "_unsynced" / args.site / PurePosixPath(r.info.filename).name

    # two members bound for one name in the site folder: refused
    by_name = defaultdict(list)
    for r in rows:
        if r.action == "kept":
            by_name[r.dest.name.lower()].append(r.info.filename)
    clashes = {k: v for k, v in by_name.items() if len(v) > 1}
    if clashes:
        lines = [f"  {k}: {', '.join(v)}" for k, v in sorted(clashes.items())]
        raise UnpackError(f"{len(clashes)} file name(s) in the site folder come from more than one member "
                          f"(set the unwanted ones aside with --exclude):\n" + "\n".join(lines[:20]))
    resolve_shared(rows, zip_folder)
    return rows, facts


def resolve_shared(rows: list[Row], zip_folder: str) -> None:
    """Settle the salvage and records destinations that are already taken.

    A destination taken by an identical file (same size and CRC-32), on disk
    or planned earlier in this zip, is reused without a copy. A different file
    gets ``__<zip folder>`` before its extension, then a counter.

    Args:
        rows (list of Row): The plan, changed in place.
        zip_folder (str): The zip's stem, used in a new name.
    """
    taken: dict[str, tuple[int, int]] = {}
    for r in rows:
        if r.action not in ("salvaged", "recorded") or r.dest is None:
            continue
        want = (r.info.CRC, r.info.file_size)
        candidate, n = r.dest, 0
        while True:
            key = str(candidate).lower()
            if key in taken:
                have = taken[key]
            elif candidate.is_file():
                have = (file_crc(candidate), candidate.stat().st_size)
            else:
                have = None
            if have is None or have == want:
                break
            n += 1
            tag = f"__{zip_folder}" if n == 1 else f"__{zip_folder}_{n}"
            candidate = r.dest.with_name(f"{r.dest.stem}{tag}{r.dest.suffix}")
        if candidate != r.dest:
            r.note = "; ".join(t for t in (r.note, f"renamed: {r.dest.name} holds another file") if t)
            r.dest = candidate
        key = str(candidate).lower()
        if key in taken or candidate.is_file():
            r.write = False
            r.note = "; ".join(t for t in (r.note, "identical file already at the destination") if t)
        taken[key] = want


def free_gb(path: Path) -> float:
    """Return the free space of the drive that holds a path (its nearest existing parent)."""
    p = Path(path).resolve()
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / GB


def drive_of(path: Path) -> str:
    """Return the drive (anchor) of a path."""
    return Path(path).resolve().anchor


def copy_member(zf: zipfile.ZipFile, row: Row) -> None:
    """Copy one member to its destination through a ``.part`` file, counting lines of a site file."""
    row.dest.parent.mkdir(parents=True, exist_ok=True)
    part = row.dest.with_name(row.dest.name + ".part")
    count = row.action == "kept" and row.kind in ("channel", "auxiliary")
    lines = 0
    with zf.open(row.info) as src, open(part, "wb") as out:
        while chunk := src.read(CHUNK):
            out.write(chunk)
            if count:
                lines += chunk.count(b"\n")
    os.replace(part, row.dest)
    stamp = time.mktime(row.info.date_time + (0, 0, -1))
    os.utime(row.dest, (stamp, stamp))
    if count:
        row.samples = lines


def summarise(rows: list[Row], facts: dict, args, free_before: dict, free_after: dict, planned: dict,
              elapsed: float) -> dict:
    """Build the summary JSON of one zip."""
    kept = [r for r in rows if r.action == "kept" and r.kind == "channel"]
    by_stamp = defaultdict(set)
    for r in kept:
        by_stamp[r.stamp].add(suffix_of(r.info.filename))
    full = sorted(s for s, comps in by_stamp.items() if set(CHANNELS) <= comps)
    hours = {s.replace(minute=0, second=0) for s in full}
    samples = Counter()
    for r in kept:
        if r.samples is not None:
            samples[suffix_of(r.info.filename).lstrip(".")] += r.samples
    renamed = [{"member": r.info.filename, "destination": str(r.dest)} for r in rows if "renamed" in r.note]
    return {
        "zip": str(Path(args.zip).resolve()), "site": args.site, "station": args.station,
        "window": [args.start, args.end], "dry_run": args.dry_run,
        "config": facts, "exclude": args.exclude, "day_logs": args.day_logs,
        "members": len(rows), "uncompressed_bytes": sum(r.info.file_size for r in rows),
        "counts_by_action": dict(Counter(r.action for r in rows)),
        "counts_by_reason": {f"{a} | {b}": n for (a, b), n in sorted(Counter((r.action, r.reason) for r in rows).items())},
        "bytes_by_action": {a: sum(r.info.file_size for r in rows if r.action == a)
                            for a in sorted({r.action for r in rows})},
        "first_kept_stamp": min(by_stamp).strftime("%Y-%m-%dT%H:%M:%SZ") if by_stamp else None,
        "last_kept_stamp": max(by_stamp).strftime("%Y-%m-%dT%H:%M:%SZ") if by_stamp else None,
        "kept_stamps_all_five": len(full), "kept_hours_all_five": len(hours),
        "kept_stamps_any_channel": len(by_stamp),
        "samples_by_channel": dict(samples) if not args.dry_run else None,
        "renamed_in_salvage": renamed,
        "planned_write_gb_by_drive": {k: round(v / GB, 3) for k, v in planned.items()},
        "free_gb_before": {k: round(v, 1) for k, v in free_before.items()},
        "free_gb_after": {k: round(v, 1) for k, v in free_after.items()},
        "min_free_gb": args.min_free_gb, "elapsed_s": round(elapsed, 1),
        "written_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_records(rows: list[Row], summary: dict, args) -> tuple[Path, Path]:
    """Write the manifest CSV and the summary JSON into ``<records>/manifests/``."""
    folder = Path(args.records) / "manifests"
    folder.mkdir(parents=True, exist_ok=True)
    tag = ".dryrun" if args.dry_run else ""
    manifest = folder / f"{args.site}_manifest{tag}.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MANIFEST_COLUMNS)
        for r in rows:
            w.writerow([r.info.filename, r.info.file_size, r.action, r.reason, r.station,
                        r.stamp.strftime("%Y-%m-%dT%H:%M:%SZ") if r.stamp else "",
                        "" if r.dest is None else str(r.dest),
                        "" if r.samples is None else r.samples, r.note])
    out = folder / f"{args.site}_summary{tag}.json"
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return manifest, out


def main(argv=None) -> int:
    """Unpack one zip.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 2 when the site folder exists without --force or
        a drive would fall under the free-space floor, 3 when the plan is
        refused (a name clash in the site folder, an ambiguous config).
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("zip", help="the site's PR6-24 zip")
    parser.add_argument("site", help="site name: the folder under OUT_ROOT")
    parser.add_argument("out_root", help="the survey's raw-data root (site folders only)")
    parser.add_argument("--station", required=True, help="the station name the site's files carry")
    parser.add_argument("--start", required=True, help="window start, ISO UTC (e.g. 2016-01-22T02:00:00Z)")
    parser.add_argument("--end", required=True, help="window end, ISO UTC; both ends included")
    parser.add_argument("--records", required=True, help="folder for manifests/ and field_sheets/")
    parser.add_argument("--salvage-root", required=True, help="folder for every member the site folder does not take")
    parser.add_argument("--config", help="the deployment's config folder in the zip, when there are several")
    parser.add_argument("--exclude", action="append", default=[],
                        help="fnmatch pattern of member paths to set aside in _other/ (repeatable)")
    parser.add_argument("--day-logs", choices=("kept-days", "window"), default="kept-days",
                        help="the station's .gps/.gst/.pll/.msg kept: those of the days with a kept channel "
                        "file (default), or every one stamped in the window")
    parser.add_argument("--min-free-gb", type=float, default=300.0, help="free-space floor per drive (GB)")
    parser.add_argument("--dry-run", action="store_true", help="write the manifest and summary only")
    parser.add_argument("--force", action="store_true", help="write into an existing site folder")
    args = parser.parse_args(argv)

    t0 = time.time()
    site_dir = Path(args.out_root) / args.site
    if not args.dry_run and site_dir.is_dir() and any(site_dir.iterdir()) and not args.force:
        print(f"ERROR {site_dir} exists and holds files: pass --force to write into it")
        return 2
    with zipfile.ZipFile(args.zip) as zf:
        try:
            rows, facts = plan(zf, args)
        except UnpackError as exc:
            print(f"ERROR {Path(args.zip).name}: {exc}")
            return 3
        planned = Counter()
        for r in rows:
            if r.write and r.dest is not None:
                planned[drive_of(r.dest)] += r.info.file_size
        targets = {drive_of(p): p for p in (Path(args.out_root), Path(args.salvage_root), Path(args.records))}
        free_before = {d: free_gb(p) for d, p in targets.items()}
        short = {d: free_before[d] - planned[d] / GB for d in targets if free_before[d] - planned[d] / GB < args.min_free_gb}
        if short:
            print("ERROR the copy would leave " + ", ".join(f"{d} {v:.0f} GB" for d, v in short.items())
                  + f" free, under the {args.min_free_gb:g} GB floor")
            return 2
        if not args.dry_run:
            for r in rows:
                if r.write and r.dest is not None:
                    copy_member(zf, r)
    free_after = {d: free_gb(p) for d, p in targets.items()}
    summary = summarise(rows, facts, args, free_before, free_after, planned, time.time() - t0)
    manifest, out = write_records(rows, summary, args)
    print(f"{args.site}: {summary['members']} members, " + ", ".join(f"{k} {v}" for k, v in summary["counts_by_action"].items())
          + f"; kept {summary['first_kept_stamp']} to {summary['last_kept_stamp']}, "
          f"{summary['kept_hours_all_five']} h with all five channels"
          + (" (dry run)" if args.dry_run else "") + f"; {manifest.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
