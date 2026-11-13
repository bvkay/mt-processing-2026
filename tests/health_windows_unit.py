# -*- coding: utf-8 -*-
"""
Unit test for per-mode processing windows from the health table (scripts/health_windows.py, campaign `windows:` file)

Where an E line dies mid-record the whole-record product collapses (SA
AusLAMP FR01 xy at 0.0014 of the 2018 level). scripts/health_windows.py turns health_table.py's health_weeks.csv
into one window per site and mode, the longest run of consecutive weeks in
which that line and H are sound (Ex_ok and H_ok for xy, Ey_ok and H_ok for
yx); "whole" when every week is sound, null ("no sound week") when none is.
The plan key `windows: <file>` makes stage 3 run the site once per distinct
window on its stage 3 remote and merge the xy row of one product with the yx
row of the other (scripts/merge_modes.py), the full-record default run
standing in for a whole-record mode; a mode with no sound week is not
produced.

Usage:
    python tests/health_windows_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(6) a table carrying Hpair_ok does not window xy and yx on it
    (see test_pair_column);
(7) a site whose weeks read hz_present False (an archive without hz) does not
    get tipper null with "tipper: no hz" in its reason and xy/yx from the
    pair verdict, or a site with hz gains a tipper key (see test_pair_column);
(1) the windows of the synthetic health table are not: S1 whole/whole
    ("whole record"); S2 xy weeks 1-1, yx whole; S3 yx null ("no sound
    week"); S4 xy weeks 1-2 (the longest run; week 4 named as also sound);
    S5 (H unsound in week 3, both E lines sound) xy and yx weeks 1-2 with H
    week 3 named; S6 xy weeks 1-2, yx weeks 3-4; S7 (two one-week runs) the
    run with more windows, week 3; each window's start the first week's
    start and its end the last week's end; or the reasons do not read
    "Ex sound weeks 1-2 of 4" / "whole record" / "no sound week" in form;
(2) a survey site derived from S2 (S2L, derived_from S2, its span 10 s inside
    the table's) does not get S2's windows clipped to its own span and
    `from: S2`, or the file written by `main` does not read back to (1);
(3) campaign.load_plan does not accept `windows: <the file>` (relative to
    the plan's folder), or accepts an entry whose mode is "sometimes", whose
    window ends before it starts, or a missing file;
(4) on the synthetic campaign (sites A-E of tests/campaign_unit.py) with A
    whole/whole, B xy and yx in different windows, C xy windowed and yx whole,
    D xy null and yx windowed: stage 3 gives A no window run and no merge; B
    two window runs (default-xywin, default-yxwin) and a merge whose xy source
    is the xy run and yx source the yx run; C one run (default-xywin) and a
    merge whose yx source is the full-record default run (s1_C_rr-...); D one
    run (default-yxwin) and no merge; or the dry run does not list those rows;
(5) merge_modes.merge_files of two synthetic EDIs whose sidecars carry
    different windows does not write the merged EDI with INFO lines
    `mt_workbench.merge_xy_window=<start> to <end> UTC` and
    `mt_workbench.merge_yx_window=...` naming each source's window (a source
    without a window: "whole record"), or its sidecar's merge record lacks
    `windows` {xy, yx} with the same texts.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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

import campaign as cp  # noqa: E402
import campaign_unit as cu  # noqa: E402

W0 = pd.Timestamp("2013-09-22T01:00:00Z")
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def load(name: str):
    """Import scripts/<name>.py."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def weeks(site: str, ex, ey, h, nwin=(335, 335, 335, 30)) -> list[dict]:
    """Rows of a health_weeks table: four weeks, the last 13 h long."""
    rows = []
    for k in range(4):
        start = W0 + pd.Timedelta(days=7 * k)
        end = start + (pd.Timedelta(days=7) if k < 3 else pd.Timedelta(hours=13))
        rows.append({"site": site, "week": k + 1, "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "n_windows": nwin[k], "H_ok": h[k], "Ex_ok": ex[k],
                     "Ey_ok": ey[k]})
    return rows


def wk(k: int, edge: str) -> str:
    """The start or end of week k (1-based) as "YYYY-MM-DD HH:MM:SS"."""
    start = W0 + pd.Timedelta(days=7 * (k - 1))
    t = start if edge == "start" else start + (pd.Timedelta(days=7) if k < 4 else pd.Timedelta(hours=13))
    return t.strftime("%Y-%m-%d %H:%M:%S")


