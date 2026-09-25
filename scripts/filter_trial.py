# -*- coding: utf-8 -*-
"""
Trial of candidate filter chains on one window of a site's raw archive

Loads one window of a site's raw archive (`<workspace>/mth5/<site>.h5`, read
by `crust.gui.segment.load_segment`: calibrated, offset-removed, the
magnetics in nT through the scalar gain), runs each candidate filter chain
over it with `crust.noise.apply_filters_arrays` and measures what the chain
did, so a chain can be judged on a window before it is declared for the
site. A chain is a YAML file holding a list of filters in the syntax of
`<survey>/filters.yaml` (the kinds are described in the module docstring of
`crust.noise`), or a mapping whose key is the site and whose value is that
list. `--declared` adds the site's current list as the chain "declared". The
window as recorded, "raw", is the reference every chain is compared with.
This is the command-line form of the preview on the GUI's Filter Data tab.

`trial_metrics` measures raw and each filtered window alike: the Welch PSD
at 0.05 Hz resolution (Hann, half overlap, constant detrend) over 5-500 Hz;
the excess of every evaluated line over its local floor per channel
(`crust.timefreq.line_excess`); the floor between the lines, the median PSD
in dB over 5-45, 55-95, 105-145, 155-195 and 205-245 Hz with +-1 Hz around
every evaluated line set aside; the band-averaged squared coherence of ey-hx
and ex-hy on the survey's processing bands (`crust.qc.band_coherence` on
`crust.bands.build_band_scheme` with the survey's `processing:` keys) and
its means over 0.005-0.02, 0.02-0.2, 0.2-2 and 2-20 s; the burst fraction of
each magnetic channel and the step fraction of each electric channel as
`scripts/line_noise_profile.py` defines `burst_*` and `step_*`, the 60 s
running median taken over the window with its ends padded by the end values;
and the full-band `crust.timefreq.psd_ladder` for the figure. The evaluated
lines are 50 Hz and its harmonics below Nyquist, every `extra:` line of the
chains' notches and, with `--lines`, every non-mains line of the site's line
scan (`scripts/line_scan.py`) seen in at least 3 hours. The scan is read from
`<workspace>/qc/lines_<site>.csv` when present, its detections grouped to
0.15 Hz as the scan groups its summary, and otherwise from the site's last
block in `<workspace>/qc/lines_summary.txt`. Lines from 5 Hz up to 500 Hz
and below Nyquist are kept, and a line within 0.05 Hz of one kept before
it (the mains, then the chains' lines, then the scan's) shares its Welch bin
and is merged into it.

`--remote NAME` loads the remote's window over the same samples from its raw
archive, applies the remote's declared filters and adds hx-r_hx, hy-r_hy,
ex-r_hy and ey-r_hx to the coherence; the remote arrays are the same for raw
and every chain. The window of a `replace` filter's donor is read from the
donor's raw archive over the same samples.

Usage:
    python scripts/filter_trial.py <survey.yaml> <site> <start> <end>
                                   [--chain LABEL=FILE.yaml ...] [--declared]
                                   [--remote NAME] [--lines] [--out DIR]

    start and end are UTC ISO times (a time without a zone is taken as
    UTC); the window is 5 min to 3 h long.

    Writes, per chain, under `--out` (default
    `<workspace>/qc/filter_trials/<site>/`), where `<stem>` is
    `<site>_<label>_<YYYYMMDDTHHMM>` of the window's first sample:

        <stem>_psd.png         5-500 Hz Welch PSD per channel with the
                               evaluated lines marked, and the full-band
                               ladder below it; raw grey, the chain coloured
        <stem>_timeseries.png  every channel over the window, and 20 s
                               around the largest |raw - filtered| on the
                               electrics
        <stem>_coherence.png   squared coherence against period per pair
        <stem>.json            window, chain, provenance, raw and filtered
                               metrics, package versions

    and prints one summary block per chain.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "4")

import argparse
import inspect
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import yaml
from loguru import logger
from scipy import ndimage, signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.bands import build_band_scheme
from crust.noise import apply_filters_arrays
from crust.qc import band_coherence
from crust.survey import Survey
from crust.timefreq import line_excess, psd_ladder
from crust.gui.channels import REMOTE_COMPS, kind, label as channel_label, order, resolve_pairs, roles, unit
from crust.gui.segment import load_segment

DPI = 150
WORKERS = 4  # threads per filter, as in the Filter Data tab's preview
MIN_WINDOW_S = 300.0  # the ladder's first stage needs 262 s at 1000 Hz
MAX_WINDOW_H = 3.0
WELCH_DF = 0.05  # resolution of the line metrics, Hz
LINE_BAND = (5.0, 500.0)  # Hz kept for the line metrics and the upper PSD row
MAINS_F0 = 50.0
FLOOR_BANDS = ((5.0, 45.0), (55.0, 95.0), (105.0, 145.0), (155.0, 195.0), (205.0, 245.0))
FLOOR_GUARD_HZ = 1.0  # set aside around every evaluated line in the floor
COH_GROUPS_S = ((0.005, 0.02), (0.02, 0.2), (0.2, 2.0), (2.0, 20.0))
LOCAL_PAIRS = (("ey", "hx"), ("ex", "hy"))
REMOTE_PAIRS = (("hx", "r_hx"), ("hy", "r_hy"), ("ex", "r_hy"), ("ey", "r_hx"))
MIN_LINE_HOURS = 3  # hours a scanned line must be seen in to be evaluated
LINE_GROUP_HZ = 0.15  # the grouping of scripts/line_scan.py's summary
# the step and burst measures of scripts/line_noise_profile.py
STEP_FS = 10.0
MEDIAN_S = 60.0
K_MAD = 6.0
MAD_SCALE = 1.4826
BURST_BAND = (5.0, 200.0)
BURST_ORDER = 4
# figures
STAGE_LO = 0.002  # a ladder stage is drawn from fs * STAGE_LO up to the low edge of the stage above
ZOOM_S = 20.0
ENVELOPE_COLUMNS = 2000  # min-max columns per whole-window time-series panel
RAW_COLOUR = "0.62"
B_COLOUR = "#0277bd"  # magnetics: the GUI's cyan-blue, darker for a white page
E_COLOUR = "#d32f2f"  # electrics: the GUI's red, darker for a white page
MAINS_MARK = "#ef6c00"
EXTRA_MARK = "0.35"
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line of filter_trial.py."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("site", help="site name (raw archive <workspace>/mth5/<site>.h5)")
    p.add_argument("start", help="window start, UTC ISO time")
    p.add_argument("end", help="window end, UTC ISO time")
    p.add_argument(
        "--chain", action="append", default=[], metavar="LABEL=FILE.yaml",
        help="a candidate chain: LABEL names it in the outputs, FILE.yaml holds its filter list (repeatable)",
    )
    p.add_argument("--declared", action="store_true", help="also try the site's declared filters as 'declared'")
    p.add_argument("--remote", metavar="NAME", help="remote site: adds the remote coherence pairs")
    p.add_argument(
        "--lines", action="store_true",
        help=f"also evaluate the site's scanned non-mains lines seen in >= {MIN_LINE_HOURS} hours",
    )
    p.add_argument("--out", metavar="DIR", help="output folder (default <workspace>/qc/filter_trials/<site>/)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- inputs


def parse_window(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Parse the window's UTC start and end.

    Args:
        start (str): ISO time; a time without a zone is taken as UTC.
        end (str): ISO time.

    Returns:
        tuple[pd.Timestamp, pd.Timestamp]: Start and end, tz-aware UTC.

    Raises:
        ValueError: If the window is shorter than MIN_WINDOW_S or longer
            than MAX_WINDOW_H.
    """
    t = [pd.Timestamp(s) for s in (start, end)]
    t = [x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC") for x in t]
    length = (t[1] - t[0]).total_seconds()
    if not MIN_WINDOW_S <= length <= MAX_WINDOW_H * 3600.0:
        raise ValueError(f"the window is {length:g} s long; it must be {MIN_WINDOW_S:g} s to {MAX_WINDOW_H:g} h")
    return t[0], t[1]


def read_chain(path: Path, site: str) -> list[dict]:
    """Read a candidate chain from a YAML file.

    Args:
        path (Path): A YAML list of single-key filter dicts, as a site's
            entry in filters.yaml, or a mapping whose `site` key holds one.
        site (str): The site, looked up in a mapping.

    Returns:
        list[dict]: The filter list as written.

    Raises:
        ValueError: If the file holds neither form.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and site in data:
        data = data[site]
    data = [] if data is None else data
    if not isinstance(data, list) or not all(isinstance(e, dict) and len(e) == 1 for e in data):
        raise ValueError(f"{path}: expected a list of single-key filter entries, as a site's entry in filters.yaml")
    return data


def collect_chains(specs: list[str], declared: bool, site: str, site_filters: list | None) -> list[tuple[str, list]]:
    """Resolve `--chain LABEL=FILE.yaml` arguments and `--declared` to labelled filter lists.

    Args:
        specs (list[str]): The `--chain` arguments.
        declared (bool): Whether `--declared` was given.
        site (str): The site.
        site_filters (list | None): The site's declared filters.

    Returns:
        list[tuple[str, list]]: (label, filters), "declared" first when asked.

    Raises:
        ValueError: If an argument has no "=", a label is unusable in a file
            name, is "raw" or repeats.
    """
    chains = [("declared", list(site_filters or []))] if declared else []
    for spec in specs:
        label, sep, path = spec.partition("=")
        if not sep or not path:
            raise ValueError(f"--chain {spec!r}: expected LABEL=FILE.yaml")
        if not LABEL_RE.match(label) or label == "raw":
            raise ValueError(f"--chain {spec!r}: the label must be letters, digits, _ . + - and not 'raw'")
        if label in {c[0] for c in chains}:
            raise ValueError(f"--chain {spec!r}: label {label!r} is used twice")
        chains.append((label, read_chain(Path(path), site)))
    return chains


def mains_lines(fs: float) -> list[float]:
    """50 Hz and its harmonics below Nyquist."""
    return [k * MAINS_F0 for k in range(1, int(0.5 * fs / MAINS_F0) + 1) if k * MAINS_F0 < 0.5 * fs]


def chain_extras(chains: list[tuple[str, list]]) -> list[float]:
    """Every `extra:` line of the notches of the chains, in Hz."""
    out = []
    for _label, filters in chains:
        for spec in filters:
            if "notch" in spec:
                out += [float(f) for f in (spec["notch"] or {}).get("extra", []) or []]
    return out


def scanned_lines(qc_dir: Path, site: str) -> tuple[list[float], str]:
    """Read the site's non-mains lines seen in at least MIN_LINE_HOURS hours of its line scan.

    `lines_<site>.csv` is grouped as `scripts/line_scan.py` groups its
    summary: detections sorted by frequency, a step of at most
    LINE_GROUP_HZ joining a group, a group being mains when any detection
    in it is, its hours the distinct (run, hour) pairs. Without the CSV the
    site's last block in `lines_summary.txt` is read.

    Args:
        qc_dir (Path): `<workspace>/qc`.
        site (str): The site.

    Returns:
        tuple[list[float], str]: The line frequencies in Hz and their source
        file (empty when neither file has the site).
    """
    csv = qc_dir / f"lines_{site}.csv"
    if csv.exists():
        df = pd.read_csv(csv).sort_values("f_hz")
        f = df["f_hz"].to_numpy(float)
        group = np.concatenate([[0], np.cumsum(np.diff(f) > LINE_GROUP_HZ)]) if f.size else np.array([], int)
        out = []
        for _g, sub in df.groupby(group):
            hours = len(set(zip(sub["run"], sub["hour_start_utc"])))
            if not sub["mains_harmonic"].astype(bool).any() and hours >= MIN_LINE_HOURS:
                out.append(round(float(sub["f_hz"].mean()), 3))
        return out, str(csv)
    summary = qc_dir / "lines_summary.txt"
    if not summary.exists():
        return [], ""
    blocks = re.split(r"^=== (\S+) ===$", summary.read_text(encoding="utf-8"), flags=re.M)
    mine = [body for name, body in zip(blocks[1::2], blocks[2::2]) if name == site]
    if not mine:
        return [], ""
    pattern = re.compile(r"^\s*([\d.]+) Hz\s+channels:.*?(\d+)/\s*\d+\s+h\s+max\s+\S+ dB(\s+\[mains\])?\s*$", re.M)
    out = [float(m.group(1)) for m in pattern.finditer(mine[-1])
           if not m.group(3) and int(m.group(2)) >= MIN_LINE_HOURS]
    return out, str(summary)


def band_scheme(fs: float, processing: dict) -> dict:
    """Build the survey's band scheme from the `processing:` keys `build_band_scheme` accepts.

    Args:
        fs (float): Sample rate in Hz.
        processing (dict): The survey's `processing:` block.

    Returns:
        dict: The band scheme.
    """
    accepted = set(inspect.signature(build_band_scheme).parameters) - {"sample_rate"}
    kwargs = {k: v for k, v in (processing or {}).items() if k in accepted}
    if "notch_frequencies" in kwargs:
        kwargs["notch_frequencies"] = tuple(kwargs["notch_frequencies"] or ())
    return build_band_scheme(fs, **kwargs)


def _on_grid(seg, other) -> bool:
    """True when `other` has `seg`'s rate and length and starts within half a sample of it."""
    return (other.sample_rate == seg.sample_rate and other.n == seg.n
            and abs((other.t0 - seg.t0).total_seconds() * seg.sample_rate) <= 0.5)


def load_donors(survey: Survey, filters: list[dict], seg) -> tuple[dict, list[str]]:
    """Read the coils of every `replace` donor over the window's samples.

    Args:
        survey (Survey): The survey.
        filters (list[dict]): A filter list.
        seg: The window's `Segment`.

    Returns:
        tuple[dict, list[str]]: ``{donor: {comp: array}}`` and a note per
        donor left out.
    """
    names = sorted({str(s) for f in filters if "replace" in f for s in (f["replace"] or {}).values()})
    donors, notes = {}, []
    for name in names:
        path = survey.workspace / "mth5" / f"{name}.h5"
        if not path.exists():
            notes.append(f"donor {name} has no raw archive at {path}")
            continue
        try:
            d = load_segment(path, survey.name, name, seg.t0, seg.end, REMOTE_COMPS)
        except ValueError as exc:
            notes.append(f"donor {name} does not cover this window ({exc})")
            continue
        if _on_grid(seg, d):
            donors[name] = d.arrays
        else:
            notes.append(f"donor {name} is not on this window's sample grid")
    return donors, notes


def load_remote(survey: Survey, name: str, seg) -> tuple[dict | None, dict]:
    """Read the remote's coils over the window's samples and apply its declared filters.

    Args:
        survey (Survey): The survey.
        name (str): Remote site.
        seg: The local window's `Segment`.

    Returns:
        tuple[dict | None, dict]: The filtered coils (None when the remote
        does not cover the window's grid) and a record of the remote for
        the JSON (name, filters, provenance, note).
    """
    info = {"name": name, "filters": [], "provenance": [], "note": ""}
    path = survey.workspace / "mth5" / f"{name}.h5"
    if not path.exists():
        info["note"] = f"remote {name} has no raw archive at {path}, local pairs only"
        return None, info
    try:
        r = load_segment(path, survey.name, name, seg.t0, seg.end, REMOTE_COMPS)
    except ValueError as exc:
        info["note"] = f"remote {name} does not cover this window, local pairs only ({exc})"
        return None, info
    if not _on_grid(seg, r):
        info["note"] = f"remote {name} is not on the local window's sample grid, local pairs only"
        return None, info
    filters = list(survey.site(name).filters or [])
    donors, notes = load_donors(survey, filters, r)
    out, provenance = apply_filters_arrays(r.arrays, r.sample_rate, filters, tag=name, donors=donors, workers=WORKERS)
    info.update(filters=filters, provenance=notes + provenance)
    return {c: np.asarray(a, dtype="float64") for c, a in out.items()}, info


# ---------------------------------------------------------------- metrics


def _frac_beyond(x: np.ndarray) -> float:
    """Fraction of `x` farther than K_MAD scaled MADs from zero, the MAD taken about zero."""
    mad = float(np.median(np.abs(x)))
    if not np.isfinite(mad) or mad == 0.0:
        return float("nan")
    return float(np.mean(np.abs(x) > K_MAD * MAD_SCALE * mad))


def _step_fraction(x: np.ndarray, fs: float) -> float:
    """`step_*` of scripts/line_noise_profile.py over the whole of `x`.

    The fraction of the STEP_FS samples (every n-th, no anti-alias filter)
    farther than K_MAD scaled MADs from a MEDIAN_S running median, the MAD
    from the residuals.
    """
    dec = max(1, int(round(fs / STEP_FS)))
    y = np.asarray(x[::dec], dtype="float64")
    width = int(round(MEDIAN_S * fs / dec)) | 1
    res = y - ndimage.median_filter(y, size=width, mode="nearest")
    mad = float(np.median(np.abs(res)))
    if not np.isfinite(mad) or mad == 0.0:
        return float("nan")
    return float(np.mean(np.abs(res) > K_MAD * MAD_SCALE * mad))


def _band_means(periods: np.ndarray, gamma2: np.ndarray) -> dict[str, float]:
    """Mean squared coherence over the bands whose centre period lies in each COH_GROUPS_S group."""
    out = {}
    for lo, hi in COH_GROUPS_S:
        m = (periods >= lo) & (periods < hi) & np.isfinite(gamma2)
        out[f"{lo:g}-{hi:g} s"] = float(np.mean(gamma2[m])) if m.any() else float("nan")
    return out


def trial_metrics(arrays: dict[str, np.ndarray], fs: float, scheme: dict, lines=(), remote: dict | None = None) -> dict:
    """Measure one window: line excess, floor, coherence, bursts, steps and the PSDs.

    The module docstring defines each measure. The evaluated lines are 50 Hz
    and its harmonics below Nyquist plus `lines`, those from LINE_BAND[0]
    up to LINE_BAND[1] and below Nyquist; a line within WELCH_DF of one
    already kept (mains first, then `lines` in order) shares its Welch bin
    and is merged into it. The inputs are left unchanged.

    Args:
        arrays (dict): Local channel name to samples.
        fs (float): Sample rate in Hz.
        scheme (dict): Band scheme from `crust.bands.build_band_scheme`.
        lines (iterable of float): Lines evaluated besides the mains, Hz.
        remote (dict | None): The remote's coils on the same samples.

    Returns:
        dict: fs, n, channels, lines_hz, line_excess_db (per channel, one
        value per line), floor_db (per channel and band), coherence (per
        pair: period_s, gamma2, band_means), burst, step, and for the
        figures `_welch` (freqs, {channel: PSD}) and `_ladder`.
    """
    comps = order(arrays)
    top = min(LINE_BAND[1], 0.5 * fs)
    evaluated: list[float] = []
    for f in (round(float(f), 3) for f in [*mains_lines(fs), *lines]):
        if LINE_BAND[0] <= f <= top and f < 0.5 * fs and all(abs(f - g) >= WELCH_DF for g in evaluated):
            evaluated.append(f)
    evaluated.sort()
    nperseg = int(round(fs / WELCH_DF))
    out: dict = {"fs": float(fs), "n": int(len(arrays[comps[0]])), "channels": comps, "lines_hz": evaluated,
                 "line_excess_db": {}, "floor_db": {}, "coherence": {}, "burst": {}, "step": {}}
    welch_psd, freqs = {}, None
    for c in comps:
        f, p = signal.welch(np.asarray(arrays[c], dtype="float64"), fs=fs, window="hann", nperseg=nperseg,
                            noverlap=nperseg // 2, detrend="constant")
        keep = (f >= LINE_BAND[0]) & (f <= top)
        freqs, welch_psd[c] = f[keep], p[keep]
    guard = np.zeros(freqs.size, bool)
    for f0 in evaluated:
        guard |= np.abs(freqs - f0) <= FLOOR_GUARD_HZ
    for c in comps:
        out["line_excess_db"][c] = [line_excess(freqs, welch_psd[c], f0) for f0 in evaluated]
        out["floor_db"][c] = {}
        for lo, hi in FLOOR_BANDS:
            m = (freqs >= lo) & (freqs <= hi) & ~guard
            if hi < 0.5 * fs and m.any():
                out["floor_db"][c][f"{lo:g}-{hi:g} Hz"] = float(10.0 * np.log10(np.median(welch_psd[c][m])))

    local_roles = roles(comps)
    pairs = resolve_pairs(LOCAL_PAIRS, local_roles)
    series = dict(arrays)
    if remote:
        series.update({f"r_{c}": a for c, a in remote.items()})
        pairs += resolve_pairs(REMOTE_PAIRS, local_roles, roles(list(remote), prefix="r_"))
    for a, b in pairs:
        periods, g2 = band_coherence(np.asarray(series[a], dtype="float64"), np.asarray(series[b], dtype="float64"),
                                     fs, scheme)
        out["coherence"][f"{a}-{b}"] = {"period_s": periods.tolist(), "gamma2": g2.tolist(),
                                        "band_means": _band_means(periods, g2)}

    sos = signal.butter(BURST_ORDER, BURST_BAND, btype="band", fs=fs, output="sos")
    for c in comps:
        if kind(c) == "magnetic":
            out["burst"][c] = _frac_beyond(signal.sosfiltfilt(sos, np.asarray(arrays[c], dtype="float64")))
        elif kind(c) == "electric":
            out["step"][c] = _step_fraction(arrays[c], fs)

    ladder: list = []
    for c in comps:
        for level, (fs_k, f_k, row) in enumerate(psd_ladder({c: np.array(arrays[c], dtype="float64")}, [], fs, [c])):
            if level == len(ladder):
                ladder.append((fs_k, f_k, {}))
            ladder[level][2].update(row)
    out["_welch"] = (freqs, welch_psd)
    out["_ladder"] = ladder
    return out


# ---------------------------------------------------------------- summary


def _nan(v) -> float:
    """`v` as a float, NaN for None."""
    return float("nan") if v is None else float(v)


def summary_block(site: str, label: str, n_filters: int, raw: dict, filt: dict) -> str:
    """Build the console block of one chain: coherence, line excess, floor, bursts and steps.

    Args:
        site (str): The site.
        label (str): The chain's label.
        n_filters (int): Number of filters in the chain.
        raw (dict): `trial_metrics` of the raw window.
        filt (dict): `trial_metrics` of the filtered window.

    Returns:
        str: The block.
    """
    out = [f"=== {site} {label} ({n_filters} filter{'s' if n_filters != 1 else ''}) ===",
           "coherence band means, raw -> filtered"]
    for pair, c in raw["coherence"].items():
        parts = [f"{g} {_nan(v):.3f} -> {_nan(filt['coherence'][pair]['band_means'][g]):.3f}"
                 for g, v in c["band_means"].items()]
        out.append(f"  {pair:<9} " + "   ".join(parts))

    def worst(m: dict) -> tuple[float, str]:
        best, where = -np.inf, "none"
        for c, vals in m["line_excess_db"].items():
            for f0, v in zip(m["lines_hz"], vals):
                if np.isfinite(v) and v > best:
                    best, where = v, f"{c} @ {f0:g} Hz"
        return best, where

    (fv, fw), (rv, rw) = worst(filt), worst(raw)
    out.append(f"line excess over {len(raw['lines_hz'])} lines: max remaining {fv:+.1f} dB ({fw}); "
               f"raw max {rv:+.1f} dB ({rw})")
    bands = list(next(iter(raw["floor_db"].values()), {}))
    out.append("floor change, filtered - raw (dB): " + "  ".join(f"{b:>11}" for b in bands))
    for c, vals in raw["floor_db"].items():
        out.append(f"  {c:<32} " + "  ".join(f"{filt['floor_db'][c][b] - vals[b]:+11.2f}" for b in bands))
    bs = [f"burst {c} {v:.4f} -> {filt['burst'][c]:.4f}" for c, v in raw["burst"].items()]
    bs += [f"step {c} {v:.4f} -> {filt['step'][c]:.4f}" for c, v in raw["step"].items()]
    out.append("  ".join(bs))
    return "\n".join(out)


# ---------------------------------------------------------------- figures and JSON


def _colour(comp: str) -> str:
    """The chain's colour for a channel or pair: magnetics blue, electrics red."""
    return B_COLOUR if kind(comp) == "magnetic" else E_COLOUR


def _public(m: dict) -> dict:
    """The JSON part of a `trial_metrics` result (the keys without a leading underscore)."""
    return {k: v for k, v in m.items() if not k.startswith("_")}


def _jsonable(x):
    """`x` with numpy scalars as Python numbers, tuples as lists and non-finite floats as None."""
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


def _is_mains(f0: float) -> bool:
    """True for 50 Hz or one of its harmonics."""
    return abs(f0 / MAINS_F0 - round(f0 / MAINS_F0)) < 1e-6


def _psd_ylim(ax, raw_psd: np.ndarray, filt_psd: np.ndarray) -> None:
    """Set a PSD panel's y-limits: two decades under the raw's 1st percentile up to 3x the highest value.

    The lower limit follows the raw spectrum, so a notch's dip runs off the
    bottom of the panel and the floor and the lines keep the height.
    """
    r = raw_psd[np.isfinite(raw_psd) & (raw_psd > 0)]
    both = np.concatenate([r, filt_psd[np.isfinite(filt_psd) & (filt_psd > 0)]])
    if r.size:
        ax.set_ylim(np.percentile(r, 1.0) / 100.0, both.max() * 3.0)


def _psd_figure(path: Path, title: str, label: str, raw: dict, filt: dict) -> None:
    """Draw the 5-500 Hz Welch PSDs (top row) and the full-band ladders (bottom row) per channel."""
    comps = raw["channels"]
    fig, axes = plt.subplots(2, len(comps), figsize=(4.0 * len(comps), 7.6), layout="constrained", squeeze=False)
    fr, pr = raw["_welch"]
    ff, pf = filt["_welch"]
    for j, c in enumerate(comps):
        ax = axes[0, j]
        for f0 in raw["lines_hz"]:
            mains = _is_mains(f0)
            ax.axvline(f0, color=MAINS_MARK if mains else EXTRA_MARK, lw=0.5, ls=":" if mains else "--",
                       alpha=0.7 if mains else 0.45, zorder=0)
        ax.loglog(fr, pr[c], color=RAW_COLOUR, lw=0.7, label="raw", zorder=2)
        ax.loglog(ff, pf[c], color=_colour(c), lw=1.1, label=label, zorder=3)
        _psd_ylim(ax, pr[c], pf[c])
        ax.set_xlim(LINE_BAND[0], min(LINE_BAND[1], 0.5 * raw["fs"]))
        ax.set_title(f"{channel_label(c)}, {WELCH_DF:g} Hz resolution", fontsize=10)
        ax.set_xlabel("frequency (Hz)")
        ax.grid(alpha=0.25, which="both")
        ax = axes[1, j]
        hi, drawn_raw, drawn_filt = None, [], []
        for (fs_k, f_k, row), (_fs, _f, row_f) in zip(raw["_ladder"], filt["_ladder"]):
            lo, top = fs_k * STAGE_LO, (fs_k / 2.0 if hi is None else hi)
            m = (f_k >= lo) & (f_k <= top)
            ax.loglog(f_k[m], row[c][m], color=RAW_COLOUR, lw=0.7, label="raw" if hi is None else None)
            ax.loglog(f_k[m], row_f[c][m], color=_colour(c), lw=1.0, label=label if hi is None else None)
            drawn_raw.append(row[c][m])
            drawn_filt.append(row_f[c][m])
            hi = lo
        if drawn_raw:
            _psd_ylim(ax, np.concatenate(drawn_raw), np.concatenate(drawn_filt))
        if not raw["_ladder"]:
            ax.text(0.5, 0.5, "window too short for the ladder", transform=ax.transAxes, ha="center", color="0.5")
        ax.set_title(f"{channel_label(c)}, full band (PSD ladder)", fontsize=10)
        ax.set_xlabel("frequency (Hz)")
        ax.grid(alpha=0.25, which="both")
        for row in axes[:, j]:
            row.set_ylabel(f"PSD (({unit(c)})$^2$/Hz)")
    axes[0, 0].legend(fontsize=8, loc="lower left")
    fig.suptitle(title + "\norange dotted: 50 Hz and harmonics; grey dashed: other evaluated lines", fontsize=10)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def _envelope(x: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split `x` into `columns` blocks and return each block's first index, minimum and maximum."""
    edges = np.linspace(0, x.size, min(columns, x.size) + 1).astype(int)[:-1]
    return edges, np.minimum.reduceat(x, edges), np.maximum.reduceat(x, edges)


def _timeseries_figure(path: Path, title: str, label: str, raw: dict, filt: dict, fs: float, t0: str) -> None:
    """Draw every channel over the window as min-max envelopes and a 20 s zoom on the electrics."""
    comps = order(raw)
    n = len(raw[comps[0]])
    fig, axes = plt.subplots(len(comps) + 1, 1, figsize=(13.0, 1.8 * (len(comps) + 1) + 1.0), layout="constrained")
    for ax, c in zip(axes, comps):
        for arrays, colour, name in ((raw, RAW_COLOUR, "raw"), (filt, _colour(c), label)):
            i, lo, hi = _envelope(np.asarray(arrays[c]), ENVELOPE_COLUMNS)
            ax.fill_between(i / fs / 60.0, lo, hi, step="post", color=colour, lw=0, label=name,
                            alpha=1.0 if name == "raw" else 0.85)
        ax.set_ylabel(f"{channel_label(c)} ({unit(c)})")
        ax.set_xlim(0.0, n / fs / 60.0)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7, loc="upper right")
    axes[len(comps) - 1].set_xlabel(f"minutes from {t0}")
    best, where = 0.0, None
    for c in (c for c in comps if kind(c) == "electric"):
        d = np.abs(np.asarray(raw[c], dtype="float64") - np.asarray(filt[c], dtype="float64"))
        k = int(np.argmax(d))
        if d[k] > best:
            best, where = float(d[k]), (c, k)
    half = int(round(ZOOM_S * fs / 2.0))
    ax = axes[-1]
    if where is None:
        c, k = next((c for c in comps if kind(c) == "electric"), comps[0]), n // 2
        what = f"{channel_label(c)}, 20 s at mid-window (the chain leaves the electrics unchanged)"
    else:
        c, k = where
        what = f"{channel_label(c)}, 20 s around the largest |raw - filtered| ({best:.3g} {unit(c)} at {k / fs:.2f} s)"
    i0 = int(np.clip(k - half, 0, max(0, n - 2 * half)))
    i1 = min(n, i0 + 2 * half)
    t = np.arange(i0, i1) / fs
    ax.plot(t, raw[c][i0:i1], color=RAW_COLOUR, lw=0.6, label="raw")
    ax.plot(t, filt[c][i0:i1], color=_colour(c), lw=0.9, label=label)
    ax.set_title(what, fontsize=9)
    ax.set_xlabel(f"seconds from {t0}")
    ax.set_ylabel(f"{channel_label(c)} ({unit(c)})")
    ax.set_xlim(t[0], t[-1])
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="upper right")
    fig.suptitle(title, fontsize=10)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def _coherence_figure(path: Path, title: str, label: str, raw: dict, filt: dict) -> None:
    """Draw squared coherence against period per pair, raw grey and filtered coloured."""
    pairs = list(raw["coherence"])
    ncols = 2 if len(pairs) > 1 else 1
    nrows = max(1, -(-len(pairs) // ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.2 * ncols, 3.2 * nrows + 0.8), layout="constrained",
                             squeeze=False)
    for ax, pair in zip(axes.flat, pairs):
        r, f = raw["coherence"][pair], filt["coherence"][pair]
        ax.semilogx(r["period_s"], r["gamma2"], color=RAW_COLOUR, lw=0.9, marker=".", ms=3, label="raw")
        ax.semilogx(f["period_s"], f["gamma2"], color=_colour(pair.split("-")[0]), lw=1.6, marker=".", ms=3,
                    label=label)
        for lo, hi in COH_GROUPS_S:
            ax.axvline(lo, color="0.8", lw=0.6, zorder=0)
        ax.axvline(COH_GROUPS_S[-1][1], color="0.8", lw=0.6, zorder=0)
        text = "\n".join(f"{g}: {_nan(v):.2f} -> {_nan(f['band_means'][g]):.2f}" for g, v in r["band_means"].items())
        ax.text(0.99, 0.03, text, transform=ax.transAxes, ha="right", va="bottom", fontsize=7,
                bbox=dict(facecolor="white", edgecolor="0.8", alpha=0.85))
        a, b = pair.split("-")
        ax.set_title(f"{channel_label(a)}-{channel_label(b)}", fontsize=10)
        ax.set_ylim(0.0, 1.02)
        ax.set_xlabel("period (s)")
        ax.set_ylabel(r"$\gamma^2$")
        ax.grid(alpha=0.25, which="both")
        ax.legend(fontsize=7, loc="upper left")
    for ax in list(axes.flat)[len(pairs):]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=10)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def write_trial(out_dir: Path, stem: str, info: dict, raw: dict, filt: dict, raw_arrays: dict,
                filt_arrays: dict) -> list[Path]:
    """Write one chain's three figures and its JSON.

    Args:
        out_dir (Path): Output folder, created if missing.
        stem (str): File stem, `<site>_<label>_<YYYYMMDDTHHMM>`.
        info (dict): What the JSON records besides the metrics: at least
            site, label and t0 (ISO); the chain, provenance, window,
            remote, lines and versions as the driver gives them.
        raw (dict): `trial_metrics` of the raw window.
        filt (dict): `trial_metrics` of the filtered window.
        raw_arrays (dict): The raw window's samples.
        filt_arrays (dict): The filtered samples.

    Returns:
        list[Path]: The PSD, time-series and coherence figures, then the JSON.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    label = info["label"]
    title = f"{info['site']}: chain '{label}' against raw, window from {info['t0']}"
    paths = [out_dir / f"{stem}_{p}.png" for p in ("psd", "timeseries", "coherence")] + [out_dir / f"{stem}.json"]
    _psd_figure(paths[0], title, label, raw, filt)
    _timeseries_figure(paths[1], title, label, raw_arrays, filt_arrays, raw["fs"], info["t0"])
    _coherence_figure(paths[2], title, label, raw, filt)
    payload = {**info, "raw": _public(raw), "filtered": _public(filt)}
    with open(paths[3], "w", encoding="utf-8") as f:
        json.dump(_jsonable(payload), f, indent=1)
    return paths


def versions() -> dict[str, str]:
    """numpy and scipy versions and the repository's git head when git answers."""
    out = {"numpy": np.__version__, "scipy": scipy.__version__}
    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10)
        if head.returncode == 0:
            out["crust_git_head"] = head.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return out


