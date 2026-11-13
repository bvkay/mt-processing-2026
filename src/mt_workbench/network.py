# -*- coding: utf-8 -*-
"""
Network datum: one potential per site from the inter-site phases

A pair product gives at every period psi(l, b) = arg(det T) / 2 with its
error (`mt_workbench.intersite`), and over a network of pairs
psi(l, b) = phi_l - phi_b modulo 180 deg. `solve` finds one potential per
site at one period by weighted least squares, each connected component on
its own gauge site: it starts from the most precise spanning tree and moves
equations by whole turns of 180 deg until the branch settles.
`median_relative` gives the potentials relative to the component median,
with a Monte Carlo error, `loops` the closing loop of every equation
outside the start tree, `solve_periods` all of these at every period, and
`band_reading` a summary of a period range that is never an input.

Angles are in degrees, periods in seconds, errors one standard deviation.
psi and phi are defined modulo 180 deg; `wrap` maps to (-90, 90], the
interval of the pair product. The functions on tables take and return
DataFrames with named columns. The caller chooses the equations that
enter; an error is multiplied only when the caller asks, and the solve
neither rotates a value nor leaves out an equation.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import heapq

import numpy as np
import pandas as pd
from scipy import stats

from mt_workbench.survey import distance_km

WRAP = 180.0
# Sites further than this from their component's circular centre (deg) sit
# near the cut of the half circle the median is taken on. They are counted.
FAR_DEG = 60.0
# 180 / sqrt(12), the spread of a value uniform on the circle. An equation
# with a larger error counts one degree of freedom but adds at most
# (90 / err)^2 < 1 to chi2, so it pulls chi2/dof low. Such equations are counted.
ERR_UNINFORMATIVE_DEG = 52.0
SOLVE_COLUMNS = ["component", "in_tree", "n_wrap", "model_deg", "resid_deg", "z", "redundancy"]


def wrap(d) -> np.ndarray:
    """Map angles in degrees to (-90, 90], the interval of the pair product's psi (0 as +0.0)."""
    return 0.0 - ((-np.asarray(d, dtype=float) + WRAP / 2) % WRAP - WRAP / 2)


def _circular_mean(d, w=1.0) -> float:
    """Weighted circular mean of angles in degrees with period 180."""
    a = np.radians(2 * np.asarray(d, dtype=float))
    return 0.5 * float(np.degrees(np.arctan2(np.sum(w * np.sin(a)), np.sum(w * np.cos(a)))))


def components(local, base) -> list[list[str]]:
    """Return the connected components of the graph whose edges are the equations.

    Args:
        local: Local site of each equation.
        base: Base site of each equation.

    Returns:
        list[list[str]]: Each component as a sorted list of sites, the
        largest first, then by the first site's name.
    """
    neighbours = {}
    for a, b in zip(local, base):
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    seen, out = set(), []
    for start in sorted(neighbours):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            s = stack.pop()
            comp.append(s)
            for t in neighbours[s] - seen:
                seen.add(t)
                stack.append(t)
        out.append(sorted(comp))
    return sorted(out, key=lambda c: (-len(c), c[0]))


