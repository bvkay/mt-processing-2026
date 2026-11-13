# -*- coding: utf-8 -*-
"""
Unit test for EDI and EMTF XML products of a station whose id holds a hyphen (mt_workbench.products)

mt_metadata 1.0.10 admits a hyphen in a Station id (``^[a-zA-Z0-9_-]*$``)
and not in a Run id (``^[a-zA-Z0-9_]*$``), and its EDI code and its EMTF
XML reader build a placeholder run "<station>a" (upstream issue 86):
process_rr.py on KD-Q5 exited 1 at the EDI writer after aurora had
finished, an XML of KD-Q5 did not read back, and an EDI read back gave
the station KD_Q5 (the EDI header reader's ``validate_station_name``).
`products.write_edi`, `products.write_xml` and `products.read_tf` work
inside `products.hyphenated_station_ids`, which makes the placeholder run
id admissible and keeps the DATAID's hyphen on reading.

TFs are built as tests/unknown_declination_unit.py builds one, with the
station id set. The Kalkaroo products of KD-Q5 against KD-RR_210507,
tag decl-check-Z (`P1_STEM`), are read when present, read only.

Usage:
    python tests/hyphen_station_export_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - S1: a Station id admits a character other than the hyphen that a Run
    id refuses (dot, space, plus, slash), or refuses the hyphen; the
    hyphen would then not be the only case to handle;
  - H1: `write_edi` or `write_xml` raises on a TF whose station id is
    "KD-Q5" or "KD-RR_210507", or the EDI's DATAID line or the XML's Site
    Id is not exactly the station id;
  - H2: `read_tf` of those files raises, gives another station id, or
    gives an impedance other than the TF's;
  - C1 (the control that the cases exercise the defect): mt_metadata's
    own EDI writer on the `edi_copy` of the "KD-Q5" TF does not raise the
    Run id ValidationError on "KD-Q5a", its own read of the XML does not
    raise it, or its own read of the EDI does not give "KD_Q5";
  - C4: for the station "A01" the files written with and without the
    context differ (other than their date lines), or mt_metadata's own read
    gives another station id or impedance than `read_tf`;
  - R: the names patched inside the context are not mt_metadata's own
    after it, including after an exception inside it;
  - P (when present): `read_tf` of the P1 wrapper products of KD-Q5 does
    not give "KD-Q5" for both, or their impedances differ by more than
    1e-6 relative.

The mutation, which must trip H1: `products.hyphenated_station_ids`
replaced by a context that changes nothing.
"""

from __future__ import annotations

import contextlib
import glob
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.products as products  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from unknown_declination_unit import make_tf as declination_tf  # noqa: E402

SCRATCH = scratch_dir("hyphen_station_export_unit")
HYPHENATED = ("KD-Q5", "KD-RR_210507")
PLAIN = "A01"
P1_STEM = "D:/MT_DATA/MT_Kalkaroo_Workspace/tf/KD-Q5_rr-KD-RR_210507_*_decl-check-Z"
RUN_ID_ERROR = "String should match pattern '^[a-zA-Z0-9_]*$'"
_DATE_LINE = re.compile(r"date|time", re.I)


def make_tf(station: str):
    """Return a TF shaped as aurora returns one, with station id `station`."""
    tf = declination_tf(False)
    tf.station = station
    assert tf.station_metadata.id == station, tf.station_metadata.id
    return tf


def dataid(edi: Path) -> str | None:
    """Return the value of the EDI's DATAID line, None when it has none."""
    found = re.search(r"^\s*DATAID=(.*?)\s*$", edi.read_text(encoding="latin-1"), re.M)
    return found.group(1).strip('"') if found else None


def site_id(xml: Path) -> str | None:
    """Return the text of the XML's Site Id element."""
    node = ET.parse(xml).getroot().find("Site/Id")
    return None if node is None else node.text


def same_z(a, b, rtol: float = 1e-6) -> bool:
    """Whether two TFs hold the same periods and impedance.

    mt_metadata's XML writer writes a zero as the EMPTY fill 1e32, so an
    element that is 0 or 1e32 in either TF is left out of the comparison
    (the synthetic TF's Zxx and Zyy); at least the two off-diagonal
    elements at every period are compared.
    """
    pa, pb = np.asarray(a.period), np.asarray(b.period)
    if pa.size != pb.size:
        return False
    oa, ob = np.argsort(pa), np.argsort(pb)
    za, zb = np.asarray(a.impedance.data)[oa], np.asarray(b.impedance.data)[ob]
    keep = (za != 0) & (zb != 0) & (np.abs(za) < 1e31) & (np.abs(zb) < 1e31)
    return (bool(keep[:, 0, 1].all() and keep[:, 1, 0].all()) and np.allclose(pa[oa], pb[ob], rtol=rtol)
            and np.allclose(za[keep], zb[keep], rtol=rtol, equal_nan=True))


