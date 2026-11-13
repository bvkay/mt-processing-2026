# -*- coding: utf-8 -*-
"""
Unit test for the turn of the electric pair onto magnetic north and east at ingest (`rot_e`)

A tiny EDL site (PR6-24, two 300 s stamps at 10 Hz, as tests/ingest_rot_h_unit.py builds one) "records" a
known synthetic geomagnetic-frame electric field: E_N and E_E, two independent band-limited series in mV/km,
seen by a line laid at azimuth a (clockwise from magnetic north) as E_a = E_N cos a + E_E sin a, and written
to the EX and EY files as the inverse of the whole EDL electric chain: 1 uV per count, the x10 terminal box,
the dipole length and the EDL hardware's inversion (counts = -10 L E_a for every direction a, which is the
rule mt-io's dipole filter encodes: a line at 0 calibrates with gain -L, a line at 180 with +L). The words
are written with 17 significant digits, which mt-io's ASCII reader reads back exactly, so the test's
tolerances measure the turn and not a rounding of the words. `ingest_site` writes the archive; the test
calibrates each electric channel itself, the stored samples divided by the archive's own chain response
(checked flat and real over 1e-4 .. 4 Hz first), and compares with E_N and E_E.

Usage:
    python tests/rot_e_unit.py                 # the test
    python tests/rot_e_unit.py --write-oracle  # T2's oracle: run once with the code before rot_e

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if (each scenario repeats its criterion in a comment before its asserts):
  - T1 exactness: lines at (45, 135), 48 and 50 m: the calibrated ex and ey differ from E_N and E_E by more
    than 1e-9 of max|E|, or the stored measurement azimuths are not 0 and 90;
  - T2 regression at the cardinal pairs (0, 90), (180, 270), (0, 270), (180, 90): ex's and ey's stored
    samples, chain names and chain responses differ from the oracle written by the code before rot_e (the
    `--write-oracle` run) by more than 1e-12 relative, or the calibrated pair differs from (E_N, E_E) by more
    than 1e-9 (the sign rule's expectation, independent of the oracle), or the archive carries a rot_e line;
  - T3 the general inverse: (10, 100), (210, 300) and (185, 95) are not exact to 1e-9 as in T1;
  - T4 the guard: (180, 27) or (90, 180) ingests, or its ValueError does not name the site, both azimuths and
    the angle between the lines; (2, 90) does not ingest exact to 1e-9; a non-cardinal pair under
    `flip_reversed_dipoles: false`, under `layout_north: geographic`, or on a site that keeps one electric
    line, ingests;
  - T5 provenance: the ex and ey channel comments and the station's provenance do not carry "rot_e: ex 45.0
    deg, ey 135.0 deg as laid, turned onto magnetic north and east at ingest", the run comment does not carry
    that line with the angle between the lines, hx carries it, `archive_rot_e` does not read (45.0, 135.0)
    back, or a (0, 90) or (180, 270) archive carries a rot_e line or `archive_rot_e` reads anything but None;
  - T6 mutation: with the turn forced to the identity (`ingest._rot_e_matrix` monkeypatched to return the
    unit matrix) a (45, 135) archive still passes T1's check.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import traceback
from pathlib import Path

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("rot_e_unit")
ORACLE = SCRATCH / "oracle_pre_rot_e"
SITE = "HGE"
RUN = "sr10_0001"
STAMPS = ("090320000000", "090320000500")
PER_FILE = 3000
FS = 10.0
LX, LY = 48.0, 50.0
FREQS = np.logspace(-4, math.log10(4.0), 15)
EXACT = 1e-9
CARDINAL = ((0.0, 90.0), (180.0, 270.0), (0.0, 270.0), (180.0, 90.0))
EXPECTED_NOTE = "rot_e: ex 45.0 deg, ey 135.0 deg as laid, turned onto magnetic north and east at ingest"


def band_limited(rng, n: int, scale: float, corner_hz: float) -> np.ndarray:
    """Return n samples of white noise low-passed (FFT brick wall) at `corner_hz`, scaled to std `scale`."""
    spec = np.fft.rfft(rng.normal(0.0, 1.0, n))
    spec[np.fft.rfftfreq(n, 1.0 / FS) > corner_hz] = 0.0
    out = np.fft.irfft(spec, n)
    return scale * out / np.std(out)


def field(seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    """Return the geomagnetic-frame truth (E_N, E_E) in mV/km: independent, band-limited, with offsets."""
    rng = np.random.default_rng(seed)
    n = PER_FILE * len(STAMPS)
    return (12.0 + band_limited(rng, n, 40.0, 0.5),
            -7.0 + band_limited(rng, n, 25.0, 0.3))


def along(e_n: np.ndarray, e_e: np.ndarray, azimuth: float) -> np.ndarray:
    """Return the field component along a line laid at `azimuth` deg clockwise from magnetic north."""
    a = math.radians(azimuth)
    return e_n * math.cos(a) + e_e * math.sin(a)


def write_site(root: Path, ax: float, ay: float, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    """Write the EDL site under `root`/raw with its lines at (ax, ay); return the truth (E_N, E_E).

    The EX and EY words are the inverse of the EDL electric chain: counts = -10 L E_a (uV, x10 box, the
    hardware inversion). The magnetics are integer noise (not under test)."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    e_n, e_e = field(seed)
    rng = np.random.default_rng(seed + 1)
    n = e_n.size
    words = {"EX": -10.0 * LX * along(e_n, e_e, ax), "EY": -10.0 * LY * along(e_n, e_e, ay),
             "BX": rng.integers(-200_000, 200_000, n), "BY": rng.integers(-200_000, 200_000, n),
             "BZ": rng.integers(-200_000, 200_000, n)}
    for k, stamp in enumerate(STAMPS):
        for suffix, values in words.items():
            fmt = "%.17g" if suffix.startswith("E") else "%d"
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", values[k * PER_FILE:(k + 1) * PER_FILE], fmt=fmt)
    return e_n, e_e


