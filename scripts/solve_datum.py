# -*- coding: utf-8 -*-
"""
Network datum: one potential per site at every period from inter-site pair products

Each pair product of scripts/process_intersite.py (or scripts/merge_tensor_bands.py)
gives psi(l, b) = arg(det T) / 2 with its error at every period, and over a
network of pairs psi(l, b) = phi_l - phi_b modulo 180 deg. This script reads
the products a pairs table lists and solves every period of their shared
band layout with `mt_workbench.network.solve_periods`: one potential per
site, each connected component on its own gauge, the potentials relative
to the component median with their errors, the closure (chi2/dof) and the
loop each pair closes.

The pairs table is a CSV with one row per product: `sidecar` (the product's
JSON sidecar; a relative path is taken against <workspace>/tf), and
optionally `use` (false keeps the product listed but out of the solve),
`note` (copied to the run record) and `base` (the node name of a base stack,
whose sidecar `base_site` is null). Every row of every product is written
to datum_pairs_period.csv with `entered` and `reason`. Rows not estimated
or without an error cannot enter; `use` false and `--leave-out-flag` are the
only ways to leave a row out, and both are counted. No error is scaled
unless `--scale-by-closure` is given. `--band LO-HI` writes datum_bands.csv,
a reading of the per-period table and never an input to the solve.

Refused (exit 2): two band layouts (two periods closer than relative 0.1 and
further apart than relative 1e-9), a sidecar or its CSV missing, products of
mixed tensors, a stack product without `base`, a `base` beside a named base
that differs from it, a product listed twice, a `use` that is not true or
false, a `--leave-out-flag` that no product carries, and an out folder that
exists. Writes datum_sites_period.csv, datum_periods.csv, datum_loops.csv,
datum_pairs_period.csv, datum_run.json (and datum_bands.csv with --band)
into `--out`, by default <workspace>/datum/<pairs table stem>, a new folder.

Usage:
    python scripts/solve_datum.py SURVEY_YAML --pairs PAIRS_CSV [--out DIR]
        [--scale-by-closure] [--leave-out-flag NAME ...] [--band LO-HI ...]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import mt_workbench  # noqa: E402
from mt_workbench import intersite, network  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

N_DRAWS = 4000  # Monte Carlo draws of the median-relative error
SEED = 0  # first part of every period's seed
SAME_PERIOD = 1e-9  # relative difference of two periods taken as one period
OTHER_LAYOUT = 0.1  # inside one layout consecutive periods differ by at least 17 %
PHI_ERR_MEANING = ("phi_err_deg is the formal error given the pair errors. When chi2/dof is outside its 99 % "
                   "interval it is not a measured error, and datum_pairs_period.csv (z, redundancy) shows whether "
                   "the misfit is spread over the network or sits on a few pairs.")
PAIRS_COLUMNS = ["pair", "local", "base", "period_s", "psi_deg", "err_deg", "entered", "reason"]
SOLVE_ORDER = ["component", "in_tree", "model_deg", "resid_deg", "z", "n_wrap", "redundancy"]


class Refused(ValueError):
    """A run that cannot go ahead as asked (exit 2)."""


def band_range(text: str) -> tuple[float, float]:
    """Parse LO-HI (seconds, LO < HI) for --band; exponents such as 1e-3 are read."""
    for i, ch in enumerate(text):
        if ch == "-" and i > 0 and text[i - 1] not in "eE":
            try:
                lo, hi = float(text[:i]), float(text[i + 1:])
            except ValueError:
                continue
            if 0 < lo < hi:
                return lo, hi
    raise argparse.ArgumentTypeError(f"{text!r} is not LO-HI in seconds with 0 < LO < HI")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of solve_datum.py."""
    p = argparse.ArgumentParser(prog="solve_datum.py", description=__doc__.strip().splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("survey_yaml")
    p.add_argument("--pairs", required=True, metavar="PAIRS_CSV", help="the pairs table, one row per product")
    p.add_argument("--out", default=None, metavar="DIR",
                   help="a new folder for the tables (in use: <workspace>/datum/<pairs table stem>)")
    p.add_argument("--scale-by-closure", action="store_true",
                   help="multiply the site errors of a component whose sqrt(chi2/dof) is over 1 by it")
    p.add_argument("--leave-out-flag", action="append", default=[], metavar="NAME",
                   help="leave the rows carrying this flag out of the solve (repeatable; counted)")
    p.add_argument("--band", action="append", default=[], type=band_range, metavar="LO-HI",
                   help="write datum_bands.csv, a reading of the per-period values over LO-HI s (repeatable)")
    return p


def sha256(path: Path) -> str:
    """Return the SHA-256 of a file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_pairs(path: Path, workspace: Path) -> list[dict]:
    """Read the pairs table and each product's sidecar and CSV.

    Raises:
        Refused: For a missing column, sidecar or CSV, a `use` that is not
            true or false, a product listed twice, mixed tensors, a stack
            product without `base`, or a `base` that differs from a named one.
    """
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "sidecar" not in table.columns:
        raise Refused(f"{path}: the pairs table has no sidecar column")
    products = []
    for row in table.to_dict("records"):
        sidecar = Path(row["sidecar"].strip())
        sidecar = sidecar if sidecar.is_absolute() else workspace / "tf" / sidecar
        if not sidecar.is_file():
            raise Refused(f"{sidecar}: no such sidecar")
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        csv = sidecar.parent / meta["csv"]
        if not csv.is_file():
            raise Refused(f"{sidecar.stem}: its CSV {csv} is missing")
        use = row.get("use", "").strip().lower()
        if use not in ("", "true", "1", "yes", "false", "0", "no"):
            raise Refused(f"{sidecar.stem}: use {row['use']!r} is not true or false")
        given = row.get("base", "").strip()
        if meta["base_site"] is None and not given:
            raise Refused(f"{sidecar.stem}: a stack product (base_site null) needs the node name in the base column")
        if meta["base_site"] is not None and given and given != meta["base_site"]:
            raise Refused(f"{sidecar.stem}: the pairs table's base {given} differs from the sidecar's base_site "
                          f"{meta['base_site']}")
        est, _letter = intersite.read_csv(csv)
        products.append({"stem": sidecar.stem, "sidecar": sidecar, "csv": csv, "meta": meta, "est": est,
                         "local": meta["local"], "base": meta["base_site"] or given, "tensor": meta["tensor"],
                         "use": use not in ("false", "0", "no"), "note": row.get("note", "")})
    stems = [p["stem"] for p in products]
    twice = sorted({s for s in stems if stems.count(s) > 1})
    if twice:
        raise Refused(f"listed more than once: {', '.join(twice)}")
    tensors = {p["tensor"] for p in products}
    if len(tensors) > 1:
        raise Refused("mixed tensors: " + "; ".join(
            f"{t}: {', '.join(p['stem'] for p in products if p['tensor'] == t)}" for t in sorted(tensors)))
    return products


def lattice(products: list[dict]) -> np.ndarray:
    """Return the sorted union of the products' periods, periods within relative 1e-9 merged.

    Raises:
        Refused: When two periods differ by more than relative 1e-9 and less
            than relative 0.1: two band layouts, the products of each named.
    """
    periods = np.unique(np.concatenate([p["est"].period for p in products]))
    out = [periods[0]]
    for t in periods[1:]:
        gap = (t - out[-1]) / t
        if gap <= SAME_PERIOD:
            continue
        if gap < OTHER_LAYOUT:
            holds = [[p["stem"] for p in products if np.any(np.abs(p["est"].period - v) <= SAME_PERIOD * v)]
                     for v in (out[-1], t)]
            raise Refused(f"two band layouts: periods {float(out[-1])!r} s ({', '.join(holds[0])}) and "
                          f"{float(t)!r} s ({', '.join(holds[1])}) differ by {100 * gap:.2f} %")
        out.append(t)
    return np.array(out)


def equations(products: list[dict], periods: np.ndarray, leave_out: list[str]) -> pd.DataFrame:
    """Return every row of every product as an equation with `entered` and the first `reason` that applies."""
    frames = []
    for p in products:
        est = p["est"]
        flags = est.flags()
        psi, err = np.asarray(est.half_arg_deg, float), np.asarray(est.half_arg_err_deg, float)
        reason = np.full(psi.size, "", dtype=object)
        for name in reversed(leave_out):
            reason[flags[name]] = f"flag:{name}"
        if not p["use"]:
            reason[:] = "use=false"
        with np.errstate(invalid="ignore"):
            reason[~(np.isfinite(err) & (err > 0))] = "no_error"
        reason[flags["flag_not_estimated"] | ~np.isfinite(psi)] = "not_estimated"
        snapped = periods[np.argmin(np.abs(np.log(est.period[:, None] / periods[None, :])), axis=1)]
        frames.append(pd.DataFrame({"pair": p["stem"], "local": p["local"], "base": p["base"], "period_s": snapped,
                                    "psi_deg": psi, "err_deg": err, "entered": reason == "", "reason": reason,
                                    **flags}))
    return pd.concat(frames, ignore_index=True)


def positions(survey: Survey, nodes: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Return the survey positions of the nodes and the nodes without one."""
    rows, missing = [], []
    known = set(survey.site_names())
    for node in nodes:
        site = survey.site(node) if node in known else None
        if site is None or site.latitude is None or site.longitude is None:
            missing.append(node)
        else:
            rows.append({"site": node, "latitude": float(site.latitude), "longitude": float(site.longitude)})
    return pd.DataFrame(rows, columns=["site", "latitude", "longitude"]), missing


def git_commit() -> str | None:
    """Return the repository's HEAD commit, or None when git cannot tell."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except Exception:
        return None


def records(df: pd.DataFrame) -> list:
    """Return a table as JSON records, NaN as null."""
    return json.loads(df.to_json(orient="records"))


def period_line(t: float, rows: pd.DataFrame, flagged: int) -> str:
    """Return the printed line of one period from its rows of datum_periods.csv and its entered rows flagged."""
    a = rows[rows["component"] == "all"].iloc[0]
    comps = rows[rows["component"] != "all"]
    text = (f"{t:.6g} s: {int(a['n_entered'])}/{int(a['n_rows'])} entered, {flagged} of them flagged; components "
            f"{' '.join(str(int(n)) for n in comps['n_sites']) or 'none'}")
    if a["dof"] > 0:
        inside = a["chi2_dof_lo99"] <= a["chi2_dof"] <= a["chi2_dof_hi99"]
        text += (f"; chi2/dof {a['chi2_dof']:.3f} (dof {int(a['dof'])}, {'inside' if inside else 'outside'} "
                 f"{a['chi2_dof_lo99']:.2f}-{a['chi2_dof_hi99']:.2f})")
    else:
        text += "; dof 0, closure not tested"
    if np.isfinite(a["worst_loop_z"]):
        text += f"; worst loop z {a['worst_loop_z']:+.2f} ({a['worst_loop_sites']})"
    ties = comps[comps["gauge_tie"].astype(str) != ""]
    if len(ties):
        text += "; gauge tie " + ", ".join(ties["gauge_tie"])
    if not comps["converged"].astype(bool).all():
        text += "; not converged " + ", ".join(comps.loc[~comps["converged"].astype(bool), "component"])
    return text


def main(argv=None) -> int:
    """Solve the datum and write its tables; return the exit code."""
    args = build_parser().parse_args(argv)
    started = dt.datetime.now().astimezone()
    survey = Survey.from_yaml(args.survey_yaml)
    pairs_path = Path(args.pairs)
    out = Path(args.out) if args.out else survey.workspace / "datum" / pairs_path.stem
    try:
        if out.exists():
            raise Refused(f"{out} exists: each run writes a new folder")
        products = read_pairs(pairs_path, survey.workspace)
        if not products:
            raise Refused(f"{pairs_path}: no product listed")
        periods = lattice(products)
        carried = set(products[0]["est"].flags())
        unknown = [f for f in args.leave_out_flag if f not in carried]
        if unknown:
            raise Refused(f"--leave-out-flag {', '.join(unknown)}: the products carry {', '.join(sorted(carried))}")
    except Refused as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    eq = equations(products, periods, args.leave_out_flag)
    flags = [c for c in eq.columns if c.startswith("flag_")]
    nodes = sorted(set(eq["local"]) | set(eq["base"]))
    xy, no_position = positions(survey, nodes)
    print(f"survey {survey.name} ({args.survey_yaml}); {len(products)} products, tensor {products[0]['tensor']}; "
          f"{periods.size} periods {periods[0]:.6g}-{periods[-1]:.6g} s; {len(nodes)} nodes")
    print(f"options: scale by closure {args.scale_by_closure}; left-out flags {args.leave_out_flag or 'none'}; "
          f"bands {[f'{lo:g}-{hi:g}' for lo, hi in args.band] or 'none'}; draws {N_DRAWS}, seed {SEED}")
    for node in no_position:
        print(f"WARNING {node} is not a site of survey.yaml with a position: its loops have no length")
    rank = network.gauge_rank(eq[eq["entered"]])
    tables = network.solve_periods(eq, rank, xy, scale_by_closure=args.scale_by_closure, n_draws=N_DRAWS,
                                   seed=SEED)
    per = tables["periods"]
    counts = [c for c in per.columns if c.startswith("n_")] + ["dof", "iterations"]
    per = per.astype({c: "Int64" for c in counts})
    marked = [f for f in flags if f != "flag_not_estimated"]
    flagged = eq[marked].any(axis=1)[eq["entered"]].groupby(eq["period_s"]).sum()
    for t, rows in per.groupby("period_s", sort=True):
        print(period_line(t, rows, int(flagged.get(t, 0))))
    pairs = tables["pairs_period"]
    pairs = pairs[PAIRS_COLUMNS + flags + SOLVE_ORDER]
    out.mkdir(parents=True)
    paths = {name: out / f"datum_{name}.csv" for name in ("sites_period", "periods", "loops", "pairs_period")}
    tables["sites_period"].to_csv(paths["sites_period"], index=False, float_format="%.17g")
    per.to_csv(paths["periods"], index=False, float_format="%.17g")
    tables["loops"].to_csv(paths["loops"], index=False, float_format="%.17g")
    pairs.to_csv(paths["pairs_period"], index=False, float_format="%.17g")
    if args.band:
        bands = pd.concat([network.band_reading(tables["sites_period"], lo, hi) for lo, hi in args.band],
                          ignore_index=True)
        paths["bands"] = out / "datum_bands.csv"
        bands.to_csv(paths["bands"], index=False, float_format="%.17g")
    comps = per[per["component"] != "all"]
    flag_rules = {}
    for p in products:
        for name, block in (p["meta"].get("flags") or {}).items():
            flag_rules.setdefault(name, [])
            if block.get("rule") not in flag_rules[name]:
                flag_rules[name].append(block.get("rule"))
    record = {
        "inputs": {
            "survey_yaml": str(args.survey_yaml), "survey": survey.name,
            "pairs": {"path": str(pairs_path), "sha256": sha256(pairs_path)},
            "products": [{"pair": p["stem"], "local": p["local"], "base": p["base"], "use": p["use"],
                          "note": p["note"], "rows": int(p["est"].period.size),
                          "sidecar": {"path": str(p["sidecar"]), "sha256": sha256(p["sidecar"])},
                          "csv": {"path": str(p["csv"]), "sha256": sha256(p["csv"])},
                          "coh_out_weighted": ("present" if np.isfinite(p["est"].coh_out_weighted).any() else
                                               "absent: flag_low_coherence is false on every row")}
                         for p in products],
            "flag_rules": flag_rules, "nodes_without_position": no_position},
        "options": {"scale_by_closure": bool(args.scale_by_closure), "leave_out_flags": args.leave_out_flag,
                    "bands": [[lo, hi] for lo, hi in args.band], "n_draws": N_DRAWS, "seed": SEED,
                    "seed_rule": "the draws of a period use the seed [seed, round(period_s * 1e6)]"},
        "lattice_s": [float(t) for t in periods],
        "gauge_rank": records(rank),
        "totals": {"rows": len(eq), "rows_by_reason": {(r or "entered"): int(n) for r, n in
                                                       eq["reason"].value_counts().sort_index().items()},
                   "entered_rows_flagged": {f: int((eq[f] & eq["entered"]).sum()) for f in flags},
                   "entered": int(eq["entered"].sum()),
                   "gauge_ties": int((comps["gauge_tie"].astype(str) != "").sum()),
                   "components_not_converged": int((~comps["converged"].astype(bool)).sum())},
        "phi_err_deg": PHI_ERR_MEANING,
        "product_of_record": "phi_rel_deg and phi_rel_err_deg of datum_sites_period.csv",
        "versions": {"mt_workbench": mt_workbench.__version__, "git_commit": git_commit()},
        "started": started.isoformat(),
    }
    if args.band:
        record["bands"] = ("datum_bands.csv is a reading of datum_sites_period.csv over each band, never an input "
                           "to the solve")
    record["finished"] = dt.datetime.now().astimezone().isoformat()
    paths["run"] = out / "datum_run.json"
    paths["run"].write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
