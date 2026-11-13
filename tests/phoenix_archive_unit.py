# -*- coding: utf-8 -*-
"""
Unit test for the stamp correction read back from a Phoenix archive (mt_workbench.phoenix.archive_stamp_correction)

Synthetic archives are written with mth5 into scratch: one station whose
``provenance.comments`` holds the stamp line, the stamp line after or
before a `clock_offset_s` line, a 0.0 s correction, text with no stamp
line, or no comment at all, each with a few runs, and one station of
`N_RUNS` runs of one 10-sample channel, as a burst archive holds one run
per burst. The value of `archive_stamp_correction` is compared with the
reference read `mth5_reference` (the archive opened
with mth5 and the station's metadata built, the slow read of
upstream issue 74). The real P-test archive PT_10133.h5 (one
run, 150 Hz) is compared too when it is present, read only.

Usage:
    python tests/phoenix_archive_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - A1: on any fixture archive, or on PT_10133.h5 when present, the value
    differs from `mth5_reference`'s (1.0, 0.0, -0.5 and None on the
    fixtures; 1.0 on PT_10133.h5);
  - A2: a missing archive or a station the archive does not hold does not
    raise `MTH5Error`, as the reference does, or the station's error does
    not read "Could not find station <site>";
  - A3: on the station of `N_RUNS` runs the read opens the archive through
    mth5 (`MTH5.open_mth5` is counted), takes 1 s or more, or takes more
    than a tenth of the reference's time.

The mutation, which must trip A3: the function replaced by
`mth5_reference`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402
from mth5.mth5 import MTH5  # noqa: E402
from mth5.utils.exceptions import MTH5Error  # noqa: E402

import mt_workbench.phoenix as phoenix  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("phoenix_archive_unit")
N_RUNS = 400
STAMP = "phoenix_stamp_correction_s: {:.1f} s added to every time stamp (file version 2 stamps are 1 s behind GPS)"
CLOCK = "clock_offset_s: -1.0 s added to every recorded time stamp at ingest (declared logger clock error)"
# fixture name -> (station comment, runs, expected value)
FIXTURES = {
    "stamp": (STAMP.format(1.0), 3, 1.0),
    "stamp_then_clock": (f"{STAMP.format(0.0)}; {CLOCK}", 3, 0.0),
    "clock_then_stamp": (f"{CLOCK}; {STAMP.format(-0.5)}", 3, -0.5),
    "no_stamp": ("dc level read at ingest", 3, None),
    "no_comment": (None, 3, None),
    "many_runs": (STAMP.format(1.0), N_RUNS, 1.0),
}
PTEST = Path(r"D:\MT_DATA\MT_Kalkaroo_Workspace\mth5\PT_10133.h5")
MTH5_OPENS: list[str] = []
_open_mth5 = MTH5.open_mth5


def _counting_open(self, filename, *args, **kwargs):
    MTH5_OPENS.append(str(filename))
    return _open_mth5(self, filename, *args, **kwargs)


MTH5.open_mth5 = _counting_open


def mth5_reference(path: Path, site_name: str) -> float | None:
    """Return the stamp correction as the function read it before the change (mth5, station metadata)."""
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey_name = m.surveys_group.groups_list[0]
        comment = str(m.get_station(site_name, survey=survey_name).metadata.provenance.comments.value or "")
    finally:
        m.close_mth5()
    for line in comment.split("; "):
        if line.startswith("phoenix_stamp_correction_s: "):
            return float(line[len("phoenix_stamp_correction_s: "):].split(" ", 1)[0])
    return None


def write_archive(name: str, comment: str | None, n_runs: int) -> Path:
    """Write a fixture archive: survey PHOENIX_TEST, station B1H with `comment` and `n_runs` runs of one channel."""
    path = SCRATCH / f"{name}.h5"
    path.unlink(missing_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey("PHOENIX_TEST")
        station = m.add_station("B1H", survey="PHOENIX_TEST")
        if comment is not None:
            station.metadata.provenance.comments.value = comment
            station.write_metadata()
        for k in range(n_runs):
            run = station.add_run(f"sr24000_{k + 1:05d}")
            run.add_channel("ex", "electric", np.zeros(10, dtype="f4"))
    finally:
        m.close_mth5()
    return path


def check_values(paths: dict[str, Path]) -> list[str]:
    """A1: the value on every fixture, and on PT_10133.h5 when present. Returns the failures."""
    bad = []
    for name, path in paths.items():
        want = FIXTURES[name][2]
        got, ref = phoenix.archive_stamp_correction(path, "B1H"), mth5_reference(path, "B1H")
        if got != ref or got != want:
            bad.append(f"{name}: {got!r}, the reference {ref!r}, expected {want!r}")
    if PTEST.exists():
        got, ref = phoenix.archive_stamp_correction(PTEST, "PT_10133"), mth5_reference(PTEST, "PT_10133")
        if got != ref or got != 1.0:
            bad.append(f"PT_10133.h5: {got!r}, the reference {ref!r}")
    return bad


def raised(call) -> BaseException | None:
    """Return the exception a call raises, or None."""
    try:
        call()
    except BaseException as exc:  # noqa: BLE001  (the type is the check)
        return exc
    return None


def check_errors(path: Path) -> list[str]:
    """A2: the errors of a missing archive and a missing station. Returns the failures."""
    bad = []
    missing = SCRATCH / "missing.h5"
    for label, args in (("missing archive", (missing, "B1H")), ("missing station", (path, "NOPE"))):
        got = raised(lambda: phoenix.archive_stamp_correction(*args))
        ref = raised(lambda: mth5_reference(*args))
        if not isinstance(ref, MTH5Error):
            bad.append(f"{label}: premise, the reference raised {ref!r}")
        if not isinstance(got, MTH5Error):
            bad.append(f"{label}: raised {got!r}, the reference MTH5Error")
        elif label == "missing station" and str(got) != "Could not find station NOPE":
            bad.append(f"{label}: {str(got)!r}")
    return bad


def check_cost(path: Path) -> tuple[list[str], str]:
    """A3: mth5 opens and the time on the station of N_RUNS runs. Returns the failures and the timings."""
    tic = time.perf_counter()
    mth5_reference(path, "B1H")
    ref_s = time.perf_counter() - tic
    MTH5_OPENS.clear()
    tic = time.perf_counter()
    phoenix.archive_stamp_correction(path, "B1H")
    got_s = time.perf_counter() - tic
    opens = list(MTH5_OPENS)
    bad = []
    if opens:
        bad.append(f"{len(opens)} mth5 open(s) of {Path(opens[0]).name}")
    if got_s >= 1.0 or got_s > ref_s / 10:
        bad.append(f"{got_s:.3f} s against the reference's {ref_s:.3f} s ({N_RUNS} runs)")
    return bad, f"{got_s * 1000:.1f} ms against the reference's {ref_s:.2f} s, {len(opens)} mth5 open(s)"


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    paths = {name: write_archive(name, comment, n) for name, (comment, n, _want) in FIXTURES.items()}
    failures = []

    bad = check_values(paths)
    failures += bad
    print(f"  A1 values: {'ok' if not bad else bad}: "
          f"{', '.join(f'{k} {v[2]!r}' for k, v in FIXTURES.items())}"
          f"{', PT_10133.h5 1.0' if PTEST.exists() else ' (PT_10133.h5 absent, not compared)'}")
    bad = check_errors(paths["stamp"])
    failures += bad
    print(f"  A2 errors: {'ok' if not bad else bad}: MTH5Error for a missing archive and a missing station")
    bad, timing = check_cost(paths["many_runs"])
    failures += bad
    print(f"  A3 cost: {'ok' if not bad else bad}: {timing}")

    kept = phoenix.archive_stamp_correction
    phoenix.archive_stamp_correction = mth5_reference
    try:
        trip, timing = check_cost(paths["many_runs"])
    finally:
        phoenix.archive_stamp_correction = kept
    assert trip, "mutation A3 (the mth5 read) did not trip"
    print(f"  A3 mutation (the mth5 read) tripped: {trip[0]}")

    if failures:
        print("\nFAIL  phoenix_archive_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    print("\nPASS  phoenix_archive_unit")


if __name__ == "__main__":
    main()
