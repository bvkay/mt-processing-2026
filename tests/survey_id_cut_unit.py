# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.process._restore_survey_ids: a survey id longer than mth5's 30-character summary field

mth5 0.6.9 holds the survey id of its channel and run summaries in 30 characters (docs/upstream_issues.md 550),
so a run summary of an archive pair whose survey id is longer carries the id cut, and the kernel dataset's run
lookup then fails ("Could not find /Experiment/Surveys/<cut id>/Stations/..."). `kernel_dataset` puts each
archive's own id back. The synthetic pair is tests/crosspower_unit.write_archive's layout (an L station with ex
ey hx hy, an R station with hx hy, 100 Hz, 120 s each) written under the survey id given here.

Usage:
    python tests/survey_id_cut_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. the run summary that mth5 alone builds from the 31-character pair does not carry the id cut to 30 characters
   on every row (the upstream defect has gone or is not the one repaired: then this test and the repair can go);
2. `kernel_dataset` on that pair does not give the full 31-character id on every row, local and remote;
3. with the repair switched off (`_restore_survey_ids` patched to do nothing) the kernel dataset does not carry
   the cut id on every row (then clause 2 could not fail);
4. a pair whose id has 30 characters does not come back with that id unchanged, or any row is counted as
   restored;
5. an archive holding two survey ids that share the 30-character prefix does not make `kernel_dataset` raise a
   ValueError naming both ids and upstream 550, or an archive holding a 30-character id and a longer one that
   starts with it does not raise one naming both;
6. any archive's modification time changes in clauses 1 to 5;
7. `Survey.from_yaml` does not load a 31-character survey, does not log the warning naming upstream 550 for it,
   or logs it for a 30-character name.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _scratch import scratch_dir  # noqa: E402
import crosspower_unit as cu  # noqa: E402

from loguru import logger  # noqa: E402
from mt_workbench import process  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

LONG = "eastern_goldfields_lp_2018_2019"  # 31 characters, the survey of the defect
SHORT = LONG[:30]  # 30 characters: what mth5's summaries keep of LONG
TWIN = SHORT + "x"  # a second 31-character id with the same 30-character prefix
N = int(120 * cu.FS)
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILED.append(what)


def write_pair(folder: Path, survey: str) -> tuple[Path, Path]:
    """Write the L and R archives under `survey` (crosspower_unit.write_archive with its SURVEY set)."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    local, remote = folder / "L.h5", folder / "R.h5"
    for path in (local, remote):
        if path.exists():
            path.unlink()
    saved = cu.SURVEY
    cu.SURVEY = survey  # write_archive reads the module's survey id
    try:
        cu.write_archive(local, "L", [(cu.T0, {c: np.rint(1e4 * rng.standard_normal(N)) for c in
                                               ("ex", "ey", "hx", "hy")})])
        cu.write_archive(remote, "R", [(cu.T0, {c: np.rint(1e4 * rng.standard_normal(N)) for c in ("hx", "hy")})])
    finally:
        cu.SURVEY = saved
    return local, remote


def add_survey(path: Path, survey: str) -> None:
    """Add an empty survey group to an archive."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="a")
    try:
        m.add_survey(survey)
    finally:
        m.close_mth5()


def mtimes(paths) -> list[int]:
    return [os.stat(p).st_mtime_ns for p in paths]


def summary_ids(paths) -> list[str]:
    """The survey ids of the run summary mth5 alone builds."""
    rs = process.RunSummary()
    rs.from_mth5s([Path(p) for p in paths])
    return [str(s) for s in rs.df["survey"]]


def warnings_of(path: Path) -> list[str]:
    caught: list[str] = []
    sink = logger.add(lambda msg: caught.append(str(msg)), level="WARNING")
    try:
        Survey.from_yaml(path)
    finally:
        logger.remove(sink)
    return [w for w in caught if "upstream_issues.md 550" in w]


