# -*- coding: utf-8 -*-
"""
Offline unit test for scripts/observatory_from_parquet.py

A two-day synthetic one-second record of observatory CNB (-35.315, 149.363
east, 859 m) for 2016-01-22 and 2016-01-23 is built in memory: X = 23070 +
50 sin(2 pi k / 600), Y = 5146 + 30 cos(2 pi k / 900), Z = -52963 +
20 sin(2 pi k / 3600) nT and F the vector length, at second k from
2016-01-22T00:00:00Z, so the values are not on the 0.01 nT grid of the
format. X, Y, Z and F are NaN for k = 3600..3619 (a 20 s gap), and the rows
of k = 86000..86999 are absent (a 1000 s gap across midnight). The first
day's publication state is provisional, the second's variation. Each day is
rendered by the script's `render_day`, stored by its `write_day` and read
back with `mt_workbench.observatory.read_day` and `load`. Part (c) writes the
record as a small parquet file, with a third day of NaN rows, and runs the
script's command line on it; it needs pyarrow and is skipped with a message
on an interpreter without it. Everything is written under a temporary
directory, removed at the end.

Usage:
    python tests/observatory_from_parquet_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
(a) importing the script or rendering a day imports pyarrow; the script's `day_path` differs from
    `observatory.day_path`; a rendered line is not 70 characters; `read_day` of a stored day does not
    give exactly 86400 rows at 00:00:00 + k s for k = 0..86399, x, y, z, f within 0.005 nT of the
    input wherever the input is finite and NaN exactly where it is NaN or absent, `header_position`
    (-35.315, 149.363, 859.0), IAGA Code CNB, the day's Data Type, and the fetch time given to
    `write_day`; or a day rendered at longitude -5.942 does not carry 354.058 in its header and read
    back as -5.942;
(b) `observatory.load` over the two days does not give 172800 samples with x, y, z at k = 3600..3619
    on the straight line between the samples at k = 3599 and 3620 (1e-9 nT) and masked, NaN at every
    k = 86000..86999, within 0.005 nT of the input everywhere else, and f NaN at k = 3600..3619; the
    finite stretches are not exactly [0, 86000) and [87000, 172800) (the two runs `to_mth5` writes); or
    its meta does not report 20 samples filled, a longest unfilled gap of 1000 s, the position above
    and 86400 samples each of provisional and variation;
(c) with pyarrow importable: --dry-run returns non-zero, writes any file, or does not list the three
    days as days it would write and the third as all missing; the run does not write three days whose
    values read back identical to (a)'s, with the parquet's modification time as the fetch time,
    comments naming the parquet, its fetch record and the script's version, and the third day all
    NaN with the "No finite X, Y, Z" comment; a second run rewrites a byte or does not report the
    three days kept; --force on one day rewrites any other day; or an observatory with no known
    position and no --lat/--lon/--elev does not return 2 with nothing written.
"""

from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench import observatory  # noqa: E402

SCRIPT = REPO / "scripts" / "observatory_from_parquet.py"
CODE = "CNB"
LAT, LON, ELEV = -35.315, 149.363, 859.0
DAYS = ("2016-01-22", "2016-01-23")
PUB = {"2016-01-22": "provisional", "2016-01-23": "variation"}
T0 = pd.Timestamp(DAYS[0]).value  # ns
N = 2 * 86400
NAN20 = np.arange(3600, 3620)
GAP = np.arange(86000, 87000)
FETCHED = datetime(2026, 9, 12, 10, 25, 28, tzinfo=timezone.utc)
TOL = 0.005 + 1e-9


