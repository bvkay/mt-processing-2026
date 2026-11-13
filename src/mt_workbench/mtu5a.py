# -*- coding: utf-8 -*-
"""
Phoenix MTU-5A recordings: the .TBL table and the 150 Hz .TS4 band read into runs

An MTU-5A recording is a set of files sharing one stem,
``<serial><month><day><letter>`` (4573C07A: receiver 4573, 7 December, the
day's first recording; the month is 1-9, A, B or C): the table ``.TBL`` of
the receiver's settings and the recording's facts, and one time-series file
per band, ``.TS2`` (24 kHz bursts), ``.TS3`` (2400 Hz bursts) and ``.TS4``
(150 Hz, continuous). This module reads the table and the 150 Hz band; the
burst bands are left alone, with one log line per site. A site folder holds
one receiver's recordings, any number of them, each ingested as a run (or
more, where its record tags step by other than 1 s), in time order
(`plan_runs`).

The samples are mt-io's (`mt_io.phoenix.readers.MTUTSN.read`, the raw
24-bit counts, exactly those of the file). Everything else is read here,
because mt-io 0.0.5 gets it wrong (docs/upstream_issues.md):

- 551: `MTUTable` reads the position DDMM.mmm as DD.MMmmm; here degrees
  plus minutes / 60 (`table_degrees`);
- 552, 553: the series' time comes from the table's scheduled window
  (STIM), and `MTUTSN.to_runts` drops the first tag; here a run starts at
  its first record's tag (`walk_tags`);
- 554: `MTUTSN.read` stacks every record under the first tag; here the
  tags are walked and a run ends where they step by other than 1 s;
- 555, 562: `MTUTable` decodes values by a name map that ignores each
  block's type byte (LTIM, EXR and STDE misread) and keeps the trailing
  block as the key '\\x03'; here each 25-byte block is decoded by its own
  type byte and the trailer is left out (`read_table`);
- 556: a SITE with a space or "!" stops `MTUTable`; it is not used;
- 557, 558: `to_runts(calibrate=True)` scales the reader's array in place
  and labels H nanoTesla after one scalar, with no filter; `to_runts` is not
  called: the counts are stored and the scalar chain is recorded as filters;
- 564: `MTUTSN.read` drops tag bytes 14 and 15 (status, saturation); the
  walk keeps them.

When the fork reads these right, `walk_tags`, `read_table` and the run
start set here are what can go. `read_run` refuses a file whose record and
scan counts by mt-io differ from the walk's, since mt-io counts its blocks
as round(file size / first record size).

Layout [measured on the Oak Dam December 2019 files]:
  .TS4: records of a 32-byte tag and scans x channels samples, scan-major,
  3 bytes each (little-endian two's complement). Tag bytes: 0-7 second,
  minute, hour, day, month, year in the century, weekday, century; 8-9
  serial; 10-11 scans; 12 channels; 13 tag length (32); 14 status; 15
  saturation, bit (channel - 1) set when that channel reached the
  receiver's clip in the record; 17 sample length (3); 18-19 sample rate;
  20 rate units (0, Hz); 21 clock status; 22-25 clock error.
  .TBL: 25-byte blocks of the key (bytes 0-4, null-terminated), the value's
  type (byte 11: 0 int32, 1 float64, 2 and 4 text, 5 a time in the tag's
  byte order) and the value (bytes 12-24).

Time base: a run starts at its first record's tag and its records step by
1 s (150 scans at 150 Hz); a step of any other size ends the run there and
starts the next. The tag is taken as the time of the record's first scan
[inference; the EMpower .cts gives the 150 Hz band a delay of 0.196 s,
which is not applied (docs/workbench_issues.md 122)]. Refused: overlapping
recordings in one site folder, two receivers in one, a .TS4 without its
.TBL, a table whose FTIM is more than `FTIM_TOLERANCE_S` from the first
tag, recordings whose chains differ, and any record layout other than five
channels of 3-byte samples behind 32-byte tags in whole 1 s records.

Units: the archive stores the counts (int32; units "counts", which
mt_metadata keeps as "digital counts"), as the LEMI-423 path does, and
each channel's chain from the field to the counts
is recorded as applied filters, physical to recorded (`channel_chain`):
ex, ey: the dipole (mV/km to mV, gain L / 1000, negative for a line laid
reversed and read as such), EGN (mV to mV) and the converter (mV to counts,
gain 2^23 / (1000 FSCV)); hx, hy, hz: HNOM (nT to mV, the table's nominal
value, frequency independent: no coil response is applied, so Z and M from
these H are wrong and T is not affected), HATT (mV to mV), HGN (mV to mV)
and the converter. No frequency response, no H sign stage
(docs/workbench_issues.md 121) and no delay.

Saturation and tag status: the samples are stored as recorded, flagged or
not. mt-workbench records no flagged interval at ingest for any other
recorder (`mt_workbench.masks` holds the processing masks declared in
masks.yaml), so the tags' saturation bits, status byte, clock status and
clock error are written beside the archive as an interval table
(`write_flags`, ``<archive stem>.mtu5a_flags.csv``), named in the ingest
log and counted in each run's comment, both under the archive's channel
names (after `swap_e` and `swap_h`, one mapping, `_exchange`). The dc
level the ingest records in each run comment
(`mt_workbench.ingest._record_levels`) measures each channel's share of
samples against an absolute rail in counts (`rails`): RAIL_LEVEL (0.9) x
the receiver's clip `MTU5A_CLIP` (0.941 of full scale, measured) x 2^23,
as a Phoenix MTU-5C run is measured against its input rail; the rail is
recorded after the levels ("dc rail (counts, ...)"). The relative rail,
which counts a drifting channel as saturated (upstream issue 78), is not
used for this kind.

The mt-io reader is imported inside the function that uses it, so importing
this module does not load mt-io.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import csv
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from .dclevel import RAIL_LEVEL

# the band read, its rate in Hz, and the burst bands left alone
BAND = ".TS4"
BAND_RATE = 150.0
UNREAD_BANDS = (".TS2", ".TS3")
TABLE = ".TBL"
# a recording's stem: receiver serial, month (1-9, A-C), day, the day's recording letter
NAME = re.compile(r"^(\d{4})([1-9ABC])(\d{2})([A-Z])$", re.IGNORECASE)
TAG_BYTES = 32
SAMPLE_BYTES = 3
CHANNELS = ("ex", "ey", "hx", "hy", "hz")
FULL_SCALE_COUNTS = 2 ** 23
# the receiver's clip, as a fraction of full scale (2^23 counts): every clipped record of the Oak Dam
# December 2019 files is pinned at 0.941 x 2^23 counts (the quantiles of the pinned samples are
# 0.940999-0.941195 of full scale). The dc level's absolute rail is RAIL_LEVEL of it (`rails`): a pinned
# channel is counted and a drifting one is not (upstream issue 78)
MTU5A_CLIP = 0.941
# the table's channel numbers (1-5: the sample's place in a scan, the saturation bit plus 1) and coil serials
CHANNEL_KEYS = {"ex": "CHEX", "ey": "CHEY", "hx": "CHHX", "hy": "CHHY", "hz": "CHHZ"}
COIL_KEYS = {"hx": "HXSN", "hy": "HYSN", "hz": "HZSN"}
DIPOLE_KEYS = {"ex": "EXLN", "ey": "EYLN"}
REQUIRED_KEYS = ("SNUM", "FTIM", "LTIM", "FSCV", "EGN", "HGN", "HATT", "HNOM", *DIPOLE_KEYS.values(),
                 *CHANNEL_KEYS.values())
# the table values each channel's chain is built from: every recording of a site must agree on them, because
# processing takes the first run's chain for every run. The coil serials (COIL_KEYS) are not compared: no coil
# response is applied (HNOM alone), so they carry nothing numeric into the chain, and each run's coil text is
# recorded from its own recording's table (`channel_chain`, the channel's sensor id)
CHAIN_KEYS = ("FSCV", "EGN", "HGN", "HATT", "HNOM", *DIPOLE_KEYS.values(), *CHANNEL_KEYS.values())
_TABLE_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
# a table whose first-record time is further than this from the first tag is not the recording's, in seconds
FTIM_TOLERANCE_S = 1.0
# a declared dipole length that differs from the table's by more than this is logged, in m
DIPOLE_DIFF_M = 0.5
# recordings of one site folder whose table positions are further apart than this are warned about, in m
POSITION_DIFF_M = 50.0
NOMINAL_AZIMUTH = {"ex": 0.0, "ey": 90.0, "hx": 0.0, "hy": 90.0, "hz": 0.0}
# the interval table written beside the archive (`write_flags`)
FLAGS_SUFFIX = ".mtu5a_flags.csv"
FLAG_COLUMNS = ("run", "recording", "field", "channel", "input", "value", "start", "end", "records")


# ----------------------------------------------------------------------------------------------------- the table
def _table_time(raw: bytes) -> pd.Timestamp | None:
    """Return a table time (bytes in the tag's order) as a UTC Timestamp, None for an empty or invalid one."""
    second, minute, hour, day, month, year, _weekday, century = raw[:8]
    if month == 0 or day == 0:
        return None
    try:
        return pd.Timestamp(year=century * 100 + year, month=month, day=day, hour=hour, minute=minute,
                            second=second, tz="UTC")
    except ValueError:
        return None


def read_table(path: Path) -> dict:
    """Decode an MTU-5A ``.TBL`` by each block's own type byte.

    Each 25-byte block holds a key of up to four characters (bytes 0-4,
    null-terminated), the value's type (byte 11) and the value (bytes
    12-24): type 0 a little-endian int32, 1 a float64, 2 and 4 text, 5 a time
    (`_table_time`). A block whose key is not two to four capitals and digits
    (the trailing block) is left out; a type byte of another value keeps the
    13 value bytes.

    Args:
        path (Path): The table.

    Returns:
        dict: Key to value (int, float, str, pd.Timestamp or None, bytes).

    Raises:
        ValueError: If the file is not a whole number of 25-byte blocks.
    """
    path = Path(path)
    data = path.read_bytes()
    if not data or len(data) % 25:
        raise ValueError(f"{path.name}: {len(data)} bytes, not a whole number of 25-byte table blocks")
    out = {}
    for offset in range(0, len(data), 25):
        block = data[offset:offset + 25]
        key = block[:5].split(b"\x00", 1)[0].decode("latin-1")
        if not _TABLE_KEY.match(key):
            continue
        kind, raw = block[11], block[12:25]
        if kind == 0:
            value = struct.unpack("<i", raw[:4])[0]
        elif kind == 1:
            value = struct.unpack("<d", raw[:8])[0]
        elif kind in (2, 4):
            value = raw.split(b"\x00", 1)[0].decode("latin-1").strip()
        elif kind == 5:
            value = _table_time(raw)
        else:
            value = bytes(raw)
        out[key] = value
    return out


def table_degrees(text) -> float | None:
    """Return a table position, ``DDDMM.mmm,H`` (LATG ``3103.188,S``), in signed decimal degrees.

    Args:
        text: The table's value.

    Returns:
        float or None: Degrees plus minutes / 60, negative south and west;
        None when the text is not of that form.
    """
    hit = re.match(r"^\s*(\d+)(\d\d\.\d+)\s*,\s*([NSEW])\s*$", str(text or ""))
    if not hit:
        return None
    value = int(hit.group(1)) + float(hit.group(2)) / 60.0
    return -value if hit.group(3).upper() in "SW" else value


def _sibling(path: Path, suffix: str) -> Path | None:
    """Return the file beside `path` with its stem and the extension `suffix` (case ignored), or None."""
    path = Path(path)
    return next((p for p in sorted(path.parent.iterdir())
                 if p.is_file() and p.stem.upper() == path.stem.upper() and p.suffix.upper() == suffix), None)


# ------------------------------------------------------------------------------------------------- the record tags
def _tag_seconds(tags: np.ndarray, name: str) -> np.ndarray:
    """Return the UTC unix second of each 32-byte tag (rows of `tags`), refusing one that is not a time."""
    second, minute, hour, day, month, year, _weekday, century = (tags[:, k].astype(np.int64) for k in range(8))
    bad = (month < 1) | (month > 12) | (day < 1) | (day > 31) | (hour > 23) | (minute > 59) | (second > 59)
    if bad.any():
        k = int(np.flatnonzero(bad)[0])
        raise ValueError(f"{name}: the tag of record {k} is not a time (bytes {bytes(tags[k, :8]).hex()})")
    try:
        when = pd.to_datetime(pd.DataFrame({"year": century * 100 + year, "month": month, "day": day,
                                            "hour": hour, "minute": minute, "second": second}))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name}: a record tag is not a calendar time ({exc})") from None
    return when.to_numpy().astype("datetime64[s]").astype(np.int64)


