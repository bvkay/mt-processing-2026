# -*- coding: utf-8 -*-
"""
Look up a survey's instruments in the AuScope instrument registry by serial and propose their DOIs

The registry (https://pidinst.data.auscope.org.au/, CKAN) holds PIDINST
records with DOIs under 10.82388: loggers, coils and survey platforms. A
survey.yaml declares the DOIs of the instruments each site used
(`mt_workbench.survey.SiteConfig.logger_pid`, `sensor_pid_hx`, `sensor_pid_hy`,
`sensor_pid_hz`); ingest and processing read them from there. This script
fills the declarations from the serials survey.yaml already holds.

For each site of the `sites:` block with a serial and no DOI declared (in its
entry or `defaults:`), the logger's `serial` against `logger_pid` and a
Phoenix site's `coil_hx`, `coil_hy`, `coil_hz` against `sensor_pid_hx`, ...,
the registry is searched (`package_search?q=<serial>`). A record is a
candidate when one of its SerialNumber identifiers equals the serial, it is
not a platform, and its model or title names the site's instrument
(`MODEL_TOKENS`, compared lower case with everything but letters and digits
removed; an instrument with no tokens is matched on the serial alone). A
serial is not unique across makers: 10307 is an Adelaide-Flinders Orange
Box and a Phoenix MTU-5C. Each candidate is printed with its commissioning
and decommissioning dates against the site's `start` and `end`; a record
whose dates exclude the site's span is printed and not proposed.

With `--write`, each site with exactly one proposed record gets its key
written into its entry, in place, keeping the comments of a hand-maintained
survey.yaml: a dated copy
``survey.yaml.before_pidinst_<YYYYMMDD-HHMMSS>`` first, then one inserted
line per key after an anchor inside the entry (the `serial:` line, else the
entry's own line), one entry at a time, each step parsed and checked; the
whole edit must change the parsed document by the new keys only and keep
the comment-line count and the line endings. No record, or more than one:
printed, the key left out. A failed check leaves survey.yaml
unchanged. A network failure prints one line and exits 1.

The script only reads the registry.

Usage:
    python scripts/pidinst_lookup.py <survey.yaml> [--site S ...] [--write] [--responses DIR]

``--responses DIR`` reads saved search responses ``DIR/<serial>.json``
instead of the network (tests, offline work).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

API = "https://pidinst.data.auscope.org.au/api/3/action/package_search"
TIMEOUT_S = 30
# the registry's model names or titles hold one of these (lower case, letters and digits only) for an
# instrument key of mt_workbench.instruments.INSTRUMENTS; "coil:<instrument>" for its magnetic sensors
MODEL_TOKENS = {
    "orangebox": ("orangebox", "par24b"),
    "lemi423": ("lemi423",),
    "lemi424": ("lemi424",),
    "edl": ("pr624", "earthdata"),
    "phoenix": ("mtu5c", "mtu8a", "mtu5a", "mtu2c"),
    "mtu5a": ("mtu5a",),
    "coil:phoenix": ("mtc150", "mtc155", "mtc185", "mtc"),
    "coil:lemi423": ("lemi120",),
    "coil:edl": ("lemi120",),
}
# survey.yaml serial key -> the DOI key it fills
SERIAL_KEYS = {"serial": "logger_pid", "coil_hx": "sensor_pid_hx", "coil_hy": "sensor_pid_hy",
               "coil_hz": "sensor_pid_hz"}
COPY_LABEL = "before_pidinst"


class RegistryError(RuntimeError):
    """The registry could not be reached or answered something unreadable."""


def _norm(text) -> str:
    """Return text lower case with every character but letters and digits removed."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _listed(value) -> list:
    """Return a CKAN repeating field as a list: the registry stores some as JSON text."""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return list(value) if isinstance(value, list) else []


