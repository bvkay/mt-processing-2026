# -*- coding: utf-8 -*-
"""
Unit test for scripts/merge_windows.py (the merge of a short-window and a long-window product by period)

Synthetic products of station S01 are written with mt_metadata's `TF` as EDIs, each with a sidecar in the shape of
process_rr.py's, on one aurora-like lattice: 42 periods 4 x 10**(0.05 + 0.1 k), 4.49 to 56,502 s. A (the short
source, the 256/75 % window's stand-in) is a 100 ohm-m half-space with its own diagonal terms, relative impedance
error 0.005 and tipper TA; B (the long source, the default window's) 400 ohm-m with other diagonals, error 0.01 and
tipper TB, so every component names its source. AY is A at 25 ohm-m (a yx source of its own); ACUT is A with
every row and the tipper EMPTY above 1,000 s (a short source that stops early); AERR is A whose error is 0.005 up
to 2,000 s and 0.05 above, against B's 0.01, so the "longest" and "contiguous" rules have one answer.

Usage:
    python tests/merge_windows_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** (1) a merge of A (short) and B (long) under the rule fixed:2000 does not return 0, its
periods are not the lattice's 42, or at any period up to 2,000 s the x row, the y row, the tipper or any of their
errors differs by more than 1e-5 relative from A's, or above 2,000 s from B's; (2) the sidecar's `window_merge`
block does not give the rule "fixed:2000", the crossover 2000 s for xy, yx and the tipper, and A as the short and B
as the long source of each, or the EDI's INFO block lacks a line naming the crossover of each mode and lines
naming A and B; (3) the mutation: the same comparison run on the merge with the sources swapped (B short, A long)
finds no failure below 2,000 s or none above (so (1) can fail); (4) with ACUT short under fixed:2000 the crossover
is not ACUT's last populated period (895.5 s, the ceiling) for every mode, a period of the lattice is EMPTY in the
merged x row, y row or tipper, or the rows above 895.5 s are not B's; (5) with A short for xy and AY short for yx
the y row up to 2,000 s is not AY's, or the x row is not A's; (6) with AERR short and B long, the rule
longest:1000 does not give 1,786.7 s (the last lattice period up to 2,000 s, where AERR's error 0.005 <= B's 0.01;
above it 0.05 > 0.01), longest:5000 does not give 5,000 s (the floor wins over the data), contiguous:1000 does not
give 1,786.7 s; (7) with a health
window given for xy ("2013-09-22 01:00:10 to 2013-09-29 01:00:00 UTC") the INFO block and the sidecar lack it;
(8) a rule string other than fixed:<s>, longest:<floor s> or contiguous:<floor s> is accepted (exit 2 wanted);
(9) the short end (`merge_shortend`): with S, a 10 Hz stand-in on its own lattice 0.2 x 10**(0.05 + 0.1 k) to
3,170 s, equal to L (= A's model on the 1 Hz lattice) times a = 1.1**-0.5 exp(-3 deg i) at every period, and
align qld (factor over 4-3,000 s, sigma 0.1 decade): the full band does not hold S's periods below 4.49 s then L's,
the x and y rows below 4.49 s differ by more than 1e-4 relative from S / a (A's model at those periods, errors
likewise scaled by 1/|a|), the tipper below 4.49 s is not S's unscaled, or the rows from 4.49 s are not L's;
(10) with align none the rows below 4.49 s are not S's raw, and the sidecar's `shortend` record does not give the
align mode, the band, sigma and the factor's level (1.1**0.5 = 1.0488 within 1e-4) and phase (+3 deg within
1e-3) per mode for qld; (11) the mutation: the qld rows compared against S x a (the factor inverted) find no failure.

The mutation of (3) is run by the test itself on every run.
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

SCRIPT = REPO / "scripts" / "merge_windows.py"
SCRATCH = scratch_dir("merge_windows_unit")
RTOL = 1e-5
EMPTY = 1.0e32
P = 4.0 * 10.0 ** (0.05 + 0.1 * np.arange(42))  # 4.49 .. 56,502 s, the 1 Hz family's aurora lattice
PRODUCTS = {
    "A": dict(rho=100.0, dxx=0.10 * np.exp(0.3j), dyy=0.05 * np.exp(-0.2j), rel=0.005, remote="R01", tag="qld256",
              tip=np.array([0.12 + 0.05j, -0.08 + 0.03j])),
    "B": dict(rho=400.0, dxx=0.20 * np.exp(0.9j), dyy=-0.15 * np.exp(-0.4j), rel=0.01, remote="R01", tag="default",
              tip=np.array([0.30 - 0.10j, 0.05 + 0.02j])),
    "AY": dict(rho=25.0, dxx=0.30 * np.exp(-0.5j), dyy=0.25 * np.exp(0.6j), rel=0.005, remote="R01", tag="qld256yx",
               tip=np.array([0.12 + 0.05j, -0.08 + 0.03j])),
}
FAILS: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


def write_product(name: str, base: str, cut: float | None = None, rel_above: tuple[float, float] | None = None) -> Path:
    """Write one product's EDI and sidecar; `cut` empties every row above it, `rel_above` (T, rel) sets the error."""
    spec = PRODUCTS[base]
    zh = np.sqrt(spec["rho"] / (0.2 * P)) * np.exp(0.25j * np.pi)
    z = np.empty((P.size, 2, 2), dtype=complex)
    z[:, 0, 0], z[:, 0, 1] = spec["dxx"] * zh, zh
    z[:, 1, 0], z[:, 1, 1] = -zh, spec["dyy"] * zh
    rel = np.full(P.size, spec["rel"])
    if rel_above is not None:
        rel[P > rel_above[0]] = rel_above[1]
    err = (rel * np.abs(zh))[:, None, None] * np.ones((1, 2, 2))
    tip = np.tile(spec["tip"], (P.size, 1))
    tip_err = np.tile(np.abs(spec["tip"]) * rel[:, None].mean(), (P.size, 1)) * rel[:, None] / rel.mean()
    if cut is not None:
        far = P > cut
        z[far], err[far], tip[far], tip_err[far] = np.nan, np.nan, np.nan, np.nan
    tf = TF()
    tf.station_metadata.id = "S01"
    tf.survey_metadata.id = "merge_windows_unit"
    tf.station_metadata.location.latitude = -31.0
    tf.station_metadata.location.longitude = 138.6
    tf.period = P
    tf.impedance = z
    tf.impedance_error = err
    tf.tipper = tip[:, None, :]
    tf.tipper_error = tip_err[:, None, :]
    edi = SCRATCH / f"{name}.edi"
    tf.write(fn=str(edi), file_type="edi")
    side = dict(local="S01", remote=spec["remote"], tag=spec["tag"], window={"start": None, "end": None}, masks=[],
                edi=edi.name)
    edi.with_suffix(".json").write_text(json.dumps(side, indent=2) + "\n", encoding="utf-8")
    return edi


