# -*- coding: utf-8 -*-
"""
Unit test for the calibration of each run of a site with its own filter chain (intersite.read_channels)

The fields are those of tests/intersite_unit.py (`fields`): red-noise
sources Bx, By, a base E and a local E = A exp(i phi0) exp(-2 pi i f tau)
E_base + noise. A scratch workspace at 100 Hz holds 3 h of four archives,
each channel written as int32 counts of its calibrated signal times its
chain's response:

- L2, the local in two runs of 1.5 h, end to end: the electric chains of
  the second run have twice the gain of the first's (ex 50 then 100, ey
  40 then 80 counts per mV/km), under their own filter names, as after a
  gain change in the field; the magnetic chains are the same in both runs;
- L1, the same local signal in one run with the first run's chains;
- LS, the same local signal in two runs of 1.5 h whose chains are the
  same (the same filters in both runs);
- B, the base, and R, the reference, one run each.

T is estimated from each local's E on B's E referenced to R's H through
read_channels, band_spectra and estimate. L1 and L2 record the same field,
so their T differ only by the windows L2 loses at its run boundary, which
cannot be calibrated with one chain. Leaving out a fraction q of a band's
windows moves an element by about sqrt(q / (1 - q)) sigma, the relation
the jackknife error rests on (one slice of 20 moves it by sigma /
sqrt(19)). L2 loses two windows per level at the cut: under 1 % at the
short periods, and 6 of 29 at the longest level, where sqrt(q / (1 - q))
is 0.5, so a worst case of 3 sigma over the 148 element-bands leaves room
for the scatter of that half sigma. A second run calibrated with the
first run's chain makes its E look twice as large, which moves |T| by
about half of itself, hundreds of sigma at the short periods.

Usage:
    python tests/intersite_runs_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (per-run chains) any element-band of T from L2 with a finite error
   differs from T from L1 by more than 3 times L1's error, or fewer than
   90 % of L1's element-bands have a finite value in L2's estimate;
2. (mutation, must trip 1) T from the same L2 samples with every run
   calibrated by the first run's chain (the response of
   `crosspower._Station.response` for run 0 on every window) stays within
   3 sigma of L1's in every element-band;
3. (two chains seen) read_channels on L2 does not record two runs for ex
   and for ey with different filter names, or gives ex a plain callable
   rather than an `intersite.RunResponses`; or it records runs for hx
   (one chain in both runs), or gives hx anything but a plain callable;
4. (one chain, unchanged) T from LS (two runs, one chain) is not exactly
   equal, element by element and error by error, to T from L1; or LS's
   samples read by read_channels differ from L1's in any sample (a
   boundary marked where the chain does not change).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import FS2, T_START, fields  # noqa: E402
from mt_workbench import crosspower, intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

SCRATCH = scratch_dir("intersite_runs_unit")
HOURS = 3.0
E_GAINS = {"ex": 50.0, "ey": 40.0}
H_GAINS = {"hx": 10.0, "hy": 10.0}

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def _chain(name: str, comp: str, gain: float) -> list:
    """Return a one-stage chain: a gain from physical units to counts."""
    from mt_metadata.timeseries.filters import CoefficientFilter

    units = "mV/km" if comp.startswith("e") else "nT"
    return [CoefficientFilter(name=name, units_in=units, units_out="count", gain=gain)]


def write_runs(path: Path, site: str, spec: dict, key: str, runs: list) -> None:
    """Write an archive of one station in one or more runs, each channel through its run's chain.

    Args:
        path (Path): The archive.
        site (str): The station.
        spec (dict): The spectra of `fields`, with "scale".
        key (str): The spectra's site key ("l", "b", "r").
        runs (list): Per run (first sample, samples, {comp: chain}).
    """
    from mt_metadata.timeseries.filters import ChannelResponse
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("SYNTH")
        station = m.add_station(site, survey="SYNTH")
        for k, (offset, n, chains) in enumerate(runs):
            start = T_START + pd.Timedelta(seconds=offset / FS2)
            chans = []
            for comp in ("ex", "ey", "hx", "hy"):
                chain = chains[comp]
                response = np.ones(spec["f"].size, dtype=complex)
                for stage in chain:
                    response *= stage.complex_response(spec["f"])
                physical = spec[f"{key}_{comp}"] * spec["scale"]
                counts = np.rint(np.fft.irfft(physical * response, spec["n"])[offset:offset + n]).astype("int32")
                typ = "electric" if comp.startswith("e") else "magnetic"
                ch = ChannelTS(channel_type=typ, data=counts,
                               channel_metadata={typ: {"component": comp, "sample_rate": FS2,
                                                       "time_period.start": start.isoformat()}},
                               channel_response=ChannelResponse(filters_list=chain))
                for applied in ch.channel_metadata.filters:
                    applied.applied = True
                chans.append(ch)
            run_id = f"sr{int(FS2)}_{k + 1:04d}"
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS2}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()


def chains_for(site: str, factor: float, tag: str = "") -> dict:
    """Return a run's chains: E gains times `factor`, H gains as they are, named after the site and `tag`."""
    out = {c: _chain(f"{site.lower()}_{c}_gain{tag}", c, g * factor) for c, g in E_GAINS.items()}
    out |= {c: _chain(f"{site.lower()}_{c}_gain", c, g) for c, g in H_GAINS.items()}
    return out


