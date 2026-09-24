# -*- coding: utf-8 -*-
"""
Unit test for the mtproc mt-io fork against stock mt-io 0.0.5

Tests the fork (branch `mtproc-fixes` of github.com/bvkay/mt-io). The checks
run in a fresh process (`--worker`) that imports mt_io alone, without
mtproc, since mtproc uses the fork's readers directly. Every check writes its
own synthetic files (B423, EDL ASCII, a .rsp table) into a temporary folder,
so the test needs no data drive or survey.

The mt-io tested is the clone of the fork at `MTPROC_FORKS/mt-io`
(MTPROC_FORKS defaults to `_scratch.DEFAULT_FORKS`) when it holds
`src/mt_io`, run with PYTHONPATH=<clone>/src ahead of this process's own
PYTHONPATH and src. Without a clone it is the installed mt_io, when that
already parses the four-digit altitude of check 1 (the fork installed).
Otherwise the fork checks are reported as skipped.

The installed mt-io (what this interpreter imports: site-packages, or a
PYTHONPATH set before the test) is run through the same checks and reported
check by check for information. Stock 0.0.5 fails every one, as each check
exercises the bug it documents (docs/upstream_issues.md 6, 7, 8, 18, 19,
21), and the installed fork passes every one, so a pass there is reported as
fixed.

Usage:
    python tests/mtio_fork_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

0. with the clone, the worker imports mt_io from anywhere but the clone;
1. a B423 file whose header reads `%Alt1060.0,m 12 1` does not read through
   `read_lemi423` with station elevation 1060.0 m (issue 6);
2. `LEMICollection(folder, file_ext=["B423"]).to_dataframe()`, no
   `sample_rates`, does not list both 1000 Hz files of a two-file folder (issue 7);
3. a B423 file whose tick is always 0 (one record a second) gives a sample
   rate other than None from `Read_Lemi_Data.read_summary`, or no WARNING
   naming the file (issue 8);
4. `read_uoa` on a list of EDL files (three 6 s stamps at 10 Hz) where EX has
   no file at the second stamp returns a run instead of raising ValueError
   naming EX and not BX (issue 18);
5. `read_uoa(sensor_type="lemi120", calibration_fn_b*=<.rsp>)` does not give
   hx the chain [lemi_120_hx_response, lemi120_dc_gain_hx] whose gain stage
   says 400 mV/nT, where the default read gives [uoa_bartington_hx]; or the
   default read at 1000 Hz logs no WARNING naming sensor_type; or a .rsp that
   does not parse does not raise ValueError (issue 19);
6. `read_uoa(channel_gain={"ex": 100.0})` (in place of the x10 terminal box)
   does not calibrate ex 10 times smaller than the default read of the same
   files (ratio of the two channel responses at 0.1 and 1 Hz, to 1e-12), or
   changes the stored samples, or touches ey (issue 21, the hardware-neutral
   per-channel gain).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from _scratch import fork_clone, forks_dir  # noqa: E402

STOCK_VERSION = "0.0.5"
CHECKS = {
    "1": "four-digit altitude header parses",
    "2": "LEMI-423 collection lists its files by default",
    "3": "an undetectable B423 rate is None with a warning naming the file",
    "4": "a non-contiguous EDL file list is refused, naming the channel",
    "5": "sensor_type lemi120 changes the chain; the default is not silent; a bad .rsp raises",
    "6": "a channel declared at channel_gain x100 calibrates 10x smaller",
}


def clone_ok(path: Path) -> bool:
    """Check whether a fork clone holds src/mt_io."""
    return (path / "src" / "mt_io" / "__init__.py").is_file()


# --------------------------------------------------------------------------- worker (imports mt_io only)

def _write_b423(path: Path, epoch: int = 1624510579, n: int = 2000, rate: int = 1000,
                alt_line: str = "%Alt 119.9,m 12 2") -> Path:
    """Write a synthetic B423 file.

    Args:
        path (Path): File to write.
        epoch (int): Start epoch in seconds.
        n (int): Number of records.
        rate (int): Records per second.
        alt_line (str): The header's altitude line.

    Returns:
        Path: `path`.
    """
    import numpy as np
    import pandas as pd
    from mt_io.lemi.lemi423 import Read_Lemi_Data

    when = pd.Timestamp(epoch, unit="s", tz="UTC")
    lines = ["%LEMI423 #0036", "%FIRMWARE Ver.2.1", "%MADE in UKRAINE", " ",
             f"%Date {when:%Y/%m/%d}", f"%Time {when:%H:%M:%S}", "%Ubat 13.16V", "%Current 101.7mA",
             "%Free 30424MB", "%Lat 3209.28947,N", "%Lon 00309.35612,W", alt_line, " ",
             "%Kmx = 2.909985e-06", "%Kmy = 2.909481e-06", "%Kmz = 2.908610e-06",
             "%Ax = -5.002100e+01", "%Ay = -4.990500e+01", "%Az = -4.994700e+01",
             "%Ke1 = 2.910737e-04", "%Ke2 = 2.909547e-04", "%Ae1 = -5.004800e+03", "%Ae2 = -4.958000e+03"]
    header = ("\r\n".join(lines) + "\r\n").encode("ascii").ljust(1024, b" ")
    records = np.zeros(n, dtype=Read_Lemi_Data.binary_format)
    index = np.arange(n)
    records["time"] = epoch + index // rate
    records["tick"] = (index % rate) * (1000 // rate)
    records["Ex"] = index
    path.write_bytes(header + records.tobytes())
    return path


def _write_edl(folder: Path, stamps, n: int = 60) -> list[Path]:
    """Write synthetic EDL ASCII files (BX BY BZ EX EY) of n samples for each stamp."""
    folder.mkdir(parents=True, exist_ok=True)
    body = "\n".join(str(1000 + i) for i in range(n)) + "\n"
    out = []
    for stamp in stamps:
        for ch in ("BX", "BY", "BZ", "EX", "EY"):
            path = folder / f"TEST01_{stamp}.{ch}"
            path.write_text(body)
            out.append(path)
    return out


def _write_rsp(path: Path) -> Path:
    """Write a synthetic coil response table (.rsp)."""
    import numpy as np

    f = np.logspace(-3, 3, 25)
    rows = "\n".join(f"{x:.6e} {x / np.sqrt(x * x + 0.01):.6e} {np.degrees(np.arctan2(0.1, x)):.6e}" for x in f)
    path.write_text("B\nfreq amp phas\n" + rows + "\n")
    return path


def _warnings(action):
    """Run `action` and return (its result, the loguru WARNING messages it logged)."""
    from loguru import logger

    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        result = action()
    finally:
        logger.remove(sink)
    return result, messages


def _check(tmp: Path, key: str) -> tuple[bool, str]:
    """Run one check of CHECKS in a temporary folder.

    Returns:
        tuple[bool, str]: (passed, detail).

    Raises:
        KeyError: On an unknown check.
    """
    import numpy as np

    if key == "1":
        from mt_io.lemi.lemi423 import read_lemi423

        fn = _write_b423(tmp / "1624510579.B423", alt_line="%Alt1060.0,m 12 1")
        elevation = read_lemi423(fn).station_metadata.location.elevation
        return abs(elevation - 1060.0) < 1e-9, f"elevation {elevation}"
    if key == "2":
        from mt_io.lemi import LEMICollection

        folder = tmp / "site"
        folder.mkdir()
        for k in range(2):
            _write_b423(folder / f"{1624510579 + 2 * k}.B423", epoch=1624510579 + 2 * k)
        df = LEMICollection(folder, file_ext=["B423"]).to_dataframe()
        rates = sorted(set(df.sample_rate)) if len(df) else []
        return len(df) == 2 and rates == [1000.0], f"{len(df)} file(s) listed, rates {rates}"
    if key == "3":
        from mt_io.lemi.lemi423 import Read_Lemi_Data

        fn = _write_b423(tmp / "1700000000.B423", epoch=1700000000, n=30, rate=1)
        summary, messages = _warnings(lambda: Read_Lemi_Data(fn, {}).read_summary())
        named = [m for m in messages if fn.name in m]
        return summary["sample_rate"] is None and bool(named), \
            f"rate {summary['sample_rate']}, {len(named)} warning(s) naming the file"
    if key == "4":
        from mt_io.uoa import read_uoa

        files = _write_edl(tmp / "edl", ["240101000000", "240101000006", "240101000012"])
        (tmp / "edl" / "TEST01_240101000006.EX").unlink()
        files = [f for f in files if f.exists()]
        try:
            run = read_uoa(files, sample_rate=10.0, station_id="TEST01", sensor_type="bartington",
                           dipole_length_ex=50.0, dipole_length_ey=50.0)
        except ValueError as error:
            text = str(error)
            return "EX" in text and "BX" not in text, f"refused: {text[:160]}"
        return False, f"read as one run of {run.dataset.sizes['time']} samples"
    if key == "5":
        from mt_io.uoa import read_uoa

        files = _write_edl(tmp / "edl", ["240101000000"], n=100)
        rsp = _write_rsp(tmp / "l120n.rsp")
        common = dict(station_id="TEST01", dipole_length_ex=50.0, dipole_length_ey=50.0, sample_rate=1000.0)
        default, messages = _warnings(lambda: read_uoa(files, **common))
        coil = read_uoa(files, sensor_type="lemi120",
                        **{f"calibration_fn_{c}": str(rsp) for c in ("bx", "by", "bz")}, **common)
        names_default = default.hx.channel_response.names
        names_coil = coil.hx.channel_response.names
        note = coil.hx.channel_response.filters_list[-1].comments
        note = str(getattr(note, "value", note))
        named = any("sensor_type" in m for m in messages)
        bad = tmp / "broken.rsp"
        bad.write_text("B\nfreq amp phas\nnot a number\n")
        try:
            read_uoa(files, sensor_type="lemi120", **{f"calibration_fn_{c}": str(bad) for c in ("bx", "by", "bz")},
                     **common)
            raised = False
        except ValueError:
            raised = True
        ok = (names_default == ["uoa_bartington_hx"] and names_coil == ["lemi_120_hx_response", "lemi120_dc_gain_hx"]
              and "400 mV/nT" in note and named and raised)
        return ok, (f"default {names_default}, lemi120 {names_coil}, note {note!r}, default warned: {named}, "
                    f"bad .rsp raised: {raised}")
    if key == "6":
        from mt_io.uoa import read_uoa

        files = _write_edl(tmp / "edl", ["240101000000"])
        common = dict(station_id="TEST01", dipole_length_ex=50.0, dipole_length_ey=50.0, sample_rate=10.0,
                      sensor_type="bartington")
        default = read_uoa(files, **common)
        declared = read_uoa(files, channel_gain={"ex": 100.0}, **common)
        f = np.array([0.1, 1.0])
        ratio = np.abs(declared.ex.channel_response.complex_response(f)
                       / default.ex.channel_response.complex_response(f))
        same_samples = np.array_equal(declared.ex.ts, default.ex.ts)
        same_ey = declared.ey.channel_response.names == default.ey.channel_response.names
        ok = bool(np.all(np.abs(ratio - 10.0) <= 1e-12 * 10.0)) and same_samples and same_ey
        return ok, (f"ex response ratio {ratio.tolist()}, chain {declared.ex.channel_response.names}, "
                    f"samples unchanged: {same_samples}, ey untouched: {same_ey}")
    raise KeyError(key)


def worker(out: Path) -> None:
    """Run every check with the mt_io this process imports and write the results as JSON."""
    from loguru import logger

    import mt_io

    logger.remove()  # the readers' INFO lines; _warnings adds its own sink
    results = {"mt_io": mt_io.__file__, "version": getattr(mt_io, "__version__", "?"), "checks": {}}
    for key in CHECKS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ok, detail = _check(Path(tmp), key)
            except Exception as error:  # a stock reader that raises fails the check
                ok, detail = False, f"{type(error).__name__}: {str(error)[:200]}"
        results["checks"][key] = {"ok": bool(ok), "detail": detail}
    out.write_text(json.dumps(results, indent=1))


def run_worker(pythonpath: list[Path]) -> dict:
    """Run `worker` in a fresh process and return its results.

    PYTHONPATH is `pythonpath` (the clone, if any), this process's own
    PYTHONPATH, then this repo's src; with `pythonpath` empty the installed
    mt-io is tested.

    Raises:
        RuntimeError: When the worker fails.
    """
    env = dict(os.environ)
    inherited = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([str(p) for p in pythonpath] + inherited + [str(REPO / "src")])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(out)],
                              env=env, capture_output=True, text=True)
        if proc.returncode or not out.exists():
            raise RuntimeError(f"worker failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
        return json.loads(out.read_text())


def report(results: dict, title: str) -> dict:
    """Print a worker's results and return {check: passed}."""
    print(f"  {title}: mt_io {results['version']} from {results['mt_io']}")
    for key, name in CHECKS.items():
        r = results["checks"][key]
        print(f"    {key}. {'PASS' if r['ok'] else 'FAIL'}  {name}: {r['detail']}")
    return {k: r["ok"] for k, r in results["checks"].items()}


