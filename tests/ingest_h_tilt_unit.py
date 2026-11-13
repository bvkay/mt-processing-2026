# -*- coding: utf-8 -*-
"""
Unit test for the 3-D attitude correction of a tilted three-component fluxgate at ingest (`h_tilt`)

SA029E of South Australia AusLAMP 2013-2018:
an Orange Box whose fluxgate measured the main field at H 33,995 / Z -46,405 nT against IGRF's H 24,642 / Z -52,833: the
vector tipped ~11.2 deg in the sensor x-z plane, F within 1.3 %, every channel sound.

`h_tilt: [rx, ry, rz]` is a rotation vector in degrees in the sensor axes (x, y, z as the channels are after `swap_h` and
`flip_h`): the field in the level frame is B_level = R B_sensor, R the right-hand rotation by |r| about r/|r|. Ingest
applies it to hx, hy and hz together, in physical units (each channel's counts divided by its own chain's gain, turned,
and multiplied back by its own gain), so it is exact for chains of different gain or sign (an EDL's hz divider 0.4, an
Orange Box's hy gain of opposite sign: workbench 156), and before `rot_h`.

Usage:
    python tests/ingest_h_tilt_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - H1 (EDL, rotation vector [2.0, 11.2, -1.5] deg): the archive's hx, hy, hz, divided by the Bartington gain (hx, hy
    142.857 counts/nT, hz 142.857 x 0.4) are not R times the written words divided by the same gains to 1e-3 counts at
    every sample; its mean field is not IGRF's (H, 0, Z) to 1e-4 of F in each component; or ex, ey differ from the words;
  - H2 (Orange Box, the same vector, files written so that hy's counts carry the opposite sign, as mt-io's chain has it):
    the plain archive P (the same files ingested without the key) divided by the documented gains k = (+, -, +) 2^23/FS
    does not give the written mean field to 0.5 nT per channel (which fixes k from the plain ingest alone); or the
    tilted archive's samples are not k (R (P / k)) to 1e-3 counts; or its mean field is not (H, 0, Z) to 1e-4 of F.
    (A line fitted between P and the written field over its 2 nT variation does not fix k: the reader's sample
    alignment decorrelates the two, and such a fit gives k 10.3 against 119.8 on the plain archive);
  - H3 (EDL, h_tilt then rot_h 30.0): the level field at azimuth 30 deg in the sensor frame does not end at mean
    (H, 0, Z) to 1e-4 of F (h_tilt applied before rot_h);
  - H4: the run comment lacks "h_tilt: 2.0 11.2 -1.5 deg" with the mean-field inclination before and after; hx's, hy's
    and hz's channel comments lack the line or ex's has it; the station provenance lacks it; `archive_h_tilt` does not
    read [2.0, 11.2, -1.5] back (None from an archive without the key); `products.frame_record` of a TF whose run
    carries the line does not give ``h_tilt`` [2.0, 11.2, -1.5], `frame_info_lines` lacks "mt_workbench.h_tilt=", the
    EDI written from it lacks the INFO line, or the TF read back does not give the vector again;
  - H5: `Survey.site` (and `ingest_site`, which must then write no file) accepts h_tilt with h_from, on a derived site,
    with channels lacking hz, with edl_banks_swapped, with rot_h_parts, on a LEMI-423 site, of length other than 3, not
    finite, a bool, the zero vector, or an angle |r| over 45 deg.
Mutations: the turn applied to the counts as stored (each chain's gain ignored) must make H1 fail on hz (gain 0.4 apart)
and H2 fail (hy's sign); the inverse rotation (R transposed) must make H1's mean field miss (H, 0, Z) by ~2 x 11 deg.
Each must trip its check, which shows the check can fail.
"""

from __future__ import annotations

import importlib.util
import math
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import yaml
from scipy.spatial.transform import Rotation

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench import products  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_rot_h_unit import PER_FILE, SITE, STAMPS, edl_survey, zero_mean  # noqa: E402

_spec = importlib.util.spec_from_file_location("orangebox_unit", REPO / "tests" / "orangebox_unit.py")
_ob_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ob_unit)  # the file writer; its import removes loguru's handlers
write_orange_bin = _ob_unit.write_orange_bin

