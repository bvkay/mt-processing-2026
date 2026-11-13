# -*- coding: utf-8 -*-
"""
Unit test for the command line of scripts/process_rr.py

The script is run as a subprocess, as the GUI runs it, with `--dry-run`,
which resolves everything and exits without opening an archive or writing a
product; its `key: value` lines are parsed back. The functions a dry run
cannot reach (config building, the product stem, the sidecar, the quadrant
window and the masks of both sites) are called in-process.

Usage:
    python tests/process_rr_cli_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** a plain `process_rr.py <survey.yaml> D02 E08 --dry-run`
does not exit 0 with `local_archive` ending in `D02.h5`, `remote_archive` in
`E08.h5`, `stem` matching `D02_rr-E08_<YYYYMMDD-HHMM>` (no window in it),
`tag` empty, `window` "full overlap", `ignore_filters` False and the survey's
own band block (min_period 0.005, max_period 5000, periods_per_decade 10,
notch_frequencies "50, 150"); `--min-period 0.01 --max-period 1000
--per-decade 6 --notch "50,100,150"` do not each replace exactly their own
value and leave the others alone (`started`/`stem` excepted: each
subprocess starts at its own instant); `--no-filters` does not leave both
archive paths (still `<site>.h5`, no more `_unfiltered.h5`) with
`ignore_filters` True and both "local archive"/"remote archive" status lines
reading "no filters used (--no-filters)"; `--tag try2` does not put `_try2`
at the end of the stem and "try2" in `tag`; a start and an end do not appear
in `window` while leaving the stem exactly `D02_rr-E08_<stamp>_try2` (the
window nowhere in it); `--notch ""` does not clear the list; on a scratch
copy of curnamona_cube's config (workspace pointed at the real one, so D02's
and E08's real archives are read but never written to, and a throwaway
filters.yaml only the copy ever sees; the real curnamona files are never
touched), D02's declared filters gaining a notch its archive has no variant
for does not make the "local archive" status line read "raw: ...D02.h5,
variant: to build (<hash>)", or E08's unchanged status does not stay "none
declared"; or any of these runs writes a file anywhere (including a variant).

The advanced estimator flags. **This test also fails if** a plain dry run
does not say "tweaks: none" and print no `tweak.` line; `--taper hamming
--overlap 50 --no-prewhiten --r0 2.0` does not print exactly `tweak.taper:
hamming`, `tweak.overlap_pct: 50.0`, `tweak.prewhiten: False` and `tweak.r0:
2.0` (no other tweak, no "tweaks: none") with every other line as in the
plain run (`started`/`stem` excepted); or, building aurora's real config for
D02 against E08 with the survey's lemimt band scheme (in-process, through
`mt_workbench.process.kernel_dataset` with nothing patched, while this process
holds both archives open read-only with h5py, as the GUI holds one: HDF5
refuses a read-write open of a file already open read-only, so the build
fails unless mth5 itself opens them read-only), without tweaks any decimation level is not
window.type hann (the in-use default; aurora's own is
boxcar), overlap round(num_samples * 0.25) (or int(num_samples * 0.75) on a
level whose window lasts over 600 s, of which there must be at least one, so
the boost is really exercised), prewhitening_type "first difference" with
recoloring True, min_num_stft_windows 0, and regression max_iterations 10,
max_redescending_iterations 2, r0 1.5, u0 2.8, tolerance 0.005 (and
`mt_workbench.process.ESTIMATOR_DEFAULTS`, which the GUI compares against, does not
say the same); with the tweaks `resolve()` makes of those four flags, any
level is not window.type hamming with overlap round(num_samples * 0.5)
(the long-window boost replaced), prewhitening_type "" (which mth5's
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
the argv, the tag, the edi/figure names and a `versions` dict naming mt_workbench,
aurora, mth5, mt_metadata and mt_io, or is not JSON-serialisable as it
stands; a phase-quadrant verdict built from a mode 180 deg out of quadrant is
not "flipped: ..." and one built from too few usable periods is not "not
judged: ..."; or `quadrant_window` does not pick 0.1-10 s at 100 Hz and above
and 30-3000 s below that (on 10 Hz long-period data the 0.1-10 s window
can raise a false "180 deg out ... declare flip").

The band layout. **This test also fails if** a plain dry run does not print
`window_samples: 128`, `min_bin: none (the layout's own)` and
`lowest_harmonic: 6.4` beside the processing window's own `window` line;
`--window-samples 256` or `--min-bin 10` does not replace exactly its own
line (`window_samples: 256`, `min_bin: 10.0`) and move `lowest_harmonic` to 12.8
or 10.16, with every other line as in the plain run (`--min-period 0.01`
moves it to 3.2, the other band options leave it at 6.4); building aurora's
real config for D02 against E08 (as above) with `--window-samples 256` does
not give every decimation level a 256-sample window, with the 75 % overlap
on the levels whose window lasts over 600 s and 25 % on the others, and the
same band centre periods as the plain config; with `--min-bin 10` any band
of a decimated level starts below harmonic 10 by the index mt_metadata sets
from the level's own FFT frequencies, level 0 does not lose exactly two
bands, or a band centre period under 1000 s differs from the plain config's
by more than 1e-9 of itself; or the sidecar does not carry `window` and
`min_bin` in `band_scheme` (128 and None without the flags, 256 and 10.0
with them) and `lowest_harmonic` 6.4 (10.16); on a scratch copy whose
`processing:` block gives `min_bin: 10`, the resolution does not take 10
(lowest harmonic 10.16) without the flag, or `--min-bin 0` does not give
min_bin None and lowest harmonic 6.4 (the layout's own, which the Process
tab's "layout's own" passes; taken as a harmonic of 0 it fails in
build_band_scheme), or `--min-bin -1` is not refused naming --min-bin.

Both sites' time masks. **This test also fails if**, on a scratch copy of
curnamona_cube whose own masks.yaml holds three D02 masks (one written twice),
two E08 masks and one mask identical to one of D02's, one for the stack
STK_E08u and one for the archive-only SYN01 (the entries of E08, SYN01 and
STK_E08u of scope both, so that they apply as a remote; the scope rule
itself is tests/mask_scope_unit.py's), `resolve` for D02 rr E08 does not give `masks_local` D02's
three in start order, `masks_remote` E08's three, and `masks` the union in
start order: exactly the starts listed in MASK_UNION_STARTS, the shared
interval once (D02's entry), E08's own entries carrying E08's reasons; the
sidecar `build_sidecar` makes does not carry the same three lists in the
form masks.yaml holds them (`mt_workbench.masks.stored`: `channels` left out of an
entry on every channel) with
`masks_ignored` False; the dry run does not print "masks: D02 3, E08 3 (5
applied)"; with `--no-masks` all three lists are not empty with
`masks_ignored` True in `resolve` and the sidecar and "masks: ignored
(--no-masks)" printed; `--no-masks --masks` does not apply the five with
`masks_ignored` False, or `--masks --no-masks` applies any; D02 against the stack STK_E08u picks up its
masks.yaml entry (a stacked remote has none of its own); D02 against SYN01
(archive-only, no STK_ prefix: judged by name, like a site) does not carry
SYN01's entry; or, with data_root pointed at a folder that does not exist
(the data drive unplugged), resolve classes E08, a declared recorded site,
as virtual or leaves D02 or E08 out of `raw_sites` (workbench issue 32), or
`masks_remote` in `resolve` and the sidecar is not E08's three and `masks`
not the same union.

The products and the frame. **This test also fails if** the sidecar's
`xml` and `h5` are not the EDI's stem with .xml and .h5, or `frame` is not
what was passed (None when nothing is); or `test_products_written` fails:
for an aurora-shaped TF with the survey.yaml declination applied, the
EDI's raw text has no DECLINATION, DECLINATION.MODEL and DECLINATION.EPOCH
lines with -1.07, IGRF-14 and 2023.55, HEAD COORDINATE_SYSTEM and INFO
transfer_function.coordinate_system differ, or ey and hy are not at AZM 90;
the XML lacks the declination, RESIDCOV, INVSIGCOV or the orientations
Hy and Ey at 88.930 (90 + D); the h5 does not read back as one TF with the
declination and the same impedance. Its controls: mt_metadata's own XML
write of that TF must fail, and a site without a declination must give an
EDI with no DECLINATION line.

The rotation convention (Geotools': ZROT is the clockwise azimuth of the
data's x-axis from geographic north, the data unrotated). **This test also
fails if** `test_edi_zrot_is_declination` finds, for that TF with
declination -1.07 and the default layout_north (magnetic): ZROT not -1.07
at every period, or (with a tipper) TROT not -1.07 at every period; the
impedance and tipper of the EDI read back not equal at difference 0 to
those of the same TF written with ZROT 0 (no declination), or the TF's own
impedance changed by the write; the INFO lines mt_workbench.frame (azimuth
-1.07 deg clockwise from geographic north), mt_workbench.rotation (data
not rotated) and mt_workbench.declination=-1.07, declination_model=IGRF-14,
declination_epoch=2023.55 missing, any INFO line 160 characters or longer
or holding "|"; or the sidecar frame record's zrot not -1.07. Controls that
must fail the ZROT criterion: mt_metadata's unmodified EDI write of the
same TF (ZROT 0), the TF without a declination (ZROT 0, no declination
line) and layout_north geographic (ZROT 0, COORDINATE_SYSTEM geographic,
the declination still in HEAD).

`test_xml_frame_fields` fails if the XML of that TF, read back with
mt_metadata, does not give angle_to_geographic_north -1.07 and channel
orientations hx -1.07, hy 88.93, ex -1.07, ey 88.93; its impedance read back
differs at all from that of the control; or its Notes do not state the
convention (east of geographic north, positive clockwise, Geotools' ZROT,
the EDI's ZROT). The control, mt_metadata's unmodified XML write of the
same TF (hz trimmed by hand), must fail the angle criterion (angle 0,
orientations 0 and 90).

`test_residcov_cross_written_as_zero` fails if, for that TF with the
Ex-Ey residual cross term NaN (as aurora leaves it), the XML holds 1e32
inside a Z.RESIDCOV block or a zero on its diagonal, the Notes lack the
statement that the cross term is written as 0, or the h5 does not read
back the cross term as 0 with the same statement in the station comments.
Its control, mt_metadata's unmodified XML write, must hold 1e32 there.
The same text check runs on the Morocco sample XML of process_rr
(B03_rr-B04_*_declination-sample2.xml) when the workspace is mounted, and
the earlier sample (B03_rr-B04_20261002-1458_declination-sample.xml,
written before the fix) must fail it.
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
    """Write a scratch copy of curnamona_cube's survey.yaml and filters.yaml.

    The copy's workspace points at the real one, so the real D02.h5/E08.h5
    are read in place. `extra_filters` is merged into the copy's
    filters.yaml; the real files are only read.

    Args:
        scratch (Path): Folder for the copy.
        extra_filters (dict): Site entries to add to the copy's filters.yaml.

    Returns:
        Path: The copy's survey.yaml.
    """
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
    """Import the script as a module, for the functions --dry-run cannot exercise directly."""
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
    assert got["window_samples"] == "128", got["window_samples"]
    assert got["min_bin"] == "none (the layout's own)", got["min_bin"]
    assert got["lowest_harmonic"] == "6.4", got["lowest_harmonic"]
    # fails if hz is asked for on a broadband site (it made a nonsense tipper)
    assert got["output_channels"] == "ex, ey", got["output_channels"]
    print(f"  defaults: stem {got['stem']}, archives {Path(got['local_archive']).name} / "
          f"{Path(got['remote_archive']).name}, bands {got['min_period']}-{got['max_period']} s "
          f"at {got['periods_per_decade']}/decade, notches {got['notch_frequencies']!r}")


def test_each_band_option_overrides_only_itself() -> None:
    base = dry_run()
    for option, value, key, expected, lowest in (
        ("--min-period", "0.01", "min_period", "0.01", "3.2"),
        ("--max-period", "1000", "max_period", "1000.0", "6.4"),
        ("--per-decade", "6", "periods_per_decade", "6.0", "6.4"),
        ("--notch", "50,100,150", "notch_frequencies", "50, 100, 150", "6.4"),
        ("--window-samples", "256", "window_samples", "256", "12.8"),
        ("--min-bin", "10", "min_bin", "10.0", "10.16"),
    ):
        got = dry_run(option, value)
        assert got[key] == expected, f"{option} {value}: {key} {got[key]!r}"
        assert got["lowest_harmonic"] == lowest, f"{option} {value}: lowest_harmonic {got['lowest_harmonic']!r}"
        derived = {key, "lowest_harmonic"} | TIME_KEYS
        others = {k: v for k, v in got.items() if k not in derived}
        unchanged = {k: v for k, v in base.items() if k not in derived}
        assert others == unchanged, f"{option} changed more than {key}: {others} vs {unchanged}"
        print(f"  {option} {value} -> {key} {got[key]}, lowest_harmonic {lowest}, nothing else moved")
    cleared = dry_run("--notch", "")
    assert cleared["notch_frequencies"] == "", cleared["notch_frequencies"]
    print("  --notch \"\" -> no notch frequencies at all")


def test_min_bin_zero_is_the_layouts_own() -> None:
    import tempfile

    process_rr = _load_process_rr()
    started = dt.datetime(2026, 9, 23, 21, 15, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
        config.setdefault("processing", {})["min_bin"] = 10
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        def resolved(*options):
            args = process_rr.build_parser().parse_args([str(copy_yaml), LOCAL, REMOTE, *options])
            return process_rr.resolve(args, started)

        survey, own = resolved(), resolved("--min-bin", "0")
        assert survey["scheme_kwargs"]["min_bin"] == 10 and round(survey["lowest_harmonic"], 2) == 10.16,             (survey["scheme_kwargs"]["min_bin"], survey["lowest_harmonic"])
        assert own["scheme_kwargs"]["min_bin"] is None and round(own["lowest_harmonic"], 2) == 6.4,             (own["scheme_kwargs"]["min_bin"], own["lowest_harmonic"])
        process_rr.build_band_scheme(own["sample_rate"], **own["scheme_kwargs"])
        try:
            resolved("--min-bin", "-1")
        except SystemExit as exc:
            assert "--min-bin" in str(exc), exc
        else:
            raise AssertionError("--min-bin -1 was taken")
    print("  survey min_bin 10: taken without the flag (10.16); --min-bin 0 -> None (6.4); --min-bin -1 refused")


def test_overlap_from_the_survey_block() -> None:
    """This test fails if a survey's processing: overlap_long: does not reach the tweaks when --overlap-long is
    not given, if the flag does not win over it, if overlap: does not do the same for overlap_pct, if a block
    value outside [0, 100) is not refused, or if a survey without the keys gains a tweak."""
    import tempfile

    process_rr = _load_process_rr()
    started = dt.datetime(2026, 11, 8, 9, 40, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
        block = config.setdefault("processing", {})
        block["overlap_long"] = 25
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        def resolved(*options):
            args = process_rr.build_parser().parse_args([str(copy_yaml), LOCAL, REMOTE, *options])
            return process_rr.resolve(args, started)

        from_block = resolved()["tweaks"]
        assert from_block == {"overlap_pct_long": 25.0}, from_block
        flag_wins = resolved("--overlap-long", "50")["tweaks"]
        assert flag_wins == {"overlap_pct_long": 50.0}, flag_wins
        assert "overlap_long" not in resolved()["scheme_kwargs"], "the block key leaked into the band scheme"
        block["overlap"] = 30
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        both = resolved()["tweaks"]
        assert both == {"overlap_pct": 30.0, "overlap_pct_long": 25.0}, both
        block["overlap_long"] = 100
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        try:
            resolved()
        except ValueError as exc:
            assert "overlap_long" in str(exc), exc
        else:
            raise AssertionError("overlap_long: 100 was taken")
    plain = _load_process_rr().resolve(
        _load_process_rr().build_parser().parse_args([str(SURVEY), LOCAL, REMOTE]), started)["tweaks"]
    assert plain == {}, plain
    print("  survey overlap_long 25 -> tweak overlap_pct_long 25.0; --overlap-long 50 wins; overlap 30 reaches "
          "overlap_pct; 100 refused; a survey without the keys has no tweak")


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
    """Check the "local archive"/"remote archive" status lines.

    Runs on a scratch copy of curnamona_cube whose filters.yaml gains a notch
    for D02, whose real archive has no variant for it.
    """
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
    # the window is kept out of the product name, so it must not appear in the stem
    assert re.match(r"^D02_rr-E08_\d{8}-\d{4}_try2$", got["stem"]), got["stem"]
    assert "_w" not in got["stem"].replace("_rr-", ""), f"a window token leaked into the stem: {got['stem']}"
    print(f"  --tag try2 with a window: stem {got['stem']}, tag {got['tag']!r}, window {got['window']!r}")


def test_tweaks_print_only_what_was_given() -> None:
    base = dry_run()
    assert base.get("tweaks") == "none", base.get("tweaks")
    assert not [k for k in base if k.startswith("tweak.")], base
    long_only = dry_run("--overlap-long", "0")
    assert {k: v for k, v in long_only.items() if k.startswith("tweak.")} == {"tweak.overlap_pct_long": "0.0"}, long_only
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
# output (not taken from mt_workbench.process), and what the four flags must make
IN_USE = {"type": "hann", "prewhitening_type": "first difference", "recoloring": True,
          "min_num_stft_windows": 0, "max_iterations": 10, "max_redescending_iterations": 2,
          "r0": 1.5, "u0": 2.8, "tolerance": 0.005}
TWEAKED = {**IN_USE, "type": "hamming", "prewhitening_type": "", "recoloring": False, "r0": 2.0}


def level_values(dec) -> dict:
    """Return one decimation level's estimator settings, enums read as their plain strings."""
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
    from mt_workbench.bands import build_band_scheme
    from mt_workbench.process import ESTIMATOR_DEFAULTS, apply_tweaks, build_config, kernel_dataset

    process_rr = _load_process_rr()
    started = dt.datetime.now().astimezone()
    argv = [str(SURVEY), LOCAL, REMOTE, "--taper", "hamming", "--overlap", "50", "--no-prewhiten",
            "--r0", "2.0"]
    res = process_rr.resolve(process_rr.build_parser().parse_args(argv), started)
    assert res["tweaks"] == {"taper": "hamming", "overlap_pct": 50.0, "prewhiten": False, "r0": 2.0},         res["tweaks"]
    scheme = build_band_scheme(res["survey"].sample_rate, **res["scheme_kwargs"])

    # read-only, as mth5 opens the archives itself: both are held open read-only for the
    # whole build, and HDF5 refuses a read-write open of a file this process already holds
    # read-only ("file is already open for read-only")
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
    # overlap_pct_long reaches the long levels only: 0 % there, the short levels keep their 25 %
    apply_tweaks(configs["in use"], {"overlap_pct_long": 0.0})
    touched = 0
    for dec in configs["in use"].decimations:
        n, seconds = dec.stft.window.num_samples, dec.stft.window.num_samples / dec.decimation.sample_rate
        want = 0 if seconds > 600.0 else round(n * 0.25)
        touched += seconds > 600.0
        assert dec.stft.window.overlap == want, ("overlap_pct_long", dec.decimation.level, dec.stft.window.overlap, want)
    assert touched == long_levels, (touched, long_levels)
    # given with overlap_pct, the long value wins on the long levels only
    apply_tweaks(configs["in use"], {"overlap_pct": 50.0, "overlap_pct_long": 10.0})
    for dec in configs["in use"].decimations:
        n, seconds = dec.stft.window.num_samples, dec.stft.window.num_samples / dec.decimation.sample_rate
        want = round(n * 0.10) if seconds > 600.0 else round(n * 0.50)
        assert dec.stft.window.overlap == want, ("both overlaps", dec.decimation.level, dec.stft.window.overlap, want)
    for bad in ({"overlap_pct_long": 100.0}, {"overlap_pct_long": -1.0}, {"overlap_long": 25.0}):
        try:
            apply_tweaks(configs["in use"], bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"apply_tweaks accepted {bad}")
    print(f"  config D02 rr E08, {len(levels)} levels ({long_levels} with windows over 600 s): "
          f"in use {IN_USE['type']}, overlap 25 %/75 %, r0 {IN_USE['r0']}; tweaked hamming, overlap "
          f"50 % on every level, prewhitening off, r0 2.0; dpss builds; built while both archives were "
          f"held read-only, a second read-only handle opened, mtimes unchanged")


