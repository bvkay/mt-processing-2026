# -*- coding: utf-8 -*-
"""
Resumable, parallel processing campaign over a line of sites

Runs every remote, the stacks and the estimator options for each site of a
line, in parallel and resumably. The plan (e.g. surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml) names
the campaign, its sites in order along the line, the exclusions with their
reasons, the deployment groups in processing order, the remote overlap rule,
the stack weightings, the stage 3 configs and the runner's limits.

Archives: <workspace>/mth5/<site>.h5 is the raw recording, which the
campaign leaves in place unchanged. Processing reads a filtered variant
<site>_f<hash>.h5 that `crust.ingest.processing_archive(survey, site)` (or
`build_variant`) builds on demand from the raw archive and filters.yaml;
process_rr.py calls it before every run. Stages:

0 variants: per site, a child process calls processing_archive (else
  build_variant), so every variant exists before two parallel runs could
  both try to build the same one. The variant's recorded filters (its runs'
  "ingest filters (in order): ..." comments, in crust.ingest's wording) are
  then compared with filters.yaml and the verdict goes into the ledger's
  `check` column; a `mains` filter's step_fraction is not recorded and is
  not compared. The check is informational and does not block a run.
1 remotes: every site rr every eligible remote with the defaults (Hann). A
  remote is any plan site whose record overlaps the local's (survey.yaml
  start/end) by >= `overlap.min_fraction` of the local record or
  >= `overlap.min_hours`; nearest first.
2 stacks: per site, the leave-one-out stack of the other members of its
  group that are eligible remotes, over the site's record (the builder
  intersects the members' runs), one per weighting (STK_<site>u: none,
  STK_<site>w: coherence) with scripts/build_stack.py; then the site rr each
  stack. A group with fewer than two such members borrows the other
  group whose eligible members share the longest common span with the site.
3 options: per site, on its best stage 1 remote (highest crust.quality
  score over the scoring window; among remotes within `tie_tolerance` of the
  top, the one agreeing best with the others, lowest median |dlog10 rho|),
  one process_rr.py run per plan config. The choice is kept in
  best_remote.json so a resume keeps it. A config may name the MANTLE
  engine (`mantle: [--engine, mantle]`): its run gets `--no-masks` whatever
  `runner.masks` says, its inputs carry no masks hash, and its report JSON
  and fine-grid EDI move into <campaign>/tf/ with the EDI. A config that
  turns masks.yaml on while `runner.masks` is off (`masked: [--masks]`) is
  skipped for a site when masks.yaml holds no entry for the site and no
  entry of scope both for its remote (no entry for either under
  `--mask-scope union`), since the run would repeat the default.

Readiness: before each stage the runner checks, in a fresh child process,
that crust.ingest has processing_archive or build_variant (stage 0), that
scripts/process_rr.py calls it (stages 1 and 3) and that the stack builder
(crust/virtual.py or scripts/build_stack.py) does (stage 2). Stages 0, 1 and
3 wait for it, polling every 5 minutes; a stage 2 whose builder is not ready
is deferred to the end of the campaign and waits there. --allow-raw (for
smoke checks) runs anyway: its rows are marked `provisional` and redone by
the next run without the flag.

Order: stage 0 for every selected site first (a site's remotes cross
groups), then per group in plan order stages 1, 2 and 3, so the first
group's results are complete before the next group starts. Every rr run is
tagged `--tag <name>-<config>` ("default" in stages 1 and 2). Its EDI path is
read from the child's `wrote <path>.edi` line, and the EDI, the comparison
PNG and the .json sidecar are moved into <campaign>/tf/ (plan
`runner.move_products`), so <workspace>/tf holds other outputs alone.

Runner: up to --parallel jobs at once within a stage (variant and stack
builds too). A job starts when psutil's available memory, less what the
running jobs are still expected to grow by (the `peak_percentile` of the
`peak_recent` most recently finished peaks of their kind, else the plan's
`expected_peak_gb`), is at least `min_available_gb` and `peak_factor` x that
percentile over every kind; waiting slots log every 5 min. Children run at
below-normal priority, each with its own log in <campaign>/logs/<run_id>.log;
RSS (with children) is polled every 2 s.

Outputs in <workspace>/campaign/<name>/: ledger.csv (one row per run id:
stage, kind, local, remote, config, tag, status, exit code, start, seconds,
peak RSS MB, EDI/sidecar/figure paths, the variant or stack archive and its
size, the inputs' signature, error text; rewritten atomically at every start
and finish), runs.log, scores.csv (crust.quality of every product, after
every block), figures/<site>_remotes.png, <site>_stacks.png,
<site>_options.png, <name>_best_pseudosection.png, <name>_scores.png, and
summary.md. A run is skipped when the ledger has it done with the same
inputs: per site the hash of its filters.yaml entry and its raw archive's
mtime, per stack the stack archive's mtime, so an edited filter causes a
re-run. Ctrl+C kills the running children and marks them interrupted. A
killed runner leaves "running" rows that the next start cleans up (orphaned
children killed, partial stack archives removed). --report rebuilds scores,
figures and summary from the ledger without running jobs; --dry-run prints
the whole matrix with counts and hours.

Usage:
    python scripts/campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...]
        [--parallel N] [--max-runs N] [--allow-raw] [--dry-run] [--report]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.ingest import default_archive_path  # noqa: E402
from crust.masks import is_stack, load_masks, masks_for_role, remote_masks  # noqa: E402

try:  # optional: without the variant API the campaign runs and waits for it
    from crust.ingest import filters_hash as _api_filters_hash  # noqa: E402
    from crust.ingest import variant_path as _api_variant_path  # noqa: E402
except ImportError:
    _api_filters_hash = _api_variant_path = None
from crust.quality import MODES, agreement, curves, flat_quality, pairwise_spread, tf_quality  # noqa: E402
from crust.survey import Survey, distance_km  # noqa: E402

PY = sys.executable
SCRIPTS = REPO / "scripts"
MB = 1024.0**2
POLL_S = 2.0
WAIT_LOG_S = 300.0
API_POLL_S = 300.0
STAGES = {0: "variants", 1: "remotes", 2: "stacks", 3: "options"}
KINDS = ("variant", "stack", "rr")
LEDGER_COLUMNS = [
    "run_id", "stage", "kind", "group", "local", "remote", "config", "tag", "status", "exit_code",
    "started", "finished", "seconds", "peak_rss_mb", "edi", "sidecar", "figure", "archive", "size_mb",
    "check", "inputs", "provisional", "error", "log", "runner_pid", "child_pid", "cmd",
]
NAME_RE = re.compile(r"^[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$")
FILTER_PREFIX = "ingest filters (in order): "
VARIANT_HASH_PREFIX = "filters hash "
VARIANT_FUNCS = ("processing_archive", "build_variant")
# what a child runs for stage 0: the variant API's call, printing the archive it returns
VARIANT_CODE = (
    "import sys; sys.path.insert(0, sys.argv[1]); from crust.survey import Survey; import crust.ingest as m; "
    "out = getattr(m, sys.argv[4])(Survey.from_yaml(sys.argv[2]), sys.argv[3]); print(f'variant: {out}', flush=True)"
)
API_PROBE = """
import importlib, json, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
names, out = sys.argv[3:], {}
try:
    m = importlib.import_module("crust.ingest")
    out["funcs"] = {n: callable(getattr(m, n, None)) for n in names}
except Exception as exc:
    out["funcs"], out["ingest_error"] = {}, repr(exc)[:200]
for mod in ("process_rr", "crust.virtual"):
    try:
        mm = importlib.import_module(mod)
        out[mod] = any(callable(getattr(mm, n, None)) for n in names)
    except Exception as exc:
        out[mod], out[mod + "_error"] = False, repr(exc)[:200]
print(json.dumps(out))
"""


def now() -> dt.datetime:
    """Return the current local time, timezone-aware."""
    return dt.datetime.now().astimezone()


def stamp() -> str:
    """Return the current local time as YYYYMMDD-HHMMSS."""
    return now().strftime("%Y%m%d-%H%M%S")


# ------------------------------------------------------------------ the plan


@dataclass
class Plan:
    """A campaign plan read from its YAML by `load_plan`."""

    path: Path
    name: str
    description: str
    sites: list[str]
    exclude: dict[str, str]
    groups: dict[str, list[str]]
    min_fraction: float = 0.5
    min_hours: float = 12.0
    weightings: dict[str, str] = field(default_factory=lambda: {"u": "none", "w": "coherence"})
    configs: dict[str, list[str]] = field(default_factory=dict)
    tie_tolerance: float = 0.02
    pmin: float | None = None
    pmax: float | None = None
    minutes: dict[str, float] = field(default_factory=lambda: {"rr": 8.0, "variant": 8.0, "stack": 1.0})
    min_available_gb: float = 40.0
    peak_factor: float = 1.2
    expected_peak_gb: dict[str, float] = field(default_factory=lambda: {"rr": 35.0, "variant": 20.0, "stack": 8.0})
    peak_percentile: float = 90.0
    peak_recent: int = 30
    move_products: bool = True
    masks: bool = False       # rr runs apply masks.yaml, the local's entries and the remote's of scope both (else --no-masks: every remote and option on the same data)

    def group_of(self, site: str) -> str:
        """Return the name of the group that holds `site`."""
        return next(g for g, members in self.groups.items() if site in members)

    def tag(self, config: str) -> str:
        """Return the process_rr.py tag of a config: <name>-<config>."""
        return f"{self.name}-{config}"

    def ordered(self, sites) -> list[str]:
        """Return `sites` in processing order: by group in plan order, then as listed in the group."""
        wanted = set(sites)
        return [s for members in self.groups.values() for s in members if s in wanted]


def load_plan(path) -> Plan:
    """Read and check a plan YAML.

    Args:
        path (str | Path): The plan YAML.

    Returns:
        Plan: The plan, with defaults for the keys it leaves out.

    Raises:
        ValueError: Naming every problem found in the plan.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    errors = []
    name = str(raw.get("name") or "")
    if not NAME_RE.match(name):
        errors.append(f"name {name!r}: letters, digits, _ and - only (it goes into tags and paths)")
    sites = [str(s) for s in (raw.get("sites") or [])]
    if not sites:
        errors.append("sites: none listed")
    if len(set(sites)) != len(sites):
        errors.append(f"sites: listed twice: {sorted({s for s in sites if sites.count(s) > 1})}")
    exclude = {str(k): str(v or "").strip() for k, v in (raw.get("exclude") or {}).items()}
    for site, reason in exclude.items():
        if not reason:
            errors.append(f"exclude {site}: give the reason")
        if site in sites:
            errors.append(f"exclude {site}: also in sites")
    groups = {str(g): [str(s) for s in (members or [])] for g, members in (raw.get("groups") or {}).items()}
    if not groups:
        errors.append("groups: none")
    seen: dict[str, str] = {}
    for g, members in groups.items():
        for s in members:
            if s in exclude:
                errors.append(f"group {g}: {s} is excluded")
            elif s not in sites:
                errors.append(f"group {g}: {s} is not in sites")
            if s in seen:
                errors.append(f"{s} is in groups {seen[s]} and {g}")
            seen[s] = g
    missing = [s for s in sites if s not in seen]
    if missing:
        errors.append(f"sites in no group: {missing}")
    overlap = raw.get("overlap") or {}
    stages = raw.get("stages") or {}
    stacks = stages.get("stacks") or {}
    options = stages.get("options") or {}
    weightings = {str(k): str(v) for k, v in (stacks.get("weightings") or {"u": "none", "w": "coherence"}).items()}
    for suffix, w in weightings.items():
        if w not in ("none", "coherence") or not re.match(r"^[a-z]$", suffix):
            errors.append(f"stacks weightings {suffix}: {w}: a one-letter suffix and none|coherence")
    configs = {}
    for cname, args in (options.get("configs") or {}).items():
        cname = str(cname)
        args = [str(a) for a in (args or [])]
        if not re.match(r"^[A-Za-z0-9]+$", cname) or cname == "default":
            errors.append(f"config {cname!r}: letters and digits only, not 'default'")
        if not args or not args[0].startswith("--") or any(a in ("--tag", "--dry-run") for a in args):
            errors.append(f"config {cname}: {args}: process_rr.py flags, without --tag/--dry-run")
        configs[cname] = args
    runner = raw.get("runner") or {}
    scoring = raw.get("scoring") or {}
    if errors:
        raise ValueError(f"{path}:\n  " + "\n  ".join(errors))
    plan = Plan(
        path=path, name=name, description=str(raw.get("description") or "").strip(), sites=sites,
        exclude=exclude, groups=groups,
        min_fraction=float(overlap.get("min_fraction", 0.5)), min_hours=float(overlap.get("min_hours", 12.0)),
        weightings=weightings, configs=configs, tie_tolerance=float(options.get("tie_tolerance", 0.02)),
        pmin=None if scoring.get("pmin") is None else float(scoring["pmin"]),
        pmax=None if scoring.get("pmax") is None else float(scoring["pmax"]),
        move_products=bool(runner.get("move_products", True)),
        masks=bool(runner.get("masks", False)),
        min_available_gb=float(runner.get("min_available_gb", 40.0)),
        peak_factor=float(runner.get("peak_factor", 1.2)),
    )
    plan.minutes.update({k: float(v) for k, v in (runner.get("minutes_per_job") or {}).items()})
    plan.expected_peak_gb.update({k: float(v) for k, v in (runner.get("expected_peak_gb") or {}).items()})
    plan.peak_percentile = float(runner.get("peak_percentile", 90.0))
    plan.peak_recent = int(runner.get("peak_recent", 30))
    return plan


