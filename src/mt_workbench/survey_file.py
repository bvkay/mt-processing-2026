# -*- coding: utf-8 -*-
"""
Edits to survey.yaml that keep the rest of the file as it was

A survey.yaml is written by hand as well as by scripts, so its comments, key
order, blank lines and line endings carry meaning. `edit` changes keys of
named site entries, adds new entries or changes the `defaults:` block, and
leaves every other line of the file as it was. A value equal to the one in
`defaults:` is not written into a site's entry (`_lean`), except for the keys
the code reads from the entry itself (`NO_LEAN`), a burst site's entry, and
the channel keys of a site that names its own recorder.

`plan` works on the text alone and returns the new text. `check` compares the
new text with the old one and the request: the parsed file, the comments, the
lines outside the edited entries, the lines of each edited entry other than
the keys asked, the line endings, and `Survey.site` for every site the edit
reaches. `commit` writes only when `check` finds nothing,
keeps the file as it was in survey.yaml.previous, and moves the new text into
place from a temporary file. Anything the writer cannot do on the text alone
raises `SurveyFileRefused`, with a message that says what to fix.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import copy
import difflib
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mt_workbench.survey import Survey

REMOVE = None  # a value that removes the key
# keys the code reads from the site's own entry, never from `defaults:`
NO_LEAN = ("instrument", "derived_from", "bursts_of", "sample_rate", "logger_pid", "sensor_pid_hx",
           "sensor_pid_hy", "sensor_pid_hz", "electrode_pid", "platform_pid")
# kept in an entry that names its own instrument, so a later change of the survey's set does not reach it
OWN_INSTRUMENT_KEYS = ("channels", "sensor_type")
# field facts of each site: a change of these in `defaults:` writes the old value into the sites that took it
DIPOLE_KEYS = ("dipole_length_ex", "dipole_length_ey", "azimuth_ex", "azimuth_ey")
# Windows refuses a replace while another program holds the file open
REPLACE_TRIES = 20
REPLACE_WAIT_S = 3.0
# a data_root that cannot exist, so the read-back of `check` opens no data folder
NO_DATA_ROOT = "<no data root>"


class SurveyFileRefused(ValueError):
    """The writer will not make this edit; the file is left as it was. The message says why and what to do."""


@dataclass
class Edit:
    """The outcome of one edit of a survey.yaml.

    Attributes:
        path (Path): The survey.yaml.
        written (bool): False for a request that changes nothing, and for a dry run.
        previous (Path | None): survey.yaml.previous, the file as it was, when written.
        made (dict): {"defaults": {...}, "sites": {site: {...}}, "add": {site: {...}}}, the keys
            written, with `REMOVE` for a key removed.
        summary (list[str]): One line per site changed or added and per defaults key, plus notes.
    """

    path: Path
    written: bool
    previous: Path | None
    made: dict
    summary: list[str] = field(default_factory=list)


def same(a, b) -> bool:
    """Compare two parsed YAML values, with types.

    A bool equals only a bool, int and float compare as numbers, lists
    item by item, mappings key by key in order; anything else needs the
    same type and ``==``. Plain ``==`` takes ``True == 1.0``.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _comment_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) of every comment: a '#' outside every token of the YAML scanner, at a line
    start or after a blank, to the line end."""
    covered = bytearray(len(text))
    for token in yaml.scan(text):
        a, b = token.start_mark.index, token.end_mark.index
        covered[a:b] = b"\x01" * (b - a)
    spans = []
    i = text.find("#")
    while i >= 0:
        if not covered[i] and (i == 0 or text[i - 1] in " \t\r\n"):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            spans.append((i, end))
            i = text.find("#", end)
        else:
            i = text.find("#", i + 1)
    return spans


def comment_texts(text: str) -> list[str]:
    """Return the text of every comment of a YAML file, in file order.

    A comment runs from its '#' to the line end, trailing blanks dropped. A
    '#' inside a quoted or plain value is part of the value, as PyYAML's
    scanner reads it, and is not listed.
    """
    return [text[a:b].rstrip() for a, b in _comment_spans(text)]


# characters that YAML or an editor reads as a line break; YAML would write them escaped or raw inside quotes
_BREAK = re.compile("[\r\n\x85  ]")


def _text(value) -> str:
    """Return a value as YAML on one line: scalars quoted as needed, lists and mappings in flow style."""
    if isinstance(value, dict):
        texts = [*value, *value.values()]
    elif isinstance(value, list):
        texts = value
    else:
        texts = [value]
    if any(isinstance(t, str) and _BREAK.search(t) for t in texts):
        raise SurveyFileRefused("a value holds a line break: write it on one line")
    try:
        if isinstance(value, (list, dict)):
            out = yaml.safe_dump(value, default_flow_style=True, width=10 ** 9, allow_unicode=True,
                                 sort_keys=False)
        else:
            out = yaml.safe_dump({"k": value}, width=10 ** 9, allow_unicode=True, sort_keys=False)[3:]
    except yaml.YAMLError as exc:
        raise SurveyFileRefused(f"the value {value!r} cannot be written in survey.yaml: {exc}") from exc
    out = out.rstrip("\n")
    if "\n" in out:
        raise SurveyFileRefused("a value holds a line break: write it on one line")
    return out


def name_text(name) -> str:
    """Return a site name as written on its header line, quoted where YAML would read another type."""
    if not isinstance(name, str) or not name.strip():
        raise SurveyFileRefused(f"site name {name!r} is not a text")
    return _text(name)


# ------------------------------------------------------------------ lines


def _lines(text: str) -> list[str]:
    """Split on '\\n' only, each line with its ending; str.splitlines also splits on characters notes hold."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def _newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and lf:
        raise SurveyFileRefused(f"survey.yaml mixes CRLF ({crlf}) and LF ({lf}) line endings: make them one "
                                f"kind first")
    return "\r\n" if crlf else "\n"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _blank(line: str) -> bool:
    return not line.strip()


