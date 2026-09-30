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
the grid. A_hdr is A with ACQBY "Field crew" and FILEBY "Source filer" in its
header. L (station S01L, remote R04) stands for a 1 Hz product: 64 ohm-m
on 33 periods from 0.984 to 9843 s, each 1000 Hz period divided by 1.0159,
so 1.6 % below A's periods where the two overlap. L2 is L again under
another file name; L_hole is L with both rows EMPTY at 13.13 s. A_cut is A
cut at 100 s. M (remote R05, 36 ohm-m) holds A's 41 periods with every odd
one divided by 1.0159; M20 (the first review's E4 source) A's first 20
periods and the next 20 divided by 1.0159, ending at 738.2 s, so exactly
half of its 40 periods on A's; M19 the same with 19 and 21. F (remote R06,
144 ohm-m) holds A's periods shifted by 1.4e-5 in log10 period, just beyond
LOG_TOL.
The merges run through the script's `main` with a recipe file whose EDI
paths are relative to it, and through `merge_files`.

Usage:
    python tests/merge_best_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if a merged row does not come from the source and range the recipe names for it, or the
written EDI lacks either longitude spelling or the recipe's header credits.

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
in log10 period between them; (9) merged through `main` from a recipe file
whose header block gives acqby "UM6P, AU" and prosby "Ben Kay, AuScope",
with A_hdr as the first xy source, the file's >HEAD does not hold exactly
one LON and one LONG line with the same value, ACQBY equal to acqby and
FILEBY and PROSBY equal to prosby, its >=DEFINEMEAS exactly one REFLON and
one REFLONG line with the same value, or its >INFO the line
transfer_function.processed_by.author=<prosby>, the sidecar's header is not
the block, or mt_metadata reading the file does not give acqby, prosby and
prosby as the station's acquired_by, processed_by and submitter; the same
merge with `patch_edi_text` disabled (the writer's own text, which holds no
LONG) does not equal the patched file byte for byte from >FREQ to the end,
or read with mt_metadata does not give the same station id, longitude, Z and
Z errors; the recipe without the header block does not write LON and LONG
and REFLON and REFLONG with equal values, or does not leave ACQBY and FILEBY
as A_hdr has them and PROSBY and the processed_by line out; `patch_edi_text`
on text holding only LONG and REFLONG does not add LON and REFLON with the
same values; or a header block with an unknown key or a value holding = does
not make `main` return 2 without writing an EDI; (10) with xy from A then L
and yx from L over 3-100000 s then A, and no grid key, the merged periods
are not A's 41 and L's 33, or the 25 close pairs (L's periods from 0.984 to
984.3 s each beside A's 1.6 % above) are not in the one WARNING line and the
sidecar's close_pairs, or the sidecar's grid is not union with no lattice,
nothing left out and nothing lost; with yx from L over 0.9-0.99 s (its
0.9843 s only) then A, the one WARNING line does not end "1 close pair of
grid periods (adjacent within 0.02 in log10 period), at 0.9843 and 1 s";
(11) the same recipe with grid: first does not give
A's 41 periods and L's 8 beyond 1000 s with no two adjacent periods closer
than 0.02 in log10 period, the y row at A's 21 periods from 3.16 s is not on
the straight line in log10 period between L's neighbouring periods (rows and
errors, computed in the test), or the x row is not A's and the y row below
3 s is not A's; (12) L's 8 periods beyond 1000 s do not carry L's rows in
both modes, or the sidecar does not record them as copied from L's xy entry,
none interpolated; (13) with xy from A_cut, B and L, the lattice is not
extended by B.edi to 41 periods over 0.01-1000 s, the grid is not A's 41 and
L's 8 beyond, L's left_out is not its 25 periods below 1000 s, or the x row
above 100 s is not B's; (14) at every period of the grid-first product of
(11) the union product of (10) differs in Z or its errors by more than 1e-12
relative; (15) the sidecar of (11) does not record grid first, the lattice of
A.edi (station S01, 41 periods, 0.01-1000 s, no source extending it, none
added), L's 25 left-out periods, nothing lost and no close pair; (16) grid: nonsense does
not make `main` return 2 with an ERROR line naming the grid, writing no EDI;
(17) with both modes from A over 0.01-3 s, L over 3-300 s and A over
300-100000 s and grid: first, A's 15 periods between L's first and last
period in 3-300 s are not added to the grid, recorded in the sidecar's
lattice.added and filled on L's line in both rows, L's 233.4 s (no gathered
lattice period within 0.02 in log10 period: 177.8 and 316.2 s are 0.12 and
0.13 away) is not on the grid with L's own rows, L's left_out is not its 15
periods 3.113-175 s, or a mode holds a NaN; (18) with both modes from A over
100-100000 s then L over 1-100 s and grid: first, the grid is not A's 24
periods 1.334-1000 s (L's 1.313 s, below the shortest gathered lattice
period 1.334 s and within 0.02 of it, left out), a close pair remains, L's
left_out is not its 16 periods 1.313-98.43 s, or the rows at A's 15 periods
1.334-74.99 s are not on L's line; (19) with xy from A and yx from M (A's
periods, every odd one divided by 1.0159: 21 on A's lattice, 20 off) and
grid: first, M is not on the lattice, M extends it, the grid is not A's 41
periods, a close pair remains, M's left_out is not its 20 off periods, or
the y row is not M's own at its 21 lattice periods and on M's line at the
other 20; (20) with xy from A and yx from F (A's periods shifted by 1.4e-5
in log10 period, beyond LOG_TOL) then A and grid: first, the grid is not A's
41 periods (F's 1000.03 s beside A's 1000 s left out), a close pair remains,
F's left_out is not its 41 periods, or the y row is not A's at 0.01 s and on
F's line at A's other 40 periods; (21) with xy from L then A and grid: first
under the site name S01, the merge does not return 0 with one WARNING line
naming L.edi, station S01L and the site, or the sidecar's lattice does not
record first_station S01L; or the same merge under the site name S01L
prints that WARNING or writes other bytes from >FREQ on; (22) the INFO
block's crust keys of the union product of (10) are not version, merged,
tag, site, recipe, the four best lines and sidecar in that order, or those
of the grid-first product of (11) are not the same with crust.grid after
crust.recipe, its value first,A.edi,49,25, or with xy from A then L and yx
from L2 over 3-100000 s then A (L left out at 25 periods, L2 at 21 of the
same) that line does not count the 25 distinct periods; (23) with both modes
from A over 0.01-3 s, L_hole over 3-300 s and A over 300-100000 s and grid:
first, the grid is not A's 20 periods to 2.371 s, A's 13 lattice periods
3.162-177.8 s other than 10 and 13.34 s (L_hole cannot fill those two, their
neighbours 9.843 and 17.50 s enclosing its EMPTY 13.13 s), L_hole's 9.843
and 233.4 s and A's 5 periods from 316.2 s, a close pair remains, a mode
holds a NaN, L_hole's rows at 9.843 s are not its own or those at 7.499 and
17.78 s not on its line, lattice.added is not the 13, L_hole's left_out is
not its other 13 usable periods in 3-300 s, or something is lost; (24) with
xy from A and yx from M20 and grid: first (the first review's E4), M20 does
not lie on the lattice (exactly half of its periods on it), the merge does
not return 0 with the one line "WARNING grid first: mode yx: 1 left-out
period(s) with no grid period within 0.02 in log10 period holding a value:
738.2 s", the sidecar's lost is not {yx: [738.2 s]}, the same merge with the
list disabled does not return 0 with the same bytes from >FREQ on, or the
same recipe under grid: union records anything lost or prints that WARNING.
Each of (10) to (24) runs its check once more on a deliberately wrong
expectation (a close pair short, the one pair worded as several, L's 984.3 s
on the grid, L's own neighbouring values, L's values off by 0.1 %, the
lattice not extended, each union period's neighbour, a left-out period
short, the valid grid union refused, the grid without the added periods and
the grid without L's 233.4 s, the grid with L's 1.313 s, the grid with M's
off periods, the grid with F's 1000.03 s, the WARNING looked for in the S01L
merge, the union's keys with crust.grid, the grid line with 24 periods left
out and with the per-source counts summed (46), round two's grid with 10
and 13.34 s and without 9.843 s, the lattice test on M19 (19 of 40 on), and
738.2 s looked for as lost in the same merge with A behind M20 in yx), which
must fail.

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
L_FACTOR = 1.0159  # a 1 Hz product's periods are its 1000 Hz product's divided by this
P_L = 10.0 ** (np.arange(33) / 8) / L_FACTOR  # 0.984 .. 9843 s, eight per decade, 1.6 % below P8's
CLOSE = 0.02  # adjacent periods closer than this in log10 period are a close pair

# per product: resistivity, Zxx and Zyy as fractions of Zxy, location, remote, tag
PRODUCTS = {
    "A": dict(rho=100.0, dxx=0.10 * np.exp(0.3j), dyy=0.05 * np.exp(-0.2j), lat=-30.25, lon=139.22,
              remote="R01", tag="full", masks=["S01 cluster 3"]),
    "B": dict(rho=400.0, dxx=0.20 * np.exp(0.9j), dyy=-0.15 * np.exp(-0.4j), lat=-31.50, lon=140.10,
              remote="R02", tag="redo", masks=[]),
    "C": dict(rho=25.0, dxx=0.30 * np.exp(-0.5j), dyy=0.25 * np.exp(0.6j), lat=-32.00, lon=141.00,
              remote="R03", tag="night", masks=["S01 storm"]),
    "L": dict(rho=64.0, dxx=0.15 * np.exp(-0.7j), dyy=0.35 * np.exp(0.4j), lat=-30.25, lon=139.22,
              remote="R04", tag="1hz", masks=[]),
    "M": dict(rho=36.0, dxx=0.12 * np.exp(0.5j), dyy=0.22 * np.exp(-0.9j), lat=-30.25, lon=139.22,
              remote="R05", tag="half", masks=[]),
    "F": dict(rho=144.0, dxx=0.18 * np.exp(-0.3j), dyy=0.28 * np.exp(0.7j), lat=-30.25, lon=139.22,
              remote="R06", tag="near", masks=[]),
}
TIPPER = np.array([0.12 + 0.05j, -0.08 + 0.03j])
HEADER = {"acqby": "UM6P, AU", "prosby": "Ben Kay, AuScope"}
SOURCE_CREDITS = {"ACQBY": "Field crew", "FILEBY": "Source filer"}
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
                  auto: bool = False, hole: float | None = None, credits: bool = False,
                  hole_rows: tuple[int, ...] = (0,)) -> Path:
    """Write one product's EDI and sidecar under SCRATCH; return the EDI path.

    With `auto` the errors follow `auto_errors`, B's yx phase is flipped in
    0.1-0.178 s and C's rho is ten times higher in 31.6-56.2 s. With `hole`
    the rows `hole_rows` (the x row by default) and their errors are NaN at
    that period, written as EMPTY. With `credits` the header's ACQBY and
    FILEBY are SOURCE_CREDITS'.
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
        for row in hole_rows:
            z[k, row, :], err[k, row, :] = np.nan, np.nan
    tf = TF()
    tf.station_metadata.id = station
    tf.survey_metadata.id = "merge_best_unit"
    tf.station_metadata.location.latitude = spec["lat"]
    tf.station_metadata.location.longitude = spec["lon"]
    if credits:
        tf.station_metadata.acquired_by.author = SOURCE_CREDITS["ACQBY"]
        tf.station_metadata.provenance.submitter.author = SOURCE_CREDITS["FILEBY"]
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


def block_values(path: Path, block: str) -> dict[str, list[str]]:
    """Return the KEY=VALUE lines of one block of an EDI file, upper-case key to its values in file order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(k for k, line in enumerate(lines) if line.strip().split(" ")[0].upper() == block)
    found = {}
    for line in lines[start + 1:]:
        if line.lstrip().startswith(">"):
            break
        if "=" in line:
            key, value = line.strip().split("=", 1)
            found.setdefault(key.strip().upper(), []).append(value.strip())
    return found