# ------------------------------------------------------- records and remotes


def site_spans(survey: Survey, sites) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Return each site's recorded span from survey.yaml.

    Returns:
        dict: {site: (start, end)} in UTC.

    Raises:
        ValueError: When a site has no start/end in survey.yaml.
    """
    out = {}
    for s in sites:
        cfg = survey.site(s)
        if not cfg.start or not cfg.end:
            raise ValueError(f"{s}: survey.yaml has no start/end for it (scripts/new_survey.py writes them)")
        out[s] = (pd.Timestamp(cfg.start).tz_convert("UTC"), pd.Timestamp(cfg.end).tz_convert("UTC"))
    return out


def overlap_hours(a, b) -> float:
    """Return the overlap in hours of two (start, end) spans; 0 when disjoint."""
    return max(0.0, (min(a[1], b[1]) - max(a[0], b[0])).total_seconds() / 3600.0)


def is_eligible(plan: Plan, spans: dict, local: str, remote: str) -> bool:
    """Apply the plan's remote rule: overlap >= min_fraction of the local record, or >= min_hours."""
    if remote == local:
        return False
    ov = overlap_hours(spans[local], spans[remote])
    rec = (spans[local][1] - spans[local][0]).total_seconds() / 3600.0
    return ov > 0 and (ov >= plan.min_fraction * rec - 1e-9 or ov >= plan.min_hours - 1e-9)


def _km(survey: Survey, a: str, b: str) -> float:
    """Return the distance in km between two sites, inf when a position is missing."""
    ca, cb = survey.site(a), survey.site(b)
    if None in (ca.latitude, ca.longitude, cb.latitude, cb.longitude):
        return float("inf")
    return distance_km(ca.latitude, ca.longitude, cb.latitude, cb.longitude)


def eligible_remotes(plan: Plan, survey: Survey, spans: dict, local: str) -> list[str]:
    """Return every eligible remote of `local`, nearest first (then by name)."""
    rs = [r for r in plan.sites if is_eligible(plan, spans, local, r)]
    return sorted(rs, key=lambda r: (_km(survey, local, r), r))


def common_span(spans: dict, sites) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    """Return the (start, end, hours) span shared by all `sites`."""
    lo = max(spans[s][0] for s in sites)
    hi = min(spans[s][1] for s in sites)
    return lo, hi, max(0.0, (hi - lo).total_seconds() / 3600.0)


def stack_plan(plan: Plan, spans: dict, local: str) -> dict | None:
    """Plan the leave-one-out stack for `local`.

    Members are the other members of `local`'s group that are eligible
    remotes of it. With fewer than two, the members come from the other group
    whose eligible members (at least two) share the longest common span with
    `local` (at least `min_hours`). The start/end passed to the builder are
    `local`'s record.

    Returns:
        dict | None: {members, group, borrowed, span_h, span, start, end},
        or None when no stack is possible.
    """
    own = plan.group_of(local)
    members = [s for s in plan.groups[own] if s != local and is_eligible(plan, spans, local, s)]
    borrowed = None
    if len(members) < 2:
        best = None
        for g, gm in plan.groups.items():
            if g == own:
                continue
            cand = [s for s in gm if is_eligible(plan, spans, local, s)]
            if len(cand) < 2:
                continue
            _, _, h = common_span(spans, [local, *cand])
            if h >= plan.min_hours and (best is None or h > best[2]):
                best = (g, cand, h)
        if best is None:
            return None
        borrowed, members = best[0], best[1]
    lo, hi, h = common_span(spans, [local, *members])
    return {"members": members, "group": borrowed or own, "borrowed": borrowed is not None,
            "span_h": h, "span": (lo, hi), "start": spans[local][0], "end": spans[local][1]}


