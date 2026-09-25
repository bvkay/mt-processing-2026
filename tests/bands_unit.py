# -*- coding: utf-8 -*-
"""
Unit test for the band widths of crust.bands.build_band_scheme

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
still carved out) -- judged on an independent observable: every accepted
band is handed to mt_metadata's own `Band.set_indices_from_frequencies` with
the level's `np.fft.rfftfreq(window, 1 / fs_level)`, which raises IndexError
on a band holding no harmonic, and must hold at least one; or the old guard
(lowest edge under 1.5 harmonics: a 32-point window at min 2 s) no longer
raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.bands import build_band_scheme  # noqa: E402


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