def library_read(path: Path):
    """Read a file with mt_metadata's own TF.read, outside the context."""
    from mt_metadata.transfer_functions.core import TF

    tf = TF(fn=str(path))
    tf.read()
    return tf


def check_patterns() -> list[str]:
    """S1: which characters a Station id admits that a Run id refuses."""
    from mt_metadata.timeseries import Run, Station

    bad = []
    for char in "-. +/":
        admits = {}
        for cls in (Station, Run):
            try:
                cls(id=f"KD{char}Q5")
                admits[cls.__name__] = True
            except Exception:
                admits[cls.__name__] = False
        gap = admits["Station"] and not admits["Run"]
        if gap != (char == "-"):
            bad.append(f"S1: {char!r}: Station admits {admits['Station']}, Run admits {admits['Run']}")
    return bad


def check_export(station: str, tag: str = "") -> list[str]:
    """H1 and H2 for one station id."""
    tf = make_tf(station)
    edi, xml = SCRATCH / f"{station}{tag}.edi", SCRATCH / f"{station}{tag}.xml"
    for path in (edi, xml):
        path.unlink(missing_ok=True)
    try:
        products.write_edi(tf, edi)
        products.write_xml(tf, xml)
    except Exception as exc:
        return [f"H1 {station}: write raises {type(exc).__name__}: {str(exc).splitlines()[0]}"]
    bad = []
    if dataid(edi) != station:
        bad.append(f"H1 {station}: EDI DATAID {dataid(edi)!r}")
    if site_id(xml) != station:
        bad.append(f"H1 {station}: XML Site Id {site_id(xml)!r}")
    for path in (edi, xml):
        try:
            back = products.read_tf(path)
        except Exception as exc:
            bad.append(f"H2 {path.name}: read_tf raises {type(exc).__name__}: {str(exc).splitlines()[0]}")
            continue
        if back.station_metadata.id != station:
            bad.append(f"H2 {path.name}: station id {back.station_metadata.id!r}")
        if not same_z(back, tf):
            bad.append(f"H2 {path.name}: impedance differs from the TF's")
    return bad


def check_control() -> tuple[list[str], str]:
    """C1: mt_metadata's own writer and readers on KD-Q5; (failures, info)."""
    bad, info = [], []
    try:
        products.edi_copy(make_tf("KD-Q5")).write(fn=SCRATCH / "KD-Q5_library.edi", file_type="edi")
        bad.append("C1: mt_metadata's own EDI writer accepts KD-Q5: the check cannot fail")
    except Exception as exc:
        if RUN_ID_ERROR not in str(exc) or "KD-Q5a" not in str(exc):
            bad.append(f"C1: mt_metadata's own EDI writer raises another error: {str(exc).splitlines()[0]}")
        info.append("EDI write: Run id ValidationError on 'KD-Q5a'")
    try:
        library_read(SCRATCH / "KD-Q5.xml")
        bad.append("C1: mt_metadata's own read of the KD-Q5 XML works: the check cannot fail")
    except Exception as exc:
        if RUN_ID_ERROR not in str(exc):
            bad.append(f"C1: mt_metadata's own XML read raises another error: {str(exc).splitlines()[0]}")
        info.append("XML read: Run id ValidationError")
    got = library_read(SCRATCH / "KD-Q5.edi").station_metadata.id
    if got != "KD_Q5":
        bad.append(f"C1: mt_metadata's own read of the KD-Q5 EDI gives {got!r}, not the renamed 'KD_Q5'")
    info.append(f"EDI read: station {got!r}")
    return bad, "; ".join(info)


