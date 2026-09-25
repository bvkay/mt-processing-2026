# -*- coding: utf-8 -*-
"""
Unit test for scripts/decimate_site.py and the derived-site support

A synthetic LEMI-423 site, S01, is written as B423 files (the record layout
and header of tests/new_survey_unit.py) and ingested with `ingest_site`, so
its archive carries the real calibration chain: the LEMI-120 coil table of
surveys/burra/sensors/l120n.rsp, the linear stages from the header,
`h_scale` -1000 and a 37 m Ex dipole. filters.yaml declares a notch for
S01, so the processing archive is its filtered variant. Two runs: three
contiguous 600 s files from E0, and a 600 s file from E0 + 2100 s whose
first sample is 1 ms after its whole second, as D02's second run is. Every
channel holds, in counts, a 100 s and a 20 s sine of its own amplitude and
phase, a 0.7 Hz sine of 1e5 counts and an offset. The script runs as a
subprocess, as the GUI would run it.

Usage:
    python tests/decimate_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** decimate_site.py does not exit 0, print "archive:
<workspace>/mth5/S01L.h5" and write station S01L with runs sr1_0001 and
sr1_0002 (from sr1000_0001 and sr1000_0002) holding hx hy ex ey at 1 Hz;
on either run and channel, the 100 s or the 20 s sine, fitted by least
squares on the 1 Hz samples at their own UTC times, differs from the
written one by more than 0.5 % in amplitude or 0.5 deg in phase; the
0.7 Hz sine, which 1 Hz sampling folds to 0.3 Hz, comes back above 1 % of
its amplitude there; a derived run does not start on a whole second, 12 s
(the 11.1 s reach of the 10 x 10 x 10 FIR stages, rounded up to the second)
after its source run's first whole second, or ends within 11.1 s of the
source run's end; the run comment does not name the filtered variant it
was decimated from; any source channel's metadata other than sample rate
and time period (dipole length, azimuth, units, the applied-filter list)
differs in S01L, or its filter chain does (each stage's type, name, gain,
units, and the coil table's frequencies, amplitudes and phases), or
`mtproc.timefreq.load_station` reads other scalar gains off S01L than off
the source; `processing_archive` does not return S01L.h5 itself for S01L;
a second run without --force does not keep the archive (mtime unchanged,
"kept" printed) or a run with --force does not rebuild it (mtime moved, the
same samples); survey.yaml does not read back, through `Survey`, an S01L
with derived_from S01, sample_rate 1.0, S01's position, dipoles and
azimuths and the derived record's start, `instrument_of` lemi423 and no raw
folder, while the text outside the `sites:` block and S01's entry stay as
they were; `ingest_site` on S01L does not refuse, naming decimate_site.py;
or process_rr.py --dry-run of S01L against a 1 Hz observatory entry does
not print "sample_rate: S01L 1 Hz, OBS 1 Hz" and min_period 4.0 (10.0 with
--min-period 10), and S01 (1000 Hz) against it does not exit 2 naming both
rates.

The mutation: with `decimate_array` replaced by plain subsampling, x[::1000]
(no anti-alias filter), the 0.7 Hz criterion trips (it comes back near
100 %) and the 100 s and 20 s criteria still pass; the test checks both,
so the 0.7 Hz criterion is shown able to fail.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import new_survey_unit as nsu  # noqa: E402  (the B423 record layout and header)
from _scratch import scratch_dir  # noqa: E402
from mtproc.ingest import default_archive_path, ingest_site, processing_archive  # noqa: E402
from mtproc.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "decimate_site.py"
PROCESS_RR = REPO / "scripts" / "process_rr.py"
RSP = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
SCRATCH = scratch_dir("decimate_unit")
SITE, DERIVED = "S01", "S01L"
FS = 1000
E0 = 1624949744  # the first file's epoch
FILE_S = 600
# (epoch, first tick): run 1 is three contiguous files, run 2 starts 1 ms after its second
FILES = [(E0, 0), (E0 + 600, 0), (E0 + 1200, 0), (E0 + 2100, 1)]
PERIODS = (100.0, 20.0)
# counts: {B423 column: (archive channel, {period: (amplitude, phase deg)}, offset)}
SINES = {
    "Bx": ("hx", {100.0: (2.0e5, 30.0), 20.0: (8.0e4, -60.0)}, 1.0e6),
    "By": ("hy", {100.0: (1.5e5, 110.0), 20.0: (6.0e4, 15.0)}, -7.0e5),
    "Ex": ("ex", {100.0: (3.0e5, -45.0), 20.0: (1.0e5, 170.0)}, 2.0e5),
    "Ey": ("ey", {100.0: (2.5e5, 75.0), 20.0: (9.0e4, -120.0)}, -3.0e5),
}
F_ALIAS = 0.7  # Hz, above the 0.5 Hz Nyquist of 1 Hz; folds to 0.3 Hz
A_ALIAS = 1.0e5
REACH_S = 11.1  # 10 x 10 input samples per stage: 0.1 + 1 + 10 s
AMP_TOL, PHASE_TOL_DEG, ALIAS_TOL = 0.005, 0.5, 0.01
NOTCH = [{"notch": {"f0": 50.0, "harmonics": 2, "q": 30.0, "passes": 1}}]


def signal(column: str, t: np.ndarray) -> np.ndarray:
    """Return a B423 column's counts at times t (s after E0)."""
    _comp, sines, offset = SINES[column]
    out = offset + A_ALIAS * np.sin(2 * np.pi * F_ALIAS * t)
    for period, (amp, phase) in sines.items():
        out = out + amp * np.sin(2 * np.pi * t / period + np.radians(phase))
    return out