def build() -> tuple[dict, dict]:
    """Write the five archives; return their paths and the spectra."""
    shutil.rmtree(SCRATCH / "mth5", ignore_errors=True)
    spec = fields(FS2, HOURS, seed=11, h_sites=("l", "b", "r"))
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    n, half = spec["n"], spec["n"] // 2
    paths = {s: SCRATCH / "mth5" / f"{s}.h5" for s in ("L1", "L2", "LS", "B", "R")}
    write_runs(paths["L1"], "L1", spec, "l", [(0, n, chains_for("L1", 1.0))])
    write_runs(paths["L2"], "L2", spec, "l", [(0, half, chains_for("L2", 1.0)),
                                              (half, n - half, chains_for("L2", 2.0, "_x2"))])
    one = chains_for("LS", 1.0)
    write_runs(paths["LS"], "LS", spec, "l", [(0, half, one), (half, n - half, one)])
    write_runs(paths["B"], "B", spec, "b", [(0, n, chains_for("B", 1.0))])
    write_runs(paths["R"], "R", spec, "r", [(0, n, chains_for("R", 1.0))])
    return paths, spec


def estimate_local(paths: dict, local: str, n: int, scheme: dict, first_chain_only: bool = False):
    """Return T of `local` on B referenced to R, read through read_channels, and the local's read record.

    With `first_chain_only` every window of the local is calibrated with
    its first run's chain, the calibration before each run took its own.
    """
    t0 = int(T_START.tz_localize("UTC").value)
    arrays, responses, labels = {}, {}, {}
    for site, roles, prefix in ((local, ("ex", "ey"), "l_"), ("B", ("ex", "ey"), "b_"), ("R", ("hx", "hy"), "r_")):
        got, resp, chains = intersite.read_channels(paths[site], site, roles, t0, n, FS2)
        if site == local:
            labels = chains
            if first_chain_only:
                st = crosspower._layout(paths[site], site, roles)
                resp = {r: (lambda f, r=r: st.response(r, f)) for r in roles}
        arrays.update({prefix + r: got[r] for r in roles})
        responses.update({prefix + r: resp[r] for r in roles})
    local_samples = {r: arrays["l_" + r].copy() for r in ("ex", "ey")}
    bands = intersite.band_spectra(arrays, FS2, scheme, responses)
    est = intersite.estimate(bands, ("l_ex", "l_ey"), ("b_ex", "b_ey"), ("r_hx", "r_hy"))
    return est, labels, local_samples


def deviation(est, ref) -> tuple[float, int, int]:
    """Return the worst |T - T_ref| / sigma_ref over element-bands, and the finite counts of est and ref."""
    by_period = {round(float(p), 9): b for b, p in enumerate(est.period)}
    worst, n_est, n_ref = 0.0, 0, 0
    for b, p in enumerate(ref.period):
        ok = np.isfinite(ref.sigma[b]) & (ref.sigma[b] > 0)
        n_ref += int(ok.sum())
        j = by_period.get(round(float(p), 9))
        if j is None:
            continue
        d = np.abs(est.tensor[j] - ref.tensor[b]) / ref.sigma[b]
        good = ok & np.isfinite(d)
        n_est += int(good.sum())
        if good.any():
            worst = max(worst, float(d[good].max()))
    return worst, n_est, n_ref


def main() -> int:
    """Run the criteria; return 0 when all pass."""
    paths, spec = build()
    n = spec["n"]
    scheme = build_band_scheme(FS2, min_period=0.04, max_period=200.0)
    t1, lab1, s1 = estimate_local(paths, "L1", n, scheme)
    t2, lab2, _s2 = estimate_local(paths, "L2", n, scheme)
    tm, _lab, _sm = estimate_local(paths, "L2", n, scheme, first_chain_only=True)
    ts, labs, ss = estimate_local(paths, "LS", n, scheme)
    print(f"{t1.period.size} bands, {n} samples at {FS2:g} Hz")

    # 1. per-run chains
    worst, n_est, n_ref = deviation(t2, t1)
    check(worst <= 3.0 and n_est >= 0.9 * n_ref,
          f"1 L2 (gains x1 then x2) against L1 (one chain): worst {worst:.3f} sigma (at most 3), "
          f"{n_est} of {n_ref} element-bands finite")

    # 2. mutation: the first run's chain on every window
    worst_m, _ne, _nr = deviation(tm, t1)
    check(worst_m > 3.0, f"2 mutation trips: the first run's chain on both runs of L2 gives {worst_m:.1f} sigma")

    # 3. two chains seen for E, one for H
    run_responses = getattr(intersite, "RunResponses", ())
    _got, resp_h, lab_h = intersite.read_channels(paths["L2"], "L2", ("ex", "ey", "hx", "hy"),
                                                 int(T_START.tz_localize("UTC").value), n, FS2)
    ok = True
    for role in ("ex", "ey"):
        runs = lab2[role].get("runs") or []
        names = [tuple(r["filters"]) for r in runs]
        ok &= len(runs) == 2 and len(set(names)) == 2
        ok &= isinstance(resp_h[role], run_responses)
    ok &= "runs" not in lab_h["hx"] and not isinstance(resp_h["hx"], run_responses)
    check(ok, f"3 read_channels records two chains for L2's ex and ey ({lab2['ex'].get('runs')}) and one for hx "
              f"({lab_h['hx']})")

    # 4. one chain in two runs: the same samples and the same T as one run
    same_samples = all(np.array_equal(ss[r], s1[r], equal_nan=True) for r in ("ex", "ey"))
    same_t = (np.array_equal(ts.tensor, t1.tensor, equal_nan=True)
              and np.array_equal(ts.sigma, t1.sigma, equal_nan=True)
              and np.array_equal(ts.period, t1.period))
    check(same_samples and same_t and "runs" not in labs["ex"],
          f"4 LS (two runs, one chain) gives L1's samples ({same_samples}) and L1's T and errors exactly ({same_t})")

    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILURE(S)'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