def data_section(path: Path) -> bytes:
    """Return the bytes of an EDI file from its >FREQ line to the end."""
    raw = path.read_bytes()
    return raw[raw.index(b">FREQ "):]


def spellings(path: Path) -> list[str]:
    """Check that an EDI holds LON and LONG, and REFLON and REFLONG, once each with one value; return the failures."""
    fails = []
    for block, pair in ((">HEAD", ("LON", "LONG")), (">=DEFINEMEAS", ("REFLON", "REFLONG"))):
        found = block_values(path, block)
        got = [found.get(key, []) for key in pair]
        if not (len(got[0]) == len(got[1]) == 1 and got[0] == got[1]):
            fails.append(f"{path.name} {block}: {dict(zip(pair, got))}")
    return fails


def test_header(module, b: Path) -> None:
    """Test (9): both longitude spellings and the recipe's header credits, the data untouched."""
    a_hdr = write_product("A_hdr", P8, credits=True)
    src = block_values(a_hdr, ">HEAD")
    assert all(src.get(key) == [value] for key, value in SOURCE_CREDITS.items()), src
    sites = {"S01": {"xy": [entry("A_hdr.edi", 0.01, 1.0), entry(b.name, 3.0, 100.0)],
                     "yx": [entry("A_hdr.edi", 0.01, 1000)]}}
    with_header, plain = SCRATCH / "recipes_header.yaml", SCRATCH / "recipes_plain.yaml"
    with_header.write_text(yaml.safe_dump({"header": HEADER, **sites}, sort_keys=False), encoding="utf-8")
    plain.write_text(yaml.safe_dump(sites, sort_keys=False), encoding="utf-8")
    out = SCRATCH / "out"

    patched = out / "S01_header.edi"
    status, _text, err = run(module, str(patched), "--recipe", str(with_header), "--site", "S01", "--tag", "hdr")
    assert status == 0, err
    head, info = block_values(patched, ">HEAD"), block_values(patched, ">INFO")
    want = {"ACQBY": [HEADER["acqby"]], "FILEBY": [HEADER["prosby"]], "PROSBY": [HEADER["prosby"]]}
    fails = spellings(patched) + [f">HEAD {key}: {head.get(key)}" for key in want if head.get(key) != want[key]]
    if info.get("TRANSFER_FUNCTION.PROCESSED_BY.AUTHOR") != [HEADER["prosby"]]:
        fails.append(f">INFO processed_by: {info.get('TRANSFER_FUNCTION.PROCESSED_BY.AUTHOR')}")
    if sidecar(patched).get("header") != HEADER:
        fails.append(f"sidecar header: {sidecar(patched).get('header')}")
    assert not fails, fails
    sm = read(patched).station_metadata
    credits = (sm.acquired_by.author, sm.transfer_function.processed_by.author, sm.provenance.submitter.author)
    assert credits == (HEADER["acqby"], HEADER["prosby"], HEADER["prosby"]), credits
    print(f"  (9) header block: LON = LONG = {head['LON'][0]}, REFLON = REFLONG, ACQBY {head['ACQBY'][0]!r}, "
          f"FILEBY = PROSBY = {head['FILEBY'][0]!r}, INFO processed_by.author; mt_metadata reads {credits}")

    raw = out / "S01_header_raw.edi"
    original = module.patch_edi_text
    module.patch_edi_text = lambda text, header=None: text
    try:
        status, _text, err = run(module, str(raw), "--recipe", str(with_header), "--site", "S01", "--tag", "hdr")
    finally:
        module.patch_edi_text = original
    assert status == 0 and "LONG" not in block_values(raw, ">HEAD"), (status, err)
    assert data_section(patched) == data_section(raw), "the text from >FREQ on differs from the writer's"
    tf_p, tf_r = read(patched), read(raw)
    same = (tf_p.station_metadata.id == tf_r.station_metadata.id
            and tf_p.station_metadata.location.longitude == tf_r.station_metadata.location.longitude
            and np.array_equal(np.asarray(tf_p.impedance.data), np.asarray(tf_r.impedance.data), equal_nan=True)
            and np.array_equal(np.asarray(tf_p.impedance_error.data), np.asarray(tf_r.impedance_error.data),
                               equal_nan=True))
    assert same, "the patched file reads back differently from the writer's text"
    print(f"      against the writer's text: {len(data_section(raw))} bytes from >FREQ identical; station "
          f"{tf_p.station_metadata.id}, longitude {tf_p.station_metadata.location.longitude}, Z and errors equal")

    bare = out / "S01_plain.edi"
    status, _text, err = run(module, str(bare), "--recipe", str(plain), "--site", "S01")
    assert status == 0, err
    head, info = block_values(bare, ">HEAD"), block_values(bare, ">INFO")
    fails = spellings(bare) + [f">HEAD {key}: {head.get(key)}" for key, value in SOURCE_CREDITS.items()
                               if head.get(key) != [value]]
    if "PROSBY" in head or "TRANSFER_FUNCTION.PROCESSED_BY.AUTHOR" in info or sidecar(bare).get("header") != {}:
        fails.append(f"no header block: PROSBY {head.get('PROSBY')}, processed_by "
                     f"{info.get('TRANSFER_FUNCTION.PROCESSED_BY.AUTHOR')}, sidecar {sidecar(bare).get('header')}")
    assert not fails, fails
    print(f"      no header block: LON = LONG, REFLON = REFLONG, ACQBY {head['ACQBY'][0]!r} and FILEBY "
          f"{head['FILEBY'][0]!r} as A_hdr's, no PROSBY")

    text = raw.read_text(encoding="utf-8").replace("\tLON=", "\tLONG=").replace(" REFLON=", " REFLONG=")
    long_only = out / "S01_long_only.edi"
    long_only.write_text(module.patch_edi_text(text), encoding="utf-8")
    fails = spellings(long_only)
    assert not fails, fails
    print("      text with LONG and REFLONG only: LON and REFLON added with the same values")

    for label, block in (("unknown key", {"acqby": "UM6P, AU", "processedby": "x"}),
                         ("value holding =", {"prosby": "Ben Kay=AuScope"})):
        bad = SCRATCH / "recipes_bad_header.yaml"
        bad.write_text(yaml.safe_dump({"header": block, **sites}, sort_keys=False), encoding="utf-8")
        refused = out / "S01_bad_header.edi"
        status, _text, err = run(module, str(refused), "--recipe", str(bad), "--site", "S01")
        assert status == 2 and not refused.exists(), (label, status, err)
        print(f"      header {label}: exit 2, {err.strip()}")


