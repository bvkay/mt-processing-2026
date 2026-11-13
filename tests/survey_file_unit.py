# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.survey_file

Edits synthetic survey files built here (LF, CRLF, Kalkaroo-like groups, a
file with no defaults: block, a note with a euro sign, and one file per shape
the writer refuses) and copies of the eight survey files tracked in the
repository, all in the test's scratch folder, and judges every edit by its own
reading of the text: the line diff against the entry span found here, the
own-line comments, the line endings, the parsed file and `Survey.site` of
every other site. No data folder is read.

Usage:
    python tests/survey_file_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

- a request that changes nothing (empty; every key of the first, a middle
  and the last entry set to its own value; a value equal to `defaults:` on a
  site without the key) does not leave the bytes identical, or writes
  survey.yaml.previous;
- setting one key of the first, a middle and the last entry of each file,
  and of each tracked copy, changes a line outside that entry, changes the
  own-line comments, changes a line ending, or changes the parsed entry or
  `Survey.site` of any other site (burst sites of the edited site excluded);
- setting a key to the value of `defaults:` on a site that holds another
  value does not remove the key, or `Survey.site` does not then read the
  default; or a key equal to the default that was not asked about is removed;
- `logger_pid` set on a derived site to the value in `defaults:` is not
  written;
- with `remote: R1` added to `defaults:`, the burst entry asked for
  `remote: R1` does not get the key, or `Survey.site("S01H").remote` is not R1;
- the entry with its own `instrument:` asked for `channels` equal to the
  defaults' does not keep its own `channels`;
- changing `defaults: dipole_length_ex` from 50 to 45 changes
  `Survey.site(s).dipole_length_ex` of any site, its summary does not name
  the sites that keep 50, or the edit changes a line outside the defaults
  block and the entries given the old value; changing `clock_timezone` does
  not list the sites that take it; on the file with no `defaults:` block a
  defaults edit does not insert the block right above `sites:`;
- adding `101`, `yes`, `A.1`, `KD-Z9` does not insert exactly one run of
  lines each after the last entry (below its indent-4 comment, above the
  trailing column-0 comment and blank line) with every old line kept, the
  key equal to the default left out, or `Survey.site_names()` does not hold
  them as text;
- the inline comment `# taped` is not kept when its value changes; the edit
  is not refused when that key is removed, or when a block list holding a
  comment is replaced; the quoted note holding `#` cannot be replaced by a
  note with none; removing the key below an own-line comment does not add
  the "comment above it stays" summary line;
- three tampered new texts (a comment reworded; a comment moved to its
  entry's foot; a comment moved from one edited entry into another, both in
  `made`) are not refused by `check`; the inline comment of a key asked
  reworded is not refused by the comment check;
- a line of an edited entry or of `defaults:` that is not a line of a key
  asked is changed in a new text (a comment moved below its key, or to the
  entry's foot with no comment after it; a value rewritten to the same
  number; trailing blanks on the header; a blank line added) and `check`
  does not refuse it;
- a key or a site entry written twice in a new text (the old key line kept
  above the new one, an unasked key line repeated, a copy of another entry
  or of the new entry at the point of an add) is not refused by `check`;
- `elevation: true` written in place of 1.0 is not refused by `check` (a value
  `Survey.site` accepts, so only the typed comparison can refuse it);
- removing the last key of an entry is not refused; the bare header `S09`
  cannot be given a key at the file's key indent;
- the euro sign of a note is written as an escape when the note is
  rewritten;
