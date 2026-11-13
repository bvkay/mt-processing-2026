# -*- coding: utf-8 -*-
"""
Unit test for scripts/deliver_as_laid.py: an electric line measured as reversed, delivered as laid

Builds, in a fresh scratch folder, five synthetic EDIs with mt_metadata's TF
(six periods; Z with a distinct non-zero value in every real and imaginary
part, its errors, a tipper with its errors; integer channel numbers; hz at
DIP 90; two processing-parameter lines) written as the workbench writes a
delivered EDI (`mt_workbench.products.write_edi` with channel geometry, then
merge_best's `patch_edi_text` with ACQBY and PROSBY), and a synthetic
survey.yaml with one site per EDI:

(a) SYNA, ey reversed (azimuth_ey 270), notes with a dated polarity note
    (S3 quadrant, yx 180 deg out as ingested, so Ey declared reversed);
(b) SYNB, ex reversed (azimuth_ex 180), no notes;
(c) SYNC, both lines reversed, notes with a census per line and a dead-line
    clause dated 2014-05-06 between the two declarations, and electrode
    positions on both lines (ex from (0, 0) to (50, 0), ey from (0, 0) to
    (0, 48));
(d) SYND, no reversed line;
(e) SYNE, `swap_e: true` with azimuth_ey 270;
(f) SYNF, ex reversed, with the x row not estimated at one period and the
    y row at another (NaN, written as EMPTY: a merged EDI's gap, or a
    one-row delivery form such as VIC023's).

Each case runs the script's `main` in process (the command line). Two layers
are checked: [W] the TF the script hands to mt_metadata's writer (captured by
wrapping `products.write_edi` as the script calls it) and [F] the written
EDI as mt_metadata's own reader (`TF(fn).read()`) reads it and as its text
states. "Bit-equal" is this test's own comparison: the float64 bit patterns
of every real and imaginary part are equal (the synthetic values hold no
zero, so no EMPTY rule is needed).

Usage:
    python tests/deliver_as_laid_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (a): at [W] or [F] a Zyx or Zyy part is not bit-equal to minus the
   input's, a Zxx or Zxy part, an error, a tipper value or a tipper error is
   not bit-equal to the input's; at [F] the periods are not bit-equal, the
   EMEAS line of ey does not state AZM=270.00 or that of ex AZM=0.00, any
   other field of an EMEAS or HMEAS line (ID, CHTYPE, X, Y, Z, X2, Y2, Z2,
   the other azimuths, DIP, ACQCHAN) differs from the input's, the INFO
   block does not hold exactly one as-laid line,
   ``transfer_function.processing_parameters.mt_workbench.as_laid_ey=``
   with the text "ey written as laid: AZM 270; the yx row (Zyx, Zyy) is the
   field as measured on the reversed dipole; a reader assuming north and
   east sees it 180 deg out, a reader honouring AZM recovers the tensor;
   reversal measured 2026-11-02 (the polarity note of (a)), declared in
   survey.yaml; <RULING>" (the script's `RULING`), or the input's two
   processing-parameter lines are
   not kept; or the script exits other than 0.
2. (b) likewise with Zxx and Zxy negated and Zyx and Zyy kept, ex AZM=180.00
   and ey AZM=90.00, one as-laid line, of ex, ending "reversal declared in
   survey.yaml; <RULING>" (no notes); (c) with both rows negated, ex
   AZM=180.00 and ey AZM=270.00, two as-laid lines (ex quoting the
   fixture's dated census header and its census of SYNC rr SYND xy, ey the
   same header and its own census, measured 2026-11-02, not the dead line's
   2014-05-06), and on both electric lines the electrode ends exchanged
   (X, Y the input's X2, Y2 and the reverse) with every other field kept.
3. (d): a value, error, period or field of a measurement line differs from
   the input's, an as-laid INFO line is written, the record's
   ``transformed`` is not "no reversed line; nothing transformed", or the
   script exits other than 0.
4. (e): the script does not exit 2 with a message on stderr naming swap_e,
   or it writes the output EDI or its record.
5. --check on (a), (b) and (c) does not exit 0 printing "PASS round trip"
   with the record's check PASS; a copy of (a)'s output whose first ZXYR
   value is moved by one unit in its last written digit does not make
   `check_files` (what --check calls) FAIL naming "Zxy real" at the period
   and index where this test's own comparison finds the copy differs; the
   round trip of (a) with one Zxy real part moved by one ULP
   (np.nextafter) does not make `first_difference` name that element (the
   check resolves the last bit).
6. The mutations, a copy of the script's `as_laid` with one defect put in
   its place for case (a): M1 negating the other line's row (ex's
   declaration negating Zyx and Zyy, ey's Zxx and Zxy) does not fail
   exactly check 1's row checks at both layers ([W] and [F] "negated" and
   "kept"); M2 negating the row's errors too does not fail exactly [W]
   "errors" (at [F] it cannot: the EDI stores the variance, the error
   squared, and mt_metadata reads the error back as its square root);
   M3 leaving the EMEAS azimuth nominal does not make the script exit 2
   with its own "EMEAS ey AZM 90 written, 270 intended", deliver no output
   and leave the part file failing exactly check 1's [F] "azimuths".
7. mt_metadata's reader does not give ey a measurement azimuth of 270 and
   ex 0 on (a)'s output, ex 180 and ey 90 on (b)'s, or does not read the
   as-laid INFO line back whole; `mt_workbench.compare.rho_phi` on the
   output does not put the reversed row's phases (yx and yy for (a), xy and
   xx for (b)) 180 deg (to 1e-9 deg, wrapped) from the input's at every
   period with the other row's phases and every apparent resistivity
   bit-equal.
8. (f): the EMPTY marker (1e+32) does not stand at exactly the input's
   places in every Z data block of the output (ZXXR ... ZXY.VAR at the x
   row's period, ZYXR ... ZYY.VAR at the y row's); a value outside those
   places is not as check 2 states (Zxx, Zxy negated; Zyx, Zyy, the errors
   and the tipper kept; to the bit); the record's row_empty_periods of ex
   is not 1; or --check does not exit 0 with PASS (the round trip counts
   two zeros as equal: an EMPTY place reads back as +0.0 whatever sign the
   negation gave it).
9. The corrected mode (``--corrected --check``) on (a), (c)
   and (d): the script does not exit 0 printing "PASS corrected"; at [W] or
   [F] a Z value, a Z error, a tipper value or error, or (at [F]) a period
   is not bit-equal to the input's; a field of an EMEAS or HMEAS line
   differs from the input's (AZM stays 0 and 90, the electrode ends of (c)
   stay); the INFO block does not hold exactly one
   ``mt_workbench.reversed_<line>`` line per reversed line with the text
   "<line> laid reversed; reversal measured 2026-11-02 (<the fragment of
   check 1 or 2>), declared in survey.yaml; the sign was applied at ingest,
   so the <mode> row (...) is in the nominal frame and AZM states <0|90>;
   <RULING_R19>" (the script's `RULING_R19`), or holds an as-laid line;
   the record
   ``<out>.reversed_lines.json`` does not say direction "corrected",
   rows_negated [] and check PASS ((d): transformed "no reversed line;
   nothing transformed"); (a)'s as-laid output, or (a)'s corrected output,
   given to --corrected is not refused (exit 2, no file); `check_corrected`
   does not FAIL on M4, a copy of (a)'s corrected output with its ZYXR
   block negated, naming "Zyx real", on M5, a copy without its
   reversed_ey INFO line, naming that line, and on (a)'s as-laid output.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402

import deliver_as_laid as D  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from merge_best import patch_edi_text  # noqa: E402
from mt_workbench import products  # noqa: E402
from mt_workbench.compare import rho_phi  # noqa: E402

PERIODS = np.array([0.7, 3.1, 14.0, 66.0, 310.0, 1450.0])
PARAMS = ["mt_workbench.tag=synthetic", "mt_workbench.flag_001=66,yx,quadrant"]
NUMBERS = {"ex": 3, "ey": 4, "hx": 5, "hy": 1, "hz": 2}
HEADER = {"acqby": "Synthetic Acquirer", "prosby": "Synthetic Processor"}
OPEN = ("written as laid: AZM {az}; the {mode} row ({e1}, {e2}) is the field as measured on the reversed dipole; a "
        "reader assuming north and east sees it 180 deg out, a reader honouring AZM recovers the tensor; ")
SYNC_EX = "stage 2 (agent T, 2026-11-02): census SYNC rr SYND xy -140.0 deg (out; 20 of 20 periods 30-3000 s in the " \
          "opposite quadrant)"
SYNC_EY = "stage 2 (agent T, 2026-11-02): census SYNC rr SYND yx +40.0 deg (out; 19 of 20 periods 30-3000 s in the " \
          "opposite quadrant)"
SYNA_EY = "polarity measured 2026-11-02 stage 0 smoke (S3 quadrant), yx 180 deg out as ingested"
NOTES = {
    "SYNA": ("EDL synthetic; rot_h from h_azimuth.py 2026-11-01 (stage 0 smoke); " + SYNA_EY + ", so Ey declared "
             "reversed (azimuth_ey 270, flip_reversed_dipoles); BK sign Ex -1 Ey +1"),
    "SYNC": ("EDL synthetic; GA MTH5 declination 12.3 AGRF; stage 2 (agent T, 2026-11-02): Ex declared reversed "
             "(azimuth_ex 180, flip_reversed_dipoles; R3): census SYNC rr SYND xy -140.0 deg (out; 20 of 20 periods "
             "30-3000 s in the opposite quadrant); the line carries the field (activity rises x1.5 from 2014-05-06); "
             "Ey declared reversed (azimuth_ey 270, flip_reversed_dipoles; R3): census SYNC rr SYND yx +40.0 deg (out; "
             "19 of 20 periods 30-3000 s in the opposite quadrant); GA rotation-fit reading to follow"),
    # the joint form of the Tasmania broadband notes (workbench issue 91): one clause declares both lines, with no
    # census after it and nothing before it, so neither line quotes a measurement
    "SYNG": ("EDL synthetic; dipoles: AusMT reference EDI EMEAS; azimuths 0/90 laid (no field record); "
             "ex+ey declared reversed 4 Nov 2026 (ruling 14)"),
}
# case: (site, survey.yaml entry, the lines reversed, electrode positions, the expected as-laid INFO texts)
CASES = {
    "a": ("SYNA", {"azimuth_ex": 0.0, "azimuth_ey": 270.0, "notes": NOTES["SYNA"]}, ["ey"], False,
          {"ey": "ey " + OPEN.format(az=270, mode="yx", e1="Zyx", e2="Zyy") + f"reversal measured 2026-11-02 "
                 f"({SYNA_EY}), declared in survey.yaml; ruling R5 2026-11-02"}),
    "b": ("SYNB", {"azimuth_ex": 180.0, "azimuth_ey": 90.0}, ["ex"], False,
          {"ex": "ex " + OPEN.format(az=180, mode="xy", e1="Zxx", e2="Zxy") + "reversal declared in survey.yaml; "
                 "ruling R5 2026-11-02"}),
    "c": ("SYNC", {"azimuth_ex": 180.0, "azimuth_ey": 270.0, "notes": NOTES["SYNC"]}, ["ex", "ey"], True,
          {"ex": "ex " + OPEN.format(az=180, mode="xy", e1="Zxx", e2="Zxy") + f"reversal measured 2026-11-02 "
                 f"({SYNC_EX}), declared in survey.yaml; ruling R5 2026-11-02",
           "ey": "ey " + OPEN.format(az=270, mode="yx", e1="Zyx", e2="Zyy") + f"reversal measured 2026-11-02 "
                 f"({SYNC_EY}), declared in survey.yaml; ruling R5 2026-11-02"}),
    "d": ("SYND", {"azimuth_ex": 0.0, "azimuth_ey": 90.0}, [], False, {}),
    "e": ("SYNE", {"azimuth_ex": 0.0, "azimuth_ey": 270.0, "swap_e": True}, None, False, {}),
    "f": ("SYNF", {"azimuth_ex": 180.0, "azimuth_ey": 90.0}, ["ex"], False,
          {"ex": "ex " + OPEN.format(az=180, mode="xy", e1="Zxx", e2="Zxy") + "reversal declared in survey.yaml; "
                 "ruling R5 2026-11-02"}),
    "g": ("SYNG", {"azimuth_ex": 180.0, "azimuth_ey": 270.0, "notes": NOTES["SYNG"]}, ["ex", "ey"], False,
          {"ex": "ex " + OPEN.format(az=180, mode="xy", e1="Zxx", e2="Zxy") + "reversal declared in survey.yaml; "
                 "ruling R5 2026-11-02",
           "ey": "ey " + OPEN.format(az=270, mode="yx", e1="Zyx", e2="Zyy") + "reversal declared in survey.yaml; "
                 "ruling R5 2026-11-02"}),
}
# case (f): the periods (indices) at which a row is not estimated, written as EMPTY: x row at 1, y row at 3
EMPTY_AT = {0: 1, 1: 3}
EMPTY = 1e32
ROW = {"ex": 0, "ey": 1}
AZM = {"ex": ("0.00", "180.00"), "ey": ("90.00", "270.00")}  # (nominal, as laid) as an EMEAS line states it
# check 6: the sub-checks of check 1 each mutation must fail, exactly
M1_FAILS = {"W negated", "W kept", "F negated", "F kept"}
M2_FAILS = {"W errors"}
M3_FAILS = {"F azimuths"}


# ------------------------------------------------------------------------------------------------- building


def build_edi(folder: Path, case: str) -> Path:
    """Write a case's synthetic EDI as the workbench writes a delivered one; return its path."""
    site, _entry, _lines, positions, _info = CASES[case]
    rng = np.random.default_rng(20261102 + ord(case))
    n = PERIODS.size

    def signed(shape):
        return rng.uniform(0.3, 9.0, shape) * rng.choice([-1.0, 1.0], shape)

    z = signed((n, 2, 2)) + 1j * signed((n, 2, 2))
    err = rng.uniform(0.01, 0.9, (n, 2, 2))
    t = 0.05 * signed((n, 1, 2)) + 0.05j * signed((n, 1, 2))
    terr = rng.uniform(0.005, 0.05, (n, 1, 2))
    if case == "f":  # a row not estimated at a period: NaN, which the writer stores as EMPTY
        for row, k in EMPTY_AT.items():
            z[k, row, :], err[k, row, :] = np.nan, np.nan
    tf = TF()
    sm = tf.station_metadata
    sm.id = site
    tf.survey_metadata.id = "deliver_as_laid_unit"
    sm.location.latitude, sm.location.longitude, sm.location.elevation = -38.5, 146.0, 128.0
    products.set_declination(sm, 12.3, "IGRF-14", 2014.31)
    sm.orientation.reference_frame = "geomagnetic"
    held = {str(ch.component) for ch in sm.runs[0].channels}
    assert held >= set(NUMBERS), f"the default TF's run holds {sorted(held)}"
    for ch in sm.runs[0].channels:
        if str(ch.component) in NUMBERS:
            ch.channel_number = NUMBERS[str(ch.component)]
    tf.period = PERIODS
    tf.impedance, tf.impedance_error = z, err
    tf.tipper, tf.tipper_error = t, terr
    sm.transfer_function.processing_parameters = list(PARAMS)
    ends = {"ex": ((0.0, 0.0), (50.0, 0.0)), "ey": ((0.0, 0.0), (0.0, 48.0))}
    geometry = {"hx": {"azimuth": 0.0, "tilt": 0.0}, "hy": {"azimuth": 90.0, "tilt": 0.0},
                "hz": {"azimuth": 0.0, "tilt": 90.0}}
    for comp, az, length in (("ex", 0.0, 50.0), ("ey", 90.0, 48.0)):
        neg, pos = ends[comp] if positions else ((0.0, 0.0), (0.0, 0.0))
        geometry[comp] = {"azimuth": az, "tilt": 0.0, "dipole_length": length, "negative": neg, "positive": pos}
    path = folder / f"{site}_in.edi"
    products.write_edi(tf, path, geometry=geometry)
    text = path.read_text(encoding="locale")
    path.write_text(patch_edi_text(text, HEADER), encoding="locale")
    return path