def test_band_layout_reaches_every_decimation_level() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.bands import build_band_scheme
    from mt_workbench.process import build_config, kernel_dataset

    process_rr = _load_process_rr()
    started = dt.datetime.now().astimezone()
    configs = {}
    for name, flags in (("plain", []), ("window 256", ["--window-samples", "256"]), ("min_bin 10", ["--min-bin", "10"])):
        res = process_rr.resolve(process_rr.build_parser().parse_args([str(SURVEY), LOCAL, REMOTE, *flags]), started)
        scheme = build_band_scheme(res["survey"].sample_rate, **res["scheme_kwargs"])
        kd = kernel_dataset(res["local_archive"], LOCAL, res["remote_archive"], REMOTE)
        configs[name] = build_config(kd, scheme, None, output_channels=res["output_channels"])

    def periods(config, below=float("inf")):
        """Every band's centre period in s under `below`, sorted."""
        return sorted(float(b.center_period) for dec in config.decimations for b in dec.bands
                      if float(b.center_period) < below)

    long_levels = 0
    for dec in configs["window 256"].decimations:
        n, seconds = dec.stft.window.num_samples, dec.stft.window.num_samples / dec.decimation.sample_rate
        assert n == 256, (dec.decimation.level, n)
        want = int(n * 0.75) if seconds > 600.0 else round(n * 0.25)
        long_levels += seconds > 600.0
        assert dec.stft.window.overlap == want, (dec.decimation.level, dec.stft.window.overlap, want)
    assert long_levels >= 1, "no level has a window over 600 s: the boost is never exercised"
    assert periods(configs["window 256"]) == periods(configs["plain"]), "the periods moved with the window"
    plain, moved = configs["plain"].decimations, configs["min_bin 10"].decimations
    first = {int(dec.decimation.level): min(int(b.index_min) for b in dec.bands) for dec in moved}
    assert all(k >= 10 for level, k in first.items() if level > 0), first
    assert len(plain[0].bands) - len(moved[0].bands) == 2, (len(plain[0].bands), len(moved[0].bands))
    got, want = periods(configs["min_bin 10"], 1000.0), periods(configs["plain"], 1000.0)
    assert len(got) == len(want) and all(abs(g - w) <= 1e-9 * w for g, w in zip(got, want)), (got, want)
    print(f"  config D02 rr E08: --window-samples 256 -> 256 samples on all {len(configs['window 256'].decimations)} "
          f"levels ({long_levels} at 75 % overlap), the same {len(periods(configs['plain']))} periods; --min-bin 10 -> "
          f"first harmonic {min(k for level, k in first.items() if level > 0)} on the decimated levels (7 plain), "
          f"level 0 {len(moved[0].bands)} bands (6 plain), the {len(got)} periods under 1000 s unchanged")


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
    """Build a minimal in-memory mt_metadata TF: `periods` s, constant phases (deg), |Z| = 1."""
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


