"""Survey configuration: one YAML per survey, sites discovered from folders.

A survey is a folder of raw site directories plus a small YAML config.
Site name = folder name; any directory under ``data_root`` that contains raw
files for the survey's instrument is a site. Per-site settings (dipole lengths,
azimuths, positions) are optional overrides in the YAML — typically generated
once from the field spreadsheet (see ``scripts/site_table_to_yaml.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 positions, in kilometres.

    Plain haversine on a sphere of `EARTH_RADIUS_KM`: good to ~0.5 % against
    the ellipsoid, which is far tighter than a remote-pairing gut check needs
    (one degree of latitude comes out 111.2 km). Pure function, no I/O -- the
    GUI's site map and the Process tab's "remote E08 at 148.6 km" line call
    it, and so can any script.
    """
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# The per-site keys a site table may set, and their types: one row per site,
# a `site` column, any of these columns (docs/site_table_template.csv). The
# GUI's Metadata tab edits the same keys and imports the same tables;
# scripts/new_survey.py --site-table merges one before writing.
SITE_TABLE_COLUMNS = {
    "latitude": float,
    "longitude": float,
    "elevation": float,
    "dipole_length_ex": float,
    "dipole_length_ey": float,
    "azimuth_ex": float,
    "azimuth_ey": float,
    "remote": str,
    "timing": str,
    "notes": str,
}


# the MATLAB field app's survey CSV (SiteName, ExDipole, ExAzimuth, ...): the
# students already have one per survey, so its headers map onto ours. The
# two note columns are joined into `notes`; TimeZone is read by new_survey.py.
MATLAB_CSV_ALIASES = {
    "sitename": "site",
    "exdipole": "dipole_length_ex",
    "eydipole": "dipole_length_ey",
    "exazimuth": "azimuth_ex",
    "eyazimuth": "azimuth_ey",
    "deployment_notes": "notes",
}


def read_site_table(path: str | Path) -> tuple[dict[str, dict], list[str]]:
    """A site table -> ({site: {column: value}}, [ignored column names]).

    CSV, or XLSX (its first sheet), with a `site` column plus any of
    `SITE_TABLE_COLUMNS`; headers match after stripping and lower-casing, and
    any other column is returned as ignored rather than guessed at. An empty
    cell is left out, so a row carries only the values it gives. Raises
    ValueError without a `site` column, or naming the site and column of a
    number that does not parse.
    """
    import pandas as pd

    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=object)
    else:
        df = pd.read_csv(path, dtype=object)
    df.columns = [str(c).strip().lstrip("﻿").lower() for c in df.columns]
    df.columns = [MATLAB_CSV_ALIASES.get(c, c) for c in df.columns]
    if "pickup_notes" in df.columns:  # the MATLAB CSV's second note column
        pick = df["pickup_notes"].fillna("").astype(str).str.strip()
        base = df["notes"].fillna("").astype(str).str.strip() if "notes" in df.columns else ""
        df["notes"] = [" | ".join(t for t in (a, b) if t) for a, b in zip(base, pick)] if "notes" in df.columns else pick
    if "site" not in df.columns:
        raise ValueError(f"{path.name}: no 'site' column (columns: {list(df.columns)})")
    ignored = [c for c in df.columns if c != "site" and c not in SITE_TABLE_COLUMNS]
    rows: dict[str, dict] = {}
    for record in df.to_dict("records"):
        site = record["site"]
        if site is None or pd.isna(site) or not str(site).strip():
            continue
        site = str(site).strip()
        values = {}
        for column, kind in SITE_TABLE_COLUMNS.items():
            value = record.get(column)
            if value is None or pd.isna(value) or not str(value).strip():
                continue
            try:
                values[column] = str(value).strip() if kind is str else float(value)
            except ValueError:
                raise ValueError(f"{path.name}: {site} {column} {value!r} is not a number") from None
        rows[site] = values
    return rows, ignored

