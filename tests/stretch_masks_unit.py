# -*- coding: utf-8 -*-
"""
Unit test for scripts/stretch_masks.py

A synthetic 1 Hz record of three days: H white noise around a mean field at
20 deg; Ex equal to the rotated Hy' (the health module's partner of Ex) plus a
little noise inside a known good stretch and pure noise a hundred times larger
outside it; Ey pure noise throughout. No archive and no aurora.

Usage:
    python tests/stretch_masks_unit.py

**This test fails if**

1. the hourly series `line_series` gives does not reproduce the health
   module's week fractions (`mt_workbench.health.health_record`'s ``ex``
   and ``ey``: the fraction of finite windows above 0.5) to 1e-12, i.e. the
   tool does not use the same function, band and pairing;
2. with the good stretch at [10.5 h, 30.5 h): the 1-h grain does not keep
   exactly [11 h, 30 h) and write exactly the two complement masks
   [record start, 11 h) and [30 h, record end) on channels [ex], bands
   [0, 1000], scope local, found_by "stretch", reason naming the threshold,
   the grain and the hours kept (19.0 h); the 30-min grain does not keep
   exactly [10.5 h, 30.5 h); the yx line (noise) does not give one mask
   over the whole record on [ey];
3. with the good stretch at [10.25 h, 30.25 h) (on neither grid): an edge
   of the 1-h run lies 3600 s or more from the truth, an edge of the 30-min
   run 1800 s or more from it, or a kept run reaches outside the truth;
4. `--band-max 300` does not write bands [0, 300];
5. the random control does not keep exactly the selection's number of
   slots, or the two halves are not disjoint with their union the
   selection, alternate runs to A and B;
6. the candidate writer accepts the survey's masks.yaml as its output;
7. the mutation (the keep rule replaced by "below the threshold") passes
   check 2: the check must fail under it;
8. `mt_workbench.masks.normalise` refuses found_by "stretch".

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from mt_workbench import health as HL  # noqa: E402
from mt_workbench.masks import normalise  # noqa: E402

spec = importlib.util.spec_from_file_location("stretch_masks", REPO / "scripts" / "stretch_masks.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

T0 = pd.Timestamp("2015-01-01T00:00:00Z")
N = 3 * 86400
H = 3600.0


def record(good_h0: float, good_h1: float, seed: int = 1):
    """Return hx, hy, ex, ey at 1 Hz with Ex coherent with Hy' inside [good_h0, good_h1) h only."""
    rng = np.random.default_rng(seed)
    ang = 20.0
    hx = 20000.0 * np.cos(np.radians(ang)) + rng.standard_normal(N)
    hy = 20000.0 * np.sin(np.radians(ang)) + rng.standard_normal(N)
    _, ry = HL.rotate_h(hx, hy, HL.mean_field_angle(hx, hy))
    ex = 100.0 * rng.standard_normal(N)
    a, b = int(good_h0 * H), int(good_h1 * H)
    ex[a:b] = (ry[a:b] - ry[a:b].mean()) + 0.05 * rng.standard_normal(b - a)
    ey = 100.0 * rng.standard_normal(N)
    return hx, hy, ex, ey


def ts(hours: float) -> str:
    return (T0 + pd.Timedelta(seconds=hours * H)).isoformat().replace("+00:00", "Z")


def check_selection(hx, hy, ex, ey) -> None:
    """Check 2 (the exact complement); raises AssertionError on any departure."""
    ser = sm.line_series(hx, hy, ex, ey, fs=1.0)
    end = T0 + pd.Timedelta(seconds=N)
    sel = sm.select(ser, "xy", threshold=0.5, grain=3600)
    assert sel["runs"] == [(11 * H, 30 * H)], sel["runs"]
    masks = sm.stretch_masks(sel, T0, T0, end, "xy", band=(0.0, 1000.0))
    want = [(ts(0), ts(11)), (ts(30), ts(72))]
    got = [(m["start"], m["end"]) for m in masks]
    assert got == want, got
    for m in masks:
        n = normalise(m)
        assert n["channels"] == ["ex"] and n["bands"] == [0.0, 1000.0] and n["scope"] == "local", n
        assert n["found_by"] == "stretch", n
        assert "0.5" in n["reason"] and "60-min" in n["reason"] and "19.0 h" in n["reason"], n["reason"]
    sel30 = sm.select(ser, "xy", threshold=0.5, grain=1800)
    assert sel30["runs"] == [(10.5 * H, 30.5 * H)], sel30["runs"]
    sely = sm.select(ser, "yx", threshold=0.5, grain=3600)
    my = sm.stretch_masks(sely, T0, T0, end, "yx", band=(0.0, 1000.0))
    assert [(m["start"], m["end"]) for m in my] == [(ts(0), ts(72))] and my[0]["channels"] == ["ey"], my