def write_b423(path: Path, epoch: int, tick0: int) -> None:
    """Write one 600 s B423 file whose first record is `tick0` ms after `epoch`."""
    nsu.write_b423(path, 36, "2.1", -30.25, 139.22, 519.2, epoch, n=1)
    header = path.read_bytes()[:1024]
    ms = tick0 + np.arange(FILE_S * FS, dtype=np.int64)
    records = np.zeros(ms.size, dtype=nsu.RECORD)
    records["time"] = epoch + ms // 1000
    records["tick"] = ms % 1000
    t = (epoch - E0) + ms / 1000.0
    for column in SINES:
        records[column] = np.round(signal(column, t)).astype("int32")
    path.write_bytes(header + records.tobytes())


SURVEY_HEAD = """# decimate_unit scratch survey: the text above and below the sites block stays as it is
name: decimate_unit
instrument: lemi423
sample_rate: 1000
data_root: {root}
workspace: {work}
defaults:
  calibration_fn: {rsp}
  h_scale: -1000.0
  channels: [ex, ey, hx, hy]
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
"""
SURVEY_SITES = """sites:
  S01:
    dipole_length_ex: 37.0
    dipole_length_ey: 50.0
    azimuth_ex: 0.0
    azimuth_ey: 90.0
    latitude: -30.25
    longitude: 139.22
    elevation: 519.2
  OBS:
    instrument: intermagnet
    channels: [hx, hy, hz]
    latitude: 40.96
    longitude: 0.33
"""
SURVEY_TAIL = """# processing bands, after the sites block
processing:
  min_period: 0.005
  max_period: 5000.0
  periods_per_decade: 10.0
"""


def build() -> tuple[Path, Survey]:
    """Write the B423 files, survey.yaml and filters.yaml, and ingest S01's raw archive."""
    shutil.rmtree(SCRATCH, ignore_errors=True)
    root, work = SCRATCH / "raw", SCRATCH / "work"
    for epoch, tick0 in FILES:
        write_b423(root / SITE / f"{epoch}.B423", epoch, tick0)
    yaml_path = SCRATCH / "survey.yaml"
    head = SURVEY_HEAD.format(root=root.as_posix(), work=work.as_posix(), rsp=RSP.as_posix())
    yaml_path.write_text(head + SURVEY_SITES + SURVEY_TAIL, encoding="utf-8")
    (SCRATCH / "filters.yaml").write_text(yaml.safe_dump({SITE: NOTCH}), encoding="utf-8")
    survey = Survey.from_yaml(yaml_path)
    ingest_site(survey, SITE, overwrite=True)
    return yaml_path, survey


