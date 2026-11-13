# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.stacks: stack recipes in stacks.yaml

Recipes are saved to and loaded from stacks.yaml files in this test's
scratch folder (`_scratch.scratch_dir("stacks_unit")`), next to small
survey.yaml files written here; members are resolved over MTH5 archives
written here at 1 Hz (3 h, ex, ey, hx, hy). No Qt. No file of a real
survey is written: the main tree's Nador and Vulcan survey folders are
checked before and after.

Usage:
    MT_WORKBENCH_TEST_SCRATCH=<own folder> PYTHONPATH=<repo>/src python tests/stacks_unit.py

Exit status: 0 when every check ran and passed, 1 when any failed, 2 when
none failed but some could not run yet (the member checks need
`intersite.select_stack(rate=, runs_of=)` and `intersite.NOT_READ`, which the
median builder adds).

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. A recipe with every key saved to an empty folder does not give, byte for
   byte, the file text written literally below (the header, a blank line,
   the block, "\\n" newlines), or does not load back equal to itself.
2. In a hand-written "\\n" stacks.yaml (a header comment, a chart block,
   recipe A with a column-0 comment above it and an indented comment inside
   it, a commented-out recipe followed by a blank line, recipe B with a
   column-0 comment above it), saving a new recipe C and re-saving B changes
   a byte outside B's key line and indented lines; or re-saving A changes a
   byte outside A's; or a "\\r" appears; or the same steps on a "\\r\\n" copy
   leave a bare "\\n" or change a byte outside the saved block; or a
   column-0 comment between a block's indented lines is not kept, just below
   the new block; or a temporary file is left in the folder; or, in a copy
   that starts with a UTF-8 byte-order mark, a save drops the mark or
   changes a byte outside the saved block.
3. The canonical text or the hash of STK_D13 (time_mean) differs from the
   literal text and c3d32023d8f7 (the hash also taken here with hashlib); or
   reordering keys, adding comments, changing notes or the name changes a
   hash; or changing field, use, method, sample_rate, a member, an excluded
   site, start or end by one minute, min_overlap_hours, reject_factor,
   min_members, screen_polarity, member_change or use_filters leaves it
   unchanged; or ``start: 2023-12-10 00:00:00+01:00`` does not load as
   2023-12-09 23:00 UTC with the hash of ``start: 2023-12-09 23:00``, and
   keep that hash and that text through a save and a load.
4. Any invalid recipe loads without a StacksError naming the recipe and the
   key (``<name>, <key>:``), among them ``members: rule`` with time_mean, a
   time list of one site, ``screen_polarity: off`` and a start at 00:00:30;
   or a file with a top-level ``groups:`` key, with two ``STK_A:`` key lines
   (the error naming both line numbers), that is not YAML or not a mapping
   loads; or a save into a file with two ``STK_A:`` lines does not refuse
   and leave the file unchanged; or a save under a survey.yaml site's name
   does not refuse.
