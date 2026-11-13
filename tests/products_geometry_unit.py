# -*- coding: utf-8 -*-
"""
Unit test for the channel geometry of mt_workbench.products' EDI writer (docs/workbench_issues.md 52)

An MTH5 archive of one station is written with mth5's own API: ex 48.5 m at
0 deg, ey 46.5 m at 90 deg, hx 0, hy 90, hz vertical (the archive form of
an EDL site after ingest, TAS100's lengths). A TF is built as aurora hands
it to the writer: its run's channels carry no geometry (azimuth 0, dipole
0). The EDI is written through `write_edi` with `archive_geometry` of the
archive, and read as text and back through `read_tf`.

Usage:
    python tests/products_geometry_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - `archive_geometry` does not read ex 48.5 m at 0 deg and ey 46.5 m at
    90 deg, hy at 90 deg and hz at tilt 90;
  - the EDI written with that geometry lacks, on its EMEAS lines, ex with
    X2=48.50 and AZM=0.00 and ey with Y2=46.50 and AZM=90.00 (the electrode
    coordinates from the centre), or, on its HMEAS lines, hx AZM=0.00, hy
    AZM=90.00 and hz DIP=90.00;
  - the TF read back from it does not carry those azimuths and lengths;
  - its impedance and tipper differ from the TF written by more than the
    EDI's text precision (1e-6 relative of each row): the geometry must not
    touch the data;
  - the TF handed to `write_edi` is changed by the call;
  - the control, the same TF written without geometry (the writer's
    behaviour before the fix), carries the lengths or ey/hy at 90 deg: then
    the check above could not fail.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mt_metadata.timeseries import Electric, Magnetic, Run  # noqa: E402
from mt_metadata.transfer_functions.core import TF  # noqa: E402
from mth5.mth5 import MTH5  # noqa: E402

from mt_workbench import products  # noqa: E402


def write_archive(path: Path) -> None:
    """Write a one-station archive with the EDL site's channel geometry."""
    m = MTH5(file_version="0.2.0")
    m.open_mth5(str(path), "w")
    try:
        survey = m.add_survey("unit")
        station = m.add_station("T001", survey="unit")
        run = station.add_run("sr10_0001")
        n = 600
        rng = np.random.default_rng(1)
        for comp, kind, az, tilt, length in (("ex", "electric", 0.0, 0.0, 48.5), ("ey", "electric", 90.0, 0.0, 46.5),
                                             ("hx", "magnetic", 0.0, 0.0, None), ("hy", "magnetic", 90.0, 0.0, None),
                                             ("hz", "magnetic", 0.0, 90.0, None)):
            meta = Electric(component=comp) if kind == "electric" else Magnetic(component=comp)
            meta.measurement_azimuth = az
            meta.measurement_tilt = tilt
            meta.sample_rate = 10.0
            meta.time_period.start = "2016-01-22T04:00:00+00:00"
            if length is not None:
                meta.dipole_length = length
            run.add_channel(comp, kind, rng.normal(size=n), channel_metadata=meta)
    finally:
        m.close_mth5()


def aurora_like_tf() -> TF:
    """A TF whose run's channels carry no geometry, as aurora returns it."""
    tf = TF()
    tf.station_metadata.id = "T001"
    tf.station_metadata.location.latitude = -40.95
    tf.station_metadata.location.longitude = 144.92
    tf.survey_metadata.id = "unit"
    period = np.logspace(0, 3, 7)
    rng = np.random.default_rng(2)
    z = rng.normal(size=(7, 2, 2)) + 1j * rng.normal(size=(7, 2, 2))
    z[:, 0, 1] += 3 + 3j
    z[:, 1, 0] -= 3 + 3j
    tf.period = period
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    t = (rng.normal(size=(7, 1, 2)) + 1j * rng.normal(size=(7, 1, 2))) * 0.1
    tf.tipper = t
    tf.tipper_error = np.abs(t) * 0.1 + 0.01
    run = Run(id="sr10_0001")
    for comp in ("ex", "ey"):
        run.add_channel(Electric(component=comp))
    for comp in ("hx", "hy", "hz"):
        run.add_channel(Magnetic(component=comp))
    tf.station_metadata.add_run(run)
    return tf


