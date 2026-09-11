"""Ingest a local and a remote site, estimate the remote-referenced TF, and
overlay it on the legacy lemimt EDI when the survey maps one.

Usage:
    python scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end]
        [--min-period S] [--max-period S] [--per-decade N] [--notch "50,150"]
        [--no-filters] [--tag SUFFIX] [--dry-run]
        [--taper {boxcar,hamming,hann,dpss}] [--overlap PCT] [--no-prewhiten]
        [--min-windows N] [--max-iterations N] [--redescending-iterations N]
        [--r0 X] [--u0 X] [--tolerance X]

Each site's whole deployment is ingested once (one MTH5 per site holds all its
runs; later runs against other partners reuse it). `start`/`end` (UTC, e.g.
"2018-06-22 21:40") are a *processing window* applied to the aurora kernel
dataset, not to the archive — use them to keep a bad stretch out of the
estimate (Burra35's Ex died 16.5 h in). Without them aurora works on the full
time overlap. Long deployments are split into runs of at most MAX_RUN_FILES
files to bound memory; at 90 min per file that is still ~2 days per run.

The band options override the survey's `processing:` block **for this run
only**, so two band layouts can be compared without editing the YAML;
`--notch` is a comma-separated list of Hz (`--notch ""` clears the survey's).
`--no-filters` ingests both sites with their declared filters skipped, into
`<site>_unfiltered.h5` archives (`bbmt.ingest.ingest_site(ignore_filters=True)`),
which is how you find out whether a filter was worth declaring. `--tag` adds a
suffix to the output name so those runs do not overwrite each other, and
`--dry-run` prints everything this run resolved to — band kwargs, archive
paths, window, tag — and exits without opening a single file.

The estimator flags (--taper ... --tolerance) are **advanced**: each changes
aurora's STFT or robust regression on every decimation level for this run
only (`bbmt.process.process_station(tweaks=...)`, whose docstring gives the
in-use default of each). Only the flags given become tweaks; with none the
run is exactly the default one, and the resolution says "tweaks: none".

Outputs: <workspace>/mth5/<site>.h5, <workspace>/tf/<tag>.edi and
<workspace>/tf/<tag>_vs_lemimt.png, where <tag> is <local>_rr-<remote> plus a
compact window suffix when a window was given and the --tag suffix when one
was asked for.
"""

import argparse
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
import yaml
from loguru import logger

from bbmt.bands import lemimt_band_scheme
from bbmt.compare import phase_quadrants, plot_comparison
from bbmt.ingest import default_archive_path, ingest_site
from bbmt.process import TAPERS, process_station
from bbmt.survey import Survey

MAX_RUN_FILES = 34  # 34 x 90 min = 51 h per run
# the band-scheme keys this CLI can override; anything else in the survey's
# `processing:` block (window, factor, notch_fraction) is passed through
BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="process_rr.py",
        description=__doc__.split("\n\nUsage:")[0],
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
    p.add_argument("--notch", default=None, help='comma-separated Hz, e.g. "50,150" ("" for none)')
    p.add_argument("--no-filters", action="store_true",
                   help="ingest both sites with their declared filters skipped (_unfiltered archives)")
    p.add_argument("--tag", default=None, help="suffix appended to the output tag")
    p.add_argument("--dry-run", action="store_true",
                   help="print what this run resolved to and exit, opening nothing")
    adv = p.add_argument_group("advanced: the aurora estimator, on every decimation level")
    adv.add_argument("--taper", choices=TAPERS, default=None, help="STFT window (in use: boxcar)")
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
    return p


def tweaks_from(args) -> dict:
    """The estimator flags actually given, as `process_station(tweaks=...)` keys; {} for none."""
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
    """'50, 150' -> (50.0, 150.0); '' -> () (no notches at all)."""
    return tuple(float(part) for part in str(text).split(",") if part.strip())


def reference_edi(survey_yaml: Path, site: str):
    ref_yaml = Path(survey_yaml).parent / "reference_edis.yaml"
    if not ref_yaml.exists():
        return None
    mapping = yaml.safe_load(ref_yaml.read_text(encoding="utf-8")) or {}
    return (mapping.get(site) or {}).get("edi")


def window_tag(local: str, remote: str, start, end, suffix=None) -> str:
    """<local>_rr-<remote>[_w<start>-<end>][_<suffix>]."""
    tag = f"{local}_rr-{remote}"
    if start or end:
        fmt = lambda t: pd.Timestamp(t).strftime("%Y%m%dT%H%M") if t else "open"
        tag += f"_w{fmt(start)}-{fmt(end)}"
    if suffix:
        tag += f"_{str(suffix).strip().strip('_')}"
    return tag