5. One invalid recipe hides the valid ones in `load_recipes`.
6. On the scratch survey, `intersite.select_stack` with min_overlap 12 h
   over a 3 h window that the records fill (their runs ending on the
   window's last sample) leaves out a site recording the whole window
   (workbench issue 27); `resolve_members` of a rule recipe differs from
   `intersite.select_stack` with the same arguments; for a list recipe a
   site not listed lacks `NOT_LISTED`, a listed name with no entry lacks
   `NO_ENTRY`, the local loses "the local" or the base "the base"; for a
   time recipe a site whose run ends on the window's last sample or starts
   50 s late is left out, one ending 30 min early is kept, or one written
   as two runs split in the middle is kept (while the rule recipe, which
   sums runs, keeps it); a local at another rate, or a local given to a time
   recipe, does not raise; a base site given to a use: base recipe, a base
   at another rate than a reference recipe's, or a window that ends before
   it starts does not raise a StacksError starting with the recipe's name;
   with a `runs_of` that returns None for one site
   that site's reason is not `intersite.NOT_READ`, the other sites differ
   from the default reads, or any file is opened (h5py.File counted).
7. `intersite_argv` (a reference recipe with its base and window, the
   Process tab's Queue intersite form for a base recipe with and without
   no_filters, tag and dry_run) or `build_argv` differ from the literal
   lists; or a single text as `stacks`, or a start without an end, does
   not raise.
8. `applicable_keys` differs from the literal table for any (method, use)
   pair, or does not raise for (time_mean, base), (band_mean, remote) or an
   unknown method.
9. `stacks.DEFAULT_NIGHT` differs from scripts/gate_masks.py's NIGHT; the
   chart's default references are not the survey.yaml ``remote:`` sites less
   observatories; a saved chart block does not load back; a bad night or a
   single text as references does not raise.
10. A stacks.yaml appears in, or changes in, the Nador or Vulcan survey
    folder of the main tree (or of this tree).
11. A time_coherence recipe of 20 or 29 min is taken, by
    `Recipe.from_mapping` or from a stacks.yaml by `load_recipes`, or is
    refused without naming the recipe, ``end``, its own length and the
    30 min minimum; a time_coherence recipe of 30 min or a time_mean recipe
    of 20 min is refused; or `virtual.member_coherence` over three members
    at 100 Hz fails on 30 min or runs on 29 min.

Also checked: the band_mean rule is process_intersite.py's STACK_RULE
(held literally here); `best_run` keeps the run overlapping
most, the earlier on a tie, none when none overlaps; `provenance` holds the
name, hash, canonical text and rule; an unchanged file is not read twice,
and a same-size rewrite within `masks.RACY_S` of a read is seen.
"""

from __future__ import annotations

import codecs
import hashlib
import inspect
import os
import re
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite, stacks, virtual  # noqa: E402
from mt_workbench.ingest import default_archive_path  # noqa: E402
from mt_workbench.stacks import Recipe, StacksError  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRATCH = scratch_dir("stacks_unit")
MAIN = REPO.parents[2] if REPO.parent.name == "worktrees" else REPO
REAL = sorted({tree / "surveys" / name for tree in (MAIN, REPO)
               for name in ("MT_Morocco_Nador_Geothermal", "MT_Vulcan_2022")})
FAILURES: list[str] = []
NOT_RUN: list[str] = []
MEDIAN = ({"rate", "runs_of"} <= set(inspect.signature(intersite.select_stack).parameters)
          and hasattr(intersite, "NOT_READ"))
WAITING = "select_stack has no rate=/runs_of= or intersite has no NOT_READ yet (median builder)"

HEADER = (
    "# Stack recipes declared on the GUI's Stacks tab (mt_workbench.stacks): per stack, its sites,\n"
    "# field, window and method. scripts/process_intersite.py --stack NAME forms a band recipe inside\n"
    "# each run; scripts/build_stack.py --recipe NAME writes a time recipe's archive\n"
    "# <workspace>/mth5/NAME.h5 for scripts/process_rr.py. Times are UTC, written YYYY-MM-DD HH:MM.\n"
    "# The tab rewrites only the recipe it saves: its key line and its indented lines. Comment lines\n"
    "# that start in column 0 are never touched; comments indented inside a recipe are lost when that\n"
    "# recipe is saved, so keep remarks in notes:.\n"
)
EVERY_KEY = {  # given out of order, with a repeated excluded site
    "notes": "logger-9 coils left out (P2S9, P4S3)", "use_filters": True, "member_change": "constant",
    "screen_polarity": "drop", "min_members": 2, "reject_factor": 25.0, "end": "2023-12-12 06:00",
    "start": "2023-12-10 00:00", "min_overlap_hours": 12.0, "exclude": ["P4S3", "P2S9", "P4S3"], "members": "rule",
    "sample_rate": 1000, "method": "band_median", "use": "base", "field": "H"}
EVERY_KEY_FILE = HEADER + (
    "\n"
    "STK_NADOR_H:\n"
    "  field: H\n"
    "  use: base\n"
    "  method: band_median\n"
    "  sample_rate: 1000.0\n"
    "  members: rule\n"
    "  exclude: [P2S9, P4S3]\n"
    "  min_overlap_hours: 12.0\n"
    "  start: 2023-12-10 00:00\n"
    "  end: 2023-12-12 06:00\n"
    "  reject_factor: 25.0\n"
    "  min_members: 2\n"
    "  screen_polarity: drop\n"
    "  member_change: constant\n"
    "  use_filters: true\n"
    "  notes: logger-9 coils left out (P2S9, P4S3)\n")
D13 = {"field": "H", "use": "remote", "method": "time_mean", "sample_rate": 1000.0,
       "members": ["D10", "D11", "D12", "D14", "D15"], "start": "2023-09-19 19:02", "end": "2023-09-21 07:02",
       "use_filters": True}
D13_TEXT = ('{"end":"2023-09-21T07:02:00Z","field":"H","members":["D10","D11","D12","D14","D15"],'
            '"method":"time_mean","sample_rate":1000.0,"start":"2023-09-19T19:02:00Z","use":"remote",'
            '"use_filters":true}')
D13_HASH = "c3d32023d8f7"
# process_intersite.py's STACK_RULE, held literally
STACK_RULE_5OCT = ("per band, each member's calibrated channel divided by the square root of its median band power "
                   "over the windows; in each window a member whose normalised power exceeds reject_factor times "
                   "the median over the members present is left out, the stack is the mean of the members kept, "
                   "and a window keeping fewer than min_members in either channel is left out of the band")

HAND = (
    "# stacks written by hand\n"
    "# a second header line\n"
    "\n"
    "chart:\n"
    "  references: [RR1, RR2]\n"
    "  night: \"01:00-07:00\"\n"
    "\n"
    "# A: the H base, its lead comment\n"
    "STK_A:\n"
    "  field: H\n"
    "  use: base\n"
    "  # an indented comment inside A\n"
    "  sample_rate: 1.0\n"
    "\n"
    "# STK_OLD:\n"
    "#   field: E\n"
    "#   use: reference\n"
    "#   sample_rate: 1.0\n"
    "\n"
    "# B: the E reference, its lead comment\n"
    "STK_B:\n"
    "  field: E\n"
    "  use: reference\n"
    "  sample_rate: 1.0\n"
    "  members: [M1, M2]\n")
OLD_A = "STK_A:\n  field: H\n  use: base\n  # an indented comment inside A\n  sample_rate: 1.0\n"
OLD_B = "STK_B:\n  field: E\n  use: reference\n  sample_rate: 1.0\n  members: [M1, M2]\n"
NEW_A = ("STK_A:\n  field: H\n  use: base\n  method: band_mean\n  sample_rate: 1.0\n  members: rule\n"
         "  exclude: [M4]\n  min_overlap_hours: 12.0\n  reject_factor: 25.0\n  min_members: 2\n"
         "  screen_polarity: flag\n  member_change: constant\n  use_filters: true\n")
NEW_B = ("STK_B:\n  field: E\n  use: reference\n  method: band_mean\n  sample_rate: 1.0\n  members: [M1, M2, M3]\n"
         "  min_overlap_hours: 12.0\n  reject_factor: 25.0\n  min_members: 2\n  use_filters: true\n")
NEW_C = ("STK_C:\n  field: H\n  use: remote\n  method: time_coherence\n  sample_rate: 1.0\n  members: [M1, M2, M3]\n"
         "  start: 2024-03-01 00:00\n  end: 2024-03-01 03:00\n  use_filters: true\n  notes: built for L\n")
INTERLEAVED = ("STK_D:\n  field: H\n# a remark between D's lines\n  use: base\n\n  sample_rate: 1.0\n"
               "STK_E:\n  field: E\n  use: reference\n  sample_rate: 1.0\n")
NEW_D = ("STK_D:\n  field: H\n  use: base\n  method: band_mean\n  sample_rate: 2.0\n  members: rule\n  exclude: []\n"
         "  min_overlap_hours: 12.0\n  reject_factor: 25.0\n  min_members: 2\n  screen_polarity: flag\n"
         "  member_change: constant\n  use_filters: true\n")

SURVEY_YAML = """name: stacks_unit
instrument: lemi423
sample_rate: 1
data_root: {root}
workspace: {work}
timezone: Africa/Casablanca
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0, remote: RR1}}
  B: {{latitude: -31.01, longitude: 137.0, remote: RR2}}
  M1: {{latitude: -31.1, longitude: 137.1}}
  M2: {{latitude: -31.2, longitude: 137.1}}
  M3: {{latitude: -31.3, longitude: 137.1, remote: OBS}}
  M4: {{latitude: -31.4, longitude: 137.1, remote: STK_NOT_A_SITE}}
  F: {{latitude: -31.5, longitude: 137.1, sample_rate: 2.0}}
  N: {{latitude: -31.6, longitude: 137.1}}
  P: {{latitude: -31.7, longitude: 137.1}}
  T2: {{latitude: -31.8, longitude: 137.1}}
  S30: {{latitude: -31.9, longitude: 137.1}}
  Q: {{latitude: -32.0, longitude: 137.1, remote: RR2}}
  RR1: {{latitude: -32.1, longitude: 137.1}}
  RR2: {{latitude: -32.2, longitude: 137.1}}
  OBS: {{latitude: -32.3, longitude: 137.1, instrument: intermagnet, sample_rate: 1.0}}