def write_survey(root: Path) -> Path:
    """Write the synthetic survey.yaml."""
    config = {"name": "deliver_as_laid_unit", "instrument": "edl", "sample_rate": 10,
              "data_root": str(root / "raw"), "workspace": str(root / "ws"),
              "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "azimuth_ex": 0.0, "azimuth_ey": 90.0,
                           "flip_reversed_dipoles": True},
              "sites": {site: dict(entry) for site, entry, *_rest in CASES.values()}}
    path = root / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------- running


def run(survey: Path, edi: Path, out: Path, extra=(), mutant=None) -> dict:
    """Run the script's main on one EDI; capture the TFs handed to the writer, the console and the status."""
    for stale in (out, out.with_suffix(".as_laid.json"), out.with_name(out.stem + "_part.edi")):
        stale.unlink(missing_ok=True)
    handed = []
    write_edi, as_laid = D.products.write_edi, D.as_laid

    def capture(tf, path, geometry=None):
        handed.append(copy.deepcopy(tf))
        return write_edi(tf, path, geometry=geometry)

    D.products.write_edi = capture
    if mutant is not None:
        D.as_laid = mutant
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = D.main([str(survey), str(edi), str(out), *extra])
    finally:
        D.products.write_edi, D.as_laid = write_edi, as_laid
    side = out.with_suffix(".as_laid.json")
    return {"status": status, "stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "handed": handed,
            "record": json.loads(side.read_text(encoding="utf-8")) if side.exists() else None}


