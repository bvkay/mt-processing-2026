# -*- coding: utf-8 -*-
"""
Decimation and frequency-band schemes for aurora processing

`build_band_scheme` lays out bands in the lemimt manner: an even spread of
periods in log space (about 10 per decade) from `min_period` out to
`max_period`, across cascaded factor-4 decimation levels. Each level covers
one factor-4 slice of frequency, so band positions relative to the FFT
harmonics are identical at every level, and the lowest edge sits about 6
harmonics above DC (6.4 at 1000 Hz with a `min_period` of 0.005 s).

`min_bin` sets that lowest edge to the first edge of the same layout at or
above harmonic `min_bin` (`lowest_harmonic`): the level boundaries move by
whole bands, so every band keeps its period. Raised, the bands at the foot
of a level move to the top of the next decimation level, where they span
four times as many harmonics.

The returned dictionary is passed as keyword arguments to aurora's
``ConfigCreator.create_from_kernel_dataset``.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import numpy as np


def _apply_notches(
    bands: np.ndarray, notch_frequencies, notch_fraction: float, df: float
) -> np.ndarray:
    """Trim band edges away from notch lines.

    Args:
        bands (np.ndarray): (n, 2) array of band edges in Hz.
        notch_frequencies (iterable of float): Notch line frequencies in Hz.
        notch_fraction (float): Half-width of the guard around each line, as
            a fraction of the line frequency.
        df (float): FFT harmonic spacing of the level in Hz.

    Returns:
        np.ndarray: The trimmed bands. Pieces narrower than `df` are dropped.
    """
    for f0 in notch_frequencies:
        lo, hi = f0 * (1 - notch_fraction), f0 * (1 + notch_fraction)
        trimmed = []
        for a, b in bands:
            if b <= lo or a >= hi:
                trimmed.append((a, b))
                continue
            if a < lo:
                trimmed.append((a, lo))
            if b > hi:
                trimmed.append((hi, b))
        bands = np.array([(a, b) for a, b in trimmed if (b - a) >= df])
    return bands


def _level_shift(
    sample_rate: float,
    min_period: float,
    periods_per_decade: float,
    window: int,
    factor: int,
    min_bin: float | None,
) -> tuple[float, float]:
    """Return the lowest band edge in FFT harmonics and the level-boundary shift it takes.

    Args:
        sample_rate (float): Sample rate of the run in Hz.
        min_period (float): Shortest period in s.
        periods_per_decade (float): Number of bands per decade of period.
        window (int): FFT window length in samples.
        factor (int): Decimation factor between levels.
        min_bin (float or None): Lowest band edge asked for, in harmonics.

    Returns:
        tuple: ``(k_lo, shift)``. `k_lo` is the lowest band edge of every
        decimated level in harmonics; `shift` is the factor by which the
        level boundaries move up in frequency, a whole number of band
        steps of the layout (1.0 when `min_bin` is None).
    """
    f_top = min(1.0 / min_period, 0.25 * sample_rate)
    k_lo = f_top * window / (factor * sample_rate)
    if min_bin is None:
        return k_lo, 1.0
    step = float(factor) ** (1.0 / max(1, round(periods_per_decade * np.log10(factor))))
    n_steps = int(np.ceil(np.log(float(min_bin) / k_lo) / np.log(step) - 1e-9))
    shift = step**n_steps
    return k_lo * shift, shift


def lowest_harmonic(
    sample_rate: float,
    min_period: float = 0.005,
    periods_per_decade: float = 10.0,
    window: int = 128,
    factor: int = 4,
    min_bin: float | None = None,
    **_other,
) -> float:
    """Return the lowest band edge of the decimated levels in FFT harmonics of the level.

    The keyword arguments are those of `build_band_scheme`, so a scheme's
    keyword dictionary can be passed whole; its other keys are accepted and
    have no effect here.

    Args:
        sample_rate (float): Sample rate of the run in Hz.
        min_period (float): Shortest period in s.
        periods_per_decade (float): Number of bands per decade of period.
        window (int): FFT window length in samples.
        factor (int): Decimation factor between levels.
        min_bin (float or None): Lowest band edge asked for, in harmonics.

    Returns:
        float: The edge: f_top * window / (factor * sample_rate) with
        `min_bin` None (6.4 at 1000 Hz with the survey defaults), else the
        first edge of the same layout at or above `min_bin` (10.16 for 10,
        12.8 for 12 at 1000 Hz).
    """
    return _level_shift(sample_rate, min_period, periods_per_decade, window, factor, min_bin)[0]


def build_band_scheme(
    sample_rate: float,
    min_period: float = 0.005,
    max_period: float = 5000.0,
    periods_per_decade: float = 10.0,
    window: int = 128,
    factor: int = 4,
    notch_frequencies: tuple = (),
    notch_fraction: float = 0.08,
    min_bin: float | None = None,
) -> dict:
    """Build keyword arguments for aurora's ConfigCreator.create_from_kernel_dataset.

    Bands are spaced evenly in log period on each decimation level. Any band
    touching one of `notch_frequencies` has a guard of +/-`notch_fraction`
    carved out of it, so no band integrates energy from those lines.

    With `min_bin`, the boundary between each pair of levels moves up by
    the whole number of band steps that brings the lowest edge of every
    decimated level to or above harmonic `min_bin` (`lowest_harmonic`).
    The band edges stay those of the layout without it, so the periods are
    unchanged except on a partial last level; level 0 loses the bands at
    its foot to level 1, and each decimated level reaches up to `factor`
    times its lowest edge (0.32 of its sample rate for a `min_bin` of 10,
    0.4 for 12, at 1000 Hz with the survey defaults).

    Args:
        sample_rate (float): Sample rate of the run in Hz.
        min_period (float): Shortest period in s. The top band edge is
            capped at a quarter of the sample rate.
        max_period (float): Longest period in s.
        periods_per_decade (float): Number of bands per decade of period.
        window (int): FFT window length in samples, the same on every level.
        factor (int): Decimation factor between levels.
        notch_frequencies (tuple of float): Lines to avoid in Hz, for
            example mains at 50 Hz and its harmonics.
        notch_fraction (float): Half-width of each notch guard as a fraction
            of the line frequency.
        min_bin (float, optional): Lowest band edge of the decimated levels
            in FFT harmonics; None keeps the layout's own,
            ``min(1 / min_period, sample_rate / 4) * window / (factor *
            sample_rate)`` harmonics.

    Returns:
        dict: ``{"band_edges", "decimation_factors", "num_samples_window"}``,
        with ``band_edges`` keyed by decimation level.

    Raises:
        ValueError: If `max_period` does not exceed `min_period`, if the
            lowest band edge sits below FFT harmonic 1.5, if `min_bin`
            leaves level 0 without a band, or if a band of
            the even layout is narrower than one FFT harmonic spacing of its
            level. The last message names the level and the band and
            suggests a fix. The lowest band of a level spans
            k_min (factor**(1/n) - 1) harmonics; a narrower band may hold no
            harmonic at all, and aurora then stops in mt_metadata with a bare
            IndexError (docs/upstream_issues.md 20), while with any notch
            listed `_apply_notches` drops it as a sliver. At 10 Hz a
            `min_period` of 2 s triggers both cases: 13 of 41 periods remain,
            or aurora fails.
    """
    f_top = min(1.0 / min_period, 0.25 * sample_rate)
    f_floor = 1.0 / max_period
    if f_floor >= f_top:
        raise ValueError("max_period must exceed min_period")

    # lowest band edge in units of FFT harmonics (same at every decimated level)
    k_min, shift = _level_shift(sample_rate, min_period, periods_per_decade, window, factor, min_bin)
    if k_min < 1.5:
        raise ValueError(
            f"lowest band edge would sit at FFT harmonic {k_min:.2f}; "
            f"increase window or min_period"
        )
    if shift >= factor * (1.0 - 1e-9):
        raise ValueError(
            f"min_bin {min_bin:g} moves the level boundaries up {shift:.3g}x, which leaves decimation level 0 "
            f"no band (its lowest edge would be {k_min:.2f} harmonics, the top of a level {factor}x that)"
        )

    band_edges: dict[int, np.ndarray] = {}
    level = 0
    while True:
        f_level = f_top / factor**level
        f_hi = f_level * (shift if level else 1.0)
        f_lo = max(f_level * shift / factor, f_floor)
        n_bands = max(1, round(periods_per_decade * np.log10(f_hi / f_lo)))
        edges = np.geomspace(f_lo, f_hi, n_bands + 1)
        bands = np.column_stack([edges[:-1], edges[1:]])
        df_level = sample_rate / factor**level / window
        narrow = (bands[:, 1] - bands[:, 0]) < df_level * (1.0 - 1e-9)
        if narrow.any():
            a, b = bands[narrow][0]
            ratio = (f_hi / f_lo) ** (1.0 / n_bands)
            partial = f_lo == f_floor and f_floor > f_hi / factor
            fix = (f"move max_period off {max_period:g} s (this last level is a {f_hi / f_lo:.2f}x sliver)"
                   if partial else
                   f"lower min_period to {(ratio - 1.0) * window / (factor * sample_rate):.3g} s or less, "
                   f"or raise window")
            raise ValueError(
                f"band {a:.4g}-{b:.4g} Hz ({1 / b:.4g}-{1 / a:.4g} s) on decimation level {level} is "
                f"{(b - a) / df_level:.2f} FFT harmonics wide (spacing {df_level:.4g} Hz: {window} points at "
                f"{sample_rate / factor**level:.4g} Hz), so it may hold no harmonic ({int(narrow.sum())} of the "
                f"level's {len(bands)} bands are that narrow): {fix}"
            )
        bands = _apply_notches(bands, notch_frequencies, notch_fraction, df_level)
        band_edges[level] = bands
        if f_lo <= f_floor or level >= 15:
            break
        level += 1

    decimation_factors = [1] + [factor] * (len(band_edges) - 1)
    return {
        "band_edges": band_edges,
        "decimation_factors": decimation_factors,
        # aurora requires one window size per level when band_edges is given
        "num_samples_window": [window] * len(band_edges),
    }
