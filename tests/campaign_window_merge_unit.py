# -*- coding: utf-8 -*-
"""
Unit test for the campaign's window merge stage (scripts/campaign.py
plan key `window_merge`, scripts/merge_windows.py)

A site's product of record is the 256-sample / 75 % window product at the short and middle periods and the
default-window product at the long end, merged by period band. The plan key

    window_merge: {short: default, long: d128, rule: "fixed:2000"}

names the run family of each source ("default" = the full-record default run of stages 1-2, which carries the
stage flags; or a stage 3 config) and the crossover rule of scripts/merge_windows.py. Stage 3 then gives every
plan site one merge job (config `windows-merged`, kind merge) whose x row, y row and tipper take the short family's
row up to the crossover and the long family's above it. The per-mode health windows (`windows:` file) apply to
both families: a windowed mode's sources are each family's run over that window (the default family's
`default-<modes>win` runs, which already exist; for a config family new runs `<config>-<modes>win` with that
config's flags and no stage flags); a whole-record mode, a mode with no sound week and the tipper take the
full-record runs (stage 1 `s1_<site>_rr-<remote>` for default, `s3_<site>_rr-<remote>_<config>` for a config).

Usage:
    python tests/campaign_window_merge_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) load_plan does not accept the key with configs d128 and q256, or accepts: an unknown key in it, a family that is
    neither default nor a plan config, short equal to long, a rule merge_windows refuses ("2000"), or no rule;
(2) on the synthetic campaign of tests/campaign_unit.py (sites A-E) with stage flags [--window-samples 256
    --overlap 75], the windows file A whole/whole, B xy and yx in different windows, C xy windowed and yx whole,
    D xy null and yx windowed (E without an entry) and window_merge {short: default, long: d128}: the window-merge
    job of each site (remote A for B and C, B for A, E for D, D for E) does not have these sources
    (part: short run id, long run id):
      A: xy, yx, tipper: s1_A_rr-B, s3_A_rr-B_d128;
      B: xy: s3_B_rr-A_default-xywin, s3_B_rr-A_d128-xywin; yx: ..._default-yxwin, ..._d128-yxwin;
         tipper: s1_B_rr-A, s3_B_rr-A_d128;
      C: xy: s3_C_rr-A_default-xywin, s3_C_rr-A_d128-xywin; yx and tipper: s1_C_rr-A, s3_C_rr-A_d128;
      D: xy (no sound week) and tipper: s1_D_rr-E, s3_D_rr-E_d128; yx: s3_D_rr-E_default-yxwin, s3_D_rr-E_d128-yxwin;
      E: as A with remote D;
    or the job's windows texts are not "whole record" / "<start> to <end> UTC" / a text saying "no sound week";
    or B gets other than exactly one d128 window run per distinct window (d128-xywin over B's xy window, d128-yxwin
    over its yx window) whose command carries d128's flags (--window-samples 128 --overlap 25), the window as the
    two positional times, and not the stage flags (256), while B's default-xywin run carries the stage flags;
(3) the dry run of stage 3 over A-E does not list exactly one `windows-merged` row per site (5), or lists the d128
    window runs of B, C and D;
(4) with the key absent, stage 3 gives any windows-merged job or any d128-*win run (the plan without the key
    unchanged);
(5) run_merge of D's window-merge job, with ledger rows done for its four source run ids pointing at synthetic EDIs
    (short: 100 ohm-m, long: 400 ohm-m), does not write a merged EDI whose sidecar `window_merge` gives the rule
    fixed:2000, the short source's EDI for xy up to 2,000 s and the long source's above, the window text for xy
    saying "no sound week", and a ledger row done whose cmd names the rule and the four sources; or a second
    already_done check of the same job with the rule changed in the plan is not False (a rule change re-runs it).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import campaign as cp  # noqa: E402
import campaign_unit as cu  # noqa: E402

fails: list[str] = []
WM = {"short": "default", "long": "d128", "rule": "fixed:2000"}
CONFIGS = {"d128": ["--window-samples", "128", "--overlap", "25"], "q256": ["--window-samples", "256", "--overlap", "75"]}
FLAGS = ["--window-samples", "256", "--overlap", "75"]


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def write_plan(root: Path, window_merge=WM, windows=True) -> Path:
    path = cu.make_plan(root, configs=CONFIGS)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["stages"]["remotes"] = {"flags": FLAGS}
    if windows:
        raw["windows"] = "health_windows.yaml"
    if window_merge is not None:
        raw["window_merge"] = window_merge
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def entries():
    return {"A": {"xy": "whole", "yx": "whole", "reason": "whole record"},
            "B": {"xy": [cu.iso(2), cu.iso(20)], "yx": [cu.iso(24), cu.iso(46)], "reason": "xy: Ex 1; yx: Ey 2"},
            "C": {"xy": [cu.iso(6), cu.iso(30)], "yx": "whole", "reason": "xy: Ex 1; yx: whole record"},
            "D": {"xy": None, "yx": [cu.iso(41), cu.iso(60)], "reason": "xy: no sound week; yx: Ey 2"}}


def write_windows(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "health_windows.yaml").write_text(yaml.safe_dump({"sites": entries()}, sort_keys=False), encoding="utf-8")


def test_plan(tmp: Path) -> None:
    root = tmp / "plan_ok"
    cu.make_survey(root)
    write_windows(root)
    try:
        plan = cp.load_plan(write_plan(root))
        check(getattr(plan, "window_merge", None) == WM, f"(1) window_merge loads: {getattr(plan, 'window_merge', None)}")
    except (ValueError, TypeError, AttributeError) as exc:
        check(False, f"(1) window_merge refused: {str(exc)[:300]}")
    for what, bad in (("unknown key", {**WM, "floor": 1000}), ("unknown family", {**WM, "long": "nope"}),
                      ("short == long", {**WM, "short": "d128"}), ("bad rule", {**WM, "rule": "2000"}),
                      ("no rule", {"short": "default", "long": "d128"})):
        r = tmp / f"bad_{what.replace(' ', '_').replace('=', 'eq')}"
        cu.make_survey(r)
        write_windows(r)
        try:
            cp.load_plan(write_plan(r, bad))
            check(False, f"(1) {what}: accepted")
        except ValueError as exc:
            check(True, f"(1) {what}: refused ({str(exc).splitlines()[-1].strip()[:110]})")


def wm_job(jobs):
    found = [j for j in jobs if j.config == "windows-merged"]
    return found[0] if len(found) == 1 else None


def test_jobs(tmp: Path) -> None:
    root = tmp / "camp"
    survey_yaml = cu.make_survey(root)
    write_windows(root)
    plan = cp.load_plan(write_plan(root))
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    remote = {"A": "B", "B": "A", "C": "A", "D": "E", "E": "D"}
    jobs = {s: c.stage3_site_jobs(s, remote[s]) for s in "ABCDE"}
    whole = "whole record"
    want = {
        "A": {p: ("s1_A_rr-B", "s3_A_rr-B_d128") for p in ("xy", "yx", "tipper")},
        "B": {"xy": ("s3_B_rr-A_default-xywin", "s3_B_rr-A_d128-xywin"),
              "yx": ("s3_B_rr-A_default-yxwin", "s3_B_rr-A_d128-yxwin"), "tipper": ("s1_B_rr-A", "s3_B_rr-A_d128")},
        "C": {"xy": ("s3_C_rr-A_default-xywin", "s3_C_rr-A_d128-xywin"), "yx": ("s1_C_rr-A", "s3_C_rr-A_d128"),
              "tipper": ("s1_C_rr-A", "s3_C_rr-A_d128")},
        "D": {"xy": ("s1_D_rr-E", "s3_D_rr-E_d128"), "yx": ("s3_D_rr-E_default-yxwin", "s3_D_rr-E_d128-yxwin"),
              "tipper": ("s1_D_rr-E", "s3_D_rr-E_d128")},
        "E": {p: ("s1_E_rr-D", "s3_E_rr-D_d128") for p in ("xy", "yx", "tipper")},
    }
    for s in "ABCDE":
        j = wm_job(jobs[s])
        got = {p: tuple(v) for p, v in (j.parts.items() if j is not None else [])}
        check(j is not None and got == want[s], f"(2) {s} window-merge sources: {got}")
    jb = wm_job(jobs["B"])
    wt = jb.windows_text if jb is not None else {}
    check(wt.get("xy") == f"{cp.utc_text(cu.iso(2))} to {cp.utc_text(cu.iso(20))} UTC" and wt.get("tipper") == whole,
          f"(2) B windows texts {wt}")
    jd = wm_job(jobs["D"])
    wtd = jd.windows_text if jd is not None else {}
    check("no sound week" in str(wtd.get("xy", "")), f"(2) D xy window text {wtd.get('xy')!r}")
    ja = wm_job(jobs["A"])
    check(ja is not None and ja.windows_text.get("xy") == whole, f"(2) A xy window text {ja.windows_text if ja else None}")
    d128 = [j for j in jobs["B"] if j.kind == "rr" and j.config.startswith("d128-")]
    names = sorted(j.config for j in d128)
    check(names == ["d128-xywin", "d128-yxwin"], f"(2) B d128 window runs {names}")
    for j in d128:
        cmd = [str(x) for x in j.cmd]
        i = cmd.index(j.local) if j.local in cmd else -1
        has_window = i >= 0 and cmd[i + 2:i + 4] == list(j.window or ())
        ok = has_window and "128" in cmd and "25" in cmd and "256" not in cmd
        check(ok, f"(2) {j.config} cmd carries d128's flags and its window, not the stage flags: {' '.join(cmd[3:])}")
    dx = [j for j in jobs["B"] if j.config == "default-xywin"]
    check(len(dx) == 1 and "256" in [str(x) for x in dx[0].cmd], "(2) B default-xywin carries the stage flags")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        c.dry_run([3], list("ABCDE"))
    ids = [line.split()[0] for line in buf.getvalue().splitlines() if line.strip().startswith("s3_")]
    merged = [i for i in ids if i.endswith("_windows-merged")]
    check(len(merged) == 5 and len({i.split("_")[1] for i in merged}) == 5, f"(3) dry run: one windows-merged per site: {merged}")
    for rid in ("s3_B_rr-<best-of-stage-1>_d128-xywin", "s3_B_rr-<best-of-stage-1>_d128-yxwin",
                "s3_C_rr-<best-of-stage-1>_d128-xywin", "s3_D_rr-<best-of-stage-1>_d128-yxwin"):
        check(rid in ids, f"(3) dry run lists {rid}")

    root2 = tmp / "camp_nokey"
    survey2 = cu.make_survey(root2)
    write_windows(root2)
    plan2 = cp.load_plan(write_plan(root2, window_merge=None))
    c2 = cp.Campaign(survey2, plan2, parallel=2, create=False)
    extra = [j.run_id for s in "ABCDE" for j in c2.stage3_site_jobs(s, remote[s])
             if j.config == "windows-merged" or j.config.startswith("d128-")]
    check(not extra, f"(4) without the key: no window-merge job and no d128 window run ({extra})")


def edi(path: Path, rho: float) -> Path:
    from mt_metadata.transfer_functions.core import TF
    per = 4.0 * 10.0 ** (0.05 + 0.1 * np.arange(42))
    zh = np.sqrt(rho / (0.2 * per)) * np.exp(0.25j * np.pi)
    z = np.zeros((per.size, 2, 2), dtype=complex)
    z[:, 0, 1], z[:, 1, 0], z[:, 0, 0], z[:, 1, 1] = zh, -zh, 0.1 * zh, -0.1 * zh
    tf = TF()
    tf.station_metadata.id = "D"
    tf.station_metadata.location.latitude = -31.0
    tf.station_metadata.location.longitude = 138.6
    tf.period = per
    tf.impedance = z
    tf.impedance_error = 0.01 * np.abs(z) + 1e-9
    tf.tipper = np.tile(np.array([0.1 + 0.05j, -0.2 + 0.1j]) * (1 if rho < 200 else 2), (per.size, 1))[:, None, :]
    tf.tipper_error = np.full((per.size, 1, 2), 0.01)
    tf.write(fn=str(path), file_type="edi")
    path.with_suffix(".json").write_text(json.dumps({"local": "D", "remote": "E", "tag": path.stem}), encoding="utf-8")
    return path


def test_run(tmp: Path) -> None:
    root = tmp / "camp_run"
    survey_yaml = cu.make_survey(root)
    write_windows(root)
    plan = cp.load_plan(write_plan(root))
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=True)
    job = wm_job(c.stage3_site_jobs("D", "E"))
    if job is None:
        check(False, "(5) no window-merge job for D")
        return
    src = tmp / "src"
    src.mkdir(parents=True, exist_ok=True)
    short = edi(src / "short.edi", 100.0)
    long = edi(src / "long.edi", 400.0)
    for part, (s_id, l_id) in job.parts.items():
        for rid, path in ((s_id, short), (l_id, long)):
            c.ledger.upsert({"run_id": rid, "status": "done", "exit_code": "0", "edi": str(path)})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        ok = c.run_merge(job)
    row = c.ledger.rows.get(job.run_id, {})
    out = Path(row.get("edi", "") or "nowhere.edi")
    side = json.loads(out.with_suffix(".json").read_text(encoding="utf-8")) if out.is_file() else {}
    wm = side.get("window_merge", {})
    check(ok and row.get("status") == "done", f"(5) run_merge done ({row.get('status')}, {row.get('error')})")
    check(wm.get("rule") == "fixed:2000" and Path(wm.get("short", {}).get("xy", "")).name == "short.edi"
          and Path(wm.get("long", {}).get("xy", "")).name == "long.edi"
          and abs(float(wm.get("crossover_s", {}).get("xy", -1)) - 2000.0) < 1e-6,
          f"(5) sidecar window_merge {json.dumps(wm)[:300]}")
    check("no sound week" in str(wm.get("windows", {}).get("xy", "")), f"(5) xy window text {wm.get('windows')}")
    cmd = row.get("cmd", "")
    check("fixed:2000" in cmd and "short.edi" in cmd and "long.edi" in cmd, f"(5) ledger cmd {cmd[:200]}")
    check(c.already_done(job), "(5) already_done with the same rule")
    c.plan.window_merge = {**c.plan.window_merge, "rule": "fixed:3000"}
    check(not c.already_done(job), "(5) a rule change makes the merge stale")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for test in (test_plan, test_jobs, test_run):
            try:
                test(tmp)
            except Exception as exc:  # a missing API counts as a failure, reported
                check(False, f"{test.__name__}: {type(exc).__name__}: {str(exc)[:300]}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    sys.exit(main())
