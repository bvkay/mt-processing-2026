# -*- coding: utf-8 -*-
"""
Unit test for a stack member with no filter chain whose samples are calibrated (mt_workbench.virtual)

The observatory archives (ASP, CNB, GNG, CTA) hold hx and hy in nanoTesla
with no filter chain, and the derived 1 Hz L sites hold microVolt with the EDL
chain (a coefficient nanoTesla -> microVolt). A member with no chain whose
samples are in the unit the others' chains calibrate to (the first applied
filter's units_in, nanoTesla for H) is taken as an identity chain: its total
response is 1, its ratio to the reference chain is 1 / R_ref, and when that
is a real constant (a coefficient chain) the member is scaled by R_ref onto
the reference's scale, as a member of another gain is. The calibration line
of the run comment and `calibration_out` say so ("member M2: no filter chain,
samples in nanoTesla taken as calibrated"). A chain-less member in another
unit, a reference chain that varies with frequency, and two chains that
differ in shape are still refused.

Members: 1000 Hz, the four 10-minute chunks plus tail of
tests/stack_calibration_unit.py; b_i = one common field (1 nT rms per coil)
plus own noise (0.2 nT) plus a DC offset (50, 100 nT). M1 stores G b1 in
microVolt with the chain [coefficient G = 400000, nanoTesla -> microVolt];
M2 stores b2 in nanoTesla with no chain.

Usage:
    python tests/stack_identity_member_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. the plain-mean stack of [M1, M2] is refused, or the scales returned in
   `calibration_out` are not {M1: 1, M2: G} to 1e-9 relative, its reference
   is not M1, or it does not name M2 as an identity member in nanoTesla;
2. the stack in physical units (the float64 stack of `stack_arrays` on the
   members as `_open_members` opens them, divided by G) differs from the
   hand-made mean (b1 + b2) / 2 by more than 1e-9 of its rms on either coil;
3. the archived float32 stack differs from float32((M1 + G M2) / 2) (the
   stored samples, float64 sum in member order over the count) by more than
   1e-9 of its rms on either coil;
4. the run comment does not carry "member M2: no filter chain, samples in
   nanoTesla taken as calibrated", or the archive's hx is not written in
   microVolt with M1's coefficient filter applied;
5. the members listed as [M2, M1] give other scales or another reference
   (the reference is the first member WITH a chain);
6. any of these is not refused with a ValueError naming the coil, the member
   and "no filter chain" (a) or "differ in frequency response" (c): (a) M2's
   samples in microVolt with no chain (the unit is not the one M1's chain
   calibrates to), (b) M2 with no units at all, (c) M1's chain carrying a
   coil response table before its coefficient (a chain that varies with
   frequency cannot take an identity member: one chain for the stack could
   not describe it), (d) two chained members whose tables differ in shape
   (today's rule).
"""

from __future__ import annotations

import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import pandas as pd
from mt_metadata.timeseries import Magnetic
from mt_metadata.timeseries.filters import CoefficientFilter
from mth5.mth5 import MTH5

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mt_workbench.virtual as virtual  # noqa: E402
import stack_calibration_unit as scu  # noqa: E402  (the member layout, tables and constants)
from virtual_unit import SURVEY, T0, fake_survey  # noqa: E402

G = 400000.0
OFF = {"M1": 50.0, "M2": 100.0}
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def physical(seed: int = 11) -> dict:
    """Return {member: {coil: b in nT, float64}}."""
    rng = np.random.default_rng(seed)
    field = {c: rng.normal(0.0, 1.0, scu.N) for c in virtual.COILS}
    return {m: {c: field[c] + rng.normal(0.0, 0.2, scu.N) + OFF[m] for c in virtual.COILS} for m in OFF}


