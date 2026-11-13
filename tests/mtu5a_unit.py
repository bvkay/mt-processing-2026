# -*- coding: utf-8 -*-
"""
Unit test for the Phoenix MTU-5A reader of mt-workbench (mt_workbench.mtu5a)

Synthetic MTU-5A recordings are written here with numpy and struct, from
the layout in mt_workbench.mtu5a's docstring: a `.TS4` of 1 s records (a
32-byte tag and 150 scans of five 3-byte samples) and a `.TBL` of 25-byte
type-coded blocks. Each is a site of a scratch survey (instrument mtu5a,
150 Hz) and is ingested with `ingest_site` into a scratch workspace; the
archives are read back with mth5 and compared with the counts and tags
written here, never through the reader under test. The channel numbers of
the synthetic table are not in the ex ey hx hy hz order (ex 2, ey 1, hx 3,
hy 5, hz 4), so that a reader that ignores them is caught. When the Oak Dam
raw folder (`OAK_DAM`) is present, one real recording (191207/4759C07A) is
copied into scratch and ingested too; without it that part is SKIPPED.

Usage:
    python tests/mtu5a_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - M1: `read_table` of a synthetic table does not give the int32, float64,
    text and time values by each block's type byte, keeps the trailing
    block, or `table_degrees("3103.188,S")` is not -(31 + 3.188 / 60);
  - M2: a three-record recording does not ingest as one run sr150_0001
    starting at its first tag to the nanosecond, 450 samples per channel,
    each channel equal (int32, sample for sample) to the counts written
    for its table channel number, with units "digital counts" (mt_metadata's
    name for the "counts" set at read); or a channel's chain
    is not, by name, gain and units, [dipole L/1000 mV/km->mV, EGN mV->mV,
    2^23/(1000 FSCV) mV->count] for ex and ey and [HNOM nT->mV, HATT, HGN,
    the converter] for hx, hy and hz; or the run comment lacks the
    mtu5a, mtu5a_time, mtu5a_units or mtu5a_flags piece;
  - M3: the flag table beside the archive does not hold the saturation
    of record 1 on ex (bit CHEX - 1) and of records 1-2 on hy, the status
    byte of record 1, the clock status of record 2 and nothing else, each
    from its record's tag to the next second; or a flagged sample differs
    from the one written;
  - M4: the recording with its record 2 of 5 removed does not give two
    runs, records 0-1 and 2-3, the second starting at the tag after the gap
    with an "mtu5a_gap: 1 s" piece;
  - M5: any of these is ingested, or leaves an archive, or its error does
    not name what is wrong: a .TS4 without its .TBL, two receivers in one
    folder, two overlapping recordings, a table whose FTIM is 2 s off the
    first tag, records of four channels, a last record cut short, the site
    declared at 1000 Hz, a declared serial of another receiver, two
    recordings whose EGN differ;
  - M6: `detect_instrument` does not give "mtu5a" for the site folder and
    None for a folder of .TS2 and .TS3 files only, `file_start` is not the
    first tag, `span` is not FTIM to LTIM + 1 s, or the ingest of a folder
    holding .TS2 and .TS3 files beside the .TS4 does not log one line
    naming them;
  - M7 (OAK_DAM present): the real 4759C07A does not ingest as one run
    starting at its first tag (read here) with 150 samples per record of
    its file, its counts differ from a decode written here on any sample,
    or the raw folder 191207 (receivers 4573 and 4759) is not refused;
  - M8: a recording whose ex is pinned at 0.941 of full scale (the
    receiver's clip) on 2 % of its samples is not recorded "saturated?" in
    the run comment's dc level with a rail share within 0.1 % of 2 %, or
    one whose ey is pinned at 0.80 of full scale on 2 % is; or the comment
    does not record each channel's rail as 0.9 x 0.941 x 2^23 counts, in
    counts (not "V");
  - M9: under swap_e, saturation bits on the table's ex column are not
    named ey by both the run comment's mtu5a_flags piece (ex 0 ey 3) and
    the flag table (one ey row of 3 records);
  - M10: two recordings of one site that differ only in HXSN do not plan
    (`plan_runs`) as one site of two runs, or a run's hx channel comment
    (`channel_chain`) does not name its own recording's coil; or two that
    differ in EGN are planned, or refused without "differ in EGN";
  - M11: a site whose own entry holds any one of the keys of another
    recorder (recording, calibration_dir, coil_hx, coil_hy, coil_hz,
    h_scale, sensor_type, electric_gain, calibration_fn, h_from,
    electric_full_scale_uv, magnetic_full_scale_nt, clock_timezone,
    clock_drift_s, time_base) is ingested, leaves an archive, or is refused
    without naming the key; or a site with swap_h is refused;
  - the mutations do not trip: tag times read 1 s late (M2), an FTIM
    tolerance of 10 s (M5), no absolute rail (M8: the relative rail flags
    ey), the comment's flag counts by the recorded names (M9), the
    coil serials put back into CHAIN_KEYS (M10: "differ in HXSN"), and
    calibration_dir dropped from the refused Phoenix keys (M11).
"""

