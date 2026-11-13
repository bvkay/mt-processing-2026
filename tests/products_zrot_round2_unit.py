# -*- coding: utf-8 -*-
"""
Unit test for the products.zrot leftovers (workbench 179)

(a) The EMTF XML's orientation under ``products: {zrot: zero}``. In the EMTF
    XML schema (and mt_metadata's Orientation model: "Angle to rotate the data
    to align with geographic north. If this number is 0 then it is assumed the
    data are aligned with geographic north") Site Orientation
    angle_to_geographic_north is the azimuth of the TF's x-axis from
    geographic north, and each channel's orientation the azimuth it was
    measured along; the XML has no coordinate-system field beside it. The
    EDI's ZROT 0 is read with its HEAD COORDINATE_SYSTEM=geomagnetic and
    DECLINATION; the XML can say the same thing only through the
    angle itself, so the consistent setting is the declination D (x-axis at
    magnetic north, D east of geographic north), with the Declination
    element D and the Notes naming the EDI's ZROT 0. Writing 0 there would
    declare the data geographic. The test reads the written XML back.
(b) scripts/merge_best.py and scripts/deliver_as_laid.py set the survey's
    rule (`products.zrot_rule_of`), as scripts/process_rr.py does: the same TF
    written by process_rr's path (set_zrot_rule + write_products), re-written
    by deliver_as_laid.py under a survey.yaml, and merged by merge_best.py
    with --survey, reads back the same ZROT and DECLINATION under each
    setting. (scripts/process_intersite.py writes no EDI or XML, so there is
    nothing to set there.)
(c) the sidecar keeps the full instrument strings: `instrument_info_lines(...,
    cut=False)` gives the lines uncut while the INFO lines stay under
    INFO_MAX.

Usage:
    python tests/products_zrot_round2_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(a) under zero the XML read back (raw text and mt_metadata's reader) does
    not give angle_to_geographic_north = 7.21, Hx orientation 7.21, Hy 97.21,
    Declination 7.21, while the EDI beside it holds ZROT 0 and DECLINATION
    7.21; or under the default the XML angle is not 7.21 and the EDI's ZROT
    not 7.21;
(b) for each rule (zero, declination) the ZROT (first period) and
    DECLINATION of process_rr's write, deliver_as_laid.py's output and
    merge_best.py's output (with --survey) are not all equal to (0, 7.21)
    under zero and (7.21, 7.21) under the default; or merge_best.py without
    --survey does not keep its first source's rule;
(c) an instruments.csv row with a 300-character logger_doi_source does not
    give a cut INFO line under INFO_MAX ending "..." and an uncut line
    holding the whole cell text, or the uncut magnetometer line differs from
    the cut one when the cell is short.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench import products as P  # noqa: E402
from products_zrot_unit import FakeSurvey, block, small_tf  # noqa: E402

fails: list[str] = []
D = 7.21


def check(ok: bool, msg: str) -> None:
    """Record and print one check."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def head(text: str, key: str) -> str:
    m = re.search(rf"^\s*{re.escape(key)}=(\S+)", text, flags=re.M)
    return m.group(1).strip('"') if m else ""


def zrot_decl(edi: Path) -> tuple[float, float]:
    text = edi.read_text(encoding="latin-1")
    z = block(text, "ZROT")
    return (float(z[0]) if z.size else float("nan")), float(head(text, "DECLINATION") or "nan")


def written(tmp: Path, rule: str) -> Path:
    """The small TF written as process_rr writes it (set_zrot_rule, write_products)."""
    tf = small_tf()
    P.set_zrot_rule(tf, rule)
    paths = P.write_products(tf, tmp / f"pr_{rule}.edi")
    return paths["edi"]


