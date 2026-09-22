"""Offline unit test for `mtproc.observatory` and `scripts/fetch_observatory.py`: the GIN is mocked.

    python tests/observatory_unit.py

The IAGA-2002 day files are written here, in the format's fixed layout (70-character header lines
ending in "|", a comment line, the DATE column line, then one row per second), for a synthetic
observatory SFS at 36.665 N, 354.058 E, 111 m: on each day rows exist for the seconds k = 0..599 and
1800..2399 after midnight UTC (the 20 minutes between are absent), with X = 27000 + k/100,
Y = -500 + k/50, Z = 30000 - k/100 nT (exact to the format's two decimals), F = 88888.00 (not
recorded) throughout, and X, Y, Z = 99999.00 (missing) for k = 300..329: a 30 s gap. The one
network call, `mtproc.observatory._http_get`, is replaced by a function that records every URL it
is asked for and serves that day's text (or, offline, raises what urllib raises when a name does
not resolve). Everything is written under a temporary directory, removed at the end.

**This test fails if**
(a) `parse_iaga2002` of the 2023-09-20 text does not give exactly 1200 rows whose unix times are
    1695168000 + k for k = 0..599 and 1800..2399, whose x, y, z equal the formulas above to 1e-9 nT
    except NaN in exactly the 30 rows k = 300..329, and whose f is NaN in every row; or
    `header_position` of its header is not (36.665, -5.942, 111.0) -- the longitude turned from
    354.058 E into -180..180;
(b) after `load` over that day (max_gap_s 600) x, y, z at k = 300..329 are not the straight line
    between k = 299 and 330 (here the formulas, to 1e-9 nT), or anything in the 1200 s gap
    (k = 600..1799) or after k = 2399 is finite; or the archive `to_mth5` writes, read back with
    h5py, does not hold exactly two runs, sr1_0001 starting 2023-09-20T00:00:00 with 600 samples and
    sr1_0002 starting 2023-09-20T00:30:00 with 600 samples, whose hx, hy, hz equal X, Y, Z (the
    filled 30 s included) to 1e-9 nT;
(c) that archive's one station is not SFS at latitude 36.665, longitude -5.942, elevation 111.0; a
    run holds any dataset but hx, hy, hz (F dropped); a channel's sample_rate is not 1.0, its units
    not nT (mt_metadata stores "nanoTesla") or its filters not empty; or a run's comment is not
    "INTERMAGNET SFS one-second, best-available, XYZF, GIN <url>, fetched <UTC>" with <url> the
    exact URL the mocked GIN was asked for and <UTC> within the second of the fetch;
(d) `fetch_days` over 2023-09-20..21 does not ask the GIN exactly twice, the same call again asks
    it more than zero times or changes a cached file's bytes, or over 20..22 asks for anything but
    2023-09-22; `--dry-run` asks the GIN anything, creates or changes any file, or does not print
    the uncached day; offline (every request failing to resolve), the script does not return 1
    with exactly one line on stderr that starts "ERROR" and says "unreachable", or changes the
    cache (every file's bytes compared) or writes an archive;
(e) after `fetch_observatory.py <survey.yaml> sfs` on a survey written the way new_survey.py writes
    one (three sites dated 2023-09-20T05:00Z to 2023-09-21T03:00Z, so the default span is those
    two days), survey.yaml's text above `sites:` or any other site's lines are not byte-identical
    to before; the SFS entry is not {instrument: intermagnet, channels: [hx, hy, hz], latitude
    36.665, longitude -5.942, elevation 111.0, start 2023-09-20T00:00:00Z, end
    2023-09-21T00:40:00Z, notes "INTERMAGNET observatory, 1 s, fetched <UTC>"} in that key order;
    the archive is not <workspace>/mth5/SFS.h5 with four runs; running it again asks the GIN
    anything or changes a byte of survey.yaml; or a survey whose SFS is a recorded site does not
    make the script return 2 and leave that file byte-identical.
"""

from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import re
import socket
import sys
import tempfile
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from textwrap import indent

