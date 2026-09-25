# -*- coding: utf-8 -*-
"""
Start a survey.yaml from a folder of site folders and their recorders' files

For a new survey that has its raw data and paper field sheets: one subfolder
per site with LEMI-423 ``*.B423``, LEMI-424 ``YYYYMMDDhhmm.txt`` or Earth
Data PR6-24 ``{station}YYMMDDhhmmss.{BX,..,EY}`` files anywhere under it.

Sites are found by the rule of `crust.survey.Survey.site_dirs` (a subfolder
of data_root with any of those files anywhere under it; site name = folder
name), and each site's instrument is detected from its files
(`crust.instruments.detect_instrument`). The survey's `instrument:` is the
most common one, or the one named by `--instrument`. A site recorded on
another instrument gets its own `instrument:` and that instrument's default
`channels:` preset, since its reader uses other channel names. The facts of
LEMI-424 and EDL sites come from `crust.instruments.header_facts`: a
LEMI-424's `.inf` (serial, firmware) and its first data line through mt-io
(GPS position, elevation; 1 Hz), and an EDL's recorder.ini (the rate, or the
file spacing) without a position. Their span runs from the file names to the
end of the last file (`crust.instruments.span`). For each LEMI-423 site the
first B423 file (by its file-name epoch) is read through mt-io
(`mt_io.lemi.lemi423`): `Read_Lemi_Header` gives the logger's serial number
and firmware and its GPS latitude, longitude and elevation at deployment,
and `fast_sample_rate` gives the sample rate from a bounded read of the first
4096 records. mt-io's `Read_Lemi_Data.read_summary` scans the whole file (a
first file can run to more than 100 MB); the bounded read takes milliseconds.
The recorded span is that of the file-name epochs, first to last plus the
median spacing, as the GUI's window bar reads it.

The script writes surveys/<name>/survey.yaml (or --out) with the survey's
name, instrument, sample_rate (the most common across sites; a warning names
any site that differs), data_root, workspace, timezone and `generated_by:
scripts/new_survey.py`; a `defaults:` block and a `processing:` block; and a
`sites:` block with one entry per folder: latitude, longitude, elevation,
serial, firmware, start and end (UTC), and a note that the dipole lengths and
azimuths are the defaults. Dipole lengths and azimuths are left out of the
site entries, so the defaults apply until they are set from the field sheet,
on the GUI's Metadata tab or with --site-table. The site table is a CSV or
XLSX with a `site` column plus any of `crust.survey.SITE_TABLE_COLUMNS`;
its values are merged over the header's for
the sites it names. The header's GPS fix takes precedence for latitude,
longitude and elevation (the table fills them only where the header has
none), and every disagreement is printed. The columns of the field-sheet
survey CSV (SiteName, ExDipole, ExAzimuth, ..., TimeZone) are read as
well. The coil response file (default: surveys/burra/sensors/l120n.rsp, the
LEMI-120 one) is copied into the survey folder's sensors/.

--channels declares which of the recorder's columns had a sensor attached,
which is survey logistics that the files cannot tell. It is a preset label
from `crust.survey.CHANNEL_PRESETS` for the instrument ("Ex Ey Bx By", the
LEMI-423 default, with the Bz column an open input; "Ex Ey Bx By Bz"; "Bx By
(magnetics only)" for a dedicated remote; "Bx By Bz") or a comma list of the
reader's names ("hx,hy"). It is written as `defaults: channels:`, which
ingest applies, dropping every other column from the archive; a site that
differs gets its own `channels:` on the GUI's Metadata tab. The summary
prints, per site, the columns mt-io reads from the first file (the B423
record's Bx By Bz Ex Ey, stored as hx hy hz ex ey) next to the declared set,
and warns when a declared channel is not among them.

--electric-gain names the extra gain of an Earth Data PR6-24 site's electric
chain between the dipoles and the recorded values, beyond what the reader
already models (the x10 terminal box). It is hardwired at the field terminal
junction box and declared from the field notes when the PR6-24's own configs
were not kept (e.g. 10). It is written as `defaults:
electric_gain:`, which ingest folds into a filter of that gain on every EDL
site's ex and ey (`crust.instruments.read_run`). Without the option no key
is written (1.0, no filter). A site's `config/recorder.ini` may carry its
own `channel_n_high_gain` flags (read by
`crust.instruments.recorder_ini_high_gain`, since mt-io's
`read_recorder_ini` keeps one boolean for all six); the summary prints them
against the declared gain for information only. The option is an error when
no site is an EDL.

The workspace, which holds the MTH5 archives, transfer functions, figures and
the basemap, is `<data_root>/work` unless --workspace names another folder.
It sits beside the raw data rather than in the repo because a 100-site
survey's archives run to hundreds of GB. The script writes the key; the
folder is created by the first script that writes into it.

An existing survey.yaml holds hand edits and is overwritten only with
--force. When legacy EDIs exist for the survey (lemimt, a contractor's), run

    python scripts/match_reference_edis.py <edi_dir> <survey.yaml>

afterwards to write reference_edis.yaml, which the View EDIs tab overlays.

Usage:
    python scripts/new_survey.py <data_root> --name NAME [--instrument auto]
        [--channels "Ex Ey Bx By"] [--electric-gain 10]
        [--timezone Australia/Adelaide] [--out PATH]
        [--workspace DIR] [--calibration FILE] [--site-table CSV_OR_XLSX] [--force]

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

from crust.ingest import select_files
from crust.instruments import INSTRUMENTS, header_facts, record_files, span
from crust.survey import (
    CHANNEL_PRESETS, Survey, channels_from_label, default_preset, preset_label, read_site_table,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
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
             "elevation", "remote", "timing", "serial", "firmware", "start", "end", "notes")
# an EDL site's magnetic sensors from its rate (`sensor_type`, crust.instruments.EDL_SENSORS): the
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
# written by this script from the raw files' headers: re-running it (--force)
# overwrites every edit made since, the GUI's Metadata tab included
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
  # how to read a 180/270 deg dipole azimuth on the field sheet. true: the pair
  # was wired reversed, so its data are sign-flipped at ingest. false: the
  # azimuth only records the layout direction and the logger's terminals fix
  # polarity, so nothing is flipped. Check the impedance
  # phase quadrants after the first run: a wrong choice puts one mode 180 deg out.
  flip_reversed_dipoles: true
  # the columns that had a sensor attached (--channels, crust.survey.CHANNEL_PRESETS),
  # in the survey instrument's names; ingest drops the rest, e.g. the B423 Bz column,
  # an open input with no hz coil. A site on another instrument has its own channels:
  channels: {channels}
{edl_sensor}{edl_gain}# lemimt-style even log-period band layout (see crust.bands.build_band_scheme)
processing:
  min_period: 0.005
  max_period: 5000.0
  periods_per_decade: 10.0
  # keep bands clear of mains and its first in-range harmonic
  notch_frequencies: [50.0, 150.0]
"""


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
              f"the nearest LEMI-423 rate ({nearest:g} Hz) -- kept as measured: not a LEMI-423 rate, an instrument fault or dropped samples")
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


