"""INTERMAGNET one-second observatory data: a day cache from the GIN, a gap-filling loader, an MTH5 archive.

An observatory is a remote reference that reaches the long periods: far from the survey, quiet, and
recording for as long as anyone likes. INTERMAGNET's one-second records come from the BGS GIN
(`GIN_BASE`), one request per UTC day, as IAGA-2002 text in geographic XYZF, best available
publication state (definitive where it exists, else quasi-definitive, else provisional or
variation; each day's own `Data Type` header line says which it is).

Ported from the AusLAMP-Processing-2026 repository's auslamp_proc/observatory.py (itself from the
2025 GICs paper's fetch_observatory_1sec.py): `gin_url`, the three-try fetch, the 88888/99999 fill
rule, the short-gap fill (`_fill_short`: gaps up to max_gap_s linear, never a gap touching either
end of the window) and the loader's scatter of rows by their own time stamps. What differs:

  the cache      one gzip file per observatory-day, holding the IAGA-2002 text exactly as the GIN
                 served it: <cache_dir>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz, the fetch time
                 in its gzip header. A day is cached when its file exists, so a re-run fetches
                 nothing already held; each file is written whole (a temporary file moved into
                 place) or not at all. The AusLAMP code keeps one parquet per observatory-year;
                 this environment has no parquet engine (neither pyarrow nor fastparquet is
                 installed or declared), a year file has to be read and rewritten for every day
                 added, and the served text is the INTERMAGNET standard format, so a parser fix
                 applies to every cached day without a re-fetch. A day the GIN serves no finite
                 X, Y, Z for is not cached and is asked for again on the next run.
  the window     whole UTC days: `load(code, start, end)` covers start's date 00:00 to the end of
                 end's date, so the loader, the cache and the archive agree on what a span is.
  the product    `to_mth5` writes an MTH5 archive in this repo's layout (mtproc.ingest): one
                 station, one run per stretch between gaps longer than max_gap_s.

The archive's channels are hx = X (geographic north), hy = Y (geographic east), hz = Z (down),
in nT at 1 Hz, with no filters: the GIN serves calibrated nT, so there is nothing to remove. They
are named hx/hy/hz, not bx/by/bz, because hx hy hz is this repo's magnetic nomenclature (the
LEMI-423 and EDL readers write it, `scripts/build_stack.py` reads `hx`/`hy`, `mtproc.process`
hands aurora hx hy as its input channels); an archive named bx/by/bz instead would need a
nomenclature switch everywhere it is used as a remote. F is
fetched and loaded but not archived: it is the total field, not a component.

Never demeaned, detrended or rotated here: the AusLAMP reference store turns the pair into the
window's mean-field frame at use (references.observatory_member); an MTH5 remote keeps the
geographic frame the header states.
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
    """The GIN could not be reached, or would not serve, after every try."""


# ------------------------------------------------------------------ the GIN


def gin_url(code: str, day) -> str:
    """The GIN request for one UTC day of one-second IAGA-2002 XYZF, best available."""
    d = pd.Timestamp(day)
    return (f"{GIN_BASE}?Request=GetData&observatoryIagaCode={code.upper()}"
            f"&dataStartDate={d:%Y-%m-%d}&dataDuration=1&samplesPerDay=Second"
            f"&publicationState=best-avail&format=iaga2002&orientation=XYZF")


def _http_get(url: str, timeout: float = TIMEOUT_S) -> bytes:
    """The one network call (the unit test replaces it)."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def fetch_text(code: str, day, tries: int = TRIES) -> bytes:
    """One observatory-day as the GIN serves it, in `tries` attempts; raises GINError after the last."""
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
    """IAGA-2002 text -> dict(times, x, y, z, f, header, columns).

    `times` are int64 unix seconds, the row's own time stamp; x, y, z, f are float64 nT with NaN
    where the file holds 99999.00 (missing) or 88888.00 (not recorded). `header` maps each header
    line's label ("Geodetic Latitude", "Data Type", ...) to its value; comment lines are skipped.
    Raises ValueError when the data columns are not X, Y, Z (the GIN did not honour
    orientation=XYZF). An HTML page or a text with no data line gives empty arrays.
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
    """(latitude, longitude in -180..180, elevation m) from an IAGA-2002 header; None where absent.

    IAGA-2002 gives the longitude east, 0-360 (San Fernando is 354.06): it is turned into the
    -180..180 the survey.yaml sites use.
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
    t = pd.Timestamp(value)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC")
    return t.date()


def days_between(start, end) -> list[date]:
    """Every UTC calendar day from start's date to end's date, both included."""
    d0, d1 = _utc_day(start), _utc_day(end)
    if d1 < d0:
        raise ValueError(f"end {d1} is before start {d0}")
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def day_path(cache_dir, code: str, day) -> Path:
    """<cache_dir>/<CODE>/<year>/<CODE>_<YYYY-MM-DD>.sec.gz"""
    d = _utc_day(day)
    code = code.upper()
    return Path(cache_dir) / code / f"{d.year:04d}" / f"{code}_{d:%Y-%m-%d}.sec.gz"


