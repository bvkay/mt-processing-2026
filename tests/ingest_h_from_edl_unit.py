# -*- coding: utf-8 -*-
"""
Unit test for borrowed magnetics between two EDL sites (`h_from`, `mt_workbench.ingest._h_from_plan_edl`)

TAS132 of Tasmania AusLAMP 2016 takes TAS131's hx and hy (its own fluxgate
turned 13.9 deg during the record; the release used TAS131's too). Two
synthetic EDL sites at 10 Hz are written: A recorded electrics only
(`channels: [ex, ey]`, `h_from: B`) in two runs, 00:00-00:15 (three 300 s
stamps) and 01:00-01:10 (two), and B, whose fluxgate lies at +30 deg in its
sensor frame (`rot_h: 30.0`), recorded 23:55-00:10 (three stamps) and then
00:58:20-01:20 with a restart file stamped 01:03:00 inside its 00:58:20 file
(an overlap of 20 s, trimmed). So B covers A's first run in part (00:00 to
00:10) and its second whole, through B's trimmed run. A is ingested with
the key, B on its own, and the archives compared with h5py.

Usage:
    python tests/ingest_h_from_edl_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - any sample of A's borrowed hx or hy differs from B's own archive's hx
    or hy at the same instant (B turned by its rot_h 30.0, its restart
    trimmed), or an instant of A's runs has no sample in B's archive;
  - A's ex and ey differ from A's own files at the same instants, or A
    keeps any sample of its first run after 00:10 (B does not cover it);
  - `archive_h_from` does not read B from A's archive, the borrowed hx's
    comment lacks B's rot_h line, or the station's provenance does not
    name B with its rot_h;
  - `Survey.site` accepts `rot_h` on A with `h_from`.

Mutation: with the borrowed samples taken one sample late, the sample
check must fail.
"""

from __future__ import annotations

import math
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
from mt_workbench.ingest import archive_h_from, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("ingest_h_from_edl_unit")
T0 = pd.Timestamp("2016-08-10T00:00:00", tz="UTC")
FS = 10.0
# (offset s, samples) of each site's stamps
A_FILES = ((0, 3000), (300, 3000), (600, 3000), (3600, 3000), (3900, 3000))
B_FILES = ((-300, 3000), (0, 3000), (300, 3000), (3500, 3000), (3780, 3000), (4080, 3000))
H = 20_000.0 * 142.857


def write(root: Path, name: str, files, seed: int, field: bool) -> dict[str, dict[int, float]]:
    """Write one EDL site; return each channel's words by instant (ns), the earlier file's at a repeat."""
    site = root / "raw" / name
    shutil.rmtree(site, ignore_errors=True)
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(seed)
    truth: dict[str, dict[int, float]] = {}
    for offset, n in files:
        when = T0 + pd.Timedelta(seconds=offset)
        words = {s: rng.integers(-2_000_000, 2_000_000, n) for s in ("BX", "BY", "BZ", "EX", "EY")}
        if field:
            a = math.radians(30.0)
            words["BX"] = int(H * math.cos(a)) + rng.integers(-500, 500, n)
            words["BY"] = int(H * math.sin(a)) + rng.integers(-500, 500, n)
        t = when.value + np.round(np.arange(n) * 1e9 / FS).astype("int64")
        for suffix, values in words.items():
            np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}", values, fmt="%d")
            for ti, v in zip(t, values):
                truth.setdefault(suffix, {}).setdefault(int(ti), float(v))
    return truth


def survey(root: Path, a: dict | None = None) -> Survey:
    """Build the survey of A (electrics only, h_from B) and B (rot_h 30.0)."""
    base = {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "channels": ["ex", "ey", "hx", "hy", "hz"]}
    sites = {"A": {"channels": ["ex", "ey"], "h_from": "B", "latitude": -42.0, "longitude": 146.0, **(a or {})},
             "B": {"rot_h": 30.0, "latitude": -42.0, "longitude": 146.02}}
    return Survey({"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
                   "workspace": str(root / "work"), "defaults": base, "sites": sites}, root)


