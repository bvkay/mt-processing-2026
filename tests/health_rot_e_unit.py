# -*- coding: utf-8 -*-
"""
Unit test: the health table judges the electric lines as recorded at a rot_e site

At a site whose pair the ingest turned (`mt_workbench.ingest._rot_e`;
`archive_rot_e` not None) the archive's ex and ey are E_N and E_E, mixtures of
the two recorded lines, so a fault on one recorded line reaches both archive
channels (SA009 read as a centre fault). The health
table undoes the turn (`health_table.recorded_e`, the inversion of
diagonal_site.py in calibrated units: [E_bx; E_by] = M [E_N; E_E], M =
`diagonal_site.unturn_matrix(b_x, b_y, 1)`, k = 1 because each calibrated
channel already carries its own dipole gain) and pairs each recorded line with
the H component perpendicular to the direction it measures along
(`health_record(..., e_dirs=(b_x, b_y))`: H turned by the mean-field angle plus
the line's departure from its nominal 0 or 90 deg).

Synthetic 1 Hz records of 16 days (two full weeks and a two-day third), H in
the magnetic frame (hx 20,000, hy 2,000, hz -50,000 nT plus 10 nT variations),
E of a 1-D earth (E_N = H_E variation, E_E = -H_N variation, plus a 30 % cross
term), each recorded line = the field along its measuring direction plus
quiet/noisy block noise (tests/health_unit.py's `block_noise`); a "dead"
recorded line is noise of std 5 with no field. The turn is the ingest's own
matrix (`_rot_e_matrix`).

**This test fails if**
  - (1) `recorded_e` does not return the recorded lines from the turned pair to
    1e-9 (relative) at the SA009 layout (laid 225/135, measuring 45/135) and the
    SA070 layout (40/310, measuring 40/310), or its matrix is not
    `diagonal_site.unturn_matrix(b_x, b_y, 1)`, or it does not return None for a
    cardinal archive (laid None);
  - (2) at SA009's layout with recorded ex clean and recorded ey dead, the table
    on the recorded lines does not read Ex sound and Ey unsound in every week
    (and not swapped, no centre flag); the mirror (ex dead, ey clean) does not
    read Ex unsound and Ey sound; the same at SA070's layout;
  - (3) control: the same records judged on the turned pair
    read exactly "Ex sound, Ey unsound" in every week at SA009's layout (then the
    test could not show the fault being placed on its line);
  - (4) a cardinal record judged with e_dirs=(0, 90) differs from e_dirs=None in
    any field of any week (the Queensland verdicts stay the same), and the
    health_unit T1 sound record with e_dirs=(0, 90) is not identical either;
  - (5) a recorded pair with both lines clean at SA009's layout is not Ex and Ey
    sound on the recorded lines;
  - (6) the Ex-Ey coherence (exey_med, the centre flag's input) of the same two
    lines changes with e_dirs (a build computing it as Hy-Ey through the
    e_dirs path, as seen on FR05, passes (4), both of its sides going
    through that path).

Usage:
    python tests/health_rot_e_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import diagonal_site as ds  # noqa: E402
import health_table as HT  # noqa: E402
from health_unit import band, base, block_noise  # noqa: E402
from mt_workbench.health import health_record, to_1hz  # noqa: E402
from mt_workbench.ingest import _rot_e_matrix  # noqa: E402

DAY = 86400
N = 16 * DAY
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def field(seed: int):
    """H (magnetic frame) and the 1-D E field (E_N, E_E) of one seeded record."""
    rng = np.random.default_rng(seed)
    vx, vy, vz = band(rng, N), band(rng, N), band(rng, N)
    h = dict(hx=20000.0 + 10.0 * vx, hy=2000.0 + 10.0 * vy, hz=-50000.0 + 5.0 * vz)
    en, ee = 1.0 * vy + 0.3 * vx, -(1.0 * vx + 0.3 * vy)
    return h, en, ee, rng


def recorded(en, ee, b: float, rng, dead: bool) -> np.ndarray:
    """A recorded line measuring along b: the field along b plus block noise, or noise only when dead."""
    if dead:
        return 5.0 * rng.standard_normal(en.size)
    return math.cos(math.radians(b)) * en + math.sin(math.radians(b)) * ee + block_noise(rng, en.size)


def turned(x, y, bx, by):
    """The archive's (E_N, E_E) the ingest writes from recorded lines along bx, by (calibrated terms)."""
    i = _rot_e_matrix(bx, by)
    return i[0, 0] * x + i[0, 1] * y, i[1, 0] * x + i[1, 1] * y


def judge(h, ex, ey, e_dirs=None):
    """Prepare each channel at 1 Hz and evaluate the record."""
    p = {k: to_1hz(v, 1.0) for k, v in dict(h, ex=ex, ey=ey).items()}
    if e_dirs is None:
        return health_record(0.0, 1.0, p["hx"], p["hy"], p["hz"], p["ex"], p["ey"])
    return health_record(0.0, 1.0, p["hx"], p["hy"], p["hz"], p["ex"], p["ey"], e_dirs=e_dirs)


def verdicts(r) -> list[tuple[bool, bool]]:
    """(Ex_ok, Ey_ok) per week."""
    return [(w["Ex_ok"], w["Ey_ok"]) for w in r["weeks"]]


