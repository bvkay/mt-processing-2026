# -*- coding: utf-8 -*-
"""
Unit test for scripts/diagonal_site.py at a site whose pair the ingest turned (rot_e)

At a rot_e site the archive's ex and ey are E_N and E_E, linear
combinations of the two recorded lines, and the shared centre's voltage
cancels only between the lines as recorded, so diagonal_site.py undoes the
turn first (`recorded_lines`). Three synthetic EDL sites at 10 Hz are
written as hourly ASCII files and ingested with `ingest_site` (mt-io's real
EDL chain, the workbench's real `_rot_e`). Each holds a known field
E = (E_n, E_e) in mV/km and a common voltage V(t) of 1e5 words on both
lines, in the logger's words: ex = round(10 g_x E.u(b_x)) + V,
ey = round(10 g_y E.u(b_y)) + V, b the direction a line measures along
(`_e_direction`) and g mt-io's signed dipole gain (-L when b is the
as-laid azimuth, +L when it is the reverse):

- R: 48 m at 45 deg and 50 m at 315 deg (the NF41_2 layout): turned at ingest;
- Q: 50 m at 225 deg and 50 m at 135 deg (the SA009 layout): turned at ingest;
- C: R's raw files word for word, declared 0/90 (an untouched cardinal layout).

Usage:
    python tests/diagonal_site_rot_e_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - the ingest did not turn R and Q (no "rot_e:" provenance line read by
    `archive_rot_e`) or turned C;
  - `recorded_lines` on R's and Q's archives does not return the raw words
    of the hourly files exactly (0 words), or does not refuse the same
    archive read with wrong as-laid azimuths (40/310 at R) or a wrong k;
  - diagonal_site.py on R or Q does not exit 0, or the derived ex differs
    from (EX - V) - (EY - V) of the words anywhere (the common voltage must
    cancel exactly), or R's derived ex differs from C's (the untouched
    layout's diagonal of the same words) anywhere;
  - the derived ex calibrated through its chain (`load_station`) differs
    from E.u(theta_d) by more than one word, with theta_d =
    `diagonal_geometry` of the as-laid azimuths (R: 48 m u(45) - 50 m u(315),
    91.17 deg; Q: 50 u(225) - 50 u(135), 270 deg), or the archive's ex
    metadata does not state that L_d and theta_d;
  - R's run comment lacks "rot_e undone first", or survey.yaml's RD entry
    lacks the as-laid note;
  - `shared_centre_test.run_site` on R (one day, 10-1000 s) does not read
    "holds" with s_obs +1, |g| within 0.03 of 1 and residual coherence
    >= 0.98 on the recorded lines (rot_e undone, its `rot_e` column saying
    so), or, with the undo disabled (`archive_rot_e` patched to None: the
    turned pair, on which V has gains 1.39 and -0.03), it still reads "holds";
  - the control does not fail: the diagonal cut from the turned pair (the
    turn not undone, `write_derived(..., laid=None)`) must leave the common
    voltage in (more than 1e4 words off).
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import diagonal_site as ds  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mt_workbench.ingest import _e_direction, archive_rot_e, default_archive_path, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "diagonal_site.py"
SCRATCH = scratch_dir("diagonal_site_rot_e_unit")
FS = 10.0
T0 = pd.Timestamp("2015-08-10T00:00:00", tz="UTC")
HOURS = 7  # a UTC day must hold 6 h for the shared-centre test
N = int(HOURS * 3600 * FS)
SITES = {"R": (48.0, 45.0, 50.0, 315.0), "Q": (50.0, 225.0, 50.0, 135.0), "C": (48.0, 0.0, 50.0, 90.0)}
SAME_WORDS = {"C": "R"}  # C is R's raw files, declared 0/90
HEADER = ("name: t\ninstrument: edl\nsample_rate: 10\ndata_root: {raw}\nworkspace: {work}\n"
          "defaults:\n  channels: [ex, ey, hx, hy, hz]\n  sensor_type: bartington\n  flip_reversed_dipoles: true\n"
          "sites:\n")


def red(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return unit-variance red noise (integrated white noise, high-passed at 2000 s)."""
    from scipy import signal

    x = np.cumsum(rng.standard_normal(n))
    x = signal.sosfiltfilt(signal.butter(2, (1 / 2000.0) / (FS / 2), "high", output="sos"), x)
    return x / x.std()


def signed_gain(comp: str, length: float, azimuth: float) -> tuple[float, float]:
    """Return (b, g): the direction a line measures along and mt-io's signed dipole gain."""
    b = _e_direction(comp, azimuth)
    return b, (-length if b == float(azimuth) % 360.0 else length)


