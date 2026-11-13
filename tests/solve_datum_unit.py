# -*- coding: utf-8 -*-
"""
Unit test for scripts/solve_datum.py, the network datum from pair products

The pair products are built here and written by the package's own writers:
each CSV by `mt_workbench.intersite.write_csv` from a `TensorEstimate`, each
sidecar by process_rr.py's `write_sidecar` with the flags block of
process_intersite.py's `flag_block`, so a change of the product that the
script does not follow fails here. A diagonal row has T = exp(i psi) I and
an off-diagonal row T = exp(i psi) [[0, 1], [-1, 0]]; both have
arg(det T) / 2 = psi, `half_arg_deg` = psi, 20 jackknife groups and a
weighted coherence of 1. psi = wrap(phi_l - phi_b + err N(0, 1)) with six
sites A to F whose potentials phi_true are uniform over 60 deg (so that
some |psi| exceed 45 deg and carry flag_re_det_negative), errors
log-uniform from 0.3 to 2 deg, five periods 0.01 * 4**(k / 6) s, numpy seed
1. A correct build passes with this seed.

The set S1 holds ten products on one layout: B-A, C-A, D-A, E-A, F-B, C-B,
D-C, E-D, A-F (the reverse direction) and B-A again (a second part), plus
F-E, whose sidecar has only the keys a burst-merged sidecar has and whose
CSV is written as scripts/merge_tensor_bands.py writes it (with `source`
and `sample_rate` columns). Two rows have T not finite (not estimated),
three have T finite and no error, four are off-diagonal. Most sidecars are
listed relative to <workspace>/tf, one with its full path.

Usage:
    python tests/solve_datum_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

S1 (end to end, default out folder)
  1. the script exits non-zero;
  2. any of datum_sites_period.csv, datum_periods.csv, datum_loops.csv,
     datum_pairs_period.csv or datum_run.json is missing, or the run
     record lacks the SHA-256 of the pairs table or of a product's
     sidecar or CSV, inputs.flag_rules, options.seed_rule, lattice_s,
     gauge_rank, totals, phi_err_deg, versions, started or finished;
  3. datum_pairs_period.csv has a row count other than the sum of the
     products' rows;
  4. the sums over periods of n_not_estimated, n_no_error,
     n_flag_off_diagonal, n_flag_re_det_negative or n_entered on the `all`
     rows differ from the counts built in (taken from `flags()` of the
     estimates), or no entered row carries flag_re_det_negative (so that
     count was not put to the test);
  5. a row carrying a flag other than flag_not_estimated has
     entered = False;
  6. more than 1 solved site-period has
     |wrap(phi_rel - (phi_true - median(phi_true)))| > 3 phi_rel_err, the
     median over the component's solved sites, or a phi_rel is NaN (false
     failure about 0.003 over 30 site-periods);
  7. there is no loop, or a loop's length_km is not finite or differs by
     more than 1e-9 relative from the sum of distance_km over the edges of
     its pairs, positions from survey.yaml;
  8. the run record's totals.entered_rows_flagged differs, for any flag,
     from the sum over periods of n_<flag> on the `all` rows (both count
     entered rows; two rows not estimated carry flag_not_estimated and
     must not count).
S2 (options)
  1. with --leave-out-flag flag_off_diagonal: n_left_out is not 4 in all,
     a row carrying the flag has a reason other than
     flag:flag_off_diagonal, or the run record lacks the option;
  2. on S1 with every written error halved (chi2/dof near 4), with
     --scale-by-closure: phi_err_deg is not the default run's times
     `scale` within 1e-12 relative where scale > 1 (and unchanged where
     it is not), errors_scaled differs from scale > 1 on a solved row, or
     no row has scale > 1;
  3. the default run of the halved set shows errors_scaled, or its
     phi_err_deg is not half that of S1 within 1e-12 relative (the
     formal error follows the written errors and nothing more).
S3 (layouts)
  1. a product on periods 0.5 % or 5 % off the layout beside one on the
     layout is not refused with exit 2 naming both products;
  2. S1 with a product holding only the first three periods of the
     layout is not accepted, or its pairs table's rows are not all
     written (S1 itself is the control for the burst-merged form).
S4 (refusals, use and a stack base)
  1. mixed tensors (one product of M), a sidecar whose CSV is missing, a
     stack product (base_site null) without `base`, or a second run into
     an out folder that exists, does not refuse with exit 2;
  2. a product with use = false does not give all its rows
     reason use=false and entered = False, counted in n_left_out;
  3. a stack product with `base` STACK_E does not enter under STACK_E, or
     STACK_E is not a solved site.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.network import wrap  # noqa: E402
from mt_workbench.survey import distance_km  # noqa: E402
from process_intersite import flag_block  # noqa: E402
from process_rr import write_sidecar  # noqa: E402

SCRIPT = REPO / "scripts" / "solve_datum.py"
SCRATCH = scratch_dir("solve_datum_unit")
SITES = ["A", "B", "C", "D", "E", "F"]
PERIODS = 0.01 * 4.0 ** (np.arange(5) / 6)
PRODUCTS = [("B", "A", ""), ("C", "A", ""), ("D", "A", ""), ("E", "A", ""), ("F", "B", ""), ("C", "B", ""),
            ("D", "C", ""), ("E", "D", ""), ("A", "F", ""), ("B", "A", "_p2"), ("F", "E", "_wide")]
NOT_ESTIMATED = [(6, 3), (7, 4)]  # (product, period)
NO_ERROR = [(1, 0), (4, 2), (10, 1)]
OFF_DIAGONAL = [(2, 0), (2, 1), (5, 3), (8, 4)]
FILES = ["datum_sites_period.csv", "datum_periods.csv", "datum_loops.csv", "datum_pairs_period.csv",
         "datum_run.json"]

SURVEY_YAML = """name: solve_datum_unit
instrument: lemi423
sample_rate: 150
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  A: {{latitude: -30.00, longitude: 140.00}}
  B: {{latitude: -30.01, longitude: 140.00}}
  C: {{latitude: -30.00, longitude: 140.01}}
  D: {{latitude: -30.02, longitude: 140.01}}
  E: {{latitude: -30.01, longitude: 140.02}}
  F: {{latitude: -30.02, longitude: 140.02}}
