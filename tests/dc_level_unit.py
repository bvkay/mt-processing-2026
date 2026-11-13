# -*- coding: utf-8 -*-
"""
Unit test for scripts/dc_level_check.py

Two sites are written with mth5 as MTH5 0.2.0 archives of int32 counts at
1000 Hz, the layout of the raw archives. S01 holds ex ey hx hy at the
levels of line C's healthy channels (+5e7, -3e7, +4.3e7, +3.9e7 counts)
with Gaussian noise of 2e6 counts and a 50 Hz sine of 1e6, in a 120 s run
sr1000_0001, and a 10 s run sr100_0002 at 100 Hz. S02 holds two 120 s runs:
ex (+2e7) and hy (+3.7e7) as healthy as S01's, ey at 1.6e9 counts with
Gaussian noise of 1e3 (MAD about 670 counts), the level of C05 ey and C13
ey, and hx (+4.1e7, noise 5e6) clipped at its own 95th percentile, so 5 %
of its samples sit at the rail. survey.yaml also declares S03 (no archive),
S01L (derived_from S01, with a 1 Hz archive whose ey sits at 1.6e9) and OBS
(instrument intermagnet). The script's main runs in-process on that
survey.

Usage:
    python tests/dc_level_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if a channel at 1.6e9 counts is not flagged as an open
input or a healthy channel is. In detail, it fails if: S02 ey of either run
is not "open input?", with a median within 1e4 counts of 1.6e9 and a MAD
below 2e3; any channel of S01, S02 ex or S02 hy is not "ok"; S02 hx is not
"saturated?" with 5 % to 8 % of its samples at the rail; S02 ey is not
flagged by the threshold alone (--ratio 1e6) or by the ratio alone
(--threshold-counts 1e12), with a ratio within 1 % of 40 (1.6e9 over the
median of the written electric levels |+5e7|, |-3e7|, |+2e7| twice and
1.6e9 twice, 4e7), or is flagged with both off; a subsample holds more than
--sample-seconds of samples or its step is not ceil(n / (S fs)); the table
is not ordered open input?, saturated?, ok and then by site; the summary
line does not name S02 ey as an open input in both runs and S02 hx as
saturated; S01L and OBS are checked instead of skipped with a note, S03 is
not listed as having no archive, or sr100_0002 is checked at 1000 Hz; the
exit status is not 0 for the report, 2 for S03 named and 2 for a missing
survey file; or the CSV does not hold the table's rows.

The mutation: with the rail share (`mt_workbench.dclevel.rail_fraction`, which
the script's measure calls) taken as the literal share of samples whose
|counts| are at least 90 % of the largest |counts|, the healthy
channels, whose DC level is many times their noise, come back "saturated?";
the test checks that it does, so the healthy criterion is shown able to
fail.

The Phoenix input rail (upstream issue 78). It also fails if, on two
synthetic 150 Hz records in volts of 2 h each (a drifting E whose median
climbs 30 mV over the first 80 % of the run and holds at 46 mV, with
0.1 mV noise, as the S1 runs the ingest flagged; and an E of 0.2 V
noise with 3 % of its samples
at +-2.4 V, beyond the rail of 0.9 x 2.5 V), the record's own rail
(`channel_stats` without `rail`)
does not flag both "saturated?", or the absolute rail of 2.25 V
(`rail=2.25`) flags the drifting one or does not flag the railed one with
3 % at the rail; or the flag line of the railed one does not name the
rail ("at the input rail (|x| >= 2.25 V)"), the relative line names one,
or `level_note` and `parse_level_note` do not give back the rail of each
channel and the same flag line; or a ";"-piece of the `level_note`
record with rails has a dot in its key (before its first ":"; the EMTF
XML writer takes the key as an attribute path, upstream issue 82), or
`parse_level_note` does not read the rails back from the dotted key that
Phoenix archives built from commit 4beb3cd carry
(`RAIL_PREFIX_DOTTED`). The mutations: `channel_stats` ignoring `rail`
must flag the drifting record again, and `RAIL_PREFIX` set to the dotted
key must trip the key check.

The input rail read back by the script. It also fails if, on
a 150 Hz site P01 written with mth5 in volts whose run sr150_0001 holds
the two records above under a run comment with the ingest's "dc rail"
line (ex 2.25, ey 2.25), whose run sr150_0002 holds the same records
under a comment without it (the control, a LEMI or EDL run or a Phoenix
archive built before) and whose run sr150_0003 holds them under the
dotted "dc rail" line of 4beb3cd archives, `comment_rails` does not give {ex: 2.25,
ey: 2.25} for the first and third runs and nothing for the second; or
the script's report does not give the drifting ex of sr150_0001 and
sr150_0003 "ok" with 0 % at the input rail and their railed ey
"saturated?" with 2.7 % to 3.3 %, all with the rail 2.25 in the CSV, does
not give the control's ex and ey "saturated?" at the record's own rail
with no rail in the CSV, or does not count 4 of 6 channel runs at the
input rail in the line above the table. The
mutation: `comment_rails` reading no rail must flag sr150_0001 ex
"saturated?" again.
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import dclevel  # noqa: E402

SCRIPT = REPO / "scripts" / "dc_level_check.py"
SCRATCH = scratch_dir("dc_level_unit")
SURVEY = "dc_level_unit"
FS = 1000.0
RUN_S = 120
SAMPLE_S = 20.0
T0 = pd.Timestamp("2023-09-25T15:00:00+00:00")
OPEN_LEVEL = 1.6e9
# {site: {run: (rate, {channel: (DC level, Gaussian noise sigma, 50 Hz amplitude, clip share)})}}
HEALTHY_E = {"ex": (5.0e7, 2.0e6, 1.0e6, 0.0), "ey": (-3.0e7, 2.0e6, 1.0e6, 0.0)}
HEALTHY_H = {"hx": (4.3e7, 2.0e6, 1.0e6, 0.0), "hy": (3.9e7, 2.0e6, 1.0e6, 0.0)}
S02_CHANNELS = {"ex": (2.0e7, 2.0e6, 1.0e6, 0.0), "ey": (OPEN_LEVEL, 1.0e3, 0.0, 0.0),
                "hx": (4.1e7, 5.0e6, 0.0, 0.05), "hy": (3.7e7, 2.0e6, 1.0e6, 0.0)}
ARCHIVES = {
    "S01": {"sr1000_0001": (FS, RUN_S, {**HEALTHY_E, **HEALTHY_H}),
            "sr100_0002": (100.0, 10, {**HEALTHY_E, **HEALTHY_H})},
    "S02": {"sr1000_0001": (FS, RUN_S, S02_CHANNELS), "sr1000_0002": (FS, RUN_S, S02_CHANNELS)},
    "S01L": {"sr1_0001": (1.0, 600, {"ex": (5.0e7, 2.0e6, 0.0, 0.0), "ey": (OPEN_LEVEL, 1.0e3, 0.0, 0.0)})},
}
HEALTHY = [("S01", "ex"), ("S01", "ey"), ("S01", "hx"), ("S01", "hy"), ("S02", "ex"), ("S02", "hy")]
EXPECTED_RATIO = OPEN_LEVEL / float(np.median([5e7, 3e7, 2e7, 2e7, OPEN_LEVEL, OPEN_LEVEL]))  # 40

SURVEY_YAML = """name: {name}
instrument: lemi423
sample_rate: 1000
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  S01:
    latitude: 31.6
    longitude: -5.6
  S02:
    latitude: 31.7
    longitude: -5.6
  S03:
    latitude: 31.8
    longitude: -5.6
  S01L:
    derived_from: S01
    sample_rate: 1.0
  OBS:
    instrument: intermagnet
    channels: [hx, hy, hz]
