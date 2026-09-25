# -*- coding: utf-8 -*-
"""
Band masks of a coherent near-field source, found from the clusters of a site's chunk impedances

A coherent source near a site replaces the Earth's impedance over a range of
periods for part of the record. In the per-chunk remote-reference impedances
of the Cross-powers tab (`crust.crosspower`) such a band splits into two
clusters in the (log10 |Z|, phase) plane: the Earth's, at a physical phase,
and the source's, near zero phase. The script finds the two clusters band by
band and writes a band mask over every chunk of the source cluster, the mask
a selection on the tab's polar panel records, with found_by "cluster".

The pair's window store is computed over the overlap of the two stations, or
over [start, end), with `compute_windows` (4 threads) on the archives
processing reads (a site's filtered variant when it is built, else its raw
archive), and grouped into chunks of `--chunk-s` with `bin_windows`. For
every band, the display groups of the band's grid (`band_view`) that hold at
least half the band's median window count and a coherence of at least
`--min-coherence` in the component's row are placed at (log10 |Z|, phase),
Zyx drawn plus 180 deg so that the Earth of both modes lies in 0-90 deg. Each
axis is divided by its robust spread (1.4826 times its median absolute
deviation) and the groups are split by 2-means, started from the means of
the tenth of the groups with the lowest phase and the tenth with the
highest; a band with fewer than `MIN_GROUPS` (30) such groups is left
whole. The source cluster is the one whose median phase lies nearer
0 deg, the Earth cluster the other. The split is accepted when the Earth
cluster's median phase lies in 0-90 deg, the source cluster's lies within
`--max-source-phase` of 0 deg, the two median phases differ by at
least `--min-separation` and by more than twice the pooled median absolute
deviation of the phases (each about its own cluster's median), and the
Earth cluster holds at least `--min-earth-fraction` of the groups. An
accepted band gets one mask per run of consecutive masked groups, over the
run's span, with the band's [pmin, pmax]: the source cluster's groups, and
with `--dilate N` (default 2) the N groups either side of each of them too, since the
chunks around the source's own carry its field at an Earth-like phase.
`--component both` clusters xy and yx separately.

The console prints the per-band table and, for the stacked impedance
(`stack_impedance`) with no masks, with the cluster masks and with the
site's other masks, the usable range of each mode (`USABLE_RULE`). `--out`
writes the masks to a YAML file laid out as masks.yaml; `--write` saves them
into the survey's masks.yaml (`crust.masks.save_masks`), in place of the
site's earlier found_by "cluster" masks, keeping its other masks.
`--figures` writes, under `<workspace>/qc/cluster_masks/<local>_rr-<remote>/`,
one scatter per band, a summary figure (the fraction of groups masked, both
clusters' phases, and rho and phase of the three stacks with their jackknife
errors) and `cluster_masks.json` with the table and the usable ranges.

Usage:
    python scripts/cluster_masks.py <survey.yaml> <local> <remote> [start] [end]
                                    [--component yx|xy|both] [--chunk-s S]
                                    [--min-separation DEG] [--min-earth-fraction F]
                                    [--min-coherence C] [--max-source-phase DEG]
                                    [--dilate N]
                                    [--out FILE.yaml] [--write] [--figures]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "4")

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from loguru import logger
from matplotlib.patches import Polygon

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.bands import build_band_scheme  # noqa: E402
from crust.crosspower import (  # noqa: E402
    CHUNKS_S, band_view, bin_windows, compute_windows, masked_chunks, stack_impedance,
)
from crust.ingest import default_archive_path, variant_path, variant_ready  # noqa: E402
from crust.masks import HEADER, _Dumper, load_masks, normalise, save_masks  # noqa: E402
from crust.survey import Survey  # noqa: E402

WORKERS = 4
CHUNK_S = CHUNKS_S[0]  # the Cross-powers tab's default chunk
MIN_SEPARATION_DEG = 20.0
MIN_EARTH_FRACTION = 0.2
MIN_COHERENCE = 0.5
MAX_SOURCE_PHASE_DEG = 30.0
MAD_FACTOR = 2.0  # the median phases differ by more than this many pooled MADs
MIN_GROUPS = 30  # groups a band needs to be split
MIN_WINDOW_SHARE = 0.5  # of the band's median window count, for a group to be clustered
TAIL = 0.1  # the share of groups at each phase extreme that starts a cluster
MAX_ITER = 100
QUADRANT = (0.0, 90.0)  # the Earth's phases of both modes, yx plus 180 deg
COMPONENTS = ("xy", "yx")
FOUND_BY = "cluster"
# the usable band of a stacked impedance
MAX_PHASE_ERR_DEG = 10.0
PHYSICAL_DEG = (10.0, 80.0)
SPIKE_DEG = 10.0
SLOPE_TOL_DEG = 25.0
MAX_SLOPE = 0.5  # the near field of a source makes rho rise as the period (slope 1)
SLOPE_HALF = 2  # bands either side in the fit of log10 rho against log10 period
USABLE_RULE = (
    f"a band is usable when its jackknife phase error is at most {MAX_PHASE_ERR_DEG:g} deg, its phase (yx plus "
    f"180) lies in {PHYSICAL_DEG[0]:g}-{PHYSICAL_DEG[1]:g} deg and differs by at most {SPIKE_DEG:g} deg from the "
    f"median of itself and its two neighbours, and s, the slope of log10 rho against log10 period fitted over "
    f"the {2 * SLOPE_HALF + 1} bands centred on it, is at most {MAX_SLOPE:g} with the phase within "
    f"{SLOPE_TOL_DEG:g} deg of 45 (1 - s); the usable range is the longest run of consecutive usable bands")
EARTH_COLOUR, SOURCE_COLOUR, DROPPED_COLOUR = "#1f77b4", "#d62728", "0.75"
MODE_COLOUR = {"xy": "C0", "yx": "C3"}
DPI = 120


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("local")
    p.add_argument("remote")
    p.add_argument("start", nargs="?", default=None, help="UTC start (default: the overlap's)")
    p.add_argument("end", nargs="?", default=None, help="UTC end (default: the overlap's)")
    p.add_argument("--component", choices=("yx", "xy", "both"), default="yx")
    p.add_argument("--chunk-s", type=float, default=60.0, help="base chunk, s (default 60)")
    p.add_argument("--min-separation", type=float, default=MIN_SEPARATION_DEG, metavar="DEG")
    p.add_argument("--min-earth-fraction", type=float, default=MIN_EARTH_FRACTION, metavar="F")
    p.add_argument("--min-coherence", type=float, default=MIN_COHERENCE, metavar="C")
    p.add_argument("--max-source-phase", type=float, default=MAX_SOURCE_PHASE_DEG, metavar="DEG")
    p.add_argument("--dilate", type=int, default=2, metavar="N",
                   help="also mask the N groups either side of every source-cluster group (default 0)")
    p.add_argument("--out", default=None, metavar="FILE.yaml", help="write the masks to this file")
    p.add_argument("--write", action="store_true", help="save the masks into the survey's masks.yaml")
    p.add_argument("--figures", action="store_true", help="write the scatters, the summary figure and the JSON")
    return p.parse_args(argv)


# ------------------------------------------------------------------ clustering


def mode_phase(z, component: str) -> np.ndarray:
    """Return the phase of Zxy, or of Zyx plus 180 deg, in degrees in (-180, 180]."""
    z = np.asarray(z)
    return np.degrees(np.angle(-z if component == "yx" else z))


def kept_groups(z, coherence, n_windows, min_coherence: float = MIN_COHERENCE) -> np.ndarray:
    """Return the groups of a band that take part in the clustering.

    Args:
        z: Complex Z of one component per group (NaN where a group has no estimate).
        coherence: The coherence of the component's row per group.
        n_windows: Windows kept per group.
        min_coherence (float): The lowest coherence taken.

    Returns:
        np.ndarray: True for a group with a finite Z, at least `MIN_WINDOW_SHARE`
        of the median window count of the groups with an estimate, and a
        coherence of at least `min_coherence`.
    """
    z, coherence, n_windows = np.asarray(z), np.asarray(coherence, float), np.asarray(n_windows, float)
    has = np.isfinite(z) & (n_windows > 0)
    if not has.any():
        return has
    floor = MIN_WINDOW_SHARE * np.median(n_windows[has])
    with np.errstate(invalid="ignore"):
        return has & (n_windows >= floor) & (coherence >= min_coherence)


def two_means(log_z, phase) -> np.ndarray:
    """Split points of the (log10 |Z|, phase) plane into two clusters by 2-means.

    Each axis is divided by 1.4826 times its median absolute deviation. The
    clusters start at the means of the `TAIL` share of points with the
    lowest phase and of those with the highest.

    Args:
        log_z: log10 |Z| per point.
        phase: Phase per point, deg.

    Returns:
        np.ndarray: 0 or 1 per point, 0 for the cluster started at low phase.
    """
    x = np.column_stack([np.asarray(log_z, float), np.asarray(phase, float)])
    centre = np.median(x, axis=0)
    spread = 1.4826 * np.median(np.abs(x - centre), axis=0)
    u = (x - centre) / np.where(spread > 0, spread, 1.0)
    order = np.argsort(x[:, 1], kind="stable")
    k = max(1, int(round(TAIL * len(order))))
    means = np.array([u[order[:k]].mean(axis=0), u[order[-k:]].mean(axis=0)])
    labels = np.full(len(u), -1)
    for _ in range(MAX_ITER):
        new = np.argmin(((u[:, None, :] - means[None]) ** 2).sum(axis=-1), axis=1)
        if (new == labels).all():
            break
        labels = new
        for i in (0, 1):
            if (labels == i).any():
                means[i] = u[labels == i].mean(axis=0)
    return labels


def earth_index(medians) -> int:
    """Return which of two clusters is the Earth's: the one whose median phase lies farther from 0 deg."""
    return int(np.argmax(np.abs(np.asarray(medians, float))))