import h5py
import numpy as np
import pandas as pd
import yaml
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc import observatory  # noqa: E402

SCRIPT = REPO / "scripts" / "fetch_observatory.py"
CODE = "SFS"
DAY = "2023-09-20"
T0 = 1695168000  # 2023-09-20T00:00:00Z
ROWS = list(range(600)) + list(range(1800, 2400))
FILL = range(300, 330)
HEADER = [("Format", "IAGA-2002"), ("Source of Data", "synthetic, tests/observatory_unit.py"),
          ("Station Name", "San Fernando"), ("IAGA Code", CODE), ("Geodetic Latitude", "36.665"),
          ("Geodetic Longitude", "354.058"), ("Elevation", "111"), ("Reported", "XYZF"),
          ("Sensor Orientation", "HDZF"), ("Digital Sampling", "0.01 second"),
          ("Data Interval Type", "1-second (00:00:00 - 00:00:00)"), ("Data Type", "Definitive")]


def xyz(k) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k = np.asarray(k, float)
    return 27000.0 + k / 100.0, -500.0 + k / 50.0, 30000.0 - k / 100.0


def iaga_day(day: str) -> bytes:
    """One synthetic IAGA-2002 day (see the module docstring)."""
    lines = [f" {label:<23}{value:<45}|" for label, value in HEADER]
    lines.append(f" # {'synthetic: X Y Z linear in the second of the day':<66}|")
    lines.append(f"DATE       TIME         DOY     {CODE}X      {CODE}Y      {CODE}Z      {CODE}F   |")
    t0 = pd.Timestamp(day)
    for k in ROWS:
        t = t0 + pd.Timedelta(seconds=k)
        x, y, z = (float(v) for v in xyz(k))
        if k in FILL:
            x = y = z = 99999.0
        lines.append(f"{t:%Y-%m-%d %H:%M:%S}.000 {t.dayofyear:03d}   {x:10.2f}{y:10.2f}{z:10.2f}{88888.0:10.2f}")
    return ("\n".join(lines) + "\n").encode("ascii")


class FakeGIN:
    def __init__(self):
        self.urls: list[str] = []
        self.offline = False

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if self.offline:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        return iaga_day(re.search(r"dataStartDate=([0-9-]+)", url).group(1))

    def days(self) -> list[str]:
        return [re.search(r"dataStartDate=([0-9-]+)", u).group(1) for u in self.urls]


GIN = FakeGIN()


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_observatory", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script, *args) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = script.main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def station(f: h5py.File):
    surveys = f["Experiment/Surveys"]
    assert len(surveys) == 1, list(surveys)
    stations = surveys[next(iter(surveys))]["Stations"]
    assert list(stations) == [CODE], list(stations)
    return stations[CODE]


def runs_of(st) -> list[str]:
    return sorted(k for k in st if k.startswith("sr"))


def utc(text: str) -> float:
    return pd.Timestamp(text).timestamp()


# ---------------------------------------------------------------------- (a)


def test_a_parse(tmp: Path) -> None:
    got = observatory.parse_iaga2002(iaga_day(DAY))
    k = np.array(ROWS)
    assert got["times"].dtype == np.int64 and np.array_equal(got["times"], T0 + k), got["times"][:3]
    x, y, z = xyz(k)
    nan = np.isin(k, list(FILL))
    for name, want in (("x", x), ("y", y), ("z", z)):
        v = got[name]
        assert np.array_equal(np.isnan(v), nan), (name, np.flatnonzero(np.isnan(v))[:5])
        assert np.max(np.abs(v[~nan] - want[~nan])) < 1e-9, name
    assert np.isnan(got["f"]).all(), "f should be NaN (88888.00) in every row"
    assert observatory.header_position(got["header"]) == (36.665, -5.942, 111.0), got["header"]
    print(f"  (a) {len(k)} rows, times T0+k, 30 NaN rows at k=300..329, f all NaN, "
          f"position {observatory.header_position(got['header'])}")