"""


def channel_samples(rng: np.random.Generator, n: int, fs: float, spec: tuple) -> np.ndarray:
    """Return a channel's int32 counts: DC level, Gaussian noise, a 50 Hz sine, clipped at a rail when asked."""
    level, sigma, amp50, clip = spec
    t = np.arange(n) / fs
    x = level + sigma * rng.standard_normal(n) + amp50 * np.sin(2 * np.pi * 50.0 * t)
    if clip:
        x = np.minimum(x, np.quantile(x, 1.0 - clip))
    return np.round(x).astype("int32")


def write_archive(path: Path, site: str, runs: dict, rng: np.random.Generator) -> None:
    """Write one site's MTH5 0.2.0 archive of int32 counts, runs back to back from T0."""
    from mth5.mth5 import MTH5

    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        station.write_metadata()
        start = T0
        for run_id, (fs, seconds, channels) in runs.items():
            n = int(seconds * fs)
            end = start + pd.Timedelta(seconds=(n - 1) / fs)
            run = station.add_run(run_id)
            for comp, spec in channels.items():
                kind = "electric" if comp.startswith("e") else "magnetic"
                ch = run.add_channel(comp, kind, channel_samples(rng, n, fs, spec))
                ch.metadata.component = comp
                ch.metadata.sample_rate = fs
                ch.metadata.time_period.start = str(start)
                ch.metadata.time_period.end = str(end)
                ch.metadata.units = "digital counts"
                ch.write_metadata()
            run.metadata.sample_rate = fs
            run.metadata.time_period.start = str(start)
            run.metadata.time_period.end = str(end)
            run.write_metadata()
            start = end + pd.Timedelta(seconds=60)
    finally:
        m.close_mth5()