def run_script(yaml_path: Path, *extra: str) -> subprocess.CompletedProcess:
    """Run decimate_site.py on S01."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), SITE, *extra],
                          capture_output=True, text=True, cwd=REPO)


def fit(t: np.ndarray, y: np.ndarray) -> dict:
    """Fit an offset and sines at 1/100, 1/20 and 0.3 Hz; return {frequency: (amplitude, phase deg)}."""
    freqs = [1 / p for p in PERIODS] + [1.0 - F_ALIAS]
    cols = [np.ones_like(t)]
    for f in freqs:
        cols += [np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)]
    coef, *_ = np.linalg.lstsq(np.column_stack(cols), y, rcond=None)
    out = {}
    for k, f in enumerate(freqs):
        a, b = coef[1 + 2 * k], coef[2 + 2 * k]
        out[f] = (float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a))))
    return out


def read_runs(path: Path, station: str) -> dict:
    """Read every run of an archive: {run: {"start", "rate", "n", "comment", "channels": {comp: samples}}}."""
    from mth5.mth5 import MTH5
    from mtproc.timefreq import _real_runs

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(station, survey=m.surveys_group.groups_list[0])
        out = {}
        for run_id, start, end in _real_runs(st):
            run = st.get_run(run_id)
            comment = run.metadata.comments
            chans = {c: np.asarray(run.get_channel(c).hdf5_dataset[()], dtype="float64") for c in run.groups_list}
            out[run_id] = dict(start=start, end=end, rate=float(run.metadata.sample_rate), channels=chans,
                               comment=str(getattr(comment, "value", comment) or ""))
        return out
    finally:
        m.close_mth5()


def sine_failures(path: Path) -> dict[str, list[str]]:
    """Check the sines of a derived archive; return the failures per criterion ("100 s", "20 s", "0.7 Hz")."""
    failures = {"100 s": [], "20 s": [], "0.7 Hz": []}
    for run_id, run in read_runs(path, DERIVED).items():
        t0 = (run["start"] - pd.Timestamp(E0, unit="s", tz="UTC")).total_seconds()
        for column, (comp, sines, _offset) in SINES.items():
            y = run["channels"][comp]
            got = fit(t0 + np.arange(y.size) / run["rate"], y)
            for period, (amp, phase) in sines.items():
                a, p = got[1 / period]
                dphi = (p - phase + 180.0) % 360.0 - 180.0
                if abs(a / amp - 1.0) > AMP_TOL or abs(dphi) > PHASE_TOL_DEG:
                    failures[f"{period:g} s"].append(f"{run_id} {comp}: {a / amp - 1:+.2%}, {dphi:+.3f} deg")
            alias = got[1.0 - F_ALIAS][0] / A_ALIAS
            if alias > ALIAS_TOL:
                failures["0.7 Hz"].append(f"{run_id} {comp}: {alias:.1%} at 0.3 Hz")
    return failures


def worst(path: Path) -> str:
    """Summarise the largest sine errors of a derived archive for the log."""
    amp, phase, alias = 0.0, 0.0, 0.0
    for run in read_runs(path, DERIVED).values():
        t0 = (run["start"] - pd.Timestamp(E0, unit="s", tz="UTC")).total_seconds()
        for comp, sines, _offset in SINES.values():
            y = run["channels"][comp]
            got = fit(t0 + np.arange(y.size) / run["rate"], y)
            for period, (a0, p0) in sines.items():
                a, p = got[1 / period]
                amp = max(amp, abs(a / a0 - 1.0))
                phase = max(phase, abs((p - p0 + 180.0) % 360.0 - 180.0))
            alias = max(alias, got[1.0 - F_ALIAS][0] / A_ALIAS)
    return f"worst amplitude {amp:.4%}, phase {phase:.4f} deg, 0.7 Hz left {alias:.3%}"


def chain(ch) -> list[tuple]:
    """Describe a channel's filter chain: type, name, gain, units and any response table."""
    out = []
    for f in ch.channel_response.filters_list:
        row = [type(f).__name__, f.name, float(getattr(f, "gain", 1.0) or 1.0), str(f.units_in), str(f.units_out)]
        for key in ("frequencies", "amplitudes", "phases"):
            if hasattr(f, key) and getattr(f, key) is not None:
                row.append(tuple(np.round(np.asarray(getattr(f, key), dtype=float), 12)))
        out.append(tuple(row))
    return out


