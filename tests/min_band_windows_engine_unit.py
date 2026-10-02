# -*- coding: utf-8 -*-
"""
Unit test for min_band_windows under the two engines of scripts/process_rr.py

The floor on STFT windows per band (`mt_workbench.process.drop_short_bands`)
acts inside aurora's `process_station` alone. On a two-site synthetic
survey, process_rr.py's `resolve`, `print_resolution` and `build_sidecar`
are called in process with each engine; no archive is read and no engine
runs.

Usage:
    python tests/min_band_windows_engine_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** an aurora resolution does not take 5 by default, 3
from `--min-band-windows 3` and 7 from survey.yaml `processing:
min_band_windows: 7`, print `min_band_windows: <n>` and record the same
in the sidecar; or if `--engine mantle --min-band-windows 3` is not
refused naming --min-band-windows, or a MANTLE resolution (with the
survey.yaml key or without it) prints a min_band_windows line or gives a
sidecar whose `min_band_windows` is not null. Before this check the
MANTLE flag was taken silently and the sidecar recorded 5, a setting
that did not act.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import yaml  # noqa: E402

from _scratch import scratch_dir  # noqa: E402

ROOT = scratch_dir("min_band_windows_engine_unit")
STARTED = dt.datetime(2026, 10, 3, 7, 0).astimezone()
QUADRANT = {"pmin": 0.1, "pmax": 10.0, "xy": 45.0, "yx": -135.0, "xy_ok": True, "yx_ok": True, "reason": ""}


def _survey(name: str, processing: dict) -> Path:
    """Write a two-site LEMI-423 survey (A, B recorded at the same time, no masks); return its survey.yaml."""
    root = ROOT / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    span = {"start": "2023-09-22T12:21:22Z", "end": "2023-09-24T10:51:26Z"}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0, **processing},
           "sites": {"A": {"latitude": 31.0, "longitude": -5.5, **span},
                     "B": {"latitude": 31.05, "longitude": -5.5, **span}}}
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text("{}\n", encoding="utf-8")
    return root / "survey.yaml"


def _process_rr():
    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from loguru import logger

    logger.remove()
    return module


def _run(pr, survey_yaml: Path, *options: str):
    """Resolve A rr B with `options`; return (resolution lines, sidecar) or the SystemExit raised."""
    args = pr.build_parser().parse_args([str(survey_yaml), "A", "B", "--no-masks", *options])
    try:
        res = pr.resolve(args, STARTED)
    except SystemExit as exc:
        return exc
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pr.print_resolution(res)
    side = pr.build_sidecar(res, args, STARTED, STARTED, Path("x.edi"), Path("x.png"), QUADRANT, [])
    return buf.getvalue().splitlines(), side


def main() -> int:
    pr = _process_rr()
    plain, keyed = _survey("plain", {}), _survey("keyed", {"min_band_windows": 7})
    failures = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"  {'ok' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(name)

    for name, survey_yaml, options, want in (("aurora default", plain, (), 5),
                                             ("aurora --min-band-windows 3", plain, ("--min-band-windows", "3"), 3),
                                             ("aurora survey.yaml 7", keyed, (), 7)):
        got = _run(pr, survey_yaml, *options)
        if isinstance(got, SystemExit):
            check(name, False, f"refused: {got}")
            continue
        lines, side = got
        printed = [ln for ln in lines if ln.startswith("min_band_windows")]
        check(name, printed == [f"min_band_windows: {want}"] and side.get("min_band_windows") == want,
              f"printed {printed}, sidecar min_band_windows {side.get('min_band_windows')!r}")

    got = _run(pr, plain, "--engine", "mantle", "--min-band-windows", "3")
    check("mantle --min-band-windows 3", isinstance(got, SystemExit) and "--min-band-windows" in str(got),
          f"refused: {got}" if isinstance(got, SystemExit) else
          f"taken: sidecar min_band_windows {got[1].get('min_band_windows')!r}")

    for name, survey_yaml in (("mantle default", plain), ("mantle survey.yaml 7", keyed)):
        got = _run(pr, survey_yaml, "--engine", "mantle")
        if isinstance(got, SystemExit):
            check(name, False, f"refused: {got}")
            continue
        lines, side = got
        printed = [ln for ln in lines if ln.startswith("min_band_windows")]
        check(name, not printed and "min_band_windows" in side and side["min_band_windows"] is None,
              f"printed {printed}, sidecar min_band_windows {side.get('min_band_windows', 'absent')!r}")

    print(f"\n{'FAIL' if failures else 'PASS'}  min_band_windows_engine_unit "
          f"({len(failures)} failed{': ' + ', '.join(failures) if failures else ''})")
    return 1 if failures else 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    sys.exit(main())
