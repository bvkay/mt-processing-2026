# -*- coding: utf-8 -*-
"""
Remote-referenced processing of one local/remote pair

Ingests a local and a remote site, estimates the remote-referenced TF with
aurora, and overlays it on the legacy lemimt EDI when the survey maps one.

Each site's whole deployment is ingested once: one MTH5 per site holds all its
runs, and later runs against other partners reuse it. `start`/`end` (UTC, e.g.
"2018-06-22 21:40") are a processing window applied to the aurora kernel
dataset, leaving the archive whole; they keep a bad stretch out of the
estimate (a channel that failed part-way through, say). Without them aurora
works on the full time overlap. Long deployments are split into runs of at
most MAX_RUN_FILES files to bound memory; at 90 min per file that is about 2
days per run.

The band options override the survey's `processing:` block for this run
only, so two band layouts can be compared without editing the YAML.
`--notch` is a comma-separated list of Hz (`--notch ""` clears the
survey's). Each site's raw archive (`<site>.h5`, unfiltered) is ingested if
it is missing. The archive processed from is chosen by
`mt_workbench.ingest.processing_archive`: the filtered variant
(`<site>_f<hash>.h5`, built from the raw archive when it is missing or its
recorded hash does not match the current `filters.yaml`), or the raw archive
with `--no-filters`, which shows whether a filter was worth declaring.
A Phoenix archive built without the H polarity stage is
named in a warning (`mt_workbench.phoenix.warn_without_h_polarity`) and
processed as it is.
`--tag` adds a suffix to the output name so such runs keep separate files.
`--dry-run` prints everything the run resolved to (band kwargs, both sites'
raw and variant archive status, a raw archive that is missing marked so,
both sites' spans, window, product stem) and exits without writing a file or
building a variant. A site with no survey.yaml entry (a stacked remote
excepted) and a pair whose spans share no time exit 2, in the dry run as in
the real run, before anything is ingested or opened for writing.

Time masks (`<survey>/masks.yaml`, declared per site on the GUI's
Cross-powers tab or by scripts/cluster_masks.py and scripts/gate_masks.py)
are applied by role: the entries of the local site whose `scope` is `local`
or `both`, and the entries of the remote site whose `scope` is `both` or
`remote`, joined with `mt_workbench.masks.union_masks`. An entry of scope
`local`, the default, applies only when its site is the local, so a mask
of a site's electric channels keeps its windows in the pairs that use the
site as a remote, where its magnetics alone are used; an entry of scope
`remote` applies only when its site is the remote. A stacked remote
(`STK_...`) has no entry of its own; the remote is looked up by its name
(`mt_workbench.masks.remote_masks`), so its masks apply whether or not data_root
is mounted. `--mask-scope union` applies every entry of both sites,
whatever its scope, for comparison.

An entry's `channels` (every channel without the key) narrows it. Of the
remote, an entry naming neither hx nor hy is left out, since the remote
contributes its magnetics alone. Of the applied entries, one naming hx, hy
or every channel leaves out whole windows for every output row, and one
naming only output channels (ex, ey, hz) leaves out windows of those rows
alone: row r takes the whole-window entries and the entries naming r
(`row_runs`), aurora runs once per distinct set of entries, and the rows
are merged into one transfer function before the EDI, the figure, the
quadrant check and the sidecar (`merge_rows`): row r's transfer function,
its errors and row and column r of the residual covariance from row r's
run, the rest from the base run (the set with the fewest entries). With
one distinct set, the usual case, there is one run and no merge.

The sidecar records the rule (`mask_scope`), the counts applied from each
site (`mask_counts`: local, remote, remote_left_out, the remote's entries
its scope leaves out, remote_left_out_channels, the remote's entries
naming no magnetic channel, and local_left_out_channels, the local's
entries naming only output channels the run does not estimate) and the
runs (`channel_runs`: the rows each served, its entry count and which is
the base). `--no-masks` ignores the file for both sites. `--masks-file PATH`
reads both sites' entries from another file laid out as masks.yaml in place
of the survey's (a candidate selection, e.g. scripts/stretch_masks.py's,
tried without writing a masks.yaml of record); everything else is as for
masks.yaml, the sidecar records the path as `masks_file` (null without the
flag), and the flag with `--no-masks` or a missing file is refused.

A derived site (`<site>L`, written by scripts/decimate_site.py at its own
`sample_rate:`, 1 Hz) is processed from its archive as it is, against a
remote at the same rate: an observatory (scripts/fetch_observatory.py) or
another derived site. Its runs are its parent's, so MAX_RUN_FILES shaped
them at ingest. The band scheme and the quadrant window follow the local's
rate, and so does the shortest period, `rate_min_period` (4 s at 1 Hz),
unless --min-period is given. A remote at another rate is refused (exit 2)
with both rates named. A remote with no survey.yaml entry, such as a stack
of derived members (scripts/build_stack.py, STK_<site>Lu at 1 Hz), is at
the rate its archive's runs record (`archive_rate`), not the survey's. A
derived local without a reference EDI of its own
is compared with its parent's. The sidecar records the rates
(`sample_rates`) and the parents (`derived_from`).

A derived diagonal site (`<site>D`, written by scripts/diagonal_site.py at
its parent's rate) holds one electric line, ex along its `azimuth_ex:`
(the dipole between the two outer electrodes of a shared-centre layout),
and the parent's magnetics: its declared channels make the outputs ex and
hz (`output_channels`), aurora estimates them through
`mt_workbench.process._one_electric_line`, and the EDI carries that one
impedance row with its errors, the tipper, the ey row EMPTY and the ex
azimuth in EMEAS (from the archive's channel metadata). The phase-quadrant
check is not judged for it (`diagonal_azimuth`): the row of a line at
another azimuth has no fixed quadrant. Its comparison figure overlays the
parent's reference EDI, whose rows are the parent's N and E lines.

The estimator flags (--taper ... --tolerance) are advanced options: each
changes aurora's STFT or robust regression on every decimation level for
this run only (`mt_workbench.process.process_station(tweaks=...)`, whose docstring
gives the default in use for each). The flags given become tweaks; with none
the run uses the defaults, and the resolution prints "tweaks: none".

An aurora period whose band rests on fewer than `min_band_windows` STFT
windows is not written. A Z or T row with a zero or non-finite error at a
period is written as not estimated there (the EDI's EMPTY value, 1e32),
the other rows keeping theirs, and a period left with no row is not
written (`mt_workbench.process.process_station`, and again after the rows
of a masked run are merged, where a band one row's run did not keep stays
EMPTY in that row alone); each is logged as a warning with the periods.
The floor is `--min-band-windows N`, else survey.yaml's `processing:
min_band_windows`, else `mt_workbench.process.MIN_BAND_WINDOWS` (2: a band
of a single window is not written); 0 keeps every period. The resolution
prints it and the sidecar records it as `min_band_windows`, with the
periods the floor removed as `dropped_periods`: {"n", "periods_s" (sorted,
in s), "min_band_windows"}, n 0 and an empty list when none (for a masked
run of several aurora runs, the periods any run removed). MANTLE applies no
such floor: `--engine mantle` refuses the flag, and its sidecar records
`min_band_windows` and `dropped_periods` as null.

The band-layout flags are advanced options that keep every band's period
and change the FFT harmonics it spans (`mt_workbench.bands.build_band_scheme`).
`--window-samples N` sets the FFT window of every decimation level (128
samples unless the survey's `processing:` block gives `window:`), so each
band spans N/128 times as many harmonics; the overlap stays 25 % of the
window (75 % on levels whose window lasts over 600 s) unless the survey's
`processing:` block gives `overlap:` or `overlap_long:` in percent, which
`--overlap` and `--overlap-long` override for one run (the 75 % boost counts
overlapped windows as independent and prints errors about 1.8 times too
small on those levels, docs/workbench_issues.md 170: a survey that wants
honest errors there sets `overlap_long: 25`). `--min-bin N` sets
the lowest band edge of every decimated level to the first edge of the
layout at or above harmonic N (the layout's own is 6.4 at 1000 Hz: 10.16
for 10, 12.8 for 12); raised, it moves the bands at the foot of each level
to the top of the next. `--min-bin 0` is the layout's own, over a
`min_bin:` the survey's `processing:` block gives (the GUI's "layout's
own"); a negative N is refused. In the survey layout the two lowest bands of each
level span two harmonics each. The resolution prints `window_samples`,
`min_bin` and the resolved `lowest_harmonic`; the sidecar records the first
two in `band_scheme` (as `window` and `min_bin`) and the third as
`lowest_harmonic`.

`--engine mantle` estimates with MANTLE instead of aurora
(`mt_workbench.engine_mantle`): the same processing archives and window, read
through MANTLE's own MTH5 reader, its robust remote-reference cascade with
block-jackknife error bars, and the EDI pooled onto the same band scheme, so
the figure, the sidecar, the GUI's EDI list and the campaign's scores read
it as they read an aurora product. Two more files land beside it, MANTLE's
fine-grid EDI (`<stem>_fine.edi`) and its report JSON
(`<stem>.mantle_report.json`), and the sidecar gains `engine`,
`engine_version`, `engine_config`, `mantle_report` and `mantle_fine_edi`; a
sidecar without `engine` is an aurora run. The aurora estimator flags and
masks.yaml entries are refused with it (`--no-masks` runs without them).
`--mantle-whiten diff` first-differences every channel before the cascade.
MANTLE holds the whole window in memory and refuses one longer than
`--mantle-max-hours` (24 h by default); a limit above 24 h logs the peak
memory the window is expected to need, about 1.35 GB per hour of window at
1000 Hz with six channels. The sidecar records the limit as
`engine_config.options.max_hours`. `--mantle-window clip` chooses a window
that fits in place of refusing (`mt_workbench.mantle_window.choose_window`): inside
the window requested (the start and end given, else the pair's overlap) the
longest span both archives' runs cover without a gap
(`mt_workbench.engine_mantle.archive_spans`), its first `--mantle-max-hours` hours
when it is longer. The resolution prints it as `mantle.window_used` (a dry
run reads the runs of the archives it would process, metadata only, and
runs nothing), and the sidecar records it as `window` with `window_clipped`:
null, or {requested_hours, used_hours, reason} with reason "cap", "gap" or
"cap and gap". A pair whose runs share no covered span of an hour inside the
window is an error. `--mantle-window refuse`, the default, keeps the refusal
and adds neither the line nor the key; aurora refuses the option, since it
reads the window a piece at a time and needs no clip.

Outputs: <workspace>/mth5/<site>.h5, <workspace>/tf/<stem>.edi,
<workspace>/tf/<stem>.xml (EMTF XML, carrying aurora's residual and inverse
signal covariances), <workspace>/tf/<stem>.h5 (a standalone MTH5 file holding
the TF; `mt_workbench.products.write_products`),
<workspace>/tf/<stem>_vs_lemimt.png and <workspace>/tf/<stem>.json, where
<stem> is <local>_rr-<remote>_<YYYYMMDD-HHMM> (the local time this run
started, taken from the machine clock at the top of `main` and formatted
once) plus the --tag suffix when given. The stem uses the run's start rather
than the processing window, since two runs of the same pair over the same
window would otherwise overwrite each other's EDI. The window, and
everything else about the run (archives and their mtimes, the band scheme
and estimator tweaks used, both sites' declared filters, the full argv, the
phase-quadrant verdict and the package versions), is in the `.json` sidecar
next to the EDI. Its `versions.installed` says where each package of the
stack (aurora, mth5, mt_timeseries, mt_metadata, mt_io) was installed from
and fingerprints what is installed (`installed_origin`), since a fork and
the stock release carry the same version number. A short summary also goes into the EDI's INFO block
(`processing_parameters`). The sidecar's `edi`, `xml` and `h5` keys name the
three products, and `frame` records the frame metadata written with them.

The products stay in the sensor frame and are never rotated. Before they
are written, the local site's survey.yaml frame and declination are set on
the TF's station metadata, over the archive's
(`mt_workbench.products.apply_site_frame`): `layout_north` (magnetic, the
default, or geographic) gives `orientation.reference_frame` (geomagnetic
or geographic), and `declination`, `declination_model` and
`declination_epoch` (scripts/declination.py) are set when the site carries
them, so an archive ingested before the keys existed needs no rebuild; the
sidecar's `frame.declination_source` says "survey.yaml" or "archive". A
site with neither (the archive's 0.0 with no epoch is mt_metadata's
default) gets a WARNING, null declination keys in the sidecar and no
Declination element in the XML, as its EDI has no DECLINATION line. The
EDI's HEAD then carries DECLINATION lines, its INFO block's
`transfer_function.coordinate_system` equals the HEAD's COORDINATE_SYSTEM,
and for a geomagnetic frame with a declination its ZROT and TROT are the
declination at every period (the x-axis azimuth east of geographic north,
Geotools' convention; the data unrotated) and `mt_workbench.frame`,
`mt_workbench.rotation` and `mt_workbench.declination*` INFO lines state
it in words; the sidecar's `frame.zrot` records it. The three products
are written once, after the INFO lines are added.

The instruments. Where survey.yaml declares the AuScope instrument
registry DOIs of a site's instruments (`logger_pid`, `sensor_pid_hx`, ...,
`platform_pid`; `mt_workbench.survey.Survey.instrument_pids`), the sidecar
records them as `instrument_pids` (`local` and `remote`, each ``{site,
pids}``; a stacked remote ``{site, members: {site: pids}}``, its members
read from the stack archive's recorded provenance, `instrument_pids_of`),
the dry run prints `instrument_pid.local` and `instrument_pid.remote`, the
EDI's INFO block gets one line per instrument
(``mt_workbench.instrument_pid_local_logger=10.82388/25jrcc6q``,
`mt_workbench.products.pid_info_lines`) and the XML's Notes a sentence with
each DOI as an https://doi.org/ link (`mt_workbench.products.pid_sentence`).
With no key declared none of these is written.

Usage:
    python scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end]
        [--min-period S] [--max-period S] [--per-decade N] [--notch "50,150"]
        [--no-filters] [--no-masks | --masks] [--masks-file PATH] [--mask-origins LIST] [--mask-scope {role,union}]
        [--tag SUFFIX] [--dry-run]
        [--window-samples N] [--min-bin N]
        [--taper {boxcar,hamming,hann,dpss}] [--overlap PCT] [--overlap-long PCT] [--no-prewhiten]
        [--min-windows N] [--min-band-windows N] [--max-iterations N] [--redescending-iterations N]
        [--r0 X] [--u0 X] [--tolerance X]
        [--engine {aurora,mantle}] [--mantle-whiten {none,diff}] [--mantle-max-hours H]
        [--mantle-window {refuse,clip}]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import matplotlib
import numpy as np
import pandas as pd
import yaml
from loguru import logger

matplotlib.use("Agg")  # before mth5 and mt_io import pyplot: the figures are PNGs

from mt_workbench.bands import build_band_scheme, lowest_harmonic, site_min_period
from mt_workbench.compare import phase_quadrants, plot_comparison
from mt_workbench.ingest import default_archive_path, filters_hash, ingest_site, processing_archive, variant_path, variant_ready
from mt_workbench.masks import (
    FOUND_BY, OUTPUTS, SCOPE_RULES, _ordered, is_stack, load_masks, masks_for_role, masks_for_row, read_document,
    remote_channel_split, remote_masks, stored, union_masks,
)
from mt_workbench.phoenix import warn_without_h_polarity
from mt_workbench.process import (DROPPED_ATTR, ESTIMATOR_DEFAULTS, LONG_WINDOW_SECONDS, MIN_BAND_WINDOWS,  # noqa: E402
                                  OVERLAP_ATTR, TAPERS, process_station)
from mt_workbench.products import (apply_instruments, apply_site_frame, drop_bad_errors, frame_record,
                                   instrument_info_lines, match_coordinate_system, pid_info_lines, product_names,
                                   set_zrot_rule, write_products, zrot_rule_of)
from mt_workbench.survey import OBSERVATORY, Survey, pid_text

MAX_RUN_FILES = 34  # 34 x 90 min = 51 h per run
ENGINES = ("aurora", "mantle")
MANTLE_WHITEN = ("none", "diff")  # mt_workbench.engine_mantle.WHITEN, spelt here so the parser builds without MANTLE
MANTLE_MAX_HOURS = 24.0  # mt_workbench.engine_mantle.MAX_HOURS, likewise
MANTLE_WINDOW = ("refuse", "clip")
# the band-scheme keys this CLI can override; anything else in the survey's
# `processing:` block (factor, notch_fraction) is passed through
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies", "window", "min_bin")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of process_rr.py."""
    p = argparse.ArgumentParser(
        prog="process_rr.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("local")
    p.add_argument("remote")
    p.add_argument("start", nargs="?", default=None, help='UTC, e.g. "2021-06-29 12:55"')
    p.add_argument("end", nargs="?", default=None, help="UTC")
    p.add_argument("--min-period", type=float, default=None, help="shortest period (s)")
    p.add_argument("--max-period", type=float, default=None, help="longest period (s)")
    p.add_argument("--per-decade", type=float, default=None, help="bands per decade")
    p.add_argument("--notch", default=None, help='comma-separated Hz, e.g. "50,100" ("" for none)')
    p.add_argument("--no-filters", action="store_true",
                   help="process from the raw archive, not the filtered variant")
    p.add_argument("--no-masks", dest="masks", action="store_false",
                   help="ignore masks.yaml for both sites (a campaign run: every remote and option on the same data)")
    p.add_argument("--masks", dest="masks", action="store_true", default=True,
                   help="apply masks.yaml (the default; after --no-masks, the later flag wins)")
    p.add_argument("--mask-origins", default=None, metavar="LIST",
                   help="apply only the masks.yaml entries found by these origins, a comma list of "
                        + ", ".join(FOUND_BY) + " (default: every entry)")
    p.add_argument("--masks-file", default=None, metavar="PATH",
                   help="read both sites' entries from this file, laid out as masks.yaml, in place of the survey's "
                        "masks.yaml (a candidate file; the survey's files are left unchanged)")
    p.add_argument("--mask-scope", choices=SCOPE_RULES, default="role",
                   help="role (the default): the local's masks.yaml entries of scope local or both and the "
                        "remote's of scope both or remote; union: every entry of both sites, whatever its scope")
    p.add_argument("--tag", default=None, help="suffix appended to the output stem")
    p.add_argument("--dry-run", action="store_true",
                   help="print what this run resolved to and exit, opening nothing")
    lay = p.add_argument_group("advanced: the band layout (every band keeps its period)")
    lay.add_argument("--window-samples", type=int, default=None, metavar="N",
                     help="FFT window in samples on every decimation level (in use: 128, or the survey's window:); "
                          "each band spans N/128 times the harmonics")
    lay.add_argument("--min-bin", type=float, default=None, metavar="N",
                     help="lowest band edge of every decimated level, in FFT harmonics: the first edge of the layout "
                          "at or above N; 0 is the layout's own, over the survey's min_bin: (in use: the survey's "
                          "min_bin:, else the layout's own, 6.4 at 1000 Hz)")
    adv = p.add_argument_group("advanced: the aurora estimator, on every decimation level")
    adv.add_argument("--taper", choices=TAPERS, default=None, help="STFT window (in use: hann; aurora's own is boxcar)")
    adv.add_argument("--overlap", type=float, default=None, metavar="PCT",
                     help="STFT overlap %% on every level (in use: the survey's processing: overlap:, else 25, "
                          "75 on windows over 600 s)")
    adv.add_argument("--overlap-long", type=float, default=None, metavar="PCT",
                     help="STFT overlap %% on the long levels only (windows over 600 s; in use: the survey's "
                          "processing: overlap_long:, else 75), the other levels untouched")
    adv.add_argument("--no-prewhiten", action="store_true",
                     help="skip the first-difference pre-whitening (and its recolouring)")
    adv.add_argument("--min-windows", type=int, default=None, metavar="N",
                     help="fewest STFT windows a level needs (in use: 0)")
    adv.add_argument("--min-band-windows", type=int, default=None, metavar="N",
                     help="aurora: a period whose band rests on fewer STFT windows is not written (in use: survey.yaml "
                          f"processing: min_band_windows, else {MIN_BAND_WINDOWS}; 0 keeps every period)")
    adv.add_argument("--max-iterations", type=int, default=None, metavar="N",
                     help="robust regression iterations (in use: 10)")
    adv.add_argument("--redescending-iterations", type=int, default=None, metavar="N",
                     help="redescending iterations (in use: 2)")
    adv.add_argument("--r0", type=float, default=None, metavar="X", help="Huber threshold (in use: 1.5)")
    adv.add_argument("--u0", type=float, default=None, metavar="X",
                     help="redescending threshold (in use: 2.8)")
    adv.add_argument("--tolerance", type=float, default=None, metavar="X",
                     help="regression convergence tolerance (in use: 0.005)")
    eng = p.add_argument_group("the engine")
    eng.add_argument("--engine", choices=ENGINES, default="aurora",
                     help="transfer-function engine: aurora (default) or mantle (MANTLE's robust remote-reference "
                          "cascade on the same archives and window; the aurora flags above are refused with it)")
    eng.add_argument("--mantle-whiten", choices=MANTLE_WHITEN, default="none", metavar="KIND",
                     help="mantle only: 'diff' first-differences every channel before the cascade (cancels in Z, "
                          "removes red-spectrum leakage); in use: none")
    eng.add_argument("--mantle-max-hours", type=float, default=MANTLE_MAX_HOURS, metavar="H",
                     help="mantle only: the longest window accepted, in hours (in use: 24); MANTLE holds the "
                          "window in memory, about 1.35 GB per hour at 1000 Hz, and a limit above 24 logs the "
                          "window's expected peak")
    eng.add_argument("--mantle-window", choices=MANTLE_WINDOW, default=None, metavar="MODE",
                     help="mantle only: refuse (in use) a window longer than --mantle-max-hours or not covered by "
                          "both archives' runs; clip takes the longest span both cover inside the window, its "
                          "first --mantle-max-hours hours when longer")
    return p


def tweaks_from(args, survey=None) -> dict:
    """Collect the estimator flags given on the command line, and the survey's overlaps under them.

    Args:
        args (argparse.Namespace): Parsed arguments.
        survey (Survey, optional): When given, its `processing:` block's
            `overlap:` and `overlap_long:` (`Survey.overlap_pct`,
            `Survey.overlap_pct_long`) stand in for `--overlap` and
            `--overlap-long` wherever those were not given.

    Returns:
        dict: The settings as `process_station(tweaks=...)` keys; {} when
        none were given and the survey sets none.
    """
    given = {
        "taper": args.taper,
        "overlap_pct": args.overlap,
        "overlap_pct_long": args.overlap_long,
        "prewhiten": False if args.no_prewhiten else None,
        "min_windows": args.min_windows,
        "max_iterations": args.max_iterations,
        "redescending_iterations": args.redescending_iterations,
        "r0": args.r0,
        "u0": args.u0,
        "tolerance": args.tolerance,
    }
    if survey is not None:
        if given["overlap_pct"] is None:
            given["overlap_pct"] = survey.overlap_pct
        if given["overlap_pct_long"] is None:
            given["overlap_pct_long"] = survey.overlap_pct_long
    return {key: value for key, value in given.items() if value is not None}


def parse_notch(text: str) -> tuple:
    """Parse a --notch value: '50, 150' -> (50.0, 150.0); '' -> () (no notches)."""
    return tuple(float(part) for part in str(text).split(",") if part.strip())


def reference_edi(survey_yaml: Path, site: str):
    """Return the reference EDI mapped to a site in reference_edis.yaml, or None."""
    ref_yaml = Path(survey_yaml).parent / "reference_edis.yaml"
    if not ref_yaml.exists():
        return None
    mapping = yaml.safe_load(ref_yaml.read_text(encoding="utf-8")) or {}
    return (mapping.get(site) or {}).get("edi")


def clean_tag(tag) -> str:
    """Clean a --tag value for use in a file name.

    Outer whitespace and leading dashes/underscores are dropped and inner
    whitespace becomes '-'. A tag such as "-mask_test" is passed as
    --tag=-mask_test, since argparse reads it as an option otherwise, and
    loses its leading dash here.

    Args:
        tag (str | None): The tag as given.

    Returns:
        str: The cleaned tag, "" for None.

    Raises:
        ValueError: When the tag holds a path separator.
    """
    text = "-".join(str(tag or "").split()).lstrip("-_").rstrip("_")
    if any(c in text for c in "/\:"):
        raise ValueError(f"tag {tag!r} must not hold a path separator")
    return text


def run_stem(local: str, remote: str, started, suffix=None) -> str:
    """Build the product stem <local>_rr-<remote>_<YYYYMMDD-HHMM>[_<suffix>].

    The stamp is `started` (local time, the machine clock at the top of
    `main`) rather than the processing window, since two runs of the same
    pair over the same window would otherwise overwrite each other's EDI.
    The window is recorded in the `.json` sidecar next to the EDI.

    Args:
        local (str): Local site.
        remote (str): Remote site.
        started: Start time of the run.
        suffix (str | None): Tag, cleaned with `clean_tag`.

    Returns:
        str: The stem.
    """
    stem = f"{local}_rr-{remote}_{pd.Timestamp(started).strftime('%Y%m%d-%H%M')}"
    suffix = clean_tag(suffix)
    if suffix:
        stem += f"_{suffix}"
    return stem


def recorded_site_folders(survey: Survey) -> dict[str, Path]:
    """Map every recorded site of a survey to its raw folder, found under `data_root` or not.

    The folders `Survey.site_dirs` finds, then every declared site that is
    not derived (`derived_from`), a burst site (`bursts_of`) or an
    observatory (`instrument: intermagnet`) at ``data_root/<site>``,
    whether that folder exists or not (workbench issue 32). A declared
    recorded site is never a virtual remote: its raw folder may be on a
    drive that is not plugged in, or `data_root` may name a folder the raw
    data has moved from, and its archive is still read through
    `ingest_site` (which keeps an existing archive), `processing_archive`
    (its filtered variant) and the filter records (`archive_status`,
    `_declared_filters`). The run then takes the same archives and filters
    and writes the same records whichever root holds the raw folders. A
    stack, an observatory, a derived site and a burst site have no raw
    folder of their own and are left out, as before.

    Args:
        survey (Survey): The survey.

    Returns:
        dict: Site name to raw folder Path.
    """
    try:
        folders = survey.site_dirs()
    except OSError:  # data_root on a drive that is not plugged in
        folders = {}
    for name in survey.site_names():
        entry = (survey.config.get("sites") or {}).get(name) or {}
        product = survey.parent_of(name) or survey.bursts_parent(name) or entry.get("instrument") == OBSERVATORY
        if name in folders or product:
            continue
        folders[name] = survey.data_root / name
    return folders


def archive_status(survey: Survey, site: str, raw_sites: dict, use_filters: bool) -> dict | None:
    """Report a site's raw and variant archive status without building anything.

    Args:
        survey (Survey): The survey.
        site (str): Site name.
        raw_sites (dict): Site name to raw-data folder (`recorded_site_folders`).
        use_filters (bool): False with --no-filters.

    Returns:
        dict | None: {"raw", "raw_missing", "variant", "variant_state"}.
        `raw_missing` is None when the raw archive exists, else what the
        run does about it ("missing: ingested from <raw folder> first", or
        "missing, and no raw folder at <folder> to ingest from" when the
        folder is not there either, where the run stops in `ingest_site`).
        `variant` is None
        and `variant_state` "no filters used" with `use_filters=False`, or
        "none declared" when the site's `filters.yaml` entry is empty;
        otherwise `variant_path` and "ready" (the raw archive exists and
        `variant_ready`) or "to build (<hash>)". A derived site gets its
        archive, `variant` None and "derived_from" its parent. None for
        another site not in `raw_sites`, such as a stacked remote without a
        raw archive, which `resolve` handles separately.
    """
    parent = survey.parent_of(site)
    if parent:
        return {"raw": default_archive_path(survey, site), "raw_missing": None, "variant": None,
                "derived_from": parent,
                "variant_state": f"none (derived from {parent}: its archive is used as it is)"}
    if site not in raw_sites:
        return None
    raw = default_archive_path(survey, site)
    folder = Path(raw_sites[site])
    missing = (None if raw.exists() else f"missing: ingested from {folder} first" if folder.is_dir()
               else f"missing, and no raw folder at {folder} to ingest from")
    declared = survey.site(site).filters or []
    if not use_filters:
        return {"raw": raw, "raw_missing": missing, "variant": None, "variant_state": "no filters used (--no-filters)"}
    if not declared:
        return {"raw": raw, "raw_missing": missing, "variant": None, "variant_state": "none declared"}
    vpath = variant_path(survey, site)
    ready = raw.exists() and variant_ready(survey, site)
    state = "ready" if ready else f"to build ({filters_hash(declared)})"
    return {"raw": raw, "raw_missing": missing, "variant": vpath, "variant_state": state}


def archive_span(path: Path, site: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return the first and last instant of a site's runs in an archive, read with h5py (mode "r").

    Args:
        path (Path): The archive.
        site (str): Station name in it.

    Returns:
        tuple | None: (start, end), UTC, from the runs' ``time_period``
        attributes; None when the file is missing or holds no run of `site`.
    """
    import h5py

    if not Path(path).exists():
        return None
    starts, ends = [], []
    with h5py.File(path, "r") as f:
        for survey_group in f.get("Experiment/Surveys", {}).values():
            station = survey_group.get(f"Stations/{site}")
            if station is None:
                continue
            for run in station.values():
                if isinstance(run, h5py.Group) and "time_period.start" in run.attrs:
                    starts.append(_utc(run.attrs["time_period.start"]))
                    ends.append(_utc(run.attrs["time_period.end"]))
    if not starts:
        return None
    return min(starts), max(ends)


def archive_rate(path: Path, site: str) -> float | None:
    """Return the sample rate of a site's runs in an archive, read with h5py (mode "r").

    Args:
        path (Path): The archive.
        site (str): Station name in it.

    Returns:
        float | None: The runs' ``sample_rate`` attribute; None when the file
        is missing or holds no run of `site` that records one.

    Raises:
        RateMismatch: When the site's runs record different rates.
    """
    import h5py

    if not Path(path).exists():
        return None
    rates = set()
    with h5py.File(path, "r") as f:
        for survey_group in f.get("Experiment/Surveys", {}).values():
            station = survey_group.get(f"Stations/{site}")
            if station is None:
                continue
            for run in station.values():
                kind = run.attrs.get("mth5_type", b"") if isinstance(run, h5py.Group) else b""
                kind = kind.decode() if isinstance(kind, bytes) else str(kind)
                if kind.lower() == "run" and "sample_rate" in run.attrs:
                    rates.add(float(run.attrs["sample_rate"]))
    if len(rates) > 1:
        raise RateMismatch(f"{site}: {Path(path).name} holds runs at {', '.join(f'{r:g}' for r in sorted(rates))} "
                           f"Hz; aurora pairs archives of one rate")
    return rates.pop() if rates else None


def site_span(survey: Survey, site: str, archive: Path) -> tuple[pd.Timestamp, pd.Timestamp, str] | None:
    """Return a site's recorded span: survey.yaml's start and end, else its archive's runs.

    Args:
        survey (Survey): The survey.
        site (str): Site name.
        archive (Path): The site's raw archive (or a stacked remote's).

    Returns:
        tuple | None: (start, end, where it was read: "survey.yaml" or the
        archive's name); None when neither gives one.
    """
    if site in survey.site_names():
        cfg = survey.site(site)
        if cfg.start and cfg.end:
            return _utc(cfg.start), _utc(cfg.end), "survey.yaml"
    span = archive_span(archive, site)
    return (*span, Path(archive).name) if span else None


def _utc(value) -> pd.Timestamp:
    """Read an instant as a UTC timestamp; a value without an offset is taken as UTC."""
    t = pd.Timestamp(value.decode() if isinstance(value, bytes) else str(value))
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _utc_text(t: pd.Timestamp) -> str:
    """Format a UTC instant as 2023-09-22T12:21:22Z."""
    return _utc(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_pair(survey: Survey, local: str, remote: str, local_h5: Path, remote_h5: Path, virtual: bool,
               raw_sites: dict) -> dict:
    """Refuse a pair that cannot run, before anything is opened for writing.

    A site without a survey.yaml entry is refused: its dipole lengths and
    azimuths would be the survey defaults, and without a raw folder the
    ingest fails. A remote whose archive is in the workspace (`virtual`), or
    a stacked remote named STK_..., built or not, has no entry and passes.
    Then the two sites' spans (`site_span`) are compared, and a pair that
    shares no time is refused with both spans.

    Args:
        survey (Survey): The survey.
        local (str): Local site.
        remote (str): Remote site.
        local_h5 (Path): The local's raw archive.
        remote_h5 (Path): The remote's raw archive, or the stacked remote's.
        virtual (bool): The remote is a stacked, observatory or derived archive.
        raw_sites (dict): Site name to raw folder.

    Returns:
        dict: {"local": span or None, "remote": span or None}, each span
        (start, end, source) as `site_span` gives it.

    Raises:
        PairRefused: When a site has no entry, or the spans do not overlap.
    """
    names = survey.site_names()
    for site, path in ((local, local_h5), (remote, remote_h5)):
        if site in names or (site == remote and (virtual or is_stack(site))):
            continue
        folder = (f"a raw folder at {raw_sites[site]}" if site in raw_sites
                  else f"no raw folder under {survey.data_root}")
        held = f"an archive at {path}" if Path(path).exists() else f"no archive at {path}"
        raise PairRefused(f"{site} has no entry in survey.yaml ({folder}, {held}): check the name, or add the site "
                          f"(scripts/new_survey.py or the GUI's Metadata tab) so its dipoles are declared")
    spans = {"local": site_span(survey, local, local_h5), "remote": site_span(survey, remote, remote_h5)}
    a, b = spans["local"], spans["remote"]
    if a and b and (a[1] <= b[0] or b[1] <= a[0]):
        raise PairRefused(f"{local} ({_utc_text(a[0])} to {_utc_text(a[1])}, {a[2]}) and {remote} "
                          f"({_utc_text(b[0])} to {_utc_text(b[1])}, {b[2]}) share no time: choose a remote "
                          f"recording at the same time")
    return spans


def mask_origins(text: str | None) -> set[str] | None:
    """Return the set of mask origins named in `--mask-origins`, or None for every origin.

    Args:
        text (str | None): The comma list given on the command line.

    Returns:
        set[str] | None: The origins, each one of `mt_workbench.masks.FOUND_BY`.

    Raises:
        SystemExit: If a name is not a known origin or the list is empty.
    """
    if text is None:
        return None
    names = {s.strip() for s in text.split(",") if s.strip()}
    unknown = sorted(names - set(FOUND_BY))
    if unknown or not names:
        raise SystemExit(f"--mask-origins takes a comma list of {', '.join(FOUND_BY)}; given {text!r}")
    return names


def file_masks(path, site: str) -> list[dict]:
    """Return one site's entries of a file laid out as masks.yaml (`--masks-file`), normalised, earliest first.

    The same reading `mt_workbench.masks.load_masks` gives a survey's
    masks.yaml (`read_document`, then `_ordered`), from another path; a
    stacked remote (`STK_...`) has none, as with `remote_masks`.
    """
    if is_stack(site):
        return []
    return _ordered(read_document(Path(path)).get(site) or [])


def resolve(args, started) -> dict:
    """Resolve everything the run needs before any file is opened.

    The band kwargs are the survey's `processing:` block with the command
    line's overrides applied, filled out from the defaults of
    `build_band_scheme` so `--dry-run` prints a number for each. `started`
    is the local wall-clock instant `main` began
    (`dt.datetime.now().astimezone()`), passed in so the product stem and the
    sidecar agree on the start time.

    `raw_sites` is `recorded_site_folders`: every raw folder found, and
    every declared recorded site at ``data_root/<site>`` whether its
    folder is there or not. `virtual_remote` is True for a remote with
    no raw folder of its own and an archive in the workspace: a stack, an
    observatory, a derived or burst site, an undeclared archive. A
    declared recorded site is never virtual (workbench issue 32), so its
    filters apply and are recorded whichever root holds the raw folders.

    `local_archive`/`remote_archive` are each site's raw archive path
    (`default_archive_path`), so `--dry-run` builds nothing;
    `local_status`/`remote_status` (`archive_status`) say whether a filtered
    variant is ready, needs building, or is not used. After the `--dry-run`
    return, `main` resolves the archive processed from
    (`mt_workbench.ingest.processing_archive`, which builds a missing variant) and
    overwrites these two entries before the sidecar is written.

    `masks_local`/`masks_remote` are the `masks.yaml` entries applied from
    each site (`masks_for_role` under the rule `mask_scope`: the local's
    entries of scope local or both, the remote's of scope both or remote,
    or all of them under `--mask-scope union`; `remote_masks` gives [] for a
    stack named `STK_...`), each narrowed to `--mask-origins` when given;
    of the remote's, those naming neither hx nor hy are left out
    (`mt_workbench.masks.remote_channel_split`). `masks` is their union in start
    order, and `channel_runs` (`row_runs`) groups it by output row: one
    entry per aurora run, its rows, its masks as passed to
    `process_station`, and whether it is the base run. `mask_counts` holds
    the number applied from the local and from the remote,
    `remote_left_out` the remote's entries its scope leaves out,
    `remote_left_out_channels` those of the remote its channels leave out,
    and `local_left_out_channels` the local's entries that name no row the
    run estimates. With `--no-masks` all three lists are [], every count 0,
    one run with no masks, and `masks_ignored` True.

    `sample_rate` and `remote_sample_rate` are `Survey.sample_rate_of` of
    the two sites, except for a remote with no survey.yaml entry whose
    archive is in the workspace (a stack): its archive's run rate
    (`archive_rate`), since survey.yaml gives an undeclared name the
    survey's rate and a stack of derived members is at theirs; the band
    scheme and the quadrant window use `sample_rate`. A local at its own rate starts at
    `mt_workbench.bands.site_min_period` unless --min-period is given: a
    derived site at the larger of the survey's and `rate_min_period`, a
    faster site (a burst site, a 1000 Hz site in a 150 Hz survey) at the
    shortest period of the survey's layout at or above `rate_min_period`.
    `lowest_harmonic` is
    the lowest band edge of the decimated levels in FFT harmonics
    (`mt_workbench.bands.lowest_harmonic` of the band kwargs at `sample_rate`).

    Args:
        args (argparse.Namespace): Parsed arguments.
        started (datetime.datetime): Start of the run.

    `check_pair` refuses a site without a survey.yaml entry (a stacked
    remote excepted) and a pair whose spans (survey.yaml start and end,
    else the archive's runs) share no time; `spans` holds both spans, which
    `print_resolution` prints as `local_span` and `remote_span`.

    Returns:
        dict: The resolution, printed by `print_resolution`.

    Raises:
        RateMismatch: When the two sites' sample rates differ.
        PairRefused: When a site has no survey.yaml entry or the two sites
            share no time (`check_pair`).
    """
    survey = Survey.from_yaml(args.survey_yaml)
    scheme_kwargs = dict(survey.processing)
    for key, value in (
        ("min_period", args.min_period),
        ("max_period", args.max_period),
        ("periods_per_decade", args.per_decade),
        ("notch_frequencies", None if args.notch is None else parse_notch(args.notch)),
        ("window", getattr(args, "window_samples", None)),
        ("min_bin", getattr(args, "min_bin", None)),
    ):
        if value is not None:
            scheme_kwargs[key] = value
    min_bin = getattr(args, "min_bin", None)
    if min_bin is not None and min_bin < 0:
        raise SystemExit(f"--min-bin takes 0 (the layout's own) or a harmonic above 0; given {min_bin:g}")
    if min_bin == 0:  # the layout's own, over the survey's min_bin:
        scheme_kwargs["min_bin"] = None
    defaults = {n: p.default for n, p in inspect.signature(build_band_scheme).parameters.items()}
    for key in BAND_KEYS:
        scheme_kwargs.setdefault(key, defaults[key])
    min_band_windows = next(v for v in (getattr(args, "min_band_windows", None), survey.min_band_windows,
                                        MIN_BAND_WINDOWS) if v is not None)
    if min_band_windows < 0:
        raise SystemExit(f"--min-band-windows takes 0 or more windows; given {min_band_windows}")
    # the local's own rate (a derived <site>L at 1 Hz) or the survey's; the
    # remote's must match, since aurora pairs archives of one rate
    local_rate = survey.sample_rate_of(args.local)
    remote_rate = survey.sample_rate_of(args.remote)
    if args.remote not in survey.site_names():
        # a stack has no entry, so survey.yaml gives it the survey's rate; its archive records its own
        # (a stack of derived <site>L members is at 1 Hz in a 10 Hz survey)
        recorded = archive_rate(survey.workspace / "mth5" / f"{args.remote}.h5", args.remote)
        remote_rate = remote_rate if recorded is None else recorded
    if not math.isclose(local_rate, remote_rate, rel_tol=1e-9):
        hint = (f": decimate the local first (scripts/decimate_site.py {args.survey_yaml} {args.local}) and "
                f"process {args.local}L against {args.remote}" if remote_rate < local_rate else "")
        raise RateMismatch(f"{args.local} is at {local_rate:g} Hz and {args.remote} at {remote_rate:g} Hz; aurora "
                           f"needs one sample rate for both{hint}")
    if args.min_period is None and local_rate != survey.sample_rate:
        scheme_kwargs["min_period"] = site_min_period(local_rate, survey.sample_rate, scheme_kwargs["min_period"],
                                                      scheme_kwargs["periods_per_decade"],
                                                      scheme_kwargs.get("factor", 4))

    # every declared recorded site, its raw folder found or not (`recorded_site_folders`)
    raw_sites = recorded_site_folders(survey)
    use_filters = not args.no_filters
    local_h5 = default_archive_path(survey, args.local)
    # a stacked synthetic remote (scripts/build_stack.py), an observatory
    # (scripts/fetch_observatory.py), a derived site (scripts/decimate_site.py)
    # and a burst site have no raw folder of their own: the archive is used as
    # it is, with or without filters, since it is a product rather than a
    # `processing_archive` variant. A declared recorded site is in `raw_sites`
    # whether its folder is mounted or not, so it is never virtual
    remote_parent = survey.parent_of(args.remote)
    stacked = survey.workspace / "mth5" / f"{args.remote}.h5"
    virtual = bool(remote_parent) or (args.remote not in raw_sites and stacked.exists())
    remote_h5 = stacked if virtual else default_archive_path(survey, args.remote)
    # a site without an entry, or two sites that share no time, end here, so the dry run says so too
    spans = check_pair(survey, args.local, args.remote, local_h5, remote_h5, virtual, raw_sites)
    ignore_masks = not args.masks
    scope_rule = getattr(args, "mask_scope", "role")
    # --masks-file: a candidate file read in place of the survey's masks.yaml, for both sites
    masks_file = getattr(args, "masks_file", None)
    if masks_file is not None:
        if ignore_masks:
            raise SystemExit("--masks-file names masks to apply and --no-masks ignores masks: give one of the two")
        if not Path(masks_file).is_file():
            raise SystemExit(f"--masks-file {masks_file}: no such file")
        masks_local = masks_for_role(file_masks(masks_file, args.local), "local", scope_rule)
        declared_remote = masks_for_role(file_masks(masks_file, args.remote), "remote", "union")
    else:
        masks_local = [] if ignore_masks else masks_for_role(load_masks(survey, args.local), "local", scope_rule)
        # by name (`remote_masks`), not by `virtual`: an undeclared archive-only
        # remote (not named STK_...) is virtual and keeps its masks;
        # every entry is read once, and the scope rule picks the ones applied
        declared_remote = [] if ignore_masks else remote_masks(survey, args.remote, rule="union", channels=False)
    origins = mask_origins(getattr(args, "mask_origins", None))
    if origins is not None:
        masks_local = [m for m in masks_local if m["found_by"] in origins]
        declared_remote = [m for m in declared_remote if m["found_by"] in origins]
    in_scope_remote = masks_for_role(declared_remote, "remote", scope_rule)
    # the remote contributes hx and hy alone: an entry naming neither leaves out nothing there
    masks_remote, channel_left_out = remote_channel_split(in_scope_remote)
    masks = union_masks(masks_local, masks_remote)
    rows = output_channels(survey, args.local) or list(OUTPUTS)
    runs, row_left_out = row_runs(masks, rows)
    flag_tweaks = tweaks_from(args)  # the command line alone, for the MANTLE check
    tweaks = tweaks_from(args, survey)  # with the survey's overlap: / overlap_long: under the flags
    engine = getattr(args, "engine", "aurora")
    if engine == "mantle":
        # MANTLE has its own estimator (DPSS multitaper, bounded-influence solve, block jackknife):
        # aurora's STFT and regression flags have no counterpart there, and masks act inside
        # aurora's kernel dataset and regression, so both are refused rather than silently dropped
        if flag_tweaks:
            raise SystemExit(f"--engine mantle takes none of the aurora estimator flags (given: {sorted(flag_tweaks)})")
        tweaks = {}
        if getattr(args, "min_band_windows", None) is not None:
            raise SystemExit(f"--min-band-windows {args.min_band_windows} is an aurora option: MANTLE applies no "
                             "floor on STFT windows per band")
        if masks_local or masks_remote:
            raise SystemExit(f"--engine mantle applies no masks.yaml entries yet ({args.local} {len(masks_local)}, "
                             f"{args.remote} {len(masks_remote)} to apply): run it with --no-masks")
    max_hours = float(getattr(args, "mantle_max_hours", MANTLE_MAX_HOURS))
    if not max_hours > 0.0:
        raise SystemExit(f"--mantle-max-hours takes a positive number of hours; given {max_hours:g}")
    mantle_window = getattr(args, "mantle_window", None)
    if mantle_window is not None and engine != "mantle":
        raise SystemExit(f"--mantle-window {mantle_window} is a MANTLE option (--engine mantle): aurora reads the "
                         "window a piece at a time and needs no clip")

    return {
        "survey": survey,
        "survey_yaml": str(Path(args.survey_yaml)),
        "local": args.local,
        "remote": args.remote,
        "raw_sites": raw_sites,
        "virtual_remote": virtual,
        "local_archive": local_h5,
        "remote_archive": remote_h5,
        "local_status": archive_status(survey, args.local, raw_sites, use_filters),
        "remote_status": (archive_status(survey, args.remote, raw_sites, use_filters)
                          if remote_parent or not virtual else None),
        "local_parent": survey.parent_of(args.local),
        "remote_parent": remote_parent,
        "sample_rate": local_rate,
        "remote_sample_rate": remote_rate,
        "ignore_filters": not use_filters,
        "start": args.start,
        "end": args.end,
        "window": (f"{args.start or 'start'} to {args.end or 'end'} UTC"
                   if (args.start or args.end) else "full overlap"),
        "spans": spans,
        "started": started,
        "tag": args.tag,
        "stem": run_stem(args.local, args.remote, started, args.tag),
        "scheme_kwargs": scheme_kwargs,
        "lowest_harmonic": lowest_harmonic(local_rate, **scheme_kwargs),
        # aurora: the fewest STFT windows a band needs for its period to be written;
        # None under MANTLE, which applies no such floor (the sidecar records null)
        "min_band_windows": None if engine == "mantle" else int(min_band_windows),
        # aurora estimates a TF row for every output channel it is asked for;
        # hz on a broadband site (no sensor, an open input) gives a meaningless
        # tipper, so the channels the survey declares are requested. A site
        # without a `channels:` declaration keeps aurora's default.
        "output_channels": output_channels(survey, args.local),
        # the advanced estimator flags given on the command line
        "tweaks": tweaks,
        "masks_local": masks_local,
        "masks_remote": masks_remote,
        "masks": masks,
        "channel_runs": runs,
        "masks_ignored": ignore_masks,
        "masks_file": str(masks_file) if masks_file is not None else None,
        "mask_origins": sorted(origins) if origins is not None else None,
        "mask_scope": scope_rule,
        "mask_counts": {"local": len(masks_local), "remote": len(masks_remote),
                        "remote_left_out": len(declared_remote) - len(in_scope_remote),
                        "remote_left_out_channels": len(channel_left_out),
                        "local_left_out_channels": len(row_left_out)},
        "engine": engine,
        "mantle_whiten": getattr(args, "mantle_whiten", "none"),
        "mantle_max_hours": max_hours,
        # refuse or clip with MANTLE, None with aurora; `window_choice` is set by
        # `choose_mantle_window` once the archives are known
        "mantle_window": (mantle_window or "refuse") if engine == "mantle" else None,
        "window_choice": None,
    }


def dry_run_archives(res: dict) -> tuple[Path, Path]:
    """Return the archives a run would process from, as far as a dry run can tell without building one.

    The filtered variant when `archive_status` says it is ready, else the
    raw archive (a variant to build has the raw archive's runs); a virtual
    remote's archive as it is.
    """
    def pick(status, path):
        if status and status.get("variant") and status.get("variant_state") == "ready":
            return Path(status["variant"])
        return Path(path)

    remote = Path(res["remote_archive"]) if res["virtual_remote"] else pick(res["remote_status"], res["remote_archive"])
    return pick(res["local_status"], res["local_archive"]), remote


def choose_mantle_window(res: dict, local_h5, remote_h5, start, end):
    """Choose the window of a `--mantle-window clip` run from the two archives' runs and keep it in `res`.

    Sets `res["window_choice"]` and `res["window"]`, the window's text in
    the figure's title.

    Args:
        res (dict): Output of `resolve`.
        local_h5 (Path): The local's archive.
        remote_h5 (Path): The remote's archive.
        start: Start requested (UTC), or None.
        end: End requested (UTC), or None.

    Returns:
        WindowChoice: The window chosen (`mt_workbench.mantle_window.choose_window`).

    Raises:
        SystemExit: When the runs share no covered span of an hour inside the window.
    """
    from mt_workbench import engine_mantle
    from mt_workbench.mantle_window import choose_window

    def epoch(t):
        return None if t is None else pd.Timestamp(t, tz="UTC").timestamp()

    try:
        choice = choose_window(engine_mantle.archive_spans(local_h5), engine_mantle.archive_spans(remote_h5),
                               res["mantle_max_hours"], start=epoch(start), end=epoch(end))
    except ValueError as exc:
        raise SystemExit(f"ERROR {res['local']} rr {res['remote']}: {exc}") from None
    res["window_choice"] = choice
    res["window"] = f"{_epoch_text(choice.start)} to {_epoch_text(choice.end)} UTC"
    return choice


def _epoch_text(t: float) -> str:
    """Format epoch seconds as "YYYY-MM-DD HH:MM:SS" UTC."""
    return pd.Timestamp(t, unit="s", tz="UTC").strftime("%Y-%m-%d %H:%M:%S")


def mantle_window_line(res: dict) -> str:
    """Return the `mantle.window_used` line of a clip run: the window, its hours and what was clipped."""
    from mt_workbench.mantle_window import clip_text

    choice = res["window_choice"]
    return (f"mantle.window_used: {_epoch_text(choice.start)} to {_epoch_text(choice.end)} UTC "
            f"({choice.hours:.2f} h; {clip_text(choice.clipped)})")


def output_channels(survey, site: str) -> list[str] | None:
    """Return the TF output channels of a site.

    Args:
        survey (Survey): The survey.
        site (str): Site name.

    Returns:
        list[str] | None: The declared electrics, plus hz when the site
        declares an hz channel (the broadband deployments do not); None when
        the site declares no channels, which keeps aurora's default.
    """
    declared = survey.site(site).channels
    if not declared:
        return None
    declared = [c.lower() for c in declared]
    return [c for c in ("ex", "ey", "hz") if c in declared]


def diagonal_azimuth(survey, site: str) -> float | None:
    """Return the ex azimuth of a derived site that holds one electric line off the N/E axes, else None.

    Such a site is the diagonal of a shared-centre layout
    (scripts/diagonal_site.py): its declared channels keep ex and not ey,
    and its `azimuth_ex` is neither 0 nor 180 deg.

    Args:
        survey (Survey): The survey.
        site (str): Site name.

    Returns:
        float | None: The azimuth in degrees, or None for any other site.
    """
    if not survey.parent_of(site):
        return None
    config = survey.site(site)
    kept = [c.lower() for c in config.channels] if config.channels else None
    if kept is None or "ex" not in kept or "ey" in kept:
        return None
    azimuth = float(config.azimuth_ex) % 360.0
    return None if azimuth in (0.0, 180.0) else azimuth


def row_runs(masks, rows) -> tuple[list[dict], list[dict]]:
    """Group the applied masks by output row into the aurora runs they need.

    Row r takes the masks that leave out whole windows (naming hx, hy or
    every channel) and the masks naming r (`mt_workbench.masks.masks_for_row`),
    in the order of `masks`. Rows with the same set share one run. The base
    run is the one with the fewest masks, ties going to the run of the
    earliest row in `rows`; its inverse signal power and everything else
    outside the rows goes into the merged transfer function (`merge_rows`).

    Args:
        masks (list of dict): The masks applied, both sites' joined
            (`mt_workbench.masks.union_masks`), normalised.
        rows (list of str): The output channels estimated, in order.

    Returns:
        tuple: ``(runs, left_out)``. `runs` is a list, in the order of each
        run's first row, of ``{"channels": [rows served], "masks": [...],
        "base": bool}``; `left_out` the masks applying to no row (naming
        only output channels the run does not estimate).
    """
    runs: list[dict] = []
    by_key: dict[tuple, dict] = {}
    used: set[int] = set()
    for row in rows:
        key = tuple(k for k, m in enumerate(masks) if masks_for_row([m], row))
        used.update(key)
        if key in by_key:
            by_key[key]["channels"].append(row)
            continue
        by_key[key] = {"channels": [row], "masks": [masks[k] for k in key], "base": False}
        runs.append(by_key[key])
    if runs:
        min(runs, key=lambda run: len(run["masks"]))["base"] = True
    return runs, [m for k, m in enumerate(masks) if k not in used]


def _period_union(tfs, rtol: float = 1e-9) -> np.ndarray:
    """Return the periods of several transfer functions joined, ascending; periods within `rtol` are one."""
    out: list[float] = []
    for tf in tfs:
        for p in np.asarray(tf.period, dtype=float):
            if not any(math.isclose(p, q, rel_tol=rtol) for q in out):
                out.append(float(p))
    return np.array(sorted(out))


def _on_periods(dataset, periods: np.ndarray, rtol: float = 1e-9):
    """Return a TF dataset on `periods`: each of its periods snapped to its match, NaN where it has none."""
    own = np.asarray(dataset["period"].values, dtype=float)
    snapped = [next(q for q in periods if math.isclose(p, q, rel_tol=rtol)) for p in own]
    return dataset.assign_coords(period=snapped).reindex(period=periods)


def merge_rows(tfs, runs):
    """Merge the transfer functions of the per-row runs into one.

    Every run's dataset is placed on the union of the runs' periods (a band
    one run lacks, aurora having dropped it for too few windows, is NaN
    there). The merged transfer function is a copy of the base run's
    (`row_runs`), metadata, inverse signal power, model errors and all;
    then for each run and each row r it served, row r of
    ``transfer_function`` and ``transfer_function_error`` and row and
    column r of ``residual_covariance`` are taken from that run. Rows are
    written in the order of the runs, so an off-diagonal residual
    covariance term between two rows of different runs comes from the
    later run, row and column alike.

    Args:
        tfs (list of TF): mt_metadata transfer functions, one per run, in
            the order of `runs`.
        runs (list of dict): From `row_runs`.

    Returns:
        TF: The merged transfer function.

    Raises:
        ValueError: If `tfs` and `runs` differ in length or no run is the base.
    """
    if len(tfs) != len(runs):
        raise ValueError(f"{len(tfs)} transfer function(s) for {len(runs)} run(s)")
    try:
        base = next(i for i, run in enumerate(runs) if run["base"])
    except StopIteration:
        raise ValueError("no run is marked as the base") from None
    periods = _period_union(tfs)
    merged = tfs[base].copy()
    ds = _on_periods(tfs[base]._transfer_function, periods)
    for tf, run in zip(tfs, runs):
        src = _on_periods(tf._transfer_function, periods)
        for row in run["channels"]:
            name = getattr(tf, row)  # the channel's name under the TF's nomenclature
            for var in ("transfer_function", "transfer_function_error"):
                ds[var].loc[dict(output=name)] = src[var].sel(output=name).reindex(input=ds["input"].values).values
            cov = "residual_covariance"
            ds[cov].loc[dict(output=name)] = src[cov].sel(output=name).reindex(input=ds["input"].values).values
            ds[cov].loc[dict(input=name)] = src[cov].sel(input=name).reindex(output=ds["output"].values).values
    merged._transfer_function = ds
    return merged


class RateMismatch(ValueError):
    """Raised by `resolve` when the local and remote archives are at different sample rates."""


class PairRefused(ValueError):
    """Raised by `resolve` when a site has no survey.yaml entry or the two sites share no time."""


def rate_min_period(sample_rate: float) -> float:
    """Return the shortest period processed at a local's own sample rate: 4 / sample_rate, in s.

    `build_band_scheme` caps the top band edge at a quarter of the sample
    rate, so this is the shortest period the scheme reaches at that rate.
    It is twice the Nyquist period, where the anti-alias FIR of
    scripts/decimate_site.py passes within 0.5 % of unit gain, and at 1 Hz
    the first level's bands, 4-16 s, span harmonics 8 to 32 of the
    128-point window.
    """
    return 4.0 / float(sample_rate)


def quadrant_window(sample_rate: float) -> tuple[float, float]:
    """Pick the (pmin, pmax) window in s for `phase_quadrants` from the sample rate.

    0.1-10 s at 100 Hz and above (the broadband deployments this window was
    tuned on); 30-3000 s below that. The 0.1-10 s band is pure noise on a
    10 Hz long-period deployment and can raise a false "180 deg out ...
    declare flip" there.
    """
    return (0.1, 10.0) if sample_rate >= 100.0 else (30.0, 3000.0)


def _package_version(name: str) -> str:
    """Return an installed package's version, or "not installed"."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def mt_workbench_version() -> str:
    """Return this checkout's `git describe`.

    Returns:
        str: The description, "uncommitted <short sha>" when the tree has
        local changes, or "unknown" when git fails.
    """

    def git(*args: str) -> str:
        """Run git in the repository and return its stripped stdout."""
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()

    try:
        sha = git("rev-parse", "--short", "HEAD")
        if git("status", "--porcelain"):
            return f"uncommitted {sha}"
        return git("describe", "--tags", "--always") or sha
    except Exception:
        return "unknown"


STACK = ("aurora", "mth5", "mt_timeseries", "mt_metadata", "mt_io")


def _sha256(data: bytes) -> str:
    """Return the hex SHA-256 of some bytes."""
    return hashlib.sha256(data).hexdigest()


def installed_origin(name: str) -> dict:
    """Return where an installed package came from and a fingerprint of what is installed.

    A fork installed from its clone carries the upstream version number, so
    the version alone cannot tell a fork row from a stock row in a ledger.
    pip records the install source in the distribution's `direct_url.json`
    (the clone's folder for an install from a local clone, and a commit only
    for an install from a version-control URL) and every installed file
    with its own hash in `RECORD`, so the hash of `RECORD` changes with any
    installed file. The `__init__.py` hash is of the file this process
    imports (a clone first on PYTHONPATH included), found without importing
    it.

    Args:
        name (str): Distribution and import name.

    Returns:
        dict: ``version``; ``direct_url`` (None for an index install),
        ``editable``, ``commit`` (the commit pip recorded, else None),
        ``record_sha256`` (None without a RECORD), ``init_path`` and
        ``init_sha256`` (None when the package is not found). Without a
        distribution, ``version`` is "not installed" and only the last two
        keys follow.
    """
    out = {"version": "not installed"}
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        dist = None
    if dist is not None:
        out = {"version": dist.version, "direct_url": None, "editable": False, "commit": None,
               "record_sha256": None}
        direct = dist.read_text("direct_url.json")
        if direct:
            info = json.loads(direct)
            out["direct_url"] = info.get("url")
            out["editable"] = bool((info.get("dir_info") or {}).get("editable"))
            out["commit"] = (info.get("vcs_info") or {}).get("commit_id")
        record = dist.read_text("RECORD")
        if record is not None:
            out["record_sha256"] = _sha256(record.encode("utf-8"))
    out["init_path"], out["init_sha256"] = None, None
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin and Path(spec.origin).is_file():
        out["init_path"] = str(spec.origin)
        out["init_sha256"] = _sha256(Path(spec.origin).read_bytes())
    return out


def versions() -> dict:
    """Return the versions of mt-workbench and of the stack, and where each package of the stack came from.

    Returns:
        dict: ``mt_workbench`` (`mt_workbench_version`), the version of each
        package of `STACK`, and ``installed``: `installed_origin` of each.
    """
    return {
        "mt_workbench": mt_workbench_version(),
        **{name: _package_version(name) for name in STACK},
        "installed": {name: installed_origin(name) for name in STACK},
    }


def _archive_info(path) -> dict:
    """Build a sidecar archive entry {"path", "mtime"}; mtime is None when the file is missing."""
    path = Path(path)
    mtime = None
    if path.exists():
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat()
    return {"path": str(path), "mtime": mtime}


def _utc_iso(t) -> str | None:
    """Format a time as a UTC ISO string, or None."""
    return None if t is None else pd.Timestamp(t, tz="UTC").isoformat()


def _declared_filters(survey, site: str, raw_sites) -> list | None:
    """Return a site's declared `filters.yaml` entries.

    Returns:
        list | None: The entries, or None for a site not in `raw_sites`
        (`recorded_site_folders`): a stack, an observatory, a derived or
        burst site, which has no raw folder and so no declaration of its
        own.
    """
    if site not in raw_sites:
        return None
    return survey.site(site).filters or []


def _quadrant_verdict(quadrant: dict, flipped: list[str]) -> str:
    """Summarise the phase-quadrant result as one line for the sidecar."""
    if flipped:
        return f"flipped: {' and '.join(flipped)} 180 deg out of quadrant"
    if quadrant.get("reason"):
        return f"not judged: {quadrant['reason']}"
    return "physical quadrants"


def instrument_pids_of(survey: Survey, site: str, archive=None, members=None) -> dict | None:
    """Return the registry DOIs a site of the pair declares, for the sidecar and the INFO lines.

    Args:
        survey (Survey): The survey.
        site (str): The local or the remote.
        archive (Path, optional): The site's archive; for a stacked remote
            (`is_stack`) without `members`, its recorded provenance names
            the members (`mt_workbench.virtual.recorded_provenance`).
        members (list of str, optional): A stack's members, given.

    Returns:
        dict or None: ``{"site", "pids": {role: doi}}`` for a site with
        keys (`Survey.instrument_pids`); for a site without (a stack)
        ``{"site", "members": {member: {role: doi}}}`` over the members
        that declare any; None when no DOI is declared, or a stack's
        members are not known (built without a recipe).
    """
    pids = survey.instrument_pids(site)
    if pids:
        return {"site": site, "pids": pids}
    if members is None and archive is not None and is_stack(site):
        from mt_workbench.virtual import recorded_provenance

        try:
            members = (recorded_provenance(archive, survey.name, site) or {}).get("members")
        except OSError as exc:
            logger.warning(f"{site}: the stack's members could not be read from {archive}: {exc}")
    found = {str(m): survey.instrument_pids(str(m)) for m in members or []}
    found = {m: p for m, p in found.items() if p}
    return {"site": site, "members": found} if found else None


def _pair_pids(res: dict) -> dict:
    """Return the sidecar's `instrument_pids` of a resolved pair: the roles with a declaration (`instrument_pids_of`)."""
    out = {}
    for role in ("local", "remote"):
        entry = instrument_pids_of(res["survey"], res[role], res.get(f"{role}_archive"))
        if entry:
            out[role] = entry
    return out


def overlap_record(res: dict, args) -> dict | None:
    """Return the sidecar's `overlap` block: the short and long overlap, their sources and the per-level table.

    ``short_pct`` is ``overlap_pct`` (25 by default); ``long_pct`` the
    overlap of the levels whose window lasts over 600 s
    (`LONG_WINDOW_SECONDS`): ``overlap_pct_long`` when given, else
    ``overlap_pct`` when given (it replaces the boost on every level), else
    75 (`mt_workbench.process.build_config`). ``long_source`` names where it
    came from: "--overlap-long", "--overlap (every level)", "survey
    processing: overlap_long:", "survey processing: overlap: (every level)"
    or "built-in 75 % (mt_workbench.process.build_config)". ``levels`` is
    `mt_workbench.process.overlap_table` of the config the run used. None
    for a MANTLE run.
    """
    if res.get("engine") == "mantle":
        return None
    tw = res.get("tweaks") or {}
    if "overlap_pct_long" in tw:
        long_pct = float(tw["overlap_pct_long"])
        source = "--overlap-long" if getattr(args, "overlap_long", None) is not None else \
            "survey processing: overlap_long:"
    elif "overlap_pct" in tw:
        long_pct = float(tw["overlap_pct"])
        source = "--overlap (every level)" if getattr(args, "overlap", None) is not None else \
            "survey processing: overlap: (every level)"
    else:
        long_pct, source = 75.0, "built-in 75 % (mt_workbench.process.build_config)"
    return {"short_pct": float(tw.get("overlap_pct", ESTIMATOR_DEFAULTS["overlap_pct"])), "long_pct": long_pct,
            "long_source": source, "long_window_s": LONG_WINDOW_SECONDS, "levels": res.get("overlap_levels")}


def build_sidecar(res: dict, args, started, finished, edi_path: Path, png_path: Path,
                   quadrant: dict, flipped: list[str], frame: dict | None = None) -> dict:
    """Build the `.json` sidecar describing this run.

    `quadrant` and `flipped` are computed by the caller, so the function is a
    pure dict builder; a unit test can pass a fake TF through
    `phase_quadrants` and hand the result in without an aurora run.

    Args:
        res (dict): Output of `resolve`, with the archives processed from.
        args (argparse.Namespace): Parsed arguments.
        started (datetime.datetime): Start of the run.
        finished (datetime.datetime): End of the run.
        edi_path (Path): EDI written.
        png_path (Path): Comparison figure written.
        quadrant (dict): Return of `mt_workbench.compare.phase_quadrants`.
        flipped (list[str]): Modes judged out of quadrant.
        frame (dict, optional): The TF's frame metadata
            (`mt_workbench.products.frame_record`), stored as ``frame``.

    Returns:
        dict: The sidecar content. ``edi``, ``xml`` and ``h5`` name the
        row's three products (`mt_workbench.products.product_names`);
        ``instrument_pids`` (`_pair_pids`) is there only when survey.yaml
        declares a registry DOI for the local, the remote or a stack's
        members.
    """
    survey = res["survey"]
    raw_sites = res["raw_sites"]
    local, remote = res["local"], res["remote"]
    pids = _pair_pids(res)
    choice = res.get("window_choice")
    if choice is None:
        window = {"start": _utc_iso(args.start), "end": _utc_iso(args.end)}
        clipped = {}
    else:  # --mantle-window clip: the window used, and what was clipped from the one requested
        window = {"start": pd.Timestamp(choice.start, unit="s", tz="UTC").isoformat(),
                  "end": pd.Timestamp(choice.end, unit="s", tz="UTC").isoformat()}
        clipped = {"window_clipped": choice.clipped}
    return {
        "local": local,
        "remote": remote,
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "seconds": (finished - started).total_seconds(),
        "window": window,
        **clipped,
        "local_archive": _archive_info(res["local_archive"]),
        "remote_archive": _archive_info(res["remote_archive"]),
        "survey_yaml": {"path": res["survey_yaml"], "name": Path(res["survey_yaml"]).name},
        # the instruments' registry DOIs as survey.yaml declares them; absent when none is declared
        **({"instrument_pids": pids} if pids else {}),
        # the rates the band scheme and quadrant window were built at (`local`),
        # and the derived sites' parents
        "sample_rates": {"survey": survey.sample_rate, "local": res.get("sample_rate", survey.sample_rate),
                         "remote": res.get("remote_sample_rate", survey.sample_rate)},
        "derived_from": {local: res.get("local_parent"), remote: res.get("remote_parent")},
        "band_scheme": dict(res["scheme_kwargs"]),
        # the lowest band edge of the decimated levels, in FFT harmonics of the level
        "lowest_harmonic": res.get("lowest_harmonic"),
        "min_band_windows": res.get("min_band_windows"),
        # the periods the floor removed (`dropped_record`); null for MANTLE, which applies no floor
        "dropped_periods": (None if res.get("engine") == "mantle"
                            else dropped_record(res.get("dropped_periods") or [], res.get("min_band_windows"))),
        # the full effective set, defaults filled in, so the sidecar says
        # "taper: hann" on a run without --taper too
        "tweaks": {**ESTIMATOR_DEFAULTS, **res["tweaks"]},
        # issue 181: the overlap each level used (25 % short, 75 % on levels over 600 s by default), which
        # tweaks.overlap_pct alone does not say; null for MANTLE (no aurora STFT)
        "overlap": overlap_record(res, args),
        "filters": {
            local: _declared_filters(survey, local, raw_sites),
            remote: _declared_filters(survey, remote, raw_sites),
        },
        # the masks.yaml entries applied from each site, the scope rule that chose the
        # remote's and the counts, and the union actually applied (the key the
        # existing sidecar readers use); each entry as masks.yaml holds it, `channels`
        # only when it names channels
        "masks_local": [stored(m) for m in res.get("masks_local") or []],
        "masks_remote": [stored(m) for m in res.get("masks_remote") or []],
        "mask_origins": res.get("mask_origins"),
        # --masks-file: the candidate file read in place of the survey's masks.yaml (null: the survey's own)
        "masks_file": res.get("masks_file"),
        "mask_scope": res.get("mask_scope", "role"),
        "mask_counts": dict(res.get("mask_counts") or {"local": 0, "remote": 0, "remote_left_out": 0,
                                                       "remote_left_out_channels": 0,
                                                       "local_left_out_channels": 0}),
        "masks": [stored(m) for m in res.get("masks") or []],
        # the aurora runs the masks' channels needed (`row_runs`): the output rows each
        # served, its mask count, and the base run whose other fields the EDI carries
        "channel_runs": [{"channels": list(run["channels"]), "masks": len(run["masks"]), "base": bool(run["base"])}
                         for run in res.get("channel_runs") or []],
        "masks_ignored": bool(res.get("masks_ignored")),
        "argv": list(sys.argv),
        "tag": res["tag"],
        **product_names(edi_path),
        "frame": frame,
        "figure": png_path.name,
        "quadrant": {
            "pmin": quadrant.get("pmin"), "pmax": quadrant.get("pmax"),
            "xy": quadrant.get("xy"), "yx": quadrant.get("yx"),
            "xy_ok": quadrant.get("xy_ok"), "yx_ok": quadrant.get("yx_ok"),
            "verdict": _quadrant_verdict(quadrant, flipped),
        },
        "versions": versions(),
    }


def dropped_record(periods, min_band_windows) -> dict:
    """Return the sidecar's `dropped_periods` entry of an aurora run.

    Args:
        periods (iterable of float): The periods the floor removed, in s
            (`mt_workbench.process.drop_short_bands`); repeats are counted
            once.
        min_band_windows (int): The floor the run used.

    Returns:
        dict: ``{"n", "periods_s", "min_band_windows"}``, the periods sorted;
        n 0 and an empty list when none were removed.
    """
    kept = sorted({float(p) for p in periods})
    return {"n": len(kept), "periods_s": kept,
            "min_band_windows": None if min_band_windows is None else int(min_band_windows)}


def write_sidecar(path: Path, sidecar: dict) -> None:
    """Write the sidecar as indented JSON."""
    path.write_text(json.dumps(sidecar, indent=2, default=str) + "\n", encoding="utf-8")


def edi_info_lines(sidecar: dict) -> list[str]:
    """Build a few `key=value` lines for the EDI's INFO block.

    `tf.station_metadata.transfer_function.processing_parameters` is a plain
    list of strings that mt_metadata's edi writer writes unchanged into
    `>INFO`. In mt_metadata 1.0.10, `station_metadata.comments` is used when
    reading an EDI but is absent from the write path. The lines point to the
    sidecar JSON, which holds the full record. A sidecar with
    `instrument_pids` adds one line per instrument of the local and the
    remote (`mt_workbench.products.pid_info_lines`).

    Args:
        sidecar (dict): Output of `build_sidecar`.

    Returns:
        list[str]: The INFO lines.
    """
    lines = [
        f"mt_workbench.version={sidecar['versions']['mt_workbench']}",
        f"mt_workbench.started={sidecar['started']}",
        f"mt_workbench.tag={sidecar['tag'] or ''}",
    ]
    if sidecar.get("engine", "aurora") == "aurora":
        lines.append(f"mt_workbench.taper={sidecar['tweaks']['taper']}")
    else:
        lines += [f"mt_workbench.engine={sidecar['engine']}", f"mt_workbench.engine_version={sidecar['engine_version']}"]
    lines += [
        f"mt_workbench.quadrant_verdict={sidecar['quadrant']['verdict']}",
        f"mt_workbench.sidecar={sidecar['edi'].rsplit('.', 1)[0]}.json",
    ]
    for role in ("local", "remote"):
        lines += pid_info_lines(role, (sidecar.get("instrument_pids") or {}).get(role))
    return lines


def _print_archive_status(label: str, status: dict | None) -> None:
    """Print one archive status line.

    The line is "<label> archive: raw: <path>, variant: ready | to build
    (<hash>) | none declared | no filters used (--no-filters)", with
    "(missing: ingested from <raw folder> first)" after the path when the
    raw archive does not exist and its raw folder is there, "(missing, and
    no raw folder at <folder> to ingest from)" when neither is, or
    "(no raw folder)" when `archive_status` returned None, which now means
    a virtual remote only: a stack, an observatory, a burst site or an
    undeclared archive (workbench issue 32).
    """
    if status is None:
        print(f"{label} archive: (no raw folder)")
        return
    missing = f" ({status['raw_missing']})" if status.get("raw_missing") else ""
    print(f"{label} archive: raw: {status['raw']}{missing}, variant: {status['variant_state']}")


def _reads_text(status: dict | None, path, virtual: bool) -> str:
    """Return the archive a site is read from, as far as the resolution tells, for `print_resolution`.

    A virtual remote's archive as it is; the filtered variant with its
    state when the site declares filters (ready, or to build from the raw
    archive); else the raw archive with the reason no variant is read.
    """
    if virtual or status is None:
        return f"{path} (as it is)"
    if status.get("variant"):
        return f"{status['variant']} (filtered variant, {status['variant_state']})"
    return f"{status['raw']} (raw archive, filters: {status['variant_state']})"


def _filters_text(survey, site: str, raw_sites) -> str:
    """Return the kinds of the declared filters the sidecar records for a site (`_declared_filters`)."""
    declared = _declared_filters(survey, site, raw_sites)
    if declared is None:
        return "not recorded (no raw folder of its own)"
    return ", ".join(k for entry in declared for k in entry) or "none declared"


def print_resolution(res: dict) -> None:
    """Print the resolution as `key: value` lines, as --dry-run and the log show it.

    Besides the resolution's own entries, `local_reads`/`remote_reads`
    name the archive each site is processed from (`_reads_text`) and
    `filters_recorded` the declared filter kinds the sidecar records for
    each site (`_filters_text`).
    """
    for key in ("survey_yaml", "local", "remote", "local_archive", "remote_archive",
                "virtual_remote", "ignore_filters", "start", "end", "window",
                "started", "tag", "stem", "engine"):
        value = res[key]
        if key == "started" and value is not None:
            value = value.isoformat()
        print(f"{key}: {value if value is not None else ''}")
    _print_archive_status("local", res["local_status"])
    _print_archive_status("remote", res["remote_status"])
    print(f"local_reads: {_reads_text(res['local_status'], res['local_archive'], False)}")
    print(f"remote_reads: {_reads_text(res['remote_status'], res['remote_archive'], res['virtual_remote'])}")
    print("filters_recorded: " + "; ".join(f"{res[role]} {_filters_text(res['survey'], res[role], res['raw_sites'])}"
                                           for role in ("local", "remote")))
    for role in ("local", "remote"):
        span = (res.get("spans") or {}).get(role)
        print(f"{role}_span: {res[role]} " + (f"{_utc_text(span[0])} to {_utc_text(span[1])} ({span[2]})"
                                             if span else "unknown (no start/end in survey.yaml and no archive)"))
    print(f"sample_rate: {res['local']} {res['sample_rate']:g} Hz, {res['remote']} {res['remote_sample_rate']:g} Hz")
    oc = res["output_channels"]
    print("output_channels: " + (", ".join(oc) if oc else "aurora default (ex, ey, hz)"))
    for key in BAND_KEYS:
        value = res["scheme_kwargs"][key]
        if key == "notch_frequencies":
            value = ", ".join(f"{f:g}" for f in value)
        elif key == "min_bin" and value is None:
            value = "none (the layout's own)"
        # the FFT window prints as window_samples: `window` is the processing window's line
        print(f"{'window_samples' if key == 'window' else key}: {value}")
    print(f"lowest_harmonic: {res['lowest_harmonic']:.4g}")
    extra = {k: v for k, v in res["scheme_kwargs"].items() if k not in BAND_KEYS}
    for key, value in extra.items():
        print(f"{key}: {value}")
    if res["masks_ignored"]:
        print("masks: ignored (--no-masks)")
    else:
        counts = res.get("mask_counts", {})
        left_out = counts.get("remote_left_out", 0)
        scope = ("; --mask-scope union" if res.get("mask_scope") == "union" else
                 f"; {res['remote']} {left_out} of scope local left out" if left_out else "")
        n_ch = counts.get("remote_left_out_channels", 0)
        if n_ch:
            scope += f"; {res['remote']} {n_ch} naming no magnetic channel left out"
        n_row = counts.get("local_left_out_channels", 0)
        if n_row:
            scope += f"; {res['local']} {n_row} naming no output channel estimated left out"
        print(f"masks: {res['local']} {len(res['masks_local'])}, {res['remote']} "
              f"{len(res['masks_remote'])} ({len(res['masks'])} applied"
              + (f"; origins {', '.join(res['mask_origins'])}" if res.get("mask_origins") else "") + scope + ")")
        print(f"mask runs: {runs_text(res.get('channel_runs') or [])}")
        if res.get("masks_file"):
            print(f"masks file: {res['masks_file']}")
    if res["engine"] != "mantle" and res.get("min_band_windows") is not None:
        print(f"min_band_windows: {res['min_band_windows']}")
    for key, value in res["tweaks"].items():
        print(f"tweak.{key}: {value}")
    if not res["tweaks"]:
        print("tweaks: none")
    for role, entry in _pair_pids(res).items():  # only the roles with registry DOIs declared
        if entry.get("pids"):
            print(f"instrument_pid.{role}: {entry['site']} {pid_text(entry['pids'])}")
        for member, pids in (entry.get("members") or {}).items():
            print(f"instrument_pid.{role}: {entry['site']} member {member} {pid_text(pids)}")
    if res["engine"] == "mantle":
        print(f"mantle.whiten: {res['mantle_whiten']}")
        print(f"mantle.max_hours: {res['mantle_max_hours']:g}")
        if res.get("mantle_window") == "clip":
            print("mantle.window: clip")


def runs_text(runs) -> str:
    """Describe the per-row runs as "ex 5; ey+hz 3 (base)": each run's rows, its mask count, the base marked."""
    return "; ".join(f"{'+'.join(run['channels'])} {len(run['masks'])}" + (" (base)" if run["base"] else "")
                     for run in runs) or "none"


def main(args) -> None:
    """Process one pair and write the EDI, comparison figure and sidecar.

    Args:
        args (argparse.Namespace): Parsed arguments from `build_parser`.
    """
    started = dt.datetime.now().astimezone()
    try:
        res = resolve(args, started)
    except (RateMismatch, PairRefused) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    survey = res["survey"]
    print_resolution(res)
    if args.dry_run:
        if res["mantle_window"] == "clip":
            local_h5, remote_h5 = dry_run_archives(res)
            missing = [str(p) for p in (local_h5, remote_h5) if not p.exists()]
            if missing:
                print(f"mantle.window_used: unknown until the archives exist ({', '.join(missing)})")
                return
            choose_mantle_window(res, local_h5, remote_h5, args.start, args.end)
            print(mantle_window_line(res) + f" (runs of {local_h5.name} and {remote_h5.name})")
        return

    raw_sites = res["raw_sites"]
    local, remote = res["local"], res["remote"]
    use_filters = not res["ignore_filters"]
    for site in (local, remote):
        if site not in raw_sites:
            continue
        cfg = survey.site(site)
        logger.info(
            f"{site}: Ex {cfg.dipole_length_ex} m @ {cfg.azimuth_ex} deg, "
            f"Ey {cfg.dipole_length_ey} m @ {cfg.azimuth_ey} deg, timing {cfg.timing}"
        )
    for site, parent, path in ((local, res["local_parent"], res["local_archive"]),
                               (remote, res["remote_parent"], res["remote_archive"])):
        if parent and not Path(path).exists():
            raise FileNotFoundError(f"{site}: no archive at {path}; decimate {parent} first: "
                                    f"scripts/decimate_site.py {args.survey_yaml} {parent}")
    # the raw archive first (ingest_site reuses it if it is already there),
    # then the archive processing actually reads: the filtered variant,
    # built from the raw one on demand, or the raw archive itself with
    # --no-filters (`processing_archive`); a derived local's archive is used
    # as scripts/decimate_site.py wrote it
    if res["local_parent"]:
        logger.info(f"{local}: derived from {res['local_parent']} at {res['sample_rate']:g} Hz, "
                    f"using {res['local_archive']}")
        local_h5 = res["local_archive"]
    else:
        ingest_site(survey, local, max_run_files=MAX_RUN_FILES)
        local_h5 = processing_archive(survey, local, use_filters=use_filters)
    if res["virtual_remote"]:
        logger.info(f"{remote}: virtual remote, using {res['remote_archive']}")
        remote_h5 = res["remote_archive"]
    else:
        ingest_site(survey, remote, max_run_files=MAX_RUN_FILES)
        remote_h5 = processing_archive(survey, remote, use_filters=use_filters)
    res["local_archive"], res["remote_archive"] = local_h5, remote_h5
    for site, path in ((local, local_h5), (remote, remote_h5)):
        warn_without_h_polarity(path, site)  # an archive built before the stage: named, processed as it is

    stem = res["stem"]
    scheme = build_band_scheme(res["sample_rate"], **res["scheme_kwargs"])
    masks = res["masks"]  # the masks.yaml intervals applied from both sites, joined (`resolve`)
    if res["masks_ignored"]:
        logger.info(f"{local}, {remote}: masks.yaml ignored (--no-masks)")
    else:
        def all_band(declared):
            return sum(1 for m in declared if m["bands"] == "all")

        if res["masks_local"]:
            logger.info(f"{local}: {len(res['masks_local'])} mask(s) declared in masks.yaml "
                        f"({all_band(res['masks_local'])} all-band, applied as time cuts)")
        left_out = res["mask_counts"]["remote_left_out"]
        left_channels = res["mask_counts"].get("remote_left_out_channels", 0)
        if res["masks_remote"] or left_out or left_channels:
            chosen = "every entry (--mask-scope union)" if res["mask_scope"] == "union" else "scope both or remote"
            logger.info(f"{remote} (remote): {len(res['masks_remote'])} mask(s) applied, {chosen} "
                        f"({all_band(res['masks_remote'])} all-band, applied as time cuts); "
                        f"{left_out} of scope local left out; {left_channels} naming no magnetic channel left out")
        if res["masks_remote"]:
            logger.info(f"{local} rr {remote}: {len(masks)} mask(s) applied (both sites' entries joined)")
        if len(res["channel_runs"]) > 1:
            logger.info(f"{local} rr {remote}: masks by output row, one aurora run each: "
                        f"{runs_text(res['channel_runs'])}")
    extras: dict = {}
    # the frame and declination are read from survey.yaml here and set on the TF before the write,
    # so an archive ingested before the keys existed (declination 0.0) needs no rebuild; the data keep
    # their frame. The products are written once, at the end, with the INFO lines
    local_cfg = survey.site(local)
    if res["engine"] == "mantle":
        # the second engine: the same archives and window, MANTLE's cascade, the EDI on the same
        # band grid; imported here so an aurora run needs no MANTLE install
        from mt_workbench import engine_mantle

        site_cfg = survey.site(local)
        start, end = args.start, args.end
        if res["mantle_window"] == "clip":
            choice = choose_mantle_window(res, local_h5, remote_h5, args.start, args.end)
            print(mantle_window_line(res))
            logger.info(f"{local} rr {remote}: {mantle_window_line(res)}")
            start, end = choice.start, choice.end  # epoch seconds, which MANTLE's reader takes as they are
        tf, extras = engine_mantle.process_pair(
            local_h5, local, remote_h5, remote,
            survey_name=survey.name, latitude=site_cfg.latitude, longitude=site_cfg.longitude,
            elevation=site_cfg.elevation if site_cfg.elevation is not None else 0.0,
            out_dir=survey.workspace / "tf", stem=stem, scheme=scheme, start=start, end=end,
            options=engine_mantle.MantleOptions(whiten=res["mantle_whiten"], max_hours=res["mantle_max_hours"]),
        )
        apply_site_frame(tf.station_metadata, local_cfg)
    else:
        runs = res["channel_runs"]
        station_kwargs = dict(
            band_scheme=scheme, start=args.start, end=args.end, tag=stem, tweaks=res["tweaks"] or None,
            min_band_windows=res["min_band_windows"],
            **({"output_channels": res["output_channels"]} if res["output_channels"] else {}),
        )
        if len(runs) == 1:
            tf = process_station(local_h5, local, remote_h5, remote, out_dir=None,
                                 time_masks=runs[0]["masks"] or None, site=local_cfg, **station_kwargs)
            res["dropped_periods"] = list(getattr(tf, DROPPED_ATTR, []))
            res["overlap_levels"] = getattr(tf, OVERLAP_ATTR, None)
        else:
            # one run per distinct set of masks by output row, merged row by row (`merge_rows`)
            tfs = []
            for k, run in enumerate(runs, 1):
                logger.info(f"{local} rr {remote}: run {k} of {len(runs)}, rows {', '.join(run['channels'])}, "
                            f"{len(run['masks'])} mask(s)" + (" (the base run)" if run["base"] else ""))
                tfs.append(process_station(local_h5, local, remote_h5, remote, out_dir=None,
                                           time_masks=run["masks"] or None, **station_kwargs))
            res["dropped_periods"] = [p for run_tf in tfs for p in getattr(run_tf, DROPPED_ATTR, [])]
            res["overlap_levels"] = getattr(tfs[0], OVERLAP_ATTR, None)  # one config for every row's run
            tf = merge_rows(tfs, runs)
            # a band one row's run did not keep stays NaN in that row; the period goes only when no row is left
            drop_bad_errors(tf, f"{stem} (rows merged)")
            apply_site_frame(tf.station_metadata, local_cfg)
            logger.info(f"{stem}: rows merged from {len(runs)} aurora runs (the masks' channels)")

    pmin, pmax = quadrant_window(res["sample_rate"])
    logger.info(
        f"{local}: judging phase quadrants over {pmin:g}-{pmax:g} s "
        f"(sample rate {res['sample_rate']:g} Hz)"
    )
    q = phase_quadrants(tf, pmin=pmin, pmax=pmax)
    msg = f"{local}: median phases {q['pmin']:g}-{q['pmax']:g} s xy {q['xy']:+.0f} deg, yx {q['yx']:+.0f} deg"
    # a mode with too few usable periods is not judged (nan) and counts as
    # undetermined; a judged mode outside its quadrant is a sign error
    flipped = [m for m in ("xy", "yx") if not q[f"{m}_ok"] and q[f"{m}_n"] >= 5]
    diagonal = diagonal_azimuth(survey, local)
    if diagonal is not None:
        # a line along another azimuth mixes the tensor's two rows: its phases have no fixed quadrant
        flipped = []
        q["reason"] = (f"{local} holds one electric line along {diagonal:g} deg (a diagonal, "
                       f"scripts/diagonal_site.py), whose row has no fixed phase quadrant")
        logger.info(msg + f"; not judged: {q['reason']}")
    elif flipped:
        logger.error(
            msg + f"; {' and '.join(flipped)} 180 deg out of quadrant: an E or H channel has the wrong sign. "
            "Declare `flip: {channels: [...]}` for the site on the Filter Data tab (or check "
            "flip_reversed_dipoles in survey.yaml), rebuild the archive and re-run."
        )
    elif q["reason"]:
        logger.warning(msg + f"; not judged: {q['reason']}; look at the EDI before trusting it")
    else:
        logger.info(msg + " (physical quadrants)")

    baseline = reference_edi(Path(args.survey_yaml), local)
    if baseline is None and res["local_parent"]:  # a derived site is compared with its parent's EDI
        baseline = reference_edi(Path(args.survey_yaml), res["local_parent"])
    if baseline is None:
        logger.warning(f"{local}: no reference EDI mapped, plotting aurora alone")
    out_png = survey.workspace / "tf" / f"{stem}_vs_lemimt.png"
    plot_comparison(
        tf, baseline=baseline,
        title=f"{local} RR {remote} — {res['engine']} vs lemimt ({res['window']})",
        out_png=out_png, main_label=res["engine"],
    )
    logger.info(f"wrote {out_png}")
    print(f"comparison figure: {out_png}")

    finished = dt.datetime.now().astimezone()
    edi_path = survey.workspace / "tf" / f"{stem}.edi"
    # survey.yaml products.zrot: what the EDI writes as ZROT and TROT (`mt_workbench.products.zrot_rule_of`; the
    # default "declination" leaves the products as before), recorded in the TF, the sidecar's frame and the XML
    set_zrot_rule(tf, zrot_rule_of(survey))
    # the local site's instrument identity from <survey folder>/instruments.csv, when the file has it
    instrument_lines = instrument_info_lines(survey, local)
    apply_instruments(tf, survey, local)
    match_coordinate_system(tf)
    frame = frame_record(tf, "survey.yaml" if local_cfg.declination is not None else "archive")
    if frame["declination"] is None:
        logger.warning(f"{local}: no declination in survey.yaml or the archive: the products state none "
                       f"(scripts/declination.py {args.survey_yaml} {local} --write stores it)")
    sidecar = build_sidecar(res, args, started, finished, edi_path, out_png, q, flipped, frame)
    sidecar.update(extras)  # the mantle engine's keys; an aurora run adds none
    if instrument_lines:
        sidecar["instrument_info"] = instrument_lines
        full = instrument_info_lines(survey, local, cut=False)
        if full != instrument_lines:  # INFO cuts a long cell at INFO_MAX; the sidecar keeps it whole
            sidecar["instrument_info_full"] = full
    sidecar_path = edi_path.with_suffix(".json")
    write_sidecar(sidecar_path, sidecar)
    logger.info(f"wrote {sidecar_path}")
    print(f"sidecar: {sidecar_path}")

    # a short pointer to the sidecar in the EDI's INFO block; the docstring of
    # edi_info_lines explains the use of `processing_parameters`. The three
    # products are then written, once (the EDI's frame lines are added by
    # mt_workbench.products.edi_copy)
    try:
        tf.station_metadata.transfer_function.processing_parameters.extend(edi_info_lines(sidecar) + instrument_lines)
    except Exception as exc:
        logger.warning(f"{edi_path.name}: could not add the run's facts to the EDI's INFO block: {exc}")
    write_products(tf, edi_path)


if __name__ == "__main__":
    main(build_parser().parse_args())
