# -*- coding: utf-8 -*-
"""
Unit test for the hx/hy exchange of crust.ingest (`swap_h`)

A LEMI-423 site is written as one synthetic B423 file of 4 s at 1000 Hz
whose Bx and By columns are distinct series (+4.3e7 and -3.1e7 counts
with Gaussian noise of 2e6 and 1e6, different seeds), with the header's
two magnetic coefficients Kmx and Kmy different, and ingested with a
synthetic coil table and `h_scale: -1000` three times: with no `swap_h`
key, with `swap_h: false` and with `swap_h: true`. An EDL site of two
synthetic 300 s stamps at 10 Hz, every channel file a distinct random
series, is ingested with and without the key. The archives are read back
with h5py and mth5 and compared with the files read here with numpy.

Usage:
    python tests/ingest_swap_h_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - with `swap_h: true`, the LEMI-423 archive's hx is not the file's By
    column sample for sample, its hy is not the file's Bx column, or ex
    and ey differ from the archive without the key;
  - the swapped hx's chain is not [coil table, `lemi423_linear_hy` of
    gain 1/Kmy, `lemi423_b_scale` -1000], the swapped hy's is not the same
    with `lemi423_linear_hx` of gain 1/Kmx, or either calibrated through
    its own chain (mth5's `remove_instrument_response`) differs by more
    than 1e-12 from the unswapped channel of the same input calibrated
    through its own;
  - the swapped archive's run comment does not record "swap_h: hx and hy
    exchanged", hx's metadata comment does not name the hy input, hy's
    does not name the hx input, or hx and hy do not keep their own
    azimuths (0, 90) and channel numbers (1, 2);
  - without the key, the archive's hx and hy are not the file's Bx and By
    columns with the chains of their own inputs and channel numbers 1 and
    2, a comment records a swap, or the `swap_h: false` archive differs
    from it in any dataset, channel's chain, number, azimuth or comment, or
    in the run comment;
  - with `swap_h: true`, the EDL archive's hx is not the BY file's values
    with the reader's hy chain, its hy is not the BX file's with the hx
    chain, or hz, ex and ey are not their own files';
  - `swap_h` on a site whose run holds hx and no hy ingests instead of
    raising ValueError;
  - `variant_path` of a site with declared filters changes with the key,
    or the variant built from the swapped raw archive does not keep the
    swapped hx's chain and comment.

The mutation: with the samples exchanged and the filter chains left with
the channel names, the chain and calibration checks must fail, which shows
they can.
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

import crust.ingest as ingest  # noqa: E402
from crust.ingest import build_variant, filters_hash, ingest_site, variant_path  # noqa: E402
from crust.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mtio_fork_unit import _write_b423, _write_rsp  # noqa: E402

SCRATCH = scratch_dir("ingest_swap_h_unit")
EPOCH = 1624510579
KMX, KMY = 2.909985e-06, 2.909481e-06  # the header coefficients `_write_b423` writes
NOTE = "swap_h: hx and hy exchanged"
NOTCH = [{"notch": {"f0": 50.0, "harmonics": 3, "q": 30.0, "passes": 1}}]


def lemi_survey(root: Path, own: dict, filters=None) -> Survey:
    """Build the one-site LEMI-423 survey over `root`, with the site's own entry."""
    rsp = root / "l120.rsp"
    if not rsp.exists():
        _write_rsp(rsp)
    defaults = {"calibration_fn": str(rsp), "h_scale": -1000.0, "channels": ["ex", "ey", "hx", "hy"],
                "dipole_length_ex": 50.0, "dipole_length_ey": 50.0}
    entry = dict(own, **({"filters": filters} if filters else {}))
    return Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"), "defaults": defaults, "sites": {"S01": entry}}, root)


