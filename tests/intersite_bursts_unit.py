# -*- coding: utf-8 -*-
"""
Unit test for burst sites in the band layout and in intersite

B1 and B2: `mt_workbench.intersite.read_bursts`, the compact grid of burst
sites. Three synthetic burst archives are written through mth5 into
scratch, one run per burst as the Phoenix burst ingest writes them: 13
bursts of 2 s at 24 kHz every 30 s. The base's ex, ey are seeded white
noise; the local's are T0 = [[0.8, 0.3], [-0.2, 1.1]] times the base's
delayed by 3 samples, plus 5 % seeded noise; the reference's hx, hy are a
fixed mix of the base's plus 50 % noise. The archives carry no filter, so
the expected tensor of a band is T0 times the mean of e^{-i 2 pi f 3 / 24000}
over the band's harmonics (white inputs weigh them equally), built here
without the reader. The mean, not the value at one frequency: across a
band of level 0 (4.7-6 kHz) the 3-sample delay turns the phase by about
1 rad, which shrinks the band's |T| by up to 4 %, some 17 sigma.

Level 0 is held to a relative error instead of its jackknife sigma. With
the band mean as the expectation, levels 1-3 fall within 3 sigma and level
0 still shows |T| 0.2-0.4 % low, up to 8 sigma; with the delay set to 0
every level, level 0 included, is within 3 sigma (checked when this test
was written). The loss is the estimator's: a 3-sample shift inside a
128-sample Hann window decorrelates the two windows a little, a bias that
falls by 4 per level as the shift does, and that the 6,000 windows of
level 0 resolve. It says nothing about where the reader puts the samples.

B3: the shortest period of a site faster than the survey
(`mt_workbench.bands.site_min_period`). A burst site at 24 kHz in a 150 Hz
survey whose `processing:` min_period is 4**(22/6)/6000 s (the value that
puts the 150 Hz band edges on the 24 kHz ones) must take 1/6000 s, and the
two layouts must share every band they both cover.

Usage:
    python tests/intersite_bursts_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - B1: on the first 12 bursts, the compact grid and the dense grid of
    `read_channels` differ by more than one window per burst at any level
    of `band_spectra`; or the T estimated on the compact grid is not
    within 3 sigma of the expected tensor in 95 % of the (band, element)
    pairs of levels 1-3 and within 6 sigma in all of them, an element of
    level 0 is off by 2 % of |T0| or more (1.0 % measured: the bias
    below plus noise), the median |T - expected| over all pairs is 0.02
    or more, or for any one of levels 1, 2 and 3 the median |T - expected|
    over its bands and elements is 2 % of |T0| or more (0.10, 0.11 and
    0.35 % measured). The sigma rule alone cannot fail on decorrelated
    data, since the jackknife sigma grows with the misfit (100 % within 3
    sigma under the mutation below); the per-level bound can;
  - B2: `read_bursts` reads an archive whose fifth run's hx names a filter
    the first run's does not;
  - B3: `site_min_period(24000, 150, 4**(22/6)/6000)` is not 1/6000 s,
    `site_min_period(1, 1000, 0.005)` (a decimated site) is not 4 s, or the
    survey's own rate does not keep the survey's min_period;
    `build_band_scheme(24000, min_period=1/6000)` raises or its top edge is
    not 6000 Hz; fewer than all of the 150 Hz layout's bands inside the
    24 kHz layout's levels 0-4 (to 5.86 Hz) have both edges equal (1e-9 relative) to a 24 kHz
    band, or the two bands of 0.0269-0.0427 s are not among them; or
    scripts/process_intersite.py and scripts/process_rr.py do not take
    `--min-period`; or process_rr's `resolve`, on a scratch survey of two
    150 Hz Phoenix sites and their 24 kHz burst sites (its `check_pair`
    replaced, since the pair has no archive to take spans from), does not
    give min_period 1/6000 s to the burst pair, the survey's to the 150 Hz
    pair, and 0.001 s to the burst pair with `--min-period 0.001`.

The mutations: B1 with the base's bursts shifted by one slot against the
local's (the coherence collapses, the T check must fail, and the
per-level bound of each of levels 1, 2 and 3 on its own); B2 with the
chain comparison removed (the archive must then be read, and the check
must fail); B3 with the old rule, max(survey min_period, 4 / rate), under
which the 24 kHz site resolves to 0.0269 s and the first check and the
`resolve` check must fail.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.bands as bands  # noqa: E402
import mt_workbench.intersite as intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("intersite_bursts_unit")
RATE = 24000.0
BURST_N = 48000
EVERY_S = 30
N_BURSTS = 13
DELAY = 3
T0 = np.array([[0.8, 0.3], [-0.2, 1.1]])
START_NS = 1604617200 * 10**9  # a burst start on a whole second
# the bound on each of levels 1-3 of the median |T - expected| over its bands and elements, as a
# fraction of |T0| (the measured values are in the docstring)
LEVEL_BOUND = 0.02


def write_bursts(path: Path, station: str, bursts: list[dict], odd_run: int | None = None) -> Path:
    """Write a burst archive through mth5: one run per burst, as the Phoenix burst ingest does.

    Args:
        path (Path): The archive.
        station (str): The station.
        bursts (list of dict): {component: samples} per burst, every EVERY_S s from START_NS.
        odd_run (int, optional): A run (from 1) whose hx names an extra filter.
    """
    import pandas as pd
    from mt_metadata.timeseries import Electric, Magnetic
    from mt_metadata.timeseries.filters import CoefficientFilter
    from mth5.groups import FiltersGroup
    from mth5.mth5 import MTH5

    if path.exists():
        path.unlink()
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("BURSTS")
        station_group = m.add_station(station, survey="BURSTS")
        for k, chans in enumerate(bursts):
            t0 = pd.Timestamp(START_NS + k * EVERY_S * 10**9, unit="ns", tz="UTC")
            t1 = t0 + pd.Timedelta(seconds=(BURST_N - 1) / RATE)
            run = station_group.add_run(f"sr24000_{k + 1:05d}")
            for comp, data in chans.items():
                md = Electric() if comp.startswith("e") else Magnetic()
                md.component, md.sample_rate = comp, RATE
                md.time_period.start, md.time_period.end = t0.isoformat(), t1.isoformat()
                if odd_run == k + 1 and comp == "hx":
                    extra = CoefficientFilter()
                    extra.name, extra.gain, extra.units_in, extra.units_out = "b2_gain", 1.0, "Volt", "Volt"
                    FiltersGroup(run.hdf5_group.parent.parent.parent["Filters"]).add_filter(extra)
                    md.add_filter(name="b2_gain", applied=True, stage=1)
                run.add_channel(comp, md.type, data.astype(np.float32), channel_metadata=md)
            run.metadata.sample_rate = RATE
            run.metadata.time_period.start, run.metadata.time_period.end = t0.isoformat(), t1.isoformat()
            run.write_metadata()
    finally:
        m.close_mth5()
    return path


def synthetic_sites() -> dict[str, Path]:
    """Write the local, base and reference burst archives of B1."""
    rng = np.random.default_rng(20201105)
    local, base, ref = [], [], []
    mix = np.array([[0.6, -0.5], [0.4, 0.9]])
    for _k in range(N_BURSTS):
        ext = rng.standard_normal((2, BURST_N + DELAY))
        b = ext[:, DELAY:]
        signal = T0 @ ext[:, :BURST_N]  # local(t) = T0 base(t - DELAY samples)
        noise = 0.05 * signal.std(axis=1, keepdims=True) * rng.standard_normal(signal.shape)
        out = signal + noise
        h = mix @ b + 0.5 * rng.standard_normal(b.shape)
        local.append({"ex": out[0], "ey": out[1]})
        base.append({"ex": b[0], "ey": b[1]})
        ref.append({"hx": h[0], "hy": h[1]})
    return {"L": write_bursts(SCRATCH / "L.h5", "L", local), "B": write_bursts(SCRATCH / "B.h5", "B", base),
            "R": write_bursts(SCRATCH / "R.h5", "R", ref)}


def windows_per_level(arrays: dict, scheme: dict) -> dict[int, int]:
    """Return the windows of each level's first band (`band_spectra`)."""
    out = {}
    for band in intersite.band_spectra(arrays, RATE, scheme, None):
        out.setdefault(band.level, band.n_windows)
    return out


