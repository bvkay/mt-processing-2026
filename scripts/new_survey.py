"""Start a survey.yaml from a folder of site folders and their B423 headers.

For a new survey that has only its raw data -- one subfolder per site with
LEMI-423 ``*.B423`` files anywhere under it -- and paper field sheets.

Usage:
    python scripts/new_survey.py <data_root> --name NAME [--instrument lemi423]
        [--timezone Australia/Adelaide] [--out PATH] [--calibration FILE]
        [--site-table CSV_OR_XLSX] [--force]

Sites are found by the rule `bbmt.survey.Survey.site_dirs` uses (a subfolder
of data_root with a B423 file anywhere under it; site name = folder name).
For each site, the FIRST B423 file (by its file-name epoch) is read through
mt-io (`mt_io.lemi.lemi423`): `Read_Lemi_Header` for the logger's serial
number and firmware, its GPS latitude, longitude and elevation at deployment,
and `fast_sample_rate` (below) for the sample rate -- a bounded read of the
first 4096 records rather than mt-io's own `Read_Lemi_Data.read_summary`,
which scans the whole file (about 0.7 s a site on Curnamona's 162 MB first
files; the bounded read is milliseconds). The recorded span is the file-name
epochs', first to last plus the median spacing, as the GUI's window bar reads it.

Writes surveys/<name>/survey.yaml (or --out) with the survey's name,
instrument, sample_rate (the most common across sites; a warning names any
site that differs), data_root, timezone and `generated_by:
scripts/new_survey.py`; a `defaults:` block and a `processing:` block; and a
`sites:` block with one entry per folder: latitude, longitude, elevation,
serial, firmware, start and end (UTC), and a note that the dipole lengths and
azimuths are the defaults. Those are not written per site, so the defaults
apply until they are set from the field sheet -- on the GUI's Metadata tab,
or with --site-table (a CSV or XLSX with a `site` column plus any of
`bbmt.survey.SITE_TABLE_COLUMNS`, see docs/site_table_template.csv), whose
values are merged over the header's for the sites it names, except that
the header's GPS fix wins for latitude, longitude and elevation (the table
fills them only where the header has none) and every disagreement is
printed; the MATLAB field app's survey CSV columns (SiteName, ExDipole,
ExAzimuth, ..., TimeZone) are understood too. The coil
response file (default: surveys/burra/sensors/l120n.rsp, the LEMI-120 one)
is copied into the survey folder's sensors/.

An existing survey.yaml is never overwritten without --force: hand edits live
in it. When legacy EDIs exist for the survey (lemimt, a contractor's), run
afterwards

    python scripts/match_reference_edis.py <edi_dir> <survey.yaml>

to write reference_edis.yaml, which the View EDIs tab overlays.
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

from bbmt.ingest import select_files
from bbmt.survey import Survey, read_site_table

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
DEFAULT_FILE_SECONDS = 5400  # a B423 file's nominal span, for a site with one file
DEFAULTS_NOTE = "dipole lengths and azimuths from defaults - set them from the field sheet"
# the LEMI-423's documented rates (mt_io.lemi.lemi_collection.LEMICollection's docstring)
# the LEMI-423's documented rates. There is no 1 Hz mode: a file with one
# record per second (Morocco R05, tick always 0) is an instrument fault and
# is reported as measured, with a warning, never snapped to a known rate
KNOWN_SAMPLE_RATES = (4000.0, 2000.0, 1000.0, 500.0, 250.0)
SAMPLE_RATE_RECORDS = 4096  # bounded read for the rate scan: several seconds even at 250 Hz
DIPOLE_KEYS = ("dipole_length_ex", "dipole_length_ey", "azimuth_ex", "azimuth_ey")
# the order a site entry's keys are written in
KEY_ORDER = (*DIPOLE_KEYS, "latitude", "longitude", "elevation", "remote", "timing",
             "serial", "firmware", "start", "end", "notes")
ISO = "%Y-%m-%dT%H:%M:%SZ"

HEAD = """\
name: {name}
instrument: {instrument}
sample_rate: {sample_rate}
data_root: {data_root}
# local time of the field area (IANA name), for display only: every
# timestamp in the YAML, the archives and the scripts is UTC
timezone: {timezone}
# written by this script from the B423 headers: re-running it (--force)
# overwrites every edit made since, the GUI's Metadata tab included
generated_by: scripts/new_survey.py
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  # LEMI-120 coil response; a relative path resolves against this folder first
  calibration_fn: {calibration_fn}
  # empirical magnetics correction vs the lemimt convention: pT -> nT + polarity
  # (validated at Curnamona on D02/E08: constant 1e6 rho offset, exact 180 deg phase)
  h_scale: -1000.0
  # how to read a 180/270 deg dipole azimuth on the field sheet. true: the pair
  # was wired reversed, so its data are sign-flipped at ingest (Curnamona).
  # false: the azimuth only records the layout direction and the logger's
  # terminals fix polarity, so nothing is flipped (Burra). Check the impedance
  # phase quadrants after the first run: a wrong choice puts one mode 180 deg out.
  flip_reversed_dipoles: true
  # no hz sensor on a broadband deployment: the B423 Bz column is an open
  # input, so it is dropped at ingest
  channels: [ex, ey, hx, hy]
