# -*- coding: utf-8 -*-
"""
Unit test for a variant rebuild while the variant is open in another program

**This test fails if** a rebuild of a variant that another process holds open
(h5py, mode "r", as the GUI holds it) leaves its ``.part`` file behind,
changes or deletes the variant on disk, or ends in anything but one line that
names the file and says it is open in another program: in
`mt_workbench.ingest.build_variant`, and in `scripts/ingest_site.py <survey>
<site> --variant --force`, which must exit 1 with that line and no traceback;
or if the script's cleanup after a rebuild that fails for any other reason
deletes the current variant instead of the ``.part`` file; or if, once the
hold is released, the same rebuild does not succeed (`variant_ready`).

Control (must fail, or the test stops): with the hold in place,
`os.replace` of a scratch file onto a held copy of the variant must raise
PermissionError, so the hold is real.

The survey is written into a scratch folder: one site, VH01, at 10 Hz with a
5 Hz notch declared in filters.yaml, its raw folder holding one empty B423
file named by its epoch (enough for `Survey.site_dirs`; `--variant` reads no
raw file) and its raw archive written directly with the mth5 API
(`ingest_unit._write_raw_archive`, 2000 samples of hx and hy). The holder is a
second Python process that opens the variant and the copy with
``h5py.File(path, "r")``, prints "HELD 2" and waits for its stdin to close.
The script runs with the interpreter MT_WORKBENCH_PYTHON names (this one by
default). The other-failure case replaces the script's `build_variant` in
this process with a stand-in that writes a ``.part`` file and raises.

Usage:
    python tests/variant_held_open_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from _scratch import scratch_dir  # noqa: E402
from ingest_unit import _write_raw_archive  # noqa: E402
from mt_workbench.ingest import build_variant, default_archive_path, variant_path, variant_ready  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "ingest_site.py"
PY = os.environ.get("MT_WORKBENCH_PYTHON", sys.executable)
SCRATCH = scratch_dir("variant_held_open_unit")
SITE, FS, EPOCH = "VH01", 10.0, 1577836800
NOTCH = [{"notch": {"f0": 5.0, "harmonics": 2, "q": 10.0, "passes": 1}}]
HOLDER = ("import sys, h5py\n"
          "files = [h5py.File(p, 'r') for p in sys.argv[1:]]\n"
          "print(f'HELD {len(files)}', flush=True)\n"
          "sys.stdin.read()\n"
          "for f in files:\n"
          "    f.close()\n")


def make_survey() -> Path:
    """Write the one-site survey of the module docstring and its raw archive; return survey.yaml."""
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    (root / "raw" / SITE).mkdir(parents=True)
    (root / "raw" / SITE / f"{EPOCH}.B423").write_bytes(b"")
    config = {"name": "held_open", "instrument": "lemi423", "sample_rate": FS,
              "data_root": str(root / "raw"), "workspace": str(root / "work"), "sites": {SITE: {}}}
    (root / "survey.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (root / "filters.yaml").write_text(yaml.safe_dump({SITE: NOTCH}), encoding="utf-8")
    survey = Survey.from_yaml(root / "survey.yaml")
    rng = np.random.default_rng(3)
    data = {"hx": rng.normal(size=2000) * 1000 + 5000, "hy": rng.normal(size=2000) * 1000 - 3000}
    _write_raw_archive(default_archive_path(survey, SITE), SITE, "held_open", data, FS, "2020-01-01T00:00:00+00:00")
    assert SITE in survey.site_dirs(), f"premise: {SITE}'s raw folder is not found under {survey.data_root}"
    return root / "survey.yaml"


def sha1(path: Path) -> str:
    """Return the SHA-1 of a file's bytes."""
    return hashlib.sha1(path.read_bytes()).hexdigest()


