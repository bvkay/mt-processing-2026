# -*- coding: utf-8 -*-
"""
Unit test for the check of a Phoenix archive's H polarity stage (mt_workbench.phoenix.archive_h_polarity)

A Phoenix archive built by an older ingest holds its H without the stage
`phoenix_h_polarity` (upstream issue 81), so a product mixing it with a
re-ingested Phoenix archive or a LEMI-423 site carries a silent -1.
`run_h_polarity` tells from a run's filter lists whether its Phoenix
magnetic channels (hx, hy, hz whose chain holds `phoenix_mv_to_v`) carry
the stage, `archive_h_polarity` reads every run of a station with h5py,
and `warn_without_h_polarity` logs one warning naming the archive;
scripts/process_rr.py, scripts/process_intersite.py and
`intersite.stack_channels` call it for each site whose archive they open.

Synthetic archives are written with h5py into scratch: a Phoenix station
with the stage (mth5 0.2.0's ``filters`` attribute), one without, one with
the stage on hx only, the same without the stage in mth5 0.1.0's
``filter.name`` form, a LEMI-423 station and an electric-only station.
When present, read only: the Kalkaroo workspace's scratch G5.h5
(re-ingested with the stage), the workspace KD-RR_210428.h5 (built at
4beb3cd, before it), the P-test burst archive PT_10133H.h5 (24 kHz
bursts, one run each) and the LEMI-423 KD-RRa_210428.h5. An archive held
open elsewhere (Windows refuses the read) is reported and not checked.

Usage:
    python tests/phoenix_h_polarity_check_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - P1: `run_h_polarity` does not give True for hx and hy with the stage,
    False when hx or hy lacks it, None for a run of electric channels only
    and None for a LEMI-423 chain (no `phoenix_mv_to_v`);
  - P2: on the synthetic archives `archive_h_polarity` does not give True
    (stage; the 0.1.0 form with it; `N_BURSTS` runs with it, read in under
    5 s), False (no stage; stage on hx only; the 0.1.0 form without it),
    None (LEMI-423, electric only, a missing station, a missing archive);
  - P3: `warn_without_h_polarity` does not log exactly one warning naming
    the archive and "phoenix_h_polarity" for an archive without the stage,
    or logs one for an archive with it or a LEMI-423 archive;
  - P4 (real archives, when present): the scratch G5.h5 does not read True
    with no warning, KD-RR_210428.h5 and PT_10133H.h5 do not read
    False with one warning each, KD-RRa_210428.h5 does not read None, or
    the read of the burst archive takes 5 s or more.

The mutation, which must trip P2 and P4: `phoenix.H_POLARITY` renamed, so
that no archive holds the stage the check looks for.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import mt_workbench.phoenix as phoenix  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("phoenix_h_polarity_check_unit")
WORKSPACE = Path("D:/MT_DATA/MT_Kalkaroo_Workspace/mth5")
REAL = {"scratch G5": (WORKSPACE / "scratch_sign_fix" / "mth5" / "G5.h5", "G5", True),
        "KD-RR_210428": (WORKSPACE / "KD-RR_210428.h5", "KD-RR_210428", False),
        "PT_10133H": (WORKSPACE / "PT_10133H.h5", "PT_10133H", False),
        "KD-RRa_210428": (WORKSPACE / "KD-RRa_210428.h5", "KD-RRa_210428", None)}
N_BURSTS = 1629  # the runs of a large burst archive (upstream issue 74)
E_CHAIN = ["dipole_100m", "phoenix_mv_to_v", "mtu-8a_rmt05_10133_e1_10000hz_lowpass"]
LEMI_H = ["lemi_120_34_response", "lemi423_linear_hx", "lemi423_b_scale"]


def h_chain(stage: bool, coil: str = "53508") -> list[str]:
    """Return a Phoenix magnetic chain's filter names, with or without the polarity stage."""
    names = [f"phoenix_coil_{coil}", "phoenix_mv_to_v", "mtu-8a_rmt05_10133_h1_10000hz_lowpass"]
    if stage:
        names.insert(1, "phoenix_h_polarity")
    return names


