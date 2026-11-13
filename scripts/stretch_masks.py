# -*- coding: utf-8 -*-
"""
Sub-week stretch selection of a site's electric lines, written as candidate masks

The health table (scripts/health_table.py, `mt_workbench.health`) judges each
electric line per week; this script finds every usable stretch inside a
week. It takes the same hourly E-H coherence the health module
computes (`mt_workbench.health.hourly_pair_coherence`: one-hour windows at a
30-min step, the band 20-200 s, H turned by the whole record's mean-field
angle, Ex paired with Hy' and Ey with Hx', the swapped rule and, at a rot_e
site, the lines as recorded, exactly as `health_record` pairs them), keeps
the windows whose coherence exceeds `--threshold` (0.5, the health module's
`E_COH`), merges them into runs and writes masks.yaml entries on the
complement, the stretches left out:

- channels [ex] for the xy mode, [ey] for yx (that TF row alone; H and the
  other row keep every window);
- bands [band_min, band_max] (0 to `--band-max`, 1,000 s by default), so the
  levels above keep the whole record (masks starve the
  long levels);
- scope local, found_by "stretch", the reason naming the threshold, the
  grain and the hours kept.

The grain: `--grain 3600` keeps the one-hour windows that start on the
record's hourly grid (window k starts k hours after sample 0) and pass;
`--grain 1800` keeps the union of every passing one-hour window on the
30-min grid (the health series itself), so a run edge resolves to 30 min
instead of one hour (a run is still at least one hour long). A selection is
held as a boolean per grain slot ([k g, (k+1) g) seconds from sample 0):
at 3600 slot k is kept when its window passes; at 1800 when either of the
two windows covering it passes. `data` marks the slots some finite window
covers.

Controls (selecting hours by the coherence of the data that make
the estimate can manufacture a response from noise), `--control`:

- ``random:SEED``: the selection's pattern of kept slots turned circularly
  by a random offset over the data slots (the gaps skipped), so the same
  number of slots, the same runs (cut only at gaps) and the same band
  limit, placed where the coherence did not choose them;
- ``half:A`` / ``half:B``: the selection's runs taken alternately, A the
  first, third, ... and B the second, fourth, ...; disjoint, their union
  the selection.

The masks go to a candidate file (`--out`, default
<workspace>/qc/stretch_masks/<site>_stretch_g<grain>_t<threshold>[_<control>].yaml),
laid out as masks.yaml, for `scripts/process_rr.py --masks-file`; the
survey's masks.yaml is refused as an output. `--series FILE.csv` also writes
the hourly series (window start and centre UTC, xy and yx coherence, finite)
for figures. The survey folder is left unchanged.

The record is [min(survey start, archive t0), max(survey end, archive end)];
a mode with no window kept gets one mask over the whole record (its short
and middle bands blanked; its long levels kept).

Usage:
    python scripts/stretch_masks.py <survey.yaml> <site> [--modes xy,yx] [--grain 3600|1800]
        [--threshold 0.5] [--band-max 1000] [--band-min 0] [--control random:SEED|half:A|half:B]
        [--out FILE] [--series FILE.csv]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from mt_workbench import health as HL  # noqa: E402
from mt_workbench.masks import masks_path, normalise, utc  # noqa: E402

MODES = {"xy": "ex", "yx": "ey"}       # mode: the TF row (electric channel) its masks name
GRAINS = (3600, 1800)
THRESHOLD = HL.E_COH                    # 0.5
BAND_MAX = 1000.0
ORIGIN = "stretch"


def passes(values, threshold: float) -> np.ndarray:
    """The keep rule: a window passes when its coherence is finite and above `threshold`."""
    v = np.asarray(values, float)
    return np.isfinite(v) & (v > threshold)


def line_series(hx, hy, ex, ey, fs: float = 1.0, e_dirs=None) -> dict:
    """Return the hourly E-H coherence of each line, paired as `mt_workbench.health.health_record` pairs it.

    Args:
        hx, hy (array): H as laid (mean field kept: the turn uses it).
        ex, ey (array): E (the lines as recorded at a rot_e site, with `e_dirs`).
        fs (float): Sample rate (1 Hz after `to_1hz`).
        e_dirs (tuple, optional): The directions the lines measure along (`health_record`).

    Returns:
        dict: ``start_s`` and ``centre_s`` (window start and centre, s from sample 0), ``xy`` (Ex with its
        partner) and ``yx`` (Ey with its partner) per window, ``finite`` (every pair of the health
        module finite, its window count), ``swapped`` (the record's swapped verdict), ``angle``.
    """
    hx = np.asarray(hx, float)
    hy = np.asarray(hy, float)
    n = min(len(hx), len(hy), len(ex), len(ey))
    ang = HL.mean_field_angle(hx, hy)
    rx, ry = HL.rotate_h(hx, hy, ang)
    loc = {"Hx": rx, "Hy": ry, "Ex": np.asarray(ex, float), "Ey": np.asarray(ey, float)}
    h_for = {"Ex": (rx, ry), "Ey": (rx, ry)}
    if e_dirs is not None:
        for comp, b, nominal in (("Ex", e_dirs[0], 0.0), ("Ey", e_dirs[1], 90.0)):
            off = ((float(b) - nominal) + 180.0) % 360.0 - 180.0
            if off != 0.0:
                h_for[comp] = HL.rotate_h(hx, hy, ang + off)
    fr, tc = {}, None
    for a, b in (("Hx", "Ey"), ("Hy", "Ex"), ("Hx", "Ex"), ("Hy", "Ey"), ("Ex", "Ey"), ("Hx", "Hy")):
        ha = h_for[b][0 if a == "Hx" else 1] if (b in h_for and a in ("Hx", "Hy")) else loc[a]
        tc, v = HL.hourly_pair_coherence(ha[:n], loc[b][:n], fs, HL.BAND_S[0], HL.BAND_S[1])
        fr[a + b] = v
    swapped = bool((HL._frac(fr["HxEx"], HL.E_COH) > HL._frac(fr["HxEy"], HL.E_COH) + HL.SWAP_MARGIN)
                   and (HL._frac(fr["HyEy"], HL.E_COH) > HL._frac(fr["HyEx"], HL.E_COH) + HL.SWAP_MARGIN))
    finite = np.isfinite(fr["HxHy"])
    for v in fr.values():
        finite &= np.isfinite(v)
    return {"start_s": tc - HL.WIN_S / 2.0, "centre_s": tc,
            "xy": fr["HxEx"] if swapped else fr["HyEx"],
            "yx": fr["HyEy"] if swapped else fr["HxEy"],
            "finite": finite, "swapped": swapped, "angle": ang}


def slot_runs(keep: np.ndarray, grain: int) -> list[tuple[float, float]]:
    """Return the runs of kept slots as [start, end) seconds from sample 0."""
    keep = np.asarray(keep, bool)
    if not keep.any():
        return []
    d = np.diff(np.concatenate(([0], keep.astype(np.int8), [0])))
    return [(float(a * grain), float(b * grain)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))]


def select(series: dict, mode: str, threshold: float = THRESHOLD, grain: int = 3600) -> dict:
    """Select one mode's kept slots at a grain from the hourly series (module docstring).

    Returns:
        dict: ``mode``, ``grain``, ``threshold``, ``keep`` and ``data`` (bool per slot), ``runs``
        ([start, end) s from sample 0), ``n_slots``.
    """
    if grain not in GRAINS:
        raise ValueError(f"grain must be one of {GRAINS}, not {grain}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {tuple(MODES)}, not {mode!r}")
    start = np.asarray(series["start_s"], float)
    ok = passes(series[mode], threshold) & np.asarray(series["finite"], bool)
    fin = np.asarray(series["finite"], bool)
    step = int(round(HL.STEP_S))
    idx = np.rint(start / step).astype(int)                 # window k starts at k * STEP_S
    per = int(round(HL.WIN_S / grain))                       # slots a window covers: 1 at 3600, 2 at 1800
    n_slots = int(np.ceil((start[-1] + HL.WIN_S) / grain)) if start.size else 0
    keep = np.zeros(n_slots, bool)
    data = np.zeros(n_slots, bool)
    for k, good, f in zip(idx, ok, fin):
        s0 = k * step
        if s0 % grain:
            continue                                         # not on this grain's grid (3600: odd windows)
        first = s0 // grain
        if f:
            data[first:first + per] = True
        if good:
            keep[first:first + per] = True
    return {"mode": mode, "grain": int(grain), "threshold": float(threshold), "keep": keep, "data": data,
            "runs": slot_runs(keep, grain), "n_slots": n_slots}


def random_control(sel: dict, seed: int) -> dict:
    """The selection's kept-slot pattern turned circularly by a random offset over the data slots."""
    out = dict(sel)
    di = np.flatnonzero(sel["data"])
    pattern = sel["keep"][di]
    rng = np.random.default_rng(seed)
    shift = int(rng.integers(1, max(2, di.size))) if di.size > 1 else 0
    keep = np.zeros_like(sel["keep"])
    keep[di] = np.roll(pattern, shift)
    out.update(keep=keep, runs=slot_runs(keep, sel["grain"]), control=f"random:{seed}", shift_slots=shift,
               overlap=float((keep & sel["keep"]).sum() / max(1, sel["keep"].sum())))
    return out


def half_control(sel: dict, half: str) -> dict:
    """The selection's runs taken alternately: A the 1st, 3rd, ...; B the 2nd, 4th, ..."""
    if half not in ("A", "B"):
        raise ValueError(f"half must be A or B, not {half!r}")
    out = dict(sel)
    keep = np.zeros_like(sel["keep"])
    g = sel["grain"]
    for k, (a, b) in enumerate(sel["runs"]):
        if (k % 2 == 0) == (half == "A"):
            keep[int(a // g):int(b // g)] = True
    out.update(keep=keep, runs=slot_runs(keep, g), control=f"half:{half}")
    return out


def _complement(runs, lo: float, hi: float) -> list[tuple[float, float]]:
    """[lo, hi) with the runs taken out."""
    out, cur = [], lo
    for a, b in sorted(runs):
        if b <= cur or a >= hi:
            continue
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < hi:
        out.append((cur, hi))
    return out


def stretch_masks(sel: dict, t0, record_start, record_end, mode: str, band=(0.0, BAND_MAX)) -> list[dict]:
    """Return the masks.yaml entries on the complement of a selection's runs.

    Args:
        sel (dict): From `select` (or a control).
        t0: Time of sample 0 of the series.
        record_start, record_end: The record the complement spans (UTC).
        mode (str): "xy" or "yx" (channels [ex] or [ey]).
        band (tuple): (band_min, band_max), s.

    Returns:
        list of dict: Normalised entries, earliest first.
    """
    t0, rs, re_ = utc(t0), utc(record_start), utc(record_end)
    lo = (rs - t0).total_seconds()
    hi = (re_ - t0).total_seconds()
    runs = [(max(a, lo), min(b, hi)) for a, b in sel["runs"] if min(b, hi) > max(a, lo)]
    kept_h = sum(b - a for a, b in runs) / 3600.0
    total_h = (hi - lo) / 3600.0
    ctl = f", control {sel['control']}" if sel.get("control") else ""
    reason = (f"stretch: {mode} hours with E-H coherence (20-200 s) > {sel['threshold']:g} at "
              f"{sel['grain'] / 60:g}-min grain; {kept_h:.1f} h of {total_h:.1f} h kept in {len(runs)} runs"
              f"{ctl}; bands to {band[1]:g} s (stretch_masks.py)")
    out = []
    for a, b in _complement(runs, lo, hi):
        out.append(normalise({"start": t0 + pd.Timedelta(seconds=a), "end": t0 + pd.Timedelta(seconds=b),
                              "bands": [float(band[0]), float(band[1])], "reason": reason, "found_by": ORIGIN,
                              "scope": "local", "channels": [MODES[mode]]}))
    return out


def write_candidate(path, survey_yaml, site: str, masks) -> Path:
    """Write a candidate file laid out as masks.yaml; the survey's own masks.yaml is refused."""
    from cluster_masks import write_mask_file

    path = Path(path)
    if path.resolve() == masks_path(Path(survey_yaml)).resolve():
        raise SystemExit(f"{path} is the survey's masks.yaml: stretch masks go to a candidate file "
                         "(scripts/process_rr.py --masks-file), never into the masks of record")
    return write_mask_file(path, site, masks)


def site_series(survey_yaml, site: str) -> tuple[pd.Timestamp, float, dict, object]:
    """Read a site's archive as scripts/health_table.py does and return (t0, record seconds, series, survey)."""
    from health_table import load_survey, recorded_e
    from mt_workbench.ingest import archive_rot_e, default_archive_path
    from mt_workbench.timefreq import load_station

    survey = load_survey(Path(survey_yaml))
    archive = default_archive_path(survey, site)
    if not archive.exists():
        raise SystemExit(f"{site}: no archive {archive}")
    rec = load_station(archive, survey.name, site, comps=("hx", "hy", "ex", "ey"))
    fs = rec.sample_rate
    one = {c: HL.to_1hz(rec.value(c), fs, gaps=rec.gaps) for c in ("hx", "hy")}
    laid = archive_rot_e(archive, site)
    und = recorded_e(rec.value("ex"), rec.value("ey"), laid)
    e = {"ex": rec.value("ex"), "ey": rec.value("ey")} if und is None else {"ex": und[0], "ey": und[1]}
    e_dirs = None if und is None else und[2]
    for c in ("ex", "ey"):
        one[c] = HL.to_1hz(e[c], fs, gaps=rec.gaps)
    ser = line_series(one["hx"], one["hy"], one["ex"], one["ey"], 1.0, e_dirs)
    return pd.Timestamp(rec.t0), float(len(one["hx"])), ser, survey


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=next(ln for ln in __doc__.strip().splitlines() if ln.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("site")
    p.add_argument("--modes", default="xy,yx", help="comma list of xy, yx (default both)")
    p.add_argument("--grain", type=int, choices=GRAINS, default=3600)
    p.add_argument("--threshold", type=float, default=THRESHOLD)
    p.add_argument("--band-max", type=float, default=BAND_MAX)
    p.add_argument("--band-min", type=float, default=0.0)
    p.add_argument("--control", default=None, metavar="random:SEED|half:A|half:B")
    p.add_argument("--out", default=None, metavar="FILE")
    p.add_argument("--series", default=None, metavar="FILE.csv")
    return p.parse_args(argv)


def apply_control(sel: dict, control: str | None) -> dict:
    if not control:
        return sel
    kind, _, arg = control.partition(":")
    if kind == "random":
        return random_control(sel, int(arg))
    if kind == "half":
        return half_control(sel, arg)
    raise SystemExit(f"--control takes random:SEED, half:A or half:B, not {control!r}")


def main(argv=None) -> int:
    args = parse_args(argv)
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes or any(m not in MODES for m in modes):
        raise SystemExit(f"--modes takes a comma list of {', '.join(MODES)}; given {args.modes!r}")
    t0, n_s, ser, survey = site_series(args.survey_yaml, args.site)
    cfg = survey.site(args.site)
    end = t0 + pd.Timedelta(seconds=n_s)
    rs = min(utc(cfg.start), utc(t0)) if cfg.start else utc(t0)
    re_ = max(utc(cfg.end), utc(end)) if cfg.end else utc(end)
    masks = []
    for mode in modes:
        sel = apply_control(select(ser, mode, args.threshold, args.grain), args.control)
        ms = stretch_masks(sel, t0, rs, re_, mode, (args.band_min, args.band_max))
        runs = sel["runs"]
        longest = max((b - a for a, b in runs), default=0.0) / 3600.0
        print(f"{args.site} {mode}: {sum(b - a for a, b in runs) / 3600:.1f} h kept of "
              f"{(re_ - rs).total_seconds() / 3600:.1f} h, {len(runs)} runs, longest {longest:.1f} h; "
              f"{len(ms)} masks" + (f" ({sel['control']})" if sel.get("control") else ""))
        masks.extend(ms)
    tag = f"_{args.control.replace(':', '')}" if args.control else ""
    out = Path(args.out) if args.out else (survey.workspace / "qc" / "stretch_masks" /
                                           f"{args.site}_stretch_g{args.grain}_t{args.threshold:g}{tag}.yaml")
    path = write_candidate(out, args.survey_yaml, args.site, masks)
    print(f"candidate: {path}")
    if args.series:
        df = pd.DataFrame({"start": [t0 + pd.Timedelta(seconds=float(s)) for s in ser["start_s"]],
                           "centre": [t0 + pd.Timedelta(seconds=float(s)) for s in ser["centre_s"]],
                           "xy": ser["xy"], "yx": ser["yx"], "finite": ser["finite"]})
        Path(args.series).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.series, index=False)
        print(f"series: {args.series}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
