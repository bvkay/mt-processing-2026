# -*- coding: utf-8 -*-
"""
Render one-second observatory data held as parquet into the observatory day cache

`mt_workbench.observatory` reads an INTERMAGNET observatory's one-second X, Y,
Z, F from a day cache, one gzip file of IAGA-2002 text per UTC day at
<cache>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz, and
scripts/fetch_observatory.py fetches from the BGS GIN only the days missing
from it. This script fills the cache from one-second data already held as
parquet, with columns DateTime (UTC), BX, BY, BZ and F (geographic X, Y, Z
and the total field in nT, NaN where missing) and pub (the day's
publication state). fetch_observatory.py and `observatory.load` then read
the rendered days as cached days.

Each UTC day of [start, end] (default: the parquet's span) is written in the
layout the GIN serves: 70-character lines; the header (Format, Source of
Data, Station Name, IAGA Code, Geodetic Latitude, Geodetic Longitude in
0-360 east, Elevation, Reported XYZF, Sensor Orientation, Digital Sampling,
Data Interval Type, and Data Type from pub); comment lines naming the
parquet file, its fetch record and this script's version; the column line;
then one row for every second of the day, X, Y, Z, F to 0.01 nT, with
99999.00 for a missing value and for a second absent from the parquet. A
day whose rows hold no finite X, Y, Z is written all 99999.00 with a
comment line saying so; a day with no row in the parquet is skipped. The
text is gzipped with the parquet file's modification time as the fetch
time in the gzip header, written to a temporary file and moved into place,
as `observatory._write_day` stores a fetched day. An existing day file is
kept unless --force.

The position is --lat, --lon (degrees east) and --elev (m). For CNB they
default to -35.315, 149.363 and 859 m for the Canberra observatory
(Geoscience Australia); ISGI lists -35.313, 149.364 and 859 m, and the
GIN's quasi-definitive IAGA-2002 headers give -35.317, 149.367 and 859 m.

The script imports numpy and pandas, and pyarrow inside `read_parquet` and
`parquet_span` only, so `render_day` runs on an interpreter without pyarrow
and the script on one without mt_workbench.

Usage:
    python scripts/observatory_from_parquet.py <parquet> <IAGA code> --cache DIR
        [--start UTC] [--end UTC] [--lat DEG --lon DEG --elev M]
        [--record FILE] [--force] [--dry-run]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "1.0"
SECONDS_PER_DAY = 86400
NS = 10**9
MISSING = 99999.0  # IAGA-2002 missing value
FILL_AT = 88888.0  # |value| >= this reads back as missing (observatory.FILL_AT)
WIDTH = 70  # IAGA-2002 line length, the closing "|" included
RECORD_NAME = "run_fetch_1sec.json"  # the fetch record kept beside the year files
COLUMNS = ["DateTime", "BX", "BY", "BZ", "F", "pub"]
KNOWN = {"CNB": dict(name="Canberra", source="Geoscience Australia", latitude=-35.315, longitude=149.363,
                     elevation=859.0)}
ISO = "%Y-%m-%dT%H:%M:%SZ"
_CLOCK = [f"{h:02d}:{m:02d}:{s:02d}" for h in range(24) for m in range(60) for s in range(60)]


def _day(value) -> date:
    """Return the UTC calendar date of a time value."""
    t = pd.Timestamp(value)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC")
    return t.date()


def _day_ns(day) -> np.int64:
    """Return 00:00 UTC of a day in ns since the epoch."""
    return np.int64(pd.Timestamp(_day(day)).value)


def day_path(cache_dir, code: str, day) -> Path:
    """Return the cache path of one day: <cache_dir>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz."""
    d = _day(day)
    code = code.upper()
    return Path(cache_dir) / code / f"{d.year:04d}" / f"{code}_{d:%Y-%m-%d}.sec.gz"


def day_ranges(days) -> str:
    """Format dates as runs of consecutive days, e.g. "2016-01-20 .. 2016-01-22 (3), 2016-02-01"."""
    days = sorted(days)
    if not days:
        return "none"
    out, a, b = [], days[0], days[0]
    for d in days[1:] + [None]:
        if d is not None and (d - b).days == 1:
            b = d
            continue
        out.append(str(a) if a == b else f"{a} .. {b} ({(b - a).days + 1})")
        if d is not None:
            a = b = d
    return ", ".join(out)


def _header_line(label: str, value: str) -> str:
    """Return one IAGA-2002 header line, label and value in fixed columns."""
    line = f" {label:<23}{value:<45}|"
    if len(line) != WIDTH:
        raise ValueError(f"IAGA-2002 header value too long for {label!r}: {value!r}")
    return line


def render_day(day, times, x, y, z, f, *, code: str, latitude: float, longitude: float, elevation: float,
               data_type: str, station_name: str = "", source: str = "", comments=()) -> bytes:
    """Render one UTC day as IAGA-2002 text in the GIN's layout.

    Every second of the day gets a row. Values are placed by their own time
    stamps; a second with no row, or with a NaN value, is written 99999.00.
    Rows outside the day are ignored.

    Args:
        day: The UTC day, any value pandas reads as a date.
        times: Time stamps of the rows, UTC, on whole seconds: datetime64
            values, or int64 ns since the epoch.
        x, y, z, f: Geographic X, Y, Z and the total field F in nT, NaN
            where missing.
        code (str): IAGA code.
        latitude (float): Geodetic latitude in degrees.
        longitude (float): Geodetic longitude in degrees east; written 0-360.
        elevation (float): Elevation in m.
        data_type (str): The header's Data Type, the day's publication state.
        station_name (str): The header's Station Name.
        source (str): The header's Source of Data.
        comments (iterable of str): Comment lines, wrapped to the line width.

    Returns:
        bytes: The ASCII text, each line ending in a newline.

    Raises:
        ValueError: If a time stamp is off the whole second or repeated, a
            finite value reaches 88888 nT (it would read back as missing), or
            a header value is too long.
    """
    code = code.upper()
    d = _day(day)
    t = np.asarray(times)
    t = t.astype("datetime64[ns]").astype(np.int64) if t.dtype.kind == "M" else t.astype(np.int64)
    k_ns = t - _day_ns(d)
    sel = (k_ns >= 0) & (k_ns < SECONDS_PER_DAY * NS)
    k_ns = k_ns[sel]
    if (k_ns % NS).any():
        raise ValueError(f"{code} {d}: {int((k_ns % NS != 0).sum())} time stamp(s) off the whole second")
    k = k_ns // NS
    if np.unique(k).size != k.size:
        raise ValueError(f"{code} {d}: {k.size - np.unique(k).size} repeated time stamp(s)")
    grid = np.full((SECONDS_PER_DAY, 4), MISSING)
    for j, v in enumerate((x, y, z, f)):
        v = np.asarray(v, dtype=float)[sel]
        ok = np.isfinite(v)
        if (np.abs(v[ok]) >= FILL_AT).any():
            raise ValueError(f"{code} {d}: a finite value reaches {FILL_AT:.0f} nT and would read back as missing")
        grid[k[ok], j] = v[ok]
    lines = [
        _header_line("Format", "IAGA-2002"),
        _header_line("Source of Data", source),
        _header_line("Station Name", station_name),
        _header_line("IAGA Code", code),
        _header_line("Geodetic Latitude", f"{latitude:.3f}"),
        _header_line("Geodetic Longitude", f"{longitude % 360.0:.3f}"),
        _header_line("Elevation", f"{elevation:g}"),
        _header_line("Reported", "XYZF"),
        _header_line("Sensor Orientation", ""),
        _header_line("Digital Sampling", ""),
        _header_line("Data Interval Type", "1-second"),
        _header_line("Data Type", data_type),
    ]
    for text in comments:
        lines += [f" # {piece:<66}|" for piece in textwrap.wrap(text, 66)]
    lines.append(f"DATE       TIME         DOY     {code}X      {code}Y      {code}Z      {code}F   |")
    stem = f"{d:%Y-%m-%d} "
    doy = f".000 {d.timetuple().tm_yday:03d}   "
    lines += [f"{stem}{clock}{doy}{a:10.2f}{b:10.2f}{c:10.2f}{e:10.2f}"
              for clock, (a, b, c, e) in zip(_CLOCK, grid.tolist())]
    return ("\n".join(lines) + "\n").encode("ascii")


def write_day(path, raw: bytes, fetched: datetime) -> None:
    """Write the text gzipped, with the fetch time in the gzip header, via a temporary file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(gzip.compress(raw, compresslevel=6, mtime=int(fetched.timestamp())))
    os.replace(tmp, path)


