"""A UoA field-notes CSV (the Stuart Shelf 2009 layout) -> the site table new_survey.py --site-table reads.

Usage:
    python scripts/site_table_from_notes.py <notes.csv> <site_table.csv>
        [--timezone Australia/Adelaide] [--data-root DIR]

The notes CSV is the field spreadsheet saved as CSV: a few header rows (group
titles, long names, units), then the row that starts `Station` and names the
columns (`Longitude_dd`, `Latitude_dd`, `Elevation`, `X_dip_length`, ...),
then one row per station; blank rows are skipped. Written per station:

    site               Station, as typed (it must match the site's folder name)
    latitude/longitude Latitude_dd / Longitude_dd; where those are blank, the
                       degree/minute pairs beside them (south and east: the DMS
                       columns carry no sign). Where both are given and differ by
                       more than 1e-4 deg, a warning is printed and the decimal kept
    elevation          Elevation (m)
    dipole_length_ex   X_dip_length (the north line = Ex), m
    dipole_length_ey   Y_dip_length (the east line = Ey), m
    azimuth_ex/_ey     X_orientation / Y_orientation, deg, as typed (-90 is a
                       reversed east line; ingest reads it as 270)
    timezone           --timezone, one value for the table (new_survey.py takes
                       the survey's `timezone:` from it)
    notes              survey; logger box / EDL / HD serials, magnetometer, rate,
                       gain, declination; deployment and recovery in local time
                       and in UTC computed from it; where the sheet's typed UTC
                       is over an hour from that, a note saying so (and a printed
                       warning); the deployment / recovery / processing notes

Every other column is left out. A blank cell stays blank (the survey default
then applies; a blank dipole length is also named in the site's notes). With
--data-root, the stations are compared with the site folders there: a station
with no folder and a folder with no station are both printed.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

COLUMNS = ["site", "latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey",
           "azimuth_ex", "azimuth_ey", "timezone", "notes"]
DMS_TOLERANCE_DEG = 1e-4


def _num(value) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except ValueError:
        return None


def read_notes(path: Path) -> pd.DataFrame:
    """The station rows, columns named by the header row (the first row starting `Station` with `Latitude_dd`)."""
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.reader(f))
    at = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Station" and "Latitude_dd" in r), None)
    if at is None:
        raise ValueError(f"{path.name}: no header row starting 'Station' with a 'Latitude_dd' column")
    header = [h.strip() for h in rows[at]]
    # the degree/minute pairs have no name in that row: take them from the long-name row above
    # ("Long", "", "Lat", "") where it has them
    names = next((r for r in reversed(rows[:at]) if "Long" in [c.strip() for c in r]), None)
    if names:
        i_long = [c.strip() for c in names].index("Long")
        i_lat = [c.strip() for c in names].index("Lat")
        for i, name in ((i_long, "Long_deg"), (i_long + 1, "Long_min"), (i_lat, "Lat_deg"), (i_lat + 1, "Lat_min")):
            if i < len(header) and not header[i]:
                header[i] = name
    body = [r + [""] * (len(header) - len(r)) for r in rows[at + 1:] if r and r[0].strip()]
    return pd.DataFrame([r[: len(header)] for r in body], columns=header)


def to_utc(local: str, zone: str) -> pd.Timestamp | None:
    text = str(local).strip()
    if not text:
        return None
    t = pd.to_datetime(text, dayfirst=True)
    return t.tz_localize(zone, ambiguous="raise", nonexistent="raise").tz_convert("UTC")


def typed_utc_disagrees(typed: str, computed: pd.Timestamp | None) -> bool:
    """Whether the sheet's typed UTC (a time, or a date and time) is more than an hour from `computed`."""
    text = str(typed).strip()
    if not text or computed is None:
        return False
    if "/" in text:
        t = pd.to_datetime(text, dayfirst=True).tz_localize("UTC")
        return abs((t - computed).total_seconds()) > 3600
    h, m = (int(x) for x in text.split(":")[:2])
    diff = abs((h * 60 + m) - (computed.hour * 60 + computed.minute))
    return min(diff, 1440 - diff) > 60


