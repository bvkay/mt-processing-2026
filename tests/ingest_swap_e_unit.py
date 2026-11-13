# -*- coding: utf-8 -*-
"""
Unit test for the exchange of the two electric channels at ingest (`swap_e`)

TAS125's field sheet (Tasmania AusLAMP 2016) gives its Ex line at 270 deg
(W, 44.0 m) and its Ey line at 0 deg (N, 49.2 m): the logger's EX input
recorded the west line and its EY input the north line. Declared `swap_e:
true` with `azimuth_ex: 0.0`, `azimuth_ey: 270.0`, `dipole_length_ex: 49.2`
and `dipole_length_ey: 44.0` (the sheet's values moved to the channels they
now name), ingest exchanges the two inputs' samples, keeps each channel's
dipole stage (its declared length and sign) with the channel name and moves
every other stage of the chain (the logger input's own) with the samples;
the reversed-dipole rule then reads the channels as they are after the
exchange, so ey (270 deg) is the reversed one. An EDL site of two synthetic
300 s stamps at 10 Hz is ingested so with and without the key, and the
LEMI-423 sites of tests/ingest_h_from_unit.py (A electrics only with
`h_from: B`, whose header coefficients Ke1 and Ke2 differ) carry the key on
A.

Usage:
    python tests/ingest_swap_e_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - E1: with the key, the EDL archive's ex is not the EY file's words, its
    ey not the EX file's, or hx, hy, hz are not their own files'; ex's
    chain is not [uoa_dipole_ex_49.2m of gain -49.2, the terminal box] and
    ey's not [uoa_dipole_ey_44.0m of gain +44.0 (reversed), the terminal
    box]; or ex calibrated through its chain (mth5's
    `remove_instrument_response`) is not the archive without the key's ey
    (the same EY words through the reader's ey chain, -50.0 x 10)
    calibrated and scaled by -500 / -492, and ey not that archive's ex
    scaled by -500 / +440, to 1e-12 with each series' mean taken out (the
    DC bin is |X(f1)| whatever the chain's sign). (The calibrated series is not compared
    with words / gain: that calibration moves |X(f1)| into the DC bin,
    upstream issue 68, which leaves 0.5-0.7 % of the series off a plain
    division in the archive without the key too; the first run of this
    test, with that criterion, failed so on both channels.)
  - E2: the run comment lacks "swap_e: ex and ey exchanged", ex's channel
    comment does not name the ey input or ey's the ex input, or a channel
    keeps its own `dipole_length` metadata other than 49.2 (ex) and 44.0
    (ey); or `swap_e: false` differs from no key in any dataset or the run
    comment;
  - E3: the sheet's own layout (`azimuth_ex: 270.0`, `azimuth_ey: 0.0`,
    no key), which no flip can mend, ingests instead of raising ValueError
    before the archive is touched, on the EDL site or on a LEMI-423 site
    (the rule holds for every recorder: ex at 0 or 180, ey at 90 or 270);
  - E4: on the LEMI-423 site A with `h_from: B` (allowed with `swap_e`), A's
    ex is not the file's Ey column, its ey not the Ex column, ex's chain is
    not [lemi423_dipole_ex_49.2m, lemi423_linear_ey] or ey's not
    [lemi423_dipole_ey_44.0m, lemi423_linear_ex], or A's borrowed hx, hy
    differ from the archive without the key; `Survey.site` refuses
    `swap_e` with `h_from`, or accepts `swap_e` with channels lacking ey,
    or a value that is not a bool.

Mutation: E1 with the chains left whole with the channel names (the
samples alone exchanged) on the LEMI-423 site must trip E4's chain check,
and with the dipole stages moved with the samples on the EDL site must
trip E1's; each shows the check can fail.
"""

from __future__ import annotations

import shutil
import sys
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
import ingest_h_from_unit as hf  # noqa: E402
from ingest_swap_h_unit import all_datasets, same  # noqa: E402

