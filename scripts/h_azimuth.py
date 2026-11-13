# -*- coding: utf-8 -*-
"""
The fluxgate field of each site against the IGRF, the sensor's azimuth and its `rot_h:` key

A three-component fluxgate records the main field as well as its variations,
so the medians of its record say how the sensor sat: the horizontal field's
direction in the sensor frame is the sensor's azimuth from magnetic north,
and the angle between the field and the sensor's z axis, set against the
IGRF's inclination, bounds its tilt. For each recorded fluxgate site of a
survey.yaml (an EDL site with `sensor_type` bartington, a LEMI-424 site or an Orange Box site;
a site whose channels lack hx or hy, a derived site and an observatory are
left out) this script reads the raw archive
(`mt_workbench.ingest.default_archive_path`) calibrated through its chain by
`mt_workbench.timefreq.load_station`, every run on one grid, with the DC level
added back (`Record.value`), and writes one row:

- the medians of hx, hy and hz in nT, |H| = hypot(hx, hy) and
  F = sqrt(|H|^2 + hz^2) of those medians, and the inclination
  atan2(hz, |H|) (z down, so negative in the southern hemisphere);
- the IGRF at the site's position and the record's midpoint (ppigrf, as
  scripts/declination.py calls it): H, Z (down), F, inclination and
  declination, and the ratios |H| / H, |hz| / |Z| and F / F. F and |hz| test
  the gains (a sensor's attitude does not change F, and moves |hz| by
  the cosine of its tilt); |H| also moves with the tilt, by tan(I) per
  radian, about 5 % per degree at I = -71 deg;
- the tilt estimate, the field-to-z angle arccos(|hz| / F) less the
  IGRF's arccos(|Z| / F): the least tilt of the sensor's z axis in the
  field's plane that explains the record (a tilt about the field's own
  horizontal direction leaves it unchanged, so it is a lower bound);
- the azimuth of the median horizontal field in the archive's frame,
  atan2(median hy, median hx), with the 5 and 95 % points of the hourly
  medians' azimuth and the azimuth of the record's means beside it;
- `rot_h_recorded`, the turn the archive's ingest applied (`mt_workbench.ingest.
  archive_rot_h`, 0 when it records none), and `azimuth_sensor`, the azimuth
  in the sensor's own frame, `azimuth` + `rot_h_recorded` (wrapped to
  (-180, 180]). `rot_h` (`mt_workbench.survey.SiteConfig.rot_h`) is the
  azimuth of magnetic north measured from the sensor's x axis toward its
  y axis, atan2(mean hy, mean hx) in the sensor frame, so the proposed key
  is `azimuth_sensor` rounded to 0.01 deg, the same whether the archive was
  built on the sensor axes or already turned. An archive turned by its
  declared `rot_h` reads `azimuth` 0 within the rounding and the spread of
  a median of turned components;
- `field_flag`: "F" when F / IGRF is outside 0.95-1.05 (a gain or a dead
  channel), "hz" when |hz| / |Z| is, "hz sign" when the median hz is not
  negative (z down in the south), "moved" when the hourly azimuth's 5-95 %
  spread exceeds `MOVED_DEG` (a sensor turned during the record; one
  `rot_h` cannot serve both parts).

`--neighbours` adds the independent check of the azimuth from the
variation field: for each site, the inter-site magnetic tensor M of
H_local = M H_base (`scripts/process_intersite.py --kind magnetic`,
remote-referenced to a third site, products in
`<workspace>/tf/h_azimuth/`) against the best concurrent neighbour, the
nearest site whose record overlaps half of the local's, referenced to the
nearest other site that overlaps both. Where the external field is uniform
M is near k R(phi), R = [[cos, sin], [-sin, cos]], phi the turn from the
base's sensor x axis to the local's; level sensors at the mean-field
azimuths a_base and a_local give phi = a_base - a_local. Per period of
10-3,000 s phi and k are fitted by weighted least squares
(`rotation_fit`); the row gets the median phi over those periods and half
its 16-84 % spread, the median k, the variation field's azimuth of the
local, `azimuth_neighbour` = a_base - phi (both in the sensor frames:
`azimuth_sensor` of the base), its difference to `azimuth_sensor`, `flag`
(difference over `FLAG_DEG`, 5 deg) and `hold` (over `HOLD_DEG`, 10 deg:
the site needs a dive before its key is trusted). The difference carries
the base's own error too, and the induction of a structure (k far from 1,
M far from a rotation) shows in it. M is rotation-invariant in its
determinant, so the timing fit of the same products
(`mt_workbench.intersite.timing_check`, tau > 0: the local lags the base)
goes into the row as `tau_ms` and `tau_err_ms`.

Outputs: `<workspace>/qc/h_azimuth/h_azimuth.csv` (one row per site, written
as the rows come), `h_azimuth.png` (the azimuth in the sensor frame, the
neighbour's and the tilt per site, sorted by phase and name) and, with
`--neighbours`, the M products. `--propose` prints the `rot_h:` key of each
site of the table. `--apply` writes those keys into survey.yaml in place
(`apply_rot_h`): a copy beside it first (`survey.yaml.before_rot_h_<stamp>`),
each site's `rot_h:` line replaced or added after the entry's last indented
line, every other line kept unchanged; the new text is parsed and
compared with the old (only `rot_h` keys of the named sites may differ, the
sites and their order unchanged, every top-level key equal), its comment
count must equal the old one, and `Survey.site` must accept every changed
site, or the file is left as it was (exit 2).
`--apply` takes only the sites named on the line (or every site of the
table without `--exclude`d ones) and refuses a site whose row is `moved` or
`hold` unless `--force-holds` is given.

Exit status: 0 done, 1 a site failed (listed), 2 a usage error or a
refused write.

Usage:
    python scripts/h_azimuth.py <survey.yaml> [SITE ...] [--neighbours] [--workers N]
        [--propose] [--apply [--exclude S1,S2] [--force-holds]]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import re
import shutil
import subprocess
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from mt_workbench.ingest import archive_h_tilt, archive_rot_h, archive_rot_h_parts, default_archive_path  # noqa: E402
from mt_workbench.instruments import edl_sensor  # noqa: E402
from mt_workbench.survey import OBSERVATORY, Survey, distance_km  # noqa: E402

FLAG_DEG = 5.0   # neighbour difference that flags a site
HOLD_DEG = 10.0  # neighbour difference that holds a site for a dive
MOVED_DEG = 2.0  # hourly azimuth 5-95 % spread that says the sensor turned during the record
RATIO_BAND = (0.95, 1.05)  # F / IGRF and |hz| / |Z| outside it flag the site
NEIGHBOUR_BAND = (10.0, 3000.0)  # s, the periods of the rotation fit
MIN_OVERLAP = 0.5  # share of the local's record the base (and the reference) must overlap
KEY_LINE = re.compile(r"^(?P<indent>[ ]+)rot_h:")
COMMENT = re.compile(r"(^|\s)#")
COLUMNS = ("site", "phase", "wave", "instrument", "archive", "samples", "t_mid", "hx_med", "hy_med", "hz_med",
           "H", "F", "inclination", "igrf_H", "igrf_Z_down", "igrf_F", "igrf_inc", "igrf_dec", "H_ratio",
           "hz_ratio", "F_ratio", "tilt_deg", "azimuth", "azimuth_mean", "az_hourly_p05", "az_hourly_p95",
           "rot_h_recorded", "azimuth_sensor", "rot_h_declared", "rot_h_proposed", "field_flag",
           "base", "reference", "base_azimuth_sensor", "overlap_h", "distance_km", "phi_median", "phi_spread",
           "k_median", "n_periods", "azimuth_neighbour", "difference", "flag", "hold", "tau_ms", "tau_err_ms",
           "m_product", "rot_h_parts_recorded", "h_tilt_recorded")


def wrap(deg: float) -> float:
    """Return an angle in degrees wrapped to (-180, 180]."""
    out = (float(deg) + 180.0) % 360.0 - 180.0
    return 180.0 if out == -180.0 else out


def decimal_year(when: pd.Timestamp) -> float:
    """Return a UTC instant as a decimal year."""
    t = pd.Timestamp(when)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    start = pd.Timestamp(year=t.year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=t.year + 1, month=1, day=1, tz="UTC")
    return t.year + (t - start) / (end - start)


def igrf_field(latitude: float, longitude: float, elevation_m: float, when: pd.Timestamp) -> dict:
    """Return the IGRF main field at a place and instant (ppigrf, as scripts/declination.py calls it).

    Args:
        latitude (float): Geodetic latitude in degrees.
        longitude (float): Longitude in degrees, east positive.
        elevation_m (float): Height in m.
        when (pd.Timestamp): The instant, UTC.

    Returns:
        dict: ``H``, ``Z_down``, ``F`` in nT, ``inc`` (atan2(Z_down, H)) and
        ``dec`` (atan2(Be, Bn)) in degrees.
    """
    import ppigrf

    t = pd.Timestamp(when)
    t = t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t
    be, bn, bu = (float(np.ravel(x)[0]) for x in ppigrf.igrf(longitude, latitude, elevation_m / 1000.0,
                                                               t.to_pydatetime()))
    h = math.hypot(be, bn)
    return dict(H=h, Z_down=-bu, F=math.sqrt(h * h + bu * bu), inc=math.degrees(math.atan2(-bu, h)),
                dec=math.degrees(math.atan2(be, bn)))


def site_phase(config) -> tuple[str, str]:
    """Return a site's phase ("1".."4" from its notes, "" when they do not say) and its wave.

    The wave splits phase 1 into its west (starts before 2016-02-10) and
    north deployments; the other phases are one wave each.
    """
    m = re.match(r"\s*phase\s+(\d+)", str(config.notes or ""))
    phase = m.group(1) if m else ""
    if phase == "1" and config.start:
        wave = "1 west" if pd.Timestamp(config.start) < pd.Timestamp("2016-02-10T00:00Z") else "1 north"
    else:
        wave = phase
    return phase, wave


def fluxgate_sites(survey: Survey, names: list[str] | None) -> tuple[list[str], dict[str, str]]:
    """Return the recorded fluxgate sites among `names` (every site when None) and the reasons for the others.

    Args:
        survey (Survey): The survey.
        names (list of str or None): Sites asked for.

    Returns:
        tuple: (sites, {site: reason left out}).
    """
    out, skipped = [], {}
    for site in names or survey.site_names():
        try:
            config = survey.site(site)
            instrument = survey.instrument_of(site)
        except ValueError as exc:
            skipped[site] = f"survey.yaml refuses it: {exc}"
            continue
        channels = [c.lower() for c in config.channels] if config.channels else None
        if survey.parent_of(site) or survey.bursts_parent(site):
            skipped[site] = "derived or burst site: its archive is made from its parent's"
        elif instrument == OBSERVATORY:
            skipped[site] = "observatory"
        elif channels is not None and not {"hx", "hy"} <= set(channels):
            skipped[site] = f"channels {channels}: no hx and hy of its own"
        elif not ((instrument == "edl" and edl_sensor(config) == "bartington") or instrument in ("lemi424", "orangebox")):
            skipped[site] = f"{instrument} without a fluxgate"
        elif not default_archive_path(survey, site).exists():
            skipped[site] = f"no archive {default_archive_path(survey, site)}"
        else:
            out.append(site)
    return out, skipped


def field_row(survey_yaml: str, site: str) -> dict:
    """Return the field columns of one site's row (the module docstring lists them).

    Run in a worker process, so it takes the survey.yaml path.

    Args:
        survey_yaml (str): The survey.yaml.
        site (str): A recorded fluxgate site with an archive.

    Returns:
        dict: The row's field columns.
    """
    from mt_workbench.timefreq import load_station

    survey = Survey.from_yaml(survey_yaml)
    config = survey.site(site)
    archive = default_archive_path(survey, site)
    comps = [c for c in ("hx", "hy", "hz") if not config.channels or c in [x.lower() for x in config.channels]]
    rec = load_station(archive, survey.name, site, comps=tuple(comps))
    values = {c: rec.value(c) for c in comps if c in rec.arrays}
    good = np.all([np.isfinite(v) for v in values.values()], axis=0)
    med = {c: float(np.median(v[good])) for c, v in values.items()}
    mean = {c: float(np.mean(v[good])) for c, v in values.items()}
    n_h = int(round(3600 * rec.sample_rate))
    nb = rec.n // n_h
    hourly = {}
    for c in ("hx", "hy"):
        blocks = values[c][: nb * n_h].reshape(nb, n_h)
        with warnings.catch_warnings():  # an hour of the grid inside a gap is all NaN: its median is NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            hourly[c] = np.nanmedian(blocks, axis=1) if nb else np.array([med[c]])
    az_hourly = np.degrees(np.arctan2(hourly["hy"], hourly["hx"]))
    az = math.degrees(math.atan2(med["hy"], med["hx"]))
    # the hourly azimuths unwrapped about the record's own, so a sensor near 180 deg reads a spread, not 360
    az_hourly = az + (az_hourly - az + 180.0) % 360.0 - 180.0
    az_hourly = az_hourly[np.isfinite(az_hourly)]
    t_mid = rec.t0 + pd.Timedelta(seconds=rec.duration_s / 2)
    ref = igrf_field(config.latitude, config.longitude, config.elevation or 0.0, t_mid)
    h = math.hypot(med["hx"], med["hy"])
    hz = med.get("hz", float("nan"))
    f = math.sqrt(h * h + hz * hz)
    tilt = (math.degrees(math.acos(min(1.0, abs(hz) / f))) - math.degrees(math.acos(abs(ref["Z_down"]) / ref["F"]))
            if math.isfinite(hz) else float("nan"))
    recorded = archive_rot_h(archive, site)
    # a site declared rot_h_parts (one turn per part): the parts are reported; azimuth_sensor then holds the
    # azimuth in the turned frame (no single angle describes the record)
    parts = archive_rot_h_parts(archive, site)
    phase, wave = site_phase(config)
    row = dict(site=site, phase=phase, wave=wave, instrument=survey.instrument_of(site), archive=str(archive),
               samples=int(good.sum()), t_mid=t_mid.isoformat(), hx_med=med["hx"], hy_med=med["hy"], hz_med=hz,
               H=h, F=f, inclination=math.degrees(math.atan2(hz, h)) if math.isfinite(hz) else float("nan"),
               igrf_H=ref["H"], igrf_Z_down=ref["Z_down"], igrf_F=ref["F"], igrf_inc=ref["inc"],
               igrf_dec=ref["dec"], H_ratio=h / ref["H"], hz_ratio=abs(hz) / abs(ref["Z_down"]),
               F_ratio=f / ref["F"], tilt_deg=tilt, azimuth=az,
               azimuth_mean=math.degrees(math.atan2(mean["hy"], mean["hx"])),
               az_hourly_p05=float(np.percentile(az_hourly, 5)) if az_hourly.size else float("nan"),
               az_hourly_p95=float(np.percentile(az_hourly, 95)) if az_hourly.size else float("nan"),
               rot_h_recorded=recorded or 0.0, azimuth_sensor=wrap(az + (recorded or 0.0)),
               rot_h_declared=config.rot_h,
               rot_h_parts_recorded=" ".join(f"{a!r}@{s}/{e}" for s, e, a in parts) if parts else "",
               h_tilt_recorded=" ".join(repr(v) for v in (archive_h_tilt(archive, site) or [])))
    row["rot_h_proposed"] = round(row["azimuth_sensor"], 2)
    flags = []
    if not RATIO_BAND[0] <= row["F_ratio"] <= RATIO_BAND[1]:
        flags.append(f"F {row['F_ratio']:.3f}")
    if math.isfinite(hz) and not RATIO_BAND[0] <= row["hz_ratio"] <= RATIO_BAND[1]:
        flags.append(f"hz {row['hz_ratio']:.3f}")
    if math.isfinite(hz) and hz >= 0:
        flags.append("hz sign")
    if row["az_hourly_p95"] - row["az_hourly_p05"] > MOVED_DEG:
        flags.append(f"moved {row['az_hourly_p95'] - row['az_hourly_p05']:.1f} deg")
    row["field_flag"] = "; ".join(flags)
    return row


def rotation_fit(frame: pd.DataFrame) -> pd.DataFrame:
    """Fit M = k R(phi) per period by weighted least squares.

    With R(phi) = [[cos, sin], [-sin, cos]] and k real, k R(phi) is
    [[a, b], [-b, a]] for real a = k cos(phi), b = k sin(phi), whose
    weighted least-squares values are a = (w_xx Re M_xx + w_yy Re M_yy) /
    (w_xx + w_yy) and b = (w_xy Re M_xy - w_yx Re M_yx) / (w_xy + w_yx),
    w = 1 / error^2; then phi = atan2(b, a) and k = hypot(a, b) > 0.

    Args:
        frame (pd.DataFrame): process_intersite.py's csv rows (columns
            ``period``, ``M_<ij>_re``, ``M_<ij>_err``).

    Returns:
        pd.DataFrame: ``period``, ``phi``, ``k``.
    """
    def weight(col):
        e = frame[f"M_{col}_err"].to_numpy(float)
        return np.where(np.isfinite(e) & (e > 0), 1.0 / np.maximum(e, 1e-300) ** 2, 0.0)

    wxx, wyy, wxy, wyx = (weight(c) for c in ("xx", "yy", "xy", "yx"))
    with np.errstate(all="ignore"):
        a = (wxx * frame.M_xx_re + wyy * frame.M_yy_re) / (wxx + wyy)
        b = (wxy * frame.M_xy_re - wyx * frame.M_yx_re) / (wxy + wyx)
    return pd.DataFrame({"period": frame.period.to_numpy(float), "phi": np.degrees(np.arctan2(b, a)),
                         "k": np.hypot(a, b)})


def neighbour_plan(survey: Survey, sites: list[str], candidates: list[str]) -> dict[str, tuple[str, str, float, float]]:
    """Choose each site's base and reference for the variation-field check.

    The base is the nearest candidate whose record overlaps `MIN_OVERLAP`
    of the local's (survey.yaml `start`/`end`); the reference the nearest
    other candidate to the local overlapping `MIN_OVERLAP` of the local's
    record and some of the base's.

    Args:
        survey (Survey): The survey.
        sites (list of str): The locals.
        candidates (list of str): Sites that may be a base or a reference.

    Returns:
        dict: {local: (base, reference, overlap hours of local and base, km)};
        a site with no base or no reference is left out.
    """
    spans = {}
    for s in set(sites) | set(candidates):
        c = survey.site(s)
        if c.start and c.end and c.latitude is not None and c.longitude is not None:
            spans[s] = (pd.Timestamp(c.start), pd.Timestamp(c.end), c.latitude, c.longitude)

    def overlap(a, b):
        return max(0.0, (min(spans[a][1], spans[b][1]) - max(spans[a][0], spans[b][0])).total_seconds() / 3600.0)

    out = {}
    for local in sites:
        if local not in spans:
            continue
        rec = (spans[local][1] - spans[local][0]).total_seconds() / 3600.0
        near = sorted((distance_km(spans[local][2], spans[local][3], spans[s][2], spans[s][3]), s)
                      for s in candidates if s != local and s in spans and overlap(local, s) >= MIN_OVERLAP * rec)
        if len(near) < 2:
            continue
        km, base = near[0]
        ref = next((s for _d, s in near[1:] if overlap(base, s) > 0), None)
        if ref is not None:
            out[local] = (base, ref, overlap(local, base), km)
    return out


def run_intersite(survey_yaml: str, local: str, base: str, ref: str, out_dir: Path, log_dir: Path) -> Path:
    """Run scripts/process_intersite.py --kind magnetic for one site and return its csv.

    Args:
        survey_yaml (str): The survey.yaml.
        local (str): The local.
        base (str): The base.
        ref (str): The reference (--remote).
        out_dir (Path): The products' folder.
        log_dir (Path): The folder of the run's log.

    Returns:
        Path: ``<out_dir>/<local>_hm-<base>_rr-<ref>.csv``.

    Raises:
        RuntimeError: If the script exits with an error.
    """
    csv_path = out_dir / f"{local}_hm-{base}_rr-{ref}.csv"
    cmd = [sys.executable, str(REPO / "scripts" / "process_intersite.py"), survey_yaml, local, base,
           "--kind", "magnetic", "--remote", ref, "--out-dir", str(out_dir)]
    log = log_dir / f"intersite_{local}_hm-{base}_rr-{ref}.log"
    with open(log, "w", encoding="utf-8") as handle:
        done = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, cwd=str(REPO))
    if done.returncode != 0 or not csv_path.exists():
        raise RuntimeError(f"process_intersite.py {local} {base} --remote {ref} exited {done.returncode} (log {log})")
    return csv_path


def neighbour_columns(csv_path: Path, local_az: float, base_az: float) -> dict:
    """Return the neighbour columns of a row from an M product (the module docstring lists them).

    Args:
        csv_path (Path): The product's csv.
        local_az (float): The local's `azimuth_sensor`.
        base_az (float): The base's `azimuth_sensor`.

    Returns:
        dict: ``phi_median``, ``phi_spread``, ``k_median``, ``n_periods``,
        ``azimuth_neighbour``, ``difference``, ``flag``, ``hold``,
        ``tau_ms``, ``tau_err_ms``, ``m_product``.
    """
    import json

    frame = pd.read_csv(csv_path)
    fits = rotation_fit(frame)
    band = fits[(fits.period >= NEIGHBOUR_BAND[0]) & (fits.period <= NEIGHBOUR_BAND[1]) & np.isfinite(fits.phi)]
    predicted = wrap(base_az - local_az)
    # each period's phi on the branch nearest the mean-field prediction, so a sensor near 180 deg has no wrap
    phis = predicted + (band.phi.to_numpy() - predicted + 180.0) % 360.0 - 180.0
    phi = float(np.median(phis)) if phis.size else float("nan")
    spread = float((np.percentile(phis, 84) - np.percentile(phis, 16)) / 2) if phis.size else float("nan")
    neighbour = wrap(base_az - phi)
    difference = wrap(neighbour - local_az)
    side = json.loads(csv_path.with_suffix(".json").read_text(encoding="utf-8"))
    timing = side.get("timing_check") or {}
    return dict(phi_median=wrap(phi), phi_spread=spread, k_median=float(np.median(band.k)) if len(band) else float("nan"),
                n_periods=int(len(band)), azimuth_neighbour=neighbour, difference=difference,
                flag=bool(abs(difference) > FLAG_DEG), hold=bool(abs(difference) > HOLD_DEG),
                tau_ms=timing.get("tau_ms"), tau_err_ms=timing.get("tau_err_ms"), m_product=csv_path.name)


def write_table(rows: list[dict], path: Path) -> None:
    """Write the rows to a csv with `COLUMNS`, floats to 4 decimals."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=list(COLUMNS), extrasaction="ignore")
        out.writeheader()
        for r in rows:
            out.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})


