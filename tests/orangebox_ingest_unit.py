# -*- coding: utf-8 -*-
"""
Unit test of the Orange Box instrument of mt-workbench on synthetic files

Synthetic Orange Box files written in the documented layout (the writer of
tests/orangebox_unit.py) go through detection, `Survey.site`,
`mt_workbench.ingest.ingest_site` and scripts/new_survey.py in a temporary
survey: three files, two back to back and one two hours later, logged on
a clock running on Australia/Perth (UTC+8) that was 5 s ahead of GPS at
recovery (`clock_drift_s: -5.0`). The samples carry a 100 s sine on ch0
(hx) taken at the instants the Orange Box time base
puts them at; the test predicts those instants itself
from the stamps, the zone and the drift, and reads the archive back.

Usage:
    python tests/orangebox_ingest_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - `detect_instrument` does not say "orangebox" for the folder of three
    files, or says anything but None for a folder holding one empty
    HFM0-000.BIN only;
  - the ingest does not write two runs (the 2 h gap splits them, the back
    to back pair joins), or either run's sample rate is not 10.0 Hz;
  - the first sample of the archive is not at the first header stamp less
    8 h (Perth) to within 0.1 s, read from the archive's time index;
  - a run's sample count differs by more than one from N x 10 / fs_true,
    with fs_true = N / (T_rtc + drift x T_rtc / T_dep) worked out by the
    test from the stamps it wrote;
  - the sine read back from the archive through the chain (counts divided
    by the hx filter gain the archive holds) has an amplitude other than
    FS_nT x A / 2**23 to 0.5 %, or lies more than 0.05 s from the instants
    the time base predicts, in either run (a reader that ignores the drift
    puts run 2 4.1 s off; one that ignores the zone, 8 h; one that times
    the samples at the header's nominal 10.00064 Hz, 0.9 s at the end of
    run 1);
  - the second run's comment does not record the drift, or a site with no
    `clock_drift_s` does not get "drift unrecorded" in its run comments and
    drift_recorded False from `archive_time_base`;
  - an Orange Box key (`clock_drift_s`) in a LEMI-423 site's own entry, or
    `calibration_fn` in an Orange Box site's own entry, is not refused by
    `_check_instrument_keys`; or an Orange Box site with no
    `electric_full_scale_uv` is not refused before any archive is written,
    with 25000 and 100000 named in the message;
  - `SiteConfig` accepts a clock_timezone zoneinfo does not know, or a
    clock_drift_s of 1e4 s;
  - five back-to-back files stamped at 10.001 records per RTC second do
    not give `header_rate` 10.001 to 1e-9;
  - scripts/new_survey.py on the folder (with --clock-timezone
    Australia/Perth) does not write instrument orangebox, serial hfm2 from
    the report HFM0-RPT.TXT ("Number 0" is box 2), start at the first
    header less 8 h, channels ex ey hx hy hz and `clock_timezone:
    Australia/Perth` under `defaults:`, or does not print the line
    "logger clocks read on Australia/Perth";
  - (the `time_base` key) a site declaring `time_base:
    headers` gives an archive that differs from the default's (S2, no key)
    by any sample or any grid time, in either run; or a site declaring
    `time_base: nominal` (no drift) is not read on the reader's own axis:
    its runs' first samples not at their first headers less 8 h to 0.1 s,
    its sample counts not N x 10 / 10.00064 to one, its sine more than
    0.05 s from the instants the test predicts for the nominal axis (and
    the nominal axis lies at least 1.5 s from the headers axis in run 1's last
    ten minutes and through run 2, so a reader that ignores the key fails), its
    run comments without time_base=nominal, or `archive_time_base` not
    giving time_base "nominal", rate_from "nominal", fs_true 10.00064 Hz
    and drift_recorded False; or `SiteConfig` accepts `time_base: gps` or
    `time_base: nominal` with a clock_drift_s, or `_check_instrument_keys`
    accepts `time_base` in a LEMI-423 site's own entry.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

_spec = importlib.util.spec_from_file_location("orangebox_unit", REPO / "tests" / "orangebox_unit.py")
_ob_unit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ob_unit)  # the file writer; its import removes loguru's handlers
write_orange_bin = _ob_unit.write_orange_bin

import pandas as pd  # noqa: E402

from mt_workbench import orangebox  # noqa: E402
from mt_workbench.instruments import detect_instrument  # noqa: E402

FS_NT = 70000.0
FS_UV = 25000.0
A_COUNTS = 2 ** 20
PERIOD = 100.0
DRIFT = -5.0
N_FILE = 30003  # records per file
RTC_RATE = 10.001  # records per RTC second in the synthetic stamps: a file spans 3000 RTC s
FP = 0x7A1
# the first header, on the logger clock (Perth, UTC+8)
T0 = datetime(2006, 5, 2, 14, 56, 0)
# file starts on the logger clock: two back to back, the third 2 h after the second ends
STARTS = [T0, T0 + timedelta(seconds=3000), T0 + timedelta(seconds=6000 + 7200)]
T_DEP = 6000 + 7200 + 3000.0
T_REF = datetime(2006, 5, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def _utc(stamp: datetime) -> float:
    """A Perth wall-clock stamp as UTC seconds (UTC+8 in May 2006)."""
    return (stamp - timedelta(hours=8)).replace(tzinfo=timezone.utc).timestamp()


def _fs_true() -> float:
    """The test's own fs_true: N / (T_rtc + drift x T_rtc / T_dep), the same for every run here."""
    t_rtc = N_FILE / RTC_RATE
    return N_FILE / (t_rtc + DRIFT * t_rtc / T_DEP)