def edl_survey(root: Path, ax: float, ay: float, channels=("ex", "ey", "hx", "hy", "hz"), **defaults) -> Survey:
    """Build the one-site EDL survey over `root` with the lines at (ax, ay)."""
    base = {"dipole_length_ex": LX, "dipole_length_ey": LY, "channels": list(channels),
            "flip_reversed_dipoles": True, "layout_north": "magnetic"}
    return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                   "workspace": str(root / "work"), "defaults": {**base, **defaults},
                   "sites": {SITE: {"azimuth_ex": ax, "azimuth_ey": ay}}}, root)


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def read_archive(path: Path) -> dict:
    """Return the run comment, the station provenance, and per channel: samples, comment, azimuth, chain."""
    from mth5.mth5 import MTH5
    out = {}
    with h5py.File(path, "r") as f:
        station = f[f"Experiment/Surveys/t/Stations/{SITE}"]
        group = station[RUN]
        out["comment"] = _text(group.attrs.get("comments"))
        out["provenance"] = _text(station.attrs.get("provenance.comments"))
        for comp in ("ex", "ey", "hx"):
            ds = group[comp]
            out[comp] = dict(samples=ds[()].astype("float64"), comment=_text(ds.attrs.get("comments")),
                             azimuth=float(ds.attrs.get("measurement_azimuth")))
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(SITE, survey="t").get_run(RUN)
        if not out["provenance"]:
            out["provenance"] = _text(m.get_station(SITE, survey="t").metadata.provenance.comments.value)
        for comp in ("ex", "ey"):
            response = run.get_channel(comp).channel_response
            out[comp]["chain"] = [f.name for f in response.filters_list]
            out[comp]["response"] = np.asarray(response.complex_response(FREQS))
    finally:
        m.close_mth5()
    return out


def calibrated(got: dict, comp: str) -> np.ndarray:
    """Return a channel's samples divided by its archive chain, after checking the chain is flat and real."""
    r = got[comp]["response"]
    assert np.max(np.abs(r - r[0])) <= 1e-12 * abs(r[0]) and abs(r[0].imag) <= 1e-12 * abs(r[0]), \
        (comp, "chain not flat and real", r[:3])
    return got[comp]["samples"] / r[0].real