def first_tag_time(path: Path) -> int:
    """Return the UTC unix second of a ``.TS4`` file's first record tag.

    Raises:
        ValueError: If the file is shorter than a tag or the tag is not a time.
    """
    path = Path(path)
    with open(path, "rb") as f:
        head = f.read(TAG_BYTES)
    if len(head) < TAG_BYTES:
        raise ValueError(f"{path.name}: {len(head)} bytes, shorter than one {TAG_BYTES}-byte record tag")
    return int(_tag_seconds(np.frombuffer(head, dtype=np.uint8).reshape(1, -1), path.name)[0])


@dataclass
class TagWalk:
    """The record tags of one ``.TS4`` file.

    Attributes:
        path (Path): The file.
        serial (int): The receiver serial every tag carries.
        scans (int): Scans per record.
        channels (int): Channels per scan.
        rate (float): Sample rate in Hz.
        record_bytes (int): Bytes per record, tag included.
        times (np.ndarray): Each record's tag, UTC unix seconds (int64).
        status (np.ndarray): Tag byte 14 per record (uint8).
        saturation (np.ndarray): Tag byte 15 per record, bit (channel - 1)
            set for a channel at the clip (uint8).
        clock_status (np.ndarray): Tag byte 21 per record (uint8).
        clock_error (np.ndarray): Tag bytes 22-25 per record (int32).
    """

    path: Path
    serial: int
    scans: int
    channels: int
    rate: float
    record_bytes: int
    times: np.ndarray
    status: np.ndarray
    saturation: np.ndarray
    clock_status: np.ndarray
    clock_error: np.ndarray

    @property
    def n(self) -> int:
        """Return the number of records."""
        return int(self.times.size)


