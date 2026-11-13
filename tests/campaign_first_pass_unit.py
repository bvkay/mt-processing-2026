# -*- coding: utf-8 -*-
"""
Unit test for campaign.py's remote rules and plan keys for a survey-wide first pass

The runner's never_remote key, lender rule, candidate cap, rr_flags, empty
stage 2, same-H-source rule and twin rule; this file tests each:

(a) `never_remote: [SITE, ...]`, a top-level plan key naming plan sites that are
    locals only (the SA sites with `h_from`: their H is the lender's):
    `eligible_remotes` and `refused_remotes` never offer them, `load_plan`
    refuses a name that is not a plan site, and the dry run's per-site stage-1
    line ends ", <n> never-remote site(s) left out" when a concurrent one was.
(b) the lender rule: when the survey's entry for the local has `h_from: X`, X is
    not an eligible remote of that local (`is_eligible` False) and
    `refused_remotes` lists it with floor "same H source". `Survey.site(...)`
    exposes `h_from` (mt_workbench.survey.SiteConfig.h_from), so the runner
    reads it from there (`read_lenders`), once per plan.
(c) `stages.remotes.max_candidates: N`: after the gate, stage 1 keeps the N
    nearest eligible candidates by km (ties by name); the others are not
    refused but "beyond the nearest N", listed in
    <campaign>/beyond_cap_remotes.csv (local, remote, km, overlap_h) at plan
    time, counted on the per-site line, and never candidates for
    `best_remotes` even when the ledger holds their products. Absent: no cap.
(d) flags on every rr job.
    `stages.remotes.flags` reaches the stage-1 default runs and the stage-3
    `default-<modes>win` window runs on a site remote, but not a stage-3 config
    run (`Campaign.stage_flags` returns [] for it), so a top-level
    `rr_flags: [...]` serves: every rr job of the plan (stages 1, 2, 3, the
    window runs included) carries it after the plan's --min-band-windows and
    before the stage flags and the config's own flags; validated as stage flags
    are; part of the inputs (";rr_flags <flags>"); shown by the dry run.
(e) stage 2 off: an empty weightings map, `stages.stacks: {weightings: {}}`,
    means "no stacks" (no stage-2 job, no error), while an absent stacks
    block keeps the default (u and w).

The survey is tests/campaign_unit.py's synthetic one: sites on a line 5 km
apart, in this order, E2 moved onto E's position (a distance tie):

    A 0 km, B 5, C 10, D 15, E 20, E2 20, F 30   records 0-100 h   group G1
    X 35, Y 40                                     records 200-300 h group G2

C carries `h_from: D` (channels [ex, ey]); the plans name `never_remote: [B]`.
The test plans and dry-runs the campaign; a dry run writes the campaign's CSVs alone.

Usage:
    python tests/campaign_first_pass_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(a) B is eligible for A, among A's `eligible_remotes` (want exactly [C, D, E,
    E2, F]) or A's `refused_remotes`; `load_plan` accepts `never_remote` naming
    an excluded site (Z), an unknown site, a site twice or a plain string; the
    dry run's stage-1 line of A does not end "5 eligible remote(s), 0 refused by
    the overlap rule, 1 never-remote site(s) left out", or X's line (no
    concurrent never-remote site) carries that clause, or B as a local loses its
    remotes; or with the never_remote test removed from `is_eligible` and
    `refused_remotes` (a mutation) check (a) still passes;
(b) `read_lenders` does not give {C: [D]}; D is eligible for C or among C's
    eligible remotes (want exactly [A, E, E2, F]); C's `refused_remotes` is not
    [D] with floor "same H source" and 100 h overlap; the dry run's
    refused_remotes.csv lacks the row (C, D, "same H source"); D's remotes lose
    C (the lender rule is the local's own, one way: a borrower as a remote is
    `never_remote`'s business); or with the lender test removed (a mutation)
    check (b) still passes;
(c) with `max_candidates: 3`: A's stage-1 jobs are not exactly C, D, E (E kept
    over E2 at the same 20 km by name); any site has more than 3 stage-1 jobs;
    A's line does not end ", 2 beyond the nearest 3"; beyond_cap_remotes.csv is
    missing, has other columns than local, remote, km, overlap_h, or lacks (A,
    E2) and (A, F) with 20.0 / 30.0 km and 100 h; refused_remotes.csv holds a
    beyond-cap pair; `best_remotes` picks A's beyond-cap E2 when the ledger
    holds A rr E2 scoring above A rr C; without the key A keeps all 5 jobs and
    no beyond_cap_remotes.csv is written; `load_plan` accepts 0, -2, "8", true
    or 2.5; or with the beyond-cap drop removed (a mutation) the pick check
    still passes;
(d) with `stages.remotes.flags` alone a stage-3 config run carries them or a
    window run lacks them (the established behaviour, pinned); with
    `rr_flags: [--min-period, "0.2", --notch, "1,2"]` and min_band_windows 2,
    a stage-1 job, a stage-2 rr job on a stack, a stage-3 config job and a
    window run do not each carry --min-period 0.2, --notch 1,2 and
    --min-band-windows 2 exactly once, the rr_flags do not sit before the
    config's own flags, a job's inputs lack ";rr_flags --min-period 0.2 --notch
    1,2", a change of the flags leaves the inputs unchanged, a plan without the
    key puts "rr_flags" into any inputs, the dry run does not show the flags on
    a stage-1 row, or `load_plan` accepts rr_flags with --tag, an unknown flag,
    a positional item or a plain string;
(e) `stages.stacks: {weightings: {}}` raises, leaves weightings non-empty,
    yields any stage-2 job or a dry run whose stage-2 totals are not
    "nothing"; or a plan with no stacks block no longer gets the u and w
    weightings;
(f) (the lender rule generalised to same-H sources, survey keys h_from
    and derived_from, followed transitively) on a
    survey with AD `derived_from: A` and CD `derived_from: C` (C h_from D),
    both in never_remote: `read_lenders` does not give {AD: [A], C: [D], CD:
    [C, D]}; A is eligible for AD, or C or D for CD; AD's refused list is not
    [A] with floor "same H source and twin within 100 m", or CD's not C with
    that floor and D with "same H source" (the D sites sit on their parents'
    coordinates, so a parent is a twin as well); A as a
    local is offered AD (a D site is never a remote); or with derived_from
    ignored (a mutation) check (f) still passes;
(g) (the twin rule: co-located twins are the best
    lenders and the worst remotes) on the base survey with a site A2 placed
    60 m from A: `read_twins` does not give exactly {A: [A2], A2: [A], E: [E2],
    E2: [E]} (E2 sits on E's coordinates, 0 m); A2 is eligible for A or A for
    A2, or E2 for E; A's `refused_remotes` lacks (A2, "twin within 100 m") or
    lists B (5 km, not a twin); A's eligible remotes are not exactly [C, D, E,
    E2, F] (B is never_remote); the dry run's refused_remotes.csv lacks the row
    (A, A2, "twin within 100 m"); or with `read_twins` reading none (a
    mutation) check (g) still passes.

Mutations: (a) empties the loaded plan's never_remote (the key read but acted
on nowhere, which is what removing the test from both functions does); (b)
replaces `read_lenders` with one that reads none; (c) replaces
`capped_remotes` with one that caps nothing.

(a) compares B's remotes as a set: A and C sit 5 km either side of B on the
synthetic line, but their haversine distances differ by float noise, so name
order does not apply. The true tie of (c) (E2 on E's coordinates) keeps its
order check. (e) reads only the dry run's lines after "totals (still to
run):", not the block headers ("stage 2 stacks group G1: 0 job(s) (none)");
with no stage-2 job the totals have no stage-2 line at all, which passes.
"""