def filters_hash(filters) -> str:
    """Hash a site's filters.yaml entry to 8 hex digits.

    Uses crust.ingest.filters_hash (the variant's ``_f<hash>``) when the API
    is present, else the same sha1 of the canonical JSON.
    """
    if _api_filters_hash is not None:
        return _api_filters_hash(filters)
    text = json.dumps(list(filters or []), sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# --------------------------------------------------- recorded filter provenance


def _attr_text(value) -> str:
    """Return an HDF5 attribute as text ("" for None, bytes decoded as UTF-8)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def read_run_comments(path: Path, site: str) -> list[dict]:
    """Read the comment, channels and sample rate of every Run group of a site.

    Opens the archive read-only with h5py.

    Returns:
        list[dict]: [{run, comment, channels, sample_rate}].
    """
    import h5py

    out = []
    with h5py.File(path, "r") as f:
        for survey_name in f["Experiment/Surveys"]:
            stations = f[f"Experiment/Surveys/{survey_name}/Stations"]
            if site not in stations:
                continue
            for run_id, grp in stations[site].items():
                if _attr_text(grp.attrs.get("mth5_type")) != "Run":
                    continue
                chans = [c for c, ch in grp.items()
                         if _attr_text(ch.attrs.get("mth5_type")) in ("Electric", "Magnetic", "Auxiliary")]
                out.append({"run": run_id, "comment": _attr_text(grp.attrs.get("comments")),
                            "channels": sorted(c.lower() for c in chans),
                            "sample_rate": float(grp.attrs.get("sample_rate") or 0.0)})
    return out


def _num(a, b) -> bool:
    """Compare two numbers (or numeric strings) to a relative 1e-9."""
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))


def filter_line_matches(spec: dict, line: str, run_channels, fs: float) -> tuple[bool, str]:
    """Check whether one recorded provenance line says `spec` was applied.

    The line is in the wording of crust.noise / crust.ingest.

    Args:
        spec (dict): One declared filter, {kind: options}.
        line (str): One recorded filter line.
        run_channels (list[str]): The run's channels, used when the spec
            names none.
        fs (float): The run's sample rate.

    Returns:
        tuple[bool, str]: (match, explanation).
    """
    if len(spec) != 1:
        return False, f"filter spec {spec} is not a single-key dict"
    kind, opts = next(iter(spec.items()))
    opts = dict(opts or {})
    if kind == "replace":
        want = "replace magnetics: " + ", ".join(f"{str(c).lower()} <- {s}" for c, s in opts.items())
        return (line == want), f"recorded {line!r}, declared {want!r}"
    m = re.match(r"^(.*) on (\[[^\]]*\])$", line)
    if not m:
        return False, f"cannot read the channels of {line!r}"
    head, chan_text = m.groups()
    try:
        chans = {str(c).lower() for c in ast.literal_eval(chan_text)}
    except (ValueError, SyntaxError):
        return False, f"cannot read the channels of {line!r}"
    want_chans = {str(c).lower() for c in (opts["channels"] if opts.get("channels") is not None else run_channels)}
    if chans != want_chans:
        return False, f"{kind} on {sorted(chans)}, declared on {sorted(want_chans)}"
    if kind == "notch":
        mm = re.match(r"^notch f0=(\S+) Hz harmonics=(\d+) q=(\S+) passes=(\d+)(?: extra=(\[.*\]))? zero-phase$", head)
        if not mm:
            return False, f"not a notch line: {head!r}"
        f0, h, q, p, extra = mm.groups()
        extra = [float(x) for x in ast.literal_eval(extra)] if extra else []
        want_extra = [float(x) for x in (opts.get("extra") or [])]
        ok = (_num(f0, opts.get("f0", 50.0)) and int(h) == int(opts.get("harmonics", 9))
              and _num(q, opts.get("q", 30.0)) and int(p) == int(opts.get("passes", 2))
              and len(extra) == len(want_extra) and all(_num(a, b) for a, b in zip(extra, want_extra)))
        return ok, f"recorded {head!r}, declared notch {opts}"
    if kind == "mains":
        f0 = float(opts.get("f0", 50.0))
        nh = sum(1 for k in range(1, int(opts.get("harmonics", 9)) + 1) if k * f0 < 0.5 * fs)
        mm = re.match(r"^mains: f0 (\S+) Hz x(\d+) harmonics fitted per (\S+) s block", head)
        ok = bool(mm) and _num(mm.group(1), f0) and int(mm.group(2)) == nh and _num(mm.group(3), opts.get("block_s", 1.0))
        return ok, f"recorded {head[:80]!r}, declared mains {opts} ({nh} harmonics under Nyquist)"
    if kind in ("hp", "lp"):
        btype = "highpass" if kind == "hp" else "lowpass"
        want = (f"{kind} {btype} {float(opts.get('cutoff_hz', float('nan'))):g} Hz Butterworth order "
                f"{int(opts.get('order', 4))}, zero-phase (sosfiltfilt)")
        return head == want, f"recorded {head!r}, declared {want!r}"
    if kind == "cp":
        ok = head.startswith("cp stack-subtract: period ") and \
            f", {float(opts.get('window_minutes', 10.0)):g} min windows, median cycle removed" in head
        if not opts.get("refine"):
            ok = ok and f"period {float(opts.get('period_s', 12.0)):.5f} s" in head
        return ok, f"recorded {head!r}, declared cp {opts}"
    if kind == "burst":
        ok = head.startswith("burst: ") and f"threshold {float(opts.get('threshold', 12.0)):g} x MAD on " in head \
            and (f"; min {float(opts.get('min_len_s', 0.05)):g} s, pad {float(opts.get('pad_s', 0.1)):g} s, "
                 f"taper {float(opts.get('taper_s', 0.05)):g} s, set to the local level") in head
        return ok, f"recorded {head!r}, declared burst {opts}"
    if kind == "flip":
        return head == "flip: sign reversed", f"recorded {head!r}"
    return False, f"unknown filter kind {kind!r}"


def recorded_matches(comment: str, declared: list, run_channels, fs: float) -> tuple[bool, str]:
    """Check whether one run's comment records exactly the declared filters, in ingest's order.

    Returns:
        tuple[bool, str]: (match, explanation).
    """
    comment = (comment or "").strip()
    declared = [s for s in (declared or []) if s]
    if comment.startswith(VARIANT_HASH_PREFIX):  # a build_variant archive: "filters hash <h>; ingest filters ..."
        recorded, _, comment = comment[len(VARIANT_HASH_PREFIX):].partition("; ")
        if recorded.strip() != filters_hash(declared):
            return False, f"records filters hash {recorded.strip()}, filters.yaml hashes to {filters_hash(declared)}"
    if not comment.startswith(FILTER_PREFIX):
        if not declared:
            return (not comment.startswith("ingest filters")), "no filters declared"
        return False, f"records no filters, {len(declared)} declared"
    if not declared:
        return False, "records filters, none declared"
    body = comment[len(FILTER_PREFIX):]
    body = re.split(r"; (?:PR6-24 high gain|electric gain \S+) on ", body)[0]  # the EDL gain line follows the filters
    lines = body.split("; then ")
    order = [s for s in declared if "replace" in s] + [s for s in declared if "replace" not in s]
    if len(lines) != len(order):
        return False, f"records {len(lines)} filter(s), {len(order)} declared"
    for k, (spec, line) in enumerate(zip(order, lines), 1):
        ok, why = filter_line_matches(spec, line, run_channels, fs)
        if not ok:
            return False, f"filter {k}: {why}"
    return True, f"{len(order)} filter(s) as declared"


def archive_filters_check(path: Path, site: str, declared, fs_default: float) -> tuple[bool, str]:
    """Check whether every run of `site` in an archive records exactly `declared`.

    Returns:
        tuple[bool, str]: (verdict, detail).
    """
    try:
        runs = read_run_comments(Path(path), site)
    except (OSError, KeyError) as exc:
        return False, f"{Path(path).name}: unreadable ({exc})"
    if not runs:
        return False, f"{Path(path).name}: no run of {site}"
    for r in runs:
        ok, why = recorded_matches(r["comment"], declared, r["channels"], r["sample_rate"] or fs_default)
        if not ok:
            return False, f"{r['run']}: {why}"
    return True, f"{len(runs)} run(s): {why}"


# ------------------------------------------------------------------- ledger


class Ledger:
    """The campaign ledger: one row per run id, rewritten atomically (temp file + os.replace) at every change."""

    def __init__(self, path: Path, log=print):
        self.path = Path(path)
        self.log = log
        self.rows: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    self.rows[row["run_id"]] = {c: row.get(c, "") or "" for c in LEDGER_COLUMNS}

    def upsert(self, row: dict) -> None:
        """Insert or update a row, stored as the CSV reads back, and save."""
        old = self.rows.get(row["run_id"], {c: "" for c in LEDGER_COLUMNS})
        old.update({k: ("" if v is None else str(v)) for k, v in row.items() if k in LEDGER_COLUMNS})  # as the CSV reads back
        self.rows[row["run_id"]] = old
        self.save()

    def save(self) -> bool:
        """Write the ledger atomically.

        Returns:
            bool: False when the file stayed locked (e.g. open in Excel);
            the rows are kept in memory and written at the next change.
        """
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, LEDGER_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for row in self.rows.values():
                w.writerow(row)
            fh.flush()
            os.fsync(fh.fileno())
        for _ in range(10):
            try:
                os.replace(tmp, self.path)
                return True
            except PermissionError:
                time.sleep(0.5)
        self.log(f"WARNING {self.path.name} is locked (open in Excel? open a copy): kept in memory, "
                 f"written at the next change")
        return False

    def peak_mb(self, kind: str | None = None, percentile: float = 90.0, recent: int = 0) -> float:
        """Return a percentile of the peak RSS of finished jobs, in MB.

        The gate keys on a percentile (`runner.peak_percentile` in the plan,
        default 90) rather than the maximum: a single outlying job (a larger
        window overlap, say) would otherwise hold the gate at its own peak and
        keep a slot idle while typical jobs would fit side by side. With
        `recent` > 0 the `recent` most recently finished jobs count, so a
        change of estimator that changes the peaks moves the gate with it.

        Args:
            kind (str | None): Job kind, or None for all kinds.
            percentile (float): Percentile of the peaks.
            recent (int): Number of most recent jobs to use; 0 for all.

        Returns:
            float: The peak in MB, 0 when no job has finished.
        """
        rows = [r for r in self.rows.values()
                if r["peak_rss_mb"] and (kind is None or r["kind"] == kind)]
        if recent > 0:
            rows = sorted(rows, key=lambda r: r["finished"] or r["started"])[-recent:]
        vals = sorted(float(r["peak_rss_mb"]) for r in rows)
        if not vals:
            return 0.0
        k = min(len(vals) - 1, max(0, int(round(percentile / 100.0 * (len(vals) - 1)))))
        return vals[k]


# --------------------------------------------------------------------- jobs


@dataclass
class Job:
    """One campaign job: an rr run, a variant build or a stack build."""

    run_id: str
    stage: int
    kind: str
    group: str
    local: str
    remote: str = ""
    config: str = ""
    tag: str = ""
    cmd: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    input_sites: list[str] = field(default_factory=list)
    output: Path | None = None
    note: str = ""


@dataclass
class Running:
    """A started job with its process, log and memory samples."""

    job: Job
    popen: subprocess.Popen
    ps: psutil.Process | None
    started: dt.datetime
    t0: float
    log_path: Path
    log_offset: int
    aside: Path | None = None
    peak_mb: float = 0.0
    rss_mb: float = 0.0


def kill_tree(pid: int) -> None:
    """Kill a process and all its children, then wait up to 30 s for them."""
    try:
        p = psutil.Process(pid)
        procs = p.children(recursive=True) + [p]
    except psutil.Error:
        return
    for q in procs:
        try:
            q.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(procs, timeout=30)


WROTE_RE = re.compile(r"\bwrote (.+?)\s*$")
# loguru colours its lines even into a redirected log ("\x1b[1m ... wrote <path>\x1b[0m")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_products(text: str) -> dict:
    """Read the product paths from a process_rr.py log.

    Returns:
        dict: {"edi", "sidecar", "figure"}: the last `wrote <path>` of each
        kind, "" when absent.
    """
    out = {"edi": "", "sidecar": "", "figure": ""}
    for line in ANSI_RE.sub("", text).splitlines():
        m = WROTE_RE.search(line)
        if m:
            path = m.group(1).strip().strip("'\"")
            low = path.lower()
            key = "edi" if low.endswith(".edi") else "sidecar" if low.endswith(".json") else \
                "figure" if low.endswith(".png") else None
            if key:
                out[key] = path
        for label, key in (("sidecar: ", "sidecar"), ("comparison figure: ", "figure")):
            if line.startswith(label) and not out[key]:
                out[key] = line[len(label):].strip()
    return out


def last_error(text: str) -> str:
    """Return the last error-looking line of a log, else its last line (300 characters at most)."""
    lines = [ln.strip() for ln in ANSI_RE.sub("", text).splitlines() if ln.strip()]
    for ln in reversed(lines):
        if re.search(r"(Error|Exception|ERROR|Traceback|Killed)", ln):
            return ln[:300]
    return lines[-1][:300] if lines else ""


def api_state() -> dict:
    """Probe the variant API as a fresh process sees it.

    This process imported crust.ingest when it started, so the probe runs
    in a child and imports the modules. Stage 0 needs processing_archive (or
    build_variant) in crust.ingest, stages 1 and 3 need scripts/process_rr.py
    to import one, and stage 2 needs crust.virtual (the stack builder) to. A
    module that fails to import counts as not ready.

    Returns:
        dict: {"func", "variant", "rr", "stack", "why"}.
    """
    try:
        out = subprocess.run([PY, "-c", API_PROBE, str(REPO / "src"), str(SCRIPTS), *VARIANT_FUNCS],
                             capture_output=True, text=True, timeout=300, cwd=str(REPO))
        have = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 and out.stdout.strip() else {}
        if not have:
            have = {"error": (out.stderr or out.stdout or "").strip().splitlines()[-1:]}
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError) as exc:
        have = {"error": [repr(exc)]}
    funcs = have.get("funcs") or {}
    func = next((n for n in VARIANT_FUNCS if funcs.get(n)), "")
    rr = bool(func) and bool(have.get("process_rr"))
    stack = rr and bool(have.get("crust.virtual"))
    why = []
    if not func:
        why.append(f"crust.ingest has neither {' nor '.join(VARIANT_FUNCS)}" +
                   (f" ({have['ingest_error']})" if have.get("ingest_error") else ""))
    if not have.get("process_rr"):
        why.append("scripts/process_rr.py does not use it" +
                   (f" ({have['process_rr_error']})" if have.get("process_rr_error") else ""))
    if not have.get("crust.virtual"):
        why.append("the stack builder (crust.virtual) does not use it" +
                   (f" ({have['crust.virtual_error']})" if have.get("crust.virtual_error") else ""))
    if have.get("error"):
        why.append(f"probe failed: {have['error']}")
    return {"func": func, "variant": bool(func), "rr": rr, "stack": stack, "why": "; ".join(why)}


NEEDS = {0: "variant", 1: "rr", 2: "stack", 3: "rr"}


# ------------------------------------------------------------------ runner


class Campaign:
    """The campaign runner: builds the jobs of each stage, runs them and writes the reports.

    Args:
        survey_yaml (str | Path): The survey.yaml.
        plan (Plan): The campaign plan.
        parallel (int): Jobs at once.
        max_runs (int | None): Start at most this many jobs.
        allow_raw (bool): Run without the variant API, marking rows
            provisional.
        create (bool): Create the campaign folders; False for a dry run.
    """

    def __init__(self, survey_yaml, plan: Plan, parallel: int = 2, max_runs: int | None = None,
                 allow_raw: bool = False, create: bool = True):
        self.survey_yaml = str(Path(survey_yaml).resolve())
        self.survey = Survey.from_yaml(self.survey_yaml)
        self.plan = plan
        self.parallel = max(1, int(parallel))
        self.max_runs = max_runs
        self.allow_raw = allow_raw
        self.dir = self.survey.workspace / "campaign" / plan.name
        for sub in ("", "logs", "tf", "figures") if create else ():  # a dry run writes nothing
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.dir / "ledger.csv", log=self.log)
        self.spans = site_spans(self.survey, plan.sites)
        self.pmin = plan.pmin if plan.pmin is not None else self.survey.processing.get("min_period")
        self.pmax = plan.pmax if plan.pmax is not None else self.survey.processing.get("max_period")
        self.n_started = 0
        self.api: dict = {"func": "", "variant": False, "rr": False, "stack": False, "why": "not checked"}
        self._running: dict[str, Running] = {}
        self._last_wait_log = 0.0

    # ---------------------------------------------------------------- helpers

    def log(self, msg: str) -> None:
        """Print a time-stamped line and append it to runs.log."""
        line = f"{now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            with open(self.dir / "runs.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def refresh(self) -> None:
        """Re-read survey.yaml and filters.yaml (a filter may be edited mid-campaign)."""
        self.survey = Survey.from_yaml(self.survey_yaml)

    def raw_archive(self, site: str) -> Path:
        """Return the site's raw archive path."""
        return default_archive_path(self.survey, site)

    def stack_archive(self, name: str) -> Path:
        """Return <workspace>/mth5/<name>.h5."""
        return self.survey.workspace / "mth5" / f"{name}.h5"

    def signature(self, site: str) -> str:
        """Return the input signature of a site (filters.yaml hash and raw archive mtime) or a stack (archive mtime)."""
        if site.startswith("STK_"):
            p = self.stack_archive(site)
            return f"{site}@{int(p.stat().st_mtime) if p.exists() else 'missing'}"
        p = self.raw_archive(site)
        return (f"{site}:f{filters_hash(self.survey.site(site).filters)}"
                f"@{int(p.stat().st_mtime) if p.exists() else 'missing'}")

    def inputs(self, job: Job) -> str:
        """Return the input signature of a job; a change means the job is re-run."""
        sig = ";".join(self.signature(s) for s in job.input_sites)
        if job.kind == "rr" and self.rr_masks_on(job.config):
            # process_rr applies every masks.yaml entry of the local and the remote's entries
            # of scope both, or all of them under --mask-scope union (a stack has none of its
            # own, by the name rule of crust.masks.is_stack). The hash covers the entries a
            # run applies, each without its scope key, so an edit that changes them makes
            # the product stale
            rule = self.config_mask_scope(job.config)
            for site, role in ((job.local, "local"), (job.remote, "remote")):
                if not site or is_stack(site):
                    continue
                applied = [{k: v for k, v in m.items() if k != "scope"}
                           for m in masks_for_role(load_masks(self.survey, site), role, rule)]
                digest = hashlib.sha1(json.dumps(applied, sort_keys=True).encode()).hexdigest()[:8]
                sig += f";{site}:m{digest}"
        return sig

    def config_engine(self, config: str) -> str:
        """Return the engine a config's flags name (`--engine <name>`), "aurora" without the flag."""
        flags = self.plan.configs.get(config, []) if config != "default" else []
        for i, flag in enumerate(flags):
            if flag == "--engine":
                return flags[i + 1] if i + 1 < len(flags) else "aurora"
        return "aurora"

    def config_mask_scope(self, config: str) -> str:
        """Return the mask scope rule a config's flags name (`--mask-scope <rule>`), "role" without the flag.

        The last `--mask-scope` given wins, as on the process_rr command line.
        """
        flags = self.plan.configs.get(config, []) if config != "default" else []
        rule = "role"
        for i, flag in enumerate(flags):
            if flag == "--mask-scope" and i + 1 < len(flags):
                rule = flags[i + 1]
            elif flag.startswith("--mask-scope="):
                rule = flag.split("=", 1)[1]
        return rule

    def rr_masks_on(self, config: str) -> bool:
        """Return whether an rr run of `config` applies masks.yaml.

        The plan's `runner.masks` sets the default and a config's own
        `--masks` or `--no-masks` overrides it, as the later flag wins on the
        process_rr command line. A MANTLE config (`--engine mantle`) applies
        none: process_rr.py takes that engine with `--no-masks` only.
        """
        if self.config_engine(config) == "mantle":
            return False
        on = self.plan.masks
        for flag in (self.plan.configs.get(config, []) if config != "default" else []):
            if flag == "--masks":
                on = True
            elif flag == "--no-masks":
                on = False
        return on

    def rr_cmd(self, local: str, remote: str, config: str) -> list[str]:
        """Build the process_rr.py command line of one rr run.

        The runner's `--no-masks` goes before the config's flags so that a
        config declaring `--masks` wins; a MANTLE config gets `--no-masks`
        whatever the plan's `runner.masks` says.
        """
        extra = self.plan.configs.get(config, []) if config != "default" else []
        masks = [] if self.plan.masks and self.config_engine(config) != "mantle" else ["--no-masks"]
        return [PY, str(SCRIPTS / "process_rr.py"), self.survey_yaml, local, remote, *masks, *extra,
                "--tag", self.plan.tag(config)]

    def rr_job(self, stage: int, local: str, remote: str, config: str, run_id: str, deps=()) -> Job:
        """Build one rr job."""
        return Job(run_id=run_id, stage=stage, kind="rr", group=self.plan.group_of(local), local=local,
                   remote=remote, config=config, tag=self.plan.tag(config), cmd=self.rr_cmd(local, remote, config),
                   deps=list(deps), input_sites=[local, remote])

    # ------------------------------------------------------------ job builders

    def stage0_jobs(self, sites) -> list[Job]:
        """Build the variant jobs of stage 0, one per site."""
        func = self.api.get("func") or VARIANT_FUNCS[0]
        jobs = []
        for s in sites:
            n = len(self.survey.site(s).filters or [])
            jobs.append(Job(run_id=f"s0_{s}", stage=0, kind="variant", group=self.plan.group_of(s), local=s,
                            config=f"f{filters_hash(self.survey.site(s).filters)}",
                            cmd=[PY, "-c", VARIANT_CODE, str(REPO / "src"), self.survey_yaml, s, func],
                            input_sites=[s], note=f"{n} declared filter(s), {func}"))
        return jobs

    def stage1_jobs(self, sites) -> list[Job]:
        """Build the stage 1 rr jobs: every site against every eligible remote."""
        return [self.rr_job(1, s, r, "default", f"s1_{s}_rr-{r}")
                for s in sites for r in eligible_remotes(self.plan, self.survey, self.spans, s)]

    def stage2_jobs(self, sites) -> list[Job]:
        """Build the stage 2 jobs: per site, one stack build and one rr run per weighting."""
        jobs = []
        for s in sites:
            sp = stack_plan(self.plan, self.spans, s)
            if sp is None:
                self.log(f"stage 2: {s}: no stack possible (fewer than two eligible members in any group)")
                continue
            for suffix, weighting in self.plan.weightings.items():
                name = f"STK_{s}{suffix}"
                build = Job(
                    run_id=f"s2_build_{name}", stage=2, kind="stack", group=self.plan.group_of(s), local=s,
                    remote=name, config=weighting,
                    cmd=[PY, str(SCRIPTS / "build_stack.py"), self.survey_yaml, name,
                         sp["start"].strftime("%Y-%m-%d %H:%M:%S"), sp["end"].strftime("%Y-%m-%d %H:%M:%S"),
                         *sp["members"], "--weighting", weighting],
                    input_sites=list(sp["members"]), output=self.stack_archive(name),
                    note=(f"{weighting} of {' '.join(sp['members'])}"
                          + (f" (borrowed group {sp['group']})" if sp["borrowed"] else "")
                          + f", common span {sp['span_h']:.1f} h"))
                jobs.append(build)
                jobs.append(self.rr_job(2, s, name, "default", f"s2_{s}_rr-{name}", deps=[build.run_id]))
        # per site, its builds before its runs, so two slots build a site's stacks first
        order = {s: k for k, s in enumerate(sites)}
        return sorted(jobs, key=lambda j: (order[j.local], j.kind != "stack"))

    def stage3_jobs(self, sites, dry: bool = False) -> list[Job]:
        """Build the stage 3 jobs: one rr run per plan config on each site's best remote."""
        jobs = []
        chosen = self.best_remotes(sites, persist=not dry)
        for s in sites:
            remote = chosen.get(s, {}).get("remote")
            if not remote:
                if dry:
                    remote = "<best-of-stage-1>"
                else:
                    self.log(f"stage 3: {s}: no stage 1 product to choose a remote from: skipped")
                    continue
            for config in self.plan.configs:
                rule = self.config_mask_scope(config)
                if (self.rr_masks_on(config) and not self.plan.masks and remote != "<best-of-stage-1>"
                        and not self.has_masks(s, remote, rule)):
                    # the run would repeat the default: masks.yaml holds no entry it applies
                    which = f"{s} or {remote}" if rule == "union" else f"{s} and none of scope both for {remote}"
                    self.log(f"stage 3: {s}: {config}: no masks.yaml entry for {which}: skipped")
                    continue
                jobs.append(self.rr_job(3, s, remote, config, f"s3_{s}_rr-{remote}_{config}"))
        return jobs

    def has_masks(self, local: str, remote: str, rule: str = "role") -> bool:
        """Return whether masks.yaml holds an entry an rr run of `local` against `remote` applies.

        Every entry of the local applies; of the remote, the entries of scope
        both, or all of them under the rule union (`crust.masks.remote_masks`;
        a stack has none).

        Args:
            local (str): The local site.
            remote (str): The remote site or stack.
            rule (str): The mask scope rule, "role" or "union".

        Returns:
            bool: True when the run applies at least one entry.
        """
        return bool(load_masks(self.survey, local)) or bool(remote_masks(self.survey, remote, rule))

    # --------------------------------------------------------------- choices

    def best_remotes(self, sites, persist: bool = True, df: pd.DataFrame | None = None) -> dict:
        """Return each site's best stage 1 remote.

        The choice stored in best_remote.json is used when present; otherwise
        it is made now from the stage 1 scores and stored. A choice made from
        provisional products (--allow-raw) is not stored.

        Returns:
            dict: {site: {"remote", "score", "why"}}.
        """
        path = self.dir / "best_remote.json"
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        df = self.scores(write=persist) if df is None else df
        out, changed = {}, False
        for s in sites:
            s1 = df[(df["stage"] == 1) & (df["local"] == s)] if len(df) else df
            if s in stored and stored[s]["remote"] in set(s1.get("remote", [])):
                out[s] = stored[s]
                continue
            pick = choose_best(s1, self.plan.tie_tolerance, self.pmin, self.pmax)
            if pick:
                out[s] = pick
                clean = len(s1) == 0 or not s1.get("provisional", pd.Series(dtype=str)).fillna("").astype(str).str.strip().any()
                if clean:
                    stored[s] = {**pick, "chosen": now().isoformat(timespec="seconds")}
                    changed = True
        if persist and changed:
            path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
        return out

    # ------------------------------------------------------------------ blocks

    def blocks(self, stages, sites, dry: bool = False):
        """Yield (label, stage, group, sites, jobs) in run order; each block's jobs are built when it is reached."""
        sites = self.plan.ordered(sites)
        if 0 in stages:
            self.refresh()
            yield "stage 0 variants (all sites)", 0, "", sites, self.stage0_jobs(sites)
        for g, members in self.plan.groups.items():
            gs = [s for s in members if s in sites]
            if not gs:
                continue
            for st in (1, 2, 3):
                if st not in stages:
                    continue
                self.refresh()
                builder = {1: self.stage1_jobs, 2: self.stage2_jobs,
                           3: lambda x: self.stage3_jobs(x, dry=dry)}[st]
                yield f"stage {st} {STAGES[st]} group {g}", st, g, gs, builder(gs)

    def already_done(self, job: Job) -> bool:
        """Check whether the ledger has the job done, with the same inputs and its product present."""
        row = self.ledger.rows.get(job.run_id)
        if not row or row["status"] != "done" or str(row["exit_code"]) != "0":
            return False
        if row["provisional"] and not self.allow_raw:
            return False
        if row["inputs"] != self.inputs(job):
            return False
        if job.kind == "variant":
            return bool(row["archive"]) and Path(row["archive"]).exists()
        if job.kind == "stack":
            return job.output is not None and job.output.exists()
        return bool(row["edi"]) and Path(row["edi"]).exists()

    # --------------------------------------------------------------- readiness

    def check_api(self) -> dict:
        """Probe the variant API (`api_state`) and keep the result."""
        self.api = api_state()
        return self.api

    def wait_ready(self, need: str, label: str) -> bool:
        """Wait until the variant API serves `need` ("variant", "rr", "stack").

        Returns:
            bool: True when ready; False at once with --allow-raw, and the
            caller runs provisional.
        """
        t0, waited = time.time(), False
        while True:
            api = self.check_api()
            if api[need]:
                if waited:
                    self.log(f"{label}: the variant API is ready ({api['func']}) after "
                             f"{(time.time() - t0) / 60:.0f} min")
                return True
            if self.allow_raw:
                self.log(f"{label}: variant API not ready ({api['why']}): --allow-raw, running PROVISIONAL")
                return False
            self.log(f"{label}: waiting for the variant API: {api['why']} (checking every "
                     f"{API_POLL_S / 60:.0f} min)")
            waited = True
            time.sleep(API_POLL_S)

    # ------------------------------------------------------------------ memory

    def expected_peak_mb(self, kind: str) -> float:
        """Return the expected peak RSS of a job kind in MB, from the ledger or the plan."""
        return (self.ledger.peak_mb(kind, self.plan.peak_percentile, self.plan.peak_recent)
                or self.plan.expected_peak_gb.get(kind, 35.0) * 1024.0)

    def gate(self) -> tuple[bool, str]:
        """Check the memory gate for starting another job.

        Returns:
            tuple[bool, str]: (enough memory, explanation).
        """
        avail = psutil.virtual_memory().available / MB
        reserve = sum(max(0.0, self.expected_peak_mb(r.job.kind) - r.rss_mb) for r in self._running.values())
        need = max(self.plan.min_available_gb * 1024.0, self.plan.peak_factor * self.ledger.peak_mb(None, self.plan.peak_percentile, self.plan.peak_recent))
        ok = avail - reserve >= need
        return ok, (f"available {avail / 1024:.1f} GB, {reserve / 1024:.1f} GB held back for "
                    f"{len(self._running)} running job(s), need {need / 1024:.1f} GB")

    def sample(self, r: Running) -> None:
        """Update a running job's RSS and peak, children included."""
        if r.ps is None:
            return
        try:
            mi = r.ps.memory_info()
            rss = mi.rss
            peak = getattr(mi, "peak_wset", 0)
            for c in r.ps.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                except psutil.Error:
                    pass
            r.rss_mb = rss / MB
            r.peak_mb = max(r.peak_mb, rss / MB, peak / MB)
        except psutil.Error:
            pass

    # ------------------------------------------------------------- start/finish

    def _row(self, job: Job, **kw) -> dict:
        """Build a ledger row for a job with extra fields."""
        row = {"run_id": job.run_id, "stage": job.stage, "kind": job.kind, "group": job.group, "local": job.local,
               "remote": job.remote, "config": job.config, "tag": job.tag}
        row.update(kw)
        return row

    def _skip(self, job: Job, why: str) -> None:
        """Log and record a skipped job."""
        self.log(f"SKIP {job.run_id}: {why}")
        self.ledger.upsert(self._row(job, status="skipped", error=why, exit_code="", runner_pid=os.getpid()))

    def provisional_reason(self, job: Job) -> str:
        """Return why the job's product would be provisional, or ""."""
        why = []
        if job.kind == "rr" and not self.api["rr"]:
            why.append("process_rr.py read the raw archives (variant API not ready)")
        if job.kind == "stack" and not self.api["stack"]:
            why.append("stack members read raw (variant API not ready in the stack builder)")
        for s in job.input_sites:
            if s.startswith("STK_"):
                row = self.ledger.rows.get(f"s2_build_{s}")
                if row and row["provisional"]:
                    why.append(f"{s} is provisional")
        return "; ".join(why)

    def start(self, job: Job) -> str:
        """Start a job in a child process with its own log.

        Returns:
            str: "started" or "skipped".
        """
        aside = None
        if job.kind == "stack" and job.output is not None and job.output.exists():
            # an earlier (stale or partial) stack of ours: build_synthetic_remote would reuse it
            aside = job.output.with_name(job.output.name + ".old-" + stamp())
            try:
                os.replace(job.output, aside)
            except OSError as exc:
                self._skip(job, f"{job.output.name} is open in another process: {exc}")
                return "skipped"
        log_path = self.dir / "logs" / f"{job.run_id}.log"
        fh = open(log_path, "a", encoding="utf-8")
        fh.write(f"\n=== {now().isoformat(timespec='seconds')} {subprocess.list2cmdline(job.cmd)}\n")
        fh.flush()
        offset = fh.tell()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        inputs = self.inputs(job)
        provisional = self.provisional_reason(job)
        try:
            popen = subprocess.Popen(job.cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT, env=env,
                                     creationflags=flags)
        except OSError as exc:
            fh.close()
            if aside is not None:
                os.replace(aside, job.output)
            self._skip(job, f"could not start: {exc}")
            return "skipped"
        fh.close()
        try:
            ps = psutil.Process(popen.pid)
        except psutil.Error:
            ps = None
        started = now()
        r = Running(job, popen, ps, started, time.monotonic(), log_path, offset, aside)
        self._running[job.run_id] = r
        self.n_started += 1
        self.ledger.upsert(self._row(
            job, status="running", exit_code="", started=started.isoformat(timespec="seconds"), finished="",
            seconds="", peak_rss_mb="", edi="", sidecar="", figure="", archive="", size_mb="", check="", error="",
            log=str(log_path), inputs=inputs, provisional=provisional, runner_pid=os.getpid(),
            child_pid=popen.pid, cmd=subprocess.list2cmdline(job.cmd)))
        what = {"rr": f"{job.local} rr {job.remote} [{job.config}]",
                "variant": f"variant of {job.local} ({job.note})",
                "stack": f"build {job.remote} ({job.note})"}[job.kind]
        self.log(f"START {job.run_id}: {what}" + (f" -- PROVISIONAL: {provisional}" if provisional else "")
                 + f" (pid {popen.pid})")
        return "started"

    def _read_log(self, r: Running) -> str:
        """Return the part of a job's log written by this run."""
        try:
            with open(r.log_path, "rb") as fh:
                fh.seek(r.log_offset)
                return fh.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def finish(self, r: Running, rc: int, interrupted: bool = False) -> bool:
        """Record a finished job in the ledger and check its product.

        Args:
            r (Running): The job.
            rc (int): Exit code.
            interrupted (bool): Whether the runner killed it.

        Returns:
            bool: True when the job succeeded.
        """
        job = r.job
        text = self._read_log(r)
        secs = time.monotonic() - r.t0
        row = self._row(job, exit_code=rc, finished=now().isoformat(timespec="seconds"), seconds=f"{secs:.0f}",
                        peak_rss_mb=f"{r.peak_mb:.0f}")
        ok = rc == 0 and not interrupted
        err = ""
        if job.kind == "rr":
            prod = parse_products(text)
            if ok and not (prod["edi"] and Path(prod["edi"]).exists()):
                ok, err = False, "exit 0 but no `wrote <path>.edi` line naming an existing file"
            if ok and self.plan.move_products:
                prod = self.move_products(job, prod)
            row.update(prod)
        elif job.kind == "variant":
            m = re.findall(r"^variant: (.+?)\s*$", text, flags=re.M)
            path = Path(m[-1]) if m else None
            if ok and (path is None or not path.exists()):
                ok, err = False, f"exit 0 but no `variant: <path>` line naming an existing file ({m[-1] if m else ''})"
            if ok:
                row["archive"] = str(path)
                row["size_mb"] = f"{path.stat().st_size / MB:.0f}"
                declared = self.survey.site(job.local).filters or []
                good, why = archive_filters_check(path, job.local, declared, self.survey.sample_rate)
                row["check"] = ("recorded filters match filters.yaml: " if good else
                                "RECORDED FILTERS DIFFER from filters.yaml: ") + why
                if not good:
                    self.log(f"WARNING {job.run_id}: {path.name}: {row['check']}")
        elif job.kind == "stack":
            out = job.output
            if ok and out.exists():
                row["archive"] = str(out)
                row["size_mb"] = f"{out.stat().st_size / MB:.0f}"
                if r.aside is not None and r.aside.exists():
                    r.aside.unlink()
            else:
                ok = False
                if out.exists():
                    out.unlink()  # removed so the next build starts afresh
        if not ok and not err:
            err = "interrupted" if interrupted else last_error(text) or f"exit code {rc}"
        row["status"] = "done" if ok else ("interrupted" if interrupted else "failed")
        row["error"] = err
        self.ledger.upsert(row)
        tail = ""
        if ok and job.kind == "rr":
            try:
                q = tf_quality(row["edi"], self.pmin, self.pmax)
                tail = f", score {q['overall']['score']:.3f}"
            except Exception as exc:  # a product that cannot be read is reported, not fatal
                tail = f", score unreadable ({exc})"
        elif ok:
            tail = f", {row.get('size_mb', '?')} MB"
        self.log(f"{'DONE' if ok else row['status'].upper()} {job.run_id}: {secs / 60:.1f} min, peak "
                 f"{r.peak_mb / 1024:.1f} GB{tail}" + (f" -- {err}" if err else ""))
        return ok

    def move_products(self, job: Job, prod: dict) -> dict:
        """Move an rr run's EDI, sidecar and figure into <campaign>/tf/.

        A MANTLE run's report JSON and fine-grid EDI, named in its sidecar
        (`mantle_report`, `mantle_fine_edi`), move with them.

        Returns:
            dict: The product paths after the move.
        """
        tf_dir = (self.survey.workspace / "tf").resolve()
        dest_dir = self.dir / "tf"
        out = dict(prod)
        extras: dict[str, str] = {}
        if prod.get("sidecar") and Path(prod["sidecar"]).exists():
            try:
                sidecar = json.loads(Path(prod["sidecar"]).read_text(encoding="utf-8"))
                for key in ("mantle_report", "mantle_fine_edi"):
                    if sidecar.get(key):
                        extras[key] = str(Path(prod["sidecar"]).with_name(str(sidecar[key])))
            except (OSError, ValueError):
                pass
        for key, value in extras.items():
            prod = {**prod, key: value}
        for key in ("edi", "sidecar", "figure", *extras):
            p = Path(prod[key]) if prod[key] else None
            if p is None or not p.exists():
                continue
            if p.resolve().parent != tf_dir or job.tag not in p.name or not p.name.startswith(f"{job.local}_rr-"):
                self.log(f"{job.run_id}: {p} not moved (not this run's product in {tf_dir})")
                continue
            dest = dest_dir / p.name
            if dest.exists():
                self.log(f"{job.run_id}: {dest} exists: {p.name} left in place")
                continue
            shutil.move(str(p), str(dest))
            out[key] = str(dest)
        return out

    # ------------------------------------------------------------------ blocks

    def run_block(self, label: str, jobs: list[Job]) -> None:
        """Run one block of jobs in parallel, respecting dependencies and the memory gate."""
        done, failed = set(), set()
        pending = []
        for job in jobs:
            if self.already_done(job):
                done.add(job.run_id)
            else:
                pending.append(job)
        # a dependency outside this block counts as the ledger records it: done, or failed for good
        ids = {j.run_id for j in jobs}
        for d in {d for j in pending for d in j.deps if d not in ids}:
            row = self.ledger.rows.get(d)
            (done if row and row["status"] == "done" else failed).add(d)
        self.log(f"=== {label}: {len(jobs)} job(s), {len(done)} already done, {len(pending)} to run "
                 f"({self.parallel} at a time)")
        while pending or self._running:
            for rid, r in list(self._running.items()):
                self.sample(r)
                rc = r.popen.poll()
                if rc is not None:
                    (done if self.finish(r, rc) else failed).add(rid)
                    del self._running[rid]
            if self.max_runs is not None and self.n_started >= self.max_runs and pending:
                self.log(f"--max-runs {self.max_runs} reached: {len(pending)} job(s) of {label} not started")
                pending = []
            if pending and len(self._running) < self.parallel:
                job = self._next(pending, done, failed)
                if job is not None:
                    ok, msg = self.gate()
                    if ok:
                        pending.remove(job)
                        if self.start(job) == "skipped":
                            failed.add(job.run_id)
                        continue  # look again at once: another slot may be free
                    if time.time() - self._last_wait_log >= WAIT_LOG_S:
                        self.log(f"slot waiting for memory before {job.run_id}: {msg}")
                        self._last_wait_log = time.time()
                elif not self._running:  # nothing running and nothing startable: the rest is skipped
                    for j in list(pending):
                        pending.remove(j)
                        failed.add(j.run_id)
                        self._skip(j, f"waits for {', '.join(d for d in j.deps if d not in done)}, which cannot run")
            time.sleep(POLL_S)

    def _next(self, pending: list[Job], done: set, failed: set) -> Job | None:
        """Return the next job whose dependencies are done, skipping jobs whose dependencies failed."""
        for job in list(pending):
            bad = [d for d in job.deps if d in failed]
            if bad:
                pending.remove(job)
                failed.add(job.run_id)
                self._skip(job, f"needs {', '.join(bad)}, which did not finish")
                continue
            if all(d in done for d in job.deps):
                return job
        return None

    def interrupt(self) -> None:
        """Kill the running jobs, record them as interrupted and drop partial variants."""
        self.log(f"interrupted: stopping {len(self._running)} running job(s)")
        for rid, r in list(self._running.items()):
            kill_tree(r.popen.pid)
            try:
                rc = r.popen.wait(timeout=30)
            except subprocess.TimeoutExpired:
                rc = -1
            self.finish(r, rc if rc is not None else -1, interrupted=True)
            del self._running[rid]
            if r.job.kind == "variant":
                self.drop_partial_variant(r.job.local, r.started.timestamp(), rid)
        self.ledger.save()

    def drop_partial_variant(self, site: str, t0: float, rid: str) -> None:
        """Delete the variant a killed stage 0 job was writing.

        build_variant writes in place, and a partial file whose first run is
        complete would pass crust.ingest.variant_ready.
        """
        if _api_variant_path is None:
            self.log(f"{rid}: the variant build of {site} was killed; no variant API to locate its file")
            return
        path = _api_variant_path(self.survey, site)
        if path.exists() and path.stat().st_mtime >= t0 - 1.0:
            path.unlink()
            self.log(f"{rid}: deleted {path.name}, written by the killed variant build")

    def cleanup_orphans(self) -> None:
        """Clean up rows left "running" by a runner that died: kill its children, drop partial archives.

        Raises:
            SystemExit: When another campaign runner is still running a row.
        """
        for rid, row in list(self.ledger.rows.items()):
            if row["status"] != "running":
                continue
            rp = int(row["runner_pid"] or 0)
            if rp and rp != os.getpid() and psutil.pid_exists(rp):
                try:
                    if "campaign.py" in " ".join(psutil.Process(rp).cmdline()):
                        raise SystemExit(f"{rid} is being run by another campaign runner (pid {rp})")
                except psutil.Error:
                    pass
            cp = int(row["child_pid"] or 0)
            if cp and psutil.pid_exists(cp):
                try:
                    cmd = " ".join(psutil.Process(cp).cmdline())
                except psutil.Error:
                    cmd = ""
                if row["local"] in cmd and any(s in cmd for s in ("process_rr.py", "build_stack.py", VARIANT_FUNCS[0],
                                                                   "crust.ingest")):
                    self.log(f"{rid}: killing the orphaned child {cp} of a dead runner")
                    kill_tree(cp)
            if row["kind"] == "stack":
                out = self.stack_archive(row["remote"])
                t0 = pd.Timestamp(row["started"]).timestamp() if row["started"] else 0.0
                if out.exists() and out.stat().st_mtime >= t0:
                    out.unlink()
                    self.log(f"{rid}: removed the partial {out.name}")
            if row["kind"] == "variant" and row["started"]:
                self.drop_partial_variant(row["local"], pd.Timestamp(row["started"]).timestamp(), rid)
            self.ledger.upsert({"run_id": rid, "status": "interrupted", "error": f"runner {rp} died"})

    # ------------------------------------------------------------------ reports

    def scores(self, write: bool = True) -> pd.DataFrame:
        """Build the scores.csv frame, rescoring products whose EDI changed, and write it atomically.

        Args:
            write (bool): Whether to write scores.csv.

        Returns:
            pd.DataFrame: One row per scored rr product.
        """
        path = self.dir / "scores.csv"
        cache = {}
        if path.exists():
            try:
                old = pd.read_csv(path, keep_default_na=False, na_values=[""])
                cache = {(r["edi"], int(r["edi_mtime"])): r for r in old.to_dict("records")}
            except (OSError, ValueError, KeyError, pd.errors.EmptyDataError):
                cache = {}
        rows = []
        for row in self.ledger.rows.values():
            if row["kind"] != "rr" or row["status"] != "done" or not row["edi"] or not Path(row["edi"]).exists():
                continue
            edi = Path(row["edi"])
            key = (str(edi), int(edi.stat().st_mtime))
            base = {"run_id": row["run_id"], "stage": int(row["stage"]), "group": row["group"],
                    "local": row["local"], "remote": row["remote"], "config": row["config"],
                    "remote_kind": "stack" if row["remote"].startswith("STK_") else "site",
                    "provisional": row["provisional"], "edi": str(edi), "edi_mtime": key[1]}
            if key in cache:
                rows.append({**cache[key], **base})
                continue
            try:
                q = flat_quality(tf_quality(edi, self.pmin, self.pmax))
                full = tf_quality(edi)["overall"]["score"]
            except Exception as exc:
                self.log(f"scores: {edi.name} unreadable: {exc}")
                continue
            verdict = ""
            if row["sidecar"] and Path(row["sidecar"]).exists():
                try:
                    verdict = json.loads(Path(row["sidecar"]).read_text(encoding="utf-8"))["quadrant"]["verdict"]
                except (OSError, ValueError, KeyError, TypeError):
                    verdict = ""
            rows.append({**base, "verdict": verdict, **q, "score_full": full})
        df = pd.DataFrame(rows)
        if len(df):
            df["provisional"] = df["provisional"].fillna("").astype(str)
        if not write:
            return df
        tmp = path.with_name(path.name + ".tmp")
        df.to_csv(tmp, index=False)
        try:
            os.replace(tmp, path)
        except PermissionError:
            self.log("scores.csv is locked (open in Excel?): not rewritten this time")
        return df

    def report(self, sites=None) -> None:
        """Write scores.csv, the per-site figures for `sites` (all plan sites when None), the line figures and summary.md."""
        df = self.scores()
        write_report(self, df, self.plan.ordered(sites or self.plan.sites))

    # ------------------------------------------------------------------ dry run

    def dry_run(self, stages, sites) -> dict:
        """Print the job matrix with counts and estimated hours, running nothing.

        Returns:
            dict: {"counts", "total", "hours"}.
        """
        api = self.check_api()
        print(f"variant API: {api['func'] or 'not in crust.ingest yet'}; process_rr.py uses it: {api['rr']}; "
              f"stack builder uses it: {api['stack']}" + (f"  ({api['why']})" if api["why"] else ""))
        counts: dict[int, dict[str, int]] = {}
        todo_min = 0.0
        for label, st, g, gs, jobs in self.blocks(stages, sites, dry=True):
            n_done = sum(self.already_done(j) for j in jobs)
            by_kind = {k: sum(j.kind == k for j in jobs) for k in KINDS if any(j.kind == k for j in jobs)}
            wait = "" if api[NEEDS[st]] else "  [waits for the variant API]" if st != 2 else \
                "  [deferred to the end until the stack builder uses the variant API]"
            print(f"\n{label}: {len(jobs)} job(s) ({', '.join(f'{v} {k}' for k, v in by_kind.items()) or 'none'})"
                  + (f", {n_done} already done" if n_done else "") + wait)
            for j in jobs:
                done = self.already_done(j)
                if j.kind == "rr":
                    ov = overlap_hours(self.spans[j.local], self.spans[j.remote]) if j.remote in self.spans else None
                    km = _km(self.survey, j.local, j.remote) if j.remote in self.spans else None
                    extra = " ".join(self.plan.configs.get(j.config, [])) if j.config != "default" else "defaults"
                    info = f"{j.local} rr {j.remote} [{extra}]" + (f" ({ov:.1f} h overlap, {km:.1f} km)" if ov else "")
                elif j.kind == "stack":
                    info = f"{j.remote}: {j.note}"
                else:
                    row = self.ledger.rows.get(j.run_id) or {}
                    have = f"built: {Path(row['archive']).name}" if done else "to build"
                    info = f"variant {j.local} (filters {j.config}, {j.note}): {have}"
                print(f"  {'done ' if done else ''}{j.run_id:<34} {info}")
                c = counts.setdefault(st, {k: 0 for k in KINDS})
                if not done:
                    c[j.kind] += 1
                    todo_min += self.plan.minutes.get(j.kind, 8.0)
        print("\ntotals (still to run):")
        total = {k: 0 for k in KINDS}
        for st in sorted(counts):
            c = counts[st]
            print(f"  stage {st} {STAGES[st]:<8}: " + (", ".join(f"{v} {k}" for k, v in c.items() if v) or "nothing"))
            for k in KINDS:
                total[k] += c[k]
        hours = todo_min / self.parallel / 60.0
        mins = ", ".join(f"{self.plan.minutes.get(k, 8.0):g} min per {k}" for k in KINDS)
        print(f"  all: {total['rr']} rr run(s), {total['variant']} variant build(s), {total['stack']} stack "
              f"build(s); at {mins} over {self.parallel} slot(s): {hours:.1f} h (more when the memory gate "
              f"holds a slot or the variant API is not there yet)")
        return {"counts": counts, "total": total, "hours": hours}


def choose_best(s1: pd.DataFrame, tie_tolerance: float, pmin=None, pmax=None) -> dict | None:
    """Choose the best stage 1 remote from a site's scores.

    The highest score wins; among remotes within `tie_tolerance` of it, the
    one with the lowest median |dlog10 rho| against the site's other stage 1
    products is chosen.

    Args:
        s1 (pd.DataFrame): The site's stage 1 scores.
        tie_tolerance (float): Score margin counted as a tie.
        pmin (float | None): Shortest period of the agreement window.
        pmax (float | None): Longest period of the agreement window.

    Returns:
        dict | None: {"remote", "score", "why"}, or None without scores.
    """
    if s1 is None or len(s1) == 0:
        return None
    s1 = s1.sort_values("score", ascending=False)
    top = float(s1["score"].iloc[0])
    tied = s1[s1["score"] >= top - tie_tolerance]
    if len(tied) == 1 or len(s1) < 3:
        r = s1.iloc[0]
        return {"remote": r["remote"], "score": float(r["score"]), "why": "highest score"}
    best, best_d = None, None
    for _, cand in tied.iterrows():
        others = [o for o in s1["edi"] if o != cand["edi"]]
        d = np.nanmedian([agreement(cand["edi"], o, pmin, pmax)["overall"]["dlog_rho"] for o in others])
        if best_d is None or d < best_d:
            best, best_d = cand, d
    return {"remote": best["remote"], "score": float(best["score"]),
            "why": f"{len(tied)} within {tie_tolerance:g} of the top ({top:.3f}); median |dlog10 rho| "
                   f"to the other remotes {best_d:.3f}"}


# ------------------------------------------------------------------- report

# the dark-neutral look of scripts/compare_unmerged.py
DARK = {
    "figure.facecolor": "#1f1f1f", "figure.edgecolor": "#1f1f1f",
    "axes.facecolor": "#1f1f1f", "axes.edgecolor": "#c8c8c8",
    "axes.labelcolor": "#e6e6e6", "axes.titlecolor": "#e6e6e6",
    "text.color": "#e6e6e6",
    "xtick.color": "#c8c8c8", "ytick.color": "#c8c8c8",
    "grid.color": "#4a4a4a",
    "legend.facecolor": "#1f1f1f", "legend.edgecolor": "#555555", "legend.labelcolor": "#e6e6e6",
    "savefig.facecolor": "#1f1f1f", "savefig.edgecolor": "#1f1f1f",
}
PALETTE = ["#4fc3f7", "#ff5252", "#ffd54f", "#81c784", "#ba68c8", "#ff8a65", "#4db6ac", "#f06292",
           "#aed581", "#9575cd", "#e0e0e0", "#ffb74d", "#64b5f6", "#a1887f"]
BEST_COLOUR = "#ffffff"


def _plt():
    """Import matplotlib.pyplot on the Agg backend."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _phase_display(phi: np.ndarray, mode: str) -> np.ndarray:
    """Return a phase as the MT plots show it: xy as is, yx + 180, both wrapped to [-180, 180)."""
    f = np.asarray(phi, dtype=float) + (180.0 if mode == "yx" else 0.0)
    return (f + 180.0) % 360.0 - 180.0


def _draw(ax_rho, ax_phi, edi, colour, label, bold=False, errors=False) -> None:
    """Draw an EDI's apparent resistivity and phase of both modes."""
    p, rho, phi, rerr, perr = curves(edi)
    kw = dict(color=colour, lw=2.0 if bold else 0.9, ms=3.2 if bold else 2.0, alpha=1.0 if bold else 0.85,
              zorder=5 if bold else 2)
    for col, (mode, (i, j)) in enumerate(MODES.items()):
        r = rho[:, i, j]
        f = _phase_display(phi[:, i, j], mode)
        ok = np.isfinite(r) & (r > 0) & np.isfinite(f)
        if errors:
            ax_rho[col].errorbar(p[ok], r[ok], yerr=np.minimum(rerr[ok, i, j], 0.95 * r[ok]), fmt="o-",
                                 elinewidth=0.6, capsize=0, label=label if col == 0 else None, **kw)
            ax_phi[col].errorbar(p[ok], f[ok], yerr=perr[ok, i, j], fmt="o-", elinewidth=0.6, capsize=0, **kw)
        else:
            ax_rho[col].plot(p[ok], r[ok], "o-", label=label if col == 0 else None, **kw)
            ax_phi[col].plot(p[ok], f[ok], "o-", **kw)


def _style(ax_rho, ax_phi, xlabel: bool = True) -> None:
    """Set scales, limits, grids and labels of the rho and phase axes."""
    for col, mode in enumerate(MODES):
        a, b = ax_rho[col], ax_phi[col]
        a.set_xscale("log")
        a.set_yscale("log")
        a.grid(True, which="both", alpha=0.3)
        a.set_title(f"{mode}" + ("" if mode == "xy" else "  (phase shown + 180)"))
        b.set_xscale("log")
        b.set_ylim(-30, 120)
        b.axhspan(0, 90, color="#ffffff", alpha=0.05, lw=0)
        b.grid(True, which="both", alpha=0.3)
        if xlabel:
            b.set_xlabel("period (s)")
    ax_rho[0].set_ylabel("apparent resistivity (ohm m)")
    ax_phi[0].set_ylabel("phase (deg)")


def _legend(fig, ax, title: str) -> None:
    """Place the figure legend outside the axes, top right."""
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="outside right upper", fontsize=8, title=title, title_fontsize=8)