def read(path: Path) -> TF:
    """Read an EDI with mt_metadata's own reader."""
    tf = TF(fn=str(path))
    tf.read()
    return tf


def bits(a) -> np.ndarray:
    """The float64 bit patterns of an array's real and imaginary parts, stacked."""
    a = np.asarray(a)
    parts = [a.real, a.imag] if np.iscomplexobj(a) else [a]
    return np.stack([np.ascontiguousarray(p, dtype=np.float64).view(np.uint64) for p in parts])


def bit_equal(a, b) -> bool:
    """Whether two arrays are equal to the bit."""
    return np.shape(a) == np.shape(b) and np.array_equal(bits(a), bits(b))


def meas(text: str) -> dict[str, dict[str, str]]:
    """The EMEAS and HMEAS lines' fields by channel, as written."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*>[EH]MEAS\s+(.*)", line)
        if m:
            fields = dict(re.findall(r"(\w+)=(\S+)", m.group(1)))
            out[fields["CHTYPE"].lower()] = fields
    return out


def empty_places(text: str) -> dict[str, list[int]]:
    """The places (value indices) of the EMPTY marker in each Z data block of an EDI's text, blocks holding one."""
    out, name, values = {}, None, []
    for line in text[text.find(">FREQ"):].splitlines() + [">END"]:
        body = line.strip()
        if body.startswith(">"):
            if name and name.startswith("Z") and name not in ("ZROT",):
                places = [i for i, v in enumerate(values) if float(v) == EMPTY]
                if places:
                    out[name] = places
            name, values = body[1:].split()[0], []
        elif body and not body.startswith("!"):
            values += body.split()
    return out


