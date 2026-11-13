# -*- coding: utf-8 -*-
"""
Unit test for masks.yaml in inter-site runs

A mask leaves out of `mt_workbench.intersite.band_spectra`'s window choice
every window that holds a sample inside it. A window of level L stands for
the base samples of its win + 1 level samples (the first difference takes
one more), each standing for factor**L base samples. The test cuts those
windows by hand from the unmasked bands, using only each window's centre
`t_mid`, and asks for the same T as the masked run.

Part 1 (the array interface): the 20 min record at 100 Hz of
tests/intersite_flags_unit.py, with a noise burst of 30 times the base E's
RMS on the base's ex and ey over 400-460 s, masked as a base entry. Part 2
(the script): the same record written as archives L, B and R of a scratch
survey, with a masks.yaml holding entries of every scope at each site, run
through scripts/process_intersite.py; and a second survey over the same
archives without masks.yaml. Part 3 (the burst grid): three burst archives
at 24 kHz (8 bursts of 2 s every 30 s, written as
tests/intersite_bursts_unit.py writes them), a noise burst in the base's
fourth burst, a mask over that burst and a mask over 0.5 s inside the
sixth, read on the compact grid of `read_bursts`.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (part 1) T, its errors or arg(det)/2 with the base's mask differ from
   T on the same bands with the masked windows cut by hand by more than
   1e-9 (relative, worst band), or a band's window count differs; or the
   mask record's windows per band differ from the hand count;
2. (part 1, control) the unmasked T is within 1e-3 of the hand-cut T, so
   the burst does not move T and an ignored mask would pass criterion 1;
3. (part 1) a mask limited to one band's period changes another band, or
   that band's T is not its hand-cut T to 1e-9;
4. (roles) `mask_role` does not give local for the local and the base and
   remote for the reference, or `site_masks` applies an entry of the wrong
   scope or one naming none of the channels read from the site;
5. (part 2) the script exits non-zero; or its T, errors and arg(det)/2
   differ from the hand-cut T with the entries the roles take (B 400-460 s
   scope local, L 600-630 s scope both, R 1000-1030 s scope remote) by
   more than 1e-9; or, as controls, T cut by every entry of every scope,
   or by none, is within 1e-9 of the script's;
6. (part 2) the sidecar's windows masked per site differ from the hand
   count, its entries applied and left out differ from 1/1/0 (L), 1/1/1
   (B) and 1/1/0 (R) (scope, channels), or the log does not print each
   site's count;
7. (part 2) the survey without masks.yaml gives a T other than the
   unmasked estimate (exactly), or its sidecar counts a masked window;
8. (part 3) on the compact burst grid, T with the masks differs from the
   hand-cut T by more than 1e-9, the record's counts differ from the hand
   count, the 0.5 s mask leaves out none or all of the sixth burst's
   level 0 windows, or (control) spans placed as on a dense grid equal
   the burst grid's.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from _scratch import scratch_dir  # noqa: E402
from intersite_flags_unit import KEYS, SURVEY_YAML, short_record  # noqa: E402
from intersite_unit import T_START, series, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402
from mt_workbench.masks import normalise  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("intersite_masks_unit")
FS = 100.0
E_L, E_B, R = ("l_ex", "l_ey"), ("b_ex", "b_ey"), ("r_hx", "r_hy")
BURST_S = (400.0, 460.0)  # the noise burst on the base's E, s from the first sample
STEM = "L_te-B_rr-R"
# masks.yaml entries, s from the first sample: (site, start, end, scope, channels, applied as)
ENTRIES = [("B", 400, 460, "local", None, "applied"), ("B", 700, 760, "remote", None, "scope"),
           ("B", 900, 930, "both", ["hx"], "channels"), ("L", 600, 630, "both", None, "applied"),
           ("L", 300, 330, "remote", None, "scope"), ("R", 1000, 1030, "remote", None, "applied"),
           ("R", 200, 230, "local", None, "scope")]

failures: list[str] = []


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def iso(seconds: float, t0=T_START) -> str:
    """Return the UTC time `seconds` after t0 as masks.yaml text."""
    return (pd.Timestamp(t0) + pd.Timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def mask(start_s: float, end_s: float, bands="all", scope="local", channels=None, t0=T_START) -> dict:
    """Return a masks.yaml entry over [start_s, end_s) after t0."""
    out = {"start": iso(start_s, t0), "end": iso(end_s, t0), "bands": bands, "reason": "test", "found_by": "time",
           "scope": scope}
    if channels is not None:
        out["channels"] = channels
    return out


def window_s(band, scheme: dict, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Return each window's span [start, end) in s of the grid from its centre (see the module docstring)."""
    factors = list(scheme["decimation_factors"])
    scale = (int(factors[1]) if len(factors) > 1 else 4) ** band.level
    win = int(scheme["num_samples_window"][band.level])
    start = band.t_mid - win * scale / (2.0 * rate)
    return start, start + (win + 1) * scale / rate