def main() -> int:
    """Test the installed mt-io (for information) and the fork; return 1 when a fork check fails."""
    installed = run_worker([])  # the installed mt-io
    clone = fork_clone("mt-io")
    failures = []

    fixed = report(installed, "installed mt-io, informational (stock fails every check, the fork passes them)")
    n_fixed = sum(fixed.values())
    kind = "the fork" if n_fixed == len(fixed) else "stock behaviour" if not n_fixed else "a partial fix"
    installed_line = f"installed mt-io {installed['version']}: {n_fixed} of {len(fixed)} checks fixed ({kind})"

    if clone is not None and clone_ok(clone):
        fork = run_worker([clone / "src"])
        inside = Path(fork["mt_io"]).resolve().is_relative_to((clone / "src").resolve())
        print(f"  0. {'PASS' if inside else 'FAIL'}  the worker imports mt_io from the clone: {fork['mt_io']}")
        if not inside:
            failures.append(f"check 0: mt_io imported from {fork['mt_io']}, not {clone / 'src'}")
        ok = report(fork, f"fork, the clone at {clone}")
    elif installed["checks"]["1"]["ok"]:
        print(f"  no fork clone at {forks_dir('mt-io')}; the installed mt-io parses the four-digit altitude: "
              f"the fork installed, checks 1-6 asserted on it")
        ok = fixed
    else:
        print(f"  stock mt-io {installed['version']} installed and no fork clone at "
              f"{clone or forks_dir('mt-io')}: fork checks 1-6 SKIPPED")
        ok = {}
    failures += [f"check {k} ({CHECKS[k]}) fails on the fork" for k, v in ok.items() if not v]

    fork_line = f"fork: {sum(ok.values())} of {len(ok)} checks fixed; " if ok else ""
    print(f"\n  {fork_line}{installed_line}")
    if failures:
        print("\nFAIL  mtio_fork_unit\n  " + "\n  ".join(failures))
        return 1
    print("\nPASS  mtio_fork_unit" + ("" if ok else " (fork checks skipped)"))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        raise SystemExit(0)
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    raise SystemExit(main())