# ---------------------------------------------------------------------- (b), (c)


def test_bc_archive(tmp: Path) -> None:
    cache = tmp / "cache_bc"
    GIN.urls.clear()
    before = time.time()
    observatory.fetch_days(CODE, DAY, DAY, cache)
    after = time.time()
    got = observatory.load(CODE, DAY, DAY, cache, max_gap_s=600.0)
    x, y, z = xyz(np.arange(len(got["x"])))
    fill = np.arange(300, 330)
    for name, want in (("x", x), ("y", y), ("z", z)):
        assert np.max(np.abs(got[name][fill] - want[fill])) < 1e-9, (name, got[name][fill][:3])
        assert not np.isfinite(got[name][600:1800]).any(), f"{name}: the 20-minute gap was filled"
        assert not np.isfinite(got[name][2400:]).any(), f"{name}: the gap at the day's end was filled"
    assert not got["mask"][fill].any() and got["mask"][:300].all(), "mask: filled samples are not real data"

    archive = tmp / "bc" / "SFS.h5"
    summary = observatory.to_mth5(CODE, DAY, DAY, cache, archive, max_gap_s=600.0, survey="TEST")
    assert summary["path"] == archive
    with h5py.File(archive, "r") as f:
        st = station(f)
        names = runs_of(st)
        assert names == ["sr1_0001", "sr1_0002"], names
        for name, first in (("sr1_0001", 0), ("sr1_0002", 1800)):
            run = st[name]
            assert set(run) == {"hx", "hy", "hz"}, (name, list(run))  # (c) F dropped
            want = xyz(np.arange(first, first + 600))
            for comp, w in zip(("hx", "hy", "hz"), want):
                ds = run[comp]
                assert ds.shape == (600,), (name, comp, ds.shape)
                assert utc(ds.attrs["time_period.start"]) == T0 + first, (name, comp, ds.attrs["time_period.start"])
                assert np.max(np.abs(ds[()] - w)) < 1e-9, (name, comp)
                # (c) the channel
                assert float(ds.attrs["sample_rate"]) == 1.0 and ds.attrs["units"] == "nanoTesla", dict(ds.attrs)
                assert ds.attrs["filters"] == "[]", (name, comp, ds.attrs["filters"])
            assert float(run.attrs["sample_rate"]) == 1.0
            # (c) the provenance line
            comment = run.attrs["comments"]
            m = re.fullmatch(r"INTERMAGNET SFS one-second, best-available, XYZF, GIN (\S+), fetched (\S+)", comment)
            assert m, comment
            assert m.group(1) == GIN.urls[0], (m.group(1), GIN.urls)
            assert int(before) - 1 <= utc(m.group(2)) <= after + 1, (m.group(2), before, after)
        # (c) the station
        a = st.attrs
        assert (float(a["location.latitude"]), float(a["location.longitude"]), float(a["location.elevation"])) == \
            (36.665, -5.942, 111.0), {k: a[k] for k in a if k.startswith("location.")}
    print(f"  (b) 30 s gap filled on the line, 1200 s gap and the day's end left NaN; runs {names}: "
          f"600 s from 00:00:00 and 600 s from 00:30:00, hx hy hz = X Y Z")
    print(f"  (c) station SFS at 36.665, -5.942, 111.0 m; hx hy hz only, 1 Hz, nanoTesla, filters []; "
          f"comment {comment[:60]}...")


# ---------------------------------------------------------------------- (d)


