# -*- coding: utf-8 -*-
"""
Unit test for the per-period flags and the full band layout of an inter-site product

The fields are those of tests/intersite_unit.py: local E on base E,
referenced to a remote's H, T = A exp(i phi0) with a 2 ms delay. A flag
marks a period and never removes it, and every band of the survey's band
layout is a row of the product: a band the record cannot form is a row of
NaN with its flag.

Part 1 (the array interface), 1 h at 100 Hz, bands of
build_band_scheme(100, min_period=0.04, max_period=20): the local's ex
and ey exchanged, so T has its rows swapped and is off-diagonal with
det T = -det(A) exp(2 i phi0); the same record unexchanged as the
control; a dead local E (red noise sharing nothing with the fields).
Part 2, 20 min at 100 Hz with max_period 200: level 4 holds 4 windows (a
band with fewer than five jackknife slices) and the longest bands cannot
be formed. Part 3 runs scripts/process_intersite.py on the 20 min record
written as the MTH5 archives of a scratch survey.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. with the local's E exchanged, any estimated band lacks
   flag_off_diagonal or flag_re_det_negative; or, as the control, the
   unexchanged record raises either flag in any band;
2. with the local's E dead, any estimated band lacks flag_low_coherence;
   or the clean record raises it in any band;
3. on the 20 min record, flag_few_groups differs from n_groups < 5 in any
   estimated row, or no formed band has fewer than five groups (so the flag was not
   put to the test);
4. any (level, f_lo, f_hi) of the band layout is missing from a product of
   `estimate` given the layout, from its CSV read back, or from the
   script's CSV; a band the record cannot form is not a row with NaN T,
   errors and arg(det)/2, 0 windows and flag_not_estimated; or, as the
   control that the count can fail, `estimate` without the layout holds
   every band of the 20 min layout;
5. a flagged product (exchanged, dead or short) has a row count other than
   the layout's, so a flag removed a row;
6. the script exits non-zero, or its sidecar lacks the flags block naming
   the group limit 5 and the coherence limit 0.1 with each flag's row
   count, or its h5 lacks the flag arrays;
7. scripts/merge_tensor_bands.py's `shared_bands`, given the 20 min
   product (with its rows not formed) as the burst side and 2 h of the
   same layout as the continuous side, refuses, pairs a row not formed, or
   leaves a formed row of the 20 min product unpaired;
8. a row that is not estimated (flag_not_estimated) carries any other
   flag in the 20 min product of `estimate`, in the script's CSV or in its
   h5 arrays; or the sidecar's row count of a flag differs from that flag's
   count in the script's CSV or h5; or the 20 min product has no row that
   is not estimated (so the rule was not put to the test).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import FS2, T_START, fields, series, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
FS = 100.0
SCRATCH = scratch_dir("intersite_flags_unit")
E_L, E_B, R = ("l_ex", "l_ey"), ("b_ex", "b_ey"), ("r_hx", "r_hy")
KEYS = ["l_ex", "l_ey", "b_ex", "b_ey", "r_hx", "r_hy"]
FLAGS = ("flag_not_estimated", "flag_few_groups", "flag_low_coherence", "flag_off_diagonal",
         "flag_re_det_negative")

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def layout(scheme: dict) -> list[tuple[int, float, float]]:
    """Return every (level, f_lo, f_hi) of a band scheme's layout."""
    out = []
    for level, edges in scheme["band_edges"].items():
        if int(level) < len(scheme["num_samples_window"]):
            out += [(int(level), float(lo), float(hi)) for lo, hi in np.asarray(edges, dtype=float).reshape(-1, 2)]
    return out


def missing(df: pd.DataFrame, bands: list) -> list:
    """Return the layout bands with no row of the same level and edges (to 1e-9) in a product frame."""
    rows = list(zip(df["level"].astype(int), df["f_lo"].astype(float), df["f_hi"].astype(float)))
    return [b for b in bands
            if not any(lv == b[0] and abs(lo - b[1]) <= 1e-9 * b[1] and abs(hi - b[2]) <= 1e-9 * b[2]
                       for lv, lo, hi in rows)]


def frame(arrays: dict, scheme: dict, use_layout: bool = True) -> pd.DataFrame:
    """Return the CSV frame of local E on base E referenced to R's H."""
    bands = intersite.band_spectra({k: v.copy() for k, v in arrays.items()}, FS, scheme)
    try:
        est = intersite.estimate(bands, E_L, E_B, R, layout=scheme) if use_layout else \
            intersite.estimate(bands, E_L, E_B, R)
    except TypeError as exc:
        check(False, f"estimate takes the band layout ({exc})")
        est = intersite.estimate(intersite.band_spectra({k: v.copy() for k, v in arrays.items()}, FS, scheme),
                                 E_L, E_B, R)
    return est.frame("T")


def has_flags(df: pd.DataFrame, label: str) -> bool:
    """Record a failure when a product frame lacks a flag column."""
    absent = [f for f in FLAGS if f not in df.columns]
    return check(not absent, f"{label}: flag columns present (missing {absent})")