def _window_text(c: "Campaign") -> str:
    """Describe the scoring window, e.g. "0.01-1000 s"."""
    return f"{c.pmin:g}-{c.pmax:g} s" if c.pmin is not None and c.pmax is not None else "all periods"


def _is_provisional(r) -> bool:
    """Check whether a scores row is provisional."""
    v = r.get("provisional")
    return isinstance(v, str) and bool(v.strip())


def fig_remotes(c: "Campaign", df: pd.DataFrame, site: str, best: str | None, out: Path) -> bool:
    """Draw every stage 1 remote of `site` together, with scores in the legend and where they agree.

    Args:
        c (Campaign): The campaign; its scoring window is named in the title.
        df (pd.DataFrame): The scored products (`Campaign.scores`).
        site (str): Local site.
        best (str | None): The site's best stage 1 remote
            (`Campaign.best_remotes`), or None; drawn bold, with
            error bars.
        out (Path): Path of the PNG.

    Returns:
        bool: False when the site has no stage 1 product.
    """
    s1 = df[(df["stage"] == 1) & (df["local"] == site)].sort_values("score", ascending=False) if len(df) else df
    if len(s1) == 0:
        return False
    plt = _plt()
    with plt.rc_context(DARK):
        fig, ax = plt.subplots(3, 2, figsize=(15, 11), sharex=True, height_ratios=[2.2, 1.3, 1.0],
                               layout="constrained")
        for k, (_, r) in enumerate(s1.iterrows()):
            is_best = r["remote"] == best
            label = f"{r['remote']:<7} {r['score']:.2f}" + ("  best" if is_best else "") + \
                ("  [provisional]" if _is_provisional(r) else "")
            _draw(ax[0], ax[1], r["edi"], BEST_COLOUR if is_best else PALETTE[k % len(PALETTE)], label,
                  bold=is_best, errors=is_best)
        _style(ax[0], ax[1], xlabel=False)
        sp = pairwise_spread(list(s1["edi"])) if len(s1) >= 2 else None
        for col, mode in enumerate(MODES):
            a = ax[2][col]
            a.set_xscale("log")
            a.set_xlabel("period (s)")
            a.grid(True, which="both", alpha=0.3)
            if sp is None:
                a.text(0.5, 0.5, "one remote only: nothing to compare", transform=a.transAxes, ha="center")
                continue
            agree = (sp["dlog_rho"][mode] < 0.1) & (sp["dphase"][mode] < 5.0)
            a.fill_between(sp["period"], 0, 1, where=agree, step="mid", color="#66bb6a", alpha=0.22, lw=0,
                           transform=a.get_xaxis_transform(), label="remotes agree (< 0.1 dex and < 5 deg)")
            a.plot(sp["period"], sp["dlog_rho"][mode], "-", color="#ffd54f", lw=1.4,
                   label="median over remote pairs |dlog10 rho|")
            a.axhline(0.1, color="#ffd54f", lw=0.7, ls=":")
            a.set_ylim(0, 1.0)
            a.set_ylabel("|dlog10 rho| (dex)")
            b = a.twinx()
            b.plot(sp["period"], sp["dphase"][mode], "--", color="#80cbc4", lw=1.1, label="median over pairs |dphase|")
            b.set_ylim(0, 45)
            b.set_ylabel("|dphase| (deg)", color="#80cbc4")
            b.tick_params(axis="y", colors="#80cbc4")
            if col == 0:
                h1, l1 = a.get_legend_handles_labels()
                h2, l2 = b.get_legend_handles_labels()
                a.legend(h1 + h2, l1 + l2, fontsize=7, loc="upper left")
        _legend(fig, ax[0][0], "remote   score")
        fig.suptitle(f"{site}: every remote, stage 1 defaults ({len(s1)} runs). score: crust.quality over "
                     f"{_window_text(c)}; bottom row: where the remotes agree", fontsize=11)
        fig.savefig(out, dpi=110)
        plt.close(fig)
    return True