def _run_starts() -> list[float]:
    """The test's own UTC time of each run's first sample: its header in UTC plus the RTC error by then."""
    out = []
    for start in (STARTS[0], STARTS[2]):
        error = DRIFT * (start - T0).total_seconds() / T_DEP
        out.append(_utc(start) + error)
    return out


def _write_files(folder: Path) -> None:
    """Write the three files, the sine on ch0 at the true instants of the time base, and the report."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    fs = _fs_true()
    run_start = _run_starts()
    k0 = {0: 0, 1: N_FILE, 2: 0}
    for i, start in enumerate(STARTS):
        t = run_start[0 if i < 2 else 1] + (k0[i] + np.arange(N_FILE)) / fs
        counts = np.zeros((N_FILE, 8), dtype=np.int64)
        counts[:, 0] = 2 ** 23 + np.round(A_COUNTS * np.sin(2 * np.pi * (t - T_REF) / PERIOD)).astype(np.int64)
        for ch in (1, 2, 6, 7):
            counts[:, ch] = 2 ** 23 + rng.integers(-1000, 1000, N_FILE)
        counts[:, 3] = 1000
        counts[:, 4] = 1000
        counts[:, 5] = 20
        end = write_orange_bin(folder / f"HFM0-{i:03d}.BIN", counts, pd.Timestamp(start), fp=FP)
        # write_orange_bin stamps the trailer at the nominal rate; the stamps must say RTC_RATE
        assert (end - pd.Timestamp(start)).total_seconds() == 3000.0, end
    (folder / "HFM0-RPT.TXT").write_text("High Frequency Magnetometer Number 0 - Flinders University 1999 - 2003\n"
                                         "  * Logging started at Tue May  2 14:56:00 2006\n", encoding="ascii")


def _survey_yaml(root: Path, sites: dict) -> Path:
    """Write a survey.yaml for the synthetic sites and return its path."""
    config = {"name": "obtest", "instrument": "orangebox", "sample_rate": 10, "data_root": str(root / "raw"),
              "workspace": str(root / "ws"),
              "defaults": {"azimuth_ex": 0.0, "azimuth_ey": 90.0, "channels": ["ex", "ey", "hx", "hy", "hz"],
                           "electric_full_scale_uv": FS_UV, "magnetic_full_scale_nt": FS_NT,
                           "clock_timezone": "Australia/Perth"},
              "sites": sites}
    path = root / "survey" / "survey.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _archive_runs(path: Path, site: str) -> dict:
    """Read each run's hx back: {run: (time ns, nT through the chain, sample rate, comment)}."""
    from mth5.mth5 import MTH5

    out = {}
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station(site, survey="obtest")
        for run_id in station.groups_list:
            if not run_id.startswith("sr"):
                continue
            run = station.get_run(run_id)
            ch = run.get_channel("hx").to_channel_ts()
            gain = 1.0
            for f in ch.channel_response.filters_list:
                gain *= float(f.gain)
            t = ch.data_array.time.values.astype("datetime64[ns]").astype(np.int64)
            out[run_id] = (t, np.asarray(ch.ts, dtype=float) / gain, float(ch.sample_rate),
                           str(run.metadata.comments.value or ""))
    finally:
        m.close_mth5()
    return out


def test_detection(root: Path) -> None:
    from mt_workbench.instruments import detect_instrument as detect

    assert detect(root / "raw" / "S1") == "orangebox", detect(root / "raw" / "S1")
    empty = root / "empty_only"
    empty.mkdir()
    (empty / "HFM0-000.BIN").write_bytes(b"")
    assert detect(empty) is None, detect(empty)
    print("  detection: orangebox for the three files, None for a folder of one empty file")


