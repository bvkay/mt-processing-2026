"""Unit test for `scripts/process_rr.py`'s command line, through --dry-run.

    python tests/process_rr_cli_unit.py

The script is run as a subprocess (the way the GUI runs it) with `--dry-run`,
which resolves everything and exits without opening an archive or writing a
product. Its `key: value` lines are parsed back here.

**This test fails if** a plain `process_rr.py <survey.yaml> D02 E08 --dry-run`
does not exit 0 with `local_archive` ending in `D02.h5`, `remote_archive` in
`E08.h5`, `stem` matching `D02_rr-E08_<YYYYMMDD-HHMM>` (no window in it),
`tag` empty, `window` "full overlap", `ignore_filters` False and the survey's
own band block (min_period 0.005, max_period 5000, periods_per_decade 10,
notch_frequencies "50, 150"); `--min-period 0.01 --max-period 1000
--per-decade 6 --notch "50,100,150"` do not each replace exactly their own
value and leave the others alone (`started`/`stem` excepted -- each
subprocess starts at its own instant); `--no-filters` does not leave both
archive paths (still `<site>.h5`, no more `_unfiltered.h5`) with
`ignore_filters` True and both "local archive"/"remote archive" status lines
reading "no filters used (--no-filters)"; `--tag try2` does not put `_try2`
at the end of the stem and "try2" in `tag`; a start and an end do not appear
in `window` while leaving the stem exactly `D02_rr-E08_<stamp>_try2` (the
window nowhere in it); `--notch ""` does not clear the list; on a SCRATCH
COPY of curnamona_cube's config (workspace pointed at the real one, so D02's
and E08's real archives are read but never written to, and a throwaway
filters.yaml only the copy ever sees -- the real curnamona files are never
touched), D02's declared filters gaining a notch its archive has no variant
for does not make the "local archive" status line read "raw: ...D02.h5,
variant: to build (<hash>)", or E08's unchanged status does not stay "none
declared"; or any of these runs writes a file anywhere (including a variant).

The advanced estimator flags. **This test also fails if** a plain dry run
does not say "tweaks: none" and print no `tweak.` line; `--taper hamming
--overlap 50 --no-prewhiten --r0 2.0` does not print exactly `tweak.taper:
hamming`, `tweak.overlap_pct: 50.0`, `tweak.prewhiten: False` and `tweak.r0:
2.0` -- no other tweak, no "tweaks: none" -- with every other line as in the
plain run (`started`/`stem` excepted); or, building aurora's real config for
D02 against E08 with the survey's lemimt band scheme (in-process, through
`mtproc.process.kernel_dataset` with nothing patched, while this process
holds both archives open read-only with h5py, as the GUI holds one: HDF5
refuses a read-write open of a file already open read-only, so the build
fails unless mth5 itself opens them read-only), without tweaks any decimation level is not
window.type hann (the in-use default; aurora's own is
boxcar), overlap round(num_samples * 0.25) -- or int(num_samples * 0.75) on a
level whose window lasts over 600 s, of which there must be at least one, so
the boost is really exercised -- prewhitening_type "first difference" with
recoloring True, min_num_stft_windows 0, and regression max_iterations 10,
max_redescending_iterations 2, r0 1.5, u0 2.8, tolerance 0.005 (and
`mtproc.process.ESTIMATOR_DEFAULTS`, which the GUI compares against, does not
say the same); with the tweaks `resolve()` makes of those four flags, any
level is not window.type hamming with overlap round(num_samples * 0.5) --
the long-window boost replaced -- prewhitening_type "" (which mth5's
`apply_prewhitening` must hand back untouched) with recoloring False and r0
2.0, or any other value moved from the defaults above; a dpss taper does not
build a finite taper of num_samples points on every level; or the config
builds change the modification time of D02.h5 or E08.h5, or a second
read-only h5py handle cannot open either while the first is held.

The product stem, the sidecar and the quadrant window. **This test also
fails if** `run_stem` does not give exactly `<local>_rr-<remote>_
<YYYYMMDD-HHMM>` (the local instant passed in, to the minute) with `_<tag>`
appended and stripped of surrounding underscores when a suffix is given, put
any window token in the name, or give two stems a minute apart the same
value; `build_sidecar`, fed a fake TF's own `phase_quadrants` result, does
not carry `local`/`remote`, `started`/`finished` as the exact ISO strings
passed in, `seconds` matching their difference, the band scheme and the full
effective tweaks (taper "hann" included even though no `--taper` was given),
the argv, the tag, the edi/figure names and a `versions` dict naming mtproc,
aurora, mth5, mt_metadata and mt_io -- or is not JSON-serialisable as it
stands; a phase-quadrant verdict built from a mode 180 deg out of quadrant is
not "flipped: ..." and one built from too few usable periods is not "not
judged: ..."; or `quadrant_window` does not pick 0.1-10 s at 100 Hz and above
and 30-3000 s below that (the false "180 deg out ... declare flip" the
0.1-10 s window raised on Stuart Shelf's 10 Hz ST19/ST20).

Both sites' time masks. **This test also fails if**, on a scratch copy of
curnamona_cube whose own masks.yaml holds three D02 masks (one written twice),
two E08 masks and one mask identical to one of D02's, one for the stack
STK_E08u and one for the archive-only SYN01, `resolve` for D02 rr E08 does not give `masks_local` D02's
three in start order, `masks_remote` E08's three, and `masks` the union in
start order -- exactly the starts listed in MASK_UNION_STARTS, the shared
interval once (D02's entry), E08's own entries carrying E08's reasons; the
sidecar `build_sidecar` makes does not carry the same three lists with
`masks_ignored` False; the dry run does not print "masks: D02 3, E08 3 (5
applied)"; with `--no-masks` all three lists are not empty with
`masks_ignored` True in `resolve` and the sidecar and "masks: ignored
(--no-masks)" printed; D02 against the stack STK_E08u picks up its
masks.yaml entry (a stacked remote has none of its own); D02 against SYN01
(archive-only, no STK_ prefix: judged by name, like a site) does not carry
SYN01's entry; or, with data_root pointed at a folder that does not exist
(the data drive unplugged, so resolve sees no raw sites and classes E08 as
virtual), `masks_remote` in `resolve` and the sidecar is not E08's three
and `masks` not the same union.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "process_rr.py"
SURVEY_DIR = REPO / "surveys" / "curnamona_cube"
SURVEY = SURVEY_DIR / "survey.yaml"
LOCAL, REMOTE = "D02", "E08"
MTH5_DIR = SURVEY_DIR / "work" / "mth5"
# the keys that legitimately differ between two subprocess calls: each one
# starts at its own instant, so a run's own start/product stem move even
# with identical flags
TIME_KEYS = {"started", "stem"}
STEM_RE = re.compile(r"^D02_rr-E08_\d{8}-\d{4}$")


def make_survey_copy(scratch: Path, extra_filters: dict) -> Path:
    """A scratch copy of curnamona_cube's survey.yaml + filters.yaml, workspace
    pointed at the real one (the real D02.h5/E08.h5 are read, never copied or
    written to), `extra_filters` merged into the copy's filters.yaml alone --
    the real file is never opened for writing."""
    for name in ("survey.yaml", "filters.yaml"):
        (scratch / name).write_bytes((SURVEY_DIR / name).read_bytes())
    copy_yaml = scratch / "survey.yaml"
    config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
    config["workspace"] = str(MTH5_DIR.parent)
    copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    filters_path = scratch / "filters.yaml"
    data = yaml.safe_load(filters_path.read_text(encoding="utf-8")) or {}
    data.update(extra_filters)
    filters_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return copy_yaml


def _load_process_rr():
    """The script as a module, for the functions --dry-run cannot exercise directly."""
    spec = importlib.util.spec_from_file_location("process_rr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dry_run(*options: str) -> dict[str, str]:
    """Run the script with --dry-run and parse its `key: value` lines."""
    argv = [sys.executable, str(SCRIPT), str(SURVEY), LOCAL, REMOTE, *options, "--dry-run"]
    done = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
    assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
    out = {}
    for line in done.stdout.splitlines():
        if ": " in line or line.endswith(":"):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def test_defaults_come_from_the_survey() -> None:
    got = dry_run()
    assert got["local_archive"].endswith(f"{LOCAL}.h5"), got["local_archive"]
    assert got["remote_archive"].endswith(f"{REMOTE}.h5"), got["remote_archive"]
    assert STEM_RE.match(got["stem"]), got["stem"]
    assert got["tag"] == "", got["tag"]
    assert got["window"] == "full overlap", got["window"]
    assert got["ignore_filters"] == "False", got["ignore_filters"]
    assert got["min_period"] == "0.005", got["min_period"]
    assert got["max_period"] == "5000.0", got["max_period"]
    assert got["periods_per_decade"] == "10.0", got["periods_per_decade"]
    assert got["notch_frequencies"] == "50, 150", got["notch_frequencies"]
    # fails if hz is asked for on a broadband site (it made a nonsense tipper)
    assert got["output_channels"] == "ex, ey", got["output_channels"]
    print(f"  defaults: stem {got['stem']}, archives {Path(got['local_archive']).name} / "
          f"{Path(got['remote_archive']).name}, bands {got['min_period']}-{got['max_period']} s "
          f"at {got['periods_per_decade']}/decade, notches {got['notch_frequencies']!r}")


def test_each_band_option_overrides_only_itself() -> None:
    base = dry_run()
    for option, value, key, expected in (
        ("--min-period", "0.01", "min_period", "0.01"),
        ("--max-period", "1000", "max_period", "1000.0"),
        ("--per-decade", "6", "periods_per_decade", "6.0"),
        ("--notch", "50,100,150", "notch_frequencies", "50, 100, 150"),
    ):
        got = dry_run(option, value)
        assert got[key] == expected, f"{option} {value}: {key} {got[key]!r}"
        others = {k: v for k, v in got.items() if k != key and k not in TIME_KEYS}
        unchanged = {k: v for k, v in base.items() if k != key and k not in TIME_KEYS}
        assert others == unchanged, f"{option} changed more than {key}: {others} vs {unchanged}"
        print(f"  {option} {value} -> {key} {got[key]}, nothing else moved")
    cleared = dry_run("--notch", "")
    assert cleared["notch_frequencies"] == "", cleared["notch_frequencies"]
    print("  --notch \"\" -> no notch frequencies at all")


def test_no_filters_uses_the_raw_archive() -> None:
    got = dry_run("--no-filters")
    assert got["local_archive"].endswith(f"{LOCAL}.h5") and "_unfiltered" not in got["local_archive"],         got["local_archive"]
    assert got["remote_archive"].endswith(f"{REMOTE}.h5") and "_unfiltered" not in got["remote_archive"],         got["remote_archive"]
    assert got["ignore_filters"] == "True", got["ignore_filters"]
    assert "no filters used (--no-filters)" in got["local archive"], got["local archive"]
    assert "no filters used (--no-filters)" in got["remote archive"], got["remote archive"]
    print(f"  --no-filters: {Path(got['local_archive']).name} / {Path(got['remote_archive']).name} "
          f"(raw, no _unfiltered suffix any more); {got['local archive']}")


def test_dry_run_reports_archive_status() -> None:
    """The "local archive"/"remote archive" status lines, on a scratch copy of
    curnamona_cube whose filters.yaml gains a notch for D02 -- whose real
    archive has no variant for it."""
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {LOCAL: [{"notch": {"f0": 50.0}}]})
        argv = [sys.executable, str(SCRIPT), str(copy_yaml), LOCAL, REMOTE, "--dry-run"]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
        assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
        lines = {}
        for line in done.stdout.splitlines():
            if line.startswith("local archive:") or line.startswith("remote archive:"):
                key, _, value = line.partition(":")
                lines[key.strip()] = value.strip()
        assert lines["local archive"].startswith(f"raw: {MTH5_DIR / f'{LOCAL}.h5'}"), lines["local archive"]
        assert re.search(r"variant: to build \([0-9a-f]{8}\)$", lines["local archive"]), lines["local archive"]
        assert lines["remote archive"] == f"raw: {MTH5_DIR / f'{REMOTE}.h5'}, variant: none declared",             lines["remote archive"]
        after = sorted(p.name for p in MTH5_DIR.glob("*.h5"))
        assert not any(n.startswith(f"{LOCAL}_f") for n in after), f"--dry-run built a variant: {after}"
    print(f"  archive status: D02 (a notch just declared) -> {lines['local archive']}; "
          f"E08 (nothing declared) -> {lines['remote archive']}")


def test_tag_suffix_and_no_window_in_the_stem() -> None:
    got = dry_run("--tag", "try2")
    assert got["tag"] == "try2", got["tag"]
    assert got["stem"] == f"{got['stem'].rsplit('_try2', 1)[0]}_try2" and got["stem"].endswith("_try2"), got["stem"]
    assert re.match(r"^D02_rr-E08_\d{8}-\d{4}_try2$", got["stem"]), got["stem"]
    start, end = "2021-06-29 12:55", "2021-06-29 14:55"
    got = dry_run(start, end, "--tag", "try2")
    assert got["window"] == f"{start} to {end} UTC", got["window"]
    assert got["start"] == start and got["end"] == end, (got["start"], got["end"])
    # the point of dropping the window from the name: it must not appear in the stem at all
    assert re.match(r"^D02_rr-E08_\d{8}-\d{4}_try2$", got["stem"]), got["stem"]
    assert "_w" not in got["stem"].replace("_rr-", ""), f"a window token leaked into the stem: {got['stem']}"
    print(f"  --tag try2 with a window: stem {got['stem']}, tag {got['tag']!r}, window {got['window']!r}")


def test_tweaks_print_only_what_was_given() -> None:
    base = dry_run()
    assert base.get("tweaks") == "none", base.get("tweaks")
    assert not [k for k in base if k.startswith("tweak.")], base
    got = dry_run("--taper", "hamming", "--overlap", "50", "--no-prewhiten", "--r0", "2.0")
    tweaks = {k: v for k, v in got.items() if k.startswith("tweak.")}
    assert tweaks == {"tweak.taper": "hamming", "tweak.overlap_pct": "50.0",
                      "tweak.prewhiten": "False", "tweak.r0": "2.0"}, tweaks
    assert "tweaks" not in got, got["tweaks"]
    rest = {k: v for k, v in got.items() if not k.startswith("tweak.") and k not in TIME_KEYS}
    base_rest = {k: v for k, v in base.items() if k != "tweaks" and k not in TIME_KEYS}
    assert rest == base_rest, "a tweak moved another line"
    print(f"  tweaks: plain run 'tweaks: none'; four flags -> {tweaks}, nothing else moved")


# the in-use estimator values, stated here from aurora 0.6.2's ConfigCreator
# output (not taken from mtproc.process), and what the four flags must make
IN_USE = {"type": "hann", "prewhitening_type": "first difference", "recoloring": True,
          "min_num_stft_windows": 0, "max_iterations": 10, "max_redescending_iterations": 2,
          "r0": 1.5, "u0": 2.8, "tolerance": 0.005}
TWEAKED = {**IN_USE, "type": "hamming", "prewhitening_type": "", "recoloring": False, "r0": 2.0}


def level_values(dec) -> dict:
    """One decimation level's estimator settings, enums read as their plain strings."""
    stft, reg = dec.stft, dec.regression
    return {"type": str(getattr(stft.window.type, "value", stft.window.type)),
            "prewhitening_type": str(getattr(stft.prewhitening_type, "value", stft.prewhitening_type)),
            "recoloring": stft.recoloring, "min_num_stft_windows": stft.min_num_stft_windows,
            "max_iterations": reg.max_iterations,
            "max_redescending_iterations": reg.max_redescending_iterations,
            "r0": reg.r0, "u0": reg.u0, "tolerance": reg.tolerance}