def walk_tags(path: Path) -> TagWalk:
    """Read every record tag of a ``.TS4`` file without its samples.

    The first tag gives the layout (tag and sample length, scans, channels,
    rate); the file must be a whole number of such records, and every tag,
    read at its place in that stride, must repeat the first's serial, scans,
    channels, tag and sample lengths, rate and rate units, so that a file of
    mixed layouts is refused rather than read at the wrong offsets.

    Args:
        path (Path): The file.

    Returns:
        TagWalk: The tags.

    Raises:
        ValueError: If the tag or sample length is not 32 and 3 bytes, a
            record is not five channels of a 1 s record in Hz, the last record
            is short, a tag differs from the first in its layout, or a tag
            is not a time.
    """
    path = Path(path)
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(TAG_BYTES)
    if len(head) < TAG_BYTES:
        raise ValueError(f"{path.name}: {size} bytes, shorter than one {TAG_BYTES}-byte record tag")
    serial = int.from_bytes(head[8:10], "little")
    scans = int.from_bytes(head[10:12], "little")
    channels, tag_length, sample_length = head[12], head[13], head[17]
    rate, rate_units = int.from_bytes(head[18:20], "little"), head[20]
    if tag_length != TAG_BYTES or sample_length != SAMPLE_BYTES:
        raise ValueError(f"{path.name}: tag length {tag_length} and sample length {sample_length} bytes, where an "
                         f"MTU-5A record has a {TAG_BYTES}-byte tag and {SAMPLE_BYTES}-byte samples")
    if channels != len(CHANNELS):
        raise ValueError(f"{path.name}: {channels} channels per record; the mtu5a reader reads five-channel MT "
                         f"recordings (ex ey hx hy hz)")
    if rate_units != 0 or not rate or scans != rate:
        raise ValueError(f"{path.name}: records of {scans} scans at {rate} (rate units {rate_units}); a record of "
                         f"the continuous band is 1 s of scans at a rate in Hz (rate units 0)")
    record = TAG_BYTES + scans * channels * SAMPLE_BYTES
    n, rest = divmod(size, record)
    if rest:
        raise ValueError(f"{path.name}: {size} bytes is {n} records of {record} bytes and {rest} bytes more: the "
                         f"last record is short, and a partial record is not read")
    layout = np.dtype([("tag", np.uint8, (TAG_BYTES,)), ("samples", f"V{record - TAG_BYTES}")])
    mapped = np.memmap(path, dtype=layout, mode="r", shape=(n,))
    try:
        tags = np.array(mapped["tag"])
    finally:
        del mapped
    fixed = [8, 9, 10, 11, 12, 13, 17, 18, 19, 20]
    odd = np.flatnonzero((tags[:, fixed] != tags[0, fixed]).any(axis=1))
    if odd.size:
        k = int(odd[0])
        raise ValueError(f"{path.name}: the tag of record {k} (byte {k * record}) gives another serial, layout or "
                         f"rate than record 0: the records are not of one layout")
    error = np.ascontiguousarray(tags[:, 22:26]).view("<i4").reshape(-1)
    return TagWalk(path=path, serial=serial, scans=scans, channels=channels, rate=float(rate), record_bytes=record,
                   times=_tag_seconds(tags, path.name), status=tags[:, 14].copy(), saturation=tags[:, 15].copy(),
                   clock_status=tags[:, 21].copy(), clock_error=error.astype(np.int32))


# ---------------------------------------------------------------------------------------------------- recordings
@dataclass
class Recording:
    """One MTU-5A recording: its 150 Hz file, its table and the file's tags.

    Attributes:
        stem (str): The recording's name (4573C07A).
        ts4 (Path): The ``.TS4`` file.
        tbl (Path): The ``.TBL`` beside it.
        table (dict): `read_table` of the table.
        walk (TagWalk): `walk_tags` of the file.
        order (dict): Channel to its table number, 1-5 (CHEX .. CHHZ).
    """

    stem: str
    ts4: Path
    tbl: Path
    table: dict
    walk: TagWalk
    order: dict

    @property
    def serial(self) -> int:
        """Return the receiver serial."""
        return self.walk.serial

    @property
    def position(self) -> tuple[float | None, float | None]:
        """Return the table's latitude and longitude in degrees (`table_degrees`)."""
        return table_degrees(self.table.get("LATG")), table_degrees(self.table.get("LNGG"))


