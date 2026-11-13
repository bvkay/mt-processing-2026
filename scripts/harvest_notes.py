# -*- coding: utf-8 -*-
"""
Index a survey's processing notebook and check it against the saved reports

A survey's notebook is the folder ``notes/`` beside its survey.yaml: markdown
files that record, per method and per site, what was tried, the numbers, the
verdict and the reason, each claim followed by its source in brackets. The
notes may sit in subfolders (``notes/lineC/C05.md``); every ``*.md`` under the
folder is a note except the top-level ``index.md``. The sources are the report
files in the reports folder, ``<workspace>/qc/survey/reports/`` when that
folder exists (the organised qc layout of ``scripts/organise_qc.py``), else
``<workspace>/qc/reports/`` (one JSON file per report, named
``<date>_<workflow>_<label>.json``, or a markdown file with a
``<!-- report ... -->`` header), the figures and products under the
workspace, and commits.

The script writes ``notes/index.md``, one row per report with its date,
workflow, label, the sites it names and the note files that cite it, and
``manifest.csv`` in the reports folder (file, workflow, label, phase, date,
sites, has_verdict, kind, run_id, agent_id; the sites are the survey.yaml
site names a report's text holds). A note is named by its path under the
notes folder (``lineC/C05.md``). It then checks the notebook. A
note cites a report by its file name, written ``r: <file>``. A path cited in
a note is a backtick span without spaces that holds a slash or ends in a file
extension (.png, .edi, .json, .csv, .md, .yaml, .py, .h5, ...); it is looked
up as given, then under the citing note's own folder (so ``../README.md`` and
``README.md`` in ``lineC/C05.md`` name the notebook's and the line's
README), the workspace (and its qc, tf, mth5 and campaign folders), the
repository, the survey folder, the notes folder and the reports folder. A span with ``*`` must match at least one file. Spans holding
``<`` are templates (such as ``qc/lineC_fx/<site>_*.png``) and are skipped.

With --journals, report records are first copied from workflow journals
(``journal.jsonl`` files of JSON lines) found under the given folders. A
``started`` line gives an id's label and phase, a ``result`` line its report.
For a journal at ``<log root>/subagents/workflows/<run id>/journal.jsonl``
the workflow's name comes from ``<log root>/workflows/<run id>.json`` (key
workflowName) or a script ``<log root>/workflows/scripts/<name>-<run id>.js``,
and the date from the journal file's modification time. A report
whose run and id are already saved keeps its file; only its kind and verdict
fields are updated. A report is a verdict when its phase or label names a
verification (verify, sceptic, review, probe, critique) or its keys include
``refuted``. A report has a verdict when a verdict of the same run names one
of its label's parts or its site, or when the run holds one verdict that
names no report.

The check fails (exit 1) if a report in the reports folder is cited by no
note, if a path cited in a note does not exist, or if an ``r: <file>``
citation names no saved report. Exit 0 otherwise.

Usage:
    python scripts/harvest_notes.py <survey.yaml> [--notes DIR] [--reports DIR]
        [--journals DIR [DIR ...]] [--no-index]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

import yaml

PATH_EXT = (
    ".png", ".jpg", ".pdf", ".edi", ".json", ".csv", ".md", ".yaml", ".yml",
    ".py", ".h5", ".txt", ".log", ".npz", ".js", ".jsonl",
)
SPAN_RE = re.compile(r"`([^`\n]+)`")
REPORT_RE = re.compile(r"\br: ([A-Za-z0-9._-]+\.(?:json|md))")
MANIFEST_COLUMNS = [
    "file", "workflow", "label", "phase", "date", "sites", "has_verdict",
    "kind", "run_id", "agent_id",
]
VERIFY_WORDS = ("verify", "sceptic", "review", "probe", "critique")


def survey_paths(survey_yaml: Path) -> tuple[Path, Path, Path, list[str]]:
    """Return the survey folder, the workspace, the repository root and the site names.

    Args:
        survey_yaml (Path): The survey's survey.yaml.

    Returns:
        tuple[Path, Path, Path, list[str]]: survey folder, workspace
        (``workspace:`` or ``<survey folder>/work``), repository root (the
        parent of scripts/), and the names in the ``sites:`` block.
    """
    with open(survey_yaml, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    survey_dir = survey_yaml.resolve().parent
    ws = config.get("workspace")
    workspace = Path(ws) if ws else survey_dir / "work"
    names = [str(n) for n in (config.get("sites") or {})]
    return survey_dir, workspace, Path(__file__).resolve().parents[1], names


def default_reports(workspace: Path) -> Path:
    """Return the reports folder: ``qc/survey/reports`` when it exists, else ``qc/reports``."""
    organised = workspace / "qc" / "survey" / "reports"
    return organised if organised.is_dir() else workspace / "qc" / "reports"


def site_pattern(names: list[str]) -> re.Pattern | None:
    """Return a regex matching any of the site names as a whole word, or None for no names."""
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z0-9])(" + alternatives + r")(?![A-Za-z0-9])")


def sites_in(text: str, pattern: re.Pattern | None) -> list[str]:
    """Return the sorted site names of the survey that a text names."""
    return sorted(set(pattern.findall(text))) if pattern is not None else []


def clean_name(text: str) -> str:
    """Return text as a file-name part: letters, digits, dot, dash and underscore."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return name or "unnamed"


