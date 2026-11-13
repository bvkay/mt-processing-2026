# -*- coding: utf-8 -*-
"""
Unit test of `h_from` on Orange Box sites, on synthetic files

Two synthetic Orange Box sites are written in the documented layout (the
writer of tests/orangebox_unit.py, as tests/orangebox_ingest_unit.py uses
it): a local S1 (two back-to-back files from 2 May 2006 14:56 Perth, no
drift) and a lender L1 (two files starting 600 s later, 3 s of drift, so a
different true rate and a different place on the logger clock). Each
channel carries its own signal: sines of distinct periods on the lender's
hx and hy, other sines and noise on the local's five channels. The survey
declares `h_from: L1` on S1 and nothing else (the local keeps the default
channels ex ey hx hy hz, as Kalgoorlie's Kal05 and Kal015 do). S1 is
ingested twice, with and without the key, and L1 once on its own; the
archives are read back.

Usage:
    python tests/orangebox_h_from_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - `Survey.site` or `_check_instrument_keys` refuses `h_from` on an Orange
    Box site that keeps the default five channels;
  - the lent hx and hy of S1's archive are not L1's own archive samples at
    S1's grid times (exactly, sample for sample, over every sample of the
    overlap), or S1's archive keeps any sample outside L1's record;
  - S1's ex, ey and hz under `h_from` differ in any sample from the same
    times of S1 ingested without it, or hz is missing;
  - the run comment does not name L1 and say S1's own hx and hy were left
    out, or `archive_h_from` does not return "L1".
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location("orangebox_unit", REPO / "tests" / "orangebox_unit.py")
_ob_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ob_unit)  # the file writer; its import removes loguru's handlers
write_orange_bin = _ob_unit.write_orange_bin

import pandas as pd  # noqa: E402

N_FILE = 30003
FP = 0x7A1
T0 = datetime(2006, 5, 2, 14, 56, 0)  # Perth wall clock
T_REF = datetime(2006, 5, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp()
# the channel columns of the file: hx=ch0, hz=ch1, hy=ch2, ey=ch6, ex=ch7 (tests/orangebox_unit.py)
COLUMNS = {"hx": 0, "hz": 1, "hy": 2, "ey": 6, "ex": 7}


def _write_site(folder: Path, start: datetime, periods: dict, seed: int) -> None:
    """Write two back-to-back files with a sine of the given period (s) on each named channel, noise elsewhere."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t_utc = (start - timedelta(hours=8)).replace(tzinfo=timezone.utc).timestamp()
    for i in range(2):
        t = t_utc + (i * N_FILE + np.arange(N_FILE)) / 10.0
        counts = np.zeros((N_FILE, 8), dtype=np.int64)
        for comp, ch in COLUMNS.items():
            noise = rng.integers(-2000, 2000, N_FILE)
            sine = np.round(2 ** 19 * np.sin(2 * np.pi * (t - T_REF) / periods[comp])) if comp in periods else 0
            counts[:, ch] = 2 ** 23 + sine + noise
        counts[:, 3], counts[:, 4], counts[:, 5] = 1000, 1000, 20
        write_orange_bin(folder / f"HFM1-{i:03d}.BIN", counts, pd.Timestamp(start + timedelta(seconds=3000 * i)), fp=FP)
    (folder / "HFM1-RPT.TXT").write_text("High Frequency Magnetometer Number 1 - Flinders University 1999 - 2003\n",
                                         encoding="ascii")


