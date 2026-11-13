# -*- coding: utf-8 -*-
"""
Unit test for derived 1 Hz sites in remote-reference runs: an h_from parent's outputs, and a stack of derived members

Two failures on derived sites (scripts/decimate_site.py's `<site>L`), seen
in Tasmania AusLAMP 2016's 1 Hz processing: every TAS132L pair stopped on
"'TransferFunctionCollection' object has no attribute 'impedance'"
(TAS132 takes TAS131's hx and hy, `h_from`, and has no hz, but TAS132L's
entry declared no channels, so process_rr.py asked aurora for an hz row),
and every rr on a stack of `L` members was refused as "at 10 Hz" (a stack
has no survey.yaml entry, and `Survey.sample_rate_of` gives such a name the
survey's rate, though the stack archive was at 1 Hz).

Three synthetic EDL sites at 10 Hz are written as hourly ASCII files (the
layout of tests/diagonal_site_unit.py) over 12 h and ingested with
`ingest_site`: N records ex, ey, hx, hy, hz; R the same; A records
electrics only (`channels: [ex, ey]`, `h_from: N`; its own BX, BY files hold
noise and are not read). The magnetic field is common red noise; A's
electric field is a fixed linear map of it plus noise. decimate_site.py
then writes NL, RL and AL at 1 Hz.

Usage:
    python tests/derived_sites_rr_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - decimate_site.py does not write AL's entry with `channels: [ex, ey, hx,
    hy]` (the archive's: A's own ex, ey and the hx, hy borrowed from N), or
    writes a `channels:` key in NL's or RL's entry (their channels are the
    defaults');
  - process_rr.py AL RL does not exit 0, print "output_channels: ex, ey",
    and write an EDI whose ZXY and ZYX are estimated at 8 periods or more
    and agree with A rr R at 10 Hz over 8-500 s (median rho ratio within
    5 % of 1, median |phase difference| under 2 deg, per mode), with no
    tipper;
  - the control: with AL's `channels:` line removed (its entry before the
    fix), the same run does not exit non-zero with the RuntimeError of
    `mt_workbench.process.process_station` naming the outputs "ex, ey, hz"
    (aurora's legacy TransferFunctionCollection, refused by name);
  - build_stack.py STK_ALu of NL and RL (--min-piece-h 1) does not exit 0,
    or its archive's runs are not at 1 Hz (sr1_0001, ...), or any of its
    hx/hy samples differs from the float32 of the float64 mean of NL's and
    RL's at the same instant;
  - process_rr.py --dry-run AL STK_ALu does not exit 0 printing "sample_rate:
    AL 1 Hz, STK_ALu 1 Hz", or the real run does not exit 0 with ZXY and ZYX
    estimated;
  - the mutation: with `process_rr.archive_rate` returning None (the rule
    before the fix), `resolve` does not refuse AL against STK_ALu as "at
    10 Hz";
  - the control: process_rr.py --dry-run AL against a 10 Hz stack of N and R
    does not exit 2 naming "AL is at 1 Hz and STK_A10 at 10 Hz".
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import yaml
from scipy import signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.ingest import default_archive_path, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

DECIMATE = REPO / "scripts" / "decimate_site.py"
PROCESS_RR = REPO / "scripts" / "process_rr.py"
BUILD_STACK = REPO / "scripts" / "build_stack.py"
SCRATCH = scratch_dir("derived_sites_rr_unit")
FS = 10.0
T0 = pd.Timestamp("2016-08-10T00:00:00", tz="UTC")
HOURS = 12
N = int(HOURS * 3600 * FS)
HEADER = ("name: t\ninstrument: edl\nsample_rate: 10\ndata_root: {raw}\nworkspace: {work}\n"
          "defaults:\n  channels: [ex, ey, hx, hy, hz]\n  sensor_type: bartington\n  flip_reversed_dipoles: true\n"
          "processing:\n  min_period: 0.2\n  max_period: 2000.0\n  periods_per_decade: 5.0\n  min_band_windows: 2\n"
          "sites:\n")
SITES = {"N": "", "R": "", "A": "    channels: [ex, ey]\n    h_from: \"N\"\n"}


def red(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return unit-variance red noise (integrated white noise, high-passed at 4000 s)."""
    x = np.cumsum(rng.standard_normal(n))
    x = signal.sosfiltfilt(signal.butter(2, (1 / 4000.0) / (FS / 2), "high", output="sos"), x)
    return x / x.std()


