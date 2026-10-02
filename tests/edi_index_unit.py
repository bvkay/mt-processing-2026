# -*- coding: utf-8 -*-
"""
Unit test for the View EDIs list's product index (mt_workbench.tf_index, gui/tabs/edis.py)

A temporary workspace holds a tf folder of 300 fake products: an EDI and
its `.json` sidecar each, every third a MANTLE run with a fine-grid EDI as
well (400 rows). `EdiTab.reload` runs under an offscreen QApplication while
every open of a sidecar is counted. No archive is read.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/edi_index_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** two reloads open any sidecar more than once between
them; a row's label differs from the one `mantle_products.describe` gives
the same EDI from its sidecar; a sidecar rewritten with another engine
(new mtime) is not read again and relabelled at the next reload, or that
reload opens any other sidecar; `tf/index.json` is not written; a fresh
start (the in-process entries dropped) reading the index opens any
sidecar; or `tf_index.add`, which `products.write_products` calls as a
product lands, does not record a new product's engine in the index.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.gui import mantle_products  # noqa: E402
from mt_workbench.gui.app import State  # noqa: E402
from mt_workbench.gui.tabs.edis import EdiTab  # noqa: E402

WORK = scratch_dir("edi_index_unit") / "workspace"
TF = WORK / "tf"
N = 300
OPENED: list[str] = []
_open, _io_open = builtins.open, io.open


def _counting(file, *args, **kwargs):
    """open(), recording each open of a sidecar in the test's tf folder."""
    name = str(file)
    if name.endswith(".json") and not name.endswith("index.json") and str(TF) in os.path.abspath(name):
        OPENED.append(Path(name).name)
    return _open(file, *args, **kwargs)


builtins.open = io.open = _counting


def make_products() -> list[str]:
    """Write N fake products into TF; return their stems."""
    if WORK.exists():
        shutil.rmtree(WORK)
    TF.mkdir(parents=True)
    stems = []
    for i in range(N):
        stem = f"S{i:03d}_rr-R01_20261003-{i // 60:02d}{i % 60:02d}"
        mantle = i % 3 == 0
        (TF / f"{stem}.edi").write_text("fake EDI\n", encoding="utf-8")
        sidecar = {"edi": f"{stem}.edi", "padding": "x" * 2000}
        if mantle:
            sidecar.update(engine="mantle", mantle_fine_edi=f"{stem}_fine.edi")
            (TF / f"{stem}_fine.edi").write_text("fake EDI\n", encoding="utf-8")
        (TF / f"{stem}.json").write_text(json.dumps(sidecar), encoding="utf-8")
        stems.append(stem)
    return stems


def labels(tab) -> dict[str, str]:
    """Return {EDI file name: row label} of the processed group."""
    top = tab.tree.topLevelItem(0)
    return {Path(top.child(r).data(0, 0x0100)).name: top.child(r).text(0) for r in range(top.childCount())}


def main() -> int:
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    app = QApplication.instance() or QApplication([])
    stems = make_products()
    state = State()
    state.survey = types.SimpleNamespace(workspace=WORK, config={})
    tab = EdiTab(state)

    OPENED.clear()
    t = time.perf_counter()
    tab.reload()
    first = time.perf_counter() - t
    t = time.perf_counter()
    tab.reload()
    second = time.perf_counter() - t
    counts = {name: OPENED.count(name) for name in set(OPENED)}
    shown = labels(tab)
    assert len(shown) == N + N // 3, len(shown)
    assert max(counts.values(), default=0) <= 1, sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    print(f"  two reloads of {len(shown)} rows: {len(OPENED)} sidecar opens, at most {max(counts.values(), default=0)} "
          f"per sidecar ({first:.3f} s, then {second:.3f} s)")

    OPENED.clear()
    truth = {p.name: mantle_products.describe(p) for p in TF.glob("*.edi")}
    OPENED.clear()
    for name, label in shown.items():
        assert label.endswith(truth[name]) and (truth[name] or "[" not in label), (name, label, truth[name])
    assert sum("[mantle fine grid]" in v for v in shown.values()) == N // 3
    print(f"  every label as describe() gives it: {sum('[aurora]' in v for v in shown.values())} aurora, "
          f"{sum(v.endswith('[mantle]') for v in shown.values())} mantle, "
          f"{sum('fine grid' in v for v in shown.values())} fine grid")

    assert (TF / "index.json").exists(), "tf/index.json was not written"
    path = TF / f"{stems[1]}.json"
    status = path.stat()
    path.write_text(json.dumps({"edi": f"{stems[1]}.edi", "engine": "mantle"}), encoding="utf-8")
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000_000))
    OPENED.clear()
    tab.reload()
    assert OPENED == [path.name], OPENED
    assert labels(tab)[f"{stems[1]}.edi"].endswith("[mantle]"), labels(tab)[f"{stems[1]}.edi"]
    print(f"  {path.name} rewritten as mantle: that sidecar alone read again ({OPENED}), relabelled")

    from mt_workbench import tf_index

    tf_index._KEPT.clear()
    tf_index._LOADED.clear()
    OPENED.clear()
    tab.reload()
    assert OPENED == [], OPENED[:5]
    print("  a fresh start from tf/index.json: no sidecar opened")

    stem = "T999_rr-R01_20261003-2359"
    (TF / f"{stem}.edi").write_text("fake EDI\n", encoding="utf-8")
    (TF / f"{stem}.json").write_text(json.dumps({"engine": "mantle"}), encoding="utf-8")
    tf_index.add(TF / f"{stem}.edi")
    entry = json.loads((TF / "index.json").read_text(encoding="utf-8"))["products"].get(stem)
    assert entry is not None and entry["engine"] == "mantle", entry
    print(f"  tf_index.add (write_products) records a landed product: {entry['engine']}")

    tab.close()
    print("\nPASS  edi_index_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
