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
    1000 Hz above) does not return exactly 1000.0 (the bounded-read scan
    new_survey.py uses in place of mt-io's whole-file `read_summary`);
(4) generated_by is not scripts/new_survey.py; the defaults block is not
    exactly the one asked for (channels [ex, ey, hx, hy], the LEMI-423's
    default preset, with no --channels given; flip_reversed_dipoles true, h_scale
    -1000.0, calibration_fn sensors/l120n.rsp, 50 m dipoles, azimuths 0/90);
    the processing block differs; a site carries a dipole length or azimuth of
    its own (the defaults must apply until edited), or its notes are not the
    "set them from the field sheet" line; the coil response copied into
    sensors/ is not identical to surveys/burra/sensors/l120n.rsp; or
    `Survey.site()` does not read serial/firmware/start/end back as strings
    and the dipole lengths as the defaults; or the `workspace:` key (and
    `Survey.workspace`) is not `<data_root>/work`, or the script made that
    folder (it only writes the key: on a real survey it is the data drive);
(5) a second run with the same folders exits other than 0, does not say
    "nothing to add: every site folder has an entry", changes a byte of the
    file, makes survey.yaml.previous, or prints an "ignored on a re-run"
    line;
(6) a first run with --site-table and a CSV naming S01 (dipole_length_ex
    48.5, azimuth_ex 180) and a site that does not exist (X99) does not set
    exactly those two values on S01, leave S02 as it was, and print "1 of 2
    sites matched";
(7) --workspace DIR does not write `workspace:` DIR instead;
(8) the default run's summary does not print, on each site's line, the
    columns mt-io reads from the first file ("columns hx hy hz ex ey") next
    to the declared set ("declared ex ey hx hy"); or --channels "hx,hy"
    does not write `defaults: channels: [hx, hy]`, print
    "declared hx hy" on both sites' lines and warn about no channel; or
    --channels "Bx By (magnetics only)" (a preset label) does not write
    [hx, hy] too;
(9) --channels "e1,e2,hx,hy" (LEMI-424 electrics on a LEMI-423 survey) does
    not warn, once per site, that e1 and e2 are not among the first file's
    columns, or the run fails because of it (a declaration is only warned
    about).

Part 3, a mixed data root (`tests/instrument_samples.py`: S01 from part 1's
synthetic LEMI-423 writer beside one real hour of a LEMI-424, MBJ21, and of
an EDL, EGFLP02, cut into the scratch folder). **This test fails if**

(10) the default run (instrument auto) does not exit 0 and list exactly
     EGFLP02, MBJ21 and S01; the survey's `instrument:` is not lemi423 (one
     site each: the tie goes to the first of `INSTRUMENTS`) or its
     sample_rate not 1000 (the lemi423 sites' own); S01 carries an
     `instrument:` or `channels:` of its own; MBJ21 does not carry
     `instrument: lemi424` and `channels: [ex, ey, e3, e4, hx, hy, hz]` (the
     LEMI-424 default preset, in the stored names), and EGFLP02 `instrument: edl` and
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
     lines do not read "1 Hz  lemi424  columns hx hy hz ex ey e3 e4, declared
     ex ey e3 e4 hx hy hz" and "10 Hz  edl  columns hx hy hz ex ey, declared
     ex ey hx hy hz"; or the default (lemi423) survey's `defaults:` holds
     an `e_sign` key;
(12) `--instrument edl` does not make edl the survey's (sample_rate 10) and
     give S01 `instrument: lemi423` with the LEMI-423 default [ex, ey, hx,
     hy] and MBJ21 its LEMI-424 set, EGFLP02 none of its own, with
     `defaults: sensor_type: bartington` (fluxgates at 10 Hz); or the default
     (lemi423) survey does not give EGFLP02 its own `sensor_type: bartington`;
     `--instrument lemi424` does not write `defaults: e_sign: -1.0` with the
     comment line "# LEMI-424 sites: E1 and E2 are recorded with the
     opposite sign ..." right above it and `defaults: channels` [ex, ey, e3,
     e4, hx, hy, hz], or `Survey.site("MBJ21").e_sign` does not read -1.0
     back;
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
     value, or the flag over part 1's LEMI-423-only root, each run into a
     survey.yaml that does not exist, does not stop the script with exit 2
     and a message that names the electric gain, with no file written.

Part 4, the name of a new survey and the second run over a survey.yaml that
exists (a re-run), on data roots built as part 1's. **This test fails if**

(15) at a first run a name of 31 characters, a name with a space or a name
     with an accent is not refused with exit 2 and a message that says what
     to choose, over a data root with no site folder (where a name read
     after the folders would exit 1), or the refused run makes the folder of
     the survey.yaml; a name of 30 characters is refused; or
     `check_survey_name` accepts an empty name, a dot, a slash or a space,
     or refuses letters, digits, "_" and "-";
