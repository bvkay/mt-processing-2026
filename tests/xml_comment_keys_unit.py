# -*- coding: utf-8 -*-
"""
Unit test for the run-comment keys handed to the EMTF XML writer (mt_workbench.products.dot_free_comment_keys)

mt_metadata's EMTF XML writer splits a run comment on ";", takes the text
before the first ":" of each piece as an attribute path and raises
"Cannot set attribute" when the path does not exist, so a key with a dot
stops the write (upstream issues 48 and 82). Phoenix archives built
from commit 4beb3cd carry the key "dc rail (V, 0.9 x the input
range)" (`mt_workbench.dclevel.RAIL_PREFIX_DOTTED`), on which the XML write
fails. The ingest writes the
dot-free key `dclevel.RAIL_PREFIX`, and `products.xml_copy` passes each
run comment through `dot_free_comment_keys`, so such an archive
still exports.

TFs are built as tests/unknown_declination_unit.py builds one, with the
run comment set; a scratch Kalkaroo archive
(`SCRATCH_G5`, with the dotted key)
gives a real run comment when present,
read only.

Usage:
    python tests/xml_comment_keys_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - X1: `write_xml` raises, or writes no file, on a TF whose run comment
    holds the 4beb3cd dc level record with the dotted "dc rail" key, or
    the TF's own run comment is changed by the write;
  - X2 (the control that the case exercises the defect): mt_metadata's
    own writer (`TF.write(file_type="xml")` on the `xml_copy` made without
    the sanitiser) does not raise "Cannot set attribute" on that TF;
  - X3: `dot_free_comment_keys` leaves a dot in a key, changes a value,
    or changes a piece without ":" or a comment without a dotted key;
  - X4: `dclevel.RAIL_PREFIX` holds a dot before its ":", or mt_metadata's
    own writer refuses a run comment of `dclevel.level_note`'s record with
    it (parentheses, comma and % in the key), or `parse_level_note` does
    not read the rails back from either key;
  - X5 (when the scratch G5.h5 is present): its first run's comment does
    not hold the dotted key, `write_xml` refuses it, or mt_metadata's own
    writer does not raise "Cannot set attribute" on it.

The mutation, which must trip X1: `products.dot_free_comment_keys`
replaced by the identity.
"""

from __future__ import annotations

import sys
from pathlib import Path

import h5py

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.products as products  # noqa: E402
from mt_workbench import dclevel  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from unknown_declination_unit import make_tf as declination_tf  # noqa: E402

SCRATCH = scratch_dir("xml_comment_keys_unit")
SCRATCH_G5 = Path("D:/MT_DATA/MT_Kalkaroo_Workspace/mth5/scratch_sign_fix/mth5/G5.h5")
ROWS = [dict(channel=c, median_counts=m, rail_fraction=0.0, verdict="ok", rail_level=r)
        for c, m, r in (("ex", 1.065e-2, 2.25), ("ey", -3.1e-3, 2.25), ("hx", 2.0e-4, 1.125), ("hy", -7.7e-4, 1.125))]
LEVELS = "dc level (median V, rail %): ex +1.065e-02 0.00 ok, ey -3.100e-03 0.00 ok, hx +2.000e-04 0.00 ok"
DOTTED_RECORD = (f"phoenix_units: mt-io v_to_mv (gain 1000) replaced by phoenix_mv_to_v (gain 0.001); {LEVELS}; "
                 f"{dclevel.RAIL_PREFIX_DOTTED}ex 2.25, ey 2.25, hx 1.125, hy 1.125")


def make_tf(comment: str):
    """Return a TF with one run whose comment is `comment`."""
    tf = declination_tf(False)
    tf.station_metadata.runs[0].comments.value = comment
    return tf


def run_comment(tf) -> str:
    """Return the first run's comment text."""
    value = tf.station_metadata.runs[0].comments
    return str(getattr(value, "value", value) or "")


def library_refuses(comment: str, name: str) -> str | None:
    """Write a TF with `comment` through mt_metadata's own writer; return its error, None when it writes.

    The TF is the `products.xml_copy` that `write_xml` writes, made with
    `dot_free_comment_keys` replaced by the identity, so only the
    sanitiser is left out.
    """
    kept = products.dot_free_comment_keys
    products.dot_free_comment_keys = lambda text: text
    try:
        tfc = products.xml_copy(make_tf(comment))
    finally:
        products.dot_free_comment_keys = kept
    try:
        tfc.write(fn=SCRATCH / f"{name}.xml", file_type="xml")
    except AttributeError as exc:
        return str(exc).strip()
    return None


def check_export(comment: str, name: str) -> list[str]:
    """X1: `write_xml` writes the TF and leaves its comment as it was."""
    bad = []
    tf = make_tf(comment)
    path = SCRATCH / f"{name}.xml"
    path.unlink(missing_ok=True)
    try:
        products.write_xml(tf, path)
    except AttributeError as exc:
        return [f"X1 {name}: write_xml raises {str(exc).strip()!r}"]
    if not path.is_file() or path.stat().st_size == 0:
        bad.append(f"X1 {name}: no XML written")
    if run_comment(tf) != comment:
        bad.append(f"X1 {name}: the TF's run comment changed to {run_comment(tf)[:80]!r}")
    return bad