def check_plain() -> list[str]:
    """C4: A01 written by `write_edi` / `write_xml` the same with the context and with it made a no-op."""
    bad = []
    tf = make_tf(PLAIN)
    kept = products.hyphenated_station_ids
    products.hyphenated_station_ids = contextlib.nullcontext
    try:
        products.write_edi(tf, SCRATCH / f"{PLAIN}_library.edi")
        products.write_xml(tf, SCRATCH / f"{PLAIN}_library.xml")
    finally:
        products.hyphenated_station_ids = kept
    for suffix in (".edi", ".xml"):
        ours, lib = SCRATCH / f"{PLAIN}{suffix}", SCRATCH / f"{PLAIN}_library{suffix}"
        keep = [[line for line in p.read_text(encoding="latin-1").splitlines() if not _DATE_LINE.search(line)]
                for p in (ours, lib)]
        if keep[0] != keep[1]:
            diff = [(a, b) for a, b in zip(*keep) if a != b][:2]
            bad.append(f"C4 {suffix}: written with the context differs from without: {diff}")
        a, b = products.read_tf(ours), library_read(ours)
        if a.station_metadata.id != b.station_metadata.id or not same_z(a, b, rtol=0.0):
            bad.append(f"C4 {suffix}: read_tf gives {a.station_metadata.id!r}, mt_metadata {b.station_metadata.id!r}")
    return bad


def check_restored() -> list[str]:
    """R: the patched names are mt_metadata's own after the context, also after an exception."""
    from mt_metadata.timeseries import Run
    from mt_metadata.transfer_functions.io.edi import edi as edi_module
    from mt_metadata.transfer_functions.io.edi.metadata import header as header_module
    from mt_metadata.transfer_functions.io.emtfxml import emtfxml as xml_module
    from mt_metadata.utils.validators import validate_station_name

    def own() -> bool:
        return (edi_module.Run is Run and xml_module.Run is Run
                and edi_module.validate_station_name is validate_station_name
                and header_module.validate_station_name is validate_station_name)

    bad = [] if own() else ["R: the names are not mt_metadata's own before the context"]
    with products.hyphenated_station_ids():
        if own():
            bad.append("R: the context patches nothing")
    if not own():
        bad.append("R: not restored after the context")
    with contextlib.suppress(RuntimeError):
        with products.hyphenated_station_ids():
            raise RuntimeError("inside")
    if not own():
        bad.append("R: not restored after an exception inside the context")
    return bad


def check_p1() -> tuple[list[str], str]:
    """P: the P1 wrapper products of KD-Q5, read only."""
    edis = sorted(glob.glob(P1_STEM + ".edi"))
    if not edis:
        return [], f"P: no {P1_STEM}.edi, not checked"
    edi = Path(edis[-1])
    xml = edi.with_suffix(".xml")
    a, b = products.read_tf(edi), products.read_tf(xml)
    bad = []
    for label, t in (("EDI", a), ("XML", b)):
        if t.station_metadata.id != "KD-Q5":
            bad.append(f"P {label}: station id {t.station_metadata.id!r}")
    if not same_z(a, b):
        bad.append("P: EDI and XML impedances differ")
    return bad, f"P: {edi.name} and .xml read as {a.station_metadata.id!r}, {b.station_metadata.id!r}, " \
                f"{np.asarray(a.period).size} periods"


def main() -> None:
    """Run S1, H1, H2, C1, C4, R and P, then the mutation."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    failures = check_patterns()
    print(f"  S1 the hyphen is the only character a Station id admits and a Run id refuses: "
          f"{'ok' if not failures else failures}")
    for station in HYPHENATED + (PLAIN,):
        bad = check_export(station)
        failures += bad
        print(f"  H1/H2 {station}: {'ok' if not bad else bad}")
    bad, info = check_control()
    failures += bad
    print(f"  C1 control, mt_metadata's own code on KD-Q5 ({info}): {'ok' if not bad else bad}")
    bad = check_plain()
    failures += bad
    print(f"  C4 {PLAIN} unchanged with the context: {'ok' if not bad else bad}")
    bad = check_restored()
    failures += bad
    print(f"  R names restored: {'ok' if not bad else bad}")
    bad, info = check_p1()
    failures += bad
    print(f"  {info}: {'ok' if not bad else bad}")
    if not failures:
        kept = products.hyphenated_station_ids
        products.hyphenated_station_ids = contextlib.nullcontext
        try:
            trip = check_export("KD-Q5", "_mutant")
        finally:
            products.hyphenated_station_ids = kept
        assert trip and "ValidationError" in trip[0], trip
        print(f"  mutation (no context) tripped: {trip[0][:120]}")
    if failures:
        print("\nFAIL  hyphen_station_export_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    print("\nPASS  hyphen_station_export_unit")


if __name__ == "__main__":
    main()