(16) after a first run with `--timezone Australia/Perth`, a comment line and
     a key (`rot_h: 3.0` on S01) typed into the file and a folder S03 put
     under the data root, a re-run with no head argument does not exit 0,
     insert the entry of S03 (its position, serial, firmware and span as
     its files give them) as one run of lines after the last entry with
     every other line as it was, keep the file before it as
     survey.yaml.previous, print "added 1 site(s): S03; left as they are: 2
     site(s) with an entry", or it prints an "ignored on a re-run" line;
(17) a re-run with `--timezone Australia/Adelaide`, which differs from the
     file, does not print the one line "ignored on a re-run: --timezone
     Australia/Adelaide (survey.yaml keeps timezone: Australia/Perth)" and
     leave every byte; or `--timezone Australia/Perth`, equal to the file,
     prints such a line;
(18) `--force`, on the survey.yaml that exists and on one that does not, does
     not exit 2 with the message that says to delete the file by hand, the
     file unchanged or not made;
(19) a re-run with another data root, or another `--name`, is not refused
     with exit 2, a message that names the folder or the name the file
     holds, and the file unchanged;
(20) on a file whose `name:` has 33 characters (typed in by hand, as two
     surveys made before the name check have), a re-run with that name does
     not add the folder S04; or its row of the `--site-table` given
     (dipole_length_ex 46) is not in the new entry;
(21) a re-run with `--site-table` does not change the sites that have an
     entry in place: S01's row (dipole_length_ex 48.5, azimuth_ex 0, which
     equals `defaults:`, a latitude 0.01 deg off the header's) must add the
     one line `dipole_length_ex: 48.5` to S01's entry, write no azimuth_ex,
     keep the latitude and print the disagreement, S03's row must add
     `dipole_length_ey: 47.0`, every other line and the typed comment must
     stay, and the output must name both sites with the values changed and
     "left as they are: 2 site(s)"; or the same table run again changes a
     byte or does not say that the two sites already read as the table;
(22) a first run with `--dipole-length 45 --azimuths 10 100` does not write
     `defaults:` dipole lengths 45/45 and azimuths 10/100 with every other
     key of `defaults:` as in (4), read back by `Survey.site`; a re-run with
     `--dipole-length 50 --azimuths 0 90` does not print one "ignored on a
     re-run" line for each, naming 45.0 and "10.0 and 100.0" as what
     `defaults:` keeps, and leave every byte; a re-run with the file's own
     values prints such a line; or the help text does not say that the
     azimuths are from magnetic north;
(23) at a first run a site with a position and a span does not get
     `declination`, `declination_model` and `declination_epoch`: the model
     an IGRF, the epoch the decimal year of the middle of its span to 2
     decimals (worked out here), the declination to 2 decimals between 6.5
     and 9.0 degrees east (the Flinders Ranges in 2021, about 7.3); or S03,
     added by a re-run, does not get its three keys;
(24) the fill of the declination changes anything else: for every site,
     `Survey.site` read from the file and from the same file with the three
     declination keys taken out of every entry must differ in those three
     fields only; no entry may hold an azimuth, a rotation key or
     `layout_north`, every site must read `layout_north` magnetic and the
     azimuths of `defaults:`, and the file must not hold the word
     "geographic";
(25) the first run does not print "coil response copied: sensors/l120n.rsp
     (the Burra LEMI-120 table): check it is this survey's coils", a line
     that says the declination is recorded for 2 sites and never applied to
     the data, and "next: python scripts/check_survey.py <survey.yaml>" as
     its last line; or, over site folders named `A.1` and with 29
     characters, does not write their entries and name each with what to do
     (rename its folder).

Part 5, sites of another recorder and another rate, on the mixed data root
of part 3 and on its EDL folder alone. **This test fails if**

(26) in the default mixed survey (lemi423 at 1000 Hz) MBJ21 (1 Hz) and
     EGFLP02 (10 Hz) do not carry `sample_rate: 1.0` and `10.0` in their own
     entries, read back by `Survey.sample_rate_of`, or S01 carries one; or
     EGFLP02, which has no position, gets a declination key;
(27) a first run over the EDL folder alone (an EDL survey at 10 Hz) does not
     keep `calibration_fn` and `h_scale` in `defaults:` and the coil table
     in sensors/; or a re-run after a LEMI-423 folder (S01) and a LEMI-424
     folder (MBJ21) are put beside it does not give S01 its own
     `instrument: lemi423`, `channels: [ex, ey, hx, hy]` and `sample_rate:
     1000.0`, with `Survey.site("S01")` reading `h_scale` -1000.0 and the
     `calibration_fn` from `defaults:`, and MBJ21 its own `instrument:
     lemi424` and `sample_rate: 1.0`;
(28) the `processing:` block does not follow the survey's rate: the EDL
     survey at 10 Hz of (27) must hold `min_period` 0.2, `max_period`
     100000.0, `periods_per_decade` 10.0 and `min_band_windows` 2 with no
     `notch_frequencies`, read back by `Survey.processing` and
     `Survey.min_band_windows`; a survey over the LEMI-424 folder alone
     (1 Hz) the same with `min_period` 4.0; the 1000 Hz surveys keep the
     block of (4); and `processing_block`, called here, must keep the block
     of (4) at 100 Hz, give 2 / rate at 99, 10 and 2 Hz, and 4.0 at 1.9 and
     0.5 Hz.

