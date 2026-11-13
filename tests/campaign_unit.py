# -*- coding: utf-8 -*-
"""
Unit test for scripts/campaign.py

Checks the plan parser, the overlap rule, the stacks, resume, the dry-run
counts, the runner, the filter check, product parsing, the masks
signature, a MANTLE stage 3 config (its memory class, the ledger's
engine and the score of its shorter product, its window clip and its
expected peak by hours), the plan's per-site remotes, modes and windows,
the deferred configs with --configs, the plan's min_band_windows and its
remote_only sites. Everything runs on a synthetic survey in a
temporary workspace,
without an archive or aurora: five sites on a line with designed record
spans, A 0-48 h, B 2-50 h, C 4-46 h (group G1) and D 40-90 h, E 44-94 h
(group G2), so A/B/C overlap each other by 42-46 h and D/E by 46 h while no
G1-G2 pair reaches 12 h or half of either record. The "raw archives" are
empty files, of which the campaign reads the mtimes. The runner tests start
real child processes: python one-liners that copy a synthetic EDI and print
`wrote <path>`, and a stand-in scripts/process_rr.py (`FAKE_PROCESS_RR`)
that the campaign's own command lines run.

Usage:
    python tests/campaign_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) the real plan (surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml)
    does not load as 23 sites in 4 groups A, B, C10_C11, C in that order, C21
    excluded with a reason naming C07 and C21new, nine stage 3 configs; or a
    plan with a site in two groups, an excluded site in a group, a config
    carrying --tag, or an exclusion without a reason loads at all;

(2) the overlap rule is wrong at its edges (both floors hold,
    min_fraction of the local record and min_hours): for a 48 h
    local, 24 h of overlap (exactly 50 %, over 12 h) must qualify, 12 h
    (exactly the floor but 25 %) and 11.9 h (25 %) must not; for a 10 h
    local, 6 h (60 %, under 12 h) must not; for a 24 h local, 12 h (exactly
    50 % and exactly 12 h) must; no overlap never does; a site is never its
    own remote. The two floors together are tested in
    tests/campaign_overlap_gate_unit.py (workbench 187).

(3) the stacks are wrong: G1's sites stack the other two members (the local
    never in its own stack); a site alone in its group stacks its eligible
    remotes of the other group (F 0-48 h takes G1's A, B, C, span 42 h,
    marked borrowed from G1); D, with one eligible remote, gets none;

(4) resume is wrong: a ledger row marked done with the current inputs and an
    existing EDI is not skipped (no child may start), or it still counts as
    done after the site's filters.yaml entry changed, or when provisional
    (--allow-raw) and the runner runs without --allow-raw;

(5) the dry run does not count, for the synthetic plan with 2 configs:
    stage 0 5 variants; stage 1 8 rr (A, B, C two remotes each, D and E one);
    stage 2 6 stack builds and 6 rr (G1 only); stage 3 10 rr; hours
    (5 x 8 + 6 x 1 + 24 x 8) / 2 slots / 60 = 1.983; or it writes anything
    but <campaign>/refused_remotes.csv (and the folders holding it), which
    the dry run writes at plan time;

(6) the runner, on three fake rr jobs of ~2 s with --parallel 2: ever runs
    three at once or never two, does not record every job done with its EDI
    moved into <campaign>/tf/ (and gone from <workspace>/tf), a peak RSS > 0
    and the input signature; a job depending on a failed one is not skipped,
    in the same block or (a resume) when the failure is only in the ledger;
    --max-runs 1 starts more than one; a leftover "running" row whose runner
    is dead does not get its live orphan child killed and the row marked
    interrupted;

(7) the filter check is wrong against the real producer: comments built the
    way ingest builds them (mt_workbench.noise.apply_filters_arrays' own provenance
    lines joined by "; then ") for C04's declared list (mains then notch) and
    C22's (notch with extra lines) must match, bare, behind build_variant's
    "filters hash <h>; " prefix, and behind the prefix and the freshness
    record that follows it ("source: ...; calibration_sha256: ...; donor:
    ...", workbench issue 20); a changed q, a swapped order, a missing
    filter, a comment with no filters, a notch on the wrong channels and a
    recorded hash that is not filters.yaml's must not;

(8) parse_products does not take the EDI path from the `wrote <path>.edi`
    loguru line (and the sidecar and figure from theirs) of a process_rr.py
    log, or reads one out of a line that only mentions an .edi. The lines are
    the ones loguru really writes into the redirected log, ANSI colour codes
    and all: a captured path ending in the ANSI reset code (ESC[0m) does not
    match ".edi" under a naive suffix check;

(9) the masks signature is wrong: with the plan's runner.masks on, an rr
    job A rr B's inputs do not name both A's and B's masks.yaml hash
    (";A:m<8 hex>" and ";B:m<8 hex>"), or do not change when a mask of
    scope both is added to B alone (the remote: process_rr applies it too)
    or then to A; a job against a stack STK_Au names a masks hash for the
    stack; or its command carries --no-masks. The scope: a mask of scope
    local (written without the key) added to B alone changes A rr B's
    inputs, or leaves B rr A's unchanged; a config [--mask-scope union]
    does not name that mask in A rr B's inputs; or a scope key set on a
    mask the run applies either way (A's own, from local to both) changes
    A rr B's inputs. With runner.masks off: any ":m" hash in the inputs,
    or a command without --no-masks; a config declared as [--masks] whose
    command does not put --masks after the runner's --no-masks, or whose
    inputs name no masks hash; with runner.masks on, a config [--no-masks]
    whose inputs name one; a stage 3 [--masks] job built for A rr B while
    masks.yaml names neither, or not built once B holds a mask of scope
    both; built while B holds only a mask of scope local, or a
    [--masks, --mask-scope union] job not built then;

(10) a MANTLE config is handled wrongly: with runner.masks on, a config
     `mantle: [--engine, mantle]` does not give `rr_masks_on` False,
     `config_engine` "mantle" ("aurora" for the default and a [--taper]
     config), a command carrying exactly one --no-masks before --engine
     mantle, and inputs without any ":m" hash; with runner.masks off its
     command does not carry exactly one --no-masks; stage 3 on A (best
     remote B, masks.yaml empty) does not build the mantle job beside the
     other configs; the dry run over the synthetic plan with that config does
     not list its stage 3 jobs as "[--engine mantle]" and count them; or
     `move_products` on a run whose sidecar names a report JSON and a
     fine-grid EDI (synthetic files in <workspace>/tf named for the job)
     does not move those two into <campaign>/tf/ beside the EDI, sidecar and
     figure, returning their new paths under `mantle_report` and
     `mantle_fine_edi`;

(11) a MANTLE config's runner figures are wrong: a plan whose
     `expected_peak_gb` names neither a kind nor a config (`mantel`) loads;
     with `mantle: 65` in `expected_peak_gb`, 40 GB available (psutil
     stubbed) and an empty ledger, the gate does not let an aurora stage 3
     job start and hold a mantle job back needing 65.0 GB; a running mantle
     job at 5 GB does not hold back 60.0 GB; with finished peaks in the
     ledger (rr 20 GB, mantle 60 GB), the mantle class does not expect
     60 GB or the rr job's need includes the mantle peak; the dry run of
     stage 3 with `minutes_per_job: {rr: 8, mantle: 12}` over 5 sites and 2
     slots does not come to (5 x 12 + 5 x 8) / 2 / 60 h;

(12) the runner, on stage 1 and stage 3 of site A through a stand-in
     process_rr.py (copies a prepared EDI into <workspace>/tf, writes a
     sidecar naming `engine` for --engine mantle, prints `wrote` lines),
     does not record engine "mantle" for the mantle row and "aurora" for the
     others, or the mantle child does not receive `--mantle-max-hours 72`
     and `--no-masks`; the mantle product (the default's curve up to
     1000 s, which is where it stops) is not scored over its own periods:
     its score must equal mt_workbench.quality's score of the default's product
     over 0.005-1000 s, its `period_max` 1000 s and its `n_periods` the
     periods up to 1000 s, while the default's score over 0.005-5000 s,
     with a scattered tail above 1000 s, is lower; summary.md does not list
     the mantle config as "(to 1000 s)"; or a second pass starts a child;

(13) the per-site keys are wrong: a plan with `remotes: {A: A}`, `remotes:
     {A: Z}` (not a site), `modes: {B: [zz]}`, a window whose end precedes
     its start, or `merge: true` over two mode windows loads; with
     `remotes: {A: C}` while stage 1 picks B (C's products carry a longer
     scattered tail), stage 3 of A does not run on C, its rows do not carry
     the note "remote override (the campaign's pick: B)", or
     best_remote.json does not keep B; a fresh dry run (no stage 1 product)
     does not list A's stage 3 on C with one window run and one merge;
     `modes: {B: [xy]}` does not make every B score equal its xy score
     (its yx row is scattered, so the overall differs by > 0.1) or mark B
     "xy-only" in summary.md; `windows: {A: {yx: [10 h, 14 h], merge:
     true}}` does not add a default run with the window's start and end as
     process_rr.py's positional arguments (tag syn-default-yxwin), then a
     merge (kind merge, tag syn-default-merged) whose sidecar names the
     stage 1 A rr C product as the xy source and the window product as the
     yx source; the merged EDI's xy row is not the full-record product's or
     its yx row not the window product's at a period both hold; the merged
     product does not outscore the full-record default, or summary.md does
     not show its score as A's with "the default is the merged product";
     or a second pass starts a child or rebuilds the merge;

(14) the masks signature and stage 3 check miss a mask's `channels` or
     scope remote: A's all-band entry without `channels` does not hash to
     the digest computed here from its six keys without scope (sha1 of the
     sorted JSON, as before the key existed); the same entry with
     `channels: [ex]` hashes the same; a both-scoped `channels: [ex]` entry
     of B changes A rr B's inputs (the remote takes H alone) or leaves B rr
     A's unchanged; a remote-scoped entry of B leaves A rr B's inputs
     unchanged or changes B rr A's; a remote-scoped entry of A changes A rr
     B's inputs; a stage 3 [--masks] job for A rr B is built while A holds
     only a remote-scoped entry and B only a both-scoped `channels: [ey]`
     entry, or not built once B holds a remote-scoped entry;

(15) a MANTLE row's window and memory are wrong: a config [--engine mantle,
     --mantle-max-hours 24] does not end its command with exactly one
     `--mantle-window clip` before --tag; a config naming `--mantle-window
     refuse` does not keep its own and gain none; an aurora config gains
     one; A rr B (46 h overlap) under the 24 h cap does not carry the
     expected clip note "expected window clip (cap): 46.0 h overlap over the
     24 h cap"; with runner rr 35 GB and mantle_gb_per_hour 1.25 and no
     finished row, the 24 h row does not expect the flat 35.0 GB (24 x 1.25
     = 30 is smaller) and a [--mantle-max-hours 100] row not 57.5 GB (46 h x
     1.25); with finished peaks aurora 20 GB and that config 70 GB, the
     config's row does not expect 70 GB, or the aurora percentile
     (`finished_peak_mb(None)`) takes in the MANTLE peak (it must stay
     20 GB); with a 64 GB machine and min_available_gb 10 (psutil stubbed),
     the 57.5 GB row is not refused by `over_machine` naming both figures,
     the 24 h row (35 GB) is, run_block starts a child for the 57.5 GB
     row, or its ledger row is not "skipped" with a note naming "expected
     peak 57.5 GB" and "the machine has 64.0 GB"; the dry run of stage 3
     does not print "MANTLE 24.0 h (the 24 h cap of 46.0 h), expected peak
     35.0 GB" for A's 24 h row, "MANTLE 46.0 h, expected peak 57.5 GB" and
     "would be SKIPPED" for its 100 h row;

(16) the resume of MANTLE rows is wrong, through the stand-in process_rr.py:
     the mantle child does not receive `--mantle-window clip`, its ledger
     note after the run is not "window clipped (cap): 46.0 h requested,
     24.0 h used" (from the sidecar), a done MANTLE row whose `cmd` has no
     `--mantle-window` (as rows done before the flag was added) is re-run
     on a resume, or a failed one is not (exactly one child starts);

(17) the deferred configs are wrong: a plan whose `runner.deferred_configs`
     names a config it does not have loads, a config named `mantle_full`
     does not load or one named `full_` (whose tag process_rr.py would
     strip) does; with `deferred_configs:
     [mantle_full]`, stage 3 of A builds the mantle_full job without
     --configs, or leaves out the other config or the `windows:` run;
     `configs=["mantle_full"]` does not build exactly the mantle_full job
     (no window run, no merge); `configs=["hamming"]` builds another;
     `campaign.py --configs nope` does not exit 2; and on the campaign of
     (16), finished, `campaign.py <survey> <plan> --stage 3 --sites A
     --configs mantle_full` does not run exactly the one mantle_full child,
     leaving every earlier row (stage 1 and stage 3) as it was, with the
     stage 3 remote from best_remote.json;

(18) the plan's `min_band_windows` is wrong: a plan giving -1, 2.5, true or
     "2" loads, or one giving 0 does not; with `min_band_windows: 2` a stage
     1, a stage 2 (against a stack) and a stage 3 aurora rr job and the
     `windows:` run do not carry `--min-band-windows 2` exactly once,
     after the runner's --no-masks and before the config's flags and
     --tag, or the MANTLE job carries it; a config [--min-band-windows 5]
     does not put its own flag after the plan's (the later wins) or names
     the plan's floor in its inputs; an aurora job's inputs do not end
     ";min_band_windows 2", or do not change at 3 while the MANTLE job's
     stay the same; a row done under 2 is still done under 3, or not done
     under 2 again; a plan without the key adds the flag or names a floor
     in the inputs; the dry run does not list the stage 1 jobs as
     "[--min-band-windows 2]" and the stage 3 floor5 job as
     "[--min-band-windows 2 --min-band-windows 5]", or `campaign.py
     --dry-run` does not print "min_band_windows 2 on every aurora rr run"
     on the plan's line; summary.md does not state the floor. Mutations
     that trip it: the flag given to a MANTLE config, the floor left out of
     the inputs, the plan's flag put after the config's.

(19) the plan's `remote_only` is wrong: a plan whose remote_only site is
     also a plan site, is listed twice, or (with the key) holds sites A and
     AR (their stacks would share STK_AR<suffix>) loads; with
     `remote_only: [O]` (a site O in survey.yaml spanning 0-94 h, in no
     group) and `remotes: {A: O}`: O is in no job as the local (stages 1-3);
     stage 0 does not hold one variant job for O (group "remote_only");
     stage 1 does not give each of A-E one job against O beside its own
     remotes; stage 2 does not build, per weighting, STK_<site><s> of the
     group's members and STK_<site>R<s> of the same members and O (G1's
     sites; D and E, whose group has no stack, get neither), with O's name
     at the end of the R build's member list only; A's stage 3 is not on O;
     the dry run does not count stage 0 6 variants, stage 1 13 rr, stage 2
     12 stack builds and 12 rr, stage 3 5 rr, or writes any new file
     (refused_remotes.csv is already there: stage 1 jobs were built).
     Mutations that trip it (run by hand through monkeypatching): the
     remote-only sites left out of `eligible_remotes`, the R stacks not
     built, stage 0 without them.

(20) the stack members are not chosen by their runs: with A 0-48 h and the runs B (2-40, 41-50),
     C (4-46), G (0-9.6: 20 % of A's record), H (0-30, 31-48: 62.5 %),
     I (0-28, 29-48: 58 %), A's stack holds G or H, or not B and C; its
     floor is not 70 %; its span from the runs is not 36 h (4-40) or its
     survey-span figure not 42 h; with B and C in `stages.stacks.
     exclude_members` A's members are not H and I at the 50 % floor, or
     its build's note does not say the floor was lowered; with H excluded
     as well no stack is planned; of ten candidates covering the
     whole record the members are not the 8 nearest; a plan whose
     exclude_members names a site it does not have loads; through the
     Campaign (runs injected), A's build commands do not list B C (and
     B C O for the R stack, O covering 100 %) or their notes do not read
     "expected span 36.0 h from the runs (survey spans 42.0 h)"; a
     remote-only site covering under the floor gives an R stack; or
     `split_done` counts a done rr row on STK_Au as done while the
     stack's build is to run again (its members changed), or as not done
     when the build is done too. Mutations that trip it (run by hand):
     coverage from the survey spans instead of the runs, no coverage
     floor, exclude_members ignored, `split_done` without the dependency
     rule.

(21) the stacks are not planned per piece (a member with a gap costs the
     gap, not the stack): with A
     0-48 h, B in two runs (0-36, 37-48: its best run covers 75 %) and C
     (4-46), A's stack does not span 41 h in two pieces (4-36 and 37-46)
     from the runs, its note does not read "expected span 41.0 h in 2
     pieces from the runs", its build command does not end with
     "--min-piece-h 6", or its inputs do not carry ";pieces 2 (41.0 h)";
     with item 20's runs (one piece of 36 h, 4-40, and one of 5 h left
     out) the inputs carry a piece marker, or the note does not add "1
     piece(s) under 6 h left out (5.0 h)"; `piece_marker` gives "" for a
     single piece that is not the one-run span; or `run_pieces` does not
     take a site without runs as one run over its span. Mutation that
     trips it (run by hand): `piece_marker` always "".
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import campaign as cp  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mt_workbench.noise import apply_filters_arrays  # noqa: E402

PY = sys.executable
ROOT = Path(tempfile.mkdtemp(prefix="campaign_unit_"))
T0 = pd.Timestamp("2023-09-22T00:00:00Z")
SPANS_H = {"A": (0, 48), "B": (2, 50), "C": (4, 46), "D": (40, 90), "E": (44, 94)}


def iso(h: float) -> str:
    """Return T0 plus h hours as an ISO UTC string."""
    return (T0 + pd.Timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_survey(root: Path, spans=SPANS_H, filters=None) -> Path:
    """Write a survey.yaml (+ filters.yaml) with sites on a line 5 km apart and empty raw archives.

    Args:
        root (Path): Survey folder.
        spans (dict): Site to (start, end) hours after T0.
        filters (dict | None): filters.yaml content; a 50 Hz notch per site
            when None.

    Returns:
        Path: The survey.yaml.
    """
    sites = {}
    for k, (s, (a, b)) in enumerate(spans.items()):
        sites[s] = {"latitude": 31.0 + 0.045 * k, "longitude": -5.5, "start": iso(a), "end": iso(b)}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text(yaml.safe_dump(filters or {s: [{"notch": {"f0": 50.0}}] for s in spans}),
                                       encoding="utf-8")
    (root / "work" / "mth5").mkdir(parents=True, exist_ok=True)
    (root / "work" / "tf").mkdir(parents=True, exist_ok=True)
    for s in spans:
        (root / "work" / "mth5" / f"{s}.h5").write_bytes(b"")
    return root / "survey.yaml"


def make_plan(root: Path, groups=None, configs=None, runner=None, sites=None) -> Path:
    """Write a synthetic campaign plan; the keyword arguments override its groups, configs, runner and sites."""
    groups = groups or {"G1": ["A", "B", "C"], "G2": ["D", "E"]}
    plan = {"name": "syn", "sites": sites or [s for g in groups.values() for s in g],
            "exclude": {"Z": "a copy of A"}, "groups": groups,
            "overlap": {"min_fraction": 0.5, "min_hours": 12},
            "stages": {"variants": {}, "remotes": {}, "stacks": {"weightings": {"u": "none", "w": "coherence"}},
                       "options": {"configs": configs or {"boxcar": ["--taper", "boxcar"], "pd8": ["--per-decade", "8"]}}},
            "runner": runner or {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2,
                                 "peak_factor": 1.2, "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05}}}
    root.mkdir(parents=True, exist_ok=True)
    path = root / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return path


def synthetic_edi(path: Path) -> Path:
    """Write a smooth synthetic EDI (100 ohm m, 45 deg) to `path`."""
    p = np.logspace(-2, 3, 31)
    z = np.zeros((p.size, 2, 2), dtype=complex)
    amp = np.sqrt(100.0 / (0.2 * p))
    z[:, 0, 1] = amp * np.exp(1j * np.radians(45.0))
    z[:, 1, 0] = amp * np.exp(1j * np.radians(-135.0))
    tf = TF()
    tf.station = "SYN"
    tf.period = p
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    tf.write(fn=path, file_type="edi")
    return path


P_FULL = 10.0 ** (np.arange(-20, 37) / 10.0)  # 0.01 to 3981 s, ten per decade, 1000 s on the grid
P_MANTLE = P_FULL[P_FULL <= 1000.0 * (1.0 + 1e-9)]  # where a day's MANTLE cascade stops

FAKE_PROCESS_RR = '''\
"""A stand-in for scripts/process_rr.py: copies a prepared EDI into <workspace>/tf and writes a sidecar.