def read_parquet(path, start=None, end=None) -> dict:
    """Read the rows of [start, end) from a one-second parquet file.

    Args:
        path (str or Path): Parquet file with columns DateTime, BX, BY, BZ, F
            and pub.
        start: First time read (UTC); the file's start when None.
        end: Time after the last one read (UTC); the file's end when None.

    Returns:
        dict: ``times`` (int64 ns since the epoch, UTC, sorted), ``x``,
        ``y``, ``z``, ``f`` (float64 nT) and ``pub`` (str array, "" where
        null).

    Raises:
        ValueError: If a column is absent.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    schema = pq.read_schema(path)
    absent = [c for c in COLUMNS if c not in schema.names]
    if absent:
        raise ValueError(f"{Path(path).name}: no column {absent} (columns {schema.names})")
    tz = getattr(schema.field("DateTime").type, "tz", None)
    filters = []
    for op, value in ((">=", start), ("<", end)):
        if value is not None:
            t = pd.Timestamp(value)
            t = t.tz_convert("UTC") if t.tzinfo is not None else t.tz_localize("UTC")
            filters.append(("DateTime", op, t if tz else t.tz_localize(None)))
    table = pq.read_table(path, columns=COLUMNS, filters=filters or None)
    times = table.column("DateTime").cast(pa.timestamp("ns", tz)).cast(pa.int64()).to_numpy()
    order = np.argsort(times, kind="stable") if (np.diff(times) < 0).any() else slice(None)
    out = dict(times=times[order])
    for name, col in (("x", "BX"), ("y", "BY"), ("z", "BZ"), ("f", "F")):
        out[name] = table.column(col).cast(pa.float64()).to_numpy()[order]
    pub = pc.fill_null(table.column("pub").combine_chunks(), "").dictionary_encode()
    names = np.array(pub.dictionary.to_pylist(), dtype=object)
    out["pub"] = names[pub.indices.to_numpy(zero_copy_only=False)][order] if len(names) else \
        np.full(times.size, "", dtype=object)
    return out


def parquet_span(path) -> tuple[date, date]:
    """Return the UTC dates of the first and last time stamp of a parquet file."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    col = pq.read_table(path, columns=["DateTime"]).column("DateTime")
    tz = getattr(col.type, "tz", None)
    span = pc.min_max(col.cast(pa.timestamp("ns", tz)).cast(pa.int64()))
    lo, hi = span["min"].as_py(), span["max"].as_py()
    return pd.Timestamp(lo, unit="ns").date(), pd.Timestamp(hi, unit="ns").date()