def fetch(serial: str, responses: Path | None = None) -> dict:
    """Return the registry's package_search response for a serial.

    Args:
        serial (str): The serial searched for (`q=<serial>`).
        responses (Path, optional): A folder of saved responses
            ``<serial>.json``, read instead of the network.

    Returns:
        dict: The parsed response.

    Raises:
        RegistryError: If the registry cannot be reached, a saved response is
            missing, or the answer is not a successful CKAN response.
    """
    if responses is not None:
        path = Path(responses) / f"{serial}.json"
        if not path.exists():
            raise RegistryError(f"no saved response {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        url = f"{API}?{urllib.parse.urlencode({'q': serial, 'rows': 50})}"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as reply:
                data = json.loads(reply.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise RegistryError(f"registry not reached ({url}): {exc}") from None
    if not isinstance(data, dict) or not data.get("success") or "result" not in data:
        raise RegistryError(f"registry answer for {serial!r} is not a successful package_search response")
    return data


def record_summary(record: dict) -> dict:
    """Return the fields of one registry record the lookup uses.

    Args:
        record (dict): One entry of a package_search ``result.results``.

    Returns:
        dict: ``doi``, ``name``, ``title``, ``model`` (the model names
        joined), ``serials``, ``inventory``, ``commissioned``,
        ``decommissioned`` (None when absent) and ``is_platform``.
    """
    ids = _listed(record.get("alternate_identifier_obj"))
    dates = {d.get("date_type"): str(d.get("date_value") or "") for d in _listed(record.get("date"))
             if isinstance(d, dict)}
    return {
        "doi": record.get("doi"),
        "name": record.get("name"),
        "title": record.get("title"),
        "model": "; ".join(str(m.get("model_name") or "") for m in _listed(record.get("model")) if isinstance(m, dict)),
        "serials": [str(i.get("alternate_identifier")) for i in ids
                    if isinstance(i, dict) and i.get("alternate_identifier_type") == "SerialNumber"],
        "inventory": [str(i.get("alternate_identifier")) for i in ids
                      if isinstance(i, dict) and i.get("alternate_identifier_type") == "InventoryNumber"],
        "commissioned": dates.get("Commissioned") or None,
        "decommissioned": dates.get("DeCommissioned") or None,
        "is_platform": bool(record.get("is_platform")),
    }


def dates_cover(summary: dict, start: str | None, end: str | None) -> bool | None:
    """Whether a record's service dates cover a site's recorded span.

    The dates are compared as ISO text cut to the record's precision
    ("2002" against "2006-05-02T06:56:00Z" compares the years).

    Args:
        summary (dict): Output of `record_summary`.
        start (str or None): The site's first instant, UTC ISO.
        end (str or None): The site's last instant, UTC ISO.

    Returns:
        bool or None: False when the record was commissioned after the
        site's end or decommissioned before its start; None when neither
        the record's dates nor the site's span are known; else True.
    """
    lo, hi = summary.get("commissioned"), summary.get("decommissioned")
    first, last = start or end, end or start
    if not first or not (lo or hi):
        return None
    if lo and last[:len(lo)] < lo:
        return False
    if hi and first[:len(hi)] > hi:
        return False
    return True


def candidates(response: dict, serial: str, tokens: tuple[str, ...] | None) -> list[dict]:
    """Return the records of a search response that match a serial and a model.

    Args:
        response (dict): A package_search response (`fetch`).
        serial (str): The serial; a record matches when one of its
            SerialNumber identifiers equals it (letters and digits compared,
            case ignored).
        tokens (tuple of str or None): `MODEL_TOKENS` of the instrument; a
            record matches when its model or title holds one. None or empty
            matches every model.

    Returns:
        list of dict: `record_summary` of each match that is not a platform.
    """
    out = []
    for record in response["result"].get("results") or []:
        summary = record_summary(record)
        if summary["is_platform"] or not summary["doi"]:
            continue
        if _norm(serial) not in [_norm(s) for s in summary["serials"]]:
            continue
        named = _norm(summary["model"]) + " " + _norm(summary["title"])
        if tokens and not any(t in named for t in tokens):
            continue
        out.append(summary)
    return out


def wanted(config: dict, instrument_of) -> list[tuple[str, str, str, tuple | None]]:
    """List the (site, serial key, serial, model tokens) the lookup searches for.

    A site is searched for a serial key when the serial is set in its entry
    and the DOI key it fills is set neither in the entry nor in `defaults:`.

    Args:
        config (dict): The parsed survey.yaml.
        instrument_of (callable): Site name to instrument key
            (`mt_workbench.survey.Survey.instrument_of`).

    Returns:
        list of tuple: One row per serial to search.
    """
    defaults = config.get("defaults") or {}
    rows = []
    for site, entry in (config.get("sites") or {}).items():
        entry = entry or {}
        if entry.get("derived_from") or entry.get("bursts_of"):
            continue  # a derived or burst site takes its recorded site's instruments
        instrument = instrument_of(site)
        for key, pid_key in SERIAL_KEYS.items():
            serial = entry.get(key)
            if serial in (None, "") or pid_key in entry or pid_key in defaults:
                continue
            kind = instrument if key == "serial" else f"coil:{instrument}"
            rows.append((site, key, str(serial), MODEL_TOKENS.get(kind)))
    return rows


def comment_lines(text: str) -> int:
    """Return the number of comment lines of a YAML text."""
    return sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))


