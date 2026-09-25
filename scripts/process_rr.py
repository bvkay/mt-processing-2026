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
`mtproc.ingest.processing_archive`: the filtered variant
(`<site>_f<hash>.h5`, built from the raw archive when it is missing or its
recorded hash does not match the current `filters.yaml`), or the raw archive
with `--no-filters`, which shows whether a filter was worth declaring.
`--tag` adds a suffix to the output name so such runs keep separate files.
`--dry-run` prints everything the run resolved to (band kwargs, both sites'
raw and variant archive status, window, product stem) and exits without
opening a file or building a variant.

Time masks (`<survey>/masks.yaml`, declared per site on the GUI's
Cross-powers tab) are applied from both sites of the pair: the local and
remote entries are joined (`mtproc.masks.union_masks`). A remote-referenced
estimate uses both stations' samples, so an interval that is bad at either
one is left out. A stacked remote (`STK_...`) has no entry of its own; the
remote is looked up by its name (`mtproc.masks.remote_masks`), so its masks
apply whether or not data_root is mounted. `--no-masks` ignores the file for
both sites.

A derived site (`<site>L`, written by scripts/decimate_site.py at its own
`sample_rate:`, 1 Hz) is processed from its archive as it is, against a
remote at the same rate: an observatory (scripts/fetch_observatory.py) or
another derived site. Its runs are its parent's, so MAX_RUN_FILES shaped
them at ingest. The band scheme and the quadrant window follow the local's
rate, and so does the shortest period, `rate_min_period` (4 s at 1 Hz),
unless --min-period is given. A remote at another rate is refused (exit 2)
with both rates named. A derived local without a reference EDI of its own
is compared with its parent's. The sidecar records the rates
(`sample_rates`) and the parents (`derived_from`).

The estimator flags (--taper ... --tolerance) are advanced options: each
changes aurora's STFT or robust regression on every decimation level for
this run only (`mtproc.process.process_station(tweaks=...)`, whose docstring
gives the default in use for each). The flags given become tweaks; with none
the run uses the defaults, and the resolution prints "tweaks: none".

`--engine mantle` estimates with MANTLE instead of aurora
(`mtproc.engine_mantle`): the same processing archives and window, read
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

Outputs: <workspace>/mth5/<site>.h5, <workspace>/tf/<stem>.edi,
<workspace>/tf/<stem>_vs_lemimt.png and <workspace>/tf/<stem>.json, where
<stem> is <local>_rr-<remote>_<YYYYMMDD-HHMM> (the local time this run
started, taken from the machine clock at the top of `main` and formatted
once) plus the --tag suffix when given. The stem uses the run's start rather
than the processing window, since two runs of the same pair over the same
window would otherwise overwrite each other's EDI. The window, and
everything else about the run (archives and their mtimes, the band scheme
and estimator tweaks used, both sites' declared filters, the full argv, the
phase-quadrant verdict and the package versions), is in the `.json` sidecar
next to the EDI. A short summary also goes into the EDI's INFO block
(`processing_parameters`).

Usage:
    python scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end]
        [--min-period S] [--max-period S] [--per-decade N] [--notch "50,150"]
        [--no-filters] [--no-masks | --masks] [--tag SUFFIX] [--dry-run]
        [--taper {boxcar,hamming,hann,dpss}] [--overlap PCT] [--no-prewhiten]
        [--min-windows N] [--max-iterations N] [--redescending-iterations N]
        [--r0 X] [--u0 X] [--tolerance X]
        [--engine {aurora,mantle}] [--mantle-whiten {none,diff}]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import datetime as dt
import importlib.metadata
import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
import yaml
from loguru import logger

from mtproc.bands import build_band_scheme
from mtproc.compare import phase_quadrants, plot_comparison
from mtproc.ingest import default_archive_path, filters_hash, ingest_site, processing_archive, variant_path, variant_ready
from mtproc.masks import load_masks, remote_masks, union_masks
from mtproc.process import ESTIMATOR_DEFAULTS, TAPERS, process_station
from mtproc.survey import Survey