def check_compact(paths: dict, base_shift: int = 0) -> list[str]:
    """B1: windows on the compact against the dense grid, and the compact T. Returns the failures."""
    bad = []
    scheme = build_band_scheme(RATE, min_period=1 / 6000, max_period=0.05)
    slots = sorted(intersite.burst_slots(paths["L"], "L", ("ex", "ey")))[:12]
    base_slots = sorted(intersite.burst_slots(paths["B"], "B", ("ex", "ey")))[base_shift:base_shift + 12]
    arrays = {}
    for key, (site, roles, mine) in {"l_": ("L", ("ex", "ey"), slots), "b_": ("B", ("ex", "ey"), base_slots),
                                      "r_": ("R", ("hx", "hy"), slots)}.items():
        got, _resp, _chains = intersite.read_bursts(paths[site], site, roles, mine, BURST_N, RATE)
        arrays.update({key + r: v for r, v in got.items()})
    if base_shift == 0:
        n_dense = 11 * EVERY_S * int(RATE) + BURST_N
        dense, _r, _c = intersite.read_channels(paths["L"], "L", ("ex", "ey"), slots[0], n_dense, RATE)
        compact = windows_per_level({"l_ex": arrays["l_ex"], "l_ey": arrays["l_ey"]}, scheme)
        full = windows_per_level({"l_ex": dense["ex"], "l_ey": dense["ey"]}, scheme)
        for level in sorted(set(compact) | set(full)):
            a, b = compact.get(level, 0), full.get(level, 0)
            if abs(a - b) > 12:
                bad.append(f"level {level}: {a} windows compact, {b} dense")
        print(f"  B1 windows per level, compact / dense: "
              + ", ".join(f"L{lv} {compact.get(lv, 0)}/{full.get(lv, 0)}" for lv in sorted(full)))
    band_list = list(intersite.band_spectra(arrays, RATE, scheme, None))
    est = intersite.estimate(band_list, ("l_ex", "l_ey"), ("b_ex", "b_ey"), ("r_hx", "r_hy"))
    rotation = {round(b.period, 12): np.mean(np.exp(-2j * np.pi * b.freqs * DELAY / RATE)) for b in band_list}
    expected = T0[None] * np.array([rotation[round(p, 12)] for p in est.period])[:, None, None]
    diff = np.abs(est.tensor - expected)
    upper = est.level >= 1
    z = (diff / est.sigma)[upper]
    z = z[np.isfinite(z)]
    within3, worst, median = float(np.mean(z <= 3)), float(np.max(z)), float(np.median(diff))
    level0 = float(np.max(diff[~upper])) / float(np.max(np.abs(T0))) if (~upper).any() else 0.0
    if within3 < 0.95 or worst > 6 or median >= 0.02 or level0 >= 0.02:
        bad.append(f"T: {within3:.1%} of {z.size} pairs of levels 1-3 within 3 sigma, worst {worst:.1f} sigma, "
                   f"level 0 worst {level0:.2%} of |T0|, median |T - expected| {median:.3f}")
    # the sigma rule alone cannot fail on decorrelated data: the jackknife sigma grows with the misfit
    per_level = {int(lv): float(np.median(diff[est.level == lv])) / float(np.max(np.abs(T0)))
                 for lv in sorted(set(est.level.tolist())) if lv >= 1}
    for lv, frac in per_level.items():
        if frac >= LEVEL_BOUND:
            bad.append(f"level {lv}: median |T - expected| {frac:.2%} of |T0|")
    if sorted(per_level) != [1, 2, 3]:
        bad.append(f"levels 1-3 expected in the estimate, got {sorted(per_level)}")
    print(f"  B1 T{' (base shifted one burst)' if base_shift else ''}: {est.period.size} bands "
          f"{est.period.min():.2e}-{est.period.max():.3f} s, {within3:.1%} of {z.size} pairs of levels 1-3 within "
          f"3 sigma, worst {worst:.1f}; level 0 worst {level0:.2%} of |T0|; median |T - expected| {median:.4f}; "
          f"per level, median |T - expected| / |T0|: "
          + ", ".join(f"L{lv} {frac:.2%}" for lv, frac in per_level.items()))
    return bad


