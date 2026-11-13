# -*- coding: utf-8 -*-
"""
Unit test for the record window at ingest (`record_window`, `mt_workbench.ingest._record_window`)

SA106 of South Australia AusLAMP 2013-2018 carries, after its own record
ends on 2014-12-14, 767 h of SA106_2's files (the same logger, read
unswapped), and SA061, SA108, SA115, SA344 and SA320 carry a day of their
second occupation's files at their end. A site
declares `record_window: [start, end]` (UTC ISO, either may be null) and
ingest keeps only the samples at instants t with start <= t < end: a run
is clipped, a run wholly outside is left out, and the run comment and the
station's ``provenance.comments`` say so.

A synthetic EDL site at 10 Hz has two runs: 00:00-00:10 (two 300 s
stamps) and 00:20-00:25 (one stamp). The tests h_from case reuses the two
sites of tests/ingest_h_from_edl_unit.py (A electrics only, `h_from: B`).

Usage:
    python tests/ingest_record_window_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - W1: with `record_window: ["...T00:02:00Z", "...T00:07:30Z"]` the archive
    does not hold exactly one run whose every channel is the files' words
    at instants 00:02:00 <= t < 00:07:30 (samples 1200..4499 of the first
    run, 3300 samples) with its stored start 00:02:00; the second run
    (00:20-00:25, wholly outside) is not left out; the run comment lacks
    "record_window:" or the station provenance lacks the window and the
    left-out run;
  - W2: with `[null, "...T00:20:00Z"]` the first run is not kept whole
    (6000 samples, untouched) and the second left out; with
    `["...T00:21:00Z", null]` the first run is not left out or the second
    not cut to 00:21:00 onward (2400 samples, the words from sample 600);
  - W3: no key, or a window enclosing every sample, changes any sample or
    the number of runs against the archive without the key;
  - W4: on the h_from pair (A borrows B's hx, hy) with A's window
    ["...T00:02:00Z", "...T01:05:00Z"], A keeps an instant outside the
    window, or a kept instant's hx/hy differs from B's own archive or its
    ex/ey from A's files, or A's run sizes are not [4800, 2000, 1000]
    (00:02-00:10, B covering A's first run to 00:10; then 01:00-01:03:20
    and 01:03:20-01:05, A's second run split by h_from at B's run boundary;
    ingest_h_from_edl_unit without a window gives 6000, 2000, 4000, and the
    window cuts the last piece to 1000).
  - W5: `SiteConfig` accepts `[null, null]`, a window with start >= end, a
    string that is not a time, or a list of one; or `Survey.site` accepts a
    site whose survey.yaml `start` lies before the window's start or `end`
    after the window's end (the span the campaign reads must be the
    clipped span).

Mutation: with `_record_window` returning every run untouched (the window
ignored), W1 must fail.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import SiteConfig, Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
import ingest_h_from_edl_unit as hf  # noqa: E402

SCRATCH = scratch_dir("ingest_record_window_unit")
SITE = "RWS"
T0 = pd.Timestamp("2014-12-14T00:00:00", tz="UTC")
FS = 10.0
STAMPS = (0, 300, 1200)  # seconds after T0: run 1 = 0 and 300 (contiguous), run 2 = 1200
COMPS = ("hx", "hy", "hz", "ex", "ey")
SUFFIX = {"hx": "BX", "hy": "BY", "hz": "BZ", "ex": "EX", "ey": "EY"}


def iso(seconds: float) -> str:
    """Return T0 + seconds as a UTC ISO string with Z."""
    return (T0 + pd.Timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_site(root: Path) -> dict[str, dict[int, float]]:
    """Write the EDL site; return each file suffix's words by instant (ns)."""
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / SITE
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(106)
    truth: dict[str, dict[int, float]] = {}
    for offset in STAMPS:
        when = T0 + pd.Timedelta(seconds=offset)
        t = when.value + np.round(np.arange(3000) * 1e9 / FS).astype("int64")
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            values = rng.integers(-2_000_000, 2_000_000, 3000)
            np.savetxt(site / f"{SITE}_{when:%y%m%d%H%M%S}.{suffix}", values, fmt="%d")
            truth.setdefault(suffix, {}).update(zip(t.tolist(), values.astype(float).tolist()))
    return truth


