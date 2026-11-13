# -*- coding: utf-8 -*-
"""
Convert Phoenix binary calibration files (.scal, .rxcal) to EMpower's JSON form

A Phoenix MTU-5C or MTU-8A survey brings its calibrations as binary files,
``<coil serial>_<epoch hex>.scal`` for a coil and ``<receiver>_<epoch
hex>.rxcal`` for a receiver, the epoch being the calibration time in UTC
seconds. mt-io and mth5 read only the JSON form that EMpower exports
(``.scal.json``, ``.rxcal.json``; `mt_io.phoenix.readers.calibrations.
PhoenixCalibration`), and `mt_workbench.phoenix` takes a site's tables from
a folder of such JSON files. This script writes the JSON form of binary
files, from a folder, single files or the members of a .zip read in place.

The layout below was derived from 24 coils and 12 receivers that exist in
both forms with the same serial and epoch (the Kalkaroo set of November
2020). All numbers are little-endian; text fields are ASCII padded with
zero bytes. Offsets are from the start of the file.

Common header (256 bytes, both kinds):

    0    4 bytes   magic: 05 06 00 01 (.scal), 06 06 00 01 (.rxcal)
    4    uint32    calibration time, UTC seconds = the name's hex = JSON
                   `timestamp_utc`
    8    char[10]  receiver serial (JSON `inst_serial`): for a coil, the
                   receiver it was calibrated on
    18   uint8     1 on MTU-5C, 4 on MTU-8A receivers (not in the JSON)
    19   text      receiver board ids and part numbers ("031CB1",
                   "BTM01-I", "2912", "0001002FX"; not in the JSON)
    59   char[10]  .scal only: the coil serial (JSON `sensor_serial`),
                   followed by "MTC-150", "UNK_HWV", "UNK_FWV", "FP_XYZ"
                   (not in the JSON)
    111  float32   latitude, deg (JSON `latitude`)
    115  float32   longitude, deg (JSON `longitude`)
    119  float32   altitude, m (JSON `altitude`)
    125  char[7+]  receiver model code, RMT03-D, RMT03-G or RMT05 (JSON
                   `instrument_model`); JSON `instrument_type` is MTU-5C for
                   RMT03-*, MTU-8A for RMT05 (`mt_workbench.instruments.
                   PHOENIX_MODELS`)
    the rest     zeros and words that look like memory addresses; not used

.scal (2516 bytes): one channel block from byte 256: board ids, the
receiver channel tag the coil was calibrated on at 286 (char[2], "H1" or
"H2", JSON `cal_data[0].tag`), the number of records at 339 (uint8, 68
in every file seen), then the records from 340, 32 bytes each:

    +0  float32  frequency, Hz
    +4  float32  real part of the response, mV per nT
    +8  float32  imaginary part
    +12 20 bytes not decoded (repeat within a band; not in the JSON)

in descending frequency. The JSON holds the same records in ascending
frequency, `magnitude` = |re + i im| and `phs_deg` = atan2(im, re) in
degrees.

.rxcal (256 + 1464 bytes per channel: 7576 bytes for the five channels of
an MTU-5C, 11968 for the eight of an MTU-8A): channel blocks of 1464
bytes from byte 256. Each holds board ids, the channel tag at +30
(char[2]: E1 E2 H1 ... H6, JSON `cal_data[i].tag`) and four bands, each a
band index byte, a 10-character band code and a uint8 record count
followed by that many 32-byte records laid out as in the .scal:

    00150000BC  13 records, 1024-10240 Hz   JSON chan_data[0], lp 10000
    811D0000BC   9 records,  110-2048 Hz    JSON chan_data[1], lp 1000
    821D0000BC  10 records,   15-225 Hz     JSON chan_data[2], lp 100
    831D0000BC  10 records,  0.2-15 Hz      JSON chan_data[3], lp 10

(the records of a band are not all in frequency order). The JSON's value
at a recorded frequency is |re + i im| and atan2(im, re) - 360 f tau deg,
wrapped to [-180, 180): a delay tau of 1.4666667 ms (0.528 deg/Hz, held as
a float32, `DELAY_S`) removed from every record, the same on all 12
receivers; its source in the bytes was not found. EMpower's values differ
from these by up to 1.0e-7 relative in magnitude and 1.0e-5 deg in phase,
the size of float32 arithmetic (`compare` allows a receiver 2.4e-7 and
2e-5 deg). Below each band's lowest recorded frequency the JSON
holds a curve that is not in the file: about 30 to 56 points from 1e-5 Hz
up, magnitude near 1 and phase near a pure delay, a model that EMpower
fits to the records and does not write down (rational fits of the records
reproduce it to 1e-6 in the lowest band only). This script therefore
takes that part of each band from an EMpower ``.rxcal.json`` of the same
receiver (`--curve-from`, by default the one of nearest epoch in the
output folder that EMpower wrote, not one this script wrote), and names it
in the key `curve_below_records_from`. A receiver with no such file is not
converted. The 150 Hz and 30 Hz recordings of a receiver set to lp 10000
use only that part (their band is below 1024 Hz), so the receiver curve
of a converted rxcal is the measured one only from 1024 Hz up.

Each JSON written carries EMpower's keys (`empower_version` null) and
`converted_from`, the binary file's name. An output file that exists
already is never replaced: it is compared value by value with the
conversion (metadata keys and every frequency, magnitude and phase) and
reported as equal or different: a coil's values within 2 units of their
8th significant digit (EMpower's coil JSON is the binary's float32 printed
to 8 digits; the 24 coils in both forms agree to 0 units), a receiver's
within those 2 units or the float32 tolerances above.

Exit status: 0 done (every existing file equal), 1 an existing file
differs or a file was refused, 2 a usage error.

Usage:
    python scripts/phoenix_cal_convert.py <source> <out_dir> [--curve-from DIR] [--dry-run]

<source> is a folder, a .zip or one .scal/.rxcal file.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import zipfile
from pathlib import Path

MAGIC = {b"\x05\x06\x00\x01": "scal", b"\x06\x06\x00\x01": "rxcal"}
HEADER_BYTES = 256
CHANNEL_BYTES = 1464  # one .rxcal channel block
RECORD_BYTES = 32
SCAL_COUNT_AT = 339
SCAL_RECORDS_AT = 340
TAG_AT = 30  # within a channel block
BAND_CODE = re.compile(rb"([\x00-\x03])([0-9A-F]{4}0000BC)")
# the delay removed from the phase of every rxcal record, s: 0.528 deg/Hz / 360 as a float32
DELAY_S = struct.unpack("<f", struct.pack("<f", 0.528 / 360.0))[0]
MODELS = {"RMT03-D": "MTU-5C", "RMT03-G": "MTU-5C", "RMT05": "MTU-8A"}
NAME = re.compile(r"^(\d+)_([0-9A-Fa-f]{8})\.(scal|rxcal)$")
# a converted value agrees with an existing one within this many units of its 8th significant digit (a coil's
# values: only this), or, for a receiver, within the float32 arithmetic of EMpower: RELATIVE_TOLERANCE of a
# frequency or magnitude, PHASE_TOLERANCE_DEG of a phase
DIGITS_TOLERANCE = 2
RELATIVE_TOLERANCE = 2.4e-7
PHASE_TOLERANCE_DEG = 2e-5


def _text(b: bytes, start: int, length: int) -> str:
    """Return the zero-padded ASCII field at `start`."""
    return b[start:start + length].split(b"\0", 1)[0].decode("ascii").strip()


def _g8(x: float) -> float:
    """Round to 8 significant digits, as EMpower prints a float32."""
    return float(f"{x:.8g}")


def _records(b: bytes, at: int, n: int) -> list[tuple[float, float, float]]:
    """Return `n` records (frequency, real, imaginary) from byte `at`."""
    if at + n * RECORD_BYTES > len(b):
        raise ValueError(f"{n} records from byte {at} run past the end ({len(b)} bytes)")
    return [struct.unpack_from("<3f", b, at + k * RECORD_BYTES) for k in range(n)]


def header(b: bytes) -> dict:
    """Return the header fields of a binary .scal or .rxcal in the JSON's keys.

    Raises:
        ValueError: If the magic bytes are not a .scal's or an .rxcal's, or
            the model code is not a known receiver.
    """
    kind = MAGIC.get(b[:4])
    if kind is None:
        raise ValueError(f"magic {b[:4].hex()} is neither a .scal nor an .rxcal")
    model = _text(b, 125, 10)
    if model not in MODELS:
        raise ValueError(f"model code {model!r} at byte 125 is not one of {sorted(MODELS)}")
    lat, lon, alt = struct.unpack_from("<3f", b, 111)
    return {"kind": kind, "timestamp_utc": struct.unpack_from("<I", b, 4)[0], "inst_serial": _text(b, 8, 10),
            "instrument_model": model, "instrument_type": MODELS[model], "latitude": _g8(lat),
            "longitude": _g8(lon), "altitude": _g8(alt), "sensor_serial": _text(b, 59, 10) if kind == "scal" else None}


def _base(h: dict, file_type: str, n_channels: int, source: str) -> dict:
    """Return the JSON's top-level keys, in EMpower's order."""
    out = {"altitude": h["altitude"], "empower_version": None, "file_type": file_type, "file_version": "1.0",
           "inst_serial": h["inst_serial"], "instrument_model": h["instrument_model"],
           "instrument_type": h["instrument_type"], "latitude": h["latitude"], "longitude": h["longitude"],
           "manufacturer": "Phoenix Geophysics", "num_channels": n_channels}
    if h["sensor_serial"] is not None:
        out["sensor_serial"] = h["sensor_serial"]
    out["timestamp_utc"] = h["timestamp_utc"]
    out["converted_from"] = source
    return out


def _table(points: list[tuple[float, float, float]]) -> dict:
    """Return a JSON `chan_data` entry from (frequency, magnitude, phase deg) points, ascending."""
    points = sorted(points)
    return {"num_records": len(points), "freq_Hz": [p[0] for p in points], "magnitude": [p[1] for p in points],
            "phs_deg": [p[2] for p in points]}


def scal_to_json(b: bytes, source: str) -> dict:
    """Return the JSON form of a binary .scal.

    Args:
        b (bytes): The file.
        source (str): Its name, for `converted_from`.

    Raises:
        ValueError: If the file is not a .scal of the layout above.
    """
    h = header(b)
    if h["kind"] != "scal":
        raise ValueError(f"{source}: not a .scal")
    n = b[SCAL_COUNT_AT]
    if len(b) != SCAL_RECORDS_AT + n * RECORD_BYTES:
        raise ValueError(f"{source}: {len(b)} bytes, {n} records need {SCAL_RECORDS_AT + n * RECORD_BYTES}")
    points = [(_g8(f), _g8(math.hypot(re_, im)), _g8(math.degrees(math.atan2(im, re_))))
              for f, re_, im in _records(b, SCAL_RECORDS_AT, n)]
    out = _base(h, "sensor calibration", 1, source)
    out["cal_data"] = [{"tag": _text(b, HEADER_BYTES + TAG_AT, 2), "num_of_responses": 1,
                        "chan_data": [_table(points)]}]
    return out


def rxcal_bands(b: bytes, source: str = "") -> list[tuple[str, list[tuple[str, list]]]]:
    """Return the channel tags and the recorded bands of a binary .rxcal.

    Returns:
        list: (tag, [(band code, [(frequency, real, imaginary), ...]), ...])
        per channel, in file order.

    Raises:
        ValueError: If the size is not 256 + 1464 per channel or a channel
            block does not hold four bands that fill it.
    """
    if (len(b) - HEADER_BYTES) % CHANNEL_BYTES:
        raise ValueError(f"{source}: {len(b)} bytes is not {HEADER_BYTES} + {CHANNEL_BYTES} per channel")
    channels = []
    for c in range((len(b) - HEADER_BYTES) // CHANNEL_BYTES):
        off = HEADER_BYTES + c * CHANNEL_BYTES
        end = off + CHANNEL_BYTES
        tag = _text(b, off + TAG_AT, 2)
        bands, at = [], off
        while True:
            hit = BAND_CODE.search(b, at, end)
            if hit is None:
                break
            n = b[hit.end()]
            first = hit.end() + 1
            if int(hit.group(1)[0]) != len(bands):
                raise ValueError(f"{source} {tag}: band {hit.group(2).decode()} has index {hit.group(1)[0]}, "
                                 f"expected {len(bands)}")
            bands.append((hit.group(2).decode(), _records(b, first, n)))
            at = first + n * RECORD_BYTES
        if len(bands) != 4 or at != end:
            raise ValueError(f"{source} {tag}: {len(bands)} bands ending at {at - off} of {CHANNEL_BYTES} bytes")
        channels.append((tag, bands))
    return channels


def rxcal_to_json(b: bytes, source: str, curve_from: dict, curve_name: str) -> dict:
    """Return the JSON form of a binary .rxcal.

    Args:
        b (bytes): The file.
        source (str): Its name, for `converted_from`.
        curve_from (dict): An EMpower .rxcal.json of the same receiver, whose
            curve below each band's lowest recorded frequency is taken.
        curve_name (str): That file's name, for `curve_below_records_from`.

    Raises:
        ValueError: If the file is not an .rxcal of the layout above, or
            `curve_from` is of another receiver or lacks a channel or band.
    """
    h = header(b)
    if h["kind"] != "rxcal":
        raise ValueError(f"{source}: not an .rxcal")
    if str(curve_from.get("inst_serial")) != h["inst_serial"]:
        raise ValueError(f"{source}: {curve_name} is of receiver {curve_from.get('inst_serial')}")
    theirs = {ch["tag"]: ch["chan_data"] for ch in curve_from["cal_data"]}
    cal_data = []
    for tag, bands in rxcal_bands(b, source):
        if tag not in theirs or len(theirs[tag]) != len(bands):
            raise ValueError(f"{source}: {curve_name} has no {len(bands)} bands for {tag}")
        tables = []
        for (code, recs), their in zip(bands, theirs[tag]):
            lowest = min(r[0] for r in recs)
            points = [(_g8(f), _g8(math.hypot(re_, im)),
                       _g8((math.degrees(math.atan2(im, re_)) - 360.0 * DELAY_S * f + 180.0) % 360.0 - 180.0))
                      for f, re_, im in recs]
            below = [(f, m, p) for f, m, p in zip(their["freq_Hz"], their["magnitude"], their["phs_deg"])
                     if f < lowest * (1 - 1e-6)]
            tables.append(_table(below + points))
        cal_data.append({"tag": tag, "num_of_responses": len(tables), "chan_data": tables})
    out = _base(h, "receiver calibration", len(cal_data), source)
    out["curve_below_records_from"] = curve_name
    out["cal_data"] = cal_data
    return out


def _close(a: float, b: float, phase: bool = False, coil: bool = False) -> bool:
    """Whether two values agree.

    A phase agrees across 360 deg. For a coil (`coil`), within
    DIGITS_TOLERANCE units of the 8th significant digit; for a receiver,
    a phase within PHASE_TOLERANCE_DEG and another value within those
    units or RELATIVE_TOLERANCE.
    """
    if a == b:
        return True
    d = abs(a - b)
    if phase:
        d = min(d % 360.0, 360.0 - d % 360.0)
    scale = max(abs(a), abs(b))
    digits = DIGITS_TOLERANCE * 10 ** (math.floor(math.log10(scale)) - 7)
    if coil:
        return d <= digits
    if phase:
        return d <= PHASE_TOLERANCE_DEG
    return d <= max(digits, RELATIVE_TOLERANCE * scale)


METADATA_KEYS = ("file_type", "inst_serial", "instrument_model", "instrument_type", "sensor_serial",
                 "timestamp_utc", "latitude", "longitude", "altitude")


def compare(ours: dict, theirs: dict) -> list[str]:
    """Return the differences between two calibration JSONs, [] when they agree.

    The metadata keys of `METADATA_KEYS` (numbers within the tolerance of
    `_close`, a coil's when `ours` is a sensor calibration), the channel
    tags, band and record counts and every frequency, magnitude and phase
    are compared.
    """
    out = []
    coil = ours.get("file_type") == "sensor calibration"
    for key in METADATA_KEYS:
        a, b = ours.get(key), theirs.get(key)
        if isinstance(a, float) or isinstance(b, float):
            if a is None or b is None or not _close(float(a), float(b), coil=coil):
                out.append(f"{key}: {a} vs {b}")
        elif str(a) != str(b) and not (a is None and b is None):
            out.append(f"{key}: {a} vs {b}")
    tags_a = [c["tag"] for c in ours["cal_data"]]
    tags_b = [c["tag"] for c in theirs["cal_data"]]
    if tags_a != tags_b:
        return out + [f"channels {tags_a} vs {tags_b}"]
    for ca, cb in zip(ours["cal_data"], theirs["cal_data"]):
        if len(ca["chan_data"]) != len(cb["chan_data"]):
            out.append(f"{ca['tag']}: {len(ca['chan_data'])} vs {len(cb['chan_data'])} bands")
            continue
        for k, (ta, tb) in enumerate(zip(ca["chan_data"], cb["chan_data"])):
            if len(ta["freq_Hz"]) != len(tb["freq_Hz"]):
                out.append(f"{ca['tag']} band {k}: {len(ta['freq_Hz'])} vs {len(tb['freq_Hz'])} records")
                continue
            for name in ("freq_Hz", "magnitude", "phs_deg"):
                bad = 0
                for x, y in zip(ta[name], tb[name]):
                    bad += not _close(x, y, phase=name == "phs_deg", coil=coil)
                if bad:
                    out.append(f"{ca['tag']} band {k} {name}: {bad} of {len(ta[name])} differ")
    return out


def write_json(obj: dict, path: Path) -> None:
    """Write a calibration JSON, keys in EMpower's order, indented by one space."""
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")


def sources(src: Path) -> list[tuple[str, bytes]]:
    """Return (file name, bytes) of every .scal and .rxcal in a folder, a .zip or one file."""
    if src.is_dir():
        files = sorted(p for p in src.iterdir() if NAME.match(p.name))
        return [(p.name, p.read_bytes()) for p in files]
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            members = sorted(m for m in z.namelist() if NAME.match(Path(m).name))
            return [(Path(m).name, z.read(m)) for m in members]
    if NAME.match(src.name):
        return [(src.name, src.read_bytes())]
    raise ValueError(f"{src}: not a folder, a .zip or a .scal/.rxcal file")


def empower_rxcal(receiver: str, epoch: int, folder: Path) -> Path | None:
    """Return the EMpower-written ``<receiver>_*.rxcal.json`` of `folder` nearest in epoch, or None."""
    best = None
    for p in sorted(folder.glob(f"{receiver}_*.rxcal.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        if "converted_from" in obj:
            continue
        gap = abs(int(obj.get("timestamp_utc", 0)) - epoch)
        if best is None or gap < best[0]:
            best = (gap, p)
    return None if best is None else best[1]


def convert(name: str, b: bytes, curve_dir: Path) -> dict:
    """Return the JSON form of one binary file, checking its name against its header.

    Raises:
        ValueError: If the name's serial or epoch is not the header's, or
            the conversion refuses (`scal_to_json`, `rxcal_to_json`).
    """
    serial, hexepoch, kind = NAME.match(name).groups()
    h = header(b)
    if h["kind"] != kind or h["timestamp_utc"] != int(hexepoch, 16):
        raise ValueError(f"{name}: header is a {h['kind']} of epoch {h['timestamp_utc']:08X}")
    if kind == "scal":
        if h["sensor_serial"] != serial:
            raise ValueError(f"{name}: header coil serial {h['sensor_serial']}")
        return scal_to_json(b, name)
    if h["inst_serial"] != serial:
        raise ValueError(f"{name}: header receiver {h['inst_serial']}")
    ref = empower_rxcal(serial, h["timestamp_utc"], curve_dir)
    if ref is None:
        raise ValueError(f"{name}: no EMpower {serial}_*.rxcal.json in {curve_dir} to take the curve below the "
                         f"records from")
    return rxcal_to_json(b, name, json.loads(ref.read_text(encoding="utf-8")), ref.name)


def main(argv=None) -> int:
    """Convert, compare with existing files, print one line per file and return the exit status."""
    p = argparse.ArgumentParser(prog="phoenix_cal_convert.py",
                                description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("source", type=Path, help="a folder, a .zip or one .scal/.rxcal file")
    p.add_argument("out_dir", type=Path, help="the folder the .scal.json and .rxcal.json files go to")
    p.add_argument("--curve-from", type=Path, default=None,
                   help="folder of EMpower .rxcal.json files for the curve below the records (default out_dir)")
    p.add_argument("--dry-run", action="store_true", help="convert and compare, write nothing")
    args = p.parse_args(argv)
    if not args.out_dir.is_dir():
        print(f"ERROR out_dir {args.out_dir} is not a folder", file=sys.stderr)
        return 2
    curve_dir = args.curve_from or args.out_dir
    status = 0
    for name, b in sources(args.source):
        target = args.out_dir / f"{name}.json"
        try:
            obj = convert(name, b, curve_dir)
        except ValueError as exc:
            print(f"{name}: refused: {exc}")
            status = 1
            continue
        if target.exists():
            diffs = compare(obj, json.loads(target.read_text(encoding="utf-8")))
            verdict = "equal, kept" if not diffs else "DIFFERS, kept: " + "; ".join(diffs)
            print(f"{name}: {target.name} exists, {verdict}")
            status = status or (1 if diffs else 0)
            continue
        if not args.dry_run:
            write_json(obj, target)
        source = obj.get("curve_below_records_from")
        extra = f" (curve below the records from {source})" if source else ""
        print(f"{name}: {'would write' if args.dry_run else 'wrote'} {target.name}{extra}")
    return status


if __name__ == "__main__":
    sys.exit(main())
