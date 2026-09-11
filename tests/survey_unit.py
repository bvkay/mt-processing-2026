"""Unit test for `bbmt.survey.distance_km` and `Survey.timezone` -- no Qt, no archive.

    python tests/survey_unit.py

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
file byte-for-byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from bbmt.survey import Survey, distance_km  # noqa: E402

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


def test_matlab_survey_csv_columns() -> None:
    """Fails if a MATLAB field-app survey CSV (SiteName, ExDipole, ExAzimuth,
    EyDipole, EyAzimuth, Latitude, Longitude, Elevation, Deployment_Notes,
    Pickup_Notes, TimeZone, ...) is not read into our site-table columns, or
    its two note columns are not joined into `notes`."""
    import tempfile
    from bbmt.survey import read_site_table
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
    print(f"  MATLAB CSV read: A01 {rows['A01']}, ignored {ignored}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  survey_unit ({len(tests)} tests)")
