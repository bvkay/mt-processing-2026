# -*- coding: utf-8 -*-
"""
Unit test for the band-domain stack of mt_workbench.intersite and process_intersite.py's stack forms

The fields are those of tests/intersite_unit.py (`fields`): red-noise
sources, the base's electric field E and a local's E = T E_base. Each
stack member's ex, ey is 0.8 of the base's E without its noise plus its own
noise (0.2 of E's spectrum), so the members share one common signal, the
clean E, and differ in their noise. A scratch survey at 100 Hz holds 3 h of
the pair L, B and the sites

- M1-M5, the stack's members; M3 carries a fault over 5 % of the record
  (from 60 % to 65 % of it): red noise 1000 times M3's own RMS added to its
  ex and ey;
- N3, M3 without the fault (the fault-free stack's third member);
- W, a member whose ex and ey carry a slow drift (periods of 1500 and
  2300 s) over the first half of the record only, under a smooth envelope,
  so its RMS is about 20 times larger in the first half than in the second
  while its power at periods of 20 s and shorter does not change.

"The clean signal" is the base's E without its noise. The multiple
coherence of a stack with it is that of each clean component on the
stack's two channels (`intersite._mcoh`), the lower of the two, per band,
over the band's windows. The bands judged are those of 20 s and shorter
(the drift's periods lie above them).

Usage:
    python tests/intersite_stack_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (fault) in any judged band, the band stack of M1-M5 (each member over
   its per-band scale, a member's window over 25 times the array level
   left out) has a multiple coherence with the clean signal more than 0.02
   below the band stack of M1, M2, N3, M4, M5 (the same members without
   the fault); or the plain stack of M1-M5 (`stack_channels`: each member
   over its RMS over the window, the mean in the time domain) is not at
   least 0.02 below the fault-free stack in every judged band (the control
   that the fault matters and that criterion 1 can see it); or M3 is not
   rejected in 3-12 % of its windows in every judged band, or another
   member in more than 0.5 % of them;
2. (mutation, must trip 1) the band stack of M1-M5 with rejection disabled
   (a threshold of 1e12) stays within 0.02 of the fault-free stack in
   every judged band;
3. (scale) with members M1, M2, M4, M5 and W and no fault, in any judged
   band W's normalised power over the array level, its median over each
   half of the record, lies outside 0.5-2 in the band stack, or W is
   rejected in more than 0.5 % of its windows; or, as the control that the
   whole-window RMS is the wrong scale, the same ratio with each member's
   band power divided by its RMS over the window squared (the plain
   stack's weighting, from `stack_channels`' record) is not under 0.1 in
   both halves; or W's RMS ratio between the halves is not 15-25;
4. (no rejection) a threshold of 1e12 rejects any window, or its stack
   differs by more than 1e-5 (relative, worst window) from the mean of the
   members' spectra each divided by the square root of its median band
   power, computed here without `stack_band`;
5. (optional channels) `band_spectra` with the members as optional
   channels changes the windows or a bit of the other channels' spectra;
   or a member with a 30-min gap is not NaN in exactly the windows
   touching its gap carried down the levels, or elsewhere differs from the
   same member without the gap by more than 1e-3 (relative band power,
   worst window);
6. (plain, identical) process_intersite.py `--remote-stack E
   --stack-plain` writes a CSV that differs by one byte from the CSV of
   the pipeline the script ran before the band stack (`stack_channels`,
   `band_spectra`, `estimate`, `write_csv`) on the same window;
7. (the record) the default run's sidecar reference block lacks form
   "band", reject_factor 25, min_members 2 or a band record whose M3
   rejected fractions are those of criterion 1, or its h5 lacks the same
   record as JSON; the --stack-plain sidecar's form is not "plain"; the dry
   runs do not print "stack_form: band" and "stack_form: plain"; or the
   script accepts --stack-plain without --remote-stack, a threshold of 1,
   --stack-reject-factor with --stack-plain, or --stack-min-members over
   the members (each must exit 2).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import FS2, T_START, fields, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("intersite_stack_unit")
HOURS = 3.0
MEMBERS = ("M1", "M2", "M3", "M4", "M5")
FREE = ("M1", "M2", "N3", "M4", "M5")
SWING = ("M1", "M2", "M4", "M5", "W")
FAULT_SPAN = (0.60, 0.65)  # the fault's part of the record
FAULT_GAIN = 1000.0
JUDGED_MAX_PERIOD = 20.0
ROLES = ("ex", "ey")

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


SURVEY_YAML = """name: intersite_stack_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0}}
  B: {{latitude: -31.01, longitude: 137.0}}
  M1: {{latitude: -31.1, longitude: 137.1}}
  M2: {{latitude: -31.2, longitude: 137.1}}
  M3: {{latitude: -31.3, longitude: 137.1}}
  M4: {{latitude: -31.4, longitude: 137.1}}
  M5: {{latitude: -31.5, longitude: 137.1}}
  N3: {{latitude: -31.6, longitude: 137.1}}
  W: {{latitude: -31.7, longitude: 137.1}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""


def build_survey() -> tuple[Path, dict]:
    """Write the scratch survey and its archives; return survey.yaml and the spectra (with ``rms_halves`` of W)."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    spec = fields(FS2, HOURS, seed=11, h_sites=("l", "b", "m1", "m2", "m3", "m4", "m5", "w"))
    n = spec["n"]
    # the base's E at 1e3 rms: the fault (1e3 times a member) stays well inside int32 counts
    spec["scale"] = 1.0e3 / float(np.std(np.fft.irfft(spec["b_ex"], n)))
    for c in ("ex", "ey", "hx", "hy"):
        spec[f"n3_{c}"] = spec[f"m3_{c}"].copy()
    rng = np.random.default_rng(23)
    f = spec["f"]
    shape = np.maximum(f, f[1]) ** -0.5
    t = np.arange(n) / FS2
    a, b = (int(x * n) for x in FAULT_SPAN)
    first = t < t[-1] / 2.0
    envelope = np.where(first, np.sin(np.pi * t / (t[-1] / 2.0)) ** 2, 0.0)
    rms_halves = {}
    for c in ROLES:
        # the fault: red noise FAULT_GAIN times M3's own RMS over [a, b)
        own = np.fft.irfft(spec[f"m3_{c}"], n)
        noise = np.fft.irfft((rng.standard_normal(f.size) + 1j * rng.standard_normal(f.size)) * shape, n)
        fault = np.zeros(n)
        fault[a:b] = noise[a:b] / np.std(noise[a:b]) * FAULT_GAIN * np.std(own)
        spec[f"m3_{c}"] = spec[f"m3_{c}"] + np.fft.rfft(fault)
        # W's drift: two slow sinusoids over the first half, under a smooth envelope
        w = np.fft.irfft(spec[f"w_{c}"], n)
        phase = rng.uniform(0, 2 * np.pi, 2)
        drift = envelope * (np.sin(2 * np.pi * t / 1500.0 + phase[0]) + np.sin(2 * np.pi * t / 2300.0 + phase[1]))
        drift *= 32.0 * np.std(w)
        spec[f"w_{c}"] = spec[f"w_{c}"] + np.fft.rfft(drift)
        w = w + drift
        rms_halves[c] = float(np.std(w[first]) / np.std(w[~first]))
    spec["rms_halves"] = rms_halves
    for site in ("L", "B") + MEMBERS + ("N3", "W"):
        write_site(work, site, spec, T_START, n)
    return yaml_path, spec


def run(yaml_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run process_intersite.py on the scratch survey, a telluric pair L on B."""
    return subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), "L", "B", "--kind", "telluric", *args],
                          capture_output=True, text=True, cwd=REPO)