The mutations parts 4 and 5 catch, each made in a copy of the code: `>` written
as `>=` in `check_survey_name` (the 30-character item of (15) fails); the
name checked after the site folders are looked for (the first item of (15)
exits 1); a re-run that writes the file again from the folders ((5) does
not say "nothing to add") or, when it adds, from its parsed form ((16): the
typed comment is lost and every line changes); `--timezone` defaulting to
Australia/Adelaide again ((16) prints an "ignored" line); `--force`
accepted ((18)); the data root of the file not compared ((19)); the name
checked on a re-run ((20)); the table rows of sites that have an entry not
applied ((21)); `--dipole-length` written to dipole_length_ex only, or not
compared on a re-run ((22)); the declination not filled for a site added by
a re-run ((23)); the fill also writing `layout_north: geographic` and the
site's azimuths turned by the declination ((24)); `sample_rate` written only
for a site of the survey's own recorder ((26)); `calibration_fn` and
`h_scale` written only for a LEMI-423 survey ((27)); the block of 100 Hz and
above written at every rate, or only above 100 Hz, the shortest period taken
as 4 / rate below 100 Hz, or the 4 s of the slowest records taken from 2 Hz
down in place of below 2 Hz ((28)).

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

import difflib
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

from mt_workbench.survey import Survey  # noqa: E402

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


def fresh(name: str) -> Path:
    """Return <scratch>/<name>/survey.yaml with its folder removed, so the next run is a first run."""
    out = SCRATCH / name / "survey.yaml"
    shutil.rmtree(out.parent, ignore_errors=True)
    return out


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
    assert again.returncode == 0 and out.read_bytes() == before, (again.returncode, again.stdout, again.stderr)
    assert "nothing to add: every site folder has an entry" in again.stdout, again.stdout
    assert "ignored on a re-run" not in again.stdout, again.stdout
    assert not out.with_name("survey.yaml.previous").exists(), "a run that adds nothing made survey.yaml.previous"
    print(f"(5) a second run with the same folders: {again.stdout.strip().splitlines()[-1]}; the file as it was")

    table = SCRATCH / "two_rows.csv"
    # the table's elevation is 1000 m low on purpose (as a hand-typed table can
    # be): the header's GPS fix must win and the disagreement be printed
    low = float(sites["S01"]["elevation"]) - 1000.0
    table.write_text(f"site,dipole_length_ex,azimuth_ex,elevation\nS01,48.5,180,{low}\nX99,10,0,\n", encoding="utf-8")
    merged = run(root, "--name", "synthetic", "--out", fresh("synthetic_table"), "--site-table", table)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert "1 of 2 sites matched" in merged.stdout, merged.stdout
    assert "S01 elevation: table" in merged.stdout and "header kept" in merged.stdout, merged.stdout
    after = yaml.safe_load((SCRATCH / "synthetic_table" / "survey.yaml").read_text(encoding="utf-8"))["sites"]
    changed = {k: v for k, v in after["S01"].items() if sites["S01"].get(k) != v}
    assert changed == {"dipole_length_ex": 48.5, "azimuth_ex": 180.0}, changed
    assert after["S01"]["elevation"] == sites["S01"]["elevation"], after["S01"]["elevation"]
    assert after["S02"] == sites["S02"], after["S02"]
    print(f"(6) --site-table: S01 changed {changed}, its elevation kept from the header, S02 untouched")

    elsewhere = SCRATCH / "elsewhere"
    moved_out = fresh("synthetic_workspace")
    moved = run(root, "--name", "synthetic", "--out", moved_out, "--workspace", elsewhere)
    assert moved.returncode == 0, moved.stdout + moved.stderr
    got = yaml.safe_load(moved_out.read_text(encoding="utf-8"))["workspace"]
    assert Path(got) == elsewhere.resolve(), got
    print(f"(7) --workspace {elsewhere}: workspace {got}")

    for site in ("S01", "S02"):
        line = next(ln for ln in done.stdout.splitlines() if ln.strip().startswith(site))
        assert line.endswith("columns hx hy hz ex ey, declared ex ey hx hy"), line
    for arg in ("hx,hy", "Bx By (magnetics only)"):
        mag_out = fresh("synthetic_channels")
        mag = run(root, "--name", "synthetic", "--out", mag_out, "--channels", arg)
        assert mag.returncode == 0, mag.stdout + mag.stderr
        got = yaml.safe_load(mag_out.read_text(encoding="utf-8"))["defaults"]["channels"]
        assert got == ["hx", "hy"], (arg, got)
        lines = [ln for ln in mag.stdout.splitlines() if ln.strip().startswith(("S01", "S02"))]
        assert len(lines) == 2 and all(ln.endswith("declared hx hy") for ln in lines), lines
        assert "not among" not in mag.stdout, mag.stdout
        print(f"(8) --channels {arg!r}: defaults channels {got}; S01 {lines[0][lines[0].index('columns'):]}")

    odd = run(root, "--name", "synthetic", "--out", fresh("synthetic_odd"), "--channels", "e1,e2,hx,hy")
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
    assert sites["MBJ21"]["channels"] == ["ex", "ey", "e3", "e4", "hx", "hy", "hz"], sites["MBJ21"]["channels"]
    assert "e_sign" not in config["defaults"], config["defaults"]
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
    assert lines["MBJ21"].endswith("1 Hz  lemi424  columns hx hy hz ex ey e3 e4, declared ex ey e3 e4 hx hy hz"), lines
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
    lemi = samples.mixed_survey("--instrument", "lemi424")
    assert lemi.returncode == 0, lemi.stdout + lemi.stderr
    text = samples.MIXED_YAML.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    assert config["instrument"] == "lemi424" and config["defaults"]["e_sign"] == -1.0, config["defaults"]
    rows = text.splitlines()
    at = rows.index("  e_sign: -1.0")
    assert rows[at - 1].startswith("  # LEMI-424 sites: E1 and E2 are recorded with the opposite sign"), rows[at - 1]
    assert config["defaults"]["channels"] == ["ex", "ey", "e3", "e4", "hx", "hy", "hz"], config["defaults"]
    assert Survey.from_yaml(samples.MIXED_YAML).site("MBJ21").e_sign == -1.0
    print(f"(12) --instrument lemi424: defaults e_sign -1.0 under its comment, channels "
          f"{config['defaults']['channels']}; Survey.site reads e_sign -1.0 back")
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
    out = root / "gain_10" / "survey.yaml"
    done = run(root / "raw", "--name", "edl_gain", "--out", out, "--electric-gain", "10")
    assert done.returncode == 0, done.stdout + done.stderr
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert config["defaults"]["electric_gain"] == 10.0, config["defaults"]
    own = {s: config["sites"][s].get("electric_gain") for s in flags}
    assert own == {"ST91": None, "ST92": None, "ST93": None}, own
    survey = Survey.from_yaml(out)
    resolved = {s: survey.site(s).electric_gain for s in flags}
    assert resolved == {"ST91": 10.0, "ST92": 10.0, "ST93": 10.0}, resolved
    for data_root, value, fragment in ((root / "raw", "abc", "argument --electric-gain: invalid float value"),
                                       (SCRATCH / "raw", "10", "--electric-gain is an Earth Data PR6-24")):
        bad_out = root / "refused" / "survey.yaml"
        shutil.rmtree(bad_out.parent, ignore_errors=True)
        bad = run(data_root, "--name", "edl_gain", "--out", bad_out, "--electric-gain", value)
        assert bad.returncode == 2, (data_root, value, bad.returncode, bad.stdout, bad.stderr)
        assert fragment in bad.stderr, (value, bad.stderr)
        assert not bad_out.exists(), f"a refused run wrote {bad_out}"
    print(f"(14) electric gain: no flag -> no defaults key, no site key, recorder.ini noted "
          f"informationally; '10' -> defaults 10.0, no site key, resolved {resolved}; 'abc' and a "
          f"LEMI-423-only root refused (exit 2) with the electric gain named, nothing written")


