# -*- coding: utf-8 -*-
"""
Unit test for campaign.py's stage-1 overlap gate

A candidate remote is admitted in stage 1 only if its common record with the
local site is at least `overlap.min_fraction` of the local record and at least
`overlap.min_hours`; a candidate that overlaps but falls under either floor is
refused before any run and listed as refused (`refused_remotes`, the dry run's
per-site line, `<campaign>/refused_remotes.csv`, the count in
best_remote.json's `why`; workbench 187). With either floor enough on its own,
FR09 took FR11 (1.6 days of common record) over FR19 (21 days).

The survey is tests/campaign_unit.py's synthetic one (sites on a line 5 km
apart, in the order below), with spans set to the minute; the plan is its
synthetic plan with `overlap: {min_fraction: 0.5, min_hours: 24}`:

    L1 0-400 h; RA2 0-12 h (12 h, 3 % of L1); RA 360-440 h (40 h, 10 %);
    RE 0-400 h (100 %)                                         group G1
    L2 1000-1016.67 h; RB 1006.67-1030 h (10 h, 60 % of L2)    group G2
    L3 2000-2066.67 h; RC 2026.67-2100 h (40 h, 60 % of L3)    group G3

Usage:
    python tests/campaign_overlap_gate_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** (a) RA, overlapping 10 % of L1's record and 40 h, is
eligible for L1 or among its `eligible_remotes` (an OR of the floors admits it on
min_hours alone); (b) RB, at 60 % of L2's record and 10 h, is eligible for L2;
(c) RC, at 60 % and 40 h, is not eligible for L3 or L3's eligible remotes are
not exactly [RC]; (d) `refused_remotes` for L1 is not [RA2, RA] (nearest by
distance first) with overlap 12 h / 0.5 d and 40 h / 1.67 d, the local record
400 h, the fractions 0.03 and 0.10 and the floors "min_fraction 0.5 and
min_hours 24" and "min_fraction 0.5", or for L2 not [RB] at 10 h, 60 %, floor
"min_hours 24", or for L3 not empty (a site with no common record is not a
candidate); (e) the dry run of stage 1 does not print, per site, "stage 1: L1:
1 eligible remote(s), 2 refused by the overlap rule (largest refused RA at 1.7
d of 16.7 d, 10 %)" (the refused candidate with the largest overlap,
not the nearest by km, RA2), the L2 line
with RB at 0.4 d of 0.7 d, 60 %, and "stage 1: L3: 1 eligible remote(s), 0
refused by the overlap rule" with nothing after it; lists a job L1 rr RA or L2 rr RB; does not write <campaign>/refused_remotes.csv
with the columns local, remote, km, overlap_h, overlap_d, local_record_h,
fraction, floor and the refused pairs of every plan site; or writes anything
else; (f) `best_remotes` (from given stage 1 scores) does not give L1's pick
the why "highest score; 2 candidate(s) refused by the overlap rule" and L3's
exactly "highest score", in its return and in best_remote.json; (g) with an OR of the
floors in `is_eligible` (a mutation, monkeypatched), check (a) still passes.

The stored pick (a refused remote is never the
remote of record, whatever the ledger holds): (h) with a ledger holding two
done stage 1 products of L1, L1 rr RA (refused) scoring above L1 rr RE (scores
built by `Campaign.scores` from the EDIs, the order checked first),
`best_remotes` picks RA, or its why is not "highest score; 2 candidate(s)
refused by the overlap rule"; (i) with best_remote.json naming RA for L1, a
dry run of stage 3 does not log "stage 3: L1: stored pick RA is refused by the
overlap rule (1.7 d of 16.7 d): re-chosen", lists a stage 3 job on RA or none
on RE, the pick's why does not begin "stored pick RA refused by the overlap
rule; ", or best_remote.json changes (bytes or mtime); (j) with the drop
removed (`drop_refused` monkeypatched to return the scores whole, a mutation),
(h) still passes.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import campaign_unit as cu  # noqa: E402

cp = cu.cp
T0 = cu.T0
# site: (start, end) in minutes after T0, in survey (= line) order
SPANS_MIN = {"L1": (0, 24000), "RA2": (0, 720), "RA": (21600, 26400), "RE": (0, 24000),
             "L2": (60000, 61000), "RB": (60400, 61800),
             "L3": (120000, 124000), "RC": (121600, 126000)}
GROUPS = {"G1": ["L1", "RA2", "RA", "RE"], "G2": ["L2", "RB"], "G3": ["L3", "RC"]}
CSV_COLUMNS = ["local", "remote", "km", "overlap_h", "overlap_d", "local_record_h", "fraction", "floor"]


def iso_min(m: int) -> str:
    """Return T0 plus m minutes as an ISO UTC string."""
    return (T0 + pd.Timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup(name: str):
    """Write the survey and plan under ROOT/<name>; return (survey_yaml, plan)."""
    root = cu.ROOT / name
    survey_yaml = cu.make_survey(root, {s: (a / 60.0, b / 60.0) for s, (a, b) in SPANS_MIN.items()})
    cfg = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))
    for s, (a, b) in SPANS_MIN.items():  # the spans to the minute (hours like 16.67 do not round-trip)
        cfg["sites"][s]["start"], cfg["sites"][s]["end"] = iso_min(a), iso_min(b)
    survey_yaml.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    plan_path = cu.make_plan(root, groups=GROUPS)
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    raw["overlap"] = {"min_fraction": 0.5, "min_hours": 24}
    plan_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return survey_yaml, cp.load_plan(plan_path)


SURVEY_YAML, PLAN = setup("overlap_gate")
SURVEY = cp.Survey.from_yaml(SURVEY_YAML)
SPANS = cp.site_spans(SURVEY, PLAN.sites)


def check_a() -> None:
    ov = cp.overlap_hours(SPANS["L1"], SPANS["RA"])
    assert abs(ov - 40.0) < 1e-9, ov
    got = cp.is_eligible(PLAN, SPANS, "L1", "RA")
    assert got is False, f"(a) L1 rr RA ({ov:.1f} h, 10 % of 400 h) is eligible under min_fraction 0.5, min_hours 24"
    el = cp.eligible_remotes(PLAN, SURVEY, SPANS, "L1")
    assert el == ["RE"], f"(a) L1's eligible remotes {el}, want ['RE']"
    print(f"(a) L1 rr RA: {ov:.1f} h, 10 % of L1's 400 h -> not eligible; L1's eligible remotes {el}")


def check_b() -> None:
    ov = cp.overlap_hours(SPANS["L2"], SPANS["RB"])
    assert abs(ov - 10.0) < 1e-9, ov
    assert cp.is_eligible(PLAN, SPANS, "L2", "RB") is False, "(b) L2 rr RB (10 h, 60 %) is eligible"
    assert cp.eligible_remotes(PLAN, SURVEY, SPANS, "L2") == [], cp.eligible_remotes(PLAN, SURVEY, SPANS, "L2")
    print(f"(b) L2 rr RB: {ov:.1f} h, 60 % of L2's 16.7 h -> not eligible (under min_hours 24)")


def check_c() -> None:
    ov = cp.overlap_hours(SPANS["L3"], SPANS["RC"])
    assert abs(ov - 40.0) < 1e-9, ov
    assert cp.is_eligible(PLAN, SPANS, "L3", "RC") is True, "(c) L3 rr RC (40 h, 60 %) is not eligible"
    el = cp.eligible_remotes(PLAN, SURVEY, SPANS, "L3")
    assert el == ["RC"], el
    print(f"(c) L3 rr RC: {ov:.1f} h, 60 % of L3's 66.7 h -> eligible; L3's eligible remotes {el}")


def check_d() -> None:
    got = cp.refused_remotes(PLAN, SURVEY, SPANS, "L1")
    assert [r["remote"] for r in got] == ["RA2", "RA"], f"(d) L1 refused {[r['remote'] for r in got]}"
    want = [("RA2", 5.0, 12.0, 0.5, 400.0, 0.03, "min_fraction 0.5 and min_hours 24"),
            ("RA", 10.0, 40.0, 40.0 / 24.0, 400.0, 0.10, "min_fraction 0.5")]
    for row, (remote, km, ov_h, ov_d, rec_h, frac, floor) in zip(got, want):
        assert row["local"] == "L1" and row["remote"] == remote, row
        assert abs(row["km"] - km) < 0.1, (remote, row["km"])
        assert abs(row["overlap_h"] - ov_h) < 1e-6 and abs(row["overlap_d"] - ov_d) < 1e-6, row
        assert abs(row["local_record_h"] - rec_h) < 1e-6 and abs(row["fraction"] - frac) < 1e-9, row
        assert row["floor"] == floor, (remote, row["floor"])
    l2 = cp.refused_remotes(PLAN, SURVEY, SPANS, "L2")
    assert [r["remote"] for r in l2] == ["RB"], l2
    r = l2[0]
    assert abs(r["overlap_h"] - 10.0) < 1e-6 and abs(r["fraction"] - 0.6) < 1e-9 and r["floor"] == "min_hours 24", r
    assert abs(r["local_record_h"] - 1000.0 / 60.0) < 1e-6, r
    l3 = cp.refused_remotes(PLAN, SURVEY, SPANS, "L3")
    assert l3 == [], f"(d) L3 refused {l3} (L1/L2's sites share no record with it)"
    print(f"(d) refused L1: " + "; ".join(f"{x['remote']} {x['km']:.1f} km {x['overlap_h']:.1f} h "
                                         f"({x['overlap_d']:.2f} d) of {x['local_record_h']:.0f} h, "
                                         f"{x['fraction']:.2f}, {x['floor']}" for x in got)
          + f"; L2: RB {r['overlap_h']:.1f} h, {r['fraction']:.2f}, {r['floor']}; L3: none")


def check_e() -> None:
    root = cu.ROOT / "overlap_gate"
    c = cp.Campaign(SURVEY_YAML, PLAN, parallel=1, create=False)
    csv_path = c.dir / "refused_remotes.csv"
    before = {p.relative_to(root) for p in root.rglob("*")}
    _, text = cu.quiet(c.dry_run, [1], PLAN.sites)
    lines = text.splitlines()
    want = {"L1": "stage 1: L1: 1 eligible remote(s), 2 refused by the overlap rule (largest refused RA at 1.7 d "
                  "of 16.7 d, 10 %)",
            "L2": "stage 1: L2: 0 eligible remote(s), 1 refused by the overlap rule (largest refused RB at 0.4 d "
                  "of 0.7 d, 60 %)",
            "L3": "stage 1: L3: 1 eligible remote(s), 0 refused by the overlap rule"}
    for s, w in want.items():
        hit = [ln for ln in lines if f"stage 1: {s}:" in ln]
        assert len(hit) == 1 and hit[0].endswith(w), f"(e) {s}: {hit}, want a line ending {w!r}"
    for job in ("s1_L1_rr-RA ", "s1_L1_rr-RA2", "s1_L2_rr-RB"):
        assert job not in text, f"(e) the dry run lists {job.strip()}"
    assert "s1_L1_rr-RE" in text and "s1_L3_rr-RC" in text, text
    assert csv_path.exists(), f"(e) the dry run did not write {csv_path}"
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        header = rows and list(rows[0].keys())
    assert header == CSV_COLUMNS, header
    pairs = sorted((r["local"], r["remote"]) for r in rows)
    want_pairs = sorted((s, x["remote"]) for s in PLAN.sites for x in cp.refused_remotes(PLAN, SURVEY, SPANS, s))
    assert pairs == want_pairs and ("L1", "RA") in pairs and ("L2", "RB") in pairs, (pairs, want_pairs)
    after = {p.relative_to(root) for p in root.rglob("*")}
    extra = after - before - {csv_path.relative_to(root), *[p.relative_to(root) for p in csv_path.parents
                                                              if root in p.parents]}
    assert not extra, f"(e) the dry run wrote {sorted(map(str, extra))} besides refused_remotes.csv"
    print("(e) dry run: " + " | ".join(next(ln for ln in lines if f"stage 1: {s}:" in ln).split(" ", 2)[2]
                                       for s in want)
          + f"; refused_remotes.csv {len(rows)} row(s), nothing else written")


def check_f() -> None:
    survey_yaml, plan = setup("overlap_gate_best")
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=True)
    df = pd.DataFrame([{"stage": 1, "local": "L1", "remote": "RE", "config": "default", "score": 0.9,
                        "edi": "L1_RE.edi", "provisional": ""},
                       {"stage": 1, "local": "L3", "remote": "RC", "config": "default", "score": 0.8,
                        "edi": "L3_RC.edi", "provisional": ""}])
    out = c.best_remotes(["L1", "L3"], persist=True, df=df)
    stored = json.loads((c.dir / "best_remote.json").read_text(encoding="utf-8"))
    w1 = "highest score; 2 candidate(s) refused by the overlap rule"
    assert out["L1"]["remote"] == "RE" and out["L1"]["why"] == w1, out["L1"]
    assert out["L3"]["remote"] == "RC" and out["L3"]["why"] == "highest score", out["L3"]
    assert stored["L1"]["why"] == w1 and stored["L3"]["why"] == "highest score", stored
    print(f"(f) best_remotes: L1 -> RE, why {out['L1']['why']!r}; L3 -> RC, why {out['L3']['why']!r} "
          "(and so in best_remote.json)")


def check_g() -> None:
    original = cp.is_eligible

    def or_rule(plan, spans, local, remote):  # an OR of the two floors
        if remote == local:
            return False
        ov = cp.overlap_hours(spans[local], spans[remote])
        rec = (spans[local][1] - spans[local][0]).total_seconds() / 3600.0
        return ov > 0 and (ov >= plan.min_fraction * rec - 1e-9 or ov >= plan.min_hours - 1e-9)

    cp.is_eligible = or_rule
    try:
        check_a()
    except AssertionError as exc:
        print(f"(g) mutation (the OR restored) fails (a): {exc}")
    else:
        raise AssertionError("(g) check (a) passed with the OR restored: it cannot fail")
    finally:
        cp.is_eligible = original


def ledger_campaign(name: str):
    """Return a Campaign (create=True) under ROOT/<name> whose ledger holds done L1 rr RA and L1 rr RE.

    RA's EDI is the clean synthetic product, RE's the same with its yx row
    scattered, so the refused RA scores above RE.
    """
    survey_yaml, plan = setup(name)
    c = cp.Campaign(survey_yaml, plan, parallel=1, create=True)
    for remote, bad in (("RA", False), ("RE", True)):
        edi = cu.product_edi(c.dir / "tf" / f"L1_rr-{remote}_default.edi", cu.P_FULL, bad_yx=bad)
        c.ledger.upsert({"run_id": f"s1_L1_rr-{remote}", "stage": 1, "kind": "rr", "group": "G1", "local": "L1",
                         "remote": remote, "config": "default", "status": "done", "edi": str(edi)})
    return survey_yaml, plan, c


def check_h() -> None:
    _, _, c = ledger_campaign("overlap_gate_ledger")
    df = c.scores(write=False)
    sc = {r["remote"]: float(r["score"]) for _, r in df[df["local"] == "L1"].iterrows()}
    assert sc["RA"] > sc["RE"], f"(h) set-up: the refused RA must score above RE: {sc}"
    out = c.best_remotes(["L1"], persist=False, df=df)
    w = "highest score; 2 candidate(s) refused by the overlap rule"
    assert out["L1"]["remote"] == "RE", f"(h) L1's pick is {out['L1']['remote']} (RA is refused): {out['L1']}"
    assert out["L1"]["why"] == w, out["L1"]["why"]
    print(f"(h) ledger: L1 rr RA {sc['RA']:.3f} (refused) over L1 rr RE {sc['RE']:.3f}; pick RE, why {w!r}")


def check_i() -> None:
    survey_yaml, plan, c = ledger_campaign("overlap_gate_stored")
    path = c.dir / "best_remote.json"
    path.write_text(json.dumps({"L1": {"remote": "RA", "score": 0.99, "why": "highest score",
                                       "chosen": "2026-11-08T00:00:00", "score_form": plan.score_form,
                                       "min_coverage": plan.min_coverage}}, indent=2) + "\n", encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    dry = cp.Campaign(survey_yaml, plan, parallel=1, create=False)
    _, text = cu.quiet(dry.dry_run, [3], ["L1"])
    want = "stage 3: L1: stored pick RA is refused by the overlap rule (1.7 d of 16.7 d): re-chosen"
    assert any(ln.endswith(want) for ln in text.splitlines()), f"(i) no line ending {want!r} in:\n{text}"
    assert "s3_L1_rr-RA_" not in text and "s3_L1_rr-RE_" in text, f"(i) stage 3 jobs:\n{text}"
    pick, _ = cu.quiet(dry.best_remotes, ["L1"], persist=False)
    assert pick["L1"]["remote"] == "RE", pick
    assert pick["L1"]["why"].startswith("stored pick RA refused by the overlap rule; "), pick["L1"]["why"]
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before, "(i) the dry run rewrote best_remote.json"
    print(f"(i) stored RA superseded in the dry run: {want!r}; stage 3 on RE, why {pick['L1']['why']!r}; "
          "best_remote.json untouched")


def check_j() -> None:
    original = cp.drop_refused
    cp.drop_refused = lambda s1, refused: s1
    try:
        check_h()
    except AssertionError as exc:
        print(f"(j) mutation (the drop removed) fails (h): {exc}")
    else:
        raise AssertionError("(j) check (h) passed with the drop removed: it cannot fail")
    finally:
        cp.drop_refused = original


def main() -> int:
    """Run every check and return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    check_a()
    check_b()
    check_c()
    check_d()
    check_e()
    check_f()
    check_g()
    check_h()
    check_i()
    check_j()
    print("\nPASS  campaign_overlap_gate_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
