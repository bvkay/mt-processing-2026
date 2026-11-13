# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.ingest

Checks the raw/variant split, the LEMI-423 path, one real hour of LEMI-424
and EDL, and the EDL and LEMI-423 calibration chains. `ingest_site` is
driven with its reader, its MTH5 class and its per-run helpers replaced by
recorders, over one empty stand-in .B423 file in the scratch directory, so
the raw/variant decision is tested without opening or writing a real
archive. `filters_hash`, `build_variant`, `variant_ready` and
`archive_filter_kinds` are driven over small real MTH5 archives written
directly with the mth5 API (`_write_raw_archive`), since they read an
archive's run comments back from disk.

Usage:
    python tests/ingest_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `default_archive_path` gives anything but
``<workspace>/mth5/<site>.h5`` (`ignore_filters` is accepted and ignored, kept
only for old call sites); `ingest_site` applies a site's declared filters, or
its `replace` entry, to the raw archive at all, whatever `ignore_filters`
is, or writes a line about filters into the run comment (it carries only
the PR6-24 high-gain note, when there is one, the dc
level record and the coil-table record "calibration_sha256: ..."); or
`ignore_filters` changes anything else (the channel keep, the dipole
polarity, the coil/h_scale steps must still run once per run).

**`b423_files`** returns a record from a subfolder when the site folder itself holds records, or
returns nothing when the records sit only in a subfolder (a card copied whole).