def build() -> Path:
    """Write the archives and survey.yaml; return the survey.yaml path."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    root, work = SCRATCH / "raw", SCRATCH / "work"
    root.mkdir(parents=True)
    rng = np.random.default_rng(20260925)
    for site, runs in ARCHIVES.items():
        write_archive(work / "mth5" / f"{site}.h5", site, runs, rng)
    yaml_path = SCRATCH / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(name=SURVEY, root=root.as_posix(), work=work.as_posix()),
                         encoding="utf-8")
    return yaml_path


def load_script():
    """Import scripts/dc_level_check.py as a module."""
    spec = importlib.util.spec_from_file_location("dc_level_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, *argv: str) -> tuple[int, str, str]:
    """Run the script's main in-process; return (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = module.main([str(a) for a in argv])
    return status, out.getvalue(), err.getvalue()


def read_csv(path: Path) -> dict[tuple[str, str, str], dict]:
    """Read the script's CSV: {(site, run, channel): row}."""
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["site"], r["run"], r["channel"]): r for r in csv.DictReader(f)}


def table_rows(stdout: str) -> list[list[str]]:
    """Return the table's rows from the report, split on whitespace (the verdict kept whole)."""
    lines = stdout.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("site "))
    rows = []
    for ln in lines[first + 2:]:
        if not ln.strip():
            break
        head, verdict = ln.rsplit("  ", 1)
        rows.append(head.split() + [verdict.strip()])
    return rows