def _comment_line(line: str) -> bool:
    return line.lstrip().startswith("#")


def _content(line: str) -> bool:
    return not _blank(line) and not _comment_line(line)


def _item(line: str) -> bool:
    text = line.strip()
    return text == "-" or text.startswith("- ")


_KEY = re.compile(r"""( *)('(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|[^\s#'"][^#]*?):(?:[ \t]+(.*?))?[ \t]*""")


def _key(line: str):
    """Return (indent, parsed key, rest after the colon) of a 'key: value' line, else None."""
    match = _KEY.fullmatch(line.rstrip("\r\n"))
    if not match or _item(line):
        return None
    try:
        parsed = yaml.safe_load(match.group(2) + ": 0")
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict) or len(parsed) != 1:
        return None
    return len(match.group(1)), next(iter(parsed)), match.group(3) or ""


def _has_value(rest: str) -> bool:
    return bool(rest) and not rest.startswith("#")


def _block(lines: list[str], top: str):
    """Return (header line, end) of a top-level block such as 'sites:', or None when the file has none."""
    heads = [i for i, line in enumerate(lines)
             if _content(line) and _indent(line) == 0 and (key := _key(line)) and key[1] == top]
    if len(heads) > 1:
        raise SurveyFileRefused(f"the file has {len(heads)} top-level '{top}:' lines")
    if not heads:
        return None
    head = heads[0]
    if _has_value(_key(lines[head])[2]):
        raise SurveyFileRefused(f"'{top}:' holds its value on its own line ({lines[head].strip()!r}): only a "
                                f"block of one entry per line is edited")
    end = next((k for k in range(head + 1, len(lines)) if _content(lines[k]) and _indent(lines[k]) == 0),
               len(lines))
    return head, end


def _entries(lines: list[str], head: int, end: int):
    """Return the entry indent and {name: [(header line, next header or block end, rest)]} of a block."""
    first = next((k for k in range(head + 1, end) if _content(lines[k])), None)
    n = _indent(lines[first]) if first is not None else None
    heads = [(k, key[1], key[2]) for k in range(head + 1, end)
             if _content(lines[k]) and _indent(lines[k]) == n and (key := _key(lines[k]))]
    entries: dict = {}
    for i, (k, name, rest) in enumerate(heads):
        stop = heads[i + 1][0] if i + 1 < len(heads) else end
        entries.setdefault(name, []).append((k, stop, rest))
    return n, entries


def _back_off(lines: list[str], head: int, stop: int, deepest: int) -> int:
    """Leave out blank lines, and comment lines indented `deepest` or less, at the foot of a span."""
    while stop > head + 1 and (_blank(lines[stop - 1]) or
                               (_comment_line(lines[stop - 1]) and _indent(lines[stop - 1]) <= deepest)):
        stop -= 1
    return stop