**`filters_hash`** is not stable for the same list; does not change when the
same entries are given in a different *order*, or when one entry's parameter
(a notch's q) changes; or [] and None do not hash the same.

**`build_variant`**, on a small real one-run raw archive, does not write
hx/hy identical to `mt_workbench.noise.apply_filters_arrays` run directly on
the same raw arrays for the same notch; does not record `filters hash <hash>`
then the same provenance line `apply_filters_arrays` returned, in the run's
comment; or `variant_ready` does not read False before the build and True
after it, False again once the declared filters change (a new hash), and a
rebuild after that change does not leave exactly one ``<site>_f*.h5`` behind
(the stale one pruned). `archive_filter_kinds` must read [] off a raw
archive, the kinds back off a variant in order, and None off a path that does
not exist; `build_variant`/`processing_archive` must both refuse
(`ValueError` naming "old layout") a `<site>.h5` whose run comment already
carries a filter provenance line, as a pre-split `ingest_site` would have
left one; and `variant_ready` must not read True off a ``.part`` temp file
(`build_variant`'s own in-progress name, `os.replace`d onto the finished one
only once every run is written) or off a finished-name file whose later run
lacks the recorded hash (what an interrupted, non-atomic write could
otherwise leave behind for a crashed campaign job to pick up as "ready").

**The freshness record** (workbench issue 20): a variant
must record, after its hash, ``source: <stem> size <bytes> mtime <time>
sha256_head <hex>`` of its raw archive (computed here from the definition),
``calibration_sha256: <hex>`` as the raw archive records it and ``donor:
<identity>`` per `replace` donor, each a piece mt_metadata's EMTF XML
parser can set; it fails if `variant_ready` reads True after the raw
archive is rewritten (hx and hy exchanged, the filters hash unchanged),
after one of its bytes changes under the recorded size and mtime, after the
coil table it records changes, or after a donor's raw archive is
rewritten; if a variant without the record (built by an earlier version) does
not read ready, with a WARNING that it is judged by file time, while newer
than its raw archive, or reads ready once the raw archive is rewritten
after it (the Nador P4S7 and P4S8 case); if the
rebuilt variant does not hold the notch of the rewritten raw hx; if
`build_variant` and `processing_archive` (variant and raw) do not refuse a
raw archive whose recorded table has changed; or if the controls do not
read ready again (the original bytes and mtime back, the original table
back). A raw archive without the table record gives a variant recording
"unknown", which a table edit does not make stale. A real LEMI-423 ingest
with a `calibration_fn` must record the sha256 of that file.

**The LEMI-423 path is unchanged** (the per-instrument dispatch):
with the same recorders, a LEMI-423 site's one file must reach
`read_lemi423` exactly as before (the file itself, not a list, and keyword
arguments exactly {station_id, dipole_length_ex, dipole_length_ey}), and the
LEMI-424/EDL reader (`read_run`) must never be called; any call fails the
test.

**The declination is stored, not applied** (`test_lemi423_declination_stored`):
a synthetic LEMI-423 site declaring declination -1.07, IGRF-14, 2023.55 must
be archived with that value, model and epoch in the station's
``location.declination``, the reader's geomagnetic frame, no
``translated_azimuth`` on any channel and hy at 90; the control without the
keys must be archived with 0.0 and no epoch. The same site with
`layout_north: geographic` must be archived with the reference frame
geographic and the declination still stored (the frame follows the key, not
the reader's geomagnetic).

**The frame follows layout_north for every reader**: the LEMI-424 (MBJ21)
and EDL (EGFLP02) archives of the one-hour test must carry the reference
frame geomagnetic (the default layout_north, magnetic). Control: the
LEMI-424 reader's own run, read from the same file without
`apply_site_frame`, must carry mt_metadata's geographic default.

**One real hour per new instrument** (`tests/instrument_samples.py` cuts
them from MBJ21, LEMI-424, and EGFLP02, EDL, into the scratch folder and
`scripts/new_survey.py` writes the mixed survey over them): `ingest_site`
into that survey's scratch workspace fails the test if the archive does not
open read-only with exactly one run, named sr1_0001 (LEMI-424) / sr10_0001
(EDL), whose channels are exactly the stored names the survey declares
(ex ey e3 e4 hx hy hz, no temperature channel / ex ey hx hy hz) at 1.0 /
10.0 Hz with 3600 / 36000 samples from 2024-10-25T00:00:00 / 2019-01-10T00:00:00
UTC; if the EDL hx chain is not the reader's Bartington coefficient
(142.857 nT -> uV) or the LEMI-424 ex chain is not the one stage
lemi424_e_sign (gain -1, recorded as applied); or if the archive's ex
samples differ from an independent read of the sample file with numpy
(LEMI-424: the 12th column of the text lines, E1, as the logger wrote it,
and ex divided by its scalar chain gain, `timefreq._scalar_gain`, equal to
minus that column, the e_sign convention; EDL: the EX file's values): the
archive must hold what the recorder wrote.

**An EDL stamp missing one channel's file**: on
seven synthetic 300 s stamps at 10 Hz, the second with no EX file, the fourth
with a second BX file under old/ (a test recording) and the fifth only
15 s long (a startup file),
`_group_contiguous` (with the rate) must give the runs [1], [3], [5], [6, 7] and leave
the second and fourth out, and every file's stretch of every archived channel must
equal the file stamped at that stretch's own time (h5py and numpy only).
The old grouping made one run in which mt-io's reader put the third EX file
at the second stamp's time, and the spacing rule alone ran the 15 s file on into the next.

**EDL files named for another station** than the site's recorder.ini (here
PLB03_ stamps a month earlier and an "XX_" stamp inside the site's own
record) must not reach `record_files`, the span or the archive, which must be
exactly the own files; a recorder.ini naming no file's station keeps them all.

**A LEMI-423 site with a `calibration_fn`** and `h_scale: -1000`, ingested
from one synthetic B423 file, must be archived with hx's and hy's chain the
mt-io fork's, physical to recorded: the .rsp table (nanoTesla ->
nanoTesla; amplitudes and phases equal to the file read with numpy), the
reader's linear stage (nanoTesla -> digital counts, gain 1/K), then
`lemi423_b_scale` (-1000, counts -> counts), each stage's units_in the
previous stage's units_out, and ex with neither the coil nor the b_scale
stage. Stock mt-io raises there instead (its coil table's "millivolts").

**An EDL site declared `sensor_type: lemi120`** (LEMI-120 coils on the PR6-24)
must be archived with, on hx and hy, the .rsp table (amplitudes
and phases equal to the file read with numpy) then mt-io's 400000 uV/nT
flat-band gain, its electric chain and its samples unchanged; lemi120 without
a `calibration_fn`, or an unknown sensor_type, must raise instead of ingesting.

**An EDL site declared `electric_gain: 10.0`** (the electric chain's gain
declared from the field notes: a field-notes fact, not a PR6-24 setting), ingested
from the same synthetic files as the same site with no key (1.0, no filter),
must be archived with every channel's stored samples identical to the
other archive's and to the files (the words stay as stored); ex's and ey's
chain the other's plus one filter, `uoa_electric_gain`, a CoefficientFilter of
gain 10.0 microVolt -> microVolt whose comment (the archive's HDF5 attribute)
names "the field notes" and which the default-gain archive lacks, so that
each's calibrated series (mth5's `remove_instrument_response`, what the chain
means) is exactly 0.1 x the default-gain archive's own (to 1e-12); hx, not an
electric channel, calibrated identically to the other archive's. The run
comment must carry "electric gain 10 on ['ex', 'ey'] (declared from the field
notes)" and the default-gain archive's no such line. The key in the own entry
of a site that is not an EDL must raise before the existing archive is
touched.

**The raw DC level at ingest**: a LEMI-423 site ingested from two
synthetic B423 files of 4 s, one run each (`max_run_files` 1), with ex,
hx and hy at +2e7, +4.3e7 and +3.9e7 counts (Gaussian noise 2e6) in both
runs and ey at 1.6e9 counts (noise 1e3, the level of the Morocco survey's
C05 ey and C13 ey) in sr1000_0001 and at -3e7 (noise 2e6) in sr1000_0002,
fails the test if sr1000_0001's comment, read with h5py, does not record
ey "open input?" and ex, hx and hy "ok", or sr1000_0002's does not record
all four "ok"; if a recorded median differs from the median of the
channel's samples read here from the archive with h5py and numpy by more
than the record's rounding (4 significant digits); if
`mt_workbench.dclevel.recorded_levels` does not give back those verdicts; if
`mt_workbench.dclevel.flag_line` of the one flagged row is not "S01 sr1000_0001
ey: median 1.60e9 counts, open input?"; or if
`mt_workbench.dclevel.channel_summary` does not give ey "open input?" at 1.6e9 in
1 of its 2 runs and the other channels "ok".

It also fails if `readable_b423` does not leave out a B423 file whose
1024-byte header block is all zero (naming it, with the reason) or a
file with no records while keeping the readable files, or does not refuse
a folder of ten or more files whose median file holds under one percent of
the interval between file names, with a message about card space; or if
the same files, read at a sample rate of 1 Hz (R05's native rate), are
not accepted in full while they stay refused at 1000 Hz.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import default_archive_path, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

sys.path.insert(0, str(REPO / "tests"))
import instrument_samples  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("ingest_unit")
SITE = "D02"
# a `replace` and a `notch`, declared to show that `ingest_site` leaves both alone;
# they are applied by `mt_workbench.noise.apply_filters_arrays` through `build_variant`
FILTERS = [{"replace": {"hx": "A06"}},
           {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2}}]


# --------------------------------------------------------------- the stand-ins


class _Comments:
    """Stand-in for a metadata comment with a `value`."""

    def __init__(self):
        self.value = ""


class _RunMeta:
    """Stand-in for run metadata: an id and a comment."""

    def __init__(self):
        self.id = ""
        self.comments = _Comments()


class _StationMeta:
    """Stand-in for station metadata: the orientation `apply_site_frame` sets."""

    def __init__(self):
        self.orientation = type("Orientation", (), {"reference_frame": None})()


class _Run:
    """Stand-in for the parts of a RunTS that `ingest_site` touches once the helpers are recorders."""

    def __init__(self):
        self.dataset = {}
        self.filters = {}
        self.sample_rate = 1000.0
        self.run_metadata = _RunMeta()
        self.station_metadata = _StationMeta()


class _RunGroup:
    """Stand-in for an mth5 run group; writes nothing."""

    def from_runts(self, run):
        pass


class _StationGroup:
    """Stand-in for an mth5 station group; writes nothing."""

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
    """Stand-in for MTH5 that records the files it would open and writes nothing."""

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
    """The calls each recorder saw, per run."""


def make_survey(filters) -> Survey:
    """Build a one-site survey over a scratch data_root holding one empty .B423."""
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
    """Run `ingest_site` with every side effect recorded instead of performed.

    The recorders stand in for `read_lemi423` (its calls), `MTH5` (the files
    it opens), `readable_b423` (the empty stand-in file passes), and
    `_keep_channels`, `_standardise_e_orientation` and `_apply_h_scale`
    (call counts); `read_run` fails the test if reached.
    None concerns the declared filters: `ingest_site` applies none of them
    (`mt_workbench.ingest.build_variant` applies them all through
    `mt_workbench.noise.apply_filters_arrays`, `replace` by `_replace_from_donors`),
    whatever `filters` declares.

    Returns:
        tuple: (survey, the archive path returned, the Calls recorded).
    """
    survey = make_survey(filters)
    calls = Calls(keep=0, orientation=0, h_scale=0, runs=[], read=[])

    def bump(key):
        """Return a recorder that counts its calls under `key`."""
        def _fn(*_args, **_kwargs):
            calls[key] += 1
        return _fn

    def read(*args, **kwargs):
        """Record a reader call and return a stand-in run."""
        calls["read"].append((args, kwargs))
        return _Run()

    def not_this_reader(*_args, **_kwargs):
        """Fail the test: the LEMI-423 path reached the LEMI-424/EDL reader."""
        raise AssertionError("the LEMI-423 path called read_run (the LEMI-424/EDL reader)")

    original = {name: getattr(ingest, name) for name in
                ("read_lemi423", "read_run", "MTH5", "readable_b423", "_keep_channels",
                 "_standardise_e_orientation", "_apply_h_scale")}
    try:
        ingest.read_lemi423 = read
        ingest.readable_b423 = lambda files, **kw: (files, [])
        ingest.read_run = not_this_reader
        ingest.MTH5 = _MTH5
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
    ignored = default_archive_path(survey, SITE, ignore_filters=True)
    assert plain.name == f"{SITE}.h5", plain
    assert plain == ignored, f"ignore_filters must no longer change the path: {plain} vs {ignored}"
    assert plain.parent == survey.workspace / "mth5", plain.parent
    print(f"  default_archive_path: always {plain.name} under {plain.parent} (ignore_filters accepted, ignored)")


def test_ingest_site_never_touches_filters() -> None:
    """Check that `ingest_site` writes the raw archive without applying declared filters.

    Holds whatever `site.filters` declares (a `replace` included) and
    whatever `ignore_filters` is: the calibration steps (channel keep, dipole
    polarity, coil/h_scale) run once a run, and no filter step is reached.
    """
    for ignore in (False, True):
        survey, out, calls = run_ingest(FILTERS, ignore_filters=ignore)
        assert out.name == f"{SITE}.h5", (ignore, out)
        assert calls["keep"] == calls["orientation"] == calls["h_scale"] == 1, (ignore, dict(calls))
        print(f"  ignore_filters={ignore}: -> {out.name}; the three calibration steps ran once; "
              f"the declared replace+notch were never reached (no such recorder exists any more)")


def test_run_comment_carries_no_filters() -> None:
    """Check that the raw run's comment records no filters whatever `ignore_filters` is.

    The filter provenance is written by `build_variant` into the variant's
    run comment. The raw run's comment is exactly the coil-table record,
    "calibration_sha256: none", since the site declares no `calibration_fn`.
    """
    seen = {}

    def capture(ignore: bool):
        """Run ingest_site with stand-ins and return the run comment it set."""
        survey = make_survey(FILTERS)
        run = _Run()
        original = {name: getattr(ingest, name) for name in
                    ("read_lemi423", "MTH5", "readable_b423", "_keep_channels",
                     "_standardise_e_orientation", "_apply_h_scale")}
        try:
            ingest.read_lemi423 = lambda *_a, **_k: run
            ingest.MTH5 = _MTH5
            ingest.readable_b423 = lambda files, **kw: (files, [])
            ingest._keep_channels = lambda *_a, **_k: None
            ingest._standardise_e_orientation = lambda *_a, **_k: None
            ingest._apply_h_scale = lambda *_a, **_k: None
            ingest_site(survey, SITE, ignore_filters=ignore)
        finally:
            for name, value in original.items():
                setattr(ingest, name, value)
        return run.run_metadata.comments.value

    seen[False], seen[True] = capture(False), capture(True)
    assert seen[False] == seen[True] == "calibration_sha256: none", seen
    print(f"  run comment, ignore_filters=False and True: both {seen[False]!r} (no filter provenance at ingest any more)")


# ------------------------------------------------- filters_hash / variants


def _write_raw_archive(path: Path, site: str, survey_name: str, data: dict, fs: float, t0: str,
                       comment: str = "") -> None:
    """Write a minimal real raw MTH5.

    Args:
        path (Path): Archive to write, replacing any existing file.
        site (str): Station name.
        survey_name (str): Survey id.
        data (dict): One 1-D array per channel ({comp: array}).
        fs (float): Sample rate in Hz; the run is ``sr<fs>_0001``.
        t0 (str): Start time.
        comment (str): Run comment: empty for a genuine raw archive, a
            filter-provenance string to fabricate an "old layout" one.
    """
    import pandas as pd
    from mth5.mth5 import MTH5

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    n = len(next(iter(data.values())))
    start = pd.Timestamp(t0)
    end = start + pd.Timedelta(seconds=(n - 1) / fs)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(survey_name)
        station = m.add_station(site, survey=survey_name)
        station.write_metadata()
        run = station.add_run(f"sr{int(fs)}_0001")
        for comp, values in data.items():
            ch = run.add_channel(comp, "magnetic", values.astype("float32"))
            ch.metadata.component = comp
            ch.metadata.sample_rate = fs
            ch.metadata.time_period.start = str(start)
            ch.metadata.time_period.end = str(end)
            ch.metadata.units = "digital counts"
            ch.write_metadata()
        run.metadata.sample_rate = fs
        run.metadata.time_period.start = str(start)
        run.metadata.time_period.end = str(end)
        if comment:
            run.metadata.comments = comment
        run.write_metadata()
        station.metadata.time_period.start = str(start)
        station.metadata.time_period.end = str(end)
        station.write_metadata()
    finally:
        m.close_mth5()


VARIANT_FS = 10.0
VARIANT_SURVEY_NAME = "variant_unit"
NOTCH_A = [{"notch": {"f0": 5.0, "harmonics": 2, "q": 10.0, "passes": 1}}]
NOTCH_B = [{"notch": {"f0": 5.0, "harmonics": 2, "q": 8.0, "passes": 1}}]  # differing q


def _variant_survey(site: str, filters) -> Survey:
    """Build a one-site survey at VARIANT_FS declaring `filters`."""
    config = {
        "name": VARIANT_SURVEY_NAME, "instrument": "lemi423", "sample_rate": VARIANT_FS,
        "data_root": str(SCRATCH / "variant_raw"), "workspace": str(SCRATCH / "variant_work"),
        "sites": {site: {"filters": filters}},
    }
    return Survey(config, SCRATCH)


def test_filters_hash() -> None:
    a = [{"notch": {"f0": 50.0, "q": 30.0}}, {"hp": {"cutoff_hz": 0.01}}]
    b = [{"hp": {"cutoff_hz": 0.01}}, {"notch": {"f0": 50.0, "q": 30.0}}]  # reordered
    c = [{"notch": {"f0": 50.0, "q": 25.0}}, {"hp": {"cutoff_hz": 0.01}}]  # differing notch q
    from mt_workbench.ingest import filters_hash
    assert filters_hash(a) == filters_hash(list(a)), "the same list must hash the same"
    assert filters_hash(a) != filters_hash(b), "reordering the same entries must change the hash"
    assert filters_hash(a) != filters_hash(c), "a differing notch q must change the hash"
    assert filters_hash([]) == filters_hash(None), "[] and None ('nothing declared') must hash the same"
    print(f"  filters_hash: stable ({filters_hash(a)}); order-sensitive (!= {filters_hash(b)}); "
          f"q-sensitive (!= {filters_hash(c)}); [] == None ({filters_hash([])})")


def test_build_variant_bit_for_bit_and_lifecycle() -> None:
    """Check `build_variant` on a small real raw archive.

    The variant is bit-for-bit `apply_filters_arrays`, `variant_ready` is
    correct before and after, and one variant is kept after a
    declared-filter change.
    """
    import numpy as np
    from mth5.mth5 import MTH5
    from mt_workbench.ingest import archive_filter_kinds, build_variant, default_archive_path, variant_path, variant_ready
    from mt_workbench.noise import apply_filters_arrays

    site = "VD02"
    rng = np.random.default_rng(7)
    n = 2000
    hx = rng.normal(size=n).astype("float64") * 1000 + 5000
    hy = rng.normal(size=n).astype("float64") * 1000 - 3000
    survey = _variant_survey(site, NOTCH_A)
    raw_path = default_archive_path(survey, site)
    _write_raw_archive(raw_path, site, VARIANT_SURVEY_NAME, {"hx": hx, "hy": hy}, VARIANT_FS,
                       "2020-01-01T00:00:00+00:00")

    assert archive_filter_kinds(raw_path) == [], "a raw archive must record no filters"
    assert archive_filter_kinds(default_archive_path(survey, "NOPE")) is None, "a missing archive must read None"
    assert not variant_ready(survey, site), "a variant that does not exist yet must not read ready"

    out = build_variant(survey, site)
    assert out == variant_path(survey, site), (out, variant_path(survey, site))
    assert variant_ready(survey, site), "the just-built variant must read ready"
    assert archive_filter_kinds(out) == ["notch"], archive_filter_kinds(out)

    want, _lines = apply_filters_arrays({"hx": hx, "hy": hy}, VARIANT_FS, NOTCH_A, tag=site)
    m = MTH5()
    m.open_mth5(out, mode="r")
    try:
        run = m.get_station(site, survey=VARIANT_SURVEY_NAME).get_run(f"sr{int(VARIANT_FS)}_0001")
        got_hx, got_hy = run.get_channel("hx").hdf5_dataset[()], run.get_channel("hy").hdf5_dataset[()]
    finally:
        m.close_mth5()
    assert np.array_equal(got_hx, want["hx"].astype("float32")), "hx must equal apply_filters_arrays bit-for-bit"
    assert np.array_equal(got_hy, want["hy"].astype("float32")), "hy must equal apply_filters_arrays bit-for-bit"

    # a changed declared filter (q 10 -> 8): a new hash, not ready, and a
    # rebuild must prune the outdated variant
    survey2 = _variant_survey(site, NOTCH_B)
    assert not variant_ready(survey2, site), "a changed filters.yaml (a new hash) must not read ready"
    out2 = build_variant(survey2, site)
    variants = sorted((survey.workspace / "mth5").glob(f"{site}_f*.h5"))
    assert variants == [out2], f"exactly one variant must remain after a rebuild: {[p.name for p in variants]}"
    assert not out.exists(), "the outdated variant must be pruned"
    print(f"  build_variant: hx/hy bit-for-bit == apply_filters_arrays; variant_ready correct before/after/"
          f"after a change; one variant kept ({out.name} -> {out2.name})")


def test_old_layout_refused() -> None:
    """Check that an old-layout archive is refused.

    A `<site>.h5` whose run comment already carries a filter provenance line,
    as a pre-split `ingest_site` left it, must make `build_variant` and
    `processing_archive` raise, naming "old layout".
    """
    import numpy as np
    from mt_workbench.ingest import build_variant, default_archive_path, processing_archive

    site = "OLDSITE"
    survey = _variant_survey(site, NOTCH_A)
    old_path = default_archive_path(survey, site)
    _write_raw_archive(
        old_path, site, VARIANT_SURVEY_NAME, {"hx": np.arange(500, dtype="float64")}, VARIANT_FS,
        "2020-01-01T00:00:00+00:00",
        comment="ingest filters (in order): notch f0=50 Hz harmonics=9 q=30 passes=2 zero-phase on [hx]",
    )
    for fn in (lambda: build_variant(survey, site), lambda: processing_archive(survey, site)):
        try:
            fn()
        except ValueError as exc:
            assert "old layout" in str(exc), exc
            continue
        raise AssertionError("an old-layout archive did not raise ValueError")
    print("  an archive with filters baked in (old layout) is refused by build_variant and processing_archive")


def test_variant_ready_rejects_a_partial_file() -> None:
    """Check that `variant_ready` refuses partial files.

    A `.part` temp name (`build_variant` writing) or a finished-name archive
    whose later run lacks the recorded hash (what an interrupted, non-atomic
    write could leave) must not read as ready.
    """
    import numpy as np
    import pandas as pd
    from mth5.mth5 import MTH5
    from mt_workbench.ingest import (
        _all_real_run_comments, archive_identity, default_archive_path, filters_hash, variant_path, variant_ready,
    )

    site = "VPART"
    survey = _variant_survey(site, NOTCH_A)
    raw_path = default_archive_path(survey, site)
    hx = np.arange(200, dtype="float64")
    _write_raw_archive(raw_path, site, VARIANT_SURVEY_NAME, {"hx": hx}, VARIANT_FS, "2020-01-01T00:00:00+00:00")
    h = filters_hash(NOTCH_A)
    # the hash and a freshness record that hold for this raw archive, so that only the
    # missing hash of the second run below can make variant_ready refuse
    good_comment = (f"filters hash {h}; source: {archive_identity(raw_path)}; calibration_sha256: unknown; "
                    f"ingest filters (in order): notch f0=5 Hz harmonics=2 q=10 passes=1 zero-phase on [hx]")
    out_path = variant_path(survey, site)
    _write_raw_archive(out_path, site, VARIANT_SURVEY_NAME, {"hx": hx}, VARIANT_FS, "2020-01-01T00:00:00+00:00",
                       comment=good_comment)
    assert variant_ready(survey, site), "control: one run with the hash and a current record must read ready"
    out_path.unlink()

    # a .part file (build_variant mid-write) must not read as the finished variant
    part_path = out_path.with_name(out_path.name + ".part")
    _write_raw_archive(part_path, site, VARIANT_SURVEY_NAME, {"hx": hx}, VARIANT_FS, "2020-01-01T00:00:00+00:00",
                       comment=good_comment)
    assert _all_real_run_comments(part_path) is None, "_all_real_run_comments must refuse a .part path"
    assert not variant_ready(survey, site), "a .part file lying around must not read as the finished variant"
    part_path.unlink()
    assert not variant_ready(survey, site), "no finished variant at all must not read ready either"

    # two runs under the finished name, only the first carrying the recorded
    # hash: what a non-atomic build_variant could leave after a crash between
    # the first run and the second
    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(VARIANT_SURVEY_NAME)
        station = m.add_station(site, survey=VARIANT_SURVEY_NAME)
        station.write_metadata()
        for i, comment in enumerate((good_comment, "")):
            t0 = pd.Timestamp("2020-01-01T00:00:00+00:00") + pd.Timedelta(seconds=i * 1000)
            t1 = t0 + pd.Timedelta(seconds=(hx.size - 1) / VARIANT_FS)
            run = station.add_run(f"sr{int(VARIANT_FS)}_000{i + 1}")
            ch = run.add_channel("hx", "magnetic", hx.astype("float32"))
            ch.metadata.sample_rate = VARIANT_FS
            ch.metadata.time_period.start = str(t0)
            ch.metadata.time_period.end = str(t1)
            ch.write_metadata()
            run.metadata.sample_rate = VARIANT_FS
            run.metadata.time_period.start = str(t0)
            run.metadata.time_period.end = str(t1)
            if comment:
                run.metadata.comments = comment
            run.write_metadata()
    finally:
        m.close_mth5()
    assert not variant_ready(survey, site), "a second run without the recorded hash must not read ready"
    out_path.unlink()
    print("  variant_ready: a .part file, and a finished-name file whose second run lacks the hash, both refused")


# ----------------------------------------- the freshness record (workbench issue 20)

COIL_RSP = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
T0 = "2020-01-01T00:00:00+00:00"


def _sha256(path: Path) -> str:
    """Return a file's sha256 hex digest, computed here."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _identity_here(path: Path) -> str:
    """Compute an archive's ``source:`` identity here from the definition in the issue.

    ``<stem> size <bytes> mtime <UTC, ISO 8601 basic, ns> sha256_head <sha256
    of the first MiB, then the size in decimal>``.
    """
    import hashlib
    import time
    st = path.stat()
    with open(path, "rb") as fh:
        head = fh.read(1 << 20)
    digest = hashlib.sha256(head + str(st.st_size).encode("ascii")).hexdigest()
    sec, ns = divmod(st.st_mtime_ns, 1_000_000_000)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(sec)) + f".{ns:09d}Z"
    return f"{path.stem} size {st.st_size} mtime {stamp} sha256_head {digest}"


def _fresh_survey(sites: dict) -> Survey:
    """Build a survey at VARIANT_FS with the given site entries, in its own workspace."""
    config = {"name": VARIANT_SURVEY_NAME, "instrument": "lemi423", "sample_rate": VARIANT_FS,
              "data_root": str(SCRATCH / "fresh_raw"), "workspace": str(SCRATCH / "fresh_work"), "sites": sites}
    return Survey(config, SCRATCH)


def _table_copy(name: str) -> Path:
    """Copy the LEMI-120 table into the scratch folder, so the test can edit it."""
    path = SCRATCH / "fresh_tables" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(COIL_RSP.read_bytes())
    return path


def _channel(path: Path, site: str, comp: str):
    """Read one channel of an archive's first run, read-only."""
    from mth5.mth5 import MTH5
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(site, survey=VARIANT_SURVEY_NAME).get_run(f"sr{int(VARIANT_FS)}_0001")
        return run.get_channel(comp).hdf5_dataset[()]
    finally:
        m.close_mth5()


def _comments(path: Path) -> list:
    """Return an archive's real run comments."""
    from mt_workbench.ingest import _all_real_run_comments
    return _all_real_run_comments(path)


def test_variant_follows_a_rebuilt_raw_archive() -> None:
    """Check that a variant built from a raw archive is not current once that archive is rewritten.

    **This test fails if** a variant just built is not ready; its run
    comment is not "filters hash <h>; source: <identity>; calibration_sha256:
    <the table's sha256>; ingest filters (in order): notch ...", with the
    identity computed here from the definition, or mt_metadata's EMTF XML
    run-comment parser cannot set one of its pieces; after the raw archive
    is rewritten with hx and hy exchanged (newer mtime; the variant's
    filters hash still matches, so the old hash-only rule kept it)
    `variant_ready` reads True, or `processing_archive` does not rebuild it
    into hx equal to the notch of the new raw hx (the old hy); or when the
    raw archive's bytes change under the recorded size and mtime (restored
    with os.utime) the variant reads ready, or it does not read ready again
    once the original bytes and mtime are back.
    """
    import os
    import numpy as np
    from mt_metadata.transfer_functions.io.emtfxml.metadata import Run as XmlRun
    from mt_workbench.ingest import build_variant, filters_hash, processing_archive, variant_path, variant_ready
    from mt_workbench.noise import apply_filters_arrays

    site = "VF01"
    table = _table_copy("vf01.rsp")
    survey = _fresh_survey({site: {"filters": NOTCH_A, "calibration_fn": str(table)}})
    raw = default_archive_path(survey, site)
    rng = np.random.default_rng(11)
    hx = rng.normal(size=1500) * 1000 + 4000
    hy = rng.normal(size=1500) * 700 - 2500
    cal = f"calibration_sha256: {_sha256(table)}"  # what ingest_site records for this table
    _write_raw_archive(raw, site, VARIANT_SURVEY_NAME, {"hx": hx, "hy": hy}, VARIANT_FS, T0, comment=cal)
    out = build_variant(survey, site)
    assert variant_ready(survey, site), "a variant just built must read ready"
    pieces = _comments(out)[0].split("; ")
    want = [f"filters hash {filters_hash(NOTCH_A)}", f"source: {_identity_here(raw)}", cal]
    assert pieces[:3] == want and pieces[3].startswith("ingest filters (in order): notch"), (pieces, want)
    xml_run = XmlRun()
    for piece in _comments(out)[0].split(";"):  # as the EMTF XML writer parses a run comment
        if piece.count(":") >= 1:
            key, value = piece.split(":", 1)
            xml_run.update_attribute(key.strip(), value.strip())

    before = raw.stat().st_mtime_ns
    _write_raw_archive(raw, site, VARIANT_SURVEY_NAME, {"hx": hy, "hy": hx}, VARIANT_FS, T0, comment=cal)
    assert raw.stat().st_mtime_ns > before, "premise: the rewrite has a newer mtime"
    stale_hash = all(c.startswith(f"filters hash {filters_hash(NOTCH_A)}; ") for c in _comments(out))
    assert stale_hash, "premise: the stale variant's filters hash still matches"
    assert not variant_ready(survey, site), "a variant of a rewritten raw archive must not read ready"
    rebuilt = processing_archive(survey, site)
    assert rebuilt == variant_path(survey, site) and variant_ready(survey, site), rebuilt
    notched, _lines = apply_filters_arrays({"hx": hy, "hy": hx}, VARIANT_FS, NOTCH_A, tag=site)
    same = np.array_equal(_channel(rebuilt, site, "hx"), notched["hx"].astype("float32"))
    assert same, "the rebuilt variant's hx must be the notch of the rewritten raw hx"

    st = raw.stat()
    original = raw.read_bytes()
    changed = bytearray(original)
    changed[len(changed) // 2] ^= 0xFF
    raw.write_bytes(bytes(changed))
    os.utime(raw, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert (raw.stat().st_size, raw.stat().st_mtime_ns) == (st.st_size, st.st_mtime_ns), "premise: size, mtime kept"
    assert not variant_ready(survey, site), "changed bytes under the recorded size and mtime must not read ready"
    raw.write_bytes(original)
    os.utime(raw, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert variant_ready(survey, site), "control: the original bytes and mtime back must read ready again"
    print(f"  {site}: ready when built; record {pieces[1][:60]}...; not ready after the raw rewrite (hash "
          f"unchanged); rebuilt hx = notch(new raw hx); a byte changed under the same size and mtime caught")


def test_variant_follows_the_coil_table() -> None:
    """Check that a variant is not current once the coil table its raw archive records has changed.

    **This test fails if** a variant built from a raw archive recording the
    table's sha256 is not ready; after one byte is appended to the table it
    reads ready, or `build_variant`, `processing_archive` and
    `processing_archive(use_filters=False)` do not refuse with a ValueError
    asking for a re-ingest (rebuilding the variant from that raw archive
    would only repeat the old table); with the original table back it does
    not read ready again; or a variant of a raw archive that records no
    table (ingested before the record) does not record "unknown" and stay
    ready through a table edit (nothing to compare against).
    """
    import numpy as np
    from mt_workbench.ingest import build_variant, processing_archive, variant_ready

    site, old = "VF02", "VF03"
    table = _table_copy("vf02.rsp")
    entry = {"filters": NOTCH_A, "calibration_fn": str(table)}
    survey = _fresh_survey({site: dict(entry), old: dict(entry)})
    data = {"hx": np.linspace(-1.0, 1.0, 800) * 3000}
    _write_raw_archive(default_archive_path(survey, site), site, VARIANT_SURVEY_NAME, data, VARIANT_FS, T0,
                       comment=f"calibration_sha256: {_sha256(table)}")
    _write_raw_archive(default_archive_path(survey, old), old, VARIANT_SURVEY_NAME, data, VARIANT_FS, T0)
    build_variant(survey, site)
    old_variant = build_variant(survey, old)
    assert variant_ready(survey, site) and variant_ready(survey, old), "both variants must read ready when built"
    assert _comments(old_variant)[0].split("; ")[2] == "calibration_sha256: unknown", _comments(old_variant)[0]

    original = table.read_bytes()
    table.write_bytes(original + bytes([10]))  # one byte appended
    try:
        assert not variant_ready(survey, site), "a variant must not read ready after its coil table changed"
        for label, call in (("build_variant", lambda: build_variant(survey, site)),
                            ("processing_archive", lambda: processing_archive(survey, site)),
                            ("raw processing_archive", lambda: processing_archive(survey, site, use_filters=False))):
            try:
                call()
            except ValueError as exc:
                assert "re-ingest" in str(exc) and "coil table" in str(exc), (label, exc)
            else:
                raise AssertionError(f"{label} did not refuse a raw archive of the old coil table")
        assert variant_ready(survey, old), "a variant recording an unknown table must not be judged by it"
    finally:
        table.write_bytes(original)
    assert variant_ready(survey, site), "control: the original table back must read ready again"
    print(f"  {site}: not ready after the table changed; build_variant and processing_archive (variant and raw) "
          f"refuse, asking for a re-ingest; ready again with the table back; {old} (no record) records unknown")


def test_variant_without_the_record() -> None:
    """Check the grandfather rule for a variant built before the record existed.

    **This test fails if** a variant whose run comment is what
    `build_variant` wrote before the record existed ("filters hash <h>; ingest
    filters (in order): ...", the hash current) and whose file is newer
    than its raw archive does not read ready, or no WARNING line says it is
    judged by file time; if, once the raw archive is rewritten (now newer
    than the variant, as Nador's P4S7 and P4S8 raw archives were), it
    reads ready; or if `processing_archive` does not then rebuild
    it into a variant that carries the record and reads ready.
    """
    import os
    import time
    import numpy as np
    from loguru import logger
    from mt_workbench.ingest import filters_hash, processing_archive, variant_path, variant_ready

    site = "VF04"
    survey = _fresh_survey({site: {"filters": NOTCH_A}})
    raw = default_archive_path(survey, site)
    data = {"hx": np.cos(np.arange(600) / 7.0) * 2000}
    _write_raw_archive(raw, site, VARIANT_SURVEY_NAME, data, VARIANT_FS, T0)
    old = (f"filters hash {filters_hash(NOTCH_A)}; ingest filters (in order): notch f0=5 Hz harmonics=2 q=10 "
           f"passes=1 zero-phase on [hx]")
    variant = variant_path(survey, site)
    _write_raw_archive(variant, site, VARIANT_SURVEY_NAME, data, VARIANT_FS, T0, comment=old)
    now = time.time_ns()
    os.utime(raw, ns=(now - 600 * 10**9, now - 600 * 10**9))  # the raw archive ingested first,
    os.utime(variant, ns=(now - 300 * 10**9, now - 300 * 10**9))  # the variant built from it after

    said = []
    sink = logger.add(lambda message: said.append(str(message)), level="WARNING")
    try:
        ready = variant_ready(survey, site)
    finally:
        logger.remove(sink)
    assert ready, "a record-less variant newer than its raw archive must read ready (the grandfather rule)"
    warned = [line for line in said if "WARNING" in line and "judged current by file time" in line]
    assert warned, said

    _write_raw_archive(raw, site, VARIANT_SURVEY_NAME, data, VARIANT_FS, T0)  # rebuilt after the variant
    assert raw.stat().st_mtime_ns > variant.stat().st_mtime_ns, "premise: the raw archive is now newer"
    assert not variant_ready(survey, site), "a record-less variant older than its rewritten raw archive is stale"
    rebuilt = processing_archive(survey, site)
    assert variant_ready(survey, site) and _comments(rebuilt)[0].split("; ")[1].startswith("source: VF04 size ")
    print(f"  {site}: record-less and newer than its raw archive: ready, with the warning; older than the "
          f"rewritten raw archive: not ready; processing_archive rebuilt it with the record")


def test_variant_follows_its_donor() -> None:
    """Check that a variant with a `replace` entry is not current once its donor's raw archive is rewritten.

    **This test fails if** the variant of a site whose hx is replaced from
    a donor does not record ``donor: <the donor raw archive's identity>``
    or is not ready when built; reads ready after the donor's raw archive
    is rewritten; or, rebuilt, does not record the rewritten donor and read
    ready.
    """
    import numpy as np
    from mt_workbench.ingest import build_variant, processing_archive, variant_ready

    site, donor = "VF05", "VF06"
    filters = [{"replace": {"hx": donor}}] + NOTCH_A
    survey = _fresh_survey({site: {"filters": filters}, donor: {}})
    rng = np.random.default_rng(5)
    _write_raw_archive(default_archive_path(survey, site), site, VARIANT_SURVEY_NAME,
                       {"hx": rng.normal(size=700), "hy": rng.normal(size=700)}, VARIANT_FS, T0)
    donor_raw = default_archive_path(survey, donor)
    _write_raw_archive(donor_raw, donor, VARIANT_SURVEY_NAME, {"hx": rng.normal(size=700)}, VARIANT_FS, T0)
    out = build_variant(survey, site)
    pieces = _comments(out)[0].split("; ")
    assert f"donor: {_identity_here(donor_raw)}" in pieces and variant_ready(survey, site), pieces[:4]
    _write_raw_archive(donor_raw, donor, VARIANT_SURVEY_NAME, {"hx": rng.normal(size=700)}, VARIANT_FS, T0)
    assert not variant_ready(survey, site), "a variant must not read ready after its donor's raw archive changed"
    rebuilt = processing_archive(survey, site)
    assert f"donor: {_identity_here(donor_raw)}" in _comments(rebuilt)[0].split("; ") and variant_ready(survey, site)
    print(f"  {site}: records donor {donor}'s identity; not ready after {donor}.h5 was rewritten; rebuilt and ready")


def test_lemi423_reader_call_unchanged() -> None:
    """Check that a LEMI-423 site reaches read_lemi423 with the file and the three keyword arguments."""
    survey, out, calls = run_ingest(FILTERS, ignore_filters=False)
    stamp = survey.data_root / SITE / "1624510579.B423"
    assert len(calls["read"]) == 1, calls["read"]
    args, kwargs = calls["read"][0]
    assert args == (stamp,), args
    assert kwargs == {"station_id": SITE, "dipole_length_ex": 0.0, "dipole_length_ey": 0.0}, kwargs
    assert survey.instrument_of(SITE) == "lemi423"
    print(f"  read_lemi423({stamp.name}, {kwargs}): once, exactly the old call; read_run never called")


def _independent_column(path: Path, column: int | None) -> "np.ndarray":
    """Read one column of a text sample file (or the whole file) with numpy."""
    import numpy as np
    return np.loadtxt(path, usecols=column) if column is not None else np.loadtxt(path)


def _check_archive(path: Path, site: str, run_id: str, comps: list[str], rate: float, n: int, start: str):
    """Read the one run of an archive, asserting its shape.

    Returns:
        tuple[dict, dict]: (channel -> samples, channel -> filter chain).
    """
    from mth5.mth5 import MTH5
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        station = m.get_station(site, survey="mixed")
        runs = [r for r in station.groups_list if r.startswith("sr")]
        assert runs == [run_id], runs
        run = station.get_run(run_id)
        assert sorted(run.groups_list) == sorted(comps), run.groups_list
        data, chains = {}, {}
        for comp in comps:
            ch = run.get_channel(comp)
            assert float(ch.metadata.sample_rate) == rate, (comp, ch.metadata.sample_rate)
            assert ch.hdf5_dataset.shape[0] == n, (comp, ch.hdf5_dataset.shape)
            assert str(ch.metadata.time_period.start).startswith(start), (comp, ch.metadata.time_period.start)
            data[comp] = ch.hdf5_dataset[()]
            chains[comp] = [(type(f).__name__, float(getattr(f, "gain", 1.0))) for f in ch.channel_response.filters_list]
    finally:
        m.close_mth5()
    return data, chains


def test_new_instruments_one_hour() -> None:
    """Check the ingest of one real hour of LEMI-424 (MBJ21) and EDL (EGFLP02)."""
    import time
    import numpy as np
    done = instrument_samples.mixed_survey()
    assert done.returncode == 0, done.stdout + done.stderr
    survey = Survey.from_yaml(instrument_samples.MIXED_YAML)
    assert survey.workspace.is_relative_to(instrument_samples.SCRATCH), survey.workspace
    cases = (
        ("MBJ21", "lemi424", "sr1_0001", ["ex", "ey", "e3", "e4", "hx", "hy", "hz"], 1.0, 3600,
         "2024-10-25T00:00:00", "ex", instrument_samples.LEMI424_FILE, 11),
        ("EGFLP02", "edl", "sr10_0001", ["ex", "ey", "hx", "hy", "hz"], 10.0, 36000,
         "2019-01-10T00:00:00", "ex", f"{instrument_samples.EDL_DAY}/{instrument_samples.EDL_STAMP}.EX", None),
    )
    from mth5.mth5 import MTH5
    from mt_workbench.ingest import select_files
    from mt_workbench.instruments import read_run

    frames = {}
    for site, instrument, run_id, comps, rate, n, start, check, source, column in cases:
        assert survey.instrument_of(site) == instrument, (site, survey.instrument_of(site))
        t = time.perf_counter()
        path = ingest_site(survey, site, overwrite=True)
        took = time.perf_counter() - t
        data, chains = _check_archive(path, site, run_id, comps, rate, n, start)
        m = MTH5()
        m.open_mth5(path, mode="r")
        try:
            ref = m.get_station(site, survey="mixed").metadata.orientation.reference_frame
            frames[site] = str(getattr(ref, "value", ref))
        finally:
            m.close_mth5()
        assert frames[site] == "geomagnetic", (site, frames[site])
        truth = _independent_column(survey.data_root / site / source, column)
        # E1 stored as ex as the logger wrote it; the e_sign convention (-1.0 unset) is the chain's stage
        assert np.array_equal(data[check], truth), (site, check, data[check][:3], truth[:3])
        if instrument == "edl":
            assert chains["hx"] == [("CoefficientFilter", 1e6 / 7000.0)], chains["hx"]
        else:
            assert chains["ex"] == [("CoefficientFilter", -1.0)], chains["ex"]
            assert np.array_equal(data[check] / chains["ex"][0][1], -truth), (site, "ex / chain gain is not -E1")
        print(f"  {site} ({instrument}): {path.name} in {took:.2f} s, run {run_id}, {comps} at {rate:g} Hz, "
              f"{n} samples from {start}; {check} == the file's own values; chain {chains[check if instrument == 'lemi424' else 'hx']}; "
              f"frame {frames[site]}")
    site_dir = survey.site_dirs()["MBJ21"]
    own = read_run("lemi424", select_files(site_dir, None, None, "lemi424"), survey.site("MBJ21"), site_dir)
    own_frame = str(getattr(own.station_metadata.orientation.reference_frame, "value",
                            own.station_metadata.orientation.reference_frame))
    assert own_frame == "geographic", f"control: the LEMI-424 reader's own frame is {own_frame}, not geographic"
    print(f"  control: the LEMI-424 reader's own run carries {own_frame}; the archive carries {frames['MBJ21']}")


def test_edl_lemi120_sensor_chain() -> None:
    """Check the coil chain of an EDL site declared `sensor_type: lemi120`.

    Fails if the site (LEMI-120 coils on the PR6-24) is archived
    with anything but the coil chain on hx and hy (the .rsp table, amplitudes
    and phases equal to the file read here with numpy, then mt-io's
    400000 uV/nT flat-band gain), or with its samples or electric chain
    changed; or if lemi120 without a `calibration_fn`, or an unknown
    sensor_type, ingests instead of raising.
    """
    import shutil
    import h5py
    import numpy as np
    from mth5.mth5 import MTH5
    rsp = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
    root = SCRATCH / "edl_lemi120"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "HSX"
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    truth = {}
    for k, stamp in enumerate(("120327050500", "120327051000")):
        for c, suffix in enumerate(("BX", "BY", "BZ", "EX", "EY")):
            values = (c + 1) * 1000 + k * 100 + np.arange(3000) % 97
            np.savetxt(site / f"HSX_{stamp}.{suffix}", values, fmt="%d")
            truth.setdefault(suffix, []).append(values.astype(float))

    def survey(**defaults):
        """Build the one-site EDL survey with extra defaults."""
        base = {"dipole_length_ex": 49.0, "dipole_length_ey": 51.0, "channels": ["ex", "ey", "hx", "hy"]}
        return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                       "workspace": str(root / "work"), "defaults": {**base, **defaults},
                       "sites": {"HSX": {}}}, root)

    path = ingest_site(survey(sensor_type="lemi120", calibration_fn=str(rsp)), "HSX", overwrite=True)
    table = np.loadtxt(rsp, skiprows=2)
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station("HSX", survey="t").get_run("sr10_0001")
        for comp in ("hx", "hy"):
            fap, gain = run.get_channel(comp).channel_response.filters_list
            assert (type(fap).__name__, fap.name) == ("FrequencyResponseTableFilter", f"lemi_120_{comp}_response"), fap.name
            assert np.allclose(fap.amplitudes, table[:, 1]) and np.allclose(np.rad2deg(fap.phases), table[:, 2]), comp
            assert (type(gain).__name__, float(gain.gain)) == ("CoefficientFilter", 400000.0), (gain.name, gain.gain)
        ex_chain = [(f.name, float(f.gain)) for f in run.get_channel("ex").channel_response.filters_list]
        assert ex_chain == [("uoa_dipole_ex_49.0m", -49.0), ("uoa_efield_terminal_box_gain", 10.0)], ex_chain
    finally:
        m.close_mth5()
    with h5py.File(path, "r") as h5:
        group = h5["Experiment/Surveys/t/Stations/HSX/sr10_0001"]
        for comp, suffix in (("hx", "BX"), ("ey", "EY")):
            assert np.array_equal(group[comp][()], np.concatenate(truth[suffix])), comp
    for bad, error in (({"sensor_type": "lemi120"}, FileNotFoundError), ({"sensor_type": "fluxgate"}, ValueError)):
        try:
            ingest_site(survey(**bad), "HSX", out_path=root / "work" / "bad.h5", overwrite=True)
        except error:
            continue
        raise AssertionError(f"{bad} ingested without raising {error.__name__}")
    print(f"  sensor_type lemi120: hx, hy = {rsp.name} table ({len(table)} rows, == numpy) then 400000 uV/nT; "
          f"ex chain {ex_chain}; samples untouched; lemi120 without calibration_fn and 'fluxgate' refused")


def test_edl_electric_gain() -> None:
    """Check the declared electric chain gain of an EDL site.

    Fails if `electric_gain: 10.0` does not make both ex and ey come out
    exactly 10x smaller than the same files read at the default gain (1.0),
    through the archive's own chain with the samples kept as the stored
    words, or touches hx; if the run comment does not say so; or if the key
    on a non-EDL site ingests.
    """
    import shutil
    import h5py
    import numpy as np
    from mth5.mth5 import MTH5
    root = SCRATCH / "edl_electric_gain"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "HGX"
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    rng = np.random.default_rng(21)
    words = {}
    for stamp in ("090320000000", "090320000500"):
        for suffix in ("BX", "BY", "BZ", "EX", "EY"):
            values = rng.integers(-2_000_000, 2_000_000, 3000)
            np.savetxt(site / f"HGX_{stamp}.{suffix}", values, fmt="%d")
            words.setdefault(suffix, []).append(values.astype(float))

    def survey(own=None, **defaults):
        """Build the one-site EDL survey with the site's own entry and extra defaults."""
        base = {"dipole_length_ex": 49.0, "dipole_length_ey": 51.0, "channels": ["ex", "ey", "hx", "hy"]}
        return Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"),
                       "workspace": str(root / "work"), "defaults": {**base, **defaults},
                       "sites": {"HGX": own or {}}}, root)

    low = ingest_site(survey(), "HGX", out_path=root / "work" / "low.h5", overwrite=True)
    high = ingest_site(survey(electric_gain=10.0), "HGX", out_path=root / "work" / "high.h5", overwrite=True)
    freqs = np.logspace(-4, 0.5, 12)
    got = {}
    for tag, path in (("low", low), ("high", high)):
        m = MTH5()
        m.open_mth5(path, mode="r")
        try:
            run = m.get_station("HGX", survey="t").get_run("sr10_0001")
            got[tag] = {"comment": str(run.metadata.comments.value or "")}
            for comp in ("ex", "ey", "hx"):
                ch = run.get_channel(comp)
                response = ch.channel_response
                got[tag][comp] = dict(
                    chain=[f.name for f in response.filters_list],
                    filters={f.name: f for f in response.filters_list},
                    complex=response.complex_response(freqs),
                    calibrated=ch.to_channel_ts().remove_instrument_response().ts)
        finally:
            m.close_mth5()
    with h5py.File(low, "r") as a, h5py.File(high, "r") as b:
        for comp, suffix in (("ex", "EX"), ("ey", "EY"), ("hx", "BX"), ("hy", "BY")):
            ga = a[f"Experiment/Surveys/t/Stations/HGX/sr10_0001/{comp}"][()]
            gb = b[f"Experiment/Surveys/t/Stations/HGX/sr10_0001/{comp}"][()]
            assert np.array_equal(gb, ga) and np.array_equal(gb, np.concatenate(words[suffix])), comp
        # mth5 reads a filter back without its comment, so the archive's own attribute is read here
        stored = dict(b["Experiment/Surveys/t/Filters/coefficient/uoa_electric_gain"].attrs)
        assert "field notes" in str(stored.get("comments")), stored
        assert "uoa_electric_gain" not in a["Experiment/Surveys/t/Filters/coefficient"], "default-gain archive has it"
    lo, hi = got["low"], got["high"]
    ratios = {}
    for comp in ("ex", "ey"):
        assert hi[comp]["chain"] == lo[comp]["chain"] + ["uoa_electric_gain"], (comp, lo[comp]["chain"], hi[comp]["chain"])
        gain = hi[comp]["filters"]["uoa_electric_gain"]
        assert (type(gain).__name__, float(gain.gain), gain.units_in, gain.units_out) == (
            "CoefficientFilter", 10.0, "microVolt", "microVolt"), (comp, gain.gain, gain.units_in, gain.units_out)
        # the declared-gain response is exactly 10x the default's at every test frequency; the
        # reference is read off the default archive, since the dipole length differs between ex and ey
        assert np.allclose(hi[comp]["complex"], 10.0 * lo[comp]["complex"], rtol=1e-12, atol=0), \
            (comp, hi[comp]["complex"][:3], lo[comp]["complex"][:3])
        ratio = hi[comp]["calibrated"] / lo[comp]["calibrated"]
        assert np.allclose(hi[comp]["calibrated"], 0.1 * lo[comp]["calibrated"], rtol=1e-12, atol=0), \
            (comp, np.nanmin(ratio), np.nanmax(ratio))
        ratios[comp] = ratio
    assert hi["hx"]["chain"] == lo["hx"]["chain"], hi["hx"]["chain"]
    assert np.array_equal(hi["hx"]["calibrated"], lo["hx"]["calibrated"])
    note = "electric gain 10 on ['ex', 'ey'] (declared from the field notes)"
    assert note in hi["comment"] and "electric gain" not in lo["comment"], (lo["comment"], hi["comment"])
    before = high.read_bytes()
    for bad, own in ((None, {"instrument": "lemi424", "electric_gain": 10.0}),):
        try:
            ingest_site(survey(own=own, **(bad or {})), "HGX", out_path=high, overwrite=True)
        except ValueError as exc:
            assert "electric_gain" in str(exc), exc
            continue
        raise AssertionError(f"{bad or own} ingested without raising ValueError")
    assert high.read_bytes() == before, "a refused ingest touched the existing archive"
    print(f"  electric_gain 10.0: samples == the files in both archives; ex chain {hi['ex']['chain']}, "
          f"ey chain {hi['ey']['chain']}; calibrated ex/default {np.nanmin(ratios['ex']):.15f} .. "
          f"{np.nanmax(ratios['ex']):.15f}, ey/default {np.nanmin(ratios['ey']):.15f} .. "
          f"{np.nanmax(ratios['ey']):.15f}; hx calibrated identically; comment {note!r}; "
          f"the key on a lemi424 site refused, the archive untouched")


