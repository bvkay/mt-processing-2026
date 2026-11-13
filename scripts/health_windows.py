# -*- coding: utf-8 -*-
"""
Per-mode processing windows from a health table

scripts/health_table.py writes <workspace>/qc/.../health_weeks.csv: per site
and week (UTC), whether H, Ex and Ey are sound (`H_ok`, `Ex_ok`, `Ey_ok`;
`mt_workbench.health`). Where an electric line dies mid-record, the
whole-record product carries the dead weeks (the SA AusLAMP Flinders trial:
FR01 xy at 0.0014 of the 2018 level, FR25 xy at 0.005).
This script turns the table into one processing window per site and mode:

- xy takes the weeks in which Ex and the H pair are both sound, yx those in
  which Ey and the pair are: the pair-only verdict `Hpair_ok` (a
  dead hz costs the tipper, not the impedance), or `H_ok` for a table written
  before that column existed (the tipper is not windowed here and keeps H_ok);
- the window is the longest run of consecutive such weeks, from the first
  week's start to the last week's end; of two runs of the same number of
  weeks the one holding more windows (`n_windows`), then the earlier;
- "whole" when every week of the site is sound for the mode (the Queensland
  default, whole record, applies), null when none is ("no sound week": the
  mode is not produced).

Each site gets a `reason`: "whole record" when both modes are whole, else one
clause per mode, e.g. "xy: Ex sound week 1 of 4; yx: whole record", "xy: Ex
sound weeks 1-2 of 4 (also week 4; the longest sound run taken)", "yx: no
sound week", with "(H unsound weeks 3)" when H decided it. A survey site
derived from a table site (survey.yaml `derived_from`, the decimated <site>L
family) gets the table site's windows clipped to its own start and end, and
`from: <table site>`; the table site keeps its own entry.

The output, <survey folder>/health_windows.yaml unless --out names another
file, is the campaign plan key `windows: health_windows.yaml`
(scripts/campaign.py): stage 3 runs a site once per distinct window on its
stage 3 remote and merges the xy row of one product with the yx row of the
other with scripts/merge_modes.py; the full-record default run stays on
record. Times are UTC, "YYYY-MM-DD HH:MM:SS".

Usage:
    python scripts/health_windows.py <survey.yaml> <health_weeks.csv> [--out FILE]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench.survey import Survey  # noqa: E402

MODES = {"xy": "Ex_ok", "yx": "Ey_ok"}  # mode: the electric line's column
LINE = {"xy": "Ex", "yx": "Ey"}
H_COLUMN = "Hpair_ok"  # xy and yx take the pair-only H verdict; a table without it falls back to H_ok
FMT = "%Y-%m-%d %H:%M:%S"


def _flag(value) -> bool:
    """Read a health-table flag (bool, or the text True/False) as a bool."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value) if pd.notna(value) else False


def _weeks_text(weeks: list[int]) -> str:
    """Return "week 3" or "weeks 1-2" for consecutive week numbers, "weeks 1, 3-4" otherwise."""
    if not weeks:
        return "no week"
    parts, start = [], weeks[0]
    for a, b in zip(weeks, weeks[1:] + [None]):
        if b != a + 1:
            parts.append(f"{start}" if start == a else f"{start}-{a}")
            start = b
    return ("week " if len(weeks) == 1 else "weeks ") + ", ".join(parts)


def mode_window(table: pd.DataFrame, mode: str) -> tuple[object, str]:
    """Return one mode's window and its reason clause from one site's weeks.

    Args:
        table (pd.DataFrame): The site's rows of health_weeks.csv.
        mode (str): "xy" or "yx".

    Returns:
        tuple: (window, text): "whole", None, or [start, end] (UTC text),
        and the clause after "<mode>: ".
    """
    t = table.sort_values("week")
    weeks = [int(w) for w in t["week"]]
    h_col = H_COLUMN if H_COLUMN in t.columns else "H_ok"     # the pair verdict for the impedance modes
    h_ok = [_flag(v) for v in t[h_col]]
    e_ok = [_flag(v) for v in t[MODES[mode]]]
    ok = [a and b for a, b in zip(h_ok, e_ok)]
    n = len(weeks)
    h_bad = [w for w, h, e in zip(weeks, h_ok, e_ok) if e and not h]
    h_note = f" ({'H pair' if h_col == H_COLUMN else 'H'} unsound {_weeks_text(h_bad)})" if h_bad else ""
    if all(ok):
        return "whole", "whole record"
    if not any(ok):
        return None, "no sound week" + h_note
    runs, cur = [], []
    for i, flag in enumerate(ok):
        if flag:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    nwin = [float(x) if pd.notna(x) else 0.0 for x in t.get("n_windows", pd.Series([0] * n))]
    best = max(runs, key=lambda r: (len(r), sum(nwin[i] for i in r), -r[0]))
    rows = t.iloc[best]
    start = pd.Timestamp(rows["start"].iloc[0])
    end = pd.Timestamp(rows["end"].iloc[-1])
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    taken = [weeks[i] for i in best]
    others = [weeks[i] for r in runs if r is not best for i in r]
    text = f"{LINE[mode]} sound {_weeks_text(taken)} of {n}"
    if others:
        text += f" (also {_weeks_text(others)}; the longest sound run taken)"
    return [start.strftime(FMT), end.strftime(FMT)], text + h_note