def test_d_cache(tmp: Path, script) -> None:
    cache = tmp / "cache_d"
    GIN.urls.clear()
    observatory.fetch_days(CODE, "2023-09-20", "2023-09-21", cache)
    assert GIN.days() == ["2023-09-20", "2023-09-21"], GIN.days()
    held = snapshot(cache)
    assert len(held) == 2, list(held)
    GIN.urls.clear()
    paths = observatory.fetch_days(CODE, "2023-09-20", "2023-09-21", cache)
    assert GIN.urls == [], GIN.days()
    assert snapshot(cache) == held, "a cached day's file changed"
    assert [p.name for p in paths] == ["SFS_2023-09-20.sec.gz", "SFS_2023-09-21.sec.gz"], paths
    observatory.fetch_days(CODE, "2023-09-20", "2023-09-22", cache)
    assert GIN.days() == ["2023-09-22"], GIN.days()
    with gzip.open(paths[0], "rb") as g:
        assert g.read() == iaga_day("2023-09-20"), "the cache does not hold the served text"
    print(f"  (d) first call 2 requests, second 0 (bytes unchanged), 20..22 asked only for 2023-09-22")

    survey_yaml = write_survey(tmp / "survey_d", SITES)
    everything = snapshot(tmp)
    GIN.urls.clear()
    code, stdout, stderr = run(script, survey_yaml, CODE, "2023-09-20", "2023-09-23", "--cache", cache, "--dry-run")
    assert code == 0 and GIN.urls == [], (code, GIN.urls, stderr)
    assert snapshot(tmp) == everything, "--dry-run wrote something"
    assert "to fetch:  2023-09-23" in stdout and "2023-09-20 .. 2023-09-22 (3)" in stdout, stdout
    print(f"  (d) --dry-run: 0 requests, no file touched; {stdout.splitlines()[1].strip()!r}")

    GIN.offline = True
    try:
        code, stdout, stderr = run(script, survey_yaml, CODE, "2023-09-20", "2023-09-23", "--cache", cache)
    finally:
        GIN.offline = False
    lines = [ln for ln in stderr.splitlines() if ln.strip()]
    assert code == 1 and len(lines) == 1 and lines[0].startswith("ERROR") and "unreachable" in lines[0], (code, stderr)
    assert snapshot(tmp) == everything, "offline: the cache or another file changed"
    assert not (tmp / "survey_d" / "work" / "mth5").exists(), "offline: an archive was written"
    print(f"  (d) offline: exit 1, {lines[0][:90]!r}..., every file as it was, no archive")


# ---------------------------------------------------------------------- (e)

SITES = {
    "A01": {"latitude": 31.540402, "longitude": -9.686461, "elevation": 125.2, "serial": "14", "firmware": "2.1",
            "start": "2023-09-20T05:00:00Z", "end": "2023-09-20T18:00:00Z", "notes": "Sorrounded by houses :-("},
    "A02": {"dipole_length_ex": 42.0, "dipole_length_ey": 48.0, "latitude": 31.455528, "longitude": -9.776493,
            "start": "2023-09-20T09:00:00Z", "end": "2023-09-21T03:00:00Z"},
    "R05": {"latitude": 31.2, "longitude": -7.5, "start": "2023-09-20T12:00:00Z", "end": "2023-09-20T20:00:00Z",
            "notes": "recorded at 1 Hz, the survey is 1000 Hz"},
}
HEAD = """\
name: TEST_SURVEY
instrument: lemi423
sample_rate: 1000
data_root: {data_root}
# archives, transfer functions and figures: beside the raw data by default
workspace: {workspace}
timezone: Africa/Casablanca
generated_by: scripts/new_survey.py
defaults:
  dipole_length_ex: 50.0
  # the columns that had a sensor attached
  channels: [ex, ey, hx, hy]
processing:
  min_period: 0.005
"""


def write_survey(folder: Path, sites: dict) -> Path:
    """A survey.yaml written as scripts/new_survey.py writes one: HEAD, then the safe_dump sites block."""
    folder.mkdir(parents=True, exist_ok=True)
    head = HEAD.format(data_root=(folder / "raw").as_posix(), workspace=(folder / "work").as_posix())
    body = yaml.safe_dump(sites, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path = folder / "survey.yaml"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + "sites:\n" + indent(body, "  "))
    return path


def site_blocks(text: str) -> tuple[str, dict[str, str]]:
    """(the text above `sites:`, {site: its lines}) cut from the file's own text."""
    head, _, block = text.partition("\nsites:\n")
    out, name = {}, None
    for line in block.splitlines(keepends=True):
        m = re.match(r"^  (\S[^:]*):\s*$", line)
        if m:
            name = m.group(1)
            out[name] = ""
        out[name] += line
    return head, out