from __future__ import annotations

import csv
import sys
import traceback
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import campaign_unit as cu  # noqa: E402  (the synthetic survey and plan; puts scripts/ on the path)

cp = cu.cp
SPANS_H = {"A": (0, 100), "B": (0, 100), "C": (0, 100), "D": (0, 100), "E": (0, 100), "E2": (0, 100),
           "F": (0, 100), "X": (200, 300), "Y": (200, 300)}
GROUPS = {"G1": ["A", "B", "C", "D", "E", "E2", "F"], "G2": ["X", "Y"]}
FLAGS = ["--min-period", "0.2", "--notch", "1,2"]
BEYOND_COLUMNS = ["local", "remote", "km", "overlap_h"]


def make(name: str, **keys):
    """Write the survey and a plan under ROOT/<name> with extra plan keys; return (survey_yaml, plan_path).

    `keys` are top-level plan keys, except `max_candidates`, `remote_flags`
    and `stacks`, which go into the stages block (`stacks=None` removes the
    stacks block). A key whose value is `...` is left out.
    """
    root = cu.ROOT / name
    survey_yaml = cu.make_survey(root, SPANS_H)
    cfg = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))
    cfg["sites"]["E2"]["latitude"] = cfg["sites"]["E"]["latitude"]  # the distance tie
    cfg["sites"]["C"]["h_from"] = "D"
    cfg["sites"]["C"]["channels"] = ["ex", "ey"]
    survey_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    plan_path = cu.make_plan(root, groups=GROUPS, configs={"hamming": ["--taper", "hamming"]})
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    raw["overlap"] = {"min_fraction": 0.5, "min_hours": 24}
    raw["min_band_windows"] = 2
    stages = raw["stages"]
    if "max_candidates" in keys:
        n = keys.pop("max_candidates")
        if n is not ...:
            stages["remotes"]["max_candidates"] = n
    if "remote_flags" in keys:
        stages["remotes"]["flags"] = keys.pop("remote_flags")
    if "stacks" in keys:
        st = keys.pop("stacks")
        if st is None:
            stages.pop("stacks")
        else:
            stages["stacks"] = st
    keys.setdefault("never_remote", ["B"])
    for k, v in keys.items():
        if v is ...:
            raw.pop(k, None)
        else:
            raw[k] = v
    plan_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return survey_yaml, plan_path