The EDI is edis/<remote>_<kind>.edi beside this file, else edis/<kind>.edi,
with kind "mantle" for --engine mantle, "window" when a start is given, else
"full".
"""
import argparse, datetime as dt, json, shutil, sys
from pathlib import Path
import yaml

p = argparse.ArgumentParser()
for name in ("survey_yaml", "local", "remote"):
    p.add_argument(name)
p.add_argument("start", nargs="?")
p.add_argument("end", nargs="?")
p.add_argument("--tag")
p.add_argument("--engine", default="aurora")
p.add_argument("--mantle-max-hours", type=float, default=24.0)
p.add_argument("--mantle-window", default=None)
# the plan configs' options that take a value: left undeclared, Python 3.13's
# argparse hands the value (e.g. "hamming" of --taper hamming) to `start`
for name in ("--taper", "--per-decade", "--mask-scope"):
    p.add_argument(name)
args, _ = p.parse_known_args()
for value in (args.start, args.end):
    if value is not None:
        try:
            dt.datetime.fromisoformat(value)
        except ValueError:
            sys.exit(f"stand-in process_rr.py: window bound {value!r} is not a time (an undeclared option's value?)")
cfg = yaml.safe_load(Path(args.survey_yaml).read_text(encoding="utf-8"))
work = Path(cfg["workspace"])
kind = "mantle" if args.engine == "mantle" else "window" if args.start else "full"
edis = Path(__file__).with_name("edis")
src = next(q for q in (edis / f"{args.remote}_{kind}.edi", edis / f"{kind}.edi") if q.exists())
stem = f"{args.local}_rr-{args.remote}_{dt.datetime.now().strftime('%Y%m%d-%H%M')}_{args.tag}"
edi = work / "tf" / f"{stem}.edi"
shutil.copy(src, edi)
side = {"local": args.local, "remote": args.remote, "tag": args.tag, "argv": sys.argv, "edi": edi.name,
        "window": {"start": args.start, "end": args.end}, "quadrant": {"verdict": "physical quadrants"}}
if args.engine == "mantle":
    side.update(engine="mantle", engine_config={"options": {"max_hours": args.mantle_max_hours}})
if args.engine == "mantle" and args.mantle_window == "clip":
    ts = [dt.datetime.fromisoformat(str(cfg["sites"][s][k]).replace("Z", "+00:00"))
          for s in (args.local, args.remote) for k in ("start", "end")]
    hours = (min(ts[1], ts[3]) - max(ts[0], ts[2])).total_seconds() / 3600.0
    side["window_clipped"] = None if hours <= args.mantle_max_hours else {
        "requested_hours": hours, "used_hours": args.mantle_max_hours, "reason": "cap"}
edi.with_suffix(".json").write_text(json.dumps(side), encoding="utf-8")
print(f"wrote {edi}", flush=True)
print(f"wrote {edi.with_suffix('.json')}", flush=True)
'''


def product_edi(path: Path, periods, tail_from: float | None = None, bad_yx: bool = False) -> Path:
    """Write a synthetic product EDI on `periods`: 100 ohm m, xy at 45 deg and yx at -135 deg.

    Both modes carry a dead band at 1-3 s (rho alternating 0.3 dex either
    side), so a score over any window holding it is below 1. The diagonal
    terms are 5 % of the off-diagonal ones, as a real product's are nonzero.

    Args:
        path (Path): EDI to write.
        periods (array): Periods in s.
        tail_from (float | None): Periods above this alternate 0.5 dex either
            side of the curve in both modes, a scattered long-period tail.
        bad_yx (bool): The yx row's phase and rho scattered, as with a
            faulty ey.

    Returns:
        Path: `path`.
    """
    p = np.asarray(periods, dtype=float)
    sign = (-1.0) ** np.arange(p.size)
    dex = np.where((p >= 1.0) & (p <= 3.0), 0.3, 0.0)
    if tail_from is not None:
        dex = np.where(p > tail_from * (1.0 + 1e-9), 0.5, dex)
    amp = np.sqrt(100.0 / (0.2 * p)) * 10.0 ** (0.5 * dex * sign)
    z = np.zeros((p.size, 2, 2), dtype=complex)
    z[:, 0, 1] = amp * np.exp(1j * np.radians(45.0))
    z[:, 1, 0] = amp * np.exp(1j * np.radians(-135.0))
    z[:, 0, 0] = 0.05 * amp * np.exp(1j * np.radians(30.0))
    z[:, 1, 1] = 0.05 * amp * np.exp(1j * np.radians(-150.0))
    if bad_yx:
        z[:, 1, 0] = amp * 10.0 ** (0.6 * sign) * np.exp(1j * np.radians(-135.0 + 150.0 * sign))
    tf = TF()
    tf.station = "SYN"
    tf.period = p
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    path.parent.mkdir(parents=True, exist_ok=True)
    tf.write(fn=path, file_type="edi")
    return path


def fake_scripts(root: Path, bad_yx: bool = False) -> Path:
    """Write the stand-in process_rr.py and its prepared EDIs under `root`.

    full.edi is the whole record with a scattered tail above 1000 s,
    mantle.edi the same curve up to 1000 s, and window.edi a product of a
    few hours (0.01-200 s) whose yx row is sound.

    Args:
        root (Path): Folder of the test.
        bad_yx (bool): Scatter the yx row of full.edi and mantle.edi.

    Returns:
        Path: The folder to point `campaign.SCRIPTS` at.
    """
    folder = root / "fake_scripts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "process_rr.py").write_text(FAKE_PROCESS_RR, encoding="utf-8")
    product_edi(folder / "edis" / "full.edi", P_FULL, tail_from=1000.0, bad_yx=bad_yx)
    product_edi(folder / "edis" / "mantle.edi", P_MANTLE, bad_yx=bad_yx)
    product_edi(folder / "edis" / "window.edi", P_FULL[P_FULL <= 200.0])
    return folder


def quiet(fn, *a, **k):
    """Call fn with stdout captured; return (its result, the captured text)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **k)
    return out, buf.getvalue()


