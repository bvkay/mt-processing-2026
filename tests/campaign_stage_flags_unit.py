# -*- coding: utf-8 -*-
"""
Unit test for the campaign plan keys stages.remotes.flags and stages.stacks.flags

The keys are lists of process_rr.py flags passed to every rr run of that
stage (stage 1: the site remotes; stage 2: the runs on the stacks, not the
stack builds), for example 256 samples at 75 % overlap in place of aurora's
128-sample / 25 % defaults. They are part of each row's inputs, shown in the dry run
and in the ledger's command, and refused when process_rr.py does not take them.
A `windows:` run of stage 3 pairs with a full-record default run and takes that
run's stage flags (the remotes' for a site remote, the stacks' for a stack), so
its merge joins two rows made alike.

Runs on the synthetic survey of tests/campaign_unit.py (five sites, empty
archives), and processes none of them.

Usage:
    python tests/campaign_stage_flags_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) load_plan does not read ``stages.remotes.flags: [--window-samples, "256",
    --overlap, "75"]`` and ``stages.stacks.flags: [--window-samples, 256]`` as
    {1: [...], 2: [...]} of strings, or a plan without the keys gives anything
    but no flags;
(2) load_plan accepts any of: an unknown flag (--no-such-flag), a bad value
    (--overlap abc, --taper square), --tag, --dry-run, --engine (stages 1 and
    2 are aurora's), a positional item ("256"), or a value that is not a list;
(3) a stage 1 rr command does not carry the remotes' flags after the plan's
    --min-band-windows and before --tag, a stage 2 rr command on a stack does
    not carry the stacks' flags, a stack build or a stage 3 config run carries
    either, or a `windows:` run on a site remote does not carry the remotes'
    flags;
(4) a stage 1 or 2 job's inputs do not end in ";flags <the flags>", a change of
    the flags leaves the inputs unchanged (a resume would not re-run the row),
    or with the keys absent any job's inputs carry "flags" (older ledgers must
    stay done);
(5) the dry run does not show the flags on every stage 1 row and every stage 2
    rr row, or shows them on a stack build or a stage 3 config row.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import campaign as cp  # noqa: E402
import campaign_unit as cu  # noqa: E402  (the synthetic survey and plan)

R_FLAGS = ["--window-samples", "256", "--overlap", "75"]
S_FLAGS = ["--window-samples", "256"]


def plan_with(root: Path, remotes=None, stacks=None, windows=None) -> Path:
    """Write the synthetic plan with the given stage flags (None leaves a key out)."""
    path = cu.make_plan(root)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if remotes is not None:
        raw["stages"]["remotes"] = {"flags": remotes}
    if stacks is not None:
        raw["stages"]["stacks"]["flags"] = stacks
    if windows is not None:
        raw["windows"] = windows
    raw["min_band_windows"] = 2
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def main() -> int:
    fails = []
    root = cu.ROOT / "stage_flags"
    survey_yaml = cu.make_survey(root)

    # (1)
    try:
        plan = cp.load_plan(plan_with(root / "p1", R_FLAGS, ["--window-samples", 256]))
        got = getattr(plan, "stage_flags", "no attribute stage_flags")
    except ValueError as exc:
        got = f"refused: {exc}"
    print(f"(1) flags read: {got}")
    if got != {1: R_FLAGS, 2: S_FLAGS}:
        fails.append(f"(1) stage flags {got!r}")
    bare = cp.load_plan(plan_with(root / "p0"))
    if getattr(bare, "stage_flags", None) not in ({}, {1: [], 2: []}):
        fails.append(f"(1) without the keys: {getattr(bare, 'stage_flags', None)!r}")

    # (2)
    bad = {"unknown flag": ["--no-such-flag"], "bad number": ["--overlap", "abc"],
           "bad choice": ["--taper", "square"], "--tag": ["--tag", "x"], "--dry-run": ["--dry-run"],
           "--engine": ["--engine", "mantle"], "positional": ["256"], "not a list": "--overlap 75"}
    for what, flags in bad.items():
        for stage in ("remotes", "stacks"):
            kw = {stage: flags}
            try:
                cp.load_plan(plan_with(root / "p2", **kw))
                fails.append(f"(2) {stage} {what} {flags!r}: accepted")
                print(f"(2) {stage} {what}: ACCEPTED")
            except ValueError as exc:
                line = next((x.strip() for x in str(exc).splitlines()[1:] if "flags" in x), str(exc)[:120])
                if stage == "remotes":
                    print(f"(2) {stage} {what}: refused: {line[:150]}")

    # (3), (4), (5) on a campaign with both keys and a window on A
    win = {"A": {"yx": [cu.iso(10), cu.iso(30)], "merge": True}}
    try:
        plan = cp.load_plan(plan_with(root / "p3", R_FLAGS, S_FLAGS, windows=win))
    except ValueError as exc:
        fails.append(f"(3) plan refused: {exc}")
        plan = None
    if plan is not None:
        c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
        s1 = c.stage1_jobs(["A", "B", "C"])
        s2 = c.stage2_jobs(["A", "B", "C"])
        s3 = [c.rr_job(3, "A", "B", "boxcar", "s3_A_rr-B_boxcar"), *c.window_jobs("A", "B")]

        def carries(cmd, flags) -> bool:
            n = len(flags)
            return any(cmd[i:i + n] == flags for i in range(len(cmd) - n + 1))

        for j in s1:
            i_floor, i_tag = j.cmd.index("--min-band-windows"), j.cmd.index("--tag")
            pos = next((i for i in range(len(j.cmd)) if j.cmd[i:i + len(R_FLAGS)] == R_FLAGS), -1)
            if not i_floor < pos < i_tag:
                fails.append(f"(3) {j.run_id}: flags not between --min-band-windows and --tag: {j.cmd[3:]}")
            if not c.inputs(j).endswith(";flags " + " ".join(R_FLAGS)):
                fails.append(f"(4) {j.run_id}: inputs {c.inputs(j)!r}")
        for j in s2:
            if j.kind == "rr" and not (carries(j.cmd, S_FLAGS) and not carries(j.cmd, R_FLAGS)):
                fails.append(f"(3) {j.run_id}: not the stacks' flags: {j.cmd[3:]}")
            if j.kind == "rr" and not c.inputs(j).endswith(";flags " + " ".join(S_FLAGS)):
                fails.append(f"(4) {j.run_id}: inputs {c.inputs(j)!r}")
            if j.kind == "stack" and ("--window-samples" in j.cmd or "flags" in c.inputs(j)):
                fails.append(f"(3) {j.run_id}: a stack build carries stage flags")
        cfg = s3[0]
        if "--window-samples" in cfg.cmd or "flags" in c.inputs(cfg):
            fails.append(f"(3) the stage 3 config run carries stage flags: {cfg.cmd[3:]}")
        wins = [j for j in s3[1:] if j.kind == "rr"]
        if not wins or not all(carries(j.cmd, R_FLAGS) and c.inputs(j).endswith(";flags " + " ".join(R_FLAGS))
                               for j in wins):
            fails.append(f"(3) the windows: run does not carry the remotes' flags: {[j.cmd[3:] for j in wins]}")
        print(f"(3) stage 1 cmd: {' '.join(s1[0].cmd[3:])}")
        print(f"(4) stage 1 inputs: {c.inputs(s1[0])}")
        other = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "p4", ["--window-samples", "512"], S_FLAGS)),
                            parallel=2, create=False)
        if other.inputs(other.stage1_jobs(["A"])[0]) == c.inputs(s1[0]):
            fails.append("(4) changing the flags leaves the stage 1 inputs unchanged")
        c0 = cp.Campaign(survey_yaml, bare, parallel=2, create=False)
        for j in [*c0.stage1_jobs(["A", "B", "C"]), *c0.stage2_jobs(["A", "B", "C"])]:
            if "flags" in c0.inputs(j):
                fails.append(f"(4) without the keys {j.run_id} inputs carry flags: {c0.inputs(j)!r}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c.dry_run([1, 2, 3], ["A", "B", "C"])
        text = buf.getvalue()
        rows = [x for x in text.splitlines() if x.strip().startswith(("s1_", "s2_", "s3_", "done s"))]
        for x in rows:
            rid = x.split()[0] if not x.strip().startswith("done") else x.split()[1]
            want = (" ".join(R_FLAGS) if rid.startswith("s1_") or "win" in rid
                    else " ".join(S_FLAGS) if rid.startswith("s2_") and "_rr-" in rid else None)
            if want and want not in x:
                fails.append(f"(5) dry-run row without its flags: {x.strip()[:160]}")
            if want is None and "--window-samples" in x:
                fails.append(f"(5) dry-run row with stage flags: {x.strip()[:160]}")
        print(f"(5) dry-run rows: {len(rows)}; e.g.\n    " + "\n    ".join(r.strip()[:150] for r in rows[:2]))
    for line in fails:
        print(f"FAIL: {line}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