def read_members(survey, sites, t0: int, n: int) -> tuple[dict, dict, list]:
    """Read the sites' ex, ey under the band stack's keys; return arrays, responses and (site, keys) per member."""
    from mt_workbench.ingest import processing_archive

    arrays, responses, members = {}, {}, []
    for site in sites:
        got, resp, _chains = intersite.read_channels(processing_archive(survey, site, True), site, ROLES, t0, n, FS2)
        keys = {r: f"{site}_{r}" for r in ROLES}
        arrays.update({keys[r]: got[r] for r in ROLES})
        responses.update({keys[r]: resp[r] for r in ROLES})
        members.append((site, keys))
    return arrays, responses, members


def stack_of(band, members, reject_factor=intersite.STACK_REJECT_FACTOR):
    """Return the band stack of one band, (BandSpectra or None, the band's record)."""
    record: list = []
    out = list(intersite.band_stack([band], members, {"ex": "r_ex", "ey": "r_ey"}, reject_factor, 2, record))
    return (out[0] if out else None), record[0]


def coherence(band, keys=("r_ex", "r_ey")) -> float:
    """Return the lower multiple coherence of the clean components on the stack's two channels."""
    X = np.column_stack([band.spectra[k].reshape(-1) for k in keys]).astype(np.complex128)
    return min(intersite._mcoh(band.spectra[c].reshape(-1).astype(np.complex128), X) for c in ("c_ex", "c_ey"))


