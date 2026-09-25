# -*- coding: utf-8 -*-
"""
Unit test for scripts/new_survey.py

Runs without Qt, in three parts. Part 1 builds a scratch data root by hand:
two site folders of synthetic LEMI-423 files plus a folder with no B423
file. Each file is a 1024-byte ASCII header laid out as mt-io's
`Read_Lemi_Header` documents it (serial, firmware, date, time, DDMM.MMMMM
latitude and longitude, altitude, calibration coefficients) followed by 2000
records of 30 bytes (the documented little-endian layout, the tick counter
running 0-999 twice, i.e. 2 s at 1000 Hz). S02's files sit one folder down.

Usage:
    python tests/new_survey_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) the script exits non-zero, or the YAML does not list exactly S01 and S02
    (the folder without B423 files is not a site);
(2) either site's latitude or longitude differs by more than 1e-6 degree from
    the value encoded in its header here, its elevation from the header's, its
    serial from the header's "#NNNN" number as text ("36", "112"), or its
    firmware from the header's version ("2.1", "2.3");
(3) start/end are not the file-name epochs, first to last plus the median
    spacing, as UTC ISO text; sample_rate is not 1000 (the survey-wide value);
    or a direct call to `fast_sample_rate` on S01's first file (written at
    1000 Hz above) does not return exactly 1000.0 -- the bounded-read scan
    new_survey.py now uses in place of mt-io's whole-file `read_summary`;
(4) generated_by is not scripts/new_survey.py; the defaults block is not
    exactly the one asked for (channels [ex, ey, hx, hy] -- the LEMI-423's
    default preset, with no --channels given -- flip_reversed_dipoles true, h_scale
    -1000.0, calibration_fn sensors/l120n.rsp, 50 m dipoles, azimuths 0/90);
    the processing block differs; a site carries a dipole length or azimuth of
    its own (the defaults must apply until edited), or its notes are not the
    "set them from the field sheet" line; the coil response copied into
    sensors/ is not identical to surveys/burra/sensors/l120n.rsp; or
    `Survey.site()` does not read serial/firmware/start/end back as strings
    and the dipole lengths as the defaults; or the `workspace:` key (and
    `Survey.workspace`) is not `<data_root>/work`, or the script made that
    folder (it only writes the key: on a real survey it is the data drive);
(5) a second run without --force does not refuse (exit 2) and leave the file
    unchanged;
(6) --site-table with a CSV naming S01 (dipole_length_ex 48.5, azimuth_ex
    180) and a site that does not exist (X99) does not set exactly those two
    values on S01, leave S02 as it was, and print "1 of 2 sites matched";
(7) --workspace DIR (with --force) does not write `workspace:` DIR instead;
(8) the default run's summary does not print, on each site's line, the
    columns mt-io reads from the first file ("columns hx hy hz ex ey") next
    to the declared set ("declared ex ey hx hy"); or --channels "hx,hy"
    (with --force) does not write `defaults: channels: [hx, hy]`, print
    "declared hx hy" on both sites' lines and warn about no channel; or
    --channels "Bx By (magnetics only)" (a preset label) does not write
    [hx, hy] too;
(9) --channels "e1,e2,hx,hy" (LEMI-424 electrics on a LEMI-423 survey) does
    not warn, once per site, that e1 and e2 are not among the first file's
    columns -- or the run fails because of it (a declaration is the crew's
    word, only warned about).

Part 3, a mixed data root (`tests/instrument_samples.py`: S01 from part 1's
synthetic LEMI-423 writer beside one real hour of a LEMI-424, MBJ21, and of
an EDL, EGFLP02, cut into the scratch folder). **This test fails if**

(10) the default run (instrument auto) does not exit 0 and list exactly
     EGFLP02, MBJ21 and S01; the survey's `instrument:` is not lemi423 (one
     site each: the tie goes to the first of `INSTRUMENTS`) or its
     sample_rate not 1000 (the lemi423 sites' own); S01 carries an
     `instrument:` or `channels:` of its own; MBJ21 does not carry
     `instrument: lemi424` and `channels: [e1, e2, e3, e4, bx, by, bz]` (the
     LEMI-424 default preset), and EGFLP02 `instrument: edl` and
     `channels: [ex, ey, hx, hy, hz]`; `Survey.instrument_of` does not read
     the three back;
(11) MBJ21's serial and firmware are not "160" and "1.4" (the `.inf` says
     "%LEMI424 #0160", "%FIRMWARE Ver.1.4"), its latitude and longitude are
     more than 1e-4 degree (11 m: GPS jitter over the hour) from its first data line's DDMM.MMMMM fields
     decoded here (2800.28816 S, 12054.72277 E), or its span is not
     2024-10-25T00:00:00Z to 01:00:00Z (the last line, 00:59:59, plus one
     second); EGFLP02's span is not 2019-01-10T00:00:00Z to 01:00:00Z (the
     stamp plus 36000 samples at recorder.ini's 10 Hz), it has a latitude,
     or its notes do not say the files carry no position; or the summary
     lines do not read "1 Hz  lemi424  columns bx by bz e1 e2 e3 e4, declared
     e1 e2 e3 e4 bx by bz" and "10 Hz  edl  columns hx hy hz ex ey, declared
     ex ey hx hy hz";
(12) `--instrument edl` does not make edl the survey's (sample_rate 10) and
     give S01 `instrument: lemi423` with the LEMI-423 default [ex, ey, hx,
     hy] and MBJ21 its LEMI-424 set, EGFLP02 none of its own, with
     `defaults: sensor_type: bartington` (fluxgates at 10 Hz); or the default
     (lemi423) survey does not give EGFLP02 its own `sensor_type: bartington`;
(13) an EDL root whose recorder.ini says 1000 Hz (broadband LEMI-120
     coils) does not get `defaults: sensor_type: lemi120` (read back by
     `Survey.site`), or `--channels "Bx By Ex Ey"` there is not [ex, ey, hx, hy].
(14) the electric chain gain: over three EDL
     sites whose recorder.ini sets `channel_n_high_gain` to 1 on the channels
     its `channel_n_long_id` calls EX and EY (channels 0 and 1 here, so UoA's
     default order would name hx hy), to 0 on all five, and not at all, the
     run without --electric-gain does not leave `defaults:` with no
     `electric_gain` key at all, leave every site's own entry without one
     too, and print "ST91: recorder.ini sets channel_n_high_gain=1 for ex ey"
     informationally; `--electric-gain 10` does not write `defaults:
     electric_gain: 10.0` with no site's own entry given one, with
     `Survey.site` reading 10.0 back for all three sites; or a non-numeric
     value, or the flag over part 1's LEMI-423-only root, does not stop the
     script (exit 2) before it writes anything.

Part 2, the real-data check: the script run over the Curnamona Cube raw data
(E:, read only) into the scratch folder must give D02 and E08 latitudes and
longitudes within 0.001 degree of surveys/curnamona_cube/survey.yaml (the
field spreadsheet's numbers, written by a different script; they agree with
the headers to the sixth decimal, so the spreadsheet was filled from the same
GPS: this checks the DDMM.MMMMM parse and the folder-to-site mapping, not the
GPS itself), D02's start at its first file's epoch 1624949744
(2021-06-29T06:55:44Z, read off the file listing), and sample_rate 1000.
Skipped with a printed reason when E: is not mounted.
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

from crust.survey import Survey  # noqa: E402

from _scratch import scratch_dir

SCRIPT = REPO / "scripts" / "new_survey.py"

# new_survey.py is not a package: load it in-process (the way
# tests/process_rr_cli_unit.py loads scripts/process_rr.py) to call
# `fast_sample_rate` directly rather than only through the subprocess.
_spec = importlib.util.spec_from_file_location("new_survey", SCRIPT)
new_survey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(new_survey)
SCRATCH = scratch_dir("new_survey_unit")
CURNAMONA_RAW = Path(r"E:\MT_Timeseries_DATA\MT_Curnamona_Cube_MT")
CURNAMONA_YAML = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
RSP = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
NOTE = "dipole lengths and azimuths from defaults - set them from the field sheet"

# the documented 30-byte record, written out here rather than taken from mt-io
RECORD = np.dtype([("time", "<u4"), ("tick", "<u2"), ("Bx", "<i4"), ("By", "<i4"), ("Bz", "<i4"),
                   ("Ex", "<i4"), ("Ey", "<i4"), ("sync", "<i1"), ("stage", "<u1"), ("CRC", "<i2")])
assert RECORD.itemsize == 30

# (folder, subfolder, serial, firmware, lat, lon, alt, first epoch, spacing s, n files)
SITES = [
    ("S01", "", 36, "2.1", -31.123456, 138.654321, 123.4, 1624949744, 5400, 3),
    ("S02", "day1", 112, "2.3", -31.2, 138.75, 250.0, 1625000000, 3600, 2),
]
EXPECTED_DEFAULTS = {
    "dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "azimuth_ex": 0.0, "azimuth_ey": 90.0,
    "calibration_fn": "sensors/l120n.rsp", "h_scale": -1000.0, "flip_reversed_dipoles": True,
    "channels": ["ex", "ey", "hx", "hy"],
}
EXPECTED_PROCESSING = {"min_period": 0.005, "max_period": 5000.0, "periods_per_decade": 10.0,
                       "notch_frequencies": [50.0, 150.0]}


def ddmm(value: float, width: int, hemispheres: str) -> str:
    """Format decimal degrees as the header's DDMM.MMMMM,H (DDDMM for longitude)."""
    a = abs(value)
    degrees = int(a)
    return f"{degrees:0{width}d}{(a - degrees) * 60:08.5f},{hemispheres[value < 0]}"


