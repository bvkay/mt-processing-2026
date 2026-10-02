# -*- coding: utf-8 -*-
"""
Time the whole pipeline on site pairs, from the raw files to the products

For each pair, in the order given and one step at a time, the script runs:

- `ingest`: the raw archive of the local and of the remote from the raw
  recorder files (scripts/ingest_site.py <site> --raw; --force when the
  archive exists). A site already ingested earlier in the same call is not
  ingested again.
- `variant`: the filtered variant of each of them
  (`mt_workbench.ingest.build_variant`, as the campaign runs it). A site
  that declares no filters has no variant; its row says so and takes no
  time.
- `stack`: when the remote is a stack named by --stack, its members are
  ingested and their variants built first, then the stack is built
  (scripts/build_stack.py).
- `rr`: scripts/process_rr.py over the pair's full overlap, with the
  settings of the reference product (below).
- `products`: the EDI, the EMTF XML and the TF h5 that process_rr writes;
  the row holds the time of those writes, taken from the rr run's phases,
  and the files' sizes.
- `identity`: the bench products and archives against the reference ones.

Every step but `products` runs as a child process through
scripts/profile_run.py (`run_stage`, or `run_sampled` and `analyse` for
the identity check), which samples it every --interval s with psutil (the
working set, CPU, the child's own read and write bytes) and splits it into
phases by the PROFMARK lines of the library functions it wraps. Before each
step the machine must be quiet: the machine CPU over 5 s at most
--quiet-cpu percent, and no other process_rr.py, ingest_site.py,
campaign.py, build_stack.py or profile_run.py running. The script waits up
to --quiet-wait s for that, then runs the step anyway and records it as not
quiet. The machine state at the start and end of each step is a JSON column
of the results.

The reference of a pair is a product in <reference-dir>/tf: the one named
by LOCAL:REMOTE@STEM, else the newest aurora sidecar
<local>_rr-<remote>_<stamp>[_tag].json. Its recorded argv gives the run's
options (the processing window, masks, band layout, estimator flags); the
bench run passes them with its own --tag. The reference workspace must not
be the survey's workspace: the bench writes archives with --force.

Identity, per pair (`identity` rows; the verdict is pass, fail or n/a):

- archives: every channel of each raw archive ingested for the pair equals
  the reference workspace's raw archive of that site: the same runs and
  channels, each channel's samples equal (read in blocks with h5py, both
  files opened read-only), and the same start, end, sample rate and sample
  count, which define its time index. n/a when the reference has no raw
  archive of the site.
- settings: the bench sidecar records the same masks (the full list), band
  scheme, lowest harmonic, estimator tweaks, window and declared filters as
  the reference sidecar, and processes archives of the same names (the
  filter hash is part of a variant's name).
- EDI: the same periods, and for every period the relative difference of
  each impedance element (complex) and of its variance at most --tol (1e-9)
  against the reference EDI. Header lines are not compared: today's EDIs
  carry ZROT and DECLINATION fields that are not data.

The first identity check also runs the controls, which must fail: the bench
EDI against another pair's reference EDI (one of the same local when there
is one), the reference EDI against itself with one impedance value changed
by 1e-6, the bench local archive against the reference archive of another
site, and against its own reference with one sample changed in memory.

--repeat LOCAL:REMOTE runs that pair's rr step once more after all pairs; it
passes when its time is within 5 % of the first. --memory slowest (or
LOCAL:REMOTE) runs the rr of the slowest pair (the largest sum of its
ingest, variant, stack and rr steps) once more under profile_run.py's
tracemalloc stage, traced from the level-0 STFTs through the level-0
regression, with the snapshot step set so that about --snap-steps snapshots
land between the start of tracing and the peak of the first run. With
masks that split the rows into several aurora runs, the base run alone is
traced.

Outputs in --out (default <workspace>/bench): bench_results.csv (one row
per pair and step: wall_s, peak_rss_gib, peak_wset_gib, mean_cores,
read_mb, write_mb, phases JSON, verdict, detail JSON, machine state at the
start and end), phases_all.csv (every phase of every step), runs/ (each
child's log, samples, phases, details, timeline figure and spec, as
profile_run.py writes them), identity/ (one JSON per check),
bench_figure.png (time per step stacked, and peak working set, per pair),
bench_summary.json and workspace_sizes.csv (the survey workspace's files
and sizes at the end). The CSV is rewritten after every step. A later call
with the same --out adds its rows to the earlier ones, so --stages none
with --memory or --repeat runs those on pairs benched before.

The exit code is 1 when an identity check fails, a control does not fail or
the repeat is outside 5 %, else 0.

Usage:
    python scripts/bench_pipeline.py <survey.yaml> --pairs LOCAL:REMOTE[@STEM] [LOCAL:REMOTE ...]
        [--stack NAME:MEMBER,MEMBER[,...][:START:END]] [--stack-weighting none|coherence]
        [--out DIR] [--stages ingest,variant,stack,rr,products,identity]
        [--reference-dir DIR] [--interval S] [--tag bench]
        [--repeat LOCAL:REMOTE] [--memory slowest|LOCAL:REMOTE] [--snap-steps N]
        [--quiet-cpu PCT] [--quiet-wait S] [--tol X]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
for _p in (REPO / "src", SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psutil  # noqa: E402

import profile_run as prof  # noqa: E402

GIB = prof.GIB
STAGES = ("ingest", "variant", "stack", "rr", "products", "identity")
PIPELINE_SCRIPTS = ("process_rr.py", "ingest_site.py", "campaign.py", "build_stack.py", "profile_run.py")
STAMP = re.compile(r"_rr-(?P<remote>.+?)_(?P<stamp>\d{8}-\d{4})(?:_(?P<tag>.+))?$")
TIME = r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?Z?"
EDI_Z = ("ZXX", "ZXY", "ZYX", "ZYY")
EDI_T = ("TX", "TY")
REPEAT_TOL = 0.05


# ------------------------------------------------------------------ arguments

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of bench_pipeline.py."""
    p = argparse.ArgumentParser(
        prog="bench_pipeline.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("--pairs", nargs="+", required=True, metavar="LOCAL:REMOTE[@STEM]",
                   help="pairs in run order; @STEM names the reference product (else the newest aurora row)")
    p.add_argument("--stack", action="append", default=[], metavar="NAME:MEMBERS[:START:END]",
                   help="a stack used as a pair's remote: members comma-separated, window UTC")
    p.add_argument("--stack-weighting", choices=["none", "coherence"], default="none")
    p.add_argument("--out", default=None, help="output folder (default <workspace>/bench)")
    p.add_argument("--stages", default=",".join(STAGES),
                   help="comma-separated subset of " + ",".join(STAGES) + ", or none (with --memory alone)")
    p.add_argument("--reference-dir", default=None,
                   help="the reference workspace, holding tf/ (products) and mth5/ (raw archives)")
    p.add_argument("--interval", type=float, default=0.5, help="sampling interval (s)")
    p.add_argument("--tag", default="bench", help="process_rr --tag of the bench products")
    p.add_argument("--repeat", default=None, metavar="LOCAL:REMOTE", help="run this pair's rr once more")
    p.add_argument("--memory", default=None, metavar="slowest|LOCAL:REMOTE",
                   help="run this pair's rr once more under tracemalloc")
    p.add_argument("--snap-steps", type=int, default=8,
                   help="tracemalloc snapshots wanted between the start of tracing and the peak")
    p.add_argument("--quiet-cpu", type=float, default=10.0, help="machine CPU percent allowed before a step")
    p.add_argument("--quiet-wait", type=float, default=600.0, help="seconds to wait for a quiet machine")
    p.add_argument("--tol", type=float, default=1e-9, help="relative tolerance of the EDI identity")
    return p