def write_sites(root: Path) -> None:
    """Write N, R and A as hourly EDL ASCII files sharing one magnetic field."""
    rng = np.random.default_rng(7)
    hx, hy = red(rng, N), red(rng, N)
    for k, name in enumerate(SITES):
        site = root / "raw" / name
        shutil.rmtree(site, ignore_errors=True)
        (site / "config").mkdir(parents=True)
        (site / "config" / "recorder.ini").write_text(
            "[recorder]\n" + "".join(f"channel_{c}_samplerate=10\n" for c in range(5)), encoding="utf-8")
        own = rng.standard_normal((5, N))
        if name == "A":  # its fluxgate is not read: h_from N
            words = {"BX": np.round(3e6 * own[0]), "BY": np.round(3e6 * own[1]), "BZ": np.round(1e3 * own[2])}
        else:
            words = {"BX": np.round(2.8e6 + 2e4 * hx + 200 * own[0]), "BY": np.round(2e4 * hy + 200 * own[1]),
                     "BZ": np.round(-3.3e6 + 2e3 * hx + 50 * own[2])}
        e_n = 2.0 * hy + 0.6 * hx + 0.05 * own[3]  # a fixed linear map of the field: a frequency-independent Z
        e_e = -1.5 * hx - 0.3 * hy + 0.05 * own[4]
        words["EX"] = np.round(-10 * 50.0 * e_n * (1.0 + 0.1 * k))
        words["EY"] = np.round(-10 * 50.0 * e_e * (1.0 + 0.1 * k))
        per = int(3600 * FS)
        for h in range(HOURS):
            when = T0 + pd.Timedelta(hours=h)
            for suffix, values in words.items():
                np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}",
                           values[h * per:(h + 1) * per].astype("int64"), fmt="%d")


def build(root: Path) -> Path:
    """Write survey.yaml and the three sites, ingest them, decimate them; return the yaml path."""
    root.mkdir(parents=True, exist_ok=True)
    text = HEADER.format(raw=(root / "raw").as_posix(), work=(root / "work").as_posix())
    end = T0 + pd.Timedelta(hours=HOURS)
    for k, (name, extra) in enumerate(SITES.items()):
        text += (f"  {name}:\n    dipole_length_ex: 50.0\n    dipole_length_ey: 50.0\n    azimuth_ex: 0.0\n"
                 f"    azimuth_ey: 90.0\n    latitude: -42.0\n    longitude: {147.0 + 0.05 * k}\n    elevation: 100.0\n"
                 f"    start: '{T0:%Y-%m-%dT%H:%M:%SZ}'\n    end: '{end:%Y-%m-%dT%H:%M:%SZ}'\n{extra}")
    path = root / "survey.yaml"
    path.write_text(text, encoding="utf-8")
    write_sites(root)
    sv = Survey.from_yaml(path)
    for name in ("N", "R", "A"):
        ingest_site(sv, name, out_path=default_archive_path(sv, name), overwrite=True)
    for name in ("N", "R", "A"):
        run = subprocess.run([sys.executable, str(DECIMATE), str(path), name], capture_output=True, text=True, cwd=REPO)
        assert run.returncode == 0, f"decimate_site.py {name}: exit {run.returncode}\n{run.stderr[-1500:]}"
    return path


def run_rr(path: Path, local: str, remote: str, *extra: str) -> subprocess.CompletedProcess:
    """Run process_rr.py on a pair with the campaign's flags."""
    return subprocess.run([sys.executable, str(PROCESS_RR), str(path), local, remote, "--no-masks",
                           "--min-band-windows", "2", *extra], capture_output=True, text=True, cwd=REPO)


def wrote_edi(text: str) -> Path | None:
    """Return the EDI a process_rr run says it wrote."""
    for line in re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).splitlines():
        if "wrote " in line and line.rstrip().endswith(".edi"):
            return Path(line.rstrip().split("wrote ", 1)[1])
    return None


def read_tf(edi: Path):
    """Return period, impedance and tipper of an EDI."""
    from mt_metadata.transfer_functions.core import TF

    tf = TF()
    tf.read(str(edi))
    tipper = np.asarray(tf.tipper) if tf.has_tipper() else None
    return np.asarray(tf.period, float), np.asarray(tf.impedance), tipper


