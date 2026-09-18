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
Each site's raw archive (`<site>.h5`, never filtered) is ingested once if it
is missing, then the site actually processed from is
`mtproc.ingest.processing_archive`: its filtered variant (`<site>_f<hash>.h5`,
built from the raw archive on demand when it is missing or its recorded hash
does not match the current `filters.yaml`) normally, or the raw archive
itself with `--no-filters` -- which is how you find out whether a filter was
worth declaring. `--tag` adds a suffix to the output name so those runs do
not overwrite each other, and `--dry-run` prints everything this run resolved
to — band kwargs, both sites' raw and variant archive status, window, product
stem — and exits without opening a single file (it never builds a variant).

The estimator flags (--taper ... --tolerance) are **advanced**: each changes
aurora's STFT or robust regression on every decimation level for this run
only (`mtproc.process.process_station(tweaks=...)`, whose docstring gives the
in-use default of each). Only the flags given become tweaks; with none the
run is exactly the default one, and the resolution says "tweaks: none".

Outputs: <workspace>/mth5/<site>.h5, <workspace>/tf/<stem>.edi,
<workspace>/tf/<stem>_vs_lemimt.png and <workspace>/tf/<stem>.json, where
<stem> is <local>_rr-<remote>_<YYYYMMDD-HHMM> (the LOCAL time this run
started, the machine clock at the top of `main`, formatted once and reused)
plus the --tag suffix when one was asked for. The processing window does not
appear in the name -- two runs of the same pair with the same window would
overwrite each other's EDI, while a run's own start, to the minute, never does.
The window (and everything else about the run: archives and their mtimes, the
band scheme and estimator tweaks actually used, both sites' declared filters,
the full argv, the phase-quadrant verdict and the package versions in play)
is in the `.json` sidecar next to the EDI instead; a short summary of the same
facts also goes into the EDI's own INFO block (`processing_parameters`).
"""

import argparse
import datetime as dt
import importlib.metadata
import inspect
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
import yaml
from loguru import logger

from mtproc.bands import lemimt_band_scheme
from mtproc.compare import phase_quadrants, plot_comparison
from mtproc.ingest import default_archive_path, filters_hash, ingest_site, processing_archive, variant_path, variant_ready
from mtproc.masks import load_masks
from mtproc.process import ESTIMATOR_DEFAULTS, TAPERS, process_station
from mtproc.survey import Survey

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
    p.add_argument("--notch", default=None, help='comma-separated Hz, e.g. "50,100" ("" for none)')
    p.add_argument("--no-filters", action="store_true",
                   help="process from the raw archive, not the filtered variant")
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


def run_stem(local: str, remote: str, started, suffix=None) -> str:
    """<local>_rr-<remote>_<YYYYMMDD-HHMM>[_<suffix>].

    The stamp is `started` (local time, the machine clock at the top of
    `main`, formatted once there and reused everywhere), not the processing
    window: two runs of the same pair over the same window would overwrite
    each other's EDI if the window were the only thing in the name besides
    the pair. A run's own start, to the minute, never repeats. The window
    itself lives in the `.json` sidecar next to the EDI, not in the file name.
    """
    stem = f"{local}_rr-{remote}_{pd.Timestamp(started).strftime('%Y%m%d-%H%M')}"
    if suffix:
        stem += f"_{str(suffix).strip().strip('_')}"
    return stem


def archive_status(survey: Survey, site: str, raw_sites: dict, use_filters: bool) -> dict | None:
    """{"raw", "variant", "variant_state"} for `site`, read-only -- never builds anything.

    None for a site not in `raw_sites` (a stacked/virtual remote, which has no
    raw archive of its own -- `resolve` handles that case separately).
    `variant` is None and `variant_state` "no filters used" with
    `use_filters=False`, or "none declared" when the site's `filters.yaml`
    entry is empty; otherwise `variant_path` and `variant_state` "ready" (the
    raw archive exists and `variant_ready`) or "to build (<hash>)".
    """
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
    """Everything this run decided, before anything is opened.

    The band kwargs are the survey's `processing:` block with the command
    line's overrides applied, filled out from `lemimt_band_scheme`'s own
    defaults so `--dry-run` always prints a number for each. `started` is the
    local wall-clock instant `main` began (`dt.datetime.now().astimezone()`),
    captured once there and threaded through here so the product stem and,
    later, the sidecar agree on exactly when this run started.

    `local_archive`/`remote_archive` are each site's RAW archive path
    (`default_archive_path`) -- read-only, so `--dry-run` never builds
    anything; `local_status`/`remote_status` (`archive_status`) say whether a
    filtered variant is ready, needs building, or is not in play. `main`
    resolves the archive actually processed from (`mtproc.ingest.processing_archive`,
    which does build) once `--dry-run` has returned, and overwrites these two
    entries with what was actually used before the sidecar is written.
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
        raw_sites = survey.site_dirs()
    except OSError:  # data_root on a drive that is not plugged in
        raw_sites = {}
    use_filters = not args.no_filters
    local_h5 = default_archive_path(survey, args.local)
    # a stacked synthetic remote (scripts/build_stack.py) has no raw folder:
    # its archive is used as it is, filters or no filters -- it is a product,
    # never a `processing_archive` variant
    stacked = survey.workspace / "mth5" / f"{args.remote}.h5"
    virtual = args.remote not in raw_sites and stacked.exists()
    remote_h5 = stacked if virtual else default_archive_path(survey, args.remote)

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
        "remote_status": None if virtual else archive_status(survey, args.remote, raw_sites, use_filters),
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