def _iso(seconds: float) -> str:
    """Return a UTC unix time as ISO text."""
    return pd.Timestamp(seconds, unit="s", tz="UTC").isoformat()


def _compact(seconds: float) -> str:
    """Return a UTC unix second as ``YYYYMMDDThhmmssZ``: a time with no colon, for a run comment piece."""
    return pd.Timestamp(seconds, unit="s", tz="UTC").strftime("%Y%m%dT%H%M%SZ")


def open_recording(ts4: Path) -> Recording:
    """Decode a recording's table and walk its ``.TS4`` tags, checking that they belong together.

    Args:
        ts4 (Path): The ``.TS4`` file.

    Returns:
        Recording: The recording.

    Raises:
        FileNotFoundError: If there is no ``.TBL`` of the same stem beside it.
        ValueError: If the name is not an MTU-5A stem, the table lacks a key
            the chain needs, the name, table (SNUM) and tags name different
            receivers, the table does not number five channels 1 to 5, its
            150 Hz rate (SRL4) is not the tags', its FTIM is further than
            `FTIM_TOLERANCE_S` from the first tag, or `walk_tags` refuses.
    """
    ts4 = Path(ts4)
    hit = NAME.match(ts4.stem)
    if not hit:
        raise ValueError(f"{ts4.name}: not an MTU-5A recording name, <serial><month><day><letter> such as "
                         f"4573C07A.TS4")
    tbl = _sibling(ts4, TABLE)
    if tbl is None:
        raise FileNotFoundError(f"{ts4.name} has no {ts4.stem}.TBL beside it: the table gives the channel order and "
                                f"the scale chain, and the .TS4 is not read without it")
    table = read_table(tbl)
    missing = [k for k in REQUIRED_KEYS if table.get(k) is None]
    if missing:
        raise ValueError(f"{tbl.name}: no {', '.join(missing)}, which the channel order, the chain and the time "
                         f"check need")
    walk = walk_tags(ts4)
    named = {"the name": int(hit.group(1)), f"{tbl.name} SNUM": int(table["SNUM"]), "the record tags": walk.serial}
    if len(set(named.values())) != 1:
        raise ValueError(f"{ts4.stem}: " + ", ".join(f"{k} {v}" for k, v in named.items())
                         + ": the receivers differ")
    order = {comp: int(table[key]) for comp, key in CHANNEL_KEYS.items()}
    if sorted(order.values()) != list(range(1, len(CHANNELS) + 1)):
        raise ValueError(f"{tbl.name}: channel numbers {order}; the mtu5a reader reads five channels numbered 1 to 5")
    if table.get("SRL4") is not None and int(table["SRL4"]) != int(walk.rate):
        raise ValueError(f"{tbl.name}: SRL4 {table['SRL4']} Hz, and the tags of {ts4.name} {walk.rate:g} Hz")
    first = float(walk.times[0])
    ftim = table["FTIM"].timestamp()
    if abs(ftim - first) > FTIM_TOLERANCE_S:
        raise ValueError(f"{tbl.name}: FTIM {table['FTIM'].isoformat()} and the first tag of {ts4.name} "
                         f"{_iso(first)} differ by {ftim - first:+g} s (more than {FTIM_TOLERANCE_S:g} s): the "
                         f"table is not this recording's")
    return Recording(stem=ts4.stem.upper(), ts4=ts4, tbl=tbl, table=table, walk=walk, order=order)


@dataclass
class Mtu5aRun:
    """One run of a recording: records ``first`` to ``stop - 1``, each 1 s after the one before.

    Attributes:
        recording (Recording): The recording.
        first (int): The run's first record.
        stop (int): One past its last record.
        gap_s (float or None): The seconds between the record before
            ``first`` and ``first``, less the 1 s of a record, when the run
            starts after a step in the tags; None for a recording's first run
            (or a run cut by the window).
    """

    recording: Recording
    first: int
    stop: int
    gap_s: float | None = None

    @property
    def start_s(self) -> int:
        """Return the run's first tag, UTC unix seconds."""
        return int(self.recording.walk.times[self.first])

    @property
    def end_s(self) -> int:
        """Return the end of the run's last record (its tag plus 1 s), UTC unix seconds."""
        return int(self.recording.walk.times[self.stop - 1]) + 1

    @property
    def n(self) -> int:
        """Return the run's samples per channel."""
        return (self.stop - self.first) * self.recording.walk.scans

    def describe(self) -> str:
        """Return the run's file and records, for the ingest log."""
        return f"{self.recording.ts4.name} records {self.first}-{self.stop - 1} ({self.stop - self.first} s)"


def _seconds(value) -> float:
    """Return a window bound as UTC unix seconds (a naive time is UTC)."""
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.timestamp()


def _note_other_files(site_dir: Path, site_name: str) -> None:
    """Log the burst files left alone (one line) and warn about the tables without a ``.TS4``."""
    files = [p for p in Path(site_dir).rglob("*") if p.is_file()]
    bursts = sorted(p.name for p in files if p.suffix.upper() in UNREAD_BANDS)
    if bursts:
        logger.info(f"{site_name}: {len(bursts)} .TS2/.TS3 file(s) left alone ({', '.join(bursts)}): the mtu5a "
                    f"reader reads the 150 Hz .TS4 band only")
    alone = sorted(p.name for p in files if p.suffix.upper() == TABLE and _sibling(p, BAND) is None)
    if alone:
        logger.warning(f"{site_name}: {len(alone)} .TBL file(s) with no .TS4 beside them ({', '.join(alone)}): no "
                       f"150 Hz band, not ingested")


