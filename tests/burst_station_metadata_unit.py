# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.process.slim_station_metadata and _keep_processed_runs on a burst station of many runs

A synthetic burst archive of 240 one-burst runs (tests/intersite_bursts_unit.write_bursts, the shape the Phoenix
burst ingest writes, with the station's run list as the ingest records it) is read the way aurora reads it, one
run at a time through RunGroup.to_runts. Outside the context, mth5 hands every channel a station metadata holding
all 240 runs; inside it, the one run.

Usage:
    python tests/burst_station_metadata_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. inside the context a channel's station metadata holds other than its one run, or outside it other than all;
2. inside the context the station metadata lacks the station id or the channel's run id, or the survey lacks
   the station;
3. the RunTS read inside the context differs from the one read outside in any sample, channel name, sample
   rate, run id or station id;
4. after the context the original mth5 method is back (a read then holds every run again);
5. reading 20 runs inside the context is not at least four times faster than outside (240 runs is small; the
   gain grows with the run count);
6. a mutation that leaves run_list untouched inside the context does not trip clause 1;
7. with `wanted` naming two runs, the station group's metadata holds other than those two with their channels,
   or a station read outside holds fewer than all;
8. `_keep_processed_runs` on a station of 300 runs whose estimate used two leaves other than those two, in their
   order, or drops anything when every run was used.
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _scratch import scratch_dir  # noqa: E402
import intersite_bursts_unit as ibu  # noqa: E402

from mt_workbench import process  # noqa: E402

N_RUNS = 240
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILED.append(what)


def build(path: Path) -> Path:
    """Write the burst archive and the station's run list, as the Phoenix burst ingest records it."""
    from mt_metadata.timeseries import Run
    from mth5.mth5 import MTH5

    rng = np.random.default_rng(7)
    bursts = [{"ex": rng.standard_normal(ibu.BURST_N), "ey": rng.standard_normal(ibu.BURST_N),
               "hx": rng.standard_normal(ibu.BURST_N), "hy": rng.standard_normal(ibu.BURST_N)}
              for _ in range(N_RUNS)]
    ibu.write_bursts(path, "S", bursts)
    m = MTH5()
    m.open_mth5(path, mode="a")
    try:
        st = m.get_station("S", "BURSTS")
        for k in range(1, N_RUNS + 1):
            st.metadata.add_run(Run(id=f"sr24000_{k:05d}"))
        st.write_metadata()
    finally:
        m.close_mth5()
    return path


def read_runs(h5: Path, run_ids: list[str]):
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(h5, mode="r")
    try:
        st = m.get_station("S", "BURSTS")
        out = []
        for rid in run_ids:
            run = st.get_run(rid)
            levels = run.get_channel("ex")._metadata_levels()
            out.append((run.to_runts(), levels))
        return out
    finally:
        m.close_mth5()


def station_runs(h5: Path, wanted=None) -> list[str]:
    """The run ids a station read holds with channels, inside the context with `wanted` or outside it."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(h5, mode="r")
    try:
        if wanted is None:
            return [r.id for r in m.get_station("S", "BURSTS").metadata.runs if r.channels]
        with process.slim_station_metadata(wanted):
            return [r.id for r in m.get_station("S", "BURSTS").metadata.runs if r.channels]
    finally:
        m.close_mth5()


def main() -> int:
    scratch = scratch_dir("burst_station_metadata_unit")
    h5 = build(scratch / "S.h5")
    ids = [f"sr24000_{k:05d}" for k in range(1, 21)]
    t0 = time.perf_counter()
    plain = read_runs(h5, ids)
    t_plain = time.perf_counter() - t0
    with process.slim_station_metadata():
        t0 = time.perf_counter()
        slim = read_runs(h5, ids)
        t_slim = time.perf_counter() - t0
    after = read_runs(h5, ids[:1])
    n_plain = sorted({len(levels[1].runs) for _, levels in plain})
    n_slim = sorted({len(levels[1].runs) for _, levels in slim})
    check(n_slim == [1] and n_plain == [N_RUNS],
          f"(1) runs in a channel's station metadata: inside {n_slim}, outside {n_plain} (one and {N_RUNS})")
    ok2 = all(levels[1].id == "S" and levels[1].runs[0].id == rid and levels[2].stations[0].id == "S"
              for (_, levels), rid in zip(slim, ids))
    check(ok2, "(2) inside the context the station keeps its id and the channel's run, the survey its station")
    same = True
    for (a, _), (b, _) in zip(plain, slim):
        same &= list(a.channels) == list(b.channels) and a.sample_rate == b.sample_rate
        same &= a.run_metadata.id == b.run_metadata.id and a.station_metadata.id == b.station_metadata.id
        for c in a.channels:
            same &= np.array_equal(a.dataset[c].values, b.dataset[c].values)
    check(same, "(3) the RunTS read inside the context equals the one read outside: samples, channels, rate, ids")
    n_after = len(after[0][1][1].runs)
    check(n_after == N_RUNS, f"(4) after the context a read holds every run again ({n_after})")
    ratio = t_plain / max(t_slim, 1e-9)
    check(ratio >= 4.0, f"(5) 20 runs read in {t_slim:.2f} s inside against {t_plain:.2f} s outside: "
                        f"{ratio:.1f}x (at least 4x)")
    from mth5.groups.channel_dataset import ChannelDataset

    original = ChannelDataset._station_metadata_with

    def untrimmed(self, run_metadata):
        return original(self, run_metadata)

    ChannelDataset._station_metadata_with = untrimmed
    try:
        mutant = read_runs(h5, ids[:2])
    finally:
        ChannelDataset._station_metadata_with = original
    check(all(len(levels[1].runs) == N_RUNS for _, levels in mutant),
          "(6) mutation (run_list left untouched) trips clause 1: every run comes back")
    want = {ids[4], ids[5]}
    filled = sorted(station_runs(h5, want))
    filled_all = len(station_runs(h5))
    check(set(filled) == want and filled_all == N_RUNS,
          f"(7) the station getter holds the wanted runs inside ({filled}) and every run outside "
          f"({filled_all} of {N_RUNS})")
    from mt_metadata.timeseries import Run
    from mt_metadata.transfer_functions.tf import Station

    station = Station(id="S")
    for k in range(1, 301):
        station.add_run(Run(id=f"sr24000_{k:05d}"))
    station.transfer_function.runs_processed = ["sr24000_00010", "sr24000_00011"]
    dropped = process._keep_processed_runs(types.SimpleNamespace(station_metadata=station))
    kept = [r.id for r in station.runs]
    full = Station(id="S")
    full.add_run(Run(id="a"))
    full.transfer_function.runs_processed = ["a"]
    none_dropped = process._keep_processed_runs(types.SimpleNamespace(station_metadata=full))
    check(dropped == 298 and kept == ["sr24000_00010", "sr24000_00011"] and none_dropped == 0,
          f"(8) the product keeps the estimate's runs: dropped {dropped}, kept {kept}; a full use drops none")
    print(("FAIL  " if FAILED else "PASS  ") + f"burst_station_metadata_unit ({len(FAILED)} of 8 failed)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    os.environ.setdefault("MT_WORKBENCH_TEST_SCRATCH", str(Path(__file__).resolve().parents[1] / "work" / "scratch"))
    sys.exit(main())
