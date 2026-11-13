# -*- coding: utf-8 -*-
"""
Start a survey.yaml from a folder of site folders and their recorders' files

For a new survey that has its raw data and paper field sheets: one subfolder
per site with LEMI-423 ``*.B423``, LEMI-424 ``YYYYMMDDhhmm.txt``, Earth
Data PR6-24 ``{station}YYMMDDhhmmss.{BX,..,EY}``, Phoenix or Orange Box
``HFM<n>-NNN.BIN`` or ``LP<n>-NNN.BIN`` files anywhere under it.

Sites are found by the rule of `mt_workbench.survey.Survey.site_dirs` (a subfolder
of data_root with any of those files anywhere under it; site name = folder
name), and each site's instrument is detected from its files
(`mt_workbench.instruments.detect_instrument`). The survey's `instrument:` is the
most common one, or the one named by `--instrument`. A site recorded on
another instrument gets its own `instrument:` and that instrument's default
`channels:` preset, since its reader uses other channel names. The facts of
LEMI-424 and EDL sites come from `mt_workbench.instruments.header_facts`: a
LEMI-424's `.inf` (serial, firmware) and its first data line through mt-io
(GPS position, elevation; 1 Hz), and an EDL's recorder.ini (the rate, or the
file spacing) without a position. Their span runs from the file names to the
end of the last file (`mt_workbench.instruments.span`). For each LEMI-423 site the
first B423 file (by its file-name epoch) is read through mt-io
(`mt_io.lemi.lemi423`): `Read_Lemi_Header` gives the logger's serial number
and firmware and its GPS latitude, longitude and elevation at deployment,
and `fast_sample_rate` gives the sample rate from a bounded read of the first
4096 records. mt-io's `Read_Lemi_Data.read_summary` scans the whole file (a
first file can run to more than 100 MB); the bounded read takes milliseconds.
The recorded span is that of the file-name epochs, first to last plus the
median spacing, as the GUI's window bar reads it.

The name of a new survey is checked before any folder is read
(`mt_workbench.survey.check_survey_name`: 30 characters at most, of letters,
digits, _ and -). The script writes surveys/<name>/survey.yaml (or --out) with the survey's
name, instrument, sample_rate (the most common across sites; a warning names
any site that differs), data_root, workspace, timezone and `generated_by:
scripts/new_survey.py`; a `defaults:` block and a `processing:` block; and a
`sites:` block with one entry per folder: latitude, longitude, elevation,
serial, firmware, start and end (UTC), and a note that the dipole lengths and
azimuths are the defaults. The declination keys (declination,
declination_model, declination_epoch) are left unset unless the site table
gives them; scripts/declination.py fills them from the IGRF, and the
summary's last line says so. Dipole lengths and azimuths are left out of the
site entries, so the defaults apply until they are set from the field sheet,
on the GUI's Metadata tab or with --site-table. The site table is a CSV or
XLSX with a `site` column plus any of `mt_workbench.survey.SITE_TABLE_COLUMNS`;
its values are merged over the header's for
the sites it names. The header's GPS fix takes precedence for latitude,
longitude and elevation (the table fills them only where the header has
none), and every disagreement is printed. The columns of the field-sheet
survey CSV (SiteName, ExDipole, ExAzimuth, ..., TimeZone) are read as
well. The coil response file (default: surveys/burra/sensors/l120n.rsp, the
LEMI-120 one) is copied into the survey folder's sensors/.

--channels declares which of the recorder's columns had a sensor attached,
which is survey logistics that the files cannot tell. It is a preset label
from `mt_workbench.survey.CHANNEL_PRESETS` for the instrument ("Ex Ey Bx By", the
LEMI-423 default, with the Bz column an open input; "Ex Ey Bx By Bz"; "Bx By
(magnetics only)" for a dedicated remote; "Bx By Bz") or a comma list of the
reader's names ("hx,hy"). It is written as `defaults: channels:`, which
ingest applies, dropping every other column from the archive; a site that
differs gets its own `channels:` on the GUI's Metadata tab. The summary
prints, per site, the columns mt-io reads from the first file (the B423
record's Bx By Bz Ex Ey, stored as hx hy hz ex ey) next to the declared set,
and warns when a declared channel is not among them.

For an Orange Box site the facts are the box named by the logger report
(``HFM<n>-RPT.TXT``, "High Frequency Magnetometer Number <n>", box 2 for
number 0, written as serial "hfm2"), the span from the first header to the
last end stamp read on the logger clock's zone (--clock-timezone, default
UTC), the archive's 10 Hz rate and no position. An Orange Box survey's
`defaults:` gets `clock_timezone:` and the two full scales as comments to
set (`electric_full_scale_uv`, `magnetic_full_scale_nt`: ingest refuses a
site without them); each site's `clock_drift_s` comes from the field sheet.

For a LEMI-424 survey the `defaults:` block also gets `e_sign: -1.0` with a
one-line comment: the logger records E1 and E2 with the opposite sign to the
x-north, y-east frame, and ingest multiplies them by it
(`mt_workbench.survey.SiteConfig.e_sign`).

--electric-gain names the extra gain of an Earth Data PR6-24 site's electric
chain between the dipoles and the recorded values, beyond what the reader
already models (the x10 terminal box). It is hardwired at the field terminal
junction box and declared from the field notes when the PR6-24's own configs
were not kept (e.g. 10). It is written as `defaults:
electric_gain:`, which ingest folds into a filter of that gain on every EDL
site's ex and ey (`mt_workbench.instruments.read_run`). Without the option no key
is written (1.0, no filter). A site's `config/recorder.ini` may carry its
own `channel_n_high_gain` flags (read by
`mt_workbench.instruments.recorder_ini_high_gain`, since mt-io's
`read_recorder_ini` keeps one boolean for all six); the summary prints them
against the declared gain for information only. The option is an error when
no site is an EDL.

The workspace, which holds the MTH5 archives, transfer functions, figures and
the basemap, is `<data_root>/work` unless --workspace names another folder.
It sits beside the raw data rather than in the repo because a 100-site
survey's archives run to hundreds of GB. The script writes the key; the
folder is created by the first script that writes into it.

A survey.yaml that exists holds hand edits and is never written again from
the folders. Run on it a second time (a re-run, with the same data folder
and name), the script adds an entry for each site folder that has none,
through `mt_workbench.survey_file.edit`: every other line of the file stays,
and the file as it was is kept as survey.yaml.previous. The new entries are
read as at the first run, against the file's own instrument and sample
rate. The head of the file is not changed: a head argument given with
another value than the file's is named as ignored. With --site-table, the
rows of sites that already have an entry are applied to those entries in
place (a value equal to `defaults:` is not written, a position the entry
holds is kept), and the sites and values changed are printed. To start
again, delete the survey.yaml by hand; --force is refused. A second
deployment at a station goes in a site folder of its own (SA106_2), never
into an existing one, and becomes a site like any other.

When legacy EDIs exist for the survey (lemimt, a contractor's), run

    python scripts/match_reference_edis.py <edi_dir> <survey.yaml>

afterwards to write reference_edis.yaml, which the View EDIs tab overlays.

Usage (the same command again adds the site folders that have no entry):
    python scripts/new_survey.py <data_root> --name NAME [--instrument auto]
        [--channels "Ex Ey Bx By"] [--electric-gain 10]
        [--timezone Australia/Adelaide] [--out PATH]
        [--workspace DIR] [--calibration FILE] [--site-table CSV_OR_XLSX]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path
from textwrap import indent

import numpy as np
import pandas as pd
import yaml
from mt_io.lemi.lemi423 import Read_Lemi_Data, Read_Lemi_Header

from mt_workbench import survey_file
from mt_workbench.ingest import select_files
from mt_workbench.instruments import INSTRUMENTS, header_facts, record_files, span
from mt_workbench.survey import (
    CHANNEL_PRESETS, Survey, channels_from_label, check_survey_name, default_preset, merge_table_row, preset_label,
    read_site_table,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
DEFAULT_TIMEZONE = "Australia/Adelaide"
FORCE_GONE = ("--force is gone: a re-run only adds the site folders that have no entry. To start again, delete "
              "{out} by hand and run this command again.")
DEFAULT_FILE_SECONDS = 5400  # a B423 file's nominal span, for a site with one file
DEFAULTS_NOTE = "dipole lengths and azimuths from defaults - set them from the field sheet"
# the LEMI-423's documented rates (mt_io.lemi.lemi_collection.LEMICollection's docstring).
# There is no 1 Hz mode: a file with one record per second (tick always 0)
# is an instrument fault and is reported as measured, with a warning
KNOWN_SAMPLE_RATES = (4000.0, 2000.0, 1000.0, 500.0, 250.0)
SAMPLE_RATE_RECORDS = 4096  # bounded read for the rate scan: several seconds even at 250 Hz
# how mt-io's LEMI423Reader.read names the B423 record's data columns (its `mapping`)
READER_CHANNELS = {"Bx": "hx", "By": "hy", "Bz": "hz", "Ex": "ex", "Ey": "ey"}
DIPOLE_KEYS = ("dipole_length_ex", "dipole_length_ey", "azimuth_ex", "azimuth_ey")
# the order a site entry's keys are written in (instrument and channels only
# for a site whose recorder is not the survey's)
KEY_ORDER = ("instrument", "channels", "sensor_type", "electric_gain", *DIPOLE_KEYS, "latitude", "longitude",
             "elevation", "declination", "declination_model", "declination_epoch", "remote", "timing", "serial", "firmware", "start", "end", "notes")
# an EDL site's magnetic sensors from its rate (`sensor_type`, mt_workbench.instruments.EDL_SENSORS): the
# UoA practice is induction coils at 500 or 1000 Hz and Bartington fluxgates at 10 Hz (the field
# notes "Usual settings when we deploy Induction coils using the Earth Data Recorder")
EDL_COIL_MIN_RATE = 100.0


def edl_sensor_for(rate) -> str:
    """Return an EDL site's sensor_type from its rate.

    Returns:
        str: "lemi120" (induction coils) at `EDL_COIL_MIN_RATE` Hz and above,
        otherwise "bartington" (fluxgates).
    """
    return "lemi120" if rate and float(rate) >= EDL_COIL_MIN_RATE else "bartington"
ISO = "%Y-%m-%dT%H:%M:%SZ"

HEAD = """\
name: {name}
instrument: {instrument}
sample_rate: {sample_rate}
data_root: {data_root}
# archives, transfer functions and figures: beside the raw data by default
workspace: {workspace}
# local time of the field area (IANA name), for display only: every
# timestamp in the YAML, the archives and the scripts is UTC
timezone: {timezone}
# written by this script from the raw files' headers; run again, it adds the
# site folders that have no entry and leaves every other line
generated_by: scripts/new_survey.py
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  # LEMI-120 coil response (LEMI-423 sites, and EDL sites with sensor_type lemi120);
  # a relative path resolves against this folder first
  calibration_fn: {calibration_fn}
  # LEMI-423 sites: magnetics correction to the lemimt convention, pT to nT and polarity
  h_scale: -1000.0
{e_sign}  # how to read a 180/270 deg dipole azimuth on the field sheet. true: the pair
  # was wired reversed, so its data are sign-flipped at ingest. false: the
  # azimuth only records the layout direction and the logger's terminals fix
  # polarity, so nothing is flipped. Check the impedance
  # phase quadrants after the first run: a wrong choice puts one mode 180 deg out.
  flip_reversed_dipoles: true
  # the columns that had a sensor attached (--channels, mt_workbench.survey.CHANNEL_PRESETS),
  # in the survey instrument's names; ingest drops the rest, e.g. the B423 Bz column,
  # an open input with no hz coil. A site on another instrument has its own channels:
  channels: {channels}
{edl_sensor}{edl_gain}# lemimt-style even log-period band layout (see mt_workbench.bands.build_band_scheme)
processing:
  min_period: 0.005
  max_period: 5000.0
  periods_per_decade: 10.0
  # keep bands clear of mains and its first in-range harmonic
  notch_frequencies: [50.0, 150.0]
