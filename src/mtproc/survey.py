# -*- coding: utf-8 -*-
"""
Survey configuration: one YAML per survey, sites discovered from folders

A survey is a folder of raw site directories plus a small YAML config. The
site name is the folder name. Any directory under ``data_root`` that holds
raw files of an instrument mtproc reads (`INSTRUMENTS`: LEMI-423, LEMI-424,
Earth Data PR6-24) is a site, and its instrument is detected from those
files (`detect_instrument`). The top-level `instrument:` of the YAML is the
survey default, and a site's own `instrument:` overrides both
(`Survey.instrument_of`). Per-site settings (dipole lengths, azimuths,
positions) are optional overrides in the YAML, usually generated once from
the field spreadsheet (see ``scripts/site_table_to_yaml.py``).

`Survey.from_yaml` loads a survey and `Survey.site` returns the merged
`SiteConfig` of one site. A derived site, written by
``scripts/decimate_site.py`` as ``<site>L``, names the recorded site it was
decimated from (`derived_from:`, `Survey.parent_of`) and its own
`sample_rate:` (`Survey.sample_rate_of`). `read_site_table` reads a CSV or XLSX site table,
and `CHANNEL_PRESETS` lists the channel sets a survey may declare.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger

from .instruments import INSTRUMENTS, detect_instrument  # noqa: F401  (mtproc.survey.INSTRUMENTS)

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius
# `instrument:` of an INTERMAGNET observatory entry (scripts/fetch_observatory.py):
# an archive of 1 Hz hx hy hz in nT with no raw folder
OBSERVATORY = "intermagnet"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 positions, in kilometres.

    Uses the haversine formula on a sphere of `EARTH_RADIUS_KM`, accurate to
    about 0.5 % against the ellipsoid; one degree of latitude comes out as
    111.2 km. The GUI site map and the remote distance shown on the Process
    tab use it.

    Args:
        lat1 (float): Latitude of the first position in degrees.
        lon1 (float): Longitude of the first position in degrees.
        lat2 (float): Latitude of the second position in degrees.
        lon2 (float): Longitude of the second position in degrees.

    Returns:
        float: Distance in km.
    """
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# Per-site keys a site table may set, and their types. A table has one row per
# site, a `site` column and any of these columns.
# The GUI Metadata tab edits the same keys and imports the same tables;
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


# Header aliases for the field-sheet survey CSV (SiteName, ExDipole, ExAzimuth,
# ...), so that file reads as a site table. Its two note columns are joined
# into `notes`; TimeZone is read by scripts/new_survey.py.
FIELD_CSV_ALIASES = {
    "sitename": "site",
    "exdipole": "dipole_length_ex",
    "eydipole": "dipole_length_ey",
    "exazimuth": "azimuth_ex",
    "eyazimuth": "azimuth_ey",
    "deployment_notes": "notes",
}


def read_site_table(path: str | Path) -> tuple[dict[str, dict], list[str]]:
    """Read a site table.

    The table is a CSV, or an XLSX read from its first sheet, with a `site`
    column plus any of `SITE_TABLE_COLUMNS`. Headers match after stripping
    and lower-casing, and the field-sheet survey CSV headers are mapped
    through `FIELD_CSV_ALIASES`. Any other column is returned as ignored. An empty
    cell is left out, so a row carries only the values it gives.

    Args:
        path (str or Path): CSV, XLSX or XLS file.

    Returns:
        tuple: ``({site: {column: value}}, [ignored column names])``.

    Raises:
        ValueError: If there is no `site` column, or a numeric cell does not
            parse; the message names the site and column.
    """
    import pandas as pd

    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=object)
    else:
        df = pd.read_csv(path, dtype=object)
    df.columns = [str(c).strip().lstrip("﻿").lower() for c in df.columns]
    df.columns = [FIELD_CSV_ALIASES.get(c, c) for c in df.columns]
    if "pickup_notes" in df.columns:  # the field-sheet CSV's second note column
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