def read_archive(path: Path, site: str, run_id: str, comps: tuple) -> dict:
    """Read a run's comment and, per channel, its samples, chain, calibrated series and metadata."""
    from mth5.mth5 import MTH5

    out = {}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(site, survey="t").get_run(run_id)
        out["comment"] = str(run.metadata.comments.value or "")
        for comp in comps:
            ch = run.get_channel(comp)
            md = ch.metadata
            comment = getattr(md.comments, "value", md.comments)
            out[comp] = dict(
                samples=np.asarray(ch.hdf5_dataset[()]),
                chain=[(f.name, float(getattr(f, "gain", 1.0) or 1.0)) for f in ch.channel_response.filters_list],
                calibrated=None if comp in ("hz", "ex", "ey") else ch.to_channel_ts().remove_instrument_response().ts,
                number=int(md.channel_number), azimuth=float(md.measurement_azimuth), comment=str(comment or ""))
    finally:
        m.close_mth5()
    return out


def chain_problems(swapped: dict, plain: dict) -> list[str]:
    """Return what is wrong with the swapped archive's chains and calibrated series; empty when right."""
    problems = []
    for comp, source, k in (("hx", "hy", KMY), ("hy", "hx", KMX)):
        names = [name for name, _gain in swapped[comp]["chain"]]
        gains = dict(swapped[comp]["chain"])
        if len(names) != 3 or not names[0].startswith("lemi_120_") or names[1:] != [f"lemi423_linear_{source}",
                                                                                      "lemi423_b_scale"]:
            problems.append(f"{comp} chain {names}")
        elif abs(gains[f"lemi423_linear_{source}"] * k - 1.0) > 1e-9 or gains["lemi423_b_scale"] != -1000.0:
            problems.append(f"{comp} gains {gains}")
        if not np.allclose(swapped[comp]["calibrated"], plain[source]["calibrated"], rtol=1e-12, atol=0):
            ratio = swapped[comp]["calibrated"] / plain[source]["calibrated"]
            problems.append(f"{comp} calibrated / unswapped {source} calibrated {np.nanmin(ratio):.9f} .. "
                            f"{np.nanmax(ratio):.9f}")
    return problems


def all_datasets(path: Path) -> dict:
    """Return every dataset of an HDF5 file by name.

    The fields of a summary table that hold HDF5 object references, which
    point into their own file and so differ between two files, are left out.
    """
    found = {}

    def keep(name, obj):
        if not isinstance(obj, h5py.Dataset):
            return
        data = obj[()]
        names = getattr(getattr(data, "dtype", None), "names", None)
        if names:
            data = {field: data[field] for field in names if not field.endswith("reference")}
        found[name] = data

    with h5py.File(path, "r") as f:
        f.visititems(keep)
    return found


def same(a, b) -> bool:
    """Return whether two `all_datasets` values are equal."""
    if isinstance(a, dict):
        return sorted(a) == sorted(b) and all(np.array_equal(a[k], b[k]) for k in a)
    return np.array_equal(a, b)