def _key_offset(lines: list[str], entries: dict, n: int) -> int:
    """The most common indent of an entry's keys under its header; 2 when no entry has a key."""
    offsets = Counter()
    for spans in entries.values():
        for head, stop, _rest in spans:
            first = next((k for k in range(head + 1, stop) if _content(lines[k])), None)
            if first is not None:
                offsets[_indent(lines[first]) - n] += 1
    return offsets.most_common(1)[0][0] if offsets else 2


def _insert_at(lines: list[str], head: int, end: int, entries: dict, n: int) -> int:
    """Where a new entry goes: after the last entry without its foot of blank lines and shallow comments."""
    if entries:
        last, stop, _rest = max(span for spans in entries.values() for span in spans)
        return _back_off(lines, last, stop, n)
    return _back_off(lines, head, end, 10 ** 9)


def _key_spans(lines: list[str], head: int, stop: int, label: str):
    """Return the key indent and {key: (first line, end)} of an entry, each key with its continuation lines."""
    first = next((k for k in range(head + 1, stop) if _content(lines[k])), None)
    m = _indent(lines[first]) if first is not None else None
    spans: dict = {}
    k = head + 1
    while k < stop:
        if not _content(lines[k]):
            k += 1
            continue
        key = _key(lines[k])
        if key is None or _indent(lines[k]) != m:
            raise SurveyFileRefused(f"{label}: line {k + 1} is not a 'key: value' line at the entry's indent, nor "
                                    f"a '- ' item of a key above with no value")
        if key[1] in spans:
            raise SurveyFileRefused(f"{label}: key {key[1]} appears twice")
        last, j = k, k + 1
        while j < stop:
            line = lines[j]
            if _blank(line):
                j += 1
                continue
            listed = _indent(line) == m and not _has_value(key[2]) and _item(line)
            if _indent(line) <= m and not listed:
                break
            last, j = j, j + 1
        spans[key[1]] = (k, last + 1)
        k = last + 1
    return m, spans


def _comments_in(text: str) -> list[tuple[int, int]]:
    try:
        return _comment_spans(text)
    except yaml.YAMLError:
        return []  # the fragment does not scan alone; the comment check of `check` still compares the files


# ------------------------------------------------------------------ the edit on text


def _lean(changes: dict, defaults: dict, own: dict) -> dict:
    """Return the keys to write into one entry, `REMOVE` for a key to remove.

    A key already holding the value asked is left alone. A value equal to
    `defaults` is not written, and the entry's own key is removed, unless
    the key is in `NO_LEAN`, the entry is a burst site's (`bursts_of`), or
    the key is in `OWN_INSTRUMENT_KEYS` and the entry names its own
    `instrument`.

    Args:
        changes (dict): {key: value} asked; `REMOVE` removes the key.
        defaults (dict): The parsed `defaults:` block after this edit.
        own (dict): The site's parsed entry.

    Returns:
        dict: The keys to write, in the order asked.
    """
    burst = "bursts_of" in own or changes.get("bursts_of") is not None
    instrument = changes["instrument"] if "instrument" in changes else own.get("instrument")
    out = {}
    for key, value in changes.items():
        if value is REMOVE:
            if key in own:
                out[key] = REMOVE
            continue
        if key in own and same(own[key], value):
            continue
        may_lean = not (burst or key in NO_LEAN or (key in OWN_INSTRUMENT_KEYS and instrument is not None))
        if may_lean and key in defaults and same(defaults[key], value):
            if key in own:
                out[key] = REMOVE
            continue
        out[key] = value
    return out