def test_survey_name() -> None:
    """Run check (15): the name of a new survey is checked before any folder is read."""
    from mt_workbench.survey import check_survey_name

    no_sites = SCRATCH / "name_no_sites"
    no_sites.mkdir(exist_ok=True)
    out = SCRATCH / "name_refused" / "survey.yaml"
    shutil.rmtree(out.parent, ignore_errors=True)
    letters = "holds characters other than letters, digits, _ and -: choose another name"
    accent = chr(233)  # an e with an acute accent, by its code point
    for name, fragment in (("n" * 31, "survey name has 31 characters: 30 at most; choose a shorter name"),
                           ("my survey", letters), (f"Maroc_T{accent}n{accent}r{accent}", letters)):
        done = run(no_sites, "--name", name, "--out", out)
        assert done.returncode == 2, (name, done.returncode, done.stdout, done.stderr)
        assert fragment in done.stdout, (name, done.stdout)
        assert not out.parent.exists(), f"{name}: the refused run made {out.parent}"
    root = SCRATCH / "raw"
    build_data_root(root)
    out = SCRATCH / "name_30" / "survey.yaml"
    shutil.rmtree(out.parent, ignore_errors=True)
    done = run(root, "--name", "n" * 30, "--out", out)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["name"] == "n" * 30
    for good in ("n" * 30, "A-b_9"):
        check_survey_name(good)
    for bad in ("", " ", "n" * 31, "a.b", "a/b", "a b", accent):
        try:
            check_survey_name(bad)
        except ValueError:
            continue
        raise AssertionError(f"check_survey_name accepted {bad!r}")
    print("(15) names of 31 characters, with a space and with an accent refused (exit 2) before any folder is "
          "read, nothing made; a name of 30 characters accepted")


DECLINATION_KEYS = ("declination", "declination_model", "declination_epoch")


def decimal_year(epoch: float) -> float:
    """Return an epoch in seconds as a decimal year to 2 decimals, worked out here from the calendar."""
    when = pd.Timestamp(epoch, unit="s", tz="UTC")
    start = pd.Timestamp(year=when.year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=when.year + 1, month=1, day=1, tz="UTC")
    return round(when.year + (when - start) / (end - start), 2)


