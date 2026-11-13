# -*- coding: utf-8 -*-
"""
Unit test for process_intersite.py --base-stack H: the band stack of the members' H as the base of M

The fields are those of tests/intersite_unit.py (`fields`): red-noise
sources Bx, By (the common horizontal magnetic field H) and the regional
electric field E. The local's H is a known M applied to the common field,

    H_local = MT exp(i phi0) H + noise,
    MT = [[1.05, 0.08], [-0.06, 0.95]], phi0 = -1.5 deg, no delay.

A scratch survey at 100 Hz holds 3 h of the sites

- L, the local (its H as above, its noise 0.3 of H's spectrum);
- M1-M5, the base stack's members: hx, hy = 0.8 H + noise of 0.5 of H's
  spectrum each, so the members share the common H and differ in their
  noise;
- R, the reference: ex, ey = 0.8 E + its own noise (an E-site reference,
  `--remote R --remote-channels ex,ey`), and an H of its own, so that R
  qualifies as a member of the base stack and is left out by --exclude;
- P, a member whose hx is reversed (-0.8 Hx + noise), its hy as M1's are;
- Q1-Q3, sites with H = H + their own noise, the members of a reference
  stack built from other sites than the base stack (`--remote-exclude`).

Every channel is written as int32 counts through its filter chain
(`intersite_unit.write_site`). The band stack divides each member by its
per-band scale s, so in a band the stack's channel r is
0.8 mean_m(1 / s_m,r) H_r plus noise, and the expected M on the stack is
MT exp(i phi0) with its column r divided by 0.8 mean_m(1 / s_m,r), the
scales those the sidecar records. That diagonal is real and positive, so
arg(det M) / 2 and the delay are those of MT exp(i phi0).

Usage:
    python tests/intersite_basestack_h_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (recovery) the run `L --kind magnetic --base-stack H --remote R
   --remote-channels ex,ey --exclude R,P,Q1,Q2,Q3` (members M1-M5) has,
   of its element-bands with a finite error, more than 5 % beyond 3 sigma
   of the expected M on the stack or any beyond 5 sigma; or its timing
   check's tau differs from 0 by more than max(3 sigma, 0.05 ms) or its
   intercept from phi0 by more than max(3 sigma, 0.1 deg); the same for
   the run of criterion 3 on the reference stack of Q1-Q3 and for the
   `--screen-polarity drop` run of criterion 4 against the scales of the
   members it kept;
2. (mutation, must trip 1) the same base stack referenced to the stack of
   the same members' H (`--remote-stack H --allow-shared-members`, the
   reference then sharing every member's noise with the inputs) passes
   criterion 1's 3-sigma count, or puts 25 % or fewer of the element-bands
   beyond 3 sigma; or that run's sidecar does not record the five shared
   members;
3. (the separate reference list) `--remote-stack H --exclude R,P,Q1,Q2,Q3`
   without `--remote-exclude` (the reference stack then M1-M5, the base
   stack's own members) is not refused with exit 2 naming errors in
   variables; or with `--remote-exclude M1,M2,M3,M4,M5,P,R` the dry run
   does not print "reference_exclude: M1, M2, M3, M4, M5, P, R
   (--remote-exclude)", the run fails, its sidecar's reference members are
   not Q1-Q3 with exclude_from "--remote-exclude", its base stack members
   not M1-M5, or its shared sites not empty;
4. (polarity) with P a member (`--exclude R,Q1,Q2,Q3`) the flag run's
   sidecar does not flag P's hx with a correlation under -0.5, or flags
   P's hy or any channel of M1-M5 (the control that the flag can stay
   down), or leaves P out of the stack, or the log lacks the flag line;
   the `--screen-polarity drop` run does not mark P dropped, keeps P in
   its band record or in the h5's base_stack_members, or fails
   criterion 1;
5. (units) the run of criterion 1's sidecar lacks, in a band of its
   base_stack record, a stack_scale_rms for hx and hy equal (to 1e-9
   relative) to the root mean square of that band's member scales; or its
   `units` is not `intersite.STACK_UNITS`; or, over the bands with M's
   diagonal known to 10 % (error under 0.1 of the modulus), the median
   relative misfit of column r times 1 / stack_scale_rms[r] to the member
   field ratio MT exp(i phi0) / 0.8 exceeds 3 % on the diagonal; or, as
   the control that |M| on the stack is not a field ratio, the same
   misfit without the division is under 50 %;
6. (the sidecar's base block) the run of criterion 1 has a stem other
   than L_hm-stackH_rr-R-E, a base_site that is not null, inputs other
   than "stackH hx", "stackH hy", or a base_stack lacking: field H,
   channels [hx, hy]; members exactly M1-M5, each with a positive scale
   and a rejected fraction for hx and hy in every band; the local left out
   as "the local"; R, P and Q1-Q3 left out as excluded; the polarity mode
   flag; no shared site; or its h5 lacks the same band record;
7. (the command line) `--base-stack E` with `--kind magnetic` or
   `--base-stack H` with `--kind telluric` is not refused with exit 2
   naming the pairing that goes; `--remote-exclude` with a named base and
   `--remote-stack`, or with `--base-stack` and `--remote SITE`, is not
   refused with exit 2; a base member as `--remote` (`--remote M1`) is
   not refused naming M1 and errors in variables; the dry run of
   criterion 1 does not print the members M1-M5 as base_member lines,
   "polarity_screen: flag", the stem and the base_stack_units line; or a
   dry run or refusal writes a file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import FS2, PHI0_DEG, T_START, fields, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("intersite_basestack_h_unit")
HOURS = 3.0
MT = np.array([[1.05, 0.08], [-0.06, 0.95]])
MEMBERS = ("M1", "M2", "M3", "M4", "M5")
REF_MEMBERS = ("Q1", "Q2", "Q3")
MEMBER_NOISE = 0.5  # of H's spectrum, per member
LOCAL_NOISE = 0.3  # of H's spectrum
SIGNAL = 0.8  # each member's share of the common H
ROLES = ("hx", "hy")
BASE_EXCLUDE = "R,P,Q1,Q2,Q3"

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


SURVEY_YAML = """name: intersite_basestack_h_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0}}
  R: {{latitude: -31.8, longitude: 137.3}}
  M1: {{latitude: -31.1, longitude: 137.1}}
  M2: {{latitude: -31.2, longitude: 137.1}}
  M3: {{latitude: -31.3, longitude: 137.1}}
  M4: {{latitude: -31.4, longitude: 137.1}}
  M5: {{latitude: -31.5, longitude: 137.1}}
  P: {{latitude: -31.6, longitude: 137.1}}
  Q1: {{latitude: -31.1, longitude: 137.4}}
  Q2: {{latitude: -31.2, longitude: 137.4}}
  Q3: {{latitude: -31.3, longitude: 137.4}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""


def build_survey() -> Path:
    """Write the scratch survey and its archives; return survey.yaml."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    sites = ("l", "r", "m1", "m2", "m3", "m4", "m5", "p", "q1", "q2", "q3")
    spec = fields(FS2, HOURS, seed=41, h_sites=sites)
    n, f = spec["n"], spec["f"]
    rng = np.random.default_rng(43)
    fpos = np.maximum(f, f[1])
    b_shape = fpos**-1.0  # as `fields` shapes B

    def white():
        w = rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)
        w[0] = 0.0
        return w

    bx, by = _common_field(spec)
    m = MT * np.exp(1j * np.radians(PHI0_DEG))
    spec["l_hx"] = m[0, 0] * bx + m[0, 1] * by + LOCAL_NOISE * white() * b_shape
    spec["l_hy"] = m[1, 0] * bx + m[1, 1] * by + LOCAL_NOISE * white() * b_shape
    for site in ("m1", "m2", "m3", "m4", "m5", "p"):
        spec[f"{site}_hx"] = SIGNAL * bx + MEMBER_NOISE * white() * b_shape
        spec[f"{site}_hy"] = SIGNAL * by + MEMBER_NOISE * white() * b_shape
    spec["p_hx"] = -SIGNAL * bx + MEMBER_NOISE * white() * b_shape
    # H of 1e4 counts rms through the gain of 10; the electric channels stay well inside int32
    spec["scale"] = 1.0e3 / float(np.std(np.fft.irfft(bx, n)))
    e_peak = max(float(np.max(np.abs(np.fft.irfft(spec[k], n)))) for k in ("r_ex", "r_ey", "l_ex", "l_ey"))
    assert e_peak * spec["scale"] * 60.0 < 2.0e9, "the electric channels would overflow int32"
    for site in ("L", "R", "P") + MEMBERS + REF_MEMBERS:
        write_site(work, site, spec, T_START, n)
    return yaml_path


def _common_field(spec: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return the common Bx, By of `fields`, which keeps only the clean E: src_ex = 2 z By, src_ey = -1.5 z Bx."""
    f = spec["f"]
    fpos = np.maximum(f, f[1])
    z = np.sqrt(fpos) * np.exp(1j * np.pi / 4)
    by = spec["src_ex"] / (2.0 * z)
    bx = spec["src_ey"] / (-1.5 * z)
    bx[0] = by[0] = 0.0
    return bx, by


def run(yaml_path: Path, *args: str, kind: str = "magnetic") -> subprocess.CompletedProcess:
    """Run process_intersite.py on the scratch survey with the local L."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "L", "--kind", kind, *args],
                          capture_output=True, text=True, cwd=REPO)


def last_line(res: subprocess.CompletedProcess) -> str:
    """Return the last line of stderr, shortened."""
    return (res.stderr.strip().splitlines() or [""])[-1][:200]


def read_side(out: Path, stem: str) -> dict:
    """Read a run's sidecar."""
    return json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))


