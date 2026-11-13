# -*- coding: utf-8 -*-
"""
Unit test for process_intersite.py --base-stack E: the band stack of the members' E as the base

The fields are those of tests/intersite_unit.py (`fields`): red-noise
sources Bx, By, the clean regional electric field E (the base's E there,
without its noise) and a local whose E is a known T applied to it,

    E_local = A exp(i phi0) exp(-2 pi i f tau) E + noise,
    A = [[1.10, 0.10], [-0.05, 0.90]], phi0 = -1.5 deg, tau = 2 ms.

A scratch survey at 100 Hz holds 3 h of the sites

- L, the local;
- M1-M5, the base stack's members: ex, ey = 0.8 E + noise of 0.5 of E's
  spectrum each, so the members share the clean E and differ in their
  noise (the mean of five keeps about 6 % of E's power in ex as noise);
- R, the reference: hx, hy = B + its own noise (RR-like), and an E of its
  own (0.8 E + noise), so that R qualifies as a member of the base stack;
- P, a member whose ex is reversed (-0.8 Ex + noise), its ey as M1's are;
- X, a member whose record ends 2.5 h into the 3 h.

Every channel is written as int32 counts through its filter chain
(`intersite_unit.write_site`). The band stack divides each member by its
per-band scale s, so in a band the stack's channel r is
0.8 mean_m(1 / s_m,r) E_r plus noise, and the expected T on the stack is
the band's expected T (`intersite_unit.expected`) with its column r divided
by 0.8 mean_m(1 / s_m,r), the scales those the sidecar records. That
diagonal is real and positive, so arg(det T) / 2 and the delay are those
of A.

Usage:
    python tests/intersite_basestack_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (recovery) the run `L --base-stack E --remote R --exclude R,P,X`
   (members M1-M5) has, of its element-bands with a finite error, more
   than 5 % beyond 3 sigma of the expected T on the stack or any beyond 5
   sigma; or its timing check's tau differs from +2 ms by more than
   max(3 sigma, 0.05 ms) or its intercept from phi0 by more than
   max(3 sigma, 0.1 deg); the same for the `--screen-polarity drop` run of
   criterion 4 against the scales of the members it kept;
2. (mutation, must trip 1) the same base stack referenced to the stack of
   the same members' E (`--remote-stack E --allow-shared-members`, the
   reference then sharing every member's noise with the inputs) passes
   criterion 1's 3-sigma count, or puts 25 % or fewer of the element-bands
   beyond 3 sigma; or that run's sidecar does not record the five shared
   members;
3. (membership) with X a member (`--exclude R,P --min-overlap-hours 2`)
   the dry run does not exit 2 naming "X ends at" its last sample's time
   (02:29:59 or 02:30:00); or the run with `--allow-member-change` fails,
   or its sidecar's base_stack does not hold that one change with
   window_members_constant false; or, as the control of the 60 s
   tolerance at the edges, the dry run over a window ending 30 s after X's
   last sample does not pass with no member_change line; or
   `--window-members-constant` with `--allow-member-change` is not refused;
4. (polarity) with P a member (`--exclude R,X`) the flag run's sidecar does
   not flag P's ex with a correlation under -0.5, or flags P's ey or any
   channel of M1-M5, or leaves P out of the stack, or the log lacks the
   flag line; the `--screen-polarity drop` run does not mark P dropped,
   keeps P in its band record or in the h5's base_stack_members, or fails
   criterion 1; or, as the control that the flag can stay down, the screen
   over the same archives with P's ex sign restored (its spectra negated
   in `polarity_screen`'s input) flags anything;
5. (shared members) `--remote R` with R in the base stack (`--exclude
   P,X`) is not refused with exit 2 naming R and errors in variables, or
   with `--allow-shared-members` the dry run does not pass printing
   "shared_members: R";
6. (the sidecar's base block) the run of criterion 1 has a stem other
   than L_te-stackE_rr-R, a base_site that is not null, inputs other than
   "stackE ex", "stackE ey", or a base_stack lacking: channels [ex, ey];
   members exactly M1-M5, each with a per-band record of a positive
   scale and a rejected fraction for ex and ey in every band; the local
   left out as "the local" and local_excluded L; R, P and X left out as
   excluded; a summary of the windows left out; a window equal to the
   sidecar's; window_members_constant true and no change; the polarity
   mode flag; no shared site; or its h5 lacks the same band record;
7. (the command line) a site named where the start goes with
   `--base-stack`, `--stack-plain` or `--kind magnetic` with
   `--base-stack`, a base-stack option without `--base-stack`, or no base
   and no `--base-stack` is not refused with exit 2; the dry run with
   start and end as the two positionals after the local does not print
   that 2.00 h window, the members M1-M5 as base_member lines and
   "polarity_screen: flag"; or a dry run or refusal writes a file.
"""

