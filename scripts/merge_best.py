# -*- coding: utf-8 -*-
"""
Merge the good period ranges of several EDIs of one site into one EDI

A recipe (YAML) names, per site and per mode (xy, yx and optionally the
tipper), an ordered list of sources, each an EDI with a period range
[pmin, pmax] in s. The x row (Zxx, Zxy and their errors) of the written EDI
comes from the xy sources, the y row (Zyx, Zyy and their errors) from the yx
sources and the tipper from the tipper sources. The period grid is the union
of the sources' usable periods inside their ranges, merged within LOG_TOL in
log10 period. At each grid period a mode takes the first source in its list
whose range covers the period and which gives a value there: its own values
at a period it holds (within LOG_TOL) where they are usable, or, at a period
it does not hold, values interpolated linearly in log10 period (real and
imaginary parts separately, errors likewise) between its two neighbouring
periods inside the range when both are usable. A source period whose row is
zero or non-finite (the EMPTY value read back) is not usable: the source
gives no value at it nor between its neighbours across it, and the period
passes to the next source in the list. A period for which no source of a
mode gives a value is NaN, which mt_metadata's EDI writer stores as the
EMPTY value 1e+32. Without a tipper list the EDI has no tipper.

The station metadata, location and header come from the first xy source; its
INFO block's processing parameters are replaced by ``crust.*`` lines naming
the recipe, each source and its range. The station ids of all sources must
agree (--force merges them regardless); their remotes may differ.
``OUT.json`` beside the output records the recipe, each source (path,
station, and the remote, tag, window and masks of its ``<stem>.json``
sidecar), the periods taken from each source per mode, the gaps, and the UTC
time. Exit status: 0 written, 2 when a recipe entry lacks edi, pmin or pmax,
a range is not 0 < pmin <= pmax, a mode has no source listed, a source is
missing, a mode takes no period, or the stations differ without --force.
`merge_files` is the same merge for a caller in Python.

With --auto the script proposes a recipe for one site from candidate EDIs
and writes it to --propose. Per quarter-decade band and mode, a candidate is
dropped when it has no error bars there, when fewer than half of its phases
lie in the mode's quadrant, or when its median rho differs by more than
JUMP_DEX from that of each of its neighbouring bands; the rest are ranked by
the median relative rho error (crust.quality.curves). The lowest wins,
unless the candidate holding the band below is within PREFER of it. Runs of
bands with one winner become one recipe entry spanning the winner's periods
there, and a comment per band names the runner-up and the margin.

Usage:
    python scripts/merge_best.py OUT.edi --recipe recipes.yaml --site D03 [--tag TAG] [--force]
    python scripts/merge_best.py --auto --site D03 --candidates A.edi B.edi ... --propose recipe_out.yaml

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.metadata
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

import crust  # noqa: E402
from crust.quality import MODES as QUALITY_MODES, curves, in_quadrant  # noqa: E402
from merge_modes import (ISO, LOG_TOL, X_ROW, Y_ROW, read_sidecar, read_tf, row_of, row_on_grid,  # noqa: E402
                         source_entry, usable)

MODES = ("xy", "yx", "tipper")
REQUIRED = ("xy", "yx")
ROWS = {"xy": X_ROW, "yx": Y_ROW}
BANDS_PER_DECADE = 4  # --auto bands: quarter decades
JUMP_DEX = 0.3  # --auto: a band whose median rho is this far from each neighbouring band's drops the candidate
PREFER = 0.2  # --auto: the candidate holding the band below is kept while its error is within this of the lowest
RULE = ("per mode, at each period of the grid (the union of the sources' usable periods inside their ranges, "
        "merged within LOG_TOL in log10 period), the first listed source whose range covers the period and which "
        "gives a value there: copied at a period it holds within LOG_TOL where its row is usable, interpolated "
        "linearly in log10 period between its two neighbouring periods inside the range when both are usable "
        "(real and imaginary parts separately, errors likewise) at a period it does not hold; a held period whose "
        "row is zero or non-finite passes to the next source; NaN where no source gives a value")


def load_recipe(path) -> dict:
    """Read a recipe file, a mapping of site to its recipe."""
    with open(path, encoding="utf-8") as handle:
        recipe = yaml.safe_load(handle)
    if not isinstance(recipe, dict):
        raise ValueError(f"{path}: a recipe is a mapping of site to {{xy: [...], yx: [...]}}")
    return recipe


def mode_row(tf: TF, mode: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return a TF's periods and one mode's row with its errors.

    Args:
        tf (TF): The transfer function.
        mode (str): ``"xy"`` (the x row), ``"yx"`` (the y row) or
            ``"tipper"``.

    Returns:
        tuple: ``(period, z, err)``, (n,) float, (n, 2) complex and (n, 2)
        float; the tipper row is NaN when the TF has none.
    """
    period = np.asarray(tf.period, dtype=float)
    if mode != "tipper":
        return (period, *row_of(tf, ROWS[mode]))
    if not tf.has_tipper():
        return period, np.full((period.size, 2), np.nan, dtype=complex), np.full((period.size, 2), np.nan)
    t = np.asarray(tf.tipper.data)[:, 0, :].astype(complex)
    if tf.tipper_error is None:
        return period, t, np.zeros(t.shape)
    return period, t, np.asarray(tf.tipper_error.data, dtype=float)[:, 0, :]