def test_ingest_time_base(root: Path) -> None:
    from mt_workbench.ingest import archive_time_base, ingest_site
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(root / "survey" / "survey.yaml")
    out = ingest_site(survey, "S1", overwrite=True)
    runs = _archive_runs(out, "S1")
    assert sorted(runs) == ["sr10_0001", "sr10_0002"], sorted(runs)
    fs = _fs_true()
    starts = _run_starts()
    first_ns = min(r[0][0] for r in runs.values())
    want_first = _utc(T0) * 1e9
    assert abs(first_ns - want_first) <= 1e8, (first_ns - want_first) / 1e9
    print(f"  first sample {pd.Timestamp(first_ns, unit='ns')} UTC, first header {T0} Perth: "
          f"{(first_ns - want_first) / 1e9:+.3f} s from header - 8 h")
    n_run = {"sr10_0001": 2 * N_FILE, "sr10_0002": N_FILE}
    for run_id, (t, nt, rate, comment) in sorted(runs.items()):
        assert rate == 10.0, (run_id, rate)
        want_n = n_run[run_id] * 10.0 / fs
        assert abs(len(t) - want_n) <= 1.0, (run_id, len(t), want_n)
        # least squares fit of a sin + b cos at the archive's times: amplitude and the time shift of the sine
        x = 2 * np.pi * (t / 1e9 - T_REF) / PERIOD
        design = np.column_stack([np.sin(x), np.cos(x), np.ones_like(x)])
        (a, b, _c), *_ = np.linalg.lstsq(design, nt, rcond=None)
        amplitude = float(np.hypot(a, b))
        shift = float(np.arctan2(b, a)) / (2 * np.pi) * PERIOD  # value(t) = amp sin(2 pi (t + shift) / P)
        want_amp = FS_NT * A_COUNTS / 2 ** 23
        print(f"  {run_id}: {len(t)} samples at {rate:g} Hz (N x 10 / fs_true = {want_n:.2f}); sine amplitude "
              f"{amplitude:.3f} nT against {want_amp:.3f} ({amplitude / want_amp - 1:+.4%}); time shift {shift:+.4f} s")
        assert abs(amplitude / want_amp - 1) <= 0.005, (run_id, amplitude, want_amp)
        assert abs(shift) <= 0.05, (run_id, shift)
    assert "clock_drift_s=-5.0" in runs["sr10_0002"][3] and "drift unrecorded" not in runs["sr10_0002"][3]
    bases = archive_time_base(out, "S1")
    assert abs(bases["sr10_0001"]["fs_true_hz"] - fs) < 1e-6 and bases["sr10_0001"]["drift_recorded"], bases
    assert bases["sr10_0001"]["rate_from"] == "stamps", bases["sr10_0001"]  # three files: too few headers to fit
    print(f"  fs_true {fs:.7f} Hz (test) and {bases['sr10_0001']['fs_true_hz']:.7f} Hz (recorded); run starts "
          f"{starts[0]:.3f}, {starts[1]:.3f} UTC s predicted")
    # the same files with no clock_drift_s: drift unrecorded, no correction
    survey2 = Survey.from_yaml(root / "survey" / "survey.yaml")
    out2 = ingest_site(survey2, "S2", overwrite=True)
    bases2 = archive_time_base(out2, "S2")
    comments = [r[3] for r in _archive_runs(out2, "S2").values()]
    assert all("drift unrecorded" in c for c in comments) and not any(b["drift_recorded"] for b in bases2.values())
    print("  S2 (no clock_drift_s): 'drift unrecorded' in both run comments, drift_recorded False")


