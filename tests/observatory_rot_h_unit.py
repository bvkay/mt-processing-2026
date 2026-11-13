# -*- coding: utf-8 -*-
"""
Unit test for scripts/observatory_rot_h.py: an observatory archive turned onto magnetic north in place

A synthetic 1 Hz observatory archive is written by the workbench's own
writer (`mt_workbench.observatory.to_mth5`, from IAGA-2002 day files in a
cache, as scripts/fetch_observatory.py writes it): two UTC days, hx = X =
H cos D + variations, hy = Y = H sin D + variations, hz = Z + variations,
H 24,000 nT, D = 8.25 deg, Z -52,000 nT, the variations band-limited
noise of 15 nT; a 20-minute gap in day 2 splits it into two runs.

**This test fails if**
  - (1) the script without --apply does not exit 0, does not print the
    angle within 0.05 deg of D, or changes the archive (bytes);
  - (2) --apply does not exit 0; afterwards the archive's mean-field angle
    (atan2(median hy, median hx) over every sample, measured here
    independently with h5py) is not 0 within 0.01 deg; `archive_rot_h` does
    not read the applied angle back (within 1e-4 of the measured D);
    the station provenance, every run's comment and hx's and hy's comments
    in every run do not carry the "rot_h: ... applied to the observatory
    archive" line; the per-sample F differs from before by more than 1e-9 nT
    anywhere; hz differs from before anywhere; or the turned samples differ
    from cos(r) X + sin(r) Y, -sin(r) X + cos(r) Y of the original by more
    than 1e-9 nT;
  - (3) the dated copy <CODE>.h5.before_rot_h_<stamp> is missing or its
    bytes differ from the archive before the turn;
  - (4) a second --apply is not refused (exit 2, "already records rot_h"),
    or changes the archive (bytes);
  - (5) a site that is not an observatory is not refused (exit 2).

Usage:
    python tests/observatory_rot_h_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import yaml
from scipy.signal import butter, sosfiltfilt

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import observatory  # noqa: E402
from mt_workbench.ingest import archive_rot_h  # noqa: E402

SCRIPT = REPO / "scripts" / "observatory_rot_h.py"
SCRATCH = scratch_dir("observatory_rot_h_unit")
CODE = "TOB"
DAYS = ("2015-03-01", "2015-03-02")
H, D, Z = 24000.0, 8.25, -52000.0
GAP = (86400 + 40000, 86400 + 41200)   # 20 min in day 2: two runs
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def series() -> dict:
    """X, Y, Z of the two days (NaN in the gap)."""
    rng = np.random.default_rng(5)
    sos = butter(4, 0.02, fs=1.0, output="sos")
    n = 2 * 86400
    v = {c: sosfiltfilt(sos, rng.standard_normal(n)) for c in "xyz"}
    v = {c: 15.0 * a / a.std() for c, a in v.items()}
    out = dict(x=H * math.cos(math.radians(D)) + v["x"], y=H * math.sin(math.radians(D)) + v["y"], z=Z + v["z"])
    for c in out:
        out[c][GAP[0]:GAP[1]] = np.nan
    return out


def iaga_day(day: str, k0: int, data: dict) -> bytes:
    """One IAGA-2002 day of the synthetic series (99999.00 where NaN)."""
    head = [("Format", "IAGA-2002"), ("Source of Data", "synthetic, tests/observatory_rot_h_unit.py"),
            ("Station Name", "Test Observatory"), ("IAGA Code", CODE), ("Geodetic Latitude", "-31.000"),
            ("Geodetic Longitude", "138.000"), ("Elevation", "100"), ("Reported", "XYZF"),
            ("Sensor Orientation", "XYZF"), ("Digital Sampling", "0.01 second"),
            ("Data Interval Type", "1-second (00:00:00 - 00:00:00)"), ("Data Type", "Definitive")]
    lines = [f" {label:<23}{value:<45}|" for label, value in head]
    lines.append(f"DATE       TIME         DOY     {CODE}X      {CODE}Y      {CODE}Z      {CODE}F   |")
    t0 = pd.Timestamp(day)
    for k in range(86400):
        t = t0 + pd.Timedelta(seconds=k)
        x, y, z = (float(data[c][k0 + k]) for c in "xyz")
        x, y, z = (99999.0 if not np.isfinite(a) else a for a in (x, y, z))
        lines.append(f"{t:%Y-%m-%d %H:%M:%S}.000 {t.dayofyear:03d}   {x:10.2f}{y:10.2f}{z:10.2f}{88888.0:10.2f}")
    return ("\n".join(lines) + "\n").encode("ascii")


def build(root: Path) -> Path:
    """Survey with the observatory and one EDL site; the archive written by to_mth5; return survey.yaml."""
    if root.exists():
        shutil.rmtree(root)
    data = series()
    cache = root / "cache"
    for i, day in enumerate(DAYS):
        observatory._write_day(observatory.day_path(cache, CODE, day), iaga_day(day, i * 86400, data),
                               datetime(2026, 11, 8, tzinfo=timezone.utc))
    cfg = {"name": "TESTOBS", "instrument": "edl", "sample_rate": 10, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 4.0, "max_period": 10000.0},
           "sites": {CODE: {"instrument": "intermagnet", "channels": ["hx", "hy", "hz"], "latitude": -31.0,
                            "longitude": 138.0, "elevation": 100.0, "start": "2015-03-01T00:00:00Z",
                            "end": "2015-03-02T23:59:59Z"},
                     "S01": {"latitude": -31.1, "longitude": 138.1, "start": "2015-03-01T00:00:00Z",
                             "end": "2015-03-02T23:59:59Z"}}}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    observatory.to_mth5(CODE, DAYS[0], DAYS[1], cache, root / "work" / "mth5" / f"{CODE}.h5", survey="TESTOBS")
    return root / "survey.yaml"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def channels(path: Path) -> dict:
    """Every run's hx, hy, hz and comments, read with h5py (independent of the script)."""
    out = {}
    with h5py.File(path, "r") as f:
        sv = f["Experiment/Surveys"]
        st = sv[list(sv.keys())[0]]["Stations"][CODE]
        out["station_provenance"] = str(st.attrs.get("provenance.comments", ""))
        for rid in sorted(k for k in st.keys() if k.startswith("sr")):
            r = st[rid]
            out[rid] = {c: np.asarray(r[c][()], dtype="float64") for c in ("hx", "hy", "hz")}
            out[rid]["comments"] = {c: str(r[c].attrs.get("comments", "")) for c in ("hx", "hy")}
            out[rid]["run_comments"] = str(r.attrs.get("comments", ""))
    return out


