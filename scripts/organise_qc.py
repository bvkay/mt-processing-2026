# -*- coding: utf-8 -*-
"""
Sort a survey's qc folder into one folder per line and one per site

The workspace's ``qc/`` folder collects every figure, table and investigation
folder side by side. This script plans, and with --apply carries out, a move
of each item into:

- ``qc/<line>/<site>/`` when its name starts with a site of survey.yaml
  (the part before the first ``_``, ``.`` or ``-``). A derived site goes under
  the site it is derived from (``B01L`` under ``B01``), a site named after
  another plus letters goes under that one (``C21new`` and ``C21newL`` under
  ``C21``, ``A19L`` under ``A19``), and a stack ``STK_<site><letters>`` goes
  under the site it serves (``STK_C01u`` under ``C01``). The line is the
  site's first letter, ``lineA`` ... ``lineD``; the R remote stations go
  with line B (``qc/lineB/R01/``). A site
  that is not on a line (the observatory ``EBR``) goes to
  ``qc/survey/<site>/``.
- ``qc/<line>/line/`` for line-level items: names starting ``line<X>_``
  (``lineC_1hz``, ``lineC_ebr``, ``lineA_profile.png``, ``lineA_R``),
  ``line_noise_<X>``, ``lines_<site>`` (the line scan's figures) and
  ``filters_line<X>`` (``line_noise_R`` goes to ``qc/lineB/line/``).
- ``qc/survey/<topic>/`` for the survey-level folders ``merge_products``,
  ``reports``, ``cluster_masks``, ``filter_trials``, ``north_recovery`` and
  ``night_ss``.
- ``qc/unsorted/`` for anything no rule places; the dry run lists them.

Folders move whole, except ``lineC_fx`` (a per-site workbench): its files
that start with a site name go to that site's folder and the rest (the
summaries) to ``qc/lineC/line/lineC_fx/``. Inside a line folder that already
exists (``qc/lineA/``), an item starting with a site name goes to the site's
folder and any other item to ``qc/<line>/line/``; site folders, ``line/``,
``survey/``, ``unsorted/`` and ``_moves.csv`` are left alone, so a second
--apply moves nothing. Two files are kept at the top of ``qc/`` because
``scripts/filter_trial.py --lines`` reads them there: ``lines_<site>.csv``
and ``lines_summary.txt``. An item whose destination
exists is merged when both are folders; otherwise it is reported as a conflict
and left where it is, so existing files are kept.
Only ``qc/`` is touched; ``tf/``, ``mth5/`` and ``campaign/`` keep their
layouts, which the campaign runner and the GUI read.

Without --apply the plan and its counts are printed and nothing changes.
With --apply each item is moved (shutil.move), each move is appended to
``qc/_moves.csv`` (old, new, date; paths relative to the workspace, such as
``qc/C05_ey_psd.png``), and every move recorded in ``_moves.csv`` is then
rewritten in the notebook (``notes/**/*.md``) and in the saved reports
(``*.json``, ``*.md`` and ``manifest.csv`` of the reports folder). A cited
path is rewritten when it is the old path, relative (``qc/...``) or under the
workspace (``<root>\\<workspace>\\qc\\...``), with either separator, followed
by a character that cannot continue a file name; a path inside a moved
folder is rewritten through the folder. A JSON report is read, its strings
rewritten and written back only when one changed. Run
``scripts/harvest_notes.py`` afterwards: it fails on any cited path that
still does not exist.

Usage:
    python scripts/organise_qc.py <survey.yaml> [--qc DIR] [--notes DIR] [--apply]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

SURVEY_TOPICS = ("merge_products", "reports", "cluster_masks", "filter_trials", "north_recovery", "night_ss")
SPLIT_FOLDERS = ("lineC_fx",)
MOVES_CSV = "_moves.csv"
ORGANISED_TOP = ("survey", "unsorted", MOVES_CSV)
LINE_DIR = re.compile(r"^line([A-Z])$")
SEP = re.compile(r"[_.\-]")
KEEP_RE = re.compile(r"^lines_[A-Za-z0-9]+\.csv$|^lines_summary\.txt$")
# a letter whose sites are kept with another line's: the R remotes with line B
HOME_LINE = {"R": "B"}
LINE_RULES = (
    re.compile(r"^line([A-Z])_"),
    re.compile(r"^line_noise_([A-Z])"),
    re.compile(r"^filters_line([A-Z])(?![a-z])"),
)


def survey_sites(survey_yaml: Path) -> tuple[Path, Path, dict]:
    """Return the survey folder, the workspace and the ``sites:`` block of a survey.yaml."""
    with open(survey_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    survey_dir = survey_yaml.resolve().parent
    ws = config.get("workspace")
    return survey_dir, Path(ws) if ws else survey_dir / "work", dict(config.get("sites") or {})


def parent_map(sites: dict) -> dict[str, str]:
    """Return, per site, the site whose folder holds it.

    A site with ``derived_from`` takes its source's parent; a site named after
    another plus letters (``C21new``) takes that one's parent; any other site
    is its own parent.
    """
    names = set(sites)

    def parent(name: str, seen: tuple = ()) -> str:
        source = (sites.get(name) or {}).get("derived_from")
        if source in names and source not in seen:
            return parent(source, seen + (name,))
        stems = [p for p in names if p != name and name.startswith(p) and name[len(p):].isalpha()]
        if stems:
            return parent(max(stems, key=len), seen + (name,))
        return name

    return {n: parent(n) for n in names}


class Rules:
    """The placement rules of one survey (see the module docstring)."""

    def __init__(self, sites: dict):
        self.parents = parent_map(sites)
        self.names = sorted(self.parents, key=len, reverse=True)

    def site_of(self, name: str) -> str | None:
        """Return the parent site an item's name starts with, or None."""
        rest = name[4:] if name.startswith("STK_") else name
        token = SEP.split(rest, 1)[0]
        if token in self.parents:
            return self.parents[token]
        for site in self.names:
            if token.startswith(site) and token[len(site):].isalpha():
                return self.parents[site]
        return None

    @staticmethod
    def site_folder(site: str) -> str:
        """Return a site's folder under qc: ``line<X>/<site>``, or ``survey/<site>`` off the lines."""
        if re.match(r"^[A-Z][0-9]", site):
            return f"line{HOME_LINE.get(site[0], site[0])}/{site}"
        return f"survey/{site}"

    def site_dest(self, site: str, name: str, is_dir: bool) -> str:
        """Return the destination of an item of a site: inside its folder, or the folder itself
        for a folder named after the site (merged into it)."""
        folder = self.site_folder(site)
        return folder if is_dir and name == site else f"{folder}/{name}"

    def line_of(self, name: str) -> str | None:
        """Return the line letter of a line-level item, or None."""
        for rule in LINE_RULES:
            m = rule.match(name)
            if m:
                return HOME_LINE.get(m.group(1), m.group(1))
        if name.startswith("lines_"):
            site = self.site_of(name[len("lines_"):])
            if site is not None and re.match(r"^[A-Z][0-9]", site):
                return HOME_LINE.get(site[0], site[0])
        return None

    def place_top(self, name: str, is_dir: bool) -> tuple[str, str | None]:
        """Return (kind, destination under qc) for an item at the top of qc.

        kind is one of organised, keep, survey, split, line, site, unsorted;
        the destination is None for organised, keep and split.
        """
        if name in ORGANISED_TOP or (is_dir and LINE_DIR.match(name)):
            return "organised", None
        if KEEP_RE.match(name):
            return "keep", None
        if name in SURVEY_TOPICS:
            return "survey", f"survey/{name}"
        if is_dir and name in SPLIT_FOLDERS:
            return "split", None
        letter = self.line_of(name)
        if letter:
            return "line", f"line{letter}/line/{name}"
        site = self.site_of(name)
        if site:
            return "site", self.site_dest(site, name, is_dir)
        return "unsorted", f"unsorted/{name}"

    def place_in_line(self, line: str, name: str, is_dir: bool) -> tuple[str, str | None]:
        """Return (kind, destination under qc) for an item inside ``qc/<line>/``."""
        if name == "line":
            return "organised", None
        site = self.site_of(name)
        if is_dir and site == name and self.site_folder(site) == f"{line}/{name}":
            return "organised", None
        if site:
            return "site", self.site_dest(site, name, is_dir)
        return "line", f"{line}/line/{name}"

    def place_in_split(self, folder: str, name: str, is_dir: bool) -> tuple[str, str]:
        """Return (kind, destination under qc) for an item inside a split folder such as ``lineC_fx``."""
        site = self.site_of(name)
        if site:
            return "site", self.site_dest(site, name, is_dir)
        letter = self.line_of(folder) or "X"
        return "line", f"line{letter}/line/{folder}/{name}"


