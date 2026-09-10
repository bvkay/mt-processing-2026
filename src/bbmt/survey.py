"""Survey configuration: one YAML per survey, sites discovered from folders.

A survey is a folder of raw site directories plus a small YAML config.
Site name = folder name; any directory under ``data_root`` that contains raw
files for the survey's instrument is a site. Per-site settings (dipole lengths,
azimuths, positions) are optional overrides in the YAML — typically generated
once from the field spreadsheet (see ``scripts/site_table_to_yaml.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger


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
    def processing(self) -> dict:
        """Band/period targets for aurora (kwargs for bbmt.bands schemes)."""
        return self.config.get("processing") or {}

    @property
    def workspace(self) -> Path:
        """Output folder for mth5/TF/figure products (gitignored)."""
        ws = self.config.get("workspace")
        return Path(ws) if ws else self.config_dir / "work"

    def site_dirs(self) -> dict[str, Path]:
        """Map site name -> raw-data folder, discovered from data_root."""
        pattern = self.RAW_PATTERNS[self.instrument]
        out = {}
        for d in sorted(self.data_root.iterdir()):
            if d.is_dir() and next(d.rglob(pattern), None) is not None:
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