def refused_by(plan_path: Path) -> str:
    """Return load_plan's error text for a plan, "" when it loads."""
    try:
        cp.load_plan(plan_path)
    except ValueError as exc:
        return str(exc)
    return ""


def stage1_line(text: str, site: str) -> str:
    """Return the one dry-run line "stage 1: <site>: ..." (asserting there is exactly one)."""
    hit = [ln for ln in text.splitlines() if f"stage 1: {site}:" in ln]
    assert len(hit) == 1, f"stage 1 lines for {site}: {hit}"
    return hit[0]


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Return (header, rows) of a CSV."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


# ------------------------------------------------------------------- (a)

SURVEY_YAML, PLAN_PATH = make("first_pass")
PLAN = cp.load_plan(PLAN_PATH) if not refused_by(PLAN_PATH) else None
SURVEY = cp.Survey.from_yaml(SURVEY_YAML)
SPANS = cp.site_spans(SURVEY, list(SPANS_H))


def need_plan():
    """Return the base plan, failing when load_plan refused it."""
    assert PLAN is not None, f"the base plan (never_remote: [B]) is refused: {refused_by(PLAN_PATH)}"
    return PLAN


def check_a() -> None:
    plan = need_plan()
    assert getattr(plan, "never_remote", None) == ["B"], f"(a) plan.never_remote {getattr(plan, 'never_remote', None)}"
    assert cp.is_eligible(plan, SPANS, "A", "B") is False, "(a) never-remote B is eligible for A"
    el = cp.eligible_remotes(plan, SURVEY, SPANS, "A")
    assert el == ["C", "D", "E", "E2", "F"], f"(a) A's eligible remotes {el}"
    ref = [x["remote"] for x in cp.refused_remotes(plan, SURVEY, SPANS, "A")]
    assert "B" not in ref and ref == [], f"(a) A's refused remotes {ref} (B is never offered, so never refused)"
    el_b = cp.eligible_remotes(plan, SURVEY, SPANS, "B")
    assert sorted(el_b) == ["A", "C", "D", "E", "E2", "F"], f"(a) B as a local: {el_b}"
    for bad, why in (({"never_remote": ["Z"]}, "excluded"), ({"never_remote": ["NOPE"]}, "unknown"),
                     ({"never_remote": ["B", "B"]}, "twice"), ({"never_remote": "B"}, "a string")):
        _, p = make("first_pass_bad_nr", **bad)
        err = refused_by(p)
        assert "never_remote" in err, f"(a) load_plan accepts never_remote {bad['never_remote']!r} ({why}): {err!r}"
    c = cp.Campaign(SURVEY_YAML, plan, parallel=1, create=False)
    _, text = cu.quiet(c.dry_run, [1], plan.sites)
    la = stage1_line(text, "A")
    want = "stage 1: A: 5 eligible remote(s), 0 refused by the overlap rule, 1 never-remote site(s) left out"
    assert la.endswith(want), f"(a) A's line {la!r}, want it to end {want!r}"
    lx = stage1_line(text, "X")
    assert lx.endswith("stage 1: X: 1 eligible remote(s), 0 refused by the overlap rule"), f"(a) X's line {lx!r}"
    assert "s1_B_rr-A" in text and "s1_A_rr-B" not in text, "(a) the dry run's B jobs"
    print(f"(a) never_remote [B]: A's eligible {el}, refused {ref}; B as local {el_b}; load_plan refuses Z, NOPE, "
          f"[B, B] and 'B'; dry run: {la.split(' ', 2)[2]!r}")


def check_a_mutation() -> None:
    """With the never_remote test removed from is_eligible and refused_remotes, (a) must fail."""
    saved = PLAN.never_remote
    PLAN.never_remote = []  # the key read but not acted on: the same as removing both tests
    try:
        check_a_core()
    except AssertionError as exc:
        print(f"(a) mutation (never_remote not applied) fails (a): {exc}")
    else:
        raise AssertionError("(a) check (a) passed with never_remote not applied: it cannot fail")
    finally:
        PLAN.never_remote = saved


