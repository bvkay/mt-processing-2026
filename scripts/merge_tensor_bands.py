# -*- coding: utf-8 -*-
"""
Stitch two inter-site tensor products of one pair by band into one wide-band product

A Phoenix receiver records a continuous stream (150 Hz) and 24 kHz bursts.
scripts/process_intersite.py estimates T (or M) on each: the burst sites
(``<site>H``, `bursts_of:`) on their compact grid, from 1/6000 s to about
0.04 s; the recorded sites from the survey's `min_period` up. When the
continuous product's `min_period` is 4**(m/6) times the burst product's
(4**(22/6)/6000 = 0.026878315731 s for 150 Hz against 24 kHz), the two band
layouts share their band edges, and the products overlap in the bands both
cover. This script takes the burst product's rows below the first shared
band and the continuous product's from that band on (the continuous record
holds thousands of times more windows there), keeps each row's own
jackknife error, and checks the shared bands: for each shared band, each
tensor element and arg(det)/2, the difference over the two errors combined
is a z value, and **the check fails if any |z| exceeds 2**. A failure stops
the merge (exit 2) unless `--accept-disagreement` is given, which is then
recorded.

Refused (exit 2): products of different kinds; burst sites whose
`bursts_of` parents are not the continuous product's local, base and
reference; different estimator settings (method, r0, jackknife groups);
shared band edges that differ by more than 1e-9 relative (the message gives
the aligned `min_period`); no shared band; archives whose
`phoenix_stamp_correction_s` differ (mt_workbench.phoenix).

Writes `<continuous stem>_wide.csv` (the rows with `source` and
`sample_rate` columns), `.h5`, `.png` and `.json` (both parents with their
sidecar's SHA-256, the rule, each band's source, the overlap table with its
z values and verdict, the failure criterion and argv) beside the
continuous product, or in `--out-dir`.

Usage:
    python scripts/merge_tensor_bands.py <bursts sidecar .json> <continuous sidecar .json>
        [--accept-disagreement] [--out-dir DIR]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from mt_workbench import intersite  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

EDGE_TOLERANCE = 1e-9  # relative difference of two band edges taken as the same edge
Z_LIMIT = 2.0  # a shared band fails the overlap check when any |z| exceeds this
RULE = ("burst product for the bands below the first band both products share; continuous product from that "
        "band on; each row keeps its own jackknife error")
CRITERION = (f"fails if any |z| > {Z_LIMIT:g} in a shared band, z = |a - b| / sqrt(sigma_a^2 + sigma_b^2) for each "
             f"tensor element and for arg(det)/2")


class Refused(ValueError):
    """A merge refused: exit 2."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("bursts", help="the burst product's sidecar (.json) of scripts/process_intersite.py")
    p.add_argument("continuous", help="the continuous product's sidecar (.json)")
    p.add_argument("--accept-disagreement", action="store_true",
                   help="write the merge although the overlap check fails (recorded)")
    p.add_argument("--out-dir", default=None, metavar="DIR", help="where to write (in use: the continuous product's)")
    return p


def load(sidecar: Path) -> dict:
    """Read a product: its sidecar, the estimate from its h5 and the sidecar's SHA-256."""
    sidecar = Path(sidecar)
    raw = sidecar.read_bytes()
    meta = json.loads(raw)
    est, letter, _attrs = intersite.read_h5(sidecar.parent / meta["h5"])
    return {"path": sidecar, "meta": meta, "est": est, "letter": letter, "stem": sidecar.stem,
            "sha256": hashlib.sha256(raw).hexdigest()}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= EDGE_TOLERANCE * max(abs(a), abs(b))


def aligned_min_period(burst_min_period: float, cont_min_period: float) -> float:
    """Return the continuous `min_period` nearest to the given one whose band edges fall on the burst layout's."""
    m = round(6 * math.log(cont_min_period / burst_min_period) / math.log(4))
    return burst_min_period * 4 ** (m / 6)