"""


# the 150 Hz shortest period whose band edges fall on the 24 kHz burst layout's (4**(22/6)/6000 s):
# scripts/merge_tensor_bands.py stitches the two products only when they share band edges
PHOENIX_MIN_PERIOD = 4 ** (22 / 6) / 6000


def phoenix_defaults(head: str) -> str:
    """Return the survey.yaml head with the defaults a Phoenix survey needs.

    The receiver metadata (empower_recmeta.json, as mt-io reads it) holds
    each dipole's length, and a non-zero `dipole_length_ex/ey` would
    override it at every site, so the defaults are 0.0. The receivers' and
    coils' calibration JSON files come from `calibration_dir`, and the
    shortest period is `PHOENIX_MIN_PERIOD`, so that a 150 Hz product can be
    stitched to its bursts' (scripts/merge_tensor_bands.py).

    Args:
        head (str): The formatted `HEAD`.

    Returns:
        str: The head with those three settings.
    """
    old = "  dipole_length_ex: 50.0\n  dipole_length_ey: 50.0\n"
    new = ("  # Phoenix: 0.0 takes each recording's dipole lengths from empower_recmeta.json (as mt-io\n"
           "  # reads it); a site's own non-zero value (the taped length) overrides it\n"
           "  dipole_length_ex: 0.0\n  dipole_length_ey: 0.0\n"
           "  # Phoenix: the folder of the receivers' <receiver>_*.rxcal.json and the coils'\n"
           "  # <serial>_*.scal.json files; a relative path resolves against this folder first\n"
           "  calibration_dir: sensors\n")
    if old not in head:
        raise ValueError("the defaults block has changed: update phoenix_defaults")
    head = head.replace(old, new)
    period = "  min_period: 0.005\n"
    if period not in head:
        raise ValueError("the processing block has changed: update phoenix_defaults")
    return head.replace(period, f"  # 4**(22/6)/6000: the 150 Hz band edges fall on the 24 kHz bursts' (merge_tensor_bands.py)\n"
                                f"  min_period: {PHOENIX_MIN_PERIOD!r}\n")


def orangebox_defaults(head: str, clock_timezone: str) -> str:
    """Return the survey.yaml head with the defaults an Orange Box survey needs.

    The logger clock's zone is written as `clock_timezone`; the two full
    scales are written as comments to set, since ingest refuses an Orange
    Box site without them and the files do not tell them.

    Args:
        head (str): The formatted `HEAD`.
        clock_timezone (str): The --clock-timezone value.

    Returns:
        str: The head with those settings after `channels:`.
    """
    anchor = "  channels: "
    at = head.index(anchor)
    at = head.index("\n", at) + 1
    block = ("  # Orange Box chain (docs/upstream_issues.md 13, 14): no default, ingest refuses a site without\n"
             "  # them. Electric: 25000 uV for the +/-2.5 V boxes before July 2010, 100000 for the +/-10 V ones;\n"
             "  # magnetic: 70000 or 100000 nT, the Bartington sensor's\n"
             "  # electric_full_scale_uv: 25000.0\n"
             "  # magnetic_full_scale_nt: 70000.0\n"
             "  # the zone the loggers' real-time clocks ran on (their stamps are read as UTC with it);\n"
             "  # each site's clock_drift_s (GPS minus logger at recovery) comes from the field sheet\n"
             f"  clock_timezone: {scalar(clock_timezone)}\n")
    return head[:at] + block + head[at:]


def scalar(value) -> str:
    """Format one YAML scalar as safe_dump writes it, quoted when it would read back as another type."""
    return yaml.safe_dump({"k": value}, allow_unicode=True, width=10**9).split(":", 1)[1].strip()


def fast_sample_rate(path: Path, n_records: int = SAMPLE_RATE_RECORDS) -> float | None:
    """Derive a B423 file's sample rate from a bounded read.

    Skips the 1024-byte header and reads the first `n_records` of the 30-byte
    records documented by `mt_io.lemi.lemi423.Read_Lemi_Data.binary_format`
    (`time`: whole seconds; `tick`: milliseconds within the second, resetting
    to 0 when `time` ticks over). Counting records by their `time` value gives
    records per whole second. The last `time` value in the read is dropped,
    as `n_records` may cut it short, and the derived rate is the largest
    count left, since a partial second at the start can only under-count.
    The rate is snapped to the nearest of the LEMI-423's documented rates
    (`KNOWN_SAMPLE_RATES`). When it is more than 1 % off that rate (dropped
    samples, or an unknown rate) a warning is printed and the measured rate
    is returned.

    Args:
        path (Path): B423 file.
        n_records (int): Number of records to read.

    Returns:
        float | None: The sample rate in Hz, or None when the file holds no
        complete record.
    """
    record = Read_Lemi_Data.binary_format
    with open(path, "rb") as f:
        f.seek(1024)
        raw = f.read(n_records * record.itemsize)
    raw = raw[: (len(raw) // record.itemsize) * record.itemsize]
    if not raw:
        return None
    arr = np.frombuffer(raw, dtype=record)
    counts = Counter(arr["time"].tolist())
    seconds = sorted(counts)
    complete = seconds[:-1] if len(seconds) > 1 else seconds
    derived = max(counts[s] for s in complete)
    nearest = min(KNOWN_SAMPLE_RATES, key=lambda rate: abs(rate - derived))
    off = abs(derived - nearest) / nearest
    if off > 0.01:
        # an unknown rate: report what was measured rather than the nearest
        # known value (a file at 1 record/s would otherwise snap to 250 Hz)
        print(f"  WARNING {path.name}: derived sample rate {derived} records/s is {off:.1%} off "
              f"the nearest LEMI-423 rate ({nearest:g} Hz); kept as measured: not a LEMI-423 rate, an instrument fault or dropped samples")
        return float(derived)
    return nearest


def file_columns(path: Path) -> list[str]:
    """Return the channels mt-io reads from a B423 file.

    These are the records' data columns (`Read_Lemi_Data.binary_format`) as
    `LEMI423Reader.read` names them.

    Args:
        path (Path): B423 file.

    Returns:
        list[str]: Channel names, or [] when the file holds no complete
        record.
    """
    record = Read_Lemi_Data.binary_format
    if path.stat().st_size < 1024 + record.itemsize:
        return []
    return [READER_CHANNELS[name] for name in record.names if name in READER_CHANNELS]


def read_other_site(site_dir: Path, instrument: str, clock_timezone: str = "UTC") -> dict:
    """Read the facts of a LEMI-424, EDL, Phoenix or Orange Box site.

    Args:
        site_dir (Path): The site's folder.
        instrument (str): "lemi424", "edl", "phoenix" or "orangebox".
        clock_timezone (str): Orange Box only: the zone its logger clock
            ran on, with which the span is read as UTC.

    Returns:
        dict: files, start, end, sample_rate, problem and columns, updated
        with `mt_workbench.instruments.header_facts`. An unreadable first file is
        recorded in "problem".
    """
    files = record_files(site_dir, instrument)
    start, end, n = span(site_dir, instrument, files, clock_timezone=clock_timezone)
    facts = {"files": n, "start": start, "end": end, "sample_rate": None, "problem": None, "columns": None}
    try:
        facts.update(header_facts(site_dir, instrument, files))
    except Exception as exc:  # an unreadable first file: the site is still listed
        facts["problem"] = f"first {INSTRUMENTS[instrument]['label']} file unreadable ({files[0].name}: {exc})"
    return facts


def read_site(site_dir: Path, instrument: str = "lemi423", clock_timezone: str = "UTC") -> dict:
    """Read the facts of one site's files.

    For a LEMI-423 site: the header and a bounded scan of the first B423
    file, and the span of the file names. Other instruments go to
    `read_other_site`.

    Args:
        site_dir (Path): The site's folder.
        instrument (str): The site's instrument.
        clock_timezone (str): Orange Box only (`read_other_site`).

    Returns:
        dict: files, start, end, sample_rate, problem and columns, plus
        serial, firmware and the GPS position when the header has them.
    """
    if instrument != "lemi423":
        return read_other_site(site_dir, instrument, clock_timezone)
    files = select_files(site_dir)
    epochs = np.array([int(f.stem) for f in files], dtype="int64")
    spacing = int(np.median(np.diff(epochs))) if epochs.size > 1 else DEFAULT_FILE_SECONDS
    start = pd.Timestamp(int(epochs[0]), unit="s", tz="UTC")
    end = pd.Timestamp(int(epochs[-1]) + spacing, unit="s", tz="UTC")
    facts = {"files": len(files), "start": start, "end": end, "sample_rate": None, "problem": None,
             "columns": None}
    try:
        header = Read_Lemi_Header(files[0]).read()
        facts["sample_rate"] = fast_sample_rate(files[0])
        facts["columns"] = file_columns(files[0])
    except Exception as exc:  # a corrupt first file: the site is still listed
        facts["problem"] = f"first B423 header unreadable ({files[0].name}: {exc})"
        return facts
    facts["serial"] = None if header["instrument_number"] is None else str(header["instrument_number"])
    facts["firmware"] = header["firmware_version"]
    if header["latitude"] == 0 and header["longitude"] == 0:
        facts["problem"] = "no GPS fix in the first B423 header"
    else:
        facts["latitude"] = round(float(header["latitude"]), 6)
        facts["longitude"] = round(float(header["longitude"]), 6)
        facts["elevation"] = float(header["elevation"])
    return facts


def site_entry(facts: dict) -> dict:
    """Build a site's survey.yaml entry from its facts, with the defaults note."""
    entry = {key: facts[key] for key in ("latitude", "longitude", "elevation", "serial", "firmware")
             if facts.get(key) is not None}
    entry["start"] = facts["start"].strftime(ISO)
    entry["end"] = facts["end"].strftime(ISO)
    entry["notes"] = "; ".join(n for n in (DEFAULTS_NOTE, facts["problem"]) if n)
    return entry


