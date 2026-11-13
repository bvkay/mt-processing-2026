# -*- coding: utf-8 -*-
"""
Unit test for the per-coil sign flip of mt_workbench.ingest (`flip_h`)

A LEMI-423 site is written as one synthetic B423 file of 4 s at 1000 Hz
whose Bx and By columns are distinct series, and ingested with a
synthetic coil table and `h_scale: -1000` with no key, with `flip_h: []`
and with `flip_h: [hy]`. For the order with `swap_h`, a known field (Hx
and Hy in counts, two distinct series) is written as a coil pair turned
through 90 deg either way: Bx = -Hy and By = +Hx (Nador P6S3, declared
`swap_h: true` and `flip_h: [hy]`), and Bx = +Hy and By = -Hx (`swap_h:
true` and `flip_h: [hx]`). The two sites of tests/ingest_h_from_unit.py
(A electrics only with `h_from: B`) show the donor's flip travelling, B
declaring `flip_h: [hy]` and then `swap_h: true` as well. Where the
Kalkaroo Phoenix test folder is present, the burst site G5H of
tests/ingest_phoenix_unit.py is ingested with no key, with `flip_h: [hy]`
and with `swap_h: true` and `flip_h: [hy]` on G5. The archives are read
back with h5py and mth5 and compared with the files read here with numpy.

Usage:
    python tests/ingest_flip_h_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - F1: with `flip_h: [hy]`, the archive's hy is not minus the file's By
    column sample for sample, its hx is not the Bx column, ex or ey differ
    from the archive without the key, hy's filter chain differs from the
    unflipped hy's, or hy calibrated through it (mth5's
    `remove_instrument_response`), less its mean, is not minus the
    unflipped hy calibrated less its mean, to 1e-12 (the means are
    compared out because that calibration puts |X(f1)| in the DC bin
    whatever the sign, docs/upstream_issues.md 68); the run comment lacks
    "flip_h: hy samples negated at ingest", hy's channel comment lacks
    "flip_h: the samples negated", or hx's has it; or the `flip_h: []`
    archive differs from the archive without the key in any dataset or in
    the run comment;
  - F2: either turned pair, ingested with `swap_h: true` and the `flip_h`
    that names the channel reading minus after the exchange, does not
    give back hx = Hx and hy = Hy sample for sample, or its run comment
    does not hold the swap_h piece before a flip_h piece that says "after
    swap_h";
  - F3: a run comment of the flipped or the turned archives holds a
    ";"-piece whose key (before its first ":") has a dot, or `write_xml`
    (mt_metadata's EMTF XML writer, docs/upstream_issues.md 48) raises on
    a TF whose run carries that comment (the key check stands on its own:
    `write_xml` replaces the dots of keys, upstream 82);
  - F4: `Survey.site`, or `ingest_site` (which must then write no file),
    accepts `flip_h` naming hx or hy on a site with `h_from`, a value that
    is not a list (`flip_h: hy`), a channel other than hx, hy and hz, a
    channel named twice, or a channel the site's `channels:` does not
    keep; or [HY, hx] is not stored as [hx, hy] and [] as None;
  - F5: A's borrowed hx or hy differs from B's own archive at the same
    instants with B declaring `flip_h: [hy]`, alone or with `swap_h:
    true`; A's borrowed hy is not minus that of B's archive ingested
    without `flip_h` (and its hx not equal); or the borrowed hy's comment
    and the station's provenance do not record B's flip_h;
  - F6 (Phoenix bursts, when the Kalkaroo Phoenix test folder is
    present; read only, the cut copied to scratch): G5H with `flip_h: [hy]`
    on G5 does not hold minus the plain burst hy and the plain hx, ex and
    ey in every run, or with `swap_h: true` as well its hx is not the plain
    hy and its hy not minus the plain hx; or a flipped run's comment lacks
    the flip_h piece or its hy channel comment the channel line.

Mutations: F1 with `_flip_h` a no-op; F2 with the flip applied before the
exchange; F3 with a piece whose key has a dot ("flip_h hy x -1.0: ..."),
written with `products.dot_free_comment_keys` replaced by the identity;
F5 with the flip left out of the borrowed read. Each must trip its check,
which shows the check can fail.
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
from _scratch import scratch_dir  # noqa: E402
import ingest_h_from_unit as hf  # noqa: E402
from ingest_swap_h_unit import all_datasets, lemi_survey, read_archive, same  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRATCH = scratch_dir("ingest_flip_h_unit")
EPOCH = 1624510579
RUN = "sr1000_0001"
COMPS = ("hx", "hy", "ex", "ey")
FLIP_RUN = "flip_h: hy samples negated at ingest"
FLIP_CHANNEL = "flip_h: the samples negated"
SWAP_RUN = "swap_h: hx and hy exchanged"


def write_site(root: Path, wiring=None) -> tuple[np.ndarray, np.ndarray]:
    """Write site S01's B423 file under `root`/raw and return its first Bx and By columns.

    With `wiring`, a function of those two columns returning {"Bx": ...,
    "By": ...}, the file's Bx and By are then replaced by what it returns,
    so the returned columns are the field and the file what the coils
    recorded of it.
    """
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    shutil.rmtree(root, ignore_errors=True)
    path = _write_b423(root / "raw" / "S01" / f"{EPOCH}.B423", epoch=EPOCH, n=4000,
                       levels={"Bx": (4.3e7, 2.0e6), "By": (-3.1e7, 1.0e6), "Ey": (-2.0e7, 2.0e6)}, seed=11)
    data = path.read_bytes()
    records = np.frombuffer(data[1024:], dtype=Read_Lemi_Data.binary_format).copy()
    hx, hy = records["Bx"].astype("int64"), records["By"].astype("int64")
    assert not np.array_equal(hx, hy) and np.all(hx != 0) and np.all(hy != 0)
    if wiring is not None:
        for field, values in wiring(hx, hy).items():
            records[field] = values
        path.write_bytes(data[:1024] + records.tobytes())
    return hx, hy


def flip_problems(flipped: dict, plain: dict, bx: np.ndarray, by: np.ndarray) -> list[str]:
    """Return what is wrong with the `flip_h: [hy]` archive against the file and the plain archive."""
    problems = []
    if not np.array_equal(flipped["hy"]["samples"], -by):
        problems.append("hy is not minus the file's By column")
    if not np.array_equal(flipped["hx"]["samples"], bx):
        problems.append("hx is not the file's Bx column")
    for comp in ("ex", "ey"):
        if not np.array_equal(flipped[comp]["samples"], plain[comp]["samples"]):
            problems.append(f"{comp} differs from the archive without the key")
    if flipped["hy"]["chain"] != plain["hy"]["chain"]:
        problems.append(f"hy chain {flipped['hy']['chain']} against {plain['hy']['chain']}")
    # mt_timeseries sets the DC bin to |X(f1)| whatever the sign (docs/upstream_issues.md 68), so each
    # calibrated series is compared less its mean
    mine, theirs = flipped["hy"]["calibrated"], plain["hy"]["calibrated"]
    if not np.allclose(mine - mine.mean(), -(theirs - theirs.mean()), rtol=1e-12, atol=0):
        problems.append("calibrated hy less its mean is not minus the unflipped calibrated hy less its mean")
    if FLIP_RUN not in flipped["comment"]:
        problems.append(f"run comment lacks {FLIP_RUN!r}")
    if FLIP_CHANNEL not in flipped["hy"]["comment"] or "flip_h" in flipped["hx"]["comment"]:
        problems.append(f"channel comments hx {flipped['hx']['comment']!r}, hy {flipped['hy']['comment']!r}")
    return problems


def test_flip_one_coil() -> Path:
    """F1: hy negated sample for sample, hx and the electrics untouched, the record; [] changes nothing."""
    root = SCRATCH / "flip"
    bx, by = write_site(root)
    work = root / "work"
    paths = {tag: ingest_site(lemi_survey(root, own), "S01", out_path=work / f"{tag}.h5", overwrite=True)
             for tag, own in (("plain", {}), ("empty", {"flip_h": []}), ("flip", {"flip_h": ["hy"]}))}
    got = {tag: read_archive(path, "S01", RUN, COMPS) for tag, path in paths.items()}
    problems = flip_problems(got["flip"], got["plain"], bx, by)
    assert not problems, problems
    a, b = all_datasets(paths["plain"]), all_datasets(paths["empty"])
    differ = sorted(set(a) ^ set(b)) + [name for name in a if name in b and not same(a[name], b[name])]
    assert not differ and got["empty"]["comment"] == got["plain"]["comment"], (differ, got["empty"]["comment"])
    print(f"  F1 flip_h [hy]: hy == -By, hx == Bx ({by.size} samples), ex ey unchanged, hy chain "
          f"{[n for n, _g in got['flip']['hy']['chain']]} unchanged, calibrated hy == -unflipped to 1e-12 "
          f"(means out); "
          f"run comment {FLIP_RUN!r}...; flip_h [] == no key in all {len(a)} datasets")

    real = ingest._flip_h
    ingest._flip_h = lambda run, site: None
    try:
        mutant = ingest_site(lemi_survey(root, {"flip_h": ["hy"]}), "S01", out_path=work / "mutant.h5",
                             overwrite=True)
    finally:
        ingest._flip_h = real
    caught = flip_problems(read_archive(mutant, "S01", RUN, COMPS), got["plain"], bx, by)
    assert "hy is not minus the file's By column" in caught, caught
    print(f"  F1 mutation (_flip_h a no-op): {len(caught)} problems, e.g. {caught[0]!r}")
    return paths["flip"]


def rotation_problems(got: dict, hx: np.ndarray, hy: np.ndarray) -> list[str]:
    """Return how the archive's hx and hy differ from the field; empty when they are the field."""
    return [f"{comp} is not {name}" for comp, name, want in (("hx", "Hx", hx), ("hy", "Hy", hy))
            if not np.array_equal(got[comp]["samples"], want)]


