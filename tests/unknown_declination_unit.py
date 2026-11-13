# -*- coding: utf-8 -*-
"""
Unit test for an unknown declination in the products (mt_workbench.products)

A transfer function is built two ways, as an aurora run returns one: with
the archive's unset declination (mt_metadata's default, 0.0 and "IGRF" with
no epoch: neither survey.yaml nor the archive holds one) and with a declared one (-0.36, IGRF-14, 2023.73, C18's).
For each, `frame_record` gives the sidecar's frame keys and `write_xml`
writes the EMTF XML, whose raw text is searched for the Site Location
Declination element and which mt_metadata reads back. `write_edi` writes
the EDI, whose HEAD is searched for a DECLINATION line, so the three
products are compared on the same TF.

Usage:
    python tests/unknown_declination_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the unknown declination's sidecar record gives a
declination, model, epoch or source other than null (case 8c wrote 0.0,
"IGRF" and "archive"); its XML carries a Declination element (case 8c wrote
`<Declination epoch="1995">0.000</Declination>`) or does not read back with
mt_metadata; its EDI writes a DECLINATION line; or if the declared control
does not keep -0.36, IGRF-14, 2023.73 and "survey.yaml" in the record,
`<Declination epoch="2023">-0.360</Declination>` in the XML and a
DECLINATION line in the EDI.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
from mt_metadata.timeseries import Electric, Magnetic, Run  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mt_workbench.products import frame_record, match_coordinate_system, write_edi, write_xml  # noqa: E402
from mt_workbench.products import set_declination  # noqa: E402

DECLARED = (-0.36, "IGRF-14", 2023.73)  # C18's survey.yaml entry
DECLINATION = re.compile(r"<Declination\b[^>]*>[^<]*</Declination>")


def make_tf(declared: bool) -> TF:
    """Build a TF shaped as aurora returns one: geomagnetic frame, Z with errors and covariances.

    Without `declared` the declination is the archive's unset one (0.0, no
    epoch); with it, C18's declared value, model and epoch are set.
    """
    period = np.geomspace(0.01, 100.0, 6)
    tf = TF()
    tf.station = "C18"
    tf.survey_metadata.id = "test"
    tf.station_metadata.orientation.reference_frame = "geomagnetic"
    run = Run(id="sr1000_0001", sample_rate=1000.0)
    for comp in ("ex", "ey", "hx", "hy"):
        ch = Electric(component=comp) if comp.startswith("e") else Magnetic(component=comp)
        ch.measurement_azimuth = 90.0 if comp in ("ey", "hy") else 0.0
        run.add_channel(ch)
    tf.station_metadata.add_run(run)
    tf.period = period
    z = np.zeros((period.size, 2, 2), dtype=complex)
    z[:, 0, 1], z[:, 1, 0] = 1.0 + 1.0j, -1.0 - 1.0j
    tf.impedance = z
    tf.impedance_error = np.full((period.size, 2, 2), 0.1)
    tf.residual_covariance = np.tile(np.eye(3, dtype=complex) * 0.01, (period.size, 1, 1))
    tf.inverse_signal_power = np.tile(np.eye(2, dtype=complex) * 2.0, (period.size, 1, 1))
    if declared:
        set_declination(tf.station_metadata, *DECLARED)
    match_coordinate_system(tf)
    return tf


def products(declared: bool, tmp: Path) -> tuple[dict, str, str, TF]:
    """Return the sidecar frame record, the XML text, the EDI text and the XML read back."""
    tf = make_tf(declared)
    source = "survey.yaml" if declared else "archive"  # what process_rr.py passes
    record = frame_record(tf, source)
    xml = write_xml(tf, tmp / f"{'declared' if declared else 'unknown'}.xml")
    edi = write_edi(tf, tmp / f"{'declared' if declared else 'unknown'}.edi")
    back = TF(xml)
    back.read()
    return record, xml.read_text(encoding="utf-8"), edi.read_text(encoding="latin-1"), back


def test_unknown_declination_is_stated_as_none() -> None:
    """Check the unknown declination gives null sidecar keys, no XML element and no EDI line."""
    with tempfile.TemporaryDirectory() as tmp:
        record, xml, edi, back = products(False, Path(tmp))
    keys = {k: record[k] for k in ("declination", "declination_model", "declination_epoch", "declination_source")}
    print(f"  unknown: sidecar {keys}; XML Declination elements {DECLINATION.findall(xml)}; "
          f"EDI DECLINATION lines {re.findall(r'DECLINATION=.*', edi)}")
    assert all(v is None for v in keys.values()), f"sidecar states a declination: {keys}"
    assert not DECLINATION.findall(xml), f"XML states a declination: {DECLINATION.findall(xml)}"
    assert "<Location" in xml and "<Latitude>" in xml, "the XML lost its Location element"
    assert not re.search(r"^\s*DECLINATION=", edi, re.M), "the EDI states a declination"
    d = back.station_metadata.location.declination
    assert back.impedance.shape[0] == 6, back.impedance.shape
    print(f"  unknown: XML read back by mt_metadata: 6 periods, declination {d.value} epoch {d.epoch}")


def test_declared_control_keeps_its_value() -> None:
    """Check the declared declination is kept in all three products (the control)."""
    with tempfile.TemporaryDirectory() as tmp:
        record, xml, edi, back = products(True, Path(tmp))
    keys = {k: record[k] for k in ("declination", "declination_model", "declination_epoch", "declination_source")}
    print(f"  declared: sidecar {keys}; XML {DECLINATION.findall(xml)}; "
          f"EDI {re.findall(r'DECLINATION=.*', edi)}")
    assert keys == {"declination": -0.36, "declination_model": "IGRF-14", "declination_epoch": "2023.73",
                    "declination_source": "survey.yaml"}, keys
    assert DECLINATION.findall(xml) == ['<Declination epoch="2023">-0.360</Declination>'], DECLINATION.findall(xml)
    assert re.search(r"^\s*DECLINATION=-0\.36", edi, re.M), "the EDI lost its declination"
    assert abs(float(back.station_metadata.location.declination.value) + 0.36) < 1e-9


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  unknown_declination_unit ({len(tests) - failed} of {len(tests)} tests passed)")
    sys.exit(1 if failed else 0)