def read_other_site(site_dir: Path, instrument: str) -> dict:
    """Read the facts of a LEMI-424 or EDL site.

    Args:
        site_dir (Path): The site's folder.
        instrument (str): "lemi424" or "edl".

    Returns:
        dict: files, start, end, sample_rate, problem and columns, updated
        with `crust.instruments.header_facts`. An unreadable first file is
        recorded in "problem".
    """
    files = record_files(site_dir, instrument)
    start, end, n = span(site_dir, instrument, files)
    facts = {"files": n, "start": start, "end": end, "sample_rate": None, "problem": None, "columns": None}
    try:
        facts.update(header_facts(site_dir, instrument, files))
    except Exception as exc:  # an unreadable first file: the site is still listed
        facts["problem"] = f"first {INSTRUMENTS[instrument]['label']} file unreadable ({files[0].name}: {exc})"
    return facts


def read_site(site_dir: Path, instrument: str = "lemi423") -> dict:
    """Read the facts of one site's files.

    For a LEMI-423 site: the header and a bounded scan of the first B423
    file, and the span of the file names. Other instruments go to
    `read_other_site`.

    Args:
        site_dir (Path): The site's folder.
        instrument (str): The site's instrument.

    Returns:
        dict: files, start, end, sample_rate, problem and columns, plus
        serial, firmware and the GPS position when the header has them.
    """
    if instrument != "lemi423":
        return read_other_site(site_dir, instrument)
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


