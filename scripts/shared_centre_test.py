# -*- coding: utf-8 -*-
"""
Does a noisy shared centre electrode explain a site's two electric lines, and which diagonal is clean?

An Earth Data PR6-24 (EDL) site measures its two lines off one shared centre
electrode C: the logger's ex input holds V(N) - V(C) and its ey input
V(E) - V(C), the outer electrode on the + terminal of each (Tasmania
AusLAMP 2016, acquisition report section 4). A noisy centre puts one
voltage on both lines, and the dipole between the two outer electrodes,
ex - ey, is free of it. This script runs the shared-centre test on the
archives of this package.

The observable is not the coherence of the two lines or of the diagonals,
which the natural field's polarization sets on a day the lines are coherent
with H, but the pair of residuals left after the part of each line that
(hx, hy) explain is removed per frequency bin: a shared centre leaves one
voltage on both, so the residuals are coherent at gain 1. Per site:

1. The archive of record (`mt_workbench.ingest.default_archive_path`) is
   read with `mt_workbench.timefreq.load_station`, every run on one grid.
   The electrics are taken in the logger's own units, the archive's samples
   (microvolts at the logger, after the x10 terminal box), not in mV/km: a
   centre voltage is the same number of microvolts on both inputs whatever
   the arm lengths, so its gain is 1 in these units, and the sign found is
   the sign `scripts/diagonal_site.py` subtracts with. hx and hy are in nT.
   At a site whose pair the ingest turned (rot_e: the station's
   "rot_e: ex <a_x> deg, ey <a_y> deg as laid" line, `archive_rot_e`) the
   archive's ex and ey are E_N and E_E, and a centre voltage sits on the
   lines as recorded, not on the turned pair, so the turn is
   undone first in the logger's units (`diagonal_site.unturn_matrix` with k
   the ratio of ey's to ex's chain gain): the test then reads the recorded
   lines, as diagonal_site.py subtracts them. The site row's `rot_e` column
   names the as-laid azimuths where this was done.
2. Each UTC day holding at least `MIN_DAY_HOURS` of the record is a
   candidate. Each channel's day is despiked at the archive rate (a sample
   step beyond `SPIKE_K` times the robust scale of the steps blanks the
   samples around it, `despike`), refused when under `MIN_FINITE` of
   it is finite (gaps included), interpolated across the blanks, decimated
   to 1 Hz (the zero-phase FIR stages of scripts/decimate_site.py) and
   high-passed (2nd-order Butterworth, forward and back, at 3 times the
   band's longest period). Cross-spectra of ex, ey, hx and hy follow by
   Welch's method (`NPERSEG` samples at 1 Hz, half overlap, Hann), the
   convention of scipy.signal.csd, S_pq = <conj(P) Q>. A day whose (hx, hy)
   cross-spectral matrix is singular in a bin (a dead or flat magnetometer)
   is left out as unusable.
3. Per frequency bin inside the band (default 10-1000 s): the residual
   cross-spectra S_r1r2 = S_12 - S_1h Shh^-1 S_h2 of the two lines after the
   two-input least-squares transfer function from (hx, hy) is removed; the
   residual coherence |S_rxry|^2 / (S_rxrx S_ryry) and the complex gain
   g = S_ry,rx / S_rx,rx (under this convention the
   regression coefficient of ry on rx is conj(g), with the same modulus and
   real part); the multiple coherence with (hx, hy) of the two diagonals,
   ex - ey ("diff") and ex + ey ("sum"); and the source coherence of the
   two lines, |S_ex,ey|^2 / (S_ex,ex S_ey,ey).
4. A day's value of each is the median over the octave sub-bands of the
   band of the median over each sub-band's bins (most bins
   of a decade-wide band sit at its short end, so a median over bins
   reports the short periods alone). The sign of the gain of a day is the
   sign of its median Re(g).
5. The site uses the --days days of highest source coherence inside its
   record (where a common voltage is strong, the lines are
   coherent through it) and takes the medians over them; its sign s_obs is
   the sign of the sum of the days' signs.

Verdict per site (columns `model_holds`, `control`, `verdict`):

- **holds**: the shared-centre model describes the site, the residual
  coherence >= `MODEL_COH` (0.9) and |g| within `MODEL_GAIN` (0.85-1.18):
  one voltage, gain 1. The clean diagonal is ex - s ey with s = sign Re(g)
  (in archive samples): s = +1 cancels a centre on the minus terminal of
  both inputs.
- **control**: no common mode to find, the source coherence of the two lines
  under `CONTROL_COH` (0.35) on every chosen day.
- **fails**: neither: the lines are coherent without one shared voltage at
  gain 1 (AusLAMP Victoria sites with gain 0.3-0.4: another fault, which the
  diagonal does not cure).

A site that holds and is a control at once is reported as "holds" and
fails criterion B. The H test: the clean diagonal by H (`clean_by_H`) is
the one of ex - ey and ex + ey with the higher multiple coherence with
(hx, hy); `remedy_applicable` is True where the model holds and the clean
diagonal by H is the one the sign says (`clean_obs`).

The sign convention: the archive's ex and ey samples are the logger's own
words, whatever the azimuths (mt-io's EDL dipole filter carries the sign
of a reversed line, gain -L for a line along its nominal azimuth and +L
for one at 180 deg from it, and the samples are not negated), and the
junction box puts the centre on the minus terminal of both inputs, so the
prediction is s = +1 at every site (`S_PRED`); in the declared N/E frame
that is the parity rule (s = +1 for an even number of reversed arms, -1
for an odd number). A site that holds with s = -1 has one line wired with
its centre on the plus terminal.

The VERDICT lines, as the script prints them: A, the sign prediction
fails at a site where the model holds and s_obs differs from s_pred; B, the
test fails as a test if a control site shows residual coherence >= 0.9 (a
shared centre found where there is no common mode), and a run with no
control site cannot judge B; C, the remedy applies only where the model
holds and the clean diagonal's H coherence exceeds the other's.

Outputs, under --out (default `<workspace>/qc/shared_centre/`):
`centre_test.csv` (one row per site; a run on some sites replaces their
rows and keeps the others), `centre_test_days.csv` (every candidate day of
every site run: its values and whether it was chosen), `centre_test_bands.csv`
(the chosen days' values per octave sub-band), one figure per site
`<site>_centre_test.png` (the daily timeline of source coherence, residual
coherence and |g|; the chosen days' residual coherence, |g| and H
coherence of the two diagonals per sub-band) and the survey summary
`centre_test_summary.png`. Rows are written as each site finishes.

Exit status: 0 done, 1 a site failed (listed), 2 a usage error.

Usage:
    python scripts/shared_centre_test.py <survey.yaml> [SITE ...] [--days 3] [--band 10 1000]
        [--out DIR] [--workers N]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import traceback
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import signal  # noqa: E402

from mt_workbench.ingest import default_archive_path  # noqa: E402
from mt_workbench.survey import OBSERVATORY, Survey  # noqa: E402

DAY_S = 86400.0
MIN_DAY_HOURS = 6.0   # a UTC day holding less of the record is not a candidate
MIN_FINITE = 0.8      # share of a day's samples that must be finite after despiking
SPIKE_K = 30.0        # step threshold in robust scales of the steps (`despike`)
FS_TEST = 1.0         # Hz, the rate the spectra are taken at
NPERSEG = 4096        # Welch segment at FS_TEST
HP_FACTOR = 3.0       # the high-pass corner sits at this many times the band's longest period
MODEL_COH = 0.9       # residual coherence at or above which one voltage explains both lines
MODEL_GAIN = (0.85, 1.18)  # |g| inside which that voltage has gain 1
CONTROL_COH = 0.35    # source Ex-Ey coherence under which on every chosen day a site is a control
S_PRED = 1            # the predicted sign in archive samples: centre on the minus terminal of both inputs
LINES = ("ex", "ey")
FIELD = ("hx", "hy")
SITE_COLUMNS = ("site", "phase", "azimuth_ex", "azimuth_ey", "dipole_length_ex", "dipole_length_ey", "h_from",
                "days_usable", "days_used", "days", "src_coh", "src_max", "resid_coh", "resid_gain", "arg_g",
                "re_g", "s_obs", "s_pred", "mcoh_diff", "mcoh_sum", "model_holds", "control", "clean_obs",
                "clean_by_H", "remedy_applicable", "verdict", "days_model", "band", "archive", "rot_e")
DAY_COLUMNS = ("site", "day", "t_start", "hours", "finite", "chosen", "src", "coh_r", "gain", "re_g", "im_g",
               "arg_g", "s", "mcoh_diff", "mcoh_sum", "model")
BAND_COLUMNS = ("site", "day", "lo_s", "hi_s", "n_bins", "src", "coh_r", "gain", "re_g", "im_g", "mcoh_diff",
                "mcoh_sum")


# ---------------------------------------------------------------- the day's series


def despike(x: np.ndarray, k: float = SPIKE_K) -> tuple[np.ndarray, int]:
    """Blank the samples around every sample step beyond k robust scales of the steps.

    The scale is 1.4826 times the median
    absolute deviation of the steps; samples i-2 to i+3 around a step i are
    set to NaN.

    Args:
        x (np.ndarray): Samples, float64; NaN in gaps.
        k (float): Threshold in robust scales.

    Returns:
        tuple: (the series with the blanks as NaN, the number blanked).
    """
    x = np.array(x, dtype="float64", copy=True)
    d = np.diff(x)
    good = np.isfinite(d)
    if good.sum() < 10:
        return x, 0
    mad = float(np.median(np.abs(d[good] - np.median(d[good])))) * 1.4826
    hit = np.flatnonzero(good & (np.abs(np.where(good, d, 0.0)) > k * mad + 1e-9))
    if not hit.size:
        return x, 0
    bad = np.zeros(x.size, dtype=bool)
    for offset in range(-2, 4):
        idx = hit + offset
        bad[idx[(idx >= 0) & (idx < x.size)]] = True
    x[bad] = np.nan
    return x, int(bad.sum())


def fill_gaps(x: np.ndarray) -> np.ndarray:
    """Linearly interpolate across NaN samples (the ends held at the nearest finite value)."""
    fin = np.isfinite(x)
    if fin.all():
        return x
    idx = np.arange(x.size)
    return np.interp(idx, idx[fin], x[fin])


def to_test_rate(x: np.ndarray, fs: float) -> np.ndarray:
    """Decimate a gap-free series from `fs` to `FS_TEST` with the FIR stages of scripts/decimate_site.py."""
    if math.isclose(fs, FS_TEST):
        return x
    from decimate_site import decimate_array, stage_factors

    return decimate_array(x, stage_factors(fs, FS_TEST))


def high_pass(x: np.ndarray, corner_s: float) -> np.ndarray:
    """Remove the mean and high-pass a 1 Hz series at `corner_s` (2nd-order Butterworth, filtfilt)."""
    b, a = signal.butter(2, (1.0 / corner_s) / (0.5 * FS_TEST), "high")
    return signal.filtfilt(b, a, x - x.mean())


def prepare_day(series: dict[str, np.ndarray], fs: float, corner_s: float) -> tuple[dict | None, float]:
    """Despike, check, fill, decimate and high-pass one day of each channel.

    Args:
        series (dict): Channel to the day's samples at `fs`, NaN in gaps.
        fs (float): Archive sample rate in Hz.
        corner_s (float): High-pass corner period in s.

    Returns:
        tuple: (channel to the 1 Hz series, or None when a channel is under
        `MIN_FINITE` finite; the least finite share over the channels).
    """
    out, least = {}, 1.0
    for comp, x in series.items():
        y, _ = despike(x)
        fin = float(np.isfinite(y).mean())
        least = min(least, fin)
        if fin < MIN_FINITE:
            return None, least
        out[comp] = high_pass(to_test_rate(fill_gaps(y), fs), corner_s)
    return out, least


# ---------------------------------------------------------------- the spectral observables


def cross_spectra(ch: dict[str, np.ndarray], nperseg: int = NPERSEG) -> tuple[np.ndarray, dict]:
    """Return the frequencies and every auto- and cross-spectrum of the channels (S_pq = <conj(P) Q>).

    Args:
        ch (dict): Channel to its 1 Hz series, all of one length.
        nperseg (int): Welch segment in samples, half overlapped.

    Returns:
        tuple: (frequencies in Hz, {(p, q): spectrum}).
    """
    names = list(ch)
    n = min(nperseg, min(v.size for v in ch.values()))
    spectra, f = {}, None
    for i, p in enumerate(names):
        for q in names[i:]:
            f, s_pq = signal.csd(ch[p], ch[q], fs=FS_TEST, nperseg=n, noverlap=n // 2)
            spectra[(p, q)] = s_pq
            spectra[(q, p)] = np.conj(s_pq)
    return f, spectra


def octave_bands(lo_s: float, hi_s: float) -> list[tuple[float, float]]:
    """Return the octave sub-bands (lo, hi) in s covering [lo_s, hi_s]; the last may be shorter."""
    edges = [float(lo_s)]
    while edges[-1] * 2.0 < hi_s * (1 - 1e-9):
        edges.append(edges[-1] * 2.0)
    edges.append(float(hi_s))
    return list(zip(edges[:-1], edges[1:]))


def bin_stats(f: np.ndarray, spectra: dict, band: tuple[float, float]) -> dict[str, np.ndarray]:
    """Return the per-bin observables of the shared-centre test inside the band.

    Args:
        f (np.ndarray): Frequencies in Hz.
        spectra (dict): From `cross_spectra`, with ex, ey, hx and hy.
        band (tuple): (shortest, longest) period in s.

    Returns:
        dict: ``period`` (s), ``coh_r`` (residual coherence), ``g`` (complex
        gain S_ry,rx / S_rx,rx), ``mcoh_diff`` and ``mcoh_sum`` (multiple
        coherence with hx, hy of ex - ey and ex + ey), ``src`` (coherence of
        ex with ey), one value per bin.
    """
    S = spectra
    with np.errstate(divide="ignore"):
        period = np.where(f > 0, 1.0 / np.where(f > 0, f, 1.0), np.inf)
    sel = (period >= band[0]) & (period <= band[1])
    shh = np.stack([np.stack([S[("hx", "hx")], S[("hx", "hy")]], -1),
                    np.stack([S[("hy", "hx")], S[("hy", "hy")]], -1)], -2)[sel]
    inv = np.linalg.inv(shh)

    def seh(e):
        return np.stack([S[(e, "hx")], S[(e, "hy")]], -1)[sel]

    def she(e):
        return np.stack([S[("hx", e)], S[("hy", e)]], -1)[sel]

    def resid(e1, e2):  # S_r1,r2 = S_12 - S_1h Shh^-1 S_h2
        return S[(e1, e2)][sel] - np.einsum("ni,nij,nj->n", seh(e1), inv, she(e2))

    rxx, ryy, rxy = resid("ex", "ex").real, resid("ey", "ey").real, resid("ex", "ey")

    def mcoh(w):  # the multiple coherence with (hx, hy) of ex + w ey
        see = S[("ex", "ex")][sel].real + w * w * S[("ey", "ey")][sel].real + 2 * w * S[("ex", "ey")][sel].real
        seh_w = seh("ex") + w * seh("ey")
        she_w = she("ex") + w * she("ey")
        return np.einsum("ni,nij,nj->n", seh_w, inv, she_w).real / see

    src = np.abs(S[("ex", "ey")][sel]) ** 2 / (S[("ex", "ex")][sel].real * S[("ey", "ey")][sel].real)
    return dict(period=period[sel], coh_r=np.abs(rxy) ** 2 / (rxx * ryy), g=np.conj(rxy) / rxx,
                mcoh_diff=mcoh(-1.0), mcoh_sum=mcoh(1.0), src=src)


def band_medians(stats: dict[str, np.ndarray], band: tuple[float, float]) -> list[dict]:
    """Return the median of each observable over each octave sub-band's bins (sub-bands with no bin left out)."""
    rows = []
    for lo, hi in octave_bands(*band):
        k = (stats["period"] >= lo) & (stats["period"] < hi if hi < band[1] else stats["period"] <= hi)
        if not k.any():
            continue
        g = stats["g"][k]
        rows.append(dict(lo_s=lo, hi_s=hi, n_bins=int(k.sum()), src=float(np.median(stats["src"][k])),
                         coh_r=float(np.median(stats["coh_r"][k])), gain=float(np.median(np.abs(g))),
                         re_g=float(np.median(g.real)), im_g=float(np.median(g.imag)),
                         mcoh_diff=float(np.median(stats["mcoh_diff"][k])),
                         mcoh_sum=float(np.median(stats["mcoh_sum"][k]))))
    return rows


