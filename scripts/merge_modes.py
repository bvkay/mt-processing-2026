# -*- coding: utf-8 -*-
"""
Merge the xy row of one EDI and the yx row of another into one EDI

When one electric channel of a site is usable over the whole record and the
other only over a window, the pair is processed twice (process_rr.py), once
over the full record and once over the window. This script writes one EDI
from the two products: the x row (Zxx, Zxy and their errors) and the tipper
from the --xy product, the y row (Zyx, Zyy and their errors) from the --yx
product, on the --xy product's periods. The --xy product's station
metadata, location, runs and header are kept; its INFO block's processing
parameters are replaced by ``crust.*`` lines naming the two sources and the
sidecar.

The y row is placed on the xy periods as follows. A --yx period whose y row
is finite and nonzero is usable (mt_metadata reads the EDI's EMPTY value,
1e+32, back as 0). An xy period within LOG_TOL of a usable --yx period in
log10 period takes that period's values; one between two usable periods
takes values interpolated linearly in log10 period, real and imaginary
parts separately and the errors likewise; one outside their range takes
NaN, which mt_metadata's EDI writer stores as the EMPTY value and its
reader returns as 0 with a zero error.

The station ids of the two EDIs must agree, and so must the remotes named
by their sidecars (``<stem>.json`` beside each EDI) when both are present;
--force merges them regardless. ``OUT.json`` beside the output records the
two sources (paths, station, periods, and the tag, window, remote and masks
of their sidecars), the rule, the counts of xy periods copied, interpolated
and set to NaN, and the UTC time of the merge, in the indented JSON of
process_rr.py's sidecar. Exit status: 0 written, 2 when a source is
missing, the --yx product has no usable y row, or the stations or remotes
differ without --force. `merge_files` is the same merge for a caller in
Python, scripts/campaign.py's merged products among them.

Usage:
    python scripts/merge_modes.py OUT.edi --xy A.edi --yx B.edi [--tag TAG] [--force]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

import crust  # noqa: E402

X_ROW, Y_ROW = 0, 1  # impedance output index of ex and ey
LOG_TOL = 1e-5  # log10-period distance within which two periods are the same
ISO = "%Y-%m-%dT%H:%M:%SZ"
SOURCE_KEYS = ("local", "remote", "tag", "window", "masks", "mask_origins", "masks_ignored", "engine", "started",
               "edi")
RULE = ("x row (Zxx, Zxy and errors) and tipper from the xy source; y row (Zyx, Zyy and errors) from the yx "
        "source on the xy source's periods: copied at a period shared within LOG_TOL in log10 period, "
        "interpolated linearly in log10 period between two usable yx periods (real and imaginary parts "
        "separately, errors likewise), NaN outside their range")


def read_tf(path: Path) -> TF:
    """Read an EDI into an mt_metadata TF."""
    tf = TF(fn=str(path))
    tf.read()
    return tf


def read_sidecar(edi_path: Path) -> tuple[Path | None, dict | None]:
    """Return the path and contents of the ``.json`` sidecar beside an EDI, (None, None) without one."""
    path = Path(edi_path).with_suffix(".json")
    if not path.exists():
        return None, None
    with open(path, encoding="utf-8") as handle:
        return path, json.load(handle)


def row_of(tf: TF, row: int) -> tuple[np.ndarray, np.ndarray]:
    """Return one output row of a TF's impedance and its errors.

    Args:
        tf (TF): The transfer function.
        row (int): Output index, X_ROW (ex) or Y_ROW (ey).

    Returns:
        tuple: ``(z, err)``, (n, 2) complex and (n, 2) float over the
        input channels hx, hy; err is zero when the TF carries no errors.
    """
    z = np.asarray(tf.impedance.data)[:, row, :].astype(complex)
    if tf.impedance_error is None:
        return z, np.zeros(z.shape)
    return z, np.asarray(tf.impedance_error.data, dtype=float)[:, row, :]


def usable(z: np.ndarray) -> np.ndarray:
    """Flag the periods of an (n, 2) impedance row that are finite and nonzero in both components."""
    return np.all(np.isfinite(z), axis=1) & np.all(z != 0, axis=1)


def row_on_grid(p_src: np.ndarray, z_src: np.ndarray, e_src: np.ndarray,
                p_dst: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Place an impedance row and its errors on another period grid.

    Args:
        p_src (np.ndarray): (m,) source periods in s, each usable.
        z_src (np.ndarray): (m, 2) complex impedance row.
        e_src (np.ndarray): (m, 2) errors.
        p_dst (np.ndarray): (n,) periods to place the row on, in s.

    Returns:
        tuple: ``(z, err, kind)``: (n, 2) complex and (n, 2) float, NaN
        outside the source range, and (n,) str, "copied", "interpolated"
        or "nan" per destination period.
    """
    order = np.argsort(p_src)
    x_src, z_src, e_src = np.log10(p_src)[order], z_src[order], e_src[order]
    x_dst = np.log10(np.asarray(p_dst, dtype=float))
    z_out = np.full((x_dst.size, 2), np.nan, dtype=complex)
    e_out = np.full((x_dst.size, 2), np.nan)
    kind = np.full(x_dst.size, "nan", dtype=object)
    if x_src.size == 0:
        return z_out, e_out, kind
    gap = np.abs(x_dst[:, None] - x_src[None, :])
    nearest = gap.argmin(axis=1)
    copied = gap[np.arange(x_dst.size), nearest] <= LOG_TOL
    inside = (x_dst > x_src[0]) & (x_dst < x_src[-1]) & ~copied
    z_out[copied], e_out[copied] = z_src[nearest[copied]], e_src[nearest[copied]]
    for c in range(2):
        z_out[inside, c] = (np.interp(x_dst[inside], x_src, z_src[:, c].real)
                            + 1j * np.interp(x_dst[inside], x_src, z_src[:, c].imag))
        e_out[inside, c] = np.interp(x_dst[inside], x_src, e_src[:, c])
    kind[copied], kind[inside] = "copied", "interpolated"
    return z_out, e_out, kind