def plan_runs(site_dir: Path, site, rate: float, start=None, end=None) -> list[Mtu5aRun]:
    """List an MTU-5A site's runs: one or more per recording, in time order.

    Every ``.TS4`` under the site folder is a recording (`open_recording`:
    its ``.TBL`` must be beside it). The recordings must be of one receiver
    (and of the site's `serial` when declared), agree on every table value
    of the chain (`CHAIN_KEYS`; not the coil serials, which carry nothing
    numeric and are recorded per run from each recording's table), and not
    overlap. A recording's run ends
    where its tags step by other than 1 s, and the next run starts at the
    tag after the step; runs that would overlap (a tag stepping back) are
    refused. With a window, the records overlapping [start, end) are kept.
    The burst files are logged once and left alone.

    Args:
        site_dir (Path): The site folder.
        site (SiteConfig): The site's settings.
        rate (float): `Survey.sample_rate_of` the site; must be 150.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.

    Returns:
        list of Mtu5aRun: The runs in time order.

    Raises:
        FileNotFoundError: If the folder holds no ``.TS4``, or a ``.TS4``
            has no ``.TBL``.
        ValueError: If the rate is not 150 Hz, `open_recording` refuses, the
            folder holds two receivers or another than the declared serial,
            the recordings' chains differ, two recordings or two runs
            overlap, or no record is in the window.
    """
    from .instruments import record_files

    site_dir = Path(site_dir)
    if float(rate) != BAND_RATE:
        raise ValueError(f"{site.name}: declared at {float(rate):g} Hz; the mtu5a reader reads the 150 Hz .TS4 band "
                         f"only (sample_rate: 150)")
    files = record_files(site_dir, "mtu5a")
    if not files:
        raise FileNotFoundError(f"{site.name}: no .TS4 file under {site_dir}")
    _note_other_files(site_dir, site.name)
    recordings = []
    for f in files:
        try:
            recordings.append(open_recording(f))
        except (ValueError, FileNotFoundError) as exc:
            raise type(exc)(f"{site.name}: {exc}") from None
    serials = sorted({r.serial for r in recordings})
    if len(serials) > 1:
        raise ValueError(f"{site.name}: {site_dir} holds recordings of receivers {serials} ("
                         + ", ".join(r.ts4.name for r in recordings) + "): one receiver per site folder")
    if site.serial and str(site.serial) != str(serials[0]):
        raise ValueError(f"{site.name}: its recordings are receiver {serials[0]}, and survey.yaml declares serial "
                         f"{site.serial}")
    chains = {r.stem: tuple(r.table.get(k) for k in CHAIN_KEYS) for r in recordings}
    if len(set(chains.values())) > 1:
        first = next(iter(chains.values()))
        differ = [k for i, k in enumerate(CHAIN_KEYS) if len({c[i] for c in chains.values()}) > 1]
        raise ValueError(f"{site.name}: its recordings differ in {', '.join(differ)} ("
                         + ", ".join(f"{s} {dict(zip(CHAIN_KEYS, c))[differ[0]]!r}" for s, c in chains.items())
                         + f"; {len(first)} values compared): processing takes the first run's chain for every run, "
                         f"so give each recording its own site folder")
    positions = [(r.stem, *r.position) for r in recordings if None not in r.position]
    if len(positions) > 1:
        from .survey import distance_km

        far = max(distance_km(a[1], a[2], b[1], b[2]) for a in positions for b in positions) * 1000.0
        if far > POSITION_DIFF_M:
            logger.warning(f"{site.name}: the tables put its recordings up to {far:.0f} m apart ("
                           + ", ".join(f"{s} {la:.6f} {lo:.6f}" for s, la, lo in positions) + ")")
    recordings.sort(key=lambda r: int(r.walk.times[0]))
    for a, b in zip(recordings, recordings[1:]):
        if int(b.walk.times[0]) < int(a.walk.times[-1]) + 1:
            raise ValueError(f"{site.name}: {b.ts4.name} starts at {_iso(b.walk.times[0])}, before {a.ts4.name} ends "
                             f"at {_iso(a.walk.times[-1] + 1)}: overlapping recordings in one site folder are refused")
    lo = _seconds(start) if start is not None else -math.inf
    hi = _seconds(end) if end is not None else math.inf
    units = []
    for rec in recordings:
        times = rec.walk.times
        cuts = (np.flatnonzero(np.diff(times) != 1) + 1).tolist()
        for a, b in zip([0, *cuts], [*cuts, rec.walk.n]):
            if a:
                logger.warning(f"{site.name}: {rec.ts4.name} record tags step {int(times[a] - times[a - 1]):+d} s at "
                               f"record {a} ({_iso(times[a])}): a new run starts there")
            inside = np.flatnonzero((times[a:b] + 1 > lo) & (times[a:b] < hi))
            if not inside.size:
                continue
            first, stop = a + int(inside[0]), a + int(inside[-1]) + 1
            gap = float(times[a] - times[a - 1] - 1) if a and first == a else None
            units.append(Mtu5aRun(recording=rec, first=first, stop=stop, gap_s=gap))
    units.sort(key=lambda u: u.start_s)
    for u, v in zip(units, units[1:]):
        if v.start_s < u.end_s:
            raise ValueError(f"{site.name}: {v.describe()} starts at {_iso(v.start_s)}, before {u.describe()} ends at "
                             f"{_iso(u.end_s)}: the record tags step back, and overlapping runs are refused")
    if not units:
        raise ValueError(f"{site.name}: no MTU-5A record overlaps [{start}, {end})")
    return units


# ---------------------------------------------------------------------------------------------- chain and read
def _coefficient(name: str, gain: float, units_in: str, units_out: str, comments: str):
    """Return a CoefficientFilter of the chain."""
    from mt_metadata.timeseries.filters import CoefficientFilter

    stage = CoefficientFilter()
    stage.name, stage.gain = name, float(gain)
    stage.units_in, stage.units_out = units_in, units_out
    stage.comments = comments
    return stage