def estimated(df: pd.DataFrame) -> np.ndarray:
    """Rows whose T is finite."""
    return np.isfinite(df[[f"T_{el}_re" for el in intersite.ELEMENTS]].to_numpy()).all(axis=1)


def part1() -> None:
    """Criteria 1, 2 and 5 on 1 h of fields."""
    scheme = build_band_scheme(FS, min_period=0.04, max_period=20.0)
    bands = layout(scheme)
    spec = fields(FS, 1.0, seed=21, h_sites=("r",))
    clean = series(spec, KEYS)
    swapped = dict(clean, l_ex=clean["l_ey"].copy(), l_ey=clean["l_ex"].copy())
    rng = np.random.default_rng(4)
    dead = dict(clean)
    for k in E_L:  # the same channel of fields made from another seed: red, and sharing nothing with these
        dead[k] = series(fields(FS, 1.0, seed=int(rng.integers(1000, 2000)), h_sites=()), [k])[k]
    out = {name: frame(arr, scheme) for name, arr in (("clean", clean), ("exchanged", swapped), ("dead", dead))}
    if not all(has_flags(df, name) for name, df in out.items()):
        return
    for name, df in out.items():
        check(len(df) == len(bands) and not missing(df, bands),
              f"5 {name}: {len(df)} rows for {len(bands)} layout bands, missing {len(missing(df, bands))}")
    x, c, d = out["exchanged"], out["clean"], out["dead"]
    ex, ec, ed = estimated(x), estimated(c), estimated(d)
    check(ex.sum() >= 20 and x["flag_off_diagonal"][ex].all() and x["flag_re_det_negative"][ex].all(),
          f"1 exchanged E: off-diagonal in {int(x['flag_off_diagonal'][ex].sum())} and Re det < 0 in "
          f"{int(x['flag_re_det_negative'][ex].sum())} of {int(ex.sum())} estimated bands (all)")
    check(not c["flag_off_diagonal"][ec].any() and not c["flag_re_det_negative"][ec].any(),
          f"1 control: as recorded, off-diagonal in {int(c['flag_off_diagonal'][ec].sum())} and Re det < 0 in "
          f"{int(c['flag_re_det_negative'][ec].sum())} of {int(ec.sum())} bands (none)")
    check(ed.sum() >= 20 and d["flag_low_coherence"][ed].all(),
          f"2 dead local E: low coherence in {int(d['flag_low_coherence'][ed].sum())} of {int(ed.sum())} bands "
          f"(all; weighted coherence at most {float(np.nanmax(d[['coh_out_weighted_x', 'coh_out_weighted_y']])):.3f})")
    check(not c["flag_low_coherence"][ec].any(),
          f"2 control: the clean record has low coherence in {int(c['flag_low_coherence'][ec].sum())} bands "
          f"(none; weighted coherence at least "
          f"{float(np.nanmin(c[['coh_out_weighted_x', 'coh_out_weighted_y']])):.3f})")


def short_record():
    """Return (spectra, arrays, scheme) of the 20 min record with max_period 200."""
    scheme = build_band_scheme(FS, min_period=0.04, max_period=200.0)
    spec = fields(FS, 1.0 / 3.0, seed=31, h_sites=("l", "b", "r"))
    return spec, series(spec, KEYS), scheme


def check_layout_rows(df: pd.DataFrame, bands: list, label: str) -> None:
    """Criterion 4 on one product frame: every layout band a row, the unformed ones NaN and flagged."""
    gone = missing(df, bands)
    unformed = df["n_windows"].to_numpy() == 0
    cols = [f"T_{el}_{p}" for el in intersite.ELEMENTS for p in ("re", "im", "err")] + \
        ["half_arg_det_deg", "half_arg_det_err_deg"]
    nan_ok = bool(np.all(np.isnan(df.loc[unformed, cols].to_numpy(float))))
    flag_ok = bool(df.loc[unformed, "flag_not_estimated"].astype(bool).all())
    check(not gone and unformed.sum() >= 1 and nan_ok and flag_ok,
          f"4 {label}: {len(df)} rows for {len(bands)} layout bands, missing {gone}; {int(unformed.sum())} not "
          f"formed, NaN {nan_ok}, flagged {flag_ok}")


