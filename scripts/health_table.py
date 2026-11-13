# -*- coding: utf-8 -*-
"""
The Queensland health table of a survey's sites: per site, UTC week and channel group, sound or not

A port of the Queensland inspection table; the maths
is `mt_workbench.health` (its docstring gives the rules, the thresholds and
the departures forced by gaps). Per site this script reads the raw archive
(`mt_workbench.ingest.default_archive_path`) with
`mt_workbench.timefreq.load_station` (every run on one calibrated grid, NaN
in gaps; `Record.value` puts the DC level back, so H is in nT with its mean
field), takes each channel to 1 Hz with `mt_workbench.health.to_1hz` (a
10 Hz record decimated as the Queensland 1 Hz cache was, gaps up to 600 s
filled; a 1 Hz record kept), and evaluates the weeks
(`mt_workbench.health.health_record`). E is used as the archive holds it
(the coherences do not see its sign), except at a rot_e site (`archive_rot_e`
not None): there the archive's ex, ey are E_N, E_E, mixtures of the
two recorded lines, so the turn is undone first (`recorded_e`, the inversion
of scripts/diagonal_site.py on calibrated samples) and each recorded line is
paired with the H perpendicular to the direction it measures along
(`health_record(..., e_dirs=...)`); the per-line verdicts (Ex_ok, Ey_ok,
centre_flag, the swapped test) then describe the lines as laid.
Both CSVs carry `e_frame` ("recorded" there, "archive" elsewhere) and the
printed line ends "lines: recorded (...)". An archive without hz (a dead hz
left out at ingest) is evaluated: F and the hz fields NaN, H_ok
False, Hpair_ok and the E verdicts on the pair, `hz_present` False in both
CSVs and "no hz" on the printed line.

Outputs, in ``<workspace>/qc/health/`` (or ``--out``), rewritten as each
site's rows come:
- ``health_table.csv``: one row per site and channel group (H, Ex, Ey), the
  Queensland columns (site, channel, weeks_sound, weeks_total, first_sound,
  last_sound, fraction_sound, e_swapped, sound_weeks, unsound_weeks) plus
  instrument, archive, t0, t1, windows_total (hourly window slots in the
  record), windows_used (finite windows in the weeks that count), and the
  departure's H_component_ok_weeks (on the H row: weeks whose hx, hy, hz
  deviations are all within `COMPONENT_TOL`, see `mt_workbench.health`;
  blank on Ex and Ey), and the pair-only Hpair_ok_weeks (H row)
  and igrf_H;
- ``health_weeks.csv``: one row per site and week (site, week, start, end
  as UTC ISO, n_windows, F, angle, hxhy_hi, hxhy_med, ex, ey, H_ok, Ex_ok,
  Ey_ok, and the departure's hx_med, hy_med, hz_med (nT), hx_dev, hy_dev,
  hz_dev, H_component_ok, ..., and the pair-only verdict H_pair, H_igrf_ratio,
  Hpair_ok: the Hx-Hy rules and |H| within `H_IGRF_BAND` of the IGRF H, no hz
  term; H_ok also needs that |H| band, so H_ok implies Hpair_ok).
Each site prints the Queensland one-line summary with " comp n/N" (the
component check's sound weeks) and " pair n/N" (Hpair_ok weeks) appended.

Memory: a worker holds a site's five channels at the native rate as float32
plus one float64 channel during `to_1hz`: about 0.45 GB + 0.18 GB for a
26-day 10 Hz record (about 17 MB per channel-day at 10 Hz), so the default
``--workers 2`` needs about 1.3 GB.

A site that fails (no archive, a channel missing, a rate that is not an
integer number of Hz) is reported and the run goes on.

Exit status: 0 every site done, 1 a site failed (listed), 2 a usage error.

Usage:
    python scripts/health_table.py <survey.yaml> [SITE ...] [--workers N] [--out DIR]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from mt_workbench import health as HL  # noqa: E402
from mt_workbench.ingest import archive_rot_e, default_archive_path  # noqa: E402
from diagonal_site import recorded_directions, unturn_matrix  # noqa: E402  (the rot_e undo)
from mt_workbench.survey import OBSERVATORY, Survey  # noqa: E402
from h_azimuth import igrf_field  # noqa: E402  (the IGRF F at the site)

CHANNELS = ("hx", "hy", "hz", "ex", "ey")
TABLE_COLUMNS = ("site", "channel", "weeks_sound", "weeks_total", "first_sound", "last_sound", "fraction_sound",
                 "e_swapped", "sound_weeks", "unsound_weeks", "instrument", "archive", "t0", "t1",
                 "windows_total", "windows_used", "H_component_ok_weeks", "centre_weeks", "igrf_F",
                 "Hpair_ok_weeks", "igrf_H", "e_frame", "hz_present")
WEEK_COLUMNS = ("site", "week", "start", "end", "n_windows", "F", "angle", "hxhy_hi", "hxhy_med", "ex", "ey",
                "H_ok", "Ex_ok", "Ey_ok", "hx_med", "hy_med", "hz_med", "hx_dev", "hy_dev", "hz_dev",
                "H_component_ok", "exey_med", "centre_flag", "F_igrf_ratio", "F_igrf_ok", "H_pair", "H_igrf_ratio",
                "Hpair_ok", "e_frame", "hz_present")


def recorded_e(ex, ey, laid: tuple[float, float] | None):
    """Undo a rot_e turn on calibrated E: the lines as recorded, from the archive's E_N and E_E.

    The ingest's `_rot_e` wrote [E_N; E_E] = inv(M) [E_bx; E_by] in calibrated
    terms, M = [[cos b_x, sin b_x], [cos b_y, sin b_y]], b the directions the
    recorded lines measure along (`diagonal_site.recorded_directions` of the
    as-laid azimuths, `_e_direction`). diagonal_site.py undoes it in the
    logger's words with `unturn_matrix(b_x, b_y, k)`, k = g_y / g_x the ratio
    of the two dipole gains, because there each channel's counts carry its
    own gain; on calibrated samples the gains are already divided out, so
    the same matrix with k = 1 (= M) is exact: [E_bx; E_by] = M [E_N; E_E],
    each recorded line in mV/km along the direction it measures (the words
    route divided by that line's own chain).

    Args:
        ex, ey (array): The archive's calibrated ex and ey (E_N, E_E).
        laid (tuple or None): The as-laid azimuths of `archive_rot_e`, None at
            a cardinal archive.

    Returns:
        tuple or None: (x, y, (b_x, b_y), M), None when `laid` is None.
    """
    if laid is None:
        return None
    bx, by = recorded_directions(laid)
    m = unturn_matrix(bx, by, 1.0)
    ex = np.asarray(ex, dtype="float64")
    ey = np.asarray(ey, dtype="float64")
    return m[0, 0] * ex + m[0, 1] * ey, m[1, 0] * ex + m[1, 1] * ey, (bx, by), m


def load_survey(path: Path) -> Survey:
    """Survey from its survey.yaml, ``Survey(yaml.safe_load(text), path.parent)``."""
    return Survey(yaml.safe_load(path.read_text(encoding="utf-8")), path.parent)


def iso(t: pd.Timestamp) -> str:
    """UTC ISO 8601 to the second, ``YYYY-MM-DDTHH:MM:SSZ``."""
    t = pd.Timestamp(t)
    t = t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def site_rows(survey_yaml: str, site: str) -> dict:
    """Evaluate one site; run in a worker process, so it takes the survey.yaml path.

    Returns:
        dict: ``table`` (3 rows), ``weeks`` (week rows), ``line`` (the summary).

    Raises:
        FileNotFoundError: No archive.
        ValueError: A channel missing, or a rate that is not an integer number of Hz.
    """
    from mt_workbench.timefreq import load_station

    path = Path(survey_yaml)
    survey = load_survey(path)
    archive = default_archive_path(survey, site)
    if not archive.exists():
        raise FileNotFoundError(f"no archive {archive}")
    rec = load_station(archive, survey.name, site, comps=CHANNELS)
    # hz may be absent (a dead hz left out at ingest): the pair and E verdicts stand, H_ok is False
    missing = [c for c in CHANNELS if c not in rec.arrays and c != "hz"]
    if missing:
        raise ValueError(f"channels {missing} not in the archive")
    has_hz = "hz" in rec.arrays
    fs = rec.sample_rate
    # at a rot_e site the archive's ex, ey are E_N, E_E; judge the lines as recorded (the turn undone)
    laid = archive_rot_e(archive, site)
    one = {}
    for c in ("hx", "hy", "hz"):
        if c == "hz" and not has_hz:
            one[c] = None
            continue
        one[c] = HL.to_1hz(rec.value(c), fs, gaps=rec.gaps)
        rec.arrays[c] = None                       # free the native channel once it is at 1 Hz
    e_dirs = None
    und = recorded_e(rec.value("ex"), rec.value("ey"), laid)
    if und is None:
        e_native = {"ex": rec.value("ex"), "ey": rec.value("ey")}
    else:
        e_native = {"ex": und[0], "ey": und[1]}
        e_dirs = und[2]
    del und
    rec.arrays["ex"] = rec.arrays["ey"] = None
    for c in ("ex", "ey"):
        one[c] = HL.to_1hz(e_native[c], fs, gaps=rec.gaps)
        e_native[c] = None
    e_frame = "archive" if laid is None else "recorded"
    t0 = pd.Timestamp(rec.t0)
    # the IGRF F at the site and the record midpoint: a dead fluxgate passes the Queensland median-F test,
    # so H_ok also needs F within HL.F_IGRF_BAND of it
    cfg = survey.site(site)
    mid = t0 + pd.Timedelta(seconds=len(one["hx"]) / 2.0)
    igrf = igrf_field(float(cfg.latitude), float(cfg.longitude), float(cfg.elevation or 0.0), mid)
    f_igrf, h_igrf = igrf["F"], igrf["H"]          # h_igrf: the pair-only verdict Hpair_ok
    r = HL.health_record(t0, 1.0, one["hx"], one["hy"], one["hz"], one["ex"], one["ey"], f_igrf=f_igrf,
                         h_igrf=h_igrf, e_dirs=e_dirs)
    weeks, n, swapped = r["weeks"], r["n"], r["e_swapped"]

    def day(off):
        return iso(t0 + pd.Timedelta(seconds=off))

    common = dict(instrument=survey.instrument_of(site), archive=str(archive), t0=iso(t0),
                  t1=day(n), windows_total=r["windows_total"], windows_used=r["windows_used"])
    table = []
    for ch, key in (("H", "H_ok"), ("Ex", "Ex_ok"), ("Ey", "Ey_ok")):
        ok = [w for w in weeks if w[key]]
        table.append(dict(site=site, channel=ch, weeks_sound=len(ok), weeks_total=len(weeks),
                          first_sound=day(ok[0]["start"])[:10] if ok else "",
                          last_sound=day(ok[-1]["end"] - 1)[:10] if ok else "",
                          fraction_sound=round(sum(w["end"] - w["start"] for w in ok) / n, 2),
                          e_swapped=bool(swapped),
                          sound_weeks=" ".join(day(w["start"])[5:10] for w in ok),
                          unsound_weeks=" ".join("%s/%s" % (day(w["start"])[:10], day(w["end"] - 1)[:10])
                                                 for w in weeks if not w[key]),
                          H_component_ok_weeks=sum(w["H_component_ok"] for w in weeks) if ch == "H" else "",
                          centre_weeks=sum(w["centre_flag"] for w in weeks),
                          igrf_F=round(f_igrf, 1),
                          Hpair_ok_weeks=sum(w["Hpair_ok"] for w in weeks) if ch == "H" else "",
                          igrf_H=round(h_igrf, 1), e_frame=e_frame, hz_present=has_hz,
                          **common))
    week_rows = [dict(site=site, week=k + 1, start=day(w["start"]), end=day(w["end"]), n_windows=w["n_windows"],
                      F=round(w["F"], 2), angle=round(w["angle"], 3), hxhy_hi=round(w["hxhy_hi"], 4),
                      hxhy_med=round(w["hxhy_med"], 4), ex=round(w["ex"], 4), ey=round(w["ey"], 4),
                      H_ok=w["H_ok"], Ex_ok=w["Ex_ok"], Ey_ok=w["Ey_ok"], hx_med=round(w["hx_med"], 2),
                      hy_med=round(w["hy_med"], 2), hz_med=round(w["hz_med"], 2), hx_dev=round(w["hx_dev"], 6),
                      hy_dev=round(w["hy_dev"], 6), hz_dev=round(w["hz_dev"], 6),
                      H_component_ok=w["H_component_ok"], exey_med=round(w["exey_med"], 4),
                      centre_flag=w["centre_flag"], F_igrf_ratio=round(w["F_igrf_ratio"], 4),
                      F_igrf_ok=w["F_igrf_ok"], H_pair=round(w["H_pair"], 2),
                      H_igrf_ratio=round(w["H_igrf_ratio"], 4), Hpair_ok=w["Hpair_ok"],
                      e_frame=e_frame, hz_present=has_hz) for k, w in enumerate(weeks)]
    # the Queensland printed line (qld_health_table.py), with the component count appended
    line = "%-7s %s H %d/%d  Ex %d/%d  Ey %d/%d  comp %d/%d  pair %d/%d%s" % (
        site, "SWAPPED" if swapped else "       ", sum(w["H_ok"] for w in weeks), len(weeks),
        sum(w["Ex_ok"] for w in weeks), len(weeks), sum(w["Ey_ok"] for w in weeks), len(weeks),
        sum(w["H_component_ok"] for w in weeks), len(weeks), sum(w["Hpair_ok"] for w in weeks), len(weeks),
        "" if all(w["H_ok"] for w in weeks) else "  H unsound: " + " ".join(
            day(w["start"])[5:10] + ("(leak %.2f)" % w["hxhy_med"] if w["hxhy_med"] > HL.HXHY_MED_MAX else "")
            for w in weeks if not w["H_ok"]))
    if sum(w["centre_flag"] for w in weeks):
        line += "  CENTRE %d/%d" % (sum(w["centre_flag"] for w in weeks), len(weeks))
    if not has_hz:
        line += "  no hz"
    if laid is not None:
        line += "  lines: recorded (rot_e laid %g/%g, measuring %g/%g)" % (laid[0], laid[1], e_dirs[0], e_dirs[1])
    return dict(table=table, weeks=week_rows, line=line, fs=fs, angle=r["angle"],
                windows_finite=r["windows_finite"])


def write_csv(rows: list[dict], columns, path: Path) -> None:
    """Write rows with the given columns (a temporary then a rename, so a reader never sees half a file)."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(columns))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})
    tmp.replace(path)


def candidate_sites(survey: Survey, names: list[str] | None) -> tuple[list[str], dict[str, str]]:
    """Sites to evaluate (recorded sites; a derived or burst site and an observatory are left out)."""
    out, skipped = [], {}
    for site in names or survey.site_names():
        try:
            instrument = survey.instrument_of(site)
        except ValueError as exc:
            skipped[site] = f"survey.yaml refuses it: {exc}"
            continue
        if survey.parent_of(site) or survey.bursts_parent(site):
            skipped[site] = "derived or burst site"
        elif instrument == OBSERVATORY:
            skipped[site] = "observatory"
        else:
            out.append(site)
    return out, skipped


def main(argv=None) -> int:
    """Run the table; see the module docstring for the exit status."""
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("survey_yaml")
    p.add_argument("sites", nargs="*", help="sites (default: every recorded site)")
    p.add_argument("--workers", type=int, default=2, help="worker processes (2; ~0.65 GB per 26-day 10 Hz site)")
    p.add_argument("--out", default=None, help="output folder (<workspace>/qc/health)")
    args = p.parse_args(argv)
    path = Path(args.survey_yaml)
    survey = load_survey(path)
    unknown = [s for s in args.sites if s not in survey.site_names()]
    if unknown:
        print(f"ERROR not in survey.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else survey.workspace / "qc" / "health"
    if str(out.resolve()).upper().startswith("E:"):
        print(f"ERROR refusing to write under E: ({out})", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    sites, skipped = candidate_sites(survey, args.sites or None)
    for site, why in skipped.items():
        print(f"skipped {site}: {why}")
    print(f"criterion (Queensland): H sound when |F| is within {100 * HL.F_TOL:g} % of the site's median weekly |F|, "
          f"under {100 * HL.HXHY_HI_MAX:g} % of windows have Hx-Hy > {HL.HXHY_HI_COH} and the median Hx-Hy is at most "
          f"{HL.HXHY_MED_MAX}; Ex (Ey) sound when at least {100 * HL.E_FRAC_MIN:g} % of windows have Hy-Ex (Hx-Ey) "
          f"> {HL.E_COH}, Hx-Ex (Hy-Ey) when swapped; a week counts with >= {HL.MIN_WINDOWS} finite windows",
          flush=True)
    table_rows, week_rows, failed = {}, {}, {}
    table_path, weeks_path = out / "health_table.csv", out / "health_weeks.csv"
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {site: pool.submit(site_rows, str(path), site) for site in sites}
        for site, fut in futures.items():
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001  (one site's failure is listed, the run goes on)
                failed[site] = f"{type(exc).__name__}: {exc}"
                print(f"FAILED {site}: {failed[site]}", flush=True)
                continue
            table_rows[site], week_rows[site] = res["table"], res["weeks"]
            print(res["line"], flush=True)
            print(f"        {res['fs']:g} Hz, angle {res['angle']:+.2f} deg, windows used "
                  f"{res['table'][0]['windows_used']}/{res['table'][0]['windows_total']} "
                  f"(finite {res['windows_finite']})", flush=True)
            write_csv([r for s in sites if s in table_rows for r in table_rows[s]], TABLE_COLUMNS, table_path)
            write_csv([r for s in sites if s in week_rows for r in week_rows[s]], WEEK_COLUMNS, weeks_path)
    print(f"table: {table_path}")
    print(f"weeks: {weeks_path}")
    if failed:
        print(f"{len(failed)} site(s) failed: {', '.join(sorted(failed))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