# ---------------------------------------------------------------------- tests


def test_plan_parser() -> None:
    plan = cp.load_plan(REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "campaign_lineC.yaml")
    assert len(plan.sites) == 23 and list(plan.groups) == ["A", "B", "C10_C11", "C"], (plan.sites, list(plan.groups))
    assert "C21" not in plan.sites and "C07" in plan.exclude["C21"] and "C21new" in plan.exclude["C21"], plan.exclude
    assert len(plan.configs) == 9 and plan.configs["r0u0"] == ["--r0", "1.0", "--u0", "2.0"], plan.configs
    root = ROOT / "plans"
    root.mkdir(exist_ok=True)
    five = ["A", "B", "C", "D", "E"]
    bad = {  # label: (plan kwargs, the message the refusal must carry)
        "site in two groups": ({"groups": {"G1": ["A", "B", "C"], "G2": ["C", "D", "E"]}, "sites": five},
                               "C is in groups G1 and G2"),
        "excluded site in a group": ({"groups": {"G1": ["A", "B", "C", "Z"], "G2": ["D", "E"]}, "sites": five},
                                     "group G1: Z is excluded"),
        "config with --tag": ({"configs": {"x": ["--taper", "boxcar", "--tag", "y"]}}, "without --tag/--dry-run"),
    }
    for label, (kw, message) in bad.items():
        path = make_plan(root, **kw)
        try:
            cp.load_plan(path)
        except ValueError as exc:
            assert message in str(exc), (label, str(exc))
            print(f"  refused ({label}): {next(ln.strip() for ln in str(exc).splitlines() if message in ln)}")
        else:
            raise AssertionError(f"a plan with {label} loaded")
    path = make_plan(root)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["exclude"] = {"Z": ""}
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    try:
        cp.load_plan(path)
    except ValueError as exc:
        assert "exclude Z: give the reason" in str(exc), str(exc)
        print(f"  refused (exclusion without a reason): {str(exc).splitlines()[1].strip()}")
    else:
        raise AssertionError("an exclusion without a reason loaded")
    print(f"  lineC: {len(plan.sites)} sites, groups {list(plan.groups)}, C21: {plan.exclude['C21'][:60]}...")


def test_overlap_rule() -> None:
    plan = cp.load_plan(make_plan(ROOT / "rule", groups={"G": ["L", "P", "Q", "R", "S", "N", "M", "T", "U"]}))
    spans = {k: (T0 + pd.Timedelta(hours=a), T0 + pd.Timedelta(hours=b)) for k, (a, b) in {
        "L": (0, 48), "P": (24, 80), "Q": (36, 90), "R": (36.1, 90), "S": (0, 10), "N": (60, 70), "M": (4, 100),
        "T": (0, 24), "U": (12, 40)}.items()}
    # both floors hold (min_fraction 0.5 of the local record and min_hours 12); on one floor
    # alone L rr Q and S rr M would pass
    cases = [("L", "P", True, "24 h = 50 %"), ("L", "Q", False, "12 h floor but 25 %"),
             ("L", "R", False, "11.9 h, 25 %"), ("S", "M", False, "6 h = 60 % of a 10 h local, under 12 h"),
             ("T", "U", True, "12 h = 50 % of a 24 h local: both edges"),
             ("L", "N", False, "no overlap"), ("L", "L", False, "itself")]
    for local, remote, want, why in cases:
        got = cp.is_eligible(plan, spans, local, remote)
        assert got == want, (local, remote, why, cp.overlap_hours(spans[local], spans[remote]))
        print(f"  {local} rr {remote}: {cp.overlap_hours(spans[local], spans[remote]):.1f} h -> "
              f"{'eligible' if got else 'not'} ({why})")


def test_stacks() -> None:
    spans_h = {**SPANS_H, "F": (0, 48)}
    survey_yaml = make_survey(ROOT / "stacks", spans_h)
    plan = cp.load_plan(make_plan(ROOT / "stacks", groups={"G1": ["A", "B", "C"], "G2": ["D", "E"], "G3": ["F"]}))
    spans = cp.site_spans(cp.Survey.from_yaml(survey_yaml), plan.sites)
    # the members are the eligible remotes of every group:
    # F (G3, 0-48 h) is one of A's, B's and C's; G1 still holds most of them
    for s, others in (("A", ["B", "C", "F"]), ("B", ["A", "C", "F"]), ("C", ["A", "B", "F"])):
        sp = cp.stack_plan(plan, spans, s)
        assert sp and sorted(sp["members"]) == others and sp["group"] == "G1", (s, sp)
    sp = cp.stack_plan(plan, spans, "F")
    assert sp and sp["borrowed"] and sp["group"] == "G1" and sorted(sp["members"]) == ["A", "B", "C"], sp
    assert abs(sp["span_h"] - 42.0) < 1e-9, sp["span_h"]
    assert cp.stack_plan(plan, spans, "D") is None, cp.stack_plan(plan, spans, "D")
    print(f"  A <- B C F; F (alone in G3) takes G1's {sp['members']} over {sp['span_h']:.0f} h; D: none")


def test_dry_run_counts() -> None:
    root = ROOT / "dry"
    survey_yaml = make_survey(root)
    plan = cp.load_plan(make_plan(root))
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    out, text = quiet(c.dry_run, [0, 1, 2, 3], plan.sites)
    got = {st: {k: v for k, v in kinds.items() if v} for st, kinds in out["counts"].items()}
    want = {0: {"variant": 5}, 1: {"rr": 8}, 2: {"stack": 6, "rr": 6}, 3: {"rr": 10}}
    assert got == want, (got, text)
    assert abs(out["hours"] - (5 * 8 + 6 * 1 + 24 * 8) / 2 / 60) < 1e-9, out["hours"]
    after = sorted(p.relative_to(root) for p in root.rglob("*"))
    # the dry run writes <campaign>/refused_remotes.csv at plan time, and nothing else
    refused = (c.dir / "refused_remotes.csv").relative_to(root)
    allowed = {refused, *(p for p in refused.parents if str(p) != ".")}
    assert refused in set(after), f"the dry run did not write {refused}"
    assert set(after) - set(before) <= allowed, f"the dry run wrote {set(after) - set(before) - allowed}"
    print(f"  counts {got}; {out['hours']:.3f} h; nothing written but {refused}")


def _fake_job(c, run_id: str, local: str, remote: str, edi_src: Path, seconds: float, trace: Path,
              fail: bool = False, deps=()) -> cp.Job:
    """Build an rr job whose child sleeps, copies an EDI into <workspace>/tf and prints `wrote <path>`.

    The child appends its start and end times to `trace`, and with `fail`
    exits with an error before copying.
    """
    tag = c.plan.tag("default")
    dest = c.survey.workspace / "tf" / f"{local}_rr-{remote}_20260923-2300_{tag}.edi"
    code = (
        "import shutil, sys, time\n"
        "trace, src, dest, secs, fail = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5] == '1'\n"
        "open(trace, 'a').write(f'start {time.time()}\\n')\n"
        "block = bytearray(50_000_000)\n"  # 50 MB so the peak RSS is plainly > 0
        "time.sleep(secs)\n"
        "open(trace, 'a').write(f'end {time.time()}\\n')\n"
        "if fail: raise SystemExit('ValueError: made to fail')\n"
        "shutil.copy(src, dest)\n"
        "print(f'2026-09-23 23:00:00.000 | INFO | mt_workbench.process:process_station:255 - wrote {dest}', flush=True)\n"
    )
    return cp.Job(run_id=run_id, stage=1, kind="rr", group=c.plan.group_of(local), local=local, remote=remote,
                  config="default", tag=tag, deps=list(deps), input_sites=[local, remote],
                  cmd=[PY, "-c", code, str(trace), str(edi_src), str(dest), str(seconds), "1" if fail else "0"])


def _max_concurrency(trace: Path) -> int:
    """Return the largest number of fake jobs running at once, from their trace file."""
    events = []
    for line in trace.read_text().splitlines():
        kind, t = line.split()
        events.append((float(t), 1 if kind == "start" else -1))
    live = peak = 0
    for _, d in sorted(events, key=lambda e: (e[0], e[1])):
        live += d
        peak = max(peak, live)
    return peak


def test_runner_and_resume() -> None:
    root = ROOT / "run"
    survey_yaml = make_survey(root)
    plan = cp.load_plan(make_plan(root))
    edi = synthetic_edi(root / "src.edi")
    c = cp.Campaign(survey_yaml, plan, parallel=2)
    c.api = {"func": "processing_archive", "variant": True, "rr": True, "stack": True, "why": ""}
    trace = root / "trace.txt"
    jobs = [_fake_job(c, f"s1_{a}_rr-{b}", a, b, edi, 2.0, trace) for a, b in (("A", "B"), ("A", "C"), ("B", "A"))]
    t = time.time()
    quiet(c.run_block, "fake stage 1", jobs)
    wall = time.time() - t
    conc = _max_concurrency(trace)
    assert conc == 2, f"{conc} at once"
    for j in jobs:
        row = c.ledger.rows[j.run_id]
        assert row["status"] == "done" and row["exit_code"] == "0", row
        assert Path(row["edi"]).parent == c.dir / "tf" and Path(row["edi"]).exists(), row["edi"]
        assert float(row["peak_rss_mb"]) > 0 and row["inputs"] == c.inputs(j), row
    assert not list((c.survey.workspace / "tf").glob("*.edi")), "products left in <workspace>/tf"
    print(f"  3 jobs of 2 s at --parallel 2: at most {conc} at once, {wall:.1f} s; peak RSS "
          f"{max(float(c.ledger.rows[j.run_id]['peak_rss_mb']) for j in jobs):.0f} MB; EDIs moved to campaign/tf")

    # resume: the done rows are skipped, nothing starts
    c2 = cp.Campaign(survey_yaml, plan, parallel=2)
    c2.api = dict(c.api)
    again = [_fake_job(c2, f"s1_{a}_rr-{b}", a, b, edi, 2.0, trace) for a, b in (("A", "B"), ("A", "C"), ("B", "A"))]
    quiet(c2.run_block, "resume", again)
    assert c2.n_started == 0, f"{c2.n_started} started on resume"
    # a changed filter for A invalidates A's runs (and B rr A's), a provisional row is not done without --allow-raw
    filt = yaml.safe_load((root / "filters.yaml").read_text(encoding="utf-8"))
    filt["A"] = [{"notch": {"f0": 50.0, "q": 40.0}}]
    (root / "filters.yaml").write_text(yaml.safe_dump(filt), encoding="utf-8")
    c2.refresh()
    assert [c2.already_done(j) for j in again] == [False, False, False], [c2.already_done(j) for j in again]
    c2.ledger.rows["s1_B_rr-A"]["inputs"] = c2.inputs(again[2])
    assert c2.already_done(again[2])
    c2.ledger.rows["s1_B_rr-A"]["provisional"] = "process_rr.py read the raw archives"
    assert not c2.already_done(again[2])
    c2.allow_raw = True
    assert c2.already_done(again[2])
    print("  resume: 0 started; A's filter changed -> 3 not done; provisional row done only with --allow-raw")

    # a failed job's dependant is skipped; --max-runs 1 starts one
    c3 = cp.Campaign(survey_yaml, plan, parallel=2, max_runs=1)
    c3.api = dict(c.api)
    bad = _fake_job(c3, "s1_D_rr-E", "D", "E", edi, 0.2, root / "trace3.txt", fail=True)
    dep = _fake_job(c3, "s2_D_rr-STK_Du", "D", "E", edi, 0.2, root / "trace3.txt", deps=["s1_D_rr-E"])
    extra = _fake_job(c3, "s1_E_rr-D", "E", "D", edi, 0.2, root / "trace3.txt")
    quiet(c3.run_block, "max-runs", [bad, dep, extra])
    n_first = c3.n_started
    assert n_first == 1 and c3.ledger.rows["s1_D_rr-E"]["status"] == "failed", c3.ledger.rows["s1_D_rr-E"]
    assert "made to fail" in c3.ledger.rows["s1_D_rr-E"]["error"], c3.ledger.rows["s1_D_rr-E"]["error"]
    c3.max_runs = None
    t = time.time()
    quiet(c3.run_block, "deps", [dep])  # its dependency failed in an earlier block: only the ledger records it
    assert time.time() - t < 30, "run_block waited on a dependency outside the block"
    assert c3.ledger.rows["s2_D_rr-STK_Du"]["status"] == "skipped", c3.ledger.rows["s2_D_rr-STK_Du"]
    quiet(c3.run_block, "deps in block", [_fake_job(c3, "s1_E_rr-D", "E", "D", edi, 0.2, root / "trace3.txt",
                                                    fail=True),
                                          _fake_job(c3, "s2_E_rr-STK_Eu", "E", "D", edi, 0.2, root / "trace3.txt",
                                                    deps=["s1_E_rr-D"])])
    assert c3.ledger.rows["s2_E_rr-STK_Eu"]["status"] == "skipped", c3.ledger.rows["s2_E_rr-STK_Eu"]
    print(f"  --max-runs 1: {n_first} started; failed row error {c3.ledger.rows['s1_D_rr-E']['error']!r}; "
          f"its dependant skipped")

    # an orphan: a "running" row whose runner is dead and whose child still lives
    orphan = subprocess.Popen([PY, "-c", "import time; time.sleep(120)", "process_rr.py", "E", "D"])
    dead = subprocess.Popen([PY, "-c", "pass"])
    dead.wait()
    c3.ledger.upsert({"run_id": "s1_E_rr-D", "stage": 1, "kind": "rr", "local": "E", "remote": "D",
                      "status": "running", "runner_pid": dead.pid, "child_pid": orphan.pid,
                      "started": cp.now().isoformat(timespec="seconds")})
    quiet(c3.cleanup_orphans)
    try:
        orphan.wait(timeout=30)
    except subprocess.TimeoutExpired:
        orphan.kill()
        raise AssertionError("the orphaned child is still alive")
    assert c3.ledger.rows["s1_E_rr-D"]["status"] == "interrupted", c3.ledger.rows["s1_E_rr-D"]
    assert not psutil.pid_exists(orphan.pid) or psutil.Process(orphan.pid).status() == psutil.STATUS_ZOMBIE
    print(f"  orphan child {orphan.pid} of dead runner {dead.pid}: killed, row interrupted")