def test_e_survey_yaml(tmp: Path, script) -> None:
    survey_yaml = write_survey(tmp / "survey_e", SITES)
    text0 = survey_yaml.read_bytes().decode("utf-8")
    head0, blocks0 = site_blocks(text0)
    GIN.urls.clear()
    code, stdout, stderr = run(script, survey_yaml, "sfs")
    assert code == 0, (code, stdout, stderr)
    assert GIN.days() == ["2023-09-20", "2023-09-21"], GIN.days()
    text1 = survey_yaml.read_bytes().decode("utf-8")
    head1, blocks1 = site_blocks(text1)
    assert head1 == head0, "the text above sites: changed"
    for site in SITES:
        assert blocks1[site] == blocks0[site], (site, blocks0[site], blocks1[site])
    assert list(blocks1) == ["A01", "A02", "R05", "SFS"], list(blocks1)
    entry = yaml.safe_load(text1)["sites"]["SFS"]
    notes = entry.pop("notes")
    assert entry == {"instrument": "intermagnet", "channels": ["hx", "hy", "hz"], "latitude": 36.665,
                     "longitude": -5.942, "elevation": 111.0, "start": "2023-09-20T00:00:00Z",
                     "end": "2023-09-21T00:40:00Z"}, entry
    assert list(yaml.safe_load(text1)["sites"]["SFS"]) == ["instrument", "channels", "latitude", "longitude",
                                                          "elevation", "start", "end", "notes"]
    m = re.fullmatch(r"INTERMAGNET observatory, 1 s, fetched (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", notes)
    assert m and abs(utc(m.group(1)) - time.time()) < 120, notes
    archive = tmp / "survey_e" / "work" / "mth5" / "SFS.h5"
    with h5py.File(archive, "r") as f:
        assert runs_of(station(f)) == ["sr1_0001", "sr1_0002", "sr1_0003", "sr1_0004"], runs_of(station(f))
    print(f"  (e) SFS added after R05, the head and A01 A02 R05 byte-identical; {archive.name} with 4 runs")
    print("      " + "\n      ".join(blocks1["SFS"].rstrip().splitlines()))

    GIN.urls.clear()
    code, stdout, stderr = run(script, survey_yaml, "SFS")
    assert code == 0 and GIN.urls == [], (code, GIN.days(), stderr)
    assert survey_yaml.read_bytes().decode("utf-8") == text1, "a refresh from the cache changed survey.yaml"
    print("  (e) run again: 0 requests, survey.yaml byte-identical (refreshed from the cache)")

    clash = write_survey(tmp / "survey_clash", dict(SITES, SFS={"latitude": 31.0, "longitude": -8.0,
                                                               "start": "2023-09-20T00:00:00Z",
                                                               "end": "2023-09-20T12:00:00Z"}))
    before = clash.read_bytes()
    code, stdout, stderr = run(script, clash, "SFS", "2023-09-20", "2023-09-20")
    assert code == 2 and clash.read_bytes() == before, (code, stderr)
    print(f"  (e) a recorded site named SFS: exit 2, file unchanged ({stderr.strip()[:70]}...)")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    real, wait = observatory._http_get, observatory.RETRY_WAIT_S
    observatory._http_get, observatory.RETRY_WAIT_S = GIN, 0.0
    try:
        script = load_script()  # imports mth5, which adds its own loguru handler: quieten after it
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
        with tempfile.TemporaryDirectory(prefix="observatory_unit_") as name:
            tmp = Path(name)
            test_a_parse(tmp)
            test_bc_archive(tmp)
            test_d_cache(tmp, script)
            test_e_survey_yaml(tmp, script)
    finally:
        observatory._http_get, observatory.RETRY_WAIT_S = real, wait
    print(f"\nPASS  observatory_unit (a)-(e), GIN mocked, no network ({datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ})")