def exact_problems(got: dict, e_n: np.ndarray, e_e: np.ndarray) -> list[str]:
    """Return what is wrong with an archive whose ex, ey must be E_N, E_E on azimuths 0 and 90; empty if right."""
    problems = []
    scale = max(np.max(np.abs(e_n)), np.max(np.abs(e_e)))
    for comp, truth in (("ex", e_n), ("ey", e_e)):
        err = float(np.max(np.abs(calibrated(got, comp) - truth)) / scale)
        if not err <= EXACT:
            problems.append(f"calibrated {comp} differs from the truth by {err:.3e} of max|E| (> {EXACT:g})")
    if (got["ex"]["azimuth"], got["ey"]["azimuth"]) != (0.0, 90.0):
        problems.append(f"stored azimuths {got['ex']['azimuth']:g}, {got['ey']['azimuth']:g}, not 0 and 90")
    return problems


def max_err(got: dict, e_n, e_e) -> float:
    scale = max(np.max(np.abs(e_n)), np.max(np.abs(e_e)))
    return max(float(np.max(np.abs(calibrated(got, "ex") - e_n)) / scale),
               float(np.max(np.abs(calibrated(got, "ey") - e_e)) / scale))


def ingest_pair(tag: str, ax: float, ay: float, **defaults) -> tuple[dict, np.ndarray, np.ndarray, Path]:
    """Write the fixture for (ax, ay), ingest it, read it back."""
    root = SCRATCH / tag
    e_n, e_e = write_site(root, ax, ay)
    path = ingest_site(edl_survey(root, ax, ay, **defaults), SITE, out_path=root / "work" / f"{tag}.h5",
                       overwrite=True)
    return read_archive(path), e_n, e_e, path


def _tag(ax: float, ay: float) -> str:
    return f"az_{ax:g}_{ay:g}".replace(".", "p")


# ---------------------------------------------------------------- the oracle (run before the change)

def write_oracle() -> None:
    """Write T2's oracle from the code as it stands (to be run once, before rot_e exists)."""
    ORACLE.mkdir(parents=True, exist_ok=True)
    meta = {}
    for ax, ay in CARDINAL:
        got, _e_n, _e_e, _ = ingest_pair("oracle_" + _tag(ax, ay), ax, ay)
        np.savez(ORACLE / f"{_tag(ax, ay)}.npz",
                 ex=got["ex"]["samples"], ey=got["ey"]["samples"],
                 ex_response=got["ex"]["response"], ey_response=got["ey"]["response"])
        meta[_tag(ax, ay)] = {"ex_chain": got["ex"]["chain"], "ey_chain": got["ey"]["chain"],
                              "ex_azimuth": got["ex"]["azimuth"], "ey_azimuth": got["ey"]["azimuth"]}
        print(f"  oracle {_tag(ax, ay)}: ex chain {got['ex']['chain']}, ey chain {got['ey']['chain']}")
    meta["written_by"] = "tests/rot_e_unit.py --write-oracle, with ingest.py before rot_e (has _rot_e: " \
                         f"{hasattr(ingest, '_rot_e')})"
    (ORACLE / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"  oracle written to {ORACLE}")


# ---------------------------------------------------------------- the scenarios

def test_t1_exactness() -> None:
    """T1: lines at (45, 135), 48 and 50 m, come out as E_N and E_E on azimuths 0 and 90."""
    got, e_n, e_e, _ = ingest_pair("t1", 45.0, 135.0)
    # fails if the calibrated ex, ey differ from E_N, E_E by more than 1e-9 of max|E| or the azimuths are not 0, 90
    problems = exact_problems(got, e_n, e_e)
    assert not problems, problems
    print(f"  T1 (45, 135), 48/50 m: calibrated ex, ey == E_N, E_E to {max_err(got, e_n, e_e):.2e} of max|E|; "
          f"azimuths {got['ex']['azimuth']:g}, {got['ey']['azimuth']:g}; chains ex {got['ex']['chain']}, "
          f"ey {got['ey']['chain']}")


