# -*- coding: utf-8 -*-
"""
Fill each site's magnetic declination in survey.yaml from the IGRF

Every product stays in the sensor (geomagnetic) frame and is never rotated
at processing; the declination is stored with it so a modeller can rotate
once, inside the inversion (`mt_workbench.products`). This script computes,
for each site of a survey.yaml, the declination of the International
Geomagnetic Reference Field with the ppigrf package (pure Python, its
newest coefficient file, IGRF-14 in ppigrf 2.1.0) at the site's latitude,
longitude and elevation (geodetic, elevation 0 m when unset) and at the
midpoint of its record (`start:` and `end:`, UTC; `start:` alone when there
is no end), as a decimal year. The declination is
``atan2(Be, Bn)`` in degrees, east positive. It goes into the site entry as
three keys (`mt_workbench.survey.SiteConfig`):

    declination: -1.07          # degrees east of geographic north, 2 decimals
    declination_model: IGRF-14  # the coefficient file ppigrf used
    declination_epoch: 2023.53  # the decimal year, 2 decimals

A site without a position or a start is skipped and listed.

--dry-run (the default) prints a table: site, latitude, longitude,
elevation, epoch, declination, model and the value survey.yaml holds now.
--write updates survey.yaml in place by lines: a site's existing
declination keys are replaced on their own lines, missing ones are added
after the entry's last line, and every other line is kept byte for byte,
comments and line endings included. Before the file is written the new
text is parsed and compared with the old: every site's other keys and
every top-level key must be equal, or nothing is written (exit 2).
--check SITE=DEG ... compares the fill of the named sites with the values
given (e.g. from the NOAA calculator) within --tol degrees (0.05) and exits
1 when one differs. --self-test runs the script's own check against the
NOAA calculator (DGRF2020, mid-2023): the fill at 31.87 N 7.93 W, 567 m,
2023.53 must give -1.07 deg and at 33.0 N 3.4 W, 0 m, 2023.53 +0.20 deg,
each within 0.05 deg; the same check with the signs flipped is the control
and must fail.

Exit status: 0 done, 1 a check failed, 2 a usage error, an unreadable
sites block or a write that would change anything else.

Usage:
    python scripts/declination.py <survey.yaml> [SITE ...] [--dry-run | --write]
    python scripts/declination.py <survey.yaml> --check B03=-1.07 R01=-1.05 [--tol 0.05]
    python scripts/declination.py --self-test

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
from pathlib import Path

import yaml

KEYS = ("declination", "declination_model", "declination_epoch")
TOL = 0.05  # degrees, the --check and self-test tolerance
# the NOAA calculator's values (DGRF2020, mid-2023), east positive: (lat, lon, elevation m, epoch, degrees)
NOAA_CONTROLS = ((31.87, -7.93, 567.0, 2023.53, -1.07), (33.0, -3.4, 0.0, 2023.53, 0.20))
SITE_LINE = re.compile(r"^  (?P<q>['\"]?)(?P<name>[^'\"#\s][^'\"#:]*?)(?P=q):\s*(?:#.*)?$")
KEY_LINE = re.compile(r"^(?P<indent>[ ]+)(?P<key>declination_model|declination_epoch|declination):")


def decimal_year(when) -> float:
    """Return a UTC instant as a decimal year (2023-07-13T00:00Z is 2023.53)."""
    import pandas as pd

    t = pd.Timestamp(when)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    start = pd.Timestamp(year=t.year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=t.year + 1, month=1, day=1, tz="UTC")
    return t.year + (t - start) / (end - start)


def model_name() -> str:
    """Return the name of ppigrf's default coefficient file, e.g. "IGRF-14"."""
    import ppigrf

    stem = Path(ppigrf.ppigrf.shc_fn).stem  # "IGRF14"
    m = re.match(r"([A-Za-z]+)(\d+)$", stem)
    return f"{m.group(1).upper()}-{m.group(2)}" if m else stem


def igrf_declination(latitude: float, longitude: float, elevation_m: float, epoch: float) -> float:
    """Return the IGRF declination in degrees, east positive.

    Args:
        latitude (float): Geodetic latitude in degrees.
        longitude (float): Longitude in degrees, east positive.
        elevation_m (float): Height above the ellipsoid in m.
        epoch (float): Decimal year.

    Returns:
        float: ``atan2(Be, Bn)`` in degrees.
    """
    import numpy as np
    import ppigrf

    year = int(math.floor(epoch))
    t0 = dt.datetime(year, 1, 1)
    when = t0 + (dt.datetime(year + 1, 1, 1) - t0) * (epoch - year)
    be, bn, _bu = ppigrf.igrf(longitude, latitude, elevation_m / 1000.0, when)
    return float(np.degrees(np.arctan2(np.ravel(be)[0], np.ravel(bn)[0])))


def site_epoch(entry: dict) -> float | None:
    """Return the decimal year of the midpoint of a site's record, None without a start."""
    import pandas as pd

    if not entry.get("start"):
        return None
    start = pd.Timestamp(entry["start"])
    end = pd.Timestamp(entry["end"]) if entry.get("end") else start
    return decimal_year(start + (end - start) / 2)