def line_changes(old: str, new: str) -> list[tuple]:
    """Return (tag, first old line, old lines, new lines) for each run of lines that differs."""
    a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    return [(tag, i1, a[i1:i2], b[j1:j2])
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if tag != "equal"]


def test_rerun() -> None:
    """Run checks (16)-(21): a re-run adds the folders with no entry and leaves the rest of the file."""
    root, out = SCRATCH / "rerun_raw", fresh("rerun")
    previous = out.with_name("survey.yaml.previous")
    build_data_root(root)
    first = run(root, "--name", "rerun", "--out", out, "--timezone", "Australia/Perth")
    assert first.returncode == 0, first.stdout + first.stderr
    made = out.read_bytes().decode("utf-8")
    comment = "  # S02 moved 20 m east on the second day\n"
    typed = made.replace("  S02:\n", comment + "  S02:\n").replace("  S01:\n", "  S01:\n    rot_h: 3.0\n")
    assert typed.count(comment) == 1 and typed.count("    rot_h: 3.0\n") == 1, "the hand edits did not go in"
    out.write_bytes(typed.encode("utf-8"))
    epoch, spacing = 1625100000, 3600
    for k in range(2):
        write_b423(root / "S03" / f"{epoch + k * spacing}.B423", 77, "2.2", -31.3, 138.8, 300.0, epoch + k * spacing)

    again = run(root, "--name", "rerun", "--out", out)
    assert again.returncode == 0, (again.returncode, again.stdout, again.stderr)
    added = out.read_bytes().decode("utf-8")
    changes = line_changes(typed, added)
    assert len(changes) == 1 and changes[0][0] == "insert" and changes[0][1] == len(typed.splitlines()), changes
    assert changes[0][3][0] == "  S03:\n", changes[0][3]
    sites = yaml.safe_load(added)["sites"]
    assert list(sites) == ["S01", "S02", "S03"], list(sites)
    s03 = sites["S03"]
    assert abs(s03["latitude"] + 31.3) <= 1e-6 and abs(s03["longitude"] - 138.8) <= 1e-6, s03
    assert (s03["elevation"], s03["serial"], s03["firmware"]) == (300.0, "77", "2.2"), s03
    assert (s03["start"], s03["end"]) == (iso(epoch), iso(epoch + 2 * spacing)), s03
    assert str(s03.get("declination_model", "")).startswith("IGRF-"), s03
    assert 6.5 < s03["declination"] < 9.0 and s03["declination_epoch"] == decimal_year(epoch + spacing), s03
    assert sites["S01"]["rot_h"] == 3.0 and comment in added
    assert previous.read_bytes() == typed.encode("utf-8"), "survey.yaml.previous is not the file before the re-run"
    assert "added 1 site(s): S03; left as they are: 2 site(s) with an entry" in again.stdout, again.stdout
    assert "ignored on a re-run" not in again.stdout, again.stdout
    print("(16) re-run: S03 added as one run of lines after the last entry, the typed comment and key and every "
          "other line kept, the file before it in survey.yaml.previous, no head argument compared")
    print(f"(23) S03, added by the re-run: declination {s03['declination']} ({s03['declination_model']}, "
          f"{s03['declination_epoch']})")

    ignored = "ignored on a re-run: --timezone Australia/Adelaide (survey.yaml keeps timezone: Australia/Perth)"
    other = run(root, "--name", "rerun", "--out", out, "--timezone", "Australia/Adelaide")
    assert other.returncode == 0 and out.read_bytes().decode("utf-8") == added, (other.returncode, other.stdout)
    assert [ln for ln in other.stdout.splitlines() if "ignored on a re-run" in ln] == [ignored], other.stdout
    same = run(root, "--name", "rerun", "--out", out, "--timezone", "Australia/Perth")
    assert same.returncode == 0 and "ignored on a re-run" not in same.stdout, same.stdout
    print(f"(17) {ignored}; no such line for a value equal to the file's")

    absent = fresh("rerun_force")
    for target in (out, absent):
        forced = run(root, "--name", "rerun", "--out", target, "--force")
        assert forced.returncode == 2, (forced.returncode, forced.stdout, forced.stderr)
        assert "--force is gone: a re-run only adds the site folders that have no entry" in forced.stdout
        assert f"delete {target.resolve()} by hand and run this command again" in forced.stdout, forced.stdout
    assert out.read_bytes().decode("utf-8") == added and not absent.exists(), "--force wrote a file"
    print("(18) --force refused (exit 2) with the delete-by-hand message, on a file that exists and on none")

    elsewhere = run(SCRATCH / "raw", "--name", "rerun", "--out", out)
    assert elsewhere.returncode == 2, (elsewhere.returncode, elsewhere.stdout)
    assert f"survey.yaml reads its sites from {root.resolve()}" in elsewhere.stdout, elsewhere.stdout
    renamed = run(root, "--name", "other_name", "--out", out)
    assert renamed.returncode == 2 and "'rerun'" in renamed.stdout, (renamed.returncode, renamed.stdout)
    assert out.read_bytes().decode("utf-8") == added, "a refused re-run changed the file"
    print("(19) a re-run with another data root, or another --name, refused (exit 2), the file unchanged")

    long_name = "a_survey_name_of_33_characters_xx"
    assert len(long_name) == 33
    assert added.count("name: rerun\n") == 1
    long_text = added.replace("name: rerun\n", f"name: {long_name}\n")
    out.write_bytes(long_text.encode("utf-8"))
    write_b423(root / "S04" / f"{epoch}.B423", 78, "2.2", -31.4, 138.9, 310.0, epoch)
    table = SCRATCH / "rerun_new_site.csv"
    table.write_text("site,dipole_length_ex\nS04,46\n", encoding="utf-8")
    long_run = run(root, "--name", long_name, "--out", out, "--site-table", table)
    assert long_run.returncode == 0, (long_run.returncode, long_run.stdout, long_run.stderr)
    sites = yaml.safe_load(out.read_text(encoding="utf-8"))["sites"]
    assert list(sites) == ["S01", "S02", "S03", "S04"] and sites["S04"]["dipole_length_ex"] == 46.0, sites
    assert "added 1 site(s): S04" in long_run.stdout, long_run.stdout
    print("(20) a file whose name has 33 characters: the re-run adds S04, with its row of the site table")

    before = out.read_bytes().decode("utf-8")
    table = SCRATCH / "rerun_table.csv"
    off = round(sites["S01"]["latitude"] + 0.01, 6)
    table.write_text("site,dipole_length_ex,dipole_length_ey,azimuth_ex,latitude\n"
                     f"S01,48.5,,0,{off}\nS03,,47,,\nX99,10,,,\n", encoding="utf-8")
    tabled = run(root, "--name", long_name, "--out", out, "--site-table", table)
    assert tabled.returncode == 0, (tabled.returncode, tabled.stdout, tabled.stderr)
    after = out.read_bytes().decode("utf-8")
    inserted = [(tag, old, new) for tag, _at, old, new in line_changes(before, after)]
    assert inserted == [("insert", [], ["    dipole_length_ex: 48.5\n"]),
                        ("insert", [], ["    dipole_length_ey: 47.0\n"])], inserted
    now = yaml.safe_load(after)["sites"]
    assert list(now["S01"])[-1] == "dipole_length_ex" and "azimuth_ex" not in now["S01"], now["S01"]
    assert now["S01"]["latitude"] == sites["S01"]["latitude"] and list(now["S03"])[-1] == "dipole_length_ey"
    assert comment in after and now["S01"]["rot_h"] == 3.0
    for line in ("changed 2 site(s) from the site table:", "  S01: dipole_length_ex 48.5",
                 "  S03: dipole_length_ey 47.0", "left as they are: 2 site(s) with an entry"):
        assert line in tabled.stdout, (line, tabled.stdout)
    assert "S01 latitude: table" in tabled.stdout and "survey.yaml kept" in tabled.stdout, tabled.stdout
    assert "not a site folder: X99" in tabled.stdout, tabled.stdout
    twice = run(root, "--name", long_name, "--out", out, "--site-table", table)
    assert twice.returncode == 0 and out.read_bytes().decode("utf-8") == after, (twice.returncode, twice.stdout)
    assert "the 2 site(s) with an entry that it names already read as the table" in twice.stdout, twice.stdout
    print("(21) a re-run with --site-table: one line added to S01 and one to S03, the value equal to defaults: "
          "not written, S01's latitude kept and the disagreement printed; the same table again changes no byte")