def in_range(period, entry: dict) -> np.ndarray:
    """Flag the periods inside an entry's [pmin, pmax], with LOG_TOL of slack in log10 period."""
    x = np.log10(np.asarray(period, dtype=float))
    return (x >= np.log10(entry["pmin"]) - LOG_TOL) & (x <= np.log10(entry["pmax"]) + LOG_TOL)


def period_grid(plan: dict, rows: dict) -> np.ndarray:
    """Return the union of the entries' usable periods inside their ranges.

    Args:
        plan (dict): Mode to its list of entries (``edi`` resolved, ``pmin``,
            ``pmax``).
        rows (dict): ``(edi, mode)`` to the output of `mode_row`.

    Returns:
        np.ndarray: The grid periods in s, ascending; of several within
        LOG_TOL in log10 period the shortest is kept.
    """
    found = [np.zeros(0)]
    for mode, entries in plan.items():
        for entry in entries:
            p, z, _e = rows[(entry["edi"], mode)]
            found.append(p[usable(z) & in_range(p, entry)])
    keep, last = [], None
    for value in np.sort(np.concatenate(found)):
        if last is None or np.log10(value) - np.log10(last) > LOG_TOL:
            keep.append(value)
            last = value
    return np.asarray(keep, dtype=float)


def across_empty(grid: np.ndarray, p_good: np.ndarray, p_empty: np.ndarray, kind: np.ndarray) -> np.ndarray:
    """Flag the interpolated grid periods whose two neighbouring usable source periods enclose an unusable one.

    Args:
        grid (np.ndarray): (n,) periods in s.
        p_good (np.ndarray): The source's usable periods inside the range.
        p_empty (np.ndarray): The source's unusable periods inside the range.
        kind (np.ndarray): (n,) str, the output of `row_on_grid` from the
            usable periods.

    Returns:
        np.ndarray: (n,) bool, True where a period marked "interpolated"
        lies between usable neighbours with an unusable period between them.
    """
    flags = np.zeros(grid.size, dtype=bool)
    interp = kind == "interpolated"
    if not interp.any() or p_empty.size == 0:
        return flags
    x_good, x_empty = np.sort(np.log10(p_good)), np.sort(np.log10(p_empty))
    x = np.log10(grid[interp])
    upper = np.searchsorted(x_good, x)
    lo, hi = x_good[upper - 1], x_good[upper]
    flags[interp] = np.searchsorted(x_empty, hi, side="left") > np.searchsorted(x_empty, lo, side="right")
    return flags


