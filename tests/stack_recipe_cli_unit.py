# -*- coding: utf-8 -*-
"""
Unit test for the recipe forms of scripts/process_intersite.py (--stack NAME) and scripts/build_stack.py (--recipe NAME)

A recipe of stacks.yaml (`mt_workbench.stacks`) is a second way to give a
stack to the two scripts; the test holds each recipe run against the run
the existing flags make of the same stack, which wires the same library
calls by a different path, and checks the records, the refusals and the
archive rules the recipe forms add.

The band part uses tests/intersite_stack_unit.py's scratch survey (100 Hz,
3 h; the pair L, B, whose T is intersite_unit's model, and the sites M1-M5,
N3 and W, each with E = 0.8 of the base's clean E plus its own noise; M3 has
a fault over 5 % of the record), built in this test's own scratch folder,
with a stacks.yaml written here by hand:

- STK_E, a band_mean reference stack of field E, members rule, exclude M3;
- STK_EM, the same with band_median;
- STK_B, a band_mean base stack of field E, exclude B, N3 and W (members
  M1-M5), screen_polarity drop;
- STK_BN, the same base without the drop and with every band key off its
  default: reject_factor 10, min_members 3, min_overlap_hours 2,
  member_change allow;
- STK_EW and STK_BW, a reference and a base recipe with windows that
  differ; STK_BH (a field H base), STK_E1K (at 1000 Hz), STK_T (a time
  recipe) and STK_BAD (screen_polarity: off on a reference), for refusals.

The time part writes a scratch survey "SYNTH" at 1000 Hz from
tests/virtual_unit.py's members (`synthetic_members`, `write_archive`): A1,
A2 and A3 over 40 min 1.234 s from 2023-09-19 20:00, and P2, written as two
runs split 20 min into the window (20:00-20:20, then 20:20:10 to the end),
with the time recipes STK_T (time_mean, A1-A3, 20:00-20:40), STK_T2 (A1, A2,
P2), STK_T3 (A1, P2), STK_LEG (the name of a legacy positional build), STK_TC
(time_coherence, A1-A3, 20:00-20:20, under the 30 min a coherence window
needs) and a band recipe STK_BAND.

Usage:
    python tests/stack_recipe_cli_unit.py [--quick]

--quick leaves out criterion 6 (the five existing suites, several minutes).
Exit 0 when every criterion ran and passed, 1 on a failure, 2 when no
criterion failed but a suite of criterion 6 could not run here (campaign_unit
without its plan file): "NOT COMPLETE", never a pass.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (reference recipe, mean) `process_intersite.py L B --kind telluric
   --stack STK_E` writes a CSV that differs by one byte, or an h5 estimate
   that differs in any value, from `--remote-stack E --exclude M3`; its
   sidecar's reference block differs from the flag run's in any key other
   than exclude_from, or does not add exactly recipe, recipe_hash (equal to
   `stacks.recipe_hash` of the loaded recipe) and recipe_text (equal to
   `stacks.canonical_text`); either run's block lacks method "mean"; or
   its stem is not L_te-B_rr-STK_E, or the flag run's not L_te-B_rr-stackE;
2. (median) the STK_EM run differs from `--remote-stack E --stack-method
   median --exclude M3` as in 1; its h5 attribute stack_method is not
   "median" (nor the flag run's) or its stack_recipe is not STK_EM; its
   estimate equals the band_mean run's in every value of the tensor; or the
   band_mean or the band_median recipe run fails
   `intersite_unit.recovery`'s element criterion against the model T (more
   than 5 % of element-bands beyond 3 sigma, or any beyond 5 sigma); or the
   flag median's stem is not L_te-B_rr-stackEmed;
3. (base recipe) `L --kind telluric --stack STK_B --remote B` differs from
   `L --kind telluric --base-stack E --exclude B,N3,W --screen-polarity drop
   --remote B` in its CSV bytes, its estimate, or any key of the sidecar's
   base_stack block (the members with their per-band record, the polarity
   flags and screen record, the band record) other than the three recipe
   keys it adds; its stem is not L_te-STK_B_rr-B; or its h5 lacks
   base_stack_method "mean", base_stack_recipe STK_B and the recipe's hash;
   or STK_BN differs from `--base-stack E --exclude B,N3,W
   --stack-reject-factor 10 --stack-min-members 3 --min-overlap-hours 2
   --allow-member-change --remote B` in its CSV bytes, its estimate or any key
   of the base_stack block other than the recipe keys, or either block does
   not record reject_factor 10, min_members 3, min_overlap_hours 2 and
   window_members_constant false;
4. (resolution and refusals) a dry run with STK_EW does not take the
   recipe's window 00:30-02:30, or with start and end on the command line
   does not take theirs and print the recipe's as recipe_window; or any of
   these exits other than 2, or without naming the recipe in stderr: a
   recipe with --remote-stack, --base-stack, --stack-plain, --exclude,
   --stack-method or --screen-polarity; a time recipe (also naming
   build_stack.py); an unknown name (also listing STK_E); two reference
   recipes; --no-filters against a recipe's use_filters; a base recipe of
   field H with --kind telluric; a recipe at 1000 Hz with a 100 Hz local;
   recipes whose windows differ; a reference recipe with --remote; a base
   recipe with a named base; an invalid recipe (also naming its key); a
   base recipe with no reference (naming the recipe and --remote); or
   no reference at all, --stack-method without a stack or with
   --stack-plain, exit other than 2; or any dry run or refusal writes a
   file; or the command lines `stacks.intersite_argv` builds for the GUI
   (STK_B with --remote B and a window, STK_E with the base B) do not dry
   run with exit 0, the recipe's stem, and that window (STK_B) or the
   window the flag run `--remote-stack E --exclude M3` prints (STK_E);
5. (build_stack.py --recipe) the STK_T build's hx or hy is not identical to
   the legacy positional build's (`STK_LEG <start> <end> A1 A2 A3`), or the
   legacy build's station comment is not the frozen default or its run
   comment not empty; the STK_T station comment lacks
   "recipe=STK_T recipe_hash=<hash>", or `virtual.recorded_provenance`
   lacks the hash, the canonical text, the members A1-A3 or, for each, a
   source identity equal to `ingest.archive_identity` of its processing
   archive; a second run, or a third through `stacks.build_argv` (the
   GUI's, with --overwrite), is not reused (exit 0, "reused", the archive's
   bytes and modification time unchanged); with a folder .build_99999 holding
   a file left in the mth5 folder, the second run's stdout has no line of
   leftover build folders naming it and "remove them by hand", or the folder
   or its file is gone after the run; after `os.utime` moves A2's
   archive time, a run without --overwrite does not exit 2 naming A2 with
   the archive unchanged, or one with --overwrite does not record A2's new
   identity; after the recipe's end moves to 20:30, a run without
   --overwrite exits 0, or one with it records the old hash; a rebuild
   made to fail (A3 rewritten half a sample off the others' grid, with
   --overwrite) exits other than 2, changes a byte of STK_T.h5 or leaves a
   .build_* folder; STK_T2 does not leave P2 out with its coverage reason
   and build from A1 and A2 alone, or STK_T3 (one member left) does not
   exit 2 naming P2; `built_span_short` returns None for a stack starting
   61 s after the window's start or ending 61 s before its end, or a reason
   for 59 s; --check with a recipe does not print the coherence table or
   writes a file; or positionals or --weighting with --recipe, a band
   recipe, an unknown recipe, or --overwrite without --recipe exit 0; or
   `--recipe STK_TC` (time_coherence over 20 min) exits other than 2, its
   stderr lacks STK_TC, "20 min" or "30 min", or the mth5 folder's listing or
   modification time changes (a .build_ folder made and removed); or
   `--recipe STK_LEG --overwrite` over the legacy build STK_LEG.h5 (no
   recorded recipe) exits other than 2, does not say it was not built from
   a recipe, or changes a byte of it; or --check through a survey.yaml whose
   name is not the archives' survey exits other than 2 or prints a
   traceback;
6. (unless --quick) tests/intersite_stack_unit.py,
   tests/intersite_basestack_unit.py, tests/intersite_basestack_h_unit.py,
   tests/virtual_unit.py or tests/campaign_unit.py exits other than 0.
   campaign_unit reads surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml,
   which is gitignored (workbench issue 29); where it is absent the suite is
   reported NOT RUN and the test exits 2.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import intersite_stack_unit as isu  # noqa: E402
import virtual_unit as vu  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from intersite_unit import A, PHI0_DEG, TAU_S, model_bands, recovery  # noqa: E402
from mt_workbench import intersite, stacks  # noqa: E402
from mt_workbench.ingest import archive_identity, processing_archive  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.virtual import recorded_provenance  # noqa: E402

INTERSITE = REPO / "scripts" / "process_intersite.py"
BUILD = REPO / "scripts" / "build_stack.py"
SCRATCH = scratch_dir("stack_recipe_cli_unit")
SUITES = ("intersite_stack_unit.py", "intersite_basestack_unit.py", "intersite_basestack_h_unit.py",
          "virtual_unit.py", "campaign_unit.py")
RECIPE_KEYS = {"recipe", "recipe_hash", "recipe_text"}
# the plan campaign_unit reads: gitignored, so absent from a worktree or a clean checkout (workbench issue 29)
CAMPAIGN_PLAN = REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "campaign_lineC.yaml"

failures: list[str] = []
not_run: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def last_line(res: subprocess.CompletedProcess) -> str:
    """Return the last line of stderr, shortened."""
    return (res.stderr.strip().splitlines() or [""])[-1][:170]


def sha256(path: Path) -> str | None:
    """Return the SHA-256 of a file's bytes, None when the file is gone."""
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


