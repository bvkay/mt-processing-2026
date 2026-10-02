# -*- coding: utf-8 -*-
"""
Unit test for the parse cache of mt_workbench.masks and the GUI's MasksReader

A temporary masks.yaml with three sites is loaded through `load_masks`,
`remote_masks` and `load_history` while every `Path.read_text` of it is
counted. The GUI part runs `mt_workbench.gui.masks_reader.MasksReader` under
an offscreen QApplication on the same file.

Usage:
    python tests/masks_cache_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** a second `load_masks` (of the same site or another)
or a `remote_masks` of an unchanged masks.yaml reads the file again; a
change of the file's modification time (same size, new text) does not make
the next load read it and return the new text; `save_masks` from the
Cross-powers tab's path is not seen by the next load; the masks loaded
differ from `_ordered(yaml.safe_load(text)[site])`, the pure-Python parse
the loader used before; a rewrite at the same size within the same
mtime tick, just after a write, is not seen by the next load; a broken file is not raised as a YAMLError on every
load, or is read again while unchanged; `is_current` is not False before
the first parse and True after it; or `MasksReader.request()` answers True
before the parse, parses on the GUI thread, parses more than once for one
change, or reads the file again on a request after `ready`; or, on a file
it cannot read, starts a second read as the tabs ask again on `ready`.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _scratch import scratch_dir  # noqa: E402
from mt_workbench import masks  # noqa: E402
from mt_workbench.masks import _ordered, load_masks, masks_path, remote_masks, save_masks  # noqa: E402

SCRATCH = scratch_dir("masks_cache_unit")
TEXT = """# masks of three sites
A01:
- start: '2024-01-01T00:00:00Z'
  end: '2024-01-01T01:00:00Z'
  bands: all
  reason: aaaa
  found_by: time
- start: '2024-01-02T00:00:00Z'
  end: '2024-01-02T00:30:00.5Z'
  bands: [0.012345678901234, 3.5]
  reason: 'polar, 0.02 s'
  found_by: polar
  scope: both
  channels: [ey]
A02:
- start: 2024-01-03T00:00:00Z
  end: 2024-01-03T02:00:00Z
  reason: "quoted: colon"
  scope: remote