def main() -> None:
    yaml_path = build()
    module = load_script()
    out_csv = SCRATCH / "dc_level.csv"

    status, stdout, stderr = run_main(module, yaml_path, "--sample-seconds", SAMPLE_S, "--csv", out_csv)
    assert status == 0, f"exit {status}\n{stdout}\n{stderr}"
    print("\n".join("  " + ln for ln in stdout.splitlines()))
    rows = read_csv(out_csv)

    # the verdicts
    for run in ("sr1000_0001", "sr1000_0002"):
        ey = rows[("S02", run, "ey")]
        assert ey["verdict"] == "open input?", ey
        assert abs(float(ey["median_counts"]) - OPEN_LEVEL) < 1e4 and float(ey["mad_counts"]) < 2e3, ey
        hx = rows[("S02", run, "hx")]
        assert hx["verdict"] == "saturated?" and 0.05 <= float(hx["rail_fraction"]) <= 0.08, hx
    healthy = [r for (site, _run, comp), r in rows.items() if (site, comp) in HEALTHY]
    assert len(healthy) == 8, sorted(rows)
    bad = [(r["site"], r["run"], r["channel"], r["verdict"]) for r in healthy if r["verdict"] != "ok"]
    assert not bad, f"healthy channels flagged: {bad}"
    rails = [100 * float(rows[("S02", run, "hx")]["rail_fraction"]) for run in ("sr1000_0001", "sr1000_0002")]
    print(f"  S02 ey open input? in both runs; S02 hx saturated? ({rails[0]:.2f} %, {rails[1]:.2f} % at the "
          f"rail); {len(healthy)} healthy channel runs ok")

    # the ratio against the written levels
    ratio = float(rows[("S02", "sr1000_0001", "ey")]["ratio"])
    assert abs(ratio / EXPECTED_RATIO - 1.0) < 0.01, (ratio, EXPECTED_RATIO)

    # the subsample
    for (site, run, comp), r in rows.items():
        n, step, n_read = int(r["n_samples"]), int(r["step"]), int(r["n_read"])
        assert step == math.ceil(n / (SAMPLE_S * FS)) and n_read == math.ceil(n / step), r
        assert n_read <= SAMPLE_S * FS, r
    print(f"  subsample: {n} samples read every {step} -> {n_read} ({SAMPLE_S:g} s at {FS:g} Hz); "
          f"ratio of S02 ey {ratio:.2f} (expected {EXPECTED_RATIO:.2f})")

    # the table's order and the summary line
    table = table_rows(stdout)
    assert sorted((r[0], r[1], r[2], r[-1]) for r in table) == \
        sorted((s, run, c, r["verdict"]) for (s, run, c), r in rows.items()), "the CSV and the table differ"
    order = {"open input?": 0, "saturated?": 1, "ok": 2}
    keys = [(order[r[-1]], r[0]) for r in table]
    assert keys == sorted(keys), keys
    summary = next(ln for ln in stdout.splitlines() if ln.startswith("summary:"))
    assert "open input? S02 ey (sr1000_0001, sr1000_0002)" in summary, summary
    assert "saturated? S02 hx (sr1000_0001, sr1000_0002)" in summary, summary
    assert summary.startswith("summary: 4 of 12 channel runs flagged"), summary

    # skipped sites and runs
    assert "skipped (derived): S01L" in stdout.splitlines(), stdout
    assert "skipped (observatory): OBS" in stdout.splitlines(), stdout
    assert "skipped (no archive): S03" in stdout.splitlines(), stdout
    assert not any(site in ("S01L", "OBS") for site, _r, _c in rows), sorted(rows)
    assert not any(run == "sr100_0002" for _s, run, _c in rows) and "left out: sr100_0002 at 100 Hz" in stdout
    print("  S01L and OBS skipped with a note, S03 listed without an archive, sr100_0002 left out at 1000 Hz")

    # each level criterion alone, and both off
    _s, only_threshold, _e = run_main(module, yaml_path, "S02", "--ratio", "1e6", "--sample-seconds", SAMPLE_S)
    _s, only_ratio, _e = run_main(module, yaml_path, "S01", "S02", "--threshold-counts", "1e12",
                                  "--sample-seconds", SAMPLE_S)
    _s, neither, _e = run_main(module, yaml_path, "S01", "S02", "--threshold-counts", "1e12", "--ratio", "1e6",
                               "--sample-seconds", SAMPLE_S)

    def verdicts(stdout_text: str, comp: str) -> set[str]:
        return {r[-1] for r in table_rows(stdout_text) if r[0] == "S02" and r[2] == comp}

    assert verdicts(only_threshold, "ey") == {"open input?"}, only_threshold
    assert verdicts(only_ratio, "ey") == {"open input?"}, only_ratio
    assert verdicts(neither, "ey") == {"ok"}, neither
    print("  S02 ey flagged by the 1e9 threshold alone and by the 30 x ratio alone; ok with both off")

    # exit status
    status, _o, err = run_main(module, yaml_path, "S01", "S03")
    assert status == 2 and "S03: no archive" in err, (status, err)
    status, _o, err = run_main(module, SCRATCH / "absent.yaml")
    assert status == 2 and "no survey file" in err, (status, err)
    print("  exit 2 for S03 named without an archive and for a missing survey file")

    # the mutation: the literal |counts| share at the rail
    literal = dclevel.rail_fraction
    dclevel.rail_fraction = lambda x, median: float(np.mean(np.abs(x) >= 0.9 * np.abs(x).max()))
    try:
        _s, mutant, _e = run_main(module, yaml_path, "S01", "S02", "--sample-seconds", SAMPLE_S)
    finally:
        dclevel.rail_fraction = literal
    tripped = [r for r in table_rows(mutant) if (r[0], r[2]) in HEALTHY and r[-1] != "ok"]
    assert tripped, mutant
    print(f"  mutation |counts| >= 90 % of max|counts|: {len(tripped)} of 8 healthy channel runs come back "
          f"{sorted({r[-1] for r in tripped})}, e.g. {tripped[0][0]} {tripped[0][1]} {tripped[0][2]} "
          f"at {tripped[0][-2]} %: the healthy criterion trips")


PHOENIX_RAIL_V = 2.25  # 0.9 x the 2.5 V input range of a Phoenix E channel at circuitry gain 2


def phoenix_records() -> dict[str, np.ndarray]:
    """Return the drifting and the railed synthetic 150 Hz E records, in volts, 2 h each."""
    rng = np.random.default_rng(78)
    n = int(150 * 7200)
    drift = 0.016 + 0.030 * np.clip(np.linspace(0.0, 1.25, n), 0.0, 1.0) + rng.normal(0.0, 1e-4, n)
    railed = 0.01 + rng.normal(0.0, 0.2, n)
    hit = rng.choice(n, size=int(0.03 * n), replace=False)
    railed[hit] = np.where(rng.random(hit.size) < 0.5, -2.4, 2.4)
    return {"ex": drift, "ey": railed}