MAX_RUN_FILES = 34  # 34 x 90 min = 51 h per run
ENGINES = ("aurora", "mantle")
MANTLE_WHITEN = ("none", "diff")  # mtproc.engine_mantle.WHITEN, spelt here so the parser builds without MANTLE
# the band-scheme keys this CLI can override; anything else in the survey's
# `processing:` block (window, factor, notch_fraction) is passed through
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies")


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
    p.add_argument("--tag", default=None, help="suffix appended to the output stem")
    p.add_argument("--dry-run", action="store_true",
                   help="print what this run resolved to and exit, opening nothing")
    adv = p.add_argument_group("advanced: the aurora estimator, on every decimation level")
    adv.add_argument("--taper", choices=TAPERS, default=None, help="STFT window (in use: hann; aurora's own is boxcar)")
    adv.add_argument("--overlap", type=float, default=None, metavar="PCT",
                     help="STFT overlap %% on every level (in use: 25, 75 on windows over 600 s)")
    adv.add_argument("--no-prewhiten", action="store_true",
                     help="skip the first-difference pre-whitening (and its recolouring)")
    adv.add_argument("--min-windows", type=int, default=None, metavar="N",
                     help="fewest STFT windows a level needs (in use: 0)")
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
    return p


def tweaks_from(args) -> dict:
    """Collect the estimator flags given on the command line.

    Args:
        args (argparse.Namespace): Parsed arguments.

    Returns:
        dict: The given flags as `process_station(tweaks=...)` keys; {} when
        none were given.
    """
    given = {
        "taper": args.taper,
        "overlap_pct": args.overlap,
        "prewhiten": False if args.no_prewhiten else None,
        "min_windows": args.min_windows,
        "max_iterations": args.max_iterations,
        "redescending_iterations": args.redescending_iterations,
        "r0": args.r0,
        "u0": args.u0,
        "tolerance": args.tolerance,
    }
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