def take(grid: np.ndarray, entries: list[dict], mode: str, rows: dict) -> tuple:
    """Fill one mode's row on the grid from its entries, the first that gives a value winning.

    An entry gives a value at a grid period it holds where its row is
    usable, and at a period it does not hold by interpolation between its
    two neighbouring periods inside the range when both are usable; a held
    period whose row is not usable passes to the next entry.

    Args:
        grid (np.ndarray): (n,) periods in s.
        entries (list[dict]): The mode's entries in recipe order.
        mode (str): The mode.
        rows (dict): ``(edi, mode)`` to the output of `mode_row`.

    Returns:
        tuple: ``(z, err, owner, kind)``: (n, 2) complex and (n, 2) float,
        NaN where no entry gives a value; (n,) int, the index of the entry
        taken, -1 for none; (n,) str, "copied", "interpolated" or "nan".
    """
    n = grid.size
    z, err = np.full((n, 2), np.nan, dtype=complex), np.full((n, 2), np.nan)
    owner, kind = np.full(n, -1), np.full(n, "nan", dtype=object)
    for k, entry in enumerate(entries):
        p, zs, es = rows[(entry["edi"], mode)]
        inside, good = in_range(p, entry), usable(zs)
        keep = good & inside
        zk, ek, kk = row_on_grid(p[keep], zs[keep], es[keep], grid)
        kk[across_empty(grid, p[keep], p[inside & ~good], kk)] = "nan"
        new = (owner < 0) & (kk != "nan") & in_range(grid, entry)
        z[new], err[new], owner[new], kind[new] = zk[new], ek[new], k, kk[new]
    return z, err, owner, kind


def runs_of(flags: np.ndarray, grid: np.ndarray) -> list[list[float]]:
    """Return the first and last period of each run of flagged grid periods."""
    runs, start = [], None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        if start is not None and (not flag or i == flags.size - 1):
            end = i if flag else i - 1
            runs.append([float(grid[start]), float(grid[end])])
            start = None
    return runs


def build_tf(first: TF, grid: np.ndarray, taken: dict) -> TF:
    """Build the merged TF on the grid with the first xy source's survey and station metadata.

    Args:
        first (TF): The first xy source.
        grid (np.ndarray): (n,) periods in s.
        taken (dict): Mode to the output of `take`.

    Returns:
        TF: The merged transfer function.
    """
    tf = TF()
    tf.survey_metadata = copy.deepcopy(first.survey_metadata)
    tf.station_metadata = copy.deepcopy(first.station_metadata)
    tf.period = grid
    z = np.full((grid.size, 2, 2), np.nan, dtype=complex)
    err = np.full((grid.size, 2, 2), np.nan)
    for mode in REQUIRED:
        z[:, ROWS[mode], :], err[:, ROWS[mode], :] = taken[mode][0], taken[mode][1]
    tf.impedance = z
    tf.impedance_error = err
    if "tipper" in taken:
        tf.tipper = taken["tipper"][0][:, None, :]
        tf.tipper_error = taken["tipper"][1][:, None, :]
    return tf


def _span(lo: float, hi: float) -> str:
    """Format a period range as "lo .. hi s"."""
    return f"{lo:.4g} .. {hi:.4g} s"


def _joined(values: list) -> str | None:
    """Join the distinct non-empty values in order of appearance with "/"; None when there are none."""
    seen = list(dict.fromkeys(str(v) for v in values if v))
    return "/".join(seen) if seen else None


def _write_atomic(path: Path, text: str) -> None:
    """Write text to a temporary file beside `path`, then move it into place."""
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def info_lines(side: dict) -> list[str]:
    """Build the ``crust.*`` lines of the merged EDI's INFO block."""
    recipe = side["recipe"]["path"]
    lines = [f"crust.version={side['versions']['crust']}", f"crust.merged={side['created']}",
             f"crust.tag={side['tag'] or ''}", f"crust.site={side['site']}",
             f"crust.recipe={Path(recipe).name if recipe else ''}"]
    for mode, block in side["merge"]["modes"].items():
        for k, entry in enumerate(block["entries"], start=1):
            lines.append(f"crust.best_{mode}_{k}={Path(entry['edi']).name},{entry['pmin']:g},{entry['pmax']:g}")
    lines.append(f"crust.sidecar={Path(side['edi']).with_suffix('.json').name}")
    return lines


