# -*- coding: utf-8 -*-
"""
Unit test for mt_workbench.stackcheck and the Stacks tab's MemberCheck (run headless)

The library half runs on synthetic arrays at 100 Hz over one hour, six
members: M1, M2, M3 and M6 a common red-noise field (white noise through a
one-pole low-pass at 0.95) plus independent noise of the same spectral
shape at 0.1 of its rms, so the ratio holds in every band; M4 the negative
of such a member (a reversed coil); M5 such noise alone (a dead coil). Both
channels, hx and hy, have their own field. The widget half writes six real
MTH5 archives at 1000 Hz over 1200 s (`virtual_unit.write_archive`) into a
scratch survey, W4 reversed, and drives `MemberCheck` offscreen through a
real `State`.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/stack_check_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (stackcheck) M4 is not the only member flagged reversed or M5 not the only
   one flagged dead, on either channel; a good member's 0.1-10 s gamma2 (the
   median over the usable chunks) is under 0.9; or M4's polarity is above
   -0.5. Independently of the library: the check's 0.1-10 s gamma2 of any
   member differs by more than 0.05 from scipy.signal.coherence of that
   member with the mean of the other five (4096-sample Hann segments, the
   mean over 0.1-10 Hz harmonics), or the sign of a live member's polarity
   differs from the sign of its correlation with that mean in time;
2. `check_span` with t0 and an end 5000 s later at 1000 Hz does not end
   3600 s after t0; with a 24 h segment and a 1000 Hz recipe it does not end
   3600 s after t0; with a 600 s segment it does not end at the segment's
   end; or a 1 Hz recipe on the 24 h segment does not keep the whole 24 h;
   or `check_plan` at 1000 Hz and at 1 Hz differs from the literal bands,
   chunk and polarity periods of the spec (13.2); or, given a 24 h span at
   1 Hz, its chunk is not 28800 s (a third of the span: the ladder planner
   wants three windows), and the six members of (1) at 1 Hz over 24 h give
   no coherence, fewer than three chunks, a good member's 10-1000 s gamma2
   under 0.9, or flags other than M4 reversed and M5 dead;
3. with M2 holding a 120 s gap (zero in the gap, as `load_segment` gives it,
   and the gap listed) any value of the result is not finite (coherence,
   polarity, preview); the chunk touching the gap is counted usable, or any
   other chunk not; or a window `intersite.band_spectra` yields while the
   check runs (the polarity and preview windows, counted by wrapping it)
   overlaps the gap. Or, as controls (so both observables can fail), with
   the gap not listed that chunk is not counted usable or no window
   overlapping the gap is yielded; or M2's gamma2 in the gap chunk on the
   zeroed arrays is within 0.05 of the same chunk on the arrays without the
   gap (so leaving the chunk out would not matter);
4. the band-mean preview of the four good members has a stack power outside
   0.8-1.25 of their median power, or that of six independent unit-noise
   members is outside 0.7-1.3 times 1/6 of theirs, or the band-median
   preview of the same six is outside 1.1-1.5 times 1/6 (1.29/6 for the
   marginal median of six independent unit complex Gaussians, Monte Carlo of
   the spec), so a median preview that fell back to the mean fails. Each
   ratio is the median over the preview bands inside the check's full band,
   0.1-10 s: a single band's ratio at 5-10 s has few windows and scatters by
   +-30 % [measured while writing this test];
5. the coherence-weighted time preview's weights do not sum to 1 within 1e-9
   in each chunk on each channel, or it gives no weights; or one member, or
   none, raises instead of returning a result whose note says there is
   nothing to compare;
6. (MemberCheck) `state.archive_lock` is busy after the result; the lock is
   taken and released (cycles of the check as holder) fewer times than the
   members read; the first check reads other than each of its five members
   once (`segment.load_segment` wrapped); adding a sixth member reads other
   than that one site; the result has a note (coherence not computed on
   the 1200 s span), a W1 full-band gamma2 under 0.9, or does not flag W4,
   and W4 only, reversed, or the second check returns no result;
   `clear()` leaves `kept_sites()` not empty; `wait()` on a check in flight
   takes over 30 s or leaves the lock busy; or a Qt slot raised;
7. (MemberCheck's display) shown the result of (1)'s six members taken as
   ex and ey (an electric recipe), M5's ex bar (flagged dead) is filled
   within 40 levels of `theme.E_COLOUR`, has no BAD_COLOUR outline, or has
   no "dead" text over it; or an unflagged ex bar is not filled with
   E_COLOUR, or an unflagged hx bar of an H result not with B_COLOUR; or
   the two preview panels do not sit one over the other, By-Ex (Zxy) on
   top.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import coherence as welch_coherence
from scipy.signal import lfilter

if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

from mt_workbench import intersite, stackcheck  # noqa: E402
from mt_workbench.bands import build_band_scheme  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

FS = 100.0
N = int(3600 * FS)
ROLES = ("hx", "hy")
GOOD = ("M1", "M2", "M3", "M6")
GAP = (int(1300 * FS), int(1420 * FS))  # 120 s inside the third 600 s chunk
FULL = (0.1, 10.0)
SCRATCH = scratch_dir("stack_check_unit")
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def red(rng, n: int = N) -> np.ndarray:
    """Return red noise: white noise through a one-pole low-pass at 0.95."""
    return lfilter([1.0], [1.0, -0.95], rng.standard_normal(n))


def six_members(seed: int = 5) -> dict:
    """Return the six members of the module docstring as {site: {role: float32}}."""
    rng = np.random.default_rng(seed)
    field = {r: red(rng) for r in ROLES}
    out = {}
    for k in range(1, 7):
        coils = {}
        for r in ROLES:
            noise = 0.1 * red(rng)
            x = noise if k == 5 else -(field[r] + noise) if k == 4 else field[r] + noise
            coils[r] = x.astype(np.float32)
        out[f"M{k}"] = coils
    return out


def full_gamma2(res, role: str, i: int) -> float:
    """Return member i's 0.1-10 s gamma2, the median over the usable chunks."""
    s = stackcheck.band_summary(res.coherence[role][FULL][i], res.usable[role])
    return float("nan") if s is None else s[0]