def check_input_rail() -> list[str]:
    """Classify the two records against their own rail and the absolute one. Returns the failures."""
    bad, rows = [], {}
    for rail in (None, PHOENIX_RAIL_V):
        mine = []
        for channel, x in phoenix_records().items():
            try:
                stats = dclevel.channel_stats(x, 150.0) if rail is None else dclevel.channel_stats(x, 150.0, rail=rail)
            except TypeError as exc:  # the code before the fix takes no rail
                return bad + [f"channel_stats(rail={rail}): {exc}"]
            mine.append(dict(site="P01", run="sr150_0001", channel=channel, type="electric", **stats))
        dclevel.classify(mine, threshold_counts=float("inf"))
        rows[rail] = {r["channel"]: r for r in mine}
    own, absolute = rows[None], rows[PHOENIX_RAIL_V]
    if [own[c]["verdict"] for c in ("ex", "ey")] != ["saturated?"] * 2:
        bad.append(f"own rail: ex {own['ex']['verdict']}, ey {own['ey']['verdict']}, expected both saturated?")
    ex, ey = absolute["ex"], absolute["ey"]
    if ex["verdict"] != "ok" or ex["rail_fraction"] != 0.0:
        bad.append(f"input rail: drifting ex {ex['verdict']} at {100 * ex['rail_fraction']:.2f} %")
    if ey["verdict"] != "saturated?" or abs(ey["rail_fraction"] - 0.03) > 0.002:
        bad.append(f"input rail: railed ey {ey['verdict']} at {100 * ey['rail_fraction']:.2f} %")
    line = dclevel.flag_line(absolute["ey"], "V")
    if "at the input rail (|x| >= 2.25 V)" not in line:
        bad.append(f"flag line does not name the rail: {line}")
    if "input rail" in dclevel.flag_line(own["ey"], "V"):
        bad.append(f"relative flag line names an input rail: {dclevel.flag_line(own['ey'], 'V')}")
    parsed = {r["channel"]: r for r in dclevel.parse_level_note(dclevel.level_note(list(absolute.values()), "V"))}
    if {c: r.get("rail_level") for c, r in parsed.items()} != {"ex": PHOENIX_RAIL_V, "ey": PHOENIX_RAIL_V}:
        bad.append(f"rails read back {({c: r.get('rail_level') for c, r in parsed.items()})}")
    else:
        again = dclevel.flag_line(dict(site="P01", run="sr150_0001", **parsed["ey"]), "V")
        if again != line:
            bad.append(f"flag line read back differs: {again}")
    return bad


def check_rail_key() -> list[str]:
    """The rail record's keys are dot-free, and the dotted record of 4beb3cd reads back. Returns the failures."""
    bad = []
    rows = [dict(channel=c, median_counts=0.01, rail_fraction=0.0, verdict="ok", rail_level=PHOENIX_RAIL_V)
            for c in ("ex", "ey")]
    note = dclevel.level_note(rows, "V")
    dotted = [p.split(":", 1)[0] for p in note.split(";") if ":" in p and "." in p.split(":", 1)[0]]
    if dotted:
        bad.append(f"rail key with a dot: {dotted}")
    old = note.replace(dclevel.RAIL_PREFIX, dclevel.RAIL_PREFIX_DOTTED)
    read = {r["channel"]: r.get("rail_level") for r in dclevel.parse_level_note(old)}
    if read != {"ex": PHOENIX_RAIL_V, "ey": PHOENIX_RAIL_V}:
        bad.append(f"dotted rail key read back {read}")
    return bad


