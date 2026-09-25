# -*- coding: utf-8 -*-
"""
Ingest sites into their MTH5 archives and filtered variants

Ingests a site's raw files into its MTH5 archive and builds its filtered
variant, in the same way as process_rr.py. The raw archive is
``<workspace>/mth5/<site>.h5`` (`crust.ingest.ingest_site`). It uses the run
length of process_rr.py's MAX_RUN_FILES, imported from it (34 files of 90
min, 51 h per run, unless --max-run-files), and the naming of
`crust.ingest.default_archive_path`, so process_rr.py reuses an archive
built here. The whole deployment goes into the raw archive; the processing
window is chosen in process_rr.py. The site's recorder is
`Survey.instrument_of(site)` (LEMI-423, LEMI-424 or Earth Data PR6-24,
`crust.instruments`). --max-run-files counts B423 files, caps LEMI-423 runs
only and applies to the raw archive alone.

With no flag, and when the site declares filters in <survey>/filters.yaml,
the script also builds the filtered variant ``<site>_f<hash>.h5``
(`crust.ingest.build_variant`) on top of the raw archive. `--raw` builds the
raw archive only; filters are applied to the variant alone. `--variant`
builds the variant only, from an existing raw archive.

For one site the script prints "archive: <path>" for the raw step and
"variant: <path>" for the variant step (or "variant: none (no declared
filters)"). An existing raw archive is rebuilt only with --force, since
every transfer function of the site may have been made from it. A variant
already current for the site's declared filters
(`crust.ingest.variant_ready`) is likewise kept unless --force is given. A
run that fails part-way removes the partial file it was writing. The Time
Series tab of the GUI runs this script (no flags) from its "Build MTH5"
button for a site without an archive.

Several sites, or --all, make a batch. --all takes every site of
survey.yaml that has a raw data folder (`Survey.site_dirs`) and lists the
sites it skips: declared sites without a raw folder, and raw folders missing
from survey.yaml. In a batch each site keeps an existing raw archive
(rebuilt with --force) and goes on to its variant step, and --raw,
--variant, --max-run-files and --force apply to every site. --parallel N
builds N sites at once, each in a process of its own that runs this script
for that one site, with its output written to
``<workspace>/logs/ingest_<site>.log``; with the default of 1 the sites are
built one after another in this process, their output on the console. A
site that fails is reported and the batch goes on with the next. The batch
ends with a table of each site's archive, variant, seconds and status
(built, kept, or failed with the first line of its error) and exits with 1
when a site failed, 0 otherwise. Ctrl+C stops the batch, kills the running
processes and removes their partial archives.

Usage:
    python scripts/ingest_site.py <survey.yaml> <site> [<site> ...]
        [--raw | --variant] [--max-run-files N] [--force] [--parallel N]
    python scripts/ingest_site.py <survey.yaml> --all
        [--raw | --variant] [--max-run-files N] [--force] [--parallel N]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from crust.ingest import build_variant, default_archive_path, ingest_site, variant_path, variant_ready  # noqa: E402
from crust.survey import Survey  # noqa: E402
from process_rr import MAX_RUN_FILES  # noqa: E402  (shared with process_rr.py)

POLL_S = 0.25  # how often a batch checks its running processes
# the last line of a traceback ("ValueError: ..."), or this script's own "ERROR ..." line
ERROR_LINE = re.compile(r"^(?:[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit)\b.*|ERROR .+)$")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of ingest_site.py."""
    p = argparse.ArgumentParser(prog="ingest_site.py",
                                description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("sites", nargs="*", metavar="site", help="one site, or several for a batch")
    p.add_argument("--all", action="store_true",
                   help="a batch of every site of survey.yaml that has a raw data folder")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--raw", action="store_true", help="raw archive only, no variant build")
    group.add_argument("--variant", action="store_true", help="filtered variant only, from an existing raw archive")
    p.add_argument("--max-run-files", type=int, default=MAX_RUN_FILES,
                   help=f"B423 files per run at most, LEMI-423 only (default {MAX_RUN_FILES}, as process_rr.py)")
    p.add_argument("--force", action="store_true", help="rebuild a raw archive or variant that is already current")
    p.add_argument("--parallel", type=int, default=1, metavar="N",
                   help="sites of a batch built at once, each in its own process with a log in "
                        "<workspace>/logs (default 1: one after another in this process)")
    return p


def _remove_partial(path: Path) -> None:
    """Delete a partly written archive, if present, and report it on stderr."""
    if path.exists():
        path.unlink()
        print(f"removed the partial {path}", file=sys.stderr)


class SiteJob:
    """One site of a batch: the steps it needs and how they went.

    Args:
        site (str): Site name.

    Attributes:
        flags (list[str]): The single-site flags of this script that build it.
        raw_step (bool): Whether the raw archive is to be built.
        variant_step (bool): Whether the variant is to be built.
        archive (str): The summary's archive cell.
        variant (str): The summary's variant cell.
        status (str): "built", "kept" or "failed"; "" while it waits.
        error (str): First line of the error of a failed site.
        seconds (float): Time the site took.
        log (Path | None): The site's log file, in a parallel batch.
    """

    def __init__(self, site: str):
        self.site = site
        self.flags: list[str] = []
        self.raw_step = False
        self.variant_step = False
        self.archive = "-"
        self.variant = "-"
        self.status = ""
        self.error = ""
        self.seconds = 0.0
        self.log: Path | None = None


def plan_site(survey: Survey, site: str, raw_sites: dict, args: argparse.Namespace) -> SiteJob:
    """Decide the steps one site of a batch needs.

    Args:
        survey (Survey): The survey.
        site (str): Site name.
        raw_sites (dict): `Survey.site_dirs` of the survey.
        args (argparse.Namespace): The batch's parsed arguments.

    Returns:
        SiteJob: Status "kept" when the site has nothing to build, "failed"
        when it has no raw data folder, "" otherwise.
    """
    job = SiteJob(site)
    if site not in raw_sites:
        job.status = "failed"
        job.error = f"no folder of raw files (B423, LEMI-424 .txt, EDL) under {survey.data_root}"
        return job
    archive = default_archive_path(survey, site)
    if not args.variant:
        job.raw_step = args.force or not archive.exists()
        job.archive = f"{archive.name} {'built' if job.raw_step else 'kept'}"
    if not args.raw:
        if not survey.site(site).filters:
            job.variant = "none"
        elif not args.force and variant_ready(survey, site):
            job.variant = f"{variant_path(survey, site).name} kept"
        else:
            job.variant_step = True
            job.variant = f"{variant_path(survey, site).name} built"
    if job.raw_step:
        job.flags = (["--raw"] if args.raw else []) + ["--max-run-files", str(args.max_run_files)]
    elif job.variant_step:
        job.flags = ["--variant"]
    else:
        job.status = "kept"
    if args.force:
        job.flags.append("--force")
    return job


def _first_line(exc: BaseException) -> str:
    """Return an exception as "<type>: <first line of its message>", as a traceback ends."""
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0]}" if lines else type(exc).__name__