def flagged(res, mark: str) -> set:
    """Return the sites carrying `mark` on any channel."""
    return {site for (site, _role), marks in res.flags.items() if mark in marks}


def finite_everywhere(res) -> bool:
    """True when every coherence, polarity and preview value of the result is finite."""
    values = [g for role in res.roles for g in res.coherence[role].values()]
    values += [res.polarity[role] for role in res.roles]
    values += [v for role in res.roles for v in res.preview[role].values()]
    return bool(values) and all(np.isfinite(np.asarray(v, dtype=float)).all() for v in values)


def ratio_in_band(prev: dict, members: int = 1) -> float:
    """Return members times the median over the 0.1-10 s preview bands of stack power over the members' median."""
    ratio = prev["stack"] / np.median(prev["members"], axis=0)
    inside = (prev["periods"] >= FULL[0]) & (prev["periods"] <= FULL[1])
    return float(members * np.median(ratio[inside]))


# ------------------------------------------------------------------ 1


def criterion_1(arrays: dict) -> None:
    """Criterion 1."""
    res = stackcheck.compute_check(arrays, {}, FS, ROLES, "band")
    print(f"     note: {res.note!r}; flags {dict((k, v) for k, v in res.flags.items() if v)}")
    check(flagged(res, "reversed") == {"M4"}, f"(1) only M4 flagged reversed: {sorted(flagged(res, 'reversed'))}")
    check(flagged(res, "dead") == {"M5"}, f"(1) only M5 flagged dead: {sorted(flagged(res, 'dead'))}")
    sites = res.members
    for role in ROLES:
        good = [full_gamma2(res, role, sites.index(s)) for s in GOOD]
        check(min(good) >= 0.9, f"(1) {role}: good members' 0.1-10 s gamma2 >= 0.9: {np.round(good, 3)}")
        pol = res.polarity[role][sites.index("M4")]
        check(pol <= -0.5, f"(1) {role}: M4 polarity {pol:+.3f} <= -0.5")
        print(f"     {role}: M5 polarity {res.polarity[role][sites.index('M5')]:+.4f} "
              f"(dead: a sign here says nothing, so it is not flagged reversed)")
        total = sum(arrays[s][role].astype(np.float64) for s in sites)
        for i, site in enumerate(sites):
            x = arrays[site][role].astype(np.float64)
            others = (total - x) / (len(sites) - 1)
            f, c = welch_coherence(x, others, fs=FS, window="hann", nperseg=4096)
            ref = float(np.mean(c[(f >= 1 / FULL[1]) & (f <= 1 / FULL[0])]))
            got = full_gamma2(res, role, i)
            check(abs(got - ref) <= 0.05, f"(1) {role} {site}: gamma2 {got:.3f} vs scipy Welch {ref:.3f}")
            if site != "M5":
                corr = float(np.corrcoef(x, others)[0, 1])
                pol = res.polarity[role][i]
                check(np.sign(corr) == np.sign(pol), f"(1) {role} {site}: polarity {pol:+.3f}, time correlation "
                                                     f"{corr:+.3f}, same sign")


