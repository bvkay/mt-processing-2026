# -*- coding: utf-8 -*-
"""
Unit test for the calibration a synthetic-remote stack carries (mt_workbench.virtual)

Builds stacks from synthetic members whose archives carry a filter chain
as an EDL + LEMI-120 member's does (a frequency response table in
nanoTesla, then a coefficient in nanoTesla -> microVolt; units microVolt),
and checks that the stack is written with the members' common chain and
units, that members whose chains differ by a constant are scaled onto the
first member's, that the weighting rule is unchanged by the scaling, that
the stack in physical units is the weighted mean of the members in physical
units whatever gains they were recorded with, and that members whose
responses differ in shape, or carry a chain beside members that carry
none, refuse the build; members with no chain at all give the uncalibrated
stack of before, with its warning.

Members: 1000 Hz, four 10-minute chunks plus a 1234-sample tail (the
coherence ladder needs more than two). The
physical field b_i(t) of member i is one white-noise field of 1 nT rms per
coil plus the member's own noise of 0.2 nT rms, plus a DC offset of
50-150 nT. The archives store g_i * b_i in microVolt (the gain g_i is the
coefficient stage; the response table is declared, as in a real archive,
not applied to the synthetic samples: the stack never applies a chain, it
copies one). Sets:

- S0: A1, A2, A3 with one chain (gain 400000, table T);
- S1: the same b_i with gains 400000, 200000, -800000 and table T (A2 on
  half the scale, A3 on twice the scale and reversed);
- S2: as S0 but A3's table is T3 (another corner frequency);
- S3: no chain and units left as mth5 gives them (as tests/virtual_unit.py
  writes its members);
- S4: A1, A2 with the chain, A3 without;
- S5: as S0 but A2's table is T scaled by a factor that runs from 1 to
  1 + 4e-6 across the grid (its ratio to A1's departs from its mean by 2e-6),
  and S6 by one that runs to 1 + 1e-6 (5e-7: the tolerance's two sides).

Usage:
    python tests/stack_calibration_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. the S0 stack's hx or hy is not written in units microVolt with the two
   applied filters [table, coefficient] at stages 1 and 2 (the names of the
   member's chain), or the stack archive's own `channel_response`
   (`mth5`, resolved from its Filters group) differs from the member's
   on 241 frequencies from 1e-4 Hz to Nyquist by more than 1e-9 relative, or
   aurora's `get_calibration_filters` on the stack's run does not return
   those two filters to remove;
2. the coherence-weighted S1 stack differs from the coherence-weighted S0
   stack (float32, as archived) by more than 1e-6 of S0's rms on either
   coil, or S1's chain is not A1's (gain 400000, units microVolt), or the
   scales returned through `calibration_out` are not exactly {A1: 1,
   A2: 2, A3: -0.5}, or the run comment's calibration line does not name
   them;
3. any S1 weight differs from the S0 weight by more than 1e-9 (the rule is
   scale-free, so scaling a member changes no weight);
4. the S1 stack divided by its declared gain (400000) differs from the
   single-shot weighted mean of the physical members b_i (each less the
   median of its even subsample, S1's weights spread over the chunks, the
   tail taking the last chunk's) by more than 1e-6 of that mean's rms: the
   stack in physical units does not depend on the gains the members were
   recorded with;
5. the plain-mean S1 stack (weighting "none") differs from the plain-mean
   S0 stack by more than 1e-6 of its rms, or either's station comment lacks
   "calibrated: hx and hy carry the members' common filter chain";
6. S2 does not raise a ValueError naming hx, A3, A1 and "differ in frequency
   response";
7. S3 is not written as before: units "digital counts", no filters, hx/hy
   bytes equal to the frozen plain mean of the stored samples (float64 sum
   in member order / count -> float32), the station comment's no-chain
   wording, no "calibration:" line in the run comment, `calibration_out`
   {hx: None, hy: None}, and one WARNING per coil saying "no member
   carries a filter chain" (captured on the module's logger: mth5 resets
   loguru's handlers whenever it opens a file, so a sink added here is
   gone by the time the warning fires);
8. S4 does not raise a ValueError naming hx, A3 and "no filter chain";
9. S5 (a response ratio departing from its mean by 2e-6) is not refused,
   or S6 (by 5e-7) is refused;
10. `_Coil` with scale 2.0 does not return float64 twice the stored slice, or
    `_Coil` with scale 1.0 does not return the stored slice's bytes and dtype.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mt_metadata.timeseries import Magnetic
from mt_metadata.timeseries.filters import CoefficientFilter, FrequencyResponseTableFilter
from mth5.mth5 import MTH5

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mt_workbench.virtual as virtual  # noqa: E402
from virtual_unit import SURVEY, T0, fake_survey, read_back, write_archive  # noqa: E402

FS = 1000.0
CHUNK = int(virtual.WEIGHT_CHUNK_S * FS)
N_CHUNKS = 4
N = N_CHUNKS * CHUNK + 1234
MEMBERS = ["A1", "A2", "A3"]
G0 = 400000.0
GAINS_S1 = {"A1": 400000.0, "A2": 200000.0, "A3": -800000.0}
OFFSETS = {"A1": 50.0, "A2": 100.0, "A3": 150.0}  # nT, so a scaled member's offset follows its samples
GRID = np.logspace(-4, np.log10(FS / 2), 241)

failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def coil_table(name: str, corner_hz: float = 1.0, shape=None) -> FrequencyResponseTableFilter:
    """Build a coil-like response table: amplitude f / sqrt(f^2 + fc^2), phase atan(fc / f), nanoTesla -> nanoTesla.

    Args:
        name (str): The filter's name.
        corner_hz (float): The corner frequency.
        shape (callable, optional): A factor on the amplitude per frequency
            (a response differing in shape).
    """
    f = np.logspace(-4, 3, 57)
    amp = f / np.sqrt(f ** 2 + corner_hz ** 2)
    if shape is not None:
        amp = amp * shape(f)
    return FrequencyResponseTableFilter(name=name, frequencies=f, amplitudes=amp, phases=np.arctan2(corner_hz, f),
                                        units_in="nanoTesla", units_out="nanoTesla", gain=1.0)


def physical_members(seed: int = 7) -> dict[str, dict[str, np.ndarray]]:
    """Return {member: {coil: b (nT, float64)}}: one common field per coil plus each member's own noise and offset."""
    rng = np.random.default_rng(seed)
    field = {c: rng.normal(0.0, 1.0, N) for c in virtual.COILS}
    return {m: {c: field[c] + rng.normal(0.0, 0.2, N) + OFFSETS[m] for c in virtual.COILS} for m in MEMBERS}


