# -*- coding: utf-8 -*-
"""
Unit test for scripts/merge_tensor_bands.py, the stitch of a burst and a continuous T product

M1: two synthetic products of one pair are written into scratch in the
form scripts/process_intersite.py writes them (an h5 through
`mt_workbench.intersite.write_h5` and a JSON sidecar): a burst product of
the sites AH, BH, CH (`bursts_of` A, B, C) on the 24 kHz layout
(min_period 1/6000 s, levels 0-3, to 0.038 s), and a continuous product of
A, B, C on the 150 Hz layout at min_period 4**(22/6)/6000 s. Both hold
T(f) = T0 e^{-i 2 pi f tau} with seeded noise of their stated sigma, and
six small MTH5 archives record the stamp correction of 1.0 s.

Usage:
    python tests/merge_tensor_bands_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - the consistent pair does not merge (exit 0), the merged rows below the
    first shared band are not exactly the burst product's, the rows from
    it on not exactly the continuous product's (the two shared bands
    included), the CSV lacks the `source` and `sample_rate` columns, or
    the sidecar's overlap verdict is not "pass" with two shared bands;
  - the pair with the burst product's shared bands moved by 5 sigma does
    not exit 2, or exits 0 without `--accept-disagreement` and 2 with it;
  - a continuous product at min_period 0.0268776 s (misaligned edges)
    does not exit 2 with the aligned min_period 0.0268783157 in the
    message;
  - a pair whose continuous local's archive records a stamp correction of
    0.0 s does not exit 2.

The mutation: with the shared bands taken from the burst product, the
row-source check must fail.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("merge_tensor_bands_unit")
ALIGNED = 4 ** (22 / 6) / 6000
T0 = np.array([[0.8, 0.3], [-0.2, 1.1]])
TAU = 1e-4  # s
SIGMA = 0.01
STAMP_LINE = "phoenix_stamp_correction_s: {v!r} s added to every time stamp"


def _load_script():
    spec = importlib.util.spec_from_file_location("merge_tensor_bands", REPO / "scripts" / "merge_tensor_bands.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_archive(path: Path, station: str, correction: float) -> Path:
    """Write an MTH5 archive holding one station whose provenance records a stamp correction."""
    from mth5.mth5 import MTH5

    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("MERGE")
        group = m.add_station(station, survey="MERGE")
        group.metadata.provenance.comments.value = STAMP_LINE.format(v=correction)
        group.write_metadata()
    finally:
        m.close_mth5()
    return path


def estimate_on(scheme: dict, levels, rng, shift_sigma: float = 0.0, shift_bands=()) -> intersite.TensorEstimate:
    """Return a synthetic TensorEstimate on a band scheme's bands of the given levels."""
    rows = sorted(((int(lv), float(lo), float(hi)) for lv, bands in scheme["band_edges"].items() if int(lv) in levels
                   for lo, hi in np.asarray(bands)), key=lambda r: -np.sqrt(r[1] * r[2]))
    level = np.array([r[0] for r in rows])
    f_lo, f_hi = np.array([r[1] for r in rows]), np.array([r[2] for r in rows])
    f = np.sqrt(f_lo * f_hi)
    tensor = T0[None] * np.exp(-2j * np.pi * f * TAU)[:, None, None]
    tensor = tensor + SIGMA / np.sqrt(2) * (rng.standard_normal(tensor.shape) + 1j * rng.standard_normal(tensor.shape))
    for k in range(f.size):
        if any(abs(f_lo[k] - a) <= 1e-9 * a and abs(f_hi[k] - b) <= 1e-9 * b for a, b in shift_bands):
            tensor[k] += shift_sigma * SIGMA * np.sqrt(2)
    det = tensor[:, 0, 0] * tensor[:, 1, 1] - tensor[:, 0, 1] * tensor[:, 1, 0]
    n = f.size
    return intersite.TensorEstimate(
        period=1 / f, f_lo=f_lo, f_hi=f_hi, f_mean=f, f_weighted=f, level=level, n_windows=np.full(n, 1000),
        n_harm=np.full(n, 4), n_groups=np.full(n, 20), tensor=tensor, sigma=np.full((n, 2, 2), SIGMA), det=det,
        abs_det_err=np.full(n, SIGMA), half_arg_deg=np.degrees(np.angle(det)) / 2, half_arg_err_deg=np.full(n, 0.5),
        coh_out=np.full((n, 2), 0.99), coh_in=np.full((n, 2), 0.99))