def is_verdict(label: str, phase: str, result) -> bool:
    """Return True when a report is a verification of other reports."""
    words = f"{label} {phase}".lower()
    if any(w in words for w in VERIFY_WORDS):
        return True
    return isinstance(result, dict) and "refuted" in result


def verdict_target(label: str) -> str:
    """Return the part of a verdict's label after its first colon, lower case."""
    return label.split(":", 1)[1].lower() if ":" in label else ""


def workflow_name(journal: Path, run_id: str) -> str:
    """Return the workflow name of a journal's run, or the run id when none is found."""
    session = journal.parents[3] if len(journal.parents) > 3 else journal.parent
    record = session / "workflows" / f"{run_id}.json"
    if record.exists():
        try:
            with open(record, encoding="utf-8") as f:
                name = json.load(f).get("workflowName")
            if name:
                return str(name)
        except (OSError, ValueError):
            pass
    for script in (session / "workflows" / "scripts").glob(f"*-{run_id}.js"):
        return script.name[: -len(f"-{run_id}.js")]
    return run_id


def read_journal(journal: Path) -> tuple[dict, dict]:
    """Return the started records and the results of one journal, keyed by id."""
    started, results = {}, {}
    with open(journal, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "started" and rec.get("agentId"):
                started[rec["agentId"]] = rec
            elif rec.get("type") == "result" and rec.get("agentId"):
                results[rec["agentId"]] = rec.get("result")
    return started, results


def saved_ids(reports: Path) -> dict[tuple[str, str], Path]:
    """Return the JSON reports already saved, keyed by (run id, id)."""
    ids = {}
    for path in reports.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("run_id"):
            ids[(str(rec.get("run_id")), str(rec.get("agent_id")))] = path
    return ids


def harvest_journals(roots: list[Path], reports: Path, pattern: re.Pattern | None = None) -> list[Path]:
    """Copy the results of every journal under roots into the reports folder.

    Args:
        roots (list[Path]): Folders searched for ``journal.jsonl``.
        reports (Path): The reports folder, created when missing.
        pattern (re.Pattern | None): The survey's site names (`site_pattern`).

    Returns:
        list[Path]: The report files written by this call.
    """
    reports.mkdir(parents=True, exist_ok=True)
    have = saved_ids(reports)
    written = []
    for root in roots:
        for journal in sorted(Path(root).rglob("journal.jsonl")):
            run_id = journal.parent.name
            started, results = read_journal(journal)
            if not results:
                continue
            name = workflow_name(journal, run_id)
            date = dt.datetime.fromtimestamp(journal.stat().st_mtime).strftime("%Y-%m-%d")
            entries = []
            for agent_id, result in results.items():
                rec = started.get(agent_id, {})
                label, phase = str(rec.get("label") or agent_id), str(rec.get("phase") or "")
                entries.append({
                    "agent_id": agent_id, "label": label, "phase": phase, "result": result,
                    "kind": "verdict" if is_verdict(label, phase, result) else "report",
                })
            verdicts = [e for e in entries if e["kind"] == "verdict"]
            plain = [e for e in entries if e["kind"] == "report"]
            for e in plain:
                parts = {p.lower() for p in e["label"].split(":")}
                site = e["result"].get("site") if isinstance(e["result"], dict) else None
                e["verdict_by"] = [
                    v["label"] for v in verdicts
                    if verdict_target(v["label"]).split(":")[0] in parts
                    or (site and isinstance(v["result"], dict) and v["result"].get("site") == site)
                ]
            unmatched = [
                v for v in verdicts
                if not any(v["label"] in e["verdict_by"] for e in plain)
            ]
            if len(verdicts) == 1 and unmatched:
                for e in plain:
                    e["verdict_by"] = [verdicts[0]["label"]]
            for e in entries:
                has_verdict = e["kind"] == "verdict" or bool(e.get("verdict_by"))
                old = have.get((run_id, e["agent_id"]))
                if old is not None:
                    with open(old, encoding="utf-8") as f:
                        rec = json.load(f)
                    fields = {
                        "kind": e["kind"], "has_verdict": has_verdict,
                        "verdict_by": e.get("verdict_by", []),
                        "sites": sites_in(json.dumps(e["result"], ensure_ascii=False), pattern),
                    }
                    if any(rec.get(k) != v for k, v in fields.items()):
                        rec.update(fields)
                        with open(old, "w", encoding="utf-8") as f:
                            json.dump(rec, f, indent=2, ensure_ascii=False)
                    continue
                stem = f"{date}_{clean_name(name)}_{clean_name(e['label'])}"
                path = reports / f"{stem}.json"
                if path.exists():
                    path = reports / f"{stem}_{e['agent_id'][:8]}.json"
                text = json.dumps(e["result"], ensure_ascii=False)
                record = {
                    "workflow": name, "run_id": run_id, "label": e["label"],
                    "phase": e["phase"], "agent_id": e["agent_id"], "date": date,
                    "kind": e["kind"],
                    "has_verdict": has_verdict,
                    "verdict_by": e.get("verdict_by", []),
                    "sites": sites_in(text, pattern), "journal": str(journal),
                    "result": e["result"],
                }
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2, ensure_ascii=False)
                have[(run_id, e["agent_id"])] = path
                written.append(path)
    return written