from __future__ import annotations

import shutil
import struct
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import mt_workbench.mtu5a as mtu5a  # noqa: E402
from mt_workbench.dclevel import parse_level_note  # noqa: E402
import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.instruments import detect_instrument, file_start, span  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.timefreq import _real_runs  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("mtu5a_unit")
DATA = SCRATCH / "data"
WORKSPACE = SCRATCH / "workspace"
OAK_DAM = Path(r"D:\MT_DATA\MT_Oak_Dam\01-RAW\01-RAW")
REAL = ("191207", "4759C07A")
START = datetime(2019, 12, 7, 1, 9, 50)
SERIAL = 4573
ORDER = {"ex": 2, "ey": 1, "hx": 3, "hy": 5, "hz": 4}  # table channel numbers, not in the stored order
TABLE = {"SNUM": 4573, "FSCV": 2.45, "EGN": 4, "HGN": 1, "HATT": 0.233, "HNOM": 100.0, "EXLN": 100.0,
         "EYLN": 90.0, "SRL4": 150, "SITE": "SYN 1", "LATG": "3103.188,S", "LNGG": "13700.782,E", "ELEV": 107,
         "HXSN": "BMT1", "HYSN": "BMT2", "HZSN": "BMT3", "VER": "3112G3", "HW": "MTU5A"}


