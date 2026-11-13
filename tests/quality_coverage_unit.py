# -*- coding: utf-8 -*-
"""
Unit test for the coverage form of mt_workbench.quality's score and the campaign plan key scoring.quadrant_term

The smooth TF of tests/quality_unit.py (0.005-5000 s, 61 periods, both modes
in their physical quadrants, 5 % errors) is the reference. Twins of it are
written to EDIs through mt_metadata and read back, as the campaign scores
aurora's products:

- OUT: the xy row's phase rotated by -70 deg at every period (|Z| and so rho
  unchanged; the phase leaves the 0-90 deg quadrant at most periods);
- GAPS: 12 of the 61 periods of both modes EMPTY (no value).

Usage:
    python tests/quality_coverage_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) under the coverage form (``quadrant_term=False``) OUT does not score the
    same as the reference (to 1e-9), or under the quadrant form (the default)
    it does not score lower by more than 0.3 (its xy quadrant fraction falls);
(2) GAPS does not score lower than the reference under the coverage form (its
    coverage under 1), or its xy coverage is not 49/61;
(3) `tf_quality` does not report both ``score_quadrant`` and
    ``score_coverage`` (per mode and overall), ``score`` is not the selected
    form's, or ``score_form`` does not name it; or the default score differs
    from ``score_quadrant`` (older ledgers must reproduce);
(4) campaign.load_plan does not read ``scoring: {quadrant_term: false}`` as
    False, leaves it True when absent, or accepts a non-boolean value ("no");
(5) the control: a twin whose phase stays inside the quadrant (rotated by -5
    deg) changes the quadrant form's score by more than 0.02 (the phase
    rotation alone must not be what lowers OUT's quadrant score).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mt_workbench import quality  # noqa: E402
from mt_workbench.products import read_tf, write_edi  # noqa: E402

PERIOD = np.logspace(np.log10(0.005), np.log10(5000), 61)


def smooth_z() -> np.ndarray:
    """The reference impedance: log10 rho = 2 + 0.6 tanh(log10 T); xy phase 45 - 12 tanh, yx minus 180."""
    x = np.log10(PERIOD)
    rho = 10 ** (2 + 0.6 * np.tanh(x))
    phi = np.radians(45 - 12 * np.tanh(x))
    amp = np.sqrt(rho / (0.2 * PERIOD))
    z = np.zeros((PERIOD.size, 2, 2), dtype=complex)
    z[:, 0, 1] = amp * np.exp(1j * phi)
    z[:, 1, 0] = amp * np.exp(1j * (phi - np.pi))
    z[:, 0, 0] = 0.05 * amp
    z[:, 1, 1] = -0.05 * amp
    return z


def write(path: Path, z: np.ndarray) -> Path:
    """Write an impedance to an EDI and return the path."""
    tf = TF()
    tf.station_metadata.id = "Q001"
    tf.station_metadata.location.latitude = -41.0
    tf.station_metadata.location.longitude = 145.0
    tf.period = PERIOD
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05 + 1e-6
    write_edi(tf, path)
    read_tf(path)  # the product must read back
    return path


def main() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z0 = smooth_z()
        out = z0.copy()
        out[:, 0, 1] *= np.exp(-1j * np.radians(70))
        ctrl = z0.copy()
        ctrl[:, 0, 1] *= np.exp(-1j * np.radians(5))
        gaps = z0.copy()
        gaps[10:22] = np.nan
        ref_p, out_p, ctrl_p, gaps_p = (write(tmp / f"{n}.edi", z) for n, z in
                                        (("ref", z0), ("out", out), ("ctrl", ctrl), ("gaps", gaps)))
        q = {n: (quality.tf_quality(p), quality.tf_quality(p, quadrant_term=False))
             for n, p in (("ref", ref_p), ("out", out_p), ("ctrl", ctrl_p), ("gaps", gaps_p))}
        rq, rc = q["ref"][0]["overall"]["score"], q["ref"][1]["overall"]["score"]
        oq, oc = q["out"][0]["overall"]["score"], q["out"][1]["overall"]["score"]
        print(f"reference: quadrant {rq:.4f}, coverage {rc:.4f}")
        print(f"OUT:       quadrant {oq:.4f}, coverage {oc:.4f} (xy quadrant fraction "
              f"{q['out'][0]['xy']['quadrant_frac']:.3f})")
        if abs(oc - rc) > 1e-9:
            fails.append(f"(1) coverage form: OUT {oc} differs from the reference {rc}")
        if not rq - oq > 0.3:
            fails.append(f"(1) quadrant form: OUT {oq} not lower than the reference {rq} by more than 0.3")
        gq, gc = q["gaps"][0]["overall"]["score"], q["gaps"][1]["overall"]["score"]
        print(f"GAPS:      quadrant {gq:.4f}, coverage {gc:.4f} (xy coverage {q['gaps'][1]['xy']['coverage']:.4f})")
        if not gc < rc:
            fails.append(f"(2) GAPS {gc} not lower than the reference {rc} under the coverage form")
        if abs(q["gaps"][1]["xy"]["coverage"] - 49 / 61) > 1e-9:
            fails.append(f"(2) GAPS xy coverage {q['gaps'][1]['xy']['coverage']}, not 49/61")
        for name, (a, b) in q.items():
            for res, form, key in ((a, "quadrant", "score_quadrant"), (b, "coverage", "score_coverage")):
                if res["score_form"] != form:
                    fails.append(f"(3) {name}: score_form {res['score_form']} for {form}")
                for part in ("xy", "yx", "overall"):
                    if not {"score_quadrant", "score_coverage", "coverage"} <= set(res[part]):
                        fails.append(f"(3) {name} {part}: both scores and the coverage not reported")
                    elif abs(res[part]["score"] - res[part][key]) > 1e-12:
                        fails.append(f"(3) {name} {part}: score is not the {form} form's")
            if abs(a["overall"]["score_quadrant"] - b["overall"]["score_quadrant"]) > 1e-12:
                fails.append(f"(3) {name}: score_quadrant depends on the selection")
        cq = q["ctrl"][0]["overall"]["score"]
        print(f"control:   quadrant {cq:.4f}")
        if abs(cq - rq) > 0.02:
            fails.append(f"(5) the in-quadrant rotation moves the quadrant score by {abs(cq - rq):.3f}")
        import campaign as cp

        base = {"name": "syn", "sites": ["A", "B"], "groups": {"G": ["A", "B"]},
                "stages": {"variants": {}, "remotes": {}, "stacks": {"weightings": {"u": "none"}}, "options": {}}}
        for value, want in ((False, False), (None, True), (True, True), ("no", "error")):
            raw = dict(base)
            if value is not None:
                raw["scoring"] = {"pmin": 10.0, "pmax": 10000.0, "quadrant_term": value}
            path = tmp / f"plan_{value}.yaml"
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            try:
                plan = cp.load_plan(path)
                got = plan.quadrant_term
            except ValueError:
                got = "error"
            if got != want:
                fails.append(f"(4) scoring.quadrant_term {value!r}: got {got!r}, wanted {want!r}")
    for line in fails:
        print(f"FAIL: {line}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
