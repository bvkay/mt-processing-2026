# -*- coding: utf-8 -*-
"""
Unit test: the Queensland health table, ported to mt-workbench (`mt_workbench.health`)

Synthetic 1 Hz records of 23 days (three full weeks and a two-day fourth),
seeded: H is band-limited random variation on realistic levels (hx 20,000 nT,
hy 2,000 nT, hz -50,000 nT, variations of 10 nT), E a linear combination of
the H variations plus noise whose level switches per 30-min block between quiet
and noisy, so that the fraction of hourly windows with H-E coherence above 0.5
sits near 0.77 rather than at 1.0 by construction.

**This test fails if** (each scenario repeats its own criterion before its asserts)
  - T0 `hourly_pair_coherence` does not give ~1 for identical series, < 0.3 for
    independent ones, NaN for a window holding a NaN, or the 3600/1800 s grid;
  - T1 a sound record is not sound in every week, or its E fractions are not
    computed numbers inside [0.6, 0.95];
  - T2 a dead hx in week 2 whose level puts |F| 8 % off does not fail H in week 2
    only; T2b an hx level 8 % off its own value (|F| moves 1.1 % at these levels)
    does not make the component check (`H_component_ok`, a departure from the
    Queensland rule: deviation of each weekly median from the site's, over |H|_site for hx and
    hy, over |hz_site| for hz) False in week 2 only, with hx_dev ~0.08, while the
    Queensland |F| rule (H_ok) still passes it;
  - T3 leakage (hy = hx + noise) in week 3 does not give hxhy_med > 0.5 and H unsound;
  - T4 common-mode noise in 40 % of week 1's hours does not give hxhy_hi >= 0.3
    and H unsound in week 1 only;
  - T5 a dead ex in week 2 does not fail Ex in week 2 only, Ey sound throughout;
  - T6 exchanged electrics are not detected as swapped with Ex and Ey sound;
  - T7 a 3-day gap in week 2 does not leave week 2 evaluated with exactly the
    ungapped windows counted, or a 300 s gap costs a window;
  - T8 the thresholds are not read from the constants block (mutating the |F|
    tolerance to 0, the hxhy_hi limit to 1.0 or COMPONENT_TOL to 0.10 does not
    change the verdicts);
  - T9 `to_1hz` at 10 Hz does not reproduce a 1 Hz sampling of a slow signal,
    fill a 500 s gap or leave a 700 s gap NaN;
  - T12 (the pair-only verdict `Hpair_ok`) a dead hz with a sound pair is not
    H_ok False and Hpair_ok True in every week (IGRF F and H given), a dead pair with a
    live hz is not H_ok False and Hpair_ok False in every week, a pair at 0.75 of the
    IGRF H is Hpair_ok anywhere, a leaky pair (T3's week 3) is Hpair_ok, T1's sound record
    is not Hpair_ok in every week with and without the IGRF, or a record evaluated
    without h_igrf does not keep H_ok exactly as before;
  - T13 (a four-channel archive, the dead hz dropped) a record
    with hz None, and one with hz all NaN, does not evaluate: every week must have F,
    hz_med, hz_dev and F_igrf_ratio NaN, hz_present False, H_ok False, Hpair_ok True
    (the pair sound, |H| at the IGRF H), Ex and Ey as T1's, the same windows as T1;
    and T1's record must still read hz_present True.

Usage:
    python tests/health_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mt_workbench.health as H  # noqa: E402
from mt_workbench.health import hourly_pair_coherence, mean_field_angle, rotate_h, to_1hz, weekly_health  # noqa: E402

DAY = 86400
N = 23 * DAY
SOS = butter(4, 0.1, btype="low", fs=1.0, output="sos")   # variations at periods > 10 s: flat over 20-200 s


def band(rng, n=N):
    """Unit-variance band-limited random series."""
    s = sosfiltfilt(SOS, rng.standard_normal(n))
    return s / s.std()


def block_noise(rng, n=N, p_quiet=0.88, quiet=0.3, noisy=6.0, block=1800):
    """White noise whose std is `quiet` or `noisy` per 30-min block (p_quiet quiet blocks).

    The signal's unit variance lives below 0.1 Hz, the noise's over 0-0.5 Hz, so in band the noisy level is
    ~7x the signal's density (coherence ~0.2) and the quiet ~0.02x (~0.9). Noisy = 2.0
    is only ~0.8x in band: every window stays above 0.5 and T1 reads fractions of 1.0 (measured:
    noisy 2.0 -> 1.0, noisy 6.0 -> 0.74 on one seeded week).
    """
    nb = -(-n // block)
    level = np.where(rng.random(nb) < p_quiet, quiet, noisy)
    return rng.standard_normal(n) * np.repeat(level, block)[:n]


def base(seed=1):
    """A sound record: dict of hx, hy, hz (nT) and ex, ey, plus the variations used to build E."""
    rng = np.random.default_rng(seed)
    vx, vy, vz = band(rng), band(rng), band(rng)
    d = dict(hx=20000.0 + 10.0 * vx, hy=2000.0 + 10.0 * vy, hz=-50000.0 + 5.0 * vz,
             ex=1.0 * vy + 0.3 * vx + block_noise(rng), ey=1.0 * vx + 0.3 * vy + block_noise(rng))
    return d, (vx, vy, vz), rng


def run(d, f_igrf=None, **kw):
    """Prepare each channel with to_1hz at 1 Hz and evaluate (f_igrf: the IGRF F, T11; kw: h_igrf, T12)."""
    p = {k: to_1hz(v, 1.0) for k, v in d.items()}
    return weekly_health(0.0, 1.0, p["hx"], p["hy"], p["hz"], p["ex"], p["ey"], f_igrf=f_igrf, **kw)


def wk(k):
    """Sample slice of week k (1-based)."""
    return slice((k - 1) * 7 * DAY, min(N, k * 7 * DAY))


def t0_coherence():
    rng = np.random.default_rng(7)
    x, y = band(rng, 5 * 3600), band(rng, 5 * 3600)
    xn = x.copy()
    xn[4 * 3600 + 100] = np.nan
    tc, same = hourly_pair_coherence(x, x + 1e-6 * rng.standard_normal(x.size))
    _, ind = hourly_pair_coherence(x, y)
    _, gap = hourly_pair_coherence(xn, x)
    # fails if: the window grid is not 3600 s windows stepped 1800 s (centres 1800, 3600, ...),
    # identical series are not ~1, independent ones not < 0.3, or a NaN sample does not void its windows
    assert np.allclose(tc, np.arange(1800, 5 * 3600 - 1800 + 1, 1800)), tc
    assert np.all(same > 0.99), same
    assert np.all(ind < 0.3), ind
    assert np.all(np.isnan(gap[-2:])) and np.all(np.isfinite(gap[:-2])), gap
    # fails if: rotate_h is not rotate_fixed's convention (Hx' = c Hx + s Hy, Hy' = -s Hx + c Hy)
    # or mean_field_angle is not atan2(mean hy, mean hx); rotating by it must zero the mean Hy
    hx, hy = 20000.0 + x, 2000.0 + y
    a = mean_field_angle(hx, hy)
    assert abs(a - np.degrees(np.arctan2(np.mean(hy), np.mean(hx)))) < 1e-9, a
    rx, ry = rotate_h(hx, hy, a)
    assert abs(np.mean(ry)) < 1e-6 and abs(np.mean(rx) - np.hypot(np.mean(hx), np.mean(hy))) < 1e-6
    rx, ry = rotate_h(np.array([1.0]), np.array([0.0]), 90.0)
    assert np.allclose([rx[0], ry[0]], [0.0, -1.0], atol=1e-12), (rx, ry)
    print("T0 coherence grid, rotation convention: ok")


def t1_sound():
    d, _, _ = base()
    weeks = run(d)
    # fails if: the 23-day record is not 4 weeks (the 2-day tail keeps >= 24 windows), any week is not
    # H/Ex/Ey sound, the record reads swapped, hxhy_med >= 0.5, or an E fraction is outside [0.6, 0.95]
    # (outside means the noise design or the fraction is wrong; 1.0 would be by construction), or any week
    # fails the component check (or a dev is not ~0: 10 nT variations about fixed levels)
    assert len(weeks) == 4, [w["start"] for w in weeks]
    for w in weeks:
        assert w["H_ok"] and w["Ex_ok"] and w["Ey_ok"], w
        assert w["H_component_ok"] and max(w["hx_dev"], w["hy_dev"], w["hz_dev"]) < 0.005, w
        assert not w["e_swapped"], w
        assert w["hxhy_med"] < 0.5, w
        assert 0.6 <= w["ex"] <= 0.95 and 0.6 <= w["ey"] <= 0.95, (w["ex"], w["ey"])
    print("T1 sound: ok  ex", [round(w["ex"], 3) for w in weeks], "ey", [round(w["ey"], 3) for w in weeks],
          "hxhy_med", [round(w["hxhy_med"], 3) for w in weeks], "n_windows", [w["n_windows"] for w in weeks])
    return weeks


def t2_dead_hx():
    d, _, rng = base()
    # "a level 8 % off the true one" read literally: at hz = -50,000 nT an hx level 8 % off moves |F|
    # only 1.1 %, inside the 5 % rule, so the dead channel here sits at the level that puts |F| 8 % off
    # (hx 29,719 nT) and T2b checks the literal reading separately
    f0 = np.sqrt(20000.0 ** 2 + 2000.0 ** 2 + 50000.0 ** 2)
    level = np.sqrt((1.08 * f0) ** 2 - 2000.0 ** 2 - 50000.0 ** 2)
    s = wk(2)
    d["hx"][s] = level + 10.0 * rng.standard_normal(d["hx"][s].size)
    weeks = run(d)
    # fails if: week 2 is H sound, weeks 1 or 3 are not, or Ex/Ey change in weeks 1 and 3
    assert not weeks[1]["H_ok"], weeks[1]
    assert weeks[0]["H_ok"] and weeks[2]["H_ok"], (weeks[0], weeks[2])
    for w in (weeks[0], weeks[2]):
        assert w["Ex_ok"] and w["Ey_ok"], w
    print(f"T2 dead hx (|F| +8 %): ok  F {[round(w['F']) for w in weeks]}")

    d, _, rng = base()
    d["hx"][s] = 1.08 * 20000.0 + 10.0 * rng.standard_normal(d["hx"][s].size)
    weeks = run(d)
    # T2b: fails if the component check does not catch a dead hx whose level is 8 % off hx (H_component_ok
    # False in week 2, True in every other week; week 2's hx_dev = 1600 / hypot(20000, 2000) = 0.0796 to
    # within 0.002), or if the Queensland |F| rule (H_ok, unchanged) catches it
    # (|F| 1.1 % off: if H_ok fell the test would not be showing the blind spot the component check covers)
    dF = abs(weeks[1]["F"] - np.median([w["F"] for w in weeks])) / np.median([w["F"] for w in weeks])
    assert not weeks[1]["H_component_ok"] and abs(weeks[1]["hx_dev"] - 1600.0 / np.hypot(20000.0, 2000.0)) < 0.002, weeks[1]
    assert all(weeks[k]["H_component_ok"] for k in (0, 2, 3)), weeks
    assert dF < 0.05 and weeks[1]["H_ok"], (dF, weeks[1])
    print(f"T2b hx level 8 % off: |F| off {100 * dF:.2f} %, H_ok {[w['H_ok'] for w in weeks]}, H_component_ok "
          f"{[w['H_component_ok'] for w in weeks]}, hx_dev {[round(w['hx_dev'], 4) for w in weeks]}")
    return d


def t3_leakage():
    d, (vx, vy, vz), rng = base()
    s = wk(3)
    d["hy"][s] = 2000.0 + 10.0 * (vx[s] + 0.3 * rng.standard_normal(vx[s].size))
    weeks = run(d)
    fmed = np.median([w["F"] for w in weeks])
    # fails if: week 3's median Hx-Hy coherence is not above 0.5, week 3 is H sound, its |F| is outside the
    # tolerance (then the failure would not be the leakage's), or weeks 1 and 2 are not H sound
    assert weeks[2]["hxhy_med"] > 0.5, weeks[2]
    assert not weeks[2]["H_ok"], weeks[2]
    assert abs(weeks[2]["F"] - fmed) <= 0.05 * fmed, weeks[2]
    assert weeks[0]["H_ok"] and weeks[1]["H_ok"], weeks[:2]
    print(f"T3 leakage: ok  hxhy_med {[round(w['hxhy_med'], 3) for w in weeks]}")


def t4_common_mode():
    d, _, rng = base()
    cm = 100.0 * band(rng, 67 * 3600)          # 67 contiguous hours = 40 % of the week's 168
    i0 = 50 * 3600
    d["hx"][i0:i0 + cm.size] += cm
    d["hy"][i0:i0 + cm.size] += cm
    weeks = run(d)
    # fails if: week 1's hxhy_hi is below 0.3, week 1 is H sound, its median Hx-Hy is above 0.5 (then the
    # failure would not be the common mode's), or any other week is H unsound
    assert weeks[0]["hxhy_hi"] >= 0.3, weeks[0]
    assert weeks[0]["hxhy_med"] <= 0.5, weeks[0]
    assert not weeks[0]["H_ok"], weeks[0]
    assert all(w["H_ok"] for w in weeks[1:]), weeks[1:]
    print(f"T4 common mode: ok  hxhy_hi {[round(w['hxhy_hi'], 3) for w in weeks]}")
    return d


def t5_dead_ex():
    d, _, rng = base()
    s = wk(2)
    d["ex"][s] = rng.standard_normal(d["ex"][s].size)
    weeks = run(d)
    # fails if: week 2 is Ex sound, any other week is not, or any week is Ey unsound
    assert not weeks[1]["Ex_ok"], weeks[1]
    assert all(weeks[k]["Ex_ok"] for k in (0, 2, 3)), weeks
    assert all(w["Ey_ok"] for w in weeks), weeks
    print(f"T5 dead ex: ok  ex {[round(w['ex'], 3) for w in weeks]}")


def t10_centre_electrode():
    """The centre-electrode class. Both lines carry one voltage that is not MT (a noisy or open centre
    electrode puts V(C) on ex and ey alike): the week is Ex and Ey unsound and the two lines are coherent with each
    other. Fails if: week 2 is not flagged centre_flag, any other week is, exey_med in week 2 is under
    CENTRE_EXEY_MIN, a dead-ex-only week (T5's case) is flagged, or T1's sound weeks are flagged."""
    d, _, rng = base()
    s = wk(2)
    common = 50.0 * rng.standard_normal(d["ex"][s].size)
    d["ex"][s] = common + 0.5 * rng.standard_normal(common.size)
    d["ey"][s] = common + 0.5 * rng.standard_normal(common.size)
    weeks = run(d)
    assert weeks[1]["centre_flag"], weeks[1]
    assert not weeks[1]["Ex_ok"] and not weeks[1]["Ey_ok"], weeks[1]
    assert weeks[1]["exey_med"] >= H.CENTRE_EXEY_MIN, weeks[1]["exey_med"]
    assert not any(weeks[k]["centre_flag"] for k in (0, 2, 3)), weeks
    d5, _, rng5 = base()
    d5["ex"][s] = rng5.standard_normal(d5["ex"][s].size)
    w5 = run(d5)
    assert not any(w["centre_flag"] for w in w5), [w["centre_flag"] for w in w5]
    print(f"T10 centre electrode: ok  exey_med {[round(w['exey_med'], 3) for w in weeks]} flags {[w['centre_flag'] for w in weeks]}")


def t11_dead_sensor_vs_igrf():
    """The Queensland H rule measures |F| against the site's own median, so a dead fluxgate (a steady
    output near zero, or a constant) passes as sound in every week. With the site's IGRF F given, H_ok must also
    require F within F_IGRF_BAND of it. Fails if: a record whose H is zero plus noise in every week is H_ok anywhere
    when f_igrf is given; the same record without f_igrf keeps the Queensland verdict (the cross-check must not move);
    T1's sound record with f_igrf = its own F stays H_ok in every week; a record at 0.85 of the IGRF F is H_ok nowhere."""
    d, _, rng = base()
    f_true = float(np.sqrt(np.nanmean(d["hx"]) ** 2 + np.nanmean(d["hy"]) ** 2 + np.nanmean(d["hz"]) ** 2))
    w_sound = run(d, f_igrf=f_true)
    assert all(w["H_ok"] for w in w_sound), [w["H_ok"] for w in w_sound]
    dd, _, rng2 = base()
    for c in ("hx", "hy", "hz"):
        dd[c] = 2.0 * rng2.standard_normal(dd[c].size)
    w_dead_qld = run(dd)
    w_dead = run(dd, f_igrf=f_true)
    assert not any(w["H_ok"] for w in w_dead), [w["H_ok"] for w in w_dead]
    assert all("F_igrf_ok" in w for w in w_dead), w_dead[0].keys()
    ds, _, _ = base()
    for c in ("hx", "hy", "hz"):
        ds[c] = ds[c] * 0.85
    w_low = run(ds, f_igrf=f_true)
    assert not any(w["H_ok"] for w in w_low), [round(w["F"] / f_true, 3) for w in w_low]
    print(f"T11 dead sensor vs IGRF: ok  Queensland-only verdict on the dead record {[w['H_ok'] for w in w_dead_qld]}, with IGRF {[w['H_ok'] for w in w_dead]}, 0.85 F {[w['H_ok'] for w in w_low]}")