def test_tweaks_reach_every_decimation_level() -> None:
    import h5py
    import numpy as np
    import xarray as xr
    from mth5.processing.spectre.prewhitening import apply_prewhitening

    sys.path.insert(0, str(REPO / "src"))
    from mtproc.bands import lemimt_band_scheme
    from mtproc.process import ESTIMATOR_DEFAULTS, apply_tweaks, build_config, kernel_dataset

    process_rr = _load_process_rr()
    started = dt.datetime.now().astimezone()
    argv = [str(SURVEY), LOCAL, REMOTE, "--taper", "hamming", "--overlap", "50", "--no-prewhiten",
            "--r0", "2.0"]
    res = process_rr.resolve(process_rr.build_parser().parse_args(argv), started)
    assert res["tweaks"] == {"taper": "hamming", "overlap_pct": 50.0, "prewhiten": False, "r0": 2.0},         res["tweaks"]
    scheme = lemimt_band_scheme(res["survey"].sample_rate, **res["scheme_kwargs"])

    # read-only, as mth5 opens the archives itself (mtproc patches nothing): both are held
    # open read-only for the whole build, and HDF5 refuses a read-write open of a file this
    # process already holds read-only ("file is already open for read-only")
    archives = [MTH5_DIR / f"{LOCAL}.h5", MTH5_DIR / f"{REMOTE}.h5"]
    mtimes = [p.stat().st_mtime_ns for p in archives]
    held = [h5py.File(p, "r") for p in archives]
    try:
        configs = {}
        for name, tweaks in (("in use", None), ("tweaked", res["tweaks"])):
            try:
                kd = kernel_dataset(res["local_archive"], LOCAL, res["remote_archive"], REMOTE)
            except OSError as exc:
                raise AssertionError(f"the kernel dataset opened a held archive read-write: {exc}") from exc
            configs[name] = build_config(kd, scheme, tweaks, output_channels=res["output_channels"])
        second = [h5py.File(p, "r") for p in archives]  # read-only still opens beside the held handle
        for f in second:
            f.close()
    finally:
        for f in held:
            f.close()
    assert [p.stat().st_mtime_ns for p in archives] == mtimes, "a config build wrote to an archive"

    long_levels = 0
    for dec in configs["in use"].decimations:
        n, seconds = dec.stft.window.num_samples, dec.stft.window.num_samples / dec.decimation.sample_rate
        want = int(n * 0.75) if seconds > 600.0 else round(n * 0.25)
        long_levels += seconds > 600.0
        assert dec.stft.window.overlap == want, (dec.decimation.level, dec.stft.window.overlap, want)
        assert level_values(dec) == IN_USE, (dec.decimation.level, level_values(dec))
    assert long_levels >= 1, "no level has a window over 600 s: the boost is never exercised"
    assert ESTIMATOR_DEFAULTS == {"taper": "hann", "overlap_pct": 25.0, "prewhiten": True,
                                  "min_windows": 0, "max_iterations": 10,
                                  "redescending_iterations": 2, "r0": 1.5, "u0": 2.8,
                                  "tolerance": 0.005}, ESTIMATOR_DEFAULTS
    levels = configs["tweaked"].decimations
    ds = xr.Dataset({"ex": ("time", np.arange(8.0))}, coords={"time": np.arange(8)})
    for dec in levels:
        assert dec.stft.window.overlap == round(dec.stft.window.num_samples * 0.5),             (dec.decimation.level, dec.stft.window.overlap)
        assert level_values(dec) == TWEAKED, (dec.decimation.level, level_values(dec))
        assert apply_prewhitening(dec.stft.prewhitening_type, ds) is ds, "prewhitening still applied"
    apply_tweaks(configs["tweaked"], {"taper": "dpss"})
    for dec in levels:
        dec.stft.window._taper = None  # built lazily and cached: rebuild it as dpss
        taper = dec.stft.window.taper()
        assert len(taper) == dec.stft.window.num_samples and np.isfinite(taper).all(), dec.decimation.level
    print(f"  config D02 rr E08, {len(levels)} levels ({long_levels} with windows over 600 s): "
          f"in use {IN_USE['type']}, overlap 25 %/75 %, r0 {IN_USE['r0']}; tweaked hamming, overlap "
          f"50 % on every level, prewhitening off, r0 2.0; dpss builds; built while both archives were "
          f"held read-only, a second read-only handle opened, mtimes unchanged")