def test_keys_refused(root: Path) -> None:
    from mt_workbench.ingest import _check_instrument_keys, ingest_site
    from mt_workbench.survey import SiteConfig, Survey

    survey = Survey({"name": "x", "instrument": "lemi423", "data_root": str(root),
                     "sites": {"L1": {"clock_drift_s": 1.0}}}, root)
    try:
        _check_instrument_keys(survey, survey.site("L1"), "lemi423")
    except ValueError as exc:
        assert "clock_drift_s" in str(exc) and "Orange Box" in str(exc), exc
        print(f"  LEMI-423 site with clock_drift_s refused: {exc}")
    else:
        raise AssertionError("clock_drift_s on a LEMI-423 site was not refused")
    survey = Survey({"name": "x", "instrument": "orangebox", "data_root": str(root),
                     "sites": {"O1": {"calibration_fn": "l120n.rsp"}}}, root)
    try:
        _check_instrument_keys(survey, survey.site("O1"), "orangebox")
    except ValueError as exc:
        assert "calibration_fn" in str(exc), exc
        print(f"  Orange Box site with calibration_fn refused: {exc}")
    else:
        raise AssertionError("calibration_fn on an Orange Box site was not refused")
    path = root / "survey" / "survey.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    del config["defaults"]["electric_full_scale_uv"]
    config["workspace"] = str(root / "ws_missing")
    path_missing = root / "survey_missing" / "survey.yaml"
    path_missing.parent.mkdir()
    path_missing.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    try:
        ingest_site(Survey.from_yaml(path_missing), "S1", overwrite=True)
    except ValueError as exc:
        assert "electric_full_scale_uv" in str(exc) and "25000" in str(exc) and "100000" in str(exc), exc
        assert not (root / "ws_missing" / "mth5" / "S1.h5").exists(), "an archive was written"
        print(f"  missing electric full scale refused, nothing written: {exc}")
    else:
        raise AssertionError("an Orange Box site with no electric_full_scale_uv was ingested")
    for bad in ({"clock_timezone": "Mars/Olympus"}, {"clock_drift_s": 1e4}):
        try:
            SiteConfig(name="B", **bad)
        except ValueError as exc:
            print(f"  refused {bad}: {exc}")
        else:
            raise AssertionError(f"SiteConfig accepted {bad}")


def test_header_rate(root: Path) -> None:
    folder = root / "five"
    folder.mkdir()
    counts = np.full((N_FILE, 8), 2 ** 23, dtype=np.int64)
    counts[:, 3:6] = 0
    for i in range(5):
        write_orange_bin(folder / f"HFM1-{i:03d}.BIN", counts, pd.Timestamp(T0 + timedelta(seconds=3000 * i)), fp=FP)
    listed, skipped = orangebox.orange_files(sorted(folder.iterdir()))
    runs = orangebox.plan_runs(listed)
    rate, latency = orangebox.header_rate(runs)
    assert len(runs) == 1 and not skipped and abs(rate - RTC_RATE) < 1e-9 and abs(latency) < 1e-6, (runs, rate, latency)
    print(f"  five back-to-back files: one run, header_rate {rate:.9f} records per RTC second, latency {latency:.2e} s")