def site_row(r: pd.Series, zone: str, warnings: list[str]) -> dict:
    site = r["Station"].strip()
    lat, lon = _num(r.get("Latitude_dd")), _num(r.get("Longitude_dd"))
    dms = {k: _num(r.get(k)) for k in ("Lat_deg", "Lat_min", "Long_deg", "Long_min")}
    if None not in dms.values():
        dlat = -(dms["Lat_deg"] + dms["Lat_min"] / 60.0)
        dlon = dms["Long_deg"] + dms["Long_min"] / 60.0
        if lat is None or lon is None:
            lat, lon = (lat if lat is not None else round(dlat, 6)), (lon if lon is not None else round(dlon, 6))
            warnings.append(f"{site}: position from the degree/minute columns")
        elif abs(lat - dlat) > DMS_TOLERANCE_DEG or abs(lon - dlon) > DMS_TOLERANCE_DEG:
            warnings.append(f"{site}: decimal {lat}, {lon} vs degree/minute {dlat:.5f}, {dlon:.5f} -> decimal kept")
    dep, rec = to_utc(r.get("Depl_Date", ""), zone), to_utc(r.get("Recovery_date", ""), zone)
    sheet_flags = []
    for label, typed, computed in (("start", r.get("Start_time_UTC", ""), dep), ("end", r.get("End_time_UTC", ""), rec)):
        if typed_utc_disagrees(typed, computed):
            warnings.append(f"{site}: typed {label} UTC {str(typed).strip()!r} vs {computed:%Y-%m-%d %H:%M} from the "
                            f"local time (both kept in the notes)")
            sheet_flags.append(f"the sheet's typed {label} UTC {str(typed).strip()} disagrees with its local time")
    blank = [xy for xy in ("X", "Y") if _num(r.get(f"{xy}_dip_length")) is None]
    if blank:
        warnings.append(f"{site}: dipole length blank on the sheet (X {r.get('X_dip_length', '')!r}, "
                        f"Y {r.get('Y_dip_length', '')!r}) -> survey default")
        sheet_flags.append(f"{'/'.join(blank)} dipole length blank on the sheet: the survey default applies")

    def cell(name):
        return str(r.get(name, "")).strip()

    kit = ", ".join(t for t in (
        f"box {cell('Instr_box')}" if cell("Instr_box") else "",
        f"EDL {cell('EDLogger')}" if cell("EDLogger") else "",
        f"HD {cell('HD_No:')}" if cell("HD_No:") else "",
        " ".join(t for t in (cell("Mag_Type"), cell("Mag_Sens")) if t),
        f"{cell('Sampling_rate')} Hz" if cell("Sampling_rate") else "",
        f"gain {cell('Gain')}" if cell("Gain") else "",
        f"declination {cell('Declination')}" if cell("Declination") else "",
    ) if t)
    when = (f"deployed {cell('Depl_Date')} local = {dep:%Y-%m-%d %H:%M} UTC" if dep is not None else "deployed ?") + ", " + \
           (f"recovered {cell('Recovery_date')} local = {rec:%Y-%m-%d %H:%M} UTC" if rec is not None else "recovered ?")
    remarks = " | ".join(t for t in (cell("Notes_Deployment"), cell("Notes_Recovery"), cell("Notes_Processing")) if t)
    return {
        "site": site, "latitude": lat, "longitude": lon, "elevation": _num(r.get("Elevation")),
        "dipole_length_ex": _num(r.get("X_dip_length")), "dipole_length_ey": _num(r.get("Y_dip_length")),
        "azimuth_ex": _num(r.get("X_orientation")), "azimuth_ey": _num(r.get("Y_orientation")),
        "timezone": zone,
        "notes": "; ".join(t for t in (cell("Survey"), kit, when, *sheet_flags, remarks) if t),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("notes_csv")
    p.add_argument("site_table")
    p.add_argument("--timezone", default="Australia/Adelaide", help="IANA name of the local times on the sheet")
    p.add_argument("--data-root", help="compare the stations with the site folders here")
    args = p.parse_args(argv)
    notes = read_notes(Path(args.notes_csv))
    warnings: list[str] = []
    rows = [site_row(r, args.timezone, warnings) for _, r in notes.iterrows()]
    sites = [r["site"] for r in rows]
    twice = sorted({s for s in sites if sites.count(s) > 1})
    if twice:
        print(f"ERROR station(s) on more than one row: {', '.join(twice)}")
        return 1
    out = Path(args.site_table)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(out, index=False, encoding="utf-8")
    print(f"wrote {out}: {len(rows)} stations, timezone {args.timezone}")
    for w in warnings:
        print(f"  WARNING {w}")
    if args.data_root:
        folders = {d.name for d in Path(args.data_root).iterdir() if d.is_dir()}
        no_folder = [s for s in sites if s not in folders]
        no_station = sorted(folders - set(sites))
        print(f"  stations with no folder under {args.data_root}: {', '.join(no_folder) or 'none'}")
        print(f"  folders with no station: {', '.join(no_station) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
