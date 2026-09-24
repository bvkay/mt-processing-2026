# -*- coding: utf-8 -*-
"""
Unit test for scripts/campaign.py

Checks the plan parser, the overlap rule, the stacks, resume, the dry-run
counts, the runner, the filter check, product parsing and the masks
signature. Everything runs on a synthetic survey in a temporary workspace,
without an archive or aurora: five sites on a line with designed record
spans, A 0-48 h, B 2-50 h, C 4-46 h (group G1) and D 40-90 h, E 44-94 h
(group G2), so A/B/C overlap each other by 42-46 h and D/E by 46 h while no
G1-G2 pair reaches 12 h or half of either record. The "raw archives" are
empty files, of which the campaign reads the mtimes. The runner test starts
real child processes (python one-liners that copy a synthetic EDI and print
`wrote <path>`).

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

(2) the overlap rule is wrong at its edges: for a 48 h local, 24 h of overlap
    (exactly 50 %) and 12 h (exactly the floor) must qualify and 11.9 h
    (25 %) must not; for a 10 h local, 6 h (60 %, under 12 h) must qualify;
    no overlap never does; a site is never its own remote;

(3) the stacks are wrong: G1's sites stack the other two members (the local
    never in its own stack); a site alone in its group borrows the group
    with the longest common span (F 0-48 h borrows G1, span 42 h); D, whose
    group has one other member and no other group qualifying, gets none;

(4) resume is wrong: a ledger row marked done with the current inputs and an
    existing EDI is not skipped (no child may start), or it still counts as
    done after the site's filters.yaml entry changed, or when provisional
    (--allow-raw) and the runner runs without --allow-raw;

(5) the dry run does not count, for the synthetic plan with 2 configs:
    stage 0 5 variants; stage 1 8 rr (A, B, C two remotes each, D and E one);
    stage 2 6 stack builds and 6 rr (G1 only); stage 3 10 rr; hours
    (5 x 8 + 6 x 1 + 24 x 8) / 2 slots / 60 = 1.983; or it writes anything;

(6) the runner, on three fake rr jobs of ~2 s with --parallel 2: ever runs
    three at once or never two, does not record every job done with its EDI
    moved into <campaign>/tf/ (and gone from <workspace>/tf), a peak RSS > 0
    and the input signature; a job depending on a failed one is not skipped,
    in the same block or (a resume) when the failure is only in the ledger;
    --max-runs 1 starts more than one; a leftover "running" row whose runner
    is dead does not get its live orphan child killed and the row marked
    interrupted;

(7) the filter check is wrong against the real producer: comments built the
    way ingest builds them (mtproc.noise.apply_filters_arrays' own provenance
    lines joined by "; then ") for C04's declared list (mains then notch) and
    C22's (notch with extra lines) must match, bare and behind build_variant's
    "filters hash <h>; " prefix; a changed q, a swapped order, a missing
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
    (";A:m<8 hex>" and ";B:m<8 hex>"), or do not change when a mask is added
    to B alone (the remote: process_rr applies it too) or then to A; a job
    against a stack STK_Au names a masks hash for the stack; or its command
    carries --no-masks. With runner.masks off: any ":m" hash in the inputs,
    or a command without --no-masks; a config declared as [--masks] whose
    command does not put --masks after the runner's --no-masks, or whose
    inputs name no masks hash; with runner.masks on, a config [--no-masks]
    whose inputs name one; a stage 3 [--masks] job built for A rr B while
    masks.yaml names neither, or not built once it names B.
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

from mtproc.noise import apply_filters_arrays  # noqa: E402

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
    plan = cp.load_plan(make_plan(ROOT / "rule", groups={"G": ["L", "P", "Q", "R", "S", "N", "M"]}))
    spans = {k: (T0 + pd.Timedelta(hours=a), T0 + pd.Timedelta(hours=b)) for k, (a, b) in {
        "L": (0, 48), "P": (24, 80), "Q": (36, 90), "R": (36.1, 90), "S": (0, 10), "N": (60, 70), "M": (4, 100)}.items()}
    cases = [("L", "P", True, "24 h = 50 %"), ("L", "Q", True, "12 h floor"), ("L", "R", False, "11.9 h, 25 %"),
             ("S", "M", True, "6 h = 60 % of a 10 h local"), ("L", "N", False, "no overlap"), ("L", "L", False, "itself")]
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
    for s, others in (("A", ["B", "C"]), ("B", ["A", "C"]), ("C", ["A", "B"])):
        sp = cp.stack_plan(plan, spans, s)
        assert sp and sorted(sp["members"]) == others and not sp["borrowed"], (s, sp)
    sp = cp.stack_plan(plan, spans, "F")
    assert sp and sp["borrowed"] and sp["group"] == "G1" and sorted(sp["members"]) == ["A", "B", "C"], sp
    assert abs(sp["span_h"] - 42.0) < 1e-9, sp["span_h"]
    assert cp.stack_plan(plan, spans, "D") is None, cp.stack_plan(plan, spans, "D")
    print(f"  A <- B C; F (alone) borrows G1: {sp['members']} over {sp['span_h']:.0f} h; D: none")


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
    assert before == after, f"the dry run wrote {set(after) - set(before)}"
    print(f"  counts {got}; {out['hours']:.3f} h; nothing written")


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
        "print(f'2026-09-23 23:00:00.000 | INFO | mtproc.process:process_station:255 - wrote {dest}', flush=True)\n"
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
    quiet(c3.run_block, "deps", [dep])  # its dependency failed in an earlier block: only the ledger knows
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
        f"{esc}[1m2026-09-23T22:56:54.847749+0800 | INFO | mtproc.process | process_station | line: 255 | "
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

    def mask(h0: float) -> dict:
        """Build a 30 min all-band mask from h0 hours after T0."""
        return {"start": iso(h0), "end": iso(h0 + 0.5), "bands": "all", "reason": "test", "found_by": "time"}

    (root / "masks.yaml").write_text(yaml.safe_dump({"B": [mask(10)]}), encoding="utf-8")
    remote_masked = c.inputs(job)
    assert remote_masked != bare, "a mask added to the remote did not change the inputs"
    assert remote_masked.split(";A:m")[1][:8] == bare.split(";A:m")[1][:8], (bare, remote_masked)
    (root / "masks.yaml").write_text(yaml.safe_dump({"A": [mask(20)], "B": [mask(10)]}), encoding="utf-8")
    both_masked = c.inputs(job)
    assert both_masked != remote_masked, "a mask added to the local did not change the inputs"
    stack_sig = c.inputs(stack_job)
    assert ";A:m" in stack_sig and "STK_Au:m" not in stack_sig, stack_sig

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
    print(f"  stage 3 with no masks.yaml entry for A or B: {none}; with one for B: {some}")


def main() -> int:
    """Run every test; return 1 when any failed."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [test_plan_parser, test_overlap_rule, test_stacks, test_dry_run_counts, test_runner_and_resume,
             test_filter_check, test_parse_products, test_inputs_masks_both_sites]
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