def parse_pair(text: str) -> dict:
    """Parse LOCAL:REMOTE[@STEM] into {"local", "remote", "stem"}."""
    body, _, stem = text.partition("@")
    local, sep, remote = body.partition(":")
    if not (sep and local and remote):
        raise SystemExit(f"--pairs {text!r}: LOCAL:REMOTE[@STEM]")
    return {"local": local, "remote": remote, "stem": stem or None}


def parse_stack(text: str) -> dict:
    """Parse NAME:MEMBER,MEMBER[:START:END] into {"name", "members", "start", "end"}.

    START and END are UTC times such as 2023-09-22T12:21:22Z or
    "2023-09-22 12:21:22"; they hold colons themselves, so the window is
    matched as two times.
    """
    name, _, rest = text.partition(":")
    members, _, window = rest.partition(":")
    members = [m for m in members.split(",") if m]
    if not name or len(members) < 2:
        raise SystemExit(f"--stack {text!r}: NAME:MEMBER,MEMBER[:START:END] with two members or more")
    start = end = None
    if window:
        m = re.fullmatch(rf"({TIME}):({TIME})", window)
        if not m:
            raise SystemExit(f"--stack {text!r}: the window is START:END, each a UTC time")
        start, end = (_utc_text(t) for t in m.groups())
    return {"name": name, "members": members, "start": start, "end": end}


def _utc_text(text: str) -> str:
    """Format a time as UTC "YYYY-mm-dd HH:MM:SS", the form scripts/build_stack.py is given by the campaign."""
    ts = pd.Timestamp(text)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return f"{ts:%Y-%m-%d %H:%M:%S}"


# ------------------------------------------------------------------ references

def find_reference(tf_dir: Path, local: str, remote: str, stem: str | None) -> dict:
    """Find a pair's reference product and the process_rr options it was made with.

    Args:
        tf_dir (Path): The reference products folder.
        local (str): Local site.
        remote (str): Remote site or stack.
        stem (str | None): The product stem to use; None takes the newest
            aurora sidecar of the pair (by its `started`).

    Returns:
        dict: {"stem", "sidecar" (dict), "json", "edi", "options"}, where
        `options` is the recorded argv after the survey, local and remote,
        without its --tag.

    Raises:
        SystemExit: When no reference is found.
    """
    if stem:
        paths = [tf_dir / f"{stem}.json"]
    else:
        paths = [p for p in tf_dir.glob(f"{local}_rr-{remote}_*.json")
                 if (m := STAMP.search(p.stem)) and m["remote"] == remote]
    rows = []
    for path in paths:
        if not path.exists():
            continue
        side = json.loads(path.read_text(encoding="utf-8"))
        if side.get("engine", "aurora") != "aurora" or "argv" not in side:
            continue
        rows.append((str(side.get("started", "")), path, side))
    if not rows:
        raise SystemExit(f"{local} rr {remote}: no aurora reference in {tf_dir}" + (f" named {stem}" if stem else ""))
    _, path, side = max(rows, key=lambda r: r[0])
    argv = list(side["argv"])[4:]
    options, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--tag":
            skip = True
            continue
        if a.startswith("--tag=") or a == "--dry-run":
            continue
        options.append(a)
    edi = path.with_name(side.get("edi") or f"{path.stem}.edi")
    return {"stem": path.stem, "sidecar": side, "json": path, "edi": edi, "options": options}


# ------------------------------------------------------------------ machine state

def _pipeline_processes(own: set[int]) -> list[str]:
    """List other running pipeline processes (scripts in PIPELINE_SCRIPTS), as 'pid script'."""
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] in own:
                continue
            cmd = " ".join(p.info["cmdline"] or [])
            hit = next((s for s in PIPELINE_SCRIPTS if s in cmd), None)
            if hit and "python" in cmd.lower():
                out.append(f"{p.info['pid']} {hit}")
        except (psutil.Error, TypeError):
            pass
    return out


def machine_state(seconds: float = 5.0) -> dict:
    """Return the machine's CPU over `seconds`, its memory, and the other pipeline processes running."""
    own = {os.getpid(), *(c.pid for c in psutil.Process().children(recursive=True))}
    cpu = psutil.cpu_percent(interval=seconds)
    vm = psutil.virtual_memory()
    return {"t": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "cpu_pct": round(cpu, 1),
            "cpu_window_s": seconds, "mem_available_gib": round(vm.available / GIB, 1),
            "mem_used_gib": round((vm.total - vm.available) / GIB, 1), "others": _pipeline_processes(own)}


def quiet_gate(max_cpu: float, wait_s: float) -> dict:
    """Wait for a quiet machine (CPU over 5 s at most `max_cpu` %, no other pipeline process).

    Returns:
        dict: The last `machine_state`, with "quiet" (bool) and "waited_s".
    """
    t0 = time.time()
    while True:
        state = machine_state(5.0)
        quiet = state["cpu_pct"] <= max_cpu and not state["others"]
        if quiet or time.time() - t0 > wait_s:
            state.update(quiet=quiet, waited_s=round(time.time() - t0, 1))
            if not quiet:
                print(f"machine not quiet after {wait_s:.0f} s ({state}): running anyway", flush=True)
            return state
        print(f"waiting for a quiet machine: CPU {state['cpu_pct']} %, others {state['others']}", flush=True)
        time.sleep(30)


# ------------------------------------------------------------------ one step

