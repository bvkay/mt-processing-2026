# -*- coding: utf-8 -*-
"""
Unit test for the Stacks tab's availability rows (mt_workbench.gui.availability_model)

Writes a synthetic 1 Hz survey into the test's scratch folder: real MTH5
archives laid out as `mt_workbench.ingest.ingest_site` writes them (survey
SYNTH, runs sr1_000k through RunTS / `from_runts`, int32 counts), with
dc-level records written into two run comments, a text file named G.h5, a
10 Hz entry and an entry with no archive. The runs, groups, hour counts,
default windows, nights and tree windows are checked against values
computed here by hand or by an independent code path. No Qt.

- S1: hx hy ex ey, runs 0-30 h and 31-80 h from 2024-03-01 00:00 UTC;
- S2: hx hy only, runs 2-12 h and 14-54 h;
- S3: hx hy ex ey, one run 0-72 h;
- S4: hx hy, one run 50-60 h;
- S5: hx hy, runs 0-24 h (86400 samples) and from 48 h (30000 samples), so
  its second 24 h tree window has no samples;
- F10: 10 Hz, no archive; NA: 1 Hz, no archive; G (second survey only): G.h5
  is text.

Usage:
    python tests/availability_model_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. `read_runs` of S2 (two runs, hx and hy only) does not return the written
   runs, (start, start + (n - 1) s), under "all" and "H", and [] under "E";
   its "dc" of S1 is not the dict {channel: verdict} worked out here from the
   two runs' records (the most severe verdict per channel); or G.h5 (text)
   or a missing file does not raise OSError;
2. the rows of
   `build_rows` over `stacks.resolve_members(..., runs_of=cache.runs_of(survey))`,
   after `RunsCache.read` of every archive, give any member, overlap or
   reason different from `stacks.resolve_members` with its default h5py
   reads, for a rule recipe, a list recipe, a rule recipe with a local and
   one with an exclude list; before any read a site the default reads judge
   on its runs does not read `intersite.NOT_READ`; or G, whose read raised
   OSError, does not read "archive unreadable: ..."; or, given masks
   {S1: [one mask], S2: the text of a masks.yaml error}, S1's row does not
   hold that list with no error, S2's does not hold that text with no list,
   or any other row holds either;
3. `group_rows` puts a site under any reference but the one whose runs it
   overlaps most (the earlier on a tie, so the order of the references
   decides it), orders the groups otherwise than given, keeps a site that
   overlaps no reference or is not read out of the group "", or gives
   anything but the one group "" with no references;
4. `members_per_hour` differs from the hand count over 10:00-13:00: a run to
   12:30 counts in hours 10 and 11 and not 12; one ending 11:59:30 counts in
   11 with the 60 s edge and not with edge 0; one from 10:00:30 to 11:58:30
   counts in 10 only; two runs 1 ms apart count as one record, two runs
   2 min apart do not, and with ``merge=False`` (a time recipe, each run
   alone) the 1 ms pair counts in hour 11 only, which its second run
   covers; an E-only run and a site not among the candidates count
   nowhere; or `best_window` does not give the longest run of hours at the
   top count (the earliest of equal runs), or None when no hour counts;
5. `night_spans` differs by a nanosecond from scripts/gate_masks.py's
   `night_windows` for "01:00-05:00" in Africa/Casablanca, "00:00-06:00" in
   Australia/Adelaide and "22:00-04:00" in UTC, each over three days, the
   first two also over a clock change; or a malformed night is accepted;
6. `tree_window_at` differs from `windows.window_list(load_grid(...))`, which
   walks the grid with `run_slices`, at any instant of a half-hour grid over
   S1 and S5 and at the first and last sample of each listed window, or
   gives a window before the record, after it, or in S5's empty window; or
   `window_list` lists other than 4 windows for S1 and 2 for S5 (S5's empty
   second day left out), so that the comparison covers a first, a middle
   and a last window and a window the tree drops;
7. `RunsCache.get` or a call of `runs_of` opens a file (counted by wrapping
   `h5py.File`), a second `read` of an unchanged archive opens one, or
   either returns the kept runs after the archive's modification time
   changed;
8. `best_window` with `within` (the local's record) does not search inside
   it first: over 4 candidates in hours 0-11 and 2 in hours 12-23, within
   12-24 h it does not give 12-24 h while without `within` it gives 0-12 h
   (outside that record); inside the record it does not take the top count
   there (16-18 h, at 3 among 2s); a record from 13:31 to 23:59:59.999 does
   not give 14-24 h with the 60 s edge and 14-23 h with edge 0; a record
   over hours that count nothing (12-24 h over zeros, or 30-34 h past the
   last hour) does not fall back to 0-12 h; or any of three mutants run
   here (`within` ignored, no fall back, no edge) passes every one of these.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from mth5.mth5 import MTH5  # noqa: E402
from mth5.timeseries import ChannelTS, RunTS  # noqa: E402

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import intersite, stacks  # noqa: E402
from mt_workbench.gui import availability_model as am  # noqa: E402
from mt_workbench.gui.archive import load_grid  # noqa: E402
from mt_workbench.gui.windows import window_list  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRATCH = scratch_dir("availability_model_unit")
SURVEY = "SYNTH"
FS = 1.0
T0 = pd.Timestamp("2024-03-01T00:00:00", tz="UTC")
H = 3600
# site -> (channels, [(start hour, samples)])
SITES = {
    "S1": (("hx", "hy", "ex", "ey"), [(0, 30 * H), (31, 49 * H)]),
    "S2": (("hx", "hy"), [(2, 10 * H), (14, 40 * H)]),
    "S3": (("hx", "hy", "ex", "ey"), [(0, 72 * H)]),
    "S4": (("hx", "hy"), [(50, 10 * H)]),
    "S5": (("hx", "hy"), [(0, 24 * H), (48, 30000)]),
}
# the dc-level records written into S1's run comments, and the summary they make
S1_NOTES = {
    "sr1_0001": "dc level (median counts, rail %): hx +1.000e+05 0.00 ok, hy +2.000e+05 0.00 ok, "
                "ex +1.600e+09 0.00 open input?, ey +3.000e+07 0.00 ok",
    "sr1_0002": "dc level (median counts, rail %): hx +1.000e+05 5.00 saturated?, hy +2.000e+05 0.00 ok, "
                "ex +1.600e+09 0.00 open input?, ey +3.000e+07 0.00 ok",
}
S1_DC = {"hx": "saturated?", "hy": "ok", "ex": "open input?", "ey": "ok"}
OPENS: list[str] = []
_h5_init = h5py.File.__init__
failures: list[str] = []


def _counting_init(self, name, *args, **kwargs):
    if isinstance(name, (str, os.PathLike)):  # h5py also builds File objects from open ids
        OPENS.append(str(name))
    _h5_init(self, name, *args, **kwargs)


h5py.File.__init__ = _counting_init


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def ns(hours: float) -> int:
    """Return T0 plus `hours` as ns since the epoch."""
    return int(T0.value + round(hours * 3.6e12))


def write_site(workspace: Path, site: str, comps, runs) -> Path:
    """Write one site's archive at 1 Hz, as `ingest_site` lays it out.

    Args:
        workspace (Path): The archive is <workspace>/mth5/<site>.h5.
        site (str): Station name.
        comps (tuple): Channels, magnetic hx/hy and electric ex/ey.
        runs (list): (start hour after T0, samples) per run.

    Returns:
        Path: The archive.
    """
    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(len(site) + sum(map(ord, site)))
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        for i, (hour, n) in enumerate(runs, 1):
            run_id = f"sr1_{i:04d}"
            start = (T0 + pd.Timedelta(hours=hour)).tz_localize(None).isoformat()
            chans = []
            for c in comps:
                kind = "magnetic" if c.startswith("h") else "electric"
                chans.append(ChannelTS(channel_type=kind, data=rng.integers(-1000, 1000, n).astype("int32"),
                                       channel_metadata={kind: {"component": c, "sample_rate": FS,
                                                                "time_period.start": start}}))
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()
    return path


def write_survey(root: Path, name: str, extra: dict) -> Path:
    """Write a survey.yaml over the shared workspace; return its path."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)
    lines = [f"name: {SURVEY}", "instrument: lemi423", "sample_rate: 1",
             f"data_root: {(root / 'raw').as_posix()}", f"workspace: {(root / 'work').as_posix()}",
             "timezone: Africa/Casablanca", "sites:"]
    for site in list(SITES) + ["NA"] + list(extra):
        lines.append(f"  {site}:")
        lines.append("    latitude: 35.0")
        lines.append("    longitude: -3.0")
        for key, value in extra.get(site, {}).items():
            lines.append(f"    {key}: {value}")
    lines += ["  F10:", "    latitude: 35.0", "    longitude: -3.0", "    sample_rate: 10"]
    path = folder / "survey.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_fixture() -> tuple[Path, Path, dict]:
    """Write the archives and two surveys; return (survey A, survey B with G, archive paths)."""
    root = SCRATCH / "survey"
    if root.exists():
        shutil.rmtree(root)
    work = root / "work"
    paths = {site: write_site(work, site, comps, runs) for site, (comps, runs) in SITES.items()}
    with h5py.File(paths["S1"], "r+") as f:
        station = f[f"Experiment/Surveys/{SURVEY}/Stations/S1"]
        for run, note in S1_NOTES.items():
            station[run].attrs["comments"] = note
    (work / "mth5" / "G.h5").write_text("not an HDF5 file\n", encoding="utf-8")
    paths["G"] = work / "mth5" / "G.h5"
    yaml_a = write_survey(root, "a", {})
    yaml_b = write_survey(root, "b", {"G": {}})
    return yaml_a, yaml_b, paths