def _edit_entry(lines, head, stop, changes, nl, key_indent, name, label, summary) -> list[str]:
    """Return the lines of one entry (head to stop) with its keys replaced, removed or appended."""
    m, spans = _key_spans(lines, head, stop, label)
    pad = " " * (m if m is not None else key_indent)
    kept = [k for k in spans if changes.get(k, 0) is not REMOVE]
    added = [k for k, v in changes.items() if k not in spans and v is not REMOVE]
    if spans and not kept and not added:
        raise SurveyFileRefused(f"removing the last key of {name} would leave an empty entry: remove the entry "
                                f"by hand")
    new = {}
    for key, value in changes.items():
        if key not in spans:
            continue
        a, b = spans[key]
        comments = _comments_in("".join(lines[a:b]))
        if comments and (value is REMOVE or b - a > 1):
            raise SurveyFileRefused(f"the value of {key} in {name} carries a comment: change it by hand")
        for i in range(a, b):
            new[i] = []
        if value is REMOVE:
            if a - 1 > head and _comment_line(lines[a - 1]):
                summary.append(f"{name}: removed {key}; the comment above it stays: check it")
            continue
        old = lines[a].rstrip("\r\n")
        tail = old[len(old[:comments[0][0]].rstrip()):] if comments else ""
        ending = nl if lines[b - 1].endswith("\n") else ""  # a last line with no ending stays without one
        new[a] = [f"{pad}{_text(key)}: {_text(value)}{tail}{ending}"]
    at = max((b for _a, b in spans.values()), default=head + 1)
    out = []
    for i in range(head, stop):
        out.extend(new.get(i, [lines[i]]))
        if i == at - 1 and added:
            if out and not out[-1].endswith("\n"):
                out[-1] += nl
            out.extend(f"{pad}{_text(k)}: {_text(changes[k])}{nl}" for k in added)
    return out


def _site_line(head: str, changes: dict, takes: dict | None = None) -> str:
    """One summary line; a removed key in `takes` names the value the site now reads from `defaults:`."""
    takes = takes or {}
    parts = []
    for k, v in changes.items():
        if v is not REMOVE:
            parts.append(f"{k} {_text(v)}")
        elif k in takes:
            parts.append(f"{k} removed (takes {_text(takes[k])} from defaults:)")
        else:
            parts.append(f"{k} removed")
    return head + ", ".join(parts)


def _names(sites: list) -> str:
    return ", ".join(str(s) for s in sites[:10]) + (" ..." if len(sites) > 10 else "")


def _edit_defaults(lines, changes, nl, summary) -> list[str]:
    block = _block(lines, "defaults")
    if block is not None:
        head, end = block
        stop = _back_off(lines, head, end, 0)
        return lines[:head] + _edit_entry(lines, head, stop, changes, nl, 2, "defaults:", "defaults:",
                                          summary) + lines[stop:]
    sites = _block(lines, "sites")
    at = sites[0] if sites else len(lines)
    n = (_entries(lines, *sites)[0] if sites else None) or 2
    new = [f"defaults:{nl}"] + [f"{' ' * n}{_text(k)}: {_text(v)}{nl}" for k, v in changes.items()
                                if v is not REMOVE]
    if at == len(lines) and lines and not lines[-1].endswith("\n"):
        lines = lines[:-1] + [lines[-1] + nl]
    return lines[:at] + new + lines[at:]


def _locate(lines, block, name):
    """Return (header, end) of a site's entry, refusing a name the writer cannot edit safely."""
    _n, entries = _entries(lines, *block)
    found = entries.get(name, [])
    if not found:
        number = next((spans[0][0] for k, spans in entries.items() if not isinstance(k, str) and str(k) == name),
                      None)
        if number is not None:
            raise SurveyFileRefused(f"site {name!r} is written as a number in survey.yaml "
                                    f"({lines[number].strip()}); quote it by hand first")
        raise SurveyFileRefused(f"site {name!r} has no entry: add it first (Add sites, or scripts/new_survey.py "
                                f"again)")
    if len(found) > 1:
        raise SurveyFileRefused(f"site {name!r} appears twice in sites:")
    head, stop, rest = found[0]
    if _has_value(rest):
        raise SurveyFileRefused(f"site {name!r} holds its entry on its header line: edit it by hand")
    return head, stop


def _mapping(config: dict, key: str) -> dict:
    value = config.get(key)
    if value is not None and not isinstance(value, dict):
        raise SurveyFileRefused(f"'{key}:' in survey.yaml is not a block of 'key: value' lines: edit it by hand")
    return value or {}