def quadrant_window(sample_rate: float) -> tuple[float, float]:
    """(pmin, pmax) s for `phase_quadrants`, picked from the local site's sample rate.

    0.1-10 s at 100 Hz and above (the broadband deployments this window was
    tuned on); 30-3000 s below that. The 0.1-10 s band is pure noise on a
    10 Hz long-period deployment and raised a false "180 deg out ... declare
    flip" on Stuart Shelf ST19 and ST20.
    """
    return (0.1, 10.0) if sample_rate >= 100.0 else (30.0, 3000.0)


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def mtproc_version() -> str:
    """This checkout's `git describe`, or "uncommitted <short sha>" when the tree has local changes."""

    def git(*args: str) -> str:
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
    """mtproc's own version plus the four libraries doing the actual estimation/IO."""
    return {
        "mtproc": mtproc_version(),
        "aurora": _package_version("aurora"),
        "mth5": _package_version("mth5"),
        "mt_metadata": _package_version("mt_metadata"),
        "mt_io": _package_version("mt_io"),
    }


def _archive_info(path) -> dict:
    """{"path", "mtime"} for a sidecar archive entry; mtime None when the file is not there."""
    path = Path(path)
    mtime = None
    if path.exists():
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).isoformat()
    return {"path": str(path), "mtime": mtime}


def _utc_iso(t) -> str | None:
    return None if t is None else pd.Timestamp(t, tz="UTC").isoformat()


def _declared_filters(survey, site: str, raw_sites) -> list | None:
    """`site`'s declared `filters.yaml` entries, or None for a virtual/stacked remote
    (it has no raw folder and so no declaration of its own -- see `main`'s own guard)."""
    if site not in raw_sites:
        return None
    return survey.site(site).filters or []


def _quadrant_verdict(quadrant: dict, flipped: list[str]) -> str:
    if flipped:
        return f"flipped: {' and '.join(flipped)} 180 deg out of quadrant"
    if quadrant.get("reason"):
        return f"not judged: {quadrant['reason']}"
    return "physical quadrants"


