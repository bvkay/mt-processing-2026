"""Match reference EDIs back to survey sites, and write reference_edis.yaml.

Four rules, tried in order, first hit wins:

1. file name — ``<site>.edi`` sits in the folder (Burra_2017-18);
2. INFO-block SITE name — the merged lemimt EDIs were renamed
   (e.g. Cube_017.edi) but kept "SITE : P-A02_RR-A03" inside;
3. nearest EDI not yet claimed, within `MAX_KM`;
4. nearest EDI overall within `MAX_KM`, reusing one already claimed — a repeat
   deployment (Burra10repeat) sits on its original site's position and so
   shares that site's EDI.

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


def entry_for(edi: Path, pos, site: dict) -> dict:
    entry = {"edi": str(edi)}
    if pos and site.get("latitude") is not None:
        d = km_between(site["latitude"], site["longitude"], *pos)
        entry["distance_km"] = round(d, 3)
        if d > MAX_KM:
            entry["warning"] = f"EDI position {d:.1f} km from field-sheet position"
    return entry


def nearest(positions: dict, site: dict):
    """(path, distance_km) of the closest EDI in `positions` to `site`."""
    best = min(
        positions.items(),
        key=lambda kv: km_between(site["latitude"], site["longitude"], *kv[1]),
    )
    return best[0], km_between(site["latitude"], site["longitude"], *best[1])


def main(edi_dir: str, survey_yaml: str) -> None:
    edi_dir, survey_yaml = Path(edi_dir), Path(survey_yaml)
    config = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))

    sites = config.get("sites") or {}
    mapping, by_coords, unmatched = {}, {}, []
    all_coords = {edi: edi_position(edi) for edi in sorted(edi_dir.glob("*.edi"))}
    all_coords = {edi: pos for edi, pos in all_coords.items() if pos}

    # 1. the EDI is named after the site (Burra_2017-18: Burra57.edi -> Burra57)
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
    #    claimed — repeat/rr folders reoccupy an earlier site's position
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
