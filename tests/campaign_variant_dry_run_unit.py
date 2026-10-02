# -*- coding: utf-8 -*-
"""
Unit test for campaign.py's stage 0 dry run over variants already on disk

**This test fails if** `campaign.py --stage 0 --dry-run`, on a workspace
whose ledger has no row, does not list site A's variant, built by
`build_variant` and current for A's declared filters, as "ready" with its
file name instead of "to build"; if it lists site B's variant, a file under
B's current variant name whose run comment records another filters hash (a
stale file), or sites C, D and E, which have no variant file, as anything but
"to build"; or if the stage 0 count is not 4 variants (A left out, since the
run reuses it). In a second survey, it fails if C's variant, built and
current but with C's raw archive deleted afterwards, is listed "ready"
instead of "raw archive missing" with the raw archive's path, or is left out
of the count (the run's `processing_archive` stops on it, as
`process_rr.resolve` says). In a third, it fails if the dry run raises on D's
0-byte file or E's non-HDF5 file under their current variant names instead
of listing each "unreadable" with its file name and the first line of the
OSError `variant_ready` raises on it, or leaves them out of the count.

The survey and plan are campaign_unit's synthetic ones (`make_survey`,
`make_plan`: five sites, A to E, each declaring a 50 Hz notch, with empty
raw archives). A's raw archive is replaced by a real one-run MTH5 at
1000 Hz (`ingest_unit._write_raw_archive`, 2000 samples of hx and hy) and
its variant built from it; B's stale file is written directly with a run
comment "filters hash 00000000; ...". The second survey does the same for C
and then deletes C's raw archive; the third writes D's and E's variant
files as 0 bytes and as 64 bytes of text.

Usage:
    python tests/campaign_variant_dry_run_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import campaign as cp  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from campaign_unit import make_plan, make_survey  # noqa: E402
from ingest_unit import _write_raw_archive  # noqa: E402
from mt_workbench.ingest import build_variant, default_archive_path, variant_path, variant_ready  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRATCH = scratch_dir("campaign_variant_dry_run_unit")
T0 = "2023-09-22T00:00:00+00:00"
STAGE0 = ["s0_A", "s0_B", "s0_C", "s0_D", "s0_E"]


def lines_by_run(text: str) -> dict[str, str]:
    """Return the dry run's job lines by run id ("s0_A": the line)."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "done":
            parts = parts[1:]
        if parts and parts[0].startswith("s0_"):
            out[parts[0]] = line.strip()
    return out


def new_survey(name: str) -> tuple[Path, Survey, dict]:
    """Write campaign_unit's survey into a fresh scratch folder; return (survey.yaml, survey, raw data)."""
    root = SCRATCH / name
    shutil.rmtree(root, ignore_errors=True)
    survey_yaml = make_survey(root)
    rng = np.random.default_rng(5)
    data = {"hx": rng.normal(size=2000) * 1000 + 5000, "hy": rng.normal(size=2000) * 1000 - 3000}
    return survey_yaml, Survey.from_yaml(survey_yaml), data


def build_current(survey: Survey, site: str, data: dict) -> Path:
    """Write a real raw archive for `site` and build its variant; return the variant."""
    _write_raw_archive(default_archive_path(survey, site), site, "SYN", data, 1000.0, T0)
    out = build_variant(survey, site)
    assert variant_ready(survey, site), f"premise: {site}'s variant is not ready after build_variant"
    return out


def stage0_dry_run(survey_yaml: Path) -> tuple[dict[str, str], dict, str]:
    """Run the stage 0 dry run on an empty ledger; return (lines by run id, counts with a value, the text)."""
    plan = cp.load_plan(make_plan(survey_yaml.parent))
    c = cp.Campaign(survey_yaml, plan, parallel=2, create=False)
    assert not c.ledger.rows, f"premise: the ledger has rows: {list(c.ledger.rows)}"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = c.dry_run([0], plan.sites)
    text = buf.getvalue()
    rows = lines_by_run(text)
    assert sorted(rows) == STAGE0, f"the stage 0 lines: {sorted(rows)}\n{text}"
    return rows, {k: v for k, v in out["counts"][0].items() if v}, text