- a refused shape (a flow entry on its header, an unquoted numeric name, a
  duplicate site, mixed line endings, a tab, `sites: {}`, anchors, a merge
  key with an alias and one with a flow mapping, two `sites:` lines, a
  value with a line break, a line that is not a key at the entry's indent)
  writes anything, or its message does not name
  the site, the line or the shape; or another entry of the file with the
  flow entry cannot be edited;
- after a write, survey.yaml.previous is not the old bytes, or a `*.tmp`
  file is left; with `os.replace` raising PermissionError twice the third
  try does not succeed; with survey.yaml read-only the commit is not refused
  with the file intact, or after the flag is cleared the next commit fails;
- `commit` with a new text that also changes another site (a tampered
  text) does not refuse with the file untouched;
- the file changed between `plan` and `commit` is not refused.

The mutations this test catches, each made in a copy of the module: (a) values
equal to the default written into the entry; (b) entry ends not
backed off past trailing comments; (c) comment texts taken with the regular
expression ``(^|\\s)#.*``; (d) the line ending taken as LF always; (e) `check`
returning no problem; (f) `NO_LEAN` emptied; (g) the burst exemption removed;
(h) the comment check put back to a count; (i) `same` replaced by ``==``; (j)
`name_text` returning the raw name.
"""

from __future__ import annotations

import difflib
import os
import shutil
import stat
import sys
from pathlib import Path

import yaml
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench import survey_file as sf  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

TRACKED = ["MT_Morocco_Atlas_Mountains", "burra", "curnamona_cube", "hillside_phase1", "hillside_phase2",
           "stuart_shelf_2009", "MT_Vulcan_2022", "MT_Vulcan_2024_25"]

LF = """\
# survey for the writer test
name: t_writer
instrument: lemi423
sample_rate: 1000
data_root: X
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  channels: [ex, ey, hx, hy]
  clock_timezone: UTC
  logger_pid: 10.1234/abcd
sites:
  S01:
    latitude: -31.0
    dipole_length_ex: 52.0  # taped
    serial: '036'
  S02:
    latitude: -31.1
    # measured twice
    longitude: 140.1
    azimuth_ex: 5.0
    # the next key was typed from the sheet
    azimuth_ey: 95.0
  S03:
    latitude: -31.2
    notes: 'a long note # with a hash
      that runs on'
    dipole_length_ey: 50.0
    elevation: 1.0
  S01L:
    derived_from: S01
    sample_rate: 1.0
"""

GROUPS = """\
name: t_groups
instrument: lemi423
sample_rate: 1000
data_root: X
defaults:
  dipole_length_ex: 50.0
  channels:
  - ex
  - ey
  - hx
  - hy
sites:
  # group A: the first line
  S01:
    latitude: -30.0
    longitude: 140.0
  S01H:
    bursts_of: S01
    sample_rate: 24000
  # group B: the second line
  S02:
    latitude: -30.5
    channels:
    - ex
    - ey
  S04:
    instrument: lemi424
    latitude: -30.6
    channels: [ex, ey, hx, hy, hz]
  S05:
    latitude: -30.7
    # checked on site
# end of the sites

"""

BARE = "name: t_bare\ndata_root: X\nsites:\n  S09:\n  S10:\n    latitude: -29.0"

TEXT = """\
name: t_text
data_root: X
sites:
  S01:
    notes: cable 5 € per metre, 20 °C
"""

HEAD = "name: t\ndata_root: X\ndefaults:\n  dipole_length_ex: 50.0\n"
REFUSED = {  # name: (text, request, a fragment the message holds)
    "flow entry": (HEAD + "sites:\n  S01: {latitude: 1.0}\n  S02:\n    latitude: 1.0\n",
                   {"sites": {"S01": {"latitude": 2.0}}}, "'S01' holds its entry on its header line"),
    "numeric name": (HEAD + "sites:\n  101:\n    latitude: 1.0\n", {"sites": {"101": {"latitude": 2.0}}},
                     "site '101' is written as a number"),
    "comment in a block list": (HEAD + "sites:\n  S01:\n    channels:\n    - ex  # first\n    - ey\n",
                                {"sites": {"S01": {"channels": ["hx", "hy"]}}},
                                "the value of channels in S01 carries a comment"),
    "duplicate site": (HEAD + "sites:\n  S01:\n    latitude: 1.0\n  S01:\n    latitude: 3.0\n",
                       {"sites": {"S01": {"latitude": 2.0}}}, "'S01' appears twice"),
    "mixed endings": ("name: t\r\ndata_root: X\nsites:\n  S01:\n    latitude: 1.0\n",
                      {"sites": {"S01": {"latitude": 2.0}}}, "mixes CRLF (1) and LF (4)"),
    "tab": (HEAD + "sites:\n  S01:\n\tlatitude: 1.0\n", {"sites": {"S01": {"latitude": 2.0}}}, "line 7"),
    "sites: {}": (HEAD + "sites: {}\n", {"add": {"S01": {"latitude": 2.0}}}, "'sites: {}'"),
    "anchors": ("name: t\ndata_root: X\ndefaults: &d\n  dipole_length_ex: 50.0\nsites:\n  S01:\n    latitude: 1.0\n",
                {"sites": {"S01": {"latitude": 2.0}}}, "anchors or aliases (line 3)"),
    "merge key": ("name: t\ndata_root: X\nbase: &d\n  latitude: 1.0\nsites:\n  S01:\n    <<: *d\n",
                  {"sites": {"S01": {"latitude": 2.0}}}, "anchors or aliases (line 3)"),
    "merge key without an alias": (HEAD + "sites:\n  S01:\n    latitude: 1.0\n  S02:\n    <<: {serial: '1'}\n",
                                   {"sites": {"S01": {"latitude": 2.0}}}, "merge key (<<) on line 9"),
    "two sites: lines": (HEAD + "sites:\n  S01:\n    latitude: 1.0\nsites:\n  S02:\n    latitude: 1.0\n",
                         {"sites": {"S01": {"latitude": 2.0}}}, "2 top-level 'sites:' lines"),
    "line break": (HEAD + "sites:\n  S01:\n    latitude: 1.0\n", {"sites": {"S01": {"notes": "a\nb"}}},
                   "line break"),
    "not a key line": (HEAD + "sites:\n  S01:\n    latitude: 1.0\n    ? complex\n    : 1\n",
                       {"sites": {"S01": {"latitude": 2.0}}}, "site 'S01': line 8"),
}

SCRATCH = scratch_dir("survey_file_unit")
NOWHERE = SCRATCH / "no_data_root"
failed: list[str] = []
n_checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global n_checks
    n_checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    if not ok:
        failed.append(name)


# ------------------------------------------------------------------ the test's own reading of the text


def put(case: str, text: str) -> Path:
    folder = SCRATCH / case
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    path = folder / "survey.yaml"
    path.write_bytes(text.encode("utf-8"))
    return path


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def split(text: str) -> list[str]:
    return text.split("\n")


def own_comments(text: str) -> list[str]:
    return [line.strip() for line in split(text) if line.lstrip().startswith("#")]


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def is_content(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def block_span(lines: list[str], top: str) -> tuple[int, int]:
    """A top-level block from its header to the next line of content at column 0, less its foot of blank
    lines and column-0 comments."""
    head = next(i for i, line in enumerate(lines) if line.startswith(top + ":"))
    end = next((i for i in range(head + 1, len(lines)) if is_content(lines[i]) and indent(lines[i]) == 0),
               len(lines))
    while end > head + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
        end -= 1
    return head, end


def entry_span(lines: list[str], name: str) -> tuple[int, int]:
    """An entry from its header to the next header, less its foot of blank lines and comments at the
    entry indent or less."""
    head = next(i for i, line in enumerate(lines) if line.startswith("sites:"))
    end = next((i for i in range(head + 1, len(lines)) if is_content(lines[i]) and indent(lines[i]) == 0),
               len(lines))
    n = indent(next(lines[i] for i in range(head + 1, end) if is_content(lines[i])))
    heads = [i for i in range(head + 1, end) if is_content(lines[i]) and indent(lines[i]) == n
             and not lines[i].lstrip().startswith("- ")]
    start = next(i for i in heads if lines[i].strip().split(":")[0].strip("'\"") == name)
    stop = next((i for i in heads if i > start), end)
    while stop > start + 1 and (not lines[stop - 1].strip() or
                                (lines[stop - 1].lstrip().startswith("#") and indent(lines[stop - 1]) <= n)):
        stop -= 1
    return start, stop


def outside(old: str, new: str, spans: list[tuple[int, int]]) -> list:
    """Line changes of new against old that are not inside one of the spans."""
    bad = []
    a, b = split(old), split(new)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert" and any(s < i1 <= e for s, e in spans):
            continue
        if tag != "insert" and any(s <= i1 and i2 <= e for s, e in spans):
            continue
        bad.append((tag, i1, i2, b[j1:j2][:2]))
    return bad


def endings_kept(old: str, new: str) -> bool:
    crlf = "\r\n" in old
    lines = new.split("\n")[:-1]
    return all(line.endswith("\r") == crlf for line in lines)


def survey_of(text: str) -> Survey:
    config = yaml.safe_load(text)
    config["data_root"] = str(NOWHERE)
    return Survey(config, SCRATCH)


def settings(survey: Survey, name) -> object:
    try:
        return vars(survey.site(name))
    except ValueError as exc:
        return f"refused: {exc}"


def others_moved(old: str, new: str, skip: set) -> list:
    before, after = survey_of(old), survey_of(new)
    old_sites, new_sites = yaml.safe_load(old)["sites"] or {}, yaml.safe_load(new)["sites"] or {}
    return [s for s in before.site_names() if s not in skip and
            (settings(before, s) != settings(after, s) or old_sites.get(s) != new_sites.get(s))]


def refused(fn) -> str | None:
    try:
        fn()
    except sf.SurveyFileRefused as exc:
        return str(exc)
    return None


# ------------------------------------------------------------------ the criteria


def test_no_op(files: dict) -> None:
    for label, text in files.items():
        config = yaml.safe_load(text)
        sites = [s for s in (config.get("sites") or {})]
        path = put("noop", text)
        results = [sf.edit(path)]
        for site in {sites[0], sites[len(sites) // 2], sites[-1]} if sites else []:
            own = config["sites"][site] or {}
            results.append(sf.edit(path, sites={site: dict(own)}))
        defaults = config.get("defaults") or {}
        lean = [(k, v) for k, v in defaults.items() if k not in sf.NO_LEAN and k not in sf.OWN_INSTRUMENT_KEYS]
        target = next(((s, k, v) for s in sites for k, v in lean if k not in (config["sites"][s] or {})
                       and "bursts_of" not in (config["sites"][s] or {})), None)
        if target:
            results.append(sf.edit(path, sites={target[0]: {target[1]: target[2]}}))
        same_bytes = read(path) == text
        check(f"no-op on {label}: {len(results)} requests", same_bytes and not any(r.written for r in results)
              and not (path.parent / "survey.yaml.previous").exists(),
              f"bytes same {same_bytes}, written {[r.written for r in results]}, default asked {target}")


def new_value(entry: dict) -> tuple[str, object]:
    for key in ("latitude", "elevation", "serial", "notes", "start"):
        if key in entry:
            value = entry[key]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return key, round(float(value) + 0.001, 6)
            return key, f"{value} trial"
    return "timing", "trial"


def test_one_entry(files: dict) -> None:
    for label, text in files.items():
        config = yaml.safe_load(text)
        entries = config["sites"]
        sites = [s for s, e in entries.items() if "bursts_of" not in (e or {})]
        for site in dict.fromkeys([sites[0], sites[len(sites) // 2], sites[-1]]):
            key, value = new_value(entries[site] or {})
            path = put("one", text)
            try:
                result = sf.edit(path, sites={site: {key: value}})
            except sf.SurveyFileRefused as exc:
                check(f"one key of {site} in {label}", False, f"refused: {exc}")
                continue
            new = read(path)
            bad = outside(text, new, [entry_span(split(text), site)])
            children = {s for s, e in entries.items() if (e or {}).get("bursts_of") == site}
            moved = others_moved(text, new, {site} | children)
            got = (yaml.safe_load(new)["sites"][site] or {}).get(key)
            check(f"one key of {site} in {label} ({key})",
                  result.written and not bad and own_comments(new) == own_comments(text)
                  and endings_kept(text, new) and not moved and sf.same(got, value),
                  f"outside the entry {bad[:2]}, comments same {own_comments(new) == own_comments(text)}, "
                  f"endings kept {endings_kept(text, new)}, other sites moved {moved[:3]}, read back {got!r}")


def test_lean() -> None:
    path = put("lean", LF)
    sf.edit(path, sites={"S02": {"azimuth_ex": 0.0}, "S03": {"latitude": -31.25}})
    new = read(path)
    s02, s03 = yaml.safe_load(new)["sites"]["S02"], yaml.safe_load(new)["sites"]["S03"]
    reads = survey_of(new).site("S02").azimuth_ex
    check("a key set to the default is removed and the site reads the default",
          "azimuth_ex" not in s02 and reads == 0.0, f"S02 {s02}, reads {reads}")
    check("a key equal to the default that was not asked about stays", s03.get("dipole_length_ey") == 50.0, str(s03))

    path = put("lean_pid", LF)
    sf.edit(path, sites={"S01L": {"logger_pid": "10.1234/abcd"}})
    s01l = yaml.safe_load(read(path))["sites"]["S01L"]
    check("logger_pid equal to defaults: is written on a derived site", s01l.get("logger_pid") == "10.1234/abcd",
          str(s01l))

    path = put("burst", GROUPS)
    sf.edit(path, defaults={"remote": "R1"})
    sf.edit(path, sites={"S01H": {"remote": "R1"}})
    new = read(path)
    own = yaml.safe_load(new)["sites"]["S01H"]
    remote = survey_of(new).site("S01H").remote
    check("a burst entry asked for remote equal to defaults: gets the key", own.get("remote") == "R1"
          and remote == "R1", f"entry {own}, Survey.site remote {remote!r}")

    path = put("own_instrument", GROUPS)
    sf.edit(path, sites={"S04": {"channels": ["ex", "ey", "hx", "hy"]}})
    own = yaml.safe_load(read(path))["sites"]["S04"]
    check("an entry with its own instrument keeps channels equal to the defaults'",
          own.get("channels") == ["ex", "ey", "hx", "hy"], str(own))


def test_defaults() -> None:
    path = put("defaults_dipole", LF)
    result = sf.edit(path, defaults={"dipole_length_ex": 45.0})
    new = read(path)
    before, after = survey_of(LF), survey_of(new)
    moved = [s for s in before.site_names()
             if before.site(s).dipole_length_ex != after.site(s).dipole_length_ex]
    keep = next((line for line in result.summary if line.startswith("defaults dipole_length_ex")), "")
    lines = split(LF)
    spans = [block_span(lines, "defaults")] + [entry_span(lines, s) for s in ("S02", "S03", "S01L")]
    bad = outside(LF, new, spans)
    check("defaults dipole_length_ex 50 -> 45 moves no site and names the sites that keep 50",
          not moved and yaml.safe_load(new)["defaults"]["dipole_length_ex"] == 45.0
          and "3 site(s) keep 50.0" in keep and all(s in keep for s in ("S02", "S03", "S01L")) and not bad,
          f"moved {moved}, summary {keep!r}, outside {bad[:2]}")

    result = sf.edit(put("defaults_zone", LF), defaults={"clock_timezone": "Australia/Perth"})
    take = next((line for line in result.summary if line.startswith("defaults clock_timezone")), "")
    check("a defaults change of clock_timezone lists the sites that take it",
          "4 site(s) take the new value" in take and all(s in take for s in ("S01", "S02", "S03", "S01L")), take)

    path = put("defaults_bare", BARE)
    sf.edit(path, defaults={"azimuth_ey": 90.0})
    new = split(read(path))
    at = next(i for i, line in enumerate(new) if line == "defaults:")
    check("no defaults: block: one is inserted right above sites:",
          new[at + 1] == "  azimuth_ey: 90.0" and new[at + 2] == "sites:"
          and new[:at] + new[at + 2:] == split(BARE), str(new))


def test_add() -> None:
    lines = split(GROUPS)
    at = lines.index("    # checked on site") + 1
    for name in ("101", "yes", "A.1", "KD-Z9"):
        path = put("add", GROUPS)
        try:
            result = sf.edit(path, add={name: {"latitude": -30.9, "dipole_length_ex": 50.0}})
        except sf.SurveyFileRefused as exc:
            check(f"add {name}", False, f"refused: {exc}")
            continue
        new = read(path)
        ops = [op for op in difflib.SequenceMatcher(None, lines, split(new), autojunk=False).get_opcodes()
               if op[0] != "equal"]
        one = len(ops) == 1 and ops[0][0] == "insert" and ops[0][1] == at and ops[0][4] - ops[0][3] == 2
        names = survey_of(new).site_names()
        check(f"add {name}: one run of two lines after the last entry, read back as text",
              result.written and one and name in names and all(isinstance(s, str) for s in names)
              and "dipole_length_ex" not in result.made["add"][name], f"changes {ops}, names {names[-2:]}")
    path = put("add_all", GROUPS)
    sf.edit(path, add={name: {"latitude": -30.9} for name in ("101", "yes", "A.1", "KD-Z9")})
    names = survey_of(read(path)).site_names()
    check("four entries added in one edit, in order, as text", names[-4:] == ["101", "yes", "A.1", "KD-Z9"],
          str(names))


def test_comments() -> None:
    path = put("taped", LF)
    sf.edit(path, sites={"S01": {"dipole_length_ex": 53.5}})
    check("the inline comment is kept when its value changes",
          "    dipole_length_ex: 53.5  # taped" in split(read(path)), "")
    for label, value in (("removed", sf.REMOVE), ("set to the default", 50.0)):
        path = put("taped_remove", LF)
        message = refused(lambda: sf.edit(path, sites={"S01": {"dipole_length_ex": value}}))
        check(f"the key with an inline comment {label}: refused, file unchanged",
              message is not None and "dipole_length_ex in S01 carries a comment" in message and read(path) == LF,
              str(message))
    path = put("note", LF)
    message = refused(lambda: sf.edit(path, sites={"S03": {"notes": "short"}}))
    check("the quoted note holding # is replaced by one with none",
          message is None and yaml.safe_load(read(path))["sites"]["S03"]["notes"] == "short", str(message))
    path = put("above", LF)
    result = sf.edit(path, sites={"S02": {"azimuth_ey": sf.REMOVE}})
    note = "S02: removed azimuth_ey; the comment above it stays: check it"
    check("removing the key below an own-line comment adds the summary line",
          note in result.summary and "    # the next key was typed from the sheet" in split(read(path)),
          str(result.summary))


def test_tampered() -> None:
    new, made, _ = sf.plan(LF, sites={"S01": {"timing": "a"}, "S02": {"timing": "b"}})
    lines = split(new)
    comment = "    # measured twice"
    k = lines.index(comment)
    reworded = list(lines)
    reworded[k] = "    # measured three times"
    foot = lines[:k] + lines[k + 1:]
    foot.insert(foot.index("    timing: b") + 1, comment)
    moved = lines[:k] + lines[k + 1:]
    moved.insert(moved.index("  S01:") + 1, comment)
    check("the plain edit of S01 and S02 passes check", sf.check(LF, new, made) == [], "")
    for label, text in (("reworded", reworded), ("moved to its entry's foot", foot),
                        ("moved into another edited entry", moved)):
        problems = sf.check(LF, "\n".join(text), made)
        check(f"a comment {label}: refused by check", bool(problems), str(problems))

    new, made, _ = sf.plan(LF, sites={"S03": {"timing": "c"}})
    tampered = new.replace("    elevation: 1.0\n", "    elevation: true\n")
    problems = sf.check(LF, tampered, made)
    check("elevation: true in place of 1.0: refused by check", tampered != new and bool(problems), str(problems))

    new, made, _ = sf.plan(LF, sites={"S01": {"dipole_length_ex": 53.5}})
    kept_old = new.replace("    dipole_length_ex: 53.5", "    dipole_length_ex: 52.0\n    dipole_length_ex: 53.5")
    repeated = new.replace("    serial: '036'\n", "    serial: '036'\n    serial: '036'\n")
    new_add, made_add, _ = sf.plan(LF, add={"S04": {"latitude": -31.4}})
    copied = new_add + "  S01L:\n    derived_from: S01\n    sample_rate: 1.0\n"
    doubled = new_add + "  S04:\n    latitude: -31.4\n"
    new, made, _ = sf.plan(LF, sites={"S02": {"timing": "x"}})
    below = new.replace("    # measured twice\n    longitude: 140.1\n", "    longitude: 140.1\n    # measured twice\n")
    foot = new.replace("    # the next key was typed from the sheet\n", "").replace(
        "    timing: x\n", "    timing: x\n    # the next key was typed from the sheet\n")
    digits = new.replace("    latitude: -31.1\n", "    latitude: -31.10\n")
    blanks = new.replace("  S02:\n", "  S02:  \n")
    extra = new.replace("    longitude: 140.1\n", "    longitude: 140.1\n\n")
    new_d, made_d, _ = sf.plan(LF, defaults={"clock_timezone": "Australia/Perth"})
    in_defaults = new_d.replace("  azimuth_ex: 0.0\n", "  azimuth_ex: 0.00\n")
    for label, old_made, text in (("a comment moved below the key it describes", made, below),
                                  ("a comment moved to its entry's foot, no comment after it", made, foot),
                                  ("an unasked value of the edited entry rewritten", made, digits),
                                  ("trailing blanks on the edited entry's header", made, blanks),
                                  ("a blank line inserted in the edited entry", made, extra),
                                  ("an unasked value of defaults: rewritten", made_d, in_defaults)):
        problems = sf.check(LF, text, old_made)
        check(f"{label}: refused by check", text not in (new, new_d)
              and any("other than those of the keys asked" in p for p in problems), str(problems))

    new, made, _ = sf.plan(LF, sites={"S01": {"dipole_length_ex": 53.5}})
    retold = new.replace("53.5  # taped", "53.5  # taped twice")
    problems = sf.check(LF, retold, made)
    check("the inline comment of the key asked reworded: refused by check", retold != new
          and any("the comments would change" in p for p in problems), str(problems))
    for label, old_made, text in (("the old key line kept above the new one", made, kept_old),
                                  ("an unasked key line written twice", made, repeated),
                                  ("a copy of the entry S01L at the point of an add", made_add, copied),
                                  ("the new entry written twice", made_add, doubled)):
        problems = sf.check(LF, text, old_made)
        check(f"{label}: refused by check as a key twice", text not in (new, new_add)
              and any("appears twice" in p for p in problems), str(problems))


def test_entries() -> None:
    path = put("last_key", BARE)
    message = refused(lambda: sf.edit(path, sites={"S10": {"latitude": sf.REMOVE}}))
    check("removing the last key of an entry is refused", message is not None and "S10" in message
          and read(path) == BARE, str(message))
    sf.edit(path, sites={"S09": {"latitude": -29.5}})
    new = read(path)
    check("the bare header S09 is given a key at the file's key indent",
          "  S09:\n    latitude: -29.5\n  S10:" in new and yaml.safe_load(new)["sites"]["S09"] == {"latitude": -29.5},
          repr(new))
    path = put("euro", TEXT)
    sf.edit(path, sites={"S01": {"notes": "cable 6 € per metre, 20 °C"}})
    line = next(line for line in split(read(path)) if "notes" in line)
    check("the euro and degree signs are written as characters", "€" in line and "°" in line
          and "\\" not in line, line)


def test_refused_shapes() -> None:
    for label, (text, request, fragment) in REFUSED.items():
        path = put("refused", text)
        message = refused(lambda: sf.edit(path, **request))
        check(f"refused shape, {label}", message is not None and fragment in message and read(path) == text
              and not (path.parent / "survey.yaml.previous").exists(), str(message))
    path = put("flow_other", REFUSED["flow entry"][0])
    sf.edit(path, sites={"S02": {"latitude": 2.0}})
    check("another entry of the file with a flow entry is edited",
          yaml.safe_load(read(path))["sites"]["S02"] == {"latitude": 2.0}, "")


def test_commit() -> None:
    path = put("commit", LF)
    result = sf.edit(path, sites={"S02": {"timing": "one"}})
    previous = path.parent / "survey.yaml.previous"
    check("a write keeps the old bytes in survey.yaml.previous and leaves no temporary file",
          result.written and result.previous == previous and previous.read_bytes() == LF.encode()
          and not list(path.parent.glob("*.tmp")), "")

    calls = []
    real_replace = os.replace

    def flaky(a, b):
        calls.append(b)
        if len(calls) <= 2:
            raise PermissionError("held by another program")
        real_replace(a, b)

    sf.os.replace, sf.REPLACE_WAIT_S = flaky, 0.01
    try:
        result = sf.edit(path, sites={"S02": {"timing": "two"}})
    except sf.SurveyFileRefused as exc:
        result = exc
    finally:
        sf.os.replace = real_replace
    check("os.replace refused twice: the third try writes", not isinstance(result, Exception) and result.written
          and len(calls) == 3 and yaml.safe_load(read(path))["sites"]["S02"]["timing"] == "two", str(calls))

    before = read(path)
    os.chmod(path, stat.S_IREAD)
    try:
        message = refused(lambda: sf.edit(path, sites={"S02": {"timing": "three"}}))
        intact = read(path) == before and not list(path.parent.glob("*.tmp"))
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    check("a read-only survey.yaml: refused with the file intact", message is not None and intact, str(message))
    result = sf.edit(path, sites={"S02": {"timing": "three"}})
    check("after the flag is cleared the next commit writes", result.written
          and yaml.safe_load(read(path))["sites"]["S02"]["timing"] == "three", "")

    path = put("tampered", LF)
    new, made, _ = sf.plan(LF, sites={"S01": {"timing": "x"}})
    tampered = new.replace("    latitude: -31.2\n", "    latitude: -31.3\n")
    message = refused(lambda: sf.commit(path, LF, tampered, made))
    check("commit of a text that also changes another site: refused, file untouched",
          tampered != new and message is not None and read(path) == LF, str(message))

    path = put("meanwhile", LF)
    new, made, _ = sf.plan(LF, sites={"S01": {"timing": "x"}})
    meanwhile = LF.replace("latitude: -31.0", "latitude: -31.05")
    path.write_bytes(meanwhile.encode())
    message = refused(lambda: sf.commit(path, LF, new, made))
    check("the file changed between plan and commit: refused", message is not None
          and "changed while the edit was prepared" in message and read(path) == meanwhile, str(message))


def main() -> int:
    logger.remove()
    print(__doc__.split("**This test fails if**")[1].split("The mutations")[0].strip())
    print()
    tracked = {name: (REPO / "surveys" / name / "survey.yaml").read_bytes().decode("utf-8") for name in TRACKED}
    synthetic = {"lf.yaml": LF, "crlf.yaml": LF.replace("\n", "\r\n"), "groups.yaml": GROUPS, "bare.yaml": BARE,
                 "text.yaml": TEXT}
    tests = [(test_no_op, {**synthetic, **tracked}), (test_one_entry, {**synthetic, **tracked}), (test_lean,),
             (test_defaults,), (test_add,), (test_comments,), (test_tampered,), (test_entries,),
             (test_refused_shapes,), (test_commit,)]
    for test, *args in tests:
        print(f"{test.__name__}:")
        try:
            test(*args)
        except Exception as exc:  # a crash of the writer is a failure of the criterion under test
            check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  survey_file_unit ({len(failed)} of {n_checks} checks failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