def _entry_bounds(lines: list[str], site: str) -> tuple[int, int, str]:
    """Return the first line, the line after the last, and the key indent of a site's entry.

    Raises:
        ValueError: If the `sites:` block or the entry is not found exactly once.
    """
    tops = [i for i, line in enumerate(lines) if line.rstrip() == "sites:"]
    if len(tops) != 1:
        raise ValueError(f"`sites:` found {len(tops)} times at the top level")
    heads = [i for i in range(tops[0] + 1, len(lines))
             if re.match(rf"^(\s+){re.escape(site)}:\s*$", lines[i].rstrip("\r\n"))
             or re.match(rf"^(\s+)['\"]{re.escape(site)}['\"]:\s*$", lines[i].rstrip("\r\n"))]
    if len(heads) != 1:
        raise ValueError(f"{site}: entry found {len(heads)} times under sites:")
    head = heads[0]
    site_indent = len(lines[head]) - len(lines[head].lstrip())
    end, key_indent = len(lines), None
    for i in range(head + 1, len(lines)):
        text = lines[i].rstrip("\r\n")
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        indent = len(text) - len(text.lstrip())
        if indent <= site_indent:
            end = i
            break
        if key_indent is None:
            key_indent = indent
    if key_indent is None:
        raise ValueError(f"{site}: the entry holds no keys (an inline entry is not edited)")
    return head, end, " " * key_indent