def written_runs(site: str) -> list[tuple[int, int]]:
    """Return the runs as written: (start, start + (n - 1) samples), ns."""
    return [(ns(hour), ns(hour) + int((n - 1) * 1e9 / FS)) for hour, n in SITES[site][1]]


def raises_oserror(fn) -> str:
    """Return the OSError text `fn()` raises, or "" when it raises none."""
    try:
        fn()
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


# ------------------------------------------------------------------ checks


def check_read_runs(paths) -> None:
    """Criterion 1."""
    got = am.read_runs(paths["S2"], "S2", SURVEY)
    want = written_runs("S2")
    check(got["all"] == want and got["H"] == want and got["E"] == [],
          f"1. S2 runs all {got['all']} H {got['H']} E {got['E']} (want {want} twice and [])")
    check(got["dc"] == {}, f"1. S2 has no dc record: dc {got['dc']}")
    s1 = am.read_runs(paths["S1"], "S1", SURVEY)
    check(s1["all"] == written_runs("S1") and s1["E"] == written_runs("S1"), "1. S1 runs under all and E")
    check(s1["dc"] == S1_DC, f"1. S1 dc {s1['dc']} (want {S1_DC})")
    text = raises_oserror(lambda: am.read_runs(paths["G"], "G", SURVEY))
    check(bool(text), f"1. G.h5 (text) raises OSError: {text or 'nothing raised'}")
    missing = raises_oserror(lambda: am.read_runs(paths["G"].with_name("NONE.h5"), "NONE", SURVEY))
    check(bool(missing), f"1. a missing archive raises OSError: {missing or 'nothing raised'}")


