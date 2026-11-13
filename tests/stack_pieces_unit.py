# -*- coding: utf-8 -*-
"""
Unit test for the piece-wise stack (`mt_workbench.virtual.build_synthetic_remote(min_piece_h=...)`,
`stack_pieces`, scripts/build_stack.py --min-piece-h)

Three synthetic members at 10 Hz are written as real MTH5 archives (the
layout of tests/virtual_unit.py) in a scratch workspace with a survey.yaml.
Each member's hx and hy are slices of its own continuous series G_m(t) (a
common field plus the member's noise, offset and gain) on one 0.1 s grid
from T0, so the stack expected at any instant is the mean of the three
series there, whichever runs hold it. Runs, in hours from T0:

- A: one run, 0 to 10;
- B: 0 to 4, then 4.5 to 10 (a 30 min gap);
- C: 0 to 6, a restart stub 6.1 to 6.4, then 6.5 to 10.

Over the window 0.5 to 9.5 h the stretches with every member inside a run
are 0.5-4 (3.5 h), 4.5-6 (1.5 h), 6.1-6.4 (0.3 h) and 6.5-9.5 (3.0 h); one
run per member (B's 4.5-10, C's 0-6) shares only 4.5-6 (1.5 h).

Usage:
    python tests/stack_pieces_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. `stack_pieces` does not give exactly those four pieces, each with the
   member runs that hold it (B's first run in the first piece, its second
   in the other three; C's stub in the third);
2. the build with min_piece_h 1.0 does not write three runs, sr10_0001 to
   sr10_0003, starting at 0.5, 4.5 and 6.5 h and holding 126,000, 54,000
   and 108,000 samples (the 0.3 h stub left out), or any of their hx/hy float32
   samples differs from the float32 of the float64 mean of the three
   members' series at the same instants;
3. `pieces_out` does not list the three kept pieces and the 0.3 h one left
   out, in time order, or the station comment does not say "built per
   piece: 3 run(s)" and "1 piece(s) under 1 h left out (0.30 h)", or a run
   comment does not name its piece and its members' runs;
4. the default build (no min_piece_h) is not the one-run stack: one run
   sr10_0001 from 4.5 h of 54,000 samples with the same mean's samples
   (a campaign stack built whole);
5. the control: with every member's samples delayed by one sample inside
   each read (`_Coil` shifted, its first sample repeated), check 2's
   comparison does not fail;
6. the coherence-weighted piece-wise build does not return one weight
   column per whole 600 s chunk of every kept piece (21 + 9 + 18 = 48), or
   its runs' comments lack the weights rule;
7. min_piece_h 4.0, longer than every piece, does not raise a ValueError
   saying the members do not share 4 h of data;
8. scripts/build_stack.py with --min-piece-h 1 does not exit 0, print the
   three kept pieces and the one left out and write the same samples as
   check 2; with --recipe or --check beside --min-piece-h it does not exit 2.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from mth5.timeseries import ChannelTS, RunTS

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import mt_workbench.virtual as virtual  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

FS = 10.0
T0 = pd.Timestamp("2016-08-01T00:00:00", tz="UTC")
HOURS = 10.0
N = int(HOURS * 3600 * FS)
SURVEY = "pieces"
RUNS_H = {"A": [(0.0, 10.0)], "B": [(0.0, 4.0), (4.5, 10.0)], "C": [(0.0, 6.0), (6.1, 6.4), (6.5, 10.0)]}
WINDOW_H = (0.5, 9.5)
PIECES_H = [(0.5, 4.0, {"A": 1, "B": 1, "C": 1}), (4.5, 6.0, {"A": 1, "B": 2, "C": 1}),
            (6.1, 6.4, {"A": 1, "B": 2, "C": 2}), (6.5, 9.5, {"A": 1, "B": 2, "C": 3})]
SCRIPT = REPO / "scripts" / "build_stack.py"

failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def k_of(hours: float) -> int:
    """Return the sample index of an instant in hours from T0."""
    return int(round(hours * 3600 * FS))


def series(seed: int = 5) -> dict[str, dict[str, np.ndarray]]:
    """Return each member's continuous hx and hy series over the whole 10 h, in counts."""
    rng = np.random.default_rng(seed)
    field = {c: 1000.0 * rng.standard_normal(N) for c in ("hx", "hy")}
    out = {}
    for i, m in enumerate(RUNS_H):
        out[m] = {c: np.rint(1e6 * (i + 1) + (0.9 + 0.1 * i) * field[c] + 200.0 * rng.standard_normal(N))
                  for c in ("hx", "hy")}
    return out


