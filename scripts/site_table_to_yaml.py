# -*- coding: utf-8 -*-
"""
Field-sheet spreadsheet to survey.yaml sites

Converts a field-sheet spreadsheet into the `sites:` section of a survey.yaml.
The sheet has the columns SiteName, SampleRate, Latitude, Longitude,
Elevation, ExDipole, ExAzimuth, EyDipole and EyAzimuth. The `sites:` block
of the YAML is rewritten in place and every other key is preserved.

Usage:
    python scripts/site_table_to_yaml.py <field_sheet.xlsx> <survey.yaml>

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import sys
from pathlib import Path

import pandas as pd
import yaml


def main(xlsx_path: str, yaml_path: str) -> None:
    """Write the sites of a field sheet into a survey.yaml.

    Args:
        xlsx_path (str): Field-sheet spreadsheet, one row per site.
        yaml_path (str): survey.yaml to update; created if it does not exist.
    """
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