def load_script():
    spec = importlib.util.spec_from_file_location("merge_windows", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path: Path):
    tf = TF(fn=str(path))
    tf.read()
    t = np.asarray(tf.tipper.data)[:, 0, :] if tf.has_tipper() else None
    te = np.asarray(tf.tipper_error.data, dtype=float)[:, 0, :] if tf.has_tipper() else None
    return (np.asarray(tf.period, dtype=float), np.asarray(tf.impedance.data),
            np.asarray(tf.impedance_error.data, dtype=float), t, te)


def at(periods, period) -> int:
    gap = np.abs(np.log10(periods) - np.log10(period))
    assert gap.min() < 1e-6, (period, periods)
    return int(gap.argmin())


def close(got, want) -> bool:
    got, want = np.asarray(got), np.asarray(want)
    return bool(np.all(np.isfinite(got)) and np.all(np.abs(got - want) <= RTOL * np.abs(want)))


def compare(merged: Path, sources: dict, periods) -> list[str]:
    """Rows of the merged EDI against a source per part at the given periods; return the failures.

    `sources` maps "x", "y", "t" to the EDI whose row (x row, y row, tipper) the merged one must equal.
    """
    pm, zm, em, tm, tme = read(merged)
    got = {k: read(v) for k, v in sources.items()}
    fails = []
    for p in periods:
        i = at(pm, p)
        for part, row in (("x", 0), ("y", 1)):
            ps, zs, es, _t, _te = got[part]
            k = at(ps, p)
            if not (close(zm[i, row], zs[k, row]) and close(em[i, row], es[k, row])):
                fails.append(f"{part} row at {p:.4g} s is not {sources[part].name}'s")
        ps, _z, _e, ts, tse = got["t"]
        k = at(ps, p)
        if not (close(tm[i], ts[k]) and close(tme[i], tse[k])):
            fails.append(f"tipper at {p:.4g} s is not {sources['t'].name}'s")
    return fails