def t12_pair_only():
    """H_ok judges hx, hy, hz together, so a dead-Bz site with a sound pair reads H-unsound
    although its impedance is fine. Hpair_ok = the Hx-Hy rules (hxhy_hi, hxhy_med) and, with the IGRF H given, |H| =
    hypot(week's hx and hy medians) within H_IGRF_BAND of it; no hz term. Fails if: (a) dead hz (2 nT noise about 0)
    under a sound pair is not H_ok False and Hpair_ok True in every week; (b) a dead pair (2 nT noise about 0 on hx and
    hy) under a live hz is not H_ok False and Hpair_ok False in every week; (c) the pair at 0.75 of the IGRF H is
    Hpair_ok in any week; (d) T3's leaky week 3 is Hpair_ok; (e) T1's sound record is not Hpair_ok in every week with
    and without the IGRF; (f) a record evaluated with f_igrf only does not give H_ok False in every
    week on T11's dead record and True in every week on T1's sound one."""
    d, (vx, vy, vz), rng = base()
    f_true = float(np.sqrt(np.nanmean(d["hx"]) ** 2 + np.nanmean(d["hy"]) ** 2 + np.nanmean(d["hz"]) ** 2))
    h_true = float(np.hypot(np.nanmean(d["hx"]), np.nanmean(d["hy"])))
    w1 = run(d, f_igrf=f_true, h_igrf=h_true)
    w1n = run(d)
    assert all(w["Hpair_ok"] for w in w1) and all(w["Hpair_ok"] for w in w1n), ([w["Hpair_ok"] for w in w1], [w["Hpair_ok"] for w in w1n])
    assert all(w["H_ok"] for w in w1), [w["H_ok"] for w in w1]
    da, _, rng_a = base()
    da["hz"] = 2.0 * rng_a.standard_normal(da["hz"].size)
    wa = run(da, f_igrf=f_true, h_igrf=h_true)
    assert not any(w["H_ok"] for w in wa) and all(w["Hpair_ok"] for w in wa), ([w["H_ok"] for w in wa], [w["Hpair_ok"] for w in wa])
    db, _, rng_b = base()
    db["hx"] = 2.0 * rng_b.standard_normal(db["hx"].size)
    db["hy"] = 2.0 * rng_b.standard_normal(db["hy"].size)
    wb = run(db, f_igrf=f_true, h_igrf=h_true)
    assert not any(w["H_ok"] for w in wb) and not any(w["Hpair_ok"] for w in wb), ([w["H_ok"] for w in wb], [w["Hpair_ok"] for w in wb], [round(w["F"] / f_true, 3) for w in wb])
    dc, _, _ = base()
    dc["hx"], dc["hy"] = 0.75 * dc["hx"], 0.75 * dc["hy"]
    wc = run(dc, f_igrf=f_true, h_igrf=h_true)
    assert not any(w["Hpair_ok"] for w in wc), [round(w["H_igrf_ratio"], 3) for w in wc]
    dd, _, rng_d = base()
    s = wk(3)
    dd["hy"][s] = 2000.0 + 10.0 * (vx[s] + 0.3 * rng_d.standard_normal(vx[s].size))
    wd = run(dd, f_igrf=f_true, h_igrf=h_true)
    assert not wd[2]["Hpair_ok"] and wd[0]["Hpair_ok"], [w["Hpair_ok"] for w in wd]
    dead, _, rng2 = base()
    for c in ("hx", "hy", "hz"):
        dead[c] = 2.0 * rng2.standard_normal(dead[c].size)
    assert [w["H_ok"] for w in run(dead, f_igrf=f_true)] == [False] * 4
    assert [w["H_ok"] for w in run(d, f_igrf=f_true)] == [True] * 4
    print(f"T12 pair-only H: ok  dead hz H_ok {[w['H_ok'] for w in wa]} Hpair_ok {[w['Hpair_ok'] for w in wa]}; dead pair "
          f"H_ok {[w['H_ok'] for w in wb]} Hpair_ok {[w['Hpair_ok'] for w in wb]} (F/F_igrf {[round(w['F'] / f_true, 3) for w in wb]}); "
          f"0.75 H ratio {[round(w['H_igrf_ratio'], 3) for w in wc]}; leak wk3 {wd[2]['Hpair_ok']}")