def as_laid_lines(text: str) -> dict[str, list[str]]:
    """The INFO lines keyed mt_workbench.as_laid_<line>, by line (a list, to count repeats)."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"\s*transfer_function\.processing_parameters\.mt_workbench\.as_laid_(\w+)=(.*)$", line)
        if m:
            out.setdefault(m.group(1), []).append(m.group(2).rstrip())
    return out


# -------------------------------------------------------------------------------------------- check 1 and 2


def tensor_checks(layer: str, tf_in: TF, tf_out: TF, reversed_: list[str]) -> list[tuple[str, str, bool, str]]:
    """The tensor sub-checks of one layer: (id, criterion, ok, detail)."""
    z_in, z_out = np.asarray(tf_in.impedance.data), np.asarray(tf_out.impedance.data)
    rows = [ROW[c] for c in reversed_]
    kept = [r for r in (0, 1) if r not in rows]
    names = {0: "Zxx, Zxy", 1: "Zyx, Zyy"}
    out = []
    neg = all(bit_equal(z_out[:, r, :], -z_in[:, r, :]) for r in rows)
    out.append((f"{layer} negated", f"a part of {' and '.join(names[r] for r in rows) or 'no row'} is not bit-equal "
                f"to minus the input's", neg, ""))
    same = all(bit_equal(z_out[:, r, :], z_in[:, r, :]) for r in kept)
    out.append((f"{layer} kept", f"a part of {' and '.join(names[r] for r in kept) or 'no row'} is not bit-equal to "
                f"the input's", same, ""))
    out.append((f"{layer} errors", "a Z error is not bit-equal to the input's",
                bit_equal(np.asarray(tf_out.impedance_error.data), np.asarray(tf_in.impedance_error.data)), ""))
    out.append((f"{layer} tipper", "a tipper value or error is not bit-equal to the input's",
                bit_equal(np.asarray(tf_out.tipper.data), np.asarray(tf_in.tipper.data))
                and bit_equal(np.asarray(tf_out.tipper_error.data), np.asarray(tf_in.tipper_error.data)), ""))
    if layer == "F":
        out.append(("F periods", "a period is not bit-equal to the input's",
                    bit_equal(np.asarray(tf_out.period), np.asarray(tf_in.period)), ""))
    return out


def file_checks(case: str, in_text: str, out_text: str) -> list[tuple[str, str, bool, str]]:
    """The text sub-checks of the written EDI: measurement lines and INFO."""
    _site, _entry, reversed_, positions, info = CASES[case]
    m_in, m_out = meas(in_text), meas(out_text)
    want = {c: AZM[c][1] if c in reversed_ else AZM[c][0] for c in ("ex", "ey")}
    got = {c: m_out.get(c, {}).get("AZM") for c in ("ex", "ey")}
    out = [("F azimuths", f"EMEAS ex does not state AZM={want['ex']} or ey AZM={want['ey']}", got == want,
            f"ex {got['ex']}, ey {got['ey']}")]
    bad = []
    for comp, fields in m_in.items():
        expected = dict(fields)
        if comp in reversed_:
            expected.pop("AZM")
            if positions:
                expected["X"], expected["Y"], expected["X2"], expected["Y2"] = (fields["X2"], fields["Y2"], fields["X"],
                                                                                fields["Y"])
        written = {k: v for k, v in m_out.get(comp, {}).items() if not (comp in reversed_ and k == "AZM")}
        if written != expected:
            bad.append(f"{comp}: {written} not {expected}")
    if set(m_out) != set(m_in):
        bad.append(f"channels {sorted(m_out)} not {sorted(m_in)}")
    ends = " (the reversed lines' ends exchanged)" if positions and reversed_ else ""
    out.append(("F lines", f"a field of an EMEAS or HMEAS line other than the reversed lines' AZM differs from the "
                f"input's{ends}", not bad, "; ".join(bad)))
    lines = as_laid_lines(out_text)
    expect = {c: [text] for c, text in info.items()}
    out.append(("F info", f"the as-laid INFO lines are not exactly {len(expect)} ({', '.join(expect) or 'none'}) "
                f"with the stated text", lines == expect, "" if lines == expect else f"got {lines}"))
    params = D.processing_parameters(out_text)
    out.append(("F params", "the input's processing-parameter lines are not kept",
                all(p in params for p in PARAMS), ""))
    return out


def case_checks(case: str, edi: Path, out: Path, result: dict, check_exit: bool = True) -> list[tuple]:
    """Every sub-check of checks 1-3 for a case's run (or of check 1 on a part file when `check_exit` is False)."""
    _site, _entry, reversed_, _positions, _info = CASES[case]
    tf_in = read(edi)
    rows = []
    if check_exit:
        rows.append(("exit 0", "the script does not exit 0", result["status"] == 0, result["stderr"].strip()[:300]))
    if result["handed"]:
        rows += tensor_checks("W", tf_in, result["handed"][0], reversed_)
    if out.exists():
        rows += tensor_checks("F", tf_in, read(out), reversed_)
        rows += file_checks(case, edi.read_text(encoding="latin-1"), out.read_text(encoding="latin-1"))
    else:
        rows.append(("F written", "no output EDI is written", False, str(out)))
    return rows