def test_rotation_composes() -> list[Path]:
    """F2: a coil pair turned through 90 deg comes back as the field with swap_h then flip_h."""
    cases = (("P6S3: recorded hx = -Hy, hy = +Hx", lambda hx, hy: {"Bx": -hy, "By": hx}, ["hy"]),
             ("recorded hx = +Hy, hy = -Hx", lambda hx, hy: {"Bx": hy, "By": -hx}, ["hx"]))
    paths = []
    for k, (label, wiring, flip) in enumerate(cases):
        root = SCRATCH / f"rotation{k}"
        hx, hy = write_site(root, wiring)
        own = {"swap_h": True, "flip_h": flip}
        path = ingest_site(lemi_survey(root, own), "S01", out_path=root / "work" / "turned.h5", overwrite=True)
        got = read_archive(path, "S01", RUN, ("hx", "hy"))
        problems = rotation_problems(got, hx, hy)
        assert not problems, (label, problems)
        comment = got["comment"]
        swap_at = comment.find(SWAP_RUN)
        flip_at = comment.find(f"flip_h: {flip[0]} samples negated at ingest, after swap_h")
        assert 0 <= swap_at < flip_at, (label, comment)
        print(f"  F2 {label}: swap_h true + flip_h {flip} -> hx == Hx, hy == Hy ({hx.size} samples); the run "
              f"comment's swap_h piece then {comment[flip_at:flip_at + 60]!r}...")
        paths.append(path)
        if k == 0:
            real_swap, real_flip = ingest._swap_h, ingest._flip_h
            ingest._swap_h = lambda run, site: (real_flip(run, site), real_swap(run, site))[1]
            ingest._flip_h = lambda run, site: None
            try:
                mutant = ingest_site(lemi_survey(root, own), "S01", out_path=root / "work" / "mutant.h5",
                                     overwrite=True)
            finally:
                ingest._swap_h, ingest._flip_h = real_swap, real_flip
            caught = rotation_problems(read_archive(mutant, "S01", RUN, ("hx", "hy")), hx, hy)
            assert caught == ["hx is not Hx", "hy is not Hy"], caught
            print(f"  F2 mutation (flip before the exchange): {caught}")
    return paths