def main_input_rail() -> None:
    bad = check_rail_key()
    for line in bad:
        print(f"  FAIL rail key: {line}")
    assert not bad, f"{len(bad)} rail key failure(s)"
    print(f"  rail key {dclevel.RAIL_PREFIX.split(':')[0]!r} dot-free; the 4beb3cd key "
          f"{dclevel.RAIL_PREFIX_DOTTED.split(':')[0]!r} still read back")
    kept = dclevel.RAIL_PREFIX
    dclevel.RAIL_PREFIX = dclevel.RAIL_PREFIX_DOTTED
    try:
        trip = check_rail_key()
    finally:
        dclevel.RAIL_PREFIX = kept
    assert any(t.startswith("rail key with a dot") for t in trip), trip
    print(f"  mutation (the dotted key written) tripped: {trip[0]}")
    bad = check_input_rail()
    for line in bad:
        print(f"  FAIL input rail: {line}")
    assert not bad, f"{len(bad)} input rail failure(s)"
    absolute = {c: dclevel.channel_stats(x, 150.0, rail=PHOENIX_RAIL_V) for c, x in phoenix_records().items()}
    own = {c: dclevel.channel_stats(x, 150.0) for c, x in phoenix_records().items()}
    print(f"  Phoenix input rail: drifting ex {100 * own['ex']['rail_fraction']:.2f} % at its own rail (saturated?), "
          f"{100 * absolute['ex']['rail_fraction']:.2f} % at 2.25 V (ok); railed ey "
          f"{100 * own['ey']['rail_fraction']:.2f} % and {100 * absolute['ey']['rail_fraction']:.2f} % (saturated? "
          f"both); the flag line names the rail; the note round trip keeps it")
    kept = dclevel.channel_stats
    dclevel.channel_stats = lambda samples, fs, sample_seconds=dclevel.SAMPLE_SECONDS, rail=None: kept(
        samples, fs, sample_seconds)
    try:
        trip = check_input_rail()
    finally:
        dclevel.channel_stats = kept
    assert any(t.startswith("input rail: drifting ex saturated?") for t in trip), trip
    print(f"  mutation (rail ignored) tripped: {next(t for t in trip if t.startswith('input rail: drifting'))}")


RAIL_SURVEY = "dc_level_rail"
RAIL_SURVEY_YAML = """name: {name}
instrument: lemi423
sample_rate: 150
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey]
sites:
  P01:
    latitude: -31.9
    longitude: 140.4
"""


def write_volts_archive(path: Path, site: str, runs: dict) -> None:
    """Write a site's MTH5 0.2.0 archive of float32 volts, each run with its comment.

    Args:
        path (Path): The archive.
        site (str): Station id.
        runs (dict): {run id: (sample rate, {channel: samples}, comment)}.
    """
    from mth5.mth5 import MTH5

    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(RAIL_SURVEY)
        station = m.add_station(site, survey=RAIL_SURVEY)
        station.write_metadata()
        start = T0
        for run_id, (fs, channels, comment) in runs.items():
            n = len(next(iter(channels.values())))
            end = start + pd.Timedelta(seconds=(n - 1) / fs)
            run = station.add_run(run_id)
            for comp, x in channels.items():
                ch = run.add_channel(comp, "electric", np.asarray(x, dtype="float32"))
                ch.metadata.component = comp
                ch.metadata.sample_rate = fs
                ch.metadata.time_period.start = str(start)
                ch.metadata.time_period.end = str(end)
                ch.metadata.units = "V"
                ch.write_metadata()
            run.metadata.sample_rate = fs
            run.metadata.time_period.start = str(start)
            run.metadata.time_period.end = str(end)
            run.metadata.comments.value = comment
            run.write_metadata()
            start = end + pd.Timedelta(seconds=60)
    finally:
        m.close_mth5()


def build_rail_survey() -> Path:
    """Write P01 (a run with the "dc rail" line in its comment, one without) and its survey.yaml."""
    root, work = SCRATCH / "rail" / "raw", SCRATCH / "rail" / "work"
    shutil.rmtree(SCRATCH / "rail", ignore_errors=True)
    root.mkdir(parents=True)
    records = phoenix_records()
    rows = {}
    for rail in (PHOENIX_RAIL_V, None):
        rows[rail] = [dict(site="P01", run="sr150_0001", channel=c, type="electric",
                           **dclevel.channel_stats(x, 150.0, rail=rail)) for c, x in records.items()]
        dclevel.classify(rows[rail], threshold_counts=float("inf"))
    write_volts_archive(work / "mth5" / "P01.h5", "P01", {
        "sr150_0001": (150.0, records, dclevel.level_note(rows[PHOENIX_RAIL_V], "V")),
        "sr150_0002": (150.0, records, dclevel.level_note(rows[None], "V")),
        "sr150_0003": (150.0, records, dclevel.level_note(rows[PHOENIX_RAIL_V], "V").replace(
            dclevel.RAIL_PREFIX, dclevel.RAIL_PREFIX_DOTTED)),
    })
    yaml_path = SCRATCH / "rail" / "survey.yaml"
    yaml_path.write_text(RAIL_SURVEY_YAML.format(name=RAIL_SURVEY, root=root.as_posix(), work=work.as_posix()),
                         encoding="utf-8")
    return yaml_path


