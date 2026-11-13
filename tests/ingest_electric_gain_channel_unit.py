# -*- coding: utf-8 -*-
"""
Unit test for a per-channel EDL electric gain (`electric_gain_ex`, `electric_gain_ey`)

NF18 of South Australia AusLAMP 2013-2018 reads its xy apparent resistivity
3.64 dex (factor 4,365; 64 squared is 4,096) above NF18_2's at the same
place, with the phase within 8 deg, while its yx agrees to 0.005 dex:
the Ex input carried an extra gain of 64 that the
chain does not model, and Ey did not. `electric_gain` (both lines) cannot
declare it. `electric_gain_ex` / `electric_gain_ey` (default 1.0, no
filter) each add one forward coefficient stage to that channel's chain
only, after the reader's stages and after `electric_gain`'s, as
`electric_gain` does for both (`mt_workbench.instruments.read_run`): the
samples stay the stored words and calibration divides by the gain.

A synthetic EDL site of two 300 s stamps at 10 Hz is ingested without a
key, with `electric_gain_ex: 64`, and with `electric_gain: 10` plus
`electric_gain_ex: 64`.

Usage:
    python tests/ingest_electric_gain_channel_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - G1: with `electric_gain_ex: 64` any stored sample differs from the
    archive without the key; ex's chain is not the plain chain followed by
    one stage `uoa_electric_gain_ex` of gain 64, or ey's chain differs from
    the plain one; ex calibrated (mth5's `remove_instrument_response`) is
    not the plain ex calibrated / 64, or ey calibrated is not the plain ey
    calibrated, to 1e-12 with each series' mean taken out (the DC bin is
    |X(f1)| whatever the chain, upstream issue 68); or the run comment
    lacks "electric gain 64 on ex";
  - G2: with `electric_gain: 10` and `electric_gain_ex: 64`, ex's chain does
    not end [uoa_electric_gain 10, uoa_electric_gain_ex 64] or ex
    calibrated is not the plain ex / 640 and ey the plain ey / 10;
  - G3: `SiteConfig` accepts a gain of 0, a negative gain, a non-finite
    gain or a bool; `Survey.site` accepts a per-channel gain other than 1
    with `swap_e` (the exchange moves input stages stage for stage and the
    chains would differ in length); or a non-EDL site's own
    `electric_gain_ex` other than 1 passes `ingest._electric_gain`.

Mutation: with the per-channel stage added to both ex and ey (the
`electric_gain` behaviour), G1 must fail on ey.
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
import mt_workbench.instruments as instruments  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import SiteConfig, Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from ingest_swap_e_unit import read_channels  # noqa: E402

SCRATCH = scratch_dir("ingest_electric_gain_channel_unit")
SITE = "NFG"
RUN = "sr10_0001"
COMPS = ("ex", "ey", "hx", "hy", "hz")


def write_site(root: Path) -> None:
    """Write the EDL site under `root`/raw: two 300 s stamps at 10 Hz."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(18)
    for stamp in ("150617040000", "150617040500"):
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", rng.integers(-2_000_000, 2_000_000, 3000), fmt="%d")


def survey(root: Path, own: dict) -> Survey:
    """Build the one-site EDL survey with the site's own entry."""
    return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "flip_reversed_dipoles": True},
                   "sites": {SITE: own}}, root)


def close(a: np.ndarray, b: np.ndarray) -> bool:
    """Equal to 1e-12 with the means taken out."""
    return bool(np.allclose(a - a.mean(), b - b.mean(), rtol=1e-12, atol=1e-12 * np.max(np.abs(b))))


def gain_problems(got: dict, plain: dict, gx: float, gy: float, tail_x: list) -> list[str]:
    """Return what is wrong with a keyed archive against the plain one (ex / gx, ey / gy, chains)."""
    out = []
    for comp in COMPS:
        if not np.array_equal(got[comp]["samples"], plain[comp]["samples"]):
            out.append(f"{comp} stored samples changed")
    if got["ex"]["chain"] != plain["ex"]["chain"] + tail_x:
        out.append(f"ex chain {got['ex']['chain']}")
    want_y = plain["ey"]["chain"] + ([("uoa_electric_gain", gy)] if gy != 1.0 else [])
    if got["ey"]["chain"] != want_y:
        out.append(f"ey chain {got['ey']['chain']}")
    if not close(got["ex"]["calibrated"], plain["ex"]["calibrated"] / gx):
        out.append(f"ex calibrated is not the plain ex / {gx:g}")
    if not close(got["ey"]["calibrated"], plain["ey"]["calibrated"] / gy):
        out.append(f"ey calibrated is not the plain ey / {gy:g}")
    return out