def fig_stacks(c: "Campaign", df: pd.DataFrame, site: str, best: str | None, out: Path) -> bool:
    """Draw the best single remote against the stacks (stage 2).

    Args:
        c (Campaign): The campaign; its plan gives the stack weightings
            and members.
        df (pd.DataFrame): The scored products (`Campaign.scores`).
        site (str): Local site.
        best (str | None): The site's best stage 1 remote
            (`Campaign.best_remotes`), or None; drawn bold, with
            error bars.
        out (Path): Path of the PNG.

    Returns:
        bool: False when the site has no stage 2 product.
    """
    if len(df) == 0:
        return False
    s2 = df[(df["stage"] == 2) & (df["local"] == site)].sort_values("remote")
    b1 = df[(df["stage"] == 1) & (df["local"] == site) & (df["remote"] == best)]
    if len(s2) == 0:
        return False
    plt = _plt()
    with plt.rc_context(DARK):
        fig, ax = plt.subplots(2, 2, figsize=(15, 8.5), sharex=True, height_ratios=[2, 1.2], layout="constrained")
        if len(b1):
            r = b1.iloc[0]
            _draw(ax[0], ax[1], r["edi"], BEST_COLOUR, f"best single: {best}  {r['score']:.2f}", bold=True, errors=True)
        for k, (_, r) in enumerate(s2.iterrows()):
            w = c.plan.weightings.get(r["remote"][-1], "?")
            _draw(ax[0], ax[1], r["edi"], ("#4fc3f7", "#ff8a65", "#81c784")[k % 3],
                  f"{r['remote']} ({w})  {r['score']:.2f}", errors=True)
        _style(ax[0], ax[1])
        _legend(fig, ax[0][0], "remote   score")
        sp = stack_plan(c.plan, c.spans, site)
        members = "no stack plan" if sp is None else f"members {' '.join(sp['members'])}" + \
            (f" (borrowed group {sp['group']})" if sp["borrowed"] else "")
        fig.suptitle(f"{site}: best single remote vs the leave-one-out stacks ({members})", fontsize=11)
        fig.savefig(out, dpi=110)
        plt.close(fig)
    return True