def write_member(workspace: Path, site: str, coils: dict, chain: dict | None) -> Path:
    """Write one member as `ingest_site` lays an EDL member out: float64 samples, the chain in the Filters group.

    Args:
        workspace (Path): The archive is <workspace>/mth5/<site>.h5.
        site (str): The member.
        coils (dict): {coil: float64 samples}.
        chain (dict or None): {coil: [filter objects in stage order]} with
            units microVolt; None writes no chain and no units.
    """
    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    end = T0 + pd.Timedelta(seconds=(N - 1) / FS)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        survey_group = m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        run = station.add_run("sr1000_0001")
        for comp, data in coils.items():
            md = Magnetic()
            md.component = comp
            md.sample_rate = FS
            md.time_period.start = T0.isoformat()
            md.time_period.end = end.isoformat()
            md.measurement_azimuth = 0.0 if comp == "hx" else 90.0
            if chain is not None:
                md.units = "microVolt"
                for stage, f in enumerate(chain[comp], 1):
                    survey_group.filters_group.add_filter(f)
                    md.add_filter(name=f.name, applied=True, stage=stage)
            run.add_channel(comp, "magnetic", np.asarray(data, dtype="float64"), channel_metadata=md)
        run.metadata.sample_rate = FS
        run.metadata.time_period.start = T0.isoformat()
        run.metadata.time_period.end = end.isoformat()
        run.write_metadata()
        station.metadata.time_period.start = T0.isoformat()
        station.metadata.time_period.end = end.isoformat()
        station.write_metadata()
    finally:
        m.close_mth5()
    return path


def chain_for(member: str, gain: float, table: FrequencyResponseTableFilter | None = None) -> dict:
    """Return {coil: [table, coefficient]} with the member's gain (nanoTesla -> microVolt)."""
    out = {}
    for comp in virtual.COILS:
        fap = table if table is not None else coil_table(f"lemi_120_{comp}_response")
        fap = FrequencyResponseTableFilter(name=f"lemi_120_{comp}_response", frequencies=fap.frequencies,
                                           amplitudes=fap.amplitudes, phases=fap.phases, units_in="nanoTesla",
                                           units_out="nanoTesla", gain=1.0)
        coef = CoefficientFilter(name=f"lemi120_dc_gain_{comp}", gain=float(gain), units_in="nanoTesla",
                                 units_out="microVolt")
        out[comp] = [fap, coef]
    return out