def write_yaml(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "survey.yaml"
    path.write_text(f"name: {name}\ninstrument: lemi423\nsample_rate: 10\ndata_root: {folder.as_posix()}\n",
                    encoding="utf-8")
    return path


def main() -> int:
    scratch = scratch_dir("survey_id_cut_unit")
    local, remote = write_pair(scratch / "long", LONG)
    before = mtimes([local, remote])

    # 1. the upstream defect: the run summary alone carries the cut id
    ids = summary_ids([local, remote])
    check(len(ids) == 2 and all(s == SHORT for s in ids),
          f"(1) mth5's run summary of the {len(LONG)}-character pair carries the {len(SHORT)}-character cut: {ids}")

    # 2. the repair: every kernel dataset row carries the full id
    kd = process.kernel_dataset(local, "L", remote, "R")
    got = [str(s) for s in kd.df["survey"]]
    check(len(got) == 2 and all(s == LONG for s in got) and set(kd.df["station"]) == {"L", "R"},
          f"(2) kernel_dataset gives the full id on every row, local and remote: {got}")

    # 3. the repair switched off: the cut id comes through, so clause 2 can fail
    original = process._restore_survey_ids
    process._restore_survey_ids = lambda rs: 0
    try:
        kd_off = process.kernel_dataset(local, "L", remote, "R")
    finally:
        process._restore_survey_ids = original
    off = [str(s) for s in kd_off.df["survey"]]
    check(len(off) == 2 and all(s == SHORT for s in off),
          f"(3) with the repair switched off the kernel dataset carries the cut id: {off}")

    # 4. an id of 30 characters is left as it is
    s_local, s_remote = write_pair(scratch / "short", SHORT)
    s_before = mtimes([s_local, s_remote])
    rs = process.RunSummary()
    rs.from_mth5s([s_local, s_remote])
    n = process._restore_survey_ids(rs)
    kd_short = process.kernel_dataset(s_local, "L", s_remote, "R")
    short_ids = [str(s) for s in kd_short.df["survey"]]
    check(n == 0 and all(s == SHORT for s in short_ids) and len(short_ids) == 2,
          f"(4) a {len(SHORT)}-character id comes back unchanged: {short_ids}, {n} rows restored")

    # 5. two survey ids of one archive share the cut: ValueError
    a_local, a_remote = write_pair(scratch / "ambiguous", LONG)
    add_survey(a_local, TWIN)
    a_before = mtimes([a_local, a_remote])
    message = ""
    try:
        process.kernel_dataset(a_local, "L", a_remote, "R")
    except ValueError as err:
        message = str(err)
    b_local, b_remote = write_pair(scratch / "ambiguous_short", SHORT)
    add_survey(b_local, TWIN)
    b_before = mtimes([b_local, b_remote])
    message_b = ""
    try:
        process.kernel_dataset(b_local, "L", b_remote, "R")
    except ValueError as err:
        message_b = str(err)
    check(LONG in message and TWIN in message and "550" in message
          and f"'{SHORT}'," in message_b and TWIN in message_b,
          f"(5) an ambiguous cut raises a ValueError naming both ids and upstream 550: {message!r}; "
          f"and so does a {len(SHORT)}-character id beside a longer one that starts with it: {message_b!r}")

    # 6. read-only throughout
    check(mtimes([local, remote]) == before and mtimes([s_local, s_remote]) == s_before
          and mtimes([a_local, a_remote]) == a_before and mtimes([b_local, b_remote]) == b_before,
          "(6) no archive's modification time changed")

    # 7. Survey.from_yaml warns for a long name and loads it
    long_yaml = write_yaml(scratch / "yaml_long", LONG)
    short_yaml = write_yaml(scratch / "yaml_short", SHORT)
    loaded = Survey.from_yaml(long_yaml).name
    w_long, w_short = warnings_of(long_yaml), warnings_of(short_yaml)
    check(loaded == LONG and len(w_long) == 1 and not w_short,
          f"(7) Survey.from_yaml loads {loaded!r}, warns once for it ({len(w_long)}) and not for "
          f"{len(SHORT)} characters ({len(w_short)})")

    print(("FAIL  " if FAILED else "PASS  ") + f"survey_id_cut_unit ({len(FAILED)} of 7 failed)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    os.environ.setdefault("MT_WORKBENCH_TEST_SCRATCH", str(Path(__file__).resolve().parents[1] / "work" / "scratch"))
    sys.exit(main())