def test_dry_run_writes_nothing() -> None:
    before = sorted(p.name for p in MTH5_DIR.glob("*.h5")) if MTH5_DIR.exists() else []
    dry_run("--no-filters", "--tag", "never")
    after = sorted(p.name for p in MTH5_DIR.glob("*.h5")) if MTH5_DIR.exists() else []
    assert before == after, f"--dry-run changed the archives: {before} -> {after}"
    print(f"  --dry-run wrote nothing: {MTH5_DIR.name}/ still holds {after}")


def test_run_stem_format_and_uniqueness() -> None:
    process_rr = _load_process_rr()
    t0 = dt.datetime(2026, 9, 23, 21, 15, 30, tzinfo=dt.timezone.utc)
    stem = process_rr.run_stem(LOCAL, REMOTE, t0)
    assert stem == f"{LOCAL}_rr-{REMOTE}_20260923-2115", stem
    tagged = process_rr.run_stem(LOCAL, REMOTE, t0, suffix="try2")
    assert tagged == f"{LOCAL}_rr-{REMOTE}_20260923-2115_try2", tagged
    stripped = process_rr.run_stem(LOCAL, REMOTE, t0, suffix="__nofilt__")
    assert stripped == f"{LOCAL}_rr-{REMOTE}_20260923-2115_nofilt", stripped
    assert "_w" not in stem.replace("_rr-", ""), f"a window token leaked into run_stem's output: {stem}"
    t1 = t0 + dt.timedelta(minutes=1)
    stem1 = process_rr.run_stem(LOCAL, REMOTE, t1)
    assert stem1 != stem, "two stems a minute apart did not differ"
    print(f"  run_stem: {stem}, tagged {tagged}, stripped {stripped}, a minute later {stem1} (differs)")