def test_t2_cardinal_regression() -> None:
    """T2: the cardinal pairs are exactly today's path (the oracle) and the sign rule's expectation."""
    meta_path = ORACLE / "meta.json"
    # fails if the oracle written by the pre-rot_e code is missing (the regression cannot be checked without it)
    assert meta_path.is_file(), f"no oracle at {ORACLE}: run --write-oracle with the code before rot_e"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for ax, ay in CARDINAL:
        tag = _tag(ax, ay)
        got, e_n, e_e, path = ingest_pair("t2_" + tag, ax, ay)
        want = np.load(ORACLE / f"{tag}.npz")
        for comp in ("ex", "ey"):
            # fails if the samples, chain names or responses differ from the oracle by more than 1e-12 relative
            s, w = got[comp]["samples"], want[comp]
            assert s.shape == w.shape and np.max(np.abs(s - w)) <= 1e-12 * np.max(np.abs(w)), (tag, comp)
            assert got[comp]["chain"] == meta[tag][f"{comp}_chain"], (tag, comp, got[comp]["chain"])
            r, wr = got[comp]["response"], want[f"{comp}_response"]
            assert np.max(np.abs(r - wr)) <= 1e-12 * np.max(np.abs(wr)), (tag, comp, r[:2], wr[:2])
            assert got[comp]["azimuth"] == meta[tag][f"{comp}_azimuth"], (tag, comp, got[comp]["azimuth"])
        # fails if the calibrated pair is not (E_N, E_E) to 1e-9 (the sign rule's expectation)
        problems = exact_problems(got, e_n, e_e)
        assert not problems, (tag, problems)
        # fails if a cardinal archive records a turn
        assert "rot_e" not in got["comment"] + got["provenance"] + got["ex"]["comment"] + got["ey"]["comment"], tag
        print(f"  T2 ({ax:g}, {ay:g}): samples, chains, responses, azimuths == the pre-rot_e oracle; calibrated "
              f"== (E_N, E_E) to {max_err(got, e_n, e_e):.1e}; no rot_e line")


def test_t3_general_inverse() -> None:
    """T3: (10, 100), (210, 300) and (185, 95) are exact."""
    for ax, ay in ((10.0, 100.0), (210.0, 300.0), (185.0, 95.0)):
        got, e_n, e_e, _ = ingest_pair("t3_" + _tag(ax, ay), ax, ay)
        # fails if the calibrated ex, ey differ from E_N, E_E by more than 1e-9 or the azimuths are not 0, 90
        problems = exact_problems(got, e_n, e_e)
        assert not problems, ((ax, ay), problems)
        print(f"  T3 ({ax:g}, {ay:g}): exact to {max_err(got, e_n, e_e):.2e}; ex chain {got['ex']['chain']}, "
              f"ey chain {got['ey']['chain']}")


def test_t4_guard() -> None:
    """T4: (180, 27) and (90, 180) refused, naming the site, both azimuths and the angle; (2, 90) passes."""
    for ax, ay, angle in ((180.0, 27.0, 27.0), (90.0, 180.0, 90.0)):
        root = SCRATCH / ("t4_" + _tag(ax, ay))
        write_site(root, ax, ay)
        out = root / "work" / "refused.h5"
        # fails if the pair ingests, or the message misses the site, either azimuth or the angle between the lines
        try:
            ingest_site(edl_survey(root, ax, ay), SITE, out_path=out, overwrite=True)
        except ValueError as exc:
            msg = str(exc)
            for piece in (SITE, f"{ax:g}", f"{ay:g}", f"angle {angle:g}"):
                assert piece in msg, ((ax, ay), piece, msg)
            assert not out.exists(), "a refused pair left an archive"
            print(f"  T4 ({ax:g}, {ay:g}) refused: {msg}")
            continue
        raise AssertionError(f"({ax:g}, {ay:g}) ingested")
    got, e_n, e_e, _ = ingest_pair("t4_" + _tag(2.0, 90.0), 2.0, 90.0)
    # fails if (2, 90), 88 deg between the lines, is refused or not exact to 1e-9
    problems = exact_problems(got, e_n, e_e)
    assert not problems, problems
    print(f"  T4 (2, 90) (88 deg apart) ingested, exact to {max_err(got, e_n, e_e):.2e}")
    for label, extra in (("flip_reversed_dipoles false", {"flip_reversed_dipoles": False}),
                         ("layout_north geographic", {"layout_north": "geographic"}),
                         ("one electric line kept", {"channels": ("ex", "hx", "hy", "hz")})):
        root = SCRATCH / "t4_cond"
        write_site(root, 45.0, 135.0)
        kwargs = dict(extra)
        channels = kwargs.pop("channels", ("ex", "ey", "hx", "hy", "hz"))
        # fails if a non-cardinal pair ingests under a condition the turn cannot honour
        try:
            ingest_site(edl_survey(root, 45.0, 135.0, channels=channels, **kwargs), SITE,
                        out_path=root / "work" / "refused.h5", overwrite=True)
        except ValueError as exc:
            print(f"  T4 (45, 135) with {label} refused: {exc}")
            continue
        raise AssertionError(f"(45, 135) with {label} ingested")