T, F = True, False
TABLE = (weeks("S1", [T] * 4, [T] * 4, [T] * 4) + weeks("S2", [T, F, F, F], [T] * 4, [T] * 4)
         + weeks("S3", [T] * 4, [F] * 4, [T] * 4) + weeks("S4", [T, T, F, T], [T] * 4, [T] * 4)
         + weeks("S5", [T] * 4, [T] * 4, [T, T, F, T]) + weeks("S6", [T, T, F, F], [F, F, T, T], [T] * 4)
         + weeks("S7", [T, F, T, F], [T] * 4, [T] * 4, nwin=(330, 335, 336, 30)))
WANT = {  # site: (xy, yx, words that must appear in the reason)
    "S1": ("whole", "whole", ["whole record"]),
    "S2": ([wk(1, "start"), wk(1, "end")], "whole", ["Ex sound week 1 of 4", "yx: whole record"]),
    "S3": ("whole", None, ["xy: whole record", "yx: no sound week"]),
    "S4": ([wk(1, "start"), wk(2, "end")], "whole", ["Ex sound weeks 1-2 of 4", "also week 4"]),
    "S5": ([wk(1, "start"), wk(2, "end")], [wk(1, "start"), wk(2, "end")], ["Ex sound weeks 1-2 of 4",
                                                                            "Ey sound weeks 1-2 of 4", "H unsound"]),
    "S6": ([wk(1, "start"), wk(2, "end")], [wk(3, "start"), wk(4, "end")], ["Ex sound weeks 1-2 of 4",
                                                                            "Ey sound weeks 3-4 of 4"]),
    "S7": ([wk(3, "start"), wk(3, "end")], "whole", ["Ex sound week 3 of 4", "also week 1"]),
}