def split_band(log_z, phase, min_separation: float = MIN_SEPARATION_DEG,
               min_earth_fraction: float = MIN_EARTH_FRACTION,
               max_source_phase: float = MAX_SOURCE_PHASE_DEG) -> dict:
    """Split one band's groups into an Earth and a source cluster, and judge the split.

    Args:
        log_z: log10 |Z| per group.
        phase: Phase per group, deg, the Earth's in 0-90 (`mode_phase`).
        min_separation (float): The least difference of the two median phases, deg.
        min_earth_fraction (float): The least share of the groups in the Earth cluster.
        max_source_phase (float): The farthest the source cluster's median phase may lie from 0 deg.

    Returns:
        dict: ``accepted`` (bool), ``verdict`` (text), ``n`` (groups), and
        after a split ``source`` (bool per group), ``earth_phase``,
        ``source_phase``, ``earth_log_z``, ``source_log_z`` (medians),
        ``separation``, ``mad`` (the pooled median absolute deviation of the
        phases), ``earth_fraction`` and ``n_source``.
    """
    log_z, phase = np.asarray(log_z, float), np.asarray(phase, float)
    n = int(phase.size)
    out = {"accepted": False, "n": n}
    if n < MIN_GROUPS:
        out["verdict"] = f"{n} groups clustered, {MIN_GROUPS} needed"
        return out
    labels = two_means(log_z, phase)
    if (labels == labels[0]).all():
        out["verdict"] = "one cluster"
        return out
    med = np.array([np.median(phase[labels == i]) for i in (0, 1)])
    earth = earth_index(med)
    source = labels != earth
    separation = float(abs(med[earth] - med[1 - earth]))
    mad = float(np.median(np.abs(phase - med[labels])))
    fraction = float(np.mean(~source))
    out.update(source=source, earth_phase=float(med[earth]), source_phase=float(med[1 - earth]),
               earth_log_z=float(np.median(log_z[~source])), source_log_z=float(np.median(log_z[source])),
               separation=separation, mad=mad, earth_fraction=fraction, n_source=int(source.sum()))
    fails = []
    if not QUADRANT[0] <= med[earth] <= QUADRANT[1]:
        fails.append(f"no cluster at a physical phase (the one farther from 0 deg is at {med[earth]:.1f})")
    if abs(med[1 - earth]) > max_source_phase:
        fails.append(f"source cluster phase {med[1 - earth]:.1f} deg, farther than {max_source_phase:g} from 0")
    if separation < min_separation:
        fails.append(f"separation {separation:.1f} deg < {min_separation:g}")
    if separation <= MAD_FACTOR * mad:
        fails.append(f"separation {separation:.1f} deg <= {MAD_FACTOR:g} x MAD {mad:.1f}")
    if fraction < min_earth_fraction:
        fails.append(f"Earth fraction {fraction:.2f} < {min_earth_fraction:g}")
    out["accepted"] = not fails
    out["verdict"] = "; ".join(fails) if fails else "two clusters"
    return out