def merge_site_table(sites: dict, path: Path) -> None:
    """Merge a site table over the header values, for the sites it names.

    Position and elevation from the header's GPS fix are kept; the table
    fills them only where the header has none. Disagreements, unmatched
    sites and ignored columns are printed.

    Args:
        sites (dict): Site entries, updated in place.
        path (Path): CSV or XLSX site table.
    """
    rows, ignored = read_site_table(path)
    matched = [s for s in rows if s in sites]
    disagreements = []
    for site in matched:
        entry = sites[site]
        values = dict(rows[site])
        # the header's GPS fix takes precedence for position and elevation: a
        # table is typed or derived by hand (elevations exactly 1000 m low come
        # from a mis-read of the header's glued four-digit `%Alt` line). The
        # table fills them only where the header has no fix; every
        # disagreement is printed for a check against the sheet.
        for key, tol in (("latitude", 0.0005), ("longitude", 0.0005), ("elevation", 20.0)):
            if key in values and entry.get(key) is not None:
                if abs(float(values[key]) - float(entry[key])) > tol:
                    disagreements.append(f"{site} {key}: table {values[key]} vs header {entry[key]} -> header kept")
                del values[key]
        entry.update(values)
        if all(k in entry for k in DIPOLE_KEYS) and "notes" not in rows[site]:
            entry["notes"] = entry["notes"].replace(DEFAULTS_NOTE, "").lstrip("; ")
            if not entry["notes"]:
                del entry["notes"]
        sites[site] = {k: entry[k] for k in KEY_ORDER if k in entry}
    print(f"site table {path.name}: {len(matched)} of {len(rows)} sites matched")
    for line in disagreements:
        print(f"  WARNING {line}")
    missing = sorted(set(rows) - set(sites))
    if missing:
        print(f"  WARNING not a site folder: {', '.join(missing)}")
    if ignored:
        print(f"  WARNING ignored columns: {', '.join(ignored)}")


