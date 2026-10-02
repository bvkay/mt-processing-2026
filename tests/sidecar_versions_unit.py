# -*- coding: utf-8 -*-
"""
Unit test for the package origins in scripts/process_rr.py's sidecar

`versions()` (the sidecar's `versions` block, as `build_sidecar` stores it)
and `installed_origin` on the installed stack and on two stand-in
distributions in a temporary folder: a fork installed from a version-control
URL with a commit, and a stock install from an index.

Usage:
    python tests/sidecar_versions_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the sidecar `build_sidecar` makes for the Curnamona
D02 rr E08 pair lacks `versions.installed` with aurora, mth5, mt_timeseries,
mt_metadata and mt_io each carrying version, direct_url, editable, commit,
record_sha256, init_path and init_sha256; for an installed package, its
direct_url differs from its dist-info `direct_url.json` read here, its
record_sha256 from the SHA-256 of its `RECORD` file read here, or its
init_sha256 from the SHA-256 of the `__init__.py` the imported module was
loaded from; the stand-in fork does not report its URL and commit, the
stand-in stock install reports a URL or a commit, the two report the same
record_sha256, or a second install of the fork with one file's hash changed
in its RECORD keeps the first record_sha256; a missing package is not
"not installed"; or the sidecar does not round-trip as JSON.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
SCRIPT = REPO / "scripts" / "process_rr.py"
SURVEY = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
STACK = ("aurora", "mth5", "mt_timeseries", "mt_metadata", "mt_io")
KEYS = {"version", "direct_url", "editable", "commit", "record_sha256", "init_path", "init_sha256"}


def load_process_rr():
    """Import the script as a module."""
    spec = importlib.util.spec_from_file_location("process_rr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fake_dist(root: Path, name: str, record_hash: str, direct: dict | None) -> None:
    """Write a package `name` and its dist-info (METADATA, RECORD, optional direct_url.json) under root."""
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'"""{name}"""\n__version__ = "1.0.0"\n', encoding="utf-8")
    info = root / f"{name}-1.0.0.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0.0\n", encoding="utf-8")
    (info / "RECORD").write_text(f"{name}/__init__.py,sha256={record_hash},40\n"
                                 f"{name}-1.0.0.dist-info/METADATA,,\n", encoding="utf-8")
    if direct is not None:
        (info / "direct_url.json").write_text(json.dumps(direct), encoding="utf-8")


def check_installed(process_rr) -> None:
    started = dt.datetime(2026, 10, 3, 6, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    args = process_rr.build_parser().parse_args(
        [str(SURVEY), "D02", "E08", "2021-06-29 12:55", "2021-06-29 14:55", "--tag", "versions-test"])
    res = process_rr.resolve(args, started)
    edi = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
    quadrant = {"pmin": 0.1, "pmax": 10.0, "xy": 45.0, "yx": -135.0, "xy_ok": True, "yx_ok": True}
    sidecar = process_rr.build_sidecar(res, args, started, started, edi, edi.with_suffix(".png"), quadrant, [])
    sidecar = json.loads(json.dumps(sidecar, default=str))
    installed = sidecar["versions"].get("installed")
    assert isinstance(installed, dict) and set(installed) == set(STACK), sidecar["versions"]
    for name in STACK:
        rec = installed[name]
        assert set(rec) == KEYS, (name, sorted(rec))
        dist = importlib.metadata.distribution(name)
        assert rec["version"] == dist.version == sidecar["versions"][name], (name, rec["version"])
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        assert rec["direct_url"] == direct.get("url"), (name, rec["direct_url"], direct)
        infos = sorted(Path(dist.locate_file("")).glob(f"{name}-*.dist-info"))
        assert len(infos) == 1 and (infos[0] / "RECORD").is_file(), (name, infos)
        record = (infos[0] / "RECORD").read_bytes().replace(b"\r\n", b"\n")
        assert rec["record_sha256"] == sha(record), (name, "record_sha256")
        module = importlib.import_module(name)
        assert Path(rec["init_path"]) == Path(module.__file__), (name, rec["init_path"], module.__file__)
        assert rec["init_sha256"] == sha(Path(module.__file__).read_bytes()), (name, "init_sha256")
        print(f"  {name} {rec['version']}: {rec['direct_url']}, commit {rec['commit']}, "
              f"RECORD {rec['record_sha256'][:12]}, __init__ {rec['init_sha256'][:12]}")


def check_stand_ins(process_rr) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fork_url = "file:///D:/clones/fakefork"
        commit = "0123456789abcdef0123456789abcdef01234567"
        fake_dist(root / "a", "fakefork", "A" * 43, {"url": fork_url, "vcs_info": {"vcs": "git", "commit_id": commit}})
        fake_dist(root / "b", "fakestock", "A" * 43, None)
        fake_dist(root / "c", "fakefork2", "A" * 43, {"url": fork_url, "dir_info": {}})
        fake_dist(root / "d", "fakefork2b", "B" * 43, {"url": fork_url, "dir_info": {}})
        sys.path[:0] = [str(root / k) for k in "abcd"]
        importlib.invalidate_caches()
        try:
            fork = process_rr.installed_origin("fakefork")
            stock = process_rr.installed_origin("fakestock")
            first = process_rr.installed_origin("fakefork2")
            second = process_rr.installed_origin("fakefork2b")
            missing = process_rr.installed_origin("no_such_package_here")
        finally:
            del sys.path[:4]
    assert fork["direct_url"] == fork_url and fork["commit"] == commit and fork["editable"] is False, fork
    assert stock["direct_url"] is None and stock["commit"] is None, stock
    assert fork["version"] == stock["version"] == "1.0.0", (fork, stock)
    assert fork["init_sha256"] and fork["init_sha256"] != stock["init_sha256"], (fork, stock)
    # the same RECORD lines but the package name: fork and stock differ; one file hash changed: differs
    assert first["record_sha256"] != second["record_sha256"], (first, second)
    assert first["commit"] is None and first["direct_url"] == fork_url, first
    assert missing["version"] == "not installed" and missing["init_sha256"] is None, missing
    print(f"  stand-ins: fork {fork['direct_url']} @ {fork['commit'][:7]}; stock direct_url None; the same "
          f"version 1.0.0 told apart; one RECORD hash changed -> record_sha256 {first['record_sha256'][:8]} -> "
          f"{second['record_sha256'][:8]}; missing -> not installed")


def main() -> int:
    """Run every check and return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    process_rr = load_process_rr()
    check_installed(process_rr)
    check_stand_ins(process_rr)
    print("\nPASS  sidecar_versions_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
