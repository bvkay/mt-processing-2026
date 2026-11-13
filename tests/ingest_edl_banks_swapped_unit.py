# -*- coding: utf-8 -*-
"""
Unit test for an EDL site whose magnetometer and electrode cables sat in each other's banks (`edl_banks_swapped`)

SA104A and SA104B of South Australia AusLAMP 2013-2018 ("swapped channels
1-3, 4-6" in the field notes), and SA073 and SA098 with the same signature,
recorded the fluxgate's x and y on the electric bank (the .EX and .EY files
hold the main field, |H|/IGRF 0.996-1.06) and the electrode lines on the
magnetometer bank (.BX matches SA104C's E at 0.98 coherence); the .BZ file
holds the electric bank's spare input, coherent with nothing, and the
fluxgate's z was not recorded. Declared
`edl_banks_swapped: true`, ingest stores the .EX words as hx and the .EY
words as hy, read through the magnetometer chain, and the .BX words as ex
and the .BY words as ey, read through the electric chain built from the
site's declared dipole lengths and azimuths; hz is not stored. Each
channel keeps the chain of the sensor whose signal it holds (both banks
of the PR6-24 store microVolt as recorded; the reader's chains are the
sensors': the Bartington stage, the dipole and the terminal box).

The independent observable: the same words written to disk under the
exchanged extensions (EX's words as .BX, and so on) and ingested without
the key are what a correctly wired site would have produced. The keyed
site's archive must equal that one.

Usage:
    python tests/ingest_edl_banks_swapped_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - B1: with the key (ex laid at 180 deg, so the reversed-dipole sign
    applies, and `rot_h: 10.0`), the archive's hx, hy, ex, ey differ in any
    stored sample, in the chain (names and gains) or in the calibrated
    series (mth5's `remove_instrument_response`, to 1e-12) from the
    archive of the site written with the files exchanged on disk and
    ingested without the key; or the archive holds hz;
  - B2: the run comment lacks "edl_banks_swapped:", the station provenance
    lacks it, or hx's channel comment does not name the .EX file and ex's
    the .BX file;
  - B3: `edl_banks_swapped: false` differs from no key in any channel or the
    number of channels;
  - B4: `SiteConfig` accepts a non-bool; `Survey.site` accepts the key with
    `h_from` (the site's own H is the point) or with the site's own
    `channels:` naming hz (not recorded); ingest accepts the key on a
    LEMI-423 or LEMI-424 site.

Mutations: with the key ignored (files read as named) B1 must fail on the
samples; with the chains exchanged together with the samples (each channel
keeping its input's chain) B1 must fail on the chains. Both run without
`rot_h` (amended after the first passing run, in which mutation 2 was
stopped by rot_h's own refusal of unequal hx/hy chains rather than by the
chain comparison).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import SiteConfig, Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_swap_e_unit import read_channels  # noqa: E402

SCRATCH = scratch_dir("ingest_edl_banks_swapped_unit")
RUN = "sr10_0001"
COMPS = ("hx", "hy", "ex", "ey")
# where each file's words go on disk for the correctly wired twin
EXCHANGED = {"EX": "BX", "EY": "BY", "BX": "EX", "BY": "EY"}
OWN = {"azimuth_ex": 180.0, "azimuth_ey": 90.0, "dipole_length_ex": 48.0, "dipole_length_ey": 47.0,
       "rot_h": 10.0, "channels": ["ex", "ey", "hx", "hy"]}


def write_sites(root: Path) -> None:
    """Write site SWP (cables in each other's banks) and REF (the same words under the exchanged extensions)."""
    shutil.rmtree(root, ignore_errors=True)
    rng = np.random.default_rng(104)
    for name in ("SWP", "REF"):
        site = root / "raw" / name
        (site / "config").mkdir(parents=True)
        (site / "config" / "recorder.ini").write_text(
            "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    for stamp in ("141220000000", "141220000500"):
        words = {
            # the fluxgate on the electric bank: a main field plus variation, ~25,000 nT x 142.857 uV/nT
            "EX": 3_600_000 + rng.integers(-20_000, 20_000, 3000),
            "EY": 660_000 + rng.integers(-20_000, 20_000, 3000),
            # the electrodes on the magnetometer bank: small potentials
            "BX": 175_000 + rng.integers(-5_000, 5_000, 3000),
            "BY": -228_000 + rng.integers(-5_000, 5_000, 3000),
            "BZ": 127_000 + rng.integers(-50, 50, 3000),
        }
        for suffix, values in words.items():
            np.savetxt(root / "raw" / "SWP" / f"SWP_{stamp}.{suffix}", values, fmt="%d")
            ref = EXCHANGED.get(suffix, suffix)
            np.savetxt(root / "raw" / "REF" / f"REF_{stamp}.{ref}", values, fmt="%d")


def survey(root: Path, swp: dict, ref: dict | None = None, instrument: str = "edl") -> Survey:
    """Build the two-site survey."""
    return Survey({"name": "t", "instrument": instrument, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "flip_reversed_dipoles": True,
                                "sensor_type": "bartington"},
                   "sites": {"SWP": swp, "REF": ref if ref is not None else dict(OWN)}}, root)


def bank_problems(got: dict, ref: dict) -> list[str]:
    """Return what differs between the keyed site's channels and the correctly wired twin's."""
    out = []
    for comp in COMPS:
        if not np.array_equal(got[comp]["samples"], ref[comp]["samples"]):
            out.append(f"{comp} samples differ from the wired twin's")
        if got[comp]["chain"] != ref[comp]["chain"]:
            out.append(f"{comp} chain {got[comp]['chain']} != {ref[comp]['chain']}")
        a, b = got[comp]["calibrated"], ref[comp]["calibrated"]
        if a.shape != b.shape or not np.allclose(a, b, rtol=1e-12, atol=1e-12 * np.max(np.abs(b))):
            out.append(f"{comp} calibrated differs from the wired twin's")
    return out


def channels_in(path: Path, station: str) -> list[str]:
    """Return the channel names of the first run."""
    import h5py

    with h5py.File(path, "r") as f:
        g = f[f"Experiment/Surveys/t/Stations/{station}/{RUN}"]
        return sorted(k for k in g if isinstance(g[k], h5py.Dataset))


def provenance(path: Path, station: str) -> str:
    """Return the station's provenance comment."""
    import h5py

    with h5py.File(path, "r") as f:
        v = f[f"Experiment/Surveys/t/Stations/{station}"].attrs.get("provenance.comments")
    return v.decode() if isinstance(v, bytes) else str(v or "")


def test_banks() -> None:
    """B1, B2, B3: the exchange against the wired twin, the record, and no change with false."""
    root = SCRATCH / "pair"
    write_sites(root)
    work = root / "work"
    sv = survey(root, {**OWN, "edl_banks_swapped": True})
    ref_path = ingest_site(sv, "REF", out_path=work / "ref.h5", overwrite=True)
    ref = read_channels(ref_path, "REF", RUN, COMPS)
    path = ingest_site(sv, "SWP", out_path=work / "swp.h5", overwrite=True)
    got = read_channels(path, "SWP", RUN, COMPS)
    problems = bank_problems(got, ref)
    if "hz" in channels_in(path, "SWP"):
        problems.append("hz stored")
    assert not problems, problems
    print(f"  B1 edl_banks_swapped: hx hy ex ey == the wired twin's (samples, chains, calibrated); hx chain "
          f"{[n for n, _ in got['hx']['chain']]}, ex chain {got['ex']['chain']}; no hz")

    assert "edl_banks_swapped:" in got["comment"], got["comment"]
    assert "edl_banks_swapped:" in provenance(path, "SWP"), provenance(path, "SWP")
    assert ".EX" in got["hx"]["comment"] and ".BX" in got["ex"]["comment"], (got["hx"]["comment"], got["ex"]["comment"])
    print(f"  B2 run comment, provenance and channel comments record it (hx: {got['hx']['comment'][-90:]!r})")

    real = ingest._edl_banks_swapped

    def ignored(run, site):
        """Mutation 1: the key ignored."""
        return None

    def with_chains(run, site):
        """Mutation 2: the chains exchanged with the samples."""
        chains = {c: run.dataset[c].attrs.get("filters") for c in COMPS}
        note = real(run, site)
        for a, b in (("hx", "ex"), ("hy", "ey")):
            run.dataset[a].attrs["filters"], run.dataset[b].attrs["filters"] = chains[b], chains[a]
        return note

    # the mutations run without rot_h on either site, so the chain comparison itself catches them (with rot_h,
    # rot_h's own refusal of unequal hx/hy chains would stop the mutant before any comparison)
    flat = {k: v for k, v in OWN.items() if k != "rot_h"}
    sv_flat = survey(root, {**flat, "edl_banks_swapped": True}, dict(flat))
    ref_flat = read_channels(ingest_site(sv_flat, "REF", out_path=work / "ref_flat.h5", overwrite=True), "REF", RUN,
                             COMPS)
    good = bank_problems(read_channels(ingest_site(sv_flat, "SWP", out_path=work / "swp_flat.h5", overwrite=True),
                                       "SWP", RUN, COMPS), ref_flat)
    assert not good, good
    for mutation, word in ((ignored, "samples"), (with_chains, "chain")):
        ingest._edl_banks_swapped = mutation
        try:
            mpath = ingest_site(sv_flat, "SWP", out_path=work / "m.h5", overwrite=True)
            comps = [c for c in COMPS if c in channels_in(mpath, "SWP")]
            caught = bank_problems(read_channels(mpath, "SWP", RUN, comps), ref_flat) if comps == list(COMPS) else \
                [f"samples: channels {comps}"]
        finally:
            ingest._edl_banks_swapped = real
        assert any(word in p for p in caught), (mutation.__name__, caught)
        print(f"  B1 mutation ({mutation.__doc__.strip()}): {[p for p in caught if word in p][0][:100]!r}")

    plain = ingest_site(survey(root, dict(OWN)), "SWP", out_path=work / "plain.h5", overwrite=True)
    false = ingest_site(survey(root, {**OWN, "edl_banks_swapped": False}), "SWP", out_path=work / "false.h5",
                        overwrite=True)
    a, b = (read_channels(p, "SWP", RUN, COMPS) for p in (plain, false))
    assert channels_in(plain, "SWP") == channels_in(false, "SWP")
    assert all(np.array_equal(a[c]["samples"], b[c]["samples"]) and a[c]["chain"] == b[c]["chain"] for c in COMPS)
    print("  B3 edl_banks_swapped: false == no key")


def test_refusals() -> None:
    """B4: a non-bool, h_from, an own channels list with hz, another recorder."""
    for bad in ("yes", 1, None):
        try:
            SiteConfig(name="X", edl_banks_swapped=bad)
        except ValueError as exc:
            assert "edl_banks_swapped" in str(exc), exc
        else:
            raise AssertionError(f"edl_banks_swapped {bad!r} accepted")
    root = SCRATCH / "pair"
    for own, tag in (({**OWN, "edl_banks_swapped": True, "h_from": "REF", "rot_h": 0.0, "channels": ["ex", "ey"]},
                      "h_from"),
                     ({**OWN, "edl_banks_swapped": True, "channels": ["ex", "ey", "hx", "hy", "hz"]}, "hz")):
        try:
            survey(root, own).site("SWP")
        except ValueError as exc:
            assert "edl_banks_swapped" in str(exc), exc
        else:
            raise AssertionError(f"edl_banks_swapped with {tag} accepted")
    for instrument in ("lemi423", "lemi424"):
        sv = survey(root, {**OWN, "edl_banks_swapped": True}, instrument=instrument)
        try:
            ingest._check_banks_instrument(sv.site("SWP"), instrument)
        except ValueError as exc:
            assert "edl_banks_swapped" in str(exc), exc
        else:
            raise AssertionError(f"edl_banks_swapped on {instrument} accepted")
    print("  B4 refused: non-bool, with h_from, own channels naming hz, a LEMI-423 or LEMI-424 site")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    for test in (test_banks, test_refusals):
        test()
        print(f"  ok  test {test.__name__}")
    print("\nPASS  ingest_edl_banks_swapped_unit (2 tests)")