SCRATCH = scratch_dir("ingest_h_tilt_unit")
TILT = [2.0, 11.2, -1.5]
B_LEVEL = np.array([24642.0, 0.0, -52833.0])  # IGRF at SA029E, nT (x north, y east, z down)
G_EDL = np.array([142.857, 142.857, 142.857 * 0.4])  # counts per nT: Bartington chain, hz through the 0.4 divider
FS_NT = 70000.0
OB_SIGN = np.array([1.0, -1.0, 1.0])  # mt-io's Orange Box chain: +2^23/FS hx and hz, -2^23/FS hy (issue 156)
N_FILE = 30003
FP = 0x7A1
T0_OB = datetime(2015, 5, 14, 15, 30, 0)  # Adelaide wall clock


def rot(vec_deg) -> np.ndarray:
    """The rotation matrix of a rotation vector in degrees (scipy's, independent of the code under test)."""
    return Rotation.from_rotvec(np.radians(np.asarray(vec_deg, float))).as_matrix()


def sensor_field(n: int, rng, level=B_LEVEL, vec=TILT) -> np.ndarray:
    """Return 3 x n sensor-frame field samples (nT): the level main field turned into the tilted sensor, plus variation
    of exactly zero mean in the level frame."""
    var = np.vstack([zero_mean(rng, n, 2.0).astype(float) for _ in range(3)])
    return rot(vec).T @ (level[:, None] + var)


# --- EDL ---------------------------------------------------------------------------------------------------------------
def write_edl(root: Path, level=B_LEVEL, seed: int = 5) -> dict:
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(seed)
    n = PER_FILE * len(STAMPS)
    b = sensor_field(n, rng, level)
    words = {"BX": np.round(b[0] * G_EDL[0]).astype("int64"), "BY": np.round(b[1] * G_EDL[1]).astype("int64"),
             "BZ": np.round(b[2] * G_EDL[2]).astype("int64"),
             "EX": rng.integers(-2_000_000, 2_000_000, n), "EY": rng.integers(-2_000_000, 2_000_000, n)}
    for k, stamp in enumerate(STAMPS):
        for suffix, values in words.items():
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", values[k * PER_FILE:(k + 1) * PER_FILE], fmt="%d")
    return words


def read_all(path: Path, station: str, survey: str) -> dict:
    """Return {"": provenance, comp: (samples joined over runs, [channel comments]), "comments": [run comments]}."""
    out = {"comments": []}
    with h5py.File(path, "r") as f:
        st = f[f"Experiment/Surveys/{survey}/Stations/{station}"]
        prov = st.attrs.get("provenance.comments")
        out[""] = prov.decode() if isinstance(prov, bytes) else str(prov or "")
        for rid in sorted(st):
            g = st[rid]
            if not isinstance(g, h5py.Group) or not rid.startswith("sr"):
                continue
            c = g.attrs.get("comments")
            out["comments"].append(c.decode() if isinstance(c, bytes) else str(c or ""))
            for comp in g:
                if isinstance(g[comp], h5py.Dataset):
                    cc = g[comp].attrs.get("comments")
                    cc = cc.decode() if isinstance(cc, bytes) else str(cc or "")
                    old = out.get(comp, (np.array([]), []))
                    out[comp] = (np.concatenate([old[0], g[comp][()].astype(float)]), old[1] + [cc])
    return out


def edl_problems(got: dict, words: dict, level=B_LEVEL, then_rot_h: float = 0.0) -> list[str]:
    problems = []
    w = np.vstack([words[k].astype(float) for k in ("BX", "BY", "BZ")]) / G_EDL[:, None]
    want = rot(TILT) @ w
    if then_rot_h:
        c, s = math.cos(math.radians(then_rot_h)), math.sin(math.radians(then_rot_h))
        want = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]]) @ want
    want_counts = want * G_EDL[:, None]
    for i, comp in enumerate(("hx", "hy", "hz")):
        d = float(np.max(np.abs(got[comp][0] - want_counts[i])))
        if d > 1e-3:
            problems.append(f"{comp}: {d:.4g} counts from R times the words (in nT through each chain)")
    mean = np.array([np.mean(got[c][0]) for c in ("hx", "hy", "hz")]) / G_EDL
    target = B_LEVEL
    f = float(np.linalg.norm(target))
    if np.max(np.abs(mean - target)) > 1e-4 * f:
        problems.append(f"mean field {np.round(mean, 2)} nT is not {target} to 1e-4 of F")
    for comp, suffix in (("ex", "EX"), ("ey", "EY")):
        if not np.array_equal(got[comp][0], words[suffix].astype(float)):
            problems.append(f"{comp} differs from the {suffix} words")
    return problems