def subset(band, keep: np.ndarray, keys) -> intersite.BandSpectra:
    """Return the band on the kept windows with the given channels only."""
    return intersite.BandSpectra(band.level, band.f_lo, band.f_hi, band.freqs, band.t_mid[keep], band.record_s,
                                 {k: band.spectra[k][keep] for k in keys})


def fault_and_scale(yaml_path: Path, spec: dict) -> None:
    """Criteria 1-5 in process."""
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(yaml_path)
    scheme = build_band_scheme(FS2, **survey.processing)
    n, t0 = spec["n"], int(T_START.tz_localize("UTC").value)
    sites = sorted(set(MEMBERS) | set(FREE) | set(SWING))
    arrays, responses, _members = read_members(survey, sites, t0, n)
    members = {site: {r: f"{site}_{r}" for r in ROLES} for site in sites}
    plain, _info = intersite.stack_channels(survey, list(MEMBERS), ROLES, t0, n, FS2)
    _plain_swing, info_swing = intersite.stack_channels(survey, list(SWING), ROLES, t0, n, FS2)
    rms = {m["site"]: m["rms"] for m in info_swing}
    del _plain_swing
    clean = {f"c_{r}": np.fft.irfft(spec[f"src_{r}"], n).astype(np.float32) for r in ROLES}
    arrays.update(clean)
    arrays.update({f"p_{r}": plain[r] for r in ROLES})
    optional = [f"{s}_{r}" for s in sites for r in ROLES]
    # 5. the same bands without the optional members, and a member with a gap of 30 min
    base_only = {k: arrays[k].copy() for k in ("c_ex", "c_ey", "p_ex", "p_ey")}
    gap_a, gap_b = int(0.25 * n), int(0.25 * n + 1800 * FS2)
    gapped = arrays["M1_ex"].copy()
    gapped[gap_a:gap_b] = np.nan
    arrays["G_ex"] = gapped
    responses["G_ex"] = responses["M1_ex"]
    bands = list(intersite.band_spectra(arrays, FS2, scheme, responses, optional=optional + ["G_ex"]))
    bands_ref = list(intersite.band_spectra(base_only, FS2, scheme))
    same = len(bands) == len(bands_ref) and all(
        np.array_equal(a.t_mid, b.t_mid) and all(np.array_equal(a.spectra[k], b.spectra[k]) for k in b.spectra)
        for a, b in zip(bands, bands_ref))
    check(same, f"5 the optional members leave the other channels' windows and spectra unchanged ({len(bands)} "
                f"bands)")
    gap_ok, worst_gap = True, 0.0
    level_gaps: dict = {}
    for band in bands:
        if band.level not in level_gaps:
            g, n_level = [(gap_a, gap_b)], n
            for _ in range(band.level):
                n_level = -(-n_level // 4)  # scipy's decimate keeps ceil(n / 4) samples
                g = intersite._carry_gaps(g, 4, n_level)
            level_gaps[band.level] = g
        # a window [start, start + win] at this level touches the gap carried down
        win = scheme["num_samples_window"][band.level]
        fs_level = FS2 / 4 ** band.level
        starts = np.rint(band.t_mid * fs_level - win / 2.0).astype(int)
        (ga, gb), = level_gaps[band.level]
        touch = (starts < gb) & (starts + win + 1 > ga)
        nan = ~np.all(np.isfinite(band.spectra["G_ex"]), axis=1)
        gap_ok &= bool(np.array_equal(nan, touch))
        p_g = np.mean(np.abs(band.spectra["G_ex"][~nan]) ** 2, axis=1)
        p_m = np.mean(np.abs(band.spectra["M1_ex"][~nan]) ** 2, axis=1)
        if p_m.size:
            worst_gap = max(worst_gap, float(np.max(np.abs(p_g / p_m - 1.0))))
    check(gap_ok and worst_gap <= 1e-3, f"5 a member's 30-min gap: NaN in exactly the windows touching it on every "
                                        f"level ({gap_ok}); elsewhere its band power within {worst_gap:.2e} of "
                                        f"the member without the gap (at most 1e-3)")

    judged = [b for b in bands if b.period <= JUDGED_MAX_PERIOD]
    rows = []
    for band in judged:
        robust, rec = stack_of(band, [(s, members[s]) for s in MEMBERS])
        free, _rec_free = stack_of(band, [(s, members[s]) for s in FREE])
        open_, _rec_open = stack_of(band, [(s, members[s]) for s in MEMBERS], reject_factor=1e12)
        full = np.ones(band.n_windows, dtype=bool)
        rows.append({"period": band.period,
                     "free": coherence(free), "robust": coherence(robust), "open": coherence(open_),
                     "plain": coherence(subset(band, full, ("c_ex", "c_ey", "p_ex", "p_ey")), ("p_ex", "p_ey")),
                     "m3_rej": max(rec["members"]["M3"][r]["rejected"] for r in ROLES),
                     "other_rej": max(rec["members"][s][r]["rejected"] for s in MEMBERS if s != "M3" for r in ROLES),
                     "left_out": rec["left_out"]})
    df = pd.DataFrame(rows)
    df["robust_d"] = df.free - df.robust
    df["plain_d"] = df.free - df.plain
    df["open_d"] = df.free - df.open
    print(df.round(4).to_string(index=False))
    check(df.robust_d.max() <= 0.02,
          f"1 the band stack with M3's fault stays within 0.02 of the fault-free stack in all {len(df)} bands of "
          f"{JUDGED_MAX_PERIOD:g} s and shorter (largest drop {df.robust_d.max():+.4f}; fault-free coherence "
          f"{df.free.min():.4f}-{df.free.max():.4f})")
    check(df.plain_d.min() >= 0.02,
          f"1 control: the plain stack with M3's fault drops {df.plain_d.min():.4f}-{df.plain_d.max():.4f} below the "
          f"fault-free stack (at least 0.02 in every band)")
    check(df.m3_rej.between(0.03, 0.12).all() and df.other_rej.max() <= 0.005,
          f"1 M3 rejected in {df.m3_rej.min():.4f}-{df.m3_rej.max():.4f} of its windows per band (3-12 %), the "
          f"others in at most {df.other_rej.max():.4f}")
    check(df.open_d.max() > 0.02,
          f"2 mutation trips: rejection disabled (threshold 1e12) drops up to {df.open_d.max():.4f} below the "
          f"fault-free stack (median {df.open_d.median():.4f})")

    # 3. W's 20x RMS swing between the halves
    ratio = spec["rms_halves"]
    check(all(15.0 <= v <= 25.0 for v in ratio.values()),
          "3 W's RMS, first half over second: " + ", ".join(f"{r} {v:.1f}" for r, v in ratio.items()))
    rows = []
    for band in judged:
        half = band.t_mid < band.record_s / 2.0
        for r in ROLES:
            X = np.stack([band.spectra[f"{s}_{r}"] for s in SWING])
            res = intersite.stack_band(X)
            w = SWING.index("W")
            robust_ratio = res["power"][w] / res["level"]
            pw = np.mean(np.abs(X.astype(np.complex128)) ** 2, axis=2)
            # the plain stack's weighting: each member's band power over its RMS over the window squared;
            # the RMS is in counts and the spectra calibrated, and every member here has the same gain
            plain_p = pw / np.array([rms[s][r] for s in SWING])[:, None] ** 2
            plain_ratio = plain_p[w] / np.median(plain_p, axis=0)
            rows.append({"period": band.period, "role": r,
                         "robust_h1": float(np.median(robust_ratio[half])),
                         "robust_h2": float(np.median(robust_ratio[~half])),
                         "plain_h1": float(np.median(plain_ratio[half])),
                         "plain_h2": float(np.median(plain_ratio[~half])),
                         "w_rej": float(res["rejected"][w].mean())})
    sw = pd.DataFrame(rows)
    print(sw.round(4).to_string(index=False))
    robust_vals = sw[["robust_h1", "robust_h2"]].to_numpy()
    plain_vals = sw[["plain_h1", "plain_h2"]].to_numpy()
    check(((robust_vals >= 0.5) & (robust_vals <= 2.0)).all() and sw.w_rej.max() <= 0.005,
          f"3 band stack: W's normalised power over the array level, median per half, "
          f"{robust_vals.min():.3f}-{robust_vals.max():.3f} (0.5-2) in every judged band; W rejected in at most "
          f"{sw.w_rej.max():.4f} of its windows")
    check((plain_vals < 0.1).all(),
          f"3 control: under the whole-window RMS W sits at {plain_vals.min():.4f}-{plain_vals.max():.4f} of the "
          f"array level (under 0.1 in both halves)")

    # 4. a threshold so large that no window is rejected: the per-band scale alone, computed here
    worst, rejected = 0.0, 0
    for band in bands:
        X = np.stack([band.spectra[f"{s}_ex"] for s in MEMBERS]).astype(np.complex128)
        res = intersite.stack_band(X.astype(np.complex64), reject_factor=1e12)
        rejected += int(res["rejected"].sum())
        scale = np.sqrt(np.median(np.mean(np.abs(X) ** 2, axis=2), axis=1))
        expect = np.mean(X / scale[:, None, None], axis=0)
        dev = np.abs(res["stack"] - expect).max(axis=1) / np.abs(expect).max(axis=1)
        worst = max(worst, float(dev.max()))
    check(rejected == 0 and worst <= 1e-5, f"4 threshold 1e12: {rejected} windows rejected, the stack equals the "
                                           f"per-band-scaled mean to {worst:.2e} (worst window, relative)")


def script_runs(yaml_path: Path, spec: dict) -> None:
    """Criteria 6 and 7 through the script."""
    from mt_workbench.ingest import processing_archive
    from mt_workbench.survey import Survey

    out = SCRATCH / "out"
    shutil.rmtree(out, ignore_errors=True)
    common = ("--remote-stack", "E", "--exclude", "N3,W", "--out-dir", str(out))
    stem = "L_te-B_rr-stackE"

    # 7. the dry runs and the refusals
    res = run(yaml_path, *common, "--dry-run")
    check(res.returncode == 0 and "stack_form: band" in res.stdout, f"7 dry run prints stack_form: band (exit "
                                                                     f"{res.returncode})")
    res = run(yaml_path, *common, "--stack-plain", "--dry-run")
    check(res.returncode == 0 and "stack_form: plain" in res.stdout, f"7 dry run with --stack-plain prints "
                                                                      f"stack_form: plain (exit {res.returncode})")
    for label, args in (("--stack-plain without --remote-stack", ("--remote", "M1", "--stack-plain")),
                        ("a threshold of 1", common + ("--stack-reject-factor", "1")),
                        ("--stack-reject-factor with --stack-plain",
                         common + ("--stack-plain", "--stack-reject-factor", "30")),
                        ("--stack-min-members over the members", common + ("--stack-min-members", "9"))):
        res = run(yaml_path, *args, "--dry-run")
        check(res.returncode == 2, f"7 refused, exit {res.returncode}: {label}: "
                                   f"{(res.stderr.strip().splitlines() or [''])[-1][:110]}")
    check(not out.exists(), "7 the dry runs and refusals wrote nothing")

    # 6. --stack-plain against the earlier pipeline on the same window
    res = run(yaml_path, *common, "--stack-plain", "--tag", "plain")
    if check(res.returncode == 0, f"6 --stack-plain run exits {res.returncode}"):
        side = json.loads((out / f"{stem}_plain.json").read_text(encoding="utf-8"))
        check(side["reference"].get("form") == "plain", f"7 --stack-plain sidecar form {side['reference'].get('form')}")
        survey = Survey.from_yaml(yaml_path)
        t0 = int(pd.Timestamp(side["window"]["start"]).value)
        n = int(side["window"]["samples"])
        arrays, responses = {}, {}
        for prefix, site in (("l_", "L"), ("b_", "B")):
            got, resp, _ = intersite.read_channels(processing_archive(survey, site, True), site, ROLES, t0, n, FS2)
            arrays.update({prefix + r: got[r] for r in ROLES})
            responses.update({prefix + r: resp[r] for r in ROLES})
        got, _info = intersite.stack_channels(survey, [m["site"] for m in side["reference"]["members"]], ROLES, t0,
                                              n, FS2, True)
        arrays.update({"r_" + r: got[r] for r in ROLES})
        scheme = build_band_scheme(FS2, **side["band_scheme"])
        est = intersite.estimate(intersite.band_spectra(arrays, FS2, scheme, responses), ("l_ex", "l_ey"),
                                 ("b_ex", "b_ey"), ("r_ex", "r_ey"))
        earlier = intersite.write_csv(est, "T", SCRATCH / "earlier_plain.csv")
        a, b = earlier.read_bytes(), (out / f"{stem}_plain.csv").read_bytes()
        check(a == b, f"6 --stack-plain CSV is identical to the earlier pipeline's ({len(b)} bytes, members "
                      f"{[m['site'] for m in side['reference']['members']]})")
    else:
        print(res.stdout[-3000:], res.stderr[-3000:])

    # 7. the default run's record
    res = run(yaml_path, *common)
    if not check(res.returncode == 0, f"7 band stack run exits {res.returncode}"):
        print(res.stdout[-3000:], res.stderr[-3000:])
        return
    side = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
    ref = side["reference"]
    judged = [b for b in ref.get("bands", []) if b["period"] <= JUDGED_MAX_PERIOD]
    m3 = [max(b["members"]["M3"][r]["rejected"] for r in ROLES) for b in judged]
    others = [b["members"][s][r]["rejected"] for b in judged for s in MEMBERS if s != "M3" for r in ROLES]
    scales = all(b["members"][s][r]["scale"] for b in ref.get("bands", []) for s in MEMBERS for r in ROLES)
    ok = (ref.get("form") == "band" and ref.get("reject_factor") == 25.0 and ref.get("min_members") == 2
          and [m["site"] for m in ref["members"]] == list(MEMBERS) and judged and scales
          and all(0.03 <= x <= 0.12 for x in m3) and max(others) <= 0.005)
    check(bool(ok), f"7 sidecar: form {ref.get('form')}, reject_factor {ref.get('reject_factor')}, min_members "
                    f"{ref.get('min_members')}, {len(ref.get('bands', []))} bands recorded; M3 rejected "
                    f"{min(m3):.4f}-{max(m3):.4f}, the others at most {max(others):.4f} in the bands of "
                    f"{JUDGED_MAX_PERIOD:g} s and shorter; windows left out {ref['summary']['windows_left_out']}")
    with h5py.File(out / f"{stem}.h5", "r") as f:
        record = json.loads(f.attrs["stack_record"])
        form = f.attrs["stack_form"]
    form = form.decode() if isinstance(form, bytes) else form
    check(form == "band" and record == ref["bands"], f"7 the h5 carries the stack's form ({form}) and the sidecar's "
                                                     f"band record")


def main() -> int:
    """Run every criterion; return 1 on any failure."""
    yaml_path, spec = build_survey()
    fault_and_scale(yaml_path, spec)
    script_runs(yaml_path, spec)
    print(f"\n{len(failures)} failure(s)")
    for msg in failures:
        print("  " + msg)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