# ---------------------------------------------------------------- driver


def main(argv=None) -> None:
    """Load the window, try every chain, write the figures and JSON and print the summaries.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Raises:
        FileNotFoundError: When the site has no raw archive.
        ValueError: When the window, a chain or its filters are invalid.
    """
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    start, end = parse_window(args.start, args.end)
    site_cfg = survey.site(args.site)
    chains = collect_chains(args.chain, args.declared, args.site, site_cfg.filters)
    if not chains:
        raise ValueError("give at least one --chain LABEL=FILE.yaml or --declared")
    h5 = survey.workspace / "mth5" / f"{args.site}.h5"
    if not h5.exists():
        raise FileNotFoundError(f"no raw archive for {args.site}: {h5}")
    out_dir = Path(args.out) if args.out else survey.workspace / "qc" / "filter_trials" / args.site

    t_start = time.time()
    seg = load_segment(h5, survey.name, args.site, start, end, site_cfg.channels)
    fs = seg.sample_rate
    t0 = seg.t0.isoformat()
    logger.info(f"{args.site}: {seg.n} samples at {fs:g} Hz from {t0} ({seg.duration_s / 60:.1f} min, "
                f"{', '.join(order(seg.arrays))}) in {time.time() - t_start:.1f} s")
    if seg.gaps:
        logger.warning(f"{args.site}: {len(seg.gaps)} gap(s) in the window, zeroed")
    scheme = band_scheme(fs, survey.processing)

    scan, scan_source = scanned_lines(survey.workspace / "qc", args.site) if args.lines else ([], "")
    if args.lines:
        logger.info(f"--lines: {len(scan)} line(s) seen in >= {MIN_LINE_HOURS} h from {scan_source or 'no scan'}")
    extra = [*chain_extras(chains), *scan]

    remote, remote_info = None, None
    if args.remote:
        remote, remote_info = load_remote(survey, args.remote, seg)
        if remote is None:
            logger.warning(remote_info["note"])
        else:
            logger.info(f"remote {args.remote}: {', '.join(remote)}; {len(remote_info['filters'])} declared filter(s)")

    t = time.time()
    raw = trial_metrics(seg.arrays, fs, scheme, extra, remote)
    logger.info(f"raw metrics: {len(raw['lines_hz'])} line(s), {len(raw['coherence'])} pair(s) "
                f"in {time.time() - t:.1f} s")
    window = {"start": start.isoformat(), "end": end.isoformat(), "t0": t0, "n": seg.n, "sample_rate": fs,
              "gaps": seg.gaps, "archive": str(h5)}
    common = {"site": args.site, "survey": survey.name, "t0": t0, "window": window, "remote": remote_info,
              "lines": {"scan_source": scan_source, "scan_hz": scan, "chain_extra_hz": chain_extras(chains)},
              "versions": versions()}

    written = []
    for label, filters in chains:
        t = time.time()
        donors, notes = load_donors(survey, filters, seg)
        filtered, provenance = apply_filters_arrays(seg.arrays, fs, filters, tag=args.site, donors=donors,
                                                    workers=WORKERS)
        filt = trial_metrics(filtered, fs, scheme, extra, remote)
        stem = f"{args.site}_{label}_{seg.t0:%Y%m%dT%H%M}"
        info = {**common, "label": label, "chain": filters, "provenance": notes + provenance}
        paths = write_trial(out_dir, stem, info, raw, filt, seg.arrays, filtered)
        written += paths
        logger.info(f"chain {label!r}: {time.time() - t:.1f} s")
        print()
        print(summary_block(args.site, label, len(filters), raw, filt))
        for line in notes + provenance:
            print(f"  provenance: {line}")
        del filtered, filt
    print()
    for p in written:
        logger.info(f"-> {p}")


if __name__ == "__main__":
    main()
