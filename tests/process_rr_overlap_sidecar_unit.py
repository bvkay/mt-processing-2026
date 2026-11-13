# -*- coding: utf-8 -*-
"""
Unit test for workbench issue 181: process_rr.py's sidecar records the overlap each decimation level used

The default aurora run overlaps a level by 25 % of its window, and by 75 % on
every level whose window lasts over 600 s (`mt_workbench.process.build_config`,
`LONG_WINDOW_SECONDS`; issue 170), but the sidecar's `tweaks` said only
`overlap_pct 25.0`, so "the default window, 128 samples at 25 %" was a
misreading the sidecar invited. The sidecar key `overlap` holds the short
and long overlap in percent, the source of the long one
("--overlap-long", "survey overlap_long:", or "built-in 75 % (build_config)"),
the long-window threshold, and `levels`: one entry per decimation level of the
aurora config the run used (level, sample_rate, window_samples, window_s,
overlap_samples, overlap_pct, long).

A smoke run on the SA Flinders archives (FR05L rr FR01L, 2013-09-22 to 10-02
(10 days), no masks, tag J4overlap), twice: the default, and --overlap-long 25.
Skips (exit 0) when the survey's archives are absent.

**This test fails if**
  - either run does not exit 0 or writes no sidecar;
  - the default run's sidecar has no `overlap.levels`, no level with
    window_s over 600, or any level whose overlap_pct is not 75 where
    window_s > 600 and 25 elsewhere (to the rounding of
    round(num_samples * pct / 100)); or its `overlap.long_pct` is not 75 with
    a source naming "built-in"; or `tweaks.overlap_pct` is not 25;
  - the --overlap-long 25 run's levels are not all 25 %, or its long source
    does not name "--overlap-long".

Usage:
    python tests/process_rr_overlap_sidecar_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SURVEY = REPO / "surveys" / "south_australia_auslamp_2013_2018" / "survey.yaml"
WS = Path(r"D:\MT_DATA\MT_SA_AusLAMP_2013_2018_Workspace")
LOCAL, REMOTE = "FR05L", "FR01L"
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def run(tag: str, *extra) -> dict | None:
    """Run process_rr.py on the pair (10 days, no masks) and return the sidecar of its product."""
    before = set((WS / "tf").glob(f"{LOCAL}_rr-{REMOTE}_*_{tag}.json"))
    cmd = [sys.executable, str(REPO / "scripts" / "process_rr.py"), str(SURVEY), LOCAL, REMOTE,
           "2013-09-22 00:00", "2013-10-02 00:00", "--no-masks", "--tag", tag, *extra]
    p = subprocess.run(cmd, capture_output=True, text=True)
    after = sorted(set((WS / "tf").glob(f"{LOCAL}_rr-{REMOTE}_*_{tag}.json")) - before)
    check(p.returncode == 0 and len(after) == 1, f"{tag}: exit {p.returncode}, new sidecar {[a.name for a in after]}"
          + ("" if p.returncode == 0 else f"; {(p.stdout + p.stderr).strip().splitlines()[-1]}"))
    return json.loads(after[-1].read_text(encoding="utf-8")) if after else None


def main() -> int:
    if not (WS / "mth5" / f"{LOCAL}.h5").exists() or not (WS / "mth5" / f"{REMOTE}.h5").exists():
        print("process_rr_overlap_sidecar_unit: SKIP (the SA archives are absent)")
        return 0
    side = run("J4overlap")
    if side is not None:
        ov = side.get("overlap") or {}
        levels = ov.get("levels") or []
        print(f"default: overlap {json.dumps({k: v for k, v in ov.items() if k != 'levels'})}")
        for lv in levels:
            print(f"    {lv}")
        long_ = [lv for lv in levels if lv["window_s"] > 600]
        right = all(lv["overlap_samples"] == round(lv["window_samples"] * (0.75 if lv["window_s"] > 600 else 0.25))
                    and abs(lv["overlap_pct"] - (75.0 if lv["window_s"] > 600 else 25.0)) < 0.5 for lv in levels)
        check(bool(levels) and bool(long_) and right, f"default: {len(levels)} levels, {len(long_)} long; "
                                                      f"overlap 75 % exactly on the long ones: {right}")
        check(ov.get("long_pct") == 75.0 and "built-in" in str(ov.get("long_source")),
              f"default: long_pct {ov.get('long_pct')}, source {ov.get('long_source')!r}")
        check((side.get("tweaks") or {}).get("overlap_pct") == 25.0,
              f"default: tweaks.overlap_pct {(side.get('tweaks') or {}).get('overlap_pct')}")
    side = run("J4overlap-long25", "--overlap-long", "25")
    if side is not None:
        ov = side.get("overlap") or {}
        levels = ov.get("levels") or []
        check(bool(levels) and all(abs(lv["overlap_pct"] - 25.0) < 0.5 for lv in levels)
              and "--overlap-long" in str(ov.get("long_source")),
              f"--overlap-long 25: levels {[lv['overlap_pct'] for lv in levels]}, source {ov.get('long_source')!r}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