def test_edl_files_of_another_station_left_out() -> None:
    """Check that EDL files named for another station are left out.

    Fails if an EDL site folder's files named for another station than its
    recorder.ini's (here PLB03_ stamps a month earlier and an "XX_" stamp
    inside the site's own record) reach
    `record_files`, the span or the archive, which must be exactly the own
    files, read here with numpy and h5py; or if a recorder.ini naming a
    station no file carries makes the site lose its files instead of keeping
    them all.
    """
    import shutil
    import h5py
    import numpy as np
    from mt_workbench.instruments import record_files, span
    root = SCRATCH / "edl_foreign"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "EDLZ"
    (site / "config").mkdir(parents=True)
    ini = "[recorder]\nstation_long_identifier={}\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5))
    (site / "config" / "recorder.ini").write_text(ini.format("EDLZ_"), encoding="utf-8")
    own = {}
    for prefix, stamp, n in (("EDLZ_", "190101000000", 3000), ("EDLZ_", "190101000500", 3000),
                             ("EDLZ_", "190101001000", 3000), ("PLB03_", "181201000000", 3000),
                             ("XX_", "190101000708", 100)):
        for c, suffix in enumerate(("BX", "BY", "BZ", "EX", "EY")):
            values = (c + 1) * 1_000_000 + int(stamp[-6:]) + np.arange(n)
            np.savetxt(site / f"{prefix}{stamp}.{suffix}", values, fmt="%d")
            if prefix == "EDLZ_":
                own.setdefault(suffix, []).append(values.astype(float))
    files = record_files(site, "edl")
    assert {f.name.split("_")[0] for f in files} == {"EDLZ"} and len(files) == 15, [f.name for f in files]
    start, end, n_stamps = span(site, "edl", files)
    assert (str(start), str(end), n_stamps) == ("2019-01-01 00:00:00+00:00", "2019-01-01 00:15:00+00:00", 3), (start, end)
    survey = Survey({"name": "t", "instrument": "edl", "data_root": str(root / "raw"), "workspace": str(root / "work"),
                     "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "channels": ["ex", "ey", "hx", "hy"]},
                     "sites": {"EDLZ": {}}}, root)
    path = ingest_site(survey, "EDLZ", overwrite=True)
    with h5py.File(path, "r") as h5:
        station = h5["Experiment/Surveys/t/Stations/EDLZ"]
        runs = sorted(n for n, g in station.items() if g.attrs.get("mth5_type") == "Run")
        assert runs == ["sr10_0001"], runs
        for comp, suffix in (("hx", "BX"), ("ex", "EX")):
            assert np.array_equal(station["sr10_0001"][comp][()], np.concatenate(own[suffix])), comp
    (site / "config" / "recorder.ini").write_text(ini.format("RENAMED_"), encoding="utf-8")
    assert len(record_files(site, "edl")) == 15, "a recorder.ini naming no file's station: the folder's own station not kept"
    nobody = site.rename(site.with_name("SITE_OF_NOBODY"))  # a folder named for no station either
    assert len(record_files(nobody, "edl")) == 25, "a recorder.ini and a folder naming no file's station dropped files"
    print(f"  PLB03 (a month earlier) and XX (inside the record) left out: {len(files)} files, span {start} to "
          f"{end}, one run == the own files; recorder.ini naming nobody's station keeps the folder's own 15, and all 25 "
          f"when the folder is named for nobody too")