def archive_status(survey: Survey, site: str, raw_sites: dict, use_filters: bool) -> dict | None:
    """Report a site's raw and variant archive status without building anything.

    Args:
        survey (Survey): The survey.
        site (str): Site name.
        raw_sites (dict): Site name to raw-data folder.
        use_filters (bool): False with --no-filters.

    Returns:
        dict | None: {"raw", "variant", "variant_state"}. `variant` is None
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
        return {"raw": default_archive_path(survey, site), "variant": None, "derived_from": parent,
                "variant_state": f"none (derived from {parent}: its archive is used as it is)"}
    if site not in raw_sites:
        return None
    raw = default_archive_path(survey, site)
    declared = survey.site(site).filters or []
    if not use_filters:
        return {"raw": raw, "variant": None, "variant_state": "no filters used (--no-filters)"}
    if not declared:
        return {"raw": raw, "variant": None, "variant_state": "none declared"}
    vpath = variant_path(survey, site)
    ready = raw.exists() and variant_ready(survey, site)
    state = "ready" if ready else f"to build ({filters_hash(declared)})"
    return {"raw": raw, "variant": vpath, "variant_state": state}


def resolve(args, started) -> dict:
    """Resolve everything the run needs before any file is opened.

    The band kwargs are the survey's `processing:` block with the command
    line's overrides applied, filled out from the defaults of
    `build_band_scheme` so `--dry-run` prints a number for each. `started`
    is the local wall-clock instant `main` began
    (`dt.datetime.now().astimezone()`), passed in so the product stem and the
    sidecar agree on the start time.

    `local_archive`/`remote_archive` are each site's raw archive path
    (`default_archive_path`), so `--dry-run` builds nothing;
    `local_status`/`remote_status` (`archive_status`) say whether a filtered
    variant is ready, needs building, or is not used. After the `--dry-run`
    return, `main` resolves the archive processed from
    (`mtproc.ingest.processing_archive`, which builds a missing variant) and
    overwrites these two entries before the sidecar is written.

    `masks_local`/`masks_remote` are each site's `masks.yaml` entries
    (`load_masks`, and `remote_masks` for the remote, which gives [] for a
    stack named `STK_...`), and `masks` is their union in start order, as
    passed to `process_station`. With `--no-masks` all three are [] and
    `masks_ignored` is True.

    `sample_rate` and `remote_sample_rate` are `Survey.sample_rate_of` of
    the two sites; the band scheme and the quadrant window use
    `sample_rate`. A local at its own rate (a derived site) starts at
    `rate_min_period` unless --min-period is given.

    Args:
        args (argparse.Namespace): Parsed arguments.
        started (datetime.datetime): Start of the run.

    Returns:
        dict: The resolution, printed by `print_resolution`.

    Raises:
        RateMismatch: When the two sites' sample rates differ.
    """
    survey = Survey.from_yaml(args.survey_yaml)
    scheme_kwargs = dict(survey.processing)
    for key, value in (
        ("min_period", args.min_period),
        ("max_period", args.max_period),
        ("periods_per_decade", args.per_decade),
        ("notch_frequencies", None if args.notch is None else parse_notch(args.notch)),
    ):
        if value is not None:
            scheme_kwargs[key] = value
    defaults = {n: p.default for n, p in inspect.signature(build_band_scheme).parameters.items()}
    for key in BAND_KEYS:
        scheme_kwargs.setdefault(key, defaults[key])
    # the local's own rate (a derived <site>L at 1 Hz) or the survey's; the
    # remote's must match, since aurora pairs archives of one rate
    local_rate = survey.sample_rate_of(args.local)
    remote_rate = survey.sample_rate_of(args.remote)
    if not math.isclose(local_rate, remote_rate, rel_tol=1e-9):
        hint = (f": decimate the local first (scripts/decimate_site.py {args.survey_yaml} {args.local}) and "
                f"process {args.local}L against {args.remote}" if remote_rate < local_rate else "")
        raise RateMismatch(f"{args.local} is at {local_rate:g} Hz and {args.remote} at {remote_rate:g} Hz; aurora "
                           f"needs one sample rate for both{hint}")
    if args.min_period is None and local_rate != survey.sample_rate:
        scheme_kwargs["min_period"] = max(float(scheme_kwargs["min_period"]), rate_min_period(local_rate))

    try:
        raw_sites = survey.site_dirs()
    except OSError:  # data_root on a drive that is not plugged in
        raw_sites = {}
    use_filters = not args.no_filters
    local_h5 = default_archive_path(survey, args.local)
    # a stacked synthetic remote (scripts/build_stack.py), an observatory
    # (scripts/fetch_observatory.py) and a derived site (scripts/decimate_site.py)
    # have no raw folder: the archive is used as it is, with or without filters,
    # since it is a product rather than a `processing_archive` variant
    remote_parent = survey.parent_of(args.remote)
    stacked = survey.workspace / "mth5" / f"{args.remote}.h5"
    virtual = bool(remote_parent) or (args.remote not in raw_sites and stacked.exists())
    remote_h5 = stacked if virtual else default_archive_path(survey, args.remote)
    ignore_masks = not args.masks
    masks_local = [] if ignore_masks else load_masks(survey, args.local)
    # by name (`remote_masks`), not by `virtual`: with data_root unmounted every
    # remote that has an archive looks virtual, and its masks would be dropped
    masks_remote = [] if ignore_masks else remote_masks(survey, args.remote)
    tweaks = tweaks_from(args)
    engine = getattr(args, "engine", "aurora")
    if engine == "mantle":
        # MANTLE has its own estimator (DPSS multitaper, bounded-influence solve, block jackknife):
        # aurora's STFT and regression flags have no counterpart there, and masks act inside
        # aurora's kernel dataset and regression, so both are refused rather than silently dropped
        if tweaks:
            raise SystemExit(f"--engine mantle takes none of the aurora estimator flags (given: {sorted(tweaks)})")
        if masks_local or masks_remote:
            raise SystemExit(f"--engine mantle applies no masks.yaml entries yet ({args.local} {len(masks_local)}, "
                             f"{args.remote} {len(masks_remote)} declared): run it with --no-masks")

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
        "started": started,
        "tag": args.tag,
        "stem": run_stem(args.local, args.remote, started, args.tag),
        "scheme_kwargs": scheme_kwargs,
        # aurora estimates a TF row for every output channel it is asked for;
        # hz on a broadband site (no sensor, an open input) gives a meaningless
        # tipper, so the channels the survey declares are requested. A site
        # without a `channels:` declaration keeps aurora's default.
        "output_channels": output_channels(survey, args.local),
        # the advanced estimator flags given on the command line
        "tweaks": tweaks,
        "masks_local": masks_local,
        "masks_remote": masks_remote,
        "masks": union_masks(masks_local, masks_remote),
        "masks_ignored": ignore_masks,
        "engine": engine,
        "mantle_whiten": getattr(args, "mantle_whiten", "none"),
    }


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


class RateMismatch(ValueError):
    """Raised by `resolve` when the local and remote archives are at different sample rates."""


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


def mtproc_version() -> str:
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


def versions() -> dict:
    """Return the versions of mtproc and of aurora, mth5, mt_metadata and mt_io."""
    return {
        "mtproc": mtproc_version(),
        "aurora": _package_version("aurora"),
        "mth5": _package_version("mth5"),
        "mt_metadata": _package_version("mt_metadata"),
        "mt_io": _package_version("mt_io"),
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
        list | None: The entries, or None for a virtual or stacked remote,
        which has no raw folder and so no declaration of its own.
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


def build_sidecar(res: dict, args, started, finished, edi_path: Path, png_path: Path,
                   quadrant: dict, flipped: list[str]) -> dict:
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
        quadrant (dict): Return of `mtproc.compare.phase_quadrants`.
        flipped (list[str]): Modes judged out of quadrant.

    Returns:
        dict: The sidecar content.
    """
    survey = res["survey"]
    raw_sites = res["raw_sites"]
    local, remote = res["local"], res["remote"]
    return {
        "local": local,
        "remote": remote,
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "seconds": (finished - started).total_seconds(),
        "window": {"start": _utc_iso(args.start), "end": _utc_iso(args.end)},
        "local_archive": _archive_info(res["local_archive"]),
        "remote_archive": _archive_info(res["remote_archive"]),
        "survey_yaml": {"path": res["survey_yaml"], "name": Path(res["survey_yaml"]).name},
        # the rates the band scheme and quadrant window were built at (`local`),
        # and the derived sites' parents
        "sample_rates": {"survey": survey.sample_rate, "local": res.get("sample_rate", survey.sample_rate),
                         "remote": res.get("remote_sample_rate", survey.sample_rate)},
        "derived_from": {local: res.get("local_parent"), remote: res.get("remote_parent")},
        "band_scheme": dict(res["scheme_kwargs"]),
        # the full effective set, defaults filled in, so the sidecar says
        # "taper: hann" on a run without --taper too
        "tweaks": {**ESTIMATOR_DEFAULTS, **res["tweaks"]},
        "filters": {
            local: _declared_filters(survey, local, raw_sites),
            remote: _declared_filters(survey, remote, raw_sites),
        },
        # each site's masks.yaml entries, and the union actually applied (the key
        # the existing sidecar readers use)
        "masks_local": list(res.get("masks_local") or []),
        "masks_remote": list(res.get("masks_remote") or []),
        "masks": list(res.get("masks") or []),
        "masks_ignored": bool(res.get("masks_ignored")),
        "argv": list(sys.argv),
        "tag": res["tag"],
        "edi": edi_path.name,
        "figure": png_path.name,
        "quadrant": {
            "pmin": quadrant.get("pmin"), "pmax": quadrant.get("pmax"),
            "xy": quadrant.get("xy"), "yx": quadrant.get("yx"),
            "xy_ok": quadrant.get("xy_ok"), "yx_ok": quadrant.get("yx_ok"),
            "verdict": _quadrant_verdict(quadrant, flipped),
        },
        "versions": versions(),
    }