# lemimt-style even log-period band layout (see bbmt.bands.lemimt_band_scheme)
processing:
  min_period: 0.005
  max_period: 5000.0
  periods_per_decade: 10.0
  # keep bands clear of mains and its first in-range harmonic
  notch_frequencies: [50.0, 150.0]
"""


def scalar(value) -> str:
    """One YAML scalar as safe_dump writes it (quoted when it would read back as another type)."""
    return yaml.safe_dump({"k": value}, allow_unicode=True, width=10**9).split(":", 1)[1].strip()


def fast_sample_rate(path: Path, n_records: int = SAMPLE_RATE_RECORDS) -> float | None:
    """The sample rate from a bounded read of `path`, instead of mt-io's whole-file scan.

    Skips the 1024-byte header and reads the first `n_records` of the 30-byte
    records `mt_io.lemi.lemi423.Read_Lemi_Data.binary_format` documents
    (`time`: whole seconds; `tick`: milliseconds within the second, resetting
    to 0 when `time` ticks over). Counting records by their `time` value gives
    records-per-whole-second directly; the last `time` value in the read is
    dropped as possibly cut short by `n_records`, and (in case the read
    starts mid-second) the derived rate is the largest count left, since a
    partial second can only under-count. That is snapped to the nearest of
    the LEMI-423's documented rates (`KNOWN_SAMPLE_RATES`), with a warning if
    it is more than 1% off that rate (dropped samples, or a rate this script
    does not know about).
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
        # not a rate this script knows: report what was measured rather than
        # a wrong known value (R05 at 1 record/s snapped to 250 Hz before 1 Hz was listed)
        print(f"  WARNING {path.name}: derived sample rate {derived} records/s is {off:.1%} off "
              f"the nearest LEMI-423 rate ({nearest:g} Hz) -- kept as measured: not a LEMI-423 rate, an instrument fault or dropped samples")
        return float(derived)
    return nearest


def read_site(site_dir: Path) -> dict:
    """The facts one site's B423 files give: header of the first file, its scan, the file-name span."""
    files = select_files(site_dir)
    epochs = np.array([int(f.stem) for f in files], dtype="int64")
    spacing = int(np.median(np.diff(epochs))) if epochs.size > 1 else DEFAULT_FILE_SECONDS
    start = pd.Timestamp(int(epochs[0]), unit="s", tz="UTC")
    end = pd.Timestamp(int(epochs[-1]) + spacing, unit="s", tz="UTC")
    facts = {"files": len(files), "start": start, "end": end, "sample_rate": None, "problem": None}
    try:
        header = Read_Lemi_Header(files[0]).read()
        facts["sample_rate"] = fast_sample_rate(files[0])
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
    entry = {key: facts[key] for key in ("latitude", "longitude", "elevation", "serial", "firmware")
             if facts.get(key) is not None}
    entry["start"] = facts["start"].strftime(ISO)
    entry["end"] = facts["end"].strftime(ISO)
    entry["notes"] = "; ".join(n for n in (DEFAULTS_NOTE, facts["problem"]) if n)
    return entry