def periods_fail(got, want) -> list[str]:
    """Compare two period lists within 1e-6 in log10 period; return the difference, empty when they agree."""
    got, want = np.asarray(got, dtype=float), np.asarray(want, dtype=float)
    if got.size == want.size and np.allclose(np.log10(got), np.log10(want), rtol=0, atol=1e-6):
        return []
    extra = [f"{p:.4g}" for p in got if np.abs(np.log10(want) - np.log10(p)).min() > 1e-6] if want.size else []
    short = [f"{p:.4g}" for p in want if np.abs(np.log10(got) - np.log10(p)).min() > 1e-6] if got.size else []
    return [f"{got.size} periods, not {want.size}; not wanted {extra}; missing {short}"]


def pairs_of(periods) -> list[list[float]]:
    """Return the adjacent periods closer than CLOSE in log10 period, computed here."""
    p = np.sort(np.asarray(periods, dtype=float))
    return [[float(p[k]), float(p[k + 1])] for k in range(p.size - 1) if np.log10(p[k + 1] / p[k]) < CLOSE]


def pairs_fail(got, want) -> list[str]:
    """Compare two lists of period pairs within 1e-6 relative; return the difference."""
    if len(got) == len(want) and all(np.allclose(g, w, rtol=1e-6, atol=0) for g, w in zip(got, want)):
        return []
    return [f"{len(got)} pairs, not {len(want)}: {got[:2]} ... against {want[:2]} ..."]