def survey_yaml(tmp: Path, rule: str) -> Path:
    cfg = {"name": "Z2", "instrument": "edl", "sample_rate": 10, "data_root": str(tmp / "raw"),
           "workspace": str(tmp / "work"), "processing": {"min_period": 4.0, "max_period": 10000.0},
           "sites": {"FR05L": {"latitude": -31.14, "longitude": 138.69, "start": "2013-09-22T00:00:00Z",
                               "end": "2013-10-12T00:00:00Z"}}}
    if rule == "zero":
        cfg["products"] = {"zrot": "zero"}
    path = tmp / f"survey_{rule}.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_xml(tmp: Path) -> None:
    from mt_metadata.transfer_functions.core import TF
    (tmp / "xml").mkdir(exist_ok=True)
    for rule, want_z in (("zero", 0.0), ("declination", D)):
        edi = written(tmp / "xml", rule)
        xml = edi.with_suffix(".xml")
        text = xml.read_text(encoding="utf-8")
        ang = re.search(r'<Orientation angle_to_geographic_north="([-0-9.]+)"', text)
        hx = re.search(r'<Magnetic name="Hx" orientation="([-0-9.]+)"', text)
        hy = re.search(r'<Magnetic name="Hy" orientation="([-0-9.]+)"', text)
        dec = re.search(r"<Declination[^>]*>([-0-9.]+)<", text)
        got = tuple(float(m.group(1)) if m else float("nan") for m in (ang, hx, hy, dec))
        back = TF()
        back.read(xml)
        a_back = back.station_metadata.orientation.angle_to_geographic_north
        z, decl = zrot_decl(edi)
        # small_tf() has no channel metadata, so its hy's measurement azimuth is mt_metadata's default 0 and the
        # XML writes Hy at D + 0 (7.21 under both rules; a property of the fixture, not of the rule). Hy reads
        # D + the TF's own hy azimuth.
        az_hy = 0.0
        for run in small_tf().station_metadata.runs:
            for ch in run.channels:
                if ch.component == "hy":
                    az_hy = float(ch.measurement_azimuth or 0.0)
        ok = np.allclose(got, (D, D, az_hy + D, D), atol=0.006) and abs(float(a_back) - D) < 0.006 \
            and z == want_z and abs(decl - D) < 1e-9
        check(ok, f"(a) {rule}: XML angle/Hx/Hy/Declination {got}, read back angle {a_back}; EDI ZROT {z}, "
                  f"DECLINATION {decl}")


def run(script: str, *args) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(REPO / "scripts" / script), *map(str, args)], capture_output=True,
                       text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def test_writers(tmp: Path) -> None:
    for rule, want in (("zero", (0.0, D)), ("declination", (D, D))):
        w = tmp / f"w_{rule}"
        w.mkdir()
        src = written(w, rule)
        sy = survey_yaml(w, rule)
        got = {"process_rr path": zrot_decl(src)}
        # deliver_as_laid.py: from a source written under the OTHER rule, so the survey must decide
        (w / "o").mkdir()
        other = written(w / "o", "declination" if rule == "zero" else "zero")
        out = w / "delivered.edi"
        code, text = run("deliver_as_laid.py", sy, other, out, "--site", "FR05L")
        got["deliver_as_laid"] = zrot_decl(out) if out.exists() else (code, text.splitlines()[-1][:120])
        recipe = w / "recipe.yaml"
        recipe.write_text(yaml.safe_dump({"FR05L": {"xy": [{"edi": str(other), "pmin": 1.0, "pmax": 1e4}],
                                                    "yx": [{"edi": str(other), "pmin": 1.0, "pmax": 1e4}]}}),
                          encoding="utf-8")
        merged = w / "merged.edi"
        code, text = run("merge_best.py", merged, "--recipe", recipe, "--site", "FR05L", "--survey", sy)
        got["merge_best --survey"] = zrot_decl(merged) if code == 0 and merged.exists() else (code, text.splitlines()[-1][:160])
        ok = all(isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], float) and np.allclose(v, want)
                 for v in got.values())
        check(ok, f"(b) {rule}: want ZROT, DECLINATION {want}: {got}")
        # merge_best without --survey keeps the first source's rule
        kept = w / "merged_kept.edi"
        code, text = run("merge_best.py", kept, "--recipe", recipe, "--site", "FR05L")
        want_kept = (0.0, D) if rule == "declination" else (D, D)    # `other` was written under the other rule
        k = zrot_decl(kept) if code == 0 and kept.exists() else (code, text.splitlines()[-1][:160])
        check(isinstance(k[0], float) and np.allclose(k, want_kept),
              f"(b) merge_best without --survey keeps its source's rule: {k} want {want_kept}")


def test_instrument_full(tmp: Path) -> None:
    folder = tmp / "inst"
    folder.mkdir()
    source = "INFERRED from the workbook recorder number " + "x" * 260
    (folder / "instruments.csv").write_text(
        "site,logger_model,logger_serial,logger_doi,logger_doi_source,magnetometer_model,magnetometer_serial\n"
        f"S1,Earth Data PR6-24,60965,10.82388/8hjqyq4t,{source},Bartington Mag03MS70,1183\n", encoding="utf-8")
    survey = FakeSurvey({}, folder=folder)
    try:
        cut = P.instrument_info_lines(survey, "S1")
        full = P.instrument_info_lines(survey, "S1", cut=False)
    except TypeError as exc:
        check(False, f"(c) instrument_info_lines(cut=False): {exc}")
        return
    ok = (len(cut) == 2 and len(full) == 2 and cut[0].endswith("...") and all(len(P.INFO_PREFIX + x) < P.INFO_MAX
                                                                              for x in cut)
          and source in full[0] and full[1] == cut[1])
    check(ok, f"(c) cut {[len(x) for x in cut]} chars, full {[len(x) for x in full]} chars; whole source in full "
              f"{source in (full[0] if full else '')}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    test_xml(tmp)
    test_writers(tmp)
    test_instrument_full(tmp)
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