def write_product(folder: Path, stem: str, est, sites, rate: float, min_period: float, archives: dict,
                  survey_yaml: Path) -> Path:
    """Write a product as scripts/process_intersite.py does: the h5 and the sidecar."""
    intersite.write_h5(est, "T", folder / f"{stem}.h5")
    local, base, ref = sites
    sidecar = {"kind": "telluric", "tensor": "T", "local": local, "base_site": base,
               "reference": {"type": "site", "site": ref, "channels": ["hx", "hy"]},
               "estimator": {"engine": "mt_workbench.intersite", "method": "huber", "r0": intersite.R0,
                             "jackknife_groups": intersite.JACKKNIFE_GROUPS, "window_samples": 128},
               "band_scheme": {"min_period": min_period}, "sample_rates": {"survey": 150.0, "local": rate},
               "local_archive": {"path": str(archives[local])}, "base_archive": {"path": str(archives[base])},
               "remote_archive": {"path": str(archives[ref])}, "survey_yaml": {"path": str(survey_yaml)},
               "h5": f"{stem}.h5"}
    path = folder / f"{stem}.json"
    path.write_text(json.dumps(sidecar))
    return path


def setup(case: str, cont_min_period: float = ALIGNED, shift: float = 0.0, local_correction: float = 1.0):
    """Write one case's survey, archives and products; return the two sidecars."""
    folder = SCRATCH / case
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    survey_yaml = folder / "survey.yaml"
    survey_yaml.write_text(yaml.safe_dump({
        "name": "MERGE", "instrument": "phoenix", "sample_rate": 150, "data_root": str(folder),
        "sites": {"A": {}, "B": {}, "C": {}, "AH": {"bursts_of": "A", "sample_rate": 24000},
                  "BH": {"bursts_of": "B", "sample_rate": 24000}, "CH": {"bursts_of": "C", "sample_rate": 24000}}}))
    archives = {s: write_archive(folder / f"{s}.h5", s, local_correction if s == "A" else 1.0)
                for s in ("A", "B", "C", "AH", "BH", "CH")}
    rng = np.random.default_rng(7)
    burst_scheme = build_band_scheme(24000.0, min_period=1 / 6000, max_period=0.05)
    cont_scheme = build_band_scheme(150.0, min_period=cont_min_period, max_period=10.0)
    overlap = [(float(lo), float(hi)) for lo, hi in np.asarray(cont_scheme["band_edges"][0])
               if 1 / hi >= 0.0268 and 1 / lo <= 0.0428]
    burst = estimate_on(burst_scheme, range(4), rng, shift, overlap)
    cont = estimate_on(cont_scheme, cont_scheme["band_edges"].keys(), rng)
    b = write_product(folder, "AH_te-BH_rr-CH", burst, ("AH", "BH", "CH"), 24000.0, 1 / 6000, archives, survey_yaml)
    c = write_product(folder, "A_te-B_rr-C", cont, ("A", "B", "C"), 150.0, cont_min_period, archives, survey_yaml)
    return b, c, burst, cont


def run(module, argv) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main([str(a) for a in argv])
    return code, out.getvalue() + err.getvalue()