def _comment(specs, comps=("ex", "ey", "hx", "hy"), fs=1000.0) -> str:
    """Build a run comment as ingest does, from apply_filters_arrays' own provenance lines."""
    rng = np.random.default_rng(0)
    arrays = {c: rng.normal(0.0, 1.0, int(4 * fs)) for c in comps}
    _, lines = apply_filters_arrays(arrays, fs, specs, tag="unit")
    return cp.FILTER_PREFIX + "; then ".join(lines)


def test_filter_check() -> None:
    filt = yaml.safe_load((REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "filters.yaml").read_text(encoding="utf-8"))
    chans = ["ex", "ey", "hx", "hy"]
    for site in ("C04", "C22"):
        declared = filt[site]
        ok, why = cp.recorded_matches(_comment(declared), declared, chans, 1000.0)
        assert ok, (site, why)
        variant = f"{cp.VARIANT_HASH_PREFIX}{cp.filters_hash(declared)}; {_comment(declared)}"
        ok, why = cp.recorded_matches(variant, declared, chans, 1000.0)
        assert ok, (site, "variant", why)
        stamp = "mtime 20261005T044812.520872600Z"
        record = (f"source: {site} size 1 {stamp} sha256_head {'0' * 64}; calibration_sha256: {'a' * 64}; "
                  f"donor: R01 size 2 {stamp} sha256_head {'b' * 64}")
        fresh = f"{cp.VARIANT_HASH_PREFIX}{cp.filters_hash(declared)}; {record}; {_comment(declared)}"
        ok, why = cp.recorded_matches(fresh, declared, chans, 1000.0)
        assert ok, (site, "variant with its freshness record", why)
        print(f"  {site} ({' then '.join(next(iter(s)) for s in declared)}): recorded as declared, "
              f"bare and as a variant (hash {cp.filters_hash(declared)})")
    declared = filt["C04"]
    changed = json.loads(json.dumps(declared))
    changed[1]["notch"]["q"] = 45.0
    cases = {
        "q changed": (_comment(declared), changed),
        "order swapped": (_comment(declared[::-1]), declared),
        "a filter missing": (_comment(declared[:1]), declared),
        "no filters recorded": ("", declared),
        "wrong channels": (_comment([{"notch": {**declared[1]["notch"], "channels": ["ex", "ey"]}}]), declared[1:]),
        "variant hash not filters.yaml's": (f"{cp.VARIANT_HASH_PREFIX}0badc0de; {_comment(declared)}", declared),
    }
    for label, (comment, want) in cases.items():
        ok, why = cp.recorded_matches(comment, want, chans, 1000.0)
        assert not ok, (label, why)
        print(f"  {label}: mismatch ({why[:90]})")


def test_parse_products() -> None:
    esc = "\x1b"
    log = "\n".join([  # the exact shape of scripts/process_rr.py's log (loguru colours it)
        "stem: C18_rr-C19_20260923-2300_lineC-default",
        f"{esc}[1m2026-09-23T22:56:54.847749+0800 | INFO | mt_workbench.process | process_station | line: 255 | "
        f"wrote D:\\W\\tf\\C18_rr-C19_x.edi{esc}[0m",
        f"{esc}[1m2026-09-23T22:56:55.217105+0800 | INFO | __main__ | main | line: 530 | "
        f"wrote D:\\W\\tf\\C18_rr-C19_x_vs_lemimt.png{esc}[0m",
        "comparison figure: D:\\W\\tf\\C18_rr-C19_x_vs_lemimt.png",
        f"{esc}[1m2026-09-23T22:56:55.253730+0800 | INFO | __main__ | main | line: 538 | "
        f"wrote D:\\W\\tf\\C18_rr-C19_x.json{esc}[0m",
        "sidecar: D:\\W\\tf\\C18_rr-C19_x.json",
        f"{esc}[33m2026-09-23T22:56:55.3+0800 | WARNING | __main__ | main | line: 560 | "
        f"C18_rr-C19_x.edi: could not add the facts{esc}[0m",
    ])
    got = cp.parse_products(log)
    want = {"edi": "D:\\W\\tf\\C18_rr-C19_x.edi", "sidecar": "D:\\W\\tf\\C18_rr-C19_x.json",
            "figure": "D:\\W\\tf\\C18_rr-C19_x_vs_lemimt.png"}
    assert got == want, got
    assert cp.parse_products("the EDI C18_rr-C19_x.edi was not written")["edi"] == ""
    # a note after the path (process_rr's merged-rows line of 27 Sep) must not become part of it
    noted = cp.parse_products("wrote D:\\W\\tf\\C19_rr-C22_m.edi (rows merged from 2 runs)")
    assert noted["edi"] == "D:\\W\\tf\\C19_rr-C22_m.edi", noted
    print(f"  {got}")


def test_inputs_masks_both_sites() -> None:
    import re

    root = ROOT / "masks"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2,
              "masks": True}
    c = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root, runner=runner)), parallel=2, create=False)
    job = c.rr_job(1, "A", "B", "default", "s1_A_rr-B")
    stack_job = c.rr_job(2, "A", "STK_Au", "default", "s2_A_rr-STK_Au")
    bare = c.inputs(job)
    assert re.search(r";A:m[0-9a-f]{8}", bare) and re.search(r";B:m[0-9a-f]{8}", bare), bare
    assert "--no-masks" not in job.cmd, job.cmd

    def mask(h0: float, scope: str | None = "both") -> dict:
        """Build a 30 min all-band mask from h0 hours after T0; scope None leaves the key out (scope local)."""
        out = {"start": iso(h0), "end": iso(h0 + 0.5), "bands": "all", "reason": "test", "found_by": "time"}
        return out if scope is None else {**out, "scope": scope}

    (root / "masks.yaml").write_text(yaml.safe_dump({"B": [mask(10)]}), encoding="utf-8")
    remote_masked = c.inputs(job)
    assert remote_masked != bare, "a mask added to the remote did not change the inputs"
    assert remote_masked.split(";A:m")[1][:8] == bare.split(";A:m")[1][:8], (bare, remote_masked)
    (root / "masks.yaml").write_text(yaml.safe_dump({"A": [mask(20)], "B": [mask(10)]}), encoding="utf-8")
    both_masked = c.inputs(job)
    assert both_masked != remote_masked, "a mask added to the local did not change the inputs"
    stack_sig = c.inputs(stack_job)
    assert ";A:m" in stack_sig and "STK_Au:m" not in stack_sig, stack_sig

    # the scope: B's mask of scope local is B's own as the local, and no part of A rr B
    reverse = c.rr_job(1, "B", "A", "default", "s1_B_rr-A")
    reverse_bare = c.inputs(reverse)
    (root / "masks.yaml").write_text(yaml.safe_dump({"B": [mask(10, None)]}), encoding="utf-8")
    assert c.inputs(job) == bare, ("a local-scoped mask of the remote changed the inputs", bare, c.inputs(job))
    assert c.inputs(reverse) != reverse_bare, "a local-scoped mask of the local left the inputs unchanged"
    c.plan.configs["union"] = ["--mask-scope", "union"]
    union_job = c.rr_job(3, "A", "B", "union", "s3_A_rr-B_union")
    assert c.config_mask_scope("union") == "union" and c.config_mask_scope("default") == "role"
    # a config's own flags enter its rows' inputs (";config <flags>", workbench 180),
    # so the union run's inputs are the masks the default run would name plus that marker; the masks part is unchanged
    assert c.inputs(union_job) == remote_masked + ";config --mask-scope union", (c.inputs(union_job), remote_masked)
    (root / "masks.yaml").write_text(yaml.safe_dump({"A": [mask(20, None)], "B": [mask(10, "local")]}),
                                     encoding="utf-8")
    local_scoped = c.inputs(job)
    (root / "masks.yaml").write_text(yaml.safe_dump({"A": [mask(20, "both")], "B": [mask(10, "local")]}),
                                     encoding="utf-8")
    assert c.inputs(job) == local_scoped, "A's scope changed, not its masks, and A rr B's inputs moved"
    print(f"  B's local-scoped mask: A rr B {c.inputs(job)} (as bare), B rr A changed; "
          f"[--mask-scope union] names it: {c.inputs(union_job)}")

    off = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root / "off")), parallel=2, create=False)
    off_job = off.rr_job(1, "A", "B", "default", "s1_A_rr-B")
    assert ":m" not in off.inputs(off_job) and "--no-masks" in off_job.cmd, (off.inputs(off_job), off_job.cmd)
    # a config's own --masks wins over runner.masks off: it comes after the
    # runner's --no-masks on the command line and the inputs name both hashes
    off.plan.configs["masked"] = ["--masks"]
    masked_job = off.rr_job(3, "A", "B", "masked", "s3_A_rr-B_masked")
    assert off.rr_masks_on("masked") and not off.rr_masks_on("default"), off.plan.configs
    assert masked_job.cmd.index("--no-masks") < masked_job.cmd.index("--masks"), masked_job.cmd
    masked_sig = off.inputs(masked_job)
    assert ";A:m" in masked_sig and ";B:m" in masked_sig, masked_sig
    c.plan.configs["unmasked"] = ["--no-masks"]
    unmasked_job = c.rr_job(3, "A", "B", "unmasked", "s3_A_rr-B_unmasked")
    assert not c.rr_masks_on("unmasked") and ":m" not in c.inputs(unmasked_job), c.inputs(unmasked_job)
    assert unmasked_job.cmd.count("--no-masks") == 1 and "--masks" not in unmasked_job.cmd, unmasked_job.cmd
    print(f"  masks on: {bare} -> B masked {remote_masked} -> A masked {both_masked}; stack job {stack_sig}")
    print(f"  runner.masks off + config [--masks]: {masked_job.cmd[-5:]} -> {masked_sig}; "
          f"runner.masks on + config [--no-masks]: no masks hash")

    # stage 3 leaves the masked config out when masks.yaml names neither site
    off.plan.configs = {"masked": ["--masks"], "hamming": ["--taper", "hamming"]}
    off.best_remotes = lambda sites, persist=True, df=None: {s: {"remote": "B"} for s in sites}
    (root / "masks.yaml").write_text("", encoding="utf-8")
    none = [j.config for j in off.stage3_jobs(["A"])]
    (root / "masks.yaml").write_text(yaml.safe_dump({"B": [mask(10)]}), encoding="utf-8")
    some = [j.config for j in off.stage3_jobs(["A"])]
    assert none == ["hamming"] and some == ["masked", "hamming"], (none, some)
    print(f"  stage 3 with no masks.yaml entry for A or B: {none}; with one of scope both for B: {some}")
    # B's only mask of scope local: the masked run would repeat the default, the union run would not
    off.plan.configs = {"masked": ["--masks"], "masked_union": ["--masks", "--mask-scope", "union"],
                        "hamming": ["--taper", "hamming"]}
    (root / "masks.yaml").write_text(yaml.safe_dump({"B": [mask(10, None)]}), encoding="utf-8")
    local_only = [j.config for j in off.stage3_jobs(["A"])]
    assert local_only == ["masked_union", "hamming"], local_only
    print(f"  stage 3 with one mask of scope local for B: {local_only}")