def show(check: str, case: str, rows: list[tuple], label: str = "") -> set[str]:
    """Print a case's sub-checks, one line each with its failure criterion; return the ids that failed."""
    failed = set()
    for sid, criterion, ok, detail in rows:
        failed |= set() if ok else {sid}
        tail = "ok" if ok else f"FAIL {detail}".rstrip()
        print(f"  [{check}]{label} ({case}) {sid:<11} fails if {criterion}: {tail}")
    return failed


# ------------------------------------------------------------------------------------------------- mutations


def m1_wrong_row(tf, comps, geometry, laid=True):
    """`as_laid` with the rows exchanged: ex's declaration negates Zyx and Zyy, ey's Zxx and Zxy (mutation M1)."""
    z = np.array(tf.impedance.data)
    for comp in comps:
        row = 1 - D.LINES[comp]["row"]  # the defect
        z[:, row, :] = -z[:, row, :]
        g = geometry[comp]
        g["azimuth"] = D.LINES[comp]["laid" if laid else "nominal"]
        if any(g["negative"]) or any(g["positive"]):
            g["negative"], g["positive"] = g["positive"], g["negative"]
    tf.impedance = z


def m2_errors_too(tf, comps, geometry, laid=True):
    """`as_laid` negating the row's errors as well as its values (mutation M2)."""
    z = np.array(tf.impedance.data)
    err = np.array(tf.impedance_error.data)
    for comp in comps:
        row = D.LINES[comp]["row"]
        z[:, row, :] = -z[:, row, :]
        err[:, row, :] = -err[:, row, :]  # the defect
        g = geometry[comp]
        g["azimuth"] = D.LINES[comp]["laid" if laid else "nominal"]
        if any(g["negative"]) or any(g["positive"]):
            g["negative"], g["positive"] = g["positive"], g["negative"]
    tf.impedance = z
    tf.impedance_error = err


def m3_no_azimuth(tf, comps, geometry, laid=True):
    """`as_laid` that negates the rows and leaves the EMEAS geometry as it was (mutation M3)."""
    z = np.array(tf.impedance.data)
    for comp in comps:
        row = D.LINES[comp]["row"]
        z[:, row, :] = -z[:, row, :]
        # the defect: no azimuth set, no ends exchanged
    tf.impedance = z


# ----------------------------------------------------------------------------------- check 9 (the corrected mode)

R19_TAIL = "ruling R19 2026-11-05"
# case: the expected corrected-mode INFO texts (the measurement as checks 1 and 2 quote it)
CORRECTED = {
    "a": {"ey": f"ey laid reversed; reversal measured 2026-11-02 ({SYNA_EY}), declared in survey.yaml; the sign was "
                f"applied at ingest, so the yx row (Zyx, Zyy) is in the nominal frame and AZM states 90; {R19_TAIL}"},
    "c": {"ex": f"ex laid reversed; reversal measured 2026-11-02 ({SYNC_EX}), declared in survey.yaml; the sign was "
                f"applied at ingest, so the xy row (Zxx, Zxy) is in the nominal frame and AZM states 0; {R19_TAIL}",
          "ey": f"ey laid reversed; reversal measured 2026-11-02 ({SYNC_EY}), declared in survey.yaml; the sign was "
                f"applied at ingest, so the yx row (Zyx, Zyy) is in the nominal frame and AZM states 90; {R19_TAIL}"},
    "d": {},
}


def reversed_lines(text: str) -> dict[str, list[str]]:
    """The INFO lines keyed mt_workbench.reversed_<line>, by line (a list, to count repeats)."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"\s*transfer_function\.processing_parameters\.mt_workbench\.reversed_(\w+)=(.*)$", line)
        if m:
            out.setdefault(m.group(1), []).append(m.group(2).rstrip())
    return out


def negate_block(text: str, block: str) -> str:
    """Return an EDI's text with every value of one data block (">ZYXR") negated in its written form."""
    lines = text.splitlines(keepends=True)
    start = next(k for k, line in enumerate(lines) if line.strip().startswith(f">{block}"))
    k = start + 1
    while k < len(lines) and not lines[k].strip().startswith(">"):
        lines[k] = re.sub(r"(?<!\S)(-?)(\d)", lambda m: ("" if m.group(1) else "-") + m.group(2), lines[k])
        k += 1
    return "".join(lines)


