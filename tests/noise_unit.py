"""Unit test for `mtproc.noise` -- the declared filters, on plain arrays and on a run.

    python tests/noise_unit.py

A synthetic 20 min at 1000 Hz: every channel carries a 50 Hz line (amplitude
2), a 0.01 Hz drift (amplitude 100) and white noise (1 rms); ey also carries
a 200 Hz tone (amplitude 3) and ex a 12 s square wave (amplitude 5). Each
measure below is taken here with numpy alone -- a lock-in projection, block
means, a projection on the square wave -- or with `mtproc.timefreq.line_excess` on a
plain `scipy.signal.welch`, never with the filter under test. **This test
fails if**

- `notch` (50 Hz, 9 harmonics, the defaults) does not drop the 50 Hz line's
  `line_excess` on hx by more than 20 dB;
- `hp` at 0.05 Hz does not remove the drift: the std of hx's 10 s block
  means (a low-pass taken here by averaging) must fall below 1 % of the raw
  block means' std, while the 50 Hz line (far above the cutoff) keeps a
  `line_excess` within 1 dB of the raw one;
- `lp` at 100 Hz does not attenuate ey's 200 Hz tone by more than 30 dB (its
  amplitude by a lock-in at 200 Hz, before and after);
- `cp` (12 s, 10 min windows) does not remove ex's square wave: its
  amplitude, by projection on the known square wave, must fall below 1 % of
  the raw on ex without the drift, and below 2 % on the drifting ex with
  the cascade the module docstring advises (hp 0.05 Hz, then cp); cp alone
  on the drifting ex is printed, not asserted (the drift leaks into the
  median cycle: that is why the advice says high-pass first);
- `channels` scoping leaves any channel it does not name bit-identical to
  its input (notch, hp, lp and cp each scoped to one channel);
- any input array changes (SHA-1 of its bytes before and after), or an
  untouched channel in the output is writable (it would alias the input);
- the ingest path is not neutral: `apply_filters` on a run-like object (an
  xarray Dataset in `run.dataset`) and `apply_filters_arrays` on the same
  arrays do not give bit-identical channels and identical provenance lines
  for notch then cp, or either differs from calling `mains_notch` then
  `cp_stack_subtract` by hand in that order;
- `workers=4` is not bit-identical to `workers=1`;
- `replace` does not take the donor's array when `donors` holds it, or,
  without it, does not leave the channel untouched and say "replace
  hx<-A06: donor not loaded, skipped in preview"; or `apply_filters` (the
  run path) accepts a replace entry;
- an hp cutoff at or above Nyquist is not refused;
- `burst` (the defaults, on a second synthetic: 3 min at 1000 Hz of white
  noise, 1 rms, on every channel, plus three 0.5 s 40 Hz ringings decaying
  as exp(-t / 0.5 s) at 30 x the noise on ex and ey and 5 x on hy, at 30,
  75 and 140 s) does not say "burst: 3 spans", or the samples it changed
  (on ex, found here by comparing output with input) do not form exactly
  three runs each starting and ending within 0.15 s of a true burst's start
  and end, or any sample of any channel more than 0.3 s outside a true
  burst differs from its input by a single bit, or a changed run's interior
  (the tapers aside) on ex, ey, hx or hy is not the local level -- here
  |y| < 0.2 with the noise gone (std < 0.1) -- or hy's 5 x ringing
  survives; or, with ex carried at 5000 + 37 x (counts, as ingest sees
  them), the spans move or ex's fill is not at 5000 (to 0.2 x 37): a fill
  at zero would dig a 5000-count hole; or the plain noise, or the noise
  with one 500 x single-sample spike on ex (a sferic), yields a span; or
  `channels: [ex]` changes hy (or ey, hx) by a bit;
- `flip: {channels: [ey]}` does not make ey the exact negative of its
  input with the other channels bit-identical and the line "flip: sign
  reversed on ['ey']", or a flip without `channels`, or of a channel the
  run lacks, is not refused;
- `mains` (the defaults, on a third synthetic: 120 s at 1000 Hz of pink-ish
  noise, std 1, different on every channel, plus a mains of 50, 150 and 250
  Hz, amplitude 100 each, that steps to 300 at 40.0031 s and back at
  80.0117 s -- off every block and sub-block boundary -- while its
  frequency wanders linearly from 49.95 to 50.05 Hz), on any channel:
  (a) the output's Welch PSD (2^14 segments) at 50, 150 or 250 Hz (its
  highest bin within 0.5 Hz) stands more than 3 dB above the same synthetic
  without the mains (its mean over those bins); (b) within 0.5 s of either
  step, |output - the synthetic without the mains| reaches 3 x that one's
  std (ringing); (c) the mean PSD over 20-40 Hz or 60-140 Hz differs from
  the mains-free one's by more than 0.5 dB; (d) the provenance line does
  not report 2 amplitude steps on each channel and a tracked offset mean
  within 0.02 Hz of the truth's (0 Hz: 50.00 on average); (e) with
  `channels: [ex]` ex is untouched or ey, hx or hy differ from their input
  by a bit (or come out writable), or 4 workers differ from 1, or an input
  array changes; (f) on the noise alone (no mains at all, where the 0.1 s
  amplitude is noise and changes by 30 % about twice a second) it reports a
  step; (g) on ex carried as counts, 5000 + 37 x plus a drift of 50 counts
  a second (as ingest sees an electrode), the output is not the same line
  plus 37 x the output on x, to 1e-6 of the mains amplitude (an offset or
  a drift must not leak into the harmonics: before the fits carried a
  straight line, a 5000 offset left 216 behind).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import xarray as xr
from scipy.signal import welch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mtproc.noise import (  # noqa: E402
    apply_filters, apply_filters_arrays, cp_stack_subtract, mains_notch, mains_subtract,
)
from mtproc.timefreq import line_excess  # noqa: E402

FS = 1000.0
N = int(20 * 60 * FS)
COMPS = ("hx", "hy", "ex", "ey")
NOTCH = {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2}}
CP = {"cp": {"period_s": 12.0, "window_minutes": 10.0}}


def synthetic(seed: int = 7) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    t = np.arange(N) / FS
    base = 2.0 * np.sin(2 * np.pi * 50.0 * t) + drift(t)
    out = {c: base + rng.standard_normal(N) for c in COMPS}
    out["ey"] = out["ey"] + 3.0 * np.sin(2 * np.pi * 200.0 * t + 0.7)
    out["ex"] = out["ex"] + 5.0 * square(t)
    return {c: a.astype("float32") for c, a in out.items()}


def sha(a: np.ndarray) -> str:
    return hashlib.sha1(np.ascontiguousarray(a).tobytes()).hexdigest()


def excess_50(x: np.ndarray) -> float:
    f, p = welch(np.asarray(x, dtype="float64"), fs=FS, nperseg=2**14)
    return line_excess(f, p, 50.0)


def lock_in(x: np.ndarray, f: float) -> float:
    """Amplitude of the f Hz component: projection on cos and sin over whole cycles."""
    t = np.arange(len(x)) / FS
    x = np.asarray(x, dtype="float64")
    return float(2.0 * np.hypot(np.mean(x * np.cos(2 * np.pi * f * t)), np.mean(x * np.sin(2 * np.pi * f * t))))


def block_means(x: np.ndarray, seconds: float = 10.0) -> np.ndarray:
    m = int(seconds * FS)
    return np.asarray(x[: len(x) // m * m], dtype="float64").reshape(-1, m).mean(axis=1)


def square(t: np.ndarray) -> np.ndarray:
    return np.sign(np.sin(2 * np.pi * t / 12.0 + 0.1))


def drift(t: np.ndarray) -> np.ndarray:
    return 100.0 * np.sin(2 * np.pi * 0.01 * t + 0.3)


def square_amplitude(x: np.ndarray) -> float:
    """Least-squares amplitude of the known 12 s square wave in x (white noise projects to ~1e-3)."""
    sq = square(np.arange(len(x)) / FS)
    return float(np.dot(np.asarray(x, dtype="float64"), sq) / np.dot(sq, sq))


BURSTS = (30.0, 75.0, 140.0)  # starts (s) of the synthetic's three ringings, each 0.5 s long
BURST_N = int(3 * 60 * FS)


def burst_window(bursts=BURSTS, seed: int = 3) -> dict[str, np.ndarray]:
    """White noise (1 rms) on every channel; 40 Hz ringings decaying as exp(-t / 0.5 s), 30 x on ex, ey, 5 x on hy."""
    rng = np.random.default_rng(seed)
    t = np.arange(BURST_N) / FS
    ring = np.zeros(BURST_N)
    for tb in bursts:
        k = (t >= tb) & (t < tb + 0.5)
        ring[k] = np.exp(-(t[k] - tb) / 0.5) * np.sin(2 * np.pi * 40.0 * (t[k] - tb))
    out = {c: rng.standard_normal(BURST_N) for c in COMPS}
    for comp, gain in (("ex", 30.0), ("ey", 30.0), ("hy", 5.0)):
        out[comp] = out[comp] + gain * ring
    return {c: a.astype("float32") for c, a in out.items()}


def changed_runs(new: np.ndarray, old: np.ndarray) -> list[tuple[int, int]]:
    """[(start, stop)] runs of samples where new differs from old (gaps of up to 2 equal samples bridged)."""
    idx = np.flatnonzero(np.asarray(new, dtype="float64") != np.asarray(old, dtype="float64"))
    if not len(idx):
        return []
    cut = np.flatnonzero(np.diff(idx) > 3)
    return list(zip(idx[np.r_[0, cut + 1]], idx[np.r_[cut, len(idx) - 1]] + 1))


def check_burst() -> None:
    raw = burst_window()
    before = {c: sha(a) for c, a in raw.items()}
    out, lines = apply_filters_arrays(raw, FS, [{"burst": {}}], workers=4)
    assert lines[0].startswith("burst: 3 spans"), lines
    runs = changed_runs(out["ex"], raw["ex"])
    assert len(runs) == 3, f"burst changed {len(runs)} runs of ex, not 3: {[(a / FS, b / FS) for a, b in runs]}"
    t = np.arange(BURST_N) / FS
    near = np.zeros(BURST_N, dtype=bool)
    for (a, b), tb in zip(runs, BURSTS):
        assert abs(a / FS - tb) <= 0.15 and abs(b / FS - (tb + 0.5)) <= 0.15, \
            f"span {a / FS:.3f}-{b / FS:.3f} s is not within 0.15 s of the burst {tb}-{tb + 0.5} s"
        near |= (t >= tb - 0.3) & (t < tb + 0.8)
    taper = int(0.05 * FS)
    for c in COMPS:
        assert np.array_equal(np.asarray(out[c])[~near], raw[c][~near].astype("float64")), \
            f"burst changed {c} more than 0.3 s from every true burst"
        for a, b in runs:
            inner = np.asarray(out[c][a + taper:b - taper])
            assert np.max(np.abs(inner)) < 0.2 and np.std(inner) < 0.1, \
                f"{c} {a / FS:.2f} s: the span is not the local level (max |y| {np.max(np.abs(inner)):.3f}, " \
                f"std {np.std(inner):.3f})"
    hy_ring = max(np.max(np.abs(raw["hy"][a:b])) for a, b in runs)
    print(f"burst: {lines[0]!r}; ex changed in {[(float(a / FS), float(b / FS)) for a, b in runs]} s "
          f"(true {[(tb, tb + 0.5) for tb in BURSTS]}); every channel bit-identical more than 0.3 s away, "
          f"at the local level (|y| < 0.2) inside (hy's ringing, peak {hy_ring:.1f}, gone)")

    counts = dict(raw, ex=(5000.0 + 37.0 * raw["ex"].astype("float64")).astype("float32"))
    out2, lines2 = apply_filters_arrays(counts, FS, [{"burst": {}}])
    runs2 = changed_runs(out2["hx"], raw["hx"])
    assert lines2[0].startswith("burst: 3 spans") and \
        all(abs(a - a2) <= 2 and abs(b - b2) <= 2 for (a, b), (a2, b2) in zip(runs, runs2)), (lines2, runs2)
    fill = np.concatenate([np.asarray(out2["ex"][a + taper:b - taper]) for a, b in runs])
    assert np.max(np.abs(fill - 5000.0)) < 0.2 * 37.0, f"ex in counts filled at {fill.min():.1f}..{fill.max():.1f}, not 5000"
    print(f"burst on counts (5000 + 37 x ex): the same spans, ex filled at {fill.mean():.1f} (the level, not zero)")

    quiet = burst_window(bursts=())
    out, lines = apply_filters_arrays(quiet, FS, [{"burst": {}}])
    assert lines[0].startswith("burst: 0 spans"), lines
    assert all(np.array_equal(out[c], quiet[c]) and not out[c].flags.writeable for c in COMPS)
    spike = dict(quiet, ex=quiet["ex"].copy())
    spike["ex"][int(100.0 * FS)] = 500.0
    out, lines_spike = apply_filters_arrays(spike, FS, [{"burst": {}}])
    assert lines_spike[0].startswith("burst: 0 spans"), lines_spike
    print(f"burst: plain noise {lines[0][:14]!r}, outputs the inputs' read-only views; a 500 x single-sample "
          f"spike (a sferic) {lines_spike[0][:14]!r}")

    out, lines = apply_filters_arrays(raw, FS, [{"burst": {"channels": ["ex"]}}])
    assert lines[0].startswith("burst: 3 spans") and "on ['ex']" in lines[0], lines
    assert changed_runs(out["ex"], raw["ex"]) == runs
    for c in ("ey", "hx", "hy"):
        assert np.array_equal(out[c], raw[c]) and not out[c].flags.writeable, f"burst on [ex] touched {c}"
    assert {c: sha(a) for c, a in raw.items()} == before, "burst changed an input array"
    print("burst: channels [ex] left ey, hx, hy bit-identical; the inputs' SHA-1 unchanged")


def check_flip(raw: dict[str, np.ndarray]) -> None:
    out, lines = apply_filters_arrays(raw, FS, [{"flip": {"channels": ["ey"]}}])
    assert lines == ["flip: sign reversed on ['ey']"], lines
    assert np.array_equal(out["ey"], -raw["ey"].astype("float64")), "flipped ey is not the exact negative"
    for c in ("ex", "hx", "hy"):
        assert np.array_equal(out[c], raw[c]) and not out[c].flags.writeable, f"flip on [ey] touched {c}"
    for spec in ({"flip": {}}, {"flip": {"channels": ["ez"]}}):
        try:
            apply_filters_arrays(raw, FS, [spec])
        except ValueError:
            continue
        raise AssertionError(f"{spec} was accepted")
    print(f"flip: ey exactly negated, ex hx hy bit-identical; {lines[0]!r}; no channels, or ez, refused")


MAINS_STEPS = (40.0031, 80.0117)  # the mains synthetic's amplitude steps (s): 100 -> 300 -> 100
MAINS_N = int(120 * FS)


def pinkish(seed: int) -> np.ndarray:
    """MT-like noise: white shaped to an amplitude spectrum 1/sqrt(f) (flat below 0.5 Hz), std 1."""
    f = np.fft.rfftfreq(MAINS_N, 1.0 / FS)
    x = np.fft.irfft(np.fft.rfft(np.random.default_rng(seed).standard_normal(MAINS_N)) / np.sqrt(np.maximum(f, 0.5)),
                     MAINS_N)
    return x / x.std()


def mains_wave() -> np.ndarray:
    """50, 150 and 250 Hz of amplitude 100 (300 between the steps), the frequency 49.95 -> 50.05 Hz in 120 s."""
    t = np.arange(MAINS_N) / FS
    theta = 2 * np.pi * (49.95 * t + 0.1 * t ** 2 / (2 * 120.0))
    amp = np.where((t >= MAINS_STEPS[0]) & (t < MAINS_STEPS[1]), 300.0, 100.0)
    return amp * (np.cos(theta + 0.3) + np.cos(3 * theta + 1.1) + np.cos(5 * theta + 2.0))


def check_mains() -> None:
    clean = {c: pinkish(20 + i) for i, c in enumerate(COMPS)}
    raw = {c: (x + mains_wave()).astype("float32") for c, x in clean.items()}
    before = {c: sha(a) for c, a in raw.items()}
    out, lines = apply_filters_arrays(raw, FS, [{"mains": {}}], workers=4)
    t = np.arange(MAINS_N) / FS
    for c in COMPS:
        y, x = np.asarray(out[c]), clean[c]
        f, p_out = welch(y, fs=FS, nperseg=2**14)
        _, p_clean = welch(x, fs=FS, nperseg=2**14)
        _, p_raw = welch(raw[c].astype("float64"), fs=FS, nperseg=2**14)
        excess, raw_excess = [], []
        for k in (1, 3, 5):
            near = np.abs(f - 50.0 * k) <= 0.5
            excess.append(10 * np.log10(p_out[near].max() / p_clean[near].mean()))
            raw_excess.append(10 * np.log10(p_raw[near].max() / p_clean[near].mean()))
        assert max(excess) <= 3.0, f"(a) {c}: 50/150/250 Hz stand {np.round(excess, 2)} dB above the mains-free PSD"
        peaks = [float(np.max(np.abs(y - x)[np.abs(t - s) <= 0.5])) for s in MAINS_STEPS]
        assert max(peaks) < 3.0 * x.std(), f"(b) {c}: |output - mains-free| peaks {np.round(peaks, 2)} near the steps"
        bands = [10 * np.log10(p_out[(f >= lo) & (f <= hi)].mean() / p_clean[(f >= lo) & (f <= hi)].mean())
                 for lo, hi in ((20.0, 40.0), (60.0, 140.0))]
        assert max(abs(b) for b in bands) <= 0.5, f"(c) {c}: 20-40 and 60-140 Hz moved {np.round(bands, 3)} dB"
        if c == "ex":
            print(f"mains: ex 50/150/250 Hz {np.round(excess, 2)} dB over the mains-free PSD (raw "
                  f"{np.round(raw_excess, 1)}); peak |output - mains-free| within 0.5 s of the steps "
                  f"{np.round(peaks, 3)} (< 3 x {x.std():.2f}); 20-40, 60-140 Hz {np.round(bands, 3)} dB")
    assert lines[0].startswith("mains: ") and \
        "8 amplitude steps followed in all (hx 2, hy 2, ex 2, ey 2)" in lines[0], f"(d) {lines[0]!r}"
    offset = float(lines[0].split("tracked offset mean ")[1].split(" Hz")[0])
    assert abs(offset - 0.0) <= 0.02, f"(d) tracked offset mean {offset} Hz, the truth's 0"
    steps = mains_subtract(raw["ex"], FS)[1]["steps"]
    print(f"mains: {lines[0]!r}; ex's steps at samples {steps.tolist()} (the first at the new level: "
          f"{[int(np.ceil(s * FS)) for s in MAINS_STEPS]})")

    one, lines_one = apply_filters_arrays(raw, FS, [{"mains": {}}], workers=1)
    assert lines_one == lines and all(np.array_equal(one[c], out[c]) for c in COMPS), "(e) workers 4 != 1"
    scoped, lines_ex = apply_filters_arrays(raw, FS, [{"mains": {"channels": ["ex"]}}])
    assert not np.array_equal(scoped["ex"], raw["ex"]) and "on ['ex']" in lines_ex[0], f"(e) {lines_ex}"
    for c in ("ey", "hx", "hy"):
        assert np.array_equal(scoped[c], raw[c]) and not scoped[c].flags.writeable, f"(e) mains on [ex] touched {c}"
    assert {c: sha(a) for c, a in raw.items()} == before, "(e) mains changed an input array"
    print("mains: channels [ex] left ey, hx, hy bit-identical (read-only views); 4 workers == 1; inputs unchanged")

    quiet, lines_quiet = apply_filters_arrays({c: x.astype("float32") for c, x in clean.items()}, FS, [{"mains": {}}])
    assert "0 amplitude steps followed in all" in lines_quiet[0], f"(f) on noise alone: {lines_quiet[0]!r}"
    print(f"mains: noise alone {lines_quiet[0].split(', ')[2][:40]!r}")

    x64 = clean["ex"] + mains_wave()
    line = 5000.0 + 50.0 * np.arange(MAINS_N) / FS
    plain, _ = mains_subtract(x64, FS)
    counts, info_counts = mains_subtract(line + 37.0 * x64, FS)
    worst = float(np.max(np.abs((counts - line) / 37.0 - plain)))
    assert worst < 1e-6 * 300.0, f"(g) on counts the output moved by {worst:.3g} (in x's units)"
    print(f"mains: on counts (5000 + 50 t + 37 x) the output is the line + 37 x the output on x to {worst:.1e}; "
          f"steps {info_counts['steps'].tolist()}")


def main() -> int:
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    raw = synthetic()
    before = {c: sha(a) for c, a in raw.items()}

    # --- notch
    out, lines = apply_filters_arrays(raw, FS, [NOTCH])
    e0, e1 = excess_50(raw["hx"]), excess_50(out["hx"])
    assert e0 - e1 > 20.0, f"notch: 50 Hz excess {e0:.1f} -> {e1:.1f} dB, a drop of only {e0 - e1:.1f} dB"
    print(f"notch: hx 50 Hz excess {e0:.1f} -> {e1:.1f} dB (drop {e0 - e1:.1f} dB > 20); {lines[0]!r}")

    # --- hp
    out, lines = apply_filters_arrays(raw, FS, [{"hp": {"cutoff_hz": 0.05}}])
    s0, s1 = float(np.std(block_means(raw["hx"]))), float(np.std(block_means(out["hx"])))
    assert s1 < 0.01 * s0, f"hp: 10 s block-mean std {s0:.3g} -> {s1:.3g}, not under 1 %"
    e_hp = excess_50(out["hx"])
    assert abs(e_hp - e0) < 1.0, f"hp at 0.05 Hz moved the 50 Hz line: {e0:.2f} -> {e_hp:.2f} dB"
    print(f"hp 0.05 Hz: hx 10 s block-mean std {s0:.3g} -> {s1:.3g} ({100 * s1 / s0:.3f} %); "
          f"50 Hz excess {e0:.2f} -> {e_hp:.2f} dB (kept); {lines[0]!r}")

    # --- lp
    out, lines = apply_filters_arrays(raw, FS, [{"lp": {"cutoff_hz": 100.0}}])
    a0, a1 = lock_in(raw["ey"], 200.0), lock_in(out["ey"], 200.0)
    drop = 20 * np.log10(a0 / a1)
    assert drop > 30.0, f"lp: 200 Hz tone {a0:.3g} -> {a1:.3g}, only {drop:.1f} dB"
    print(f"lp 100 Hz: ey 200 Hz tone amplitude {a0:.3f} -> {a1:.2e} ({drop:.1f} dB > 30); {lines[0]!r}")

    # --- cp
    steady = {"ex": (raw["ex"] - drift(np.arange(N) / FS)).astype("float32")}
    a0 = square_amplitude(steady["ex"])
    out, lines = apply_filters_arrays(steady, FS, [CP])
    a1 = square_amplitude(out["ex"])
    assert abs(a1) < 0.01 * abs(a0), f"cp: square wave {a0:.3g} -> {a1:.3g}, not under 1 %"
    out, _ = apply_filters_arrays(raw, FS, [{"hp": {"cutoff_hz": 0.05}}, CP])
    a2 = square_amplitude(out["ex"])
    assert abs(a2) < 0.02 * abs(a0), f"hp then cp: square wave {a0:.3g} -> {a2:.3g}, not under 2 %"
    out, _ = apply_filters_arrays(raw, FS, [CP])
    a3 = square_amplitude(out["ex"])
    print(f"cp 12 s: ex square wave {a0:.3f} -> {a1:.2e} without the drift ({100 * abs(a1 / a0):.3f} %), "
          f"-> {a2:.3f} with it after hp then cp ({100 * abs(a2 / a0):.2f} %); {lines[0]!r}")
    print(f"  (information: cp alone on the drifting ex leaves {a3:.3f}, {100 * abs(a3 / a0):.1f} % -- "
          f"high-pass first)")

    # --- channels scoping, and the untouched outputs are read-only views
    for spec in ({"notch": {"channels": ["ex"]}}, {"hp": {"cutoff_hz": 0.05, "channels": ["ex"]}},
                 {"lp": {"cutoff_hz": 100.0, "channels": ["ex"]}},
                 {"cp": {"period_s": 12.0, "channels": ["ex"]}}):
        out, lines = apply_filters_arrays(raw, FS, [spec])
        kind = next(iter(spec))
        assert not np.array_equal(out["ex"], raw["ex"]), f"{kind} scoped to ex did not touch ex"
        for c in ("hx", "hy", "ey"):
            assert np.array_equal(out[c], raw[c]) and out[c].dtype == raw[c].dtype, f"{kind} touched {c}"
            assert not out[c].flags.writeable, f"{kind}: untouched {c} is writable"
        assert "['ex']" in lines[0], lines[0]
    print("channels: notch, hp, lp and cp scoped to ex left hx, hy, ey bit-identical (read-only views)")

    # --- inputs never modified
    after = {c: sha(a) for c, a in raw.items()}
    assert after == before, "an input array changed"
    print("inputs: SHA-1 of every channel unchanged after every call")

    # --- neutrality: the run path against the arrays path, and both against the primitives
    arrays64 = {c: a.astype("float64") for c, a in raw.items()}
    run = SimpleNamespace(dataset=xr.Dataset({c: ("time", a.copy()) for c, a in arrays64.items()}))
    run_lines = apply_filters(run, [NOTCH, CP], FS, tag="T")
    arr_out, arr_lines = apply_filters_arrays(arrays64, FS, [NOTCH, CP], tag="T")
    assert run_lines == arr_lines, (run_lines, arr_lines)
    for c in COMPS:
        by_hand = cp_stack_subtract(mains_notch(arrays64[c], FS, 50.0, 9, 30.0, 2, []), FS, 12.0, 10.0)
        assert np.array_equal(run.dataset[c].data, arr_out[c]), f"{c}: run path != arrays path"
        assert np.array_equal(arr_out[c], by_hand), f"{c}: arrays path != mains_notch then cp_stack_subtract"
    print(f"neutral: apply_filters(run) == apply_filters_arrays == the primitives by hand, bit for bit; "
          f"lines {run_lines}")

    # --- threads
    one, _ = apply_filters_arrays(raw, FS, [NOTCH, {"hp": {"cutoff_hz": 0.05}}, CP], workers=1)
    four, _ = apply_filters_arrays(raw, FS, [NOTCH, {"hp": {"cutoff_hz": 0.05}}, CP], workers=4)
    assert all(np.array_equal(one[c], four[c]) for c in COMPS), "workers=4 differs from workers=1"
    print("workers: 4 threads bit-identical to 1")

    # --- replace
    donor = {"A06": {"hx": np.full(N, 7.0, dtype="float32")}}
    out, with_donor = apply_filters_arrays(raw, FS, [NOTCH, {"replace": {"hx": "A06"}}], donors=donor)
    assert with_donor[0] == "replace magnetics: hx <- A06", with_donor
    assert np.allclose(out["hx"], 7.0, atol=1e-6), "the donor's hx did not reach the notch"
    out, lines = apply_filters_arrays(raw, FS, [{"replace": {"hx": "A06"}}])
    assert lines == ["replace hx<-A06: donor not loaded, skipped in preview"], lines
    assert np.array_equal(out["hx"], raw["hx"])
    try:
        apply_filters(run, [{"replace": {"hx": "A06"}}], FS)
    except ValueError:
        pass
    else:
        raise AssertionError("apply_filters (the run path) accepted a replace entry")
    print(f"replace: {with_donor[0]!r} (applied first, then the notch) with the donor, "
          f"{lines[0]!r} without it; the run path refuses replace")

    try:
        apply_filters_arrays(raw, FS, [{"hp": {"cutoff_hz": 500.0}}])
    except ValueError as exc:
        print(f"hp at Nyquist refused: {exc}")
    else:
        raise AssertionError("an hp cutoff at Nyquist was accepted")

    check_burst()
    check_flip(raw)
    after = {c: sha(a) for c, a in raw.items()}
    assert after == before, "an input array changed (flip)"
    check_mains()

    print("\nPASS  noise_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