def survey_with_derived(root: Path) -> Path:
    """A survey.yaml with S1..S7 and S2L derived from S2 (its span 10 s inside the table's)."""
    sites = {s: {"latitude": -30.5, "longitude": 138.4, "start": wk(1, "start").replace(" ", "T") + "Z",
                 "end": wk(4, "end").replace(" ", "T") + "Z"} for s in WANT}
    sites["S2L"] = {"derived_from": "S2", "sample_rate": 1.0, "latitude": -30.5, "longitude": 138.4,
                    "start": (W0 + pd.Timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end": (pd.Timestamp(wk(4, "end"), tz="UTC") - pd.Timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    cfg = {"name": "HW", "instrument": "edl", "sample_rate": 10, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 4.0, "max_period": 10000.0}, "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return root / "survey.yaml"


def test_windows(tmp: Path) -> None:
    try:
        hw = load("health_windows")
    except FileNotFoundError as exc:
        check(False, f"(1) scripts/health_windows.py: {exc}")
        return
    df = pd.DataFrame(TABLE)
    survey_yaml = survey_with_derived(tmp / "hw")
    csv = tmp / "hw" / "health_weeks.csv"
    df.to_csv(csv, index=False)
    got = hw.build_windows(survey_yaml, csv)
    for site, (xy, yx, words) in WANT.items():
        e = got.get(site, {})
        ok = e.get("xy") == xy and e.get("yx") == yx and all(w in e.get("reason", "") for w in words)
        check(ok, f"(1) {site}: xy {e.get('xy')}, yx {e.get('yx')}; reason {e.get('reason')!r}")
    d = got.get("S2L", {})
    start_l = (W0 + pd.Timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
    check(d.get("xy") == [start_l, wk(1, "end")] and d.get("yx") == "whole" and d.get("from") == "S2",
          f"(2) S2L: {d}")
    status = hw.main([str(survey_yaml), str(csv)])
    out = survey_yaml.parent / "health_windows.yaml"
    back = yaml.safe_load(out.read_text(encoding="utf-8")) if out.exists() else {}
    sites_back = back.get("sites", back)
    check(status == 0 and all(sites_back.get(s, {}).get("xy") == WANT[s][0] for s in WANT),
          f"(2) main wrote {out.name} (exit {status}), read back {len(sites_back)} site(s)")


def test_pair_column(tmp: Path) -> None:
    """(6) With the pair-only column Hpair_ok in the table, xy and yx take it instead of H_ok.
    Fails if: P1 (H_ok False in weeks 2-3 from a dead hz, Hpair_ok True throughout, both E lines sound) is not
    whole/whole; P2 (Hpair_ok False in week 3, H_ok False in weeks 2-3) is not xy = yx = weeks 1-2 with
    "H pair unsound week 3" in the reason; or a table without the column (S5 of (1)) stops reading H_ok."""
    hw = load("health_windows")
    rows = []
    for site, h, hp in (("P1", [T, F, F, T], [T] * 4), ("P2", [T, F, F, T], [T, T, F, T])):
        for r, x in zip(weeks(site, [T] * 4, [T] * 4, h), hp):
            r["Hpair_ok"] = x
            rows.append(r)
    root = tmp / "hwp"
    survey_yaml = survey_with_derived(root)
    csv = root / "health_weeks.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    got = hw.build_windows(survey_yaml, csv)
    p1, p2 = got.get("P1", {}), got.get("P2", {})
    check(p1.get("xy") == "whole" and p1.get("yx") == "whole", f"(6) P1 (dead hz, sound pair): {p1}")
    w12 = [wk(1, "start"), wk(2, "end")]
    check(p2.get("xy") == w12 and p2.get("yx") == w12 and "H pair unsound week 3" in p2.get("reason", ""),
          f"(6) P2 (pair unsound week 3): {p2}")
    # (7) no hz: H_ok False throughout, the pair sound, hz_present False
    rows = []
    for site, hz in (("N1", False), ("N2", True)):
        for r in weeks(site, [T] * 4, [T] * 4, [F] * 4 if not hz else [T] * 4):
            r["Hpair_ok"], r["hz_present"] = True, hz
            rows.append(r)
    csv7 = root / "health_weeks_nohz.csv"
    pd.DataFrame(rows).to_csv(csv7, index=False)
    got = hw.build_windows(survey_yaml, csv7)
    n1, n2 = got.get("N1", {}), got.get("N2", {})
    check(n1.get("xy") == "whole" and n1.get("yx") == "whole" and "tipper" in n1 and n1["tipper"] is None
          and "tipper: no hz" in n1.get("reason", "") and "tipper" not in n2,
          f"(7) N1 (no hz): {n1}; N2 (hz): {n2}")


def write_windows(root: Path, entries: dict) -> Path:
    """Write a health_windows.yaml of `entries` beside the plan."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "health_windows.yaml"
    path.write_text(yaml.safe_dump({"sites": entries}, sort_keys=False), encoding="utf-8")
    return path


def test_campaign(tmp: Path) -> None:
    root = tmp / "camp"
    survey_yaml = cu.make_survey(root)
    w1, w2, w3 = [cu.iso(2), cu.iso(20)], [cu.iso(22), cu.iso(40)], [cu.iso(41), cu.iso(60)]
    entries = {"A": {"xy": "whole", "yx": "whole", "reason": "whole record"},
               "B": {"xy": w1, "yx": [cu.iso(24), cu.iso(46)], "reason": "xy: Ex 1; yx: Ey 2"},
               "C": {"xy": [cu.iso(6), cu.iso(30)], "yx": "whole", "reason": "xy: Ex 1; yx: whole record"},
               "D": {"xy": None, "yx": w3, "reason": "xy: no sound week; yx: Ey 2"}}
    write_windows(root, entries)
    path = cu.make_plan(root)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["windows"] = "health_windows.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    try:
        plan = cp.load_plan(path)
    except (ValueError, TypeError, AttributeError) as exc:
        check(False, f"(3) windows: health_windows.yaml refused: {str(exc)[:300]}")
        return
    check(True, "(3) windows: health_windows.yaml loads")
    for what, bad in (("mode 'sometimes'", {"A": {"xy": "sometimes", "yx": "whole"}}),
                      ("window ending first", {"A": {"xy": [cu.iso(20), cu.iso(2)], "yx": "whole"}})):
        r2 = tmp / f"bad_{len(what)}"
        write_windows(r2, bad)
        p2 = cu.make_plan(r2)
        raw2 = yaml.safe_load(p2.read_text(encoding="utf-8"))
        raw2["windows"] = "health_windows.yaml"
        p2.write_text(yaml.safe_dump(raw2, sort_keys=False), encoding="utf-8")
        try:
            cp.load_plan(p2)
            check(False, f"(3) {what}: accepted")
        except ValueError as exc:
            check(True, f"(3) {what}: refused ({str(exc).splitlines()[-1].strip()[:120]})")
    r3 = tmp / "missing"
    p3 = cu.make_plan(r3)
    raw3 = yaml.safe_load(p3.read_text(encoding="utf-8"))
    raw3["windows"] = "no_such_windows.yaml"
    p3.write_text(yaml.safe_dump(raw3, sort_keys=False), encoding="utf-8")
    try:
        cp.load_plan(p3)
        check(False, "(3) a missing windows file: accepted")
    except ValueError as exc:
        check(True, f"(3) a missing windows file: refused ({str(exc).splitlines()[-1].strip()[:100]})")

    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    remote = {"A": "B", "B": "A", "C": "A", "D": "E"}
    jobs = {s: c.window_jobs(s, remote[s]) for s in "ABCD"}
    desc = {s: [(j.kind, j.config, list(j.deps)) for j in js] for s, js in jobs.items()}
    check(desc["A"] == [], f"(4) A (whole/whole): {desc['A']}")
    b = desc["B"]
    check([x[1] for x in b] == ["default-xywin", "default-yxwin", "default-merged"]
          and b[2][2] == ["s3_B_rr-A_default-xywin", "s3_B_rr-A_default-yxwin"], f"(4) B: {b}")
    cc = desc["C"]
    check([x[1] for x in cc] == ["default-xywin", "default-merged"]
          and cc[1][2] == ["s3_C_rr-A_default-xywin", "s1_C_rr-A"], f"(4) C: {cc}")
    check([x[1] for x in desc["D"]] == ["default-yxwin"], f"(4) D: {desc['D']}")
    win_b = [j.window for j in jobs["B"] if j.kind == "rr"]
    check(win_b == [(cp.utc_text(w1[0]), cp.utc_text(w1[1])), (cp.utc_text(cu.iso(24)), cp.utc_text(cu.iso(46)))],
          f"(4) B windows {win_b}")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        c.dry_run([3], ["A", "B", "C", "D"])
    text = buf.getvalue()
    for rid in ("s3_B_rr-<best-of-stage-1>_default-xywin", "s3_B_rr-<best-of-stage-1>_default-yxwin",
                "s3_B_rr-<best-of-stage-1>_default-merged", "s3_C_rr-<best-of-stage-1>_default-merged",
                "s3_D_rr-<best-of-stage-1>_default-yxwin"):
        check(rid in text, f"(4) dry run lists {rid}")
    ids = [line.split()[0] for line in text.splitlines() if line.strip().startswith("s3_")]
    a_extra = [i for i in ids if i.startswith("s3_A_") and ("win" in i or "merged" in i)]
    check(not a_extra, f"(4) dry run has no window or merge row for A: {a_extra}")
    check("s3_D_rr-<best-of-stage-1>_default-merged" not in ids, "(4) dry run has no merge row for D")


def test_merge(tmp: Path) -> None:
    from mt_metadata.transfer_functions.core import TF

    mm = load("merge_modes")
    per = np.logspace(1, 3, 9)
    paths = {}
    for name, rho, window in (("XY", 100.0, {"start": "2013-09-22T01:00:00+00:00", "end": "2013-09-29T01:00:00+00:00"}),
                              ("YX", 400.0, {"start": None, "end": None})):
        zh = np.sqrt(rho / (0.2 * per)) * np.exp(0.25j * np.pi)
        z = np.zeros((per.size, 2, 2), dtype=complex)
        z[:, 0, 1], z[:, 1, 0] = zh, -zh
        z[:, 0, 0], z[:, 1, 1] = 0.1 * zh, -0.1 * zh  # merge_modes reads a zero component as EMPTY
        tf = TF()
        tf.station_metadata.id = "FR01L"
        tf.station_metadata.location.latitude = -30.5
        tf.station_metadata.location.longitude = 138.4
        tf.period = per
        tf.impedance = z
        tf.impedance_error = 0.05 * np.abs(z) + 1e-6
        edi = tmp / f"{name}.edi"
        tf.write(fn=str(edi), file_type="edi")
        edi.with_suffix(".json").write_text(json.dumps({"local": "FR01L", "remote": "FR08L", "tag": name.lower(),
                                                        "window": window}), encoding="utf-8")
        paths[name] = edi
    out = tmp / "merged.edi"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        status = mm.merge_files(out, paths["XY"], paths["YX"], tag="t", argv=["x"])
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    want_xy = "mt_workbench.merge_xy_window=2013-09-22 01:00:00 to 2013-09-29 01:00:00 UTC"
    want_yx = "mt_workbench.merge_yx_window=whole record"
    check(status == 0 and want_xy in text and want_yx in text,
          f"(5) merged EDI INFO names both windows (exit {status}; xy line {want_xy in text}, yx line {want_yx in text})")
    side = json.loads(out.with_suffix(".json").read_text(encoding="utf-8")) if out.exists() else {}
    w = (side.get("merge") or {}).get("windows")
    check(w == {"xy": "2013-09-22 01:00:00 to 2013-09-29 01:00:00 UTC", "yx": "whole record"},
          f"(5) sidecar merge windows {w}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        test_windows(tmp)
        test_pair_column(tmp)
        test_campaign(tmp)
        test_merge(tmp)
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