def check_merge(module) -> list[str]:
    """The consistent pair: exit 0, the rows by the rule, the columns and the verdict."""
    b, c, burst, cont = setup("consistent")
    code, text = run(module, [b, c])
    if code != 0:
        return [f"consistent pair: exit {code}: {text[-300:]}"]
    bad = []
    frame = pd.read_csv(c.parent / "A_te-B_rr-C_wide.csv")
    meta = json.loads((c.parent / "A_te-B_rr-C_wide.json").read_text())
    if not {"source", "sample_rate"} <= set(frame.columns):
        bad.append(f"CSV columns {list(frame.columns)[-4:]}")
    shared = [r for r in meta["overlap"]]
    if meta["overlap_verdict"] != "pass" or len(shared) != 2:
        bad.append(f"overlap {meta['overlap_verdict']} with {len(shared)} shared bands")
    first = min(r["period_s"] for r in shared) if shared else 0.0
    merged, _letter, _attrs = intersite.read_h5(c.parent / "A_te-B_rr-C_wide.h5")
    for k, period in enumerate(merged.period):
        source = frame["source"][k]
        if period < first * (1 - 1e-9):
            j = int(np.argmin(np.abs(burst.period - period)))
            want, label = burst.tensor[j], "bursts"
        else:
            j = int(np.argmin(np.abs(cont.period - period)))
            want, label = cont.tensor[j], "continuous"
        if source != label or not np.array_equal(merged.tensor[k], want):
            bad.append(f"row {period:.5f} s: source {source}, expected {label} and its tensor")
            break
    return bad


def main() -> None:
    from loguru import logger

    logger.remove()
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    module = _load_script()
    failures = check_merge(module)
    print(f"  consistent: {'ok' if not failures else failures}: bursts below the first shared band, continuous from "
          f"it on, two shared bands pass")

    b, c, _burst, _cont = setup("moved", shift=5.0)
    code, text = run(module, [b, c])
    code_accept, _ = run(module, [b, c, "--accept-disagreement"])
    if code != 2 or code_accept != 0:
        failures.append(f"moved by 5 sigma: exit {code}, with --accept-disagreement {code_accept}")
    print(f"  moved 5 sigma: exit {code} ({text.strip().splitlines()[-1][:90]}); accepted: exit {code_accept}")

    b, c, _burst, _cont = setup("misaligned", cont_min_period=0.0268776)
    code, text = run(module, [b, c])
    if code != 2 or "0.0268783157" not in text:
        failures.append(f"misaligned: exit {code}: {text[-200:]}")
    print(f"  misaligned edges: exit {code} ({text.strip()[-90:]})")

    b, c, _burst, _cont = setup("stamps", local_correction=0.0)
    code, text = run(module, [b, c])
    if code != 2 or "stamp_correction" not in text:
        failures.append(f"stamp corrections differ: exit {code}")
    print(f"  stamp corrections differ: exit {code}")

    kept = module.stitch
    module.stitch = lambda burst, cont, pairs: _stitch_from_bursts(kept, burst, cont, pairs)
    try:
        trip = check_merge(module)
    finally:
        module.stitch = kept
    assert trip, "mutation (shared bands from the burst product) did not trip"
    print(f"  mutation (shared bands from the burst product) tripped: {trip[0]}")
    if failures:
        print("\nFAIL  merge_tensor_bands_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    shutil.rmtree(SCRATCH)
    print("\nPASS  merge_tensor_bands_unit")


def _stitch_from_bursts(stitch, burst, cont, pairs):
    """The mutation: the shared bands' rows taken from the burst product instead of the continuous one."""
    merged, sources, rates = stitch(burst, cont, pairs)
    b = burst["est"]
    for k, period in enumerate(merged.period):
        i = int(np.argmin(np.abs(b.period - period)))
        if abs(b.period[i] - period) <= 1e-9 * period and sources[k] == "continuous":
            merged.tensor[k] = b.tensor[i]
            sources[k] = "bursts"
    return merged, sources, rates


if __name__ == "__main__":
    main()
