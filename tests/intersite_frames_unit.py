# -*- coding: utf-8 -*-
"""
Unit test for the site frames an inter-site product records

The local's and the base's azimuth_ex, azimuth_ey, layout_north and
declination, as survey.yaml declares them, are written into the sidecar
and the h5 of a T product, and are not applied: the tensor stays in each
site's channels as recorded. Two scratch surveys share one workspace of
20 min archives at 100 Hz (tests/intersite_flags_unit.py's record): one
declares turned layouts at both sites, the other declares nothing beyond
the defaults, and scripts/process_intersite.py runs on each.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. either run exits non-zero;
2. the sidecar's frames block or the h5's frames attribute lacks the local
   or the base, or any of their four values differs from survey.yaml's
   (L: 10, 100, geographic, 7.5; B: 350, 80, magnetic, -3.25), or the
   block does not say the frames are not applied;
3. the run on the undeclared survey records other values than the
   defaults (0, 90, magnetic, no declination) or says a declared site has
   no entry;
4. any T, error or arg(det)/2 cell of the CSV differs between the two
   runs, so a declared frame changed the tensor (a rotation of either
   site's channels by the declared azimuths moves T by tens of percent).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_flags_unit import short_record  # noqa: E402
from intersite_unit import T_START, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("intersite_frames_unit")
DECLARED = {"L": {"azimuth_ex": 10.0, "azimuth_ey": 100.0, "layout_north": "geographic", "declination": 7.5},
            "B": {"azimuth_ex": 350.0, "azimuth_ey": 80.0, "layout_north": "magnetic", "declination": -3.25}}
DEFAULT = {"azimuth_ex": 0.0, "azimuth_ey": 90.0, "layout_north": "magnetic", "declination": None}
STEM = "L_te-B_rr-R"

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def survey_yaml(name: str, work: Path, root: Path, declared: bool) -> Path:
    """Write a scratch survey.yaml over the shared workspace; return its path."""
    def entry(site, lat):
        extra = "".join(f", {k}: {v}" for k, v in DECLARED[site].items()) if declared and site in DECLARED else ""
        return f"  {site}: {{latitude: {lat}, longitude: 137.0{extra}}}\n"

    text = (f"name: frames_{name}\ninstrument: lemi423\nsample_rate: 100\ndata_root: {root.as_posix()}\n"
            f"workspace: {work.as_posix()}\ndefaults:\n  channels: [ex, ey, hx, hy]\nsites:\n"
            + entry("L", -31.0) + entry("B", -31.01) + entry("R", -31.5)
            + "processing:\n  min_period: 0.04\n  max_period: 200.0\n  periods_per_decade: 10.0\n")
    path = SCRATCH / name / "survey.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run(yaml_path: Path, out: Path) -> subprocess.CompletedProcess:
    """Run the script for L on B referenced to R."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "L", "B", "--kind", "telluric", "--remote",
                           "R", "--out-dir", str(out)], capture_output=True, text=True, cwd=REPO)


def site_values(block: dict, site: str) -> dict:
    """Return a site's four frame values from a frames block ({} when absent)."""
    entry = ((block or {}).get("sites") or {}).get(site) or {}
    return {k: entry.get(k, "absent") for k in DEFAULT}


def main() -> int:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    root, work = SCRATCH / "raw", SCRATCH / "work"
    root.mkdir(parents=True)
    spec, _arrays, _scheme = short_record()
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    for site in ("L", "B", "R"):
        write_site(work, site, spec, T_START, spec["n"])
    out = {}
    for name, declared in (("declared", True), ("plain", False)):
        out[name] = SCRATCH / name / "out"
        res = run(survey_yaml(name, work, root, declared), out[name])
        if not check(res.returncode == 0, f"1 {name}: exit {res.returncode}"):
            print(res.stderr[-3000:])
            return 1

    side = json.loads((out["declared"] / f"{STEM}.json").read_text(encoding="utf-8"))
    with h5py.File(out["declared"] / f"{STEM}.h5", "r") as f:
        attr = f.attrs.get("frames")
    h5_block = json.loads(attr) if attr is not None else {}
    for label, block in (("sidecar", side.get("frames")), ("h5", h5_block)):
        got = {s: site_values(block, s) for s in DECLARED}
        not_applied = (block or {}).get("applied") is False
        check(got == DECLARED and not_applied,
              f"2 {label}: frames {got} (declared {DECLARED}); applied {(block or {}).get('applied')!r}")

    plain = json.loads((out["plain"] / f"{STEM}.json").read_text(encoding="utf-8")).get("frames")
    got = {s: site_values(plain, s) for s in DECLARED}
    entries = all(((plain or {}).get("sites") or {}).get(s, {}).get("entry") is True for s in DECLARED)
    check(got == {s: DEFAULT for s in DECLARED} and entries,
          f"3 undeclared: frames {got}; survey.yaml entries named {entries}")

    a = pd.read_csv(out["declared"] / f"{STEM}.csv", dtype=str)
    b = pd.read_csv(out["plain"] / f"{STEM}.csv", dtype=str)
    cols = [f"T_{el}_{p}" for el in intersite.ELEMENTS for p in ("re", "im", "err")] + \
        ["half_arg_det_deg", "half_arg_det_err_deg"]
    same = len(a) == len(b) and a[cols].fillna("nan").equals(b[cols].fillna("nan"))
    check(same, f"4 T, errors and arg(det)/2 identical as text in {len(a)} rows with and without the declared "
                f"frames")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