def log_line(source: Path, row: int, periods) -> tuple[np.ndarray, np.ndarray]:
    """Return a source's row and errors on the straight line in log10 period at the given periods, computed here."""
    p_s, z_s, e_s = arrays(source)
    order = np.argsort(p_s)
    x, z_s, e_s = np.log10(p_s[order]), z_s[order, row, :], e_s[order, row, :]
    xq = np.log10(np.asarray(periods, dtype=float))
    z = np.stack([np.interp(xq, x, z_s[:, j].real) + 1j * np.interp(xq, x, z_s[:, j].imag) for j in range(2)], axis=1)
    e = np.stack([np.interp(xq, x, e_s[:, j]) for j in range(2)], axis=1)
    return z, e


def values_fail(merged: Path, row: int, periods, z_want, e_want) -> list[str]:
    """Compare one row of the merged EDI and its errors with wanted values at the given periods; return the failures."""
    p_m, z_m, e_m = arrays(merged)
    fails = []
    for p, zw, ew in zip(periods, z_want, e_want):
        i = at(p_m, p)
        if not (close(z_m[i, row], zw) and close(e_m[i, row], ew)):
            fails.append(f"{p:.4g} s: {z_m[i, row]} is not {zw}")
    return fails


def must_fail(label: str, fails: list[str]) -> None:
    """Assert that a check given a deliberately wrong expectation reports a failure."""
    assert fails, f"control {label}: the check passed a wrong expectation"
    print(f"      control {label}: fails as it must ({fails[0][:90]})")