def check_cache(survey, paths) -> None:
    """Criterion 7."""
    cache = am.RunsCache()
    path = paths["S1"]
    lookup = cache.runs_of(survey)
    OPENS.clear()
    before = (cache.get(survey, "S1", path), lookup("S1", path, ("hx", "hy")))
    check(before == (None, None) and not OPENS, f"7. before a read: get/runs_of {before}, opens {OPENS}")
    OPENS.clear()
    kept = cache.read(survey, "S1", path)
    first = len(OPENS)
    OPENS.clear()
    again = cache.read(survey, "S1", path)
    check(first == 4 and not OPENS and again is kept,
          f"7. read opens the archive {first} times (want 4), a second read {len(OPENS)} (want 0)")
    OPENS.clear()
    answers = (cache.get(survey, "S1", path), lookup("S1", path, ()), lookup("S1", path, ("hx", "hy")),
               lookup("S1", path, ["ex", "ey"]))
    check(not OPENS and answers[0] is kept and answers[1] == kept["all"] and answers[2] == kept["H"]
          and answers[3] == kept["E"], f"7. get and runs_of answer from the cache, opens {OPENS}")
    status = path.stat()
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 2_000_000_000))
    OPENS.clear()
    stale = (cache.get(survey, "S1", path), lookup("S1", path, ("hx", "hy")))
    check(stale == (None, None) and not OPENS, f"7. after an mtime change: {stale}, opens {OPENS}")
    cache.read(survey, "S1", path)
    check(len(OPENS) == 4 and cache.get(survey, "S1", path) is not None,
          f"7. the changed archive is read again ({len(OPENS)} opens)")
    OPENS.clear()
    gone = cache.get(survey, "S1", path.with_name("NONE.h5"))
    check(gone is None and not OPENS, "7. a failed stat gives None and opens nothing")