def plan(text: str, *, sites: dict | None = None, add: dict | None = None,
         defaults: dict | None = None) -> tuple[str, dict, list[str]]:
    """Return the new text of a survey.yaml for an edit, without writing.

    The defaults are changed first, then the site entries from the last in
    the file to the first, then the new entries go after the last entry.
    A change of a key of `DIPOLE_KEYS` in `defaults:` writes the old value
    into every entry that took it, so no site's dipoles move.

    Args:
        text (str): The file as read, with its own line endings.
        sites (dict | None): {site: {key: value}} for sites with an entry.
        add (dict | None): {site: {key: value}} for new entries.
        defaults (dict | None): {key: value} for the `defaults:` block.

    Returns:
        tuple: (new text, made, summary), as `Edit` holds them.

    Raises:
        SurveyFileRefused: If the file or the request is one the writer
            does not edit; the message says what to do.
    """
    nl = _newline(text)
    try:
        config = yaml.safe_load(text) or {}
        tokens = list(yaml.scan(text))
    except yaml.YAMLError as exc:
        raise SurveyFileRefused(f"survey.yaml does not parse: {exc}; fix it by hand first") from exc
    anchors = [t for t in tokens if isinstance(t, (yaml.AnchorToken, yaml.AliasToken))]
    if anchors:
        raise SurveyFileRefused(f"survey.yaml uses YAML anchors or aliases (line {anchors[0].start_mark.line + 1}): "
                                f"the writer edits plain files only; edit it by hand")
    merges = [t for key, t in zip(tokens, tokens[1:]) if isinstance(key, yaml.KeyToken)
              and isinstance(t, yaml.ScalarToken) and t.plain and t.value == "<<"]
    if merges:
        raise SurveyFileRefused(f"survey.yaml uses a YAML merge key (<<) on line {merges[0].start_mark.line + 1}: "
                                f"edit it by hand")
    if not isinstance(config, dict):
        raise SurveyFileRefused("survey.yaml is not a block of 'key: value' lines: edit it by hand")
    entries = _mapping(config, "sites")
    old_defaults = _mapping(config, "defaults")
    lines = _lines(text)
    made: dict = {"defaults": {}, "sites": {}, "add": {}}
    summary: list[str] = []
    requests = {name: dict(changes) for name, changes in (sites or {}).items()}

    new_defaults = dict(old_defaults)
    changes = {k: v for k, v in (defaults or {}).items()
               if (k in old_defaults if v is REMOVE else not (k in old_defaults and same(old_defaults[k], v)))}
    if changes:
        lines = _edit_defaults(lines, changes, nl, summary)
        made["defaults"] = changes
        for key, value in changes.items():
            if value is REMOVE:
                new_defaults.pop(key, None)
            else:
                new_defaults[key] = value
            takers = [s for s, e in entries.items() if not isinstance(e, dict) or
                      (key not in e and "bursts_of" not in e)]
            was = repr(old_defaults[key]) if key in old_defaults else "not set"
            now = "removed" if value is REMOVE else repr(value)
            if key in DIPOLE_KEYS and key in old_defaults:
                for s in takers:
                    requests.setdefault(s, {}).setdefault(key, old_defaults[key])
                summary.append(f"defaults {key}: {was} -> {now}; {len(takers)} site(s) keep {was} in their own "
                               f"entry: {_names(takers)}")
            else:
                summary.append(f"defaults {key}: {was} -> {now}; {len(takers)} site(s) take the new value: "
                               f"{_names(takers)}")

    if requests:
        block = _block(lines, "sites")
        if block is None:
            raise SurveyFileRefused(f"site {next(iter(requests))!r} has no entry: add it first (Add sites, or "
                                    f"scripts/new_survey.py again)")
        n, all_entries = _entries(lines, *block)
        offset = _key_offset(lines, all_entries, n)
        places = {name: _locate(lines, block, name) for name in requests}
        done = {}
        for name in sorted(places, key=lambda s: -places[s][0]):
            head, stop = places[name]
            own = entries.get(name) or {}
            changes = _lean(requests[name], new_defaults, own)
            if not changes:
                continue
            stop = _back_off(lines, head, stop, n)
            lines[head:stop] = _edit_entry(lines, head, stop, changes, nl, n + offset, name, f"site {name!r}",
                                           summary)
            done[name] = changes
        for name in sorted(done, key=lambda s: places[s][0]):
            made["sites"][name] = done[name]
            own = entries.get(name) or {}
            # NO_LEAN keys, and some keys of a burst entry, are read from the entry alone: no value from defaults:
            takes = {} if "bursts_of" in own else {k: new_defaults[k] for k in done[name] if k in new_defaults
                                                   and k not in NO_LEAN}
            summary.append(_site_line(f"{name}: ", done[name], takes))

    for name, values in (add or {}).items():
        block = _block(lines, "sites")
        if block is None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += nl
            lines.append(f"sites:{nl}")
            block = (len(lines) - 1, len(lines))
        n, all_entries = _entries(lines, *block)
        if name in all_entries:
            raise SurveyFileRefused(f"site {name!r} already has an entry")
        entry = {k: v for k, v in _lean(dict(values), new_defaults, {}).items() if v is not REMOVE}
        if not entry:
            raise SurveyFileRefused(f"site {name!r} would get an empty entry (every value equals defaults:): give "
                                    f"it at least one key of its own")
        m = (n if n is not None else 2) + _key_offset(lines, all_entries, n or 0)
        new = [f"{' ' * (n if n is not None else 2)}{name_text(name)}:{nl}"]
        new += [f"{' ' * m}{_text(k)}: {_text(v)}{nl}" for k, v in entry.items()]
        at = _insert_at(lines, *block, all_entries, n or 0)
        if at == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] += nl
        lines[at:at] = new
        made["add"][name] = entry
        summary.append(_site_line(f"{name}: added with ", entry))
    return "".join(lines), made, summary