def test_inputs_masks_channels_and_remote_scope() -> None:
    import hashlib

    root = ROOT / "channels"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2, "masks": True}
    c = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root, runner=runner)), parallel=2, create=False)
    job = c.rr_job(1, "A", "B", "default", "s1_A_rr-B")
    reverse = c.rr_job(1, "B", "A", "default", "s1_B_rr-A")

    def mask(h0: float, scope: str = "local", channels=None) -> dict:
        """Build a 30 min all-band mask from h0 hours after T0, with `channels` when given."""
        out = {"start": iso(h0), "end": iso(h0 + 0.5), "bands": "all", "reason": "test", "found_by": "time",
               "scope": scope}
        return out if channels is None else {**out, "channels": channels}

    def write(blocks: dict) -> None:
        (root / "masks.yaml").write_text(yaml.safe_dump(blocks), encoding="utf-8")

    def digest(site: str, sig: str) -> str:
        return sig.split(f";{site}:m")[1][:8]

    write({})
    bare, reverse_bare = c.inputs(job), c.inputs(reverse)
    write({"A": [mask(20)]})
    old = {k: v for k, v in mask(20).items() if k != "scope"}  # the six keys a pre-channels entry hashed
    want = hashlib.sha1(json.dumps([old], sort_keys=True).encode()).hexdigest()[:8]
    plain = c.inputs(job)
    assert digest("A", plain) == want, (plain, want)
    write({"A": [mask(20, channels=["ex"])]})
    assert digest("A", c.inputs(job)) != want, "A's channels: [ex] left its masks hash as without the key"
    write({"B": [mask(10, "both", ["ex"])]})
    assert c.inputs(job) == bare, ("B's E-only entry changed A rr B's inputs", c.inputs(job))
    assert c.inputs(reverse) != reverse_bare, "B's E-only entry left B rr A's inputs unchanged"
    write({"B": [mask(10, "remote")]})
    assert c.inputs(job) != bare, "B's remote-scoped entry left A rr B's inputs unchanged"
    assert c.inputs(reverse) == reverse_bare, ("B's remote-scoped entry changed B rr A's inputs", c.inputs(reverse))
    write({"A": [mask(20, "remote")]})
    assert c.inputs(job) == bare, ("A's remote-scoped entry changed A rr B's inputs", c.inputs(job))
    print(f"  A's entry without channels hashes to {want} as before; channels [ex] moves it; B's E-only entry: "
          f"A rr B unchanged, B rr A changed; scope remote: B's applies to A rr B only, A's to neither")

    off = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root / "off")), parallel=2, create=False)
    off.plan.configs = {"masked": ["--masks"], "hamming": ["--taper", "hamming"]}
    off.best_remotes = lambda sites, persist=True, df=None: {s: {"remote": "B"} for s in sites}
    write({"A": [mask(20, "remote")], "B": [mask(10, "both", ["ey"])]})
    none = [j.config for j in off.stage3_jobs(["A"])]
    write({"A": [mask(20, "remote")], "B": [mask(10, "remote")]})
    some = [j.config for j in off.stage3_jobs(["A"])]
    assert none == ["hamming"] and some == ["masked", "hamming"], (none, some)
    print(f"  stage 3: A remote-scoped + B E-only: {none}; B remote-scoped: {some}")


def test_mantle_config() -> None:
    root = ROOT / "mantle"
    survey_yaml = make_survey(root)
    configs = {"mantle": ["--engine", "mantle"], "hamming": ["--taper", "hamming"]}
    runner_on = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2, "masks": True}
    on = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root, configs=configs, runner=runner_on)), parallel=2,
                     create=False)
    assert on.config_engine("mantle") == "mantle" and on.config_engine("hamming") == "aurora", on.plan.configs
    assert on.config_engine("default") == "aurora"
    assert not on.rr_masks_on("mantle") and on.rr_masks_on("hamming") and on.rr_masks_on("default")
    job = on.rr_job(3, "A", "B", "mantle", "s3_A_rr-B_mantle")
    assert job.cmd.count("--no-masks") == 1 and job.cmd.index("--no-masks") < job.cmd.index("--engine"), job.cmd
    assert job.cmd[job.cmd.index("--engine") + 1] == "mantle", job.cmd
    assert ":m" not in on.inputs(job), on.inputs(job)
    aurora_job = on.rr_job(3, "A", "B", "hamming", "s3_A_rr-B_hamming")
    assert "--no-masks" not in aurora_job.cmd and ":m" in on.inputs(aurora_job), (aurora_job.cmd, on.inputs(aurora_job))
    off = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root / "off", configs=configs)), parallel=2, create=False)
    off_job = off.rr_job(3, "A", "B", "mantle", "s3_A_rr-B_mantle")
    assert off_job.cmd.count("--no-masks") == 1, off_job.cmd
    off.best_remotes = lambda sites, persist=True, df=None: {s: {"remote": "B"} for s in sites}
    (root / "off" / "masks.yaml").write_text("", encoding="utf-8")
    built = [j.config for j in off.stage3_jobs(["A"])]
    assert built == ["mantle", "hamming"], built
    print(f"  runner.masks on: {job.cmd[-6:]}, inputs {on.inputs(job)!r}; off: {off_job.cmd[-6:]}; stage 3 {built}")

    out, text = quiet(off.dry_run, [3], off.plan.sites)
    listed = [line for line in text.splitlines() if "[--engine mantle]" in line]
    assert len(listed) == 5 and out["counts"][3]["rr"] == 10, (len(listed), out["counts"], text)
    print(f"  dry run: {len(listed)} stage 3 rows '[--engine mantle]', stage 3 counts {out['counts'][3]}")

    # move_products takes the report and the fine EDI the sidecar names along with the EDI
    c = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root / "move", configs=configs)), parallel=2, create=True)
    tf_dir = c.survey.workspace / "tf"
    tf_dir.mkdir(parents=True, exist_ok=True)
    stem = "A_rr-B_20260925-0900_syn-mantle"
    files = {key: tf_dir / name for key, name in (
        ("edi", f"{stem}.edi"), ("sidecar", f"{stem}.json"), ("figure", f"{stem}_vs_lemimt.png"),
        ("mantle_report", f"{stem}.mantle_report.json"), ("mantle_fine_edi", f"{stem}_fine.edi"))}
    for path in files.values():
        path.write_text("{}" if path.suffix == ".json" else "x", encoding="utf-8")
    files["sidecar"].write_text(json.dumps({"engine": "mantle", "mantle_report": files["mantle_report"].name,
                                            "mantle_fine_edi": files["mantle_fine_edi"].name}), encoding="utf-8")
    move_job = c.rr_job(3, "A", "B", "mantle", "s3_A_rr-B_mantle")
    moved = c.move_products(move_job, {k: str(files[k]) for k in ("edi", "sidecar", "figure")})
    for key, path in files.items():
        dest = c.dir / "tf" / path.name
        assert dest.exists() and not path.exists(), (key, path, dest)
        assert Path(moved[key]) == dest, (key, moved.get(key), dest)
    print(f"  move_products: {sorted(moved)} moved into {c.dir / 'tf'}")


MANTLE_CONFIGS = {"mantle": ["--engine", "mantle", "--mantle-max-hours", "72", "--no-masks"],
                  "hamming": ["--taper", "hamming"]}


def test_mantle_runner_figures() -> None:
    from types import SimpleNamespace

    root = ROOT / "mantle_gate"
    survey_yaml = make_survey(root)
    bad = {"minutes_per_job": {"rr": 8}, "expected_peak_gb": {"rr": 35, "mantel": 65}}
    try:
        cp.load_plan(make_plan(root / "bad", configs=MANTLE_CONFIGS, runner=bad))
    except ValueError as exc:
        assert "expected_peak_gb mantel" in str(exc), str(exc)
    else:
        raise AssertionError("a plan whose expected_peak_gb names 'mantel' loaded")
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1, "mantle": 12}, "min_available_gb": 0.2,
              "peak_factor": 1.0, "expected_peak_gb": {"rr": 35, "variant": 20, "stack": 8, "mantle": 65}}
    c = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root, configs=MANTLE_CONFIGS, runner=runner)), parallel=2,
                    create=False)
    rr = c.rr_job(3, "A", "B", "hamming", "s3_A_rr-B_hamming")
    mantle = c.rr_job(3, "A", "B", "mantle", "s3_A_rr-B_mantle")
    original = cp.psutil.virtual_memory
    cp.psutil.virtual_memory = lambda: SimpleNamespace(available=40.0 * 1024.0**3)
    try:
        ok_rr, msg_rr = c.gate(rr)
        ok_m, msg_m = c.gate(mantle)
        assert ok_rr and not ok_m and msg_m.endswith("need 65.0 GB"), (msg_rr, msg_m)
        c._running["run"] = cp.Running(mantle, popen=None, ps=None, started=cp.now(), t0=0.0,
                                       log_path=root / "x.log", log_offset=0, rss_mb=5.0 * 1024.0)
        ok_held, msg_held = c.gate(rr)
        assert not ok_held and "60.0 GB held back" in msg_held, msg_held
        c._running.clear()
        for rid, kind, config, gb in (("r1", "rr", "default", 20.0), ("m1", "rr", "mantle", 60.0)):
            c.ledger.rows[rid] = {**{k: "" for k in cp.LEDGER_COLUMNS}, "run_id": rid, "kind": kind,
                                  "config": config, "peak_rss_mb": str(gb * 1024.0), "finished": rid}
        assert c.expected_peak_mb("mantle") == 60.0 * 1024.0, c.expected_peak_mb("mantle")
        assert c.expected_peak_mb("rr") == 20.0 * 1024.0, c.expected_peak_mb("rr")
        ok_rr2, msg_rr2 = c.gate(rr)
        assert ok_rr2 and msg_rr2.endswith("need 20.0 GB"), msg_rr2
    finally:
        cp.psutil.virtual_memory = original
    print(f"  40 GB available: aurora job starts ({msg_rr}); mantle waits ({msg_m}); a running mantle job at 5 GB: "
          f"{msg_held}; with finished peaks rr 20 / mantle 60 GB the aurora job {msg_rr2}")

    c.ledger.rows.clear()
    c.best_remotes = lambda sites, persist=True, df=None: {s: {"remote": "B" if s != "B" else "A"} for s in sites}
    out, _ = quiet(c.dry_run, [3], c.plan.sites)
    want = (5 * 12 + 5 * 8) / 2 / 60
    assert out["counts"][3]["rr"] == 10 and abs(out["hours"] - want) < 1e-9, (out["counts"], out["hours"], want)
    print(f"  dry run stage 3: {out['counts'][3]['rr']} rr, {out['hours']:.3f} h (mantle at 12 min, the rest at 8)")


def test_mantle_runner_and_scores() -> None:
    root = ROOT / "mantle_run"
    survey_yaml = make_survey(root)
    # mantle_gb_per_hour tiny: the stand-in's peak is a few MB, and the gate must not wait for 46 h x 1.25 GB
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1, "mantle": 12}, "min_available_gb": 0.2,
              "peak_factor": 1.0, "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05, "mantle": 0.05},
              "mantle_gb_per_hour": 0.0001}
    plan = cp.load_plan(make_plan(root, configs=MANTLE_CONFIGS, runner=runner))
    fake = fake_scripts(root)
    original = cp.SCRIPTS
    cp.SCRIPTS = fake
    try:
        c = cp.Campaign(survey_yaml, plan, parallel=2)
        c.api = {"func": "processing_archive", "variant": True, "rr": True, "stack": True, "why": ""}
        quiet(c.run_block, "stage 1 A", c.stage1_jobs(["A"]))
        jobs3 = c.stage3_jobs(["A"])
        quiet(c.run_block, "stage 3 A", jobs3)
        again = cp.Campaign(survey_yaml, plan, parallel=2)
        again.api = dict(c.api)
        quiet(again.run_block, "stage 3 A again", again.stage3_jobs(["A"]))
    finally:
        cp.SCRIPTS = original
    assert again.n_started == 0, f"{again.n_started} child(ren) started on the second pass"
    rows = c.ledger.rows
    s3 = {j.config: rows[j.run_id] for j in jobs3}
    assert sorted(s3) == ["hamming", "mantle"] and all(r["status"] == "done" for r in s3.values()), s3
    assert s3["mantle"]["engine"] == "mantle" and s3["hamming"]["engine"] == "aurora", \
        {k: r["engine"] for k, r in s3.items()}
    assert all(rows[f"s1_A_rr-{r}"]["engine"] == "aurora" for r in ("B", "C")), rows
    argv = json.loads(Path(s3["mantle"]["sidecar"]).read_text(encoding="utf-8"))["argv"]
    assert argv[argv.index("--mantle-max-hours") + 1] == "72" and "--no-masks" in argv, argv

    df = c.scores()
    m = df[df["config"] == "mantle"].iloc[0]
    d = df[(df["stage"] == 1) & (df["remote"] == m["remote"])].iloc[0]
    own = cp.tf_quality(d["edi"], c.pmin, 1000.0)["overall"]["score"]
    assert abs(m["score"] - own) < 1e-12 and m["engine"] == "mantle", (m["score"], own, m["engine"])
    assert abs(m["period_max"] - 1000.0) < 1.0 and m["n_periods"] == P_MANTLE.size, (m["period_max"], m["n_periods"])
    assert d["score"] < m["score"] and abs(d["period_max"] - P_FULL[-1]) < 1.0, (d["score"], d["period_max"])
    c.report(["A"])
    summary = (c.dir / "summary.md").read_text(encoding="utf-8")
    line = next(ln for ln in summary.splitlines() if ln.startswith("| A | G1 |"))
    assert "(to 1000 s)" in line and "mantle +" in line, line
    print(f"  ledger engines: mantle {s3['mantle']['engine']}, hamming {s3['hamming']['engine']}; mantle argv "
          f"...{' '.join(argv[-8:])}")
    print(f"  mantle product: score {m['score']:.3f} over {m['n_periods']} periods to {m['period_max']:.0f} s = the "
          f"default's score over 0.005-1000 s ({own:.3f}); the default over 0.005-5000 s {d['score']:.3f} "
          f"(to {d['period_max']:.0f} s); summary: {line.split('|')[-2].strip()}")


