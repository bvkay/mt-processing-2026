# -*- coding: utf-8 -*-
"""
Unit test for scripts/merge_modes.py

Two synthetic products of the pair S01 and R01 are written with
mt_metadata's `TF` as EDIs, each with a sidecar in the shape of
process_rr.py's. A (the --xy source, tag "full") holds ten periods from
0.01 to 1000 s and a tipper. B (the --yx source, tag "ey-window", a window
of a few hours) holds four of A's periods, 0.129 to 5.99 s, then 10, 39.8,
158 and 631 s, whose shifted grid puts A's 21.5 and 77.4 s between two of
its periods; its y row at 631 s is NaN, so the EDI holds the EMPTY value
there. Each product is a 1D half-space of its own resistivity (A 100, B
400 ohm-m) with diagonal terms, errors and a location of its own, so every
component and error names its source. The merge runs through the script's
`main` (which calls `merge_files`, the entry scripts/campaign.py uses),
and the merged EDI is read back with mt_metadata.

Usage:
    python tests/merge_modes_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if the merged product's rows do not come from the sources named for them.

**This test fails if** `main` does not return 0, or the merged EDI's periods
differ from A's by more than 1e-6 relative; its x row (Zxx, Zxy) or their
errors differ from A's by more than 1e-5 relative (the EDI holds seven
significant digits); at the four periods A shares with B, its y row (Zyx,
Zyy) or their errors differ from B's by more than 1e-5 relative; at 21.5
and 77.4 s, the y row or its errors differ by more than 1e-5 relative from
the value on the straight line, in log10 period, between B's two
neighbouring periods, computed here on real and imaginary parts
separately; at 0.01, 0.0359, 278 and 1000 s (outside B's usable range,
which ends at 158 s because B's 631 s row is empty), the ZYXR and ZYYR
blocks of the file do not hold the EDI's EMPTY value 1e+32 or mt_metadata
does not read the y row back as 0 with a zero error; the tipper or its
errors differ from A's, or the location differs from A's; the sidecar lacks
local, remote, created (UTC, ending in Z), tag, edi, merge, sources,
forced, mismatches, argv or versions, its merge counts are other than 4
copied, 2 interpolated, 4 NaN and 1 yx period left out, or its sources do
not give A's and B's paths with their sidecars' tags and windows; the
printed lines do not name A for the xy row and B for the yx row; `main`
does not return 2, naming both stations, when B's station id is S02, or
naming both remotes when B's sidecar names R09; or it does not return 0
with the station mismatch under --force, recorded in the sidecar.

The mutation: with the script's `row_of` giving the other row of the TF it
is asked for, the shared-period criterion trips (the y row holds B's Zxx
and Zxy) and the x-row criterion still passes; the test checks both, so
the shared-period criterion is shown able to fail.
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

SCRIPT = REPO / "scripts" / "merge_modes.py"
SCRATCH = scratch_dir("merge_modes_unit")
RTOL = 1e-5
EMPTY = 1.0e32

P_A = np.logspace(-2, 3, 10)
P_B = np.concatenate([P_A[2:6], 10.0 ** np.array([1.0, 1.6, 2.2, 2.8])])
SHARED = [2, 3, 4, 5]  # A's indices on B's grid
BETWEEN = {6: (4, 5), 7: (5, 6)}  # A's index: B's neighbouring indices
OUTSIDE = [0, 1, 8, 9]
B_EMPTY = 7  # B's index whose y row is NaN

# per product: resistivity, Zxx and Zyy as fractions of Zxy, error fractions [[xx, xy], [yx, yy]], location
PRODUCTS = {
    "A": dict(rho=100.0, dxx=0.10 * np.exp(0.3j), dyy=0.05 * np.exp(-0.2j),
              err=[[0.01, 0.05], [0.06, 0.02]], lat=-30.25, lon=139.22),
    "B": dict(rho=400.0, dxx=0.20 * np.exp(0.9j), dyy=-0.15 * np.exp(-0.4j),
              err=[[0.03, 0.08], [0.09, 0.04]], lat=-31.50, lon=140.10),
}
TIPPER = np.array([0.12 + 0.05j, -0.08 + 0.03j])
TIPPER_ERR = np.array([0.011, 0.023])
SIDECARS = {
    "A": dict(local="S01", remote="R01", tag="full", window={"start": None, "end": None},
              masks=["S01 cluster 3"], mask_origins=["cluster"], masks_ignored=False),
    "B": dict(local="S01", remote="R01", tag="ey-window",
              window={"start": "2023-09-27T05:10:00+00:00", "end": "2023-09-27T09:16:00+00:00"},
              masks=[], mask_origins=None, masks_ignored=False),
}
SIDECAR_KEYS = {"local", "remote", "created", "tag", "edi", "merge", "sources", "forced", "mismatches", "argv",
                "versions"}


def load_script():
    """Import scripts/merge_modes.py as a module."""
    spec = importlib.util.spec_from_file_location("merge_modes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def half_space(periods: np.ndarray, rho: float) -> np.ndarray:
    """Return a half-space Zxy in mV/km/nT: |Z| = sqrt(rho / (0.2 T)), phase 45 deg."""
    return np.sqrt(rho / (0.2 * periods)) * np.exp(0.25j * np.pi)


def write_product(name: str, periods: np.ndarray, station: str = "S01", remote: str = "R01",
                  tipper: bool = False, empty_y: int | None = None) -> Path:
    """Write one product's EDI and sidecar under SCRATCH; return the EDI path."""
    spec = PRODUCTS[name[0]]
    zh = half_space(periods, spec["rho"])
    z = np.empty((periods.size, 2, 2), dtype=complex)
    z[:, 0, 0], z[:, 0, 1] = spec["dxx"] * zh, zh
    z[:, 1, 0], z[:, 1, 1] = -zh, spec["dyy"] * zh
    err = np.asarray(spec["err"])[None, :, :] * np.abs(zh)[:, None, None]
    if empty_y is not None:
        z[empty_y, 1, :], err[empty_y, 1, :] = np.nan, np.nan
    tf = TF()
    tf.station_metadata.id = station
    tf.survey_metadata.id = "merge_unit"
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
    side = dict(SIDECARS[name[0]], local=station, remote=remote, edi=edi.name)
    edi.with_suffix(".json").write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
    return edi