def write_set(tmp: Path, label: str, physical: dict, gains: dict | None, tables: dict | None = None,
              no_chain=()) -> Path:
    """Write a member set under <tmp>/<label>: samples g_i * b_i in microVolt with each member's chain.

    Args:
        gains (dict or None): {member: gain}; None writes every member
            uncalibrated (no chain, raw b_i).
        tables (dict, optional): {member: table} overriding the default
            table for those members.
        no_chain (tuple): Members written with the samples of their gain
            but no chain (S4).
    """
    ws = tmp / label
    for member in MEMBERS:
        if gains is None:
            write_member(ws, member, physical[member], None)
            continue
        g = gains[member]
        samples = {c: g * physical[member][c] for c in virtual.COILS}
        chain = None if member in no_chain else chain_for(member, g, (tables or {}).get(member))
        write_member(ws, member, samples, chain)
    return ws


def build(ws: Path, tmp: Path, name: str, **kwargs):
    """Run build_synthetic_remote on the set in `ws`; return (path, weights, calibration)."""
    weights: dict = {}
    calibration: dict = {}
    path = virtual.build_synthetic_remote(fake_survey(ws), MEMBERS, "2023-09-19", "2023-09-20", name=name,
                                          out_path=tmp / f"{name}.h5", weights_out=weights,
                                          calibration_out=calibration, **kwargs)
    return path, weights, calibration


def stack_channels(path: Path, name: str) -> dict:
    """Read the stack's channel units, applied filters and resolved response on GRID, per coil, through mth5."""
    out = {}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(name, survey=SURVEY).get_run("sr1000_0001")
        for comp in virtual.COILS:
            ch = run.get_channel(comp)
            cr = ch.channel_response
            logger.disable("mt_metadata")
            try:
                resp = cr.complex_response(GRID, filters_list=cr.filters_list) if cr.filters_list else None
            finally:
                logger.enable("mt_metadata")
            out[comp] = {"units": str(ch.metadata.units), "filters": [(f.name, bool(f.applied), f.stage)
                                                                       for f in (ch.metadata.filters or [])],
                         "response": resp, "gains": [float(f.gain) for f in cr.filters_list]}
    finally:
        m.close_mth5()
    return out


def member_response(chain: dict, comp: str) -> np.ndarray:
    """Return the product of a member chain's responses on GRID."""
    logger.disable("mt_metadata")
    try:
        resp = np.ones(GRID.size, dtype=complex)
        for f in chain[comp]:
            resp = resp * f.complex_response(GRID)
    finally:
        logger.enable("mt_metadata")
    return resp