def make_tf(comment: str):
    """Return a TF with one run whose comment is `comment`, built as unknown_declination_unit builds one."""
    from unknown_declination_unit import make_tf as declination_tf

    tf = declination_tf(False)
    tf.station_metadata.runs[0].comments.value = comment
    return tf


def test_xml_accepts(paths: list[Path]) -> None:
    """F3: the run comments are dot-free key pieces and the EMTF XML writer takes them."""
    from mt_workbench.products import write_xml

    out = SCRATCH / "xml"
    out.mkdir(parents=True, exist_ok=True)
    comments = [read_archive(path, "S01", RUN, ())["comment"] for path in paths]
    for k, comment in enumerate(comments):
        assert "flip_h:" in comment, comment
        dotted = [piece for piece in comment.split(";") if ":" in piece and "." in piece.split(":", 1)[0]]
        assert not dotted, dotted
        written = write_xml(make_tf(comment), out / f"run_comment_{k}.xml")
        assert written.stat().st_size > 0
    print(f"  F3 {len(comments)} run comments ({sum(c.count(';') + 1 for c in comments)} pieces) written to EMTF "
          f"XML; no key has a dot")
    import mt_workbench.products as products

    mutant = comments[0] + "; flip_h hy x -1.0: negated"
    kept = products.dot_free_comment_keys
    products.dot_free_comment_keys = lambda text: text  # the writer as it is, without mt-workbench's key repair
    try:
        write_xml(make_tf(mutant), out / "mutant.xml")
    except AttributeError as exc:
        print(f"  F3 mutation (a dotted key appended): the writer raises {str(exc).strip()!r}")
    else:
        raise AssertionError("the EMTF XML writer took a dotted key: the check cannot fail")
    finally:
        products.dot_free_comment_keys = kept