def cluster_band(z, coherence, n_windows, component: str, min_separation: float = MIN_SEPARATION_DEG,
                 min_earth_fraction: float = MIN_EARTH_FRACTION, min_coherence: float = MIN_COHERENCE,
                 max_source_phase: float = MAX_SOURCE_PHASE_DEG) -> dict:
    """Cluster one component of one band and mark the groups of an accepted source cluster.

    Args:
        z: Complex Z of the component per group.
        coherence: The coherence of the component's row per group.
        n_windows: Windows kept per group.
        component (str): "xy" or "yx".
        min_separation (float): See `split_band`.
        min_earth_fraction (float): See `split_band`.
        min_coherence (float): See `kept_groups`.
        max_source_phase (float): See `split_band`.

    Returns:
        dict: `split_band`'s result with ``kept`` (bool per group of the
        band), ``masked`` (bool per group: in the source cluster of an
        accepted split), ``earth_coherence`` and ``source_coherence``
        (medians), ``earth_z`` and ``source_z`` (median |Z|).
    """
    z = np.asarray(z)
    kept = kept_groups(z, coherence, n_windows, min_coherence)
    idx = np.flatnonzero(kept)
    with np.errstate(divide="ignore"):
        out = split_band(np.log10(np.abs(z[idx])), mode_phase(z[idx], component), min_separation,
                         min_earth_fraction, max_source_phase)
    out["kept"] = kept
    masked = np.zeros(z.size, dtype=bool)
    if "source" in out:
        coh = np.asarray(coherence, float)[idx]
        src = out["source"]
        out.update(earth_coherence=float(np.median(coh[~src])), source_coherence=float(np.median(coh[src])),
                   earth_z=float(10 ** out["earth_log_z"]), source_z=float(10 ** out["source_log_z"]))
        if out["accepted"]:
            masked[idx[src]] = True
    out["masked"] = masked
    return out