"""
FS = 1.0
T0 = pd.Timestamp("2024-03-01 00:00", tz="UTC")
HOUR = pd.Timedelta(hours=1)
# per site: (run start, samples) per run; N has no archive
LAYOUT = {
    **{s: [(T0, 10800)] for s in ("L", "B", "M1", "M2", "M3", "M4", "F", "RR1", "RR2")},
    "P": [(T0, 7200)],                                  # two of the three hours
    "T2": [(T0, 5400), (T0 + 1.5 * HOUR, 5400)],        # two runs split in the middle
    "S30": [(T0, 9000)],                                 # ends 30 min early
    "Q": [(T0 + pd.Timedelta(seconds=50), 10750)],       # starts 50 s late
}


def check(ok, msg: str) -> bool:
    """Print PASS or FAIL and record a failure."""
    print(("PASS  " if ok else "FAIL  ") + msg)
    if not ok:
        FAILURES.append(msg)
    return bool(ok)


def not_run(msg: str) -> None:
    """Print and record a check that cannot run yet."""
    print(f"NOT RUN  {msg} ({WAITING})")
    NOT_RUN.append(msg)


def raised(fn, exc=StacksError) -> str | None:
    """Return the text of the exception `fn` raises, None when it raises none."""
    try:
        fn()
    except exc as error:
        return str(error) or type(error).__name__
    return None


def folder(name: str, sites: str = "  M1: {}\n  M2: {}\n  M3: {}\n  M4: {}\n") -> Path:
    """Return an empty scratch folder holding a minimal survey.yaml."""
    path = SCRATCH / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    (path / "survey.yaml").write_text(f"name: {name}\ndata_root: {(path / 'raw').as_posix()}\nsites:\n{sites}",
                                      encoding="utf-8")
    return path


def real_state() -> dict:
    """Return each real survey folder's stacks.yaml bytes, or None when it has none."""
    return {str(p): ((p / "stacks.yaml").read_bytes() if (p / "stacks.yaml").exists() else None) for p in REAL}


# --- 1, 2: writing ----------------------------------------------------------------------------------------------


def every_key() -> None:
    """Criterion 1."""
    where = folder("c1")
    recipe = Recipe.from_mapping("STK_NADOR_H", EVERY_KEY)
    path = stacks.save_recipe(Survey.from_yaml(where / "survey.yaml"), recipe)
    data = path.read_bytes()
    check(data == EVERY_KEY_FILE.encode("utf-8"),
          "(1) a recipe with every key saves to exactly the literal text" +
          ("" if data == EVERY_KEY_FILE.encode() else f": got\n{data.decode()}"))
    valid, errors = stacks.load_recipes(where)
    check(valid == {"STK_NADOR_H": recipe} and errors == {}, "(1) it loads back equal to itself")
    check(stacks.load_recipe(where / "survey.yaml", "STK_NADOR_H") == recipe, "(1) load_recipe gives it too")
    check(sorted(p.name for p in where.iterdir()) == ["stacks.yaml", "survey.yaml"], "(1) no temporary file left")


def hand_written(newline: str) -> None:
    """Criterion 2 on the hand-written file with the given newline."""
    tag = "LF" if newline == "\n" else "CRLF"
    nl = (lambda s: s.replace("\n", newline))
    where = folder(f"c2_{tag}")
    (where / "stacks.yaml").write_bytes(nl(HAND).encode("utf-8"))
    survey = Survey.from_yaml(where / "survey.yaml")
    valid, errors = stacks.load_recipes(survey)
    check(sorted(valid) == ["STK_A", "STK_B"] and not errors, f"(2 {tag}) the hand-written file loads A and B")
    stacks.save_recipe(survey, Recipe.from_mapping("STK_C", {
        "field": "H", "use": "remote", "method": "time_coherence", "sample_rate": 1, "members": ["M3", "M1", "M2"],
        "start": "2024-03-01 00:00", "end": "2024-03-01 03:00", "notes": "built for L"}))
    stacks.save_recipe(survey, Recipe.from_mapping("STK_B", {
        "field": "E", "use": "reference", "sample_rate": 1.0, "members": ["M1", "M2", "M3"]}))
    data = (where / "stacks.yaml").read_bytes()
    expected = nl(HAND.replace(OLD_B, NEW_B) + "\n" + NEW_C).encode("utf-8")
    check(data == expected, f"(2 {tag}) saving C then re-saving B changes no byte outside B's key and indented "
                            f"lines" + ("" if data == expected else f": got\n{data.decode()}"))
    stacks.save_recipe(survey, Recipe.from_mapping("STK_A", {
        "field": "H", "use": "base", "sample_rate": 1.0, "exclude": ["M4"]}))
    data = (where / "stacks.yaml").read_bytes()
    expected = nl(HAND.replace(OLD_B, NEW_B).replace(OLD_A, NEW_A) + "\n" + NEW_C).encode("utf-8")
    check(data == expected, f"(2 {tag}) re-saving A drops its indented comment and changes no byte outside A" +
          ("" if data == expected else f": got\n{data.decode()}"))
    if newline == "\n":
        check(b"\r" not in data, "(2 LF) no \\r in the file")
    else:
        check(re.search(rb"(?<!\r)\n", data) is None, "(2 CRLF) no bare \\n in the file")
    valid, errors = stacks.load_recipes(survey)
    check(sorted(valid) == ["STK_A", "STK_B", "STK_C"] and not errors, f"(2 {tag}) the file loads A, B and C")
    check(stacks.load_chart(survey) == {"references": ["RR1", "RR2"], "night": "01:00-07:00"},
          f"(2 {tag}) the chart block is read")
    # a column-0 comment between a block's indented lines moves to just below the new block
    (where / "stacks.yaml").write_bytes(nl(INTERLEAVED).encode("utf-8"))
    stacks.save_recipe(survey, Recipe.from_mapping("STK_D", {"field": "H", "use": "base", "sample_rate": 2.0}))
    data = (where / "stacks.yaml").read_bytes()
    expected = nl(NEW_D + "# a remark between D's lines\n" + INTERLEAVED[INTERLEAVED.index("STK_E:"):])
    check(data == expected.encode("utf-8"), f"(2 {tag}) a column-0 comment inside D is kept just below the new "
                                            f"block" + ("" if data == expected.encode() else f": got\n{data.decode()}"))
    left = sorted(p.name for p in where.iterdir())
    check(left == ["stacks.yaml", "survey.yaml"], f"(2 {tag}) no temporary file left: {left}")
    # a file that starts with a byte-order mark (Notepad's "UTF-8 with BOM") keeps it through a save
    bom = codecs.BOM_UTF8
    (where / "stacks.yaml").write_bytes(bom + nl(HAND).encode("utf-8"))
    stacks.save_recipe(survey, Recipe.from_mapping("STK_B", {
        "field": "E", "use": "reference", "sample_rate": 1.0, "members": ["M1", "M2", "M3"]}))
    data = (where / "stacks.yaml").read_bytes()
    expected = bom + nl(HAND.replace(OLD_B, NEW_B)).encode("utf-8")
    check(data == expected, f"(2 {tag}) a byte-order mark is kept through a save, no other byte outside B changed"
                            + ("" if data == expected else f": got {data[:60]!r}"))


# --- 3: the hash ------------------------------------------------------------------------------------------------