def quiet(func, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = func(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


def info_block(path: Path) -> str:
    text = path.read_text(encoding="latin-1")
    return re.search(r"^>INFO[^\n]*\n(.*?)(?=^>)", text, re.S | re.M).group(1)


def sidecar(path: Path) -> dict:
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))


def merge(module, name: str, short: dict, long: dict, rule: str, **kw):
    out = SCRATCH / f"{name}.edi"
    status, so, se = quiet(module.merge_windows, out, short, long, rule, site="S01", **kw)
    return status, out, so + se


P10 = 0.2 * 10.0 ** (0.05 + 0.1 * np.arange(42))  # 0.224 .. 3,170 s, the 10 Hz family's lattice
ALPHA = 1.1 ** -0.5 * np.exp(-1j * np.radians(3.0))


def write_s(name: str, factor: complex) -> Path:
    """Write A's model on the 10 Hz lattice times `factor` (impedance and errors; the tipper unscaled)."""
    spec = PRODUCTS["A"]
    zh = np.sqrt(spec["rho"] / (0.2 * P10)) * np.exp(0.25j * np.pi)
    z = np.empty((P10.size, 2, 2), dtype=complex)
    z[:, 0, 0], z[:, 0, 1], z[:, 1, 0], z[:, 1, 1] = spec["dxx"] * zh, zh, -zh, spec["dyy"] * zh
    err = (spec["rel"] * np.abs(zh))[:, None, None] * np.ones((1, 2, 2))
    tf = TF()
    tf.station_metadata.id = "S01"
    tf.survey_metadata.id = "merge_windows_unit"
    tf.station_metadata.location.latitude = -31.0
    tf.station_metadata.location.longitude = 138.6
    tf.period = P10
    tf.impedance = z * factor
    tf.impedance_error = err * abs(factor)
    tf.tipper = np.tile(np.array([0.2 + 0.1j, -0.1 + 0.05j]), (P10.size, 1))[:, None, :]
    tf.tipper_error = np.full((P10.size, 1, 2), 0.004)
    edi = SCRATCH / f"{name}.edi"
    tf.write(fn=str(edi), file_type="edi")
    edi.with_suffix(".json").write_text(json.dumps({"local": "S01", "remote": "R10", "tag": name}), encoding="utf-8")
    return edi


def rows_vs(merged: Path, ref: Path, factor: complex, periods) -> list[str]:
    """The merged x/y rows (and errors) against `ref`'s times `factor` (errors |factor|) at the given periods."""
    pm, zm, em, _t, _te = read(merged)
    pr, zr, er, _t2, _te2 = read(ref)
    fails = []
    for p in periods:
        i, k = at(pm, p), at(pr, p)
        for row in (0, 1):
            if not (np.all(np.abs(zm[i, row] - zr[k, row] * factor) <= 1e-4 * np.abs(zr[k, row] * factor))
                    and np.all(np.abs(em[i, row] - er[k, row] * abs(factor)) <= 1e-4 * np.abs(er[k, row] * abs(factor)))):
                fails.append(f"row {row} at {p:.4g} s")
    return fails