def test_edl_stamp_missing_a_channel_splits_the_run() -> None:
    """Check that an EDL stamp missing a channel's file splits the run.

    Fails if an EDL stamp that lacks one channel's file (no EX), or has two
    for one channel (a test recording under old/ with the real files'
    stamps), is grouped into a run; if a file shorter than the time to the
    next stamp (15 s startup files, 300 s apart) does not end its run; or
    if any archived sample differs from
    the file stamped at its own time, read here with numpy and h5py alone.
    mt-io's reader joins each channel's files end to end, so grouping across
    such a stamp would put the third EX file at the second stamp's time (ex
    300 s early for the rest of the run) and every sample after a short file
    285 s early.
    """
    import shutil
    import h5py
    import numpy as np
    import pandas as pd
    from mt_workbench.ingest import _group_contiguous
    from mt_workbench.instruments import record_files
    root = SCRATCH / "edl_missing"
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "EDLX"
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{n}_samplerate=10\n" for n in range(5)), encoding="utf-8")
    fs, per_file = 10, 3000  # 300 s files at 10 Hz
    stamps = [
        "190101000000", "190101000500", "190101001000", "190101001500", "190101002000", "190101002500",
        "190101003000"]
    truth = {}
    (site / "old").mkdir()
    for k, stamp in enumerate(stamps):
        for c, suffix in enumerate(("BX", "BY", "BZ", "EX", "EY")):
            if k == 1 and suffix == "EX":
                continue  # the missing file
            n = 150 if k == 4 else per_file  # stamp 4: a 15 s file, the next stamp 300 s on
            values = (c + 1) * 1_000_000 + k * 10_000 + np.arange(n)
            np.savetxt(site / f"EDLX_{stamp}.{suffix}", values, fmt="%d")
            truth[(stamp, suffix)] = values.astype(float)
    # a test recording kept under old/: a second BX file with a stamp the real files have
    np.savetxt(site / "old" / f"EDLX_{stamps[3]}.BX", -np.arange(per_file), fmt="%d")
    files = record_files(site, "edl")
    got = [sorted({p.stem.split("_")[1] for p in g}) for g in _group_contiguous(files, None, "edl", rate=fs)]
    assert got == [[stamps[0]], [stamps[2]], [stamps[4]], [stamps[5], stamps[6]]], got
    by_spacing = [sorted({p.stem.split("_")[1] for p in g}) for g in _group_contiguous(files, None, "edl")]
    assert by_spacing == [[stamps[0]], [stamps[2]], stamps[4:]], by_spacing  # blind to the short file
    survey = Survey({"name": "t", "instrument": "edl", "sample_rate": fs, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0,
                                  "channels": ["ex", "ey", "hx", "hy"]},
                     "sites": {"EDLX": {}}}, root)
    path = ingest_site(survey, "EDLX", overwrite=True)
    checked = 0
    with h5py.File(path, "r") as h5:
        station = h5["Experiment/Surveys/t/Stations/EDLX"]
        runs = {n: g for n, g in station.items() if g.attrs.get("mth5_type") == "Run"}
        assert sorted(runs) == [f"sr10_000{i}" for i in range(1, 5)], sorted(runs)
        for run in runs.values():
            t0 = pd.Timestamp(run.attrs["time_period.start"])
            for comp, suffix in (("hx", "BX"), ("hy", "BY"), ("ex", "EX"), ("ey", "EY")):
                data, pos = run[comp][()], 0
                while pos < data.size:  # walk the run file by file: the file stamped at each position
                    stamp = (t0 + pd.Timedelta(seconds=pos / fs)).strftime("%y%m%d%H%M%S")
                    assert (stamp, suffix) in truth, (comp, stamp)
                    want = truth[(stamp, suffix)]
                    assert np.array_equal(data[pos:pos + want.size], want), (comp, stamp)
                    pos += want.size
                    checked += 1
                assert pos == data.size, (comp, pos, data.size)
    print(f"  runs {got} (by spacing alone {by_spacing}); the stamp without EX and the one with two BX "
          f"left out, the 15 s file ends its run; {checked} files' stretches of the archive == the file "
          f"stamped at their own time")