def kept_scales(base_stack: dict) -> dict:
    """Return period (rounded) -> role -> the scales of the members the stack kept."""
    scales: dict = {}
    for m in base_stack["members"]:
        if m.get("dropped"):
            continue
        for b in m["per_band"]:
            for r in ROLES:
                scales.setdefault(round(b["period"], 9), {}).setdefault(r, []).append(b[r]["scale"])
    return scales


def stack_recovery(est, base_stack: dict, label: str, report: bool = True) -> dict:
    """Judge criterion 1: the estimate against MT exp(i phi0) with each column over 0.8 mean(1 / s) of the kept members.

    Args:
        est (TensorEstimate): The estimate read back from the CSV.
        base_stack (dict): The sidecar's base_stack block.
        label (str): For the printed lines.
        report (bool): Record PASS/FAIL lines.

    Returns:
        dict: n, beyond3, beyond5, worst, elements_ok, timing_ok, tau, intercept.
    """
    scales = kept_scales(base_stack)
    m_true = MT * np.exp(1j * np.radians(PHI0_DEG))
    dev = []
    for b, p in enumerate(est.period):
        key = round(float(p), 9)
        k = np.array([SIGNAL * np.mean(1.0 / np.array(scales[key][r])) for r in ROLES])
        d = np.abs(est.tensor[b] - m_true / k[None, :]) / est.sigma[b]
        dev += [x for x in d.ravel() if np.isfinite(x)]
    dev = np.array(dev)
    n3, n5 = int((dev > 3).sum()), int((dev > 5).sum())
    elements_ok = dev.size > 0 and n3 <= 0.05 * dev.size and n5 == 0
    tc = intersite.timing_check(est)
    timing_ok = (tc["tau_ms"] is not None and abs(tc["tau_ms"]) <= max(3 * tc["tau_err_ms"], 0.05)
                 and abs(tc["intercept_deg"] - PHI0_DEG) <= max(3 * tc["intercept_err_deg"], 0.1))
    out = {"n": int(dev.size), "beyond3": n3, "beyond5": n5, "worst": float(dev.max()) if dev.size else np.nan,
           "elements_ok": bool(elements_ok), "timing_ok": bool(timing_ok), "tau": tc["tau_ms"],
           "intercept": tc["intercept_deg"]}
    if report:
        check(elements_ok, f"{label}: {n3} of {dev.size} element-bands beyond 3 sigma of MT on the stack (at most "
                           f"5 %), {n5} beyond 5 sigma, worst {out['worst']:.2f} sigma")
        check(timing_ok, f"{label}: timing tau {tc['tau_ms']:+.4f} +/- {tc['tau_err_ms']:.4f} ms (expected 0), "
                         f"intercept {tc['intercept_deg']:+.3f} +/- {tc['intercept_err_deg']:.3f} deg (expected "
                         f"{PHI0_DEG:+.2f})")
    return out