from __future__ import annotations

import json
import re
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
from intersite_unit import A, FS2, PHI0_DEG, T_START, TAU_S, expected, fields, freqs_by_period, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("intersite_basestack_unit")
HOURS = 3.0
X_HOURS = 2.5
MEMBERS = ("M1", "M2", "M3", "M4", "M5")
MEMBER_NOISE = 0.5  # of E's spectrum, per member
SIGNAL = 0.8  # each member's share of the clean E
ROLES = ("ex", "ey")

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


SURVEY_YAML = """name: intersite_basestack_unit
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
  X: {{latitude: -31.7, longitude: 137.1}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""


def build_survey() -> tuple[Path, dict]:
    """Write the scratch survey and its archives; return survey.yaml and the spectra."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    sites = ("l", "r", "m1", "m2", "m3", "m4", "m5", "p", "x")
    spec = fields(FS2, HOURS, seed=17, h_sites=sites)
    n, f = spec["n"], spec["f"]
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["src_ex"], n)))
    rng = np.random.default_rng(29)
    fpos = np.maximum(f, f[1])
    e_shape = np.sqrt(fpos) * fpos**-1.0 * 1.75  # as `fields` shapes E's noise

    def white():
        w = rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)
        w[0] = 0.0
        return w

    for site in ("m1", "m2", "m3", "m4", "m5", "p", "x"):
        for c in ROLES:
            spec[f"{site}_{c}"] = SIGNAL * spec[f"src_{c}"] + MEMBER_NOISE * white() * e_shape
    spec["p_ex"] = -SIGNAL * spec["src_ex"] + MEMBER_NOISE * white() * e_shape
    for site in ("L", "R", "P") + MEMBERS:
        write_site(work, site, spec, T_START, n)
    write_site(work, "X", spec, T_START, int(X_HOURS * 3600 * FS2))
    return yaml_path, spec


def run(yaml_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run process_intersite.py on the scratch survey with the local L."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "L", "--kind", "telluric", *args],
                          capture_output=True, text=True, cwd=REPO)


def last_line(res: subprocess.CompletedProcess) -> str:
    """Return the last line of stderr, shortened."""
    return (res.stderr.strip().splitlines() or [""])[-1][:160]


def model_bands(yaml_path: Path) -> dict:
    """Return period -> the band's harmonics for the scratch survey's scheme (one pass over noise)."""
    from mt_workbench.survey import Survey

    scheme = build_band_scheme(FS2, **Survey.from_yaml(yaml_path).processing)
    probe = {"a": np.random.default_rng(1).standard_normal(int(HOURS * 3600 * FS2)).astype(np.float32)}
    return freqs_by_period(intersite.band_spectra(probe, FS2, scheme))