def figure(rows: list[dict], path: Path, title: str) -> None:
    """Draw the azimuth in the sensor frame, the neighbour's and the tilt per site, sorted by wave and name."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted(rows, key=lambda r: (r["wave"], r["site"]))
    x = np.arange(len(rows))
    fig, axes = plt.subplots(3, 1, figsize=(max(10, 0.32 * len(rows) + 3), 10), sharex=True, layout="constrained")
    az = np.array([r["azimuth_sensor"] for r in rows])
    arch = np.array([r["azimuth"] for r in rows])
    nb = np.array([r.get("azimuth_neighbour", np.nan) if r.get("azimuth_neighbour") is not None else np.nan
                   for r in rows], float)
    spread = np.array([r.get("phi_spread", np.nan) if r.get("phi_spread") is not None else np.nan for r in rows],
                      float)
    ax = axes[0]
    ax.plot(x, az, "o", color="C0", label="mean-field azimuth, sensor frame (the proposed rot_h)")
    ax.errorbar(x, nb, yerr=spread, fmt="x", color="C3", label="variation field against the base (a_base - phi)")
    ax.plot(x, arch, ".", color="k", ms=4, label="azimuth in the archive as built")
    for i, r in enumerate(rows):
        if r.get("hold"):
            ax.annotate("hold", (x[i], az[i]), textcoords="offset points", xytext=(0, 8), ha="center",
                        color="C3", fontsize=7)
        elif r.get("flag"):
            ax.annotate("flag", (x[i], az[i]), textcoords="offset points", xytext=(0, 8), ha="center",
                        color="C1", fontsize=7)
    ax.set_ylim(-185, 185)
    ax.set_yticks(range(-180, 181, 45))
    ax.set_ylabel("azimuth of magnetic north\nfrom sensor x toward y (deg)")
    ax.legend(fontsize=8, loc="lower left")
    ax = axes[1]
    diff = np.array([r.get("difference", np.nan) if r.get("difference") is not None else np.nan for r in rows],
                    float)
    ax.bar(x, diff, color=["C3" if abs(d) > HOLD_DEG else "C1" if abs(d) > FLAG_DEG else "C2" for d in
                           np.nan_to_num(diff)])
    for lim, style in ((FLAG_DEG, ":"), (HOLD_DEG, "--")):
        ax.axhline(lim, color="k", ls=style, lw=0.8)
        ax.axhline(-lim, color="k", ls=style, lw=0.8)
    ax.set_ylabel("neighbour - mean field (deg)\nflag 5, hold 10")
    ax = axes[2]
    ax.bar(x, [r["tilt_deg"] for r in rows], color="C4", label="tilt estimate (field-to-z angle - IGRF's)")
    ax.plot(x, [100 * (r["F_ratio"] - 1) for r in rows], "s", color="k", ms=4, label="100 (F / IGRF - 1)")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("deg (bars), % (squares)")
    ax.legend(fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['site']} ({r['wave']})" for r in rows], rotation=90, fontsize=7)
    for a in axes:
        a.grid(alpha=0.3)
    fig.suptitle(title)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def comment_count(text: str) -> int:
    """Return the number of lines holding a YAML comment ("#" at the start or after white space)."""
    return sum(1 for line in text.splitlines() if COMMENT.search(line))


def set_rot_h(text: str, values: dict[str, float]) -> str:
    """Write each site's `rot_h:` line into survey.yaml text, by lines.

    Args:
        text (str): The survey.yaml text, line endings as read.
        values (dict): {site: degrees}.

    Returns:
        str: The new text: an existing `rot_h:` line of the entry replaced
        in place, else one added after the entry's last indented line;
        every other line unchanged.

    Raises:
        ValueError: If the sites block or a site's block entry is not found.
    """
    from declination import _indent, entry_spans, sites_block

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
    for site, value in values.items():
        head, stop = spans[site]
        body = range(head + 1, stop)
        content = [i for i in body if lines[i].strip() and not lines[i].lstrip().startswith("#")]
        pad = " " * (_indent(lines[content[0]]) if content else 4)
        line = f"{pad}rot_h: {float(value):.2f}"
        found = [i for i in body if (m := KEY_LINE.match(lines[i])) and m.group("indent") == pad]
        if found:
            i = found[0]
            lines[i] = line + (lines[i][len(lines[i].rstrip("\r\n")):] or newline)
            continue
        last = max([i for i in body if lines[i].strip() and _indent(lines[i]) > 2], default=head)
        inserts.setdefault(last, []).append(line + newline)
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        out.extend(inserts.get(i, []))
    return "".join(out)


def check_rot_h_edit(old: str, new: str, values: dict[str, float]) -> list[str]:
    """Compare two survey.yaml texts: only the `rot_h` keys of the given sites may differ.

    Returns:
        list[str]: One line per difference found, the comment counts among
        them; empty when the new text is the old one plus the given keys.
    """
    a, b = yaml.safe_load(old) or {}, yaml.safe_load(new) or {}
    found = [f"top-level key {k} changed" for k in set(a) | set(b) if k != "sites" and a.get(k) != b.get(k)]
    sa, sb = a.get("sites") or {}, b.get("sites") or {}
    if list(sa) != list(sb):
        found.append("the sites or their order changed")
    for site in sb:
        ea, eb = dict(sa.get(site) or {}), dict(sb.get(site) or {})
        if site in values:
            got = eb.pop("rot_h", None)
            ea.pop("rot_h", None)
            if got is None or abs(float(got) - round(float(values[site]), 2)) > 1e-9:
                found.append(f"{site} rot_h: {got!r}, wanted {values[site]:.2f}")
        if ea != eb or [k for k in ea] != [k for k in eb]:
            found.append(f"{site}: other keys changed")
    if comment_count(old) != comment_count(new):
        found.append(f"comment lines {comment_count(old)} -> {comment_count(new)}")
    return found


def apply_rot_h(path: Path, values: dict[str, float]) -> Path:
    """Write the `rot_h` keys into survey.yaml in place, after a copy and the checks.

    Args:
        path (Path): survey.yaml.
        values (dict): {site: degrees}.

    Returns:
        Path: The copy of the file as it was.

    Raises:
        ValueError: If the edit changes anything but the named sites'
            `rot_h`, the comment count changes, or `Survey.site` refuses a
            changed site; the file is left as it was then.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        old = handle.read()
    new = set_rot_h(old, values)
    problems = check_rot_h_edit(old, new, values)
    if problems:
        raise ValueError("the rot_h edit would change more than the rot_h keys: " + "; ".join(problems))
    survey = Survey(yaml.safe_load(new), path.parent)
    for site in values:
        survey.site(site)
    copy = path.with_name(f"{path.name}.before_rot_h_{dt.datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, copy)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(new)
    return copy


def main(argv=None) -> int:
    """Run the field table, the neighbour check, the proposal and the in-place write.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: The exit status (see the module docstring).
    """
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("survey_yaml")
    p.add_argument("sites", nargs="*", help="sites (default: every recorded fluxgate site)")
    p.add_argument("--neighbours", action="store_true", help="the variation-field check against a neighbour")
    p.add_argument("--propose", action="store_true", help="print the rot_h keys")
    p.add_argument("--apply", action="store_true", help="write the rot_h keys into survey.yaml in place")
    p.add_argument("--exclude", default="", help="with --apply: sites left out, comma separated")
    p.add_argument("--force-holds", action="store_true", help="with --apply: write the keys of moved or held sites")
    p.add_argument("--workers", type=int, default=3, help="worker processes (3)")
    p.add_argument("--out", default=None, help="output folder (<workspace>/qc/h_azimuth)")
    args = p.parse_args(argv)
    path = Path(args.survey_yaml)
    survey = Survey.from_yaml(path)
    unknown = [s for s in args.sites if s not in survey.site_names()]
    if unknown:
        print(f"ERROR not in survey.yaml: {', '.join(unknown)}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else survey.workspace / "qc" / "h_azimuth"
    out.mkdir(parents=True, exist_ok=True)
    sites, skipped = fluxgate_sites(survey, args.sites or None)
    for site, why in skipped.items():
        print(f"skipped {site}: {why}")
    print(f"criterion: a site whose F / IGRF or |hz| / |Z| is outside {RATIO_BAND[0]}-{RATIO_BAND[1]}, whose hz is "
          f"not negative or whose hourly azimuth spreads over {MOVED_DEG} deg is flagged in field_flag"
          + (f"; with --neighbours a site whose variation-field azimuth differs from its mean-field azimuth by over "
             f"{FLAG_DEG} deg is flagged and over {HOLD_DEG} deg held" if args.neighbours else ""), flush=True)
    rows, failed = {}, {}
    table = out / "h_azimuth.csv"
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {site: pool.submit(field_row, str(path), site) for site in sites}
        for site, fut in futures.items():
            try:
                rows[site] = fut.result()
            except Exception as exc:  # noqa: BLE001  (one site's failure is listed, the table goes on)
                failed[site] = f"{type(exc).__name__}: {exc}"
                print(f"FAILED {site}: {failed[site]}", flush=True)
                continue
            r = rows[site]
            print(f"{site}: azimuth {r['azimuth']:+8.2f} (sensor {r['azimuth_sensor']:+8.2f}), tilt "
                  f"{r['tilt_deg']:+5.2f}, H/F/hz ratios {r['H_ratio']:.3f} {r['F_ratio']:.3f} {r['hz_ratio']:.3f}"
                  f"{'  ' + r['field_flag'] if r['field_flag'] else ''}", flush=True)
            write_table([rows[s] for s in sites if s in rows], table)
    if args.neighbours:
        plan = neighbour_plan(survey, [s for s in sites if s in rows], [s for s in sites if s in rows])
        for site in sites:
            if site in rows and site not in plan:
                rows[site]["base"] = "none: no site overlaps half its record"
        m_dir = survey.workspace / "tf" / "h_azimuth"
        m_dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {local: pool.submit(run_intersite, str(path), local, base, ref, m_dir, out)
                       for local, (base, ref, _ov, _km) in plan.items()}
            for local, fut in futures.items():
                base, ref, ov, km = plan[local]
                rows[local].update(base=base, reference=ref, overlap_h=ov, distance_km=km,
                                   base_azimuth_sensor=rows[base]["azimuth_sensor"])
                try:
                    rows[local].update(neighbour_columns(fut.result(), rows[local]["azimuth_sensor"],
                                                         rows[base]["azimuth_sensor"]))
                except Exception as exc:  # noqa: BLE001
                    failed[local] = f"neighbour check: {type(exc).__name__}: {exc}"
                    print(f"FAILED {local}: {failed[local]}", flush=True)
                    continue
                r = rows[local]
                tau = "no tau" if r["tau_ms"] is None else f"tau {r['tau_ms']:+.1f} ms"  # None: no fit or not determined
                print(f"{local} on {base} (rr {ref}, {km:.0f} km): phi {r['phi_median']:+.1f} +/- {r['phi_spread']:.1f}"
                      f", neighbour azimuth {r['azimuth_neighbour']:+.1f}, difference {r['difference']:+.1f}"
                      f"{' HOLD' if r['hold'] else ' flag' if r['flag'] else ''}; {tau}", flush=True)
                write_table([rows[s] for s in sites if s in rows], table)
    ordered = [rows[s] for s in sites if s in rows]
    write_table(ordered, table)
    if ordered:
        figure(ordered, out / "h_azimuth.png",
               f"{survey.name}: fluxgate azimuth (sensor frame), variation-field check and tilt, "
               f"{dt.datetime.now():%Y-%m-%d %H:%M}")
    print(f"table: {table}")
    print(f"figure: {out / 'h_azimuth.png'}")
    if args.propose or args.apply:
        for r in ordered:
            note = "; ".join(x for x in (r["field_flag"], "HOLD" if r.get("hold") else "flag" if r.get("flag") else "")
                             if x)
            print(f"  {r['site']}:\n    rot_h: {r['rot_h_proposed']:.2f}" + (f"   # {note}" if note else ""))
    if args.apply:
        excluded = {s.strip() for s in args.exclude.split(",") if s.strip()}
        values, refused = {}, []
        for r in ordered:
            if r["site"] in excluded:
                continue
            if not args.force_holds and (r.get("hold") or "moved" in r["field_flag"]):
                refused.append(r["site"])
                continue
            values[r["site"]] = r["rot_h_proposed"]
        if refused:
            print(f"not written (hold or moved; --force-holds writes them): {', '.join(refused)}")
        try:
            copy = apply_rot_h(path, values)
        except ValueError as exc:
            print(f"ERROR {exc}", file=sys.stderr)
            return 2
        print(f"wrote rot_h for {len(values)} site(s) into {path}; the file as it was: {copy}")
    for site, why in failed.items():
        print(f"failed {site}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
