# -*- coding: utf-8 -*-
"""
Unit test for the turn of the horizontal fluxgate pair onto magnetic north at ingest (`rot_h`)

An EDL site of two synthetic 300 s stamps at 10 Hz (Bartington chain, as
mt-io reads a PR6-24) records a main field of 20,000 nT (2,857,140 counts
at 142.857 uV/nT) whose horizontal part lies at a chosen azimuth in the
sensor frame, plus a variation series of exactly zero mean, so that the
mean field's azimuth is the chosen one to within the rounding of the
words. `rot_h` (`mt_workbench.survey.SiteConfig.rot_h`) is the azimuth of
magnetic north measured from the sensor's x axis toward its y axis, the
mean-field azimuth atan2(mean hy, mean hx) in the sensor frame; ingest turns
(hx, hy) by it after `swap_h` and `flip_h`. The site is ingested at +30 deg
with `rot_h: 30.0`, at 180 deg with `rot_h: 180.0`, at +157.6 deg (TAS107's
sensor) with `rot_h: 157.6`, with `rot_h: 0.0` and with no key. The
30 deg archive then gives a filtered variant (`build_variant`), a derived
1 Hz site (scripts/decimate_site.py `write_derived`) and a transfer
function whose run carries its run comment, written to an EDI and read
back (`mt_workbench.products`).

Usage:
    python tests/ingest_rot_h_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - R1: with `rot_h: 30.0` the archive's mean hy is not 0 to 1e-6 of |H|,
    its mean hx is not positive, hx and hy differ from the words turned
    by 30 deg (hx' = cos hx + sin hy, hy' = -sin hx + cos hy) by more than
    1e-6 counts, or hz, ex or ey differ from the files' words;
  - R2: with the field at 180 deg and `rot_h: 180.0`, or at +157.6 deg
    and `rot_h: 157.6`, the mean hx is not positive or the mean hy not 0
    to 1e-6 of |H|;
  - R3: the `rot_h: 0.0` archive differs from the archive without the key
    in any dataset or in the run comment;
  - R4: the run comment lacks "rot_h: 30.0 deg applied at ingest" or the
    run's mean-field azimuth before (+30.00) and after (+0.00) the turn,
    hx's or hy's channel comment lacks the rot_h line or hz's has it, or
    `archive_rot_h` does not read 30.0 from the archive (and None from the
    archive without the key);
  - R5: `Survey.site`, or `ingest_site` (which must then write no file),
    accepts `rot_h` on a site with `h_from`, in `defaults:`, on a derived
    site, outside (-180, 180], not finite, a bool, or with channels
    lacking hy; or a LEMI-423 site, whose hx and hy chains differ in
    their linear stage (Kmx is not Kmy), ingests with `rot_h` instead of
    raising ValueError naming the chains. (That refusal comes from the
    first run read, after the archive was opened: like any per-run error
    of `ingest_site` it leaves the partial file, which scripts/ingest_site.py
    removes and the library does not);
  - R6: the variant built from the 30 deg archive or the derived 1 Hz
    archive does not keep the turned samples (the variant's, unchanged),
    the channel comments' rot_h line and the station's record
    (`archive_rot_h` 30.0);
  - R7: `products.frame_record` of a TF whose run comment carries the
    rot_h line does not give `rot_h` 30.0, `frame_info_lines` lacks
    "mt_workbench.rot_h=30.0 deg", or the EDI written from it lacks that
    INFO line, or the TF read back from that EDI does not give 30.0 again;
    a TF without the line gives None and no such INFO line.

Mutations: R1 with `_rot_h` turning the other way (the angle negated)
must find mean hy far from 0 (sin 60 deg of |H|); R3 with the 0.0
key written into the run comment must find the comments differ; R7 with
the run comment's key spelled "rot-h" must find no rot_h. Each must trip
its check, which shows the check can fail.
"""

from __future__ import annotations