def part2() -> None:
    """Criteria 3, 4 and 5 on the 20 min record."""
    _spec, arrays, scheme = short_record()
    bands = layout(scheme)
    df = frame(arrays, scheme)
    if not has_flags(df, "20 min"):
        return
    check(len(df) == len(bands), f"5 20 min: {len(df)} rows for {len(bands)} layout bands")
    check_layout_rows(df, bands, "20 min, estimate")
    path = SCRATCH / "short.csv"
    df.to_csv(path, index=False, float_format="%.17g")
    back, _ = intersite.read_csv(path)
    check_layout_rows(back.frame("T"), bands, "20 min, CSV read back")
    bare = frame(arrays, scheme, use_layout=False)
    check(len(missing(bare, bands)) > 0,
          f"4 control: without the layout {len(missing(bare, bands))} layout bands are missing (more than 0)")
    import importlib.util

    loader = importlib.util.spec_from_file_location("merge_tensor_bands", REPO / "scripts" / "merge_tensor_bands.py")
    merge = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(merge)
    spec2 = fields(FS, 2.0, seed=41, h_sites=("r",))
    long_df = frame(series(spec2, KEYS), scheme)
    short_est, _ = intersite.TensorEstimate.from_frame(df)
    long_est, _ = intersite.TensorEstimate.from_frame(long_df)
    try:
        pairs = merge.shared_bands({"est": short_est, "meta": {}}, {"est": long_est, "meta": {}})
        why = ""
    except Exception as exc:  # noqa: BLE001
        pairs, why = [], f"{type(exc).__name__}: {str(exc)[:150]}"
    formed = set(np.flatnonzero(short_est.n_windows > 0).tolist())
    paired = {i for i, _j in pairs}
    check(not why and paired == formed,
          f"7 merge pairs {len(paired)} rows of the 20 min product, its formed rows {len(formed)}, rows not formed "
          f"paired {sorted(paired - formed)} {why}")
    few = df["n_groups"].to_numpy() < 5
    est = estimated(df)
    formed_few = few & (df["n_windows"].to_numpy() > 0) & est
    check(np.array_equal(df["flag_few_groups"].to_numpy(bool)[est], few[est]) and formed_few.sum() >= 1,
          f"3 flag_few_groups equals n_groups < 5 in every estimated row; {int(formed_few.sum())} formed bands "
          f"with {sorted(set(df.loc[formed_few, 'n_groups'].astype(int)))} groups, flagged")
    not_est = df["flag_not_estimated"].to_numpy(bool)
    check(not_est.sum() >= 1 and not flagged_unestimated(df),
          f"8 20 min: {int(not_est.sum())} rows not estimated, other flags on them "
          f"{flagged_unestimated(df) or 'none'}")


def flagged_unestimated(flags: dict | pd.DataFrame) -> dict:
    """Return each flag other than flag_not_estimated with its count of rows that are not estimated."""
    not_est = np.asarray(flags["flag_not_estimated"], dtype=bool)
    out = {f: int(np.sum(np.asarray(flags[f], dtype=bool) & not_est)) for f in FLAGS[1:]}
    return {f: n for f, n in out.items() if n}


SURVEY_YAML = """name: intersite_flags_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0}}
  B: {{latitude: -31.01, longitude: 137.0}}
  R: {{latitude: -31.5, longitude: 137.2}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""


def part3() -> None:
    """Criteria 4 and 6 through the script."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    spec, _arrays, scheme = short_record()
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    for site in ("L", "B", "R"):
        write_site(work, site, spec, T_START, spec["n"])
    out = SCRATCH / "out"
    shutil.rmtree(out, ignore_errors=True)
    res = subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "L", "B", "--kind", "telluric", "--remote",
                          "R", "--out-dir", str(out)], capture_output=True, text=True, cwd=REPO)
    if not check(res.returncode == 0, f"6 script exit {res.returncode}"):
        print(res.stderr[-3000:])
        return
    stem = "L_te-B_rr-R"
    df = pd.read_csv(out / f"{stem}.csv", float_precision="round_trip")
    if not has_flags(df, "script CSV"):
        return
    check_layout_rows(df, layout(scheme), "script CSV")
    side = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
    flags = side.get("flags") or {}
    counts_ok = all(isinstance((flags.get(f) or {}).get("rows"), int) for f in FLAGS)
    limits_ok = (flags.get("flag_few_groups", {}).get("below") == 5
                 and flags.get("flag_low_coherence", {}).get("below") == 0.1)
    import h5py

    with h5py.File(out / f"{stem}.h5", "r") as f:
        in_h5 = [k for k in FLAGS if k in f]
        h5_flags = {k: f[k][()] for k in in_h5}
    check(counts_ok and limits_ok and len(in_h5) == len(FLAGS),
          f"6 sidecar flags block with row counts ({counts_ok}) and limits 5 and 0.1 ({limits_ok}); h5 flag "
          f"arrays {in_h5}")
    if not counts_ok or len(in_h5) != len(FLAGS):
        return
    counts = {f: (flags[f]["rows"], int(df[f].astype(bool).sum()), int(np.sum(h5_flags[f]))) for f in FLAGS}
    agree = all(len(set(c)) == 1 for c in counts.values())
    check(agree and not flagged_unestimated(df) and not flagged_unestimated(h5_flags),
          f"8 script: rows per flag (sidecar, CSV, h5) {counts}; other flags on rows not estimated, CSV "
          f"{flagged_unestimated(df) or 'none'}, h5 {flagged_unestimated(h5_flags) or 'none'}")


def main() -> int:
    if FS2 != FS:
        check(False, f"intersite_unit's archive rate {FS2} is this test's {FS}")
    part1()
    part2()
    part3()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
