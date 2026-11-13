# -*- coding: utf-8 -*-
"""
Unit test for the borrowed magnetics of mt_workbench.ingest (`h_from`)

Two synthetic LEMI-423 sites at 1000 Hz are written as B423 files of 4 s.
Site A recorded electrics only (`channels: [ex, ey]`, `h_from: B`): four
files back to back from the epoch, then one 34 s and one 54 s after it, so
its ingest makes three runs (16 s, 4 s and 4 s). Site B has four channels,
another logger number, other Kmx and Kmy coefficients and another latitude
in its headers, and an `h_scale` that differs from A's. B's record starts
3 s before A's (five files back to back, which cover A's first run), then
one file from 52 s, which ends inside A's last run; nothing of B covers A's
second run. In the second case B declares `clock_offset_s: -1.0` and
`swap_h: true`. A is ingested with and without the key, B on its own, and
the archives are compared with h5py and mth5. A third site, B2, holds B's
last file alone and covers under a tenth of A's samples.

Usage:
    python tests/ingest_h_from_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - for either case, any sample of A's borrowed hx or hy differs from B's
    own archive's hx or hy at the same instant (B's clock offset applied),
    an instant of A's has no sample in B's archive, or the borrowed
    channels' filter chains (names and gains), azimuths, sensor ids and
    channel numbers are not those of B's archive;
  - A's ex and ey, or their time axes, differ from the archive A's ingest
    writes without the key over the same instants, a run's hx axis is not
    its ex axis, or A's station location is not its own;
  - the runs are not: A's first run whole, its second left out, its third
    cut to the part B covers (2000 samples, 1000 with B's offset);
  - the cut run's comment does not record the cut, the station's
    ``provenance.comments`` does not record the run left out and the
    neighbour, `archive_h_from` does not read back B (or reads a name from
    B's own archive), a borrowed channel's comment is not "h_from: hx of B,
    <distance> m away, coil <id>, logger <id>; aligned by GPS time; the
    neighbour's clock_offset_s <x> applied", the ingest log lacks one line
    per run with its span, or the filtered variant loses the record;
  - `ingest_site` writes a file, or `Survey.site` accepts the key, when A
    declares hx and hy, B declares channels without hy, B is itself
    `h_from`, B is at another sample rate, B is derived, or the key is in
    `defaults:` or names A itself; or the ingest accepts a neighbour that
    covers under half of A's samples.

The mutation: with the borrowed samples read one sample early, the
sample-for-sample check must fail on every run and channel, which shows it
can.
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
from mt_workbench.ingest import archive_h_from, build_variant, ingest_site  # noqa: E402
from mt_workbench.survey import Survey, distance_km  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mtio_fork_unit import _write_b423, _write_rsp  # noqa: E402

SCRATCH = scratch_dir("ingest_h_from_unit")
EPOCH = 1624510579
A_STARTS = (EPOCH, EPOCH + 4, EPOCH + 8, EPOCH + 12, EPOCH + 34, EPOCH + 54)
B_STARTS = (EPOCH - 3, EPOCH + 1, EPOCH + 5, EPOCH + 9, EPOCH + 13, EPOCH + 52)
POSITIONS = {"A": (-32.0, 138.0), "B": (-32.0, 138.02)}
NOTCH = [{"notch": {"f0": 50.0, "harmonics": 3, "q": 30.0, "passes": 1}}]
# B's header: another logger, other coefficients, another latitude (same widths as `_write_b423`'s)
B_HEADER = ((b"%LEMI423 #0036", b"%LEMI423 #0041"), (b"%Kmx = 2.909985e-06", b"%Kmx = 2.801234e-06"),
            (b"%Kmy = 2.909481e-06", b"%Kmy = 2.812345e-06"), (b"%Lat 3209.28947,N", b"%Lat 3211.28947,N"))


def write_sites(root: Path) -> None:
    """Write the B423 files of A, B and B2 (B's last file alone) under `root`/raw."""
    shutil.rmtree(root, ignore_errors=True)
    for k, start in enumerate(A_STARTS):
        _write_b423(root / "raw" / "A" / f"{start}.B423", epoch=start, n=4000, seed=100 + k,
                    levels={"Ex": (2.0e7, 2.0e6), "Ey": (-1.5e7, 1.0e6), "Bx": (-2.0e9, 0.0), "By": (-2.0e9, 0.0)})
    for k, start in enumerate(B_STARTS):
        for folder in (("B", "B2") if start == B_STARTS[-1] else ("B",)):
            path = _write_b423(root / "raw" / folder / f"{start}.B423", epoch=start, n=4000, seed=200 + k,
                               levels={"Ex": (1.0e7, 1.0e6), "Ey": (-1.0e7, 1.0e6), "Bx": (4.3e7, 2.0e6),
                                       "By": (-3.1e7, 1.0e6)})
            data = path.read_bytes()
            for old, new in B_HEADER:
                assert len(old) == len(new) and old in data[:1024], old
                data = data.replace(old, new, 1)
            path.write_bytes(data)


def two_sites(root: Path, a: dict | None = None, b: dict | None = None, extra: dict | None = None,
              defaults: dict | None = None, filters: list | None = None) -> Survey:
    """Build the survey of A (electrics only, `h_from: B` unless `a` says otherwise) and B."""
    rsp = root / "l120.rsp"
    if not rsp.exists():
        _write_rsp(rsp)
    base = {"calibration_fn": str(rsp), "h_scale": -1000.0, "channels": ["ex", "ey", "hx", "hy"],
            "dipole_length_ex": 50.0, "dipole_length_ey": 50.0, **(defaults or {})}
    site_a = {"channels": ["ex", "ey"], "h_from": "B", "h_scale": -500.0, "latitude": POSITIONS["A"][0],
              "longitude": POSITIONS["A"][1], **(a or {})}
    site_a = {k: v for k, v in site_a.items() if v is not None}
    if filters:
        site_a["filters"] = filters
    site_b = {"latitude": POSITIONS["B"][0], "longitude": POSITIONS["B"][1], **(b or {})}
    sites = {"A": site_a, "B": site_b, "B2": dict(site_b), **(extra or {})}
    return Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"), "defaults": base, "sites": sites}, root)


def read_runs(path: Path, site: str, comps=("ex", "ey", "hx", "hy")) -> dict:
    """Read every run of an archive: comment, and per channel its times, samples, chain and metadata."""
    from mth5.mth5 import MTH5
    from mt_workbench.timefreq import _real_runs

    out = {"runs": {}}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station(site, survey="t")
        md = station.metadata
        out["provenance"] = str(md.provenance.comments.value or "")
        out["latitude"] = float(md.location.latitude)
        for run_id, _start, _end in _real_runs(station):
            run = station.get_run(run_id)
            row = {"comment": str(run.metadata.comments.value or "")}
            for comp in comps:
                if comp not in run.groups_list:
                    continue
                ch = run.get_channel(comp)
                cmd = ch.metadata
                comment = getattr(cmd.comments, "value", cmd.comments)
                row[comp] = dict(
                    time=ch.to_channel_ts().data_array.coords["time"].values.astype("datetime64[ns]"),
                    samples=np.asarray(ch.hdf5_dataset[()]),
                    chain=[(f.name, float(getattr(f, "gain", 1.0) or 1.0)) for f in ch.channel_response.filters_list],
                    azimuth=float(cmd.measurement_azimuth), sensor=str(getattr(getattr(cmd, "sensor", None), "id", "")),
                    number=int(cmd.channel_number), comment=str(comment or ""))
            out["runs"][run_id] = row
    finally:
        m.close_mth5()
    return out


def borrowed_problems(a: dict, b: dict) -> list[str]:
    """Return how A's hx and hy differ from B's archive at the same instants; empty when they agree."""
    problems = []
    for comp in ("hx", "hy"):
        times = np.concatenate([row[comp]["time"] for row in b["runs"].values()])
        samples = np.concatenate([row[comp]["samples"] for row in b["runs"].values()])
        order = np.argsort(times)
        times, samples = times[order], samples[order]
        first_b = next(iter(b["runs"].values()))[comp]
        for run_id, row in a["runs"].items():
            mine = row[comp]
            at = np.searchsorted(times, mine["time"])
            inside = (at < times.size) & (times[np.minimum(at, times.size - 1)] == mine["time"])
            if not inside.all():
                problems.append(f"{run_id} {comp}: {int((~inside).sum())} instants not in B's archive")
                continue
            differ = int((samples[at] != mine["samples"]).sum())
            if differ:
                problems.append(f"{run_id} {comp}: {differ} of {mine['samples'].size} samples differ from B's")
            for key in ("chain", "azimuth", "sensor", "number"):
                if mine[key] != first_b[key]:
                    problems.append(f"{run_id} {comp} {key}: {mine[key]} vs B's {first_b[key]}")
    return problems


def local_problems(a: dict, plain: dict) -> list[str]:
    """Return how A's ex, ey and time axes differ from A's archive without the key; empty when they agree."""
    problems = []
    for comp in ("ex", "ey"):
        times = np.concatenate([row[comp]["time"] for row in plain["runs"].values()])
        samples = np.concatenate([row[comp]["samples"] for row in plain["runs"].values()])
        for run_id, row in a["runs"].items():
            at = np.searchsorted(times, row[comp]["time"])
            if (at >= times.size).any() or not np.array_equal(times[at], row[comp]["time"]):
                problems.append(f"{run_id} {comp}: time axis not A's own")
            elif not np.array_equal(samples[at], row[comp]["samples"]):
                problems.append(f"{run_id} {comp}: samples not A's own")
            if not np.array_equal(row["hx"]["time"], row[comp]["time"]):
                problems.append(f"{run_id}: hx axis is not the {comp} axis")
    return problems


def test_borrow(case: str, b_entry: dict) -> None:
    """Check one case: the samples, chains, metadata, run layout, record and log."""
    from loguru import logger

    root = SCRATCH / case
    write_sites(root)
    survey = two_sites(root, b=b_entry)
    assert survey.site("A").h_from == "B", survey.site("A")
    work = root / "work"
    b_path = ingest_site(survey, "B", out_path=work / "B.h5", overwrite=True)
    plain = ingest_site(two_sites(root, a={"h_from": None}, b=b_entry), "A", out_path=work / "A_plain.h5",
                        overwrite=True)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO", filter=lambda r: "h_from" in r["message"])
    try:
        a_path = ingest_site(survey, "A", out_path=work / "A.h5", overwrite=True)
    finally:
        logger.remove(sink)
    a, b, p = read_runs(a_path, "A"), read_runs(b_path, "B"), read_runs(plain, "A", ("ex", "ey"))

    problems = borrowed_problems(a, b)
    assert not problems, (case, problems)
    problems = local_problems(a, p)
    assert not problems, (case, problems)
    assert a["latitude"] == p["latitude"] != b["latitude"], (a["latitude"], p["latitude"], b["latitude"])

    # the run layout: A's first run whole, the second left out, the third cut
    offset = float(b_entry.get("clock_offset_s", 0.0))
    kept = int(round((B_STARTS[-1] + 4 + offset - A_STARTS[-1]) * 1000))
    sizes = [row["hx"]["samples"].size for row in a["runs"].values()]
    assert sizes == [16000, kept], (case, sizes)
    starts = [row["ex"]["time"][0] for row in a["runs"].values()]
    want = [np.datetime64(EPOCH, "s").astype("datetime64[ns]"), np.datetime64(A_STARTS[-1], "s").astype("datetime64[ns]")]
    assert starts == want, (case, starts)

    # the record
    first, cut = list(a["runs"].values())
    assert "h_from: hx and hy of B" in first["comment"] and "cut" not in first["comment"], first["comment"]
    assert f"cut to the part B covers ({kept} of 4000 samples" in cut["comment"], cut["comment"]
    left_out = f"{np.datetime64(A_STARTS[4], 's')}"
    assert f"h_from B: the recorded run {left_out}" in a["provenance"] and "left out" in a["provenance"], \
        a["provenance"]
    assert archive_h_from(a_path, "A") == "B" and archive_h_from(b_path, "B") is None
    metres = 1000.0 * distance_km(*POSITIONS["A"], *POSITIONS["B"])
    for comp in ("hx", "hy"):
        note = (f"h_from: {comp} of B, {metres:.0f} m away, coil 41, logger 41; aligned by GPS time; the "
                f"neighbour's clock_offset_s {offset!r} applied")
        for row in a["runs"].values():
            assert note in row[comp]["comment"], (case, row[comp]["comment"])
    if b_entry.get("swap_h"):
        assert "swap_h" in first["hx"]["comment"], first["hx"]["comment"]
    pieces = [line for line in lines if "h_from B -> hx, hy over" in line]
    assert len(pieces) == len(a["runs"]), lines
    assert any("hx and hy from B (h_from), 2 of 3 run(s) covered" in line for line in lines), lines
    chain = [name for name, _gain in first["hx"]["chain"]]
    print(f"  {case}: {sum(sizes)} borrowed samples per channel == B's archive at the same instants; runs "
          f"{sizes} (the second left out, the third cut); hx chain {chain}, b_scale "
          f"{dict(first['hx']['chain'])['lemi423_b_scale']:g} (B's, A's is -500); ex, ey and axes A's own; "
          f"comment {first['hx']['comment'][-110:]!r}")

    if case == "plain":
        # the mutation: the borrowed samples read one sample early
        real = ingest._read_borrowed

        def early(plan, g, j0, j1, rate, tag):
            return real(plan, g, j0 - 1, j1 - 1, rate, tag)

        ingest._read_borrowed = early
        try:
            mutant = ingest_site(survey, "A", out_path=work / "mutant.h5", overwrite=True)
        finally:
            ingest._read_borrowed = real
        caught = borrowed_problems(read_runs(mutant, "A"), b)
        assert len(caught) == 2 * len(a["runs"]), caught
        print(f"  mutation (one sample early): {len(caught)} problems, e.g. {caught[0]!r}")

        # the variant keeps the record
        filtered = two_sites(root, b=b_entry, filters=NOTCH)
        ingest_site(filtered, "A", overwrite=True)
        variant = build_variant(filtered, "A")
        assert archive_h_from(variant, "A") == "B"
        assert "h_from: hx of B" in next(iter(read_runs(variant, "A")["runs"].values()))["hx"]["comment"]
        print(f"  variant {variant.name}: archive_h_from B and the channel comments kept")


def test_refusals() -> None:
    """Check the declarations `Survey.site` and `ingest_site` refuse, and that a refused ingest writes nothing."""
    root = SCRATCH / "refusals"
    write_sites(root)
    out = root / "work" / "refused.h5"
    cases = {
        "A has hx and hy": two_sites(root, a={"channels": ["ex", "ey", "hx", "hy"]}),
        "A inherits hx and hy": two_sites(root, a={"channels": None}),
        "B lacks hy": two_sites(root, b={"channels": ["ex", "ey", "hx"]}),
        "B is h_from": two_sites(root, b={"channels": ["ex", "ey"], "h_from": "A"}),
        "B at 500 Hz": two_sites(root, b={"sample_rate": 500.0}),
        "B derived": two_sites(root, a={"h_from": "BL"}, extra={"BL": {"derived_from": "B", "sample_rate": 1.0}}),
        "A names itself": two_sites(root, a={"h_from": "A"}),
        "in defaults": two_sites(root, defaults={"h_from": "B"}),
        "not a name": two_sites(root, a={"h_from": 11}),
        "B2 covers 8 %": two_sites(root, a={"h_from": "B2"}),
    }
    said = {}
    for case, survey in cases.items():
        out.unlink(missing_ok=True)
        try:
            ingest_site(survey, "A", out_path=out, overwrite=True)
        except ValueError as exc:
            assert "h_from" in str(exc), (case, exc)
            assert not out.exists(), f"{case}: a refused ingest wrote a file"
            said[case] = str(exc)
            continue
        raise AssertionError(f"{case}: ingested")
    assert "8.3%" in said["B2 covers 8 %"], said["B2 covers 8 %"]
    # a refused ingest keeps the archive already there
    out.write_bytes(b"kept")
    try:
        ingest_site(cases["B2 covers 8 %"], "A", out_path=out, overwrite=True)
    except ValueError:
        assert out.read_bytes() == b"kept"
    else:
        raise AssertionError("B2 accepted")
    print(f"  refused ({len(said)}): " + "; ".join(f"{k}: {v[:70]!r}" for k, v in list(said.items())[:3])
          + f"; ...; {said['B2 covers 8 %'][:90]!r}; an existing archive kept")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("**This test fails if**", 1)[1].split("\n\nThe mutation")[0])
    print()
    tests = [("plain", lambda: test_borrow("plain", {})),
             ("offset_swap", lambda: test_borrow("offset_swap", {"clock_offset_s": -1.0, "swap_h": True})),
             ("refusals", test_refusals)]
    for name, test in tests:
        test()
        print(f"  ok  {name}")
    print(f"\nPASS  ingest_h_from_unit ({len(tests)} tests)")