def write_b423(path: Path, serial: int, firmware: str, lat: float, lon: float, alt: float,
               epoch: int, n: int = 2000) -> None:
    """Write a synthetic B423 file at 1000 Hz.

    Args:
        path (Path): File to write; its folders are created.
        serial (int): Logger serial number.
        firmware (str): Firmware version, e.g. "2.1".
        lat (float): Latitude in decimal degrees.
        lon (float): Longitude in decimal degrees.
        alt (float): Altitude in m.
        epoch (int): Start epoch in seconds.
        n (int): Number of records.
    """
    when = pd.Timestamp(epoch, unit="s", tz="UTC")
    lines = [f"%LEMI423 #{serial:04d}", f"%FIRMWARE Ver.{firmware}", "%MADE in UKRAINE", " ",
             f"%Date {when:%Y/%m/%d}", f"%Time {when:%H:%M:%S}", "%Ubat 13.16V", "%Current 101.7mA",
             "%Free 30424MB", f"%Lat {ddmm(lat, 2, 'NS')}", f"%Lon {ddmm(lon, 3, 'EW')}",
             f"%Alt {alt:.1f},m 12 2", " ",
             "%Kmx = 2.909985e-06", "%Kmy = 2.909481e-06", "%Kmz = 2.908610e-06",
             "%Ax = -5.002100e+01", "%Ay = -4.990500e+01", "%Az = -4.994700e+01",
             "%Ke1 = 2.910737e-04", "%Ke2 = 2.909547e-04", "%Ae1 = -5.004800e+03", "%Ae2 = -4.958000e+03"]
    header = ("\r\n".join(lines) + "\r\n").encode("ascii").ljust(1024, b" ")
    assert len(header) == 1024
    records = np.zeros(n, dtype=RECORD)
    records["time"] = epoch + np.arange(n) // 1000
    records["tick"] = np.arange(n) % 1000
    records["Ex"] = np.arange(n)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + records.tobytes())


