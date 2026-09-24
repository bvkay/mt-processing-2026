# -*- coding: utf-8 -*-
"""
Build the sites block of the Burra survey.yaml from the field sheets

The Burra-specific counterpart of ``site_table_to_yaml.py``. The Burra field
sheet has a different layout (short site names, a combined
"Azimuth (Ex, Ey)" cell, no positions for the Sep-Oct 2018 phase), and the
clock status is kept in two separate timing sheets.

Sources, all under the survey's ``data_root``:

* ``Burra_DeploymentNotes.xlsx`` / "Deployment Notes": the older field sheet.
* ``BurraTimingPhase2.xlsx`` / "Deployment Notes": the newer field sheet, with
  the Sep-Oct 2018 phase filled in. Same columns: dipole lengths, azimuths,
  positions, free-form notes; one row per deployment, short names (b1, b10r).
  The two are merged as a union keyed by short name. Where both carry a
  non-empty value for a field the script uses, the newer sheet's value is
  kept and the older value is appended to that site's ``notes`` as a
  "conflict: ..." string.
* ``Burra_Timing.xlsx`` / "Sheet1": clock status for the June 2018 phases.
* ``BurraTimingPhase2.xlsx`` / "Sheet2": clock status for Sep-Oct 2018.
* ``lemi423_metadata_summary.csv``: positions read from the B423 headers,
  used where the field sheet has none and as a cross-check where it has
  both, plus the recording window of every folder.

The site list is the set of zip stems in ``data_root`` (site name = folder
name = zip stem); a few folders have no field-sheet row.

Each site also gets its ``remote``. The dedicated remote is one location
redeployed once per stage as the folders Burra54, Burra54rr, Burra54rr2,
Burra54rr3 and Burra54rr4, so a site's remote is the Burra54* run whose
recording window overlaps the site's for the longest time. A site that
overlaps none of them gets a note instead, and the Burra54* folders get no
``remote``.

Usage:
    python scripts/burra_notes_to_yaml.py surveys/burra/survey.yaml

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from textwrap import indent

import pandas as pd
import yaml
from loguru import logger

# (workbook, sheet) oldest first; later sheets take precedence where values conflict
DEPLOYMENT_SHEETS = [
    ("Burra_DeploymentNotes.xlsx", "Deployment Notes"),
    ("BurraTimingPhase2.xlsx", "Deployment Notes"),
]
# columns this script writes out; these alone are merged and conflict-checked,
# so cosmetic differences elsewhere stay out of the notes
MERGED_COLUMNS = [
    "UnixTime",
    "Lat",
    "Long",
    "Elevation",
    "Azimuth (Ex, Ey)",
    "Ex Length (m)",
    "Ey Length (m)",
    "Notes",
]
METADATA_CSV = "lemi423_metadata_summary.csv"
# (workbook, sheet, column holding the Correct/Behind/No data flag)
TIMING_SHEETS = [
    ("Burra_Timing.xlsx", "Sheet1", "TIME"),
    ("BurraTimingPhase2.xlsx", "Sheet2", "Time"),
]
# not an MT site folder: a Zonge dataset parked in the same directory
EXCLUDE_STEMS = {"Burra_PrincessRoyal_Zonge_2019"}

VALID_AZIMUTHS = ("270", "180", "90", "0")
NO_FIELD_ROW_NOTE = "no field-sheet row; dipoles/azimuths are survey defaults"
# the dedicated remote: one location, one folder per deployment stage
REMOTE_FOLDER_PREFIX = "Burra54"
NO_REMOTE_NOTE = "no Burra54 remote deployment overlaps this site"
# a field-sheet position and the B423 header position further apart than this
# means one of the two is for a different site
POSITION_TOLERANCE_KM = 0.2
# A row's UnixTime is the deployment epoch and equals the folder's first B423
# filename for every clean case, so a row further than this from the folder's
# first-file epoch describes a different run. The CSV's "Start Time" column
# runs a constant +8 h ahead of the file epochs and is unsuitable for this.
MATCH_TOLERANCE_S = 6 * 3600.0


def site_folders(data_root: Path) -> list[str]:
    """Return the site list: one zip per site, site name = zip stem."""
    return sorted(p.stem for p in data_root.glob("*.zip") if p.stem not in EXCLUDE_STEMS)


def is_remote_folder(name: str) -> bool:
    """Check whether a folder is a deployment of the dedicated remote (Burra54, Burra54rr ... Burra54rr4)."""
    return str(name).startswith(REMOTE_FOLDER_PREFIX)


def site_number(name: str) -> int | None:
    """Return the site number shared by a site's deployments: b18/b18r/Burra18repeat -> 18."""
    m = re.match(r"(?:b|burra)0*(\d+)", str(name).strip().lower())
    return int(m.group(1)) if m else None


