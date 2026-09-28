# -*- coding: utf-8 -*-
"""
Unit test for scripts/merge_best.py

Synthetic products of station S01 are written with mt_metadata's `TF` as
EDIs, each with a sidecar in the shape of process_rr.py's. A (remote R01,
with a tipper), B (remote R02) and C (remote R03) are 1D half-spaces of 100,
400 and 25 ohm-m with diagonal terms of their own, so every component names
its source. A and B hold 41 periods from 0.01 to 1000 s, eight per decade;
C's grid is offset by a sixteenth of a decade in the merge tests. For --auto
the relative rho errors are set per band: A 0.10 throughout; B 0.05 below
1 s and 0.20 above, with its yx phase flipped out of quadrant in the band
0.1-0.178 s; C 0.30 below 3.16 s, 0.09 in 3.16-5.62 s, 0.08 in 5.62-10 s,
0.02 above, and its rho ten times higher (1 dex) in the band 31.6-56.2 s.
A_hole is A with its x row EMPTY at 3.16 s; its y row still puts 3.16 s on
the grid. The merges run through the script's `main` with a recipe file whose EDI
paths are relative to it, and through `merge_files`.

Usage:
    python tests/merge_best_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if a merged row does not come from the source and range the recipe names for it.

**This test fails if** (1) with xy from A over 0.01-1 s and B over 3-100 s
and yx from A throughout, `main` does not return 0, the merged periods are
not A's 41, the x row (Zxx, Zxy) or its errors differ by more than 1e-5
relative from A's at A's periods up to 1 s or from B's at B's periods in
3-100 s, the ZXXR and ZXYR blocks of the file do not hold the EMPTY value
1e+32 at the three periods between 1 and 3 s and the eight above 100 s, the
y row differs from A's anywhere, the merged EDI has a tipper, or the
sidecar's xy gaps are not 1.33-2.37 s and 133-1000 s; (2) with A over
0.01-1 s listed before B over 1-1000 s, the x row at 1 s is not A's, or with
B listed first it is not B's; (3) with yx from A over 0.01-0.1 s, B over
0.13-10 s and C over 13-1000 s, the y row is not A's at A's 9 periods, B's
at its 16, C's at C's own 15 periods, on the straight line in log10 period
between C's neighbouring periods at the 14 of A's periods inside C's
periods, or EMPTY at 13.3 and 1000 s (in C's range, outside its periods),
or the sidecar's counts per yx source are not 9, 16 and 15 copied and 14
interpolated; (4) with yx from A over 0.01-1 s only and a tipper list, the
y row above 1 s is not EMPTY, the sidecar's yx gap is not 1.33-1000 s, or
the tipper and its errors are not A's; (5) `main` does not return 2 naming
S01 and S02 when B's station is S02 (writing no EDI), 0 with that mismatch
under --force (recorded in the sidecar), 2 for a missing EDI, 2 for a mode
with no source listed, and 2 for a mode whose range holds no period of its
source; (6) --auto on A, B and C does not propose, per mode, B, A, C, A, C
over 0.01-0.75, 1-4.22, 5.62-23.7, 31.6-42.2 and 56.2-1000 s (the yx mode
with A over 0.1-0.133 s, where B's phase is out of quadrant), the comment of
the band 3.16-5.62 s does not say A was kept with runner-up C at -10 %, the
comment of the band 31.6-56.2 s does not name C's 1 dex jump, or the
proposal merged with `merge_files` does not give B's, A's and C's x rows at
0.01, 1 and 10 s; (7) `merge_files` does not return 0, its sidecar lacks
local, remote, created (UTC, ending in Z), tag, edi, site, recipe, merge,
sources, forced, mismatches, argv or versions, does not survive json.dumps
and json.loads unchanged, or its sources do not carry their sidecars' tags,
remotes and masks, or the EDI's INFO block lacks the crust.best_xy lines;
(8) with xy from A_hole then B over 0.01-1000 s, the x row at 3.16 s is not
B's, the x row at A_hole's other 40 periods is not A's, or the sidecar's xy
counts are not 40 copied from A_hole and 1 from B, none interpolated; with
xy from A_hole alone, the file does not hold EMPTY in ZXXR and ZXYR at
3.16 s, or the sidecar's xy gaps are not 3.16-3.16 s with n_nan 1; with xy
from A_hole then C over 0.01-1000 s, C's two periods either side of 3.16 s
are not C's own values, or the x row at 3.16 s is not on the straight line
in log10 period between them.

The mutations: with the script's PREFER set to 0 the band 3.16-5.62 s goes
to C and with JUMP_DEX set to 10 the band 31.6-56.2 s goes to C, so the
criteria of (6) on the 20 % preference and the continuity guard are shown
able to fail.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

SCRIPT = REPO / "scripts" / "merge_best.py"
SCRATCH = scratch_dir("merge_best_unit")
RTOL = 1e-5
EMPTY = 1.0e32

P8 = 10.0 ** (-2 + np.arange(41) / 8)  # 0.01 .. 1000 s, eight per decade
P_OFFSET = P8 * 10 ** (1 / 16)

# per product: resistivity, Zxx and Zyy as fractions of Zxy, location, remote, tag
PRODUCTS = {
    "A": dict(rho=100.0, dxx=0.10 * np.exp(0.3j), dyy=0.05 * np.exp(-0.2j), lat=-30.25, lon=139.22,
              remote="R01", tag="full", masks=["S01 cluster 3"]),
    "B": dict(rho=400.0, dxx=0.20 * np.exp(0.9j), dyy=-0.15 * np.exp(-0.4j), lat=-31.50, lon=140.10,
              remote="R02", tag="redo", masks=[]),
    "C": dict(rho=25.0, dxx=0.30 * np.exp(-0.5j), dyy=0.25 * np.exp(0.6j), lat=-32.00, lon=141.00,
              remote="R03", tag="night", masks=["S01 storm"]),
}
TIPPER = np.array([0.12 + 0.05j, -0.08 + 0.03j])
TIPPER_ERR = np.array([0.011, 0.023])
SIDECAR_KEYS = {"local", "remote", "created", "tag", "edi", "site", "recipe", "merge", "sources", "forced",
                "mismatches", "argv", "versions"}


def auto_errors(name: str, periods: np.ndarray) -> np.ndarray:
    """Return the relative rho error per period of a product for the --auto test."""
    if name == "A":
        return np.full(periods.size, 0.10)
    if name == "B":
        return np.where(periods < 1.0, 0.05, 0.20)
    rel = np.full(periods.size, 0.02)
    rel[periods < 10.0] = 0.08
    rel[periods < 10 ** 0.75] = 0.09
    rel[periods < 10 ** 0.5] = 0.30
    return rel


def load_script():
    """Import scripts/merge_best.py as a module."""
    spec = importlib.util.spec_from_file_location("merge_best", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_product(name: str, periods: np.ndarray, station: str = "S01", tipper: bool = False,
                  auto: bool = False, hole: float | None = None) -> Path:
    """Write one product's EDI and sidecar under SCRATCH; return the EDI path.

    With `auto` the errors follow `auto_errors`, B's yx phase is flipped in
    0.1-0.178 s and C's rho is ten times higher in 31.6-56.2 s. With `hole`
    the x row and its errors are NaN at that period, written as EMPTY.
    """
    spec = PRODUCTS[name[0]]
    zh = np.sqrt(spec["rho"] / (0.2 * periods)) * np.exp(0.25j * np.pi)
    if auto and name[0] == "C":
        zh = np.where((periods >= 10 ** 1.5) & (periods < 10 ** 1.75), zh * np.sqrt(10.0), zh)
    z = np.empty((periods.size, 2, 2), dtype=complex)
    z[:, 0, 0], z[:, 0, 1] = spec["dxx"] * zh, zh
    z[:, 1, 0], z[:, 1, 1] = -zh, spec["dyy"] * zh
    if auto and name[0] == "B":
        flip = (periods >= 0.1) & (periods < 10 ** -0.75)
        z[flip, 1, :] *= -1
    rel = auto_errors(name[0], periods) if auto else np.full(periods.size, 0.1)
    err = (0.5 * rel * np.abs(zh))[:, None, None] * np.ones((1, 2, 2))
    if hole is not None:
        k = at(periods, hole)
        z[k, 0, :], err[k, 0, :] = np.nan, np.nan
    tf = TF()
    tf.station_metadata.id = station
    tf.survey_metadata.id = "merge_best_unit"
    tf.station_metadata.location.latitude = spec["lat"]
    tf.station_metadata.location.longitude = spec["lon"]
    tf.period = periods
    tf.impedance = z
    tf.impedance_error = err
    if tipper:
        tf.tipper = np.tile(TIPPER, (periods.size, 1))[:, None, :]
        tf.tipper_error = np.tile(TIPPER_ERR, (periods.size, 1))[:, None, :]
    edi = SCRATCH / f"{name}.edi"
    tf.write(fn=str(edi), file_type="edi")
    side = dict(local=station, remote=spec["remote"], tag=spec["tag"], window={"start": None, "end": None},
                masks=spec["masks"], edi=edi.name)
    edi.with_suffix(".json").write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
    return edi


def read(path: Path) -> TF:
    """Read an EDI with mt_metadata."""
    tf = TF(fn=str(path))
    tf.read()
    return tf


def arrays(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return an EDI's periods, impedance and impedance errors as arrays."""
    tf = read(path)
    return (np.asarray(tf.period, dtype=float), np.asarray(tf.impedance.data),
            np.asarray(tf.impedance_error.data, dtype=float))