def write_archive(workspace: Path, site: str, g: dict) -> None:
    """Write a member's runs (slices of its series) as an `ingest_site`-like archive."""
    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        for i, (a, b) in enumerate(RUNS_H[site], 1):
            run_id = f"sr10_{i:04d}"
            start = T0 + pd.Timedelta(hours=a)
            chans = [ChannelTS(channel_type="magnetic", data=g[c][k_of(a):k_of(b)].astype("int32"),
                               channel_metadata={"magnetic": {"component": c, "sample_rate": FS,
                                                              "time_period.start": start.isoformat()}})
                     for c in ("hx", "hy")]
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()


def make_survey(root: Path, g: dict) -> Path:
    """Write survey.yaml and the members' archives; return the yaml path."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)
    text = (f"name: {SURVEY}\ninstrument: edl\nsample_rate: 10\ndata_root: {(root / 'raw').as_posix()}\n"
            f"workspace: {(root / 'ws').as_posix()}\nsites:\n")
    for k, s in enumerate(RUNS_H):
        text += f"  {s}:\n    latitude: -42.0\n    longitude: {147.0 + 0.1 * k}\n"
    path = root / "survey.yaml"
    path.write_text(text, encoding="utf-8")
    for s in RUNS_H:
        write_archive(root / "ws", s, g[s])
    return path


def read_runs(path: Path, name: str) -> dict:
    """Read every run of a stack archive: {run: {"start", "hx", "hy", "comment"}} and the station comment."""
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(name, survey=SURVEY)
        out = {"_station": str(getattr(st.metadata.comments, "value", st.metadata.comments))}
        for run_id in st.groups_list:
            if not run_id.startswith("sr"):
                continue
            run = st.get_run(run_id)
            ch = run.get_channel("hx")
            out[run_id] = {"start": pd.Timestamp(str(ch.metadata.time_period.start)),
                           "comment": str(getattr(run.metadata.comments, "value", run.metadata.comments)),
                           "hx": ch.hdf5_dataset[:], "hy": run.get_channel("hy").hdf5_dataset[:]}
    finally:
        m.close_mth5()
    return out


def mean_at(g: dict, a: int, n: int, comp: str) -> np.ndarray:
    """Return the float32 of the float64 mean of the members' series over samples a..a+n, in member order."""
    acc = np.zeros(n, dtype="float64")
    for m in sorted(g):
        acc += g[m][comp][a:a + n].astype("float64")
    return (acc / len(g)).astype("float32")


def runs_match(got: dict, g: dict, want: list[tuple[float, int]]) -> tuple[bool, str]:
    """Compare a stack's runs with the expected (start h, samples) list and the members' mean."""
    ids = sorted(k for k in got if not k.startswith("_"))
    if ids != [f"sr10_{i:04d}" for i in range(1, len(want) + 1)]:
        return False, f"runs {ids}"
    for rid, (a_h, n) in zip(ids, want):
        r = got[rid]
        if r["start"] != T0 + pd.Timedelta(hours=a_h) or r["hx"].size != n:
            return False, f"{rid} starts {r['start']} with {r['hx'].size} samples, not {a_h} h and {n}"
        for c in ("hx", "hy"):
            if r[c].tobytes() != mean_at(g, k_of(a_h), n, c).tobytes():
                d = np.abs(r[c].astype("float64") - mean_at(g, k_of(a_h), n, c)).max()
                return False, f"{rid} {c} differs from the members' mean (max {d:.3g} counts)"
    return True, ", ".join(f"{rid} {got[rid]['start']:%H:%M} {got[rid]['hx'].size}" for rid in ids)