def day_values(bands: list[dict]) -> dict:
    """Return a day's values: the medians over its sub-bands, the gain's sign and argument."""
    out = {key: float(np.median([b[key] for b in bands]))
           for key in ("src", "coh_r", "gain", "re_g", "im_g", "mcoh_diff", "mcoh_sum")}
    out["arg_g"] = math.degrees(math.atan2(out["im_g"], out["re_g"]))
    out["s"] = 1 if out["re_g"] >= 0 else -1
    out["model"] = bool(out["coh_r"] >= MODEL_COH and MODEL_GAIN[0] <= out["gain"] <= MODEL_GAIN[1])
    return out


def series_stats(ch: dict[str, np.ndarray], band: tuple[float, float]) -> tuple[dict, list[dict]]:
    """Run the test on one prepared day: (the day's values, its sub-band rows)."""
    f, spectra = cross_spectra(ch)
    bands = band_medians(bin_stats(f, spectra, band), band)
    if not bands:
        raise ValueError(f"no frequency bin of the {NPERSEG}-sample segment lies in {band[0]:g}-{band[1]:g} s")
    return day_values(bands), bands


def site_verdict(chosen: list[dict]) -> dict:
    """Combine the chosen days into the site's values and verdict.

    Args:
        chosen (list of dict): The chosen days' values (`day_values` plus
            ``day``).

    Returns:
        dict: The site's medians, s_obs, model_holds, control, clean_obs,
        clean_by_H, remedy_applicable and verdict.
    """
    med = {k: float(np.median([d[k] for d in chosen])) for k in ("src", "coh_r", "gain", "re_g", "im_g",
                                                                "mcoh_diff", "mcoh_sum")}
    s_obs = int(np.sign(sum(d["s"] for d in chosen))) or 1
    model = bool(med["coh_r"] >= MODEL_COH and MODEL_GAIN[0] <= med["gain"] <= MODEL_GAIN[1])
    src_max = max(d["src"] for d in chosen)
    control = bool(src_max < CONTROL_COH)
    clean_obs = "diff" if s_obs > 0 else "sum"
    clean_h = "diff" if med["mcoh_diff"] > med["mcoh_sum"] else "sum"
    return dict(src_coh=med["src"], src_max=src_max, resid_coh=med["coh_r"], resid_gain=med["gain"],
                arg_g=math.degrees(math.atan2(med["im_g"], med["re_g"])), re_g=med["re_g"], s_obs=s_obs,
                s_pred=S_PRED, mcoh_diff=med["mcoh_diff"], mcoh_sum=med["mcoh_sum"], model_holds=model,
                control=control, clean_obs=clean_obs, clean_by_H=clean_h,
                remedy_applicable=bool(model and clean_h == clean_obs),
                verdict="holds" if model else ("control" if control else "fails"))