def sample_stats(out: Path, stem: str) -> dict:
    """Summarise a child's psutil samples: peak RSS and working set, mean cores, its own read/write MB."""
    path = out / f"{stem}_samples.csv"
    if not path.exists():
        return {}
    s = pd.read_csv(path)
    if s.empty or "rss" not in s:
        return {}
    stats = {"peak_rss_gib": round(s["rss"].max() / GIB, 2),
             "peak_wset_gib": round(s["peak_wset"].max() / GIB, 2) if "peak_wset" in s else None,
             "mean_cores": round(s["cpu"].iloc[1:].mean() / 100.0, 2) if len(s) > 1 else None}
    for col, key in (("p_read", "read_mb"), ("p_write", "write_mb")):
        if col in s:
            v = s[col].dropna()
            stats[key] = round(float(v.max() - v.min()) / 1e6, 1) if len(v) else None
    return stats


def phases_json(table: pd.DataFrame) -> dict:
    """Sum a phase table's seconds per phase name, keeping each name's peak RSS: {name: [s, peak GiB]}."""
    out: dict = {}
    if table is None or table.empty:
        return out
    for row in table.itertuples():
        s, peak = out.get(row.phase, [0.0, 0.0])
        out[row.phase] = [round(s + float(row.seconds), 2),
                          max(peak, float(getattr(row, "peak_rss_gib", 0.0) or 0.0))]
    return out