def check_a_core() -> None:
    """The eligibility half of (a), for the mutation."""
    assert cp.eligible_remotes(PLAN, SURVEY, SPANS, "A") == ["C", "D", "E", "E2", "F"], \
        f"A's eligible remotes {cp.eligible_remotes(PLAN, SURVEY, SPANS, 'A')}"


# ------------------------------------------------------------------- (b)

def check_b() -> None:
    plan = need_plan()
    lenders = cp.read_lenders(plan, SURVEY)
    assert lenders == {"C": ["D"]}, f"(b) read_lenders {lenders}"
    assert cp.is_eligible(plan, SPANS, "C", "D") is False, "(b) the lender D is eligible for its borrower C"
    el = cp.eligible_remotes(plan, SURVEY, SPANS, "C")
    assert el == ["A", "E", "E2", "F"], f"(b) C's eligible remotes {el}"
    ref = cp.refused_remotes(plan, SURVEY, SPANS, "C")
    assert [x["remote"] for x in ref] == ["D"], f"(b) C's refused {[x['remote'] for x in ref]}"
    assert ref[0]["floor"] == "same H source" and abs(ref[0]["overlap_h"] - 100.0) < 1e-9, ref[0]
    assert "C" in cp.eligible_remotes(plan, SURVEY, SPANS, "D"), "(b) D lost C (the rule is the local's own)"
    c = cp.Campaign(SURVEY_YAML, plan, parallel=1, create=False)
    cu.quiet(c.stage1_jobs, plan.sites)
    _, rows = read_csv(c.dir / "refused_remotes.csv")
    hit = [r for r in rows if r["local"] == "C" and r["remote"] == "D"]
    assert len(hit) == 1 and hit[0]["floor"] == "same H source", f"(b) refused_remotes.csv rows {rows}"
    print(f"(b) C h_from D: read_lenders {lenders}; C's eligible {el}; refused D, floor {ref[0]['floor']!r}, "
          f"{ref[0]['overlap_h']:.0f} h; refused_remotes.csv row (C, D, same H source)")


def check_b_mutation() -> None:
    """With the lender test removed (no lenders read), (b) must fail."""
    original = cp.read_lenders
    saved = PLAN.lenders

    def none(plan, survey):
        plan.lenders = {}
        return {}

    cp.read_lenders = none
    PLAN.lenders = {}
    try:
        assert cp.eligible_remotes(PLAN, SURVEY, SPANS, "C") == ["A", "E", "E2", "F"], \
            f"C's eligible remotes {cp.eligible_remotes(PLAN, SURVEY, SPANS, 'C')}"
    except AssertionError as exc:
        print(f"(b) mutation (the lender rule off) fails (b): {exc}")
    else:
        raise AssertionError("(b) check (b) passed with the lender rule off: it cannot fail")
    finally:
        cp.read_lenders = original
        PLAN.lenders = saved


# ------------------------------------------------------------------- (c)

def cap_campaign(name: str, create: bool = False, **keys):
    """Return (survey_yaml, plan, Campaign) of the plan with max_candidates 3 (or `keys`)."""
    keys.setdefault("max_candidates", 3)
    survey_yaml, path = make(name, **keys)
    err = refused_by(path)
    assert not err, f"(c) the plan is refused: {err}"
    plan = cp.load_plan(path)
    return survey_yaml, plan, cp.Campaign(survey_yaml, plan, parallel=1, create=create)


