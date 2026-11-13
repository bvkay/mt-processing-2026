# -*- coding: utf-8 -*-
"""
Unit test: Orange Box files named LP<n>-NNN.BIN are Orange Box files

South Australia AusLAMP (2015-2018) has 20 Orange Box sites whose loggers
(MagLog 4.1 on a Persistor CF2) wrote their hourly files as ``LP<n>-NNN.BIN``
and their report as ``LP<n>-RPT.TXT``; the 8 others (MagLog 3.50, CF1) wrote
``HFM<n>-NNN.BIN``. The byte layout is the same (40-byte header, 21-byte
records, 26-byte trailer; SA163's LP14-000.BIN and SA165's HFM4-000.BIN are
both 756,066 bytes with the header " 00008CA0 ...  7A1") and the report
opens with the same "High Frequency Magnetometer Number <n>" line, so the
prefix is a firmware label, not a format. mt-io's reader never looks at the
name; only mt-workbench's name rules did (docs/workbench_issues.md 162).

**This test fails if**
  - `mt_workbench.orangebox.is_orange_name` / `ORANGE_NAME` do not accept
    ``LP<n>-NNN.BIN`` (and ``.BIN.OLD``) with the box number as group 1, or
    accept a name that is not an Orange Box data file;
  - `REPORT_NAME` does not match ``LP<n>-RPT.TXT``, or `report_box` does not
    return "hfm<n>" from such a report;
  - `mt_workbench.instruments.detect_instrument` does not return "orangebox"
    for a folder whose only record is a synthetic LP file with a parsing
    header, including when the survey prefers "edl" (the SA case);
  - `header_facts` cannot take the box number from an LP file name;
  - `mt_workbench.survey.Survey.site_dirs` of an EDL survey leaves such a
    folder out (what scripts/new_survey.py uses).

Usage:
    python tests/orangebox_lp_name_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orangebox_unit import synthetic_counts, write_orange_bin  # noqa: E402  (the synthetic file writer)

from mt_workbench.instruments import detect_instrument, header_facts, record_files  # noqa: E402
from mt_workbench.orangebox import ORANGE_NAME, REPORT_NAME, is_orange_name, report_box  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

REPORT_TEXT = ("High Frequency Magnetometer Number 14 - Flinders & Adelaide University 1999 - 2010\r\n\r\n"
               "  * MagLog Version 4.1 for CF2 15/08/2010: Sep  5 2011 compiled on 11:49:34 \r\n")


def test_names() -> None:
    for name in ("LP14-000.BIN", "LP14-000.BIN.OLD", "lp6-123.bin", "HFM4-000.BIN", "HFM0-000.BIN.OLD"):
        assert is_orange_name(Path(name)), f"{name} should be an Orange Box data file"
    for name in ("._LP14-000.BIN", "LP-000.BIN", "LPX14-000.BIN", "box14.dat", "LP14-RPT.TXT", "logcf1.pxe",
                 "SA163_151014230000.BX", "HFM4-RPT.TXT"):
        assert not is_orange_name(Path(name)), f"{name} should not be an Orange Box data file"
    m = ORANGE_NAME.match("LP14-007.BIN")
    assert m and m.group(1) == "14" and m.group(2) == "007", m
    m = ORANGE_NAME.match("HFM4-007.BIN")
    assert m and m.group(1) == "4" and m.group(2) == "007", m
    r = REPORT_NAME.match("LP14-RPT.TXT")
    assert r and r.group(1) == "14", r
    r = REPORT_NAME.match("HFM4-RPT.TXT")
    assert r and r.group(1) == "4", r
    assert REPORT_NAME.match("LP14-000.BIN") is None


def test_folder(tmp: Path) -> None:
    root = tmp / "root"
    site = root / "SA163" / "raw"
    site.mkdir(parents=True)
    start = pd.Timestamp("2015-04-28 10:48:01")
    write_orange_bin(site / "LP14-000.BIN", synthetic_counts(600), start)
    (site / "LP14-RPT.TXT").write_bytes(REPORT_TEXT.encode("ascii"))
    (site / "box14.dat").write_bytes(b"12355060  02621539\r\n")
    (site / "Convert.log").write_bytes(b"Output record every 1 seconds\r\n")

    assert detect_instrument(root / "SA163") == "orangebox", "LP folder not detected (default prefer)"
    assert detect_instrument(root / "SA163", prefer="edl") == "orangebox", "LP folder not detected (prefer edl)"
    files = record_files(root / "SA163", "orangebox")
    assert [f.name for f in files] == ["LP14-000.BIN"], files
    assert report_box(site, "14") == "hfm14", report_box(site, "14")
    facts = header_facts(root / "SA163", "orangebox", files)
    assert facts["serial"] == "hfm14", facts
    assert facts["header_rate"] is not None and abs(facts["header_rate"] - 10.00064) < 1e-3, facts

    survey = Survey({"name": "t", "instrument": "edl", "data_root": str(root)}, tmp)
    found = survey.site_dirs()
    assert "SA163" in found, f"site_dirs of an EDL survey left the LP folder out: {sorted(found)}"
    assert survey.instrument_of("SA163") == "orangebox", survey.instrument_of("SA163")


if __name__ == "__main__":
    test_names()
    with tempfile.TemporaryDirectory() as d:
        test_folder(Path(d))
    print("orangebox_lp_name_unit: all passed")