def resolve(args) -> dict:
    """Everything this run decided, before anything is opened.

    The band kwargs are the survey's `processing:` block with the command
    line's overrides applied, filled out from `lemimt_band_scheme`'s own
    defaults so `--dry-run` always prints a number for each.
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
    defaults = {n: p.default for n, p in inspect.signature(lemimt_band_scheme).parameters.items()}
    for key in BAND_KEYS:
        scheme_kwargs.setdefault(key, defaults[key])

    try:
        raw_sites = set(survey.site_dirs())
    except OSError:  # data_root on a drive that is not plugged in
        raw_sites = set()
    ignore = bool(args.no_filters)
    local_h5 = default_archive_path(survey, args.local, ignore)
    # a stacked synthetic remote (scripts/build_stack.py) has no raw folder:
    # its archive is used as it is, filters or no filters
    stacked = survey.workspace / "mth5" / f"{args.remote}.h5"
    virtual = args.remote not in raw_sites and stacked.exists()
    remote_h5 = stacked if virtual else default_archive_path(survey, args.remote, ignore)

    return {
        "survey": survey,
        "survey_yaml": str(Path(args.survey_yaml)),
        "local": args.local,
        "remote": args.remote,
        "virtual_remote": virtual,
        "local_archive": local_h5,
        "remote_archive": remote_h5,
        "ignore_filters": ignore,
        "start": args.start,
        "end": args.end,
        "window": (f"{args.start or 'start'} to {args.end or 'end'} UTC"
                   if (args.start or args.end) else "full overlap"),
        "tag": window_tag(args.local, args.remote, args.start, args.end, args.tag),
        "scheme_kwargs": scheme_kwargs,
        # aurora estimates a TF row for every output channel it is asked for;
        # asking for hz on a broadband site (no sensor, an open input) made a
        # nonsense tipper, so only the channels the survey declares are asked
        # for. A site with no `channels:` declaration keeps aurora's default.
        "output_channels": output_channels(survey, args.local),
        # only the advanced estimator flags given on the command line
        "tweaks": tweaks_from(args),
    }


def output_channels(survey, site: str) -> list[str] | None:
    """The TF output channels for `site`: the electrics it declares, plus hz only
    when the survey lists an hz channel (never on the broadband deployments)."""
    declared = survey.site(site).channels
    if not declared:
        return None
    declared = [c.lower() for c in declared]
    return [c for c in ("ex", "ey", "hz") if c in declared]


def print_resolution(res: dict) -> None:
    """`key: value` lines — what --dry-run prints, and what the log opens with."""
    for key in ("survey_yaml", "local", "remote", "local_archive", "remote_archive",
                "virtual_remote", "ignore_filters", "start", "end", "window", "tag"):
        print(f"{key}: {res[key] if res[key] is not None else ''}")
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
    for key, value in res["tweaks"].items():
        print(f"tweak.{key}: {value}")
    if not res["tweaks"]:
        print("tweaks: none")


def main(args) -> None:
    res = resolve(args)
    survey = res["survey"]
    print_resolution(res)
    if args.dry_run:
        return

    raw_sites = survey.site_dirs()
    local, remote = res["local"], res["remote"]
    ignore = res["ignore_filters"]
    for site in (local, remote):
        if site not in raw_sites:
            continue
        cfg = survey.site(site)
        logger.info(
            f"{site}: Ex {cfg.dipole_length_ex} m @ {cfg.azimuth_ex} deg, "
            f"Ey {cfg.dipole_length_ey} m @ {cfg.azimuth_ey} deg, timing {cfg.timing}"
        )
    local_h5 = ingest_site(survey, local, max_run_files=MAX_RUN_FILES, ignore_filters=ignore)
    if res["virtual_remote"]:
        logger.info(f"{remote}: virtual remote, using {res['remote_archive']}")
        remote_h5 = res["remote_archive"]
    else:
        remote_h5 = ingest_site(survey, remote, max_run_files=MAX_RUN_FILES, ignore_filters=ignore)

    tag = res["tag"]
    scheme = lemimt_band_scheme(survey.sample_rate, **res["scheme_kwargs"])
    tf = process_station(
        local_h5, local, remote_h5, remote,
        out_dir=survey.workspace / "tf", band_scheme=scheme,
        start=args.start, end=args.end, tag=tag, tweaks=res["tweaks"] or None,
        **({"output_channels": res["output_channels"]} if res["output_channels"] else {}),
    )

    q = phase_quadrants(tf)
    msg = f"{local}: short-period phases xy {q['xy']:+.0f} deg, yx {q['yx']:+.0f} deg"
    if q["xy_ok"] and q["yx_ok"]:
        logger.info(msg + " (physical quadrants)")
    else:
        logger.error(
            msg + " — a mode is 180 deg out: an E or H channel has the wrong sign. "
            "Check dipole polarity (flip_reversed_dipoles in survey.yaml) and re-ingest."
        )

    baseline = reference_edi(Path(args.survey_yaml), local)
    if baseline is None:
        logger.warning(f"{local}: no reference EDI mapped — plotting aurora alone")
    out_png = survey.workspace / "tf" / f"{tag}_vs_lemimt.png"
    plot_comparison(
        tf, baseline=baseline,
        title=f"{local} RR {remote} — aurora vs lemimt ({res['window']})",
        out_png=out_png,
    )
    print(f"comparison figure: {out_png}")


if __name__ == "__main__":
    main(build_parser().parse_args())
