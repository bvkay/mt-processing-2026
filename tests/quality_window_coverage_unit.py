# -*- coding: utf-8 -*-
"""
Unit test for the window coverage of mt_workbench.quality (scoring.coverage, scoring.min_coverage)

A cross-wave pair whose product stops at 3,649 s can win the choice of remote
(FR09, FR11 and FR15 of SA AusLAMP 2013-2018): its EDI holds 26 periods in the 10-30,000 s scoring window where a
whole-record product holds 35, and the score (either form) is taken over the
periods the EDI holds, so the 9 it lacks are not charged (its coverage is
1.0). The window coverage C_w counts the periods of the window the product's
own band lattice lays out (its log-period step, extended over the window) and
divides the valid ones by that count, so a period absent from the EDI costs as
much as one present without a value.

The smooth TF of tests/quality_coverage_unit.py (0.005-5000 s, 61 periods) is
the reference; twins are written to EDIs and read back:

- TRUNC: the first 30 of the 61 periods only (to 0.47 s; the EDI has no other
  periods, as the cross-wave pair's has none past 3,649 s);
- GAPS: periods 10-21 of both modes empty (in the EDI, without values);
- OUT: the xy phase rotated by -70 deg.

Usage:
    python tests/quality_window_coverage_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) with ``coverage=True`` over the window 0.005-5000 s, TRUNC (31 of 61
    periods missing) does not score at most half of the reference, under the
    quadrant form and under the coverage form, or its window coverage is not
    30/61;
(2) with the key absent (``coverage`` not passed, and False) any of the 18
    overall scores frozen from the code before the change (reference, GAPS,
    OUT; both forms; no window, 0.005-5000 s, 0.1-100 s) moves by more than
    1e-9, or TRUNC's default score is not the plain form's;
(3) the reference's window coverage is not exactly 1 (a whole product must
    not be charged), GAPS's is not 49/61, or with ``coverage=True`` the
    quadrant form is not Q x C_w x S x exp(-5B/N) and the coverage form not
    C_w x S x exp(-5B/N) per mode (to 1e-12), or ``score_form`` does not name
    the window term;
(4) campaign.load_plan does not read ``scoring: {coverage: true,
    min_coverage: 0.8}``, leaves them other than False / 0.0 when absent, or
    accepts ``coverage: "yes"``, ``min_coverage: 1.5`` or ``min_coverage: -0.1``;
(5) campaign.choose_best with ``min_coverage`` 0.8 picks a remote whose window
    coverage is under 0.8 though another passes it, or with 0.0 does not pick
    the top score; or returns a pick when no product passes the floor.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from mt_metadata.transfer_functions.core import TF  # noqa: E402

import quality_coverage_unit as qc  # noqa: E402  (the reference TF and its writer)
from mt_workbench import quality  # noqa: E402
from mt_workbench.products import read_tf, write_edi  # noqa: E402

# the overall scores without the window coverage, frozen
FROZEN = {
    ("ref", True, (None, None)): 0.987460652935,
    ("ref", True, (0.005, 5000.0)): 0.987460652935,
    ("ref", True, (0.1, 100.0)): 0.975508496605,
    ("ref", False, (None, None)): 0.987460652935,
    ("ref", False, (0.005, 5000.0)): 0.987460652935,
    ("ref", False, (0.1, 100.0)): 0.975508496605,
    ("gaps", True, (None, None)): 0.779670599615,
    ("gaps", True, (0.005, 5000.0)): 0.779670599615,
    ("gaps", True, (0.1, 100.0)): 0.718256909841,
    ("gaps", False, (None, None)): 0.779670599615,
    ("gaps", False, (0.005, 5000.0)): 0.779670599615,
    ("gaps", False, (0.1, 100.0)): 0.718256909841,
    ("out", True, (None, None)): 0.493730326467,
    ("out", True, (0.005, 5000.0)): 0.493730326467,
    ("out", True, (0.1, 100.0)): 0.487754248303,
    ("out", False, (None, None)): 0.987460652186,
    ("out", False, (0.005, 5000.0)): 0.987460652186,
    ("out", False, (0.1, 100.0)): 0.97550849672,
}
KEEP = 30  # TRUNC keeps the first 30 of the 61 periods


def write_trunc(path: Path, z: np.ndarray) -> Path:
    """Write the first KEEP periods of an impedance to an EDI (no other periods) and return the path."""
    tf = TF()
    tf.station_metadata.id = "Q001"
    tf.station_metadata.location.latitude = -41.0
    tf.station_metadata.location.longitude = 145.0
    tf.period = qc.PERIOD[:KEEP]
    tf.impedance = z[:KEEP]
    tf.impedance_error = np.abs(z[:KEEP]) * 0.05 + 1e-6
    write_edi(tf, path)
    read_tf(path)
    return path


def main() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z0 = qc.smooth_z()
        gaps = z0.copy()
        gaps[10:22] = np.nan
        out = z0.copy()
        out[:, 0, 1] *= np.exp(-1j * np.radians(70))
        paths = {"ref": qc.write(tmp / "ref.edi", z0), "gaps": qc.write(tmp / "gaps.edi", gaps),
                 "out": qc.write(tmp / "out.edi", out), "trunc": write_trunc(tmp / "trunc.edi", z0)}
        win = (0.005, 5000.0)

        # (1) TRUNC under the window term
        for qt in (True, False):
            form = quality.SCORE_FORMS[qt]
            try:
                r = quality.tf_quality(paths["ref"], *win, quadrant_term=qt, coverage=True)
                t = quality.tf_quality(paths["trunc"], *win, quadrant_term=qt, coverage=True)
            except TypeError as exc:
                fails.append(f"(1) {form}: {exc}")
                continue
            rs, ts = r["overall"]["score"], t["overall"]["score"]
            print(f"(1) {form}: reference {rs:.4f}, TRUNC {ts:.4f} (ratio {ts / rs:.3f}; window coverage "
                  f"{t['overall']['window_coverage']:.4f})")
            if not ts <= 0.5 * rs:
                fails.append(f"(1) {form}: TRUNC {ts:.4f} above half the reference {rs:.4f}")
            for m in ("xy", "yx"):
                if abs(t[m]["window_coverage"] - KEEP / 61) > 1e-12:
                    fails.append(f"(1) TRUNC {m} window coverage {t[m]['window_coverage']}, not {KEEP}/61")

        # (2) the key absent: the frozen numbers
        moved = 0
        for (name, qt, w), want in FROZEN.items():
            for kw in ({}, {"coverage": False}):
                try:
                    got = quality.tf_quality(paths[name], *w, quadrant_term=qt, **kw)["overall"]["score"]
                except TypeError as exc:
                    got = f"TypeError: {exc}"
                if isinstance(got, str) or abs(got - want) > 1e-9:
                    moved += 1
                    fails.append(f"(2) {name} quadrant_term={qt} window={w} {kw}: {got!r}, frozen {want!r}")
        print(f"(2) frozen scores: {2 * len(FROZEN) - moved} of {2 * len(FROZEN)} unchanged")
        for qt in (True, False):
            a = quality.tf_quality(paths["trunc"], *win, quadrant_term=qt)
            if abs(a["overall"]["score"] - a["overall"][f"score_{quality.SCORE_FORMS[qt]}"]) > 1e-12:
                fails.append(f"(2) TRUNC {qt}: the default score is not the plain form's")
        a = quality.tf_quality(paths["trunc"], *win)
        print(f"(2) TRUNC without the key: {a['overall']['score']:.4f} (coverage {a['overall']['coverage']:.3f}, "
              f"its missing periods not charged)")

        # (3) the factors
        try:
            rw = quality.tf_quality(paths["ref"], *win, coverage=True)
            gw = quality.tf_quality(paths["gaps"], *win, coverage=True)
            print(f"(3) window coverage: reference {rw['overall']['window_coverage']!r}, GAPS xy "
                  f"{gw['xy']['window_coverage']:.4f}")
            if rw["overall"]["window_coverage"] != 1.0:
                fails.append(f"(3) reference window coverage {rw['overall']['window_coverage']!r}, not 1")
            if abs(gw["xy"]["window_coverage"] - 49 / 61) > 1e-12:
                fails.append(f"(3) GAPS xy window coverage {gw['xy']['window_coverage']}, not 49/61")
            for name in ("ref", "gaps", "out", "trunc"):
                for qt in (True, False):
                    res = quality.tf_quality(paths[name], *win, quadrant_term=qt, coverage=True)
                    want_form = f"{quality.SCORE_FORMS[qt]}+window"
                    if res["score_form"] != want_form:
                        fails.append(f"(3) {name}: score_form {res['score_form']!r}, not {want_form!r}")
                    n = res["n_periods"]
                    for m in ("xy", "yx"):
                        d = res[m]
                        first = d["quadrant_frac"] * d["window_coverage"] if qt else d["window_coverage"]
                        want = quality.combined_score(first, d["smoothness"], d["blowups"], n)
                        if abs(d["score"] - want) > 1e-12:
                            fails.append(f"(3) {name} {m} quadrant_term={qt}: score {d['score']} not {want}")
        except (TypeError, KeyError) as exc:
            fails.append(f"(3) {type(exc).__name__}: {exc}")

        # (4) the plan keys
        import campaign as cp

        base = {"name": "syn", "sites": ["A", "B"], "groups": {"G": ["A", "B"]},
                "stages": {"variants": {}, "remotes": {}, "stacks": {"weightings": {"u": "none"}}, "options": {}}}
        cases = (({}, (False, 0.0)), ({"coverage": True, "min_coverage": 0.8}, (True, 0.8)),
                 ({"coverage": True}, (True, 0.0)), ({"coverage": "yes"}, "error"),
                 ({"coverage": True, "min_coverage": 1.5}, "error"), ({"min_coverage": -0.1}, "error"))
        for keys, want in cases:
            raw = dict(base)
            raw["scoring"] = {"pmin": 10.0, "pmax": 10000.0, **keys}
            path = tmp / "plan.yaml"
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            try:
                plan = cp.load_plan(path)
                got = (plan.coverage, plan.min_coverage)
            except ValueError:
                got = "error"
            except AttributeError as exc:
                got = f"AttributeError: {exc}"
            print(f"(4) scoring {keys}: {got}")
            if got != want:
                fails.append(f"(4) scoring {keys}: got {got!r}, wanted {want!r}")

        # (5) the floor in the choice
        s1 = pd.DataFrame([
            {"remote": "X", "score": 0.95, "edi": "x.edi", "overall_window_coverage": 0.74},
            {"remote": "Y", "score": 0.85, "edi": "y.edi", "overall_window_coverage": 1.0},
        ])
        for floor, want in ((0.8, "Y"), (0.0, "X"), (0.99, "Y")):
            try:
                got = (cp.choose_best(s1, 0.02, min_coverage=floor) or {}).get("remote")
            except TypeError as exc:
                got = f"TypeError: {exc}"
            print(f"(5) min_coverage {floor}: {got}")
            if got != want:
                fails.append(f"(5) min_coverage {floor}: picked {got!r}, wanted {want!r}")
        try:
            none = cp.choose_best(s1, 0.02, min_coverage=1.005)
        except TypeError as exc:
            none = f"TypeError: {exc}"
        if none is not None:
            fails.append(f"(5) no product passes min_coverage 1.005, yet the pick is {none!r}")
    for line in fails:
        print(f"FAIL: {line}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
