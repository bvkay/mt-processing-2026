"""Decimation and frequency-band schemes for aurora processing.

`lemimt_band_scheme` lays out bands lemimt-style: an even spread of periods in
log space (~10 per decade) from `min_period` out to `max_period`, across
cascaded factor-4 decimation levels. Each level covers one factor-4 slice of
frequency, so band positions relative to the FFT harmonics are identical at
every level (lowest edge sits a safe ~6 harmonics above DC by construction).
"""

from __future__ import annotations

import numpy as np


def lemimt_band_scheme(
    sample_rate: float,
    min_period: float = 0.005,
    max_period: float = 5000.0,
    periods_per_decade: float = 10.0,
    window: int = 128,
    factor: int = 4,
) -> dict:
    """Build kwargs for aurora's ConfigCreator.create_from_kernel_dataset.

    Returns {"band_edges", "decimation_factors", "num_samples_window"}.
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
        band_edges[level] = np.column_stack([edges[:-1], edges[1:]])
        if f_lo <= f_floor or level >= 15:
            break
        level += 1

    decimation_factors = [1] + [factor] * (len(band_edges) - 1)
    return {
        "band_edges": band_edges,
        "decimation_factors": decimation_factors,
        "num_samples_window": window,
    }