def test_stage0_dry_run() -> None:
    survey_yaml, survey, data = new_survey("survey")
    a_variant = build_current(survey, "A", data)
    b_variant = variant_path(survey, "B")
    _write_raw_archive(b_variant, "B", "SYN", data, 1000.0, T0,
                       comment="filters hash 00000000; ingest filters (in order): notch")
    assert not variant_ready(survey, "B"), "premise: B's stale file reads ready"

    rows, got, _text = stage0_dry_run(survey_yaml)
    assert rows["s0_A"].endswith(f"ready: {a_variant.name} on disk and current"), \
        f"A's current variant is not listed ready: {rows['s0_A']!r}"
    for site in "BCDE":
        assert rows[f"s0_{site}"].endswith(": to build"), f"{site} is not listed to build: {rows[f's0_{site}']!r}"
    assert got == {"variant": 4}, f"stage 0 counts {got}, expected 4 variants (A reused)"
    print(f"  {rows['s0_A']}")
    print(f"  {rows['s0_B']}   (stale file {b_variant.name})")
    print(f"  {rows['s0_C']}   (no file)")
    print(f"  stage 0 still to run: {got}")


def test_raw_archive_missing() -> None:
    survey_yaml, survey, data = new_survey("raw_missing")
    c_variant = build_current(survey, "C", data)
    raw = default_archive_path(survey, "C")
    raw.unlink()
    assert c_variant.exists() and variant_ready(survey, "C") and not raw.exists(), \
        "premise: C's variant is not current on disk without its raw archive"

    rows, got, _text = stage0_dry_run(survey_yaml)
    line = rows["s0_C"]
    assert "ready" not in line and "raw archive missing" in line and str(raw) in line, \
        f"C (variant current, raw archive deleted) is not listed with its raw archive missing: {line!r}"
    for site in "ABDE":
        assert rows[f"s0_{site}"].endswith(": to build"), f"{site} is not listed to build: {rows[f's0_{site}']!r}"
    assert got == {"variant": 5}, f"stage 0 counts {got}, expected 5 variants (the run stops on C, so it counts)"
    print(f"  {line}")
    print(f"  stage 0 still to run: {got}")


def test_unreadable_variant() -> None:
    survey_yaml, survey, _data = new_survey("unreadable")
    variant_path(survey, "D").write_bytes(b"")
    variant_path(survey, "E").write_bytes(b"not an HDF5 file, a copy cut short or written by hand\n" + b"x" * 9)
    first = {}
    for site in "DE":
        try:
            variant_ready(survey, site)
        except OSError as exc:
            first[site] = next(s.strip() for s in str(exc).splitlines() if s.strip())
        else:
            raise AssertionError(f"premise: variant_ready on {site}'s unreadable file raised no OSError")

    try:
        rows, got, _text = stage0_dry_run(survey_yaml)
    except OSError as exc:
        raise AssertionError(f"the dry run raised {type(exc).__name__}: {str(exc).splitlines()[0]}") from exc
    for site in "DE":
        line = rows[f"s0_{site}"]
        want = f"unreadable: {variant_path(survey, site).name} ({first[site]})"
        assert want in line, f"{site}'s unreadable file is not listed as {want!r}: {line!r}"
    for site in "ABC":
        assert rows[f"s0_{site}"].endswith(": to build"), f"{site} is not listed to build: {rows[f's0_{site}']!r}"
    assert got == {"variant": 5}, f"stage 0 counts {got}, expected 5 variants (the run stops on D and E)"
    print(f"  {rows['s0_D']}")
    print(f"  {rows['s0_E']}")
    print(f"  stage 0 still to run: {got}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("The survey and plan")[0].strip())
    print()
    failed = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # an error out of the dry run is a failure of this test, not a crash of the file
            failed.append(test.__name__)
            first = (str(exc).splitlines() or [""])[0]
            said = exc if isinstance(exc, AssertionError) else f"{type(exc).__name__}: {first}"
            print(f"  FAIL  {test.__name__}: {said}")
        else:
            print(f"  ok    {test.__name__}")
    print(f"\n{'FAIL' if failed else 'PASS'}  campaign_variant_dry_run_unit ({len(tests) - len(failed)} of {len(tests)} "
          f"passed)")
    sys.exit(1 if failed else 0)
