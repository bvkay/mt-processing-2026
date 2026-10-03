# -*- coding: utf-8 -*-
"""
Unit test for the imports of mt_workbench.compare

Each check runs in a fresh Python process with this tree's src first on the
path, so the modules a statement loads are its own, and without MPLBACKEND,
so a backend set outside cannot stand in for the one the code selects.

Usage:
    python tests/compare_imports_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `import mt_workbench.compare` (or
`import mt_workbench.quality`, which imports it) loads
mt_metadata.transfer_functions or matplotlib; the control, the same process
importing mt_metadata's TF itself, is not seen to load it; `rho_phi` and
`phase_quadrants` on tests/fixtures/aurora_stock/stock_default.edi called
after that import do not give the periods, rho and phase of a TF read here
with mt_metadata (0.2 T |Z|^2, the angle of Z) and the same quadrant result
for the path as for that TF object; or `plot_comparison` with
`out_png` does not write the PNG on the Agg backend and close its figure,
both in a fresh process and in one where matplotlib.pyplot was imported
first (as mt_metadata's filter plotting helpers import it in process_rr.py);
or `import process_rr` does not import matplotlib.pyplot, or the backend
recorded at the moment it is first imported (a `sys.meta_path` finder in
the child) is not Agg: process_rr.py must select Agg before mth5 and mt_io
import pyplot, and selecting it only after them fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDI = REPO / "tests" / "fixtures" / "aurora_stock" / "stock_default.edi"
WATCH = ("mt_metadata.transfer_functions", "mt_metadata", "matplotlib", "matplotlib.pyplot")


def child(code: str) -> dict:
    """Run `code` in a fresh process with this tree's src first and no MPLBACKEND; return the JSON it prints last."""
    head = f"import sys, json; sys.path.insert(0, {str(REPO / 'src')!r}); "
    env = {k: v for k, v in os.environ.items() if k.upper() != "MPLBACKEND"}
    res = subprocess.run([sys.executable, "-c", head + code], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr[-2000:]
    return json.loads(res.stdout.strip().splitlines()[-1])


def loaded_after(statement: str) -> dict:
    return child(f"{statement}; print(json.dumps({{m: m in sys.modules for m in {WATCH!r}}}))")


def check_imports() -> None:
    for statement in ("import mt_workbench.compare", "import mt_workbench.quality"):
        got = loaded_after(statement)
        assert not got["mt_metadata.transfer_functions"], f"{statement} loads mt_metadata.transfer_functions: {got}"
        assert not got["matplotlib"], f"{statement} loads matplotlib: {got}"
        print(f"{statement}: loads none of {', '.join(m for m in WATCH if not got[m])}")
    control = loaded_after("import mt_workbench.compare; from mt_metadata.transfer_functions.core import TF")
    assert control["mt_metadata.transfer_functions"], f"control: the TF import not seen: {control}"
    print("control: importing mt_metadata's TF as well is seen (mt_metadata.transfer_functions loaded)")


def check_rho_phi() -> None:
    code = (
        "import numpy as np; from mt_workbench.compare import rho_phi, phase_quadrants; "
        f"p, rho, phi, re, pe = rho_phi({str(EDI)!r}); q = phase_quadrants({str(EDI)!r}); "
        "from mt_metadata.transfer_functions.core import TF; "
        f"tf = TF(fn={str(EDI)!r}); tf.read(); z = np.asarray(tf.impedance.data); T = np.asarray(tf.period, float); "
        "print(json.dumps({'n': len(p), 'period': bool(np.array_equal(p, T)), "
        "'rho': bool(np.array_equal(rho, 0.2 * T[:, None, None] * np.abs(z) ** 2)), "
        "'phi': bool(np.array_equal(phi, np.degrees(np.angle(z)))), 'xy': q['xy'], 'yx': q['yx'], "
        "'same_quadrants': q == phase_quadrants(tf)}))"
    )
    got = child(code)
    assert got["n"] > 10 and got["period"] and got["rho"] and got["phi"], got
    assert got["same_quadrants"], got
    print(f"rho_phi on {EDI.name}: {got['n']} periods, rho and phase equal to mt_metadata's TF read here; "
          f"phase_quadrants of the path == of the TF (median xy {got['xy']:.1f}, yx {got['yx']:.1f} deg)")


def check_plot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for name, first in (("fresh", ""), ("pyplot first", "import matplotlib.pyplot; ")):
            png = Path(tmp) / f"{name.replace(' ', '_')}.png"
            code = (
                f"{first}from mt_workbench.compare import plot_comparison; "
                f"plot_comparison({str(EDI)!r}, baseline={str(EDI)!r}, title='t', out_png={str(png)!r}); "
                "import matplotlib, matplotlib.pyplot as plt; "
                "print(json.dumps({'backend': matplotlib.get_backend().lower(), 'open': plt.get_fignums()}))"
            )
            got = child(code)
            assert got["backend"] == "agg" and got["open"] == [], (name, got)
            assert png.is_file() and png.stat().st_size > 10_000, (name, png)
            print(f"plot_comparison ({name}): {png.stat().st_size} B PNG on {got['backend']}, no figure left open")


def check_process_rr_backend() -> None:
    # the finder records the raw rcParams backend (no auto-resolution) when
    # matplotlib.pyplot is first looked for, before pyplot's own import runs
    code = (
        f"sys.path.insert(0, {str(REPO / 'scripts')!r}); seen = {{}}\n"
        "class PyplotWatch:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'matplotlib.pyplot' and 'backend' not in seen:\n"
        "            import matplotlib\n"
        "            seen['backend'] = str(dict.__getitem__(matplotlib.rcParams, 'backend'))\n"
        "        return None\n"
        "sys.meta_path.insert(0, PyplotWatch())\n"
        "import process_rr, matplotlib\n"
        "print(json.dumps({'at_pyplot': seen.get('backend'), 'pyplot': 'matplotlib.pyplot' in sys.modules, "
        "'after': str(dict.__getitem__(matplotlib.rcParams, 'backend'))}))"
    )
    got = child(code)
    assert got["pyplot"] and got["at_pyplot"] is not None, \
        f"import process_rr: matplotlib.pyplot not imported, the check sees nothing: {got}"
    assert got["at_pyplot"].lower() == "agg", \
        f"import process_rr: pyplot imported with backend {got['at_pyplot']!r}, not Agg (after the import: {got['after']!r})"
    print(f"import process_rr: matplotlib.pyplot imported with the backend {got['at_pyplot']!r} already selected")


def main() -> int:
    """Run every check and return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    check_imports()
    check_rho_phi()
    check_plot()
    check_process_rr_backend()
    print("\nPASS  compare_imports_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