def table_timezone(path: Path) -> str | None:
    """Return the time zone a site table names.

    The field-sheet survey CSV has a TimeZone column.

    Args:
        path (Path): CSV or XLSX site table.

    Returns:
        str | None: The single IANA zone the table names, or None when the
        column is absent, names several zones or an invalid one.
    """
    import pandas as pd

    df = pd.read_excel(path, dtype=object) if path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(path, dtype=object)
    cols = {str(c).strip().lstrip("﻿").lower(): c for c in df.columns}
    if "timezone" not in cols:
        return None
    zones = sorted({str(z).strip() for z in df[cols["timezone"]].dropna() if str(z).strip()})
    if len(zones) != 1:
        if zones:
            print(f"  WARNING site table names {len(zones)} time zones {zones}: not used")
        return None
    try:
        pd.Timestamp.now(tz=zones[0])
    except Exception:
        print(f"  WARNING site table time zone {zones[0]!r} is not an IANA name: not used")
        return None
    return zones[0]


def merge_site_table(sites: dict, path: Path, existing: dict | None = None) -> dict:
    """Merge a site table over the values read from the files, for the sites it names.

    A position or elevation a site already holds (the header's GPS fix, or
    the value in its survey.yaml entry) is kept; the table fills them only
    where the site has none. Disagreements, unmatched sites and ignored
    columns are printed.

    Args:
        sites (dict): The entries being written, updated in place.
        path (Path): CSV or XLSX site table.
        existing (dict | None): On a re-run, {site: entry} of the sites that
            already have an entry in survey.yaml.

    Returns:
        dict: {site: {key: value}} to set on the sites of `existing` that
        the table names; empty at a first run.
    """
    existing = existing or {}
    rows, ignored = read_site_table(path)
    matched = [s for s in rows if s in sites or s in existing]
    disagreements, changes = [], {}
    for site in matched:
        if site in existing:
            entry = existing[site] or {}
            changes[site], disagree = merge_table_row(entry, rows[site])
            disagreements += [f"{site} {key}: table {rows[site][key]} vs survey.yaml {entry[key]} -> survey.yaml kept"
                              for key in disagree]
            continue
        entry = sites[site]
        # the header's GPS fix takes precedence for position and elevation: a
        # table is typed or derived by hand (elevations exactly 1000 m low come
        # from a mis-read of the header's glued four-digit `%Alt` line). The
        # table fills them only where the header has no fix; every
        # disagreement is printed for a check against the sheet.
        values, disagree = merge_table_row(entry, rows[site])
        disagreements += [f"{site} {key}: table {rows[site][key]} vs header {entry[key]} -> header kept"
                          for key in disagree]
        entry.update(values)
        if all(k in entry for k in DIPOLE_KEYS) and "notes" not in rows[site]:
            entry["notes"] = entry["notes"].replace(DEFAULTS_NOTE, "").lstrip("; ")
            if not entry["notes"]:
                del entry["notes"]
        sites[site] = {k: entry[k] for k in KEY_ORDER if k in entry}
    print(f"site table {path.name}: {len(matched)} of {len(rows)} sites matched")
    for line in disagreements:
        print(f"  WARNING {line}")
    missing = sorted(set(rows) - set(sites) - set(existing))
    if missing:
        print(f"  WARNING not a site folder: {', '.join(missing)}")
    if ignored:
        print(f"  WARNING ignored columns: {', '.join(ignored)}")
    return changes