def check_chain_refusal() -> list[str]:
    """B2: a run whose hx names another filter must be refused. Returns the failures."""
    rng = np.random.default_rng(2)
    bursts = [{"hx": rng.standard_normal(BURST_N), "hy": rng.standard_normal(BURST_N)} for _ in range(6)]
    path = write_bursts(SCRATCH / "odd.h5", "ODD", bursts, odd_run=5)
    slots = sorted(intersite.burst_slots(path, "ODD", ("hx", "hy")))
    try:
        intersite.read_bursts(path, "ODD", ("hx", "hy"), slots, BURST_N, RATE)
    except ValueError as exc:
        print(f"  B2 refused: {str(exc)[:110]}")
        return []
    return ["B2: the archive with a different hx chain in run 5 was read"]

ALIGNED = 4 ** (22 / 6) / 6000  # 0.026878315731 s: 6000 / 4**(22/6) = 37.2047 Hz, the 150 Hz layout's top edge


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bands(scheme: dict) -> list[tuple[float, float]]:
    return [tuple(map(float, r)) for v in scheme["band_edges"].values() for r in np.asarray(v)]


def check_min_period() -> list[str]:
    """B3: the rule, the layout at 24 kHz and the shared bands. Returns the failures."""
    bad = []
    fast = bands.site_min_period(24000.0, 150.0, ALIGNED)
    if abs(fast - 1 / 6000) > 1e-15:
        bad.append(f"24 kHz in a 150 Hz survey: min_period {fast!r}, expected 1/6000")
    if bands.site_min_period(1.0, 1000.0, 0.005) != 4.0:
        bad.append("1 Hz in a 1000 Hz survey: not 4 s")
    if bands.site_min_period(150.0, 150.0, ALIGNED) != ALIGNED:
        bad.append("150 Hz in a 150 Hz survey: not the survey's min_period")
    bad += check_rr_resolve()
    try:
        burst = build_band_scheme(24000.0, min_period=fast)
    except ValueError as exc:
        return bad + [f"build_band_scheme(24000, {fast:g}) raised: {exc}"]
    top = max(hi for _lo, hi in _bands(burst))
    if abs(top - 6000.0) > 1e-6:
        bad.append(f"24 kHz layout top edge {top:g} Hz, expected 6000")
    cont = _bands(build_band_scheme(150.0, min_period=ALIGNED))
    # levels 0-4 of the 24 kHz layout: a burst gives windows to level 3; the levels below, with
    # periods of minutes, are cut short by the layout's max_period
    lo_b = min(float(np.min(burst["band_edges"][level])) for level in range(5))
    hi_b = top
    inside = [b for b in cont if b[0] >= lo_b * (1 - 1e-12) and b[1] <= hi_b * (1 + 1e-12)]
    shared = [b for b in inside if any(abs(b[0] - q[0]) <= 1e-9 * b[0] and abs(b[1] - q[1]) <= 1e-9 * b[1]
                                       for q in _bands(burst))]
    if len(shared) != len(inside) or not inside:
        bad.append(f"{len(shared)} of {len(inside)} 150 Hz bands share both edges with a 24 kHz band")
    overlap = [b for b in shared if 0.0268 <= 1 / b[1] and 1 / b[0] <= 0.0428]
    if len(overlap) != 2:
        bad.append(f"overlap bands 0.0269-0.0427 s: {overlap}")
    for name in ("process_intersite", "process_rr"):
        parser = _load(name).build_parser()
        if not any("--min-period" in a.option_strings for a in parser._actions):
            bad.append(f"scripts/{name}.py has no --min-period")
    return bad