def channel_chain(rec: Recording, comp: str, site) -> tuple[list, list[str]]:
    """Return a channel's chain from the field to the counts, and its comment pieces.

    ex, ey: the dipole (`mtu5a_dipole_<c>_<L>m`, mV/km to mV, gain L / 1000,
    L the declared `dipole_length_*` or else the table's EXLN/EYLN; a line
    whose azimuth is its nominal plus 180 deg, read as reversed under
    `flip_reversed_dipoles`, gets the negative gain and the suffix
    ``_reversed``), EGN (mV to mV) and the converter (mV to counts, gain
    2^23 / (1000 FSCV)). hx, hy, hz: HNOM (nT to mV, the table's nominal
    value), HATT (mV to mV), HGN (mV to mV) and the converter; no coil
    response, no H sign stage.

    Args:
        rec (Recording): The recording.
        comp (str): The channel.
        site (SiteConfig): The site's settings.

    Returns:
        tuple: (filters physical to recorded, comment pieces).

    Raises:
        ValueError: If an electric channel has no dipole length.
    """
    table = rec.table
    fscv = float(table["FSCV"])
    converter = _coefficient(f"mtu5a_counts_{fscv:g}v", FULL_SCALE_COUNTS / (1000.0 * fscv), "milliVolt", "count",
                             f"MTU-5A converter: FSCV {fscv:g} V at 2^23 counts ({rec.tbl.name})")
    pieces = [f"mtu5a: {rec.stem} channel {rec.order[comp]} ({CHANNEL_KEYS[comp]})"]
    if comp in DIPOLE_KEYS:
        declared = float(getattr(site, f"dipole_length_{comp}", 0.0) or 0.0)
        tabled = float(table[DIPOLE_KEYS[comp]])
        length = declared or tabled
        if not length:
            raise ValueError(f"{site.name} {comp}: no dipole length in {rec.tbl.name} and none declared")
        if declared and abs(declared - tabled) > DIPOLE_DIFF_M:
            logger.info(f"{site.name} {comp}: dipole {declared:g} m from survey.yaml, {rec.tbl.name} {tabled:g} m")
        azimuth = float(getattr(site, f"azimuth_{comp}", NOMINAL_AZIMUTH[comp])) % 360.0
        laid_reversed = (azimuth - NOMINAL_AZIMUTH[comp]) % 360.0 == 180.0
        flip = laid_reversed and bool(site.flip_reversed_dipoles)
        dipole = _coefficient(f"mtu5a_dipole_{comp}_{length:g}m" + ("_reversed" if flip else ""),
                              (-1.0 if flip else 1.0) * length / 1000.0, "milliVolt per kilometer", "milliVolt",
                              f"dipole {length:g} m" + (", laid reversed: the gain is negative" if flip else ""))
        egn = _coefficient(f"mtu5a_egn_{table['EGN']:g}", float(table["EGN"]), "milliVolt", "milliVolt",
                           f"MTU-5A electric gain EGN ({rec.tbl.name})")
        chain = [dipole, egn, converter]
        pieces.append(f"dipole {length:g} m from {'survey.yaml' if declared else rec.tbl.name}, {rec.tbl.name} "
                      f"{tabled:g}")
        if laid_reversed:
            pieces.append(f"azimuth {azimuth:g} " + ("read as the reversed line (the dipole stage's gain negative)"
                                                    if flip else "taken as the layout direction (flip_reversed_dipoles "
                                                                 "false)"))
        resistance = table.get("EXR" if comp == "ex" else "EYR")
        if resistance is not None:
            pieces.append(f"contact resistance {resistance} ohm ({rec.tbl.name})")
    else:
        hnom = _coefficient(f"mtu5a_hnom_{table['HNOM']:g}", float(table["HNOM"]), "nanoTesla", "milliVolt",
                            f"MTU-5A HNOM, the table's nominal coil value, frequency independent: no coil response "
                            f"({rec.tbl.name})")
        hatt = _coefficient(f"mtu5a_hatt_{table['HATT']:g}", float(table["HATT"]), "milliVolt", "milliVolt",
                            f"MTU-5A magnetic attenuation HATT ({rec.tbl.name})")
        hgn = _coefficient(f"mtu5a_hgn_{table['HGN']:g}", float(table["HGN"]), "milliVolt", "milliVolt",
                           f"MTU-5A magnetic gain HGN ({rec.tbl.name})")
        chain = [hnom, hatt, hgn, converter]
        coil = str(table.get(COIL_KEYS[comp]) or "").strip()
        pieces.append(f"coil {coil or 'not in the table'} ({COIL_KEYS[comp]})")
        pieces.append("coil response missing (HNOM alone): Z and M wrong here, T unaffected; no H sign stage")
    return chain, pieces


def _check_reader(reader, rec: Recording) -> None:
    """Refuse mt-io's read of a file when its counts of records, scans or channels, rate, serial or start differ from the walk's."""
    meta, walk = reader.ts_metadata, rec.walk
    got = {"channels": meta["n_ch"], "scans": meta["n_scan"], "records": meta["n_block"],
           "rate": float(meta["sample_rate"]), "serial": meta["box_number"], "shape": tuple(reader.ts.shape),
           "start": pd.Timestamp(meta["start"].isoformat()).timestamp()}
    want = {"channels": walk.channels, "scans": walk.scans, "records": walk.n, "rate": walk.rate,
            "serial": walk.serial, "shape": (walk.channels, walk.n * walk.scans), "start": float(walk.times[0])}
    differ = [k for k in want if got[k] != want[k]]
    if differ:
        raise ValueError(f"{rec.ts4.name}: mt-io's read and the tag walk differ in "
                         + ", ".join(f"{k} (mt-io {got[k]}, tags {want[k]})" for k in differ)
                         + ": the file is not read")


def rails() -> dict[str, float]:
    """Return each channel's absolute rail for an MTU-5A run's dc level, in counts.

    The rail is `mt_workbench.dclevel.RAIL_LEVEL` x `MTU5A_CLIP` x 2^23
    counts, the same for every channel (the converter's full scale is the
    same for all five), so swap_e and swap_h do not move it; in the form of
    `mt_workbench.ingest._phoenix_rails`, whose rails are in volts.

    Returns:
        dict[str, float]: {channel: rail in counts}.
    """
    return {comp: RAIL_LEVEL * MTU5A_CLIP * FULL_SCALE_COUNTS for comp in CHANNELS}


def _exchange(site) -> dict[str, str]:
    """Return the archive channel each recorded channel becomes under the site's swap_e and swap_h."""
    exchange = {}
    if site.swap_e:
        exchange.update(ex="ey", ey="ex")
    if site.swap_h:
        exchange.update(hx="hy", hy="hx")
    return exchange


def _flag_counts(unit: Mtu5aRun, site) -> str:
    """Return the run comment's count of flagged records: saturation per archive channel (after swap_e and
    swap_h, as `flag_rows` names them), status, clock status."""
    rec, walk = unit.recording, unit.recording.walk
    part = slice(unit.first, unit.stop)
    saturation = walk.saturation[part]
    exchange = _exchange(site)  # an exchange of two: the archive's ey holds the recorded ex, and so on
    per = " ".join(f"{c} {int(((saturation >> (rec.order[exchange.get(c, c)] - 1)) & 1).sum())}" for c in CHANNELS)
    clock = walk.clock_status[part]
    values, counts = np.unique(walk.clock_status, return_counts=True)
    usual = int(values[np.argmax(counts)])
    return (f"mtu5a_flags: saturation records {per}, status nonzero {int((walk.status[part] != 0).sum())}, clock "
            f"status other than {usual} {int((clock != usual).sum())}, clock error nonzero "
            f"{int((walk.clock_error[part] != 0).sum())}, intervals in the archive's {FLAGS_SUFFIX[1:]}")