def resolve_plan(recipe_for_site: dict, base: Path) -> tuple[dict, list[str]]:
    """Check a site's recipe and resolve its EDI paths.

    Args:
        recipe_for_site (dict): ``{xy: [...], yx: [...], tipper: [...],
            note: str}``, each entry ``{edi, pmin, pmax}``.
        base (Path): Directory relative EDI paths are taken from.

    Returns:
        tuple: ``(plan, errors)``: mode to its list of entries with ``edi``
        resolved and ``pmin``, ``pmax`` as floats, and one line per problem.
    """
    plan, errors = {}, []
    for mode in MODES:
        entries = recipe_for_site.get(mode)
        if entries is None and mode == "tipper":
            continue
        if not entries:
            errors.append(f"mode {mode}: no source listed")
            continue
        plan[mode] = []
        for entry in entries:
            try:
                edi = Path(entry["edi"])
                pmin, pmax = float(entry["pmin"]), float(entry["pmax"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"mode {mode}: entry {entry!r} needs edi, pmin and pmax")
                continue
            if not 0 < pmin <= pmax:
                errors.append(f"mode {mode}: {edi.name} range {pmin:g} .. {pmax:g} s is not 0 < pmin <= pmax")
            edi = (edi if edi.is_absolute() else base / edi).resolve()
            if not edi.is_file():
                errors.append(f"{edi}: no such file")
            plan[mode].append({"edi": edi, "pmin": pmin, "pmax": pmax})
    return plan, errors


def mode_block(mode: str, entries: list[dict], taken: tuple, grid: np.ndarray, paths: list[Path]) -> dict:
    """Describe what one mode took from each entry for the sidecar, printing a line per entry and the gaps.

    Args:
        mode (str): The mode.
        entries (list[dict]): The mode's entries.
        taken (tuple): The mode's output of `take`.
        grid (np.ndarray): (n,) periods in s.
        paths (list[Path]): The distinct sources, in the order of the
            sidecar's ``sources``.

    Returns:
        dict: ``entries`` (per entry its ``source`` index, ``edi``,
        ``pmin``, ``pmax`` and the ``copied`` and ``interpolated`` periods),
        ``n_nan`` and ``gaps`` (first and last period of each NaN run).
    """
    _z, _e, owner, kind = taken
    block = {"entries": [], "n_nan": int((owner < 0).sum()), "gaps": runs_of(owner < 0, grid)}
    for k, entry in enumerate(entries):
        copied, interp = grid[(owner == k) & (kind == "copied")], grid[(owner == k) & (kind == "interpolated")]
        block["entries"].append({"source": paths.index(entry["edi"]), "edi": str(entry["edi"]),
                                 "pmin": entry["pmin"], "pmax": entry["pmax"],
                                 "copied": [float(p) for p in copied], "interpolated": [float(p) for p in interp]})
        print(f"{mode} <- {entry['edi'].name} {_span(entry['pmin'], entry['pmax'])}: "
              f"{copied.size} copied, {interp.size} interpolated")
    gaps = ", ".join(_span(lo, hi) for lo, hi in block["gaps"]) or "none"
    print(f"{mode}: {block['n_nan']} of {grid.size} periods NaN ({gaps})")
    return block


def merge_files(out, recipe_for_site: dict, tag: str | None = None, force: bool = False,
                argv: list[str] | None = None, site: str | None = None, recipe_path=None) -> int:
    """Write the merged EDI and its sidecar from one site's recipe, printing what was taken from each source.

    Args:
        out (str | Path): Merged EDI to write; the sidecar goes beside it as
            .json.
        recipe_for_site (dict): ``{xy: [{edi, pmin, pmax}, ...], yx: [...],
            tipper: [...] (optional), note: str (optional)}``.
        tag (str | None): Label recorded in the sidecar and the INFO block.
        force (bool): Merge sources whose stations differ.
        argv (list[str] | None): Command line recorded in the sidecar;
            sys.argv when None.
        site (str | None): Site name recorded; the first xy source's station
            when None.
        recipe_path (str | Path | None): The recipe file, recorded; relative
            EDI paths are taken from its directory, or from the working
            directory when None.

    Returns:
        int: 0 when written, 2 when a recipe entry lacks edi, pmin or pmax,
        a range is not 0 < pmin <= pmax, a mode has no source listed, a
        source is missing, a mode takes no period, or the stations differ
        without `force`.
    """
    out = Path(out).resolve()
    recipe_path = None if recipe_path is None else Path(recipe_path).resolve()
    plan, errors = resolve_plan(recipe_for_site, recipe_path.parent if recipe_path else Path.cwd())
    for line in errors:
        print(f"ERROR {line}", file=sys.stderr)
    if errors:
        return 2

    paths = list(dict.fromkeys(entry["edi"] for entries in plan.values() for entry in entries))
    tfs = {path: read_tf(path) for path in paths}
    first_path = plan["xy"][0]["edi"]
    station = tfs[first_path].station_metadata.id
    found = [f"stations differ: {first_path.name} {station}, {path.name} {tfs[path].station_metadata.id}"
             for path in paths if tfs[path].station_metadata.id != station]
    if found and not force:
        for line in found:
            print(f"ERROR {line}; --force merges them", file=sys.stderr)
        return 2
    for line in found:
        print(f"WARNING {line}: merged under --force")

    rows = {(entry["edi"], mode): mode_row(tfs[entry["edi"]], mode)
            for mode, entries in plan.items() for entry in entries}
    grid = period_grid(plan, rows)
    taken = {mode: take(grid, entries, mode, rows) for mode, entries in plan.items()}
    empty = [mode for mode, result in taken.items() if not (result[2] >= 0).any()]
    for mode in empty:
        print(f"ERROR mode {mode}: no source gives a value inside its range", file=sys.stderr)
    if empty:
        return 2

    sidecars = {path: read_sidecar(path) for path in paths}
    modes = {mode: mode_block(mode, entries, taken[mode], grid, paths) for mode, entries in plan.items()}
    created = dt.datetime.now(dt.timezone.utc).strftime(ISO)
    found_sides = [s for _p, s in sidecars.values() if s is not None]
    side = {
        "local": station,
        "remote": _joined([s.get("remote") for s in found_sides]),
        "created": created,
        "tag": tag,
        "edi": out.name,
        "site": site or station,
        "recipe": {"path": None if recipe_path is None else str(recipe_path), "site": recipe_for_site},
        "merge": {"rule": RULE, "log10_period_tolerance": LOG_TOL, "n_periods": int(grid.size),
                  "period_range": [float(grid.min()), float(grid.max())], "modes": modes,
                  "tipper": "recipe" if "tipper" in plan else None},
        "sources": [source_entry(path, tfs[path], *sidecars[path]) for path in paths],
        "forced": bool(force),
        "mismatches": found,
        "argv": list(sys.argv if argv is None else argv),
        "versions": {"crust": crust.__version__, "mt_metadata": importlib.metadata.version("mt_metadata")},
    }
    if found_sides:
        side["engine"] = _joined([s.get("engine") or "aurora" for s in found_sides])
    tf = build_tf(tfs[first_path], grid, taken)
    tf.station_metadata.transfer_function.processing_parameters = info_lines(side)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + "_part.edi")
    tf.write(fn=str(tmp), file_type="edi")
    os.replace(tmp, out)
    side_path = out.with_suffix(".json")
    _write_atomic(side_path, json.dumps(side, indent=2, default=str) + "\n")
    print(f"edi: {out}")
    print(f"sidecar: {side_path}")
    return 0