def test_shortend(module, a: Path) -> None:
    print("(9)-(11) the 10 Hz short end aligned onto the long product")
    s = write_s("S", ALPHA)
    below = P10[P10 < P[0] * (1 - 1e-6)]
    out = SCRATCH / "FULL.edi"
    status, so, se = quiet(module.merge_shortend, out, s, a, align="qld", site="S01")
    check(status == 0, "(9) exit 0", (so + se).strip().splitlines()[-1] if (so + se).strip() else "")
    if status != 0:
        return
    pm = read(out)[0]
    want = np.concatenate([below, P])
    check(pm.size == want.size and np.allclose(pm, want, rtol=1e-6), "(9) S's periods below 4.49 s, then L's",
          f"{pm.size} periods vs {want.size}")
    f = rows_vs(out, s, 1 / ALPHA, below)
    check(not f, "(9) rows below 4.49 s = S / a (aligned)", "; ".join(f[:3]))
    _p, _z, _e, tm, _te = read(out)
    _ps, _zs, _es, ts, _tse = read(s)
    check(np.allclose(tm[:below.size], ts[:below.size], rtol=1e-5), "(9) tipper below 4.49 s = S's, unscaled")
    f = compare(out, {"x": a, "y": a, "t": a}, P)
    check(not f, "(9) rows from 4.49 s = L's", "; ".join(f[:3]))
    rec = sidecar(out).get("shortend", {})
    fac = rec.get("factor", {})
    ok = (rec.get("align") == "qld" and list(rec.get("band_s", [])) == [4.0, 3000.0] and abs(rec.get("sigma_dex", 0) - 0.1) < 1e-12
          and all(abs(fac.get(m, {}).get("level_median", 0) - 1.1 ** 0.5) < 1e-4 and
                  abs(fac.get(m, {}).get("phase_median_deg", 0) - 3.0) < 1e-3 for m in ("xy", "yx")))
    check(ok, "(10) sidecar shortend record (align, band, sigma, factor 1.0488 / +3 deg per mode)", json.dumps(rec)[:240])
    f = rows_vs(out, s, ALPHA, below)
    check(bool(f), "(11) mutation: the factor inverted is caught", f"{len(f)} failures")
    out2 = SCRATCH / "FULL_none.edi"
    status, _so, _se = quiet(module.merge_shortend, out2, s, a, align="none", site="S01")
    f = rows_vs(out2, s, 1.0, below) if status == 0 else ["exit"]
    check(status == 0 and not f, "(10) align none: rows below 4.49 s = S raw", "; ".join(f[:3]))