def test_time_base_key(root: Path) -> None:
    from mt_workbench.ingest import _check_instrument_keys, archive_time_base, ingest_site
    from mt_workbench.survey import SiteConfig, Survey

    survey = Survey.from_yaml(root / "survey" / "survey.yaml")
    # headers, declared, against the default (S2: the same files, no key, no drift)
    default = _archive_runs(ingest_site(survey, "S2", overwrite=True), "S2")
    declared = _archive_runs(ingest_site(survey, "S3", overwrite=True), "S3")
    assert sorted(default) == sorted(declared), (sorted(default), sorted(declared))
    for run_id in default:
        t0, v0 = default[run_id][0], default[run_id][1]
        t1, v1 = declared[run_id][0], declared[run_id][1]
        assert np.array_equal(t0, t1) and np.array_equal(v0, v1), run_id
    print(f"  time_base headers declared (S3) = the default (S2): {sum(len(r[0]) for r in default.values())} "
          f"samples and grid times identical in {len(default)} runs")
    # nominal: the reader's own axis
    out = ingest_site(survey, "S4", overwrite=True)
    runs = _archive_runs(out, "S4")
    assert sorted(runs) == ["sr10_0001", "sr10_0002"], sorted(runs)
    nominal = 1e7 / (512 * FP)
    fs = _fs_true()
    true_start = _run_starts()
    headers = {"sr10_0001": _utc(STARTS[0]), "sr10_0002": _utc(STARTS[2])}
    n_run = {"sr10_0001": 2 * N_FILE, "sr10_0002": N_FILE}
    for i, (run_id, (t, nt, rate, comment)) in enumerate(sorted(runs.items())):
        g = t / 1e9
        assert abs(g[0] - headers[run_id]) <= 0.1, (run_id, g[0] - headers[run_id])
        want_n = n_run[run_id] * 10.0 / nominal
        assert abs(len(t) - want_n) <= 1.0, (run_id, len(t), want_n)
        k = (g - headers[run_id]) * nominal  # the sample index the nominal axis puts at grid time g
        u = true_start[i] + k / fs  # the instant that sample was taken (the synthetic truth)
        x = 2 * np.pi * (u - T_REF) / PERIOD
        design = np.column_stack([np.sin(x), np.cos(x), np.ones_like(x)])
        (a, b, _c), *_ = np.linalg.lstsq(design, nt, rcond=None)
        shift = float(np.arctan2(b, a)) / (2 * np.pi) * PERIOD
        apart = g - u  # the nominal axis against the headers axis, s
        where = apart[-6000:] if i == 0 else apart
        print(f"  {run_id} nominal: first sample {g[0] - headers[run_id]:+.3f} s from its header - 8 h, {len(t)} "
              f"samples (N x 10 / 10.00064 = {want_n:.2f}), sine shift {shift:+.4f} s against the nominal "
              f"prediction; nominal minus headers axis {np.min(where):+.2f} to {np.max(where):+.2f} s "
              f"({'last ten minutes' if i == 0 else 'whole run'})")
        assert abs(shift) <= 0.05, (run_id, shift)
        assert np.min(np.abs(where)) >= 1.5, (run_id, np.min(np.abs(where)))
        assert "time_base=nominal" in comment and "rate_from=nominal" in comment, comment
    bases = archive_time_base(out, "S4")
    for run_id, base in bases.items():
        assert base["time_base"] == "nominal" and base["rate_from"] == "nominal", base
        assert abs(base["fs_true_hz"] - nominal) < 1e-6 and not base["drift_recorded"], base
    assert archive_time_base(root / "ws" / "mth5" / "S2.h5", "S2")["sr10_0001"]["time_base"] == "headers"
    print(f"  archive_time_base: time_base nominal, rate_from nominal, fs_true {nominal:.7f} Hz, drift_recorded "
          f"False; S2 reads time_base headers")
    for bad in ({"time_base": "gps"}, {"time_base": "nominal", "clock_drift_s": -5.0}):
        try:
            SiteConfig(name="B", **bad)
        except ValueError as exc:
            print(f"  refused {bad}: {exc}")
        else:
            raise AssertionError(f"SiteConfig accepted {bad}")
    lemi = Survey({"name": "x", "instrument": "lemi423", "data_root": str(root),
                   "sites": {"L1": {"time_base": "nominal"}}}, root)
    try:
        _check_instrument_keys(lemi, lemi.site("L1"), "lemi423")
    except ValueError as exc:
        assert "time_base" in str(exc), exc
        print(f"  LEMI-423 site with time_base refused: {exc}")
    else:
        raise AssertionError("time_base on a LEMI-423 site was not refused")


def test_new_survey(root: Path) -> None:
    import contextlib
    import io

    import new_survey

    out = root / "ns" / "survey.yaml"
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = new_survey.main([str(root / "raw"), "--name", "obns", "--instrument", "auto", "--out", str(out),
                                "--clock-timezone", "Australia/Perth", "--timezone", "Australia/Perth"])
    assert code == 0, (code, printed.getvalue())
    assert "logger clocks read on Australia/Perth" in printed.getvalue().splitlines(), printed.getvalue()
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert config["instrument"] == "orangebox", config["instrument"]
    assert config["defaults"]["clock_timezone"] == "Australia/Perth", config["defaults"]
    assert config["defaults"]["channels"] == ["ex", "ey", "hx", "hy", "hz"], config["defaults"]["channels"]
    entry = config["sites"]["S1"]
    want = pd.Timestamp(_utc(T0), unit="s").strftime("%Y-%m-%dT%H:%M:%SZ")
    assert entry["serial"] == "hfm2" and entry["start"] == want, entry
    print(f"  new_survey: instrument orangebox, S1 serial {entry['serial']}, start {entry['start']} (header - 8 h), "
          f"defaults clock_timezone {config['defaults']['clock_timezone']}")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_files(root / "raw" / "S1")
        _write_files(root / "raw" / "S2")
        _write_files(root / "raw" / "S3")
        _write_files(root / "raw" / "S4")
        _survey_yaml(root, {"S1": {"dipole_length_ex": 15.0, "dipole_length_ey": 20.0, "clock_drift_s": DRIFT},
                            "S2": {"dipole_length_ex": 15.0, "dipole_length_ey": 20.0},
                            "S3": {"dipole_length_ex": 15.0, "dipole_length_ey": 20.0, "time_base": "headers"},
                            "S4": {"dipole_length_ex": 15.0, "dipole_length_ey": 20.0, "time_base": "nominal"}})
        tests = [test_detection, test_ingest_time_base, test_keys_refused, test_header_rate, test_time_base_key,
                 test_new_survey]
        for test in tests:
            test(root)
            print(f"  ok  {test.__name__}")
    print(f"\nPASS  orangebox_ingest_unit ({len(tests)} tests)")