# --- the band part: process_intersite.py --stack ------------------------------------------------------------

BAND_STACKS = """\
# written by tests/stack_recipe_cli_unit.py
STK_E:
  field: E
  use: reference
  method: band_mean
  sample_rate: 100.0
  members: rule
  exclude: [M3]

STK_EM:
  field: E
  use: reference
  method: band_median
  sample_rate: 100.0
  members: rule
  exclude: [M3]

STK_B:
  field: E
  use: base
  sample_rate: 100.0
  exclude: [B, N3, W]
  screen_polarity: drop

STK_BN:
  field: E
  use: base
  sample_rate: 100.0
  exclude: [B, N3, W]
  min_overlap_hours: 2.0
  reject_factor: 10.0
  min_members: 3
  member_change: allow

STK_EW:
  field: E
  use: reference
  sample_rate: 100.0
  exclude: [M3]
  start: 2024-03-01 00:30
  end: 2024-03-01 02:30

STK_BW:
  field: E
  use: base
  sample_rate: 100.0
  exclude: [B, N3, W]
  start: 2024-03-01 01:00
  end: 2024-03-01 02:00

STK_BH:
  field: H
  use: base
  sample_rate: 100.0

STK_E1K:
  field: E
  use: reference
  sample_rate: 1000.0

STK_T:
  field: H
  use: remote
  method: time_mean
  sample_rate: 100.0
  members: [M1, M2]
  start: 2024-03-01 00:00
  end: 2024-03-01 02:00

STK_BAD:
  field: E
  use: reference
  sample_rate: 100.0
  screen_polarity: off
"""