def _survey(root: Path, name: str, s1: dict) -> Path:
    """Write a survey.yaml of S1 and L1 under root/name and return its path."""
    config = {"name": "obhfrom", "instrument": "orangebox", "sample_rate": 10, "data_root": str(root / "raw"),
              "workspace": str(root / f"ws_{name}"),
              "defaults": {"azimuth_ex": 0.0, "azimuth_ey": 90.0, "channels": ["ex", "ey", "hx", "hy", "hz"],
                           "electric_full_scale_uv": 25000.0, "magnetic_full_scale_nt": 70000.0,
                           "clock_timezone": "Australia/Perth"},
              "sites": {"S1": dict(dipole_length_ex=15.0, dipole_length_ey=20.0, latitude=-30.56, longitude=120.70,
                                   **s1),
                        "L1": dict(dipole_length_ex=20.0, dipole_length_ey=15.0, latitude=-30.56, longitude=120.65,
                                   clock_drift_s=3.0)}}
    path = root / name / "survey.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _read(path: Path, site: str) -> tuple[dict, list[str]]:
    """Return ({channel: pd.Series of raw counts by time}, [run comments]) over every run of a site."""
    from mth5.mth5 import MTH5

    series, comments = {}, []
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station(site, survey="obhfrom")
        for run_id in station.groups_list:
            if not run_id.startswith("sr"):
                continue
            run = station.get_run(run_id)
            comments.append(str(run.metadata.comments.value or ""))
            for comp in run.groups_list:
                ch = run.get_channel(comp).to_channel_ts()
                s = pd.Series(np.asarray(ch.ts, dtype=float), index=pd.DatetimeIndex(ch.data_array.time.values))
                series[comp] = pd.concat([series[comp], s]) if comp in series else s
    finally:
        m.close_mth5()
    return series, comments


def main() -> int:
    from mt_workbench.ingest import _check_instrument_keys, archive_h_from, ingest_site
    from mt_workbench.survey import Survey

    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_site(root / "raw" / "S1", T0, {"hx": 300.0, "hy": 410.0, "hz": 170.0, "ex": 230.0, "ey": 520.0}, 1)
        _write_site(root / "raw" / "L1", T0 + timedelta(seconds=600), {"hx": 777.0, "hy": 133.0}, 2)
        plain = Survey.from_yaml(_survey(root, "plain", {}))
        borrow = Survey.from_yaml(_survey(root, "borrow", {"h_from": "L1"}))
        site = borrow.site("S1")
        _check_instrument_keys(borrow, site, "orangebox")
        print(f"  Survey.site and _check_instrument_keys accept h_from {site.h_from} with channels {site.channels}")

        lender, _ = _read(ingest_site(plain, "L1", overwrite=True), "L1")
        own, _ = _read(ingest_site(plain, "S1", overwrite=True), "S1")
        out = ingest_site(borrow, "S1", overwrite=True)
        lent, comments = _read(out, "S1")

        assert sorted(lent) == ["ex", "ey", "hx", "hy", "hz"], sorted(lent)
        times = lent["hx"].index
        assert times[0] >= lender["hx"].index[0] and times[-1] <= lender["hx"].index[-1], (times[0], times[-1])
        for comp in ("hx", "hy"):
            theirs = lender[comp].reindex(times)
            assert not theirs.isna().any(), f"{comp}: {int(theirs.isna().sum())} lent samples at times L1 lacks"
            diff = np.abs(lent[comp].values - theirs.values).max()
            assert diff == 0.0, (comp, diff)
            mine = own[comp].reindex(times).values
            assert np.abs(mine - lent[comp].values).max() > 1000, f"{comp}: still S1's own samples"
            print(f"  {comp}: {len(times)} samples from {times[0]} to {times[-1]} equal L1's archive exactly "
                  f"(max |diff| {diff:g} counts); S1's own differ by up to {np.abs(mine - lent[comp].values).max():.0f}")
        for comp in ("ex", "ey", "hz"):
            mine = own[comp].reindex(lent[comp].index)
            assert not mine.isna().any() and np.abs(mine.values - lent[comp].values).max() == 0.0, comp
            print(f"  {comp}: unchanged from S1 without h_from over the {len(mine)} samples kept")
        cut = len(own["ex"]) - len(lent["ex"])
        print(f"  S1 kept {len(lent['ex'])} of its {len(own['ex'])} samples ({cut} before L1 starts left out)")
        assert cut > 0, cut
        joined = " | ".join(comments)
        assert "hx and hy of L1" in joined and "recorded hx and hy of S1 left out" in joined, joined
        assert archive_h_from(out, "S1") == "L1", archive_h_from(out, "S1")
        print(f"  run comment names L1 and the replaced pair; archive_h_from -> {archive_h_from(out, 'S1')!r}")
    print("\nPASS  orangebox_h_from_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