def merge(tf_xy: TF, tf_yx: TF) -> tuple[TF, dict]:
    """Replace the y row of `tf_xy` with the y row of `tf_yx` on tf_xy's periods.

    Args:
        tf_xy (TF): Source of the x row, the tipper, the periods and the
            metadata; modified and returned.
        tf_yx (TF): Source of the y row.

    Returns:
        tuple: ``(tf, counts)``: the merged TF and a dict of ``n_periods``,
        ``n_copied``, ``n_interpolated``, ``n_nan``, ``yx_usable``,
        ``yx_left_out`` (--yx periods whose y row is zero or non-finite)
        and ``yx_usable_range``, plus ``kind``, the (n,) placement of each
        period.

    Raises:
        ValueError: If `tf_yx` has no usable y row.
    """
    p_yx = np.asarray(tf_yx.period, dtype=float)
    z_yx, e_yx = row_of(tf_yx, Y_ROW)
    ok = usable(z_yx)
    if not ok.any():
        raise ValueError("the yx source has no period with a finite, nonzero y row")
    p_xy = np.asarray(tf_xy.period, dtype=float)
    z_row, e_row, kind = row_on_grid(p_yx[ok], z_yx[ok], e_yx[ok], p_xy)
    z = np.asarray(tf_xy.impedance.data).astype(complex)
    if tf_xy.impedance_error is None:
        err = np.zeros(z.shape)
    else:
        err = np.asarray(tf_xy.impedance_error.data, dtype=float).copy()
    z[:, Y_ROW, :], err[:, Y_ROW, :] = z_row, e_row
    tf_xy.impedance = z
    tf_xy.impedance_error = err
    counts = dict(n_periods=int(p_xy.size), n_copied=int((kind == "copied").sum()),
                  n_interpolated=int((kind == "interpolated").sum()), n_nan=int((kind == "nan").sum()),
                  yx_usable=int(ok.sum()), yx_left_out=int((~ok).sum()),
                  yx_usable_range=[float(p_yx[ok].min()), float(p_yx[ok].max())], kind=kind)
    return tf_xy, counts


def mismatches(tf_xy: TF, tf_yx: TF, side_xy: dict | None, side_yx: dict | None) -> list[str]:
    """List how the two sources disagree on station or remote.

    Args:
        tf_xy (TF): The xy source.
        tf_yx (TF): The yx source.
        side_xy (dict | None): The xy source's sidecar.
        side_yx (dict | None): The yx source's sidecar.

    Returns:
        list[str]: One line per disagreement; empty when they agree.
    """
    out = []
    st_xy, st_yx = tf_xy.station_metadata.id, tf_yx.station_metadata.id
    if st_xy != st_yx:
        out.append(f"stations differ: xy {st_xy}, yx {st_yx}")
    if side_xy is not None and side_yx is not None:
        r_xy, r_yx = side_xy.get("remote"), side_yx.get("remote")
        if r_xy != r_yx:
            out.append(f"remotes differ: xy {r_xy}, yx {r_yx}")
    return out