# ------------------------------------------------------------------ the checks


def _expected(config: dict, made: dict) -> dict:
    """The old parsed file with the edit applied: new keys and new sites last, a new `defaults:` above `sites:`."""
    out = copy.deepcopy(config)
    if made["defaults"]:
        values = dict(out.get("defaults") or {})
        for key, value in made["defaults"].items():
            if value is REMOVE:
                values.pop(key, None)
            else:
                values[key] = value
        if "defaults" in out or "sites" not in out:
            out["defaults"] = values
        else:
            out = {**{k: v for k, v in out.items() if k != "sites"}, "defaults": values, "sites": out["sites"]}
    if made["sites"] or made["add"]:
        if out.get("sites") is None:
            out["sites"] = {}
        for site, changes in made["sites"].items():
            entry = dict(out["sites"].get(site) or {})
            for key, value in changes.items():
                if value is REMOVE:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            out["sites"][site] = entry
        for site, entry in made["add"].items():
            out["sites"][site] = dict(entry)
    return out


def _allowed(old: str, made: dict) -> tuple[list, list]:
    """Return the old-text spans an edit may change and the points where it may insert lines."""
    lines = _lines(old)
    spans, points = [], []
    sites = _block(lines, "sites")
    n = _entries(lines, *sites)[0] if sites else None
    for site in made["sites"]:
        head, stop = _locate(lines, sites, site)
        spans.append((head, _back_off(lines, head, stop, n)))
    if made["defaults"]:
        block = _block(lines, "defaults")
        if block is not None:
            spans.append((block[0], _back_off(lines, *block, 0)))
        else:
            points.append(sites[0] if sites else len(lines))
    if made["add"]:
        if sites is None:
            points.append(len(lines))
        else:
            n, entries = _entries(lines, *sites)
            points.append(_insert_at(lines, *sites, entries, n or 0))
    return spans, points


class _KeysTwice(yaml.SafeLoader):
    """A loader that lists every key written twice in one mapping; `yaml.safe_load` keeps the last silently."""

    def construct_mapping(self, node, deep=False):
        nodes = [k for k, _v in node.value if k.tag != "tag:yaml.org,2002:merge"]  # '<<' has no constructor
        keys = [self.construct_object(k, deep=deep) for k in nodes]
        self.twice += [(str(key), nodes[i].start_mark.line + 1) for i, key in enumerate(keys) if key in keys[:i]]
        return super().construct_mapping(node, deep)


def _twice(text: str) -> list[tuple[str, int]]:
    """Return (key, line) of every key that repeats an earlier key of its mapping."""
    loader = _KeysTwice(text)
    loader.twice = []
    try:
        loader.get_single_data()
    finally:
        loader.dispose()
    return loader.twice


