"""Convert a field-sheet spreadsheet into a survey.yaml sites section.

Usage:
    python scripts/site_table_to_yaml.py <field_sheet.xlsx> <survey.yaml>

Expects columns: SiteName, SampleRate, Latitude, Longitude, Elevation,
ExDipole, ExAzimuth, EyDipole, EyAzimuth (as in a_Curnamona_Cube_LMEI.xlsx).
Rewrites the `sites:` block of the YAML in place, preserving everything else.
"""

import sys
from pathlib import Path

import pandas as pd
import yaml


def main(xlsx_path: str, yaml_path: str) -> None:
    df = pd.read_excel(xlsx_path)
    df.columns = [str(c).strip() for c in df.columns]

    sites = {}
    for row in df.itertuples():
        name = str(row.SiteName).strip()
        sites[name] = {
            "dipole_length_ex": float(row.ExDipole),
            "dipole_length_ey": float(row.EyDipole),
            "azimuth_ex": float(row.ExAzimuth),
            "azimuth_ey": float(row.EyAzimuth),
            "latitude": round(float(row.Latitude), 6),
            "longitude": round(float(row.Longitude), 6),
            "elevation": float(row.Elevation),
        }

    yaml_path = Path(yaml_path)
    config = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) if yaml_path.exists() else {}
    config["sites"] = sites
    yaml_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"wrote {len(sites)} sites to {yaml_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