def make_words(name: str, seed: int) -> dict:
    """Return a site's field, common voltage and logger words."""
    lx, ax, ly, ay = SITES[name]
    rng = np.random.default_rng(seed)
    e_n, e_e, v = 2.0 * red(rng, N), 1.5 * red(rng, N), np.round(1e5 * red(rng, N))
    bx, gx = signed_gain("ex", lx, ax)
    by, gy = signed_gain("ey", ly, ay)
    ux, uy = (math.cos(math.radians(bx)), math.sin(math.radians(bx))), (math.cos(math.radians(by)),
                                                                          math.sin(math.radians(by)))
    words = {"BX": np.round(2.8e6 + 2e4 * red(rng, N)), "BY": np.round(2e4 * red(rng, N)),
             "BZ": np.round(-3.3e6 + 50 * rng.standard_normal(N)),
             "EX": np.round(10 * gx * (ux[0] * e_n + ux[1] * e_e)) + v,
             "EY": np.round(10 * gy * (uy[0] * e_n + uy[1] * e_e)) + v}
    return dict(e_n=e_n, e_e=e_e, v=v, words=words)


def write_files(root: Path, name: str, truth: dict) -> None:
    """Write a site's hourly EDL files and recorder.ini."""
    site = root / "raw" / name
    shutil.rmtree(site, ignore_errors=True)
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{k}_samplerate=10\n" for k in range(5)), encoding="utf-8")
    per = int(3600 * FS)
    for h in range(HOURS):
        when = T0 + pd.Timedelta(hours=h)
        for suffix, values in truth["words"].items():
            np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}", values[h * per:(h + 1) * per].astype("int64"),
                       fmt="%d")


def build(root: Path) -> tuple[Path, dict]:
    """Write survey.yaml and the three sites, ingest them; return the yaml path and the truths."""
    root.mkdir(parents=True, exist_ok=True)
    text = HEADER.format(raw=(root / "raw").as_posix(), work=(root / "work").as_posix())
    for k, (name, (lx, ax, ly, ay)) in enumerate(SITES.items()):
        text += (f"  {name}:\n    dipole_length_ex: {lx}\n    dipole_length_ey: {ly}\n    azimuth_ex: {ax}\n"
                 f"    azimuth_ey: {ay}\n    latitude: -34.0\n    longitude: {139.0 + 0.01 * k}\n    elevation: 10.0\n"
                 f"    declination: 8.0\n    start: '2015-08-10T00:00:00Z'\n    end: '2015-08-10T07:00:00Z'\n")
    path = root / "survey.yaml"
    path.write_bytes(text.encode("utf-8"))
    sv = Survey.from_yaml(path)
    truths = {}
    for k, name in enumerate(SITES):
        truths[name] = truths[SAME_WORDS[name]] if name in SAME_WORDS else make_words(name, 20 + k)
        write_files(root, name, truths[name])
        ingest_site(sv, name, out_path=default_archive_path(sv, name), overwrite=True)
    return path, truths