def _kept(lines: list[str], made: dict) -> dict:
    """Return {site, or None for `defaults:`: its lines less the lines of the keys asked} for an edit."""
    out = {}
    if made["defaults"] and _block(lines, "defaults") is not None:
        head, end = _block(lines, "defaults")
        out[None] = (head, _back_off(lines, head, end, 0), made["defaults"])
    if made["sites"]:
        block = _block(lines, "sites")
        n, entries = _entries(lines, *block) if block else (None, {})
        for site, keys in made["sites"].items():
            if len(entries.get(site, [])) != 1:
                raise SurveyFileRefused(f"site {site!r} is not one entry")
            head, stop, _rest = entries[site][0]
            out[site] = (head, _back_off(lines, head, stop, n), keys)
    for part, (head, stop, keys) in out.items():
        _m, spans = _key_spans(lines, head, stop, "defaults:" if part is None else f"site {part!r}")
        asked = {i for key in keys if key in spans for i in range(*spans[key])}
        out[part] = [lines[i] for i in range(head, stop) if i not in asked]
    return out


def _kept_lines(old: str, new: str, made: dict) -> list[str]:
    """Return a problem for each edited entry, or `defaults:`, whose lines other than the keys asked differ.

    The lines are found in the old and the new text separately, so a comment
    moved, a value rewritten or a blank line added inside an edited entry is
    seen even where the parsed file and the comment list stay the same.
    """
    texts = [_lines(old), _lines(new)]
    nl = _newline(old)
    for lines in texts:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += nl  # the last line compared with its ending, as the line diff does
    try:
        before, after = _kept(texts[0], made), _kept(texts[1], made)
    except SurveyFileRefused as exc:
        return [f"the new text: {exc}"]
    problems = []
    for part in before:
        if before[part] != after.get(part):
            label = "the defaults block" if part is None else f"site {part!r}"
            problems.append(f"{label}: a line other than those of the keys asked would change")
    return problems


def _refusals(config: dict, names: list) -> dict:
    """Return {site: message} for each named site that `Survey.site` refuses, read with no data folder."""
    config = {**config, "data_root": NO_DATA_ROOT}
    config.setdefault("name", "survey")
    try:
        survey = Survey(config, Path(NO_DATA_ROOT))
    except ValueError as exc:
        return {name: str(exc) for name in names}
    out = {}
    for name in names:
        try:
            survey.site(name)
        except ValueError as exc:
            out[name] = str(exc)
    return out


def check(old: str, new: str, made: dict) -> list[str]:
    """Compare a new text of survey.yaml with the old one and the edit.

    Each item is a separate observation: the new text parses to the old
    file with `made` applied (key order included); no key or site name
    appears twice that did not before; the comment texts are the same
    list; every line removed, changed or inserted lies inside an
    edited entry or the defaults block, or at the point where a new entry
    or block goes; inside an edited entry or `defaults:`, every line that
    is not a line of a key asked stays as it was; every line keeps the file's ending; and `Survey.site`
    reads every site the edit reaches unless it was refused before.

    Args:
        old (str): The file as read.
        new (str): The text to be written.
        made (dict): The edit, as `plan` returns it.

    Returns:
        list[str]: One line per failure; empty when the text is safe to write.
    """
    problems = []
    try:
        new_config = yaml.safe_load(new) or {}
    except yaml.YAMLError as exc:
        return [f"the new text does not parse: {exc}"]
    old_config = yaml.safe_load(old) or {}
    want = _expected(old_config, made)
    if not same(new_config, want):
        keys = list(dict.fromkeys(list(new_config) + list(want)))
        problems += [f"{k} would read differently" for k in keys
                     if k != "sites" and not same(new_config.get(k), want.get(k))]
        got_sites, want_sites = new_config.get("sites") or {}, want.get("sites") or {}
        problems += [f"site {s} would read differently" for s in dict.fromkeys(list(got_sites) + list(want_sites))
                     if not same(got_sites.get(s), want_sites.get(s))]
        if list(got_sites) != list(want_sites) or list(new_config) != list(want):
            problems.append("the order of the keys or the sites would change")
        if not problems:
            problems.append("the parsed file would read differently")
    twice = _twice(new)
    if sorted(k for k, _line in twice) != sorted(k for k, _line in _twice(old)):
        problems.append("a key or site name appears twice: " + ", ".join(f"{k} (line {line})" for k, line in twice))
    if comment_texts(old) != comment_texts(new):
        problems.append("the comments would change (a comment reworded, moved or lost)")
    problems += _kept_lines(old, new, made)

    nl = _newline(old)
    old_lines, new_lines = _lines(old), _lines(new)
    if old_lines and not old_lines[-1].endswith("\n") and new.endswith("\n"):
        old_lines[-1] += nl  # the old last line gains its ending when lines go after it
    spans, points = _allowed(old, made)
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            ok = i1 in points or any(a < i1 <= b for a, b in spans)
        else:
            ok = any(a <= i1 and i2 <= b for a, b in spans)
        if not ok:
            problems.append(f"lines {i1 + 1} to {i2} would change outside the edit")
    for k, line in enumerate(new_lines):
        last_bare = k == len(new_lines) - 1 and not line.endswith("\n") and not old.endswith("\n")
        if not last_bare and (not line.endswith(nl) or (nl == "\n" and line.endswith("\r\n"))):
            problems.append(f"line {k + 1} would change its line ending")
            break

    names = list(made["sites"]) + list(made["add"])
    if made["defaults"]:
        names = list(dict.fromkeys(list(new_config.get("sites") or {}) + names))
    before, after = _refusals(old_config, names), _refusals(new_config, names)
    problems += [f"{s}: Survey.site would refuse it: {after[s]}" for s in names if s in after and s not in before]
    return problems


