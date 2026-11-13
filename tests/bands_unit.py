# -*- coding: utf-8 -*-
"""
Unit test for the band widths of mt_workbench.bands.build_band_scheme

Checks that `build_band_scheme` refuses a band layout with a band narrower
than one FFT harmonic spacing and leaves working layouts unchanged. Runs on
the band scheme alone, without an archive or an aurora run.

Usage:
    python tests/bands_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** a layout with a band narrower than one FFT harmonic
spacing is accepted: at 10 Hz with a 128-point window, `min_period` 2 s and
`max_period` 10,000 s (unchecked, such a layout loses bands silently at
every level with a notch list, and without one aurora stops with a bare
IndexError) must
raise ValueError naming the level, the band and "harmonic", with notches and
without; or a layout that works is refused or changed: the 10 Hz survey
defaults (min 0.005 s, max 5000 s, notches 50 and 150 Hz; 41 bands on 7
levels), the Orange Box layout (min 0.4 s, max 6553.6 s; 42 bands) and the
1000 Hz broadband defaults (60 bands, the notch guards at 50 and 150 Hz
still carved out), judged on an independent observable: every accepted
band is handed to mt_metadata's own `Band.set_indices_from_frequencies` with
the level's `np.fft.rfftfreq(window, 1 / fs_level)`, which raises IndexError
on a band holding no harmonic, and must hold at least one; or the old guard
(lowest edge under 1.5 harmonics: a 32-point window at min 2 s) no longer
raises.

The lowest harmonic. **This test also fails if**, on the 1000 Hz broadband
layout (min 0.005 s, max 5000 s, notches 50 and 150 Hz), judged by the
harmonics mt_metadata's `Band.set_indices_from_frequencies` finds in each
band (the level's own window and rate): without `min_bin` the lowest edge
(`lowest_harmonic`) is not 6.4 or the two lowest bands of any full
decimated level do not hold exactly harmonics 7-8 and 9-10; `min_bin` 6.4
or None does not give band edges identical to those of the call
without it; `min_bin` 10 (12) does not give a lowest edge of 6.4 * 4**(2/6)
= 10.16 (12.8), a first harmonic of at least 10 (12) in every band of
every decimated level, 4 (3) bands on level 0 against 6, and the same 53
band centre periods below 1000 s to 1e-9 as the layout without it, the
bands of the 7-10 harmonics now holding at least 7 harmonics each; a
256-point window does not give the same 60 periods with each band holding
at least as many harmonics as with 128 and the two lowest bands of each
decimated level 4 each; or `min_bin` 25.6 (the layout's own 6.4 times 4,
which empties level 0) is accepted instead of refused with ValueError
naming level 0.

One `min_period` at several rates (the Kalkaroo case: 150 Hz Phoenix,
1000 Hz LEMI-423 and 24 kHz bursts). **This test also fails if**, with the
survey at 150 Hz and `min_period` 4**(14/6)/6000 s (0.004233) or
4**(22/6)/6000 s (0.026878) and `max_period` 4**(75/6)/6000 s (5592.4),
the layout of each site (its `min_period` from `site_min_period`) has an
edge off the lattice 6000 / 4**(k/6) Hz (integer k, to 1e-9 relative), an
edge above a quarter of its rate, or a top edge other than 37.2047 Hz
(k = 22) at 150 Hz, 236.235 Hz (k = 14) at 1000 Hz and 6000 Hz (k = 0) at
24 kHz; if aurora's own band assignment (`Processing.assign_bands`, what
`ConfigCreator.create_from_kernel_dataset` calls) leaves a band of either
layout without a harmonic or above its level's Nyquist; if the 150 Hz
layout of 0.004233 s differs from that of 0.026878 s (to 1e-12, so a
150 Hz product of a035bc7 keeps its bands); if `site_min_period(1000, 150,
4**(22/6)/6000)` is not 4**(14/6)/6000, or `site_min_period(24000, 150,
...)` not exactly 1/6000; or if process_rr's `resolve`, on a scratch
150 Hz survey with two 150 Hz and two 1000 Hz sites, gives a scheme
(`build_band_scheme(res["sample_rate"], **res["scheme_kwargs"])`, as its
run builds it) whose top edge is not 37.2047 Hz for the 150 Hz pair and
236.235 Hz for the 1000 Hz pair under either `min_period`. The control: the
1000 Hz broadband layout (0.005 s) keeps its top edge of 200.0 Hz exactly
and every edge on the 0.005 s lattice, and 100 Hz at 0.005 s (200 Hz nine
steps down is the quarter rate) keeps 25.0 Hz exactly, as aurora_fork_unit's
fixtures need. With `max_period` 5000 s, off the
lattice, only the last (partial) level's edges leave it, at every rate.
The mutation: `top_edge` made the old rule (1 / min_period capped at a
quarter of the rate) must trip the check with the 150 Hz top at 37.5 Hz.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import mt_workbench.bands as bands  # noqa: E402
from mt_workbench.bands import build_band_scheme, lowest_harmonic, site_min_period  # noqa: E402

BROADBAND = dict(min_period=0.005, max_period=5000.0, notch_frequencies=(50.0, 150.0))
# the 24 kHz bursts' lattice: band edges at 6000 / 4**(k/6) Hz
M14, M22, M75 = (4 ** (m / 6) / 6000 for m in (14, 22, 75))
TOPS = {150.0: 22, 1000.0: 14, 24000.0: 0}  # the lattice index of each rate's top edge


def lattice_index(f_hz: float, base_hz: float = 6000.0) -> tuple[int, float]:
    """Return the nearest k of base / 4**(k/6) to a frequency and the relative distance from it."""
    k = round(6 * np.log(base_hz / f_hz) / np.log(4))
    return k, abs(f_hz / (base_hz / 4 ** (k / 6)) - 1.0)


def check_rates(min_period: float, max_period: float = M75) -> tuple[list[str], dict]:
    """Lay out each Kalkaroo rate from one survey min_period at 150 Hz. Returns the failures and the layouts."""
    from aurora.config.metadata.processing import Processing

    bad, layouts = [], {}
    for fs, k_top in TOPS.items():
        mp = site_min_period(fs, 150.0, min_period)
        scheme = build_band_scheme(fs, min_period=mp, max_period=max_period)
        layouts[fs] = scheme
        edges = np.unique(np.concatenate([np.ravel(b) for b in scheme["band_edges"].values()]))
        off = [float(f) for f in edges if lattice_index(f)[1] > 1e-9]
        if off:
            bad.append(f"{fs:g} Hz: {len(off)} edges off the lattice, the first {off[0]:.6g} Hz")
        top = float(edges.max())
        k, distance = lattice_index(top)
        if k != k_top or distance > 1e-9:
            bad.append(f"{fs:g} Hz: top edge {top:.6g} Hz (k {k}), expected {6000 / 4 ** (k_top / 6):.6g} Hz "
                       f"(k {k_top})")
        if top > 0.25 * fs * (1 + 1e-12):
            bad.append(f"{fs:g} Hz: top edge {top:.6g} Hz above a quarter of the rate")
        processing = Processing(id="lattice")
        processing.assign_bands(scheme["band_edges"], fs, scheme["decimation_factors"], scheme["num_samples_window"])
        for level in processing.decimations:
            nyquist = level.decimation.sample_rate / 2
            for band in level.bands:
                if band.index_max < band.index_min or band.frequency_max > nyquist:
                    bad.append(f"{fs:g} Hz level {level.decimation.level}: band {band.frequency_min:.4g}-"
                               f"{band.frequency_max:.4g} Hz, harmonics {band.index_min}-{band.index_max}")
    return bad, layouts


def test_one_min_period_at_every_rate() -> None:
    for min_period in (M14, M22):
        bad, layouts = check_rates(min_period)
        assert not bad, (min_period, bad)
        tops = {fs: float(max(np.max(b) for b in s["band_edges"].values())) for fs, s in layouts.items()}
        print(f"  min_period {min_period:.6g} s: top edges {', '.join(f'{fs:g} Hz {t:.6g}' for fs, t in tops.items())}"
              f" Hz, every edge on 6000 / 4**(k/6), aurora's assign_bands gives every band a harmonic")
    low = build_band_scheme(150.0, min_period=M14, max_period=M75)["band_edges"]
    high = build_band_scheme(150.0, min_period=M22, max_period=M75)["band_edges"]
    assert low.keys() == high.keys() and all(np.allclose(low[k], high[k], rtol=1e-12, atol=0) for k in low)
    assert abs(site_min_period(1000.0, 150.0, M22) / M14 - 1) < 1e-12, site_min_period(1000.0, 150.0, M22)
    assert site_min_period(24000.0, 150.0, M22) == 1 / 6000, site_min_period(24000.0, 150.0, M22)
    assert site_min_period(1.0, 1000.0, 0.005) == 4.0 and site_min_period(150.0, 150.0, M14) == M14
    print(f"  150 Hz at {M14:.6g} s = 150 Hz at {M22:.6g} s to 1e-12; site_min_period: 1000 Hz {M14:.6g} s, "
          f"24 kHz 1/6000 s, 1 Hz in a 1000 Hz survey 4 s")
    control = build_band_scheme(1000.0, **BROADBAND)
    edges = np.unique(np.concatenate([np.ravel(b) for b in control["band_edges"].values()]))
    guards = {f * (1 + s * 0.08) for f in (50.0, 150.0) for s in (-1, 1)}
    off = [f for f in edges if lattice_index(f, 200.0)[1] > 1e-9 and min(abs(f - g) for g in guards) > 1e-9]
    last = control["band_edges"][max(control["band_edges"])]
    assert float(edges.max()) == 200.0 and all(np.min(np.abs(last - f)) < 1e-15 for f in off), off
    quarter = max(float(np.max(b)) for b in build_band_scheme(100.0, max_period=10.0)["band_edges"].values())
    assert quarter == 25.0, quarter  # 200 / 4**(9/6) is the quarter rate: kept exactly (aurora_fork_unit)
    for fs in TOPS:
        scheme = build_band_scheme(fs, min_period=site_min_period(fs, 150.0, M14), max_period=5000.0)
        *full, partial = scheme["band_edges"].values()
        assert not [f for b in full for f in np.ravel(b) if lattice_index(f)[1] > 1e-9], fs
        assert [f for f in np.ravel(partial) if lattice_index(f)[1] > 1e-9], fs
    print(f"  control: 1000 Hz at 0.005 s keeps its top edge 200.0 Hz, {len(off)} edges off its lattice, all on "
          f"the last level; max_period 5000 s leaves the lattice on the last level only, at 150, 1000 and 24000 Hz")
    kept = bands.top_edge
    bands.top_edge = lambda sample_rate, min_period, *_: min(1.0 / min_period, 0.25 * sample_rate)
    try:
        trip, _ = check_rates(M14)
    finally:
        bands.top_edge = kept
    assert any(t.startswith("150 Hz: top edge 37.5 Hz") for t in trip), trip
    print(f"  mutation (the old cap at a quarter of the rate) tripped: {trip[0]}")


def test_process_rr_resolve_at_two_rates() -> None:
    import datetime
    import importlib.util
    import tempfile

    import yaml

    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    rr.check_pair = lambda *args, **kwargs: {}  # spans need archives; the band choice comes before
    got = {}
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "data").mkdir()
        for min_period in (M14, M22):
            config = {"name": "TWO_RATES", "instrument": "phoenix", "sample_rate": 150.0,
                      "data_root": str(folder / "data"), "workspace": str(folder / "workspace"),
                      "processing": {"min_period": min_period, "max_period": 5000.0},
                      "sites": {"A": {}, "B": {}, "L1": {"instrument": "lemi423", "sample_rate": 1000},
                                "L2": {"instrument": "lemi423", "sample_rate": 1000}}}
            survey_yaml = folder / "survey.yaml"
            survey_yaml.write_text(yaml.safe_dump(config))
            for local, remote in (("A", "B"), ("L1", "L2")):
                res = rr.resolve(rr.build_parser().parse_args([str(survey_yaml), local, remote]),
                                 datetime.datetime.now())
                scheme = build_band_scheme(res["sample_rate"], **res["scheme_kwargs"])
                got[(round(min_period, 6), local)] = float(max(np.max(b) for b in scheme["band_edges"].values()))
    want = {"A": 6000 / 4 ** (22 / 6), "L1": 6000 / 4 ** (14 / 6)}
    wrong = {k: v for k, v in got.items() if abs(v / want[k[1]] - 1) > 1e-9}
    assert not wrong, (wrong, want)
    print(f"  process_rr resolve, 150 Hz survey: top edges {', '.join(f'{k[1]} at {k[0]} s {v:.6g} Hz' for k, v in got.items())}")


def harmonics_per_band(fs: float, scheme: dict, window: int = 128, factor: int = 4) -> list[int]:
    """Count the FFT harmonics in each band of a scheme using mt_metadata's Band.

    Args:
        fs (float): Sample rate of decimation level 0 in Hz.
        scheme (dict): Band scheme with a "band_edges" mapping of level to
            (low, high) frequency pairs.
        window (int): FFT window length in samples.
        factor (int): Decimation factor between levels.

    Returns:
        list[int]: Harmonic count of every band, level by level.

    Raises:
        IndexError: From `Band.set_indices_from_frequencies` when a band
            holds no harmonic.
    """
    from mt_metadata.common.band import Band

    counts = []
    for level, bands in scheme["band_edges"].items():
        freqs = np.fft.rfftfreq(window, 1.0 / (fs / factor**level))
        for lo, hi in bands:
            band = Band(frequency_min=float(lo), frequency_max=float(hi))
            band.set_indices_from_frequencies(freqs)
            counts.append(int(band.index_max) - int(band.index_min) + 1)
    return counts


def band_harmonics(fs: float, scheme: dict, factor: int = 4) -> list[tuple[int, float, int, int]]:
    """List every band's level, centre period and first and last harmonic using mt_metadata's Band.

    Args:
        fs (float): Sample rate of decimation level 0 in Hz.
        scheme (dict): Band scheme from `build_band_scheme`; each level's
            window is read from its "num_samples_window".
        factor (int): Decimation factor between levels.

    Returns:
        list[tuple[int, float, int, int]]: ``(level, period_s, first,
        last)`` per band, level by level, the period being 1 / sqrt(lo * hi)
        as aurora labels it.
    """
    from mt_metadata.common.band import Band

    rows = []
    for level, bands in scheme["band_edges"].items():
        window = scheme["num_samples_window"][level]
        freqs = np.fft.rfftfreq(window, 1.0 / (fs / factor**level))
        for lo, hi in bands:
            band = Band(frequency_min=float(lo), frequency_max=float(hi))
            band.set_indices_from_frequencies(freqs)
            rows.append((int(level), 1.0 / float(np.sqrt(lo * hi)), int(band.index_min), int(band.index_max)))
    return rows


def test_min_bin_moves_the_level_boundaries() -> None:
    base = build_band_scheme(1000.0, **BROADBAND)
    rows = band_harmonics(1000.0, base)
    assert abs(lowest_harmonic(1000.0, **BROADBAND) - 6.4) < 1e-9, lowest_harmonic(1000.0, **BROADBAND)
    full = range(1, len(base["band_edges"]) - 1)  # decimated levels with the whole factor-4 slice
    for level in full:
        mine = sorted((r for r in rows if r[0] == level), key=lambda r: -r[1])
        assert [(r[2], r[3]) for r in mine[:2]] == [(7, 8), (9, 10)], (level, mine[:2])
    for same in (6.4, None):
        other = build_band_scheme(1000.0, **BROADBAND, min_bin=same)
        assert all(other["band_edges"][k].tobytes() == base["band_edges"][k].tobytes() for k in base["band_edges"])
    base_periods = np.array(sorted(r[1] for r in rows if r[1] < 1000.0))
    edge_bands = {round(r[1], 9) for r in rows if r[0] in full and r[2] <= 10}
    for min_bin, edge, level0 in ((10, 6.4 * 4 ** (2 / 6), 4), (12, 12.8, 3)):
        scheme = build_band_scheme(1000.0, **BROADBAND, min_bin=min_bin)
        got = band_harmonics(1000.0, scheme)
        assert abs(lowest_harmonic(1000.0, **BROADBAND, min_bin=min_bin) - edge) < 1e-9, min_bin
        low = [r for r in got if r[0] > 0 and r[2] < min_bin]
        assert not low, (min_bin, low)
        assert len(scheme["band_edges"][0]) == level0 and len(base["band_edges"][0]) == 6, min_bin
        periods = np.array(sorted(r[1] for r in got if r[1] < 1000.0))
        assert periods.size == base_periods.size == 60 - 7 and np.allclose(periods, base_periods, rtol=1e-9, atol=0)
        moved = [r for r in got if round(r[1], 9) in edge_bands]
        assert moved and min(r[3] - r[2] + 1 for r in moved) >= 7, (min_bin, moved)
        print(f"  min_bin {min_bin}: lowest edge {edge:.4g} harmonics, first harmonic >= {min_bin} on every "
              f"decimated level, level 0 {level0} bands, the {periods.size} periods under 1000 s unchanged, the "
              f"bands of harmonics 7-10 now {min(r[3] - r[2] + 1 for r in moved)}-"
              f"{max(r[3] - r[2] + 1 for r in moved)} harmonics")
    wide = build_band_scheme(1000.0, **BROADBAND, window=256)
    got = band_harmonics(1000.0, wide)
    assert abs(lowest_harmonic(1000.0, **BROADBAND, window=256) - 12.8) < 1e-9
    assert np.allclose([r[1] for r in got], [r[1] for r in rows], rtol=1e-12, atol=0), "periods moved with window"
    assert all(g[3] - g[2] >= r[3] - r[2] for g, r in zip(got, rows)), "a band lost harmonics with window 256"
    for level in full:
        mine = sorted((r for r in got if r[0] == level), key=lambda r: -r[1])
        assert [r[3] - r[2] + 1 for r in mine[:2]] == [4, 4], (level, mine[:2])
    print("  window 256: lowest edge 12.8 harmonics, the same 60 periods, the two lowest bands of each "
          "decimated level 4 harmonics each (2 with 128)")
    try:
        build_band_scheme(1000.0, **BROADBAND, min_bin=25.6)
    except ValueError as exc:
        refused = str(exc)
    else:
        raise AssertionError("min_bin 25.6 (four times the layout's own 6.4) was accepted")
    assert "level 0" in refused, refused
    print(f"  min_bin 25.6 refused: {refused}")


def test_too_narrow_is_refused() -> None:
    for notches in ((), (50.0, 150.0)):
        try:
            build_band_scheme(10.0, min_period=2.0, max_period=10000.0, notch_frequencies=notches)
        except ValueError as exc:
            text = str(exc)
            assert "level 0" in text and "harmonic" in text and "0.125-0.1575 Hz" in text, text
        else:
            raise AssertionError(f"min 2 s at 10 Hz accepted (notches {notches})")
    print(f"  10 Hz, min 2 s, max 10,000 s: refused with and without notches: {text[:110]}...")


def test_working_layouts_unchanged() -> None:
    cases = [(10.0, dict(min_period=0.005, max_period=5000.0, notch_frequencies=(50.0, 150.0)), 41, 7),
             (10.0, dict(min_period=0.4, max_period=6553.6), 42, 7),
             (1000.0, dict(min_period=0.005, max_period=5000.0, notch_frequencies=(50.0, 150.0)), 60, 10)]
    for fs, kw, n_bands, n_levels in cases:
        scheme = build_band_scheme(fs, **kw)
        got = sum(len(b) for b in scheme["band_edges"].values())
        assert got == n_bands and len(scheme["band_edges"]) == n_levels, (fs, kw, got, len(scheme["band_edges"]))
        counts = harmonics_per_band(fs, scheme)
        assert min(counts) >= 1, (fs, kw, counts)
        if fs == 1000.0:
            level0 = scheme["band_edges"][0]
            assert not any(lo < 54.0 and hi > 46.0 for lo, hi in level0), "50 Hz guard not carved out"
        print(f"  {fs:g} Hz {kw}: {got} bands on {n_levels} levels, {min(counts)}-{max(counts)} harmonics a band")


def test_old_guard_still_raises() -> None:
    try:
        build_band_scheme(10.0, min_period=2.0, max_period=10000.0, window=32)
    except ValueError as exc:
        assert "lowest band edge" in str(exc), exc
    else:
        raise AssertionError("a 32-point window at min 2 s (edge at 0.4 harmonics) was accepted")
    print("  32-point window at 10 Hz, min 2 s: the lowest-edge guard still raises")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  bands_unit ({len(tests)} tests)")
