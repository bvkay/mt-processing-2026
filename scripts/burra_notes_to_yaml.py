"""Build the `sites:` block of the Burra survey.yaml from the field sheets.

One-off, Burra-specific counterpart to ``site_table_to_yaml.py`` - the Burra
field sheet is laid out differently (short site names, a combined
"Azimuth (Ex, Ey)" cell, no positions for the Sep-Oct 2018 phase) and the
clock status lives in two separate timing sheets.

Sources, all under the survey's ``data_root``:

* ``Burra_DeploymentNotes.xlsx`` / "Deployment Notes" - the older field sheet.
* ``BurraTimingPhase2.xlsx`` / "Deployment Notes" - the newer field sheet, with
  the Sep-Oct 2018 phase filled in. Same columns: dipole lengths, azimuths,
  positions, free-form notes; one row per deployment, short names (b1, b10r).
  The two are merged as a union keyed by short name; where both carry a
  non-empty value for a field this script uses, the newer sheet wins and the
  older value is appended to that site's ``notes`` as a "conflict: ..." string.
* ``Burra_Timing.xlsx`` / "Sheet1" - clock status for the June 2018 phases.
* ``BurraTimingPhase2.xlsx`` / "Sheet2" - clock status for Sep-Oct 2018.
* ``lemi423_metadata_summary.csv`` - positions read from the B423 headers, used
  where the field sheet has none and as a cross-check where it has both.

The authoritative site list is the set of zip stems in ``data_root`` (site name
= folder name = zip stem), not the field sheet: a few folders have no row.

Usage:
    python scripts/burra_notes_to_yaml.py surveys/burra/survey.yaml
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

# (workbook, sheet) oldest first - later sheets win where values conflict
DEPLOYMENT_SHEETS = [
    ("Burra_DeploymentNotes.xlsx", "Deployment Notes"),
    ("BurraTimingPhase2.xlsx", "Deployment Notes"),
]
# columns this script actually writes out: only these are merged and
# conflict-checked, so cosmetic differences elsewhere stay out of the notes
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
# a field-sheet position and the B423 header position further apart than this
# means one of the two is for a different site
POSITION_TOLERANCE_KM = 0.2
# A row's UnixTime is the deployment epoch and equals the folder's first B423
# filename for every clean case, so a row further than this from the folder's
# first-file epoch describes a different run. (Do not use the CSV's "Start Time"
# column for this: it runs a constant +8 h ahead of the file epochs.)
MATCH_TOLERANCE_S = 6 * 3600.0


def site_folders(data_root: Path) -> list[str]:
    """Authoritative site list: one zip per site, site name = zip stem."""
    return sorted(p.stem for p in data_root.glob("*.zip") if p.stem not in EXCLUDE_STEMS)


def site_number(name: str) -> int | None:
    """Site number shared by a site's deployments: b18/b18r/Burra18repeat -> 18."""
    m = re.match(r"(?:b|burra)0*(\d+)", str(name).strip().lower())
    return int(m.group(1)) if m else None


def short_to_folder(short: str, folders: set[str]) -> str | None:
    """Field-sheet short name -> folder name: b1 -> Burra01, b10r -> Burra10repeat.

    The repeat suffix is spelled two ways in the raw data ("repeat" and "r"),
    so both are tried and only a spelling that actually exists is returned.
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

    Only split when the decomposition against {0, 90, 180, 270} is unique, so
    this is a parse rather than a guess; the caller still keeps the raw cell
    text in the site's notes.
    """
    splits = [
        [a, token[len(a) :]]
        for a in VALID_AZIMUTHS
        if token.startswith(a) and token[len(a) :] in VALID_AZIMUTHS
    ]
    return splits[0] if len(splits) == 1 else [token]


def split_azimuths(cell) -> tuple[float, float]:
    """'180, 90' -> (180.0, 90.0). Only 0/90/180/270 are expected."""
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
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def clean(value):
    """Spreadsheet cell -> None when blank, else the stripped value."""
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
    """Cell -> float, or None when it is not a number (numpy scalars included)."""
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
    """Plain-ASCII note text: substitute what we know, drop anything left over."""
    for bad, good in ASCII_SUBSTITUTIONS.items():
        text = text.replace(bad, good)
    stripped = text.encode("ascii", "ignore").decode("ascii")
    if stripped != text:
        logger.warning(f"dropped non-ASCII characters from a note: {text!r}")
    return stripped


def same_value(a, b) -> bool:
    """Spreadsheet-cell equality: numbers by value (int 13 == float 13.0 as the
    two sheets store them differently), everything else as text."""
    fa, fb = as_float(a), as_float(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def read_deployment_notes(data_root: Path) -> tuple[dict, dict, list]:
    """Both field sheets -> {short name: merged row}, {short name: [conflicts]},
    and the short names whose row was a blank placeholder.

    Merged as a union keyed by the short site name: a later sheet's non-empty
    value wins, an earlier one fills a gap, and a genuine disagreement is
    recorded so it ends up in the site's notes rather than being silently lost.
    A row whose merged columns are all empty (b44/b56/b71 in the older sheet)
    is dropped - it is a placeholder, not metadata.
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
    Returns {folder: (short, row)}, {folder: [extra notes]} and the short names
    that map to no folder at all.
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
    """Both timing sheets -> {short name: 'Correct' | 'Behind' | 'No data'}.

    Keyed by short name, not folder, so the flag follows its row through the
    deployment-time matching in ``assign_rows``.
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


def read_header_metadata(data_root: Path) -> dict[str, dict]:
    """B423 header summary -> {folder: {latitude, longitude, elevation, start}}.

    ``start`` is the folder's first B423 filename as a unix epoch (the zips are
    never opened); it is what the field sheet's ``UnixTime`` records.
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
        }
    return out


def build_site(folder, row, header, defaults, timing, conflicts, extra_notes, issues) -> dict:
    """One site entry: field sheet first, B423 header metadata as fallback."""
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
            # malformed cell: record what was there rather than silently fixing it
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
    """Replace the `sites:` block in place, keeping the rest of the file (comments
    included) byte-for-byte. Requires `sites:` to be the last top-level key."""
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

    sites = {
        folder: build_site(
            folder,
            matched[folder][1] if folder in matched else None,
            headers.get(folder),
            defaults,
            timing.get(folder),
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


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "surveys/burra/survey.yaml")