def _settle(job: SiteJob, survey: Survey) -> None:
    """Set a failed site's summary cells from the files its steps left."""
    if job.raw_step and not default_archive_path(survey, job.site).exists():
        job.archive = "-"
    if job.variant_step:
        job.variant = "-"


def _report(job: SiteJob) -> None:
    """Print the one line that closes a site of a batch."""
    tail = f": {job.error}" if job.error else ""
    where = f" (log {job.log})" if job.log and job.status == "failed" else ""
    print(f"{job.site}: {job.status} in {job.seconds:.1f} s{tail}{where}", flush=True)


def run_here(jobs: list[SiteJob], args: argparse.Namespace, survey: Survey) -> bool:
    """Build the sites one after another in this process, their output on the console.

    Args:
        jobs (list[SiteJob]): The sites to build.
        args (argparse.Namespace): The batch's parsed arguments.
        survey (Survey): The survey.

    Returns:
        bool: True when Ctrl+C stopped the batch.
    """
    for k, job in enumerate(jobs, 1):
        print(f"[{k}/{len(jobs)}] {job.site}", flush=True)
        start = time.perf_counter()
        stopped = False
        try:
            code = main([str(args.survey_yaml), job.site, *job.flags])
        except KeyboardInterrupt:
            stopped = True
            job.status, job.error = "failed", "KeyboardInterrupt: stopped"
            for rest in jobs[k:]:
                rest.status, rest.error = "failed", "stopped before it started"
                _settle(rest, survey)
        except (Exception, SystemExit) as exc:
            traceback.print_exc()
            job.status, job.error = "failed", _first_line(exc)
        else:
            job.status = "built" if code == 0 else "failed"
            job.error = "" if code == 0 else f"exit code {code}"
        job.seconds = time.perf_counter() - start
        if job.status == "failed":
            _settle(job, survey)
        _report(job)
        if stopped:
            return True
    return False