B01: []
"""
READS: list[str] = []
_read_text = Path.read_text


def _counting_read_text(self, *args, **kwargs):
    """Path.read_text, recording each read of a masks file."""
    if self.name in ("masks.yaml", "masks_history.yaml"):
        READS.append(self.name)
    return _read_text(self, *args, **kwargs)


Path.read_text = _counting_read_text


def fresh(name: str, text: str = TEXT, age_s: float = 3600.0) -> Path:
    """Write `text` as masks.yaml in a new folder, its mtime `age_s` ago; return the survey folder."""
    folder = SCRATCH / name
    folder.mkdir(parents=True, exist_ok=True)
    path = masks_path(folder)
    path.write_text(text, encoding="utf-8")
    then = time.time_ns() - int(age_s * 1e9)
    os.utime(path, ns=(then, then))
    return folder


def test_a_second_load_reads_nothing():
    survey = fresh("a")
    READS.clear()
    first = load_masks(survey, "A01")
    assert len(READS) == 1, READS
    again = load_masks(survey, "A01")
    other = load_masks(survey, "A02")
    remote = remote_masks(survey, "A02")
    assert len(READS) == 1, f"the unchanged file was read {len(READS)} times over four loads"
    assert first == again and len(first) == 2 and len(other) == 1 and len(remote) == 1, (first, other, remote)
    print(f"  four loads (A01 twice, A02, remote_masks A02) of an unchanged file: {len(READS)} read")


def test_b_mtime_change_rereads():
    survey = fresh("b")
    path = masks_path(survey)
    load_masks(survey, "A01")
    before = path.stat()
    path.write_text(TEXT.replace("aaaa", "bbbb"), encoding="utf-8")  # the same size
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    assert path.stat().st_size == before.st_size
    READS.clear()
    reasons = [m["reason"] for m in load_masks(survey, "A01")]
    assert READS == ["masks.yaml"], READS
    assert reasons[0] == "bbbb", reasons
    print(f"  same size, mtime +1 s: read again ({len(READS)}), reason {reasons[0]!r}")


def test_c_same_masks_as_pure_python():
    survey = fresh("c")
    document = yaml.safe_load(TEXT)
    for site in ("A01", "A02", "B01", "Z99"):
        assert load_masks(survey, site) == _ordered(document.get(site) or []), site
    print(f"  load_masks == _ordered(yaml.safe_load(text)[site]) for A01, A02, B01, Z99 "
          f"(loader {getattr(masks, '_LOADER', yaml.SafeLoader).__name__})")


def test_d_save_seen():
    survey = fresh("d")
    load_masks(survey, "A01")
    save_masks(survey, "A01", load_masks(survey, "A01")[:1])
    assert len(load_masks(survey, "A01")) == 1
    assert len(load_masks(survey, "A02")) == 1
    print("  save_masks then a load: A01 now 1 mask, A02 kept")


def test_h_same_tick_rewrite():
    survey = fresh("h", age_s=0.0)
    path = masks_path(survey)
    assert load_masks(survey, "A01")[0]["reason"] == "aaaa"
    stamp = path.stat()
    path.write_text(TEXT.replace("aaaa", "cccc"), encoding="utf-8")  # the same size, the same mtime
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert (path.stat().st_mtime_ns, path.stat().st_size) == (stamp.st_mtime_ns, stamp.st_size)
    reason = load_masks(survey, "A01")[0]["reason"]
    assert reason == "cccc", f"a rewrite at the same size and mtime, just after a write, was missed: {reason!r}"
    print(f"  a same-size rewrite in the same mtime tick, just after a write: seen ({reason!r})")


def test_e_error_kept():
    survey = fresh("e", "A01: [\n  - start: {\n")
    for k in range(2):
        try:
            load_masks(survey, "A01")
        except yaml.YAMLError:
            pass
        else:
            raise AssertionError(f"load {k + 1} of a broken file did not raise")
    assert READS[-1:] == ["masks.yaml"]
    READS.clear()
    try:
        load_masks(survey, "A01")
    except yaml.YAMLError:
        pass
    assert READS == [], READS
    print("  a broken file raises YAMLError on every load and is read once while unchanged")


def test_f_is_current():
    survey = fresh("f")
    path = masks_path(survey)
    assert not masks.is_current(path)
    load_masks(survey, "A01")
    assert masks.is_current(path)
    assert masks.is_current(SCRATCH / "f" / "absent.yaml")
    print("  is_current: False before the first parse, True after, True for an absent file")


def test_g_gui_reader():
    from PySide6.QtWidgets import QApplication

    from mt_workbench.gui import masks_reader

    app = QApplication.instance() or QApplication([])
    survey = fresh("g")
    threads = []
    parse = masks_reader.read_document

    def recording(path):
        threads.append(threading.current_thread() is threading.main_thread())
        return parse(path)

    masks_reader.read_document = recording
    reader = masks_reader.MasksReader(types.SimpleNamespace(survey_yaml=survey / "survey.yaml"))
    ready = []
    reader.ready.connect(lambda: ready.append(True))
    READS.clear()
    assert reader.request() is False, "the file is not parsed yet"
    assert reader.request() is False and reader.parses == 1, reader.parses
    end = time.time() + 10
    while not ready and time.time() < end:
        app.processEvents()
    assert ready, "ready was not emitted within 10 s"
    assert threads == [False], threads
    assert reader.request() is True and reader.parses == 1, reader.parses
    assert len(load_masks(survey, "A01")) == 2
    assert READS == ["masks.yaml"], READS
    masks_reader.read_document = parse
    print(f"  MasksReader: parsed once on a worker thread, then a request and a load read nothing ({READS})")


def test_i_gui_reader_unreadable_file():
    from PySide6.QtWidgets import QApplication

    from mt_workbench.gui import masks_reader

    app = QApplication.instance() or QApplication([])
    survey = fresh("i")
    parse = masks_reader.read_document

    def locked(path):
        raise PermissionError(13, "the file is locked", str(path))

    masks_reader.read_document = locked
    try:
        reader = masks_reader.MasksReader(types.SimpleNamespace(survey_yaml=survey / "survey.yaml"))
        ready = []
        reader.ready.connect(lambda: ready.append(reader.request()))  # as the tabs do on ready
        assert reader.request() is False
        end = time.time() + 5
        while time.time() < end and len(ready) < 3:
            app.processEvents()
        assert reader.parses == 1 and ready[:1] == [True], (reader.parses, ready)
    finally:
        masks_reader.read_document = parse
    print(f"  MasksReader on a file it cannot read: one attempt, then the tabs load it (and report the error); "
          f"attempts {reader.parses}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  masks_cache_unit ({len(tests)} tests)")
