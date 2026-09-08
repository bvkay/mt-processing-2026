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

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Survey":
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls(config, path.parent)

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
        return SiteConfig(name=name, **merged)
