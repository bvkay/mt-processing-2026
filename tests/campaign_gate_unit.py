# -*- coding: utf-8 -*-
"""
Unit test for campaign.py's default number of jobs: what the memory gate admits

`gate_slots`, `Campaign.gate_admits` against the gate itself, the plan key
`runner.parallel` and the start line of a dry run, on the synthetic survey
and plan of tests/campaign_unit.py, with psutil's available memory stubbed.

Usage:
    python tests/campaign_gate_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `gate_slots` with 107.7 GB available does not give 4
jobs at a 22.4 GB peak (need 25 or 40 GB), 3 at 34.6 GB (need 34.6) and 2 at
34.6 GB (need 40), 4 at 25 GB with 100 GB and need 25, 3 with 99.99 GB, and 0
when the need exceeds the available memory; `gate_admits` disagrees with the
number of rr jobs `Campaign.gate` lets start one after another (each running
job still at RSS 0) with 107.7 GB available, from the plan's 22.4 GB figure
(4) and from 30 finished rr peaks whose 90th percentile is 34.6 GB (3), or
its line does not name the peak's source; `runner.parallel` 3 does not load
as 3, `gate` or no key as None, or 0, 2.5 or "four" loads; or the dry run's
start line does not say "admits 4" with "parallel 4 (the gate's count" when
neither --parallel nor runner.parallel is given, "parallel 2 (--parallel)"
with --parallel 2 and "parallel 3 (runner.parallel)" with the key at 3.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import campaign_unit as cu  # noqa: E402

cp = cu.cp
GiB = 1024.0**3
RUNNER = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 25.0, "peak_factor": 1.0,
          "expected_peak_gb": {"rr": 22.4, "variant": 24.0, "stack": 8.0}}


def check_arithmetic() -> None:
    cases = [((107.7, 22.4, 25.0), 4), ((107.7, 22.4, 40.0), 4), ((107.7, 34.6, 34.6), 3),
             ((107.7, 34.6, 40.0), 2), ((100.0, 25.0, 25.0), 4), ((99.99, 25.0, 25.0), 3), ((20.0, 22.4, 25.0), 0)]
    for args, want in cases:
        got = cp.gate_slots(*args)
        assert got == want, f"gate_slots{args} = {got}, want {want}"
    try:
        cp.gate_slots(100.0, 0.0, 25.0)
    except ValueError:
        pass
    else:
        raise AssertionError("gate_slots accepted a zero peak")
    print("gate_slots: 107.7 GB -> 4 at 22.4 GB (need 25 or 40), 3 at 34.6 (need 34.6), 2 at 34.6 (need 40); "
          "100 GB -> 4 at 25, 99.99 -> 3; 20 GB -> 0; a zero peak refused")


def started_by_gate(c, job) -> int:
    """Return how many copies of `job` the gate starts one after another, each running at RSS 0."""
    c._running.clear()
    n = 0
    while n < 20 and c.gate(job)[0]:
        c._running[f"r{n}"] = cp.Running(job, popen=None, ps=None, started=cp.now(), t0=0.0,
                                         log_path=Path("x.log"), log_offset=0, rss_mb=0.0)
        n += 1
    c._running.clear()
    return n


def check_admits() -> None:
    root = cu.ROOT / "gate_admits"
    survey_yaml = cu.make_survey(root)
    c = cp.Campaign(survey_yaml, cp.load_plan(cu.make_plan(root, runner=RUNNER)), parallel=1, create=False)
    rr = c.rr_job(1, "A", "B", "default", "s1_A_rr-B")
    original = cp.psutil.virtual_memory
    cp.psutil.virtual_memory = lambda: SimpleNamespace(available=107.7 * GiB, total=127.7 * GiB)
    try:
        n_plan, line_plan = c.gate_admits()
        gate_plan = started_by_gate(c, rr)
        # 30 finished rr peaks, 26 at 20 GB, one at 34.6 and 3 at 40: the ledger's nearest-rank 90th
        # percentile (index 26 of 30) is 34.6 GB
        peaks = [20.0] * 26 + [34.6] + [40.0] * 3
        for k, gb in enumerate(peaks):
            rid = f"s1_X{k}_rr-Y"
            c.ledger.rows[rid] = {**{key: "" for key in cp.LEDGER_COLUMNS}, "run_id": rid, "kind": "rr",
                                  "config": "default", "status": "done", "peak_rss_mb": str(gb * 1024.0),
                                  "finished": f"2026-10-03T05:{k:02d}:00"}
        p90 = c.expected_peak_mb("rr") / 1024.0
        n_led, line_led = c.gate_admits()
        gate_led = started_by_gate(c, rr)
    finally:
        cp.psutil.virtual_memory = original
    assert n_plan == gate_plan == 4, (n_plan, gate_plan, line_plan)
    assert "rr peak 22.4 GB (runner.expected_peak_gb rr" in line_plan and "admits 4 rr job(s)" in line_plan, line_plan
    assert abs(p90 - 34.6) < 0.05, p90
    assert n_led == gate_led == 3, (n_led, gate_led, line_led)
    assert "p90 of the last 30 finished rr runs" in line_led and "admits 3 rr job(s)" in line_led, line_led
    print(f"gate_admits == jobs the gate starts: {line_plan!r} ({gate_plan} started); {line_led!r} "
          f"({gate_led} started)")


def check_plan_key() -> None:
    root = cu.ROOT / "gate_key"
    cu.make_survey(root)
    for value, want in ((3, 3), ("gate", None), (None, None)):
        runner = dict(RUNNER) if value is None else {**RUNNER, "parallel": value}
        got = cp.load_plan(cu.make_plan(root / f"k{value}", runner=runner)).parallel
        assert got == want, (value, got)
    for bad in (0, 2.5, "four"):
        try:
            cp.load_plan(cu.make_plan(root / f"bad{bad}", runner={**RUNNER, "parallel": bad}))
        except ValueError as exc:
            assert "runner parallel" in str(exc), str(exc)
        else:
            raise AssertionError(f"runner.parallel {bad!r} loaded")
    print("runner.parallel: 3 -> 3, gate and no key -> None (the gate's count); 0, 2.5 and 'four' refused")


def check_dry_run_line() -> None:
    root = cu.ROOT / "gate_dry"
    survey_yaml = cu.make_survey(root)
    plain = cu.make_plan(root / "plain", runner=RUNNER)
    keyed = cu.make_plan(root / "keyed", runner={**RUNNER, "parallel": 3})
    original = cp.psutil.virtual_memory
    cp.psutil.virtual_memory = lambda: SimpleNamespace(available=107.7 * GiB, total=127.7 * GiB)
    lines = {}
    try:
        for name, argv in (("gate", [str(survey_yaml), str(plain), "--stage", "0", "--dry-run"]),
                           ("flag", [str(survey_yaml), str(plain), "--stage", "0", "--dry-run", "--parallel", "2"]),
                           ("key", [str(survey_yaml), str(keyed), "--stage", "0", "--dry-run"])):
            _, out = cu.quiet(cp.main, argv)
            lines[name] = next((ln for ln in out.splitlines() if ln.startswith("memory gate:")), "")
    finally:
        cp.psutil.virtual_memory = original
    assert "admits 4 rr job(s)" in lines["gate"] and "parallel 4 (the gate's count" in lines["gate"], lines
    assert lines["flag"].endswith("parallel 2 (--parallel)"), lines
    assert lines["key"].endswith("parallel 3 (runner.parallel)"), lines
    print(f"dry run start line: {lines['gate']!r}; with --parallel 2 ...{lines['flag'][-26:]!r}; "
          f"runner.parallel 3 ...{lines['key'][-30:]!r}")


def main() -> int:
    """Run every check and return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    check_arithmetic()
    check_admits()
    check_plan_key()
    check_dry_run_line()
    print("\nPASS  campaign_gate_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