@dataclass
class SiteConfig:
    name: str
    dipole_length_ex: float = 0.0
    dipole_length_ey: float = 0.0
    azimuth_ex: float = 0.0
    azimuth_ey: float = 90.0
    latitude: float | None = None
    longitude: float | None = None
    elevation: float | None = None
    # coil response file (e.g. LEMI-120 .rsp); relative paths resolve against data_root
    calibration_fn: str | None = None
    # extra gain folded into the magnetic channel filter chain. For LEMI-423
    # the counts->field calibration comes out in pT with inverted polarity
    # relative to the lemimt convention, hence -1000 (pT -> nT + sign).
    # Established empirically against merged lemimt EDIs on Curnamona Cube
    # (constant 1e6 rho offset, exact 180 deg on both phase modes).
    h_scale: float = 1.0
    # How to read a 180/270 deg dipole azimuth on the field sheet. True
    # (Curnamona): the pair was wired reversed, so the data are sign-flipped at
    # ingest. False (Burra): the azimuth records layout direction only, the
    # logger's N/S/E/W terminals fix polarity, and nothing is flipped. Decide
    # per survey from the impedance phase quadrants (bbmt.compare.phase_quadrants);
    # a wrong choice puts one mode 180 deg out.
    flip_reversed_dipoles: bool = True
    # channels to keep at ingest; None keeps everything the reader returns.
    # Broadband deployments carried no hz sensor (the B423 Bz column is an
    # open input, constant -2^31), so those surveys set [ex, ey, hx, hy] and
    # aurora never estimates a tipper from a dead channel.
    channels: list[str] | None = None
    # declared time-domain filters applied at ingest, in order (see
    # bbmt.noise); from <survey>/filters.yaml, never auto-detected.
    filters: list[dict] | None = None
    # logger clock status from the field timing sheets ("Correct"/"Behind"/
    # "No data"); None when the site is not listed on one.
    timing: str | None = None
    # free-form field-sheet remarks (noise sources, chewed cables, ...).
    notes: str | None = None
    # the usual remote-reference partner (dedicated remote, adjacent site or a
    # stacked remote's name). Only a default for the GUI's remote dropdown and
    # a note for the reader; every script still takes the remote explicitly.
    remote: str | None = None
    # recorder facts from the site's first B423 header and its file names,
    # written by scripts/new_survey.py and read-only everywhere else (the GUI
    # shows them, nothing computes with them): the logger's serial number and
    # firmware as mt-io reads them, and the recorded span's first and last
    # instant as UTC ISO strings ("2021-06-29T06:55:44Z").
    serial: str | None = None
    firmware: str | None = None
    start: str | None = None
    end: str | None = None


class Survey:
    RAW_PATTERNS = {"lemi423": "*.B423"}

    def __init__(self, config: dict, config_dir: Path):
        self.config = config
        self.config_dir = Path(config_dir)
        self.name: str = config["name"]
        self.instrument: str = config.get("instrument", "lemi423")
        if self.instrument not in self.RAW_PATTERNS:
            raise ValueError(f"unknown instrument {self.instrument!r}")
        self.sample_rate = float(config.get("sample_rate", 1000))
        self.data_root = Path(config["data_root"])
        # the script that wrote the `sites:` block (top-level `generated_by:`),
        # None for a hand-written file: re-running it overwrites hand edits
        self.generated_by: str | None = config.get("generated_by") or None
        self._defaults: dict = config.get("defaults") or {}
        self._sites: dict = config.get("sites") or {}
        # per-site noise decisions live in their own file so regenerating the
        # sites block from the field sheet never wipes them
        self._filters: dict = {}
        filters_yaml = self.config_dir / "filters.yaml"
        if filters_yaml.exists():
            with open(filters_yaml, encoding="utf-8") as f:
                self._filters = yaml.safe_load(f) or {}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Survey":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls(config, path.parent)

    @property
    def timezone(self) -> str:
        """IANA name of the survey area's local time (top-level `timezone:`), default UTC.

        Only ever a *display* convenience: every timestamp in this package,
        in the YAML and in the archives is UTC. Students read field sheets in
        local time, so the GUI labels the processing-window fields with the
        local equivalent (the MATLAB app's "(ACST)" suffix).
        """
        return str(self.config.get("timezone") or "UTC")

    @property
    def processing(self) -> dict:
        """Band/period targets for aurora (kwargs for bbmt.bands schemes)."""
        return self.config.get("processing") or {}

    @property
    def workspace(self) -> Path:
        """Output folder for mth5/TF/figure products (gitignored)."""
        ws = self.config.get("workspace")
        return Path(ws) if ws else self.config_dir / "work"

    def site_names(self) -> list[str]:
        """Sites declared in survey.yaml's `sites:` block (raw folders may add more)."""
        return list(self._sites)

    def site_dirs(self) -> dict[str, Path]:
        """Map site name -> raw-data folder, discovered from data_root."""
        pattern = self.RAW_PATTERNS[self.instrument]
        out = {}
        for d in sorted(self.data_root.iterdir()):
            # a record file is named by its epoch; a folder holding only
            # AppleDouble twins (`._<epoch>.B423`) is not a site
            if d.is_dir() and any(f.stem.isdigit() for f in d.rglob(pattern)):
                out[d.name] = d
        return out

    def site(self, name: str) -> SiteConfig:
        overrides = self._sites.get(name)
        if overrides is None:
            logger.warning(
                f"site {name!r} has no entry in survey.yaml — using survey "
                f"defaults (check dipole lengths/azimuths!)"
            )
            overrides = {}
        merged = {**self._defaults, **overrides}
        if name in self._filters and "filters" not in merged:
            merged["filters"] = self._filters[name]
        return SiteConfig(name=name, **merged)