def test_quadrant_window_by_sample_rate() -> None:
    process_rr = _load_process_rr()
    assert process_rr.quadrant_window(1000.0) == (0.1, 10.0), process_rr.quadrant_window(1000.0)
    assert process_rr.quadrant_window(100.0) == (0.1, 10.0), process_rr.quadrant_window(100.0)
    assert process_rr.quadrant_window(99.9) == (30.0, 3000.0), process_rr.quadrant_window(99.9)
    assert process_rr.quadrant_window(10.0) == (30.0, 3000.0), process_rr.quadrant_window(10.0)
    print("  quadrant_window: 1000/100 Hz -> 0.1-10 s (broadband); 99.9/10 Hz -> 30-3000 s (long-period)")


def _fake_tf(xy_deg: float, yx_deg: float, periods):
    """A minimal in-memory mt_metadata TF: `periods` s, constant phases (deg), |Z| = 1."""
    import numpy as np
    from mt_metadata.transfer_functions.core import TF

    period = np.asarray(periods, dtype=float)
    z = np.zeros((period.size, 2, 2), dtype=complex)
    z[:, 0, 1] = np.exp(1j * np.radians(xy_deg))
    z[:, 1, 0] = np.exp(1j * np.radians(yx_deg))
    tf = TF()
    tf.station = "FAKE"
    tf.survey_metadata.id = "test"
    tf.period = period
    tf.impedance = z
    return tf