def fill(entry: dict) -> dict | None:
    """Return a site entry's three declination keys, None when it has no position or start.

    Args:
        entry (dict): The merged site settings (defaults and the entry).

    Returns:
        dict or None: ``{declination, declination_model, declination_epoch}``,
        the declination and epoch rounded to 2 decimals, plus ``raw``, the
        unrounded declination.
    """
    lat, lon = entry.get("latitude"), entry.get("longitude")
    epoch = site_epoch(entry)
    if lat is None or lon is None or epoch is None:
        return None
    raw = igrf_declination(float(lat), float(lon), float(entry.get("elevation") or 0.0), epoch)
    value = round(raw, 2)
    value = 0.0 if abs(value) < 0.005 else value
    return {"declination": value, "declination_model": model_name(), "declination_epoch": round(epoch, 2),
            "raw": raw}


def value_text(key: str, value) -> str:
    """Format a key's value as the YAML line carries it."""
    return str(value) if key == "declination_model" else f"{float(value):.2f}"


def sites_block(lines: list[str]) -> tuple[int, int]:
    """Return the line span [start, end) of the top-level `sites:` block.

    Raises:
        ValueError: If there is not exactly one `sites:` line.
    """
    starts = [i for i, line in enumerate(lines) if re.match(r"^sites:\s*(?:#.*)?$", line.rstrip("\r\n"))]
    if len(starts) != 1:
        raise ValueError(f"expected one top-level 'sites:' line, found {len(starts)}")
    start = starts[0]
    end = next((k for k in range(start + 1, len(lines))
                if lines[k].strip() and not lines[k].startswith((" ", "\t", "#"))), len(lines))
    return start, end


def entry_spans(lines: list[str], start: int, end: int) -> dict[str, tuple[int, int]]:
    """Return each site entry's line span [header, next header) inside the sites block."""
    heads = [(i, SITE_LINE.match(lines[i].rstrip("\r\n")).group("name"))
             for i in range(start + 1, end) if SITE_LINE.match(lines[i].rstrip("\r\n"))]
    return {name: (i, heads[k + 1][0] if k + 1 < len(heads) else end) for k, (i, name) in enumerate(heads)}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def set_keys(text: str, values: dict[str, dict]) -> str:
    """Write the declination keys of the given sites into survey.yaml text, by lines.

    Args:
        text (str): The survey.yaml text, line endings as read.
        values (dict): ``{site: {declination, declination_model,
            declination_epoch}}``.

    Returns:
        str: The new text: each site's existing key lines replaced in place,
        missing ones added after the entry's last indented line, every other
        line unchanged.

    Raises:
        ValueError: If the sites block is not found or a site has no block
            entry (``  <site>:`` on a line of its own).
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    start, end = sites_block(lines)
    spans = entry_spans(lines, start, end)
    missing = [s for s in values if s not in spans]
    if missing:
        raise ValueError(f"no block entry '  <site>:' for {', '.join(missing)}")
    inserts: dict[int, list[str]] = {}
    for site, keys in values.items():
        head, stop = spans[site]
        body = range(head + 1, stop)
        content = [i for i in body if lines[i].strip() and not lines[i].lstrip().startswith("#")]
        pad = " " * (_indent(lines[content[0]]) if content else 4)
        found = {}
        for i in body:
            m = KEY_LINE.match(lines[i])
            if m and m.group("indent") == pad:
                found[m.group("key")] = i
        for key in KEYS:
            line = f"{pad}{key}: {value_text(key, keys[key])}"
            if key in found:
                i = found[key]
                ending = lines[i][len(lines[i].rstrip("\r\n")):] or newline
                lines[i] = line + ending
        last = max([i for i in body if lines[i].strip() and _indent(lines[i]) > 2], default=head)
        new = [f"{pad}{key}: {value_text(key, keys[key])}{newline}" for key in KEYS if key not in found]
        if new:
            inserts.setdefault(last, []).extend(new)
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        out.extend(inserts.get(i, []))
    return "".join(out)


def check_unchanged(old: str, new: str, values: dict[str, dict]) -> list[str]:
    """Compare two survey.yaml texts: only the declination keys of the given sites may differ.

    Returns:
        list[str]: One line per difference found; empty when the new text is
        the old one plus the given values.
    """
    a, b = yaml.safe_load(old) or {}, yaml.safe_load(new) or {}
    found = [f"top-level key {k} changed" for k in set(a) | set(b) if k != "sites" and a.get(k) != b.get(k)]
    sa, sb = a.get("sites") or {}, b.get("sites") or {}
    if list(sa) != list(sb):
        found.append("the sites or their order changed")
    for site in sb:
        ea, eb = dict(sa.get(site) or {}), dict(sb.get(site) or {})
        if site in values:
            for key in KEYS:
                want = values[site][key]
                got = eb.pop(key, None)
                if (str(got) != str(want)) if key == "declination_model" else \
                        (got is None or abs(float(got) - float(want)) > 1e-9):
                    found.append(f"{site} {key}: {got!r}, wanted {want!r}")
                ea.pop(key, None)
        if ea != eb or list(ea) != list(eb):
            found.append(f"{site}: other keys changed")
    return found


def merged_entries(config: dict) -> dict[str, dict]:
    """Return each site's settings with the `defaults:` block under them, as `Survey.site` merges them."""
    defaults = config.get("defaults") or {}
    return {site: {**defaults, **(entry or {})} for site, entry in (config.get("sites") or {}).items()}