def read(path: Path) -> TF:
    """Read an EDI with mt_metadata."""
    tf = TF(fn=str(path))
    tf.read()
    return tf


def arrays(tf: TF) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a TF's periods, impedance and impedance errors as arrays."""
    return (np.asarray(tf.period, dtype=float), np.asarray(tf.impedance.data),
            np.asarray(tf.impedance_error.data, dtype=float))


def close(got, want) -> bool:
    """True when every value is within RTOL of the wanted one, relative to the wanted value's size."""
    got, want = np.asarray(got), np.asarray(want)
    return bool(np.all(np.abs(got - want) <= RTOL * np.abs(want)))


def edi_block(path: Path, key: str) -> np.ndarray:
    """Return the numbers of one data block of an EDI file, e.g. "ZYXR"."""
    text = path.read_text(encoding="utf-8")
    body = re.search(rf"^>{key} [^\n]*\n(.*?)(?=^>)", text, flags=re.S | re.M).group(1)
    return np.array([float(v) for v in body.split()])


def at(periods: np.ndarray, period: float) -> int:
    """Return the index of `period` in `periods`, matched within 1e-6 in log10 period."""
    gap = np.abs(np.log10(periods) - np.log10(period))
    assert gap.min() < 1e-6, (period, periods)
    return int(gap.argmin())