# Channel sets a survey may declare, per instrument, in the names the mt-io
# reader stores: mt_io.lemi.lemi423 reads the B423 columns Bx By Bz Ex Ey as
# hx hy hz ex ey; mt_io.lemi.lemi424 keeps e1 e2 e3 e4 bx by bz; mt_io.uoa.pr624
# reads the EDL files BX BY BZ EX EY as hx hy hz ex ey. The reader determines
# which columns a file carries; the survey declares which of them had a sensor
# attached (a LEMI-423 site normally Ex Ey Bx By with the Bz column an open
# input, some deployments with a Bz coil, a dedicated remote magnetics only) as
# `channels:`, applied at ingest (mtproc.ingest._keep_channels). An
# instrument's first preset is its default. scripts/new_survey.py --channels
# and the GUI Metadata tab use them.
CHANNEL_PRESETS: dict[str, dict[str, list[str]]] = {
    "lemi423": {
        "Ex Ey Bx By": ["ex", "ey", "hx", "hy"],
        "Ex Ey Bx By Bz": ["ex", "ey", "hx", "hy", "hz"],
        "Bx By (magnetics only)": ["hx", "hy"],
        "Bx By Bz": ["hx", "hy", "hz"],
    },
    "lemi424": {
        "E1 E2 E3 E4 Bx By Bz": ["e1", "e2", "e3", "e4", "bx", "by", "bz"],
        "E1 E2 Bx By Bz": ["e1", "e2", "bx", "by", "bz"],
        "Bx By Bz": ["bx", "by", "bz"],
    },
    "edl": {
        "Ex Ey Bx By Bz": ["ex", "ey", "hx", "hy", "hz"],
        "Ex Ey Bx By": ["ex", "ey", "hx", "hy"],
        "Bx By Bz": ["hx", "hy", "hz"],
    },
}
# Label for `channels:` unset (None): ingest keeps every column the reader returns.
ALL_CHANNELS = "all columns"


def default_preset(instrument: str) -> str:
    """Return the label of the default channel set (first preset) of an instrument."""
    return next(iter(CHANNEL_PRESETS[instrument]))


def preset_label(channels: list[str] | None, instrument: str) -> str:
    """Return the preset label of a `channels:` list.

    The match ignores order and case, since ingest keeps a set.
    `channels_from_label` is the inverse.

    Args:
        channels (list of str or None): Channel names; None means all.
        instrument (str): Instrument key of `CHANNEL_PRESETS`.

    Returns:
        str: The matching preset label, `ALL_CHANNELS` for None, or else the
        names joined as ``"a, b, c"``.
    """
    if channels is None:
        return ALL_CHANNELS
    names = [str(c).strip().lower() for c in channels]
    for label, preset in CHANNEL_PRESETS.get(instrument, {}).items():
        if sorted(preset) == sorted(names):
            return label
    return ", ".join(names)


def channels_from_label(label: str, instrument: str) -> list[str] | None:
    """Convert a preset label or a typed list to channel names.

    A preset label gives a copy of its list. The same words map to different
    names on different instruments: "Bx By Bz" is hx hy hz on a LEMI-423 and
    bx by bz on a LEMI-424. A preset's words in another order or with commas
    match that preset too, so "Bx By Ex Ey" gives the "Ex Ey Bx By" preset,
    [ex, ey, hx, hy] on an EDL or LEMI-423. Read as a typed list it would
    name bx and by, which those readers do not produce, and ingest would
    drop both coils.

    Args:
        label (str): Preset label in any case, `ALL_CHANNELS`, or a typed
            list such as ``"hx, hy"`` or ``"hx hy"``.
        instrument (str): Instrument key of `CHANNEL_PRESETS`.

    Returns:
        list of str or None: Lower-case channel names, or None for
        `ALL_CHANNELS`.
    """
    text = str(label).strip()
    if text.lower() == ALL_CHANNELS:
        return None
    words = sorted(w.lower() for w in re.split(r"[,\s]+", text) if w)
    for name, preset in CHANNEL_PRESETS.get(instrument, {}).items():
        if name.lower() == text.lower() or sorted(w.lower() for w in name.split()) == words:
            return list(preset)
    return [c.lower() for c in re.split(r"[,\s]+", text) if c]