# ------------------------------------------------------------------ 2


def criterion_2() -> None:
    """Criterion 2."""
    t0 = pd.Timestamp("2023-12-10 01:00", tz="UTC")
    span = stackcheck.check_span(t0, t0 + pd.Timedelta(seconds=5000), 1000.0)
    check(span == (t0, t0 + pd.Timedelta(seconds=3600)), f"(2) 5000 s at 1000 Hz ends at 3600 s: {span[1]}")
    day = t0 + pd.Timedelta(hours=24)
    span = stackcheck.check_span(t0, day, 1000.0)
    check(span[1] == t0 + pd.Timedelta(seconds=3600), f"(2) a 24 h segment, 1000 Hz recipe: {span[1]}")
    span = stackcheck.check_span(t0, t0 + pd.Timedelta(seconds=600), 1000.0)
    check(span[1] == t0 + pd.Timedelta(seconds=600), f"(2) a 600 s segment ends at its end: {span[1]}")
    span = stackcheck.check_span(t0, day, 1.0)
    check(span[1] == day, f"(2) a 1 Hz recipe keeps the 24 h segment: {span[1]}")
    for fs, want in ((1000.0, (((0.1, 1.0), (1.0, 10.0), (0.1, 10.0)), 600.0, (1.0, 100.0))),
                     (1.0, (((10.0, 100.0), (100.0, 1000.0), (10.0, 1000.0)), 60000.0, (100.0, 10000.0)))):
        plan = stackcheck.check_plan(fs)
        got = (plan["bands"], plan["chunk_s"], plan["polarity_periods"])
        check(got == want, f"(2) check_plan({fs:g}): {got}")
    chunk = stackcheck.check_plan(1.0, span_s=86400.0)["chunk_s"]
    check(chunk == 28800.0, f"(2) check_plan(1, span 24 h) chunk {chunk:g} s")
    rng = np.random.default_rng(8)
    n = 86400
    field = red(rng, n)
    slow = {}
    for k in range(1, 7):
        noise = 0.1 * red(rng, n)
        slow[f"M{k}"] = {"hx": (noise if k == 5 else -(field + noise) if k == 4 else field + noise).astype(np.float32)}
    res = stackcheck.compute_check(slow, {}, 1.0, ("hx",), "band")
    full = stackcheck.check_plan(1.0)["full_band"]
    g = res.coherence["hx"].get(full)
    check(g is not None and g.shape[1] == 3, f"(2) 1 Hz over 24 h: coherence on {None if g is None else g.shape[1]} "
                                              f"chunks (note {res.note!r})")
    if g is not None:
        good = [stackcheck.band_summary(g[res.members.index(s)], res.usable["hx"])[0] for s in GOOD]
        check(min(good) >= 0.9, f"(2) 1 Hz: good members' {full[0]:g}-{full[1]:g} s gamma2 {np.round(good, 3)}")
    check(flagged(res, "reversed") == {"M4"} and flagged(res, "dead") == {"M5"},
          f"(2) 1 Hz flags: {dict((k, v) for k, v in res.flags.items() if v)}")


# ------------------------------------------------------------------ 3


def overlapping_windows(seen: list, scheme: dict) -> int:
    """Count the yielded band windows whose samples reach into GAP."""
    factor = int(scheme["decimation_factors"][1])
    count = 0
    for band in seen:
        half = (int(scheme["num_samples_window"][band.level]) + 1) / 2.0 * factor**band.level / FS
        count += int(np.sum((band.t_mid + half > GAP[0] / FS) & (band.t_mid - half < GAP[1] / FS)))
    return count