def hashes() -> None:
    """Criterion 3."""
    check(hashlib.sha256(D13_TEXT.encode("ascii")).hexdigest()[:12] == D13_HASH,
          "(3) hashlib gives c3d32023d8f7 for the literal canonical text")
    d13 = Recipe.from_mapping("STK_D13", D13)
    check(stacks.canonical_text(d13) == D13_TEXT, f"(3) STK_D13's canonical text: {stacks.canonical_text(d13)}")
    check(stacks.recipe_hash(d13) == D13_HASH, f"(3) STK_D13's hash: {stacks.recipe_hash(d13)}")
    same = {
        "keys reordered": Recipe.from_mapping("STK_D13", dict(reversed(list(D13.items())))),
        "notes changed": Recipe.from_mapping("STK_D13", {**D13, "notes": "a remark"}),
        "renamed": Recipe.from_mapping("STK_OTHER", D13),
        "members reordered and repeated": Recipe.from_mapping("STK_D13", {**D13, "members": ["D15", "D10", "D11",
                                                                                            "D12", "D14", "D10"]}),
    }
    where = folder("c3")
    (where / "stacks.yaml").write_text(
        "# comments added\nSTK_D13:\n  use_filters: true  # an end-of-line comment\n  members: [D15, D14, D12, "
        "D11, D10]\n  # an indented comment\n  end: 2023-09-21 07:02\n  start: 2023-09-19 19:02\n  method: "
        "time_mean\n  sample_rate: 1000\n  field: H\n", encoding="utf-8")
    same["read from a reordered, commented file"] = stacks.load_recipe(where, "STK_D13")
    for what, recipe in same.items():
        check(stacks.recipe_hash(recipe) == D13_HASH, f"(3) hash unchanged: {what}")
    base = Recipe.from_mapping("STK_NADOR_H", EVERY_KEY)
    h0 = stacks.recipe_hash(base)
    one_minute = {"start": "2023-12-10 00:01", "end": "2023-12-12 06:01"}
    changes = {
        "field": {"field": "E"}, "method": {"method": "band_mean"}, "sample_rate": {"sample_rate": 500},
        "exclude": {"exclude": ["P2S9"]}, "start": {"start": one_minute["start"]}, "end": {"end": one_minute["end"]},
        "min_overlap_hours": {"min_overlap_hours": 6.0}, "reject_factor": {"reject_factor": 20.0},
        "min_members": {"min_members": 3}, "screen_polarity": {"screen_polarity": "flag"},
        "member_change": {"member_change": "allow"}, "use_filters": {"use_filters": False},
    }
    for key, change in changes.items():
        other = Recipe.from_mapping("STK_NADOR_H", {**EVERY_KEY, **change})
        check(stacks.recipe_hash(other) != h0, f"(3) hash changes with {key}")
    reference = {k: v for k, v in EVERY_KEY.items() if k not in ("screen_polarity", "member_change")}
    check(stacks.recipe_hash(Recipe.from_mapping("STK_NADOR_H", {**reference, "use": "reference"})) != h0,
          "(3) hash changes with use")
    listed = {"field": "E", "use": "reference", "sample_rate": 1.0, "members": ["M1", "M2"]}
    check(stacks.recipe_hash(Recipe.from_mapping("STK_L", listed)) !=
          stacks.recipe_hash(Recipe.from_mapping("STK_L", {**listed, "members": ["M1", "M3"]})),
          "(3) hash changes with a member of a list")
    check(stacks.recipe_hash(Recipe.from_mapping("STK_D13", {**D13, "members": ["D10", "D11"]})) != D13_HASH,
          "(3) hash changes with a member of a time recipe")
    # a zone-aware start becomes UTC with the same hash, and keeps it through a save and a load
    block = ("STK_Z:\n  field: H\n  use: base\n  sample_rate: 1.0\n  start: {start}\n  end: 2023-12-12 06:00\n")
    where = folder("c3_zone")
    (where / "stacks.yaml").write_text(block.format(start="2023-12-10 00:00:00+01:00"), encoding="utf-8")
    zoned = stacks.load_recipe(where, "STK_Z")
    (where / "stacks.yaml").write_text(block.format(start="2023-12-09 23:00"), encoding="utf-8")
    plain = stacks.load_recipe(where, "STK_Z")
    check(zoned.start == pd.Timestamp("2023-12-09 23:00", tz="UTC"),
          f"(3) start 2023-12-10 00:00:00+01:00 loads as 2023-12-09 23:00 UTC: {zoned.start}")
    check(stacks.recipe_hash(zoned) == stacks.recipe_hash(plain), "(3) the zoned start hashes as the UTC one")
    (where / "stacks.yaml").write_text(block.format(start="2023-12-10 00:00:00+01:00"), encoding="utf-8")
    stacks.save_recipe(Survey.from_yaml(where / "survey.yaml"), zoned)
    text = (where / "stacks.yaml").read_text(encoding="utf-8")
    again = stacks.load_recipe(where, "STK_Z")
    check("  start: 2023-12-09 23:00\n" in text and stacks.recipe_hash(again) == stacks.recipe_hash(plain),
          "(3) after a save and a load the start reads 2023-12-09 23:00 and the hash is kept")


# --- 4, 5: validation -------------------------------------------------------------------------------------------

BAND = "  field: H\n  use: base\n  sample_rate: 1.0\n"
REFERENCE = "  field: E\n  use: reference\n  sample_rate: 1.0\n"
TIME = ("  field: H\n  use: remote\n  method: time_mean\n  sample_rate: 1.0\n  members: [M1, M2]\n"
        "  start: 2024-03-01 00:00\n  end: 2024-03-01 03:00\n")
INVALID = [  # (what, block body, the key the error must name)
    ("an unknown key", BAND + "  colour: red\n", "colour"),
    ("screen_polarity on a reference", REFERENCE + "  screen_polarity: flag\n", "screen_polarity"),
    ("member_change on a reference", REFERENCE + "  member_change: allow\n", "member_change"),
    ("exclude beside a member list", REFERENCE + "  members: [M1, M2]\n  exclude: [M3]\n", "exclude"),
    ("min_overlap_hours on a time method", TIME + "  min_overlap_hours: 2.0\n", "min_overlap_hours"),
    ("reject_factor on a time method", TIME + "  reject_factor: 20.0\n", "reject_factor"),
    ("a time method with field E", TIME.replace("field: H", "field: E"), "field"),
    ("a time method with use base", TIME.replace("use: remote", "use: base"), "use"),
    ("members: rule with time_mean", TIME.replace("members: [M1, M2]", "members: rule"), "members"),
    ("a time list of one site", TIME.replace("members: [M1, M2]", "members: [M1]"), "members"),
    ("a time recipe with no members", TIME.replace("  members: [M1, M2]\n", ""), "members"),
    ("a time recipe with no window", TIME.split("  start:")[0], "start"),
    ("use_filters false on a time method", TIME + "  use_filters: false\n", "use_filters"),
    ("a band method with use remote", BAND.replace("use: base", "use: remote"), "use"),
    ("screen_polarity: off", BAND + "  screen_polarity: off\n", "screen_polarity"),
    ("screen_polarity: none", BAND + "  screen_polarity: none\n", "screen_polarity"),
    ("member_change: sometimes", BAND + "  member_change: sometimes\n", "member_change"),
    ("a start at 00:00:30", BAND + "  start: 2023-12-10 00:00:30\n  end: 2023-12-11 00:00\n", "start"),
    ("an end at 00:00:30 as text", BAND + "  start: 2023-12-10 00:00\n  end: '2023-12-11 00:00:30'\n", "end"),
    ("a start that is not a time", BAND + "  start: soon\n  end: 2023-12-11 00:00\n", "start"),
    ("a start without an end", BAND + "  start: 2023-12-10 00:00\n", "end"),
    ("an end before the start", BAND + "  start: 2023-12-10 00:00\n  end: 2023-12-09 00:00\n", "end"),
    ("no field", "  use: base\n  sample_rate: 1.0\n", "field"),
    ("field X", BAND.replace("field: H", "field: X"), "field"),
    ("no sample_rate", "  field: H\n  use: base\n", "sample_rate"),
    ("a band method with no use", "  field: H\n  sample_rate: 1.0\n", "use"),
    ("sample_rate -1", BAND.replace("sample_rate: 1.0", "sample_rate: -1"), "sample_rate"),
    ("sample_rate as text", BAND.replace("sample_rate: 1.0", "sample_rate: fast"), "sample_rate"),
    ("reject_factor 1", BAND + "  reject_factor: 1.0\n", "reject_factor"),
    ("min_members 0", BAND + "  min_members: 0\n", "min_members"),
    ("min_members 2.5", BAND + "  min_members: 2.5\n", "min_members"),
    ("min_overlap_hours 0", BAND + "  min_overlap_hours: 0\n", "min_overlap_hours"),
    ("a member list shorter than min_members", REFERENCE + "  members: [M1]\n", "members"),
    ("a number among the members", REFERENCE + "  members: [M1, 5]\n", "members"),
    ("members neither rule nor a list", REFERENCE + "  members: all\n", "members"),
    ("exclude that is not a list", BAND + "  exclude: M4\n", "exclude"),
    ("an unknown method", BAND + "  method: band_mode\n", "method"),
    ("use_filters as text", BAND + "  use_filters: maybe\n", "use_filters"),
    ("notes as a number", BAND + "  notes: 5\n", "notes"),
]