def main(argv=None) -> int:
    """Render the days of a parquet file into the day cache.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 2 when the position is unknown or the days hold
        no row of the parquet.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    parser.add_argument("parquet")
    parser.add_argument("code", help="the observatory's IAGA code, e.g. CNB")
    parser.add_argument("--cache", required=True, help="day cache root, e.g. <workspace>/observatory")
    parser.add_argument("--start", help="UTC date or time, its whole day included (default: the parquet's first day)")
    parser.add_argument("--end", help="UTC date or time, its whole day included (default: the parquet's last day)")
    parser.add_argument("--lat", type=float, help="geodetic latitude, degrees")
    parser.add_argument("--lon", type=float, help="geodetic longitude, degrees east")
    parser.add_argument("--elev", type=float, help="elevation, m")
    parser.add_argument("--record", help=f"fetch record named in the comments (default: {RECORD_NAME} beside the parquet)")
    parser.add_argument("--force", action="store_true", help="rewrite days already in the cache")
    parser.add_argument("--dry-run", action="store_true", help="print the days that would be written; write nothing")
    args = parser.parse_args(argv)

    code = args.code.upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        parser.error(f"{args.code!r} is not an IAGA code (three letters)")
    known = KNOWN.get(code, {})
    lat = args.lat if args.lat is not None else known.get("latitude")
    lon = args.lon if args.lon is not None else known.get("longitude")
    elev = args.elev if args.elev is not None else known.get("elevation")
    if None in (lat, lon, elev):
        print(f"ERROR no position for {code}: give --lat, --lon and --elev", file=sys.stderr)
        return 2
    parquet = Path(args.parquet).resolve()
    if not parquet.is_file():
        parser.error(f"no file {parquet}")
    record = Path(args.record) if args.record else parquet.parent / RECORD_NAME
    fetched = datetime.fromtimestamp(int(parquet.stat().st_mtime), timezone.utc)
    cache = Path(args.cache).resolve()

    first, last = (_day(args.start) if args.start else None), (_day(args.end) if args.end else None)
    if first is None or last is None:
        span = parquet_span(parquet)
        first, last = first or span[0], last or span[1]
    if last < first:
        parser.error(f"end {last} is before start {first}")
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    data = read_parquet(parquet, pd.Timestamp(first), pd.Timestamp(last + timedelta(days=1)))
    if not data["times"].size:
        print(f"ERROR {parquet.name} holds no row in {first} .. {last}", file=sys.stderr)
        return 2

    comments = [f"Rendered from {parquet.name} by observatory_from_parquet {VERSION} (mt-workbench).",
                f"Fetch record: {record.name if record.is_file() else 'none found'}.",
                f"Parquet modified {fetched.strftime(ISO)}, the fetch time in the gzip header."]
    print(f"{code} {first} .. {last}: {len(days)} day(s) from {parquet.name} into {cache / code} "
          f"(position {lat}, {lon}, {elev:g} m; fetch time {fetched.strftime(ISO)})")
    kept, absent, written, empty = [], [], [], []
    verb = "would write" if args.dry_run else "written"
    for d in days:
        path = day_path(cache, code, d)
        if path.exists() and not args.force:
            kept.append(d)
            continue
        t0 = _day_ns(d)
        a, b = np.searchsorted(data["times"], [t0, t0 + np.int64(SECONDS_PER_DAY * NS)])
        if a == b:
            absent.append(d)
            continue
        part = {c: data[c][a:b] for c in ("times", "x", "y", "z", "f", "pub")}
        good = int((np.isfinite(part["x"]) & np.isfinite(part["y"]) & np.isfinite(part["z"])).sum())
        data_type = "+".join(sorted({str(p) for p in part["pub"] if p})) or "unknown"
        note = [] if good else ["No finite X, Y, Z in the parquet for this day."]
        if not good:
            empty.append(d)
        if not args.dry_run:
            raw = render_day(d, part["times"], part["x"], part["y"], part["z"], part["f"], code=code,
                             latitude=lat, longitude=lon, elevation=elev, data_type=data_type,
                             station_name=known.get("name", code), source=known.get("source", ""),
                             comments=comments + note)
            write_day(path, raw, fetched)
        written.append(d)
        print(f"  {d} {verb}: {b - a} row(s), {good} of {SECONDS_PER_DAY} s with X Y Z, {data_type}")
    print(f"  {verb}: {day_ranges(written)}")
    print(f"  kept (already in the cache): {day_ranges(kept)}")
    print(f"  {verb} all missing (no finite X, Y, Z): {day_ranges(empty)}")
    print(f"  skipped (no row in the parquet): {day_ranges(absent)}")
    if args.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