def check_c() -> None:
    _, plan, c = cap_campaign("first_pass_cap")
    assert getattr(plan, "max_candidates", None) == 3, f"(c) plan.max_candidates {getattr(plan, 'max_candidates', None)}"
    jobs, text = cu.quiet(c.stage1_jobs, plan.sites)
    a = sorted(j.remote for j in jobs if j.local == "A")
    assert a == ["C", "D", "E"], f"(c) A's stage-1 remotes {a}"
    per = {s: sum(j.local == s for j in jobs) for s in plan.sites}
    assert max(per.values()) <= 3, f"(c) stage-1 jobs per site {per}"
    la = stage1_line(text, "A")
    assert la.endswith(", 2 beyond the nearest 3"), f"(c) A's line {la!r}"
    path = c.dir / "beyond_cap_remotes.csv"
    assert path.exists(), f"(c) no {path}"
    header, rows = read_csv(path)
    assert header == BEYOND_COLUMNS, f"(c) beyond_cap_remotes.csv columns {header}"
    got = {(r["local"], r["remote"]): (float(r["km"]), float(r["overlap_h"])) for r in rows}
    for pair, km in ((("A", "E2"), 20.0), (("A", "F"), 30.0)):
        assert pair in got and abs(got[pair][0] - km) < 0.15 and abs(got[pair][1] - 100.0) < 1e-6, (pair, got)
    _, refused = read_csv(c.dir / "refused_remotes.csv")
    both = {(r["local"], r["remote"]) for r in refused} & set(got)
    assert not both, f"(c) pairs both refused and beyond the cap: {both}"
    _, plan0, c0 = cap_campaign("first_pass_nocap", max_candidates=...)
    if hasattr(plan0, "max_candidates"):
        assert plan0.max_candidates is None, plan0.max_candidates
    jobs0, _ = cu.quiet(c0.stage1_jobs, plan0.sites)
    assert sum(j.local == "A" for j in jobs0) == 5, f"(c) without the key A has {sum(j.local == 'A' for j in jobs0)}"
    assert not (c0.dir / "beyond_cap_remotes.csv").exists(), "(c) beyond_cap_remotes.csv written without the key"
    for bad in (0, -2, "8", True, 2.5):
        _, p = make("first_pass_bad_cap", max_candidates=bad)
        err = refused_by(p)
        assert "max_candidates" in err, f"(c) load_plan accepts max_candidates {bad!r}: {err!r}"
    print(f"(c) max_candidates 3: A's stage-1 remotes {a} (E over E2 at 20 km by name), at most "
          f"{max(per.values())} per site; {la.split(' ', 2)[2]!r}; beyond_cap_remotes.csv {len(rows)} row(s), "
          f"(A, E2) and (A, F) in it, none also refused; without the key A keeps 5 and no CSV; load_plan refuses "
          f"0, -2, '8', true, 2.5")


def ledger_cap_campaign(name: str):
    """A create=True campaign whose ledger holds done A rr E2 (clean, beyond the cap) and A rr C (yx scattered)."""
    _, plan, c = cap_campaign(name, create=True)
    for remote, bad in (("E2", False), ("C", True)):
        edi = cu.product_edi(c.dir / "tf" / f"A_rr-{remote}_default.edi", cu.P_FULL, bad_yx=bad)
        c.ledger.upsert({"run_id": f"s1_A_rr-{remote}", "stage": 1, "kind": "rr", "group": "G1", "local": "A",
                         "remote": remote, "config": "default", "status": "done", "edi": str(edi)})
    return c


def check_c_pick() -> None:
    c = ledger_cap_campaign("first_pass_cap_ledger")
    df = c.scores(write=False)
    sc = {r["remote"]: float(r["score"]) for _, r in df[df["local"] == "A"].iterrows()}
    assert sc["E2"] > sc["C"], f"(c) set-up: the beyond-cap E2 must score above C: {sc}"
    out, _ = cu.quiet(c.best_remotes, ["A"], persist=False, df=df)
    assert out["A"]["remote"] == "C", f"(c) A's pick is {out['A']['remote']} (E2 is beyond the nearest 3): {out['A']}"
    print(f"(c) ledger: A rr E2 {sc['E2']:.3f} (beyond the cap) over A rr C {sc['C']:.3f}; pick C")


def check_c_mutation() -> None:
    """With the beyond-cap drop removed from best_remotes (capped_remotes giving no beyond), the pick must fail."""
    original = cp.capped_remotes

    def no_cap(plan, survey, spans, local):
        el = cp.eligible_remotes(plan, survey, spans, local)
        return el, []

    cp.capped_remotes = no_cap
    try:
        check_c_pick()
    except AssertionError as exc:
        print(f"(c) mutation (no beyond-cap drop) fails the pick: {exc}")
    else:
        raise AssertionError("(c) the pick check passed with the beyond-cap drop removed: it cannot fail")
    finally:
        cp.capped_remotes = original


# ------------------------------------------------------------------- (d)

WINDOW = {"D": {"yx": ["2023-09-22T10:00:00Z", "2023-09-23T10:00:00Z"], "merge": True}}


def once(cmd: list[str], what: str) -> None:
    """Assert the rr_flags and the floor appear exactly once each in a command."""
    for flag, value in (("--min-period", "0.2"), ("--notch", "1,2"), ("--min-band-windows", "2")):
        n = cmd.count(flag)
        assert n == 1, f"(d) {what}: {flag} appears {n} time(s): {cmd}"
        i = cmd.index(flag)
        assert cmd[i + 1] == value, f"(d) {what}: {flag} {cmd[i + 1]!r}, want {value!r}"


