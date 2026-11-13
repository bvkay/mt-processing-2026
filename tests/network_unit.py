# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.network, the network datum

Every network is synthetic and built here: a random tree over ns sites
plus extra edges up to ne equations (no pair twice), errors log-uniform
between two limits, potentials phi_true uniform over a range and
psi = wrap(phi_l - phi_b + err N(0, 1)), so psi(l, b) = phi_l - phi_b
holds modulo 180 deg within the stated errors. The random graphs often
give the two top sites of `gauge_rank` the same counts, a gauge tie with
phi_deg NaN, so the tests that read phi_deg raise the top site's count of
each component by one in the rank table (`untied`); G1 tests the tie.
Every random case uses fixed seeds, given with its case below, and a
correct build passes them.

Usage:
    python tests/network_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

W1 (wrap)
  1. wrap([-90, 90, 270, -270, 0, -0.0, 180]) is not
     [90, 90, 90, 90, 0, 0, 0], the interval (-90, 90] of the pair
     product, or a 0 comes out as -0.0.
N1 (recovery; seeds 0 to 9, 30 sites, 70 equations, errors 0.1 to 1 deg,
potentials over 40 deg)
  1. more than 5 of the 290 non-gauge site-seeds have
     |wrap(phi_deg - (phi_true - phi_true[gauge]))| > 3 phi_err_deg, or a
     phi_deg is NaN (false failure 2e-4 for independent sites, binomial;
     more since the sites of one seed share a gauge);
  2. more than 1 of the 10 seeds has chi2/dof outside its 99 % interval
     (false failure 0.004);
  3. dof differs from 70 - 29;
  4. the sum of the redundancies differs from dof by more than 1e-9;
  5. the number of loops differs from dof;
  6. with noise-free psi, any loop closure exceeds 1e-9 deg;
  7. the gauge site's phi_deg or phi_err_deg is not exactly 0.
N2 (seed 0's graph, errors 1 deg, the first pair with redundancy over 0.3
shifted by +20 deg)
  1. the pooled chi2/dof stays under 2;
  2. the loop of largest |z| does not hold that pair, or the `all` row's
     worst_loop_z and worst_loop_sites are not that loop's z and sites;
  3. as the control, the unshifted network has chi2/dof over 2 or a loop
     with |z| >= 4.5 (in 200 such networks the worst loop held the pair
     and the control passed every time).
N3 (seed 0's network solved with its rank table and with another site
first, one on the other side of the median of phi_true from the first
gauge)
  1. wrap(phi_deg(A) - phi_deg(B)) is not one constant within 1e-9 deg, or
     the two gauges are the same site (so nothing was changed);
  2. phi_rel_deg differs by more than 1e-9 deg;
  3. phi_rel_err_deg differs by more than 1e-12 deg + 1e-6 relative;
  4. chi2 differs by more than 1e-9 relative;
  5. the loop tables differ in anything but the component label, which
     names the gauge.