def fig_options(c: "Campaign", df: pd.DataFrame, site: str, best: str | None, out: Path) -> bool:
    """Draw the best remote's stage 3 configs over its stage 1 default.

    Args:
        c (Campaign): The campaign; its plan's configs set the order.
        df (pd.DataFrame): The scored products (`Campaign.scores`).
        site (str): Local site.
        best (str | None): The site's best stage 1 remote
            (`Campaign.best_remotes`), or None (no figure).
        out (Path): Path of the PNG.

    Returns:
        bool: False when the site has no stage 3 product.
    """
    if len(df) == 0 or not best:
        return False
    base = df[(df["stage"] == 1) & (df["local"] == site) & (df["remote"] == best)]
    s3 = df[(df["stage"] == 3) & (df["local"] == site) & (df["remote"] == best)]
    if len(s3) == 0:
        return False
    b = float(base["score"].iloc[0]) if len(base) else float("nan")
    plt = _plt()
    with plt.rc_context(DARK):
        fig, ax = plt.subplots(2, 2, figsize=(15, 8.5), sharex=True, height_ratios=[2, 1.2], layout="constrained")
        if len(base):
            _draw(ax[0], ax[1], base["edi"].iloc[0], BEST_COLOUR, f"default     {b:.2f}", bold=True, errors=True)
        order = list(c.plan.configs)
        s3 = s3.assign(_o=s3["config"].map(lambda x: order.index(x) if x in order else 99)).sort_values("_o")
        for k, (_, r) in enumerate(s3.iterrows()):
            d = r["score"] - b
            _draw(ax[0], ax[1], r["edi"], PALETTE[k % len(PALETTE)], f"{r['config']:<11} {r['score']:.2f} ({d:+.2f})")
        _style(ax[0], ax[1])
        _legend(fig, ax[0][0], "config   score (vs default)")
        fig.suptitle(f"{site} rr {best}: estimator and band options (stage 3) over the defaults", fontsize=11)
        fig.savefig(out, dpi=110)
        plt.close(fig)
    return True


