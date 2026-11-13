# -*- coding: utf-8 -*-
"""
Unit test for the per-part turn of the horizontal fluxgate pair at ingest (`rot_h_parts`)

For a fluxgate that turned during its record, as at FR12 of South Australia AusLAMP 2013-2018 on
2013-10-03: `rot_h_parts: [[start, end, angle_deg], ...]` (UTC ISO, start <= t < end, parts not overlapping,
mutually exclusive with `rot_h`) turns hx and hy by each part's angle over that part, and leaves out every sample outside
all parts (as `record_window` does), so the stretch of the turn is masked by leaving it out of both parts.

An EDL site of two synthetic 300 s stamps at 10 Hz (Bartington chain, `ingest_rot_h_unit`'s writer) records its
horizontal main field at +30 deg in the sensor frame in the first stamp and at -40 deg in the second: a sensor turned
by -70 deg at the stamp boundary t0 + 300 s. Declared: [[t0, t0 + 280 s, 30.0], [t0 + 320 s, t0 + 600 s, -40.0]].

Usage:
    python tests/ingest_rot_h_parts_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - P1: the archive does not hold exactly two runs, one per part, spanning t0 .. t0 + 279.9 s and t0 + 320 s ..
    t0 + 599.9 s (the 40 s around the turn left out); or in either run hx and hy differ from the file words turned by
    THAT part's angle by more than 1e-6 counts, its mean hy is not 0 to 1e-4 of |H|, its mean hx is not positive, or
    hz, ex, ey differ from the words at those instants;
  - P2: a run comment lacks "rot_h_part: <its angle> deg" and its span, hx/hy channel comments lack the part line or
    hz's has one; `archive_rot_h_parts` does not read both parts back; `archive_rot_h` does not give None (one angle
    does not describe the record); the station provenance lacks either part;
  - P3: `products.frame_record` of a TF whose runs carry the two part lines does not give both parts under
    ``rot_h_parts`` (and ``rot_h`` None), `frame_info_lines` lacks "mt_workbench.rot_h_parts=" naming both angles, or
    the EDI written from it lacks that INFO line, or the TF read back does not give both parts again;
  - P4: `Survey.site` (and `ingest_site`, which must then write no file) accepts rot_h_parts together with a non-zero
    rot_h, with h_from, on a derived site, overlapping parts, a part whose start is not before its end, an angle
    outside (-180, 180], a part that is not [start, end, angle], or a site whose start/end lie outside the parts.
Mutation: the same angle (30.0) applied to both parts must make P1 find the second run's mean hy far from 0
(sin 70 deg of |H|), which shows P1 can fail.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench import products  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_rot_h_unit import H_COUNTS, PER_FILE, SITE, STAMPS, Z_COUNTS, edl_survey, zero_mean  # noqa: E402

SCRATCH = scratch_dir("ingest_rot_h_parts_unit")
T0 = pd.Timestamp("2009-03-20T00:00:00Z")
PARTS = [[(T0).strftime("%Y-%m-%dT%H:%M:%SZ"), (T0 + pd.Timedelta(seconds=280)).strftime("%Y-%m-%dT%H:%M:%SZ"), 30.0],
         [(T0 + pd.Timedelta(seconds=320)).strftime("%Y-%m-%dT%H:%M:%SZ"),
          (T0 + pd.Timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ"), -40.0]]
SPAN = {"start": PARTS[0][0], "end": PARTS[1][1]}


def write_turned_site(root: Path) -> dict[str, np.ndarray]:
    """Write the two-stamp EDL site: field at +30 deg in stamp 1, at -40 deg in stamp 2. Returns the words by suffix."""
    import shutil

    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(11)
    words = {k: [] for k in ("BX", "BY", "BZ", "EX", "EY")}
    for k, (stamp, az) in enumerate(zip(STAMPS, (30.0, -40.0))):
        a = math.radians(az)
        part = {"BX": int(round(H_COUNTS * math.cos(a))) + zero_mean(rng, PER_FILE, 300.0),
                "BY": int(round(H_COUNTS * math.sin(a))) + zero_mean(rng, PER_FILE, 300.0),
                "BZ": int(round(Z_COUNTS)) + zero_mean(rng, PER_FILE, 200.0),
                "EX": rng.integers(-2_000_000, 2_000_000, PER_FILE), "EY": rng.integers(-2_000_000, 2_000_000, PER_FILE)}
        for suffix, values in part.items():
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", values, fmt="%d")
            words[suffix].append(values)
    return {k: np.concatenate(v) for k, v in words.items()}


def read_runs(path: Path) -> dict:
    """Return {run id: {comment, t0, comps: {comp: (samples, comment)}}} and the station provenance under key ''."""
    out = {}
    with h5py.File(path, "r") as f:
        st = f[f"Experiment/Surveys/t/Stations/{SITE}"]
        prov = st.attrs.get("provenance.comments")
        out[""] = prov.decode() if isinstance(prov, bytes) else str(prov or "")
        for rid in st:
            g = st[rid]
            if not isinstance(g, h5py.Group) or not rid.startswith("sr"):
                continue
            c = g.attrs.get("comments")
            run = {"comment": c.decode() if isinstance(c, bytes) else str(c or ""),
                   "start": str(g.attrs.get("time_period.start")), "comps": {}}
            for comp in g:
                if isinstance(g[comp], h5py.Dataset):
                    cc = g[comp].attrs.get("comments")
                    run["comps"][comp] = (g[comp][()], cc.decode() if isinstance(cc, bytes) else str(cc or ""))
            out[rid] = run
    return out


def part_problems(got: dict, words: dict, angles=(30.0, -40.0)) -> list[str]:
    runs = [got[r] for r in sorted(k for k in got if k)]
    problems = []
    if len(runs) != 2:
        return [f"{len(runs)} runs, want 2"]
    for run, (lo, n), deg in zip(runs, ((0, 2800), (3200, 2800)), angles):
        hx, hy = run["comps"]["hx"][0], run["comps"]["hy"][0]
        if hx.size != n:
            problems.append(f"run of {hx.size} samples, want {n}")
            continue
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        x, y = words["BX"][lo:lo + n].astype(float), words["BY"][lo:lo + n].astype(float)
        if np.max(np.abs(hx - (c * x + s * y))) > 1e-6 or np.max(np.abs(hy - (-s * x + c * y))) > 1e-6:
            problems.append(f"part {deg}: hx, hy are not the words turned by {deg}")
        h = math.hypot(float(np.mean(hx)), float(np.mean(hy)))
        if abs(float(np.mean(hy))) > 1e-4 * h:
            problems.append(f"part {deg}: mean hy {np.mean(hy):.4g} is not 0 to 1e-4 of |H| {h:.6g}")
        if not float(np.mean(hx)) > 0:
            problems.append(f"part {deg}: mean hx {np.mean(hx):.6g} not positive")
        for comp, suffix in (("hz", "BZ"), ("ex", "EX"), ("ey", "EY")):
            if not np.array_equal(run["comps"][comp][0], words[suffix][lo:lo + n]):
                problems.append(f"part {deg}: {comp} differs from the {suffix} words")
    return problems


def test_parts() -> Path:
    root = SCRATCH / "turn"
    words = write_turned_site(root)
    path = ingest_site(edl_survey(root, {"rot_h_parts": PARTS, **SPAN}), SITE, out_path=root / "work" / "parts.h5",
                       overwrite=True)
    got = read_runs(path)
    problems = part_problems(got, words)
    assert not problems, problems
    runs = sorted(k for k in got if k)
    print(f"  P1 two runs {runs}: {[got[r]['start'] for r in runs]}; each part's hx, hy == words turned by its angle "
          f"(30.0, -40.0) to 1e-6 counts, mean hy 0, hz ex ey == words; 40 s around the turn left out")
    real = ingest._turn_h
    ingest._turn_h = lambda run, site, value: real(run, site, 30.0)
    try:
        mutant = ingest_site(edl_survey(root, {"rot_h_parts": PARTS, **SPAN}), SITE,
                             out_path=root / "work" / "mutant.h5", overwrite=True)
    finally:
        ingest._turn_h = real
    caught = part_problems(read_runs(mutant), words)
    assert any("mean hy" in p for p in caught), caught
    print(f"  P1 mutation (one angle for both parts): {caught[0]!r}")
    for rid, deg in zip(runs, (30.0, -40.0)):
        comment = got[rid]["comment"]
        assert f"rot_h_part: {deg!r} deg" in comment, (deg, comment)
        for comp in ("hx", "hy"):
            assert f"rot_h_part: {deg!r} deg" in got[rid]["comps"][comp][1], got[rid]["comps"][comp][1]
        assert "rot_h_part" not in got[rid]["comps"]["hz"][1]
    parts = ingest.archive_rot_h_parts(path, SITE)
    assert [p[2] for p in parts] == [30.0, -40.0] and len(parts) == 2, parts
    assert ingest.archive_rot_h(path, SITE) is None
    assert got[""].count("rot_h_part: ") == 2, got[""]
    print(f"  P2 run comments, hx/hy channel comments and provenance carry the parts; archive_rot_h_parts {parts}; "
          f"archive_rot_h None")
    return path


def test_products() -> None:
    from unknown_declination_unit import make_tf

    lines = [ingest._rot_h_part_note(30.0, PARTS[0][0], PARTS[0][1]), ingest._rot_h_part_note(-40.0, PARTS[1][0], PARTS[1][1])]
    tf = make_tf(True)
    run0 = tf.station_metadata.runs[0]
    run0.comments = f"calibration_sha256: none; {lines[0]}"
    run1 = run0.copy()
    run1.id = "b"
    run1.comments = f"calibration_sha256: none; {lines[1]}"
    tf.station_metadata.add_run(run1)
    rec = products.frame_record(tf, "survey.yaml")
    assert [p[2] for p in rec["rot_h_parts"]] == [30.0, -40.0] and rec["rot_h"] is None, rec
    info = products.frame_info_lines(tf)
    line = next((x for x in info if x.startswith("mt_workbench.rot_h_parts=")), None)
    assert line and "30.0 deg" in line and "-40.0 deg" in line, info
    path = SCRATCH / "products" / "P3.edi"
    path.parent.mkdir(parents=True, exist_ok=True)
    products.write_edi(tf, path)
    assert "mt_workbench.rot_h_parts=" in path.read_text(encoding="latin-1")
    back = products.read_tf(path)
    assert [p[2] for p in products.frame_record(back)["rot_h_parts"]] == [30.0, -40.0], products.frame_record(back)
    print(f"  P3 frame_record rot_h_parts {rec['rot_h_parts']}; INFO {line!r}; EDI and back: both parts")


def refused(make, what, expect):
    try:
        make()
    except ValueError as exc:
        assert expect in str(exc), (what, exc)
        return str(exc)
    raise AssertionError(f"{what}: accepted")


def test_refusals() -> None:
    root = SCRATCH / "refusals"
    write_turned_site(root)
    out = root / "work" / "refused.h5"
    out.unlink(missing_ok=True)
    over = [[PARTS[0][0], PARTS[1][0], 30.0], [PARTS[0][1], PARTS[1][1], -40.0]]
    cases = (
        ("with rot_h", {"rot_h_parts": PARTS, "rot_h": 5.0, **SPAN}, {}, SITE, "rot_h"),
        ("h_from", {"rot_h_parts": PARTS, "h_from": "NB", "channels": ["ex", "ey"], **SPAN}, {"NB": {}}, SITE, "h_from"),
        ("derived", {}, {"HGRL": {"derived_from": SITE, "sample_rate": 1.0, "rot_h_parts": PARTS}}, "HGRL", "derived"),
        ("overlap", {"rot_h_parts": over, **SPAN}, {}, SITE, "overlap"),
        ("start >= end", {"rot_h_parts": [[PARTS[0][1], PARTS[0][0], 30.0]]}, {}, SITE, "start"),
        ("angle", {"rot_h_parts": [[PARTS[0][0], PARTS[0][1], 190.0]]}, {}, SITE, "(-180, 180]"),
        ("shape", {"rot_h_parts": [[PARTS[0][0], 30.0]]}, {}, SITE, "[start, end, angle"),
        ("span outside", {"rot_h_parts": PARTS, "start": "2009-03-19T23:00:00Z", "end": SPAN["end"]}, {}, SITE, "outside"),
    )
    for what, own, extra, name, expect in cases:
        msg = refused(lambda: edl_survey(root, own, extra_sites=extra).site(name), what, expect)
        print(f"  P4 {what}: refused ({msg[:90]}...)")
    refused(lambda: ingest_site(edl_survey(root, {"rot_h_parts": PARTS, "rot_h": 5.0, **SPAN}), SITE, out_path=out,
                                overwrite=True), "ingest with rot_h", "rot_h")
    assert not out.exists(), "a refused ingest wrote a file"


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\nMutation")[0])
    test_parts()
    print("  ok  test_parts")
    test_products()
    print("  ok  test_products")
    test_refusals()
    print("  ok  test_refusals")
    print("\nPASS  ingest_rot_h_parts_unit (3 tests)")