def build_entries(facts: dict, recorder: dict, instrument: str, sample_rate: float) -> tuple[dict, dict]:
    """Build the survey.yaml entries of sites from the facts of their files.

    A site recorded on another instrument than the survey's gets its own
    `instrument:` and that instrument's default `channels:` (and
    `sensor_type:` for an EDL). A site of the survey's instrument at
    another rate than the survey's gets a note.

    Args:
        facts (dict): {site: facts}, as `read_site` returns them.
        recorder (dict): {site: instrument}, as detected from the folders.
        instrument (str): The survey's instrument.
        sample_rate (float): The survey's sample rate in Hz.

    Returns:
        tuple[dict, dict]: The entries, and {site: channels} of the sites
        recorded on another instrument.
    """
    own = {site: channels_from_label(default_preset(inst), inst)
           for site, inst in recorder.items() if inst != instrument}
    sites = {site: site_entry(f) for site, f in facts.items()}
    for site, site_channels in own.items():
        entry = dict(sites[site], instrument=recorder[site], channels=site_channels)
        if recorder[site] == "edl":  # an EDL site in another recorder's survey: its own sensors
            entry["sensor_type"] = edl_sensor_for(facts[site]["sample_rate"])
        sites[site] = {k: entry[k] for k in KEY_ORDER if k in entry}
    for site, f in facts.items():
        # a site of the survey's instrument not at the survey rate gets a note
        # in its entry, shown in the Metadata table, as well as a console
        # warning (another recorder has its own rate)
        if f["sample_rate"] and f["sample_rate"] != sample_rate and site not in own:
            known = instrument != "lemi423" or f["sample_rate"] in KNOWN_SAMPLE_RATES
            fault = "" if known else " - not a LEMI-423 rate: instrument fault, exclude from processing"
            note = f"recorded at {f['sample_rate']:g} Hz, the survey is {sample_rate:g} Hz{fault}"
            entry = sites[site]
            entry["notes"] = "; ".join(t for t in (entry.get("notes", ""), note) if t)
            sites[site] = {k: entry[k] for k in KEY_ORDER if k in entry}
    return sites, own