N4 (seeds 0 and 1 as two networks with distinct names, offsets +30 and
-40 deg, solved together)
  1. there are not two components, each labelled by its own top-ranked site;
  2. a site's component is the other network's label;
  3. phi_rel of either network differs from it solved alone by over 1e-9 deg;
  4. the pooled dof is not the sum of the two;
  5. a site's phi_deg differs from its network solved alone by over 1e-9
     deg (a value on the other network's zero);
  6. with a flag column flag_test (error over 0.5 deg), the two
     components' n_entered and n_flag_test do not sum to the `all` row's,
     or the `all` row's are not the numbers of rows and flagged rows.
N5 (20 sites, 45 equations, potentials over 0 to 170 deg; seeds 9000 to
9199; case a errors 0.5 to 3 deg, case b errors 0.2 to 120 deg)
  1. in any seed of either case a site has
     |wrap(phi_deg - (phi_true - phi_true[gauge]))| > 5 phi_err_deg or NaN
     (false failure about 4e-3: 400 seeds x 19 sites x 5.7e-7);
  2. in case a more than 6 of 200 seeds have chi2/dof outside the 99 %
     interval (false failure 0.004). Case b has no such item: equations
     with errors over 52 deg pull chi2/dof low;
  3. on the graphs of case a with noise-free psi, a loop's |closure_deg|
     is 1e-9 deg or more (the potentials span 170 deg, so a loop's sum of
     psi is a whole number of turns that only the wrap brings to 0);
  4. in a seed of case b, n_err_over_52 is not the number of equations
     with an error over 52 deg, or no seed has one;
  5. with potentials over 0 to 150 deg (seeds 9000 to 9019, errors 0.5 to
     3 deg), n_far_from_centre is not the number of sites whose phi_deg
     lies more than 60 deg from the circular mean (period 180) of the
     component's phi_deg, or no seed has one.
N6 (a 2-site tree, a 4-site chain and a third component with loops)
  1. a tree component's site is not solved or has no phi_rel_deg;
  2. a tree component's chi2_dof or scale is not NaN, its dof is not 0, or
     the scale written on its sites in sites_period is not NaN;
  3. a tree component's redundancy differs from 0 by more than 1e-12;
  4. the 2-site phi_rel is not +psi/2 at the local and -psi/2 at the base
     within 1e-12 deg;
  5. a tree component lists a loop;
  6. the `all` row's dof and chi2 are not those of the third component.
N7 (one pair given three times, errors 1, 2 and 3 deg, in a network of
seed 7 with errors 4 to 10 deg)
  1. phi_deg differs from the same network with the three combined by
     inverse variance by more than 1e-9 deg;
  2. dof is not larger by exactly 2;
  3. there are not 2 `repeat` loops.
N8 (error calibration; seeds 0 to 999, 31 sites, 70 equations, errors 0.01
to 0.05 deg, potentials over 30 deg; one random site per seed)
  1. the fraction with |phi_rel - (phi_true - median(phi_true))| <=
     phi_rel_err (a site with phi_rel_err > 0) is outside 0.683 +- 0.044
     (3 sigma of the binomial, false failure 0.003 at a coverage of 0.683;
     the plug-in error's own coverage lies between about 0.67 and 0.71,
     and at 0.705 the false failure rises to about 0.05);
  2. the fraction for the gauge-relative phi_deg and phi_err_deg (a
     non-gauge site) is outside the same interval (false failure 0.003);
  3. the mean chi2/dof over the seeds is outside 1 +- 3 sqrt(2 / (dof x
     1000)) (false failure 0.003).
N9 (band_reading, rows built here)
  1. one site, 5 periods, a constant phi_rel and errors 1 to 5: phi_rel_deg
     is not the constant, err_independent_deg not (sum 1/e^2)^-1/2, or
     err_correlated_deg not 1.5601 within 1e-4;
  2. with one of five errors 0: n_zero_err is not 1 or the reading is not
     that of the other four rows;
  3. with one period, scatter_chi2_dof is not NaN;
  4. the frame passed in is changed;
  5. a site whose component changes inside the band is merged into one row;
  6. a band holding no solved row does not give an empty frame with the
     twelve columns of a reading.
N10 (seed 0's graph and errors with the potentials over 1 deg, where the
median site changes from draw to draw and the median error is not linear
in a scale)
  1. with every error doubled: phi_deg differs by more than 1e-9 deg,
     phi_err_deg is not doubled within 1e-12 relative, chi2 is not divided
     by 4 within 1e-9 relative, or phi_rel_err_deg differs from
     median_relative(x, 4 C_full) with the period's seed by more than 1e-12;
  2. with scale_by_closure on the errors halved (chi2/dof near 4) beside a
     second component Q (seed 5, 8 sites, 16 equations) whose errors are
     doubled (chi2/dof near 0.25): phi_err_deg is not times the scale,
     phi_rel_err_deg differs from median_relative(x, scale^2 C_full) by
     more than 1e-12, or errors_scaled is not set; or a component with
     scale <= 1 has phi_err_deg or phi_rel_err_deg changed or
     errors_scaled set;
  3. a run without scale_by_closure sets errors_scaled.
G1 (gauge_rank and ties)
  1. a star of 5 sites round a centre with one chord and one pair given
     twice, and a site Y with 4 equations to the centre only, over two
     periods, does not give the counts and order built in (Y, 4 equations
     and 1 partner, above L1, 3 equations and 2 partners);
  2. a 4-site ring with equal errors and counts does not give gauge empty,
     gauge_tie naming all four, phi_deg NaN, solved sites, and phi_rel
     within 1e-9 deg of the ring solved with an untied rank table;
  3. the run stops on the tie.
E1 (inputs the solve refuses)
  1. an entered row of a 3-site loop with psi NaN, error NaN or error 0
     does not raise ValueError naming its pair;
  2. solve with max_iter 0 does not raise ValueError saying it needs at
     least 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench import network  # noqa: E402
from mt_workbench.network import wrap  # noqa: E402

PERIOD = 1.0
SEED = [0, int(round(PERIOD * 1e6))]

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def graph(r, ns: int, ne: int) -> tuple[np.ndarray, np.ndarray]:
    """Return local and base site indices of a random tree plus extra edges, no pair twice."""
    edges = set()
    for i in range(1, ns):
        edges.add((i, int(r.integers(0, i))))
    while len(edges) < ne:
        a, b = (int(v) for v in r.integers(0, ns, 2))
        if a != b and (b, a) not in edges and (a, b) not in edges:
            edges.add((a, b))
    e = sorted(edges)
    return np.array([a for a, _ in e]), np.array([b for _, b in e])


def make(seed: int, ns: int, ne: int, err_lo: float, err_hi: float, span: float, prefix: str = "S") -> dict:
    """Draw a network: graph, errors, potentials and unit noise, in that order."""
    r = np.random.default_rng(seed)
    loc, bas = graph(r, ns, ne)
    err = np.exp(r.uniform(np.log(err_lo), np.log(err_hi), ne))
    phi = r.uniform(0, span, ns)
    z = r.standard_normal(ne)
    names = np.array([f"{prefix}{i:02d}" for i in range(ns)])
    return {"names": names, "loc": loc, "bas": bas, "err": err, "phi": phi, "z": z}


def frame(net: dict, psi=None, err=None) -> pd.DataFrame:
    """Return the equations frame of a network at one period, every row entered."""
    err = net["err"] if err is None else err
    if psi is None:
        psi = wrap(net["phi"][net["loc"]] - net["phi"][net["bas"]] + err * net["z"])
    loc, bas = net["names"][net["loc"]], net["names"][net["bas"]]
    return pd.DataFrame({"pair": [f"{a}-{b}" for a, b in zip(loc, bas)], "local": loc, "base": bas,
                         "psi_deg": psi, "err_deg": err, "period_s": PERIOD, "entered": True, "reason": ""})


def untied(rank: pd.DataFrame, eq: pd.DataFrame) -> pd.DataFrame:
    """Raise the count of each component's first site of the rank table by one, keeping the order."""
    rank = rank.copy()
    for comp in network.components(eq["local"], eq["base"]):
        first = rank.index[rank["site"].isin(comp)][0]
        rank.loc[first, "n_equations"] += 1
    return rank


def run(eq: pd.DataFrame, rank=None, **kw) -> dict:
    """Solve every period of eq, with the untied gauge_rank table unless one is given."""
    if rank is None:
        rank = untied(network.gauge_rank(eq), eq)
    return network.solve_periods(eq, rank, **kw)


def comp_rows(res: dict) -> pd.DataFrame:
    p = res["periods"]
    return p[p["component"] != "all"].reset_index(drop=True)


def all_row(res: dict) -> pd.Series:
    p = res["periods"]
    return p[p["component"] == "all"].iloc[0]


def gauge_dev(res: dict, net: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return wrap(phi_deg - (phi_true - phi_true[gauge])) and phi_err_deg of the non-gauge sites."""
    gauge = comp_rows(res)["gauge"].iloc[0]
    sp = res["sites_period"].set_index("site").loc[net["names"]]
    truth = net["phi"] - net["phi"][list(net["names"]).index(gauge)] if gauge else np.full(len(net["phi"]), np.nan)
    keep = net["names"] != gauge
    return wrap(sp["phi_deg"].to_numpy() - truth)[keep], sp["phi_err_deg"].to_numpy()[keep]


def outside99(row: pd.Series) -> bool:
    return not (row["chi2_dof_lo99"] <= row["chi2_dof"] <= row["chi2_dof_hi99"])


def w1() -> None:
    got = wrap([-90.0, 90.0, 270.0, -270.0, 0.0, -0.0, 180.0])
    ok = got.tolist() == [90.0, 90.0, 90.0, 90.0, 0.0, 0.0, 0.0] and not np.signbit(got).any()
    check(ok, f"W1.1 wrap of -90, 90, 270, -270, 0, -0.0, 180: {got.tolist()}")


def n1() -> None:
    beyond, outside, dofs, red_gap, loop_gap, closure, gauge_rows = 0, 0, [], 0.0, [], 0.0, []
    for seed in range(10):
        net = make(seed, 30, 70, 0.1, 1.0, 40.0)
        res = run(frame(net))
        dev, err = gauge_dev(res, net)
        beyond += int(np.sum(~(np.abs(dev) <= 3 * err)))
        c = comp_rows(res).iloc[0]
        g = res["sites_period"].set_index("site").loc[c["gauge"]]
        gauge_rows.append((float(g["phi_deg"]), float(g["phi_err_deg"])))
        outside += outside99(c)
        dofs.append(int(c["dof"]))
        red_gap = max(red_gap, abs(res["pairs_period"]["redundancy"].sum() - c["dof"]))
        loop_gap.append(len(res["loops"]) - c["dof"])
        clean = run(frame(net, psi=wrap(net["phi"][net["loc"]] - net["phi"][net["bas"]])))
        closure = max(closure, float(clean["loops"]["closure_deg"].abs().max()))
    check(beyond <= 5, f"N1.1 non-gauge site-seeds beyond 3 sigma or NaN: {beyond} of 290 (limit 5)")
    check(outside <= 1, f"N1.2 seeds with chi2/dof outside 99 %: {outside} of 10 (limit 1)")
    check(set(dofs) == {41}, f"N1.3 dof {sorted(set(dofs))} (expected 41)")
    check(red_gap <= 1e-9, f"N1.4 |sum redundancy - dof| {red_gap:.2e}")
    check(set(loop_gap) == {0}, f"N1.5 loops - dof {sorted(set(loop_gap))}")
    check(closure <= 1e-9, f"N1.6 largest noise-free loop closure {closure:.2e} deg")
    check(all(p == 0 and e == 0 for p, e in gauge_rows),
          f"N1.7 gauge rows (phi_deg, phi_err_deg) {sorted(set(gauge_rows))}")


def n2() -> None:
    net = make(0, 30, 70, 0.1, 1.0, 40.0)
    eq = frame(net, err=np.ones(70))
    ctrl = run(eq)
    lp = ctrl["loops"]
    check(all_row(ctrl)["chi2_dof"] <= 2 and lp["z"].abs().max() < 4.5,
          f"N2.3 control: chi2/dof {all_row(ctrl)['chi2_dof']:.3f}, largest |loop z| {lp['z'].abs().max():.2f}")
    j = int(np.flatnonzero(ctrl["pairs_period"]["redundancy"].to_numpy() > 0.3)[0])
    shifted = eq.copy()
    shifted.loc[j, "psi_deg"] = float(wrap(shifted.loc[j, "psi_deg"] + 20.0))
    res = run(shifted)
    check(all_row(res)["chi2_dof"] >= 2, f"N2.1 chi2/dof with pair {eq.loc[j, 'pair']} shifted: "
          f"{all_row(res)['chi2_dof']:.3f}")
    worst = res["loops"].iloc[int(np.argmax(res["loops"]["z"].abs()))]
    held = eq.loc[j, "pair"] in [p[1:] for p in worst["pairs"].split()]
    a = all_row(res)
    named = a["worst_loop_z"] == worst["z"] and a["worst_loop_sites"] == worst["sites"]
    check(held and named, f"N2.2 worst loop (z {worst['z']:.2f}) {worst['pairs']} holds {eq.loc[j, 'pair']}: "
          f"{held}; all row names it (z {a['worst_loop_z']:.2f}, sites {a['worst_loop_sites']}): {named}")


def n3() -> None:
    net = make(0, 30, 70, 0.1, 1.0, 40.0)
    eq = frame(net)
    rank_a = untied(network.gauge_rank(eq), eq)
    # The first site of rank_a has the largest count, so any site put before it is untied.
    side = net["phi"] > np.median(net["phi"])
    first = list(net["names"]).index(rank_a["site"].iloc[0])
    k = int(np.flatnonzero(side != side[first])[0])
    rank_b = pd.concat([rank_a[rank_a["site"] == net["names"][k]], rank_a[rank_a["site"] != net["names"][k]]],
                       ignore_index=True)
    a, b = run(eq, rank_a), run(eq, rank_b)
    ga, gb = comp_rows(a)["gauge"].iloc[0], comp_rows(b)["gauge"].iloc[0]
    sa, sb = a["sites_period"], b["sites_period"]
    d = wrap(sa["phi_deg"] - sb["phi_deg"])
    spread = float(np.max(np.abs(wrap(d - d[0]))))
    check(ga != gb and spread <= 1e-9, f"N3.1 gauges {ga} and {gb}; phi_deg(A) - phi_deg(B) spread {spread:.2e}")
    rel = float(np.max(np.abs(wrap(sa["phi_rel_deg"] - sb["phi_rel_deg"]))))
    check(rel <= 1e-9, f"N3.2 largest phi_rel_deg difference {rel:.2e}")
    ea, eb = sa["phi_rel_err_deg"].to_numpy(), sb["phi_rel_err_deg"].to_numpy()
    check(bool(np.all(np.abs(ea - eb) <= 1e-12 + 1e-6 * ea)),
          f"N3.3 largest phi_rel_err_deg difference {np.max(np.abs(ea - eb)):.2e}")
    ca, cb = comp_rows(a)["chi2"].iloc[0], comp_rows(b)["chi2"].iloc[0]
    check(abs(ca / cb - 1) <= 1e-9, f"N3.4 chi2 {ca:.12g} and {cb:.12g}")
    la, lb = (r["loops"].drop(columns="component") for r in (a, b))
    check(la.equals(lb), f"N3.5 loop tables equal but for the component label: {la.equals(lb)} ({len(la)} loops)")


def n4() -> None:
    nets = [make(0, 30, 70, 0.1, 1.0, 40.0, "A"), make(1, 30, 70, 0.1, 1.0, 40.0, "B")]
    for net, offset in zip(nets, (30.0, -40.0)):
        net["phi"] = net["phi"] + offset
    eqs = [frame(net).assign(flag_test=lambda e: e["err_deg"] > 0.5) for net in nets]
    both = pd.concat(eqs, ignore_index=True)
    res = run(both)
    alone = [run(eq) for eq in eqs]
    tops = [network.gauge_rank(eq)["site"].iloc[0] for eq in eqs]
    labels = list(comp_rows(res)["component"])
    check(sorted(labels) == sorted(tops), f"N4.1 components {labels}, top-ranked sites {tops}")
    sp = res["sites_period"].set_index("site")
    wrong = [s for net, top in zip(nets, tops) for s in net["names"] if sp.loc[s, "component"] != top]
    check(not wrong, f"N4.2 sites labelled by the other network: {wrong[:5] or 'none'}")
    d_rel = d_phi = 0.0
    for net, one in zip(nets, alone):
        so = one["sites_period"].set_index("site").loc[net["names"]]
        sj = sp.loc[net["names"]]
        d_rel = max(d_rel, float(np.max(np.abs(wrap(sj["phi_rel_deg"] - so["phi_rel_deg"])))))
        d_phi = max(d_phi, float(np.max(np.abs(wrap(sj["phi_deg"] - so["phi_deg"])))))
    check(d_rel <= 1e-9, f"N4.3 largest phi_rel_deg difference from each network alone {d_rel:.2e}")
    dofs = [int(all_row(one)["dof"]) for one in alone]
    check(all_row(res)["dof"] == sum(dofs), f"N4.4 pooled dof {all_row(res)['dof']}, alone {dofs}")
    check(d_phi <= 1e-9, f"N4.5 largest phi_deg difference from each network alone {d_phi:.2e}")
    sums = comp_rows(res)[["n_entered", "n_flag_test"]].sum()
    a = all_row(res)
    n_flag = int(both["flag_test"].sum())
    check(sums["n_entered"] == a["n_entered"] == len(both) and sums["n_flag_test"] == a["n_flag_test"] == n_flag > 0,
          f"N4.6 components' n_entered {sums['n_entered']} and n_flag_test {sums['n_flag_test']}; all row "
          f"{a['n_entered']} and {a['n_flag_test']}; built {len(both)} and {n_flag}")


def n5() -> None:
    for case, lo, hi in (("a", 0.5, 3.0), ("b", 0.2, 120.0)):
        bad, outside, closure, n52, n52_wrong = [], 0, 0.0, 0, []
        for seed in range(9000, 9200):
            net = make(seed, 20, 45, lo, hi, 170.0)
            res = run(frame(net))
            dev, err = gauge_dev(res, net)
            if np.any(~(np.abs(dev) <= 5 * err)):
                bad.append(seed)
            outside += outside99(comp_rows(res).iloc[0])
            n52 += int(np.sum(net["err"] > 52.0))
            if comp_rows(res)["n_err_over_52"].iloc[0] != np.sum(net["err"] > 52.0):
                n52_wrong.append(seed)
            if case == "a":
                clean = run(frame(net, psi=wrap(net["phi"][net["loc"]] - net["phi"][net["bas"]])))
                closure = max(closure, float(clean["loops"]["closure_deg"].abs().max()))
        check(not bad, f"N5.1 case {case}: seeds with a site beyond 5 sigma or NaN {bad or 'none'}")
        if case == "a":
            check(outside <= 6, f"N5.2 case a: seeds with chi2/dof outside 99 % {outside} of 200 (limit 6)")
            check(closure < 1e-9, f"N5.3 case a: largest noise-free loop closure {closure:.2e} deg")
        else:
            check(n52 > 0 and not n52_wrong, f"N5.4 case b: seeds whose n_err_over_52 is not the count of errors "
                                             f"over 52 deg {n52_wrong[:5] or 'none'} "
                                             f"({len(n52_wrong)} seeds; {n52} such errors)")
    far, far_wrong = 0, []
    for seed in range(9000, 9020):
        net = make(seed, 20, 45, 0.5, 3.0, 150.0)
        res = run(frame(net))
        phi = res["sites_period"]["phi_deg"].to_numpy()
        a = np.radians(2 * phi)
        centre = 0.5 * np.degrees(np.arctan2(np.sin(a).sum(), np.cos(a).sum()))
        n_far = int(np.sum(np.abs(wrap(phi - centre)) > 60.0))
        far += n_far
        if comp_rows(res)["n_far_from_centre"].iloc[0] != n_far:
            far_wrong.append(seed)
    check(far > 0 and not far_wrong, f"N5.5 potentials over 150 deg: seeds whose n_far_from_centre is not the count "
                                     f"of sites over 60 deg from the circular mean {far_wrong or 'none'} ({far} such "
                                     f"sites)")


def n6() -> None:
    rows = [("P1", "P2", 10.0), ("Q1", "Q2", 5.0), ("Q2", "Q3", -7.0), ("Q4", "Q3", 3.0)]
    tree = pd.DataFrame({"pair": [f"{a}-{b}" for a, b, _ in rows], "local": [a for a, _, _ in rows],
                         "base": [b for _, b, _ in rows], "psi_deg": [p for _, _, p in rows], "err_deg": 1.0,
                         "period_s": PERIOD, "entered": True, "reason": ""})
    eq = pd.concat([tree, frame(make(3, 6, 10, 0.5, 2.0, 40.0, "R"))], ignore_index=True)
    res = network.solve_periods(eq, network.gauge_rank(eq))
    sp = res["sites_period"].set_index("site")
    tree_sites = ["P1", "P2", "Q1", "Q2", "Q3", "Q4"]
    labels = set(sp.loc[tree_sites, "component"])
    ok = sp.loc[tree_sites, "solved"].all() and np.isfinite(sp.loc[tree_sites, "phi_rel_deg"]).all()
    check(bool(ok) and len(labels) == 2, f"N6.1 tree components {sorted(labels)} solved: {bool(ok)}")
    c = comp_rows(res).set_index("component")
    ct = c.loc[sorted(labels)]
    site_scale = sp.loc[tree_sites, "scale"]
    check(bool(ct["chi2_dof"].isna().all() and ct["scale"].isna().all() and (ct["dof"] == 0).all()
               and site_scale.isna().all()),
          f"N6.2 tree components dof {list(ct['dof'])}, chi2_dof {list(ct['chi2_dof'])}, scale {list(ct['scale'])}, "
          f"scale of their sites {sorted(set(site_scale.astype(str)))}")
    pp = res["pairs_period"]
    red = float(pp[pp["component"].isin(labels)]["redundancy"].abs().max())
    check(red <= 1e-12, f"N6.3 largest |redundancy| in the tree components {red:.2e}")
    gap = max(abs(sp.loc["P1", "phi_rel_deg"] - 5.0), abs(sp.loc["P2", "phi_rel_deg"] + 5.0))
    check(gap <= 1e-12, f"N6.4 2-site phi_rel {sp.loc['P1', 'phi_rel_deg']!r}, {sp.loc['P2', 'phi_rel_deg']!r} "
          f"(psi 10)")
    n_tree_loops = int(res["loops"]["component"].isin(labels).sum())
    check(n_tree_loops == 0, f"N6.5 loops in the tree components {n_tree_loops}")
    third = c.drop(index=sorted(labels)).iloc[0]
    a = all_row(res)
    check(a["dof"] == third["dof"] > 0 and a["chi2"] == third["chi2"],
          f"N6.6 all row dof {a['dof']} chi2 {a['chi2']!r}; third component dof {third['dof']} chi2 {third['chi2']!r}")


def n7() -> None:
    net = make(7, 10, 20, 4.0, 10.0, 40.0)
    base = frame(net)
    true = net["phi"][net["loc"][0]] - net["phi"][net["bas"][0]]
    e = np.array([1.0, 2.0, 3.0])
    psi = wrap(true + e * np.random.default_rng(70).standard_normal(3))
    parts = pd.concat([base.iloc[[0, 0, 0]].assign(psi_deg=psi, err_deg=e, pair=[f"part{k}" for k in "abc"]),
                       base.iloc[1:]], ignore_index=True)
    w = 1 / e ** 2
    combined = base.copy()
    combined.loc[0, ["psi_deg", "err_deg"]] = [np.sum(w * psi) / np.sum(w), np.sum(w) ** -0.5]
    rank = untied(network.gauge_rank(parts), parts)
    rp, rc = run(parts, rank), run(combined, rank)
    d = float(np.max(np.abs(wrap(rp["sites_period"]["phi_deg"] - rc["sites_period"]["phi_deg"]))))
    check(d <= 1e-9, f"N7.1 largest phi_deg difference, parts against combined {d:.2e}")
    dp, dc = all_row(rp)["dof"], all_row(rc)["dof"]
    check(dp - dc == 2, f"N7.2 dof with parts {dp}, combined {dc}")
    kinds = list(rp["loops"]["kind"])
    check(kinds.count("repeat") == 2, f"N7.3 repeat loops {kinds.count('repeat')} (kinds {kinds})")


def n8() -> None:
    hit_rel = hit_phi = 0
    chi = []
    for seed in range(1000):
        net = make(seed, 31, 70, 0.01, 0.05, 30.0)
        res = run(frame(net))
        sp = res["sites_period"].set_index("site").loc[net["names"]]
        pick = np.random.default_rng([seed, 1])
        rel_err = sp["phi_rel_err_deg"].to_numpy()
        i = int(pick.choice(np.flatnonzero(rel_err > 0)))
        truth = net["phi"] - np.median(net["phi"])
        hit_rel += abs(wrap(sp["phi_rel_deg"].iloc[i] - truth[i])) <= rel_err[i]
        dev, err = gauge_dev(res, net)
        k = int(pick.integers(0, dev.size))
        hit_phi += abs(dev[k]) <= err[k]
        chi.append(comp_rows(res)["chi2_dof"].iloc[0])
    dof = int(comp_rows(res)["dof"].iloc[0])
    check(abs(hit_rel / 1000 - 0.683) <= 0.044, f"N8.1 phi_rel coverage {hit_rel / 1000:.3f} (0.683 +- 0.044)")
    check(abs(hit_phi / 1000 - 0.683) <= 0.044, f"N8.2 phi_deg coverage {hit_phi / 1000:.3f} (0.683 +- 0.044)")
    lim = 3 * np.sqrt(2 / (dof * 1000))
    check(abs(np.mean(chi) - 1) <= lim, f"N8.3 mean chi2/dof {np.mean(chi):.4f} (1 +- {lim:.4f})")


def n9() -> None:
    e = np.arange(1.0, 6.0)
    one = pd.DataFrame({"period_s": [0.1, 0.2, 0.4, 0.8, 1.6], "site": "X", "component": "X",
                        "phi_rel_deg": 12.3, "phi_rel_err_deg": e, "solved": True, "errors_scaled": False})
    kept = one.copy()
    b = network.band_reading(one, 0.1, 1.6).iloc[0]
    ok = (abs(b["phi_rel_deg"] - 12.3) <= 1e-9 and abs(b["err_independent_deg"] - np.sum(e ** -2) ** -0.5) <= 1e-12
          and abs(b["err_correlated_deg"] - 1.5601) <= 1e-4)
    check(ok, f"N9.1 phi_rel {b['phi_rel_deg']!r}, independent {b['err_independent_deg']!r}, "
          f"correlated {b['err_correlated_deg']!r}")
    zero = one.assign(phi_rel_deg=[0.0, 3.0, -2.0, 4.0, 1.0], phi_rel_err_deg=[0.0, 2.0, 3.0, 4.0, 5.0])
    bz = network.band_reading(zero, 0.1, 1.6).iloc[0]
    b4 = network.band_reading(zero.iloc[1:], 0.1, 1.6).iloc[0]
    cols = ["phi_rel_deg", "err_independent_deg", "err_correlated_deg", "scatter_chi2_dof"]
    check(bz["n_zero_err"] == 1 and np.allclose(bz[cols].astype(float), b4[cols].astype(float), rtol=0, atol=1e-12),
          f"N9.2 n_zero_err {bz['n_zero_err']}; reading {list(bz[cols])} against the other four {list(b4[cols])}")
    b1 = network.band_reading(one, 0.1, 0.1).iloc[0]
    check(np.isnan(b1["scatter_chi2_dof"]), f"N9.3 one period: scatter_chi2_dof {b1['scatter_chi2_dof']}")
    check(one.equals(kept), f"N9.4 frame passed in unchanged: {one.equals(kept)}")
    moved = one.assign(component=["X", "X", "Y", "Y", "Y"])
    bm = network.band_reading(moved, 0.1, 1.6)
    check(len(bm) == 2 and list(bm["n_periods"]) == [2, 3],
          f"N9.5 site whose component changes: {len(bm)} rows, n_periods {list(bm['n_periods'])}")
    empty = network.band_reading(one, 10.0, 20.0)
    check(len(empty) == 0 and list(empty.columns) == list(b.index),
          f"N9.6 band without a solved row: {len(empty)} rows, columns {list(empty.columns)}")


def n10() -> None:
    net = make(0, 30, 70, 0.1, 1.0, 40.0)
    net["phi"] = net["phi"] / 40.0
    eq = frame(net)
    rank = untied(network.gauge_rank(eq), eq)
    _, _, _, cov = network.solve(eq, rank)
    names, x, C = next(iter(cov.values()))
    r1, r2 = run(eq, rank), run(eq.assign(err_deg=2 * eq["err_deg"]), rank)
    s1, s2 = (r["sites_period"].set_index("site").loc[names] for r in (r1, r2))
    gauge = s1["phi_err_deg"] > 0
    d_phi = float(np.max(np.abs(wrap(s2["phi_deg"] - s1["phi_deg"]))))
    d_err = float(np.max(np.abs(s2["phi_err_deg"][gauge] / (2 * s1["phi_err_deg"][gauge]) - 1)))
    c1, c2 = comp_rows(r1)["chi2"].iloc[0], comp_rows(r2)["chi2"].iloc[0]
    d_rel = float(np.max(np.abs(s2["phi_rel_err_deg"] - network.median_relative(x, 4 * C, 4000, SEED)[1])))
    check(d_phi <= 1e-9 and d_err <= 1e-12 and abs(c2 / (c1 / 4) - 1) <= 1e-9 and d_rel <= 1e-12,
          f"N10.1 errors x2: phi_deg {d_phi:.1e}, phi_err/2 {d_err:.1e} rel, chi2 x4 {abs(c2 / (c1 / 4) - 1):.1e} "
          f"rel, phi_rel_err against median_relative(x, 4C) {d_rel:.1e}")
    q = frame(make(5, 8, 16, 0.1, 1.0, 40.0, "Q"))
    half = pd.concat([eq.assign(err_deg=eq["err_deg"] / 2), q.assign(err_deg=2 * q["err_deg"])], ignore_index=True)
    rank_h = untied(network.gauge_rank(half), half)
    _, _, comps_h, cov_h = network.solve(half, rank_h)
    _, xh, Ch = cov_h[comps_h["component"].iloc[0]]
    names_q = cov_h[comps_h["component"].iloc[1]][0]
    plain, scaled = run(half, rank_h), run(half, rank_h, scale_by_closure=True)
    sp, ss = (r["sites_period"].set_index("site").loc[names] for r in (plain, scaled))
    s, s_q = comp_rows(scaled)["scale"]
    gauge = sp["phi_err_deg"] > 0
    d_err = float(np.max(np.abs(ss["phi_err_deg"][gauge] / (s * sp["phi_err_deg"][gauge]) - 1)))
    d_rel = float(np.max(np.abs(ss["phi_rel_err_deg"] - network.median_relative(xh, s ** 2 * Ch, 4000, SEED)[1])))
    qp, qs = (r["sites_period"].set_index("site").loc[names_q] for r in (plain, scaled))
    q_same = (qp["phi_err_deg"].equals(qs["phi_err_deg"]) and qp["phi_rel_err_deg"].equals(qs["phi_rel_err_deg"])
              and not qs["errors_scaled"].any())
    check(s > 1.5 and d_err <= 1e-12 and d_rel <= 1e-12 and bool(ss["errors_scaled"].all()) and s_q < 1 and q_same,
          f"N10.2 scale {s:.3f}: phi_err x scale {d_err:.1e} rel, phi_rel_err against median_relative(x, s^2 C) "
          f"{d_rel:.1e}, errors_scaled on {int(ss['errors_scaled'].sum())} of {len(ss)} sites; component Q at "
          f"scale {s_q:.3f} left as it was: {q_same}")
    n_set = sum(int(r["sites_period"]["errors_scaled"].sum()) for r in (r1, r2, plain))
    check(n_set == 0, f"N10.3 rows with errors_scaled in the runs without scale_by_closure: {n_set}")


def g1() -> None:
    star = [("C", f"L{k}") for k in range(1, 6)] + [("Y", "C"), ("Y", "C")]
    p1 = star + [("L1", "L2"), ("C", "L3")]
    eq = pd.DataFrame([(a, b, t) for t, edges in ((1.0, p1), (2.0, star)) for a, b in edges],
                      columns=["local", "base", "period_s"])
    rank = network.gauge_rank(eq)
    got = list(zip(rank["rank"], rank["site"], rank["n_equations"], rank["n_partners"]))
    # Y has more equations and fewer partners than L1, so it ranks above L1 only when equations count first.
    want = [(1, "C", 15, 6), (2, "Y", 4, 1), (3, "L1", 3, 2), (4, "L2", 3, 2), (5, "L3", 3, 1), (6, "L4", 2, 1),
            (7, "L5", 2, 1)]
    check(got == want, f"G1.1 star ranking {got}")
    ring = pd.DataFrame({"pair": ["W1-W2", "W2-W3", "W3-W4", "W4-W1"], "local": ["W1", "W2", "W3", "W4"],
                         "base": ["W2", "W3", "W4", "W1"], "psi_deg": [10.0, -4.0, 7.5, -12.0], "err_deg": 1.0,
                         "period_s": PERIOD, "entered": True, "reason": ""})
    try:
        tied = network.solve_periods(ring, network.gauge_rank(ring))
    except Exception as exc:  # the run must go on through a tie
        check(False, f"G1.3 the run stopped on a gauge tie: {exc!r}")
        return
    check(True, "G1.3 the run went on through a gauge tie")
    c = comp_rows(tied).iloc[0]
    sp = tied["sites_period"]
    ref = run(ring)["sites_period"]
    d = float(np.max(np.abs(wrap(sp["phi_rel_deg"] - ref["phi_rel_deg"]))))
    ok = (c["gauge"] == "" and c["gauge_tie"] == "W1 W2 W3 W4" and sp["phi_deg"].isna().all()
          and sp["phi_err_deg"].isna().all() and sp["solved"].all() and d <= 1e-9)
    check(ok, f"G1.2 ring: gauge {c['gauge']!r}, gauge_tie {c['gauge_tie']!r}, phi_deg NaN "
          f"{bool(sp['phi_deg'].isna().all())}, solved {bool(sp['solved'].all())}, phi_rel against untied {d:.1e}")


def e1() -> None:
    tri = pd.DataFrame({"pair": ["A-B", "B-C", "C-A"], "local": ["A", "B", "C"], "base": ["B", "C", "A"],
                        "psi_deg": [10.0, -4.0, -5.0], "err_deg": [1.0, 2.0, 3.0], "period_s": PERIOD,
                        "entered": True, "reason": ""})
    rank = network.gauge_rank(tri)
    for label, column, value in (("psi NaN", "psi_deg", np.nan), ("error NaN", "err_deg", np.nan),
                                 ("error 0", "err_deg", 0.0)):
        bad = tri.copy()
        bad.loc[1, column] = value
        try:
            network.solve_periods(bad, rank)
            got = "no error"
        except ValueError as exc:
            got = f"ValueError: {exc}"
        check(got.startswith("ValueError") and "B-C" in got, f"E1.1 entered row with {label}: {got}")
    try:
        network.solve(tri, rank, max_iter=0)
        got = "no error"
    except Exception as exc:
        got = f"{type(exc).__name__}: {exc}"
    check(got.startswith("ValueError") and "at least 1" in got, f"E1.2 max_iter 0: {got}")


def main() -> int:
    print(f"network from {network.__file__}")
    for test in (w1, n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, g1, e1):
        test()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