def run(*args) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def angle_of(ch: dict) -> float:
    runs = [k for k in ch if k.startswith("sr")]
    x = np.concatenate([ch[r]["hx"] for r in runs])
    y = np.concatenate([ch[r]["hy"] for r in runs])
    ok = np.isfinite(x) & np.isfinite(y)
    return float(np.degrees(np.arctan2(np.median(y[ok]), np.median(x[ok]))))


def main() -> int:
    if not SCRIPT.exists():
        check(False, f"(0) {SCRIPT} does not exist")
        print(f"FAIL ({len(fails)})")
        return 1
    survey_yaml = build(SCRATCH / "obs")
    arch = SCRATCH / "obs" / "work" / "mth5" / f"{CODE}.h5"
    before = channels(arch)
    runs = [k for k in before if k.startswith("sr")]
    d_meas = angle_of(before)
    print(f"synthetic archive: {len(runs)} runs, measured angle before {d_meas:.4f} deg (D {D})")
    h0 = sha(arch)
    code, out = run(survey_yaml, CODE)
    check(code == 0 and f"{d_meas:+.4f}" in out and abs(d_meas - D) < 0.05 and sha(arch) == h0,
          f"(1) measure only: exit {code}, archive unchanged {sha(arch) == h0}; {out.strip().splitlines()[-1]}")
    code, out = run(survey_yaml, CODE, "--apply")
    check(code == 0, f"(2) --apply exit {code}: {out.strip().splitlines()[-1] if out.strip() else out}")
    after = channels(arch)
    a_after = angle_of(after)
    back = archive_rot_h(arch, CODE)
    check(abs(a_after) < 0.01, f"(2) angle after {a_after:+.5f} deg")
    check(back is not None and abs(back - d_meas) < 1e-4, f"(2) archive_rot_h reads {back!r}")
    key = "applied to the observatory archive"
    check(key in after["station_provenance"] and all(key in after[r]["run_comments"] for r in runs)
          and all(key in after[r]["comments"][c] for r in runs for c in ("hx", "hy")),
          f"(2) comments: station {after['station_provenance'][-120:]!r}")
    r_ = math.radians(back if back is not None else d_meas)
    fd = hz = rot = 0.0
    for r in runs:
        b, a = before[r], after[r]
        fin = np.isfinite(b["hx"]) & np.isfinite(b["hy"]) & np.isfinite(b["hz"])
        f0 = np.sqrt(b["hx"] ** 2 + b["hy"] ** 2 + b["hz"] ** 2)[fin]
        f1 = np.sqrt(a["hx"] ** 2 + a["hy"] ** 2 + a["hz"] ** 2)[fin]
        fd = max(fd, float(np.max(np.abs(f1 - f0))))
        hz = max(hz, float(np.nanmax(np.abs(a["hz"] - b["hz"]))))
        ex = math.cos(r_) * b["hx"] + math.sin(r_) * b["hy"]
        ey = -math.sin(r_) * b["hx"] + math.cos(r_) * b["hy"]
        rot = max(rot, float(np.nanmax(np.abs(a["hx"] - ex))), float(np.nanmax(np.abs(a["hy"] - ey))))
    check(fd <= 1e-9 and hz == 0.0 and rot <= 1e-9, f"(2) per-sample |dF| max {fd:.1e} nT, hz max change {hz}, "
                                                    f"turn vs the formula {rot:.1e} nT")
    copies = sorted(arch.parent.glob(f"{CODE}.h5.before_rot_h_*"))
    check(len(copies) == 1 and sha(copies[0]) == h0, f"(3) dated copy {[c.name for c in copies]} equal to before: "
                                                     f"{bool(copies) and sha(copies[0]) == h0}")
    h1 = sha(arch)
    code, out = run(survey_yaml, CODE, "--apply")
    check(code == 2 and "already records rot_h" in out and sha(arch) == h1,
          f"(4) second --apply: exit {code}, archive unchanged {sha(arch) == h1}; {out.strip().splitlines()[-1]}")
    code, out = run(survey_yaml, "S01", "--apply")
    check(code == 2 and "not an observatory" in out, f"(5) S01 --apply: exit {code}; {out.strip().splitlines()[-1]}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