def plan_moves(qc: Path, rules: Rules) -> dict:
    """Return the placement plan of a qc folder.

    Returns:
        dict: ``moves`` [(src, dst, kind)] as absolute paths, ``keep`` and
        ``unsorted`` [names], ``conflicts`` [(src, dst)].
    """
    plan = {"moves": [], "keep": [], "unsorted": [], "conflicts": []}
    taken: set[Path] = set()

    def add(src: Path, rel: str, kind: str) -> None:
        dst = qc / rel
        if dst in taken:
            plan["conflicts"].append((src, dst))
        elif not dst.exists():
            taken.add(dst)
            plan["moves"].append((src, dst, kind))
        elif src.is_dir() and dst.is_dir():
            # merge: the folder's items go into the existing folder one by one
            for child in sorted(src.iterdir()):
                add(child, f"{rel}/{child.name}", kind)
        else:
            plan["conflicts"].append((src, dst))

    for item in sorted(qc.iterdir()):
        kind, rel = rules.place_top(item.name, item.is_dir())
        if kind == "organised":
            m = LINE_DIR.match(item.name)
            if m and item.is_dir():
                for child in sorted(item.iterdir()):
                    k, r = rules.place_in_line(item.name, child.name, child.is_dir())
                    if k != "organised":
                        add(child, r, k)
            continue
        if kind == "keep":
            plan["keep"].append(item.name)
            continue
        if kind == "split":
            for child in sorted(item.iterdir()):
                k, r = rules.place_in_split(item.name, child.name, child.is_dir())
                add(child, r, k)
            continue
        if kind == "unsorted":
            plan["unsorted"].append(item.name)
        add(item, rel, kind)
    return plan