def coverage(code: str, start, end, cache_dir) -> pd.DataFrame:
    """One row per UTC day of [start, end]: day, cached (its file exists), path, url. Reads no file."""
    rows = []
    for d in days_between(start, end):
        p = day_path(cache_dir, code, d)
        rows.append(dict(day=d, cached=p.exists(), path=p, url=gin_url(code, d)))
    return pd.DataFrame(rows, columns=["day", "cached", "path", "url"])


def _write_day(path: Path, raw: bytes, fetched: datetime) -> None:
    """The served bytes, gzipped with the fetch time in the header, moved into place whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(gzip.compress(raw, compresslevel=6, mtime=int(fetched.timestamp())))
    os.replace(tmp, path)


def read_day(path) -> dict:
    """One cached day: `parse_iaga2002` of its text, plus `fetched` (UTC datetime) and `path`."""
    with gzip.open(path, "rb") as g:
        raw = g.read()
        mtime = g.mtime
    out = parse_iaga2002(raw)
    out["fetched"] = datetime.fromtimestamp(mtime, timezone.utc) if mtime else None
    out["path"] = Path(path)
    return out


def fetch_days(code: str, start, end, cache_dir) -> list[Path]:
    """Fetch every day of [start, end] the cache does not hold; the cached day files of the span, in order.

    One GIN request per missing day, logged with its size, its sample count, its data type and the
    seconds it took. A day already cached is not asked for. A day the GIN serves no finite X, Y,
    Z for is logged and not cached. Raises GINError when the GIN cannot be had (the days fetched
    before that are kept, each whole), and ValueError when a served day is not the observatory
    asked for or not XYZ.
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
    """[start, end) index pairs of the True stretches of `bad`."""
    d = np.diff(np.r_[0, bad.astype(np.int8), 0])
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _fill_short(x, mask, max_gap):
    """Linearly fill runs of missing samples up to `max_gap` long, in place (AusLAMP's rule).

    A gap touching either end of the window is never filled: np.interp would extend the edge value
    across it. Returns (samples filled, the longest gap left, every gap's length).
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
    """One observatory's X, Y, Z, F on a 1 s grid over the whole UTC days of [start, end], from the cache.

    Returns dict(times, x, y, z, f, mask, meta): `times` datetime64[s]; x, y, z in nT with every gap
    up to max_gap_s filled by a straight line and longer ones (and any touching the window's ends)
    NaN; f as served, never filled; `mask` True where x, y and z are all real data. `meta` holds
    the header's station name and position (longitude in -180..180), each data type's sample
    count, the fetch times, the first day's GIN url, the days cached and missing, and the gap
    statistics. Raises FileNotFoundError when no day of the span is cached.
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
    """The run comment: what the values are and where they came from."""
    first, last = meta["fetched_first"], meta["fetched_last"]
    when = first.strftime(ISO) if first == last else f"{first.strftime(ISO)} .. {last.strftime(ISO)}"
    url = meta["url"]
    if len(meta["days"]) > 1:
        url += f" (one request per UTC day, {meta['days'][0]} .. {meta['days'][-1]})"
    return PROVENANCE.format(code=meta["code"], url=url, fetched=when)


def to_mth5(code: str, start, end, cache_dir, archive_path, station_id: str | None = None,
            max_gap_s: float = MAX_GAP_S, survey: str = "INTERMAGNET") -> dict:
    """Write the cached days of [start, end] as an MTH5 archive; returns dict(path, station, runs, meta).

    One station (`station_id`, default the IAGA code upper case) at the IAGA-2002 header's
    latitude, longitude and elevation, under MTH5 survey `survey` (scripts/fetch_observatory.py
    passes the survey's own name, as mtproc.ingest does for a site); channels hx = X (north),
    hy = Y (east), hz = Z (down), nT, 1 Hz, no filters; F is not written. One run
    (sr1_0001, sr1_0002, ...) per stretch between gaps longer than max_gap_s, shorter gaps filled
    by `load`. Every run's comment is the provenance line (`PROVENANCE`). An existing archive is
    replaced: it is a function of the cache alone, and a failed write leaves no partial archive.
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
            # RunTS gives its station a phantom ["auxiliary_default"]; a reader's station lists its channels
            run_ts.station_metadata.channels_recorded = list(CHANNELS)
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
    """The observatory's survey.yaml `sites:` entry, keys in scripts/new_survey.py's KEY_ORDER.

    start is the first run's first sample and end the last run's last sample plus one second (the
    end of the record, as new_survey.py writes a site's span).
    """
    end = pd.Timestamp(runs[-1]["end"]) + pd.Timedelta(seconds=1 / FS)
    fetched = meta["fetched_last"].strftime(ISO) if meta["fetched_last"] else "unknown"
    return dict(instrument="intermagnet", channels=list(CHANNELS), latitude=meta["latitude"],
                longitude=meta["longitude"], elevation=meta["elevation"], start=runs[0]["start"],
                end=end.strftime(ISO), notes=f"INTERMAGNET observatory, 1 s, fetched {fetched}")