CLIP_CONFIGS = {"mantle": ["--engine", "mantle", "--mantle-max-hours", "24"],
                "big": ["--engine", "mantle", "--mantle-max-hours", "100"],
                "own": ["--engine", "mantle", "--mantle-window", "refuse"],
                "hamming": ["--taper", "hamming"]}


def test_mantle_window_and_memory() -> None:
    from types import SimpleNamespace

    root = ROOT / "mantle_clip"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 10.0, "peak_factor": 1.0,
              "expected_peak_gb": {"rr": 35, "variant": 20, "stack": 8}, "mantle_gb_per_hour": 1.25}
    c = cp.Campaign(survey_yaml, cp.load_plan(make_plan(root, configs=CLIP_CONFIGS, runner=runner)), parallel=1,
                    create=True)
    jobs = {k: c.rr_job(3, "A", "B", k, f"s3_A_rr-B_{k}") for k in CLIP_CONFIGS}
    cmd = jobs["mantle"].cmd
    assert cmd.count("--mantle-window") == 1 and cmd[-4:-2] == ["--mantle-window", "clip"], cmd
    own = jobs["own"].cmd
    assert own.count("--mantle-window") == 1 and own[own.index("--mantle-window") + 1] == "refuse", own
    assert "--mantle-window" not in jobs["hamming"].cmd, jobs["hamming"].cmd
    assert jobs["mantle"].clip_note.startswith("expected window clip (cap): 46.0 h overlap over the 24 h cap"), \
        jobs["mantle"].clip_note
    assert jobs["big"].clip_note == "" and jobs["own"].clip_note == "", (jobs["big"].clip_note, jobs["own"].clip_note)

    gb = lambda job: c.job_peak_mb(job) / 1024.0  # noqa: E731
    assert abs(gb(jobs["mantle"]) - 35.0) < 1e-9 and abs(gb(jobs["big"]) - 57.5) < 1e-9, \
        (gb(jobs["mantle"]), gb(jobs["big"]))
    assert abs(gb(jobs["hamming"]) - 35.0) < 1e-9, gb(jobs["hamming"])
    for rid, config, peak in (("r1", "default", 20.0), ("b1", "big", 70.0)):
        c.ledger.rows[rid] = {**{k: "" for k in cp.LEDGER_COLUMNS}, "run_id": rid, "kind": "rr", "config": config,
                              "peak_rss_mb": str(peak * 1024.0), "finished": rid}
    assert abs(gb(jobs["big"]) - 70.0) < 1e-9, gb(jobs["big"])
    assert abs(c.finished_peak_mb(None) / 1024.0 - 20.0) < 1e-9, c.finished_peak_mb(None) / 1024.0
    finished = (gb(jobs["big"]), c.finished_peak_mb(None) / 1024.0)
    c.ledger.rows.clear()

    original = cp.psutil.virtual_memory
    cp.psutil.virtual_memory = lambda: SimpleNamespace(available=60.0 * 1024.0**3, total=64.0 * 1024.0**3)
    try:
        over = c.over_machine(jobs["big"])
        assert "expected peak 57.5 GB" in over and "the machine has 64.0 GB" in over, over
        assert c.over_machine(jobs["mantle"]) == "" and c.over_machine(jobs["hamming"]) == ""
        quiet(c.run_block, "too big", [jobs["big"]])
        row = c.ledger.rows[jobs["big"].run_id]
        assert c.n_started == 0 and row["status"] == "skipped", (c.n_started, row)
        assert "expected peak 57.5 GB" in row["note"] and "the machine has 64.0 GB" in row["note"], row["note"]
        c.ledger.rows.clear()
        c.best_remotes = lambda sites, persist=True, df=None: {s: {"remote": "B" if s != "B" else "A"} for s in sites}
        _, text = quiet(c.dry_run, [3], ["A"])
    finally:
        cp.psutil.virtual_memory = original
    lines = {ln.split()[0]: ln for ln in text.splitlines() if ln.strip().startswith("s3_A_rr-B_")}
    assert "MANTLE 24.0 h (the 24 h cap of 46.0 h), expected peak 35.0 GB" in lines["s3_A_rr-B_mantle"], lines
    assert "MANTLE 46.0 h, expected peak 57.5 GB" in lines["s3_A_rr-B_big"], lines
    assert "would be SKIPPED" in lines["s3_A_rr-B_big"] and "SKIPPED" not in lines["s3_A_rr-B_mantle"], lines
    assert "MANTLE" not in lines["s3_A_rr-B_hamming"], lines["s3_A_rr-B_hamming"]
    print(f"  commands: mantle ...{' '.join(cmd[-4:])}; own ...{' '.join(own[-4:])}; note {jobs['mantle'].clip_note!r}")
    print(f"  expected peaks: 24 h row 35.0 GB (flat), 46 h row 57.5 GB (by hours); with finished peaks the 46 h row "
          f"{finished[0]:.1f} GB and the aurora percentile {finished[1]:.1f} GB")
    print(f"  64 GB machine: {over}; row skipped, note {row['note'][:60]!r}...")
    print(f"  dry run: {lines['s3_A_rr-B_big'].split(';', 1)[1].strip()[:140]}")


def test_mantle_resume() -> None:
    root = ROOT / "mantle_resume"
    survey_yaml = make_survey(root)
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2, "peak_factor": 1.0,
              "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05}, "mantle_gb_per_hour": 0.0001}
    configs = {"mantle": CLIP_CONFIGS["mantle"], "hamming": ["--taper", "hamming"]}
    plan = cp.load_plan(make_plan(root, configs=configs, runner=runner))
    fake = fake_scripts(root)
    product_edi(fake / "edis" / "C_full.edi", P_FULL, tail_from=100.0)  # C scores lower: B is A's best remote
    original = cp.SCRIPTS
    cp.SCRIPTS = fake
    try:
        c = cp.Campaign(survey_yaml, plan, parallel=2)
        c.api = {"func": "processing_archive", "variant": True, "rr": True, "stack": True, "why": ""}
        quiet(c.run_block, "stage 1 A", c.stage1_jobs(["A"]))
        quiet(c.run_block, "stage 3 A", c.stage3_jobs(["A"]))
        rid = "s3_A_rr-B_mantle"
        row = c.ledger.rows[rid]
        argv = json.loads(Path(row["sidecar"]).read_text(encoding="utf-8"))["argv"]
        mode = argv[argv.index("--mantle-window") + 1] if "--mantle-window" in argv else None
        assert row["status"] == "done" and mode == "clip", (row["status"], argv)
        assert row["note"] == "window clipped (cap): 46.0 h requested, 24.0 h used", row["note"]
        # a row done before the flag existed: its cmd lacks it
        c.ledger.upsert({"run_id": rid, "cmd": row["cmd"].replace(" --mantle-window clip", "")})
        assert "--mantle-window" not in c.ledger.rows[rid]["cmd"]
        again = cp.Campaign(survey_yaml, plan, parallel=2)
        again.api = dict(c.api)
        quiet(again.run_block, "resume", again.stage3_jobs(["A"]))
        assert again.n_started == 0, f"{again.n_started} started on resume"
        again.ledger.upsert({"run_id": rid, "status": "failed", "exit_code": "1"})
        third = cp.Campaign(survey_yaml, plan, parallel=2)
        third.api = dict(c.api)
        quiet(third.run_block, "resume after a failure", third.stage3_jobs(["A"]))
        assert third.n_started == 1 and third.ledger.rows[rid]["status"] == "done", \
            (third.n_started, third.ledger.rows[rid]["status"])
    finally:
        cp.SCRIPTS = original
    print(f"  mantle child argv ...{' '.join(argv[-4:])}; ledger note {row['note']!r}; a done row without the flag "
          f"in its cmd: 0 started; the same row failed: {third.n_started} started")


def test_deferred_configs() -> None:
    root = ROOT / "mantle_resume"  # the campaign of test_mantle_resume, finished
    survey_yaml = root / "survey.yaml"
    configs = {"mantle": CLIP_CONFIGS["mantle"], "hamming": ["--taper", "hamming"],
               "mantle_full": ["--engine", "mantle", "--mantle-max-hours", "100"]}
    runner = {"minutes_per_job": {"rr": 8, "variant": 8, "stack": 1}, "min_available_gb": 0.2, "peak_factor": 1.0,
              "expected_peak_gb": {"rr": 0.05, "variant": 0.05, "stack": 0.05}, "mantle_gb_per_hour": 0.0001,
              "deferred_configs": ["mantle_full"]}
    bad = dict(runner, deferred_configs=["mantelfull"])
    try:
        cp.load_plan(make_plan(root / "bad", configs=configs, runner=bad))
    except ValueError as exc:
        assert "deferred_configs mantelfull" in str(exc), str(exc)
    else:
        raise AssertionError("a plan deferring a config it lacks loaded")
    try:
        cp.load_plan(make_plan(root / "bad", configs={"full_": ["--engine", "mantle"]}))
    except ValueError as exc:
        assert "config 'full_'" in str(exc), str(exc)
    else:
        raise AssertionError("a config named with a trailing underscore loaded")
    plan_path = make_plan(root / "full", configs=configs, runner=runner)
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    raw["windows"] = {"A": {"yx": [iso(10), iso(14)]}}
    plan_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    plan = cp.load_plan(plan_path)
    assert plan.deferred_configs == ["mantle_full"], plan.deferred_configs
    pick = lambda sites, persist=True, df=None: {s: {"remote": "B"} for s in sites}  # noqa: E731
    built = {}
    for label, only in (("none", None), ("mantle_full", ["mantle_full"]), ("hamming", ["hamming"])):
        c = cp.Campaign(survey_yaml, plan, parallel=1, create=False, configs=only)
        c.best_remotes = pick
        built[label] = [j.config for j in c.stage3_jobs(["A"])]
    assert built["none"] == ["mantle", "hamming", "default-yxwin"], built["none"]
    assert built["mantle_full"] == ["mantle_full"] and built["hamming"] == ["hamming"], built
    nope = quiet(cp.main, [str(survey_yaml), str(plan_path), "--stage", "3", "--configs", "nope", "--dry-run"])[0]
    assert nope == 2, nope

    before = {rid: dict(row) for rid, row in cp.Ledger(ROOT / "mantle_resume" / "work" / "campaign" / "syn" /
                                                         "ledger.csv").rows.items()}
    fake = ROOT / "mantle_resume" / "fake_scripts"
    original, probe = cp.SCRIPTS, cp.api_state
    cp.SCRIPTS = fake
    cp.api_state = lambda: {"func": "processing_archive", "variant": True, "rr": True, "stack": True, "why": ""}
    try:
        code, text = quiet(cp.main, [str(survey_yaml), str(plan_path), "--stage", "3", "--sites", "A", "--configs",
                                     "mantle_full", "--parallel", "1"])
    finally:
        cp.SCRIPTS, cp.api_state = original, probe
    after = cp.Ledger(ROOT / "mantle_resume" / "work" / "campaign" / "syn" / "ledger.csv").rows
    new = sorted(set(after) - set(before))
    assert code == 0 and new == ["s3_A_rr-B_mantle_full"], (code, new, text[-600:])
    assert after["s3_A_rr-B_mantle_full"]["status"] == "done", after["s3_A_rr-B_mantle_full"]
    changed = [rid for rid in before if after[rid] != before[rid]]
    assert not changed, changed
    starts = [ln for ln in text.splitlines() if " START " in ln]
    assert len(starts) == 1 and "s3_A_rr-B_mantle_full" in starts[0], starts
    print(f"  stage 3 of A: no --configs {built['none']}; --configs mantle_full {built['mantle_full']}; "
          f"--configs hamming {built['hamming']}; --configs nope exit {nope}")
    print(f"  finished campaign, --stage 3 --configs mantle_full: 1 child ({starts[0].split('START ')[1][:60]}), "
          f"{len(before)} earlier rows unchanged")