import importlib.util
import math
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench import products  # noqa: E402
from mt_workbench.ingest import archive_rot_h, build_variant, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_swap_h_unit import all_datasets, lemi_survey, same  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRATCH = scratch_dir("ingest_rot_h_unit")
SITE = "HGR"
RUN = "sr10_0001"
STAMPS = ("090320000000", "090320000500")
PER_FILE = 3000
H_COUNTS = 20_000.0 * 142.857  # 20,000 nT through the Bartington chain
Z_COUNTS = -55_000.0 * 142.857 * 0.4  # the vertical field through the 0.4 divider
NOTCH = [{"notch": {"f0": 2.0, "harmonics": 1, "q": 30.0, "passes": 1}}]


def zero_mean(rng, n: int, scale: float) -> np.ndarray:
    """Return n integers of exactly zero sum: white noise of standard deviation `scale` and its negation."""
    half = np.round(rng.normal(0.0, scale, n // 2)).astype("int64")
    out = np.concatenate([half, -half[::-1]])
    assert out.sum() == 0
    return out


def write_site(root: Path, azimuth_deg: float, seed: int = 3) -> dict[str, np.ndarray]:
    """Write the EDL site under `root`/raw with its horizontal main field at `azimuth_deg` in the sensor frame.

    Returns:
        dict: The words of each channel file, by suffix, both stamps joined.
    """
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(seed)
    n = PER_FILE * len(STAMPS)
    a = math.radians(azimuth_deg)
    words = {"BX": int(round(H_COUNTS * math.cos(a))) + zero_mean(rng, n, 300.0),
             "BY": int(round(H_COUNTS * math.sin(a))) + zero_mean(rng, n, 300.0),
             "BZ": int(round(Z_COUNTS)) + zero_mean(rng, n, 200.0),
             "EX": rng.integers(-2_000_000, 2_000_000, n), "EY": rng.integers(-2_000_000, 2_000_000, n)}
    for k, stamp in enumerate(STAMPS):
        for suffix, values in words.items():
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", values[k * PER_FILE:(k + 1) * PER_FILE], fmt="%d")
    return words


def edl_survey(root: Path, own: dict, filters=None, extra_sites: dict | None = None, **defaults) -> Survey:
    """Build the one-site EDL survey over `root`, with the site's own entry and extra defaults."""
    base = {"dipole_length_ex": 49.0, "dipole_length_ey": 51.0, "channels": ["ex", "ey", "hx", "hy", "hz"]}
    entry = dict(own, **({"filters": filters} if filters else {}))
    return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                   "workspace": str(root / "work"), "defaults": {**base, **defaults},
                   "sites": {SITE: entry, **(extra_sites or {})}}, root)


def read_run(path: Path, station: str = SITE, run_id: str = RUN) -> dict:
    """Return a run's comment, each channel's samples and comment, and the station's provenance."""
    out = {}
    with h5py.File(path, "r") as f:
        group = f[f"Experiment/Surveys/t/Stations/{station}/{run_id}"]
        comment = group.attrs.get("comments")
        out["comment"] = comment.decode() if isinstance(comment, bytes) else str(comment or "")
        for comp in group:
            if isinstance(group[comp], h5py.Dataset):
                c = group[comp].attrs.get("comments")
                out[comp] = dict(samples=group[comp][()],
                                 comment=c.decode() if isinstance(c, bytes) else str(c or ""))
    return out