def band_of(period) -> np.ndarray:
    """Return the quarter-decade band of each period.

    Band k spans [10**(k/4), 10**((k+1)/4)); a period within LOG_TOL in
    log10 period below an edge counts in the band above it.
    """
    x = np.log10(np.asarray(period, dtype=float)) + LOG_TOL
    return np.floor(BANDS_PER_DECADE * x).astype(int)


def band_stats(edi, mode: str) -> dict[int, dict]:
    """Summarise one candidate's mode per band.

    Args:
        edi (str | Path): The candidate EDI.
        mode (str): ``"xy"`` or ``"yx"``.

    Returns:
        dict: Band to ``rel_err`` (median rho_err / rho, NaN without error
        bars), ``log_rho`` (median log10 rho), ``quadrant_frac`` and
        ``periods``, over the band's periods with finite, positive rho and
        finite phase.
    """
    period, rho, phi, rho_err, _ = curves(Path(edi))
    i, j = QUALITY_MODES[mode]
    r, ph, e = rho[:, i, j], phi[:, i, j], rho_err[:, i, j]
    valid = np.isfinite(r) & (r > 0) & np.isfinite(ph)
    bands = band_of(period)
    out = {}
    for b in np.unique(bands[valid]):
        sel = valid & (bands == b)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = e[sel] / r[sel]
        rel = rel[np.isfinite(rel) & (rel > 0)]
        out[int(b)] = {"rel_err": float(np.median(rel)) if rel.size else float("nan"),
                       "log_rho": float(np.median(np.log10(r[sel]))),
                       "quadrant_frac": float(in_quadrant(ph[sel], mode).mean()), "periods": period[sel]}
    return out