def print_sites(sites: dict, facts: dict, recorder: dict, own: dict, channels: list, sample_rate: float) -> None:
    """Print one line per site read (serial, position, span, rate, recorder, columns) and its warnings.

    Args:
        sites (dict): The entries, as `build_entries` returns them.
        facts (dict): {site: facts}, as `read_site` returns them.
        recorder (dict): {site: instrument}.
        own (dict): {site: channels} of the sites recorded on another
            instrument than the survey's.
        channels (list): The survey's declared channels.
        sample_rate (float): The survey's sample rate in Hz.
    """
    for site, f in facts.items():
        entry = sites[site]
        declared = own.get(site, channels)
        where = (f"{entry['latitude']:.6f} {entry['longitude']:.6f} {entry.get('elevation', float('nan')):.1f} m"
                 if "latitude" in entry else "no position")
        hours = (f["end"] - f["start"]).total_seconds() / 3600.0
        rate = f"{f['sample_rate']:g} Hz" if f["sample_rate"] else "rate unknown"
        columns = "unknown" if f["columns"] is None else " ".join(f["columns"]) or "none"
        print(f"  {site:<12} serial {entry.get('serial', '-'):>5}  firmware {entry.get('firmware', '-')}  "
              f"{where}  {entry['start']} to {entry['end']} ({hours:.1f} h, {f['files']} files)  {rate}  "
              f"{recorder[site]}  columns {columns}, declared {' '.join(declared)}")
        if f["problem"]:
            print(f"  WARNING {site}: {f['problem']}")
        missing = [c for c in declared if f["columns"] is not None and c not in f["columns"]]
        if missing:
            print(f"  WARNING {site}: declared channel(s) {' '.join(missing)} not among the first file's "
                  f"columns ({columns}): ingest has nothing to keep for them")
        if f["sample_rate"] and f["sample_rate"] != sample_rate and site not in own:
            print(f"  WARNING {site}: recorded at {f['sample_rate']:g} Hz, the survey says {sample_rate:g} Hz")