def test_apple_double_twins_are_skipped() -> None:
    """Check that AppleDouble twins are skipped.

    Fails if `select_files` or `Survey.site_dirs` counts a `._<epoch>.B423`
    AppleDouble twin (a Mac copy artefact) as a record, or drops the real
    file.
    """
    import tempfile
    from mt_workbench.ingest import b423_files, select_files
    from mt_workbench.survey import Survey
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


def test_stray_subfolder_records_are_left_out() -> None:
    """Check that a site folder's own records win over records in its subfolders.

    Fails if `select_files` returns a B423 record from a subfolder when the
    site folder itself holds records (Nador's P2S1: a stray one-hertz card
    of another logger in ``DATA0034`` beside the site's own files), or
    returns nothing when the records sit only in a subfolder (a card copied
    whole), or `Survey.site_dirs` stops recognising that site.
    """
    import tempfile
    from mt_workbench.ingest import b423_files, select_files
    from mt_workbench.survey import Survey
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / "P2S1"; site.mkdir()
        for epoch in (1702458924, 1702464328):
            (site / f"{epoch}.B423").write_bytes(bytes([120]) * 64)
        stray = site / "DATA0034"; stray.mkdir()
        for epoch in (1689762000, 1689767400, 1689772800):
            (stray / f"{epoch}.B423").write_bytes(bytes([120]) * 64)
        names = [f.name for f in select_files(site)]
        assert names == ["1702458924.B423", "1702464328.B423"], names
        card = root / "P9S9"; card.mkdir()
        (card / "DATA0001").mkdir()
        (card / "DATA0001" / "1702458924.B423").write_bytes(bytes([120]) * 64)
        assert [f.name for f in b423_files(card)] == ["1702458924.B423"], b423_files(card)
        survey = Survey({"name": "t", "data_root": str(root)}, root)
        assert list(survey.site_dirs()) == ["P2S1", "P9S9"], list(survey.site_dirs())
        print("  stray subfolder records left out beside a recording; a card-only subfolder still read")