def survey(root: Path, own: dict) -> Survey:
    """Build the one-site EDL survey with the site's own entry."""
    return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                   "workspace": str(root / "work"),
                   "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "flip_reversed_dipoles": True},
                   "sites": {SITE: own}}, root)


def runs_of(path: Path, station: str = SITE) -> tuple[list[dict], str]:
    """Return each run's id, start (ns), comment and channel samples, and the station's provenance comment."""
    out = []
    with h5py.File(path, "r") as f:
        st = f[f"Experiment/Surveys/t/Stations/{station}"]
        prov = st.attrs.get("provenance.comments")
        prov = prov.decode() if isinstance(prov, bytes) else str(prov or "")
        for name, g in st.items():
            if not isinstance(g, h5py.Group) or g.attrs.get("mth5_type") != "Run":
                continue
            c = g.attrs.get("comments")
            row = {"id": name, "start": pd.Timestamp(g.attrs["time_period.start"]).value,
                   "comment": c.decode() if isinstance(c, bytes) else str(c or "")}
            for comp in g:
                if isinstance(g[comp], h5py.Dataset):
                    row[comp] = g[comp][()]
            out.append(row)
    return sorted(out, key=lambda r: r["start"]), prov


def instants(run: dict) -> np.ndarray:
    """Return the instants (ns) of a run's samples."""
    return run["start"] + np.round(np.arange(run["ex"].size) * 1e9 / FS).astype("int64")


def window_problems(runs: list[dict], truth: dict, lo: float | None, hi: float | None,
                    want_sizes: list[int]) -> list[str]:
    """Return what is wrong with the runs against the files' words inside [lo, hi) (seconds after T0)."""
    out = []
    if [r["ex"].size for r in runs] != want_sizes:
        out.append(f"run sizes {[r['ex'].size for r in runs]}, want {want_sizes}")
    a = None if lo is None else (T0 + pd.Timedelta(seconds=lo)).value
    b = None if hi is None else (T0 + pd.Timedelta(seconds=hi)).value
    for r in runs:
        t = instants(r)
        if (a is not None and t.min() < a) or (b is not None and t.max() >= b):
            out.append(f"{r['id']} keeps an instant outside the window ({t.min()} .. {t.max()})")
        for comp in COMPS:
            want = np.array([truth[SUFFIX[comp]].get(int(x), np.nan) for x in t])
            if not np.array_equal(r[comp].astype(float), want):
                out.append(f"{r['id']} {comp} is not the files' words at its instants")
    return out


def test_clip() -> None:
    """W1, W2, W3: the clip, the run left out, the record, and no change without the key."""
    root = SCRATCH / "site"
    truth = write_site(root)
    work = root / "work"
    plain = ingest_site(survey(root, {}), SITE, out_path=work / "plain.h5", overwrite=True)
    p_runs, _ = runs_of(plain)
    assert [r["ex"].size for r in p_runs] == [6000, 3000], [r["ex"].size for r in p_runs]

    w1 = {"record_window": [iso(120), iso(450)]}
    runs, prov = runs_of(ingest_site(survey(root, w1), SITE, out_path=work / "w1.h5", overwrite=True))
    problems = window_problems(runs, truth, 120, 450, [3300])
    if runs and runs[0]["start"] != (T0 + pd.Timedelta(seconds=120)).value:
        problems.append(f"stored start {runs[0]['start']}")
    if runs and "record_window:" not in runs[0]["comment"]:
        problems.append(f"run comment lacks record_window: {runs[0]['comment'][-300:]}")
    if "record_window:" not in prov or "left out" not in prov:
        problems.append(f"provenance lacks the window or the run left out: {prov[-400:]}")
    assert not problems, problems
    print(f"  W1 window {w1['record_window']}: one run of 3300 samples from 00:02:00, every channel == the files' "
          f"words; the 00:20 run left out; run comment and provenance record it")

    real = ingest._record_window

    def ignored(piece, site):
        """The mutation: the window ignored."""
        return piece, None

    ingest._record_window = ignored
    try:
        mutant = ingest_site(survey(root, w1), SITE, out_path=work / "mutant.h5", overwrite=True)
    finally:
        ingest._record_window = real
    caught = window_problems(runs_of(mutant)[0], truth, 120, 450, [3300])
    assert caught, "the mutation (window ignored) passed W1"
    print(f"  W1 mutation (window ignored): {caught[0]!r}")

    for own, lo, hi, sizes, tag in (({"record_window": [None, iso(1200)]}, None, 1200, [6000], "end only"),
                                    ({"record_window": [iso(1260), None]}, 1260, None, [2400], "start only")):
        runs, prov = runs_of(ingest_site(survey(root, own), SITE, out_path=work / "w2.h5", overwrite=True))
        problems = window_problems(runs, truth, lo, hi, sizes)
        assert not problems, (tag, problems)
        print(f"  W2 {tag} {own['record_window']}: runs {[r['ex'].size for r in runs]} == the words inside")

    whole = {"record_window": [iso(-60), iso(3600)]}
    for own, tag in (({}, "no key"), (whole, "enclosing window")):
        runs, _ = runs_of(ingest_site(survey(root, own), SITE, out_path=work / "w3.h5", overwrite=True))
        same = len(runs) == len(p_runs) and all(
            r["start"] == q["start"] and all(np.array_equal(r[c], q[c]) for c in COMPS) for r, q in zip(runs, p_runs))
        assert same, tag
    print("  W3 no key and an enclosing window: every run and sample as without the key")


