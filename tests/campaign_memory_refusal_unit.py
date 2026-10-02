# -*- coding: utf-8 -*-
"""
Unit test for campaign.py's refusal of a memory gate the machine can never meet

**This test fails if** on a machine of 64 GB (psutil's `virtual_memory`
stubbed: total 64 GB, available 60 GB), a plan whose `runner.min_available_gb`
is 200 GB, or 64 GB (equal to the total, which available memory never
reaches), does not make `campaign.py` exit 2 before it runs anything, both as
a run and as `--dry-run`, with exactly one stderr line that names the plan,
`min_available_gb` with its value and the machine's 64.0 GB; or if a plan at
40 GB is refused (its dry run must exit 0 and print the matrix); or if a slot
held back by the gate (40 GB needed, 30 GB available) no longer gets the
wait line's amounts ("available 30.0 GB", "need 40.0 GB").

The survey and plan are campaign_unit's synthetic ones (`make_survey`,
`make_plan`: five sites, empty raw archives). `run_campaign` is replaced by
a stand-in that raises, so a run that gets past the refusal stops at once
instead of waiting at the gate for ever.

Usage:
    python tests/campaign_memory_refusal_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import campaign as cp  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from campaign_unit import make_plan, make_survey  # noqa: E402

SCRATCH = scratch_dir("campaign_memory_refusal_unit")
GB = 1024.0**3
MACHINE = SimpleNamespace(total=64.0 * GB, available=60.0 * GB)


class Reached(Exception):
    """Raised by the stand-in `run_campaign`: main went on to run the campaign."""


def run_main(min_gb: float, dry: bool) -> tuple[int | str, str, str]:
    """Run campaign.main on a 64 GB machine with a plan at `min_gb`; return (code, stdout, stderr)."""
    root = SCRATCH / f"plan_{min_gb:g}_{'dry' if dry else 'run'}"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": min_gb,
              "peak_factor": 1.2, "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05}}
    plan_yaml = make_plan(root, runner=runner)
    out, err = io.StringIO(), io.StringIO()
    vm, run_campaign = cp.psutil.virtual_memory, cp.run_campaign

    def stand_in(*_args, **_kwargs):
        raise Reached

    cp.psutil.virtual_memory, cp.run_campaign = (lambda: MACHINE), stand_in
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cp.main([str(survey_yaml), str(plan_yaml), "--stage", "1", *(["--dry-run"] if dry else [])])
    except Reached:
        code = "ran the campaign"
    finally:
        cp.psutil.virtual_memory, cp.run_campaign = vm, run_campaign
    return code, out.getvalue(), err.getvalue()


def test_refused_at_start() -> None:
    for min_gb in (200.0, 64.0):
        for dry in (False, True):
            code, out, err = run_main(min_gb, dry)
            how = f"min_available_gb {min_gb:g} on a 64 GB machine{' (--dry-run)' if dry else ''}"
            assert code == 2, f"{how}: main gave {code!r}, expected exit 2\n{out[-800:]}{err[-800:]}"
            lines = [line for line in err.splitlines() if line.strip()]
            assert len(lines) == 1, f"{how}: expected one stderr line, got {lines}"
            line = lines[0]
            assert "plan.yaml" in line and f"min_available_gb {min_gb:g} GB" in line and "64.0 GB" in line, \
                f"{how}: the line does not name the plan, the setting and the machine: {line!r}"
            assert "=== " not in out and "stage 1" not in out, f"{how}: something ran or was listed:\n{out[-800:]}"
            print(f"  {how}: exit 2, {line}")


def test_feasible_plan_runs() -> None:
    code, out, err = run_main(40.0, True)
    assert code == 0 and "stage 1" in out, f"a 40 GB gate on a 64 GB machine was refused: {code!r}\n{err[-800:]}"
    print("  min_available_gb 40 on a 64 GB machine: the dry run exits 0 and lists stage 1")


def test_wait_line_amounts() -> None:
    root = SCRATCH / "gate"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 40.0,
              "peak_factor": 1.2, "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05}}
    plan = cp.load_plan(make_plan(root, runner=runner))
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    vm = cp.psutil.virtual_memory
    cp.psutil.virtual_memory = lambda: SimpleNamespace(total=64.0 * GB, available=30.0 * GB)
    try:
        ok, msg = c.gate()
    finally:
        cp.psutil.virtual_memory = vm
    assert not ok and "available 30.0 GB" in msg and "need 40.0 GB" in msg, (ok, msg)
    print(f"  40 GB needed, 30 GB available: held, {msg!r}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("The survey and plan")[0].strip())
    print()
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        else:
            print(f"  ok    {test.__name__}")
    print(f"\n{'FAIL' if failed else 'PASS'}  campaign_memory_refusal_unit ({len(tests) - len(failed)} of {len(tests)} "
          f"passed)")
    sys.exit(1 if failed else 0)