SCRATCH = scratch_dir("ingest_swap_e_unit")
SITE = "TSE"
RUN = "sr10_0001"
NOTE = "swap_e: ex and ey exchanged"
TAS125 = {"swap_e": True, "azimuth_ex": 0.0, "azimuth_ey": 270.0, "dipole_length_ex": 49.2,
          "dipole_length_ey": 44.0}


def write_site(root: Path) -> dict[str, np.ndarray]:
    """Write the EDL site under `root`/raw: two 300 s stamps at 10 Hz, every file a distinct series."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(125)
    words = {}
    for stamp in ("090320000000", "090320000500"):
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            values = rng.integers(-2_000_000, 2_000_000, 3000)
            np.savetxt(site / f"{SITE}_{stamp}.{suffix}", values, fmt="%d")
            words.setdefault(suffix, []).append(values)
    return {k: np.concatenate(v) for k, v in words.items()}


def survey(root: Path, own: dict) -> Survey:
    """Build the one-site EDL survey with the site's own entry."""
    return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "flip_reversed_dipoles": True},
                   "sites": {SITE: own}}, root)


def read_channels(path: Path, station: str, run_id: str, comps) -> dict:
    """Return the run comment and, per channel, the samples, chain, calibrated series, comment and length."""
    from mth5.mth5 import MTH5

    out = {}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(station, survey="t").get_run(run_id)
        out["comment"] = str(run.metadata.comments.value or "")
        for comp in comps:
            ch = run.get_channel(comp)
            md = ch.metadata
            out[comp] = dict(samples=np.asarray(ch.hdf5_dataset[()]),
                             chain=[(f.name, float(getattr(f, "gain", 1.0) or 1.0))
                                    for f in ch.channel_response.filters_list],
                             calibrated=ch.to_channel_ts().remove_instrument_response().ts,
                             comment=str(getattr(md.comments, "value", md.comments) or ""),
                             length=float(getattr(md, "dipole_length", 0.0) or 0.0))
    finally:
        m.close_mth5()
    return out


def edl_problems(got: dict, words: dict, plain: dict) -> list[str]:
    """Return what is wrong with the swapped EDL archive against the files and the archive without the key."""
    problems = []
    for comp, suffix in (("ex", "EY"), ("ey", "EX"), ("hx", "BX"), ("hy", "BY"), ("hz", "BZ")):
        if not np.array_equal(got[comp]["samples"], words[suffix]):
            problems.append(f"{comp} is not the {suffix} words")
    want = {"ex": [("uoa_dipole_ex_49.2m", -49.2), ("uoa_efield_terminal_box_gain", 10.0)],
            "ey": [("uoa_dipole_ey_44.0m", 44.0), ("uoa_efield_terminal_box_gain", 10.0)]}
    for comp in ("ex", "ey"):
        if got[comp]["chain"] != want[comp]:
            problems.append(f"{comp} chain {got[comp]['chain']}")
    # the archive without the key holds the same words through the reader's own chains, -50 x 10 on both
    for comp, other, gain in (("ex", "ey", -49.2 * 10.0), ("ey", "ex", 44.0 * 10.0)):
        # less their means: the calibration's DC bin is |X(f1)| whatever the chain's sign (upstream issue 68)
        want = plain[other]["calibrated"] * (-500.0 / gain)
        mine = got[comp]["calibrated"]
        if not np.allclose(mine - mine.mean(), want - want.mean(), rtol=1e-12, atol=1e-12 * np.max(np.abs(want))):
            problems.append(f"{comp} calibrated is not the unswapped {other} calibrated x -500 / {gain:g}")
    return problems