def check_d_established() -> None:
    """Pins the behaviour read in the code: stages.remotes.flags skip a stage-3 config run."""
    survey_yaml, path = make("first_pass_stageflags", remote_flags=["--window-samples", "256"], windows=WINDOW)
    plan = cp.load_plan(path)
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=False)
    s3 = cu.quiet(c.stage3_site_jobs, "D", "A")[0]
    cfg = next(j for j in s3 if j.config == "hamming")
    win = next(j for j in s3 if j.config == "default-yxwin")
    assert "--window-samples" not in cfg.cmd, f"(d) a stage-3 config run carries stages.remotes.flags: {cfg.cmd}"
    assert "--window-samples" in win.cmd, f"(d) a window run lacks stages.remotes.flags: {win.cmd}"
    print("(d) established: stages.remotes.flags reach the window run (default-yxwin) but not the stage-3 config "
          "run (hamming): Campaign.stage_flags returns [] for a config run, so rr_flags is needed")


def check_d() -> None:
    survey_yaml, path = make("first_pass_rrflags", rr_flags=FLAGS, windows=WINDOW)
    err = refused_by(path)
    assert not err, f"(d) the plan with rr_flags is refused: {err}"
    plan = cp.load_plan(path)
    assert getattr(plan, "rr_flags", None) == FLAGS, f"(d) plan.rr_flags {getattr(plan, 'rr_flags', None)}"
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=False)
    s1 = cu.quiet(c.stage1_jobs, ["A"])[0]
    j1 = next(j for j in s1 if j.remote == "C")
    once(j1.cmd, "stage-1 job")
    j2 = c.rr_job(2, "A", "STK_Au", "default", "s2_A_rr-STK_Au")
    once(j2.cmd, "stage-2 rr job on a stack")
    s3 = cu.quiet(c.stage3_site_jobs, "D", "A")[0]
    j3 = next(j for j in s3 if j.config == "hamming")
    once(j3.cmd, "stage-3 config job")
    assert j3.cmd.index("--min-period") < j3.cmd.index("--taper"), f"(d) rr_flags after the config's flags: {j3.cmd}"
    jw = next(j for j in s3 if j.config == "default-yxwin")
    once(jw.cmd, "window run")
    marker = ";rr_flags --min-period 0.2 --notch 1,2"
    for j, what in ((j1, "stage 1"), (j3, "stage 3"), (jw, "window run")):
        assert marker in c.inputs(j), f"(d) {what} inputs lack {marker!r}: {c.inputs(j)}"
    before = c.inputs(j1)
    plan.rr_flags = ["--min-period", "0.5", "--notch", "1,2"]
    changed = c.inputs(c.rr_job(1, "A", "C", "default", "s1_A_rr-C"))
    plan.rr_flags = list(FLAGS)
    assert changed != before, "(d) a change of rr_flags leaves the inputs unchanged (a resume would not re-run)"
    _, text = cu.quiet(c.dry_run, [1], ["A"])
    row = next((ln for ln in text.splitlines() if "s1_A_rr-C " in ln), "")
    assert "--min-period 0.2 --notch 1,2" in row, f"(d) the dry run's stage-1 row {row!r}"
    survey0, path0 = make("first_pass_norrflags", windows=WINDOW)
    plan0 = cp.load_plan(path0)
    c0 = cp.Campaign(survey0, plan0, parallel=1, create=False)
    jobs0 = [*cu.quiet(c0.stage1_jobs, ["A"])[0], *cu.quiet(c0.stage3_site_jobs, "D", "A")[0]]
    leak = [j.run_id for j in jobs0 if j.kind == "rr" and "rr_flags" in c0.inputs(j)]
    assert not leak, f"(d) without the key these inputs carry rr_flags: {leak}"
    for bad in (["--tag", "x"], ["--no-such-flag"], ["0.2", "--notch", "1,2"], "--min-period 0.2"):
        _, p = make("first_pass_bad_rrflags", rr_flags=bad)
        err = refused_by(p)
        assert "rr_flags" in err, f"(d) load_plan accepts rr_flags {bad!r}: {err!r}"
    print(f"(d) rr_flags {FLAGS}: once each (with --min-band-windows 2) on the stage-1, stage-2 stack, stage-3 "
          f"config and window-run commands, before the config's flags; inputs carry {marker!r} and change with the "
          f"flags; none without the key; the dry run shows them; load_plan refuses --tag, an unknown flag, a "
          f"positional item and a string")


# ------------------------------------------------------------------- (e)

