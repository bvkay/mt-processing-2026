# -*- coding: utf-8 -*-
"""
Turn an observatory archive's horizontal pair from geographic X, Y onto magnetic north (its own rot_h)

`mt_workbench.observatory.to_mth5` (scripts/fetch_observatory.py) archives an
INTERMAGNET observatory as hx = X (geographic north), hy = Y (geographic
east), hz = Z, in nT with no filters. Every site of a survey in the
geomagnetic frame of record is turned onto its own magnetic north at ingest
(`rot_h`, `mt_workbench.ingest._rot_h`), so an observatory
that serves as a remote, a stack member or a lender of H sits about one
declination away from the sites. This script gives the
observatory archive the same turn, in place:

- the angle is measured as scripts/h_azimuth.py measures a site's azimuth:
  atan2(median hy, median hx) over every sample of every run of the archive
  (in the geographic frame that is the observatory's mean declination over
  the archive's span);
- with --apply, every run's hx and hy are turned by that angle r with
  `_rot_h`'s formula, hx' = cos(r) hx + sin(r) hy, hy' = -sin(r) hx +
  cos(r) hy (hz untouched), written back into the same datasets; the line
  "rot_h: <r> deg applied to the observatory archive by
  scripts/observatory_rot_h.py <stamp>, hx and hy turned from geographic X, Y
  onto magnetic north (the archive's mean-field angle)" is appended to every
  run's comment, to hx's and hy's comments and to the station's
  ``provenance.comments``, where `mt_workbench.ingest.archive_rot_h` reads it
  back;
- before anything is changed a copy of the file is written beside it,
  ``<CODE>.h5.before_rot_h_<YYYYmmddTHHMMSSZ>``, and checked equal to the
  original by size and SHA-256;
- an archive that already records a rot_h (`archive_rot_h` not None) is
  refused by --apply, so a second run cannot turn it twice;
- after the turn the angle is measured again (it must read 0 within
  `AFTER_TOL_DEG`, else exit 1) and printed with the per-sample F check
  (the largest |F after - F before| of hx, hy, hz over every sample).

Without --apply the archive is left unchanged: the angle is measured and printed with
what --apply would do. Rebuilding the archive with fetch_observatory.py
rewrites it from the cache in the geographic frame, so the turn has to be
applied again after any rebuild.

Exit status: 0 done, 1 a check after the turn failed, 2 a refusal or usage
error (not an observatory, no archive, already turned, a path on E:).

Usage:
    python scripts/observatory_rot_h.py <survey.yaml> <CODE> [--apply]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from mt_workbench.ingest import _append_comment, archive_rot_h, default_archive_path  # noqa: E402
from mt_workbench.products import ROT_H_PREFIX  # noqa: E402
from mt_workbench.survey import OBSERVATORY, Survey  # noqa: E402
from mt_workbench.timefreq import _real_runs  # noqa: E402

AFTER_TOL_DEG = 0.01  # the azimuth of the turned archive (median-based) must be 0 within this
F_TOL_NT = 1e-6       # the largest per-sample |F after - F before| allowed, nT (float64 rounding is ~1e-11)


def rot_h_note(angle: float, stamp: str) -> str:
    """The comment line recording the turn: "rot_h: <angle> deg applied to the observatory archive ...".

    One "key: value" piece with no ";" and no second ":" (docs/upstream_issues.md 48), so the stamp has
    no colons; `archive_rot_h` reads the float after the prefix.
    """
    return (f"{ROT_H_PREFIX}{angle!r} deg applied to the observatory archive by scripts/observatory_rot_h.py "
            f"{stamp}, hx and hy turned from geographic X, Y onto magnetic north (the archive's mean-field angle)")


def _station(m, code: str):
    survey_name = m.surveys_group.groups_list[0]
    return m.get_station(code, survey=survey_name)


def measure(path: Path, code: str) -> dict:
    """Return the archive's mean-field angle, atan2(median hy, median hx) over every sample, and its counts.

    Returns:
        dict: ``angle`` (deg), ``hx_med``, ``hy_med`` (nT), ``n`` (samples with hx and hy finite), ``runs``.
    """
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = _station(m, code)
        runs = [r for r, _, _ in _real_runs(st)]
        xs, ys = [], []
        for rid in runs:
            rg = st.get_run(rid)
            xs.append(np.asarray(rg.get_channel("hx").hdf5_dataset[()], dtype="float64"))
            ys.append(np.asarray(rg.get_channel("hy").hdf5_dataset[()], dtype="float64"))
    finally:
        m.close_mth5()
    x, y = np.concatenate(xs), np.concatenate(ys)
    ok = np.isfinite(x) & np.isfinite(y)
    hx_med, hy_med = float(np.median(x[ok])), float(np.median(y[ok]))
    return dict(angle=float(np.degrees(np.arctan2(hy_med, hx_med))), hx_med=hx_med, hy_med=hy_med,
                n=int(ok.sum()), runs=len(runs))


def sha256(path: Path, chunk: int = 1 << 24) -> str:
    """SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def dated_copy(path: Path, stamp: str) -> Path:
    """Copy the archive to <name>.before_rot_h_<stamp> beside it and check size and SHA-256; return the copy."""
    copy = path.with_name(f"{path.name}.before_rot_h_{stamp}")
    if copy.exists():
        raise FileExistsError(f"{copy} exists")
    shutil.copy2(path, copy)
    if copy.stat().st_size != path.stat().st_size or sha256(copy) != sha256(path):
        copy.unlink(missing_ok=True)
        raise OSError(f"the copy {copy} does not equal {path}")
    return copy


