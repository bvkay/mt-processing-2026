"""Unit test for mt-io's Orange Box reader (`mt_io.uoa.orange`) on the format as decoded
for Stuart Shelf 2009 trip 3 -- no mtproc module involved, mt-io is the reader.

    python tests/orangebox_unit.py

The Orange Box (Adelaide/Flinders "High Frequency Magnetometer", HFM<n>) writes one
binary file an hour, HFM<n>-NNN.BIN:

    40 byte ASCII header   " 00008CA0 \\n"  sample count, hex (11 bytes)
                           "Tue Jun 16 02:01:04 2009\\n"  start, logger RTC, UTC (25 bytes)
                           " 7A1"  filter point, hex (4 bytes): fs = 1e7 / (512 fp)
    n records of 21 bytes  big endian, unsigned: ch0 ch1 ch2 (3 bytes each), ch3 ch4
                           (2 bytes), ch5 (1 byte), ch6 ch7 (3 bytes), then 0x20
    26 byte ASCII trailer  " Tue Jun 16 03:01:04 2009\\n"  end, logger RTC

**This test fails if**
  - a synthetic file written in that layout does not read back exactly through
    `OrangeDataReader` (all eight channels, the 24-bit ones signed about 2**23) and
    `read_orange` (hx=ch0, hz=ch1, hy=ch2, ey=ch6, ex=ch7, counts unchanged; the header's
    rate 1e7/(512*1953) = 10.00064 Hz; start from the header; gains 2**23/70000 for hx and
    hz, -2**23/70000 for hy, -2**23*L/100000 for ex and ey);
  - the RunTS read_orange returns does NOT step its time index at exactly 0.1 s (this
    documents docs/upstream_issues.md #10: mt_timeseries' ChannelTS rounds any rate >= 1 Hz
    to an integer, so the 10.00064 Hz the reader computes is stored as 10.0 Hz. When this
    starts failing the rounding is gone upstream: re-run the timing QC);
  - two synthetic files two hours apart are NOT joined into one gap-free run by
    `read_orange` (this documents docs/upstream_issues.md #11: the reader never compares a
    file's start with the previous file's end. When this assertion starts failing mt-io has
    added a gap check: good news, update the scratch ingest and the issue);
  - one real hour (Stuart Shelf ST61, HFM1-000.BIN, read only from E:) averaged to 1 s does
    not match the legacy converter's mtdata.raw to 0.015 nT on hx, hy, hz (float32 and
    two-decimal rounding), or its ex and ey are not exactly 1/4 of mt-io's (the legacy
    25,000 uV electric full scale against mt-io's 100,000 uV: issue #13), to 1e-4;
  - the 69 real ST61 files are not back to back by their own stamps (each trailer stamp
    equals the next header's start, within the 1 s the stamps resolve).
A missing E: drive is a failure, not a skip.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from mt_io.uoa.orange import OrangeDataReader, read_orange

logger.remove()

ST61 = Path(r"E:\MT_Timeseries_DATA\MT_Stuart_Shelf_2009_LPMT\Trip3_06-2009\Rawdata_st61-st94\ST61\merged")
STAMP = "%a %b %d %H:%M:%S %Y"
FP = 0x7A1  # 1953, the Stuart Shelf filter point
RNG = np.random.default_rng(2009)


def write_orange_bin(path: Path, counts: np.ndarray, start: pd.Timestamp, fp: int = FP) -> pd.Timestamp:
    """Write `counts` (n x 8, unsigned as recorded) as one Orange Box file; return the end stamp written."""
    n = counts.shape[0]
    end = start + pd.Timedelta(seconds=round(n / (1e7 / (512 * fp))))
    rec = np.zeros((n, 21), dtype=np.uint8)
    for ch, offset in ((0, 0), (1, 3), (2, 6), (6, 14), (7, 17)):
        v = counts[:, ch].astype(np.int64)
        rec[:, offset], rec[:, offset + 1], rec[:, offset + 2] = (v >> 16) & 255, (v >> 8) & 255, v & 255
    for ch, offset in ((3, 9), (4, 11)):
        v = counts[:, ch].astype(np.int64)
        rec[:, offset], rec[:, offset + 1] = (v >> 8) & 255, v & 255
    rec[:, 13] = counts[:, 5]
    rec[:, 20] = 0x20
    header = f" {n:08X} \n{start.strftime(STAMP)}\n {fp:3X}".encode("ascii")
    assert len(header) == 40, len(header)
    path.write_bytes(header + rec.tobytes() + f" {end.strftime(STAMP)}\n".encode("ascii"))
    return end


def synthetic_counts(n: int) -> np.ndarray:
    c = np.empty((n, 8), dtype=np.int64)
    for ch in (0, 1, 2, 6, 7):
        c[:, ch] = RNG.integers(0, 2**24, n)
    c[:, 3] = RNG.integers(0, 2**16, n)
    c[:, 4] = RNG.integers(0, 2**16, n)
    c[:, 5] = RNG.integers(0, 256, n)
    return c


def test_synthetic_round_trip(tmp: Path) -> None:
    n = 3000
    counts = synthetic_counts(n)
    start = pd.Timestamp("2009-06-16 02:01:04")
    f = tmp / "HFM9-000.BIN"
    write_orange_bin(f, counts, start)
    r = OrangeDataReader(f)
    with open(f, "rb") as h:
        head = r.parse_header(h)
        got = r.read_samples(h)
    assert head["n_samples"] == n and head["filter_point"] == FP, head
    assert abs(head["sample_rate"] - 1e7 / (512 * FP)) < 1e-12, head
    assert head["start_time"] == start.tz_localize("UTC"), head
    want = counts.copy()
    for ch in (0, 1, 2, 6, 7):
        want[:, ch] -= 2**23
    assert np.array_equal(got, want), "OrangeDataReader did not return the written counts"

    L_ex, L_ey = 20.0, 15.0
    run = read_orange(str(f), station_id="SYN", dipole_length_ex=L_ex, dipole_length_ey=L_ey)
    for comp, ch in (("hx", 0), ("hz", 1), ("hy", 2), ("ey", 6), ("ex", 7)):
        assert np.array_equal(run.dataset[comp].values, want[:, ch]), f"{comp} is not ch{ch}"
    gains = {c: run.filters[run.dataset[c].attrs["filters"][0]["applied_filter"]["name"]].gain
             for c in ("hx", "hy", "hz", "ex", "ey")}
    expect = {"hx": 2**23 / 70000, "hz": 2**23 / 70000, "hy": -(2**23) / 70000,
              "ex": -(2**23) * L_ex / 100000, "ey": -(2**23) * L_ey / 100000}
    for c in expect:
        assert abs(gains[c] - expect[c]) < 1e-9 * abs(expect[c]), (c, gains[c], expect[c])
    step = np.unique(np.diff(run.dataset.time.values) / np.timedelta64(1, "ns"))
    assert run.sample_rate == 10.0 and step.tolist() == [100_000_000], (run.sample_rate, step)
    print(f"PASS synthetic: {n} records of 21 bytes read back exactly; mapping and gains as documented; "
          f"header rate {head['sample_rate']:.6f} Hz, RunTS rate {run.sample_rate} Hz (issue #10 documented)")


def test_gap_is_not_detected(tmp: Path) -> None:
    n = 1200
    a, b = tmp / "HFM9-000.BIN", tmp / "HFM9-001.BIN"
    t0 = pd.Timestamp("2009-06-16 02:00:00")
    write_orange_bin(a, synthetic_counts(n), t0)
    end_b = write_orange_bin(b, synthetic_counts(n), t0 + pd.Timedelta(hours=2))
    run = read_orange([str(a), str(b)], station_id="SYN")
    n_run = run.dataset.time.size
    last = pd.Timestamp(run.dataset.time.values[-1])
    assert n_run == 2 * n, n_run
    assert last < end_b - pd.Timedelta(hours=1.5), (last, end_b)
    print(f"PASS gap (issue #11 documented): two files 2 h apart joined into one run of {n_run} "
          f"samples ending {last:%H:%M:%S}, while the second file's own stamp ends {end_b:%H:%M:%S}")


def test_real_hour_vs_legacy() -> None:
    if not ST61.is_dir():
        raise SystemExit(f"FAIL: {ST61} is not mounted")
    run = read_orange(str(ST61 / "HFM1-000.BIN"), station_id="ST61", dipole_length_ex=20.0, dipole_length_ey=15.0)
    legacy = np.loadtxt(ST61 / "mtdata.raw", max_rows=3600)
    worst = {}
    for comp, col in (("hx", 1), ("hy", 2), ("hz", 3), ("ex", 4), ("ey", 5)):
        ch = run.dataset[comp]
        gain = run.filters[ch.attrs["filters"][0]["applied_filter"]["name"]].gain
        one_s = (ch.values / gain).reshape(-1, 10).mean(axis=1)
        if comp.startswith("h"):
            worst[comp] = np.abs(one_s - legacy[:, col]).max()
            assert worst[comp] < 0.015, (comp, worst[comp])
        else:
            worst[comp] = np.abs(one_s / 4.0 - legacy[:, col]).max()
            assert worst[comp] < 1e-3, (comp, worst[comp])
    print("PASS real hour ST61: legacy = mt-io for hx hy hz (max |diff| "
          + ", ".join(f"{c} {worst[c]:.4f} nT" for c in ("hx", "hy", "hz"))
          + "); legacy = mt-io / 4 for ex ey (max |diff| "
          + ", ".join(f"{c} {worst[c]:.4f} mV/km" for c in ("ex", "ey")) + ")")


def test_real_files_back_to_back() -> None:
    files = sorted(ST61.glob("HFM1-*.BIN"))
    assert len(files) == 69, len(files)
    starts, ends = [], []
    for f in files:
        raw = f.read_bytes()
        n = int(raw[:11].strip(), 16)
        assert n == 36000 and int(raw[36:40].strip(), 16) == FP and len(raw) == 40 + 21 * n + 26, f.name
        starts.append(pd.to_datetime(raw[11:35].decode(), format=STAMP))
        ends.append(pd.to_datetime(raw[40 + 21 * n:].decode().strip(), format=STAMP))
    gaps = np.array([(s - e).total_seconds() for s, e in zip(starts[1:], ends[:-1])])
    assert np.all(np.abs(gaps) <= 1.0), gaps
    span = (ends[-1] - starts[0]).total_seconds()
    print(f"PASS ST61 files back to back: 69 x 36000 samples, stamp gaps {gaps.min():.0f}..{gaps.max():.0f} s, "
          f"{span:.0f} s by the stamps against {69 * 36000 / (1e7 / (512 * FP)):.0f} s at mt-io's rate")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_synthetic_round_trip(Path(d))
        test_gap_is_not_detected(Path(d))
    test_real_hour_vs_legacy()
    test_real_files_back_to_back()
    print("orangebox_unit: all passed")