def t13_no_hz(t1_weeks):
    """A four-channel archive (the dead hz dropped). Fails if a
    record without hz (None, or all NaN) is refused or does not give, in every week, F / hz_med / hz_dev /
    F_igrf_ratio NaN, hz_present False, H_ok False, Hpair_ok True, Ex_ok/Ey_ok and n_windows equal to T1's; or T1's
    record does not read hz_present True."""
    d, _, _ = base()
    f_true = float(np.sqrt(np.nanmean(d["hx"]) ** 2 + np.nanmean(d["hy"]) ** 2 + np.nanmean(d["hz"]) ** 2))
    h_true = float(np.hypot(np.nanmean(d["hx"]), np.nanmean(d["hy"])))
    p = {k: to_1hz(v, 1.0) for k, v in d.items()}
    for label, hz in (("hz None", None), ("hz all NaN", np.full(p["hx"].size, np.nan))):
        weeks = weekly_health(0.0, 1.0, p["hx"], p["hy"], hz, p["ex"], p["ey"], f_igrf=f_true, h_igrf=h_true)
        assert len(weeks) == len(t1_weeks), (label, len(weeks))
        for w, w1 in zip(weeks, t1_weeks):
            assert all(np.isnan(w[k]) for k in ("F", "hz_med", "hz_dev", "F_igrf_ratio")), (label, w)
            assert w["hz_present"] is False and not w["H_ok"] and w["Hpair_ok"], (label, w)
            assert (w["Ex_ok"], w["Ey_ok"], w["n_windows"]) == (w1["Ex_ok"], w1["Ey_ok"], w1["n_windows"]), (label, w)
    assert all(w["hz_present"] for w in run(d)), [w.get("hz_present") for w in run(d)]
    print(f"T13 no hz: ok  (None and all-NaN) H_ok {[w['H_ok'] for w in weeks]} Hpair_ok {[w['Hpair_ok'] for w in weeks]}"
          f" Ex/Ey {[(w['Ex_ok'], w['Ey_ok']) for w in weeks]}")