def agreement(edi_a: Path, edi_b: Path, pmin: float, pmax: float) -> dict:
    """Return, per off-diagonal mode, the median rho ratio and median |phase difference| of a against b."""
    pa, za, _ = read_tf(edi_a)
    pb, zb, _ = read_tf(edi_b)
    out = {}
    for mode, (i, j) in (("xy", (0, 1)), ("yx", (1, 0))):
        keep = (pa >= pmin) & (pa <= pmax) & np.isfinite(za[:, i, j])
        ok = np.isfinite(zb[:, i, j])
        o = np.argsort(pb[ok])
        x, z = np.log10(pb[ok][o]), zb[ok, i, j][o]
        zi = np.interp(np.log10(pa[keep]), x, z.real) + 1j * np.interp(np.log10(pa[keep]), x, z.imag)
        ratio = np.abs(za[keep, i, j]) ** 2 / np.abs(zi) ** 2
        dphi = np.degrees(np.angle(za[keep, i, j] / zi))
        out[mode] = (int(keep.sum()), float(np.median(ratio)), float(np.median(np.abs(dphi))))
    return out


def estimated(edi: Path) -> tuple[int, int, bool]:
    """Return the periods with ZXY and ZYX finite, and whether a tipper is there."""
    _, z, t = read_tf(edi)
    fin = np.isfinite(z[:, 0, 1]) & np.isfinite(z[:, 1, 0])
    has_t = t is not None and bool(np.isfinite(t).any())
    return int(fin.sum()), int(z.shape[0]), has_t


def stack_problems(sv: Survey, name: str, members: list[str]) -> list[str]:
    """Compare a stack archive with its members: rate 1 Hz, run names, samples = the mean of the members'."""
    def runs(path: Path, station: str) -> list[dict]:
        out = []
        with h5py.File(path, "r") as f:
            st = f[f"Experiment/Surveys/t/Stations/{station}"]
            for rid, g in st.items():
                if isinstance(g, h5py.Group) and "hx" in g:
                    out.append(dict(id=rid, fs=float(g.attrs["sample_rate"]),
                                    t0=pd.Timestamp(g["hx"].attrs["time_period.start"]).value,
                                    hx=g["hx"][()], hy=g["hy"][()]))
        return out

    stack = runs(default_archive_path(sv, name), name)
    mem = {m: runs(default_archive_path(sv, m), m) for m in members}
    out = []
    if not stack:
        return [f"{name}: no run"]
    for k, r in enumerate(stack, 1):
        if r["fs"] != 1.0 or r["id"] != f"sr1_{k:04d}":
            out.append(f"{name} {r['id']}: {r['fs']:g} Hz")
        for c in ("hx", "hy"):
            acc = np.zeros(r[c].size)
            for m in members:
                mr = next(x for x in mem[m] if x["t0"] <= r["t0"] < x["t0"] + x[c].size * 1e9)
                i0 = int(round((r["t0"] - mr["t0"]) / 1e9))
                acc += mr[c][i0:i0 + r[c].size].astype("float64")
            if r[c].tobytes() != (acc / len(members)).astype("float32").tobytes():
                out.append(f"{name} {r['id']} {c} is not the mean of {members}")
    return out