def stack_recovery(est, fmap: dict, base_stack: dict, label: str, report: bool = True) -> dict:
    """Judge criterion 1: the estimate against A with each column over 0.8 mean(1 / s) of the kept members.

    Args:
        est (TensorEstimate): The estimate read back from the CSV.
        fmap (dict): period -> the band's harmonics.
        base_stack (dict): The sidecar's base_stack block.
        label (str): For the printed lines.
        report (bool): Record PASS/FAIL lines.

    Returns:
        dict: n, beyond3, beyond5, worst, elements_ok, timing_ok, tau, intercept.
    """
    scales = {}  # period -> role -> [scale per kept member]
    for m in base_stack["members"]:
        if m.get("dropped"):
            continue
        for b in m["per_band"]:
            for r in ROLES:
                scales.setdefault(round(b["period"], 9), {}).setdefault(r, []).append(b[r]["scale"])
    dev = []
    for b, p in enumerate(est.period):
        key = round(float(p), 9)
        k = np.array([SIGNAL * np.mean(1.0 / np.array(scales[key][r])) for r in ROLES])
        exp = expected(fmap[key], A, PHI0_DEG, TAU_S) / k[None, :]
        d = np.abs(est.tensor[b] - exp) / est.sigma[b]
        dev += [x for x in d.ravel() if np.isfinite(x)]
    dev = np.array(dev)
    n3, n5 = int((dev > 3).sum()), int((dev > 5).sum())
    elements_ok = dev.size > 0 and n3 <= 0.05 * dev.size and n5 == 0
    tc = intersite.timing_check(est)
    timing_ok = (tc["tau_ms"] is not None and abs(tc["tau_ms"] - TAU_S * 1e3) <= max(3 * tc["tau_err_ms"], 0.05)
                 and abs(tc["intercept_deg"] - PHI0_DEG) <= max(3 * tc["intercept_err_deg"], 0.1))
    out = {"n": int(dev.size), "beyond3": n3, "beyond5": n5, "worst": float(dev.max()) if dev.size else np.nan,
           "elements_ok": bool(elements_ok), "timing_ok": bool(timing_ok), "tau": tc["tau_ms"],
           "intercept": tc["intercept_deg"]}
    if report:
        check(elements_ok, f"{label}: {n3} of {dev.size} element-bands beyond 3 sigma of A on the stack (at most "
                           f"5 %), {n5} beyond 5 sigma, worst {out['worst']:.2f} sigma")
        check(timing_ok, f"{label}: timing tau {tc['tau_ms']:+.4f} +/- {tc['tau_err_ms']:.4f} ms (expected "
                         f"{TAU_S * 1e3:+.3f}), intercept {tc['intercept_deg']:+.3f} +/- "
                         f"{tc['intercept_err_deg']:.3f} deg (expected {PHI0_DEG:+.2f})")
    return out


def read_side(out: Path, stem: str) -> dict:
    """Read a run's sidecar."""
    return json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))


def command_line(yaml_path: Path, out: Path) -> None:
    """Criteria 5 and 7: the refusals and the dry runs, none of which may write a file."""
    o = ("--out-dir", str(out))
    base = ("--base-stack", "E")
    for label, args in (
            ("a site where the start goes", ("M1",) + base + ("--remote", "R", "--exclude", "R,P,X") + o),
            ("--stack-plain with --base-stack", base + ("--remote", "R", "--exclude", "R,P,X", "--stack-plain") + o),
            ("--kind magnetic with --base-stack", base + ("--remote", "R", "--exclude", "R,P,X", "--kind",
                                                          "magnetic") + o),
            ("--screen-polarity without --base-stack", ("M1", "--remote", "R", "--screen-polarity", "drop") + o),
            ("--allow-member-change without --base-stack", ("M1", "--remote", "R", "--allow-member-change") + o),
            ("no base and no --base-stack", ("--remote", "R") + o),
            ("--window-members-constant with --allow-member-change",
             base + ("--remote", "R", "--exclude", "R,P,X", "--window-members-constant", "--allow-member-change")
             + o)):
        res = run(yaml_path, *args, "--dry-run")
        check(res.returncode == 2, f"7 refused, exit {res.returncode}: {label}: {last_line(res)}")

    res = run(yaml_path, "2024-03-01 00:30", "2024-03-01 02:30", *base, "--remote", "R", "--exclude", "R,P,X",
              *o, "--dry-run")
    got = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("base_member: ")]
    ok = (res.returncode == 0 and "window: 2024-03-01T00:30:00Z to 2024-03-01T02:30:00Z (2.00 h" in res.stdout
          and got == list(MEMBERS) and "polarity_screen: flag" in res.stdout
          and "stem: L_te-stackE_rr-R" in res.stdout)
    check(ok, f"7 dry run with start and end after the local: exit {res.returncode}, base members {got}")
    if res.returncode != 0:
        print(res.stderr[-2000:])

    # 5. R both a base member and the reference
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "P,X", *o, "--dry-run")
    check(res.returncode == 2 and "['R']" in res.stderr and "errors in variables" in res.stderr,
          f"5 R as the reference and a base member refused, exit {res.returncode}: {last_line(res)}")
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "P,X", "--allow-shared-members", *o, "--dry-run")
    check(res.returncode == 0 and "shared_members: R" in res.stdout,
          f"5 --allow-shared-members passes and prints the overlap (exit {res.returncode})")

    # 3. X's record ends inside the window
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "R,P", "--min-overlap-hours", "2", *o, "--dry-run")
    check(res.returncode == 2 and re.search(r"X ends at 2024-03-01T02:(29:59|30:00)Z", res.stderr) is not None,
          f"3 X ending inside the window refused, exit {res.returncode}: {last_line(res)}")
    res = run(yaml_path, "2024-03-01 00:00", "2024-03-01 02:30:30", *base, "--remote", "R", "--exclude", "R,P",
              "--min-overlap-hours", "2", *o, "--dry-run")
    members = [ln.split()[1] for ln in res.stdout.splitlines() if ln.startswith("base_member: ")]
    check(res.returncode == 0 and "member_change:" not in res.stdout and "X" in members,
          f"3 control: a window ending 30 s after X's last sample passes with X a member and no change "
          f"(exit {res.returncode}, members {members})")
    check(not out.exists(), "7 the dry runs and refusals wrote nothing")