def filters_attr(names: list[str]) -> str:
    """Return mth5 0.2.0's ``filters`` attribute for a chain of filter names."""
    return json.dumps([{"applied_filter": {"applied": True, "name": n, "stage": k + 1}} for k, n in enumerate(names)])


def write_archive(path: Path, station: str, runs: dict, old_form: bool = False) -> Path:
    """Write a minimal archive: one station, runs of {channel: filter names}, 10 samples each."""
    with h5py.File(path, "w") as f:
        group = f.create_group(f"Experiment/Surveys/SYN/Stations/{station}")
        group.create_group("Transfer_Functions")
        for run, channels in runs.items():
            rg = group.create_group(run)
            for comp, names in channels.items():
                d = rg.create_dataset(comp, data=np.zeros(10, dtype=np.float32))
                if old_form:
                    d.attrs["filter.name"] = np.array(names, dtype=h5py.string_dtype())
                else:
                    d.attrs["filters"] = filters_attr(names)
    return path


def fixtures() -> dict:
    """Write the synthetic archives; {label: (path, station, expected)}."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with_stage = {"ex": E_CHAIN, "hx": h_chain(True), "hy": h_chain(True, "53509")}
    without = {"ex": E_CHAIN, "hx": h_chain(False), "hy": h_chain(False, "53509")}
    half = {"ex": E_CHAIN, "hx": h_chain(True), "hy": h_chain(False, "53509")}
    out = {
        "stage": (write_archive(SCRATCH / "P01.h5", "P01", {"sr150_0001": with_stage, "sr150_0002": with_stage}),
                  "P01", True),
        "no stage": (write_archive(SCRATCH / "P02.h5", "P02", {"sr150_0001": without}), "P02", False),
        "stage on hx only": (write_archive(SCRATCH / "P03.h5", "P03", {"sr150_0001": with_stage,
                                                                         "sr150_0002": half}), "P03", False),
        "0.1.0 form, no stage": (write_archive(SCRATCH / "P04.h5", "P04", {"sr150_0001": without}, old_form=True),
                                 "P04", False),
        "0.1.0 form, stage": (write_archive(SCRATCH / "P05.h5", "P05", {"sr150_0001": with_stage}, old_form=True),
                              "P05", True),
        "LEMI-423": (write_archive(SCRATCH / "L01.h5", "L01", {"sr1000_0001": {"hx": LEMI_H, "hy": LEMI_H}}),
                     "L01", None),
        "electric only": (write_archive(SCRATCH / "E01.h5", "E01", {"sr150_0001": {"ex": E_CHAIN}}), "E01", None),
        "bursts, stage": (write_archive(SCRATCH / "B01.h5", "B01",
                                        {f"sr24000_{k:05d}": with_stage for k in range(1, N_BURSTS + 1)}),
                          "B01", True),
    }
    out["missing station"] = (out["stage"][0], "P99", None)
    out["missing archive"] = (SCRATCH / "absent.h5", "P01", None)
    return out


def captured(func, *args):
    """Run func and return (its value, the WARNING lines it logged)."""
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="WARNING", format="{message}")
    try:
        value = func(*args)
    finally:
        logger.remove(sink)
    return value, lines


def check_runs() -> list[str]:
    """P1: `run_h_polarity` on filter lists."""
    bad = []
    cases = (("hx hy with the stage", {"ex": E_CHAIN, "hx": h_chain(True), "hy": h_chain(True)}, True),
             ("hy without", {"hx": h_chain(True), "hy": h_chain(False)}, False),
             ("hx without", {"hx": h_chain(False), "hy": h_chain(True)}, False),
             ("hz without", {"hx": h_chain(True), "hy": h_chain(True), "hz": h_chain(False)}, False),
             ("coil missing, with the stage", {"hx": h_chain(True)[1:], "hy": h_chain(True)[1:]}, True),
             ("electric only", {"ex": E_CHAIN, "ey": E_CHAIN}, None),
             ("LEMI-423", {"hx": LEMI_H, "hy": LEMI_H}, None))
    for label, filters, want in cases:
        got = phoenix.run_h_polarity(filters)
        if got is not want:
            bad.append(f"P1 {label}: {got}, expected {want}")
    return bad


def check_archives(cases: dict) -> list[str]:
    """P2 and P3: `archive_h_polarity` and its warning on the synthetic archives."""
    bad = []
    for label, (path, station, want) in cases.items():
        tic = time.perf_counter()
        got = phoenix.archive_h_polarity(path, station)
        seconds = time.perf_counter() - tic
        if got is not want:
            bad.append(f"P2 {label}: {got}, expected {want}")
        if seconds >= 5.0:
            bad.append(f"P2 {label}: read in {seconds:.1f} s")
        if label.startswith("bursts"):
            print(f"  P2 {label}: {N_BURSTS} runs read in {seconds:.2f} s")
        warned, lines = captured(phoenix.warn_without_h_polarity, path, station)
        if want is False:
            if not (warned and len(lines) == 1 and path.name in lines[0] and "phoenix_h_polarity" in lines[0]):
                bad.append(f"P3 {label}: {warned}, warnings {lines}, expected one naming {path.name}")
        elif warned or lines:
            bad.append(f"P3 {label}: warned {lines}")
    return bad


def check_real() -> tuple[list[str], list[str]]:
    """P4: the real archives, read only; (failures, info lines)."""
    bad, info = [], []
    for label, (path, station, want) in REAL.items():
        if not path.is_file():
            info.append(f"P4 {label}: {path} absent, not checked")
            continue
        try:
            tic = time.perf_counter()
            held = phoenix.archive_h_polarity(path, station)
            seconds = time.perf_counter() - tic
        except OSError as exc:
            info.append(f"P4 {label}: {path.name} not readable ({type(exc).__name__}: held open elsewhere?), "
                        f"not checked")
            continue
        _warned, lines = captured(phoenix.warn_without_h_polarity, path, station)
        info.append(f"P4 {label}: archive_h_polarity {held}, {len(lines)} warning(s), {seconds:.2f} s")
        if held is not want:
            bad.append(f"P4 {label}: {held}, expected {want}")
        if (want is False) != (len(lines) == 1) or len(lines) > 1:
            bad.append(f"P4 {label}: warnings {lines}")
        if seconds >= 5.0:
            bad.append(f"P4 {label}: {seconds:.1f} s")
    return bad, info


def main() -> None:
    """Run P1-P4 and the mutation."""
    cases = fixtures()
    failures = check_runs()
    print(f"  P1 run_h_polarity: {'ok' if not failures else failures}")
    bad = check_archives(cases)
    failures += bad
    print(f"  P2-P3 {len(cases)} synthetic archives: {'ok' if not bad else bad}")
    bad, info = check_real()
    failures += bad
    for line in info:
        print(f"  {line}")
    print(f"  P4 real archives: {'ok' if not bad else bad}")
    if not failures:
        kept = phoenix.H_POLARITY
        phoenix.H_POLARITY = "phoenix_h_polarity_renamed"
        try:
            trip = check_archives(cases) + check_real()[0]
        finally:
            phoenix.H_POLARITY = kept
        assert any(t.startswith("P2 stage:") for t in trip), trip
        real_tripped = any(t.startswith("P4 scratch G5:") for t in trip) or not REAL["scratch G5"][0].is_file()
        assert real_tripped, trip
        print(f"  mutation (H_POLARITY renamed) tripped: {trip[0][:120]}")
    if failures:
        print("\nFAIL  phoenix_h_polarity_check_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    print("\nPASS  phoenix_h_polarity_check_unit")


if __name__ == "__main__":
    main()
