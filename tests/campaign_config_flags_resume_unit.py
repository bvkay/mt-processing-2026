# -*- coding: utf-8 -*-
"""
Unit test for workbench issue 180: campaign.py's resume re-runs a stage 3 config whose flags were edited

A row's inputs (`Campaign.inputs`) held the sites' signatures, masks, window,
the plan's min_band_windows and the stage flags, but not the config's own
flags, so a stage 3 row done under `d128: [--window-samples 128, --overlap
25]` stayed "done" after the config was edited in place. The fix adds ";config <flags>" to the inputs of an rr job whose
config has flags (a stage 3 config and its window runs `<config>-<modes>win`),
nothing to a default run; a row written before the marker existed (its inputs
equal the new ones without it) stays done only when its recorded command
carries the config's present flags, so an unedited config is not re-run and
an edited one is.

Runs on the synthetic survey of tests/campaign_unit.py (five sites, empty
archives); no data are processed.

Usage:
    python tests/campaign_config_flags_resume_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) a stage 3 rr job of config d128 is already done after its config's flags
    were edited (128 -> 256): the row written done under the old flags, a new
    Campaign built from the edited plan on the same ledger must say not done,
    and the dry run must not list it as "done";
(2) the same row is not done when the plan is unchanged (a resume must not
    re-run it);
(3) a default (stage 1) job's inputs carry ";config" (older ledgers of
    stages 1 and 2 must stay done), or a stage 3 job's inputs do not carry
    ";config <its flags>" (REVISED after the regression batch: first written as "end in"; the marker
    now sits before the window and floor markers, which campaign_unit expects last);
(4) a row written before the marker (inputs without ";config ...") whose
    ledger command carries the config's present flags is not done, or one
    whose command carries other flags is done.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import campaign as cp  # noqa: E402
import campaign_unit as cu  # noqa: E402  (the synthetic survey and plan)

OLD = ["--window-samples", "128", "--overlap", "25"]
NEW = ["--window-samples", "256", "--overlap", "25"]
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def plan_with(root: Path, flags) -> Path:
    """The synthetic plan with stage 3 config d128 holding `flags`, and A's stage 3 remote fixed to B.

    The `remotes:` entry was added after the first run: without it the dry run has no stage 1 product to
    choose A's stage 3 remote from and lists no stage 3 row (a fixture gap, not the code under test)."""
    path = cu.make_plan(root, configs={"d128": list(flags)})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["remotes"] = {"A": "B"}
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def done_row(c, job, edi: Path, inputs: str | None = None, cmd: str | None = None) -> None:
    """Write `job` into the ledger as done (product `edi`), with its inputs and command as the runner records them."""
    c.ledger.upsert({"run_id": job.run_id, "stage": job.stage, "kind": job.kind, "local": job.local,
                     "remote": job.remote, "config": job.config, "status": "done", "exit_code": 0, "edi": str(edi),
                     "inputs": c.inputs(job) if inputs is None else inputs,
                     "cmd": subprocess.list2cmdline(job.cmd) if cmd is None else cmd, "provisional": ""})
    c.ledger.save()


def main() -> int:
    root = cu.ROOT / "config_flags_resume"
    survey_yaml = cu.make_survey(root)
    edi = cu.synthetic_edi(root / "src.edi")

    c_old = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "camp", OLD)), parallel=2)
    job_old = c_old.rr_job(3, "A", "B", "d128", "s3_A_rr-B_d128")
    s1 = c_old.stage1_jobs(["A", "B"])
    done_row(c_old, job_old, edi)
    inputs_old = c_old.inputs(job_old)

    # (2) unchanged plan: done
    c_same = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "camp", OLD)), parallel=2)
    check(c_same.already_done(c_same.rr_job(3, "A", "B", "d128", "s3_A_rr-B_d128")),
          "(2) unchanged config: the done row stays done")

    # (1) edited plan: not done
    c_new = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "camp", NEW)), parallel=2)
    job_new = c_new.rr_job(3, "A", "B", "d128", "s3_A_rr-B_d128")
    check(not c_new.already_done(job_new), f"(1) edited config (128 -> 256): already_done "
                                           f"{c_new.already_done(job_new)}; inputs old {inputs_old!r} new "
                                           f"{c_new.inputs(job_new)!r}")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        c_new.dry_run([3], ["A", "B"])
    rows = [x for x in buf.getvalue().splitlines() if "s3_A_rr-B_d128" in x]
    check(bool(rows) and not any(x.strip().startswith("done") for x in rows),
          f"(1) dry run row: {rows[0].strip()[:150] if rows else 'none'}")

    # (3) markers
    check(all(";config" not in c_old.inputs(j) for j in s1), f"(3) stage 1 inputs: {c_old.inputs(s1[0])!r}")
    check(";config " + " ".join(OLD) in inputs_old, f"(3) stage 3 inputs: {inputs_old!r}")

    # (4) a row from before the marker
    legacy = inputs_old.replace(";config " + " ".join(OLD), "", 1)
    c4 = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "camp4", OLD)), parallel=2)
    j4 = c4.rr_job(3, "A", "B", "d128", "s3_A_rr-B_d128")
    done_row(c4, j4, edi, inputs=legacy)
    check(c4.already_done(j4), "(4) legacy row, its command carrying the present flags: done")
    c4n = cp.Campaign(survey_yaml, cp.load_plan(plan_with(root / "camp4", NEW)), parallel=2)
    check(not c4n.already_done(c4n.rr_job(3, "A", "B", "d128", "s3_A_rr-B_d128")),
          "(4) legacy row, the config edited since: not done")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