def validation() -> None:
    """Criteria 4 and 5."""
    where = folder("c4")
    survey = Survey.from_yaml(where / "survey.yaml")
    for what, body, key in INVALID:
        (where / "stacks.yaml").write_text("STK_X:\n" + body, encoding="utf-8")
        valid, errors = stacks.load_recipes(survey)
        message = errors.get("STK_X", "")
        check(not valid and message.startswith(f"STK_X, {key}:"), f"(4) {what}: refused naming {key}: {message}")
    (where / "stacks.yaml").write_text("STK_a-b:\n" + BAND, encoding="utf-8")
    valid, errors = stacks.load_recipes(survey)
    check(not valid and "STK_a-b" in errors.get("STK_a-b", ""), f"(4) a bad name is refused: {errors}")
    (where / "stacks.yaml").write_text("STK_" + "A" * 37 + ":\n" + BAND, encoding="utf-8")
    check(not stacks.load_recipes(survey)[0], "(4) a 41-character name is refused")
    files = {
        "a top-level groups: key": ("STK_A:\n" + BAND + "groups:\n  north: [M1, M2]\n", "groups"),
        "two STK_A: key lines": ("STK_A:\n" + BAND + "\n# again\nSTK_A:\n" + REFERENCE, "lines 1 and 7"),
        "text that is not YAML": ("STK_A:\n  field: [H\n", "not YAML"),
        "a list, not a mapping": ("- STK_A\n- STK_B\n", "mapping"),
    }
    for what, (text, words) in files.items():
        (where / "stacks.yaml").write_text(text, encoding="utf-8")
        message = raised(lambda: stacks.load_recipes(survey))
        check(message is not None and words in message, f"(4) {what} is a file error: {message}")
    # a save into a file with a file error refuses and writes nothing
    duplicate = ("STK_A:\n" + BAND + "STK_A:\n" + REFERENCE).encode("utf-8")
    (where / "stacks.yaml").write_bytes(duplicate)
    message = raised(lambda: stacks.save_recipe(survey, Recipe.from_mapping("STK_A", {"field": "H", "use": "base",
                                                                                     "sample_rate": 1.0})))
    check(message is not None and (where / "stacks.yaml").read_bytes() == duplicate,
          f"(4) a save into a file with two STK_A lines refuses and leaves it unchanged: {message}")
    sites = folder("c4_site", sites="  STK_M1: {}\n  M2: {}\n")
    message = raised(lambda: stacks.save_recipe(Survey.from_yaml(sites / "survey.yaml"), Recipe.from_mapping(
        "STK_M1", {"field": "H", "use": "base", "sample_rate": 1.0})))
    check(message is not None and not (sites / "stacks.yaml").exists(),
          f"(4) a save under a survey.yaml site's name refuses: {message}")
    # criterion 5: one bad recipe hides nothing
    (where / "stacks.yaml").write_text("STK_GOOD1:\n" + BAND + "STK_BAD:\n" + BAND + "  screen_polarity: off\n"
                                       "STK_GOOD2:\n" + TIME, encoding="utf-8")
    valid, errors = stacks.load_recipes(survey)
    check(list(valid) == ["STK_GOOD1", "STK_GOOD2"] and list(errors) == ["STK_BAD"],
          f"(5) one invalid recipe hides no valid one: valid {list(valid)}, errors {list(errors)}")


# --- 6: members -------------------------------------------------------------------------------------------------

OPENS: list[str] = []
_H5_INIT = h5py.File.__init__


def _counting_init(self, name, *args, **kwargs):
    if isinstance(name, (str, os.PathLike)):  # h5py also builds File objects from open ids
        OPENS.append(str(name))
    _H5_INIT(self, name, *args, **kwargs)


def counted(fn):
    """Return fn() and the files h5py opened meanwhile."""
    OPENS.clear()
    h5py.File.__init__ = _counting_init
    try:
        out = fn()
    finally:
        h5py.File.__init__ = _H5_INIT
    return out, list(OPENS)


def write_runs(work: Path, site: str, runs: list[tuple[pd.Timestamp, int]]) -> Path:
    """Write a site's archive as ingest_site lays it out: ex, ey, hx, hy per run, int32 counts."""
    from mth5.mth5 import MTH5
    from mth5.timeseries import ChannelTS, RunTS

    path = work / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("SYNTH")
        station = m.add_station(site, survey="SYNTH")
        for i, (start, n) in enumerate(runs, 1):
            run_id = f"sr1_{i:04d}"
            chans = []
            for comp in ("ex", "ey", "hx", "hy"):
                typ = "electric" if comp.startswith("e") else "magnetic"
                chans.append(ChannelTS(channel_type=typ, data=np.full(n, i, dtype="int32"),
                                       channel_metadata={typ: {"component": comp, "sample_rate": FS,
                                                               "time_period.start": start.isoformat()}}))
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()
    return path


def build_survey() -> Survey:
    """Write the member survey and its archives (`LAYOUT`); return it."""
    where = SCRATCH / "c6"
    shutil.rmtree(where, ignore_errors=True)
    (where / "raw").mkdir(parents=True)
    (where / "survey.yaml").write_text(SURVEY_YAML.format(root=(where / "raw").as_posix(),
                                                          work=(where / "work").as_posix()), encoding="utf-8")
    for site, runs in LAYOUT.items():
        write_runs(where / "work", site, runs)
    return Survey.from_yaml(where / "survey.yaml")


