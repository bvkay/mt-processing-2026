# -*- coding: utf-8 -*-
"""
INTERMAGNET one-second observatory data

A day cache filled from the BGS GIN, a gap-filling loader and an MTH5
archive writer. An observatory serves as a remote reference for the long
periods: it is far from the survey, quiet, and records continuously.
INTERMAGNET one-second records come from the BGS GIN (`GIN_BASE`), one
request per UTC day, as IAGA-2002 text in geographic XYZF at the best
available publication state (definitive where it exists, else
quasi-definitive, else provisional or variation; each day's ``Data Type``
header line says which).

`gin_url`, the three-try fetch, the 88888/99999 fill rule, the short-gap
fill (`_fill_short`: gaps up to max_gap_s filled linearly, except a gap
touching either end of the window) and the loader's placement of rows by
their own time stamps are ported from auslamp_proc/observatory.py in the
AusLAMP-Processing-2026 repository, which in turn derives from
fetch_observatory_1sec.py of the 2025 GICs paper. This module differs in:

  the cache      one gzip file per observatory-day holding the IAGA-2002 text as the GIN served
                 it: <cache_dir>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz, with the fetch time in
                 its gzip header. A day is cached when its file exists, so a re-run fetches only
                 missing days. Each file is written to a temporary name and moved into place
                 whole. Keeping the served text means a parser fix applies to every cached day
                 without a re-fetch. The AusLAMP code keeps one parquet file per
                 observatory-year instead. A day for which the GIN serves no finite X, Y, Z is
                 not cached and is requested again on the next run.
  the window     whole UTC days: `load(code, start, end)` covers 00:00 of start's date to the
                 end of end's date, so the loader, the cache and the archive share one span.
  the product    `to_mth5` writes an MTH5 archive in the layout of crust.ingest: one station,
                 one run per stretch between gaps longer than max_gap_s.

The archive channels are hx = X (geographic north), hy = Y (geographic
east) and hz = Z (down), in nT at 1 Hz with no filters, since the GIN serves
calibrated nT. The names follow the magnetic nomenclature of this package:
the LEMI-423 and EDL readers write hx hy hz, `scripts/build_stack.py` reads
hx and hy, and `crust.process` passes hx and hy to aurora as input
channels. F, the total field, is fetched and loaded but not archived.

The data are not demeaned, detrended or rotated, and an MTH5 remote keeps
the geographic frame the header states. The AusLAMP reference store rotates
the pair into the window's mean-field frame at use
(references.observatory_member).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import gzip
import io
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

GIN_BASE = "https://imag-data.bgs.ac.uk/GIN_V1/GINServices"
FS = 1.0
SECONDS_PER_DAY = 86400
FILL_AT = 88888.0  # |value| >= this is IAGA-2002's missing (99999.00) or not-recorded (88888.00)
MAX_GAP_S = 600.0  # the longest gap filled by a straight line (AusLAMP's max_gap_s)
TRIES = 3
RETRY_WAIT_S = 3.0  # waited (x the try number) after a failed try
TIMEOUT_S = 300.0  # one day of one-second text is about 8 MB, and the GIN builds it first
CHANNELS = {"hx": "x", "hy": "y", "hz": "z"}  # archive channel -> IAGA-2002 component
AZIMUTH_TILT = {"hx": (0.0, 0.0), "hy": (90.0, 0.0), "hz": (0.0, 90.0)}  # geographic, Z down
PROVENANCE = "INTERMAGNET {code} one-second, best-available, XYZF, GIN {url}, fetched {fetched}"
ISO = "%Y-%m-%dT%H:%M:%SZ"
_HEADER = re.compile(r"^ (\S(?:.*?\S)?)\s{2,}(.*?)\s*\|?\s*$")


class GINError(RuntimeError):
    """Raised when the GIN cannot be reached, or does not serve, after every try."""


# ------------------------------------------------------------------ the GIN


def gin_url(code: str, day) -> str:
    """Build the GIN request URL for one UTC day of one-second IAGA-2002 XYZF, best available.

    Args:
        code (str): IAGA observatory code.
        day: Any value pandas reads as a date.

    Returns:
        str: Request URL.
    """
    d = pd.Timestamp(day)
    return (f"{GIN_BASE}?Request=GetData&observatoryIagaCode={code.upper()}"
            f"&dataStartDate={d:%Y-%m-%d}&dataDuration=1&samplesPerDay=Second"
            f"&publicationState=best-avail&format=iaga2002&orientation=XYZF")


def _http_get(url: str, timeout: float = TIMEOUT_S) -> bytes:
    """Fetch a URL and return its body; the unit tests replace this function."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def fetch_text(code: str, day, tries: int = TRIES) -> bytes:
    """Fetch one observatory-day from the GIN.

    Failed attempts are retried after RETRY_WAIT_S times the attempt number.

    Args:
        code (str): IAGA observatory code.
        day: Any value pandas reads as a date.
        tries (int): Number of attempts.

    Returns:
        bytes: The IAGA-2002 text as served.

    Raises:
        GINError: If every attempt fails.
    """
    url = gin_url(code, day)
    last = None
    for k in range(tries):
        try:
            return _http_get(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:  # HTTPError is a URLError
            last = exc
            if k < tries - 1:
                time.sleep(RETRY_WAIT_S * (k + 1))
    reason = getattr(last, "reason", None) or last
    raise GINError(f"GIN unreachable for {code.upper()} {pd.Timestamp(day):%Y-%m-%d} after {tries} tries: "
                   f"{type(last).__name__}: {reason}")


# ----------------------------------------------------------- IAGA-2002 text


def parse_iaga2002(text: str | bytes) -> dict:
    """Parse IAGA-2002 text.

    Args:
        text (str or bytes): IAGA-2002 file content.

    Returns:
        dict: ``times`` (int64 unix seconds, each row's own time stamp,
        floored to the second), ``x``, ``y``, ``z``, ``f`` (float64 nT, NaN
        where the file holds 99999.00 for missing or 88888.00 for not
        recorded), ``header`` (each header line's label, such as
        "Geodetic Latitude" or "Data Type", mapped to its value; comment
        lines skipped) and ``columns``. An HTML page or a text with no data
        line gives empty arrays.

    Raises:
        ValueError: If the data columns are not X, Y, Z, meaning the GIN
            did not honour orientation=XYZF.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    header: dict[str, str] = {}
    columns: list[str] = []
    rows: list[str] = []
    if "<html" not in text[:400].lower():
        for line in text.splitlines():
            if not line.strip():
                continue
            if line.startswith("DATE"):
                columns = line.replace("|", " ").split()
            elif line[0].isdigit():
                rows.append(line)
            elif line[0] == " " and not line.lstrip().startswith("#"):
                m = _HEADER.match(line)
                if m:
                    header[m.group(1)] = m.group(2)
    if not rows:
        empty = np.zeros(0)
        return dict(times=np.zeros(0, np.int64), x=empty, y=empty.copy(), z=empty.copy(), f=empty.copy(),
                    header=header, columns=columns)
    comps = [c[-1].upper() for c in columns[3:7]] if len(columns) >= 7 else []
    if comps[:3] != ["X", "Y", "Z"]:
        raise ValueError(f"IAGA-2002 columns {columns[3:7] or columns} are not X Y Z (orientation=XYZF "
                         f"not honoured; reported {header.get('Reported', '?')})")
    d = pd.read_csv(io.StringIO("\n".join(rows)), sep=r"\s+", header=None, engine="c",
                    names=["date", "time", "doy", "x", "y", "z", "f"], usecols=range(7),
                    dtype={"date": str, "time": str})
    stamp = pd.to_datetime(d["date"] + " " + d["time"], format="%Y-%m-%d %H:%M:%S.%f")
    ms = stamp.to_numpy(dtype="datetime64[ms]").astype(np.int64)
    if (ms % 1000).any():
        logger.warning(f"IAGA-2002: {int((ms % 1000 != 0).sum())} time stamp(s) off the whole second, floored")
    out = dict(times=ms // 1000, header=header, columns=columns)
    for c in ("x", "y", "z", "f"):
        v = d[c].to_numpy(dtype=float)
        out[c] = np.where(np.abs(v) >= FILL_AT, np.nan, v)
    return out


def header_position(header: dict) -> tuple[float | None, float | None, float | None]:
    """Read the position from an IAGA-2002 header.

    IAGA-2002 gives the longitude east in 0-360 (San Fernando is 354.06);
    it is converted to the -180..180 range used for survey.yaml sites.

    Args:
        header (dict): Header as returned by `parse_iaga2002`.

    Returns:
        tuple: ``(latitude, longitude, elevation_m)``, each None where absent.
    """
    def num(key):
        try:
            return float(header[key])
        except (KeyError, ValueError):
            return None

    lat, lon, elev = num("Geodetic Latitude"), num("Geodetic Longitude"), num("Elevation")
    if lon is not None:
        lon = round(((lon + 180.0) % 360.0) - 180.0, 6)
    return lat, lon, elev


# ------------------------------------------------------------------ the cache


def _utc_day(value) -> date:
    """Return the UTC calendar date of a time value."""
    t = pd.Timestamp(value)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC")
    return t.date()


def days_between(start, end) -> list[date]:
    """List every UTC calendar day from start's date to end's date, both included.

    Raises:
        ValueError: If end is before start.
    """
    d0, d1 = _utc_day(start), _utc_day(end)
    if d1 < d0:
        raise ValueError(f"end {d1} is before start {d0}")
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def day_path(cache_dir, code: str, day) -> Path:
    """Return the cache path of one day: <cache_dir>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz."""
    d = _utc_day(day)
    code = code.upper()
    return Path(cache_dir) / code / f"{d.year:04d}" / f"{code}_{d:%Y-%m-%d}.sec.gz"


def coverage(code: str, start, end, cache_dir) -> pd.DataFrame:
    """Tabulate the cache state of each UTC day of [start, end].

    Only file existence is checked.

    Args:
        code (str): IAGA observatory code.
        start: Start of the span; its UTC date is the first day.
        end: End of the span; its UTC date is the last day.
        cache_dir (str or Path): Cache root (`day_path`).

    Returns:
        pd.DataFrame: One row per day with columns ``day``, ``cached``,
        ``path`` and ``url``.
    """
    rows = []
    for d in days_between(start, end):
        p = day_path(cache_dir, code, d)
        rows.append(dict(day=d, cached=p.exists(), path=p, url=gin_url(code, d)))
    return pd.DataFrame(rows, columns=["day", "cached", "path", "url"])


def _write_day(path: Path, raw: bytes, fetched: datetime) -> None:
    """Write the served bytes gzipped, with the fetch time in the header, via a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(gzip.compress(raw, compresslevel=6, mtime=int(fetched.timestamp())))
    os.replace(tmp, path)


def read_day(path) -> dict:
    """Read one cached day.

    Returns:
        dict: `parse_iaga2002` of its text plus ``fetched`` (UTC datetime
        from the gzip header, or None) and ``path``.
    """
    with gzip.open(path, "rb") as g:
        raw = g.read()
        mtime = g.mtime
    out = parse_iaga2002(raw)
    out["fetched"] = datetime.fromtimestamp(mtime, timezone.utc) if mtime else None
    out["path"] = Path(path)
    return out


def fetch_days(code: str, start, end, cache_dir) -> list[Path]:
    """Fetch every day of [start, end] missing from the cache.

    One GIN request is made per missing day and logged with its size,
    sample count, data type and duration. A day for which the GIN serves no
    finite X, Y, Z is logged and not cached. Days fetched before an error
    stay in the cache, each file complete.

    Args:
        code (str): IAGA observatory code.
        start: Start of the span.
        end: End of the span.
        cache_dir (str or Path): Cache root.

    Returns:
        list of Path: The cached day files of the span, in order.

    Raises:
        GINError: If the GIN cannot be reached.
        ValueError: If a served day is for another observatory or is not XYZ.
    """
    code = code.upper()
    cov = coverage(code, start, end, cache_dir)
    todo = cov[~cov.cached]
    logger.info(f"{code}: {len(cov)} day(s) {cov.day.iloc[0]} .. {cov.day.iloc[-1]}, "
                f"{int(cov.cached.sum())} cached, {len(todo)} to fetch into {Path(cache_dir) / code}")
    for row in todo.itertuples():
        t0 = time.perf_counter()
        raw = fetch_text(code, row.day)
        seconds = time.perf_counter() - t0
        fetched = datetime.now(timezone.utc)
        got = parse_iaga2002(raw)
        served = got["header"].get("IAGA Code", code).strip().upper()
        if served != code:
            raise ValueError(f"{code} {row.day}: the GIN served IAGA code {served}")
        good = int((np.isfinite(got["x"]) & np.isfinite(got["y"]) & np.isfinite(got["z"])).sum())
        if not good:
            logger.warning(f"{code} {row.day}: the GIN served no data ({len(raw) / 1e6:.2f} MB, "
                           f"{seconds:.1f} s) - not cached, asked for again next run")
            continue
        _write_day(row.path, raw, fetched)
        logger.info(f"{code} {row.day}: fetched {len(raw) / 1e6:.2f} MB in {seconds:.1f} s, "
                    f"{good} of {SECONDS_PER_DAY} s with X Y Z, {got['header'].get('Data Type', '?')}")
    return [p for p in coverage(code, start, end, cache_dir).path if p.exists()]


# ------------------------------------------------------------------ the loader


def _runs(bad: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index pairs of the True stretches of a boolean array."""
    d = np.diff(np.r_[0, bad.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _fill_short(x, mask, max_gap):
    """Linearly fill runs of missing samples up to `max_gap` long, in place.

    A gap touching either end of the window is left unfilled, since
    np.interp would extend the edge value across it.

    Args:
        x (np.ndarray): Samples, modified in place.
        mask (np.ndarray): True where samples are valid.
        max_gap (int): Longest gap filled, in samples.

    Returns:
        tuple: ``(n_filled, longest_unfilled_gap, gap_lengths)``.
    """
    bad = ~mask
    if not bad.any():
        return 0, 0, []
    runs = _runs(bad)
    lens = [e - s for s, e in runs]
    fillable = np.zeros(len(x), bool)
    left = []
    for s, e in runs:
        if (e - s) <= max_gap and s > 0 and e < len(x):
            fillable[s:e] = True
        else:
            left.append(e - s)
    n_fill = int(fillable.sum())
    if n_fill and mask.any():
        idx = np.arange(len(x))
        x[fillable] = np.interp(idx[fillable], idx[mask], x[mask])
    return n_fill, (max(left) if left else 0), lens


def load(code: str, start, end, cache_dir, max_gap_s: float = MAX_GAP_S) -> dict:
    """Load an observatory's X, Y, Z, F from the cache on a 1 s grid.

    The grid covers the whole UTC days of [start, end].

    Args:
        code (str): IAGA observatory code.
        start: Start of the span.
        end: End of the span.
        cache_dir (str or Path): Cache root.
        max_gap_s (float): Longest gap filled by a straight line, in s.

    Returns:
        dict: ``times`` (datetime64[s]); ``x``, ``y``, ``z`` in nT with
        gaps up to `max_gap_s` filled linearly and longer gaps, or gaps
        touching the ends of the window, left NaN; ``f`` as served and
        unfilled; ``mask``, True where x, y and z are all recorded data;
        and ``meta``, holding the header's station name and position
        (longitude in -180..180), the sample count per data type, the fetch
        times, the first day's GIN URL, the days cached and missing, and gap
        statistics.

    Raises:
        FileNotFoundError: If no day of the span is cached.
    """
    code = code.upper()
    days = days_between(start, end)
    t0 = int(pd.Timestamp(days[0]).tz_localize("UTC").timestamp())
    n = len(days) * SECONDS_PER_DAY
    arr = {c: np.full(n, np.nan) for c in ("x", "y", "z", "f")}
    mask = np.zeros(n, bool)
    header, positions, data_types, fetched, cached, missing = {}, set(), {}, [], [], []
    for d in days:
        p = day_path(cache_dir, code, d)
        if not p.exists():
            missing.append(d.isoformat())
            continue
        got = read_day(p)
        cached.append(d.isoformat())
        header = header or got["header"]
        positions.add(header_position(got["header"]))
        if got["fetched"] is not None:
            fetched.append(got["fetched"])
        k = got["times"] - t0
        sel = (k >= 0) & (k < n)
        k = k[sel]
        for c in arr:
            arr[c][k] = got[c][sel]
        mask[k] = np.isfinite(got["x"][sel]) & np.isfinite(got["y"][sel]) & np.isfinite(got["z"][sel])
        kind = got["header"].get("Data Type", "unknown")
        data_types[kind] = data_types.get(kind, 0) + int(sel.sum())
    if not cached:
        raise FileNotFoundError(f"no {code} day of {days[0]} .. {days[-1]} is cached under {Path(cache_dir) / code}")
    if len(positions) > 1:
        logger.warning(f"{code}: the IAGA-2002 headers give {len(positions)} positions {sorted(positions)}; "
                       f"the first day's is used")
    lens, n_fill, longest = [], 0, 0
    for c in ("x", "y", "z"):
        f_, lg, ls = _fill_short(arr[c], mask, int(max_gap_s))
        n_fill, longest, lens = max(n_fill, f_), max(longest, lg), ls
    lat, lon, elev = header_position(header)
    meta = dict(
        code=code, station_name=header.get("Station Name", ""), source=header.get("Source of Data", ""),
        latitude=lat, longitude=lon, elevation=elev, reported=header.get("Reported", ""),
        sensor_orientation=header.get("Sensor Orientation", ""), data_types=data_types,
        fetched_first=min(fetched) if fetched else None, fetched_last=max(fetched) if fetched else None,
        url=gin_url(code, days[0]), days=[d.isoformat() for d in days], days_cached=cached,
        days_missing=missing, max_gap_s=float(max_gap_s),
        gaps=dict(n_missing=int((~mask).sum()), n_filled=int(n_fill), n_unfilled=int((~np.isfinite(arr["x"])).sum()),
                  n_gaps=len(lens), longest_gap_s=int(max(lens) if lens else 0), longest_unfilled_gap_s=int(longest)))
    times = (np.int64(t0) + np.arange(n, dtype=np.int64)).astype("datetime64[s]")
    return dict(times=times, x=arr["x"], y=arr["y"], z=arr["z"], f=arr["f"], mask=mask, meta=meta)


# ------------------------------------------------------------------ the archive


def provenance(meta: dict) -> str:
    """Build the run comment stating what the values are and where they came from."""
    first, last = meta["fetched_first"], meta["fetched_last"]
    when = first.strftime(ISO) if first == last else f"{first.strftime(ISO)} .. {last.strftime(ISO)}"
    url = meta["url"]
    if len(meta["days"]) > 1:
        url += f" (one request per UTC day, {meta['days'][0]} .. {meta['days'][-1]})"
    return PROVENANCE.format(code=meta["code"], url=url, fetched=when)


def to_mth5(code: str, start, end, cache_dir, archive_path, station_id: str | None = None,
            max_gap_s: float = MAX_GAP_S, survey: str = "INTERMAGNET") -> dict:
    """Write the cached days of [start, end] as an MTH5 archive.

    The archive holds one station at the latitude, longitude and elevation
    of the IAGA-2002 header, under MTH5 survey `survey`;
    scripts/fetch_observatory.py passes the survey's own name, as
    crust.ingest does for a site. Channels are hx = X (north), hy = Y
    (east) and hz = Z (down), in nT at 1 Hz with no filters; F is not
    written. There is one run (sr1_0001, sr1_0002, ...) per stretch between
    gaps longer than `max_gap_s`; shorter gaps are filled by `load`. Every
    run's comment is the provenance line (`PROVENANCE`). An existing
    archive is replaced, and a failed write removes the partial file.

    Args:
        code (str): IAGA observatory code.
        start: Start of the span.
        end: End of the span.
        cache_dir (str or Path): Cache root.
        archive_path (str or Path): Output MTH5 file.
        station_id (str, optional): Station id; the upper-case IAGA code
            when None.
        max_gap_s (float): Longest gap filled, in s.
        survey (str): MTH5 survey id.

    Returns:
        dict: ``path``, ``station``, ``runs`` (list of dicts with ``id``,
        ``start``, ``end`` and ``n``) and ``meta`` from `load`.

    Raises:
        ValueError: If no sample has X, Y and Z.
    """
    from mt_metadata.timeseries import Run, Station
    from mt_timeseries import ChannelTS, RunTS
    from mth5.mth5 import MTH5

    got = load(code, start, end, cache_dir, max_gap_s)
    meta = got["meta"]
    station_id = station_id or meta["code"]
    finite = np.isfinite(got["x"]) & np.isfinite(got["y"]) & np.isfinite(got["z"])
    stretches = _runs(finite)
    if not stretches:
        raise ValueError(f"{meta['code']}: no sample with X, Y and Z in {meta['days'][0]} .. {meta['days'][-1]}")
    logger.info(f"{meta['code']}: {meta['station_name']} at {meta['latitude']} N, {meta['longitude']} E, "
                f"{meta['elevation']} m (IAGA-2002 header); {len(stretches)} run(s), gaps {meta['gaps']}")
    comment = provenance(meta)
    path = Path(archive_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    runs = []
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(survey)
        station_group = None
        for i, (a, b) in enumerate(stretches, 1):
            run_id = f"sr{int(FS)}_{i:04d}"
            t_start = pd.Timestamp(got["times"][a]).tz_localize("UTC")
            t_end = pd.Timestamp(got["times"][b - 1]).tz_localize("UTC")
            station = Station()
            station.id = station_id
            station.location.latitude = meta["latitude"]
            station.location.longitude = meta["longitude"]
            station.location.elevation = meta["elevation"]
            station.comments.value = f"INTERMAGNET observatory {meta['station_name']} ({meta['source']})"
            run = Run()
            run.id = run_id
            run.sample_rate = FS
            run.comments.value = comment
            channels = []
            for comp, iaga in CHANNELS.items():
                ch = ChannelTS("magnetic")
                ch.channel_metadata.units = "nT"
                ch.channel_metadata.measurement_azimuth, ch.channel_metadata.measurement_tilt = AZIMUTH_TILT[comp]
                ch.channel_metadata.comments.value = (f"INTERMAGNET {meta['code']} geographic {iaga.upper()}, nT as "
                                                      f"served (no filters)")
                ch.sample_rate = FS
                ch.start = t_start.isoformat()
                ch.ts = got[iaga][a:b]
                ch.component = comp
                channels.append(ch)
            run_ts = RunTS(array_list=channels, station_metadata=station, run_metadata=run)
            run_ts.run_metadata.comments.value = comment
            if station_group is None:
                station_group = m.add_station(station_id, survey=survey)
                station_group.metadata.update(run_ts.station_metadata)
                station_group.write_metadata()
            station_group.add_run(run_id).from_runts(run_ts)
            runs.append(dict(id=run_id, start=t_start.strftime(ISO), end=t_end.strftime(ISO), n=int(b - a)))
            logger.info(f"{station_id}: run {run_id} {runs[-1]['start']} .. {runs[-1]['end']} ({b - a} s)")
        station_group.update_metadata()
    except BaseException:
        m.close_mth5()
        path.unlink(missing_ok=True)
        raise
    m.close_mth5()
    return dict(path=path, station=station_id, runs=runs, meta=meta)


def survey_entry(meta: dict, runs: list[dict]) -> dict:
    """Build the observatory's survey.yaml `sites:` entry.

    Keys follow KEY_ORDER of scripts/new_survey.py. ``start`` is the first
    run's first sample and ``end`` the last run's last sample plus one
    second, the end of the record, as new_survey.py writes a site's span.

    Args:
        meta (dict): ``meta`` from `load`.
        runs (list of dict): ``runs`` from `to_mth5`.

    Returns:
        dict: The site entry.
    """
    end = pd.Timestamp(runs[-1]["end"]) + pd.Timedelta(seconds=1 / FS)
    fetched = meta["fetched_last"].strftime(ISO) if meta["fetched_last"] else "unknown"
    return dict(instrument="intermagnet", channels=list(CHANNELS), latitude=meta["latitude"],
                longitude=meta["longitude"], elevation=meta["elevation"], start=runs[0]["start"],
                end=end.strftime(ISO), notes=f"INTERMAGNET observatory, 1 s, fetched {fetched}")