def first_run(path: Path, station: str) -> dict:
    """Return the first run's channels, ex/ey dipole gains, ex metadata and run comment."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(station, survey=m.surveys_group.groups_list[0]).get_run("sr10_0001")
        out = {c: np.asarray(run.get_channel(c).hdf5_dataset[()], "float64") for c in run.groups_list}
        for c in ("ex", "ey"):
            if c in run.groups_list:
                out["g" + c] = [float(f.gain) for f in run.get_channel(c).channel_response.filters_list
                                if "_dipole_" in f.name][0]
        md = run.get_channel("ex").metadata
        out["meta"] = dict(length=float(md.dipole_length), azimuth=float(md.measurement_azimuth))
        c = run.metadata.comments
        out["comment"] = str(c.value if hasattr(c, "value") else c)
        return out
    finally:
        m.close_mth5()


def test_turned_and_recovered(path: Path, truths: dict) -> None:
    """The ingest turned R and Q (not C); recorded_lines gives the raw words back exactly, and refuses wrong inputs."""
    sv = Survey.from_yaml(path)
    for name in SITES:
        laid = archive_rot_e(default_archive_path(sv, name), name)
        if name == "C":
            assert laid is None, laid
            continue
        assert laid == (SITES[name][1], SITES[name][3]), (name, laid)
        run = first_run(default_archive_path(sv, name), name)
        w = truths[name]["words"]
        assert np.max(np.abs(run["ex"] - w["EX"])) > 1e3, "the archive's ex should be the turned field, not the line"
        x, y, worst = ds.recorded_lines(run["ex"], run["ey"], laid, run["gex"], run["gey"])
        dx, dy = float(np.max(np.abs(x - w["EX"]))), float(np.max(np.abs(y - w["EY"])))
        assert dx == 0.0 and dy == 0.0, (name, dx, dy)
        print(f"  {name}: turned at ingest (laid {laid[0]:g}/{laid[1]:g}); recorded_lines returns the raw words "
              f"exactly (largest fraction before rounding {worst:.1e} words)")
    run = first_run(default_archive_path(sv, "R"), "R")
    for label, laid, gx, gy in (("azimuths 40/310", (40.0, 310.0), run["gex"], run["gey"]),
                                ("k = 1", (45.0, 315.0), run["gex"], -run["gex"])):
        try:
            ds.recorded_lines(run["ex"], run["ey"], laid, gx, gy)
        except ValueError as exc:
            print(f"  refused ({label}): {str(exc)[:120]}")
        else:
            raise AssertionError(f"recorded_lines accepted {label}")


def run_script(path: Path, site: str) -> str:
    """Run diagonal_site.py on a site; return its output, failing on a non-zero exit."""
    run = subprocess.run([sys.executable, str(SCRIPT), str(path), site], capture_output=True, text=True, timeout=900)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text[-3000:]
    return text


def calibrated_error(path: Path, name: str, truth: dict, azimuth: float) -> tuple[float, float]:
    """Return the largest |calibrated derived ex - E.u(theta_d)| in mV/km and the one-word bound."""
    from mt_workbench.timefreq import load_station

    sv = Survey.from_yaml(path)
    rec = load_station(default_archive_path(sv, name), "t", name, comps=("ex",))
    cal = rec.value("ex")
    a = math.radians(azimuth)
    want = math.cos(a) * truth["e_n"] + math.sin(a) * truth["e_e"]
    n = min(cal.size, want.size)
    return float(np.max(np.abs(cal[:n] - want[:n]))), 1.0 / abs(rec.gains["ex"])


def test_script(path: Path, truths: dict) -> None:
    """The script on R, Q and C: cancellation, R == C, the calibration end to end, the notes."""
    for name in ("R", "Q", "C"):
        run_script(path, name)
    sv = Survey.from_yaml(path)
    got = {n: first_run(default_archive_path(sv, n + "D"), n + "D") for n in ("R", "Q", "C")}
    for name in ("R", "Q"):
        lx, ax, ly, ay = SITES[name]
        w, v = truths[name]["words"], truths[name]["v"]
        worst = float(np.max(np.abs(got[name]["ex"] - ((w["EX"] - v) - (w["EY"] - v)))))
        assert worst == 0.0, (name, worst)
        geo = ds.diagonal_geometry(lx, ax, ly, ay, 1)
        meta = got[name]["meta"]
        assert abs(meta["length"] - geo["length"]) < 1e-9 and abs(meta["azimuth"] - geo["azimuth"]) < 1e-9, (meta, geo)
        err, word = calibrated_error(path, name + "D", truths[name], geo["azimuth"])
        assert err <= word * 1.0001, (name, err, word)
        assert "rot_e undone first" in got[name]["comment"], got[name]["comment"][:400]
        print(f"  {name}D: V cancels exactly (0 words); L_d {geo['length']:.4f} m, theta_d {geo['azimuth']:.4f} deg; "
              f"calibrated error {err:.3g} mV/km (one word {word:.3g})")
    same = float(np.max(np.abs(got["R"]["ex"] - got["C"]["ex"])))
    assert same == 0.0, same
    print(f"  RD's derived ex equals CD's (the untouched 0/90 declaration of the same words): max |diff| {same}")
    entry = Survey.from_yaml(path).config["sites"]["RD"]
    assert "rot_e turn undone first (lines laid 45/315)" in entry["notes"], entry["notes"]


def test_control(path: Path, truths: dict) -> None:
    """Without the turn undone the common voltage stays in: the criterion can fail."""
    sv = Survey.from_yaml(path)
    out = SCRATCH / "control_RD.h5"
    ds.write_derived(default_archive_path(sv, "R"), "R", out, 1, laid=None)
    got = first_run(out, "RD")
    w, v = truths["R"]["words"], truths["R"]["v"]
    worst = float(np.max(np.abs(got["ex"] - ((w["EX"] - v) - (w["EY"] - v)))))
    assert worst > 1e4, worst
    print(f"  control (the turned pair subtracted): {worst:.3g} words off -> the cancellation criterion trips")


def test_centre(path: Path) -> None:
    """The shared-centre test reads the recorded lines at a rot_e site; on the turned pair it would not hold."""
    import mt_workbench.ingest as ingest
    import shared_centre_test as sct

    row = sct.run_site(str(path), "R", 1, (10.0, 1000.0))["row"]
    assert row["verdict"] == "holds" and row["s_obs"] == 1, row
    assert abs(row["resid_gain"] - 1) < 0.03 and row["resid_coh"] >= 0.98, row
    assert row["rot_e"] == "undone (laid 45/315)", row["rot_e"]
    print(f"  R (rot_e undone): {row['verdict']}, residual coh {row['resid_coh']:.3f}, |g| {row['resid_gain']:.3f}, "
          f"s_obs {row['s_obs']:+d}")
    keep = ingest.archive_rot_e
    ingest.archive_rot_e = lambda *_a, **_k: None
    try:
        bad = sct.run_site(str(path), "R", 1, (10.0, 1000.0))["row"]
    finally:
        ingest.archive_rot_e = keep
    assert bad["verdict"] != "holds", bad
    print(f"  control, the turned pair: {bad['verdict']}, residual coh {bad['resid_coh']:.3f}, |g| "
          f"{bad['resid_gain']:.3f} -> the undo is what makes the model readable")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1])
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    survey_path, site_truths = build(root)
    test_turned_and_recovered(survey_path, site_truths)
    print("  ok  test_turned_and_recovered")
    test_script(survey_path, site_truths)
    print("  ok  test_script")
    test_centre(survey_path)
    print("  ok  test_centre")
    test_control(survey_path, site_truths)
    print("  ok  test_control")
    print("\nPASS  diagonal_site_rot_e_unit (4 tests)")