def intersite_run(yaml_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run process_intersite.py on the band survey."""
    return subprocess.run([sys.executable, str(INTERSITE), str(yaml_path), *args], capture_output=True, text=True,
                          cwd=REPO)


def products(out: Path, stem: str) -> dict:
    """Read a run's products: the sidecar, the h5 estimate and attributes, and the CSV bytes."""
    est, _letter, attrs = intersite.read_h5(out / f"{stem}.h5")
    return {"side": json.loads((out / f"{stem}.json").read_text(encoding="utf-8")), "est": est, "attrs": attrs,
            "csv": (out / f"{stem}.csv").read_bytes()}


def same_estimate(a, b) -> bool:
    """Return whether two TensorEstimates are equal in every value (NaN equal to NaN)."""
    return all(np.array_equal(np.asarray(getattr(a, f.name)), np.asarray(getattr(b, f.name)), equal_nan=True)
               for f in dataclasses.fields(a))


def block_difference(flag: dict, recipe: dict, ignore=("exclude_from",)) -> list[str]:
    """Return the keys in which a recipe run's stack block differs from the flag run's, recipe keys aside."""
    keys = (set(flag) | set(recipe)) - RECIPE_KEYS - set(ignore)
    return sorted(k for k in keys if flag.get(k, "<missing>") != recipe.get(k, "<missing>"))


def band_part() -> None:
    """Criteria 1-4."""
    isu.SCRATCH = SCRATCH / "band"  # build_survey writes under its module's SCRATCH; keep it in this test's folder
    yaml_path, _spec = isu.build_survey()
    (yaml_path.parent / stacks.STACKS_FILE).write_text(BAND_STACKS, encoding="utf-8")
    survey = Survey.from_yaml(yaml_path)
    recipes, errors = stacks.load_recipes(survey)
    print(f"band survey: {yaml_path}; recipes {sorted(recipes)}, invalid {sorted(errors)}")
    fmap, _scheme = model_bands(yaml_path)
    out = SCRATCH / "band_out"
    shutil.rmtree(out, ignore_errors=True)
    o = ("--out-dir", str(out))
    pair = ("L", "B", "--kind", "telluric")

    # 4. dry runs and refusals first: none may write a file
    res = intersite_run(yaml_path, *pair, "--stack", "STK_EW", *o, "--dry-run")
    check(res.returncode == 0 and "window: 2024-03-01T00:30:00Z to 2024-03-01T02:30:00Z" in res.stdout
          and "recipe_window:" not in res.stdout and "stem: L_te-B_rr-STK_EW" in res.stdout
          and f"stack_recipe: STK_EW {stacks.recipe_hash(recipes['STK_EW'])}" in res.stdout,
          f"4 STK_EW's dry run takes the recipe's window 00:30-02:30 and prints its name and hash (exit "
          f"{res.returncode})")
    res = intersite_run(yaml_path, "L", "B", "2024-03-01 01:00", "2024-03-01 02:00", "--kind", "telluric",
                        "--stack", "STK_EW", *o, "--dry-run")
    check(res.returncode == 0 and "window: 2024-03-01T01:00:00Z to 2024-03-01T02:00:00Z" in res.stdout
          and "recipe_window: 2024-03-01T00:30:00Z to 2024-03-01T02:30:00Z (the command line's is used)"
          in res.stdout, f"4 start and end on the command line win over STK_EW's window, which is printed as "
                         f"recipe_window (exit {res.returncode})")
    res = intersite_run(yaml_path, "L", "--kind", "telluric", "--stack", "STK_B", "--remote", "B", *o, "--dry-run")
    members = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("base_member: ")]
    check(res.returncode == 0 and members == ["M1", "M2", "M3", "M4", "M5"] and "stem: L_te-STK_B_rr-B" in res.stdout
          and "base_stack_method: mean" in res.stdout and "polarity_screen: drop" in res.stdout,
          f"4 STK_B's dry run: base members {members}, screen drop, stem L_te-STK_B_rr-B (exit {res.returncode})")
    res = intersite_run(yaml_path, *pair, "--remote-stack", "E", "--stack-method", "median", "--exclude", "M3", *o,
                        "--dry-run")
    check(res.returncode == 0 and "stem: L_te-B_rr-stackEmed" in res.stdout and "stack_method: median" in res.stdout,
          f"2 --stack-method median's dry run: stem L_te-B_rr-stackEmed, stack_method median (exit "
          f"{res.returncode})")
    refusals = (
        ("a recipe with --remote-stack", ("L", "--kind", "telluric", "--stack", "STK_B", "--remote-stack", "E"),
         ("STK_B",)),
        ("a recipe with --base-stack", pair + ("--stack", "STK_E", "--base-stack", "E"), ("STK_E",)),
        ("a recipe with --stack-plain", pair + ("--stack", "STK_E", "--stack-plain"), ("STK_E",)),
        ("a recipe with --exclude", pair + ("--stack", "STK_E", "--exclude", "M1"), ("STK_E", "--exclude")),
        ("a recipe with --stack-method", pair + ("--stack", "STK_E", "--stack-method", "median"), ("STK_E",)),
        ("a recipe with --screen-polarity", ("L", "--kind", "telluric", "--stack", "STK_B", "--remote", "B",
                                             "--screen-polarity", "flag"), ("STK_B",)),
        ("a time recipe", pair + ("--stack", "STK_T"), ("STK_T", "build_stack.py")),
        ("an unknown recipe", pair + ("--stack", "STK_NONE"), ("STK_NONE", "STK_E")),
        ("two reference recipes", pair + ("--stack", "STK_E", "--stack", "STK_EM"), ("STK_E", "STK_EM")),
        ("--no-filters against use_filters: true", pair + ("--stack", "STK_E", "--no-filters"), ("STK_E",)),
        ("a field H base recipe with --kind telluric", ("L", "--kind", "telluric", "--stack", "STK_BH", "--remote",
                                                        "B"), ("STK_BH",)),
        ("a 1000 Hz recipe with a 100 Hz local", pair + ("--stack", "STK_E1K"), ("STK_E1K",)),
        ("recipes whose windows differ", ("L", "--kind", "telluric", "--stack", "STK_BW", "--stack", "STK_EW"),
         ("STK_BW", "STK_EW")),
        ("a reference recipe with --remote", pair + ("--stack", "STK_E", "--remote", "M1"), ("STK_E",)),
        ("a base recipe with a named base", pair + ("--stack", "STK_B", "--remote", "M1"), ("STK_B",)),
        ("an invalid recipe", pair + ("--stack", "STK_BAD"), ("STK_BAD", "screen_polarity")),
        ("a base recipe with no reference", ("L", "--kind", "telluric", "--stack", "STK_B"), ("STK_B", "--remote")),
        ("no reference", pair, ("--remote",)),
        ("--stack-method without a stack", pair + ("--remote", "M1", "--stack-method", "median"), ()),
        ("--stack-method with --stack-plain", pair + ("--remote-stack", "E", "--stack-plain", "--stack-method",
                                                      "median"), ()),
    )
    for label, args, needles in refusals:
        res = intersite_run(yaml_path, *args, *o, "--dry-run")
        check(res.returncode == 2 and all(n in res.stderr for n in needles),
              f"4 refused, exit {res.returncode}, naming {', '.join(needles) or '(nothing asked)'}: {label}: "
              f"{last_line(res)}")
    # without a window the recipe run takes the common span, as the flag run does (it ends at the last sample)
    res = intersite_run(yaml_path, *pair, "--remote-stack", "E", "--exclude", "M3", *o, "--dry-run")
    span = next((ln for ln in res.stdout.splitlines() if ln.startswith("window: ")), "no window line")
    gui = (("STK_B", stacks.intersite_argv(sys.executable, INTERSITE, yaml_path, "L", "telluric", ["STK_B"],
                                           remote="B", start="2024-03-01 01:00", end="2024-03-01 02:00",
                                           dry_run=True),
            "window: 2024-03-01T01:00:00Z to 2024-03-01T02:00:00Z", "stem: L_te-STK_B_rr-B"),
           ("STK_E", stacks.intersite_argv(sys.executable, INTERSITE, yaml_path, "L", "telluric", ["STK_E"],
                                           base="B", dry_run=True),
            span, "stem: L_te-B_rr-STK_E"))
    for name, argv, window, stem in gui:
        res = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
        check(res.returncode == 0 and window in res.stdout and stem in res.stdout,
              f"4 stacks.intersite_argv's command line for {name} ({' '.join(argv[3:])}) dry runs: exit "
              f"{res.returncode}, {window!r} {window in res.stdout}, {stem!r} {stem in res.stdout}")
    check(not out.exists(), "4 the dry runs and refusals wrote nothing")

    # 1. the band_mean reference recipe against the flags
    runs = {"flag_mean": (pair + ("--remote-stack", "E", "--exclude", "M3"), "L_te-B_rr-stackE"),
            "recipe_mean": (pair + ("--stack", "STK_E"), "L_te-B_rr-STK_E"),
            "flag_median": (pair + ("--remote-stack", "E", "--stack-method", "median", "--exclude", "M3"),
                            "L_te-B_rr-stackEmed"),
            "recipe_median": (pair + ("--stack", "STK_EM"), "L_te-B_rr-STK_EM"),
            "flag_base": (("L", "--kind", "telluric", "--base-stack", "E", "--exclude", "B,N3,W",
                           "--screen-polarity", "drop", "--remote", "B"), "L_te-stackE_rr-B"),
            "recipe_base": (("L", "--kind", "telluric", "--stack", "STK_B", "--remote", "B"), "L_te-STK_B_rr-B"),
            # every band key off its default; its own folder, since the flag run's stem is flag_base's
            "flag_nondefault": (("L", "--kind", "telluric", "--base-stack", "E", "--exclude", "B,N3,W",
                                 "--stack-reject-factor", "10", "--stack-min-members", "3", "--min-overlap-hours",
                                 "2", "--allow-member-change", "--remote", "B"), "L_te-stackE_rr-B"),
            "recipe_nondefault": (("L", "--kind", "telluric", "--stack", "STK_BN", "--remote", "B"),
                                  "L_te-STK_BN_rr-B")}
    got = {}
    for key, (args, stem) in runs.items():
        tic = time.time()
        where = out / "nondefault" if key.endswith("nondefault") else out
        res = intersite_run(yaml_path, *args, "--out-dir", str(where))
        ok = res.returncode == 0 and (where / f"{stem}.h5").exists()
        if not check(ok, f"1-3 run {key} exits {res.returncode} and writes stem {stem} ({time.time() - tic:.0f} s)"):
            print(res.stdout[-2000:], res.stderr[-3000:])
            continue
        got[key] = products(where, stem)
    if {"flag_mean", "recipe_mean"} <= set(got):
        flag, rec = got["flag_mean"], got["recipe_mean"]
        check(flag["csv"] == rec["csv"] and same_estimate(flag["est"], rec["est"]),
              f"1 STK_E's CSV ({len(rec['csv'])} bytes) and estimate equal --remote-stack E --exclude M3's")
        diff = block_difference(flag["side"]["reference"], rec["side"]["reference"])
        added = set(rec["side"]["reference"]) - set(flag["side"]["reference"])
        r = rec["side"]["reference"]
        check(not diff and added == RECIPE_KEYS and r.get("recipe") == "STK_E"
              and r.get("recipe_hash") == stacks.recipe_hash(recipes["STK_E"])
              and r.get("recipe_text") == stacks.canonical_text(recipes["STK_E"]),
              f"1 STK_E's reference block equals the flag run's but for {diff or 'nothing'}, and adds {sorted(added)} "
              f"(hash {r.get('recipe_hash')})")
        check(r.get("method") == "mean" and flag["side"]["reference"].get("method") == "mean"
              and flag["attrs"].get("stack_method") == "mean" and "stack_recipe" not in flag["attrs"]
              and rec["attrs"].get("stack_recipe") == "STK_E",
              f"1 both blocks record method mean ({r.get('method')}, {flag['side']['reference'].get('method')}); h5 "
              f"stack_method {flag['attrs'].get('stack_method')}, stack_recipe {rec['attrs'].get('stack_recipe')}")
    if {"flag_median", "recipe_median"} <= set(got):
        flag, rec = got["flag_median"], got["recipe_median"]
        check(flag["csv"] == rec["csv"] and same_estimate(flag["est"], rec["est"]),
              "2 STK_EM's CSV and estimate equal --remote-stack E --stack-method median --exclude M3's")
        diff = block_difference(flag["side"]["reference"], rec["side"]["reference"])
        check(not diff and rec["side"]["reference"].get("method") == "median"
              and rec["attrs"].get("stack_method") == "median" and flag["attrs"].get("stack_method") == "median"
              and rec["attrs"].get("stack_recipe") == "STK_EM"
              and rec["attrs"].get("stack_recipe_hash") == stacks.recipe_hash(recipes["STK_EM"]),
              f"2 STK_EM's reference block equals the flag run's but for {diff or 'nothing'}; h5 stack_method "
              f"{rec['attrs'].get('stack_method')} (flag {flag['attrs'].get('stack_method')}), stack_recipe "
              f"{rec['attrs'].get('stack_recipe')}")
        check(rec["side"]["reference"].get("rule") == stacks.METHODS["band_median"].rule,
              "2 STK_EM's block records the median's rule")
    if {"recipe_mean", "recipe_median"} <= set(got):
        mean, median = got["recipe_mean"]["est"], got["recipe_median"]["est"]
        equal = np.array_equal(mean.tensor, median.tensor, equal_nan=True)
        check(not equal, f"2 the median run's tensor differs from the mean run's (largest difference "
                         f"{np.nanmax(np.abs(mean.tensor - median.tensor)):.3e}, relative to "
                         f"{np.nanmax(np.abs(mean.tensor)):.3f})")
        for label, est in (("band_mean (STK_E)", mean), ("band_median (STK_EM)", median)):
            r = recovery(est, fmap, A, PHI0_DEG, TAU_S, label, report=False)
            check(r["elements_ok"], f"2 recovery of the model T, {label}: {r['beyond3']} of {r['n']} element-bands "
                                    f"beyond 3 sigma (at most 5 %), {r['beyond5']} beyond 5 sigma, worst "
                                    f"{r['worst']:.2f} sigma")
    if {"flag_base", "recipe_base"} <= set(got):
        flag, rec = got["flag_base"], got["recipe_base"]
        check(flag["csv"] == rec["csv"] and same_estimate(flag["est"], rec["est"]),
              "3 STK_B's CSV and estimate equal --base-stack E --exclude B,N3,W --screen-polarity drop's")
        fb, rb = flag["side"]["base_stack"], rec["side"]["base_stack"]
        diff = block_difference(fb, rb, ignore=())
        check(not diff and set(rb) - set(fb) == RECIPE_KEYS and [m["site"] for m in rb["members"]]
              == [m["site"] for m in fb["members"]] and rb["screen_polarity"] == fb["screen_polarity"],
              f"3 STK_B's base_stack block equals the flag run's but for {diff or 'nothing'} (members "
              f"{[m['site'] for m in rb['members']]}, polarity flagged "
              f"{[f['site'] + ' ' + f['channel'] for f in rb['screen_polarity']['flagged']]}, dropped "
              f"{rb['screen_polarity']['dropped']})")
        a = rec["attrs"]
        check(a.get("base_stack_method") == "mean" and a.get("base_stack_recipe") == "STK_B"
              and a.get("base_stack_recipe_hash") == stacks.recipe_hash(recipes["STK_B"])
              and flag["attrs"].get("base_stack_method") == "mean" and "base_stack_recipe" not in flag["attrs"],
              f"3 h5: base_stack_method {a.get('base_stack_method')}, base_stack_recipe {a.get('base_stack_recipe')} "
              f"{a.get('base_stack_recipe_hash')}")
    if {"flag_nondefault", "recipe_nondefault"} <= set(got):
        flag, rec = got["flag_nondefault"], got["recipe_nondefault"]
        check(flag["csv"] == rec["csv"] and same_estimate(flag["est"], rec["est"]),
              f"3 STK_BN's CSV ({len(rec['csv'])} bytes) and estimate equal the flags' (--stack-reject-factor 10 "
              f"--stack-min-members 3 --min-overlap-hours 2 --allow-member-change)")
        fb, rb = flag["side"]["base_stack"], rec["side"]["base_stack"]
        diff = block_difference(fb, rb, ignore=())
        check(not diff and set(rb) - set(fb) == RECIPE_KEYS,
              f"3 STK_BN's base_stack block equals the flag run's but for {diff or 'nothing'}")
        want = {"reject_factor": 10.0, "min_members": 3, "min_overlap_hours": 2.0, "window_members_constant": False}
        for label, block in (("STK_BN", rb), ("the flag run", fb)):
            seen = {k: block.get(k) for k in want}
            check(seen == want, f"3 {label}'s base_stack block records the recipe's own values: {seen}")