# ------------------------------------------------------------------ writing


def _unchanged(path: Path, planned: bytes) -> None:
    if path.read_bytes() != planned:
        raise SurveyFileRefused("survey.yaml changed while the edit was prepared: nothing written; do it again")


def commit(path, old: str, new: str, made: dict, *, dry_run: bool = False) -> Edit:
    """Check a new text and write it over survey.yaml, keeping the file as it was.

    `commit` writes nothing when the text is unchanged, on a dry run, or
    when `check` finds a problem. Otherwise the file is read again and must
    still be `old`; it is copied to survey.yaml.previous; the new text goes
    to a temporary file in the same folder, which replaces survey.yaml
    (retried while Windows holds the file, the file read again before each
    try).

    Args:
        path (str | Path): The survey.yaml.
        old (str): The file as read for the plan.
        new (str): The new text.
        made (dict): The edit, as `plan` returns it.
        dry_run (bool): Check only.

    Returns:
        Edit: The outcome, with an empty summary.

    Raises:
        SurveyFileRefused: If a check fails, the file changed meanwhile, or
            it could not be replaced; survey.yaml is then as it was.
    """
    path = Path(path)
    if new == old:
        return Edit(path, False, None, made)
    problems = check(old, new, made)
    if problems:
        raise SurveyFileRefused("survey.yaml was not written: " + "; ".join(problems))
    if dry_run:
        return Edit(path, False, None, made)
    planned = old.encode("utf-8")
    _unchanged(path, planned)
    previous = path.with_name(path.name + ".previous")
    shutil.copyfile(path, previous)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(new.encode("utf-8"))
        for attempt in range(REPLACE_TRIES):
            _unchanged(path, planned)
            try:
                os.replace(temporary, path)
                return Edit(path, True, previous, made)
            except PermissionError as exc:
                if attempt == REPLACE_TRIES - 1:
                    raise SurveyFileRefused(f"survey.yaml could not be replaced ({exc}): close the program that "
                                            f"holds it or clear its read-only flag, then save again; nothing "
                                            f"written") from exc
                time.sleep(REPLACE_WAIT_S)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def edit(path, *, sites: dict | None = None, add: dict | None = None, defaults: dict | None = None,
         dry_run: bool = False) -> Edit:
    """Edit a survey.yaml in place: read it, plan the edit, check it and write it.

    Args:
        path (str | Path): The survey.yaml.
        sites (dict | None): {site: {key: value}} for sites with an entry;
            `REMOVE` removes a key.
        add (dict | None): {site: {key: value}} for new entries.
        defaults (dict | None): {key: value} for the `defaults:` block.
        dry_run (bool): Plan and check only.

    Returns:
        Edit: What was written and the summary lines.

    Raises:
        SurveyFileRefused: If the edit is refused; the file is as it was.
    """
    path = Path(path)
    try:
        old = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SurveyFileRefused(f"survey.yaml is not UTF-8 text ({exc}): save it as UTF-8 first") from exc
    new, made, summary = plan(old, sites=sites, add=add, defaults=defaults)
    result = commit(path, old, new, made, dry_run=dry_run)
    result.summary = summary
    return result