def check_rail_read_back(module, yaml_path: Path) -> list[str]:
    """Run the script on P01 and check the rail it measured each run against. Returns the failures."""
    import h5py

    bad = []
    archive = yaml_path.parent / "work" / "mth5" / "P01.h5"
    with h5py.File(archive, "r", locking=False) as f:
        station = dclevel.station_group(f, RAIL_SURVEY, "P01")
        read = {run: module.comment_rails(station[run]) for run in ("sr150_0001", "sr150_0002", "sr150_0003")}
    both = {"ex": PHOENIX_RAIL_V, "ey": PHOENIX_RAIL_V}
    if read != {"sr150_0001": both, "sr150_0002": {}, "sr150_0003": both}:
        bad.append(f"comment_rails: {read}")
    out_csv = SCRATCH / "rail" / "dc_level.csv"
    status, stdout, stderr = run_main(module, yaml_path, "--csv", out_csv)
    if status != 0:
        return bad + [f"exit {status}: {stderr}"]
    rows = read_csv(out_csv)
    for run in ("sr150_0001", "sr150_0003"):
        ex, ey = rows[("P01", run, "ex")], rows[("P01", run, "ey")]
        tail = "" if run == "sr150_0001" else f" ({run}, dotted key)"
        if ex["verdict"] != "ok" or float(ex["rail_fraction"]) != 0.0 or ex["rail_level"] != "2.25":
            bad.append(f"input rail: drifting ex {ex['verdict']} at {100 * float(ex['rail_fraction']):.2f} % "
                       f"(rail {ex['rail_level'] or 'its own'}){tail}")
        if (ey["verdict"] != "saturated?" or not 0.027 <= float(ey["rail_fraction"]) <= 0.033
                or ey["rail_level"] != "2.25"):
            bad.append(f"input rail: railed ey {ey['verdict']} at {100 * float(ey['rail_fraction']):.2f} % "
                       f"(rail {ey['rail_level'] or 'its own'}){tail}")
    for comp in ("ex", "ey"):
        row = rows[("P01", "sr150_0002", comp)]
        if row["verdict"] != "saturated?" or row["rail_level"] != "":
            bad.append(f"control: sr150_0002 {comp} {row['verdict']} (rail {row['rail_level'] or 'its own'})")
    if "(the input rail of the run comment for 4 of 6 channel runs, else the record's own)" not in stdout:
        bad.append("the line above the table does not count 4 of 6 channel runs at the input rail")
    return bad


def main_rail_read_back() -> None:
    module = load_script()
    yaml_path = build_rail_survey()
    bad = check_rail_read_back(module, yaml_path)
    for line in bad:
        print(f"  FAIL rail read back: {line}")
    assert not bad, f"{len(bad)} rail read-back failure(s)"
    rows = read_csv(SCRATCH / "rail" / "dc_level.csv")
    share = {(run, c): 100 * float(rows[("P01", run, c)]["rail_fraction"])
             for run in ("sr150_0001", "sr150_0002") for c in ("ex", "ey")}
    print(f"  dc_level_check.py with the run comment's rail: sr150_0001 ex {share['sr150_0001', 'ex']:.2f} % at "
          f"2.25 V (ok), ey {share['sr150_0001', 'ey']:.2f} % (saturated?); the control sr150_0002 (no rail line) "
          f"ex {share['sr150_0002', 'ex']:.2f} % and ey {share['sr150_0002', 'ey']:.2f} % at the record's own rail "
          f"(saturated? both)")
    kept = module.comment_rails
    module.comment_rails = lambda group: {}
    try:
        trip = check_rail_read_back(module, yaml_path)
    finally:
        module.comment_rails = kept
    assert any(t.startswith("input rail: drifting ex saturated?") for t in trip), trip
    print(f"  mutation (no rail read from the comment) tripped: "
          f"{next(t for t in trip if t.startswith('input rail: drifting'))}")


if __name__ == "__main__":
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\n")[0])
    print()
    main()
    main_input_rail()
    main_rail_read_back()
    print("\nPASS  dc_level_unit")