# --- the time part: build_stack.py --recipe -----------------------------------------------------------------

TIME_YAML = """\
name: SYNTH
instrument: lemi423
sample_rate: 1000
data_root: {root}
workspace: {work}
defaults:
  channels: [hx, hy]
sites:
  A1: {{latitude: -31.1, longitude: 139.0}}
  A2: {{latitude: -31.2, longitude: 139.0}}
  A3: {{latitude: -31.3, longitude: 139.0}}
  P2: {{latitude: -31.4, longitude: 139.0}}
"""

TIME_STACKS = """\
STK_T:
  field: H
  use: remote
  method: time_mean
  sample_rate: 1000.0
  members: [A1, A2, A3]
  start: 2023-09-19 20:00
  end: {end}

STK_T2:
  field: H
  use: remote
  method: time_mean
  sample_rate: 1000.0
  members: [A1, A2, P2]
  start: 2023-09-19 20:00
  end: 2023-09-19 20:40

STK_T3:
  field: H
  use: remote
  method: time_mean
  sample_rate: 1000.0
  members: [A1, P2]
  start: 2023-09-19 20:00
  end: 2023-09-19 20:40

STK_LEG:
  field: H
  use: remote
  method: time_mean
  sample_rate: 1000.0
  members: [A1, A2, A3]
  start: 2023-09-19 20:00
  end: 2023-09-19 20:40

STK_TC:
  field: H
  use: remote
  method: time_coherence
  sample_rate: 1000.0
  members: [A1, A2, A3]
  start: 2023-09-19 20:00
  end: 2023-09-19 20:20

STK_BAND:
  field: H
  use: reference
  sample_rate: 1000.0
"""
LEGACY_COMMENT = ("synthetic remote: mean of raw hx/hy counts from A1, A2, A3; uncalibrated: the members carry no "
                  "filter chain (the remote-reference estimate is invariant to the remote's calibration, its errors "
                  "are not: upstream issue 111)")