def print_skipped(data_root: Path, found: dict, workspace: Path) -> None:
    """Print the folders under data_root that are not sites: no file of a recorder mt-workbench reads.

    The workspace is left out when it lies under data_root, as it does by
    default.
    """
    skipped = sorted(d.name for d in data_root.iterdir()
                     if d.is_dir() and d.name not in found and d.resolve() != workspace)
    if skipped:
        print(f"skipped {len(skipped)} folder(s) with no {', '.join(spec['label'] for spec in INSTRUMENTS.values())} "
              f"files (not a recorder mt-workbench reads, or no data): {', '.join(skipped)}")


def ignored_arguments(args, config: dict) -> list[str]:
    """Return one line per head argument given on a re-run whose value differs from the file's.

    A re-run does not change the head of survey.yaml, so such an argument
    has no effect and is named. An argument that was not given, or that
    equals the file's value, has no line.

    Args:
        args (argparse.Namespace): The parsed command line; a head argument
            that was not given is None.
        config (dict): The parsed survey.yaml.

    Returns:
        list[str]: The lines, each starting "ignored on a re-run: ".
    """
    defaults = config.get("defaults") or {}
    instrument = config.get("instrument", "lemi423")
    asked = []  # (the argument as typed, its value, the key of survey.yaml, True for a key of defaults:)
    if args.instrument not in (None, "auto"):
        asked.append((f"--instrument {args.instrument}", args.instrument, "instrument", False))
    if args.channels is not None:
        asked.append((f"--channels {args.channels}", channels_from_label(args.channels, instrument), "channels",
                      True))
    if args.electric_gain is not None:
        asked.append((f"--electric-gain {args.electric_gain:g}", args.electric_gain, "electric_gain", True))
    if args.timezone is not None:
        asked.append((f"--timezone {args.timezone}", args.timezone, "timezone", False))
    if args.clock_timezone is not None:
        asked.append((f"--clock-timezone {args.clock_timezone}", args.clock_timezone, "clock_timezone", True))
    if args.workspace is not None:
        asked.append((f"--workspace {args.workspace}", Path(args.workspace).resolve().as_posix(), "workspace", False))
    if args.calibration is not None:
        asked.append((f"--calibration {args.calibration}", f"sensors/{Path(args.calibration).name}",
                      "calibration_fn", True))
    lines = []
    for typed, value, key, in_defaults in asked:
        held = (defaults if in_defaults else config).get(key)
        if key == "workspace" and held is not None:
            held = Path(str(held)).resolve().as_posix()
        if survey_file.same(value, held):
            continue
        shown = "[" + ", ".join(str(item) for item in held) + "]" if isinstance(held, list) else held
        if held is None:
            kept = f"has no {key} in defaults:" if in_defaults else f"has no {key}: line"
        else:
            kept = f"keeps {shown} in defaults:" if in_defaults else f"keeps {key}: {shown}"
        lines.append(f"ignored on a re-run: {typed} (survey.yaml {kept})")
    return lines