def write(ws: Path, site: str, coils: dict, chain: dict | None, units: str | None) -> None:
    """Write one member: float64 samples, `chain` ({coil: [filters]}) in the Filters group, channel `units`."""
    path = ws / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    end = T0 + pd.Timedelta(seconds=(scu.N - 1) / scu.FS)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        survey_group = m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        run = station.add_run("sr1000_0001")
        for comp, data in coils.items():
            md = Magnetic()
            md.component = comp
            md.sample_rate = scu.FS
            md.time_period.start = T0.isoformat()
            md.time_period.end = end.isoformat()
            md.measurement_azimuth = 0.0 if comp == "hx" else 90.0
            if units is not None:
                md.units = units
            for stage, f in enumerate((chain or {}).get(comp, []), 1):
                survey_group.filters_group.add_filter(f)
                md.add_filter(name=f.name, applied=True, stage=stage)
            run.add_channel(comp, "magnetic", np.asarray(data, dtype="float64"), channel_metadata=md)
        run.metadata.sample_rate = scu.FS
        run.metadata.time_period.start = T0.isoformat()
        run.metadata.time_period.end = end.isoformat()
        run.write_metadata()
        station.metadata.time_period.start = T0.isoformat()
        station.metadata.time_period.end = end.isoformat()
        station.write_metadata()
    finally:
        m.close_mth5()


def coef_chain(gain: float = G) -> dict:
    """{coil: [coefficient nanoTesla -> microVolt]} (the EDL L site's chain)."""
    return {c: [CoefficientFilter(name=f"edl_h_{c}", gain=float(gain), units_in="nanoTesla", units_out="microVolt")]
            for c in virtual.COILS}


def table_chain(corner_hz: float = 1.0) -> dict:
    """{coil: [coil response table, coefficient]}, nanoTesla -> microVolt (a chain varying with frequency)."""
    return scu.chain_for("M", G, scu.coil_table("t", corner_hz))


def build(ws: Path, members, name: str, cal: dict | None = None) -> Path:
    """Plain-mean stack of `members` in `ws`."""
    return virtual.build_synthetic_remote(fake_survey(ws), members, "2023-09-19", "2023-09-20", name=name,
                                          out_path=ws / f"{name}.h5", calibration_out=cal)


def read_stack(path: Path, name: str) -> tuple[dict, str, dict]:
    """Return ({coil: float32 samples}, run comment, {coil: (units, [filter names])})."""
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(name, survey=SURVEY).get_run("sr1000_0001")
        data, meta = {}, {}
        for c in virtual.COILS:
            ch = run.get_channel(c)
            data[c] = ch.hdf5_dataset[:]
            meta[c] = (str(ch.metadata.units), [f.name for f in (ch.metadata.filters or [])])
        comment = str(getattr(run.metadata.comments, "value", run.metadata.comments) or "")
    finally:
        m.close_mth5()
    return data, comment, meta


def rel(a, b) -> float:
    """max |a - b| over the rms of b."""
    a, b = np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")
    return float(np.max(np.abs(a - b)) / np.sqrt(np.mean(b ** 2)))


def refusal(fn) -> str:
    """Return the ValueError text `fn()` raises, "" when it raises none."""
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return ""