def check_group_rows() -> None:
    """Criterion 3."""
    runs = {"R1": [(0, ns(10) - T0.value)], "R2": [(ns(5) - T0.value, ns(20) - T0.value)],
            "X": [(0, ns(4) - T0.value)],                              # R1 4 h, R2 0
            "Y": [(ns(6) - T0.value, ns(15) - T0.value)],              # R1 4 h, R2 9 h
            "Z": [(ns(5) - T0.value, ns(10) - T0.value)],              # 5 h each: a tie
            "W": [(ns(30) - T0.value, ns(31) - T0.value)],             # none
            "U": None}                                                 # not read
    sites = ["X", "R2", "Y", "R1", "Z", "W", "U", "Q"]
    runs["Q"] = [(ns(0) - T0.value, ns(1) - T0.value)]                 # R1 1 h
    of = runs.get
    got = am.group_rows(sites, of, ["R1", "R2", "NOT_A_SITE"])
    want = [("R1", ["R1", "Q", "X", "Z"]), ("R2", ["R2", "Y"]), ("", ["U", "W"])]
    check(got == want, f"3. references R1, R2: {got} (want {want})")
    got = am.group_rows(sites, of, ["R2", "R1"])
    want = [("R2", ["R2", "Y", "Z"]), ("R1", ["R1", "Q", "X"]), ("", ["U", "W"])]
    check(got == want, f"3. references R2, R1 (the tie goes to R2): {got} (want {want})")
    got = am.group_rows(sites, of, [])
    check(got == [("", sorted(sites))], f"3. no references: {got}")


def at(text: str) -> int:
    """Return 2024-03-01 <text> UTC as ns."""
    return int(pd.Timestamp(f"2024-03-01 {text}", tz="UTC").value)