def meas_lines(text: str) -> dict[str, str]:
    """The EMEAS and HMEAS lines of an EDI, by channel type."""
    out = {}
    for line in text.splitlines():
        m = re.match(r">([EH])MEAS .*CHTYPE=(\w+)", line.strip())
        if m:
            out[m.group(2).lower()] = line.strip()
    return out


def field(line: str, key: str) -> float:
    """A numeric field of a measurement line."""
    return float(re.search(rf"\b{key}=([-+0-9.eE]+)", line).group(1))


def main() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        arch = tmp / "T001.h5"
        write_archive(arch)
        geo = products.archive_geometry(arch)
        exp = {"ex": (0.0, 48.5), "ey": (90.0, 46.5)}
        for comp, (az, length) in exp.items():
            if abs(geo[comp]["azimuth"] - az) > 1e-9 or abs(geo[comp]["dipole_length"] - length) > 1e-9:
                fails.append(f"archive_geometry {comp}: {geo[comp]}")
        if abs(geo["hy"]["azimuth"] - 90) > 1e-9 or abs(geo["hz"]["tilt"] - 90) > 1e-9:
            fails.append(f"archive_geometry hy/hz: {geo['hy']}, {geo['hz']}")

        tf = aurora_like_tf()
        before = repr(tf.station_metadata.runs[0].channels[1].measurement_azimuth)
        fixed, control = tmp / "fixed.edi", tmp / "control.edi"
        products.write_edi(tf, fixed, geometry=geo)
        if repr(tf.station_metadata.runs[0].channels[1].measurement_azimuth) != before:
            fails.append("write_edi changed the TF handed to it")
        products.write_edi(tf, control)
        lines = meas_lines(fixed.read_text(encoding="latin-1"))
        want = {"ex": {"X2": 48.5, "Y2": 0.0, "AZM": 0.0}, "ey": {"X2": 0.0, "Y2": 46.5, "AZM": 90.0},
                "hx": {"AZM": 0.0}, "hy": {"AZM": 90.0}, "hz": {"DIP": 90.0}}
        for comp, keys in want.items():
            if comp not in lines:
                fails.append(f"no measurement line for {comp}")
                continue
            for key, value in keys.items():
                got = field(lines[comp], key)
                if abs(got - value) > 0.005:
                    fails.append(f"{comp} {key}={got}, wanted {value}: {lines[comp]}")
        back = products.read_tf(fixed)
        chans = {c.component: c for c in back.station_metadata.runs[0].channels}
        if abs(float(chans["ey"].measurement_azimuth) - 90) > 1e-6 or abs(float(chans["hy"].measurement_azimuth) - 90) > 1e-6:
            fails.append("read back: ey or hy not at 90 deg")
        for comp, length in (("ex", 48.5), ("ey", 46.5)):
            ch = chans[comp]
            got = float(np.hypot(ch.positive.x2 - ch.negative.x, ch.positive.y2 - ch.negative.y))
            if abs(got - length) > 0.01:
                fails.append(f"read back: {comp} electrode separation {got}, wanted {length}")
        for name in ("impedance", "tipper"):
            a = np.asarray(getattr(tf, name).data)
            b = np.asarray(getattr(back, name).data)
            scale = np.abs(a).max(axis=-1, keepdims=True)
            d = float(np.max(np.abs(a - b) / scale))
            if d > 1e-6:
                fails.append(f"{name} changed by the geometry: {d:.2e}")
        ctrl = meas_lines(control.read_text(encoding="latin-1"))
        if (abs(field(ctrl["ex"], "X2") - 48.5) < 0.005 or abs(field(ctrl["ey"], "AZM") - 90) < 0.005
                or abs(field(ctrl["hy"], "AZM") - 90) < 0.005):
            fails.append(f"control written without geometry carries it: the check cannot fail ({ctrl})")
        print("fixed:", *lines.values(), sep="\n  ")
        print("control:", *ctrl.values(), sep="\n  ")
    for line in fails:
        print(f"FAIL: {line}")
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
