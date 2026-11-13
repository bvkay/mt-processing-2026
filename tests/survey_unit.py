# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.survey

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
"Ex Ey Bx By" = [ex, ey, hx, hy]; the LEMI-424 default is not "E1 E2 Bx By
Bz" = [ex, ey, hx, hy, hz] with "E1 E2 E3 E4 Bx By Bz" the second preset
(a LEMI-424 site records two electric channels at most surveys); the same
set in another order or case does
not get the preset's label; "Bx By Bz" does not mean hx hy hz on a LEMI-423
and on a LEMI-424 (stored names); a custom list is not written "a, b, c" and read
back unchanged; a typed "hx hy" is not [hx, hy]; None is not "all columns"
and back; a returned preset list is not a copy; or a preset names a channel
the reader does not produce (LEMI-424: mt-io's own `LEMI424().file_column_names`
as ingest stores them, `mt_workbench.instruments.LEMI424_RENAME`;
LEMI-423: hx hy hz ex ey, as `LEMI423Reader.read` stores Bx By Bz Ex Ey; EDL:
mt-io's own `UoACollection.CHANNEL_MAP`; Phoenix: mt-io's channel tags e1 e2
h1 h2 h3 as mt_workbench.phoenix renames them; Orange Box: the channels
mt-io's `read_orange` returns for a one-record synthetic file), the presets'
instruments are not exactly `INSTRUMENTS` (lemi423, lemi424, edl, phoenix,
orangebox) or the EDL default is not
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
`instrument_of` does not name each one's recorder (the mixed folder
lemi423 in a lemi423 survey and lemi424 in a lemi424 survey: the survey's
instrument is preferred), or a site's own `instrument:` does not win over
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