def main() -> int:
    """Run the checks; return 1 when any failed."""
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1])
    failures = []

    def check(ok: bool, msg: str) -> None:
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            failures.append(msg)

    root = SCRATCH / "case"
    shutil.rmtree(root, ignore_errors=True)
    path = build(root)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["sites"]
    check(raw["AL"].get("channels") == ["ex", "ey", "hx", "hy"] and "channels" not in raw["NL"]
          and "channels" not in raw["RL"],
          f"derived entries: AL channels {raw['AL'].get('channels')}, NL {raw['NL'].get('channels')}, "
          f"RL {raw['RL'].get('channels')}")
    sv = Survey.from_yaml(path)

    # the h_from parent's derived site processes to a Z
    ref = run_rr(path, "A", "R", "--tag", "ten")
    run = run_rr(path, "AL", "RL", "--tag", "one")
    edi, edi10 = wrote_edi(run.stdout + run.stderr), wrote_edi(ref.stdout + ref.stderr)
    if run.returncode == 0 and edi and edi10:
        n, total, has_t = estimated(edi)
        agree = agreement(edi, edi10, 8.0, 500.0)
        good = all(k >= 5 and abs(r - 1) < 0.05 and d < 2.0 for k, r, d in agree.values())
        check("output_channels: ex, ey" in run.stdout and n >= 8 and not has_t and good,
              f"AL rr RL: Z at {n} of {total} periods, tipper {has_t}; against A rr R at 10 Hz (8-500 s): "
              + "; ".join(f"{m} {k} periods rho ratio {r:.4f} |dphi| {d:.2f} deg" for m, (k, r, d) in agree.items()))
    else:
        check(False, f"AL rr RL exit {run.returncode}, A rr R exit {ref.returncode}\n{run.stderr[-1500:]}")

    # the control: AL's entry before the fix (no channels: the defaults' hz asked for)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["sites"]["AL"].pop("channels", None)
    unfixed = root / "survey_unfixed.yaml"
    unfixed.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    bad = run_rr(unfixed, "AL", "RL", "--tag", "unfixed")
    check(bad.returncode != 0 and "RuntimeError: aurora returned a TransferFunctionCollection for AL" in bad.stderr
          and "Outputs asked for: ex, ey, hz" in bad.stderr,
          f"control, AL without channels: exit {bad.returncode}, "
          + (bad.stderr.strip().splitlines() or ["no stderr"])[-1][:160])

    # a 1 Hz stack of derived members
    lo, hi = sv.site("AL").start, sv.site("AL").end
    b = subprocess.run([sys.executable, str(BUILD_STACK), str(path), "STK_ALu", str(lo), str(hi), "NL", "RL",
                        "--min-piece-h", "1"], capture_output=True, text=True, cwd=REPO)
    probs = stack_problems(sv, "STK_ALu", ["NL", "RL"]) if b.returncode == 0 else [b.stderr[-800:]]
    check(b.returncode == 0 and not probs, f"STK_ALu of NL and RL: exit {b.returncode}, {probs or '1 Hz, the mean'}")
    dry = run_rr(path, "AL", "STK_ALu", "--dry-run")
    check(dry.returncode == 0 and "sample_rate: AL 1 Hz, STK_ALu 1 Hz" in dry.stdout,
          f"--dry-run AL STK_ALu: exit {dry.returncode}, "
          + next((ln for ln in dry.stdout.splitlines() if ln.startswith("sample_rate")), dry.stderr[-300:]))
    real = run_rr(path, "AL", "STK_ALu", "--tag", "stk")
    edi_s = wrote_edi(real.stdout + real.stderr)
    n_s = estimated(edi_s)[0] if real.returncode == 0 and edi_s else 0
    check(real.returncode == 0 and n_s >= 8, f"AL rr STK_ALu: exit {real.returncode}, Z at {n_s} periods")

    # the mutation: the rule before the fix
    import process_rr

    args = process_rr.build_parser().parse_args([str(path), "AL", "STK_ALu", "--dry-run", "--no-masks"])
    process_rr.resolve(args, dt.datetime.now().astimezone())
    keep = process_rr.archive_rate
    process_rr.archive_rate = lambda *_a: None
    try:
        process_rr.resolve(args, dt.datetime.now().astimezone())
        msg = ""
    except process_rr.RateMismatch as exc:
        msg = str(exc)
    finally:
        process_rr.archive_rate = keep
    check("STK_ALu at 10 Hz" in msg, f"mutation, the survey's rate for a stack: {msg[:90] or 'not refused'}")

    # the control: a 10 Hz stack for a 1 Hz local
    b10 = subprocess.run([sys.executable, str(BUILD_STACK), str(path), "STK_A10", str(lo), str(hi), "N", "R"],
                         capture_output=True, text=True, cwd=REPO)
    d10 = run_rr(path, "AL", "STK_A10", "--dry-run")
    check(b10.returncode == 0 and d10.returncode == 2 and "AL is at 1 Hz and STK_A10 at 10 Hz" in d10.stderr,
          f"control, 10 Hz stack: build exit {b10.returncode}, dry run exit {d10.returncode}: "
          + (d10.stderr.strip().splitlines() or [""])[-1][:120])

    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'PASS  derived_sites_rr_unit (all checks)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
