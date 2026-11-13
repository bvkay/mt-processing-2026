# -*- coding: utf-8 -*-
"""
Unit test for stack membership at the edges of a window shorter than the overlap rule (intersite.select_stack)

A window shorter than `MIN_OVERLAP_HOURS` asks a stack member to cover the
whole window. `member_changes`, which judges whether a base stack's
membership stays the same across the window, treats a member's start or
end within `MEMBER_EDGE_S` (60 s) of the window's edges as no change, so a
member ending a few seconds before the window's end belongs to the base
stack by that rule and must not be left out by `select_stack` (upstream
89). `select_stack` applies that tolerance when `edge_s` is given, and
process_intersite.py gives it for the base stack only; without it the
whole window less one sample is asked for, the rule of other stacks.

A scratch survey at 100 Hz holds archives written with h5py that carry
only what `archive_runs` reads: one run per site with its time_period
attributes and ex, ey, hx, hy datasets. The window is 6 h. FULL covers it
with an hour to spare at each side; E1, E30, E59 and E61 start an hour
early and end 1, 30, 59 and 61 s before the window's end; S59 and S61
start 59 and 61 s after the window's start and end an hour late; G30
covers the window with a gap of 30 s in its middle (two runs). The local
L covers the window; B has no archive. The survey's stacks.yaml declares
a base recipe (field E) and a reference recipe (field H) with the member
rule.

Usage:
    python tests/intersite_stack_edge_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (kept) `select_stack` with `edge_s` = `MEMBER_EDGE_S` over the 6 h
   window leaves out FULL, E1, E30, E59, S59 or G30;
2. (control, left out) with `edge_s` it keeps E61 or S61, whose start or
   end lies more than 60 s inside the window;
3. (the two rules agree) `member_changes` over the same window names a
   change for FULL, E1, E30, E59, S59 or G30, or names none for E61 or
   S61: a site kept by `select_stack` with `edge_s` must be one whose
   record `member_changes` reads as unchanged, and the reverse;
4. (longer window unchanged) with `edge_s` and `min_overlap_hours` 2 over
   the same 6 h window (the window then longer than the rule) any of the
   eight sites is left out, since each covers more than 2 h;
5. (no edge_s: the whole window) without `edge_s` `select_stack` keeps any
   site but FULL, or E30's reason differs from "its runs with ex/ey cover
   5.99 h of the window, under 6 h", the text of the rule without a
   tolerance;
6. (the script: base stack only) process_intersite.py's `resolve` with
   `--base-stack E --remote-stack H` over the window, or with the base and
   reference recipes of stacks.yaml, leaves FULL, E1, E30, E59, S59 or G30
   out of the base stack, keeps E61 or S61 in it, or keeps any site but
   FULL in the reference stack, or gives E30 another reference-stack
   reason than the text of 5 with hx/hy (the script passes the tolerance
   to its base stack and not to its reference stack).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRATCH = scratch_dir("intersite_stack_edge_unit")
SCRIPT = REPO / "scripts" / "process_intersite.py"
LO = pd.Timestamp("2024-03-01T00:00:00", tz="UTC")
HI = LO + pd.Timedelta(hours=6)
HOUR = pd.Timedelta(hours=1)
SEC = pd.Timedelta(seconds=1)
RUNS = {
    "FULL": [(LO - HOUR, HI + HOUR)],
    "E1": [(LO - HOUR, HI - 1 * SEC)],
    "E30": [(LO - HOUR, HI - 30 * SEC)],
    "E59": [(LO - HOUR, HI - 59 * SEC)],
    "E61": [(LO - HOUR, HI - 61 * SEC)],
    "S59": [(LO + 59 * SEC, HI + HOUR)],
    "S61": [(LO + 61 * SEC, HI + HOUR)],
    "G30": [(LO - HOUR, LO + 3 * HOUR), (LO + 3 * HOUR + 30 * SEC, HI + HOUR)],
}
LOCAL_RUNS = [(LO - HOUR, HI + HOUR)]
KEPT = ("FULL", "E1", "E30", "E59", "S59", "G30")
LEFT = ("E61", "S61")
E30_REASON = "its runs with {} cover 5.99 h of the window, under 6 h"  # the rule without a tolerance
STACKS_YAML = """\
# written by tests/intersite_stack_edge_unit.py
STK_BASE:
  field: E
  use: base
  sample_rate: 100.0
  min_members: 1

STK_REF:
  field: H
  use: reference
  sample_rate: 100.0
  min_members: 1
"""

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def write_archive(path: Path, site: str, runs) -> None:
    """Write an archive holding each run's times and ex, ey, hx, hy datasets."""
    with h5py.File(path, "w") as f:
        for k, (start, end) in enumerate(runs):
            g = f.create_group(f"Experiment/Surveys/SYNTH/Stations/{site}/sr100_{k + 1:04d}")
            g.attrs["time_period.start"] = start.isoformat()
            g.attrs["time_period.end"] = end.isoformat()
            for comp in ("ex", "ey", "hx", "hy"):
                g.create_dataset(comp, data=np.zeros(1, dtype="int32"))