def criterion_3(arrays: dict) -> None:
    """Criterion 3."""
    gapped = {s: {r: a.copy() for r, a in c.items()} for s, c in arrays.items()}
    for r in ROLES:
        gapped["M2"][r][GAP[0]:GAP[1]] = 0.0
    seen: list = []
    real = intersite.band_spectra

    def spy(*args, **kwargs):
        for band in real(*args, **kwargs):
            seen.append(band)
            yield band

    scheme = build_band_scheme(FS, **stackcheck.check_plan(FS)["scheme"])
    chunk = int(stackcheck.check_plan(FS)["chunk_s"] * FS)
    hit = GAP[0] // chunk
    intersite.band_spectra = spy
    try:
        res = stackcheck.compute_check(gapped, {"M2": [GAP]}, FS, ROLES, "band")
        used_listed = overlapping_windows(seen, scheme)
        n_listed = len(seen)
        seen.clear()
        ctrl = stackcheck.compute_check(gapped, {}, FS, ROLES, "band")
        used_unlisted = overlapping_windows(seen, scheme)
    finally:
        intersite.band_spectra = real
    check(finite_everywhere(res), "(3) every coherence, polarity and preview value finite with the gap listed")
    for role in ROLES:
        want = np.ones(res.usable[role].size, dtype=bool)
        want[hit] = False
        check(np.array_equal(res.usable[role], want), f"(3) {role}: only chunk {hit} unusable: {res.usable[role]}")
        check(bool(ctrl.usable[role][hit]), f"(3) control {role}: gap not listed, chunk {hit} counted usable")
    check(used_listed == 0, f"(3) no polarity or preview window overlaps the gap ({n_listed} bands yielded)")
    check(used_unlisted > 0, f"(3) control: gap not listed, {used_unlisted} windows overlap it")
    clean = stackcheck.compute_check(arrays, {}, FS, ROLES, "band")
    i = res.members.index("M2")
    for role in ROLES:
        a, b = res.coherence[role][FULL][i, hit], clean.coherence[role][FULL][i, hit]
        check(abs(a - b) > 0.05, f"(3) control {role}: M2's gap chunk gamma2 {a:.3f} vs {b:.3f} without the gap")


# ------------------------------------------------------------------ 4


def criterion_4(arrays: dict) -> None:
    """Criterion 4."""
    four = {s: arrays[s] for s in GOOD}
    res = stackcheck.compute_check(four, {}, FS, ROLES, "band", stack="mean")
    for role in ROLES:
        r = ratio_in_band(res.preview[role])
        check(0.8 <= r <= 1.25, f"(4) {role}: band-mean preview of the four good members, stack/members {r:.3f}")
    rng = np.random.default_rng(17)
    six = {f"N{k}": {"hx": rng.standard_normal(N).astype(np.float32)} for k in range(6)}
    for stack, lo, hi in (("mean", 0.7, 1.3), ("median", 1.1, 1.5)):
        res = stackcheck.compute_check(six, {}, FS, ("hx",), "band", stack=stack)
        r = ratio_in_band(res.preview["hx"], 6)
        check(lo <= r <= hi, f"(4) six independent members, band {stack}: 6 x stack/members {r:.3f} in {lo}-{hi}")


# ------------------------------------------------------------------ 5


def criterion_5(arrays: dict) -> None:
    """Criterion 5."""
    res = stackcheck.compute_check(arrays, {}, FS, ROLES, "time", weighting="coherence")
    check(res.weights is not None and set(res.weights) == set(ROLES), "(5) the coherence time preview gives weights")
    for role, w in (res.weights or {}).items():
        err = float(np.max(np.abs(w.sum(axis=0) - 1.0)))
        check(err <= 1e-9, f"(5) {role}: weights sum to 1 in each of {w.shape[1]} chunks (max error {err:.1e})")
    check(finite_everywhere(res), f"(5) time preview values finite (note {res.note!r})")
    for subset in (["M1"], []):
        try:
            res = stackcheck.compute_check({s: arrays[s] for s in subset}, {}, FS, ROLES, "band")
        except Exception as exc:  # noqa: BLE001 - any raise fails the criterion
            check(False, f"(5) {len(subset)} member(s) raised {type(exc).__name__}: {exc}")
            continue
        check(res.note == stackcheck.NOTE_FEW, f"(5) {len(subset)} member(s): note {res.note!r}")


# ------------------------------------------------------------------ 6