def t6_swapped():
    d, _, _ = base()
    d["ex"], d["ey"] = d["ey"], d["ex"]
    weeks = run(d)
    # fails if: the record is not read as swapped or any week is Ex or Ey unsound under the swap
    assert all(w["e_swapped"] for w in weeks), weeks
    assert all(w["Ex_ok"] and w["Ey_ok"] for w in weeks), weeks
    print(f"T6 swapped: ok  ex {[round(w['ex'], 3) for w in weeks]} ey {[round(w['ey'], 3) for w in weeks]}")


def t7_gaps(t1_weeks):
    d, _, _ = base()
    g0, g1 = int(8.5 * DAY), int(11.5 * DAY)       # 3 days inside week 2
    h0, h1 = 3 * DAY + 1000, 3 * DAY + 1300        # 300 s inside week 1
    for k in d:
        d[k][g0:g1] = np.nan
        d[k][h0:h1] = np.nan
    weeks = run(d)
    # the expected count, from the window grid alone: windows [s, s + 3600) with centre in week 2 that do
    # not touch the 3-day gap (the 300 s gap is filled and voids nothing)
    starts = np.arange(0, N - 3600 + 1, 1800)
    cen = starts + 1800
    in2 = (cen >= 7 * DAY) & (cen < 14 * DAY)
    clear = (starts + 3600 <= g0) | (starts >= g1)
    expect2 = int((in2 & clear).sum())
    # fails if: week 2 is dropped, its n_windows is not the ungapped count, week 1 lost a window to the
    # 300 s gap, or week 2's ex fraction is not formed over its finite windows (counting a gapped window
    # as "not above 0.5" would cut it to ~57 % of T1's)
    assert len(weeks) == 4, len(weeks)
    assert weeks[1]["n_windows"] == expect2 and expect2 >= 24, (weeks[1]["n_windows"], expect2)
    assert weeks[0]["n_windows"] == t1_weeks[0]["n_windows"], (weeks[0]["n_windows"], t1_weeks[0]["n_windows"])
    assert abs(weeks[1]["ex"] - t1_weeks[1]["ex"]) < 0.15, (weeks[1]["ex"], t1_weeks[1]["ex"])
    print(f"T7 gaps: ok  n_windows {[w['n_windows'] for w in weeks]} (week 2 expected {expect2}), "
          f"week 2 ex {weeks[1]['ex']:.3f} vs T1 {t1_weeks[1]['ex']:.3f}")