def runs(yaml_path: Path, fmap: dict) -> None:
    """Criteria 1-4 and 6 through the script."""
    from mt_workbench.ingest import processing_archive
    from mt_workbench.survey import Survey

    out = SCRATCH / "out"
    base = ("--base-stack", "E", "--out-dir", str(out))

    # 1 and 6. the default run on M1-M5
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "R,P,X")
    stem = "L_te-stackE_rr-R"
    if not check(res.returncode == 0 and (out / f"{stem}.json").exists(), f"1 base stack run exits "
                                                                           f"{res.returncode}"):
        print(res.stdout[-3000:], res.stderr[-3000:])
        return
    side = read_side(out, stem)
    bs = side.get("base_stack") or {}
    est, _letter = intersite.read_csv(out / f"{stem}.csv")
    stack_recovery(est, fmap, bs, "1 T on the E stack of M1-M5, rr R")
    left = {x["site"]: x["reason"] for x in bs.get("left_out", [])}
    per_band_ok = all(
        len(m["per_band"]) == len(bs["bands"]) and all(
            (b[r]["scale"] or 0) > 0 and b[r]["rejected"] is not None for b in m["per_band"] for r in ROLES)
        for m in bs.get("members", []))
    ok = (side.get("base_site", "missing") is None and side.get("inputs") == ["stackE ex", "stackE ey"]
          and bs.get("channels") == ["ex", "ey"] and [m["site"] for m in bs.get("members", [])] == list(MEMBERS)
          and per_band_ok and left.get("L") == "the local" and bs.get("local_excluded") == "L"
          and all(left.get(s) == "excluded on request" for s in ("R", "P", "X"))
          and isinstance(bs.get("summary", {}).get("windows_left_out"), int)
          and bs.get("window", {}).get("start") == side["window"]["start"]
          and bs.get("window", {}).get("end") == side["window"]["end"]
          and bs.get("window_members_constant") is True and bs.get("member_changes") == []
          and bs.get("screen_polarity", {}).get("mode") == "flag" and bs.get("shared_with_reference") == [])
    check(ok, f"6 sidecar: base_site {side.get('base_site', 'missing')}, inputs {side.get('inputs')}, members "
              f"{[m['site'] for m in bs.get('members', [])]}, per-band scales and rejected fractions {per_band_ok}, "
              f"left out {left}, windows left out {bs.get('summary', {}).get('windows_left_out')}, constant "
              f"{bs.get('window_members_constant')}, shared {bs.get('shared_with_reference')}")
    with h5py.File(out / f"{stem}.h5", "r") as f:
        record = json.loads(f.attrs["base_stack_record"])
    check(record == bs.get("bands"), f"6 the h5 carries the base stack's band record ({len(record)} bands)")

    # 2. mutation: the reference the same members' E stack
    res = run(yaml_path, *base, "--remote-stack", "E", "--exclude", "R,P,X", "--allow-shared-members")
    stem2 = "L_te-stackE_rr-stackE"
    if check(res.returncode == 0, f"2 base stack rr the members' own E stack runs (exit {res.returncode})"):
        side2 = read_side(out, stem2)
        est2, _letter = intersite.read_csv(out / f"{stem2}.csv")
        bad = stack_recovery(est2, fmap, side2["base_stack"], "2", report=False)
        check(not bad["elements_ok"] and bad["beyond3"] > 0.25 * bad["n"],
              f"2 mutation trips: the shared reference puts {bad['beyond3']} of {bad['n']} element-bands beyond 3 "
              f"sigma (worst {bad['worst']:.1f}); |det| median ratio to the run of 1 "
              f"{np.nanmedian(np.abs(est2.det) / np.abs(est.det)):.4f}")
        check(side2["base_stack"]["shared_with_reference"] == list(MEMBERS),
              f"2 the sidecar records the shared members {side2['base_stack']['shared_with_reference']}")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 3. the change of membership, run and recorded
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "R,P", "--min-overlap-hours", "2",
              "--allow-member-change", "--tag", "change")
    if check(res.returncode == 0, f"3 --allow-member-change runs (exit {res.returncode})"):
        bs3 = read_side(out, "L_te-stackE_rr-R_change")["base_stack"]
        ch = bs3["member_changes"]
        check(len(ch) == 1 and ch[0]["site"] == "X" and ch[0]["change"] == "ends"
              and bs3["window_members_constant"] is False,
              f"3 the sidecar records the change {ch}, window_members_constant {bs3['window_members_constant']}")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 4. polarity: flag, then drop
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "R,X", "--tag", "flag")
    if check(res.returncode == 0, f"4 flag run exits {res.returncode}"):
        bs4 = read_side(out, "L_te-stackE_rr-R_flag")["base_stack"]
        flags = {(f["site"], f["channel"]): f for f in bs4["screen_polarity"]["flags"]}
        p_ex = flags.get(("P", "ex"), {})
        others = [k for k, f in flags.items() if f["flagged"] and k != ("P", "ex")]
        kept = [m["site"] for m in bs4["members"] if not m["dropped"]]
        corr = {f"{s}_{c}": f["correlation"] for (s, c), f in flags.items()}
        check(p_ex.get("flagged") and p_ex["correlation"] < -0.5 and not others and "P" in kept
              and "polarity: P ex median correlation" in res.stdout,
              f"4 flag: P ex flagged at {p_ex.get('correlation')}, other flags {others}, P kept {'P' in kept}; "
              f"correlations {corr}")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])
    res = run(yaml_path, *base, "--remote", "R", "--exclude", "R,X", "--screen-polarity", "drop", "--tag", "drop")
    stem5 = "L_te-stackE_rr-R_drop"
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
        stack_recovery(est5, fmap, bs5, "1 T on the stack after the screen dropped P")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 4. control: the screen with P's ex sign restored flags nothing
    survey = Survey.from_yaml(yaml_path)
    scheme = build_band_scheme(FS2, **survey.processing)
    n, t0 = int(HOURS * 3600 * FS2), int(T_START.tz_localize("UTC").value)
    arrays, responses, pairs = {}, {}, []
    for site in MEMBERS + ("P",):
        got, resp, _chains = intersite.read_channels(processing_archive(survey, site, True), site, ROLES, t0, n, FS2)
        keys = {r: f"{site}_{r}" for r in ROLES}
        arrays.update({keys[r]: got[r] for r in ROLES})
        responses.update({keys[r]: resp[r] for r in ROLES})
        pairs.append((site, keys))
    got, resp, _chains = intersite.read_channels(processing_archive(survey, "L", True), "L", ROLES, t0, n, FS2)
    arrays["l_ex"] = got["ex"]
    arrays["P_ex"] = -arrays["P_ex"]
    optional = [k for _s, keys in pairs for k in keys.values()]
    record: list = []
    for _band in intersite.polarity_screen(intersite.band_spectra(arrays, FS2, scheme, responses, optional=optional),
                                           pairs, ROLES, record=record):
        pass
    summary = intersite.polarity_summary(record, [s for s, _k in pairs], ROLES)
    flagged = [(f["site"], f["channel"]) for f in summary if f["flagged"]]
    p_ex = next(f for f in summary if f["site"] == "P" and f["channel"] == "ex")
    check(not flagged and p_ex["correlation"] > 0.5,
          f"4 control: P's ex sign restored, flags {flagged}, P ex correlation {p_ex['correlation']:+.3f} over "
          f"{p_ex['bands']} bands")


def main() -> int:
    """Run every criterion; return 1 on any failure."""
    yaml_path, _spec = build_survey()
    fmap = model_bands(yaml_path)
    out = SCRATCH / "out"
    shutil.rmtree(out, ignore_errors=True)
    command_line(yaml_path, out)
    runs(yaml_path, fmap)
    print(f"\n{len(failures)} failure(s)")
    for msg in failures:
        print("  " + msg)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
