"""Unit test for `bbmt.ingest`'s `ignore_filters` switch -- no reader, no MTH5 written.

    python tests/ingest_unit.py

`ingest_site` is driven here with its reader, its MTH5 class and its four
per-run helpers replaced by recorders, over one empty stand-in .B423 file in
the scratch directory: no real archive is opened or written, and what is left
under test is exactly the decision this change added.

**This test fails if** `default_archive_path` does not give
``<workspace>/mth5/<site>.h5`` normally and ``<site>_unfiltered.h5`` with
`ignore_filters=True`; a default ingest of a site with two declared filters
(one of them a `replace`) does not apply both -- `_replace_channels` once and
`apply_filters` once with the remaining entry -- and write an
"ingest filters (in order): ..." run comment naming them; `ignore_filters=True`
does not apply **neither** of them, write the run comment
"ingest filters: none (ignore_filters)" and return the `_unfiltered` path; or
`ignore_filters` changes anything else (the channel keep, the dipole
polarity, the coil/h_scale steps must still run once per run in both cases).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import bbmt.ingest as ingest  # noqa: E402
from bbmt.ingest import NO_FILTERS_COMMENT, default_archive_path, ingest_site  # noqa: E402
from bbmt.survey import Survey  # noqa: E402

SCRATCH = Path(
    r"C:\Users\joint\AppData\Local\Temp\claude\D--BEN-BBMT-Processing-2026"
    r"\7432a3ce-c47b-448e-8958-b1c946ec7c08\scratchpad\ingest_unit"
)
SITE = "D02"
FILTERS = [{"replace": {"hx": "A06"}},
           {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2}}]


# --------------------------------------------------------------- the stand-ins


class _Comments:
    def __init__(self):
        self.value = ""


class _RunMeta:
    def __init__(self):
        self.id = ""
        self.comments = _Comments()


class _Run:
    """What `ingest_site` touches on a RunTS once the helpers are recorders."""

    def __init__(self):
        self.dataset = {}
        self.filters = {}
        self.sample_rate = 1000.0
        self.run_metadata = _RunMeta()
        self.station_metadata = object()


class _RunGroup:
    def from_runts(self, run):
        pass


class _StationGroup:
    class _Meta:
        def update(self, other):
            pass

    def __init__(self):
        self.metadata = self._Meta()

    def write_metadata(self):
        pass

    def add_run(self, run_id):
        return _RunGroup()


class _MTH5:
    """Records that a file would have been written, and writes nothing."""

    opened: list[Path] = []

    def __init__(self, file_version=None):
        self.file_version = file_version

    def open_mth5(self, path, mode="w"):
        _MTH5.opened.append(Path(path))

    def add_survey(self, name):
        return None

    def add_station(self, name, survey=None):
        return _StationGroup()

    def close_mth5(self):
        pass


class Calls(dict):
    """What each recorder saw, per run."""


def make_survey(filters) -> Survey:
    """A one-site survey over a scratch data_root holding one empty .B423."""
    data_root = SCRATCH / "raw"
    (data_root / SITE).mkdir(parents=True, exist_ok=True)
    stamp = data_root / SITE / "1624510579.B423"
    if not stamp.exists():
        stamp.write_bytes(b"")
    config = {
        "name": "unit", "instrument": "lemi423", "sample_rate": 1000,
        "data_root": str(data_root), "workspace": str(SCRATCH / "work"),
        "sites": {SITE: {"channels": ["ex", "ey", "hx", "hy"], "filters": filters}},
    }
    return Survey(config, SCRATCH)


def run_ingest(filters, ignore_filters: bool):
    """`ingest_site` with every side effect recorded instead of performed."""
    survey = make_survey(filters)
    calls = Calls(replace=[], apply=[], keep=0, orientation=0, h_scale=0, runs=[])

    def fake_replace(run, _survey, spec, tag):
        calls["replace"].append(spec)
        return "replace magnetics: " + ", ".join(f"{c} <- {d}" for c, d in spec.items())

    def fake_apply(run, specs, fs, tag=""):
        calls["apply"].append(list(specs))
        return [f"{list(s)[0]}" for s in specs]

    def bump(key):
        def _fn(*_args, **_kwargs):
            calls[key] += 1
        return _fn

    original = {name: getattr(ingest, name) for name in
                ("read_lemi423", "MTH5", "_replace_channels", "apply_filters",
                 "_keep_channels", "_standardise_e_orientation", "_apply_h_scale")}
    try:
        ingest.read_lemi423 = lambda *_a, **_k: _Run()
        ingest.MTH5 = _MTH5
        ingest._replace_channels = fake_replace
        ingest.apply_filters = fake_apply
        ingest._keep_channels = bump("keep")
        ingest._standardise_e_orientation = bump("orientation")
        ingest._apply_h_scale = bump("h_scale")
        _MTH5.opened = []
        out = ingest_site(survey, SITE, ignore_filters=ignore_filters)
    finally:
        for name, value in original.items():
            setattr(ingest, name, value)
    # the comment written on the one run: read it back off the object the
    # fake reader handed out (ingest_site sets it in place)
    return survey, out, calls


# --------------------------------------------------------------------- tests


def test_default_archive_path() -> None:
    survey = make_survey(None)
    plain = default_archive_path(survey, SITE)
    unfiltered = default_archive_path(survey, SITE, ignore_filters=True)
    assert plain.name == f"{SITE}.h5", plain
    assert unfiltered.name == f"{SITE}_unfiltered.h5", unfiltered
    assert plain.parent == unfiltered.parent == survey.workspace / "mth5", plain.parent
    print(f"  default_archive_path: {plain.name} / {unfiltered.name} under {plain.parent}")


def test_declared_filters_are_applied_by_default() -> None:
    survey, out, calls = run_ingest(FILTERS, ignore_filters=False)
    assert out.name == f"{SITE}.h5", out
    assert calls["replace"] == [{"hx": "A06"}], calls["replace"]
    assert len(calls["apply"]) == 1 and list(calls["apply"][0][0]) == ["notch"], calls["apply"]
    assert calls["keep"] == calls["orientation"] == calls["h_scale"] == 1, dict(calls)
    print(f"  default: -> {out.name}, replace {calls['replace']}, "
          f"apply_filters on {[list(s)[0] for s in calls['apply'][0]]}")


def test_ignore_filters_applies_none_and_renames() -> None:
    survey, out, calls = run_ingest(FILTERS, ignore_filters=True)
    assert out.name == f"{SITE}_unfiltered.h5", out
    assert calls["replace"] == [] and calls["apply"] == [], dict(calls)
    assert calls["keep"] == calls["orientation"] == calls["h_scale"] == 1, dict(calls)
    print(f"  ignore_filters: -> {out.name}, no replace, no apply_filters, "
          f"the other three ingest steps still run once")


def test_run_comment() -> None:
    """The comment the run carries in each case, read off the run object itself."""
    seen = {}

    def capture(ignore: bool):
        survey = make_survey(FILTERS)
        run = _Run()
        original = {name: getattr(ingest, name) for name in
                    ("read_lemi423", "MTH5", "_replace_channels", "apply_filters",
                     "_keep_channels", "_standardise_e_orientation", "_apply_h_scale")}
        try:
            ingest.read_lemi423 = lambda *_a, **_k: run
            ingest.MTH5 = _MTH5
            ingest._replace_channels = lambda *_a, **_k: "replace magnetics: hx <- A06"
            ingest.apply_filters = lambda *_a, **_k: ["notch 50 Hz"]
            ingest._keep_channels = lambda *_a, **_k: None
            ingest._standardise_e_orientation = lambda *_a, **_k: None
            ingest._apply_h_scale = lambda *_a, **_k: None
            ingest_site(survey, SITE, ignore_filters=ignore)
        finally:
            for name, value in original.items():
                setattr(ingest, name, value)
        return run.run_metadata.comments.value

    seen[False] = capture(False)
    seen[True] = capture(True)
    assert seen[False].startswith("ingest filters (in order): "), seen[False]
    assert "replace magnetics: hx <- A06" in seen[False] and "notch 50 Hz" in seen[False], seen[False]
    assert seen[True] == NO_FILTERS_COMMENT, seen[True]
    print(f"  run comment, default : {seen[False]!r}")
    print(f"  run comment, ignored : {seen[True]!r}")


def test_apple_double_twins_are_skipped() -> None:
    """Fails if `select_files` or `Survey.site_dirs` counts a `._<epoch>.B423`
    AppleDouble twin (a Mac copy artefact) as a record, or drops the real file."""
    import tempfile
    from bbmt.ingest import b423_files, select_files
    from bbmt.survey import Survey
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / "S01"; site.mkdir()
        (site / "1677774771.B423").write_bytes(bytes([120]) * 64)
        (site / "._1677774771.B423").write_bytes(bytes([0, 5, 22, 7]) + bytes(60))
        ghost = root / "GHOST"; ghost.mkdir()
        (ghost / "._1677774772.B423").write_bytes(bytes(64))
        files = select_files(site)
        assert [f.name for f in files] == ["1677774771.B423"], [f.name for f in files]
        assert [f.name for f in b423_files(ghost)] == []
        survey = Survey({"name": "t", "data_root": str(root)}, root)
        assert list(survey.site_dirs()) == ["S01"], list(survey.site_dirs())
        print("  AppleDouble twin skipped; a folder holding only twins is not a site")


def test_glued_altitude_header_line() -> None:
    """Fails if a B423 header whose altitude line reads `%Alt1060.0,m 12 1`
    (firmware 2.1, four-digit altitudes, 47 Morocco sites) still raises in
    mt-io's coordinate parser once bbmt.ingest is imported, or if the
    ordinary `%Alt 125.2,m 12 1` form parses differently than before."""
    import bbmt.ingest  # installs the tolerant parser
    from mt_io.lemi.lemi423 import Read_Lemi_Header
    base = ["%LEMI423 #0011", "%FIRMWARE Ver.2.1", "%MADE in UKRAINE", " ", "%Date 2023/09/19",
            "%Time 16:32:57", "%Ubat 12.57V", "%Current 108.5mA", "%Free 30132MB",
            "%Lat 3209.28947,N", "%Lon 00309.35612,W", "%Alt1060.0,m 12 1", " "]
    reader = Read_Lemi_Header.__new__(Read_Lemi_Header)
    reader._extract_coordinates(base)
    assert abs(reader.elevation - 1060.0) < 1e-9 and abs(reader.latitude - 32.15482) < 1e-4, (reader.elevation, reader.latitude)
    assert reader.longitude < 0, reader.longitude  # W
    spaced = list(base); spaced[11] = "%Alt 125.2,m 12 1"
    reader._extract_coordinates(spaced)
    assert abs(reader.elevation - 125.2) < 1e-9, reader.elevation
    print("  glued '%Alt1060.0' parses to 1060.0 m; spaced form unchanged")


if __name__ == "__main__":
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  ingest_unit ({len(tests)} tests)")
