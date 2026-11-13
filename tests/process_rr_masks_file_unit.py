# -*- coding: utf-8 -*-
"""
Unit test for process_rr.py --masks-file (candidate masks read from a file outside the survey's masks.yaml)

On a synthetic two-site survey in a temporary folder (no archive, no aurora):
the survey A has no masks.yaml and a candidate file elsewhere holds entries
for A and B; the survey B is the same survey with the candidate file's
entries copied into its masks.yaml.

Usage:
    python tests/process_rr_masks_file_unit.py

**This test fails if**

1. `resolve` for A rr B with `--masks-file <candidate>` on survey A does not
   give exactly the masks_local, masks_remote, masks, channel_runs and
   mask_counts that survey B gives with no flag (the entries copied into its
   masks.yaml), for both pair directions and under `--mask-scope union`;
2. without the flag survey A applies anything (it has no masks.yaml), or
   survey B's resolution with no flag differs from what it was before the
   option existed (its masks.yaml entries, by reason and start);
3. the sidecar does not record `masks_file` (the path given; null without
   the flag), or the resolution does not print a "masks file:" line;
4. `--masks-file` with `--no-masks`, or a file that does not exist, is not
   refused (SystemExit);
5. the run touches survey A's folder: a masks.yaml appears there.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

T0 = pd.Timestamp("2023-09-22T00:00:00", tz="UTC")


def entry(h0, h1, reason, bands="all", scope=None, channels=None, found_by="stretch"):
    out = {"start": (T0 + pd.Timedelta(hours=h0)).isoformat().replace("+00:00", "Z"),
           "end": (T0 + pd.Timedelta(hours=h1)).isoformat().replace("+00:00", "Z"),
           "bands": bands, "reason": reason, "found_by": found_by}
    if scope:
        out["scope"] = scope
    if channels:
        out["channels"] = channels
    return out


CANDIDATE = {
    "A": [entry(0, 3, "A xy stretch", bands=[0.0, 1000.0], channels=["ex"]),
          entry(10, 12, "A yx stretch", bands=[0.0, 1000.0], channels=["ey"]),
          entry(5, 6, "A both-scoped time cut", scope="both", found_by="time")],
    "B": [entry(2, 3, "B local stretch", bands=[0.0, 1000.0], channels=["ex"]),
          entry(7, 8, "B both-scoped H cut", scope="both", channels=["hx", "hy"], found_by="time")],
}


def make_survey(root: Path, masks: dict | None) -> Path:
    sites = {s: {"latitude": 31.0 + 0.045 * k, "longitude": -5.5, "start": "2023-09-22T00:00:00Z",
                 "end": "2023-09-23T00:00:00Z"} for k, s in enumerate(("A", "B"))}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text("{}\n", encoding="utf-8")
    if masks is not None:
        (root / "masks.yaml").write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")
    return root / "survey.yaml"


def load_process_rr():
    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    return module


KEYS = ("masks_local", "masks_remote", "masks", "mask_counts")


def main() -> int:
    pr = load_process_rr()
    started = dt.datetime(2026, 11, 9, 9, 0, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sa = make_survey(tmp / "A", None)
        sb = make_survey(tmp / "B", CANDIDATE)
        cand = tmp / "cand" / "candidate.yaml"
        cand.parent.mkdir()
        cand.write_text(yaml.safe_dump(CANDIDATE, sort_keys=False), encoding="utf-8")

        def res_of(survey_yaml, local, remote, *extra):
            args = pr.build_parser().parse_args([str(survey_yaml), local, remote, *extra])
            res = pr.resolve(args, started)
            return args, res

        # 1. identical to the entries copied into a masks.yaml
        for local, remote, extra in (("A", "B", ()), ("B", "A", ()), ("A", "B", ("--mask-scope", "union"))):
            _, ra = res_of(sa, local, remote, "--masks-file", str(cand), *extra)
            _, rb = res_of(sb, local, remote, *extra)
            for k in KEYS:
                assert ra[k] == rb[k], (local, remote, extra, k, ra[k], rb[k])
            assert [(r["channels"], r["masks"], r["base"]) for r in ra["channel_runs"]] == \
                   [(r["channels"], r["masks"], r["base"]) for r in rb["channel_runs"]], (ra["channel_runs"],
                                                                                         rb["channel_runs"])
            print(f"1. {local} rr {remote} {' '.join(extra) or ''}: --masks-file == masks.yaml copy "
                  f"({len(ra['masks'])} applied, runs {pr.runs_text(ra['channel_runs'])})")

        # 2. without the flag nothing changes
        _, ra = res_of(sa, "A", "B")
        assert ra["masks"] == [] and ra["masks_local"] == [] and ra["masks_remote"] == [], ra["masks"]
        _, rb = res_of(sb, "A", "B")
        assert [m["reason"] for m in rb["masks_local"]] == ["A xy stretch", "A both-scoped time cut",
                                                            "A yx stretch"], rb["masks_local"]
        assert [m["reason"] for m in rb["masks_remote"]] == ["B both-scoped H cut"], rb["masks_remote"]
        print("2. without the flag: survey A applies nothing; survey B applies its masks.yaml as before")

        # 3. sidecar and resolution line
        args, ra = res_of(sa, "A", "B", "--masks-file", str(cand))
        edi = ra["survey"].workspace / "tf" / f"{ra['stem']}.edi"
        side = pr.build_sidecar(ra, args, started, started, edi, edi.with_suffix(".png"), {}, [])
        json.loads(json.dumps(side, default=str))
        assert side["masks_file"] == str(cand), side.get("masks_file")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pr.print_resolution(ra)
        assert f"masks file: {cand}" in out.getvalue(), out.getvalue()
        args, rb = res_of(sb, "A", "B")
        side_b = pr.build_sidecar(rb, args, started, started, edi, edi.with_suffix(".png"), {}, [])
        assert side_b["masks_file"] is None, side_b.get("masks_file")
        print("3. sidecar masks_file = the path (null without the flag); resolution prints 'masks file:'")

        # 4. refusals
        for extra in (("--masks-file", str(cand), "--no-masks"), ("--masks-file", str(tmp / "nope.yaml"))):
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    res_of(sa, "A", "B", *extra)
                except SystemExit:
                    pass
                else:
                    raise AssertionError(f"{extra} was not refused")
        print("4. --masks-file with --no-masks refused; a missing file refused")

        # 5. survey A untouched
        assert not (tmp / "A" / "masks.yaml").exists()
        print("5. survey A's folder has no masks.yaml")
    print("process_rr_masks_file_unit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