def members(survey: Survey) -> None:
    """Criterion 6."""
    H, E = ("hx", "hy"), ("ex", "ey")
    lo, hi = int(T0.value), int((T0 + 3 * HOUR).value)
    second = 1_000_000_000
    runs_m1 = intersite.archive_runs(default_archive_path(survey, "M1"), "M1", H)
    check(runs_m1 == [(lo, hi - second)], f"(6 fixture) M1's one run ends on the window's last sample: {runs_m1}")
    runs_t2 = intersite.archive_runs(default_archive_path(survey, "T2"), "T2", H)
    check(len(runs_t2) == 2, f"(6 fixture) T2 holds two runs: {runs_t2}")
    # select_stack with min_overlap 12 h over a 3 h window equal to the records: a run ends at its last sample,
    # so M1 covers the window one sample short; it is a member (workbench issue 27)
    plain = intersite.select_stack(survey, "L", None, lo, hi, H, (), 12.0)
    names = [m["site"] for m in plain[0]]
    check(names == ["B", "M1", "M2", "M3", "M4", "RR1", "RR2"],
          f"(6) select_stack(L, 12 h) over a 3 h window equal to the records keeps the sites recording all of it, "
          f"one sample short at the end (workbench issue 27): {names}; M1: "
          f"{next((d['reason'] for d in plain[1] if d['site'] == 'M1'), 'a member')}")
    window = {"start": "2024-03-01 00:00", "end": "2024-03-01 03:00"}
    rule = Recipe.from_mapping("STK_RULE", {"field": "H", "use": "base", "sample_rate": 1.0, "min_overlap_hours": 2.25,
                                            "exclude": ["M4"], **window})
    listed = Recipe.from_mapping("STK_LIST", {"field": "E", "use": "reference", "sample_rate": 1.0,
                                              "members": ["M1", "M2", "M3", "ZZ"], "min_overlap_hours": 2.0})
    timed = Recipe.from_mapping("STK_TIME", {"field": "H", "use": "remote", "method": "time_mean", "sample_rate": 1.0,
                                             "members": ["M1", "M2", "Q", "S30", "T2", "F", "ZZ"], **window})
    message = raised(lambda: stacks.resolve_members(rule, survey, local="F"))
    check(message is not None, f"(6) a local at another rate raises: {message}")
    message = raised(lambda: stacks.resolve_members(timed, survey, local="L"))
    check(message is not None, f"(6) a local given to a time recipe raises: {message}")
    message = raised(lambda: stacks.resolve_members(listed, survey, local="L"))
    check(message is not None, f"(6) a recipe with no window, given none, raises: {message}")
    for what, call, name in (
            ("a base site given to a use: base recipe",
             lambda: stacks.resolve_members(rule, survey, local="L", base="B"), "STK_RULE"),
            ("a base at another rate (F, 2 Hz) than the reference recipe's",
             lambda: stacks.resolve_members(listed, survey, window=(lo, hi), local="L", base="F"), "STK_LIST"),
            ("a window that ends before it starts",
             lambda: stacks.resolve_members(listed, survey, window=(hi, lo), local="L", base="B"), "STK_LIST")):
        message = raised(call)
        check(message is not None and message.startswith(name), f"(6) {what} raises naming {name}: {message}")
    if not MEDIAN:
        for what in ("rule recipe equals select_stack", "list recipe reasons", "time recipe members",
                     "runs_of None gives NOT_READ and opens no file"):
            not_run(f"(6) {what}")
        return
    got = stacks.resolve_members(rule, survey, local="L")
    want = intersite.select_stack(survey, "L", None, lo, hi, H, ["M4"], 2.25, rate=1.0)
    check(got == want, "(6) rule recipe: resolve_members equals select_stack(rate=1.0) with the same arguments")
    check(got == intersite.select_stack(survey, "L", None, lo, hi, H, ["M4"], 2.25),
          "(6) rule recipe: and select_stack at the local's rate")
    names = [m["site"] for m in got[0]]
    check(names == ["B", "M1", "M2", "M3", "T2", "S30", "Q", "RR1", "RR2"],
          f"(6) rule recipe keeps the sites covering 2.25 h, T2's two runs summed: {names}")
    check(stacks.resolve_members(rule, survey, window=(T0, T0 + 3 * HOUR), local="L") == got,
          "(6) a window given as times gives the recipe's own")
    got_m, got_l = stacks.resolve_members(listed, survey, window=(lo, hi), local="L", base="B")
    reasons = {d["site"]: d["reason"] for d in got_l}
    check([m["site"] for m in got_m] == ["M1", "M2", "M3"], f"(6) list recipe members: {got_m}")
    others = [s for s in survey.site_names() if s not in ("L", "B", "M1", "M2", "M3")]
    check(all(reasons.get(s) == stacks.NOT_LISTED for s in others),
          f"(6) every site off the list reads NOT_LISTED: {[(s, reasons.get(s)) for s in others]}")
    check(reasons.get("ZZ") == stacks.NO_ENTRY, f"(6) a listed name with no entry reads NO_ENTRY: {reasons.get('ZZ')}")
    check(reasons.get("L") == "the local" and reasons.get("B") == "the base",
          f"(6) the local and the base keep their reasons: {reasons.get('L')!r}, {reasons.get('B')!r}")
    tm, tl = stacks.resolve_members(timed, survey)
    names = [m["site"] for m in tm]
    reasons = {d["site"]: d["reason"] for d in tl}
    check("M1" in names and "M2" in names, f"(6) time: sites ending on the window's last sample are kept: {names}")
    check("Q" in names, f"(6) time: a site starting 50 s late is kept: {reasons.get('Q')}")
    check("S30" not in names and "cover" in reasons.get("S30", ""),
          f"(6) time: a site ending 30 min early is left out: {reasons.get('S30')}")
    check("T2" not in names and "cover" in reasons.get("T2", ""),
          f"(6) time: a site of two runs split in the middle is left out: {reasons.get('T2')}")
    check(names == ["M1", "M2", "Q"], f"(6) time recipe members: {names}")
    check(reasons.get("F", "").startswith("2 Hz") and reasons.get("ZZ") == stacks.NO_ENTRY
          and reasons.get("L") == stacks.NOT_LISTED,
          f"(6) time: F at 2 Hz, ZZ no entry, L not listed: {reasons.get('F')!r}, {reasons.get('ZZ')!r}, "
          f"{reasons.get('L')!r}")
    cache = {}
    for site in survey.site_names():
        path = default_archive_path(survey, site)
        if path.exists():
            for roles in (H, E):
                cache[(site, roles)] = intersite.archive_runs(path, site, roles)

    def runs_of(site, path, roles):
        return None if site == "M2" else cache[(site, tuple(roles))]

    (rm, rl), opens = counted(lambda: stacks.resolve_members(rule, survey, local="L", runs_of=runs_of))
    check(not opens, f"(6) runs_of: no file opened ({len(opens)})")
    reasons = {d["site"]: d["reason"] for d in rl}
    check(reasons.get("M2") == intersite.NOT_READ, f"(6) runs_of None gives NOT_READ: {reasons.get('M2')!r}")
    check(rm == [m for m in got[0] if m["site"] != "M2"] and [d for d in rl if d["site"] != "M2"] == got[1],
          "(6) runs_of: every other site as with the default reads")
    (tm2, tl2), opens = counted(lambda: stacks.resolve_members(timed, survey, runs_of=runs_of))
    check(not opens and tm2 == [m for m in tm if m["site"] != "M2"],
          f"(6) runs_of with a time recipe: no file opened ({len(opens)}), the same members less M2")