def _plan_with(root: Path, **keys) -> Path:
    """Write the synthetic plan (configs [--taper hamming]) with extra top-level keys."""
    path = make_plan(root, configs={"hamming": ["--taper", "hamming"]})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.update(keys)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_site_overrides() -> None:
    root = ROOT / "sites"
    survey_yaml = make_survey(root)
    window = [iso(10), iso(14)]
    bad = {
        "a site as its own remote": ({"remotes": {"A": "A"}}, "remotes A: A: another plan site or a stack"),
        "a remote outside the plan": ({"remotes": {"A": "Z"}}, "remotes A: Z: another plan site or a stack"),
        "an unknown mode": ({"modes": {"B": ["zz"]}}, "modes B: ['zz']: one or both of xy, yx"),
        "a window ending first": ({"windows": {"A": {"yx": window[::-1]}}}, "windows A yx:"),
        "merge over two windows": ({"windows": {"A": {"xy": window, "yx": window, "merge": True}}},
                                   "windows A: merge takes one mode's window, 2 given"),
    }
    for label, (keys, message) in bad.items():
        try:
            cp.load_plan(_plan_with(root / "bad", **keys))
        except ValueError as exc:
            assert message in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"a plan with {label} loaded")
    print(f"  refused: {', '.join(bad)}")

    keys = {"remotes": {"A": "C"}, "modes": {"B": ["xy"]}, "windows": {"A": {"yx": window, "merge": True}}}
    plan = cp.load_plan(_plan_with(root, **keys))
    start, end = (cp.utc_text(t) for t in window)
    assert plan.windows["A"] == {"modes": {"yx": (start, end)}, "merge": True}, plan.windows

    fresh = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    out, text = quiet(fresh.dry_run, [3], ["A"])
    assert out["counts"][3]["rr"] == 2 and out["counts"][3]["merge"] == 1, (out["counts"], text)
    assert "s3_A_rr-C_default-yxwin" in text and "s3_A_rr-C_default-merged" in text, text
    print(f"  dry run with no stage 1 product: A's stage 3 on C, {out['counts'][3]}")

    fake = fake_scripts(root, bad_yx=True)
    product_edi(fake / "edis" / "C_full.edi", P_FULL, tail_from=100.0, bad_yx=True)
    original = cp.SCRIPTS
    cp.SCRIPTS = fake
    try:
        c = cp.Campaign(survey_yaml, plan, parallel=2)
        c.api = {"func": "processing_archive", "variant": True, "rr": True, "stack": True, "why": ""}
        quiet(c.run_block, "stage 1 A B", c.stage1_jobs(["A", "B"]))
        jobs3 = c.stage3_jobs(["A", "B"])
        quiet(c.run_block, "stage 3 A B", jobs3)
        again = cp.Campaign(survey_yaml, plan, parallel=2)
        again.api = dict(c.api)
        quiet(again.run_block, "stage 3 again", again.stage3_jobs(["A", "B"]))
    finally:
        cp.SCRIPTS = original
    rows = c.ledger.rows
    stored = json.loads((c.dir / "best_remote.json").read_text(encoding="utf-8"))
    assert stored["A"]["remote"] == "B", stored["A"]
    a3 = {j.config: j for j in jobs3 if j.local == "A"}
    assert sorted(a3) == ["default-merged", "default-yxwin", "hamming"], sorted(a3)
    assert all(j.remote == "C" for j in a3.values()), [(j.config, j.remote) for j in a3.values()]
    for j in a3.values():
        assert rows[j.run_id]["status"] == "done", rows[j.run_id]
        assert "remote override (the campaign's pick: B)" in rows[j.run_id]["note"], rows[j.run_id]["note"]
    win = a3["default-yxwin"]
    assert win.cmd[5:7] == [start, end] and win.tag == "syn-default-yxwin", (win.cmd, win.tag)
    merged = rows[a3["default-merged"].run_id]
    assert merged["kind"] == "merge" and merged["tag"] == "syn-default-merged" and merged["engine"] == "aurora", merged
    side = json.loads(Path(merged["sidecar"]).read_text(encoding="utf-8"))
    assert side["sources"]["xy"]["edi"] == rows["s1_A_rr-C"]["edi"], side["sources"]["xy"]
    assert side["sources"]["yx"]["edi"] == rows[win.run_id]["edi"], side["sources"]["yx"]
    p_m, rho_m, phi_m = cp.curves(merged["edi"])[:3]
    p_f, rho_f, phi_f = cp.curves(rows["s1_A_rr-C"]["edi"])[:3]
    p_w, rho_w, phi_w = cp.curves(rows[win.run_id]["edi"])[:3]
    # at 158 s the full record's rows are scattered (its tail starts at 100 s) and the window's are not
    k_m, k_f, k_w = (int(np.argmin(np.abs(np.log(p / 10.0**2.2)))) for p in (p_m, p_f, p_w))
    assert abs(rho_f[k_f, 0, 1] / rho_w[k_w, 0, 1] - 1) > 0.5, "the two sources agree at the check period"
    assert abs(rho_m[k_m, 0, 1] / rho_f[k_f, 0, 1] - 1) < 1e-4 and abs(phi_m[k_m, 0, 1] - phi_f[k_f, 0, 1]) < 0.01
    assert abs(rho_m[k_m, 1, 0] / rho_w[k_w, 1, 0] - 1) < 1e-4 and abs(phi_m[k_m, 1, 0] - phi_w[k_w, 1, 0]) < 0.01
    assert again.n_started == 0 and again.ledger.rows[merged["run_id"]]["finished"] == merged["finished"], \
        (again.n_started, again.ledger.rows[merged["run_id"]]["finished"], merged["finished"])

    df = c.scores()
    b_rows = df[df["local"] == "B"]
    assert len(b_rows) and (b_rows["modes"] == "xy").all(), b_rows[["run_id", "modes"]]
    assert np.allclose(b_rows["score"], b_rows["xy_score"]), b_rows[["score", "xy_score"]]
    # the fixture: every B product is a full-record one (scattered yx), not the window's (sound yx, to 200 s)
    fixture = (b_rows["yx_score"] < 0.1) & (b_rows["period_max"] > 1000.0)
    assert fixture.all(), b_rows[["run_id", "yx_score", "period_max"]]
    assert ((b_rows["overall_score"] - b_rows["score"]).abs() > 0.1).all(), b_rows[["score", "overall_score"]]
    m = df[df["run_id"] == merged["run_id"]].iloc[0]
    full = df[df["run_id"] == "s1_A_rr-C"].iloc[0]
    assert m["score"] > full["score"] + 0.1, (m["score"], full["score"])
    c.report(["A", "B"])
    summary = (c.dir / "summary.md").read_text(encoding="utf-8")
    line_a = next(ln for ln in summary.splitlines() if ln.startswith("| A | G1 |"))
    line_b = next(ln for ln in summary.splitlines() if ln.startswith("| B (xy-only) | G1 |"))
    assert f"| C | {m['score']:.3f} |" in line_a and "the default is the merged product" in line_a, line_a
    assert "remote override (the campaign's pick: B" in line_a, line_a
    print(f"  A: stage 3 on C ({rows[a3['hamming'].run_id]['note']}); window run {win.cmd[5:7]}; merge "
          f"{Path(merged['edi']).name}: xy from {Path(side['sources']['xy']['edi']).name}, yx from "
          f"{Path(side['sources']['yx']['edi']).name}; score {m['score']:.3f} vs the full record {full['score']:.3f}")
    print(f"  B xy-only: scores {list(np.round(b_rows['score'], 3))} = xy, overall "
          f"{list(np.round(b_rows['overall_score'], 3))}; second pass: 0 started, the merge kept")
    print(f"  summary: {line_a[:160]}...")


def test_min_band_windows_plan_key() -> None:
    root = ROOT / "floor"
    survey_yaml = make_survey(root)
    configs = {"hamming": ["--taper", "hamming"], "mantle": ["--engine", "mantle"],
               "floor5": ["--min-band-windows", "5"]}

    def plan_path(sub: str, floor, windows=True) -> Path:
        path = make_plan(root / sub, configs=configs)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if floor is not None:
            raw["min_band_windows"] = floor
        if windows:
            raw["windows"] = {"A": {"yx": [iso(10), iso(14)]}}
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return path

    for bad in (-1, 2.5, True, "2"):
        try:
            cp.load_plan(plan_path("bad", bad))
        except ValueError as exc:
            assert "min_band_windows" in str(exc), str(exc)
        else:
            raise AssertionError(f"a plan with min_band_windows {bad!r} loaded")
    assert cp.load_plan(plan_path("zero", 0)).min_band_windows == 0

    pick = lambda sites, persist=True, df=None: {s: {"remote": "B"} for s in sites}  # noqa: E731

    def campaign(sub: str, floor) -> "cp.Campaign":
        c = cp.Campaign(survey_yaml, cp.load_plan(plan_path(sub, floor)), parallel=2, create=False)
        c.best_remotes = pick
        return c

    two, three, none = campaign("two", 2), campaign("three", 3), campaign("none", None)
    (root / "two" / "masks.yaml").write_text("", encoding="utf-8")
    s1 = two.stage1_jobs(["A"])
    s2 = [j for j in quiet(two.stage2_jobs, ["A"])[0] if j.kind == "rr"]
    s3 = {j.config: j for j in two.stage3_jobs(["A"])}
    assert sorted(s3) == ["default-yxwin", "floor5", "hamming", "mantle"], sorted(s3)
    flag = ["--min-band-windows", "2"]

    def at(cmd, items):
        return [i for i in range(len(cmd) - 1) if cmd[i:i + len(items)] == items]

    for job in [*s1, *s2, s3["hamming"], s3["default-yxwin"], s3["floor5"]]:
        where = at(job.cmd, flag)
        assert len(where) == 1 and job.cmd.count("--min-band-windows") == (2 if job.config == "floor5" else 1), \
            (job.run_id, job.cmd)
        assert job.cmd.index("--no-masks") < where[0] < job.cmd.index("--tag"), (job.run_id, job.cmd)
        extra = two.plan.configs.get(job.config, [])
        assert not extra or where[0] < at(job.cmd, extra)[0], (job.run_id, job.cmd)
        assert two.inputs(job).endswith(";min_band_windows 2") or job.config == "floor5", two.inputs(job)
    own = at(s3["floor5"].cmd, ["--min-band-windows", "5"])
    assert own and own[0] > at(s3["floor5"].cmd, flag)[0], s3["floor5"].cmd
    assert "min_band_windows" not in two.inputs(s3["floor5"]), two.inputs(s3["floor5"])
    assert "--min-band-windows" not in s3["mantle"].cmd and "min_band_windows" not in two.inputs(s3["mantle"]), \
        s3["mantle"].cmd
    print(f"  floor 2: stage 1 {s1[0].cmd[5:]}; stage 2 {s2[0].run_id}, stage 3 hamming, the window run carry "
          f"--min-band-windows 2 once; floor5 {s3['floor5'].cmd[5:-2]}; mantle none")

    j3 = {j.config: j for j in three.stage3_jobs(["A"])}
    assert three.inputs(j3["hamming"]).endswith(";min_band_windows 3"), three.inputs(j3["hamming"])
    assert three.inputs(j3["hamming"]) != two.inputs(s3["hamming"])
    assert three.inputs(j3["mantle"]) == two.inputs(s3["mantle"]), (three.inputs(j3["mantle"]), two.inputs(s3["mantle"]))
    assert three.inputs(j3["floor5"]) == two.inputs(s3["floor5"])
    edi = synthetic_edi(root / "done.edi")
    row = {**{k: "" for k in cp.LEDGER_COLUMNS}, "run_id": s3["hamming"].run_id, "stage": "3", "kind": "rr",
           "local": "A", "remote": "B", "config": "hamming", "status": "done", "exit_code": "0", "edi": str(edi),
           "inputs": two.inputs(s3["hamming"])}
    for c in (two, three):  # in memory: a dry-run campaign has no folder to save the ledger to
        c.ledger.rows[row["run_id"]] = dict(row)
    assert two.already_done(s3["hamming"]) and not three.already_done(j3["hamming"]), "the floor change left it done"
    n1 = none.stage1_jobs(["A"])
    nj = {j.config: j for j in none.stage3_jobs(["A"])}
    assert all("--min-band-windows" not in j.cmd for j in [*n1, nj["hamming"], nj["default-yxwin"]]), n1[0].cmd
    assert all("min_band_windows" not in none.inputs(j) for j in [*n1, *nj.values()])
    print("  floor 3: aurora inputs changed, mantle and floor5 unchanged; a row done under 2 stale under 3; "
          "no key: no flag, no floor in the inputs")

    out, text = quiet(two.dry_run, [1, 3], ["A"])
    lines = text.splitlines()
    s1_lines = [ln for ln in lines if ln.strip().startswith("s1_A_rr-")]
    assert s1_lines and all("[--min-band-windows 2]" in ln for ln in s1_lines), s1_lines
    assert any("s3_A_rr-B_floor5" in ln and "[--min-band-windows 2 --min-band-windows 5]" in ln for ln in lines), text
    assert any("s3_A_rr-B_mantle" in ln and "[--engine mantle]" in ln for ln in lines), text
    code, text = quiet(cp.main, [str(survey_yaml), str(root / "two" / "plan.yaml"), "--stage", "1", "--sites", "A",
                                 "--dry-run"])
    head = next(ln for ln in text.splitlines() if ln.startswith("campaign syn:"))
    assert code == 0 and head.endswith("; min_band_windows 2 on every aurora rr run"), (code, head)
    two.ledger.rows = {}
    summary = root / "two_summary.md"
    cp.write_summary(two, pd.DataFrame(), {}, summary)
    assert "`--min-band-windows 2`" in summary.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8")[:600]
    print(f"  dry run: {s1_lines[0].strip()[:90]}; plan line ends {head[-45:]!r}; summary.md states the floor")