@dataclass
class SiteConfig:
    """Settings of one site, merged from the survey defaults and the site entry.

    Attributes:
        name (str): Site name, the raw folder name.
        instrument (str or None): Recorder named by the site's own
            `instrument:` (a key of INSTRUMENTS). None means the instrument
            its files are detected as, else the survey's;
            `Survey.instrument_of` resolves it. scripts/new_survey.py writes
            it for a site whose recorder differs from the survey's.
        dipole_length_ex (float): Ex dipole length in m.
        dipole_length_ey (float): Ey dipole length in m.
        azimuth_ex (float): Ex azimuth in degrees.
        azimuth_ey (float): Ey azimuth in degrees.
        latitude (float or None): Latitude in degrees.
        longitude (float or None): Longitude in degrees.
        elevation (float or None): Elevation in m.
        calibration_fn (str or None): Coil response file, for example a
            LEMI-120 .rsp. Relative paths resolve against the survey folder,
            then data_root. Used by LEMI-423 sites and by EDL sites whose
            `sensor_type` is lemi120.
        sensor_type (str or None): EDL (Earth Data PR6-24) sites: the
            magnetic sensors in mt-io's names
            (mtproc.instruments.EDL_SENSORS). "bartington" is Mag-03
            fluxgates, the long-period setup (UoA: 10 Hz), and is what None
            means. "lemi120" is LEMI-120 induction coils, the broadband setup
            (UoA: 500/1000 Hz), whose response is `calibration_fn`.
            scripts/new_survey.py writes it for an EDL survey.
        electric_gain (float): EDL sites: extra gain of the electric chain
            between the dipoles and the recorded values, beyond what the
            reader models (for the PR6-24 the reader's x10 terminal box). The
            electrical gain is hardwired at the electrical terminal junction
            box; the other gains are set on the PR6-24 during operation, and
            where those configs are lost the value is declared from the
            field notes (e.g. 10.0). Default 1.0.
            Applied to every electric channel of the site (ex, ey) at ingest
            (mtproc.instruments.read_run). A `defaults:` value applies to the
            survey's EDL sites; a non-EDL site with its own key stops ingest
            with an error. Set with scripts/new_survey.py --electric-gain.
        h_scale (float): LEMI-423 sites: extra gain folded into the magnetic
            channel filter chain. The LEMI-423 counts-to-field calibration
            comes out in pT with polarity inverted relative to the lemimt
            convention, hence -1000 (pT to nT plus sign), established against
            merged lemimt EDIs (without it, rho is offset by a constant 1e6
            and both phase modes by exactly 180 deg).
        flip_reversed_dipoles (bool): How to read a 180 or 270 deg dipole
            azimuth on the field sheet. True: the pair was wired
            reversed, so the data are sign-flipped at ingest. False:
            the azimuth records the layout direction, the logger's N/S/E/W
            terminals fix polarity, and nothing is flipped. Set per survey
            from the impedance phase quadrants
            (mtproc.compare.phase_quadrants); a wrong choice puts one mode
            180 deg out.
        channels (list of str or None): Channels kept at ingest; None keeps
            every column the reader returns. Broadband deployments carried
            no hz sensor (the B423 Bz column is an open input, constant
            -2^31), so those surveys set [ex, ey, hx, hy] and aurora
            estimates no tipper from a dead channel. The usual sets are in
            CHANNEL_PRESETS; a site whose set differs from `defaults:` has
            its own.
        filters (list of dict or None): Declared time-domain filters applied
            at ingest, in order (see mtproc.noise), from
            <survey>/filters.yaml.
        timing (str or None): Logger clock status from the field timing
            sheets ("Correct", "Behind", "No data"); None when the site is
            not listed.
        notes (str or None): Free-form field-sheet remarks (noise sources,
            chewed cables, ...).
        remote (str or None): Usual remote-reference partner (dedicated
            remote, adjacent site or a stacked remote's name). It is the
            default of the GUI remote dropdown; scripts take the remote as
            an explicit argument.
        serial (str or None): Logger serial number as mt-io reads it from the
            site's first B423 header. This and `firmware`, `start` and `end`
            are written by scripts/new_survey.py and shown in the GUI.
        firmware (str or None): Logger firmware from the same header.
        start (str or None): First instant of the recorded span, UTC ISO
            ("2021-06-29T06:55:44Z").
        end (str or None): Last instant of the recorded span, UTC ISO.
        derived_from (str or None): The recorded site whose processing
            archive scripts/decimate_site.py decimated into this site's
            archive (`D02L` from `D02`). A derived site has no raw folder;
            `Survey.instrument_of` gives its parent's recorder.
        sample_rate (float or None): The site's own sample rate in Hz, set
            on a derived site (1.0); None means the survey's `sample_rate`
            (`Survey.sample_rate_of`).
    """

    name: str
    instrument: str | None = None
    dipole_length_ex: float = 0.0
    dipole_length_ey: float = 0.0
    azimuth_ex: float = 0.0
    azimuth_ey: float = 90.0
    latitude: float | None = None
    longitude: float | None = None
    elevation: float | None = None
    calibration_fn: str | None = None
    sensor_type: str | None = None
    electric_gain: float = 1.0
    h_scale: float = 1.0
    flip_reversed_dipoles: bool = True
    channels: list[str] | None = None
    filters: list[dict] | None = None
    timing: str | None = None
    notes: str | None = None
    remote: str | None = None
    serial: str | None = None
    firmware: str | None = None
    start: str | None = None
    end: str | None = None
    derived_from: str | None = None
    sample_rate: float | None = None