def drop_reason(stats: dict[int, dict], band: int) -> str | None:
    """Say why a candidate is dropped in a band; None when it is ranked there."""
    s = stats[band]
    if not np.isfinite(s["rel_err"]):
        return "no error bars"
    if s["quadrant_frac"] < 0.5:
        return f"phase out of quadrant at {100 * (1 - s['quadrant_frac']):.0f} % of periods"
    jumps = [abs(s["log_rho"] - stats[n]["log_rho"]) for n in (band - 1, band + 1) if n in stats]
    if jumps and min(jumps) > JUMP_DEX:
        return f"rho jumps {min(jumps):.2f} dex from its neighbouring bands"
    return None


def choose(stats: list[dict[int, dict]]) -> list[dict]:
    """Pick a candidate per band of one mode, in ascending period.

    Args:
        stats (list[dict]): Per candidate, the output of `band_stats`.

    Returns:
        list[dict]: Per band holding data, ``band``, ``choice`` (candidate
        index or None), ``errors`` (candidate index to rel_err of the ranked
        candidates, lowest first), ``dropped`` (candidate index to reason)
        and ``kept`` (True when the choice holds the band below and is not
        the lowest).
    """
    out, incumbent, previous = [], None, None
    for band in sorted(set().union(*stats)):
        if previous is not None and band != previous + 1:
            incumbent = None
        errors, dropped = {}, {}
        for c, st in enumerate(stats):
            if band in st:
                reason = drop_reason(st, band)
                if reason is None:
                    errors[c] = st[band]["rel_err"]
                else:
                    dropped[c] = reason
        errors = dict(sorted(errors.items(), key=lambda item: item[1]))
        choice, kept = next(iter(errors), None), False
        if incumbent in errors and incumbent != choice and errors[incumbent] <= (1 + PREFER) * errors[choice]:
            choice, kept = incumbent, True
        out.append({"band": band, "choice": choice, "errors": errors, "dropped": dropped, "kept": kept})
        incumbent, previous = choice, band
    return out


def band_comment(pick: dict, names: list[str]) -> str:
    """Write the proposal's comment line for one band."""
    lo, hi = (10 ** (k / BANDS_PER_DECADE) for k in (pick["band"], pick["band"] + 1))
    choice, errors = pick["choice"], pick["errors"]
    text = f"# {lo:.3g}-{hi:.3g} s: "
    if choice is None:
        text += "no candidate"
    else:
        text += f"{names[choice]} err {errors[choice]:.3f}"
        if pick["kept"]:
            text += f", kept from the band below (within {100 * PREFER:.0f} % of the lowest)"
        others = [c for c in errors if c != choice]
        if others:
            r = others[0]
            text += f"; runner-up {names[r]} err {errors[r]:.3f} ({100 * (errors[r] / errors[choice] - 1):+.0f} %)"
        else:
            text += "; no runner-up"
    for c, reason in pick["dropped"].items():
        text += f"; dropped {names[c]} ({reason})"
    return text


def propose(candidates: list[Path]) -> dict[str, list[dict]]:
    """Propose each mode's recipe entries from candidate EDIs.

    Args:
        candidates (list[Path]): The candidate EDIs.

    Returns:
        dict: Mode (xy, yx) to its runs of adjacent bands with one choice,
        each ``edi`` (None for bands without a choice), ``pmin`` and
        ``pmax`` (the chosen candidate's first and last periods in the run's
        bands) and ``picks`` (the run's bands, from `choose`).
    """
    out = {}
    for mode in REQUIRED:
        stats = [band_stats(path, mode) for path in candidates]
        runs = []
        for pick in choose(stats):
            last = runs[-1]["picks"][-1] if runs else None
            if last is not None and last["choice"] == pick["choice"] and last["band"] == pick["band"] - 1:
                runs[-1]["picks"].append(pick)
            else:
                runs.append({"picks": [pick]})
        for run in runs:
            c = run["picks"][0]["choice"]
            run["edi"] = None if c is None else candidates[c]
            if c is not None:
                p = np.concatenate([stats[c][pick["band"]]["periods"] for pick in run["picks"]])
                run["pmin"], run["pmax"] = float(p.min()), float(p.max())
        out[mode] = runs
    return out