def t8_mutation(d_t4, d_t2b):
    keep = (H.F_TOL, H.HXHY_HI_MAX, H.COMPONENT_TOL)
    try:
        H.F_TOL = 0.0
        d, _, _ = base()
        weeks = run(d)
        # fails if: with no |F| tolerance every week of the sound record is still H sound
        assert not all(w["H_ok"] for w in weeks), weeks
        H.F_TOL = keep[0]
        H.HXHY_HI_MAX = 1.0
        weeks = run(d_t4)
        # fails if: with the hxhy_hi limit at 1.0 week 1 of T4 is still H unsound
        assert weeks[0]["H_ok"], weeks[0]
        H.HXHY_HI_MAX = keep[1]
        H.COMPONENT_TOL = 0.10
        weeks = run(d_t2b)
        # fails if: with COMPONENT_TOL at 0.10 week 2 of T2b (hx_dev 0.08) still fails the component check
        assert weeks[1]["H_component_ok"], weeks[1]
    finally:
        H.F_TOL, H.HXHY_HI_MAX, H.COMPONENT_TOL = keep
    assert (H.F_TOL, H.HXHY_HI_MAX, H.COMPONENT_TOL) == (0.05, 0.3, 0.05)
    print("T8 mutation: ok  (F_TOL 0 -> not all H sound; HXHY_HI_MAX 1.0 -> T4 week 1 sound; "
          "COMPONENT_TOL 0.10 -> T2b week 2 (hx_dev 0.08) component-sound)")


