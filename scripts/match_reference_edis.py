# -*- coding: utf-8 -*-
"""
Match reference EDIs to survey sites

Matches a folder of reference EDIs back to the sites of a survey.yaml and
writes reference_edis.yaml beside it. Four rules are tried in order and the
first hit wins:

1. File name: ``<site>.edi`` is in the folder.
2. INFO-block SITE name: merged lemimt EDIs that were renamed (to a
   numbered file name, say) keep "SITE : P-A02_RR-A03" inside.
3. Nearest EDI not yet claimed, within `MAX_KM`.
4. Nearest EDI overall within `MAX_KM`, reusing one already claimed. A repeat
   deployment sits on its original site's position and so shares that
   site's EDI.

Each entry holds the EDI path and, when both positions are known, the
distance in km between the EDI and the field-sheet position.

Usage:
    python scripts/match_reference_edis.py <edi_dir> <survey.yaml>

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import math
import re
import sys
from pathlib import Path

import yaml

MAX_KM = 3.0


def parse_deg(value: str) -> float:
    """Parse an EDI latitude or longitude to decimal degrees.

    Args:
        value (str): Decimal degrees or [+-]DD:MM:SS.S.

    Returns:
        float: Decimal degrees.
    """
    value = value.strip().lstrip("+")
    if ":" in value:
        d, m, s = value.split(":")
        sign = -1.0 if d.strip().startswith("-") else 1.0
        return sign * (abs(float(d)) + float(m) / 60.0 + float(s) / 3600.0)
    return float(value)


def edi_position(path: Path):
    """Read LAT and LONG from the first 4000 characters of an EDI.

    Args:
        path (Path): EDI file.

    Returns:
        tuple[float, float] | None: (latitude, longitude) in decimal degrees,
        or None when either is missing.
    """
    head = path.read_text(errors="ignore")[:4000]
    lat = re.search(r"^\s*LAT\s*=\s*([+\-0-9:.]+)", head, re.M)
    lon = re.search(r"^\s*LONG\s*=\s*([+\-0-9:.]+)", head, re.M)
    if not (lat and lon):
        return None
    return parse_deg(lat.group(1)), parse_deg(lon.group(1))


def edi_site_name(path: Path):
    """Return the original processing name from the INFO block of an EDI.

    Args:
        path (Path): EDI file.

    Returns:
        str | None: The local site of 'SITE : P-<site>_RR...', e.g. A02 for
        'SITE : P-A02_RR-A03', or None when absent.
    """
    head = path.read_text(errors="ignore")[:4000]
    m = re.search(r"SITE\s*:\s*P-([A-Za-z0-9]+)_RR", head)
    return m.group(1) if m else None


def km_between(lat1, lon1, lat2, lon2) -> float:
    """Great-circle (haversine) distance in km between two points in degrees."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def entry_for(edi: Path, pos, site: dict) -> dict:
    """Build the reference_edis.yaml entry of a site matched to an EDI.

    Args:
        edi (Path): Matched EDI.
        pos (tuple[float, float] | None): EDI position, if known.
        site (dict): Site entry of the survey.yaml.

    Returns:
        dict: {"edi": path}, plus "distance_km" when both positions are
        known and a "warning" when the distance exceeds MAX_KM.
    """
    entry = {"edi": str(edi)}
    if pos and site.get("latitude") is not None:
        d = km_between(site["latitude"], site["longitude"], *pos)
        entry["distance_km"] = round(d, 3)
        if d > MAX_KM:
            entry["warning"] = f"EDI position {d:.1f} km from field-sheet position"
    return entry


def nearest(positions: dict, site: dict):
    """Find the EDI closest to a site.

    Args:
        positions (dict): EDI path to (latitude, longitude).
        site (dict): Site entry with "latitude" and "longitude".

    Returns:
        tuple[Path, float]: The closest EDI and its distance in km.
    """
    best = min(
        positions.items(),
        key=lambda kv: km_between(site["latitude"], site["longitude"], *kv[1]),
    )
    return best[0], km_between(site["latitude"], site["longitude"], *best[1])


def main(edi_dir: str, survey_yaml: str) -> None:
    """Match the EDIs of a folder to the survey's sites and write reference_edis.yaml.

    Args:
        edi_dir (str): Folder of reference EDIs.
        survey_yaml (str): survey.yaml whose `sites:` are matched.
    """
    edi_dir, survey_yaml = Path(edi_dir), Path(survey_yaml)
    config = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))

    sites = config.get("sites") or {}
    mapping, by_coords, unmatched = {}, {}, []
    all_coords = {edi: edi_position(edi) for edi in sorted(edi_dir.glob("*.edi"))}
    all_coords = {edi: pos for edi, pos in all_coords.items() if pos}

    # 1. the EDI is named after the site (S01.edi -> S01)
    for name, site in sites.items():
        edi = edi_dir / f"{name}.edi"
        if edi.exists():
            mapping[name] = entry_for(edi, all_coords.get(edi), site)
    claimed = {Path(e["edi"]) for e in mapping.values()}

    # 2. the original processing name survives in the INFO block
    for edi, pos in all_coords.items():
        if edi in claimed:
            continue
        name = edi_site_name(edi)
        if name and name in sites and name not in mapping:
            mapping[name] = entry_for(edi, pos, sites[name])
        else:
            by_coords[edi] = pos

    # 3. fall back to nearest-coordinate match among the EDIs still unclaimed
    for name, site in sites.items():
        if name in mapping or site.get("latitude") is None or not by_coords:
            continue
        best, dist = nearest(by_coords, site)
        if dist <= MAX_KM:
            mapping[name] = {"edi": str(best), "distance_km": round(dist, 3)}

    # 4. last resort: nearest EDI overall, reusing one another site already
    #    claimed; repeat/rr folders reoccupy an earlier site's position
    for name, site in sites.items():
        if name in mapping or site.get("latitude") is None or not all_coords:
            continue
        best, dist = nearest(all_coords, site)
        if dist <= MAX_KM:
            mapping[name] = {"edi": str(best), "distance_km": round(dist, 3)}
        else:
            unmatched.append((name, round(dist, 1)))

    out = survey_yaml.parent / "reference_edis.yaml"
    out.write_text(yaml.safe_dump(mapping, sort_keys=True), encoding="utf-8")
    print(f"matched {len(mapping)}/{len(sites)} sites -> {out}")
    if unmatched:
        print("unmatched (no SITE name, nearest EDI too far):", unmatched)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