# ---------------------------------------------------------------- one site


def candidate_sites(survey: Survey, names: list[str] | None) -> tuple[list[str], dict[str, str]]:
    """Return the sites the test runs on and the reasons for the others.

    A site runs when it is a recorded site (not derived, burst or an
    observatory), keeps ex and ey, and has an archive.

    Args:
        survey (Survey): The survey.
        names (list of str or None): Sites asked for; every site when None.

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
        kept = [c.lower() for c in config.channels] if config.channels else None
        if survey.parent_of(site) or survey.bursts_parent(site):
            skipped[site] = "derived or burst site"
        elif instrument == OBSERVATORY:
            skipped[site] = "observatory"
        elif kept is not None and not set(LINES) <= set(kept):
            skipped[site] = f"channels {kept}: not both electric lines"
        elif not default_archive_path(survey, site).exists():
            skipped[site] = f"no archive {default_archive_path(survey, site)}"
        else:
            out.append(site)
    return out, skipped


def run_site(survey_yaml: str, site: str, n_days: int, band: tuple[float, float]) -> dict:
    """Run the test on one site's archive.

    Run in a worker process, so it takes the survey.yaml path.

    Args:
        survey_yaml (str): The survey.yaml.
        site (str): The site.
        n_days (int): Days of highest source coherence to use.
        band (tuple): (shortest, longest) period in s.

    Returns:
        dict: ``row`` (the site's row, `SITE_COLUMNS`), ``days`` (every
        candidate day's row), ``bands`` (the chosen days' sub-band rows).

    Raises:
        ValueError: If the archive lacks a channel or no day is usable.
    """
    from diagonal_site import recorded_directions, unturn_matrix
    from mt_workbench.ingest import archive_rot_e
    from mt_workbench.timefreq import load_station

    survey = Survey.from_yaml(survey_yaml)
    config = survey.site(site)
    archive = default_archive_path(survey, site)
    rec = load_station(archive, survey.name, site, comps=LINES + FIELD)
    missing = [c for c in LINES + FIELD if c not in rec.arrays]
    if missing:
        raise ValueError(f"{site}: {archive.name} has no {', '.join(missing)}")
    fs = rec.sample_rate
    corner = HP_FACTOR * band[1]
    # electrics back to the logger's units (archive samples): the record is (samples - offset) / gain
    scale = {c: (rec.gains[c] if c in LINES else 1.0) for c in LINES + FIELD}
    laid = archive_rot_e(archive, site)
    unturn = None
    if laid is not None:  # the recorded lines, not the turned pair; k = ey's chain gain over ex's
        unturn = unturn_matrix(*recorded_directions(laid), rec.gains["ey"] / rec.gains["ex"])
    t0 = rec.t0
    day0 = t0.floor("D")
    n_day = int(round(DAY_S * fs))
    first = int(round((day0 - t0).total_seconds() * fs))
    days, bands_by_day = [], {}
    for i0 in range(first, rec.n, n_day):
        a, b = max(i0, 0), min(i0 + n_day, rec.n)
        if (b - a) / fs < MIN_DAY_HOURS * 3600.0:
            continue
        day = (day0 + pd.Timedelta(seconds=(i0 - first) / fs)).strftime("%Y-%m-%d")
        series = {c: rec.arrays[c][a:b].astype("float64") * scale[c] for c in LINES + FIELD}
        if unturn is not None:
            xa, ya = series["ex"], series["ey"]
            series["ex"], series["ey"] = unturn[0, 0] * xa + unturn[0, 1] * ya, unturn[1, 0] * xa + unturn[1, 1] * ya
        prepared, finite = prepare_day(series, fs, corner)
        row = dict(site=site, day=day, t_start=(t0 + pd.Timedelta(seconds=a / fs)).isoformat(),
                   hours=round((b - a) / fs / 3600.0, 3), finite=round(finite, 4), chosen=False)
        if prepared is None:
            days.append(row)
            continue
        try:
            values, bands = series_stats(prepared, band)
        except np.linalg.LinAlgError:  # (hx, hy) singular on the day (a dead or flat-filled magnetometer): unusable
            days.append(row)
            continue
        row.update(values)
        days.append(row)
        bands_by_day[day] = bands
    usable = [d for d in days if "src" in d]
    if not usable:
        raise ValueError(f"{site}: no UTC day with {MIN_DAY_HOURS:g} h of the record and {MIN_FINITE:.0%} finite")
    chosen = sorted(usable, key=lambda d: d["src"], reverse=True)[:n_days]
    for d in chosen:
        d["chosen"] = True
    verdict = site_verdict(chosen)
    row = dict(site=site, phase=_phase(config.notes), azimuth_ex=config.azimuth_ex, azimuth_ey=config.azimuth_ey,
               dipole_length_ex=config.dipole_length_ex, dipole_length_ey=config.dipole_length_ey,
               h_from=config.h_from or "", days_usable=len(usable), days_used=len(chosen),
               days=" ".join(d["day"] for d in sorted(chosen, key=lambda d: d["day"])),
               days_model=sum(1 for d in usable if d["model"]), band=f"{band[0]:g}-{band[1]:g}",
               archive=str(archive), rot_e=(f"undone (laid {laid[0]:g}/{laid[1]:g})" if laid else ""), **verdict)
    band_rows = [dict(site=site, day=d["day"], **b) for d in chosen for b in bands_by_day[d["day"]]]
    return dict(row=row, days=days, bands=band_rows)


def _phase(notes) -> str:
    """Return the phase word of a site's notes ("phase 1" -> "1"), "" when they do not say."""
    text = str(notes or "").strip()
    return text.split(";")[0].replace("phase", "").strip() if text.startswith("phase") else ""