def load_script():
    """Import scripts/observatory_from_parquet.py as a module."""
    spec = importlib.util.spec_from_file_location("observatory_from_parquet", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic() -> dict:
    """Return the synthetic record: every second's input (NaN in gaps) and the rows that exist."""
    k = np.arange(N, dtype=float)
    x = 23070.0 + 50.0 * np.sin(2 * np.pi * k / 600.0)
    y = 5146.0 + 30.0 * np.cos(2 * np.pi * k / 900.0)
    z = -52963.0 + 20.0 * np.sin(2 * np.pi * k / 3600.0)
    f = np.sqrt(x**2 + y**2 + z**2)
    full = dict(x=x, y=y, z=z, f=f)
    for v in full.values():
        v[NAN20] = np.nan
        v[GAP] = np.nan  # what the grid holds where rows are absent
    keep = np.ones(N, bool)
    keep[GAP] = False
    rows = {c: v[keep] for c, v in full.items()}
    rows["times"] = T0 + np.flatnonzero(keep).astype(np.int64) * 10**9
    rows["pub"] = np.where(rows["times"] < T0 + 86400 * 10**9, PUB[DAYS[0]], PUB[DAYS[1]]).astype(object)
    return dict(full=full, rows=rows)


def day_rows(rows: dict, i: int) -> dict:
    """Return the rows of day i (0 or 1)."""
    lo, hi = T0 + i * 86400 * 10**9, T0 + (i + 1) * 86400 * 10**9
    sel = (rows["times"] >= lo) & (rows["times"] < hi)
    return {c: v[sel] for c, v in rows.items()}


def run(script, *args) -> tuple[int, str, str]:
    """Run the script's main and return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = script.main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path) -> dict[str, bytes]:
    """Return the bytes of every file under root, keyed by relative path."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def text_of(path: Path) -> str:
    """Return the IAGA-2002 text of a cached day."""
    with gzip.open(path, "rb") as g:
        return g.read().decode("ascii")


# ---------------------------------------------------------------------- (a)


def test_a_render(tmp: Path, script, data: dict, pyarrow_before: bool) -> dict:
    cache = tmp / "cache_a"
    worst, got_days = 0.0, {}
    for i, day in enumerate(DAYS):
        r = day_rows(data["rows"], i)
        raw = script.render_day(day, r["times"], r["x"], r["y"], r["z"], r["f"], code=CODE, latitude=LAT,
                                longitude=LON, elevation=ELEV, data_type=PUB[day], station_name="Canberra",
                                source="Geoscience Australia", comments=["synthetic record of the unit test"])
        lengths = {len(line) for line in raw.decode("ascii").splitlines()}
        assert lengths == {70}, f"{day}: line lengths {sorted(lengths)}"
        path = script.day_path(cache, CODE, day)
        assert path == observatory.day_path(cache, CODE, day), (path, observatory.day_path(cache, CODE, day))
        script.write_day(path, raw, FETCHED)
        got = observatory.read_day(path)
        t_day = T0 // 10**9 + i * 86400
        assert got["times"].dtype == np.int64 and np.array_equal(got["times"], t_day + np.arange(86400)), \
            (day, got["times"][:3], got["times"].size)
        for c in ("x", "y", "z", "f"):
            want = data["full"][c][i * 86400:(i + 1) * 86400]
            nan = ~np.isfinite(want)
            assert np.array_equal(np.isnan(got[c]), nan), (day, c, np.flatnonzero(np.isnan(got[c]) != nan)[:5])
            err = float(np.max(np.abs(got[c][~nan] - want[~nan])))
            assert err <= TOL, (day, c, err)
            worst = max(worst, err)
        assert observatory.header_position(got["header"]) == (LAT, LON, ELEV), got["header"]
        assert got["header"]["IAGA Code"] == CODE and got["header"]["Data Type"] == PUB[day], got["header"]
        assert got["fetched"] == FETCHED, got["fetched"]
        got_days[day] = got
    west = script.render_day(DAYS[0], [], [], [], [], [], code="SFS", latitude=36.665, longitude=-5.942,
                             elevation=111.0, data_type="provisional")
    head = observatory.parse_iaga2002(west)["header"]
    assert head["Geodetic Longitude"] == "354.058", head
    assert observatory.header_position(head) == (36.665, -5.942, 111.0), head
    loaded = "pyarrow" in sys.modules
    assert pyarrow_before or not loaded, "importing the script or rendering a day imported pyarrow"
    nan_rows = int(np.isnan(got_days[DAYS[0]]["x"]).sum() + np.isnan(got_days[DAYS[1]]["x"]).sum())
    print(f"  (a) 2 days x 86400 rows on the whole-second grid, every line 70 characters; max |read - input| "
          f"{worst:.6f} nT (<= 0.005); {nan_rows} NaN rows = 20 NaN + 1000 absent; position "
          f"{observatory.header_position(got_days[DAYS[0]]['header'])}; Data Type provisional / variation; "
          f"fetch time {FETCHED:%Y-%m-%dT%H:%M:%SZ} from the gzip header; -5.942 E written 354.058, read -5.942")
    print(f"      pyarrow {'was loaded by pandas before the script (check not applicable here)' if pyarrow_before else 'not imported by the script or the render'}")
    return got_days


# ---------------------------------------------------------------------- (b)


def test_b_load(tmp: Path, data: dict) -> None:
    cache = tmp / "cache_a"
    got = observatory.load(CODE, DAYS[0], DAYS[1], cache, max_gap_s=600.0)
    assert got["x"].size == N and np.array_equal(got["times"].astype(np.int64), T0 // 10**9 + np.arange(N))
    for c in ("x", "y", "z"):
        v = got[c]
        line = np.interp(NAN20, [3599, 3620], [v[3599], v[3620]])
        assert np.max(np.abs(v[NAN20] - line)) < 1e-9, (c, v[NAN20][:3], line[:3])
        assert not np.isfinite(v[GAP]).any(), f"{c}: the 1000 s gap was filled"
        rest = np.ones(N, bool)
        rest[NAN20] = rest[GAP] = False
        err = float(np.max(np.abs(v[rest] - data["full"][c][rest])))
        assert err <= TOL, (c, err)
    assert not got["mask"][NAN20].any() and not got["mask"][GAP].any() and got["mask"][:3600].all()
    assert np.isnan(got["f"][NAN20]).all(), "f was filled"
    finite = np.isfinite(got["x"]) & np.isfinite(got["y"]) & np.isfinite(got["z"])
    stretches = observatory._runs(finite)
    assert stretches == [(0, 86000), (87000, N)], stretches
    m = got["meta"]
    assert m["gaps"]["n_filled"] == 20 and m["gaps"]["longest_unfilled_gap_s"] == 1000, m["gaps"]
    assert (m["latitude"], m["longitude"], m["elevation"]) == (LAT, LON, ELEV), m
    assert m["data_types"] == {"provisional": 86400, "variation": 86400}, m["data_types"]
    assert m["days_missing"] == [], m["days_missing"]
    print(f"  (b) load: 20 s gap filled on the line and masked, 1000 s gap NaN; runs {stretches}; gaps {m['gaps']}; "
          f"data types {m['data_types']}")


# ---------------------------------------------------------------------- (c)


def test_c_cli(tmp: Path, script, data: dict, got_days: dict) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print(f"  (c) SKIP: pyarrow is not importable on {sys.executable}; run this test on an interpreter "
              f"with pyarrow for the command-line part")
        return
    folder = tmp / "obs"
    folder.mkdir()
    r = data["rows"]
    t3 = T0 + 2 * 86400 * 10**9 + np.arange(86400, dtype=np.int64) * 10**9  # a third day of NaN rows
    nan3 = np.full(86400, np.nan)
    table = pa.table({
        "DateTime": pa.array(np.r_[r["times"], t3].astype("datetime64[ns]"), pa.timestamp("ns")),
        "BX": np.r_[r["x"], nan3], "BY": np.r_[r["y"], nan3], "BZ": np.r_[r["z"], nan3], "F": np.r_[r["f"], nan3],
        "pub": pa.array(list(r["pub"]) + ["variation"] * 86400, pa.string())})
    parquet = folder / "CNB_fixture.parquet"
    pq.write_table(table, parquet)
    (folder / "run_fetch_1sec.json").write_text(json.dumps({"runs": []}))
    os.utime(parquet, (FETCHED.timestamp(), FETCHED.timestamp()))
    cache = tmp / "cache_c"
    days3 = list(DAYS) + ["2016-01-24"]

    everything = snapshot(tmp)
    code, out, err = run(script, parquet, "cnb", "--cache", cache, "--dry-run")
    assert code == 0, (code, out, err)
    assert snapshot(tmp) == everything and not cache.exists(), "--dry-run wrote something"
    assert "would write: 2016-01-22 .. 2016-01-24 (3)" in out, out
    assert "would write all missing (no finite X, Y, Z): 2016-01-24" in out, out
    print(f"  (c) --dry-run: exit 0, no file written; {[ln.strip() for ln in out.splitlines() if ln.startswith('  would write:')]}")

    code, out, err = run(script, parquet, "cnb", "--cache", cache)
    assert code == 0, (code, out, err)
    paths = [observatory.day_path(cache, CODE, d) for d in days3]
    assert all(p.exists() for p in paths) and len(snapshot(cache)) == 3, list(snapshot(cache))
    for day, p in zip(DAYS, paths):
        got = observatory.read_day(p)
        for c in ("times", "x", "y", "z", "f"):
            assert np.array_equal(got[c], got_days[day][c], equal_nan=True), (day, c)
        assert got["fetched"] == FETCHED, got["fetched"]
        text = text_of(p)
        for word in ("CNB_fixture.parquet", "run_fetch_1sec.json", "observatory_from_parquet 1.0"):
            assert word in text, (day, word)
    got3 = observatory.read_day(paths[2])
    assert got3["times"].size == 86400 and np.isnan(got3["x"]).all() and got3["header"]["Data Type"] == "variation"
    assert "No finite X, Y, Z in the parquet for this day." in text_of(paths[2])
    print("  (c) run: 3 days written; days 1-2 read back identical to (a), fetch time = the parquet's mtime, "
          "comments name the parquet, run_fetch_1sec.json and version 1.0; day 3 all NaN with its comment")

    held = snapshot(cache)
    code, out, err = run(script, parquet, "CNB", "--cache", cache)
    assert code == 0 and snapshot(cache) == held, (code, err)
    assert "kept (already in the cache): 2016-01-22 .. 2016-01-24 (3)" in out, out
    mtimes = {p: p.stat().st_mtime_ns for p in paths}
    code, out, err = run(script, parquet, "CNB", "--cache", cache, "--start", "2016-01-23", "--end", "2016-01-23",
                         "--force")
    assert code == 0 and "written: 2016-01-23" in out and snapshot(cache) == held, (code, out, err)
    assert mtimes[paths[0]] == paths[0].stat().st_mtime_ns and mtimes[paths[2]] == paths[2].stat().st_mtime_ns
    print("  (c) second run: 3 days kept, bytes unchanged; --force on 2016-01-23 rewrote that day alone, same bytes")

    before = snapshot(tmp)
    code, out, err = run(script, parquet, "XYZ", "--cache", tmp / "cache_x")
    assert code == 2 and "no position" in err and snapshot(tmp) == before, (code, err)
    print(f"  (c) unknown observatory without a position: exit 2, nothing written ({err.strip()!r})")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    pyarrow_before = "pyarrow" in sys.modules  # pandas loads it on some interpreters
    script = load_script()
    data = synthetic()
    with tempfile.TemporaryDirectory(prefix="observatory_from_parquet_unit_") as name:
        tmp = Path(name)
        got_days = test_a_render(tmp, script, data, pyarrow_before)
        test_b_load(tmp, data)
        test_c_cli(tmp, script, data, got_days)
    print(f"\nPASS  observatory_from_parquet_unit on {Path(sys.executable).parent.name} "
          f"({datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ})")