def test_edl() -> None:
    """E1, E2, E3: the EDL exchange, its record, no change with false, and the unmendable layout refused."""
    root = SCRATCH / "edl"
    words = write_site(root)
    work = root / "work"
    paths = {tag: ingest_site(survey(root, own), SITE, out_path=work / f"{tag}.h5", overwrite=True)
             for tag, own in (("plain", {}), ("false", {"swap_e": False}), ("swap", TAS125))}
    comps = ("ex", "ey", "hx", "hy", "hz")
    got = {tag: read_channels(path, SITE, RUN, comps) for tag, path in paths.items()}
    problems = edl_problems(got["swap"], words, got["plain"])
    assert not problems, problems
    print(f"  E1 swap_e: ex == the EY words with chain {got['swap']['ex']['chain']}, ey == the EX words with "
          f"{got['swap']['ey']['chain']}; calibrated == the unswapped channel x the gain ratio to 1e-12; hx hy hz their own ({words['EX'].size} samples)")

    real = ingest._swap_e

    def whole_chains(run, site):
        """The mutation: the samples and every stage of the chain exchanged, the dipole stages too."""
        note = real(run, type(site)(**{**site.__dict__, "swap_e": False}))
        assert note is None
        ex, ey = run.dataset["ex"], run.dataset["ey"]
        ex.data, ey.data = ey.data.copy(), ex.data.copy()
        ex.attrs["filters"], ey.attrs["filters"] = ey.attrs.get("filters"), ex.attrs.get("filters")
        return "swap_e: mutated"

    ingest._swap_e = whole_chains
    try:
        mutant = ingest_site(survey(root, TAS125), SITE, out_path=work / "mutant.h5", overwrite=True)
    finally:
        ingest._swap_e = real
    caught = edl_problems(read_channels(mutant, SITE, RUN, comps), words, got["plain"])
    assert any("chain" in p for p in caught), caught
    print(f"  E1 mutation (the dipole stages moved with the samples): {caught[0]!r}")

    swap = got["swap"]
    assert NOTE in swap["comment"], swap["comment"]
    assert "ey input" in swap["ex"]["comment"] and "ex input" in swap["ey"]["comment"], \
        (swap["ex"]["comment"], swap["ey"]["comment"])
    assert (swap["ex"]["length"], swap["ey"]["length"]) == (49.2, 44.0), (swap["ex"]["length"], swap["ey"]["length"])
    a, b = all_datasets(paths["plain"]), all_datasets(paths["false"])
    differ = sorted(set(a) ^ set(b)) + [name for name in a if name in b and not same(a[name], b[name])]
    assert not differ and got["false"]["comment"] == got["plain"]["comment"], differ
    piece = next(p for p in swap["comment"].split("; ") if p.startswith("swap_e"))
    print(f"  E2 run comment {piece!r}; channel comments {swap['ex']['comment']!r}; dipole_length 49.2 / 44.0; "
          f"swap_e false == no key in all {len(a)} datasets")

    out = work / "sheet.h5"
    out.write_bytes(b"kept")
    try:
        ingest_site(survey(root, {"azimuth_ex": 270.0, "azimuth_ey": 0.0, "dipole_length_ex": 44.0,
                                  "dipole_length_ey": 49.2}), SITE, out_path=out, overwrite=True)
    except ValueError as exc:
        assert "azimuth" in str(exc), exc
        assert out.read_bytes() == b"kept", "the refused ingest touched the existing file"
        print(f"  E3 the sheet's own layout (Ex 270, Ey 0, no key) refused before the archive is touched: "
              f"{str(exc)[:100]}...")
    else:
        raise AssertionError("the sheet's layout Ex 270 / Ey 0 ingested")
    from ingest_swap_h_unit import lemi_survey
    from mtio_fork_unit import _write_b423

    lemi = SCRATCH / "lemi_sheet"
    shutil.rmtree(lemi, ignore_errors=True)
    _write_b423(lemi / "raw" / "S01" / "1624510579.B423", epoch=1624510579, n=2000, seed=3)
    kept = lemi / "work" / "kept.h5"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"kept")
    try:
        ingest_site(lemi_survey(lemi, {"azimuth_ex": 270.0, "azimuth_ey": 0.0}), "S01", out_path=kept, overwrite=True)
    except ValueError as exc:
        assert "azimuth" in str(exc) and kept.read_bytes() == b"kept", exc
        print(f"  E3 the same layout on a LEMI-423 site refused, the existing file untouched")
    else:
        raise AssertionError("the sheet's layout Ex 270 / Ey 0 ingested on a LEMI-423 site")


