"""Unit test for `scripts/process_rr.py`'s command line, through --dry-run.

    python tests/process_rr_cli_unit.py

The script is run as a subprocess (the way the GUI runs it) with `--dry-run`,
which resolves everything and exits without opening an archive or writing a
product. Its `key: value` lines are parsed back here.

**This test fails if** a plain `process_rr.py <survey.yaml> D02 E08 --dry-run`
does not exit 0 with `local_archive` ending in `D02.h5`, `remote_archive` in
`E08.h5`, `tag` exactly `D02_rr-E08`, `window` "full overlap",
`ignore_filters` False and the survey's own band block
(min_period 0.005, max_period 5000, periods_per_decade 10,
notch_frequencies "50, 150"); `--min-period 0.01 --max-period 1000
--per-decade 6 --notch "50,100,150"` do not each replace exactly their own
value and leave the others alone; `--no-filters` does not turn both archive
paths into `_unfiltered.h5` and `ignore_filters` True; `--tag try2` does not
put `_try2` at the end of the tag; a start and an end do not appear in
`window` and as a `_w<start>-<end>` suffix on the tag; `--notch ""` does not
clear the list; or any of these runs writes a file under the workspace.

The advanced estimator flags. **This test also fails if** a plain dry run
does not say "tweaks: none" and print no `tweak.` line; `--taper hann
--overlap 50 --no-prewhiten --r0 2.0` does not print exactly `tweak.taper:
hann`, `tweak.overlap_pct: 50.0`, `tweak.prewhiten: False` and `tweak.r0:
2.0` -- no other tweak, no "tweaks: none" -- with every other line as in the
plain run; or, building aurora's real config for D02 against E08 with the
survey's lemimt band scheme (in-process, the archives opened read-only),
without tweaks any decimation level is not window.type boxcar, overlap
round(num_samples * 0.25) -- or int(num_samples * 0.75) on a level whose
window lasts over 600 s, of which there must be at least one, so the boost
is really exercised -- prewhitening_type "first difference" with
recoloring True, min_num_stft_windows 0, and regression max_iterations 10,
max_redescending_iterations 2, r0 1.5, u0 2.8, tolerance 0.005 (and
`bbmt.process.ESTIMATOR_DEFAULTS`, which the GUI compares against, does not
say the same); with the tweaks `resolve()` makes of those four flags, any
level is not window.type hann with overlap round(num_samples * 0.5) --
the long-window boost replaced -- prewhitening_type "" (which mth5's
`apply_prewhitening` must hand back untouched) with recoloring False and r0
2.0, or any other value moved from the defaults above; a dpss taper does not
build a finite taper of num_samples points on every level; or the config
builds change the modification time of D02.h5 or E08.h5.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "process_rr.py"
SURVEY = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
LOCAL, REMOTE = "D02", "E08"
MTH5_DIR = REPO / "surveys" / "curnamona_cube" / "work" / "mth5"


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
    assert got["tag"] == f"{LOCAL}_rr-{REMOTE}", got["tag"]
    assert got["window"] == "full overlap", got["window"]
    assert got["ignore_filters"] == "False", got["ignore_filters"]
    assert got["min_period"] == "0.005", got["min_period"]
    assert got["max_period"] == "5000.0", got["max_period"]
    assert got["periods_per_decade"] == "10.0", got["periods_per_decade"]
    assert got["notch_frequencies"] == "50, 150", got["notch_frequencies"]
    # fails if hz is asked for on a broadband site (it made a nonsense tipper)
    assert got["output_channels"] == "ex, ey", got["output_channels"]
    print(f"  defaults: {got['tag']}, archives {Path(got['local_archive']).name} / "
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
        others = {k: v for k, v in got.items() if k != key}
        unchanged = {k: v for k, v in base.items() if k != key}
        assert others == unchanged, f"{option} changed more than {key}: {others} vs {unchanged}"
        print(f"  {option} {value} -> {key} {got[key]}, nothing else moved")
    cleared = dry_run("--notch", "")
    assert cleared["notch_frequencies"] == "", cleared["notch_frequencies"]
    print("  --notch \"\" -> no notch frequencies at all")


def test_no_filters_uses_the_unfiltered_archives() -> None:
    got = dry_run("--no-filters")
    assert got["local_archive"].endswith(f"{LOCAL}_unfiltered.h5"), got["local_archive"]
    assert got["remote_archive"].endswith(f"{REMOTE}_unfiltered.h5"), got["remote_archive"]
    assert got["ignore_filters"] == "True", got["ignore_filters"]
    print(f"  --no-filters: {Path(got['local_archive']).name} / {Path(got['remote_archive']).name}")


def test_tag_suffix_and_window() -> None:
    got = dry_run("--tag", "try2")
    assert got["tag"] == f"{LOCAL}_rr-{REMOTE}_try2", got["tag"]
    start, end = "2021-06-29 12:55", "2021-06-29 14:55"
    got = dry_run(start, end, "--tag", "try2")
    assert got["window"] == f"{start} to {end} UTC", got["window"]
    assert got["tag"] == f"{LOCAL}_rr-{REMOTE}_w20210629T1255-20210629T1455_try2", got["tag"]
    assert got["start"] == start and got["end"] == end, (got["start"], got["end"])
    print(f"  --tag try2 with a window: tag {got['tag']}, window {got['window']}")


def test_tweaks_print_only_what_was_given() -> None:
    base = dry_run()
    assert base.get("tweaks") == "none", base.get("tweaks")
    assert not [k for k in base if k.startswith("tweak.")], base
    got = dry_run("--taper", "hann", "--overlap", "50", "--no-prewhiten", "--r0", "2.0")
    tweaks = {k: v for k, v in got.items() if k.startswith("tweak.")}
    assert tweaks == {"tweak.taper": "hann", "tweak.overlap_pct": "50.0",
                      "tweak.prewhiten": "False", "tweak.r0": "2.0"}, tweaks
    assert "tweaks" not in got, got["tweaks"]
    rest = {k: v for k, v in got.items() if not k.startswith("tweak.")}
    assert rest == {k: v for k, v in base.items() if k != "tweaks"}, "a tweak moved another line"
    print(f"  tweaks: plain run 'tweaks: none'; four flags -> {tweaks}, nothing else moved")


# the in-use estimator values, stated here from aurora 0.6.2's ConfigCreator
# output (not taken from bbmt.process), and what the four flags must make
IN_USE = {"type": "boxcar", "prewhitening_type": "first difference", "recoloring": True,
          "min_num_stft_windows": 0, "max_iterations": 10, "max_redescending_iterations": 2,
          "r0": 1.5, "u0": 2.8, "tolerance": 0.005}
TWEAKED = {**IN_USE, "type": "hann", "prewhitening_type": "", "recoloring": False, "r0": 2.0}


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
    import importlib.util

    import mth5.mth5
    import mth5.processing.run_summary as run_summary
    import numpy as np
    import xarray as xr
    from mth5.processing.spectre.prewhitening import apply_prewhitening

    sys.path.insert(0, str(REPO / "src"))
    from bbmt.bands import lemimt_band_scheme
    from bbmt.process import ESTIMATOR_DEFAULTS, apply_tweaks, build_config, kernel_dataset

    spec = importlib.util.spec_from_file_location("process_rr", SCRIPT)
    process_rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(process_rr)
    argv = [str(SURVEY), LOCAL, REMOTE, "--taper", "hann", "--overlap", "50", "--no-prewhiten",
            "--r0", "2.0"]
    res = process_rr.resolve(process_rr.build_parser().parse_args(argv))
    assert res["tweaks"] == {"taper": "hann", "overlap_pct": 50.0, "prewhiten": False, "r0": 2.0},         res["tweaks"]
    scheme = lemimt_band_scheme(res["survey"].sample_rate, **res["scheme_kwargs"])

    # read-only: RunSummary opens through initialize_mth5 (mode "a") and the
    # KernelDataset's metadata read through MTH5.open_mth5 (default mode "a")
    archives = [MTH5_DIR / f"{LOCAL}.h5", MTH5_DIR / f"{REMOTE}.h5"]
    mtimes = [p.stat().st_mtime_ns for p in archives]
    real_init, real_open = run_summary.initialize_mth5, mth5.mth5.MTH5.open_mth5
    run_summary.initialize_mth5 = lambda path, mode="r", **kw: real_init(path, mode="r", **kw)
    mth5.mth5.MTH5.open_mth5 = (
        lambda self, filename=None, mode="r", **kw: real_open(self, filename, mode="r", **kw))
    try:
        configs = {}
        for name, tweaks in (("in use", None), ("tweaked", res["tweaks"])):
            kd = kernel_dataset(res["local_archive"], LOCAL, res["remote_archive"], REMOTE)
            configs[name] = build_config(kd, scheme, tweaks, output_channels=res["output_channels"])
    finally:
        run_summary.initialize_mth5, mth5.mth5.MTH5.open_mth5 = real_init, real_open
    assert [p.stat().st_mtime_ns for p in archives] == mtimes, "a config build wrote to an archive"

    long_levels = 0
    for dec in configs["in use"].decimations:
        n, seconds = dec.stft.window.num_samples, dec.stft.window.num_samples / dec.decimation.sample_rate
        want = int(n * 0.75) if seconds > 600.0 else round(n * 0.25)
        long_levels += seconds > 600.0
        assert dec.stft.window.overlap == want, (dec.decimation.level, dec.stft.window.overlap, want)
        assert level_values(dec) == IN_USE, (dec.decimation.level, level_values(dec))
    assert long_levels >= 1, "no level has a window over 600 s: the boost is never exercised"
    assert ESTIMATOR_DEFAULTS == {"taper": "boxcar", "overlap_pct": 25.0, "prewhiten": True,
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
          f"in use {IN_USE['type']}, overlap 25 %/75 %, r0 {IN_USE['r0']}; tweaked hann, overlap "
          f"50 % on every level, prewhitening off, r0 2.0; dpss builds; archives' mtimes unchanged")


def test_dry_run_writes_nothing() -> None:
    before = sorted(p.name for p in MTH5_DIR.glob("*.h5")) if MTH5_DIR.exists() else []
    dry_run("--no-filters", "--tag", "never")
    after = sorted(p.name for p in MTH5_DIR.glob("*.h5")) if MTH5_DIR.exists() else []
    assert before == after, f"--dry-run changed the archives: {before} -> {after}"
    assert not any(n.endswith("_unfiltered.h5") for n in after), after
    print(f"  --dry-run wrote nothing: {MTH5_DIR.name}/ still holds {after}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  process_rr_cli_unit ({len(tests)} tests)")