class Survey:
    """One survey: its YAML config, its raw site folders and its per-site files.

    Args:
        config (dict): Parsed survey.yaml. ``name`` and ``data_root`` are
            required; ``instrument`` defaults to lemi423 and
            ``sample_rate`` to 1000 Hz.
        config_dir (Path): Folder holding survey.yaml, filters.yaml and
            masks.yaml.

    Raises:
        ValueError: If the survey instrument is unknown.
    """

    RAW_PATTERNS = {name: spec["pattern"] for name, spec in INSTRUMENTS.items()}

    def __init__(self, config: dict, config_dir: Path):
        self.config = config
        self.config_dir = Path(config_dir)
        self.name: str = config["name"]
        self.instrument: str = config.get("instrument", "lemi423")
        if self.instrument not in self.RAW_PATTERNS:
            raise ValueError(f"unknown instrument {self.instrument!r}")
        self.sample_rate = float(config.get("sample_rate", 1000))
        self.data_root = Path(config["data_root"])
        # script that wrote the `sites:` block (top-level `generated_by:`), None
        # for a hand-written file; re-running that script overwrites hand edits
        self.generated_by: str | None = config.get("generated_by") or None
        self._defaults: dict = config.get("defaults") or {}
        self._sites: dict = config.get("sites") or {}
        # site -> the instrument its folder was detected as, filled by site_dirs()
        self._detected: dict[str, str] = {}
        # per-site filters live in filters.yaml, so regenerating the sites
        # block from the field sheet leaves them in place
        self._filters: dict = {}
        filters_yaml = self.config_dir / "filters.yaml"
        if filters_yaml.exists():
            with open(filters_yaml, encoding="utf-8") as f:
                self._filters = yaml.safe_load(f) or {}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Survey":
        """Load a survey from its survey.yaml path."""
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return cls(config, path.parent)

    @property
    def timezone(self) -> str:
        """IANA name of the survey area's local time (top-level `timezone:`), default UTC.

        Used for display: every timestamp in this package, in the YAML and in
        the archives is UTC. Field sheets are kept in local time, so the GUI
        labels the processing-window fields with the local equivalent, such as
        "18:25 ACST".
        """
        return str(self.config.get("timezone") or "UTC")

    @property
    def defaults(self) -> dict:
        """Copy of the `defaults:` block, applied to every key a site does not set."""
        return dict(self._defaults)

    @property
    def processing(self) -> dict:
        """Band/period targets for aurora (kwargs for mtproc.bands schemes)."""
        return self.config.get("processing") or {}

    @property
    def workspace(self) -> Path:
        """Output folder for mth5/TF/figure products (gitignored)."""
        ws = self.config.get("workspace")
        return Path(ws) if ws else self.config_dir / "work"

    def site_names(self) -> list[str]:
        """Sites declared in the `sites:` block of survey.yaml; raw folders may add more."""
        return list(self._sites)

    def site_dirs(self) -> dict[str, Path]:
        """Map site names to raw-data folders discovered under data_root.

        A folder is a site when it holds data files of any instrument
        (`detect_instrument`, preferring the survey's instrument). A LEMI-423
        folder is recognised by a B423 file named by its epoch; an
        AppleDouble ``._<epoch>.B423`` twin does not count. The detected
        instrument is recorded for `instrument_of`. A site folder holds that
        site's raw recordings; processing products are written to the
        workspace. A derived site (`parent_of`) and an observatory
        (`OBSERVATORY`) have an archive and no folder, and are not listed; a
        derived site's parent's folder is ``site_dirs()[parent_of(site)]``.

        Returns:
            dict: Site name to folder Path, sorted by name.
        """
        out = {}
        for d in sorted(self.data_root.iterdir()):
            if not d.is_dir():
                continue
            found = detect_instrument(d, prefer=self.instrument)
            if found:
                out[d.name] = d
                self._detected[d.name] = found
        return out

    def instrument_of(self, site: str) -> str:
        """Return the recorder of a site.

        The site's own `instrument:` wins, then, for a derived site, its
        parent's recorder, then the instrument detected in
        ``data_root/<site>``, then the survey's. Detection runs on the first
        call unless `site_dirs()` has already done it. A missing folder, for
        example on a drive that is not connected, falls back to the survey's
        instrument.

        Args:
            site (str): Site name.

        Returns:
            str: Instrument key of INSTRUMENTS, or `OBSERVATORY`
            ("intermagnet") for an observatory entry written by
            scripts/fetch_observatory.py (1 Hz hx hy hz, no raw folder).

        Raises:
            ValueError: If the site declares an unknown instrument, or is
                derived from itself.
        """
        declared = (self._sites.get(site) or {}).get("instrument")
        if declared:
            if declared == OBSERVATORY:
                return declared
            if declared not in INSTRUMENTS:
                raise ValueError(f"{site}: unknown instrument {declared!r} (know: {', '.join(INSTRUMENTS)})")
            return declared
        parent = self.parent_of(site)
        if parent:
            if parent == site:
                raise ValueError(f"{site}: derived_from names the site itself")
            return self.instrument_of(parent)
        if site not in self._detected:
            folder = self.data_root / site
            found = detect_instrument(folder, prefer=self.instrument) if folder.is_dir() else None
            self._detected[site] = found or self.instrument
        return self._detected[site]

    def parent_of(self, site: str) -> str | None:
        """Return the site a derived site was decimated from.

        Args:
            site (str): Site name.

        Returns:
            str or None: The site entry's `derived_from:`; None for a
            recorded site and for a name with no entry.
        """
        parent = (self._sites.get(site) or {}).get("derived_from")
        return str(parent) if parent else None

    def sample_rate_of(self, site: str) -> float:
        """Return the sample rate of a site's archive in Hz.

        The site entry's own `sample_rate:` wins (a derived site's 1.0); an
        INTERMAGNET observatory entry (`instrument: intermagnet`, written by
        scripts/fetch_observatory.py) is at `mtproc.observatory.FS`; every
        other site, and a name with no entry such as a stacked remote, is at
        the survey's `sample_rate`.

        Args:
            site (str): Site name.

        Returns:
            float: Sample rate in Hz.
        """
        entry = self._sites.get(site) or {}
        if entry.get("sample_rate") is not None:
            return float(entry["sample_rate"])
        if entry.get("instrument") == OBSERVATORY:
            from .observatory import FS

            return float(FS)
        return self.sample_rate

    def site(self, name: str) -> SiteConfig:
        """Return the settings of one site.

        The `defaults:` block is merged with the site's entry, the entry
        winning, and the site's filters.yaml entry is added unless the merged
        settings already carry ``filters``. A site without an entry gets the
        defaults and a logged warning.

        Args:
            name (str): Site name.

        Returns:
            SiteConfig: The merged settings.
        """
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