def apply_turn(path: Path, code: str, angle: float, stamp: str) -> dict:
    """Turn every run's hx and hy by `angle` in place and write the comments; return the per-sample F check.

    Returns:
        dict: ``runs``, ``samples``, ``f_max_diff`` (nT, the largest |F after - F before| over every sample),
        ``hz_changed`` (always False: hz is not touched; checked by reading it back).
    """
    from mth5.mth5 import MTH5

    c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    note = rot_h_note(angle, stamp)
    m = MTH5()
    m.open_mth5(path, mode="a")
    f_max, n = 0.0, 0
    try:
        st = _station(m, code)
        runs = [r for r, _, _ in _real_runs(st)]
        for rid in runs:
            rg = st.get_run(rid)
            chx, chy, chz = rg.get_channel("hx"), rg.get_channel("hy"), rg.get_channel("hz")
            dx, dy = chx.hdf5_dataset, chy.hdf5_dataset
            x = np.asarray(dx[()], dtype="float64")
            y = np.asarray(dy[()], dtype="float64")
            z = np.asarray(chz.hdf5_dataset[()], dtype="float64")
            xn, yn = c * x + s * y, -s * x + c * y
            dx[...] = xn.astype(dx.dtype)
            dy[...] = yn.astype(dy.dtype)
            xb, yb = np.asarray(dx[()], dtype="float64"), np.asarray(dy[()], dtype="float64")
            fin = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
            if fin.any():
                f0 = np.sqrt(x[fin] ** 2 + y[fin] ** 2 + z[fin] ** 2)
                f1 = np.sqrt(xb[fin] ** 2 + yb[fin] ** 2 + z[fin] ** 2)
                f_max = max(f_max, float(np.max(np.abs(f1 - f0))))
            n += int(fin.sum())
            for ch in (chx, chy):
                ch.metadata.comments.value = _append_comment(ch.metadata.comments, note)
                ch.write_metadata()
            rg.metadata.comments.value = _append_comment(rg.metadata.comments, note)
            rg.write_metadata()
        st.metadata.provenance.comments.value = _append_comment(st.metadata.provenance.comments, note)
        st.write_metadata()
    finally:
        m.close_mth5()
    return dict(runs=len(runs), samples=n, f_max_diff=f_max)


def main(argv=None) -> int:
    """Measure, and with --apply turn; see the module docstring for the exit status."""
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("survey_yaml")
    p.add_argument("code", help="the observatory's site name in survey.yaml (its IAGA code)")
    p.add_argument("--apply", action="store_true", help="turn the archive in place (a dated copy first)")
    args = p.parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    code = args.code
    if code not in survey.site_names():
        print(f"ERROR {code} is not a site of {args.survey_yaml}", file=sys.stderr)
        return 2
    if survey.instrument_of(code) != OBSERVATORY:
        print(f"ERROR {code} is not an observatory (instrument {survey.instrument_of(code)}): a site's turn is "
              f"its rot_h key, applied at ingest", file=sys.stderr)
        return 2
    path = default_archive_path(survey, code)
    if str(path.resolve()).upper().startswith("E:"):
        print(f"ERROR refusing to write under E: ({path})", file=sys.stderr)
        return 2
    if not path.exists():
        print(f"ERROR no archive {path}", file=sys.stderr)
        return 2
    done = archive_rot_h(path, code)
    before = measure(path, code)
    print(f"{code}: {path} ({before['runs']} runs, {before['n']} samples): median hx {before['hx_med']:.2f} nT, "
          f"median hy {before['hy_med']:.2f} nT -> mean-field angle {before['angle']:+.4f} deg")
    if done is not None:
        print(f"{'ERROR ' if args.apply else ''}{code}: the archive already records rot_h {done!r} deg; "
              f"{'refused, it is not turned twice' if args.apply else 'nothing to do'}",
              file=sys.stderr if args.apply else sys.stdout)
        return 2 if args.apply else 0
    angle = round(before["angle"], 4)
    if not args.apply:
        print(f"{code}: --apply would turn hx and hy by rot_h {angle!r} deg in every run (a dated copy first)")
        return 0
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copy = dated_copy(path, stamp)
    print(f"{code}: copy {copy} (size and SHA-256 equal)", flush=True)
    res = apply_turn(path, code, angle, stamp)
    after = measure(path, code)
    back = archive_rot_h(path, code)
    ok = abs(after["angle"]) <= AFTER_TOL_DEG and res["f_max_diff"] <= F_TOL_NT and back == angle
    print(f"{code}: turned by {angle!r} deg in {res['runs']} runs ({res['samples']} samples); after: median hx "
          f"{after['hx_med']:.2f}, hy {after['hy_med']:.2f} nT, angle {after['angle']:+.5f} deg (limit "
          f"{AFTER_TOL_DEG}); per-sample |dF| max {res['f_max_diff']:.2e} nT (limit {F_TOL_NT:g}); archive_rot_h "
          f"reads {back!r}; {'OK' if ok else 'CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