def test_grid(module, a: Path, b: Path) -> None:
    """Tests (10) to (24): the grid key, with L, station S01L, on P_L, 1.6 % below A's periods."""
    lp = write_product("L", P_L, station="S01L")
    a_cut = write_product("A_cut", P8[:33])
    out = SCRATCH / "out"
    base = {"xy": [entry(str(a), 0.01, 1e5), entry(str(lp), 0.01, 1e5)],
            "yx": [entry(str(lp), 3.0, 1e5), entry(str(a), 0.01, 1e5)]}
    inside, beyond = P_L[P_L < 1000.0], P_L[P_L > 1000.0]
    owned_l = P8[P8 >= 3.0]  # A's periods at which L gives yx, between its own periods
    p_l, z_l, e_l = arrays(lp)

    # (10) without the key: both grids, the close pairs reported
    m_u = out / "S01_union_L.edi"
    status, text, err = quiet(module.merge_files, m_u, base, force=True)
    assert status == 0, err
    p_u = arrays(m_u)[0]
    side_u = sidecar(m_u)["merge"]
    want_pairs = [[float(q), float(q * L_FACTOR)] for q in inside]
    warn = [ln for ln in text.splitlines() if ln.startswith("WARNING") and "close pairs" in ln]
    fails = (periods_fail(p_u, np.sort(np.concatenate([P8, P_L]))) + pairs_fail(pairs_of(p_u), want_pairs)
             + pairs_fail(side_u["close_pairs"], want_pairs))
    if not (len(warn) == 1 and warn[0].startswith(f"WARNING {inside.size} close pairs")):
        fails.append(f"warning lines {warn}")
    if not (side_u["grid"] == "union" and side_u["lattice"] is None and side_u["left_out"] == {}
            and side_u["lost"] == {}):
        fails.append(f"sidecar grid {side_u['grid']}, lattice {side_u['lattice']}, left_out {side_u['left_out']}, "
                     f"lost {side_u['lost']}")
    assert not fails, fails
    print(f"  (10) no grid key: {p_u.size} periods (A's {P8.size} and L's {P_L.size}), {len(want_pairs)} close pairs "
          f"{want_pairs[0][0]:.4g}/{want_pairs[0][1]:.4g} .. {want_pairs[-1][0]:.4g}/{want_pairs[-1][1]:.4g} s in "
          f"the WARNING line and the sidecar; nothing lost")
    must_fail("close pairs one short", pairs_fail(side_u["close_pairs"], want_pairs[1:]))

    # (10) one close pair: the WARNING names its two periods
    m_1 = out / "S01_union_one_pair.edi"
    rec = {"xy": [entry(str(a), 0.01, 1e5)], "yx": [entry(str(lp), 0.9, 0.99), entry(str(a), 0.01, 1e5)]}
    status, text, err = quiet(module.merge_files, m_1, rec, force=True)
    assert status == 0, err

    def one_pair_fail(text: str, ending: str) -> list[str]:
        warn = [ln for ln in text.splitlines() if ln.startswith("WARNING") and "close pair" in ln]
        if len(warn) == 1 and warn[0].startswith("WARNING 1 close pair of grid periods") and warn[0].endswith(ending):
            return []
        return [f"warning lines {warn}"]

    ending = f"(adjacent within {CLOSE} in log10 period), at {P_L[0]:.4g} and {P8[16]:.4g} s"
    assert not one_pair_fail(text, ending), one_pair_fail(text, ending)
    print(f"      one close pair: {[ln for ln in text.splitlines() if 'close pair' in ln][0]}")
    must_fail("the one pair worded as several", one_pair_fail(
        text, f"the first {P_L[0]:.4g} and {P8[16]:.4g} s, the last {P_L[0]:.4g} and {P8[16]:.4g} s"))

    # (11) grid first: A's lattice, L's yx on it by interpolation, A's xy as it is
    m_f = out / "S01_first_L.edi"
    status, text, err = quiet(module.merge_files, m_f, {**base, "grid": "first"}, force=True)
    assert status == 0, err
    p_f = arrays(m_f)[0]
    want_grid = np.concatenate([P8, beyond])
    z_want, e_want = log_line(lp, 1, owned_l)
    fails = (periods_fail(p_f, want_grid) + pairs_fail(pairs_of(p_f), [])
             + values_fail(m_f, 1, owned_l, z_want, e_want) + row_matches(m_f, a, 0, P8)
             + row_matches(m_f, a, 1, P8[P8 < 3.0]))
    assert not fails, fails
    print(f"  (11) grid first: {p_f.size} periods, A's {P8.size} and L's {beyond.size} beyond 1000 s; no close pair; "
          f"yx at A's {owned_l.size} periods from 3.16 s on L's line, x row = A's")
    must_fail("L's 984.3 s on the grid", periods_fail(p_f, np.sort(np.append(want_grid, inside[-1]))))
    near = [at(p_l, q / L_FACTOR) for q in owned_l]
    must_fail("L's own neighbouring values", values_fail(m_f, 1, owned_l, z_l[near, 1, :], e_l[near, 1, :]))

    # (12) L's periods beyond A's longest are on the grid, copied
    k = [at(p_l, q) for q in beyond]
    fails = sum((values_fail(m_f, row, beyond, z_l[k, row, :], e_l[k, row, :]) for row in (0, 1)), [])
    xy_l = sidecar(m_f)["merge"]["modes"]["xy"]["entries"][1]
    fails += periods_fail(xy_l["copied"], beyond) + (["xy from L interpolated"] if xy_l["interpolated"] else [])
    assert not fails, fails
    print(f"  (12) L's {beyond.size} periods {beyond[0]:.4g} .. {beyond[-1]:.4g} s on the grid, both rows copied")
    must_fail("L's values off by 0.1 %", values_fail(m_f, 0, beyond, z_l[k, 0, :] * 1.001, e_l[k, 0, :]))

    # (13) a first xy source cut at 100 s, the lattice extended by B
    m_x = out / "S01_first_ext.edi"
    rec = {"xy": [entry(str(a_cut), 0.01, 1e5), entry(str(b), 0.01, 1e5), entry(str(lp), 0.01, 1e5)],
           "yx": [entry(str(lp), 3.0, 1e5), entry(str(a_cut), 0.01, 1e5)], "grid": "first"}
    status, text, err = quiet(module.merge_files, m_x, rec, force=True)
    assert status == 0, err
    p_x, side_x = arrays(m_x)[0], sidecar(m_x)["merge"]
    lat = side_x["lattice"]
    left = {Path(k).name: v for k, v in side_x["left_out"].items()}
    fails = (periods_fail(p_x, want_grid) + periods_fail(left.get("L.edi", []), inside)
             + row_matches(m_x, b, 0, P8[P8 > 100.0]))
    if not ([Path(p).name for p in lat["extended_by"]] == ["B.edi"] and lat["n_periods"] == P8.size
            and np.allclose(lat["span"], [P8[0], P8[-1]], rtol=1e-6)):
        fails.append(f"lattice {lat}")
    assert not fails, fails
    print(f"  (13) A_cut ({P8[:33].size} periods to 100 s) then B: the lattice extended by B.edi to "
          f"{lat['n_periods']} periods, {lat['span'][0]:.4g} .. {lat['span'][1]:.4g} s; L left out at its "
          f"{inside.size} periods inside; x row above 100 s = B's")
    unextended = np.sort(np.concatenate([P8, P_L[P_L > 100.0]]))
    must_fail("the lattice not extended", periods_fail(p_x, unextended))

    # (14) at the periods both hold, the grid-first product is the union product
    p_u, z_u, e_u = arrays(m_u)
    p_f, z_f, e_f = arrays(m_f)
    both = [(at(p_f, p), at(p_u, p)) for p in p_f]
    i_f, i_u = np.array([i for i, _ in both]), np.array([j for _, j in both])

    def largest(zf, zu) -> float:
        return float(np.max(np.abs(zf - zu) / np.abs(zu)))

    worst = max(largest(z_f[i_f], z_u[i_u]), largest(e_f[i_f], e_u[i_u]))
    assert len(both) == p_f.size and worst <= 1e-12, (len(both), worst)
    print(f"  (14) at the {len(both)} periods both products hold: largest relative difference {worst:.1e} (Z and "
          f"errors, both rows)")
    shifted = largest(z_f[i_f[:-1]], z_u[i_u[:-1] + 1])
    assert shifted > 1e-12, shifted
    print(f"      control each union period's neighbour: largest relative difference {shifted:.2g}, fails as it must")

    # (15) the sidecar of the grid-first merge
    side_f = sidecar(m_f)["merge"]
    lat = side_f["lattice"]
    left = {Path(k).name: v for k, v in side_f["left_out"].items()}
    fails = periods_fail(left.get("L.edi", []), inside) + pairs_fail(side_f["close_pairs"], [])
    if not (side_f["grid"] == "first" and set(left) == {"L.edi"} and Path(lat["first"]).name == "A.edi"
            and lat["first_station"] == "S01"
            and [Path(p).name for p in lat["sources"]] == ["A.edi"] and lat["extended_by"] == []
            and lat["added"] == [] and lat["n_periods"] == P8.size
            and np.allclose(lat["span"], [P8[0], P8[-1]], rtol=1e-6) and side_f["close_dex"] == CLOSE
            and side_f["lost"] == {}):
        fails.append(f"grid {side_f['grid']}, lattice {lat}, left_out sources {list(left)}")
    assert not fails, fails
    print(f"  (15) sidecar: grid first, lattice of A.edi {lat['n_periods']} periods {lat['span'][0]:.4g} .. "
          f"{lat['span'][1]:.4g} s, left_out L.edi {len(left['L.edi'])} periods, lost {{}}, close_pairs []")
    must_fail("left_out one short", periods_fail(left["L.edi"], inside[:-1]))

    # (16) an unknown grid
    def refused_fail(grid: str, name: str) -> list[str]:
        path = SCRATCH / "recipes_grid.yaml"
        path.write_text(yaml.safe_dump({"S01": {**base, "grid": grid}}, sort_keys=False), encoding="utf-8")
        target = out / name
        status, _text, err = run(module, str(target), "--recipe", str(path), "--site", "S01", "--force")
        if status == 2 and f"ERROR grid: {grid!r}" in err and not target.exists():
            return []
        return [f"grid {grid}: exit {status}, stderr {err.strip()!r}, written {target.exists()}"]

    assert not refused_fail("nonsense", "S01_grid_nonsense.edi")
    print("  (16) grid: nonsense: exit 2, ERROR grid: 'nonsense' is not one of union, first; no EDI")
    must_fail("the valid grid union refused", refused_fail("union", "S01_grid_union.edi"))

    # (17) L alone over a range A does not cover: A's lattice periods between L's own go on the grid
    m_h = out / "S01_first_hole.edi"
    rec = {mode: [entry(str(a), 0.01, 3.0), entry(str(lp), 3.0, 300.0), entry(str(a), 300.0, 1e5)]
           for mode in ("xy", "yx")}
    status, text, err = quiet(module.merge_files, m_h, {**rec, "grid": "first"}, force=True)
    assert status == 0, err
    own = P_L[(P_L >= 3.0) & (P_L <= 300.0)]
    added = P8[(P8 >= own.min()) & (P8 <= own.max())]
    last = own[-1:]  # 233.4 s: the nearest gathered lattice periods, 177.8 and 316.2 s, are 0.12 and 0.13 away
    want = np.sort(np.concatenate([P8[P8 <= 3.0], added, last, P8[P8 >= 300.0]]))
    side_h = sidecar(m_h)["merge"]
    left = {Path(k).name: v for k, v in side_h["left_out"].items()}
    fails = (periods_fail(arrays(m_h)[0], want) + periods_fail(side_h["lattice"]["added"], added)
             + periods_fail(left.get("L.edi", []), own[:-1]))
    k_last = [at(p_l, q) for q in last]
    for row in (0, 1):
        fails += values_fail(m_h, row, added, *log_line(lp, row, added))
        fails += values_fail(m_h, row, last, z_l[k_last, row, :], e_l[k_last, row, :])
    nans = [side_h["modes"][mode]["n_nan"] for mode in ("xy", "yx")]
    assert not fails and nans == [0, 0], (fails, nans)
    print(f"  (17) L alone over 3-300 s: A's {added.size} periods {added[0]:.4g} .. {added[-1]:.4g} s added and "
          f"filled from L's line in both rows; L's {last[0]:.4g} s kept with L's rows; L left out at "
          f"{len(left['L.edi'])} periods; {want.size} periods, none NaN")
    must_fail("the union less L's periods", periods_fail(arrays(m_h)[0], np.concatenate([P8[P8 <= 3.0],
                                                                                        P8[P8 >= 300.0]])))
    must_fail("the grid without L's 233.4 s", periods_fail(arrays(m_h)[0], np.setdiff1d(want, last)))

    # (18) an off-lattice source below the shortest gathered lattice period: no close pair at the short end
    m_s = out / "S01_first_short.edi"
    rec = {mode: [entry(str(a), 100.0, 1e5), entry(str(lp), 1.0, 100.0)] for mode in ("xy", "yx")}
    status, text, err = quiet(module.merge_files, m_s, {**rec, "grid": "first"}, force=True)
    assert status == 0, err
    own = P_L[(P_L >= 1.0) & (P_L <= 100.0)]
    added = P8[(P8 >= own.min()) & (P8 <= own.max()) & (P8 < 100.0)]
    want = P8[P8 >= own.min()]
    p_s = arrays(m_s)[0]
    side_s = sidecar(m_s)["merge"]
    left = {Path(k).name: v for k, v in side_s["left_out"].items()}
    fails = (periods_fail(p_s, want) + pairs_fail(pairs_of(p_s), []) + pairs_fail(side_s["close_pairs"], [])
             + periods_fail(left.get("L.edi", []), own) + row_matches(m_s, a, 0, P8[P8 >= 100.0]))
    for row in (0, 1):
        fails += values_fail(m_s, row, added, *log_line(lp, row, added))
    assert not fails, fails
    print(f"  (18) A over 100 s and up, L over 1-100 s: {p_s.size} periods {p_s[0]:.4g} .. {p_s[-1]:.4g} s, no close "
          f"pair; L left out at {len(left['L.edi'])} periods {own[0]:.4g} .. {own[-1]:.4g} s; rows at A's "
          f"{added.size} periods {added[0]:.4g} .. {added[-1]:.4g} s on L's line")
    must_fail("the grid with L's 1.313 s", periods_fail(p_s, np.sort(np.append(want, own[0]))))

    # (19) a source on the lattice at half its periods does not extend it inside the first xy source's span
    p_m = P8.copy()
    p_m[1::2] /= L_FACTOR
    mp = write_product("M", p_m)
    m_m = out / "S01_first_half.edi"
    rec = {"xy": [entry(str(a), 0.01, 1e5)], "yx": [entry(str(mp), 0.01, 1e5)], "grid": "first"}
    status, text, err = quiet(module.merge_files, m_m, rec)
    assert status == 0, err
    p_g = arrays(m_m)[0]
    side_m = sidecar(m_m)["merge"]
    lat = side_m["lattice"]
    left = {Path(k).name: v for k, v in side_m["left_out"].items()}
    off_m = p_m[1::2]
    z_m, e_m = log_line(mp, 1, P8[1::2])
    fails = (periods_fail(p_g, P8) + pairs_fail(pairs_of(p_g), []) + periods_fail(left.get("M.edi", []), off_m)
             + row_matches(m_m, mp, 1, P8[0::2]) + values_fail(m_m, 1, P8[1::2], z_m, e_m))
    if not ([Path(p).name for p in lat["sources"]] == ["A.edi", "M.edi"] and lat["extended_by"] == []
            and lat["n_periods"] == P8.size):
        fails.append(f"lattice {lat}")
    assert not fails, fails
    print(f"  (19) M with {P8[0::2].size} of its {p_m.size} periods on A's lattice: on it, extending nothing; "
          f"{p_g.size} periods, no close pair; M left out at its {len(left['M.edi'])} off periods; y row M's own "
          f"at {P8[0::2].size}, on M's line at {P8[1::2].size}")
    must_fail("the grid with M's off periods", periods_fail(p_g, np.sort(np.concatenate([P8, off_m]))))

    # (20) a source a little beyond LOG_TOL from the lattice: its longest period beside A's is left out too
    p_fs = P8 * 10 ** 1.4e-5
    fp = write_product("F", p_fs)
    m_n = out / "S01_first_near.edi"
    rec = {"xy": [entry(str(a), 0.01, 1e5)], "yx": [entry(str(fp), 0.01, 1e5), entry(str(a), 0.01, 1e5)],
           "grid": "first"}
    status, text, err = quiet(module.merge_files, m_n, rec)
    assert status == 0, err
    p_n = arrays(m_n)[0]
    side_n = sidecar(m_n)["merge"]
    left = {Path(k).name: v for k, v in side_n["left_out"].items()}
    fails = (periods_fail(p_n, P8) + pairs_fail(pairs_of(p_n), []) + periods_fail(left.get("F.edi", []), p_fs)
             + row_matches(m_n, a, 1, P8[:1]) + values_fail(m_n, 1, P8[1:], *log_line(fp, 1, P8[1:])))
    assert not fails, fails
    print(f"  (20) F 1.4e-5 from A in log10 period: {p_n.size} periods, no close pair; F left out at "
          f"{len(left['F.edi'])} periods; y row A's at {P8[0]:.4g} s, on F's line at the other {P8.size - 1}")
    must_fail("the grid with F's 1000.03 s", periods_fail(p_n, np.append(P8, p_fs[-1])))

    # (21) the first xy source is the 1 Hz station: a WARNING, the merge unchanged
    rec = {"xy": [entry(str(lp), 0.01, 1e5), entry(str(a), 0.01, 1e5)], "yx": [entry(str(a), 0.01, 1e5)],
           "grid": "first"}
    m_w, m_q = out / "S01_first_is_L.edi", out / "S01L_first_is_L.edi"
    status_w, text_w, err_w = quiet(module.merge_files, m_w, rec, force=True, site="S01")
    status_q, text_q, err_q = quiet(module.merge_files, m_q, rec, force=True, site="S01L")

    def warned(text: str, site: str) -> list[str]:
        found = [ln for ln in text.splitlines() if ln.startswith("WARNING grid first")]
        if len(found) == 1 and "L.edi" in found[0] and "station S01L" in found[0] and f"site {site}" in found[0]:
            return []
        return [f"WARNING lines {found}"]

    fails = warned(text_w, "S01")
    if not (status_w == status_q == 0 and sidecar(m_w)["merge"]["lattice"]["first_station"] == "S01L"):
        fails.append(f"exit {status_w}, {status_q}; lattice {sidecar(m_w)['merge']['lattice']}")
    if [ln for ln in text_q.splitlines() if ln.startswith("WARNING grid first")]:
        fails.append("site S01L warned")
    if data_section(m_w) != data_section(m_q):
        fails.append("the data from >FREQ on differ between the two site names")
    assert not fails, fails
    print(f"  (21) L first under site S01: exit 0, "
          f"{[ln for ln in text_w.splitlines() if ln.startswith('WARNING grid first')][0]}; lattice first_station "
          f"S01L; under site S01L no WARNING, {len(data_section(m_q))} bytes from >FREQ identical")
    must_fail("the WARNING looked for in the S01L merge", warned(text_q, "S01L"))

    # (22) the INFO block's crust lines: crust.grid under grid first only
    def crust_lines(path: Path) -> list[tuple[str, str]]:
        # written as transfer_function.processing_parameters.crust.<key>=<value>, the = dropped for an empty value
        return re.findall(r"^\s*\S*?(crust\.[A-Za-z0-9_]+)=?(.*?)\s*$", path.read_text(encoding="utf-8"), flags=re.M)

    def keys_fail(path: Path, want: list[str], grid_value: str | None) -> list[str]:
        got = crust_lines(path)
        fails = [] if [k for k, _v in got] == want else [f"{path.name} keys {[k for k, _v in got]}"]
        value = dict(got).get("crust.grid")
        if value != grid_value:
            fails.append(f"{path.name} crust.grid {value!r}, not {grid_value!r}")
        return fails

    best = ["crust.best_xy_1", "crust.best_xy_2", "crust.best_yx_1", "crust.best_yx_2"]
    head = ["crust.version", "crust.merged", "crust.tag", "crust.site", "crust.recipe"]
    want_u, want_f = head + best + ["crust.sidecar"], head + ["crust.grid"] + best + ["crust.sidecar"]
    grid_value = f"first,A.edi,{P8.size + beyond.size},{inside.size}"
    fails = keys_fail(m_u, want_u, None) + keys_fail(m_f, want_f, grid_value)
    assert not fails, fails
    print(f"  (22) INFO crust lines: union {len(want_u)} without crust.grid; grid first crust.grid={grid_value} after "
          f"crust.recipe")
    must_fail("the union's keys with crust.grid", keys_fail(m_u, want_f, grid_value))
    must_fail("the grid line with 24 periods left out", keys_fail(m_f, want_f, grid_value.rsplit(",", 1)[0] + ",24"))

    # (22) two off-lattice sources left out at the same periods: the count is of distinct periods
    l2 = write_product("L2", P_L, station="S01L")
    m_d = out / "S01_first_L_L2.edi"
    rec = {"xy": [entry(str(a), 0.01, 1e5), entry(str(lp), 0.01, 1e5)],
           "yx": [entry(str(l2), 3.0, 1e5), entry(str(a), 0.01, 1e5)], "grid": "first"}
    status, text, err = quiet(module.merge_files, m_d, rec, force=True)
    assert status == 0, err
    left = {Path(k).name: v for k, v in sidecar(m_d)["merge"]["left_out"].items()}
    counts = {name: len(v) for name, v in left.items()}
    assert counts == {"L.edi": inside.size, "L2.edi": int((inside > 3.0).sum())}, counts
    fails = keys_fail(m_d, want_f, grid_value)
    assert not fails, fails
    print(f"      L and L2 left out at {counts['L.edi']} and {counts['L2.edi']} periods, {inside.size} distinct: "
          f"crust.grid={grid_value}")
    summed = f"{grid_value.rsplit(',', 1)[0]},{sum(counts.values())}"
    must_fail(f"the per-source counts summed ({sum(counts.values())})", keys_fail(m_d, want_f, summed))

    # (23) an off-lattice entry does not gather the lattice periods across one of its unusable periods
    l_hole = write_product("L_hole", P_L, station="S01L", hole=float(P_L[9]), hole_rows=(0, 1))
    p_lh, z_lh, e_lh = arrays(l_hole)
    assert not np.all(np.isfinite(z_lh[9]) & (z_lh[9] != 0)), f"L_hole at {P_L[9]:.4g} s reads {z_lh[9]}"
    m_n1 = out / "S01_first_L_hole.edi"
    rec = {mode: [entry(str(a), 0.01, 3.0), entry(str(l_hole), 3.0, 300.0), entry(str(a), 300.0, 1e5)]
           for mode in ("xy", "yx")}
    status, text, err = quiet(module.merge_files, m_n1, {**rec, "grid": "first"}, force=True)
    assert status == 0, err
    usable_l = np.delete(P_L, 9)
    own = usable_l[(usable_l >= 3.0) & (usable_l <= 300.0)]
    span = P8[(P8 >= own.min()) & (P8 <= own.max())]
    across = span[(span > P_L[8]) & (span < P_L[10])]  # 10 and 13.34 s, between L_hole's 9.843 and 17.50 s
    added = np.setdiff1d(span, across)
    kept_l = P_L[[8, 19]]  # 9.843 s (nearest gathered lattice periods 7.499 and 17.78 s) and 233.4 s
    want = np.sort(np.concatenate([P8[P8 <= 3.0], added, kept_l, P8[P8 >= 300.0]]))
    p_n1 = arrays(m_n1)[0]
    side_n1 = sidecar(m_n1)["merge"]
    left = {Path(k).name: v for k, v in side_n1["left_out"].items()}
    fails = (periods_fail(p_n1, want) + pairs_fail(pairs_of(p_n1), [])
             + periods_fail(side_n1["lattice"]["added"], added)
             + periods_fail(left.get("L_hole.edi", []), np.setdiff1d(own, kept_l)))
    assert not fails, fails
    beside = P8[[23, 26]]  # 7.499 and 17.78 s, next to the unusable 13.13 s's neighbours
    for row in (0, 1):
        fails += values_fail(m_n1, row, kept_l[:1], z_lh[[8], row, :], e_lh[[8], row, :])
        fails += values_fail(m_n1, row, beside, *log_line(l_hole, row, beside))
    nans = [side_n1["modes"][mode]["n_nan"] for mode in ("xy", "yx")]
    if nans != [0, 0] or side_n1["lost"] != {}:
        fails.append(f"n_nan {nans}, lost {side_n1['lost']}")
    assert not fails, fails
    print(f"  (23) L_hole (EMPTY at {P_L[9]:.4g} s) over 3-300 s: {p_n1.size} periods, no close pair, none NaN, "
          f"nothing lost; {added.size} lattice periods added, not {across[0]:.4g} and {across[1]:.4g} s; L_hole's "
          f"{kept_l[0]:.4g} and {kept_l[1]:.4g} s kept with its rows; left out at {len(left['L_hole.edi'])} periods")
    round_two = np.sort(np.concatenate([P8[P8 <= 3.0], span, kept_l[1:], P8[P8 >= 300.0]]))
    must_fail("round two's grid with 10 and 13.34 s and without 9.843 s", periods_fail(p_n1, round_two))

    # (24) E4: a value the union holds that no grid period near it holds is reported; A behind M20 holds it
    p_m20 = np.concatenate([P8[:20], P8[20:40] / L_FACTOR])
    p_m19 = np.concatenate([P8[:19], P8[19:40] / L_FACTOR])
    m20, m19 = write_product("M20", p_m20), write_product("M19", p_m19)
    e4 = {"xy": [entry(str(a), 0.01, 1e5)], "yx": [entry(str(m20), 0.01, 1e5)]}
    m_e4, m_e4u, m_e4q = out / "S01_first_E4.edi", out / "S01_union_E4.edi", out / "S01_first_E4_quiet.edi"
    status, text, err = quiet(module.merge_files, m_e4, {**e4, "grid": "first"})
    status_u, text_u, err_u = quiet(module.merge_files, m_e4u, e4)
    original = module.lost_values
    module.lost_values = lambda *args, **kwargs: {}
    try:
        status_q, _text_q, err_q = quiet(module.merge_files, m_e4q, {**e4, "grid": "first"})
    finally:
        module.lost_values = original
    assert status == status_u == status_q == 0, (err, err_u, err_q)
    last_m = p_m20[-1:]  # 738.2 s; the grid's 749.9 s is 0.0068 away and beyond M20's reach, 562.3 s 0.12 away

    def lost_fail(text: str, path: Path, want: dict) -> list[str]:
        side = sidecar(path)["merge"]
        found = [ln for ln in text.splitlines() if ln.startswith("WARNING grid first: mode")]
        wanted = [f"WARNING grid first: mode {mode}: {len(v)} left-out period(s) with no grid period within "
                  f"{CLOSE} in log10 period holding a value: {', '.join(f'{q:.4g}' for q in v)} s"
                  for mode, v in want.items()]
        fails = [] if found == wanted else [f"WARNING lines {found}, not {wanted}"]
        if set(side["lost"]) != set(want):
            fails.append(f"lost {side['lost']}, not {want}")
        for mode, v in want.items():
            fails += periods_fail(side["lost"].get(mode, []), v)
        return fails

    def on_lattice_fail(path: Path, name: str) -> list[str]:
        sources = [Path(p).name for p in sidecar(path)["merge"]["lattice"]["sources"]]
        return [] if sources == ["A.edi", name] else [f"lattice sources {sources}"]

    fails = lost_fail(text, m_e4, {"yx": last_m}) + lost_fail(text_u, m_e4u, {}) + on_lattice_fail(m_e4, "M20.edi")
    if data_section(m_e4) != data_section(m_e4q):
        fails.append("the bytes from >FREQ on change with the lost list disabled")
    assert not fails, fails
    print(f"  (24) E4, M20 ({int(on_periods_count(p_m20))} of {p_m20.size} on A's lattice) on the lattice: "
          f"{[ln for ln in text.splitlines() if ln.startswith('WARNING grid first: mode')][0]}; sidecar lost "
          f"{ {k: [round(q, 2) for q in v] for k, v in sidecar(m_e4)['merge']['lost'].items()} }; union lost {{}}; "
          f"{len(data_section(m_e4))} bytes from >FREQ as with the list disabled")
    m_e4a = out / "S01_first_E4_behind.edi"
    rec = {"xy": e4["xy"], "yx": [entry(str(m20), 0.01, 1e5), entry(str(a), 0.01, 1e5)], "grid": "first"}
    status, text_a, err = quiet(module.merge_files, m_e4a, rec)
    assert status == 0 and not lost_fail(text_a, m_e4a, {}), (err, lost_fail(text_a, m_e4a, {}))
    print("      A behind M20 in yx: nothing lost, no WARNING")
    must_fail("738.2 s looked for as lost with A behind M20", lost_fail(text_a, m_e4a, {"yx": last_m}))
    m_e419 = out / "S01_first_E4_M19.edi"
    status, _text, err = quiet(module.merge_files, m_e419, {"xy": e4["xy"], "yx": [entry(str(m19), 0.01, 1e5)],
                                                            "grid": "first"})
    assert status == 0, err
    must_fail("the lattice test on M19 (19 of 40 on)", on_lattice_fail(m_e419, "M19.edi"))


def on_periods_count(periods) -> int:
    """Count the periods that equal one of P8's within 1e-6 in log10 period, computed here."""
    x = np.log10(np.asarray(periods, dtype=float))
    return int((np.abs(x[:, None] - np.log10(P8)[None, :]).min(axis=1) < 1e-6).sum())


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
    test_header(module, b)
    test_grid(module, a, b)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutations:")[0].strip())
    print()
    main()
    print("\nPASS  merge_best_unit")