def test_lemi423_coil_chain() -> None:
    """Check the coil chain of a LEMI-423 site with a `calibration_fn` and `h_scale`.

    Fails if a LEMI-423 site with a `calibration_fn` (the LEMI-120 .rsp) and
    `h_scale: -1000`, ingested from one synthetic B423 file, is not archived
    with hx's and hy's chain exactly, physical to recorded: the coil table
    (FrequencyResponseTableFilter nanoTesla -> nanoTesla, amplitudes and
    phases equal to the .rsp read here with numpy), the reader's linear stage
    (CoefficientFilter `lemi423_linear_<comp>`, nanoTesla -> digital counts,
    gain 1/K from the header), then `lemi423_b_scale` (gain -1000, digital
    counts -> digital counts); or if each stage's units_in is not the
    previous stage's units_out; or if ex carries a coil or b_scale stage.
    This is the mt-io fork's chain with mt-workbench's one stage appended; stock
    mt-io raises before writing anything, since its coil table's "millivolts"
    is not one of mt_metadata's units. It also fails if the run comment does
    not record "calibration_sha256: <sha256 of the .rsp file, computed here>".
    """
    import shutil
    import numpy as np
    from mth5.mth5 import MTH5
    import new_survey_unit as nsu
    rsp = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
    root = SCRATCH / "lemi423_coil"
    shutil.rmtree(root, ignore_errors=True)
    epoch = 1624510579
    nsu.write_b423(root / "raw" / "S01" / f"{epoch}.B423", 36, "2.1", -31.5, 138.5, 123.4, epoch)
    survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"calibration_fn": str(rsp), "h_scale": -1000.0, "channels": ["ex", "ey", "hx", "hy"],
                                  "dipole_length_ex": 50.0, "dipole_length_ey": 50.0},
                     "sites": {"S01": {}}}, root)
    path = ingest_site(survey, "S01", overwrite=True)
    table = np.loadtxt(rsp, skiprows=2)
    k = {"hx": 2.909985e-06, "hy": 2.909481e-06}  # write_b423's %Kmx, %Kmy
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station("S01", survey="t").get_run("sr1000_0001")
        chains = {}
        for comp in ("hx", "hy", "ex"):
            chains[comp] = run.get_channel(comp).channel_response.filters_list
        for comp in ("hx", "hy"):
            stages = chains[comp]
            got = [(type(f).__name__, f.name, str(f.units_in), str(f.units_out)) for f in stages]
            assert len(stages) == 3, got
            coil, linear, scale = stages
            assert (type(coil).__name__, str(coil.units_in), str(coil.units_out)) == \
                ("FrequencyResponseTableFilter", "nanoTesla", "nanoTesla"), got
            assert coil.name.startswith("lemi_120_") and coil.name.endswith("_response"), got
            assert np.allclose(coil.amplitudes, table[:, 1]) and np.allclose(np.rad2deg(coil.phases), table[:, 2]), comp
            assert (type(linear).__name__, linear.name, str(linear.units_in), str(linear.units_out)) == \
                ("CoefficientFilter", f"lemi423_linear_{comp}", "nanoTesla", "digital counts"), got
            assert abs(float(linear.gain) * k[comp] - 1.0) < 1e-9, (comp, linear.gain)
            assert (type(scale).__name__, scale.name, float(scale.gain), str(scale.units_in), str(scale.units_out)) == \
                ("CoefficientFilter", "lemi423_b_scale", -1000.0, "digital counts", "digital counts"), got
            for a, b in zip(stages, stages[1:]):
                assert str(b.units_in) == str(a.units_out), (comp, a.name, a.units_out, b.name, b.units_in)
        ex_names = [f.name for f in chains["ex"]]
        assert not any(n.startswith("lemi_120_") or n == "lemi423_b_scale" for n in ex_names), ex_names
        recorded = str(run.metadata.comments.value or "").split("; ")
        assert f"calibration_sha256: {_sha256(rsp)}" in recorded, recorded
    finally:
        m.close_mth5()
    print(f"  LEMI-423 with {rsp.name}, h_scale -1000: hx, hy = {[f.name for f in chains['hx']]} "
          f"(nT -> nT -> counts -> counts, table == numpy); ex {ex_names}")