def write_sidecar(path: Path, sidecar: dict) -> None:
    """Write the sidecar as indented JSON."""
    path.write_text(json.dumps(sidecar, indent=2, default=str) + "\n", encoding="utf-8")


def edi_info_lines(sidecar: dict) -> list[str]:
    """Build a few `key=value` lines for the EDI's INFO block.

    `tf.station_metadata.transfer_function.processing_parameters` is a plain
    list of strings that mt_metadata's edi writer writes unchanged into
    `>INFO`. In mt_metadata 1.0.10, `station_metadata.comments` is used when
    reading an EDI but is absent from the write path. The lines point to the
    sidecar JSON, which holds the full record.

    Args:
        sidecar (dict): Output of `build_sidecar`.

    Returns:
        list[str]: The INFO lines.
    """
    lines = [
        f"mtproc.version={sidecar['versions']['mtproc']}",
        f"mtproc.started={sidecar['started']}",
        f"mtproc.tag={sidecar['tag'] or ''}",
    ]
    if sidecar.get("engine", "aurora") == "aurora":
        lines.append(f"mtproc.taper={sidecar['tweaks']['taper']}")
    else:
        lines += [f"mtproc.engine={sidecar['engine']}", f"mtproc.engine_version={sidecar['engine_version']}"]
    lines += [
        f"mtproc.quadrant_verdict={sidecar['quadrant']['verdict']}",
        f"mtproc.sidecar={sidecar['edi'].rsplit('.', 1)[0]}.json",
    ]
    return lines