And the declination keys: `SiteConfig` does not default `declination`,
`declination_model` and `declination_epoch` to None (unset, not 0.0); a
site's own 0.0 does not stay 0.0, distinct from unset; a `defaults:`
declination does not reach a site without its own, or a site's own does
not win; `SITE_TABLE_COLUMNS` does not type them float, str, float; a site
table CSV does not read them; or the GUI Metadata table does not round trip
them: the tab's `COLUMNS` lacks one, `format_cell` then `parse_cell` does not
give each value back ("-" for None back to None), or
`survey_file.edit` (what the tab's Save calls) on a scratch survey.yaml does
not write -1.07, IGRF-14 and 2023.53 that `Survey.site` reads back while the
other site's entry is unchanged. The GUI functions import PySide6 and make no
widget. Control: the same round trip with the epoch cell typed "2023.5x"
must raise ValueError.

And `layout_north`: `SiteConfig` does not default it to "magnetic"; a
`defaults:` "geographic" does not reach a site without its own, or a
site's own "magnetic" does not win; `mt_workbench.products.apply_site_frame`
does not set ``orientation.reference_frame`` geomagnetic for magnetic and
geographic for geographic on an mt_metadata Station whose default is
geographic; the Morocco survey.yaml does not give "magnetic" for B03 (from
its `defaults:`). Control: a site with `layout_north: north` must raise
ValueError when built.

And the unknown keys: a site entry with `model` (a key `SiteConfig` does
not declare) or a `defaults:` block with `bogus_key` does not raise
ValueError naming the key and where it came from (site entry or
defaults:), or a site with only known keys is refused. The mutation:
with `_check_known_keys` made a no-op, `Survey.site` must raise TypeError
instead, which the check must report as a failure.

And the Phoenix keys and the burst site: in a scratch data root with a
Phoenix folder G5 (one synthetic `.td_150` name), `Survey.site("G5")` does
not carry `recording`, `calibration_dir` and `coil_hx` as declared, or a
coil serial and receiver id written as YAML integers do not come back as
text; the burst site G5H (`bursts_of: G5`, `sample_rate: 24000`, `remote:
G8H`) does not get G5's dipoles, coils and calibration folder under the
name G5H with its own rate, remote and a `clock_offset_s` of 0.0, its
`instrument_of` is not phoenix, `sample_rate_of` not 24000, `raw_site` not
G5, `bursts_parent` not G5 (None for G5), or `site_dirs()` lists G5H. And
a burst entry with `dipole_length_ex`, with `derived_from`, with
`sample_rate: 150`, without `sample_rate`, naming itself, or naming a
derived site, is not refused with ValueError naming the problem. The
mutation: with `dipole_length_ex` added to `BURST_SITE_KEYS`, the refusal
of `dipole_length_ex` on G5H must fail.

And the burst site's clock: under a G5 declaring `clock_offset_s: -0.1148`
(the Kalkaroo continuous stream's delay), G5H does not resolve to 0.0 (its
bursts carry GPS time); a G5H entry declaring 0.05 does not resolve to 0.05
or is refused; G5 does not keep -0.1148 (the control); or a G5H entry
declaring 61.0 is not refused by `MAX_CLOCK_OFFSET_S`. The mutation:
`Survey._burst_site` copying the recorded site's offset, must fail the
check.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_workbench.survey import (  # noqa: E402
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
    from mt_workbench.survey import read_site_table
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


def _orange_reader_channels() -> set[str]:
    """Return the channels mt-io's Orange Box reader returns, read from a one-record synthetic file."""
    import tempfile
    from mt_io.uoa.orange import read_orange
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "HFM1-000.BIN"
        header = b" 00000001 \nTue May  2 14:56:00 2006\n 7A1"
        path.write_bytes(header + bytes([128, 0, 0] * 3 + [0] * 5 + [128, 0, 0] * 2 + [32])
                         + b" Tue May  2 14:56:00 2006\n")
        run = read_orange([str(path)], station_id="T", dipole_length_ex=1.0, dipole_length_ey=1.0,
                          electric_full_scale_uv=25000.0, magnetic_full_scale_nt=70000.0,
                          latitude=0.0, longitude=0.0, elevation=0.0)
        return set(run.dataset.data_vars)


def test_channel_presets() -> None:
    from mt_io.lemi.lemi424 import LEMI424
    from mt_io.uoa import UoACollection
    from mt_io.phoenix.readers.header import Header
    from mt_workbench.mtu5a import CHANNELS as MTU5A_CHANNELS
    # Phoenix: mt-io's channel tags (e1 e2 h1 h2 h3), as mt_workbench.phoenix renames them
    rename = {"e1": "ex", "e2": "ey", "h1": "hx", "h2": "hy", "h3": "hz"}
    from mt_workbench.instruments import LEMI424_RENAME
    produced = {"lemi423": {"hx", "hy", "hz", "ex", "ey"},
                "lemi424": {LEMI424_RENAME.get(c, c) for c in LEMI424().file_column_names},
                "edl": {comp for comp, _n in UoACollection.CHANNEL_MAP.values()},
                "phoenix": {rename[t] for t in Header().channel_map.values() if t in rename},
                "orangebox": _orange_reader_channels(),
                "mtu5a": set(MTU5A_CHANNELS)}  # the table's CHEX .. CHHZ, as mt_workbench.mtu5a stores them
    assert set(CHANNEL_PRESETS) == set(INSTRUMENTS) == {"lemi423", "lemi424", "edl", "phoenix", "orangebox",
                                                        "mtu5a"}, \
        list(CHANNEL_PRESETS)
    for instrument, presets in CHANNEL_PRESETS.items():
        for label, channels in presets.items():
            back = channels_from_label(label, instrument)
            assert back == channels and preset_label(back, instrument) == label, (instrument, label, back)
            assert set(channels) <= produced[instrument], (instrument, label, set(channels) - produced[instrument])
        print(f"  {instrument}: {len(presets)} presets round trip; default {default_preset(instrument)!r}")
    assert default_preset("lemi423") == "Ex Ey Bx By"
    assert default_preset("edl") == "Ex Ey Bx By Bz"
    assert list(CHANNEL_PRESETS["lemi424"])[:2] == ["E1 E2 Bx By Bz", "E1 E2 E3 E4 Bx By Bz"], \
        list(CHANNEL_PRESETS["lemi424"])
    assert channels_from_label(default_preset("lemi424"), "lemi424") == ["ex", "ey", "hx", "hy", "hz"]
    assert channels_from_label("Ex Ey Bx By Bz", "edl") == ["ex", "ey", "hx", "hy", "hz"]
    assert channels_from_label("Ex Ey Bx By", "lemi423") == ["ex", "ey", "hx", "hy"]
    assert preset_label(["HX", "hy", "Ey", "ex"], "lemi423") == "Ex Ey Bx By"
    assert channels_from_label("bx by bz", "lemi423") == ["hx", "hy", "hz"]
    assert channels_from_label("Bx By Bz", "lemi424") == ["hx", "hy", "hz"]
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
    assert channels_from_label("Bx By Bz E1 E2", "lemi424") == ["ex", "ey", "hx", "hy", "hz"]
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


def test_declination_keys() -> None:
    import tempfile

    import yaml

    from mt_workbench.survey import SITE_TABLE_COLUMNS, SiteConfig, read_site_table

    cfg = SiteConfig(name="X")
    assert (cfg.declination, cfg.declination_model, cfg.declination_epoch) == (None, None, None), cfg
    config = {"name": "t", "instrument": "lemi423", "data_root": ".",
              "sites": {"A": {}, "Z": {"declination": 0.0, "declination_model": "IGRF-14",
                                       "declination_epoch": 2023.53}}}
    survey = Survey(config, Path("."))
    assert survey.site("A").declination is None and survey.site("Z").declination == 0.0
    assert survey.site("Z").declination is not None  # 0.0 is a value, not unset
    with_default = Survey({**config, "defaults": {"declination": -1.5, "declination_model": "IGRF-14"}}, Path("."))
    assert with_default.site("A").declination == -1.5 and with_default.site("Z").declination == 0.0
    assert {k: SITE_TABLE_COLUMNS[k] for k in ("declination", "declination_model", "declination_epoch")} == \
        {"declination": float, "declination_model": str, "declination_epoch": float}
    with tempfile.TemporaryDirectory() as tmp:
        csv = Path(tmp) / "table.csv"
        csv.write_text("site,declination,declination_model,declination_epoch\nA,-1.07,IGRF-14,2023.53\n",
                       encoding="utf-8")
        rows, ignored = read_site_table(csv)
        assert rows == {"A": {"declination": -1.07, "declination_model": "IGRF-14", "declination_epoch": 2023.53}}, rows
        assert ignored == [], ignored

        from mt_workbench.gui import metadata_edit
        from mt_workbench.gui.tabs.metadata import COLUMNS, NUMBERS

        keys = ("declination", "declination_model", "declination_epoch")
        assert all(k in COLUMNS for k in keys) and {"declination", "declination_epoch"} <= NUMBERS
        assert all(k in metadata_edit.EDITABLE for k in keys)
        values = {"declination": -1.07, "declination_model": "IGRF-14", "declination_epoch": 2023.53}
        for key, value in values.items():
            text = metadata_edit.format_cell(key, value)
            assert metadata_edit.parse_cell(key, text) == value, (key, text)
            assert metadata_edit.parse_cell(key, metadata_edit.format_cell(key, None)) is None
        try:
            metadata_edit.parse_cell("declination_epoch", "2023.5x")
        except ValueError:
            pass
        else:
            raise AssertionError("control: a typed '2023.5x' epoch must raise")
        path = Path(tmp) / "survey.yaml"
        path.write_text("name: t\ninstrument: lemi423\ndata_root: .\nsites:\n  A:\n    latitude: 31.9\n"
                        "  B:\n    latitude: 32.0\n", encoding="utf-8")
        cells = {k: metadata_edit.parse_cell(k, metadata_edit.format_cell(k, v)) for k, v in values.items()}
        from mt_workbench import survey_file

        survey_file.edit(path, sites={"A": cells})
        back = Survey.from_yaml(path)
        got = {k: getattr(back.site("A"), k) for k in keys}
        assert got == values, got
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["sites"]["B"] == {"latitude": 32.0}
    print(f"  declination keys: None by default, 0.0 kept, defaults and own value; table CSV; GUI cells and "
          f"save round trip {got}; a bad epoch cell raises")


def test_layout_north() -> None:
    from mt_metadata.timeseries import Station

    from mt_workbench.products import apply_site_frame
    from mt_workbench.survey import SiteConfig

    assert SiteConfig(name="X").layout_north == "magnetic"
    config = {"name": "t", "instrument": "lemi423", "data_root": ".", "defaults": {"layout_north": "geographic"},
              "sites": {"A": {}, "M": {"layout_north": "magnetic"}}}
    survey = Survey(config, Path("."))
    assert survey.site("A").layout_north == "geographic" and survey.site("M").layout_north == "magnetic"
    frames = {}
    for name in ("A", "M"):
        station = Station()
        assert str(getattr(station.orientation.reference_frame, "value", "")) == "geographic"  # mt_metadata's default
        apply_site_frame(station, survey.site(name))
        frames[name] = str(getattr(station.orientation.reference_frame, "value", station.orientation.reference_frame))
    assert frames == {"A": "geographic", "M": "geomagnetic"}, frames
    morocco = Survey.from_yaml(REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "survey.yaml")
    assert morocco.defaults.get("layout_north") == "magnetic" and morocco.site("B03").layout_north == "magnetic"
    bad = Survey({**config, "sites": {"N": {"layout_north": "north"}}}, Path("."))
    try:
        bad.site("N")
    except ValueError as exc:
        refused = str(exc)
    else:
        raise AssertionError("control: layout_north north was accepted")
    print(f"  layout_north: default magnetic; defaults geographic -> A {frames['A']}, own magnetic -> M "
          f"{frames['M']}; Morocco B03 magnetic; control: {refused}")


def _unknown_key_refusal(survey: Survey, site: str) -> str:
    """Return the ValueError text `Survey.site` raises for a site, failing on any other outcome."""
    try:
        survey.site(site)
    except ValueError as exc:
        return str(exc)
    except TypeError as exc:
        raise AssertionError(f"{site}: TypeError, not ValueError: {exc}") from None
    raise AssertionError(f"{site}: an unknown key was accepted")


def test_unknown_key() -> None:
    import mt_workbench.survey as survey_module
    config = {"name": "t", "data_root": ".", "defaults": {"azimuth_ex": 0.0},
              "sites": {"A": {"model": "MTU-8A"}, "B": {"dipole_length_ex": 50.0}}}
    survey = Survey(config, Path("."))
    text = _unknown_key_refusal(survey, "A")
    assert "'model' (site entry)" in text, text
    assert survey.site("B").dipole_length_ex == 50.0
    other = Survey({**config, "defaults": {"bogus_key": 1}}, Path("."))
    text_d = _unknown_key_refusal(other, "B")
    assert "'bogus_key' (defaults:)" in text_d, text_d
    # mutation: without the check the dataclass's TypeError comes through, and the check must see it
    kept = survey_module._check_known_keys
    survey_module._check_known_keys = lambda *a, **k: None
    try:
        _unknown_key_refusal(survey, "A")
    except AssertionError as exc:
        tripped = str(exc)
    else:
        raise AssertionError("mutation: the TypeError passed the check")
    finally:
        survey_module._check_known_keys = kept
    assert "TypeError" in tripped, tripped
    print(f"  unknown keys: {text.split(';')[0]}; {text_d.split(';')[0]}; mutation tripped ({tripped[:40]}...)")


def _burst_refusals(root: Path) -> dict:
    """Return the ValueError text for each refused burst entry, or "ACCEPTED" where none was raised."""
    base = {"G5": {"serial": "10133"}, "G5L": {"derived_from": "G5", "sample_rate": 1.0}}
    cases = {"dipole_length_ex": {"bursts_of": "G5", "sample_rate": 24000, "dipole_length_ex": 50.0},
             "derived_from": {"bursts_of": "G5", "sample_rate": 24000, "derived_from": "G5"},
             "rate 150": {"bursts_of": "G5", "sample_rate": 150},
             "no rate": {"bursts_of": "G5"},
             "itself": {"bursts_of": "G5H", "sample_rate": 24000},
             "of derived": {"bursts_of": "G5L", "sample_rate": 24000}}
    out = {}
    for label, entry in cases.items():
        survey = Survey({"name": "t", "instrument": "phoenix", "data_root": str(root),
                         "sites": {**base, "G5H": entry}}, root)
        try:
            survey.site("G5H")
        except ValueError as exc:
            out[label] = str(exc)
        else:
            out[label] = "ACCEPTED"
    return out


def test_phoenix_keys_and_burst_site() -> None:
    import tempfile
    import mt_workbench.survey as survey_module
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "G5" / "3").mkdir(parents=True)
        (root / "G5" / "3" / "10133_5FA4809A_3_00000001.td_150").write_bytes(bytes(128))
        sites = {"G5": {"serial": 10133, "dipole_length_ey": 85.0, "coil_hx": 53674, "recording": ".",
                        "calibration_dir": "sensors", "clock_offset_s": 0.5},
                 "G5H": {"bursts_of": "G5", "sample_rate": 24000, "remote": "G8H"}}
        survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": 150, "data_root": str(root),
                         "sites": sites}, root)
        g5 = survey.site("G5")
        assert (g5.serial, g5.coil_hx, g5.recording, g5.calibration_dir) == ("10133", "53674", ".", "sensors"), g5
        g5h = survey.site("G5H")
        same = ("serial", "dipole_length_ey", "coil_hx", "calibration_dir", "recording")
        assert all(getattr(g5h, k) == getattr(g5, k) for k in same), g5h
        assert (g5.clock_offset_s, g5h.clock_offset_s) == (0.5, 0.0), (g5.clock_offset_s, g5h.clock_offset_s)
        assert (g5h.name, g5h.bursts_of, g5h.sample_rate, g5h.remote) == ("G5H", "G5", 24000.0, "G8H"), g5h
        assert survey.instrument_of("G5H") == survey.instrument_of("G5") == "phoenix"
        assert survey.sample_rate_of("G5H") == 24000.0 and survey.sample_rate_of("G5") == 150.0
        assert (survey.raw_site("G5H"), survey.raw_site("G5")) == ("G5", "G5")
        assert (survey.bursts_parent("G5H"), survey.bursts_parent("G5")) == ("G5", None)
        assert list(survey.site_dirs()) == ["G5"], list(survey.site_dirs())
        refused = _burst_refusals(root)
        accepted = [k for k, v in refused.items() if v == "ACCEPTED"]
        assert not accepted, accepted
        assert "dipole_length_ex on a burst site" in refused["dipole_length_ex"], refused["dipole_length_ex"]
        assert "derived_from on a burst site" in refused["derived_from"], refused["derived_from"]
        assert "sample_rate: 24000" in refused["rate 150"] and "None" in refused["no rate"], refused
        assert "names the site itself" in refused["itself"] and "derived or burst" in refused["of derived"], refused
        kept = survey_module.BURST_SITE_KEYS
        survey_module.BURST_SITE_KEYS = (*kept, "dipole_length_ex")
        try:
            mutated = _burst_refusals(root)["dipole_length_ex"]
        finally:
            survey_module.BURST_SITE_KEYS = kept
        assert mutated == "ACCEPTED", mutated
    print(f"  G5H from G5: serial {g5h.serial}, ey {g5h.dipole_length_ey}, coil_hx {g5h.coil_hx}, clock "
          f"{g5h.clock_offset_s}, rate {g5h.sample_rate:g}, remote {g5h.remote}; 6 bad burst entries refused; "
          f"mutation (dipole_length_ex allowed) accepted it, as it must")