def test_h_from() -> None:
    """W4: the window on a site that borrows its hx and hy."""
    root = SCRATCH / "pair"
    a_truth = hf.write(root, "A", hf.A_FILES, 1, field=False)
    hf.write(root, "B", hf.B_FILES, 2, field=True)
    t0 = hf.T0
    lo, hi = t0 + pd.Timedelta(seconds=120), t0 + pd.Timedelta(seconds=3900)
    own = {"record_window": [lo.strftime("%Y-%m-%dT%H:%M:%SZ"), hi.strftime("%Y-%m-%dT%H:%M:%SZ")]}
    sv = hf.survey(root, own)
    b = ingest_site(sv, "B", out_path=root / "work" / "B.h5", overwrite=True)
    a = ingest_site(sv, "A", out_path=root / "work" / "A.h5", overwrite=True)
    a_runs, b_runs = hf.runs_of(a, "A"), hf.runs_of(b, "B")
    problems = hf.problems_of(a_runs, b_runs, a_truth)
    step = int(1e9 / FS)
    for r in a_runs:
        t = r["start"] + np.arange(r["ex"].size) * step
        if t.min() < lo.value or t.max() >= hi.value:
            problems.append(f"{r['id']} keeps an instant outside the window")
    sizes = [r["ex"].size for r in a_runs]
    if sizes != [4800, 2000, 1000]:  # 00:02-00:10 (B covers to 00:10), 01:00-01:03:20, 01:03:20-01:05
        problems.append(f"A run sizes {sizes}, want [4800, 2000, 1000]")
    assert not problems, problems
    print(f"  W4 h_from A window {own['record_window']}: runs {sizes}, hx/hy == B's archive, ex/ey == A's files, "
          f"nothing outside the window")


def test_refusals() -> None:
    """W5: malformed windows and a survey span outside the window are refused."""
    for bad in ([None, None], [iso(450), iso(120)], [iso(120), iso(120)], ["soon", None], [iso(120)], iso(120)):
        try:
            SiteConfig(name="X", record_window=bad)
        except ValueError as exc:
            assert "record_window" in str(exc), exc
        else:
            raise AssertionError(f"record_window {bad!r} accepted")
    ok = SiteConfig(name="X", record_window=[iso(120), None])
    assert ok.record_window == [iso(120), None], ok.record_window
    root = SCRATCH / "site"
    for own, tag in (({"record_window": [iso(120), None], "start": iso(0), "end": iso(1500)}, "start before"),
                     ({"record_window": [None, iso(450)], "start": iso(0), "end": iso(1500)}, "end after")):
        try:
            survey(root, own).site(SITE)
        except ValueError as exc:
            assert "record_window" in str(exc), exc
        else:
            raise AssertionError(f"survey span {tag} the window accepted")
    survey(root, {"record_window": [iso(120), iso(450)], "start": iso(120), "end": iso(450)}).site(SITE)
    print("  W5 refused: [null, null], start >= end, a non-time, a list of one, a bare string; survey start "
          "before / end after the window; a span inside it accepted")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    for test in (test_clip, test_h_from, test_refusals):
        test()
        print(f"  ok  {test.__name__}")
    print("\nPASS  ingest_record_window_unit (3 tests)")