def single_shot_weighted(physical: dict, info: dict, comp: str) -> np.ndarray:
    """Return the whole-array weighted mean of the physical members with `info`'s weights (float64)."""
    w = info["weights"]
    k = np.minimum(np.arange(N) // CHUNK, w.shape[1] - 1)
    acc = np.zeros(N, dtype="float64")
    for i, m in enumerate(info["members"]):
        a = physical[m][comp]
        off = float(np.median(a[:: max(1, a.size // 1_000_000)]))
        acc += w[i][k] * (a - off)
    return acc


def frozen_mean(ws: Path, comp: str) -> np.ndarray:
    """Return the plain-mean arithmetic as written on the stored samples: float64 sum in member order / count -> float32."""
    acc = np.zeros(N, dtype="float64")
    m = MTH5()
    for member in MEMBERS:
        m.open_mth5(ws / "mth5" / f"{member}.h5", mode="r")
        try:
            acc += m.get_channel(member, "sr1000_0001", comp, SURVEY).hdf5_dataset[:].astype("float64")
        finally:
            m.close_mth5()
    return (acc / len(MEMBERS)).astype("float32")


def raises(fn) -> str:
    """Return the ValueError message `fn()` raises, or "" if it raises none."""
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return ""


class _Capture:
    """Stand-in for the module's logger that keeps the warning messages and passes everything else through."""

    def __init__(self):
        self.warnings: list[str] = []

    def warning(self, message, *args, **kwargs):
        self.warnings.append(str(message))

    def __getattr__(self, name):
        return getattr(logger, name)


def rel_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Return max |a - b| over the rms of b."""
    return float(np.max(np.abs(a.astype("float64") - b.astype("float64"))) / np.sqrt(np.mean(b.astype("float64") ** 2)))


def main() -> None:
    """Run the checks and exit 1 when any failed."""
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    physical = physical_members()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        s0 = write_set(tmp, "S0", physical, {m: G0 for m in MEMBERS})
        s1 = write_set(tmp, "S1", physical, GAINS_S1)
        chain0 = chain_for("A1", G0)

        # 1. the chain, units and resolved response of the S0 stack
        p0, w0, cal0 = build(s0, tmp, "STK_S0", weighting="coherence")
        ch0 = stack_channels(p0, "STK_S0")
        for comp in virtual.COILS:
            want = [(f"lemi_120_{comp}_response", True, 1), (f"lemi120_dc_gain_{comp}", True, 2)]
            check(ch0[comp]["units"] == "microVolt" and ch0[comp]["filters"] == want,
                  f"1. S0 {comp}: units microVolt, applied filters {want}")
            got, ref = ch0[comp]["response"], member_response(chain0, comp)
            dev = float(np.max(np.abs(got - ref) / np.abs(ref))) if got is not None else np.inf
            check(dev <= 1e-9, f"1. S0 {comp}: the archive's own channel_response equals the member's on the grid "
                               f"(max rel dev {dev:.2e})")
        from aurora.time_series.spectrogram_helpers import get_calibration_filters

        m = MTH5()
        m.open_mth5(p0, mode="r")
        try:
            run = m.get_station("STK_S0", survey=SURVEY).get_run("sr1000_0001")
            _, to_remove = get_calibration_filters(run, "hx")
            names = [f.name for f in to_remove]
        finally:
            m.close_mth5()
        check(names == ["lemi_120_hx_response", "lemi120_dc_gain_hx"],
              f"1. aurora get_calibration_filters on the stack's hx returns the chain to remove: {names}")

        # 2. S1 (gains 4e5, 2e5, -8e5) harmonised onto A1 equals S0
        p1, w1, cal1 = build(s1, tmp, "STK_S1", weighting="coherence")
        r0, r1 = read_back(p0, "STK_S0"), read_back(p1, "STK_S1")
        ch1 = stack_channels(p1, "STK_S1")
        for comp in virtual.COILS:
            d = rel_diff(r1[comp], r0[comp])
            check(d <= 1e-6, f"2. S1 {comp} equals S0 (max |diff| / rms {d:.2e} <= 1e-6)")
            check(ch1[comp]["units"] == "microVolt" and ch1[comp]["gains"] == [1.0, G0],
                  f"2. S1 {comp}: carries A1's chain (gains {ch1[comp]['gains']}, {ch1[comp]['units']})")
            check(cal1[comp]["reference"] == "A1" and cal1[comp]["scales"] == {"A1": 1.0, "A2": 2.0, "A3": -0.5},
                  f"2. S1 {comp}: calibration_out scales {cal1[comp]['scales']} (reference {cal1[comp]['reference']})")
        line = [ln for ln in r1["run_comment"].split("\n") if ln.startswith("calibration: ")]
        check(len(line) == 1 and "hx chain of A1 (lemi_120_hx_response, lemi120_dc_gain_hx) in microVolt, scales "
              "A1 x1, A2 x2, A3 x-0.5" in line[0] and "hy chain of A1" in line[0],
              f"2. the run comment's calibration line names the chain and the scales: {line[:1]}")

        # 3. the weights are unchanged by the scaling
        for comp in virtual.COILS:
            dw = float(np.max(np.abs(w1[comp]["weights"] - w0[comp]["weights"])))
            check(dw <= 1e-9, f"3. {comp}: S1 weights equal S0 weights (max |diff| {dw:.2e})")

        # 4. the stack in physical units is the weighted mean of the physical members
        for comp in virtual.COILS:
            ref = single_shot_weighted(physical, w1[comp], comp)
            d = rel_diff(r1[comp].astype("float64") / G0, ref)
            check(d <= 1e-6, f"4. {comp}: S1 / 400000 equals the weighted mean of the physical members "
                             f"(max |diff| / rms {d:.2e})")

        # 5. the plain mean path
        q0, _, _ = build(s0, tmp, "STK_S0m", weighting="none")
        q1, _, calm = build(s1, tmp, "STK_S1m", weighting="none")
        m0, m1 = read_back(q0, "STK_S0m"), read_back(q1, "STK_S1m")
        for comp in virtual.COILS:
            d = rel_diff(m1[comp], m0[comp])
            check(d <= 1e-6, f"5. plain mean: S1 {comp} equals S0 (max |diff| / rms {d:.2e})")
        phrase = "calibrated: hx and hy carry the members' common filter chain"
        check(phrase in m0["station_comment"] and phrase in m1["station_comment"] and phrase in r0["station_comment"],
              "5. station comments say the stack is calibrated")
        check(calm["hx"]["scales"] == {"A1": 1.0, "A2": 2.0, "A3": -0.5}, "5. plain mean: the same scales")

        # 6. a member of another response table is refused
        s2 = write_set(tmp, "S2", physical, {m: G0 for m in MEMBERS},
                       tables={"A3": coil_table("lemi_120_hx_response", corner_hz=3.0)})
        msg = raises(lambda: build(s2, tmp, "STK_S2"))
        check(all(s in msg for s in ("hx", "A3", "A1", "differ in frequency response")),
              f"6. another response table is refused: {msg[:140]}")

        # 7. members with no chain: the uncalibrated stack of before
        s3 = write_set(tmp, "S3", physical, None)
        capture, real_logger = _Capture(), virtual.logger
        virtual.logger = capture
        try:
            p3, _, cal3 = build(s3, tmp, "STK_S3")
        finally:
            virtual.logger = real_logger
        warnings = capture.warnings
        r3, ch3 = read_back(p3, "STK_S3"), stack_channels(p3, "STK_S3")
        for comp in virtual.COILS:
            check(ch3[comp]["units"] == "digital counts" and ch3[comp]["filters"] == [],
                  f"7. S3 {comp}: digital counts, no filters")
            check(r3[comp].tobytes() == frozen_mean(s3, comp).tobytes(), f"7. S3 {comp}: bytes of the frozen mean")
        check(r3["station_comment"].endswith("uncalibrated: the members carry no filter chain (the remote-reference "
                                             "estimate is invariant to the remote's calibration, its errors are not: "
                                             "upstream issue 111)"),
              "7. S3 station comment: the no-chain wording")
        check("calibration:" not in r3["run_comment"] and cal3 == {"hx": None, "hy": None},
              "7. S3: no calibration line, calibration_out {hx: None, hy: None}")
        n_warn = sum("no member carries a filter chain" in w for w in warnings)
        check(n_warn == 2, f"7. S3: one WARNING per coil ({n_warn})")

        # 8. a chain beside no chain is refused
        s4 = write_set(tmp, "S4", physical, {m: G0 for m in MEMBERS}, no_chain=("A3",))
        msg = raises(lambda: build(s4, tmp, "STK_S4"))
        check(all(s in msg for s in ("hx", "A3", "no filter chain")), f"8. a member without a chain is refused: {msg[:120]}")

        # 9. the tolerance's two sides
        s5 = write_set(tmp, "S5", physical, {m: G0 for m in MEMBERS},
                       tables={"A2": coil_table("x", shape=lambda f: 1.0 + 4e-6 * np.log10(f * 1e4) / 7.0)})
        s6 = write_set(tmp, "S6", physical, {m: G0 for m in MEMBERS},
                       tables={"A2": coil_table("x", shape=lambda f: 1.0 + 1e-6 * np.log10(f * 1e4) / 7.0)})
        msg5 = raises(lambda: build(s5, tmp, "STK_S5"))
        msg6 = raises(lambda: build(s6, tmp, "STK_S6"))
        check("differ in frequency response" in msg5, f"9. a ratio departing 2e-6 from its mean is refused: {msg5[:100]}")
        check(msg6 == "", "9. a ratio departing 5e-7 from its mean is within the tolerance (built)")

        # 10. _Coil's scale
        m = MTH5()
        m.open_mth5(s0 / "mth5" / "A1.h5", mode="r")
        try:
            ds = m.get_channel("A1", "sr1000_0001", "hx", SURVEY).hdf5_dataset
            plain, twice = virtual._Coil(ds, 10, 1000), virtual._Coil(ds, 10, 1000, scale=2.0)
            a, b, raw = plain[5:105], twice[5:105], ds[15:115]
            check(a.dtype == raw.dtype and a.tobytes() == raw.tobytes(), "10. scale 1 returns the stored slice")
            check(b.dtype == np.float64 and np.array_equal(b, 2.0 * raw.astype("float64")),
                  "10. scale 2 returns float64 twice the stored slice")
        finally:
            m.close_mth5()

    print(f"\n{len(failures)} failure(s)")
    for f in failures:
        print("  " + f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