def check_members_per_hour() -> None:
    """Criterion 4."""
    runs = {
        "a": {"H": [(at("10:00"), at("12:30"))]},
        "b": {"H": [(at("10:00"), at("11:59:30"))]},
        "c": {"H": [(at("10:00:30"), at("11:58:30"))]},
        "d": {"H": [(at("10:00"), at("10:30")), (at("10:30") + 1_000_000, at("12:00"))]},
        "e": {"H": [(at("10:00"), at("10:30")), (at("10:32"), at("12:00"))]},
        "f": {"H": [], "E": [(at("10:00"), at("13:00"))]},
        "g": {"H": [(at("10:00"), at("13:00"))]},
    }
    candidates = ["a", "b", "c", "d", "e", "f", "missing"]
    edges, counts = am.members_per_hour(runs, candidates, "H", at("10:20"), at("12:10"))
    want_edges = [at("10:00"), at("11:00"), at("12:00"), at("13:00")]
    # hour 10: a b c d; hour 11: a b d e; hour 12: none
    check(list(edges) == want_edges and list(counts) == [4, 4, 0],
          f"4. counts {list(counts)} over {[str(pd.Timestamp(e, tz='UTC').time()) for e in edges]} "
          f"(want [4, 4, 0] over 10-13)")
    _, counts0 = am.members_per_hour(runs, candidates, "H", at("10:20"), at("12:10"), edge_s=0.0)
    # edge 0: hour 10 a b (c starts 30 s late; d's 1 ms gap is no longer merged); hour 11 a d e (b ends
    # 30 s early)
    check(list(counts0) == [2, 3, 0], f"4. edge 0: {list(counts0)} (want [2, 3, 0])")
    _, counts_alone = am.members_per_hour(runs, candidates, "H", at("10:20"), at("12:10"), merge=False)
    # each run alone (a time recipe): d's first run (10:00-10:30) covers no hour whole, its second
    # (10:30:00.001-12:00) covers hour 11
    check(list(counts_alone) == [3, 4, 0], f"4. runs alone: {list(counts_alone)} (want [3, 4, 0])")
    _, counts_e = am.members_per_hour(runs, candidates, "E", at("10:00"), at("13:00"))
    check(list(counts_e) == [1, 1, 1], f"4. field E counts only f: {list(counts_e)}")
    edges = np.arange(7) * am.HOUR_NS
    check(am.best_window(edges, [1, 3, 3, 0, 3, 2]) == (int(edges[1]), int(edges[3])),
          "4. best_window takes the longest run at the top count")
    check(am.best_window(edges, [3, 0, 3, 3, 0, 3]) == (int(edges[2]), int(edges[4]))
          and am.best_window(edges, [3, 0, 3, 0, 0, 0]) == (int(edges[0]), int(edges[1])),
          "4. best_window: longest first, then earliest")
    check(am.best_window(edges, [0] * 6) is None and am.best_window(edges[:1], []) is None,
          "4. best_window is None with no count")


def local_window_cases(best) -> list[tuple[bool, str]]:
    """Return (passed, message) per case of criterion 8 for `best`, `best_window` or a mutant of it."""
    edges = np.array([ns(h) for h in range(25)], dtype=np.int64)  # the hours of 2024-03-01

    def hours(a: int, b: int) -> tuple[int, int]:
        return int(edges[a]), int(edges[b])

    def text(window) -> str:
        return "None" if window is None else "-".join(f"{(w - T0.value) / 3.6e12:g} h" for w in window)

    busy_first = [4] * 12 + [2] * 12
    record = hours(12, 24)
    cases = []
    got, plain = best(edges, busy_first, within=record), best(edges, busy_first)
    inside = got is not None and record[0] <= got[0] < got[1] <= record[1]
    cases.append((got == hours(12, 24) and inside, f"8. within the record 12-24 h: {text(got)} (want 12-24 h)"))
    outside = plain is not None and plain[1] <= record[0]
    cases.append((plain == hours(0, 12) and outside, f"8. without within: {text(plain)} (want 0-12 h, outside)"))
    got = best(edges, [4] * 12 + [2] * 4 + [3] * 2 + [2] * 6, within=record)
    cases.append((got == hours(16, 18), f"8. the top count inside the record: {text(got)} (want 16-18 h)"))
    ragged = (at("13:31"), int(edges[24]) - 1_000_000)  # a record from 13:31 to its last sample at 23:59:59.999
    got, got0 = best(edges, [1] * 24, within=ragged), best(edges, [1] * 24, within=ragged, edge_s=0.0)
    cases.append((got == hours(14, 24) and got0 == hours(14, 23),
                  f"8. record 13:31-23:59:59.999: {text(got)} with the 60 s edge (want 14-24 h), {text(got0)} with "
                  f"edge 0 (want 14-23 h)"))
    got = best(edges, [4] * 12 + [0] * 12, within=record)
    cases.append((got == hours(0, 12), f"8. no count inside the record: falls back to {text(got)} (want 0-12 h)"))
    got = best(edges, busy_first, within=(ns(30), ns(34)))
    cases.append((got == hours(0, 12), f"8. a record past the last hour: falls back to {text(got)} (want 0-12 h)"))
    got = best(edges, [0] * 24, within=record)
    cases.append((got is None, f"8. no count anywhere: {text(got)} (want None)"))
    return cases


