# -*- coding: utf-8 -*-
"""
Merge two window lengths of one site by period band: the short source below a crossover, the long source above

A typical use takes the 256-sample, 75 % window product over the short and middle periods and the
default-window product (128 samples, 25 %) at the long end, merged by period band into one EDI, both sources and
the crossover named in INFO and the sidecar. Per part (the x row Zxx, Zxy; the y row Zyx, Zyy; the tipper) it takes the short source's
rows at periods up to the crossover T and the long source's rows above T, each row with its own errors, nothing
interpolated, nothing averaged. Each part may have sources of its own (the per-mode health windows of
scripts/health_windows.py give the x row and the y row different processing windows; the same window applies to
both window lengths, since a window belongs to the site, not to one window length).

The crossover, per part, from the rule (`--rule`):

- ``fixed:<T>``: T s.
- ``longest:<floor>``: the longest period at which the short source's error is no larger than the long source's
  (relative rho error = 2 |dZ| / |Z| for a row's off-diagonal; for the tipper the root sum of squares of the two
  tipper errors), never below the floor. Unstable at the long end where both errors are large and the comparison is
  a coin flip; kept for comparison.
- ``contiguous:<floor>``: from the floor up, the short source holds while its error stays no larger than the long
  source's; T is the last such period, the floor when the first period above it already fails.

Whatever the rule, T is capped at the short source's last populated period in that part (the ceiling), so the
merge never opens a gap between the short source's end and T. A part with no usable short row takes the long
source throughout (T = 0 recorded). The periods compared are those both sources hold within LOG_TOL in log10
period; the two products must share one band lattice (the same survey processing block), as scripts/merge_best.py
copies held periods only where it can.

The merge is scripts/merge_best.py's `merge_files` (grid union): per part the recipe lists the short source over
[its first period, T] and the long source over (T, its last period], the long range starting 2 LOG_TOL above T so
that a period on T is the short source's. Everything merge_best writes (EDI, EMTF XML, MTH5, sidecar; the first
xy source's station metadata and frame; INFO lines naming each source and range) is written, and this script adds
INFO lines ``mt_workbench.window_merge_rule``, ``mt_workbench.window_merge_crossover_<part>=<T> s ...``,
``mt_workbench.window_merge_short_<part>`` and ``..._long_<part>`` (file names), and, when given,
``mt_workbench.window_merge_window_<part>`` (the health window), and a sidecar block ``window_merge`` with the
rule, the crossover per part (``crossover_s``), the rule's own value before the ceiling (``rule_s``), the short
source's last period (``short_last_s``), both sources per part (full paths) and the windows.

Exit status: 0 written; 2 for a rule that is not fixed:<s>, longest:<s> or contiguous:<s> with s > 0, a part
without both sources, a missing file, or a refusal of merge_best's.

Usage:
    python scripts/merge_windows.py OUT.edi --short-xy A.edi --short-yx A.edi --long-xy B.edi --long-yx B.edi
        [--short-tipper A.edi --long-tipper B.edi] --rule fixed:2000 [--site S] [--tag TAG]
        [--window-xy TEXT] [--window-yx TEXT]

`merge_windows` is the same merge for a caller in Python (scripts/campaign.py's merge stage).

`merge_shortend` (Python only) puts a short-period product (the 10 Hz family) under the merged long product (the
1 Hz family): per part the short product's rows below the long product's first usable period, the long product's
from it on; with align "qld" the short rows are first multiplied by a level and
phase factor, the Gaussian-weighted (0.1 decade) mean of Z_long / Z_short over the common band (4-3,000 s by
default), recorded in INFO (`mt_workbench.shortend_*`) and the sidecar (`shortend`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

PARTS = ("xy", "yx", "tipper")
RULE_RE = re.compile(r"^(fixed|longest|contiguous):([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)$")


@lru_cache(maxsize=1)
def merge_best():
    """Import scripts/merge_best.py."""
    spec = importlib.util.spec_from_file_location("merge_best", REPO / "scripts" / "merge_best.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_rule(rule: str) -> tuple[str, float]:
    """Return (kind, seconds) of a rule string; raise ValueError for anything else."""
    m = RULE_RE.match(str(rule).strip())
    if not m or not float(m.group(2)) > 0:
        raise ValueError(f"rule {rule!r}: want fixed:<s>, longest:<floor s> or contiguous:<floor s>, s > 0")
    return m.group(1), float(m.group(2))


def part_row(tf, part: str):
    """Return (period, usable, error measure) of one part of a TF: rel rho error of the off-diagonal, tipper rss."""
    mb = merge_best()
    period, z, err = mb.mode_row(tf, part)
    good = mb.usable(z)
    if part == "tipper":
        measure = np.sqrt(np.nansum(np.asarray(err, dtype=float) ** 2, axis=1))
    else:
        col = 1 if part == "xy" else 0  # Zxy in the x row, Zyx in the y row
        a = np.abs(z[:, col])
        with np.errstate(divide="ignore", invalid="ignore"):
            measure = 2.0 * np.asarray(err, dtype=float)[:, col] / a
    good = good & np.isfinite(measure)
    return np.asarray(period, dtype=float), good, measure


def crossover(kind: str, value: float, short, long) -> tuple[float, float, float]:
    """Return (T, rule value before the ceiling, short source's last period) for one part.

    `short` and `long` are `part_row` outputs. T = 0 when the short source holds no usable row.
    """
    ps, gs, es = short
    pl, gl, el = long
    if not gs.any():
        return 0.0, float("nan"), float("nan")
    last = float(ps[gs].max())
    log_tol = merge_best().LOG_TOL

    def long_at(p):
        k = int(np.argmin(np.abs(np.log10(pl) - np.log10(p))))
        return k if abs(np.log10(pl[k]) - np.log10(p)) <= log_tol and gl[k] else None

    if kind == "fixed":
        t_rule = value
    elif kind == "longest":
        found = [p for i, p in enumerate(ps) if gs[i] and (k := long_at(p)) is not None and es[i] <= el[k]]
        t_rule = max(max(found), value) if found else value
    else:  # contiguous
        t_rule = value
        for i in np.argsort(ps):
            p = ps[i]
            if p <= value:
                continue
            k = long_at(p) if gs[i] else None
            if k is None or es[i] > el[k]:
                break
            t_rule = float(p)
    return float(min(t_rule, last)), float(t_rule), last


def merge_windows(out, short: dict, long: dict, rule: str, site: str | None = None, tag: str | None = None,
                  windows: dict | None = None, header: dict | None = None, argv: list[str] | None = None) -> int:
    """Write the window merge of one site.

    Args:
        out (str | Path): Merged EDI; its sidecar, XML and h5 go beside it.
        short (dict): Part ("xy", "yx", optionally "tipper") to the short source's EDI.
        long (dict): The same parts to the long source's EDI.
        rule (str): fixed:<s>, longest:<floor s> or contiguous:<floor s>.
        site (str | None): Site name recorded.
        tag (str | None): Tag recorded (merge_best's INFO and sidecar).
        windows (dict | None): Part to the health-window text of its sources ("whole record", "<start> to <end>
            UTC"), recorded.
        header (dict | None): merge_best's header block (acqby, prosby).
        argv (list[str] | None): Command line recorded; sys.argv when None.

    Returns:
        int: 0 when written, 2 when refused.
    """
    try:
        kind, value = parse_rule(rule)
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    parts = [p for p in PARTS if p in short or p in long]
    errors = [f"part {p}: needs both a short and a long source" for p in parts if not (short.get(p) and long.get(p))]
    errors += [f"part {p}: no source" for p in ("xy", "yx") if p not in parts]
    paths = {}
    for p in parts:
        for role, src in (("short", short), ("long", long)):
            if src.get(p):
                path = Path(src[p]).resolve()
                if not path.is_file():
                    errors.append(f"{path}: no such file")
                paths[(role, p)] = path
    if errors:
        for line in errors:
            print(f"ERROR {line}", file=sys.stderr)
        return 2
    mb = merge_best()
    tfs = {path: mb.read_tf(path) for path in set(paths.values())}
    recipe, record = {}, {"rule": f"{kind}:{value:g}", "crossover_s": {}, "rule_s": {}, "short_last_s": {},
                          "short": {}, "long": {}, "windows": dict(windows or {})}
    info = [f"mt_workbench.window_merge_rule={kind}:{value:g} (short source up to the crossover, long source above; "
            f"crossover capped at the short source's last period)"]
    for p in parts:
        s_path, l_path = paths[("short", p)], paths[("long", p)]
        s_row, l_row = part_row(tfs[s_path], p), part_row(tfs[l_path], p)
        t, t_rule, last = crossover(kind, value, s_row, l_row)
        entries = []
        if t > 0:
            entries.append({"edi": str(s_path), "pmin": float(s_row[0].min()), "pmax": t})
        lo = t * 10 ** (2 * mb.LOG_TOL) if t > 0 else float(l_row[0].min())
        if l_row[0].max() >= lo:
            entries.append({"edi": str(l_path), "pmin": lo, "pmax": float(l_row[0].max())})
        recipe[p] = entries
        record["crossover_s"][p], record["rule_s"][p], record["short_last_s"][p] = t, t_rule, last
        record["short"][p], record["long"][p] = str(s_path), str(l_path)
        info.append(f"mt_workbench.window_merge_crossover_{p}={t:g} s (rule {t_rule:g}, short last {last:g})")
        info.append(f"mt_workbench.window_merge_short_{p}={s_path.name}")
        info.append(f"mt_workbench.window_merge_long_{p}={l_path.name}")
        if windows and windows.get(p):
            info.append(f"mt_workbench.window_merge_window_{p}={windows[p]}")
        print(f"{p}: short {s_path.name} up to {t:g} s (rule {t_rule:g} s, short last {last:g} s), "
              f"long {l_path.name} above")
    recipe["note"] = f"window merge, rule {kind}:{value:g}"
    return mb.merge_files(out, recipe, tag=tag, site=site, header=header, argv=argv, extra_info=info,
                          extra={"window_merge": record})


SIGMA_DEX = 0.1  # the Queensland alignment's Gaussian smoothing, in decades of period
ALIGN_BAND = (4.0, 3000.0)  # the default band the factor is taken over (s): the 1 Hz and 10 Hz families' common band


def _amp_phase(tf, part: str):
    """Return (period, usable, log10 |Z|, unwrapped phase in rad) of a row's off-diagonal."""
    mb = merge_best()
    period, z, _err = mb.mode_row(tf, part)
    good = mb.usable(z)
    zz = z[:, 1 if part == "xy" else 0]
    good = good & np.isfinite(zz) & (np.abs(zz) > 0)
    p, zz = np.asarray(period, dtype=float)[good], zz[good]
    o = np.argsort(p)
    return p[o], np.log10(np.abs(zz[o])), np.unwrap(np.angle(zz[o]))


def align_factor(short_tf, long_tf, part: str, band=ALIGN_BAND, sigma=SIGMA_DEX):
    """Return the Queensland alignment of one row: a function of period giving the complex factor, and its record.

    At each usable long-product period in `band` the ratio Z_long / Z_short of the row's off-diagonal is taken,
    the short product's log10 |Z| and phase interpolated linearly in log10 period onto it (inside the short
    product's span only). The factor at period p is 10**L(p) exp(i Phi(p)), L and Phi the Gaussian-weighted means
    (sigma `sigma` decades of log10 period) of log10 |ratio| and of the phase difference over those periods.
    """
    pl, al, phl = _amp_phase(long_tf, part)
    ps, as_, phs = _amp_phase(short_tf, part)
    sel = (pl >= band[0] * (1 - 1e-9)) & (pl <= band[1] * (1 + 1e-9)) & (pl >= ps.min()) & (pl <= ps.max())
    if sel.sum() < 2:
        raise ValueError(f"part {part}: fewer than 2 common periods in {band[0]:g}-{band[1]:g} s to align on")
    x = np.log10(pl[sel])
    lev = al[sel] - np.interp(x, np.log10(ps), as_)
    dph = phl[sel] - np.interp(x, np.log10(ps), phs)
    dph = (dph + np.pi) % (2 * np.pi) - np.pi

    def factor(period):
        w = np.exp(-0.5 * ((np.log10(np.asarray(period, dtype=float))[:, None] - x[None, :]) / sigma) ** 2)
        w = w / w.sum(axis=1, keepdims=True)
        return 10.0 ** (w @ lev) * np.exp(1j * (w @ dph))

    record = {"n_periods": int(sel.sum()), "level_median": float(10 ** np.median(lev)),
              "level_min": float(10 ** lev.min()), "level_max": float(10 ** lev.max()),
              "phase_median_deg": float(np.degrees(np.median(dph))), "phase_min_deg": float(np.degrees(dph.min())),
              "phase_max_deg": float(np.degrees(dph.max()))}
    return factor, record


def merge_shortend(out, short_edi, long_edi, align: str = "qld", band=ALIGN_BAND, sigma: float = SIGMA_DEX,
                   site: str | None = None, tag: str | None = None, argv: list[str] | None = None) -> int:
    """Write the full band: the short-period product (10 Hz) below the long product's first period, the long above.

    Per part, the short product's rows at its periods below the long product's first usable period in that part
    (2 LOG_TOL below it), the long product's rows from that period on. `short_edi` is one EDI, or a mapping of part
    (xy, yx, tipper) to EDI when the parts have short sources of their own (a mode's health window applies to the
    10 Hz record as to the 1 Hz one). With `align` "qld" each short source's x row
    and y row (values and errors) are first multiplied by `align_factor` of that row, computed from that source
    (errors by the factor's modulus), and written beside `out` as <out stem>_shortend_aligned_<parts>.edi, the
    file merged; the tipper is never scaled (it holds no electric field). With "none" the short sources are merged
    as they are. The products are different stations (FR05 and FR05L), so merge_best runs with force and records
    the mismatch; the long product is listed first and gives the station metadata.

    Returns:
        int: 0 when written, 2 when refused (unknown align, a missing file, no common periods to align on).
    """
    mb = merge_best()
    if align not in ("qld", "none"):
        print(f"ERROR align {align!r}: qld or none", file=sys.stderr)
        return 2
    short_by = ({p: Path(short_edi[p]).resolve() for p in PARTS if p in short_edi} if isinstance(short_edi, dict)
                else {p: Path(short_edi).resolve() for p in PARTS})
    long_edi, out = Path(long_edi).resolve(), Path(out).resolve()
    for path in [long_edi, *short_by.values()]:
        if not path.is_file():
            print(f"ERROR {path}: no such file", file=sys.stderr)
            return 2
    l_tf = mb.read_tf(long_edi)
    tfs = {path: mb.read_tf(path) for path in set(short_by.values())}
    record = {"align": align, "band_s": [float(band[0]), float(band[1])], "sigma_dex": float(sigma),
              "short": {p: str(v) for p, v in short_by.items()}, "long": str(long_edi), "first_long_s": {},
              "factor": {}, "aligned_edi": {}}
    merged_src = dict(short_by)
    if align == "qld":
        by_file: dict[Path, list[str]] = {}
        for p in ("xy", "yx"):
            if p in short_by:
                by_file.setdefault(short_by[p], []).append(p)
        out.parent.mkdir(parents=True, exist_ok=True)
        for path, parts in by_file.items():
            a_tf = copy.deepcopy(tfs[path])
            period = np.asarray(a_tf.period, dtype=float)
            z = np.asarray(a_tf.impedance.data).copy()
            err = np.asarray(a_tf.impedance_error.data, dtype=float).copy()
            for p in parts:
                try:
                    factor, rec = align_factor(tfs[path], l_tf, p, band, sigma)
                except ValueError as exc:
                    print(f"ERROR {exc}", file=sys.stderr)
                    return 2
                c = factor(period)
                row = 0 if p == "xy" else 1
                z[:, row, :] *= c[:, None]
                err[:, row, :] *= np.abs(c)[:, None]
                record["factor"][p] = rec
            a_tf.impedance, a_tf.impedance_error = z, err
            aligned = out.with_name(f"{out.stem}_shortend_aligned_{''.join(parts)}.edi")
            with mb.hyphenated_station_ids():
                a_tf.write(fn=str(aligned), file_type="edi")
            _sp, side = mb.read_sidecar(path)
            side = dict(side or {})
            side.update({"aligned_from": str(path), "aligned_parts": parts, "align": align,
                         "band_s": record["band_s"], "sigma_dex": record["sigma_dex"],
                         "factor": {p: record["factor"][p] for p in parts}})
            aligned.with_suffix(".json").write_text(json.dumps(side, indent=2, default=str) + "\n", encoding="utf-8")
            for p in parts:
                merged_src[p] = aligned
                record["aligned_edi"][p] = str(aligned)
    recipe = {}
    info = [f"mt_workbench.shortend_align={align}" + (f" (factor over {band[0]:g}-{band[1]:g} s, Gaussian {sigma:g} "
                                                       f"decade)" if align == "qld" else "")]
    for p in PARTS:
        pl, zl, _e = mb.mode_row(l_tf, p)
        good = mb.usable(zl)
        if not good.any():
            continue
        pl = np.asarray(pl, dtype=float)
        first = float(pl[good].min())
        recipe[p] = [{"edi": str(long_edi), "pmin": first, "pmax": float(pl[good].max())}]
        record["first_long_s"][p] = first
        if p in merged_src:
            src = merged_src[p]
            ps = np.asarray(mb.mode_row(tfs[short_by[p]], p)[0], dtype=float)
            if ps.min() < first * 10 ** (-2 * mb.LOG_TOL):
                recipe[p].append({"edi": str(src), "pmin": float(ps.min()), "pmax": first * 10 ** (-2 * mb.LOG_TOL)})
            info.append(f"mt_workbench.shortend_{p}={src.name} below {first:g} s, {long_edi.name} from it")
    for p, f in record["factor"].items():
        info.append(f"mt_workbench.shortend_factor_{p}=level {f['level_median']:.4f} (median), phase "
                    f"{f['phase_median_deg']:+.3f} deg (median)")
    recipe["note"] = f"short end ({align}) onto the long product"
    return mb.merge_files(out, recipe, tag=tag, force=True, site=site, argv=argv, extra_info=info,
                          extra={"shortend": record})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("out", help="merged EDI to write")
    for role in ("short", "long"):
        for part in PARTS:
            p.add_argument(f"--{role}-{part}", default=None, metavar="EDI",
                           help=f"the {role} source of the {part}" + (" (optional)" if part == "tipper" else ""))
    p.add_argument("--rule", required=True, help="fixed:<s>, longest:<floor s> or contiguous:<floor s>")
    p.add_argument("--site", default=None)
    p.add_argument("--tag", default=None)
    for part in PARTS:
        p.add_argument(f"--window-{part}", default=None, metavar="TEXT", help=f"the {part} sources' health window")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    short = {k: getattr(args, f"short_{k}") for k in PARTS if getattr(args, f"short_{k}")}
    long = {k: getattr(args, f"long_{k}") for k in PARTS if getattr(args, f"long_{k}")}
    windows = {k: getattr(args, f"window_{k}") for k in PARTS if getattr(args, f"window_{k}")}
    return merge_windows(args.out, short, long, args.rule, site=args.site, tag=args.tag, windows=windows,
                         argv=list(sys.argv if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