def test_refusals() -> None:
    """F4: the declarations Survey.site and ingest_site refuse, and the stored forms."""
    root = SCRATCH / "refusals"
    hf.write_sites(root)
    out = root / "work" / "refused.h5"
    cases = {
        "A h_from B with flip_h [hy]": (hf.two_sites(root, a={"flip_h": ["hy"]}), "A", "h_from"),
        "A h_from B with flip_h [hx, hy]": (hf.two_sites(root, a={"flip_h": ["hx", "hy"]}), "A", "h_from"),
        "A h_from B with flip_h [hz], channels [ex, ey]": (hf.two_sites(root, a={"flip_h": ["hz"]}), "A",
                                                           "does not keep"),
        "flip_h: hy (not a list)": (hf.two_sites(root, b={"flip_h": "hy"}), "B", "not a list"),
        "flip_h [ex]": (hf.two_sites(root, b={"flip_h": ["ex"]}), "B", "only the coil channels"),
        "flip_h [hy, HY]": (hf.two_sites(root, b={"flip_h": ["hy", "HY"]}), "B", "more than once"),
        "flip_h [hz], channels [ex, ey, hx, hy]": (hf.two_sites(root, b={"flip_h": ["hz"]}), "B", "does not keep"),
    }
    said = {}
    for case, (survey, site, words) in cases.items():
        try:
            survey.site(site)
        except ValueError as exc:
            assert "flip_h" in str(exc) and words in str(exc), (case, exc)
        else:
            raise AssertionError(f"{case}: Survey.site accepted it")
        out.unlink(missing_ok=True)
        try:
            ingest_site(survey, site, out_path=out, overwrite=True)
        except ValueError as exc:
            assert not out.exists(), f"{case}: a refused ingest wrote a file"
            said[case] = str(exc)
            continue
        raise AssertionError(f"{case}: ingested")
    stored = {repr(given): hf.two_sites(root, b={"flip_h": given}).site("B").flip_h
              for given in (["HY", "hx"], [], None)}
    assert stored == {"['HY', 'hx']": ["hx", "hy"], "[]": None, "None": None}, stored
    print(f"  F4 refused ({len(said)}): " + "; ".join(f"{k}: {v[:80]!r}" for k, v in list(said.items())[:2])
          + f"; ...; stored {stored}")


def against(a: dict, b: dict, comp: str, sign: int) -> list[str]:
    """Return where A's `comp` is not `sign` times B's at the same instants; empty when it is."""
    times = np.concatenate([row[comp]["time"] for row in b["runs"].values()])
    samples = np.concatenate([row[comp]["samples"] for row in b["runs"].values()])
    order = np.argsort(times)
    times, samples = times[order], samples[order]
    problems = []
    for run_id, row in a["runs"].items():
        at = np.minimum(np.searchsorted(times, row[comp]["time"]), times.size - 1)
        if not np.array_equal(times[at], row[comp]["time"]):
            problems.append(f"{run_id} {comp}: instants not in B's archive")
        elif not np.array_equal(sign * samples[at].astype("int64"), row[comp]["samples"].astype("int64")):
            problems.append(f"{run_id} {comp}: not {sign:+d} x B's unflipped {comp}")
    return problems