class Hold:
    """Hold files open with h5py, mode "r", in a second process for the life of a `with` block."""

    def __init__(self, *paths: Path):
        self.paths = paths
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Hold":
        self.proc = subprocess.Popen([PY, "-c", HOLDER, *map(str, self.paths)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()
        assert line == f"HELD {len(self.paths)}", f"the holder did not open the files: {line!r}"
        return self

    def __exit__(self, *exc) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=60)


def built_variant() -> tuple[Survey, Path, str, Path]:
    """Return the survey, its built variant, the variant's SHA-1 and a copy of it to probe the hold with."""
    survey_yaml = make_survey()
    survey = Survey.from_yaml(survey_yaml)
    out = build_variant(survey, SITE)
    assert out == variant_path(survey, SITE) and variant_ready(survey, SITE), "premise: the first build is not ready"
    probe = SCRATCH / "survey" / "probe.h5"
    shutil.copy2(out, probe)
    return survey, out, sha1(out), probe


def check_hold_is_real(probe: Path) -> None:
    """The control: replacing a held file must raise PermissionError."""
    dummy = probe.with_name("dummy.bin")
    dummy.write_bytes(b"x")
    try:
        os.replace(dummy, probe)
    except PermissionError:
        dummy.unlink()
        return
    raise AssertionError(f"CONTROL: os.replace onto the held {probe.name} succeeded: the hold is not real")


def check_left(out: Path, before: str, where: str) -> None:
    """The variant must be byte for byte as before and its .part file gone."""
    part = out.with_name(out.name + ".part")
    assert not part.exists(), f"{where}: {part.name} was left behind ({part.stat().st_size} bytes)"
    assert out.exists(), f"{where}: the variant {out.name} was deleted"
    assert sha1(out) == before, f"{where}: the variant {out.name} changed"


def test_build_variant_held() -> None:
    survey, out, before, probe = built_variant()
    with Hold(out, probe):
        check_hold_is_real(probe)
        try:
            build_variant(survey, SITE)
        except Exception as exc:  # noqa: BLE001 -- any type; the message and the files are checked
            err = exc
        else:
            raise AssertionError("build_variant replaced a variant another process holds open")
    text = str(err)
    assert len(text.splitlines()) == 1, f"the message is not one line: {text!r}"
    assert out.name in text and "open in another program" in text, f"the message does not name the file " \
                                                                   f"and the holder: {type(err).__name__}: {text}"
    check_left(out, before, "build_variant")
    print(f"  build_variant while held: {type(err).__name__}: {text}")
    print(f"  {out.name}.part gone, {out.name} unchanged (sha1 {before[:12]})")


def test_script_held() -> None:
    survey, out, before, probe = built_variant()
    survey_yaml = SCRATCH / "survey" / "survey.yaml"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with Hold(out, probe):
        check_hold_is_real(probe)
        done = subprocess.run([PY, str(SCRIPT), str(survey_yaml), SITE, "--variant", "--force"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                              timeout=900)
    both = done.stdout + done.stderr
    assert done.returncode == 1, f"exit {done.returncode}, expected 1:\n{both[-2000:]}"
    assert "Traceback" not in both, f"the script printed a traceback:\n{both[-2000:]}"
    errors = [line for line in done.stderr.splitlines() if line.startswith("ERROR ")]
    assert len(errors) == 1 and out.name in errors[0] and "open in another program" in errors[0], \
        f"expected one ERROR line naming {out.name} and the holder, got {errors}:\n{both[-2000:]}"
    check_left(out, before, "ingest_site.py --variant --force")
    print(f"  ingest_site.py {SITE} --variant --force while held: exit 1, {errors[0]}")


def test_other_failure_keeps_variant() -> None:
    import ingest_site
    survey, out, before, _probe = built_variant()
    survey_yaml = SCRATCH / "survey" / "survey.yaml"
    part = out.with_name(out.name + ".part")

    def failing_build(_survey, _site):
        part.write_bytes(b"partial")
        raise RuntimeError("stand-in failure midway through the build")

    original = ingest_site.build_variant
    ingest_site.build_variant = failing_build
    try:
        ingest_site.main([str(survey_yaml), SITE, "--variant", "--force"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("the stand-in's RuntimeError did not reach the caller")
    finally:
        ingest_site.build_variant = original
    check_left(out, before, "a rebuild failing midway")
    print(f"  a --force rebuild failing midway: the .part removed, the current {out.name} kept")


def test_released_rebuild() -> None:
    survey, out, _before, _probe = built_variant()
    again = build_variant(survey, SITE)
    part = again.with_name(again.name + ".part")
    assert again == out and variant_ready(survey, SITE) and not part.exists(), \
        "a rebuild with nothing holding the variant did not give a ready variant"
    print(f"  with no hold: rebuilt {again.name}, ready")


if __name__ == "__main__":
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("Control (must fail")[0].strip())
    print()
    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        else:
            print(f"  ok    {test.__name__}")
    print(f"\n{'FAIL' if failed else 'PASS'}  variant_held_open_unit ({len(tests) - len(failed)} of {len(tests)} passed)")
    sys.exit(1 if failed else 0)