def test_lemi423_with_h_from() -> None:
    """E4: swap_e on a LEMI-423 site that borrows its H; the input stages move with the samples."""
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    root = SCRATCH / "lemi423"
    hf.write_sites(root)
    own = {"swap_e": True, "dipole_length_ex": 49.2, "dipole_length_ey": 44.0}
    work = root / "work"
    plain = ingest_site(hf.two_sites(root), "A", out_path=work / "plain.h5", overwrite=True)
    swapped = ingest_site(hf.two_sites(root, a=own), "A", out_path=work / "swap.h5", overwrite=True)
    records = np.frombuffer((root / "raw" / "A" / f"{hf.A_STARTS[0]}.B423").read_bytes()[1024:],
                            dtype=Read_Lemi_Data.binary_format)
    n = records.size
    run_id = "sr1000_0001"
    got = read_channels(swapped, "A", run_id, ("ex", "ey", "hx", "hy"))
    base = read_channels(plain, "A", run_id, ("ex", "ey", "hx", "hy"))

    def problems_of(g):
        out = []
        if not np.array_equal(g["ex"]["samples"][:n], records["Ey"]):
            out.append("ex is not the Ey column")
        if not np.array_equal(g["ey"]["samples"][:n], records["Ex"]):
            out.append("ey is not the Ex column")
        if [c for c, _g in g["ex"]["chain"]] != ["lemi423_dipole_ex_49.2m", "lemi423_linear_ey"]:
            out.append(f"ex chain {g['ex']['chain']}")
        if [c for c, _g in g["ey"]["chain"]] != ["lemi423_dipole_ey_44.0m", "lemi423_linear_ex"]:
            out.append(f"ey chain {g['ey']['chain']}")
        for comp in ("hx", "hy"):
            if not np.array_equal(g[comp]["samples"], base[comp]["samples"]):
                out.append(f"borrowed {comp} differs from the archive without the key")
        return out

    problems = problems_of(got)
    assert not problems, problems
    real = ingest._swap_e

    def samples_only(run, site):
        """The mutation: the samples exchanged, every stage left with the channel name."""
        if not site.swap_e:
            return None
        ex, ey = run.dataset["ex"], run.dataset["ey"]
        ex.data, ey.data = ey.data.copy(), ex.data.copy()
        return "swap_e: mutated"

    ingest._swap_e = samples_only
    try:
        mutant = ingest_site(hf.two_sites(root, a=own), "A", out_path=work / "mutant.h5", overwrite=True)
    finally:
        ingest._swap_e = real
    caught = problems_of(read_channels(mutant, "A", run_id, ("ex", "ey", "hx", "hy")))
    assert any("chain" in p for p in caught), caught
    print(f"  E4 LEMI-423 A (h_from B) swap_e: ex == the Ey column with {[c for c, _g in got['ex']['chain']]}, ey == "
          f"Ex with {[c for c, _g in got['ey']['chain']]}; borrowed hx hy unchanged; mutation (samples only): "
          f"{caught[0]!r}")
    for what, entry, expect in (("no ey", {"swap_e": True, "channels": ["ex", "hx", "hy"]}, "ey"),
                                ("not a bool", {"swap_e": "yes"}, "swap_e")):
        try:
            Survey({"name": "t", "instrument": "edl", "data_root": str(root), "sites": {"X": entry}}, root).site("X")
        except ValueError as exc:
            assert expect in str(exc), (what, exc)
            print(f"  E4 {what}: refused ({str(exc)[:80]}...)")
            continue
        raise AssertionError(f"swap_e {what}: accepted")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    tests = [test_edl, test_lemi423_with_h_from]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  ingest_swap_e_unit ({len(tests)} tests)")