def command_line(yaml_path: Path, out: Path) -> None:
    """Criteria 3 (the refusal), 7: the refusals and the dry runs, none of which may write a file."""
    o = ("--out-dir", str(out))
    base = ("--base-stack", "H")
    for label, kind, args, needle in (
            ("--base-stack E with --kind magnetic", "magnetic",
             ("--base-stack", "E", "--remote", "R", "--exclude", BASE_EXCLUDE), "--base-stack H goes with --kind "
                                                                                 "magnetic"),
            ("--base-stack H with --kind telluric", "telluric",
             base + ("--remote", "R", "--exclude", BASE_EXCLUDE), "--base-stack E goes with --kind telluric"),
            ("--remote-exclude with a named base", "magnetic",
             ("M1", "--remote-stack", "H", "--remote-exclude", "M2"), "--remote-exclude goes with"),
            ("--remote-exclude with --base-stack and --remote SITE", "magnetic",
             base + ("--remote", "R", "--exclude", BASE_EXCLUDE, "--remote-exclude", "M1"),
             "--remote-exclude goes with"),
            ("a base member as --remote", "magnetic", base + ("--remote", "M1", "--exclude", BASE_EXCLUDE),
             "errors in variables")):
        res = run(yaml_path, *args, *o, "--dry-run", kind=kind)
        ok = res.returncode == 2 and needle in res.stderr
        if label == "a base member as --remote":
            ok = ok and "['M1']" in res.stderr
        check(ok, f"7 refused, exit {res.returncode}: {label}: {last_line(res)}")

    res = run(yaml_path, *base, "--remote-stack", "H", "--exclude", BASE_EXCLUDE, *o, "--dry-run")
    check(res.returncode == 2 and "errors in variables" in res.stderr and "'M1'" in res.stderr,
          f"3 the reference stack on --exclude alone (M1-M5, the base stack's members) refused, exit "
          f"{res.returncode}: {last_line(res)}")
    res = run(yaml_path, *base, "--remote-stack", "H", "--exclude", BASE_EXCLUDE, "--remote-exclude",
              "M1,M2,M3,M4,M5,P,R", *o, "--dry-run")
    refs = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("member: ")]
    check(res.returncode == 0 and "reference_exclude: M1, M2, M3, M4, M5, P, R (--remote-exclude)" in res.stdout
          and refs == list(REF_MEMBERS) and "shared_members: none" in res.stdout,
          f"3 --remote-exclude dry run: exit {res.returncode}, reference members {refs}")

    res = run(yaml_path, *base, "--remote", "R", "--remote-channels", "ex,ey", "--exclude", BASE_EXCLUDE, *o,
              "--dry-run")
    got = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("base_member: ")]
    ok = (res.returncode == 0 and got == list(MEMBERS) and "polarity_screen: flag" in res.stdout
          and "stem: L_hm-stackH_rr-R-E" in res.stdout and "inputs: base stack H: hx, hy of 5 member(s)" in res.stdout
          and "base_stack_units: per-band normalised: |M| is not a field ratio" in res.stdout)
    check(ok, f"7 dry run: exit {res.returncode}, base members {got}")
    if res.returncode != 0:
        print(res.stderr[-2000:])
    check(not out.exists(), "7 the dry runs and refusals wrote nothing")