def _close_child(job: SiteJob, returncode: int | None, seconds: float, survey: Survey) -> None:
    """Record how a site's process ended, from its exit code and its log.

    A process that ended inside the raw step (its log has the "ingesting"
    line and no "archive:" line) has its archive removed, as the script
    itself does on an error, and a variant's ``.part`` file is removed too.

    Args:
        job (SiteJob): The site.
        returncode (int | None): The process's exit code; None when the
            batch killed it.
        seconds (float): Time the site took.
        survey (Survey): The survey.
    """
    text = job.log.read_text(encoding="utf-8", errors="replace") if job.log and job.log.exists() else ""
    job.seconds = seconds
    if returncode == 0:
        want = [line for line, needed in (("archive:", "--variant" not in job.flags),
                                          ("variant:", "--raw" not in job.flags)) if needed]
        missing = [line for line in want if not re.search(rf"^{line} ", text, re.M)]
        job.status = "failed" if missing else "built"
        job.error = f"exit 0 without the {' and '.join(repr(m) for m in missing)} line" if missing else ""
    else:
        lines = [ln.strip() for ln in text.splitlines() if ERROR_LINE.match(ln.strip())]
        job.status = "failed"
        job.error = ("KeyboardInterrupt: stopped" if returncode is None
                     else lines[-1] if lines else f"exit code {returncode}")
        partial = []
        if (job.raw_step and not re.search(r"^archive: ", text, re.M)
                and re.search(rf"^ingesting {re.escape(job.site)} ", text, re.M)):
            partial.append(default_archive_path(survey, job.site))
        if job.variant_step:
            vpath = variant_path(survey, job.site)
            partial.append(vpath.with_name(vpath.name + ".part"))
        for path in partial:
            try:
                _remove_partial(path)
            except OSError as exc:
                print(f"could not remove the partial {path}: {exc}", file=sys.stderr)
    if job.status == "failed":
        _settle(job, survey)
    _report(job)


def run_children(jobs: list[SiteJob], args: argparse.Namespace, survey: Survey) -> bool:
    """Build the sites `args.parallel` at a time, each in a process running this script for it.

    Each process writes its output to ``<workspace>/logs/ingest_<site>.log``.

    Args:
        jobs (list[SiteJob]): The sites to build.
        args (argparse.Namespace): The batch's parsed arguments.
        survey (Survey): The survey.

    Returns:
        bool: True when Ctrl+C stopped the batch.
    """
    log_dir = survey.workspace / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    script = str(Path(__file__).resolve())
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    pending = list(jobs)
    running: dict[subprocess.Popen, tuple[SiteJob, object, float]] = {}
    try:
        while pending or running:
            while pending and len(running) < args.parallel:
                job = pending.pop(0)
                job.log = log_dir / f"ingest_{job.site}.log"
                handle = open(job.log, "wb")
                argv = [sys.executable, script, str(args.survey_yaml), job.site, *job.flags]
                proc = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, env=env)
                running[proc] = (job, handle, time.perf_counter())
                print(f"{job.site}: started, log {job.log}", flush=True)
            done = [proc for proc in running if proc.poll() is not None]
            for proc in done:
                job, handle, start = running.pop(proc)
                handle.close()
                _close_child(job, proc.returncode, time.perf_counter() - start, survey)
            if not done:
                time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("Ctrl+C: stopping the batch", flush=True)
        for proc, (job, handle, start) in running.items():
            code = proc.poll()
            if code is None:
                proc.kill()
                proc.wait()
            handle.close()
            _close_child(job, code, time.perf_counter() - start, survey)
        for job in pending:
            job.status, job.error = "failed", "stopped before it started"
            _settle(job, survey)
        return True
    return False