def runs(flags) -> list[tuple[int, int]]:
    """Return the [first, last] index pairs of the runs of consecutive True entries."""
    flags = np.asarray(flags, dtype=bool)
    edges = np.flatnonzero(np.diff(np.r_[0, flags.astype(int), 0]))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2])]


def dilate(flags, n: int) -> np.ndarray:
    """Return `flags` with the n entries either side of every True entry set too."""
    out = np.asarray(flags, dtype=bool).copy()
    idx = np.flatnonzero(out)
    for k in range(1, max(0, int(n)) + 1):
        out[idx[idx >= k] - k] = True
        out[idx[idx < out.size - k] + k] = True
    return out


def mask_records(starts, ends, masked, pmin: float, pmax: float, component: str, split: dict,
                 dilated: int = 0) -> list[dict]:
    """Return the masks of one band: one per run of consecutive masked groups, over the run's span.

    Args:
        starts: Group starts (UTC).
        ends: Group ends (UTC).
        masked: True per masked group.
        pmin (float): The band's shortest period, s.
        pmax (float): The band's longest period, s.
        component (str): The component clustered.
        split (dict): `cluster_band`'s result, for the reason text.
        dilated (int): The groups either side of the source's that `masked` holds, for the reason text.

    Returns:
        list of dict: Normalised masks with found_by "cluster".
    """
    if not np.any(masked):
        return []
    grown = f", dilated by {dilated} group(s)" if dilated > 0 else ""
    reason = (f"cluster mask: {component} source cluster phase {split['source_phase']:.1f} deg "
              f"|Z| {split['source_z']:.3g}, Earth cluster phase {split['earth_phase']:.1f} deg, separation "
              f"{split['separation']:.1f} deg, {split['n_source']}/{split['n']} chunks{grown} (cluster_masks.py)")
    return [normalise({"start": starts[a], "end": ends[b], "bands": [pmin, pmax], "reason": reason,
                       "found_by": FOUND_BY}) for a, b in runs(masked)]


def replace_cluster_masks(existing, new, origin: str = FOUND_BY) -> list[dict]:
    """Return a site's masks with those of `origin` (found_by "cluster") replaced by `new`, the others kept first."""
    kept = [m for m in (normalise(m) for m in existing or []) if m["found_by"] != origin]
    return kept + [normalise(m) for m in new]


def write_site_masks(survey_yaml, site: str, new, origin: str = FOUND_BY) -> tuple[int, int, int]:
    """Save a site's masks of one origin into masks.yaml in place of its earlier ones of that origin.

    Args:
        survey_yaml: The survey.yaml path or the survey folder.
        site (str): The site.
        new: The new masks, all of `origin`.
        origin (str): Their found_by.

    Returns:
        tuple: (masks of other origins kept, earlier masks of `origin` removed, masks written).
    """
    existing = load_masks(survey_yaml, site)
    merged = replace_cluster_masks(existing, new, origin)
    n_kept = sum(m["found_by"] != origin for m in existing)
    save_masks(survey_yaml, site, merged)
    return n_kept, len(existing) - n_kept, len(merged) - n_kept


def write_mask_file(path, site: str, masks) -> Path:
    """Write masks to a YAML file laid out as masks.yaml, one site's block."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.dump({site: [normalise(m) for m in masks]}, Dumper=_Dumper, sort_keys=False,
                     allow_unicode=True, default_flow_style=False, width=100)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def jaccard(a, b) -> float:
    """Return |a & b| / |a | b| of two boolean arrays, NaN when both are empty."""
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    union = int((a | b).sum())
    return float((a & b).sum() / union) if union else float("nan")


# ------------------------------------------------------------------ usable band


def rho_phase(periods, z, z_err) -> tuple[np.ndarray, ...]:
    """Return rho (ohm m), phase (deg, yx plus 180 when `z` is Zyx given negated) and their errors."""
    az = np.abs(z)
    rho = 0.2 * np.asarray(periods) * az**2
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.asarray(z_err) / az
    return rho, np.degrees(np.angle(z)), 2.0 * rho * rel, np.degrees(rel)


def usable_bands(periods, rho, phase, phase_err) -> np.ndarray:
    """Return, per band (periods ascending), whether the stack's phase is physical and smooth (`USABLE_RULE`)."""
    periods, rho, phase, phase_err = (np.asarray(a, float) for a in (periods, rho, phase, phase_err))
    n = periods.size
    ok = np.isfinite(phase) & np.isfinite(phase_err) & (phase_err <= MAX_PHASE_ERR_DEG)
    ok &= (phase >= PHYSICAL_DEG[0]) & (phase <= PHYSICAL_DEG[1])
    good = np.zeros(n, dtype=bool)
    lr, lp = np.log10(np.where(rho > 0, rho, np.nan)), np.log10(periods)
    for j in np.flatnonzero(ok):
        near = phase[max(0, j - 1): j + 2]
        near = near[np.isfinite(near)]
        if abs(phase[j] - np.median(near)) > SPIKE_DEG:
            continue
        sl = slice(max(0, j - SLOPE_HALF), j + SLOPE_HALF + 1)
        fit = np.isfinite(lr[sl])
        if fit.sum() < 3:
            continue
        slope = np.polyfit(lp[sl][fit], lr[sl][fit], 1)[0]
        good[j] = slope <= MAX_SLOPE and abs(phase[j] - 45.0 * (1.0 - slope)) <= SLOPE_TOL_DEG
    return good