def test_gain() -> None:
    """G1, G2: ex scaled, ey untouched; composition with electric_gain."""
    root = SCRATCH / "site"
    write_site(root)
    work = root / "work"
    plain = read_channels(ingest_site(survey(root, {}), SITE, out_path=work / "plain.h5", overwrite=True),
                          SITE, RUN, COMPS)
    g1 = read_channels(ingest_site(survey(root, {"electric_gain_ex": 64}), SITE, out_path=work / "g1.h5",
                                   overwrite=True), SITE, RUN, COMPS)
    problems = gain_problems(g1, plain, 64.0, 1.0, [("uoa_electric_gain_ex", 64.0)])
    if "electric gain 64 on ex" not in g1["comment"]:
        problems.append(f"run comment lacks the per-channel gain: {g1['comment'][-300:]}")
    assert not problems, problems
    print(f"  G1 electric_gain_ex 64: samples unchanged; ex chain {g1['ex']['chain']}; ey chain as plain; "
          f"ex calibrated == plain / 64, ey == plain (1e-12)")

    real = instruments.add_channel_electric_gains

    def both(run, site):
        """The mutation: ex's gain put on both lines."""
        g = float(getattr(site, "electric_gain_ex", 1.0) or 1.0)
        site2 = type(site)(**{**site.__dict__, "electric_gain_ey": g})
        return real(run, site2)

    instruments.add_channel_electric_gains = both
    try:
        mutant = read_channels(ingest_site(survey(root, {"electric_gain_ex": 64}), SITE, out_path=work / "m.h5",
                                           overwrite=True), SITE, RUN, COMPS)
    finally:
        instruments.add_channel_electric_gains = real
    caught = gain_problems(mutant, plain, 64.0, 1.0, [("uoa_electric_gain_ex", 64.0)])
    assert any(p.startswith("ey") for p in caught), caught
    print(f"  G1 mutation (both lines scaled): {[p for p in caught if p.startswith('ey')][0]!r}")

    g2 = read_channels(ingest_site(survey(root, {"electric_gain": 10, "electric_gain_ex": 64}), SITE,
                                   out_path=work / "g2.h5", overwrite=True), SITE, RUN, COMPS)
    problems = gain_problems(g2, plain, 640.0, 10.0, [("uoa_electric_gain", 10.0), ("uoa_electric_gain_ex", 64.0)])
    assert not problems, problems
    print(f"  G2 electric_gain 10 + electric_gain_ex 64: ex chain ends {g2['ex']['chain'][-2:]}; ex == plain / 640, "
          f"ey == plain / 10")


def test_refusals() -> None:
    """G3: bad values, swap_e with a per-channel gain, a non-EDL site's own key."""
    for key in ("electric_gain_ex", "electric_gain_ey"):
        for bad in (0, -64, float("inf"), float("nan"), True, "64x"):
            try:
                SiteConfig(name="X", **{key: bad})
            except ValueError as exc:
                assert key in str(exc), exc
            else:
                raise AssertionError(f"{key} {bad!r} accepted")
    root = SCRATCH / "site"
    try:
        survey(root, {"swap_e": True, "electric_gain_ey": 2.0}).site(SITE)
    except ValueError as exc:
        assert "electric_gain_ey" in str(exc) and "swap_e" in str(exc), exc
    else:
        raise AssertionError("swap_e with electric_gain_ey accepted")
    sv = Survey({"name": "t", "instrument": "lemi424", "data_root": str(root / "raw"), "workspace": str(root / "w"),
                 "sites": {"L1": {"electric_gain_ex": 64}}}, root)
    try:
        ingest._electric_gain(sv, sv.site("L1"), "lemi424", root)
    except ValueError as exc:
        assert "electric_gain_ex" in str(exc), exc
    else:
        raise AssertionError("a LEMI-424 site's own electric_gain_ex accepted")
    print("  G3 refused: 0, negative, inf, nan, bool, text; swap_e with a per-channel gain; a LEMI-424 site's own "
          "electric_gain_ex")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    for test in (test_gain, test_refusals):
        test()
        print(f"  ok  {test.__name__}")
    print("\nPASS  ingest_electric_gain_channel_unit (2 tests)")