def _burst_clocks(root: Path) -> dict:
    """Return G5's and G5H's resolved clock_offset_s under a G5 at -0.1148 s, for three G5H entries.

    Each value is the offset, or the ValueError text where `Survey.site` refused the entry.
    """
    entries = {"inherits": {}, "own 0.05": {"clock_offset_s": 0.05}, "own 61": {"clock_offset_s": 61.0}}
    out = {}
    for label, extra in entries.items():
        sites = {"G5": {"serial": "10133", "clock_offset_s": -0.1148},
                 "G5H": {"bursts_of": "G5", "sample_rate": 24000, **extra}}
        survey = Survey({"name": "t", "instrument": "phoenix", "sample_rate": 150, "data_root": str(root),
                         "sites": sites}, root)
        out[f"G5 ({label})"] = survey.site("G5").clock_offset_s
        try:
            out[label] = survey.site("G5H").clock_offset_s
        except ValueError as exc:
            out[label] = str(exc)
    return out


def _check_burst_clocks(root: Path) -> list[str]:
    """Return the failures of the burst-clock criterion of the module docstring."""
    got, bad = _burst_clocks(root), []
    if got["inherits"] != 0.0:
        bad.append(f"G5H under G5 at -0.1148 s resolves to {got['inherits']!r}, expected 0.0")
    if got["own 0.05"] != 0.05:
        bad.append(f"G5H declaring 0.05 resolves to {got['own 0.05']!r}")
    if not isinstance(got["own 61"], str) or "not a clock offset" not in got["own 61"]:
        bad.append(f"G5H declaring 61.0 resolves to {got['own 61']!r}, expected the MAX_CLOCK_OFFSET_S refusal")
    bad += [f"{k} resolves to {v!r}, expected -0.1148" for k, v in got.items() if k.startswith("G5 (") and v != -0.1148]
    return bad