def best_products(df: pd.DataFrame) -> dict:
    """Return each site's highest-scoring product row, any stage: {site: row}."""
    if len(df) == 0:
        return {}
    return {s: g.sort_values("score", ascending=False).iloc[0] for s, g in df.groupby("local")}


def _label(r) -> str:
    """Label a product as <remote> or <remote>/<config>."""
    return r["remote"] + ("" if r["config"] in ("default", "") else f"/{r['config']}")


def fig_pseudosection(c: "Campaign", df: pd.DataFrame, out: Path) -> bool:
    """Draw rho_xy, rho_yx and both phases of each site's best product along the line, log period down.

    Returns:
        bool: False when no product is scored.
    """
    best = best_products(df)
    if not best:
        return False
    sites = list(c.plan.sites)
    lo, hi = np.inf, -np.inf
    for r in best.values():
        p = curves(r["edi"])[0]
        lo, hi = min(lo, p.min()), max(hi, p.max())
    grid = np.arange(np.floor(np.log10(lo) * 10), np.ceil(np.log10(hi) * 10) + 1) / 10.0
    data = {k: np.full((grid.size, len(sites)), np.nan) for k in ("rxy", "ryx", "pxy", "pyx")}
    for col, s in enumerate(sites):
        if s not in best:
            continue
        p, rho, phi, _, _ = curves(best[s]["edi"])
        lp = np.log10(p)
        for mode, (i, j) in MODES.items():
            r = rho[:, i, j]
            f = _phase_display(phi[:, i, j], mode)
            ok = np.isfinite(r) & (r > 0) & np.isfinite(f)
            if ok.sum() < 2:
                continue
            inside = (grid >= lp[ok].min()) & (grid <= lp[ok].max())
            data[f"r{mode}"][inside, col] = np.interp(grid[inside], lp[ok], np.log10(r[ok]))
            data[f"p{mode}"][inside, col] = np.interp(grid[inside], lp[ok], f[ok])
    rr = np.concatenate([data["rxy"][np.isfinite(data["rxy"])], data["ryx"][np.isfinite(data["ryx"])]])
    rlim = (np.percentile(rr, 2), np.percentile(rr, 98)) if rr.size else (0, 4)
    plt = _plt()
    with plt.rc_context(DARK):
        fig, ax = plt.subplots(2, 2, figsize=(17, 10), sharex=True, sharey=True, layout="constrained")
        xe = np.arange(len(sites) + 1) - 0.5
        ye = np.concatenate([[grid[0] - 0.05], (grid[1:] + grid[:-1]) / 2, [grid[-1] + 0.05]])
        panels = (("rxy", "log10 rho_xy (ohm m)", "Spectral", rlim), ("ryx", "log10 rho_yx (ohm m)", "Spectral", rlim),
                  ("pxy", "phase xy (deg)", "Spectral_r", (0, 90)), ("pyx", "phase yx + 180 (deg)", "Spectral_r", (0, 90)))
        for a, (key, title, cmap, lim) in zip(ax.flat, panels):
            cm = plt.get_cmap(cmap).copy()
            cm.set_bad("#2b2b2b")
            m = a.pcolormesh(xe, ye, np.ma.masked_invalid(data[key]), cmap=cm, vmin=lim[0], vmax=lim[1])
            fig.colorbar(m, ax=a, shrink=0.9, label=title)
            a.set_title(title)
            a.set_xticks(range(len(sites)))
            a.set_xticklabels(sites, rotation=90, fontsize=8)
            a.set_ylabel("log10 period (s)")
        ax[0][0].invert_yaxis()
        for col, s in enumerate(sites):
            if s in best:
                ax[0][0].text(col, ye[0], f" {_label(best[s])} {best[s]['score']:.2f}", rotation=90, va="bottom",
                              ha="center", fontsize=6.5, color="#bdbdbd", clip_on=False)
        fig.suptitle(f"{c.plan.name}: best product per site (highest score, any stage), sites in order along "
                     f"the line; grey = no product or outside its band", fontsize=11)
        fig.savefig(out, dpi=110)
        plt.close(fig)
    return True


def fig_scores(c: "Campaign", df: pd.DataFrame, bests: dict, out: Path) -> bool:
    """Draw sites x remotes (stage 1 and the stacks) and sites x configs (stage 3), coloured by score.

    Returns:
        bool: False when no product is scored.
    """
    if len(df) == 0:
        return False
    sites = list(c.plan.sites)
    rem_cols = sites + [f"STK {sfx}" for sfx in c.plan.weightings]
    m1 = np.full((len(sites), len(rem_cols)), np.nan)
    cfg_cols = ["default"] + list(c.plan.configs)
    m3 = np.full((len(sites), len(cfg_cols)), np.nan)
    for _, r in df.iterrows():
        if r["local"] not in sites:
            continue
        i = sites.index(r["local"])
        if r["stage"] == 1 and r["remote"] in sites:
            m1[i, rem_cols.index(r["remote"])] = r["score"]
        elif r["stage"] == 2 and str(r["remote"]).startswith("STK_"):
            key = f"STK {r['remote'][-1]}"
            if key in rem_cols:
                m1[i, rem_cols.index(key)] = r["score"]
        best = bests.get(r["local"], {}).get("remote")
        if best and r["remote"] == best:
            if r["stage"] == 1:
                m3[i, 0] = r["score"]
            elif r["stage"] == 3 and r["config"] in cfg_cols:
                m3[i, cfg_cols.index(r["config"])] = r["score"]
    plt = _plt()
    with plt.rc_context(DARK):
        fig, ax = plt.subplots(1, 2, figsize=(22, 10), width_ratios=[len(rem_cols), len(cfg_cols) + 2],
                               layout="constrained")
        cm = plt.get_cmap("viridis").copy()
        cm.set_bad("#2b2b2b")
        for a, m, cols, title in ((ax[0], m1, rem_cols, "stage 1 remotes (and stage 2 stacks): score"),
                                  (ax[1], m3, cfg_cols, "stage 3 options on each site's best remote: score")):
            im = a.imshow(np.ma.masked_invalid(m), cmap=cm, vmin=0, vmax=1, aspect="auto")
            a.set_xticks(range(len(cols)))
            a.set_xticklabels(cols, rotation=90, fontsize=8)
            a.set_yticks(range(len(sites)))
            a.set_yticklabels([f"{s} ({bests.get(s, {}).get('remote', '-')})" if a is ax[1] else s for s in sites],
                              fontsize=8)
            a.set_title(title)
            for (i, j), v in np.ndenumerate(m):
                if np.isfinite(v):
                    a.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6.5,
                           color="#000000" if v > 0.6 else "#ffffff")
            fig.colorbar(im, ax=a, shrink=0.6, label="score")
        ax[0].set_xlabel("remote")
        ax[0].set_ylabel("local site (along the line)")
        ax[1].set_xlabel("config")
        fig.suptitle(f"{c.plan.name}: crust.quality score of every product ({_window_text(c)})", fontsize=11)
        fig.savefig(out, dpi=100)
        plt.close(fig)
    return True