def test_head() -> None:
    """Run checks (22)-(25): the usual dipoles, the declination, the frame and the summary lines."""
    root = SCRATCH / "raw"
    build_data_root(root)
    out = fresh("head_usual")
    done = run(root, "--name", "head_usual", "--out", out, "--dipole-length", "45", "--azimuths", "10", "100")
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    want = {**EXPECTED_DEFAULTS, "dipole_length_ex": 45.0, "dipole_length_ey": 45.0, "azimuth_ex": 10.0,
            "azimuth_ey": 100.0}
    assert config["defaults"] == want, config["defaults"]
    s01 = Survey.from_yaml(out).site("S01")
    usual = (s01.dipole_length_ex, s01.dipole_length_ey, s01.azimuth_ex, s01.azimuth_ey)
    assert usual == (45.0, 45.0, 10.0, 100.0), usual
    before = out.read_bytes()
    again = run(root, "--name", "head_usual", "--out", out, "--dipole-length", "50", "--azimuths", "0", "90")
    ignored = [ln for ln in again.stdout.splitlines() if ln.startswith("ignored on a re-run")]
    assert again.returncode == 0 and out.read_bytes() == before, (again.returncode, again.stdout)
    assert ignored == ["ignored on a re-run: --dipole-length 50 (survey.yaml keeps 45.0 in defaults:)",
                       "ignored on a re-run: --azimuths 0 90 (survey.yaml keeps 10.0 and 100.0 in defaults:)"], ignored
    same = run(root, "--name", "head_usual", "--out", out, "--dipole-length", "45", "--azimuths", "10", "100")
    assert same.returncode == 0 and "ignored on a re-run" not in same.stdout, same.stdout
    help_text = " ".join(run("--help").stdout.split())
    assert "degrees from magnetic north" in help_text, help_text
    print(f"(22) --dipole-length 45 --azimuths 10 100: defaults {usual}; on a re-run: {ignored[0]}; {ignored[1]}")

    out = fresh("head_default")
    done = run(root, "--name", "head_default", "--out", out)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    text = out.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    for folder, _sub, _serial, _fw, _lat, _lon, _alt, epoch, spacing, n in SITES:
        e = config["sites"][folder]
        assert str(e.get("declination_model", "")).startswith("IGRF-"), (folder, e)
        assert e["declination_epoch"] == decimal_year(epoch + n * spacing / 2), (folder, e["declination_epoch"])
        assert 6.5 < e["declination"] < 9.0 and round(e["declination"], 2) == e["declination"], (folder, e)
        print(f"(23) {folder}: declination {e['declination']} ({e['declination_model']}, {e['declination_epoch']})")

    without = yaml.safe_load(text)
    for entry in without["sites"].values():
        for key in DECLINATION_KEYS:
            del entry[key]
    filled, plain = Survey(config, out.parent), Survey(without, out.parent)
    for site, entry in config["sites"].items():
        a, b = vars(filled.site(site)), vars(plain.site(site))
        differ = sorted(k for k in a if a[k] != b[k])
        assert differ == sorted(DECLINATION_KEYS), (site, differ)
        assert a["layout_north"] == "magnetic" and (a["azimuth_ex"], a["azimuth_ey"]) == (0.0, 90.0), (site, a)
        assert not set(entry) & {"azimuth_ex", "azimuth_ey", "rot_h", "rot_e", "layout_north"}, (site, entry)
    assert "layout_north" not in text and "geographic" not in text, "the new survey names a layout north"
    print("(24) the declination keys are the only fields the fill moves; layout_north magnetic, azimuths 0/90")

    lines = done.stdout.splitlines()
    coil = "coil response copied: sensors/l120n.rsp (the Burra LEMI-120 table): check it is this survey's coils"
    assert coil in lines, done.stdout
    recorded = [ln for ln in lines if ln.startswith("declination (IGRF-")]
    assert len(recorded) == 1 and "recorded for 2 site(s)" in recorded[0], done.stdout
    assert "never applied to the data" in recorded[0], recorded
    assert lines[-1] == f"next: python scripts/check_survey.py {out.resolve()}", lines[-1]
    odd_root, long_site = SCRATCH / "odd_names", "S" * 29
    shutil.rmtree(odd_root, ignore_errors=True)
    for name in ("A.1", long_site, "S01"):
        write_b423(odd_root / name / "1624949744.B423", 36, "2.1", -31.1, 138.6, 100.0, 1624949744)
    odd_out = fresh("odd_names_survey")
    odd = run(odd_root, "--name", "odd_names", "--out", odd_out)
    assert odd.returncode == 0, (odd.returncode, odd.stdout, odd.stderr)
    assert sorted(yaml.safe_load(odd_out.read_text(encoding="utf-8"))["sites"]) == sorted(["A.1", long_site, "S01"])
    named = [ln.strip() for ln in odd.stdout.splitlines() if "site name" in ln]
    assert len(named) == 2 and all("rename its folder" in ln for ln in named), named
    assert "'A.1' holds characters other than letters, digits, _ and -" in named[0], named
    assert f"'{long_site}' has 29 characters: 28 at most" in named[1], named
    print(f"(25) summary: {coil}; {recorded[0]}; {lines[-1]}; {named[0]}")