def _print_archive_status(label: str, status: dict | None) -> None:
    """Print one archive status line.

    The line is "<label> archive: raw: <path>, variant: ready | to build
    (<hash>) | none declared | no filters used (--no-filters)", or "(no raw
    folder)" when `archive_status` returned None (a virtual or stacked
    remote, or unreadable `raw_sites`).
    """
    if status is None:
        print(f"{label} archive: (no raw folder)")
        return
    print(f"{label} archive: raw: {status['raw']}, variant: {status['variant_state']}")


def print_resolution(res: dict) -> None:
    """Print the resolution as `key: value` lines, as --dry-run and the log show it."""
    for key in ("survey_yaml", "local", "remote", "local_archive", "remote_archive",
                "virtual_remote", "ignore_filters", "start", "end", "window",
                "started", "tag", "stem", "engine"):
        value = res[key]
        if key == "started" and value is not None:
            value = value.isoformat()
        print(f"{key}: {value if value is not None else ''}")
    _print_archive_status("local", res["local_status"])
    _print_archive_status("remote", res["remote_status"])
    print(f"sample_rate: {res['local']} {res['sample_rate']:g} Hz, {res['remote']} {res['remote_sample_rate']:g} Hz")
    oc = res["output_channels"]
    print("output_channels: " + (", ".join(oc) if oc else "aurora default (ex, ey, hz)"))
    for key in BAND_KEYS:
        value = res["scheme_kwargs"][key]
        if key == "notch_frequencies":
            value = ", ".join(f"{f:g}" for f in value)
        print(f"{key}: {value}")
    extra = {k: v for k, v in res["scheme_kwargs"].items() if k not in BAND_KEYS}
    for key, value in extra.items():
        print(f"{key}: {value}")
    if res["masks_ignored"]:
        print("masks: ignored (--no-masks)")
    else:
        print(f"masks: {res['local']} {len(res['masks_local'])}, {res['remote']} "
              f"{len(res['masks_remote'])} ({len(res['masks'])} applied)")
    for key, value in res["tweaks"].items():
        print(f"tweak.{key}: {value}")
    if not res["tweaks"]:
        print("tweaks: none")
    if res["engine"] == "mantle":
        print(f"mantle.whiten: {res['mantle_whiten']}")


