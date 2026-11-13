# -*- coding: utf-8 -*-
"""
Unit test for min_band_windows under the two engines of scripts/process_rr.py

The floor on STFT windows per band (`mt_workbench.process.drop_short_bands`)
acts inside aurora's `process_station` alone. On a two-site synthetic
survey, process_rr.py's `resolve`, `print_resolution` and `build_sidecar`
are called in process with each engine; no archive is read and no engine
runs. The periods an aurora run's floor removed are handed to
`build_sidecar` as `main` hands them (the resolution's `dropped_periods`,
read off each run's TF), unsorted and with a repeat, as two masked runs
give them.

Usage:
    python tests/min_band_windows_engine_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** an aurora resolution does not take 2 by default
(`MIN_BAND_WINDOWS`; set back to 5, this trips), 3 from
`--min-band-windows 3` and 7 from survey.yaml `processing:
min_band_windows: 7`, print `min_band_windows: <n>` and record the same
in the sidecar; an aurora sidecar's `dropped_periods` is not
{"n": 0, "periods_s": [], "min_band_windows": <n>} when nothing was
dropped, or, given 4507.6, 3663.6 and 4507.6 s again, not n 2 with
[3663.6, 4507.6] (a repeat counted twice or the list left unsorted
trips); or if `--engine mantle --min-band-windows 3` is not refused
naming --min-band-windows, or a MANTLE resolution (with the survey.yaml
key or without it) prints a min_band_windows line or gives a sidecar
whose `min_band_windows` or `dropped_periods` is not null. Before this
check the MANTLE flag was taken silently and the sidecar recorded 5, a
setting that did not act.
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


def _run(pr, survey_yaml: Path, *options: str, dropped=None):
    """Resolve A rr B with `options`; return (resolution lines, sidecar) or the SystemExit raised.

    `dropped` stands for the periods the run's floor removed, set on the
    resolution as `main` sets it after aurora runs.
    """
    args = pr.build_parser().parse_args([str(survey_yaml), "A", "B", "--no-masks", *options])
    try:
        res = pr.resolve(args, STARTED)
    except SystemExit as exc:
        return exc
    if dropped is not None:
        res["dropped_periods"] = list(dropped)
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

    for name, survey_yaml, options, want in (("aurora default", plain, (), 2),
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
        none = {"n": 0, "periods_s": [], "min_band_windows": want}
        check(f"{name}, nothing dropped", side.get("dropped_periods") == none,
              f"sidecar dropped_periods {side.get('dropped_periods', 'absent')!r}")

    got = _run(pr, plain, dropped=[4507.6, 3663.6, 4507.6])
    want = {"n": 2, "periods_s": [3663.6, 4507.6], "min_band_windows": 2}
    check("aurora default, two periods dropped", not isinstance(got, SystemExit)
          and got[1].get("dropped_periods") == want,
          f"refused: {got}" if isinstance(got, SystemExit) else
          f"sidecar dropped_periods {got[1].get('dropped_periods', 'absent')!r}")

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
        check(name, not printed and "min_band_windows" in side and side["min_band_windows"] is None
              and "dropped_periods" in side and side["dropped_periods"] is None,
              f"printed {printed}, sidecar min_band_windows {side.get('min_band_windows', 'absent')!r}, "
              f"dropped_periods {side.get('dropped_periods', 'absent')!r}")

    print(f"\n{'FAIL' if failures else 'PASS'}  min_band_windows_engine_unit "
          f"({len(failures)} failed{': ' + ', '.join(failures) if failures else ''})")
    return 1 if failures else 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    sys.exit(main())