def table_timezone(path: Path) -> str | None:
    """The one time zone a site table names (the MATLAB survey CSV has a
    TimeZone column), or None when absent or inconsistent."""
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
    """Overwrite the header's values with the table's, for the sites it names."""
    rows, ignored = read_site_table(path)
    matched = [s for s in rows if s in sites]
    disagreements = []
    for site in matched:
        entry = sites[site]
        values = dict(rows[site])
        # the header's GPS fix wins for position and elevation: a table is
        # typed or derived by hand (the Morocco CSV carried 45 elevations
        # exactly 1000 m low, a mis-read of the glued `%Alt1168.9` line). The
        # table fills them only where the header has no fix; every
        # disagreement is printed so the student can check the sheet.
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
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_root", help="the folder holding one subfolder per site")
    parser.add_argument("--name", required=True, help="survey name (also the default folder under surveys/)")
    parser.add_argument("--instrument", default="lemi423", choices=["lemi423"])
    parser.add_argument("--timezone", default="Australia/Adelaide", help="IANA name, for display only")
    parser.add_argument("--out", help="survey.yaml to write (default surveys/<name>/survey.yaml)")
    parser.add_argument("--calibration", default=str(DEFAULT_CALIBRATION), help="coil response file")
    parser.add_argument("--site-table", help="CSV or XLSX: a site column plus any editable column")
    parser.add_argument("--force", action="store_true", help="overwrite an existing survey.yaml")
    args = parser.parse_args(argv)

    data_root = Path(args.data_root).resolve()
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

    found = Survey({"name": args.name, "instrument": args.instrument, "data_root": str(data_root)},
                   out.parent).site_dirs()
    if not found:
        print(f"ERROR no site folder with {Survey.RAW_PATTERNS[args.instrument]} files under {data_root}")
        return 1
    facts = {site: read_site(folder) for site, folder in found.items()}
    rates = Counter(f["sample_rate"] for f in facts.values() if f["sample_rate"])
    sample_rate = rates.most_common(1)[0][0] if rates else 1000.0
    sites = {site: site_entry(f) for site, f in facts.items()}
    for site, f in facts.items():
        # a site not at the survey rate is noted where the student will see
        # it (the Metadata table), not only on this console
        if f["sample_rate"] and f["sample_rate"] != sample_rate:
            known = f["sample_rate"] in KNOWN_SAMPLE_RATES
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
        name=scalar(args.name), instrument=args.instrument,
        sample_rate=int(sample_rate) if float(sample_rate).is_integer() else sample_rate,
        data_root=scalar(data_root.as_posix()), timezone=scalar(args.timezone),
        calibration_fn=scalar(f"sensors/{calibration.name}"),
    )
    # the sites block as burra_notes_to_yaml.py's write_sites_block and the GUI's
    # Save write it, so a later save rewrites it without reflowing anything
    body = yaml.safe_dump(sites, sort_keys=False, allow_unicode=True, default_flow_style=False)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + "sites:\n" + indent(body, "  "))

    print(f"wrote {out}: {len(sites)} sites, sample_rate {sample_rate:g} Hz, coil response {sensor}")
    for site, f in facts.items():
        entry = sites[site]
        where = (f"{entry['latitude']:.6f} {entry['longitude']:.6f} {entry.get('elevation', float('nan')):.1f} m"
                 if "latitude" in entry else "no position")
        hours = (f["end"] - f["start"]).total_seconds() / 3600.0
        rate = f"{f['sample_rate']:g} Hz" if f["sample_rate"] else "rate unknown"
        print(f"  {site:<12} serial {entry.get('serial', '-'):>5}  firmware {entry.get('firmware', '-')}  "
              f"{where}  {entry['start']} to {entry['end']} ({hours:.1f} h, {f['files']} files)  {rate}")
        if f["problem"]:
            print(f"  WARNING {site}: {f['problem']}")
        if f["sample_rate"] and f["sample_rate"] != sample_rate:
            print(f"  WARNING {site}: recorded at {f['sample_rate']:g} Hz, the survey says {sample_rate:g} Hz")
    print("next: set dipole lengths and azimuths from the field sheet (the GUI's Metadata tab, or "
          "--site-table); with legacy EDIs, run scripts/match_reference_edis.py <edi_dir> "
          f"{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
