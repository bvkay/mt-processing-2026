"""Match renamed reference EDIs back to survey sites by coordinates.

The final merged lemimt EDIs were renamed (e.g. Cube_017.edi), so the only
link back to site names is position. This scans a folder of EDIs, matches each
survey site to the nearest EDI within `MAX_KM`, and writes the mapping to
<survey folder>/reference_edis.yaml.

Usage:
    python scripts/match_reference_edis.py <edi_dir> <survey.yaml>
"""

import math
import re
import sys
from pathlib import Path

import yaml

MAX_KM = 3.0


def parse_deg(value: str) -> float:
    """EDI lat/lon: decimal degrees or [+-]DD:MM:SS.S."""
    value = value.strip().lstrip("+")
    if ":" in value:
        d, m, s = value.split(":")
        sign = -1.0 if d.strip().startswith("-") else 1.0
        return sign * (abs(float(d)) + float(m) / 60.0 + float(s) / 3600.0)
    return float(value)


def edi_position(path: Path):
    head = path.read_text(errors="ignore")[:4000]
    lat = re.search(r"^\s*LAT\s*=\s*([+\-0-9:.]+)", head, re.M)
    lon = re.search(r"^\s*LONG\s*=\s*([+\-0-9:.]+)", head, re.M)
    if not (lat and lon):
        return None
    return parse_deg(lat.group(1)), parse_deg(lon.group(1))


def edi_site_name(path: Path):
    """Original processing name from the INFO block, e.g. 'SITE : P-A02_RR-A03' -> A02."""
    head = path.read_text(errors="ignore")[:4000]
    m = re.search(r"SITE\s*:\s*P-([A-Za-z0-9]+)_RR", head)
    return m.group(1) if m else None


def km_between(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main(edi_dir: str, survey_yaml: str) -> None:
    edi_dir, survey_yaml = Path(edi_dir), Path(survey_yaml)
    config = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))

    sites = config.get("sites") or {}
    mapping, by_coords, unmatched = {}, {}, []

    for edi in sorted(edi_dir.glob("*.edi")):
        name = edi_site_name(edi)
        pos = edi_position(edi)
        if name and name in sites:
            entry = {"edi": str(edi)}
            site = sites[name]
            if pos and site.get("latitude") is not None:
                d = km_between(site["latitude"], site["longitude"], *pos)
                entry["distance_km"] = round(d, 3)
                if d > MAX_KM:
                    entry["warning"] = f"EDI position {d:.1f} km from field-sheet position"
            mapping[name] = entry
        elif pos:
            by_coords[edi] = pos

    # fall back to nearest-coordinate match for EDIs without a usable SITE name
    for name, site in sites.items():
        if name in mapping or site.get("latitude") is None or not by_coords:
            continue
        best = min(by_coords.items(), key=lambda kv: km_between(site["latitude"], site["longitude"], *kv[1]))
        dist = km_between(site["latitude"], site["longitude"], *best[1])
        if dist <= MAX_KM:
            mapping[name] = {"edi": str(best[0]), "distance_km": round(dist, 3)}
        else:
            unmatched.append((name, round(dist, 1)))

    out = survey_yaml.parent / "reference_edis.yaml"
    out.write_text(yaml.safe_dump(mapping, sort_keys=True), encoding="utf-8")
    print(f"matched {len(mapping)}/{len(sites)} sites -> {out}")
    if unmatched:
        print("unmatched (no SITE name, nearest EDI too far):", unmatched)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