def n_files(path: Path) -> int:
    """Return the number of files in a folder (recursive), or 1 for a file."""
    if path.is_file():
        return 1
    return sum(len(files) for _root, _dirs, files in os.walk(path))


def group_of(qc: Path, dst: Path) -> str:
    """Return the destination folder a move is counted under (``lineC/C05``, ``lineC/line``,
    ``survey/reports``, ``unsorted``)."""
    parts = dst.relative_to(qc).parts
    return "unsorted" if parts[0] == "unsorted" else "/".join(parts[:2])


def read_moves(qc: Path) -> list[dict]:
    """Return the rows of ``qc/_moves.csv`` (old, new, date), or [] when there is none."""
    path = qc / MOVES_CSV
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_moves(qc: Path, rows: list[dict]) -> None:
    """Append rows to ``qc/_moves.csv``, writing its header when the file is new."""
    path = qc / MOVES_CSV
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["old", "new", "date"])
        if new:
            writer.writeheader()
        writer.writerows(rows)


def rel_path(workspace: Path, path: Path) -> str:
    """Return a path relative to the workspace with forward slashes (``qc/...``)."""
    return path.relative_to(workspace).as_posix()


def apply_plan(plan: dict, qc: Path, workspace: Path) -> tuple[list[dict], list[str]]:
    """Carry out the moves of a plan; return the moved rows and the failures."""
    rows, failures = [], []
    now = dt.datetime.now().isoformat(timespec="seconds")
    emptied: set[Path] = set()

    def move(src: Path, dst: Path) -> None:
        if dst.exists():
            # made by an earlier move of this run: merge a folder, never overwrite a file
            if src.is_dir() and dst.is_dir():
                for child in sorted(src.iterdir()):
                    move(child, dst / child.name)
                emptied.add(src)
            else:
                failures.append(f"{src} -> {dst}: destination exists")
            return
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            failures.append(f"{src} -> {dst}: {exc}")
            return
        rows.append({"old": rel_path(workspace, src), "new": rel_path(workspace, dst), "date": now})
        if src.parent != qc:
            emptied.add(src.parent)

    for src, dst, _kind in plan["moves"]:
        move(src, dst)
    for folder in sorted(emptied, key=lambda p: len(p.parts), reverse=True):
        # a merged or split source folder left empty is removed, and so is each
        # parent it leaves empty, up to qc; line folders stay
        while (folder != qc and folder.is_dir() and not LINE_DIR.match(folder.name)
               and not any(folder.iterdir())):
            folder.rmdir()
            folder = folder.parent
    append_moves(qc, rows)
    return rows, failures