def main() -> None:
    b = physical()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ws = tmp / "ok"
        write(ws, "M1", {c: G * b["M1"][c] for c in virtual.COILS}, coef_chain(), "microVolt")
        write(ws, "M2", b["M2"], None, "nanoTesla")

        # 1
        cal: dict = {}
        msg = refusal(lambda: build(ws, ["M1", "M2"], "STK", cal))
        check(msg == "", f"1. [M1, M2] builds ({msg[:160] or 'no refusal'})")
        if msg:
            print("FAIL (the rest needs the stack)")
            sys.exit(1)
        for c in virtual.COILS:
            p = cal.get(c) or {}
            sc = p.get("scales", {})
            check(p.get("reference") == "M1" and abs(sc.get("M1", np.nan) - 1.0) <= 1e-9
                  and abs(sc.get("M2", np.nan) / G - 1.0) <= 1e-9,
                  f"1. {c}: reference {p.get('reference')}, scales {sc}")
            check(p.get("identity") == {"M2": "nanoTesla"}, f"1. {c}: identity members {p.get('identity')}")

        # 2: float64, in physical units
        survey = fake_survey(ws)
        with ExitStack() as st:
            _, coils, span, _ = virtual._open_members(survey, virtual._per_comp(["M1", "M2"]), "2023-09-19",
                                                      "2023-09-20", "STK", st)
            for c in virtual.COILS:
                total, _ = virtual.stack_arrays(coils[c], span.fs, "none")
                hand = (b["M1"][c] + b["M2"][c]) / 2.0
                d = rel(total / G, hand)
                check(d <= 1e-9, f"2. {c}: float64 stack / G vs hand mean of the calibrated samples: {d:.2e}")

        # 3, 4: the archive
        data, comment, meta = read_stack(ws / "STK.h5", "STK")
        for c in virtual.COILS:
            frozen = ((G * b["M1"][c]).astype("float64") + b["M2"][c].astype("float64") * G) / 2.0
            d = rel(data[c], frozen.astype("float32"))
            check(d <= 1e-9, f"3. {c}: archived float32 vs float32((M1 + G M2) / 2): {d:.2e}")
        want = "member M2: no filter chain, samples in nanoTesla taken as calibrated"
        check(want in comment, f"4. run comment carries {want!r}: {comment[-220:]!r}")
        check(meta["hx"] == ("microVolt", ["edl_h_hx"]), f"4. hx written as {meta['hx']}")

        # 5: chain-less member listed first
        cal2: dict = {}
        build(ws, ["M2", "M1"], "STK2", cal2)
        check(all((cal2[c] or {}).get("reference") == "M1" and cal2[c]["scales"] == cal[c]["scales"]
                  for c in virtual.COILS), f"5. [M2, M1]: {[(cal2[c] or {}).get('reference') for c in virtual.COILS]}"
                                           f", scales {[cal2[c]['scales'] for c in virtual.COILS]}")

        # 6: refusals
        cases = {}
        ws_a = tmp / "a"
        write(ws_a, "M1", {c: G * b["M1"][c] for c in virtual.COILS}, coef_chain(), "microVolt")
        write(ws_a, "M2", {c: G * b["M2"][c] for c in virtual.COILS}, None, "microVolt")
        cases["a: M2 in microVolt, no chain"] = (ws_a, ["M1", "M2"], "no filter chain")
        ws_b = tmp / "b"
        write(ws_b, "M1", {c: G * b["M1"][c] for c in virtual.COILS}, coef_chain(), "microVolt")
        write(ws_b, "M2", b["M2"], None, None)
        cases["b: M2 with no units"] = (ws_b, ["M1", "M2"], "no filter chain")
        ws_c = tmp / "c"
        write(ws_c, "M1", {c: G * b["M1"][c] for c in virtual.COILS}, table_chain(), "microVolt")
        write(ws_c, "M2", b["M2"], None, "nanoTesla")
        cases["c: M1's chain varies with frequency"] = (ws_c, ["M1", "M2"], "no filter chain")
        ws_d = tmp / "d"
        write(ws_d, "M1", {c: G * b["M1"][c] for c in virtual.COILS}, table_chain(1.0), "microVolt")
        write(ws_d, "M2", {c: G * b["M2"][c] for c in virtual.COILS}, table_chain(3.0), "microVolt")
        cases["d: two chains of another shape"] = (ws_d, ["M1", "M2"], "differ in frequency response")
        for what, (w, members, phrase) in cases.items():
            msg = refusal(lambda: build(w, members, "STKX"))
            check(bool(msg) and "hx" in msg and "M2" in msg and phrase in msg,
                  f"6. {what}: refused: {msg[:200] or 'not refused'}")
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