def read_run(unit: Mtu5aRun, site):
    """Read one run of a recording into a RunTS of counts with its chain.

    The file is read with mt-io's `MTUTSN.read` (raw counts), checked
    against the walk (`_check_reader`), and the run's records taken in the
    table's channel order, as int32. Each channel gets the chain of
    `channel_chain` as applied filters, units "counts", its nominal
    azimuth, its dipole length or coil serial and its comment pieces; the
    run starts at its first tag (UTC) at the tags' rate. The run comment
    names the receiver, the recording and its records, the time base, the
    units and the flagged records (`_flag_counts`), and a gap before the
    run.

    Args:
        unit (Mtu5aRun): The run.
        site (SiteConfig): The site's settings.

    Returns:
        RunTS: The run.

    Raises:
        ValueError: If `_check_reader` refuses, mt-io's counts are not whole
            24-bit numbers, or `channel_chain` refuses.
    """
    from mt_io.phoenix.readers import MTUTSN
    from mt_metadata.timeseries import Electric, Magnetic, Run, Station
    from mt_metadata.timeseries.filters import ChannelResponse
    from mt_timeseries import ChannelTS, RunTS

    rec, walk = unit.recording, unit.recording.walk
    reader = MTUTSN(rec.ts4)
    reader.read()
    _check_reader(reader, rec)
    lo, hi = unit.first * walk.scans, unit.stop * walk.scans
    start = pd.Timestamp(unit.start_s, unit="s", tz="UTC")
    end = start + pd.Timedelta(seconds=(unit.n - 1) / walk.rate)
    built, chains = [], {}
    for comp in CHANNELS:
        values = reader.ts[rec.order[comp] - 1, lo:hi]
        samples = values.astype(np.int32)
        if not np.array_equal(samples, values) or np.abs(samples).max(initial=0) > FULL_SCALE_COUNTS:
            raise ValueError(f"{rec.ts4.name} {comp}: mt-io's counts are not whole 24-bit numbers")
        chain, pieces = channel_chain(rec, comp, site)
        chains[comp] = chain
        md = Electric() if comp in DIPOLE_KEYS else Magnetic()
        md.component = comp
        md.channel_number = rec.order[comp]
        md.units = "counts"
        md.sample_rate = walk.rate
        md.measurement_azimuth = NOMINAL_AZIMUTH[comp]
        md.measurement_tilt = 90.0 if comp == "hz" else 0.0
        md.time_period.start = start.isoformat()
        md.time_period.end = end.isoformat()
        if comp in DIPOLE_KEYS:
            md.dipole_length = abs(float(chain[0].gain)) * 1000.0
        else:
            md.sensor.id = str(rec.table.get(COIL_KEYS[comp]) or "").strip()
            md.sensor.manufacturer = "Phoenix Geophysics"
            md.sensor.type = "induction coil"
        for stage, f in enumerate(chain, 1):
            md.add_filter(name=f.name, applied=True, stage=stage)
        md.comments = ", ".join(pieces)
        built.append(ChannelTS(channel_type=md.type, data=samples, channel_metadata=md,
                               channel_response=ChannelResponse(filters_list=chain)))
    del values
    reader.ts = None  # the file's float64 copy, freed before the run is assembled
    table = rec.table
    run_md = Run()
    run_md.id = "a"
    run_md.data_type = "BBMT"
    run_md.sample_rate = walk.rate
    run_md.data_logger.manufacturer = "Phoenix Geophysics"
    run_md.data_logger.model = str(table.get("HW") or "MTU-5A")
    run_md.data_logger.id = str(rec.serial)
    run_md.data_logger.type = "broadband"
    if table.get("VER"):
        run_md.data_logger.firmware.version = str(table["VER"])
    station_md = Station()
    station_md.id = site.name
    declared = site.latitude is not None and site.longitude is not None
    lat, lon = (site.latitude, site.longitude) if declared else rec.position
    if lat is not None and lon is not None:
        station_md.location.latitude, station_md.location.longitude = float(lat), float(lon)
    elevation = site.elevation if site.elevation is not None else table.get("ELEV")
    if elevation is not None:
        station_md.location.elevation = float(elevation)
    where = ("survey.yaml" if declared else f"{rec.tbl.name} LATG LNGG (none declared)" if lat is not None
             else "none (neither survey.yaml nor the table)")
    for period in (run_md.time_period, station_md.time_period):
        period.start, period.end = start.isoformat(), end.isoformat()
    run = RunTS(array_list=built, run_metadata=run_md, station_metadata=station_md)
    for chain in chains.values():
        for f in chain:
            run.filters[f.name] = f
    clean = lambda text: re.sub(r"[;:]", " ", str(text))  # noqa: E731  (a run comment piece is "key: value")
    pieces = [f"mtu5a: Phoenix MTU-5A receiver {rec.serial} ({clean(table.get('HW', ''))} firmware "
              f"{clean(table.get('VER', ''))}), recording {rec.stem}, records {unit.first}-{unit.stop - 1} of "
              f"{walk.n}, table {rec.tbl.name} (SITE {clean(table.get('SITE', ''))!r}), position from {where}",
              f"mtu5a_time: the run starts at its first record's tag {_compact(unit.start_s)}, records of "
              f"{walk.scans} scans 1 s apart, the tag taken as the time of the record's first scan (no band delay "
              f"applied)",
              f"mtu5a_units: counts, chain FSCV {float(table['FSCV']):g} V at 2^23 counts, EGN {table['EGN']:g}, "
              f"dipoles ex {abs(chains['ex'][0].gain) * 1000:g} m ey {abs(chains['ey'][0].gain) * 1000:g} m, "
              f"HGN {table['HGN']:g} x HATT {table['HATT']:g} x HNOM {table['HNOM']:g} nominal (no coil response, "
              f"no H sign stage)",
              _flag_counts(unit, site)]
    if unit.gap_s is not None:
        pieces.append(f"mtu5a_gap: {unit.gap_s:g} s without records in {rec.stem} before this run")
    run.run_metadata.comments.value = "; ".join(pieces)
    return run