def row_failures(merged: Path, a: Path, b: Path) -> dict[str, list[str]]:
    """Check each merged row against the source named for it; return the failures per criterion."""
    fails = {"periods": [], "x row": [], "shared": [], "interpolated": [], "nan": [], "tipper": []}
    p_m, z_m, e_m = arrays(read(merged))
    p_a, z_a, e_a = arrays(read(a))
    p_b, z_b, e_b = arrays(read(b))
    if p_m.size != p_a.size or not np.allclose(p_m, p_a, rtol=1e-6, atol=0):
        fails["periods"].append(f"merged periods {p_m} are not A's {p_a}")
        return fails
    if not (close(z_m[:, 0, :], z_a[:, 0, :]) and close(e_m[:, 0, :], e_a[:, 0, :])):
        fails["x row"].append("x row or its errors differ from A's")
    for i in SHARED:
        k = at(p_b, p_a[i])
        if not (close(z_m[i, 1, :], z_b[k, 1, :]) and close(e_m[i, 1, :], e_b[k, 1, :])):
            fails["shared"].append(f"{p_a[i]:.4g} s: y row {z_m[i, 1, :]} is not B's {z_b[k, 1, :]}")
    for i, (j0, j1) in BETWEEN.items():
        k0, k1 = at(p_b, P_B[j0]), at(p_b, P_B[j1])
        x, x0, x1 = np.log10(p_a[i]), np.log10(p_b[k0]), np.log10(p_b[k1])
        w = (x - x0) / (x1 - x0)
        line_re = (1 - w) * z_b[k0, 1, :].real + w * z_b[k1, 1, :].real
        line_im = (1 - w) * z_b[k0, 1, :].imag + w * z_b[k1, 1, :].imag
        line_e = (1 - w) * e_b[k0, 1, :] + w * e_b[k1, 1, :]
        if not (close(z_m[i, 1, :], line_re + 1j * line_im) and close(e_m[i, 1, :], line_e)):
            fails["interpolated"].append(f"{p_a[i]:.4g} s: y row {z_m[i, 1, :]}, line {line_re + 1j * line_im}")
    raw = {key: edi_block(merged, key) for key in ("ZYXR", "ZYYR", "FREQ")}
    for i in OUTSIDE:
        k = at(1.0 / raw["FREQ"], p_a[i])  # the file's own order of periods
        stored = [float(raw[key][k]) for key in ("ZYXR", "ZYYR")]
        if stored != [EMPTY, EMPTY] or np.any(z_m[i, 1, :] != 0) or np.any(e_m[i, 1, :] != 0):
            fails["nan"].append(f"{p_a[i]:.4g} s: file {stored}, read {z_m[i, 1, :]} +- {e_m[i, 1, :]}")
    tf_m, tf_a = read(merged), read(a)
    if not (tf_m.has_tipper() and close(np.asarray(tf_m.tipper.data), np.asarray(tf_a.tipper.data))
            and close(np.asarray(tf_m.tipper_error.data), np.asarray(tf_a.tipper_error.data))):
        fails["tipper"].append("tipper or its errors differ from A's")
    return fails


