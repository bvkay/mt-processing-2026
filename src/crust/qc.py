# -*- coding: utf-8 -*-
"""
QC products built on the processing band scheme

`band_coherence` computes the magnitude-squared coherence between two
channels, band-averaged into the same decimation levels and bands the TF
estimation uses, so QC plots share the period axis of the TF plots. It works
on raw counts, since coherence is invariant to per-channel scaling.

The loaders (`load_channel`, `longest_run`, `run_periods`,
`best_overlap_runs`) open MTH5 archives read-only.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from scipy.signal import csd, decimate, welch


def load_channel(mth5_path: Path, survey_name: str, station: str, run: str, comp: str):
    """Load one channel from an MTH5 archive.

    Args:
        mth5_path (Path): MTH5 file, opened read-only.
        survey_name (str): Survey id.
        station (str): Station id.
        run (str): Run id.
        comp (str): Channel component, for example ``"ex"`` or ``"hy"``.

    Returns:
        tuple: ``(data, start, sample_rate)``: float64 samples, start time as
        a pandas Timestamp, and sample rate in Hz.
    """
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    try:
        ch = m.get_channel(station, run, comp, survey_name)
        data = ch.hdf5_dataset[:].astype("float64")
        start = pd.Timestamp(str(ch.metadata.time_period.start))
        sr = float(ch.metadata.sample_rate)
    finally:
        m.close_mth5()
    return data, start, sr


def longest_run(mth5_path: Path, survey_name: str, station: str) -> str:
    """Return the id of the longest run of a station.

    Args:
        mth5_path (Path): MTH5 file, opened read-only.
        survey_name (str): Survey id.
        station (str): Station id.

    Returns:
        str: Run id with the longest time period.
    """
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    try:
        st = m.get_station(station, survey=survey_name)
        best, best_len = None, -1.0
        for run_id in st.groups_list:
            rg = st.get_run(run_id)
            t = rg.metadata.time_period
            length = (pd.Timestamp(str(t.end)) - pd.Timestamp(str(t.start))).total_seconds()
            if length > best_len:
                best, best_len = run_id, length
    finally:
        m.close_mth5()
    return best


def run_periods(mth5_path: Path, survey_name: str, station: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Map each run group of a station to its time period.

    Auxiliary station-level groups written by aurora and mth5 (Features,
    Fourier_Coefficients, Transfer_Functions, ...) come back with a null
    1980-01-01 period, as in `longest_run`, so they lose any overlap search.

    Args:
        mth5_path (Path): MTH5 file, opened read-only.
        survey_name (str): Survey id.
        station (str): Station id.

    Returns:
        dict: Run id to ``(start, end)`` pandas Timestamps.
    """
    m = MTH5()
    m.open_mth5(Path(mth5_path), mode="r")
    try:
        st = m.get_station(station, survey=survey_name)
        periods = {}
        for run_id in st.groups_list:
            t = st.get_run(run_id).metadata.time_period
            periods[run_id] = (pd.Timestamp(str(t.start)), pd.Timestamp(str(t.end)))
    finally:
        m.close_mth5()
    return periods


def best_overlap_runs(
    mth5_a: Path, survey_name: str, station_a: str, mth5_b: Path, station_b: str
) -> tuple[str, str, float]:
    """Find the pair of runs, one per station, that overlap the most.

    Where `longest_run` looks at a single station, this picks the run pair
    that shares the most time. It suits a local/remote or local/stack
    comparison where each station may be split into several runs, for
    example at a run boundary forced by a file-timing anomaly (see
    scripts/timing_qc.py).

    Args:
        mth5_a (Path): MTH5 file of the first station.
        survey_name (str): Survey id, shared by both files.
        station_a (str): First station id.
        mth5_b (Path): MTH5 file of the second station.
        station_b (str): Second station id.

    Returns:
        tuple: ``(run_a, run_b, overlap_s)``. The overlap is negative when
        no pair overlaps.
    """
    periods_a = run_periods(mth5_a, survey_name, station_a)
    periods_b = run_periods(mth5_b, survey_name, station_b)
    best_a = best_b = None
    best_overlap = -1.0
    for run_a, (a0, a1) in periods_a.items():
        for run_b, (b0, b1) in periods_b.items():
            overlap = (min(a1, b1) - max(a0, b0)).total_seconds()
            if overlap > best_overlap:
                best_a, best_b, best_overlap = run_a, run_b, overlap
    return best_a, best_b, best_overlap


def align(channels: list[tuple[np.ndarray, pd.Timestamp, float]]) -> list[np.ndarray]:
    """Slice channels to their common time span.

    Args:
        channels (list of tuple): ``(data, start, sample_rate)`` tuples as
            returned by `load_channel`, all at one sample rate and on
            millisecond-aligned grids.

    Returns:
        list of np.ndarray: The sliced arrays, all of one length.

    Raises:
        ValueError: If the sample rates differ or the channels do not
            overlap.
    """
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
    """Average a spectrum over each band in `edges`; NaN for an empty band."""
    out = []
    for a, b in edges:
        mask = (freqs >= a) & (freqs < b)
        out.append(spec[mask].mean() if mask.any() else np.nan)
    return np.asarray(out)


def band_coherence(x: np.ndarray, y: np.ndarray, sample_rate: float, scheme: dict):
    """Compute band-averaged squared coherence over a decimation cascade.

    Both series are demeaned, then decimated level by level with a
    zero-phase FIR filter. On each level the cross- and auto-spectra from
    Welch's method are averaged over the level's bands. The cascade stops
    early when a level has fewer than four windows of data.

    Args:
        x (np.ndarray): First channel.
        y (np.ndarray): Second channel, aligned with `x`.
        sample_rate (float): Sample rate of `x` and `y` in Hz.
        scheme (dict): Band scheme as returned by
            `crust.bands.build_band_scheme`.

    Returns:
        tuple: ``(period_centers, gamma2)`` across all levels, sorted by
        period. Band centres are geometric means of the band edges.
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
    periods = np.asarray(periods)
    g2 = np.asarray(g2)
    order = np.argsort(periods)
    return periods[order], g2[order]