def tag_bytes(when: datetime, serial: int = SERIAL, channels: int = 5, status: int = 0, saturation: int = 0,
              clock_status: int = 4) -> bytes:
    """Return a 32-byte record tag."""
    b = bytearray(32)
    b[0:8] = bytes([when.second, when.minute, when.hour, when.day, when.month, when.year % 100,
                    when.isoweekday() % 7, when.year // 100])
    b[8:10] = serial.to_bytes(2, "little")
    b[10:12] = (150).to_bytes(2, "little")
    b[12], b[13], b[14], b[15], b[17] = channels, 32, status, saturation, 3
    b[18:20] = (150).to_bytes(2, "little")
    b[21] = clock_status
    return bytes(b)


def record_counts(k: int, channels: int = 5) -> np.ndarray:
    """Return record k's counts, (150 scans, channels) int, a different ramp per channel and record."""
    scan = np.arange(150)[:, None]
    chan = np.arange(channels)[None, :]
    return ((scan * 977 + chan * 104729 + k * 7919) % (2 ** 24) - 2 ** 23).astype(np.int64)


def int24(counts: np.ndarray) -> bytes:
    """Return counts as 3-byte little-endian two's complement, scan-major."""
    v = counts.reshape(-1).astype(np.int64) & 0xFFFFFF
    return np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=1).astype(np.uint8).tobytes()


def write_ts4(path: Path, seconds: list[int], serial: int = SERIAL, channels: int = 5, flags: dict | None = None,
              cut: int = 0, values: list | None = None) -> dict:
    """Write a .TS4 of records tagged START + each of `seconds`; returns {record: counts}.

    `flags` maps a record to tag keyword values (status, saturation,
    clock_status); `cut` drops that many bytes from the end of the file;
    `values`, when given, holds each record's counts (150 scans, channels)
    in place of `record_counts`.
    """
    flags = flags or {}
    out, data = {}, bytearray()
    for k, s in enumerate(seconds):
        counts = record_counts(k, channels) if values is None else values[k]
        out[k] = counts
        data += tag_bytes(START + timedelta(seconds=s), serial, channels, **flags.get(k, {})) + int24(counts)
    path.write_bytes(bytes(data[:len(data) - cut] if cut else data))
    return out


def table_block(key: str, kind: int, value) -> bytes:
    """Return one 25-byte table block."""
    if kind == 0:
        raw = struct.pack("<i", int(value))
    elif kind == 1:
        raw = struct.pack("<d", float(value))
    elif kind == 2:
        raw = str(value).encode("latin-1")
    else:
        raw = bytes([value.second, value.minute, value.hour, value.day, value.month, value.year % 100,
                     value.isoweekday() % 7, value.year // 100])
    return key.encode("latin-1").ljust(5, b"\x00") + b"\x02\x00\x00\x00\x00\x00" + bytes([kind]) + raw.ljust(13, b"\x00")


def write_tbl(path: Path, first: datetime, last: datetime, **override) -> None:
    """Write a .TBL with `TABLE`, `ORDER`, FTIM, LTIM and a trailing block; keyword values replace TABLE's."""
    values = {**TABLE, **{f"CH{'E' if c[0] == 'e' else 'H'}{c[1].upper()}": n for c, n in ORDER.items()},
              **override}
    blocks = []
    for key, value in values.items():
        kind = 2 if isinstance(value, str) else 1 if isinstance(value, float) else 0
        blocks.append(table_block(key, kind, value))
    blocks += [table_block("STIM", 5, datetime(2019, 1, 1)), table_block("FTIM", 5, first),
               table_block("LTIM", 5, last), b"\x00" * 11 + b"\x03" + b"\x00" * 13]
    path.write_bytes(b"".join(blocks))


def make_site(name: str, recordings: list[dict]) -> Path:
    """Write a site folder of recordings: dicts of stem, seconds and write_ts4/write_tbl keywords."""
    folder = DATA / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for r in recordings:
        stem, seconds = r["stem"], r["seconds"]
        r["counts"] = write_ts4(folder / f"{stem}.TS4", seconds, r.get("serial", SERIAL), r.get("channels", 5),
                                r.get("flags"), r.get("cut", 0), r.get("values"))
        if not r.get("no_table"):
            first = START + timedelta(seconds=seconds[0] + r.get("ftim_off", 0))
            write_tbl(folder / f"{stem}.TBL", first, START + timedelta(seconds=seconds[-1]),
                      SNUM=r.get("serial", SERIAL), **r.get("table", {}))
    return folder


def survey_for(name: str, entry: dict | None = None, rate: float = 150.0) -> Survey:
    """Return a scratch survey of the synthetic sites with one site's entry set."""
    config = {"name": "MTU5A_TEST", "instrument": "mtu5a", "sample_rate": rate, "data_root": str(DATA),
              "workspace": str(WORKSPACE), "sites": {name: dict(entry or {"dipole_length_ex": 100.0})}}
    return Survey(config, SCRATCH)


def read_back(path: Path, site: str) -> list[dict]:
    """Read an archive's runs with mth5 as plain dicts: id, start_ns, data, units, chains, filters, comment."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    out = []
    try:
        station = m.get_station(site, survey=m.surveys_group.groups_list[0])
        for run_id, _s, _e in _real_runs(station):
            group = station.get_run(run_id)
            data, units, chains, filters, start = {}, {}, {}, {}, None
            for comp in group.groups_list:
                ch = group.get_channel(comp)
                data[comp] = np.asarray(ch.hdf5_dataset[()])
                units[comp] = str(ch.metadata.units)
                chains[comp] = [f.name for f in ch.metadata.filters]
                filters.update({f.name: f for f in ch.channel_response.filters_list})
                start = int(pd.Timestamp(str(ch.metadata.time_period.start)).value)
            out.append({"id": run_id, "start_ns": start, "data": data, "units": units, "chains": chains,
                        "filters": filters, "comment": str(group.metadata.comments.value or "")})
    finally:
        m.close_mth5()
    return out


def ns(second: int) -> int:
    """Return START + second in ns since the epoch (UTC)."""
    return int(pd.Timestamp(START + timedelta(seconds=second), tz="UTC").value)


def expected(counts: dict, records: range) -> dict:
    """Return the stored channels of `records` as written: each channel's column of its table number."""
    joined = np.concatenate([counts[k] for k in records], axis=0)
    return {c: joined[:, n - 1].astype(np.int32) for c, n in ORDER.items()}


def check_table() -> list[str]:
    path = DATA / "table" / "4573C07A.TBL"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_tbl(path, START, START + timedelta(seconds=2))
    got = mtu5a.read_table(path)
    bad = []
    for key, want in (("SNUM", 4573), ("EGN", 4), ("FSCV", 2.45), ("HNOM", 100.0), ("SITE", "SYN 1"),
                      ("LATG", "3103.188,S"), ("CHEX", 2), ("FTIM", pd.Timestamp(START, tz="UTC")),
                      ("STIM", pd.Timestamp(datetime(2019, 1, 1), tz="UTC"))):
        if got.get(key) != want or type(got.get(key)) is not type(want):
            bad.append(f"M1 {key}: {got.get(key)!r}, expected {want!r}")
    if any(not k.isalnum() for k in got):
        bad.append(f"M1 a key that is not a table key was kept: {[k for k in got if not k.isalnum()]}")
    deg = mtu5a.table_degrees("3103.188,S")
    if abs(deg + (31 + 3.188 / 60)) > 1e-12:
        bad.append(f"M1 table_degrees 3103.188,S: {deg}")
    return bad


# units as mt_metadata stores them: "count" and "counts" are kept as "digital counts"
COUNTS = "digital counts"
CHAIN_E = [("mtu5a_dipole_ex_100m", 0.1, "milliVolt per kilometer", "milliVolt"),
           ("mtu5a_egn_4", 4.0, "milliVolt", "milliVolt"),
           ("mtu5a_counts_2.45v", 2 ** 23 / 2450.0, "milliVolt", COUNTS)]
CHAIN_H = [("mtu5a_hnom_100", 100.0, "nanoTesla", "milliVolt"), ("mtu5a_hatt_0.233", 0.233, "milliVolt", "milliVolt"),
           ("mtu5a_hgn_1", 1.0, "milliVolt", "milliVolt"), ("mtu5a_counts_2.45v", 2 ** 23 / 2450.0, "milliVolt", COUNTS)]


def check_three() -> list[str]:
    flags = {1: {"saturation": 1 << (ORDER["ex"] - 1) | 1 << (ORDER["hy"] - 1), "status": 3},
             2: {"saturation": 1 << (ORDER["hy"] - 1), "clock_status": 3}}
    rec = {"stem": "4573C07A", "seconds": [0, 1, 2], "flags": flags}
    make_site("SYN", [rec])
    path = ingest_site(survey_for("SYN"), "SYN", overwrite=True)
    runs = read_back(path, "SYN")
    bad = []
    if [r["id"] for r in runs] != ["sr150_0001"]:
        return [f"M2 runs {[r['id'] for r in runs]}, expected ['sr150_0001']"]
    run = runs[0]
    if run["start_ns"] != ns(0):
        bad.append(f"M2 start {run['start_ns']} ns, the first tag {ns(0)}")
    want = expected(rec["counts"], range(3))
    for comp, samples in want.items():
        got = run["data"].get(comp)
        if got is None or got.size != 450 or not np.array_equal(got, samples) or got.dtype != np.int32:
            bad.append(f"M2 {comp}: {None if got is None else (got.size, got.dtype)} differs from the written counts")
        if run["units"].get(comp) != COUNTS:
            bad.append(f"M2 {comp} units {run['units'].get(comp)!r}")
    for comp in ("ex", "ey", "hx", "hy", "hz"):
        model = CHAIN_E if comp in ("ex", "ey") else CHAIN_H
        if comp == "ey":
            model = [("mtu5a_dipole_ey_90m", 0.09, *CHAIN_E[0][2:])] + CHAIN_E[1:]
        names = run["chains"][comp]
        if names != [m[0] for m in model]:
            bad.append(f"M2 {comp} chain {names}")
            continue
        for name, gain, uin, uout in model:
            f = run["filters"][name]
            if abs(float(f.gain) - gain) > 1e-9 * abs(gain) or (str(f.units_in), str(f.units_out)) != (uin, uout):
                bad.append(f"M2 {comp} {name}: gain {f.gain} {f.units_in} -> {f.units_out}")
    for piece in ("mtu5a: ", "mtu5a_time: ", "mtu5a_units: ", "mtu5a_flags: "):
        if piece not in run["comment"]:
            bad.append(f"M2 no {piece!r} in the run comment")
    bad += check_flags(path, rec)
    return bad


def check_flags(path: Path, rec: dict) -> list[str]:
    table = mtu5a.flags_path(path)
    if not table.exists():
        return [f"M3 no {table.name} beside the archive"]
    rows = pd.read_csv(table, dtype=str, keep_default_na=False)
    got = sorted((r["field"], r["channel"], r["value"], r["start"], r["end"], r["records"]) for _i, r in rows.iterrows())
    iso = lambda s: pd.Timestamp(START + timedelta(seconds=s), tz="UTC").isoformat()  # noqa: E731
    want = sorted([("saturation", "ex", "1", iso(1), iso(2), "1"), ("saturation", "hy", "1", iso(1), iso(3), "2"),
                   ("status", "", "3", iso(1), iso(2), "1"), ("clock_status", "", "3", iso(2), iso(3), "1")])
    bad = [] if got == want else [f"M3 flag rows {got}, expected {want}"]
    return bad


def check_gap() -> list[str]:
    rec = {"stem": "4573C07A", "seconds": [0, 1, 3, 4]}
    make_site("GAP", [rec])
    runs = read_back(ingest_site(survey_for("GAP"), "GAP", overwrite=True), "GAP")
    bad = []
    if len(runs) != 2:
        return [f"M4 {len(runs)} run(s), expected 2"]
    if (runs[0]["start_ns"], runs[1]["start_ns"]) != (ns(0), ns(3)):
        bad.append(f"M4 starts {runs[0]['start_ns']}, {runs[1]['start_ns']}, expected {ns(0)}, {ns(3)}")
    for run, records in zip(runs, (range(0, 2), range(2, 4))):
        want = expected(rec["counts"], records)
        if any(not np.array_equal(run["data"][c], want[c]) for c in want):
            bad.append(f"M4 {run['id']}: samples differ from records {list(records)}")
    if "mtu5a_gap: 1 s" not in runs[1]["comment"]:
        bad.append(f"M4 no 'mtu5a_gap: 1 s' in {runs[1]['id']}'s comment")
    return bad


REFUSALS = {
    "no table": ([{"stem": "4573C07A", "seconds": [0, 1, 2], "no_table": True}], {}, 150.0, "4573C07A.TBL"),
    "two receivers": ([{"stem": "4573C07A", "seconds": [0, 1]}, {"stem": "4759C07A", "seconds": [5, 6],
                                                                 "serial": 4759}], {}, 150.0, "receivers [4573, 4759]"),
    "overlap": ([{"stem": "4573C07A", "seconds": [0, 1, 2]}, {"stem": "4573C07B", "seconds": [2, 3]}], {}, 150.0,
                "overlapping recordings"),
    "ftim": ([{"stem": "4573C07A", "seconds": [0, 1, 2], "ftim_off": 2}], {}, 150.0, "FTIM"),
    "four channels": ([{"stem": "4573C07A", "seconds": [0, 1, 2], "channels": 4}], {}, 150.0, "4 channels"),
    "short record": ([{"stem": "4573C07A", "seconds": [0, 1, 2], "cut": 100}], {}, 150.0, "last record is short"),
    "rate": ([{"stem": "4573C07A", "seconds": [0, 1, 2]}], {}, 1000.0, "150 Hz"),
    "serial": ([{"stem": "4573C07A", "seconds": [0, 1, 2]}], {"serial": 4759}, 150.0, "declares serial 4759"),
    "chains": ([{"stem": "4573C07A", "seconds": [0, 1]}, {"stem": "4573C07B", "seconds": [5, 6],
                                                          "table": {"EGN": 16}}], {}, 150.0, "differ in EGN"),
}


def check_refusals(which=None) -> list[str]:
    bad = []
    for label, (recordings, entry, rate, words) in REFUSALS.items():
        if which and label not in which:
            continue
        make_site("BAD", [dict(r) for r in recordings])
        archive = WORKSPACE / "mth5" / "BAD.h5"
        archive.unlink(missing_ok=True)
        try:
            ingest_site(survey_for("BAD", {"dipole_length_ex": 100.0, **entry}, rate), "BAD", overwrite=True)
            bad.append(f"M5 {label}: ingested")
        except (ValueError, FileNotFoundError) as exc:
            if words not in str(exc):
                bad.append(f"M5 {label}: the error does not name {words!r}: {exc}")
        if archive.exists():
            bad.append(f"M5 {label}: {archive.name} left in the workspace")
    return bad


# keys of another recorder, each refused in an mtu5a site's own entry, with a value of its kind
OTHER_KEYS = {"recording": "4573C07A", "calibration_dir": "calibrations", "coil_hx": "BMT1", "coil_hy": "BMT2",
              "coil_hz": "BMT3", "h_scale": 1.0, "sensor_type": "lemi120", "electric_gain": 1.0,
              "calibration_fn": "l120n.rsp", "h_from": "SYN", "electric_full_scale_uv": 25000.0,
              "magnetic_full_scale_nt": 70000.0, "clock_timezone": "UTC", "clock_drift_s": 0.0,
              "time_base": "headers"}
# the h_from entry also declares channels [ex, ey]: a declaration Survey.site accepts, refused by the key check alone
KEY_ENTRY = {"h_from": {"channels": ["ex", "ey"]}}


def check_keys() -> list[str]:
    """M11: each key of another recorder in an mtu5a site's entry is refused by name; swap_h is not."""
    bad = []
    archive = WORKSPACE / "mth5" / "KEYS.h5"
    for key, value in OTHER_KEYS.items():
        make_site("KEYS", [{"stem": "4573C07A", "seconds": [0, 1]}])
        archive.unlink(missing_ok=True)
        try:
            entry = {"dipole_length_ex": 100.0, key: value, **KEY_ENTRY.get(key, {})}
            ingest_site(survey_for("KEYS", entry), "KEYS", overwrite=True)
            bad.append(f"M11 {key}: ingested")
        except (ValueError, FileNotFoundError) as exc:
            if f"{key} in its survey.yaml entry" not in str(exc):
                bad.append(f"M11 {key}: the error does not name {key!r}: {exc}")
        if archive.exists():
            bad.append(f"M11 {key}: {archive.name} left in the workspace")
    make_site("KEYS", [{"stem": "4573C07A", "seconds": [0, 1]}])
    try:
        ingest_site(survey_for("KEYS", {"dipole_length_ex": 100.0, "swap_h": True}), "KEYS", overwrite=True)
    except (ValueError, FileNotFoundError) as exc:
        bad.append(f"M11 swap_h: refused with {exc}")
    archive.unlink(missing_ok=True)
    return bad


def check_detection() -> list[str]:
    rec = {"stem": "4573C07A", "seconds": [0, 1, 2]}
    folder = make_site("DET", [rec])
    bad = []
    if detect_instrument(folder) != "mtu5a" or detect_instrument(folder, prefer="phoenix") != "mtu5a":
        bad.append(f"M6 detect_instrument {detect_instrument(folder)!r}, expected 'mtu5a'")
    bursts = DATA / "BURSTS"
    if bursts.exists():
        shutil.rmtree(bursts)
    bursts.mkdir(parents=True)
    for suffix in (".TS2", ".TS3", ".TBL"):
        shutil.copy(folder / ("4573C07A.TS4" if suffix != ".TBL" else "4573C07A.TBL"), bursts / f"4573C07A{suffix}")
    if detect_instrument(bursts) is not None:
        bad.append(f"M6 detect_instrument of .TS2/.TS3/.TBL only {detect_instrument(bursts)!r}, expected None")
    ts4 = folder / "4573C07A.TS4"
    if file_start(ts4, "mtu5a") != ns(0) // 10 ** 9:
        bad.append(f"M6 file_start {file_start(ts4, 'mtu5a')}, expected {ns(0) // 10 ** 9}")
    s0, s1, n = span(folder, "mtu5a")
    if (int(s0.value), int(s1.value), n) != (ns(0), ns(3), 1):
        bad.append(f"M6 span {s0} {s1} {n}")
    for suffix in (".TS2", ".TS3"):
        shutil.copy(ts4, folder / f"4573C07A{suffix}")
    lines = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO")
    try:
        ingest_site(survey_for("DET"), "DET", overwrite=True)
    finally:
        logger.remove(sink)
    named = [ln for ln in lines if "4573C07A.TS2" in ln and "4573C07A.TS3" in ln]
    if len(named) != 1:
        bad.append(f"M6 {len(named)} log line(s) name the .TS2 and .TS3 files, expected 1")
    return bad


CLIP = 0.941  # the receiver's clip, of full scale (read from the Oak Dam files); the rail is 0.9 of it
RAIL_COUNTS = 0.9 * CLIP * 2 ** 23


def check_rail() -> list[str]:
    """M8: ex pinned at the clip on 2 % of its samples is saturated?, ey pinned at 0.80 of full scale is not."""
    records, scans = 50, 150
    n = records * scans
    t = np.arange(n)
    stored = {c: (100_000 + 50_000 * np.sin(2 * np.pi * t / (37 + 5 * i))).round().astype(np.int64)
              for i, c in enumerate(ORDER)}
    pinned = np.arange(0, n, 50)  # 150 samples of 7500, 2 %, spread over the recording
    stored["ex"][pinned] = round(CLIP * 2 ** 23)
    stored["ey"][pinned] = round(0.80 * 2 ** 23)
    columns = np.zeros((n, 5), dtype=np.int64)
    for comp, number in ORDER.items():
        columns[:, number - 1] = stored[comp]
    values = [columns[k * scans:(k + 1) * scans] for k in range(records)]
    make_site("RAIL", [{"stem": "4573C07A", "seconds": list(range(records)), "values": values}])
    runs = read_back(ingest_site(survey_for("RAIL"), "RAIL", overwrite=True), "RAIL")
    comment = runs[0]["comment"] if runs else ""
    levels = {r["channel"]: r for r in parse_level_note(comment)}
    bad = []
    ex, ey = levels.get("ex"), levels.get("ey")
    if ex is None or ex["verdict"] != "saturated?" or abs(ex["rail_fraction"] - pinned.size / n) > 0.001:
        bad.append(f"M8 ex (pinned at {CLIP} of full scale on {100 * pinned.size / n:g} %): {ex}")
    if ey is None or ey["verdict"] == "saturated?" or ey["rail_fraction"] > 0.001:
        bad.append(f"M8 ey (pinned at 0.80 of full scale on {100 * pinned.size / n:g} %): {ey}")
    rails = {c: r.get("rail_level") for c, r in levels.items()}
    if set(rails) != set(ORDER) or any(v is None or abs(v - RAIL_COUNTS) > 1e-5 * RAIL_COUNTS for v in rails.values()):
        bad.append(f"M8 rails recorded {rails}, expected {RAIL_COUNTS:.6g} counts on each channel")
    if "dc rail (counts, " not in comment or "dc rail (V" in comment:
        bad.append(f"M8 the rail is not recorded in counts: {comment[comment.find('dc level'):][:300]!r}")
    return bad


def check_swap_flags() -> list[str]:
    """M9: under swap_e, saturation on the table's ex column is named ey by the run comment and the flag table."""
    bit = 1 << (ORDER["ex"] - 1)
    rec = {"stem": "4573C07A", "seconds": [0, 1, 2], "flags": {k: {"saturation": bit} for k in range(3)}}
    make_site("SWAP", [rec])
    path = ingest_site(survey_for("SWAP", {"dipole_length_ex": 100.0, "swap_e": True}), "SWAP", overwrite=True)
    runs = read_back(path, "SWAP")
    bad = []
    comment = runs[0]["comment"] if runs else ""
    if "saturation records ex 0 ey 3 hx 0 hy 0 hz 0" not in comment:
        piece = comment[comment.find("mtu5a_flags"):][:120]
        bad.append(f"M9 comment {piece!r}, expected 'saturation records ex 0 ey 3 hx 0 hy 0 hz 0'")
    rows = pd.read_csv(mtu5a.flags_path(path), dtype=str, keep_default_na=False)
    got = [(r["channel"], r["records"]) for _i, r in rows.iterrows() if r["field"] == "saturation"]
    if got != [("ey", "3")]:
        bad.append(f"M9 flag table saturation rows {got}, expected [('ey', '3')]")
    return bad


def check_coil_chain() -> list[str]:
    """M10: recordings differing only in a coil serial plan as one site, each run naming its own coil; EGN refuses."""
    make_site("COIL", [{"stem": "4573C07A", "seconds": [0, 1]},
                       {"stem": "4573C07B", "seconds": [5, 6], "table": {"HXSN": "BMT9"}}])
    site = survey_for("COIL").site("COIL")
    bad = []
    try:
        runs = mtu5a.plan_runs(DATA / "COIL", site, 150.0)
    except ValueError as exc:
        return [f"M10 coil serials alone: refused with {exc}"]
    if [r.recording.stem for r in runs] != ["4573C07A", "4573C07B"]:
        bad.append(f"M10 runs of {[r.recording.stem for r in runs]}, expected one each of 4573C07A and 4573C07B")
    for run, coil in zip(runs, ("BMT1", "BMT9")):
        _chain, pieces = mtu5a.channel_chain(run.recording, "hx", site)
        if f"coil {coil} (HXSN)" not in pieces:
            bad.append(f"M10 {run.recording.stem} hx comment {pieces}, expected 'coil {coil} (HXSN)'")
    make_site("COIL", [{"stem": "4573C07A", "seconds": [0, 1]},
                       {"stem": "4573C07B", "seconds": [5, 6], "table": {"EGN": 16}}])
    try:
        mtu5a.plan_runs(DATA / "COIL", site, 150.0)
        bad.append("M10 two recordings whose EGN differ were planned")
    except ValueError as exc:
        if "differ in EGN" not in str(exc):
            bad.append(f"M10 EGN refused without 'differ in EGN': {exc}")
    return bad


def decode_file(path: Path) -> tuple[list[int], np.ndarray]:
    """Decode a whole .TS4 here: the tag seconds and the counts (records x 150, 5), with numpy alone."""
    raw = np.fromfile(path, dtype=np.uint8)
    rec = 32 + 150 * 5 * 3
    rows = raw.reshape(-1, rec)
    tags = rows[:, :32]
    secs = [int(pd.Timestamp(year=int(t[7]) * 100 + int(t[5]), month=int(t[4]), day=int(t[3]), hour=int(t[2]),
                             minute=int(t[1]), second=int(t[0]), tz="UTC").timestamp()) for t in tags[[0, -1]]]
    b = rows[:, 32:].reshape(-1, 3).astype(np.int32)
    v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    v[v >= 1 << 23] -= 1 << 24
    return secs, v.reshape(-1, 5)


def check_real() -> list[str] | None:
    folder = OAK_DAM / REAL[0]
    if not folder.is_dir():
        return None
    site = DATA / "REAL"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    for suffix in (".TBL", ".TS4"):
        shutil.copy2(folder / f"{REAL[1]}{suffix}", site / f"{REAL[1]}{suffix}")
    bad = []
    path = ingest_site(survey_for("REAL", {}), "REAL", overwrite=True)
    runs = read_back(path, "REAL")
    (first, last), counts = decode_file(site / f"{REAL[1]}.TS4")
    raw = (site / f"{REAL[1]}.TBL").read_bytes()  # the channel numbers read here, not by read_table
    keys = {"CHEX": "ex", "CHEY": "ey", "CHHX": "hx", "CHHY": "hy", "CHHZ": "hz"}
    order = {keys[raw[i:i + 5].split(b"\x00")[0].decode("latin-1")]: struct.unpack("<i", raw[i + 12:i + 16])[0]
             for i in range(0, len(raw) - 24, 25) if raw[i:i + 5].split(b"\x00")[0].decode("latin-1") in keys}
    if len(runs) != 1 or runs[0]["start_ns"] != first * 10 ** 9:
        bad.append(f"M7 {len(runs)} run(s), start {runs[0]['start_ns'] if runs else None}, first tag {first * 10 ** 9}")
    elif counts.shape[0] != (last - first + 1) * 150:
        bad.append(f"M7 {counts.shape[0]} samples for tags {first} .. {last}: not one record a second")
    else:
        for comp, number in order.items():
            if not np.array_equal(runs[0]["data"][comp], counts[:, number - 1]):
                bad.append(f"M7 {comp}: the archive differs from the decode")
    try:
        mtu5a.plan_runs(folder, survey_for("REAL", {}).site("REAL"), 150.0)
        bad.append("M7 the raw folder 191207 (two receivers) was planned")
    except ValueError as exc:
        if "receivers [4573, 4759]" not in str(exc):
            bad.append(f"M7 191207 refused with {exc}")
    return bad


def mutated(target, name: str, value, check, *args) -> list[str]:
    """Run `check` with `target.name` replaced by `value`; return its failures."""
    kept = getattr(target, name)
    setattr(target, name, value)
    try:
        return check(*args)
    except Exception as exc:  # a mutation may also break the run: that trips too
        return [f"raised {type(exc).__name__}: {exc}"]
    finally:
        setattr(target, name, kept)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    failures = []
    for label, check in (("M1 table", check_table), ("M2/M3 three records and flags", check_three),
                         ("M4 gap", check_gap), ("M5 refusals", check_refusals), ("M6 detection", check_detection),
                         ("M8 rail at the clip", check_rail), ("M9 swap_e flag names", check_swap_flags),
                         ("M10 coil serials outside the chain", check_coil_chain),
                         ("M11 keys of other recorders", check_keys)):
        bad = check()
        failures += bad
        print(f"  {label}: {'ok' if not bad else bad}")
    late = mtu5a._tag_seconds
    trip = mutated(mtu5a, "_tag_seconds", lambda tags, name: late(tags, name) + 1, check_three)
    # the start check, or read_run's self-check against mt-io's start, which comes first
    assert any(t.startswith("M2 start") or "differ in start" in t for t in trip), trip
    print(f"  M2 mutation (tags read 1 s late) tripped: {trip[0][:120]}")
    trip = mutated(mtu5a, "FTIM_TOLERANCE_S", 10.0, check_refusals, ["ftim"])
    assert any("ftim: ingested" in t for t in trip), trip
    print(f"  M5 mutation (FTIM tolerance 10 s) tripped: {trip[0][:120]}")
    trip = mutated(mtu5a, "rails", lambda: {}, check_rail)
    assert any(t.startswith("M8 ey") for t in trip), trip
    print(f"  M8 mutation (no absolute rail: the relative one) tripped: {trip[0][:120]}")
    unswapped, plain = mtu5a._flag_counts, SimpleNamespace(swap_e=False, swap_h=False)
    trip = mutated(mtu5a, "_flag_counts", lambda unit, site: unswapped(unit, plain), check_swap_flags)
    assert any(t.startswith("M9 comment") for t in trip), trip
    print(f"  M9 mutation (comment counts by the recorded names) tripped: {trip[0][:120]}")
    trip = mutated(mtu5a, "CHAIN_KEYS", (*mtu5a.CHAIN_KEYS, *mtu5a.COIL_KEYS.values()), check_coil_chain)
    assert any(t.startswith("M10 coil serials alone") and "differ in HXSN" in t for t in trip), trip
    print(f"  M10 mutation (coil serials back in CHAIN_KEYS) tripped: {trip[0][:160]}")
    let_through = tuple(k for k in ingest._PHOENIX_ONLY_KEYS if k != "calibration_dir")
    trip = mutated(ingest, "_PHOENIX_ONLY_KEYS", let_through, check_keys)
    assert any(t.startswith("M11 calibration_dir: ingested") for t in trip), trip
    print(f"  M11 mutation (calibration_dir let through) tripped: {trip[0][:120]}")
    real = check_real()
    if real is None:
        print(f"  M7 real recording: SKIPPED ({OAK_DAM} not present)")
    else:
        failures += real
        print(f"  M7 real recording {REAL[0]}/{REAL[1]}: {'ok' if not real else real}")
    if failures:
        print("\nFAIL  mtu5a_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    shutil.rmtree(DATA)
    shutil.rmtree(WORKSPACE, ignore_errors=True)
    print("\nPASS  mtu5a_unit")


if __name__ == "__main__":
    main()