def metadata_of(path: Path, station: str) -> dict:
    """Return {run index: {comp: (metadata dict less rate and time period, chain, scalar gain)}}."""
    from mth5.mth5 import MTH5
    from mtproc.timefreq import _real_runs, _scalar_gain

    skip = ("sample_rate", "time_period.start", "time_period.end", "hdf5_reference")
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(station, survey=m.surveys_group.groups_list[0])
        out = {}
        for run_id, _s, _e in _real_runs(st):
            run = st.get_run(run_id)
            out[run_id.rsplit("_", 1)[-1]] = {
                c: ({k: v for k, v in run.get_channel(c).metadata.to_dict(single=True).items() if k not in skip},
                    chain(run.get_channel(c)), _scalar_gain(run.get_channel(c)))
                for c in run.groups_list}
        return out
    finally:
        m.close_mth5()


def main() -> None:
    from mtproc.timefreq import load_station

    yaml_path, survey = build()
    raw_text = yaml_path.read_text(encoding="utf-8")
    source = processing_archive(survey, SITE)
    assert source.name.startswith(f"{SITE}_f"), f"the processing archive is not the variant: {source}"
    out_path = default_archive_path(survey, DERIVED)

    done = run_script(yaml_path)
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    assert f"archive: {out_path}" in done.stdout.splitlines(), done.stdout
    derived, src = read_runs(out_path, DERIVED), read_runs(source, SITE)
    assert list(derived) == ["sr1_0001", "sr1_0002"], list(derived)
    assert list(src) == ["sr1000_0001", "sr1000_0002"], list(src)
    for (rid, run), (sid, srun) in zip(derived.items(), src.items()):
        assert sorted(run["channels"]) == ["ex", "ey", "hx", "hy"] and run["rate"] == 1.0, (rid, run["rate"])
        first_second = srun["start"].ceil("s")
        assert run["start"] == first_second + pd.Timedelta(seconds=12), (rid, run["start"], srun["start"])
        assert run["start"] == run["start"].floor("s"), f"{rid} does not start on a whole second"
        assert run["end"] <= srun["end"] - pd.Timedelta(seconds=REACH_S), (rid, run["end"], srun["end"])
        assert f"decimated from {source.name} {sid}" in run["comment"], run["comment"]
        print(f"  {rid} <- {sid}: source starts {srun['start']}, derived {run['start']} (+12 s from the "
              f"second), ends {run['end']} (source {srun['end']})")

    failures = sine_failures(out_path)
    assert not any(failures.values()), failures
    print(f"  sines at 1 Hz: {worst(out_path)} (limits {AMP_TOL:.1%}, {PHASE_TOL_DEG} deg, {ALIAS_TOL:.0%})")

    got_meta, want_meta = metadata_of(out_path, DERIVED), metadata_of(source, SITE)
    assert got_meta == want_meta, "the channel metadata or filter chains of S01L differ from the source's"
    rec_d = load_station(out_path, survey.name, DERIVED, comps=("hx", "hy", "ex", "ey"))
    rec_s = load_station(source, survey.name, SITE, comps=("hx", "hy", "ex", "ey"))
    assert rec_d.gains == rec_s.gains, (rec_d.gains, rec_s.gains)
    hx_chain = [row[:3] for row in want_meta["0001"]["hx"][1]]
    print(f"  calibration copied: hx chain {hx_chain}; load_station gains {rec_d.gains}")

    assert processing_archive(Survey.from_yaml(yaml_path), DERIVED) == out_path, "processing_archive of S01L"
    try:
        ingest_site(Survey.from_yaml(yaml_path), DERIVED)
    except ValueError as exc:
        assert "decimate_site.py" in str(exc), exc
    else:
        raise AssertionError("ingest_site on a derived site must refuse")

    # the survey entry, through Survey, and the text around the sites block
    text = yaml_path.read_text(encoding="utf-8")
    head = raw_text.split("sites:\n", 1)[0]
    assert text.startswith(head) and text.endswith(SURVEY_TAIL), "text outside the sites block changed"
    again = Survey.from_yaml(yaml_path)
    cfg, parent = again.site(DERIVED), again.site(SITE)
    assert (cfg.derived_from, cfg.sample_rate) == (SITE, 1.0), (cfg.derived_from, cfg.sample_rate)
    for key in ("latitude", "longitude", "elevation", "dipole_length_ex", "dipole_length_ey", "azimuth_ex",
                "azimuth_ey"):
        assert getattr(cfg, key) == getattr(parent, key), (key, getattr(cfg, key), getattr(parent, key))
    assert cfg.start == derived["sr1_0001"]["start"].strftime("%Y-%m-%dT%H:%M:%SZ"), cfg.start
    assert again.instrument_of(DERIVED) == "lemi423" and DERIVED not in again.site_dirs()
    before = yaml.safe_load(SURVEY_SITES)["sites"][SITE]
    assert yaml.safe_load(text)["sites"][SITE] == before, yaml.safe_load(text)["sites"][SITE]
    print(f"  survey.yaml: {DERIVED} {yaml.safe_load(text)['sites'][DERIVED]}")

    # --force semantics
    mtime = out_path.stat().st_mtime_ns
    kept = run_script(yaml_path)
    assert kept.returncode == 0 and "kept" in kept.stdout and out_path.stat().st_mtime_ns == mtime, kept.stdout
    rebuilt = run_script(yaml_path, "--force")
    assert rebuilt.returncode == 0 and out_path.stat().st_mtime_ns != mtime, rebuilt.stdout + rebuilt.stderr
    for rid, run in read_runs(out_path, DERIVED).items():
        for comp, y in run["channels"].items():
            assert np.array_equal(y, derived[rid]["channels"][comp]), (rid, comp)
    print("  kept without --force (mtime unchanged); rebuilt with --force, the same samples")

    # process_rr.py at the derived rate
    def dry(local, *extra):
        return subprocess.run([sys.executable, str(PROCESS_RR), str(yaml_path), local, "OBS", *extra,
                               "--dry-run"], capture_output=True, text=True, cwd=REPO)

    done = dry(DERIVED)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = dict(ln.split(": ", 1) for ln in done.stdout.splitlines() if ": " in ln)
    assert lines["sample_rate"] == "S01L 1 Hz, OBS 1 Hz" and lines["min_period"] == "4.0", lines
    assert "derived from S01" in lines["local archive"], lines["local archive"]
    given = dry(DERIVED, "--min-period", "10")
    assert "min_period: 10.0" in given.stdout.splitlines(), given.stdout
    refused = dry(SITE)
    assert refused.returncode == 2 and "1000 Hz" in refused.stderr and "at 1 Hz" in refused.stderr, \
        (refused.returncode, refused.stderr)
    print(f"  process_rr --dry-run: {lines['sample_rate']}, min_period {lines['min_period']}; "
          f"S01 vs OBS refused: {refused.stderr.strip()}")

    # the mutation: plain subsampling instead of the FIR stages
    spec = importlib.util.spec_from_file_location("decimate_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.decimate_array = lambda x, stages: x[::int(np.prod(stages))]
    mutant = SCRATCH / "work" / "mutant" / f"{DERIVED}.h5"
    module.write_derived(source, SITE, mutant, 1.0)
    tripped = sine_failures(mutant)
    assert tripped["0.7 Hz"] and not tripped["100 s"] and not tripped["20 s"], tripped
    print(f"  mutation x[::1000]: the 0.7 Hz criterion trips ({tripped['0.7 Hz'][0]}), 100 s and 20 s still pass")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    main()
    print("\nPASS  decimate_unit")