def self_test() -> int:
    """Check the fill against the NOAA controls, and the sign-flipped control that must fail.

    Returns:
        int: 0 when the controls pass and the flipped control fails, else 1.
    """
    print(f"criterion: the fill must match the NOAA calculator within {TOL} deg at each control; "
          "the control with the signs flipped must not match")
    ok = True
    for lat, lon, elev, epoch, want in NOAA_CONTROLS:
        got = igrf_declination(lat, lon, elev, epoch)
        good = abs(got - want) <= TOL
        flipped = abs(got - (-want)) <= TOL
        ok &= good and not flipped
        print(f"  {lat:.2f} {lon:+.2f} {elev:.0f} m {epoch:.2f}: {got:+.3f} deg ({model_name()}), NOAA {want:+.2f}: "
              f"{'PASS' if good else 'FAIL'}; flipped {-want:+.2f}: {'matches (BAD)' if flipped else 'fails (as it must)'}")
    print("self-test " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None) -> int:
    """Fill, write or check the declination keys of a survey.yaml.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: The exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml", nargs="?", help="the survey.yaml")
    parser.add_argument("sites", nargs="*", help="sites to fill (default: every site of the sites block)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the table only (the default)")
    mode.add_argument("--write", action="store_true", help="write the keys into survey.yaml, by lines")
    mode.add_argument("--check", nargs="+", metavar="SITE=DEG", help="compare the fill with the values given")
    mode.add_argument("--self-test", action="store_true", help="check the fill against the NOAA controls")
    parser.add_argument("--tol", type=float, default=TOL, help=f"--check tolerance in degrees ({TOL})")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.survey_yaml:
        parser.print_usage(sys.stderr)
        print("ERROR survey.yaml needed", file=sys.stderr)
        return 2

    path = Path(args.survey_yaml)
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    config = yaml.safe_load(text) or {}
    entries = merged_entries(config)
    expected = {}
    if args.check:
        for item in args.check:
            site, _, value = item.partition("=")
            try:
                expected[site] = float(value)
            except ValueError:
                print(f"ERROR --check {item}: SITE=DEG wanted", file=sys.stderr)
                return 2
    wanted = list(expected) or args.sites or list(entries)
    unknown = [s for s in wanted if s not in entries]
    if unknown:
        print(f"ERROR not in the sites block: {', '.join(unknown)}", file=sys.stderr)
        return 2

    values, skipped = {}, []
    for site in wanted:
        got = fill(entries[site])
        if got is None:
            skipped.append(site)
        else:
            values[site] = got
    print(f"{'site':<10} {'lat':>10} {'lon':>11} {'elev m':>8} {'epoch':>8} {'decl':>7}  {'model':<8} stored")
    for site, v in values.items():
        e = entries[site]
        stored = e.get("declination")
        print(f"{site:<10} {float(e['latitude']):>10.5f} {float(e['longitude']):>11.5f} "
              f"{float(e.get('elevation') or 0.0):>8.1f} {v['declination_epoch']:>8.2f} {v['declination']:>+7.2f}  "
              f"{v['declination_model']:<8} {'-' if stored is None else f'{float(stored):+.2f}'}")
    if skipped:
        print(f"skipped (no position or no start): {', '.join(skipped)}")

    if args.check:
        print(f"criterion: each fill within {args.tol} deg of the value given")
        bad = 0
        for site, want in expected.items():
            if site not in values:
                print(f"  {site}: no fill (no position or no start): FAIL")
                bad += 1
                continue
            diff = values[site]["raw"] - want
            good = abs(diff) <= args.tol
            bad += not good
            print(f"  {site}: fill {values[site]['raw']:+.3f}, given {want:+.2f}, difference {diff:+.3f}: "
                  f"{'PASS' if good else 'FAIL'}")
        print("check " + ("PASS" if not bad else f"FAIL ({bad} site(s))"))
        return 1 if bad else 0

    if not args.write:
        print(f"dry run: {len(values)} site(s) filled, nothing written (--write writes them)")
        return 0
    keys = {site: {k: v[k] for k in KEYS} for site, v in values.items()}
    try:
        new = set_keys(text, keys)
    except ValueError as exc:
        print(f"ERROR {path.name}: {exc}", file=sys.stderr)
        return 2
    found = check_unchanged(text, new, keys)
    if found:
        for line in found:
            print(f"ERROR {line}", file=sys.stderr)
        print(f"ERROR {path.name} not written", file=sys.stderr)
        return 2
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(new)
    changed = sum(1 for s in keys if entries[s].get("declination") != keys[s]["declination"])
    print(f"wrote {path}: {len(keys)} site(s), {changed} declination value(s) new or changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