def _ignore_within(edges, counts, within=None, edge_s=60.0):
    """Mutant of `best_window`: `within` ignored."""
    return am.best_window(edges, counts)


def _no_fall_back(edges, counts, within=None, edge_s=60.0):
    """Mutant of `best_window`: the hours inside `within` alone, None when none counts."""
    if within is None:
        return am.best_window(edges, counts)
    edges, edge_ns = np.asarray(edges), int(edge_s * 1e9)
    inside = (edges[:-1] >= within[0] - edge_ns) & (edges[1:] <= within[1] + edge_ns)
    return am.best_window(edges, np.where(inside, counts, 0))


def _no_edge(edges, counts, within=None, edge_s=60.0):
    """Mutant of `best_window`: no slack at the ends of `within`."""
    return am.best_window(edges, counts, within=within, edge_s=0.0)


def check_local_window() -> None:
    """Criterion 8, then its three mutants, each of which must fail a case."""
    for ok, msg in local_window_cases(am.best_window):
        check(ok, msg)
    for name, mutant in (("within ignored", _ignore_within), ("no fall back", _no_fall_back),
                         ("no edge", _no_edge)):
        failed = [msg for ok, msg in local_window_cases(mutant) if not ok]
        check(bool(failed), f"8. mutant '{name}' trips: {failed[0] if failed else 'every case passes'}")


def check_nights() -> None:
    """Criterion 5."""
    from gate_masks import night_windows

    cases = [("01:00-05:00", "Africa/Casablanca", "2023-12-10 13:17"),
             ("01:00-05:00", "Africa/Casablanca", "2024-03-08 12:00"),   # Ramadan: +01 to +00
             ("01:00-07:00", "Africa/Casablanca", "2024-04-12 18:00"),   # and back
             ("00:00-06:00", "Australia/Adelaide", "2024-04-05 07:00"),  # ACDT to ACST
             ("00:00-06:00", "Australia/Adelaide", "2024-10-04 07:00"),  # ACST to ACDT
             ("02:00-04:00", "Australia/Adelaide", "2024-10-04 07:00"),  # 02:00 does not exist on 6 Oct
             ("02:30-05:00", "Australia/Adelaide", "2024-04-05 07:00"),  # 02:30 happens twice on 7 Apr
             ("22:00-04:00", "UTC", "2024-03-01 00:00")]
    for night, tz, start in cases:
        lo = pd.Timestamp(start, tz="UTC")
        hi = lo + pd.Timedelta(days=3)
        want = [(a.value, b.value) for a, b in night_windows(lo, hi, night, tz)]
        got = am.night_spans(lo.value, hi.value, night, tz)
        check(got == want and len(got) >= 3, f"5. {night} {tz} from {start}: {len(got)} nights, "
                                              f"{'equal' if got == want else f'{got} vs {want}'}")
    for bad in ("1-5", "25:00-05:00", "01:00-01:00", "01:00/05:00", ""):
        try:
            am.parse_night(bad)
            check(False, f"5. night {bad!r} accepted")
        except ValueError:
            check(True, f"5. night {bad!r} refused")