def write_survey() -> Path:
    """Write six W members at 1000 Hz over 1200 s as archives of a scratch survey; return survey.yaml."""
    import virtual_unit  # noqa: E402  (its archive writer, at 1000 Hz)

    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    (root / "raw").mkdir(parents=True)
    work = root / "work"
    rng = np.random.default_rng(3)
    n = int(1200 * virtual_unit.FS)
    field = {c: 1000.0 * red(rng, n) for c in ROLES}
    sites = []
    for k in range(1, 7):
        coils = {c: 1.0e6 * k + (-1 if k == 4 else 1) * (field[c] + 100.0 * red(rng, n)) for c in ROLES}
        virtual_unit.write_archive(work, f"W{k}", [(pd.Timestamp("2024-03-01T00:00:00"),
                                                    {c: np.rint(v).astype("int32") for c, v in coils.items()})])
        sites.append(f"  W{k}: {{latitude: -31.{k}, longitude: 137.0}}")
    yaml_path = root / "survey.yaml"
    yaml_path.write_text(f"name: {virtual_unit.SURVEY}\ninstrument: lemi423\nsample_rate: 1000\n"
                         f"data_root: {(root / 'raw').as_posix()}\nworkspace: {work.as_posix()}\n"
                         "sites:\n" + "\n".join(sites) + "\n", encoding="utf-8")
    return yaml_path


def criterion_6(arrays: dict) -> None:
    """Criteria 6 and 7 (the widget)."""
    from PySide6.QtWidgets import QApplication

    from mt_workbench.gui import segment, theme
    from mt_workbench.gui.app import State
    from mt_workbench.gui.stack_check import MemberCheck

    slot_errors: list[str] = []
    sys.excepthook = lambda kind, value, tb: slot_errors.append(f"{kind.__name__}: {value}")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    yaml_path = write_survey()
    state = State(REPO)
    state.open_survey(yaml_path, fetch_basemap=False)
    widget = MemberCheck(state)
    widget.resize(1200, 900)
    widget.show()
    lock = state.archive_lock
    cycles = {"acquire": 0, "release": 0}
    real_acquire, real_release = lock.acquire, lock.release

    def acquire(holder):
        before = lock.holder
        ok = real_acquire(holder)
        cycles["acquire"] += int(holder is widget and before is None and lock.holder is widget)
        return ok

    def release(holder):
        before = lock.holder
        real_release(holder)
        cycles["release"] += int(before is widget and lock.holder is None)

    lock.acquire, lock.release = acquire, release
    reads: list[str] = []
    real_load = segment.load_segment

    def counting_load(path, survey_name, station, *args, **kwargs):
        reads.append(station)
        return real_load(path, survey_name, station, *args, **kwargs)

    segment.load_segment = counting_load
    results: list = []
    widget.ready.connect(results.append)
    widget.failed.connect(lambda msg: slot_errors.append(f"check failed: {msg}"))
    t0 = pd.Timestamp("2024-03-01T00:00:00", tz="UTC")
    span = stackcheck.check_span(t0, t0 + pd.Timedelta(seconds=1200), 1000.0)
    args = (("hx", "hy"), span, "band", "mean", None, 25.0, 2, True)

    def run(members) -> object:
        results.clear()
        widget.request(members, *args)
        end = time.time() + 300
        while not results and time.time() < end and not slot_errors:
            app.processEvents()
            time.sleep(0.01)
        for _ in range(20):  # let the finished thread's queued signals land
            app.processEvents()
        return results[0] if results else None

    try:
        first = ["W1", "W2", "W3", "W4", "W5"]
        started = time.time()
        res = run(first)
        print(f"     first check: {time.time() - started:.1f} s, reads {reads}")
        check(res is not None, "(6) the first check returned a result")
        check(not lock.busy, "(6) the archive lock is free after the result")
        check(cycles["acquire"] == cycles["release"] >= len(first),
              f"(6) lock cycles: {cycles['acquire']} taken, {cycles['release']} released, {len(first)} members")
        check(sorted(reads) == first, f"(6) each of the five members read once: {reads}")
        if res is not None:
            coh = res.coherence.get("hx", {}).get(FULL)
            g1 = None if coh is None else stackcheck.band_summary(coh[0], res.usable["hx"])
            check(not res.note and g1 is not None and g1[0] >= 0.9,
                  f"(6) coherence computed on the 1200 s span: note {res.note!r}, W1 gamma2 {g1}")
        reads.clear()
        res = run(first + ["W6"])
        check(res is not None, "(6) the check with W6 added returned a result")
        check(reads == ["W6"], f"(6) adding W6 reads that site only: {reads}")
        if res is not None:
            check(flagged(res, "reversed") == {"W4"} and not flagged(res, "dead"),
                  f"(6) W4, and W4 only, flagged reversed: {dict((k, v) for k, v in res.flags.items() if v)}")
        widget.clear()
        check(widget.kept_sites() == [], f"(6) clear() empties kept_sites(): {widget.kept_sites()}")
        widget.request(first, *args)
        app.processEvents()
        started = time.time()
        widget.wait()
        took = time.time() - started
        check(took <= 30.0, f"(6) wait() on a check in flight returned in {took:.1f} s")
        check(not lock.busy, "(6) the lock is free after wait()")
        for _ in range(20):
            app.processEvents()
        criterion_7(widget, arrays)
    finally:
        segment.load_segment = real_load
        widget.clear()
        widget.close()
        widget.deleteLater()
        app.processEvents()
    check(not slot_errors, f"(6) no Qt slot raised: {slot_errors}")