def _span(periods) -> str:
    """Format a period range as "lo .. hi s"."""
    p = np.asarray(periods, dtype=float)
    return f"{p.min():.4g} .. {p.max():.4g} s" if p.size else "none"


def _runs_of(mask: np.ndarray, periods: np.ndarray) -> str:
    """Format the period ranges of the flagged periods, contiguous in period order."""
    order = np.argsort(periods)
    flags, p = mask[order], periods[order]
    parts, start = [], None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        if start is not None and (not flag or i == flags.size - 1):
            end = i if flag else i - 1
            parts.append(_span(p[start:end + 1]))
            start = None
    return ", ".join(parts)


def source_entry(edi: Path, tf: TF, sidecar_path: Path | None, sidecar: dict | None) -> dict:
    """Describe one source for the merged sidecar.

    Args:
        edi (Path): The source EDI.
        tf (TF): The source as read.
        sidecar_path (Path | None): Its sidecar.
        sidecar (dict | None): The sidecar's contents.

    Returns:
        dict: ``edi``, ``station``, ``n_periods``, ``period_range`` and
        ``sidecar`` (None, or its path and the SOURCE_KEYS it holds).
    """
    p = np.asarray(tf.period, dtype=float)
    side = None
    if sidecar is not None:
        side = {"path": str(sidecar_path), **{k: sidecar[k] for k in SOURCE_KEYS if k in sidecar}}
    return {"edi": str(edi), "station": tf.station_metadata.id, "n_periods": int(p.size),
            "period_range": [float(p.min()), float(p.max())], "sidecar": side}


def _engine(side_xy: dict | None, side_yx: dict | None) -> str | None:
    """Name the engines of the two sources: the shared one, "xy/yx" when they differ, None without sidecars."""
    if side_xy is None or side_yx is None:
        return None
    e_xy, e_yx = (str(s.get("engine") or "aurora") for s in (side_xy, side_yx))
    return e_xy if e_xy == e_yx else f"{e_xy}/{e_yx}"


def build_sidecar(out: Path, tag: str | None, force: bool, argv: list[str], tf_xy: TF, sources: dict,
                  counts: dict, found: list[str], created: str, remote: str | None, engine: str | None) -> dict:
    """Build the merged product's sidecar.

    Args:
        out (Path): The merged EDI.
        tag (str | None): The label given with --tag.
        force (bool): Whether --force was given.
        argv (list[str]): The command line recorded.
        tf_xy (TF): The merged TF.
        sources (dict): ``{"xy": source_entry, "yx": source_entry}``.
        counts (dict): Output of `merge`.
        found (list[str]): Output of `mismatches`, merged under --force.
        created (str): UTC time of the merge.
        remote (str | None): The remote of the sources' sidecars.
        engine (str | None): Output of `_engine`.

    Returns:
        dict: The sidecar content.
    """
    side = {
        "local": tf_xy.station_metadata.id,
        "remote": remote,
        "created": created,
        "tag": tag,
        "edi": out.name,
        "merge": {"rule": RULE, "log10_period_tolerance": LOG_TOL,
                  **{k: v for k, v in counts.items() if k != "kind"},
                  "tipper": "xy" if tf_xy.has_tipper() else None},
        "sources": sources,
        "forced": bool(force),
        "mismatches": found,
        "argv": list(argv),
        "versions": {"crust": crust.__version__, "mt_metadata": importlib.metadata.version("mt_metadata")},
    }
    if engine is not None:
        side["engine"] = engine
    return side


def info_lines(side: dict) -> list[str]:
    """Build the ``crust.*`` lines of the merged EDI's INFO block."""
    return [f"crust.version={side['versions']['crust']}", f"crust.merged={side['created']}",
            f"crust.tag={side['tag'] or ''}", f"crust.merge_xy={Path(side['sources']['xy']['edi']).name}",
            f"crust.merge_yx={Path(side['sources']['yx']['edi']).name}",
            f"crust.sidecar={Path(side['edi']).with_suffix('.json').name}"]