def check_tree_windows(paths) -> None:
    """Criterion 6."""
    # S1: 80 h of grid, so windows from 0, 24, 48 and 72 h; S5: 0-24 h, an empty 24-48 h left out, 48 h on
    for site, count in (("S1", 4), ("S5", 2)):
        runs = am.read_runs(paths[site], site, SURVEY)["all"]
        listed = window_list(load_grid(paths[site], SURVEY, site))
        listed = [(pd.Timestamp(a).tz_convert("UTC") if pd.Timestamp(a).tzinfo else pd.Timestamp(a, tz="UTC"),
                   pd.Timestamp(b).tz_convert("UTC") if pd.Timestamp(b).tzinfo else pd.Timestamp(b, tz="UTC"))
                  for a, b in listed]

        def holding(t: int):
            return next(((a, b) for a, b in listed if a.value <= t < b.value), None)

        bad = []
        grid = range(runs[0][0] - 2 * H * 10**9, runs[-1][1] + 2 * H * 10**9, 1800 * 10**9)
        probes = list(grid) + [a.value for a, _ in listed] + [b.value - 10**9 for _, b in listed]
        for t in probes:
            got, want = am.tree_window_at(runs, FS, t), holding(t)
            if got != want:
                bad.append((pd.Timestamp(t, tz="UTC"), got, want))
        check(not bad and len(listed) == count,
              f"6. {site}: {len(listed)} tree windows (want {count}), {len(probes)} instants, "
              f"{'all equal' if not bad else f'{len(bad)} differ, first {bad[0]}'}")
    s5 = am.read_runs(paths["S5"], "S5", SURVEY)["all"]
    check(am.tree_window_at(s5, FS, ns(30)) is None, "6. S5's empty second window gives None")
    check(am.tree_window_at(s5, FS, ns(-1)) is None and am.tree_window_at(s5, FS, ns(60)) is None,
          "6. before and after the record gives None")



def outcome(members, left_out) -> dict:
    """Return {site: ("member", overlap) or ("out", reason)}."""
    out = {m["site"]: ("member", m["overlap_h"]) for m in members}
    out.update({d["site"]: ("out", d["reason"]) for d in left_out})
    return out


