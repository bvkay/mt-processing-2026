# -*- coding: utf-8 -*-
"""
Unit test for scripts/declination.py

Checks the IGRF fill against the NOAA calculator, the sign, the decimal
year of a site's record, and the line-preserving write into a copy of the
Morocco survey.yaml. Runs without Qt or an archive; needs ppigrf.

Usage:
    python tests/declination_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the fill at 31.87 N 7.93 W, 567 m, 2023.53 is not
-1.07 deg within 0.05 or at 33.0 N 3.4 W, 0 m, 2023.53 not +0.20 within 0.05
(the NOAA calculator, DGRF2020), or the same values with the sign flipped
match (the sign control); the script's own --self-test does not exit 0; the
midpoint of a record from 2023-07-19T10:22:47Z to 2023-07-23T10:22:51Z is
not 2023.55 to 2 decimals, or a site without a start is not skipped;
the model is not named as ppigrf's coefficient file (IGRF-14 in ppigrf
2.1.0).

And the write, on copies of surveys/MT_Morocco_Atlas_Mountains/survey.yaml:
with every declination line removed, --write does not give back a file
identical to the filled file in the repository (every other line kept, the three keys
after each entry's last line); the diff against the stripped copy is not
exactly three added lines per site and no removed line; the same with CRLF line
endings does not keep CRLF on every line; a second --write is not a no-op;
a site whose keys hold other values does not have them replaced on their
own lines (line count unchanged); the guard `check_unchanged` does not
report a changed key of another site (control: a mutation that must trip);
or --check B03=-1.07 does not exit 0 and --check B03=+1.07 (the flipped
sign, the control) does not exit 1.
"""

from __future__ import annotations

import difflib
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import declination  # noqa: E402

MOROCCO = REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "survey.yaml"
KEY_LINE = re.compile(r"^    declination(_model|_epoch)?: ")


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def stripped(text: str) -> str:
    return "".join(line for line in text.splitlines(keepends=True) if not KEY_LINE.match(line))


def test_noaa_controls_and_sign() -> None:
    for lat, lon, elev, epoch, want in declination.NOAA_CONTROLS:
        got = declination.igrf_declination(lat, lon, elev, epoch)
        assert abs(got - want) <= 0.05, (lat, lon, got, want)
        assert abs(got - (-want)) > 0.05, f"sign control matched at {lat} {lon}: {got} vs {-want}"
        print(f"  {lat:.2f} {lon:+.2f} {elev:.0f} m {epoch}: {got:+.3f} deg, NOAA {want:+.2f}; flipped {-want:+.2f} "
              f"fails")
    assert declination.self_test() == 0
    assert declination.model_name() == "IGRF-14", declination.model_name()


def test_epoch_and_skip() -> None:
    epoch = declination.site_epoch({"start": "2023-07-19T10:22:47Z", "end": "2023-07-23T10:22:51Z"})
    assert round(epoch, 2) == 2023.55, epoch
    assert round(declination.decimal_year("2023-07-13T00:00:00Z"), 2) == 2023.53
    assert declination.fill({"latitude": 31.9, "longitude": -7.9}) is None
    got = declination.fill({"latitude": 32.023322, "longitude": -7.946535, "elevation": 447.3,
                            "start": "2023-07-19T10:22:47Z", "end": "2023-07-23T10:22:51Z"})
    assert got["declination"] == -1.07 and got["declination_epoch"] == 2023.55, got
    print(f"  B03's record midpoint {epoch:.4f}; fill {got['declination']} {got['declination_model']} "
          f"{got['declination_epoch']}; no start -> skipped")


def test_line_preserving_write() -> None:
    committed = read(MOROCCO)
    assert committed.count("\n    declination_model: ") > 100, "the Morocco survey.yaml carries no fill"
    base = stripped(committed)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "survey.yaml"
        write(copy, base)
        assert declination.main([str(copy), "--write"]) == 0
        new = read(copy)
        assert new == committed, "the rewrite of the stripped copy is not the filled file"
        diff = [d for d in difflib.unified_diff(base.splitlines(), new.splitlines(), lineterm="", n=0)
                if not d.startswith(("---", "+++", "@@"))]
        added = [d for d in diff if d.startswith("+")]
        n_sites = len(declination.entry_spans(base.splitlines(keepends=True), *declination.sites_block(
            base.splitlines(keepends=True))))
        assert not [d for d in diff if d.startswith("-")], "a line was removed"
        assert len(added) == 3 * n_sites and all(KEY_LINE.match(d[1:]) for d in added), len(added)
        assert declination.main([str(copy), "--write"]) == 0 and read(copy) == new, "a second --write changed it"

        crlf = Path(tmp) / "crlf.yaml"
        write(crlf, base.replace("\n", "\r\n"))
        assert declination.main([str(crlf), "--write"]) == 0
        text = read(crlf)
        assert text.count("\n") == text.count("\r\n") and text == committed.replace("\n", "\r\n"), "CRLF lost"

        other = new.replace("    declination: -1.07\n    declination_model: IGRF-14\n    declination_epoch: 2023.55",
                            "    declination: 9.99\n    declination_model: hand\n    declination_epoch: 1999.00", 1)
        assert other != new
        write(copy, other)
        assert declination.main([str(copy), "--write"]) == 0
        assert read(copy) == new and len(other.splitlines()) == len(new.splitlines()), "keys not replaced in place"

        values = {"B03": {"declination": -1.07, "declination_model": "IGRF-14", "declination_epoch": 2023.55}}
        assert declination.check_unchanged(new, new, values) == []
        mutated = new.replace("    dipole_length_ex: 53.0\n", "    dipole_length_ex: 54.0\n", 1)
        assert mutated != new and declination.check_unchanged(new, mutated, values), "control: the guard missed it"

        assert declination.main([str(copy), "--check", "B03=-1.07"]) == 0
        assert declination.main([str(copy), "--check", "B03=1.07"]) == 1, "control: the flipped sign passed"
    print(f"  {n_sites} sites: stripped copy rewritten identical to the filled file, {len(added)} lines added, "
          f"none removed; CRLF kept; second write a no-op; hand values replaced in place; guard trips on a "
          f"changed key; --check B03=-1.07 passes, B03=+1.07 fails")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  declination_unit ({len(tests)} tests)")