def check_rr_resolve() -> list[str]:
    """B3: process_rr's `resolve` on a scratch survey of 150 Hz sites and their burst sites. Returns the failures."""
    import datetime

    import yaml

    folder = SCRATCH / "rr_resolve"
    (folder / "data").mkdir(parents=True, exist_ok=True)
    config = {"name": "BURSTS", "instrument": "phoenix", "sample_rate": 150.0, "data_root": str(folder / "data"),
              "workspace": str(folder / "workspace"), "processing": {"min_period": ALIGNED},
              "defaults": {"calibration_dir": str(folder)},
              "sites": {"A": {}, "B": {}, "AH": {"bursts_of": "A", "sample_rate": 24000},
                        "BH": {"bursts_of": "B", "sample_rate": 24000}}}
    survey_yaml = folder / "survey.yaml"
    survey_yaml.write_text(yaml.safe_dump(config))
    rr = _load("process_rr")
    rr.check_pair = lambda *args, **kwargs: {}  # spans need archives; the rule under test comes before
    bad = []
    for local, remote, extra, want in (("AH", "BH", [], 1 / 6000), ("A", "B", [], ALIGNED),
                                       ("AH", "BH", ["--min-period", "0.001"], 0.001)):
        args = rr.build_parser().parse_args([str(survey_yaml), local, remote, *extra])
        try:
            got = float(rr.resolve(args, datetime.datetime.now())["scheme_kwargs"]["min_period"])
        except Exception as exc:
            bad.append(f"process_rr resolve {local} {remote} {' '.join(extra)}: raised {exc}")
            continue
        if abs(got - want) > 1e-12 * want:
            bad.append(f"process_rr resolve {local} {remote} {' '.join(extra)}: min_period {got!r}, expected {want!r}")
    return bad