def shared_bands(burst: dict, cont: dict) -> list[tuple[int, int]]:
    """Return (burst row, continuous row) pairs of the bands with the same edges.

    Only bands each product formed count: a row with 0 windows is a band
    of the layout its record could not form, written as NaN, and is left
    out of the pairs, the overlap and the check below.

    Raises:
        Refused: When the products' frequency ranges overlap but a band of
            one in the overlap has no band of the other with the same
            edges, or when no band is shared.
    """
    b, c = burst["est"], cont["est"]
    rows_b, rows_c = np.flatnonzero(b.n_windows > 0), np.flatnonzero(c.n_windows > 0)
    pairs = []
    for i in rows_b:
        for j in rows_c:
            if _same(b.f_lo[i], c.f_lo[j]) and _same(b.f_hi[i], c.f_hi[j]):
                pairs.append((int(i), int(j)))
    lo, hi = max(b.f_lo[rows_b].min(), c.f_lo[rows_c].min()), min(b.f_hi[rows_b].max(), c.f_hi[rows_c].max())
    inside_b = [int(i) for i in rows_b if b.f_lo[i] >= lo * (1 - EDGE_TOLERANCE)
                and b.f_hi[i] <= hi * (1 + EDGE_TOLERANCE)]
    unmatched = [i for i in inside_b if i not in {p[0] for p in pairs}]
    if hi > lo and (unmatched or not pairs):
        mp_b = float(burst["meta"]["band_scheme"]["min_period"])
        mp_c = float(cont["meta"]["band_scheme"]["min_period"])
        raise Refused(f"the band edges of the two products do not coincide in their overlap ({lo:.6g}-{hi:.6g} Hz): "
                      f"the continuous min_period {mp_c!r} s is not 4**(m/6) times the burst product's {mp_b!r} s; "
                      f"the aligned min_period is {aligned_min_period(mp_b, mp_c)!r} s")
    if not pairs:
        raise Refused("the two products share no band: their periods do not overlap")
    return pairs


def check_pair(burst: dict, cont: dict, survey: Survey | None) -> None:
    """Refuse products that are not the same pair, kind and estimator.

    Raises:
        Refused: As the module docstring lists.
    """
    bm, cm = burst["meta"], cont["meta"]
    if bm["kind"] != cm["kind"]:
        raise Refused(f"the kinds differ: {bm['kind']} (bursts) and {cm['kind']} (continuous)")
    keys = ("method", "r0", "jackknife_groups")
    eb, ec = ({k: m["estimator"].get(k) for k in keys} for m in (bm, cm))
    if eb != ec:
        raise Refused(f"the estimator settings differ: {eb} (bursts) and {ec} (continuous)")
    sites_b = (bm["local"], bm["base_site"], (bm["reference"] or {}).get("site"))
    sites_c = (cm["local"], cm["base_site"], (cm["reference"] or {}).get("site"))
    if None in sites_b or None in sites_c:
        raise Refused("a stack is not a site: the merge takes products with a named base and a named reference")
    parents = tuple(survey.bursts_parent(s) for s in sites_b) if survey is not None else (None,) * 3
    if parents != sites_c:
        raise Refused(f"the burst product's sites {sites_b} are bursts of {parents}, and the continuous product's "
                      f"local, base and reference are {sites_c}")


def stamp_corrections(product: dict) -> dict:
    """Return the `phoenix_stamp_correction_s` each of a product's three archives records."""
    from mt_workbench.phoenix import archive_stamp_correction

    meta = product["meta"]
    out = {}
    for key, site in (("local_archive", meta["local"]), ("base_archive", meta["base_site"]),
                      ("remote_archive", (meta["reference"] or {}).get("site"))):
        path = Path((meta.get(key) or {}).get("path", ""))
        if not path.is_file():
            raise Refused(f"{product['stem']}: {key} {path} not found; the stamp corrections cannot be compared")
        out[f"{site} ({path.name})"] = archive_stamp_correction(path, site)
    return out


def overlap_table(burst: dict, cont: dict, pairs) -> list[dict]:
    """Compare the shared bands: z per element and for arg(det)/2 (see CRITERION)."""
    b, c = burst["est"], cont["est"]
    rows = []
    for i, j in pairs:
        z = np.abs(b.tensor[i] - c.tensor[j]) / np.sqrt(b.sigma[i] ** 2 + c.sigma[j] ** 2)
        za = abs(b.half_arg_deg[i] - c.half_arg_deg[j]) / math.hypot(b.half_arg_err_deg[i], c.half_arg_err_deg[j])
        values = [float(v) for v in z.ravel()] + [float(za)]
        ok = all(np.isfinite(values)) and max(values) <= Z_LIMIT
        rows.append({"period_s": float(c.period[j]), "f_lo": float(c.f_lo[j]), "f_hi": float(c.f_hi[j]),
                     "z_xx": values[0], "z_xy": values[1], "z_yx": values[2], "z_yy": values[3],
                     "z_half_arg": values[4], "windows_bursts": int(b.n_windows[i]),
                     "windows_continuous": int(c.n_windows[j]), "verdict": "pass" if ok else "fail"})
    return rows