def short_to_folder(short: str, folders: set[str]) -> str | None:
    """Map a field-sheet short name to its folder: b1 -> Burra01, b10r -> Burra10repeat.

    The repeat suffix is spelled two ways in the raw data ("repeat" and "r"),
    so both are tried and the spelling that exists is returned.

    Args:
        short (str): Short site name from the field sheet.
        folders (set[str]): Existing folder names.

    Returns:
        str | None: The folder name, or None when no spelling exists.
    """
    m = re.fullmatch(r"b(\d+)([a-z0-9]*)", str(short).strip().lower())
    if not m:
        return None
    base, suffix = f"Burra{int(m.group(1)):02d}", m.group(2)
    if suffix == "":
        candidates = [base]
    elif suffix == "r":
        candidates = [base + "repeat", base + "r"]
    else:
        candidates = [base + suffix]
    return next((c for c in candidates if c in folders), None)


def _decompose_azimuths(token: str) -> list[str]:
    """Split a run-together azimuth cell ('180270') into two valid azimuths.

    The cell is split when its decomposition into {0, 90, 180, 270} is
    unique, so the result is a parse rather than a guess; the caller keeps
    the raw cell text in the site's notes.

    Returns:
        list[str]: The two azimuths, or [token] when the split is not unique.
    """
    splits = [
        [a, token[len(a) :]]
        for a in VALID_AZIMUTHS
        if token.startswith(a) and token[len(a) :] in VALID_AZIMUTHS
    ]
    return splits[0] if len(splits) == 1 else [token]


def split_azimuths(cell) -> tuple[float, float]:
    """Parse an "Azimuth (Ex, Ey)" cell: '180, 90' -> (180.0, 90.0).

    Raises:
        ValueError: When the cell does not hold two of 0/90/180/270.
    """
    text = str(cell).strip()
    parts = [p for p in re.split(r"[,;/\s]+", text) if p]
    if len(parts) == 1:
        parts = _decompose_azimuths(parts[0])
    if len(parts) != 2 or any(p not in VALID_AZIMUTHS for p in parts):
        raise ValueError(
            f"unexpected azimuth cell {text!r}: expected two of {VALID_AZIMUTHS}"
        )
    return float(parts[0]), float(parts[1])