def print_summary(jobs: list[SiteJob], survey: Survey) -> None:
    """Print the batch's table: site, archive, variant, seconds and status."""
    head = ("site", "archive", "variant", "seconds", "status")
    rows = [(j.site, j.archive, j.variant, f"{j.seconds:.1f}", f"{j.status}: {j.error}" if j.error else j.status)
            for j in jobs]
    widths = [max(len(r[i]) for r in (head, *rows)) for i in range(4)]
    print(f"\nsummary (archives in {survey.workspace / 'mth5'})")
    for r in (head, *rows):
        print("  ".join((r[0].ljust(widths[0]), r[1].ljust(widths[1]), r[2].ljust(widths[2]),
                         r[3].rjust(widths[3]), r[4])))
    counts = {s: sum(j.status == s for j in jobs) for s in ("built", "kept", "failed")}
    print(f"{len(jobs)} site(s): {counts['built']} built, {counts['kept']} kept, {counts['failed']} failed")


def run_batch(survey: Survey, args: argparse.Namespace) -> int:
    """Build the raw archives and/or variants of several sites.

    Args:
        survey (Survey): The survey.
        args (argparse.Namespace): Parsed arguments naming the sites, or
            --all.

    Returns:
        int: 1 when a site failed or Ctrl+C stopped the batch, 0 otherwise.
    """
    raw_sites = survey.site_dirs()
    if args.all:
        declared = survey.site_names()
        for site in declared:
            if site not in raw_sites:
                print(f"skipping {site}: no raw data folder under {survey.data_root}")
        undeclared = [s for s in raw_sites if s not in declared]
        if undeclared:
            print(f"skipping raw folder(s) missing from survey.yaml: {' '.join(undeclared)} "
                  "(name a site to build it with the survey defaults)")
        names = [s for s in declared if s in raw_sites]
    else:
        names = list(dict.fromkeys(args.sites))
    if not names:
        print("no site to build")
        return 0

    jobs = [plan_site(survey, site, raw_sites, args) for site in names]
    for job in jobs:
        if job.status == "failed":
            print(f"ERROR {job.site}: {job.error}", file=sys.stderr)
        elif job.status == "kept":
            print(f"{job.site}: kept (archive {job.archive.split()[0]}, variant {job.variant.split()[0]})")
    todo = [j for j in jobs if not j.status]
    how = ("one after another in this process" if args.parallel == 1
           else f"{args.parallel} at a time, logs in {survey.workspace / 'logs'}")
    print(f"batch of {len(jobs)} site(s), {len(todo)} to build, {how}", flush=True)
    stopped = (run_here if args.parallel == 1 else run_children)(todo, args, survey) if todo else False
    print_summary(jobs, survey)
    if stopped:
        print("stopped by Ctrl+C")
    return 1 if any(j.status == "failed" for j in jobs) else 0


def main(argv=None) -> int:
    """Build the raw archive and/or the filtered variant of one site, or of a batch of sites.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 1 when the site has no raw-file folder or a site
        of a batch failed, 2 when the raw archive of one site exists and
        --force was not given.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.all and args.sites:
        parser.error("site and --all are mutually exclusive")
    if not args.all and not args.sites:
        parser.error("name one or more sites, or give --all")
    if args.parallel < 1:
        parser.error("--parallel takes 1 or more")
    survey = Survey.from_yaml(args.survey_yaml)
    if args.all or len(args.sites) > 1:
        return run_batch(survey, args)

    site = args.sites[0]
    raw_sites = survey.site_dirs()
    if site not in raw_sites:
        print(f"ERROR {site}: no folder of raw files (B423, LEMI-424 .txt, EDL) under {survey.data_root}",
              file=sys.stderr)
        return 1

    if not args.variant:
        out = default_archive_path(survey, site)
        if out.exists() and not args.force:
            print(f"ERROR {out} exists: pass --force to rebuild it", file=sys.stderr)
            return 2
        print(f"ingesting {site} ({survey.instrument_of(site)}) from {raw_sites[site]} "
              f"(LEMI-423 runs of at most {args.max_run_files} files) -> {out}", flush=True)
        try:
            path = ingest_site(survey, site, overwrite=args.force, max_run_files=args.max_run_files)
        except BaseException:
            _remove_partial(out)
            raise
        print(f"archive: {path}")

    if not args.raw:
        declared = survey.site(site).filters or []
        if not declared:
            print("variant: none (no declared filters)")
        elif not args.force and variant_ready(survey, site):
            print(f"variant: {variant_path(survey, site)} (already current)")
        else:
            vpath = variant_path(survey, site)
            print(f"building {site}'s variant ({len(declared)} declared filter(s)) -> {vpath}", flush=True)
            try:
                built = build_variant(survey, site)
            except BaseException:
                _remove_partial(vpath)
                raise
            print(f"variant: {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
