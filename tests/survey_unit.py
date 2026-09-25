# -*- coding: utf-8 -*-
"""
Unit test for crust.survey

Checks `distance_km`, `Survey.timezone`, the field-sheet survey CSV reader,
the channel presets, instrument detection, the electric chain gain key and
the derived and observatory sites. Runs without Qt or an archive.

Usage:
    python tests/survey_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** one degree of latitude on the equator, and again at
-30 deg (D02's latitude), is not 111.2 km to within 0.5 km; the same distance
is not symmetric in its arguments, zero for a point against itself, and
shorter along a degree of longitude at -30 deg than along a degree of
latitude (cos 30 = 0.87 of it); `distance_km` between D02 and E08, read from
`surveys/curnamona_cube/survey.yaml`, is not 148.6 km within 0.5 km; a survey
with no top-level `timezone:` does not report "UTC"; a survey that declares
one does not report exactly it; or the two real survey configs do not both
declare `Australia/Adelaide` **above** their `sites:` block, where
`scripts/burra_notes_to_yaml.py`'s `write_sites_block` keeps the head of the
file unchanged; or the channel presets (`CHANNEL_PRESETS`, `preset_label`,
`channels_from_label`) break: a preset of either instrument does not round
trip label -> list -> label; the LEMI-423 default (the first preset) is not
"Ex Ey Bx By" = [ex, ey, hx, hy]; the same set in another order or case does
not get the preset's label; "Bx By Bz" does not mean hx hy hz on a LEMI-423
and bx by bz on a LEMI-424; a custom list is not written "a, b, c" and read
back unchanged; a typed "hx hy" is not [hx, hy]; None is not "all columns"
and back; a returned preset list is not a copy; or a preset names a channel
the reader does not produce (LEMI-424: mt-io's own `LEMI424().file_column_names`;
LEMI-423: hx hy hz ex ey, as `LEMI423Reader.read` stores Bx By Bz Ex Ey; EDL:
mt-io's own `UoACollection.CHANNEL_MAP`), the presets' instruments are not
exactly `INSTRUMENTS` (lemi423, lemi424, edl) or the EDL default is not
"Ex Ey Bx By Bz" = [ex, ey, hx, hy, hz]; or a preset's words in another
order, with commas or in another case ("Bx By Ex Ey", as typed for an
EDL survey's `--channels`) are not that preset ([ex, ey, hx, hy] on an
EDL or LEMI-423,
not [bx, by, ex, ey], which drops both coils at ingest), or a typed list
that is no preset's words is not kept as typed.

And the instrument detection: in a scratch data root holding a B423 folder,
a LEMI-424 folder (a 12-digit .txt whose first line has the reader's 24
fields), an EDL folder with only a channel file, an EDL folder with only
`config/recorder.ini`, a folder whose 12-digit .txt holds prose, a folder of
AppleDouble twins only, and a folder with both B423 and LEMI-424 files,
`Survey.site_dirs()` does not list exactly the five data folders or
`instrument_of` does not name each one's recorder -- the mixed folder
lemi423 in a lemi423 survey and lemi424 in a lemi424 survey (the survey's
instrument is preferred) -- or a site's own `instrument:` does not win over
its files, or an unknown one does not raise ValueError, or a site with no
folder does not fall back to the survey's instrument.

And the electric chain gain key (a field-notes fact about the electric
chain, not a PR6-24 pre-amplifier setting): with `defaults: electric_gain: 10.0`, a site
with no key of its own does not read 10.0 from `Survey.site(...).electric_gain`,
a site's own number does not win over the default, or a survey without the
key does not give 1.0 (no filter, the EDL default).

And the sites with an archive and no raw folder: in the same scratch data
root, with a derived entry S01L (`derived_from: S01`, `sample_rate: 1.0`,
as scripts/decimate_site.py writes it) and an observatory entry EBR
(`instrument: intermagnet`, as scripts/fetch_observatory.py writes it),
`instrument_of` does not give S01L its parent's recorder (lemi423) and EBR
"intermagnet" without raising; `site_dirs()` lists either; `parent_of` does
not give S01 for S01L and None for S01 and EBR; `sample_rate_of` does not
give 1.0 for S01L and EBR, the survey's 1000.0 for S01 and for a name with
no entry (a stacked remote); `Survey.site("S01L")` does not carry
`derived_from` and `sample_rate`; or a site derived from itself does not
raise ValueError.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.survey import (  # noqa: E402
    ALL_CHANNELS, CHANNEL_PRESETS, INSTRUMENTS, Survey, channels_from_label, default_preset, distance_km,
    preset_label,
)

ONE_DEGREE_KM = 111.2
TOLERANCE_KM = 0.5
SURVEYS = [REPO / "surveys" / "curnamona_cube" / "survey.yaml",
           REPO / "surveys" / "burra" / "survey.yaml"]
D02_E08_KM = 148.6


def test_one_degree_of_latitude() -> None:
    for lat in (0.0, -30.0, 45.0):
        got = distance_km(lat, 138.0, lat + 1.0, 138.0)
        assert abs(got - ONE_DEGREE_KM) < TOLERANCE_KM, f"1 deg lat at {lat}: {got:.3f} km"
        print(f"  1 deg of latitude at {lat:+.0f}: {got:.3f} km")


def test_symmetry_zero_and_longitude_shrink() -> None:
    a, b = (-30.2557, 139.2282), (-30.4990, 140.7512)
    there, back = distance_km(*a, *b), distance_km(*b, *a)
    assert abs(there - back) < 1e-9, (there, back)
    assert distance_km(*a, *a) == 0.0, distance_km(*a, *a)
    lat_deg = distance_km(-30.0, 139.0, -29.0, 139.0)
    lon_deg = distance_km(-30.0, 139.0, -30.0, 140.0)
    ratio = lon_deg / lat_deg
    assert 0.85 < ratio < 0.88, f"a degree of longitude at -30 deg is {ratio:.3f} of a degree of latitude"
    print(f"  symmetric to 1e-9 km, zero for a point on itself, "
          f"lon/lat degree ratio at -30 deg {ratio:.3f}")


def test_d02_to_e08_from_the_yaml() -> None:
    survey = Survey.from_yaml(SURVEYS[0])
    d02, e08 = survey.site("D02"), survey.site("E08")
    got = distance_km(d02.latitude, d02.longitude, e08.latitude, e08.longitude)
    assert abs(got - D02_E08_KM) < TOLERANCE_KM, f"D02-E08 {got:.3f} km"
    print(f"  D02 -> E08 from survey.yaml: {got:.2f} km")


def test_timezone_defaults_to_utc() -> None:
    config = {"name": "t", "data_root": str(REPO)}
    assert Survey(config, REPO).timezone == "UTC", Survey(config, REPO).timezone
    config["timezone"] = "Australia/Perth"
    assert Survey(config, REPO).timezone == "Australia/Perth"
    config["timezone"] = None  # an empty key is still UTC
    assert Survey(config, REPO).timezone == "UTC"
    print("  timezone: absent -> UTC, declared -> that name, empty -> UTC")


def test_real_surveys_declare_adelaide_above_sites() -> None:
    for path in SURVEYS:
        survey = Survey.from_yaml(path)
        assert survey.timezone == "Australia/Adelaide", (path.parent.name, survey.timezone)
        text = path.read_text(encoding="utf-8")
        assert text.index("\ntimezone:") < text.index("\nsites:"), path
        print(f"  {path.parent.name}: timezone {survey.timezone}, declared above the sites: block")


def test_field_survey_csv_columns() -> None:
    """Check that a field-sheet survey CSV is read into the site table.

    Fails if a field-sheet survey CSV (SiteName, ExDipole, ExAzimuth,
    EyDipole, EyAzimuth, Latitude, Longitude, Elevation, Deployment_Notes,
    Pickup_Notes, TimeZone, ...) is not read into the site-table columns, or
    its two note columns are not joined into `notes`.
    """
    import tempfile
    from crust.survey import read_site_table
    lines = [
        "﻿SiteName,Latitude,Longitude,Elevation,TimeZone,ExDipole,ExAzimuth,EyDipole,EyAzimuth,Resistance_NG,Deployment_Notes,Pickup_Notes",
        "A01,31.54,-9.686,125.2,Africa/Casablanca,55,0,54,90,4.18,Surrounded by houses,",
        "A02,31.455,-9.776, 27.1,Africa/Casablanca,42,0,48,90,233,,electrode dug up",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Morocco_LEMI.csv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows, ignored = read_site_table(path)
    assert rows["A01"]["dipole_length_ex"] == 55.0 and rows["A01"]["azimuth_ey"] == 90.0, rows["A01"]
    assert rows["A02"]["elevation"] == 27.1 and rows["A02"]["dipole_length_ey"] == 48.0, rows["A02"]
    assert rows["A01"]["notes"] == "Surrounded by houses", rows["A01"].get("notes")
    assert rows["A02"]["notes"] == "electrode dug up", rows["A02"].get("notes")
    assert "resistance_ng" in ignored and "timezone" in ignored, ignored
    print(f"  field-sheet survey CSV read: A01 {rows['A01']}, ignored {ignored}")


def test_channel_presets() -> None:
    from mt_io.lemi.lemi424 import LEMI424
    from mt_io.uoa import UoACollection
    produced = {"lemi423": {"hx", "hy", "hz", "ex", "ey"}, "lemi424": set(LEMI424().file_column_names),
                "edl": {comp for comp, _n in UoACollection.CHANNEL_MAP.values()}}
    assert set(CHANNEL_PRESETS) == set(INSTRUMENTS) == {"lemi423", "lemi424", "edl"}, list(CHANNEL_PRESETS)
    for instrument, presets in CHANNEL_PRESETS.items():
        for label, channels in presets.items():
            back = channels_from_label(label, instrument)
            assert back == channels and preset_label(back, instrument) == label, (instrument, label, back)
            assert set(channels) <= produced[instrument], (instrument, label, set(channels) - produced[instrument])
        print(f"  {instrument}: {len(presets)} presets round trip; default {default_preset(instrument)!r}")
    assert default_preset("lemi423") == "Ex Ey Bx By"
    assert default_preset("edl") == "Ex Ey Bx By Bz"
    assert channels_from_label("Ex Ey Bx By Bz", "edl") == ["ex", "ey", "hx", "hy", "hz"]
    assert channels_from_label("Ex Ey Bx By", "lemi423") == ["ex", "ey", "hx", "hy"]
    assert preset_label(["HX", "hy", "Ey", "ex"], "lemi423") == "Ex Ey Bx By"
    assert channels_from_label("bx by bz", "lemi423") == ["hx", "hy", "hz"]
    assert channels_from_label("Bx By Bz", "lemi424") == ["bx", "by", "bz"]
    for custom in (["hx", "ey"], ["ex", "ey", "hx", "hy", "hz", "tx"], ["e1", "e2", "hx", "hy"]):
        label = preset_label(custom, "lemi423")
        assert label == ", ".join(custom) and channels_from_label(label, "lemi423") == custom, (custom, label)
    assert channels_from_label("hx hy", "lemi423") == ["hx", "hy"]
    assert preset_label(["hx", "hy"], "lemi423") == "Bx By (magnetics only)"
    assert preset_label(None, "lemi423") == ALL_CHANNELS and channels_from_label(ALL_CHANNELS, "lemi423") is None
    assert preset_label(["ex", "ey", "hx", "hy"], "earthdata") == "ex, ey, hx, hy"  # no presets: the list
    got = channels_from_label("Bx By (magnetics only)", "lemi423")
    got.append("hz")
    assert CHANNEL_PRESETS["lemi423"]["Bx By (magnetics only)"] == ["hx", "hy"], "a preset list was handed out, not copied"
    print("  default Ex Ey Bx By; order and case ignored; Bx By Bz per instrument; custom lists kept; "
          "None <-> 'all columns'")


def test_preset_words_in_any_order() -> None:
    # an EDL broadband survey declared with `new_survey.py --channels "Bx By Ex Ey"` must not
    # get [bx, by, ex, ey], of which ingest would keep only ex, ey; the EDL reader names its
    # coils hx hy
    for typed in ("Bx By Ex Ey", "bx, by, ex, ey", "  EY EX BY BX "):
        for instrument in ("edl", "lemi423"):
            got = channels_from_label(typed, instrument)
            assert got == ["ex", "ey", "hx", "hy"], (typed, instrument, got)
            assert preset_label(got, instrument) == "Ex Ey Bx By", (typed, instrument)
    assert channels_from_label("Bx By Bz Ex Ey", "edl") == ["ex", "ey", "hx", "hy", "hz"]
    assert channels_from_label("Bx By Bz E1 E2", "lemi424") == ["e1", "e2", "bx", "by", "bz"]
    # a typed list that is no preset's words is still the list, as typed
    assert channels_from_label("hx, hy, ex, ey", "edl") == ["hx", "hy", "ex", "ey"]
    assert channels_from_label("Bx By Ex", "edl") == ["bx", "by", "ex"]
    assert channels_from_label("bx, by", "lemi424") == ["bx", "by"]
    print("  'Bx By Ex Ey' (any order, commas, case) -> [ex, ey, hx, hy] on edl and lemi423; "
          "a non-preset list unchanged")


LEMI424_LINE = ("2024 10 25 00 00 00 27150.959 -74.552 -50540.593 27.73 36.16 -154.411 -297.117 "
                "94.135 -767.370 12.00  512.8 2800.28816 S 12054.72277 E 12 2 0\n")


def test_instrument_detection() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files = {
            "S01/1624949744.B423": b"",
            "MBJ21/202410250000.txt": LEMI424_LINE.encode(),
            "EGF01/001/EGF01_190110000000.EX": b"1\n2\n",
            "EGF02/config/recorder.ini": b"[recorder]\nchannel_0_samplerate=10\n",
            "NOTES/202410250000.txt": b"field notes, not a record\n",
            "GHOST/._1677774771.B423": bytes(8),
            "MIXED/1624949744.B423": b"",
            "MIXED/202410250000.txt": LEMI424_LINE.encode(),
        }
        for name, data in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(data)
        expected = {"EGF01": "edl", "EGF02": "edl", "MBJ21": "lemi424", "MIXED": "lemi423", "S01": "lemi423"}
        survey = Survey({"name": "t", "data_root": str(root), "sites": {"S01": {}}}, root)
        assert list(survey.site_dirs()) == sorted(expected), list(survey.site_dirs())
        got = {site: survey.instrument_of(site) for site in expected}
        assert got == expected, got
        other = Survey({"name": "t", "instrument": "lemi424", "data_root": str(root)}, root)
        assert other.instrument_of("MIXED") == "lemi424" and other.instrument_of("S01") == "lemi423"
        declared = Survey({"name": "t", "data_root": str(root),
                           "sites": {"S01": {"instrument": "edl"}, "BAD": {"instrument": "lemi999"}}}, root)
        assert declared.instrument_of("S01") == "edl" and declared.site("S01").instrument == "edl"
        try:
            declared.instrument_of("BAD")
        except ValueError:
            pass
        else:
            raise AssertionError("an unknown instrument was accepted")
        assert declared.instrument_of("NOFOLDER") == "lemi423"
        print(f"  site_dirs {sorted(expected)}; instruments {got}; MIXED is lemi424 in a lemi424 survey; "
              f"declared wins; unknown raises; no folder -> the survey's")


def test_derived_and_observatory_sites() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "S01").mkdir()
        (root / "S01" / "1624949744.B423").write_bytes(b"")
        sites = {"S01": {},
                 "S01L": {"derived_from": "S01", "sample_rate": 1.0, "latitude": -31.5},
                 "EBR": {"instrument": "intermagnet", "channels": ["hx", "hy", "hz"], "latitude": 40.96},
                 "LOOP": {"derived_from": "LOOP"}}
        survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root),
                         "sites": sites}, root)
        assert list(survey.site_dirs()) == ["S01"], list(survey.site_dirs())
        got = {s: survey.instrument_of(s) for s in ("S01", "S01L", "EBR")}
        assert got == {"S01": "lemi423", "S01L": "lemi423", "EBR": "intermagnet"}, got
        parents = {s: survey.parent_of(s) for s in ("S01", "S01L", "EBR")}
        assert parents == {"S01": None, "S01L": "S01", "EBR": None}, parents
        rates = {s: survey.sample_rate_of(s) for s in ("S01", "S01L", "EBR", "STK_S01")}
        assert rates == {"S01": 1000.0, "S01L": 1.0, "EBR": 1.0, "STK_S01": 1000.0}, rates
        cfg = survey.site("S01L")
        assert (cfg.derived_from, cfg.sample_rate, cfg.latitude) == ("S01", 1.0, -31.5), cfg
        try:
            survey.instrument_of("LOOP")
        except ValueError:
            pass
        else:
            raise AssertionError("a site derived from itself must raise")
    print(f"  derived S01L and observatory EBR: instruments {got}, rates {rates}, no raw folder for either")


def test_electric_gain_resolve() -> None:
    config = {"name": "t", "instrument": "edl", "data_root": ".",
              "defaults": {"electric_gain": 10.0},
              "sites": {"A": {}, "B": {"electric_gain": 1.0}, "C": {"electric_gain": 5.0}}}
    survey = Survey(config, Path("."))
    got = {s: survey.site(s).electric_gain for s in "ABC"}
    assert got == {"A": 10.0, "B": 1.0, "C": 5.0}, got
    plain = Survey({"name": "t", "instrument": "edl", "data_root": ".", "sites": {"A": {}}}, Path("."))
    assert plain.site("A").electric_gain == 1.0
    print(f"  electric_gain: default 10.0; {got}; no key -> 1.0 (no filter)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  survey_unit ({len(tests)} tests)")