def close(got, want) -> bool:
    """True when every value is within RTOL of the wanted one, relative to the wanted value's size."""
    got, want = np.asarray(got), np.asarray(want)
    return bool(np.all(np.abs(got - want) <= RTOL * np.abs(want)))


def at(periods: np.ndarray, period: float) -> int:
    """Return the index of `period` in `periods`, matched within 1e-6 in log10 period."""
    gap = np.abs(np.log10(periods) - np.log10(period))
    assert gap.min() < 1e-6, (period, periods)
    return int(gap.argmin())


def edi_block(path: Path, key: str) -> np.ndarray:
    """Return the numbers of one data block of an EDI file, e.g. "ZXYR"."""
    text = path.read_text(encoding="utf-8")
    body = re.search(rf"^>{key} [^\n]*\n(.*?)(?=^>)", text, flags=re.S | re.M).group(1)
    return np.array([float(v) for v in body.split()])


def row_matches(merged: Path, source: Path, row: int, periods) -> list[str]:
    """Compare one row of the merged EDI with a source's at the given periods; return the failures."""
    p_m, z_m, e_m = arrays(merged)
    p_s, z_s, e_s = arrays(source)
    fails = []
    for p in periods:
        i, k = at(p_m, p), at(p_s, p)
        if not (close(z_m[i, row], z_s[k, row]) and close(e_m[i, row], e_s[k, row])):
            fails.append(f"{p:.4g} s: {z_m[i, row]} is not {source.name}'s {z_s[k, row]}")
    return fails