def cut(bands, keep_of):
    """Return the bands with the windows `keep_of(band)` marks False removed.

    A band left with fewer than `intersite.MIN_LEVEL_WINDOWS` windows is
    dropped, as `band_spectra` drops a level that holds fewer.
    """
    out = []
    for b in bands:
        keep = keep_of(b)
        if int(keep.sum()) < intersite.MIN_LEVEL_WINDOWS:
            continue
        out.append(intersite.BandSpectra(b.level, b.f_lo, b.f_hi, b.freqs, b.t_mid[keep], b.record_s,
                                         {k: v[keep] for k, v in b.spectra.items()}))
    return out


def dense_hits(scheme: dict, intervals) -> callable:
    """Return band -> windows overlapping any (start_s, end_s, bands) interval that covers the band."""
    def hits(band):
        lo, hi = window_s(band, scheme, FS)
        out = np.zeros(band.t_mid.size, dtype=bool)
        for a, b, cover in intervals:
            if cover == "all" or cover[0] <= band.period <= cover[1]:
                out |= (lo < b) & (hi > a)
        return out
    return hits


def moved(a, b) -> float:
    """Return the worst relative difference of T over the bands both estimate, whatever their window counts."""
    both = np.isfinite(a.tensor).all(axis=(1, 2)) & np.isfinite(b.tensor).all(axis=(1, 2))
    if a.period.size != b.period.size or not both.any():
        return np.inf
    return float(np.max(np.abs(a.tensor[both] - b.tensor[both]) / np.abs(b.tensor[both])))


def compare(a, b) -> float:
    """Return the worst relative difference of T, its errors and arg(det)/2 (inf on a NaN or count mismatch)."""
    if a.period.size != b.period.size or not np.array_equal(a.n_windows, b.n_windows):
        return np.inf
    worst = 0.0
    for x, y in ((a.tensor, b.tensor), (a.sigma, b.sigma), (a.half_arg_deg, b.half_arg_deg),
                 (a.half_arg_err_deg, b.half_arg_err_deg), (a.abs_det_err, b.abs_det_err)):
        x, y = np.asarray(x), np.asarray(y)
        if not np.array_equal(np.isnan(x), np.isnan(y)):
            return np.inf
        ok = ~np.isnan(x)
        if ok.any():
            worst = max(worst, float(np.max(np.abs(x[ok] - y[ok]) / np.maximum(np.abs(y[ok]), 1e-300))))
    return worst


def burst_arrays():
    """Return (spec with the burst, arrays, scheme): the 20 min record with noise on the base's E over BURST_S."""
    spec, arrays, scheme = short_record()
    rng = np.random.default_rng(5)
    a, b = (int(t * FS) for t in BURST_S)
    for key in E_B:
        x = np.fft.irfft(spec[key], spec["n"])
        x[a:b] += 30.0 * float(np.std(x)) * rng.standard_normal(b - a)
        spec[key] = np.fft.rfft(x)
    return spec, series(spec, KEYS), scheme