def test_t5_provenance() -> None:
    """T5: the rot_e lines are written and read back; a cardinal site carries none."""
    got, _e_n, _e_e, path = ingest_pair("t5", 45.0, 135.0)
    # fails if the ex or ey channel comment or the station provenance lacks the line, or hx carries it
    for comp in ("ex", "ey"):
        assert EXPECTED_NOTE in got[comp]["comment"], (comp, got[comp]["comment"])
    assert "rot_e" not in got["hx"]["comment"], got["hx"]["comment"]
    assert EXPECTED_NOTE in got["provenance"], got["provenance"]
    # fails if the run comment lacks the line with the angle between the lines
    piece = next((p for p in got["comment"].split("; ") if p.startswith("rot_e")), "")
    assert piece.startswith(EXPECTED_NOTE) and "angle between the lines 90.00 deg" in piece, got["comment"]
    # fails if archive_rot_e does not read (45.0, 135.0) back
    assert ingest.archive_rot_e(path, SITE) == (45.0, 135.0), ingest.archive_rot_e(path, SITE)
    print(f"  T5 run comment {piece!r}; ex, ey comments and the station provenance carry it, hx not; "
          f"archive_rot_e {ingest.archive_rot_e(path, SITE)}")
    for ax, ay in ((0.0, 90.0), (180.0, 270.0)):
        got, _e_n, _e_e, path = ingest_pair("t5_" + _tag(ax, ay), ax, ay)
        # fails if a cardinal archive carries a rot_e line or archive_rot_e reads anything but None
        text = got["comment"] + got["provenance"] + got["ex"]["comment"] + got["ey"]["comment"]
        assert "rot_e" not in text, ((ax, ay), text)
        assert ingest.archive_rot_e(path, SITE) is None, (ax, ay)
        print(f"  T5 ({ax:g}, {ay:g}): no rot_e line, archive_rot_e None")


def test_t6_mutation() -> None:
    """T6: with the turn forced to the identity, T1's check fails."""
    real = ingest._rot_e_matrix
    ingest._rot_e_matrix = lambda *_a, **_k: np.eye(2)
    try:
        got, e_n, e_e, _ = ingest_pair("t6", 45.0, 135.0)
    finally:
        ingest._rot_e_matrix = real
    # fails if the identity turn still passes T1's check (the check could not see a missing turn)
    caught = exact_problems(got, e_n, e_e)
    assert any("calibrated ex" in p for p in caught), caught
    print(f"  T6 mutation (identity turn) caught: {caught[0]!r}")


def main() -> int:
    if "--write-oracle" in sys.argv[1:]:
        write_oracle()
        return 0
    failed = []
    for test in (test_t1_exactness, test_t2_cardinal_regression, test_t3_general_inverse, test_t4_guard,
                 test_t5_provenance, test_t6_mutation):
        print(f"{test.__name__}:")
        try:
            test()
        except Exception:  # noqa: BLE001  (every scenario runs; the failures are reported together)
            failed.append(test.__name__)
            print(f"  FAIL {test.__name__}:\n" + "".join("    " + line for line in
                                                          traceback.format_exc().splitlines(True)[-6:]))
    print(f"rot_e_unit: {6 - len(failed)} of 6 scenarios passed" + (f"; FAILED {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