def test_remote_only() -> None:
    root = ROOT / "remote_only"
    survey_yaml = make_survey(root, {**SPANS_H, "O": (0, 94)})
    bad = {
        "a remote-only site that is a plan site": ({"remote_only": ["A"]}, "remote_only A: also in sites or exclude"),
        "a remote-only site listed twice": ({"remote_only": ["O", "O"]}, "remote_only: listed twice: ['O']"),
    }
    for label, (keys, message) in bad.items():
        try:
            cp.load_plan(_plan_with(root / "bad", **keys))
        except ValueError as exc:
            assert message in str(exc), (label, str(exc))
        else:
            raise AssertionError(f"a plan with {label} loaded")
    clash = make_plan(root / "clash", groups={"G1": ["A", "AR", "B"], "G2": ["D", "E"]})
    raw = yaml.safe_load(clash.read_text(encoding="utf-8"))
    raw["remote_only"] = ["O"]
    clash.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    try:
        cp.load_plan(clash)
    except ValueError as exc:
        assert "sites ['A'] and <site>R would share the stack names" in str(exc), str(exc)
    else:
        raise AssertionError("a plan with sites A and AR and remote_only loaded")
    print(f"  refused: {', '.join(bad)}, sites A and AR")

    plan = cp.load_plan(_plan_with(root, remote_only=["O"], remotes={"A": "O"}))
    assert plan.remote_only == ["O"] and plan.group_of("O") == "remote_only" and "O" not in plan.sites, plan
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    s0 = c.stage0_jobs([*plan.sites, *plan.remote_only])
    s1 = c.stage1_jobs(plan.sites)
    s2 = c.stage2_jobs(plan.sites)
    s3 = c.stage3_jobs(plan.sites, dry=True)
    assert not [j.run_id for j in s1 + s2 + s3 if j.local == "O"], "O is a local"
    blocks = list(c.blocks([0], plan.sites, dry=True))
    assert [j.local for j in blocks[0][4]].count("O") == 1, [j.local for j in blocks[0][4]]
    assert [j.group for j in s0 if j.local == "O"] == ["remote_only"], [(j.local, j.group) for j in s0]
    for s in plan.sites:
        against = [j.remote for j in s1 if j.local == s]
        assert against.count("O") == 1 and len(against) >= 2, (s, against)
    builds = {j.remote: j for j in s2 if j.kind == "stack"}
    want = {f"STK_{s}{m}{w}" for s in ("A", "B", "C") for m in ("", "R") for w in ("u", "w")}
    assert set(builds) == want, sorted(builds)
    for s, others in (("A", ["B", "C"]), ("B", ["A", "C"]), ("C", ["A", "B"])):
        for w, weighting in (("u", "none"), ("w", "coherence")):
            plain, with_o = builds[f"STK_{s}{w}"], builds[f"STK_{s}R{w}"]
            # the piece rule's flag last (item 21), then the weighting
            assert plain.cmd[-2:] == ["--min-piece-h", "6"] and with_o.cmd[-2:] == ["--min-piece-h", "6"], plain.cmd
            pc, wc = plain.cmd[:-2], with_o.cmd[:-2]
            assert pc[-2:] == ["--weighting", weighting] and wc[-2:] == ["--weighting", weighting]
            # members nearest first (the member rule of item 20), O last in the R build
            assert sorted(pc[-4:-2]) == others and sorted(plain.input_sites) == others, plain.cmd
            assert sorted(wc[-5:-3]) == others and wc[-3] == "O", with_o.cmd
            assert sorted(with_o.input_sites) == [*others, "O"], with_o.cmd
    runs2 = sorted(j.remote for j in s2 if j.kind == "rr")
    assert runs2 == sorted(want), runs2
    assert {j.remote for j in s3 if j.local == "A"} == {"O"}, [(j.run_id, j.remote) for j in s3 if j.local == "A"]
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    out, text = quiet(c.dry_run, [0, 1, 2, 3], plan.sites)
    got = {st: {k: v for k, v in kinds.items() if v} for st, kinds in out["counts"].items()}
    assert got == {0: {"variant": 6}, 1: {"rr": 13}, 2: {"stack": 12, "rr": 12}, 3: {"rr": 5}}, (got, text)
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before, "the dry run wrote"
    print(f"  O: stage 1 remote of A-E, in STK_<site>R<s> of G1; A's stage 3 on O; counts {got}")


def test_stack_members_by_runs() -> None:
    root = ROOT / "member_runs"
    spans_h = {"A": (0, 48), "B": (2, 50), "C": (4, 46), "G": (0, 48), "H": (0, 48), "I": (0, 48), "O": (0, 94)}
    survey_yaml = make_survey(root, spans_h)

    def t(h: float) -> pd.Timestamp:
        return T0 + pd.Timedelta(hours=h)

    runs = {"B": [(t(2), t(40)), (t(41), t(50))], "C": [(t(4), t(46))], "G": [(t(0), t(9.6))],
            "H": [(t(0), t(30)), (t(31), t(48))], "I": [(t(0), t(28)), (t(29), t(48))], "O": [(t(0), t(94))]}

    def plan_with(**stack_keys):
        path = make_plan(root, groups={"G1": ["A", "B", "C", "G", "H", "I"]}, configs={"hamming": ["--taper", "hamming"]})
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw["stages"]["stacks"].update(stack_keys)
        raw["remote_only"] = ["O"]
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return cp.load_plan(path)

    plan = plan_with()
    spans = cp.site_spans(cp.Survey.from_yaml(survey_yaml), [*plan.sites, *plan.remote_only])
    sp = cp.stack_plan(plan, spans, "A", runs=runs)
    assert sorted(sp["members"]) == ["B", "C"], sp["members"]
    assert abs(sp["cover"]["G"] - 0.2) < 1e-9 and abs(sp["cover"]["H"] - 0.625) < 1e-9, sp["cover"]
    assert sp["floor"] == cp.STACK_COVER == 0.70, sp["floor"]
    assert abs(sp["run_span_h"] - 36.0) < 1e-9 and abs(sp["span_h"] - 42.0) < 1e-9, (sp["run_span_h"], sp["span_h"])
    print(f"  A: members {sp['members']} (G covers 20 %, H 62.5 %, I 58 %: left out), span {sp['run_span_h']:.1f} h "
          f"from the runs against {sp['span_h']:.1f} h from the survey spans")

    sp2 = cp.stack_plan(plan_with(exclude_members=["B", "C"]), spans, "A", runs=runs)
    assert sorted(sp2["members"]) == ["H", "I"] and sp2["floor"] == cp.STACK_COVER_MIN == 0.50, sp2
    note = cp.stack_note(sp2, sp2["members"], "none")
    assert "floor lowered from 70 %: fewer than 2 reach it" in note, note
    assert cp.stack_plan(plan_with(exclude_members=["B", "C", "H"]), spans, "A", runs=runs) is None
    try:
        plan_with(exclude_members=["Q"])
    except ValueError as exc:
        assert "stacks exclude_members Q: not a plan site or a remote_only site" in str(exc), str(exc)
    else:
        raise AssertionError("a plan excluding a site it does not have loaded")
    print(f"  B and C excluded: {sp2['members']} at the 50 % floor ({note.split('; ')[1]}); H also excluded: none")

    cap_sites = [f"S{k:02d}" for k in range(11)]
    cap = cp.Plan(path=root / "cap.yaml", name="cap", description="", sites=cap_sites, exclude={},
                  groups={"G": cap_sites})
    cap_spans = {s: (t(0), t(48)) for s in cap_sites}
    sp3 = cp.stack_plan(cap, cap_spans, "S00", km=lambda a, b: abs(int(a[1:]) - int(b[1:])))
    assert sp3["members"] == cap_sites[1:9], sp3["members"]

    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    c._runs = {**{s: [spans[s]] for s in spans}, **runs}
    builds = {j.remote: j for j in c.stage2_jobs(["A"]) if j.kind == "stack"}
    assert sorted(builds) == ["STK_ARu", "STK_ARw", "STK_Au", "STK_Aw"], sorted(builds)
    assert builds["STK_Au"].cmd[-6:-4] == ["B", "C"] and builds["STK_ARu"].cmd[-7:-4] == ["B", "C", "O"], \
        (builds["STK_Au"].cmd, builds["STK_ARu"].cmd)
    for b in builds.values():
        assert "expected span 36.0 h from the runs (survey spans 42.0 h)" in b.note, b.note
    c._runs["O"] = [(t(0), t(10))]
    quiet_builds = quiet(c.stage2_jobs, ["A"])[0]
    assert not [j.remote for j in quiet_builds if "STK_AR" in j.remote], [j.remote for j in quiet_builds]
    print(f"  ten candidates: the 8 nearest; the Campaign's builds: {builds['STK_Au'].note}; O at 21 %: no R stack")

    # a stack rebuilt (new members) makes its rr run again, though the rr row's inputs still match
    build = builds["STK_Au"]
    rr = next(j for j in quiet_builds if j.kind == "rr" and j.remote == "STK_Au")
    edi = root / "work" / "tf" / "A_rr-STK_Au.edi"
    edi.write_text("x", encoding="utf-8")
    build.output.write_bytes(b"")
    c.ledger.rows[rr.run_id] = {"status": "done", "exit_code": "0", "provisional": "", "inputs": c.inputs(rr),
                                "edi": str(edi)}
    c.ledger.rows[build.run_id] = {"status": "done", "exit_code": "0", "provisional": "", "inputs": c.inputs(build)}
    done, pending = c.split_done([build, rr])
    assert done == {build.run_id, rr.run_id} and not pending, (done, [j.run_id for j in pending])
    c.ledger.rows[build.run_id]["inputs"] = "members of the earlier rule"
    done, pending = c.split_done([build, rr])
    assert not done and [j.run_id for j in pending] == [build.run_id, rr.run_id], (done, [j.run_id for j in pending])
    print("  a done rr row on a stack that is rebuilt runs again (split_done)")


def test_stack_pieces() -> None:
    root = ROOT / "pieces"
    spans_h = {"A": (0, 48), "B": (0, 48), "C": (4, 46)}
    survey_yaml = make_survey(root, spans_h)

    def t(h: float) -> pd.Timestamp:
        return T0 + pd.Timedelta(hours=h)

    runs = {"B": [(t(0), t(36)), (t(37), t(48))], "C": [(t(4), t(46))]}
    path = make_plan(root, groups={"G1": ["A", "B", "C"]}, configs={"hamming": ["--taper", "hamming"]})
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["stages"]["stacks"]["weightings"] = {"u": "none"}
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    plan = cp.load_plan(path)
    spans = cp.site_spans(cp.Survey.from_yaml(survey_yaml), plan.sites)
    sp = cp.stack_plan(plan, spans, "A", runs=runs)
    assert sorted(sp["members"]) == ["B", "C"] and abs(sp["cover"]["B"] - 0.75) < 1e-9, (sp["members"], sp["cover"])
    assert sp["pieces"]["kept"] == [(t(4), t(36)), (t(37), t(46))] and not sp["pieces"]["short"], sp["pieces"]
    assert abs(sp["run_span_h"] - 41.0) < 1e-9 and sp["run_span"] == (t(4), t(46)), (sp["run_span_h"], sp["run_span"])
    assert abs(cp.run_span(runs, spans, "A", sp["members"])[2] - 32.0) < 1e-9
    note = cp.stack_note(sp, sp["members"], "none")
    assert "expected span 41.0 h in 2 pieces from the runs (survey spans 42.0 h)" in note, note
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    c._runs = {**{s: [spans[s]] for s in spans}, **runs}
    build = next(j for j in c.stage2_jobs(["A"]) if j.kind == "stack")
    assert build.cmd[-2:] == ["--min-piece-h", "6"] and build.pieces == "2 (41.0 h)", (build.cmd, build.pieces)
    assert c.inputs(build).endswith(";pieces 2 (41.0 h)"), c.inputs(build)
    print(f"  two pieces: {note.split('; ')[-1]}; inputs ...{c.inputs(build)[-24:]}")

    # item 20's runs: one piece of 36 h (the one-run span) and one of 5 h left out
    runs20 = {"B": [(t(2), t(40)), (t(41), t(50))], "C": [(t(4), t(46))]}
    sp20 = cp.stack_plan(plan, spans, "A", runs=runs20)
    c._runs = {**{s: [spans[s]] for s in spans}, **runs20}
    b20 = next(j for j in c.stage2_jobs(["A"]) if j.kind == "stack")
    assert b20.pieces == "" and ";pieces" not in c.inputs(b20), (b20.pieces, c.inputs(b20))
    assert b20.note.endswith("expected span 36.0 h from the runs (survey spans 42.0 h); 1 piece(s) under 6 h left "
                             "out (5.0 h)"), b20.note
    assert sp20["pieces"]["kept"] == [(t(4), t(40))] and sp20["pieces"]["short"] == [(t(41), t(46))], sp20["pieces"]
    one = cp.piece_marker({"kept": [(t(10), t(20))], "short": [], "hours": 10.0}, (t(0), t(5), 5.0))
    assert one == "1 (10.0 h)", one
    p_ = cp.run_pieces({}, spans, "A", ["C"])
    assert p_["kept"] == [(t(4), t(46))] and abs(p_["hours"] - 42.0) < 1e-9, p_
    print(f"  one piece equal to the one-run span: no marker; a different single piece: {one!r}")


def main() -> int:
    """Run every test; return 1 when any failed."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [test_plan_parser, test_overlap_rule, test_stacks, test_dry_run_counts, test_runner_and_resume,
             test_filter_check, test_parse_products, test_inputs_masks_both_sites,
             test_inputs_masks_channels_and_remote_scope, test_mantle_config,
             test_mantle_runner_figures, test_mantle_runner_and_scores, test_site_overrides,
             test_mantle_window_and_memory, test_mantle_resume, test_deferred_configs,
             test_min_band_windows_plan_key, test_remote_only, test_stack_members_by_runs,
             test_stack_pieces]
    failed = 0
    for t in tests:
        print(t.__name__)
        try:
            t()
            print("  PASS")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