def test_lemi423_swap() -> None:
    """Check the LEMI-423 exchange: samples, chains, calibration, the record, and no change without the key."""
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    root = SCRATCH / "lemi423"
    shutil.rmtree(root, ignore_errors=True)
    b423 = _write_b423(root / "raw" / "S01" / f"{EPOCH}.B423", epoch=EPOCH, n=4000,
                       levels={"Bx": (4.3e7, 2.0e6), "By": (-3.1e7, 1.0e6), "Ey": (-2.0e7, 2.0e6)}, seed=7)
    records = np.frombuffer(b423.read_bytes()[1024:], dtype=Read_Lemi_Data.binary_format)
    bx, by = records["Bx"].astype("int64"), records["By"].astype("int64")
    assert not np.array_equal(bx, by) and KMX != KMY
    work = root / "work"
    paths = {tag: ingest_site(lemi_survey(root, own), "S01", out_path=work / f"{tag}.h5", overwrite=True)
             for tag, own in (("plain", {}), ("false", {"swap_h": False}), ("swap", {"swap_h": True}))}
    comps = ("hx", "hy", "ex", "ey")
    got = {tag: read_archive(path, "S01", "sr1000_0001", comps) for tag, path in paths.items()}
    plain, swapped = got["plain"], got["swap"]

    # without the key: the recording's own columns, chains, numbers, and no record
    assert np.array_equal(plain["hx"]["samples"], bx) and np.array_equal(plain["hy"]["samples"], by)
    for comp, k, number in (("hx", KMX, 1), ("hy", KMY, 2)):
        gains = dict(plain[comp]["chain"])
        assert abs(gains[f"lemi423_linear_{comp}"] * k - 1.0) < 1e-9, (comp, plain[comp]["chain"])
        assert plain[comp]["number"] == number and plain[comp]["comment"] == "", (comp, plain[comp])
    assert "swap_h" not in plain["comment"], plain["comment"]
    a, b = all_datasets(paths["plain"]), all_datasets(paths["false"])
    assert sorted(a) == sorted(b), (sorted(set(a) ^ set(b)))
    differ = [name for name in a if not same(a[name], b[name])]
    assert not differ and got["false"]["comment"] == plain["comment"], (differ, got["false"]["comment"])
    for comp in comps:
        for key in ("chain", "number", "azimuth", "comment"):
            assert got["false"][comp][key] == plain[comp][key], (comp, key, got["false"][comp][key])

    # with the key: exchanged sample for sample, electrics untouched
    assert np.array_equal(swapped["hx"]["samples"], by), "swapped hx is not the file's By column"
    assert np.array_equal(swapped["hy"]["samples"], bx), "swapped hy is not the file's Bx column"
    for comp in ("ex", "ey"):
        assert np.array_equal(swapped[comp]["samples"], plain[comp]["samples"]), comp
        assert swapped[comp]["chain"] == plain[comp]["chain"], comp

    # each linear stage follows its data, and so the calibrated series
    problems = chain_problems(swapped, plain)
    assert not problems, problems

    # the record
    assert NOTE in swapped["comment"], swapped["comment"]
    assert "hy input" in swapped["hx"]["comment"] and "hx input" in swapped["hy"]["comment"], \
        (swapped["hx"]["comment"], swapped["hy"]["comment"])
    assert (swapped["hx"]["number"], swapped["hy"]["number"]) == (1, 2)
    assert (swapped["hx"]["azimuth"], swapped["hy"]["azimuth"]) == (0.0, 90.0)
    print(f"  swap_h true: hx == By column, hy == Bx column ({bx.size} samples each); hx chain "
          f"{[n for n, _g in swapped['hx']['chain']]}, hy chain {[n for n, _g in swapped['hy']['chain']]}; "
          f"calibrated hx == unswapped calibrated hy to 1e-12 and the other way round; "
          f"comment {NOTE!r}; no key and swap_h false: the same {len(a)} datasets")

    # the mutation: the filter chains left behind with the channel names
    kept = ingest._INPUT_ATTRS
    ingest._INPUT_ATTRS = ()
    try:
        mutant_path = ingest_site(lemi_survey(root, {"swap_h": True}), "S01", out_path=work / "mutant.h5",
                                  overwrite=True)
    finally:
        ingest._INPUT_ATTRS = kept
    mutant = chain_problems(read_archive(mutant_path, "S01", "sr1000_0001", ("hx", "hy")), plain)
    assert len(mutant) == 4, mutant
    print(f"  mutation (chains not moved): {len(mutant)} problems, e.g. {mutant[0]!r}; {mutant[1]!r}")