def test_burst_site_clock_offset() -> None:
    import tempfile
    import mt_workbench.survey as survey_module
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "G5" / "3").mkdir(parents=True)
        (root / "G5" / "3" / "10133_5FA4809A_3_00000001.td_150").write_bytes(bytes(128))
        bad = _check_burst_clocks(root)
        assert not bad, bad
        got = _burst_clocks(root)
        kept = survey_module.Survey._burst_site

        def inheriting(self, name):
            config = kept(self, name)
            config.clock_offset_s = self.site(config.bursts_of).clock_offset_s
            return config

        survey_module.Survey._burst_site = inheriting
        try:
            trip = _check_burst_clocks(root)
        finally:
            survey_module.Survey._burst_site = kept
        assert trip and "expected 0.0" in trip[0], trip
    print(f"  G5 at {got['G5 (inherits)']}: G5H {got['inherits']}, G5H declaring 0.05 {got['own 0.05']}, "
          f"61.0 refused; mutation (the recorded site's offset copied) tripped: {trip[0]}")


def test_processing_overlap_keys() -> None:
    """This test fails if processing: overlap: / overlap_long: are not read as percentages by overlap_pct /
    overlap_pct_long, if they are not left out of `processing` (they are not band-scheme keywords), if an
    unset key does not read None, or if a value outside [0, 100) is not refused."""
    config = {"name": "t", "data_root": ".", "sites": {"A": {}},
              "processing": {"min_period": 0.2, "max_period": 1e5, "min_band_windows": 2, "overlap_long": 25}}
    survey = Survey(config, Path("."))
    assert survey.overlap_pct_long == 25.0 and survey.overlap_pct is None, (survey.overlap_pct_long, survey.overlap_pct)
    assert set(survey.processing) == {"min_period", "max_period"}, survey.processing
    assert survey.min_band_windows == 2
    both = Survey({**config, "processing": {**config["processing"], "overlap": 0}}, Path("."))
    assert both.overlap_pct == 0.0, both.overlap_pct
    for bad in (100, -1, 250):
        try:
            Survey({**config, "processing": {**config["processing"], "overlap_long": bad}}, Path(".")).overlap_pct_long
        except ValueError as exc:
            assert "overlap_long" in str(exc), exc
        else:
            raise AssertionError(f"overlap_long: {bad} was taken")
    assert Survey({**config, "processing": {}}, Path(".")).overlap_pct_long is None
    print("  processing: overlap_long 25 -> 25.0, overlap unset -> None, both left out of processing; 100/-1/250 refused")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  survey_unit ({len(tests)} tests)")
