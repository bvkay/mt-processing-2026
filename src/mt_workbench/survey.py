# -*- coding: utf-8 -*-
"""
Survey configuration: one YAML per survey, sites discovered from folders

A survey is a folder of raw site directories plus a small YAML config. The
site name is the folder name. Any directory under ``data_root`` that holds
raw files of an instrument mt-workbench reads (`INSTRUMENTS`: LEMI-423, LEMI-424,
Earth Data PR6-24, Phoenix MTU-5C/8A, Orange Box, Phoenix MTU-5A) is a site, and its instrument is detected from those
files (`detect_instrument`). The top-level `instrument:` of the YAML is the
survey default, and a site's own `instrument:` overrides both
(`Survey.instrument_of`). Per-site settings (dipole lengths, azimuths,
positions, declination) are optional overrides in the YAML, usually taken from
the field spreadsheet (``scripts/new_survey.py --site-table``, or Import site table in
the GUI's Metadata tab, both through `merge_table_row`).

`Survey.from_yaml` loads a survey and `Survey.site` returns the merged
`SiteConfig` of one site. A derived site, written by
``scripts/decimate_site.py`` as ``<site>L``, names the recorded site it was
decimated from (`derived_from:`, `Survey.parent_of`) and its own
`sample_rate:` (`Survey.sample_rate_of`); so does the diagonal of a
shared-centre site, ``<site>D`` (``scripts/diagonal_site.py``), whose
`channels:` keep one electric line, ex along its `azimuth_ex:`, beside the
magnetics. A Phoenix site's 24 kHz bursts
are ingested as a site of their own, ``<site>H``, whose entry names the
recorded site (`bursts_of:`, `Survey.bursts_parent`) and carries
`sample_rate: 24000`; every other setting is the recorded site's but
`clock_offset_s`, which is 0.0 unless its own entry declares one. A site
that recorded electrics only may name a neighbour whose hx and hy its
archive takes (`h_from:`, checked by `Survey.site`). A fluxgate site may
declare the azimuth its horizontal pair is turned by onto magnetic north at
ingest (`rot_h:`), and a site whose electric lines were connected to each
other's inputs the exchange of ex and ey (`swap_e:`). A site may limit its
record to a time window (`record_window:`), an EDL site declare an extra gain
on one electric line (`electric_gain_ex:`, `electric_gain_ey:`) or that its
magnetometer and electrode cables sat in each other's banks
(`edl_banks_swapped:`). The instruments a site
used are declared by their AuScope instrument registry DOIs (`logger_pid:`,
`sensor_pid_hx:` ..., `platform_pid:` also at the top level;
`Survey.instrument_pids`). `read_site_table` reads a CSV or XLSX site table,
and `CHANNEL_PRESETS` lists the channel sets a survey may declare.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml
from loguru import logger

from .instruments import INSTRUMENTS, LEMI424_RENAME, detect_instrument  # noqa: F401  (mt_workbench.survey.INSTRUMENTS)

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
# the values of survey.yaml's layout_north (`SiteConfig.layout_north`), as in mt_workbench.products.LAYOUT_FRAMES
LAYOUT_NORTH = ("magnetic", "geographic")
# the keys a burst site's own entry may hold (`SiteConfig.bursts_of`); every other setting is its
# recorded site's, but `clock_offset_s`, which is the burst site's own (`Survey._burst_site`)
BURST_SITE_KEYS = ("bursts_of", "sample_rate", "remote", "notes", "clock_offset_s")
# the rate of a Phoenix receiver's burst files (.td_24k), the only rate a burst site may declare
BURST_RATE = 24000.0
# the largest |clock_offset_s| a site may declare, in seconds: a logger whose GPS
# stamps are a whole second late is a firmware fault the key corrects, while an
# offset of minutes is a wrong clock or time zone, for the field sheets to settle
MAX_CLOCK_OFFSET_S = 60.0
# the largest |clock_drift_s| an Orange Box site may declare, in seconds: the field reading of the
# logger's real-time clock against a handheld GPS after days (Kalgoorlie 2006: -10 to +2 s); minutes
# would be a wrong clock or time zone, which `clock_timezone` declares
MAX_CLOCK_DRIFT_S = 600.0
# the channels `SiteConfig.flip_h` may name, in the order the run comment lists them
FLIP_H_CHANNELS = ("hx", "hy", "hz")
# the instrument registry keys (AuScope PIDINST, https://pidinst.data.auscope.org.au/) and the role each
# names in `Survey.instrument_pids`, in the order the products list them; `logger_hx_hy` is added there
# for a site with `h_from` (the neighbour's logger, which recorded its hx and hy)
PID_ROLES = {"logger_pid": "logger", "sensor_pid_hx": "sensor_hx", "sensor_pid_hy": "sensor_hy",
             "sensor_pid_hz": "sensor_hz", "electrode_pid": "electrode", "platform_pid": "platform"}
PID_KEYS = tuple(PID_ROLES)
# a pid value: a bare DOI (10.<registrant, 4 to 9 digits>/<suffix>), or PID_NONE for an instrument the
# registry does not hold
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
PID_NONE = "none"
# start of the run and station comment piece ingest writes for a site with registry keys
# (`Survey.registry_note`): one "key: value" piece, no dot in the key, no semicolon, as the EMTF XML
# writer takes each "key: value" piece of a run comment as an attribute (docs/upstream_issues.md 48)
REGISTRY_PREFIX = "instrument_registry: "

SITE_TABLE_COLUMNS = {
    "latitude": float,
    "longitude": float,
    "elevation": float,
    "declination": float,
    "declination_model": str,
    "declination_epoch": float,
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


# How far a site-table position or elevation may lie from the site's own before the two are said to
# disagree: 0.0005 deg is about 50 m, and 20 m is above the spread of a handheld GPS elevation.
POSITION_TOLERANCE = {"latitude": 0.0005, "longitude": 0.0005, "elevation": 20.0}


def merge_table_row(entry: dict, row: dict) -> tuple[dict, list[str]]:
    """Work out the values one site-table row sets on a site.

    The row's latitude, longitude and elevation fill the site's only where
    the site has none: a table is typed by hand, and a value the site
    already holds (the recorder's GPS fix, or one set before) is kept.
    Where both exist and differ by more than `POSITION_TOLERANCE`, the key
    is listed as a disagreement. Every other column is taken from the row.
    scripts/new_survey.py and the GUI's Import site table both use it, so
    one sheet gives one file either way.

    Args:
        entry (dict): The site's values now, {key: value}; a key that is
            missing or None is a value the site does not have.
        row (dict): The site's row, as `read_site_table` returns it.

    Returns:
        tuple[dict, list[str]]: The values to set, and the position keys
        whose table value disagrees with the site's.
    """
    values, disagreements = {}, []
    for key, value in row.items():
        held = entry.get(key)
        if key in POSITION_TOLERANCE and held is not None:
            if abs(float(value) - float(held)) > POSITION_TOLERANCE[key]:
                disagreements.append(key)
            continue
        values[key] = value
    return values, disagreements


# A survey's name is its folder under surveys/ and its id in the archives. mth5's channel and run
# summaries keep 30 characters of the id (docs/upstream_issues.md 550) in an ASCII field, and mt_metadata
# takes letters, digits, "_", "-" and the space in a survey id; the space is left out here, as in a
# folder name.
SURVEY_NAME_MAX = 30
SURVEY_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def check_survey_name(name: str) -> None:
    """Refuse a name that a new survey cannot take.

    Run when a survey is made (scripts/new_survey.py at its first run, and
    the New survey form), never when one is opened: a survey made before
    this check keeps its name.

    Args:
        name (str): The survey name.

    Raises:
        ValueError: If the name is empty, longer than `SURVEY_NAME_MAX`
            characters, or holds a character other than a letter, a digit,
            "_" or "-"; the message says what to choose.
    """
    if not name or not name.strip():
        raise ValueError("survey name is empty: give the survey a name")
    if len(name) > SURVEY_NAME_MAX:
        raise ValueError(f"survey name has {len(name)} characters: {SURVEY_NAME_MAX} at most; choose a shorter "
                         f"name (mth5 keeps {SURVEY_NAME_MAX} in its summaries, docs/upstream_issues.md 550)")
    if not SURVEY_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"survey name {name!r} holds characters other than letters, digits, _ and -: choose "
                         f"another name (mt_metadata refuses them in a survey id, and mth5's summary field "
                         f"holds ASCII only)")


# A site's name is its folder's and its station id in the archives; 28 leaves room for the L, D and SL
# endings of the sites derived from it.
SITE_NAME_MAX = 28


def check_site_name(name: str) -> None:
    """Refuse a site name that an archive cannot take as a station id.

    A site is named by its data folder, so the way out is to rename the
    folder.

    Args:
        name (str): The site name.

    Raises:
        ValueError: If the name holds a character other than a letter, a
            digit, "_" or "-", or is longer than `SITE_NAME_MAX` characters;
            the message says what to do.
    """
    if not SURVEY_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"site name {name!r} holds characters other than letters, digits, _ and -: rename its "
                         f"folder (mt_metadata refuses it as a station id)")
    if len(name) > SITE_NAME_MAX:
        raise ValueError(f"site name {name!r} has {len(name)} characters: {SITE_NAME_MAX} at most; rename its "
                         f"folder (a site derived from it adds up to two letters)")


# Channel sets a survey may declare, per instrument, in the names ingest
# stores: mt_io.lemi.lemi423 reads the B423 columns Bx By Bz Ex Ey as
# hx hy hz ex ey; mt_io.lemi.lemi424 reads Bx By Bz E1 E2 E3 E4 as bx by bz e1
# e2 e3 e4, stored as hx hy hz ex ey e3 e4 (mt_workbench.instruments.lemi424_stored,
# the labels kept as the recorder prints them); mt_io.uoa.pr624
# reads the EDL files BX BY BZ EX EY as hx hy hz ex ey; a Phoenix receiver's
# E1 E2 H1 H2 H3 are stored as ex ey hx hy hz (mt_workbench.phoenix). The reader determines
# which columns a file carries; the survey declares which of them had a sensor
# attached (a LEMI-423 site normally Ex Ey Bx By with the Bz column an open
# input, some deployments with a Bz coil, a dedicated remote magnetics only) as
# `channels:`, applied at ingest (mt_workbench.ingest._keep_channels). An
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
        "E1 E2 E3 E4 Bx By Bz": ["ex", "ey", "e3", "e4", "hx", "hy", "hz"],
        "E1 E2 Bx By Bz": ["ex", "ey", "hx", "hy", "hz"],
        "Bx By Bz": ["hx", "hy", "hz"],
    },
    "edl": {
        "Ex Ey Bx By Bz": ["ex", "ey", "hx", "hy", "hz"],
        "Ex Ey Bx By": ["ex", "ey", "hx", "hy"],
        "Bx By Bz": ["hx", "hy", "hz"],
    },
    # mt_workbench.phoenix renames the receiver's E1 E2 H1 H2 H3 to ex ey hx hy hz
    "phoenix": {
        "E and H": ["ex", "ey", "hx", "hy"],
        "E and H, Hz": ["ex", "ey", "hx", "hy", "hz"],
        "H only": ["hx", "hy"],
    },
    # mt-io's Orange Box reader names its channels hx hy hz ex ey (three-component fluxgate)
    "orangebox": {
        "Ex Ey Bx By Bz": ["ex", "ey", "hx", "hy", "hz"],
        "Ex Ey Bx By": ["ex", "ey", "hx", "hy"],
        "Bx By Bz": ["hx", "hy", "hz"],
    },
    # mt_workbench.mtu5a stores the table's channels CHEX CHEY CHHX CHHY CHHZ as ex ey hx hy hz
    "mtu5a": {
        "Ex Ey Hx Hy Hz": ["ex", "ey", "hx", "hy", "hz"],
        "Ex Ey Hx Hy": ["ex", "ey", "hx", "hy"],
        "Hx Hy Hz": ["hx", "hy", "hz"],
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

    A preset label gives a copy of its list. A label carries the recorder's
    own words, so "E1 E2 Bx By Bz" is ex ey hx hy hz on a LEMI-424, whose
    reader names those columns e1 e2 bx by bz (stored under the workbench's
    names). A preset's words in another order or with commas
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
        declination (float or None): Magnetic declination at the site in
            degrees east of geographic north (east positive), stored with
            every product and never applied: the products stay in the
            sensor (geomagnetic) frame and a modeller rotates once.
            None means unset, which is not the same as 0.0.
            scripts/declination.py fills it from the IGRF at the site's
            position and the midpoint of its record. Ingest copies it into
            the archive's station metadata (``location.declination``), and
            process_rr.py sets it on each TF before writing, so an archive
            built before the key existed needs no rebuild.
        declination_model (str or None): The field model of `declination`,
            e.g. "IGRF-14".
        declination_epoch (float or None): The decimal year `declination`
            is for, e.g. 2023.53.
        layout_north (str): The north the sensors were laid out to,
            "magnetic" (the default) or "geographic"; usually a `defaults:`
            key, overridable per site. It sets the station's
            ``orientation.reference_frame`` (geomagnetic or geographic) at
            ingest for every reader and on each TF at write time
            (`mt_workbench.products.apply_site_frame`), and with it the
            EDI's COORDINATE_SYSTEM. Under "magnetic" with a declination
            the EDI's ZROT and TROT and the XML's
            angle_to_geographic_north are the declination; under
            "geographic" the declination is still stored and they are 0.
        calibration_fn (str or None): Coil response file, for example a
            LEMI-120 .rsp. Relative paths resolve against the survey folder,
            then data_root. Used by LEMI-423 sites and by EDL sites whose
            `sensor_type` is lemi120.
        sensor_type (str or None): EDL (Earth Data PR6-24) sites: the
            magnetic sensors in mt-io's names
            (mt_workbench.instruments.EDL_SENSORS). "bartington" is Mag-03
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
            (mt_workbench.instruments.read_run). A `defaults:` value applies to the
            survey's EDL sites; a non-EDL site with its own key stops ingest
            with an error. Set with scripts/new_survey.py --electric-gain.
        electric_gain_ex (float): EDL sites: an extra gain on the ex line
            alone, beyond `electric_gain` (NF18 of South Australia AusLAMP
            2013-2018: an x64 stage on Ex only, its Ey right). One more
            forward coefficient stage, `uoa_electric_gain_ex`, on the ex chain
            after the reader's stages and `electric_gain`'s, so calibration
            divides ex by electric_gain x electric_gain_ex
            (mt_workbench.instruments.add_channel_electric_gains). A
            positive finite number; default 1.0, no stage. Not with
            `swap_e` (the exchange moves the input stages stage for stage).
        electric_gain_ey (float): The same for the ey line
            (`uoa_electric_gain_ey`).
        h_scale (float): LEMI-423 sites: extra gain folded into the magnetic
            channel filter chain. The LEMI-423 counts-to-field calibration
            comes out in pT with polarity inverted relative to the lemimt
            convention, hence -1000 (pT to nT plus sign), established against
            merged lemimt EDIs (without it, rho is offset by a constant 1e6
            and both phase modes by exactly 180 deg).
        e_sign (float or None): LEMI-424 sites: the sign every electric
            channel is multiplied by at ingest, 1.0 or -1.0
            (mt_workbench.ingest._apply_e_sign, recorded as the stage
            lemi424_e_sign in each channel's chain). The LEMI-424 records E1
            and E2 with the opposite sign to the x-north, y-east frame
            (every row out of quadrant at three of three Victorian cards
            with H in the field's direction; the WA-MT chain's Ex = -E1),
            so None, the key unset, means -1.0 on a LEMI-424 site. Set in
            `defaults:` for the survey (scripts/new_survey.py writes -1.0
            for a LEMI-424 survey); 1.0 there with per-site -1.0, or the
            reverse, is a one-line change. A line a crew laid reversed is
            declared on top of it as for any recorder (azimuth 180 or 270
            with `flip_reversed_dipoles`). A `defaults:` value is ignored on
            another recorder's site, and a site of another recorder whose
            own entry sets a value other than 1.0 stops ingest.
        flip_reversed_dipoles (bool): How to read a 180 or 270 deg dipole
            azimuth on the field sheet. True: the pair was wired
            reversed, so the data are sign-flipped at ingest. False:
            the azimuth records the layout direction, the logger's N/S/E/W
            terminals fix polarity, and the data keep their sign. Set per survey
            from the impedance phase quadrants
            (mt_workbench.compare.phase_quadrants); a wrong choice puts one mode
            180 deg out.
        swap_h (bool): True for a site whose two horizontal coils were
            plugged into each other's inputs, so that the recorded hx is the
            field along hy and the recorded hy the field along hx, both with
            normal polarity. Ingest then exchanges the hx and hy channels
            (mt_workbench.ingest._swap_h), each channel's samples moving with the
            filter chain of the input they were recorded on. Default False.
        flip_h (list of str or None): The coils whose recorded samples are
            the negative of the field along their channel's direction, from
            "hx", "hy" and "hz" with none repeated, e.g. [hy] for a coil
            cabled with its polarity reversed. The direction is the
            channel's own (hx along azimuth 0, hy along 90, hz down) and the
            sign the one the site's other coils give after `h_scale`, so
            a coil "reads minus" when its archive samples, unflipped,
            calibrate to minus the field its correctly cabled neighbour
            records. Ingest negates the samples of those channels
            (mt_workbench.ingest._flip_h), the filter chain unchanged, after
            `swap_h` is applied: the names are the channels as they are
            after the exchange. A coil pair turned through 90 deg is then
            `swap_h: true` plus `flip_h` naming the channel that reads minus
            after the exchange. At Nador P6S3 (M against P6S2, H_local =
            M H_base, 30-300 s: M_xy -1.02, M_yx +1.04) the recorded hx is
            -Hy and the recorded hy +Hx, where Hx and Hy are the field
            along 0 and 90 deg; after `swap_h` hx holds +Hx and hy holds
            -Hy, so the site declares `swap_h: true` and `flip_h: [hy]`.
            The other rotation (recorded hx = +Hy, hy = -Hx) is `swap_h:
            true` and `flip_h: [hx]`. With `h_from`, a site may not name hx
            or hy: the borrowed coils carry the neighbour's own `flip_h`.
            Default None, nothing flipped; an empty list is None.
        rot_h (float): The azimuth of magnetic north in a three-component
            fluxgate's own frame, in degrees measured from the sensor's x
            axis toward its y axis: atan2(mean hy, mean hx) of the record as
            the sensor wrote it (after `swap_h` and `flip_h`). The sensor's
            x axis therefore lies rot_h degrees anticlockwise (west) of
            magnetic north, seen from above; a negative value is east of
            it. Ingest turns the pair by it (mt_workbench.ingest._rot_h):
            hx' = cos(rot_h) hx + sin(rot_h) hy and hy' = -sin(rot_h) hx +
            cos(rot_h) hy, so that the record's mean horizontal field has
            hy' = 0 and hx' > 0 and hx, hy lie along magnetic north and east,
            the frame the electrodes were laid out in by compass; hz is not
            touched. A fluxgate set 21.6 deg east of magnetic north declares
            -21.6 (Tasmania AusLAMP 2016, TAS100); one facing south-southeast,
            whose hx reads minus the field, +157.6 (TAS107). It is measured
            and proposed by scripts/h_azimuth.py. The turn mixes the samples
            of two inputs, so their filter chains must have one response (a
            fluxgate pair on one logger; a LEMI-423's per-input linear
            coefficients are refused). Only a site's own entry may set it,
            within (-180, 180], on a site that keeps hx and hy, and not on a
            derived or observatory site (the archive of a derived site is
            decimated from its parent's turned archive) or a site with
            `h_from` (the borrowed coils carry the neighbour's own rot_h).
            Default 0.0, which changes nothing.
        swap_e (bool): True for a site whose two electric lines were
            connected to each other's inputs, so that the logger's ex input
            recorded the line declared as ey and its ey input the line
            declared as ex. Ingest exchanges the samples of ex and ey
            (mt_workbench.ingest._swap_e) before the reversed-dipole rule:
            each channel keeps its own dipole stage (the declared
            `dipole_length_*` and the sign of its `azimuth_*`), and every
            other stage of the chain, the logger input's own (the EDL
            terminal box, the LEMI-423 linear coefficient), moves with the
            samples. The lengths and azimuths are declared for the lines as
            they are after the exchange: TAS125 of Tasmania AusLAMP 2016,
            whose field sheet gives Ex 44.0 m at 270 deg and Ey 49.2 m at
            0 deg, declares `swap_e: true`, `azimuth_ex: 0.0`, `azimuth_ey:
            270.0`, `dipole_length_ex: 49.2` and `dipole_length_ey: 44.0`,
            and the reversed-dipole rule then flips ey. A Phoenix site's
            inputs are exchanged when they are read
            (mt_workbench.phoenix.component_of): the E2 input is stored as
            ex and the E1 input as ey, each with its samples, receiver
            curve, contact readings, rail and folder, at the declared
            lengths and azimuths of ex and ey. Allowed with `h_from`.
            Default False.
        clock_offset_s (float): Seconds added to the logger's recorded time
            stamps when the site's raw archive is ingested
            (mt_workbench.ingest._shift_clock): the archive's time of a sample
            is its recorded time plus this value. A logger that stamps its
            samples 1.000 s late, so that each sample's recorded time is
            1 s after the instant it was taken, gets -1.0; one that stamps
            them early gets a positive value. Every run's start time moves
            and the samples are untouched. Default 0.0, which changes
            nothing. Only a site's own entry may set it (not `defaults:`),
            and not a derived or observatory site, whose archives are not
            ingested from a logger's stamps (`Survey.site`); a value that
            is not finite or whose magnitude exceeds MAX_CLOCK_OFFSET_S is
            refused. A burst site does not take its recorded site's: its
            bursts carry GPS time, so it is 0.0 unless its own entry
            declares one (`Survey._burst_site`). `start` and `end` stay the
            header's recorded times.
        h_from (str or None): For a site that recorded electrics only
            (`channels` without hx and hy), the name of a nearby site of the
            same survey whose hx and hy the ingest takes in their place
            (mt_workbench.ingest.ingest_site): the neighbour's raw files are
            read with its own calibration, `h_scale`, `swap_h`, `flip_h`
            and `clock_offset_s`, and its samples taken at the local's GPS
            time stamps. Both sites must be LEMI-423, or both EDL (Tasmania
            AusLAMP 2016's TAS132 takes TAS131's), or both Orange Box
            (Kalgoorlie LP 2006's Kal05 takes Kal03's: the neighbour's run on
            the same UTC 10 Hz grid; the local's own recorded hx and hy are
            replaced, so an Orange Box site may keep hx and hy in
            `channels`), at the same sample rate.
            Only a site's own entry may set it; the site may not declare hx,
            hy, `swap_h`, a `flip_h` naming hx or hy, or derive from another
            site, and the neighbour may not
            be derived, an observatory, `h_from` itself, or declare channels
            without hx and hy (`Survey.site`). Default None.
        channels (list of str or None): Channels kept at ingest; None keeps
            every column the reader returns. Broadband deployments carried
            no hz sensor (the B423 Bz column is an open input, constant
            -2^31), so those surveys set [ex, ey, hx, hy] and aurora
            estimates no tipper from a dead channel. The usual sets are in
            CHANNEL_PRESETS; a site whose set differs from `defaults:` has
            its own.
        filters (list of dict or None): Declared time-domain filters applied
            at ingest, in order (see mt_workbench.noise), from
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
            With `record_window`, `start` and `end` must lie inside the
            window (`Survey.site` refuses otherwise), so the span the
            campaign and scripts/h_azimuth.py read from survey.yaml is the
            clipped span.
        record_window (list or None): [start, end], UTC ISO times (either
            may be null for no bound): ingest keeps only the samples at
            instants t with start <= t < end (mt_workbench.ingest._record_window):
            a run is clipped, a run wholly outside is left out, and the run
            comment and the station's ``provenance.comments`` record it. For
            a record whose raw folder also holds another occupation's files
            (SA106 of South Australia AusLAMP 2013-2018 holds 767 h of
            SA106_2's, from 2014-12-14) or hours when a sensor was dead.
            Stored as two ISO strings ("...Z") or None. Default None.
        rot_h_parts (list or None): [[start, end, angle_deg], ...], UTC ISO
            times (start <= t < end) and the sensor azimuth of each part,
            for a fluxgate that turned during the record (FR12 of South
            Australia AusLAMP 2013-2018): ingest turns hx
            and hy by each part's angle over that part (as `rot_h` turns
            the whole record) and leaves out every sample outside all parts,
            as `record_window` does, so the stretch of the turn is masked
            by leaving it out of both parts (mt_workbench.ingest._rot_h_parts).
            Parts must not overlap and are stored sorted; mutually exclusive
            with a non-zero `rot_h` and with `h_from`; refused on a derived
            or observatory site. `start` and `end` must lie inside
            [first part's start, last part's end]. Default None.
        h_tilt (list or None): [rx, ry, rz], a rotation vector in degrees
            in the sensor axes (x, y, z as the channels are after `swap_h`
            and `flip_h`), for a three-component fluxgate whose sensor was
            not level (SA029E of South Australia AusLAMP 2013-2018):
            the field in the level frame is B_level = R
            B_sensor, R the right-hand rotation by |r| degrees about
            r/|r|. Ingest turns hx, hy and hz together by R in physical
            units (each channel's counts through its own chain's gain, so
            chains of different gain or sign are exact), before `rot_h`
            (mt_workbench.ingest._h_tilt); the minimal rotation taking the
            measured main-field vector onto IGRF's (H, 0, Z) is one such
            vector (its twist about the field is not fixed by one vector).
            Each a finite number, not all zero, |r| at most
            MAX_H_TILT_DEG. Refused with `h_from`, on a derived or
            observatory site, with `rot_h_parts`, with channels lacking
            hx, hy or hz (`edl_banks_swapped` records no hz), and on an
            instrument other than an EDL or Orange Box fluxgate. Default
            None.
        edl_banks_swapped (bool): EDL sites: True for a site whose
            magnetometer and electrode cables were plugged into each other's
            banks of the PR6-24 (inputs 1-3 and 4-6), so the .EX and .EY files
            hold the fluxgate's x and y and the .BX and .BY files the
            electrode lines. Ingest stores the .EX words as hx and the .EY
            words as hy through the magnetometer chain, the .BX words as ex
            and the .BY words as ey through the electric chain of the
            declared dipole lengths and azimuths, and no hz (the .BZ file
            holds the electric bank's spare input; the fluxgate's z was not
            recorded) (mt_workbench.ingest._edl_banks_swapped). Not with
            `h_from` (the site's own magnetometer is the point) or with the
            site's own `channels:` naming hz. Default False.
        derived_from (str or None): The recorded site whose processing
            archive scripts/decimate_site.py decimated into this site's
            archive (`D02L` from `D02`), or scripts/diagonal_site.py made
            the diagonal line of (`TAS112D` from `TAS112`: channels [ex, hx,
            hy, hz], ex the dipole between the outer electrodes, of length
            `dipole_length_ex` along `azimuth_ex`, any azimuth). A derived
            site has no raw folder; `Survey.instrument_of` gives its
            parent's recorder.
        sample_rate (float or None): The site's own sample rate in Hz, set
            on a derived site (1.0) and a burst site (24000); None means the
            survey's `sample_rate` (`Survey.sample_rate_of`).
        recording (str or None): Phoenix sites: the recording folder,
            relative to the site folder, for a site folder that holds
            several. None means the one folder under the site folder that
            holds empower_recmeta.json or recmeta.json beside numbered
            channel folders (mt_workbench.phoenix).
        calibration_dir (str or None): Phoenix sites: the folder of the
            receivers' ``<receiver>_*.rxcal.json`` and the coils'
            ``<serial>_*.scal.json`` files, resolved like
            `calibration_fn`. Required on a Phoenix site.
        coil_hx (str or None): Phoenix sites: the serial of the coil on hx,
            overriding the serial mt-io reads from the receiver metadata
            file (empower_recmeta.json first). For a coil whose own report
            in backend.log, or the field sheet, contradicts the metadata
            file. None takes the metadata file's.
        coil_hy (str or None): As `coil_hx`, for hy.
        coil_hz (str or None): As `coil_hx`, for hz.
        electric_full_scale_uv (float or None): Orange Box sites: the
            electric full scale of the box in microVolt, 25000 for the
            +/-2.5 V boxes before July 2010 and 100000 for the +/-10 V ones
            after (docs/upstream_issues.md 13); passed to mt-io's reader,
            whose ex and ey gain is -2**23 x L / full scale. No default: an
            Orange Box site without it, in its entry or `defaults:`, is
            refused at ingest. Refused in the entry of another recorder's
            site.
        magnetic_full_scale_nt (float or None): Orange Box sites: the
            Bartington fluxgate's full scale in nT, 70000 or 100000
            (docs/upstream_issues.md 14); the gain of hx, hy and hz is
            2**23 / full scale. No default, as `electric_full_scale_uv`.
        clock_timezone (str): Orange Box sites: the IANA name of the zone
            the logger's real-time clock ran on, with which its header and
            trailer stamps are read as UTC (zoneinfo, so daylight saving
            follows the zone's rules). Default "UTC". The Kalgoorlie 2006
            boxes ran on Western Standard Time ("Australia/Perth").
        clock_drift_s (float or None): Orange Box sites: GPS minus logger at
            recovery, in seconds, the field reading (param.mt line 10, the
            field sheet's Drift). The ingest spreads it linearly over the
            deployment (mt_workbench.orangebox.time_base). None, the key
            unset, means not recorded: no correction, and each run comment
            says "drift unrecorded". A value that is not finite or whose
            magnitude exceeds MAX_CLOCK_DRIFT_S is refused. `clock_offset_s`
            stays a separate constant shift.
        time_base (str): Orange Box sites: "headers" (the default: the
            header-stamp line with `clock_drift_s`,
            mt_workbench.orangebox.time_base) or "nominal" (the reader's own
            axis: first header in UTC, the nominal 10.00064 Hz, no drift; for
            comparison only).
            "nominal" with `clock_drift_s` set is refused.
        bursts_of (str or None): On a burst site (``<site>H``), the
            recorded Phoenix site whose 24 kHz bursts its archive holds.
            Its entry holds only `BURST_SITE_KEYS`, with `sample_rate`
            24000; `Survey.site` gives it the recorded site's settings
            under its own name, with its own `clock_offset_s` (0.0 unless
            declared).
        logger_pid (str or None): The DOI of the site's data logger in the
            AuScope instrument registry (PIDINST,
            https://pidinst.data.auscope.org.au/), written bare,
            ``10.<prefix>/<suffix>`` ("10.82388/25jrcc6q"); a URL or a
            "doi:" prefix is refused. The word "none" (any case, stored
            lower case) declares an instrument the registry does not hold,
            with the reason in `notes`. None, the key unset, records
            nothing. The keys are declared, never fetched
            (scripts/pidinst_lookup.py proposes them from `serial` and the
            coil serials); `Survey.instrument_pids` resolves them, ingest
            writes them into the run and station comments
            (`Survey.registry_note`) and scripts/process_rr.py into the
            sidecar, the EDI's INFO block and the XML's Notes.
        sensor_pid_hx (str or None): As `logger_pid`, for the magnetic
            sensor on hx where it has a record of its own (a LEMI-120 or
            MTC-150 coil); unset for a fluxgate inside a logger's record
            (the Orange Box).
        sensor_pid_hy (str or None): As `sensor_pid_hx`, for hy.
        sensor_pid_hz (str or None): As `sensor_pid_hx`, for hz.
        electrode_pid (str or None): As `logger_pid`, for the electrodes
            (reserved: none are registered in 2026).
        platform_pid (str or None): As `logger_pid`, for the survey
            deployment's platform record. Usually declared once at the top
            level of survey.yaml (`Survey.platform_pid`); a site's own (in
            its entry or `defaults:`) wins, for a survey that spans two
            deployment records.
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
    declination: float | None = None
    declination_model: str | None = None
    declination_epoch: float | None = None
    layout_north: str = "magnetic"
    calibration_fn: str | None = None
    sensor_type: str | None = None
    electric_gain: float = 1.0
    electric_gain_ex: float = 1.0
    electric_gain_ey: float = 1.0
    h_scale: float = 1.0
    e_sign: float | None = None
    flip_reversed_dipoles: bool = True
    swap_h: bool = False
    flip_h: list[str] | None = None
    rot_h: float = 0.0
    swap_e: bool = False
    clock_offset_s: float = 0.0
    h_from: str | None = None
    channels: list[str] | None = None
    filters: list[dict] | None = None
    timing: str | None = None
    notes: str | None = None
    remote: str | None = None
    serial: str | None = None
    firmware: str | None = None
    start: str | None = None
    end: str | None = None
    record_window: list | None = None
    rot_h_parts: list | None = None
    h_tilt: list | None = None
    edl_banks_swapped: bool = False
    derived_from: str | None = None
    sample_rate: float | None = None
    recording: str | None = None
    calibration_dir: str | None = None
    coil_hx: str | None = None
    coil_hy: str | None = None
    coil_hz: str | None = None
    bursts_of: str | None = None
    electric_full_scale_uv: float | None = None
    magnetic_full_scale_nt: float | None = None
    clock_timezone: str = "UTC"
    clock_drift_s: float | None = None
    time_base: str = "headers"
    logger_pid: str | None = None
    sensor_pid_hx: str | None = None
    sensor_pid_hy: str | None = None
    sensor_pid_hz: str | None = None
    electrode_pid: str | None = None
    platform_pid: str | None = None

    def __post_init__(self) -> None:
        """Check `layout_north`, `clock_offset_s` and `rot_h` (stored as floats), `swap_e`, `h_from` and `flip_h`.

        The registry keys (`PID_KEYS`) are checked by `check_pid`.
        `flip_h` is stored lower case in the order of `FLIP_H_CHANNELS`, or
        None for an empty list. `e_sign`, when set, must be 1.0 or -1.0 and
        is stored as a float. The Orange Box keys: the full scales, when
        set, must be positive finite numbers, `clock_timezone` a zone
        known to zoneinfo and `clock_drift_s`, when set, a finite number within
        +/-MAX_CLOCK_DRIFT_S; numbers are stored as floats. `time_base` must
        be one of mt_workbench.orangebox.TIME_BASES, and "nominal" comes
        without `clock_drift_s`.
        """
        self._check_orangebox_keys()
        sign = self.e_sign
        if sign is not None:
            if isinstance(sign, bool) or not isinstance(sign, (int, float)) or float(sign) not in (1.0, -1.0):
                raise ValueError(f"site {self.name!r}: e_sign {sign!r} is not 1.0 or -1.0: the sign the LEMI-424's "
                                 f"electric channels are multiplied by at ingest")
            self.e_sign = float(sign)
        turn = self.rot_h
        number = isinstance(turn, (int, float)) and not isinstance(turn, bool)
        if not number or not math.isfinite(turn) or not -180.0 < turn <= 180.0:
            raise ValueError(
                f"site {self.name!r}: rot_h {turn!r} is not a sensor azimuth: expected a finite number of degrees "
                f"in (-180, 180], the azimuth of magnetic north from the fluxgate's x axis toward its y axis "
                f"(scripts/h_azimuth.py --propose)")
        self.rot_h = float(turn)
        if not isinstance(self.swap_e, bool):
            raise ValueError(f"site {self.name!r}: swap_e {self.swap_e!r} is not true or false")
        if not isinstance(self.edl_banks_swapped, bool):
            raise ValueError(f"site {self.name!r}: edl_banks_swapped {self.edl_banks_swapped!r} is not true or false")
        for key in ("electric_gain_ex", "electric_gain_ey"):
            gain = getattr(self, key)
            number = isinstance(gain, (int, float)) and not isinstance(gain, bool)
            if not number or not math.isfinite(gain) or gain <= 0:
                raise ValueError(f"site {self.name!r}: {key} {gain!r} is not a gain: expected a positive finite "
                                 f"number, the extra forward gain of that electric line (calibration divides by it)")
            setattr(self, key, float(gain))
        self.record_window = _record_window(self.name, self.record_window)
        self.rot_h_parts = _rot_h_parts(self.name, self.rot_h_parts)
        self.h_tilt = _h_tilt(self.name, self.h_tilt)
        if self.rot_h_parts and self.rot_h != 0.0:
            raise ValueError(f"site {self.name!r}: rot_h {self.rot_h!r} with rot_h_parts: one angle for the whole "
                             f"record and one per part cannot both apply; keep rot_h_parts and remove rot_h")
        if self.layout_north not in LAYOUT_NORTH:
            raise ValueError(f"site {self.name!r}: layout_north {self.layout_north!r}, expected one of "
                             f"{', '.join(LAYOUT_NORTH)}")
        offset = self.clock_offset_s
        number = isinstance(offset, (int, float)) and not isinstance(offset, bool)
        if not number or not math.isfinite(offset) or abs(offset) > MAX_CLOCK_OFFSET_S:
            raise ValueError(
                f"site {self.name!r}: clock_offset_s {offset!r} is not a clock offset: expected a finite "
                f"number of seconds within +/-{MAX_CLOCK_OFFSET_S:g}, added to the recorded time stamps "
                f"(-1.0 for a logger that stamps its samples 1 s late)")
        self.clock_offset_s = float(offset)
        if self.h_from is not None and (not isinstance(self.h_from, str) or not self.h_from.strip()):
            raise ValueError(f"site {self.name!r}: h_from {self.h_from!r} is not a site name: quote it in "
                             f"survey.yaml (h_from: \"<site>\")")
        self.flip_h = _flip_h_channels(self.name, self.flip_h)
        for key in ("coil_hx", "coil_hy", "coil_hz", "serial"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, bool) and isinstance(value, (int, float)):
                setattr(self, key, str(int(value)) if float(value).is_integer() else str(value))
        for key in PID_KEYS:
            setattr(self, key, check_pid(f"site {self.name!r}", key, getattr(self, key)))


    def _check_orangebox_keys(self) -> None:
        """Check and store the Orange Box keys (see `__post_init__`)."""
        for key in ("electric_full_scale_uv", "magnetic_full_scale_nt"):
            value = getattr(self, key)
            if value is None:
                continue
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not number or not math.isfinite(value) or value <= 0:
                raise ValueError(f"site {self.name!r}: {key} {value!r} is not a full scale: expected a positive "
                                 f"number (Orange Box: 25000 or 100000 uV for the electrics, 70000 or 100000 nT "
                                 f"for the fluxgate)")
            setattr(self, key, float(value))
        zone = self.clock_timezone
        if not isinstance(zone, str) or not zone.strip():
            raise ValueError(f"site {self.name!r}: clock_timezone {zone!r} is not a zone name: expected an IANA "
                             f"name such as Australia/Perth")
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"site {self.name!r}: clock_timezone {zone!r} is not a zone known to zoneinfo: expected "
                             f"an IANA name such as Australia/Perth") from None
        drift = self.clock_drift_s
        if drift is not None:
            number = isinstance(drift, (int, float)) and not isinstance(drift, bool)
            if not number or not math.isfinite(drift) or abs(drift) > MAX_CLOCK_DRIFT_S:
                raise ValueError(f"site {self.name!r}: clock_drift_s {drift!r} is not a clock drift: expected a "
                                 f"finite number of seconds within +/-{MAX_CLOCK_DRIFT_S:g}, GPS minus logger at "
                                 f"recovery")
            self.clock_drift_s = float(drift)
        from .orangebox import TIME_BASES

        if self.time_base not in TIME_BASES:
            raise ValueError(f"site {self.name!r}: time_base {self.time_base!r} is not an Orange Box time base: "
                             f"expected one of {', '.join(TIME_BASES)}")
        if self.time_base == "nominal" and self.clock_drift_s is not None:
            raise ValueError(f"site {self.name!r}: time_base nominal with clock_drift_s {self.clock_drift_s!r}: the "
                             f"nominal axis applies no drift; remove one of the two keys")


def check_pid(where: str, key: str, value) -> str | None:
    """Return a registry key's value as stored: a bare DOI, "none" or None.

    Args:
        where (str): Whose key it is, for messages ("site 'Kal024'",
            "survey.yaml").
        key (str): The key (`PID_KEYS`).
        value: The declared value.

    Returns:
        str or None: The DOI as declared (surrounding spaces removed),
        `PID_NONE` for the word none in any case, None for None.

    Raises:
        ValueError: If the value is not a string of the form
            ``10.<prefix>/<suffix>`` or the word none (a URL, a "doi:"
            prefix, a number or an empty string).
    """
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else None
    if text is not None and text.lower() == PID_NONE:
        return PID_NONE
    if text is None or not DOI_PATTERN.match(text):
        raise ValueError(f"{where}: {key} {value!r} is not a registry DOI: write it bare as 10.<prefix>/<suffix> "
                         f"(e.g. 10.82388/25jrcc6q, no https://doi.org/ and no doi:), or none for an instrument "
                         f"the registry does not hold, with the reason in the site's notes")
    return text


def pid_text(pids: dict) -> str:
    """Return resolved registry DOIs as one line: "logger <doi>, sensor_hx <doi>, platform <doi>".

    Args:
        pids (dict): Role to DOI or "none" (`Survey.instrument_pids`).

    Returns:
        str: The roles and values in order, joined by ", " (no semicolon,
        so the line is one piece of a run comment).
    """
    return ", ".join(f"{role} {value}" for role, value in pids.items())


def _flip_h_channels(name: str, given) -> list[str] | None:
    """Return a declared `flip_h` as lower-case channels in `FLIP_H_CHANNELS` order.

    Args:
        name (str): Site name, for messages.
        given: The declared value: None or a list of channel names.

    Returns:
        list of str or None: The channels; None for None or an empty list.

    Raises:
        ValueError: If the value is not a list of strings, names a channel
            other than hx, hy and hz, or names one twice.
    """
    if given is None:
        return None
    if not isinstance(given, (list, tuple)) or not all(isinstance(c, str) for c in given):
        raise ValueError(f"site {name!r}: flip_h {given!r} is not a list of coil channels: write it as "
                         f"flip_h: [hy] (or [hx], [hx, hy]; hz too)")
    names = [c.strip().lower() for c in given]
    other = [c for c in names if c not in FLIP_H_CHANNELS]
    if other:
        raise ValueError(f"site {name!r}: flip_h names {other}: only the coil channels "
                         f"{', '.join(FLIP_H_CHANNELS)} are flipped by it (a reversed dipole is "
                         f"flip_reversed_dipoles)")
    twice = sorted({c for c in names if names.count(c) > 1})
    if twice:
        raise ValueError(f"site {name!r}: flip_h names {twice} more than once; each named coil is negated once")
    return [c for c in FLIP_H_CHANNELS if c in names] or None


def _window_time(value):
    """Return a record_window bound as a UTC pandas Timestamp, None for null; ValueError when not a time."""
    import pandas as pd

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, pd.Timestamp)) and not hasattr(value, "isoformat"):
        raise ValueError(f"{value!r} is not a time")
    try:
        t = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{value!r} is not a time") from exc
    if pd.isna(t):
        raise ValueError(f"{value!r} is not a time")
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _record_window(name: str, given) -> list | None:
    """Return a declared `record_window` as [start, end] ISO strings ("...Z") or None per bound; None when unset.

    Raises:
        ValueError: If it is not a list of two, a bound is not a time, both
            are null, or start is not before end.
    """
    if given is None:
        return None
    how = "write it as record_window: [\"2014-11-14T09:00:00Z\", \"2014-11-23T19:00:00Z\"] (either may be null)"
    if not isinstance(given, (list, tuple)) or len(given) != 2:
        raise ValueError(f"site {name!r}: record_window {given!r} is not [start, end]: {how}")
    try:
        lo, hi = (_window_time(v) for v in given)
    except ValueError as exc:
        raise ValueError(f"site {name!r}: record_window {list(given)!r}: {exc}: {how}") from None
    if lo is None and hi is None:
        raise ValueError(f"site {name!r}: record_window [null, null] limits nothing: remove the key")
    if lo is not None and hi is not None and not lo < hi:
        raise ValueError(f"site {name!r}: record_window starts {lo} at or after its end {hi}")
    return [None if t is None else t.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z" for t in (lo, hi)]


def _rot_h_parts(name: str, given) -> list | None:
    """Return a declared `rot_h_parts` as sorted [[start "...Z", end "...Z", angle float], ...]; None when unset.

    Raises:
        ValueError: If it is not a non-empty list of [start, end, angle], a
            bound is not a time (null is not allowed), start is not before
            end, an angle is not a finite number in (-180, 180], or two
            parts overlap.
    """
    if given is None:
        return None
    how = ("write it as rot_h_parts: [[\"2013-09-21T02:00:00Z\", \"2013-10-03T05:00:00Z\", 12.3], "
           "[\"2013-10-03T07:00:00Z\", \"2013-10-07T00:00:00Z\", 71.2]]")
    if not isinstance(given, (list, tuple)) or not given:
        raise ValueError(f"site {name!r}: rot_h_parts {given!r} is not a list of [start, end, angle_deg]: {how}")
    out = []
    for part in given:
        if not isinstance(part, (list, tuple)) or len(part) != 3:
            raise ValueError(f"site {name!r}: rot_h_parts part {part!r} is not [start, end, angle_deg]: {how}")
        try:
            lo, hi = (_window_time(v) for v in part[:2])
        except ValueError as exc:
            raise ValueError(f"site {name!r}: rot_h_parts part {list(part)!r}: {exc}: {how}") from None
        if lo is None or hi is None:
            raise ValueError(f"site {name!r}: rot_h_parts part {list(part)!r}: both bounds are needed: {how}")
        if not lo < hi:
            raise ValueError(f"site {name!r}: rot_h_parts part {list(part)!r}: its start is not before its end")
        angle = part[2]
        number = isinstance(angle, (int, float)) and not isinstance(angle, bool)
        if not number or not math.isfinite(angle) or not -180.0 < angle <= 180.0:
            raise ValueError(f"site {name!r}: rot_h_parts part {list(part)!r}: angle {angle!r} is not a sensor "
                             f"azimuth in (-180, 180] (as rot_h)")
        out.append((lo, hi, float(angle)))
    out.sort(key=lambda p: p[0])
    for (a0, a1, _), (b0, b1, _) in zip(out, out[1:]):
        if b0 < a1:
            raise ValueError(f"site {name!r}: rot_h_parts parts overlap ({a0} .. {a1} and {b0} .. {b1}): each sample "
                             f"takes one turn")
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"  # noqa: E731
    return [[iso(lo), iso(hi), angle] for lo, hi, angle in out]


# the largest angle of a declared `h_tilt`: a sensor tipped further is not a levelling error but a sensor on its side
MAX_H_TILT_DEG = 45.0
# the instruments whose three-component fluxgate `h_tilt` is built and tested for (tests/ingest_h_tilt_unit.py)
H_TILT_INSTRUMENTS = ("edl", "orangebox")


def _h_tilt(name: str, given) -> list | None:
    """Return a declared `h_tilt` as [rx, ry, rz] floats (degrees); None when unset.

    Raises:
        ValueError: If it is not a list of three finite numbers (no bool), is the zero vector, or turns by more than
            MAX_H_TILT_DEG.
    """
    if given is None:
        return None
    how = ("write it as h_tilt: [rx, ry, rz], a rotation vector in degrees in the sensor axes (B_level = R B_sensor, "
           "R the right-hand rotation by |r| about r/|r|), e.g. h_tilt: [0.0, 11.2, 0.0]")
    ok = (isinstance(given, (list, tuple)) and len(given) == 3
          and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in given))
    if not ok:
        raise ValueError(f"site {name!r}: h_tilt {given!r} is not [rx, ry, rz] (three finite numbers): {how}")
    vec = [float(v) for v in given]
    angle = math.sqrt(sum(v * v for v in vec))
    if angle == 0.0:
        raise ValueError(f"site {name!r}: h_tilt {given!r} is the zero vector (no turn): remove the key")
    if angle > MAX_H_TILT_DEG:
        raise ValueError(f"site {name!r}: h_tilt {given!r} turns by {angle:.2f} deg, more than {MAX_H_TILT_DEG:g}: a "
                         f"sensor tipped that far is not a levelling error (swap_h, flip_h or a field check)")
    return vec


def window_bounds(config) -> tuple:
    """Return a site's `record_window` as (start, end) UTC pandas Timestamps, None for an open bound or no key."""
    window = getattr(config, "record_window", None)
    if not window:
        return None, None
    return tuple(_window_time(v) for v in window)


def _check_known_keys(name: str, merged: dict, own: dict) -> None:
    """Refuse a site setting that `SiteConfig` does not declare.

    Without this check the dataclass raises TypeError ("unexpected keyword
    argument"), which scripts that catch ValueError do not report as a
    configuration error.

    Args:
        name (str): Site name.
        merged (dict): The merged `defaults:` and site entry.
        own (dict): The site's own entry, to say where a key came from.

    Raises:
        ValueError: Naming each unknown key and whether it is in the site's
            entry or in `defaults:`.
    """
    known = {f.name for f in fields(SiteConfig)} - {"name"}
    unknown = sorted(k for k in merged if k not in known)
    if unknown:
        where = ", ".join(f"{k!r} ({'site entry' if k in own else 'defaults:'})" for k in unknown)
        raise ValueError(f"site {name!r}: unknown survey.yaml key(s) {where}; known keys: "
                         f"{', '.join(sorted(known))}")


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
        # the survey deployment's registry record (`SiteConfig.platform_pid`), checked here
        self._platform_pid = check_pid("survey.yaml", "platform_pid", config.get("platform_pid"))
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
        """Load a survey from its survey.yaml path.

        A name longer than 30 characters is logged as a warning: mth5's
        channel and run summaries keep 30 (docs/upstream_issues.md 550), and
        `mt_workbench.process.kernel_dataset` puts the full id back.
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        survey = cls(config, path.parent)
        if len(survey.name) > 30:
            logger.warning(f"survey name {survey.name!r} has {len(survey.name)} characters: mth5's channel and run "
                           f"summaries keep 30 (docs/upstream_issues.md 550); processing puts the full id back "
                           f"(mt_workbench.process.kernel_dataset)")
        return survey

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

    # keys of the `processing:` block that are not band-scheme keywords: the
    # window floor and the STFT overlaps, read by their own properties
    _PROCESSING_ESTIMATOR_KEYS = ("min_band_windows", "overlap", "overlap_long")

    @property
    def processing(self) -> dict:
        """Band/period targets for aurora (kwargs for mt_workbench.bands schemes).

        The block's `min_band_windows`, `overlap` and `overlap_long` are
        left out (`min_band_windows`, `overlap_pct`, `overlap_pct_long`):
        they are estimator settings, not band-scheme keywords.
        """
        block = self.config.get("processing") or {}
        return {k: v for k, v in block.items() if k not in self._PROCESSING_ESTIMATOR_KEYS}

    def _overlap_key(self, key: str) -> float | None:
        """Return the `processing:` block's `key` as an overlap in percent, or None when unset."""
        value = (self.config.get("processing") or {}).get(key)
        if value is None:
            return None
        pct = float(value)
        if not 0.0 <= pct < 100.0:
            raise ValueError(f"{self.config_dir / 'survey.yaml'}: processing: {key}: {value!r} is not an STFT "
                             f"overlap in percent (0 or more, under 100)")
        return pct

    @property
    def overlap_pct(self) -> float | None:
        """The `processing:` block's STFT overlap in percent for every level, or None when unset.

        None means the default of `scripts/process_rr.py` (25 % of the window;
        `mt_workbench.process.ESTIMATOR_DEFAULTS`); `--overlap` on a run wins.
        """
        return self._overlap_key("overlap")

    @property
    def overlap_pct_long(self) -> float | None:
        """The `processing:` block's STFT overlap in percent for the long levels only, or None when unset.

        The long levels are those whose window lasts over
        `mt_workbench.process.LONG_WINDOW_SECONDS` (600 s); None means the
        default 75 % boost of `mt_workbench.process.build_config`, which counts
        overlapped windows as independent and so prints errors about 1.8
        times too small there (docs/workbench_issues.md 170); `--overlap-long`
        on a run wins.
        """
        return self._overlap_key("overlap_long")

    @property
    def min_band_windows(self) -> int | None:
        """The `processing:` block's floor on STFT windows per band, or None when unset.

        A period whose band rests on fewer windows is not written
        (`mt_workbench.process.drop_short_bands`); None means the default,
        `mt_workbench.process.MIN_BAND_WINDOWS`.
        """
        value = (self.config.get("processing") or {}).get("min_band_windows")
        return None if value is None else int(value)

    @property
    def platform_pid(self) -> str | None:
        """The top-level `platform_pid:`, the deployment's registry DOI or "none"; None when unset."""
        return self._platform_pid

    def instrument_pids(self, name: str) -> dict[str, str]:
        """Return the registry DOIs a site declares, by role, in `PID_ROLES` order.

        The site's merged settings (`site`) give its logger, sensors,
        electrode and platform (its own `platform_pid`, else the top-level
        one). A site with `h_from` adds ``logger_hx_hy``, the neighbour's
        `logger_pid`, and takes the neighbour's `sensor_pid_hx` and
        `sensor_pid_hy`, which recorded its hx and hy. A derived site whose
        own entry declares no registry key takes its parent's; a burst
        site has its recorded site's settings (`_burst_site`). A name
        with no entry, such as a stacked remote, gives an empty dict
        (scripts/process_rr.py lists a stack's members').

        Args:
            name (str): Site name.

        Returns:
            dict: Role ("logger", "logger_hx_hy", "sensor_hx", "sensor_hy",
            "sensor_hz", "electrode", "platform") to a DOI or "none"; the
            roles with no value left out; empty when the survey declares
            none for the site.
        """
        own = self._sites.get(name)
        if own is None:
            return {}
        parent = self.parent_of(name)
        if parent and not any(key in own for key in PID_KEYS):
            return self.instrument_pids(parent)
        config = self.site(name)
        found = {role: getattr(config, key) for key, role in PID_ROLES.items()}
        if found["platform"] is None:
            found["platform"] = self.platform_pid
        hx_hy = None
        if config.h_from:
            neighbour = self.site(config.h_from)
            hx_hy = neighbour.logger_pid
            for comp in ("hx", "hy"):
                if getattr(neighbour, f"sensor_pid_{comp}") is not None:
                    found[f"sensor_{comp}"] = getattr(neighbour, f"sensor_pid_{comp}")
        out = {"logger": found["logger"], "logger_hx_hy": hx_hy}
        out.update((role, found[role]) for role in PID_ROLES.values() if role != "logger")
        return {role: value for role, value in out.items() if value is not None}

    def registry_note(self, name: str) -> str | None:
        """Return the run and station comment piece of a site's registry DOIs, or None when it has none.

        Args:
            name (str): Site name.

        Returns:
            str or None: ``REGISTRY_PREFIX`` and `pid_text` of
            `instrument_pids` ("instrument_registry: logger 10.82388/25jrcc6q,
            platform none").
        """
        pids = self.instrument_pids(name)
        return f"{REGISTRY_PREFIX}{pid_text(pids)}" if pids else None

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
        workspace. A derived site (`parent_of`), a burst site
        (`bursts_parent`) and an observatory (`OBSERVATORY`) have an
        archive and no folder, and are not listed; a derived site's
        parent's folder is ``site_dirs()[parent_of(site)]``, a burst site's
        ``site_dirs()[raw_site(site)]``.

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

        The site's own `instrument:` wins, then, for a derived or burst
        site, its parent's recorder, then the instrument detected in
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
        parent = self.parent_of(site) or self.bursts_parent(site)
        if parent:
            if parent == site:
                raise ValueError(f"{site}: derived_from or bursts_of names the site itself")
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

    def bursts_parent(self, site: str) -> str | None:
        """Return the recorded site whose bursts a burst site's archive holds.

        Args:
            site (str): Site name.

        Returns:
            str or None: The site entry's `bursts_of:`; None for any other
            site and for a name with no entry.
        """
        parent = (self._sites.get(site) or {}).get("bursts_of")
        return str(parent) if parent else None

    def raw_site(self, site: str) -> str:
        """Return the site whose raw folder a site's archive is ingested from.

        A burst site's is its `bursts_of` site; every other site's is its
        own.

        Args:
            site (str): Site name.

        Returns:
            str: Site name.
        """
        return self.bursts_parent(site) or site

    def sample_rate_of(self, site: str) -> float:
        """Return the sample rate of a site's archive in Hz.

        The site entry's own `sample_rate:` wins (a derived site's 1.0); an
        INTERMAGNET observatory entry (`instrument: intermagnet`, written by
        scripts/fetch_observatory.py) is at `mt_workbench.observatory.FS`; every
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
        defaults and a logged warning. A LEMI-424 site's `channels:` in the
        reader's names (e1 e2 bx by bz, as written before the store renamed
        them, docs/workbench_issues.md 92) is read in the stored names
        (`mt_workbench.instruments.LEMI424_RENAME`). A burst site (`bursts_of:`) gets its
        recorded site's settings under its own name, with its own
        `sample_rate`, `remote`, `notes` and `clock_offset_s` (`_burst_site`).

        Args:
            name (str): Site name.

        Returns:
            SiteConfig: The merged settings.

        Raises:
            ValueError: If a key is not a `SiteConfig` field
                (`_check_known_keys`), a setting is refused by `SiteConfig`,
                `defaults:` sets a non-zero `clock_offset_s`, or a derived or
                observatory site sets one: its archive is decimated from
                its parent's archive, which carries the parent's shifted
                stamps, or fetched from INTERMAGNET, and is not ingested
                from a logger's stamps; or `h_from` is set in `defaults:`
                or refused by `_check_h_from`; or `flip_h` names a channel
                the site's `channels:` does not keep; or `rot_h` is set in
                `defaults:` or on a derived or observatory site, or with
                `channels:` that do not keep hx and hy; or `swap_e` with
                `channels:` that do not keep ex and ey; or a burst site's
                entry is refused by `_burst_site`.
        """
        if self._defaults.get("clock_offset_s", 0.0) not in (0, 0.0, None):
            raise ValueError(f"clock_offset_s {self._defaults['clock_offset_s']!r} in `defaults:`: it is one "
                             f"logger's clock error, so set it in that site's own entry")
        if self._defaults.get("h_from") is not None:
            raise ValueError(f"h_from {self._defaults['h_from']!r} in `defaults:`: it names one site's "
                             f"neighbour, so set it in that site's own entry")
        if self._defaults.get("rot_h", 0.0) not in (0, 0.0, None):
            raise ValueError(f"rot_h {self._defaults['rot_h']!r} in `defaults:`: it is one sensor's azimuth, so "
                             f"set it in that site's own entry (scripts/h_azimuth.py --propose)")
        if self.bursts_parent(name):
            return self._burst_site(name)
        overrides = self._sites.get(name)
        if overrides is None:
            logger.warning(
                f"site {name!r} has no entry in survey.yaml; using survey "
                f"defaults (check dipole lengths/azimuths!)"
            )
            overrides = {}
        merged = {**self._defaults, **overrides}
        old = [str(c).lower() for c in merged.get("channels") or [] if str(c).lower() in LEMI424_RENAME]
        if old and self.instrument_of(name) == "lemi424":
            # a LEMI-424 `channels:` written in the reader's names (before the store renamed them)
            merged["channels"] = [LEMI424_RENAME.get(str(c).lower(), str(c).lower()) for c in merged["channels"]]
        if name in self._filters and "filters" not in merged:
            merged["filters"] = self._filters[name]
        _check_known_keys(name, merged, overrides)
        config = SiteConfig(name=name, **merged)
        if config.clock_offset_s != 0.0:
            parent = self.parent_of(name)
            if parent:
                raise ValueError(f"{name}: clock_offset_s {config.clock_offset_s!r} on a site derived from "
                                 f"{parent}: its archive is decimated from {parent}'s, which carries "
                                 f"{parent}'s time stamps; declare the offset on {parent} and re-ingest it")
            if merged.get("instrument") == OBSERVATORY:
                raise ValueError(f"{name}: clock_offset_s {config.clock_offset_s!r} on an observatory: its "
                                 f"archive is fetched by scripts/fetch_observatory.py, not ingested from a "
                                 f"logger's time stamps")
        if config.rot_h != 0.0 and (self.parent_of(name) or merged.get("instrument") == OBSERVATORY):
            raise ValueError(f"{name}: rot_h {config.rot_h!r} on a derived or observatory site: a derived site's "
                             f"archive is decimated from its parent's, which carries the parent's turn; declare "
                             f"it on {self.parent_of(name) or 'the recorded site'} and re-ingest it")
        if config.rot_h_parts and (self.parent_of(name) or merged.get("instrument") == OBSERVATORY):
            raise ValueError(f"{name}: rot_h_parts on a derived or observatory site: a derived site's archive is "
                             f"made from its parent's, which carries the parent's turns; declare them on "
                             f"{self.parent_of(name) or 'the recorded site'} and re-ingest it")
        if config.rot_h_parts:
            lo, hi = _window_time(config.rot_h_parts[0][0]), _window_time(config.rot_h_parts[-1][1])
            for key, value in (("start", config.start), ("end", config.end)):
                if value is None:
                    continue
                t = _window_time(value)
                if t < lo or t > hi:
                    raise ValueError(f"{name}: {key} {value} lies outside its rot_h_parts ({lo} .. {hi}): samples "
                                     f"outside every part are left out at ingest, so the span survey.yaml gives must "
                                     f"lie inside the parts; set {key} inside them")
        if config.record_window:
            lo, hi = window_bounds(config)
            for key, value in (("start", config.start), ("end", config.end)):
                if value is None:
                    continue
                t = _window_time(value)
                if (lo is not None and t < lo) or (hi is not None and t > hi):
                    raise ValueError(f"{name}: {key} {value} lies outside its record_window {config.record_window}: "
                                     f"the span survey.yaml gives (read by the campaign's remote rule and "
                                     f"scripts/h_azimuth.py) must be the clipped span; set {key} inside the window")
        for key in ("electric_gain_ex", "electric_gain_ey"):
            if config.swap_e and getattr(config, key) != 1.0:
                raise ValueError(f"{name}: {key} {getattr(config, key)!r} with swap_e: the exchange moves the "
                                 f"inputs' stages stage for stage, and a gain on one line makes the chains differ; "
                                 f"not built")
        if config.edl_banks_swapped:
            if config.h_from is not None:
                raise ValueError(f"{name}: edl_banks_swapped with h_from {config.h_from!r}: the bank exchange gives "
                                 f"the site its own magnetometer; remove h_from")
            own_channels = [str(c).lower() for c in overrides.get("channels") or []]
            if "hz" in own_channels:
                raise ValueError(f"{name}: edl_banks_swapped and channels {own_channels} naming hz: the .BZ file "
                                 f"holds the electric bank's spare input and the fluxgate's z was not recorded; "
                                 f"declare channels: [ex, ey, hx, hy]")
        if config.h_tilt:
            if self.parent_of(name) or merged.get("instrument") == OBSERVATORY:
                raise ValueError(f"{name}: h_tilt on a derived or observatory site: a derived site's archive is made "
                                 f"from its parent's, which carries the parent's attitude; declare it on "
                                 f"{self.parent_of(name) or 'the recorded site'} and re-ingest it")
            if config.h_from is not None:
                raise ValueError(f"{name}: h_tilt with h_from {config.h_from!r}: the borrowed coils are "
                                 f"{config.h_from}'s, so declare its attitude on {config.h_from}")
            if config.rot_h_parts:
                raise ValueError(f"{name}: h_tilt with rot_h_parts: a sensor that turned during the record has no one "
                                 f"attitude; not built")
            instrument = self.instrument_of(name)
            if instrument not in H_TILT_INSTRUMENTS:
                raise ValueError(f"{name}: h_tilt on a {instrument} site: it levels a three-component fluxgate whose "
                                 f"main field fixes the attitude, built for {', '.join(H_TILT_INSTRUMENTS)}")
            if config.edl_banks_swapped:
                raise ValueError(f"{name}: h_tilt with edl_banks_swapped: the bank exchange records no hz, and the "
                                 f"turn needs hx, hy and hz")
            tilt_kept = [c.lower() for c in config.channels] if config.channels else None
            if tilt_kept is not None and not {"hx", "hy", "hz"} <= set(tilt_kept):
                raise ValueError(f"{name}: h_tilt turns hx, hy and hz together, and channels {tilt_kept} does not keep "
                                 f"all three (no hz)")
        if config.h_from is not None:
            self._check_h_from(config, merged)
        kept = [c.lower() for c in config.channels] if config.channels else None
        if config.flip_h and kept is not None:
            missing = [c for c in config.flip_h if c not in kept]
            if missing:
                raise ValueError(f"{name}: flip_h names {missing}, which channels {kept} does not keep")
        if config.rot_h != 0.0 and kept is not None and not {"hx", "hy"} <= set(kept):
            raise ValueError(f"{name}: rot_h turns hx and hy, and channels {kept} does not keep both")
        if config.rot_h_parts and kept is not None and not {"hx", "hy"} <= set(kept):
            raise ValueError(f"{name}: rot_h_parts turns hx and hy, and channels {kept} does not keep both")
        if config.swap_e and kept is not None and not {"ex", "ey"} <= set(kept):
            raise ValueError(f"{name}: swap_e exchanges ex and ey, and channels {kept} does not keep both")
        return config

    def _burst_site(self, name: str) -> SiteConfig:
        """Return a burst site's settings: its recorded site's, under its own name.

        The archive of a burst site is ingested from its recorded site's
        raw folder, so it carries that site's coils, dipoles and
        calibration, and its own entry may set only `BURST_SITE_KEYS`.
        Its `clock_offset_s` is not the recorded site's: the bursts carry
        GPS time (the stamp of each burst plus the file-version-2 second,
        `mt_workbench.phoenix.stamp_correction`), while an offset declared
        on the recorded site corrects its continuous stream, whose samples
        trail GPS by the delay of the receiver's decimation filter
        (Kalkaroo: -0.1148 s on every 150 Hz site). Copied, it would move
        the bursts off GPS time by that delay. It is 0.0 unless the burst
        site's own entry declares one.

        Args:
            name (str): The burst site.

        Returns:
            SiteConfig: The recorded site's settings with ``name``,
            ``bursts_of``, ``sample_rate``, the entry's ``remote`` and
            ``notes``, and its ``clock_offset_s`` (0.0 when not declared).

        Raises:
            ValueError: If the entry holds another key, its `sample_rate`
                is not `BURST_RATE`, it names itself, the recorded site is
                a derived or burst site itself, or its `clock_offset_s` is
                refused by `SiteConfig`.
        """
        own = self._sites.get(name) or {}
        parent = str(own["bursts_of"])
        extra = sorted(k for k in own if k not in BURST_SITE_KEYS)
        if extra:
            raise ValueError(f"{name}: {', '.join(extra)} on a burst site (bursts_of {parent}): its archive is "
                             f"ingested from {parent}'s raw folder and logger stamps, so it takes {parent}'s "
                             f"settings; set them on {parent}. A burst site's entry holds only "
                             f"{', '.join(BURST_SITE_KEYS)}")
        if parent == name:
            raise ValueError(f"{name}: bursts_of names the site itself")
        if self.parent_of(parent) or self.bursts_parent(parent):
            raise ValueError(f"{name}: bursts_of {parent}: {parent} is a derived or burst site; name the "
                             f"recorded site whose raw folder holds the bursts")
        rate = own.get("sample_rate")
        if rate is None or float(rate) != BURST_RATE:
            raise ValueError(f"{name}: a burst site (bursts_of {parent}) declares sample_rate: "
                             f"{BURST_RATE:g}, the rate of the receiver's .td_24k files; got {rate!r}")
        recorded = self.site(parent)
        settings = {f.name: getattr(recorded, f.name) for f in fields(SiteConfig)}
        settings.update(name=name, bursts_of=parent, sample_rate=BURST_RATE,
                        remote=own.get("remote"), notes=own.get("notes", recorded.notes),
                        clock_offset_s=own.get("clock_offset_s", 0.0))
        return SiteConfig(**settings)

    def _check_h_from(self, config: SiteConfig, merged: dict) -> None:
        """Refuse an `h_from` declaration the ingest cannot honour.

        Args:
            config (SiteConfig): The local site's merged settings.
            merged (dict): The merged `defaults:` and site entry.

        Raises:
            ValueError: If `h_from` names the site itself; the site is derived
                or an observatory, declares hx or hy (or no `channels:`,
                which keeps every column; allowed on an Orange Box site,
                whose own pair is replaced), `swap_h`, a `flip_h` naming
                hx or hy or a non-zero `rot_h`; the neighbour is
                derived, an observatory or `h_from` itself, declares
                channels without hx and hy, or has another sample rate.
        """
        name, other = config.name, config.h_from
        if other == name:
            raise ValueError(f"{name}: h_from names the site itself")
        if self.parent_of(name) or merged.get("instrument") == OBSERVATORY:
            raise ValueError(f"{name}: h_from on a derived or observatory site: only a recorded site "
                             f"takes hx and hy from a neighbour at ingest")
        own = [c.lower() for c in config.channels] if config.channels else None
        # an Orange Box records all five channels: the neighbour's hx and hy replace the local's at ingest
        # (`mt_workbench.ingest._drop_own_h`), so its channels may name them
        replaced = self.instrument_of(name) == "orangebox"
        if not replaced and (own is None or "hx" in own or "hy" in own):
            raise ValueError(f"{name}: h_from {other} takes hx and hy from {other}, and {name} already "
                             f"has them (channels {own if own is not None else 'unset: every column'}): "
                             f"declare channels: [ex, ey] for a site that recorded electrics only")
        if config.swap_h:
            raise ValueError(f"{name}: swap_h with h_from {other}: the borrowed coils carry {other}'s own "
                             f"swap_h, so declare it on {other}")
        borrowed = [c for c in config.flip_h or [] if c in ("hx", "hy")]
        if borrowed:
            raise ValueError(f"{name}: flip_h {borrowed} with h_from {other}: the borrowed coils carry {other}'s "
                             f"own flip_h, so declare it on {other}")
        if config.rot_h_parts:
            raise ValueError(f"{name}: rot_h_parts with h_from {other}: the borrowed coils carry {other}'s own "
                             f"turn, so declare it on {other}")
        if config.rot_h != 0.0:
            raise ValueError(f"{name}: rot_h {config.rot_h!r} with h_from {other}: the borrowed coils carry "
                             f"{other}'s own rot_h, so declare it on {other}")
        entry = self._sites.get(other) or {}
        if self.parent_of(other) or entry.get("instrument") == OBSERVATORY:
            raise ValueError(f"{name}: h_from {other}: {other} is derived or an observatory; the neighbour "
                             f"must be a recorded site whose raw files hold hx and hy")
        if entry.get("h_from"):
            raise ValueError(f"{name}: h_from {other}: {other} takes its own hx and hy from "
                             f"{entry['h_from']} (h_from); name the site that recorded them")
        neighbour = self.site(other)
        theirs = [c.lower() for c in neighbour.channels] if neighbour.channels else None
        if theirs is not None and not ("hx" in theirs and "hy" in theirs):
            raise ValueError(f"{name}: h_from {other}: {other} declares channels {theirs}, without both "
                             f"hx and hy")
        if self.sample_rate_of(other) != self.sample_rate_of(name):
            raise ValueError(f"{name}: h_from {other}: {other} is at {self.sample_rate_of(other):g} Hz and "
                             f"{name} at {self.sample_rate_of(name):g} Hz; the samples are taken one for one")