def main(args) -> None:
    """Process one pair and write the EDI, comparison figure and sidecar.

    Args:
        args (argparse.Namespace): Parsed arguments from `build_parser`.
    """
    started = dt.datetime.now().astimezone()
    try:
        res = resolve(args, started)
    except RateMismatch as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    survey = res["survey"]
    print_resolution(res)
    if args.dry_run:
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
            raise FileNotFoundError(f"{site}: no archive at {path} -- decimate {parent} first: "
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

    stem = res["stem"]
    scheme = build_band_scheme(res["sample_rate"], **res["scheme_kwargs"])
    masks = res["masks"]  # both sites' masks.yaml intervals, joined (`resolve`)
    if res["masks_ignored"]:
        logger.info(f"{local}, {remote}: masks.yaml ignored (--no-masks)")
    else:
        def all_band(declared):
            return sum(1 for m in declared if m["bands"] == "all")

        if res["masks_local"]:
            logger.info(f"{local}: {len(res['masks_local'])} mask(s) declared in masks.yaml "
                        f"({all_band(res['masks_local'])} all-band, applied as time cuts)")
        if res["masks_remote"]:
            logger.info(f"{remote} (remote): {len(res['masks_remote'])} mask(s) declared "
                        f"({all_band(res['masks_remote'])} all-band, applied as time cuts)")
            logger.info(f"{local} rr {remote}: {len(masks)} mask(s) applied (both sites' entries joined)")
    extras: dict = {}
    if res["engine"] == "mantle":
        # the second engine: the same archives and window, MANTLE's cascade, the EDI on the same
        # band grid; imported here so an aurora run needs no MANTLE install
        from mtproc import engine_mantle

        site_cfg = survey.site(local)
        tf, extras = engine_mantle.process_pair(
            local_h5, local, remote_h5, remote,
            survey_name=survey.name, latitude=site_cfg.latitude, longitude=site_cfg.longitude,
            elevation=site_cfg.elevation if site_cfg.elevation is not None else 0.0,
            out_dir=survey.workspace / "tf", stem=stem, scheme=scheme, start=args.start, end=args.end,
            options=engine_mantle.MantleOptions(whiten=res["mantle_whiten"]),
        )
        edi_path = survey.workspace / "tf" / f"{stem}.edi"
        tf.write(fn=edi_path, file_type="edi")
        logger.info(f"wrote {edi_path}")
    else:
        tf = process_station(
            local_h5, local, remote_h5, remote,
            out_dir=survey.workspace / "tf", band_scheme=scheme,
            start=args.start, end=args.end, tag=stem, tweaks=res["tweaks"] or None,
            time_masks=masks or None,
            **({"output_channels": res["output_channels"]} if res["output_channels"] else {}),
        )

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
    if flipped:
        logger.error(
            msg + f" — {' and '.join(flipped)} 180 deg out of quadrant: an E or H channel has the wrong sign. "
            "Declare `flip: {channels: [...]}` for the site on the Filter Data tab (or check "
            "flip_reversed_dipoles in survey.yaml), rebuild the archive and re-run."
        )
    elif q["reason"]:
        logger.warning(msg + f" — not judged: {q['reason']}; look at the EDI before trusting it")
    else:
        logger.info(msg + " (physical quadrants)")

    baseline = reference_edi(Path(args.survey_yaml), local)
    if baseline is None and res["local_parent"]:  # a derived site is compared with its parent's EDI
        baseline = reference_edi(Path(args.survey_yaml), res["local_parent"])
    if baseline is None:
        logger.warning(f"{local}: no reference EDI mapped — plotting aurora alone")
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
    sidecar = build_sidecar(res, args, started, finished, edi_path, out_png, q, flipped)
    sidecar.update(extras)  # the mantle engine's keys; an aurora run adds none
    sidecar_path = edi_path.with_suffix(".json")
    write_sidecar(sidecar_path, sidecar)
    logger.info(f"wrote {sidecar_path}")
    print(f"sidecar: {sidecar_path}")

    # a short pointer to the sidecar in the EDI's INFO block; the docstring of
    # edi_info_lines explains the use of `processing_parameters`
    try:
        tf.station_metadata.transfer_function.processing_parameters.extend(edi_info_lines(sidecar))
        tf.write(fn=edi_path, file_type="edi")
    except Exception as exc:
        logger.warning(f"{edi_path.name}: could not add the run's facts to the EDI's INFO block: {exc}")


if __name__ == "__main__":
    main(build_parser().parse_args())