def _fmt(v, spec=".3f") -> str:
    """Format a number, "-" for None or non-finite values."""
    try:
        return "-" if v is None or not np.isfinite(float(v)) else format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def write_summary(c: "Campaign", df: pd.DataFrame, bests: dict, out: Path) -> None:
    """Write summary.md: the exclusions, stage 0's variants, the best remote/stack/options per site, and line-wide options.

    Args:
        c (Campaign): The campaign: its plan, ledger, spans and scoring
            window.
        df (pd.DataFrame): The scored products (`Campaign.scores`).
        bests (dict): Each site's best stage 1 remote,
            ``{site: {"remote", "score", "why"}}`` (`Campaign.best_remotes`).
        out (Path): Path of summary.md, written through a temporary file.
    """
    plan, rows = c.plan, list(c.ledger.rows.values())
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    L = [f"# Campaign {plan.name}", ""]
    if plan.description:
        L += [plan.description, ""]
    L += [f"Written {now().isoformat(timespec='seconds')} from `ledger.csv` ({len(rows)} rows: "
          + (", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) or "none") + ").",
          f"Scores: `crust.quality.tf_quality` over {_window_text(c)}: score = Q x S x exp(-5 B / N) "
          "(Q the fraction of periods in the physical phase quadrant, S the mean per-step smoothness "
          "exp(-(|dlog10 rho| / 0.25)^2), B blow-ups out of N periods), mean of xy and yx; higher is better. "
          "The figures are the judgement; the score only ranks.", ""]
    L += ["## Excluded", ""] + [f"- **{s}**: {r}" for s, r in plan.exclude.items()] + [""]

    L += ["## Stage 0: filtered variants", "",
          "Raw archives (`<workspace>/mth5/<site>.h5`) are never rebuilt; each site's filtered variant is built "
          "from it by `crust.ingest` and its recorded filters compared with filters.yaml (`check`).", "",
          "| site | status | variant | started | minutes | size MB | peak RSS GB | check / error |",
          "|---|---|---|---|---|---|---|---|"]
    for s in plan.ordered(plan.sites):
        r = c.ledger.rows.get(f"s0_{s}")
        if r:
            mins = _fmt(float(r["seconds"]) / 60.0, ".1f") if r["seconds"] else "-"
            peak = _fmt(float(r["peak_rss_mb"]) / 1024.0, ".1f") if r["peak_rss_mb"] else "-"
            note = (r["check"] or r["error"] or "").replace("|", "/")[:160]
            L.append(f"| {s} | {r['status']} | {Path(r['archive']).name if r['archive'] else '-'} | {r['started']} | "
                     f"{mins} | {r['size_mb'] or '-'} | {peak} | {note} |")
        else:
            L.append(f"| {s} | not run | - | - | - | - | - | - |")
    L.append("")

    L += ["## Per site", "",
          "| site | group | best remote | score | why | best stack | stack score | stack - best | "
          "options moving the score by > 0.05 |", "|---|---|---|---|---|---|---|---|---|"]
    opt_delta: dict[str, list[float]] = {k: [] for k in plan.configs}
    for s in plan.ordered(plan.sites):
        b = bests.get(s)
        sdf = df[df["local"] == s] if len(df) else df
        if not b:
            n1 = int((sdf["stage"] == 1).sum()) if len(sdf) else 0
            L.append(f"| {s} | {plan.group_of(s)} | - | - | {n1} stage 1 product(s) | - | - | - | - |")
            continue
        base = sdf[(sdf["stage"] == 1) & (sdf["remote"] == b["remote"])]
        bscore = float(base["score"].iloc[0]) if len(base) else float("nan")
        st2 = sdf[sdf["stage"] == 2].sort_values("score", ascending=False)
        stack, sscore = (st2["remote"].iloc[0], float(st2["score"].iloc[0])) if len(st2) else ("-", float("nan"))
        moved = []
        for _, r in sdf[(sdf["stage"] == 3) & (sdf["remote"] == b["remote"])].iterrows():
            d = float(r["score"]) - bscore
            if r["config"] in opt_delta and np.isfinite(d):
                opt_delta[r["config"]].append(d)
            if np.isfinite(d) and abs(d) > 0.05:
                moved.append(f"{r['config']} {d:+.2f}")
        L.append(f"| {s} | {plan.group_of(s)} | {b['remote']} | {_fmt(bscore)} | {b.get('why', '')} | {stack} | "
                 f"{_fmt(sscore)} | {_fmt(sscore - bscore, '+.3f')} | {', '.join(moved) or 'none'} |")
    L.append("")

    L += ["## Options, line-wide (score change vs the default on each site's best remote)", "",
          "| config | flags | helped (> +0.05) | hurt (< -0.05) | within 0.05 | median change | sites |",
          "|---|---|---|---|---|---|---|"]
    ranked = sorted(opt_delta.items(), key=lambda kv: -sum(d > 0.05 for d in kv[1]))
    for k, ds in ranked:
        ds = np.asarray(ds, dtype=float)
        L.append(f"| {k} | `{' '.join(plan.configs[k])}` | {int((ds > 0.05).sum())} | {int((ds < -0.05).sum())} | "
                 f"{int((np.abs(ds) <= 0.05).sum())} | {_fmt(np.median(ds) if ds.size else np.nan, '+.3f')} | {ds.size} |")
    L += ["", "The per-decade configs change the band layout, so their score is over other periods; a "
          "max-period config is scored over the same window as the rest (its longer periods show in the "
          "figure only).", ""]

    L += ["## Stacks", "", "| site | members | group | common span (h) |", "|---|---|---|---|"]
    for s in plan.ordered(plan.sites):
        sp = stack_plan(plan, c.spans, s)
        if sp is None:
            L.append(f"| {s} | none possible | - | - |")
        else:
            L.append(f"| {s} | {' '.join(sp['members'])} | {sp['group']}{' (borrowed)' if sp['borrowed'] else ''} | "
                     f"{sp['span_h']:.1f} |")
    L.append("")

    prov = [r for r in rows if r["provisional"] and r["status"] == "done"]
    if prov:
        L += [f"## Provisional ({len(prov)}): run with --allow-raw, redone by the next run without it", ""]
        L += [f"- `{r['run_id']}`: {r['provisional']}" for r in prov] + [""]
    bad = [r for r in rows if r["status"] in ("failed", "skipped", "interrupted")]
    L += [f"## Not done ({len(bad)})", ""]
    L += [f"- `{r['run_id']}` {r['status']}: {(r['error'] or '')[:200]}" for r in bad] or ["none"]
    L.append("")
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("\n".join(L) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def write_report(c: "Campaign", df: pd.DataFrame, sites) -> None:
    """Write the per-site figures for `sites`, the two line figures and summary.md."""
    figs = c.dir / "figures"
    bests = c.best_remotes(c.plan.sites, persist=False, df=df)
    n = 0
    for s in sites:
        b = bests.get(s, {}).get("remote")
        for fn, suffix in ((fig_remotes, "remotes"), (fig_stacks, "stacks"), (fig_options, "options")):
            try:
                n += bool(fn(c, df, s, b, figs / f"{s}_{suffix}.png"))
            except Exception as exc:  # a broken product is logged and the report continues
                c.log(f"report: {s}_{suffix}.png failed: {type(exc).__name__}: {exc}")
    try:
        n += bool(fig_pseudosection(c, df, figs / f"{c.plan.name}_best_pseudosection.png"))
    except Exception as exc:
        c.log(f"report: {c.plan.name}_best_pseudosection.png failed: {type(exc).__name__}: {exc}")
    try:
        n += bool(fig_scores(c, df, bests, figs / f"{c.plan.name}_scores.png"))
    except Exception as exc:
        c.log(f"report: {c.plan.name}_scores.png failed: {type(exc).__name__}: {exc}")
    write_summary(c, df, bests, c.dir / "summary.md")
    c.log(f"report: {len(df)} scored product(s), {n} figure(s) in {figs}, {c.dir / 'summary.md'}")


# ---------------------------------------------------------------------- CLI


def parse_stages(text: str) -> list[int]:
    """Parse --stage, e.g. "0,1,2,3".

    Raises:
        argparse.ArgumentTypeError: On an unknown stage.
    """
    out = sorted({int(x) for x in re.split(r"[,\s]+", text.strip()) if x})
    bad = [s for s in out if s not in STAGES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown stage(s) {bad}; stages are {sorted(STAGES)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of campaign.py."""
    p = argparse.ArgumentParser(prog="campaign.py",
                                description=next(line for line in __doc__.strip().splitlines() if line.strip()),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("survey_yaml")
    p.add_argument("plan_yaml")
    p.add_argument("--stage", type=parse_stages, default=[0, 1, 2, 3], help="e.g. 0,1,2,3 (default all)")
    p.add_argument("--sites", nargs="+", default=None, help="local sites to run (default: the plan's)")
    p.add_argument("--parallel", type=int, default=2, help="jobs at once (default 2)")
    p.add_argument("--max-runs", type=int, default=None, help="start at most N jobs (smoke checks)")
    p.add_argument("--allow-raw", action="store_true",
                   help="do not wait for the variant API: run on raw archives, rows marked provisional "
                        "(smoke checks only; redone by the next run without it)")
    p.add_argument("--dry-run", action="store_true", help="print the matrix, counts and hours; run nothing")
    p.add_argument("--report", action="store_true", help="rebuild scores, figures and summary from the ledger")
    return p


def run_campaign(c: Campaign, stages, sites) -> None:
    """Run every block in order; a stage 2 whose stack builder is not on the variant API waits at the end."""
    deferred = []
    for label, st, g, gs, jobs in c.blocks(stages, sites):
        if c.max_runs is not None and c.n_started >= c.max_runs:
            break
        need = NEEDS[st]
        if not c.check_api()[need] and st == 2 and not c.allow_raw:
            c.log(f"{label}: deferred to the end: {c.api['why']}")
            deferred.append((label, gs))
            continue
        if st == 0 and not c.api["variant"] and c.allow_raw:
            c.log(f"{label}: skipped: {c.api['why']} (--allow-raw; process_rr.py builds variants on first use)")
            continue
        c.wait_ready(need, label)
        if st == 0:
            jobs = c.stage0_jobs(gs)  # with the function the API actually offers
        c.run_block(label, jobs)
        try:
            c.report(gs if st else None)
        except Exception as exc:  # a failed figure is logged and the campaign continues
            c.log(f"report after {label} failed: {type(exc).__name__}: {exc}")
    for label, gs in deferred:
        if c.max_runs is not None and c.n_started >= c.max_runs:
            break
        c.wait_ready("stack", label)
        c.refresh()
        c.run_block(label + " (deferred)", c.stage2_jobs(gs))
        try:
            c.report(gs)
        except Exception as exc:
            c.log(f"report after {label} failed: {type(exc).__name__}: {exc}")


def main(argv=None) -> int:
    """Run, dry-run or report a campaign.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 2 for sites not in the plan, 3 when another
        runner holds the lock, 130 when interrupted.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    plan = load_plan(args.plan_yaml)
    if args.sites:
        unknown = [s for s in args.sites if s not in plan.sites]
        if unknown:
            why = "; ".join(f"{s}: {plan.exclude[s]}" for s in unknown if s in plan.exclude)
            print(f"ERROR sites not in the plan: {unknown}" + (f" ({why})" if why else ""), file=sys.stderr)
            return 2
    sites = args.sites or plan.sites
    c = Campaign(args.survey_yaml, plan, parallel=args.parallel, max_runs=args.max_runs, allow_raw=args.allow_raw,
                 create=not args.dry_run)
    if args.report:
        c.report(sites if args.sites else None)
        print(f"report: {c.dir / 'summary.md'}")
        return 0
    if args.dry_run:
        print(f"campaign {plan.name}: {len(plan.sites)} sites, groups "
              + ", ".join(f"{g} ({len(m)})" for g, m in plan.groups.items())
              + "; excluded: " + ("; ".join(f"{s}: {r}" for s, r in plan.exclude.items()) or "none"))
        c.dry_run(args.stage, sites)
        return 0

    lock = c.dir / "runner.lock"
    if lock.exists():
        try:
            other = json.loads(lock.read_text(encoding="utf-8"))
            pid = int(other.get("pid", 0))
            if pid and pid != os.getpid() and psutil.pid_exists(pid) and \
                    "campaign.py" in " ".join(psutil.Process(pid).cmdline()):
                print(f"ERROR another runner (pid {pid}, since {other.get('started')}) holds {lock}", file=sys.stderr)
                return 3
        except (ValueError, OSError, psutil.Error):
            pass
    lock.write_text(json.dumps({"pid": os.getpid(), "started": now().isoformat(timespec="seconds"),
                                "argv": sys.argv}) + "\n", encoding="utf-8")

    def _raise(signum, frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _raise)
    c.log(f"campaign {plan.name}: pid {os.getpid()}, stages {args.stage}, sites {', '.join(plan.ordered(sites))}, "
          f"parallel {c.parallel}" + (f", max-runs {args.max_runs}" if args.max_runs else "")
          + (", --allow-raw (PROVISIONAL products)" if args.allow_raw else ""))
    rc = 0
    try:
        c.cleanup_orphans()
        run_campaign(c, args.stage, sites)
        c.log(f"campaign {plan.name}: finished this invocation ({c.n_started} job(s) started)")
    except KeyboardInterrupt:
        c.interrupt()
        rc = 130
    finally:
        try:
            if json.loads(lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                lock.unlink()
        except (OSError, ValueError):
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