def _mask(start: str, end: str, reason: str, bands="all", scope: str | None = None) -> dict:
    """Build one masks.yaml entry found by "time"; `scope` is left out when None."""
    out = {"start": start, "end": end, "bands": bands, "reason": reason, "found_by": "time"}
    return out if scope is None else {**out, "scope": scope}


MASKS_BOTH = {
    LOCAL: [_mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z", "D02 spike"),
            _mask("2021-06-29T08:00:00Z", "2021-06-29T08:30:00Z", "D02 band", [0.01, 0.1]),
            _mask("2021-06-29T10:00:00Z", "2021-06-29T10:20:00Z", "D02 spike again"),
            _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z", "D02 night")],
    REMOTE: [_mask("2021-06-29T12:00:00Z", "2021-06-29T12:05:00Z", "E08 band", [1.0, 10.0], "both"),
             _mask("2021-06-29T09:00:00Z", "2021-06-29T09:15:00Z", "E08 fence", scope="both"),
             _mask("2021-06-30T01:00:00Z", "2021-06-30T01:10:00Z", "E08 same as D02 night", scope="both")],
    "SYN01": [_mask("2021-06-29T11:00:00Z", "2021-06-29T11:30:00Z", "SYN01 declared by hand", scope="both")],
    "STK_E08u": [_mask("2021-06-29T11:00:00Z", "2021-06-29T11:30:00Z", "a stack has no masks", scope="both")],
}
# stated here, not computed from the masks: the union's starts and reasons, earliest first
MASK_UNION_STARTS = ["2021-06-29T08:00:00Z", "2021-06-29T09:00:00Z", "2021-06-29T10:00:00Z",
                     "2021-06-29T12:00:00Z", "2021-06-30T01:00:00Z"]
MASK_UNION_REASONS = ["D02 band", "E08 fence", "D02 spike", "E08 band", "D02 night"]


def test_masks_from_both_sites() -> None:
    from mt_workbench.masks import stored
    import numpy as np

    process_rr = _load_process_rr()
    started = dt.datetime(2026, 9, 24, 9, 0, 0, tzinfo=dt.timezone.utc)
    physical = process_rr.phase_quadrants(_fake_tf(45.0, -135.0, np.geomspace(0.1, 10.0, 8)))
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        (Path(tmp) / "masks.yaml").write_text(yaml.safe_dump(MASKS_BOTH, sort_keys=False), encoding="utf-8")

        def resolved(*extra):
            """Resolve D02 rr E08 on the copy and build its sidecar; return (resolution, sidecar)."""
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
            assert sidecar[key] == [stored(m) for m in res[key]], (key, sidecar[key])
            assert all("channels" not in m for m in sidecar[key]), (key, sidecar[key])
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

        # the later flag wins: a campaign config's --masks after the runner's --no-masks
        res, sidecar = resolved("--no-masks", "--masks")
        assert len(res["masks"]) == 5 and res["masks_ignored"] is False and sidecar["masks_ignored"] is False,             (len(res["masks"]), res["masks_ignored"])
        res, sidecar = resolved("--masks", "--no-masks")
        assert res["masks"] == [] and res["masks_ignored"] is True, (res["masks"], res["masks_ignored"])
        print("  --no-masks --masks: 5 applied; --masks --no-masks: ignored (the later flag wins)")

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

    # data_root on a drive that is not plugged in: E08 is declared, so it is still a
    # recorded remote at data_root/E08 (workbench issue 32), and its masks apply
    with tempfile.TemporaryDirectory() as tmp:
        copy_yaml = make_survey_copy(Path(tmp), {})
        config = yaml.safe_load(copy_yaml.read_text(encoding="utf-8"))
        config["data_root"] = str(Path(tmp) / "drive_not_mounted")
        copy_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        (Path(tmp) / "masks.yaml").write_text(yaml.safe_dump(MASKS_BOTH, sort_keys=False), encoding="utf-8")
        res, sidecar = resolved()
        folders = {site: Path(res["raw_sites"].get(site, "")) for site in (LOCAL, REMOTE)}
        assert all(f.name == site and f.parent.name == "drive_not_mounted" for site, f in folders.items()), folders
        assert res["virtual_remote"] is False, res["virtual_remote"]
        assert [m["reason"] for m in res["masks_remote"]] == [
            "E08 fence", "E08 band", "E08 same as D02 night"], res["masks_remote"]
        assert [m["start"] for m in res["masks"]] == MASK_UNION_STARTS, [m["start"] for m in res["masks"]]
        assert sidecar["masks_remote"] == [stored(m) for m in res["masks_remote"]], sidecar["masks_remote"]
        print(f"  data_root unmounted (E08 still recorded, not virtual): masks_remote {len(res['masks_remote'])}, "
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
    assert sidecar["band_scheme"]["window"] == 128 and sidecar["band_scheme"]["min_bin"] is None, sidecar["band_scheme"]
    assert sidecar["lowest_harmonic"] == 6.4, sidecar["lowest_harmonic"]
    layout_args = process_rr.build_parser().parse_args(
        [str(SURVEY), LOCAL, REMOTE, "--window-samples", "256", "--min-bin", "10"])
    layout = process_rr.build_sidecar(process_rr.resolve(layout_args, started), layout_args, started, finished,
                                      edi_path, png_path, process_rr.phase_quadrants(
                                          _fake_tf(45.0, -135.0, np.geomspace(0.1, 10.0, 8))), [])
    assert layout["band_scheme"]["window"] == 256 and layout["band_scheme"]["min_bin"] == 10.0, layout["band_scheme"]
    assert round(layout["lowest_harmonic"], 2) == 10.16, layout["lowest_harmonic"]
    assert sidecar["tweaks"] == process_rr.ESTIMATOR_DEFAULTS, "no --taper given: must fall back to the default"
    assert sidecar["tweaks"]["taper"] == "hann", sidecar["tweaks"]
    assert sidecar["argv"] == list(sys.argv), sidecar["argv"]
    assert sidecar["tag"] == "sidecar-test", sidecar["tag"]
    assert sidecar["edi"] == edi_path.name and sidecar["figure"] == png_path.name, sidecar
    assert sidecar["xml"] == edi_path.with_suffix(".xml").name, sidecar["xml"]
    assert sidecar["h5"] == edi_path.with_suffix(".h5").name, sidecar["h5"]
    assert sidecar["frame"] is None, sidecar["frame"]  # none passed
    framed = process_rr.build_sidecar(res, args, started, finished, edi_path, png_path, physical, [],
                                      {"reference_frame": "geomagnetic", "declination": -1.07})
    assert framed["frame"] == {"reference_frame": "geomagnetic", "declination": -1.07}, framed["frame"]
    assert sidecar["quadrant"]["verdict"] == "physical quadrants", sidecar["quadrant"]
    for lib in ("mt_workbench", "aurora", "mth5", "mt_metadata", "mt_io"):
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
    assert any(line == "mt_workbench.taper=hann" for line in lines), lines
    assert any(line.startswith("mt_workbench.sidecar=") and line.endswith(".json") for line in lines), lines
    print(f"  edi_info_lines: {lines}")


def _aurora_like_tf():
    """Build a TF shaped as aurora returns one for a site without hz.

    Two runs at 1000 Hz, the first listing hz and the second not, no
    tipper, residual and inverse signal covariances, the sensor frame
    (geomagnetic, ey and hy at 90 deg), an empty tf_id and the archive's
    unset declination (0.0, no epoch).
    """
    import numpy as np
    from mt_metadata.timeseries import Electric, Magnetic, Run
    from mt_metadata.transfer_functions.core import TF

    period = np.geomspace(0.01, 100.0, 6)
    tf = TF()
    tf.station = "FAKE"
    tf.survey_metadata.id = "test"
    tf.station_metadata.orientation.reference_frame = "geomagnetic"
    for run_id, comps in (("sr1000_0002", ("ex", "ey", "hx", "hy", "hz")), ("sr1000_0003", ("ex", "ey", "hx", "hy"))):
        run = Run(id=run_id, sample_rate=1000.0)
        for comp in comps:
            ch = Electric(component=comp) if comp.startswith("e") else Magnetic(component=comp)
            ch.measurement_azimuth = 90.0 if comp in ("ey", "hy") else 0.0
            run.add_channel(ch)
        tf.station_metadata.add_run(run)
    tf.period = period
    z = np.zeros((period.size, 2, 2), dtype=complex)
    z[:, 0, 1], z[:, 1, 0] = 1.0 + 1.0j, -1.0 - 1.0j
    tf.impedance = z
    tf.impedance_error = np.full((period.size, 2, 2), 0.1)
    tf.residual_covariance = np.tile(np.eye(3, dtype=complex) * 0.01, (period.size, 1, 1))
    tf.inverse_signal_power = np.tile(np.eye(2, dtype=complex) * 2.0, (period.size, 1, 1))
    return tf


def _edi_head(path: Path) -> tuple[dict, str | None, dict]:
    """Read an EDI's raw text: HEAD key=value pairs, the INFO coordinate_system, and AZM per channel."""
    text = path.read_text(encoding="latin-1")
    head = dict(re.findall(r"^\s*([A-Z_.]+)=(.*?)\s*$", text.split(">INFO")[0], re.M))
    info = re.search(r"transfer_function\.coordinate_system=(\S+)", text)
    azm = {m.group(1): float(m.group(2)) for m in re.finditer(r"CHTYPE=(\w+) .*?AZM=([-\d.]+)", text)}
    return head, info.group(1) if info else None, azm


def test_products_written() -> None:
    """Check the three products `mt_workbench.products.write_products` writes for a row.

    Fails if, for an aurora-shaped TF with a survey.yaml declination applied
    (`apply_site_declination` from a SiteConfig: -1.07, IGRF-14, 2023.55),
    the EDI's raw text lacks DECLINATION=-1.07, DECLINATION.MODEL=IGRF-14 or
    DECLINATION.EPOCH=2023.55, its HEAD COORDINATE_SYSTEM and INFO
    transfer_function.coordinate_system are not both geomagnetic, or ey and
    hy are not at AZM=90; the XML lacks Declination -1.070, the RESIDCOV
    and INVSIGCOV estimates, Hy and Ey at orientation 88.930 (90 + D) or the
    frame note;
    the h5 does not open as one TF that reads back with the declination and
    the same impedance; or the TF's channels were changed by the writes
    (translated_azimuth set on ex or ey). Controls: mt_metadata's own XML
    write of the same TF must fail (a run listing hz beside one without:
    the reason `write_xml` keeps only the channels with data), and a
    SiteConfig with no declination must leave the TF as it was, so its EDI
    has no DECLINATION line.
    """
    import copy

    import numpy as np
    from mth5.mth5 import MTH5

    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.products import apply_site_declination, write_products
    from mt_workbench.survey import SiteConfig

    try:
        copy.deepcopy(_aurora_like_tf()).write(fn=str(Path(tempfile.gettempdir()) / "control.xml"), file_type="xml")
    except AttributeError:
        pass
    else:
        raise AssertionError("control: mt_metadata's XML writer took the aurora-shaped TF; the trim is untested")
    with tempfile.TemporaryDirectory() as tmp:
        tf = _aurora_like_tf()
        assert apply_site_declination(tf.station_metadata, SiteConfig(name="FAKE", declination=-1.07,
                                      declination_model="IGRF-14", declination_epoch=2023.55))
        paths = write_products(tf, Path(tmp) / "FAKE_rr-REM_20261002-1200_t.edi")
        assert sorted(p.name for p in Path(tmp).iterdir()) == sorted(p.name for p in paths.values()), \
            list(Path(tmp).iterdir())
        head, info, azm = _edi_head(paths["edi"])
        assert (head.get("DECLINATION"), head.get("DECLINATION.MODEL"), head.get("DECLINATION.EPOCH")) == \
            ("-1.07", "IGRF-14", "2023.55"), head
        assert head.get("COORDINATE_SYSTEM") == info == "geomagnetic", (head.get("COORDINATE_SYSTEM"), info)
        assert azm.get("ey") == 90.0 and azm.get("hy") == 90.0, azm
        xml = paths["xml"].read_text(encoding="utf-8")
        for needle in ('<Declination epoch="2023">-1.070</Declination>', '<Estimate name="RESIDCOV"',
                       '<Estimate name="INVSIGCOV"', '<Magnetic name="Hy" orientation="88.930"',
                       '<Electric name="Ey" orientation="88.930"', "Frame: geomagnetic"):
            assert needle in xml, needle
        m = MTH5()
        m.open_mth5(paths["h5"], "r")
        try:
            df = m.tf_summary.to_dataframe()
            assert len(df) == 1, df
            row = df.iloc[0]
            back = m.get_transfer_function(row.station, row.tf_id, survey=row.survey)
            d = back.station_metadata.location.declination
            assert (d.value, d.model, d.epoch) == (-1.07, "IGRF-14", "2023.55"), d
            assert np.allclose(back.impedance.data, tf.impedance.data), "h5 impedance differs"
        finally:
            m.close_mth5()
        assert all(ch.translated_azimuth is None for run in tf.station_metadata.runs for ch in run.channels)

        plain = _aurora_like_tf()
        assert not apply_site_declination(plain.station_metadata, SiteConfig(name="FAKE"))
        control = write_products(plain, Path(tmp) / "control.edi")
        chead, cinfo, _ = _edi_head(control["edi"])
        assert "DECLINATION" not in chead and chead.get("COORDINATE_SYSTEM") == cinfo, chead
    print(f"  products: {', '.join(p.name for p in paths.values())}; DECLINATION {head['DECLINATION']} "
          f"{head['DECLINATION.MODEL']} {head['DECLINATION.EPOCH']}; HEAD/INFO {info}; AZM {azm}; XML with RESIDCOV, "
          f"INVSIGCOV; h5 tf_id {row.tf_id}; controls: raw XML write fails, no declination -> no line")


DECL = {"declination": -1.07, "declination_model": "IGRF-14", "declination_epoch": 2023.55}
# the Morocco sample of process_rr (B03 rr B04 --masks), written before and after the fix
SAMPLE_TF = Path(r"D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace\qc\survey\declination_xml_h5_20261002\sample\tf")
SAMPLE_BEFORE = SAMPLE_TF / "B03_rr-B04_20261002-1458_declination-sample.xml"


def _framed_tf(tipper: bool = False, **site):
    """Return `_aurora_like_tf` with the frame of a SiteConfig(name="FAKE", **site) applied.

    With `tipper` the TF carries a tipper (TROT is then written).
    """
    import numpy as np

    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.products import apply_site_frame
    from mt_workbench.survey import SiteConfig

    tf = _aurora_like_tf()
    if tipper:
        n = tf.period.size
        tf.tipper = np.tile(np.array([[[0.1 + 0.05j, -0.2 + 0.02j]]]), (n, 1, 1))
        tf.tipper_error = np.full((n, 1, 2), 0.01)
    apply_site_frame(tf.station_metadata, SiteConfig(name="FAKE", **site))
    return tf


def _rot_block(text: str, key: str):
    """Return the values of an EDI's >ZROT or >TROT block, or None when there is none."""
    import numpy as np

    m = re.search(rf"^>{key}\b[^\n]*\n(.*?)(?:\n\s*\n|\n>)", text, re.S | re.M)
    return None if m is None else np.array([float(v) for v in m.group(1).split()])


def _hand_trimmed(tf):
    """Return a copy of an `_aurora_like_tf` without hz, for mt_metadata's unmodified XML write."""
    import copy

    tfc = copy.deepcopy(tf)
    for run in tfc.station_metadata.runs:
        if "hz" in [ch.component for ch in run.channels]:
            run.remove_channel("hz")
    return tfc


def _residcov_problems(text: str) -> list[str]:
    """List what is wrong in an EMTF XML's Z.RESIDCOV blocks: an EMPTY 1e32 anywhere, a zero on the diagonal."""
    blocks = re.findall(r"<Z\.RESIDCOV\b.*?</Z\.RESIDCOV>", text, re.S)
    if not blocks:
        return ["no Z.RESIDCOV block"]
    problems = []
    for k, block in enumerate(blocks):
        values = re.findall(r'<value output="(\w+)" input="(\w+)">\s*(\S+)\s+(\S+)\s*</value>', block)
        if len(values) != 4:
            problems.append(f"period {k}: {len(values)} values")
        for out, inp, re_text, im_text in values:
            v = complex(float(re_text), float(im_text))
            if abs(v.real) >= 1e31 or abs(v.imag) >= 1e31:
                problems.append(f"period {k}: {out}-{inp} {re_text} {im_text} (EMPTY)")
            if out == inp and v == 0:
                problems.append(f"period {k}: {out}-{inp} zero on the diagonal")
    return problems


def test_edi_zrot_is_declination() -> None:
    """Check that the EDI carries ZROT = TROT = the declination with the data unrotated.

    Criteria in the module docstring (the rotation convention); each
    control must fail the ZROT criterion.
    """
    import copy

    import numpy as np
    from mt_metadata.transfer_functions.core import TF

    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.products import INFO_MAX, frame_record, match_coordinate_system, write_edi

    d = DECL["declination"]

    def zrot_is_d(values) -> bool:
        return values is not None and values.size == 6 and bool(np.all(values == d))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tf = _framed_tf(tipper=True, **DECL)
        z0, t0 = tf.impedance.data.copy(), tf.tipper.data.copy()
        match_coordinate_system(tf)
        edi = write_edi(tf, tmp / "decl.edi")
        assert np.array_equal(tf.impedance.data, z0) and np.array_equal(tf.tipper.data, t0), "the write changed the TF"
        text = edi.read_text(encoding="latin-1")
        zrot, trot = _rot_block(text, "ZROT"), _rot_block(text, "TROT")
        assert zrot_is_d(zrot), f"ZROT {zrot}"
        assert zrot_is_d(trot), f"TROT {trot}"

        plain = _framed_tf(tipper=True)
        match_coordinate_system(plain)
        ptext = write_edi(plain, tmp / "plain.edi").read_text(encoding="latin-1")
        pz = _rot_block(ptext, "ZROT")
        assert not zrot_is_d(pz) and np.all(pz == 0) and "DECLINATION=" not in ptext, f"control: no declination, {pz}"
        back, pback = TF(edi), TF(tmp / "plain.edi")
        back.read()
        pback.read()
        dz = np.abs(back.impedance.data - pback.impedance.data).max()
        dt_ = np.abs(back.tipper.data - pback.tipper.data).max()
        assert dz == 0 and dt_ == 0, f"read back with ZROT {d} differs from ZROT 0: Z {dz}, T {dt_}"
        assert np.allclose(back.impedance.data, z0, rtol=1e-6), "read back differs from the TF beyond the text precision"
        assert np.all(np.asarray(back._rotation_angle) == d), back._rotation_angle

        info = [line for line in text.split(">INFO")[1].split(">=DEFINEMEAS")[0].splitlines() if "mt_workbench." in line]
        bad = [line for line in info if len(line) >= INFO_MAX or "|" in line]
        assert not bad, bad
        lines = dict(re.findall(r"processing_parameters\.(mt_workbench\.[a-z_]+)=(.*?)\s*$", text, re.M))
        assert lines.get("mt_workbench.frame") == ("sensor frame, x-axis at azimuth -1.07 deg clockwise from "
                                                   "geographic north"), lines
        assert lines.get("mt_workbench.rotation", "").startswith("data not rotated; ZROT and TROT state this azimuth")
        assert (lines.get("mt_workbench.declination"), lines.get("mt_workbench.declination_model"),
                lines.get("mt_workbench.declination_epoch")) == ("-1.07", "IGRF-14", "2023.55"), lines
        assert frame_record(tf)["zrot"] == d, frame_record(tf)

        raw = tmp / "raw.edi"
        copy.deepcopy(tf).write(fn=str(raw), file_type="edi")
        rz = _rot_block(raw.read_text(encoding="latin-1"), "ZROT")
        assert not zrot_is_d(rz), f"control: mt_metadata's unmodified write gave ZROT {rz}"

        geo = _framed_tf(tipper=True, layout_north="geographic", **DECL)
        match_coordinate_system(geo)
        gtext = write_edi(geo, tmp / "geo.edi").read_text(encoding="latin-1")
        gz = _rot_block(gtext, "ZROT")
        head = dict(re.findall(r"^\s*([A-Z_.]+)=(.*?)\s*$", gtext.split(">INFO")[0], re.M))
        assert not zrot_is_d(gz) and np.all(gz == 0), f"control: geographic layout gave ZROT {gz}"
        assert head.get("COORDINATE_SYSTEM") == "geographic" and head.get("DECLINATION") == "-1.07", head
        assert frame_record(geo)["zrot"] == 0.0
    print(f"  ZROT {zrot[:3]}..., TROT {trot[:3]}... ({zrot.size} periods); Z and T read back equal to the ZROT 0 "
          f"write at difference {dz:g}/{dt_:g}; INFO {len(info)} mt_workbench lines, longest "
          f"{max(len(line) for line in info)} characters; controls: unmodified write ZROT {rz[0]:g}, no declination "
          f"ZROT {pz[0]:g}, geographic layout ZROT {gz[0]:g} with DECLINATION {head['DECLINATION']}")


def test_xml_frame_fields() -> None:
    """Check the XML's Orientation and channel orientations against the declination, read back with mt_metadata.

    Criteria in the module docstring; the unmodified write must fail.
    """
    import numpy as np
    from mt_metadata.transfer_functions.core import TF

    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.products import write_xml

    d = DECL["declination"]
    want = {"ex": d, "ey": 90.0 + d, "hx": d, "hy": 90.0 + d}

    def read_frame(path: Path):
        back = TF(path)
        back.read()
        az = {ch.component: float(ch.measurement_azimuth) for ch in back.station_metadata.runs[0].channels}
        return back.station_metadata.orientation.angle_to_geographic_north, az, back.impedance.data

    def frame_ok(angle, az) -> bool:
        return angle is not None and abs(angle - d) < 1e-9 and set(az) == set(want) and \
            all(abs(az[c] - want[c]) < 1e-9 for c in want)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tf = _framed_tf(**DECL)
        path = write_xml(tf, tmp / "decl.xml")
        angle, az, z = read_frame(path)
        assert frame_ok(angle, az), (angle, az)
        notes = re.search(r"<Notes>(.*?)</Notes>", path.read_text(encoding="utf-8"), re.S).group(1)
        for needle in ("azimuth -1.07 deg east of geographic north (positive clockwise)", "Geotools writes for ZROT",
                       "the EDI's ZROT and TROT carry the same number"):
            assert needle in notes, needle
        raw = tmp / "raw.xml"
        _hand_trimmed(tf).write(fn=str(raw), file_type="xml")
        c_angle, c_az, c_z = read_frame(raw)
        assert not frame_ok(c_angle, c_az), f"control: the unmodified write passed ({c_angle}, {c_az})"
        dz = np.abs(z - c_z).max()
        assert dz == 0, f"XML impedance differs from the unmodified write's by {dz}"
    print(f"  XML read back: angle {angle}, orientations {az}; Z equal to the unmodified write's at difference "
          f"{dz:g}; control (unmodified write): angle {c_angle}, orientations {c_az}")


def test_residcov_cross_written_as_zero() -> None:
    """Check that an unestimated Ex-Ey residual cross term is written as 0, not 1e32.

    Criteria in the module docstring; the unmodified write and the sample
    written before the fix must fail.
    """
    import numpy as np
    from mth5.mth5 import MTH5

    sys.path.insert(0, str(REPO / "src"))
    from mt_workbench.products import CROSS_NOTE, write_products

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tf = _framed_tf(**DECL)
        rc = tf.residual_covariance.copy()
        for out, inp in (("ex", "ey"), ("ey", "ex")):
            rc.loc[dict(output=out, input=inp)] = np.nan
        tf.residual_covariance = rc
        assert np.isnan(tf.residual_covariance.loc[dict(output="ex", input="ey")].data).all(), "setup: no NaN"
        paths = write_products(tf, tmp / "cross.edi")
        text = paths["xml"].read_text(encoding="utf-8")
        problems = _residcov_problems(text)
        assert not problems, problems[:4]
        assert CROSS_NOTE in text, "Notes lack the cross-term statement"
        m = MTH5()
        m.open_mth5(paths["h5"], "r")
        try:
            row = m.tf_summary.to_dataframe().iloc[0]
            back = m.get_transfer_function(row.station, row.tf_id, survey=row.survey)
            cross = back.residual_covariance.loc[dict(output="ex", input="ey")].data
            comment = back.station_metadata.comments.value or ""
        finally:
            m.close_mth5()
        assert np.all(cross == 0), cross
        assert CROSS_NOTE in comment, comment
        raw = tmp / "raw.xml"
        _hand_trimmed(tf).write(fn=str(raw), file_type="xml")
        control = _residcov_problems(raw.read_text(encoding="utf-8"))
        assert any("EMPTY" in p for p in control), f"control: the unmodified write has no 1e32 ({control})"
    sample = sorted(SAMPLE_TF.glob("B03_rr-B04_*_declination-sample2.xml")) if SAMPLE_TF.is_dir() else []
    if sample:
        got = _residcov_problems(sample[-1].read_text(encoding="utf-8"))
        assert not got, (sample[-1].name, got[:4])
        before = _residcov_problems(SAMPLE_BEFORE.read_text(encoding="utf-8"))
        assert any("EMPTY" in p for p in before), f"control: {SAMPLE_BEFORE.name} passed"
        on_sample = (f"; sample {sample[-1].name}: {text_count(sample[-1])} RESIDCOV blocks clean; control "
                     f"{SAMPLE_BEFORE.name}: {len(before)} EMPTY values")
    else:
        on_sample = f"; no sample2 XML under {SAMPLE_TF} (workspace not mounted or not yet written): skipped"
    print(f"  cross term NaN -> XML 0, diagonal non-zero, Notes and h5 comments state it, h5 cross {cross[0]}; "
          f"control (unmodified write): {len(control)} EMPTY values{on_sample}")


def text_count(path: Path) -> int:
    """Count the Z.RESIDCOV blocks of an XML."""
    return path.read_text(encoding="utf-8").count("<Z.RESIDCOV")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  process_rr_cli_unit ({len(tests)} tests)")