def path_regex(pairs: list[tuple[str, str]], ws_name: str) -> re.Pattern | None:
    """Return a regex matching any old path of pairs as a cited path (see the module docstring)."""
    if not pairs:
        return None
    olds = sorted({old for old, _new in pairs}, key=len, reverse=True)
    alternatives = "|".join(r"[\\/]".join(re.escape(part) for part in old.split("/")) for old in olds)
    left = rf"(?:(?<![A-Za-z0-9_.\-/\\])|(?<={re.escape(ws_name)}[\\/]))"
    right = r"(?![A-Za-z0-9_\-]|\.[A-Za-z0-9_])"
    return re.compile(left + "(" + alternatives + ")" + right)


def rewrite_text(text: str, regex: re.Pattern | None, mapping: dict[str, str]) -> tuple[str, int]:
    """Return text with every old path replaced by its new one, and the number replaced."""
    if regex is None:
        return text, 0

    def repl(m: re.Match) -> str:
        found = m.group(1)
        new = mapping[found.replace("\\", "/")]
        return new.replace("/", "\\") if "\\" in found else new

    return regex.subn(repl, text)


def rewrite_json(value, regex: re.Pattern | None, mapping: dict[str, str]):
    """Return a JSON value with its strings rewritten, and the number of paths replaced."""
    if isinstance(value, str):
        return rewrite_text(value, regex, mapping)
    if isinstance(value, list):
        out, n = [], 0
        for v in value:
            v2, k = rewrite_json(v, regex, mapping)
            out.append(v2)
            n += k
        return out, n
    if isinstance(value, dict):
        out, n = {}, 0
        for key, v in value.items():
            v2, k = rewrite_json(v, regex, mapping)
            out[key] = v2
            n += k
        return out, n
    return value, 0


def reports_folder(qc: Path) -> Path:
    """Return the reports folder: ``qc/survey/reports`` when it exists, else ``qc/reports``."""
    organised = qc / "survey" / "reports"
    return organised if organised.is_dir() else qc / "reports"


def rewrite_citations(pairs: list[tuple[str, str]], notes: Path | None, reports: Path | None,
                      ws_name: str, write: bool) -> dict[str, int]:
    """Rewrite old paths to new ones in the notes and the saved reports.

    Args:
        pairs (list[tuple[str, str]]): (old, new) paths relative to the workspace.
        notes (Path | None): The notebook folder (every ``*.md`` below it).
        reports (Path | None): The reports folder (its top-level ``*.json``,
            ``*.md`` and ``manifest.csv``).
        ws_name (str): The workspace folder's name, for absolute paths.
        write (bool): Write the changed files; False only counts.

    Returns:
        dict[str, int]: Per changed file, the number of paths replaced.
    """
    mapping = {old: new for old, new in pairs}
    regex = path_regex(pairs, ws_name)
    changed: dict[str, int] = {}
    files: list[Path] = []
    if notes is not None and notes.is_dir():
        files += sorted(notes.rglob("*.md"))
    if reports is not None and reports.is_dir():
        files += sorted(p for p in reports.iterdir() if p.is_file()
                        and (p.suffix in (".json", ".md") or p.name == "manifest.csv"))
    for path in files:
        if path.suffix == ".json":
            try:
                with open(path, encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, ValueError):
                continue
            record, n = rewrite_json(record, regex, mapping)
            if n and write:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2, ensure_ascii=False)
        else:
            with open(path, encoding="utf-8", errors="replace", newline="") as f:
                text = f.read()
            text, n = rewrite_text(text, regex, mapping)
            if n and write:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(text)
        if n:
            changed[str(path)] = n
    return changed