def main() -> int:
    hx, hy, ex, ey = record(10.5, 30.5)

    # 1. the health module's week fractions
    ser = sm.line_series(hx, hy, ex, ey, fs=1.0)
    r = HL.health_record(0.0, 1.0, hx, hy, np.full(N, 40000.0), ex, ey)
    assert len(r["weeks"]) == 1, r["weeks"]
    w = r["weeks"][0]
    for mode, key in (("xy", "ex"), ("yx", "ey")):
        v = ser[mode][ser["finite"]]
        frac = float(np.mean(v > HL.E_COH))
        assert abs(frac - w[key]) < 1e-12, (mode, frac, w[key])
    print(f"1. series reproduce health_record's week fractions: ex {w['ex']:.4f}, ey {w['ey']:.4f}")

    # 2. the exact complement
    check_selection(hx, hy, ex, ey)
    print("2. 1-h grain keeps [11 h, 30 h): masks [0, 11 h) and [30 h, 72 h) on [ex], bands [0, 1000], "
          "scope local, found_by stretch; 30-min grain keeps [10.5 h, 30.5 h); yx one whole-record mask on [ey]")

    # 3. off-grid stretch: the 30-min grain halves the edge bound
    hx2, hy2, ex2, ey2 = record(10.25, 30.25, seed=2)
    ser2 = sm.line_series(hx2, hy2, ex2, ey2, fs=1.0)
    truth = (10.25 * H, 30.25 * H)
    for grain in (3600, 1800):
        runs = sm.select(ser2, "xy", threshold=0.5, grain=grain)["runs"]
        assert len(runs) == 1, (grain, runs)
        a, b = runs[0]
        assert truth[0] <= a and b <= truth[1], (grain, runs)
        assert a - truth[0] < grain and truth[1] - b < grain, (grain, runs, truth)
        print(f"3. grain {grain} s: run [{a / H:g} h, {b / H:g} h) inside the truth [10.25 h, 30.25 h), "
              f"edges {(a - truth[0]) / 60:g} and {(truth[1] - b) / 60:g} min (< {grain / 60:g} min)")

    # 4. the band limit
    sel = sm.select(ser, "xy", threshold=0.5, grain=3600)
    m300 = sm.stretch_masks(sel, T0, T0, T0 + pd.Timedelta(seconds=N), "xy", band=(0.0, 300.0))
    assert all(normalise(m)["bands"] == [0.0, 300.0] for m in m300), m300
    print("4. --band-max 300 writes bands [0, 300]")

    # 5. controls
    two = sm.select(ser, "xy", threshold=0.5, grain=3600)
    two["keep"] = two["keep"].copy()
    two["keep"][50:55] = True                      # a second run (hours 50-54) for the halves
    two["runs"] = sm.slot_runs(two["keep"], two["grain"])
    for seed in (1, 2, 3):
        rnd = sm.random_control(two, seed)
        assert int(rnd["keep"].sum()) == int(two["keep"].sum()), (seed, rnd["keep"].sum(), two["keep"].sum())
        assert not (rnd["keep"] & ~two["data"]).any(), seed
    ha, hb = sm.half_control(two, "A"), sm.half_control(two, "B")
    assert not (ha["keep"] & hb["keep"]).any() and ((ha["keep"] | hb["keep"]) == two["keep"]).all()
    assert ha["runs"] == [two["runs"][0]] and hb["runs"] == [two["runs"][1]], (ha["runs"], hb["runs"])
    print(f"5. random control keeps {int(two['keep'].sum())} slots in each of 3 draws, inside the data; "
          "halves A, B disjoint, alternate runs, union = the selection")

    # 6. the candidate writer refuses masks.yaml of record
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        try:
            sm.write_candidate(Path(tmp) / "masks.yaml", survey_yaml, "X", m300)
        except SystemExit:
            pass
        else:
            raise AssertionError("the candidate writer wrote the survey's masks.yaml")
        out = sm.write_candidate(Path(tmp) / "cand" / "X_stretch.yaml", survey_yaml, "X", m300)
        assert out.exists() and not (Path(tmp) / "masks.yaml").exists()
    print("6. write_candidate refuses <survey>/masks.yaml and writes a candidate file")

    # 7. mutation: keep BELOW the threshold must fail check 2
    original = sm.passes
    sm.passes = lambda v, thr: np.isfinite(v) & (v < thr)
    try:
        check_selection(hx, hy, ex, ey)
    except AssertionError:
        print("7. mutation (keep below the threshold) FAILS check 2, as it must")
    else:
        raise AssertionError("the mutation passed check 2: the check cannot fail")
    finally:
        sm.passes = original

    # 8. found_by stretch
    normalise({"start": ts(0), "end": ts(1), "found_by": "stretch", "channels": ["ex"], "bands": [0, 1000]})
    print("8. normalise accepts found_by stretch")
    print("stretch_masks_unit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
