# -*- coding: utf-8 -*-
"""
Ingest one site into its MTH5 archive and filtered variant

Ingests one site's raw files into its MTH5 archive and builds its filtered
variant, in the same way as process_rr.py. The raw archive is
``<workspace>/mth5/<site>.h5`` (`mtproc.ingest.ingest_site`). It uses the run
length of process_rr.py's MAX_RUN_FILES, imported from it (34 files of 90
min, 51 h per run, unless --max-run-files), and the naming of
`mtproc.ingest.default_archive_path`, so process_rr.py reuses an archive
built here. The whole deployment goes into the raw archive; the processing
window is chosen in process_rr.py. The site's recorder is
`Survey.instrument_of(site)` (LEMI-423, LEMI-424 or Earth Data PR6-24,
`mtproc.instruments`). --max-run-files counts B423 files, caps LEMI-423 runs
only and applies to the raw archive alone.

With no flag, and when the site declares filters in <survey>/filters.yaml,
the script also builds the filtered variant ``<site>_f<hash>.h5``
(`mtproc.ingest.build_variant`) on top of the raw archive. `--raw` builds the
raw archive only; filters are applied to the variant alone. `--variant`
builds the variant only, from an existing raw archive.

Prints "archive: <path>" for the raw step and "variant: <path>" for the
variant step (or "variant: none (no declared filters)"). An existing raw
archive is rebuilt only with --force, since every transfer function of the
site may have been made from it. A variant already current for the site's
declared filters (`mtproc.ingest.variant_ready`) is likewise kept unless
--force is given. A run that fails part-way removes the partial file it was
writing. The Time Series tab of the GUI runs this script (no flags) from its
"Build MTH5" button for a site without an archive.

Usage:
    python scripts/ingest_site.py <survey.yaml> <site>
        [--raw | --variant] [--max-run-files N] [--force]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from mtproc.ingest import build_variant, default_archive_path, ingest_site, variant_path, variant_ready  # noqa: E402
from mtproc.survey import Survey  # noqa: E402
from process_rr import MAX_RUN_FILES  # noqa: E402  (shared with process_rr.py)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of ingest_site.py."""
    p = argparse.ArgumentParser(prog="ingest_site.py",
                                description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("site")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--raw", action="store_true", help="raw archive only, no variant build")
    group.add_argument("--variant", action="store_true", help="filtered variant only, from an existing raw archive")
    p.add_argument("--max-run-files", type=int, default=MAX_RUN_FILES,
                   help=f"B423 files per run at most, LEMI-423 only (default {MAX_RUN_FILES}, as process_rr.py)")
    p.add_argument("--force", action="store_true", help="rebuild a raw archive or variant that is already current")
    return p


def _remove_partial(path: Path) -> None:
    """Delete a partly written archive, if present, and report it on stderr."""
    if path.exists():
        path.unlink()
        print(f"removed the partial {path}", file=sys.stderr)


def main(argv=None) -> int:
    """Build the raw archive and/or the filtered variant of one site.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 1 when the site has no raw-file folder, 2 when
        the raw archive exists and --force was not given.
    """
    args = build_parser().parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    raw_sites = survey.site_dirs()
    if args.site not in raw_sites:
        print(f"ERROR {args.site}: no folder of raw files (B423, LEMI-424 .txt, EDL) under {survey.data_root}",
              file=sys.stderr)
        return 1

    if not args.variant:
        out = default_archive_path(survey, args.site)
        if out.exists() and not args.force:
            print(f"ERROR {out} exists: pass --force to rebuild it", file=sys.stderr)
            return 2
        print(f"ingesting {args.site} ({survey.instrument_of(args.site)}) from {raw_sites[args.site]} "
              f"(LEMI-423 runs of at most {args.max_run_files} files) -> {out}", flush=True)
        try:
            path = ingest_site(survey, args.site, overwrite=args.force, max_run_files=args.max_run_files)
        except BaseException:
            _remove_partial(out)
            raise
        print(f"archive: {path}")

    if not args.raw:
        declared = survey.site(args.site).filters or []
        if not declared:
            print("variant: none (no declared filters)")
        elif not args.force and variant_ready(survey, args.site):
            print(f"variant: {variant_path(survey, args.site)} (already current)")
        else:
            vpath = variant_path(survey, args.site)
            print(f"building {args.site}'s variant ({len(declared)} declared filter(s)) -> {vpath}", flush=True)
            try:
                built = build_variant(survey, args.site)
            except BaseException:
                _remove_partial(vpath)
                raise
            print(f"variant: {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