def site_entry(table: pd.DataFrame) -> dict:
    """Return one site's entry: {"xy", "yx", "reason"}, and "tipper": None for a site archived without hz."""
    out, clauses = {}, []
    for mode in MODES:
        out[mode], text = mode_window(table, mode)
        clauses.append(f"{mode}: {text}")
    out["reason"] = "whole record" if out["xy"] == out["yx"] == "whole" else "; ".join(clauses)
    if "hz_present" in table.columns and not any(_flag(v) for v in table["hz_present"]):
        # an archive without hz (a dead hz left out at ingest): no tipper to window (campaign.py reads xy and yx only)
        out["tipper"] = None
        out["reason"] += "; tipper: no hz"
    return out


def _clip(window, start: pd.Timestamp | None, end: pd.Timestamp | None):
    """Clip a [start, end] window to a site's span; "whole" and None pass through; None when no part of it lies in the span."""
    if not isinstance(window, list):
        return window
    a, b = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC")
    if start is not None:
        a = max(a, start)
    if end is not None:
        b = min(b, end)
    return [a.strftime(FMT), b.strftime(FMT)] if b > a else None


def _utc(value) -> pd.Timestamp | None:
    """A survey.yaml time as a UTC Timestamp, None when absent."""
    if not value:
        return None
    t = pd.Timestamp(str(value))
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def build_windows(survey_yaml, health_csv) -> dict:
    """Return {site: entry} for every site of the table and every survey site derived from one.

    Args:
        survey_yaml (str | Path): The survey.
        health_csv (str | Path): health_table.py's health_weeks.csv.

    Returns:
        dict: {site: {"xy", "yx", "reason"}}, plus "from" for a derived site.
    """
    survey = Survey.from_yaml(survey_yaml)
    table = pd.read_csv(health_csv)
    need = {"site", "week", "start", "end", "H_ok", "Ex_ok", "Ey_ok"}
    missing = need - set(table.columns)
    if missing:
        raise ValueError(f"{health_csv}: no column(s) {sorted(missing)} (scripts/health_table.py writes them)")
    table["site"] = table["site"].astype(str)
    out = {}
    for site, rows in table.groupby("site", sort=True):
        out[site] = site_entry(rows)
    for name in survey.site_names():
        cfg = survey.site(name)
        base = survey.parent_of(name)
        if not base or str(base) not in out or name in out:
            continue
        e = out[str(base)]
        start, end = _utc(cfg.start), _utc(cfg.end)
        out[name] = {"xy": _clip(e["xy"], start, end), "yx": _clip(e["yx"], start, end), "reason": e["reason"],
                     "from": str(base)}
    return out


def main(argv=None) -> int:
    """Write health_windows.yaml; return 0."""
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("survey_yaml")
    p.add_argument("health_csv")
    p.add_argument("--out", default=None, help="the file to write; default <survey folder>/health_windows.yaml")
    args = p.parse_args(argv)
    windows = build_windows(args.survey_yaml, args.health_csv)
    out = Path(args.out) if args.out else Path(args.survey_yaml).resolve().parent / "health_windows.yaml"
    head = (f"# Per-mode processing windows from {Path(args.health_csv)} (scripts/health_windows.py, "
            f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}).\n"
            "# xy: the longest run of weeks with Ex and H sound; yx: Ey and H. whole = every week sound (the whole\n"
            "# record); null = no sound week (the mode is not produced). Times UTC. Campaign plan key\n"
            "# `windows: health_windows.yaml` (scripts/campaign.py stage 3).\n")
    body = yaml.safe_dump({"source": str(Path(args.health_csv)), "sites": windows}, sort_keys=False, width=200)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(head + body, encoding="utf-8")
    tmp.replace(out)
    counts = {k: 0 for k in ("whole", "windowed", "none")}
    for e in windows.values():
        for mode in MODES:
            counts["whole" if e[mode] == "whole" else "none" if e[mode] is None else "windowed"] += 1
    print(f"wrote {out}: {len(windows)} site(s); modes {counts['whole']} whole, {counts['windowed']} windowed, "
          f"{counts['none']} with no sound week")
    return 0


if __name__ == "__main__":
    sys.exit(main())