def km_between(lat1, lon1, lat2, lon2) -> float:
    """Great-circle (haversine) distance in km between two points in degrees."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clean(value):
    """Normalise a spreadsheet cell: None when blank, else the stripped value."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def as_float(value):
    """Convert a cell to float, or None when it is not a number (numpy scalars included)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# typographic characters the field sheet uses, mapped to their ASCII forms
# (code points, so this file is plain ASCII itself)
ASCII_SUBSTITUTIONS = {
    chr(0x2010): "-",  # hyphen
    chr(0x2011): "-",  # non-breaking hyphen
    chr(0x2012): "-",  # figure dash
    chr(0x2013): "-",  # en dash
    chr(0x2014): "-",  # em dash
    chr(0x2018): "'",  # left single quote
    chr(0x2019): "'",  # right single quote / apostrophe
    chr(0x201C): '"',  # left double quote
    chr(0x201D): '"',  # right double quote
    chr(0x00B0): " deg",  # degree sign
    chr(0x00A0): " ",  # non-breaking space
    chr(0x2026): "...",  # ellipsis
}


def ascii_text(text: str) -> str:
    """Convert note text to plain ASCII: substitute known characters, drop the rest."""
    for bad, good in ASCII_SUBSTITUTIONS.items():
        text = text.replace(bad, good)
    stripped = text.encode("ascii", "ignore").decode("ascii")
    if stripped != text:
        logger.warning(f"dropped non-ASCII characters from a note: {text!r}")
    return stripped


def same_value(a, b) -> bool:
    """Compare two spreadsheet cells.

    Numbers compare by value (int 13 == float 13.0, as the two sheets store
    them differently); everything else compares as text.
    """
    fa, fb = as_float(a), as_float(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def read_deployment_notes(data_root: Path) -> tuple[dict, dict, list]:
    """Read and merge both field sheets.

    The rows are merged as a union keyed by the short site name: a later
    sheet's non-empty value is kept, an earlier one fills a gap, and a real
    disagreement is recorded for the site's notes. A row whose merged columns
    are all empty (b44/b56/b71 in the older sheet) is a placeholder and is
    dropped.

    Args:
        data_root (Path): Folder holding the workbooks.

    Returns:
        tuple[dict, dict, list]: {short name: merged row}, {short name:
        [conflicts]}, and the short names whose row was a blank placeholder.
    """
    rows: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    conflicts: dict[str, list[str]] = {}

    for workbook, sheet in DEPLOYMENT_SHEETS:
        df = pd.read_excel(data_root / workbook, sheet_name=sheet, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        for record in df.to_dict("records"):
            short = clean(record.get("SiteName"))
            if short is None:
                continue
            short = str(short).lower()
            row = rows.setdefault(short, {})
            source = sources.setdefault(short, {})
            for column in MERGED_COLUMNS:
                value = clean(record.get(column))
                if value is None:
                    continue
                if column in row and not same_value(row[column], value):
                    conflicts.setdefault(short, []).append(
                        f'conflict: {source[column]} {column} "{row[column]}"'
                    )
                row[column] = value
                source[column] = workbook

    placeholders: list[str] = []
    for short in [s for s, row in rows.items() if not row]:
        logger.info(f"{short}: field-sheet row is a blank placeholder - treating as absent")
        placeholders.append(short)
        rows.pop(short)
    return rows, conflicts, placeholders


def assign_rows(rows: dict, folders: list[str], starts: dict, issues: list) -> tuple[dict, dict, list]:
    """Pair field-sheet rows with folders by name, then correct by deployment time.

    The zips do not always carry the name the field sheet used (Burra18 holds
    the September run and Burra18repeat the June one), so a name match whose
    ``UnixTime`` is more than ``MATCH_TOLERANCE_S`` from the folder's first
    B423 epoch is re-tested against the other rows for the same site number.

    Args:
        rows (dict): Merged field-sheet rows by short name.
        folders (list[str]): Site folders.
        starts (dict): First B423 epoch by folder.
        issues (list): List that problems are appended to.

    Returns:
        tuple[dict, dict, list]: {folder: (short, row)}, {folder: [extra
        notes]} and the short names that map to no folder.

    Raises:
        ValueError: When time matching assigns one row to two folders.
    """
    folder_set = set(folders)
    by_name = {}
    unmapped = []
    for short in rows:
        folder = short_to_folder(short, folder_set)
        if folder is None:
            unmapped.append(short)
            continue
        if folder in by_name:
            logger.warning(
                f"{folder}: rows {by_name[folder]!r} and {short!r} both map to it "
                f"by name - keeping the first"
            )
            continue
        by_name[folder] = short

    groups: dict[int, list[str]] = {}
    for short in rows:
        groups.setdefault(site_number(short), []).append(short)

    def offset(short, folder):
        """Return |UnixTime - first B423 epoch| in s, or None when either is missing."""
        unix, start = as_float(rows[short].get("UnixTime")), starts.get(folder)
        return None if unix is None or start is None else abs(unix - start)

    assigned, extra_notes = dict(by_name), {}
    for folder, short in by_name.items():
        gap = offset(short, folder)
        if gap is None or gap <= MATCH_TOLERANCE_S:
            continue
        candidates = [
            other
            for other in groups.get(site_number(folder), [])
            if other != short
            and offset(other, folder) is not None
            and offset(other, folder) <= MATCH_TOLERANCE_S
        ]
        if len(candidates) == 1:
            assigned[folder] = candidates[0]
            note = (
                f"field-sheet row {candidates[0]} matched by deployment time "
                f"(name swap in zips)"
            )
        else:
            span = f"{gap / 86400:.0f} days" if gap >= 2 * 86400 else f"{gap / 3600:.1f} h"
            note = (
                f"field-sheet row {short} is {span} from this folder's first "
                f"B423 file and no other row fits - check which deployment "
                f"this folder holds"
            )
        extra_notes.setdefault(folder, []).append(note)
        issues.append(f"{folder}: {note}")

    claimed = [f for f, s in assigned.items() if list(assigned.values()).count(s) > 1]
    if claimed:
        raise ValueError(f"deployment-time matching assigned one row to two folders: {claimed}")
    return {f: (s, rows[s]) for f, s in assigned.items()}, extra_notes, unmapped


def read_timing(data_root: Path) -> dict[str, str]:
    """Read both timing sheets.

    The flags are keyed by short name so that each follows its row through
    the deployment-time matching in ``assign_rows``.

    Args:
        data_root (Path): Folder holding the workbooks.

    Returns:
        dict[str, str]: {short name: 'Correct' | 'Behind' | 'No data'}.
    """
    flags: dict[str, str] = {}
    for workbook, sheet, column in TIMING_SHEETS:
        df = pd.read_excel(data_root / workbook, sheet_name=sheet, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        for row in df.to_dict("records"):
            short, flag = clean(row.get("SiteName")), clean(row.get(column))
            if short is None or flag is None:
                continue
            short = str(short).lower()
            if flags.get(short, flag) != flag:
                logger.warning(
                    f"{short}: timing flag {flags[short]!r} != {flag!r} "
                    f"({workbook}/{sheet}) - keeping the later one"
                )
            flags[short] = str(flag)
    return flags


def iso_epoch(value) -> float | None:
    """Convert a "Start/End Time ISO" cell to unix epoch seconds, or None when unparseable."""
    stamp = pd.to_datetime(clean(value), utc=True, errors="coerce")
    return None if pd.isna(stamp) else float(stamp.timestamp())


def read_header_metadata(data_root: Path) -> dict[str, dict]:
    """Read the B423 header summary CSV.

    ``start`` is the folder's first B423 filename as a unix epoch, read from
    the CSV without opening the zips; the field sheet's ``UnixTime`` records
    the same instant. ``window_start``/``window_end`` come from the CSV's ISO
    columns and are compared with each other alone: they run a constant few
    hours ahead of the file epochs, which cancels in an overlap between two
    folders.

    Args:
        data_root (Path): Folder holding the CSV.

    Returns:
        dict[str, dict]: {folder: {latitude, longitude, elevation, start,
        window_start, window_end}}.
    """
    df = pd.read_csv(data_root / METADATA_CSV)
    out = {}
    for row in df.to_dict("records"):
        first = str(clean(row.get("First File")) or "")
        stem = first.split(".")[0]
        out[str(row["Folder"]).strip()] = {
            "latitude": clean(row.get("Lat")),
            "longitude": clean(row.get("Lon")),
            "elevation": clean(row.get("Alt")),
            "start": float(stem) if stem.isdigit() else None,
            "window_start": iso_epoch(row.get("Start Time ISO")),
            "window_end": iso_epoch(row.get("End Time ISO")),
        }
    return out


def assign_remotes(folders: list[str], headers: dict) -> dict[str, str]:
    """Assign each site the Burra54* remote run that overlaps it longest.

    The dedicated remote sat at one location and was redeployed once per
    stage, so a site's remote folder is decided by time alone: the Burra54*
    recording window with the largest overlap with the site's. A site whose
    window overlaps none of them, or that has no window in the header
    summary, is left out, as are the Burra54* folders themselves.

    Args:
        folders (list[str]): Site folders.
        headers (dict): Output of `read_header_metadata`.

    Returns:
        dict[str, str]: {site folder: Burra54* folder}.
    """
    windows = {
        f: (headers.get(f, {}).get("window_start"), headers.get(f, {}).get("window_end"))
        for f in folders
    }
    remotes = {f: w for f, w in windows.items() if is_remote_folder(f) and None not in w}
    if not remotes:
        logger.warning(f"no {REMOTE_FOLDER_PREFIX}* folder has a recording window")

    out = {}
    for folder, (start, end) in windows.items():
        if is_remote_folder(folder) or start is None or end is None:
            continue
        overlaps = {
            remote: min(end, remote_end) - max(start, remote_start)
            for remote, (remote_start, remote_end) in remotes.items()
        }
        best = max(overlaps, key=overlaps.get, default=None)
        if best is not None and overlaps[best] > 0:
            out[folder] = best
    return out


def build_site(folder, row, header, defaults, timing, remote, conflicts, extra_notes, issues) -> dict:
    """Build one site entry from the field sheet, with B423 header metadata as fallback.

    Args:
        folder (str): Site folder.
        row (dict | None): Merged field-sheet row, or None when the folder
            has none (the survey defaults are used).
        header (dict | None): The folder's B423 header metadata.
        defaults (dict): The survey's `defaults:` block.
        timing (str | None): Clock status flag.
        remote (str | None): Burra54* remote folder.
        conflicts (list[str] | None): Field-sheet conflicts for the notes.
        extra_notes (list[str] | None): Further notes.
        issues (list): List that problems are appended to.

    Returns:
        dict: The site entry.
    """
    notes: list[str] = []
    header = header or {}
    conflicts = list(conflicts or [])

    if row is None:
        entry = {
            "dipole_length_ex": float(defaults.get("dipole_length_ex", 0.0)),
            "dipole_length_ey": float(defaults.get("dipole_length_ey", 0.0)),
            "azimuth_ex": float(defaults.get("azimuth_ex", 0.0)),
            "azimuth_ey": float(defaults.get("azimuth_ey", 90.0)),
        }
        notes.append(NO_FIELD_ROW_NOTE)
        latitude = longitude = elevation = None
    else:
        raw_azimuth = str(clean(row.get("Azimuth (Ex, Ey)")))
        azimuth_ex, azimuth_ey = split_azimuths(raw_azimuth)
        if raw_azimuth.replace(" ", "") != f"{azimuth_ex:.0f},{azimuth_ey:.0f}":
            # malformed cell: the raw text is recorded in the notes
            notes.append(f'azimuth cell read as "{azimuth_ex:.0f}, {azimuth_ey:.0f}" '
                         f'from raw text "{raw_azimuth}"')
            issues.append(f"{folder}: azimuth cell {raw_azimuth!r}")
        entry = {
            "dipole_length_ex": float(clean(row.get("Ex Length (m)"))),
            "dipole_length_ey": float(clean(row.get("Ey Length (m)"))),
            "azimuth_ex": azimuth_ex,
            "azimuth_ey": azimuth_ey,
        }
        latitude = clean(row.get("Lat"))
        longitude = clean(row.get("Long"))
        elevation = clean(row.get("Elevation"))

    if latitude is not None and header.get("latitude") is not None:
        gap = km_between(
            float(latitude), float(longitude), float(header["latitude"]), float(header["longitude"])
        )
        if gap > POSITION_TOLERANCE_KM:
            note = f"field-sheet position {gap * 1000:.0f} m from the B423 header position"
            notes.append(note)
            issues.append(f"{folder}: {note}")
    if latitude is None:
        latitude, longitude = header.get("latitude"), header.get("longitude")
    if elevation is None:
        elevation = header.get("elevation")

    entry["latitude"] = round(float(latitude), 6) if latitude is not None else None
    entry["longitude"] = round(float(longitude), 6) if longitude is not None else None
    entry["elevation"] = float(elevation) if elevation is not None else None

    if timing is not None:
        entry["timing"] = timing
    if remote is not None:
        entry["remote"] = remote
    notes.extend(extra_notes or [])
    for conflict in conflicts:
        notes.append(conflict)
        issues.append(f"{folder}: {conflict}")
    if row is not None and clean(row.get("Notes")) is not None:
        notes.insert(0, str(clean(row.get("Notes"))))
    if notes:
        # keep notes plain ASCII: they are read in terminals and copied into
        # logs, and the field sheet uses typographic dashes in places
        entry["notes"] = ascii_text("; ".join(notes))
    return entry


def write_sites_block(yaml_path: Path, sites: dict) -> None:
    """Replace the `sites:` block in place, keeping the rest of the file unchanged.

    Comments outside the block are kept.

    Args:
        yaml_path (Path): survey.yaml to update.
        sites (dict): New site entries.

    Raises:
        ValueError: When `sites:` is missing, repeated or not the last
            top-level key.
    """
    text = yaml_path.read_text(encoding="utf-8")
    if text.count("\nsites:") != 1:
        raise ValueError(f"expected exactly one top-level 'sites:' key in {yaml_path}")
    head, _, tail = text.partition("\nsites:")
    trailing = [ln for ln in tail.splitlines()[1:] if ln and not ln.startswith((" ", "#"))]
    if trailing:
        raise ValueError(f"'sites:' is not the last top-level key in {yaml_path}: {trailing[0]!r}")
    body = yaml.safe_dump(sites, sort_keys=False, allow_unicode=True, default_flow_style=False)
    yaml_path.write_text(f"{head}\nsites:\n{indent(body, '  ')}", encoding="utf-8")


def main(yaml_path: str) -> None:
    """Build and write the Burra `sites:` block.

    Args:
        yaml_path (str): The Burra survey.yaml.
    """
    yaml_path = Path(yaml_path)
    config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data_root = Path(config["data_root"])
    defaults = config.get("defaults") or {}

    folders = site_folders(data_root)
    logger.info(f"{len(folders)} site folders under {data_root}")

    rows, conflicts, placeholders = read_deployment_notes(data_root)
    timing_by_short = read_timing(data_root)
    headers = read_header_metadata(data_root)

    issues: list[str] = []
    starts = {f: h["start"] for f, h in headers.items()}
    matched, extra_notes, unmapped = assign_rows(rows, folders, starts, issues)

    # the clock flag belongs to the deployment, so it follows its row's folder
    row_folder = {short: folder for folder, (short, _) in matched.items()}
    timing = {}
    for short, flag in timing_by_short.items():
        folder = row_folder.get(short) or short_to_folder(short, set(folders))
        if folder is None:
            logger.warning(f"timing row {short!r} maps to no folder")
            continue
        timing[folder] = flag

    remotes = assign_remotes(folders, headers)
    no_remote = [f for f in folders if f not in remotes and not is_remote_folder(f)]
    for folder in no_remote:
        extra_notes.setdefault(folder, []).append(NO_REMOTE_NOTE)

    sites = {
        folder: build_site(
            folder,
            matched[folder][1] if folder in matched else None,
            headers.get(folder),
            defaults,
            timing.get(folder),
            remotes.get(folder),
            conflicts.get(matched[folder][0]) if folder in matched else None,
            extra_notes.get(folder),
            issues,
        )
        for folder in folders
    }
    write_sites_block(yaml_path, sites)

    missing = [f for f in folders if f not in matched]
    logger.info(f"wrote {len(sites)} sites to {yaml_path}")
    if missing:
        logger.warning(f"{len(missing)} folder(s) with no field-sheet row: {missing}")
    no_folder = sorted(
        set(unmapped) | {s for s in placeholders if short_to_folder(s, set(folders)) is None}
    )
    if no_folder:
        logger.warning(f"field-sheet name(s) mapping to no folder: {no_folder}")
    for issue in issues:
        logger.warning(issue)
    counts = {flag: sum(1 for s in sites.values() if s.get("timing") == flag) for flag in sorted(set(timing.values()))}
    counts["unknown"] = sum(1 for s in sites.values() if "timing" not in s)
    logger.info(f"timing flags: {counts}")
    remote_counts = {
        remote: sum(1 for r in remotes.values() if r == remote)
        for remote in sorted(set(remotes.values()))
    }
    logger.info(f"remote reference: {remote_counts}")
    if no_remote:
        logger.warning(
            f"{len(no_remote)} site(s) with no overlapping "
            f"{REMOTE_FOLDER_PREFIX}* deployment: {no_remote}"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "surveys/burra/survey.yaml")