def report_files(reports: Path) -> list[Path]:
    """Return the report files of the reports folder (JSON and markdown, top level)."""
    return sorted(p for p in reports.glob("*") if p.is_file() and p.suffix in (".json", ".md"))


def report_meta(path: Path, pattern: re.Pattern | None = None) -> dict:
    """Return a report's manifest row (the MANIFEST_COLUMNS keys)."""
    row = {k: "" for k in MANIFEST_COLUMNS}
    row["file"] = path.name
    if path.suffix == ".json":
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            return row
        for key in MANIFEST_COLUMNS[1:]:
            value = rec.get(key, "")
            row[key] = " ".join(value) if isinstance(value, list) else value
        row["has_verdict"] = "yes" if rec.get("has_verdict") else "no"
        return row
    text = path.read_text(encoding="utf-8", errors="replace")
    head = re.search(r"<!--\s*report(.*?)-->", text, re.S)
    if head:
        for line in head.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip() in row:
                row[key.strip()] = value.strip()
    if not row["sites"]:
        row["sites"] = " ".join(sites_in(text, pattern))
    row["has_verdict"] = row["has_verdict"] or "no"
    return row


def write_manifest(reports: Path, rows: list[dict]) -> Path:
    """Write manifest.csv in the reports folder from the report rows."""
    path = reports / "manifest.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def note_files(notes: Path) -> list[Path]:
    """Return the notebook's markdown files at any depth, the top-level index.md left out."""
    return sorted(p for p in notes.rglob("*.md") if p != notes / "index.md")


def note_name(notes: Path, note: Path) -> str:
    """Return a note's name: its path under the notes folder, with forward slashes."""
    return note.relative_to(notes).as_posix()


def citations(notes: Path, names: list[str]) -> dict[str, list[str]]:
    """Return, per report file name, the note files whose text holds that name."""
    cited: dict[str, list[str]] = {n: [] for n in names}
    for note in note_files(notes):
        text = note.read_text(encoding="utf-8", errors="replace")
        for n in names:
            if re.search(r"(?<![A-Za-z0-9._-])" + re.escape(n) + r"(?![A-Za-z0-9_-])", text):
                cited[n].append(note_name(notes, note))
    return cited