# ---------------------------------------------------------------- tables and figures


def merge_rows(path: Path, rows: list[dict], columns, key: str = "site") -> pd.DataFrame:
    """Write `rows` to a CSV, replacing the rows of their sites and keeping the others'."""
    new = pd.DataFrame(rows, columns=list(columns))
    if path.exists():
        old = pd.read_csv(path)
        old = old[~old[key].isin(set(new[key]))]
        new = pd.concat([old, new], ignore_index=True) if len(old) else new
    new = new.sort_values([key] + ([c for c in ("day", "lo_s") if c in new.columns])).reset_index(drop=True)
    tmp = path.with_name(path.name + ".tmp")
    new.to_csv(tmp, index=False)
    tmp.replace(path)
    return new


def site_figure(result: dict, path: Path) -> None:
    """Draw one site's figure: the daily timeline and the chosen days per sub-band."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter

    row, days = result["row"], pd.DataFrame(result["days"])
    bands = pd.DataFrame(result["bands"])
    fig = plt.figure(figsize=(14, 8.5))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.1], hspace=0.35, wspace=0.28)
    ax = fig.add_subplot(gs[0, :])
    use = days[days.get("src").notna()] if "src" in days else days.iloc[0:0]
    t = pd.to_datetime(use["day"])
    ax.plot(t, use["src"], "o-", color="0.45", ms=4, label="source coherence ex~ey")
    ax.plot(t, use["coh_r"], "s-", color="C3", ms=4, label="residual coherence")
    ax.axhline(MODEL_COH, color="C3", ls=":", lw=1)
    ax.axhline(CONTROL_COH, color="0.45", ls=":", lw=1)
    ch = use[use["chosen"].astype(bool)]
    ax.plot(pd.to_datetime(ch["day"]), ch["src"], "o", mfc="none", mec="k", ms=11, mew=1.5, label="chosen days")
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("coherence")
    ax2 = ax.twinx()
    ax2.plot(t, use["gain"], "^-", color="C0", ms=4, lw=0.8, label="|g| (right)")
    ax2.axhspan(*MODEL_GAIN, color="C0", alpha=0.08)
    ax2.set_yscale("log")
    ax2.set_ylim(0.05, 20)
    ax2.set_ylabel("|g| residual gain", color="C0")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower left", fontsize=8, ncol=4)
    ax.set_title("daily values (medians over octave sub-bands of %s s); model-holds days %d of %d"
                 % (row["band"], row["days_model"], row["days_usable"]), fontsize=10)
    ax.grid(alpha=0.3)
    panels = (("coh_r", "residual coherence", (0, 1.02)), ("gain", "|g| (sign of Re g in marker)", None),
              ("mcoh", "H multiple coherence of the diagonals", (0, 1.02)))
    for k, (key, label, ylim) in enumerate(panels):
        axb = fig.add_subplot(gs[1, k])
        for j, (day, g) in enumerate(bands.groupby("day")):
            mid = np.sqrt(g["lo_s"] * g["hi_s"])
            colour = f"C{j % 10}"
            if key == "mcoh":
                axb.plot(mid, g["mcoh_diff"], "o-", color=colour, label=f"{day} ex-ey")
                axb.plot(mid, g["mcoh_sum"], "x--", color=colour, label=f"{day} ex+ey")
            elif key == "gain":
                pos = g["re_g"] >= 0
                axb.plot(mid, g["gain"], "-", color=colour, label=day)
                axb.plot(mid[pos], g["gain"][pos], "+", color=colour, ms=9)
                axb.plot(mid[~pos], g["gain"][~pos], "_", color=colour, ms=9)
            else:
                axb.plot(mid, g[key], "o-", color=colour, label=day)
        axb.set_xscale("log")
        axb.xaxis.set_minor_formatter(NullFormatter())
        if key == "gain":
            axb.set_yscale("log")
            axb.yaxis.set_minor_formatter(NullFormatter())
            axb.axhspan(*MODEL_GAIN, color="C0", alpha=0.08)
        else:
            axb.set_ylim(*ylim)
        if key == "coh_r":
            axb.axhline(MODEL_COH, color="C3", ls=":", lw=1)
        axb.set_xlabel("period (s)")
        axb.set_title(label, fontsize=10)
        axb.grid(alpha=0.3, which="both")
        axb.legend(fontsize=7)
    fig.suptitle(
        f"{row['site']} shared-centre test: {row['verdict'].upper()}; residual coherence {row['resid_coh']:.2f}, "
        f"|g| {row['resid_gain']:.2f}, arg g {row['arg_g']:+.0f} deg, s_obs {row['s_obs']:+d} (pred {row['s_pred']:+d}); "
        f"H coherence ex-ey {row['mcoh_diff']:.2f}, ex+ey {row['mcoh_sum']:.2f}; remedy "
        f"{'applies' if row['remedy_applicable'] else 'does not apply'}\n"
        f"azimuths ex {row['azimuth_ex']:g} ey {row['azimuth_ey']:g}, dipoles {row['dipole_length_ex']:g} / "
        f"{row['dipole_length_ey']:g} m{'; H from ' + row['h_from'] if row['h_from'] else ''}; days {row['days']} "
        f"(source coherence max {row['src_max']:.2f})", fontsize=10)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def summary_figure(table: pd.DataFrame, path: Path, title: str) -> None:
    """Draw the survey summary: residual coherence against |g| per site, and the per-site bars."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {"holds": "C3", "control": "C2", "fails": "0.5"}
    fig, (ax, axb) = plt.subplots(1, 2, figsize=(16, 7), gridspec_kw=dict(width_ratios=[1, 1.6]))
    ax.add_patch(plt.Rectangle((MODEL_COH, MODEL_GAIN[0]), 1.0 - MODEL_COH + 0.02, MODEL_GAIN[1] - MODEL_GAIN[0],
                               color="C3", alpha=0.1, label="model holds"))
    for verdict, g in table.groupby("verdict"):
        ax.scatter(g["resid_coh"], g["resid_gain"], c=colours.get(verdict, "k"), s=28,
                   label=f"{verdict} ({len(g)})", edgecolors="k", linewidths=0.4)
        for r in g.itertuples():
            ax.annotate(str(r.site).replace("TAS", ""), (r.resid_coh, r.resid_gain), fontsize=6,
                        xytext=(2, 2), textcoords="offset points")
    ax.set_yscale("log")
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("residual coherence (median of the chosen days)")
    ax.set_ylabel("|g|")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")
    order = table.sort_values(["resid_coh"], ascending=False)
    x = np.arange(len(order))
    axb.bar(x - 0.2, order["src_max"], 0.4, color="0.6", label="source coherence ex~ey (max of chosen days)")
    axb.bar(x + 0.2, order["resid_coh"], 0.4, color=[colours.get(v, "k") for v in order["verdict"]],
            label="residual coherence (colour: verdict)")
    axb.axhline(MODEL_COH, color="C3", ls=":", lw=1)
    axb.axhline(CONTROL_COH, color="0.4", ls=":", lw=1)
    axb.set_xticks(x)
    axb.set_xticklabels([f"{s}{'*' if r else ''}" for s, r in zip(order["site"], order["remedy_applicable"])],
                        rotation=90, fontsize=7)
    axb.set_ylim(0, 1.02)
    axb.legend(fontsize=8, loc="upper right")
    axb.set_title("* remedy applies (model holds and the clean diagonal by H is the sign's)", fontsize=9)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def verdict_lines(table: pd.DataFrame) -> list[str]:
    """Return the VERDICT lines A, B and C of a site table (a criterion with nothing to judge is UNJUDGED)."""
    held = table[table["model_holds"].astype(bool)]
    ctrl = table[table["control"].astype(bool)]
    a_fail = held[held["s_obs"] != held["s_pred"]]
    b_fail = ctrl[ctrl["resid_coh"] >= MODEL_COH]
    lines = []
    if held.empty:
        lines.append("VERDICT centre A (sign prediction): UNJUDGED: no site holds the model")
    else:
        lines.append(f"VERDICT centre A (sign prediction): {len(held) - len(a_fail)} of {len(held)} sites where the "
                     f"model holds agree with s_pred {S_PRED:+d}" + ("" if a_fail.empty else
                                                                   "; FAIL at " + " ".join(a_fail["site"])))
    if ctrl.empty:
        lines.append("VERDICT centre B (control): UNJUDGED: no control site (none with a source ex-ey coherence "
                     f"under {CONTROL_COH} on every chosen day), so the test was not shown able to fail")
    else:
        lines.append(f"VERDICT centre B (control): {len(ctrl)} control sites, {len(b_fail)} with a false shared "
                     f"centre -> {'PASS' if b_fail.empty else 'FAIL ' + ' '.join(b_fail['site'])}")
    applies = table[table["remedy_applicable"].astype(bool)]["site"]
    rest = table[~table["remedy_applicable"].astype(bool)]["site"]
    lines.append(f"VERDICT centre C (remedy applicable): {' '.join(applies) or 'none'}; not applicable: "
                 f"{' '.join(rest) or 'none'}")
    return lines


