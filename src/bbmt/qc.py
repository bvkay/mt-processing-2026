"""QC products built on the processing band scheme.

`band_coherence` computes magnitude-squared coherence between two channels,
band-averaged into the same decimation levels and bands the TF estimation
uses, so QC plots share the TF plots' period axis. Works on raw counts:
coherence is invariant to per-channel scaling.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from scipy.signal import csd, decimate, welch


def load_channel(mth5_path: Path, survey_name: str, station: str, run: str, comp: str):
    """Return (data, start_timestamp, sample_rate) for one channel."""
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    try:
        ch = m.get_channel(station, run, comp, survey_name)
        data = ch.hdf5_dataset[:].astype("float64")
        start = pd.Timestamp(ch.metadata.time_period.start)
        sr = float(ch.metadata.sample_rate)
    finally:
        m.close_mth5()
    return data, start, sr


def longest_run(mth5_path: Path, survey_name: str, station: str) -> str:
    """Run id with the most samples for a station."""
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    try:
        st = m.get_station(station, survey=survey_name)
        best, best_len = None, -1.0
        for run_id in st.groups_list:
            rg = st.get_run(run_id)
            t = rg.metadata.time_period
            length = (pd.Timestamp(t.end) - pd.Timestamp(t.start)).total_seconds()
            if length > best_len:
                best, best_len = run_id, length
    finally:
        m.close_mth5()
    return best


def align(channels: list[tuple[np.ndarray, pd.Timestamp, float]]) -> list[np.ndarray]:
    """Slice channels (all same sample rate, ms-aligned grids) to their common span."""
    srs = {sr for _, _, sr in channels}
    if len(srs) != 1:
        raise ValueError(f"mixed sample rates: {srs}")
    sr = srs.pop()
    t0 = max(s for _, s, _ in channels)
    t1 = min(s + pd.Timedelta(seconds=(len(d) - 1) / sr) for d, s, _ in channels)
    if t1 <= t0:
        raise ValueError("channels do not overlap")
    out = []
    for d, s, _ in channels:
        i0 = int(round((t0 - s).total_seconds() * sr))
        n = int(round((t1 - t0).total_seconds() * sr)) + 1
        out.append(d[i0 : i0 + n])
    n_min = min(len(a) for a in out)
    return [a[:n_min] for a in out]


def _band_average(freqs: np.ndarray, spec: np.ndarray, edges: np.ndarray) -> np.ndarray:
    out = []
    for a, b in edges:
        mask = (freqs >= a) & (freqs < b)
        out.append(spec[mask].mean() if mask.any() else np.nan)
    return np.asarray(out)


def band_coherence(x: np.ndarray, y: np.ndarray, sample_rate: float, scheme: dict):
    """Band-averaged squared coherence over the scheme's decimation cascade.

    Returns (period_centers, gamma2), concatenated across all levels.
    """
    window = scheme["num_samples_window"][0]
    factors = scheme["decimation_factors"]
    x = x - x.mean()
    y = y - y.mean()
    periods: list[float] = []
    g2: list[float] = []
    for level in sorted(scheme["band_edges"].keys()):
        edges = np.asarray(scheme["band_edges"][level])
        if int(level) > 0:
            q = factors[int(level)]
            x = decimate(x, q, ftype="fir", zero_phase=True)
            y = decimate(y, q, ftype="fir", zero_phase=True)
        sr = sample_rate / np.prod(factors[1 : int(level) + 1]) if int(level) > 0 else sample_rate
        if x.size < 4 * window:
            logger.warning(f"level {level}: too few samples ({x.size}), stopping")
            break
        f, sxy = csd(x, y, fs=sr, nperseg=window)
        _, sxx = welch(x, fs=sr, nperseg=window)
        _, syy = welch(y, fs=sr, nperseg=window)
        sxy_b = _band_average(f, sxy, edges)
        sxx_b = _band_average(f, sxx.astype("float64"), edges)
        syy_b = _band_average(f, syy.astype("float64"), edges)
        with np.errstate(divide="ignore", invalid="ignore"):
            gamma2 = np.abs(sxy_b) ** 2 / (sxx_b * syy_b)
        periods.extend(1.0 / np.sqrt(edges[:, 0] * edges[:, 1]))
        g2.extend(gamma2)
    return np.asarray(periods), np.asarray(g2)