def merge_files(out, xy, yx, tag: str | None = None, force: bool = False, argv: list[str] | None = None) -> int:
    """Write the merged EDI and its sidecar from two EDI files, printing what was taken from each.

    scripts/campaign.py calls it for a site's windowed products.

    Args:
        out (str | Path): Merged EDI to write; the sidecar goes beside it as
            .json.
        xy (str | Path): EDI giving the x row, the tipper and the periods.
        yx (str | Path): EDI giving the y row.
        tag (str | None): Label recorded in the sidecar and the INFO block.
        force (bool): Merge sources whose stations or remotes differ.
        argv (list[str] | None): Command line recorded in the sidecar;
            sys.argv when None.

    Returns:
        int: 0 when written, 2 when a source is missing, the yx source has
        no usable y row, or the sources differ in station or remote without
        `force`.
    """
    out, a_path, b_path = Path(out).resolve(), Path(xy).resolve(), Path(yx).resolve()
    for path in (a_path, b_path):
        if not path.is_file():
            print(f"ERROR {path}: no such file", file=sys.stderr)
            return 2
    tf_xy, tf_yx = read_tf(a_path), read_tf(b_path)
    side_a_path, side_a = read_sidecar(a_path)
    side_b_path, side_b = read_sidecar(b_path)

    found = mismatches(tf_xy, tf_yx, side_a, side_b)
    if found and not force:
        for line in found:
            print(f"ERROR {line} ({a_path.name} and {b_path.name}); --force merges them", file=sys.stderr)
        return 2
    for line in found:
        print(f"WARNING {line}: merged under --force")
    if side_a is None or side_b is None:
        missing = " and ".join(p.name for p, s in ((a_path, side_a), (b_path, side_b)) if s is None)
        print(f"remote: unchecked, no sidecar beside {missing}")

    sources = {"xy": source_entry(a_path, tf_xy, side_a_path, side_a),
               "yx": source_entry(b_path, tf_yx, side_b_path, side_b)}
    try:
        tf, counts = merge(tf_xy, tf_yx)
    except ValueError as exc:
        print(f"ERROR {b_path.name}: {exc}", file=sys.stderr)
        return 2

    p = np.asarray(tf.period, dtype=float)
    kind = counts["kind"]
    tipper = ", tipper" if tf.has_tipper() else ""
    print(f"xy row (Zxx, Zxy{tipper}) <- {a_path.name}: {p.size} periods, {_span(p)}")
    placed = f"{counts['n_copied']} copied, {counts['n_interpolated']} interpolated, {counts['n_nan']} NaN"
    if counts["n_nan"]:
        placed += f" ({_runs_of(kind == 'nan', p)})"
    left = f", {counts['yx_left_out']} left out as empty" if counts["yx_left_out"] else ""
    print(f"yx row (Zyx, Zyy) <- {b_path.name}: {counts['yx_usable']} usable periods{left}, "
          f"{_span(counts['yx_usable_range'])}; on the xy periods {placed}")

    created = dt.datetime.now(dt.timezone.utc).strftime(ISO)
    remote = (side_a or {}).get("remote", (side_b or {}).get("remote"))
    side = build_sidecar(out, tag, force, sys.argv if argv is None else argv, tf, sources, counts, found, created,
                         remote, _engine(side_a, side_b))
    tf.station_metadata.transfer_function.processing_parameters = info_lines(side)
    out.parent.mkdir(parents=True, exist_ok=True)
    tf.write(fn=str(out), file_type="edi")
    side_path = out.with_suffix(".json")
    side_path.write_text(json.dumps(side, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"edi: {out}")
    print(f"sidecar: {side_path}")
    return 0


def main(argv=None) -> int:
    """Merge the xy row of one EDI and the yx row of another.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: The status of `merge_files`.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("out", help="merged EDI to write; its sidecar is written beside it as .json")
    parser.add_argument("--xy", required=True, help="EDI giving the x row (Zxx, Zxy), the tipper and the periods")
    parser.add_argument("--yx", required=True, help="EDI giving the y row (Zyx, Zyy)")
    parser.add_argument("--tag", default=None, help="label recorded in the sidecar and the INFO block")
    parser.add_argument("--force", action="store_true", help="merge sources whose stations or remotes differ")
    args = parser.parse_args(argv)
    return merge_files(args.out, args.xy, args.yx, tag=args.tag, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