def main() -> int:
    """Run the checks; return 1 when any failed."""
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    g = series()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        yaml_path = make_survey(root, g)
        survey = Survey.from_yaml(yaml_path)
        lo, hi = (T0 + pd.Timedelta(hours=h) for h in WINDOW_H)
        start, end = lo.strftime("%Y-%m-%d %H:%M:%S"), hi.strftime("%Y-%m-%d %H:%M:%S")

        # 1. the pieces
        member_runs = {m: [dict(run=f"sr10_{i:04d}", start=(T0 + pd.Timedelta(hours=a)).value,
                                n=k_of(b) - k_of(a), fs=FS) for i, (a, b) in enumerate(r, 1)]
                       for m, r in RUNS_H.items()}
        got = virtual.stack_pieces(member_runs, lo.value, hi.value)
        want = [((T0 + pd.Timedelta(hours=a)).value, (T0 + pd.Timedelta(hours=b)).value,
                 {m: f"sr10_{i:04d}" for m, i in runs.items()}) for a, b, runs in PIECES_H]
        have = [(int(a), int(round(b)), {m: r["run"] for m, r in ch.items()}) for a, b, ch in got]
        check(have == want, f"1. stack_pieces: {len(have)} pieces " + "; ".join(
            f"{(a - T0.value) / 3.6e12:.1f}-{(b - T0.value) / 3.6e12:.1f} h {sorted(r.items())}" for a, b, r in have))

        # 2-3. the piece-wise build
        pieces: list = []
        out = virtual.build_synthetic_remote(survey, list(RUNS_H), start, end, name="STK_P",
                                             out_path=root / "STK_P.h5", min_piece_h=1.0, pieces_out=pieces)
        runs = read_runs(out, "STK_P")
        kept_want = [(0.5, 126000), (4.5, 54000), (6.5, 108000)]
        ok, text = runs_match(runs, g, kept_want)
        check(ok, f"2. per piece: {text}")
        kept = [p for p in pieces if p["kept"]]
        left = [p for p in pieces if not p["kept"]]
        check(len(pieces) == 4 and [round(p["hours"], 2) for p in pieces] == [3.5, 1.5, 0.3, 3.0]
              and len(kept) == 3 and len(left) == 1 and left[0]["runs"] is None
              and kept[1]["runs"] == {"A": "sr10_0001", "B": "sr10_0002", "C": "sr10_0001"},
              f"3. pieces_out: {[(round(p['hours'], 2), p['kept']) for p in pieces]}")
        sc = runs["_station"]
        check("built per piece: 3 run(s)" in sc and "1 piece(s) under 1 h left out (0.30 h)" in sc,
              f"3. station comment: ...{sc[sc.find('; built'):]}")
        rc = runs.get("sr10_0002", {}).get("comment", "")
        check(rc.startswith("piece 2 of 3, 2016-08-01T04:30:00") and "A sr10_0001, B sr10_0002, C sr10_0001" in rc,
              f"3. run comment: {rc}")

        # 4. the default build: one run per member
        out1 = virtual.build_synthetic_remote(survey, list(RUNS_H), start, end, name="STK_1",
                                              out_path=root / "STK_1.h5")
        ok1, text1 = runs_match(read_runs(out1, "STK_1"), g, [(4.5, 54000)])
        check(ok1, f"4. default (one run per member): {text1}")

        # 5. the control: every member delayed by one sample
        real = virtual._Coil

        class Late(real):
            def __getitem__(self, sl):
                x = real.__getitem__(self, sl)
                return np.concatenate([x[:1], x[:-1]])

        virtual._Coil = Late
        try:
            out5 = virtual.build_synthetic_remote(survey, list(RUNS_H), start, end, name="STK_L",
                                                  out_path=root / "STK_L.h5", min_piece_h=1.0)
            ok5, text5 = runs_match(read_runs(out5, "STK_L"), g, kept_want)
        finally:
            virtual._Coil = real
        check(not ok5, f"5. control, delayed one sample: the comparison fails ({text5})")

        # 6. coherence weighting per piece
        weights: dict = {}
        out6 = virtual.build_synthetic_remote(survey, list(RUNS_H), start, end, name="STK_W",
                                              out_path=root / "STK_W.h5", weighting="coherence", min_piece_h=1.0,
                                              weights_out=weights)
        runs6 = read_runs(out6, "STK_W")
        n_chunks = weights["hx"]["weights"].shape[1] if weights else -1
        check(n_chunks == 21 + 9 + 18 and all("weighting=coherence" in runs6[r]["comment"]
                                             for r in runs6 if not r.startswith("_")),
              f"6. coherence per piece: {n_chunks} weight columns over the three pieces")

        # 7. no piece long enough
        try:
            virtual.build_synthetic_remote(survey, list(RUNS_H), start, end, name="STK_X",
                                           out_path=root / "STK_X.h5", min_piece_h=4.0)
            msg = ""
        except ValueError as exc:
            msg = str(exc)
        check("members do not share 4 h of data" in msg, f"7. min_piece_h 4: {msg or 'no error'}")

        # 8. the command line
        run = subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "STK_CLI", start, end, "A", "B", "C",
                              "--min-piece-h", "1"], capture_output=True, text=True, cwd=REPO)
        lines = [ln for ln in run.stdout.splitlines() if ln.startswith("piece")]
        cli = survey.workspace / "mth5" / "STK_CLI.h5"
        ok8, text8 = runs_match(read_runs(cli, "STK_CLI"), g, kept_want) if cli.exists() else (False, "no archive")
        check(run.returncode == 0 and len(lines) == 5 and "left out: under 1 h" in lines[2]
              and lines[-1].startswith("pieces: 3 kept, 8.00 h; 1 left out, 0.30 h") and ok8,
              f"8. build_stack.py --min-piece-h 1: exit {run.returncode}, {lines}, {text8}"
              + ("" if run.returncode == 0 else f"\n{run.stderr[-800:]}"))
        codes = []
        for extra in (["--recipe", "R"], ["--check"]):
            args = ([str(yaml_path), "--min-piece-h", "1", *extra] if extra[0] == "--recipe"
                    else [str(yaml_path), "STK_C", start, end, "A", "B", "C", "--min-piece-h", "1", *extra])
            r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO)
            codes.append((r.returncode, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""))
        check(all(c == 2 for c, _ in codes), f"8. refused beside --recipe and --check: {codes}")

    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