def test_edl(mutant: str = "") -> list[str]:
    root = SCRATCH / "edl"
    words = write_edl(root)
    path = ingest_site(edl_survey(root, {"h_tilt": TILT}), SITE, out_path=root / "work" / f"tilt{mutant}.h5",
                       overwrite=True)
    got = read_all(path, SITE, "t")
    problems = edl_problems(got, words)
    if mutant:
        return problems
    assert not problems, problems
    print(f"  H1 EDL: hx hy hz == R [2.0, 11.2, -1.5] x words through each chain (hz gain 0.4 apart) to 1e-3 counts; "
          f"mean field (H, 0, Z) to 1e-4 of F; ex ey == words")
    # H3: tilt then rot_h
    a = math.radians(30.0)
    level30 = np.array([B_LEVEL[0] * math.cos(a), B_LEVEL[0] * math.sin(a), B_LEVEL[2]])
    root3 = SCRATCH / "edl30"
    words3 = write_edl(root3, level30, seed=6)
    path3 = ingest_site(edl_survey(root3, {"h_tilt": TILT, "rot_h": 30.0}), SITE, out_path=root3 / "work" / "t30.h5",
                        overwrite=True)
    p3 = edl_problems(read_all(path3, SITE, "t"), words3, then_rot_h=30.0)
    assert not p3, p3
    print("  H3 EDL h_tilt then rot_h 30.0: samples == rot_z(30) R words; mean field (H, 0, Z) to 1e-4 of F")
    # H4 (archive side)
    line = "h_tilt: 2.0 11.2 -1.5 deg"
    assert any(line in c and "inclination" in c for c in got["comments"]), got["comments"]
    for comp in ("hx", "hy", "hz"):
        assert all(line in c for c in got[comp][1]), (comp, got[comp][1])
    assert not any("h_tilt" in c for c in got["ex"][1]), got["ex"][1]
    assert line in got[""], got[""]
    back = ingest.archive_h_tilt(path, SITE)
    assert back == TILT, back
    plain = ingest_site(edl_survey(root, {}), SITE, out_path=root / "work" / "plain.h5", overwrite=True)
    assert ingest.archive_h_tilt(plain, SITE) is None
    print(f"  H4 run, hx/hy/hz channel and station comments carry {line!r}; archive_h_tilt {back}; None without the key")
    return []