# --- 7, 8: command lines and keys ----------------------------------------------------------------------------------


def argv() -> None:
    """Criterion 7."""
    py, script, yaml_path = "C:/env/python.exe", "D:/repo/scripts/process_intersite.py", "D:/survey/survey.yaml"
    build = "D:/repo/scripts/build_stack.py"
    window = ("2023-12-10 00:00", "2023-12-12 06:00")
    got = stacks.intersite_argv(py, script, yaml_path, "L", "telluric", ["STK_VULCAN_E"], base="B",
                                start=window[0], end=window[1])
    check(got == [py, script, yaml_path, "L", "B", "2023-12-10 00:00", "2023-12-12 06:00", "--kind", "telluric",
                  "--stack", "STK_VULCAN_E"], f"(7) a reference recipe with its base and window: {got}")
    got = stacks.intersite_argv(py, script, yaml_path, "P4S8", "magnetic", ["STK_NADOR_H"], remote="RR2",
                                start=window[0], end=window[1])
    queue = [py, script, yaml_path, "P4S8", "2023-12-10 00:00", "2023-12-12 06:00", "--kind", "magnetic",
             "--remote", "RR2", "--stack", "STK_NADOR_H"]
    check(got == queue, f"(7) the Queue intersite form for a base recipe: {got}")
    got = stacks.intersite_argv(py, script, yaml_path, "P4S8", "magnetic", ["STK_NADOR_H"], remote="RR2",
                                start=window[0], end=window[1], no_filters=True)
    check(got == queue + ["--no-filters"], f"(7) and with no_filters: {got}")
    got = stacks.intersite_argv(Path(py), Path(script), Path(yaml_path), "L", "telluric", ["STK_B", "STK_E"],
                                tag="t1", dry_run=True)
    check(got == [str(Path(py)), str(Path(script)), str(Path(yaml_path)), "L", "--kind", "telluric", "--stack",
                  "STK_B", "--stack", "STK_E", "--tag", "t1", "--dry-run"], f"(7) two recipes, tag, dry run: {got}")
    got = stacks.build_argv(py, build, yaml_path, "STK_D13")
    check(got == [py, build, yaml_path, "--recipe", "STK_D13", "--overwrite"], f"(7) build_argv: {got}")
    got = stacks.build_argv(py, build, yaml_path, "STK_D13", overwrite=False, check=True)
    check(got == [py, build, yaml_path, "--recipe", "STK_D13", "--check"], f"(7) build_argv check only: {got}")
    check(raised(lambda: stacks.intersite_argv(py, script, yaml_path, "L", "telluric", "STK_B"), TypeError),
          "(7) one text as stacks raises TypeError")
    check(raised(lambda: stacks.intersite_argv(py, script, yaml_path, "L", "telluric", ["STK_B"], start=window[0]),
                 ValueError), "(7) a start without an end raises ValueError")
    check(raised(lambda: stacks.intersite_argv(py, script, yaml_path, "L", "telluric", ["STK_B"], remote=7),
                 TypeError), "(7) a remote that is not text raises TypeError")


BAND_BASE_KEYS = ("field", "use", "method", "sample_rate", "members", "exclude", "min_overlap_hours", "start", "end",
                  "reject_factor", "min_members", "screen_polarity", "member_change", "use_filters", "notes")
BAND_REFERENCE_KEYS = ("field", "use", "method", "sample_rate", "members", "exclude", "min_overlap_hours", "start",
                       "end", "reject_factor", "min_members", "use_filters", "notes")
TIME_KEYS = ("field", "use", "method", "sample_rate", "members", "start", "end", "use_filters", "notes")
KEY_TABLE = {("band_mean", "base"): BAND_BASE_KEYS, ("band_median", "base"): BAND_BASE_KEYS,
             ("band_mean", "reference"): BAND_REFERENCE_KEYS, ("band_median", "reference"): BAND_REFERENCE_KEYS,
             ("time_mean", "remote"): TIME_KEYS, ("time_coherence", "remote"): TIME_KEYS}


def keys() -> None:
    """Criterion 8, and the method table."""
    for (method, use), want in KEY_TABLE.items():
        got = stacks.applicable_keys(method, use)
        check(got == want, f"(8) applicable_keys({method}, {use}): {got}")
    for method in stacks.METHODS:
        for use in stacks.USES:
            if (method, use) not in KEY_TABLE:
                check(raised(lambda: stacks.applicable_keys(method, use)) is not None,
                      f"(8) applicable_keys({method}, {use}) raises")
    check(raised(lambda: stacks.applicable_keys("band_mode", "base")) is not None,
          "(8) applicable_keys of an unknown method raises")
    table = {k: (m.engine, m.uses, m.fields, m.stack, m.weighting) for k, m in stacks.METHODS.items()}
    check(table == {"band_mean": ("band", ("base", "reference"), ("E", "H"), "mean", None),
                    "band_median": ("band", ("base", "reference"), ("E", "H"), "median", None),
                    "time_mean": ("time", ("remote",), ("H",), "mean", "none"),
                    "time_coherence": ("time", ("remote",), ("H",), "mean", "coherence")},
          f"(8) METHODS: {table}")
    check(stacks.KIND_OF_BASE == {"E": "telluric", "H": "magnetic"}, f"(8) KIND_OF_BASE: {stacks.KIND_OF_BASE}")
    check(stacks.METHODS["band_mean"].rule == STACK_RULE_5OCT,
          "band_mean's rule is process_intersite.py's STACK_RULE, unchanged")
    check("the stack is the median of the real parts" in stacks.METHODS["band_median"].rule
          and "the mean of the members kept" not in stacks.METHODS["band_median"].rule,
          "band_median's rule names the marginal median")


# --- 9: the chart and the night -------------------------------------------------------------------------------------