def longest_run(good) -> tuple[int, int] | None:
    """Return the [first, last] indices of the longest run of True, the shorter-period one on a tie."""
    found = runs(good)
    return max(found, key=lambda r: (r[1] - r[0], -r[0])) if found else None


# ------------------------------------------------------------------ the pair


def processing_source(survey: Survey, site: str) -> tuple[Path, str]:
    """Return the archive processing reads for a site (its built variant, else the raw archive) and a note."""
    raw = default_archive_path(survey, site)
    if site in survey.site_names() and survey.site(site).filters:
        if variant_ready(survey, site):
            return variant_path(survey, site), "filtered variant"
        return raw, "raw archive (filtered variant not built)"
    return raw, "raw archive"


def cluster_pair(result: dict, components, min_separation: float, min_earth_fraction: float,
                 min_coherence: float, other_masks=(), dilate_groups: int = 0,
                 max_source_phase: float = MAX_SOURCE_PHASE_DEG) -> tuple[list[dict], list[dict]]:
    """Cluster every band of a `bin_windows` result and build the masks.

    Args:
        result (dict): From `bin_windows`.
        components: The components to cluster.
        min_separation (float): See `split_band`.
        min_earth_fraction (float): See `split_band`.
        min_coherence (float): See `kept_groups`.
        other_masks: The site's other masks, for the Jaccard overlap column.
        dilate_groups (int): Groups masked either side of every source-cluster group.
        max_source_phase (float): See `split_band`.

    Returns:
        tuple: (one row dict per band and component, the masks).
    """
    rows, masks = [], []
    lo, hi = result["band_lo_hz"], result["band_hi_hz"]
    for j, period in enumerate(result["periods"]):
        v = band_view(result, j)
        n_groups = len(v["starts"])
        other = masked_chunks(result, other_masks, j) > 0 if other_masks and n_groups else np.zeros(n_groups, bool)
        for comp in components:
            row = {"band": j, "period": float(period), "pmin": float(1.0 / hi[j]), "pmax": float(1.0 / lo[j]),
                   "level": v["level"], "multiple": v["multiple"], "component": comp, "groups": n_groups}
            if n_groups == 0:
                rows.append({**row, "clustered": 0, "accepted": False, "verdict": "no group at this level",
                             "masked": 0, "masks": 0})
                continue
            res = cluster_band(v["z" + comp], v["coh_" + comp], v["n_windows"], comp, min_separation,
                               min_earth_fraction, min_coherence, max_source_phase)
            res["source_groups"] = res["masked"]
            res["masked"] = dilate(res["masked"], dilate_groups)
            band_masks = mask_records(v["starts"], v["ends"], res["masked"], row["pmin"], row["pmax"], comp, res,
                                      dilate_groups)
            masks += band_masks
            row.update(clustered=res["n"], accepted=res["accepted"], verdict=res["verdict"],
                       masked=int(res["masked"].sum()), masks=len(band_masks),
                       jaccard_other=jaccard(res["masked"], other) if len(other_masks) else float("nan"),
                       _split=res, _view=v)
            for key in ("earth_phase", "source_phase", "separation", "mad", "earth_fraction", "earth_z",
                        "source_z", "earth_coherence", "source_coherence", "n_source"):
                if key in res:
                    row[key] = res[key]
            rows.append(row)
    return rows, masks