# --- Orange Box --------------------------------------------------------------------------------------------------------
def write_ob(folder: Path, seed: int = 7) -> np.ndarray:
    """Write two back-to-back Orange Box files of the tilted field; return the written field in nT (3 x n)."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    b = sensor_field(2 * N_FILE, rng)
    counts_h = np.round(b * OB_SIGN[:, None] * 2 ** 23 / FS_NT).astype(np.int64)
    written = counts_h * OB_SIGN[:, None] * FS_NT / 2 ** 23  # the rounded field in nT
    for i in range(2):
        sl = slice(i * N_FILE, (i + 1) * N_FILE)
        counts = np.zeros((N_FILE, 8), dtype=np.int64)
        counts[:, 0], counts[:, 2], counts[:, 1] = 2 ** 23 + counts_h[0, sl], 2 ** 23 + counts_h[1, sl], \
            2 ** 23 + counts_h[2, sl]
        counts[:, 6] = 2 ** 23 + rng.integers(-2000, 2000, N_FILE)
        counts[:, 7] = 2 ** 23 + rng.integers(-2000, 2000, N_FILE)
        counts[:, 3], counts[:, 4], counts[:, 5] = 1000, 1000, 20
        write_orange_bin(folder / f"HFM4-{i:03d}.BIN", counts, pd.Timestamp(T0_OB + timedelta(seconds=3000 * i)), fp=FP)
    (folder / "HFM4-RPT.TXT").write_text("High Frequency Magnetometer Number 4 - Flinders University 1999 - 2003\n",
                                         encoding="ascii")
    return written


def ob_survey(root: Path, own: dict) -> Survey:
    config = {"name": "obtilt", "instrument": "orangebox", "sample_rate": 10, "data_root": str(root / "raw"),
              "workspace": str(root / "work"),
              "defaults": {"azimuth_ex": 0.0, "azimuth_ey": 90.0, "channels": ["ex", "ey", "hx", "hy", "hz"],
                           "electric_full_scale_uv": 100000.0, "magnetic_full_scale_nt": FS_NT,
                           "clock_timezone": "Australia/Adelaide"},
              "sites": {"S4": dict(dipole_length_ex=48.0, dipole_length_ey=49.0, latitude=-32.5, longitude=134.5, **own)}}
    path = root / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return Survey.from_yaml(path)


def test_ob(mutant: str = "") -> list[str]:
    root = SCRATCH / "ob"
    written = write_ob(root / "raw" / "S4")
    plain = read_all(ingest_site(ob_survey(root, {}), "S4", out_path=root / "work" / "plain.h5", overwrite=True),
                     "S4", "obtilt")
    tilt = read_all(ingest_site(ob_survey(root, {"h_tilt": TILT}), "S4", out_path=root / "work" / f"tilt{mutant}.h5",
                                overwrite=True), "S4", "obtilt")
    n = plain["hx"][0].size
    assert tilt["hx"][0].size == n, (tilt["hx"][0].size, n)
    # the documented gains, checked on the plain archive's mean field (an observable of the plain ingest only)
    k = OB_SIGN * 2 ** 23 / FS_NT
    p = np.vstack([plain[c][0] for c in ("hx", "hy", "hz")])
    gap = np.abs(p.mean(axis=1) / k - written.mean(axis=1))
    assert np.all(gap < 0.5), f"plain archive / documented gains misses the written mean field by {gap} nT"
    want = k[:, None] * (rot(TILT) @ (p / k[:, None]))
    problems = []
    for i, comp in enumerate(("hx", "hy", "hz")):
        d = float(np.max(np.abs(tilt[comp][0] - want[i])))
        if d > 1e-3:
            problems.append(f"{comp}: {d:.4g} counts from k (R (P / k))")
    mean = np.array([np.mean(tilt[c][0]) / k[i] for i, c in enumerate(("hx", "hy", "hz"))])
    if np.max(np.abs(mean - B_LEVEL)) > 1e-4 * np.linalg.norm(B_LEVEL):
        problems.append(f"mean field {np.round(mean, 2)} nT is not {B_LEVEL}")
    if mutant:
        return problems
    assert not problems, problems
    print(f"  H2 Orange Box (documented gains k = {np.round(k, 3)} counts/nT give the written mean field from the plain "
          f"archive to {gap.max():.3f} nT): hx hy hz == k (R (P / k)) to 1e-3 counts; mean field (H, 0, Z) to 1e-4 of F")
    return []


# --- products ----------------------------------------------------------------------------------------------------------
def test_products() -> None:
    from unknown_declination_unit import make_tf

    tf = make_tf(True)
    run0 = tf.station_metadata.runs[0]
    run0.comments = f"calibration_sha256: none; {ingest._h_tilt_note(TILT)}"
    rec = products.frame_record(tf, "survey.yaml")
    assert rec["h_tilt"] == TILT, rec
    info = products.frame_info_lines(tf)
    line = next((x for x in info if x.startswith("mt_workbench.h_tilt=")), None)
    assert line and "2.0 11.2 -1.5 deg" in line, info
    path = SCRATCH / "products" / "H4.edi"
    path.parent.mkdir(parents=True, exist_ok=True)
    products.write_edi(tf, path)
    assert "mt_workbench.h_tilt=" in path.read_text(encoding="latin-1")
    back = products.read_tf(path)
    assert products.frame_record(back)["h_tilt"] == TILT, products.frame_record(back)
    plain = make_tf(True)
    assert products.frame_record(plain)["h_tilt"] is None
    print(f"  H4 frame_record h_tilt {rec['h_tilt']}; INFO {line!r}; EDI and back: {TILT}")


def refused(make, what, expect):
    try:
        make()
    except ValueError as exc:
        assert expect in str(exc), (what, exc)
        return str(exc)
    raise AssertionError(f"{what}: accepted")


def test_refusals() -> None:
    root = SCRATCH / "refusals"
    write_edl(root)
    out = root / "work" / "refused.h5"
    out.unlink(missing_ok=True)
    parts = [["2009-03-20T00:00:00Z", "2009-03-20T00:10:00Z", 5.0]]
    span = {"start": "2009-03-20T00:00:00Z", "end": "2009-03-20T00:10:00Z"}
    cases = (
        ("h_from", {"h_tilt": TILT, "h_from": "NB", "channels": ["ex", "ey"]}, {"NB": {}}, SITE, "h_from"),
        ("derived", {}, {"HGRL": {"derived_from": SITE, "sample_rate": 1.0, "h_tilt": TILT}}, "HGRL", "derived"),
        ("no hz", {"h_tilt": TILT, "channels": ["ex", "ey", "hx", "hy"]}, {}, SITE, "hz"),
        ("banks swapped", {"h_tilt": TILT, "edl_banks_swapped": True, "channels": ["ex", "ey", "hx", "hy"]}, {}, SITE,
         "hz"),
        ("rot_h_parts", {"h_tilt": TILT, "rot_h_parts": parts, **span}, {}, SITE, "rot_h_parts"),
        ("lemi423", {"h_tilt": TILT, "instrument": "lemi423"}, {}, SITE, "fluxgate"),
        ("length", {"h_tilt": [1.0, 2.0]}, {}, SITE, "[rx, ry, rz]"),
        ("not finite", {"h_tilt": [1.0, float("nan"), 0.0]}, {}, SITE, "[rx, ry, rz]"),
        ("bool", {"h_tilt": [True, 0.0, 0.0]}, {}, SITE, "[rx, ry, rz]"),
        ("zero", {"h_tilt": [0.0, 0.0, 0.0]}, {}, SITE, "zero"),
        ("over 45", {"h_tilt": [0.0, 46.0, 0.0]}, {}, SITE, "45"),
    )
    for what, own, extra, name, expect in cases:
        msg = refused(lambda: edl_survey(root, own, extra_sites=extra).site(name), what, expect)
        print(f"  H5 {what}: refused ({msg[:90]}...)")
    refused(lambda: ingest_site(edl_survey(root, {"h_tilt": [0.0, 46.0, 0.0]}), SITE, out_path=out, overwrite=True),
            "ingest over 45", "45")
    assert not out.exists(), "a refused ingest wrote a file"


def test_mutations() -> None:
    real = ingest._h_tilt_gains
    ingest._h_tilt_gains = lambda run, site: np.ones(3)  # the turn on the counts as stored
    try:
        m1 = test_edl("_m1")
        m2 = test_ob("_m2")
    finally:
        ingest._h_tilt_gains = real
    assert any(p.startswith("hz") for p in m1), m1
    assert m2, m2
    print(f"  mutation 1 (gains ignored): H1 {m1[0]!r}; H2 {m2[0]!r}")
    real_m = ingest._h_tilt_matrix
    ingest._h_tilt_matrix = lambda vec: real_m(vec).T
    try:
        m3 = test_edl("_m3")
    finally:
        ingest._h_tilt_matrix = real_m
    assert any("mean field" in p for p in m3), m3
    print(f"  mutation 2 (R transposed): H1 {[p for p in m3 if 'mean field' in p][0]!r}")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\nMutations")[0])
    test_edl()
    print("  ok  test_edl")
    test_ob()
    print("  ok  test_ob")
    test_products()
    print("  ok  test_products")
    test_refusals()
    print("  ok  test_refusals")
    test_mutations()
    print("  ok  test_mutations")
    print("\nPASS  ingest_h_tilt_unit (5 tests)")