def check_rows(yaml_a: Path, yaml_b: Path, paths) -> None:
    """Criterion 2."""
    survey = Survey.from_yaml(yaml_a)
    window = {"start": "2024-03-01 00:00", "end": "2024-03-03 00:00"}
    rule = stacks.Recipe.from_mapping("STK_RULE", {"field": "H", "use": "reference", "method": "band_mean",
                                                   "sample_rate": 1, "members": "rule", **window})
    listed = stacks.Recipe.from_mapping("STK_LIST", {"field": "H", "use": "remote", "method": "time_mean",
                                                     "sample_rate": 1, "members": ["S1", "S3", "S4", "NOPE"],
                                                     "start": "2024-03-01 02:00", "end": "2024-03-01 12:00"})
    excluded = stacks.Recipe.from_mapping("STK_EXCL", {"field": "E", "use": "base", "method": "band_median",
                                                       "sample_rate": 1, "members": "rule", "exclude": ["S3"],
                                                       **window})
    cases = [("rule", rule, None), ("list", listed, None), ("local S2", rule, "S2"), ("exclude", excluded, None)]
    sites = survey.site_names()
    rates = {s: survey.sample_rate_of(s) for s in sites}
    cache = am.RunsCache()
    lookup = cache.runs_of(survey)
    for label, recipe, local in cases:
        default = outcome(*stacks.resolve_members(recipe, survey, local=local))
        early = {s for s, (kind, why) in default.items()
                 if kind == "member" or str(why).startswith("its runs with")}
        OPENS.clear()
        before = outcome(*stacks.resolve_members(recipe, survey, local=local, runs_of=lookup))
        unread = [s for s in early if before.get(s) != ("out", intersite.NOT_READ)]
        check(not unread and not OPENS, f"2. {label}: before any read, sites judged on runs read NOT_READ "
                                        f"(not: {unread}), opens {len(OPENS)}")
    for site, path in paths.items():
        if site != "G":
            cache.read(survey, site, path)
    for label, recipe, local in cases:
        default = outcome(*stacks.resolve_members(recipe, survey, local=local))
        members, left_out = stacks.resolve_members(recipe, survey, local=local, runs_of=lookup)
        rows = am.build_rows(sites, rates, {s: cache.get(survey, s, paths.get(s)) for s in sites},
                             members, left_out, {}, ["S3"], {})
        got = {r.site: ("member", r.overlap_h) if r.member else ("out", r.reason) for r in rows}
        diff = {s: (got.get(s), default.get(s)) for s in set(got) | set(default)
                if got.get(s) != default.get(s) and s in sites}
        check(not diff and len(rows) == len(sites), f"2. {label}: rows = default reads "
                                                     f"({sum(r.member for r in rows)} members; diff {diff})")
    # the masks column: a list on S1's row, an entry's error text on S2's (Nador P3S6, issue 22), nothing elsewhere
    mask = {"start": "2024-03-01T02:00:00Z", "end": "2024-03-01T03:00:00Z", "bands": "all", "channels": "all"}
    # the chart's text for Nador P3S6 (workbench issue 22)
    error = ("masks.yaml entry unreadable: mask found_by must be one of ('time', 'polar', 'cluster', 'night', "
             "'gate'), not 'dive'")
    rows = am.build_rows(sites, rates, {s: cache.get(survey, s, paths.get(s)) for s in sites}, members, left_out,
                         {}, ["S3"], {"S1": [mask], "S2": error})
    by_site = {r.site: r for r in rows}
    check(by_site["S1"].masks == [mask] and by_site["S1"].masks_error is None,
          f"2. S1's row holds its one mask and no error: {by_site['S1'].masks}, {by_site['S1'].masks_error!r}")
    check(by_site["S2"].masks_error == error and by_site["S2"].masks is None,
          f"2. S2's row holds the masks error text and no list: {by_site['S2'].masks_error!r}, {by_site['S2'].masks}")
    others = [r.site for r in rows if r.site not in ("S1", "S2") and (r.masks is not None or r.masks_error)]
    check(not others, f"2. no other row holds masks or a masks error: {others}")
    survey_b = Survey.from_yaml(yaml_b)
    unread = {"G": raises_oserror(lambda: cache.read(survey_b, "G", paths["G"]))}
    members, left_out = stacks.resolve_members(rule, survey_b, runs_of=cache.runs_of(survey_b))
    rows = am.build_rows(survey_b.site_names(), {s: survey_b.sample_rate_of(s) for s in survey_b.site_names()},
                         {}, members, left_out, unread, [], {})
    g = next(r for r in rows if r.site == "G")
    # the wording is spelled out here, not taken from the module, so a changed constant fails
    check(bool(unread["G"]) and g.reason == "archive unreadable: " + unread["G"] and g.unread == unread["G"],
          f"2. G (text) reads {g.reason!r}")


def main() -> None:
    """Run the checks and exit 1 when any failed."""
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print(__doc__.split("**This test fails if**")[1].strip() + "\n")
    yaml_a, yaml_b, paths = build_fixture()
    survey = Survey.from_yaml(yaml_a)
    check_read_runs(paths)
    check_cache(survey, paths)
    check_group_rows()
    check_members_per_hour()
    check_local_window()
    check_nights()
    check_tree_windows(paths)
    check_rows(yaml_a, yaml_b, paths)
    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("PASS  availability_model_unit")


if __name__ == "__main__":
    main()