def empty_in_file(merged: Path, keys: tuple[str, ...], periods) -> list[str]:
    """Check that the file holds EMPTY in the given blocks at the given periods; return the failures."""
    freq = edi_block(merged, "FREQ")
    blocks = {key: edi_block(merged, key) for key in keys}
    fails = []
    for p in periods:
        k = at(1.0 / freq, p)
        stored = [float(blocks[key][k]) for key in keys]
        if stored != [EMPTY] * len(keys):
            fails.append(f"{p:.4g} s: {dict(zip(keys, stored))}")
    return fails


def run(module, *argv: str) -> tuple[int, str, str]:
    """Run the script's main with captured output; return (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = module.main(list(argv))
    return status, out.getvalue(), err.getvalue()


def quiet(func, *args, **kwargs):
    """Call a function with its printed output captured; return (result, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = func(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


def sidecar(edi: Path) -> dict:
    """Read the sidecar beside an EDI."""
    return json.loads(edi.with_suffix(".json").read_text(encoding="utf-8"))


def entry(edi: str, pmin: float, pmax: float) -> dict:
    """One recipe entry."""
    return {"edi": edi, "pmin": pmin, "pmax": pmax}


def test_merges(module, a: Path, b: Path, c: Path) -> None:
    """Tests (1) to (4) through `main` and a recipe file with paths relative to it."""
    recipes = {
        "S01": {"xy": [entry("A.edi", 0.01, 1.0), entry("B.edi", 3.0, 100.0)], "yx": [entry("A.edi", 0.01, 1000)],
                "note": "two xy sources over disjoint ranges"},
        "S01-overlap": {"xy": [entry("A.edi", 0.01, 1.0), entry("B.edi", 1.0, 1000.0)],
                        "yx": [entry("A.edi", 0.01, 1000)]},
        "S01-overlap-b": {"xy": [entry("B.edi", 1.0, 1000.0), entry("A.edi", 0.01, 1.0)],
                          "yx": [entry("A.edi", 0.01, 1000)]},
        "S01-three": {"xy": [entry("A.edi", 0.01, 1000)],
                      "yx": [entry("A.edi", 0.01, 0.1), entry("B.edi", 0.13, 10.0), entry("C.edi", 13.0, 1000.0)]},
        "S01-gap": {"xy": [entry("A.edi", 0.01, 1000)], "yx": [entry("A.edi", 0.01, 1.0)],
                    "tipper": [entry("A.edi", 0.01, 1000)]},
    }
    recipe = SCRATCH / "recipes.yaml"
    recipe.write_text(yaml.safe_dump(recipes, sort_keys=False), encoding="utf-8")
    out = SCRATCH / "out"

    # (1) disjoint xy ranges
    m1 = out / "S01_best.edi"
    status, text, err = run(module, str(m1), "--recipe", str(recipe), "--site", "S01", "--tag", "best")
    assert status == 0, f"exit {status}\n{text}\n{err}"
    print("\n".join(f"  | {line}" for line in text.splitlines()))
    p_m = arrays(m1)[0]
    assert p_m.size == 41 and np.allclose(p_m, P8, rtol=1e-6, atol=0), p_m
    from_a, from_b = P8[P8 <= 1.0], P8[(P8 >= 3.0) & (P8 <= 100.0)]
    nowhere = P8[((P8 > 1.0) & (P8 < 3.0)) | (P8 > 100.0)]
    fails = (row_matches(m1, a, 0, from_a) + row_matches(m1, b, 0, from_b)
             + empty_in_file(m1, ("ZXXR", "ZXYR"), nowhere) + row_matches(m1, a, 1, P8))
    assert not fails, fails
    assert not read(m1).has_tipper(), "a tipper was written without a tipper list"
    gaps = sidecar(m1)["merge"]["modes"]["xy"]["gaps"]
    want = [[P8[17], P8[19]], [P8[33], P8[40]]]
    assert np.allclose(gaps, want, rtol=1e-6), gaps
    print(f"  (1) x row = A's at {from_a.size} periods, B's at {from_b.size}, EMPTY at {nowhere.size} "
          f"(xy gaps {[[round(v, 3) for v in g] for g in gaps]}); y row = A's at 41; no tipper")

    # (2) one shared period goes to the first listed source
    m2, m2b = out / "S01_overlap.edi", out / "S01_overlap_b.edi"
    assert run(module, str(m2), "--recipe", str(recipe), "--site", "S01-overlap")[0] == 0
    assert run(module, str(m2b), "--recipe", str(recipe), "--site", "S01-overlap-b")[0] == 0
    fails = (row_matches(m2, a, 0, [1.0]) + row_matches(m2, b, 0, [P8[17]]) + row_matches(m2b, b, 0, [1.0]))
    assert not fails, fails
    print("  (2) at 1 s the x row is A's with A listed first and B's with B listed first")

    # (3) the y row from three sources, C on its own grid
    m3 = out / "S01_three.edi"
    status, text, err = run(module, str(m3), "--recipe", str(recipe), "--site", "S01-three")
    assert status == 0, err
    p_m, z_m, e_m = arrays(m3)
    c_own = P_OFFSET[(P_OFFSET >= 13.0) & (P_OFFSET <= 1000.0)]
    a_in_c = P8[(P8 > c_own.min()) & (P8 < c_own.max())]
    fails = (row_matches(m3, a, 1, P8[P8 <= 0.1]) + row_matches(m3, b, 1, P8[(P8 >= 0.13) & (P8 <= 10.0)])
             + row_matches(m3, c, 1, c_own) + empty_in_file(m3, ("ZYXR", "ZYYR"), [P8[25], P8[40]]))
    p_c, z_c, e_c = arrays(c)
    x_c = np.log10(p_c)
    for p in a_in_c:
        i = at(p_m, p)
        line = [np.interp(np.log10(p), x_c, z_c[:, 1, j].real) + 1j * np.interp(np.log10(p), x_c, z_c[:, 1, j].imag)
                for j in range(2)]
        line_e = [np.interp(np.log10(p), x_c, e_c[:, 1, j]) for j in range(2)]
        if not (close(z_m[i, 1], line) and close(e_m[i, 1], line_e)):
            fails.append(f"{p:.4g} s: y row {z_m[i, 1]} is not on C's line {line}")
    assert not fails, fails
    yx = sidecar(m3)["merge"]["modes"]["yx"]["entries"]
    counts = [(len(e["copied"]), len(e["interpolated"])) for e in yx]
    assert counts == [(9, 0), (16, 0), (15, 14)], counts
    print(f"  (3) y row from A, B, C: (copied, interpolated) {counts}; {a_in_c.size} of A's periods on C's line; "
          f"EMPTY at {P8[25]:.3g} and {P8[40]:.3g} s; {p_m.size} periods")

    # (4) no yx source above 1 s; tipper from the recipe
    m4 = out / "S01_gap.edi"
    assert run(module, str(m4), "--recipe", str(recipe), "--site", "S01-gap")[0] == 0
    fails = empty_in_file(m4, ("ZYXR", "ZYYR"), P8[P8 > 1.0])
    gaps = sidecar(m4)["merge"]["modes"]["yx"]["gaps"]
    assert not fails and np.allclose(gaps, [[P8[17], P8[40]]], rtol=1e-6), (fails, gaps)
    tf_m, tf_a = read(m4), read(a)
    assert tf_m.has_tipper() and close(np.asarray(tf_m.tipper.data), np.asarray(tf_a.tipper.data)) and close(
        np.asarray(tf_m.tipper_error.data), np.asarray(tf_a.tipper_error.data)), "tipper is not A's"
    print(f"  (4) y row EMPTY at the {int((P8 > 1).sum())} periods above 1 s, sidecar yx gaps "
          f"{[[round(v, 3) for v in g] for g in gaps]}; tipper = A's")


def test_refusals(module, a: Path) -> None:
    """Test (5): the exits on a station mismatch, a missing source and an empty mode."""
    b_st = write_product("B_S02", P8, station="S02")
    recipe = {"S01": {"xy": [entry(str(a), 0.01, 1.0), entry(str(b_st), 3.0, 100.0)],
                      "yx": [entry(str(a), 0.01, 1000)]}}
    path = SCRATCH / "recipes_st.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    refused = SCRATCH / "out" / "st.edi"
    status, _text, err = run(module, str(refused), "--recipe", str(path), "--site", "S01")
    assert status == 2 and "S01" in err and "S02" in err and not refused.exists(), (status, err)
    print(f"  (5) station mismatch: exit 2, {err.strip()}")
    forced = SCRATCH / "out" / "forced.edi"
    status, _text, err = run(module, str(forced), "--recipe", str(path), "--site", "S01", "--force")
    side = sidecar(forced)
    assert status == 0 and side["forced"] and "S02" in side["mismatches"][0], (status, err, side)
    print(f"      --force: exit 0, sidecar mismatches {side['mismatches']}")
    cases = {
        "missing EDI": {"xy": [entry(str(SCRATCH / "nowhere.edi"), 0.01, 1)], "yx": [entry(str(a), 0.01, 1)]},
        "no yx source": {"xy": [entry(str(a), 0.01, 1)], "yx": []},
        "yx range outside the periods": {"xy": [entry(str(a), 0.01, 1)], "yx": [entry(str(a), 5000, 9000)]},
    }
    for label, rec in cases.items():
        status, _text, err = quiet(module.merge_files, SCRATCH / "out" / "refused.edi", rec)
        assert status == 2 and not (SCRATCH / "out" / "refused.edi").exists(), (label, status, err)
        print(f"      {label}: exit 2, {err.strip()}")


def auto_runs(proposal: Path, site: str) -> dict:
    """Return per mode the (edi name, pmin, pmax) entries of a proposal."""
    rec = yaml.safe_load(proposal.read_text(encoding="utf-8"))[site]
    return {mode: [(Path(e["edi"]).name, e["pmin"], e["pmax"]) for e in rec[mode]] for mode in ("xy", "yx")}


def runs_match(got: list, want: list) -> bool:
    """True when two lists of (name, pmin, pmax) agree, the periods within 1e-5 relative."""
    return len(got) == len(want) and all(
        g[0] == w[0] and abs(g[1] / w[1] - 1) < 1e-5 and abs(g[2] / w[2] - 1) < 1e-5 for g, w in zip(got, want))


def test_auto(module) -> None:
    """Test (6): the proposer on three candidates with known errors."""
    cands = [write_product(name, P8, auto=True) for name in ("A_auto", "B_auto", "C_auto")]
    proposal = SCRATCH / "out" / "proposal.yaml"
    status, text, err = run(module, "--auto", "--site", "S01", "--candidates", *map(str, cands),
                            "--propose", str(proposal))
    assert status == 0, err
    print("\n".join(f"  | {line}" for line in text.splitlines()))
    p = lambda k: float(P8[k])  # noqa: E731
    tail = [("A_auto.edi", p(16), p(21)), ("C_auto.edi", p(22), p(27)), ("A_auto.edi", p(28), p(29)),
            ("C_auto.edi", p(30), p(40))]
    want = {"xy": [("B_auto.edi", p(0), p(15))] + tail,
            "yx": [("B_auto.edi", p(0), p(7)), ("A_auto.edi", p(8), p(9)), ("B_auto.edi", p(10), p(15))] + tail}
    got = auto_runs(proposal, "S01")
    assert all(runs_match(got[m], want[m]) for m in want), (got, want)
    text = proposal.read_text(encoding="utf-8")
    kept = [ln for ln in text.splitlines() if ln.strip().startswith("# 3.16-5.62 s")]
    jump = [ln for ln in text.splitlines() if ln.strip().startswith("# 31.6-56.2 s")]
    assert kept and all("kept from the band below" in ln and "runner-up C_auto.edi" in ln and "(-10 %)" in ln
                        for ln in kept), kept
    assert jump and all("dropped C_auto.edi (rho jumps 1.00 dex" in ln for ln in jump), jump
    for mode in want:
        print(f"  (6) {mode}: " + ", ".join(f"{n[0]} {lo:.3g}-{hi:.3g}" for n, lo, hi in got[mode]))
    print(f"      {kept[0].strip()}")
    print(f"      {jump[0].strip()}")

    merged = SCRATCH / "out" / "S01_auto.edi"
    status, _text, err = quiet(module.merge_files, merged, yaml.safe_load(proposal.read_text())["S01"],
                               tag="auto", recipe_path=proposal)
    fails = (row_matches(merged, cands[1], 0, [0.01]) + row_matches(merged, cands[0], 0, [1.0])
             + row_matches(merged, cands[2], 0, [10.0]))
    assert status == 0 and not fails, (status, err, fails)
    print("      the proposal merged: x row B's at 0.01 s, A's at 1 s, C's at 10 s")

    for name, value, band, winner in (("PREFER", 0.0, 2, "C_auto.edi"), ("JUMP_DEX", 10.0, 6, "C_auto.edi")):
        original = getattr(module, name)
        setattr(module, name, value)
        try:
            runs = quiet(module.propose, cands)[0]["xy"]
        finally:
            setattr(module, name, original)
        owner = [r["edi"].name for r in runs if r["edi"] is not None and any(pk["band"] == band for pk in r["picks"])]
        assert owner == [winner], (name, owner)
        print(f"  mutation {name} = {value:g}: the band {10 ** (band / 4):.3g}-{10 ** ((band + 1) / 4):.3g} s "
              f"goes to {owner[0]}, so criterion (6) trips")


def test_merge_files(module, a: Path, b: Path) -> None:
    """Test (7): `merge_files` and the sidecar's round trip through json."""
    out = SCRATCH / "out" / "S01_api.edi"
    rec = {"xy": [entry(str(a), 0.01, 1.0), entry(str(b), 3.0, 100.0)], "yx": [entry(str(a), 0.01, 1000)]}
    status, _text, err = quiet(module.merge_files, out, rec, tag="api", site="S01", argv=["merge_best.py", "api"])
    assert status == 0, err
    raw = out.with_suffix(".json").read_text(encoding="utf-8")
    side = json.loads(raw)
    assert json.loads(json.dumps(side)) == side, "sidecar does not round-trip"
    assert SIDECAR_KEYS <= set(side), SIDECAR_KEYS - set(side)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", side["created"]), side["created"]
    assert side["remote"] == "R01/R02" and side["recipe"]["site"] == rec, (side["remote"], side["recipe"])
    for src, name in zip(side["sources"], ("A", "B")):
        got = {k: src["sidecar"][k] for k in ("tag", "remote", "masks")}
        assert got == {k: PRODUCTS[name][k] for k in got}, (name, got)
    info = out.read_text(encoding="utf-8")
    assert "crust.best_xy_1=A.edi,0.01,1" in info and "crust.best_xy_2=B.edi,3,100" in info, "INFO lines"
    print(f"  (7) merge_files exit 0; sidecar {len(raw)} bytes round-trips; remote {side['remote']}; "
          f"sources {[(Path(s['edi']).name, s['sidecar']['tag']) for s in side['sources']]}")


def test_empty_period(module, b: Path, c: Path) -> None:
    """Test (8): a source's EMPTY period inside its range passes to the next source."""
    hole = float(P8[20])
    a_hole = write_product("A_hole", P8, hole=hole)
    p_h, z_h, _e_h = arrays(a_hole)
    k = at(p_h, hole)
    assert not np.all(np.isfinite(z_h[k, 0]) & (z_h[k, 0] != 0)), f"A_hole's x row at {hole:.4g} s reads {z_h[k, 0]}"
    others = np.delete(P8, 20)

    m1 = SCRATCH / "out" / "S01_hole_b.edi"
    rec = {"xy": [entry(str(a_hole), 0.01, 1000), entry(str(b), 0.01, 1000)], "yx": [entry(str(a_hole), 0.01, 1000)]}
    status, _text, err = quiet(module.merge_files, m1, rec)
    assert status == 0, err
    fails = row_matches(m1, b, 0, [hole]) + row_matches(m1, a_hole, 0, others)
    xy = sidecar(m1)["merge"]["modes"]["xy"]["entries"]
    counts = [(len(e["copied"]), len(e["interpolated"])) for e in xy]
    assert not fails and counts == [(40, 0), (1, 0)], (fails, counts)
    print(f"  (8) A_hole then B: x row at {hole:.4g} s = B's, A's at the other 40; xy (copied, interpolated) {counts}")

    m2 = SCRATCH / "out" / "S01_hole.edi"
    rec = {"xy": [entry(str(a_hole), 0.01, 1000)], "yx": [entry(str(a_hole), 0.01, 1000)]}
    status, _text, err = quiet(module.merge_files, m2, rec)
    assert status == 0, err
    block = sidecar(m2)["merge"]["modes"]["xy"]
    fails = empty_in_file(m2, ("ZXXR", "ZXYR"), [hole])
    assert not fails and block["n_nan"] == 1 and np.allclose(block["gaps"], [[hole, hole]], rtol=1e-6), (
        fails, block["n_nan"], block["gaps"])
    print(f"      A_hole alone: EMPTY at {hole:.4g} s, xy gaps {[[round(v, 3) for v in g] for g in block['gaps']]}")

    m3 = SCRATCH / "out" / "S01_hole_c.edi"
    rec = {"xy": [entry(str(a_hole), 0.01, 1000), entry(str(c), 0.01, 1000)], "yx": [entry(str(a_hole), 0.01, 1000)]}
    status, _text, err = quiet(module.merge_files, m3, rec)
    assert status == 0, err
    beside = P_OFFSET[19:21]
    fails = row_matches(m3, c, 0, beside)
    p_m, z_m, e_m = arrays(m3)
    p_c, z_c, e_c = arrays(c)
    x_c, i = np.log10(p_c), at(p_m, hole)
    line = [np.interp(np.log10(hole), x_c, z_c[:, 0, j].real) + 1j * np.interp(np.log10(hole), x_c, z_c[:, 0, j].imag)
            for j in range(2)]
    line_e = [np.interp(np.log10(hole), x_c, e_c[:, 0, j]) for j in range(2)]
    if not (close(z_m[i, 0], line) and close(e_m[i, 0], line_e)):
        fails.append(f"{hole:.4g} s: x row {z_m[i, 0]} is not on C's line {line}")
    assert not fails, fails
    print(f"      A_hole then C: x row at {beside[0]:.4g} and {beside[1]:.4g} s = C's own, at {hole:.4g} s on C's line")


def main() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    a = write_product("A", P8, tipper=True)
    b = write_product("B", P8)
    c = write_product("C", P_OFFSET)
    module = load_script()
    test_merges(module, a, b, c)
    test_refusals(module, a)
    test_auto(module)
    test_merge_files(module, a, b)
    test_empty_period(module, b, c)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutations:")[0].strip())
    print()
    main()
    print("\nPASS  merge_best_unit")