def test_lemi423_declination_stored() -> None:
    """Check that a LEMI-423 site's declared declination reaches the archive's station metadata.

    Fails if a LEMI-423 site with `declination: -1.07`, `declination_model:
    IGRF-14` and `declination_epoch: 2023.55`, ingested from one synthetic
    B423 file, is not archived with ``location.declination`` value -1.07,
    model IGRF-14 and epoch "2023.55"; if the station's reference frame is
    not the reader's geomagnetic; if any channel gains a
    ``translated_azimuth`` or hy's measurement azimuth is not 90 (nothing
    is rotated); or if the control, the same site with no declination keys,
    is not archived with value 0.0 and no epoch (unset, which the EDI writer
    leaves out).
    """
    import shutil
    from mth5.mth5 import MTH5
    import new_survey_unit as nsu
    rsp = REPO / "surveys" / "burra" / "sensors" / "l120n.rsp"
    root = SCRATCH / "lemi423_declination"
    shutil.rmtree(root, ignore_errors=True)
    epoch = 1624510579
    nsu.write_b423(root / "raw" / "S01" / f"{epoch}.B423", 36, "2.1", -31.5, 138.5, 123.4, epoch)
    got = {}
    declared = {"declination": -1.07, "declination_model": "IGRF-14", "declination_epoch": 2023.55}
    for label, keys in (("declared", declared), ("control", {}), ("geographic", {**declared,
                                                                               "layout_north": "geographic"})):
        survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
                         "workspace": str(root / "work"),
                         "defaults": {"calibration_fn": str(rsp), "h_scale": -1000.0,
                                      "channels": ["ex", "ey", "hx", "hy"]},
                         "sites": {"S01": dict(keys)}}, root)
        path = ingest_site(survey, "S01", out_path=root / "work" / f"{label}.h5", overwrite=True)
        m = MTH5()
        m.open_mth5(path, mode="r")
        try:
            station = m.get_station("S01", survey="t")
            d = station.metadata.location.declination
            frame = str(getattr(station.metadata.orientation.reference_frame, "value",
                                station.metadata.orientation.reference_frame))
            run = station.get_run("sr1000_0001")
            azimuths = {c: (run.get_channel(c).metadata.measurement_azimuth,
                            run.get_channel(c).metadata.translated_azimuth) for c in ("ex", "ey", "hx", "hy")}
        finally:
            m.close_mth5()
        got[label] = (d.value, d.model, d.epoch, frame)
        assert frame == ("geographic" if label == "geographic" else "geomagnetic"), (label, frame)
        assert all(t is None for _a, t in azimuths.values()), (label, azimuths)
        assert azimuths["hy"][0] == 90.0 and azimuths["ey"][0] == 90.0, (label, azimuths)
    assert got["declared"][:3] == (-1.07, "IGRF-14", "2023.55"), got["declared"]
    assert got["control"][0] == 0.0 and got["control"][2] is None, got["control"]
    assert got["geographic"] == (-1.07, "IGRF-14", "2023.55", "geographic"), got["geographic"]
    print(f"  LEMI-423 declination: declared -> {got['declared']}; control (no keys) -> {got['control']}; "
          f"layout_north geographic -> {got['geographic']}; no translated_azimuth, hy 90")