def print_plan(plan: dict, qc: Path, workspace: Path) -> None:
    """Print every planned move, then the counts per destination folder and per line."""
    for src, dst, _kind in plan["moves"]:
        print(f"  {rel_path(workspace, src)} -> {rel_path(workspace, dst)}")
    groups: dict[str, list[int]] = {}
    kinds = Counter()
    for src, dst, kind in plan["moves"]:
        g = groups.setdefault(group_of(qc, dst), [0, 0])
        g[0] += 1
        g[1] += n_files(src)
        kinds[kind] += 1
    print(f"\nplan: {len(plan['moves'])} moves ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})")
    print("destination folder: items (files)")
    lines: dict[str, list[int]] = {}
    for key in sorted(groups):
        items, files = groups[key]
        print(f"  qc/{key}: {items} ({files})")
        top = key.split("/")[0]
        t = lines.setdefault(top, [0, 0, 0])
        t[0] += items
        t[1] += files
        t[2] += 1
    print("per top folder: items (files) in folders")
    for top in sorted(lines):
        items, files, folders = lines[top]
        print(f"  qc/{top}: {items} ({files}) in {folders}")
    print(f"kept at the top of qc (read by scripts/filter_trial.py --lines): {len(plan['keep'])}")
    print(f"unsorted (no rule): {len(plan['unsorted'])}")
    for name in plan["unsorted"]:
        print(f"  {name}")
    print(f"conflicts (destination exists; not moved): {len(plan['conflicts'])}")
    for src, dst in plan["conflicts"]:
        print(f"  {rel_path(workspace, src)} -> {rel_path(workspace, dst)}")


def main(argv: list[str] | None = None) -> int:
    """Plan (and with --apply carry out) the sorting of a survey's qc folder; return the exit status."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("survey_yaml", type=Path)
    ap.add_argument("--qc", type=Path, help="the qc folder (default <workspace>/qc)")
    ap.add_argument("--notes", type=Path, help="the notebook folder (default <survey folder>/notes)")
    ap.add_argument("--apply", action="store_true", help="move the files and rewrite the citations")
    args = ap.parse_args(argv)

    survey_dir, workspace, sites = survey_sites(args.survey_yaml)
    qc = (args.qc or workspace / "qc").resolve()
    if not qc.is_dir():
        print(f"no qc folder: {qc}")
        return 1
    workspace = qc.parent
    notes = args.notes or survey_dir / "notes"
    rules = Rules(sites)
    plan = plan_moves(qc, rules)
    print(f"qc: {qc}")
    print_plan(plan, qc, workspace)

    history = [(r["old"], r["new"]) for r in read_moves(qc)]
    if not args.apply:
        planned = [(rel_path(workspace, s), rel_path(workspace, d)) for s, d, _k in plan["moves"]]
        changed = rewrite_citations(history + planned, notes, reports_folder(qc), workspace.name, write=False)
        print(f"citations to rewrite: {sum(changed.values())} in {len(changed)} files")
        print("dry run: nothing moved (--apply moves the files and rewrites the citations)")
        return 0

    rows, failures = apply_plan(plan, qc, workspace)
    pairs = history + [(r["old"], r["new"]) for r in rows]
    changed = rewrite_citations(pairs, notes, reports_folder(qc), workspace.name, write=True)
    print(f"moved: {len(rows)}; failed: {len(failures)}; recorded in {qc / MOVES_CSV}")
    for line in failures:
        print(f"  failed: {line}")
    print(f"citations rewritten: {sum(changed.values())} in {len(changed)} files")
    for path, n in sorted(changed.items()):
        print(f"  {path}: {n}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
