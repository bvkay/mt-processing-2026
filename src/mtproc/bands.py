"""Decimation and frequency-band schemes for aurora processing.

`lemimt_band_scheme` lays out bands lemimt-style: an even spread of periods in
log space (~10 per decade) from `min_period` out to `max_period`, across
cascaded factor-4 decimation levels. Each level covers one factor-4 slice of
frequency, so band positions relative to the FFT harmonics are identical at
every level (lowest edge sits a safe ~6 harmonics above DC by construction).
"""

from __future__ import annotations

import numpy as np


def _apply_notches(
    bands: np.ndarray, notch_frequencies, notch_fraction: float, df: float
) -> np.ndarray:
    """Trim band edges away from notch lines; drop slivers narrower than one FC bin."""
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


def lemimt_band_scheme(
    sample_rate: float,
    min_period: float = 0.005,
    max_period: float = 5000.0,
    periods_per_decade: float = 10.0,
    window: int = 128,
    factor: int = 4,
    notch_frequencies: tuple = (),
    notch_fraction: float = 0.08,
) -> dict:
    """Build kwargs for aurora's ConfigCreator.create_from_kernel_dataset.

    `notch_frequencies` (Hz, e.g. mains at 50 and its harmonics) carve a
    guard of +-`notch_fraction` out of any band touching them, so no band
    integrates energy from those lines.
    Returns {"band_edges", "decimation_factors", "num_samples_window"}.

    Raises ValueError, naming the level and the band, when a band of the
    even layout is narrower than one FFT harmonic spacing of its level (the
    lowest band of a level spans k_min (factor**(1/n) - 1) harmonics): such a
    band may hold no harmonic at all, and aurora then stops in mt_metadata
    with a bare IndexError (docs/upstream_issues.md 20), while with any
    notch listed `_apply_notches` drops it silently as a sliver. At 10 Hz a
    `min_period` of 2 s did both: 13 of 41 periods left, or the crash.
    """
    f_top = min(1.0 / min_period, 0.25 * sample_rate)
    f_floor = 1.0 / max_period
    if f_floor >= f_top:
        raise ValueError("max_period must exceed min_period")

    # lowest band edge in units of FFT harmonics (same at every level)
    k_min = f_top * window / (factor * sample_rate)
    if k_min < 1.5:
        raise ValueError(
            f"lowest band edge would sit at FFT harmonic {k_min:.2f}; "
            f"increase window or min_period"
        )

    band_edges: dict[int, np.ndarray] = {}
    level = 0
    while True:
        f_hi = f_top / factor**level
        f_lo = max(f_hi / factor, f_floor)
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