def turned(words: dict, deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the BX and BY words turned by `deg` as `rot_h` turns them."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    x, y = words["BX"].astype(float), words["BY"].astype(float)
    return c * x + s * y, -s * x + c * y


def turn_problems(got: dict, words: dict, deg: float) -> list[str]:
    """Return what is wrong with an archive turned by `deg`; empty when right."""
    problems = []
    hx, hy = got["hx"]["samples"], got["hy"]["samples"]
    h = math.hypot(float(np.mean(hx)), float(np.mean(hy)))
    if abs(float(np.mean(hy))) > 1e-6 * h:
        problems.append(f"mean hy {np.mean(hy):.4g} is not 0 to 1e-6 of |H| {h:.6g}")
    if not float(np.mean(hx)) > 0:
        problems.append(f"mean hx {np.mean(hx):.6g} is not positive")
    want_x, want_y = turned(words, deg)
    if np.max(np.abs(hx - want_x)) > 1e-6 or np.max(np.abs(hy - want_y)) > 1e-6:
        problems.append("hx, hy are not the words turned by the declared angle")
    for comp, suffix in (("hz", "BZ"), ("ex", "EX"), ("ey", "EY")):
        if not np.array_equal(got[comp]["samples"], words[suffix]):
            problems.append(f"{comp} differs from the {suffix} words")
    return problems


def test_turn_at_30() -> Path:
    """R1, R3, R4: the 30 deg field comes out on magnetic north, recorded; 0.0 changes nothing."""
    root = SCRATCH / "az30"
    words = write_site(root, 30.0)
    work = root / "work"
    paths = {tag: ingest_site(edl_survey(root, own), SITE, out_path=work / f"{tag}.h5", overwrite=True)
             for tag, own in (("plain", {}), ("zero", {"rot_h": 0.0}), ("turned", {"rot_h": 30.0}))}
    got = {tag: read_run(path) for tag, path in paths.items()}
    problems = turn_problems(got["turned"], words, 30.0)
    assert not problems, problems
    hx, hy = got["turned"]["hx"]["samples"], got["turned"]["hy"]["samples"]
    print(f"  R1 rot_h 30.0: mean hx {np.mean(hx):.1f}, mean hy {np.mean(hy):.3g} counts "
          f"({abs(np.mean(hy)) / math.hypot(np.mean(hx), np.mean(hy)):.1e} of |H|); hx, hy == the words turned by "
          f"30 deg to 1e-6 counts; hz ex ey == their words ({hx.size} samples)")

    real = ingest._rot_h
    ingest._rot_h = lambda run, site: real(run, type(site)(**{**site.__dict__, "rot_h": -site.rot_h}))
    try:
        mutant = ingest_site(edl_survey(root, {"rot_h": 30.0}), SITE, out_path=work / "mutant.h5", overwrite=True)
    finally:
        ingest._rot_h = real
    caught = turn_problems(read_run(mutant), words, 30.0)
    assert any("mean hy" in p for p in caught), caught
    print(f"  R1 mutation (turned the other way): {caught[0]!r}")

    a, b = all_datasets(paths["plain"]), all_datasets(paths["zero"])
    differ = sorted(set(a) ^ set(b)) + [name for name in a if name in b and not same(a[name], b[name])]
    assert not differ and got["zero"]["comment"] == got["plain"]["comment"], (differ, got["zero"]["comment"])
    mutated = got["zero"]["comment"] + "; rot_h: 0.0 deg applied at ingest"
    assert mutated != got["plain"]["comment"]
    print(f"  R3 rot_h 0.0: all {len(a)} datasets and the run comment as without the key (a comment with the "
          f"0.0 line would differ)")

    comment = got["turned"]["comment"]
    for piece in ("rot_h: 30.0 deg applied at ingest", "before the turn +30.00", "after +0.00"):
        assert piece in comment, (piece, comment)
    for comp in ("hx", "hy"):
        assert "rot_h: 30.0 deg applied at ingest" in got["turned"][comp]["comment"], got["turned"][comp]["comment"]
    assert "rot_h" not in got["turned"]["hz"]["comment"], got["turned"]["hz"]["comment"]
    assert archive_rot_h(paths["turned"], SITE) == 30.0 and archive_rot_h(paths["plain"], SITE) is None
    piece = next(p for p in comment.split("; ") if p.startswith("rot_h"))
    print(f"  R4 run comment {piece!r}; hx and hy channel comments carry it, hz not; archive_rot_h 30.0 "
          f"(None without the key)")
    return paths["turned"]


def test_south_and_tas107() -> None:
    """R2: a sensor turned 180 deg, and TAS107's 157.6 deg, come out with hx positive and hy 0."""
    for azimuth in (180.0, 157.6):
        root = SCRATCH / f"az{azimuth:g}"
        words = write_site(root, azimuth, seed=int(azimuth))
        path = ingest_site(edl_survey(root, {"rot_h": azimuth}), SITE, out_path=root / "work" / "t.h5",
                           overwrite=True)
        got = read_run(path)
        problems = turn_problems(got, words, azimuth)
        assert not problems, (azimuth, problems)
        print(f"  R2 field at {azimuth:g} deg (mean BX {np.mean(words['BX']):.0f}), rot_h {azimuth:g}: mean hx "
              f"{np.mean(got['hx']['samples']):.1f} > 0, mean hy {np.mean(got['hy']['samples']):.3g}")


def refused(make, what: str, expect: str) -> str:
    """Return the message of the ValueError `make()` raises; fail when it raises none or another one."""
    try:
        make()
    except ValueError as exc:
        assert expect in str(exc), (what, exc)
        return str(exc)
    raise AssertionError(f"{what}: accepted")


def test_refusals() -> None:
    """R5: the declarations `Survey.site` and `ingest_site` refuse, and no file is written."""
    root = SCRATCH / "refusals"
    write_site(root, 30.0)
    out = root / "work" / "refused.h5"
    out.unlink(missing_ok=True)
    cases = (
        ("h_from", lambda: edl_survey(root, {"rot_h": 30.0, "h_from": "NB", "channels": ["ex", "ey"]},
                                      extra_sites={"NB": {}}).site(SITE), "h_from"),
        ("defaults", lambda: edl_survey(root, {}, rot_h=30.0).site(SITE), "defaults"),
        ("derived", lambda: edl_survey(root, {}, extra_sites={"HGRL": {"derived_from": SITE, "sample_rate": 1.0,
                                                                         "rot_h": 30.0}}).site("HGRL"), "derived"),
        ("over 180", lambda: edl_survey(root, {"rot_h": 190.0}).site(SITE), "(-180, 180]"),
        ("-180", lambda: edl_survey(root, {"rot_h": -180.0}).site(SITE), "(-180, 180]"),
        ("nan", lambda: edl_survey(root, {"rot_h": float("nan")}).site(SITE), "rot_h"),
        ("bool", lambda: edl_survey(root, {"rot_h": True}).site(SITE), "rot_h"),
        ("no hy", lambda: edl_survey(root, {"rot_h": 30.0, "channels": ["ex", "ey", "hx", "hz"]}).site(SITE), "hy"),
    )
    for what, make, expect in cases:
        message = refused(make, what, expect)
        print(f"  R5 {what}: refused ({message[:90]}...)")
    refused(lambda: ingest_site(edl_survey(root, {"rot_h": 30.0, "h_from": "NB", "channels": ["ex", "ey"]},
                                           extra_sites={"NB": {}}), SITE, out_path=out, overwrite=True),
            "ingest with h_from", "h_from")
    assert not out.exists(), "a refused ingest wrote a file"
    lemi = SCRATCH / "lemi423"
    shutil.rmtree(lemi, ignore_errors=True)
    _write_b423(lemi / "raw" / "S01" / "1624510579.B423", epoch=1624510579, n=4000,
                levels={"Bx": (4.3e7, 2.0e6), "By": (-3.1e7, 1.0e6)}, seed=7)
    target = lemi / "work" / "rot.h5"
    message = refused(lambda: ingest_site(lemi_survey(lemi, {"rot_h": 30.0}), "S01", out_path=target,
                                          overwrite=True), "LEMI-423 chains", "chain")
    print(f"  R5 LEMI-423 (Kmx != Kmy): refused ({message[:110]}...)")


def test_variant_and_derived(turned_path: Path) -> None:
    """R6: the filtered variant and the derived 1 Hz site keep the turned samples and the record."""
    root = SCRATCH / "az30"
    survey = edl_survey(root, {"rot_h": 30.0}, filters=NOTCH)
    raw = ingest_site(survey, SITE, overwrite=True)
    raw_run = read_run(raw)
    assert np.array_equal(raw_run["hx"]["samples"], read_run(turned_path)["hx"]["samples"])
    variant = build_variant(survey, SITE)
    got = read_run(variant)
    assert archive_rot_h(variant, SITE) == 30.0, archive_rot_h(variant, SITE)
    for comp in ("hx", "hy"):
        assert "rot_h: 30.0 deg applied at ingest" in got[comp]["comment"], got[comp]["comment"]
    spec = importlib.util.spec_from_file_location("decimate_site", REPO / "scripts" / "decimate_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    derived = root / "work" / "mth5" / f"{SITE}L.h5"
    runs = module.write_derived(raw, SITE, derived, 1.0)
    assert archive_rot_h(derived, f"{SITE}L") == 30.0, archive_rot_h(derived, f"{SITE}L")
    low = read_run(derived, f"{SITE}L", runs[0]["id"])
    for comp in ("hx", "hy"):
        assert "rot_h: 30.0 deg applied at ingest" in low[comp]["comment"], low[comp]["comment"]
    h = math.hypot(np.mean(low["hx"]["samples"]), np.mean(low["hy"]["samples"]))
    assert abs(np.mean(low["hy"]["samples"])) < 1e-4 * h and np.mean(low["hx"]["samples"]) > 0
    print(f"  R6 variant {variant.name}: channel comments and archive_rot_h 30.0 kept; derived {derived.name} "
          f"({runs[0]['n']} samples at 1 Hz): archive_rot_h 30.0, mean hy {np.mean(low['hy']['samples']):.3g} "
          f"of |H| {h:.6g}")


def test_products() -> None:
    """R7: the sidecar's frame record and the INFO lines carry rot_h, through an EDI and back."""
    from unknown_declination_unit import make_tf

    line = "rot_h: 30.0 deg applied at ingest, hx and hy turned from the sensor axes onto magnetic north"
    tf = make_tf(True)
    tf.station_metadata.runs[0].comments = f"calibration_sha256: none; {line}"
    record = products.frame_record(tf, "survey.yaml")
    assert record["rot_h"] == 30.0, record
    info = products.frame_info_lines(tf)
    assert any(x.startswith("mt_workbench.rot_h=30.0 deg") for x in info), info
    path = SCRATCH / "products" / "R7.edi"
    path.parent.mkdir(parents=True, exist_ok=True)
    products.write_edi(tf, path)
    text = path.read_text(encoding="latin-1")
    assert "mt_workbench.rot_h=30.0 deg" in text, "the EDI lacks the INFO line"
    back = products.read_tf(path)
    assert products.frame_record(back)["rot_h"] == 30.0, products.frame_record(back)
    plain = make_tf(True)
    assert products.frame_record(plain)["rot_h"] is None
    assert not any(x.startswith("mt_workbench.rot_h") for x in products.frame_info_lines(plain))
    mutant = make_tf(True)
    mutant.station_metadata.runs[0].comments = line.replace("rot_h", "rot-h")
    assert products.frame_record(mutant)["rot_h"] is None
    print(f"  R7 frame_record rot_h 30.0; INFO {next(x for x in info if 'rot_h' in x)!r}; in the EDI and read "
          f"back 30.0; without the line None (and a 'rot-h' key gives None)")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutations")[0])
    print()
    turned_archive = test_turn_at_30()
    print("  ok  test_turn_at_30")
    for name, test in (("test_south_and_tas107", test_south_and_tas107), ("test_refusals", test_refusals),
                       ("test_variant_and_derived", lambda: test_variant_and_derived(turned_archive)),
                       ("test_products", test_products)):
        test()
        print(f"  ok  {name}")
    print("\nPASS  ingest_rot_h_unit (5 tests)")