def add_sites(args, data_root: Path, out: Path) -> int:
    """Add an entry for each site folder that has none to a survey.yaml that exists.

    The new entries are built against the file's own instrument, sample
    rate and `defaults:`. The head of the file is not changed, and a head
    argument given with another value is printed as ignored. With
    --site-table, the rows of sites that already have an entry are applied
    to those entries in place. One `mt_workbench.survey_file.edit` writes
    the new entries and those changes, and keeps the file as it was in
    survey.yaml.previous.

    Args:
        args (argparse.Namespace): The parsed command line.
        data_root (Path): The data folder given, resolved.
        out (Path): The survey.yaml, which exists.

    Returns:
        int: 0 done or nothing to add, 1 no site folder found, 2 refused.
    """
    try:
        config = yaml.safe_load(out.read_bytes().decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        print(f"ERROR {out} does not read as YAML ({exc}): fix it by hand first")
        return 2
    entries = (config.get("sites") or {}) if isinstance(config, dict) else None
    if not isinstance(entries, dict) or not config.get("name") or not config.get("data_root"):
        print(f"ERROR {out} is not a survey.yaml with a name, a data_root and a sites: block of entries: fix it "
              f"by hand, or give another --out")
        return 2
    held_root = Path(str(config["data_root"])).resolve()
    if held_root != data_root:
        print(f"ERROR survey.yaml reads its sites from {held_root}; give that folder, or change data_root by hand "
              f"({out})")
        return 2
    if str(config["name"]) != args.name:
        print(f"ERROR {out} is the survey {str(config['name'])!r}, not {args.name!r}: give --name {config['name']}, "
              f"or another --out for a new survey")
        return 2
    try:
        survey = Survey(config, out.parent)
    except ValueError as exc:
        print(f"ERROR {out}: {exc}")
        return 2
    for line in ignored_arguments(args, config):
        print(line)
    found = survey.site_dirs()
    if not found:
        print(f"ERROR no site folder with {', '.join(spec['label'] for spec in INSTRUMENTS.values())} "
              f"files under {data_root}")
        return 1
    print_skipped(data_root, found, survey.workspace.resolve())
    names = {str(name) for name in entries}
    new = {site: folder for site, folder in found.items() if site not in names}
    defaults = survey.defaults
    channels = defaults.get("channels") or channels_from_label(default_preset(survey.instrument), survey.instrument)
    recorder = {site: survey.instrument_of(site) for site in new}
    clock_timezone = str(defaults.get("clock_timezone") or "UTC")
    facts = {site: read_site(folder, recorder[site], clock_timezone) for site, folder in new.items()}
    sites, own = build_entries(facts, recorder, survey.instrument, survey.sample_rate)
    asked = {}
    if args.site_table:
        asked = merge_site_table(sites, Path(args.site_table), {str(name): entry for name, entry in entries.items()})
    try:
        result = survey_file.edit(out, add=sites, sites=asked)
    except survey_file.SurveyFileRefused as exc:
        print(f"ERROR {exc}")
        return 2

    added, changed = list(result.made["add"]), list(result.made["sites"])
    left = f"left as they are: {len(entries) - len(changed)} site(s) with an entry"
    print_sites(sites, facts, recorder, own, channels, survey.sample_rate)
    print(f"added {len(added)} site(s): {', '.join(added)}; {left}" if added else
          "nothing to add: every site folder has an entry")
    if changed:
        print(f"changed {len(changed)} site(s) from the site table:")
        for line in result.summary:
            if line.startswith(tuple(f"{site}: " for site in changed)):
                print(f"  {line}")
        if not added:
            print(left)
    elif asked:
        print(f"site table {Path(args.site_table).name}: the {len(asked)} site(s) with an entry that it names "
              f"already read as the table")
    no_folder = [str(name) for name in entries if str(name) not in found]
    if no_folder:
        print(f"entries with no folder under {data_root}: {len(no_folder)} (derived, burst or observatory sites, "
              f"or a folder that was not found): {', '.join(no_folder[:10])}{' ...' if len(no_folder) > 10 else ''}")
    if result.written:
        print(f"wrote {out}; the file as it was: {result.previous}")
    if added:
        print("next: set the dipole lengths and azimuths of the new site(s) that differ from the usual values "
              "(the GUI's Metadata tab, or --site-table)")
    return 0


def main(argv=None) -> int:
    """Write a new survey.yaml, or add the site folders with no entry to one that exists.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, also when a re-run finds nothing to add; 1 when
        no site folder is found; 2 when refused: the name of a new survey,
        --force, a re-run whose data folder or name differs from the
        file's, an edit the survey.yaml cannot take, or a bad argument.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_root", help="the folder holding one subfolder per site")
    parser.add_argument("--name", required=True, help="survey name (also the default folder under surveys/)")
    parser.add_argument("--instrument", choices=["auto", *INSTRUMENTS],
                        help="the survey's instrument (default auto: the most common among the sites' folders)")
    parser.add_argument("--channels", help="the columns that had a sensor, for the survey's instrument: a "
                        "preset label (LEMI-423: " + "; ".join(CHANNEL_PRESETS["lemi423"]) + ") or a comma "
                        "list such as hx,hy; default the instrument's first preset")
    parser.add_argument("--electric-gain", type=float, help="extra gain of an EDL (PR6-24) site's electric "
                        "chain beyond the reader's own (the x10 terminal box), declared from the field "
                        "notes, e.g. 10; written as defaults: electric_gain")
    parser.add_argument("--timezone", help=f"IANA name, for display only (default {DEFAULT_TIMEZONE}, or the "
                        "site table's)")
    parser.add_argument("--clock-timezone", help="Orange Box sites: the IANA name of the zone the loggers' "
                        "real-time clocks ran on, with which their stamps are read as UTC (default UTC)")
    parser.add_argument("--out", help="survey.yaml to write, or to add sites to when it exists (default "
                        "surveys/<name>/survey.yaml)")
    parser.add_argument("--workspace", help="archives, TFs and figures (default <data_root>/work)")
    parser.add_argument("--calibration", help="coil response file (default the LEMI-120 table "
                        "surveys/burra/sensors/l120n.rsp)")
    parser.add_argument("--site-table", help="CSV or XLSX: a site column plus any editable column; on a re-run "
                        "its rows also change the sites that already have an entry")
    parser.add_argument("--force", action="store_true", help="refused: a re-run only adds the site folders that "
                        "have no entry; to start again, delete the survey.yaml by hand")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root).resolve()
    out = Path(args.out) if args.out else REPO / "surveys" / args.name / "survey.yaml"
    out = out.resolve()
    if args.force:
        print("ERROR " + FORCE_GONE.format(out=out))
        return 2
    for zone, what, example in ((args.timezone, "timezone", DEFAULT_TIMEZONE),
                                (args.clock_timezone, "clock timezone", "Australia/Perth")):
        try:
            pd.Timestamp.now(tz=zone)  # None reads as no zone
        except Exception:
            parser.error(f"unknown {what} {zone!r} (an IANA name, e.g. {example})")
    if not data_root.is_dir():
        parser.error(f"no such folder: {data_root}")
    calibration = Path(args.calibration) if args.calibration else DEFAULT_CALIBRATION
    if not calibration.is_file():
        parser.error(f"no such coil response file: {calibration}")
    if out.exists():
        return add_sites(args, data_root, out)

    # a new survey: its name is checked before any folder is read, and a head argument not given takes its default
    try:
        check_survey_name(args.name)
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 2
    workspace = Path(args.workspace).resolve() if args.workspace else data_root / "work"
    timezone = args.timezone or DEFAULT_TIMEZONE
    clock_timezone = args.clock_timezone or "UTC"
    prefer = "lemi423" if args.instrument in (None, "auto") else args.instrument
    probe = Survey({"name": args.name, "instrument": prefer, "data_root": str(data_root)}, out.parent)
    found = probe.site_dirs()
    if not found:
        print(f"ERROR no site folder with {', '.join(spec['label'] for spec in INSTRUMENTS.values())} "
              f"files under {data_root}")
        return 1
    # a folder of a recorder mt-workbench does not read is not a site of this survey; such folders are listed
    print_skipped(data_root, found, workspace)
    recorder = {site: probe.instrument_of(site) for site in found}
    counts = Counter(recorder.values())  # the most common is the survey's; a tie goes to INSTRUMENTS order
    instrument = prefer if args.instrument not in (None, "auto") else max(INSTRUMENTS, key=lambda i: counts[i])
    channels = channels_from_label(args.channels or default_preset(instrument), instrument)
    if not channels:
        parser.error(f"--channels {args.channels!r} names no channel: a preset ("
                     + "; ".join(CHANNEL_PRESETS[instrument]) + ") or a list such as hx,hy")
    electric_gain = args.electric_gain if args.electric_gain is not None else 1.0
    if args.electric_gain is not None and "edl" not in recorder.values():
        parser.error("--electric-gain is an Earth Data PR6-24 electric-chain setting, and no site here is an EDL")
    facts = {site: read_site(folder, recorder[site], clock_timezone) for site, folder in found.items()}
    # the survey's rate: the most common among its own instrument's sites
    rates = Counter(f["sample_rate"] for site, f in facts.items()
                    if f["sample_rate"] and recorder[site] == instrument)
    sample_rate = rates.most_common(1)[0][0] if rates else 1000.0
    sites, own = build_entries(facts, recorder, instrument, sample_rate)
    # an EDL site whose recorder.ini flags channel_n_high_gain on some channel: printed against
    # the declared electric_gain below for information; the electric chain's gain is declared
    # from the field notes
    ini_flags = {site: f.get("high_gain") for site, f in facts.items()
                if recorder[site] == "edl" and f.get("high_gain")}
    if args.site_table:
        merge_site_table(sites, Path(args.site_table))
        zone = table_timezone(Path(args.site_table))
        if zone and zone != timezone:
            print(f"timezone from the site table: {zone}" +
                  (f" (command line said {args.timezone})" if args.timezone else ""))
            timezone = zone

    out.parent.mkdir(parents=True, exist_ok=True)
    sensor = out.parent / "sensors" / calibration.name
    sensor.parent.mkdir(exist_ok=True)
    if calibration.resolve() != sensor.resolve():
        shutil.copy2(calibration, sensor)
    head = HEAD.format(
        name=scalar(args.name), instrument=instrument,
        sample_rate=int(sample_rate) if float(sample_rate).is_integer() else sample_rate,
        data_root=scalar(data_root.as_posix()), workspace=scalar(workspace.as_posix()),
        timezone=scalar(timezone),
        calibration_fn=scalar(f"sensors/{calibration.name}"),
        channels="[" + ", ".join(scalar(c) for c in channels) + "]",
        edl_sensor="" if instrument != "edl" else (
            "  # EDL (PR6-24) magnetic sensors (mt_workbench.instruments.read_run): lemi120 = LEMI-120\n"
            "  # induction coils, the broadband setup, their response calibration_fn above;\n"
            "  # bartington = Mag-03 fluxgates, long period. Set from the survey's rate (UoA:\n"
            "  # coils at 500/1000 Hz, fluxgates at 10 Hz): check the field sheet\n"
            f"  sensor_type: {edl_sensor_for(sample_rate)}\n"),
        e_sign="" if instrument != "lemi424" else (
            "  # LEMI-424 sites: E1 and E2 are recorded with the opposite sign to the x-north, y-east frame;"
            " -1.0 negates them at ingest\n"
            "  e_sign: -1.0\n"),
        edl_gain="" if args.electric_gain is None else (
            "  # extra gain of the electric chain between the dipoles and the recorded values, beyond\n"
            "  # what the reader already models (the x10 terminal box): hardwired at the field terminal\n"
            "  # junction box, declared from the field notes (EDL sites only)\n"
            f"  electric_gain: {scalar(args.electric_gain)}\n"),
    )
    if instrument == "phoenix":
        head = phoenix_defaults(head)
    if instrument == "orangebox":
        head = orangebox_defaults(head, clock_timezone)
    # the sites block as burra_notes_to_yaml.py's write_sites_block writes it
    body = yaml.safe_dump(sites, sort_keys=False, allow_unicode=True, default_flow_style=False)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + "sites:\n" + indent(body, "  "))

    print(f"wrote {out}: {len(sites)} sites, sample_rate {sample_rate:g} Hz, coil response {sensor}")
    print(f"workspace (archives, TFs, figures): {workspace}")
    print(f"instrument {instrument}; channels declared (defaults): {preset_label(channels, instrument)} "
          f"= {' '.join(channels)}")
    if instrument == "edl":
        print(f"EDL magnetic sensors (defaults: sensor_type): {edl_sensor_for(sample_rate)}, from the "
              f"{sample_rate:g} Hz rate (UoA: coils at 500/1000 Hz, fluxgates at 10 Hz) - check the field sheet")
    if instrument == "edl" or args.electric_gain is not None:
        print(f"EDL electric chain gain (defaults: electric_gain): {electric_gain:g}" +
              ("" if args.electric_gain is not None else
               " (--electric-gain not given) - check the field notes"))
    for site, flags in ini_flags.items():
        print(f"  {site}: recorder.ini sets channel_n_high_gain=1 for {' '.join(flags)}: informational; "
              f"electric_gain {electric_gain:g} is declared from the field notes, not read from recorder.ini")
    print_sites(sites, facts, recorder, own, channels, sample_rate)
    print("next: set dipole lengths and azimuths from the field sheet (the GUI's Metadata tab, or "
          "--site-table); with legacy EDIs, run scripts/match_reference_edis.py <edi_dir> "
          f"{out}")
    print(f"next: fill each site's declination from the IGRF: scripts/declination.py {out} --write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