def check_e() -> None:
    survey_yaml, path = make("first_pass_nostacks", stacks={"weightings": {}})
    err = refused_by(path)
    assert not err, f"(e) stacks: {{weightings: {{}}}} is refused: {err}"
    plan = cp.load_plan(path)
    assert plan.weightings == {}, f"(e) an empty weightings map reads as {plan.weightings}"
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=False)
    jobs, _ = cu.quiet(c.stage2_jobs, plan.sites)
    assert jobs == [], f"(e) stage-2 jobs with no weightings: {[j.run_id for j in jobs]}"
    _, text = cu.quiet(c.dry_run, [2], plan.sites)
    tot = [ln for ln in text.split("totals (still to run):")[-1].splitlines() if ln.strip().startswith("stage 2 ")]
    assert all(ln.rstrip().endswith("nothing") for ln in tot), f"(e) dry-run stage-2 totals {tot}"
    assert "s2_" not in text, "(e) the dry run lists a stage-2 job"
    _, path_absent = make("first_pass_absentstacks", stacks=None)
    plan_absent = cp.load_plan(path_absent)
    assert plan_absent.weightings == {"u": "none", "w": "coherence"}, \
        f"(e) a plan without a stacks block gets {plan_absent.weightings} (today's default is u and w)"
    print("(e) stacks: {weightings: {}} loads, weightings {}, no stage-2 job, dry-run stage 2 nothing; a plan "
          "without a stacks block keeps u and w")


# ------------------------------------------------------------------- (f)

def same_h_setup(name: str):
    """Survey + plan with AD derived_from A and CD derived_from C (C h_from D); both in never_remote."""
    root = cu.ROOT / name
    spans = {**SPANS_H, "AD": (0, 100), "CD": (0, 100)}
    survey_yaml = cu.make_survey(root, spans)
    cfg = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))
    cfg["sites"]["E2"]["latitude"] = cfg["sites"]["E"]["latitude"]
    cfg["sites"]["C"]["h_from"] = "D"
    cfg["sites"]["C"]["channels"] = ["ex", "ey"]
    for d, parent in (("AD", "A"), ("CD", "C")):
        cfg["sites"][d].update({"derived_from": parent, "channels": ["ex", "hx", "hy", "hz"],
                                "latitude": cfg["sites"][parent]["latitude"]})
    survey_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    groups = {"G1": [*GROUPS["G1"], "AD", "CD"], "G2": GROUPS["G2"]}
    plan_path = cu.make_plan(root, groups=groups, configs={"hamming": ["--taper", "hamming"]})
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    raw["overlap"] = {"min_fraction": 0.5, "min_hours": 24}
    raw["never_remote"] = ["B", "AD", "CD"]
    plan_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return survey_yaml, cp.load_plan(plan_path)


def check_f() -> None:
    survey_yaml, plan = same_h_setup("first_pass_same_h")
    survey = cp.Survey.from_yaml(survey_yaml)
    spans = cp.site_spans(survey, plan.sites)
    got = cp.read_lenders(plan, survey)
    want = {"AD": ["A"], "C": ["D"], "CD": ["C", "D"]}
    assert {k: sorted(v) for k, v in got.items()} == want, f"(f) read_lenders {got}"
    assert cp.is_eligible(plan, spans, "AD", "A") is False, "(f) the parent A is eligible for its D site AD"
    el_cd = cp.eligible_remotes(plan, survey, spans, "CD")
    assert "C" not in el_cd and "D" not in el_cd, f"(f) CD's eligible remotes {el_cd}"
    ref_ad = cp.refused_remotes(plan, survey, spans, "AD")
    # amended with the twin rule (g): AD sits on A's coordinates, so A is also a twin of AD
    assert [(x["remote"], x["floor"]) for x in ref_ad] == [("A", "same H source and twin within 100 m")],         f"(f) AD refused {ref_ad}"
    ref_cd = {(x["remote"], x["floor"]) for x in cp.refused_remotes(plan, survey, spans, "CD")}
    assert ref_cd == {("C", "same H source and twin within 100 m"), ("D", "same H source")}, f"(f) CD refused {ref_cd}"
    el_a = cp.eligible_remotes(plan, survey, spans, "A")
    assert "AD" not in el_a and "CD" not in el_a, f"(f) A is offered a D site: {el_a}"
    print(f"(f) same-H sources {got}; AD refuses A, CD refuses C and D (floor 'same H source'); A's remotes {el_a}")


def check_f_mutation() -> None:
    """With derived_from ignored (only h_from read), (f) must fail."""
    original = cp.read_lenders

    def h_from_only(plan, survey):
        out = {s: [survey.site(s).h_from] for s in plan.sites if survey.site(s).h_from}
        plan.lenders = out
        return out

    cp.read_lenders = h_from_only
    try:
        check_f()
    except AssertionError as exc:
        print(f"(f) mutation (derived_from ignored) fails (f): {exc}")
    else:
        raise AssertionError("(f) check (f) passed with derived_from ignored: it cannot fail")
    finally:
        cp.read_lenders = original