def cited_paths(text: str) -> list[str]:
    """Return the backtick spans of a note that name a file or folder."""
    found = []
    for span in SPAN_RE.findall(text):
        span = span.strip()
        if not span or " " in span or "<" in span or span.startswith("-"):
            continue
        if "/" in span or "\\" in span or span.lower().endswith(PATH_EXT):
            found.append(span.rstrip(".,;:"))
    return found


def path_exists(span: str, roots: list[Path]) -> bool:
    """Return True when a cited path exists as given or under one of the roots."""
    candidates = [Path(span)] + [root / span for root in roots]
    for cand in candidates:
        if "*" in span:
            if glob.glob(str(cand)):
                return True
        elif cand.exists():
            return True
    return False


def write_index(notes: Path, rows: list[dict], cited: dict[str, list[str]]) -> Path:
    """Write notes/index.md: one row per report with the notes that cite it."""
    lines = [
        "# Evidence index",
        "",
        "Written by `scripts/harvest_notes.py`; do not edit by hand. One row per report "
        "saved in the workspace's reports folder, with the note files that cite it "
        "(named by their path under `notes/`).",
        "",
        f"{len(rows)} reports. Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "| report | date | workflow | label | kind | sites | cited by |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: (r["date"], r["workflow"], r["label"], r["file"])):
        label = str(row["label"]).replace("|", "/")
        sites = str(row["sites"])
        if len(sites) > 60:
            sites = sites[:57] + "..."
        lines.append(
            f"| {row['file']} | {row['date']} | {row['workflow']} | {label} | {row['kind']} "
            f"| {sites} | {', '.join(cited.get(row['file'], [])) or '-'} |"
        )
    path = notes / "index.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def check(notes: Path, reports: Path, roots: list[Path], cited: dict[str, list[str]]) -> list[str]:
    """Return the notebook's problems.

    Args:
        notes (Path): The notebook folder.
        reports (Path): The reports folder.
        roots (list[Path]): Folders a cited path is looked up under, after
            the citing note's own folder.
        cited (dict[str, list[str]]): Per report file name, the notes citing it.

    Returns:
        list[str]: One line per report cited by no note, per cited path that
        does not exist, and per ``r: <file>`` citation that names no saved
        report.
    """
    problems = [f"report cited by no note: {n}" for n, by in sorted(cited.items()) if not by]
    for note in note_files(notes):
        text = note.read_text(encoding="utf-8", errors="replace")
        name = note_name(notes, note)
        for span in cited_paths(text):
            if not path_exists(span, [note.parent] + roots):
                problems.append(f"{name}: cited path missing: {span}")
        for report in sorted(set(REPORT_RE.findall(text))):
            if report not in cited:
                problems.append(f"{name}: cited report missing: {report}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Harvest (optional), index and check a survey's notebook; return the exit status."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("survey_yaml", type=Path)
    ap.add_argument("--notes", type=Path, help="notebook folder (default <survey folder>/notes)")
    ap.add_argument("--reports", type=Path,
                    help="reports folder (default <workspace>/qc/survey/reports, else <workspace>/qc/reports)")
    ap.add_argument("--journals", type=Path, nargs="+", default=[],
                    help="folders searched for journal.jsonl files to copy into the reports folder")
    ap.add_argument("--no-index", action="store_true",
                    help="check only; leave index.md and manifest.csv as they are")
    args = ap.parse_args(argv)

    survey_dir, workspace, repo, names = survey_paths(args.survey_yaml)
    pattern = site_pattern(names)
    notes = args.notes or survey_dir / "notes"
    reports = args.reports or default_reports(workspace)
    if args.journals:
        written = harvest_journals(args.journals, reports, pattern)
        print(f"journals: {len(written)} new report(s) saved in {reports}")
    if not notes.is_dir():
        print(f"no notebook folder: {notes}")
        return 1
    files = report_files(reports) if reports.is_dir() else []
    rows = [report_meta(p, pattern) for p in files]
    cited = citations(notes, [p.name for p in files])
    if not args.no_index:
        if reports.is_dir():
            write_manifest(reports, rows)
        write_index(notes, rows, cited)
    roots = [
        workspace, workspace / "qc", workspace / "tf", workspace / "mth5",
        workspace / "campaign", repo, survey_dir, notes, reports,
    ]
    problems = check(notes, reports, roots, cited)
    n_cited = sum(1 for by in cited.values() if by)
    print(f"reports: {len(files)}, cited: {n_cited}; notes: {len(note_files(notes))}")
    for p in problems:
        print(p)
    print("FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