def proposal_text(site: str, candidates: list[Path], runs: dict, created: str) -> str:
    """Write the proposed recipe as YAML with a comment per band."""
    names = [path.name for path in candidates]
    lines = [f"# Proposed by scripts/merge_best.py --auto at {created} from {len(candidates)} candidates.",
             "# Per quarter-decade band and mode the lowest median relative rho error (err, rho_err / rho) wins;",
             f"# a candidate out of quadrant or jumping more than {JUMP_DEX} dex from its neighbouring bands is",
             f"# dropped, and the candidate holding the band below is kept within {100 * PREFER:.0f} % of the lowest.",
             "# Candidates:"]
    lines += [f"#   {path}" for path in candidates]
    lines += [f"{site}:", f"  note: {json.dumps(f'proposed by merge_best.py --auto at {created}')}"]
    for mode in REQUIRED:
        lines.append(f"  {mode}:")
        for run in runs[mode]:
            lines += [f"    {band_comment(pick, names)}" for pick in run["picks"]]
            if run["edi"] is not None:
                lines.append(f"    - {{edi: {json.dumps(str(run['edi']))}, pmin: {run['pmin']:.6g}, "
                             f"pmax: {run['pmax']:.6g}}}")
        if all(run["edi"] is None for run in runs[mode]):
            lines.append("    []")
    return "\n".join(lines) + "\n"


def propose_files(propose_path, candidates, site: str) -> int:
    """Write a proposed recipe for one site from candidate EDIs, printing each mode's runs.

    Args:
        propose_path (str | Path): The recipe YAML to write.
        candidates (list): The candidate EDI paths.
        site (str): The site the recipe is for.

    Returns:
        int: 0 when written, 2 when a candidate is missing.
    """
    paths = [Path(c).resolve() for c in candidates]
    missing = [path for path in paths if not path.is_file()]
    for path in missing:
        print(f"ERROR {path}: no such file", file=sys.stderr)
    if missing:
        return 2
    runs = propose(paths)
    for mode in REQUIRED:
        for run in runs[mode]:
            if run["edi"] is None:
                print(f"{mode}: no candidate in {len(run['picks'])} band(s)")
            else:
                print(f"{mode} <- {run['edi'].name} {_span(run['pmin'], run['pmax'])} ({len(run['picks'])} bands)")
    created = dt.datetime.now(dt.timezone.utc).strftime(ISO)
    path = Path(propose_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, proposal_text(site, paths, runs, created))
    print(f"proposal: {path}")
    return 0


def main(argv=None) -> int:
    """Merge one site's recipe into an EDI, or propose a recipe with --auto.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: The status of `merge_files` or `propose_files`; 2 when the site
        is not in the recipe.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("out", nargs="?", help="merged EDI to write; its sidecar is written beside it as .json")
    parser.add_argument("--recipe", help="recipe YAML, site: {xy: [{edi, pmin, pmax}, ...], yx: [...]}")
    parser.add_argument("--site", required=True, help="site of the recipe to merge, or to propose a recipe for")
    parser.add_argument("--tag", default=None, help="label recorded in the sidecar and the INFO block")
    parser.add_argument("--force", action="store_true", help="merge sources whose stations differ")
    parser.add_argument("--auto", action="store_true", help="propose a recipe from --candidates into --propose")
    parser.add_argument("--candidates", nargs="+", help="candidate EDIs for --auto")
    parser.add_argument("--propose", help="recipe YAML written by --auto")
    args = parser.parse_args(argv)
    if args.auto:
        if not args.candidates or not args.propose:
            parser.error("--auto needs --candidates and --propose")
        return propose_files(args.propose, args.candidates, args.site)
    if not args.out or not args.recipe:
        parser.error("OUT and --recipe are needed without --auto")
    recipe = load_recipe(args.recipe)
    if args.site not in recipe:
        print(f"ERROR site {args.site} is not in {args.recipe}", file=sys.stderr)
        return 2
    return merge_files(args.out, recipe[args.site], tag=args.tag, force=args.force,
                       argv=["merge_best.py", *(sys.argv[1:] if argv is None else argv)], site=args.site,
                       recipe_path=args.recipe)


if __name__ == "__main__":
    sys.exit(main())