def fmt(value, spec: str = ".1f", width: int = 6) -> str:
    """Format a number for the table, '-' when missing."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "-".rjust(width)
    return format(value, spec).rjust(width)


def print_table(rows, other: bool) -> None:
    """Print the per-band table."""
    head = (f"{'period s':>9} {'L':>1} {'m':>3} {'cmp':>3} {'grp':>5} {'clus':>5} {'Earth':>6} {'source':>6} "
            f"{'sep':>5} {'MAD':>5} {'fEarth':>6} {'|Z|E':>6} {'|Z|S':>6} {'cohE':>5} {'cohS':>5} {'masked':>6} "
            f"{'masks':>5}" + (f" {'J other':>7}" if other else "") + "  verdict")
    print(head)
    for r in rows:
        share = r["masked"] / r["groups"] if r["groups"] else float("nan")
        line = (f"{r['period']:9.4g} {r['level']:1d} {r['multiple']:3d} {r['component']:>3} {r['groups']:5d} "
                f"{r['clustered']:5d} {fmt(r.get('earth_phase'))} {fmt(r.get('source_phase'))} "
                f"{fmt(r.get('separation'), '.1f', 5)} {fmt(r.get('mad'), '.1f', 5)} "
                f"{fmt(r.get('earth_fraction'), '.2f')} {fmt(r.get('earth_z'), '.3g')} {fmt(r.get('source_z'), '.3g')} "
                f"{fmt(r.get('earth_coherence'), '.2f', 5)} {fmt(r.get('source_coherence'), '.2f', 5)} "
                f"{fmt(share, '.2f')} {r['masks']:5d}"
                + (f" {fmt(r.get('jaccard_other'), '.2f', 7)}" if other else "")
                + f"  {'MASKED' if r['accepted'] else 'none'}: {r['verdict']}")
        print(line)


def stacks_and_usable(result: dict, sets: dict) -> dict:
    """Stack the impedance for each named mask set and find each mode's usable range.

    Returns:
        dict: {name: {"stack": stack_impedance's result, "curves": {mode: (rho, phase, rho_err, phase_err)},
        "usable": {mode: [pmin, pmax] or None}, "good": {mode: bool per band}}}.
    """
    out = {}
    periods = result["periods"]
    for name, masks in sets.items():
        st = stack_impedance(result, masks)
        entry = {"stack": st, "curves": {}, "usable": {}, "good": {}}
        for mode in COMPONENTS:
            z = st["z" + mode]
            curves = rho_phase(periods, -z if mode == "yx" else z, st["z" + mode + "_err"])
            good = usable_bands(periods, curves[0], curves[1], curves[3])
            span = longest_run(good)
            entry["curves"][mode] = curves
            entry["good"][mode] = good
            entry["usable"][mode] = None if span is None else [float(periods[span[0]]), float(periods[span[1]])]
        out[name] = entry
    return out


def span_text(span) -> str:
    """Return a usable range as text."""
    return "none" if span is None else f"{span[0]:.3g}-{span[1]:.3g} s"


# ------------------------------------------------------------------ figures


def hull(points: np.ndarray) -> np.ndarray | None:
    """Return the convex hull of 2-D points (monotone chain), None for fewer than 3 distinct points."""
    pts = np.unique(points[np.isfinite(points).all(axis=1)], axis=0)
    if len(pts) < 3:
        return None
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def turn(o, a, b):  # z of (a - o) x (b - o): > 0 for a left turn
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(seq):
        chain = []
        for p in seq:
            while len(chain) >= 2 and turn(chain[-2], chain[-1], p) <= 0:
                chain.pop()
            chain.append(p)
        return chain

    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def band_figure(rows, path: Path, title: str) -> None:
    """Draw one band's groups in the (log10 |Z|, phase) plane, one panel per component."""
    fig, axes = plt.subplots(1, len(rows), figsize=(5.2 * len(rows), 4.4), squeeze=False, layout="constrained")
    for ax, r in zip(axes[0], rows):
        v, res = r["_view"], r["_split"]
        z = v["z" + r["component"]]
        with np.errstate(divide="ignore", invalid="ignore"):
            lz, ph = np.log10(np.abs(z)), mode_phase(z, r["component"])
        kept = res["kept"]
        has = np.isfinite(lz) & np.isfinite(ph)
        ax.plot(lz[has & ~kept], ph[has & ~kept], ".", ms=3, color=DROPPED_COLOUR, label="not clustered")
        if "source" in res:
            idx = np.flatnonzero(kept)
            src = np.zeros(z.size, bool)
            src[idx[res["source"]]] = True
            earth = kept & ~src
            grown = earth & res["masked"]  # Earth-cluster groups masked beside the source's (--dilate)
            earth &= ~grown
            ce, cs = (EARTH_COLOUR, SOURCE_COLOUR) if res["accepted"] else ("0.45", "0.6")
            ax.plot(lz[earth], ph[earth], "o", ms=3.5, color=ce, label=f"Earth cluster ({earth.sum()})")
            if grown.any():
                ax.plot(lz[grown], ph[grown], "o", ms=3.5, mfc="none", color=ce,
                        label=f"Earth cluster, masked beside the source ({grown.sum()})")
            ax.plot(lz[src], ph[src], "o", ms=3.5, mfc="none", color=cs, label=f"source cluster ({src.sum()})")
            poly = hull(np.column_stack([lz[src], ph[src]]))
            if poly is not None:
                ax.add_patch(Polygon(poly, closed=True, fill=False, hatch="///", edgecolor=cs, lw=0.8, alpha=0.6))
            ax.axhline(res["earth_phase"], color=ce, lw=0.8, ls="--")
            ax.axhline(res["source_phase"], color=cs, lw=0.8, ls="--")
        else:
            ax.plot(lz[kept], ph[kept], "o", ms=3.5, color="0.45", label=f"clustered ({kept.sum()})")
        ax.set_ylim(-180, 180)
        ax.set_yticks(np.arange(-180, 181, 45))
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("log10 |Z| ((mV/km)/nT)")
        ax.set_ylabel("phase (deg" + ("; yx + 180)" if r["component"] == "yx" else ")"))
        verdict = "masked" if r["accepted"] else "no masks"
        ax.set_title(f"{r['component']}: {verdict}\n{r['verdict']}", fontsize=9)
        ax.legend(fontsize=7, loc="lower left")
    fig.suptitle(title, fontsize=10)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def summary_figure(result: dict, rows, stacks: dict, path: Path, title: str) -> None:
    """Draw the fraction masked and the clusters' phases per band, and rho and phase of the stacks."""
    periods = result["periods"]
    fig, (ax_r, ax_p, ax_c, ax_f) = plt.subplots(4, 1, figsize=(9, 13), sharex=True,
                                                 height_ratios=[2.2, 1.6, 1.2, 0.8], layout="constrained")
    styles = {"none": dict(color="0.55", lw=0.8, ms=3, alpha=0.9),
              "other": dict(color="0.3", lw=0.8, ms=3, ls="--", alpha=0.9),
              "cluster": dict(lw=1.6, ms=4.5)}
    labels = {"none": "no masks", "other": "the site's other masks", "cluster": "cluster masks"}
    for name in ("none", "other", "cluster"):
        if name not in stacks:
            continue
        for mode, marker in (("xy", "o"), ("yx", "s")):
            rho, ph, rho_err, ph_err = stacks[name]["curves"][mode]
            kw = dict(styles[name])
            if name == "cluster":
                kw["color"] = MODE_COLOUR[mode]
            label = f"{mode} {labels[name]} (usable {span_text(stacks[name]['usable'][mode])})"
            kw.setdefault("ls", "-")
            ax_r.errorbar(periods, rho, yerr=np.nan_to_num(rho_err), fmt=marker, elinewidth=0.6, capsize=1.5,
                          label=label, **kw)
            ax_p.errorbar(periods, ph, yerr=np.nan_to_num(ph_err), fmt=marker, elinewidth=0.6, capsize=1.5, **kw)
    ax_r.set_xscale("log")
    ax_r.set_yscale("log")
    ax_r.set_ylabel(r"$\rho_a$ ($\Omega$m)")
    ax_r.legend(fontsize=7, ncol=2)
    ax_p.set_ylabel("phase (deg; yx + 180)")
    ax_p.set_ylim(-20, 100)
    ax_p.axhspan(*PHYSICAL_DEG, color="0.9", zorder=0)
    for comp in sorted({r["component"] for r in rows}):
        sub = [r for r in rows if r["component"] == comp and "earth_phase" in r]
        p = np.array([r["period"] for r in sub])
        acc = np.array([r["accepted"] for r in sub], bool)
        e = np.array([r["earth_phase"] for r in sub])
        s = np.array([r["source_phase"] for r in sub])
        colour = MODE_COLOUR[comp]
        ax_c.plot(p[acc], e[acc], "o", color=colour, ms=5, label=f"{comp} Earth cluster (masked band)")
        ax_c.plot(p[acc], s[acc], "x", color=colour, ms=6, label=f"{comp} source cluster (masked band)")
        ax_c.plot(p[~acc], e[~acc], "o", mfc="none", color=colour, ms=4, alpha=0.5, label=f"{comp} split rejected")
        ax_c.plot(p[~acc], s[~acc], "+", color=colour, ms=5, alpha=0.5)
        allp = np.array([r["period"] for r in rows if r["component"] == comp])
        share = np.array([r["masked"] / r["groups"] if r["groups"] else np.nan for r in rows
                          if r["component"] == comp])
        ax_f.plot(allp, share, "o-", color=colour, ms=3.5, lw=1.0, label=comp)
    ax_c.set_ylim(-60, 120)
    ax_c.axhspan(*QUADRANT, color="0.93", zorder=0)
    ax_c.set_ylabel("cluster median phase (deg)")
    ax_c.legend(fontsize=7, ncol=2)
    ax_f.set_ylabel("share of groups masked")
    ax_f.set_ylim(-0.02, 1.02)
    ax_f.set_xlabel("period (s)")
    ax_f.legend(fontsize=7)
    for ax in (ax_r, ax_p, ax_c, ax_f):
        ax.grid(True, which="both", alpha=0.3)
    ax_r.set_title(title, fontsize=10)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def json_ready(value):
    """Return `value` with numpy scalars and arrays as plain Python values."""
    if isinstance(value, dict):
        return {k: json_ready(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    """Compute the pair's store, cluster every band, report and write what the flags ask for.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0.
    """
    args = parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level="INFO", filter=lambda rec: not rec["name"].startswith("mth5"))
    try:
        import psutil
        logger.info(f"memory available {psutil.virtual_memory().available / 1e9:.1f} GB")
    except ImportError:
        pass
    survey = Survey.from_yaml(args.survey_yaml)
    scheme = build_band_scheme(survey.sample_rate, **survey.processing)
    (local_h5, local_note), (remote_h5, remote_note) = (processing_source(survey, args.local),
                                                        processing_source(survey, args.remote))
    logger.info(f"{args.local}: {local_h5.name} ({local_note}); {args.remote}: {remote_h5.name} ({remote_note})")
    t0 = time.time()
    store = compute_windows(local_h5, args.local, remote_h5, args.remote, args.start, args.end, scheme,
                            workers=WORKERS)
    result = bin_windows(store, args.chunk_s)
    logger.info(f"store over {result['start']} to {result['end']} in {time.time() - t0:.0f} s, "
                f"{len(result['base_starts'])} chunks of {args.chunk_s:g} s")
    components = COMPONENTS if args.component == "both" else (args.component,)
    other_masks = [m for m in load_masks(survey, args.local) if m["found_by"] != FOUND_BY]
    rows, masks = cluster_pair(result, components, args.min_separation, args.min_earth_fraction,
                               args.min_coherence, other_masks, args.dilate, args.max_source_phase)
    title = (f"{args.local} rr {args.remote}, {result['start']:%Y-%m-%d %H:%M} to {result['end']:%Y-%m-%d %H:%M} "
             f"UTC, {args.chunk_s:g} s chunks, {'+'.join(components)}"
             + (f", dilated by {args.dilate}" if args.dilate else ""))
    print()
    print(title)
    print(f"rule: 2-means in (log10 |Z|, phase), groups with coherence >= {args.min_coherence:g}; accepted when the "
          f"Earth median phase is in {QUADRANT[0]:g}-{QUADRANT[1]:g} deg, the source's within "
          f"{args.max_source_phase:g} deg of 0, the separation >= {args.min_separation:g} "
          f"deg and > {MAD_FACTOR:g} pooled MADs, the Earth share >= {args.min_earth_fraction:g}; the source "
          f"cluster's groups masked" + (f" with {args.dilate} group(s) either side" if args.dilate else ""))
    print_table(rows, bool(other_masks))
    n_bands = len({(r["band"]) for r in rows if r["masks"]})
    print(f"\n{len(masks)} cluster mask(s) over {n_bands} band(s)")

    sets = {"none": [], "cluster": masks}
    if other_masks:
        sets["other"] = other_masks
    stacks = stacks_and_usable(result, sets)
    print(f"\nusable range of the stacked impedance: {USABLE_RULE}")
    for name in sets:
        print(f"  {name:8s} ({len(sets[name])} masks): yx {span_text(stacks[name]['usable']['yx'])}, "
              f"xy {span_text(stacks[name]['usable']['xy'])}")
    print(f"\n  {'period s':>9} " + " ".join(f"{n + ' rho':>12} {n + ' phi':>11}" for n in sets))
    for j, period in enumerate(result["periods"]):
        cells = []
        for name in sets:
            rho, ph, _rho_err, ph_err = stacks[name]["curves"]["yx"]
            mark = "*" if stacks[name]["good"]["yx"][j] else " "
            cells.append(f"{rho[j]:12.4g} {ph[j]:6.1f}+{ph_err[j]:4.1f}{mark}")
        print(f"  {period:9.4g} " + " ".join(cells))
    print("  (yx; * a usable band)")

    if args.out:
        path = write_mask_file(args.out, args.local, masks)
        logger.info(f"{len(masks)} mask(s) written to {path}")
    if args.write:
        kept, removed, written = write_site_masks(args.survey_yaml, args.local, masks)
        logger.info(f"{args.local}: masks.yaml keeps {kept} other mask(s), {removed} earlier cluster mask(s) "
                    f"replaced by {written}")
    if args.figures:
        out_dir = survey.workspace / "qc" / "cluster_masks" / f"{args.local}_rr-{args.remote}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for j in sorted({r["band"] for r in rows if r["groups"]}):
            band_rows = [r for r in rows if r["band"] == j and "_split" in r]
            if band_rows:
                r0 = band_rows[0]
                band_figure(band_rows, out_dir / f"band_{j:02d}_{r0['period']:.4g}s.png",
                            f"{args.local} rr {args.remote}  band {r0['period']:.4g} s ({r0['pmin']:.4g}-"
                            f"{r0['pmax']:.4g} s), level {r0['level']}, {r0['groups']} groups of "
                            f"{r0['multiple'] * args.chunk_s:g} s")
        summary_figure(result, rows, stacks, out_dir / "summary.png", title)
        info = {"local": args.local, "remote": args.remote, "start": str(result["start"]), "end": str(result["end"]),
                "archives": {args.local: [local_h5.name, local_note], args.remote: [remote_h5.name, remote_note]},
                "chunk_s": args.chunk_s, "components": list(components),
                "min_separation": args.min_separation, "min_earth_fraction": args.min_earth_fraction,
                "min_coherence": args.min_coherence, "max_source_phase": args.max_source_phase,
                "dilate": args.dilate, "n_masks": len(masks),
                "usable_rule": USABLE_RULE,
                "usable": {name: stacks[name]["usable"] for name in sets},
                "n_masks_by_set": {name: len(m) for name, m in sets.items()}, "rows": rows}
        (out_dir / "cluster_masks.json").write_text(json.dumps(json_ready(info), indent=1), encoding="utf-8")
        logger.info(f"figures and cluster_masks.json -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