def _mask(start: str, end: str, reason: str, bands="all") -> dict:
    return {"start": start, "end": end, "bands": bands, "reason": reason, "found_by": "time"}


MASKS_BOTH = {
    LOCAL: [_mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z", "D02 spike"),
            _mask("2021-06-29T08:00:00Z", "2021-06-29T08:30:00Z", "D02 band", [0.01, 0.1]),
            _mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z", "D02 spike again"),
            _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z", "D02 night")],
    REMOTE: [_mask("2021-06-29T12:00:00Z", "2021-06-29T12:05:00Z", "E08 band", [1.0, 10.0]),
             _mask("2021-06-29T09:00:00Z", "2021-06-29T09:15:00Z", "E08 fence"),
             _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z", "E08 same as D02 night")],
    "SYN01": [_mask("2021-06-29T11:00:00Z", "2021-06-29T11:30:00Z", "SYN01 declared by hand")],
    "STK_E08u": [_mask("2021-06-29T11:00:00Z", "2021-06-29T11:30:00Z", "a stack has no masks")],
}
# stated here, not computed from the masks: the union's starts and reasons, earliest first
MASK_UNION_STARTS = ["2021-06-29T08:00:00Z", "2021-06-29T09:00:00Z", "2021-06-29T10:00:00Z",
                     "2021-06-29T12:00:00Z", "2021-06-30T01:00:00Z"]
MASK_UNION_REASONS = ["D02 band", "E08 fence", "D02 spike", "E08 band", "D02 night"]


def test_masks_from_both_sites() -> None:
    import numpy as np

    process_rr = _load_process_rr()
    started = dt.datetime(2026, 9, 24, 9, 0, 0, tzinfo=dt.timezone.utc)
    physical = process_rr.phase_quadrants(_fake_tf(45.0, -135.0, np.geomspace(0.1, 10.0, 8)))
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        (Path(tmp) / "masks.yaml").write_text(yaml.safe_dump(MASKS_BOTH, sort_keys=False), encoding="utf-8")

        def resolved(*extra):
            args = process_rr.build_parser().parse_args([str(copy_yaml), LOCAL, REMOTE, *extra])
            res = process_rr.resolve(args, started)
            edi = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
            sidecar = process_rr.build_sidecar(res, args, started, started, edi,
                                               edi.with_suffix(".png"), physical, [])
            return res, sidecar

        res, sidecar = resolved()
        assert [m["start"] for m in res["masks_local"]] == [
            "2021-06-29T08:00:00Z", "2021-06-29T10:00:00Z", "2021-06-30T01:00:00Z"], res["masks_local"]
        assert [m["reason"] for m in res["masks_remote"]] == [
            "E08 fence", "E08 band", "E08 same as D02 night"], res["masks_remote"]
        assert [m["start"] for m in res["masks"]] == MASK_UNION_STARTS, [m["start"] for m in res["masks"]]
        assert [m["reason"] for m in res["masks"]] == MASK_UNION_REASONS, [m["reason"] for m in res["masks"]]
        assert res["masks_ignored"] is False, res["masks_ignored"]
        for key in ("masks_local", "masks_remote", "masks"):
            assert sidecar[key] == res[key], (key, sidecar[key])
        assert sidecar["masks_ignored"] is False, sidecar["masks_ignored"]
        json.loads(json.dumps(sidecar, default=str))

        argv = [sys.executable, str(SCRIPT), str(copy_yaml), LOCAL, REMOTE, "--dry-run"]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
        assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
        line = next((ln for ln in done.stdout.splitlines() if ln.startswith("masks:")), None)
        assert line == "masks: D02 3, E08 3 (5 applied)", line
        print(f"  masks D02 rr E08: {len(res['masks_local'])} local + {len(res['masks_remote'])} remote "
              f"-> {len(res['masks'])} applied, starts {[s[11:16] for s in MASK_UNION_STARTS]}; dry run {line!r}")

        res, sidecar = resolved("--no-masks")
        for key in ("masks_local", "masks_remote", "masks"):
            assert res[key] == [] and sidecar[key] == [], (key, res[key], sidecar[key])
        assert res["masks_ignored"] is True and sidecar["masks_ignored"] is True, sidecar["masks_ignored"]
        done = subprocess.run(argv + ["--no-masks"], capture_output=True, text=True, cwd=REPO)
        line = next((ln for ln in done.stdout.splitlines() if ln.startswith("masks:")), None)
        assert line == "masks: ignored (--no-masks)", line
        print(f"  --no-masks: masks_local/masks_remote/masks all [], masks_ignored True; dry run {line!r}")

        args = process_rr.build_parser().parse_args([str(copy_yaml), LOCAL, "STK_E08u"])
        res = process_rr.resolve(args, started)
        assert res["masks_remote"] == [] and len(res["masks"]) == 3, (res["masks_remote"], res["masks"])
        print(f"  D02 rr STK_E08u (stack): its masks.yaml entry ignored, {len(res['masks'])} applied")

        # an archive-only remote without the stack prefix is judged by name, like a site
        args = process_rr.build_parser().parse_args([str(copy_yaml), LOCAL, "SYN01"])
        res = process_rr.resolve(args, started)
        assert res["virtual_remote"] is True, "SYN01 is expected to be an archive-only (virtual) remote"
        assert [m["reason"] for m in res["masks_remote"]] == ["SYN01 declared by hand"], res["masks_remote"]
        print(f"  D02 rr SYN01 (archive-only, no STK_ prefix): its entry applies, {len(res['masks'])} applied")

    # data_root on a drive that is not plugged in: every remote with an archive
    # looks virtual to resolve, and E08's masks must still apply
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
        config["data_root"] = str(Path(tmp) / "drive_not_mounted")
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        (Path(tmp) / "masks.yaml").write_text(yaml.safe_dump(MASKS_BOTH, sort_keys=False), encoding="utf-8")
        res, sidecar = resolved()
        assert res["raw_sites"] == {} and res["virtual_remote"] is True, (res["raw_sites"], res["virtual_remote"])
        assert [m["reason"] for m in res["masks_remote"]] == [
            "E08 fence", "E08 band", "E08 same as D02 night"], res["masks_remote"]
        assert [m["start"] for m in res["masks"]] == MASK_UNION_STARTS, [m["start"] for m in res["masks"]]
        assert sidecar["masks_remote"] == res["masks_remote"], sidecar["masks_remote"]
        print(f"  data_root unmounted (E08 looks virtual): masks_remote {len(res['masks_remote'])}, "
              f"{len(res['masks'])} applied")


def test_build_sidecar_with_a_fake_tf() -> None:
    import numpy as np

    process_rr = _load_process_rr()
    started = dt.datetime(2026, 9, 23, 21, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=9, minutes=30)))
    finished = started + dt.timedelta(seconds=137)
    args = process_rr.build_parser().parse_args(
        [str(SURVEY), LOCAL, REMOTE, "2021-06-29 12:55", "2021-06-29 14:55", "--tag", "sidecar-test"])
    res = process_rr.resolve(args, started)
    edi_path = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
    png_path = res["survey"].workspace / "tf" / f"{res['stem']}_vs_lemimt.png"

    # physical: xy in (0, 90), yx in (-180, -90)
    physical = process_rr.phase_quadrants(_fake_tf(45.0, -135.0, np.geomspace(0.1, 10.0, 8)))
    sidecar = process_rr.build_sidecar(res, args, started, finished, edi_path, png_path, physical, [])
    assert sidecar["local"] == LOCAL and sidecar["remote"] == REMOTE, sidecar
    assert sidecar["started"] == started.isoformat(), sidecar["started"]
    assert sidecar["finished"] == finished.isoformat(), sidecar["finished"]
    assert sidecar["seconds"] == 137.0, sidecar["seconds"]
    assert sidecar["window"] == {"start": "2021-06-29T12:55:00+00:00", "end": "2021-06-29T14:55:00+00:00"},         sidecar["window"]
    assert sidecar["band_scheme"]["min_period"] == 0.005, sidecar["band_scheme"]
    assert sidecar["tweaks"] == process_rr.ESTIMATOR_DEFAULTS, "no --taper given: must fall back to the default"
    assert sidecar["tweaks"]["taper"] == "hann", sidecar["tweaks"]
    assert sidecar["argv"] == list(sys.argv), sidecar["argv"]
    assert sidecar["tag"] == "sidecar-test", sidecar["tag"]
    assert sidecar["edi"] == edi_path.name and sidecar["figure"] == png_path.name, sidecar
    assert sidecar["quadrant"]["verdict"] == "physical quadrants", sidecar["quadrant"]
    for lib in ("mtproc", "aurora", "mth5", "mt_metadata", "mt_io"):
        assert sidecar["versions"].get(lib), sidecar["versions"]
    json.loads(json.dumps(sidecar, default=str))  # must round-trip as JSON
    print(f"  build_sidecar (physical): seconds {sidecar['seconds']}, tweaks.taper "
          f"{sidecar['tweaks']['taper']!r}, versions {sidecar['versions']}")

    # xy 180 deg out of quadrant, 8 usable periods (>= min_periods): "flipped"
    flipped_q = process_rr.phase_quadrants(_fake_tf(-135.0, -135.0, np.geomspace(0.1, 10.0, 8)))
    flipped_sidecar = process_rr.build_sidecar(res, args, started, finished, edi_path, png_path,
                                               flipped_q, ["xy"])
    assert flipped_sidecar["quadrant"]["verdict"] == "flipped: xy 180 deg out of quadrant",         flipped_sidecar["quadrant"]

    # only 2 usable periods in the window (< min_periods 5): "not judged"
    sparse_q = process_rr.phase_quadrants(_fake_tf(45.0, -135.0, [0.2, 0.5]))
    sparse_sidecar = process_rr.build_sidecar(res, args, started, finished, edi_path, png_path,
                                              sparse_q, [])
    assert sparse_sidecar["quadrant"]["verdict"].startswith("not judged:"), sparse_sidecar["quadrant"]
    print(f"  verdicts: physical {sidecar['quadrant']['verdict']!r}, flipped "
          f"{flipped_sidecar['quadrant']['verdict']!r}, sparse {sparse_sidecar['quadrant']['verdict']!r}")

    lines = process_rr.edi_info_lines(sidecar)
    assert any(line == "mtproc.taper=hann" for line in lines), lines
    assert any(line.startswith("mtproc.sidecar=") and line.endswith(".json") for line in lines), lines
    print(f"  edi_info_lines: {lines}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  process_rr_cli_unit ({len(tests)} tests)")