def units(est, side: dict) -> None:
    """Criterion 5: stack_scale_rms in the record, the sidecar's units, and the formula back to a field ratio."""
    bs = side["base_stack"]
    scales = kept_scales(bs)
    rms_ok = True
    for band in bs["bands"]:
        for r in ROLES:
            want = float(np.sqrt(np.mean(np.array(scales[round(band["period"], 9)][r]) ** 2)))
            got = band.get("stack_scale_rms", {}).get(r)
            rms_ok &= got is not None and abs(got - want) <= 1e-9 * want
    check(rms_ok, f"5 every band of the base stack record holds stack_scale_rms for hx, hy, the RMS of the members' "
                  f"scales ({len(bs['bands'])} bands)")
    check(side.get("units") == intersite.STACK_UNITS and bs.get("units") == intersite.STACK_UNITS,
          "5 the sidecar's units and the base_stack block's units are STACK_UNITS")
    rms = {round(b["period"], 9): b["stack_scale_rms"] for b in bs["bands"]}
    field = MT * np.exp(1j * np.radians(PHI0_DEG)) / SIGNAL
    misfit, raw = [], []
    for b, p in enumerate(est.period):
        diag = np.array([est.tensor[b, 0, 0], est.tensor[b, 1, 1]])
        err = np.array([est.sigma[b, 0, 0], est.sigma[b, 1, 1]])
        if not (np.all(np.isfinite(err)) and np.all(err < 0.1 * np.abs(diag))):
            continue
        s = np.array([rms[round(float(p), 9)][r] for r in ROLES])
        back = diag / s
        misfit.append(np.abs(back - np.diag(field)) / np.abs(np.diag(field)))
        raw.append(np.abs(diag - np.diag(field)) / np.abs(np.diag(field)))
    misfit, raw = np.array(misfit), np.array(raw)
    med, med_raw = float(np.median(misfit)), float(np.median(raw))
    check(misfit.size > 0 and med <= 0.03,
          f"5 the diagonal of M over stack_scale_rms is the member field ratio: median relative misfit {med:.4f} "
          f"(at most 0.03) over {misfit.shape[0]} bands, worst {float(misfit.max()):.4f}")
    check(med_raw > 0.5, f"5 control: M on the stack taken as a field ratio misses by {med_raw:.3g} (over 0.5)")