def build_run(yaml_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run build_stack.py on the time survey."""
    return subprocess.run([sys.executable, str(BUILD), str(yaml_path), *args], capture_output=True, text=True,
                          cwd=REPO)


def load_script(path: Path):
    """Import a script as a module, its main() not run."""
    spec = importlib.util.spec_from_file_location(path.stem + "_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def span_part(module) -> None:
    """Criterion 5's edge test of built_span_short on archives written here."""
    lo = vu.T0.tz_localize("UTC")
    hi = lo + pd.Timedelta(seconds=300)
    cases = {"start 61 s late": (61, 300), "start 59 s late": (59, 300), "end 61 s early": (0, 239),
             "end 59 s early": (0, 241)}
    got = {}
    for label, (a, b) in cases.items():
        ws = SCRATCH / "span" / label.replace(" ", "_")
        shutil.rmtree(ws, ignore_errors=True)
        n = (b - a) * int(vu.FS)
        zeros = np.zeros(n, dtype="int32")
        path = vu.write_archive(ws, "STK_S", [(vu.T0 + pd.Timedelta(seconds=a), {"hx": zeros, "hy": zeros})])
        got[label] = module.built_span_short(path, "STK_S", int(lo.value), int(hi.value))
    check(got["start 61 s late"] is not None and got["end 61 s early"] is not None
          and got["start 59 s late"] is None and got["end 59 s early"] is None,
          "5 built_span_short over a 300 s window: " + "; ".join(f"{k}: {v if v is None else 'short'}"
                                                                for k, v in got.items()))
    print(f"   e.g. {got['start 61 s late']}")


def time_part() -> None:
    """Criterion 5."""
    root = SCRATCH / "time"
    shutil.rmtree(root, ignore_errors=True)
    (root / "raw").mkdir(parents=True)
    ws = root / "work"
    yaml_path = root / "survey.yaml"
    yaml_path.write_text(TIME_YAML.format(root=(root / "raw").as_posix(), work=ws.as_posix()), encoding="utf-8")
    stacks_file = root / stacks.STACKS_FILE
    stacks_file.write_text(TIME_STACKS.format(end="2023-09-19 20:40"), encoding="utf-8")
    data = vu.synthetic_members("mains")
    coils = {m: {c: data[m][c].data for c in ("hx", "hy")} for m in ("A1", "A2", "A3", "C")}
    for m in ("A1", "A2", "A3"):
        vu.write_archive(ws, m, [(vu.T0, coils[m])])
    split = 1_200_000  # P2's first run ends 20 min in; its second starts 10 s later
    vu.write_archive(ws, "P2", [(vu.T0, {c: v[:split] for c, v in coils["C"].items()}),
                                (vu.T0 + pd.Timedelta(seconds=1210), {c: v[split + 10_000:]
                                                                     for c, v in coils["C"].items()})])
    survey = Survey.from_yaml(yaml_path)
    mth5_dir = ws / "mth5"
    target = mth5_dir / "STK_T.h5"
    recipe = stacks.load_recipe(survey, "STK_T")
    h1 = stacks.recipe_hash(recipe)
    module = load_script(BUILD)

    # refusals, none of which may write
    for label, args in (("positionals with --recipe", ("STK_X", "--recipe", "STK_T")),
                        ("--weighting with --recipe", ("--recipe", "STK_T", "--weighting", "coherence")),
                        ("a band recipe", ("--recipe", "STK_BAND")),
                        ("an unknown recipe", ("--recipe", "STK_NONE")),
                        ("--overwrite without --recipe", ("STK_X", "2023-09-19 20:00", "2023-09-19 20:40", "A1",
                                                          "A2", "--overwrite"))):
        res = build_run(yaml_path, *args)
        check(res.returncode == 2, f"5 refused, exit {res.returncode}: {label}: {last_line(res)}")
    # a coherence window under three chunks is refused when the recipe is read, before a build folder is made
    listing, stamp = sorted(p.name for p in mth5_dir.iterdir()), mth5_dir.stat().st_mtime_ns
    res = build_run(yaml_path, "--recipe", "STK_TC")
    same = (sorted(p.name for p in mth5_dir.iterdir()) == listing, mth5_dir.stat().st_mtime_ns == stamp)
    check(res.returncode == 2 and all(n in res.stderr for n in ("STK_TC", "20 min", "30 min")) and all(same),
          f"5 refused, exit {res.returncode}, naming STK_TC, its 20 min and the 30 min minimum, {mth5_dir.name} "
          f"listing unchanged {same[0]}, time unchanged {same[1]}: a time_coherence recipe of 20 min: "
          f"{last_line(res)}")
    res = build_run(yaml_path, "--recipe", "STK_T", "--check")
    check(res.returncode == 0 and "gamma2 with the mean of the other members" in res.stdout,
          f"5 --check with a recipe prints the coherence table (exit {res.returncode})")
    check(sorted(p.name for p in mth5_dir.iterdir()) == ["A1.h5", "A2.h5", "A3.h5", "P2.h5"],
          f"5 the refusals and the check wrote nothing: {sorted(p.name for p in mth5_dir.iterdir())}")

    # the build, and the legacy build of the same members and window
    res = build_run(yaml_path, "--recipe", "STK_T")
    if not check(res.returncode == 0 and target.exists(), f"5 --recipe STK_T builds (exit {res.returncode})"):
        print(res.stdout[-2000:], res.stderr[-3000:])
        return
    res = build_run(yaml_path, "STK_LEG", "2023-09-19 20:00", "2023-09-19 20:40", "A1", "A2", "A3")
    check(res.returncode == 0, f"5 the legacy positional build exits {res.returncode}")
    legacy = mth5_dir / "STK_LEG.h5"
    before = (legacy.stat().st_mtime_ns, sha256(legacy))
    res = build_run(yaml_path, "--recipe", "STK_LEG", "--overwrite")
    check(res.returncode == 2 and "not built from a recipe" in res.stderr
          and (legacy.stat().st_mtime_ns, sha256(legacy)) == before,
          f"5 --recipe STK_LEG --overwrite over the legacy build (no recorded recipe) exits {res.returncode}, "
          f"STK_LEG.h5 unchanged {(legacy.stat().st_mtime_ns, sha256(legacy)) == before}: {last_line(res)}")
    other = root / "other"
    other.mkdir()
    (other / "survey.yaml").write_text(TIME_YAML.replace("name: SYNTH", "name: OTHER").format(
        root=(root / "raw").as_posix(), work=ws.as_posix()), encoding="utf-8")
    shutil.copyfile(stacks_file, other / stacks.STACKS_FILE)
    res = build_run(other / "survey.yaml", "--recipe", "STK_T", "--check")
    check(res.returncode == 2 and "Traceback" not in res.stderr and res.stderr.strip().startswith("ERROR"),
          f"5 --check through a survey.yaml named OTHER (archives under SYNTH) exits {res.returncode} with one "
          f"ERROR line: {last_line(res)}")
    new, old = vu.read_back(target, "STK_T"), vu.read_back(mth5_dir / "STK_LEG.h5", "STK_LEG")
    check(all(new[c].tobytes() == old[c].tobytes() for c in ("hx", "hy")) and new["hx"].size == 2_400_000,
          f"5 STK_T's hx and hy ({new['hx'].size} samples) are identical to the legacy build's")
    check(old["station_comment"] == LEGACY_COMMENT and old["run_comment"] in ("", "None"),
          "5 the legacy build's station comment is the frozen default and its run comment empty")
    check(f"; recipe=STK_T recipe_hash={h1}" in new["station_comment"],
          f"5 STK_T's station comment names the recipe and hash {h1}")
    rec = recorded_provenance(target, survey.name, "STK_T") or {}
    want = {s: archive_identity(processing_archive(survey, s)) for s in ("A1", "A2", "A3")}
    check(rec.get("recipe_hash") == h1 and rec.get("recipe_text") == stacks.canonical_text(recipe)
          and rec.get("members") == ["A1", "A2", "A3"] and rec.get("sources") == want,
          f"5 recorded provenance: hash {rec.get('recipe_hash')}, members {rec.get('members')}, sources equal to the "
          f"processing archives' identities: {rec.get('sources') == want}")

    # reuse, beside a folder a stopped build left: the summary names it and the folder stays
    leftover = mth5_dir / ".build_99999"  # never a build's own folder: Windows process ids are multiples of 4
    leftover.mkdir()
    part = b"part of a stopped build"
    (leftover / "STK_T.h5").write_bytes(part)
    before = (target.stat().st_mtime_ns, sha256(target))
    res = build_run(yaml_path, "--recipe", "STK_T")
    check(res.returncode == 0 and "reused" in res.stdout and (target.stat().st_mtime_ns, sha256(target)) == before,
          f"5 a second run reuses STK_T.h5, its bytes and time unchanged (exit {res.returncode})")
    named = [ln for ln in res.stdout.splitlines() if ln.startswith("leftover build folders")]
    kept = (leftover / "STK_T.h5").exists() and (leftover / "STK_T.h5").read_bytes() == part
    check(len(named) == 1 and ".build_99999" in named[0] and "remove them by hand" in named[0] and kept,
          f"5 the reuse run names .build_99999 ({named[0] if named else 'no leftover line'}) and leaves it and its "
          f"file in place: {kept}")
    argv = stacks.build_argv(sys.executable, BUILD, yaml_path, "STK_T", overwrite=True)
    res = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
    check(res.returncode == 0 and "reused" in res.stdout and (target.stat().st_mtime_ns, sha256(target)) == before,
          f"5 stacks.build_argv's command line ({' '.join(argv[3:])}) reuses it too, --overwrite and all (exit "
          f"{res.returncode})")
    shutil.rmtree(leftover)  # the failed rebuild below counts the build folders left

    # a member archive changed since the build
    a2 = mth5_dir / "A2.h5"
    st = a2.stat()
    os.utime(a2, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    res = build_run(yaml_path, "--recipe", "STK_T")
    check(res.returncode == 2 and "A2" in res.stderr and (target.stat().st_mtime_ns, sha256(target)) == before,
          f"5 after A2's archive time moved, a run without --overwrite exits {res.returncode} naming A2, the "
          f"archive unchanged: {last_line(res)}")
    res = build_run(yaml_path, "--recipe", "STK_T", "--overwrite")
    rec = recorded_provenance(target, survey.name, "STK_T") or {}
    check(res.returncode == 0 and (rec.get("sources") or {}).get("A2") == archive_identity(a2)
          and (rec.get("sources") or {}).get("A2") != want["A2"],
          f"5 with --overwrite the rebuild records A2's new identity (exit {res.returncode})")

    # a changed recipe
    stacks_file.write_text(TIME_STACKS.format(end="2023-09-19 20:30"), encoding="utf-8")
    h2 = stacks.recipe_hash(stacks.load_recipe(survey, "STK_T"))
    res = build_run(yaml_path, "--recipe", "STK_T")
    check(res.returncode == 2 and "recipe hash" in res.stderr,
          f"5 the recipe's end moved to 20:30 (hash {h1} -> {h2}): without --overwrite exit {res.returncode}: "
          f"{last_line(res)}")
    res = build_run(yaml_path, "--recipe", "STK_T", "--overwrite")
    rec = recorded_provenance(target, survey.name, "STK_T") or {}
    check(res.returncode == 0 and rec.get("recipe_hash") == h2 and h2 != h1,
          f"5 with --overwrite the archive records the new hash {rec.get('recipe_hash')} (exit {res.returncode})")

    # a member left out by its single run, and too few members
    res = build_run(yaml_path, "--recipe", "STK_T2")
    rec = recorded_provenance(mth5_dir / "STK_T2.h5", survey.name, "STK_T2") or {}
    p2 = [ln for ln in res.stdout.splitlines() if ln.startswith("left_out: P2")]
    check(res.returncode == 0 and p2 and "cover" in p2[0] and rec.get("members") == ["A1", "A2"],
          f"5 STK_T2 leaves P2 out ({p2[0] if p2 else 'no left_out line'}) and builds from {rec.get('members')} "
          f"(exit {res.returncode})")
    res = build_run(yaml_path, "--recipe", "STK_T3")
    check(res.returncode == 2 and "P2" in res.stderr and "cover" in res.stderr
          and not (mth5_dir / "STK_T3.h5").exists(),
          f"5 STK_T3 (A1 alone left) exits {res.returncode} naming P2's reason: {last_line(res)}")

    # a rebuild that fails leaves the old archive and no build folder
    before = sha256(target)
    vu.write_archive(ws, "A3", [(vu.T0 + pd.Timedelta(microseconds=500), coils["A3"])])
    res = build_run(yaml_path, "--recipe", "STK_T", "--overwrite")
    leftovers = sorted(p.name for p in mth5_dir.glob(".build_*"))
    check(res.returncode == 2 and "align" in res.stderr and sha256(target) == before and not leftovers,
          f"5 a rebuild failing on A3 half a sample off the grid exits {res.returncode}, STK_T.h5 "
          f"unchanged, build folders left: {leftovers or 'none'}: {last_line(res)}")
    span_part(module)


def suites() -> None:
    """Criterion 6: the existing suites, each in its own process; campaign_unit is reported not run without its plan."""
    for name in SUITES:
        if name == "campaign_unit.py" and not CAMPAIGN_PLAN.exists():
            not_run.append(f"6 tests/{name}: {CAMPAIGN_PLAN} is absent (gitignored; workbench issue 29)")
            print(f"NOT RUN {not_run[-1]}")
            continue
        tic = time.time()
        res = subprocess.run([sys.executable, "-u", str(REPO / "tests" / name)], capture_output=True, text=True,
                             cwd=REPO)
        tail = [ln for ln in res.stdout.strip().splitlines() if ln.strip()][-1:] or [""]
        check(res.returncode == 0, f"6 tests/{name} exits {res.returncode} in {time.time() - tic:.0f} s: "
                                   f"{tail[0][:120]}")
        if res.returncode != 0:
            print(res.stdout[-3000:], res.stderr[-3000:])


def main() -> int:
    """Run every criterion; return 1 on any failure."""
    tic = time.time()
    band_part()
    time_part()
    if "--quick" not in sys.argv[1:]:
        suites()
    else:
        print("criterion 6 not run (--quick)")
    print(f"\n{len(failures)} failure(s) in {time.time() - tic:.0f} s")
    for msg in failures:
        print("  " + msg)
    if failures:
        return 1
    if not_run:
        print("NOT COMPLETE: " + "; ".join(not_run))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
