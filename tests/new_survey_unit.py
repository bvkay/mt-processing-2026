"""Unit test for scripts/new_survey.py (no Qt).

    python tests/new_survey_unit.py

Part 1 builds a scratch data root by hand: two site folders of synthetic
LEMI-423 files -- a 1024-byte ASCII header laid out as mt-io's
`Read_Lemi_Header` documents it (serial, firmware, date, time, DDMM.MMMMM
latitude and longitude, altitude, calibration coefficients) followed by
2000 records of 30 bytes (the documented little-endian layout, the tick
counter running 0-999 twice, i.e. 2 s at 1000 Hz) -- plus a folder with no
B423 file. S02's files sit one folder down. **This test fails if**

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
    exactly the one asked for (channels, flip_reversed_dipoles true, h_scale
    -1000.0, calibration_fn sensors/l120n.rsp, 50 m dipoles, azimuths 0/90);
    the processing block differs; a site carries a dipole length or azimuth of
    its own (the defaults must apply until edited), or its notes are not the
    "set them from the field sheet" line; the coil response copied into
    sensors/ is not byte-identical to surveys/burra/sensors/l120n.rsp; or
    `Survey.site()` does not read serial/firmware/start/end back as strings
    and the dipole lengths as the defaults;
(5) a second run without --force does not refuse (exit 2) and leave the file
    byte-identical;
(6) --site-table with a CSV naming S01 (dipole_length_ex 48.5, azimuth_ex
    180) and a site that does not exist (X99) does not set exactly those two
    values on S01, leave S02 as it was, and print "1 of 2 sites matched".

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

from bbmt.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "new_survey.py"

# new_survey.py is not a package: load it in-process (the way
# tests/process_rr_cli_unit.py loads scripts/process_rr.py) to call
# `fast_sample_rate` directly rather than only through the subprocess.
_spec = importlib.util.spec_from_file_location("new_survey", SCRIPT)
new_survey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(new_survey)
SCRATCH = Path(
    r"C:\Users\joint\AppData\Local\Temp\claude\D--BEN-BBMT-Processing-2026"
    r"\7432a3ce-c47b-448e-8958-b1c946ec7c08\scratchpad\new_survey_unit"
)
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
    """Decimal degrees -> the header's DDMM.MMMMM,H (DDDMM for longitude)."""
    a = abs(value)
    degrees = int(a)
    return f"{degrees:0{width}d}{(a - degrees) * 60:08.5f},{hemispheres[value < 0]}"


def write_b423(path: Path, serial: int, firmware: str, lat: float, lon: float, alt: float,
               epoch: int, n: int = 2000) -> None:
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
    if root.exists():
        shutil.rmtree(root)
    for folder, sub, serial, fw, lat, lon, alt, epoch, spacing, n in SITES:
        for k in range(n):
            write_b423(root / folder / sub / f"{epoch + k * spacing}.B423", serial, fw, lat, lon, alt,
                       epoch + k * spacing)
    (root / "field_notes").mkdir()
    (root / "field_notes" / "sheet.txt").write_text("not a site\n")


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO,
                          capture_output=True, text=True)


def iso(epoch: int) -> str:
    return pd.Timestamp(epoch, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def part1() -> None:
    root, out = SCRATCH / "raw", SCRATCH / "synthetic" / "survey.yaml"
    build_data_root(root)

    # This test fails if fast_sample_rate does not read back exactly 1000.0
    # (the rate write_b423 wrote S01's records at above): a direct call, not
    # just the subprocess's sample_rate: 1000 line, so a bug that only shows
    # up when the scan runs in-process (as the GUI's dialog will, criterion
    # 22 of tests/gui_smoke.py) is still caught here.
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
    print(f"(4) sample_rate 1000, generated_by, defaults and processing blocks as asked, "
          f"coil response copied; Survey.site('S01') = serial {s01.serial!r}, start {s01.start!r}")

    before = out.read_bytes()
    again = run(root, "--name", "synthetic", "--out", out)
    assert again.returncode == 2 and out.read_bytes() == before, (again.returncode, again.stdout)
    print(f"(5) a second run without --force refused: {again.stdout.strip()}")

    table = SCRATCH / "two_rows.csv"
    # the table's elevation is 1000 m low on purpose (the Morocco CSV really
    # was): the header's GPS fix must win and the disagreement be printed
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


def test_one_hertz_file_is_one_hertz() -> None:
    """Fails if a faulty B423 file with one record per second and the millisecond
    tick always 0 (Morocco R05; the LEMI-423 has no 1 Hz mode) is snapped to a
    known rate instead of being reported as measured (1.0), or if a file at
    3 records per second is snapped instead of kept as 3.0."""
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


def part2() -> None:
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
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    part1()
    test_one_hertz_file_is_one_hertz()
    part2()
    print("\nPASS  new_survey_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