def same_weeks(a, b) -> bool:
    """Every field of every week equal (NaN equal to NaN), and the swapped flag."""
    return (len(a["weeks"]) == len(b["weeks"]) and a["e_swapped"] == b["e_swapped"] and all(
        wa.keys() == wb.keys() and all((wa[k] == wb[k]) or (wa[k] != wa[k] and wb[k] != wb[k]) for k in wa)
        for wa, wb in zip(a["weeks"], b["weeks"])))


def test_inverse() -> None:
    try:
        recorded_e = HT.recorded_e
    except AttributeError as exc:
        check(False, f"(1) health_table.recorded_e: {exc}")
        return
    for laid in ((225.0, 135.0), (40.0, 310.0)):
        bx, by = ds.recorded_directions(laid)
        rng = np.random.default_rng(3)
        x, y = rng.standard_normal(1000), rng.standard_normal(1000)
        X, Y = turned(x, y, bx, by)
        xr, yr, dirs, m = recorded_e(X, Y, laid)
        err = max(np.max(np.abs(xr - x)), np.max(np.abs(yr - y))) / max(np.max(np.abs(x)), np.max(np.abs(y)))
        check(err < 1e-9 and np.allclose(m, ds.unturn_matrix(bx, by, 1.0), rtol=0, atol=1e-15)
              and dirs == (bx, by), f"(1) laid {laid[0]:g}/{laid[1]:g}: measuring {dirs}, max rel err {err:.1e}")
    check(recorded_e(np.zeros(3), np.zeros(3), None) is None, "(1) cardinal archive (laid None) -> None")


def test_one_dead() -> None:
    for laid, seed in (((225.0, 135.0), 11), ((40.0, 310.0), 12)):
        bx, by = ds.recorded_directions(laid)
        for dead_x in (False, True):
            h, en, ee, rng = field(seed)
            x = recorded(en, ee, bx, rng, dead=dead_x)
            y = recorded(en, ee, by, rng, dead=not dead_x)
            X, Y = turned(x, y, bx, by)
            xr, yr, dirs, _ = HT.recorded_e(X, Y, laid)
            r = judge(h, xr, yr, e_dirs=dirs)
            want = (not dead_x, dead_x)
            ok = all(v == want for v in verdicts(r)) and not r["e_swapped"] \
                and not any(w["centre_flag"] for w in r["weeks"])
            check(ok, f"(2) laid {laid[0]:g}/{laid[1]:g}, recorded {'ex' if dead_x else 'ey'} dead: recorded lines "
                      f"(Ex_ok, Ey_ok) {verdicts(r)} want {want}; ex {[round(w['ex'], 2) for w in r['weeks']]} ey "
                      f"{[round(w['ey'], 2) for w in r['weeks']]} swapped {r['e_swapped']}")
            if laid == (225.0, 135.0) and not dead_x:
                c = judge(h, X, Y)
                check(not all(v == (True, False) for v in verdicts(c)),
                      f"(3) control, the turned pair as the code before judged it: {verdicts(c)} ex "
                      f"{[round(w['ex'], 2) for w in c['weeks']]} ey {[round(w['ey'], 2) for w in c['weeks']]} "
                      f"centre {[w['centre_flag'] for w in c['weeks']]}")


def test_cardinal_unchanged() -> None:
    h, en, ee, rng = field(21)
    ex, ey = en + block_noise(rng, N), ee + block_noise(rng, N)
    a, b = judge(h, ex, ey), judge(h, ex, ey, e_dirs=(0.0, 90.0))
    check(same_weeks(a, b), f"(4) cardinal e_dirs (0, 90) == None in every field of {len(a['weeks'])} weeks")
    d, _, _ = base()
    p = {k: to_1hz(v, 1.0) for k, v in d.items()}
    a = health_record(0.0, 1.0, p["hx"], p["hy"], p["hz"], p["ex"], p["ey"])
    b = health_record(0.0, 1.0, p["hx"], p["hy"], p["hz"], p["ex"], p["ey"], e_dirs=(0.0, 90.0))
    check(same_weeks(a, b), f"(4) health_unit T1 record: e_dirs (0, 90) == None in every field of "
                            f"{len(a['weeks'])} weeks")


def test_both_clean() -> None:
    laid = (225.0, 135.0)
    bx, by = ds.recorded_directions(laid)
    h, en, ee, rng = field(31)
    x, y = recorded(en, ee, bx, rng, False), recorded(en, ee, by, rng, False)
    xr, yr, dirs, _ = HT.recorded_e(*turned(x, y, bx, by), laid)
    r = judge(h, xr, yr, e_dirs=dirs)
    check(all(v == (True, True) for v in verdicts(r)) and not r["e_swapped"],
          f"(5) both recorded lines clean at 225/135: {verdicts(r)} swapped {r['e_swapped']}")


def test_exey_independent() -> None:
    h, en, ee, rng = field(41)
    x, y = recorded(en, ee, 45.0, rng, False), recorded(en, ee, 135.0, rng, False)
    a, b = judge(h, x, y), judge(h, x, y, e_dirs=(45.0, 135.0))
    ea, eb = [w["exey_med"] for w in a["weeks"]], [w["exey_med"] for w in b["weeks"]]
    check(ea == eb, f"(6) exey_med without e_dirs {[round(v, 3) for v in ea]}, with (45, 135) "
                    f"{[round(v, 3) for v in eb]}")


def main() -> int:
    test_inverse()
    if not fails:
        test_one_dead()
        test_cardinal_unchanged()
        test_both_clean()
        test_exey_independent()
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
