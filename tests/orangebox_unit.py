# -*- coding: utf-8 -*-
"""
Unit test for the Orange Box reader of mt-io

Tests `mt_io.uoa.orange` directly on the format as decoded for Stuart Shelf
2009 trip 3. Synthetic files check the byte layout, channel mapping, gains,
sample rate and the refusal of files that do not join; one real station
(ST61) is compared with the legacy converter's output.

Usage:
    python tests/orangebox_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

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
  - the RunTS read_orange returns does not keep the header's rate: its sample rate is not
    exactly 1e7/(512*1953) = 10.00064 Hz, or its time index does not step by exactly
    99,993,600 ns (1e9 * 512 * 1953 / 1e7) between every pair of samples. Stock
    mt_timeseries rounds any rate >= 1 Hz to an integer and steps by 0.1 s
    (docs/upstream_issues.md 10); the mt-timeseries fork keeps the rate;
  - `read_orange` on two synthetic files two hours apart returns a run instead of raising
    ValueError naming the missing time and both files (docs/upstream_issues.md 11: stock
    mt-io joins them into one gap-free run dated from the first file; the mt-io fork
    refuses files that do not join), or does not read the two files back to back
    (the second starting at the first's end stamp) as one run of both files' samples;
  - one real hour (Stuart Shelf ST61, HFM1-000.BIN, read only from E:) averaged to 1 s does
    not match the legacy converter's mtdata.raw to 0.015 nT on hx, hy, hz (float32 and
    two-decimal rounding), or its ex and ey are not exactly 1/4 of mt-io's (the legacy
    25,000 uV electric full scale against mt-io's 100,000 uV: issue #13), to 1e-4;
  - the 69 real ST61 files are not back to back by their own stamps (each trailer stamp
    equals the next header's start, within the 1 s the stamps resolve).
The last two read E: (the Stuart Shelf raw data); without it they are SKIPPED, with the
reason printed, and the synthetic checks alone decide the result.
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
    """Write one Orange Box file.

    Args:
        path (Path): File to write.
        counts (np.ndarray): n x 8 counts, unsigned as recorded.
        start (pd.Timestamp): Start stamp of the header.
        fp (int): Filter point; the sample rate is 1e7 / (512 fp).

    Returns:
        pd.Timestamp: The end stamp written in the trailer.
    """
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
    """Draw n x 8 random unsigned counts in the range of each channel's width."""
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
    rate = 1e7 / (512 * FP)
    step = np.unique(np.diff(run.dataset.time.values.astype("datetime64[ns]").astype(np.int64)))
    assert run.sample_rate == rate and f"{run.sample_rate:.5f}" == "10.00064", (
        f"RunTS rate {run.sample_rate!r}, header rate {rate!r} (stock mt_timeseries rounds it to 10.0: issue 10)")
    assert step.tolist() == [99_993_600], f"time index steps {step.tolist()} ns, want [99993600] (issue 10)"
    print(f"PASS synthetic: {n} records of 21 bytes read back exactly; mapping and gains as documented; "
          f"header rate {head['sample_rate']:.9f} Hz = RunTS rate {run.sample_rate:.9f} Hz, "
          f"index step {step[0]:,} ns")


def test_gap_is_refused(tmp: Path) -> None:
    n = 1200
    a, b = tmp / "HFM9-000.BIN", tmp / "HFM9-001.BIN"
    t0 = pd.Timestamp("2009-06-16 02:00:00")
    end_a = write_orange_bin(a, synthetic_counts(n), t0)
    write_orange_bin(b, synthetic_counts(n), t0 + pd.Timedelta(hours=2))
    try:
        run = read_orange([str(a), str(b)], station_id="SYN")
    except ValueError as error:
        text = str(error)
    else:
        last = pd.Timestamp(run.dataset.time.values[-1])
        raise AssertionError(f"two files 2 h apart were joined into one run of {run.dataset.time.size} samples "
                             f"ending {last:%H:%M:%S} (issue 11: stock mt-io joins without checking)")
    missing = round((t0 + pd.Timedelta(hours=2) - end_a).total_seconds())
    assert f"{missing} s missing" in text and a.name in text and b.name in text, text
    # the same two files back to back (the second starting at the first's end stamp) still join
    c = tmp / "HFM9-002.BIN"
    write_orange_bin(c, synthetic_counts(n), end_a)
    run = read_orange([str(a), str(c)], station_id="SYN")
    assert run.dataset.time.size == 2 * n, run.dataset.time.size
    print(f"PASS gap refused: two files 2 h apart raise ValueError ({text[:110]}...); "
          f"back to back they read as one run of {2 * n} samples")


def test_real_hour_vs_legacy() -> None:
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
        test_gap_is_refused(Path(d))
    if ST61.is_dir():
        test_real_hour_vs_legacy()
        test_real_files_back_to_back()
        print("orangebox_unit: all passed")
    else:
        print(f"SKIPPED real-data checks (real hour vs legacy, ST61 files back to back): {ST61} is not "
              f"available (E: not mounted)")
        print("orangebox_unit: synthetic checks passed; real-data checks SKIPPED")