class Bench:
    """The bench run: its options, its rows, and the files it writes.

    Args:
        args (argparse.Namespace): Parsed arguments.
    """

    def __init__(self, args):
        from mt_workbench.survey import Survey

        self.args = args
        self.survey_yaml = str(Path(args.survey_yaml).resolve())
        self.survey = Survey.from_yaml(self.survey_yaml)
        self.out = Path(args.out) if args.out else self.survey.workspace / "bench"
        self.runs = self.out / "runs"
        self.ident = self.out / "identity"
        for d in (self.out, self.runs, self.ident):
            d.mkdir(parents=True, exist_ok=True)
        self.stages = [s.strip() for s in args.stages.split(",") if s.strip() and s.strip() != "none"]
        unknown = set(self.stages) - set(STAGES)
        if unknown:
            raise SystemExit(f"--stages: unknown {sorted(unknown)}; choose from {', '.join(STAGES)}")
        self.ref_ws = Path(args.reference_dir) if args.reference_dir else None
        if self.ref_ws is not None and self.ref_ws.resolve() == self.survey.workspace.resolve():
            raise SystemExit(f"--reference-dir {self.ref_ws} is the survey's own workspace: the bench writes "
                             "archives there with --force; point survey.yaml's workspace at a bench folder")
        # an earlier call's rows in the same --out are kept and added to (a memory or repeat run later)
        self.rows: list[dict] = []
        self.phase_rows: list[dict] = []
        if (self.out / "bench_results.csv").exists():
            self.rows = pd.read_csv(self.out / "bench_results.csv").astype(object).where(
                lambda d: d.notna(), None).to_dict("records")
        if (self.out / "phases_all.csv").exists():
            self.phase_rows = pd.read_csv(self.out / "phases_all.csv").to_dict("records")
        self.ingested: set[str] = set()
        self.varianted: set[str] = set()
        self.failed = False
        self.env = {**prof.child_env(), "PYTHONIOENCODING": "utf-8"}

    # --- bookkeeping

    def add_row(self, row: dict) -> dict:
        """Append a result row and rewrite bench_results.csv."""
        base = {"pair": "", "stage": "", "site": "", "stem": "", "rc": None, "wall_s": None,
                "peak_rss_gib": None, "peak_wset_gib": None, "mean_cores": None, "read_mb": None,
                "write_mb": None, "phases": "{}", "verdict": "", "detail": "{}", "machine_start": "{}",
                "machine_end": "{}", "log": ""}
        base.update(row)
        for key in ("phases", "detail", "machine_start", "machine_end"):
            if not isinstance(base[key], str):
                base[key] = json.dumps(base[key], default=str)
        self.rows.append(base)
        pd.DataFrame(self.rows).to_csv(self.out / "bench_results.csv", index=False)
        if base["verdict"] == "fail":
            self.failed = True
        print(f"[{dt.datetime.now():%H:%M:%S}] {base['pair']} {base['stage']} {base['site']}: "
              f"{base['wall_s']} s, peak {base['peak_rss_gib']} GiB, {base['verdict'] or 'ok'}", flush=True)
        return base

    def add_phases(self, pair: str, stage: str, site: str, stem: str, table: pd.DataFrame) -> None:
        """Append a step's phase table to phases_all.csv."""
        if table is None or table.empty:
            return
        t = table.copy()
        t.insert(0, "stem", stem)
        t.insert(0, "site", site)
        t.insert(0, "stage", stage)
        t.insert(0, "pair", pair)
        self.phase_rows.extend(t.to_dict("records"))
        pd.DataFrame(self.phase_rows).to_csv(self.out / "phases_all.csv", index=False)

    def step(self, stage: str, spec: dict, who: str, pair: str, site: str = "") -> dict:
        """Run one profile_run.py stage as a sampled child after the quiet gate, and record its row.

        Returns:
            dict: The `run_stage` result with the row added as "row".
        """
        start = quiet_gate(self.args.quiet_cpu, self.args.quiet_wait)
        res = prof.run_stage(stage, spec, self.runs, who, self.args.interval, True,
                             prof.NEED_GB.get(stage, 20.0), 62.0)
        end = machine_state(1.0)
        stats = sample_stats(self.runs, res["stem"])
        self.add_phases(pair, stage, site, res["stem"], res["table"])
        row = self.add_row({"pair": pair, "stage": stage, "site": site, "stem": res["stem"], "rc": res["rc"],
                            "wall_s": round(res["seconds"], 2), **stats, "phases": phases_json(res["table"]),
                            "verdict": "" if res["rc"] == 0 else "fail",
                            "detail": {"spec": spec.get("argv") or spec.get("site")},
                            "machine_start": start, "machine_end": end,
                            "log": str(self.runs / f"{res['stem']}.log")})
        res["row"] = row
        return res

    # --- the steps

    def ingest(self, site: str, pair: str) -> None:
        """Ingest a site's raw archive (--force over an existing one), once per bench run."""
        from mt_workbench.ingest import default_archive_path

        if site in self.ingested or "ingest" not in self.stages:
            return
        path = default_archive_path(self.survey, site)
        force = ["--force"] if path.exists() else []
        if force and path.stat().st_nlink > 1:
            raise SystemExit(f"{path} is a hard link to another archive: ingest into a workspace where {site} "
                             "has no archive")
        res = self.step("ingest", {"argv": [self.survey_yaml, site, "--raw", *force]}, site, pair, site)
        self.ingested.add(site)
        if res["rc"] == 0 and path.exists():
            self._annotate(res["row"], archive=str(path), archive_mb=round(path.stat().st_size / 1e6, 1))

    def variant(self, site: str, pair: str) -> None:
        """Build a site's filtered variant; a site without declared filters gets a row saying so."""
        from mt_workbench.ingest import filters_hash, variant_path

        if site in self.varianted or "variant" not in self.stages:
            return
        self.varianted.add(site)
        declared = self.survey.site(site).filters
        if not declared:
            self.add_row({"pair": pair, "stage": "variant", "site": site, "wall_s": 0.0, "verdict": "n/a",
                          "detail": {"note": "no declared filters: the raw archive is processed"}})
            return
        res = self.step("variant", {"survey": self.survey_yaml, "site": site}, site, pair, site)
        path = variant_path(self.survey, site)
        if res["rc"] == 0 and path.exists():
            self._annotate(res["row"], archive=str(path), archive_mb=round(path.stat().st_size / 1e6, 1),
                           filters_hash=filters_hash(declared))

    def stack(self, st: dict, pair: str) -> None:
        """Build a stack from its members' processing archives."""
        if "stack" not in self.stages:
            return
        start, end = st["start"], st["end"]
        if not (start and end):
            spans = [(pd.Timestamp(self.survey.site(m).start), pd.Timestamp(self.survey.site(m).end))
                     for m in st["members"]]
            start = start or f"{max(s for s, _ in spans):%Y-%m-%d %H:%M:%S}"
            end = end or f"{min(e for _, e in spans):%Y-%m-%d %H:%M:%S}"
        argv = [self.survey_yaml, st["name"], start, end, *st["members"], "--weighting", self.args.stack_weighting]
        res = self.step("stack", {"argv": argv}, st["name"], pair, st["name"])
        path = self.survey.workspace / "mth5" / f"{st['name']}.h5"
        if res["rc"] == 0 and path.exists():
            self._annotate(res["row"], archive=str(path), archive_mb=round(path.stat().st_size / 1e6, 1))

    def rr(self, pr: dict, tag: str, stage: str = "rr") -> dict:
        """Run process_rr.py for a pair with its reference's options and a bench tag."""
        argv = [self.survey_yaml, pr["local"], pr["remote"], *pr["ref"]["options"], "--tag", tag]
        res = self.step("rr", {"argv": argv}, f"{pr['local']}_rr-{pr['remote']}", pr["name"], pr["local"])
        if stage != "rr":
            res["row"]["stage"] = stage
            self.rows[-1]["stage"] = stage
            for r in self.phase_rows:
                if r["stem"] == res["stem"]:
                    r["stage"] = stage
            pd.DataFrame(self.rows).to_csv(self.out / "bench_results.csv", index=False)
            pd.DataFrame(self.phase_rows).to_csv(self.out / "phases_all.csv", index=False)
        log = Path(res["row"]["log"]).read_text(encoding="utf-8", errors="replace")
        m = re.findall(r"^sidecar: (.+\.json)\s*$", log, flags=re.M)
        res["sidecar"] = Path(m[-1]) if m else None
        return res

    def products(self, pr: dict, rr_res: dict) -> None:
        """Record the product writes of an rr run: their phases' time and the files' sizes."""
        table = rr_res["table"]
        names = ("products", "aurora TF export", "comparison figure", "phase quadrants")
        sub = table[table["phase"].str.startswith(names)] if table is not None and not table.empty else table
        writes = sub[sub["phase"].str.startswith("products")] if sub is not None and not sub.empty else sub
        files, verdict = {}, "pass"
        side = rr_res.get("sidecar")
        if side and side.exists():
            from mt_workbench.products import product_paths

            sc = json.loads(side.read_text(encoding="utf-8"))
            paths = {**product_paths(side.with_name(sc.get("edi") or f"{side.stem}.edi")), "json": side,
                     "figure": side.with_name(sc.get("figure") or f"{side.stem}_vs_lemimt.png")}
            for key, path in paths.items():
                files[key] = {"path": str(path), "bytes": path.stat().st_size if path.exists() else None}
            if any(v["bytes"] is None for k, v in files.items() if k in ("edi", "xml", "h5")):
                verdict = "fail"
        else:
            verdict = "fail"
        has_writes = writes is not None and len(writes) > 0
        has_peak = sub is not None and len(sub) > 0 and "peak_rss_gib" in sub
        self.add_row({"pair": pr["name"], "stage": "products", "site": pr["local"], "stem": rr_res["stem"],
                      "rc": rr_res["rc"], "wall_s": round(float(writes["seconds"].sum()), 2) if has_writes else None,
                      "peak_rss_gib": round(float(sub["peak_rss_gib"].max()), 2) if has_peak else None,
                      "phases": phases_json(sub), "verdict": verdict, "detail": {"files": files},
                      "log": rr_res["row"]["log"]})

    def identity(self, pr: dict, rr_res: dict | None, sites: list[str], controls: dict | None) -> None:
        """Run the identity check of a pair as a sampled child (`identity_main`) and record its row."""
        from mt_workbench.ingest import default_archive_path

        archives = []
        for site in sites:
            ref = self.ref_ws / "mth5" / f"{site}.h5" if self.ref_ws else None
            archives.append({"site": site, "bench": str(default_archive_path(self.survey, site)),
                             "reference": str(ref) if ref is not None and ref.exists() else None})
        side = rr_res.get("sidecar") if rr_res else None
        stem = f"identity_{pr['name']}_{dt.datetime.now():%Y%m%d-%H%M%S}"
        spec = {"archives": archives, "bench_sidecar": str(side) if side else None,
                "reference_sidecar": str(pr["ref"]["json"]), "tol": self.args.tol, "controls": controls,
                "result": str(self.ident / f"{stem}.json")}
        spec_path = self.runs / f"{stem}_spec.json"
        spec_path.write_text(json.dumps(spec, default=str, indent=1), encoding="utf-8")
        start = quiet_gate(self.args.quiet_cpu, self.args.quiet_wait)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--identity-child", str(spec_path)]
        print(f"[{dt.datetime.now():%H:%M:%S}] identity: {pr['name']} -> {self.runs / stem}.log", flush=True)
        samples, t_spawn, t_end, rc = prof.run_sampled(cmd, self.runs / f"{stem}.log", self.args.interval, self.env)
        table = prof.analyse(self.runs / f"{stem}.log", samples, t_spawn, t_end, self.runs, stem, "identity")
        end = machine_state(1.0)
        result = json.loads(Path(spec["result"]).read_text(encoding="utf-8")) if Path(spec["result"]).exists() else {}
        verdict = result.get("verdict", "fail") if rc == 0 else "fail"
        self.add_phases(pr["name"], "identity", pr["local"], stem, table)
        self.add_row({"pair": pr["name"], "stage": "identity", "site": pr["local"], "stem": stem, "rc": rc,
                      "wall_s": round(t_end - t_spawn, 2), **sample_stats(self.runs, stem),
                      "phases": phases_json(table), "verdict": verdict, "detail": result.get("summary", {}),
                      "machine_start": start, "machine_end": end, "log": str(self.runs / f"{stem}.log")})

    def _annotate(self, row: dict, **extra) -> None:
        """Add keys to a recorded row's detail JSON and rewrite the CSV."""
        detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else dict(row["detail"])
        detail.update(extra)
        row["detail"] = json.dumps(detail, default=str)
        pd.DataFrame(self.rows).to_csv(self.out / "bench_results.csv", index=False)

    # --- the extra runs

    def repeat(self, pr: dict, first: dict) -> None:
        """Run a pair's rr once more and compare its time with the first run's (within 5 %)."""
        res = self.rr(pr, f"{self.args.tag}-repeat", stage="rr-repeat")
        w1, w2 = float(first["row"]["wall_s"]), float(res["row"]["wall_s"])
        rel = abs(w2 - w1) / w1
        row = self.rows[-1]
        row["verdict"] = "pass" if rel <= REPEAT_TOL and res["rc"] == 0 else "fail"
        self.failed |= row["verdict"] == "fail"
        self._annotate(row, first_wall_s=w1, repeat_wall_s=w2, rel_diff=round(rel, 4), tolerance=REPEAT_TOL,
                       first_peak_rss_gib=first["row"]["peak_rss_gib"])
        print(f"repeat {pr['name']}: {w1:.1f} s then {w2:.1f} s ({100 * rel:.1f} %): {row['verdict']}", flush=True)

    def earlier_rr(self, name: str) -> dict:
        """Return a pair's first rr run recorded in bench_results.csv: {"stem", "table", "row"}."""
        row = next((r for r in self.rows if r["pair"] == name and r["stage"] == "rr"), None)
        if row is None:
            raise SystemExit(f"{name}: no rr run in {self.out / 'bench_results.csv'}")
        return {"stem": row["stem"], "row": row, "table": pd.read_csv(self.runs / f"{row['stem']}_phases.csv")}

    def memory(self, pr: dict, first: dict) -> None:
        """Run a pair's rr under tracemalloc, the snapshot step set from the first run's level-0 rise."""
        table = first["table"]
        samples = pd.read_csv(self.runs / f"{first['stem']}_samples.csv")
        t0 = samples["t"].iloc[0]
        l0 = table[table["phase"].str.startswith("L0 STFT")]
        rss0 = (prof._interp(samples, "rss", t0 + float(l0["start_s"].iloc[0])) / GIB) if len(l0) else 0.0
        peak = samples["rss"].max() / GIB
        step = max(0.25, round((peak - rss0) / max(1, self.args.snap_steps), 2))
        argv = [self.survey_yaml, pr["local"], pr["remote"], *pr["ref"]["options"], "--tag",
                f"{self.args.tag}-tracemalloc"]
        res = self.step("tracemalloc", {"argv": argv, "snap_step_gib": step, "tm_until": "regression",
                                        "nframe": 12}, f"{pr['local']}_rr-{pr['remote']}", pr["name"], pr["local"])
        res["row"]["stage"] = self.rows[-1]["stage"] = "memory"
        for r in self.phase_rows:
            if r["stem"] == res["stem"]:
                r["stage"] = "memory"
        pd.DataFrame(self.phase_rows).to_csv(self.out / "phases_all.csv", index=False)
        snaps = self.runs / f"{res['stem']}_tm_snaps.csv"
        n = len(pd.read_csv(snaps)) if snaps.exists() and snaps.stat().st_size > 2 else 0
        self._annotate(self.rows[-1], snap_step_gib=step, rss_at_l0_stft_gib=round(rss0, 2),
                       first_peak_gib=round(peak, 2), snapshots=n,
                       report=str(self.runs / f"{res['stem']}_tracemalloc.txt"))

    # --- the run

    def run(self) -> int:
        """Run every pair, then the repeat and memory runs, the figure and the summary.

        Returns:
            int: 1 when an identity check, a control or the repeat failed, else 0.
        """
        stacks = {s["name"]: s for s in map(parse_stack, self.args.stack)}
        pairs = [parse_pair(p) for p in self.args.pairs]
        tf_dir = (self.ref_ws / "tf") if self.ref_ws else None
        for pr in pairs:
            pr["name"] = f"{pr['local']}_rr-{pr['remote']}"
            pr["ref"] = find_reference(tf_dir, pr["local"], pr["remote"], pr["stem"]) if tf_dir else None
            if pr["ref"] is None and ("rr" in self.stages or "identity" in self.stages):
                raise SystemExit("--reference-dir is needed for the rr and identity steps")
        plan = {p["name"]: {"reference": p["ref"]["stem"] if p["ref"] else None,
                            "options": p["ref"]["options"] if p["ref"] else None} for p in pairs}
        plan_path = self.out / "bench_plan.json"
        if plan_path.exists():  # a later call into the same --out keeps the first call's plan
            plan_path = self.out / f"bench_plan_{dt.datetime.now():%Y%m%d-%H%M%S}.json"
        plan_path.write_text(json.dumps({"survey": self.survey_yaml, "pairs": plan, "stacks": stacks,
                                         "stages": self.stages}, indent=1, default=str), encoding="utf-8")
        print(json.dumps(plan, indent=1), flush=True)
        first_rr: dict = {}
        controls_done = False
        for pr in pairs:
            st = stacks.get(pr["remote"])
            sites = [pr["local"], *(st["members"] if st else [pr["remote"]])]
            new = [s for s in sites if s not in self.ingested]
            for site in sites:
                self.ingest(site, pr["name"])
            for site in sites:
                self.variant(site, pr["name"])
            if st:
                self.stack(st, pr["name"])
            rr_res = None
            if "rr" in self.stages:
                rr_res = self.rr(pr, self.args.tag)
                first_rr[pr["name"]] = rr_res
                if "products" in self.stages:
                    self.products(pr, rr_res)
            if "identity" in self.stages:
                controls = None
                if not controls_done:
                    others = [p for p in pairs if p is not pr]
                    same = [p for p in others if p["local"] == pr["local"]]
                    ctrl = (same or others or [None])[0]
                    candidates = [p["remote"] for p in pairs] + [p["local"] for p in pairs]
                    other_site = next((s for s in candidates if s != pr["local"] and s not in stacks), None)
                    controls = {"edi_other_reference": str(ctrl["ref"]["edi"]) if ctrl else None,
                                "edi_other_name": ctrl["name"] if ctrl else None,
                                "archive_other_site": other_site,
                                "archive_other_reference": str(self.ref_ws / "mth5" / f"{other_site}.h5")
                                if other_site and self.ref_ws else None}
                    controls_done = True
                self.identity(pr, rr_res, new, controls)
        if self.args.repeat:
            name = "_rr-".join(self.args.repeat.split(":", 1))
            pr = next((p for p in pairs if p["name"] == name), None)
            if pr is None:
                raise SystemExit(f"--repeat {self.args.repeat}: not among --pairs")
            self.repeat(pr, first_rr.get(name) or self.earlier_rr(name))
        if self.args.memory:
            if self.args.memory == "slowest":  # the pair whose steps took longest in all (ingest to rr)
                df = pd.DataFrame(self.rows)
                main = df[df["stage"].isin(["ingest", "variant", "stack", "rr"])]
                totals = pd.to_numeric(main["wall_s"], errors="coerce").groupby(main["pair"]).sum()
                name = str(totals.idxmax())
            else:
                name = "_rr-".join(self.args.memory.split(":", 1))
            pr = next((p for p in pairs if p["name"] == name), None)
            if pr is None:
                raise SystemExit(f"--memory: {name} is not among --pairs")
            self.memory(pr, first_rr.get(name) or self.earlier_rr(name))
        self.finish()
        return 1 if self.failed else 0

    def finish(self) -> None:
        """Write the workspace sizes, the summary and the figure."""
        files = [p for p in self.survey.workspace.rglob("*") if p.is_file()]
        sizes = pd.DataFrame([{"path": str(p.relative_to(self.survey.workspace)), "bytes": p.stat().st_size}
                              for p in files])
        sizes.to_csv(self.out / "workspace_sizes.csv", index=False)
        total = int(sizes["bytes"].sum()) if len(sizes) else 0
        df = pd.DataFrame(self.rows)
        summary = {"workspace": str(self.survey.workspace), "workspace_bytes": total,
                   "workspace_gib": round(total / GIB, 2), "n_files": len(files),
                   "exit_code": 1 if self.failed else 0, "pairs": {}}
        for name, g in df.groupby("pair", sort=False):
            main = g[~g["stage"].isin(["rr-repeat", "memory", "products"])]
            summary["pairs"][name] = {
                "wall_s_by_stage": main.groupby("stage")["wall_s"].sum().round(2).to_dict(),
                "peak_rss_gib_by_stage": main.groupby("stage")["peak_rss_gib"].max().to_dict(),
                "products_s": float(g.loc[g["stage"] == "products", "wall_s"].sum()),
                "total_s": round(float(main["wall_s"].fillna(0).sum()), 2),
                "verdicts": dict(zip(g["stage"] + ":" + g["site"].astype(str), g["verdict"].fillna("")))}
        (self.out / "bench_summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        try:
            plot_bench(df, self.out / "bench_figure.png")
        except Exception as exc:  # the figure is a convenience: the CSV holds the numbers
            print(f"figure not drawn: {type(exc).__name__}: {exc}", flush=True)
        print(json.dumps(summary, indent=1, default=str), flush=True)


# ------------------------------------------------------------------ the figure

# categorical slots in a fixed order (validated for adjacent pairs), one per step
STAGE_COLOURS = {"ingest": "#2a78d6", "variant": "#eb6834", "stack": "#1baf7a", "rr": "#eda100",
                 "identity": "#e87ba4"}
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot_bench(df: pd.DataFrame, out_png: Path) -> None:
    """Draw time per step stacked per pair, and the peak working set per step and pair.

    Args:
        df (pd.DataFrame): The result rows.
        out_png (Path): Figure path.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    main = df[df["stage"].isin(list(STAGE_COLOURS))].copy()
    main["wall_s"] = pd.to_numeric(main["wall_s"], errors="coerce").fillna(0.0)
    main["peak"] = pd.to_numeric(main["peak_wset_gib"], errors="coerce").fillna(
        pd.to_numeric(main["peak_rss_gib"], errors="coerce"))
    pairs = list(dict.fromkeys(main["pair"]))
    secs = main.pivot_table(index="pair", columns="stage", values="wall_s", aggfunc="sum").reindex(pairs).fillna(0)
    peak = main.pivot_table(index="pair", columns="stage", values="peak", aggfunc="max").reindex(pairs)
    stages = [s for s in STAGE_COLOURS if s in secs.columns]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 0.55 * len(pairs) + 2.2), sharey=True, facecolor=SURFACE)
    y = np.arange(len(pairs))
    left = np.zeros(len(pairs))
    for st in stages:
        ax1.barh(y, secs[st].to_numpy(), left=left, color=STAGE_COLOURS[st], label=st, height=0.6,
                 edgecolor=SURFACE, linewidth=1.5)
        left += secs[st].to_numpy()
    for yi, total in zip(y, left):
        ax1.text(total, yi, f" {total:.0f} s", va="center", fontsize=9, color=INK)
    ax1.set_yticks(y, pairs)
    ax1.invert_yaxis()
    ax1.set_xlabel("seconds (sum of the steps' wall times; one site's ingest and variant once per bench run)")
    ax1.set_title("Time per step")
    width = 0.8 / max(1, len(stages))
    for k, st in enumerate(stages):
        if st in peak.columns:
            ax2.barh(y - 0.4 + width * (k + 0.5), peak[st].to_numpy(), height=width, color=STAGE_COLOURS[st],
                     edgecolor=SURFACE, linewidth=1.0)
    ax2.set_xlabel("peak working set of the step's child (GiB)")
    ax2.set_title("Peak memory per step")
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.title.set_color(INK)
        ax.xaxis.label.set_color(MUTED)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(labels), frameon=False, fontsize=9,
               labelcolor=MUTED, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ------------------------------------------------------------------ identity (child)

def read_edi(path: Path) -> dict:
    """Read an EDI's data blocks: {block name: float array}, e.g. FREQ, ZXYR, ZXY.VAR, TXR.EXP."""
    blocks: dict = {}
    name, values = None, []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith(">"):
            if name is not None:
                blocks[name] = np.array(values, dtype=float)
            head = s[1:].split()
            name = head[0] if head and "//" in s else None
            values = []
        elif name is not None and s:
            values.extend(float(v) for v in s.split())
    if name is not None:
        blocks[name] = np.array(values, dtype=float)
    return blocks


def _rel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Relative difference |a - b| / |b|, 0 where both are equal (EMPTY or zero included)."""
    a, b = np.asarray(a), np.asarray(b)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(a - b) / np.abs(b)
    rel[(a == b) | (np.isnan(a) & np.isnan(b))] = 0.0
    return np.where(np.isfinite(rel), rel, np.inf)


def compare_edi(bench: dict, ref: dict, tol: float) -> dict:
    """Compare two EDIs' impedances, tippers and variances per period.

    Args:
        bench (dict): Blocks of the bench EDI (`read_edi`).
        ref (dict): Blocks of the reference EDI.
        tol (float): Largest relative difference that passes.

    Returns:
        dict: {"verdict", "n_periods", "max_rel_z", "max_rel_var", "worst_period_s", "per_period", ...}.
    """
    fb, fr = bench.get("FREQ"), ref.get("FREQ")
    out = {"n_periods": int(len(fr)) if fr is not None else 0}
    if fb is None or fr is None or len(fb) != len(fr) or not np.array_equal(fb, fr):
        out.update(verdict="fail", reason=f"periods differ: {None if fb is None else len(fb)} bench, "
                                          f"{None if fr is None else len(fr)} reference")
        if fb is not None and fr is not None:  # the values on the periods both hold, for the report
            common, ib, ir = np.intersect1d(fb, fr, return_indices=True)
            n = {len(fb), len(fr)}
            sub_b = {k: (v[ib] if len(v) in n and len(v) == len(fb) else v) for k, v in bench.items()}
            sub_r = {k: (v[ir] if len(v) in n and len(v) == len(fr) else v) for k, v in ref.items()}
            if len(common):
                inner = compare_edi(sub_b, sub_r, tol)
                out.update(common_periods=int(len(common)), max_rel_z=inner.get("max_rel_z"),
                           max_rel_var=inner.get("max_rel_var"),
                           n_periods_over_tol=inner.get("n_periods_over_tol"))
        return out
    zs, vs, missing = [], [], []
    for comp in EDI_Z:
        keys = (f"{comp}R", f"{comp}I", f"{comp}.VAR")
        if not all(k in ref for k in keys):
            continue
        if not all(k in bench for k in keys):
            missing.append(comp)
            continue
        zb = bench[keys[0]] + 1j * bench[keys[1]]
        zr = ref[keys[0]] + 1j * ref[keys[1]]
        zs.append(_rel(zb, zr))
        vs.append(_rel(bench[keys[2]], ref[keys[2]]))
    for comp in EDI_T:
        keys = (f"{comp}R.EXP", f"{comp}I.EXP", f"{comp}VAR.EXP")
        if all(k in ref for k in keys):
            if not all(k in bench for k in keys):
                missing.append(comp)
                continue
            zs.append(_rel(bench[keys[0]] + 1j * bench[keys[1]], ref[keys[0]] + 1j * ref[keys[1]]))
            vs.append(_rel(bench[keys[2]], ref[keys[2]]))
    if not zs:
        out.update(verdict="fail", reason="no impedance blocks")
        return out
    z = np.max(np.vstack(zs), axis=0)
    v = np.max(np.vstack(vs), axis=0)
    worst = int(np.argmax(np.maximum(z, v)))
    out.update(max_rel_z=float(z.max()), max_rel_var=float(v.max()), worst_period_s=float(1.0 / fr[worst]),
               n_periods_over_tol=int(np.sum(np.maximum(z, v) > tol)), missing=missing,
               per_period=[[round(float(1.0 / f), 6), float(a), float(b)] for f, a, b in zip(fr, z, v)])
    out["verdict"] = "pass" if (z.max() <= tol and v.max() <= tol and not missing) else "fail"
    return out


def _channels(h5) -> dict:
    """Map (run, component) to the h5py dataset of every channel in an MTH5 file."""
    found = {}

    def visit(name, obj):
        if hasattr(obj, "shape") and obj.attrs.get("mth5_type") in ("Electric", "Magnetic", "Auxiliary"):
            parts = name.split("/")
            found[(parts[-2], parts[-1])] = obj

    h5.visititems(visit)
    return found


def _attr(ds, key):
    """Return an attribute as plain text (bytes decoded)."""
    v = ds.attrs.get(key)
    return v.decode() if isinstance(v, bytes) else (str(v) if v is not None else None)


def compare_archives(bench: str, ref: str, perturb: bool = False, stop_first: bool = False,
                     block: int = 1 << 24) -> dict:
    """Compare two MTH5 archives channel by channel, both opened read-only with h5py.

    The runs and channels must match; for each channel the dtype, the
    sample count, the start, end and sample rate attributes (which define
    its time index) and every sample. `perturb` changes the first sample of
    the first channel read from `bench` (a control that must fail);
    `stop_first` (implied by `perturb`) stops at the first difference.

    Returns:
        dict: {"verdict", "channels", "samples", "differences" (first 20), "seconds"}.
    """
    import h5py

    t0 = time.perf_counter()
    diffs: list[str] = []
    n_samples = 0
    with h5py.File(bench, "r") as fb, h5py.File(ref, "r") as fr:
        cb, cr = _channels(fb), _channels(fr)
        if set(cb) != set(cr):
            diffs.append(f"channels differ: bench only {sorted(set(cb) - set(cr))[:6]}, "
                         f"reference only {sorted(set(cr) - set(cb))[:6]}")
        first = True
        for key in sorted(set(cb) & set(cr)):
            db, dr = cb[key], cr[key]
            for a in ("time_period.start", "time_period.end", "sample_rate"):
                if _attr(db, a) != _attr(dr, a):
                    diffs.append(f"{key} {a}: {_attr(db, a)} != {_attr(dr, a)}")
            if db.shape != dr.shape or db.dtype != dr.dtype:
                diffs.append(f"{key} shape/dtype {db.shape} {db.dtype} != {dr.shape} {dr.dtype}")
                continue
            n = db.shape[0] if db.shape else 0
            n_samples += n
            for i in range(0, n, block):
                a, b = db[i:i + block], dr[i:i + block]
                if perturb and first:
                    a = a.copy()
                    a[0] = a[0] + 1
                first = False
                if not np.array_equal(a, b, equal_nan=np.issubdtype(a.dtype, np.floating)):
                    k = int(np.flatnonzero(a != b)[0]) if a.shape == b.shape else 0
                    diffs.append(f"{key} sample {i + k}: {a[k]} != {b[k]}")
                    break
            if (perturb or stop_first) and diffs:
                break
    return {"verdict": "fail" if diffs else "pass", "channels": len(cb), "samples": n_samples,
            "differences": diffs[:20], "seconds": round(time.perf_counter() - t0, 2)}


SETTINGS_KEYS = ("band_scheme", "lowest_harmonic", "tweaks", "masks", "window", "filters", "masks_ignored",
                 "mask_scope", "channel_runs")


def compare_settings(bench: dict, ref: dict) -> dict:
    """Compare the recorded settings of two sidecars and the names of the archives they processed."""
    diffs = []
    for key in SETTINGS_KEYS:
        if key not in ref:
            continue
        a, b = (json.dumps(x.get(key), sort_keys=True, default=str) for x in (bench, ref))
        if a != b:
            diffs.append(key)
    for key in ("local_archive", "remote_archive"):
        a, b = (Path((x.get(key) or {}).get("path", "")).name for x in (bench, ref))
        if a != b:
            diffs.append(f"{key}: {a} != {b}")
    common = set(bench.get("mask_counts") or {}) & set(ref.get("mask_counts") or {})
    if any(bench["mask_counts"][k] != ref["mask_counts"][k] for k in common):
        diffs.append("mask_counts")
    return {"verdict": "fail" if diffs else "pass", "differences": diffs,
            "n_masks": len(ref.get("masks") or []),
            "archives": [Path((bench.get(k) or {}).get("path", "")).name for k in ("local_archive", "remote_archive")]}


def identity_main(spec_path: str) -> int:
    """Run one pair's identity check (`--identity-child`): archives, settings, EDI and the controls.

    Each check is a profile_run phase; the result JSON goes to the spec's
    "result" path.

    Returns:
        int: 0 (the verdict is in the result).
    """
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    tol = float(spec["tol"])
    result: dict = {"archives": [], "settings": None, "edi": None, "controls": {}}
    for arc in spec["archives"]:
        if not arc["reference"]:
            result["archives"].append({"site": arc["site"], "verdict": "n/a", "reason": "no reference archive"})
            continue
        with prof.phase(f"archive {arc['site']}"):
            r = compare_archives(arc["bench"], arc["reference"])
        result["archives"].append({"site": arc["site"], **r, "bench": arc["bench"], "reference": arc["reference"]})
    ref_side = json.loads(Path(spec["reference_sidecar"]).read_text(encoding="utf-8"))
    ref_edi = Path(spec["reference_sidecar"]).with_name(ref_side.get("edi") or
                                                        f"{Path(spec['reference_sidecar']).stem}.edi")
    bench_edi = None
    if spec.get("bench_sidecar"):
        side_path = Path(spec["bench_sidecar"])
        bench_side = json.loads(side_path.read_text(encoding="utf-8"))
        bench_edi = side_path.with_name(bench_side.get("edi") or f"{side_path.stem}.edi")
        with phase_or_null("settings"):
            result["settings"] = compare_settings(bench_side, ref_side)
        with prof.phase("EDI"):
            result["edi"] = {"bench": str(bench_edi), "reference": str(ref_edi),
                             **compare_edi(read_edi(bench_edi), read_edi(ref_edi), tol)}
    ctl = spec.get("controls") or {}
    if ctl:
        with prof.phase("controls"):
            c = result["controls"]
            if bench_edi is not None and ctl.get("edi_other_reference"):
                r = compare_edi(read_edi(bench_edi), read_edi(Path(ctl["edi_other_reference"])), tol)
                c["edi_vs_other_reference"] = {"other": ctl["edi_other_name"], "verdict": r["verdict"],
                                               "reason": r.get("reason"), "max_rel_z": r.get("max_rel_z"),
                                               "n_periods_over_tol": r.get("n_periods_over_tol")}
            ref_blocks = read_edi(ref_edi)
            bumped = {k: v.copy() for k, v in ref_blocks.items()}
            key = next(k for k in ("ZXYR", "ZYXR", "ZXXR") if k in bumped)
            i = int(len(bumped[key]) // 2)
            bumped[key][i] *= 1.0 + 1e-6
            r = compare_edi(bumped, ref_blocks, tol)
            c["edi_perturbed_1e-6"] = {"block": key, "index": i, "verdict": r["verdict"],
                                       "max_rel_z": r.get("max_rel_z")}
            arcs = [a for a in spec["archives"] if a["reference"]]
            if arcs and ctl.get("archive_other_reference") and Path(ctl["archive_other_reference"]).exists():
                r = compare_archives(arcs[0]["bench"], ctl["archive_other_reference"], stop_first=True)
                c["archive_vs_other_site"] = {"bench": arcs[0]["site"], "other": ctl["archive_other_site"],
                                              "verdict": r["verdict"], "differences": r["differences"][:3]}
            if arcs:
                r = compare_archives(arcs[0]["bench"], arcs[0]["reference"], perturb=True)
                c["archive_one_sample_changed"] = {"site": arcs[0]["site"], "verdict": r["verdict"],
                                                   "differences": r["differences"][:3]}
            for v in c.values():
                v["failed_as_required"] = v["verdict"] == "fail"
    checks = [a["verdict"] for a in result["archives"]]
    checks += [x["verdict"] for x in (result["settings"], result["edi"]) if x]
    broken = [k for k, v in result["controls"].items() if not v["failed_as_required"]]
    verdict = "fail" if ("fail" in checks or broken) else ("pass" if "pass" in checks else "n/a")
    result["verdict"] = verdict
    result["summary"] = {
        "archives": {a["site"]: a["verdict"] for a in result["archives"]},
        "settings": result["settings"]["verdict"] if result["settings"] else None,
        "settings_differences": result["settings"]["differences"] if result["settings"] else None,
        "edi": result["edi"]["verdict"] if result["edi"] else None,
        "edi_max_rel_z": result["edi"].get("max_rel_z") if result["edi"] else None,
        "edi_max_rel_var": result["edi"].get("max_rel_var") if result["edi"] else None,
        "edi_periods": result["edi"].get("n_periods") if result["edi"] else None,
        "controls": {k: v["verdict"] for k, v in result["controls"].items()},
        "controls_not_failing": broken, "result": spec["result"]}
    Path(spec["result"]).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps(result["summary"], default=str), flush=True)
    return 0


class phase_or_null(prof.phase):
    """A profile_run phase for a check too short to matter: marked as a detail."""

    def __init__(self, name: str):
        super().__init__(name, kind="D")


def main(argv=None) -> int:
    """Run the bench, or one identity check (`--identity-child SPEC`)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--identity-child"]:
        return identity_main(argv[1])
    return Bench(build_parser().parse_args(argv)).run()


if __name__ == "__main__":
    sys.exit(main())