def test_edl_swap() -> None:
    """Check the exchange on an EDL site, whose reader names the coils hx and hy too."""
    root = SCRATCH / "edl"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "HGX"
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(5)
    words = {}
    for stamp in ("090320000000", "090320000500"):
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            values = rng.integers(-2_000_000, 2_000_000, 3000)
            np.savetxt(site / f"HGX_{stamp}.{suffix}", values, fmt="%d")
            words.setdefault(suffix, []).append(values)
    words = {k: np.concatenate(v) for k, v in words.items()}

    def survey(own):
        """Build the one-site EDL survey with the site's own entry."""
        return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                       "workspace": str(root / "work"),
                       "defaults": {"dipole_length_ex": 49.0, "dipole_length_ey": 51.0},
                       "sites": {"HGX": own}}, root)

    paths = {tag: ingest_site(survey(own), "HGX", out_path=root / "work" / f"{tag}.h5", overwrite=True)
             for tag, own in (("plain", {}), ("swap", {"swap_h": True}))}
    want = {"plain": {"hx": "BX", "hy": "BY", "hz": "BZ", "ex": "EX", "ey": "EY"},
            "swap": {"hx": "BY", "hy": "BX", "hz": "BZ", "ex": "EX", "ey": "EY"}}
    for tag, path in paths.items():
        with h5py.File(path, "r") as f:
            group = f["Experiment/Surveys/t/Stations/HGX/sr10_0001"]
            for comp, suffix in want[tag].items():
                assert np.array_equal(group[comp][()], words[suffix]), (tag, comp, suffix)
            comment = group.attrs.get("comments")
            comment = comment.decode() if isinstance(comment, bytes) else str(comment)
            assert (NOTE in comment) == (tag == "swap"), (tag, comment)
    chains = {tag: {comp: [n for n, _g in rows[comp]["chain"]] for comp in ("hx", "hy")}
              for tag, rows in ((tag, read_archive(path, "HGX", "sr10_0001", ("hx", "hy")))
                                for tag, path in paths.items())}
    assert chains["plain"]["hx"] != chains["plain"]["hy"], chains["plain"]
    assert (chains["swap"]["hx"], chains["swap"]["hy"]) == (chains["plain"]["hy"], chains["plain"]["hx"]), chains
    print(f"  EDL: swap_h true archives hx == the BY file with chain {chains['swap']['hx']}, hy == the BX "
          f"file with {chains['swap']['hy']}, hz ex ey their own ({words['BX'].size} samples); without the key "
          f"hx == BX, hy == BY")


def test_no_pair_refused() -> None:
    """Check that `swap_h` on a run with hx and no hy raises ValueError."""
    root = SCRATCH / "lemi423"
    survey = lemi_survey(root, {"swap_h": True, "channels": ["ex", "ey", "hx"]})
    try:
        ingest_site(survey, "S01", out_path=root / "work" / "no_pair.h5", overwrite=True)
    except ValueError as exc:
        assert "swap_h" in str(exc) and "hy" in str(exc), exc
        print(f"  hx without hy refused: {exc}")
        return
    raise AssertionError("swap_h on a run without hy ingested")


def test_variant_keeps_the_swap() -> None:
    """Check the variant path is the key's alone to leave unchanged, and the variant keeps the swap."""
    root = SCRATCH / "lemi423"
    plain, swapped = lemi_survey(root, {}, NOTCH), lemi_survey(root, {"swap_h": True}, NOTCH)
    want = root / "work" / "mth5" / f"S01_f{filters_hash(NOTCH)}.h5"
    assert variant_path(plain, "S01") == variant_path(swapped, "S01") == want, \
        (variant_path(plain, "S01"), variant_path(swapped, "S01"), want)
    ingest_site(swapped, "S01", overwrite=True)
    built = build_variant(swapped, "S01")
    assert built == want, built
    got = read_archive(built, "S01", "sr1000_0001", ("hx", "hy"))
    assert [n for n, _g in got["hx"]["chain"]][1] == "lemi423_linear_hy", got["hx"]["chain"]
    assert "hy input" in got["hx"]["comment"], got["hx"]["comment"]
    print(f"  variant path {built.name} with and without the key; the variant's hx chain "
          f"{[n for n, _g in got['hx']['chain']]}, comment {got['hx']['comment']!r}")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nThe mutation")[0])
    print()
    tests = [test_lemi423_swap, test_edl_swap, test_no_pair_refused, test_variant_keeps_the_swap]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  ingest_swap_h_unit ({len(tests)} tests)")