"""

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def estimate(psi, err, periods=PERIODS, off=(), bad=()) -> intersite.TensorEstimate:
    """Return an estimate with arg(det T) / 2 = psi; rows `off` off-diagonal, rows `bad` not estimated."""
    n = len(periods)
    tensor = np.exp(1j * np.radians(psi))[:, None, None] * np.eye(2)[None]
    for i in off:
        tensor[i] = np.exp(1j * np.radians(psi[i])) * np.array([[0, 1], [-1, 0]])
    half, half_err = np.array(psi, float), np.array(err, float)
    windows = np.full(n, 100)
    for i in bad:
        tensor[i], half[i], half_err[i], windows[i] = np.nan, np.nan, np.nan, 0
    det = tensor[:, 0, 0] * tensor[:, 1, 1] - tensor[:, 0, 1] * tensor[:, 1, 0]
    ones = np.ones((n, 2))
    return intersite.TensorEstimate(
        period=np.asarray(periods, float), f_lo=0.9 / np.asarray(periods), f_hi=1 / (0.9 * np.asarray(periods)),
        f_mean=1 / np.asarray(periods), f_weighted=1 / np.asarray(periods), level=np.zeros(n, int),
        n_windows=windows, n_harm=np.full(n, 5), n_groups=np.full(n, 20), tensor=tensor,
        sigma=np.full((n, 2, 2), 0.01), det=det, abs_det_err=np.full(n, 0.01), half_arg_deg=half,
        half_arg_err_deg=half_err, coh_out=ones, coh_in=ones, coh_out_weighted=ones,
        frac_downweighted=np.zeros((n, 2)))


def write_product(tf: Path, stem: str, est, local: str, base, letter: str = "T", merged: bool = False) -> Path:
    """Write a product's CSV and sidecar as the package writes them; return the sidecar."""
    csv = tf / f"{stem}.csv"
    if merged:  # the form of scripts/merge_tensor_bands.py
        frame = est.frame(letter)
        frame["source"], frame["sample_rate"] = "continuous", 150.0
        frame.to_csv(csv, index=False, float_format="%.17g")
        meta = {"local": local, "base_site": base, "tensor": letter, "csv": csv.name}
    else:
        intersite.write_csv(est, letter, csv)
        meta = {"kind": "telluric" if letter == "T" else "magnetic", "tensor": letter, "local": local,
                "base_site": base, "csv": csv.name, "flags": flag_block(est)}
    write_sidecar(tf / f"{stem}.json", meta)
    return tf / f"{stem}.json"