def main(argv=None) -> int:
    """Write the survey.yaml and print the per-site summary.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 1 when no site folder is found, 2 when the
        survey.yaml exists and --force was not given.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_root", help="the folder holding one subfolder per site")
    parser.add_argument("--name", required=True, help="survey name (also the default folder under surveys/)")
    parser.add_argument("--instrument", default="auto", choices=["auto", *INSTRUMENTS],
                        help="the survey's instrument (default: the most common among the sites' folders)")
    parser.add_argument("--channels", help="the columns that had a sensor, for the survey's instrument: a "
                        "preset label (LEMI-423: " + "; ".join(CHANNEL_PRESETS["lemi423"]) + ") or a comma "
                        "list such as hx,hy; default the instrument's first preset")
    parser.add_argument("--electric-gain", type=float, help="extra gain of an EDL (PR6-24) site's electric "
                        "chain beyond the reader's own (the x10 terminal box), declared from the field "
                        "notes, e.g. 10; written as defaults: electric_gain")
    parser.add_argument("--timezone", default="Australia/Adelaide", help="IANA name, for display only")
    parser.add_argument("--out", help="survey.yaml to write (default surveys/<name>/survey.yaml)")
    parser.add_argument("--workspace", help="archives, TFs and figures (default <data_root>/work)")
    parser.add_argument("--calibration", default=str(DEFAULT_CALIBRATION), help="coil response file")
    parser.add_argument("--site-table", help="CSV or XLSX: a site column plus any editable column")
    parser.add_argument("--force", action="store_true", help="overwrite an existing survey.yaml")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else data_root / "work"
    out = Path(args.out) if args.out else REPO / "surveys" / args.name / "survey.yaml"
    out = out.resolve()
    calibration = Path(args.calibration)
    try:
        pd.Timestamp.now(tz=args.timezone)
    except Exception:
        parser.error(f"unknown timezone {args.timezone!r} (an IANA name, e.g. Australia/Adelaide)")
    if not data_root.is_dir():
        parser.error(f"no such folder: {data_root}")
    if not calibration.is_file():
        parser.error(f"no such coil response file: {calibration}")
    if out.exists() and not args.force:
        print(f"ERROR {out} exists: it may hold hand edits. Pass --force to overwrite it.")
        return 2

    prefer = "lemi423" if args.instrument == "auto" else args.instrument
    probe = Survey({"name": args.name, "instrument": prefer, "data_root": str(data_root)}, out.parent)
    found = probe.site_dirs()
    if not found:
        print(f"ERROR no site folder with {', '.join(spec['label'] for spec in INSTRUMENTS.values())} "
              f"files under {data_root}")
        return 1
    # a folder of a recorder CRUST does not read (Orange Box HFM*.BIN files, say) is not
    # a site of this survey; such folders are listed here
    skipped = sorted(d.name for d in data_root.iterdir() if d.is_dir() and d.name not in found)
    if skipped:
        print(f"skipped {len(skipped)} folder(s) with no {', '.join(spec['label'] for spec in INSTRUMENTS.values())} "
              f"files (not a recorder CRUST reads, or no data): {', '.join(skipped)}")
    recorder = {site: probe.instrument_of(site) for site in found}
    counts = Counter(recorder.values())  # the most common is the survey's; a tie goes to INSTRUMENTS order
    instrument = prefer if args.instrument != "auto" else max(INSTRUMENTS, key=lambda i: counts[i])
    channels = channels_from_label(args.channels or default_preset(instrument), instrument)
    if not channels:
        parser.error(f"--channels {args.channels!r} names no channel: a preset ("
                     + "; ".join(CHANNEL_PRESETS[instrument]) + ") or a list such as hx,hy")
    own = {site: channels_from_label(default_preset(inst), inst)
           for site, inst in recorder.items() if inst != instrument}
    electric_gain = args.electric_gain if args.electric_gain is not None else 1.0
    if args.electric_gain is not None and "edl" not in recorder.values():
        parser.error("--electric-gain is an Earth Data PR6-24 electric-chain setting, and no site here is an EDL")
    facts = {site: read_site(folder, recorder[site]) for site, folder in found.items()}
    # the survey's rate: the most common among its own instrument's sites
    rates = Counter(f["sample_rate"] for site, f in facts.items()
                    if f["sample_rate"] and recorder[site] == instrument)
    sample_rate = rates.most_common(1)[0][0] if rates else 1000.0
    sites = {site: site_entry(f) for site, f in facts.items()}
    for site, site_channels in own.items():
        entry = dict(sites[site], instrument=recorder[site], channels=site_channels)
        if recorder[site] == "edl":  # an EDL site in another recorder's survey: its own sensors
            entry["sensor_type"] = edl_sensor_for(facts[site]["sample_rate"])
        sites[site] = {k: entry[k] for k in KEY_ORDER if k in entry}
    # an EDL site whose recorder.ini flags channel_n_high_gain on some channel: printed against
    # the declared electric_gain below for information; the electric chain's gain is declared
    # from the field notes
    ini_flags = {site: f.get("high_gain") for site, f in facts.items()
                if recorder[site] == "edl" and f.get("high_gain")}
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
    if args.site_table:
        merge_site_table(sites, Path(args.site_table))
        zone = table_timezone(Path(args.site_table))
        if zone and zone != args.timezone:
            print(f"timezone from the site table: {zone} (command line said {args.timezone})")
            args.timezone = zone

    out.parent.mkdir(parents=True, exist_ok=True)
    sensor = out.parent / "sensors" / calibration.name
    sensor.parent.mkdir(exist_ok=True)
    if calibration.resolve() != sensor.resolve():
        shutil.copy2(calibration, sensor)
    head = HEAD.format(
        name=scalar(args.name), instrument=instrument,
        sample_rate=int(sample_rate) if float(sample_rate).is_integer() else sample_rate,
        data_root=scalar(data_root.as_posix()), workspace=scalar(workspace.as_posix()),
        timezone=scalar(args.timezone),
        calibration_fn=scalar(f"sensors/{calibration.name}"),
        channels="[" + ", ".join(scalar(c) for c in channels) + "]",
        edl_sensor="" if instrument != "edl" else (
            "  # EDL (PR6-24) magnetic sensors (crust.instruments.read_run): lemi120 = LEMI-120\n"
            "  # induction coils, the broadband setup, their response calibration_fn above;\n"
            "  # bartington = Mag-03 fluxgates, long period. Set from the survey's rate (UoA:\n"
            "  # coils at 500/1000 Hz, fluxgates at 10 Hz): check the field sheet\n"
            f"  sensor_type: {edl_sensor_for(sample_rate)}\n"),
        edl_gain="" if args.electric_gain is None else (
            "  # extra gain of the electric chain between the dipoles and the recorded values, beyond\n"
            "  # what the reader already models (the x10 terminal box): hardwired at the field terminal\n"
            "  # junction box, declared from the field notes (EDL sites only)\n"
            f"  electric_gain: {scalar(args.electric_gain)}\n"),
    )
    # the sites block as burra_notes_to_yaml.py's write_sites_block and the GUI's
    # Save write it, so a later save rewrites it without reflowing anything
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
        print(f"  {site}: recorder.ini sets channel_n_high_gain=1 for {' '.join(flags)} -- informational, "
              f"electric_gain {electric_gain:g} is declared from the field notes, not read from recorder.ini")
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
    print("next: set dipole lengths and azimuths from the field sheet (the GUI's Metadata tab, or "
          "--site-table); with legacy EDIs, run scripts/match_reference_edis.py <edi_dir> "
          f"{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