def build() -> Survey:
    """Write survey.yaml, stacks.yaml and one archive per site; return the survey."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    work = SCRATCH / "survey" / "work"
    (work / "mth5").mkdir(parents=True)
    sites = ["L", "B", *RUNS]
    text = (f"name: stack_edge\ninstrument: lemi423\nsample_rate: 100\ndata_root: {(SCRATCH / 'survey').as_posix()}\n"
            f"workspace: {work.as_posix()}\ndefaults:\n  channels: [ex, ey, hx, hy]\nsites:\n"
            + "".join(f"  {s}: {{latitude: -31.0, longitude: 137.0}}\n" for s in sites))
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(text, encoding="utf-8")
    (SCRATCH / "survey" / "stacks.yaml").write_text(STACKS_YAML, encoding="utf-8")
    for site, runs in RUNS.items():
        write_archive(work / "mth5" / f"{site}.h5", site, runs)
    write_archive(work / "mth5" / "L.h5", "L", LOCAL_RUNS)
    return Survey.from_yaml(yaml_path)


def load_script():
    """Import scripts/process_intersite.py as a module."""
    loader = importlib.util.spec_from_file_location("process_intersite", SCRIPT)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def script_stacks(script, how: str, extra: list[str]) -> None:
    """Criterion 6 for one form of the stacks: the script's resolve, base and reference members."""
    window = [LO.strftime("%Y-%m-%d %H:%M"), HI.strftime("%Y-%m-%d %H:%M")]
    argv = [str(SCRATCH / "survey" / "survey.yaml"), "L", *window, "--kind", "telluric", *extra,
            "--allow-shared-members", "--dry-run"]
    try:
        res = script.resolve(script.build_parser().parse_intermixed_args(argv),
                             pd.Timestamp.now(tz="UTC").to_pydatetime())
    except script.Refused as exc:
        check(False, f"6 {how}: resolve refused: {exc}")
        return
    base_kept = [m["site"] for m in res["base_stack"]["members"]]
    ref_kept = [m["site"] for m in res["reference"]["members"]]
    ref_reasons = {d["site"]: d["reason"] for d in res["reference"]["left_out"]}
    check(all(s in base_kept for s in KEPT) and not any(s in base_kept for s in LEFT),
          f"6 {how}: base stack keeps FULL, E1, E30, E59, S59, G30 and not E61, S61: {base_kept}")
    want = E30_REASON.format("hx/hy")
    check(ref_kept == ["FULL"] and ref_reasons.get("E30") == want,
          f"6 {how}: reference stack keeps FULL only, E30 left out as {want!r}: {ref_kept}, "
          f"E30 {ref_reasons.get('E30')!r}")


def main() -> int:
    """Run the criteria; return 0 when all pass."""
    survey = build()
    lo, hi = int(LO.value), int(HI.value)
    edge_s = intersite.MEMBER_EDGE_S
    members, left_out = intersite.select_stack(survey, "L", "B", lo, hi, ("ex", "ey"), edge_s=edge_s)
    kept = [m["site"] for m in members]
    reasons = {d["site"]: d["reason"] for d in left_out}
    print(f"members {kept}")
    for site in LEFT:
        print(f"  left out {site}: {reasons.get(site)}")

    # 1. kept, 2. left out
    check(all(s in kept for s in KEPT), f"1 FULL, E1, E30, E59, S59 and G30 kept: {[s for s in KEPT if s in kept]}")
    check(not any(s in kept for s in LEFT), f"2 E61 and S61 left out: {[s for s in LEFT if s not in kept]}")

    # 3. the two rules agree
    changes = intersite.member_changes(survey, list(RUNS), ("ex", "ey"), lo, hi)
    changed = sorted({c["site"] for c in changes})
    check(changed == sorted(LEFT), f"3 member_changes names changes for {changed} only (expected {sorted(LEFT)})")

    # 4. the window longer than the rule
    members2, _left2 = intersite.select_stack(survey, "L", "B", lo, hi, ("ex", "ey"), min_overlap_hours=2.0,
                                              edge_s=edge_s)
    kept2 = sorted(m["site"] for m in members2)
    check(kept2 == sorted(RUNS), f"4 with a 2 h rule every site is kept: {kept2}")

    # 5. without edge_s: the whole window less one sample
    members3, left3 = intersite.select_stack(survey, "L", "B", lo, hi, ("ex", "ey"))
    kept3 = [m["site"] for m in members3]
    reason3 = {d["site"]: d["reason"] for d in left3}.get("E30")
    check(kept3 == ["FULL"], f"5 without edge_s only FULL is kept: {kept3}")
    want = E30_REASON.format("ex/ey")
    check(reason3 == want, f"5 without edge_s E30 is left out as {want!r}: {reason3!r}")

    # 6. the script: the tolerance for the base stack, not for the reference stack
    script = load_script()
    script_stacks(script, "flags", ["--base-stack", "E", "--remote-stack", "H", "--stack-min-members", "1"])
    script_stacks(script, "recipes", ["--stack", "STK_BASE", "--stack", "STK_REF"])

    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILURE(S)'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
