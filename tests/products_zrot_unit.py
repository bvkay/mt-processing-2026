# -*- coding: utf-8 -*-
"""
Unit test for the survey option products.zrot (declination | zero) and the instrument INFO lines

Under ``zero`` (the Queensland convention) a geomagnetic product carries
ZROT = TROT = 0, the declination recorded and not applied; under
``declination`` (the default) it carries ZROT = TROT = the declination, as
`mt_workbench.products` wrote before the option. The survey.yaml block
`products: {zrot: declination | zero}` chooses, and the default leaves the
products unchanged. The instrument INFO lines carry the local site's
instrument identity from `surveys/<survey>/instruments.csv`.

Usage:
    python tests/products_zrot_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) `zrot_rule_of` does not give "declination" for a survey without the block,
    "zero" for `products: {zrot: zero}`, or accepts `zrot: geographic`;
(2) a small geomagnetic TF with declination 7.21 (IGRF-14, 2013.80) and a
    tipper, written under `zero`, read back from the file does not hold ZROT 0
    and TROT 0 at every period, the HEAD lines COORDINATE_SYSTEM=geomagnetic,
    DECLINATION=7.21, DECLINATION.MODEL=IGRF-14, DECLINATION.EPOCH=2013.80,
    INFO transfer_function.coordinate_system=geomagnetic, an INFO line naming
    the rule (zrot_rule=zero) and a rotation line saying ZROT and TROT 0; or
    any INFO line names another coordinate system or "ZROT and TROT state this
    azimuth"; or mt_metadata reads back another declination than 7.21;
(3) the same TF under the default does not hold ZROT = TROT = 7.21 (today's);
(4) a fresh product (the small TF under the default) differs in any byte but
    FILEDATE from the same written by the code before this change
    (tests/fixtures/small_tf_default_before_zrot.edi); or an existing Flinders
    product (FR05L rr FR01L, flinders1), read and re-written by `write_edi`,
    differs from the frozen re-write by the code before
    (tests/fixtures/FR05L_rr-FR01L_rewritten_before_zrot.edi) in anything but
    the repeated bare-key frame lines (frame=, rotation=, rot_h=) the old
    re-write carried. The code before repeated a read-back EDI's frame
    lines under bare keys, which (b) forbids (with a declination they
    contradict the new lines), so identity is required of a fresh product and of the re-write less those lines in any byte but the FILEDATE line
    (mt_metadata stamps the write time there); and a read-back EDI re-written
    with a declination keeps a stale frame line ("no declination stored")
    beside the new ones (a contradiction in INFO);
(5) `frame_record` under zero does not give zrot 0 and zrot_rule "zero", or
    `frame_note` does not say the EDI's ZROT and TROT are 0;
(6) `instrument_info_lines` for a site of a synthetic instruments.csv (and its
    derived site) does not give `mt_workbench.instrument_logger=<model> <serial>
    <doi> (<doi source>)` and `mt_workbench.instrument_magnetometer=<model>
    <serial>`, each written line under INFO_MAX; `apply_instruments` does not
    set the TF's run data_logger id/model and its magnetic channels' sensor
    id/model; or the lines are not read back from the EDI;
(7) merge_modes.merge_files of two EDIs written under zero does not write a
    merged EDI with ZROT 0 and the rule line.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from mt_metadata.transfer_functions.core import TF  # noqa: E402

from mt_workbench import products as P  # noqa: E402

# the Flinders product below, read and re-written by write_edi with the code before products.zrot existed,
# frozen; compared line by line but for FILEDATE, the write time
FROZEN_EDI = Path(__file__).resolve().parent / "fixtures" / "FR05L_rr-FR01L_rewritten_before_zrot.edi"
# small_tf() under the default, written by the code before, frozen
FROZEN_FRESH = Path(__file__).resolve().parent / "fixtures" / "small_tf_default_before_zrot.edi"
FLINDERS = Path(r"D:\MT_DATA\MT_SA_AusLAMP_2013_2018_Workspace\tf\FR05L_rr-FR01L_20261108-1009_flinders1-default.edi")
fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


class FakeSurvey:
    def __init__(self, config, folder=None, parents=None):
        self.config, self.folder, self._parents = config, folder, parents or {}

    def parent_of(self, site):
        return self._parents.get(site)


def small_tf() -> TF:
    per = np.logspace(1, 3, 7)
    zh = np.sqrt(100.0 / (0.2 * per)) * np.exp(0.25j * np.pi)
    z = np.zeros((per.size, 2, 2), dtype=complex)
    z[:, 0, 1], z[:, 1, 0], z[:, 0, 0], z[:, 1, 1] = zh, -zh, 0.1 * zh, -0.1 * zh
    tf = TF()
    tf.station_metadata.id = "FR05L"
    tf.station_metadata.location.latitude = -31.14
    tf.station_metadata.location.longitude = 138.69
    tf.station_metadata.orientation.reference_frame = "geomagnetic"
    tf.period = per
    tf.impedance = z
    tf.impedance_error = 0.05 * np.abs(z) + 1e-6
    tf.tipper = np.tile(np.array([0.1 + 0.05j, -0.2 + 0.02j]), (per.size, 1))[:, None, :]
    tf.tipper_error = np.full((per.size, 1, 2), 0.01)
    P.set_declination(tf.station_metadata, 7.21, "IGRF-14", 2013.8)
    return tf


def block(text: str, key: str) -> np.ndarray:
    body = re.search(rf"^>{key} [^\n]*\n(.*?)(?=^>)", text, flags=re.S | re.M)
    return np.array([float(v) for v in body.group(1).split()]) if body else np.array([])


def info(text: str) -> list[str]:
    body = re.search(r"^>INFO[^\n]*\n(.*?)(?=^>)", text, flags=re.S | re.M)
    return [x.strip() for x in body.group(1).splitlines() if x.strip()] if body else []


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    # (1)
    try:
        r0 = P.zrot_rule_of(FakeSurvey({}))
        r1 = P.zrot_rule_of(FakeSurvey({"products": {"zrot": "zero"}}))
        try:
            P.zrot_rule_of(FakeSurvey({"products": {"zrot": "geographic"}}))
            r2 = "accepted"
        except ValueError:
            r2 = "refused"
        check((r0, r1, r2) == ("declination", "zero", "refused"), f"(1) zrot_rule_of: {r0}, {r1}, geographic {r2}")
    except AttributeError as exc:
        check(False, f"(1) {exc}")
        print(f"FAIL ({len(fails)})")
        return 1

    # (2) zero
    tf = small_tf()
    P.set_zrot_rule(tf, "zero")
    P.match_coordinate_system(tf)
    out = tmp / "zero.edi"
    P.write_edi(tf, out)
    text = out.read_text(encoding="utf-8")
    zrot, trot = block(text, "ZROT"), block(text, "TROT")
    check(zrot.size == 7 and np.all(zrot == 0) and trot.size == 7 and np.all(trot == 0),
          f"(2) zero: ZROT {zrot.tolist()}, TROT {trot.tolist()}")
    for line in ("COORDINATE_SYSTEM=geomagnetic", "DECLINATION=7.21", "DECLINATION.MODEL=IGRF-14",
                 "DECLINATION.EPOCH=2013.80"):
        check(re.search(rf"^\s*{re.escape(line)}\s*$", text, flags=re.M) is not None, f"(2) zero: HEAD {line}")
    lines = info(text)
    check("transfer_function.coordinate_system=geomagnetic" in lines, "(2) zero: INFO coordinate_system=geomagnetic")
    check(any("zrot_rule=zero" in x for x in lines), "(2) zero: INFO names the rule")
    rot = [x for x in lines if "rotation=" in x]
    check(len(rot) == 1 and "ZROT and TROT 0" in rot[0], f"(2) zero: one rotation line, ZROT and TROT 0: {rot}")
    bad = [x for x in lines if ("coordinate_system=" in x and "geomagnetic" not in x) or "state this azimuth" in x
           or "no declination stored" in x]
    check(not bad, f"(2) zero: no contradictory INFO line: {bad}")
    back = P.read_tf(out)
    check(abs(float(back.station_metadata.location.declination.value) - 7.21) < 1e-9,
          f"(2) zero: declination read back {back.station_metadata.location.declination.value}")

    # (3) default
    tf_d = small_tf()
    P.match_coordinate_system(tf_d)
    outd = tmp / "default.edi"
    P.write_edi(tf_d, outd)
    td = outd.read_text(encoding="utf-8")
    zd, trd = block(td, "ZROT"), block(td, "TROT")
    check(np.allclose(zd, 7.21) and np.allclose(trd, 7.21) and "zrot_rule" not in td,
          f"(3) default: ZROT {zd[:2].tolist()}.., TROT {trd[:2].tolist()}.., no rule line")

    # (4) byte identity on a Flinders product, and the stale frame lines
    strip = lambda p: [x for x in p.read_text(encoding="utf-8").splitlines() if not x.strip().startswith("FILEDATE=")]
    fresh = tmp / "fresh.edi"
    P.write_edi(tf_d, fresh)
    la, lb = strip(FROZEN_FRESH), strip(fresh)
    check(la == lb, f"(4) a fresh default product (the small TF), before vs after: {len(la)} vs {len(lb)} lines, "
                    f"{sum(x != y for x, y in zip(la, lb))} differ")
    b = tmp / "after.edi"
    P.write_edi(P.read_tf(FLINDERS), b)
    # what the code before also wrote when re-writing a read-back EDI: its frame lines a second time under the
    # bare keys the reader gives back (frame=, rotation=, rot_h=), now dropped (the contradiction of (4) b)
    stale = re.compile(r"^\s*transfer_function\.processing_parameters\.(frame|rotation|rot_h)=")
    la = [x for x in strip(FROZEN_EDI) if not stale.match(x)]
    lb = strip(b)
    check(la == lb, f"(4) Flinders product re-written, before (less its {len(strip(FROZEN_EDI)) - len(la)} repeated "
                    f"bare-key frame lines) vs after: {len(la)} vs {len(lb)} lines, "
                    f"{sum(x != y for x, y in zip(la, lb))} differ")
    tf_f = P.read_tf(FLINDERS)
    P.set_declination(tf_f.station_metadata, 7.21, "IGRF-14", 2013.8)
    c = tmp / "redecl.edi"
    P.write_edi(tf_f, c)
    stale = [x for x in info(c.read_text(encoding="utf-8")) if "no declination stored" in x or "declination is unknown" in x]
    check(not stale, f"(4) a read-back EDI re-written with a declination keeps no stale frame line: {stale}")

    # (5)
    rec = P.frame_record(tf)
    note = P.frame_note(tf)
    check(rec.get("zrot") == 0.0 and rec.get("zrot_rule") == "zero", f"(5) frame_record zrot {rec.get('zrot')}, "
                                                                     f"rule {rec.get('zrot_rule')}")
    check("ZROT and TROT are 0" in note, f"(5) frame_note: {note[:200]}")
    rec_d = P.frame_record(tf_d)
    check(rec_d.get("zrot") == 7.21 and rec_d.get("zrot_rule") == "declination", f"(5) default record {rec_d.get('zrot')}, "
                                                                                 f"{rec_d.get('zrot_rule')}")

    # (6) instruments
    folder = tmp / "survey"
    folder.mkdir()
    (folder / "instruments.csv").write_text(
        "site,logger_model,logger_serial,logger_doi,logger_doi_source,magnetometer_model,magnetometer_serial\n"
        "FR05,EDL PR6-24,123,10.82388/abcd,registry serial 123,Bartington Mag-03,2044\n"
        "FR06,EDL PR6-24,124,,,,\n", encoding="utf-8")
    sv = FakeSurvey({}, folder, {"FR05L": "FR05"})
    try:
        lines5 = P.instrument_info_lines(sv, "FR05")
        lines5l = P.instrument_info_lines(sv, "FR05L")
        lines6 = P.instrument_info_lines(sv, "FR06")
        none = P.instrument_info_lines(sv, "FR99")
    except AttributeError as exc:
        check(False, f"(6) {exc}")
        lines5 = lines5l = lines6 = none = []
    want = ["mt_workbench.instrument_logger=EDL PR6-24 123 10.82388/abcd (registry serial 123)",
            "mt_workbench.instrument_magnetometer=Bartington Mag-03 2044"]
    check(lines5 == want and lines5l == want, f"(6) FR05 and FR05L lines: {lines5} / {lines5l}")
    check(lines6 == ["mt_workbench.instrument_logger=EDL PR6-24 124"] and none == [],
          f"(6) FR06 (logger only) {lines6}; FR99 {none}")
    check(all(len(P.INFO_PREFIX + x) < P.INFO_MAX for x in lines5), "(6) lines under INFO_MAX")
    tf_i = small_tf()
    try:
        P.apply_instruments(tf_i, sv, "FR05L")
        r = tf_i.station_metadata.runs[0]
        mags = [ch for ch in r.channels if ch.component in ("hx", "hy", "hz")]
        check(r.data_logger.id == "123" and r.data_logger.model == "EDL PR6-24"
              and all(ch.sensor.id == "2044" and ch.sensor.model == "Bartington Mag-03" for ch in mags),
              f"(6) station metadata: logger {r.data_logger.id}/{r.data_logger.model}, sensors "
              f"{[(ch.component, ch.sensor.id) for ch in mags]}")
    except Exception as exc:
        check(False, f"(6) apply_instruments: {type(exc).__name__}: {exc}")
    tf_i.station_metadata.transfer_function.processing_parameters = list(lines5)
    oi = tmp / "inst.edi"
    P.write_edi(tf_i, oi)
    li = info(oi.read_text(encoding="utf-8"))
    check(any(x.endswith("mt_workbench.instrument_logger=EDL PR6-24 123 10.82388/abcd (registry serial 123)") for x in li),
          "(6) the logger line is in the EDI")
    pp = P.read_tf(oi).station_metadata.transfer_function.processing_parameters
    check(any(str(x).startswith("instrument_logger=") for x in pp), f"(6) read back: {[x for x in pp if 'instrument' in str(x)]}")

    # (7) merge keeps the rule
    spec = importlib.util.spec_from_file_location("merge_modes", REPO / "scripts" / "merge_modes.py")
    mm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mm)
    xy, yx = tmp / "xy.edi", tmp / "yx.edi"
    for p in (xy, yx):
        t = small_tf()
        P.set_zrot_rule(t, "zero")
        P.match_coordinate_system(t)
        P.write_edi(t, p)
    merged = tmp / "merged.edi"
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        status = mm.merge_files(merged, xy, yx, tag="t", force=True, argv=["x"])
    tm = merged.read_text(encoding="utf-8") if merged.exists() else ""
    zm = block(tm, "ZROT")
    check(status == 0 and zm.size and np.all(zm == 0) and "zrot_rule=zero" in tm,
          f"(7) merged: exit {status}, ZROT {zm.tolist()}, rule line {'zrot_rule=zero' in tm}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