def build_sidecar(res: dict, args, started, finished, edi_path: Path, png_path: Path,
                   quadrant: dict, flipped: list[str]) -> dict:
    """Everything about this run, for the `.json` sidecar written next to the EDI.

    `quadrant` is `mtproc.compare.phase_quadrants`'s own return and `flipped`
    the modes `main` judged out of quadrant from it -- both computed by the
    caller, so this stays a pure dict-builder: a unit test can push a fake TF
    through `phase_quadrants` alone and hand the result straight in, without
    building a real aurora run.
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
        "band_scheme": dict(res["scheme_kwargs"]),
        # the full effective set, defaults filled in -- so the sidecar says
        # "taper: hann" even on a run that gave no --taper at all
        "tweaks": {**ESTIMATOR_DEFAULTS, **res["tweaks"]},
        "filters": {
            local: _declared_filters(survey, local, raw_sites),
            remote: _declared_filters(survey, remote, raw_sites),
        },
        "masks": list(res.get("masks") or []),
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
    path.write_text(json.dumps(sidecar, indent=2, default=str) + "\n", encoding="utf-8")


def edi_info_lines(sidecar: dict) -> list[str]:
    """A handful of `key=value` lines for the EDI's own INFO block.

    `tf.station_metadata.transfer_function.processing_parameters` is a plain
    list of strings mt_metadata's edi writer dumps verbatim into `>INFO`
    (checked against mt_metadata 1.0.10: `station_metadata.comments` is
    *not* wired into the write path -- only into reading an EDI back in --
    so that route was tried and dropped for this one). The sidecar JSON
    carries everything else; this is a short pointer to it, not a copy.
    """
    tw = sidecar["tweaks"]
    return [
        f"mtproc.version={sidecar['versions']['mtproc']}",
        f"mtproc.started={sidecar['started']}",
        f"mtproc.tag={sidecar['tag'] or ''}",
        f"mtproc.taper={tw['taper']}",
        f"mtproc.quadrant_verdict={sidecar['quadrant']['verdict']}",
        f"mtproc.sidecar={sidecar['edi'].rsplit('.', 1)[0]}.json",
    ]


def _print_archive_status(label: str, status: dict | None) -> None:
    """"<label> archive: raw: <path>, variant: ready | to build (<hash>) | none declared |
    no filters used (--no-filters)"; "(no raw folder)" when `archive_status` returned
    None -- a virtual/stacked remote, or `raw_sites` itself could not be read."""
    if status is None:
        print(f"{label} archive: (no raw folder)")
        return
    print(f"{label} archive: raw: {status['raw']}, variant: {status['variant_state']}")


def print_resolution(res: dict) -> None:
    """`key: value` lines — what --dry-run prints, and what the log opens with."""
    for key in ("survey_yaml", "local", "remote", "local_archive", "remote_archive",
                "virtual_remote", "ignore_filters", "start", "end", "window",
                "started", "tag", "stem"):
        value = res[key]
        if key == "started" and value is not None:
            value = value.isoformat()
        print(f"{key}: {value if value is not None else ''}")
    _print_archive_status("local", res["local_status"])
    _print_archive_status("remote", res["remote_status"])
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
    started = dt.datetime.now().astimezone()
    res = resolve(args, started)
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
    # the raw archive first (ingest_site reuses it if it is already there),
    # then the archive processing actually reads: the filtered variant,
    # built from the raw one on demand, or the raw archive itself with
    # --no-filters (`processing_archive`)
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
    scheme = lemimt_band_scheme(survey.sample_rate, **res["scheme_kwargs"])
    masks = load_masks(survey, local)  # the student's masks.yaml intervals for this site
    res["masks"] = masks
    if masks:
        logger.info(f"{local}: {len(masks)} mask(s) declared in masks.yaml "
                    f"({sum(1 for m in masks if m.get('bands', 'all') == 'all')} all-band, applied as time cuts)")
    tf = process_station(
        local_h5, local, remote_h5, remote,
        out_dir=survey.workspace / "tf", band_scheme=scheme,
        start=args.start, end=args.end, tag=stem, tweaks=res["tweaks"] or None,
        time_masks=masks or None,
        **({"output_channels": res["output_channels"]} if res["output_channels"] else {}),
    )

    pmin, pmax = quadrant_window(survey.sample_rate)
    logger.info(
        f"{local}: judging phase quadrants over {pmin:g}-{pmax:g} s "
        f"(sample rate {survey.sample_rate:g} Hz)"
    )
    q = phase_quadrants(tf, pmin=pmin, pmax=pmax)
    msg = f"{local}: median phases {q['pmin']:g}-{q['pmax']:g} s xy {q['xy']:+.0f} deg, yx {q['yx']:+.0f} deg"
    # a mode with too few usable periods is not judged (nan): that is "undetermined",
    # not "flipped" -- only a judged mode outside its quadrant is a sign error
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
    if baseline is None:
        logger.warning(f"{local}: no reference EDI mapped — plotting aurora alone")
    out_png = survey.workspace / "tf" / f"{stem}_vs_lemimt.png"
    plot_comparison(
        tf, baseline=baseline,
        title=f"{local} RR {remote} — aurora vs lemimt ({res['window']})",
        out_png=out_png,
    )
    logger.info(f"wrote {out_png}")
    print(f"comparison figure: {out_png}")

    finished = dt.datetime.now().astimezone()
    edi_path = survey.workspace / "tf" / f"{stem}.edi"
    sidecar = build_sidecar(res, args, started, finished, edi_path, out_png, q, flipped)
    sidecar_path = edi_path.with_suffix(".json")
    write_sidecar(sidecar_path, sidecar)
    logger.info(f"wrote {sidecar_path}")
    print(f"sidecar: {sidecar_path}")

    # a short pointer to the sidecar, in the EDI's own INFO block -- see
    # edi_info_lines' docstring for why this is `processing_parameters`
    # and not `station_metadata.comments`
    try:
        tf.station_metadata.transfer_function.processing_parameters.extend(edi_info_lines(sidecar))
        tf.write(fn=edi_path, file_type="edi")
    except Exception as exc:
        logger.warning(f"{edi_path.name}: could not add the run's facts to the EDI's INFO block: {exc}")


if __name__ == "__main__":
    main(build_parser().parse_args())
