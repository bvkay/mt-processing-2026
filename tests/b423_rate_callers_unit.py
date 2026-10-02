# -*- coding: utf-8 -*-
"""
Unit test for the B423 grouping of scripts/psd_qc.py and scripts/profile_run.py

`mt_workbench.ingest._group_contiguous` ends a LEMI-423 run at a file cut
short of its span only when it is given the site's rate. Four synthetic
B423 files of 4 s at 1000 Hz, named 4 s apart, are written into a scratch
site folder, the second cut to 2000 whole records and 17 bytes (as
robustness case 5c cut a real copy); a control folder holds the four
files uncut. Each script is imported and its grouping called dry:
psd_qc.py's `load_before` with `MAX_BEFORE_SAMPLES` set to 0 (so it reads
the longest group) and `read_lemi423` replaced by a stub that records the
files it is given and stops; profile_run.py's `b423_longest_run`, the
files its read benchmark times. No archive is written and nothing is
read but the file names and sizes.

Usage:
    python tests/b423_rate_callers_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** on the cut set psd_qc.py's `load_before` reads
anything but files 1-2 (the longest of two groups; without the rate the
four files form one group and it reads all four) or profile_run.py has no
`b423_longest_run` or it returns anything but files 1-2; or if on the
uncut control either does not take all four files.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRATCH = scratch_dir("b423_rate_callers_unit")
EPOCH = 1695390686
RATE = 1000
N = 4000  # records per file: 4 s at 1000 Hz


class _Read(Exception):
    """Raised by the stub reader with the files psd_qc.py asked it to read."""


def build(name: str, cut: bool) -> tuple[Survey, list[str]]:
    """Write four back-to-back B423 files under <scratch>/<name>, the second cut when `cut`."""
    root = SCRATCH / name
    shutil.rmtree(root, ignore_errors=True)
    site = root / "raw" / "S01"
    names = []
    for k in range(4):
        epoch = EPOCH + k * N // RATE
        _write_b423(site / f"{epoch}.B423", epoch=epoch, n=N, rate=RATE)
        names.append(f"{epoch}.B423")
    if cut:
        os.truncate(site / names[1], 1024 + 30 * 2000 + 17)
    survey = Survey({"name": "t", "instrument": "lemi423", "sample_rate": RATE, "data_root": str(root / "raw"),
                     "workspace": str(root / "work"),
                     "defaults": {"channels": ["ex", "ey", "hx", "hy"], "dipole_length_ex": 50.0,
                                  "dipole_length_ey": 50.0},
                     "sites": {"S01": {}}}, root)
    return survey, names


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def psd_qc_reads(psd_qc, survey: Survey, names: list[str]) -> list[str]:
    """Call psd_qc.load_before dry; return the names of the files it would read."""
    def stub(files, **kwargs):
        raise _Read([Path(f).name for f in (files if isinstance(files, (list, tuple)) else [files])])

    saved = psd_qc.read_lemi423, psd_qc.MAX_BEFORE_SAMPLES
    psd_qc.read_lemi423, psd_qc.MAX_BEFORE_SAMPLES = stub, 0
    try:
        import pandas as pd

        psd_qc.load_before(survey, "S01", ["ex"], pd.Timestamp(EPOCH, unit="s"),
                           pd.Timestamp(EPOCH + 4 * N // RATE, unit="s"))
    except _Read as got:
        return got.args[0]
    finally:
        psd_qc.read_lemi423, psd_qc.MAX_BEFORE_SAMPLES = saved
    raise AssertionError("psd_qc.load_before did not reach the reader")


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="WARNING", format="{level} {message}")
    psd_qc, profile_run = _load("psd_qc"), _load("profile_run")
    failures = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"  {'ok' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(name)

    for label, cut in (("cut", True), ("control", False)):
        survey, names = build(label, cut)
        want = names[:2] if cut else names
        got = psd_qc_reads(psd_qc, survey, names)
        check(f"psd_qc.py load_before ({label})", got == want, f"reads {got}, want {want}")
        if not hasattr(profile_run, "b423_longest_run"):
            check(f"profile_run.py ({label})", False, "no b423_longest_run: the read benchmark groups without "
                  "the rate inside bench_read")
            continue
        got = [p.name for p in profile_run.b423_longest_run(survey, "S01")]
        check(f"profile_run.py b423_longest_run ({label})", got == want, f"gives {got}, want {want}")

    print(f"\n{'FAIL' if failures else 'PASS'}  b423_rate_callers_unit "
          f"({len(failures)} failed{': ' + ', '.join(failures) if failures else ''})")
    return 1 if failures else 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    sys.exit(main())
