# -*- coding: utf-8 -*-
"""
Recorders mt-workbench reads and their detection from a folder of raw files

A site's instrument is determined by its files. The survey names a default
(`instrument:` at the top of survey.yaml), and a site whose folder holds
another recorder's files is detected as that recorder here and written by
`scripts/new_survey.py` as the site's own `instrument:`.

    lemi423  LEMI-423 broadband logger: `<unix epoch>.B423` binary files
             (90 min each), mt_io.lemi.lemi423 -> hx hy hz ex ey (counts; the
             LEMI-120 coil response and `h_scale` are added in mt_workbench.ingest)
    lemi424  LEMI-424 long-period logger: `YYYYMMDDhhmm.txt`, one text line a
             second (24 fields, or 16 without GPS), mt_io.lemi.lemi424 ->
             bx by bz e1 e2 e3 e4 (+ temperature_e, temperature_h), stored as
             hx hy hz ex ey e3 e4 (`LEMI424_RENAME`, `lemi424_stored`). No
             filter chain from the reader: magnetics in nT (fluxgate),
             electrics in mV/km as the logger writes them (no dipole length
             applied; rho matches GA's EDIs within 1 %, Victorian stage 6).
             The electric sign convention `e_sign` is recorded in each
             electric chain by mt_workbench.ingest (the samples stay the
             logger's columns)
    edl      Earth Data PR6-24 with the University of Adelaide interface: one
             ASCII (or miniSEED) file per channel, `{station}YYMMDDhhmmss.{BX,
             BY,BZ,EX,EY}`, in day folders, and `config/recorder.ini`;
             mt_io.uoa.pr624 -> hx hy hz ex ey in recorded microVolt with its
             own chain (Bartington 142.857 uV/nT, the 0.4 Bz divider, the
             signed dipole length, the x10 terminal box). A site may declare
             an extra `electric_gain:` for its electric chain beyond that:
             hardwired at the field terminal junction box, and for a survey
             whose PR6-24 configs were not kept, known from the field
             notes. That gain is added as one more filter on ex and ey
             (`ELECTRIC_GAIN_FILTER`)
    phoenix  Phoenix Geophysics MTU-5C and MTU-8A receivers: one folder per
             recording holding empower_recmeta.json or recmeta.json beside
             numbered channel folders, each with files named
             `<receiver>_<recording id hex>_<channel>_<sequence hex>.<ext>`:
             `.td_150` and `.td_30` continuous, `.td_24k` 24 kHz bursts.
             Read by mt-io's Phoenix readers (mt_io.phoenix) in
             mt_workbench.phoenix, which renames the receiver's e1 e2 h1 h2
             h3 to ex ey hx hy hz. `.td_2400` and `.td_96k` files are
             written by the receivers but mt-io has no reader for them, so
             they are not records here
    orangebox Flinders Orange Box (HFM) long-period logger: hourly
             ``HFM<n>-NNN.BIN`` or ``LP<n>-NNN.BIN`` files (``.BIN.OLD`` for the file logging was
             stopped in), a 40-byte header with the record count, the start
             stamp of the logger's real-time clock and the filter point, 21-byte
             records and a 26-byte end stamp. Read by mt-io's Orange Box reader
             (mt_io.uoa.orange) in mt_workbench.orangebox, which puts every run
             on the UTC 10 Hz grid from the stamps, the clock's time zone and
             the field drift. The stamps are the logger clock's: `file_start`
             and `span` read them as UTC unless given the zone
    mtu5a    Phoenix Geophysics MTU-5A receivers: per recording a `.TBL`
             table and one file per band, `<serial><month><day><letter>`;
             the `.TS4` (150 Hz, continuous) is the record here, read in
             mt_workbench.mtu5a (counts from mt-io's MTUTSN; the tags and
             the table decoded there). The `.TS2` and `.TS3` bursts are
             not records

The mt-io readers are imported inside the functions that use them, so
importing this module (and `mt_workbench.survey`, which imports it) does not load
mt-io. File names carry each file's start in UTC (`file_start`), which is
what run splitting and `span` use.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

INSTRUMENTS: dict[str, dict] = {
    "lemi423": {"label": "LEMI-423", "pattern": "*.B423", "reader": "mt_io.lemi.lemi423",
                "channels": ("hx", "hy", "hz", "ex", "ey"), "file_seconds": 5400},
    "lemi424": {"label": "LEMI-424", "pattern": "*.txt", "reader": "mt_io.lemi.lemi424",
                "channels": ("hx", "hy", "hz", "ex", "ey", "e3", "e4"), "file_seconds": 86400},
    "edl": {"label": "Earth Data PR6-24", "pattern": "*.[BE][XYZ]", "reader": "mt_io.uoa.pr624",
            "channels": ("hx", "hy", "hz", "ex", "ey"), "file_seconds": 3600},
    "phoenix": {"label": "Phoenix MTU-5C/8A", "pattern": "*.td_150", "reader": "mt_io.phoenix",
                "channels": ("ex", "ey", "hx", "hy", "hz"), "file_seconds": 360},
    "orangebox": {"label": "Orange Box (Flinders HFM)", "pattern": "HFM*.BIN or LP*.BIN", "reader": "mt_io.uoa.orange",
                  "channels": ("hx", "hy", "hz", "ex", "ey"), "file_seconds": 3600},
    # a recording is one .TS4 of any length, so there is no file length
    "mtu5a": {"label": "Phoenix MTU-5A", "pattern": "*.TS4", "reader": "mt_io.phoenix.readers.MTUTSN",
              "channels": ("ex", "ey", "hx", "hy", "hz"), "file_seconds": None},
}
LEMI424_ELECTRICS = ("e1", "e2", "e3", "e4")  # every electric column, the reader's names; `channels:` keeps the wired
# the reader's names and the names ingest stores them under (`lemi424_stored`); e3 and e4 keep theirs
LEMI424_RENAME = {"bx": "hx", "by": "hy", "bz": "hz", "e1": "ex", "e2": "ey"}
# measurement azimuth and tilt of the stored magnetic channels, as the EDL reader (mt_io.uoa.pr624) writes
# them: on the sensor axes (`rot_h` turns hx and hy onto magnetic north and leaves 0 and 90, now true)
STORED_AZIMUTH_TILT = {"hx": (0.0, 0.0), "hy": (90.0, 0.0), "hz": (0.0, 90.0)}
LEMI424_FIELDS = (24, 16)  # the reader's two line layouts: with and without the GPS block
EDL_FILES = {".BX": "hx", ".BY": "hy", ".BZ": "hz", ".EX": "ex", ".EY": "ey"}  # pr624's mapping
EDL_STAMP = re.compile(r"(\d{12})$")  # YYMMDDhhmmss at the end of the stem
# EDL magnetic sensors (`sensor_type:`, in mt_io.uoa.pr624's names) mapped to the prefix of
# the response filter the reader puts on hx, hy and hz for them
EDL_SENSORS = {"bartington": "uoa_bartington", "lemi120": "lemi_120"}
_EDL_SUFFIXES = {s.lower() for s in EDL_FILES}
# An EDL site's electric chain may carry extra gain between the dipoles and the recorded values,
# beyond what the reader models (the x10 terminal box). It is hardwired at the field terminal
# junction box and, for a survey whose PR6-24 configs were not kept, known
# from the field notes. `SiteConfig.electric_gain` (default 1.0, no filter) declares it, and
# `read_run` adds it as this filter on ex and ey. The filter is forward, like the reader's own gains
# (input microVolt to stored words), so calibration divides by it and the channels come out that
# many times smaller. The archive keeps the words as stored.
ELECTRIC_GAIN_FILTER = "uoa_electric_gain"
# a gain on one electric line alone (`SiteConfig.electric_gain_ex`, `electric_gain_ey`; NF18 of South
# Australia AusLAMP 2013-2018, an x64 stage on Ex only): one more forward stage on that channel's chain,
# after ELECTRIC_GAIN_FILTER's, named per channel (`add_channel_electric_gains`)
CHANNEL_GAIN_FILTER = {"ex": "uoa_electric_gain_ex", "ey": "uoa_electric_gain_ey"}
# A Phoenix data file name: receiver id, recording id (hex GPS seconds), channel folder index and
# file sequence number (hex)
PHOENIX_NAME = re.compile(r"^(\d+)_([0-9A-Fa-f]{8})_(\d+)_([0-9A-Fa-f]{8})$")
# the Phoenix file types mt-io reads, by extension, and their nominal sample rates in Hz; the
# receiver's own header gives the rate a file was written at
PHOENIX_RATES = {".td_150": 150.0, ".td_30": 30.0, ".td_24k": 24000.0}
PHOENIX_CONTINUOUS = (".td_150", ".td_30")  # one stream per file, no sub-headers
PHOENIX_BURSTS = ".td_24k"  # segments of 32-byte sub-header plus samples
# file types the receivers write and mt-io has no reader for (not in mt_io.phoenix.read.READERS)
PHOENIX_UNREAD = (".td_2400", ".td_96k")
PHOENIX_HEADER_BYTES = 128
PHOENIX_SUBHEADER_BYTES = 32
# the receiver metadata files, in the order mt-io takes them
# (mt_io.phoenix.readers.receiver_metadata.RECEIVER_METADATA_NAMES)
PHOENIX_METADATA = ("empower_recmeta.json", "recmeta.json")
# receiver models as the metadata file's channel_map.receiver_model names them
PHOENIX_MODELS = {"RMT03-D": "MTU-5C", "RMT03-G": "MTU-5C", "RMT05": "MTU-8A"}


def is_record(path: Path, instrument: str) -> bool:
    """Return whether a file name is a data file of an instrument.

    Only the name is checked. AppleDouble ``._`` twins are rejected.

    Args:
        path (Path): File path.
        instrument (str): Key of `INSTRUMENTS`.

    Returns:
        bool: True for a data file name of `instrument`.

    Raises:
        ValueError: If the instrument is unknown.
    """
    name, stem, suffix = path.name, path.stem, path.suffix
    if name.startswith("._"):
        return False
    if instrument == "lemi423":
        return suffix.lower() == ".b423" and stem.isdigit()
    if instrument == "lemi424":
        return suffix.lower() == ".txt" and len(stem) == 12 and stem.isdigit()
    if instrument == "edl":
        return suffix.upper() in EDL_FILES and EDL_STAMP.search(stem) is not None
    if instrument == "phoenix":
        return suffix.lower() in PHOENIX_RATES and PHOENIX_NAME.match(stem) is not None
    if instrument == "orangebox":
        from .orangebox import is_orange_name

        return is_orange_name(path)
    if instrument == "mtu5a":  # the name is checked when the recording is opened (mt_workbench.mtu5a)
        return suffix.upper() == ".TS4"
    raise ValueError(f"unknown instrument {instrument!r} (know: {', '.join(INSTRUMENTS)})")


def phoenix_header(path: Path) -> dict:
    """Read the fields of a Phoenix file's 128-byte header that ingest uses.

    The layout is mt-io's (`mt_io.phoenix.readers.header.Header`), read
    here with `struct` so that listing a recording's files does not build
    an mt-io reader per file. For a `.td_24k` file the first sub-header's
    GPS stamp and sample count are read too.

    Args:
        path (Path): A Phoenix data file.

    Returns:
        dict: ``file_version``, ``header_length``, ``receiver`` (the
        instrument serial as text), ``recording_id`` (GPS seconds),
        ``channel`` (folder index), ``sequence``, ``frag_period`` (s),
        ``sample_rate`` (Hz) and, for bursts, ``first_stamp`` and
        ``first_n``.

    Raises:
        ValueError: If the file is shorter than its header.
    """
    import struct

    path = Path(path)
    with open(path, "rb") as f:
        head = f.read(PHOENIX_HEADER_BYTES + PHOENIX_SUBHEADER_BYTES)
    if len(head) < PHOENIX_HEADER_BYTES:
        raise ValueError(f"{path.name}: {len(head)} bytes, shorter than the {PHOENIX_HEADER_BYTES}-byte header")
    base, exp = struct.unpack_from("<Hb", head, 59)
    out = {
        "file_version": head[1],
        "header_length": struct.unpack_from("<H", head, 2)[0],
        "receiver": head[12:20].strip(b"\x00").decode("ascii", "replace").strip(),
        "recording_id": struct.unpack_from("<I", head, 20)[0],
        "channel": head[24],
        "sequence": struct.unpack_from("<I", head, 25)[0],
        "frag_period": struct.unpack_from("<H", head, 29)[0],
        "sample_rate": float(base * 10 ** exp) if exp else float(base),
    }
    if path.suffix.lower() == PHOENIX_BURSTS and len(head) >= PHOENIX_HEADER_BYTES + 8:
        out["first_stamp"], out["first_n"] = struct.unpack_from("<II", head, PHOENIX_HEADER_BYTES)
    return out


def gps_to_utc_seconds(gps_seconds: int) -> int:
    """Return the UTC second of a Phoenix GPS stamp, as mt-io converts it.

    Phoenix stamps count GPS seconds from the unix epoch; UTC is behind by
    the leap seconds of the date (18 since 2017), which mt-io subtracts
    through mt_metadata's `MTime(gps_time=True)`. The same leap-second
    table (`calculate_leap_seconds`) is used here.

    Args:
        gps_seconds (int): A recording id or burst stamp.

    Returns:
        int: The UTC unix second.
    """
    from mt_metadata.common.mttime import calculate_leap_seconds

    when = datetime.fromtimestamp(int(gps_seconds), tz=timezone.utc)
    return int(gps_seconds) - calculate_leap_seconds(when.year, when.month, when.day)


def phoenix_file_start(header: dict, suffix: str) -> float:
    """Return the UTC time of a Phoenix file's first sample, as mt-io dates it.

    A continuous file (`.td_150`, `.td_30`) starts at the recording id
    converted to UTC (`gps_to_utc_seconds`) plus 1 s for the first file of
    a recording, and plus the fragment period times (sequence - 1) for the
    others (mt-io's `DecimatedContinuousReader.segment_start_time`). A
    burst file starts at its first burst's stamp. The second by which
    file-version-2 stamps trail GPS is not added here: mt_workbench.phoenix
    adds it.

    Args:
        header (dict): `phoenix_header` of the file.
        suffix (str): The file's extension.

    Returns:
        float: UTC seconds since the epoch.
    """
    if suffix.lower() == PHOENIX_BURSTS:
        return float(gps_to_utc_seconds(header["first_stamp"]))
    start = gps_to_utc_seconds(header["recording_id"])
    seq = int(header["sequence"])
    return float(start + 1 if seq == 1 else start + header["frag_period"] * (seq - 1))


def _lemi424_line(path: Path) -> bool:
    """Return whether the first line parses as LEMI-424 data (24 or 16 fields, a year first)."""
    try:
        with open(path, "rb") as f:
            fields = f.readline(512).split()
    except OSError:
        return False
    return len(fields) in LEMI424_FIELDS and fields[0].isdigit() and len(fields[0]) == 4


def detect_instrument(site_dir: str | Path, prefer: str = "lemi423") -> str | None:
    """Detect the instrument whose files a folder holds anywhere below it.

    The folder is walked once. `prefer` is returned as soon as one of its
    files is seen, so a LEMI-423 survey recognises a site by a B423 file
    named by its epoch anywhere under the folder. Otherwise the evidence
    seen decides, `prefer` first, then the `INSTRUMENTS` order. A LEMI-424
    ``.txt`` counts when its first line parses; an EDL folder is recognised
    by a channel file or its ``recorder.ini``; a Phoenix folder by a
    `.td_150`, `.td_30` or `.td_24k` file with a Phoenix name; an Orange
    Box folder by an ``HFM<n>-NNN.BIN`` or ``LP<n>-NNN.BIN`` (or ``.BIN.OLD``) file whose header
    parses (an empty file does not count); an MTU-5A
    folder by a `.TS4` file.

    Args:
        site_dir (str or Path): Folder to search.
        prefer (str): Instrument to return first, usually the survey's.

    Returns:
        str or None: Key of `INSTRUMENTS`, or None when the folder is not a
        site.
    """
    seen: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(site_dir):
        for name in filenames:
            low = name.lower()  # check the extension before building a Path
            found = ("edl" if low == "recorder.ini" or low[-3:] in _EDL_SUFFIXES else
                     "lemi423" if low.endswith(".b423") else "lemi424" if low.endswith(".txt") else
                     "phoenix" if low.endswith(tuple(PHOENIX_RATES)) else
                     "orangebox" if low.startswith(("hfm", "lp")) and low.endswith((".bin", ".bin.old")) else
                     "mtu5a" if low.endswith(".ts4") else None)
            if found is None or found in seen and found != prefer:
                continue
            path = Path(dirpath) / name
            if low != "recorder.ini" and not is_record(path, found):
                continue
            if found == "lemi424" and not _lemi424_line(path):
                continue
            if found == "orangebox" and _orange_head(path) is None:
                continue
            if found == prefer:
                return found
            seen.add(found)
    return next((i for i in (prefer, *INSTRUMENTS) if i in seen), None)


def _orange_head(path: Path) -> dict | None:
    """Return an Orange Box file's header (`mt_workbench.orangebox.read_header`), None if it does not parse."""
    from .orangebox import read_header

    try:
        return read_header(path)
    except OSError:
        return None


def b423_files(site_dir: Path) -> list[Path]:
    """List the B423 record files of a site folder, sorted by epoch name.

    The records in the site folder itself are the site's recording. Its
    subfolders are searched only when the folder itself holds no record:
    a logger card copied whole keeps its records in a ``DATA0001``-style
    subfolder, but a subfolder beside a complete recording is a stray (a
    card from another logger, a second copy of some files) and is left out
    with a warning naming it. Nador's P2S1 holds 265 one-hertz files of
    another logger in ``DATA0034``, which, read together with the site's
    own 32 files, made the recording look empty.

    A B423 file is named by the unix epoch of its first sample, so a name
    that is not a whole number is not a record. Data copied through a Mac
    carry an AppleDouble twin per file (``._1677774771.B423``, a 4 kB
    resource fork); those are skipped with one warning per folder.

    Args:
        site_dir (Path): Site folder.

    Returns:
        list of Path: Record files in time order.
    """
    site_dir = Path(site_dir)
    real, skipped, strays = [], [], {}
    for f in site_dir.rglob("*.B423"):
        if not f.stem.isdigit():
            skipped.append(f)
        elif f.parent == site_dir:
            real.append(f)
        else:
            strays.setdefault(f.parent.relative_to(site_dir), []).append(f)
    if skipped:
        logger.warning(
            f"{site_dir.name}: skipped {len(skipped)} non-record .B423 name(s) "
            f"such as {skipped[0].name!r} (AppleDouble twins from a Mac, or copies named '<epoch> (2)')"
        )
    if real and strays:
        for sub, files in sorted(strays.items()):
            logger.warning(
                f"{site_dir.name}: {len(files)} B423 record(s) in subfolder {str(sub)!r} left out: "
                f"the site folder itself holds the recording ({len(real)} files)"
            )
    elif strays:
        real = [f for files in strays.values() for f in files]
    return sorted(real, key=lambda p: int(p.stem))


def file_start(path: Path, instrument: str, clock_timezone: str = "UTC") -> int:
    """Return the UTC unix second a data file starts at, parsed from its name.

    A Phoenix name carries the recording id and sequence number, not the
    file's start, so its 128-byte header is read (`phoenix_file_start`,
    rounded down to the second). An Orange Box file's header stamp is read,
    on the logger clock's zone `clock_timezone` (UTC unless given; the
    other recorders ignore it). An MTU-5A `.TS4` gives its first record
    tag (`mt_workbench.mtu5a.first_tag_time`).

    Raises:
        ValueError: If the instrument is unknown or an Orange Box header
            does not parse.
    """
    stem = Path(path).stem
    if instrument == "lemi423":
        return int(stem)
    if instrument == "orangebox":
        from .orangebox import to_utc_ns

        head = _orange_head(path)
        if head is None:
            raise ValueError(f"{Path(path).name}: no Orange Box header")
        return to_utc_ns(head["stamp"], clock_timezone) // 1_000_000_000
    if instrument == "phoenix":
        return int(phoenix_file_start(phoenix_header(path), Path(path).suffix) // 1)
    if instrument == "mtu5a":
        from .mtu5a import first_tag_time

        return first_tag_time(path)
    if instrument == "lemi424":
        when = datetime.strptime(stem, "%Y%m%d%H%M")
    elif instrument == "edl":
        when = datetime.strptime(EDL_STAMP.search(stem).group(1), "%y%m%d%H%M%S")
    else:
        raise ValueError(f"unknown instrument {instrument!r}")
    return int(when.replace(tzinfo=timezone.utc).timestamp())


def record_files(site_dir: Path, instrument: str) -> list[Path]:
    """List the data files of an instrument under a folder, sorted by start time.

    Phoenix files are sorted by type, recording, channel folder and
    sequence number, the order mt_workbench.phoenix reads them in.

    Orange Box files are sorted by their header stamps, not their names
    (two report series can share a folder); an empty file, or one whose
    header does not parse, is left out with a warning naming it.

    For EDL, the channel files of each start are kept together, and when
    ``recorder.ini`` names a station (``station_long_identifier``, read by
    mt-io's `read_recorder_ini`) that some file carries, only that station's
    files are returned (`_edl_own_files`).

    Args:
        site_dir (Path): Site folder (searched recursively for LEMI-424 and
            EDL; for LEMI-423 see `b423_files`).
        instrument (str): Key of `INSTRUMENTS`.

    Returns:
        list of Path: Data files in start order.
    """
    if instrument == "lemi423":
        return b423_files(site_dir)
    found = [Path(d) / n for d, _sub, names in os.walk(site_dir) for n in names
             if is_record(Path(d) / n, instrument)]
    if instrument == "edl":
        found = _edl_own_files(Path(site_dir), found)
    if instrument == "phoenix":
        heads = {p: phoenix_header(p) for p in found}
        return sorted(found, key=lambda p: (p.suffix.lower(), heads[p]["recording_id"], heads[p]["channel"],
                                            heads[p]["sequence"], str(p)))
    if instrument == "orangebox":
        from .orangebox import orange_files

        listed, skipped = orange_files(found)
        if skipped:
            logger.warning(f"{Path(site_dir).name}: {len(skipped)} Orange Box file(s) left out: {', '.join(skipped)}")
        return [f.path for f in listed]
    return sorted(found, key=lambda p: (file_start(p, instrument), p.suffix.upper(), str(p)))


def _edl_station_key(name: str) -> tuple:
    """Return the form in which EDL station names are compared.

    Case is ignored and each run of digits compares as the number it
    writes, so leading zeros do not count: VIC041 and VIC41 are one
    station, and so are VIC074a and VIC74A, but VIC1003 is not VIC100. The
    key is for comparison only; names are reported as written.

    Args:
        name (str): A station name: a file's, recorder.ini's or a site
            folder's.

    Returns:
        tuple: The lower-case name split into its text and its digit runs,
        each digit run as an int.
    """
    parts = re.split(r"(\d+)", name.lower())
    return tuple(int(p) if i % 2 else p for i, p in enumerate(parts))


def _edl_own_files(site_dir: Path, found: list[Path]) -> list[Path]:
    """Keep the EDL files of the site's own station.

    A PR6-24 keeps writing under the last deployment's name until it is set
    for the new one, and keeps old deployments' day folders and its config.
    A site's folder can therefore hold stamps of another survey's station
    (which stretch the site's span), a few stamps under a placeholder name
    such as "XX_" (some inside the site's own record), a test recording kept
    in a subfolder, or a recorder.ini naming the deployment before: GA's
    AusLAMP Victoria folders VIC041, VIC057 and VIC086 hold an ini naming
    VIC66, VIC84 and VIC124 beside thousands of their own files (workbench
    issue 73).

    The files are grouped by station (mt-io's `parse_edl_station`, without
    a trailing "_" or "-"), with names compared by `_edl_station_key`
    (case-insensitive, digits as numbers: VIC041 = VIC41), and one station
    is kept:

    1. the station named like the site folder, when the files hold one;
    2. else recorder.ini's station (``station_long_identifier``) when files
       carry it and no other station has more files (a tie goes to
       recorder.ini's);
    3. else, when recorder.ini's station has files but another station has
       more, the station with the most files (a tie between such stations
       goes to the first by name);
    4. else (recorder.ini names no station, or no file carries its name)
       every file, with a warning when recorder.ini names a station.

    Files whose name carries no station never count as a station. Keeping
    another station than recorder.ini's is warned once with both names and
    their file counts, and the files left out once with their stations,
    counts and first stamps.

    Args:
        site_dir (Path): Site folder holding recorder.ini; its name is the
            site's.
        found (list of Path): Candidate EDL files.

    Returns:
        list of Path: The kept station's files, in the order of `found`, or
        all of `found` in case 4.
    """
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import parse_edl_station

    ini = str(UoACollection(site_dir).read_recorder_ini().get("station") or "").strip().rstrip("_-")
    groups: dict[tuple | None, list[Path]] = {}
    names: dict[tuple | None, set[str]] = {}
    for f in found:
        name = (parse_edl_station(f) or "").rstrip("_-")
        key = _edl_station_key(name) if name else None
        groups.setdefault(key, []).append(f)
        names.setdefault(key, set()).add(name or "?")
    label = lambda key: "/".join(sorted(names[key]))  # noqa: E731
    ini_key = _edl_station_key(ini) if ini else None
    site_key = _edl_station_key(site_dir.name)
    why = ""
    if site_key in groups:
        keep_key, why = site_key, "named like the site folder"
    elif ini_key is not None and ini_key in groups:
        rivals = {k: len(v) for k, v in groups.items() if k is not None and k != ini_key}
        most = max(rivals.values(), default=0)
        if len(groups[ini_key]) >= most:
            keep_key = ini_key
        else:
            keep_key, why = min((k for k, n in rivals.items() if n == most), key=label), "the most files"
    else:
        if ini:
            logger.warning(f"{site_dir.name}: no EDL file carries recorder.ini's station {ini.lower()!r}: "
                           f"every file kept")
        return found
    keep = groups[keep_key]
    if ini and keep_key != ini_key:
        logger.warning(f"{site_dir.name}: recorder.ini names station {ini!r} ({len(groups.get(ini_key, []))} "
                       f"file(s)) but {label(keep_key)!r} ({len(keep)} file(s)), {why}, is kept")
    other = {label(k): v for k, v in groups.items() if k != keep_key}
    if other:
        whose = f"recorder.ini's {ini.lower()!r}" if keep_key == ini_key else f"the kept {label(keep_key)!r}"
        logger.warning(f"{site_dir.name}: {sum(len(v) for v in other.values())} EDL file(s) named for another "
                       f"station than {whose} left out: "
                       + ", ".join(f"{k} ({len(v)} from "
                                   f"{pd.Timestamp(min(file_start(p, 'edl') for p in v), unit='s'):%Y-%m-%d %H:%M})"
                                   for k, v in sorted(other.items())))
    return keep


def edl_sample_rate(site_dir: Path, files=None) -> float | None:
    """Return the sample rate of an EDL site.

    The rate is read from ``recorder.ini`` (mt-io's
    `UoACollection.read_recorder_ini`). ASCII files carry no header, so
    without recorder.ini the rate comes from consecutive file stamps and
    sample counts (`mt_io.uoa.pr624.infer_sample_rate`, which needs two
    files).

    Args:
        site_dir (Path): Site folder.
        files (list of Path, optional): The site's EDL files; listed with
            `record_files` when None.

    Returns:
        float or None: Sample rate in Hz, or None when neither source gives
        one.
    """
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import infer_sample_rate

    rate = UoACollection(Path(site_dir)).read_recorder_ini().get("sample_rate")
    if rate:
        return float(rate)
    files = files if files is not None else record_files(Path(site_dir), "edl")
    return infer_sample_rate([f for f in files if f.suffix.upper() == ".BX"] or files)


_NO_RECORD_START: list[bool] = []  # set once mt-io without count_samples_and_start has been warned about


def edl_record_start(path: Path) -> int | None:
    """Return where an EDL file's samples start when that is not its name's stamp: after a deployment test run.

    At deployment a PR6-24 is sometimes run for a little while, stopped and
    run again, so the first file of a deployment can hold that test run (one
    trace id, the logger's previous station and location codes) and then
    the record (another id). The record starts at the last trace: mt-io
    reads and counts it alone (`mt_io.uoa.pr624.count_samples`,
    `read_edl_miniseed`), so its samples start minutes after the file
    name's stamp, at the start `mt_io.uoa.pr624.count_samples_and_start`
    gives (AusLAMP Victoria VIC078b_140822050000: 1,800 test samples from
    05:00:00, the record's 34,200 from 05:03:00; workbench issue 76).

    Only miniSEED carries trace ids; an ASCII or empty file gives None
    without being read. An mt-io without `count_samples_and_start` (before
    upstream 525) gives None, with one warning; `ingest_site` then refuses a
    run whose read does not match its plan (`ingest._check_edl_read`).

    Args:
        path (Path): An EDL data file.

    Returns:
        int or None: The record's start in ns since the epoch, or None when
        the file's samples start at its own start (its name's stamp).
    """
    from mt_io.uoa.pr624 import is_miniseed

    if not is_miniseed(path):
        return None
    try:
        from mt_io.uoa.pr624 import count_samples_and_start
    except ImportError:
        if not _NO_RECORD_START:
            _NO_RECORD_START.append(True)
            logger.warning("mt-io has no count_samples_and_start (upstream 525): a file holding the deployment test "
                           "run before the record is planned from its stamp; reinstall the mt-io fork")
        return None
    start = count_samples_and_start(path)[1]
    return None if start is None else int(pd.Timestamp(start).value)


def _lemi424_last_second(path: Path) -> int:
    """Return the UTC second of a LEMI-424 file's last line, reading only the last 4 kB."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        last = f.read().decode(errors="ignore").strip().rsplit("\n", 1)[-1].split()
    when = datetime(*(int(v) for v in last[:6]), tzinfo=timezone.utc)
    return int(when.timestamp())


def span(site_dir: Path, instrument: str, files=None,
         clock_timezone: str = "UTC") -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return the recorded span of a site from its file names.

    LEMI-423: first epoch to the last plus the median spacing (5400 s for
    one file), as `scripts/timing_qc.py` reads it.
    LEMI-424: to the last file's last line plus one second. EDL: to the last
    stamp plus its first channel file's sample count over the rate
    (`edl_sample_rate`); a file of bytes without samples (an all-null block,
    which `mt_workbench.ingest._edl_plan` leaves out) counts 0, with a
    warning, so the span ends at its stamp. Where the first or the last
    stamp's file holds the deployment test run before the record
    (`edl_record_start`), the record's start stands for that stamp. Phoenix: the continuous files' starts as mt-io
    dates them (`phoenix_file_start`) to the last file's end ((size - 128)
    / 4 samples at the header's rate), or the bursts' first stamps when the
    folder holds no continuous file; ``n`` counts the files of one channel.
    Orange Box: the first header stamp to the last end stamp (or, without
    one, the last header plus its records at the header's rate), read on
    the logger clock's zone `clock_timezone`.
    MTU-5A: the tables' earliest FTIM to their latest LTIM plus one second
    (`mt_workbench.mtu5a.span`); ``n`` counts the recordings.

    Args:
        site_dir (Path): Site folder.
        instrument (str): Key of `INSTRUMENTS`.
        files (list of Path, optional): The site's data files; listed with
            `record_files` when None.
        clock_timezone (str): Orange Box only: the zone the logger clock
            ran on (IANA name); UTC by default.

    Returns:
        tuple: ``(start, end, n)``: UTC Timestamps and the number of
        distinct file start stamps.

    Raises:
        FileNotFoundError: If the folder holds no files of the instrument.
    """
    files = files if files is not None else record_files(Path(site_dir), instrument)
    if not files:
        raise FileNotFoundError(f"no {INSTRUMENTS[instrument]['label']} files under {site_dir}")
    if instrument == "phoenix":
        return _phoenix_span(files)
    if instrument == "orangebox":
        return _orange_span(files, clock_timezone)
    if instrument == "mtu5a":
        from .mtu5a import span as mtu5a_span

        return mtu5a_span(files)
    starts = sorted({file_start(f, instrument) for f in files})
    begin = starts[0]
    if instrument == "lemi423":
        spacing = int(np.median(np.diff(starts))) if len(starts) > 1 else INSTRUMENTS[instrument]["file_seconds"]
        end = starts[-1] + spacing
    elif instrument == "lemi424":
        end = _lemi424_last_second(files[-1]) + 1
    else:
        from mt_io.uoa.pr624 import count_samples

        rate = edl_sample_rate(site_dir, files)
        last = next(f for f in files if file_start(f, instrument) == starts[-1])
        n_last = None
        if rate:
            # `mt_workbench.ingest._edl_samples`'s lines (this module does not import ingest): mt-io raises
            # ValueError on a file of bytes without samples (an all-null block); it counts 0 here
            try:
                n_last = count_samples(last)
            except ValueError as exc:
                if "holds bytes but no samples" not in str(exc):
                    raise
                logger.warning(f"{last.name} holds bytes but no samples (an all-null block): counted as 0 samples, "
                               f"the span ends at its stamp")
                n_last = 0
        # a first or last file holding the deployment test run before the record: the record's start
        record = edl_record_start(next(f for f in files if file_start(f, instrument) == starts[0]))
        if record is not None:
            begin = record / 1e9
        record = edl_record_start(last) if n_last else None
        at = starts[-1] if record is None else record / 1e9
        end = at + (n_last / rate if rate else INSTRUMENTS[instrument]["file_seconds"])
    to_ts = lambda s: pd.Timestamp(s, unit="s", tz="UTC")  # noqa: E731
    return to_ts(begin), to_ts(end), len(starts)


def _phoenix_span(files: list[Path]) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return `span` for a Phoenix site's files (see `span`)."""
    continuous = [f for f in files if f.suffix.lower() in PHOENIX_CONTINUOUS] or list(files)
    heads = [(f, phoenix_header(f)) for f in continuous]
    first_channel = min(h["channel"] for _f, h in heads)
    starts, ends = [], []
    for f, h in heads:
        if h["channel"] != first_channel:
            continue
        t0 = phoenix_file_start(h, f.suffix)
        starts.append(t0)
        n = (f.stat().st_size - PHOENIX_HEADER_BYTES) // 4 if f.suffix.lower() != PHOENIX_BURSTS else h["first_n"]
        ends.append(t0 + n / h["sample_rate"])
    to_ts = lambda s: pd.Timestamp(s, unit="s", tz="UTC")  # noqa: E731
    return to_ts(min(starts)), to_ts(max(ends)), len(starts)


def _orange_span(files: list[Path], clock_timezone: str) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return `span` for an Orange Box site's files (see `span`)."""
    from .orangebox import orange_files, to_utc_ns

    listed, _skipped = orange_files(files)
    if not listed:
        raise FileNotFoundError(f"no Orange Box file with a header among {len(files)} file(s)")
    last = listed[-1].end
    begin = to_utc_ns(listed[0].stamp, clock_timezone)
    end = to_utc_ns(last.replace(microsecond=0), clock_timezone) + last.microsecond * 1000
    return pd.Timestamp(begin, unit="ns", tz="UTC"), pd.Timestamp(end, unit="ns", tz="UTC"), len(listed)


def phoenix_metadata_file(recording_dir: Path) -> Path | None:
    """Return the receiver metadata file mt-io takes for a recording folder.

    mt-io's `find_receiver_metadata`: empower_recmeta.json where it is
    present (it holds any correction made after the survey), else
    recmeta.json.

    Args:
        recording_dir (Path): The folder that holds the channel folders.

    Returns:
        Path or None: The file, or None when there is neither.
    """
    from mt_io.phoenix.readers.receiver_metadata import find_receiver_metadata

    found = find_receiver_metadata(Path(recording_dir))
    return Path(found) if found else None


def header_facts(site_dir: Path, instrument: str, files: list[Path]) -> dict:
    """Collect the metadata a LEMI-424, EDL or Phoenix site's files carry.

    Used by `scripts/new_survey.py`. LEMI-424: the reader's first and last
    line (`LEMI424.read_metadata`) give the GPS position, elevation and
    rate; serial and firmware come from the ``.inf`` header the logger
    writes at deployment ("%LEMI424 #0160", "%FIRMWARE Ver.1.4"), which
    mt-io does not read. EDL: the rate (`edl_sample_rate`) and the
    recorder.ini high-gain flags; the files carry no position and no serial.

    Args:
        site_dir (Path): Site folder.
        instrument (str): ``"lemi424"``, ``"edl"``, ``"phoenix"`` or
            ``"orangebox"``.
        files (list of Path): The site's data files.

    Returns:
        dict: ``sample_rate``, ``columns`` (the reader's names for what
        ingest reads) and, as available, ``latitude``, ``longitude``,
        ``elevation``, ``serial``, ``firmware``, ``high_gain`` and
        ``problem`` (a message for the user).

    Phoenix: the receiver metadata file mt-io takes
    (`phoenix_metadata_file`) of the first file's recording gives the
    receiver id (serial), model, software version (firmware), GPS position
    and the channels switched on (renamed ex ey hx hy hz); the rate is the
    first continuous file's header rate.

    Orange Box: the box from the logger report (`mt_workbench.orangebox.report_box`,
    as "hfm2", read in the data files' own folder), the archive's rate (`mt_workbench.orangebox.GRID_RATE`: every
    run is resampled onto the UTC 10 Hz grid) with the header's sampler
    rate in ``header_rate``, the reader's five channels, and no position.

    MTU-5A: the first recording's ``.TBL`` (`mt_workbench.mtu5a.header_facts`).

    Raises:
        ValueError: For any other instrument.
    """
    if instrument == "orangebox":
        from .orangebox import GRID_RATE, ORANGE_NAME, read_header, report_box

        head = read_header(Path(files[0]))
        prefix = ORANGE_NAME.match(Path(files[0]).name).group(1)
        return {"sample_rate": GRID_RATE, "header_rate": head["rate"] if head else None,
                "columns": list(INSTRUMENTS["orangebox"]["channels"]),
                # the report lies beside the data files, which may sit in a subfolder of the site
                # (SA AusLAMP: <site>/raw/); Kalgoorlie keeps them in the site folder itself
                "serial": report_box(Path(files[0]).parent, prefix),
                "problem": "Orange Box files carry no position: set it from the field sheet"}
    if instrument == "mtu5a":
        from .mtu5a import header_facts as mtu5a_facts

        return mtu5a_facts(files)
    if instrument == "phoenix":
        import json

        recording = Path(files[0]).parent.parent
        meta_path = phoenix_metadata_file(recording)
        if meta_path is None:
            return {"problem": f"no {' or '.join(PHOENIX_METADATA)} in {recording}"}
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        continuous = [f for f in files if Path(f).suffix.lower() in PHOENIX_CONTINUOUS]
        rate = phoenix_header(continuous[0])["sample_rate"] if continuous else None
        rename = {"e1": "ex", "e2": "ey", "h1": "hx", "h2": "hy", "h3": "hz"}
        on = [str(c.get("tag", "")).lower() for c in meta.get("chconfig", {}).get("chans", []) if c.get("on")]
        timing = meta.get("timing") or {}
        model = (meta.get("channel_map") or {}).get("receiver_model") or meta.get("receiver_model")
        facts = {"sample_rate": rate, "columns": [rename[t] for t in rename if t in on],
                 "serial": str(meta.get("instid", "")) or None, "firmware": meta.get("sw_version"),
                 "model": PHOENIX_MODELS.get(model, model)}
        if timing.get("gps_lat") is not None:
            facts.update(latitude=round(float(timing["gps_lat"]), 6), longitude=round(float(timing["gps_lon"]), 6),
                         elevation=round(float(timing.get("gps_alt", 0.0)), 1))
        return facts
    if instrument == "lemi424":
        from mt_io.lemi.lemi424 import LEMI424

        head = LEMI424(files[0])
        head.read_metadata()
        facts = {"sample_rate": float(head.sample_rate),
                 "columns": [LEMI424_RENAME.get(c, c) for c in ("bx", "by", "bz", *LEMI424_ELECTRICS)]}
        if head.latitude is not None and (head.latitude, head.longitude) != (0, 0):
            facts.update(latitude=round(float(head.latitude), 6), longitude=round(float(head.longitude), 6),
                         elevation=round(float(head.elevation), 1))
        else:
            facts["problem"] = "no GPS position in the first LEMI-424 file"
        for inf in sorted(Path(site_dir).rglob("*.inf"))[:1]:
            text = inf.read_text(errors="ignore")
            serial = re.search(r"%LEMI424\s*#\s*0*(\d+)", text)
            firmware = re.search(r"%FIRMWARE\s+Ver\.?\s*(\S+)", text)
            facts.update(serial=serial and serial.group(1), firmware=firmware and firmware.group(1))
        return facts
    if instrument == "edl":
        present = {f.suffix.upper() for f in files}
        return {"sample_rate": edl_sample_rate(site_dir, files),
                "columns": [comp for suffix, comp in EDL_FILES.items() if suffix in present],
                "high_gain": recorder_ini_high_gain(site_dir),
                "problem": "EDL files carry no position: set it from the field sheet"}
    raise ValueError(f"header_facts reads lemi424, edl, phoenix and orangebox, not {instrument!r}")


def read_run(instrument: str, files: list[Path], site, site_dir: Path, calibration: Path | None = None):
    """Read one contiguous group of a LEMI-424 or EDL site's files into a RunTS.

    LEMI-423 files are read in `mt_workbench.ingest.ingest_site`.

    LEMI-424: the reader is given every electric column
    (`LEMI424_ELECTRICS`), and the station id, which the reader leaves
    empty, is set. The channels are stored under the workbench's names,
    with their dipole lengths and azimuths from the site
    (`lemi424_stored`). No dipole length is applied to the samples and the
    reader's units are kept.

    EDL: the reader is given the rate from `edl_sample_rate`, the site's
    dipole lengths, its azimuths when `flip_reversed_dipoles` treats a
    180/270 deg azimuth as a reversed pair (the reader's dipole filter then
    carries the sign; nominal 0/90 otherwise), and the position and
    declination when declared (the reader stores the declination's value;
    `mt_workbench.ingest.ingest_site` adds its model and epoch). The x10 terminal box is the reader's default. The magnetic
    sensors are the site's `sensor_type` (`EDL_SENSORS`): "bartington"
    (Mag-03 fluxgates, the long-period setup and the reader's default) or
    "lemi120" (induction coils, the broadband setup), whose response file
    `calibration` is passed to the reader for hx, hy and hz. A coil read with
    the fluxgate chain comes out 2800 times too large with no coil response.
    When the declared `electric_gain` (`edl_electric_gain`) is not 1.0,
    `ELECTRIC_GAIN_FILTER` is appended to the ex and ey chains
    (`add_electric_gain`). Read without its declared gain g, a site's
    apparent resistivity comes out g squared times too large (100 times
    for a gain of 10). A declared `electric_gain_ex` or `electric_gain_ey`
    other than 1.0 then appends that line's own stage
    (`CHANNEL_GAIN_FILTER`, `add_channel_electric_gains`) to its chain only.

    Args:
        instrument (str): ``"lemi424"`` or ``"edl"``.
        files (list of Path): Files of one contiguous run.
        site (SiteConfig): Site settings.
        site_dir (Path): Site folder.
        calibration (Path, optional): The site's resolved `calibration_fn`,
            required for sensor_type lemi120.

    Returns:
        RunTS: The run as mt-io reads it.

    Raises:
        ValueError: If the EDL sample rate is unknown, a magnetic channel
            lacks the expected sensor response, the sensor type is unknown,
            or the instrument is neither lemi424 nor edl.
        FileNotFoundError: If sensor_type lemi120 has no response file.
    """
    files = [Path(f) for f in files]
    if instrument == "lemi424":
        from mt_io.lemi.lemi424 import read_lemi424

        run = read_lemi424(files, e_channels=list(LEMI424_ELECTRICS))
        run.station_metadata.id = site.name
        return lemi424_stored(run, site)
    if instrument == "edl":
        from mt_io.uoa.pr624 import read_uoa

        rate = edl_sample_rate(site_dir)
        if rate is None:
            raise ValueError(f"{site.name}: EDL sample rate unknown (no recorder.ini, and the file "
                             f"stamps do not give one)")
        flip = site.flip_reversed_dipoles
        kwargs = dict(sample_rate=rate, station_id=site.name,
                      dipole_length_ex=site.dipole_length_ex, dipole_length_ey=site.dipole_length_ey,
                      ex_azimuth=site.azimuth_ex if flip else 0.0, ey_azimuth=site.azimuth_ey if flip else 90.0)
        kwargs.update({k: getattr(site, k) for k in ("latitude", "longitude", "elevation", "declination")
                       if getattr(site, k, None) is not None})
        sensor = edl_sensor(site)
        if sensor == "lemi120":
            if calibration is None or not Path(calibration).is_file():
                raise FileNotFoundError(f"{site.name}: sensor_type lemi120 needs the coils' response file "
                                        f"(calibration_fn), got {calibration}")
            kwargs.update(sensor_type="lemi120", **{f"calibration_fn_{c}": str(calibration) for c in ("bx", "by", "bz")})
        run = read_uoa(files, **kwargs)
        for comp in ("hx", "hy", "hz"):
            # a coil file the reader cannot read is logged and leaves the channel with no chain
            names = [f["applied_filter"]["name"] for f in run.dataset[comp].attrs.get("filters") or []] \
                if comp in run.dataset else None
            if names is not None and not any(n.startswith(EDL_SENSORS[sensor]) for n in names):
                raise ValueError(f"{site.name} {comp}: no {sensor} response in the reader's chain {names}")
        add_electric_gain(run, edl_electric_gain(site), site.name)
        add_channel_electric_gains(run, site)
        return run
    raise ValueError(f"read_run reads lemi424 and edl, not {instrument!r}")


def lemi424_stored(run, site):
    """Return a LEMI-424 run with its channels under the names ingest stores.

    mt-io's reader names the columns bx by bz e1 e2 e3 e4, which nothing
    downstream reads (aurora asks for hx, hy, ex and ey). Each channel is
    renamed by `LEMI424_RENAME`; e3, e4 and the two temperatures keep their
    names, and `channels:` then drops what was not wired. A RunTS keeps a
    channel's name in its dataset, in each channel's metadata, in the run's
    channel lists and in the station's channels_recorded, and its setters
    merge rather than replace, so a rename in place brings e1 and e2 back.
    The run is rebuilt instead from new ChannelTS objects (the samples, the
    channel metadata under the new component, the response), with the
    reader's run and station metadata emptied of channels
    (docs/workbench_issues.md 92).

    The metadata the reader leaves at 0 (docs/upstream_issues.md 548) is
    set as the EDL reader sets it: hx, hy and hz take
    `STORED_AZIMUTH_TILT`; ex and ey take their `dipole_length` from the
    site, tilt 0 and the azimuth of the frame they are stored in, the
    site's azimuth modulo 180 deg (a line laid at 180 or 270 deg is the
    reversed pair, flipped by `mt_workbench.ingest._standardise_e_orientation`).
    `translated_azimuth` is not set, as on the EDL path. No sample is
    changed.

    Args:
        run (RunTS): The run as mt-io's reader returns it.
        site (SiteConfig): Site settings.

    Returns:
        RunTS: The rebuilt run.
    """
    from mt_timeseries import ChannelTS
    from mt_timeseries.run_ts import RunTS

    frame = {"ex": float(site.azimuth_ex) % 180.0, "ey": float(site.azimuth_ey) % 180.0}
    channels = []
    for var in list(run.dataset.data_vars):
        old = getattr(run, var)
        md = old.channel_metadata.copy()
        comp = LEMI424_RENAME.get(var, var)
        md.component = comp
        if comp in STORED_AZIMUTH_TILT:
            md.measurement_azimuth, md.measurement_tilt = STORED_AZIMUTH_TILT[comp]
        elif comp in frame:
            md.measurement_azimuth, md.measurement_tilt = frame[comp], 0.0
            md.dipole_length = float(site.dipole_length_ex if comp == "ex" else site.dipole_length_ey)
        channels.append(ChannelTS(old.channel_metadata.type, data=old.ts, channel_metadata=md,
                                  channel_response=old.channel_response))
    run_md = run.run_metadata.copy()
    for key in list(run_md.channels.keys()):
        run_md.channels.remove(key)
    for attr in ("channels_recorded_magnetic", "channels_recorded_electric", "channels_recorded_auxiliary"):
        setattr(run_md, attr, [])
    station_md = run.station_metadata.copy()
    for key in list(station_md.runs.keys()):
        station_md.runs.remove(key)
    station_md.channels_recorded = []
    return RunTS(array_list=channels, run_metadata=run_md, station_metadata=station_md)


def edl_electric_gain(site) -> float:
    """Return an EDL site's declared electric chain gain, 1.0 (no filter) when unset."""
    value = getattr(site, "electric_gain", None)
    return 1.0 if value is None else float(value)


def add_electric_gain(run, gain: float, tag: str = "") -> list[str]:
    """Append `ELECTRIC_GAIN_FILTER` to the ex and ey filter chains of a run.

    The samples are left unchanged. The coefficient filter (microVolt in
    and out) goes into ``run.filters`` and each channel's applied-filter
    list, as `mt_workbench.ingest._apply_h_scale` adds its scale, so the archive
    carries it and calibration divides by it.

    Args:
        run (RunTS): Run to modify in place.
        gain (float): Electric chain gain. A gain of 1.0, the default when
            none is declared, adds nothing.
        tag (str): Label for the caller; not used in the filter.

    Returns:
        list of str: The electric channels the filter was added to (ex, ey,
        whichever the run carries).
    """
    if not gain or float(gain) == 1.0:
        return []
    from mt_metadata.timeseries.filters import CoefficientFilter

    coef = CoefficientFilter()
    coef.name = ELECTRIC_GAIN_FILTER
    coef.gain = float(gain)
    coef.units_in = "microVolt"
    coef.units_out = "microVolt"
    coef.comments = "electric chain gain declared from the field notes"
    run.filters[coef.name] = coef
    done = []
    for comp in ("ex", "ey"):
        if comp not in run.dataset:
            continue
        chain = list(run.dataset[comp].attrs.get("filters") or [])
        chain.append({"applied_filter": {"applied": True, "name": coef.name, "stage": len(chain) + 1}})
        run.dataset[comp].attrs["filters"] = chain
        done.append(comp)
    return done


def channel_electric_gains(site) -> dict[str, float]:
    """Return an EDL site's declared per-line electric gains other than 1.0, {comp: gain}."""
    out = {}
    for comp in ("ex", "ey"):
        value = getattr(site, f"electric_gain_{comp}", None)
        if value is not None and float(value) != 1.0:
            out[comp] = float(value)
    return out


def add_channel_electric_gains(run, site) -> list[str]:
    """Append each declared per-line gain (`CHANNEL_GAIN_FILTER`) to that channel's chain alone.

    Composes with `add_electric_gain` as that stage composes with the
    reader's chain: one more forward coefficient filter (microVolt in and
    out) at the end of the chain, so calibration divides the channel by it
    and the archive keeps the stored words. Called after `add_electric_gain`,
    so a line declared both carries electric_gain x electric_gain_<c>.

    Args:
        run (RunTS): Run to modify in place.
        site (SiteConfig): Site settings (`electric_gain_ex`, `electric_gain_ey`).

    Returns:
        list of str: The channels a stage was added to.
    """
    gains = channel_electric_gains(site)
    if not gains:
        return []
    from mt_metadata.timeseries.filters import CoefficientFilter

    done = []
    for comp, gain in gains.items():
        if comp not in run.dataset:
            continue
        coef = CoefficientFilter()
        coef.name = CHANNEL_GAIN_FILTER[comp]
        coef.gain = gain
        coef.units_in = "microVolt"
        coef.units_out = "microVolt"
        coef.comments = f"electric chain gain of the {comp} line alone, declared (electric_gain_{comp})"
        run.filters[coef.name] = coef
        chain = list(run.dataset[comp].attrs.get("filters") or [])
        chain.append({"applied_filter": {"applied": True, "name": coef.name, "stage": len(chain) + 1}})
        run.dataset[comp].attrs["filters"] = chain
        done.append(comp)
    return done


def recorder_ini_high_gain(site_dir: Path) -> list[str] | None:
    """List the EDL channels flagged ``channel_n_high_gain=1`` in recorder.ini.

    EDM 021 4.2.8 defines one flag per channel, default low. mt-io's
    `UoACollection.read_recorder_ini` folds the six into one boolean
    (docs/upstream_issues.md 21), so the first recorder.ini under
    `site_dir`, the one mt-io takes, is parsed here. Channel n is the file
    extension its ``channel_n_long_id`` names (BX .. EY, the reader's
    hx .. ey), else UoA's order 0-4 = BX BY BZ EX EY. The result is
    informational: `electric_gain` records the electric chain gain from the
    field notes, which is separate from this PR6-24 pre-amplifier setting,
    and `mt_workbench.ingest._electric_gain` uses the result for a warning.

    Args:
        site_dir (Path): Site folder.

    Returns:
        list of str or None: Flagged channels in hx, hy, hz, ex, ey order;
        an empty list when every flag is 0; None when there is no readable
        recorder.ini or it sets no gain flag.
    """
    import configparser

    found = sorted(Path(site_dir).rglob("recorder.ini"))
    if not found:
        return None
    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read(found[0], encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as exc:
        logger.warning(f"could not read {found[0]}: {exc}")
        return None
    if not parser.has_section("recorder"):
        return None
    section = parser["recorder"]
    order = list(EDL_FILES)  # .BX .BY .BZ .EX .EY
    flags = {}
    for n in range(6):
        flag = section.get(f"channel_{n}_high_gain")
        if flag is None:
            continue
        ident = str(section.get(f"channel_{n}_long_id") or (order[n][1:] if n < len(order) else "")).strip()
        comp = EDL_FILES.get("." + ident.upper())
        if comp is not None:
            flags[comp] = flag.strip() not in ("", "0")
    if not flags:
        return None
    return [c for c in INSTRUMENTS["edl"]["channels"] if flags.get(c)]


def edl_sensor(site) -> str:
    """Return an EDL site's magnetic sensor type.

    Args:
        site (SiteConfig): Site settings.

    Returns:
        str: Key of `EDL_SENSORS`, the site's `sensor_type` or
        "bartington" when unset.

    Raises:
        ValueError: If `sensor_type` is not a key of `EDL_SENSORS`.
    """
    sensor = str(getattr(site, "sensor_type", None) or "bartington").strip().lower()
    if sensor not in EDL_SENSORS:
        raise ValueError(f"{site.name}: sensor_type {sensor!r} is not one of {', '.join(EDL_SENSORS)}")
    return sensor