def runs(yaml_path: Path) -> None:
    """Criteria 1-6 through the script."""
    out = SCRATCH / "out"
    base = ("--base-stack", "H", "--out-dir", str(out))

    # 1, 5 and 6. the default run on M1-M5, an E-site reference
    res = run(yaml_path, *base, "--remote", "R", "--remote-channels", "ex,ey", "--exclude", BASE_EXCLUDE)
    stem = "L_hm-stackH_rr-R-E"
    if not check(res.returncode == 0 and (out / f"{stem}.json").exists(), f"1 base stack H run exits "
                                                                           f"{res.returncode}"):
        print(res.stdout[-3000:], res.stderr[-3000:])
        return
    side = read_side(out, stem)
    bs = side.get("base_stack") or {}
    est, letter = intersite.read_csv(out / f"{stem}.csv")
    check(letter == "M", f"1 the CSV holds M (letter {letter})")
    stack_recovery(est, bs, "1 M on the H stack of M1-M5, rr R's E")
    units(est, side)
    left = {x["site"]: x["reason"] for x in bs.get("left_out", [])}
    per_band_ok = all(
        len(m["per_band"]) == len(bs["bands"]) and all(
            (b[r]["scale"] or 0) > 0 and b[r]["rejected"] is not None for b in m["per_band"] for r in ROLES)
        for m in bs.get("members", []))
    ok = (side.get("base_site", "missing") is None and side.get("inputs") == ["stackH hx", "stackH hy"]
          and bs.get("field") == "H" and bs.get("channels") == ["hx", "hy"]
          and [m["site"] for m in bs.get("members", [])] == list(MEMBERS) and per_band_ok
          and left.get("L") == "the local"
          and all(left.get(s) == "excluded on request" for s in ("R", "P") + REF_MEMBERS)
          and bs.get("screen_polarity", {}).get("mode") == "flag" and bs.get("shared_with_reference") == [])
    check(ok, f"6 sidecar: base_site {side.get('base_site', 'missing')}, inputs {side.get('inputs')}, field "
              f"{bs.get('field')}, members {[m['site'] for m in bs.get('members', [])]}, per-band scales "
              f"{per_band_ok}, left out {left}, shared {bs.get('shared_with_reference')}")
    with h5py.File(out / f"{stem}.h5", "r") as f:
        record = json.loads(f.attrs["base_stack_record"])
    check(record == bs.get("bands"), f"6 the h5 carries the base stack's band record ({len(record)} bands)")

    # 2. mutation: the reference the same members' H stack
    res = run(yaml_path, *base, "--remote-stack", "H", "--exclude", BASE_EXCLUDE, "--allow-shared-members")
    stem2 = "L_hm-stackH_rr-stackH"
    if check(res.returncode == 0, f"2 base stack rr the members' own H stack runs (exit {res.returncode})"):
        side2 = read_side(out, stem2)
        est2, _letter = intersite.read_csv(out / f"{stem2}.csv")
        bad = stack_recovery(est2, side2["base_stack"], "2", report=False)
        check(not bad["elements_ok"] and bad["beyond3"] > 0.25 * bad["n"],
              f"2 mutation trips: the shared reference puts {bad['beyond3']} of {bad['n']} element-bands beyond 3 "
              f"sigma (worst {bad['worst']:.1f}); |det| median ratio to the run of 1 "
              f"{np.nanmedian(np.abs(est2.det) / np.abs(est.det)):.4f}")
        check(side2["base_stack"]["shared_with_reference"] == list(MEMBERS),
              f"2 the sidecar records the shared members {side2['base_stack']['shared_with_reference']}")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 3. the reference stack of other sites through --remote-exclude
    res = run(yaml_path, *base, "--remote-stack", "H", "--exclude", BASE_EXCLUDE, "--remote-exclude",
              "M1,M2,M3,M4,M5,P,R", "--tag", "q")
    stem3 = "L_hm-stackH_rr-stackH_q"
    if check(res.returncode == 0, f"3 --remote-exclude run exits {res.returncode}"):
        side3 = read_side(out, stem3)
        ref = side3["reference"]
        bs3 = side3["base_stack"]
        check([m["site"] for m in ref["members"]] == list(REF_MEMBERS) and ref.get("exclude_from") ==
              "--remote-exclude" and [m["site"] for m in bs3["members"]] == list(MEMBERS)
              and bs3["shared_with_reference"] == [],
              f"3 reference members {[m['site'] for m in ref['members']]} ({ref.get('exclude_from')}), base "
              f"members {[m['site'] for m in bs3['members']]}, shared {bs3['shared_with_reference']}")
        est3, _letter = intersite.read_csv(out / f"{stem3}.csv")
        stack_recovery(est3, bs3, "1 M on the H stack of M1-M5, rr the H stack of Q1-Q3")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 4. polarity: flag, then drop
    res = run(yaml_path, *base, "--remote", "R", "--remote-channels", "ex,ey", "--exclude", "R,Q1,Q2,Q3",
              "--tag", "flag")
    if check(res.returncode == 0, f"4 flag run exits {res.returncode}"):
        bs4 = read_side(out, "L_hm-stackH_rr-R-E_flag")["base_stack"]
        flags = {(f["site"], f["channel"]): f for f in bs4["screen_polarity"]["flags"]}
        p_hx = flags.get(("P", "hx"), {})
        others = [k for k, f in flags.items() if f["flagged"] and k != ("P", "hx")]
        kept = [m["site"] for m in bs4["members"] if not m["dropped"]]
        corr = {f"{s}_{c}": f["correlation"] for (s, c), f in flags.items()}
        check(p_hx.get("flagged") and p_hx["correlation"] < -0.5 and not others and "P" in kept
              and "polarity: P hx median correlation" in res.stdout,
              f"4 flag: P hx flagged at {p_hx.get('correlation')}, other flags {others}, P kept {'P' in kept}; "
              f"correlations {corr}")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])
    res = run(yaml_path, *base, "--remote", "R", "--remote-channels", "ex,ey", "--exclude", "R,Q1,Q2,Q3",
              "--screen-polarity", "drop", "--tag", "drop")
    stem5 = "L_hm-stackH_rr-R-E_drop"
    if check(res.returncode == 0, f"4 drop run exits {res.returncode}"):
        bs5 = read_side(out, stem5)["base_stack"]
        dropped = [m["site"] for m in bs5["members"] if m["dropped"]]
        in_record = sorted({s for b in bs5["bands"] for s in b["members"]})
        with h5py.File(out / f"{stem5}.h5", "r") as f:
            h5_members = [v.decode() if isinstance(v, bytes) else str(v) for v in f.attrs["base_stack_members"]]
        check(dropped == ["P"] and bs5["screen_polarity"]["dropped"] == ["P"] and in_record == list(MEMBERS)
              and h5_members == list(MEMBERS),
              f"4 drop: dropped {dropped}, band record members {in_record}, h5 members {h5_members}")
        est5, _letter = intersite.read_csv(out / f"{stem5}.csv")
        stack_recovery(est5, bs5, "1 M on the H stack after the screen dropped P")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])


def main() -> int:
    """Run every criterion; return 1 on any failure."""
    yaml_path = build_survey()
    out = SCRATCH / "out"
    shutil.rmtree(out, ignore_errors=True)
    command_line(yaml_path, out)
    runs(yaml_path)
    print(f"\n{len(failures)} failure(s)")
    for msg in failures:
        print("  " + msg)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