def chart(survey: Survey) -> None:
    """Criterion 9."""
    import gate_masks

    check(stacks.DEFAULT_NIGHT == gate_masks.NIGHT,
          f"(9) DEFAULT_NIGHT {stacks.DEFAULT_NIGHT!r} is gate_masks.NIGHT {gate_masks.NIGHT!r}")
    got = stacks.load_chart(survey)
    check(got == {"references": ["RR1", "RR2"], "night": "01:00-05:00"},
          f"(9) default chart: the remote: sites less the observatory and the non-site, the default night: {got}")
    path = stacks.save_chart(survey, ["RR2", "RR1", "RR2"], "22:00-04:00")
    got = stacks.load_chart(survey.config_dir / "survey.yaml")
    check(got == {"references": ["RR2", "RR1"], "night": "22:00-04:00"}, f"(9) a saved chart block loads back: {got}")
    check(path.read_text(encoding="utf-8") == HEADER + "\nchart:\n  references: [RR2, RR1]\n  night: 22:00-04:00\n",
          f"(9) the chart block's text: {path.read_text(encoding='utf-8')!r}")
    stacks.save_chart(survey, [], "01:00-07:00")
    check(stacks.load_chart(survey) == {"references": [], "night": "01:00-07:00"},
          "(9) an empty reference list is kept as empty, not replaced by the default")
    for bad in ("25:00-01:00", "01:00-01:00", "1:00-5:00", "01:00", 5):
        check(raised(lambda: stacks.save_chart(survey, ["RR1"], bad)) is not None, f"(9) night {bad!r} raises")
    check(raised(lambda: stacks.save_chart(survey, "RR1", "01:00-05:00")) is not None,
          "(9) one text as references raises")


# --- extras --------------------------------------------------------------------------------------------------------


def extras() -> None:
    """best_run, provenance, rule_text and the parse cache."""
    check(stacks.best_run([(20, 30), (0, 10)], 5, 25) == [(0, 10)], "best_run keeps the earlier run on a tie")
    check(stacks.best_run([(0, 5), (10, 30)], 0, 40) == [(10, 30)], "best_run keeps the run overlapping most")
    check(stacks.best_run([(0, 5)], 10, 20) == [], "best_run gives [] when no run overlaps")
    d13 = Recipe.from_mapping("STK_D13", D13)
    check(stacks.provenance(d13) == {"recipe": "STK_D13", "recipe_hash": D13_HASH, "recipe_text": D13_TEXT,
                                     "rule": stacks.METHODS["time_mean"].rule}, "provenance of STK_D13")
    base = Recipe.from_mapping("STK_NADOR_H", EVERY_KEY)
    check(stacks.rule_text(base).endswith("(reject_factor 25, min_members 2, polarity drop, membership constant)"),
          f"rule_text of a base recipe: ...{stacks.rule_text(base)[-80:]}")
    import time

    where = folder("cache")
    path = where / "stacks.yaml"
    path.write_text("STK_A:\n" + BAND, encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))
    reads = []
    read_bytes = Path.read_bytes

    def counting(self):
        if self.name == "stacks.yaml":
            reads.append(str(self))
        return read_bytes(self)

    Path.read_bytes = counting
    try:
        stacks.load_recipes(where)
        stacks.load_recipes(where)
    finally:
        Path.read_bytes = read_bytes
    check(len(reads) == 1, f"an unchanged file is read once for two loads: {len(reads)}")
    path.write_text("STK_A:\n" + BAND, encoding="utf-8")
    first = stacks.load_recipe(where, "STK_A")
    status = path.stat()
    path.write_text("STK_A:\n" + BAND.replace("1.0", "2.0"), encoding="utf-8")
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))
    same_stamp = path.stat().st_mtime_ns == status.st_mtime_ns and path.stat().st_size == status.st_size
    second = stacks.load_recipe(where, "STK_A")
    check(same_stamp and first.sample_rate == 1.0 and second.sample_rate == 2.0,
          f"a same-size rewrite at the same mtime within RACY_S is seen: {first.sample_rate} then "
          f"{second.sample_rate}")


# --- 11: the coherence window -----------------------------------------------------------------------------------

SHORT_BLOCK = ("STK_SHORT:\n  field: H\n  use: remote\n  method: time_coherence\n  sample_rate: 100.0\n"
               "  members: [M1, M2, M3]\n  start: 2024-03-01 00:00\n  end: 2024-03-01 00:{minutes:02d}\n")
COHERENCE = {"field": "H", "use": "remote", "method": "time_coherence", "sample_rate": 100.0,
             "members": ["M1", "M2", "M3"], "start": "2024-03-01 00:00"}


def coherence_window() -> None:
    """Criterion 11."""
    for minutes in (20, 29):
        mapping = {**COHERENCE, "end": f"2024-03-01 00:{minutes:02d}"}
        message = raised(lambda: Recipe.from_mapping("STK_SHORT", mapping)) or ""
        check(message.startswith("STK_SHORT, end:") and f"{minutes} min" in message and "30 min" in message,
              f"(11) a time_coherence recipe of {minutes} min is refused naming the recipe, end, its length and "
              f"the 30 min minimum: {message or 'taken'}")
        where = folder(f"c11_{minutes}")
        (where / "stacks.yaml").write_text(SHORT_BLOCK.format(minutes=minutes), encoding="utf-8")
        valid, errors = stacks.load_recipes(Survey.from_yaml(where / "survey.yaml"))
        check(not valid and message and errors.get("STK_SHORT") == message,
              f"(11) read from stacks.yaml, the {minutes} min recipe gives the same error: {errors or 'none'}")
    for what, mapping in (("a time_coherence recipe of 30 min", {**COHERENCE, "end": "2024-03-01 00:30"}),
                          ("a time_mean recipe of 20 min", {**COHERENCE, "method": "time_mean",
                                                            "end": "2024-03-01 00:20"})):
        message = raised(lambda: Recipe.from_mapping("STK_LONG", mapping))
        check(message is None, f"(11) {what} is taken: {message or 'no error'}")
    # the lengths the recipe takes and refuses, against the coherence the build computes
    rng = np.random.default_rng(11)
    fs = 100.0
    for minutes, runs in ((30, True), (29, False)):
        n = int(minutes * 60 * fs)
        common = rng.standard_normal(n)
        arrays = {m: common + 0.3 * rng.standard_normal(n) for m in ("M1", "M2", "M3")}
        try:
            starts, _gamma2 = virtual.member_coherence(arrays, fs, (virtual.WEIGHT_BAND_S,))
            outcome = f"runs, {len(starts)} chunks"
        except ValueError as exc:
            outcome = f"ValueError: {str(exc).splitlines()[0]}"
        check(outcome.startswith("runs") == runs, f"(11) virtual.member_coherence over three members at 100 Hz "
                                                  f"{'runs' if runs else 'fails'} on {minutes} min: {outcome}")


def main() -> int:
    """Run every check; return the exit status."""
    before = real_state()
    every_key()
    hand_written("\n")
    hand_written("\r\n")
    hashes()
    validation()
    coherence_window()
    survey = build_survey()
    members(survey)
    argv()
    keys()
    chart(survey)
    extras()
    after = real_state()
    check(after == before, f"(10) no stacks.yaml appeared or changed in {', '.join(str(p) for p in REAL)}")
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)" + (f", {len(NOT_RUN)} not run" if NOT_RUN else ""))
        return 1
    if NOT_RUN:
        print(f"NOT COMPLETE: no failures, {len(NOT_RUN)} check(s) not run ({WAITING})")
        return 2
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
