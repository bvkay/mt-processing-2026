# -*- coding: utf-8 -*-
"""
Unit test for the pair checks of scripts/process_rr.py --dry-run

A synthetic LEMI-423 survey in the scratch directory declares four sites:
A (one synthetic B423 file in its raw folder, no archive), B (the same,
and an archive file in the workspace), D (recorded three days before A
and B) and E (no
start or end in survey.yaml; its archive, written with h5py, holds one run
three days before A's). process_rr.py is run on the command line with
--dry-run (cases 9a, 9b and 4 below), and its
exit status, stdout and stderr are read.

Usage:
    python tests/process_rr_pair_check_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the dry run of A rr B (the control) does not exit 0,
does not mark A's raw archive "missing" and B's not, or does not print both
spans; if A rr D (survey.yaml spans that do not overlap, case 4) or A rr E
(E's span read from its archive) does not exit 2 with both sites' spans
in the message; or if C99 rr B (C99 has no survey.yaml entry, case 9b)
does not exit 2 naming C99. Before the fix every one of these dry runs
exited 0, and the raw archive line read the same with or without the file.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

import h5py  # noqa: E402
import yaml  # noqa: E402

from _scratch import scratch_dir  # noqa: E402
from mtio_fork_unit import _write_b423  # noqa: E402

SCRIPT = REPO / "scripts" / "process_rr.py"
ROOT = scratch_dir("process_rr_pair_check_unit")
EPOCH = 1695385282  # 2023-09-22T12:21:22Z, C18's start


def make_survey() -> Path:
    """Write the four-site survey, A's raw file, B's archive file and E's archive; return survey.yaml."""
    shutil.rmtree(ROOT, ignore_errors=True)
    for site in ("A", "B"):
        _write_b423(ROOT / "raw" / site / f"{EPOCH}.B423", epoch=EPOCH, n=2000)
    (ROOT / "work" / "mth5").mkdir(parents=True)
    (ROOT / "work" / "mth5" / "B.h5").write_bytes(b"")  # exists: the raw line must not say missing
    with h5py.File(ROOT / "work" / "mth5" / "E.h5", "w") as f:
        run = f.create_group("Experiment/Surveys/SYN/Stations/E/sr1000_0001")
        run.attrs["time_period.start"] = "2023-09-19T11:19:28+00:00"
        run.attrs["time_period.end"] = "2023-09-21T09:49:32+00:00"
    span = {"start": "2023-09-22T12:21:22Z", "end": "2023-09-24T10:51:26Z"}
    sites = {"A": {"latitude": 31.77, "longitude": -5.46, **span},
             "B": {"latitude": 31.74, "longitude": -5.49, **span},
             "D": {"latitude": 31.70, "longitude": -5.40, "start": "2023-09-19T11:19:28Z",
                   "end": "2023-09-21T09:49:32Z"},
             "E": {"latitude": 31.60, "longitude": -5.40}}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(ROOT / "raw"),
           "workspace": str(ROOT / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "defaults": {"channels": ["ex", "ey", "hx", "hy"]}, "sites": sites}
    (ROOT / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (ROOT / "filters.yaml").write_text("{}\n", encoding="utf-8")
    return ROOT / "survey.yaml"


def dry_runs(survey_yaml: Path, pairs) -> dict:
    """Run process_rr.py --dry-run on each pair at once; return {pair: (exit, stdout, stderr)}."""
    procs = {pair: subprocess.Popen([sys.executable, str(SCRIPT), str(survey_yaml), *pair, "--no-masks", "--dry-run"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                    errors="replace", cwd=REPO)
             for pair in pairs}
    out = {}
    for pair, proc in procs.items():
        stdout, stderr = proc.communicate(timeout=600)
        out[pair] = (proc.returncode, stdout, stderr)
    return out


def main() -> int:
    """Run the four dry runs and check them; return the number of failures."""
    survey_yaml = make_survey()
    got = dry_runs(survey_yaml, [("A", "B"), ("A", "D"), ("A", "E"), ("C99", "B")])
    failures = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"  {'ok' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(name)

    code, out, err = got[("A", "B")]
    lines = {ln.split(":", 1)[0]: ln for ln in out.splitlines() if ":" in ln}
    local, remote = lines.get("local archive", ""), lines.get("remote archive", "")
    check("A rr B exits 0", code == 0, f"exit {code}")
    check("A's raw archive marked missing", "(missing: ingested from" in local and str(ROOT / "raw" / "A") in local,
          local)
    check("B's raw archive not marked missing", remote.startswith("remote archive: raw:") and "missing" not in remote,
          remote)
    check("both spans printed", "2023-09-22T12:21:22Z to 2023-09-24T10:51:26Z (survey.yaml)" in lines.get("local_span", "")
          and "B 2023-09-22T12:21:22Z" in lines.get("remote_span", ""),
          f"{lines.get('local_span')} | {lines.get('remote_span')}")

    code, out, err = got[("A", "D")]
    last = (err.strip().splitlines() or [""])[-1]
    check("A rr D (no overlap, survey.yaml spans) exits 2 with both spans",
          code == 2 and "share no time" in err and "2023-09-22T12:21:22Z to 2023-09-24T10:51:26Z" in err
          and "2023-09-19T11:19:28Z to 2023-09-21T09:49:32Z" in err and "Traceback" not in err,
          f"exit {code}: {last}")

    code, out, err = got[("A", "E")]
    last = (err.strip().splitlines() or [""])[-1]
    check("A rr E (E's span from its archive) exits 2 with both spans",
          code == 2 and "share no time" in err and "E.h5" in err and "2023-09-19T11:19:28Z" in err,
          f"exit {code}: {last}")

    code, out, err = got[("C99", "B")]
    last = (err.strip().splitlines() or [""])[-1]
    check("C99 rr B (no survey.yaml entry) exits 2 naming C99",
          code == 2 and "C99 has no entry in survey.yaml" in err and "Traceback" not in err,
          f"exit {code}: {last}")
    return len(failures)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    n = main()
    print(f"\n{'FAIL' if n else 'PASS'}  process_rr_pair_check_unit ({n} check(s) failed)")
    sys.exit(1 if n else 0)
