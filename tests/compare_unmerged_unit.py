# -*- coding: utf-8 -*-
"""
Unit test for scripts/compare_unmerged.py

Checks the site-name normalisation of compare_unmerged.py and runs the script
end to end on synthetic lemimt EDIs written with mt_metadata's `TF`,
including a corrupt file that must be skipped. Runs without Qt.

Usage:
    python tests/compare_unmerged_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) site-name normalisation does not treat "D07", "D7", "d07" and "D007" as
    the same site "D7", or "R06" as "R6" -- lemimt drops leading zeros after
    the letter(s), the survey convention keeps them, and matching must be
    case-insensitive;

(2) given two tiny synthetic lemimt EDIs in one folder -- each built with
    `mt_metadata`'s own `TF` (three periods, a 2x2 impedance), written as
    ``MT-D7_RR-D9_1000Hz_1.edi`` and ``MT-D7_RR-D9_125Hz.edi`` -- plus an
    "aurora" EDI that is an identical copy of the 1000 Hz file, running
    the script (site ``D07``, so normalisation is exercised too) does not
    exit 0, does not write the output PNG, or does not print a table whose
    1000 Hz row has a median absolute log10 rho difference below 1e-6 (the
    two files are identical, so interpolating aurora onto lemimt's own
    periods must reproduce them almost exactly);

(3) a third, corrupt file that still matches the naming pattern
    (``MT-D7_RR-D9_63Hz.edi``, garbage text) is not skipped with a printed
    warning naming it -- the run must still exit 0 and still produce the
    PNG and table from the two good files.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
SCRIPT = REPO / "scripts" / "compare_unmerged.py"


def _load_script():
    """Import scripts/compare_unmerged.py as a module."""
    spec = importlib.util.spec_from_file_location("compare_unmerged", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_site_name_normalisation() -> None:
    cu = _load_script()
    assert cu.normalise_site("D07") == "D7"
    assert cu.normalise_site("D7") == "D7"
    assert cu.normalise_site("d07") == "D7"
    assert cu.normalise_site("D007") == "D7"
    assert cu.normalise_site("R06") == "R6"
    print("  D07 == D7 == d07 == D007 -> D7; R06 -> R6")


def _write_tf(out_path: Path, station: str, periods, xy, yx):
    """Write a small EDI with a constant off-diagonal impedance.

    Args:
        out_path (Path): EDI to write.
        station (str): Station name.
        periods (list[float]): Periods in seconds.
        xy (complex): Zxy at every period.
        yx (complex): Zyx at every period.

    Returns:
        Path: `out_path`.
    """
    import numpy as np
    from mt_metadata.transfer_functions.core import TF

    period = np.asarray(periods, dtype=float)
    z = np.zeros((period.size, 2, 2), dtype=complex)
    z[:, 0, 1] = xy
    z[:, 1, 0] = yx

    tf = TF()
    tf.station = station
    tf.survey_metadata.id = "test"
    tf.station_metadata.location.latitude = -31.0
    tf.station_metadata.location.longitude = -7.0
    tf.station_metadata.location.elevation = 1200.0
    tf.period = period
    tf.impedance = z
    tf.impedance_error = np.abs(z) * 0.05
    tf.write(fn=out_path)
    return out_path


def test_end_to_end_png_table_and_skip() -> None:
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        unmerged = tmp / "unmerged"
        unmerged.mkdir()

        f1000 = _write_tf(unmerged / "MT-D7_RR-D9_1000Hz_1.edi", "D7",
                           [0.001, 0.002, 0.004], 10 + 10j, -8 - 6j)
        _write_tf(unmerged / "MT-D7_RR-D9_125Hz.edi", "D7",
                  [0.05, 0.1, 0.2], 3 + 4j, -5 - 2j)
        corrupt = unmerged / "MT-D7_RR-D9_63Hz.edi"
        corrupt.write_text("this is not a real EDI file\njust garbage\n")

        aurora = tmp / "aurora.edi"
        shutil.copyfile(f1000, aurora)

        out_png = tmp / "compare.png"
        argv = [sys.executable, str(SCRIPT), str(aurora), str(unmerged), "D07",
                "--remote", "D9", "--out", str(out_png)]
        done = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
        assert done.returncode == 0, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"

        assert out_png.exists(), f"no PNG written: {out_png}\n{done.stdout}\n{done.stderr}"
        assert out_png.stat().st_size > 0, "PNG is empty"
        print(f"  exit 0, PNG written: {out_png.name} ({out_png.stat().st_size} bytes)")

        # loguru's default sink is stderr, but mt_metadata reconfigures the
        # (global) logger on import, so check both streams rather than assume
        combined = (done.stdout + "\n" + done.stderr).splitlines()
        warned = [ln for ln in combined if "MT-D7_RR-D9_63Hz.edi" in ln]
        assert warned, f"no warning naming the corrupt file\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}"
        print(f"  corrupt file skipped with a warning: {warned[0].strip()}")

        rows = [ln for ln in done.stdout.splitlines() if ln.strip().startswith("1000Hz")]
        assert rows, f"no 1000Hz row in the table\n{done.stdout}"
        fields = rows[0].split()
        # header: rate | n files | n(xy) | d log10 rho (xy) | d phase deg (xy) | n(yx) | d log10 rho (yx) | d phase deg (yx)
        rho_diff_xy = float(fields[3])
        assert rho_diff_xy < 1e-6, f"1000Hz median |d log10 rho| (xy) too large: {rho_diff_xy}\n{done.stdout}"
        print(f"  1000Hz row: median |d log10 rho| (xy) = {rho_diff_xy:.2e} (< 1e-6, aurora == lemimt here)")


def main() -> int:
    """Print the test contract, run every test_* function and return 0."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  compare_unmerged_unit ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