def test_other_recorders() -> None:
    """Run checks (26)-(27): the own sample_rate of sites at another rate, and other recorders added to an EDL survey."""
    sys.path.insert(0, str(REPO / "tests"))
    import instrument_samples as samples

    done = samples.mixed_survey()
    assert done.returncode == 0, done.stdout + done.stderr
    sites = yaml.safe_load(samples.MIXED_YAML.read_text(encoding="utf-8"))["sites"]
    own = {site: entry.get("sample_rate") for site, entry in sites.items()}
    assert own == {"EGFLP02": 10.0, "MBJ21": 1.0, "S01": None}, own
    survey = Survey.from_yaml(samples.MIXED_YAML)
    read = {site: survey.sample_rate_of(site) for site in sites}
    assert read == {"EGFLP02": 10.0, "MBJ21": 1.0, "S01": 1000.0}, read
    assert not set(sites["EGFLP02"]) & set(DECLINATION_KEYS), sites["EGFLP02"]
    assert set(DECLINATION_KEYS) <= set(sites["MBJ21"]) and set(DECLINATION_KEYS) <= set(sites["S01"]), sites
    print(f"(26) mixed survey at 1000 Hz: own sample_rate {own}, read back {read}; no declination for EGFLP02 "
          f"(no position), MBJ21 {sites['MBJ21']['declination']}")

    made = samples.make_samples()
    root, out = SCRATCH / "edl_then_others", fresh("edl_then_others_survey")
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(made["EGFLP02"], root / "EGFLP02")
    first = run(root, "--name", "edl_first", "--out", out)
    assert first.returncode == 0, (first.returncode, first.stdout, first.stderr)
    config = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert (config["instrument"], config["sample_rate"]) == ("edl", 10), (config["instrument"], config["sample_rate"])
    assert config["defaults"]["calibration_fn"] == "sensors/l120n.rsp", config["defaults"]
    assert config["defaults"]["h_scale"] == -1000.0, config["defaults"]
    assert (out.parent / "sensors" / "l120n.rsp").read_bytes() == RSP.read_bytes()
    assert "sample_rate" not in config["sites"]["EGFLP02"], config["sites"]["EGFLP02"]
    folder, sub, serial, fw, lat, lon, alt, epoch, spacing, n = SITES[0]
    for k in range(n):
        write_b423(root / folder / sub / f"{epoch + k * spacing}.B423", serial, fw, lat, lon, alt,
                   epoch + k * spacing)
    shutil.copytree(made["MBJ21"], root / "MBJ21")
    again = run(root, "--name", "edl_first", "--out", out)
    assert again.returncode == 0, (again.returncode, again.stdout, again.stderr)
    sites = yaml.safe_load(out.read_text(encoding="utf-8"))["sites"]
    assert list(sites) == ["EGFLP02", "MBJ21", "S01"], list(sites)
    s01, mbj = sites["S01"], sites["MBJ21"]
    assert (s01.get("instrument"), s01.get("channels"), s01.get("sample_rate")) == (
        "lemi423", ["ex", "ey", "hx", "hy"], 1000.0), s01
    assert (mbj.get("instrument"), mbj.get("sample_rate")) == ("lemi424", 1.0), mbj
    assert not {"h_scale", "calibration_fn"} & set(s01), s01
    survey = Survey.from_yaml(out)
    merged = survey.site("S01")
    assert (merged.h_scale, merged.calibration_fn) == (-1000.0, "sensors/l120n.rsp"), merged
    read = {site: survey.sample_rate_of(site) for site in sites}
    assert read == {"EGFLP02": 10.0, "MBJ21": 1.0, "S01": 1000.0}, read
    print(f"(27) an EDL survey at 10 Hz keeps calibration_fn and h_scale; S01 and MBJ21 added by a re-run with "
          f"their own instrument and sample_rate {read}; S01 reads h_scale {merged.h_scale} from defaults:")

    slow = {"max_period": 100000.0, "periods_per_decade": 10.0, "min_band_windows": 2}
    assert config["processing"] == {"min_period": 0.2, **slow}, config["processing"]
    assert survey.processing == {"min_period": 0.2, "max_period": 100000.0, "periods_per_decade": 10.0}
    assert survey.min_band_windows == 2, survey.min_band_windows
    lemi_root, lemi_out = SCRATCH / "lemi424_alone", fresh("lemi424_alone_survey")
    shutil.rmtree(lemi_root, ignore_errors=True)
    shutil.copytree(made["MBJ21"], lemi_root / "MBJ21")
    alone = run(lemi_root, "--name", "lemi424_alone", "--out", lemi_out)
    assert alone.returncode == 0, (alone.returncode, alone.stdout, alone.stderr)
    one_hz = yaml.safe_load(lemi_out.read_text(encoding="utf-8"))
    assert (one_hz["instrument"], one_hz["sample_rate"]) == ("lemi424", 1), one_hz["sample_rate"]
    assert one_hz["processing"] == {"min_period": 4.0, **slow}, one_hz["processing"]
    fast = yaml.safe_load(samples.MIXED_YAML.read_text(encoding="utf-8"))
    assert fast["sample_rate"] == 1000 and fast["processing"] == EXPECTED_PROCESSING, fast["processing"]
    blocks = {rate: yaml.safe_load(new_survey.processing_block(rate))["processing"]
              for rate in (1000.0, 100.0, 99.0, 10.0, 2.0, 1.9, 0.5)}
    assert blocks[1000.0] == blocks[100.0] == EXPECTED_PROCESSING, blocks[100.0]
    shortest = {rate: block["min_period"] for rate, block in blocks.items() if rate < 100.0}
    assert shortest == {99.0: 2 / 99.0, 10.0: 0.2, 2.0: 1.0, 1.9: 4.0, 0.5: 4.0}, shortest
    assert all({k: v for k, v in blocks[rate].items() if k != "min_period"} == slow for rate in shortest), blocks
    print(f"(28) processing: 10 Hz {config['processing']}; 1 Hz min_period {one_hz['processing']['min_period']}; "
          f"1000 Hz as in (4); shortest period by rate {shortest}")


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
    print()
    print(__doc__.split("**This test fails if**")[3].strip())
    print()
    test_survey_name()
    test_rerun()
    test_head()
    print()
    print(__doc__.split("**This test fails if**")[4].split("Part 2, the real-data check:")[0].strip())
    print()
    test_other_recorders()
    part2()
    print("\nPASS  new_survey_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