def check_corrected_mode(survey: Path, edis: dict, outs: dict, root: Path) -> set[str]:
    """Check 9: the corrected mode's output, record, refusals and two mutations; return the ids that failed."""
    failed: set[str] = set()
    for case in ("a", "c", "d"):
        site = CASES[case][0]
        out = root / "out" / f"{site}_corrected.edi"
        side = out.with_suffix(".reversed_lines.json")
        side.unlink(missing_ok=True)
        res = run(survey, edis[case], out, extra=["--corrected", "--check"])
        record = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        rows = [("exit 0", "the script does not exit 0 printing \"PASS corrected\"",
                 res["status"] == 0 and "PASS corrected" in res["stdout"],
                 res["stdout"].strip()[-200:] + res["stderr"].strip()[:200])]
        tf_in = read(edis[case])
        if res["handed"]:
            rows += [r for r in tensor_checks("W", tf_in, res["handed"][0], []) if r[0] != "W negated"]
        if out.exists():
            rows += [r for r in tensor_checks("F", tf_in, read(out), []) if r[0] != "F negated"]
            in_text, out_text = edis[case].read_text(encoding="latin-1"), out.read_text(encoding="latin-1")
            m_in, m_out = meas(in_text), meas(out_text)
            rows.append(("F lines", "a field of an EMEAS or HMEAS line differs from the input's (AZM 0 / 90 and the "
                         "electrode ends kept)", m_in == m_out and m_out["ex"]["AZM"] == "0.00"
                         and m_out["ey"]["AZM"] == "90.00", "" if m_in == m_out else f"{m_out} not {m_in}"))
            got = reversed_lines(out_text)
            expect = {c: [t] for c, t in CORRECTED[case].items()}
            rows.append(("F info", f"the reversed INFO lines are not exactly {len(expect)} with the stated text, or an "
                         f"as-laid line is written", got == expect and not as_laid_lines(out_text),
                         "" if got == expect else f"got {got}"))
        else:
            rows.append(("F written", "no output EDI is written", False, str(out)))
        if case == "d":
            ok = record.get("transformed") == D.NOTHING and record.get("direction") == "corrected"
        else:
            ok = (record.get("direction") == "corrected" and record.get("rows_negated") == []
                  and all(e["rows_negated"] == [] for e in record.get("transformed", [])))
        ok = ok and (record.get("check") or {}).get("result") == "PASS"
        rows.append(("record", "the record does not say direction corrected, rows_negated [] (or (d)'s nothing "
                     "transformed) and check PASS", ok, json.dumps({k: record.get(k) for k in
                                                                    ("direction", "rows_negated", "check")})[:240]))
        failed |= {f"{case} {sid}" for sid in show("9", case, rows)}

    # refusals: an as-laid input, an input already corrected
    rows = []
    for name, src in (("as laid", outs["a"]), ("again", root / "out" / "SYNA_corrected.edi")):
        dst = root / "out" / f"SYNA_refused_{name.replace(' ', '_')}.edi"
        res = run(survey, src, dst, extra=["--corrected"])
        ok = res["status"] == 2 and "REFUSED" in res["stderr"] and not dst.exists() and not dst.with_suffix(
            ".reversed_lines.json").exists()
        rows.append((f"refuse {name}", f"--corrected on (a)'s {name} output does not exit 2 writing nothing", ok,
                     res["stderr"].strip()[:160]))
    # mutations: M4 the yx row negated in the corrected output, M5 its INFO line removed; and the as-laid output
    good = root / "out" / "SYNA_corrected.edi"
    text = good.read_text(encoding="locale")
    m4 = root / "out" / "SYNA_corrected_m4.edi"
    m4.write_text(negate_block(text, "ZYXR"), encoding="locale")
    v4 = D.check_corrected(survey, edis["a"], m4)
    rows.append(("M4 negated", "check_corrected does not FAIL naming \"Zyx real\" on a copy with ZYXR negated",
                 v4["result"] == "FAIL" and (v4["first_difference"] or "").startswith("Zyx real"),
                 str(v4["first_difference"])))
    m5 = root / "out" / "SYNA_corrected_m5.edi"
    m5.write_text("".join(ln for ln in text.splitlines(keepends=True) if "mt_workbench.reversed_ey=" not in ln),
                  encoding="locale")
    v5 = D.check_corrected(survey, edis["a"], m5)
    rows.append(("M5 no INFO", "check_corrected does not FAIL naming mt_workbench.reversed_ey on a copy without it",
                 v5["result"] == "FAIL" and "mt_workbench.reversed_ey" in (v5["first_difference"] or ""),
                 str(v5["first_difference"])))
    v6 = D.check_corrected(survey, edis["a"], outs["a"])
    rows.append(("as laid", "check_corrected does not FAIL on (a)'s as-laid output", v6["result"] == "FAIL",
                 "; ".join(v6.get("problems", []))[:200]))
    print(f"        M4: {v4['first_difference']}; M5: {v5['first_difference']}; as laid: {v6['first_difference']}")
    failed |= {f"x {sid}" for sid in show("9", "a", rows)}
    return failed


# ------------------------------------------------------------------------------------------------------ main