# ------------------------------------------------------------------------------------- the flagged intervals
def flags_path(archive: Path) -> Path:
    """Return the interval table written beside an archive: ``<stem>.mtu5a_flags.csv``."""
    archive = Path(archive)
    return archive.with_name(archive.stem + FLAGS_SUFFIX)


def _stretches(values: np.ndarray, keep: np.ndarray) -> list[tuple[int, int, int]]:
    """Return (first, stop, value) of each stretch of consecutive records where `keep` holds and `values` is constant."""
    idx = np.flatnonzero(keep)
    if not idx.size:
        return []
    breaks = (np.flatnonzero((np.diff(idx) != 1) | (np.diff(values[idx].astype(np.int64)) != 0)) + 1).tolist()
    return [(int(idx[a]), int(idx[b - 1]) + 1, int(values[idx[a]])) for a, b in zip([0, *breaks], [*breaks, idx.size])]


def flag_rows(run_id: str, unit: Mtu5aRun, site) -> list[dict]:
    """Return the flagged intervals of one run, on the archive's time axis.

    Saturation: per channel, the stretches of records whose tag byte 15 has
    bit (channel - 1) set; ``input`` is the receiver's channel number and
    ``channel`` the archive's channel (after `swap_e` and `swap_h`); a bit
    above the fifth channel is kept with no channel. Status: the stretches
    of one non-zero byte 14. Clock status: the stretches of a byte 21 other
    than the recording's most common value. Clock error: the stretches of
    one non-zero error. ``start`` is a stretch's first tag and ``end`` its
    last tag plus 1 s (exclusive), both plus the site's `clock_offset_s`.

    Args:
        run_id (str): The run's id in the archive.
        unit (Mtu5aRun): The run.
        site (SiteConfig): The site's settings.

    Returns:
        list of dict: Rows of `FLAG_COLUMNS`.
    """
    rec, walk = unit.recording, unit.recording.walk
    part = slice(unit.first, unit.stop)
    times = walk.times[part].astype(np.float64) + float(site.clock_offset_s)
    exchange = _exchange(site)
    by_number = {number: comp for comp, number in rec.order.items()}
    rows = []

    def add(field, channel, number, value, first, stop):
        rows.append({"run": run_id, "recording": rec.stem, "field": field, "channel": channel, "input": number,
                     "value": value, "start": _iso(times[first]), "end": _iso(times[stop - 1] + 1.0),
                     "records": stop - first})

    saturation = walk.saturation[part]
    for bit in range(8):
        mask = ((saturation >> bit) & 1).astype(bool)
        comp = by_number.get(bit + 1)
        for first, stop, _value in _stretches(np.ones(mask.size, dtype=np.uint8), mask):
            add("saturation", exchange.get(comp, comp) if comp else "", bit + 1, 1, first, stop)
    status = walk.status[part]
    for first, stop, value in _stretches(status, status != 0):
        add("status", "", "", value, first, stop)
    values, counts = np.unique(walk.clock_status, return_counts=True)
    usual = values[np.argmax(counts)]
    clock = walk.clock_status[part]
    for first, stop, value in _stretches(clock, clock != usual):
        add("clock_status", "", "", value, first, stop)
    error = walk.clock_error[part]
    for first, stop, value in _stretches(error, error != 0):
        add("clock_error", "", "", value, first, stop)
    return rows


def write_flags(path: Path, pairs, site) -> list[dict]:
    """Write the flagged intervals of a site's runs beside its archive (`flag_rows`).

    The table is written whole, with its header when no record is flagged.

    Args:
        path (Path): The table (`flags_path` of the archive).
        pairs: (run id, Mtu5aRun) per run written.
        site (SiteConfig): The site's settings.

    Returns:
        list of dict: The rows written.
    """
    rows = [row for run_id, unit in pairs for row in flag_rows(run_id, unit, site)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(FLAG_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return rows


# ------------------------------------------------------------------------- for mt_workbench.instruments
def span(files: list[Path]) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return the recorded span of an MTU-5A site from its tables.

    The earliest FTIM to the latest LTIM plus 1 s (the end of the last
    record) of the ``.TBL`` beside each ``.TS4``.

    Args:
        files (list of Path): The site's ``.TS4`` files.

    Returns:
        tuple: ``(start, end, n)``: UTC Timestamps and the number of
        recordings.

    Raises:
        FileNotFoundError: If a ``.TS4`` has no ``.TBL``.
        ValueError: If a table has no FTIM or LTIM.
    """
    starts, ends = [], []
    for f in files:
        tbl = _sibling(f, TABLE)
        if tbl is None:
            raise FileNotFoundError(f"{Path(f).name} has no {Path(f).stem}.TBL beside it")
        table = read_table(tbl)
        if table.get("FTIM") is None or table.get("LTIM") is None:
            raise ValueError(f"{tbl.name}: no FTIM or LTIM")
        starts.append(table["FTIM"])
        ends.append(table["LTIM"] + pd.Timedelta(seconds=1))
    return min(starts), max(ends), len(files)


def header_facts(files: list[Path]) -> dict:
    """Return what the first recording's table says of an MTU-5A site, for scripts/new_survey.py.

    Args:
        files (list of Path): The site's ``.TS4`` files, in start order.

    Returns:
        dict: ``sample_rate`` (SRL4), ``columns``, ``serial`` (SNUM),
        ``firmware`` (VER), ``model`` and, from LATG, LNGG and ELEV,
        ``latitude``, ``longitude`` and ``elevation``, or ``problem``.
    """
    tbl = _sibling(files[0], TABLE)
    if tbl is None:
        return {"problem": f"{Path(files[0]).name} has no .TBL beside it"}
    table = read_table(tbl)
    facts = {"sample_rate": float(table.get("SRL4") or BAND_RATE), "columns": list(CHANNELS),
             "serial": str(table.get("SNUM", "")) or None, "firmware": table.get("VER"), "model": "MTU-5A"}
    lat, lon = table_degrees(table.get("LATG")), table_degrees(table.get("LNGG"))
    if lat is None or lon is None:
        facts["problem"] = f"no position in {tbl.name}"
    else:
        facts.update(latitude=round(lat, 6), longitude=round(lon, 6))
        if table.get("ELEV") is not None:
            facts["elevation"] = float(table["ELEV"])
    return facts