def part1() -> None:
    """Criteria 1-4 on arrays."""
    _spec, arrays, scheme = burst_arrays()
    copy = lambda: {k: v.copy() for k, v in arrays.items()}  # noqa: E731
    t0 = int(T_START.tz_localize("UTC").value)
    n = arrays["b_ex"].size
    spans = intersite.mask_spans([normalise(mask(*BURST_S))], t0, n, FS, "B")
    record = []
    masked = intersite.estimate(intersite.band_spectra(copy(), FS, scheme, masked=spans, mask_record=record),
                                E_L, E_B, R, layout=scheme)
    plain_bands = list(intersite.band_spectra(copy(), FS, scheme))
    hits = dense_hits(scheme, [(BURST_S[0], BURST_S[1], "all")])
    by_hand = intersite.estimate(cut(plain_bands, lambda b: ~hits(b)), E_L, E_B, R, layout=scheme)
    worst = compare(masked, by_hand)
    check(worst <= 1e-9, f"1 masked T against T cut by hand: worst relative difference {worst:.2e} (at most 1e-9) "
                         f"over {masked.period.size} bands")
    want = {round(b.period, 9): int(hits(b).sum()) for b in plain_bands}
    got = {round(r["period_s"], 9): r["masked"].get("B", 0) for r in record}
    check(got == want and sum(want.values()) > 0,
          f"1 mask record: {sum(got.values())} band windows masked, by hand {sum(want.values())}; per band equal "
          f"{got == want}")
    plain = intersite.estimate(iter(plain_bands), E_L, E_B, R, layout=scheme)
    shift = moved(plain, by_hand)
    check(shift > 1e-3, f"2 control: the unmasked T differs from the hand-cut T by {shift:.2e} (more than 1e-3)")

    level1 = [b for b in plain_bands if b.level == 1 and hits(b).any()]
    target = level1[len(level1) // 2]
    cover = [target.period * 0.999, target.period * 1.001]
    spans = intersite.mask_spans([normalise(mask(*BURST_S, bands=cover))], t0, n, FS, "B")
    limited = intersite.estimate(intersite.band_spectra(copy(), FS, scheme, masked=spans), E_L, E_B, R,
                                 layout=scheme)
    one = dense_hits(scheme, [(BURST_S[0], BURST_S[1], cover)])
    by_hand = intersite.estimate(cut(plain_bands, lambda b: ~one(b)), E_L, E_B, R, layout=scheme)
    worst = compare(limited, by_hand)
    changed = np.flatnonzero(limited.n_windows != plain.n_windows)
    check(worst <= 1e-9 and changed.size == 1 and np.isclose(limited.period[changed[0]], target.period),
          f"3 a mask of the {target.period:.4g} s band alone: {changed.size} band(s) changed "
          f"({', '.join(f'{p:.4g}' for p in limited.period[changed])} s); against the hand cut {worst:.2e}")

    roles = {"local": intersite.mask_role("local"), "base": intersite.mask_role("base"),
             "reference": intersite.mask_role("reference")}
    check(roles == {"local": "local", "base": "local", "reference": "remote"}, f"4 mask_role: {roles}")
    entries = [mask(0, 10, scope="local"), mask(0, 10, scope="both"), mask(0, 10, scope="remote"),
               mask(0, 10, scope="both", channels=["hx"]), mask(0, 10, scope="both", channels=["ex"])]
    picks = {}
    for role, chans in (("base", ("ex", "ey")), ("reference", ("hx", "hy")), ("reference", ("ex", "ey"))):
        got = intersite.site_masks(entries, role, chans)
        picks[(role, chans)] = (len(got["applied"]), len(got["left_out_scope"]), len(got["left_out_channels"]))
    want = {("base", ("ex", "ey")): (3, 1, 1), ("reference", ("hx", "hy")): (3, 1, 1),
            ("reference", ("ex", "ey")): (3, 1, 1)}
    check(picks == want, f"4 site_masks (applied, left out by scope, by channels): {picks}, want {want}")


def load_script():
    """Import scripts/process_intersite.py as a module."""
    loader = importlib.util.spec_from_file_location("process_intersite", SCRIPT)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def masks_yaml(path: Path) -> None:
    """Write the masks.yaml of ENTRIES."""
    import yaml

    doc = {}
    for site, a, b, scope, channels, _how in ENTRIES:
        doc.setdefault(site, []).append(mask(a, b, scope=scope, channels=channels))
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def part2() -> None:
    """Criteria 5-7 through the script."""
    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root, work = SCRATCH / "survey" / "raw", SCRATCH / "survey" / "work"
    root.mkdir(parents=True)
    spec, _arrays, scheme = burst_arrays()
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    for site in ("L", "B", "R"):
        write_site(work, site, spec, T_START, spec["n"])
    yamls = {}
    for name in ("masked", "plain"):
        yamls[name] = SCRATCH / "survey" / name / "survey.yaml"
        yamls[name].parent.mkdir(parents=True)
        yamls[name].write_text(SURVEY_YAML.format(root=root.as_posix(), work=work.as_posix()), encoding="utf-8")
    masks_yaml(yamls["masked"].parent / "masks.yaml")
    runs = {}
    for name, path in yamls.items():
        out = SCRATCH / "survey" / name / "out"
        res = subprocess.run([sys.executable, str(SCRIPT), str(path), "L", "B", "--kind", "telluric", "--remote",
                              "R", "--out-dir", str(out)], capture_output=True, text=True, cwd=REPO)
        if not check(res.returncode == 0, f"5 {name}: exit {res.returncode}"):
            print(res.stderr[-3000:])
            return
        est, _letter = intersite.read_csv(out / f"{STEM}.csv")
        runs[name] = (est, json.loads((out / f"{STEM}.json").read_text(encoding="utf-8")), res.stdout)

    script = load_script()
    args = script.build_parser().parse_intermixed_args([str(yamls["plain"]), "L", "B", "--kind", "telluric",
                                                        "--remote", "R"])
    res = script.resolve(args, pd.Timestamp.now(tz="UTC").to_pydatetime())
    arrays, responses, _sources, _m, _b = script.read_inputs(res)
    first = (res["t0_ns"] - int(T_START.tz_localize("UTC").value)) / 1e9
    plain_bands = list(intersite.band_spectra(arrays, FS, res["scheme"], responses))
    keys = (tuple("l_" + r for r in ("ex", "ey")), tuple("b_" + r for r in ("ex", "ey")),
            tuple("r_" + r for r in ("hx", "hy")))

    def by_hand(selected):
        hits = dense_hits(res["scheme"], [(a - first, b - first, "all") for _s, a, b, *_r in selected])
        return intersite.estimate(cut(plain_bands, lambda band: ~hits(band)), *keys, layout=res["scheme"])

    est, side, stdout = runs["masked"]
    applied = [e for e in ENTRIES if e[5] == "applied"]
    worst = compare(est, by_hand(applied))
    check(worst <= 1e-9, f"5 script T against the hand cut of the entries the roles take: worst {worst:.2e}")
    union = compare(est, by_hand(ENTRIES))
    none = compare(est, by_hand([]))
    check(union > 1e-9 and none > 1e-9, f"5 controls: every entry applied differs by {union:.2e}, none applied by "
                                        f"{none:.2e} (both more than 1e-9)")

    block = side.get("masks") if isinstance(side.get("masks"), dict) else {}
    sites = block.get("sites") or {}
    counted, wanted, entries_ok = {}, {}, {}
    for site in ("L", "B", "R"):
        mine = [e for e in ENTRIES if e[0] == site]
        hits = dense_hits(res["scheme"], [(a - first, b - first, "all") for _s, a, b, _sc, _c, how in mine
                                          if how == "applied"])
        wanted[site] = int(sum(hits(b).sum() for b in plain_bands))
        counted[site] = (sites.get(site) or {}).get("windows_masked")
        got = sites.get(site) or {}
        entries_ok[site] = (len(got.get("applied") or []), len(got.get("left_out_scope") or []),
                            len(got.get("left_out_channels") or []))
    check(counted == wanted and all(v > 0 for v in wanted.values()),
          f"6 sidecar band windows masked per site {counted}, by hand {wanted}")
    check(entries_ok == {"L": (1, 1, 0), "B": (1, 1, 1), "R": (1, 1, 0)},
          f"6 sidecar entries (applied, left out by scope, by channels): {entries_ok}")
    printed = all(f"masks: {site} " in stdout and f"{wanted[site]} band windows masked" in stdout
                  for site in wanted)
    check(printed, "6 the log prints each site's band windows masked")

    est_plain, side_plain, _out = runs["plain"]
    exact = compare(est_plain, intersite.estimate(iter(plain_bands), *keys, layout=res["scheme"]))
    block = side_plain.get("masks") if isinstance(side_plain.get("masks"), dict) else {}
    zero = all((v or {}).get("windows_masked") == 0 for v in (block.get("sites") or {}).values())
    check(exact == 0.0 and block.get("file") is None and zero,
          f"7 without masks.yaml: T against the unmasked estimate {exact:.1e} (0), file {block.get('file')!r}, "
          f"every count 0 {zero}")


def part3() -> None:
    """Criterion 8 on the compact burst grid."""
    from intersite_bursts_unit import BURST_N, EVERY_S, RATE, START_NS, write_bursts

    rng = np.random.default_rng(77)
    mix_t = np.array([[0.8, 0.3], [-0.2, 1.1]])
    mix_h = np.array([[0.6, -0.5], [0.4, 0.9]])
    local, base, ref = [], [], []
    for k in range(8):
        b = rng.standard_normal((2, BURST_N))
        signal = mix_t @ b
        local.append(dict(zip(("ex", "ey"), signal + 0.05 * rng.standard_normal(signal.shape))))
        noisy = b + (30.0 * rng.standard_normal(b.shape) if k == 3 else 0.0)
        base.append(dict(zip(("ex", "ey"), noisy)))
        ref.append(dict(zip(("hx", "hy"), mix_h @ b + 0.5 * rng.standard_normal(b.shape))))
    folder = SCRATCH / "bursts"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    paths = {"L": write_bursts(folder / "L.h5", "L", local), "B": write_bursts(folder / "B.h5", "B", base),
             "R": write_bursts(folder / "R.h5", "R", ref)}
    slots = sorted(intersite.burst_slots(paths["L"], "L", ("ex", "ey")))
    arrays = {}
    for prefix, site, roles in (("l_", "L", ("ex", "ey")), ("b_", "B", ("ex", "ey")), ("r_", "R", ("hx", "hy"))):
        got, _resp, _chains = intersite.read_bursts(paths[site], site, roles, slots, BURST_N, RATE)
        arrays.update({prefix + r: v for r, v in got.items()})
    scheme = build_band_scheme(RATE, min_period=1 / 6000, max_period=0.05)
    t0 = pd.Timestamp(START_NS, unit="ns", tz="UTC").tz_convert(None)
    windows = [(3 * EVERY_S - 1.0, 3 * EVERY_S + 2.5), (5 * EVERY_S + 0.5, 5 * EVERY_S + 1.0)]
    entries = [normalise(mask(a, b, t0=t0)) for a, b in windows]
    n = arrays["b_ex"].size
    spans = intersite.mask_spans(entries, START_NS, n, RATE, "B", slots_ns=slots, per_burst=BURST_N)
    dense = intersite.mask_spans(entries, START_NS, n, RATE, "B")
    copy = lambda: {k: v.copy() for k, v in arrays.items()}  # noqa: E731
    record = []
    masked = intersite.estimate(intersite.band_spectra(copy(), RATE, scheme, masked=spans, mask_record=record),
                                E_L, E_B, R, layout=scheme)
    plain_bands = list(intersite.band_spectra(copy(), RATE, scheme))
    step = BURST_N + intersite.BURST_GAP
    factors = list(scheme["decimation_factors"])
    factor = int(factors[1]) if len(factors) > 1 else 4

    def hits(band):
        scale = factor ** band.level
        win = int(scheme["num_samples_window"][band.level])
        first = np.rint(band.t_mid * RATE - win * scale / 2.0).astype(np.int64)
        burst = first // step
        lo = (np.asarray(slots)[burst] - START_NS) / 1e9 + (first - burst * step) / RATE
        hi = lo + (win + 1) * scale / RATE
        out = np.zeros(band.t_mid.size, dtype=bool)
        for a, b in windows:
            out |= (lo < b) & (hi > a)
        return out

    by_hand = intersite.estimate(cut(plain_bands, lambda b: ~hits(b)), E_L, E_B, R, layout=scheme)
    worst = compare(masked, by_hand)
    want = {round(b.period, 12): int(hits(b).sum()) for b in plain_bands}
    got = {round(r["period_s"], 12): r["masked"].get("B", 0) for r in record}
    level0 = [b for b in plain_bands if b.level == 0][0]
    scale0 = int(scheme["num_samples_window"][0])
    in_sixth = (np.rint(level0.t_mid * RATE - scale0 / 2.0).astype(np.int64) // step) == 5
    part = int((hits(level0) & in_sixth).sum())
    check(worst <= 1e-9 and got == want and 0 < part < int(in_sixth.sum()),
          f"8 burst grid: masked T against the hand cut {worst:.2e}; record {sum(got.values())} band windows, by "
          f"hand {sum(want.values())}; the 0.5 s mask leaves out {part} of the sixth burst's "
          f"{int(in_sixth.sum())} level 0 windows")
    check([s[:2] for s in dense] != [s[:2] for s in spans],
          f"8 control: dense placement gives spans {[s[:2] for s in dense]}, the burst grid "
          f"{[s[:2] for s in spans]}")


def main() -> int:
    for part in (part1, part2, part3):
        try:
            part()
        except Exception as exc:  # a missing function or keyword of the code under test is a failure
            check(False, f"{part.__name__} raised {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