# ------------------------------------------------------------------- (g)

def twin_setup(name: str):
    """The base survey plus A2, 60 m north of A (a twin); E2 already sits on E's coordinates (0 m)."""
    root = cu.ROOT / name
    spans = {**SPANS_H, "A2": (0, 100)}
    survey_yaml = cu.make_survey(root, spans)
    cfg = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))
    cfg["sites"]["E2"]["latitude"] = cfg["sites"]["E"]["latitude"]
    cfg["sites"]["C"]["h_from"] = "D"
    cfg["sites"]["C"]["channels"] = ["ex", "ey"]
    cfg["sites"]["A2"]["latitude"] = cfg["sites"]["A"]["latitude"] + 0.00054  # ~60 m
    cfg["sites"]["A2"]["longitude"] = cfg["sites"]["A"]["longitude"]
    survey_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    groups = {"G1": [*GROUPS["G1"], "A2"], "G2": GROUPS["G2"]}
    plan_path = cu.make_plan(root, groups=groups, configs={"hamming": ["--taper", "hamming"]})
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    raw["overlap"] = {"min_fraction": 0.5, "min_hours": 24}
    raw["never_remote"] = ["B"]
    plan_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return survey_yaml, cp.load_plan(plan_path)


def check_g() -> None:
    survey_yaml, plan = twin_setup("first_pass_twins")
    survey = cp.Survey.from_yaml(survey_yaml)
    spans = cp.site_spans(survey, plan.sites)
    km = cp._km(survey, "A", "A2")
    assert 0.03 < km < 0.1, f"(g) setup: A-A2 {km * 1000:.0f} m"
    got = cp.read_twins(plan, survey)
    want = {"A": ["A2"], "A2": ["A"], "E": ["E2"], "E2": ["E"]}
    assert {k: sorted(v) for k, v in got.items()} == want, f"(g) read_twins {got}"
    for a, b in (("A", "A2"), ("A2", "A"), ("E", "E2"), ("E2", "E")):
        assert cp.is_eligible(plan, spans, a, b) is False, f"(g) twin {b} is eligible for {a}"
    el = cp.eligible_remotes(plan, survey, spans, "A")
    assert el == ["C", "D", "E", "E2", "F"], f"(g) A's eligible remotes {el}"
    ref = [(x["remote"], x["floor"]) for x in cp.refused_remotes(plan, survey, spans, "A")]
    assert ref == [("A2", "twin within 100 m")], f"(g) A's refused {ref}"
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=False)
    cu.quiet(c.dry_run, [1], ["A"])
    _, rows = read_csv(c.dir / "refused_remotes.csv")
    hit = [r for r in rows if r["local"] == "A" and r["remote"] == "A2"]
    assert len(hit) == 1 and hit[0]["floor"] == "twin within 100 m", f"(g) refused_remotes.csv rows {rows}"
    print(f"(g) twins {got} (A-A2 {km * 1000:.0f} m); A refuses A2 (floor 'twin within 100 m'); A's eligible {el}; "
          f"refused_remotes.csv row (A, A2, twin within 100 m)")


def check_g_mutation() -> None:
    """With read_twins reading none, (g) must fail."""
    original = cp.read_twins

    def none(plan, survey):
        plan.twins = {}
        return {}

    cp.read_twins = none
    try:
        check_g()
    except AssertionError as exc:
        print(f"(g) mutation (the twin rule off) fails (g): {exc}")
    else:
        raise AssertionError("(g) check (g) passed with the twin rule off: it cannot fail")
    finally:
        cp.read_twins = original


CASES = [("a", check_a), ("a mutation", check_a_mutation), ("b", check_b), ("b mutation", check_b_mutation),
         ("c", check_c), ("c pick", check_c_pick), ("c mutation", check_c_mutation),
         ("d established", check_d_established), ("d", check_d), ("e", check_e),
         ("f", check_f), ("f mutation", check_f_mutation), ("g", check_g), ("g mutation", check_g_mutation)]


def main() -> int:
    """Run every case; print each failure's first line; return 0 only when all pass."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    failed = []
    for name, fn in CASES:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - each case reports its own first failing line
            first = (str(exc).splitlines() or [type(exc).__name__])[0]
            print(f"FAIL ({name}): {type(exc).__name__}: {first}")
            if not isinstance(exc, AssertionError):
                traceback.print_exc(limit=3)
            failed.append(name)
    if failed:
        print(f"\nFAIL  campaign_first_pass_unit: {', '.join(failed)}")
        return 1
    print("\nPASS  campaign_first_pass_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