def t9_decimate():
    n10 = 864000                                   # one day at 10 Hz
    t = np.arange(n10) / 10.0
    x = 20000.0 + 10.0 * np.sin(2 * np.pi * t / 100.0) + 5.0 * np.sin(2 * np.pi * t / 37.0)
    y = to_1hz(x, 10.0)
    ts = np.arange(n10 // 10)
    ref = 20000.0 + 10.0 * np.sin(2 * np.pi * ts / 100.0) + 5.0 * np.sin(2 * np.pi * ts / 37.0)
    # fails if: the output is not 1 Hz, not aligned to the input's sample 0 (zero phase: a 1 s shift is a
    # 17 % error at 37 s), or off by more than 0.25 % of the 15 nT amplitude (0.0375 nT) away from the ends.
    # First written as 0.01 nT; the cache's FIR (firwin(201), Hamming) droops 0.17 % at 37 s and 0.03 % at
    # 100 s (measured, the same at DC 0 and 20,000 nT), a property of the Queensland call itself
    assert y.size == n10 // 10, y.size
    assert np.max(np.abs(y[100:-100] - ref[100:-100])) < 0.0375, np.max(np.abs(y[100:-100] - ref[100:-100]))
    xg = x.copy()
    a0, a1 = 20000 * 10, 20500 * 10                # 500 s gap: filled
    b0, b1 = 50000 * 10, 50700 * 10                # 700 s gap: left NaN
    xg[a0:a1] = np.nan
    xg[b0:b1] = np.nan
    yg = to_1hz(xg, 10.0)
    bad = ~np.isfinite(yg)
    # fails if: the 500 s gap leaves a NaN, the 700 s gap is not NaN over its whole span, or the NaN spreads
    # more than the decimation FIR's half-length beyond it (scipy 1.17 decimate(q=10, ftype='fir') is
    # firwin(201): 100 input samples = 10 s each side; first written as 5 s before the filter length was read)
    assert not bad[19990:20510].any(), np.flatnonzero(bad[19990:20510])
    assert bad[50000:50700].all(), int(bad[50000:50700].sum())
    assert bad.sum() <= 700 + 2 * 11 and not bad[:49989].any() and not bad[50711:].any(), np.flatnonzero(bad)[[0, -1]]
    print(f"T9 to_1hz: ok  max err {np.max(np.abs(y[100:-100] - ref[100:-100])):.2e} nT, 700 s gap -> {int(bad.sum())} NaN s")


if __name__ == "__main__":
    t0_coherence()
    t9_decimate()
    w1 = t1_sound()
    d2b = t2_dead_hx()
    t3_leakage()
    d4 = t4_common_mode()
    t5_dead_ex()
    t6_swapped()
    t10_centre_electrode()
    t11_dead_sensor_vs_igrf()
    t12_pair_only()
    t13_no_hz(w1)
    t7_gaps(w1)
    t8_mutation(d4, d2b)
    print("health_unit: all passed")