def stitch(burst: dict, cont: dict, pairs):
    """Return the merged estimate and each row's source, shortest period first (see RULE)."""
    b, c = burst["est"], cont["est"]
    first = min(c.period[j] for _i, j in pairs)
    take_b = [i for i in range(b.period.size) if b.period[i] < first * (1 - EDGE_TOLERANCE)]
    take_c = [j for j in range(c.period.size) if c.period[j] >= first * (1 - EDGE_TOLERANCE)]
    fields = intersite.TensorEstimate.__dataclass_fields__
    merged = intersite.TensorEstimate(**{k: np.concatenate([getattr(b, k)[take_b], getattr(c, k)[take_c]])
                                         for k in fields})
    sources = ["bursts"] * len(take_b) + ["continuous"] * len(take_c)
    rates = [float(burst["meta"]["sample_rates"]["local"])] * len(take_b) + \
            [float(cont["meta"]["sample_rates"]["local"])] * len(take_c)
    order = np.argsort(merged.period, kind="stable")
    merged = intersite.TensorEstimate(**{k: getattr(merged, k)[order] for k in fields})
    return merged, [sources[k] for k in order], [rates[k] for k in order]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    started = dt.datetime.now().astimezone()
    try:
        burst, cont = load(Path(args.bursts)), load(Path(args.continuous))
        survey_yaml = (cont["meta"].get("survey_yaml") or {}).get("path")
        survey = Survey.from_yaml(survey_yaml) if survey_yaml else None
        check_pair(burst, cont, survey)
        pairs = shared_bands(burst, cont)
        stamps = {"bursts": stamp_corrections(burst), "continuous": stamp_corrections(cont)}
        values = {v for side in stamps.values() for v in side.values()}
        if len(values) > 1:
            raise Refused(f"the archives' phoenix_stamp_correction_s differ: {stamps}")
    except Refused as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    table = overlap_table(burst, cont, pairs)
    verdict = "pass" if all(r["verdict"] == "pass" for r in table) else "fail"
    for r in table:
        print(f"overlap {r['period_s']:.5f} s: z xx {r['z_xx']:.2f} xy {r['z_xy']:.2f} yx {r['z_yx']:.2f} "
              f"yy {r['z_yy']:.2f} arg(det)/2 {r['z_half_arg']:.2f}, windows {r['windows_bursts']} / "
              f"{r['windows_continuous']}: {r['verdict']}")
    if verdict == "fail" and not args.accept_disagreement:
        print(f"ERROR the overlap check fails ({CRITERION}): find the cause in the archives or the chains; "
              f"--accept-disagreement writes the merge anyway and records it", file=sys.stderr)
        return 2
    merged, sources, rates = stitch(burst, cont, pairs)
    letter = cont["letter"]
    out_dir = Path(args.out_dir) if args.out_dir else cont["path"].parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cont['stem']}_wide"
    frame = merged.frame(letter)
    frame["source"], frame["sample_rate"] = sources, rates
    csv = out_dir / f"{stem}.csv"
    frame.to_csv(csv, index=False, float_format="%.17g")
    h5 = intersite.write_h5(merged, letter, out_dir / f"{stem}.h5",
                            attrs={"source": sources, "rule": RULE, "overlap_verdict": verdict,
                                   "parents": [burst["stem"], cont["stem"]]})
    first = float(min(cont["est"].period[j] for _i, j in pairs))
    png = intersite.plot_estimate(merged, letter, out_dir / f"{stem}.png",
                                  title=f"{stem}: bursts below {first:.4f} s, continuous from it on")
    sidecar = {
        "kind": cont["meta"]["kind"], "tensor": letter, "local": cont["meta"]["local"],
        "base_site": cont["meta"]["base_site"], "reference": cont["meta"]["reference"],
        "parents": [{"role": role, "stem": p["stem"], "sidecar": str(p["path"]), "sha256": p["sha256"],
                     "archives": {k: p["meta"].get(k) for k in ("local_archive", "base_archive", "remote_archive")},
                     "sample_rate": p["meta"]["sample_rates"]["local"],
                     "min_period": p["meta"]["band_scheme"]["min_period"],
                     "window_samples": p["meta"]["estimator"].get("window_samples"),
                     "bands": int(p["est"].period.size)} for role, p in (("bursts", burst), ("continuous", cont))],
        "rule": RULE, "sources": [{"period_s": float(t), "source": s} for t, s in zip(merged.period, sources)],
        "overlap": table, "overlap_verdict": verdict, "failure_criterion": CRITERION,
        "accept_disagreement": bool(args.accept_disagreement), "stamp_corrections": stamps,
        "started": started.isoformat(), "argv": list(sys.argv if argv is None else ["merge_tensor_bands.py", *argv]),
        "csv": csv.name, "h5": Path(h5).name, "figure": Path(png).name,
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    print(f"wrote {csv.name}, {Path(h5).name}, {Path(png).name}, {stem}.json in {out_dir}: "
          f"{sources.count('bursts')} burst and {sources.count('continuous')} continuous bands; overlap {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