def main() -> None:
    from loguru import logger

    logger.remove()  # mt_metadata's INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    print(f"  script: {D.__file__}")
    root = Path(tempfile.mkdtemp(dir=scratch_dir("deliver_as_laid_unit")))
    survey = write_survey(root)
    edis = {case: build_edi(root, case) for case in CASES}
    outs = {case: root / "out" / f"{CASES[case][0]}.edi" for case in CASES}
    failures: dict[str, set] = {}

    # checks 1-3: (a), (b), (c), (d)
    results = {}
    for case, check in (("a", "1"), ("b", "2"), ("c", "2"), ("d", "3"), ("g", "2")):
        results[case] = run(survey, edis[case], outs[case])
        rows = case_checks(case, edis[case], outs[case], results[case])
        if case == "d":
            record = results[case]["record"] or {}
            rows.append(("record", f"the record's transformed is not \"{D.NOTHING}\"",
                         record.get("transformed") == D.NOTHING, str(record.get("transformed"))))
        failures[case] = show(check, case, rows)

    # check 4: (e) refused
    res = run(survey, edis["e"], outs["e"])
    rows = [("exit 2", "the script does not exit 2", res["status"] == 2, str(res["status"])),
            ("message", "stderr does not name swap_e", "swap_e" in res["stderr"], res["stderr"].strip()[:200]),
            ("no file", "an output EDI or record is written",
             not outs["e"].exists() and not outs["e"].with_suffix(".as_laid.json").exists(), "")]
    print(f"        (e) stderr: {res['stderr'].strip()[:160]}")
    failures["e"] = show("4", "e", rows)

    # check 5: --check PASS on (a), (b), (c); a corrupted output FAILs; the check resolves one ULP
    rows5 = []
    for case in ("a", "b", "c"):
        res = run(survey, edis[case], outs[case], extra=["--check"])
        ok = (res["status"] == 0 and "PASS round trip" in res["stdout"]
              and (res["record"] or {}).get("check", {}).get("result") == "PASS")
        rows5.append((f"check {case}", f"--check on ({case}) does not exit 0 with PASS", ok,
                      res["stdout"].strip()[-200:] + res["stderr"].strip()[:200]))
    text = outs["a"].read_text(encoding="locale")
    m = re.search(r">ZXYR[^\n]*\n\s*(\S+)", text)
    token = m.group(1)
    mantissa, exponent = token.split("e")
    last = int(mantissa[-1])
    moved = mantissa[:-1] + str(last + 1 if last < 9 else last - 1) + "e" + exponent
    corrupt = root / "out" / "SYNA_corrupt.edi"
    corrupt.write_text(text[:m.start(1)] + moved + text[m.end(1):], encoding="locale")
    z_good, z_bad = np.asarray(read(outs["a"]).impedance.data), np.asarray(read(corrupt).impedance.data)
    where = np.argwhere(bits(z_good) != bits(z_bad))  # (part, period, row, column)
    own = [tuple(int(i) for i in w) for w in where]
    period = np.asarray(read(outs["a"]).period)
    expect_k = own[0][1] if len(own) == 1 and own[0][0] == 0 and own[0][2:] == (0, 1) else None
    verdict = D.check_files(survey, edis["a"], corrupt)
    named = verdict["first_difference"] or ""
    ok = (expect_k is not None and verdict["result"] == "FAIL"
          and named.startswith(f"Zxy real at period {period[expect_k]:.6g} s (index {expect_k})"))
    print(f"        corrupted copy: ZXYR's first value {token} -> {moved}; this test finds {own} "
          f"(part, period index, row, column); --check: {verdict['result']} {named}")
    rows5.append(("corrupt", "a copy with one ZXYR value moved by one unit in its last digit does not FAIL naming "
                  "\"Zxy real\" at the period and index this test finds", ok, named))
    tf_in, tf_back = D.round_trip(survey, edis["a"], outs["a"], folder=root / "out")
    clean = D.first_difference(tf_in, tf_back)
    z = np.array(tf_back.impedance.data)
    k = 2
    nudged = np.nextafter(z[k, 0, 1].real, np.inf)
    # one step of the bit pattern (its integer moves by -1 for a negative value nudged toward +inf)
    one_ulp = abs(int(np.float64(nudged).view(np.int64)) - int(np.float64(z[k, 0, 1].real).view(np.int64))) == 1
    z[k, 0, 1] = complex(nudged, z[k, 0, 1].imag)
    tf_back.impedance = z
    named = D.first_difference(tf_in, tf_back) or ""
    ok = clean is None and one_ulp and named.startswith(f"Zxy real at period {period[k]:.6g} s (index {k})")
    print(f"        one ULP: round trip {clean or 'identical'}; nudged -> {named}")
    rows5.append(("one ULP", "the round trip differs before the nudge, or one ULP on one Zxy real part is not named",
                  ok, named))
    # workbench issue 91: the joint clause "ex+ey declared reversed ..." quotes no measurement for either line, and
    # the single-line clauses of (c) still do
    joint = (D.measurement(NOTES["SYNG"], "ey"), D.measurement(NOTES["SYNG"], "ex"))
    single = D.measurement(NOTES["SYNC"], "ey")
    ok = joint == (None, None) and single is not None and single["fragment"] == SYNC_EY
    rows5.append(("issue 91", "the joint clause of (g) quotes a fragment for ex or ey, or (c)'s ey clause no longer "
                  "quotes its census", ok, f"joint {joint}; single {single and single['fragment']}"))
    failures["5"] = show("5", "a-c", rows5)

    assert not any(failures.values()), {k: v for k, v in failures.items() if v}

    # check 6: the mutations, each in the script's place for case (a)
    mut = root / "out" / "SYNA_mutant.edi"  # the mutations write beside, not over, (a)'s output
    res = run(survey, edis["a"], mut, mutant=m1_wrong_row)
    m1 = show("6", "a", case_checks("a", edis["a"], mut, res), label=" M1")
    assert m1 == M1_FAILS, f"M1 (wrong row) failed {sorted(m1)}, expected {sorted(M1_FAILS)}"
    print(f"  mutation M1 (wrong row): fails exactly {', '.join(sorted(m1))}, as required")
    res = run(survey, edis["a"], mut, mutant=m2_errors_too)
    m2 = show("6", "a", case_checks("a", edis["a"], mut, res), label=" M2")
    assert m2 == M2_FAILS, f"M2 (errors too) failed {sorted(m2)}, expected {sorted(M2_FAILS)}"
    print(f"  mutation M2 (errors negated too): fails exactly {', '.join(sorted(m2))}, as required (the EDI's VAR "
          f"is the error squared, so the file cannot show it)")
    res = run(survey, edis["a"], mut, mutant=m3_no_azimuth)
    part = mut.with_name(mut.stem + "_part.edi")
    refused = (res["status"] == 2 and "EMEAS ey AZM 90 written, 270 intended" in res["stderr"]
               and not mut.exists() and part.exists())
    print(f"  [6] M3 (a) script    fails if it does not exit 2 with its own AZM message, delivering nothing and "
          f"leaving the part file: {'ok' if refused else 'FAIL'} (exit {res['status']}: {res['stderr'].strip()[:120]})")
    assert refused, res
    part_out = root / "out" / "SYNA_m3_part.edi"
    shutil.copyfile(part, part_out)
    m3 = show("6", "a", case_checks("a", edis["a"], part_out, res, check_exit=False), label=" M3 part")
    assert m3 == M3_FAILS, f"M3 (no azimuth) failed {sorted(m3)} on the part file, expected {sorted(M3_FAILS)}"
    print(f"  mutation M3 (azimuth forgotten): the script refuses it, and its part file fails exactly "
          f"{', '.join(sorted(m3))}, as required")

    # check 7: read back by mt_metadata; rho_phi
    rows7 = []
    for case, comp, other in (("a", "ey", "ex"), ("b", "ex", "ey")):
        tf_out = read(outs[case])
        az = {str(ch.component): float(ch.measurement_azimuth) for ch in tf_out.station_metadata.runs[0].channels
              if str(ch.component) in ("ex", "ey")}
        want = {comp: D.LINES[comp]["laid"], other: D.LINES[other]["nominal"]}
        rows7.append((f"azimuth {case}", f"mt_metadata does not read {comp} at {want[comp]:g} and {other} at "
                      f"{want[other]:g}", az == want, str(az)))
        params = tf_out.station_metadata.transfer_function.processing_parameters
        text = CASES[case][4][comp]
        rows7.append((f"info {case}", f"mt_metadata does not read the as-laid line of {comp} back whole",
                      f"as_laid_{comp}={text}" in params, ""))
        p_in, rho_in, phi_in, *_ = rho_phi(edis[case])
        p_out, rho_out, phi_out, *_ = rho_phi(outs[case])
        r = ROW[comp]
        shift = (phi_out[:, r, :] - phi_in[:, r, :] + 180.0) % 360.0 - 180.0
        moved = bool(np.all(np.abs(np.abs(shift) - 180.0) < 1e-9))
        still = bit_equal(phi_out[:, 1 - r, :], phi_in[:, 1 - r, :]) and bit_equal(rho_out, rho_in)
        rows7.append((f"phase {case}", f"the {D.LINES[comp]['mode']} row's phases are not 180 deg from the input's "
                      f"at every period, or the other row's phases or any rho differ", moved and still,
                      f"|shift| - 180 at most {np.max(np.abs(np.abs(shift) - 180.0)):.1e} deg"))
    failures["7"] = show("7", "a,b", rows7)
    assert not failures["7"], failures["7"]

    # check 8: EMPTY places kept, the values around them as check 2 states, --check PASS
    res = run(survey, edis["f"], outs["f"], extra=["--check"])
    in_text, out_text = edis["f"].read_text(encoding="latin-1"), outs["f"].read_text(encoding="latin-1")
    places_in, places_out = empty_places(in_text), empty_places(out_text)
    want = {f"Z{a}{b}{p}": [EMPTY_AT[r]] for r, a in enumerate("XY") for b in "XY" for p in ("R", "I", ".VAR")}
    rows8 = [("places", "the EMPTY marker does not stand at exactly the input's places in every data block (the x "
              f"row's at period index {EMPTY_AT[0]}, the y row's at {EMPTY_AT[1]})",
              places_out == places_in == want, f"input {places_in}, output {places_out}")]
    tin, tout = read(edis["f"]), read(outs["f"])
    z_in, z_out = np.asarray(tin.impedance.data), np.asarray(tout.impedance.data)
    held = np.ones(z_in.shape, dtype=bool)
    for row, k in EMPTY_AT.items():
        held[k, row, :] = False
    values = (bit_equal(z_out[:, 0, :][held[:, 0, :]], -z_in[:, 0, :][held[:, 0, :]])
              and bit_equal(z_out[:, 1, :][held[:, 1, :]], z_in[:, 1, :][held[:, 1, :]])
              and bit_equal(np.asarray(tout.impedance_error.data), np.asarray(tin.impedance_error.data))
              and bit_equal(np.asarray(tout.tipper.data), np.asarray(tin.tipper.data)))
    rows8.append(("values", "a value outside the EMPTY places is not as check 2 states (Zxx, Zxy negated; Zyx, Zyy, "
                  "the errors and the tipper kept; to the bit)", values, ""))
    entry = ((res["record"] or {}).get("transformed") or [{}])[0]
    rows8.append(("record", "the record's row_empty_periods of ex is not 1", entry.get("row_empty_periods") == 1,
                  str(entry.get("row_empty_periods"))))
    rows8.append(("check", "--check does not exit 0 with PASS (two zeros equal: EMPTY carries no sign)",
                  res["status"] == 0 and "PASS round trip" in res["stdout"], res["stdout"].strip()[-160:]))
    failures["8"] = show("8", "f", rows8)
    assert not failures["8"], failures["8"]

    # check 9: the corrected mode on (a), (c), (d); refusals; mutations M4 and M5
    failures["9"] = check_corrected_mode(survey, edis, outs, root)
    assert not failures["9"], failures["9"]

    shutil.rmtree(root)


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    main()
    print("\nPASS  deliver_as_laid_unit")