def check_keys() -> list[str]:
    """X3: `dot_free_comment_keys` on pieces."""
    bad = []
    got = products.dot_free_comment_keys(DOTTED_RECORD)
    for piece in got.split(";"):
        key, sep, _value = piece.partition(":")
        if sep and "." in key:
            bad.append(f"X3: key {key!r} keeps a dot")
    want = DOTTED_RECORD.replace("(V, 0.9 x", "(V, 0_9 x")
    if got != want:
        bad.append(f"X3: {got!r}, expected {want!r}")
    for text in ("phoenix_h_polarity -1", "a.b c", LEVELS, "clock_offset_s: -0.1148 s added", ""):
        if products.dot_free_comment_keys(text) != text:
            bad.append(f"X3: {text!r} changed to {products.dot_free_comment_keys(text)!r}")
    return bad


def check_source_key() -> list[str]:
    """X4: the dot-free key at the source, accepted by mt_metadata's own writer and read back."""
    bad = []
    if "." in dclevel.RAIL_PREFIX.split(":", 1)[0]:
        bad.append(f"X4: RAIL_PREFIX {dclevel.RAIL_PREFIX!r} has a dot in its key")
    note = dclevel.level_note(ROWS, "V")
    refused = library_refuses(f"phoenix_units: mt-io v_to_mv replaced; {note}", "source_key")
    if refused:
        bad.append(f"X4: mt_metadata's writer refuses the new record: {refused}")
    for label, text in (("new", note), ("dotted", DOTTED_RECORD)):
        rails = {r["channel"]: r.get("rail_level") for r in dclevel.parse_level_note(text)}
        want = {"ex": 2.25, "ey": 2.25, "hx": 1.125} if label == "dotted" else {r["channel"]: r["rail_level"]
                                                                                 for r in ROWS}
        if rails != want:
            bad.append(f"X4 {label} key: rails read back {rails}, expected {want}")
    return bad


def check_real() -> tuple[list[str], str]:
    """X5: the scratch G5.h5's first run comment; (failures, info)."""
    if not SCRATCH_G5.is_file():
        return [], f"X5: {SCRATCH_G5} absent, not checked"
    with h5py.File(SCRATCH_G5, "r", locking=False) as f:
        station = f["Experiment/Surveys"][list(f["Experiment/Surveys"])[0]]["Stations/G5"]
        run = sorted(r for r in station if r.startswith("sr"))[0]
        raw = station[run].attrs.get("comments")
    comment = raw.decode() if isinstance(raw, bytes) else str(raw)
    bad = []
    if dclevel.RAIL_PREFIX_DOTTED not in comment:
        bad.append("X5: G5's run comment lacks the dotted dc rail key")
    bad += [b.replace("X1", "X5") for b in check_export(comment, "scratch_G5")]
    refused = library_refuses(comment, "scratch_G5_library")
    if refused is None or "Cannot set attribute" not in refused:
        bad.append("X5: mt_metadata's own writer accepts G5's run comment: the case does not exercise the defect")
    return bad, f"X5: G5 {run} comment ({comment.count(';') + 1} pieces) exported; mt_metadata's own writer: {refused}"


def main() -> None:
    """Run X1-X5 and the mutation."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    failures = check_export(DOTTED_RECORD, "dotted")
    print(f"  X1 the 4beb3cd record through write_xml: {'ok' if not failures else failures}")
    refused = library_refuses(DOTTED_RECORD, "dotted_library")
    if refused is None or "Cannot set attribute" not in refused:
        failures.append("X2: mt_metadata's own writer accepts the dotted key: the check cannot fail")
    print(f"  X2 control, mt_metadata's own writer: {refused}")
    bad = check_keys()
    failures += bad
    print(f"  X3 dot_free_comment_keys: {'ok' if not bad else bad}")
    bad = check_source_key()
    failures += bad
    print(f"  X4 source key {dclevel.RAIL_PREFIX!r}: {'ok' if not bad else bad}")
    bad, info = check_real()
    failures += bad
    print(f"  {info}: {'ok' if not bad else bad}")
    if not failures:
        kept = products.dot_free_comment_keys
        products.dot_free_comment_keys = lambda text: text
        try:
            trip = check_export(DOTTED_RECORD, "mutant")
        finally:
            products.dot_free_comment_keys = kept
        assert trip and "Cannot set attribute" in trip[0], trip
        print(f"  mutation (no sanitiser) tripped: {trip[0][:120]}")
    if failures:
        print("\nFAIL  xml_comment_keys_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    print("\nPASS  xml_comment_keys_unit")


if __name__ == "__main__":
    main()