def test_dc_level_recorded_at_ingest() -> None:
    """Check the raw DC level `ingest_site` records in the run comments.

    Fails if an ey at 1.6e9 counts in the first of two runs is not recorded
    "open input?" there, a healthy channel is flagged, a recorded median
    differs from the median of the archived samples read here with h5py
    beyond the record's rounding, or `recorded_levels`, `flag_line` and
    `channel_summary` do not give back the record.
    """
    import shutil
    import h5py
    import numpy as np
    from mt_workbench.dclevel import OK, OPEN, channel_summary, flag_line, parse_level_note, recorded_levels
    from mtio_fork_unit import _write_b423

    root = SCRATCH / "dc_level"
    shutil.rmtree(root, ignore_errors=True)
    healthy = {"Ex": (2.0e7, 2.0e6), "Bx": (4.3e7, 2.0e6), "By": (3.9e7, 2.0e6)}
    epoch = 1624510579
    _write_b423(root / "raw" / "S01" / f"{epoch}.B423", epoch=epoch, n=4000,
                levels={**healthy, "Ey": (1.6e9, 1.0e3)}, seed=1)
    _write_b423(root / "raw" / "S01" / f"{epoch + 4}.B423", epoch=epoch + 4, n=4000,
                levels={**healthy, "Ey": (-3.0e7, 2.0e6)}, seed=2)
    survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"channels": ["ex", "ey", "hx", "hy"], "dipole_length_ex": 50.0,
                                  "dipole_length_ey": 50.0},
                     "sites": {"S01": {}}}, root)
    path = ingest_site(survey, "S01", overwrite=True, max_run_files=1)
    want = {"sr1000_0001": {"ex": OK, "ey": OPEN, "hx": OK, "hy": OK},
            "sr1000_0002": {"ex": OK, "ey": OK, "hx": OK, "hy": OK}}
    independent = {}
    with h5py.File(path, "r") as f:
        station = f["Experiment/Surveys/t/Stations/S01"]
        runs = sorted(r for r in station if r.startswith("sr"))
        assert runs == sorted(want), runs
        for run in runs:
            comment = station[run].attrs.get("comments")
            comment = comment.decode() if isinstance(comment, bytes) else str(comment)
            rows = {r["channel"]: r for r in parse_level_note(comment)}
            got = {c: r["verdict"] for c, r in rows.items()}
            assert got == want[run], (run, comment)
            for comp, row in rows.items():
                truth = float(np.median(station[run][comp][()].astype("float64")))
                independent[(run, comp)] = truth
                assert abs(row["median_counts"] - truth) <= 5e-4 * abs(truth), (run, comp, row, truth)
    levels = recorded_levels(path, "t", "S01")
    assert {run: {r["channel"]: r["verdict"] for r in rows} for run, rows in levels.items()} == want, levels
    ey = next(r for r in levels["sr1000_0001"] if r["channel"] == "ey")
    assert abs(ey["median_counts"] - 1.6e9) < 1e6, ey
    flagged = [flag_line(r) for rows in levels.values() for r in rows if r["verdict"] != OK]
    assert flagged == ["S01 sr1000_0001 ey: median 1.60e9 counts, open input?"], flagged
    summary = {c["channel"]: c for c in channel_summary(levels)}
    assert (summary["ey"]["verdict"], summary["ey"]["n_verdict"], summary["ey"]["n_runs"]) == (OPEN, 1, 2), summary
    assert abs(summary["ey"]["median_counts"] - 1.6e9) < 1e6, summary["ey"]
    assert all(summary[c]["verdict"] == OK for c in ("ex", "hx", "hy")), summary
    print(f"  dc level recorded: sr1000_0001 ey open input? at {ey['median_counts']:.4g} counts (h5py median "
          f"{independent[('sr1000_0001', 'ey')]:.10g}), every other channel run ok; flagged {flagged}; "
          f"summary ey open input? in {summary['ey']['n_verdict']} of {summary['ey']['n_runs']} runs")


def test_glued_altitude_header_line() -> None:
    """Check that mt-io parses a glued four-digit altitude line.

    Fails if a B423 header whose altitude line reads `%Alt1060.0,m 12 1`
    (firmware 2.1 with a four-digit altitude) raises in mt-io's
    own coordinate parser (the mt-io fork parses it), or if the ordinary
    `%Alt 125.2,m 12 1` form parses to anything but 125.2 m.
    """
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



def test_readable_b423() -> None:
    from mtio_fork_unit import _write_b423

    from mt_workbench.ingest import readable_b423

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        good = [_write_b423(folder / f"{1678728841 + 5400 * k}.B423", epoch=1678728841 + 5400 * k, n=4000) for k in (0, 2)]
        blank = folder / "1678734241.B423"
        blank.write_bytes(bytes(1024) + bytes(200_000))          # a full-length file, header block all zero
        tiny = folder / "1678745041.B423"
        tiny.write_bytes(bytes(100))
        keep, skipped = readable_b423(sorted(folder.glob("*.B423")))
        assert keep == sorted(good), keep
        assert len(skipped) == 2 and "1678734241.B423" in skipped[0] and "header unreadable" in skipped[0], skipped
        assert "1678745041.B423" in skipped[1] and "no data" in skipped[1], skipped
        print(f"  a blank-header file and a 100-byte file are left out with reasons: {skipped}")
        # a logger with no card space: every file a few kilobytes
        empty = Path(tmp) / "empty"; empty.mkdir()
        files = [_write_b423(empty / f"{1690274004 + 5400 * k}.B423", epoch=1690274004 + 5400 * k, n=6000) for k in range(12)]
        try:
            readable_b423(files)
        except ValueError as exc:
            assert "nearly empty" in str(exc) and "card space" in str(exc), exc
        else:
            raise AssertionError("a folder of nearly empty files was not refused")
        print("  twelve files holding six seconds each, 5400 s apart, are refused as nearly empty")
        # the same files at a native 1 Hz rate hold 6000 s each: a full recording
        keep, skipped = readable_b423(files, sample_rate=1.0)
        assert keep == files and skipped == [], (len(keep), skipped)
        try:
            readable_b423(files, sample_rate=1000.0)
        except ValueError as exc:
            assert "at 1000 Hz" in str(exc), exc
        else:
            raise AssertionError("the control at 1000 Hz was not refused")
        print("  the same twelve files at 1 Hz (6000 s each) are accepted in full; at 1000 Hz still refused")

if __name__ == "__main__":
    SCRATCH.mkdir(parents=True, exist_ok=True)
    from loguru import logger
    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="WARNING")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  ingest_unit ({len(tests)} tests)")