def site_line(row: dict) -> str:
    """Return the one-line report of a site."""
    return (f"   {row['site']} [{row['days']}] src ex~ey {row['src_coh']:.2f} (max {row['src_max']:.2f}); residual "
            f"coh {row['resid_coh']:.2f} gain {row['resid_gain']:.2f} arg {row['arg_g']:+.0f} s_obs "
            f"{row['s_obs']:+d} (pred {row['s_pred']:+d}); H-coh diff {row['mcoh_diff']:.2f} sum "
            f"{row['mcoh_sum']:.2f} -> {row['verdict'].upper()}, clean {row['clean_obs']} (by H "
            f"{row['clean_by_H']}); model days {row['days_model']}/{row['days_usable']}"
            + (f"  [H from {row['h_from']}]" if row["h_from"] else ""))


def main(argv=None) -> int:
    """Run the test on the sites and write the tables and figures.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 done, 1 a site failed, 2 a usage error.
    """
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("survey_yaml")
    p.add_argument("sites", nargs="*", help="sites (default: every recorded site with ex, ey and an archive)")
    p.add_argument("--days", type=int, default=3, help="days of highest source coherence used (default %(default)s)")
    p.add_argument("--band", type=float, nargs=2, default=(10.0, 1000.0), metavar=("SHORT", "LONG"),
                   help="period band in s (default %(default)s)")
    p.add_argument("--out", default="", help="output folder (default <workspace>/qc/shared_centre)")
    p.add_argument("--workers", type=int, default=1, help="sites run at once (default %(default)s)")
    args = p.parse_args(argv)
    band = (float(min(args.band)), float(max(args.band)))
    if args.days < 1 or band[0] <= 0 or band[1] > NPERSEG / FS_TEST / 2:
        print(f"ERROR --days must be 1 or more and --band inside (0, {NPERSEG / FS_TEST / 2:g}] s", file=sys.stderr)
        return 2
    yaml_path = Path(args.survey_yaml).resolve()
    survey = Survey.from_yaml(yaml_path)
    sites, skipped = candidate_sites(survey, args.sites or None)
    for site, why in skipped.items():
        if args.sites:
            print(f"   {site}: left out ({why})")
    if not sites:
        print("ERROR no site to test", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else survey.workspace / "qc" / "shared_centre"
    out.mkdir(parents=True, exist_ok=True)
    print(f"shared-centre test of {len(sites)} site(s), band {band[0]:g}-{band[1]:g} s, {args.days} day(s) each -> "
          f"{out}", flush=True)
    failed, results = {}, []

    def land(site, result):
        results.append(result)
        merge_rows(out / "centre_test.csv", [result["row"]], SITE_COLUMNS)
        merge_rows(out / "centre_test_days.csv", result["days"], DAY_COLUMNS)
        merge_rows(out / "centre_test_bands.csv", result["bands"], BAND_COLUMNS)
        site_figure(result, out / f"{site}_centre_test.png")
        print(site_line(result["row"]), flush=True)

    started = time.perf_counter()
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(run_site, str(yaml_path), s, args.days, band): s for s in sites}
            for job in as_completed(jobs):
                site = jobs[job]
                try:
                    land(site, job.result())
                except Exception as exc:  # noqa: BLE001  (a site's failure is listed, the others go on)
                    failed[site] = f"{type(exc).__name__}: {exc}"
                    print(f"   {site}: FAILED {failed[site]}", flush=True)
    else:
        for site in sites:
            try:
                land(site, run_site(str(yaml_path), site, args.days, band))
            except Exception as exc:  # noqa: BLE001
                failed[site] = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
                print(f"   {site}: FAILED {failed[site]}", flush=True)
    table = pd.read_csv(out / "centre_test.csv") if (out / "centre_test.csv").exists() else pd.DataFrame()
    if not table.empty:
        summary_figure(table, out / "centre_test_summary.png",
                       f"{survey.name}: shared-centre test, {len(table)} sites, band {band[0]:g}-{band[1]:g} s, "
                       f"{args.days} days of highest ex~ey coherence each")
        print(f"table {out / 'centre_test.csv'} ({len(table)} sites); summary {out / 'centre_test_summary.png'}")
        for line in verdict_lines(table):
            print(line)
    print(f"done in {time.perf_counter() - started:.0f} s; {len(failed)} failed"
          + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=RuntimeWarning, message="invalid value encountered")
    sys.exit(main())