def insert_keys(text: str, site: str, keys: dict[str, str], anchor: str = "serial") -> str:
    """Insert keys into one site entry of a survey.yaml text, one line each.

    The lines go after the entry's `anchor:` line when it has one at the
    entry's key indent, else after the entry's own line; each value is
    written in single quotes. The line ending of the text is kept.

    Args:
        text (str): The survey.yaml text.
        site (str): The site.
        keys (dict): Key to value, inserted in this order.
        anchor (str): The key whose line the new lines follow.

    Returns:
        str: The new text.

    Raises:
        ValueError: If the entry is not found once, or holds one of the
            keys already.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    head, end, pad = _entry_bounds(lines, site)
    own = [lines[i] for i in range(head + 1, end)]
    for key in keys:
        if any(re.match(rf"^{pad}{re.escape(key)}\s*:", line) for line in own):
            raise ValueError(f"{site}: {key} is already in the entry")
    at = head
    for i in range(head + 1, end):
        if re.match(rf"^{pad}{re.escape(anchor)}\s*:", lines[i]):
            at = i
            break
    if not lines[at].endswith(("\n", "\r")):
        lines[at] += newline
    added = [f"{pad}{key}: '{value}'{newline}" for key, value in keys.items()]
    return "".join(lines[:at + 1] + added + lines[at + 1:])


def parsed_diff(before: str, after: str) -> dict:
    """Return what a survey.yaml edit changed, parsed.

    Args:
        before (str): The text before.
        after (str): The text after.

    Returns:
        dict: ``{"added": {site: {key: value}}, "other": [descriptions]}``;
        ``other`` lists every change that is not a key added to an existing
        site entry (a changed or removed key, a site added or removed, a
        change outside `sites:`).
    """
    a, b = yaml.safe_load(before) or {}, yaml.safe_load(after) or {}
    other = []
    if {k: v for k, v in a.items() if k != "sites"} != {k: v for k, v in b.items() if k != "sites"}:
        other.append("outside sites:")
    sa, sb = a.get("sites") or {}, b.get("sites") or {}
    if list(sa) != list(sb):
        other.append(f"sites {sorted(set(sa) ^ set(sb))} added or removed")
    added = {}
    for site in sa:
        ea, eb = sa[site] or {}, sb.get(site) or {}
        new = {k: v for k, v in eb.items() if k not in ea}
        changed = [k for k in ea if eb.get(k, object()) != ea[k]]
        if changed:
            other.append(f"{site}: {changed} changed or removed")
        if new:
            added[site] = new
    return {"added": added, "other": other}


def write_keys(path: Path, plan: dict[str, dict[str, str]], stamp: str | None = None) -> Path:
    """Write keys into a survey.yaml the standing way: dated copy, one entry at a time, checked.

    Every step is checked before the next (the parsed change is the entry's
    new keys only) and the whole edit before anything is written (the
    parsed change is `plan` exactly, the comment-line count and the line
    endings unchanged).

    Args:
        path (Path): The survey.yaml.
        plan (dict): Site to {key: value}.
        stamp (str, optional): The copy's stamp, YYYYMMDD-HHMMSS; now when
            None.

    Returns:
        Path: The dated copy written.

    Raises:
        ValueError: If a step or the whole edit fails its check; survey.yaml
            is left as it was.
    """
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = text
    for site, keys in plan.items():
        step = insert_keys(new, site, keys)
        diff = parsed_diff(new, step)
        if diff["other"] or diff["added"] != {site: keys}:
            raise ValueError(f"{site}: the step changes more than its keys: {diff}")
        new = step
    diff = parsed_diff(text, new)
    if diff["other"] or diff["added"] != plan:
        raise ValueError(f"the edit changes more than the planned keys: {diff}")
    if comment_lines(new) != comment_lines(text):
        raise ValueError(f"comment lines {comment_lines(text)} -> {comment_lines(new)}")
    if ("\r\n" in text) != ("\r\n" in new) or new.count("\r\n") not in (text.count("\r\n"),
                                                                        text.count("\r\n") + _count(plan)):
        raise ValueError("line endings changed")
    stamp = stamp or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    copy = path.with_name(f"{path.name}.{COPY_LABEL}_{stamp}")
    shutil.copy2(path, copy)
    path.write_bytes(new.encode("utf-8"))
    return copy


def _count(plan: dict) -> int:
    """Return the number of keys of a plan."""
    return sum(len(keys) for keys in plan.values())


def lookup(survey_yaml: Path, sites: list[str] | None = None, responses: Path | None = None) -> tuple[dict, list]:
    """Search the registry for every serial of a survey without a DOI, printing each candidate.

    Args:
        survey_yaml (Path): The survey.yaml.
        sites (list of str, optional): Only these sites.
        responses (Path, optional): Saved responses (`fetch`).

    Returns:
        tuple: ``(plan, report)``: the plan (site to {key: DOI}) of the
        serials with exactly one proposed record, and one dict per serial
        searched (site, key, serial, candidates, verdict).

    Raises:
        RegistryError: If the registry is not reached.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(survey_yaml)
    config = yaml.safe_load(Path(survey_yaml).read_text(encoding="utf-8")) or {}
    rows = [r for r in wanted(config, survey.instrument_of) if sites is None or r[0] in sites]
    cache: dict[str, dict] = {}
    plan: dict[str, dict[str, str]] = {}
    report = []
    for site, key, serial, tokens in rows:
        if serial not in cache:
            cache[serial] = fetch(serial, responses)
        entry = (config.get("sites") or {}).get(site) or {}
        start, end = entry.get("start"), entry.get("end")
        found = candidates(cache[serial], serial, tokens)
        print(f"{site} {key} {serial} ({'model ' + '/'.join(tokens) if tokens else 'any model'}): "
              f"{len(found)} record(s); site span {start or '?'} to {end or '?'}")
        kept = []
        for c in found:
            cover = dates_cover(c, start, end)
            print(f"    {c['doi']}  {c['title']} | model {c['model'] or '?'} | inventory "
                  f"{', '.join(c['inventory']) or '-'} | commissioned {c['commissioned'] or '?'}, decommissioned "
                  f"{c['decommissioned'] or '-'} | dates {'cover' if cover else 'unknown' if cover is None else 'EXCLUDE'} "
                  f"the site's span")
            if cover is not False:
                kept.append(c)
        if len(kept) == 1:
            verdict = f"propose {SERIAL_KEYS[key]}: {kept[0]['doi']}"
            plan.setdefault(site, {})[SERIAL_KEYS[key]] = kept[0]["doi"]
        elif not kept:
            verdict = "no record: nothing written"
        else:
            verdict = f"ambiguous ({len(kept)} records): nothing written"
        print(f"    -> {verdict}")
        report.append({"site": site, "key": key, "serial": serial, "candidates": found, "verdict": verdict})
    if not rows:
        print("no site with a serial and no DOI declared")
    return plan, report


def main(argv=None) -> int:
    """Run the lookup from the command line; returns the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("survey_yaml", type=Path)
    parser.add_argument("--site", nargs="+", default=None, help="only these sites")
    parser.add_argument("--write", action="store_true", help="write the proposed keys into survey.yaml")
    parser.add_argument("--responses", type=Path, default=None,
                        help="folder of saved search responses <serial>.json, read instead of the network")
    args = parser.parse_args(argv)
    try:
        plan, _report = lookup(args.survey_yaml, args.site, args.responses)
    except RegistryError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    if not args.write:
        print(f"proposed: {_count(plan)} key(s) at {len(plan)} site(s); --write writes them")
        return 0
    if not plan:
        print("nothing to write")
        return 0
    try:
        copy = write_keys(args.survey_yaml, plan)
    except ValueError as exc:
        print(f"ERROR {exc}; nothing written", file=sys.stderr)
        return 2
    print(f"written: {_count(plan)} key(s) at {len(plan)} site(s) into {args.survey_yaml} (copy {copy.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