def build_data_root(root: Path) -> None:
    """Rebuild part 1's data root: the SITES folders and a folder without B423 files."""
    if root.exists():
        shutil.rmtree(root)
    for folder, sub, serial, fw, lat, lon, alt, epoch, spacing, n in SITES:
        for k in range(n):
            write_b423(root / folder / sub / f"{epoch + k * spacing}.B423", serial, fw, lat, lon, alt,
                       epoch + k * spacing)
    (root / "field_notes").mkdir()
    (root / "field_notes" / "sheet.txt").write_text("not a site\n")


def run(*args) -> subprocess.CompletedProcess:
    """Run scripts/new_survey.py with `args`, output captured."""
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO,
                          capture_output=True, text=True)


def iso(epoch: int) -> str:
    """Format an epoch as ISO UTC text."""
    return pd.Timestamp(epoch, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def part1() -> None:
    """Run part 1's checks (1)-(9) on the synthetic data root."""
    root, out = SCRATCH / "raw", SCRATCH / "synthetic" / "survey.yaml"
    build_data_root(root)

    # This test fails if fast_sample_rate does not read back exactly 1000.0
    # (the rate write_b423 wrote S01's records at above). The direct call
    # complements the subprocess's sample_rate: 1000 line, so a bug that shows
    # up when the scan runs in-process (as in the GUI's dialog, criterion 22
    # of tests/gui_smoke.py) is caught here too.
    s01_first = sorted((root / "S01").glob("*.B423"), key=lambda p: int(p.stem))[0]
    derived = new_survey.fast_sample_rate(s01_first)
    assert derived == 1000.0, f"fast_sample_rate({s01_first.name}) = {derived}, wanted 1000.0"
    print(f"(3) fast_sample_rate direct call: {s01_first.name} -> {derived} Hz")

    if out.parent.exists():
        shutil.rmtree(out.parent)
    done = run(root, "--name", "synthetic", "--out", out)
    print(done.stdout.strip())
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    sites = config["sites"]
    assert list(sites) == ["S01", "S02"], list(sites)
    print(f"(1) wrote {out}: sites {list(sites)}")

    for folder, _sub, serial, fw, lat, lon, alt, epoch, spacing, n in SITES:
        e = sites[folder]
        assert abs(e["latitude"] - lat) <= 1e-6 and abs(e["longitude"] - lon) <= 1e-6, (folder, e)
        assert e["elevation"] == alt, (folder, e["elevation"], alt)
        assert e["serial"] == str(serial) and e["firmware"] == fw, (folder, e["serial"], e["firmware"])
        assert e["start"] == iso(epoch) and e["end"] == iso(epoch + n * spacing), (folder, e["start"], e["end"])
        assert not set(e) & set(EXPECTED_DEFAULTS), f"{folder} carries its own {set(e) & set(EXPECTED_DEFAULTS)}"
        assert e["notes"] == NOTE, e["notes"]
        print(f"(2)(3) {folder}: {e['latitude']} {e['longitude']} {e['elevation']} m, serial "
              f"{e['serial']}, firmware {e['firmware']}, {e['start']} to {e['end']}")
    assert config["sample_rate"] == 1000, config["sample_rate"]
    assert config["generated_by"] == "scripts/new_survey.py", config.get("generated_by")
    assert config["defaults"] == EXPECTED_DEFAULTS, config["defaults"]
    assert config["processing"] == EXPECTED_PROCESSING, config["processing"]
    assert config["timezone"] == "Australia/Adelaide" and Path(config["data_root"]) == root.resolve()
    assert (out.parent / "sensors" / "l120n.rsp").read_bytes() == RSP.read_bytes()
    survey = Survey.from_yaml(out)
    s01 = survey.site("S01")
    assert survey.generated_by == "scripts/new_survey.py"
    assert all(isinstance(v, str) for v in (s01.serial, s01.firmware, s01.start, s01.end)), s01
    assert (s01.dipole_length_ex, s01.azimuth_ey) == (50.0, 90.0), s01
    assert list(survey.site_dirs()) == ["S01", "S02"]
    assert Path(config["workspace"]) == root.resolve() / "work" == survey.workspace, config["workspace"]
    assert not (root / "work").exists(), "new_survey.py made the workspace folder"
    print(f"(4) sample_rate 1000, generated_by, defaults and processing blocks as asked, "
          f"coil response copied; Survey.site('S01') = serial {s01.serial!r}, start {s01.start!r}; "
          f"workspace {config['workspace']} (<data_root>/work, not made)")

    before = out.read_bytes()
    again = run(root, "--name", "synthetic", "--out", out)
    assert again.returncode == 2 and out.read_bytes() == before, (again.returncode, again.stdout)
    print(f"(5) a second run without --force refused: {again.stdout.strip()}")

    table = SCRATCH / "two_rows.csv"
    # the table's elevation is 1000 m low on purpose (as a hand-typed table can
    # be): the header's GPS fix must win and the disagreement be printed
    low = float(sites["S01"]["elevation"]) - 1000.0
    table.write_text(f"site,dipole_length_ex,azimuth_ex,elevation\nS01,48.5,180,{low}\nX99,10,0,\n", encoding="utf-8")
    merged = run(root, "--name", "synthetic", "--out", out, "--site-table", table, "--force")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert "1 of 2 sites matched" in merged.stdout, merged.stdout
    assert "S01 elevation: table" in merged.stdout and "header kept" in merged.stdout, merged.stdout
    after = yaml.safe_load(out.read_text(encoding="utf-8"))["sites"]
    changed = {k: v for k, v in after["S01"].items() if sites["S01"].get(k) != v}
    assert changed == {"dipole_length_ex": 48.5, "azimuth_ex": 180.0}, changed
    assert after["S01"]["elevation"] == sites["S01"]["elevation"], after["S01"]["elevation"]
    assert after["S02"] == sites["S02"], after["S02"]
    print(f"(6) --site-table: S01 changed {changed}, its elevation kept from the header, S02 untouched")

    elsewhere = SCRATCH / "elsewhere"
    moved = run(root, "--name", "synthetic", "--out", out, "--workspace", elsewhere, "--force")
    assert moved.returncode == 0, moved.stdout + moved.stderr
    got = yaml.safe_load(out.read_text(encoding="utf-8"))["workspace"]
    assert Path(got) == elsewhere.resolve(), got
    print(f"(7) --workspace {elsewhere}: workspace {got}")

    for site in ("S01", "S02"):
        line = next(ln for ln in done.stdout.splitlines() if ln.strip().startswith(site))
        assert line.endswith("columns hx hy hz ex ey, declared ex ey hx hy"), line
    for arg in ("hx,hy", "Bx By (magnetics only)"):
        mag = run(root, "--name", "synthetic", "--out", out, "--channels", arg, "--force")
        assert mag.returncode == 0, mag.stdout + mag.stderr
        got = yaml.safe_load(out.read_text(encoding="utf-8"))["defaults"]["channels"]
        assert got == ["hx", "hy"], (arg, got)
        lines = [ln for ln in mag.stdout.splitlines() if ln.strip().startswith(("S01", "S02"))]
        assert len(lines) == 2 and all(ln.endswith("declared hx hy") for ln in lines), lines
        assert "not among" not in mag.stdout, mag.stdout
        print(f"(8) --channels {arg!r}: defaults channels {got}; S01 {lines[0][lines[0].index('columns'):]}")

    odd = run(root, "--name", "synthetic", "--out", out, "--channels", "e1,e2,hx,hy", "--force")
    assert odd.returncode == 0, odd.stdout + odd.stderr
    warned = [ln.strip() for ln in odd.stdout.splitlines() if "not among the first file's columns" in ln]
    assert [w.split(":")[0] for w in warned] == ["WARNING S01", "WARNING S02"], warned
    assert all("declared channel(s) e1 e2 not among" in w for w in warned), warned
    print(f"(9) --channels e1,e2,hx,hy: {warned[0]}")


def test_one_hertz_file_is_one_hertz() -> None:
    """Check that fast_sample_rate reports an unknown rate as measured.

    Fails if a faulty B423 file with one record per second and the
    millisecond tick always 0 (the LEMI-423 has no 1 Hz mode)
    is snapped to a known rate instead of being reported as measured (1.0),
    or if a file at 3 records per second is snapped instead of kept as 3.0.
    """
    import importlib.util, tempfile
    import numpy as np
    spec = importlib.util.spec_from_file_location("new_survey", REPO / "scripts" / "new_survey.py")
    ns = importlib.util.module_from_spec(spec); spec.loader.exec_module(ns)
    from mt_io.lemi.lemi423 import Read_Lemi_Data
    record = np.dtype(Read_Lemi_Data.binary_format) if not isinstance(Read_Lemi_Data.binary_format, np.dtype) else Read_Lemi_Data.binary_format
    with tempfile.TemporaryDirectory() as tmp:
        for name, per_second, expect in (("one_hz.B423", 1, 1.0), ("three_hz.B423", 3, 3.0)):
            n = 300
            arr = np.zeros(n, dtype=record)
            arr["time"] = 1689066308 + np.arange(n) // per_second
            arr["tick"] = (np.arange(n) % per_second) * (1000 // per_second)
            path = Path(tmp) / name
            path.write_bytes(bytes(1024) + arr.tobytes())
            got = ns.fast_sample_rate(path)
            assert got == expect, (name, got)
    print("  faulty 1 record/s reported as 1.0, 3 records/s as 3.0: never snapped to a LEMI rate")


def dd(ddmm: str, hemisphere: str) -> float:
    """Decode DDDMM.MMMMM + hemisphere to signed decimal degrees, independently of mt-io."""
    value = float(ddmm)
    degrees = int(value // 100)
    return (degrees + (value - 100 * degrees) / 60.0) * (-1 if hemisphere in "SW" else 1)


def part3() -> None:
    """Run part 3's checks (10)-(12) on the mixed data root of tests/instrument_samples.py."""
    sys.path.insert(0, str(REPO / "tests"))
    import instrument_samples as samples

    done = samples.mixed_survey()
    print(done.stdout.strip())
    assert done.returncode == 0, done.stdout + done.stderr
    config = yaml.safe_load(samples.MIXED_YAML.read_text(encoding="utf-8"))
    sites = config["sites"]
    assert list(sites) == ["EGFLP02", "MBJ21", "S01"], list(sites)
    assert config["instrument"] == "lemi423" and config["sample_rate"] == 1000, (config["instrument"], config["sample_rate"])
    assert not {"instrument", "channels"} & set(sites["S01"]), sites["S01"]
    assert sites["MBJ21"]["instrument"] == "lemi424", sites["MBJ21"]
    assert sites["MBJ21"]["channels"] == ["e1", "e2", "e3", "e4", "bx", "by", "bz"], sites["MBJ21"]["channels"]
    assert sites["EGFLP02"]["instrument"] == "edl" and sites["EGFLP02"]["channels"] == ["ex", "ey", "hx", "hy", "hz"]
    survey = Survey.from_yaml(samples.MIXED_YAML)
    got = {site: survey.instrument_of(site) for site in sites}
    assert got == {"EGFLP02": "edl", "MBJ21": "lemi424", "S01": "lemi423"}, got
    print(f"(10) auto: instrument lemi423 (a one-each tie), sample_rate 1000; instruments {got}; "
          f"MBJ21 channels {sites['MBJ21']['channels']}, EGFLP02 {sites['EGFLP02']['channels']}")

    first = (samples.MIXED_ROOT / "MBJ21" / samples.LEMI424_FILE).read_text().split("\n", 1)[0].split()
    lat, lon = dd(first[17], first[18]), dd(first[19], first[20])
    m = sites["MBJ21"]
    assert (m["serial"], m["firmware"]) == ("160", "1.4"), (m["serial"], m["firmware"])
    assert abs(m["latitude"] - lat) <= 1e-4 and abs(m["longitude"] - lon) <= 1e-4, (m["latitude"], lat, m["longitude"], lon)
    assert (m["start"], m["end"]) == ("2024-10-25T00:00:00Z", "2024-10-25T01:00:00Z"), (m["start"], m["end"])
    e = sites["EGFLP02"]
    assert (e["start"], e["end"]) == ("2019-01-10T00:00:00Z", "2019-01-10T01:00:00Z"), (e["start"], e["end"])
    assert "latitude" not in e and "carry no position" in e["notes"], e
    lines = {ln.split()[0]: ln for ln in done.stdout.splitlines() if ln.strip().startswith(("MBJ21", "EGFLP02"))}
    assert lines["MBJ21"].endswith("1 Hz  lemi424  columns bx by bz e1 e2 e3 e4, declared e1 e2 e3 e4 bx by bz"), lines
    assert lines["EGFLP02"].endswith("10 Hz  edl  columns hx hy hz ex ey, declared ex ey hx hy hz"), lines
    print(f"(11) MBJ21 serial {m['serial']} firmware {m['firmware']}, {m['latitude']} {m['longitude']} "
          f"(the line says {lat:.6f} {lon:.6f}), {m['start']} to {m['end']}; EGFLP02 {e['start']} to {e['end']}, "
          f"no position")

    edl = samples.mixed_survey("--instrument", "edl")
    assert edl.returncode == 0, edl.stdout + edl.stderr
    config = yaml.safe_load(samples.MIXED_YAML.read_text(encoding="utf-8"))
    sites = config["sites"]
    assert config["instrument"] == "edl" and config["sample_rate"] == 10, (config["instrument"], config["sample_rate"])
    assert config["defaults"]["channels"] == ["ex", "ey", "hx", "hy", "hz"], config["defaults"]["channels"]
    assert (sites["S01"]["instrument"], sites["S01"]["channels"]) == ("lemi423", ["ex", "ey", "hx", "hy"]), sites["S01"]
    assert sites["MBJ21"]["instrument"] == "lemi424" and not {"instrument", "channels"} & set(sites["EGFLP02"])
    assert config["defaults"]["sensor_type"] == "bartington", config["defaults"]
    print("(12) --instrument edl: survey edl at 10 Hz, defaults sensor_type bartington; S01 lemi423 "
          "[ex, ey, hx, hy], MBJ21 lemi424, EGFLP02 the default")
    again = samples.mixed_survey()  # leave the default survey behind for tests/gui_smoke.py
    assert again.returncode == 0, again.stdout + again.stderr
    mixed = yaml.safe_load(samples.MIXED_YAML.read_text(encoding="utf-8"))
    assert mixed["sites"]["EGFLP02"]["sensor_type"] == "bartington" and "sensor_type" not in mixed["defaults"], mixed


def test_edl_broadband_sensor_type() -> None:
    """Run check (13): an EDL root at 1000 Hz gets the LEMI-120 coils.

    Fails if an EDL data root whose recorder.ini says 1000 Hz (LEMI-120
    coils on the PR6-24) does not get `defaults: sensor_type:
    lemi120`, or `Survey.site(...).sensor_type` does not read it back, so
    that ingest reads the coils with their response rather than the fluxgate
    gain.
    """
    root = SCRATCH / "edl_broadband"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "hs999"
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=1000\n" for n in range(5)), encoding="utf-8")
    for stamp in ("120327050500", "120327051000"):
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            (site / f"HS999_{stamp}.{suffix}").write_text("1\n" * 300, encoding="ascii")
    out = root / "survey.yaml"
    done = run(root / "raw", "--name", "edl_bb", "--out", out, "--channels", "Bx By Ex Ey")
    assert done.returncode == 0, done.stdout + done.stderr
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert config["instrument"] == "edl" and config["sample_rate"] == 1000, config
    assert config["defaults"]["sensor_type"] == "lemi120", config["defaults"]
    assert config["defaults"]["channels"] == ["ex", "ey", "hx", "hy"], config["defaults"]["channels"]
    assert Survey.from_yaml(out).site("hs999").sensor_type == "lemi120"
    assert "EDL magnetic sensors (defaults: sensor_type): lemi120" in done.stdout, done.stdout
    print("(13) EDL at 1000 Hz: defaults sensor_type lemi120, channels 'Bx By Ex Ey' -> [ex, ey, hx, hy]")


def test_edl_electric_gain() -> None:
    """Run check (14): the declared electric chain gain.

    Fails if new_survey.py does not write the declared electric chain gain as
    asked (`--electric-gain`), leave it unwritten and note recorder.ini's own
    flags for information when it is not given, or accepts a non-numeric
    value or a root with no EDL site.
    """
    root = SCRATCH / "edl_electric_gain"
    shutil.rmtree(root, ignore_errors=True)
    # channels 0 and 1 are EX and EY here: the flags are read through the long ids, not an assumed order
    ids = ("EX", "EY", "BX", "BY", "BZ")
    ini = ("[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5))
           + "".join(f"channel_{n}_long_id={c}\n" for n, c in enumerate(ids)))
    flags = {"ST91": (1, 1, 0, 0, 0), "ST92": (0, 0, 0, 0, 0), "ST93": None}
    for site, gains in flags.items():
        folder = root / "raw" / site
        (folder / "config").mkdir(parents=True)
        extra = "" if gains is None else "".join(f"channel_{n}_high_gain={g}\n" for n, g in enumerate(gains))
        (folder / "config" / "recorder.ini").write_text(ini + extra, encoding="utf-8")
        for stamp in ("090320000000", "090320010000"):
            for suffix in ("BX", "BY", "BZ", "EX", "EY"):
                (folder / f"{site}_{stamp}.{suffix}").write_text("1\n" * 300, encoding="ascii")
    out = root / "survey.yaml"
    done = run(root / "raw", "--name", "edl_gain", "--out", out)
    assert done.returncode == 0, done.stdout + done.stderr
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "electric_gain" not in config["defaults"], config["defaults"]
    own = {s: config["sites"][s].get("electric_gain") for s in flags}
    assert own == {"ST91": None, "ST92": None, "ST93": None}, own
    assert "ST91: recorder.ini sets channel_n_high_gain=1 for ex ey" in done.stdout, done.stdout
    done = run(root / "raw", "--name", "edl_gain", "--out", out, "--electric-gain", "10", "--force")
    assert done.returncode == 0, done.stdout + done.stderr
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert config["defaults"]["electric_gain"] == 10.0, config["defaults"]
    own = {s: config["sites"][s].get("electric_gain") for s in flags}
    assert own == {"ST91": None, "ST92": None, "ST93": None}, own
    survey = Survey.from_yaml(out)
    resolved = {s: survey.site(s).electric_gain for s in flags}
    assert resolved == {"ST91": 10.0, "ST92": 10.0, "ST93": 10.0}, resolved
    before = out.read_bytes()
    for args in ((root / "raw", "--electric-gain", "abc"), (SCRATCH / "raw", "--electric-gain", "10")):
        bad = run(args[0], "--name", "edl_gain", "--out", out, "--force", *args[1:])
        assert bad.returncode == 2, (args, bad.returncode, bad.stdout, bad.stderr)
    assert out.read_bytes() == before, "a refused run wrote survey.yaml"
    print(f"(14) electric gain: no flag -> no defaults key, no site key, recorder.ini noted "
          f"informationally; '10' -> defaults 10.0, no site key, resolved {resolved}; 'abc' and a "
          f"LEMI-423-only root refused (exit 2), nothing written")


def part2() -> None:
    """Run part 2, the real-data check on the Curnamona Cube raw data; skipped when E: is not mounted."""
    if not CURNAMONA_RAW.is_dir():
        print(f"real-data check SKIPPED: {CURNAMONA_RAW} is not mounted")
        return
    out = SCRATCH / "curnamona_new" / "survey.yaml"
    if out.parent.exists():
        shutil.rmtree(out.parent)
    done = run(CURNAMONA_RAW, "--name", "curnamona_new", "--out", out)
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    got = yaml.safe_load(out.read_text(encoding="utf-8"))
    declared = yaml.safe_load(CURNAMONA_YAML.read_text(encoding="utf-8"))["sites"]
    print(f"real data: {len(got['sites'])} sites from {CURNAMONA_RAW}, sample_rate {got['sample_rate']}")
    assert got["sample_rate"] == 1000, got["sample_rate"]
    for site in ("D02", "E08"):
        g, d = got["sites"][site], declared[site]
        dlat, dlon = abs(g["latitude"] - d["latitude"]), abs(g["longitude"] - d["longitude"])
        print(f"  {site}: header {g['latitude']:.6f} {g['longitude']:.6f}, survey.yaml "
              f"{d['latitude']:.6f} {d['longitude']:.6f}: differ by {dlat:.6f}, {dlon:.6f} deg")
        assert dlat <= 0.001 and dlon <= 0.001, f"{site} is {dlat:.6f}/{dlon:.6f} deg from survey.yaml"
    assert got["sites"]["D02"]["start"] == "2021-06-29T06:55:44Z", got["sites"]["D02"]["start"]


def main() -> int:
    """Run parts 1, 3 and 2 in that order and return 0."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    part1()
    test_one_hertz_file_is_one_hertz()
    print()
    print(__doc__.split("**This test fails if**")[2].split("Part 2, the real-data check:")[0].strip())
    print()
    part3()
    test_edl_broadband_sensor_type()
    test_edl_electric_gain()
    part2()
    print("\nPASS  new_survey_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