def build(tf: Path, err_factor: float = 1.0) -> tuple[list, dict]:
    """Write S1's products (errors written times err_factor); return their (stem, est) and phi_true."""
    r = np.random.default_rng(1)
    phi = dict(zip(SITES, r.uniform(0, 60, len(SITES))))
    out = []
    for k, (loc, bas, tag) in enumerate(PRODUCTS):
        err = np.exp(r.uniform(np.log(0.3), np.log(2.0), PERIODS.size))
        psi = wrap(phi[loc] - phi[bas] + err * r.standard_normal(PERIODS.size))
        written = err * err_factor
        written[[i for p, i in NO_ERROR if p == k]] = np.nan
        est = estimate(psi, written, off=[i for p, i in OFF_DIAGONAL if p == k],
                       bad=[i for p, i in NOT_ESTIMATED if p == k])
        stem = f"{loc}_te-{bas}_rr-R{tag}"
        write_product(tf, stem, est, loc, bas, merged=tag == "_wide")
        out.append((stem, est))
    return out, phi


def pairs_table(path: Path, tf: Path, stems, extra: dict | None = None) -> Path:
    """Write a pairs table: sidecars relative to <workspace>/tf, the first with its full path."""
    rows = [{"sidecar": str(tf / f"{s}.json") if i == 0 else f"{s}.json", "use": "true", "note": f"row {i}",
             "base": ""} for i, s in enumerate(stems)]
    for row in rows:
        row.update((extra or {}).get(Path(row["sidecar"]).stem, {}))
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def run(yaml_path: Path, pairs: Path, *opts) -> subprocess.CompletedProcess:
    """Run the script."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "--pairs", str(pairs), *opts],
                          capture_output=True, text=True, cwd=REPO)


def all_rows(out: Path) -> pd.DataFrame:
    """Return the `all` rows of datum_periods.csv."""
    per = pd.read_csv(out / "datum_periods.csv", keep_default_na=False, na_values=[""])
    return per[per["component"] == "all"]


def s1(yaml_path, tf, work, products, phi) -> Path | None:
    """S1 items 1 to 6, with the default out folder."""
    stems = [s for s, _ in products]
    pairs = pairs_table(SCRATCH / "s1_pairs.csv", tf, stems)
    res = run(yaml_path, pairs)
    print(res.stdout[-2500:])
    if not check(res.returncode == 0, f"S1.1 exit {res.returncode}"):
        print(res.stderr[-3000:])
        return None
    out = work / "datum" / "s1_pairs"
    absent = [f for f in FILES if not (out / f).is_file()]
    if not check(not absent, f"S1.2 files missing in the default out folder: {absent or 'none'}"):
        return None
    rec = json.loads((out / "datum_run.json").read_text(encoding="utf-8"))
    inputs, options = rec.get("inputs", {}), rec.get("options", {})
    keys = {"inputs.pairs.sha256": inputs.get("pairs", {}).get("sha256"),
            "inputs.products sha256": [p.get(k, {}).get("sha256") for p in inputs.get("products", [{}])
                                       for k in ("sidecar", "csv")],
            "inputs.flag_rules": inputs.get("flag_rules"), "options.seed_rule": options.get("seed_rule"),
            **{k: rec.get(k) for k in ("lattice_s", "gauge_rank", "totals", "phi_err_deg", "versions", "started",
                                       "finished")}}
    lost = [k for k, v in keys.items() if v is None or v == [] or (isinstance(v, list) and None in v)]
    check(not lost, f"S1.2 run record keys missing: {lost or 'none'}")
    pp = pd.read_csv(out / "datum_pairs_period.csv", keep_default_na=False, na_values=[""])
    n_rows = sum(e.period.size for _, e in products)
    check(len(pp) == n_rows, f"S1.3 datum_pairs_period.csv rows {len(pp)} (products' rows {n_rows})")
    flags = [e.flags() for _, e in products]
    est_rows = [~f["flag_not_estimated"] & np.isfinite(e.half_arg_err_deg) for f, (_, e) in zip(flags, products)]
    built = {"n_not_estimated": sum(int(f["flag_not_estimated"].sum()) for f in flags),
             "n_no_error": sum(int((~f["flag_not_estimated"] & ~np.isfinite(e.half_arg_err_deg)).sum())
                               for f, (_, e) in zip(flags, products)),
             "n_flag_off_diagonal": sum(int((f["flag_off_diagonal"] & k).sum()) for f, k in zip(flags, est_rows)),
             "n_flag_re_det_negative": sum(int((f["flag_re_det_negative"] & k).sum())
                                           for f, k in zip(flags, est_rows)),
             "n_entered": sum(int(k.sum()) for k in est_rows)}
    a = all_rows(out)
    got = {c: int(a[c].sum()) if c in a else None for c in built}
    check(got == built and built["n_flag_re_det_negative"] > 0 and built["n_flag_off_diagonal"] == 4,
          f"S1.4 counts over periods {got} (built {built})")
    names = [c for c in pp.columns if c.startswith("flag_") and c != "flag_not_estimated"]
    marked = pp[names].astype(bool).any(axis=1)
    out_rows = pp[marked & ~pp["entered"].astype(bool)]
    check(not len(out_rows), f"S1.5 flagged rows not entered: {len(out_rows)} of {int(marked.sum())} flagged "
                             f"({sorted(set(out_rows['reason']))})")
    sp = pd.read_csv(out / "datum_sites_period.csv", keep_default_na=False, na_values=[""])
    bad, n = [], 0
    for (t, comp), g in sp[sp["solved"].astype(bool)].groupby(["period_s", "component"]):
        true = np.array([phi[s] for s in g["site"]])
        dev = np.abs(wrap(g["phi_rel_deg"].to_numpy() - (true - np.median(true))))
        far = ~(dev <= 3 * g["phi_rel_err_deg"].to_numpy())
        n += len(g)
        bad += [f"{s} {t:.4g} s" for s in g["site"][far]]
    check(len(bad) <= 1 and n >= 25, f"S1.6 site-periods beyond 3 sigma or NaN {bad} of {n} solved (limit 1)")
    pos = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))["sites"]
    ends = {p: (lo, ba) for p, lo, ba in pp[["pair", "local", "base"]].drop_duplicates().itertuples(index=False)}
    lp = pd.read_csv(out / "datum_loops.csv", keep_default_na=False, na_values=[""])
    wrong = []
    for row in lp.itertuples(index=False):
        edges = [ends[p[1:]] for p in row.pairs.split()]
        want = sum(distance_km(pos[a]["latitude"], pos[a]["longitude"], pos[b]["latitude"], pos[b]["longitude"])
                   for a, b in edges)
        if not (np.isfinite(row.length_km) and abs(row.length_km - want) <= 1e-9 * want):
            wrong.append(f"{row.loop} {row.length_km!r} (sum {want!r})")
    check(len(lp) > 0 and not wrong, f"S1.7 loops whose length_km is not the sum of their edges: "
                                     f"{wrong[:3] or 'none'} of {len(lp)}")
    flag_names = [c for c in pp.columns if c.startswith("flag_")]
    in_record = rec.get("totals", {}).get("entered_rows_flagged", {})
    summed = {f: int(a[f"n_{f}"].sum()) for f in flag_names}
    check(in_record == summed, f"S1.8 run record entered_rows_flagged {in_record}; sums of n_<flag> {summed}")
    return out


def s2(yaml_path, tf, work, products, s1_out) -> None:
    """S2 items 1 to 3."""
    stems = [s for s, _ in products]
    pairs = pairs_table(SCRATCH / "s2_pairs.csv", tf, stems)
    out = SCRATCH / "s2_leave"
    res = run(yaml_path, pairs, "--out", str(out), "--leave-out-flag", "flag_off_diagonal")
    if check(res.returncode == 0, f"S2.1 leave-out run exit {res.returncode}"):
        pp = pd.read_csv(out / "datum_pairs_period.csv", keep_default_na=False, na_values=[""])
        reasons = sorted(set(pp.loc[pp["flag_off_diagonal"].astype(bool), "reason"]))
        options = json.loads((out / "datum_run.json").read_text(encoding="utf-8")).get("options", {})
        n_left = int(all_rows(out)["n_left_out"].sum())
        check(n_left == 4 and reasons == ["flag:flag_off_diagonal"]
              and options.get("leave_out_flags") == ["flag_off_diagonal"],
              f"S2.1 n_left_out {n_left}, reasons of the flagged rows {reasons}, run record "
              f"leave_out_flags {options.get('leave_out_flags')}")
    else:
        print(res.stderr[-3000:])
    half_tf = SCRATCH / "half" / "tf"
    half_tf.mkdir(parents=True)
    build(half_tf, err_factor=0.5)
    half_pairs = SCRATCH / "s2_half.csv"
    pd.DataFrame({"sidecar": [str(half_tf / f"{s}.json") for s in stems]}).to_csv(half_pairs, index=False)
    outs = {}
    for label, opts in (("default", ()), ("scaled", ("--scale-by-closure",))):
        res = run(yaml_path, half_pairs, "--out", str(SCRATCH / f"s2_{label}"), *opts)
        if not check(res.returncode == 0, f"S2.2 {label} run exit {res.returncode}"):
            print(res.stderr[-3000:])
            return
        outs[label] = pd.read_csv(SCRATCH / f"s2_{label}" / "datum_sites_period.csv", keep_default_na=False,
                                  na_values=[""])
    d, s = outs["default"], outs["scaled"]
    solved = d["solved"].astype(bool).to_numpy()
    scale = d["scale"].to_numpy()
    over = solved & (scale > 1)
    expect = np.where(over, d["phi_err_deg"] * scale, d["phi_err_deg"])
    rel = np.abs(s["phi_err_deg"].to_numpy() - expect)[solved] / np.maximum(expect[solved], 1e-300)
    flagged = s["errors_scaled"].astype(str).str.lower().eq("true").to_numpy()
    check(over.any() and np.nanmax(rel) <= 1e-12 and np.array_equal(flagged[solved], over[solved]),
          f"S2.2 rows with scale > 1 {int(over.sum())} of {int(solved.sum())}; largest relative difference from "
          f"default x scale {np.nanmax(rel):.1e}; errors_scaled where scale > 1 "
          f"{np.array_equal(flagged[solved], over[solved])}")
    base = pd.read_csv(s1_out / "datum_sites_period.csv", keep_default_na=False, na_values=[""])
    shown = d["errors_scaled"].astype(str).str.lower().eq("true").any()
    half = np.abs(d["phi_err_deg"].to_numpy() - base["phi_err_deg"].to_numpy() / 2)[solved]
    rel = half / np.maximum(base["phi_err_deg"].to_numpy()[solved] / 2, 1e-300)
    check(not shown and np.nanmax(rel) <= 1e-12 and np.isfinite(d["phi_err_deg"].to_numpy()[solved]).all(),
          f"S2.3 default run: errors_scaled shown {shown}; largest relative difference from half of S1's "
          f"phi_err_deg {np.nanmax(rel):.1e}")


def s3(yaml_path, tf, products) -> None:
    """S3 items 1 and 2."""
    r = np.random.default_rng(11)
    on = write_product(tf, "B_te-A_rr-R_s3", estimate(r.uniform(-5, 5, 5), np.ones(5)), "B", "A")
    for pct in (0.5, 5.0):
        stem = f"C_te-A_rr-R_off{pct:g}"
        write_product(tf, stem, estimate(r.uniform(-5, 5, 5), np.ones(5), periods=PERIODS * (1 + pct / 100)),
                      "C", "A")
        res = run(yaml_path, pairs_table(SCRATCH / f"s3_{pct:g}.csv", tf, [on.stem, stem]), "--out",
                  str(SCRATCH / f"s3_{pct:g}"))
        check(res.returncode == 2 and on.stem in res.stderr and stem in res.stderr,
              f"S3.1 {pct:g} % off: exit {res.returncode}, names both products "
              f"{on.stem in res.stderr and stem in res.stderr}: {res.stderr.strip()[-300:]}")
    write_product(tf, "D_te-B_rr-R_half", estimate(r.uniform(-5, 5, 3), np.ones(3), periods=PERIODS[:3]), "D", "B")
    stems = [s for s, _ in products] + ["D_te-B_rr-R_half"]
    out = SCRATCH / "s3_half"
    res = run(yaml_path, pairs_table(SCRATCH / "s3_half.csv", tf, stems), "--out", str(out))
    if not check(res.returncode == 0, f"S3.2 half-layout product: exit {res.returncode}"):
        print(res.stderr[-3000:])
        return
    pp = pd.read_csv(out / "datum_pairs_period.csv")
    n_rows = sum(e.period.size for _, e in products) + 3
    check(len(pp) == n_rows and pp["period_s"].nunique() == PERIODS.size,
          f"S3.2 rows {len(pp)} (products' rows {n_rows}), periods {pp['period_s'].nunique()} (layout {PERIODS.size})")


def s4(yaml_path, tf, products, s1_pairs: Path) -> None:
    """S4 items 1 to 3."""
    r = np.random.default_rng(13)
    first = products[0][0]
    m = write_product(tf, "C_hm-A_rr-R", estimate(r.uniform(-5, 5, 5), np.ones(5)), "C", "A", letter="M")
    lost = write_product(tf, "C_te-A_rr-R_lost", estimate(r.uniform(-5, 5, 5), np.ones(5)), "C", "A")
    (tf / "C_te-A_rr-R_lost.csv").unlink()
    stack = write_product(tf, "D_te-stackE_rr-R", estimate(r.uniform(-5, 5, 5), np.ones(5)), "D", None)
    cases = {"mixed tensors": ([first, m.stem], "mixed tensors"), "CSV missing": ([first, lost.stem], "missing"),
             "stack without base": ([first, stack.stem], "base column")}
    for k, (label, (stems, words)) in enumerate(cases.items()):
        out = SCRATCH / f"s4_case{k}"
        res = run(yaml_path, pairs_table(SCRATCH / f"s4_case{k}.csv", tf, stems), "--out", str(out))
        check(res.returncode == 2 and words in res.stderr and not out.exists(),
              f"S4.1 {label}: exit {res.returncode}: {res.stderr.strip()[-200:]}")
    res = run(yaml_path, s1_pairs)
    check(res.returncode == 2 and "exists" in res.stderr,
          f"S4.1 second run into the default out folder: exit {res.returncode}: {res.stderr.strip()[-200:]}")
    off = products[5][0]
    stems = [s for s, _ in products] + [stack.stem]
    pairs = pairs_table(SCRATCH / "s4_use.csv", tf, stems,
                        {off: {"use": "false"}, stack.stem: {"base": "STACK_E"}})
    out = SCRATCH / "s4_use"
    res = run(yaml_path, pairs, "--out", str(out))
    if not check(res.returncode == 0, f"S4.2 run with use = false and a stack base: exit {res.returncode}"):
        print(res.stderr[-3000:])
        return
    pp = pd.read_csv(out / "datum_pairs_period.csv", keep_default_na=False, na_values=[""])
    rows = pp[pp["pair"] == off]
    n_left = int(all_rows(out)["n_left_out"].sum())
    check(len(rows) == 5 and set(rows["reason"]) == {"use=false"} and not rows["entered"].astype(bool).any()
          and n_left == 5, f"S4.2 {off}: rows {len(rows)}, reasons {sorted(set(rows['reason']))}, entered "
                           f"{int(rows['entered'].astype(bool).sum())}, n_left_out {n_left}")
    rows = pp[pp["pair"] == stack.stem]
    sp = pd.read_csv(out / "datum_sites_period.csv", keep_default_na=False, na_values=[""])
    solved = sp.loc[sp["site"] == "STACK_E", "solved"].astype(bool)
    check(len(rows) == 5 and set(rows["base"]) == {"STACK_E"} and rows["entered"].astype(bool).all()
          and len(solved) == 5 and solved.all(),
          f"S4.3 stack product bases {sorted(set(rows['base']))}, entered {int(rows['entered'].astype(bool).sum())} "
          f"of {len(rows)}; STACK_E solved at {int(solved.sum())} of {len(solved)} periods")


def main() -> int:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    work = SCRATCH / "work"
    tf = work / "tf"
    tf.mkdir(parents=True)
    yaml_path = SCRATCH / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=(SCRATCH / "raw").as_posix(), work=work.as_posix()),
                         encoding="utf-8")
    products, phi = build(tf)
    no_error_flags = [k for k, i in NO_ERROR
                      if any(v[i] for f, v in products[k][1].flags().items() if f != "flag_not_estimated")]
    check(not no_error_flags, f"setup: no row without an error carries a flag (products {no_error_flags})")
    s1_out = s1(yaml_path, tf, work, products, phi)
    if s1_out is not None:
        s2(yaml_path, tf, work, products, s1_out)
    s3(yaml_path, tf, products)
    s4(yaml_path, tf, products, SCRATCH / "s1_pairs.csv")
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