def gauge_rank(eq: pd.DataFrame) -> pd.DataFrame:
    """Rank the sites by their equations and partners.

    The first site of the ranking present in a component labels it and is
    its gauge (`solve`). The site name only fixes the order of the table.

    Args:
        eq: The entered equations of all periods, with `local` and `base`.

    Returns:
        pd.DataFrame: One row per site: `rank`, `site`, `n_equations` (its
        equations over all periods) and `n_partners` (distinct other sites
        it shares an equation with), sorted by the two counts, largest
        first, then by name.
    """
    ends = pd.concat([eq[["local", "base"]].set_axis(["site", "other"], axis=1),
                      eq[["base", "local"]].set_axis(["site", "other"], axis=1)])
    out = ends.groupby("site")["other"].agg(n_equations="size", n_partners="nunique").reset_index()
    out = out.sort_values(["n_equations", "n_partners", "site"], ascending=[False, False, True], ignore_index=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    return out


def _start_tree(loc, bas, psi, err, gauge) -> tuple[dict, np.ndarray]:
    """Set each site from the most precise equation that reaches it (Prim's rule).

    Equal errors are taken in row order. Returns the start potentials by
    site and which rows form the tree.
    """
    touching = {}
    for j, (l, b) in enumerate(zip(loc, bas)):
        touching.setdefault(l, []).append(j)
        touching.setdefault(b, []).append(j)
    phi, in_tree = {gauge: 0.0}, np.zeros(len(loc), dtype=bool)
    heap = [(err[j], j) for j in touching[gauge]]
    heapq.heapify(heap)
    while heap:
        _, j = heapq.heappop(heap)
        l, b = loc[j], bas[j]
        if (l in phi) == (b in phi):
            continue
        new = b if l in phi else l
        phi[new] = phi[l] - psi[j] if l in phi else phi[b] + psi[j]
        in_tree[j] = True
        for k in touching[new]:
            heapq.heappush(heap, (err[k], k))
    return phi, in_tree


def solve(eq: pd.DataFrame, rank: pd.DataFrame, max_iter: int = 50):
    """Solve one period for one potential per site, every component on its own gauge.

    The gauge is the first site of `rank` in the component, which labels
    it. When the next site of `rank` in the component has the same two
    counts the gauge is tied: the component is solved on the label site
    all the same, its `phi_deg` and `phi_err_deg` are NaN and `gauge_tie`
    names the tied sites. From the start tree the equations are moved by
    n_j = round((A x - psi) / 180) whole turns and solved again until n
    stops changing, at most `max_iter` times (`converged`). `phi_err_deg`
    is the formal error given the pair errors; `scale`, sqrt(chi2/dof), is
    reported and never applied here.

    Args:
        eq: The entered equations of one period: `pair`, `local`, `base`,
            `psi_deg`, `err_deg`; other columns are carried along.
        rank: The ranking of `gauge_rank`.
        max_iter: Most solves of the unwrap loop, at least 1.

    Returns:
        tuple: `sites` (`site`, `component`, `component_size`,
        `n_equations`, `phi_deg`, `phi_err_deg`); `eq` with the columns
        SOLVE_COLUMNS; `comps` (one row per component); and the covariance
        `{component: (sites, x, C_full)}`, x the continuous potentials on
        the working gauge and C_full their covariance, zero at the gauge.

    Raises:
        ValueError: When an equation has no finite psi or no finite,
            positive error, naming its pair, or when max_iter is under 1.
    """
    if max_iter < 1:
        raise ValueError(f"max_iter is {max_iter}: the unwrap loop needs at least 1 solve")
    loc_all, bas_all = eq["local"].to_numpy(), eq["base"].to_numpy()
    psi_all, err_all = eq["psi_deg"].to_numpy(float), eq["err_deg"].to_numpy(float)
    unusable = ~(np.isfinite(psi_all) & np.isfinite(err_all) & (err_all > 0))
    if unusable.any():
        raise ValueError("an equation needs a finite psi and a finite, positive error: "
                         + ", ".join(str(p) for p in eq["pair"].to_numpy()[unusable]))
    new = {c: np.full(len(eq), np.nan) for c in SOLVE_COLUMNS}
    new["component"] = np.full(len(eq), "", dtype=object)
    new["in_tree"] = np.zeros(len(eq), dtype=bool)
    counts = {s: (a, b) for s, a, b in zip(rank["site"], rank["n_equations"], rank["n_partners"])}
    site_rows, comp_rows, cov = [], [], {}
    for comp in components(loc_all, bas_all):
        ranked = [s for s in rank["site"] if s in set(comp)]
        label = ranked[0]
        tie = len(ranked) > 1 and counts[ranked[1]] == counts[label]
        rows = np.flatnonzero(np.isin(loc_all, comp))
        loc, bas, psi, err = loc_all[rows], bas_all[rows], psi_all[rows], err_all[rows]
        w = 1.0 / err ** 2
        unknown = [s for s in comp if s != label]
        col = {s: i for i, s in enumerate(unknown)}
        A = np.zeros((rows.size, len(unknown)))
        for j, (l, b) in enumerate(zip(loc, bas)):
            if l in col:
                A[j, col[l]] += 1.0
            if b in col:
                A[j, col[b]] -= 1.0
        start, in_tree = _start_tree(loc, bas, psi, err, label)
        x = np.array([start[s] for s in unknown])
        N_inv = np.linalg.inv(A.T @ (w[:, None] * A))
        n = np.round((A @ x - psi) / WRAP)
        for iterations in range(1, max_iter + 1):
            psi_used = psi + WRAP * n
            x = N_inv @ (A.T @ (w * psi_used))
            n, n_used = np.round((A @ x - psi) / WRAP), n
            if np.array_equal(n, n_used):
                break
        model = A @ x
        resid = psi_used - model
        dof = rows.size - (len(comp) - 1)
        # A tree fits exactly: its residuals are rounding only.
        chi2 = float(np.sum(w * resid ** 2)) if dof > 0 else 0.0
        chi2_dof = chi2 / dof if dof > 0 else np.nan
        for name, values in (("component", label), ("in_tree", in_tree), ("n_wrap", n_used + 0.0),
                             ("model_deg", model), ("resid_deg", resid), ("z", resid / err),
                             ("redundancy", 1.0 - w * np.einsum("ij,jk,ik->i", A, N_inv, A))):
            new[name][rows] = values
        k = [comp.index(s) for s in unknown]
        x_full, C_full = np.zeros(len(comp)), np.zeros((len(comp), len(comp)))
        x_full[k] = x
        C_full[np.ix_(k, k)] = N_inv
        cov[label] = (comp, x_full, C_full)
        n_site = pd.Series(np.concatenate([loc, bas])).value_counts()
        phi, phi_err = wrap(x_full), np.sqrt(np.diag(C_full))
        for i, s in enumerate(comp):
            site_rows.append({"site": s, "component": label, "component_size": len(comp),
                              "n_equations": int(n_site[s]), "phi_deg": np.nan if tie else phi[i],
                              "phi_err_deg": np.nan if tie else phi_err[i]})
        tied = [s for s in ranked if counts[s] == counts[label]] if tie else []
        comp_rows.append({"component": label, "gauge": "" if tie else label, "gauge_tie": " ".join(tied),
                          "n_sites": len(comp), "n_equations": rows.size, "dof": dof, "chi2": chi2,
                          "chi2_dof": chi2_dof, "scale": np.sqrt(chi2_dof), "iterations": iterations,
                          "converged": bool(np.array_equal(n, n_used))})
    out = eq.copy()
    for name in SOLVE_COLUMNS:
        out[name] = new[name]
    out["n_wrap"] = out["n_wrap"].astype("Int64")
    sites = pd.DataFrame(site_rows, columns=["site", "component", "component_size", "n_equations", "phi_deg",
                                             "phi_err_deg"])
    comps = pd.DataFrame(comp_rows, columns=["component", "gauge", "gauge_tie", "n_sites", "n_equations", "dof",
                                             "chi2", "chi2_dof", "scale", "iterations", "converged"])
    return sites, out, comps, cov


def median_relative(x: np.ndarray, C: np.ndarray, n_draws: int = 4000, seed=0) -> tuple[np.ndarray, np.ndarray]:
    """Return one component's potentials relative to its median, with their errors.

    The values are first centred on their circular mean (period 180), so
    the median is taken on a half circle. The error is the standard
    deviation of d_i - median(d) over draws d of the centred values with
    the covariance P C P, P = I - 11'/n, which does not depend on the
    gauge. Where the values are far apart against their errors the middle
    site is the median in every draw and its error is exactly 0. A scale
    s enters as `median_relative(x, s**2 * C)`: the error is not linear in it.

    Args:
        x: The continuous potentials of one component (deg), on any gauge.
        C: Their covariance (deg^2), C_full of `solve`.
        n_draws: Number of Monte Carlo draws.
        seed: Anything `np.random.default_rng` accepts.

    Returns:
        tuple: `phi_rel_deg` and `phi_rel_err_deg`, in the order of x.
    """
    v = wrap(x - _circular_mean(x))
    P = np.eye(v.size) - 1.0 / v.size
    ev, U = np.linalg.eigh(P @ C @ P)
    S = (U * np.sqrt(np.clip(ev, 0, None))) @ U.T
    d = v + np.random.default_rng(seed).standard_normal((n_draws, v.size)) @ S
    return wrap(v - np.median(v)), (d - np.median(d, axis=1, keepdims=True)).std(axis=0)


def loops(eq: pd.DataFrame, xy: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return the loop each equation outside the start tree closes, for one component.

    The loop is the equation j from its base b to its local l and the
    start tree's path back from b to l. Its closure is psi_j minus the
    path's potential difference: a tree equation walked from s to t enters
    with sign -1 if its local is t and its base s, else +1. The loops are
    the fundamental cycles of the tree: there are dof of them, and a pair
    given twice makes a 2-site `repeat` loop. The raw psi is used, so a
    loop closing near +-90 deg shows itself.

    Args:
        eq: The `equations` frame of `solve` for one component.
        xy: Positions, `site`, `latitude`, `longitude`; None gives NaN lengths.

    Returns:
        pd.DataFrame: One row per loop: `loop` (the non-tree pair), `kind`,
        `sites` (from b along the tree to l), `pairs` (signed), `closure_deg`,
        `sigma_deg`, `z` and `length_km`.
    """
    loc, bas, stems = eq["local"].to_numpy(), eq["base"].to_numpy(), eq["pair"].to_numpy()
    psi, err, tree = eq["psi_deg"].to_numpy(float), eq["err_deg"].to_numpy(float), eq["in_tree"].to_numpy(bool)
    pos = {} if xy is None else dict(zip(xy["site"], zip(xy["latitude"], xy["longitude"])))
    columns = ["loop", "kind", "sites", "pairs", "closure_deg", "sigma_deg", "z", "length_km"]
    if not len(eq) or tree.all():
        return pd.DataFrame(columns=columns)
    tree_rows = {}
    for j in np.flatnonzero(tree):
        tree_rows.setdefault(loc[j], []).append(j)
        tree_rows.setdefault(bas[j], []).append(j)
    root = loc[0]
    parent, depth, stack = {root: (None, None)}, {root: 0}, [root]
    while stack:
        s = stack.pop()
        for j in tree_rows.get(s, []):
            t = bas[j] if loc[j] == s else loc[j]
            if t not in depth:
                parent[t], depth[t] = (s, j), depth[s] + 1
                stack.append(t)
    out = []
    for j in np.flatnonzero(~tree):
        a, b, up, down = bas[j], loc[j], [], []
        while a != b:
            if depth[a] >= depth[b]:
                up.append(a)
                a = parent[a][0]
            else:
                down.append(b)
                b = parent[b][0]
        path = up + [a] + down[::-1]
        terms = [(j, 1)]
        for s, t in zip(path[:-1], path[1:]):
            e = parent[s][1] if parent[s][0] == t else parent[t][1]
            terms.append((e, -1 if (loc[e] == t and bas[e] == s) else 1))
        ends = [(loc[e], bas[e]) for e, _ in terms]
        length = sum(distance_km(*pos[p], *pos[q]) if p in pos and q in pos else np.nan for p, q in ends)
        closure = float(wrap(sum(sign * psi[e] for e, sign in terms)))
        sigma = float(np.sqrt(sum(err[e] ** 2 for e, _ in terms)))
        out.append({"loop": stems[j], "kind": "repeat" if len(path) == 2 else "cycle", "sites": " ".join(path),
                    "pairs": " ".join(("+" if sign > 0 else "-") + str(stems[e]) for e, sign in terms),
                    "closure_deg": closure, "sigma_deg": sigma, "z": closure / sigma, "length_km": length})
    return pd.DataFrame(out, columns=columns)


def _closure(eq: pd.DataFrame, flags: list, dof: int, chi2: float, lp: pd.DataFrame) -> dict:
    """Counts and closure columns of a component's row, or of a period's `all` row, of the periods table."""
    worst = lp.iloc[int(np.argmax(lp["z"].abs()))] if len(lp) else None
    ratio = chi2 / dof if dof > 0 else np.nan
    return {"n_entered": len(eq), **{f"n_{f}": int(eq[f].astype(bool).sum()) for f in flags},
            "dof": dof, "chi2": chi2, "chi2_dof": ratio, "scale": np.sqrt(ratio),
            "chi2_dof_lo99": stats.chi2.ppf(0.005, dof) / dof if dof > 0 else np.nan,
            "chi2_dof_hi99": stats.chi2.ppf(0.995, dof) / dof if dof > 0 else np.nan,
            "worst_loop_z": np.nan if worst is None else worst["z"],
            "worst_loop_sites": "" if worst is None else worst["sites"],
            "n_err_over_52": int((eq["err_deg"] > ERR_UNINFORMATIVE_DEG).sum())}


def solve_periods(eq: pd.DataFrame, rank: pd.DataFrame, xy: pd.DataFrame | None = None,
                  scale_by_closure: bool = False, n_draws: int = 4000, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Solve every period of the lattice from its entered equations.

    Per period: `solve`, then per component `median_relative` with the seed
    [seed, round(period_s * 1e6)], so a new period changes no other
    period's draws, and `loops`. With `scale_by_closure`, a component whose
    `scale` s is over 1 gets `phi_err_deg` times s and `phi_rel_err_deg`
    from `median_relative(x, s**2 C_full)` with the same seed, and
    `errors_scaled` on its rows; chi2, pair `z` and the loops keep the
    errors as entered. The pooled `all` row of a period sums chi2 and dof
    over its components.

    Args:
        eq: Every pair row of every period: the columns of `solve` and
            `period_s`, `entered`, `reason`; `flag_*` columns are counted.
        rank: The ranking of `gauge_rank`.
        xy: Positions for `loops`, or None.
        scale_by_closure: Scale the site errors of components with chi2/dof over 1.
        n_draws: Draws of `median_relative`.
        seed: First part of the seed of every period's draws.

    Returns:
        dict: `sites_period`, `periods`, `pairs_period` and `loops`.
    """
    eq = eq.reset_index(drop=True)
    nodes = sorted(set(eq["local"]) | set(eq["base"]))
    flags = [c for c in eq.columns if c.startswith("flag_")]
    sites_out, periods_out, pairs_out, loops_out = [], [], [], []
    for period, rows in eq.groupby("period_s", sort=True):
        sites, equations, comps, cov = solve(rows[rows["entered"].astype(bool)], rank)
        pairs_out.append(rows.join(equations[SOLVE_COLUMNS]))
        sites = sites.set_index("site")
        sites["phi_rel_deg"], sites["phi_rel_err_deg"], sites["scale"] = np.nan, np.nan, np.nan
        sites["errors_scaled"] = False
        draw_seed = [seed, int(round(float(period) * 1e6))]
        all_lp, comp_rows = [], []
        for c in comps.itertuples(index=False):
            names, x, C = cov[c.component]
            rel, rel_err = median_relative(x, C, n_draws, draw_seed)
            if scale_by_closure and np.isfinite(c.scale) and c.scale > 1:
                rel_err = median_relative(x, c.scale ** 2 * C, n_draws, draw_seed)[1]
                sites.loc[names, "phi_err_deg"] *= c.scale
                sites.loc[names, "errors_scaled"] = True
            sites.loc[names, "phi_rel_deg"], sites.loc[names, "phi_rel_err_deg"] = rel, rel_err
            sites.loc[names, "scale"] = c.scale
            ce = equations[equations["component"] == c.component]
            lp = loops(ce, xy)
            lp.insert(0, "component", c.component)
            all_lp.append(lp)
            comp_rows.append({**c._asdict(), **_closure(ce, flags, c.dof, c.chi2, lp),
                              "n_far_from_centre": int(np.sum(np.abs(wrap(x - _circular_mean(x))) > FAR_DEG))})
        lp = pd.concat(all_lp, ignore_index=True) if all_lp else pd.DataFrame(columns=["component"])
        lp.insert(0, "period_s", period)
        loops_out.append(lp)
        reason = rows["reason"].fillna("").astype(str)
        comp_rows.append({
            "component": "all", "gauge": "", "gauge_tie": "", "n_rows": len(rows),
            "n_not_estimated": int((reason == "not_estimated").sum()), "n_no_error": int((reason == "no_error").sum()),
            "n_left_out": int(((reason == "use=false") | reason.str.startswith("flag:")).sum()),
            "n_sites": int(comps["n_sites"].sum()), "n_equations": len(equations),
            **_closure(equations, flags, int(comps["dof"].sum()), float(comps["chi2"].sum()), lp),
            "iterations": int(comps["iterations"].max()) if len(comps) else 0,
            "converged": bool(comps["converged"].all()),
            "n_far_from_centre": int(sum(r["n_far_from_centre"] for r in comp_rows))})
        periods_out.append(pd.DataFrame(comp_rows).assign(period_s=period))
        sp = sites.reindex(nodes).rename_axis("site").reset_index()
        sp["solved"] = sp["component"].notna()
        sp = sp.fillna({"component": "", "component_size": 0, "n_equations": 0, "errors_scaled": False})
        sp = sp.astype({"component_size": int, "n_equations": int, "errors_scaled": bool})
        sp.insert(0, "period_s", period)
        sites_out.append(sp)
    periods = pd.concat(periods_out, ignore_index=True)
    first = ["period_s", "component", "gauge", "gauge_tie", "n_rows", "n_not_estimated", "n_no_error", "n_left_out",
             "n_entered"]
    return {"sites_period": pd.concat(sites_out, ignore_index=True),
            "periods": periods[first + [c for c in periods.columns if c not in first]],
            "pairs_period": pd.concat(pairs_out, ignore_index=True),
            "loops": pd.concat(loops_out, ignore_index=True)}


def band_reading(sites_period: pd.DataFrame, lo: float, hi: float) -> pd.DataFrame:
    """Summarise the solved per-period values of a period range, one row per site and component.

    A reading of `solve_periods`' table, never an input to it. The value is
    the circular mean (period 180) weighted by 1 / phi_rel_err^2 over the
    rows with a positive error; rows with error 0 (the median site of
    their period) are counted in `n_zero_err` and enter only when every
    row has error 0. Both errors are written: `err_independent_deg`, right
    if the periods are independent, and `err_correlated_deg`, right if
    their errors are fully correlated. No row is dropped.

    Args:
        sites_period: The `sites_period` table of `solve_periods`.
        lo: Shortest period of the range (s), included.
        hi: Longest period of the range (s), included.

    Returns:
        pd.DataFrame: `band_lo_s`, `band_hi_s`, `site`, `component`,
        `n_periods`, `n_periods_lattice`, `n_zero_err`, `phi_rel_deg`,
        `err_independent_deg`, `err_correlated_deg`, `scatter_chi2_dof`,
        `errors_scaled`.
    """
    band = sites_period[(sites_period["period_s"] >= lo) & (sites_period["period_s"] <= hi)]
    out = []
    for (site, comp), g in band[band["solved"].astype(bool)].groupby(["site", "component"], sort=True):
        v, e = g["phi_rel_deg"].to_numpy(float), g["phi_rel_err_deg"].to_numpy(float)
        pos = e > 0
        if pos.any():
            v, e, w = v[pos], e[pos], 1.0 / e[pos] ** 2
            mean = _circular_mean(v, w)
            err_ind, err_cor = np.sum(w) ** -0.5, np.sum(w * e) / np.sum(w)
            scatter = np.sum(w * wrap(v - mean) ** 2) / (v.size - 1) if v.size > 1 else np.nan
        else:
            mean, err_ind, err_cor, scatter = _circular_mean(v), 0.0, 0.0, np.nan
        out.append({"band_lo_s": lo, "band_hi_s": hi, "site": site, "component": comp, "n_periods": len(g),
                    "n_periods_lattice": band["period_s"].nunique(), "n_zero_err": int(np.sum(~pos)),
                    "phi_rel_deg": mean, "err_independent_deg": err_ind, "err_correlated_deg": err_cor,
                    "scatter_chi2_dof": scatter, "errors_scaled": bool(g["errors_scaled"].astype(bool).any())})
    # Named columns keep the header of a band that holds no solved row.
    return pd.DataFrame(out, columns=["band_lo_s", "band_hi_s", "site", "component", "n_periods", "n_periods_lattice",
                                      "n_zero_err", "phi_rel_deg", "err_independent_deg", "err_correlated_deg",
                                      "scatter_chi2_dof", "errors_scaled"])
