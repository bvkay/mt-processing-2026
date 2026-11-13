# -*- coding: utf-8 -*-
"""
Flinders Orange Box (HFM) long-period loggers: file listing, runs and the time base

The Orange Box writes one file an hour, ``HFM<n>-NNN.BIN`` (``LP<n>-NNN.BIN`` from the
MagLog 4.1 firmware, as 20 SA AusLAMP sites of 2015-2018; the same layout): a 40-byte ASCII
header (the sample count in hex, the start stamp of the logger's real-time
clock in whole seconds, the filter point in hex), fixed 21-byte records, and
a 26-byte trailer holding the end stamp. The last file of a deployment may
be left as ``.BIN.OLD`` when logging was stopped. mt-io's reader
(`mt_io.uoa.orange.read_orange`, in the mt-io fork) decodes the
samples and builds each channel's gain from the electric and magnetic full
scales and the dipole lengths; it times the samples from the first header
at the sampler's nominal rate 1e7 / (512 x filter point), 10.00064 Hz for
the filter point 7A1.

A box has two clocks: the sampler's crystal and the real-time clock (RTC)
that stamps the files, set from a handheld GPS at deployment and read
against it at recovery (the field drift, GPS minus logger, in whole
seconds). The RTC may run on local time. This module puts every run on the
UTC grid at `GRID_RATE`:

    * stamps are turned to UTC with the site's `clock_timezone` (zoneinfo);
    * T_dep is the deployment's last trailer minus its first header, in RTC
      seconds, and the RTC error grows linearly from 0 at the first header
      to `clock_drift_s` at T_dep;
    * the sampler's true rate is fs_true = N / (T_rtc + drift x T_rtc / T_dep),
      with N the records and T_rtc the RTC seconds they span at the rate
      the deployment's header stamps keep (`header_rate`, `time_base`);
    * a run's first sample is at its first header in UTC plus the RTC error
      accumulated by then, and sample k at that time plus k / fs_true;
    * the samples are resampled onto the grid points at whole multiples of
      1 / `GRID_RATE` seconds by a cubic spline (`resample_to_grid`).

That is the time base ``headers``, the default. The site key `time_base:
nominal` (`TIME_BASES`) gives the reader's own axis instead, for
comparison: each run's first
sample at its first header in UTC, the samples at the nominal rate of the
filter point, no header line, no header latency and no drift
(`clock_drift_s` is refused with it). The run comment records which.

`plan_runs` splits the files into runs where a file's header stamp is more
than `JOIN_TOLERANCE_S` from the previous file's trailer, the rule mt-io's
reader enforces (docs/upstream_issues.md 11).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from loguru import logger

HEADER_BYTES = 40
RECORD_BYTES = 21
TRAILER_BYTES = 26
STAMP_FORMAT = "%a %b %d %H:%M:%S %Y"
# a file joins the one before when its header is within this of the previous trailer: the stamps
# are whole RTC seconds, and mt-io's reader refuses a list that does not join at this tolerance
JOIN_TOLERANCE_S = 2.0
# the rate of the archive: every run is resampled onto the UTC grid at this rate
GRID_RATE = 10.0
# the full scales the Orange Box chain has been met with (docs/upstream_issues.md 13 and 14)
ELECTRIC_FULL_SCALES_UV = (25000.0, 100000.0)
MAGNETIC_FULL_SCALES_NT = (70000.0, 100000.0)
# HFM<n>- (MagLog 3.50, Persistor CF1) or LP<n>- (MagLog 4.1, CF2): group 1 is the box number either way
ORANGE_NAME = re.compile(r"^(?:HFM|LP)(\d+)-(\d+)\.BIN(\.OLD)?$", re.IGNORECASE)
REPORT_NAME = re.compile(r"^(?:HFM|LP)(\d+)-RPT\.TXT$", re.IGNORECASE)
REPORT_BOX = re.compile(r"High Frequency Magnetometer Number\s+(\d+)", re.IGNORECASE)
# start of the run comment line `time_base_note` writes and `parse_time_base_note` reads; one
# "key: value" piece with no dot in the key and no semicolon (the EMTF XML writer splits run
# comments on ";" and the first ":")
TIME_BASE_PREFIX = "orangebox_time_base: "
RESAMPLE_METHOD = "cubic spline (scipy CubicSpline not-a-knot) on the counts, no anti-alias stage"
# the time bases a site may declare (`time_base`): the header-stamp line with the field drift (the
# default), or the reader's nominal axis (first header, nominal rate, nothing else)
TIME_BASES = ("headers", "nominal")
_NS = 1_000_000_000


def is_orange_name(path: Path) -> bool:
    """Return whether a file name is an Orange Box data file (``HFM<n>-NNN.BIN`` or ``LP<n>-NNN.BIN``, or ``.BIN.OLD``)."""
    name = Path(path).name
    return not name.startswith("._") and ORANGE_NAME.match(name) is not None


def _parse_stamp(text: str) -> datetime | None:
    """Return a naive datetime from an Orange Box stamp ("Tue May  2 14:56:00 2006"), None if it does not parse."""
    try:
        return datetime.strptime(" ".join(text.split()), STAMP_FORMAT)
    except ValueError:
        return None


def read_header(path: Path) -> dict | None:
    """Read an Orange Box file's 40-byte header.

    Args:
        path (Path): A data file.

    Returns:
        dict or None: ``count`` (records the header claims), ``stamp``
        (naive datetime on the logger's clock), ``filter_point`` and
        ``rate`` (1e7 / (512 x filter point), Hz); None for an empty file
        or a header that does not parse as one.
    """
    with open(path, "rb") as f:
        head = f.read(HEADER_BYTES)
    if len(head) < HEADER_BYTES:
        return None
    text = head.decode("ascii", errors="replace")
    lines = text.split("\n")
    if len(lines) < 3:
        return None
    try:
        count = int(lines[0].strip(), 16)
        filter_point = int(lines[2].strip(), 16)
    except ValueError:
        return None
    stamp = _parse_stamp(lines[1])
    if stamp is None or filter_point <= 0:
        return None
    return {"count": count, "stamp": stamp, "filter_point": filter_point,
            "rate": 1e7 / (512 * filter_point)}


def read_trailer(path: Path) -> datetime | None:
    """Read the end stamp from a file's last 26 bytes.

    mt-io reads the trailer after the header's count of records, which in
    a partial last file falls one record short of it (docs/upstream_issues.md
    101); the last 26 bytes hold it in every file that has one.

    Args:
        path (Path): A data file.

    Returns:
        datetime or None: The naive stamp, or None when the file has no
        readable trailer.
    """
    path = Path(path)
    size = path.stat().st_size
    if size < HEADER_BYTES + TRAILER_BYTES:
        return None
    with open(path, "rb") as f:
        f.seek(size - TRAILER_BYTES)
        tail = f.read(TRAILER_BYTES)
    return _parse_stamp(tail.decode("ascii", errors="replace"))


def count_records(path: Path, has_trailer: bool) -> int:
    """Return the records a file holds, from its size.

    Args:
        path (Path): A data file.
        has_trailer (bool): Whether its last 26 bytes are a trailer.

    Returns:
        int: (size - header - trailer) // 21.
    """
    body = Path(path).stat().st_size - HEADER_BYTES - (TRAILER_BYTES if has_trailer else 0)
    return max(0, body // RECORD_BYTES)


def to_utc_ns(stamp: datetime, zone: str) -> int:
    """Return a logger stamp in UTC nanoseconds, read on the clock's zone.

    Args:
        stamp (datetime): Naive stamp as the logger wrote it.
        zone (str): IANA name of the zone the logger's clock ran on.

    Returns:
        int: UTC nanoseconds since the epoch.
    """
    aware = stamp.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
    return int(round(aware.timestamp())) * _NS


@dataclass
class OrangeFile:
    """One Orange Box data file as listed: its header, trailer and record count.

    Attributes:
        path (Path): The file.
        count (int): Records the header claims.
        records (int): Records the file holds (from its size).
        stamp (datetime): Header stamp on the logger clock (naive).
        trailer (datetime or None): Trailer stamp on the logger clock.
        rate (float): Nominal rate from the filter point, Hz.
    """

    path: Path
    count: int
    records: int
    stamp: datetime
    trailer: datetime | None
    rate: float

    @property
    def end(self) -> datetime:
        """The trailer, or the header plus the records at the nominal rate when it has none."""
        if self.trailer is not None:
            return self.trailer
        from datetime import timedelta
        return self.stamp + timedelta(seconds=self.records / self.rate)


@dataclass
class OrangeRun:
    """Files of one run: each starts within `JOIN_TOLERANCE_S` of the previous one's trailer.

    Attributes:
        files (list of OrangeFile): The files, in time order.
    """

    files: list[OrangeFile] = field(default_factory=list)

    @property
    def start(self) -> datetime:
        """First header stamp (logger clock)."""
        return self.files[0].stamp

    @property
    def end(self) -> datetime:
        """Last trailer stamp (logger clock), or its stand-in (`OrangeFile.end`)."""
        return self.files[-1].end

    @property
    def records(self) -> int:
        """Records the run's files hold."""
        return sum(f.records for f in self.files)

    @property
    def paths(self) -> list[Path]:
        """The run's file paths."""
        return [f.path for f in self.files]


def orange_files(paths: list[Path]) -> tuple[list[OrangeFile], list[str]]:
    """Describe Orange Box files, sorted by header stamp.

    The order is the header stamps', not the names': two report series can
    share a folder (Kalgoorlie Kal019: box 4's HFM4-000.BIN, empty, beside
    box 2's HFM0 files). An empty file or one whose header does not parse
    is left out and named.

    Args:
        paths (list of Path): Data files (`is_orange_name`).

    Returns:
        tuple: (list of OrangeFile in stamp order, list of str naming each
        file left out and why).
    """
    out, skipped = [], []
    for path in paths:
        path = Path(path)
        if path.stat().st_size == 0:
            skipped.append(f"{path.name} (empty)")
            continue
        head = read_header(path)
        if head is None:
            skipped.append(f"{path.name} (header does not parse)")
            continue
        trailer = read_trailer(path)
        out.append(OrangeFile(path=path, count=head["count"], records=count_records(path, trailer is not None),
                              stamp=head["stamp"], trailer=trailer, rate=head["rate"]))
    out.sort(key=lambda f: (f.stamp, str(f.path)))
    return out, skipped


def plan_runs(files: list[OrangeFile]) -> list[OrangeRun]:
    """Split a site's files into runs at stamp gaps.

    A file starts a new run where its header stamp differs from the
    previous file's trailer (`OrangeFile.end`) by more than
    `JOIN_TOLERANCE_S`, or its rate differs. Kalgoorlie Kal017 (five
    hourly files missing) gives two runs.

    Args:
        files (list of OrangeFile): The files in stamp order.

    Returns:
        list of OrangeRun: The runs.
    """
    runs: list[OrangeRun] = []
    for f in files:
        if runs:
            prev = runs[-1].files[-1]
            step = (f.stamp - prev.end).total_seconds()
            if abs(step) <= JOIN_TOLERANCE_S and f.rate == prev.rate:
                runs[-1].files.append(f)
                continue
        runs.append(OrangeRun(files=[f]))
    return runs


def header_rate(runs: list[OrangeRun]) -> tuple[float | None, float]:
    """Return the samples per RTC second and the header latency from the deployment's header stamps.

    A least-squares line through every header stamp against the index of
    the file's first record within its run, one slope for the deployment
    and one intercept per run. The deployment's first and last files are
    left out: at every Kalgoorlie site the first header lies about 1 s, and
    the last (the file logging was stopped in) 1 to 2 s, off the line the
    other headers keep to within 0.3 s. Trailers are
    not used: each is a whole second stamped 1 to 3 s before the next
    header, and the last one up to 2 s short of the samples before it.

    The first header is the logging start, at a whole minute ("Logging
    started at" in the report), and the samples follow it. Every later
    header is stamped when its file is opened, after the previous file is
    closed, while the samples wait in the logger's FIFO (4096 bytes, 19 s
    at 10 Hz): it lies the latency (1.0 to 2.5 s at Kalgoorlie) after its
    file's first sample, the intercept of the line minus the first header.

    Args:
        runs (list of OrangeRun): The deployment's runs.

    Returns:
        tuple: (records per RTC second, the header latency in s: the line's
        intercept for the first run minus the first header), or (None, 0.0)
        when fewer than three headers remain or the first run has none in
        the fit.
    """
    first = runs[0].start
    rows, stamps = [], []
    for r_i, run in enumerate(runs):
        k = 0
        for f in run.files:
            rows.append((r_i, k))
            stamps.append((f.stamp - first).total_seconds())
            k += f.records
    rows, stamps = rows[1:-1], stamps[1:-1]
    if len(stamps) < 3:
        return None, 0.0
    used = sorted({r for r, _k in rows})
    design = np.zeros((len(stamps), len(used) + 1))
    for i, (r_i, k) in enumerate(rows):
        design[i, used.index(r_i)] = 1.0
        design[i, -1] = k
    solution, *_ = np.linalg.lstsq(design, np.asarray(stamps), rcond=None)
    slope = float(solution[-1])
    if slope <= 0:
        return None, 0.0
    latency = float(solution[0]) if used[0] == 0 else 0.0
    return 1.0 / slope, latency


def time_base(runs: list[OrangeRun], zone: str, drift_s: float | None, mode: str = "headers") -> list[dict]:
    """Return each run's time base: its true sampler rate and the UTC time of its first sample.

    With `mode` "nominal" the reader's own axis is returned instead: each
    run's first sample at its first header in UTC, the rate the filter
    point gives (``OrangeFile.rate``, 1e7 / (512 x 1953) = 10.00064 Hz at
    Kalgoorlie), no header line, latency or drift (``rate_from``
    "nominal"); `drift_s` must then be None. The rest of this docstring is
    the default, "headers".

    T_dep is the deployment's last trailer minus its first header (RTC
    seconds). The RTC error, GPS minus logger, grows linearly from 0 at the
    first header to `drift_s` at the last trailer. A
    run's N records span T_rtc = N / fs_rtc RTC seconds, with fs_rtc the
    records per RTC second of the deployment's header stamps
    (`header_rate`), and the sampler's true rate is
    fs_true = N / (T_rtc + drift x T_rtc / T_dep) = fs_rtc / (1 + drift / T_dep).
    Where `header_rate` has too few headers, T_rtc is the run's last trailer
    minus its first header, pooled over the runs. The stamps' own span
    (last trailer minus first header) and the rate it gives are returned
    beside it as ``t_stamps`` and ``fs_stamps``. The first run's first
    sample is at its first header in UTC (the logging start); a later run's
    first header is a file's opening stamp, so its first sample is at that
    stamp less the header latency (`header_rate`; Kalgoorlie Kal021's
    second run starts 0.45 s after its first ends). The RTC error accumulated
    by then is added to each.

    Args:
        runs (list of OrangeRun): The deployment's runs.
        zone (str): IANA name of the logger clock's zone.
        drift_s (float or None): GPS minus logger at recovery, seconds;
            None when it was not recorded (then 0.0, and the record says so).
        mode (str): One of `TIME_BASES`: "headers" (the default) or
            "nominal".

    Returns:
        list of dict: Per run ``t_rtc`` (s), ``n`` (records), ``fs_rtc``,
        ``fs_true``, ``fs_stamps`` (Hz), ``t_stamps``, ``t_dep`` (s),
        ``rate_from`` ("headers", "stamps" or "nominal"), ``drift_s``,
        ``drift_recorded``, ``rtc_error_s`` (the RTC error at the run's first
        header), ``latency_s`` (the header latency taken off the run's first
        header, 0.0 for the first run), ``start_ns`` (UTC ns of its first
        sample) and ``time_base`` (`mode`).

    Raises:
        ValueError: If the deployment or a run spans no RTC time, `mode` is
            not one of `TIME_BASES`, or `mode` is "nominal" with a drift.
    """
    if mode not in TIME_BASES:
        raise ValueError(f"Orange Box time_base {mode!r}: expected one of {', '.join(TIME_BASES)}")
    if mode == "nominal" and drift_s is not None:
        raise ValueError(f"Orange Box time_base nominal with clock_drift_s {drift_s!r}: the nominal axis applies "
                         f"no drift; remove one of the two keys")
    drift = 0.0 if drift_s is None else float(drift_s)
    first, last = runs[0].start, runs[-1].end
    t_dep = (last - first).total_seconds()
    if t_dep <= 0:
        raise ValueError(f"Orange Box deployment span {t_dep} s from {first} to {last}: not positive")
    t_stamps = [(r.end - r.start).total_seconds() for r in runs]
    n = [r.records for r in runs]
    if any(t <= 0 for t in t_stamps):
        bad = [r.files[0].path.name for r, t in zip(runs, t_stamps) if t <= 0]
        raise ValueError(f"Orange Box run(s) starting {bad} span no RTC time")
    if mode == "nominal":
        # the reader's own axis: each run from its first header at the filter point's rate
        out = []
        for run, t, k in zip(runs, t_stamps, n):
            rate = run.files[0].rate
            out.append({"latency_s": 0.0, "t_rtc": k / rate, "n": k, "fs_rtc": rate, "fs_true": rate, "t_stamps": t,
                        "fs_stamps": k / t, "t_dep": t_dep, "rate_from": "nominal", "drift_s": 0.0,
                        "drift_recorded": False, "rtc_error_s": 0.0, "start_ns": to_utc_ns(run.start, zone),
                        "time_base": mode})
        return out
    scale = 1.0 + drift / t_dep
    fs_rtc, latency = header_rate(runs)
    rate_from = "headers"
    if fs_rtc is None:
        fs_rtc, rate_from = sum(n) / sum(t_stamps), "stamps"
    fs_true = fs_rtc / scale
    out = []
    for index, (run, t, k) in enumerate(zip(runs, t_stamps, n)):
        late = latency if index else 0.0
        error = drift * (run.start - first).total_seconds() / t_dep
        out.append({"latency_s": late, "t_rtc": k / fs_rtc, "n": k, "fs_rtc": fs_rtc, "fs_true": fs_true, "t_stamps": t,
                    "fs_stamps": k / (t * scale), "t_dep": t_dep, "rate_from": rate_from, "drift_s": drift,
                    "drift_recorded": drift_s is not None, "rtc_error_s": error,
                    "start_ns": to_utc_ns(run.start, zone) + int(round((error - late) * _NS)), "time_base": mode})
    return out


def grid_points(start_ns: int, n: int, fs_true: float, rate: float = GRID_RATE) -> tuple[int, int]:
    """Return the first grid point and the number of grid points that n samples from start_ns cover.

    The arithmetic of `resample_to_grid`, which calls it, so that a run's
    place on the grid can be known without reading its samples
    (`grid_span`, used by the Orange Box `h_from` plan of
    `mt_workbench.ingest`).

    Args:
        start_ns (int): UTC ns of sample 0.
        n (int): Number of samples.
        fs_true (float): The samples' true rate, Hz.
        rate (float): The grid's rate, Hz.

    Returns:
        tuple: (UTC ns of the first grid point, number of grid points).

    Raises:
        ValueError: If no grid point falls within the samples.
    """
    step = int(round(_NS / rate))
    last_ns = start_ns + (n - 1) / fs_true * _NS
    first_grid = -(-start_ns // step) * step  # ceiling to the grid
    last_grid = int(math.floor(last_ns / step)) * step
    if last_grid < first_grid:
        raise ValueError("no grid point falls within the samples")
    return first_grid, (last_grid - first_grid) // step + 1


def grid_span(run: OrangeRun, base: dict, rate: float = GRID_RATE) -> tuple[int, int]:
    """Return where `read_orangebox_run` will put a run on the grid, without reading it.

    The reader returns each file's header count, or its records where
    fewer (the samples `read_orangebox_run` checks it returns), placed at
    the run's time base and resampled by `resample_to_grid`.

    Args:
        run (OrangeRun): The run's files.
        base (dict): Its `time_base` entry.
        rate (float): The grid's rate, Hz.

    Returns:
        tuple: (UTC ns of the run's first grid sample, its number of grid
        samples).
    """
    n = sum(min(f.count, f.records) for f in run.files)
    return grid_points(base["start_ns"], n, base["fs_true"], rate)


def resample_to_grid(data: dict[str, np.ndarray], start_ns: int, fs_true: float,
                     rate: float = GRID_RATE) -> tuple[int, dict[str, np.ndarray]]:
    """Resample samples taken at start + k / fs_true onto the grid at whole multiples of 1 / rate.

    A cubic spline (scipy's CubicSpline, not-a-knot ends) is fitted to each
    channel against the sample index and evaluated at the grid points'
    fractional indices. Grid points outside the samples are dropped. There
    is no anti-alias stage: the step from 10.00064 Hz to 10 Hz moves the
    Nyquist frequency by 64 ppm, and a fluxgate record carries nothing near
    5 Hz.

    Args:
        data (dict): Channel name to its samples (any numeric dtype), all
            the same length.
        start_ns (int): UTC ns of sample 0.
        fs_true (float): The samples' true rate, Hz.
        rate (float): The grid's rate, Hz; 1e9 / rate must be a whole
            number of ns.

    Returns:
        tuple: (UTC ns of the first grid point, dict of float32 arrays on
        the grid).

    Raises:
        ValueError: If there are fewer than four samples or no grid point
            falls within them.
    """
    from scipy.interpolate import CubicSpline

    step = int(round(_NS / rate))
    n = len(next(iter(data.values())))
    if n < 4:
        raise ValueError(f"{n} samples: too few for a cubic spline")
    first_grid, count = grid_points(start_ns, n, fs_true, rate)
    # fractional sample index of each grid point; offsets in ns stay below 2**53 for 100 days
    u = (first_grid - start_ns + np.arange(count, dtype=np.float64) * step) * (fs_true / _NS)
    index = np.arange(n, dtype=np.float64)
    out = {}
    for name, values in data.items():
        spline = CubicSpline(index, np.asarray(values, dtype=np.float64), bc_type="not-a-knot")
        out[name] = spline(u).astype(np.float32)
    return first_grid, out


def _iso(ns: int) -> str:
    """Return UTC ns as an ISO string to the tenth of a second."""
    whole, frac = divmod(int(ns), _NS)
    return datetime.fromtimestamp(whole, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{frac // 100_000_000}Z"


def time_base_note(base: dict, zone: str, first_ns: int, last_ns: int, files: list[str]) -> str:
    """Return the run comment line recording a run's time base and resample.

    Args:
        base (dict): The run's `time_base` entry.
        zone (str): The logger clock's zone.
        first_ns (int): UTC ns of the first grid sample.
        last_ns (int): UTC ns of the last grid sample.
        files (list of str): The run's first and last file names.

    Returns:
        str: One line, "orangebox_time_base: clock_timezone=... ...".
    """
    mode = base.get("time_base", "headers")
    if mode == "nominal":
        drift = "0.0 (not applied)"
    else:
        drift = f"{base['drift_s']!r}" if base["drift_recorded"] else "0.0 (drift unrecorded)"
    return (f"{TIME_BASE_PREFIX}clock_timezone={zone} clock_drift_s={drift} time_base={mode} "
            f"t_rtc_s={base['t_rtc']:.1f} t_dep_s={base['t_dep']:.0f} n={base['n']} "
            f"fs_rtc_hz={base['fs_rtc']:.7f} rate_from={base['rate_from']} fs_true_hz={base['fs_true']:.7f} "
            f"t_stamps_s={base['t_stamps']:.0f} fs_stamps_hz={base['fs_stamps']:.7f} "
            f"rtc_error_at_start_s={base['rtc_error_s']:.3f} header_latency_s={base['latency_s']:.3f} "
            f"grid_hz={GRID_RATE:g} "
            f"grid_first={_iso(first_ns)} grid_last={_iso(last_ns)} files={files[0]}..{files[-1]} "
            f"resample={RESAMPLE_METHOD}")


def parse_time_base_note(comment: str) -> dict | None:
    """Read the `time_base_note` line back from a run comment.

    Args:
        comment (str): A run comment.

    Returns:
        dict or None: ``clock_timezone`` (str), ``clock_drift_s`` (float),
        ``drift_recorded`` (bool), ``t_rtc_s``, ``t_dep_s``, ``fs_rtc_hz``,
        ``fs_true_hz``, ``t_stamps_s``, ``fs_stamps_hz``,
        ``rtc_error_at_start_s``, ``header_latency_s``, ``grid_hz``
        (floats), ``n`` (int),
        ``rate_from``, ``grid_first``, ``grid_last``, ``files``,
        ``resample`` and ``time_base`` (str; "headers" for a line written
        before the key existed); None when the comment has no such line.
    """
    for line in str(comment or "").split("; "):
        if not line.startswith(TIME_BASE_PREFIX):
            continue
        body = line[len(TIME_BASE_PREFIX):]
        body, _, resample = body.partition(" resample=")
        out: dict = {"resample": resample, "time_base": "headers",
                     "drift_recorded": "(drift unrecorded)" not in body and "(not applied)" not in body}
        body = body.replace(" (drift unrecorded)", "").replace(" (not applied)", "")
        for piece in body.split():
            key, _, value = piece.partition("=")
            if key in ("clock_timezone", "grid_first", "grid_last", "files", "rate_from", "time_base"):
                out[key] = value
            elif key == "n":
                out[key] = int(value)
            elif key:
                out[key] = float(value)
        return out
    return None


def report_box(site_dir: Path, prefix: str | None = None) -> str | None:
    """Return the box named by a site's logger report, as the survey writes it ("hfm2").

    The report ``HFM<n>-RPT.TXT`` (``LP<n>-RPT.TXT``) opens with "High Frequency Magnetometer
    Number <n>"; number 0 is box 2, which writes its files as HFM0. With
    several reports in a folder (Kalgoorlie Kal019) the one of the data
    files' prefix is read.

    Args:
        site_dir (Path): Site folder.
        prefix (str, optional): The data files' number, "0" for HFM0-*.BIN.

    Returns:
        str or None: "hfm<box>", or None when no report names one.
    """
    reports = sorted(p for p in Path(site_dir).iterdir() if REPORT_NAME.match(p.name))
    if prefix is not None:
        reports = [p for p in reports if REPORT_NAME.match(p.name).group(1) == prefix] or reports
    for report in reports:
        with open(report, "rb") as f:
            first = f.read(200).decode("ascii", errors="replace")
        found = REPORT_BOX.search(first)
        if found:
            number = int(found.group(1))
            return f"hfm{2 if number == 0 else number}"
    return None


def read_orangebox_run(run: OrangeRun, base: dict, site, zone: str):
    """Read one run through mt-io and return it on the UTC grid.

    mt-io's `read_orange` is given the run's files, the site's dipole
    lengths (exchanged for a site declared `swap_e`, so that each chain
    follows its samples through `mt_workbench.ingest._swap_e`), its full
    scales and position. Its samples (counts, with the chain as the
    reader builds it: 2**23 / FS_nT on hx and hz, -2**23 / FS_nT on hy,
    -2**23 x L / FS_uV on ex and ey) are placed at the run's time base
    (`time_base`) and resampled onto the grid (`resample_to_grid`); the
    chain is not changed. ex and ey take the site's azimuths modulo 180 deg
    (a line laid at 180 or 270 deg is the reversed pair, flipped by
    `mt_workbench.ingest._standardise_e_orientation`) and dipole lengths;
    hx, hy and hz the sensor axes (0, 90 and down). The run comment holds
    `time_base_note`, and the run's timing system says it is a free-running
    RTC (docs/upstream_issues.md 103).

    Args:
        run (OrangeRun): The run's files.
        base (dict): Its `time_base` entry.
        site (SiteConfig): Site settings.
        zone (str): The logger clock's zone.

    Returns:
        RunTS: The run at `GRID_RATE`.

    Raises:
        ValueError: If the reader returns other than the run's records less
            at most the last file's one extra record, or a file other than
            the last holds other than its header's count.
    """
    from mt_io.uoa.orange import read_orange
    from mt_timeseries import ChannelTS
    from mt_timeseries.run_ts import RunTS

    for f in run.files[:-1]:
        if f.records != f.count:
            raise ValueError(f"{site.name}: {f.path.name} holds {f.records} records and its header says "
                             f"{f.count}: mt-io reads the header's count, so every later sample of the run "
                             f"would be misplaced")
    length_ex, length_ey = float(site.dipole_length_ex), float(site.dipole_length_ey)
    if site.swap_e:
        length_ex, length_ey = length_ey, length_ex
    kwargs = dict(station_id=site.name, dipole_length_ex=length_ex, dipole_length_ey=length_ey,
                  electric_full_scale_uv=float(site.electric_full_scale_uv),
                  magnetic_full_scale_nt=float(site.magnetic_full_scale_nt))
    kwargs.update({k: float(getattr(site, k)) for k in ("latitude", "longitude", "elevation")
                   if getattr(site, k, None) is not None})
    raw = read_orange([str(p) for p in run.paths], **kwargs)
    n_read = raw.dataset.sizes["time"]
    expected = sum(min(f.count, f.records) for f in run.files)
    if n_read != expected:
        raise ValueError(f"{site.name}: mt-io returned {n_read} samples from {len(run.files)} file(s), the "
                         f"files hold {run.records} records ({expected} by the headers' counts)")
    names = list(raw.dataset.data_vars)
    first_ns, grid = resample_to_grid({c: raw.dataset[c].values for c in names}, base["start_ns"], base["fs_true"])
    last_ns = first_ns + (len(grid[names[0]]) - 1) * int(round(_NS / GRID_RATE))
    start_iso = _iso(first_ns).replace("Z", "+00:00")
    end_iso = _iso(last_ns).replace("Z", "+00:00")
    frame = {"ex": float(site.azimuth_ex) % 180.0, "ey": float(site.azimuth_ey) % 180.0}
    axes = {"hx": (0.0, 0.0), "hy": (90.0, 0.0), "hz": (0.0, 90.0)}
    channels = []
    for comp in names:
        old = getattr(raw, comp)
        md = old.channel_metadata.copy()
        md.sample_rate = GRID_RATE
        md.time_period.start = start_iso
        md.time_period.end = end_iso
        if comp in axes:
            md.measurement_azimuth, md.measurement_tilt = axes[comp]
        elif comp in frame:
            md.measurement_azimuth, md.measurement_tilt = frame[comp], 0.0
            md.dipole_length = float(site.dipole_length_ex if comp == "ex" else site.dipole_length_ey)
        channels.append(ChannelTS(old.channel_metadata.type, data=grid[comp], channel_metadata=md,
                                  channel_response=old.channel_response))
    run_md = raw.run_metadata.copy()
    for key in list(run_md.channels.keys()):
        run_md.channels.remove(key)
    for attr in ("channels_recorded_magnetic", "channels_recorded_electric", "channels_recorded_auxiliary"):
        setattr(run_md, attr, [])
    run_md.sample_rate = GRID_RATE
    run_md.time_period.start = start_iso
    run_md.time_period.end = end_iso
    note = time_base_note(base, zone, first_ns, last_ns, [run.files[0].path.name, run.files[-1].path.name])
    run_md.comments.value = note
    timing = run_md.data_logger.timing_system
    timing.type = "internal real-time clock (free-running)"
    timing.drift = float(base["drift_s"])
    if base.get("time_base", "headers") == "nominal":
        state = "nominal time base: first header at the filter point's rate, no drift or header line applied"
    else:
        state = "drift unrecorded" if not base["drift_recorded"] else "drift = GPS minus logger at recovery"
    timing.comments = "RTC set from a handheld GPS at deployment and read against it at recovery; " + state
    station_md = raw.station_metadata.copy()
    for key in list(station_md.runs.keys()):
        station_md.runs.remove(key)
    station_md.channels_recorded = []
    # the reader dates the station on the logger clock read as UTC; the run's grid replaces it
    station_md.time_period.start = start_iso
    station_md.time_period.end = end_iso
    out = RunTS(array_list=channels, run_metadata=run_md, station_metadata=station_md)
    logger.info(f"{site.name}: {len(run.files)} Orange Box file(s) {run.files[0].path.name}..{run.files[-1].path.name}: "
                f"{n_read} samples at fs_true {base['fs_true']:.6f} Hz -> {len(grid[names[0]])} at {GRID_RATE:g} Hz "
                f"from {_iso(first_ns)}")
    return out