if __name__ == "__main__":
    import shutil
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    paths = synthetic_sites()
    failures = check_compact(paths)
    trip = check_compact(paths, base_shift=1)
    assert trip and trip[0].startswith("T:"), trip
    tripped = [t for t in trip if t.startswith("level ")]
    assert [t.split(":")[0] for t in tripped] == ["level 1", "level 2", "level 3"], trip
    print(f"  B1 mutation (base shifted one burst) tripped: {trip[0]}")
    print(f"  B1 mutation, each of levels 1-3 on its own: {'; '.join(tripped)}")
    failures += check_chain_refusal()
    kept_names = intersite._chain_names
    intersite._chain_names = lambda dataset: ()
    try:
        trip = check_chain_refusal()
    finally:
        intersite._chain_names = kept_names
    assert trip, "mutation B2 (no chain check) did not trip"
    print(f"  B2 mutation (no chain check) tripped: {trip[0]}")
    bad = check_min_period()
    failures += bad
    print(f"  B3: {'ok' if not bad else bad}: 24 kHz takes 1/6000 s, top edge 6000 Hz, every 150 Hz band "
          f"in range shared, two in 0.0269-0.0427 s; process_rr's resolve gives the burst pair 1/6000 s")
    kept = bands.site_min_period
    bands.site_min_period = lambda rate, survey_rate, mp, *_: (float(mp) if rate == survey_rate
                                                               else max(float(mp), 4.0 / rate))
    try:
        trip = check_min_period()
    finally:
        bands.site_min_period = kept
    assert trip and "1/6000" in trip[0], trip
    assert any(t.startswith("process_rr resolve AH BH :") for t in trip), trip
    print(f"  B3 mutation (max rule) tripped: {trip[0]}; "
          f"{next(t for t in trip if t.startswith('process_rr resolve AH BH :'))}")
    if failures:
        print("\nFAIL  intersite_bursts_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    shutil.rmtree(SCRATCH)
    print("\nPASS  intersite_bursts_unit")
