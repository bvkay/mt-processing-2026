# -*- coding: utf-8 -*-
"""
Cross-check: `mt_workbench.health` against the Queensland source run on the same 1 Hz arrays

The Queensland health table (``qc/qld_health_table.py`` of the Queensland
processing scripts, outside this repository; the test reads the student
pack at ``QLD_PACK``)
is run here with its own ``coherence_map`` (imported from
``student_pack_v2/qld_student.py``; ``setup()`` is not called), ``band_coh``
(``qld_salvage.py`` 165-167) and its weekly loop and rules copied unchanged
(``qld_health_table.py`` 35-58, with ``loc`` built as ``load_site`` builds it
and ``qld_campaign.rotate`` for the angle). The same arrays then go through
`mt_workbench.health.weekly_health`. Inputs are gapless, where the port's
finite-window departure cannot act: two synthetic records from
tests/health_unit.py (swapped electrics; common-mode noise in week 1) and the
raw archives of NF39 and SA001 (SA AusLAMP), taken to 1 Hz by `to_1hz`.

**This test fails if** for any input the number of weeks differs, any week's
start, end, F, angle, hxhy_hi, hxhy_med, ex or ey differs by more than 1e-9, any
H_ok/Ex_ok/Ey_ok verdict differs, or the swapped flag differs.

It prints SKIP and exits 0 when the Queensland source folder is absent; a real
archive that is absent is reported as skipped and the synthetic cases still run.

Usage:
    python tests/health_qld_crosscheck.py [SITE ...]      (default sites: NF39 SA001)

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import sys
from pathlib import Path

QLD_PACK = Path(r"D:\BEN\MTH5_Aurora_mt-io_2026\student_pack_v2")
REPO = Path(__file__).resolve().parents[1]
SURVEY = REPO / "surveys" / "south_australia_auslamp_2013_2018" / "survey.yaml"
CHANNELS = ("hx", "hy", "hz", "ex", "ey")

if not QLD_PACK.is_dir():
    print(f"health_qld_crosscheck: SKIP ({QLD_PACK} absent)")
    sys.exit(0)

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(QLD_PACK))
import numpy as np  # noqa: E402

import qld_student as Q  # noqa: E402
from mt_workbench import health as HL  # noqa: E402


def band_coh(x, y, lo=20.0, hi=200.0):
    """qld_salvage.py 165-167, unchanged."""
    tc, per, coh = Q.coherence_map(x, y, 1.0, 3600, 1800, pmin=lo, pmax=hi)
    return tc, np.nanmean(coh, axis=1)


def qld(hx_raw, hy_raw, hz, ex, ey):
    """qld_health_table.py 35-58 unchanged, `loc` built as load_site does (qld_campaign.rotate)."""
    th = np.arctan2(np.nanmean(hy_raw), np.nanmean(hx_raw)); c, s = np.cos(th), np.sin(th)
    loc = {"Hx": c * hx_raw + s * hy_raw, "Hy": -s * hx_raw + c * hy_raw, "Hz": hz, "Ex": ex, "Ey": ey}
    raw_h = {"Hx": hx_raw, "Hy": hy_raw}
    n = len(loc["Hx"]); WEEK = 7 * 86400; fr = {}
    for a, b in (("Hx", "Ey"), ("Hy", "Ex"), ("Hx", "Ex"), ("Hy", "Ey"), ("Ex", "Ey"), ("Hx", "Hy")):
        tc, v = band_coh(loc[a], loc[b]); fr[a + b] = v
    swapped = (np.nanmean(fr["HxEx"] > 0.5) > np.nanmean(fr["HxEy"] > 0.5) + 0.15) and (np.nanmean(fr["HyEy"] > 0.5) > np.nanmean(fr["HyEx"] > 0.5) + 0.15)
    hx, hy, hz = np.asarray(raw_h["Hx"], float), np.asarray(raw_h["Hy"], float), np.asarray(loc["Hz"], float)
    weeks = []
    for w0 in range(0, n, WEEK):
        w1 = min(n, w0 + WEEK); m = (tc >= w0) & (tc < w1)
        if m.sum() < 24:
            continue
        x, y, z = np.nanmean(hx[w0:w1]), np.nanmean(hy[w0:w1]), np.nanmean(hz[w0:w1])
        weeks.append(dict(start=w0, end=w1, F=float(np.sqrt(x * x + y * y + z * z)), angle=float(np.degrees(np.arctan2(y, x))),
                          hxhy_hi=float(np.nanmean(fr["HxHy"][m] > 0.9)), hxhy_med=float(np.nanmedian(fr["HxHy"][m])),
                          ex=float(np.nanmean((fr["HxEx"] if swapped else fr["HyEx"])[m] > 0.5)),
                          ey=float(np.nanmean((fr["HyEy"] if swapped else fr["HxEy"])[m] > 0.5))))
    Fmed = np.median([w["F"] for w in weeks])
    for w in weeks:
        w["H_ok"] = abs(w["F"] - Fmed) <= 0.05 * Fmed and w["hxhy_hi"] < 0.3 and w["hxhy_med"] <= 0.5
        w["Ex_ok"] = w["ex"] >= 0.3
        w["Ey_ok"] = w["ey"] >= 0.3
    return weeks, bool(swapped)


def compare(label, d):
    """Run both on the same arrays; assert the criterion in the module docstring."""
    a, sw = qld(d["hx"], d["hy"], d["hz"], d["ex"], d["ey"])
    b = HL.weekly_health(0.0, 1.0, d["hx"], d["hy"], d["hz"], d["ex"], d["ey"])
    assert len(a) == len(b), (label, len(a), len(b))
    worst = 0.0
    for wa, wb in zip(a, b):
        for k in ("start", "end", "F", "angle", "hxhy_hi", "hxhy_med", "ex", "ey"):
            worst = max(worst, abs(wa[k] - wb[k]))
            assert abs(wa[k] - wb[k]) <= 1e-9, (label, k, wa[k], wb[k])
        for k in ("H_ok", "Ex_ok", "Ey_ok"):
            assert bool(wa[k]) == wb[k], (label, k, wa[k], wb[k])
        assert wb["e_swapped"] == sw, (label, "swapped")
    print(f"{label}: {len(a)} weeks identical to the Queensland code (max |diff| {worst:.1e}), swapped {sw}", flush=True)


def main(sites) -> int:
    import health_unit as T
    d, _, _ = T.base()
    d["ex"], d["ey"] = d["ey"], d["ex"]
    compare("synthetic swapped", d)
    d, _, rng = T.base()
    cm = 100.0 * T.band(rng, 67 * 3600)
    d["hx"][180000:180000 + cm.size] += cm
    d["hy"][180000:180000 + cm.size] += cm
    compare("synthetic common mode", d)
    from mt_workbench.ingest import default_archive_path
    from mt_workbench.survey import Survey
    from mt_workbench.timefreq import load_station
    survey = Survey.from_yaml(SURVEY)
    for site in sites:
        archive = default_archive_path(survey, site)
        if not archive.exists():
            print(f"{site}: skipped, no archive {archive}")
            continue
        rec = load_station(archive, survey.name, site, comps=CHANNELS)
        d = {c: HL.to_1hz(rec.value(c), rec.sample_rate, gaps=rec.gaps) for c in CHANNELS}
        compare(f"{site} (1 Hz from to_1hz)", d)
    print("health_qld_crosscheck: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["NF39", "SA001"]))