def runs_of(path: Path, station: str) -> list[dict]:
    """Return each run's start (ns), comment and channel samples and comments."""
    out = []
    with h5py.File(path, "r") as f:
        st = f[f"Experiment/Surveys/t/Stations/{station}"]
        for name, g in st.items():
            if not isinstance(g, h5py.Group) or g.attrs.get("mth5_type") != "Run":
                continue
            row = {"id": name, "start": pd.Timestamp(g.attrs["time_period.start"]).value}
            for comp in g:
                if isinstance(g[comp], h5py.Dataset):
                    c = g[comp].attrs.get("comments")
                    row[comp] = g[comp][()]
                    row[comp + "_comment"] = c.decode() if isinstance(c, bytes) else str(c or "")
            out.append(row)
    return sorted(out, key=lambda r: r["start"])


def problems_of(a_runs: list[dict], b_runs: list[dict], a_truth: dict) -> list[str]:
    """Return what is wrong with A's runs against B's archive and A's files; empty when right."""
    step = int(1e9 / FS)
    b_at = {}
    for r in b_runs:
        t = r["start"] + np.arange(r["hx"].size) * step
        for comp in ("hx", "hy"):
            b_at.setdefault(comp, {}).update(zip(t.tolist(), r[comp].tolist()))
    out = []
    for r in a_runs:
        t = r["start"] + np.arange(r["ex"].size) * step
        for comp in ("hx", "hy"):
            want = np.array([b_at[comp].get(int(x), np.nan) for x in t])
            if not np.array_equal(r[comp], want):
                out.append(f"{r['id']} {comp} differs from B's archive at the same instants")
        for comp, suffix in (("ex", "EX"), ("ey", "EY")):
            want = np.array([a_truth[suffix].get(int(x), np.nan) for x in t])
            if not np.array_equal(r[comp], want):
                out.append(f"{r['id']} {comp} differs from A's files")
        if t[0] < (T0 + pd.Timedelta(seconds=3000)).value < t[-1] or (
                t[0] < (T0 + pd.Timedelta(seconds=600)).value and t[-1] >= (T0 + pd.Timedelta(seconds=600)).value):
            out.append(f"{r['id']} keeps samples B does not cover")
    return out


def test_edl_h_from() -> None:
    """The borrowed EDL magnetics, the record and the refusal."""
    root = SCRATCH / "pair"
    a_truth = write(root, "A", A_FILES, 1, field=False)
    write(root, "B", B_FILES, 2, field=True)
    sv = survey(root)
    b = ingest_site(sv, "B", out_path=root / "work" / "B.h5", overwrite=True)
    a = ingest_site(sv, "A", out_path=root / "work" / "A.h5", overwrite=True)
    a_runs, b_runs = runs_of(a, "A"), runs_of(b, "B")
    problems = problems_of(a_runs, b_runs, a_truth)
    assert not problems, problems
    assert archive_h_from(a, "A") == "B", archive_h_from(a, "A")
    assert "rot_h: 30.0 deg applied at ingest" in a_runs[0]["hx_comment"], a_runs[0]["hx_comment"]
    with h5py.File(a, "r") as f:
        prov = str(f["Experiment/Surveys/t/Stations/A"].attrs.get("provenance.comments"))
    assert "h_from: hx and hy of B" in prov and "rot_h 30.0" in prov, prov
    print(f"  A runs {[(r['id'], r['ex'].size) for r in a_runs]}: hx, hy == B's archive (rot_h 30.0, its restart "
          f"trimmed) at every instant; ex, ey == A's files; the first run cut at 00:10 (B's gap); "
          f"archive_h_from B; provenance names B's rot_h")

    real = ingest._read_borrowed_edl

    def late(plan, g, j0, j1, rate, tag):
        """The mutation: the neighbour's samples one late."""
        out, lid = real(plan, g, j0, j1, rate, tag)
        return {c: (np.roll(s, 1), at, fl) for c, (s, at, fl) in out.items()}, lid

    ingest._read_borrowed_edl = late
    try:
        mutant = ingest_site(sv, "A", out_path=root / "work" / "mutant.h5", overwrite=True)
    finally:
        ingest._read_borrowed_edl = real
    caught = problems_of(runs_of(mutant, "A"), b_runs, a_truth)
    assert any("differs from B's archive" in p for p in caught), caught
    print(f"  mutation (one sample late): {caught[0]!r}")
    try:
        survey(root, {"rot_h": 10.0}).site("A")
    except ValueError as exc:
        assert "rot_h" in str(exc), exc
        print(f"  rot_h with h_from refused: {str(exc)[:90]}...")
    else:
        raise AssertionError("rot_h with h_from accepted")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    test_edl_h_from()
    print("  ok  test_edl_h_from")
    print("\nPASS  ingest_h_from_edl_unit (1 test)")