def test_donor_flip_travels() -> None:
    """F5: an h_from site's borrowed coils carry the donor's flip_h, alone and after the donor's swap_h."""
    for case, b_entry in (("flip", {"flip_h": ["hy"]}), ("swap_flip", {"swap_h": True, "flip_h": ["hy"]})):
        root = SCRATCH / f"donor_{case}"
        hf.write_sites(root)
        survey = hf.two_sites(root, b=b_entry)
        work = root / "work"
        b_path = ingest_site(survey, "B", out_path=work / "B.h5", overwrite=True)
        unflipped = {k: v for k, v in b_entry.items() if k != "flip_h"}
        b_plain = ingest_site(hf.two_sites(root, b=unflipped), "B", out_path=work / "B_unflipped.h5",
                              overwrite=True)
        a_path = ingest_site(survey, "A", out_path=work / "A.h5", overwrite=True)
        a, b, bp = hf.read_runs(a_path, "A"), hf.read_runs(b_path, "B"), hf.read_runs(b_plain, "B", ("hx", "hy"))
        problems = hf.borrowed_problems(a, b)
        assert not problems, (case, problems)
        problems = against(a, bp, "hy", -1) + against(a, bp, "hx", +1)
        assert not problems, (case, problems)
        for row in a["runs"].values():
            assert FLIP_CHANNEL in row["hy"]["comment"] and "flip_h" not in row["hx"]["comment"], \
                (case, row["hx"]["comment"], row["hy"]["comment"])
        assert "flip_h hy and clock_offset_s" in a["provenance"], a["provenance"]
        n = sum(row["hy"]["samples"].size for row in a["runs"].values())
        print(f"  F5 {case}: A's borrowed hx, hy == B's archive ({n} samples per channel); hy == -B's "
              f"unflipped hy, hx == its hx; hy comment and station provenance record flip_h hy")
        if case == "flip":
            real = ingest._flip_h
            ingest._flip_h = lambda run, site: None
            try:
                mutant = ingest_site(survey, "A", out_path=work / "mutant.h5", overwrite=True)
            finally:
                ingest._flip_h = real
            caught = hf.borrowed_problems(hf.read_runs(mutant, "A"), b)
            assert caught and all(" hy" in c for c in caught), caught
            print(f"  F5 mutation (the donor's flip left out of the borrowed read): {len(caught)} problems, "
                  f"e.g. {caught[0]!r}")


def test_bursts() -> None:
    """F6: a Phoenix burst site carries the recorded site's flip_h, after its swap_h."""
    import ingest_phoenix_unit as px

    if not px.SOURCE.exists():
        print(f"  F6 SKIPPED: {px.SOURCE} not found")
        return
    px.make_cut("G5")
    got = {}
    for tag, entry in (("plain", {}), ("flip", {"flip_h": ["hy"]}), ("swap_flip", {"swap_h": True, "flip_h": ["hy"]})):
        survey = px.survey_for("G5", entry, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
        path = ingest_site(survey, "G5H", out_path=px.WORKSPACE / "mth5" / f"G5H_{tag}.h5", overwrite=True)
        got[tag] = px.read_bursts_archive(path, "G5H")["runs"]
    plain = got["plain"]
    counts = {tag: len(runs) for tag, runs in got.items()}
    assert plain and sorted(got["flip"]) == sorted(got["swap_flip"]) == sorted(plain), counts
    want = {"flip": {"hx": ("hx", 1), "hy": ("hy", -1), "ex": ("ex", 1), "ey": ("ey", 1)},
            "swap_flip": {"hx": ("hy", 1), "hy": ("hx", -1), "ex": ("ex", 1), "ey": ("ey", 1)}}
    for tag, rows in want.items():
        for run_id, run in got[tag].items():
            for comp, (source, sign) in rows.items():
                base = plain[run_id]["data"][source]
                assert np.any(base != 0), (run_id, source)
                assert np.array_equal(run["data"][comp], sign * base), (tag, run_id, comp)
            assert FLIP_RUN in run["run_comment"], (tag, run["run_comment"])
            assert FLIP_CHANNEL in run["channel_comments"]["hy"], (tag, run["channel_comments"]["hy"])
            assert FLIP_CHANNEL not in run["channel_comments"]["hx"], (tag, run["channel_comments"]["hx"])
    print(f"  F6 G5H {len(plain)} bursts: flip_h [hy] -> hy == -plain hy, hx ex ey plain; swap_h + flip_h [hy] -> "
          f"hx == plain hy, hy == -plain hx; run and hy channel comments record it")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("**This test fails if**", 1)[1].split("\n\nMutations")[0])
    print()
    flipped = test_flip_one_coil()
    print("  ok  test_flip_one_coil")
    turned = test_rotation_composes()
    print("  ok  test_rotation_composes")
    test_xml_accepts([flipped, *turned])
    print("  ok  test_xml_accepts")
    for test in (test_refusals, test_donor_flip_travels, test_bursts):
        test()
        print(f"  ok  {test.__name__}")
    print("\nPASS  ingest_flip_h_unit (6 tests)")