def run(module, *argv: str) -> tuple[int, str, str]:
    """Run the script's main with captured output; return (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = module.main(list(argv))
    return status, out.getvalue(), err.getvalue()


def main() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    a = write_product("A", P_A, tipper=True)
    b = write_product("B", P_B, empty_y=B_EMPTY)
    module = load_script()

    merged = SCRATCH / "out" / "S01_merged.edi"
    status, out, err = run(module, str(merged), "--xy", str(a), "--yx", str(b), "--tag", "xy-full_yx-window")
    assert status == 0, f"exit {status}\n{out}\n{err}"
    print("\n".join(f"  | {line}" for line in out.splitlines()))
    lines = out.splitlines()
    assert any(ln.startswith("xy row") and a.name in ln and "tipper" in ln for ln in lines), out
    assert any(ln.startswith("yx row") and b.name in ln and "2 interpolated" in ln for ln in lines), out

    fails = row_failures(merged, a, b)
    assert not any(fails.values()), fails
    tf_m = read(merged)
    loc = tf_m.station_metadata.location
    where = (loc.latitude, loc.longitude)
    assert where == (PRODUCTS["A"]["lat"], PRODUCTS["A"]["lon"]), where
    _p, z_m, _e = arrays(tf_m)
    print(f"  x row = A's at all 10 periods; y row = B's at {len(SHARED)} shared periods; "
          f"{len(BETWEEN)} on B's log-period line; {len(OUTSIDE)} EMPTY in the file, read as {z_m[0, 1, 0]}")
    print(f"  tipper kept from A; location {loc.latitude}, {loc.longitude} (A's)")

    side = json.loads(merged.with_suffix(".json").read_text(encoding="utf-8"))
    assert SIDECAR_KEYS <= set(side), SIDECAR_KEYS - set(side)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", side["created"]), side["created"]
    counts = {k: side["merge"][k] for k in ("n_periods", "n_copied", "n_interpolated", "n_nan", "yx_left_out")}
    assert counts == dict(n_periods=10, n_copied=4, n_interpolated=2, n_nan=4, yx_left_out=1), counts
    assert side["merge"]["tipper"] == "xy" and side["tag"] == "xy-full_yx-window", (side["merge"], side["tag"])
    assert (side["local"], side["remote"], side["edi"]) == ("S01", "R01", merged.name), side
    for role, src, name in (("xy", a, "A"), ("yx", b, "B")):
        entry = side["sources"][role]
        assert entry["edi"] == str(src) and entry["sidecar"]["path"] == str(src.with_suffix(".json")), entry
        for key in ("tag", "window", "remote", "masks"):
            assert entry["sidecar"][key] == SIDECARS[name][key], (role, key, entry["sidecar"][key])
    print(f"  sidecar: merge {counts}; sources xy tag {side['sources']['xy']['sidecar']['tag']!r}, "
          f"yx tag {side['sources']['yx']['sidecar']['tag']!r} window {side['sources']['yx']['sidecar']['window']}")

    # station and remote mismatches
    b_st = write_product("B_S02", P_B, station="S02")
    status, out, err = run(module, str(SCRATCH / "out" / "st.edi"), "--xy", str(a), "--yx", str(b_st))
    assert status == 2 and "S01" in err and "S02" in err, (status, err)
    assert not (SCRATCH / "out" / "st.edi").exists(), "a refused merge wrote an EDI"
    print(f"  station mismatch: exit 2, {err.strip()}")
    b_rr = write_product("B_R09", P_B, remote="R09")
    status, out, err = run(module, str(SCRATCH / "out" / "rr.edi"), "--xy", str(a), "--yx", str(b_rr))
    assert status == 2 and "R01" in err and "R09" in err, (status, err)
    print(f"  remote mismatch: exit 2, {err.strip()}")
    forced = SCRATCH / "out" / "forced.edi"
    status, out, err = run(module, str(forced), "--xy", str(a), "--yx", str(b_st), "--force")
    side_f = json.loads(forced.with_suffix(".json").read_text(encoding="utf-8"))
    assert status == 0 and side_f["forced"] and "S02" in side_f["mismatches"][0], (status, err, side_f)
    print(f"  --force: exit 0, sidecar mismatches {side_f['mismatches']}")

    # the mutation: row_of gives the other row
    original = module.row_of
    module.row_of = lambda tf, row: original(tf, 1 - row)
    mutant = SCRATCH / "out" / "mutant.edi"
    status, _out, err = run(module, str(mutant), "--xy", str(a), "--yx", str(b))
    assert status == 0, err
    tripped = row_failures(mutant, a, b)
    assert tripped["shared"] and not tripped["x row"], tripped
    print(f"  mutation row_of(tf, 1 - row): the shared-period criterion trips ({tripped['shared'][0]}), "
          f"the x row still passes")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutation:")[0].strip())
    print()
    main()
    print("\nPASS  merge_modes_unit")