def main() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    a, b, ay = write_product("A", "A"), write_product("B", "B"), write_product("AY", "AY")
    acut = write_product("ACUT", "A", cut=1000.0)
    aerr = write_product("AERR", "A", rel_above=(2000.0, 0.05))
    module = load_script()
    below, above = P[P <= 2000.0], P[P > 2000.0]
    both = {"xy": a, "yx": a, "tipper": a}
    longs = {"xy": b, "yx": b, "tipper": b}

    print("(1) fixed:2000, A short, B long")
    status, m1, log = merge(module, "M1", both, longs, "fixed:2000")
    check(status == 0, "(1) exit 0", f"status {status}; {log.strip().splitlines()[-1] if log.strip() else ''}")
    if status == 0:
        pm = read(m1)[0]
        check(pm.size == P.size and np.allclose(pm, P, rtol=1e-6), "(1) the lattice's 42 periods", f"{pm.size}")
        f_lo = compare(m1, {"x": a, "y": a, "t": a}, below)
        f_hi = compare(m1, {"x": b, "y": b, "t": b}, above)
        check(not f_lo, "(1) up to 2,000 s = A (x row, y row, tipper, errors)", "; ".join(f_lo[:3]))
        check(not f_hi, "(1) above 2,000 s = B", "; ".join(f_hi[:3]))

        print("(2) sidecar and INFO name both sources and the crossover")
        wm = sidecar(m1).get("window_merge", {})
        cx = wm.get("crossover_s", {})
        check(wm.get("rule") == "fixed:2000", "(2) sidecar rule", repr(wm.get("rule")))
        check(all(abs(float(cx.get(k, -1)) - 2000.0) < 1e-6 for k in ("xy", "yx", "tipper")),
              "(2) sidecar crossover 2000 s per mode", repr(cx))
        src_ok = all(Path(wm.get("short", {}).get(k, "")).name == "A.edi" and
                     Path(wm.get("long", {}).get(k, "")).name == "B.edi" for k in ("xy", "yx", "tipper"))
        check(src_ok, "(2) sidecar short = A, long = B per mode", repr({k: wm.get(k) for k in ("short", "long")}))
        info = info_block(m1)
        cross_lines = [k for k in ("xy", "yx", "tipper") if re.search(rf"window_merge_crossover_{k}=2000\b", info)]
        check(len(cross_lines) == 3, "(2) INFO crossover line per mode", f"found {cross_lines}")
        check("A.edi" in info and "B.edi" in info, "(2) INFO names A and B")

    print("(3) mutation: sources swapped, the same comparison must fail")
    status, m3, _ = merge(module, "M3", longs, both, "fixed:2000")
    if status == 0:
        f_lo = compare(m3, {"x": a, "y": a, "t": a}, below)
        f_hi = compare(m3, {"x": b, "y": b, "t": b}, above)
        check(bool(f_lo) and bool(f_hi), "(3) swapped merge FAILS the (1) comparison below and above",
              f"{len(f_lo)} failures below, {len(f_hi)} above")
    else:
        check(False, "(3) swapped merge ran", f"status {status}")

    print("(4) ceiling: ACUT stops at 895.5 s")
    status, m4, log = merge(module, "M4", {"xy": acut, "yx": acut, "tipper": acut}, longs, "fixed:2000")
    check(status == 0, "(4) exit 0", log.strip().splitlines()[-1] if log.strip() else "")
    if status == 0:
        last = P[P <= 1000.0][-1]
        cx = sidecar(m4).get("window_merge", {}).get("crossover_s", {})
        check(all(abs(float(cx.get(k, -1)) - last) < 1e-3 * last for k in ("xy", "yx", "tipper")),
              "(4) crossover = ACUT's last populated period per mode", f"{cx} vs {last:.1f}")
        pm, zm, _e, tm, _te = read(m4)
        holes = int((~np.isfinite(zm[:, 0, 1]) | (np.abs(zm[:, 0, 1]) > 1e30)).sum()
                    + (~np.isfinite(zm[:, 1, 0]) | (np.abs(zm[:, 1, 0]) > 1e30)).sum()
                    + (~np.isfinite(tm[:, 0]) | (np.abs(tm[:, 0]) > 1e30)).sum())
        check(pm.size == P.size and holes == 0, "(4) no EMPTY period in the merged rows", f"{pm.size} periods, {holes} empty")
        f_hi = compare(m4, {"x": b, "y": b, "t": b}, P[P > last])
        f_lo = compare(m4, {"x": acut, "y": acut, "t": acut}, P[P <= last])
        check(not f_hi and not f_lo, "(4) ACUT up to 895.5 s, B above", "; ".join((f_lo + f_hi)[:3]))

    print("(5) per-mode short sources: xy A, yx AY")
    status, m5, _ = merge(module, "M5", {"xy": a, "yx": ay, "tipper": a}, longs, "fixed:2000")
    if status == 0:
        f = compare(m5, {"x": a, "y": ay, "t": a}, below)
        check(not f, "(5) x row A, y row AY up to 2,000 s", "; ".join(f[:3]))
    else:
        check(False, "(5) exit 0", f"status {status}")

    print("(6) data rules on AERR (0.005 to 2,000 s, 0.05 above) against B (0.01)")
    want_long = P[P <= 2000.0][-1]
    want_floor = 5000.0
    for rule, want in (("longest:1000", want_long), ("longest:5000", want_floor), ("contiguous:1000", want_long)):
        status, m6, _ = merge(module, f"M6_{rule.replace(':', '_')}", {"xy": aerr, "yx": aerr, "tipper": aerr}, longs, rule)
        cx = sidecar(m6).get("window_merge", {}).get("crossover_s", {}) if status == 0 else {}
        got = cx.get("xy")
        check(status == 0 and got is not None and abs(float(got) - want) < 1e-3 * want, f"(6) {rule} -> {want:.1f} s",
              f"status {status}, got {got}")

    print("(7) health window recorded")
    win = {"xy": "2013-09-22 01:00:10 to 2013-09-29 01:00:00 UTC"}
    status, m7, _ = merge(module, "M7", both, longs, "fixed:2000", windows=win)
    if status == 0:
        check(win["xy"] in info_block(m7) and sidecar(m7).get("window_merge", {}).get("windows", {}).get("xy") == win["xy"],
              "(7) the xy window in INFO and the sidecar")
    else:
        check(False, "(7) exit 0", f"status {status}")

    test_shortend(module, a)

    print("(8) bad rule strings refused")
    for bad in ("2000", "fixed:", "longest:x", "median:1000", "fixed:-5"):
        status, _m, _ = merge(module, "M8", both, longs, bad)
        check(status == 2, f"(8) rule {bad!r} refused with exit 2", f"status {status}")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].split("The mutation of (3)")[0].strip())
    print()
    try:
        main()
    except Exception as exc:  # a missing script or API counts as a failure, reported
        FAILS.append(f"exception {type(exc).__name__}: {exc}")
        print(f"  FAIL exception {type(exc).__name__}: {exc}")
    print(f"\nFAIL ({len(FAILS)})  merge_windows_unit" if FAILS else "\nPASS  merge_windows_unit")
    sys.exit(1 if FAILS else 0)