def _rgb(brush_or_pen) -> tuple[int, int, int]:
    """Return the (r, g, b) of a pyqtgraph brush or pen."""
    return brush_or_pen.color().getRgb()[:3]


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    """Return the (r, g, b) of a "#rrggbb" colour."""
    return tuple(int(colour[i: i + 2], 16) for i in (1, 3, 5))


def criterion_7(widget, arrays: dict) -> None:
    """Criterion 7: the bars and panels as MemberCheck draws them."""
    import pyqtgraph as pg

    from mt_workbench.gui import theme

    t0 = pd.Timestamp("2024-03-01T00:00:00", tz="UTC")
    span = (t0, t0 + pd.Timedelta(hours=1))
    e_arrays = {site: {"ex": c["hx"], "ey": c["hy"]} for site, c in arrays.items()}
    for roles, field_colour, label in ((("ex", "ey"), theme.E_COLOUR, "E"), (ROLES, theme.B_COLOUR, "H")):
        res = stackcheck.compute_check(e_arrays if label == "E" else arrays, {}, FS, roles, "band")
        res.span = span
        widget._show(res)
        items = widget.bars.getPlotItem().items
        bars = [i for i in items if isinstance(i, pg.BarGraphItem)]
        texts = [i.textItem.toPlainText() for i in items if isinstance(i, pg.TextItem)]
        check(len(bars) == 1, f"(7) {label}: one bar item drawn ({len(bars)})")
        if len(bars) != 1:
            continue
        brushes, pens = bars[0].opts["brushes"], bars[0].opts["pens"]
        members = list(res.members)
        dead, good = members.index("M5"), members.index("M1")
        fill = _rgb(brushes[dead])
        far = max(abs(a - b) for a, b in zip(fill, _hex_rgb(theme.E_COLOUR)))
        if label == "E":
            check(far > 40 and _rgb(pens[dead]) == _hex_rgb(theme.BAD_COLOUR) and "dead" in texts,
                  f"(7) E: M5's ex bar (dead) is filled {fill}, {far} levels from E_COLOUR (over 40), outlined "
                  f"{_rgb(pens[dead])} (BAD_COLOUR {_hex_rgb(theme.BAD_COLOUR)}), flag texts {texts}")
        check(_rgb(brushes[good]) == _hex_rgb(field_colour),
              f"(7) {label}: M1's unflagged {roles[0]} bar is filled {_rgb(brushes[good])}, the field's colour "
              f"{_hex_rgb(field_colour)}")
    layout = widget.layout()
    tops = [widget.panels[0].geometry().top(), widget.panels[1].geometry().top()]
    lefts = [widget.panels[0].geometry().left(), widget.panels[1].geometry().left()]
    check(tops[0] < tops[1] and lefts[0] == lefts[1] and layout is not None,
          f"(7) the preview panels sit one over the other, By-Ex (Zxy) on top: tops {tops}, lefts {lefts}")


def main() -> None:
    """Run criteria 1-7; exit 1 on any failure."""
    print(__doc__.split("**This test fails if**")[1].rstrip())
    arrays = six_members()
    for step in (lambda: criterion_1(arrays), criterion_2, lambda: criterion_3(arrays),
                 lambda: criterion_4(arrays), lambda: criterion_5(arrays), lambda: criterion_6(arrays)):
        started = time.time()
        step()
        print(f"     ({time.time() - started:.1f} s)")
    if failures:
        print(f"\nFAIL  stack_check_unit ({len(failures)} failure(s))")
        sys.exit(1)
    print("\nPASS  stack_check_unit")


if __name__ == "__main__":
    main()
